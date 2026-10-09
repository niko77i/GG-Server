"""FB 报告写表点接入统一治理 —— 端到端测试。

守卫两件事：(1) 三个写点都登记正确的 target 与 business_key；
(2) 最终失败落 retry_failed（镜像类，**不得**出现 rolled_back）。

⚠️ 轮询必须用**模块顶层**捕获的真 sleep（下）：测试里 monkeypatch 的是全局
`time.sleep`（跳过 30s 重试），轮询循环自己也调 sleep —— 在 patch 之后再
`from time import sleep` 会拿到桩函数、主线程不让出 GIL、断言提前开火。
"""
import json
from time import sleep as _poll_sleep

import database
import sheet_write


def _fb_user(client, username):
    """注册一个 fb 平台用户并返回 (headers, uid)。"""
    client.post("/api/auth/register", json={"username": username, "password": "test123"})
    db = database.get_db()
    db.execute("UPDATE users SET platform='fb' WHERE username=?", (username,))
    db.commit()
    uid = db.execute("SELECT id FROM users WHERE username=?", (username,)).fetchone()["id"]
    db.close()
    resp = client.post("/api/auth/login", json={"username": username, "password": "test123"})
    return {"Authorization": f"Bearer {resp.get_json().get('access_token', '')}"}, uid


def _seed_report(db, uid, product="产品甲", line="线A", date="2026-10-01", acc="acc_1"):
    db.execute(
        "INSERT INTO fb_ad_reports (user_id, product_name, line_name, report_date, "
        "account_name, account_id, cost, impressions, clicks, registrations, purchases, "
        "cost_per_purchase) VALUES (?,?,?,?,'名','"+acc+"',1,2,3,4,5,6)",
        (uid, product, line, date))
    db.commit()


def _row(db, uid, key):
    return db.execute("SELECT * FROM sheet_write_log WHERE user_id=? AND target='fb_report' "
                      "AND business_key=?", (uid, key)).fetchone()


def _settle(db, uid, key, tries=300):
    for _ in range(tries):
        r = _row(db, uid, key)
        if r is not None and r["status"] in sheet_write.TERMINAL:
            return r
        _poll_sleep(0.02)
    return _row(db, uid, key)


def test_fb_report_target_registered_without_rollback():
    """target 必须已注册（漏 import 就 KeyError ⇒ 500），且**不注册 rollback**。"""
    import routes.fb_sheet_targets  # noqa: F401
    assert "fb_report" in sheet_write.TARGETS, "target 未注册"
    assert sheet_write.TARGETS["fb_report"]["rollback"] is None, \
        "镜像类不得注册 rollback（会让最终失败落 rolled_back 而非 retry_failed）"


def test_fb_report_sync_rebuilds_from_db(client, monkeypatch):
    """rebuild 从 fb_ad_reports 重算，并把 (产品,线,日期) 原样交给 upsert。"""
    import google_sheets_service as gs
    import routes.fb_sheet_targets as tgt
    calls = []
    monkeypatch.setattr(gs, "upsert_fb_reports",
                        lambda db, uid, p, l, d, records: calls.append(
                            (p, l, d, sorted(r["account_id"] for r in records))))

    _, uid = _fb_user(client, "_fbsw_sync")
    db = database.get_db()
    _seed_report(db, uid, acc="acc_1")
    _seed_report(db, uid, acc="acc_2")
    db.close()

    tgt.fb_report_sync(uid, "产品甲", "线A", "2026-10-01")
    assert calls == [("产品甲", "线A", "2026-10-01", ["acc_1", "acc_2"])], f"实际 {calls}"


def test_fb_report_sync_raises_actionable_reason_when_no_rows(client):
    """找不到原始数据 ⇒ raise 带**可操作**原因（不是固定文案）。"""
    import routes.fb_sheet_targets as tgt
    _, uid = _fb_user(client, "_fbsw_norows")
    try:
        tgt.fb_report_sync(uid, "产品甲", "线A", "2099-01-01")
    except RuntimeError as e:
        assert "找不到对应的原始数据" in str(e), f"原因应可操作，实际 {e}"
    else:
        raise AssertionError("没有原始数据时必须抛错，不得静默成功")


def test_fb_report_final_failure_lands_retry_failed(client, monkeypatch):
    """最终失败落 retry_failed（**不是** rolled_back）—— 零回滚守卫。"""
    import google_sheets_service as gs
    import time as _time
    monkeypatch.setattr(_time, "sleep", lambda _s: None)
    monkeypatch.setattr(gs, "build_service", lambda _p: object())

    def _boom(*a, **k):
        raise RuntimeError("Sheets 配额超限")

    monkeypatch.setattr(gs, "upsert_fb_reports", _boom)

    _, uid = _fb_user(client, "_fbsw_fail")
    db = database.get_db()
    _seed_report(db, uid)
    key = __import__("routes.fb_sheet_targets", fromlist=["x"]).fb_report_key(
        "产品甲", "线A", "2026-10-01")
    sync_fn = sheet_write.build_sync("fb_report", uid, key,
                                     {"product_name": "产品甲", "line_name": "线A",
                                      "report_date": "2026-10-01"})
    sheet_write.run_write(db, user_id=uid, platform="fb", target="fb_report",
                          business_key=key, sync_fn=sync_fn,
                          payload={"product_name": "产品甲", "line_name": "线A",
                                   "report_date": "2026-10-01"})
    r = _settle(db, uid, key)
    db.close()

    assert r is not None, "必须登记日志行"
    assert r["status"] == "retry_failed", f"应落 retry_failed，实际 {r['status']}"
    assert r["status"] not in ("rolled_back", "rollback_abandoned"), "镜像类不得回滚"
