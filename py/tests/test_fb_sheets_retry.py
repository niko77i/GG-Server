"""FB 做表数据「重试同步」回归测试。

守卫的缺陷（2026-10-06 修复）：`POST /api/fb/reports/retry-sync` 原先读
`sheets_sync_log` 的两个**不存在的列** ——
  · `row_data`：列名实际是 `rows_json`
  · `report_date`：该表根本没有这一列
两处都抛 `IndexError`，被 `except` 兜住后单条分支恒返回 500
「重试失败: No item with that key」，批量分支则被**裸 `except` 静默吞掉**、
只把 `retry_count+1`，用户看到 `retried: 0` 却无从知道原因。

修法不是把列名改对就完事：`rows_json` 在写入时被 `[:10000]` 截断
（`fb_routes.extract_save`），每条 record 约 200 字符，超过约 50 条即从中间
断开，`json.loads` 照样抛错。故改为按 (产品名, 线名, 日期) 回查
`fb_ad_reports` 重建待写数据 —— 那里存的是完整原始行。

**四期迁移（2026-10-09）**：重试端点从「请求线程直写 Sheets」改为「登记 → 后台
写表」（`sheet_write.run_write` / `run_write_many`），成功即删除失败行的旧语义
随之作废。判据**语义不降**：重建出的 (产品, 线名, 日期) 与 records 仍必须原样
交给 `upsert_fb_reports`；重建失败的原因仍必须**可操作地**回给用户（重建前置，
见 design §4.2）—— 只是「等写表完成」从同步返回变为轮询 `sheet_write_log`。
"""
import json
from time import sleep as _poll_sleep

import database
import sheet_write
import routes.fb_sheet_targets as _fbt


def _create_user(client, username, role="user", platform="fb"):
    """注册 → 改 role/platform → 登录，返回 (headers, user_id)。"""
    client.post("/api/auth/register", json={"username": username, "password": "test123"})
    db = database.get_db()
    db.execute("UPDATE users SET role=?, platform=? WHERE username=?",
               (role, platform, username))
    db.commit()
    uid = db.execute("SELECT id FROM users WHERE username=?", (username,)).fetchone()["id"]
    db.close()
    resp = client.post("/api/auth/login", json={"username": username, "password": "test123"})
    return {"Authorization": f"Bearer {resp.get_json().get('access_token', '')}"}, uid


def _mk_ad_report(db, uid, product_name, line_name, report_date, account_id, cost=1.0):
    """插一行 fb_ad_reports —— 重试重建待写数据的数据来源。"""
    db.execute(
        "INSERT INTO fb_ad_reports (user_id, product_name, line_name, report_date, "
        "account_name, account_id, cost, impressions, clicks, registrations, "
        "purchases, cost_per_purchase) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        (uid, product_name, line_name, report_date, f"账户{account_id}", account_id,
         cost, 100, 10, 1, 2, 0.5))
    db.commit()


def _patch_upsert(monkeypatch, calls):
    """替换掉真正的 Sheets 写，只记录调用参数。"""
    import google_sheets_service as gs

    def _fake(db, user_id, product_name, line_name, report_date, records):
        calls.append({"user_id": user_id, "product_name": product_name,
                      "line_name": line_name, "report_date": report_date,
                      "records": records})
        return {"updated": len(records)}

    monkeypatch.setattr(gs, "upsert_fb_reports", _fake)


def _fb_row(db, uid, key):
    return db.execute(
        "SELECT * FROM sheet_write_log WHERE user_id=? AND target='fb_report' "
        "AND business_key=?", (uid, key)).fetchone()


def _settle_fb(db, uid, key, tries=300):
    """轮询等 fb_report 任务落终态（写表已异步化）。"""
    for _ in range(tries):
        r = _fb_row(db, uid, key)
        if r is not None and r["status"] in sheet_write.TERMINAL:
            return r
        _poll_sleep(0.02)
    return _fb_row(db, uid, key)


def _wait_calls(calls, n=1, tries=300):
    for _ in range(tries):
        if len(calls) >= n:
            break
        _poll_sleep(0.02)


def test_retry_single_rebuilds_from_fb_ad_reports(client, monkeypatch):
    """单条重试：按 (产品, 线名, 日期) 重建 records，并把线名/日期原样带上。

    修复前这条必然 500（读不存在的 row_data / report_date 列）。
    """
    headers, uid = _create_user(client, "_fb_retry_ok")
    db = database.get_db()
    _mk_ad_report(db, uid, "产品甲", "线A", "2026-10-01", "acc_1", cost=3.0)
    _mk_ad_report(db, uid, "产品甲", "线A", "2026-10-01", "acc_2", cost=7.0)
    # 同产品同日但不同线名 —— 不得被带进来
    _mk_ad_report(db, uid, "产品甲", "线B", "2026-10-01", "acc_9", cost=99.0)
    db.close()

    calls = []
    _patch_upsert(monkeypatch, calls)

    resp = client.post("/api/fb/reports/retry-sync", headers=headers,
                       json={"groups": [["产品甲", "线A", "2026-10-01"]]})
    assert resp.status_code == 200, resp.get_json()
    assert resp.get_json()["accepted"] == 1, resp.get_json()

    _wait_calls(calls, 1)
    assert len(calls) == 1, f"应恰好写一组，实际 {calls}"
    call = calls[0]
    # 线名必须带上：upsert_fb_reports 把它当渠道号写进 J 列
    assert call["line_name"] == "线A"
    # 日期必须带上：它决定写进哪个月的表格（report_date[:7]）
    assert call["report_date"] == "2026-10-01"
    assert call["product_name"] == "产品甲"
    assert sorted(r["account_id"] for r in call["records"]) == ["acc_1", "acc_2"]

    # 原判据「成功后失败行消失」在四期等价于：这条任务登记成功并落 synced
    key = _fbt.fb_report_key("产品甲", "线A", "2026-10-01")
    db = database.get_db()
    row = _settle_fb(db, uid, key)
    db.close()
    assert row is not None and row["status"] == "synced", row


def test_retry_single_without_source_rows_returns_reason(client, monkeypatch):
    """源数据不存在时返回 400 + 可读原因，而不是 500「No item with that key」。"""
    headers, uid = _create_user(client, "_fb_retry_nosrc")

    calls = []
    _patch_upsert(monkeypatch, calls)

    resp = client.post("/api/fb/reports/retry-sync", headers=headers,
                       json={"groups": [["产品乙", "线C", "2026-10-02"]]})
    assert resp.status_code == 400
    assert "找不到对应的原始数据" in resp.get_json()["error"]
    assert calls == []


def test_retry_single_legacy_row_without_date_returns_reason(client, monkeypatch):
    """缺少日期就无法定位 ⇒ 明确告知，不静默（守住「缺日期必须给可操作原因」）。"""
    headers, uid = _create_user(client, "_fb_retry_legacy")

    calls = []
    _patch_upsert(monkeypatch, calls)

    resp = client.post("/api/fb/reports/retry-sync", headers=headers,
                       json={"groups": [["产品丙", "线D", ""]]})
    assert resp.status_code == 400
    assert "缺少日期" in resp.get_json()["error"]
    assert calls == []


def test_retry_batch_reports_unrebuildable_rows(client, monkeypatch):
    """批量重试：无法重建的行必须回传原因（`failed[]` 带 error）。

    修复前这里是裸 `except Exception:`，既不记 error_msg 也不回报，用户只看到
    `retried: 0`。
    """
    headers, uid = _create_user(client, "_fb_retry_batch")
    db = database.get_db()
    # 一条能重建的
    _mk_ad_report(db, uid, "产品丁", "线E", "2026-10-03", "acc_ok")
    db.close()

    calls = []
    _patch_upsert(monkeypatch, calls)

    # 一条能重建的 + 一条缺日期的（无法重建）
    resp = client.post("/api/fb/reports/retry-sync", headers=headers,
                       json={"groups": [["产品丁", "线E", "2026-10-03"],
                                        ["产品戊", "线F", ""]]})
    assert resp.status_code == 200, resp.get_json()
    body = resp.get_json()

    assert body["accepted"] == 1, body
    # 失败的那条必须出现在 failed 里，且带可操作原因
    assert [f["product_name"] for f in body["failed"]] == ["产品戊"], body
    assert "缺少日期" in body["failed"][0]["error"], body

    _wait_calls(calls, 1)
    assert len(calls) == 1 and calls[0]["product_name"] == "产品丁", calls

    # 旧版的等价判据：「失败的行留在表里、能重建的行被处理」。
    # 四期改为：**部分失败时那条失败的三元组必须零登记**，可重建的那组才登记。
    db = database.get_db()
    n_bad = db.execute(
        "SELECT COUNT(*) FROM sheet_write_log WHERE user_id=? AND target='fb_report' "
        "AND business_key LIKE '产品戊%'", (uid,)).fetchone()[0]
    ok_row = _fb_row(db, uid, _fbt.fb_report_key("产品丁", "线E", "2026-10-03"))
    db.close()
    assert n_bad == 0, f"重建失败的组不得登记，实际 {n_bad} 行"
    assert ok_row is not None, "可重建的那组必须登记"


def test_sheets_sync_log_has_retry_columns(client):
    """迁移必须给 sheets_sync_log 补上 report_date / line_name（重试靠它们定位）。"""
    db = database.get_db()
    cols = {r[1] for r in db.execute("PRAGMA table_info(sheets_sync_log)").fetchall()}
    db.close()
    assert "report_date" in cols
    assert "line_name" in cols
