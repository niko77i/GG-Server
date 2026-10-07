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

# conftest 的 app fixture 用 15 字节的 "test-secret-key" 作为 JWT 密钥，PyJWT 会为
# 每一次编解码抛 InsecureKeyLengthWarning。这是测试夹具的既有产物、非本文件引入，
# 按类精确静音，保持测试输出干净（只屏蔽这一种，别的 warning 仍会显示）。
pytestmark = pytest.mark.filterwarnings("ignore::jwt.warnings.InsecureKeyLengthWarning")


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


# ==================== FB 像素 / 像素BM 归属收口（B-6 / B-7） ====================
#
# 缺陷：pixels / pixel-bms 两族端点此前只卡「是不是 FB 平台用户」，不卡归属 ——
# 任何 FB 用户按 id 就能改/删**别人**的像素、软删他人 BM、往他人 BM 塞像素、
# 读他人 BM 的像素、列出全库 BM 选项。本类逐个钉住每个收口点。
#
# 归属解析：像素无 owner 列，归属看父表 `fb_pixel_bms.owner_id`（见下方 helper）。
# 每个越权用例都以**已登录的另一个 FB 用户**身份发起（不是匿名），才是「越权」而非「未登录」。


def _fb_user(client, username, role="user", platform="fb"):
    """注册 → 改写 role/platform → 登录，返回 (headers, user_id)。"""
    client.post("/api/auth/register", json={"username": username, "password": "test123"})
    db = database.get_db()
    db.execute("UPDATE users SET role=?, platform=? WHERE username=?",
               (role, platform, username))
    db.commit()
    uid = db.execute("SELECT id FROM users WHERE username=?", (username,)).fetchone()["id"]
    db.close()
    resp = client.post("/api/auth/login", json={"username": username, "password": "test123"})
    return {"Authorization": f"Bearer {resp.get_json().get('access_token', '')}"}, uid


def _mk_pixel_bm(db, owner_id, bm_id, name="像素BM"):
    db.execute("INSERT INTO fb_pixel_bms(name, bm_id, owner_id) VALUES(?,?,?)",
               (name, bm_id, owner_id))
    db.commit()
    return db.execute("SELECT id FROM fb_pixel_bms WHERE bm_id=?", (bm_id,)).fetchone()["id"]


def _mk_pixel(db, pixel_bm_id, pixel_id, name="像素"):
    db.execute("INSERT INTO fb_pixels(pixel_bm_id, pixel_name, pixel_id) VALUES(?,?,?)",
               (pixel_bm_id, name, pixel_id))
    db.commit()
    return db.execute("SELECT id FROM fb_pixels WHERE pixel_id=?", (pixel_id,)).fetchone()["id"]


def _seed_two_users(client, tag):
    """造 A、B 两个 FB 普通用户；各带一个像素BM + 一条像素。返回各 id 与 A 的认证头。"""
    a_hdr, a_id = _fb_user(client, f"{tag}_a")
    b_hdr, b_id = _fb_user(client, f"{tag}_b")
    db = database.get_db()
    a_bm = _mk_pixel_bm(db, a_id, f"{tag}-A-BM", "A的BM")
    b_bm = _mk_pixel_bm(db, b_id, f"{tag}-B-BM", "B的BM")
    a_px = _mk_pixel(db, a_bm, f"{tag}-A-PX", "A的像素")
    b_px = _mk_pixel(db, b_bm, f"{tag}-B-PX", "B的像素")
    db.close()
    return dict(a_hdr=a_hdr, a_id=a_id, b_hdr=b_hdr, b_id=b_id,
                a_bm=a_bm, b_bm=b_bm, a_px=a_px, b_px=b_px)


def _px_name(db, pxid):
    return db.execute("SELECT pixel_name FROM fb_pixels WHERE id=?", (pxid,)).fetchone()["pixel_name"]


class TestFbPixelOwnershipClosure:
    """B-6 / B-7：pixels / pixel-bms 两族补齐归属校验（跨租户越权收口）。"""

    # ---------------- 像素写：他人 ⇒ 403，本人 ⇒ 200 ----------------

    def test_user_cannot_update_others_pixel(self, client):
        s = _seed_two_users(client, "t_pxupd")
        resp = client.put(f"/api/fb/pixels/{s['b_px']}",
                          json={"pixel_name": "被改名"}, headers=s["a_hdr"])
        assert resp.status_code == 403
        db = database.get_db()
        assert _px_name(db, s["b_px"]) == "B的像素"   # 证伪：去掉校验会 200 且真改了
        db.close()

    def test_user_can_update_own_pixel(self, client):
        s = _seed_two_users(client, "t_pxupd_ok")
        resp = client.put(f"/api/fb/pixels/{s['a_px']}",
                          json={"pixel_name": "我改了"}, headers=s["a_hdr"])
        assert resp.status_code == 200
        db = database.get_db()
        assert _px_name(db, s["a_px"]) == "我改了"    # 防「一律 403」的过度收口
        db.close()

    def test_user_cannot_delete_others_pixel(self, client):
        s = _seed_two_users(client, "t_pxdel")
        resp = client.delete(f"/api/fb/pixels/{s['b_px']}", headers=s["a_hdr"])
        assert resp.status_code == 403
        db = database.get_db()
        assert db.execute("SELECT 1 FROM fb_pixels WHERE id=?", (s["b_px"],)).fetchone() is not None
        db.close()

    # ---------------- 像素BM 写：他人 ⇒ 403，本人 ⇒ 200 ----------------

    def test_user_cannot_update_others_pixel_bm(self, client):
        s = _seed_two_users(client, "t_bmupd")
        resp = client.put(f"/api/fb/pixel-bms/{s['b_bm']}",
                          json={"name": "被改名"}, headers=s["a_hdr"])
        assert resp.status_code == 403
        db = database.get_db()
        name = db.execute("SELECT name FROM fb_pixel_bms WHERE id=?", (s["b_bm"],)).fetchone()["name"]
        db.close()
        assert name == "B的BM"

    def test_user_can_update_own_pixel_bm(self, client):
        s = _seed_two_users(client, "t_bmupd_ok")
        resp = client.put(f"/api/fb/pixel-bms/{s['a_bm']}",
                          json={"name": "我改了"}, headers=s["a_hdr"])
        assert resp.status_code == 200
        db = database.get_db()
        name = db.execute("SELECT name FROM fb_pixel_bms WHERE id=?", (s["a_bm"],)).fetchone()["name"]
        db.close()
        assert name == "我改了"

    def test_user_cannot_delete_others_pixel_bm(self, client):
        s = _seed_two_users(client, "t_bmdel")
        resp = client.delete(f"/api/fb/pixel-bms/{s['b_bm']}", headers=s["a_hdr"])
        assert resp.status_code == 403
        db = database.get_db()
        deleted = db.execute("SELECT deleted_at FROM fb_pixel_bms WHERE id=?",
                             (s["b_bm"],)).fetchone()["deleted_at"]
        db.close()
        assert deleted is None                        # 未被软删

    def test_user_can_delete_own_pixel_bm(self, client):
        s = _seed_two_users(client, "t_bmdel_ok")
        resp = client.delete(f"/api/fb/pixel-bms/{s['a_bm']}", headers=s["a_hdr"])
        assert resp.status_code == 200
        db = database.get_db()
        deleted = db.execute("SELECT deleted_at FROM fb_pixel_bms WHERE id=?",
                             (s["a_bm"],)).fetchone()["deleted_at"]
        db.close()
        assert deleted is not None

    # ---------------- 往他人 BM 塞像素 ----------------

    def test_user_cannot_create_pixel_in_others_bm(self, client):
        s = _seed_two_users(client, "t_pxnew")
        resp = client.post(f"/api/fb/pixel-bms/{s['b_bm']}/pixels",
                           json={"pixel_name": "塞进去", "pixel_id": "9000001"},
                           headers=s["a_hdr"])
        assert resp.status_code == 403
        db = database.get_db()
        assert db.execute("SELECT 1 FROM fb_pixels WHERE pixel_id='9000001'").fetchone() is None
        db.close()

    def test_user_can_create_pixel_in_own_bm(self, client):
        s = _seed_two_users(client, "t_pxnew_ok")
        resp = client.post(f"/api/fb/pixel-bms/{s['a_bm']}/pixels",
                           json={"pixel_name": "我的新像素", "pixel_id": "9000002"},
                           headers=s["a_hdr"])
        assert resp.status_code == 200
        db = database.get_db()
        assert db.execute("SELECT 1 FROM fb_pixels WHERE pixel_id='9000002'").fetchone() is not None
        db.close()

    # ---------------- 读：list / options ----------------

    def test_user_cannot_list_others_bm_pixels(self, client):
        s = _seed_two_users(client, "t_pxlist")
        others = client.get(f"/api/fb/pixel-bms/{s['b_bm']}/pixels", headers=s["a_hdr"]).get_json()["data"]
        assert others == []                          # 去掉过滤时会返回 B 的像素
        mine = client.get(f"/api/fb/pixel-bms/{s['a_bm']}/pixels", headers=s["a_hdr"]).get_json()["data"]
        assert {p["pixel_id"] for p in mine} == {"t_pxlist-A-PX"}   # 非空，防「一律空」

    def test_pixel_bm_options_scoped_to_owner(self, client):
        s = _seed_two_users(client, "t_opt")
        opts = client.get("/api/fb/pixel-bms/options", headers=s["a_hdr"]).get_json()["data"]
        ids = {o["bm_id"] for o in opts}
        assert ids == {"t_opt-A-BM"}                 # 不含 B 的；去掉收窄时会含 B 的
        assert ids

    # ---------------- 契约：行不存在时行为保持既有（不因新校验变 404/500） ----------------

    def test_missing_rows_keep_existing_contract(self, client):
        """写端点对「行不存在」的既有语义必须保留（这是刻意不动的口径）。

        本改动只新增 403 一条路径：`existing` 为 None 时不拦，落回既有行为 ——
        UPDATE/DELETE 0 行仍 200；往不存在 BM 塞像素仍落回外键报错 → 400。
        若将来有人把校验前移成「先查行、无行即 404」，这几条会立刻变红。
        """
        hdr, _ = _fb_user(client, "t_missing")
        assert client.put("/api/fb/pixel-bms/999999", json={"name": "x"},
                          headers=hdr).status_code == 200
        assert client.delete("/api/fb/pixel-bms/999999", headers=hdr).status_code == 200
        assert client.put("/api/fb/pixels/999999", json={"pixel_name": "x"},
                          headers=hdr).status_code == 200
        assert client.delete("/api/fb/pixels/999999", headers=hdr).status_code == 200
        assert client.post("/api/fb/pixel-bms/999999/pixels",
                           json={"pixel_name": "x", "pixel_id": "9000009"},
                           headers=hdr).status_code == 400
        assert client.get("/api/fb/pixel-bms/999999/pixels",
                          headers=hdr).get_json()["data"] == []

    # ---------------- 对照组：跨用户角色仍可操作全部 ----------------

    def test_cross_user_role_can_operate_others_objects(self, client):
        """developer/admin/户管 属 CROSS_USER_ROLES，必须仍能操作他人对象（既有行为不退化）。"""
        s = _seed_two_users(client, "t_cross")
        hg, _ = _fb_user(client, "t_cross_hg", role="huguan", platform="gg")

        assert client.put(f"/api/fb/pixel-bms/{s['b_bm']}",
                          json={"name": "户管改的BM"}, headers=hg).status_code == 200
        assert client.put(f"/api/fb/pixels/{s['b_px']}",
                          json={"pixel_name": "户管改的像素"}, headers=hg).status_code == 200
        assert client.post(f"/api/fb/pixel-bms/{s['b_bm']}/pixels",
                           json={"pixel_name": "户管加的", "pixel_id": "9000003"},
                           headers=hg).status_code == 200

        lst = client.get(f"/api/fb/pixel-bms/{s['b_bm']}/pixels", headers=hg)
        assert lst.status_code == 200
        assert {p["pixel_id"] for p in lst.get_json()["data"]} == {"t_cross-B-PX", "9000003"}

        assert client.delete(f"/api/fb/pixels/{s['b_px']}", headers=hg).status_code == 200

        opts = client.get("/api/fb/pixel-bms/options", headers=hg).get_json()["data"]
        assert {o["bm_id"] for o in opts} == {"t_cross-A-BM", "t_cross-B-BM"}   # 跨用户看全部


# ==================== E-11：fb_routes 异常文本收口（数据流） ====================
#
# 结论文件的两个 Critical 组：
#   ① 8 处 `except Exception as e: return err(str(e))` —— 直出 sqlite 的
#      IntegrityError 原文（UNIQUE / NOT NULL / FOREIGN KEY + schema 列名）。
#   ② `sheets_sync_log.error_msg` 落 `str(e)[:500]`，再由两个 GET 与
#      `failed[].error` 回进响应体。
#
# 本组逐个点名，用**真实异常**驱动：去掉修复，响应体即回显英文库原文 ⇒ 转红。

_FB_LEAK_MARKERS = ("constraint failed", "UNIQUE", "NOT NULL", "FOREIGN KEY",
                    "IntegrityError", "sqlite3", "Traceback", "HttpError",
                    "sheets.googleapis.com")


def _assert_no_fb_leak(target):
    raw = target if isinstance(target, str) else target.get_data(as_text=True)
    for marker in _FB_LEAK_MARKERS:
        assert marker not in raw, f"响应体泄露内部细节 {marker!r}: {raw[:300]!r}"


class _InlineThread:
    """把 `threading.Thread(...).start()` 就地跑完（fb 后台写表线程同步化）。"""

    def __init__(self, target=None, daemon=None, args=(), kwargs=None):
        self._target = target
        self._args = args
        self._kwargs = kwargs or {}

    def start(self):
        self._target(*self._args, **self._kwargs)

    def join(self, timeout=None):
        pass


def _boom_fb_sheets(*_a, **_k):
    import google_sheets_service as gs
    raise gs.GoogleSheetsServiceError(
        "读取工作表失败: <HttpError 404> https://sheets.googleapis.com/v4/spreadsheets/FB-SHEET")


class TestE11FbDirectWriteSitesSanitized:
    """① 8 处直出站点：以 `POST /api/fb/bms/create` 撞 UNIQUE 为真实驱动。

    `fb_bms.bm_id` 有 UNIQUE 约束 ⇒ 第二次同 bm_id 必抛 `sqlite3.IntegrityError(
    "UNIQUE constraint failed: fb_bms.bm_id")`，正是改前直出的原文形态。
    """

    def test_create_bm_duplicate_returns_exists_message(self, client, caplog):
        """撞 UNIQUE 必须回「已存在」这个用户可操作的信号，而非笼统的「操作失败」。

        `fb_bms.bm_id` 有 UNIQUE 约束 ⇒ 第二次同 bm_id 抛
        `sqlite3.IntegrityError("UNIQUE constraint failed: fb_bms.bm_id")`。
        （收口前直出的是库原文，收口后一度退化成「操作失败」—— 这一条把
        「重复键 ⇒ 已存在」的映射钉住，去掉映射即变红。）
        """
        import logging
        from routes import fb_routes
        hdr, _ = _fb_user(client, "e11_bm")

        first = client.post("/api/fb/bms/create",
                            json={"name": "E11BM", "bm_id": "9000011"}, headers=hdr)
        assert first.status_code == 200, first.get_data(as_text=True)[:200]

        with caplog.at_level(logging.ERROR, logger="gg-server"):
            dup = client.post("/api/fb/bms/create",
                              json={"name": "E11BM2", "bm_id": "9000011"}, headers=hdr)

        assert dup.status_code == 400
        msg = dup.get_json()["error"]
        assert "已存在" in msg, f"撞 UNIQUE 没回「已存在」：{msg!r}"
        assert msg != fb_routes._FB_DB_FAILED_MSG
        assert "BM" in msg and "9000011" in msg, f"文案未指明是哪个 BM ID：{msg!r}"
        _assert_no_fb_leak(dup)
        assert "UNIQUE constraint failed: fb_bms.bm_id" in caplog.text, "异常详情没进日志"

    def test_create_account_duplicate_returns_exists_message(self, client):
        """同族另一站点（账户 create）：`fb_accounts.account_id` 也是 UNIQUE。"""
        from routes import fb_routes
        hdr, _ = _fb_user(client, "e11_acc")
        assert client.post("/api/fb/accounts/create",
                           json={"name": "E11A1", "account_id": "8100011"},
                           headers=hdr).status_code == 200
        dup = client.post("/api/fb/accounts/create",
                          json={"name": "E11A2", "account_id": "8100011"}, headers=hdr)
        assert dup.status_code == 400
        msg = dup.get_json()["error"]
        assert "已存在" in msg and "账户" in msg and "8100011" in msg, msg
        assert msg != fb_routes._FB_DB_FAILED_MSG
        _assert_no_fb_leak(dup)

    def test_create_pixel_duplicate_returns_exists_message(self, client):
        """同族另一站点（像素 create）：`fb_pixels.pixel_id` 也是 UNIQUE。"""
        from routes import fb_routes
        hdr, uid = _fb_user(client, "e11_px")
        db = database.get_db()
        bm = _mk_pixel_bm(db, uid, "8200011")
        db.close()
        assert client.post(f"/api/fb/pixel-bms/{bm}/pixels",
                           json={"pixel_name": "P1", "pixel_id": "8300011"},
                           headers=hdr).status_code == 200
        dup = client.post(f"/api/fb/pixel-bms/{bm}/pixels",
                          json={"pixel_name": "P2", "pixel_id": "8300011"}, headers=hdr)
        assert dup.status_code == 400
        msg = dup.get_json()["error"]
        assert "已存在" in msg and "像素" in msg and "8300011" in msg, msg
        assert msg != fb_routes._FB_DB_FAILED_MSG
        _assert_no_fb_leak(dup)

    def test_non_unique_integrity_error_still_fixed_text(self, client, caplog):
        """对照组：非 UNIQUE 的完整性错误（这里是 FK 失败）仍是固定文案。

        往**不存在**的像素BM 塞像素 ⇒ `FOREIGN KEY constraint failed`（不是重复键）。
        若把「所有 IntegrityError」都当成「已存在」误报，这一条即变红。
        """
        import logging
        from routes import fb_routes
        hdr, _ = _fb_user(client, "e11_fk")
        with caplog.at_level(logging.ERROR, logger="gg-server"):
            resp = client.post("/api/fb/pixel-bms/999999/pixels",
                               json={"pixel_name": "P", "pixel_id": "8400011"},
                               headers=hdr)
        assert resp.status_code == 400
        msg = resp.get_json()["error"]
        assert msg == fb_routes._FB_DB_FAILED_MSG, f"FK 失败被误报成：{msg!r}"
        assert "已存在" not in msg
        _assert_no_fb_leak(resp)
        assert "FOREIGN KEY constraint failed" in caplog.text, "FK 详情应落日志"

    def test_create_pixel_bm_duplicate_returns_fixed_text(self, client):
        """同族站点（像素BM 的 create）：同一形态、另一端点，防「只修一处」。"""
        from routes import fb_routes
        hdr, _ = _fb_user(client, "e11_pbm")
        assert client.post("/api/fb/pixel-bms/create",
                           json={"name": "E11PBM", "bm_id": "9000012"},
                           headers=hdr).status_code == 200
        dup = client.post("/api/fb/pixel-bms/create",
                          json={"name": "E11PBM2", "bm_id": "9000012"}, headers=hdr)
        assert dup.status_code == 400
        assert dup.get_json()["error"] == fb_routes._FB_DB_FAILED_MSG
        _assert_no_fb_leak(dup)


class TestE11FbSheetsSyncLogSink:
    """② `sheets_sync_log.error_msg` 是「异常落库 → 读取端点回出」的中间落点。"""

    def _seed_log_and_records(self, client, uid, log_id_out=None):
        db = database.get_db()
        db.execute(
            "INSERT INTO sheets_sync_log (user_id, product_name, line_name, report_date, "
            "spreadsheet_id, status, rows_json) VALUES (?,?,?,?,?,'failed','[]')",
            (uid, "E11产品", "E11线", "2026-01-01", "FB-SHEET"))
        log_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]
        db.execute(
            "INSERT INTO fb_ad_reports (user_id, product_name, line_name, report_date, "
            "account_name, account_id, cost) VALUES (?,?,?,?,?,?,?)",
            (uid, "E11产品", "E11线", "2026-01-01", "户A", "111", 1.0))
        db.commit()
        db.close()
        return log_id

    def test_retry_sync_by_id_sanitizes_response_and_db(self, client, monkeypatch, caplog):
        import logging
        import google_sheets_service as gs
        from routes import fb_routes

        hdr, uid = _fb_user(client, "e11_retry")
        log_id = self._seed_log_and_records(client, uid)
        monkeypatch.setattr(gs, "upsert_fb_reports", _boom_fb_sheets)

        with caplog.at_level(logging.ERROR, logger="gg-server"):
            resp = client.post("/api/fb/reports/retry-sync",
                               json={"id": log_id}, headers=hdr)

        assert resp.status_code == 500
        assert resp.get_json()["error"] == "重试失败，详情见服务端日志", (
            f"重试失败仍直出异常原文：{resp.get_json()['error']!r}")
        _assert_no_fb_leak(resp)

        # 读取端点（sync-status/<id> 与 last-sync）都不得把原文回出来
        st = client.get(f"/api/fb/reports/sync-status/{log_id}", headers=hdr)
        assert st.get_json()["error_msg"] == fb_routes._FB_SHEETS_FAILED_MSG, (
            f"error_msg 落进了异常原文：{st.get_json()['error_msg']!r}")
        _assert_no_fb_leak(st)
        last = client.get("/api/fb/reports/last-sync", headers=hdr)
        _assert_no_fb_leak(last)
        assert "sheets.googleapis.com" in caplog.text, "异常详情没进日志"

    def test_batch_retry_failed_entry_sanitized(self, client, monkeypatch, caplog):
        """批量重试的 `failed[].error` 直接进响应体 —— 同样必须是固定文案。"""
        import logging
        import google_sheets_service as gs
        from routes import fb_routes

        hdr, uid = _fb_user(client, "e11_batch")
        self._seed_log_and_records(client, uid)
        monkeypatch.setattr(gs, "upsert_fb_reports", _boom_fb_sheets)

        with caplog.at_level(logging.ERROR, logger="gg-server"):
            resp = client.post("/api/fb/reports/retry-sync", json={}, headers=hdr)

        body = resp.get_json()
        assert body["retried"] == 0 and body["failed"], f"未走到失败分支：{body!r}"
        assert body["failed"][0]["error"] == fb_routes._FB_SHEETS_FAILED_MSG, (
            f"failed[].error 直出异常原文：{body['failed'][0]['error']!r}")
        _assert_no_fb_leak(resp)
        assert "sheets.googleapis.com" in caplog.text, "异常详情没进日志"

    def test_async_write_failure_sanitized(self, client, monkeypatch, caplog):
        """`_schedule_fb_sheets_write` 的后台线程落点（extract/save 起的那条）。"""
        import logging
        import main as main_mod
        import google_sheets_service as gs
        from routes import fb_routes

        monkeypatch.setattr(fb_routes.threading, "Thread", _InlineThread)
        monkeypatch.setattr("time.sleep", lambda _s: None)
        monkeypatch.setattr(gs, "upsert_fb_reports", _boom_fb_sheets)

        hdr, uid = _fb_user(client, "e11_async")
        with caplog.at_level(logging.ERROR, logger="gg-server"):
            resp = client.post("/api/fb/extract/save",
                               json={"product_name": "E11异步", "line_name": "线",
                                     "report_date": "2026-02-02",
                                     "records": [{"account_name": "户B", "account_id": "222",
                                                  "cost": 1.0}]},
                               headers=hdr)
        assert resp.status_code == 200, resp.get_data(as_text=True)[:200]
        log_id = resp.get_json()["sync_log_id"]

        st = client.get(f"/api/fb/reports/sync-status/{log_id}", headers=hdr)
        assert st.get_json()["error_msg"] == fb_routes._FB_SHEETS_FAILED_MSG, (
            f"后台写失败把异常原文落进了 error_msg：{st.get_json()['error_msg']!r}")
        _assert_no_fb_leak(st)
        assert "sheets.googleapis.com" in caplog.text, "异常详情没进日志"


# ==================== FB 账户面板批量能力（Task 1：批量查户） ====================
#
# 形状照 GG 的 `main.accounts_batch_lookup`，但**一律带 owner 过滤** ——
# GG 那个端点没有 owner 条件（遗留清单 A8，已登记的越权），FB 版不复制该缺陷。


def _mk_fb_bm(db, owner_id, bm_id, name="BM"):
    """建一个 FB BM，返回其主键 id（fb_account_bm.bm_id 指的是这个）。"""
    db.execute("INSERT INTO fb_bms(name, bm_id, owner_id) VALUES(?,?,?)",
               (name, bm_id, owner_id))
    pk = db.execute("SELECT id FROM fb_bms WHERE bm_id=?", (bm_id,)).fetchone()["id"]
    db.commit()
    return pk


def _mk_fb_account(db, owner_id, account_id, name="账户", bm_pk=None, is_primary=1):
    """建一个 FB 账户；给了 bm_pk 则关联为（主）BM。返回账户主键 id。"""
    db.execute("INSERT INTO fb_accounts(name, account_id, owner_id) VALUES(?,?,?)",
               (name, account_id, owner_id))
    acc_pk = db.execute("SELECT id FROM fb_accounts WHERE account_id=?",
                        (account_id,)).fetchone()["id"]
    if bm_pk is not None:
        db.execute("INSERT INTO fb_account_bm(account_id, bm_id, is_primary) VALUES(?,?,?)",
                   (acc_pk, bm_pk, is_primary))
    db.commit()
    return acc_pk


class TestValidPkInt64:
    """`_valid_pk_int64` —— 主键闸门助手（Task 2 复用）。

    这些值随后原样交给 sqlite3 参数绑定：超上界时 Python 的 int() 能解析，
    绑定处却抛 OverflowError（内建，非 sqlite3 的）⇒ 500 + 英文异常原文。
    """

    def test_accepts_plain_ascii_digits(self):
        from routes import fb_routes
        assert fb_routes._valid_pk_int64("123") == 123
        assert fb_routes._valid_pk_int64(" 42 ") == 42
        assert fb_routes._valid_pk_int64(7) == 7

    def test_accepts_int64_max_boundary(self):
        from routes import fb_routes
        assert fb_routes._valid_pk_int64(str(2 ** 63 - 1)) == 2 ** 63 - 1

    def test_rejects_out_of_range_before_binding(self):
        """超 int64 上界必须在闸门就返回 None，不能漏到绑定处变 500。"""
        from routes import fb_routes
        assert fb_routes._valid_pk_int64(str(2 ** 63)) is None
        assert fb_routes._valid_pk_int64("9" * 40) is None

    def test_rejects_non_decimal_forms(self):
        from routes import fb_routes
        for bad in (True, False, -1, "1.0", "1e3", "0x10", "１２３", "", "  ", None,
                    "abc", "1; DROP TABLE fb_accounts"):
            assert fb_routes._valid_pk_int64(bad) is None, f"未拦下：{bad!r}"


class TestFbBatchLookup:
    """POST /api/fb/accounts/batch-lookup —— 批量查户。

    夹具用本文件既有的 `_fb_user(client, username, role, platform)` helper 现造
    用户（本文件没有 fb_user_headers 之类的 fixture）。
    """

    def test_batch_lookup_finds_own_account_with_bm_name(self, client):
        """自己的账户查得到，且带主 BM 名。"""
        hdr, uid = _fb_user(client, "t_lk_own")
        db = database.get_db()
        bm = _mk_fb_bm(db, uid, "T-LK-BM", "测试BM")
        _mk_fb_account(db, uid, "LOOKUP-1", "我的账户", bm_pk=bm)
        db.close()

        resp = client.post("/api/fb/accounts/batch-lookup",
                           json={"account_ids": ["LOOKUP-1"]}, headers=hdr)
        data = resp.get_json()
        assert data["success"] is True
        assert [f["account_id"] for f in data["found"]] == ["LOOKUP-1"]
        assert data["not_found"] == []
        assert data["found"][0]["bm_name"] == "测试BM"
        assert data["found"][0]["owner_id"] == uid

    def test_batch_lookup_does_not_leak_other_users_account(self, client):
        """**归属隔离**：别人的账户查不到，且落在 not_found 里。"""
        a_hdr, _ = _fb_user(client, "t_lk_a")
        _, b_id = _fb_user(client, "t_lk_b")
        db = database.get_db()
        bm_b = _mk_fb_bm(db, b_id, "T-LK-B-BM", "B的BM")
        _mk_fb_account(db, b_id, "OTHERS-1", "B的账户", bm_pk=bm_b)
        db.close()

        resp = client.post("/api/fb/accounts/batch-lookup",
                           json={"account_ids": ["OTHERS-1"]}, headers=a_hdr)
        data = resp.get_json()
        assert data["found"] == []
        assert data["not_found"] == ["OTHERS-1"]

    def test_batch_lookup_cross_user_role_sees_all(self, client):
        """**对照腿**：跨用户角色能查到别人的（防「一律看不见」的过度收口）。"""
        _, b_id = _fb_user(client, "t_lk_c")
        dev_hdr, _ = _fb_user(client, "t_lk_dev", role="developer", platform="fb")
        db = database.get_db()
        bm_b = _mk_fb_bm(db, b_id, "T-LK-C-BM", "C的BM")
        _mk_fb_account(db, b_id, "OTHERS-1", "C的账户", bm_pk=bm_b)
        db.close()

        resp = client.post("/api/fb/accounts/batch-lookup",
                           json={"account_ids": ["OTHERS-1"]}, headers=dev_hdr)
        assert [f["account_id"] for f in resp.get_json()["found"]] == ["OTHERS-1"]

    def test_batch_lookup_rejects_empty_and_non_list(self, client):
        hdr, _ = _fb_user(client, "t_lk_bad")
        for body in ({"account_ids": []}, {"account_ids": "x"}, {}):
            resp = client.post("/api/fb/accounts/batch-lookup", json=body, headers=hdr)
            assert resp.status_code == 400, f"未拦下：{body!r}"
