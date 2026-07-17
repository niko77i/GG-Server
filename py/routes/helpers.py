"""路由层公共工具函数 — 减少 main.py 中的样板代码。"""
from flask import request, jsonify, g
from flask_jwt_extended import get_jwt_identity
import database
import auth


def ok(data: dict = None) -> tuple:
    """成功响应 (200)。"""
    resp = {"success": True}
    if data:
        resp.update(data)
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
