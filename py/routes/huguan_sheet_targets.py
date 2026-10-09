"""户管看板域的写表目标（三期）。

设计见 docs/superpowers/specs/2026-10-08-sheet-write-governance-phase3-huguan-design.md

全部是**镜像类**（表 = 系统状态的投影）⇒ 一律不注册 `rollback`，最终失败落 `retry_failed`。
rebuild 一律**从 DB 重算**，不重放快照。

⚠️ `sheet_write_log.user_id` 记的是**表主人**（规格 §3.5）：除
`operator_dashboard_remark` 外，其余三个 target 的表主人 == 触发者（这些操作只有户管会做）。

线程约束：所有 service 与 DB 连接都在**函数/闭包内**新建 —— 这些代码会在后台线程里跑，
sqlite 连接与 httplib2 客户端都不可跨线程复用。
"""
import logging

import sheet_write

log = logging.getLogger("gg-server")


def _resolve_account_table(db, user_id, platform, account_id):
    """按账户的**户类型**解析它该写哪张 worksheet 的配置项（`{name, sheet_name, columns}`）。

    解析不到 → 返回 None，由调用方决定「跳过」还是「报失败」。
    gg / fb 的类型恒为空串、配置里恰有一个空名条目 ⇒ 恒命中那唯一一张表，
    行为与改动前（单表）等价；只有 tt 会真正分表。

    返回**整项**而不只是工作表名：写表前要按该表的 `columns`（手工覆盖）解析 col_map，
    读路径用的是同一份配置（`get_platform_tables` 的同一项），读写必须同源。
    """
    import huguan_dashboard as hd

    tables = hd.get_platform_tables(db, user_id, platform)
    if not tables:
        return None
    atype = ""
    if platform == "tt":
        r = db.execute("SELECT account_type FROM tt_accounts WHERE advertiser_id=?",
                       (account_id,)).fetchone()
        atype = (r["account_type"] if r else "") or ""
    for t in tables:
        if t["name"] == atype:
            return t
    return None


def _resolve_sheet_name(db, user_id, platform, account_id):
    """按账户的**户类型**解析它该写哪张 worksheet 的名字（见 `_resolve_account_table`）。"""
    t = _resolve_account_table(db, user_id, platform, account_id)
    return t["sheet_name"] if t else None


# ---------- target: huguan_dashboard（整行刷新；覆盖点位 #1 与 #5 的 :159/:171/:180） ----------

def huguan_dashboard_sync(user_id, platform, account_ids):
    """把这些账户的**整行**刷新到该户管的看板（tt 多表：按户类型各写各的 worksheet）。

    重建走 `collect_rows_for_push` —— 与既有 `push_rows` 同一条路径。
    `cells_for_row` 只产出系统拥有的可写列，**刻意不含**归属变更通道列（规格 §7.2 规则 2），
    故不会碰到户管用公式维护的列。

    **选表在这里做**（而不是在 `push_rows` / `_write_background_tables` 里）：重试路径
    同样要选表，只有放在写表处才不会出现「首次写对、重试写错表」。口径与 `group_rows_by_sheet`
    一致：查不到对应工作表的户类型**跳过并记 warning**，绝不退回写第一张表
    —— 那会把甲类账户的内容覆盖进乙类的 worksheet。
    """
    import database
    import google_sheets_service as gs
    import huguan_dashboard as hd
    from main import _GOOGLE_SHEETS_CONFIG

    db = database.get_db()
    try:
        tables = hd.get_platform_tables(db, user_id, platform)
        if not tables:
            raise RuntimeError("该看板未配置账户表")
        spreadsheet_id = hd.get_platform_config(db, user_id, platform)["spreadsheet_id"]
        if not spreadsheet_id:
            raise RuntimeError("该看板未配置表格 ID")
        # 写表前逐表解析 col_map（tt 读一次表头行；gg/fb 零额外读）。用该表配置里的
        # 手工覆盖 `columns` —— 与读路径（`dashboard_sync` 的 `t.get("columns")`）**同源**，
        # 否则读写对「哪一列是定位键」认识不一致，写就会落到错行。
        service = gs.build_service(_GOOGLE_SHEETS_CONFIG["credentials_path"])
        col_map_by_sheet = {
            t["sheet_name"]: hd.resolve_table_col_map(
                service, spreadsheet_id, t["sheet_name"], platform, t.get("columns") or {})
            for t in tables
        }
        # cells 也要按本表的 col_map 产出：tt 表头顺序不一定等于固定列规格。
        col_maps_by_type = {t["name"]: col_map_by_sheet[t["sheet_name"]] for t in tables}
        rows = hd.collect_rows_for_push(db, platform, list(account_ids), col_maps_by_type)
        groups, skipped = hd.group_rows_by_sheet(db, user_id, platform, rows)
        for name in skipped:
            log.warning("看板回写跳过：户类型「%s」查不到工作表 user=%s platform=%s",
                        name, user_id, platform)
    finally:
        db.close()
    if not rows:
        raise RuntimeError("找不到对应账户，无法重建看板行")
    # 一组都没有 ⇒ 每一行的户类型都查不到工作表。master 侧对此是静默 no-op，但三期要求
    # 「失败可见」：仍然不写错表（沿用他们的选择），同时**明确报失败** —— 否则日志行会落
    # synced 而表里一行没写，那正是本期要消灭的静默形态。
    if not groups:
        raise RuntimeError("所有账户的户类型都查不到对应工作表，未写入")

    for sheet_name, sheet_rows in groups:
        # key_col 从**本表**的 col_map 取（tt 表头顺序不同时账户ID 不在 C 列）。
        cm = col_map_by_sheet.get(sheet_name) or hd.spec_column_map(platform)
        gs.update_rows_by_account_id(service, spreadsheet_id, sheet_name, sheet_rows,
                                     key_col=hd.key_col_of_col_map(cm, platform))


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

def huguan_owner_channel_sync(user_id, platform, account_id, value, role="channel"):
    """**单格定向写**归属相关的某一列：
    `role="channel"` → 归属变更通道列（GG=H / TT=L）；
    `role="owner"`   → 运营/归属列（gg/tt=G，即 `apply_diff` 的 `item["to"]` 的落点）。
    `value` 为空串即清空该格。

    刻意**只写这一格**（与 `owner_channel_cells` 同一原则）：顺手带上别的列，就会把
    户管在表里的其他手工改动一起冲掉 —— 归属变更那一行尤其如此，所以它**不走**
    `huguan_dashboard` 的整行重建。

    选表按该账户的**户类型**（tt 多表）。这里解析不到就**报失败**、不跳过 ——
    入口侧已经有「解析不到就早退、不登记」的闸门，能走到这里说明配置是在登记之后
    才变的（户类型被改名 / 表被删），必须让用户在日志行上看见，而不是静默 no-op。
    """
    import database
    import google_sheets_service as gs
    import huguan_dashboard as hd
    from main import _GOOGLE_SHEETS_CONFIG

    db = database.get_db()
    try:
        spreadsheet_id = hd.get_platform_config(db, user_id, platform)["spreadsheet_id"]
        if not spreadsheet_id:
            raise RuntimeError("该看板未配置表格 ID")
        table = _resolve_account_table(db, user_id, platform, account_id)
        if not table:
            raise RuntimeError("该账户的户类型查不到对应工作表")
        sheet_name = table["sheet_name"]
        columns = table.get("columns") or {}
    finally:
        db.close()

    service = gs.build_service(_GOOGLE_SHEETS_CONFIG["credentials_path"])
    # 写表前按**该表**表头解析 col_map（tt 读一次表头行；gg/fb 零额外读）。定位键列
    # 与角色列都可能不在固定字母上（tt 表头顺序不同）—— 只改 key_col 而列仍写死，
    # 等于把归属名写进别的列，冲掉户管在表里的手工内容。
    cm = hd.resolve_table_col_map(service, spreadsheet_id, sheet_name, platform, columns)
    # gg/fb 的 col_map 就是固定规格，用 None 走既有固定字母路径（含它们的既有抛错口径，
    # 逐字节不变）；只有 tt 需要按表头定位角色列。
    col = hd.owner_role_col(platform, role, cm if platform == "tt" else None)
    if col is None:
        # 该表没有这一列（未采集）⇒ 一个字不碰（与 owner_channel_cells 同口径）
        return
    rows = [{"account_id": account_id, "cells": {col: value}}]
    gs.update_rows_by_account_id(service, spreadsheet_id, sheet_name, rows,
                                 key_col=hd.key_col_of_col_map(cm, platform))


def _huguan_owner_channel_rebuild(user_id, business_key, payload):
    """`payload` 需带 `platform` 与 `mode`：

      * mode="clear" → 清空该格（点位 #5 的 :165）
      * mode="owner" → 写该账户的归属留痕（点位 #3）
          - 优先取 `payload["value"]`（调用方写表前已算好：TT 的「旧转新月.日」整串
            含「旧归属人」，是从当前 DB **重算不出来**的）
          - 老路径（payload 未带 value）才回读 DB：
              · gg：`accounts.owner_id` → `users` 的名字（**可重算**）
              · tt：`tt_accounts.owner_change_note`（**读回**——单值列，会被后续换绑覆盖）

    另可带 `col_role`（缺省 "channel"）：写哪一列。`"channel"` = 归属变更通道列
    （gg=H / tt=L），`"owner"` = 运营/归属列（gg/tt=G，归属变更同步回来的落点）。
    **老行没有这个键 ⇒ 取缺省 "channel"，行为与改动前逐字一致。**
    """
    p = payload or {}
    platform = p.get("platform")
    mode = p.get("mode")
    if not platform or mode not in ("clear", "owner"):
        raise RuntimeError("payload 需带 platform 与 mode(clear|owner)")
    col_role = p.get("col_role") or "channel"

    def _sync():
        if mode == "clear":
            huguan_owner_channel_sync(user_id, platform, business_key, "", role=col_role)
            return
        if "value" in p:
            value = p.get("value") or ""
        else:
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
        huguan_owner_channel_sync(user_id, platform, business_key, value, role=col_role)

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
    """重建：J 列内容**优先取 `payload["value"]`**（触发时的备注原文）。

    为什么不回读 `tt_accounts.remark`：本 target 有一条调用路径
    （`routes/tt_accounts_routes.py::update_account`）在 `db.commit()` **之前**就发起写表；
    重建若另起连接回读该列，读不到尚未提交的 UPDATE ⇒ 会把**旧备注**写进 J 列
    （Task 2 复核发现的遗留缺陷）。触发值既已在写表前算好，随 payload 落库最稳。

    兼容未带 value 的旧路径（如 `sheet_write.build_sync(..., {})`）：回读该列，
    此时调用方要么已提交、要么本就走的是读数路径。
    """
    def _sync():
        p = payload or {}
        if "value" in p:
            value = p.get("value") or ""
        else:
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
    """写 FB 接户运营列（I 列）。

    本 target 只用于 fb（`_huguan_fb_acceptor_rebuild` 里平台是硬编码的 "fb"），
    而 fb 恒为单表 ⇒ 走 `_resolve_sheet_name` 会命中那个唯一的空名条目，
    行为与改动前等价；用同一个 helper 只是为了让「选表」只有一处实现。
    """
    import database
    import google_sheets_service as gs
    import huguan_dashboard as hd
    from main import _GOOGLE_SHEETS_CONFIG

    db = database.get_db()
    try:
        spreadsheet_id = hd.get_platform_config(db, user_id, platform)["spreadsheet_id"]
        if not spreadsheet_id:
            raise RuntimeError("该看板未配置表格 ID")
        sheet_name = _resolve_sheet_name(db, user_id, platform, account_id)
        if not sheet_name:
            raise RuntimeError("查不到该看板的工作表")
        rows = hd._fb_acceptor_cells([{"account_id": account_id}], note)
    finally:
        db.close()
    if not rows:
        raise RuntimeError("无法构造 FB 接户运营待写行")

    service = gs.build_service(_GOOGLE_SHEETS_CONFIG["credentials_path"])
    gs.update_rows_by_account_id(service, spreadsheet_id, sheet_name, rows,
                                 key_col=hd.KEY_COL[platform])


def _huguan_fb_acceptor_rebuild(user_id, business_key, payload):
    """重建：I 列内容优先取 `payload["value"]`（触发时的「旧转新」整串）；
    未带 value 的老路径回读 `fb_accounts.acceptor`。"""
    def _sync():
        p = payload or {}
        if "value" in p:
            note = p.get("value") or ""
        else:
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
