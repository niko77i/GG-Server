"""户管看板域的写表目标（三期）。

设计见 docs/superpowers/specs/2026-10-08-sheet-write-governance-phase3-huguan-design.md

全部是**镜像类**（表 = 系统状态的投影）⇒ 一律不注册 `rollback`，最终失败落 `retry_failed`。
rebuild 一律**从 DB 重算**，不重放快照。

⚠️ `sheet_write_log.user_id` 记的是**表主人**（规格 §3.5）：除
`operator_dashboard_remark` 外，其余三个 target 的表主人 == 触发者（这些操作只有户管会做）。

线程约束：所有 service 与 DB 连接都在**函数/闭包内**新建 —— 这些代码会在后台线程里跑，
sqlite 连接与 httplib2 客户端都不可跨线程复用。
"""
import sheet_write


# ---------- target: huguan_dashboard（整行刷新；覆盖点位 #1 与 #5 的 :159/:171/:180） ----------

def huguan_dashboard_sync(user_id, platform, account_ids):
    """把这些账户的**整行**刷新到该户管的看板。

    重建走 `collect_rows_for_push` —— 与既有 `push_rows` 同一条路径。
    `cells_for_row` 只产出系统拥有的可写列，**刻意不含**归属变更通道列（规格 §7.2 规则 2），
    故不会碰到户管用公式维护的列。
    """
    import database
    import google_sheets_service as gs
    import huguan_dashboard as hd
    from main import _GOOGLE_SHEETS_CONFIG

    db = database.get_db()
    try:
        conf = hd.get_platform_config(db, user_id, platform)
        if not conf["spreadsheet_id"] or not conf["sheet_name"]:
            raise RuntimeError("该看板未配置表格 ID 或工作表名")
        rows = hd.collect_rows_for_push(db, platform, list(account_ids))
    finally:
        db.close()
    if not rows:
        raise RuntimeError("找不到对应账户，无法重建看板行")

    service = gs.build_service(_GOOGLE_SHEETS_CONFIG["credentials_path"])
    gs.update_rows_by_account_id(service, conf["spreadsheet_id"],
                                 conf["sheet_name"], rows, key_col=hd.KEY_COL[platform])


def huguan_dashboard_many_sync(user_id, platform, business_keys):
    """**首跑**用：一次覆盖 N 户。

    `run_write_many` 的 `sync_fn` 只执行**一次**；拿单户工厂顶上会让只有第一户被写进表
    而 N 行全落 synced（静默漏写，二期踩过）。
    """
    keys = list(business_keys)

    def _sync():
        huguan_dashboard_sync(user_id, platform, keys)

    return _sync


def _huguan_dashboard_rebuild(user_id, business_key, payload):
    platform = (payload or {}).get("platform")
    if not platform:
        raise RuntimeError("payload 缺 platform，无法重建看板行")

    def _sync():
        huguan_dashboard_sync(user_id, platform, [business_key])

    return _sync


# ---------- target: huguan_owner_channel（通道列；覆盖点位 #3 与 #5 的 :165） ----------

def huguan_owner_channel_sync(user_id, platform, account_id, value):
    """写归属变更通道列（GG=H / TT=L）。`value` 为空串即清空该格。"""
    import database
    import google_sheets_service as gs
    import huguan_dashboard as hd
    from main import _GOOGLE_SHEETS_CONFIG

    db = database.get_db()
    try:
        conf = hd.get_platform_config(db, user_id, platform)
        if not conf["spreadsheet_id"] or not conf["sheet_name"]:
            raise RuntimeError("该看板未配置表格 ID 或工作表名")
        rows = hd.owner_channel_cells([{"account_id": account_id}], platform, value)
    finally:
        db.close()
    if not rows:
        raise RuntimeError("无法构造通道列待写行")

    service = gs.build_service(_GOOGLE_SHEETS_CONFIG["credentials_path"])
    gs.update_rows_by_account_id(service, conf["spreadsheet_id"], conf["sheet_name"], rows)


def _huguan_owner_channel_rebuild(user_id, business_key, payload):
    """`payload` 需带 `platform` 与 `mode`：

      * mode="clear" → 清空该格（点位 #5 的 :165）
      * mode="owner" → 从 DB 读回该账户的归属留痕（点位 #3）
          - gg：`accounts.owner_id` → `users` 的名字（**可重算**）
          - tt：`tt_accounts.owner_change_note`（**读回**——旧归属名与「月.日」无法从
            当前 DB 重算，但该串在写表前已落库；注意它是**单值列**，会被后续换绑覆盖）
    """
    p = payload or {}
    platform = p.get("platform")
    mode = p.get("mode")
    if not platform or mode not in ("clear", "owner"):
        raise RuntimeError("payload 需带 platform 与 mode(clear|owner)")

    def _sync():
        if mode == "clear":
            huguan_owner_channel_sync(user_id, platform, business_key, "")
            return
        import database
        db = database.get_db()
        try:
            if platform == "tt":
                r = db.execute(
                    "SELECT owner_change_note FROM tt_accounts WHERE advertiser_id=?",
                    (business_key,)).fetchone()
                value = (r["owner_change_note"] if r else "") or ""
            else:
                r = db.execute(
                    "SELECT COALESCE(NULLIF(u.display_name, ''), u.username, '') AS n "
                    "FROM accounts a LEFT JOIN users u ON a.owner_id = u.id "
                    "WHERE a.account_id = ?", (business_key,)).fetchone()
                value = (r["n"] if r else "") or ""
        finally:
            db.close()
        huguan_owner_channel_sync(user_id, platform, business_key, value)

    return _sync


# ---------- target: operator_dashboard_remark（点位 #2；唯一真正的第三方） ----------

def operator_dashboard_remark_sync(owner_id, account_id, value):
    """写**投手看板**的 J 列（备注）。表主人 = `owner_id`（账户 owner）。"""
    import database
    import google_sheets_service as gs
    import huguan_dashboard as hd
    from main import _GOOGLE_SHEETS_CONFIG

    db = database.get_db()
    try:
        row = db.execute("SELECT value FROM tags WHERE key='tt_sheet_id'").fetchone()
        sheet_id = (row["value"] if row else "") or ""
        if not sheet_id:
            raise RuntimeError("未配置 TT 表格 ID，无法写投手看板")
        sheet_name = hd._operator_dashboard_name(db, owner_id)
    finally:
        db.close()

    service = gs.build_service(_GOOGLE_SHEETS_CONFIG["credentials_path"])
    gs.update_rows_by_account_id(service, sheet_id, sheet_name,
                                 [{"account_id": account_id, "cells": {"J": value}}],
                                 key_col="D")


def _operator_dashboard_remark_rebuild(user_id, business_key, payload):
    """重建：J 列内容 = `tt_accounts.remark`（两条调用路径都在写表前落库）。"""
    def _sync():
        import database
        db = database.get_db()
        try:
            r = db.execute("SELECT remark FROM tt_accounts WHERE advertiser_id=?",
                           (business_key,)).fetchone()
            value = (r["remark"] if r else "") or ""
        finally:
            db.close()
        operator_dashboard_remark_sync(user_id, business_key, value)

    return _sync


# ---------- target: huguan_fb_acceptor（点位 #4） ----------

def huguan_fb_acceptor_sync(user_id, platform, account_id, note):
    """写 FB 接户运营列（I 列）。"""
    import database
    import google_sheets_service as gs
    import huguan_dashboard as hd
    from main import _GOOGLE_SHEETS_CONFIG

    db = database.get_db()
    try:
        conf = hd.get_platform_config(db, user_id, platform)
        if not conf["spreadsheet_id"] or not conf["sheet_name"]:
            raise RuntimeError("该看板未配置表格 ID 或工作表名")
        rows = hd._fb_acceptor_cells([{"account_id": account_id}], note)
    finally:
        db.close()
    if not rows:
        raise RuntimeError("无法构造 FB 接户运营待写行")

    service = gs.build_service(_GOOGLE_SHEETS_CONFIG["credentials_path"])
    gs.update_rows_by_account_id(service, conf["spreadsheet_id"], conf["sheet_name"], rows,
                                 key_col=hd.KEY_COL[platform])


def _huguan_fb_acceptor_rebuild(user_id, business_key, payload):
    """重建：I 列内容 = `fb_accounts.acceptor`（三条路径都在写表前落库）。"""
    def _sync():
        import database
        db = database.get_db()
        try:
            r = db.execute("SELECT acceptor FROM fb_accounts WHERE account_id=?",
                           (business_key,)).fetchone()
            note = (r["acceptor"] if r else "") or ""
        finally:
            db.close()
        if not note:
            return          # 与原实现一致：note 为空时早退（不写）
        huguan_fb_acceptor_sync(user_id, "fb", business_key, note)

    return _sync


# ---------- 注册（模块导入即生效） ----------

sheet_write.register_target("huguan_dashboard", rebuild=_huguan_dashboard_rebuild)
sheet_write.register_target("huguan_owner_channel", rebuild=_huguan_owner_channel_rebuild)
sheet_write.register_target("operator_dashboard_remark",
                            rebuild=_operator_dashboard_remark_rebuild)
sheet_write.register_target("huguan_fb_acceptor", rebuild=_huguan_fb_acceptor_rebuild)
