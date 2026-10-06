"""写表失败统一治理 —— 基建测试。

设计见 docs/superpowers/specs/2026-10-06-sheet-write-failure-governance-design.md
"""
import pytest

import database


def test_sheet_write_log_table_shape(client):
    """表必须存在，且 UNIQUE 约束落在 (user_id, target, business_key)。"""
    db = database.get_db()
    cols = {r[1] for r in db.execute("PRAGMA table_info(sheet_write_log)").fetchall()}
    db.close()
    assert {
        "id", "user_id", "platform", "target", "business_key", "status",
        "error_msg", "payload_json", "snapshot_json", "created_at",
        "updated_at", "settled_at",
    } <= cols


def test_sheet_write_log_unique_key(client):
    """同 (user_id, target, business_key) 只能有一行 —— upsert 语义的前提。"""
    db = database.get_db()
    for _ in range(2):
        try:
            db.execute(
                "INSERT INTO sheet_write_log (user_id, platform, target, business_key, status) "
                "VALUES (1,'tt','tt_recycle','acc_1','pending')")
            db.commit()
            ok = True
        except Exception:
            db.rollback()
            ok = False
    rows = db.execute(
        "SELECT COUNT(*) FROM sheet_write_log WHERE user_id=1 AND target='tt_recycle' "
        "AND business_key='acc_1'").fetchone()[0]
    db.close()
    assert ok is False, "第二次插入应撞 UNIQUE 约束"
    assert rows == 1
