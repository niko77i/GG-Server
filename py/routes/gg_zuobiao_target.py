"""GG 做表线的写表目标（五期）。

设计见 docs/superpowers/specs/2026-10-09-sheet-write-governance-phase5-gg-zuobiao-design.md

镜像类（表 = 系统状态的投影，`upsert_zuobiao` 幂等）⇒ **不注册 `rollback`**，
最终失败落 `retry_failed`。rebuild 一律**从 DB 重算**（不重放 `rows_json` 快照），
**唯一例外**：养户行是请求侧产生、不落库的数据，DB 重算不出来 ⇒ 随 payload 携带
（见 `gg_zuobiao_kwargs` 与 `_gg_zuobiao_rebuild`），且绝不截断。

线程约束：所有 service 与 DB 连接都在**函数/闭包内**新建 —— 这些代码会在后台线程里跑。
"""
import logging

import sheet_write

log = logging.getLogger("gg-server")


def gg_zuobiao_key(product_name):
    """业务键 = 产品名（该线的日志本就按 `(user_id, product_name)` 定位）。"""
    return product_name


def _zuobiao_spreadsheet_id(db, user_id, report_date):
    """解析该用户**该月**的做表表格 ID。

    做表表是**按月切的**：先按「**操作人名 + `YYYY.MM`**」在 `sheets[].spreadsheet_name`
    里找匹配，找不到退回 `active_config`，再退回 `sheets[0]`。
    **不要简化成「取 active」** —— 那会写到别的月份的表里。

    逻辑等价于 `py/main.py` 的 `google_sheets_update_zuobiao`（`:7471-7490`）里的解析；
    差别只是配置在这里重新取一份（重建在后台线程里跑，没有请求上下文）。
    """
    from main import _get_user_sheets_config

    sheets, active_config = _get_user_sheets_config(user_id)
    if not sheets:
        return ""
    user = db.execute("SELECT display_name, username FROM users WHERE id=?",
                      (user_id,)).fetchone()
    operator_name = (user["display_name"] or user["username"]) if user else ""
    expected = f"{operator_name}{(report_date or '')[:7].replace('-', '.')}"
    matched = next((s for s in sheets
                    if expected in (s.get("spreadsheet_name", "") or "")), None)
    if matched:
        return matched.get("spreadsheet_id", "") or ""
    if active_config:
        return active_config.get("spreadsheet_id", "") or ""
    return (sheets[0].get("spreadsheet_id", "") or "")


def gg_zuobiao_kwargs(db, user_id, product_name, yanghu_rows=None,
                      fallback_report_date="", fallback_region=""):
    """从 DB 重算 `upsert_zuobiao` 的实参。返回 `(kwargs, None)` 或 `(None, 失败原因)`。

    这段重建**逐行搬自退役前的 `/api/google-sheets/retry-sync`**（`py/main.py` 原
    `:7697-7745`）—— 它本来就是唯一真相源。**唯一改动**：`spreadsheet_id` 的来源从
    `log_row["spreadsheet_id"]` 换成 `_zuobiao_spreadsheet_id(db, user_id)`
    （新路径没有 `sheets_sync_log` 行可读）。

    **养户行随 payload 携带**：养户行是请求侧数据、不落库（保存端点写库时只落非养户行，
    见 `py/main.py` 的 `db_rows` 过滤），DB 重建不出来 ⇒ 由 `yanghu_rows` 显式传入、
    追加在 `rows` 末尾。顺序取舍：旧行为按**请求原顺序**写；现在非养户行取自 DB
    （T2 已改为 DB 序、已过审），养户行追加在末尾并保持它们之间的原顺序 —— 这是本期
    接受的取舍，不为对齐旧顺序去重排 DB 行。

    纯养户行（DB 无该产品的非养户行）时，`report_date` / `region` 从 `fallback_*` 取 ——
    表格 ID 解析依赖 `report_date`（做表表按月切），所以纯养户行也必须拿到它。
    """
    rows_raw = db.execute(
        "SELECT DISTINCT account, customer_id, campaign, cost, impressions, clicks, "
        "installs, in_app_actions, cost_per_in_app, report_date, region "
        "FROM ad_reports WHERE user_id=? AND product_name=? ORDER BY report_date DESC",
        (user_id, product_name)).fetchall()
    if not rows_raw and not yanghu_rows:
        return None, "没有找到对应的做表数据"

    if rows_raw:
        report_date = rows_raw[0]["report_date"] or ""
        region = rows_raw[0]["region"] or ""
    else:
        report_date = fallback_report_date or ""
        region = fallback_region or ""

    # ⚠️ 表格 ID 依赖 report_date（做表表按月切，保存端点按「操作人名 + YYYY.MM」匹配表名）
    spreadsheet_id = _zuobiao_spreadsheet_id(db, user_id, report_date)
    if not spreadsheet_id:
        return None, "表格 ID 为空"
    rows = [{
        "account": r["account"] or "",
        "customerId": str(r["customer_id"] or ""),
        "campaign": r["campaign"] or "",
        "cost": r["cost"] or 0,
    } for r in rows_raw]
    rows = rows + list(yanghu_rows or [])

    prod = db.execute(
        "SELECT COALESCE(sp.name, '') AS sales_person, agency_ratio FROM products p "
        "LEFT JOIN sales_persons sp ON p.sales_person_id = sp.id "
        "WHERE p.product_name=? AND (p.is_archived IS NULL OR p.is_archived=0) LIMIT 1",
        (product_name,)).fetchone()
    user = db.execute("SELECT display_name, username FROM users WHERE id=?",
                      (user_id,)).fetchone()

    return {
        "spreadsheet_id": spreadsheet_id,
        "rows": rows,
        "product_name": product_name,
        "region": region,
        "report_date": report_date,
        "sales_person": (prod["sales_person"] or "") if prod else "",
        "agency_ratio": prod["agency_ratio"] if prod else None,
        "operator_name": ((user["display_name"] or user["username"]) if user else ""),
    }, None


def gg_zuobiao_sync(user_id, product_name, yanghu_rows=None,
                    fallback_report_date="", fallback_region=""):
    """把该产品的做表数据写进 Google 表格。养户行等参数透传给 `gg_zuobiao_kwargs`。"""
    import database
    import google_sheets_service as gs
    from main import _GOOGLE_SHEETS_CONFIG

    db = database.get_db()
    try:
        kwargs, why = gg_zuobiao_kwargs(db, user_id, product_name,
                                        yanghu_rows=yanghu_rows,
                                        fallback_report_date=fallback_report_date,
                                        fallback_region=fallback_region)
        if kwargs is None:
            raise RuntimeError(why)
    finally:
        db.close()

    service = gs.build_service(_GOOGLE_SHEETS_CONFIG["credentials_path"])
    gs.upsert_zuobiao(service=service, **kwargs)


def _gg_zuobiao_rebuild(user_id, business_key, payload):
    product_name = (payload or {}).get("product_name") or business_key
    if not product_name:
        raise RuntimeError("payload 缺 product_name，无法重建做表数据")

    # 养户行不落库 ⇒ 重建时从 payload 取。老日志行没有这些键 ⇒ `.get()` 缺省
    # ⇒ 行为与现状完全一致（不写养户行），不得因此抛错。
    yanghu_rows = (payload or {}).get("yanghu_rows") or []
    fallback_report_date = (payload or {}).get("report_date") or ""
    fallback_region = (payload or {}).get("region") or ""

    def _sync():
        gg_zuobiao_sync(user_id, product_name, yanghu_rows=yanghu_rows,
                        fallback_report_date=fallback_report_date,
                        fallback_region=fallback_region)

    return _sync


# ---------- 注册（模块导入即生效） ----------

sheet_write.register_target("gg_zuobiao", rebuild=_gg_zuobiao_rebuild)
