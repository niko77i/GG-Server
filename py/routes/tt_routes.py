"""TikTok 平台 API 路由 — 产品管理 / BC管理 / 投放对象 / 掉包检测 / 素材关联"""
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


# ==================== 工具函数 ====================

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
