"""GG「充值表」写表目标。

镜像类：写表前 recharge_records 行已落库，表只是副本，故**不注册 rollback**。
重建一律从 recharge_records 重算（与旧 `retry-sheets` 端点的写法定全一致 ——
该端点现已改为转调 `POST /api/sheet-write/retry` 的薄封装）。
"""
import sheet_write

TARGET = "gg_recharge"


def _gg_recharge_write(rids):
    """直写：按 rids 从 recharge_records 重建追加行并写表。后台线程内执行。"""
    import database
    import google_sheets_service as gs
    # 延迟 import：这几个 helper 定义在 main.py，而 main 会 import 本模块（注册 target），
    # 顶层 import 会成环。与 routes/gg_dashboard_sheet.py 同一写法。
    from main import _GOOGLE_SHEETS_CONFIG, _get_sync_spreadsheet_id, _get_recharge_sheet_name

    db = database.get_db()
    try:
        sheet_id = _get_sync_spreadsheet_id(db)
        sheet_name = _get_recharge_sheet_name(db)
        if not sheet_id:
            raise RuntimeError("未配置充值表格 ID，无法写充值表")
        marks = ",".join("?" for _ in rids)
        # 代理名只能取 `agents.name`（JOIN `agent_id`）：
        #   - 四个充值写点的 INSERT 只落 agent_id；
        #   - `recharge_records.agent`（TEXT）**已被迁移删除** ——
        #     database.py:_cleanup_old_option_columns 在把 agent 反填进 agent_id 之后
        #     `ALTER TABLE recharge_records DROP COLUMN agent` ⇒ 在新库/已迁移库上
        #     写 `r.agent` 直接 "no such column"（实测报错）。
        # 与旧 retry-sheets 端点（改造前 `COALESCE(ag.name,'') AS agent`）的写法定全一致。
        rows = db.execute(
            "SELECT r.account_id, r.amount, r.operator, r.status, "
            "COALESCE(ag.name, '') AS agent "
            "FROM recharge_records r LEFT JOIN agents ag ON ag.id = r.agent_id "
            f"WHERE r.id IN ({marks})",
            tuple(rids)).fetchall()
        # N 个键必须**全部**查得到：少写一条却仍报 synced 就是本功能要消灭的静默漏写
        # （同 gg_dashboard_sheet.build_many_sync 的守卫）。
        if not rows or len(rows) != len(set(rids)):
            raise RuntimeError("找不到对应充值记录，无法重建待写行")
        payload = [{"account_id": r["account_id"], "amount": r["amount"],
                    "agent": r["agent"] or "", "operator": r["operator"] or "",
                    **({"status": r["status"]} if r["status"] else {})}
                   for r in rows]
    finally:
        db.close()

    service = gs.build_service(_GOOGLE_SHEETS_CONFIG["credentials_path"])
    gs.append_recharge(service, sheet_id, sheet_name, payload)


def _gg_recharge_rebuild(user_id, business_key, payload):
    """重试时重建同步函数。business_key = recharge_records.id（字符串）。

    必须是**纯构造**（register_target 的契约）：int() 解析放在闭包内，
    故本工厂不做任何 I/O、也不会在「原子 claim 之前」失败。
    """
    def _sync():
        try:
            rid = int(business_key)
        except (TypeError, ValueError):
            raise RuntimeError(f"非法的充值记录 id: {business_key}")
        _gg_recharge_write([rid])

    return _sync


def build_many_sync(user_id, business_keys, payload):
    """**首跑**用：一次后台写表覆盖 N 条充值记录。

    `run_write_many` 只执行 sync_fn **一次**（一个后台线程）。若拿单键工厂
    `build_sync(target, user_id, keys[0], payload)` 顶上，只有第一条会被写进表，
    而 N 行日志**全部**落 `synced` —— 静默漏写，比改前的串行循环更糟。

    重试仍走单键 `build_sync`：重试按 business_key 逐条触发，让重试也覆盖整批
    会让前端逐行重试退化成 N² 次写调用。
    """
    rids = []
    for k in business_keys:
        try:
            rids.append(int(k))
        except (TypeError, ValueError):
            raise RuntimeError(f"非法的充值记录 id: {k}")

    def _sync():
        _gg_recharge_write(rids)

    return _sync


sheet_write.register_target(TARGET, rebuild=_gg_recharge_rebuild)
