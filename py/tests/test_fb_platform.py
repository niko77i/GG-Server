"""FB 平台支持 — 数据库测试"""
import pytest
import sys
import os
import sqlite3
import tempfile

_py_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _py_dir not in sys.path:
    sys.path.insert(0, _py_dir)

import database  # noqa: E402


@pytest.fixture
def test_conn():
    """创建临时数据库并执行 _ensure_schema，测试后清理"""
    db_fd, db_path = tempfile.mkstemp(suffix=".db")
    original_path = database._db_path
    database._db_path = lambda: db_path
    # 重置 schema 缓存
    database._schema_verified = False
    database._schema_verified_path = None

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    yield conn
    conn.close()
    os.close(db_fd)
    try:
        os.unlink(db_path)
    except OSError:
        pass
    database._db_path = original_path
    database._schema_verified = False
    database._schema_verified_path = None


def test_users_table_has_platform_column(test_conn):
    """验证 _ensure_schema 创建的 users 表包含 platform 字段"""
    database._ensure_schema(test_conn)
    cursor = test_conn.execute("PRAGMA table_info(users)")
    columns = {row[1]: row[2] for row in cursor.fetchall()}
    assert 'platform' in columns, f"users 表缺少 platform 列。现有列: {list(columns.keys())}"
    assert columns['platform'] == 'TEXT'


def test_platform_default_value(test_conn):
    """验证 platform 字段默认值为 'gg'"""
    database._ensure_schema(test_conn)
    test_conn.execute(
        "INSERT INTO users (username, password, role) VALUES (?, ?, ?)",
        ('test_default', 'pbkdf2:sha256:xxx', 'user')
    )
    test_conn.commit()
    user = test_conn.execute("SELECT platform FROM users WHERE username='test_default'").fetchone()
    assert user['platform'] == 'gg', f"期望 platform='gg', 实际='{user['platform']}'"


def test_platform_column_allows_null(test_conn):
    """验证 platform 列允许 NULL（developer 双平台用）"""
    database._ensure_schema(test_conn)
    test_conn.execute(
        "INSERT INTO users (username, password, role, platform) VALUES (?, ?, ?, NULL)",
        ('test_null_plat', 'pbkdf2:sha256:xxx', 'user')
    )
    test_conn.commit()
    user = test_conn.execute("SELECT platform FROM users WHERE username='test_null_plat'").fetchone()
    assert user['platform'] is None
