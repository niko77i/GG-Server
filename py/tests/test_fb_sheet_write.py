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


# ---------- 补覆盖轮（协调者裁定：简报 Step 7 的变异不具判别力，补 `_payload_triple`
#            两条分支 + 一条真正走 rebuild 的用例） ----------

def test_payload_triple_flat_branch():
    """扁平分支：单组登记的 payload 是三要素平铺。"""
    import routes.fb_sheet_targets as tgt
    assert tgt._payload_triple(
        {"product_name": "P1", "line_name": "L1", "report_date": "D1"}, "任意键") \
        == ("P1", "L1", "D1")


def test_payload_triple_groups_mapping_branch():
    """映射分支：批量登记只有一个 payload，三元组按 business_key 做成映射。

    这是活路径 —— 通用重试端点 `routes/sheet_write_routes.py` 对批量登记的
    `fb_report` 行正是以 `build_sync(target, uid, business_key, payload)` 触发 rebuild，
    此时 payload 是 `{"groups": {business_key: [产品,线,日期], …}}`。
    """
    import routes.fb_sheet_targets as tgt
    payload = {"groups": {"k1": ["P1", "L1", "D1"], "k2": ["P2", "L2", "D2"]}}
    assert tgt._payload_triple(payload, "k2") == ("P2", "L2", "D2")
    assert tgt._payload_triple(payload, "k1") == ("P1", "L1", "D1")


def test_payload_triple_missing_raises_naming_the_group():
    """两者都没有 ⇒ 抛 RuntimeError，且信息要点明是**哪一组**（批量时 payload 装着 N 组）。"""
    import routes.fb_sheet_targets as tgt
    group = "产品甲|线A|2026-10-01"
    try:
        tgt._payload_triple({}, group)
    except RuntimeError as e:
        assert group in str(e), f"信息应点明是哪一组，实际 {e}"
    else:
        raise AssertionError("payload 里没有该组时必须抛错，不得静默返回")


def test_fb_report_rebuild_writes_the_payload_triple(client, monkeypatch):
    """**真正走 rebuild 的用例**：查 DB / 写表用的三元组必须来自 payload，而非任何写死值。

    钉住简报 Step 7 那处不具判别力的变异：把 `_payload_triple(payload, business_key)`
    换成写死的 `("产品甲", "线A", "2026-10-01")` ⇒ 本用例必红（payload 用的是另一组值）。
    """
    import google_sheets_service as gs
    import routes.fb_sheet_targets as tgt
    written = []
    monkeypatch.setattr(gs, "upsert_fb_reports",
                        lambda db, uid, p, l, d, records: written.append(
                            (p, l, d, sorted(r["account_id"] for r in records))))

    _, uid = _fb_user(client, "_fbsw_rebuild")
    db = database.get_db()
    # payload 那一组（本用例期望被写出的）
    _seed_report(db, uid, product="产品丙", line="线C", date="2031-12-31", acc="acc_payload")
    # 简报写死值对应的那一组：实现若退化成写死值，写出的就是它，断言随即可见
    _seed_report(db, uid, product="产品甲", line="线A", date="2026-10-01", acc="acc_hardcoded")
    db.close()

    key = tgt.fb_report_key("产品丙", "线C", "2031-12-31")
    payload = {"product_name": "产品丙", "line_name": "线C", "report_date": "2031-12-31"}
    sheet_write.build_sync("fb_report", uid, key, payload)()

    assert written == [("产品丙", "线C", "2031-12-31", ["acc_payload"])], \
        f"重建必须用 payload 里的三元组，实际 {written}"


# ---------- 四期 Task 2：重试单条 / 批量改走统一入口 ----------

def test_retry_single_registers_and_rebuild_failure_does_not(client, monkeypatch):
    """重试单条：可重建 ⇒ 登记 fb_report；不可重建 ⇒ 400 + 可操作原因、**零行登记**。"""
    import google_sheets_service as gs
    monkeypatch.setattr(gs, "upsert_fb_reports", lambda *a, **k: None)

    hdr, uid = _fb_user(client, "_fbsw_r1")
    db = database.get_db()
    _seed_report(db, uid, product="产品甲", line="线A", date="2026-10-01")
    db.close()

    body = {"groups": [["产品甲", "线A", "2026-10-01"]]}
    resp = client.post("/api/fb/reports/retry-sync", headers=hdr, json=body)
    assert resp.status_code == 200, resp.get_data(as_text=True)[:200]
    assert resp.get_json()["accepted"] == 1, resp.get_json()

    key = __import__("routes.fb_sheet_targets", fromlist=["x"]).fb_report_key(
        "产品甲", "线A", "2026-10-01")
    db = database.get_db()
    r = _settle(db, uid, key)
    db.close()
    assert r is not None, "重试必须登记 fb_report"
    assert r["status"] == "synced", f"实际 {r['status']}"

    # 不可重建（单组）：400 + 可操作原因，且没有任何行被登记
    resp = client.post("/api/fb/reports/retry-sync", headers=hdr,
                       json={"groups": [["产品乙", "线B", "2099-01-01"]]})
    assert resp.status_code == 400, resp.get_data(as_text=True)[:200]
    assert "找不到对应的原始数据" in resp.get_json()["error"], resp.get_json()
    db = database.get_db()
    n = db.execute("SELECT COUNT(*) FROM sheet_write_log WHERE target='fb_report' "
                   "AND business_key LIKE '产品乙%'").fetchone()[0]
    db.close()
    assert n == 0, f"重建失败不得登记，实际 {n} 行"


def test_retry_by_business_keys_reads_payload(client, monkeypatch):
    """汇总区重试：只回传 business_key 列表，端点从该行 payload_json 取三元组。

    这条挡住「客户端自己拆 `产品|线|日期`」那条路 —— 名字含 `|` 会拆错。
    """
    import google_sheets_service as gs
    written = []
    monkeypatch.setattr(gs, "upsert_fb_reports",
                        lambda db, uid, p, l, d, records: written.append((p, l, d)))

    hdr, uid = _fb_user(client, "_fbsw_bk")
    db = database.get_db()
    _seed_report(db, uid, product="甲|乙", line="L1", date="2026-10-01", acc="a1")
    key = __import__("routes.fb_sheet_targets", fromlist=["x"]).fb_report_key(
        "甲|乙", "L1", "2026-10-01")
    # 直接造一条失败的既有行（不起线程，确定且快）—— 端点要能从它的 payload_json 取三元组
    db.execute(
        "INSERT INTO sheet_write_log (user_id, platform, target, business_key, status, "
        "payload_json) VALUES (?, 'fb', 'fb_report', ?, 'retry_failed', ?)",
        (uid, key, json.dumps({"product_name": "甲|乙", "line_name": "L1",
                               "report_date": "2026-10-01"}, ensure_ascii=False)))
    db.commit()
    db.close()

    resp = client.post("/api/fb/reports/retry-sync", headers=hdr,
                       json={"business_keys": [key]})
    assert resp.status_code == 200, resp.get_data(as_text=True)[:200]
    assert resp.get_json()["accepted"] == 1, resp.get_json()
    for _ in range(300):
        if written:
            break
        _poll_sleep(0.02)
    assert written == [("甲|乙", "L1", "2026-10-01")], \
        f"名字含 `|` 也必须按 payload 取对三元组，实际 {written}"


def test_retry_by_business_keys_reads_mapped_payload(client, monkeypatch):
    """**批量登记**留下的行：payload 是 {business_key: [产品,线,日期]} 映射，也要认。

    自审时抓到的坑：只认扁平 payload ⇒ 批量失败的行永远重试不了。
    """
    import google_sheets_service as gs
    written = []
    monkeypatch.setattr(gs, "upsert_fb_reports",
                        lambda db, uid, p, l, d, records: written.append((p, l, d)))

    hdr, uid = _fb_user(client, "_fbsw_bkmap")
    db = database.get_db()
    _seed_report(db, uid, product="甲", line="L1", date="2026-10-01", acc="a1")
    key = __import__("routes.fb_sheet_targets", fromlist=["x"]).fb_report_key(
        "甲", "L1", "2026-10-01")
    db.execute(
        "INSERT INTO sheet_write_log (user_id, platform, target, business_key, status, "
        "payload_json) VALUES (?, 'fb', 'fb_report', ?, 'retry_failed', ?)",
        (uid, key, json.dumps({"groups": {key: ["甲", "L1", "2026-10-01"]}},
                              ensure_ascii=False)))
    db.commit()
    db.close()

    resp = client.post("/api/fb/reports/retry-sync", headers=hdr,
                       json={"business_keys": [key]})
    assert resp.status_code == 200, resp.get_data(as_text=True)[:200]
    assert resp.get_json()["accepted"] == 1, resp.get_json()
    for _ in range(300):
        if written:
            break
        _poll_sleep(0.02)
    assert written == [("甲", "L1", "2026-10-01")], f"映射形状的 payload 也要认，实际 {written}"


def test_retry_batch_covers_every_group(client, monkeypatch):
    """批量重试必须覆盖**每一组**（单组工厂会漏写，二期踩过）。"""
    import google_sheets_service as gs
    written = []
    monkeypatch.setattr(gs, "upsert_fb_reports",
                        lambda db, uid, p, l, d, records: written.append((p, l, d)))

    hdr, uid = _fb_user(client, "_fbsw_rb")
    db = database.get_db()
    _seed_report(db, uid, product="甲", line="L1", date="2026-10-01", acc="a1")
    _seed_report(db, uid, product="乙", line="L2", date="2026-10-02", acc="a2")
    _seed_report(db, uid, product="丙", line="L3", date="2026-10-03", acc="a3")
    db.close()

    resp = client.post("/api/fb/reports/retry-sync", headers=hdr,
                       json={"groups": [["甲", "L1", "2026-10-01"],
                                        ["乙", "L2", "2026-10-02"],
                                        ["丙", "L3", "2026-10-03"]]})
    assert resp.status_code == 200, resp.get_data(as_text=True)[:200]
    assert resp.get_json()["accepted"] == 3, resp.get_json()

    for _ in range(300):
        if len(written) >= 3:
            break
        _poll_sleep(0.02)
    assert sorted(written) == [("丙", "L3", "2026-10-03"), ("乙", "L2", "2026-10-02"),
                               ("甲", "L1", "2026-10-01")], f"三组都要写，实际 {written}"


def test_retry_malformed_input_returns_400_not_500(client):
    """畸形入参必须 400 —— 请求体是用户可控 JSON，不得在解包/绑定处打成 500。

    无闸门时 `[["a"]]` 会在 `for p, l, d in triples` 抛 ValueError（500）；
    `business_keys` 非列表时 `list("abc")` 会退化成逐字符、非 str 元素会在
    sqlite 绑定点抛 InterfaceError（500）。
    """
    hdr, _ = _fb_user(client, "_fbsw_badgrp")
    for body in ({"groups": [["a"]]},
                 {"groups": [["a", "b", "c", "d"]]},
                 {"groups": "abc"},
                 {"business_keys": "abc"},
                 {"business_keys": [{"k": 1}]}):
        resp = client.post("/api/fb/reports/retry-sync", headers=hdr, json=body)
        assert resp.status_code == 400, \
            f"{body} 应回 400，实际 {resp.status_code}：{resp.get_data(as_text=True)[:200]}"
        assert resp.get_json()["success"] is False, resp.get_json()
