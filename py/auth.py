from werkzeug.security import generate_password_hash, check_password_hash
from flask_jwt_extended import create_access_token, create_refresh_token

import database


def hash_password(password: str) -> str:
    return generate_password_hash(password)


def verify_password(password: str, hashed: str) -> bool:
    return check_password_hash(hashed, password)


def create_user(username: str, password: str, role: str = "user",
                display_name: str = "", created_by: int = None,
                platform: str = "gg") -> dict:
    conn = database.get_db()
    try:
        cur = conn.execute(
            "SELECT id FROM users WHERE username = ?", (username,)
        )
        if cur.fetchone():
            return None

        hashed = hash_password(password)
        cur = conn.execute(
            "INSERT INTO users (username, password, role, display_name, created_by, platform) VALUES (?, ?, ?, ?, ?, ?)",
            (username, hashed, role, display_name, created_by, platform)
        )
        conn.commit()
        return get_user_by_id(cur.lastrowid)
    finally:
        conn.close()


def get_user_by_id(user_id: int) -> dict | None:
    conn = database.get_db()
    try:
        cur = conn.execute(
            "SELECT id, username, role, display_name, created_at, last_login, created_by, config, email, telegram_username, platform FROM users WHERE id = ?",
            (user_id,)
        )
        row = cur.fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def get_user_by_username(username: str) -> dict | None:
    conn = database.get_db()
    try:
        cur = conn.execute("SELECT * FROM users WHERE username = ?", (username,))
        row = cur.fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def list_users(search: str = "", page: int = 1, page_size: int = 20, current_user_id: int = None, platform: str = None) -> dict:
    """列出用户。非 developer 用户看不到 developer 角色的用户。
    platform: 可选筛选 ('gg' | 'fb')，None 表示不过滤。
    """
    conn = database.get_db()
    try:
        # 判断当前用户是否是 developer
        is_dev = False
        if current_user_id:
            cur_user = conn.execute("SELECT role FROM users WHERE id = ?", (current_user_id,)).fetchone()
            is_dev = cur_user and cur_user["role"] == "developer"

        # 非 developer 用户看不到 developer 角色
        filters = [""] if is_dev else ["role != 'developer'"]
        params = []

        if platform:
            filters.append("platform = ?")
            params.append(platform)

        base_where = " AND ".join(f for f in filters if f)
        where_clause = f" WHERE {base_where}" if base_where else ""

        SELECT_COLS = "id, username, role, display_name, created_at, last_login, created_by, telegram_username, platform"

        if search:
            like = f"%{search}%"
            search_filter = f"({' OR '.join([base_where, '(username LIKE ? OR display_name LIKE ?)'] if base_where else ['username LIKE ? OR display_name LIKE ?'])})"
            # simplify: add AND search to where
            search_clause = " AND (username LIKE ? OR display_name LIKE ?)"
            total = conn.execute(
                f"SELECT COUNT(*) as total FROM users{where_clause}{search_clause}",
                params + [like, like]
            ).fetchone()["total"]
            offset = (page - 1) * page_size
            rows = conn.execute(
                f"SELECT {SELECT_COLS} FROM users{where_clause}{search_clause} ORDER BY id DESC LIMIT ? OFFSET ?",
                params + [like, like, page_size, offset]
            ).fetchall()
        else:
            total = conn.execute(
                f"SELECT COUNT(*) as total FROM users{where_clause}",
                params
            ).fetchone()["total"]
            offset = (page - 1) * page_size
            rows = conn.execute(
                f"SELECT {SELECT_COLS} FROM users{where_clause} ORDER BY id DESC LIMIT ? OFFSET ?",
                params + [page_size, offset]
            ).fetchall()
        return {"users": [dict(r) for r in rows], "total": total}
    finally:
        conn.close()


def update_user_role(user_id: int, new_role: str) -> bool:
    conn = database.get_db()
    try:
        cur = conn.execute("SELECT role FROM users WHERE id = ?", (user_id,))
        row = cur.fetchone()
        if not row or row["role"] == "developer":
            return False
        conn.execute("UPDATE users SET role = ? WHERE id = ?", (new_role, user_id))
        conn.commit()
        return True
    finally:
        conn.close()


def update_user(uid: int, username: str = None, display_name: str = None, platform: str = None) -> dict | None:
    """编辑用户信息（用户名、显示名、平台）。返回更新后的用户 dict，失败返回 None。"""
    conn = database.get_db()
    try:
        existing = conn.execute("SELECT * FROM users WHERE id = ?", (uid,)).fetchone()
        if not existing:
            return None

        if username is not None:
            username = username.strip()
            if len(username) < 4 or len(username) > 20:
                return None
            # 检查用户名是否被其他用户占用
            dup = conn.execute(
                "SELECT id FROM users WHERE username = ? AND id != ?", (username, uid)
            ).fetchone()
            if dup:
                return None
            conn.execute("UPDATE users SET username = ? WHERE id = ?", (username, uid))

        if display_name is not None:
            conn.execute("UPDATE users SET display_name = ? WHERE id = ?", (display_name.strip(), uid))

        if platform is not None:
            conn.execute("UPDATE users SET platform = ? WHERE id = ?", (platform, uid))

        conn.commit()
        return get_user_by_id(uid)
    finally:
        conn.close()


def update_password(uid: int, new_password: str) -> bool:
    """修改用户密码。"""
    if not new_password or len(new_password) < 6:
        return False
    conn = database.get_db()
    try:
        existing = conn.execute("SELECT id FROM users WHERE id = ?", (uid,)).fetchone()
        if not existing:
            return False
        hashed = hash_password(new_password)
        conn.execute("UPDATE users SET password = ? WHERE id = ?", (hashed, uid))
        conn.commit()
        return True
    finally:
        conn.close()


def toggle_user_status(user_id: int) -> dict | None:
    conn = database.get_db()
    try:
        cur = conn.execute("SELECT id, role FROM users WHERE id = ?", (user_id,))
        row = cur.fetchone()
        if not row or row["role"] == "developer":
            return None
        new_role = "hidden" if row["role"] in ("user", "admin", "viewer") else "user"
        conn.execute("UPDATE users SET role = ? WHERE id = ?", (new_role, user_id))
        conn.commit()
        return get_user_by_id(user_id)
    finally:
        conn.close()


def update_last_login(user_id: int):
    conn = database.get_db()
    try:
        conn.execute("UPDATE users SET last_login = datetime('now') WHERE id = ?", (user_id,))
        conn.commit()
    finally:
        conn.close()


def login_user(username: str, password: str) -> dict | None:
    user = get_user_by_username(username)
    if not user or user["role"] == "hidden":
        return None
    if not verify_password(password, user["password"]):
        return None
    update_last_login(user["id"])
    access_token = create_access_token(identity=str(user["id"]))
    refresh_token = create_refresh_token(identity=str(user["id"]))
    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "user": {"id": user["id"], "username": user["username"], "role": user["role"], "display_name": user.get("display_name", ""), "platform": user.get("platform", "gg")}
    }


def register_user(username: str, password: str, display_name: str = "") -> dict | None:
    return create_user(username=username, password=password, role="user", display_name=display_name, created_by=None)


def init_developer(config: dict):
    dev_config = config.get("developer", {})
    username = dev_config.get("username", "admin")
    password = dev_config.get("password", "admin123")
    existing = get_user_by_username(username)
    if existing:
        return
    create_user(username=username, password=password, role="developer", display_name="Developer")
    print(f"[Auth] Developer account created: {username}")
