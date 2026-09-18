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
