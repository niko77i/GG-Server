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
    body = {"advertiser_id": advertiser_id, **kw}
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


@mock.patch("google_sheets_service.build_service")
@mock.patch("google_sheets_service.read_sheet_values")
def test_sync_from_sheet_dry_run(mock_read, mock_build, client, tt_headers):
    # 构造看板 10 列：A运营 B入库 C是否回收 D账户ID EBC F国家 G渠道 H时区 I消耗 J备注
    mock_build.return_value = object()
    mock_read.return_value = [
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

    got = _ensure_bc(db, "BC-X")
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
    # TT 用户 A 创建平台共享代理
    resp = client.post("/api/agents/create", headers=tt_headers,
                       json={"name": "TT代理B"}, query_string={"platform": "tt"})
    assert resp.status_code == 200
    aid = resp.get_json()["id"]
    # 另一个 TT 用户 B 跨 owner 重命名（平台级共享，无 owner 限制）
    tt_headers2 = _mk_tt_headers(client, "ttuser2")
    resp = client.put(f"/api/agents/{aid}", headers=tt_headers2,
                      json={"name": "TT代理B改"}, query_string={"platform": "tt"})
    assert resp.status_code == 200
    resp = client.get("/api/agents/list?platform=tt", headers=tt_headers2)
    names = [a["name"] for a in resp.get_json()["agents"]]
    assert "TT代理B改" in names
    # 跨 owner 删除（平台级共享）
    resp = client.delete(f"/api/agents/{aid}", headers=tt_headers2,
                         query_string={"platform": "tt"})
    assert resp.status_code == 200
    resp = client.get("/api/agents/list?platform=tt", headers=tt_headers2)
    names = [a["name"] for a in resp.get_json()["agents"]]
    assert "TT代理B改" not in names
