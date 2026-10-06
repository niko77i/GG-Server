"""写表失败统一治理 —— 基建测试。

设计见 docs/superpowers/specs/2026-10-06-sheet-write-failure-governance-design.md
"""
import pytest

import database

# 真 sleep，供「轮询后台线程」的循环使用。
# 本文件多处测试要 monkeypatch 掉**全局** time.sleep 来跳过后台重试的 30s ——
# 那会连测试自己的轮询 sleep 一起打成空转：主线程不再让出 GIL，daemon 线程跑不
# 完回调，断言在后台线程落任何状态之前就先跑了（实测确定性失败/留下脏线程）。
# 轮询一律用这个绑定，它在 import 时就抓住了原函数，不受 monkeypatch 影响。
from time import sleep as _poll_sleep  # noqa: E402


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


def _mk_log(db, uid, target, key, status="pending", payload=None, snapshot=None):
    import json
    db.execute(
        "INSERT INTO sheet_write_log (user_id, platform, target, business_key, status, "
        "payload_json, snapshot_json) VALUES (?,?,?,?,?,?,?)",
        (uid, "tt", target, key, status,
         json.dumps(payload or {}), json.dumps(snapshot or {})))
    db.commit()


def _row(db, uid, target, key):
    return db.execute(
        "SELECT * FROM sheet_write_log WHERE user_id=? AND target=? AND business_key=?",
        (uid, target, key)).fetchone()


def test_record_pending_is_upsert(client):
    """同键重登记回 pending 并清空上轮的错误与定案时刻。"""
    import sheet_write
    db = database.get_db()
    _mk_log(db, 1, "tt_recycle", "acc_1", status="retry_failed", snapshot={"a": 1})
    sheet_write.record_pending(db, user_id=1, platform="tt", target="tt_recycle",
                               business_key="acc_1", payload={"reason": "封禁"},
                               snapshot={"b": 2})
    r = _row(db, 1, "tt_recycle", "acc_1")
    db.close()
    assert r["status"] == "pending"
    assert r["error_msg"] == ""
    assert r["settled_at"] is None
    assert '"b"' in r["snapshot_json"]


def test_settle_sets_settled_at_only_for_terminal(client):
    """settled_at 只在终态落定，中间态不得置上（前端靠它判「已定案」）。"""
    import sheet_write
    db = database.get_db()
    _mk_log(db, 1, "tt_recycle", "acc_2")
    sheet_write.settle(db, user_id=1, target="tt_recycle", business_key="acc_2",
                       status="failed", error_msg="超时")
    assert _row(db, 1, "tt_recycle", "acc_2")["settled_at"] is None
    sheet_write.settle(db, user_id=1, target="tt_recycle", business_key="acc_2",
                       status="retry_failed", error_msg="超时")
    r = _row(db, 1, "tt_recycle", "acc_2")
    db.close()
    assert r["settled_at"] is not None
    assert r["status"] == "retry_failed"


def test_run_write_marks_synced_on_success(client, monkeypatch):
    """写表成功 => synced，且不触发回滚。"""
    import sheet_write
    rolled = []
    sheet_write.register_target("_t_ok",
                                rebuild=lambda uid, key, payload: (lambda: None),
                                rollback=lambda db, snap: rolled.append(1) or True)
    db = database.get_db()
    sheet_write.run_write(db, user_id=1, platform="tt", target="_t_ok",
                          business_key="k1", sync_fn=lambda: None)
    import time
    for _ in range(100):
        if _row(db, 1, "_t_ok", "k1")["status"] == "synced":
            break
        time.sleep(0.02)
    r = _row(db, 1, "_t_ok", "k1")
    db.close()
    assert r["status"] == "synced"
    assert rolled == []


def test_run_write_marks_failed_during_retry_window(client, monkeypatch):
    """首次失败落中间态 failed（**此时不得提示**），随后才落终态。

    这是「等最终结果才提示」的守卫：前端只在 status ∈ ATTENTION 时提示，
    而 failed 不在其中。
    """
    import sheet_write
    import time as _time
    monkeypatch.setattr(_time, "sleep", lambda _s: None)

    seq = []
    real_settle = sheet_write.settle

    def _spy(db, *, user_id, target, business_key, status, error_msg=""):
        seq.append(status)
        return real_settle(db, user_id=user_id, target=target,
                           business_key=business_key, status=status, error_msg=error_msg)

    monkeypatch.setattr(sheet_write, "settle", _spy)
    sheet_write.register_target("_t_mid", rebuild=lambda uid, key, payload: (lambda: None))

    def _boom():
        raise RuntimeError("挂了")

    db = database.get_db()
    sheet_write.run_write(db, user_id=1, platform="tt", target="_t_mid",
                          business_key="k9", sync_fn=_boom)
    for _ in range(200):
        if "retry_failed" in seq:
            break
        _poll_sleep(0.01)

    sheet_write.settle = real_settle
    assert seq == ["failed", "retry_failed"]
    assert sheet_write.ATTENTION == ("retry_failed", "rolled_back", "rollback_abandoned")
    assert "failed" not in sheet_write.ATTENTION
    db.close()


def test_run_write_rolls_back_on_final_failure(client, monkeypatch):
    """最终失败 => 调回滚器，且落 rolled_back。"""
    import sheet_write
    monkeypatch.setattr("time.sleep", lambda _s: None)
    calls = []
    sheet_write.register_target(
        "_t_rb",
        rebuild=lambda uid, key, payload: (lambda: None),
        rollback=lambda db, snap: calls.append(snap) or True)

    def _boom():
        raise RuntimeError("Sheets 挂了")

    db = database.get_db()
    sheet_write.run_write(db, user_id=1, platform="tt", target="_t_rb",
                          business_key="k2", sync_fn=_boom, snapshot={"x": 9})
    import time
    for _ in range(150):
        if _row(db, 1, "_t_rb", "k2")["status"] == "rolled_back":
            break
        _poll_sleep(0.02)
    r = _row(db, 1, "_t_rb", "k2")
    db.close()
    assert r["status"] == "rolled_back"
    assert calls == [{"x": 9}]
    assert "Sheets 挂了" in r["error_msg"]


def test_run_write_abandons_rollback_when_guard_fails(client, monkeypatch):
    """回滚器返回 False（守卫未过）=> rollback_abandoned，不得落 rolled_back。"""
    import sheet_write
    monkeypatch.setattr("time.sleep", lambda _s: None)
    sheet_write.register_target("_t_ab",
                                rebuild=lambda uid, key, payload: (lambda: None),
                                rollback=lambda db, snap: False)

    def _boom():
        raise RuntimeError("Sheets 挂了")

    db = database.get_db()
    sheet_write.run_write(db, user_id=1, platform="tt", target="_t_ab",
                          business_key="k3", sync_fn=_boom, snapshot={"x": 1})
    import time
    for _ in range(150):
        if _row(db, 1, "_t_ab", "k3")["status"] == "rollback_abandoned":
            break
        _poll_sleep(0.02)
    r = _row(db, 1, "_t_ab", "k3")
    db.close()
    assert r["status"] == "rollback_abandoned"
    assert "被再次修改" in r["error_msg"]


def test_run_write_no_rollback_for_mirror_target(client, monkeypatch):
    """镜像类（未注册 rollback）最终失败 => retry_failed，且业务数据不动。"""
    import sheet_write
    monkeypatch.setattr("time.sleep", lambda _s: None)
    sheet_write.register_target("_t_mirror",
                                rebuild=lambda uid, key, payload: (lambda: None))

    def _boom():
        raise RuntimeError("挂了")

    db = database.get_db()
    sheet_write.run_write(db, user_id=1, platform="tt", target="_t_mirror",
                          business_key="k4", sync_fn=_boom)
    import time
    for _ in range(150):
        if _row(db, 1, "_t_mirror", "k4")["status"] == "retry_failed":
            break
        _poll_sleep(0.02)
    r = _row(db, 1, "_t_mirror", "k4")
    db.close()
    assert r["status"] == "retry_failed"
    assert r["settled_at"] is not None


def test_build_sync_unknown_target_raises(client):
    import sheet_write
    with pytest.raises(KeyError):
        sheet_write.build_sync("nope", 1, "k", {})
