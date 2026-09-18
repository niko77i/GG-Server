"""TikTok 平台 API 路由 — 产品管理 / BC管理 / 投放对象 / 掉包检测 / 素材关联"""
import re

from flask import Blueprint, request
from flask_jwt_extended import jwt_required
from .helpers import ok, err, get_uid, get_db, parse_body
from .decorators import tt_required

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
    if role not in ('developer', 'admin'):
        where.append("owner_id = ?")
        params.append(uid)
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
@tt_required
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
@tt_required
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
@tt_required
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
    rows = db.execute(
        "SELECT id, name, bc_id FROM tt_bcs WHERE status='normal' AND deleted_at IS NULL ORDER BY name"
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
            bc = db.execute("SELECT id, name, bc_id FROM tt_bcs WHERE id=?", (r['bc_id'],)).fetchone()
            item['bc'] = dict(bc) if bc else None
        item['runners'] = [dict(u) for u in db.execute(
            "SELECT u.id, u.username, u.display_name FROM users u "
            "JOIN tt_product_runners pr ON pr.user_id = u.id WHERE pr.product_id=?", (r['id'],)
        ).fetchall()]
        item['packages'] = [dict(pk) for pk in db.execute(
            "SELECT * FROM tt_packages WHERE product_id=? ORDER BY id", (r['id'],)
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
@tt_required
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
@tt_required
def update_product(pid):
    db = get_db()
    uid = get_uid()
    denied = _check_product_owner(db, uid, pid)
    if denied:
        return denied
    data = parse_body()
    fields = {
        'product_name': data.get('product_name', '').strip(),
        'kpi': data.get('kpi', ''),
        'region': data.get('region', ''),
        'status': data.get('status', 'active'),
        'bc_id': data.get('bc_id', None),
        'sales_person_id': data.get('sales_person_id', None),
        'agency_ratio': data.get('agency_ratio', 0),
        'customer': data.get('customer', ''),
    }
    runner_ids = data.get('runner_ids', None)
    packages = data.get('packages', None)

    if fields['product_name']:
        db.execute(
            "UPDATE tt_products SET product_name=?, kpi=?, region=?, status=?, bc_id=?, "
            "sales_person_id=?, agency_ratio=?, customer=?, updated_at=datetime('now','localtime') WHERE id=?",
            (fields['product_name'], fields['kpi'], fields['region'], fields['status'],
             fields['bc_id'], fields['sales_person_id'], fields['agency_ratio'],
             fields['customer'], pid))

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

    db.commit()
    return ok()


@tt_bp.route('/api/tt/products/<int:pid>', methods=['DELETE'])
@jwt_required()
@tt_required
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
@tt_required
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
        "SELECT * FROM tt_packages WHERE product_id=? ORDER BY id", (pid,)
    ).fetchall()]
    return ok(item)


# ==================== 投放对象（跑包 / PWA，单表） ====================

@tt_bp.route('/api/tt/products/<int:pid>/packages', methods=['POST'])
@jwt_required()
@tt_required
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

    if pkg_type not in ('package', 'pwa'):
        return err('无效的投放对象类型')
    if pkg_type == 'package' and not package_name:
        return err('跑包必须填写包名')

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
@tt_required
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

    # re-enforce type 规则：package 必须填写包名（与 add_package 语义一致）
    pkg_type = updates.get('type', existing['type'])
    if pkg_type == 'package' and 'package_name' in updates and not updates['package_name']:
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
@tt_required
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
    db.execute("DELETE FROM tt_packages WHERE id=?", (pkg_id,))
    db.commit()
    return ok()


@tt_bp.route('/api/tt/packages/batch-delete', methods=['POST'])
@jwt_required()
@tt_required
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
    db.execute(f"DELETE FROM tt_packages WHERE id IN ({placeholders})", ids)
    db.commit()
    return ok({'deleted': len(ids)})


# ==================== 掉包检测（仅跑包 type='package'） ====================

@tt_bp.route('/api/tt/products/<int:pid>/check-delist', methods=['POST'])
@jwt_required()
@tt_required
def check_delist(pid):
    import delist_checker
    import datetime
    db = get_db()
    uid = get_uid()
    denied = _check_product_owner(db, uid, pid)
    if denied:
        return denied

    pkgs = db.execute(
        "SELECT id, package_name, series_name, url FROM tt_packages "
        "WHERE product_id=? AND type='package' AND url != ''",
        (pid,)
    ).fetchall()
    if not pkgs:
        return ok({'results': [], 'message': '没有需要检测的跑包'})

    pkg_list = [dict(p) for p in pkgs]
    results = delist_checker.check_product_packages(pid, pkg_list, None)

    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    for r in results:
        db.execute(
            "INSERT OR REPLACE INTO tt_delist_checks(package_id, is_delisted, checked_at) "
            "VALUES(?, ?, ?)",
            (r["package_id"], 1 if r["is_delisted"] else 0, now))
    db.commit()
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


# ==================== 合并 / 粘贴解析 / 素材 / 用户 ====================

@tt_bp.route('/api/tt/products/merge', methods=['POST'])
@jwt_required()
@tt_required
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
        db.execute("DELETE FROM tt_packages WHERE product_id=?", (mid,))
        db.execute("DELETE FROM tt_product_runners WHERE product_id=?", (mid,))
        db.execute("DELETE FROM tt_products WHERE id=?", (mid,))

    db.execute("PRAGMA foreign_keys=ON")
    db.commit()
    return ok({'merged_packages': merged_packages, 'merged_products': len(merge_ids)})


@tt_bp.route('/api/tt/products/import-text', methods=['POST'])
@jwt_required()
@tt_required
def import_text():
    """粘贴文本解析成投放对象列表（第一阶段仅跑包 Google Play 链接）。"""
    data = parse_body()
    text = (data.get("text") or "").strip()
    prefix = (data.get("prefix") or "").strip()
    suffix = (data.get("suffix") or "").strip()
    if not text:
        return err('未提供文本内容')

    links = re.findall(r'https?://play\.google\.com/store/apps/details\?id=[\w.&=/\-?%]+', text)
    results = []
    for link in links:
        pkg = _extract_pkg_from_url(link)
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
@tt_required
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
@tt_required
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


# ==================== 工具函数 ====================

def _get_pkg_product_id(db, pkg_id):
    """反查投放对象所属 product_id，不存在返回 None。"""
    row = db.execute("SELECT product_id FROM tt_packages WHERE id=?", (pkg_id,)).fetchone()
    return row['product_id'] if row else None


def _get_role(db, uid):
    user = db.execute("SELECT role FROM users WHERE id=?", (uid,)).fetchone()
    return user['role'] if user else 'user'


def _check_bc_owner(db, uid, bid):
    """非 developer/admin 用户只能更新/删除自己的 BC。返回 None 或 403 错误响应。"""
    role = _get_role(db, uid)
    if role in ('developer', 'admin'):
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
