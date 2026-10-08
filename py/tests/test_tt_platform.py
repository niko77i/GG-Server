"""TT 平台数据库表结构测试。"""
import os
import sys
import tempfile
import sqlite3

_py_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _py_dir not in sys.path:
    sys.path.insert(0, _py_dir)

import database  # noqa: E402


def _fresh_schema_conn():
    """创建干净的临时 SQLite 连接，复刻 get_db 的建表 + 列迁移流程。"""
    fd, db_path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    database._ensure_schema(conn)
    database._ensure_columns(conn)
    conn.commit()
    return conn, db_path


def test_tt_tables_exist():
    conn, db_path = _fresh_schema_conn()

    tables = {r["name"] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    for t in ["tt_bcs", "tt_products", "tt_product_runners",
              "tt_packages", "tt_delist_checks", "tt_product_assets"]:
        assert t in tables, f"缺少表 {t}"
    conn.close()
    os.unlink(db_path)


def test_tt_packages_has_type_column():
    conn, db_path = _fresh_schema_conn()

    cols = {r[1] for r in conn.execute("PRAGMA table_info(tt_packages)")}
    for c in ["id", "product_id", "type", "series_name", "package_name",
              "url", "status", "created_at", "updated_at"]:
        assert c in cols, f"tt_packages 缺少列 {c}"
    conn.close()
    os.unlink(db_path)


def test_tt_products_has_bc_id_column():
    conn, db_path = _fresh_schema_conn()

    cols = {r[1] for r in conn.execute("PRAGMA table_info(tt_products)")}
    for c in ["id", "product_name", "kpi", "region", "status", "bc_id",
              "sales_person_id", "agency_ratio", "customer", "owner_id",
              "is_archived", "created_at", "updated_at"]:
        assert c in cols, f"tt_products 缺少列 {c}"
    conn.close()
    os.unlink(db_path)


def test_copy_gg_options_to_tt():
    conn, db_path = _fresh_schema_conn()

    # 预置一条 gg 地区，验证迁移复制出 tt 行
    conn.execute("INSERT OR IGNORE INTO regions(name, timezone, platform) VALUES('巴西','','gg')")
    conn.commit()
    database._copy_gg_options_to_tt(conn)

    rows = conn.execute("SELECT name FROM regions WHERE platform='tt'").fetchall()
    names = {r["name"] for r in rows}
    assert "巴西" in names, "TT 地区选项未从 GG 复制"
    conn.close()
    os.unlink(db_path)


def test_tt_headers_creates_tt_user(client, tt_headers):
    """tt_headers fixture 应注册并改成 tt 平台用户后登录成功。"""
    resp = client.get('/api/auth/me', headers=tt_headers)
    assert resp.status_code == 200
    body = resp.get_json()
    # 兼容 me 接口返回结构：可能是 {user: {...}} 或直接平铺
    user = body.get('user', body)
    assert user['platform'] == 'tt'


def test_require_platform_tt_blocks_gg_user(app, monkeypatch):
    """gg 用户调用 require_platform('tt') 应被拦截返回 403。"""
    import routes.decorators as dec
    # require_platform 内部从 get_jwt_identity() 取 uid、再 auth.get_user_by_id() 取用户。
    # 直接 patch 这两个引用，模拟一个 platform='gg' 的已登录用户，验证 403 分支。
    monkeypatch.setattr(dec, 'get_jwt_identity', lambda: '1')
    monkeypatch.setattr(dec.auth, 'get_user_by_id', lambda uid: {'id': 1, 'role': 'user', 'platform': 'gg'})
    with app.app_context():
        resp = dec.require_platform('tt')
    assert resp is not None
    assert resp[1] == 403


def test_tt_accounts_has_account_type_column():
    conn, db_path = _fresh_schema_conn()
    cols = {r[1] for r in conn.execute("PRAGMA table_info(tt_accounts)").fetchall()}
    assert "account_type" in cols
    conn.close()
    os.unlink(db_path)


def test_add_column_if_missing_returns_whether_added():
    """返回值必须区分「加了」与「本来就有」——回填只在前者执行。"""
    conn, db_path = _fresh_schema_conn()
    assert database._add_column_if_missing(
        conn, "tt_accounts", "account_type", "account_type TEXT DEFAULT ''") is False
    assert database._add_column_if_missing(
        conn, "tt_accounts", "_tmp_probe", "_tmp_probe TEXT DEFAULT ''") is True
    conn.close()
    os.unlink(db_path)


def test_account_type_backfill_happens_once():
    """存量行回填成加白户；**列已存在时不再覆盖**（否则户管改名会被打回）。"""
    conn, db_path = _fresh_schema_conn()
    conn.execute("INSERT INTO tt_accounts(name, advertiser_id) VALUES('a','111')")
    conn.execute("UPDATE tt_accounts SET account_type='' WHERE advertiser_id='111'")
    conn.commit()
    # 再跑一次列迁移：列已存在 ⇒ 不得回填
    database._ensure_columns(conn)
    got = conn.execute(
        "SELECT account_type FROM tt_accounts WHERE advertiser_id='111'").fetchone()[0]
    assert got == "", f"列已存在时不该覆盖，实际={got!r}"
    conn.close()
    os.unlink(db_path)
