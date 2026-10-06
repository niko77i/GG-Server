"""TT「回收户清单」接入写表失败治理 —— 端到端测试。

守卫：状态改为非存活且带原因时，写表走统一入口、登记 pending、抓快照。
"""
import database
import sheet_write

# 真 sleep，供「轮询后台线程」的循环使用。
# 本文件多条用例要 monkeypatch 掉**全局** time.sleep 来跳过后台重试的 30s ——
# 那会连测试自己的轮询 sleep 一起打成空转：主线程不再让出 GIL，daemon 线程跑不
# 完回调，断言在后台线程落任何状态之前就先跑了（实测确定性失败/留下脏线程）。
# 故**对 patch 了全局 time.sleep 的用例**，轮询须用这个绑定：它在 import 时就抓
# 住了原函数，不受 monkeypatch 影响；未 patch time.sleep 的用例仍可直接用
# time.sleep 轮询（如 test_snapshot_taken_before_editable_death_date_overwrite）。
from time import sleep as _poll_sleep  # noqa: E402


def _tt_admin(client, username):
    """建一个 TT 平台的 admin（跨用户角色，便于操作他人账户）。"""
    client.post("/api/auth/register", json={"username": username, "password": "test123"})
    db = database.get_db()
    db.execute("UPDATE users SET platform='tt', role='admin' WHERE username=?", (username,))
    db.commit()
    uid = db.execute("SELECT id FROM users WHERE username=?", (username,)).fetchone()["id"]
    db.close()
    resp = client.post("/api/auth/login", json={"username": username, "password": "test123"})
    return {"Authorization": f"Bearer {resp.get_json().get('access_token', '')}"}, uid


def _mk_account(db, uid, advertiser_id, status_id):
    db.execute(
        "INSERT INTO tt_accounts (advertiser_id, name, owner_id, status_id) VALUES (?,?,?,?)",
        (advertiser_id, advertiser_id, uid, status_id))
    db.commit()
    return db.execute("SELECT id FROM tt_accounts WHERE advertiser_id=?",
                      (advertiser_id,)).fetchone()["id"]


def _status_id(db, name):
    db.execute("INSERT OR IGNORE INTO account_statuses (name, platform) VALUES (?, 'tt')", (name,))
    db.commit()
    return db.execute("SELECT id FROM account_statuses WHERE name=? AND platform='tt'",
                      (name,)).fetchone()["id"]


def _setup_sheet(db):
    """配好 TT 全局表格 ID 与工作表映射，让 _trigger_recycle_if_dead 不提前返回。"""
    db.execute("INSERT OR REPLACE INTO tags (key, value) VALUES ('tt_sheet_id', 'SHEET_X')")
    db.execute("INSERT OR REPLACE INTO tags (key, value) VALUES "
               "('tt_sheet_mappings', '{\"recycle\": \"回收户清单\"}')")
    db.commit()


def test_recycle_write_registers_pending_and_snapshot(client, monkeypatch):
    """改非存活 => 登记一条 tt_recycle 的 pending 并抓下改前快照。"""
    import google_sheets_service as gs
    monkeypatch.setattr(gs, "build_service", lambda _p: object())
    monkeypatch.setattr(gs, "append_recycle", lambda *a, **k: {"appended": 1})

    h, uid = _tt_admin(client, "_rc_ok")
    db = database.get_db()
    _setup_sheet(db)
    alive = _status_id(db, "存活")
    dead = _status_id(db, "封禁")
    aid = _mk_account(db, uid, "adv_1", alive)
    db.close()

    resp = client.put(f"/api/tt/accounts/{aid}", headers=h,
                      json={"status_id": dead, "recycle_reason": "封禁回收"})
    assert resp.status_code == 200, resp.get_json()

    import time
    db = database.get_db()
    for _ in range(100):
        r = db.execute("SELECT * FROM sheet_write_log WHERE user_id=? AND target='tt_recycle' "
                       "AND business_key='adv_1'", (uid,)).fetchone()
        if r is not None and r["status"] == "synced":
            break
        time.sleep(0.02)
    r = db.execute("SELECT * FROM sheet_write_log WHERE user_id=? AND target='tt_recycle' "
                   "AND business_key='adv_1'", (uid,)).fetchone()
    db.close()

    assert r is not None, "必须登记一条写表任务"
    assert r["status"] == "synced"
    import json
    snap = json.loads(r["snapshot_json"])
    assert snap["account_pk"] == aid
    assert snap["prev_status_id"] == alive
    assert snap["new_status_id"] == dead
    payload = json.loads(r["payload_json"])
    assert payload["reason"] == "封禁回收"


def test_no_write_when_status_is_alive(client, monkeypatch):
    """改回「存活」不写表、不登记。"""
    import google_sheets_service as gs
    called = []
    monkeypatch.setattr(gs, "build_service", lambda _p: object())
    monkeypatch.setattr(gs, "append_recycle", lambda *a, **k: called.append(1))

    h, uid = _tt_admin(client, "_rc_alive")
    db = database.get_db()
    _setup_sheet(db)
    alive = _status_id(db, "存活")
    dead = _status_id(db, "死亡")
    aid = _mk_account(db, uid, "adv_2", dead)
    db.close()

    resp = client.put(f"/api/tt/accounts/{aid}", headers=h,
                      json={"status_id": alive, "recycle_reason": "随便"})
    assert resp.status_code == 200

    import time
    time.sleep(0.2)
    db = database.get_db()
    n = db.execute("SELECT COUNT(*) FROM sheet_write_log WHERE user_id=? AND target='tt_recycle'",
                   (uid,)).fetchone()[0]
    db.close()
    assert n == 0
    assert called == []


def test_no_write_without_reason(client, monkeypatch):
    """非存活但没带原因 => 不写表（与改动前口径一致）。"""
    import google_sheets_service as gs
    called = []
    monkeypatch.setattr(gs, "build_service", lambda _p: object())
    monkeypatch.setattr(gs, "append_recycle", lambda *a, **k: called.append(1))

    h, uid = _tt_admin(client, "_rc_noreason")
    db = database.get_db()
    _setup_sheet(db)
    alive = _status_id(db, "存活")
    dead = _status_id(db, "封禁")
    aid = _mk_account(db, uid, "adv_3", alive)
    db.close()

    assert client.put(f"/api/tt/accounts/{aid}", headers=h,
                      json={"status_id": dead}).status_code == 200
    import time
    time.sleep(0.2)
    db = database.get_db()
    n = db.execute("SELECT COUNT(*) FROM sheet_write_log WHERE user_id=? AND target='tt_recycle'",
                   (uid,)).fetchone()[0]
    db.close()
    assert n == 0
    assert called == []


def test_snapshot_taken_before_editable_death_date_overwrite(client, monkeypatch):
    """快照必须在 editable 循环改写 death_date **之前**抓。

    单条路径的 SELECT a.* 已含 death_date；但 :308-313 的 editable 列表也含
    death_date 且先执行。若把快照挪到状态块里抓，prev_death_date 会是被本次
    请求改写过的值，回滚就还原成错的。
    """
    import google_sheets_service as gs
    monkeypatch.setattr(gs, "build_service", lambda _p: object())
    monkeypatch.setattr(gs, "append_recycle", lambda *a, **k: {"appended": 1})

    h, uid = _tt_admin(client, "_rc_snap")
    db = database.get_db()
    _setup_sheet(db)
    alive = _status_id(db, "存活")
    dead = _status_id(db, "封禁")
    db.execute("INSERT INTO tt_accounts (advertiser_id, name, owner_id, status_id, death_date) "
               "VALUES ('adv_4','adv_4',?,?,'2020-01-01')", (uid, alive))
    db.commit()
    aid = db.execute("SELECT id FROM tt_accounts WHERE advertiser_id='adv_4'").fetchone()["id"]
    db.close()

    # 同一次请求里既改 death_date 又改状态
    assert client.put(f"/api/tt/accounts/{aid}", headers=h,
                      json={"death_date": "2026-10-06", "status_id": dead,
                            "recycle_reason": "封禁回收"}).status_code == 200

    import time, json
    db = database.get_db()
    for _ in range(100):
        r = db.execute("SELECT * FROM sheet_write_log WHERE user_id=? AND business_key='adv_4'",
                       (uid,)).fetchone()
        if r is not None and r["status"] == "synced":
            break
        time.sleep(0.02)
    r = db.execute("SELECT * FROM sheet_write_log WHERE user_id=? AND business_key='adv_4'",
                   (uid,)).fetchone()
    db.close()
    snap = json.loads(r["snapshot_json"])
    assert snap["prev_death_date"] == "2020-01-01", "快照抓成了被改写后的值"


# ==================== 条件回滚的端到端守卫（Task 6） ====================
# 巡逻「写表最终失败后」的三条分支：rolled_back / rollback_abandoned /
# retry_failed（镜像类无回滚）。轮询一律用模块顶部的 _poll_sleep，原因见该处注释。


def test_rollback_restores_status_on_final_failure(client, monkeypatch):
    """写表最终失败且守卫通过 => 状态被改回，落 rolled_back。"""
    import google_sheets_service as gs
    monkeypatch.setattr("time.sleep", lambda _s: None)      # 跳过 30s 重试等待
    monkeypatch.setattr(gs, "build_service", lambda _p: object())

    def _boom(*a, **k):
        raise RuntimeError("Sheets 配额超限")

    monkeypatch.setattr(gs, "append_recycle", _boom)

    h, uid = _tt_admin(client, "_rc_rb_ok")
    db = database.get_db()
    _setup_sheet(db)
    alive = _status_id(db, "存活")
    dead = _status_id(db, "封禁")
    aid = _mk_account(db, uid, "adv_rb1", alive)
    db.close()

    assert client.put(f"/api/tt/accounts/{aid}", headers=h,
                      json={"status_id": dead, "recycle_reason": "封禁回收"}
                      ).status_code == 200

    db = database.get_db()
    for _ in range(200):
        r = db.execute("SELECT * FROM sheet_write_log WHERE user_id=? AND business_key='adv_rb1'",
                       (uid,)).fetchone()
        if r is not None and r["status"] in ("rolled_back", "rollback_abandoned"):
            break
        _poll_sleep(0.02)
    r = db.execute("SELECT * FROM sheet_write_log WHERE user_id=? AND business_key='adv_rb1'",
                   (uid,)).fetchone()
    cur_status = db.execute("SELECT status_id FROM tt_accounts WHERE id=?", (aid,)).fetchone()["status_id"]
    db.close()

    assert r["status"] == "rolled_back", r["error_msg"]
    assert cur_status == alive, "状态应被改回改之前的值"
    assert "Sheets 配额超限" in r["error_msg"]


def test_rollback_abandoned_when_status_changed_again(client, monkeypatch):
    """写表期间用户又改了状态 => 守卫未过 => 不回滚，落 rollback_abandoned。

    这条比回滚本身更重要：拿 30 秒前的快照覆盖用户的后续操作就是伪造数据。

    本用例与任务初稿有**两处刻意差异**（详见 task-6-report.md「测试 2 重写」）：

    1) 初稿靠 `time.sleep(0.05)` 抢在后台线程进入 30s 重试 sleep **之前**打补丁。
       那是 50ms 竞态：后台线程若先走到 `_time.sleep(30)`，这次 sleep 已在途，
       补丁改不动它 —— 重试要 30 秒后才落终态，而轮询窗口只有 6 秒，断言在
       中间态 `failed` 上炸掉（实测 10 次跑 2 次失败）。这里把「重试等待」本身
       做成阻塞 stub，等主线程把第二次改状态做完再放行，时序**确定**。
    2) 初稿的第二次改状态**带了回收原因**，于是它又登记一条写表任务；而它与本
       用例共用同一条 (user, target, business_key) 记录，会把快照覆盖成「以当前
       状态为准」的那份 —— 那份快照与账户现值必然相符，守卫**必然通过**，永远
       走不到 rollback_abandoned（初稿实际断言的就是这条 rolled_back 路径，
       名不副实，且废掉守卫也照样通过）。不带原因的改状态（既有口径：无原因
       不写表）才是能让陈旧快照真正失效的并发修改。
    """
    import threading
    import google_sheets_service as gs
    monkeypatch.setattr(gs, "build_service", lambda _p: object())

    h, uid = _tt_admin(client, "_rc_rb_ab")
    db = database.get_db()
    _setup_sheet(db)
    alive = _status_id(db, "存活")
    dead = _status_id(db, "封禁")
    other = _status_id(db, "端口回收")
    aid = _mk_account(db, uid, "adv_rb2", alive)
    db.close()

    def _blocked(*a, **k):
        raise RuntimeError("Sheets 挂了")
    monkeypatch.setattr(gs, "append_recycle", _blocked)

    # 后台线程的「30s 重试等待」：阻塞到主线程完成第二次改状态再放行。
    # 10s 上限只是兜底 —— 正常路径下主线程几十毫秒内就 set 了。
    second_change_done = threading.Event()

    def _wait_then_retry(_s):
        second_change_done.wait(10)

    monkeypatch.setattr("time.sleep", _wait_then_retry)

    assert client.put(f"/api/tt/accounts/{aid}", headers=h,
                      json={"status_id": dead, "recycle_reason": "封禁回收"}
                      ).status_code == 200

    # 写表还在重试窗口里，用户又把它改成了第三个状态。
    # 未带原因 => 不再登记写表任务，故上一条任务的快照仍是「改前」的那份。
    assert client.put(f"/api/tt/accounts/{aid}", headers=h,
                      json={"status_id": other}).status_code == 200
    second_change_done.set()

    db = database.get_db()
    for _ in range(300):
        r = db.execute("SELECT * FROM sheet_write_log WHERE user_id=? AND business_key='adv_rb2'",
                       (uid,)).fetchone()
        if r is not None and r["status"] in ("rolled_back", "rollback_abandoned"):
            break
        _poll_sleep(0.02)
    r = db.execute("SELECT * FROM sheet_write_log WHERE user_id=? AND business_key='adv_rb2'",
                   (uid,)).fetchone()
    cur_status = db.execute("SELECT status_id FROM tt_accounts WHERE id=?", (aid,)).fetchone()["status_id"]
    db.close()

    # 快照里的 new_status_id=dead 已不是账户现值（用户改成了 other），
    # 守卫未过 => 放弃回滚，账户保持用户改后的 other
    assert r["status"] == "rollback_abandoned", r["error_msg"]
    assert cur_status == other, "不得用陈旧快照覆盖用户的后续修改"


def test_mirror_target_never_rolls_back(client, monkeypatch):
    """镜像类目标最终失败后，业务数据一字不动（此处以 tt_accounts 为对象验证）。"""
    monkeypatch.setattr("time.sleep", lambda _s: None)
    sheet_write.register_target("_t_mirror_biz",
                                rebuild=lambda uid, key, payload: (lambda: None))

    h, uid = _tt_admin(client, "_rc_mirror")
    db = database.get_db()
    alive = _status_id(db, "存活")
    dead = _status_id(db, "封禁")
    aid = _mk_account(db, uid, "adv_m1", alive)

    def _boom():
        raise RuntimeError("挂了")

    sheet_write.run_write(db, user_id=uid, platform="tt", target="_t_mirror_biz",
                          business_key="adv_m1", sync_fn=_boom)
    db.execute("UPDATE tt_accounts SET status_id=? WHERE id=?", (dead, aid))
    db.commit()

    for _ in range(150):
        r = db.execute("SELECT * FROM sheet_write_log WHERE user_id=? AND target='_t_mirror_biz'",
                       (uid,)).fetchone()
        if r is not None and r["status"] == "retry_failed":
            break
        _poll_sleep(0.02)
    r = db.execute("SELECT * FROM sheet_write_log WHERE user_id=? AND target='_t_mirror_biz'",
                   (uid,)).fetchone()
    cur = db.execute("SELECT status_id FROM tt_accounts WHERE id=?", (aid,)).fetchone()["status_id"]
    db.close()
    # 终态必须是 retry_failed（未注册 rollback 的目标口径），而非 rolled_back /
    # rollback_abandoned —— 否则「镜像目标压根没定案（停在 pending）」或
    # 「_apply_final 把它路由成可回滚」时本用例会假绿。
    assert r is not None and r["status"] == "retry_failed", \
        f"镜像类目标应落 retry_failed，实际 {r['status'] if r else None}"
    assert cur == dead, "镜像类不得回滚业务数据"


def test_batch_path_captures_snapshot_and_rolls_back(client, monkeypatch):
    """批量改状态：快照必须抓到「改前」值，最终失败时逐个条件回滚。

    补这条的由来（Task 5 审查点名）：Task 5 的 4 条用例**全部只走单条 PUT 路径**，
    批量路径 `batch_update_accounts` 零覆盖 —— 它的快照正确性只靠「`r` 是状态块
    UPDATE 之前取的物化 Row」这一语言保证，没有护栏。此用例把该保证变成断言。

    注意批量路径与单条路径的**关键差异**：单条路径必须在 `editable` 循环之前抓快照
    （该循环含 `death_date`）；批量路径的状态块之前没有会改 `death_date` 的分支，
    且它的 SELECT 已补上 `status_changed_date, death_date` 两列 —— 本用例正是在守这一点。
    """
    import google_sheets_service as gs
    monkeypatch.setattr("time.sleep", lambda _s: None)      # 跳过 30s 重试等待
    monkeypatch.setattr(gs, "build_service", lambda _p: object())

    def _boom(*a, **k):
        raise RuntimeError("Sheets 配额超限")

    monkeypatch.setattr(gs, "append_recycle", _boom)

    h, uid = _tt_admin(client, "_rc_batch")
    db = database.get_db()
    _setup_sheet(db)
    alive = _status_id(db, "存活")
    dead = _status_id(db, "封禁")
    # 两个账户各带一个「改前」的 death_date，回滚必须还原到这里
    for aid_key in ("adv_b1", "adv_b2"):
        db.execute(
            "INSERT INTO tt_accounts (advertiser_id, name, owner_id, status_id, death_date) "
            "VALUES (?,?,?,?,'2020-01-01')", (aid_key, aid_key, uid, alive))
    db.commit()
    ids = [r["id"] for r in db.execute(
        "SELECT id FROM tt_accounts WHERE advertiser_id IN ('adv_b1','adv_b2')").fetchall()]
    db.close()

    resp = client.post("/api/tt/accounts/batch-update", headers=h,
                       json={"ids": ids, "field": "status_id", "value": dead,
                             "recycle_reason": "封禁回收"})
    assert resp.status_code == 200, resp.get_json()

    import json
    db = database.get_db()
    for _ in range(300):
        rows = db.execute(
            "SELECT * FROM sheet_write_log WHERE user_id=? AND target='tt_recycle' "
            "AND business_key IN ('adv_b1','adv_b2')", (uid,)).fetchall()
        if len(rows) == 2 and all(r["status"] in ("rolled_back", "rollback_abandoned")
                                  for r in rows):
            break
        _poll_sleep(0.02)

    logs = db.execute(
        "SELECT * FROM sheet_write_log WHERE user_id=? AND target='tt_recycle' "
        "AND business_key IN ('adv_b1','adv_b2')", (uid,)).fetchall()
    after = {r["advertiser_id"]: (r["status_id"], r["death_date"]) for r in db.execute(
        "SELECT advertiser_id, status_id, death_date FROM tt_accounts "
        "WHERE advertiser_id IN ('adv_b1','adv_b2')").fetchall()}
    db.close()

    assert len(logs) == 2, f"批量路径必须为每个账户各登记一条，实际 {len(logs)}"
    snaps = {json.loads(r["snapshot_json"])["account_pk"]: json.loads(r["snapshot_json"])
             for r in logs}
    for aid_key, snap in snaps.items():
        # 快照抓的必须是「改前」值 —— 若批量 SELECT 漏了这两列，这里会是 None
        assert snap["prev_status_id"] == alive, f"{aid_key} 的 prev_status_id 抓错了"
        assert snap["prev_death_date"] == "2020-01-01", f"{aid_key} 的 prev_death_date 抓错了"
        assert snap["new_status_id"] == dead
    for aid_key, (st, dd) in after.items():
        assert st == alive, f"{aid_key} 应被条件回滚回存活"
        assert dd == "2020-01-01", f"{aid_key} 的 death_date 应被回滚还原"
