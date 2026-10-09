"""TikTok 广告账户 API 路由 — 账户管理 / 充值 / 同步 / 回收原因"""
import json
import logging
import datetime
import sqlite3

from flask import Blueprint, request
from flask_jwt_extended import jwt_required

import database
from cache import cache as _app_cache

from .helpers import ok, err, get_uid, get_db, parse_body, CROSS_USER_ROLES, parse_pagination
from .decorators import tt_required, tt_write_required

import huguan_dashboard as hd
import sheet_write

# 与 main.py / huguan_dashboard_routes.py 同一个 logger：handler 由 logging_setup 挂在 root 上。
log = logging.getLogger("gg-server")

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


def _default_account_type_tt(db, uid):
    """新建账户未指定类型时的兜底类型名（取该用户自己看板配置的第一条）。"""
    return hd._default_account_type(db, uid)


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
    # 清除缓存：任何写入 agents 表都须让代理名下拉立即刷新
    _app_cache.clear_prefix("accounts:agents:")
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
@tt_write_required
def create_account():
    db = get_db()
    uid = get_uid()
    data = parse_body()
    advertiser_id = str(data.get("advertiser_id") or "").strip()
    if not advertiser_id:
        return err("请提供广告账户 ID")
    if not advertiser_id.isdigit():
        return err("广告账户 ID 必须是纯数字")
    name = (data.get("name") or "").strip()
    if not name:
        return err("账户名称不能为空")
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
    # 户类型：未指定/空白时落默认类型（看板配置第一条，否则常量）。
    # 服务端不做白名单校验 —— 清单是用户自定义的，硬校验会在「户管刚改名、前端
    # 还拿着旧清单」的瞬间把建户打断；非法值只会变成待总表同步纠正的孤儿类型。
    account_type = (data.get("account_type") or "").strip() or hd._default_account_type(db, uid)
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    try:
        db.execute(
            "INSERT INTO tt_accounts(name, advertiser_id, bc_id, country, agent_id, timezone, "
            "consumption, status_id, acquired_date, remark, owner_id, account_type, "
            "created_at, updated_at) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (name, advertiser_id, bc_id,
             (data.get("country") or "").strip(), agent_id, (data.get("timezone") or "").strip(),
             (data.get("consumption") or "").strip(), status_id,
             (data.get("acquired_date") or None), (data.get("remark") or "").strip(),
             uid, account_type, now, now))
    except sqlite3.IntegrityError:
        # 失败即回滚（同 batch_create_accounts 的死锁教训）：约束冲突不会自动结束
        # 隐式事务，而本连接缓存在 flask.g 上、没有 teardown 关闭它 —— 悬着的写锁
        # 要等请求上下文弹出、对象被回收才释放。本处紧接着就 return，暂时不会引发
        # 阻塞，但补齐它是为了不把同一形态留给下一个人在它后面加调用。
        db.rollback()
        return err("该广告账户已存在", 409)
    new_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]
    _record_bc_change(db, new_id, bc_id, uid, "create")
    db.commit()
    # 户管看板单行回写（规格 §6.2）。只写可写列，绝不碰「换绑情况」列。
    hd.writeback_rows(uid, "tt", [advertiser_id])
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

    page, size = parse_pagination(default=50)
    search = (request.args.get('search') or '').strip()
    bc_id = (request.args.get('bc_id') or '').strip()
    agent_id = (request.args.get('agent_id') or '').strip()
    status_id = (request.args.get('status_id') or '').strip()
    timezone = (request.args.get('timezone') or '').strip()
    owner_id = (request.args.get('owner_id') or '').strip()
    # 户类型可多选：**用重复查询参数**（?account_types=A&account_types=B），
    # 不用逗号分隔 —— 类型名是用户自己起的，完全可能含逗号，切开会静默筛不到任何行。
    account_types = [t.strip() for t in request.args.getlist("account_types") if t.strip()]
    # 默认户类型（空 account_type 行的归属桶）在这里先算出来：筛选与 type_counts
    # 必须走同一个 COALESCE 口径，两处都用它，故不能在 type_counts 那里才算。
    default_type = _default_account_type_tt(db, uid)

    where = ["a.deleted_at IS NULL"]
    params = []
    if role in CROSS_USER_ROLES:
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
        # 筛选必须与**统计/显示**同口径，否则「按钮上写着 N、点下去 0 条」：
        #   显示：`it['status'] = it.get('status_name') or '存活'` —— LEFT JOIN 状态表
        #         得 NULL 时（status_id 为 NULL 或**悬挂**）兜底成「存活」；
        #   统计：`GROUP BY st.name` 后把 st.name 为 NULL 的桶并进「存活」。
        # 故筛选也一律**按名字判定**，兜底别名取同一个「存活」。
        #
        # ⚠️ 旧写法为什么不行（勿改回）：
        #   ① `a.status_id = ?` 按 id 等值：status_id 为 NULL 的户（渲染成「存活」）
        #      与**悬挂** status_id（指向已删字典行，LEFT JOIN 得 NULL ⇒ 也渲染成「存活」）
        #      两类都恒筛不出来；
        #   ② `a.status_id IS NULL OR a.status_id IN (SELECT id ... name='存活' AND
        #      platform='tt')` 补上了 NULL，但悬挂行的 id 不在该子查询里、`IS NULL`
        #      又为假 ⇒ 悬挂那条仍漏。
        # 现以**自包含相关子查询**逐字复刻统计口径：按 id 解析名字、解析不出即取别名。
        #   ⚠️ 子查询**不加 platform 条件**：TT 账户的 status_id 若因跨库拷贝/旧备份
        #      指向他平台同名行（如 fb 的「存活」），统计按 st.name 计入「存活」，
        #      筛选也必须一并计入，否则又是一次分裂。
        #   ⚠️ 不用客户端传来的 id 直接比：id 会因状态表重建而变（2026-10-06 删过 TT
        #      状态行），名字才是稳定契约。
        _st = db.execute("SELECT name FROM account_statuses WHERE id=?", (status_id,)).fetchone()
        if _st is not None and (_st["name"] or "").strip():
            # 解析出名字 → 按同一口径筛，真行 / NULL / 悬挂 / 他平台同名行一并覆盖
            where.append(
                "COALESCE((SELECT name FROM account_statuses WHERE id = a.status_id), '存活') = ?")
            params.append(_st["name"])
        else:
            # 解析不出名字（不存在的 id / 非数字）：**保持原行为** —— `a.status_id = ?`
            # 等值匹配，正常情形恒筛不到（0 行）。绝不退化成「不加条件」，那会返回全部。
            where.append("a.status_id = ?")
            params.append(status_id)
    if account_types:
        marks = ",".join("?" for _ in account_types)
        # 口径必须与 type_counts 的 COALESCE 一致：空 account_type 的行在计数里被折进
        # 默认类型那个桶，筛选也必须能筛出来，否则就是本文件在 status_id 上修过的
        # 同一类缺陷 ——「按钮上写着 N、点下去对不上」。
        where.append(f"COALESCE(NULLIF(a.account_type, ''), ?) IN ({marks})")
        # ⚠️ 顺序：COALESCE 的 ? 在 IN 的 ? 之前，必须先 append default_type。
        params.append(default_type)
        params += account_types
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
            LEFT JOIN tt_bcs b ON a.bc_id = b.id AND b.deleted_at IS NULL
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
    if role in CROSS_USER_ROLES:
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

    # 各户类型计数。口径与 status_counts **完全同底**：都基于 sc_where2
    # （含 search/bc/agent/timezone/owner，不含 status 与 account_types 自身）——
    # 两排按钮的数字必须能对上同一批账户，否则户管看到「两排加起来不等于总数」会怀疑数据。
    # default_type 已在函数前段（account_types 取参之后）算好，此处复用，不再算第二遍。
    type_counts = {}
    for r in db.execute(
        "SELECT COALESCE(NULLIF(a.account_type, ''), ?) AS atype, COUNT(*) AS cnt "
        "FROM tt_accounts a WHERE " + " AND ".join(sc_where2) + " GROUP BY atype",
        [default_type] + sc_params2
    ).fetchall():
        t = r["atype"] or default_type
        type_counts[t] = type_counts.get(t, 0) + r["cnt"]

    return ok({'items': items, 'total': total, 'page': page, 'size': size,
               'status_counts': status_counts, 'type_counts': type_counts})


@tt_accounts_bp.route('/api/tt/accounts/<int:aid>', methods=['PUT'])
@jwt_required()
@tt_write_required
def update_account(aid):
    # 路径参数 `<int:aid>` 无上界（Werkzeug 只保证可解析为 int，不限 int64）：超界 id
    # 不可能命中任何行，却会在 sqlite3 参数绑定处抛 OverflowError ⇒ 500。
    # 口径同 GG 侧 main.py 的 aid 守卫，提前按「账户不存在」返回。
    if aid > 2**63 - 1:
        return err("账户不存在", 404)
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
    if role not in CROSS_USER_ROLES and row["owner_id"] != uid:
        return err("无权限", 403)

    # 回滚快照必须在**这里**抓：下面的 `editable` 列表包含 death_date，
    # 一旦进入那个循环，row 里的 death_date 就是本次请求改写后的值了 ——
    # 那时抓到的快照会让回滚还原成错误的值。
    recycle_snapshot_base = {
        "account_pk": row["id"],
        "prev_status_id": row["status_id"],
        "prev_status_changed_date": row["status_changed_date"],
        "prev_death_date": row["death_date"],
    }

    editable = ["name", "country", "timezone", "consumption",
                "acquired_date", "death_date", "remark", "account_type"]
    # 该循环对**值非 None** 的字段执行 UPDATE ... SET f=?，所以 account_type 传空串
    # 会被原样写空。前端下拉不会传空；为稳妥，在循环之前把空串规范成默认类型。
    if "account_type" in data and data.get("account_type") is not None:
        _at = str(data["account_type"]).strip()
        data["account_type"] = _at or hd._default_account_type(db, uid)
    for f in editable:
        if f in data and data[f] is not None:
            db.execute(f"UPDATE tt_accounts SET {f}=? WHERE id=?",
                       (str(data[f]).strip() if isinstance(data[f], str) else data[f], aid))

    # 备注改动要推到两张表（2026-10-06 规格）。在 editable 循环之后取一次值：
    # 循环里可能已 strip 过，或本次并未带 remark，故以「data 里是否给了 remark」为准。
    #
    # ⚠️ 值在这里取，推送**延到 db.commit() 之后**（函数尾部）。这不是风格问题，
    # 是实测过的 SQLite 死锁：循环里的 UPDATE 到此处尚未提交，本连接正握着唯一
    # 的写者位；而 push_remark_to_operator_dashboard 经 run_write，第一步
    # record_pending 会在**另一条连接**上 INSERT+COMMIT
    # （database.get_db() 每次新连接、`sqlite3.connect(timeout=30)`）。
    # ⇒ 新连接等满 30s 后抛 "database is locked"，被 run_write 的 except 吞掉，
    # 后果是请求线程白冻 30 秒、且 sheet_write_log **一行都不登记**
    # ——这次失败从此看不见、也重试不了。回归用例：
    # tests/test_huguan_dashboard.py::TestUpdateAccountPushesRemark::test_remark_push_registers_log_row
    _push_remark = None
    if "remark" in data and data["remark"] is not None:
        _remark_value = str(data["remark"]).strip()
        _adv = row["advertiser_id"]
        _owner_for_push = row["owner_id"]
        # 户管看板的 M 列（产品信息/remark）回写**不在此处**：函数尾部既有的
        # hd.writeback_rows(uid, "tt", [row["advertiser_id"]]) 已覆盖（cells_for_row
        # 会写 M）。此处刻意不再单独回写一次 —— 一是重复，二是它若落在 db.commit()
        # 之前，push_rows 走独立连接读不到本次未提交的新值，会拿旧 remark 并发写同一行。
        # 投手看板：推给**账户的归属人**，不是调用者 —— 户管可能代改别人名下的户。
        if _owner_for_push is not None:
            _push_remark = (_owner_for_push, _adv, _remark_value)

    # agent/status 文本回退
    if "agent" in data or "agent_id" in data:
        agent_id = _resolve_agent_id(db, (data.get("agent") or "").strip(), data.get("agent_id"))
        if agent_id is not None:
            db.execute("UPDATE tt_accounts SET agent_id=? WHERE id=?", (agent_id, aid))
        elif "agent_id" in data and (data.get("agent_id") is None or data.get("agent_id") == ""):
            # 显式清除代理（对齐 GG accounts_update 的 agent_id=NULL 语义）
            db.execute("UPDATE tt_accounts SET agent_id=NULL WHERE id=?", (aid,))
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
            if new_status_name and new_status_name != (row["status_name"] or ""):
                snap = dict(recycle_snapshot_base)
                snap["new_status_id"] = status_id
                _trigger_recycle_if_dead(db, uid, row["advertiser_id"], status_id,
                                         (data.get("recycle_reason") or "").strip(), snap)

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
    # 户管看板单行回写（规格 §6.2）。只写可写列，绝不碰「换绑情况」列。
    # 它**同时承担 remark 改动时的 M 列回写**（cells_for_row 会写 M，即「产品信息」），
    # 且此处 post-commit、数据新鲜 —— 故 remark 分支不必再单独回写一次。
    hd.writeback_rows(uid, "tt", [row["advertiser_id"]])
    # 投手看板 J 列：remark 分支取好的值，**必须 post-commit 推**。
    # run_write 会在另一条连接上登记 sheet_write_log；若此时本连接还握着未提交的
    # 写事务，SQLite 的单写者约束会让它等满 timeout=30 后失败（详见 remark 分支的说明）。
    if _push_remark is not None:
        hd.push_remark_to_operator_dashboard(*_push_remark)
    return ok()


@tt_accounts_bp.route('/api/tt/accounts/batch-create', methods=['POST'])
@jwt_required()
@tt_write_required
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
        "account_type": (data.get("account_type") or "").strip(),
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
        account_type = (ov.get("account_type") or common["account_type"]).strip() \
            or hd._default_account_type(db, uid)
        try:
            db.execute(
                "INSERT INTO tt_accounts(name, advertiser_id, bc_id, country, agent_id, timezone, "
                "status_id, acquired_date, owner_id, account_type, created_at, updated_at) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                (name, aid, bc_id, country, agent_id, timezone, status_id,
                 acquired_date, uid, account_type, now, now))
            new_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]
            _record_bc_change(db, new_id, bc_id, uid, "import")
            db.commit()
            created.append(aid)
        except sqlite3.IntegrityError:
            # ⚠️ 必须 rollback：sqlite3 为这次 INSERT 开了隐式事务，而约束冲突
            # **不会**自动结束它。若失败的正是**最后一条**，循环里再没有 commit 来
            # 清理 ⇒ 本连接一直握着写锁，到下面 hd.writeback_rows(...) 时，run_write
            # 会在**另一条连接**上 record_pending ⇒ 等满 timeout=30 抛
            # "database is locked" 并被吞掉：请求冻结 30s，且 sheet_write_log
            # 一行不落（这次失败从此看不见、也无法重试）。
            # 触发条件正是「冲突在最后一条」—— 冲突在中间时，后面那条成功后的
            # commit 会顺手清掉悬着的事务，所以只在特定顺序下复现。
            # 回归用例：tests/test_huguan_sheet_write.py::
            #   test_batch_create_conflict_last_still_registers_sheet_write_log
            db.rollback()
            skipped.append({"advertiser_id": aid, "reason": "已存在"})
        except Exception as e:
            # 同上：异常路径一律先把事务收干净再继续循环。
            db.rollback()
            err_msg = str(e).lower()
            if "advertiser_id" in err_msg or "unique" in err_msg:
                skipped.append({"advertiser_id": aid, "reason": "已存在"})
            else:
                # 裸 `str(e)` 会把 sqlite 异常原文回给客户端（CWE-209）；详情只落日志。
                log.exception("导入 TT 账户失败 advertiser_id=%s", aid)
                skipped.append({"advertiser_id": aid, "reason": "导入失败，详情见服务端日志"})
    # 户管看板单行回写（规格 §6.2）。created 里装的就是 advertiser_id。
    hd.writeback_rows(uid, "tt", created)
    return ok({"created": len(created), "created_ids": created, "skipped": skipped})


@tt_accounts_bp.route('/api/tt/accounts/batch-update', methods=['POST'])
@jwt_required()
@tt_write_required
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
    affected_advertiser_ids = []
    for aid in ids:
        # owner 权限校验
        if role not in CROSS_USER_ROLES:
            r = db.execute("SELECT owner_id, bc_id, advertiser_id, status_id, "
                           "status_changed_date, death_date FROM tt_accounts WHERE id=?",
                           (aid,)).fetchone()
            if not r or r["owner_id"] != uid:
                continue
        else:
            r = db.execute("SELECT owner_id, bc_id, advertiser_id, status_id, "
                           "status_changed_date, death_date FROM tt_accounts WHERE id=?",
                           (aid,)).fetchone()
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
            if r["status_id"] is None or str(r["status_id"]) != str(value):
                snap = {"account_pk": aid,
                        "prev_status_id": r["status_id"],
                        "prev_status_changed_date": r["status_changed_date"],
                        "prev_death_date": r["death_date"],
                        "new_status_id": value}
                _trigger_recycle_if_dead(db, uid, r["advertiser_id"], value,
                                         (data.get("recycle_reason") or "").strip(), snap)
        db.execute(f"UPDATE tt_accounts SET {field}=?, updated_at=datetime('now','localtime') WHERE id=?",
                   (value, aid))
        affected_advertiser_ids.append(r["advertiser_id"])
    db.commit()
    # 户管看板单行回写（规格 §6.2）：只刷真的落库了的那些行（被权限跳过的 continue 不计）。
    hd.writeback_rows(uid, "tt", affected_advertiser_ids)
    return ok({"updated": len(ids)})


@tt_accounts_bp.route('/api/tt/accounts/<int:aid>/reassign', methods=['PUT'])
@jwt_required()
@tt_write_required
def reassign_account(aid):
    # 路径参数 `<int:aid>` 无上界：超 int64 会在 sqlite 绑定处抛 OverflowError ⇒ 500。
    # 口径同 GG 侧 main.py 的 aid 守卫（owner_id 那道闸门只管 body 侧）。
    if aid > 2**63 - 1:
        return err("账户不存在", 404)
    db = get_db()
    uid = get_uid()
    role = _get_role(db, uid)
    data = parse_body()
    # 目标归属：跨用户角色（developer/admin/户管）可用 owner_id 转给指定用户，
    # 其余角色恒为调用者自己（默认路径与改动前逐字节一致）。
    # `or ""` 不能省：owner_id 给 0 时 `"0".isdigit()` 为真，会被当成合法目标。
    target_owner = uid
    if role in CROSS_USER_ROLES:
        # `parse_body()` 对「真值非 dict」的 body（如 JSON 数组）原样返回，
        # 不判类型直接 `.get` 会 AttributeError → 500（本任务新引入的读取点）。
        raw_owner = (data.get("owner_id") or "") if isinstance(data, dict) else ""
        raw_owner_str = str(raw_owner).strip()
        if raw_owner_str:
            if not (raw_owner_str.isascii() and raw_owner_str.isdigit()):
                return err("owner_id 不合法", 400)
            target_owner = int(raw_owner_str)
            if target_owner > 2**63 - 1:
                return err("owner_id 不合法", 400)
    existing = db.execute(
        "SELECT a.*, u.username, u.display_name FROM tt_accounts a "
        "LEFT JOIN users u ON a.owner_id = u.id WHERE a.id = ?", (aid,)
    ).fetchone()
    if not existing:
        return err("账户不存在", 404)
    # 归属校验（与同文件 delete_account 同口径）：非跨用户角色只能操作自己的账户。
    # 少了这道闸，普通 user / viewer 按 id 就能把**别人名下**的账户改成自己的
    # —— 非跨用户角色走默认路径时 target_owner 恒为 uid，改归属等于白送。
    # 与 GG 侧 `/api/accounts/<aid>/reassign`（main.py:4701）一致：先鉴权，再判重复。
    if role not in CROSS_USER_ROLES and existing["owner_id"] != uid:
        return err("无权限", 403)
    # 目标用户存在性校验是**必需**的：tt_accounts.owner_id 是 INTEGER REFERENCES
    # users(id)，连接又开了 PRAGMA foreign_keys=ON ⇒ 指向不存在的用户会在
    # UPDATE 处抛 IntegrityError 变成 500。这是本任务新引入的输入路径。
    if target_owner != uid:
        if not db.execute("SELECT 1 FROM users WHERE id=?", (target_owner,)).fetchone():
            return err("目标用户不存在", 400)
    if int(existing["owner_id"] or 0) == target_owner:
        return err("该账户已属于当前用户，无需转移" if target_owner == uid
                   else "该账户已属于目标用户，无需转移", 409)
    db.execute("UPDATE tt_accounts SET owner_id=?, updated_at=datetime('now','localtime') WHERE id=?",
               (target_owner, aid))
    # 换绑记录（2026-10-06 规格）：文本与稍后写表的 L 列值必须同源，故在此构造一次。
    # 月日不用 strftime("%-m") —— Windows 不支持该格式符。
    # 先 strip 再 or：display_name 仅含空白（"   "）时它是 truthy，会顶掉 or 兜底，
    # 若在 .strip() 里收尾就会得到空串，换绑记录退化成「阿轩转10.7」（新名缺失）。
    # 2026-10-06 终审发现，两处 label 构造同修。
    _old_label = ((existing["display_name"] or "").strip()
                  or (existing["username"] or "").strip()
                  or "未分配")
    # SQL 侧同样先 TRIM 再判空，避免纯空白的 display_name 顶掉 username 兜底。
    _new_label_row = db.execute(
        "SELECT COALESCE(NULLIF(TRIM(display_name),''), NULLIF(TRIM(username),''), '') AS n "
        "FROM users WHERE id=?",
        (target_owner,)).fetchone()
    _new_label = ((_new_label_row["n"] if _new_label_row else "").strip()
                  or str(target_owner))
    _now = datetime.datetime.now()
    owner_change_note = f"{_old_label}转{_new_label}{_now.month}.{_now.day}"
    db.execute("UPDATE tt_accounts SET owner_change_note=? WHERE id=?",
               (owner_change_note, aid))
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
    # 户管看板回写（规格 §6.2 / §7.2 规则 3①）：先刷该行的可写列，再写「换绑情况」列。
    hd.writeback_rows(uid, "tt", [existing["advertiser_id"]])
    hd.writeback_owner_channel(uid, "tt", existing["advertiser_id"], target_owner,
                               text=owner_change_note)
    if target_owner == uid:
        return ok({"message": f"账户「{existing['name'] or existing['advertiser_id']}」已转移至当前用户"})
    # 规格 §7.5：文案须区分「已转移至当前用户」与「已从 A 转移至 B」。
    # old_owner 取法与 GG 侧 accounts_reassign 逐字一致；上面那条分支的文案不变。
    old_owner = existing["display_name"] or existing["username"] or "未知"
    t = db.execute("SELECT display_name, username FROM users WHERE id=?", (target_owner,)).fetchone()
    label = (t["display_name"] or t["username"]) if t else str(target_owner)
    return ok({"message": f"账户「{existing['name'] or existing['advertiser_id']}」已从 {old_owner} 转移至 {label}"})


@tt_accounts_bp.route('/api/tt/accounts/<int:aid>', methods=['DELETE'])
@jwt_required()
@tt_write_required
def delete_account(aid):
    # 路径参数 `<int:aid>` 无上界：超 int64 会在 sqlite 绑定处抛 OverflowError ⇒ 500。
    if aid > 2**63 - 1:
        return err("账户不存在或已删除", 404)
    db = get_db()
    uid = get_uid()
    role = _get_role(db, uid)
    ac = db.execute("SELECT id, owner_id FROM tt_accounts WHERE id=? AND deleted_at IS NULL", (aid,)).fetchone()
    if not ac:
        return err("账户不存在或已删除", 404)
    if role not in CROSS_USER_ROLES and ac["owner_id"] != uid:
        return err("无权限", 403)
    db.execute("UPDATE tt_accounts SET deleted_at=datetime('now','localtime'), "
               "updated_at=datetime('now','localtime') WHERE id=?", (aid,))
    db.commit()
    return ok()


@tt_accounts_bp.route('/api/tt/accounts/batch-delete', methods=['POST'])
@jwt_required()
@tt_write_required
def batch_delete_accounts():
    db = get_db()
    uid = get_uid()
    role = _get_role(db, uid)
    ids = parse_body().get("ids") or []
    if not ids:
        return err("未选择账户")
    for aid in ids:
        if role in CROSS_USER_ROLES:
            db.execute("UPDATE tt_accounts SET deleted_at=datetime('now','localtime') WHERE id=? AND deleted_at IS NULL", (aid,))
        else:
            db.execute("UPDATE tt_accounts SET deleted_at=datetime('now','localtime') WHERE id=? AND owner_id=? AND deleted_at IS NULL", (aid, uid))
    db.commit()
    return ok({"deleted": len(ids)})


@tt_accounts_bp.route('/api/tt/accounts/<int:aid>/restore', methods=['POST'])
@jwt_required()
@tt_write_required
def restore_account(aid):
    # 路径参数 `<int:aid>` 无上界：超 int64 会在 sqlite 绑定处抛 OverflowError ⇒ 500。
    if aid > 2**63 - 1:
        return err("账户不存在或未被删除", 404)
    db = get_db()
    uid = get_uid()
    role = _get_role(db, uid)
    ac = db.execute("SELECT owner_id FROM tt_accounts WHERE id=? AND deleted_at IS NOT NULL", (aid,)).fetchone()
    if not ac:
        return err("账户不存在或未被删除", 404)
    if role not in CROSS_USER_ROLES and ac["owner_id"] != uid:
        return err("无权限", 403)
    db.execute("UPDATE tt_accounts SET deleted_at=NULL, updated_at=datetime('now','localtime') WHERE id=?", (aid,))
    db.commit()
    return ok()


@tt_accounts_bp.route('/api/tt/accounts/<int:aid>/permanent', methods=['DELETE'])
@jwt_required()
@tt_write_required
def permanent_delete_account(aid):
    # 路径参数 `<int:aid>` 无上界：超 int64 会在 sqlite 绑定处抛 OverflowError ⇒ 500。
    if aid > 2**63 - 1:
        return err("账户不存在或未被删除", 404)
    db = get_db()
    uid = get_uid()
    role = _get_role(db, uid)
    ac = db.execute("SELECT owner_id FROM tt_accounts WHERE id=? AND deleted_at IS NOT NULL", (aid,)).fetchone()
    if not ac:
        return err("账户不存在或未被删除", 404)
    if role not in CROSS_USER_ROLES and ac["owner_id"] != uid:
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
    """已删除账户列表（**分页** + 服务端搜索）。

    分页理由与 GG 的 `/api/accounts/deleted` 相同（见 main.py 该端点的 docstring）。
    响应在原有 `items` 之外**追加** `total` / `page` / `size` —— 纯增量。

    归属口径与 GG 不同，且是**既有行为**，这里原样保留：跨用户角色
    （CROSS_USER_ROLES）看全部人的已删账户；普通角色只看自己的。
    """
    db = get_db()
    uid = get_uid()
    role = _get_role(db, uid)
    page, size = parse_pagination(default=50)
    cross_user = role in CROSS_USER_ROLES
    owner_filter = request.args.get('owner_id', '').strip()
    if not cross_user:
        owner_filter = ''
    search = request.args.get('search', '').strip()

    where = ["a.deleted_at IS NOT NULL"]
    params = []
    if cross_user:
        if owner_filter:
            where.append("a.owner_id = ?")
            params.append(owner_filter)
    else:
        where.append("a.owner_id = ?")
        params.append(uid)
    if search:
        # 与前端原来的客户端过滤口径对齐：账户ID / 名称 / 代理名。
        where.append("(a.advertiser_id LIKE ? OR a.name LIKE ? OR ag.name LIKE ?)")
        like = f"%{search}%"
        params += [like, like, like]
    where_sql = " AND ".join(where)

    total = db.execute(
        f"SELECT COUNT(*) FROM tt_accounts a LEFT JOIN agents ag ON a.agent_id = ag.id "
        f"WHERE {where_sql}",
        params
    ).fetchone()[0]
    rows = db.execute(
        f"""SELECT a.id, a.name, a.advertiser_id, a.deleted_at,
                   ag.name AS agent_name, st.name AS status_name
            FROM tt_accounts a
            LEFT JOIN agents ag ON a.agent_id = ag.id
            LEFT JOIN account_statuses st ON a.status_id = st.id
            WHERE {where_sql}
            ORDER BY a.deleted_at DESC, a.id DESC LIMIT ? OFFSET ?""",
        params + [size, (page - 1) * size]
    ).fetchall()

    items = []
    for r in rows:
        d = dict(r)
        d["agent"] = d.get("agent_name") or ""
        d["status"] = d.get("status_name") or ""
        items.append(d)
    return ok({"items": items, "total": total, "page": page, "size": size})


@tt_accounts_bp.route('/api/tt/accounts/<int:aid>/bc-history', methods=['GET'])
@jwt_required()
@tt_required
def bc_history(aid):
    # 路径参数 `<int:aid>` 无上界：超 int64 会在 sqlite 绑定处抛 OverflowError ⇒ 500。
    if aid > 2**63 - 1:
        return err("账户不存在", 404)
    db = get_db()
    uid = get_uid()
    role = _get_role(db, uid)
    ac = db.execute("SELECT owner_id FROM tt_accounts WHERE id=?", (aid,)).fetchone()
    if not ac:
        return err("账户不存在", 404)
    if role not in CROSS_USER_ROLES and ac["owner_id"] != uid:
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
@tt_write_required
def delete_bc_history(aid, hid):
    # 两个路径参数均无上界：超 int64 会在 sqlite 绑定处抛 OverflowError ⇒ 500。
    if aid > 2**63 - 1 or hid > 2**63 - 1:
        return err("记录不存在", 404)
    db = get_db()
    uid = get_uid()
    role = _get_role(db, uid)
    if role not in CROSS_USER_ROLES:
        return err("权限不足", 403)
    db.execute("DELETE FROM tt_account_bc_history WHERE id=? AND account_id=?", (hid, aid))
    db.commit()
    return ok()


# ==================== 充值 ====================

def _recharge_sheet_name(db):
    mappings = _get_tt_sheet_mappings(db)
    return (mappings.get("recharge") or "").strip() or "充值表"


def _is_valid_amount(amount):
    """充值金额必须为正数（允许小数）。"""
    try:
        return float(amount) > 0
    except (TypeError, ValueError):
        return False


def _append_recharge_background(db, uid, sheet_id, sheet_name, rows, rids):
    """后台异步写充值表；成功置 sheets_synced=1，失败写 sheets_error。"""
    from main import _GOOGLE_SHEETS_CONFIG, _SHEETS_SYNC_FAILED_MSG, _sync_sheets_background

    def _do_sync():
        import google_sheets_service as gs
        service = gs.build_service(_GOOGLE_SHEETS_CONFIG["credentials_path"])
        gs.append_recharge_tt(service, sheet_id, sheet_name, rows)

    def _on_fail(status, err_msg):
        # 后台线程无应用上下文，必须用 database.get_db() 新建连接（不能碰 flask.g）
        _db = database.get_db()
        if status == "synced":
            for rid in rids:
                _db.execute("UPDATE tt_recharge_records SET sheets_synced=1, sheets_error='' WHERE id=?", (rid,))
        elif status == "retry_failed":
            # ⚠️ 只有**终态**失败才落错。`_sync_sheets_background` 首次失败时会先回调一次
            # 中间态 "failed"（30s 重试在途），失败了才再回调 "retry_failed"。
            # 原实现用 if/else 两分支，把中间态与终态并进同一个 else ⇒ 首次失败就把失败
            # 文案写进 sheets_error，而前端 `TtAccountDetailModal.vue` 在
            # `sheets_synced === 0` 时就用它显示 ⚠️ ⇒ **用户会在重试还没跑完时先看到
            # 一个可能马上自愈的报错**（三期设计 §7 点名的「首次失败就报警」缺陷）。
            # GG 侧同源缺陷二期是换数据源修掉的（那边 `sheets_synced/sheets_error`
            # 已不再写入，UI 改读只回终态的 /api/sheet-write/status）；此处按设计
            # 「独立 bug 修复」的口径只修报警时机，不把 TT 充值改造成统一治理 target。
            #
            # `sheets_error` 会被 GET /api/tt/accounts/<aid>/recharge-records 原样回给
            # 客户端（`SELECT r.*` + `dict(r)`）⇒ 写固定文案，异常原文只进日志
            # （_sync_sheets_background 已按 status 落 warning/error）。
            for rid in rids:
                _db.execute("UPDATE tt_recharge_records SET sheets_error=? WHERE id=?",
                            (_SHEETS_SYNC_FAILED_MSG, rid))
        # else: status == "failed" —— 中间态、重试在途，**什么都不写**（不报警）
        _db.commit()
        _db.close()

    _sync_sheets_background(_do_sync, _on_fail)


@tt_accounts_bp.route('/api/tt/accounts/<int:aid>/recharge-records', methods=['GET'])
@jwt_required()
@tt_required
def recharge_records(aid):
    # 路径参数 `<int:aid>` 无上界：超 int64 会在 sqlite 绑定处抛 OverflowError ⇒ 500。
    if aid > 2**63 - 1:
        return err("账户不存在", 404)
    db = get_db()
    uid = get_uid()
    ac = db.execute("SELECT advertiser_id, owner_id FROM tt_accounts WHERE id=? AND deleted_at IS NULL",
                    (aid,)).fetchone()
    if not ac:
        return err("账户不存在", 404)
    role = _get_role(db, uid)
    if role not in CROSS_USER_ROLES and ac["owner_id"] != uid:
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
@tt_write_required
def recharge_submit():
    db = get_db()
    uid = get_uid()
    data = parse_body()
    account_id = (data.get("account_id") or "").strip()
    amount = str(data.get("amount") or "").strip()
    if not account_id or not amount:
        return err("缺少 account_id 或 amount")
    if not _is_valid_amount(amount):
        return err("充值金额必须为正数")
    # 校验账户存在且属于当前用户（跨用户角色可越权校验）
    role = _get_role(db, uid)
    ac = db.execute("SELECT advertiser_id, status_id, agent_id, owner_id FROM tt_accounts WHERE advertiser_id=? AND deleted_at IS NULL",
                    (account_id,)).fetchone()
    if not ac:
        return err("账户不存在", 404)
    if role not in CROSS_USER_ROLES and ac["owner_id"] != uid:
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
@tt_write_required
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
        if not _is_valid_amount(amount):
            continue
        ac = db.execute("SELECT agent_id, status_id, owner_id FROM tt_accounts WHERE advertiser_id=? AND deleted_at IS NULL",
                        (account_id,)).fetchone()
        if not ac:
            continue
        if role not in CROSS_USER_ROLES and ac["owner_id"] != uid:
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
@tt_write_required
def recharge_update(rid):
    # 路径参数 `<int:rid>` 无上界：超 int64 会在 sqlite 绑定处抛 OverflowError ⇒ 500。
    if rid > 2**63 - 1:
        return err("充值记录不存在", 404)
    db = get_db()
    uid = get_uid()
    data = parse_body()
    row = db.execute("SELECT created_by FROM tt_recharge_records WHERE id=?", (rid,)).fetchone()
    if not row:
        return err("充值记录不存在", 404)
    role = _get_role(db, uid)
    if role not in CROSS_USER_ROLES and row["created_by"] != uid:
        return err("无权限", 403)
    for f in ["amount", "operator", "status"]:
        if f in data and data[f] is not None:
            db.execute(f"UPDATE tt_recharge_records SET {f}=? WHERE id=?",
                       (str(data[f]).strip() if isinstance(data[f], str) else data[f], rid))
    db.commit()
    return ok()


@tt_accounts_bp.route('/api/tt/recharge/<int:rid>', methods=['DELETE'])
@jwt_required()
@tt_write_required
def recharge_delete(rid):
    # 路径参数 `<int:rid>` 无上界：超 int64 会在 sqlite 绑定处抛 OverflowError ⇒ 500。
    if rid > 2**63 - 1:
        return err("充值记录不存在", 404)
    db = get_db()
    uid = get_uid()
    row = db.execute("SELECT created_by FROM tt_recharge_records WHERE id=?", (rid,)).fetchone()
    if not row:
        return err("充值记录不存在", 404)
    role = _get_role(db, uid)
    if role not in CROSS_USER_ROLES and row["created_by"] != uid:
        return err("无权限", 403)
    db.execute("DELETE FROM tt_recharge_records WHERE id=?", (rid,))
    db.commit()
    return ok()


@tt_accounts_bp.route('/api/tt/recharge/<int:rid>/retry-sheets', methods=['POST'])
@jwt_required()
@tt_write_required
def recharge_retry_sheets(rid):
    # 路径参数 `<int:rid>` 无上界：超 int64 会在 sqlite 绑定处抛 OverflowError ⇒ 500。
    if rid > 2**63 - 1:
        return err("充值记录不存在", 404)
    db = get_db()
    uid = get_uid()
    row = db.execute(
        "SELECT r.*, ag.name AS agent_name FROM tt_recharge_records r "
        "LEFT JOIN agents ag ON r.agent_id = ag.id WHERE r.id=?", (rid,)).fetchone()
    if not row:
        return err("充值记录不存在", 404)
    role = _get_role(db, uid)
    if role not in CROSS_USER_ROLES and row["created_by"] != uid:
        return err("无权限", 403)
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
    """回收原因为全平台公用词表：所有 TT 用户（含 viewer）均可读。"""
    db = get_db()
    rows = db.execute("SELECT id, name FROM tt_recycle_reasons ORDER BY id").fetchall()
    return ok({"items": [dict(r) for r in rows]})


@tt_accounts_bp.route('/api/tt/recycle-reasons/create', methods=['POST'])
@jwt_required()
@tt_write_required
def recycle_reason_create():
    db = get_db()
    uid = get_uid()
    name = (parse_body().get("name") or "").strip()
    if not name:
        return err("名称不能为空")
    # 词表公用：按 name 全局去重；owner_id 仅记录创建者，不参与权限判断
    existing = db.execute("SELECT id FROM tt_recycle_reasons WHERE name=?", (name,)).fetchone()
    if existing:
        return err(f"回收原因「{name}」已存在", 409)
    try:
        db.execute("INSERT INTO tt_recycle_reasons(name, owner_id) VALUES(?,?)", (name, uid))
        db.commit()
    except sqlite3.IntegrityError:
        # 并发下撞 name 唯一索引
        # 失败即回滚（同 batch_create_accounts 的死锁教训）：冲突不会自动结束隐式事务。
        db.rollback()
        return err(f"回收原因「{name}」已存在", 409)
    return ok({"id": db.execute("SELECT last_insert_rowid()").fetchone()[0]})


@tt_accounts_bp.route('/api/tt/recycle-reasons/<int:rid>', methods=['PUT'])
@jwt_required()
@tt_write_required
def recycle_reason_rename(rid):
    """公用词表：任何非 viewer 均可改名；name 全局唯一。"""
    # 路径参数 `<int:rid>` 无上界：超 int64 会在 sqlite 绑定处抛 OverflowError ⇒ 500。
    if rid > 2**63 - 1:
        return err("回收原因不存在", 404)
    db = get_db()
    name = (parse_body().get("name") or "").strip()
    if not name:
        return err("名称不能为空")
    row = db.execute("SELECT id FROM tt_recycle_reasons WHERE id=?", (rid,)).fetchone()
    if not row:
        return err("回收原因不存在", 404)
    other = db.execute("SELECT id FROM tt_recycle_reasons WHERE name=? AND id!=?",
                       (name, rid)).fetchone()
    if other:
        return err(f"回收原因「{name}」已存在", 409)
    try:
        db.execute("UPDATE tt_recycle_reasons SET name=? WHERE id=?", (name, rid))
        db.commit()
    except sqlite3.IntegrityError:
        # 失败即回滚（同 batch_create_accounts 的死锁教训）：冲突不会自动结束隐式事务。
        db.rollback()
        return err(f"回收原因「{name}」已存在", 409)
    return ok()


@tt_accounts_bp.route('/api/tt/recycle-reasons/<int:rid>', methods=['DELETE'])
@jwt_required()
@tt_write_required
def recycle_reason_delete(rid):
    """公用词表：任何非 viewer 均可删除。"""
    # 路径参数 `<int:rid>` 无上界：超 int64 会在 sqlite 绑定处抛 OverflowError ⇒ 500。
    if rid > 2**63 - 1:
        return err("回收原因不存在", 404)
    db = get_db()
    row = db.execute("SELECT id FROM tt_recycle_reasons WHERE id=?", (rid,)).fetchone()
    if not row:
        return err("回收原因不存在", 404)
    db.execute("DELETE FROM tt_recycle_reasons WHERE id=?", (rid,))
    db.commit()
    return ok()


# ==================== 同步（我的看板） ====================

def _ensure_bc(db, name, uid):
    if not name:
        return None
    row = db.execute("SELECT id, deleted_at FROM tt_bcs WHERE name=?", (name,)).fetchone()
    if row:
        if row["deleted_at"]:
            db.execute("UPDATE tt_bcs SET deleted_at=NULL WHERE id=?", (row["id"],))
        return row["id"]
    # bc_id 唯一冲突兜底：同名软删后 name 可能仍在，但 bc_id 一定还占用
    row = db.execute("SELECT id, deleted_at FROM tt_bcs WHERE bc_id=?", (name,)).fetchone()
    if row:
        if row["deleted_at"]:
            db.execute("UPDATE tt_bcs SET deleted_at=NULL WHERE id=?", (row["id"],))
        return row["id"]
    db.execute("INSERT INTO tt_bcs(name, bc_id, owner_id) VALUES(?,?,?)",
               (name, name, uid))
    return db.execute("SELECT last_insert_rowid()").fetchone()[0]


def _ensure_agent(db, name, uid):
    if not name:
        return None
    row = db.execute("SELECT id FROM agents WHERE name=? AND platform='tt'", (name,)).fetchone()
    if row:
        return row["id"]
    db.execute("INSERT INTO agents(name, owner_id, platform) VALUES(?,?, 'tt')", (name, uid))
    # 清除缓存：任何写入 agents 表都须让代理名下拉立即刷新
    _app_cache.clear_prefix("accounts:agents:")
    return db.execute("SELECT last_insert_rowid()").fetchone()[0]


def _region_timezone(db, country):
    """看板时区为空时，用 regions 的时区补（归一化去掉 UTC 前缀，如 UTC+8 → +8）。"""
    row = db.execute("SELECT timezone FROM regions WHERE name=? AND platform='tt'", (country,)).fetchone()
    if row:
        return _strip_utc_prefix(row["timezone"])
    row = db.execute("SELECT timezone FROM regions WHERE platform='tt' ORDER BY id LIMIT 1").fetchone()
    return (_strip_utc_prefix(row["timezone"]) if row else "")


def _strip_utc_prefix(value):
    """去掉 UTC 前缀（仅当以 UTC 开头），如 UTC+8 → +8；非 UTC 值原样返回。"""
    value = value or ""
    return value[3:] if value.startswith("UTC") else value


@tt_accounts_bp.route('/api/tt/accounts/sync-from-sheet', methods=['POST'])
@jwt_required()
@tt_write_required
def sync_from_sheet():
    from main import _GOOGLE_SHEETS_CONFIG
    import google_sheets_service as gs

    db = get_db()
    uid = get_uid()
    role = _get_role(db, uid)
    data = parse_body()
    dry_run = bool(data.get("dry_run"))
    # 投手自选的户类型（2026-10-08 规格 §4.8）：只作用于**本次新建**的账户，
    # 已存在的账户类型不动（那条通路不做「以表为准」改写，类型最终由户管从总表纠正）。
    new_account_type = (data.get("account_type") or "").strip() \
        or hd._default_account_type(db, uid)
    user = db.execute("SELECT display_name, username FROM users WHERE id=?", (uid,)).fetchone()
    if user:
        operator_name = (user["display_name"] or "").strip() or (user["username"] or "")
    else:
        operator_name = ""

    sheet_id = _get_tt_sheet_id(db)
    mappings = _get_tt_sheet_mappings(db)
    dashboard = (mappings.get("my_dashboard") or "").strip() or "我的看板"
    # 用户私有覆盖：投手各自配置的看板 sheet 名（config 表）
    priv_row = db.execute("SELECT value FROM config WHERE key=?", (f"tt_sheet_mappings_{uid}",)).fetchone()
    if priv_row and priv_row["value"]:
        try:
            priv = json.loads(priv_row["value"])
            if isinstance(priv, dict) and priv.get("my_dashboard"):
                dashboard = priv["my_dashboard"]
        except Exception:
            pass
    if not sheet_id:
        return err("未配置 Google 表格")

    service = gs.build_service(_GOOGLE_SHEETS_CONFIG["credentials_path"])
    rows = gs.read_sheet_values(service, sheet_id, dashboard, "A:J")
    if rows:
        rows = rows[1:]  # 跳过表头第一行（列名），避免「运营」表头误触发门禁
    rows = [r for r in rows if len(r) > 3 and (r[3] or "").strip()]  # D 列账户ID非空

    # 门禁：A 列运营匹配当前用户（display_name 为空时回退 username）
    if rows and any((r[0] or "").strip() != operator_name for r in rows):
        return err("看板「运营」列与当前账号不匹配，仅可同步自己的账户")

    created, updated, conflicts, status_conflicts = [], [], [], []
    for r in rows:
        # Google Sheets 会截断尾部空列，逐列按 len 安全取值（对齐 GG 同步写法）
        acquired_date = (r[1] or "").strip() if len(r) > 1 else ""
        # r[2] 是否回收：是 → 死亡，可用/空 → 存活（用于状态比对）
        recycle = (r[2] or "").strip() if len(r) > 2 else ""
        sheet_status = "死亡" if recycle == "是" else "存活"
        advertiser_id = (r[3] or "").strip() if len(r) > 3 else ""
        bc_name = (r[4] or "").strip() if len(r) > 4 else ""
        country = (r[5] or "").strip() if len(r) > 5 else ""
        agent_name = (r[6] or "").strip() if len(r) > 6 else ""
        timezone = (r[7] or "").strip() if len(r) > 7 else ""
        timezone = timezone or _region_timezone(db, country)
        consumption = (r[8] or "").strip() if len(r) > 8 else ""
        remark = (r[9] or "").strip() if len(r) > 9 else ""

        if not advertiser_id.isdigit():
            continue
        bc_id = _ensure_bc(db, bc_name, uid) if not dry_run else None
        agent_id = _ensure_agent(db, agent_name, uid) if not dry_run else None

        existing = db.execute("SELECT * FROM tt_accounts WHERE advertiser_id=?", (advertiser_id,)).fetchone()
        if not existing:
            if dry_run:
                created.append({"advertiser_id": advertiser_id, "bc": bc_name,
                                "country": country, "agent": agent_name,
                                "timezone": timezone, "consumption": consumption,
                                "status": sheet_status})
            else:
                status_id = _resolve_status_id(db, sheet_status, None)
                # 死亡户同步写入死亡时间，与手动改状态保持一致
                death_date = datetime.date.today().strftime("%Y-%m-%d") if sheet_status == "死亡" else ""
                db.execute(
                    "INSERT INTO tt_accounts(name, advertiser_id, bc_id, country, agent_id, timezone, "
                    "consumption, status_id, acquired_date, death_date, remark, owner_id, account_type) "
                    "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (advertiser_id, advertiser_id, bc_id, country, agent_id, timezone,
                     consumption, status_id, acquired_date or None, death_date, remark, uid,
                     new_account_type))
                db.commit()
                new_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]
                _record_bc_change(db, new_id, bc_id, uid, "create")
                db.commit()
                created.append({"advertiser_id": advertiser_id})
            continue

        # 已软删的账户：恢复复用（仅限本人或管理员），避免被当作"已存在"跳过
        if existing["deleted_at"]:
            if existing["owner_id"] != uid and role not in CROSS_USER_ROLES:
                continue
            if not dry_run:
                db.execute("UPDATE tt_accounts SET deleted_at=NULL WHERE id=?", (existing["id"],))
                db.commit()
            created.append({"advertiser_id": advertiser_id})
            continue

        # 状态比对：C 列推导状态 vs 系统状态，不一致 → 状态冲突（用户确认后变更）
        sys_status = "存活"
        if existing["status_id"]:
            st_row = db.execute("SELECT name FROM account_statuses WHERE id=?", (existing["status_id"],)).fetchone()
            sys_status = st_row["name"] if st_row else "存活"
        if sheet_status != sys_status:
            status_conflicts.append({
                "advertiser_id": advertiser_id,
                "sheet_status": sheet_status,
                "system_status": sys_status,
            })

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
                   "updated": updated, "conflicts": conflicts,
                   "status_conflicts": status_conflicts})

    # 确认模式：处理消耗冲突 — 客户端传入 resolutions: [{advertiser_id, value}]
    resolutions = data.get("resolutions") or {}
    # 仅允许改当前用户看板行里的 advertiser_id，防止越权改任意账户消耗
    valid_ids = {r[3].strip() for r in rows}
    for adv_id, value in resolutions.items():
        if adv_id not in valid_ids:
            continue
        if role in CROSS_USER_ROLES:
            db.execute("UPDATE tt_accounts SET consumption=? WHERE advertiser_id=?",
                       (value, adv_id))
        else:
            db.execute("UPDATE tt_accounts SET consumption=? WHERE advertiser_id=? AND owner_id=?",
                       (value, adv_id, uid))
    # 处理状态冲突：客户端传入 status_resolutions {advertiser_id: new_status}
    status_resolutions = data.get("status_resolutions") or {}
    for adv_id, new_status in status_resolutions.items():
        if adv_id not in valid_ids or new_status not in ("存活", "死亡"):
            continue
        status_id = _resolve_status_id(db, new_status, None)
        # 与手动改状态保持一致：改为「死亡」置当天死亡时间，改为「存活」清空
        death_date = datetime.date.today().strftime("%Y-%m-%d") if new_status == "死亡" else ""
        if role in CROSS_USER_ROLES:
            db.execute("UPDATE tt_accounts SET status_id=?, status_changed_date=datetime('now','localtime'), death_date=? WHERE advertiser_id=?",
                       (status_id, death_date, adv_id))
        else:
            db.execute("UPDATE tt_accounts SET status_id=?, status_changed_date=datetime('now','localtime'), death_date=? WHERE advertiser_id=? AND owner_id=?",
                       (status_id, death_date, adv_id, uid))
    db.commit()
    # 户管看板单行回写（规格 §6.2）：本次同步**真的落库**的账户。
    # created / updated 里装的是 {"advertiser_id": ...}；消耗与状态两处冲突处置
    # 走 resolutions / status_resolutions 的键，且都可能与 updated 重叠，故去重。
    touched_ids = [c["advertiser_id"] for c in created] + [u["advertiser_id"] for u in updated]
    for adv in resolutions:
        if adv in valid_ids:
            touched_ids.append(adv)
    for adv in status_resolutions:
        if adv in valid_ids:
            touched_ids.append(adv)
    hd.writeback_rows(uid, "tt", list(dict.fromkeys(touched_ids)))
    return ok({"created": len(created), "updated": len(updated), "conflicts": conflicts})


# ==================== 状态改「非存活」写回收清单 ====================

def _tt_recycle_rebuild(user_id, business_key, payload):
    """构造一次「写回收户清单」的函数。

    初始写表与重试**共用**这一条重建路径（DRY）。返回的是 zero-arg 闭包，
    将由后台线程调用，故 service 与 DB 连接都必须在闭包**内部**新建 ——
    请求线程的 sqlite 连接不能跨线程使用，httplib2 客户端亦非线程安全。
    表地址在**每次执行时**现取：户管改过配置后，重试应写进新表。
    """
    def _sync():
        import database
        import google_sheets_service as gs
        from main import _GOOGLE_SHEETS_CONFIG

        db = database.get_db()
        try:
            sheet_id = _get_tt_sheet_id(db)
            mappings = _get_tt_sheet_mappings(db)
            sheet_name = (mappings.get("recycle") or "").strip() or "回收户清单"
        finally:
            db.close()
        if not sheet_id:
            raise RuntimeError("未配置 TT 表格 ID，无法写回收户清单")

        service = gs.build_service(_GOOGLE_SHEETS_CONFIG["credentials_path"])
        gs.append_recycle(service, sheet_id, sheet_name, [{
            "time": datetime.datetime.now().strftime("%Y-%m-%d"),
            "account_id": business_key,
            "reason": (payload or {}).get("reason", ""),
        }])

    return _sync


class IncompleteRecycleSnapshotError(Exception):
    """回收清单回滚快照缺少必需键 —— 无法判定守卫条件。

    原来这条路径 return False，与「守卫未过（用户又改过状态）」同路，最终会被
    _apply_final 归到「该账户在写表期间被再次修改」—— 而它并不知道这个成因。
    改为抛异常：_apply_final 会把回滚器异常如实报成「自动撤销失败（回滚过程出错：…）」。
    """


def _tt_recycle_rollback(db, snapshot):
    """条件回滚：把账户状态改回改之前的值。

    **守卫写在 UPDATE 的 WHERE 里**（原子），不是「先查后写」—— 后者在两步之间
    存在竞态。受影响行数为 0 即守卫未过：说明这 30 秒内用户又改过状态，
    此时**必须放弃回滚**（拿陈旧快照覆盖用户的后续操作就是伪造数据）。

    返回 True=已回滚，False=放弃（仅指守卫未过）。快照不完整是**另一种**失败，
    它无从判定守卫条件，故抛异常而非返回 False，别让调用方误报成「被再次修改」。
    """
    if not isinstance(snapshot, dict):
        raise IncompleteRecycleSnapshotError(
            f"回滚快照类型异常（{type(snapshot).__name__}），无法撤销")
    acct_pk = snapshot.get("account_pk")
    new_status_id = snapshot.get("new_status_id")
    if acct_pk is None or new_status_id is None:
        raise IncompleteRecycleSnapshotError(
            "回滚快照不完整（缺 account_pk / new_status_id），无法撤销")
    cur = db.execute(
        "UPDATE tt_accounts SET status_id=?, status_changed_date=?, death_date=?, "
        "updated_at=datetime('now','localtime') "
        "WHERE id=? AND status_id=?",
        (snapshot.get("prev_status_id"),
         snapshot.get("prev_status_changed_date") or "",
         snapshot.get("prev_death_date") or "",
         acct_pk, new_status_id))
    db.commit()
    return cur.rowcount > 0


sheet_write.register_target("tt_recycle", rebuild=_tt_recycle_rebuild,
                            rollback=_tt_recycle_rollback)


def _trigger_recycle_if_dead(db, uid, advertiser_id, status_id, reason, snapshot=None):
    """status 为非「存活」时，走统一入口异步写回收户清单。

    snapshot 由调用方在**业务变更落库前**抓取（见两条调用路径的注释），
    供最终失败时条件回滚用。
    """
    st = db.execute("SELECT name FROM account_statuses WHERE id=?", (status_id,)).fetchone()
    if not st or st["name"] == "存活":
        return
    if not reason:
        return
    sheet_id = _get_tt_sheet_id(db)
    if not sheet_id:
        return
    # 自动新增回收原因（词表已改为全平台公用，name 全局唯一）
    existing = db.execute("SELECT id FROM tt_recycle_reasons WHERE name=?", (reason,)).fetchone()
    if not existing:
        db.execute("INSERT OR IGNORE INTO tt_recycle_reasons(name, owner_id) VALUES(?,?)",
                   (reason, uid))

    payload = {"reason": reason}
    sheet_write.run_write(
        db, user_id=uid, platform="tt", target="tt_recycle",
        business_key=advertiser_id,
        sync_fn=sheet_write.build_sync("tt_recycle", uid, advertiser_id, payload),
        payload=payload, snapshot=snapshot)
