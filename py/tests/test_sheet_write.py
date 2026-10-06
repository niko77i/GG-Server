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


def test_run_write_reports_rollback_crash_as_such(client, monkeypatch):
    """回滚器自身抛异常 => rollback_abandoned，且原因必须指向「回滚出错」。

    原来 _apply_final 把「回滚器抛异常」与「守卫未过」归为同一个 else，都写
    「该账户在写表期间被再次修改」；前端又无条件再断言一次。回滚器崩溃时界面在
    断言一件没发生的事 —— 而本功能的需求原话就是「提示需要给出失败的原因」。
    故断言 error_msg 点明回滚过程出错，且**不得**出现「被再次修改」。
    """
    import sheet_write
    monkeypatch.setattr("time.sleep", lambda _s: None)

    def _rb_boom(db, snap):
        raise RuntimeError("回滚器炸了")

    sheet_write.register_target("_t_rb_crash",
                                rebuild=lambda uid, key, payload: (lambda: None),
                                rollback=_rb_boom)

    def _boom():
        raise RuntimeError("Sheets 挂了")

    db = database.get_db()
    sheet_write.run_write(db, user_id=1, platform="tt", target="_t_rb_crash",
                          business_key="k5", sync_fn=_boom, snapshot={"x": 1})
    import time
    for _ in range(150):
        if _row(db, 1, "_t_rb_crash", "k5")["status"] == "rollback_abandoned":
            break
        _poll_sleep(0.02)
    r = _row(db, 1, "_t_rb_crash", "k5")
    db.close()
    assert r["status"] == "rollback_abandoned"
    assert "回滚过程出错" in r["error_msg"]
    assert "回滚器炸了" in r["error_msg"]
    assert "被再次修改" not in r["error_msg"], \
        f"回滚器崩溃却断言账户被再次修改: {r['error_msg']}"


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


def _tt_user(client, username):
    client.post("/api/auth/register", json={"username": username, "password": "test123"})
    db = database.get_db()
    db.execute("UPDATE users SET platform='tt' WHERE username=?", (username,))
    db.commit()
    uid = db.execute("SELECT id FROM users WHERE username=?", (username,)).fetchone()["id"]
    db.close()
    resp = client.post("/api/auth/login", json={"username": username, "password": "test123"})
    return {"Authorization": f"Bearer {resp.get_json().get('access_token', '')}"}, uid


def test_status_returns_only_attention_items(client):
    """不带 business_key => 只回需要提示的终态（synced/pending 不出现在列表标记里）。"""
    h, uid = _tt_user(client, "_sw_list")
    db = database.get_db()
    _mk_log(db, uid, "tt_recycle", "acc_bad", status="retry_failed")
    _mk_log(db, uid, "tt_recycle", "acc_ok", status="synced")
    _mk_log(db, uid, "tt_recycle", "acc_wait", status="pending")
    db.close()

    resp = client.get("/api/sheet-write/status?platform=tt", headers=h)
    assert resp.status_code == 200
    keys = [i["business_key"] for i in resp.get_json()["items"]]
    assert keys == ["acc_bad"]


def test_status_single_returns_latest_for_key(client):
    """带 business_key => 回该项（含中间态），供轮询用。"""
    h, uid = _tt_user(client, "_sw_one")
    db = database.get_db()
    _mk_log(db, uid, "tt_recycle", "acc_x", status="failed", payload={"reason": "封禁"})
    db.close()

    resp = client.get("/api/sheet-write/status?platform=tt&business_key=acc_x", headers=h)
    body = resp.get_json()
    assert body["item"]["status"] == "failed"


def test_status_is_isolated_per_user(client):
    """A 用户查不到 B 用户的记录（约束在 SQL 的 WHERE user_id 里）。"""
    ha, uid_a = _tt_user(client, "_sw_a")
    hb, uid_b = _tt_user(client, "_sw_b")
    db = database.get_db()
    _mk_log(db, uid_a, "tt_recycle", "acc_a", status="retry_failed")
    db.close()

    resp = client.get("/api/sheet-write/status?platform=tt&business_key=acc_a", headers=hb)
    assert resp.get_json()["item"] is None


def test_status_rejects_bad_platform(client):
    h, _ = _tt_user(client, "_sw_badp")
    resp = client.get("/api/sheet-write/status?platform=zz", headers=h)
    assert resp.status_code == 400
    assert "platform" in resp.get_json()["error"]


def test_retry_requires_attention_status(client, monkeypatch):
    """pending / synced 的任务不接受重试。"""
    import sheet_write
    # 闸门现在排在 build_sync **之后**：target 必须先在注册表里查得到，否则会先撞
    # 「未注册」那条 400，就测不到「状态不满足」这条了。作用域限定在本用例内。
    monkeypatch.setitem(sheet_write.TARGETS, "tt_recycle",
                        {"rebuild": lambda uid, key, payload: (lambda: None),
                         "rollback": None})
    h, uid = _tt_user(client, "_sw_retry_pending")
    db = database.get_db()
    _mk_log(db, uid, "tt_recycle", "acc_p", status="pending")
    db.close()
    resp = client.post("/api/sheet-write/retry", headers=h,
                       json={"platform": "tt", "target": "tt_recycle", "business_key": "acc_p"})
    assert resp.status_code == 400
    assert "不需要重试" in resp.get_json()["error"]


def test_retry_unknown_target_returns_400_not_500(client):
    h, uid = _tt_user(client, "_sw_retry_badt")
    db = database.get_db()
    _mk_log(db, uid, "no_such_target", "acc_q", status="retry_failed")
    db.close()
    resp = client.post("/api/sheet-write/retry", headers=h,
                       json={"platform": "tt", "target": "no_such_target", "business_key": "acc_q"})
    assert resp.status_code == 400
    assert "未注册" in resp.get_json()["error"]


def test_retry_unknown_target_does_not_strand_row_at_pending(client):
    """未注册 target 的重试必须在 claim **之前**就失败，不得把行留在 pending。

    上一轮把原子 claim 排在 build_sync 之前：build_sync 抛 KeyError → 400，但行已被
    claim 成 pending 且无人推进 —— pending 不在 ATTENTION 里，列表标记不显示、前端
    轮询静默超时；且重试闸门只放行 ATTENTION，该任务从此**永久不可重试**。

    故只断言 400 不够（旧代码同样回 400），必须把 status 读回来、验证原位不变。
    """
    h, uid = _tt_user(client, "_sw_no_strand")
    db = database.get_db()
    _mk_log(db, uid, "no_such_target", "acc_s", status="retry_failed")
    db.close()

    resp = client.post("/api/sheet-write/retry", headers=h,
                       json={"platform": "tt", "target": "no_such_target",
                             "business_key": "acc_s"})
    assert resp.status_code == 400
    assert "未注册" in resp.get_json()["error"]

    db = database.get_db()
    status = _row(db, uid, "no_such_target", "acc_s")["status"]
    db.close()
    assert status == "retry_failed", f"未注册 target 把行卡在了 {status}（应为 retry_failed）"


def test_retry_success_path(client):
    """终态失败的任务可重试：重新走一次写表，成功则落 synced。"""
    import sheet_write
    ran = []
    sheet_write.register_target("_t_retry",
                                rebuild=lambda uid, key, payload: (lambda: ran.append(key)))
    h, uid = _tt_user(client, "_sw_retry_ok")
    db = database.get_db()
    _mk_log(db, uid, "_t_retry", "acc_r", status="retry_failed", payload={"reason": "x"})
    db.close()

    resp = client.post("/api/sheet-write/retry", headers=h,
                       json={"platform": "tt", "target": "_t_retry", "business_key": "acc_r"})
    assert resp.status_code == 200, resp.get_json()

    import time
    db = database.get_db()
    for _ in range(100):
        if _row(db, uid, "_t_retry", "acc_r")["status"] == "synced":
            break
        time.sleep(0.02)
    r = _row(db, uid, "_t_retry", "acc_r")
    db.close()
    assert ran == ["acc_r"]
    assert r["status"] == "synced"


def test_retry_missing_record_returns_404(client):
    h, uid = _tt_user(client, "_sw_retry_404")
    resp = client.post("/api/sheet-write/retry", headers=h,
                       json={"platform": "tt", "target": "tt_recycle", "business_key": "nope"})
    assert resp.status_code == 404


def test_retry_gate_is_atomic_against_concurrent_submit(client, monkeypatch):
    """闸门必须是原子 claim：两个并发 POST 不得双双通过。

    构造方式（确定性，非时序竞态）：把桩打在 run_write 上 —— 它正是「claim 已过、
    status 已原子置为 pending」之后的那个点，桩里用同一个 client 再发一次完全相同的
    POST，就把生产里两个请求交错的顺序固定下来了。

    修复后外层已把 status 原子置为 pending，嵌套请求读到 pending ⇒ 400；
    旧的 check-then-act 实现里置位发生在 run_write **内部**（record_pending），
    桩点之前外层尚未置位，嵌套请求会再读到 retry_failed 从而放行 ⇒ 200（并再起
    一次后台写，正是重复写行的成因）。故断言 400 能区分修复前后。
    """
    import sheet_write
    sheet_write.register_target("_t_atomic",
                                rebuild=lambda uid, key, payload: (lambda: None))
    h, uid = _tt_user(client, "_sw_atomic")
    db = database.get_db()
    _mk_log(db, uid, "_t_atomic", "acc_c", status="retry_failed")
    db.close()

    nested = {}
    fired = []

    def _fake_run_write(db, **kw):
        if not fired:
            fired.append(True)   # 只嵌套一发，防无限递归
            nested["resp"] = client.post(
                "/api/sheet-write/retry", headers=h,
                json={"platform": "tt", "target": "_t_atomic", "business_key": "acc_c"})
        return None

    monkeypatch.setattr(sheet_write, "run_write", _fake_run_write)
    resp = client.post("/api/sheet-write/retry", headers=h,
                       json={"platform": "tt", "target": "_t_atomic", "business_key": "acc_c"})
    assert resp.status_code == 200, resp.get_json()
    assert nested["resp"].status_code == 400, nested["resp"].get_json()
    assert "不需要重试" in nested["resp"].get_json()["error"]


def _age(db, key, seconds):
    """把某行的 updated_at 拨回 seconds 秒前。"""
    db.execute("UPDATE sheet_write_log "
               "SET updated_at=datetime('now','localtime', ?) "
               "WHERE business_key=?", (f"-{seconds} seconds", key))
    db.commit()


def test_sweep_stale_converges_middle_states(client):
    """超时停在 pending/failed 的行收敛为 retry_failed，新鲜中间态不动。

    这两态没有任何别的收敛路径：进程重启、后台线程启动失败都会让永久停在中间态。
    中间态不在 ATTENTION 里（列表不显示），又过不了只放行 ATTENTION 的重试闸门
    （不可重试）—— 失败记录静默丢失，正是本功能要消灭的形态。
    """
    import sheet_write
    db = database.get_db()
    _mk_log(db, 1, "tt_recycle", "old_p", status="pending")
    _mk_log(db, 1, "tt_recycle", "old_f", status="failed")
    _mk_log(db, 1, "tt_recycle", "fresh_p", status="pending")
    db.execute("UPDATE sheet_write_log SET error_msg='Sheets 挂了' "
               "WHERE business_key='old_f'")
    db.commit()
    stale = sheet_write.STALE_AFTER_SECONDS + 100
    _age(db, "old_p", stale)
    _age(db, "old_f", stale)

    n = sheet_write.sweep_stale(db)
    old_p = _row(db, 1, "tt_recycle", "old_p")
    old_f = _row(db, 1, "tt_recycle", "old_f")
    fresh_p = _row(db, 1, "tt_recycle", "fresh_p")
    db.close()

    assert n == 2, f"应只收敛两条超时中间态，实际 {n}"
    assert old_p["status"] == "retry_failed"
    assert "任务中断" in old_p["error_msg"]
    assert old_p["settled_at"] is not None, "收敛后必须落终态时刻"
    assert old_f["status"] == "retry_failed"
    assert "Sheets 挂了" in old_f["error_msg"] and "任务中断" in old_f["error_msg"], \
        f"原有原因被覆盖而非追加: {old_f['error_msg']}"
    assert fresh_p["status"] == "pending", "未超时的中间态不得被动"


def test_sweep_stale_is_scoped_by_user(client):
    """收敛只作用于给定 user_id —— 不得动别的操作员的行。"""
    import sheet_write
    db = database.get_db()
    _mk_log(db, 1, "tt_recycle", "u1_old", status="pending")
    _mk_log(db, 2, "tt_recycle", "u2_old", status="pending")
    stale = sheet_write.STALE_AFTER_SECONDS + 100
    _age(db, "u1_old", stale)
    _age(db, "u2_old", stale)

    n = sheet_write.sweep_stale(db, user_id=1)
    r1 = _row(db, 1, "tt_recycle", "u1_old")
    r2 = _row(db, 2, "tt_recycle", "u2_old")
    db.close()

    assert n == 1
    assert r1["status"] == "retry_failed"
    assert r2["status"] == "pending"


def test_status_endpoint_sweeps_stale_rows(client, monkeypatch):
    """轮询 status 时惰性收敛超时中间态，使其立刻可见且可重试。

    进程重启 / 后台线程启动失败留下的 pending 行，若不在此刻收敛，就既不在
    ATTENTION 列表里（操作员看不到）又过不了重试闸门（点不动）—— 永久卡住。
    """
    import sheet_write
    monkeypatch.setitem(sheet_write.TARGETS, "tt_recycle",
                        {"rebuild": lambda uid, key, payload: (lambda: None),
                         "rollback": None})
    h, uid = _tt_user(client, "_sw_sweep")
    db = database.get_db()
    _mk_log(db, uid, "tt_recycle", "acc_stuck", status="pending")
    _age(db, "acc_stuck", sheet_write.STALE_AFTER_SECONDS + 100)
    db.close()

    resp = client.get("/api/sheet-write/status?platform=tt", headers=h)
    assert resp.status_code == 200
    keys = [i["business_key"] for i in resp.get_json()["items"]]
    assert "acc_stuck" in keys, f"卡住的行未出现在 ATTENTION 列表: {keys}"

    db = database.get_db()
    r = _row(db, uid, "tt_recycle", "acc_stuck")
    db.close()
    assert r["status"] == "retry_failed"

    # 且该行现在真的可重试（闸门只放行 ATTENTION）
    resp = client.post("/api/sheet-write/retry", headers=h,
                       json={"platform": "tt", "target": "tt_recycle",
                             "business_key": "acc_stuck"})
    assert resp.status_code == 200, resp.get_json()


def test_sweep_stale_skips_inflight_rows(client):
    """在途（线程还活着）的行不得被 sweep 收敛。

    build_service 未设 timeout（google_sheets_service.py 全文零 timeout），黑洞式
    网络故障下在途的 Sheets 调用可以挂过 STALE_AFTER_SECONDS —— 此时线程并没死。
    若把这种行误收敛成 retry_failed，重试闸门会放行 → 起第二个写手 → 同一账户
    写进第二行，正是原子 claim（8917db8）专门要消灭的形态。
    """
    import sheet_write
    db = database.get_db()
    _mk_log(db, 1, "tt_recycle", "live_acc", status="pending")
    _mk_log(db, 1, "tt_recycle", "dead_acc", status="pending")
    stale = sheet_write.STALE_AFTER_SECONDS + 100
    _age(db, "live_acc", stale)
    _age(db, "dead_acc", stale)

    key = (1, "tt_recycle", "live_acc")
    with sheet_write._inflight_lock:
        sheet_write._inflight.add(key)
    try:
        n = sheet_write.sweep_stale(db)
        live = _row(db, 1, "tt_recycle", "live_acc")
        dead = _row(db, 1, "tt_recycle", "dead_acc")
    finally:
        db.close()
        with sheet_write._inflight_lock:
            sheet_write._inflight.discard(key)

    assert n == 1, f"应只收敛非在途的那条，实际 {n}"
    assert live["status"] == "pending", "在途行被误收敛成终态 —— 重试闸门将放行第二个写手"
    assert dead["status"] == "retry_failed", "非在途的行应当照常收敛"


def test_sweep_stale_sweeps_after_inflight_key_cleared(client):
    """在途登记只是**暂时**的保护：key 摘除后同一行应恢复被收敛，不是永久豁免。"""
    import sheet_write
    db = database.get_db()
    _mk_log(db, 1, "tt_recycle", "was_live", status="pending")
    _age(db, "was_live", sheet_write.STALE_AFTER_SECONDS + 100)
    key = (1, "tt_recycle", "was_live")

    with sheet_write._inflight_lock:
        sheet_write._inflight.add(key)
    n1 = sheet_write.sweep_stale(db)
    mid = _row(db, 1, "tt_recycle", "was_live")

    with sheet_write._inflight_lock:
        sheet_write._inflight.discard(key)
    n2 = sheet_write.sweep_stale(db)
    after = _row(db, 1, "tt_recycle", "was_live")
    db.close()

    assert n1 == 0, "在途时不得收敛"
    assert mid["status"] == "pending"
    assert n2 == 1, "摘除 key 后应恢复收敛"
    assert after["status"] == "retry_failed"


def test_final_failure_with_incomplete_snapshot_does_not_claim_re_edit(client, monkeypatch):
    """快照缺 new_status_id => 回滚器抛具名异常，落「回滚过程出错」，
    不得断言「该账户在写表期间被再次修改」—— 它并不知道这个成因。

    原来 _tt_recycle_rollback 在快照不完整时 return False，与「守卫未过（用户又改过
    状态）」同路，会被归到「被再次修改」。当前不可达（两处调用点都建完整 5 键快照），
    但这是最后一处会让本功能断言未知成因的路径。
    """
    import sheet_write
    from routes.tt_accounts_routes import _tt_recycle_rollback
    monkeypatch.setattr("time.sleep", lambda _s: None)
    sheet_write.register_target("_t_badsnap",
                                rebuild=lambda uid, key, payload: (lambda: None),
                                rollback=_tt_recycle_rollback)

    def _boom():
        raise RuntimeError("Sheets 挂了")

    db = database.get_db()
    # 缺 new_status_id 的不完整快照
    sheet_write.run_write(db, user_id=1, platform="tt", target="_t_badsnap",
                          business_key="k_bs", sync_fn=_boom, snapshot={"account_pk": 1})
    import time
    for _ in range(150):
        if _row(db, 1, "_t_badsnap", "k_bs")["status"] == "rollback_abandoned":
            break
        _poll_sleep(0.02)
    r = _row(db, 1, "_t_badsnap", "k_bs")
    db.close()

    assert r["status"] == "rollback_abandoned"
    assert "被再次修改" not in r["error_msg"], \
        f"快照不完整却断言账户被再次修改: {r['error_msg']}"
    assert "回滚过程出错" in r["error_msg"], f"未点明回滚出错: {r['error_msg']}"
