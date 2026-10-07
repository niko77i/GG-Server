"""GG「我的看板」写表目标。

设计见 docs/superpowers/specs/2026-10-07-sheet-write-governance-phase2-gg-design.md。

GG 侧全是「主数据镜像」：看板那一行是 accounts 行的投影，故**不注册 rollback**
（把系统回滚了镜像反而失真）。重建一律从 accounts 重算，与既有
`_sync_back_to_dashboard`（main.py:5516）的写法定全一致。
"""
import sheet_write

TARGET = "gg_my_dashboard"


def _gg_dashboard_write(dash_uid, account_ids):
    """直写：对每个 account_id，F 列写状态名、H 列写「解绑」/空。

    **在后台线程内执行** —— service 必须在这里 build（httplib2 非线程安全），
    DB 连接也必须现开（sqlite 连接不可跨线程）。
    """
    import database
    import google_sheets_service as gs
    # 延迟 import：这两个 helper 定义在 main.py，而 main 会 import 本模块（注册 target），
    # 顶层 import 会成环。GOOGLE_SHEETS_CONFIG 同理。
    from main import _GOOGLE_SHEETS_CONFIG, _get_sync_spreadsheet_id, _get_my_dashboard_name

    db = database.get_db()
    try:
        sheet_id = _get_sync_spreadsheet_id(db)
        dashboard_name = _get_my_dashboard_name(db, dash_uid)
        if not sheet_id or not dashboard_name:
            raise RuntimeError("未配置看板表格 ID 或工作表名，无法写我的看板")
        rows = db.execute(
            "SELECT a.account_id, a.deleted_at, st.name AS status_name "
            "FROM accounts a LEFT JOIN account_statuses st ON a.status_id = st.id "
            f"WHERE a.id IN ({','.join('?' for _ in account_ids)})",
            tuple(account_ids)).fetchall()
        payload = [(r["account_id"], r["status_name"] or "存活", r["deleted_at"] or "")
                   for r in rows]
    finally:
        db.close()

    if not payload:
        raise RuntimeError("找不到对应账户，无法重建看板行")

    service = gs.build_service(_GOOGLE_SHEETS_CONFIG["credentials_path"])
    for account_id, st, deleted in payload:
        # 备注列（F 列）：写状态；是否解绑（H 列）：已删除写「解绑」，未删除清空
        gs.update_cell_by_account_id(service, sheet_id, dashboard_name, account_id, st)
        gs.update_cell_by_account_id(service, sheet_id, dashboard_name, account_id,
                                     "解绑" if deleted else "", col_index=7)


def build_many_sync(user_id, business_keys, payload):
    """**首跑**用：一次后台写表覆盖 N 个账户（`run_write_many` 的 sync_fn 只执行一次）。

    为什么不能拿单户工厂 `build_sync(target, user_id, business_keys[0], payload)` 顶上：
    `run_write_many` 只调用 sync_fn **一次**（一个后台线程），于是只有第一户被写进表，
    而 N 行日志会**全部**落 synced —— 静默漏写，且比原实现更糟（原实现是一个后台线程
    串行写 N 户）。批量改状态（batch-update）与从表同步回写（sync-from-sheet）都走这里。

    重试仍走 `sheet_write.build_sync`（单户）：重试是按 business_key **逐行**触发的，
    把那户刷到与系统一致即可；若让重试也覆盖整批，前端逐行重试会退化成 N² 次写调用。
    """
    dash_uid = (payload or {}).get("dash_uid") or user_id
    keys = list(business_keys)

    def _sync():
        import database
        db = database.get_db()
        try:
            marks = ",".join("?" for _ in keys)
            rows = db.execute(
                f"SELECT id FROM accounts WHERE account_id IN ({marks})",
                tuple(keys)).fetchall()
        finally:
            db.close()
        # 有键查不到账户就不写：宁可如实失败（N 行落 retry_failed），也不能把
        # 「没刷到的那些户」报成 synced —— 那正是本功能要消灭的静默失败。
        if not rows or len(rows) != len(set(keys)):
            raise RuntimeError("部分账户不存在，无法重建看板行")
        _gg_dashboard_write(dash_uid, [r["id"] for r in rows])

    return _sync


def _gg_dashboard_rebuild(user_id, business_key, payload):
    """重试时重建同步函数。business_key = account_id；dash_uid 由 payload 带。

    dash_uid 必须在 payload 里：既有代码解析「写谁的看板」并不一致
    （改状态/批量用操作者，删户/恢复用账户 owner），本 target 不改变该差异，
    只把它编码进 payload 以便重建复现。
    """
    dash_uid = (payload or {}).get("dash_uid") or user_id

    def _sync():
        import database
        db = database.get_db()
        try:
            row = db.execute("SELECT id FROM accounts WHERE account_id=?",
                             (business_key,)).fetchone()
        finally:
            db.close()
        if row is None:
            raise RuntimeError(f"账户 {business_key} 不存在，无法重建看板行")
        _gg_dashboard_write(dash_uid, [row["id"]])

    return _sync


sheet_write.register_target(TARGET, rebuild=_gg_dashboard_rebuild)
