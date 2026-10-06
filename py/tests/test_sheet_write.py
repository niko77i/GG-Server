"""写表失败统一治理 —— 基建测试。

设计见 docs/superpowers/specs/2026-10-06-sheet-write-failure-governance-design.md
"""
import database


def test_sheet_write_log_table_shape(client):
    """表必须存在，且 UNIQUE 约束落在 (user_id, target, business_key)。"""
    db = database.get_db()
    cols = {r[1] for r in db.execute("PRAGMA table_info(sheet_write_log)").fetchall()}
    db.close()
    assert {
        "id", "user_id", "platform", "target", "business_key", "status",
        "error_msg", "payload_json", "snapshot_json", "created_at",
        "updated_at", "settled_at",
    } <= cols


def test_sheet_write_log_unique_key(client):
    """同 (user_id, target, business_key) 只能有一行 —— upsert 语义的前提。"""
    db = database.get_db()
    for _ in range(2):
        try:
            db.execute(
                "INSERT INTO sheet_write_log (user_id, platform, target, business_key, status) "
                "VALUES (1,'tt','tt_recycle','acc_1','pending')")
            db.commit()
            ok = True
        except Exception:
            db.rollback()
            ok = False
    rows = db.execute(
        "SELECT COUNT(*) FROM sheet_write_log WHERE user_id=1 AND target='tt_recycle' "
        "AND business_key='acc_1'").fetchone()[0]
    db.close()
    assert ok is False, "第二次插入应撞 UNIQUE 约束"
    assert rows == 1


def test_background_calls_back_on_first_success(monkeypatch):
    """缺陷 A 守卫：首次写成功也必须回调。

    原实现里首次成功直接跳出 try，on_fail_fn 一次都不调 —— 导致把
    `sheets_synced=1` 写在回调里的充值写表点标志位永远停在 0（前端误报
    「未同步」），以及 GG 做表的 pending 日志行永久残留（前端轮询空转）。
    """
    import main

    calls = []
    main._sync_sheets_background(lambda: None, lambda s, e: calls.append((s, e)))
    # 后台是 daemon 线程，等它跑完
    import time
    for _ in range(100):
        if calls:
            break
        time.sleep(0.02)

    assert calls == [("synced", "")]


def test_background_reports_retry_failed(monkeypatch):
    """重试也失败 => 终态 retry_failed，且错误信息非空。"""
    import main
    import time
    # 先抓一份真 sleep：下面的 monkeypatch 打的是全局 time.sleep，会连本测试自己的
    # 轮询 sleep 一起打成空转 —— 主线程就再也不 yield，daemon 线程拿不到 GIL，
    # 断言在后台线程落任何回调之前就跑了（实测确定性 calls==[]）。
    _real_sleep = time.sleep
    monkeypatch.setattr("time.sleep", lambda _s: None)   # 跳过 30s

    calls = []

    def _boom():
        raise RuntimeError("Sheets 挂了")

    main._sync_sheets_background(_boom, lambda s, e: calls.append((s, e)))
    for _ in range(100):
        if len(calls) >= 2:
            break
        _real_sleep(0.02)

    assert [c[0] for c in calls] == ["failed", "retry_failed"]
    assert "Sheets 挂了" in calls[-1][1]


def test_background_logs_callback_exception(caplog):
    """缺陷 B 守卫：回调自身抛异常必须落 ERROR 日志，不得静默 pass。

    回调是唯一负责落记录的地方 —— 它失败后彻底没痕迹，就没法排查
    「状态为什么没更新」。原来三处都是 `except Exception: pass`。
    """
    import logging
    import time

    import main

    def _bad_cb(status, err):
        raise RuntimeError("回调自己炸了")

    with caplog.at_level(logging.ERROR):
        main._sync_sheets_background(lambda: None, _bad_cb)
        for _ in range(100):
            if caplog.records:
                break
            time.sleep(0.02)

    assert any("结果回调失败" in r.getMessage() for r in caplog.records), \
        f"回调异常没有落日志，现有记录: {[r.getMessage() for r in caplog.records]}"
