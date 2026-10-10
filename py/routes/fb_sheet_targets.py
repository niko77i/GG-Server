"""FB 报告做表的写表目标（四期）。

设计见 docs/superpowers/specs/2026-10-09-sheet-write-governance-phase4-fb-design.md

镜像类（表 = 系统状态的投影，一次 `upsert_fb_reports` 覆盖该组全部记录）⇒
**不注册 `rollback`**，最终失败落 `retry_failed`。

写表数据来源（2026-10-10 修复）：**优先用 payload 里的 records —— 那是本次解析
出来的数据**。`fb_ad_reports` 按账户 upsert、**只增不删**，同一 (产品,线,日期)
多次导入会累积成并集；若写表回库 SELECT 整组，本次只解析 5 行也会写出库里的全部
行。只有**历史 payload**（改造前登记、身上没有 records）才回退到从 DB 重建。

线程约束：所有 service 与 DB 连接都在**函数/闭包内**新建 —— 这些代码会在后台线程里跑。
"""
import logging

import sheet_write

log = logging.getLogger("gg-server")


def fb_report_key(product_name, line_name, report_date):
    """业务键 = `产品|线|日期`。**仅作前端展示**（汇总区要显示是哪一组失败）。

    重建**不**依赖拆它 —— 名字里若含 `|` 会拆错；权威来源是 payload（见下）。
    """
    return f"{product_name}|{line_name}|{report_date}"


def fb_report_sync(user_id, product_name, line_name, report_date, records=None):
    """把该 (产品,线,日期) 组的记录写进该用户的 FB 做表。

    `records` 非 None ⇒ 直接写它（**本次解析出来的数据**）；为 None ⇒ 回
    `fb_ad_reports` 重建（历史登记行 / 客户端 groups 入参没有 records）。
    """
    import database
    import google_sheets_service as gs

    db = database.get_db()
    try:
        if records is None:
            from routes.fb_routes import _rebuild_fb_records
            records, why = _rebuild_fb_records(db, user_id, product_name, line_name,
                                               report_date)
            if records is None:
                # 可操作的原因原样抛出 —— 它进 sheet_write_log.error_msg 前会被
                # 换成统一固定文案（防泄露），所以调用点用「登记前先重建」拦这类情况，
                # 不指望它到得了用户眼前（见 design §4.2）。
                raise RuntimeError(why)
        gs.upsert_fb_reports(db, user_id, product_name, line_name, report_date, records)
    finally:
        db.close()


def _payload_triple(payload, business_key):
    """从 payload 取 (产品,线,日期)。

    单条登记时 payload 是扁平三要素；批量登记（`run_write_many` 只有一个 payload）
    时是 `{"groups": {business_key: …}}` 的映射，值有两种形状：
      旧：`[产品, 线, 日期]`（改造前登记的行，必须继续能解析）
      新：`{"product_name":…, "line_name":…, "report_date":…, "records":[…]}`（带 records）
    """
    p = payload or {}
    if "product_name" in p:
        return (p.get("product_name"), p.get("line_name"), p.get("report_date"))
    g = (p.get("groups") or {}).get(business_key)
    if isinstance(g, dict):
        return (g.get("product_name"), g.get("line_name"), g.get("report_date"))
    if g:
        return tuple(g)
    # 错误信息带上 business_key：批量登记时 payload 里装着 N 组，只说「这组」
    # 定位不到是哪一组（该信息仅供日志/排查，非敏感）。
    raise RuntimeError(f"payload 里找不到这组「{business_key}」的 (产品,线,日期)，无法重建")


def _payload_records(payload, business_key):
    """从 payload 取本组的 records；**含空列表**；取不到返回 None。

    与 `_payload_triple` 同构，认同样的两种形状。返回 None 表示「这是历史 payload，
    没有记录本次解析的数据」⇒ 调用方回 `fb_ad_reports` 重建（老行的重试不能挂）。
    """
    p = payload or {}
    if "records" in p:
        return p.get("records")
    g = (p.get("groups") or {}).get(business_key)
    if isinstance(g, dict) and "records" in g:
        return g.get("records")
    return None


def _fb_report_rebuild(user_id, business_key, payload):
    product_name, line_name, report_date = _payload_triple(payload, business_key)
    records = _payload_records(payload, business_key)

    def _sync():
        fb_report_sync(user_id, product_name, line_name, report_date, records)

    return _sync


def fb_report_many_sync(user_id, groups):
    """**批量首跑/批量重试**用：一次覆盖 N 组。

    `run_write_many` 的 `sync_fn` 只执行**一次**；拿单组工厂顶上会让只有第一组被写
    而 N 行全落 `synced`（静默漏写，二期踩过）。

    每组可带各自的 records：元素是 dict（`{"product_name","line_name","report_date",
    "records"}`）或 3/4 元组（第 4 个是 records；缺省 ⇒ None ⇒ 回库重建）。
    """
    def _norm(g):
        if isinstance(g, dict):
            return (g.get("product_name"), g.get("line_name"),
                    g.get("report_date"), g.get("records"))
        g = tuple(g)
        if len(g) >= 4:
            return (g[0], g[1], g[2], g[3])
        return (g[0], g[1], g[2], None)

    norm = [_norm(g) for g in groups]

    def _sync():
        for product_name, line_name, report_date, records in norm:
            fb_report_sync(user_id, product_name, line_name, report_date, records)

    return _sync


# ---------- 注册（模块导入即生效） ----------

sheet_write.register_target("fb_report", rebuild=_fb_report_rebuild)
