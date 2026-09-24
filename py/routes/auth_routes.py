"""认证路由 — /api/auth/* + JWT 回调"""
from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity, create_access_token
import auth
import database

auth_bp = Blueprint('auth', __name__)


# --- JWT 回调 ---
def register_jwt_callbacks(jwt):
    """注册 JWT 回调（由 main.py 在创建 JWTManager 后调用）。"""

    @jwt.invalid_token_loader
    def invalid_token_callback(reason):
        return jsonify(success=False, error="Invalid token"), 401

    @jwt.expired_token_loader
    def expired_token_callback(jwt_header, jwt_payload):
        return jsonify(success=False, error="Token expired"), 401


# --- 登录 / 注册 ---
@auth_bp.route("/login", methods=["POST"])
def auth_login():
    data = request.get_json()
    if not data:
        return jsonify(success=False, error="Missing request body"), 400
    username = data.get("username", "").strip()
    password = data.get("password", "")
    if not username or not password:
        return jsonify(success=False, error="Username and password required"), 400
    result = auth.login_user(username, password)
    if not result:
        return jsonify(success=False, error="Invalid credentials or account disabled"), 401
    return jsonify(success=True, **result)


@auth_bp.route("/register", methods=["POST"])
def auth_register():
    data = request.get_json()
    if not data:
        return jsonify(success=False, error="Missing request body"), 400
    username = data.get("username", "").strip()
    password = data.get("password", "")
    display_name = data.get("display_name", "").strip()
    if not username or len(username) < 4 or len(username) > 20:
        return jsonify(success=False, error="Username must be 4-20 characters"), 400
    if not password or len(password) < 6:
        return jsonify(success=False, error="Password must be at least 6 characters"), 400
    existing = auth.get_user_by_username(username)
    if existing:
        return jsonify(success=False, error="Username already exists"), 409
    user = auth.register_user(username, password, display_name)
    if not user:
        return jsonify(success=False, error="Registration failed"), 500
    return jsonify(success=True, user=user)


@auth_bp.route("/refresh", methods=["POST"])
@jwt_required(refresh=True)
def auth_refresh():
    user_id = get_jwt_identity()
    new_token = create_access_token(identity=user_id)
    return jsonify(success=True, access_token=new_token)


@auth_bp.route("/me", methods=["GET"])
@jwt_required()
def auth_me():
    user_id = int(get_jwt_identity())
    user = auth.get_user_by_id(user_id)
    if not user:
        return jsonify(success=False, error="User not found"), 404
    return jsonify(success=True, user=user)


# --- 用户配置 ---
@auth_bp.route("/custom-name", methods=["GET"])
@jwt_required()
def auth_custom_name_get():
    user_id = int(get_jwt_identity())
    db = database.get_db()
    row = db.execute("SELECT custom_name FROM users WHERE id=?", (user_id,)).fetchone()
    db.close()
    return jsonify({"success": True, "custom_name": row["custom_name"] if row else ""})


@auth_bp.route("/custom-name", methods=["PUT"])
@jwt_required()
def auth_custom_name_set():
    user_id = int(get_jwt_identity())
    data = request.get_json(silent=True) or {}
    custom_name = (data.get("custom_name") or "").strip()
    db = database.get_db()
    db.execute("UPDATE users SET custom_name=? WHERE id=?", (custom_name, user_id))
    db.commit()
    db.close()
    return jsonify({"success": True, "custom_name": custom_name})


@auth_bp.route("/email", methods=["GET"])
@jwt_required()
def auth_email_get():
    user_id = int(get_jwt_identity())
    db = database.get_db()
    row = db.execute("SELECT email FROM users WHERE id=?", (user_id,)).fetchone()
    db.close()
    return jsonify({"success": True, "email": row["email"] if row else ""})


@auth_bp.route("/email", methods=["PUT"])
@jwt_required()
def auth_email_set():
    user_id = int(get_jwt_identity())
    data = request.get_json(silent=True) or {}
    email = (data.get("email") or "").strip()
    db = database.get_db()
    db.execute("UPDATE users SET email=? WHERE id=?", (email, user_id))
    db.commit()
    db.close()
    return jsonify({"success": True, "email": email})


@auth_bp.route("/telegram-username", methods=["PUT"])
@jwt_required()
def auth_telegram_username_set():
    """当前用户设置自己的 Telegram 用户名（不带 @ 前缀）。"""
    user_id = int(get_jwt_identity())
    data = request.get_json(silent=True) or {}
    username = (data.get("telegram_username") or "").strip().lstrip("@")
    db = database.get_db()
    db.execute("UPDATE users SET telegram_username=? WHERE id=?", (username, user_id))
    db.commit()
    db.close()
    return jsonify({"success": True, "telegram_username": username})


@auth_bp.route("/password", methods=["PUT"])
@jwt_required()
def auth_password():
    """用户自己修改密码。"""
    user_id = int(get_jwt_identity())
    data = request.get_json(silent=True) or {}
    old_password = data.get("old_password", "")
    new_password = data.get("new_password", "")
    if not old_password or not new_password:
        return jsonify(success=False, error="请提供旧密码和新密码"), 400
    if len(new_password) < 6:
        return jsonify(success=False, error="新密码至少 6 位"), 400
    current_user = auth.get_user_by_id(user_id)
    if not current_user:
        return jsonify(success=False, error="User not found"), 404
    # get_user_by_id 不含 password，通过 username 获取完整信息验证旧密码
    full_user = auth.get_user_by_username(current_user["username"])
    if not auth.verify_password(old_password, full_user["password"]):
        return jsonify(success=False, error="旧密码不正确"), 400
    if auth.update_password(user_id, new_password):
        return jsonify(success=True)
    return jsonify(success=False, error="更新失败"), 400


@auth_bp.route("/profile", methods=["PUT"])
@jwt_required()
def auth_profile():
    """用户自己更新个人信息（显示名）。"""
    user_id = int(get_jwt_identity())
    data = request.get_json(silent=True) or {}
    display_name = data.get("display_name", "").strip()
    result = auth.update_user(user_id, username=None, display_name=display_name)
    if result:
        return jsonify(success=True, user=result)
    return jsonify(success=False, error="更新失败"), 400


# --- 用户名称查询 ---
@auth_bp.route("/names", methods=["GET"], endpoint="users_names")
@jwt_required()
def users_names():
    """返回在产品表中有数据的用户（owner 或 runner），供 runner 选择器使用。
    非 developer 用户看不到 developer 角色用户。"""
    current_user_id = get_jwt_identity()
    db = database.get_db()
    dev_filter = ""
    if current_user_id:
        cur_user = db.execute("SELECT role FROM users WHERE id=?", (int(current_user_id),)).fetchone()
        if not cur_user or cur_user["role"] != "developer":
            dev_filter = " AND u.role != 'developer'"
    else:
        dev_filter = " AND u.role != 'developer'"
    rows = db.execute(f"""
        SELECT DISTINCT u.id, u.username, u.display_name, u.platform
        FROM users u
        JOIN products p ON (
            p.owner_id = u.id
            OR p.runner_ids = '[' || u.id || ']'
            OR p.runner_ids LIKE '[' || u.id || ',%'
            OR p.runner_ids LIKE '%, ' || u.id || ',%'
            OR p.runner_ids LIKE '%, ' || u.id || ']'
        )
        WHERE u.role != 'hidden'{dev_filter}
        ORDER BY u.id
    """).fetchall()
    db.close()
    return jsonify({"success": True, "users": [dict(r) for r in rows]})
