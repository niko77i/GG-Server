"""户管看板同步撤回（子项目 ③）测试。

设计见 docs/superpowers/specs/2026-10-06-huguan-sync-undo-design.md。
本文件不打真实 Google API。
"""
import pytest

import database
import huguan_dashboard as hd


@pytest.fixture
def fb_user(client):
    """一个 FB 平台的户管，返回其 id。"""
    db = database.get_db()
    db.execute("INSERT INTO users(username, password, role, platform) "
               "VALUES('u_undo', 'x', 'huguan', 'fb')")
    uid = db.execute("SELECT last_insert_rowid()").fetchone()[0]
    db.commit()
    db.close()
    return uid


class TestUndoPrimitives:
    def test_table_exists(self, client):
        db = database.get_db()
        cols = {r[1] for r in db.execute("PRAGMA table_info(huguan_sync_undo)").fetchall()}
        db.close()
        assert {"id", "user_id", "platform", "direction", "created_at", "payload"} <= cols

    def test_save_then_load(self, client, fb_user):
        db = database.get_db()
        hd.save_undo(db, fb_user, "fb", "push", {"cells": [{"account_id": "A1"}]})
        db.commit()
        got = hd.load_undo(db, fb_user, "fb", "push")
        db.close()
        assert got == {"cells": [{"account_id": "A1"}]}

    def test_load_missing_returns_none(self, client, fb_user):
        db = database.get_db()
        got = hd.load_undo(db, fb_user, "fb", "sync")
        db.close()
        assert got is None

    def test_save_is_idempotent_last_wins(self, client, fb_user):
        """UNIQUE(user_id, platform, direction) ⇒ 只留最近一条。"""
        db = database.get_db()
        hd.save_undo(db, fb_user, "fb", "push", {"v": 1})
        hd.save_undo(db, fb_user, "fb", "push", {"v": 2})
        db.commit()
        n = db.execute("SELECT COUNT(*) FROM huguan_sync_undo "
                       "WHERE user_id=? AND platform='fb' AND direction='push'",
                       (fb_user,)).fetchone()[0]
        got = hd.load_undo(db, fb_user, "fb", "push")
        db.close()
        assert n == 1
        assert got == {"v": 2}

    def test_platforms_and_directions_are_independent(self, client, fb_user):
        db = database.get_db()
        hd.save_undo(db, fb_user, "fb", "push", {"k": "fb-push"})
        hd.save_undo(db, fb_user, "fb", "sync", {"k": "fb-sync"})
        hd.save_undo(db, fb_user, "gg", "push", {"k": "gg-push"})
        db.commit()
        assert hd.load_undo(db, fb_user, "fb", "push") == {"k": "fb-push"}
        assert hd.load_undo(db, fb_user, "fb", "sync") == {"k": "fb-sync"}
        assert hd.load_undo(db, fb_user, "gg", "push") == {"k": "gg-push"}
        db.close()

    def test_delete(self, client, fb_user):
        db = database.get_db()
        hd.save_undo(db, fb_user, "fb", "push", {"v": 1})
        db.commit()
        hd.delete_undo(db, fb_user, "fb", "push")
        db.commit()
        assert hd.load_undo(db, fb_user, "fb", "push") is None
        db.close()

    def test_two_users_do_not_share(self, client, fb_user):
        db = database.get_db()
        db.execute("INSERT INTO users(username, password, role, platform) "
                   "VALUES('u_undo2', 'x', 'huguan', 'fb')")
        uid2 = db.execute("SELECT last_insert_rowid()").fetchone()[0]
        hd.save_undo(db, fb_user, "fb", "push", {"who": 1})
        db.commit()
        assert hd.load_undo(db, uid2, "fb", "push") is None
        db.close()

    def test_unknown_direction_rejected(self, client, fb_user):
        db = database.get_db()
        with pytest.raises(ValueError):
            hd.save_undo(db, fb_user, "fb", "redo", {"v": 1})
        db.close()

    # ---------- load_undo 的坏 payload 契约：坏数据 → None，绝不抛 ----------

    def test_load_invalid_json_returns_none(self, client, fb_user):
        """payload 不是合法 JSON ⇒ None（撤回入口据此禁用），不得抛异常。"""
        db = database.get_db()
        db.execute("INSERT INTO huguan_sync_undo(user_id, platform, direction, payload) "
                   "VALUES(?, 'fb', 'push', ?)", (fb_user, "{not json"))
        db.commit()
        assert hd.load_undo(db, fb_user, "fb", "push") is None
        db.close()

    @pytest.mark.parametrize("raw", ["[1,2]", "null", '"str"', "42"])
    def test_load_valid_json_not_dict_returns_none(self, client, fb_user, raw):
        """合法 JSON 但不是 dict ⇒ None（快照协议只认 dict）。"""
        db = database.get_db()
        db.execute("INSERT INTO huguan_sync_undo(user_id, platform, direction, payload) "
                   "VALUES(?, 'fb', 'push', ?)", (fb_user, raw))
        db.commit()
        assert hd.load_undo(db, fb_user, "fb", "push") is None
        db.close()

    def test_load_empty_payload_returns_none(self, client, fb_user):
        """payload 为空串 ⇒ None（与「无行」同一条短路分支）。"""
        db = database.get_db()
        db.execute("INSERT INTO huguan_sync_undo(user_id, platform, direction, payload) "
                   "VALUES(?, 'fb', 'push', '')", (fb_user,))
        db.commit()
        assert hd.load_undo(db, fb_user, "fb", "push") is None
        db.close()

    def test_save_delete_do_not_commit(self, client, fb_user):
        """原语与调用方共用事务：save_undo / delete_undo 都不得 commit。"""
        db = database.get_db()
        assert db.in_transaction is False, "前置：连接应处于无事务状态"
        hd.save_undo(db, fb_user, "fb", "push", {"v": 1})
        assert db.in_transaction is True, "save_undo 不得 commit"
        hd.delete_undo(db, fb_user, "fb", "push")
        assert db.in_transaction is True, "delete_undo 不得 commit"
        db.close()
