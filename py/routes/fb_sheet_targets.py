"""FB 报告做表的写表目标（四期）。

设计见 docs/superpowers/specs/2026-10-09-sheet-write-governance-phase4-fb-design.md

镜像类（表 = 系统状态的投影，一次 `upsert_fb_reports` 覆盖该组全部记录）⇒
**不注册 `rollback`**，最终失败落 `retry_failed`。rebuild 一律**从 DB 重算**。

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


def fb_report_sync(user_id, product_name, line_name, report_date):
    """把该 (产品,线,日期) 组的记录写进该用户的 FB 做表。"""
    import database
    import google_sheets_service as gs
    from routes.fb_routes import _rebuild_fb_records

    db = database.get_db()
    try:
        records, why = _rebuild_fb_records(db, user_id, product_name, line_name, report_date)
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
    时是 `{"groups": {business_key: [产品,线,日期], …}}` 的映射。
    """
    p = payload or {}
    if "product_name" in p:
        return (p.get("product_name"), p.get("line_name"), p.get("report_date"))
    tri = (p.get("groups") or {}).get(business_key)
    if not tri:
        # 错误信息带上 business_key：批量登记时 payload 里装着 N 组，只说「这组」
        # 定位不到是哪一组（该信息仅供日志/排查，非敏感）。
        raise RuntimeError(f"payload 里找不到这组「{business_key}」的 (产品,线,日期)，无法重建")
    return tuple(tri)


def _fb_report_rebuild(user_id, business_key, payload):
    product_name, line_name, report_date = _payload_triple(payload, business_key)

    def _sync():
        fb_report_sync(user_id, product_name, line_name, report_date)

    return _sync


def fb_report_many_sync(user_id, groups):
    """**批量首跑/批量重试**用：一次覆盖 N 组。

    `run_write_many` 的 `sync_fn` 只执行**一次**；拿单组工厂顶上会让只有第一组被写
    而 N 行全落 `synced`（静默漏写，二期踩过）。
    """
    groups = [tuple(g) for g in groups]

    def _sync():
        for product_name, line_name, report_date in groups:
            fb_report_sync(user_id, product_name, line_name, report_date)

    return _sync


# ---------- 注册（模块导入即生效） ----------

sheet_write.register_target("fb_report", rebuild=_fb_report_rebuild)
