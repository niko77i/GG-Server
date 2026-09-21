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
