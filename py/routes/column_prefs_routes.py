"""账户看板自定义列配置的 HTTP 入口。

设计见 docs/superpowers/specs/2026-10-08-account-column-prefs-design.md。
本文件只做取参 / 鉴权 / 调逻辑层，校验与存储都在 column_prefs.py。
"""
from flask import Blueprint
from flask_jwt_extended import jwt_required

import column_prefs as cp
import database

from .helpers import ok, err, parse_body, get_uid

column_prefs_bp = Blueprint("column_prefs", __name__)


@column_prefs_bp.route("/api/user/column-prefs", methods=["GET"])
@jwt_required()
def column_prefs_get():
    """返回当前登录用户的全部面板列配置。无配置时 prefs 为 {}。"""
    uid = get_uid()
    if uid is None:
        return err("无法识别当前用户", 401)
    db = database.get_db()
    try:
        prefs = cp.load_prefs(db, uid)
    finally:
        db.close()
    return ok({"prefs": prefs})


@column_prefs_bp.route("/api/user/column-prefs", methods=["PUT"])
@jwt_required()
def column_prefs_put():
    """整体替换某个面板的列配置（order 与 hidden 一起提交）。

    uid 只从 JWT 取，**绝不从请求体读** —— config 的 key 内含 uid，
    接受请求体里的 uid 就等于允许任意用户改写他人的界面配置。
    """
    uid = get_uid()
    if uid is None:
        return err("无法识别当前用户", 401)

    body = parse_body()
    panel = body.get("panel")
    if panel not in cp.PANELS:
        return err(f"不支持的面板: {panel!r}")

    order = cp.validate_key_list(body.get("order"))
    if order is None:
        return err("order 必须是字符串数组，去重后不超过 64 项、每项不超过 64 字符")

    hidden = cp.validate_key_list(body.get("hidden", []))
    if hidden is None:
        return err("hidden 必须是字符串数组，不超过 64 项、每项不超过 64 字符")

    db = database.get_db()
    try:
        prefs = cp.save_panel_prefs(db, uid, panel, order, hidden)
    finally:
        db.close()
    return ok({"prefs": prefs})
