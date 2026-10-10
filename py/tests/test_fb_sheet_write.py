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


# ---------- 四期 Task 3：写点 ①（提取保存）改走统一入口 ----------

def test_extract_save_registers_fb_report_and_stops_writing_sync_log(client, monkeypatch):
    """提取保存：登记 fb_report，且**不再**写 sheets_sync_log（四期停写该表）。"""
    import google_sheets_service as gs
    monkeypatch.setattr(gs, "upsert_fb_reports", lambda *a, **k: None)

    hdr, uid = _fb_user(client, "_fbsw_ext")
    resp = client.post("/api/fb/extract/save", headers=hdr, json={
        "product_name": "产品甲", "line_name": "线A", "report_date": "2026-10-01",
        "records": [{"account_name": "名", "account_id": "acc_1", "cost": 1,
                     "impressions": 2, "clicks": 3, "registrations": 4,
                     "purchases": 5, "cost_per_purchase": 6}]})
    assert resp.status_code == 200, resp.get_data(as_text=True)[:300]
    key = resp.get_json()["business_key"]
    assert key == "产品甲|线A|2026-10-01", resp.get_json()

    db = database.get_db()
    r = _settle(db, uid, key)
    n_sync_log = db.execute("SELECT COUNT(*) FROM sheets_sync_log WHERE user_id=?",
                            (uid,)).fetchone()[0]
    db.close()
    assert r is not None, "提取保存必须登记 fb_report"
    assert r["status"] == "synced", f"实际 {r['status']}"
    assert n_sync_log == 0, f"FB 不得再写 sheets_sync_log，实际 {n_sync_log} 行"


# ---------- 回归：写表必须用「本次解析出来的数据」，不得回库读整组 ----------
#
# 缺陷 `cf6c5bb`：`_register_fb_report_write` 删掉了 records 参数，写表改由
# `_rebuild_fb_records` 从 `fb_ad_reports` SELECT 整组 —— 而该表按账户 upsert、
# **只增不删**，同一 (产品,线,日期) 多次导入会累积成并集 ⇒ 本次只解析出 5 行，
# 写表却写了库里的全部行。

def test_extract_save_writes_parsed_records_not_db_union(client, monkeypatch):
    """核心用例：库里已有 18 行（13 行不在本次解析里），写表只能喂本次解析的 5 行。"""
    import google_sheets_service as gs
    written = []
    monkeypatch.setattr(gs, "upsert_fb_reports",
                        lambda db, uid, p, l, d, records: written.append(
                            (p, l, d, sorted(r["account_id"] for r in records))))

    hdr, uid = _fb_user(client, "_fbsw_parsed")
    db = database.get_db()
    # 上一次导入留下的 13 个账户（都不在本次解析结果里）
    for i in range(13):
        _seed_report(db, uid, product="产品甲", line="线A", date="2026-10-01",
                     acc=f"old_{i}")
    db.close()

    parsed = [{"account_name": "名", "account_id": f"new_{i}", "cost": 1,
               "impressions": 2, "clicks": 3, "registrations": 4,
               "purchases": 5, "cost_per_purchase": 6} for i in range(5)]
    resp = client.post("/api/fb/extract/save", headers=hdr, json={
        "product_name": "产品甲", "line_name": "线A", "report_date": "2026-10-01",
        "records": parsed})
    assert resp.status_code == 200, resp.get_data(as_text=True)[:300]
    key = resp.get_json()["business_key"]

    db = database.get_db()
    r = _settle(db, uid, key)
    n_db = db.execute(
        "SELECT COUNT(*) FROM fb_ad_reports WHERE user_id=? AND product_name=? "
        "AND line_name=? AND report_date=?",
        (uid, "产品甲", "线A", "2026-10-01")).fetchone()[0]
    db.close()

    assert r is not None and r["status"] == "synced", r and r["status"]
    assert written == [("产品甲", "线A", "2026-10-01",
                        [f"new_{i}" for i in range(5)])], \
        f"写表必须只用本次解析的 5 行，实际 {written}"
    # 库一行都不能少：13 行旧的 + 5 行新的 = 18
    assert n_db == 18, f"fb_ad_reports 不得删行，实际 {n_db} 行"


def test_retry_after_save_keeps_parsed_records(client, monkeypatch):
    """重试路径：payload 里带了 records ⇒ 重试写的仍是那 5 行，不回库读整组。"""
    import google_sheets_service as gs
    written = []
    monkeypatch.setattr(gs, "upsert_fb_reports",
                        lambda db, uid, p, l, d, records: written.append(
                            sorted(r["account_id"] for r in records)))

    hdr, uid = _fb_user(client, "_fbsw_retry_parsed")
    db = database.get_db()
    for i in range(13):
        _seed_report(db, uid, product="产品甲", line="线A", date="2026-10-01",
                     acc=f"old_{i}")
    db.close()

    parsed = [{"account_name": "名", "account_id": f"new_{i}", "cost": 1,
               "impressions": 2, "clicks": 3, "registrations": 4,
               "purchases": 5, "cost_per_purchase": 6} for i in range(5)]
    resp = client.post("/api/fb/extract/save", headers=hdr, json={
        "product_name": "产品甲", "line_name": "线A", "report_date": "2026-10-01",
        "records": parsed})
    assert resp.status_code == 200, resp.get_data(as_text=True)[:300]
    key = resp.get_json()["business_key"]

    db = database.get_db()
    _settle(db, uid, key)
    db.close()
    assert len(written) == 1, f"首次写入应发生一次，实际 {written}"

    # 走「按既有失败行重试」那条路 —— 三元组与 records 都从该行 payload_json 取
    resp = client.post("/api/fb/reports/retry-sync", headers=hdr,
                       json={"business_keys": [key]})
    assert resp.status_code == 200, resp.get_data(as_text=True)[:300]
    assert resp.get_json()["accepted"] == 1, resp.get_json()

    for _ in range(300):
        if len(written) >= 2:
            break
        _poll_sleep(0.02)
    assert len(written) == 2, f"重试应再写一次，实际 {written}"
    assert written[1] == [f"new_{i}" for i in range(5)], \
        f"重试必须仍写本次解析的 5 行，实际 {written[1]}"


def test_retry_legacy_payload_without_records_falls_back_to_db(client, monkeypatch):
    """回退兼容：历史 payload 没有 records ⇒ 仍回库重建，不得 400。"""
    import google_sheets_service as gs
    written = []
    monkeypatch.setattr(gs, "upsert_fb_reports",
                        lambda db, uid, p, l, d, records: written.append(
                            sorted(r["account_id"] for r in records)))

    hdr, uid = _fb_user(client, "_fbsw_legacy_fb")
    db = database.get_db()
    _seed_report(db, uid, product="产品甲", line="线A", date="2026-10-01", acc="acc_1")
    _seed_report(db, uid, product="产品甲", line="线A", date="2026-10-01", acc="acc_2")
    key = __import__("routes.fb_sheet_targets", fromlist=["x"]).fb_report_key(
        "产品甲", "线A", "2026-10-01")
    # 历史形状：扁平三要素，**没有** records 键
    db.execute(
        "INSERT INTO sheet_write_log (user_id, platform, target, business_key, status, "
        "payload_json) VALUES (?, 'fb', 'fb_report', ?, 'retry_failed', ?)",
        (uid, key, json.dumps({"product_name": "产品甲", "line_name": "线A",
                               "report_date": "2026-10-01"}, ensure_ascii=False)))
    db.commit()
    db.close()

    resp = client.post("/api/fb/reports/retry-sync", headers=hdr,
                       json={"business_keys": [key]})
    assert resp.status_code == 200, resp.get_data(as_text=True)[:300]
    assert resp.get_json()["accepted"] == 1, resp.get_json()
    for _ in range(300):
        if written:
            break
        _poll_sleep(0.02)
    assert written == [["acc_1", "acc_2"]], \
        f"无 records 的历史行必须回库重建，实际 {written}"


def test_payload_triple_and_records_new_groups_dict_shape():
    """新批量形状：groups[business_key] 是 dict（三要素 + records），三元组/records 都能取。"""
    import routes.fb_sheet_targets as tgt
    recs = [{"account_id": "a1"}]
    payload = {"groups": {"k1": {"product_name": "P1", "line_name": "L1",
                                 "report_date": "D1", "records": recs}}}
    assert tgt._payload_triple(payload, "k1") == ("P1", "L1", "D1")
    assert tgt._payload_records(payload, "k1") == recs
    # 旧形状（list）仍要能解析，且 records 取不到 ⇒ None
    old = {"groups": {"k2": ["P2", "L2", "D2"]}}
    assert tgt._payload_triple(old, "k2") == ("P2", "L2", "D2")
    assert tgt._payload_records(old, "k2") is None
    # 扁平新形状（单组 + records）
    flat = {"product_name": "P3", "line_name": "L3", "report_date": "D3", "records": recs}
    assert tgt._payload_records(flat, "任意") == recs
    # 扁平旧形状（无 records）⇒ None
    assert tgt._payload_records({"product_name": "P", "line_name": "L",
                                 "report_date": "D"}, "任意") is None


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
                 {"groups": [[1, "b", "c"]]},
                 {"groups": [["a", "b", 1]]},
                 {"business_keys": "abc"},
                 {"business_keys": [{"k": 1}]}):
        resp = client.post("/api/fb/reports/retry-sync", headers=hdr, json=body)
        assert resp.status_code == 400, \
            f"{body} 应回 400，实际 {resp.status_code}：{resp.get_data(as_text=True)[:200]}"
        assert resp.get_json()["success"] is False, resp.get_json()


# 上游异常原文里必然出现的可识别标记（照 test_security_hardening.E11_LEAK_MARKERS 的口径）
_LEAK_MARKERS = ("sheets.googleapis.com", "HttpError", "Traceback")


def _assert_no_leak(raw):
    s = raw if isinstance(raw, str) else raw.get_data(as_text=True)
    for marker in _LEAK_MARKERS:
        assert marker not in s, f"响应体泄露异常原文 {marker!r}: {s[:300]!r}"


def test_retry_sync_failure_reads_sanitized_error_msg(client, monkeypatch, caplog):
    """重试写表**最终失败**：`error_msg` 落**统一固定文案**，异常原文只进日志、不得回出。

    这条是 FB **重试**路径上的「失败文案脱敏」判据（写点 ① 提取保存那条腿由
    `test_fb_platform.py::TestE11FbSheetsSyncLogSink::test_extract_save_failure_sanitized`
    覆盖）：
    `test_fb_report_final_failure_lands_retry_failed` 只断言 `status`，
    **抓不住**「落了固定文案还是落了异常原文」—— 故此处必须直接对 `error_msg` 断言。
    """
    import logging
    import time as _time
    import google_sheets_service as gs

    # 30s 重试窗口压成 0，让最终失败即时到达（_poll_sleep 是模块顶层抓的真 sleep，不受影响）
    monkeypatch.setattr(_time, "sleep", lambda _s: None)

    def _boom(*_a, **_k):
        raise RuntimeError(
            "写表失败 <HttpError 404> https://sheets.googleapis.com/v4/spreadsheets/SHEET-FB")

    monkeypatch.setattr(gs, "upsert_fb_reports", _boom)

    hdr, uid = _fb_user(client, "_fbsw_leak")
    db = database.get_db()
    _seed_report(db, uid, product="产品甲", line="线A", date="2026-10-01")
    db.close()

    key = __import__("routes.fb_sheet_targets", fromlist=["x"]).fb_report_key(
        "产品甲", "线A", "2026-10-01")

    with caplog.at_level(logging.ERROR, logger="gg-server"):
        resp = client.post("/api/fb/reports/retry-sync", headers=hdr,
                           json={"groups": [["产品甲", "线A", "2026-10-01"]]})
        assert resp.status_code == 200, resp.get_data(as_text=True)[:200]
        assert resp.get_json()["accepted"] == 1, resp.get_json()

        db = database.get_db()
        row = _settle(db, uid, key)
        db.close()
        assert row is not None, "必须登记 fb_report"
        assert row["status"] == "retry_failed", f"实际 {row['status']}"

        st = client.get("/api/sheet-write/status", headers=hdr,
                        query_string={"platform": "fb", "target": "fb_report",
                                      "business_key": key})

    assert st.status_code == 200, st.get_data(as_text=True)[:200]
    item = st.get_json()["item"]
    assert item is not None, st.get_json()
    assert item["status"] == "retry_failed", item
    # 关键：落的是**统一固定文案**，既不是异常原文，也不是 FB 自己的旧文案
    assert item["error_msg"] == sheet_write._WRITE_FAILED_MSG, \
        f"error_msg 应落统一固定文案，实际 {item['error_msg']!r}"
    assert item["error_msg"] != "表格同步失败，详情见服务端日志", \
        "不该再落 FB 自己的旧固定文案（该常量已随四期接入统一治理而删除）"

    _assert_no_leak(st)
    _assert_no_leak(resp)
    assert "sheets.googleapis.com" in caplog.text, "异常原文没进日志"
