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
    from tt_master_data import strip_utc_prefix
    assert strip_utc_prefix("UTC+8") == "+8"
    assert strip_utc_prefix("+8") == "+8"
    assert strip_utc_prefix("") == ""
    assert strip_utc_prefix(None) == ""


def test_ensure_bc_creates_with_name_as_bc_id_and_revives_soft_deleted():
    from tt_master_data import ensure_bc
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
    from tt_master_data import ensure_agent
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
