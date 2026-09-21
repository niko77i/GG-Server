"""TikTok 广告账户 API 路由 — 账户管理 / 充值 / 同步 / 回收原因"""
import json
import datetime

from flask import Blueprint, request
from flask_jwt_extended import jwt_required

from .helpers import ok, err, get_uid, get_db, parse_body
from .decorators import tt_required

tt_accounts_bp = Blueprint('tt_accounts', __name__)


def _get_role(db, uid):
    user = db.execute("SELECT role FROM users WHERE id=?", (uid,)).fetchone()
    return user['role'] if user else 'user'


def _get_tt_sheet_id(db):
    row = db.execute("SELECT value FROM tags WHERE key='tt_sheet_id'").fetchone()
    return (row["value"] if row and row["value"] else "")


def _get_tt_sheet_mappings(db):
    row = db.execute("SELECT value FROM tags WHERE key='tt_sheet_mappings'").fetchone()
    if row and row["value"]:
        try:
            loaded = json.loads(row["value"])
            if isinstance(loaded, dict):
                return loaded
        except Exception:
            pass
    return {"accounts": "账户明细", "recharge": "充值表",
            "my_dashboard": "我的看板", "recycle": "回收户清单"}


def _resolve_agent_id(db, agent, agent_id):
    """agent_id 为 None 且有 agent 文本时，按 platform='tt' 查/插 agents。"""
    if agent_id is not None:
        return agent_id
    if not agent:
        return None
    existing = db.execute(
        "SELECT id FROM agents WHERE name=? AND platform='tt'", (agent,)
    ).fetchone()
    if existing:
        return existing["id"]
    db.execute("INSERT INTO agents(name, owner_id, platform) VALUES(?,?, 'tt')", (agent, 1))
    return db.execute("SELECT last_insert_rowid()").fetchone()[0]


def _resolve_status_id(db, status, status_id):
    """status_id 为 None 且有 status 文本时，按 platform='tt' 查/插 account_statuses。"""
    if status_id is not None:
        return status_id
    if not status:
        return None
    existing = db.execute(
        "SELECT id FROM account_statuses WHERE name=? AND platform='tt'", (status,)
    ).fetchone()
    if existing:
        return existing["id"]
    db.execute("INSERT INTO account_statuses(name, owner_id, platform) VALUES(?,?, 'tt')", (status, 1))
    return db.execute("SELECT last_insert_rowid()").fetchone()[0]


def _record_bc_change(db, account_row_id, new_bc_id, uid, change_type):
    if new_bc_id == 0 or new_bc_id == "0" or (isinstance(new_bc_id, str) and not new_bc_id.strip()):
        new_bc_id = None
    if not new_bc_id:
        return
    db.execute(
        "INSERT INTO tt_account_bc_history(account_id, old_bc_id, new_bc_id, changed_by, change_type) "
        "VALUES(?, NULL, ?, ?, ?)",
        (account_row_id, new_bc_id, uid, change_type))


# ==================== 广告账户 CRUD ====================

@tt_accounts_bp.route('/api/tt/accounts/create', methods=['POST'])
@jwt_required()
@tt_required
def create_account():
    db = get_db()
    uid = get_uid()
    data = parse_body()
    advertiser_id = str(data.get("advertiser_id") or "").strip()
    if not advertiser_id:
        return err("请提供广告账户 ID")
    if not advertiser_id.isdigit():
        return err("广告账户 ID 必须是纯数字")
    # 唯一冲突检测
    ex = db.execute(
        "SELECT a.id, u.display_name, u.username FROM tt_accounts a "
        "LEFT JOIN users u ON a.owner_id = u.id WHERE a.advertiser_id = ?",
        (advertiser_id,)
    ).fetchone()
    if ex:
        owner = ex["display_name"] or ex["username"] or "未知"
        return err(f"该广告账户已存在，归属人：{owner}", 409)

    bc_id = data.get("bc_id") or None
    if bc_id == "" or bc_id == 0 or bc_id == "0":
        bc_id = None
    agent_id = _resolve_agent_id(db, (data.get("agent") or "").strip(), data.get("agent_id"))
    status = (data.get("status") or "").strip() or "存活"
    status_id = _resolve_status_id(db, status, data.get("status_id"))
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    db.execute(
        "INSERT INTO tt_accounts(name, advertiser_id, bc_id, country, agent_id, timezone, "
        "consumption, status_id, acquired_date, remark, owner_id, created_at, updated_at) "
        "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
        ((data.get("name") or "").strip(), advertiser_id, bc_id,
         (data.get("country") or "").strip(), agent_id, (data.get("timezone") or "").strip(),
         (data.get("consumption") or "").strip(), status_id,
         (data.get("acquired_date") or None), (data.get("remark") or "").strip(),
         uid, now, now))
    db.commit()
    new_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]
    _record_bc_change(db, new_id, bc_id, uid, "create")
    db.commit()
    return ok({"id": new_id})


@tt_accounts_bp.route('/api/tt/accounts/lookup', methods=['GET'])
@jwt_required()
@tt_required
def lookup_account():
    db = get_db()
    advertiser_id = (request.args.get("advertiser_id") or "").strip()
    if not advertiser_id:
        return err("缺少 advertiser_id")
    row = db.execute(
        "SELECT a.id, a.name, a.advertiser_id, a.bc_id, a.agent_id, a.status_id, "
        "a.timezone, a.acquired_date, a.owner_id, "
        "b.name AS bc_name, st.name AS status_name, ag.name AS agent_name, "
        "u.username, u.display_name "
        "FROM tt_accounts a "
        "LEFT JOIN tt_bcs b ON a.bc_id = b.id "
        "LEFT JOIN account_statuses st ON a.status_id = st.id "
        "LEFT JOIN agents ag ON a.agent_id = ag.id "
        "LEFT JOIN users u ON a.owner_id = u.id "
        "WHERE a.advertiser_id = ?", (advertiser_id,)
    ).fetchone()
    if not row:
        return ok({"found": False})
    d = dict(row)
    d["found"] = True
    d["status"] = d.get("status_name") or ""
    d["agent"] = d.get("agent_name") or ""
    d["bc_name"] = d.get("bc_name") or ""
    d["owner_name"] = d.get("display_name") or d.get("username") or "未知"
    return ok(d)


@tt_accounts_bp.route('/api/tt/accounts/batch-lookup', methods=['POST'])
@jwt_required()
@tt_required
def batch_lookup_accounts():
    db = get_db()
    data = parse_body()
    ids = data.get("account_ids") or []
    if not ids or not isinstance(ids, list):
        return err("请提供 account_ids 列表")
    ids = [str(i).strip() for i in ids if str(i).strip()]
    found, not_found = [], []
    for aid in ids:
        row = db.execute(
            "SELECT a.id, a.advertiser_id, u.display_name, u.username "
            "FROM tt_accounts a LEFT JOIN users u ON a.owner_id = u.id "
            "WHERE a.advertiser_id = ?", (aid,)
        ).fetchone()
        if row:
            d = dict(row)
            d["owner"] = d.get("display_name") or d.get("username") or "未知"
            found.append(d)
        else:
            not_found.append(aid)
    return ok({"found": found, "not_found": not_found})


@tt_accounts_bp.route('/api/tt/accounts/list', methods=['GET'])
@jwt_required()
@tt_required
def list_accounts():
    db = get_db()
    uid = get_uid()
    role = _get_role(db, uid)

    page = request.args.get('page', 1, type=int)
    size = request.args.get('size', 50, type=int)
    search = (request.args.get('search') or '').strip()
    bc_id = (request.args.get('bc_id') or '').strip()
    agent_id = (request.args.get('agent_id') or '').strip()
    status_id = (request.args.get('status_id') or '').strip()
    timezone = (request.args.get('timezone') or '').strip()
    owner_id = (request.args.get('owner_id') or '').strip()

    where = ["a.deleted_at IS NULL"]
    params = []
    if role in ('developer', 'admin'):
        if owner_id:
            where.append("a.owner_id = ?")
            params.append(owner_id)
    else:
        where.append("a.owner_id = ?")
        params.append(uid)
    if search:
        where.append("(a.name LIKE ? OR a.advertiser_id LIKE ?)")
        params += [f"%{search}%", f"%{search}%"]
    if bc_id:
        where.append("a.bc_id = ?"); params.append(bc_id)
    if agent_id:
        where.append("a.agent_id = ?"); params.append(agent_id)
    if status_id:
        where.append("a.status_id = ?"); params.append(status_id)
    if timezone:
        where.append("a.timezone = ?"); params.append(timezone)

    where_clause = " AND ".join(where)
    offset = (page - 1) * size
    total = db.execute(
        f"SELECT COUNT(*) FROM tt_accounts a WHERE {where_clause}", params
    ).fetchone()[0]
    rows = db.execute(
        f"""SELECT a.*, b.name AS bc_name, ag.name AS agent_name, st.name AS status_name,
                   u.display_name AS owner_name
            FROM tt_accounts a
            LEFT JOIN tt_bcs b ON a.bc_id = b.id
            LEFT JOIN agents ag ON a.agent_id = ag.id
            LEFT JOIN account_statuses st ON a.status_id = st.id
            LEFT JOIN users u ON a.owner_id = u.id
            WHERE {where_clause}
            ORDER BY (a.bc_id IS NULL), a.bc_id, a.created_at DESC
            LIMIT ? OFFSET ?""",
        params + [size, offset]
    ).fetchall()
    items = [dict(r) for r in rows]
    for it in items:
        it['bc'] = it.get('bc_name') or ''
        it['agent'] = it.get('agent_name') or ''
        it['status'] = it.get('status_name') or '存活'
        it['owner'] = it.get('owner_name') or ''

    # 各状态计数（不含 status 筛选，展示所有状态数量）
    sc_where2 = ["a.deleted_at IS NULL"]
    sc_params2 = []
    if role in ('developer', 'admin'):
        if owner_id:
            sc_where2.append("a.owner_id = ?"); sc_params2.append(owner_id)
    else:
        sc_where2.append("a.owner_id = ?"); sc_params2.append(uid)
    if search:
        sc_where2.append("(a.name LIKE ? OR a.advertiser_id LIKE ?)")
        sc_params2 += [f"%{search}%", f"%{search}%"]
    if bc_id:
        sc_where2.append("a.bc_id = ?"); sc_params2.append(bc_id)
    if agent_id:
        sc_where2.append("a.agent_id = ?"); sc_params2.append(agent_id)
    if timezone:
        sc_where2.append("a.timezone = ?"); sc_params2.append(timezone)
    status_counts = {}
    for r in db.execute(
        "SELECT COALESCE(st.name, '存活') AS status, COUNT(*) AS cnt "
        "FROM tt_accounts a LEFT JOIN account_statuses st ON a.status_id = st.id "
        "WHERE " + " AND ".join(sc_where2) + " GROUP BY st.name",
        sc_params2
    ).fetchall():
        s = r["status"] or "存活"
        status_counts[s] = status_counts.get(s, 0) + r["cnt"]

    return ok({'items': items, 'total': total, 'page': page, 'size': size,
               'status_counts': status_counts})


@tt_accounts_bp.route('/api/tt/accounts/<int:aid>', methods=['PUT'])
@jwt_required()
@tt_required
def update_account(aid):
    db = get_db()
    uid = get_uid()
    role = _get_role(db, uid)
    data = parse_body()
    row = db.execute(
        "SELECT a.*, st.name AS status_name FROM tt_accounts a "
        "LEFT JOIN account_statuses st ON a.status_id = st.id WHERE a.id=?", (aid,)
    ).fetchone()
    if not row:
        return err("账户不存在", 404)
    if role not in ('developer', 'admin') and row["owner_id"] != uid:
        return err("无权限", 403)

    editable = ["name", "country", "timezone", "consumption", "agent_id", "status_id",
                "acquired_date", "death_date", "remark"]
    for f in editable:
        if f in data and data[f] is not None:
            db.execute(f"UPDATE tt_accounts SET {f}=? WHERE id=?",
                       (str(data[f]).strip() if isinstance(data[f], str) else data[f], aid))

    # agent/status 文本回退
    if "agent" in data or "agent_id" in data:
        agent_id = _resolve_agent_id(db, (data.get("agent") or "").strip(), data.get("agent_id"))
        if agent_id is not None:
            db.execute("UPDATE tt_accounts SET agent_id=? WHERE id=?", (agent_id, aid))
    if "status" in data or "status_id" in data:
        status_id = _resolve_status_id(db, (data.get("status") or "").strip(), data.get("status_id"))
        if status_id is not None:
            # 状态变更时间
            new_status_name = db.execute(
                "SELECT name FROM account_statuses WHERE id=?", (status_id,)
            ).fetchone()
            new_status_name = new_status_name["name"] if new_status_name else ""
            if new_status_name and new_status_name != (row["status_name"] or ""):
                db.execute("UPDATE tt_accounts SET status_changed_date=datetime('now','localtime') WHERE id=?", (aid,))
            if new_status_name == "死亡":
                db.execute("UPDATE tt_accounts SET death_date=date('now','localtime') WHERE id=?", (aid,))
            elif (row["status_name"] or "") == "死亡":
                db.execute("UPDATE tt_accounts SET death_date='' WHERE id=?", (aid,))
            db.execute("UPDATE tt_accounts SET status_id=? WHERE id=?", (status_id, aid))
            _trigger_recycle_if_dead(db, uid, row["advertiser_id"], status_id,
                                     (data.get("recycle_reason") or "").strip())

    # BC 变更（记录历史）
    if "bc_id" in data:
        bc_id = data["bc_id"]
        if bc_id in (None, 0, "0", "") or (isinstance(bc_id, str) and not bc_id.strip()):
            bc_id = None
        old_bc = row["bc_id"]
        if (bc_id or None) != (old_bc or None):
            db.execute(
                "INSERT INTO tt_account_bc_history(account_id, old_bc_id, new_bc_id, changed_by, change_type) "
                "VALUES(?,?,?,?,?)", (aid, old_bc, bc_id, uid, "manual"))
        db.execute("UPDATE tt_accounts SET bc_id=? WHERE id=?", (bc_id, aid))

    db.execute("UPDATE tt_accounts SET updated_at=datetime('now','localtime') WHERE id=?", (aid,))
    db.commit()
    return ok()


@tt_accounts_bp.route('/api/tt/accounts/batch-create', methods=['POST'])
@jwt_required()
@tt_required
def batch_create_accounts():
    db = get_db()
    uid = get_uid()
    data = parse_body()
    account_ids = data.get("account_ids") or []
    if not account_ids or not isinstance(account_ids, list):
        return err("请提供 account_ids 列表")
    common = {
        "name_prefix": (data.get("name_prefix") or "").strip(),
        "bc_id": data.get("bc_id") or None,
        "timezone": (data.get("timezone") or "").strip(),
        "agent": (data.get("agent") or "").strip(),
        "agent_id": data.get("agent_id") or None,
        "status": (data.get("status") or "存活").strip(),
        "status_id": data.get("status_id") or None,
        "country": (data.get("country") or "").strip(),
        "acquired_date": (data.get("acquired_date") or None),
    }
    overrides = data.get("overrides") or {}
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    created, skipped = [], []
    for aid in account_ids:
        aid = str(aid).strip()
        if not aid:
            continue
        if not aid.isdigit():
            skipped.append({"advertiser_id": aid, "reason": "ID 必须是纯数字"})
            continue
        ov = overrides.get(aid, {})
        name = (ov.get("name") or "").strip() or (
            (common["name_prefix"] + " " + aid).strip() if common["name_prefix"] else aid)
        bc_id = ov.get("bc_id") if "bc_id" in ov else common["bc_id"]
        if bc_id in (0, "0", ""):
            bc_id = None
        timezone = ov.get("timezone") if "timezone" in ov else common["timezone"]
        country = ov.get("country") if "country" in ov else common["country"]
        agent_id = _resolve_agent_id(db, ov.get("agent", common["agent"]), ov.get("agent_id", common["agent_id"]))
        status_id = _resolve_status_id(db, ov.get("status", common["status"]), ov.get("status_id", common["status_id"]))
        acquired_date = ov.get("acquired_date") if "acquired_date" in ov else common["acquired_date"]
        try:
            db.execute(
                "INSERT INTO tt_accounts(name, advertiser_id, bc_id, country, agent_id, timezone, "
                "status_id, acquired_date, owner_id, created_at, updated_at) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                (name, aid, bc_id, country, agent_id, timezone, status_id,
                 acquired_date, uid, now, now))
            db.commit()
            created.append(aid)
            new_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]
            _record_bc_change(db, new_id, bc_id, uid, "import")
            db.commit()
        except Exception as e:
            err_msg = str(e).lower()
            if "advertiser_id" in err_msg or "unique" in err_msg:
                skipped.append({"advertiser_id": aid, "reason": "已存在"})
            else:
                skipped.append({"advertiser_id": aid, "reason": str(e)})
    return ok({"created": len(created), "created_ids": created, "skipped": skipped})


@tt_accounts_bp.route('/api/tt/accounts/batch-update', methods=['POST'])
@jwt_required()
@tt_required
def batch_update_accounts():
    db = get_db()
    uid = get_uid()
    data = parse_body()
    ids = data.get("ids") or []
    field = (data.get("field") or "").strip()
    value = data.get("value")
    if not ids or not field:
        return err("缺少参数")
    allowed = ["status_id", "agent_id", "bc_id", "timezone"]
    if field not in allowed:
        return err(f"不允许修改字段: {field}")
    if field == "bc_id" and value in (None, 0, "0", ""):
        value = None
    role = _get_role(db, uid)
    for aid in ids:
        # owner 权限校验
        if role not in ('developer', 'admin'):
            r = db.execute("SELECT owner_id, bc_id, advertiser_id FROM tt_accounts WHERE id=?", (aid,)).fetchone()
            if not r or r["owner_id"] != uid:
                continue
        else:
            r = db.execute("SELECT owner_id, bc_id, advertiser_id FROM tt_accounts WHERE id=?", (aid,)).fetchone()
            if not r:
                continue
        if field == "bc_id":
            if (value or None) != (r["bc_id"] or None):
                db.execute(
                    "INSERT INTO tt_account_bc_history(account_id, old_bc_id, new_bc_id, changed_by, change_type) "
                    "VALUES(?,?,?,?,?)", (aid, r["bc_id"], value, uid, "batch"))
        if field == "status_id" and value:
            st_name = db.execute("SELECT name FROM account_statuses WHERE id=?", (value,)).fetchone()
            if st_name and st_name["name"] == "死亡":
                db.execute("UPDATE tt_accounts SET death_date=date('now','localtime') WHERE id=?", (aid,))
            db.execute("UPDATE tt_accounts SET status_changed_date=datetime('now','localtime') WHERE id=?", (aid,))
            _trigger_recycle_if_dead(db, uid, r["advertiser_id"], value,
                                     (data.get("recycle_reason") or "").strip())
        db.execute(f"UPDATE tt_accounts SET {field}=?, updated_at=datetime('now','localtime') WHERE id=?",
                   (value, aid))
    db.commit()
    return ok({"updated": len(ids)})


@tt_accounts_bp.route('/api/tt/accounts/<int:aid>/reassign', methods=['PUT'])
@jwt_required()
@tt_required
def reassign_account(aid):
    db = get_db()
    uid = get_uid()
    data = parse_body()
    existing = db.execute(
        "SELECT a.*, u.username, u.display_name FROM tt_accounts a "
        "LEFT JOIN users u ON a.owner_id = u.id WHERE a.id = ?", (aid,)
    ).fetchone()
    if not existing:
        return err("账户不存在", 404)
    if int(existing["owner_id"] or 0) == uid:
        return err("该账户已属于当前用户，无需转移", 409)
    db.execute("UPDATE tt_accounts SET owner_id=?, updated_at=datetime('now','localtime') WHERE id=?",
               (uid, aid))
    for f in ["name", "country", "timezone", "agent_id", "status_id", "acquired_date", "consumption"]:
        if f in data and data[f] is not None:
            db.execute(f"UPDATE tt_accounts SET {f}=? WHERE id=?",
                       (str(data[f]).strip() if isinstance(data[f], str) else data[f], aid))
    if "bc_id" in data:
        bc_id = data["bc_id"]
        if bc_id in (None, 0, "0", "") or (isinstance(bc_id, str) and not bc_id.strip()):
            bc_id = None
        db.execute(
            "INSERT INTO tt_account_bc_history(account_id, old_bc_id, new_bc_id, changed_by, change_type) "
            "VALUES(?,?,?,?,?)", (aid, existing["bc_id"], bc_id, uid, "reassign"))
        db.execute("UPDATE tt_accounts SET bc_id=? WHERE id=?", (bc_id, aid))
    db.commit()
    return ok({"message": f"账户「{existing['name'] or existing['advertiser_id']}」已转移至当前用户"})


@tt_accounts_bp.route('/api/tt/accounts/<int:aid>', methods=['DELETE'])
@jwt_required()
@tt_required
def delete_account(aid):
    db = get_db()
    uid = get_uid()
    role = _get_role(db, uid)
    ac = db.execute("SELECT id, owner_id FROM tt_accounts WHERE id=? AND deleted_at IS NULL", (aid,)).fetchone()
    if not ac:
        return err("账户不存在或已删除", 404)
    if role not in ('developer', 'admin') and ac["owner_id"] != uid:
        return err("无权限", 403)
    db.execute("UPDATE tt_accounts SET deleted_at=datetime('now','localtime'), "
               "updated_at=datetime('now','localtime') WHERE id=?", (aid,))
    db.commit()
    return ok()


@tt_accounts_bp.route('/api/tt/accounts/batch-delete', methods=['POST'])
@jwt_required()
@tt_required
def batch_delete_accounts():
    db = get_db()
    uid = get_uid()
    role = _get_role(db, uid)
    ids = parse_body().get("ids") or []
    if not ids:
        return err("未选择账户")
    for aid in ids:
        if role in ('developer', 'admin'):
            db.execute("UPDATE tt_accounts SET deleted_at=datetime('now','localtime') WHERE id=? AND deleted_at IS NULL", (aid,))
        else:
            db.execute("UPDATE tt_accounts SET deleted_at=datetime('now','localtime') WHERE id=? AND owner_id=? AND deleted_at IS NULL", (aid, uid))
    db.commit()
    return ok({"deleted": len(ids)})


@tt_accounts_bp.route('/api/tt/accounts/<int:aid>/restore', methods=['POST'])
@jwt_required()
@tt_required
def restore_account(aid):
    db = get_db()
    uid = get_uid()
    role = _get_role(db, uid)
    ac = db.execute("SELECT owner_id FROM tt_accounts WHERE id=? AND deleted_at IS NOT NULL", (aid,)).fetchone()
    if not ac:
        return err("账户不存在或未被删除", 404)
    if role not in ('developer', 'admin') and ac["owner_id"] != uid:
        return err("无权限", 403)
    db.execute("UPDATE tt_accounts SET deleted_at=NULL, updated_at=datetime('now','localtime') WHERE id=?", (aid,))
    db.commit()
    return ok()


@tt_accounts_bp.route('/api/tt/accounts/<int:aid>/permanent', methods=['DELETE'])
@jwt_required()
@tt_required
def permanent_delete_account(aid):
    db = get_db()
    uid = get_uid()
    role = _get_role(db, uid)
    ac = db.execute("SELECT owner_id FROM tt_accounts WHERE id=? AND deleted_at IS NOT NULL", (aid,)).fetchone()
    if not ac:
        return err("账户不存在或未被删除", 404)
    if role not in ('developer', 'admin') and ac["owner_id"] != uid:
        return err("无权限", 403)
    db.execute("DELETE FROM tt_recharge_records WHERE account_id IN "
               "(SELECT advertiser_id FROM tt_accounts WHERE id=?)", (aid,))
    db.execute("DELETE FROM tt_account_bc_history WHERE account_id=?", (aid,))
    db.execute("DELETE FROM tt_accounts WHERE id=?", (aid,))
    db.commit()
    return ok()


@tt_accounts_bp.route('/api/tt/accounts/deleted', methods=['GET'])
@jwt_required()
@tt_required
def deleted_accounts_list():
    db = get_db()
    uid = get_uid()
    role = _get_role(db, uid)
    if role in ('developer', 'admin'):
        rows = db.execute(
            "SELECT a.id, a.name, a.advertiser_id, a.deleted_at, "
            "ag.name AS agent_name, st.name AS status_name "
            "FROM tt_accounts a LEFT JOIN agents ag ON a.agent_id = ag.id "
            "LEFT JOIN account_statuses st ON a.status_id = st.id "
            "WHERE a.deleted_at IS NOT NULL ORDER BY a.deleted_at DESC").fetchall()
    else:
        rows = db.execute(
            "SELECT a.id, a.name, a.advertiser_id, a.deleted_at, "
            "ag.name AS agent_name, st.name AS status_name "
            "FROM tt_accounts a LEFT JOIN agents ag ON a.agent_id = ag.id "
            "LEFT JOIN account_statuses st ON a.status_id = st.id "
            "WHERE a.owner_id=? AND a.deleted_at IS NOT NULL ORDER BY a.deleted_at DESC",
            (uid,)).fetchall()
    items = []
    for r in rows:
        d = dict(r)
        d["agent"] = d.get("agent_name") or ""
        d["status"] = d.get("status_name") or ""
        items.append(d)
    return ok({"items": items})


@tt_accounts_bp.route('/api/tt/accounts/<int:aid>/bc-history', methods=['GET'])
@jwt_required()
@tt_required
def bc_history(aid):
    db = get_db()
    uid = get_uid()
    role = _get_role(db, uid)
    ac = db.execute("SELECT owner_id FROM tt_accounts WHERE id=?", (aid,)).fetchone()
    if not ac:
        return err("账户不存在", 404)
    if role not in ('developer', 'admin') and ac["owner_id"] != uid:
        return err("无权限", 403)
    rows = db.execute(
        "SELECT h.id, h.old_bc_id, h.new_bc_id, h.change_type, h.created_at, "
        "u.display_name AS changed_by_name, "
        "b1.name AS old_bc_name, b2.name AS new_bc_name "
        "FROM tt_account_bc_history h "
        "LEFT JOIN users u ON h.changed_by = u.id "
        "LEFT JOIN tt_bcs b1 ON h.old_bc_id = b1.id "
        "LEFT JOIN tt_bcs b2 ON h.new_bc_id = b2.id "
        "WHERE h.account_id=? ORDER BY h.created_at DESC", (aid,)).fetchall()
    items = []
    for r in rows:
        d = dict(r)
        d["old_bc"] = d.get("old_bc_name") or ""
        d["new_bc"] = d.get("new_bc_name") or ""
        d["changed_by"] = d.get("changed_by_name") or ""
        items.append(d)
    return ok({"items": items})


@tt_accounts_bp.route('/api/tt/accounts/<int:aid>/bc-history/<int:hid>', methods=['DELETE'])
@jwt_required()
@tt_required
def delete_bc_history(aid, hid):
    db = get_db()
    uid = get_uid()
    role = _get_role(db, uid)
    if role not in ('developer', 'admin'):
        return err("权限不足", 403)
    db.execute("DELETE FROM tt_account_bc_history WHERE id=? AND account_id=?", (hid, aid))
    db.commit()
    return ok()


# ==================== 充值 ====================

def _recharge_sheet_name(db):
    mappings = _get_tt_sheet_mappings(db)
    return (mappings.get("recharge") or "").strip() or "充值表"


def _append_recharge_background(db, uid, sheet_id, sheet_name, rows, rids):
    """后台异步写充值表；成功置 sheets_synced=1，失败写 sheets_error。"""
    from main import _GOOGLE_SHEETS_CONFIG, _sync_sheets_background

    def _do_sync():
        import google_sheets_service as gs
        service = gs.build_service(_GOOGLE_SHEETS_CONFIG["credentials_path"])
        gs.append_recharge(service, sheet_id, sheet_name, rows)

    def _on_fail(status, err_msg):
        _db = get_db()
        if status == "synced":
            for rid in rids:
                _db.execute("UPDATE tt_recharge_records SET sheets_synced=1, sheets_error='' WHERE id=?", (rid,))
        else:
            for rid in rids:
                _db.execute("UPDATE tt_recharge_records SET sheets_error=? WHERE id=?", (err_msg, rid))
        _db.commit()

    _sync_sheets_background(_do_sync, _on_fail)


@tt_accounts_bp.route('/api/tt/accounts/<int:aid>/recharge-records', methods=['GET'])
@jwt_required()
@tt_required
def recharge_records(aid):
    db = get_db()
    uid = get_uid()
    ac = db.execute("SELECT advertiser_id, owner_id FROM tt_accounts WHERE id=? AND deleted_at IS NULL",
                    (aid,)).fetchone()
    if not ac:
        return err("账户不存在", 404)
    role = _get_role(db, uid)
    if role not in ('developer', 'admin') and ac["owner_id"] != uid:
        return err("无权限", 403)
    rows = db.execute(
        "SELECT r.*, ag.name AS agent_name, u.display_name AS operator_name "
        "FROM tt_recharge_records r "
        "LEFT JOIN agents ag ON r.agent_id = ag.id "
        "LEFT JOIN users u ON r.created_by = u.id "
        "WHERE r.account_id=? ORDER BY r.created_at DESC", (ac["advertiser_id"],)).fetchall()
    items = []
    for r in rows:
        d = dict(r)
        d["agent"] = d.get("agent_name") or ""
        d["operator"] = d.get("operator_name") or d.get("operator") or ""
        items.append(d)
    return ok({"items": items})


@tt_accounts_bp.route('/api/tt/recharge/submit', methods=['POST'])
@jwt_required()
@tt_required
def recharge_submit():
    db = get_db()
    uid = get_uid()
    data = parse_body()
    account_id = (data.get("account_id") or "").strip()
    amount = str(data.get("amount") or "").strip()
    if not account_id or not amount:
        return err("缺少 account_id 或 amount")
    # 校验账户存在且属于当前用户（或 admin）
    role = _get_role(db, uid)
    ac = db.execute("SELECT advertiser_id, status_id, agent_id, owner_id FROM tt_accounts WHERE advertiser_id=? AND deleted_at IS NULL",
                    (account_id,)).fetchone()
    if not ac:
        return err("账户不存在", 404)
    if role not in ('developer', 'admin') and ac["owner_id"] != uid:
        return err("无权限", 403)
    # 仅「存活」状态可充值
    st = db.execute("SELECT name FROM account_statuses WHERE id=?", (ac["status_id"],)).fetchone()
    if st and st["name"] != "存活":
        return err(f"仅「存活」状态可充值，当前状态：{st['name']}")

    agent_id = _resolve_agent_id(db, (data.get("agent") or "").strip(), data.get("agent_id"))
    agent_name = db.execute("SELECT name FROM agents WHERE id=?", (agent_id,)).fetchone()
    agent_name = agent_name["name"] if agent_name else ""
    user = db.execute("SELECT display_name FROM users WHERE id=?", (uid,)).fetchone()
    operator = (user["display_name"] or "") if user else ""
    status = st["name"] if st else ""
    db.execute(
        "INSERT INTO tt_recharge_records(account_id, amount, agent_id, operator, status, created_by, sheets_synced) "
        "VALUES(?,?,?,?,?,?,0)",
        (account_id, amount, agent_id, operator, status, uid))
    db.commit()
    rid = db.execute("SELECT last_insert_rowid()").fetchone()[0]

    sheet_id = _get_tt_sheet_id(db)
    sheet_name = _recharge_sheet_name(db)
    if sheet_id:
        rows = [{"account_id": account_id, "amount": amount, "agent": agent_name,
                 "operator": operator, "status": status}]
        _append_recharge_background(db, uid, sheet_id, sheet_name, rows, [rid])
    return ok({"id": rid})


@tt_accounts_bp.route('/api/tt/recharge/batch-submit', methods=['POST'])
@jwt_required()
@tt_required
def recharge_batch_submit():
    db = get_db()
    uid = get_uid()
    data = parse_body()
    items = data.get("items") or []
    if not items:
        return err("缺少 items")
    user = db.execute("SELECT display_name FROM users WHERE id=?", (uid,)).fetchone()
    operator = (user["display_name"] or "") if user else ""
    role = _get_role(db, uid)
    rids, rows = [], []
    for it in items:
        account_id = (it.get("account_id") or "").strip()
        amount = str(it.get("amount") or "").strip()
        if not account_id or not amount:
            continue
        ac = db.execute("SELECT agent_id, status_id, owner_id FROM tt_accounts WHERE advertiser_id=? AND deleted_at IS NULL",
                        (account_id,)).fetchone()
        if not ac:
            continue
        if role not in ('developer', 'admin') and ac["owner_id"] != uid:
            continue
        agent_id = _resolve_agent_id(db, (it.get("agent") or "").strip(), it.get("agent_id"))
        agent_name = db.execute("SELECT name FROM agents WHERE id=?", (agent_id,)).fetchone()
        agent_name = agent_name["name"] if agent_name else ""
        st = db.execute("SELECT name FROM account_statuses WHERE id=?", (ac["status_id"],)).fetchone()
        if st and st["name"] != "存活":
            continue
        status = st["name"] if st else ""
        db.execute(
            "INSERT INTO tt_recharge_records(account_id, amount, agent_id, operator, status, created_by, sheets_synced) "
            "VALUES(?,?,?,?,?,?,0)",
            (account_id, amount, agent_id, operator, status, uid))
        db.commit()
        rid = db.execute("SELECT last_insert_rowid()").fetchone()[0]
        rids.append(rid)
        rows.append({"account_id": account_id, "amount": amount, "agent": agent_name,
                     "operator": operator, "status": status})
    sheet_id = _get_tt_sheet_id(db)
    if sheet_id and rows:
        _append_recharge_background(db, uid, sheet_id, _recharge_sheet_name(db), rows, rids)
    return ok({"created": len(rows)})


@tt_accounts_bp.route('/api/tt/recharge/<int:rid>', methods=['PUT'])
@jwt_required()
@tt_required
def recharge_update(rid):
    db = get_db()
    uid = get_uid()
    data = parse_body()
    row = db.execute("SELECT created_by FROM tt_recharge_records WHERE id=?", (rid,)).fetchone()
    if not row:
        return err("充值记录不存在", 404)
    role = _get_role(db, uid)
    if role not in ('developer', 'admin') and row["created_by"] != uid:
        return err("无权限", 403)
    for f in ["amount", "operator", "status"]:
        if f in data and data[f] is not None:
            db.execute(f"UPDATE tt_recharge_records SET {f}=? WHERE id=?",
                       (str(data[f]).strip() if isinstance(data[f], str) else data[f], rid))
    db.commit()
    return ok()


@tt_accounts_bp.route('/api/tt/recharge/<int:rid>', methods=['DELETE'])
@jwt_required()
@tt_required
def recharge_delete(rid):
    db = get_db()
    uid = get_uid()
    row = db.execute("SELECT created_by FROM tt_recharge_records WHERE id=?", (rid,)).fetchone()
    if not row:
        return err("充值记录不存在", 404)
    role = _get_role(db, uid)
    if role not in ('developer', 'admin') and row["created_by"] != uid:
        return err("无权限", 403)
    db.execute("DELETE FROM tt_recharge_records WHERE id=?", (rid,))
    db.commit()
    return ok()


@tt_accounts_bp.route('/api/tt/recharge/<int:rid>/retry-sheets', methods=['POST'])
@jwt_required()
@tt_required
def recharge_retry_sheets(rid):
    db = get_db()
    uid = get_uid()
    row = db.execute(
        "SELECT r.*, ag.name AS agent_name FROM tt_recharge_records r "
        "LEFT JOIN agents ag ON r.agent_id = ag.id WHERE r.id=?", (rid,)).fetchone()
    if not row:
        return err("充值记录不存在", 404)
    sheet_id = _get_tt_sheet_id(db)
    if not sheet_id:
        return err("未配置 Google 表格")
    rows = [{"account_id": row["account_id"], "amount": row["amount"],
             "agent": row["agent_name"] or "", "operator": row["operator"] or "",
             "status": row["status"] or ""}]
    _append_recharge_background(db, uid, sheet_id, _recharge_sheet_name(db), rows, [rid])
    return ok()


# ==================== 回收原因 ====================

@tt_accounts_bp.route('/api/tt/recycle-reasons/list', methods=['GET'])
@jwt_required()
@tt_required
def recycle_reasons_list():
    db = get_db()
    uid = get_uid()
    role = _get_role(db, uid)
    if role in ('developer', 'admin'):
        rows = db.execute("SELECT id, name FROM tt_recycle_reasons ORDER BY id").fetchall()
    else:
        rows = db.execute("SELECT id, name FROM tt_recycle_reasons WHERE owner_id=? ORDER BY id",
                          (uid,)).fetchall()
    return ok({"items": [dict(r) for r in rows]})


@tt_accounts_bp.route('/api/tt/recycle-reasons/create', methods=['POST'])
@jwt_required()
@tt_required
def recycle_reason_create():
    db = get_db()
    uid = get_uid()
    name = (parse_body().get("name") or "").strip()
    if not name:
        return err("名称不能为空")
    existing = db.execute("SELECT id FROM tt_recycle_reasons WHERE name=? AND owner_id=?",
                          (name, uid)).fetchone()
    if existing:
        return err(f"回收原因「{name}」已存在", 409)
    db.execute("INSERT INTO tt_recycle_reasons(name, owner_id) VALUES(?,?)", (name, uid))
    db.commit()
    return ok({"id": db.execute("SELECT last_insert_rowid()").fetchone()[0]})


@tt_accounts_bp.route('/api/tt/recycle-reasons/<int:rid>', methods=['PUT'])
@jwt_required()
@tt_required
def recycle_reason_rename(rid):
    db = get_db()
    uid = get_uid()
    role = _get_role(db, uid)
    name = (parse_body().get("name") or "").strip()
    if not name:
        return err("名称不能为空")
    row = db.execute("SELECT owner_id FROM tt_recycle_reasons WHERE id=?", (rid,)).fetchone()
    if not row:
        return err("回收原因不存在", 404)
    if role not in ('developer', 'admin') and row["owner_id"] != uid:
        return err("无权限", 403)
    db.execute("UPDATE tt_recycle_reasons SET name=? WHERE id=?", (name, rid))
    db.commit()
    return ok()


@tt_accounts_bp.route('/api/tt/recycle-reasons/<int:rid>', methods=['DELETE'])
@jwt_required()
@tt_required
def recycle_reason_delete(rid):
    db = get_db()
    uid = get_uid()
    role = _get_role(db, uid)
    row = db.execute("SELECT owner_id FROM tt_recycle_reasons WHERE id=?", (rid,)).fetchone()
    if not row:
        return err("回收原因不存在", 404)
    if role not in ('developer', 'admin') and row["owner_id"] != uid:
        return err("无权限", 403)
    db.execute("DELETE FROM tt_recycle_reasons WHERE id=?", (rid,))
    db.commit()
    return ok()


# ==================== 同步（我的看板） ====================

def _ensure_bc(db, name):
    if not name:
        return None
    row = db.execute("SELECT id FROM tt_bcs WHERE name=? AND deleted_at IS NULL", (name,)).fetchone()
    if row:
        return row["id"]
    db.execute("INSERT INTO tt_bcs(name, bc_id, owner_id) VALUES(?,?,?)",
               (name, name, 1))
    return db.execute("SELECT last_insert_rowid()").fetchone()[0]


def _ensure_agent(db, name):
    if not name:
        return None
    row = db.execute("SELECT id FROM agents WHERE name=? AND platform='tt'", (name,)).fetchone()
    if row:
        return row["id"]
    db.execute("INSERT INTO agents(name, owner_id, platform) VALUES(?,?, 'tt')", (name, 1))
    return db.execute("SELECT last_insert_rowid()").fetchone()[0]


def _region_timezone(db, country):
    """看板时区为空时，用 regions 的时区补。"""
    row = db.execute("SELECT timezone FROM regions WHERE name=? AND platform='tt'", (country,)).fetchone()
    if row:
        return row["timezone"]
    row = db.execute("SELECT timezone FROM regions WHERE platform='tt' ORDER BY id LIMIT 1").fetchone()
    return (row["timezone"] if row else "")


@tt_accounts_bp.route('/api/tt/accounts/sync-from-sheet', methods=['POST'])
@jwt_required()
@tt_required
def sync_from_sheet():
    from main import _GOOGLE_SHEETS_CONFIG
    import google_sheets_service as gs

    db = get_db()
    uid = get_uid()
    data = parse_body()
    dry_run = bool(data.get("dry_run"))
    user = db.execute("SELECT display_name FROM users WHERE id=?", (uid,)).fetchone()
    display_name = (user["display_name"] or "") if user else ""

    sheet_id = _get_tt_sheet_id(db)
    mappings = _get_tt_sheet_mappings(db)
    dashboard = (mappings.get("my_dashboard") or "").strip() or "我的看板"
    if not sheet_id:
        return err("未配置 Google 表格")

    service = gs.build_service(_GOOGLE_SHEETS_CONFIG["credentials_path"])
    rows = gs.read_sheet_values(service, sheet_id, dashboard, "A:J")
    rows = [r for r in rows if len(r) > 3 and (r[3] or "").strip()]  # D 列账户ID非空

    # 门禁：A 列运营匹配当前用户
    if rows and any((r[0] or "").strip() != display_name for r in rows):
        return err("看板「运营」列与当前账号不匹配，仅可同步自己的账户")

    created, updated, conflicts = [], [], []
    for r in rows:
        acquired_date = (r[1] or "").strip()
        # r[2] 是否回收 — 仅读取，不触发状态变更
        advertiser_id = (r[3] or "").strip()
        bc_name = (r[4] or "").strip()
        country = (r[5] or "").strip()
        agent_name = (r[6] or "").strip()
        timezone = (r[7] or "").strip() or _region_timezone(db, country)
        consumption = (r[8] or "").strip()
        remark = (r[9] or "").strip()

        if not advertiser_id.isdigit():
            continue
        bc_id = _ensure_bc(db, bc_name) if not dry_run else None
        agent_id = _ensure_agent(db, agent_name) if not dry_run else None

        existing = db.execute("SELECT * FROM tt_accounts WHERE advertiser_id=?", (advertiser_id,)).fetchone()
        if not existing:
            if dry_run:
                created.append({"advertiser_id": advertiser_id, "bc": bc_name,
                                "country": country, "agent": agent_name,
                                "timezone": timezone, "consumption": consumption})
            else:
                db.execute(
                    "INSERT INTO tt_accounts(name, advertiser_id, bc_id, country, agent_id, timezone, "
                    "consumption, acquired_date, remark, owner_id) VALUES(?,?,?,?,?,?,?,?,?,?)",
                    (advertiser_id, advertiser_id, bc_id, country, agent_id, timezone,
                     consumption, acquired_date or None, remark, uid))
                db.commit()
                new_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]
                _record_bc_change(db, new_id, bc_id, uid, "create")
                db.commit()
                created.append({"advertiser_id": advertiser_id})
            continue

        # 消耗情况双向同步：Sheet 与系统不一致 → 冲突列表
        if consumption and consumption != (existing["consumption"] or ""):
            conflicts.append({
                "advertiser_id": advertiser_id,
                "sheet_value": consumption,
                "system_value": existing["consumption"] or "",
            })
        else:
            updated.append({"advertiser_id": advertiser_id})

    if dry_run:
        return ok({"dry_run": True, "total": len(rows), "created": created,
                   "updated": updated, "conflicts": conflicts})

    # 确认模式：处理消耗冲突 — 客户端传入 resolutions: [{advertiser_id, value}]
    resolutions = data.get("resolutions") or {}
    for adv_id, value in resolutions.items():
        db.execute("UPDATE tt_accounts SET consumption=? WHERE advertiser_id=?",
                   (value, adv_id))
    db.commit()
    return ok({"created": len(created), "updated": len(updated), "conflicts": conflicts})


# ==================== 状态改「封禁/死亡」写回收清单 ====================

def _maybe_write_recycle(db, uid, advertiser_id, agent_name, country, timezone, reason, sheet_id, sheet_name):
    """状态改为封禁/死亡时，后台异步写回收户清单。失败不阻塞状态变更。"""
    from main import _GOOGLE_SHEETS_CONFIG, _sync_sheets_background

    user = db.execute("SELECT display_name FROM users WHERE id=?", (uid,)).fetchone()
    operator = (user["display_name"] or "") if user else ""
    rows = [{
        "time": datetime.datetime.now().strftime("%Y-%m-%d"),
        "account_id": advertiser_id,
        "agent": agent_name,
        "operator": operator,
        "country": country,
        "timezone": timezone,
        "reason": reason,
    }]

    def _do_sync():
        import google_sheets_service as gs
        service = gs.build_service(_GOOGLE_SHEETS_CONFIG["credentials_path"])
        gs.append_recycle(service, sheet_id, sheet_name, rows)

    _sync_sheets_background(_do_sync, lambda s, e: None)


def _trigger_recycle_if_dead(db, uid, advertiser_id, status_id, reason):
    """status 为「封禁」或「死亡」时，异步写回收户清单。"""
    st = db.execute("SELECT name FROM account_statuses WHERE id=?", (status_id,)).fetchone()
    if not st or st["name"] not in ("封禁", "死亡"):
        return
    sheet_id = _get_tt_sheet_id(db)
    mappings = _get_tt_sheet_mappings(db)
    sheet_name = (mappings.get("recycle") or "").strip() or "回收户清单"
    if not sheet_id:
        return
    # 自动新增回收原因
    if reason:
        existing = db.execute("SELECT id FROM tt_recycle_reasons WHERE name=?", (reason,)).fetchone()
        if not existing:
            db.execute("INSERT OR IGNORE INTO tt_recycle_reasons(name, owner_id) VALUES(?,?)", (reason, uid))
    ac = db.execute("SELECT a.country, a.timezone, ag.name AS agent_name FROM tt_accounts a "
                    "LEFT JOIN agents ag ON a.agent_id = ag.id WHERE a.advertiser_id=?",
                    (advertiser_id,)).fetchone()
    agent_name = ac["agent_name"] if ac else ""
    country = ac["country"] if ac else ""
    timezone = ac["timezone"] if ac else ""
    _maybe_write_recycle(db, uid, advertiser_id, agent_name, country, timezone, reason, sheet_id, sheet_name)
