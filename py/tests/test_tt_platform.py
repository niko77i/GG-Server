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
