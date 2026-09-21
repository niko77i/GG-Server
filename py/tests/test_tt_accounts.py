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
    """GG 代理应复制到 platform='tt'（INSERT OR IGNORE，冲突跳过）。"""
    db = database.get_db()
    # 确保外键引用的用户存在（agents.owner_id → users.id；临时库无用户）
    db.execute("INSERT OR IGNORE INTO users(id, username, password, role) VALUES(1, 'dev', 'x', 'developer')")
    db.execute("INSERT OR IGNORE INTO users(id, username, password, role) VALUES(2, 'user2', 'x', 'user')")
    # 清掉迁移标记，插入 GG 代理（owner_id=2，避免与复制目标 owner_id=1 的 UNIQUE(name, owner_id) 冲突），手动调用复制函数
    db.execute("DELETE FROM config WHERE key='migrated_copy_agents_to_tt'")
    db.execute("INSERT OR IGNORE INTO agents(name, owner_id, platform) VALUES(?,?, 'gg')",
               ("卡尔", 2))
    db.commit()
    database._copy_gg_agents_to_tt(db)
    cnt = db.execute(
        "SELECT COUNT(*) FROM agents WHERE name='卡尔' AND platform='tt'"
    ).fetchone()[0]
    assert cnt == 1
    db.close()
