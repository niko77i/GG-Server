"""ensure_bc / ensure_agent / strip_utc_prefix —— 从 tt_accounts_routes 提取到共享模块后的行为锚。"""
import os
import sys
import tempfile
import sqlite3
import pytest

_py_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _py_dir not in sys.path:
    sys.path.insert(0, _py_dir)

import database  # noqa: E402


def _fresh_schema_conn_of(_database):
    """创建干净的临时 SQLite 连接，复刻 get_db 的建表 + 列迁移流程（对齐 test_tt_platform）。"""
    fd, db_path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    _database._ensure_schema(conn)
    _database._ensure_columns(conn)
    conn.commit()
    return conn, db_path


def test_strip_utc_prefix():
    from master_data import strip_utc_prefix
    assert strip_utc_prefix("UTC+8") == "+8"
    assert strip_utc_prefix("+8") == "+8"
    assert strip_utc_prefix("") == ""
    assert strip_utc_prefix(None) == ""


def test_ensure_bc_creates_with_name_as_bc_id_and_revives_soft_deleted():
    from master_data import ensure_bc
    import database
    conn, db_path = _fresh_schema_conn_of(database)
    try:
        new_id = ensure_bc(conn, "7677926795186094081", 1)
        row = conn.execute("SELECT name, bc_id, owner_id, deleted_at FROM tt_bcs WHERE id=?",
                           (new_id,)).fetchone()
        assert row["name"] == "7677926795186094081"
        assert row["bc_id"] == "7677926795186094081"      # 与实证数据一致
        assert row["owner_id"] == 1
        # 软删复活：把刚建的软删，再 ensure 同名 ⇒ 同一个 id、deleted_at 清空
        conn.execute("UPDATE tt_bcs SET deleted_at='2026-01-01' WHERE id=?", (new_id,))
        again = ensure_bc(conn, "7677926795186094081", 1)
        assert again == new_id
        assert conn.execute("SELECT deleted_at FROM tt_bcs WHERE id=?",
                            (new_id,)).fetchone()["deleted_at"] is None
    finally:
        conn.close()
        os.unlink(db_path)


def test_ensure_agent_creates_and_clears_cache(monkeypatch):
    import cache
    cleared = []
    monkeypatch.setattr(cache.cache, "clear_prefix", lambda p: cleared.append(p))
    from master_data import ensure_agent
    import database
    conn, db_path = _fresh_schema_conn_of(database)
    try:
        aid = ensure_agent(conn, "渠道Z", 1)
        row = conn.execute("SELECT name, platform, owner_id FROM agents WHERE id=?",
                           (aid,)).fetchone()
        assert (row["name"], row["platform"], row["owner_id"]) == ("渠道Z", "tt", 1)
        assert "accounts:agents:" in cleared, "新建渠道后必须清缓存，否则下拉看不到"
    finally:
        conn.close()
        os.unlink(db_path)


@pytest.fixture
def fb_users(client):
    """造出 id=7 / id=9 两个用户，满足 `fb_channels` / `fb_asset_types` 的
    `owner_id REFERENCES users(id)`。

    为什么必须：这两张表的 owner_id 是外键，而 `client` 夹具走的
    `database.get_db()` 会开 `PRAGMA foreign_keys=ON`（`database.py:51`）。
    直接拿 uid=7/9 去 INSERT 会抛 `FOREIGN KEY constraint failed`。
    生产路径里 uid 来自 JWT 身份 ⇒ 必然是真实用户，这里把该前提补齐。
    （同文件既有的 `ensure_bc` / `ensure_agent` 用例走 `_fresh_schema_conn_of`
    的裸连接、没开 FK pragma，所以不受此约束 —— 但那并不适合作为本用例的
    依据：本用例刻意走真实 `get_db()` 路径。）
    """
    db = database.get_db()
    for uid in (7, 9):
        db.execute("INSERT INTO users(id, username, password) VALUES(?,?,?)",
                   (uid, f"fbowner{uid}", "x"))
    db.commit()
    db.close()
    return (7, 9)


class TestEnsureFbDictionaries:
    """fb_channels / fb_asset_types 的幂等补建（设计 §4.4 / §4.4bis）。

    与 `ensure_agent` 的关键差别：这两张表**没有 deleted_at**（不像 tt_bcs），
    所以没有「软删复活」这一档；且 `platform` 必须**写死 'fb'` ——
    同步侧的 `_SQL_CHANNEL` / `_SQL_ASSET_TYPE` 写死了 `platform='fb'`，
    跟着请求侧的平台走会建出同步侧永远查不到的行。
    """

    def test_ensure_channel_creates_then_is_idempotent(self, client, fb_users):
        from master_data import ensure_channel
        db = database.get_db()
        cid = ensure_channel(db, "渠道甲", 7)
        db.commit()
        assert cid is not None
        assert ensure_channel(db, "渠道甲", 7) == cid, "第二次必须复用，不再新建"
        assert db.execute("SELECT COUNT(*) FROM fb_channels WHERE name='渠道甲'"
                          ).fetchone()[0] == 1
        db.close()

    def test_ensure_channel_pins_platform_fb_and_owner(self, client, fb_users):
        from master_data import ensure_channel
        db = database.get_db()
        ensure_channel(db, "渠道乙", 9)
        db.commit()
        row = db.execute("SELECT platform, owner_id FROM fb_channels WHERE name='渠道乙'"
                         ).fetchone()
        assert row["platform"] == "fb", "platform 必须写死 'fb'，不能跟请求侧走"
        assert row["owner_id"] == 9
        db.close()

    def test_ensure_channel_blank_name_is_noop(self, client, fb_users):
        from master_data import ensure_channel
        db = database.get_db()
        assert ensure_channel(db, "", 7) is None
        assert ensure_channel(db, "   ", 7) is None
        assert ensure_channel(db, None, 7) is None
        db.commit()
        assert db.execute("SELECT COUNT(*) FROM fb_channels").fetchone()[0] == 0
        db.close()

    def test_ensure_asset_type_creates_then_is_idempotent(self, client, fb_users):
        from master_data import ensure_asset_type
        db = database.get_db()
        tid = ensure_asset_type(db, "资产甲", 7)
        db.commit()
        assert tid is not None
        assert ensure_asset_type(db, "资产甲", 7) == tid
        assert db.execute("SELECT COUNT(*) FROM fb_asset_types WHERE name='资产甲'"
                          ).fetchone()[0] == 1
        assert db.execute("SELECT platform FROM fb_asset_types WHERE name='资产甲'"
                          ).fetchone()[0] == "fb"
        db.close()

    def test_ensure_channel_ignores_rows_of_other_platforms(self, client, fb_users):
        """同名但 platform 不是 fb 的行不该被当成「已有」。"""
        from master_data import ensure_channel
        db = database.get_db()
        db.execute("INSERT INTO fb_channels(name, owner_id, platform) VALUES(?,?,?)",
                   ("同名", None, "gg"))
        db.commit()
        cid = ensure_channel(db, "同名", 7)
        db.commit()
        assert cid is not None
        assert db.execute("SELECT COUNT(*) FROM fb_channels WHERE name='同名'"
                          ).fetchone()[0] == 2, "fb 命名空间里没有 ⇒ 应当新建一行"
        db.close()
