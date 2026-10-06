"""TT「回收户清单」接入写表失败治理 —— 端到端测试。

守卫：状态改为非存活且带原因时，写表走统一入口、登记 pending、抓快照。
"""
import database
import sheet_write


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
