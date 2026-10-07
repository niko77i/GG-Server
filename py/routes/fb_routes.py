"""Facebook 平台 API 路由 — 产品管理 / 账户管理 / BM管理 / 像素BM管理 / 数据提取 / 数据管理"""
from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity
from .helpers import ok, err, get_uid, get_db, parse_body, CROSS_USER_ROLES
from .decorators import fb_required, no_huguan
import huguan_dashboard as hd
import logging
import re
import threading

fb_bp = Blueprint('fb', __name__)

log = logging.getLogger("gg-server")

# 落库 / 回响应体共用的固定文案。这些 `except Exception` 捕到的多是 sqlite 的
# IntegrityError（UNIQUE / NOT NULL / FOREIGN KEY），原文含 schema 列名与英文约束名。
_FB_DB_FAILED_MSG = "操作失败，详情见服务端日志"
_FB_SHEETS_FAILED_MSG = "表格同步失败，详情见服务端日志"


# ==================== BM 管理 ====================

@fb_bp.route('/api/fb/bms/list', methods=['GET'])
@jwt_required()
@fb_required
def list_bms():
    db = get_db()
    page = request.args.get('page', 1, type=int)
    size = request.args.get('size', 50, type=int)
    status = request.args.get('status', '')
    offset = (page - 1) * size
    uid = get_uid()

    where = ["deleted_at IS NULL"]
    params = []
    # 普通用户只看自己的BM
    role = _get_role(db, uid)
    cross_user = role in CROSS_USER_ROLES
    owner_filter = (request.args.get('owner_id') or '').strip()
    if not cross_user:
        owner_filter = ''
    if cross_user:
        if owner_filter:
            where.append("owner_id = ?")
            params.append(owner_filter)
    else:
        where.append("owner_id = ?")
        params.append(uid)
    if status:
        where.append("status = ?")
        params.append(status)
    where_clause = " AND ".join(where)

    total = db.execute(
        f"SELECT COUNT(*) FROM fb_bms WHERE {where_clause}", params
    ).fetchone()[0]
    rows = db.execute(
        f"SELECT b.*, (SELECT COUNT(*) FROM fb_account_bm WHERE bm_id=b.id) as account_count "
        f"FROM fb_bms b WHERE {where_clause} ORDER BY b.created_at DESC LIMIT ? OFFSET ?",
        params + [size, offset]
    ).fetchall()
    return ok({'items': [dict(r) for r in rows], 'total': total, 'page': page, 'size': size})


@fb_bp.route('/api/fb/bms/unified', methods=['GET'])
@jwt_required()
@fb_required
def list_bms_unified():
    db = get_db()
    page = request.args.get('page', 1, type=int)
    size = request.args.get('size', 50, type=int)
    search = request.args.get('search', '')
    status = request.args.get('status', '')
    bm_type = request.args.get('bm_type', '')
    offset = (page - 1) * size
    uid = get_uid()
    role = _get_role(db, uid)

    base_where = ["deleted_at IS NULL"]
    base_params = []
    cross_user = role in CROSS_USER_ROLES
    owner_filter = (request.args.get('owner_id') or '').strip()
    if not cross_user:
        owner_filter = ''
    if cross_user:
        if owner_filter:
            base_where.append("owner_id = ?")
            base_params.append(owner_filter)
    else:
        base_where.append("owner_id = ?")
        base_params.append(uid)
    if search:
        base_where.append("(name LIKE ? OR bm_id LIKE ?)")
        base_params.extend([f"%{search}%", f"%{search}%"])
    if status:
        base_where.append("status = ?")
        base_params.append(status)
    base_where_clause = " AND ".join(base_where)

    # UNION 两个表，加 bm_type 标记
    union_sql = f"""
        SELECT id, name, bm_id, note, status, owner_id, created_at, updated_at,
               'account' as bm_type,
               (SELECT COUNT(*) FROM fb_account_bm WHERE bm_id=b.id) as account_count,
               0 as pixel_count
        FROM fb_bms b WHERE {base_where_clause}
        UNION ALL
        SELECT id, name, bm_id, note, status, owner_id, created_at, updated_at,
               'pixel' as bm_type,
               0 as account_count,
               (SELECT COUNT(*) FROM fb_pixels WHERE pixel_bm_id=pb.id) as pixel_count
        FROM fb_pixel_bms pb WHERE {base_where_clause}
    """

    # 加总类型过滤
    wrapped_params = base_params * 2  # 两个表的参数一样
    if bm_type:
        union_sql = f"""
            SELECT * FROM ({union_sql}) WHERE bm_type = ?
        """
        wrapped_params.append(bm_type)

    # 总数和分页
    count_sql = f"SELECT COUNT(*) FROM ({union_sql})"
    total = db.execute(count_sql, wrapped_params).fetchone()[0]
    rows = db.execute(
        f"SELECT * FROM ({union_sql}) ORDER BY created_at DESC LIMIT ? OFFSET ?",
        wrapped_params + [size, offset]
    ).fetchall()

    return ok({'items': [dict(r) for r in rows], 'total': total, 'page': page, 'size': size})


@fb_bp.route('/api/fb/bms/create', methods=['POST'])
@jwt_required()
@fb_required
def create_bm():
    db = get_db()
    data = parse_body()
    name = data.get('name', '').strip()
    bm_id = data.get('bm_id', '').strip()
    note = data.get('note', '').strip()

    if not name or not bm_id:
        return err('BM名称和BMID不能为空', 400)
    if not bm_id.isdigit():
        return err('BMID必须是纯数字', 400)

    uid = get_uid()
    try:
        db.execute(
            "INSERT INTO fb_bms (name, bm_id, note, owner_id) VALUES (?, ?, ?, ?)",
            (name, bm_id, note, uid))
        db.commit()
        return ok({'id': db.execute("SELECT last_insert_rowid()").fetchone()[0]})
    except Exception as e:
        log.exception("FB 创建BM失败 bm_id=%s", bm_id)
        return err(_FB_DB_FAILED_MSG)


@fb_bp.route('/api/fb/bms/<int:bid>', methods=['PUT'])
@jwt_required()
@fb_required
def update_bm(bid):
    db = get_db()
    data = parse_body()
    name = data.get('name', '').strip()
    note = data.get('note', '').strip()
    if name:
        db.execute(
            "UPDATE fb_bms SET name=?, note=?, updated_at=datetime('now','localtime') WHERE id=?",
            (name, note, bid))
    db.commit()
    return ok()


@fb_bp.route('/api/fb/bms/<int:bid>', methods=['DELETE'])
@jwt_required()
@fb_required
def delete_bm(bid):
    db = get_db()
    db.execute("UPDATE fb_bms SET deleted_at=datetime('now','localtime') WHERE id=?", (bid,))
    db.commit()
    return ok()


@fb_bp.route('/api/fb/bms/options', methods=['GET'])
@jwt_required()
@fb_required
def bm_options():
    db = get_db()
    rows = db.execute(
        "SELECT id, name, bm_id FROM fb_bms WHERE status='normal' AND deleted_at IS NULL ORDER BY name"
    ).fetchall()
    return ok([dict(r) for r in rows])


@fb_bp.route('/api/fb/bms/<int:bid>/ban-and-migrate', methods=['POST'])
@jwt_required()
@fb_required
def ban_and_migrate(bid):
    """封禁BM并迁移账户到目标BM"""
    db = get_db()
    data = parse_body()
    target_bm_id_str = data.get('target_bm_id', '').strip()
    target_bm_name = data.get('target_bm_name', '').strip()
    uid = get_uid()

    # 检查当前 BM 状态
    bm = db.execute("SELECT * FROM fb_bms WHERE id=?", (bid,)).fetchone()
    if not bm:
        return err('BM不存在', 404)
    if bm['status'] == 'banned':
        return err('该BM已被封禁', 400)

    try:
        # 查找或创建目标 BM
        target = db.execute("SELECT id FROM fb_bms WHERE bm_id=?", (target_bm_id_str,)).fetchone()
        if target:
            target_bid = target['id']
            if target_bid == bid:
                return err('不能迁移到自身', 400)
        else:
            if not target_bm_name:
                return err('新建BM需要提供名称', 400)
            if not target_bm_id_str.isdigit():
                return err('BMID必须是纯数字', 400)
            db.execute(
                "INSERT INTO fb_bms (name, bm_id, owner_id) VALUES (?, ?, ?)",
                (target_bm_name, target_bm_id_str, uid))
            target_bid = db.execute("SELECT last_insert_rowid()").fetchone()[0]

        # 迁移账户关联
        accounts = db.execute(
            "SELECT account_id FROM fb_account_bm WHERE bm_id=?", (bid,)
        ).fetchall()
        for acc in accounts:
            db.execute(
                "INSERT OR IGNORE INTO fb_account_bm (account_id, bm_id) VALUES (?, ?)",
                (acc['account_id'], target_bid))
            db.execute("DELETE FROM fb_account_bm WHERE account_id=? AND bm_id=?", (acc['account_id'], bid))
            db.execute(
                "INSERT INTO fb_account_bm_history (account_id, old_bm_id, new_bm_id, changed_by, change_type) "
                "VALUES (?, ?, ?, ?, 'banned_migration')",
                (acc['account_id'], bid, target_bid, uid))

        # 标记封禁
        db.execute("UPDATE fb_bms SET status='banned', updated_at=datetime('now','localtime') WHERE id=?", (bid,))

        # 检查产品-BM关联（返回警告）
        product_links = db.execute(
            "SELECT p.id, p.product_name FROM fb_products p "
            "JOIN fb_product_bms pb ON pb.product_id = p.id "
            "WHERE pb.bm_id = ?", (bid,)
        ).fetchall()
        warnings = []
        if product_links:
            warnings = [f"产品「{p['product_name']}」仍关联此BM，请手动更新产品的在跑BM" for p in product_links]

        db.commit()
        return ok({
            'migrated_accounts': len(accounts),
            'target_bm_id': target_bid,
            'warnings': warnings
        })
    except Exception as e:
        db.rollback()
        log.exception("FB 封禁迁移失败 bid=%s", bid)
        return err('封禁迁移失败，详情见服务端日志', 500)


# ==================== 账户管理 ====================

@fb_bp.route('/api/fb/accounts/list', methods=['GET'])
@jwt_required()
@fb_required
def list_accounts():
    db = get_db()
    page = request.args.get('page', 1, type=int)
    size = request.args.get('size', 50, type=int)
    bm_filter = request.args.get('bm_id', '', type=str)
    status_filter = request.args.get('status_id', '', type=str)
    search = request.args.get('search', '', type=str)
    deleted = request.args.get('deleted', '0')
    offset = (page - 1) * size
    uid = get_uid()

    where = []
    params = []
    role = _get_role(db, uid)
    cross_user = role in CROSS_USER_ROLES
    owner_filter = (request.args.get('owner_id') or '').strip()
    if not cross_user:
        owner_filter = ''
    if cross_user:
        if owner_filter:
            where.append("a.owner_id = ?")
            params.append(owner_filter)
    else:
        where.append("a.owner_id = ?")
        params.append(uid)
    if deleted == '1':
        where.append("a.deleted_at IS NOT NULL")
    else:
        where.append("a.deleted_at IS NULL")
    if bm_filter:
        where.append("a.id IN (SELECT account_id FROM fb_account_bm WHERE bm_id=?)")
        params.append(bm_filter)
    if status_filter:
        where.append("a.status_id = ?")
        params.append(status_filter)
    if search:
        where.append("(a.name LIKE ? OR a.account_id LIKE ?)")
        params.extend([f"%{search}%", f"%{search}%"])

    where_clause = " AND ".join(where) if where else "1=1"
    total = db.execute(f"SELECT COUNT(*) FROM fb_accounts a WHERE {where_clause}", params).fetchone()[0]
    rows = db.execute(
        f"SELECT a.* FROM fb_accounts a WHERE {where_clause} ORDER BY a.created_at DESC LIMIT ? OFFSET ?",
        params + [size, offset]
    ).fetchall()

    # 批量获取关联的 BM 名称，并标出主 BM（即看板「位置」列，规格 4.3）
    result_items = []
    for r in rows:
        item = dict(r)
        bms = db.execute(
            "SELECT b.name, b.id, b.bm_id, ab.is_primary FROM fb_bms b "
            "JOIN fb_account_bm ab ON ab.bm_id = b.id "
            "WHERE ab.account_id = ?", (r['id'],)
        ).fetchall()
        item['bms'] = [dict(b) for b in bms]
        item['primary_bm_name'] = next((b['name'] for b in item['bms'] if b['is_primary']), '')
        result_items.append(item)

    return ok({'items': result_items, 'total': total, 'page': page, 'size': size})


@fb_bp.route('/api/fb/accounts/create', methods=['POST'])
@jwt_required()
@fb_required
def create_account():
    db = get_db()
    data = parse_body()
    name = data.get('name', '').strip()
    account_id = data.get('account_id', '').strip()
    bm_ids = data.get('bm_ids', [])
    timezone = data.get('timezone', '')
    status_id = data.get('status_id', None)
    acquired_date = data.get('acquired_date', '')
    # 子项目 ① 新增字段（规格 4.1）
    channel_id = data.get('channel_id') or None
    asset_type_id = data.get('asset_type_id') or None
    unit_price = data.get('unit_price', '')
    inbound_qty = data.get('inbound_qty', '')
    acceptor = (data.get('acceptor') or '').strip()
    outbound_date = data.get('outbound_date', '')
    outbound_qty = data.get('outbound_qty', '')
    consumption = data.get('consumption', '')
    remark = data.get('remark', '')
    primary_bm_id = data.get('primary_bm_id') or None

    if not name or not account_id:
        return err('账户名称和账户ID不能为空', 400)
    if not account_id.isdigit():
        return err('账户ID必须是纯数字', 400)

    uid = get_uid()
    # operator 是**冻结字段**（规格 6.1）：服务端填创建者的名字快照，
    # 请求体里的同名字段一律忽略。
    operator = _display_name(db, uid)
    try:
        db.execute(
            "INSERT INTO fb_accounts (name, account_id, timezone, status_id, acquired_date, "
            "owner_id, operator, channel_id, asset_type_id, unit_price, inbound_qty, "
            "acceptor, outbound_date, outbound_qty, consumption, remark) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (name, account_id, timezone, status_id, acquired_date, uid, operator,
             channel_id, asset_type_id, unit_price, inbound_qty,
             acceptor, outbound_date, outbound_qty, consumption, remark))
        acc_pk = db.execute("SELECT last_insert_rowid()").fetchone()[0]
        for bm_id in bm_ids:
            db.execute("INSERT OR IGNORE INTO fb_account_bm (account_id, bm_id) VALUES (?, ?)",
                       (acc_pk, bm_id))
        if primary_bm_id:
            _set_primary_bm(db, acc_pk, primary_bm_id)
        db.commit()
        hd.writeback_rows(uid, "fb", [account_id])
        # 规格 §6.4 写点 1：建号时填了接户人，I 列（接户运营）不补这个定向写点就永远是空的
        # —— `cells_for_row` 跳过 I 列（COLUMN_SPEC 标 writable=False），批量回写不带它。
        # acceptor 为空时不调（helper 内也有空串早退，但不依赖它，这里显式判断）。
        if acceptor:
            hd.writeback_fb_acceptor(uid, "fb", account_id, acceptor)
        return ok({'id': acc_pk})
    except Exception as e:
        log.exception("FB 创建账户失败 account_id=%s", account_id)
        return err(_FB_DB_FAILED_MSG)


@fb_bp.route('/api/fb/accounts/<int:aid>', methods=['PUT'])
@jwt_required()
@fb_required
def update_account(aid):
    db = get_db()
    uid = get_uid()
    data = parse_body()
    name = data.get('name', '').strip()
    timezone = data.get('timezone', '')
    status_id = data.get('status_id', None)
    acquired_date = data.get('acquired_date', '')
    bm_ids = data.get('bm_ids', None)
    # 子项目 ① 新增字段。
    # ⚠️ **operator 刻意不在此列，也不出现在下面的 UPDATE 语句里** ——
    # 冻结口径是「让它没有写入路径」，而不是「在接口层过滤请求体」（规格 6.1）。
    # 想加这一列的请先读规格：它记录的是接户那一刻的户管名，事后不应变化。
    channel_id = data.get('channel_id') or None
    asset_type_id = data.get('asset_type_id') or None
    unit_price = data.get('unit_price', '')
    inbound_qty = data.get('inbound_qty', '')
    acceptor = (data.get('acceptor') or '').strip()
    outbound_date = data.get('outbound_date', '')
    outbound_qty = data.get('outbound_qty', '')
    consumption = data.get('consumption', '')
    remark = data.get('remark', '')
    primary_bm_id = data.get('primary_bm_id') or None

    if name:
        db.execute(
            "UPDATE fb_accounts SET name=?, timezone=?, status_id=?, acquired_date=?, "
            "channel_id=?, asset_type_id=?, unit_price=?, inbound_qty=?, acceptor=?, "
            "outbound_date=?, outbound_qty=?, consumption=?, remark=?, "
            "updated_at=datetime('now','localtime') WHERE id=?",
            (name, timezone, status_id, acquired_date,
             channel_id, asset_type_id, unit_price, inbound_qty, acceptor,
             outbound_date, outbound_qty, consumption, remark, aid))

    if bm_ids is not None:
        # 全量替换关联（既有行为）。这一步会把所有 is_primary 一并清掉 ——
        # 因此下面必须按 primary_bm_id 重建主 BM；前端应始终同时提交两个字段。
        db.execute("DELETE FROM fb_account_bm WHERE account_id=?", (aid,))
        for bm_id in bm_ids:
            db.execute("INSERT OR IGNORE INTO fb_account_bm (account_id, bm_id) VALUES (?, ?)",
                       (aid, bm_id))
    if primary_bm_id:
        _set_primary_bm(db, aid, primary_bm_id)

    db.commit()
    _row = db.execute("SELECT account_id FROM fb_accounts WHERE id=?", (aid,)).fetchone()
    if _row:
        hd.writeback_rows(uid, "fb", [_row["account_id"]])
        # 同 create_account：I 列不在批量回写范围里，编辑时填了接户人必须定向补写。
        # acceptor 为空时**不调**（不要把 I 列清空 / 也不依赖 helper 的空串早退）。
        if acceptor:
            hd.writeback_fb_acceptor(uid, "fb", _row["account_id"], acceptor)
    return ok()


@fb_bp.route('/api/fb/accounts/<int:aid>', methods=['DELETE'])
@jwt_required()
@fb_required
def delete_account(aid):
    db = get_db()
    db.execute("UPDATE fb_accounts SET deleted_at=datetime('now','localtime') WHERE id=?", (aid,))
    db.commit()
    return ok()


@fb_bp.route('/api/fb/accounts/deleted', methods=['GET'])
@jwt_required()
@fb_required
def list_deleted_accounts():
    """返回已删除账户列表"""
    db = get_db()
    page = request.args.get('page', 1, type=int)
    size = request.args.get('size', 50, type=int)
    offset = (page - 1) * size
    uid = get_uid()

    where = ["a.deleted_at IS NOT NULL"]
    params = []
    role = _get_role(db, uid)
    cross_user = role in CROSS_USER_ROLES
    owner_filter = (request.args.get('owner_id') or '').strip()
    if not cross_user:
        owner_filter = ''
    if cross_user:
        if owner_filter:
            where.append("a.owner_id = ?")
            params.append(owner_filter)
    else:
        where.append("a.owner_id = ?")
        params.append(uid)

    where_clause = " AND ".join(where)
    total = db.execute(f"SELECT COUNT(*) FROM fb_accounts a WHERE {where_clause}", params).fetchone()[0]
    rows = db.execute(
        f"SELECT a.* FROM fb_accounts a WHERE {where_clause} ORDER BY a.deleted_at DESC LIMIT ? OFFSET ?",
        params + [size, offset]
    ).fetchall()

    result_items = []
    for r in rows:
        item = dict(r)
        bms = db.execute(
            "SELECT b.name, b.id, b.bm_id FROM fb_bms b "
            "JOIN fb_account_bm ab ON ab.bm_id = b.id "
            "WHERE ab.account_id = ?", (r['id'],)
        ).fetchall()
        item['bms'] = [dict(b) for b in bms]
        result_items.append(item)

    return ok({'items': result_items, 'total': total, 'page': page, 'size': size})


@fb_bp.route('/api/fb/accounts/<int:aid>/reassign', methods=['PUT'])
@jwt_required()
@fb_required
def reassign_account(aid):
    """改 FB 账户的归属（「在用运营」= owner_id）。

    形状照 TT 的 `reassign_account`（routes/tt_accounts_routes.py:466）：
    - 默认路径（不带 owner_id，或调用者非 CROSS_USER_ROLES）→ 转给调用者自己
    - 跨用户路径：CROSS_USER_ROLES + 合法 owner_id → 转给该用户

    注：本端点由子项目 ① 新增，子项目 ② 接上 `hd.writeback_*` 户管看板回写：
    跨用户分支既刷该行可写列，又把「{旧}转{新}」定向写进 I 列（接户运营）。
    """
    db = get_db()
    uid = get_uid()
    role = _get_role(db, uid)
    data = parse_body()

    # 目标归属：跨用户角色可用 owner_id 转给指定用户，其余角色恒为调用者自己。
    # `or ""` 不能省：owner_id 给 0 时 `"0".isdigit()` 为真，会被当成合法目标。
    target_owner = uid
    if role in CROSS_USER_ROLES:
        # parse_body() 对「真值非 dict」的 body（如 JSON 数组）原样返回，
        # 不判类型直接 .get 会 AttributeError → 500。
        raw_owner = (data.get("owner_id") or "") if isinstance(data, dict) else ""
        raw_owner_str = str(raw_owner).strip()
        if raw_owner_str:
            if not (raw_owner_str.isascii() and raw_owner_str.isdigit()):
                return err("owner_id 不合法", 400)
            target_owner = int(raw_owner_str)
            if target_owner > 2**63 - 1:
                return err("owner_id 不合法", 400)

    existing = db.execute(
        "SELECT a.*, u.username, u.display_name FROM fb_accounts a "
        "LEFT JOIN users u ON a.owner_id = u.id WHERE a.id = ?", (aid,)
    ).fetchone()
    if not existing:
        return err("账户不存在", 404)

    # 归属校验（与同文件 delete_account 同口径）：非跨用户角色只能操作自己的账户。
    # 少了这道闸，普通 user / viewer 按 id 就能把**别人名下**的账户改成自己的。
    if role not in CROSS_USER_ROLES and existing["owner_id"] != uid:
        return err("无权限", 403)

    # 目标用户存在性校验是**必需**的：fb_accounts.owner_id 是
    # INTEGER REFERENCES users(id)，连接开着 PRAGMA foreign_keys=ON
    # ⇒ 指向不存在的用户会在 UPDATE 处抛 IntegrityError 变成 500。
    if target_owner != uid:
        if not db.execute("SELECT 1 FROM users WHERE id=?", (target_owner,)).fetchone():
            return err("目标用户不存在", 400)

    if int(existing["owner_id"] or 0) == target_owner:
        return err("该账户已属于当前用户，无需转移" if target_owner == uid
                   else "该账户已属于目标用户，无需转移", 409)

    # 规格 §8：归属变了 → 刷该行可写列 + 定向写「接户运营」记录。**两条分支都要**，
    # 与 GG/TT 两分支都回写对齐 —— 单用户分支不是「归属没变」的死路：
    # 非跨用户角色走不到这里（403 / 409），但**跨用户角色对别人的户、不传 owner_id**
    # 时 existing["owner_id"] != uid，「已属于目标」的 409 不触发，UPDATE 确实把归属
    # 改成调用者自己。`t` 提到分支之前查（与 TT 同形）：两条分支共用同一个新归属名。
    t = db.execute("SELECT display_name, username FROM users WHERE id=?",
                   (target_owner,)).fetchone()
    new_owner = (t["display_name"] or t["username"] or "") if t else ""
    # 换绑串只算一次，库 / 表共用同一份 —— 面板读 a.acceptor、表里读 I 列，
    # 任何一侧单独拼都会分叉（改前库里的 acceptor 恒为改前值，与表不一致）。
    # TT 侧（routes/tt_accounts_routes.py 的 owner_change_note）也是库表双写。
    note = hd._fb_owner_transition(
        existing["display_name"] or existing["username"] or "", new_owner)

    db.execute("UPDATE fb_accounts SET owner_id=?, updated_at=datetime('now','localtime') "
               "WHERE id=?", (target_owner, aid))
    # note 为空（新旧名皆空）时不写库：此时 helper 也不写表（空串早退），
    # 单边写会把库里已有的换绑串清成空 —— 与「库表同串」相悖。
    if note:
        db.execute("UPDATE fb_accounts SET acceptor=? WHERE id=?", (note, aid))
    db.commit()

    hd.writeback_rows(uid, "fb", [existing["account_id"]])
    hd.writeback_fb_acceptor(uid, "fb", existing["account_id"], note)

    if target_owner == uid:
        return ok({"message": f"账户「{existing['name'] or existing['account_id']}」"
                              f"已转移至当前用户"})
    old_owner = existing["display_name"] or existing["username"] or "未知"
    # 文案与 TT 侧的分支结构对称：只有跨用户分支补「已从 A」。
    return ok({"message": f"账户「{existing['name'] or existing['account_id']}」"
                          f"已从 {old_owner} 转移至 {new_owner}"})


@fb_bp.route('/api/fb/accounts/<int:aid>/restore', methods=['POST'])
@jwt_required()
@fb_required
def restore_account(aid):
    db = get_db()
    db.execute("UPDATE fb_accounts SET deleted_at=NULL WHERE id=?", (aid,))
    db.commit()
    return ok()


@fb_bp.route('/api/fb/accounts/<int:aid>/permanent', methods=['DELETE'])
@jwt_required()
@fb_required
def permanent_delete_account(aid):
    db = get_db()
    db.execute("DELETE FROM fb_account_bm WHERE account_id=?", (aid,))
    db.execute("DELETE FROM fb_accounts WHERE id=?", (aid,))
    db.commit()
    return ok()


@fb_bp.route('/api/fb/accounts/<int:aid>/bm-history', methods=['GET'])
@jwt_required()
@fb_required
def account_bm_history(aid):
    db = get_db()
    rows = db.execute(
        "SELECT h.*, ob.name as old_bm_name, nb.name as new_bm_name "
        "FROM fb_account_bm_history h "
        "LEFT JOIN fb_bms ob ON ob.id = h.old_bm_id "
        "LEFT JOIN fb_bms nb ON nb.id = h.new_bm_id "
        "WHERE h.account_id = ? ORDER BY h.created_at DESC", (aid,)
    ).fetchall()
    return ok([dict(r) for r in rows])


# ==================== 产品管理 ====================

@fb_bp.route('/api/fb/products/list', methods=['GET'])
@jwt_required()
@fb_required
def list_products():
    db = get_db()
    page = request.args.get('page', 1, type=int)
    size = request.args.get('size', 50, type=int)
    search = request.args.get('search', '')
    status = request.args.get('status', '')
    region = request.args.get('region', '')
    runner = request.args.get('runner', '', type=str)
    archived = request.args.get('archived', '0')
    uid = get_uid()
    offset = (page - 1) * size

    where = ["p.is_archived = 1" if archived == '1' else "p.is_archived = 0"]
    params = []
    role = _get_role(db, uid)
    if runner and runner.isdigit():
        where.append("p.id IN (SELECT product_id FROM fb_product_runners WHERE user_id=?)")
        params.append(int(runner))
    elif role not in ('developer', 'admin'):
        where.append("p.id IN (SELECT product_id FROM fb_product_runners WHERE user_id=?)")
        params.append(uid)
    if search:
        where.append("p.product_name LIKE ?")
        params.append(f"%{search}%")
    if status:
        where.append("p.status = ?")
        params.append(status)
    if region:
        where.append("p.region = ?")
        params.append(region)

    where_clause = " AND ".join(where)
    total = db.execute(f"SELECT COUNT(*) FROM fb_products p WHERE {where_clause}", params).fetchone()[0]
    rows = db.execute(
        f"SELECT p.* FROM fb_products p WHERE {where_clause} ORDER BY p.created_at DESC LIMIT ? OFFSET ?",
        params + [size, offset]
    ).fetchall()

    items = []
    for r in rows:
        item = dict(r)
        # 商务名
        if r['sales_person_id']:
            sp = db.execute("SELECT name FROM sales_persons WHERE id=?", (r['sales_person_id'],)).fetchone()
            item['sales_person_name'] = sp['name'] if sp else ''
        # 获取在跑BM
        bms = db.execute(
            "SELECT b.id, b.name, b.bm_id FROM fb_bms b "
            "JOIN fb_product_bms pb ON pb.bm_id = b.id WHERE pb.product_id=?", (r['id'],)
        ).fetchall()
        item['bms'] = [dict(b) for b in bms]
        # 获取在跑人员
        runners = db.execute(
            "SELECT u.id, u.username, u.display_name FROM users u "
            "JOIN fb_product_runners pr ON pr.user_id = u.id WHERE pr.product_id=?", (r['id'],)
        ).fetchall()
        item['runners'] = [dict(u) for u in runners]
        # 获取线名
        lines = db.execute(
            "SELECT l.*, p2.pixel_name, p2.pixel_id as pixel_external_id "
            "FROM fb_lines l LEFT JOIN fb_pixels p2 ON p2.id = l.pixel_id "
            "WHERE l.product_id=?", (r['id'],)
        ).fetchall()
        item['lines'] = [dict(li) for li in lines]
        items.append(item)

    return ok({'items': items, 'total': total, 'page': page, 'size': size})


@fb_bp.route('/api/fb/products/runner-products', methods=['GET'])
@jwt_required()
@fb_required
def runner_products():
    """获取当前用户的在跑产品（下拉框用），只返回当前用户是在跑人员的产品。"""
    db = get_db()
    uid = get_uid()
    products = db.execute(
        "SELECT p.id, p.product_name FROM fb_products p "
        "JOIN fb_product_runners pr ON pr.product_id = p.id "
        "WHERE pr.user_id=? AND p.is_archived=0 ORDER BY p.product_name",
        (uid,)
    ).fetchall()
    result = []
    for p in products:
        item = dict(p)
        lines = db.execute(
            "SELECT id, line_name FROM fb_lines WHERE product_id=? ORDER BY line_name", (p['id'],)
        ).fetchall()
        item['lines'] = [dict(l) for l in lines]
        result.append(item)
    return ok(result)


@fb_bp.route('/api/fb/products/create', methods=['POST'])
@jwt_required()
@fb_required
@no_huguan
def create_product():
    db = get_db()
    data = parse_body()
    product_name = data.get('product_name', '').strip()
    kpi = data.get('kpi', '')
    region = data.get('region', '')
    status = data.get('status', 'active')
    sales_person_id = data.get('sales_person_id', None)
    agency_ratio = data.get('agency_ratio', 0)
    bm_ids = data.get('bm_ids', [])
    runner_ids = data.get('runner_ids', [])
    lines = data.get('lines', [])  # [{line_name, link, pixel_id}]

    if not product_name:
        return err('产品名不能为空', 400)

    uid = get_uid()
    try:
        db.execute(
            "INSERT INTO fb_products (product_name, kpi, region, status, sales_person_id, agency_ratio, owner_id) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (product_name, kpi, region, status, sales_person_id, agency_ratio, uid))
        pid = db.execute("SELECT last_insert_rowid()").fetchone()[0]

        for bm_id in bm_ids:
            db.execute("INSERT OR IGNORE INTO fb_product_bms (product_id, bm_id) VALUES (?, ?)", (pid, bm_id))
        for ruid in runner_ids:
            db.execute("INSERT OR IGNORE INTO fb_product_runners (product_id, user_id) VALUES (?, ?)", (pid, ruid))
        for line in lines:
            db.execute(
                "INSERT INTO fb_lines (product_id, line_name, link, pixel_id) VALUES (?, ?, ?, ?)",
                (pid, line.get('line_name', ''), line.get('link', ''), line.get('pixel_id', None)))

        db.commit()
        return ok({'id': pid})
    except Exception as e:
        log.exception("FB 创建产品失败 product_name=%s", product_name)
        return err(_FB_DB_FAILED_MSG)


@fb_bp.route('/api/fb/products/<int:pid>', methods=['PUT'])
@jwt_required()
@fb_required
@no_huguan
def update_product(pid):
    db = get_db()
    data = parse_body()
    product_name = data.get('product_name', '').strip()
    kpi = data.get('kpi', '')
    region = data.get('region', '')
    status = data.get('status', 'active')
    sales_person_id = data.get('sales_person_id', None)
    agency_ratio = data.get('agency_ratio', 0)
    bm_ids = data.get('bm_ids', None)
    runner_ids = data.get('runner_ids', None)
    lines = data.get('lines', None)

    if product_name:
        db.execute(
            "UPDATE fb_products SET product_name=?, kpi=?, region=?, status=?, sales_person_id=?, "
            "agency_ratio=?, updated_at=datetime('now','localtime') WHERE id=?",
            (product_name, kpi, region, status, sales_person_id, agency_ratio, pid))

    if bm_ids is not None:
        db.execute("DELETE FROM fb_product_bms WHERE product_id=?", (pid,))
        for bm_id in bm_ids:
            db.execute("INSERT OR IGNORE INTO fb_product_bms (product_id, bm_id) VALUES (?, ?)", (pid, bm_id))

    if runner_ids is not None:
        db.execute("DELETE FROM fb_product_runners WHERE product_id=?", (pid,))
        for ruid in runner_ids:
            db.execute("INSERT OR IGNORE INTO fb_product_runners (product_id, user_id) VALUES (?, ?)", (pid, ruid))

    if lines is not None:
        db.execute("DELETE FROM fb_lines WHERE product_id=?", (pid,))
        for line in lines:
            db.execute(
                "INSERT INTO fb_lines (product_id, line_name, link, pixel_id) VALUES (?, ?, ?, ?)",
                (pid, line.get('line_name', ''), line.get('link', ''), line.get('pixel_id', None)))

    db.commit()
    return ok()


@fb_bp.route('/api/fb/products/<int:pid>', methods=['DELETE'])
@jwt_required()
@fb_required
@no_huguan
def delete_product(pid):
    db = get_db()
    db.execute("UPDATE fb_products SET is_archived=1, updated_at=datetime('now','localtime') WHERE id=?", (pid,))
    db.commit()
    return ok()


@fb_bp.route('/api/fb/products/<int:pid>/restore', methods=['POST'])
@jwt_required()
@fb_required
@no_huguan
def restore_product(pid):
    db = get_db()
    db.execute("UPDATE fb_products SET is_archived=0, updated_at=datetime('now','localtime') WHERE id=?", (pid,))
    db.commit()
    return ok()


@fb_bp.route('/api/fb/products/<int:pid>/detail', methods=['GET'])
@jwt_required()
@fb_required
def product_detail(pid):
    db = get_db()
    prod = db.execute("SELECT * FROM fb_products WHERE id=?", (pid,)).fetchone()
    if not prod:
        return err('产品不存在', 404)
    item = dict(prod)
    item['bms'] = [dict(b) for b in db.execute(
        "SELECT b.id, b.name, b.bm_id FROM fb_bms b JOIN fb_product_bms pb ON pb.bm_id=b.id WHERE pb.product_id=?", (pid,)
    ).fetchall()]
    item['runners'] = [dict(u) for u in db.execute(
        "SELECT u.id, u.username, u.display_name FROM users u JOIN fb_product_runners pr ON pr.user_id=u.id WHERE pr.product_id=?", (pid,)
    ).fetchall()]
    item['lines'] = [dict(l) for l in db.execute(
        "SELECT l.*, p.pixel_name, p.pixel_id as pixel_external_id FROM fb_lines l LEFT JOIN fb_pixels p ON p.id=l.pixel_id WHERE l.product_id=?", (pid,)
    ).fetchall()]
    return ok(item)


# ==================== 线名管理 ====================

@fb_bp.route('/api/fb/products/<int:pid>/lines', methods=['POST'])
@jwt_required()
@fb_required
@no_huguan
def add_line(pid):
    db = get_db()
    data = parse_body()
    line_name = data.get('line_name', '').strip()
    link = data.get('link', '')
    pixel_id = data.get('pixel_id', None)

    if not line_name:
        return err('线名不能为空', 400)
    try:
        db.execute(
            "INSERT INTO fb_lines (product_id, line_name, link, pixel_id) VALUES (?, ?, ?, ?)",
            (pid, line_name, link, pixel_id))
        db.commit()
        return ok({'id': db.execute("SELECT last_insert_rowid()").fetchone()[0]})
    except Exception as e:
        log.exception("FB 新增线名失败 product_id=%s", pid)
        return err(_FB_DB_FAILED_MSG)


@fb_bp.route('/api/fb/lines/<int:lid>', methods=['PUT'])
@jwt_required()
@fb_required
@no_huguan
def update_line(lid):
    db = get_db()
    data = parse_body()
    line_name = data.get('line_name', '').strip()
    link = data.get('link', '')
    pixel_id = data.get('pixel_id', None)

    if line_name:
        db.execute(
            "UPDATE fb_lines SET line_name=?, link=?, pixel_id=? WHERE id=?",
            (line_name, link, pixel_id, lid))
        db.commit()
    return ok()


@fb_bp.route('/api/fb/lines/<int:lid>', methods=['DELETE'])
@jwt_required()
@fb_required
@no_huguan
def delete_line(lid):
    db = get_db()
    db.execute("DELETE FROM fb_lines WHERE id=?", (lid,))
    db.commit()
    return ok()


# ==================== 像素BM管理 ====================

@fb_bp.route('/api/fb/pixel-bms/list', methods=['GET'])
@jwt_required()
@fb_required
def list_pixel_bms():
    db = get_db()
    page = request.args.get('page', 1, type=int)
    size = request.args.get('size', 50, type=int)
    offset = (page - 1) * size
    uid = get_uid()

    where = ["deleted_at IS NULL"]
    params = []
    role = _get_role(db, uid)
    cross_user = role in CROSS_USER_ROLES
    owner_filter = (request.args.get('owner_id') or '').strip()
    if not cross_user:
        owner_filter = ''
    if cross_user:
        if owner_filter:
            where.append("owner_id = ?")
            params.append(owner_filter)
    else:
        where.append("owner_id = ?")
        params.append(uid)

    where_clause = " AND ".join(where)
    total = db.execute(f"SELECT COUNT(*) FROM fb_pixel_bms WHERE {where_clause}", params).fetchone()[0]
    rows = db.execute(
        f"SELECT pb.*, (SELECT COUNT(*) FROM fb_pixels WHERE pixel_bm_id=pb.id) as pixel_count "
        f"FROM fb_pixel_bms pb WHERE {where_clause} ORDER BY pb.created_at DESC LIMIT ? OFFSET ?",
        params + [size, offset]
    ).fetchall()
    return ok({'items': [dict(r) for r in rows], 'total': total, 'page': page, 'size': size})


@fb_bp.route('/api/fb/pixel-bms/create', methods=['POST'])
@jwt_required()
@fb_required
def create_pixel_bm():
    db = get_db()
    data = parse_body()
    name = data.get('name', '').strip()
    bm_id = data.get('bm_id', '').strip()
    note = data.get('note', '').strip()

    if not name or not bm_id:
        return err('BM名称和BMID不能为空', 400)
    if not bm_id.isdigit():
        return err('BMID必须是纯数字', 400)

    uid = get_uid()
    try:
        db.execute(
            "INSERT INTO fb_pixel_bms (name, bm_id, note, owner_id) VALUES (?, ?, ?, ?)",
            (name, bm_id, note, uid))
        db.commit()
        return ok({'id': db.execute("SELECT last_insert_rowid()").fetchone()[0]})
    except Exception as e:
        log.exception("FB 创建像素BM失败 bm_id=%s", bm_id)
        return err(_FB_DB_FAILED_MSG)


@fb_bp.route('/api/fb/pixel-bms/<int:bid>', methods=['PUT'])
@jwt_required()
@fb_required
def update_pixel_bm(bid):
    db = get_db()
    uid = get_uid()
    role = _get_role(db, uid)
    data = parse_body()
    name = data.get('name', '').strip()
    note = data.get('note', '').strip()
    # 归属校验（口径同 reassign_account）：非跨用户角色只能改自己名下的像素BM。
    # 少了这道闸，任何 FB 用户按 id 就能改**别人**的 BM 名。行不存在时不拦
    # （existing 为 None），保持既有「UPDATE 0 行仍返回 200」的行为。
    existing = db.execute("SELECT owner_id FROM fb_pixel_bms WHERE id=?", (bid,)).fetchone()
    if existing and role not in CROSS_USER_ROLES and existing["owner_id"] != uid:
        return err("无权限", 403)
    if name:
        db.execute(
            "UPDATE fb_pixel_bms SET name=?, note=?, updated_at=datetime('now','localtime') WHERE id=?",
            (name, note, bid))
    db.commit()
    return ok()


@fb_bp.route('/api/fb/pixel-bms/<int:bid>', methods=['DELETE'])
@jwt_required()
@fb_required
def delete_pixel_bm(bid):
    db = get_db()
    uid = get_uid()
    role = _get_role(db, uid)
    # 归属校验：非跨用户角色只能软删自己的像素BM（否则可软删他人 BM）。
    # 行不存在时不拦，保持既有 200。
    existing = db.execute("SELECT owner_id FROM fb_pixel_bms WHERE id=?", (bid,)).fetchone()
    if existing and role not in CROSS_USER_ROLES and existing["owner_id"] != uid:
        return err("无权限", 403)
    db.execute("UPDATE fb_pixel_bms SET deleted_at=datetime('now','localtime') WHERE id=?", (bid,))
    db.commit()
    return ok()


@fb_bp.route('/api/fb/pixel-bms/options', methods=['GET'])
@jwt_required()
@fb_required
def pixel_bm_options():
    db = get_db()
    uid = get_uid()
    role = _get_role(db, uid)
    # 收窄口径同 list_pixel_bms：非跨用户角色强制只看自己的像素BM；
    # 跨用户角色可用 owner_id 收窄，不带则看全部。原实现返回**全库**，属跨租户可见。
    cross_user = role in CROSS_USER_ROLES
    owner_filter = (request.args.get('owner_id') or '').strip() if cross_user else ''
    where = ["status='normal'", "deleted_at IS NULL"]
    params = []
    if cross_user:
        if owner_filter:
            where.append("owner_id = ?")
            params.append(owner_filter)
    else:
        where.append("owner_id = ?")
        params.append(uid)
    where_clause = " AND ".join(where)
    rows = db.execute(
        f"SELECT id, name, bm_id FROM fb_pixel_bms WHERE {where_clause} ORDER BY name", params
    ).fetchall()
    return ok([dict(r) for r in rows])


# ==================== 像素管理 ====================

@fb_bp.route('/api/fb/pixel-bms/<int:bid>/pixels', methods=['GET'])
@jwt_required()
@fb_required
def list_pixels(bid):
    db = get_db()
    uid = get_uid()
    role = _get_role(db, uid)
    # 归属过滤口径同 list_all_pixels：像素归属由父表 fb_pixel_bms.owner_id 决定。
    # 非跨用户角色只能看自己名下的像素BM —— 否则按 bid 就能读**别人**的像素。
    # 返回空列表（而非 403），与既有 list 端点口径一致；BM 不存在时同样落到 ok([])。
    if role not in CROSS_USER_ROLES:
        bm = db.execute("SELECT owner_id FROM fb_pixel_bms WHERE id=?", (bid,)).fetchone()
        if not bm or bm["owner_id"] != uid:
            return ok([])
    rows = db.execute(
        "SELECT * FROM fb_pixels WHERE pixel_bm_id=? ORDER BY pixel_name", (bid,)
    ).fetchall()
    return ok([dict(r) for r in rows])


@fb_bp.route('/api/fb/pixel-bms/<int:bid>/pixels', methods=['POST'])
@jwt_required()
@fb_required
def create_pixel(bid):
    db = get_db()
    data = parse_body()
    pixel_name = data.get('pixel_name', '').strip()
    pixel_id = data.get('pixel_id', '').strip()

    if not pixel_name or not pixel_id:
        return err('像素名和像素ID不能为空', 400)
    if not pixel_id.isdigit():
        return err('像素ID必须是纯数字', 400)

    # 归属校验：目标像素BM必须属于调用者（跨用户角色不限）—— 否则就是把像素
    # 塞进**别人**的 BM。行不存在时不拦，落回既有 INSERT → 外键报错 → err(...)。
    uid = get_uid()
    role = _get_role(db, uid)
    bm = db.execute("SELECT owner_id FROM fb_pixel_bms WHERE id=?", (bid,)).fetchone()
    if bm and role not in CROSS_USER_ROLES and bm["owner_id"] != uid:
        return err("无权限", 403)

    try:
        db.execute(
            "INSERT INTO fb_pixels (pixel_bm_id, pixel_name, pixel_id) VALUES (?, ?, ?)",
            (bid, pixel_name, pixel_id))
        db.commit()
        return ok({'id': db.execute("SELECT last_insert_rowid()").fetchone()[0]})
    except Exception as e:
        log.exception("FB 创建像素失败 pixel_bm_id=%s", bid)
        return err(_FB_DB_FAILED_MSG)


@fb_bp.route('/api/fb/pixels/<int:pxid>', methods=['PUT'])
@jwt_required()
@fb_required
def update_pixel(pxid):
    db = get_db()
    uid = get_uid()
    role = _get_role(db, uid)
    data = parse_body()
    pixel_name = data.get('pixel_name', '').strip()
    # 归属经父表解析（fb_pixels 无 owner 列）：非跨用户角色只能改自己名下 BM 的像素。
    # 像素不存在时不拦，保持既有「UPDATE 0 行仍返回 200」的行为。
    row = db.execute(
        "SELECT pb.owner_id FROM fb_pixels p "
        "JOIN fb_pixel_bms pb ON pb.id = p.pixel_bm_id WHERE p.id=?", (pxid,)
    ).fetchone()
    if row and role not in CROSS_USER_ROLES and row["owner_id"] != uid:
        return err("无权限", 403)
    if pixel_name:
        db.execute("UPDATE fb_pixels SET pixel_name=? WHERE id=?", (pixel_name, pxid))
        db.commit()
    return ok()


@fb_bp.route('/api/fb/pixels/<int:pxid>', methods=['DELETE'])
@jwt_required()
@fb_required
def delete_pixel(pxid):
    db = get_db()
    uid = get_uid()
    role = _get_role(db, uid)
    # 归属经父表解析：非跨用户角色只能删自己名下 BM 的像素。像素不存在时不拦，保持既有 200。
    row = db.execute(
        "SELECT pb.owner_id FROM fb_pixels p "
        "JOIN fb_pixel_bms pb ON pb.id = p.pixel_bm_id WHERE p.id=?", (pxid,)
    ).fetchone()
    if row and role not in CROSS_USER_ROLES and row["owner_id"] != uid:
        return err("无权限", 403)
    db.execute("DELETE FROM fb_pixels WHERE id=?", (pxid,))
    db.commit()
    return ok()


@fb_bp.route('/api/fb/pixels/list', methods=['GET'])
@jwt_required()
@fb_required
def list_all_pixels():
    db = get_db()
    page = request.args.get('page', 1, type=int)
    size = request.args.get('size', 50, type=int)
    search = request.args.get('search', '')
    offset = (page - 1) * size

    where = []
    params = []
    uid = get_uid()
    role = _get_role(db, uid)
    cross_user = role in CROSS_USER_ROLES
    # 跨用户角色可用 owner_id 收窄；非跨用户角色强制只看自己的像素（像素归属由父表 fb_pixel_bms.owner_id 决定）
    owner_filter = (request.args.get('owner_id') or '').strip() if cross_user else ''
    if cross_user:
        if owner_filter:
            where.append("p.pixel_bm_id IN (SELECT id FROM fb_pixel_bms WHERE owner_id = ?)")
            params.append(owner_filter)
    else:
        where.append("p.pixel_bm_id IN (SELECT id FROM fb_pixel_bms WHERE owner_id = ?)")
        params.append(uid)
    if search:
        where.append("(p.pixel_name LIKE ? OR p.pixel_id LIKE ?)")
        params.extend([f"%{search}%", f"%{search}%"])
    where_clause = " AND ".join(where) if where else "1=1"

    total = db.execute(
        f"SELECT COUNT(*) FROM fb_pixels p WHERE {where_clause}", params
    ).fetchone()[0]
    rows = db.execute(
        f"SELECT p.*, pb.name as bm_name, pb.bm_id as bm_bm_id "
        f"FROM fb_pixels p LEFT JOIN fb_pixel_bms pb ON pb.id = p.pixel_bm_id "
        f"WHERE {where_clause} ORDER BY p.created_at DESC LIMIT ? OFFSET ?",
        params + [size, offset]
    ).fetchall()

    return ok({'items': [dict(r) for r in rows], 'total': total, 'page': page, 'size': size})


# ==================== 数据提取 ====================

def _parse_fb_extract(text: str, sorted_mode: bool) -> dict:
    """解析FB粘贴数据，返回结构化结果和警告"""
    lines = [l.strip() for l in text.split('\n') if l.strip()]

    # 找到数据透视表 ~ 总成效 范围
    start_idx = None
    end_idx = None
    for i, line in enumerate(lines):
        if '数据透视表' in line and start_idx is None:
            start_idx = i + 1
        if '总成效' in line and end_idx is None:
            end_idx = i
    if start_idx is None:
        return {'error': '未找到"数据透视表"标记'}
    if end_idx is None:
        end_idx = len(lines)

    # 解析尾部校验数据（"总成效"之后的内容）
    tail_lines = lines[end_idx:]
    declared_rows = 0
    declared_spend = 0.0

    for i, line in enumerate(tail_lines):
        # 匹配 "已显示8/8行" 格式，提取 "/" 后面的总行数
        m = re.search(r'已显示\d+/(\d+)行', line)
        if m:
            declared_rows = int(m.group(1))
        # 收集 $ 金额，检查该行或下一行是否有"总花费"
        if line.startswith('$'):
            amt = float(line.replace('$', '').replace(',', ''))
            nearby = line + ' ' + ' '.join(tail_lines[i+1:i+3])
            if '总花费' in nearby:
                declared_spend = max(declared_spend, amt)

    data_lines = lines[start_idx:end_idx]

    # 动态分组：文本行 + 下一行纯数字长串(≥10位) → 新组开始
    groups = []
    current_group = []
    for i, line in enumerate(data_lines):
        is_pure_digit = re.match(r'^[\d,]+$', line)
        digit_len = len(re.sub(r'[,]', '', line)) if is_pure_digit else 0
        is_account_id = digit_len >= 10
        is_text_header = not is_pure_digit and not re.match(r'^\$', line) and not re.match(r'^\[', line)
        is_short_number = is_pure_digit and digit_len < 10  # 短纯数字可能是账户名

        next_is_account_id = (
            i + 1 < len(data_lines)
            and re.match(r'^[\d,]+$', data_lines[i + 1])
            and len(re.sub(r'[,]', '', data_lines[i + 1])) >= 10
        )
        if (is_text_header or is_short_number) and next_is_account_id:
            if current_group:
                groups.append(current_group)
            current_group = [line]
        else:
            current_group.append(line)
    if current_group:
        groups.append(current_group)

    warnings = []
    results = []

    for group in groups:
        if len(group) < 2:
            continue
        account_name = group[0]
        account_id = group[1].replace(',', '')

        # 收集 $ 金额
        dollar_amounts = []
        clean_numbers = []
        for item in group[2:]:
            if re.match(r'^\[\d+\]$', item):
                continue  # 脏数据
            if item.startswith('$'):
                dollar_amounts.append(float(item.replace('$', '').replace(',', '')))
            elif re.match(r'^[\d,]+$', item):
                clean_numbers.append(int(item.replace(',', '')))

        if len(dollar_amounts) == 0:
            continue

        # 去重：相同 $ 金额视为重复数据，只保留一个
        dollar_amounts = list(set(dollar_amounts))

        # 跳过回流数据：消耗全为 $0.00 的行
        if all(a == 0 for a in dollar_amounts):
            continue

        if len(dollar_amounts) > 2:
            warnings.append(account_name)

        cost = max(dollar_amounts)

        record = {
            'account_name': account_name,
            'account_id': account_id,
            'cost': cost,
        }

        if sorted_mode:
            # 按顺序映射：展示次数、点击、完成注册、购物
            # cost_per_purchase 取 dollar_amounts 中非最大的值（如果有多个$）
            if len(clean_numbers) >= 4:
                record['impressions'] = clean_numbers[0]
                record['clicks'] = clean_numbers[1]
                record['registrations'] = clean_numbers[2]
                record['purchases'] = clean_numbers[3]
            else:
                record['impressions'] = clean_numbers[0] if len(clean_numbers) > 0 else 0
                record['clicks'] = clean_numbers[1] if len(clean_numbers) > 1 else 0
                record['registrations'] = 0
                record['purchases'] = 0
            # cost_per_purchase: 如果 $ 金额有多个，取非 max 的值（次大值）
            if len(dollar_amounts) >= 2:
                sorted_amounts = sorted(dollar_amounts, reverse=True)
                record['cost_per_purchase'] = sorted_amounts[1]
            else:
                record['cost_per_purchase'] = 0

        results.append(record)

    extracted_rows = len(results)
    extracted_spend = round(sum(r['cost'] for r in results), 2)
    validation = {
        'declared_rows': declared_rows,
        'extracted_rows': extracted_rows,
        'declared_spend': round(declared_spend, 2),
        'extracted_spend': extracted_spend
    }
    return {
        'data': results,
        'warnings': warnings,
        'group_size': len(groups[0]) if groups else 0,
        'validation': validation
    }


@fb_bp.route('/api/fb/extract/parse', methods=['POST'])
@jwt_required()
@fb_required
def extract_parse():
    data = parse_body()
    text = data.get('text', '')
    sorted_mode = data.get('sorted', False)

    if not text.strip():
        return err('请粘贴数据', 400)

    result = _parse_fb_extract(text, sorted_mode)
    if 'error' in result:
        return err(result['error'], 400)
    return ok(result)


@fb_bp.route('/api/fb/extract/save', methods=['POST'])
@jwt_required()
@fb_required
def extract_save():
    db = get_db()
    data = parse_body()
    product_name = data.get('product_name', '').strip()
    line_name = data.get('line_name', '')
    report_date = data.get('report_date', '')
    records = data.get('records', [])

    if not product_name or not records:
        return err('产品名和数据不能为空', 400)

    uid = get_uid()
    try:
        for rec in records:
            db.execute(
                "INSERT INTO fb_ad_reports "
                "(user_id, product_name, line_name, report_date, account_name, account_id, "
                "cost, impressions, clicks, registrations, purchases, cost_per_purchase) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(user_id, product_name, line_name, account_id, report_date) DO UPDATE SET "
                "account_name=excluded.account_name, cost=excluded.cost, "
                "impressions=excluded.impressions, clicks=excluded.clicks, "
                "registrations=excluded.registrations, purchases=excluded.purchases, "
                "cost_per_purchase=excluded.cost_per_purchase, "
                "saved_at=datetime('now','localtime')",
                (uid, product_name, line_name, report_date,
                 rec.get('account_name', ''), rec.get('account_id', ''),
                 rec.get('cost', 0), rec.get('impressions', 0), rec.get('clicks', 0),
                 rec.get('registrations', 0), rec.get('purchases', 0), rec.get('cost_per_purchase', 0)))
        db.commit()

        # 先插入一条 pending 同步日志并拿到 id，供前端精确轮询本次写表结果
        import json as _json
        db.execute(
            "INSERT INTO sheets_sync_log (user_id, product_name, spreadsheet_id, sheet_gid, status, rows_json, "
            "report_date, line_name) "
            "VALUES (?,?,?,'','pending',?,?,?)",
            (uid, product_name, '', _json.dumps(records, ensure_ascii=False)[:10000],
             report_date, line_name))
        log_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]
        db.commit()

        # 异步写 Google Sheets（完成后会更新这条日志的状态为 synced/failed）
        _schedule_fb_sheets_write(uid, product_name, line_name, report_date, records, log_id)

        return ok({'saved': len(records), 'sync_log_id': log_id})
    except Exception as e:
        db.rollback()
        log.exception("FB 保存提取数据失败 product_name=%s", product_name)
        return err('保存数据失败，详情见服务端日志', 500)


def _check_fb_sheet_exists(user_id, report_date):
    """同步检查对应月份的表格是否已配置。返回警告文本或 None。"""
    try:
        import database as _db
        import json
        db2 = _db.get_db()
        key = _get_sheet_config_key(db2, user_id)
        config = db2.execute("SELECT value FROM config WHERE key=?", (key,)).fetchone()
        if not config:
            db2.close()
            return "未配置 Google Sheets，请先去个人信息页添加"
        sheets = json.loads(config['value'] or '[]')
        if not sheets:
            db2.close()
            return "未配置 Google Sheets"

        user = db2.execute("SELECT display_name, username FROM users WHERE id=?", (user_id,)).fetchone()
        db2.close()
        user_name = (user['display_name'] or user['username']) if user else f"user{user_id}"
        month_key = report_date[:7].replace('-', '.')
        expected_name = f"{user_name}{month_key}"

        found = next((s for s in sheets if expected_name in (s.get('spreadsheet_name', '') or s.get('name', ''))), None)
        if not found:
            return f"未找到 {month_key} 月份的表格「{expected_name}」，请先在个人信息页添加"
        return None
    except Exception:
        # 目前无调用点（死代码），但返回值若被接进响应体就是同族泄露 ⇒ 一并收口。
        log.exception("FB 表格配置检查失败 user_id=%s", user_id)
        return "配置检查失败，详情见服务端日志"


def _get_sheet_config_key(db, user_id):
    user = db.execute("SELECT platform FROM users WHERE id=?", (user_id,)).fetchone()
    platform = (user['platform'] or 'gg') if user else 'gg'
    return f"google_sheets_fb_{user_id}" if platform == 'fb' else f"google_sheets_{user_id}"


def _schedule_fb_sheets_write(user_id, product_name, line_name, report_date, records, log_id):
    """后台线程写 Google Sheets，并更新对应的 sheets_sync_log 状态（synced/failed）。"""
    def _do_write():
        import database as _db
        import json
        db = _db.get_db()
        try:
            import google_sheets_service as gs
            result = gs.upsert_fb_reports(db, user_id, product_name, line_name, report_date, records)
            log.info("[FB-Sheets] 写入成功: %s", result)
            # 更新本次同步日志为 synced
            db.execute(
                "UPDATE sheets_sync_log SET status='synced', error_msg='', rows_json=?, "
                "updated_at=datetime('now','localtime') WHERE id=?",
                (json.dumps(records, ensure_ascii=False)[:10000], log_id))
            db.commit()
        except Exception:
            # `error_msg` 会被 GET /api/fb/reports/sync-status/<id> 与 last-sync
            # 原样回给客户端 ⇒ 只落固定文案；原文进日志。
            log.exception("[FB-Sheets] 写入失败 log_id=%s", log_id)
            try:
                db.execute(
                    "UPDATE sheets_sync_log SET status='failed', error_msg=?, rows_json=?, "
                    "updated_at=datetime('now','localtime') WHERE id=?",
                    (_FB_SHEETS_FAILED_MSG,
                     json.dumps(records, ensure_ascii=False)[:10000], log_id))
                db.commit()
            except Exception as ex2:
                log.exception("[FB-Sheets] 日志更新也失败: %s", ex2)
        finally:
            try:
                db.close()
            except Exception:
                pass
    t = threading.Thread(target=_do_write, daemon=True)
    t.start()


@fb_bp.route('/api/fb/extract/check-duplicates', methods=['POST'])
@jwt_required()
@fb_required
def fb_check_duplicates():
    """检查即将保存的数据中哪些行与已有数据重复。"""
    db = get_db()
    data = parse_body()
    user_id = get_uid()
    product_name = data.get('product_name', '').strip()
    line_name = data.get('line_name', '')
    report_date = data.get('report_date', '')
    records = data.get('records', [])

    if not product_name or not records:
        return ok({'duplicates': []})

    duplicates = []
    for rec in records:
        account_id = str(rec.get('account_id', '')).strip()
        existing = db.execute(
            "SELECT * FROM fb_ad_reports WHERE user_id=? AND product_name=? "
            "AND line_name=? AND account_id=? AND report_date=?",
            (user_id, product_name, line_name, account_id, report_date)
        ).fetchone()
        if existing:
            duplicates.append({
                "existing": dict(existing),
                "incoming": rec
            })
    return ok({'duplicates': duplicates})


@fb_bp.route('/api/fb/reports/last-sync', methods=['GET'])
@jwt_required()
@fb_required
def fb_last_sync():
    """获取最近一次 Sheet 同步结果。"""
    db = get_db()
    uid = get_uid()
    row = db.execute(
        "SELECT * FROM sheets_sync_log WHERE user_id=? ORDER BY created_at DESC LIMIT 1",
        (uid,)
    ).fetchone()
    if not row:
        return ok({'status': 'none'})
    result = dict(row)
    result['rows_json'] = (result.get('rows_json') or '')[:200]  # 截断
    return ok(result)


@fb_bp.route('/api/fb/reports/sync-status/<int:log_id>', methods=['GET'])
@jwt_required()
@fb_required
def fb_sync_status_by_id(log_id):
    """查询特定同步日志的状态（供前端在保存后精确轮询本次写表结果）。"""
    db = get_db()
    uid = get_uid()
    row = db.execute(
        "SELECT id, status, error_msg FROM sheets_sync_log WHERE id=? AND user_id=?",
        (log_id, uid)
    ).fetchone()
    if not row:
        return err('同步记录不存在', 404)
    return ok({'id': row['id'], 'status': row['status'], 'error_msg': row['error_msg'] or ''})


@fb_bp.route('/api/fb/reports/sync-status', methods=['GET'])
@jwt_required()
@fb_required
def fb_sheets_sync_status():
    """获取 Sheet 同步失败记录。"""
    db = get_db()
    user_id = get_uid()
    product_name = request.args.get('product_name', '')
    rows = db.execute(
        "SELECT * FROM sheets_sync_log WHERE user_id=? AND product_name=? "
        "ORDER BY created_at DESC LIMIT 50",
        (user_id, product_name)
    ).fetchall()
    return ok({'items': [dict(r) for r in rows]})


def _rebuild_fb_records(db, user_id, log_row):
    """按日志行的 (产品名, 线名, 日期) 回查 fb_ad_reports，重建待写 records。

    返回 `(records, None)` 或 `(None, 失败原因)`。

    **刻意不读 `sheets_sync_log.rows_json`**：那个快照在写入时被 `[:10000]` 截断
    （见 extract_save 的 pending 插入）。每条 record 约 200 字符，超过约 50 条就从
    中间断开，`json.loads` 必然抛错 —— 所以只把列名从 `row_data` 改对，
    重试照样是坏的。`fb_ad_reports` 存的是完整原始行，且按
    (user_id, product_name, line_name, account_id, report_date) 唯一，重建更可靠。
    """
    report_date = (log_row['report_date'] or '').strip()
    if not report_date:
        # 这两列是随本次修复才落库的，修复前写入的 pending/failed 行没有它，无从定位
        return None, '这条同步记录缺少日期，无法重建待写数据，请重新保存一次数据'
    records = db.execute(
        "SELECT account_name, account_id, cost, impressions, clicks, "
        "registrations, purchases, cost_per_purchase FROM fb_ad_reports "
        "WHERE user_id=? AND product_name=? AND line_name=? AND report_date=?",
        (user_id, log_row['product_name'],
         (log_row['line_name'] or '').strip(), report_date)
    ).fetchall()
    if not records:
        return None, '找不到对应的原始数据，无法重建待写数据，请重新保存一次数据'
    return [dict(r) for r in records], None


@fb_bp.route('/api/fb/reports/retry-sync', methods=['POST'])
@jwt_required()
@fb_required
def fb_retry_sheets_sync():
    """重试失败的 Sheet 同步。"""
    db = get_db()
    data = parse_body()
    log_id = data.get('id', None)
    user_id = get_uid()

    if log_id:
        log_row = db.execute(
            "SELECT * FROM sheets_sync_log WHERE id=? AND user_id=?", (log_id, user_id)
        ).fetchone()
        if not log_row:
            return err('记录不存在', 404)
        records, why = _rebuild_fb_records(db, user_id, log_row)
        if records is None:
            return err(why, 400)
        try:
            import google_sheets_service as gs
            # 线名必须带上：upsert_fb_reports 把它当渠道号写进 J 列，原来写死 '' 会让
            # 重试行丢渠道号
            gs.upsert_fb_reports(db, user_id, log_row['product_name'],
                                 (log_row['line_name'] or '').strip(),
                                 (log_row['report_date'] or '').strip(), records)
            db.execute("DELETE FROM sheets_sync_log WHERE id=?", (log_id,))
            db.commit()
            return ok({'retried': 1})
        except Exception:
            # 同一处既是落库点（error_msg 会被 sync-status 读回）又是直出点（response.error）
            # ⇒ 两处都用固定文案，原文进日志。
            log.exception("FB 重试写表失败 log_id=%s", log_id)
            db.execute(
                "UPDATE sheets_sync_log SET error_msg=?, retry_count=retry_count+1, "
                "updated_at=datetime('now','localtime') WHERE id=?",
                (_FB_SHEETS_FAILED_MSG, log_id))
            db.commit()
            return err('重试失败，详情见服务端日志', 500)

    # 批量重试
    rows = db.execute(
        "SELECT * FROM sheets_sync_log WHERE user_id=? ORDER BY created_at DESC LIMIT 20",
        (user_id,)
    ).fetchall()
    retried = 0
    failed = []
    for r in rows:
        records, why = _rebuild_fb_records(db, user_id, r)
        if records is None:
            # 无法重建的原因必须回传前端：原来是裸 except 吞掉，用户只看到
            # `retried: 0`，永远不知道哪条没成功、为什么 —— 正是「静默失败」
            failed.append({'id': r['id'], 'product_name': r['product_name'], 'error': why})
            continue
        try:
            import google_sheets_service as gs
            gs.upsert_fb_reports(db, user_id, r['product_name'],
                                 (r['line_name'] or '').strip(),
                                 (r['report_date'] or '').strip(), records)
            db.execute("DELETE FROM sheets_sync_log WHERE id=?", (r['id'],))
            retried += 1
        except Exception:
            # `failed[].error` 直接进响应体、同一文案也落进 error_msg ⇒ 固定文案 + 日志。
            log.exception("FB 批量重试写表失败 log_id=%s", r['id'])
            db.execute(
                "UPDATE sheets_sync_log SET error_msg=?, retry_count=retry_count+1, "
                "updated_at=datetime('now','localtime') WHERE id=?",
                (_FB_SHEETS_FAILED_MSG, r['id']))
            failed.append({'id': r['id'], 'product_name': r['product_name'],
                           'error': _FB_SHEETS_FAILED_MSG})
    db.commit()
    return ok({'retried': retried, 'failed': failed})


# ==================== 数据管理 ====================

@fb_bp.route('/api/fb/reports/list', methods=['GET'])
@jwt_required()
@fb_required
def list_reports():
    db = get_db()
    page = request.args.get('page', 1, type=int)
    size = request.args.get('size', 50, type=int)
    product_name = request.args.get('product_name', '')
    line_name = request.args.get('line_name', '')
    date_from = request.args.get('date_from', '')
    date_to = request.args.get('date_to', '')
    offset = (page - 1) * size
    uid = get_uid()

    where = ["user_id = ?"]
    params = [uid]
    if product_name:
        where.append("product_name = ?")
        params.append(product_name)
    if line_name:
        where.append("line_name = ?")
        params.append(line_name)
    if date_from:
        where.append("report_date >= ?")
        params.append(date_from)
    if date_to:
        where.append("report_date <= ?")
        params.append(date_to)

    where_clause = " AND ".join(where)
    total = db.execute(f"SELECT COUNT(*) FROM fb_ad_reports WHERE {where_clause}", params).fetchone()[0]
    rows = db.execute(
        f"SELECT * FROM fb_ad_reports WHERE {where_clause} ORDER BY report_date DESC, saved_at DESC LIMIT ? OFFSET ?",
        params + [size, offset]
    ).fetchall()

    return ok({'items': [dict(r) for r in rows], 'total': total, 'page': page, 'size': size})


@fb_bp.route('/api/fb/reports/<int:rid>', methods=['PUT'])
@jwt_required()
@fb_required
def update_report(rid):
    db = get_db()
    data = parse_body()
    updates = []
    params = []
    for field in ['account_name', 'account_id', 'cost', 'impressions', 'clicks',
                   'registrations', 'purchases', 'cost_per_purchase', 'report_date']:
        if field in data:
            updates.append(f"{field} = ?")
            params.append(data[field])
    if updates:
        updates.append("updated_at = datetime('now','localtime')")
        params.append(rid)
        db.execute(f"UPDATE fb_ad_reports SET {', '.join(updates)} WHERE id = ?", params)
        db.commit()
    return ok()


@fb_bp.route('/api/fb/reports/<int:rid>', methods=['DELETE'])
@jwt_required()
@fb_required
def delete_report(rid):
    db = get_db()
    db.execute("DELETE FROM fb_ad_reports WHERE id=?", (rid,))
    db.commit()
    return ok()


@fb_bp.route('/api/fb/reports/batch-delete', methods=['POST'])
@jwt_required()
@fb_required
def batch_delete_reports():
    db = get_db()
    data = parse_body()
    ids = data.get('ids', [])
    if ids:
        placeholders = ','.join(['?'] * len(ids))
        db.execute(f"DELETE FROM fb_ad_reports WHERE id IN ({placeholders})", ids)
        db.commit()
    return ok({'deleted': len(ids)})


@fb_bp.route('/api/fb/reports/stats', methods=['GET'])
@jwt_required()
@fb_required
def reports_stats():
    db = get_db()
    product_name = request.args.get('product_name', '')
    line_name = request.args.get('line_name', '')
    date_from = request.args.get('date_from', '')
    date_to = request.args.get('date_to', '')
    uid = get_uid()

    where = ["user_id = ?"]
    params = [uid]
    if product_name:
        where.append("product_name = ?")
        params.append(product_name)
    if line_name:
        where.append("line_name = ?")
        params.append(line_name)
    if date_from:
        where.append("report_date >= ?")
        params.append(date_from)
    if date_to:
        where.append("report_date <= ?")
        params.append(date_to)

    where_clause = " AND ".join(where)
    row = db.execute(
        f"SELECT product_name, line_name, report_date, "
        f"SUM(cost) as total_cost, SUM(impressions) as total_impressions, "
        f"SUM(clicks) as total_clicks, SUM(registrations) as total_registrations, "
        f"SUM(purchases) as total_purchases, COUNT(DISTINCT account_id) as account_count "
        f"FROM fb_ad_reports WHERE {where_clause} "
        f"GROUP BY product_name, line_name, report_date ORDER BY report_date DESC",
        params
    ).fetchall()

    return ok([dict(r) for r in row])


@fb_bp.route('/api/fb/reports/export', methods=['GET'])
@jwt_required()
@fb_required
def export_reports():
    import csv, io
    db = get_db()
    uid = get_uid()
    product_name = request.args.get('product_name', '')
    line_name = request.args.get('line_name', '')
    date_from = request.args.get('date_from', '')
    date_to = request.args.get('date_to', '')

    where = ["user_id = ?"]
    params = [uid]
    if product_name:
        where.append("product_name = ?")
        params.append(product_name)
    if line_name:
        where.append("line_name = ?")
        params.append(line_name)
    if date_from:
        where.append("report_date >= ?")
        params.append(date_from)
    if date_to:
        where.append("report_date <= ?")
        params.append(date_to)

    where_clause = " AND ".join(where)
    rows = db.execute(
        f"SELECT * FROM fb_ad_reports WHERE {where_clause} ORDER BY report_date DESC",
        params
    ).fetchall()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['产品名', '线名', '日期', '账户名称', '账户ID', '消耗', '展示', '点击', '注册', '购物', '单词购物费用'])
    for r in rows:
        writer.writerow([r['product_name'], r['line_name'], r['report_date'],
                         r['account_name'], r['account_id'], r['cost'],
                         r['impressions'], r['clicks'], r['registrations'],
                         r['purchases'], r['cost_per_purchase']])

    from flask import Response
    return Response(
        output.getvalue(),
        mimetype='text/csv',
        headers={'Content-Disposition': 'attachment;filename=fb_reports.csv'}
    )


# ==================== 用户查询（FB 平台） ====================

@fb_bp.route('/api/fb/users', methods=['GET'])
@jwt_required()
@fb_required
def list_fb_users():
    """返回 FB 平台用户列表（供"在跑人员"选择器使用）"""
    db = get_db()
    rows = db.execute(
        "SELECT id, username, display_name, platform FROM users "
        "WHERE (platform = 'fb' OR role = 'developer') AND role != 'hidden' "
        "ORDER BY display_name, username"
    ).fetchall()
    return ok({"users": [dict(r) for r in rows]})


# ==================== 工具函数 ====================

def _get_role(db, uid):
    user = db.execute("SELECT role FROM users WHERE id=?", (uid,)).fetchone()
    return user['role'] if user else 'user'


def _display_name(db, uid):
    """用户显示名快照：display_name 优先，空则回退 username。

    与 `resolve_owner_id` 用的同一个 COALESCE(NULLIF(...)) 口径。
    用于 `fb_accounts.operator` —— 那一列存的是**名字快照**不是外键（规格 6.1）。
    """
    r = db.execute("SELECT COALESCE(NULLIF(display_name, ''), username, '') AS n "
                   "FROM users WHERE id=?", (uid,)).fetchone()
    return r['n'] if r else ''


def _set_primary_bm(db, acc_pk, bm_id):
    """把某账户的主 BM 换成 bm_id。**不 commit**，事务边界由调用方负责。

    ⚠️ **必须先清后设，顺序不能反。** `idx_fb_account_bm_primary` 是
    `WHERE is_primary = 1` 的部分唯一索引，保证同一账户至多一行主 BM。
    SQLite 的唯一索引是**逐语句**检查的，不是事务提交时统一检查 ——
    先设新的（此刻旧的主 BM 还是 1）会立刻 UNIQUE constraint failed。
    这是正确性问题，不是代码风格问题。
    """
    db.execute("UPDATE fb_account_bm SET is_primary=0 WHERE account_id=?", (acc_pk,))
    cur = db.execute("UPDATE fb_account_bm SET is_primary=1 WHERE account_id=? AND bm_id=?",
                     (acc_pk, bm_id))
    if cur.rowcount == 0:
        # 该 BM 尚未与该账户关联
        db.execute("INSERT INTO fb_account_bm(account_id, bm_id, is_primary) VALUES(?,?,1)",
                   (acc_pk, bm_id))
