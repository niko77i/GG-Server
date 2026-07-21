"""路由层通用装饰器 — 权限检查等。"""
from functools import wraps
from flask_jwt_extended import get_jwt_identity
import auth
from routes.helpers import err


def admin_required(fn):
    """要求 admin 或 developer 角色。"""
    @wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            uid = int(get_jwt_identity())
        except Exception:
            return err("未认证", 401)
        user = auth.get_user_by_id(uid)
        if not user or user["role"] not in ("developer", "admin"):
            return err("权限不足，仅管理员可操作", 403)
        return fn(*args, **kwargs)
    return wrapper


def developer_required(fn):
    """要求 developer 角色（最高权限）。"""
    @wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            uid = int(get_jwt_identity())
        except Exception:
            return err("未认证", 401)
        user = auth.get_user_by_id(uid)
        if not user or user["role"] != "developer":
            return err("权限不足，仅开发者可操作", 403)
        return fn(*args, **kwargs)
    return wrapper


def reject_viewer():
    """如果当前用户是 viewer，返回 403 错误响应；否则返回 None。"""
    try:
        uid = int(get_jwt_identity())
    except Exception:
        return None  # 未登录，由 @jwt_required() 处理
    user = auth.get_user_by_id(uid)
    if user and user.get("role") == "viewer":
        return err("权限不足：只读用户无法执行此操作", 403)
    return None
