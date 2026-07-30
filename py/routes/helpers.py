"""路由层公共工具函数 — 减少 main.py 中的样板代码。"""
from flask import request, jsonify, g
from flask_jwt_extended import get_jwt_identity
import database
import auth


def ok(data=None) -> tuple:
    """成功响应 (200)。data 为 dict 时平铺到响应中，为 list 时包装为 {"data": [...]}。"""
    resp = {"success": True}
    if isinstance(data, list):
        resp["data"] = data
    elif isinstance(data, dict):
        resp.update(data)
    elif data is not None:
        resp["data"] = data
    return jsonify(resp)


def err(msg: str, code: int = 400) -> tuple:
    """错误响应。"""
    return jsonify({"success": False, "error": msg}), code


def parse_body() -> dict:
    """解析 JSON 请求体，失败返回空字典。"""
    return request.get_json(silent=True) or {}


def get_uid() -> int | None:
    """获取当前 JWT 用户 ID，未认证则返回 None。"""
    try:
        return int(get_jwt_identity())
    except Exception:
        return None


def get_db():
    """获取请求级共享数据库连接。"""
    db_conn = getattr(g, "db", None)
    if db_conn is None:
        db_conn = database.get_db()
        g.db = db_conn
    return db_conn


def get_current_user() -> dict | None:
    """获取当前认证用户信息。"""
    uid = get_uid()
    if uid is None:
        return None
    return auth.get_user_by_id(uid)


def get_user_display(user: dict | None, uid: int = None) -> str:
    """获取用户显示名（用于目录路径等）。"""
    if user:
        return (user.get("display_name") or user.get("username") or f"user_{user.get('id', uid or 0)}").strip()
    return f"user_{uid or 0}"


def parse_pagination() -> tuple[int, int]:
    """解析分页参数，返回 (page, size)。"""
    page = max(1, int(request.args.get("page", 1) or 1))
    size = max(1, min(100, int(request.args.get("size", 20) or 20)))
    return page, size


# --- 从 main.py 迁移的公共辅助函数 ---

MCC_CHANGE_TYPE_LABELS = {
    "manual": "手动编辑", "batch": "批量修改", "reassign": "认领转移",
    "import": "批量导入", "create": "新建账户",
}


def runner_ids_where(alias: str, uid: int):
    """返回 (SQL 片段, 参数列表)，匹配 products 表中 runner_ids JSON 列含指定 uid。"""
    uid_s = str(uid)
    return (
        f"({alias}.runner_ids = ? OR {alias}.runner_ids LIKE ? "
        f"OR {alias}.runner_ids LIKE ? OR {alias}.runner_ids LIKE ?)",
        [f"[{uid_s}]", f"[{uid_s},%", f"%, {uid_s},%", f"%, {uid_s}]"]
    )


def scope_where(scope: str, user_id: int, alias: str = None):
    """返回 scope 过滤的 (SQL片段, 参数列表)。alias 可选，如 \"v\"、\"cw\"。"""
    col = f"{alias}." if alias else ""
    if scope == "public":
        return f"{col}is_public = 1", []
    elif scope == "private":
        return f"{col}owner_id = ?", [user_id]
    else:  # all
        return f"({col}is_public = 1 OR {col}owner_id = ?)", [user_id]


def can_modify(db, user_id, table, item_id):
    """检查用户是否有权编辑/删除某项。db 由调用方传入。
    返回 (can: bool, error: str|None)
    """
    user = auth.get_user_by_id(user_id)
    if user and user["role"] in ("developer", "admin"):
        return True, None
    try:
        row = db.execute(
            f"SELECT owner_id, is_public FROM {table} WHERE id=?", (item_id,)
        ).fetchone()
        if not row:
            return False, "记录不存在"
        if row["owner_id"] == user_id:
            return True, None
        if row["is_public"] == 1:
            return True, None
        return False, "无权限：仅可操作自己的或公开的内容"
    except Exception:
        return False, "查询出错"


def can_modify_user(actor: dict, target: dict) -> bool:
    """admin 只能操作 user/viewer/hidden，不能操作其他 admin。developer 不受限。"""
    if actor["role"] == "developer":
        return True
    return target["role"] in ("user", "viewer", "hidden")
