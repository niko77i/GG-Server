"""TikTok 平台 API 路由 — 产品管理 / BC管理 / 投放对象 / 掉包检测 / 素材关联"""
import json
import os
import re
import urllib.parse

from flask import Blueprint, request
from flask_jwt_extended import jwt_required
from .helpers import ok, err, get_uid, get_db, parse_body, CROSS_USER_ROLES
from .decorators import tt_required, tt_write_required, no_huguan, reject_huguan, require_platform

# 脏数据解析用的链接正则。两个 pattern 合成一个 alternation，
# 这样 re.finditer 能按**原文出现顺序**输出，而不是「先排完 Play 再排苹果」，
# 否则 _guess_series 会拿错行去猜系列名。
# 苹果链接的查询参数（?pt= / ?ct= / ?l=）是分享/联盟参数，与掉包判定无关，
# 故意不捕获 —— 去掉后同一个 app 的重复粘贴能被合并去重键识别。
_PLAY_LINK_RE = r'https?://play\.google\.com/store/apps/details\?id=[\w.&=/\-?%]+'
# 苹果链接两种真实形状都要匹配：
#   https://apps.apple.com/vn/app/id6804355336         （无 slug）
#   https://apps.apple.com/vn/app/densia/id6804355336  （有 slug —— 实测中 200 会跳转到这个形状）
# slug 必须作为独立路径段可选：写成 `[\w\-]*id\d+` 会跨不过 slug 后的 `/`，导致 slug 形式漏匹配。
_APPSTORE_LINK_RE = r'https?://(?:apps|itunes)\.apple\.com/(?:[\w\-]+/)?app/(?:[\w\-]+/)?id\d+'
_LINK_RE = re.compile(f'(?:{_PLAY_LINK_RE})|(?:{_APPSTORE_LINK_RE})')

tt_bp = Blueprint('tt', __name__)


# ==================== BC 管理 ====================

@tt_bp.route('/api/tt/bcs/list', methods=['GET'])
@jwt_required()
@tt_required
def list_bcs():
    db = get_db()
    page = request.args.get('page', 1, type=int)
    size = request.args.get('size', 50, type=int)
    status = request.args.get('status', '')
    search = request.args.get('search', '')
    offset = (page - 1) * size
    uid = get_uid()

    where = ["deleted_at IS NULL"]
    params = []
    role = _get_role(db, uid)
    if role not in CROSS_USER_ROLES:
        where.append("owner_id = ?")
        params.append(uid)
    else:
        # 跨用户角色可用 owner_id 收窄（补齐 Task 16 的「全部用户」下拉）
        owner_filter = (request.args.get('owner_id') or '').strip()
        if owner_filter:
            where.append("owner_id = ?")
            params.append(owner_filter)
    if status:
        where.append("status = ?")
        params.append(status)
    if search:
        where.append("(name LIKE ? OR bc_id LIKE ?)")
        params += [f"%{search}%", f"%{search}%"]
    where_clause = " AND ".join(where)

    total = db.execute(
        f"SELECT COUNT(*) FROM tt_bcs WHERE {where_clause}", params
    ).fetchone()[0]
    rows = db.execute(
        f"SELECT * FROM tt_bcs WHERE {where_clause} ORDER BY created_at DESC LIMIT ? OFFSET ?",
        params + [size, offset]
    ).fetchall()
    return ok({'items': [dict(r) for r in rows], 'total': total, 'page': page, 'size': size})


@tt_bp.route('/api/tt/bcs/create', methods=['POST'])
@jwt_required()
@tt_write_required
def create_bc():
    db = get_db()
    data = parse_body()
    name = data.get('name', '').strip()
    bc_id = data.get('bc_id', '').strip()
    note = data.get('note', '').strip()

    if not name or not bc_id:
        return err('BC名称和BCID不能为空')
    if not bc_id.isdigit():
        return err('BCID必须是纯数字')

    uid = get_uid()
    if db.execute("SELECT id FROM tt_bcs WHERE bc_id=?", (bc_id,)).fetchone():
        return err(f"BCID「{bc_id}」已存在", 409)
    try:
        db.execute(
            "INSERT INTO tt_bcs (name, bc_id, note, owner_id) VALUES (?, ?, ?, ?)",
            (name, bc_id, note, uid))
        db.commit()
        return ok({'id': db.execute("SELECT last_insert_rowid()").fetchone()[0]})
    except Exception as e:
        return err(str(e))


@tt_bp.route('/api/tt/bcs/<int:bid>', methods=['PUT'])
@jwt_required()
@tt_write_required
def update_bc(bid):
    db = get_db()
    uid = get_uid()
    denied = _check_bc_owner(db, uid, bid)
    if denied:
        return denied
    data = parse_body()
    name = data.get('name', '').strip()
    note = data.get('note', '').strip()
    status = data.get('status')
    if name:
        db.execute(
            "UPDATE tt_bcs SET name=?, note=?, updated_at=datetime('now','localtime') WHERE id=?",
            (name, note, bid))
    if status in ('normal', 'banned'):
        db.execute(
            "UPDATE tt_bcs SET status=?, updated_at=datetime('now','localtime') WHERE id=?",
            (status, bid))
    db.commit()
    return ok()


@tt_bp.route('/api/tt/bcs/<int:bid>', methods=['DELETE'])
@jwt_required()
@tt_write_required
def delete_bc(bid):
    db = get_db()
    uid = get_uid()
    denied = _check_bc_owner(db, uid, bid)
    if denied:
        return denied
    db.execute("UPDATE tt_bcs SET deleted_at=datetime('now','localtime') WHERE id=?", (bid,))
    db.commit()
    return ok()


@tt_bp.route('/api/tt/bcs/options', methods=['GET'])
@jwt_required()
@tt_required
def bc_options():
    db = get_db()
    uid = get_uid()
    role = _get_role(db, uid)
    if role in CROSS_USER_ROLES:
        rows = db.execute(
            "SELECT id, name, bc_id FROM tt_bcs WHERE status='normal' AND deleted_at IS NULL ORDER BY name"
        ).fetchall()
    else:
        rows = db.execute(
            "SELECT id, name, bc_id FROM tt_bcs "
            "WHERE status='normal' AND deleted_at IS NULL AND owner_id=? ORDER BY name",
            (uid,)
        ).fetchall()
    return ok([dict(r) for r in rows])


# ==================== 产品管理 ====================

@tt_bp.route('/api/tt/products/list', methods=['GET'])
@jwt_required()
@tt_required
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
    if role in ('developer', 'admin'):
        # developer/admin 可按任意数字 runner 过滤
        if runner and runner.isdigit():
            where.append("p.id IN (SELECT product_id FROM tt_product_runners WHERE user_id=?)")
            params.append(int(runner))
    else:
        # 非 developer/admin 用户只能看到自己拥有或在跑的产品；忽略 runner 参数，避免横向越权
        where.append("(p.owner_id = ? OR p.id IN (SELECT product_id FROM tt_product_runners WHERE user_id=?))")
        params.append(uid)
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
    total = db.execute(f"SELECT COUNT(*) FROM tt_products p WHERE {where_clause}", params).fetchone()[0]
    rows = db.execute(
        f"SELECT p.* FROM tt_products p WHERE {where_clause} ORDER BY p.created_at DESC LIMIT ? OFFSET ?",
        params + [size, offset]
    ).fetchall()

    items = []
    for r in rows:
        item = dict(r)
        if r['sales_person_id']:
            sp = db.execute("SELECT name FROM sales_persons WHERE id=?", (r['sales_person_id'],)).fetchone()
            item['sales_person_name'] = sp['name'] if sp else ''
        if r['bc_id']:
            bc = db.execute("SELECT id, name, bc_id FROM tt_bcs WHERE id=? AND deleted_at IS NULL",
                            (r['bc_id'],)).fetchone()
            item['bc'] = dict(bc) if bc else None
        item['runners'] = [dict(u) for u in db.execute(
            "SELECT u.id, u.username, u.display_name FROM users u "
            "JOIN tt_product_runners pr ON pr.user_id = u.id WHERE pr.product_id=?", (r['id'],)
        ).fetchall()]
        item['packages'] = [dict(pk) for pk in db.execute(
            "SELECT pk.*, dc.is_delisted FROM tt_packages pk "
            "LEFT JOIN tt_delist_checks dc ON dc.package_id = pk.id "
            "WHERE pk.product_id=? ORDER BY pk.id", (r['id'],)
        ).fetchall()]
        items.append(item)

    return ok({'items': items, 'total': total, 'page': page, 'size': size})


@tt_bp.route('/api/tt/products/runner-products', methods=['GET'])
@jwt_required()
@tt_required
def runner_products():
    """获取当前用户的在跑产品（下拉框用）。"""
    db = get_db()
    uid = get_uid()
    rows = db.execute(
        "SELECT p.id, p.product_name FROM tt_products p "
        "JOIN tt_product_runners pr ON pr.product_id = p.id "
        "WHERE pr.user_id=? AND p.is_archived=0 ORDER BY p.product_name",
        (uid,)
    ).fetchall()
    return ok([dict(r) for r in rows])


@tt_bp.route('/api/tt/products/create', methods=['POST'])
@jwt_required()
@tt_write_required
@no_huguan
def create_product():
    db = get_db()
    data = parse_body()
    product_name = data.get('product_name', '').strip()
    kpi = data.get('kpi', '')
    region = data.get('region', '')
    status = data.get('status', 'active')
    bc_id = data.get('bc_id', None)
    sales_person_id = data.get('sales_person_id', None)
    agency_ratio = data.get('agency_ratio', 0)
    customer = data.get('customer', '')
    runner_ids = data.get('runner_ids', [])
    packages = data.get('packages', [])  # [{type, series_name, package_name, url}]

    if not product_name:
        return err('产品名不能为空')

    # 批量 packages 在 INSERT 前校验（type 二值 / 跑包必须包名）
    for pkg in packages:
        err_resp = _validate_package(pkg)
        if err_resp:
            return err_resp

    uid = get_uid()
    try:
        db.execute(
            "INSERT INTO tt_products (product_name, kpi, region, status, bc_id, "
            "sales_person_id, agency_ratio, customer, owner_id) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (product_name, kpi, region, status, bc_id, sales_person_id,
             agency_ratio, customer, uid))
        pid = db.execute("SELECT last_insert_rowid()").fetchone()[0]

        for ruid in runner_ids:
            db.execute("INSERT OR IGNORE INTO tt_product_runners (product_id, user_id) VALUES (?, ?)", (pid, ruid))
        for pkg in packages:
            db.execute(
                "INSERT INTO tt_packages (product_id, type, series_name, package_name, url, status) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (pid, pkg.get('type', 'package'), pkg.get('series_name', ''),
                 pkg.get('package_name', ''), pkg.get('url', ''), pkg.get('status', '')))

        db.commit()
        return ok({'id': pid})
    except Exception as e:
        return err(str(e))


@tt_bp.route('/api/tt/products/<int:pid>', methods=['PUT'])
@jwt_required()
@tt_write_required
@no_huguan
def update_product(pid):
    db = get_db()
    uid = get_uid()
    denied = _check_product_owner(db, uid, pid)
    if denied:
        return denied
    data = parse_body()

    # 只覆盖请求 JSON 中实际出现的 key，未传字段保留原值（与 update_package 语义一致）
    updates = {}
    if 'product_name' in data:
        product_name = (data.get('product_name') or '').strip()
        if not product_name:
            return err('产品名不能为空', 400)
        updates['product_name'] = product_name
    for key in ('kpi', 'region', 'status', 'customer'):
        if key in data:
            updates[key] = data.get(key, '')
    for key in ('bc_id', 'sales_person_id'):
        if key in data:
            updates[key] = data.get(key, None)
    if 'agency_ratio' in data:
        updates['agency_ratio'] = data.get('agency_ratio', 0)

    runner_ids = data.get('runner_ids', None)
    packages = data.get('packages', None)

    # packages 删除重建前先逐个校验（type 二值 / 跑包必须包名）
    if packages is not None:
        for pkg in packages:
            err_resp = _validate_package(pkg)
            if err_resp:
                return err_resp

    if updates:
        set_clause = ", ".join(f"{key}=?" for key in updates)
        params = list(updates.values()) + [pid]
        db.execute(
            f"UPDATE tt_products SET {set_clause}, updated_at=datetime('now','localtime') WHERE id=?",
            params)

    if runner_ids is not None:
        db.execute("DELETE FROM tt_product_runners WHERE product_id=?", (pid,))
        for ruid in runner_ids:
            db.execute("INSERT OR IGNORE INTO tt_product_runners (product_id, user_id) VALUES (?, ?)", (pid, ruid))

    if packages is not None:
        db.execute("DELETE FROM tt_packages WHERE product_id=?", (pid,))
        for pkg in packages:
            db.execute(
                "INSERT INTO tt_packages (product_id, type, series_name, package_name, url, status) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (pid, pkg.get('type', 'package'), pkg.get('series_name', ''),
                 pkg.get('package_name', ''), pkg.get('url', ''), pkg.get('status', '')))

    if not updates and runner_ids is None and packages is None:
        return ok()

    db.commit()
    return ok()


@tt_bp.route('/api/tt/products/<int:pid>', methods=['DELETE'])
@jwt_required()
@tt_write_required
@no_huguan
def delete_product(pid):
    db = get_db()
    uid = get_uid()
    denied = _check_product_owner(db, uid, pid)
    if denied:
        return denied
    db.execute("UPDATE tt_products SET is_archived=1, updated_at=datetime('now','localtime') WHERE id=?", (pid,))
    db.commit()
    return ok()


@tt_bp.route('/api/tt/products/<int:pid>/restore', methods=['POST'])
@jwt_required()
@tt_write_required
@no_huguan
def restore_product(pid):
    db = get_db()
    uid = get_uid()
    denied = _check_product_owner(db, uid, pid)
    if denied:
        return denied
    db.execute("UPDATE tt_products SET is_archived=0, updated_at=datetime('now','localtime') WHERE id=?", (pid,))
    db.commit()
    return ok()


@tt_bp.route('/api/tt/products/<int:pid>/detail', methods=['GET'])
@jwt_required()
@tt_required
def product_detail(pid):
    db = get_db()
    uid = get_uid()
    denied = _check_product_view(db, uid, pid)
    if denied:
        return denied
    prod = db.execute("SELECT * FROM tt_products WHERE id=?", (pid,)).fetchone()
    if not prod:
        return err('产品不存在', 404)
    item = dict(prod)
    if prod['bc_id']:
        bc = db.execute("SELECT id, name, bc_id FROM tt_bcs WHERE id=?", (prod['bc_id'],)).fetchone()
        item['bc'] = dict(bc) if bc else None
    item['runners'] = [dict(u) for u in db.execute(
        "SELECT u.id, u.username, u.display_name FROM users u "
        "JOIN tt_product_runners pr ON pr.user_id = u.id WHERE pr.product_id=?", (pid,)
    ).fetchall()]
    item['packages'] = [dict(pk) for pk in db.execute(
        "SELECT pk.*, dc.is_delisted FROM tt_packages pk "
        "LEFT JOIN tt_delist_checks dc ON dc.package_id = pk.id "
        "WHERE pk.product_id=? ORDER BY pk.id", (pid,)
    ).fetchall()]
    return ok(item)


# ==================== 投放对象（跑包 / PWA，单表） ====================

@tt_bp.route('/api/tt/products/<int:pid>/packages', methods=['POST'])
@jwt_required()
@tt_write_required
@no_huguan
def add_package(pid):
    db = get_db()
    uid = get_uid()
    denied = _check_product_owner(db, uid, pid)
    if denied:
        return denied
    data = parse_body()
    pkg_type = data.get('type', 'package')
    series_name = data.get('series_name', '').strip()
    package_name = data.get('package_name', '').strip()
    url = data.get('url', '').strip()
    status = data.get('status', '')

    err_resp = _validate_package(data)
    if err_resp:
        return err_resp

    try:
        db.execute(
            "INSERT INTO tt_packages (product_id, type, series_name, package_name, url, status) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (pid, pkg_type, series_name, package_name, url, status))
        db.commit()
        return ok({'id': db.execute("SELECT last_insert_rowid()").fetchone()[0]})
    except Exception as e:
        return err(str(e))


@tt_bp.route('/api/tt/packages/<int:pkg_id>', methods=['PUT'])
@jwt_required()
@tt_write_required
@no_huguan
def update_package(pkg_id):
    db = get_db()
    uid = get_uid()
    product_id = _get_pkg_product_id(db, pkg_id)
    if product_id is None:
        return err('无权限', 403)
    denied = _check_product_owner(db, uid, product_id)
    if denied:
        return denied
    existing = db.execute("SELECT * FROM tt_packages WHERE id=?", (pkg_id,)).fetchone()
    if existing is None:
        return err('无权限', 403)
    data = parse_body()

    # 只覆盖请求 JSON 中实际出现的 key，未传字段保留原值（避免部分更新清空其它字段）
    updates = {}
    for key in ('series_name', 'package_name', 'url'):
        if key in data:
            updates[key] = data.get(key, '').strip()
    if 'status' in data:
        updates['status'] = data.get('status', '')
    if 'type' in data:
        updates['type'] = data.get('type', '')

    # re-enforce type 规则：package 必须填写包名（App Store 链接除外，与 add_package 语义一致）
    pkg_type = updates.get('type', existing['type'])
    if pkg_type == 'package' and 'package_name' in updates and not updates['package_name']:
        # 本次显式传了 url 就用本次的（空串即「清空」→ 不放行）；
        # 本次没传 url 才回落库里的 url 判断是不是苹果链接。
        if 'url' in updates:
            effective_url = updates['url']
        else:
            effective_url = existing['url']
        if not _is_appstore_url(effective_url):
            return err('跑包必须填写包名', 400)

    if not updates:
        return ok()

    set_clause = ", ".join(f"{key}=?" for key in updates)
    params = list(updates.values()) + [pkg_id]
    db.execute(
        f"UPDATE tt_packages SET {set_clause}, updated_at=datetime('now','localtime') WHERE id=?",
        params)
    db.commit()
    return ok()


@tt_bp.route('/api/tt/packages/<int:pkg_id>', methods=['DELETE'])
@jwt_required()
@tt_write_required
@no_huguan
def delete_package(pkg_id):
    db = get_db()
    uid = get_uid()
    product_id = _get_pkg_product_id(db, pkg_id)
    if product_id is None:
        return err('无权限', 403)
    denied = _check_product_owner(db, uid, product_id)
    if denied:
        return denied
    db.execute("DELETE FROM tt_delist_checks WHERE package_id=?", (pkg_id,))
    db.execute("DELETE FROM tt_delist_notifications WHERE package_id=?", (pkg_id,))
    db.execute("DELETE FROM tt_packages WHERE id=?", (pkg_id,))
    db.commit()
    return ok()


@tt_bp.route('/api/tt/packages/batch-delete', methods=['POST'])
@jwt_required()
@tt_write_required
@no_huguan
def batch_delete_packages():
    db = get_db()
    uid = get_uid()
    data = parse_body()
    ids = data.get('ids') or []
    if not ids:
        return err('请选择要删除的投放对象')
    # 任一投放对象非本人所有则整体拒绝，避免部分删除
    for pkg_id in ids:
        product_id = _get_pkg_product_id(db, pkg_id)
        if product_id is None:
            return err('无权限', 403)
        denied = _check_product_owner(db, uid, product_id)
        if denied:
            return denied
    placeholders = ",".join(["?"] * len(ids))
    db.execute(f"DELETE FROM tt_delist_checks WHERE package_id IN ({placeholders})", ids)
    db.execute(f"DELETE FROM tt_delist_notifications WHERE package_id IN ({placeholders})", ids)
    db.execute(f"DELETE FROM tt_packages WHERE id IN ({placeholders})", ids)
    db.commit()
    return ok({'deleted': len(ids)})


# ==================== 掉包检测（仅跑包 type='package'） ====================

# TT Telegram 机器人配置（独立于 GG 的 telegram 节点）
_TT_TG_CONFIG_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "config", "config.json")
_TT_TG_LOCAL_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "config", "config.local.json")


def _load_tt_telegram_config() -> dict:
    """读取 TT 独立 Telegram 机器人配置（tt_telegram 节点）。

    config.local.json 覆盖 config.json（与 main.py 深合并口径一致）。
    每次调用重新读取，便于运行期改配置无需重启。
    """
    cfg = {}
    for path in (_TT_TG_CONFIG_PATH, _TT_TG_LOCAL_PATH):
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, json.JSONDecodeError):
            continue
        node = data.get("tt_telegram") or {}
        if isinstance(node, dict):
            cfg.update({k: v for k, v in node.items() if v})
    return cfg


def send_tt_delist_notifications(db, pkgs, title: str = "TT-Server") -> int:
    """按产品分组发送 TT 掉包 Telegram 群组通知。

    Args:
        db: 数据库连接
        pkgs: 掉包包字典列表，每项含 product_id, product_name, series_name
        title: 消息标题前缀

    Returns:
        实际发送的通知条数（配置缺失或发送失败均为 0）
    """
    cfg = _load_tt_telegram_config()
    if not (cfg.get("bot_token") and cfg.get("chat_id") and pkgs):
        return 0

    import telegram_sender as _tg_sender
    tg_config = _tg_sender._TelegramConfig(
        bot_token=cfg.get("bot_token", ""),
        chat_id=cfg.get("chat_id", ""),
        parse_mode=cfg.get("parse_mode", "HTML"),
    )

    # 按 product_id 分组（dict 保持插入顺序）
    groups = {}
    for pkg in pkgs:
        groups.setdefault(pkg.get("product_id"), []).append(pkg)

    sent = 0
    for pid, group_pkgs in groups.items():
        product_name = group_pkgs[0].get("product_name", "") if group_pkgs else ""
        series_names = []
        for pkg in group_pkgs:
            sn = (pkg.get("series_name") or "").strip()
            if sn and sn not in series_names:
                series_names.append(sn)

        # 在跑人员从 tt_product_runners 独立表取（非 GG 的 runner_ids JSON 列）
        usernames = []
        if pid is not None:
            rows = db.execute(
                "SELECT u.telegram_username FROM tt_product_runners pr "
                "JOIN users u ON u.id = pr.user_id "
                "WHERE pr.product_id = ? AND u.telegram_username IS NOT NULL "
                "AND u.telegram_username != ''",
                (pid,)
            ).fetchall()
            usernames = [r["telegram_username"] for r in rows]

        if _tg_sender.send_product_delist_notification(
                tg_config, product_name, series_names, usernames, title=title):
            sent += 1

    return sent


@tt_bp.route('/api/tt/products/<int:pid>/check-delist', methods=['POST'])
@jwt_required()
@tt_write_required
@no_huguan
def check_delist(pid):
    import delist_checker
    import datetime
    db = get_db()
    uid = get_uid()
    denied = _check_product_owner(db, uid, pid)
    if denied:
        return denied

    # 只检测正常状态的跑包（口径与 GG 手动检测一致）：
    # 已掉包/暂停/没事件/拒登的包不检测，也不会触发 Telegram 通知
    pkgs = db.execute(
        "SELECT id, package_name, series_name, url FROM tt_packages "
        "WHERE product_id=? AND type='package' AND url != '' "
        "AND (status IS NULL OR status='' OR status='0' OR status='normal')",
        (pid,)
    ).fetchall()
    if not pkgs:
        return ok({'results': [], 'message': '没有需要检测的跑包'})

    pkg_list = [dict(p) for p in pkgs]
    # 与 GG 手动 / GG 定时 / TT 定时口径一致：走代理池，降低限流概率。
    # 局部导入：main.py 导入并注册本 Blueprint，模块级互导会成环。
    from main import _build_delist_proxy_pool
    results = delist_checker.check_product_packages(pid, pkg_list, _build_delist_proxy_pool())

    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    dropped = []
    for r in results:
        # 判定未知（限流/服务端异常）：不写库，保留上一轮判定结果
        if r["is_delisted"] is None:
            continue
        db.execute(
            "INSERT OR REPLACE INTO tt_delist_checks(package_id, is_delisted, checked_at) "
            "VALUES(?, ?, ?)",
            (r["package_id"], 1 if r["is_delisted"] else 0, now))
    db.commit()

    # 检测到掉包 → TT 机器人群组通知（按产品聚合，@在跑人员）
    if any(r["is_delisted"] for r in results):
        prod = db.execute(
            "SELECT product_name FROM tt_products WHERE id=?", (pid,)
        ).fetchone()
        pname = prod["product_name"] if prod else ""
        dropped = [
            {"product_id": pid, "product_name": pname, "series_name": p.get("series_name", "")}
            for p, r in zip(pkg_list, results) if r["is_delisted"]
        ]
        try:
            send_tt_delist_notifications(db, dropped)
        except Exception as e:  # 通知失败不影响检测结果返回
            print(f"[TT-Telegram] 发送异常: {e}")

    return ok({'results': results})


@tt_bp.route('/api/tt/products/delist-status', methods=['GET'])
@jwt_required()
@tt_required
def delist_status():
    """获取当前用户可见的掉包检测状态。"""
    db = get_db()
    uid = get_uid()
    role = _get_role(db, uid)

    base_sql = (
        "SELECT dc.package_id, dc.is_delisted, dc.checked_at, "
        "pkg.series_name, pkg.package_name, pkg.url, pkg.status AS pkg_status, "
        "prod.product_name "
        "FROM tt_delist_checks dc "
        "JOIN tt_packages pkg ON dc.package_id = pkg.id "
        "JOIN tt_products prod ON pkg.product_id = prod.id "
    )
    if role in ('developer', 'admin'):
        where = "WHERE dc.is_delisted = 1 AND prod.is_archived = 0 "
        params = []
    else:
        where = (
            "WHERE dc.is_delisted = 1 AND prod.is_archived = 0 AND "
            "(prod.owner_id = ? OR pkg.product_id IN "
            "(SELECT product_id FROM tt_product_runners WHERE user_id=?)) "
        )
        params = [uid, uid]

    rows = db.execute(base_sql + where + "ORDER BY dc.checked_at DESC", params).fetchall()
    delisted = [dict(r) for r in rows]
    return ok({'delisted_packages': delisted})


@tt_bp.route('/api/tt/delist/pending', methods=['GET'])
@jwt_required()
def delist_pending():
    """获取当前用户待处理的 TT 掉包通知列表（按产品聚合）。

    返回两种类型的通知：
    - type='first': 首次通知（该包尚未弹出过）
    - type='reminder': 提醒通知（已关闭超过 3 分钟且未处理）

    可见性与 delist_status 一致：跨用户角色看全部，其余按 owner_id 或在跑人员。
    """
    import datetime
    db = get_db()
    uid = get_uid()

    # 平台闸门与 /api/tt/products/delist-status（@tt_required）完全一致：
    # 非 TT 平台用户（含 GG/FB 的 admin）不受理。区别在于这里静默返回空，
    # 不抛 403 —— 本接口被前端每 30s 轮询，抛错会在浏览器留下持续报错噪声。
    # developer / 户管 属 PLATFORM_SWITCH_ROLES 直接放行，户管不命中任何
    # TT 产品 → 天然返回空。
    if require_platform('tt') is not None:
        return ok({'notifications': []})

    role = _get_role(db, uid)

    base_sql = (
        "SELECT dc.package_id, dc.is_delisted, dc.checked_at, "
        "pkg.product_id, pkg.series_name, pkg.package_name, pkg.url, pkg.status AS pkg_status, "
        "prod.product_name, "
        "dn.first_notified, dn.dismissed_at, dn.reminder_count "
        "FROM tt_delist_checks dc "
        "JOIN tt_packages pkg ON dc.package_id = pkg.id "
        "JOIN tt_products prod ON pkg.product_id = prod.id "
        "LEFT JOIN tt_delist_notifications dn ON dc.package_id = dn.package_id AND dn.user_id = ? "
        "WHERE dc.is_delisted = 1 "
        "AND pkg.type = 'package' "  # 与两处检测口径一致：掉包只针对跑包，PWA 不通知
        "AND (pkg.status IS NULL OR pkg.status = '' OR pkg.status = '0' "
        "     OR pkg.status NOT IN ('dropped', 'paused')) "
        "AND (prod.status IS NULL OR prod.status = '' OR prod.status = 'active') "
        "AND (prod.is_archived IS NULL OR prod.is_archived = 0) "
    )
    if role in ('developer', 'admin'):
        params = [uid]
    else:
        base_sql += (
            "AND (prod.owner_id = ? OR pkg.product_id IN "
            "(SELECT product_id FROM tt_product_runners WHERE user_id=?)) "
        )
        params = [uid, uid, uid]

    rows = db.execute(base_sql + "ORDER BY dc.checked_at DESC", params).fetchall()

    now = datetime.datetime.now(datetime.timezone.utc)
    pkg_notifications = []
    for r in rows:
        d = dict(r)
        pkg_status = (d.get("pkg_status") or "").strip()
        if pkg_status == "dropped":
            continue  # 已标记为掉包的不需要通知

        first_notified = d.get("first_notified") or 0
        dismissed_at = d.get("dismissed_at")

        if not first_notified:
            pkg_notifications.append({
                "product_id": d["product_id"],
                "product_name": d["product_name"],
                "series_name": d["series_name"] or "",
                "package_id": d["package_id"],
                "type": "first",
                "reminder_count": 0,
            })
        elif dismissed_at:
            try:
                dismissed_dt = datetime.datetime.fromisoformat(dismissed_at)
                if dismissed_dt.tzinfo is None:
                    dismissed_dt = dismissed_dt.replace(tzinfo=datetime.timezone.utc)
                if (now - dismissed_dt).total_seconds() >= 180:  # 3 分钟
                    pkg_notifications.append({
                        "product_id": d["product_id"],
                        "product_name": d["product_name"],
                        "series_name": d["series_name"] or "",
                        "package_id": d["package_id"],
                        "type": "reminder",
                        "reminder_count": d.get("reminder_count", 0),
                    })
            except (ValueError, TypeError):
                pass

    # 按 product_id 聚合（dict 保持插入顺序）
    groups = {}
    for n in pkg_notifications:
        pid = n["product_id"]
        g = groups.setdefault(pid, {
            "product_id": pid,
            "product_name": n["product_name"],
            "series_names": [],
            "package_ids": [],
            "type": n["type"],
            "reminder_count": 0,
            "platform": "tt",
        })
        sn = (n["series_name"] or "").strip()
        if sn and sn not in g["series_names"]:
            g["series_names"].append(sn)
        if n["package_id"] not in g["package_ids"]:
            g["package_ids"].append(n["package_id"])
        if n["type"] == "first":
            g["type"] = "first"  # first 优先于 reminder
        if n["reminder_count"] > g["reminder_count"]:
            g["reminder_count"] = n["reminder_count"]

    return ok({'notifications': list(groups.values())})


@tt_bp.route('/api/tt/delist/dismiss', methods=['POST'])
@jwt_required()
def delist_dismiss():
    """记录用户关闭 TT 掉包通知的时间（支持批量 package_ids）。"""
    import datetime
    uid = get_uid()
    data = parse_body()
    package_ids = data.get("package_ids")
    if not package_ids:
        package_id = data.get("package_id")
        if package_id:
            package_ids = [package_id]
    if not package_ids:
        return err("缺少 package_ids", 400)
    if not isinstance(package_ids, list):
        package_ids = [package_ids]

    db = get_db()
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    for package_id in package_ids:
        existing = db.execute(
            "SELECT id FROM tt_delist_notifications WHERE package_id=? AND user_id=?",
            (package_id, uid)
        ).fetchone()
        if existing:
            db.execute(
                "UPDATE tt_delist_notifications SET dismissed_at=?, "
                "reminder_count=reminder_count+1 WHERE package_id=? AND user_id=?",
                (now, package_id, uid)
            )
        else:
            db.execute(
                "INSERT INTO tt_delist_notifications(package_id, user_id, first_notified, dismissed_at, reminder_count) "
                "VALUES(?, ?, 1, ?, 0)",
                (package_id, uid, now)
            )
    db.commit()
    return ok()


# ==================== 合并 / 粘贴解析 / 素材 / 用户 ====================

@tt_bp.route('/api/tt/products/merge', methods=['POST'])
@jwt_required()
@tt_write_required
@no_huguan
def products_merge():
    """合并多个产品到主产品（迁移投放对象 + 在跑人员，删除副产品）。"""
    db = get_db()
    uid = get_uid()
    data = parse_body()
    master_id = data.get("master_id")
    merge_ids = data.get("merge_ids") or []

    if not master_id or not merge_ids:
        return err('请指定主产品和被合并产品')
    if master_id in merge_ids:
        return err('主产品不能在被合并列表中')

    # 任一产品非本人所有则整体拒绝（含不存在的情况，反枚举 403），不做部分合并
    denied = _check_product_owner(db, uid, master_id)
    if denied:
        return denied
    for mid in merge_ids:
        denied = _check_product_owner(db, uid, mid)
        if denied:
            return denied

    db.execute("PRAGMA foreign_keys=OFF")
    merged_packages = 0
    for mid in merge_ids:
        # 迁移投放对象
        for p in db.execute("SELECT * FROM tt_packages WHERE product_id=?", (mid,)).fetchall():
            existing = db.execute(
                "SELECT id FROM tt_packages WHERE product_id=? AND package_name=? AND url=?",
                (master_id, p["package_name"], p["url"])
            ).fetchone()
            if not existing:
                db.execute(
                    "INSERT INTO tt_packages (product_id, type, series_name, package_name, url, status) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (master_id, p["type"], p["series_name"], p["package_name"], p["url"], p["status"]))
                merged_packages += 1

        # 迁移在跑人员
        for pr in db.execute("SELECT user_id FROM tt_product_runners WHERE product_id=?", (mid,)).fetchall():
            db.execute("INSERT OR IGNORE INTO tt_product_runners (product_id, user_id) VALUES (?, ?)",
                       (master_id, pr["user_id"]))

        # 清理并删除副产品
        db.execute("DELETE FROM tt_product_assets WHERE product_id=?", (mid,))
        # 掉包检测结果与通知都按 package_id 挂载，且上面关了外键级联（PRAGMA
        # foreign_keys=OFF），必须在 tt_packages 删除**之前**按包清理，否则遗留
        # 指向已删包的孤儿行（口径与 GG 合并一致：合并即丢弃副产品的掉包状态）
        db.execute(
            "DELETE FROM tt_delist_notifications WHERE package_id IN "
            "(SELECT id FROM tt_packages WHERE product_id=?)", (mid,))
        db.execute(
            "DELETE FROM tt_delist_checks WHERE package_id IN "
            "(SELECT id FROM tt_packages WHERE product_id=?)", (mid,))
        db.execute("DELETE FROM tt_packages WHERE product_id=?", (mid,))
        db.execute("DELETE FROM tt_product_runners WHERE product_id=?", (mid,))
        db.execute("DELETE FROM tt_products WHERE id=?", (mid,))

    db.execute("PRAGMA foreign_keys=ON")
    db.commit()
    return ok({'merged_packages': merged_packages, 'merged_products': len(merge_ids)})


@tt_bp.route('/api/tt/products/import-text', methods=['POST'])
@jwt_required()
@tt_required
@no_huguan
def import_text():
    """粘贴文本解析成投放对象列表（支持 Google Play 与 App Store 链接）。"""
    data = parse_body()
    text = (data.get("text") or "").strip()
    prefix = (data.get("prefix") or "").strip()
    suffix = (data.get("suffix") or "").strip()
    if not text:
        return err('未提供文本内容')

    links = [m.group(0) for m in _LINK_RE.finditer(text)]
    results = []
    for link in links:
        # 苹果链接没有安卓包名，也不自动填数字 id（用户裁定：包名留空）
        pkg = "" if _is_appstore_url(link) else _extract_pkg_from_url(link)
        series = _guess_series(text, link)
        if prefix:
            if not series.startswith(prefix):
                prefix_base = prefix.split("-")[0]
                series_base = series.split("-")[0] if "-" in series else series
                if prefix_base == series_base:
                    rest = series[len(series_base):].lstrip("-")
                    sep = "" if prefix.endswith("-") else "-"
                    series = prefix + sep + rest if rest else prefix
                else:
                    sep = "" if prefix.endswith("-") else "-"
                    series = prefix + sep + series
        if suffix:
            if not series.endswith("-" + suffix) and series != suffix:
                series = series + "-" + suffix
        results.append({"type": "package", "series_name": series, "package_name": pkg, "url": link})
    return ok({'parsed': results})


# App Store 的两个合法 host（老域名 itunes.apple.com 会跳转到 apps.apple.com）
_APPSTORE_HOSTS = frozenset({"apps.apple.com", "itunes.apple.com"})


def _is_appstore_url(url):
    """URL 的 host 是否属于 App Store。

    必须解析出 host 后**全等**比较：用子串匹配会让
    `https://evil.com/?u=apps.apple.com` 这类 URL 误判为苹果链接。
    """
    if not url:
        return False
    try:
        host = urllib.parse.urlsplit(str(url).strip()).hostname or ""
    except ValueError:
        return False
    return host.lower() in _APPSTORE_HOSTS


def _extract_pkg_from_url(url):
    m = re.search(r'[?&]id=([\w.]+)', url)
    return m.group(1) if m else ""


def _guess_series(text, link):
    """从文本猜测链接对应的系列名（与 GG 逻辑一致）。"""
    lines = text.split("\n")
    link_idx = -1
    for i, line in enumerate(lines):
        if link in line:
            link_idx = i
            break
    if link_idx < 0:
        return _extract_pkg_from_url(link)
    for j in range(max(0, link_idx - 8), link_idx):
        l = lines[j].strip()
        if "神包上线" in l:
            name = l.split("神包上线：")[-1].split("神包上线")[-1].strip()
            if name:
                return name
    for j in range(max(0, link_idx - 2), min(len(lines), link_idx + 5)):
        l = lines[j].strip()
        for prefix in ["广告命名：", "广告命名:", "渠道命名：", "渠道命名:"]:
            if prefix in l:
                name = l.split(prefix)[-1].strip()
                if name:
                    return name
    for j in range(link_idx, max(-1, link_idx - 10), -1):
        l = lines[j].strip()
        if "神包上线" in l:
            continue
        if ("APK" in l or ("包" in l and re.search(r'包\d+', l))) and "-" in l:
            for token in l.split():
                token = re.sub(r'^[^\w]*', '', token)
                if '-' in token and len(token) > 2:
                    return token
    for j in range(link_idx + 1, min(len(lines), link_idx + 6)):
        l = lines[j].strip()
        if "应用名：" in l or "应用名:" in l:
            name = l.split("应用名：")[-1].split("应用名:")[-1].strip()
            if name:
                return name
    for j in range(max(0, link_idx - 3), min(len(lines), link_idx)):
        l = lines[j].strip()
        if "名称：" in l or "名称:" in l:
            name = l.split("名称：")[-1].split("名称:")[-1].strip()
            if name:
                return name
    for j in range(link_idx, max(-1, link_idx - 3), -1):
        l = lines[j].strip()
        tokens = l.split()
        if tokens:
            first = re.sub(r'^[^\w]*', '', tokens[0])
            if '-' in first and len(first) > 2:
                return first
    return _extract_pkg_from_url(link)


# ==================== 素材关联（共享视频库） ====================

@tt_bp.route('/api/tt/products/<int:pid>/assets', methods=['GET'])
@jwt_required()
@tt_required
def list_assets(pid):
    db = get_db()
    uid = get_uid()
    denied = _check_product_view(db, uid, pid)
    if denied:
        return denied
    rows = db.execute("""
        SELECT v.*, pa.added_by, pa.added_at, u.display_name AS added_by_name
        FROM tt_product_assets pa
        JOIN videos v ON pa.video_id = v.id AND pa.video_owner_id = v.owner_id
        LEFT JOIN users u ON pa.added_by = u.id
        WHERE pa.product_id = ?
        ORDER BY pa.added_at DESC
    """, (pid,)).fetchall()
    return ok({'assets': [dict(r) for r in rows]})


@tt_bp.route('/api/tt/products/<int:pid>/assets', methods=['POST'])
@jwt_required()
@tt_write_required
@no_huguan
def add_assets(pid):
    """从共享视频库选择已有视频建立关联。body: { video_ids: [...] }。"""
    db = get_db()
    uid = get_uid()
    denied = _check_product_owner(db, uid, pid)
    if denied:
        return denied
    data = parse_body()
    video_ids = data.get('video_ids') or []
    if not video_ids:
        return err('请选择至少一个视频')

    added = 0
    for vid in video_ids:
        existing = db.execute(
            "SELECT id FROM tt_product_assets WHERE product_id=? AND video_id=?", (pid, vid)
        ).fetchone()
        if existing:
            continue
        # 记录视频真实 owner，保证 list_assets 的 JOIN 能命中
        video = db.execute("SELECT owner_id FROM videos WHERE id=?", (vid,)).fetchone()
        if not video:
            continue
        db.execute(
            "INSERT INTO tt_product_assets(product_id, video_id, video_owner_id, added_by) "
            "VALUES(?,?,?,?)", (pid, vid, video['owner_id'], uid))
        added += 1
    db.commit()
    return ok({'added': added})


@tt_bp.route('/api/tt/products/<int:pid>/assets/<video_id>', methods=['DELETE'])
@jwt_required()
@tt_write_required
@no_huguan
def delete_asset(pid, video_id):
    db = get_db()
    uid = get_uid()
    denied = _check_product_owner(db, uid, pid)
    if denied:
        return denied
    db.execute("DELETE FROM tt_product_assets WHERE product_id=? AND video_id=?", (pid, video_id))
    db.commit()
    return ok()


# ==================== 用户查询（TT 平台） ====================

@tt_bp.route('/api/tt/users', methods=['GET'])
@jwt_required()
@tt_required
def list_tt_users():
    """返回 TT 平台用户列表（供「在跑人员」选择器使用）。"""
    db = get_db()
    rows = db.execute(
        "SELECT id, username, display_name, platform FROM users "
        "WHERE (platform = 'tt' OR role = 'developer') AND role != 'hidden' "
        "ORDER BY display_name, username"
    ).fetchall()
    return ok({"users": [dict(r) for r in rows]})


# ==================== 设置（Google 表格配置） ====================

# 内置 key = 全局共享（仅 admin/developer 可改）；my_dashboard 为投手私有（各配各的看板）
_TT_SHEET_MAPPING_KEYS = {"accounts", "recharge", "recycle"}
_TT_SHEET_MAPPING_DEFAULTS = {
    "accounts": "账户明细",
    "recharge": "充值表",
    "my_dashboard": "我的看板",
    "recycle": "回收户清单",
}


def _get_tt_user_sheet_mappings(db, user_id):
    """读取用户私有的 TT sheet 映射覆盖值（config 表，key=tt_sheet_mappings_<uid>）。"""
    row = db.execute("SELECT value FROM config WHERE key=?", (f"tt_sheet_mappings_{user_id}",)).fetchone()
    if row and row["value"]:
        try:
            loaded = json.loads(row["value"])
            if isinstance(loaded, dict):
                return loaded
        except Exception:
            pass
    return {}


def _save_tt_user_sheet_mappings(db, user_id, mappings):
    """保存用户私有的 TT sheet 映射覆盖值（config 表）。"""
    db.execute("INSERT OR REPLACE INTO config(key,value) VALUES(?,?)",
               (f"tt_sheet_mappings_{user_id}", json.dumps(mappings, ensure_ascii=False)))


@tt_bp.route('/api/tt/settings', methods=['GET'])
@jwt_required()
@tt_required
def tt_settings_get():
    """返回 TT 平台的 Google 表格配置（三层叠加：内置默认 → 全局 tags → 用户私有 config）。"""
    db = get_db()
    sheet_id = ""
    row = db.execute("SELECT value FROM tags WHERE key='tt_sheet_id'").fetchone()
    if row and row["value"]:
        sheet_id = row["value"]
    mappings = dict(_TT_SHEET_MAPPING_DEFAULTS)
    sm_row = db.execute("SELECT value FROM tags WHERE key='tt_sheet_mappings'").fetchone()
    if sm_row and sm_row["value"]:
        try:
            loaded = json.loads(sm_row["value"])
            if isinstance(loaded, dict):
                mappings.update(loaded)
        except Exception:
            pass
    # 用户私有覆盖（投手各自配置的「我的看板」）
    mappings.update(_get_tt_user_sheet_mappings(db, get_uid()))
    return ok({"settings": {"sheet_id": sheet_id, "sheet_mappings": mappings}})


@tt_bp.route('/api/tt/settings', methods=['POST'])
@jwt_required()
@tt_required
def tt_settings_save():
    """保存 TT 平台的 Google 表格配置。

    - sheet_id：仅 admin/developer 可写全局 tag
    - accounts/recharge/recycle 三个内置 key：仅 admin 写全局 tag
    - my_dashboard：投手私有，所有用户写各自 config
    """
    db = get_db()
    uid = get_uid()
    role = _get_role(db, uid)
    is_admin = role in ('admin', 'developer')
    data = parse_body()
    if 'sheet_id' in data and is_admin:
        db.execute("INSERT OR REPLACE INTO tags(key,value) VALUES(?,?)",
                   ("tt_sheet_id", str(data['sheet_id'] or '')))
    if 'sheet_mappings' in data:
        mappings = data['sheet_mappings']
        if not isinstance(mappings, dict):
            mappings = {}
        if is_admin:
            global_mappings = {k: mappings[k] for k in _TT_SHEET_MAPPING_KEYS if k in mappings}
            if global_mappings:
                db.execute("INSERT OR REPLACE INTO tags(key,value) VALUES(?,?)",
                           ("tt_sheet_mappings", json.dumps(global_mappings, ensure_ascii=False)))
            _save_tt_user_sheet_mappings(db, uid, mappings)
        else:
            # 投手只保存自己的「我的看板」sheet 名
            _save_tt_user_sheet_mappings(db, uid, {"my_dashboard": mappings.get("my_dashboard", "")})
    db.commit()
    return ok()


# ==================== 数据导出 / 导入 ====================

@tt_bp.route('/api/tt/data/export', methods=['GET'])
@jwt_required()
@tt_required
def tt_data_export():
    """导出当前用户的 TT 数据为 JSON 文件下载（不含 tt_product_assets）。"""
    import datetime
    from flask import Response
    db = get_db()
    uid = get_uid()

    bcs = [dict(r) for r in db.execute(
        "SELECT * FROM tt_bcs WHERE owner_id=? AND deleted_at IS NULL", (uid,)).fetchall()]
    products = [dict(r) for r in db.execute(
        "SELECT * FROM tt_products WHERE owner_id=? AND is_archived=0", (uid,)).fetchall()]

    packages, runners, delist_checks = [], [], []
    product_ids = [p['id'] for p in products]
    if product_ids:
        p_ph = ",".join(["?"] * len(product_ids))
        packages = [dict(r) for r in db.execute(
            f"SELECT * FROM tt_packages WHERE product_id IN ({p_ph})", product_ids).fetchall()]
        runners = [dict(r) for r in db.execute(
            f"SELECT * FROM tt_product_runners WHERE product_id IN ({p_ph})", product_ids).fetchall()]
        pkg_ids = [p['id'] for p in packages]
        if pkg_ids:
            k_ph = ",".join(["?"] * len(pkg_ids))
            delist_checks = [dict(r) for r in db.execute(
                f"SELECT * FROM tt_delist_checks WHERE package_id IN ({k_ph})", pkg_ids).fetchall()]

    sales_persons = [dict(r) for r in db.execute(
        "SELECT id, name FROM sales_persons WHERE platform='tt'").fetchall()]

    export_data = {
        "version": 1,
        "exported_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "source": "tt-server",
        "data": {
            "bcs": bcs,
            "products": products,
            "packages": packages,
            "product_runners": runners,
            "delist_checks": delist_checks,
            "sales_persons": sales_persons,
        },
    }
    json_str = json.dumps(export_data, ensure_ascii=False, indent=2)
    date_str = datetime.datetime.now().strftime("%Y%m%d")
    filename = f"tt-server-export-{uid}-{date_str}.json"
    return Response(json_str, mimetype="application/json",
                    headers={"Content-Disposition": f"attachment; filename={filename}"})


@tt_bp.route('/api/tt/data/import', methods=['POST'])
@jwt_required()
@tt_write_required
def tt_data_import():
    """导入 TT 导出的 JSON 文件到当前用户（按外键依赖顺序重建，外键重映射）。"""
    db = get_db()
    uid = get_uid()
    if 'file' not in request.files:
        return err('请上传文件')
    file = request.files['file']
    if not file.filename or not file.filename.lower().endswith('.json'):
        return err('仅支持 .json 文件')
    if file.content_length and file.content_length > 20 * 1024 * 1024:
        return err('文件过大，最大 20MB')
    try:
        payload = json.loads(file.read())
    except Exception:
        return err('文件解析失败，请上传合法的 JSON 文件')
    data = payload.get('data', payload) if isinstance(payload, dict) else {}
    if not isinstance(data, dict):
        return err('无效的导出文件结构')

    def _as_dict_list(x):
        return [e for e in (x if isinstance(x, list) else []) if isinstance(e, dict)]

    bcs = _as_dict_list(data.get('bcs'))
    products = _as_dict_list(data.get('products'))
    packages = _as_dict_list(data.get('packages'))
    runners = _as_dict_list(data.get('product_runners'))
    delist_checks = _as_dict_list(data.get('delist_checks'))
    sales_persons = _as_dict_list(data.get('sales_persons'))

    # 户管无产品/包编辑权：导入载荷含产品/包时拒绝。
    # runners / delist_checks 依赖 products / packages 的重映射，缺前者时本就惰性空转，无需单独拦。
    if products or packages:
        err_resp = reject_huguan()
        if err_resp:
            return err_resp

    db.execute("PRAGMA foreign_keys=OFF")
    runner_count = 0
    delist_count = 0
    try:
        # 1. 商务人员（按 name 匹配/新建 TT 平台，建 old_id→new_id 映射）
        sp_map = {}
        for sp in sales_persons:
            name = (sp.get('name') or '').strip()
            sid = sp.get('id')
            if not name or sid is None:
                continue
            existing = db.execute(
                "SELECT id FROM sales_persons WHERE name=? AND platform='tt'", (name,)).fetchone()
            if existing:
                sp_map[sid] = existing['id']
            else:
                db.execute("INSERT INTO sales_persons(name, owner_id, platform) VALUES(?,?,?)",
                           (name, uid, 'tt'))
                sp_map[sid] = db.execute("SELECT last_insert_rowid()").fetchone()[0]

        # 2. BC（优先复用本人 BC；否则按全局唯一 bc_id 复用——bc_id 全局 UNIQUE，无法重复建）
        bc_map = {}
        for bc in bcs:
            bc_id = (bc.get('bc_id') or '').strip()
            bid = bc.get('id')
            if not bc_id or bid is None:
                continue
            existing = db.execute(
                "SELECT id FROM tt_bcs WHERE bc_id=? AND owner_id=? AND deleted_at IS NULL",
                (bc_id, uid)).fetchone()
            if not existing:
                existing = db.execute(
                    "SELECT id FROM tt_bcs WHERE bc_id=? AND deleted_at IS NULL", (bc_id,)).fetchone()
            if existing:
                bc_map[bid] = existing['id']
            else:
                db.execute(
                    "INSERT INTO tt_bcs(name, bc_id, note, status, owner_id) VALUES(?,?,?,?,?)",
                    (bc.get('name', ''), bc_id, bc.get('note', ''), bc.get('status', 'normal'), uid))
                bc_map[bid] = db.execute("SELECT last_insert_rowid()").fetchone()[0]

        # 3. 产品（owner_id 固定为当前用户，映射 bc/sales_person）
        prod_map = {}
        for prod in products:
            pid = prod.get('id')
            if not (prod.get('product_name') or '').strip() or pid is None:
                continue
            db.execute(
                "INSERT INTO tt_products (product_name, kpi, region, status, bc_id, "
                "sales_person_id, agency_ratio, customer, owner_id, is_archived) "
                "VALUES (?,?,?,?,?,?,?,?,?,?)",
                (prod.get('product_name', ''), prod.get('kpi', ''), prod.get('region', ''),
                 prod.get('status', 'active'), bc_map.get(prod.get('bc_id')),
                 sp_map.get(prod.get('sales_person_id')), prod.get('agency_ratio', 0),
                 prod.get('customer', ''), uid, 0))
            prod_map[pid] = db.execute("SELECT last_insert_rowid()").fetchone()[0]

        # 4. 包
        pkg_map = {}
        for pkg in packages:
            old_pid = pkg.get('product_id')
            pkg_id = pkg.get('id')
            if old_pid not in prod_map or pkg_id is None:
                continue
            db.execute(
                "INSERT INTO tt_packages (product_id, type, series_name, package_name, url, status) "
                "VALUES (?,?,?,?,?,?)",
                (prod_map[old_pid], pkg.get('type', 'package'), pkg.get('series_name', ''),
                 pkg.get('package_name', ''), pkg.get('url', ''), pkg.get('status', '')))
            pkg_map[pkg_id] = db.execute("SELECT last_insert_rowid()").fetchone()[0]

        # 5. 在跑人员（user_id 固定为当前用户，同产品多 runner 折叠为一条）
        runner_products = set()
        for pr in runners:
            old_pid = pr.get('product_id')
            if old_pid not in prod_map:
                continue
            db.execute("INSERT OR IGNORE INTO tt_product_runners (product_id, user_id) VALUES (?,?)",
                       (prod_map[old_pid], uid))
            runner_products.add(prod_map[old_pid])
        runner_count = len(runner_products)

        # 6. 掉包检测（同包多条折叠为一条，按实际包去重计数）
        delist_packages = set()
        for dc in delist_checks:
            old_pkg = dc.get('package_id')
            if old_pkg not in pkg_map:
                continue
            new_pkg = pkg_map[old_pkg]
            checked_at = dc.get('checked_at')
            if checked_at is not None:
                db.execute(
                    "INSERT OR REPLACE INTO tt_delist_checks (package_id, is_delisted, checked_at) "
                    "VALUES (?,?,?)",
                    (new_pkg, dc.get('is_delisted', 0), checked_at))
            else:
                db.execute(
                    "INSERT OR REPLACE INTO tt_delist_checks (package_id, is_delisted) VALUES (?,?)",
                    (new_pkg, dc.get('is_delisted', 0)))
            delist_packages.add(new_pkg)
        delist_count = len(delist_packages)

        db.commit()
    except Exception as e:
        db.rollback()
        return err(f'导入失败：{e}')
    finally:
        db.execute("PRAGMA foreign_keys=ON")

    report = {
        "bcs": len(bc_map),
        "products": len(prod_map),
        "packages": len(pkg_map),
        "runners": runner_count,
        "delist_checks": delist_count,
    }
    return ok({'report': report})


# ==================== 工具函数 ====================

def _get_pkg_product_id(db, pkg_id):
    """反查投放对象所属 product_id，不存在返回 None。"""
    row = db.execute("SELECT product_id FROM tt_packages WHERE id=?", (pkg_id,)).fetchone()
    return row['product_id'] if row else None


def _validate_package(pkg):
    """校验投放对象：type 必须 package/pwa；跑包必须填写包名。

    例外：App Store 的投放对象没有安卓包名，URL 是苹果链接时包名允许留空。
    返回 None 或 err 响应。
    """
    pkg_type = pkg.get('type', 'package')
    if pkg_type not in ('package', 'pwa'):
        return err('无效的投放对象类型', 400)
    if pkg_type == 'package' and not (pkg.get('package_name') or '').strip():
        if not _is_appstore_url(pkg.get('url')):
            return err('跑包必须填写包名', 400)
    return None


def _get_role(db, uid):
    user = db.execute("SELECT role FROM users WHERE id=?", (uid,)).fetchone()
    return user['role'] if user else 'user'


def _check_bc_owner(db, uid, bid):
    """非跨用户角色只能更新/删除自己的 BC。返回 None 或 403 错误响应。"""
    role = _get_role(db, uid)
    if role in CROSS_USER_ROLES:
        return None
    row = db.execute("SELECT owner_id FROM tt_bcs WHERE id=?", (bid,)).fetchone()
    if not row or row['owner_id'] != uid:
        return err('无权限', 403)
    return None


def _check_product_owner(db, uid, pid):
    """非 developer/admin 用户只能更新/删除/恢复自己的产品。返回 None 或 403 错误响应。
    产品不存在时同样返回 403，避免信息泄露。"""
    role = _get_role(db, uid)
    if role in ('developer', 'admin'):
        return None
    row = db.execute("SELECT owner_id FROM tt_products WHERE id=?", (pid,)).fetchone()
    if not row or row['owner_id'] != uid:
        return err('无权限', 403)
    return None


def _check_product_view(db, uid, pid):
    """developer/admin 放行；产品 owner 或在跑人员可查看详情；否则 403。
    产品不存在时对普通用户同样返回 403，避免信息泄露。"""
    role = _get_role(db, uid)
    if role in ('developer', 'admin'):
        return None
    prod = db.execute("SELECT owner_id FROM tt_products WHERE id=?", (pid,)).fetchone()
    if not prod:
        return err('无权限', 403)
    if prod['owner_id'] == uid:
        return None
    runner = db.execute(
        "SELECT 1 FROM tt_product_runners WHERE product_id=? AND user_id=?", (pid, uid)
    ).fetchone()
    if runner:
        return None
    return err('无权限', 403)
