"""GG 平台写表点接入统一治理 —— 端到端测试。

守卫两件事：(1) 每次触发都登记 pending 并抓对 business_key；
(2) 最终失败落 retry_failed（GG 侧全是镜像类，**不得**出现 rolled_back）。

⚠️ 轮询必须用**模块顶层**捕获的真 sleep（下）。测试里 monkeypatch 的是
**全局** `time.sleep`（`_sync_sheets_background` 的 30s 重试也靠它跳过），
而轮询循环自己也调 sleep —— 若在 patch 之后再 `from time import sleep`，
拿到的是被 patch 的桩函数，主线程不让出 GIL、后台守护线程永远跑不到，
断言就会在任务真正落终态之前提前开火。
"""
from time import sleep as _poll_sleep

import database
import sheet_write


def _gg_user(client, username, role="user"):
    client.post("/api/auth/register", json={"username": username, "password": "test123"})
    db = database.get_db()
    db.execute("UPDATE users SET role=?, platform='gg' WHERE username=?", (role, username))
    db.commit()
    uid = db.execute("SELECT id FROM users WHERE username=?", (username,)).fetchone()["id"]
    db.close()
    resp = client.post("/api/auth/login", json={"username": username, "password": "test123"})
    return {"Authorization": f"Bearer {resp.get_json().get('access_token', '')}"}, uid


def _setup_sheets(db):
    """配好全局表格 ID 与充值/看板 sheet 名，让各点位不提前 return。"""
    db.execute("INSERT OR REPLACE INTO tags (key, value) VALUES ('recharge_sheet_id', 'SHEET_X')")
    db.execute("INSERT OR REPLACE INTO tags (key, value) VALUES "
               "('sheet_mappings', '{\"my_dashboard\": \"我的看板\", \"recharge\": \"充值表\"}')")
    db.commit()


def _mk_account(db, uid, account_id, status_id=None):
    db.execute("INSERT INTO accounts (name, account_id, owner_id, status_id) VALUES (?,?,?,?)",
               (account_id, account_id, uid, status_id))
    db.commit()
    return db.execute("SELECT id FROM accounts WHERE account_id=?", (account_id,)).fetchone()["id"]


def _status_id(db, name):
    db.execute("INSERT OR IGNORE INTO account_statuses (name, platform) VALUES (?, 'gg')", (name,))
    db.commit()
    return db.execute("SELECT id FROM account_statuses WHERE name=? AND platform='gg'",
                      (name,)).fetchone()["id"]


def _row(db, uid, target, key):
    return db.execute("SELECT * FROM sheet_write_log WHERE user_id=? AND target=? "
                      "AND business_key=?", (uid, target, key)).fetchone()


def _poll(db, uid, key, tries=300):
    """轮询直到该行落终态（用模块顶层捕获的真 sleep，见文件头注释）。"""
    for _ in range(tries):
        r = _row(db, uid, "gg_my_dashboard", key)
        if r is not None and r["status"] in sheet_write.TERMINAL:
            return r
        _poll_sleep(0.02)
    return _row(db, uid, "gg_my_dashboard", key)


def _wait_until(pred, msg, tries=300):
    """轮询直到 pred() 为真；超时则以 msg 断言失败。

    用模块顶层捕获的真 sleep 让出 GIL，后台守护线程才跑得到（见文件头注释）。
    """
    for _ in range(tries):
        if pred():
            return
        _poll_sleep(0.02)
    raise AssertionError(msg)



def test_status_change_registers_dashboard_write(client, monkeypatch):
    """改状态 ⇒ 登记 gg_my_dashboard 的一条记录，business_key 是 account_id。"""
    import google_sheets_service as gs
    monkeypatch.setattr(gs, "build_service", lambda _p: object())
    monkeypatch.setattr(gs, "update_cell_by_account_id", lambda *a, **k: None)

    h, uid = _gg_user(client, "_gg_status")
    db = database.get_db()
    _setup_sheets(db)
    alive = _status_id(db, "存活")
    dead = _status_id(db, "死亡")
    aid = _mk_account(db, uid, "gg_adv_1", alive)
    acct_key = db.execute("SELECT account_id FROM accounts WHERE id=?", (aid,)).fetchone()["account_id"]
    db.close()

    resp = client.put(f"/api/accounts/{aid}", headers=h, json={"status_id": dead})
    assert resp.status_code == 200, resp.get_json()

    db = database.get_db()
    r = _poll(db, uid, acct_key)
    db.close()
    assert r is not None, "改状态必须登记一条 gg_my_dashboard"
    assert r["status"] == "synced"
    assert r["status"] not in ("rolled_back", "rollback_abandoned"), "GG 侧不得回滚"


def test_status_change_without_sheets_config_registers_nothing(client, monkeypatch):
    """未配置表格（无 recharge_sheet_id）⇒ 改状态必须**零** sheet_write_log 行。

    这是回归守卫：配置闸门（原实现为 `if sheet_id and dashboard_name:`）必须在
    **登记 pending 之前**短路，未配置实例上写表点须静默 no-op。若闸门失效（例如
    误用「构造闭包永不失败」的 build_sync 当闸门），这里会凭空多出一条日志行 ——
    后台写表随即失败 ⇒ retry_failed + ⚠️ 标记，正是用户可见回归。
    """
    h, uid = _gg_user(client, "_gg_noconfig")
    db = database.get_db()
    # 刻意**不**调 _setup_sheets：tags 里没有 recharge_sheet_id，闸门应关闭
    alive = _status_id(db, "存活")
    dead = _status_id(db, "死亡")
    aid = _mk_account(db, uid, "gg_adv_nc", alive)
    db.close()

    resp = client.put(f"/api/accounts/{aid}", headers=h, json={"status_id": dead})
    assert resp.status_code == 200, resp.get_json()

    db = database.get_db()
    n = db.execute("SELECT COUNT(*) FROM sheet_write_log").fetchone()[0]
    db.close()
    assert n == 0, f"未配置表格时不得登记任何写表任务，实际 {n} 行"


def test_delete_and_restore_register_dashboard_write(client, monkeypatch):
    """删户与恢复**各自**触发一次写表 —— 两入口独立可观测。

    为什么不能只断言「存在一行」：两处 upsert 的是**同一行**
    （UNIQUE(user_id, target, business_key)，business_key 同为 account_id），
    只看到一行分不清是哪个点位写的（弱守卫：删户点位单干也能让此断言通过）。
    故用写表实参区分：删户写 H 列「解绑」，恢复清空 H 列 —— 两者先后各自出现，
    才证明两个点位都真的触发过。轮询各自的可观测副作用，不依赖墙钟先后。
    """
    import google_sheets_service as gs
    writes = []
    monkeypatch.setattr(gs, "build_service", lambda _p: object())
    monkeypatch.setattr(gs, "update_cell_by_account_id",
                        lambda svc, sid, name, aid, val, col_index=5:
                        writes.append((aid, val, col_index)))

    h, uid = _gg_user(client, "_gg_del")
    db = database.get_db()
    _setup_sheets(db)
    aid = _mk_account(db, uid, "gg_adv_2", _status_id(db, "存活"))
    db.close()

    assert client.delete(f"/api/accounts/{aid}", headers=h).status_code == 200
    # 删户点位：H 列写「解绑」（col_index=7）
    _wait_until(lambda: ("gg_adv_2", "解绑", 7) in writes,
                f"删户必须触发写表，实际 {writes}")

    assert client.post(f"/api/accounts/{aid}/restore", headers=h).status_code == 200
    # 恢复点位：H 列清空（col_index=7、值为空串）—— 与删户的「解绑」是不同的可观测值
    _wait_until(lambda: ("gg_adv_2", "", 7) in writes,
                f"恢复必须触发写表（清空 H 列），实际 {writes}")

    db = database.get_db()
    r = _poll(db, uid, "gg_adv_2")
    db.close()
    assert r is not None, "删户/恢复必须登记 gg_my_dashboard"


def test_dashboard_final_failure_lands_retry_failed_not_rolled_back(client, monkeypatch):
    """写表最终失败 ⇒ retry_failed（**不是** rolled_back）—— GG 侧零回滚的守卫。"""
    import google_sheets_service as gs
    import time as _time
    monkeypatch.setattr(_time, "sleep", lambda _s: None)
    monkeypatch.setattr(gs, "build_service", lambda _p: object())

    def _boom(*a, **k):
        raise RuntimeError("Sheets 配额超限")

    monkeypatch.setattr(gs, "update_cell_by_account_id", _boom)

    h, uid = _gg_user(client, "_gg_fail")
    db = database.get_db()
    _setup_sheets(db)
    alive = _status_id(db, "存活")
    dead = _status_id(db, "死亡")
    aid = _mk_account(db, uid, "gg_adv_3", alive)
    db.close()

    assert client.put(f"/api/accounts/{aid}", headers=h,
                      json={"status_id": dead}).status_code == 200

    db = database.get_db()
    r = _poll(db, uid, "gg_adv_3")
    cur = db.execute("SELECT status_id FROM accounts WHERE id=?", (aid,)).fetchone()["status_id"]
    db.close()

    assert r is not None, "改状态必须登记一条 gg_my_dashboard"
    assert r["status"] == "retry_failed", f"应落 retry_failed，实际 {r['status']}"
    assert "Sheets 配额超限" in r["error_msg"]
    assert cur == dead, "GG 侧是镜像类，**不得**回滚业务数据"


def test_batch_status_change_writes_every_account(client, monkeypatch):
    """批量改状态：N 行日志 **且每一户都被写表**。

    守卫的点：`run_write_many` 只执行 sync_fn **一次**（一个后台线程，Task 1 已用
    「sync_fn 只应执行一次」钉住）。故首跑的 sync_fn 必须覆盖全部 N 户 —— 若照
    单户工厂 `build_sync(..., business_keys[0], ...)` 构造，则只有第一户被写进表，
    而 N 行日志全落 synced（静默漏写，比原实现更糟：原来是一个线程串行写 N 户）。
    """
    import google_sheets_service as gs
    writes = []
    monkeypatch.setattr(gs, "build_service", lambda _p: object())
    monkeypatch.setattr(gs, "update_cell_by_account_id",
                        lambda svc, sid, name, aid, val, col_index=5:
                        writes.append((aid, val, col_index)))

    h, uid = _gg_user(client, "_gg_batch")
    db = database.get_db()
    _setup_sheets(db)
    alive = _status_id(db, "存活")
    dead = _status_id(db, "死亡")
    a1 = _mk_account(db, uid, "gg_adv_5", alive)
    a2 = _mk_account(db, uid, "gg_adv_6", alive)
    db.close()

    resp = client.post("/api/accounts/batch-update", headers=h,
                       json={"ids": [a1, a2], "field": "status_id", "value": dead})
    assert resp.status_code == 200, resp.get_json()

    db = database.get_db()
    r1 = _poll(db, uid, "gg_adv_5")
    r2 = _poll(db, uid, "gg_adv_6")
    db.close()

    assert r1 is not None and r2 is not None, "批量改状态必须每户各登记一行"
    assert (r1["status"], r2["status"]) == ("synced", "synced")
    written = {a for a, _v, _c in writes}
    assert written == {"gg_adv_5", "gg_adv_6"}, f"两户都必须被写表，实际只写了 {writes}"


def test_dashboard_write_rebuilds_from_accounts(client, monkeypatch):
    """重建从 accounts 重算 F/H —— 删户态写「解绑」，非删户态写空。"""
    import google_sheets_service as gs
    writes = []
    monkeypatch.setattr(gs, "build_service", lambda _p: object())
    monkeypatch.setattr(gs, "update_cell_by_account_id",
                        lambda svc, sid, name, aid, val, col_index=5:
                        writes.append((aid, val, col_index)))

    h, uid = _gg_user(client, "_gg_rebuild")
    db = database.get_db()
    _setup_sheets(db)
    aid = _mk_account(db, uid, "gg_adv_4", _status_id(db, "存活"))
    db.execute("UPDATE accounts SET deleted_at=datetime('now','localtime') WHERE id=?", (aid,))
    db.commit()
    db.close()

    import sheet_write as sw
    sync_fn = sw.build_sync("gg_my_dashboard", uid, "gg_adv_4", {"dash_uid": uid})
    sync_fn()          # 直接执行（不在后台线程里，测试内联跑）

    assert ("gg_adv_4", "解绑", 7) in writes, f"H 列应写「解绑」，实际 {writes}"
