"""TT 广告账户路由测试。"""
import os
import sys

_py_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _py_dir not in sys.path:
    sys.path.insert(0, _py_dir)

import database  # noqa: E402


def test_tt_accounts_tables_exist(app):
    db = database.get_db()
    for tbl in ("tt_accounts", "tt_account_bc_history",
                "tt_recharge_records", "tt_recycle_reasons"):
        row = db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (tbl,)
        ).fetchone()
        assert row is not None, f"表 {tbl} 不存在"
    db.close()


def test_agents_has_platform_column(app):
    db = database.get_db()
    cols = [r["name"] for r in db.execute("PRAGMA table_info(agents)").fetchall()]
    assert "platform" in cols
    db.close()


def test_copy_gg_agents_to_tt(app):
    """GG 代理应复制到 platform='tt'（UNIQUE 含 platform 后，同名同 owner 可共存）。"""
    db = database.get_db()
    # 确保外键引用的用户存在（agents.owner_id → users.id；临时库无用户）
    db.execute("INSERT OR IGNORE INTO users(id, username, password, role) VALUES(1, 'dev', 'x', 'developer')")
    db.execute("INSERT OR IGNORE INTO users(id, username, password, role) VALUES(2, 'user2', 'x', 'user')")
    # 清掉迁移标记，插入 GG 代理（owner_id=1，正是重建 UNIQUE 前会被静默跳过的场景），手动调用复制函数
    db.execute("DELETE FROM config WHERE key='migrated_copy_agents_to_tt'")
    db.execute("INSERT OR IGNORE INTO agents(name, owner_id, platform) VALUES(?,?, 'gg')",
               ("卡尔", 1))
    db.commit()
    database._copy_gg_agents_to_tt(db)
    cnt = db.execute(
        "SELECT COUNT(*) FROM agents WHERE name='卡尔' AND platform='tt'"
    ).fetchone()[0]
    assert cnt == 1
    db.close()


def test_agents_unique_includes_platform(app):
    """UNIQUE 应为 (name, owner_id, platform)：GG/TT 同名同 owner 可共存。"""
    db = database.get_db()
    db.execute("INSERT OR IGNORE INTO users(id, username, password, role) VALUES(1, 'dev', 'x', 'developer')")
    db.execute("INSERT INTO agents(name, owner_id, platform) VALUES(?,?, 'gg')", ("共存代理", 1))
    db.execute("INSERT INTO agents(name, owner_id, platform) VALUES(?,?, 'tt')", ("共存代理", 1))
    db.commit()
    cnt = db.execute("SELECT COUNT(*) FROM agents WHERE name='共存代理'").fetchone()[0]
    assert cnt == 2
    db.close()


def test_rebuild_agents_unique_upgrade(app):
    """已有部署升级：旧 UNIQUE(name,owner_id) 表重建后应含 platform 且数据保留。"""
    db = database.get_db()
    db.execute("PRAGMA foreign_keys=OFF")
    db.execute("DROP TABLE agents")
    db.execute("""
        CREATE TABLE agents (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            owner_id INTEGER REFERENCES users(id),
            created_at TEXT DEFAULT (datetime('now','localtime')),
            platform TEXT DEFAULT 'gg',
            UNIQUE(name, owner_id)
        )
    """)
    db.execute("PRAGMA foreign_keys=ON")
    db.execute("INSERT OR IGNORE INTO users(id, username, password, role) VALUES(1, 'dev', 'x', 'developer')")
    db.execute("INSERT INTO agents(name, owner_id, platform) VALUES(?,?, 'gg')", ("旧代理", 1))
    db.commit()
    db.execute("DELETE FROM config WHERE key='migrated_rebuild_agents_unique'")
    db.commit()
    database._rebuild_agents_platform_unique(db)
    sql = db.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='agents'").fetchone()["sql"]
    assert "UNIQUE(name, owner_id, platform)" in sql
    assert db.execute("SELECT COUNT(*) FROM agents WHERE name='旧代理'").fetchone()[0] == 1
    db.execute("INSERT INTO agents(name, owner_id, platform) VALUES(?,?, 'tt')", ("旧代理", 1))
    db.commit()
    assert db.execute("SELECT COUNT(*) FROM agents WHERE name='旧代理'").fetchone()[0] == 2
    db.close()


import unittest.mock as mock  # noqa: E402


def _mk_account(client, headers, advertiser_id="1234567890123", **kw):
    body = {"advertiser_id": advertiser_id, "name": advertiser_id, **kw}
    return client.post("/api/tt/accounts/create", headers=headers, json=body)


def test_account_create_and_list(client, tt_headers):
    resp = _mk_account(client, tt_headers, name="测试户")
    assert resp.status_code == 200
    aid = resp.get_json()["id"]
    assert aid > 0

    resp = client.get("/api/tt/accounts/list", headers=tt_headers)
    data = resp.get_json()
    assert data["total"] == 1
    assert data["items"][0]["advertiser_id"] == "1234567890123"
    assert "status_counts" in data


def test_list_status_filter_alive_includes_null_status(client, tt_headers):
    """筛选「存活」应包含 status_id IS NULL 的户（与统计/显示保持同一并集口径）。

    根因：`status_id` 为 NULL 的户在列表里被渲染成「存活」
    （`it['status'] = it.get('status_name') or '存活'`），统计里也归到
    「存活」这一个 key（`COALESCE(st.name, '存活')`）；但筛选原先只按 id 等值，
    这批 NULL 户恒筛不出来 —— 表现为「按钮上写着 N、点下去 0 条」。
    判别力在「NULL 那条在不在」：把修法改回 `a.status_id = ?` 本用例即变红。
    另加**负对照**（异状态户必须不在）：否则「筛选退化成返回全部」的错误实现也会绿。
    """
    db = database.get_db()
    uid = db.execute("SELECT id FROM users WHERE username='ttuser'").fetchone()["id"]
    # 真「存活」状态行（TT 平台）；不存在则建一条
    row = db.execute(
        "SELECT id FROM account_statuses WHERE name='存活' AND platform='tt'"
    ).fetchone()
    if row is None:
        db.execute("INSERT INTO account_statuses(name, platform) VALUES('存活', 'tt')")
        db.commit()
        alive_id = db.execute(
            "SELECT id FROM account_statuses WHERE name='存活' AND platform='tt'"
        ).fetchone()["id"]
    else:
        alive_id = row["id"]
    # 异状态行（TT 平台「死亡」），用作负对照；不存在则建一条
    row = db.execute(
        "SELECT id FROM account_statuses WHERE name='死亡' AND platform='tt'"
    ).fetchone()
    if row is None:
        db.execute("INSERT INTO account_statuses(name, platform) VALUES('死亡', 'tt')")
        db.commit()
        dead_id = db.execute(
            "SELECT id FROM account_statuses WHERE name='死亡' AND platform='tt'"
        ).fetchone()["id"]
    else:
        dead_id = row["id"]
    # 三条户：一条 status_id=存活，一条 status_id IS NULL（渲染成「存活」），
    # 一条 status_id=死亡（**不应**被存活筛选捞出来）
    db.execute("INSERT INTO tt_accounts(name, advertiser_id, status_id, owner_id) VALUES(?,?,?,?)",
               ("真存活户", "1111111111111", alive_id, uid))
    db.execute("INSERT INTO tt_accounts(name, advertiser_id, status_id, owner_id) VALUES(?,?,?,?)",
               ("空状态户", "2222222222222", None, uid))
    db.execute("INSERT INTO tt_accounts(name, advertiser_id, status_id, owner_id) VALUES(?,?,?,?)",
               ("死亡户", "3333333333333", dead_id, uid))
    db.commit()
    db.close()

    resp = client.get(f"/api/tt/accounts/list?status_id={alive_id}", headers=tt_headers)
    assert resp.status_code == 200
    adv_ids = {it["advertiser_id"] for it in resp.get_json()["items"]}
    assert "1111111111111" in adv_ids, "真「存活」户应返回"
    assert "2222222222222" in adv_ids, "status_id 为 NULL 的户（渲染成「存活」）也应返回"
    assert "3333333333333" not in adv_ids, "异状态（死亡）户不应被存活筛选返回"


def _ensure_tt_status(db, name):
    """取（无则建）platform='tt' 的字典行 id。"""
    row = db.execute(
        "SELECT id FROM account_statuses WHERE name=? AND platform='tt'", (name,)
    ).fetchone()
    if row is None:
        db.execute("INSERT INTO account_statuses(name, platform) VALUES(?, 'tt')", (name,))
        db.commit()
        row = db.execute(
            "SELECT id FROM account_statuses WHERE name=? AND platform='tt'", (name,)
        ).fetchone()
    return row["id"]


def test_list_status_filter_alive_includes_dangling_status(client, tt_headers):
    """**悬挂** status_id（指向已删字典行）也必须出现在「存活」筛选里。

    根因（与上一条同族、本次修的第二条腿）：LEFT JOIN 状态表得 NULL ⇒ 计数/显示
    都把它归入「存活」；但旧筛选 `IS NULL` 为假、`= id` 也为假 ⇒ **任何**状态都
    筛不到它，又是一次「按钮上写着 N、点下去 0 条」。
    判别力在「悬挂那条在不在」：把修法改回 `IS NULL OR IN (按 name 取 id)` 或
    `a.status_id = ?`，本用例即变红。
    另加**负对照**（异状态户必须不在）：否则「退化成返回全部」的错误实现也会绿。
    """
    import sqlite3

    db = database.get_db()
    uid = db.execute("SELECT id FROM users WHERE username='ttuser'").fetchone()["id"]
    alive_id = _ensure_tt_status(db, "存活")
    dead_id = _ensure_tt_status(db, "死亡")

    # 两条能正常解析的户：真「存活」+ 异状态「死亡」（负对照）
    db.execute("INSERT INTO tt_accounts(name, advertiser_id, status_id, owner_id) VALUES(?,?,?,?)",
               ("真存活户", "1111111111111", alive_id, uid))
    db.execute("INSERT INTO tt_accounts(name, advertiser_id, status_id, owner_id) VALUES(?,?,?,?)",
               ("死亡户", "3333333333333", dead_id, uid))
    db.commit()
    db.close()

    # 造**悬挂** status_id。`account_statuses(id)` 是主键、`accounts.status_id` 是外键，
    # 而 get_db() 的连接开着 PRAGMA foreign_keys=ON ⇒ 直接插悬挂值会被拒。
    # 用一条**独立** raw 连接先关 FK 再插（get_db() 那条连接可能已带未提交事务，
    # 事务内的 PRAGMA foreign_keys 是静默 no-op，不可靠）——同
    # test_account_status_platform.py 的既有做法。
    dangling_id = 999000111  # 保证不存在的 id
    raw = sqlite3.connect(database._db_path())
    raw.execute("PRAGMA foreign_keys=OFF")
    raw.execute("INSERT INTO tt_accounts(name, advertiser_id, status_id, owner_id) VALUES(?,?,?,?)",
                ("悬挂状态户", "4444444444444", dangling_id, uid))
    raw.commit()
    raw.close()

    # 前置断言：确认真是悬挂（指向不存在的字典行）
    chk = database.get_db()
    assert chk.execute("SELECT COUNT(*) FROM account_statuses WHERE id=?",
                       (dangling_id,)).fetchone()[0] == 0, "前置条件：该 id 无对应字典行"
    chk.close()

    resp = client.get(f"/api/tt/accounts/list?status_id={alive_id}", headers=tt_headers)
    assert resp.status_code == 200
    body = resp.get_json()
    adv_ids = {it["advertiser_id"] for it in body["items"]}
    assert "4444444444444" in adv_ids, "悬挂 status_id 的户（渲染成「存活」）应被存活筛选返回"
    assert "1111111111111" in adv_ids, "真「存活」户应返回"
    assert "3333333333333" not in adv_ids, "异状态（死亡）户不应被存活筛选返回（负对照）"
    # 计数侧同口径：悬挂户与真存活户一起算进「存活」
    assert body["status_counts"].get("存活") == 2, (
        "悬挂户在计数里归「存活」，筛选结果就必须同口径"
    )


def test_list_status_filter_alive_includes_cross_platform_same_name(client, tt_headers):
    """**跨平台同名引用**：tt_accounts.status_id 指向**他平台**（gg/fb）的「存活」行时，
    按「存活」筛选也必须把它捞出来 —— 计数按 st.name 把它算进「存活」，筛选须同口径。

    根因（与本文件另外两条同族、本次修的**第三条腿**）：旧筛选是
    `a.status_id IN (SELECT id FROM account_statuses WHERE name='存活' AND platform='tt')`
    —— 子查询带 `platform='tt'`，他平台那条同名行的 id 不在集合里 ⇒ 筛不到；而计数/显示
    按 **名字** 判定 ⇒ 又是一次「按钮上写着 N、点下去 0 条」。本提交把子查询的 platform
    条件去掉、按名字判定，自然覆盖跨平台同名引用。

    判别力在「跨平台那条在不在」：把筛选改回 `a.status_id = ?`（等值）或把 platform
    条件加回子查询，本用例即变红。
    另加**负对照**（异状态户必须不在）：否则「筛选退化成返回全部」的错误实现也会绿。
    """
    db = database.get_db()
    uid = db.execute("SELECT id FROM users WHERE username='ttuser'").fetchone()["id"]
    alive_id = _ensure_tt_status(db, "存活")   # 正常的 tt「存活」户
    dead_id = _ensure_tt_status(db, "死亡")     # 负对照（异状态）

    # 他平台的同名「存活」行：先查再插（account_statuses 按 (name, platform) 唯一，
    # 迁移会从 gg 播种各平台同名行 —— 已存在就复用，别撞唯一约束）。
    row = db.execute(
        "SELECT id, platform FROM account_statuses WHERE name='存活' AND platform!='tt'"
    ).fetchone()
    if row is None:
        db.execute("INSERT INTO account_statuses(name, owner_id, platform) VALUES('存活', 1, 'fb')")
        db.commit()
        row = db.execute(
            "SELECT id, platform FROM account_statuses WHERE name='存活' AND platform!='tt'"
        ).fetchone()
    foreign_id = row["id"]
    assert row["platform"] != "tt", "前置条件：引用的行必须来自他平台"

    db.execute("INSERT INTO tt_accounts(name, advertiser_id, status_id, owner_id) VALUES(?,?,?,?)",
               ("同存活户", "5550000001111", alive_id, uid))
    db.execute("INSERT INTO tt_accounts(name, advertiser_id, status_id, owner_id) VALUES(?,?,?,?)",
               ("跨平台存活户", "5550000002222", foreign_id, uid))
    db.execute("INSERT INTO tt_accounts(name, advertiser_id, status_id, owner_id) VALUES(?,?,?,?)",
               ("死亡户", "5550000003333", dead_id, uid))
    db.commit()
    # 前置断言：跨平台那条的 status_id 确实指向**他平台**「存活」行（未被改动）
    chk = db.execute(
        "SELECT s.name AS name, s.platform AS platform FROM tt_accounts a "
        "JOIN account_statuses s ON a.status_id=s.id WHERE a.advertiser_id='5550000002222'"
    ).fetchone()
    assert chk["name"] == "存活" and chk["platform"] != "tt", (
        f"前置条件：跨平台户应指向他平台「存活」行，实际 {dict(chk)}"
    )
    db.close()

    # 客户端传的正是那条**他平台**行的 id
    resp = client.get(f"/api/tt/accounts/list?status_id={foreign_id}", headers=tt_headers)
    assert resp.status_code == 200
    body = resp.get_json()
    adv_ids = {it["advertiser_id"] for it in body["items"]}
    assert "5550000002222" in adv_ids, (
        "他平台同名「存活」行被引用时，按「存活」筛选必须仍能捞到该户"
    )
    assert "5550000001111" in adv_ids, "真「存活」户应返回"
    assert "5550000003333" not in adv_ids, "异状态（死亡）户不应被存活筛选返回（负对照）"
    assert body["total"] == body["status_counts"].get("存活"), (
        "统计里「存活」有几条，按它筛选就该有几条 —— 跨平台那条漏了就是死链"
    )


def test_update_account_clear_agent(client, tt_headers):
    """update_account 应支持 agent_id=null 显式清空代理（对齐 GG）。"""
    resp = _mk_account(client, tt_headers, advertiser_id="1234567890123")
    assert resp.status_code == 200
    aid = resp.get_json()["id"]

    # 设置代理
    resp = client.put(f"/api/tt/accounts/{aid}", headers=tt_headers, json={"agent": "代理A"})
    assert resp.status_code == 200
    resp = client.get("/api/tt/accounts/list", headers=tt_headers)
    assert resp.get_json()["items"][0]["agent_id"] is not None
    assert resp.get_json()["items"][0]["agent"] == "代理A"

    # 显式清空代理
    resp = client.put(f"/api/tt/accounts/{aid}", headers=tt_headers, json={"agent_id": None})
    assert resp.status_code == 200
    resp = client.get("/api/tt/accounts/list", headers=tt_headers)
    assert resp.get_json()["items"][0]["agent_id"] is None
    assert resp.get_json()["items"][0]["agent"] == ""


def test_account_create_rejects_non_digit(client, tt_headers):
    resp = _mk_account(client, tt_headers, advertiser_id="123-456-789")
    assert resp.status_code == 400


def test_account_create_duplicate_conflict(client, tt_headers):
    _mk_account(client, tt_headers, advertiser_id="1234567890123")
    resp = _mk_account(client, tt_headers, advertiser_id="1234567890123")
    assert resp.status_code == 409


def _mk_tt_headers(client, username):
    """注册一个 TT 平台用户并返回其 JWT 请求头。"""
    client.post("/api/auth/register", json={"username": username, "password": "test123"})
    db = database.get_db()
    db.execute("UPDATE users SET platform='tt' WHERE username=?", (username,))
    db.commit()
    db.close()
    resp = client.post("/api/auth/login", json={"username": username, "password": "test123"})
    token = resp.get_json().get("access_token", "")
    return {"Authorization": f"Bearer {token}"}


def test_lookup_omits_sensitive_fields(client, tt_headers):
    resp = _mk_account(client, tt_headers, advertiser_id="1234567890123",
                       remark="内部备注", consumption="1000")
    assert resp.status_code == 200
    resp = client.get("/api/tt/accounts/lookup?advertiser_id=1234567890123",
                      headers=tt_headers)
    data = resp.get_json()
    assert data["found"] is True
    assert "remark" not in data
    assert "consumption" not in data
    assert "death_date" not in data


def test_bc_history_owner_isolation(client, tt_headers):
    resp = _mk_account(client, tt_headers, advertiser_id="1234567890123")
    aid = resp.get_json()["id"]
    headers2 = _mk_tt_headers(client, "ttuser2")
    resp = client.get(f"/api/tt/accounts/{aid}/bc-history", headers=headers2)
    assert resp.status_code == 403


def test_delete_bc_history_requires_admin(client, tt_headers):
    resp = _mk_account(client, tt_headers, advertiser_id="1234567890123")
    aid = resp.get_json()["id"]
    resp = client.delete(f"/api/tt/accounts/{aid}/bc-history/1", headers=tt_headers)
    assert resp.status_code == 403


def test_recharge_submit_and_list(client, tt_headers):
    resp = _mk_account(client, tt_headers, advertiser_id="1112223334445")
    aid = resp.get_json()["id"]
    resp = client.post("/api/tt/recharge/submit", headers=tt_headers, json={
        "account_id": "1112223334445", "amount": "1000",
    })
    assert resp.status_code == 200
    rid = resp.get_json()["id"]

    resp = client.get(f"/api/tt/accounts/{aid}/recharge-records", headers=tt_headers)
    assert resp.get_json()["items"][0]["amount"] == "1000"


def test_recharge_records_owner_isolation(client, tt_headers):
    """其他普通用户不能读取他人账户的充值记录。"""
    resp = _mk_account(client, tt_headers, advertiser_id="1234567890123")
    aid = resp.get_json()["id"]
    client.post("/api/tt/recharge/submit", headers=tt_headers, json={
        "account_id": "1234567890123", "amount": "1000",
    })
    headers2 = _mk_tt_headers(client, "ttuser2")
    resp = client.get(f"/api/tt/accounts/{aid}/recharge-records", headers=headers2)
    assert resp.status_code == 403


def test_recharge_batch_submit_skips_non_owned(client, tt_headers):
    """批量充值应跳过非本人账户（owner 隔离），created 为 0 且无新增记录。"""
    _mk_account(client, tt_headers, advertiser_id="1234567890123")
    headers2 = _mk_tt_headers(client, "ttuser2")
    resp = client.post("/api/tt/recharge/batch-submit", headers=headers2, json={
        "items": [{"account_id": "1234567890123", "amount": "1000"}],
    })
    assert resp.status_code == 200
    assert resp.get_json()["created"] == 0
    db = database.get_db()
    cnt = db.execute("SELECT COUNT(*) FROM tt_recharge_records").fetchone()[0]
    db.close()
    assert cnt == 0


def test_recharge_batch_submit_skips_non_alive(client, tt_headers):
    """批量充值应跳过非「存活」状态的账户。"""
    _mk_account(client, tt_headers, advertiser_id="1234567890123", status="死亡")
    resp = client.post("/api/tt/recharge/batch-submit", headers=tt_headers, json={
        "items": [{"account_id": "1234567890123", "amount": "1000"}],
    })
    assert resp.status_code == 200
    assert resp.get_json()["created"] == 0
    db = database.get_db()
    cnt = db.execute("SELECT COUNT(*) FROM tt_recharge_records").fetchone()[0]
    db.close()
    assert cnt == 0


def test_recycle_reason_crud(client, tt_headers):
    resp = client.post("/api/tt/recycle-reasons/create", headers=tt_headers, json={"name": "跑量差"})
    assert resp.status_code == 200
    rid = resp.get_json()["id"]
    resp = client.get("/api/tt/recycle-reasons/list", headers=tt_headers)
    assert resp.get_json()["items"][0]["name"] == "跑量差"
    resp = client.put(f"/api/tt/recycle-reasons/{rid}", headers=tt_headers, json={"name": "跑量差改"})
    assert resp.status_code == 200
    resp = client.delete(f"/api/tt/recycle-reasons/{rid}", headers=tt_headers)
    assert resp.status_code == 200


def _mk_tt_admin_headers(client, username="ttadmin"):
    """创建一个 TT 平台的 admin 用户并返回其 JWT 请求头。"""
    client.post("/api/auth/register", json={"username": username, "password": "test123"})
    db = database.get_db()
    db.execute("UPDATE users SET platform='tt', role='admin' WHERE username=?", (username,))
    db.commit()
    db.close()
    resp = client.post("/api/auth/login", json={"username": username, "password": "test123"})
    token = resp.get_json().get("access_token", "")
    return {"Authorization": f"Bearer {token}"}


def test_recycle_reason_is_shared_across_users(client, tt_headers):
    """回收原因为公用词表：admin 建的原因，普通用户能看到并改名/删除。"""
    admin = _mk_tt_admin_headers(client)
    rid = client.post("/api/tt/recycle-reasons/create", headers=admin,
                      json={"name": "公用原因A"}).get_json()["id"]

    names = [r["name"] for r in
             client.get("/api/tt/recycle-reasons/list", headers=tt_headers)
                   .get_json()["items"]]
    assert "公用原因A" in names, "普通用户应能看到 admin 建的回收原因"

    assert client.put(f"/api/tt/recycle-reasons/{rid}", headers=tt_headers,
                      json={"name": "公用原因A改"}).status_code == 200
    assert client.delete(f"/api/tt/recycle-reasons/{rid}", headers=tt_headers).status_code == 200


def test_recycle_reason_name_globally_unique(client, tt_headers):
    """名称全平台唯一：不同用户建同名原因应 409。"""
    admin = _mk_tt_admin_headers(client, username="ttadmin2")
    assert client.post("/api/tt/recycle-reasons/create", headers=admin,
                       json={"name": "重名原因"}).status_code == 200
    assert client.post("/api/tt/recycle-reasons/create", headers=tt_headers,
                       json={"name": "重名原因"}).status_code == 409


def test_recycle_reason_rename_global_conflict(client, tt_headers):
    """改名撞已有名称应 409，而不是静默产生重名。"""
    rid_a = client.post("/api/tt/recycle-reasons/create", headers=tt_headers,
                        json={"name": "原因甲"}).get_json()["id"]
    client.post("/api/tt/recycle-reasons/create", headers=tt_headers, json={"name": "原因乙"})

    assert client.put(f"/api/tt/recycle-reasons/{rid_a}", headers=tt_headers,
                      json={"name": "原因乙"}).status_code == 409
    names = [r["name"] for r in
             client.get("/api/tt/recycle-reasons/list", headers=tt_headers)
                   .get_json()["items"]]
    assert "原因甲" in names and "原因乙" in names, "改名失败后原值应保持不变"


@mock.patch("google_sheets_service.build_service")
@mock.patch("google_sheets_service.read_sheet_values")
def test_sync_from_sheet_dry_run(mock_read, mock_build, client, tt_headers):
    # 构造看板 10 列：A运营 B入库 C是否回收 D账户ID EBC F国家 G渠道 H时区 I消耗 J备注
    mock_build.return_value = object()
    mock_read.return_value = [
        ["运营", "入库时间", "是否回收", "账户ID", "BC", "国家", "渠道", "时区", "消耗", "备注"],
        ["ttuser", "2026-09-20", "否", "1234567890123", "BC-A", "US", "渠道X", "+8", "高", "备注1"],
    ]
    db = database.get_db()
    # 同步门禁要求「运营」列匹配当前用户 display_name，fixture 仅注册未设 display_name，这里补齐
    db.execute("UPDATE users SET display_name='ttuser' WHERE username='ttuser'")
    db.execute("INSERT OR REPLACE INTO tags(key,value) VALUES('tt_sheet_id','sheet-1')")
    db.execute("INSERT OR REPLACE INTO tags(key,value) VALUES('tt_sheet_mappings', ?)",
               ('{"my_dashboard": "我的看板", "recharge": "充值表", "recycle": "回收户清单", "accounts": "账户明细"}',))
    db.commit()
    db.close()

    resp = client.post("/api/tt/accounts/sync-from-sheet", headers=tt_headers,
                       json={"dry_run": True})
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["total"] == 1


@mock.patch("google_sheets_service.build_service")
@mock.patch("google_sheets_service.read_sheet_values")
def test_sync_from_sheet_skips_header(mock_read, mock_build, client, tt_headers):
    """看板带表头第一行时，应跳过表头、正常识别数据行运营，不误报「运营列不匹配」。"""
    mock_build.return_value = object()
    mock_read.return_value = [
        ["运营", "入库时间", "是否回收", "账户ID", "BC", "国家", "渠道", "时区", "消耗", "备注"],
        ["黎明", "2026-09-20", "否", "1234567890123", "BC-A", "US", "渠道X", "+8", "高", "备注1"],
    ]
    db = database.get_db()
    db.execute("UPDATE users SET display_name='黎明' WHERE username='ttuser'")
    db.execute("INSERT OR REPLACE INTO tags(key,value) VALUES('tt_sheet_id','sheet-1')")
    db.execute("INSERT OR REPLACE INTO tags(key,value) VALUES('tt_sheet_mappings', ?)",
               ('{"my_dashboard": "我的看板", "recharge": "充值表", "recycle": "回收户清单", "accounts": "账户明细"}',))
    db.commit()
    db.close()

    resp = client.post("/api/tt/accounts/sync-from-sheet", headers=tt_headers,
                       json={"dry_run": True})
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["success"] is True
    assert data["total"] == 1


@mock.patch("google_sheets_service.build_service")
@mock.patch("google_sheets_service.read_sheet_values")
def test_sync_from_sheet_short_row_no_index_error(mock_read, mock_build, client, tt_headers):
    """看板数据行只有几列（未填满 A:J）时，应安全取空值，不抛 IndexError。"""
    mock_build.return_value = object()
    mock_read.return_value = [
        ["运营", "入库时间", "是否回收", "账户ID", "BC", "国家", "渠道", "时区", "消耗", "备注"],
        ["黎明", "2026-09-20", "否", "1234567890123"],  # 仅前 4 列，尾部列被 Sheets 截断
    ]
    db = database.get_db()
    db.execute("UPDATE users SET display_name='黎明' WHERE username='ttuser'")
    db.execute("INSERT OR REPLACE INTO tags(key,value) VALUES('tt_sheet_id','sheet-1')")
    db.execute("INSERT OR REPLACE INTO tags(key,value) VALUES('tt_sheet_mappings', ?)",
               ('{"my_dashboard": "我的看板"}',))
    db.commit()
    db.close()

    resp = client.post("/api/tt/accounts/sync-from-sheet", headers=tt_headers,
                       json={"dry_run": True})
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["success"] is True
    assert data["total"] == 1
    assert data["created"][0]["advertiser_id"] == "1234567890123"
    assert data["created"][0]["bc"] == ""
    assert data["created"][0]["consumption"] == ""


@mock.patch("routes.tt_accounts_routes._trigger_recycle_if_dead")
def test_update_same_status_does_not_rewrite_recycle(mock_trigger, client, tt_headers):
    """对已是「死亡」的账户再次提交同状态，不应重复写回收清单。"""
    resp = _mk_account(client, tt_headers, advertiser_id="1234567890123")
    aid = resp.get_json()["id"]

    db = database.get_db()
    dead = db.execute(
        "SELECT id FROM account_statuses WHERE name='死亡' AND platform='tt'"
    ).fetchone()
    if dead is None:
        db.execute("INSERT INTO account_statuses(name, platform) VALUES('死亡', 'tt')")
        db.commit()
        dead_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]
    else:
        dead_id = dead["id"]
    db.close()

    # 存活 → 死亡：应触发一次
    resp = client.put(f"/api/tt/accounts/{aid}", headers=tt_headers,
                      json={"status_id": dead_id, "recycle_reason": "测试"})
    assert resp.status_code == 200
    assert mock_trigger.call_count == 1

    # 再次提交同一 status_id：不应新增触发
    resp = client.put(f"/api/tt/accounts/{aid}", headers=tt_headers,
                      json={"status_id": dead_id, "recycle_reason": "测试"})
    assert resp.status_code == 200
    assert mock_trigger.call_count == 1


def test_ensure_bc_restores_soft_deleted(app):
    """软删后的 tt_bcs 应被 _ensure_bc 恢复复用，避免 bc_id UNIQUE 冲突。"""
    from routes.tt_accounts_routes import _ensure_bc

    db = database.get_db()
    db.execute("INSERT INTO tt_bcs(name, bc_id) VALUES(?,?)", ("BC-X", "BC-X"))
    db.commit()
    bid = db.execute("SELECT id FROM tt_bcs WHERE name='BC-X'").fetchone()["id"]
    db.execute("UPDATE tt_bcs SET deleted_at=datetime('now','localtime') WHERE id=?", (bid,))
    db.commit()

    got = _ensure_bc(db, "BC-X", 1)
    assert got == bid

    row = db.execute("SELECT id, deleted_at FROM tt_bcs WHERE name='BC-X'").fetchone()
    assert row["deleted_at"] is None
    cnt = db.execute("SELECT COUNT(*) FROM tt_bcs WHERE name='BC-X'").fetchone()[0]
    assert cnt == 1
    db.close()


def test_agents_platform_isolation(client, auth_headers, tt_headers):
    # TT 用户 A 创建平台共享代理
    resp = client.post("/api/agents/create", headers=tt_headers,
                       json={"name": "TT代理A"}, query_string={"platform": "tt"})
    assert resp.status_code == 200
    # 另一个 TT 用户 B 也能看到（平台级共享，无 owner 限制）
    tt_headers2 = _mk_tt_headers(client, "ttuser2")
    resp = client.get("/api/agents/list?platform=tt", headers=tt_headers2)
    names = [a["name"] for a in resp.get_json()["agents"]]
    assert "TT代理A" in names
    # GG 列表（默认）看不到 TT 代理
    resp = client.get("/api/agents/list", headers=auth_headers)
    names = [a["name"] for a in resp.get_json()["agents"]]
    assert "TT代理A" not in names


def test_agents_platform_rename_delete(client, tt_headers):
    """TT 代理的改名/删除**按 owner 私有**（B-4，2026-09-23 安全加固）。

    本用例原稿断言「另一个 TT 用户 B 跨 owner 改名/删除 → 200」，注释称 TT 代理为
    「平台级共享，无 owner 限制」—— 该认知与数据模型不符：`agents` 表的唯一约束是
    `UNIQUE(name, owner_id, platform)`（`py/database.py:1320`，2026-09-21 由 ef0a3a2 重建），
    且 `agents_create` 对 TT 代理写入 `owner_id=user_id`（`py/main.py:5932`）
    ⇒ TT 代理本就是按 owner 私有（创建即私有）。
    `agents_rename`/`agents_delete` 的 `platform == "tt"` 分支写在 `is_dev` 判断之前、
    且未校验 `owner_id`，属结构性遗漏（任何登录用户，连 viewer 在内，都能改/删他人 TT 代理）。
    现按设计文档 §3.2 B-4 收紧：非跨用户角色只能操作自己的 TT 代理（无权返回 404）。

    注意：TT 代理在**列表**上仍平台级可见（守护该行为的 test_agents_platform_isolation 未改动），
    本次收窄的只是**写**（改名/删除）。
    """
    # TT 用户 A 创建代理
    resp = client.post("/api/agents/create", headers=tt_headers,
                       json={"name": "TT代理B"}, query_string={"platform": "tt"})
    assert resp.status_code == 200
    aid = resp.get_json()["id"]
    tt_headers2 = _mk_tt_headers(client, "ttuser2")

    # 另一个 TT 用户 B 跨 owner 改名 → 404，且名称未被改动
    resp = client.put(f"/api/agents/{aid}", headers=tt_headers2,
                      json={"name": "TT代理B改"}, query_string={"platform": "tt"})
    assert resp.status_code == 404
    db = database.get_db()
    name = db.execute("SELECT name FROM agents WHERE id=?", (aid,)).fetchone()["name"]
    db.close()
    assert name == "TT代理B"

    # owner 本人改名 → 200
    resp = client.put(f"/api/agents/{aid}", headers=tt_headers,
                      json={"name": "TT代理B改"}, query_string={"platform": "tt"})
    assert resp.status_code == 200
    # 改名后该条目仍跨 owner 可见（列表读能力未随写收窄）
    resp = client.get("/api/agents/list?platform=tt", headers=tt_headers2)
    assert "TT代理B改" in [a["name"] for a in resp.get_json()["agents"]]

    # 另一个 TT 用户 B 跨 owner 删除 → 404，且行仍在
    resp = client.delete(f"/api/agents/{aid}", headers=tt_headers2,
                         query_string={"platform": "tt"})
    assert resp.status_code == 404
    db = database.get_db()
    row = db.execute("SELECT 1 FROM agents WHERE id=?", (aid,)).fetchone()
    db.close()
    assert row is not None

    # owner 本人删除 → 200，列表中消失
    resp = client.delete(f"/api/agents/{aid}", headers=tt_headers,
                         query_string={"platform": "tt"})
    assert resp.status_code == 200
    resp = client.get("/api/agents/list?platform=tt", headers=tt_headers)
    assert "TT代理B改" not in [a["name"] for a in resp.get_json()["agents"]]


def test_agents_delete_tt_referenced_by_tt_account(client, tt_headers):
    """删除被 tt_accounts 引用的 TT 代理 → 409 拒绝。"""
    resp = client.post("/api/agents/create", headers=tt_headers,
                       json={"name": "TT代理引用"}, query_string={"platform": "tt"})
    assert resp.status_code == 200
    aid = resp.get_json()["id"]

    db = database.get_db()
    uid = db.execute("SELECT id FROM users WHERE username='ttuser'").fetchone()["id"]
    db.execute("INSERT INTO tt_accounts(name, advertiser_id, agent_id, owner_id) VALUES(?,?,?,?)",
               ("引用户", "9990001112223", aid, uid))
    db.commit()
    db.close()

    resp = client.delete(f"/api/agents/{aid}", headers=tt_headers,
                         query_string={"platform": "tt"})
    assert resp.status_code == 409


def test_statuses_delete_tt_referenced_by_tt_account(client, tt_headers):
    """删除被 tt_accounts 引用的 TT 状态 → 409 拒绝。"""
    db = database.get_db()
    uid = db.execute("SELECT id FROM users WHERE username='ttuser'").fetchone()["id"]
    db.execute("INSERT INTO account_statuses(name, owner_id, platform) VALUES(?,?, 'tt')",
               ("特殊状态", uid))
    db.commit()
    sid = db.execute("SELECT id FROM account_statuses WHERE name='特殊状态' AND platform='tt'").fetchone()["id"]
    db.execute("INSERT INTO tt_accounts(name, advertiser_id, status_id, owner_id) VALUES(?,?,?,?)",
               ("引用户", "9990001112224", sid, uid))
    db.commit()
    db.close()

    resp = client.delete(f"/api/statuses/{sid}", headers=tt_headers)
    assert resp.status_code == 409


@mock.patch("google_sheets_service.build_service")
@mock.patch("google_sheets_service.read_sheet_values")
def test_sync_from_sheet_confirm_resolutions_owner_guard(mock_read, mock_build, client, tt_headers):
    """确认模式的 resolutions 只能改当前用户看板行里的 advertiser_id，越权项不生效。"""
    mock_build.return_value = object()
    # 看板行只含 advertiser_id=1111111111111（当前用户自己的账户）
    mock_read.return_value = [
        ["运营", "入库时间", "是否回收", "账户ID", "BC", "国家", "渠道", "时区", "消耗", "备注"],
        ["ttuser", "2026-09-20", "否", "1111111111111", "BC-A", "US", "渠道X", "+8", "100", "备注1"],
    ]
    db = database.get_db()
    db.execute("UPDATE users SET display_name='ttuser' WHERE username='ttuser'")
    db.execute("INSERT OR REPLACE INTO tags(key,value) VALUES('tt_sheet_id','sheet-1')")
    db.execute("INSERT OR REPLACE INTO tags(key,value) VALUES('tt_sheet_mappings', ?)",
               ('{"my_dashboard": "我的看板"}',))
    # 越权目标：不在看板行里，consumption 不应被 resolutions 改动
    db.execute("INSERT INTO tt_accounts(name, advertiser_id, consumption, owner_id) VALUES(?,?,?,?)",
               ("受害户", "9999999999999", "200", 1))
    db.commit()
    db.close()

    resp = client.post("/api/tt/accounts/sync-from-sheet", headers=tt_headers,
                       json={"dry_run": False, "resolutions": {"9999999999999": "999"}})
    assert resp.status_code == 200

    db = database.get_db()
    row = db.execute("SELECT consumption FROM tt_accounts WHERE advertiser_id='9999999999999'").fetchone()
    db.close()
    assert row["consumption"] == "200"


def test_region_timezone_strips_utc_prefix(app):
    """_region_timezone 返回值应去掉 UTC 前缀（UTC+8 → +8）。"""
    from routes.tt_accounts_routes import _region_timezone

    db = database.get_db()
    db.execute("DELETE FROM regions WHERE platform='tt'")
    db.execute("INSERT INTO regions(name, timezone, platform) VALUES(?,?, 'tt')", ("测试国", "UTC+8"))
    db.commit()
    assert _region_timezone(db, "测试国") == "+8"
    db.close()


# ==================== 修复验证（#1/#3/#5/#6/#7/#8/#10/#12/#17/#20） ====================

def _mk_viewer_headers(client, username="ttviewer"):
    """创建一个 TT 平台的 viewer（只读）用户并返回其 JWT 请求头。"""
    client.post("/api/auth/register", json={"username": username, "password": "test123"})
    db = database.get_db()
    db.execute("UPDATE users SET platform='tt', role='viewer' WHERE username=?", (username,))
    db.commit()
    db.close()
    resp = client.post("/api/auth/login", json={"username": username, "password": "test123"})
    token = resp.get_json().get("access_token", "")
    return {"Authorization": f"Bearer {token}"}


def test_create_account_requires_name(client, tt_headers):
    """#12 create_account 应拒绝空 name。"""
    resp = client.post("/api/tt/accounts/create", headers=tt_headers,
                       json={"advertiser_id": "1234567890123", "name": ""})
    assert resp.status_code == 400


def test_recharge_rejects_invalid_amount(client, tt_headers):
    """#10 充值金额必须为正数。"""
    _mk_account(client, tt_headers, advertiser_id="1112223334445")
    resp = client.post("/api/tt/recharge/submit", headers=tt_headers, json={
        "account_id": "1112223334445", "amount": "-5",
    })
    assert resp.status_code == 400
    resp = client.post("/api/tt/recharge/submit", headers=tt_headers, json={
        "account_id": "1112223334445", "amount": "abc",
    })
    assert resp.status_code == 400


def test_recharge_retry_sheets_owner_guard(client, tt_headers):
    """#7 retry-sheets 只能由记录创建者（或管理员）触发。"""
    _mk_account(client, tt_headers, advertiser_id="1112223334445")
    resp = client.post("/api/tt/recharge/submit", headers=tt_headers, json={
        "account_id": "1112223334445", "amount": "100",
    })
    rid = resp.get_json()["id"]
    headers2 = _mk_tt_headers(client, "ttuser2")
    resp = client.post(f"/api/tt/recharge/{rid}/retry-sheets", headers=headers2)
    assert resp.status_code == 403


def test_viewer_cannot_write_accounts(client):
    """#3 viewer 角色不能写账户（创建/修改/删除均 403）。"""
    viewer = _mk_viewer_headers(client)
    assert client.post("/api/tt/accounts/create", headers=viewer,
                       json={"advertiser_id": "1234567890123", "name": "x"}).status_code == 403
    assert client.post("/api/tt/recharge/submit", headers=viewer,
                       json={"account_id": "1234567890123", "amount": "100"}).status_code == 403
    assert client.post("/api/tt/recycle-reasons/create", headers=viewer,
                       json={"name": "x"}).status_code == 403


def test_agents_delete_tt_clears_recharge_agent(client, tt_headers):
    """#8 删除 TT 代理应清空 tt_recharge_records 的 agent_id 引用。"""
    resp = client.post("/api/agents/create", headers=tt_headers,
                       json={"name": "清引用代理"}, query_string={"platform": "tt"})
    aid = resp.get_json()["id"]
    db = database.get_db()
    uid = db.execute("SELECT id FROM users WHERE username='ttuser'").fetchone()["id"]
    db.execute("INSERT INTO tt_recharge_records(account_id, amount, agent_id, created_by) "
               "VALUES('111', '100', ?, ?)", (aid, uid))
    db.commit()
    db.close()

    resp = client.delete(f"/api/agents/{aid}", headers=tt_headers,
                         query_string={"platform": "tt"})
    assert resp.status_code == 200

    db = database.get_db()
    row = db.execute("SELECT agent_id FROM tt_recharge_records WHERE account_id='111'").fetchone()
    db.close()
    assert row["agent_id"] is None


def test_recharge_background_callback_updates_sheets_synced(client):
    """#1 后台线程回调（无应用上下文）应能更新 sheets_synced（不依赖 flask.g）。"""
    from routes.tt_accounts_routes import _append_recharge_background
    import main as main_mod

    client.post("/api/auth/register", json={"username": "rechargebg", "password": "test123"})
    db = database.get_db()
    uid = db.execute("SELECT id FROM users WHERE username='rechargebg'").fetchone()["id"]
    db.execute("INSERT INTO tt_recharge_records(id, account_id, amount, created_by, sheets_synced) "
               "VALUES(1, '111', '100', ?, 0)", (uid,))
    db.commit()
    db.close()

    captured = {}
    def fake_sync(sync_fn, on_fail_fn):
        captured["on_fail"] = on_fail_fn

    with mock.patch.object(main_mod, "_sync_sheets_background", side_effect=fake_sync):
        _append_recharge_background(database.get_db(), uid, "sheet", "充值表", [], [1])

    captured["on_fail"]("synced", "")

    db = database.get_db()
    row = db.execute("SELECT sheets_synced FROM tt_recharge_records WHERE id=1").fetchone()
    db.close()
    assert row["sheets_synced"] == 1


def test_ensure_bc_uses_owner_uid(client, tt_headers):
    """#6 同步新建 BC 时 owner_id 应为当前用户，而非写死 1。"""
    from routes.tt_accounts_routes import _ensure_bc

    # tt_headers 已注册 ttuser(id=1)；再注册一个用户，取 id != 1 验证未写死 1
    _mk_tt_headers(client, "bcowner")
    db = database.get_db()
    uid = db.execute("SELECT id FROM users WHERE username='bcowner'").fetchone()["id"]
    assert uid != 1
    bid = _ensure_bc(db, "同步BC", uid)
    row = db.execute("SELECT owner_id FROM tt_bcs WHERE id=?", (bid,)).fetchone()
    assert row["owner_id"] == uid
    db.close()


def test_sync_resolution_owner_guard(client, tt_headers):
    """#5 确认模式 resolutions 不能越权改他人账户的消耗。"""
    from unittest.mock import patch as _patch

    # 注册另一个用户并取其 id 作为「他人」账户 owner（当前用户 ttuser 不能改它）
    _mk_tt_headers(client, "otheruser")
    db = database.get_db()
    other_uid = db.execute("SELECT id FROM users WHERE username='otheruser'").fetchone()["id"]
    db.execute("UPDATE users SET display_name='ttuser' WHERE username='ttuser'")
    db.execute("INSERT OR REPLACE INTO tags(key,value) VALUES('tt_sheet_id','sheet-1')")
    db.execute("INSERT OR REPLACE INTO tags(key,value) VALUES('tt_sheet_mappings', ?)",
               ('{"my_dashboard": "我的看板"}',))
    # 他人账户，advertiser_id 出现在当前用户看板行中
    db.execute("INSERT INTO tt_accounts(name, advertiser_id, consumption, owner_id) "
               "VALUES('他人户', '1111111111111', '200', ?)", (other_uid,))
    db.commit()
    db.close()

    with _patch("google_sheets_service.build_service", return_value=object()), \
         _patch("google_sheets_service.read_sheet_values", return_value=[
             ["运营", "入库时间", "是否回收", "账户ID", "BC", "国家", "渠道", "时区", "消耗", "备注"],
             ["ttuser", "2026-09-20", "否", "1111111111111", "BC-A", "US", "渠道X", "+8", "高", "备注1"],
         ]):
        resp = client.post("/api/tt/accounts/sync-from-sheet", headers=tt_headers,
                           json={"dry_run": False, "resolutions": {"1111111111111": "999"}})
    assert resp.status_code == 200

    db = database.get_db()
    row = db.execute("SELECT consumption FROM tt_accounts WHERE advertiser_id='1111111111111'").fetchone()
    db.close()
    assert row["consumption"] == "200"  # 未越权改动


def test_sync_recreates_soft_deleted_account(client, tt_headers):
    """#5 看板里已软删的账户应被恢复，而非被当作"已存在"跳过。"""
    from unittest.mock import patch as _patch

    db = database.get_db()
    db.execute("UPDATE users SET display_name='ttuser' WHERE username='ttuser'")
    db.execute("INSERT OR REPLACE INTO tags(key,value) VALUES('tt_sheet_id','sheet-1')")
    db.execute("INSERT OR REPLACE INTO tags(key,value) VALUES('tt_sheet_mappings', ?)",
               ('{"my_dashboard": "我的看板"}',))
    uid = db.execute("SELECT id FROM users WHERE username='ttuser'").fetchone()["id"]
    db.execute("INSERT INTO tt_accounts(name, advertiser_id, owner_id, deleted_at) "
               "VALUES('旧户', '1234567890123', ?, datetime('now','localtime'))", (uid,))
    db.commit()
    db.close()

    with _patch("google_sheets_service.build_service", return_value=object()), \
         _patch("google_sheets_service.read_sheet_values", return_value=[
             ["运营", "入库时间", "是否回收", "账户ID", "BC", "国家", "渠道", "时区", "消耗", "备注"],
             ["ttuser", "2026-09-20", "否", "1234567890123", "BC-A", "US", "渠道X", "+8", "高", "备注1"],
         ]):
        resp = client.post("/api/tt/accounts/sync-from-sheet", headers=tt_headers,
                           json={"dry_run": False})
    assert resp.status_code == 200

    db = database.get_db()
    cnt = db.execute(
        "SELECT COUNT(*) FROM tt_accounts WHERE advertiser_id='1234567890123' AND deleted_at IS NULL"
    ).fetchone()[0]
    db.close()
    assert cnt == 1


def test_append_recharge_tt_writes_only_three_columns():
    """TT 充值写表：只写 A:C 三列，时间月/日文本、账户ID文本、金额数字。"""
    import re
    from google_sheets_service import append_recharge_tt

    fake = mock.MagicMock()
    fake.spreadsheets.return_value.get.return_value.execute.return_value = {
        "sheets": [{
            "properties": {"title": "充值表", "sheetId": 123,
                           "gridProperties": {"rowCount": 1000}}
        }]
    }
    fake.spreadsheets.return_value.values.return_value.get.return_value.execute.return_value = {
        "values": [["时间", "账户ID", "金额"]]
    }

    result = append_recharge_tt(fake, "sheet-1", "充值表", [
        {"account_id": "1234567890123", "amount": "1000"},
    ])
    assert result == {"appended": 1}

    update = fake.spreadsheets.return_value.values.return_value.update
    args, kwargs = update.call_args
    assert kwargs["range"] == "'充值表'!A2:C2"
    written = kwargs["body"]["values"][0]
    assert len(written) == 3
    assert re.match(r"^'\d{1,2}/\d{1,2}$", written[0])  # 时间 月/日 文本
    assert written[1] == "'1234567890123"  # 账户ID 文本
    assert written[2] == 1000.0  # 金额数字


def test_append_recharge_tt_appends_after_last_row():
    """TT 充值写表：应在已有数据后追加，不覆盖已有行。"""
    from google_sheets_service import append_recharge_tt

    fake = mock.MagicMock()
    fake.spreadsheets.return_value.get.return_value.execute.return_value = {
        "sheets": [{
            "properties": {"title": "充值表", "sheetId": 123,
                           "gridProperties": {"rowCount": 1000}}
        }]
    }
    fake.spreadsheets.return_value.values.return_value.get.return_value.execute.return_value = {
        "values": [["时间", "账户ID", "金额"], ["9/21", "111", "500"]]
    }

    append_recharge_tt(fake, "sheet-1", "充值表", [
        {"account_id": "222", "amount": "300"},
    ])

    update = fake.spreadsheets.return_value.values.return_value.update
    assert update.call_args.kwargs["range"] == "'充值表'!A3:C3"


def test_append_recharge_tt_finds_last_row_by_account_id_only():
    """TT 充值写表：判断最后一行只看「账户ID」列（B 列），忽略时间/金额列残留。"""
    from google_sheets_service import append_recharge_tt

    fake = mock.MagicMock()
    fake.spreadsheets.return_value.get.return_value.execute.return_value = {
        "sheets": [{
            "properties": {"title": "充值表", "sheetId": 123,
                           "gridProperties": {"rowCount": 1000}}
        }]
    }
    # 第 2 行账户ID有数据；第 3 行仅时间列（A）有残留、账户ID（B）为空 → 应忽略
    fake.spreadsheets.return_value.values.return_value.get.return_value.execute.return_value = {
        "values": [
            ["时间", "账户ID", "金额"],
            ["9/21", "111", "500"],
            ["9/22", "", ""],
        ]
    }

    append_recharge_tt(fake, "sheet-1", "充值表", [
        {"account_id": "222", "amount": "300"},
    ])

    update = fake.spreadsheets.return_value.values.return_value.update
    assert update.call_args.kwargs["range"] == "'充值表'!A3:C3"


@mock.patch("google_sheets_service.build_service")
@mock.patch("google_sheets_service.read_sheet_values")
def test_sync_from_sheet_status_conflict_dry_run(mock_read, mock_build, client, tt_headers):
    """C 列「是」（死亡）与系统「存活」不一致 → dry_run 返回 status_conflicts。"""
    mock_build.return_value = object()
    mock_read.return_value = [
        ["运营", "入库时间", "是否回收", "账户ID", "BC", "国家", "渠道", "时区", "消耗", "备注"],
        ["ttuser", "2026-09-20", "是", "1234567890123", "BC-A", "US", "渠道X", "+8", "高", "备注1"],
    ]
    db = database.get_db()
    db.execute("UPDATE users SET display_name='ttuser' WHERE username='ttuser'")
    db.execute("INSERT OR REPLACE INTO tags(key,value) VALUES('tt_sheet_id','sheet-1')")
    db.execute("INSERT OR REPLACE INTO tags(key,value) VALUES('tt_sheet_mappings', ?)",
               ('{"my_dashboard": "我的看板"}',))
    uid = db.execute("SELECT id FROM users WHERE username='ttuser'").fetchone()["id"]
    # 已存在账户，未设置 status_id（系统视为「存活」）
    db.execute("INSERT INTO tt_accounts(name, advertiser_id, owner_id) VALUES(?,?,?)",
               ("存量户", "1234567890123", uid))
    db.commit()
    db.close()

    resp = client.post("/api/tt/accounts/sync-from-sheet", headers=tt_headers,
                       json={"dry_run": True})
    assert resp.status_code == 200
    data = resp.get_json()
    sc = data.get("status_conflicts", [])
    assert len(sc) == 1
    assert sc[0]["advertiser_id"] == "1234567890123"
    assert sc[0]["sheet_status"] == "死亡"
    assert sc[0]["system_status"] == "存活"


@mock.patch("routes.tt_accounts_routes._trigger_recycle_if_dead")
@mock.patch("google_sheets_service.build_service")
@mock.patch("google_sheets_service.read_sheet_values")
def test_sync_from_sheet_confirm_status_resolutions(mock_read, mock_build, mock_trigger, client, tt_headers):
    """确认模式传 status_resolutions → 更新账户状态为「死亡」（不写回收清单）。"""
    mock_build.return_value = object()
    mock_read.return_value = [
        ["运营", "入库时间", "是否回收", "账户ID", "BC", "国家", "渠道", "时区", "消耗", "备注"],
        ["ttuser", "2026-09-20", "是", "1234567890123", "BC-A", "US", "渠道X", "+8", "高", "备注1"],
    ]
    db = database.get_db()
    db.execute("UPDATE users SET display_name='ttuser' WHERE username='ttuser'")
    db.execute("INSERT OR REPLACE INTO tags(key,value) VALUES('tt_sheet_id','sheet-1')")
    db.execute("INSERT OR REPLACE INTO tags(key,value) VALUES('tt_sheet_mappings', ?)",
               ('{"my_dashboard": "我的看板"}',))
    uid = db.execute("SELECT id FROM users WHERE username='ttuser'").fetchone()["id"]
    db.execute("INSERT INTO tt_accounts(name, advertiser_id, owner_id) VALUES(?,?,?)",
               ("存量户", "1234567890123", uid))
    db.commit()
    db.close()

    resp = client.post("/api/tt/accounts/sync-from-sheet", headers=tt_headers,
                       json={"dry_run": False, "status_resolutions": {"1234567890123": "死亡"}})
    assert resp.status_code == 200

    db = database.get_db()
    row = db.execute(
        "SELECT s.name FROM tt_accounts a JOIN account_statuses s ON s.id=a.status_id "
        "WHERE a.advertiser_id='1234567890123'"
    ).fetchone()
    db.close()
    assert row is not None and row["name"] == "死亡"
    mock_trigger.assert_not_called()


@mock.patch("google_sheets_service.build_service")
@mock.patch("google_sheets_service.read_sheet_values")
def test_sync_from_sheet_new_account_dead_status_import(mock_read, mock_build, client, tt_headers):
    """新户 C 列「是」→ dry_run created 标死亡，confirm 导入后状态为「死亡」。"""
    mock_build.return_value = object()
    mock_read.return_value = [
        ["运营", "入库时间", "是否回收", "账户ID", "BC", "国家", "渠道", "时区", "消耗", "备注"],
        ["ttuser", "2026-09-20", "是", "1234567890123", "BC-A", "US", "渠道X", "+8", "高", "备注1"],
    ]
    db = database.get_db()
    db.execute("UPDATE users SET display_name='ttuser' WHERE username='ttuser'")
    db.execute("INSERT OR REPLACE INTO tags(key,value) VALUES('tt_sheet_id','sheet-1')")
    db.execute("INSERT OR REPLACE INTO tags(key,value) VALUES('tt_sheet_mappings', ?)",
               ('{"my_dashboard": "我的看板"}',))
    db.commit()
    db.close()

    resp = client.post("/api/tt/accounts/sync-from-sheet", headers=tt_headers,
                       json={"dry_run": True})
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["created"][0]["status"] == "死亡"

    # 确认导入
    resp = client.post("/api/tt/accounts/sync-from-sheet", headers=tt_headers,
                       json={"dry_run": False})
    assert resp.status_code == 200

    db = database.get_db()
    row = db.execute(
        "SELECT s.name FROM tt_accounts a JOIN account_statuses s ON s.id=a.status_id "
        "WHERE a.advertiser_id='1234567890123'"
    ).fetchone()
    db.close()
    assert row is not None and row["name"] == "死亡"


def test_append_recycle_writes_only_three_columns():
    """回收户清单：只写 A(时间)/B(账户ID)/H(回收原因)，不触碰 C-L 公式列。"""
    from google_sheets_service import append_recycle

    fake = mock.MagicMock()
    fake.spreadsheets.return_value.get.return_value.execute.return_value = {
        "sheets": [{
            "properties": {"title": "回收户清单", "sheetId": 456,
                           "gridProperties": {"rowCount": 1000}}
        }]
    }
    fake.spreadsheets.return_value.values.return_value.get.return_value.execute.return_value = {
        "values": [["时间", "账户ID"]]
    }

    result = append_recycle(fake, "sheet-1", "回收户清单", [
        {"time": "2026-09-22", "account_id": "1234567890123", "reason": "跑量差"},
    ])
    assert result == {"appended": 1}

    batch = fake.spreadsheets.return_value.values.return_value.batchUpdate
    args, kwargs = batch.call_args
    data = kwargs["body"]["data"]
    assert len(data) == 3
    assert [d["range"] for d in data] == [
        "'回收户清单'!A2:A2", "'回收户清单'!B2:B2", "'回收户清单'!H2:H2"]
    assert data[0]["values"] == [["'2026-09-22"]]         # A 时间（文本，前导 '）
    assert data[1]["values"] == [["'1234567890123"]]      # B 账户ID（文本，前导 '）
    assert data[2]["values"] == [["跑量差"]]              # H 回收原因


def test_append_recycle_finds_last_row_by_account_id_only():
    """回收户清单：判断最后一行只看「账户ID」列（B 列），忽略时间列（A）残留。"""
    from google_sheets_service import append_recycle

    fake = mock.MagicMock()
    fake.spreadsheets.return_value.get.return_value.execute.return_value = {
        "sheets": [{
            "properties": {"title": "回收户清单", "sheetId": 456,
                           "gridProperties": {"rowCount": 1000}}
        }]
    }
    # 第 2 行账户ID有数据；第 3 行仅时间列（A）有残留、账户ID（B）为空 → 应忽略
    fake.spreadsheets.return_value.values.return_value.get.return_value.execute.return_value = {
        "values": [
            ["时间", "账户ID"],
            ["2026-09-21", "111"],
            ["2026-09-22", ""],
        ]
    }

    append_recycle(fake, "sheet-1", "回收户清单", [
        {"time": "2026-09-22", "account_id": "222", "reason": "跑量差"},
    ])

    batch = fake.spreadsheets.return_value.values.return_value.batchUpdate
    data = batch.call_args.kwargs["body"]["data"]
    assert [d["range"] for d in data] == [
        "'回收户清单'!A3:A3", "'回收户清单'!B3:B3", "'回收户清单'!H3:H3"]


def test_trigger_recycle_on_non_alive_status(app):
    """非存活状态（验证/封禁/死亡）都应写回收清单；存活不写。"""
    from routes.tt_accounts_routes import _trigger_recycle_if_dead

    db = database.get_db()
    db.execute("INSERT OR IGNORE INTO users(id, username, password, role) VALUES(1, 'dev', 'x', 'developer')")
    db.execute("INSERT OR REPLACE INTO tags(key,value) VALUES('tt_sheet_id','sheet-1')")
    db.execute("INSERT OR REPLACE INTO tags(key,value) VALUES('tt_sheet_mappings', ?)",
               ('{"recycle": "回收户清单"}',))
    for name in ("存活", "验证", "封禁", "死亡"):
        db.execute("INSERT OR IGNORE INTO account_statuses(name, platform) VALUES(?, 'tt')", (name,))
    db.commit()
    ids = {r["name"]: r["id"] for r in db.execute(
        "SELECT id, name FROM account_statuses WHERE platform='tt'").fetchall()}

    # 写表已接入统一入口（sheet_write.run_write），只保留「哪些状态该触发」这一派遣逻辑的守卫。
    with mock.patch("routes.tt_accounts_routes.sheet_write.run_write") as writer:
        for name in ("验证", "封禁", "死亡"):
            _trigger_recycle_if_dead(db, 1, "1234567890123", ids[name], "跑量差")
        # 存活不写回收清单
        _trigger_recycle_if_dead(db, 1, "1234567890123", ids["存活"], None)
        # 非存活但 reason 为空：后端兜底也不写
        _trigger_recycle_if_dead(db, 1, "1234567890123", ids["验证"], None)

    assert writer.call_count == 3
    db.close()


def test_list_filters_by_account_types(client, tt_headers):
    db = database.get_db()
    db.execute("INSERT INTO tt_accounts(name, advertiser_id, account_type, owner_id) "
               "SELECT 'a','6101','加白户', id FROM users WHERE username='ttuser'")
    db.execute("INSERT INTO tt_accounts(name, advertiser_id, account_type, owner_id) "
               "SELECT 'b','6102','企业户', id FROM users WHERE username='ttuser'")
    db.execute("INSERT INTO tt_accounts(name, advertiser_id, account_type, owner_id) "
               "SELECT 'c','6103','企业户', id FROM users WHERE username='ttuser'")
    db.commit()
    db.close()

    data = client.get("/api/tt/accounts/list?account_types=企业户",
                      headers=tt_headers).get_json()
    assert data["total"] == 2
    assert {i["advertiser_id"] for i in data["items"]} == {"6102", "6103"}
    assert data["type_counts"] == {"加白户": 1, "企业户": 2}

    data = client.get("/api/tt/accounts/list?account_types=加白户&account_types=企业户",
                      headers=tt_headers).get_json()
    assert data["total"] == 3


def test_type_counts_ignores_type_filter_but_respects_search(client, tt_headers):
    """type_counts 与 status_counts 同底：含 search，不含 account_types 自身。"""
    db = database.get_db()
    db.execute("INSERT INTO tt_accounts(name, advertiser_id, account_type, owner_id) "
               "SELECT 'a','6201','加白户', id FROM users WHERE username='ttuser'")
    db.execute("INSERT INTO tt_accounts(name, advertiser_id, account_type, owner_id) "
               "SELECT 'b','6202','企业户', id FROM users WHERE username='ttuser'")
    db.commit()
    db.close()
    data = client.get("/api/tt/accounts/list?account_types=加白户&search=6202",
                      headers=tt_headers).get_json()
    assert data["total"] == 0
    assert data["type_counts"] == {"企业户": 1}, "计数要跟着 search 走"


def test_list_extra_blank_account_types_ignored(client, tt_headers):
    """空串 / 纯空白参数必须被忽略，不得被当成筛选值。"""
    db = database.get_db()
    db.execute("INSERT INTO tt_accounts(name, advertiser_id, account_type, owner_id) "
               "SELECT 'a','6301','加白户', id FROM users WHERE username='ttuser'")
    db.execute("INSERT INTO tt_accounts(name, advertiser_id, account_type, owner_id) "
               "SELECT 'b','6302','企业户', id FROM users WHERE username='ttuser'")
    db.commit()
    db.close()
    data = client.get("/api/tt/accounts/list?account_types=&account_types=&account_types=%20",
                      headers=tt_headers).get_json()
    assert data["success"] is True
    # 真的断言：空串/空白若被当成筛选值，会命中 0 行（COALESCE 口径下空串永不匹配）
    assert data["total"] == 2, "空串/纯空白参数不得被当成筛选值"


def test_type_filter_includes_blank_account_type_as_default(client, tt_headers):
    """筛选口径必须与 type_counts 的 COALESCE 一致：空 account_type 的行在计数里
    被折进默认类型「加白户」那个桶，筛选也必须能一并筛出来 —— 否则就是本文件在
    status_id 上修过的同一类缺陷（按钮上写着 N、点下去对不上）。"""
    db = database.get_db()
    # account_type='' —— 三处 INSERT 目前不写该列，空类型行确实存在
    db.execute("INSERT INTO tt_accounts(name, advertiser_id, account_type, owner_id) "
               "SELECT 'blank','6401','', id FROM users WHERE username='ttuser'")
    db.execute("INSERT INTO tt_accounts(name, advertiser_id, account_type, owner_id) "
               "SELECT 'explicit','6402','加白户', id FROM users WHERE username='ttuser'")
    db.commit()
    db.close()
    data = client.get("/api/tt/accounts/list?account_types=加白户",
                      headers=tt_headers).get_json()
    assert data["type_counts"].get("加白户") == 2, "空类型行计入默认类型桶"
    assert data["total"] == 2, "筛选口径必须与计数一致，空类型行也要能筛出来"
    assert {i["advertiser_id"] for i in data["items"]} == {"6401", "6402"}
