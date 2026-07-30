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


# ==================== FB 表测试 ====================

FB_TABLES = [
    'fb_bms', 'fb_accounts', 'fb_account_bm', 'fb_account_bm_history',
    'fb_products', 'fb_product_runners', 'fb_product_bms',
    'fb_lines', 'fb_pixel_bms', 'fb_pixels', 'fb_ad_reports'
]


@pytest.mark.parametrize("table_name", FB_TABLES)
def test_fb_table_exists(test_conn, table_name):
    """验证每张 FB 表都被 _ensure_schema 创建"""
    database._ensure_schema(test_conn)
    row = test_conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table_name,)
    ).fetchone()
    assert row is not None, f"表 {table_name} 未创建"


def test_fb_bms_unique_bm_id(test_conn):
    """验证 fb_bms.bm_id 唯一约束"""
    database._ensure_schema(test_conn)
    # 先插入 users 以支持外键
    test_conn.execute(
        "INSERT INTO users (username, password, role) VALUES (?,?,?)",
        ('test_fb', 'x', 'user')
    )
    test_conn.commit()
    uid = test_conn.execute("SELECT id FROM users WHERE username='test_fb'").fetchone()['id']
    test_conn.execute("INSERT INTO fb_bms (name, bm_id, owner_id) VALUES ('a', '111', ?)", (uid,))
    test_conn.commit()
    with pytest.raises(sqlite3.IntegrityError):
        test_conn.execute("INSERT INTO fb_bms (name, bm_id, owner_id) VALUES ('b', '111', ?)", (uid,))
        test_conn.commit()


def test_fb_account_bm_many_to_many(test_conn):
    """验证 fb_account_bm 多对多关系"""
    database._ensure_schema(test_conn)
    test_conn.execute("INSERT INTO users (username, password, role) VALUES ('t1','x','user')")
    test_conn.commit()
    uid = test_conn.execute("SELECT id FROM users WHERE username='t1'").fetchone()['id']
    test_conn.execute("INSERT INTO fb_bms (name, bm_id, owner_id) VALUES ('bm1','1',?),('bm2','2',?)", (uid, uid))
    test_conn.execute("INSERT INTO fb_accounts (name, account_id, owner_id) VALUES ('acc','999999999999999',?)", (uid,))
    test_conn.commit()
    bm1 = test_conn.execute("SELECT id FROM fb_bms WHERE bm_id='1'").fetchone()['id']
    bm2 = test_conn.execute("SELECT id FROM fb_bms WHERE bm_id='2'").fetchone()['id']
    acc = test_conn.execute("SELECT id FROM fb_accounts WHERE account_id='999999999999999'").fetchone()['id']
    test_conn.execute("INSERT INTO fb_account_bm (account_id, bm_id) VALUES (?,?),(?,?)", (acc, bm1, acc, bm2))
    test_conn.commit()
    count = test_conn.execute("SELECT COUNT(*) FROM fb_account_bm WHERE account_id=?", (acc,)).fetchone()[0]
    assert count == 2


def test_fb_lines_unique_product_line(test_conn):
    """验证 fb_lines 同一产品下不能重名"""
    database._ensure_schema(test_conn)
    test_conn.execute("INSERT INTO users (username,password,role) VALUES ('t2','x','user')")
    test_conn.commit()
    uid = test_conn.execute("SELECT id FROM users WHERE username='t2'").fetchone()['id']
    test_conn.execute("INSERT INTO fb_products (product_name, owner_id) VALUES ('p1',?)", (uid,))
    test_conn.commit()
    pid = test_conn.execute("SELECT id FROM fb_products WHERE product_name='p1'").fetchone()['id']
    test_conn.execute("INSERT INTO fb_lines (product_id, line_name) VALUES (?, 'L1')", (pid,))
    test_conn.commit()
    with pytest.raises(sqlite3.IntegrityError):
        test_conn.execute("INSERT INTO fb_lines (product_id, line_name) VALUES (?, 'L1')", (pid,))
        test_conn.commit()


def test_fb_ad_reports_dedup_index(test_conn):
    """验证 fb_ad_reports 去重索引存在"""
    database._ensure_schema(test_conn)
    indexes = test_conn.execute(
        "SELECT name FROM sqlite_master WHERE type='index' AND name LIKE 'idx_fb_ad_reports%'"
    ).fetchall()
    names = [i['name'] for i in indexes]
    assert 'idx_fb_ad_reports_upsert' in names, f"缺少去重索引，现有: {names}"


def test_fb_pixels_cascade_on_bm_delete(test_conn):
    """验证删除像素BM时级联删除像素"""
    database._ensure_schema(test_conn)
    test_conn.execute("INSERT INTO users (username,password,role) VALUES ('t3','x','user')")
    test_conn.commit()
    uid = test_conn.execute("SELECT id FROM users WHERE username='t3'").fetchone()['id']
    test_conn.execute("INSERT INTO fb_pixel_bms (name, bm_id, owner_id) VALUES ('pb','123',?)", (uid,))
    test_conn.commit()
    pbm = test_conn.execute("SELECT id FROM fb_pixel_bms WHERE bm_id='123'").fetchone()['id']
    test_conn.execute("INSERT INTO fb_pixels (pixel_bm_id, pixel_name, pixel_id) VALUES (?, 'px1', '456')", (pbm,))
    test_conn.commit()
    # 删除像素BM
    test_conn.execute("DELETE FROM fb_pixel_bms WHERE id=?", (pbm,))
    test_conn.commit()
    # 像素应该被级联删除
    px = test_conn.execute("SELECT id FROM fb_pixels WHERE pixel_id='456'").fetchone()
    assert px is None, "像素应被级联删除"


# ==================== auth.py platform 测试 ====================

@pytest.fixture
def patched_db():
    """将 database._db_path 指向测试数据库，并预建 schema"""
    import tempfile, os
    db_fd, db_path = tempfile.mkstemp(suffix=".db")
    original_path = database._db_path
    database._db_path = lambda: db_path
    database._schema_verified = False
    database._schema_verified_path = None
    # 通过 get_db() 触发建 schema（使用正确的顺序）
    try:
        db = database.get_db()
        # 再确保 _ensure_columns 和 migration 也执行了
    finally:
        pass
    yield db
    database._db_path = original_path
    database._schema_verified = False
    database._schema_verified_path = None
    db.close()
    os.close(db_fd)
    try:
        os.unlink(db_path)
    except OSError:
        pass


def test_create_user_with_platform(patched_db):
    """验证 create_user 接受并保存 platform 参数"""
    import uuid
    from auth import create_user, get_user_by_id
    test_username = f'test_fb_{uuid.uuid4().hex[:8]}'
    user = create_user(test_username, 'test', 'user', 'TestFB', platform='fb')
    assert user is not None
    assert user['platform'] == 'fb'
    # cleanup
    c = patched_db
    c.execute("DELETE FROM users WHERE username=?", (test_username,))
    c.commit()


def test_get_user_by_id_returns_platform(patched_db):
    """验证 get_user_by_id 返回 platform 字段"""
    from auth import get_user_by_id, create_user
    import uuid
    test_username = f'test_gubip_{uuid.uuid4().hex[:8]}'
    user = create_user(test_username, 'x', 'user', 'Test')
    fetched = get_user_by_id(user['id'])
    assert 'platform' in fetched, f"缺少 platform: {list(fetched.keys())}"
    assert fetched['platform'] == 'gg'
    c = patched_db
    c.execute("DELETE FROM users WHERE username=?", (test_username,))
    c.commit()


def test_list_users_supports_platform_filter(patched_db):
    """验证 list_users 支持按 platform 筛选"""
    from auth import list_users, create_user
    import uuid
    test_username = f'test_list_{uuid.uuid4().hex[:8]}'
    create_user(test_username, 'test', 'user', 'List', platform='fb')
    result = list_users(platform='fb')
    usernames = [u['username'] for u in result['users']]
    assert test_username in usernames
    result_gg = list_users(platform='gg')
    usernames_gg = [u['username'] for u in result_gg['users']]
    assert test_username not in usernames_gg
    c = patched_db
    c.execute("DELETE FROM users WHERE username=?", (test_username,))
    c.commit()


def test_login_returns_platform(app, client):
    """验证登录响应和 /api/auth/me 返回 platform 字段"""
    import uuid
    test_username = f'test_login_{uuid.uuid4().hex[:8]}'
    # 注册新用户
    client.post("/api/auth/register", json={
        "username": test_username, "password": "test123"
    })
    # 登录
    resp = client.post("/api/auth/login", json={
        "username": test_username, "password": "test123"
    })
    data = resp.get_json()
    assert 'user' in data
    assert 'platform' in data['user'], f"登录响应缺少 platform: {data['user']}"
    assert data['user']['platform'] == 'gg'  # 默认

    # /api/auth/me
    token = data['access_token']
    resp2 = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
    me = resp2.get_json()
    assert 'platform' in me['user'], f"/api/auth/me 缺少 platform: {me['user']}"
