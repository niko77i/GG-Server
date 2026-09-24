"""户管看板（Google Sheet）配置与双向同步的 HTTP 入口。

设计见 docs/superpowers/specs/2026-09-23-huguan-sheet-design.md。
本文件只做取参/鉴权/调逻辑层，双向同步的实际判断都在 huguan_dashboard.py，
Sheets I/O 在 google_sheets_service.py。
"""
from flask import Blueprint, request
from flask_jwt_extended import jwt_required

import database
import huguan_dashboard as hd
from cache import cache as _app_cache

from .helpers import ok, err, get_uid
from .decorators import huguan_required

huguan_dashboard_bp = Blueprint("huguan_dashboard", __name__)


@huguan_dashboard_bp.route("/api/huguan/dashboard", methods=["GET"])
@jwt_required()
@huguan_required
def dashboard_config_get():
    """返回当前户管的看板配置（GG 与 TT 两份）。

    两份都经 `get_platform_config` 归一化后再返回：`config` 表是全仓共用的，
    平台条目可能是「真值非 dict」，直接透传会让 `config.gg` 变成字符串/数字，
    破坏 `{"spreadsheet_id","sheet_name"}` 这个响应契约。
    """
    db = database.get_db()
    try:
        uid = get_uid()
        conf = {p: hd.get_platform_config(db, uid, p) for p in hd.PLATFORMS}
    finally:
        db.close()
    return ok({"config": conf})


@huguan_dashboard_bp.route("/api/huguan/dashboard", methods=["POST"])
@jwt_required()
@huguan_required
def dashboard_config_save():
    """保存某平台的看板配置。表格 ID 接受裸 ID 或完整 URL。"""
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return err("请求体必须是 JSON 对象", 400)
    # 字段一律先 str() 兜底：给个数字或 null 不该炸成 500，按取不到值处理
    platform = str(data.get("platform") or "").strip()
    if platform not in hd.PLATFORMS:
        return err("platform 必须是 gg 或 tt", 400)

    from main import _parse_sheet_id
    ss_id = _parse_sheet_id(str(data.get("spreadsheet_id") or "").strip())
    sheet_name = str(data.get("sheet_name") or "").strip()

    db = database.get_db()
    try:
        hd.save_config(db, get_uid(), platform, ss_id, sheet_name)
    finally:
        db.close()
    return ok({"message": "配置已保存"})


@huguan_dashboard_bp.route("/api/huguan/dashboard/sync", methods=["POST"])
@jwt_required()
@huguan_required
def dashboard_sync():
    """表 → 系统：先出差异报告（dry_run=true），户管确认后再落库。

    归属门禁（规格 §8.2）：表地址一律取自该户管自己的配置，请求体不接受表地址，
    因此不存在「对着别人的表发起同步」这条路。
    """
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return err("请求体必须是 JSON 对象", 400)
    platform = str(data.get("platform") or "").strip()
    if platform not in hd.PLATFORMS:
        return err("platform 必须是 gg 或 tt", 400)

    uid = get_uid()
    db = database.get_db()
    try:
        conf = hd.get_platform_config(db, uid, platform)
        if not conf["spreadsheet_id"] or not conf["sheet_name"]:
            return err("请先在设置页配置户管看板的表格 ID 与工作表名", 400)

        import google_sheets_service as gs
        from main import _GOOGLE_SHEETS_CONFIG
        service = gs.build_service(_GOOGLE_SHEETS_CONFIG["credentials_path"])
        grid = gs.read_sheet_values(service, conf["spreadsheet_id"],
                                   conf["sheet_name"], hd.READ_RANGE[platform])

        # 第 1 行是表头；不跳任何数据行（户管看板没有「是否解绑」列可用作跳过标记）
        parsed_rows = []
        for i, values in enumerate(grid[1:], start=2):
            parsed = hd.parse_row(values, platform)
            parsed["row"] = i
            parsed_rows.append(parsed)

        diff = hd.build_diff(db, parsed_rows, platform)

        # fail-safe：只有**显式布尔 False** 才落库。缺省 / true / null / "false"
        # (字符串) / 0 全部走只读 dry_run —— 少了这个 is not False，JSON null 会因
        # `None` 为假值而掉进落库分支，等于「传了个空值就把库改了」。
        if data.get("dry_run") is not False:
            return ok({"diff": diff})

        # confirmed 期望 {"create": [账户ID...], "update": [账户ID...], "owner": [账户ID...]}。
        # `or {}` 兜不住真值非 dict（[1,2] / "abc"）→ apply_diff 里 conf.get 炸 500；
        # 值不是数组同样炸（`2 not in 2` → TypeError）。两层都在这里挡住。
        confirmed = data.get("confirmed")
        if not isinstance(confirmed, dict):
            return err("confirmed 必须是对象", 400)
        for k in ("create", "update", "owner"):
            v = confirmed.get(k)
            if v is not None and not isinstance(v, list):
                return err(f"confirmed.{k} 必须是账户ID数组", 400)

        result = hd.apply_diff(db, diff, platform, confirmed, user_id=uid)

        # 规格 §8.3 步骤 8：落库后清缓存（账户写入了，代理/列表下拉必须立即刷新）。
        # 只放在路由层 —— 纯逻辑的 apply_diff 不该依赖 cache。
        _app_cache.clear_prefix("accounts:agents:")
        if any(item.get("pending_status")
               for item in diff.get("to_create", []) + diff.get("to_update", [])):
            # 本次可能新建了状态行（build_diff 只读，状态行是在 apply_diff 里建的）
            _app_cache.delete(f"accounts:statuses:{uid}")

        # 规格 §7.2 规则 3② + 规则 4：应用了归属变更的行，回写运营列并清空变更通道列
        applied = result.pop("applied_owner_rows", [])
        if applied:
            # 新归属名直接取 item["to"]（apply_diff 已经带上），不再靠行号反查 ——
            # 行号在重新拉表后可能已经位移到别人身上。
            rows = [{"account_id": item["account_id"],
                     "cells": {hd.OWNER_COL[platform]: item["to"]}}
                    for item in applied]
            _write_background(service, conf, rows)
            _write_background(service, conf,
                              hd.owner_channel_cells(applied, platform, ""))
    finally:
        db.close()

    return ok({"result": result, "diff": diff})


@huguan_dashboard_bp.route("/api/huguan/dashboard/push", methods=["POST"])
@jwt_required()
@huguan_required
def dashboard_push():
    """系统 → 表：全量刷新。同步执行，返回实际写入行数。"""
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return err("请求体必须是 JSON 对象", 400)
    platform = str(data.get("platform") or "").strip()
    if platform not in hd.PLATFORMS:
        return err("platform 必须是 gg 或 tt", 400)

    uid = get_uid()
    db = database.get_db()
    try:
        conf = hd.get_platform_config(db, uid, platform)
        if not conf["spreadsheet_id"] or not conf["sheet_name"]:
            return err("请先在设置页配置户管看板的表格 ID 与工作表名", 400)
        rows = hd.collect_rows_for_push(db, platform)
    finally:
        db.close()

    import google_sheets_service as gs
    from main import _GOOGLE_SHEETS_CONFIG
    service = gs.build_service(_GOOGLE_SHEETS_CONFIG["credentials_path"])
    res = gs.update_rows_by_account_id(service, conf["spreadsheet_id"],
                                       conf["sheet_name"], rows)
    return ok({"result": {"rows": len(rows), "updated": res["updated"],
                          "not_found": res["not_found"]}})


@huguan_dashboard_bp.route("/api/huguan/dashboard/owner-options", methods=["GET"])
@jwt_required()
@huguan_required
def dashboard_owner_options():
    """「户归属」下拉的数据源：可以直接把户转给他的**全部**用户。

    与 `/api/platform/users` 的分工（父设计 §9.2 的更正）：
    - `/api/platform/users` 服务**筛选**（「归属人」筛选器）——只列该平台有未删除
      账户的人，选中一个名下无户的人必然得到空表，这种选项没有筛选价值；
    - 本端点服务**编辑**（改归属）——必须全量，否则户管没法把 GG 账户转给一个
      只在 TT 有户的合法用户（实测缺口）。
    两者都保留，各有各的用途，不要互相替代。

    排除 `viewer`（只读角色，转给它在业务上无意义，用户已裁定）与 `hidden`
    （被停用、无法登录）。**不按平台过滤**：这是「转给谁」的真实全集。
    """
    db = database.get_db()
    try:
        rows = db.execute(
            "SELECT id, username, display_name, platform FROM users "
            "WHERE role NOT IN ('viewer', 'hidden') "
            "ORDER BY display_name, username"
        ).fetchall()
    finally:
        db.close()
    return ok({"users": [dict(r) for r in rows]})


def _write_background(service, conf, rows):
    """后台写表；失败只记日志，不影响同步接口的返回（对照 main.py:5006 的做法）。"""
    import logging
    log = logging.getLogger("gg-server")

    def _do():
        import google_sheets_service as gs
        gs.update_rows_by_account_id(service, conf["spreadsheet_id"],
                                     conf["sheet_name"], rows)

    from main import _sync_sheets_background
    _sync_sheets_background(_do, lambda s, e: log.warning("户管看板回写失败: %s", e) if e else None)
