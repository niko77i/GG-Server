"""测试 routes/helpers.py 公共函数 — _scope_where, can_modify"""
import pytest
from routes.helpers import scope_where, can_modify, MCC_CHANGE_TYPE_LABELS


class TestScopeWhere:
    """_scope_where(scope, user_id, alias) 函数"""

    def test_public_with_alias(self):
        clause, params = scope_where("public", 1, "v")
        assert clause == "v.is_public = 1"
        assert params == []

    def test_private_with_alias(self):
        clause, params = scope_where("private", 1, "v")
        assert clause == "v.owner_id = ?"
        assert params == [1]

    def test_all_with_alias(self):
        clause, params = scope_where("all", 1, "v")
        assert clause == "(v.is_public = 1 OR v.owner_id = ?)"
        assert params == [1]

    def test_public_no_alias(self):
        clause, params = scope_where("public", 5)
        assert clause == "is_public = 1"
        assert params == []

    def test_private_different_alias(self):
        clause, params = scope_where("private", 3, "cw")
        assert clause == "cw.owner_id = ?"
        assert params == [3]

    def test_different_user_ids(self):
        clause, params = scope_where("private", 42, "t")
        assert clause == "t.owner_id = ?"
        assert params == [42]


class TestCanModify:
    """can_modify(db, user_id, table, item_id) 函数"""

    @pytest.fixture
    def db(self):
        """创建内存数据库用于测试"""
        import sqlite3
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        conn.execute("CREATE TABLE videos (id INTEGER, owner_id INTEGER, is_public INTEGER)")
        conn.execute("INSERT INTO videos VALUES (1, 10, 0)")
        conn.execute("INSERT INTO videos VALUES (2, 20, 1)")
        conn.execute("INSERT INTO videos VALUES (3, 30, 0)")
        conn.commit()
        yield conn
        conn.close()

    def test_admin_can_modify(self, db, monkeypatch):
        """admin/developer 始终可以修改"""
        monkeypatch.setattr("auth.get_user_by_id", lambda uid: {"id": uid, "role": "developer"})
        can, err = can_modify(db, 99, "videos", 1)
        assert can is True
        assert err is None

    def test_owner_can_modify(self, db, monkeypatch):
        """资源所有者可以修改"""
        monkeypatch.setattr("auth.get_user_by_id", lambda uid: {"id": uid, "role": "user"})
        can, err = can_modify(db, 10, "videos", 1)
        assert can is True
        assert err is None

    def test_public_resource(self, db, monkeypatch):
        """非 owner 但 is_public=1 可以修改"""
        monkeypatch.setattr("auth.get_user_by_id", lambda uid: {"id": uid, "role": "user"})
        can, err = can_modify(db, 99, "videos", 2)
        assert can is True
        assert err is None

    def test_no_permission(self, db, monkeypatch):
        """非 owner 且非公开，不可修改"""
        monkeypatch.setattr("auth.get_user_by_id", lambda uid: {"id": uid, "role": "user"})
        can, err = can_modify(db, 99, "videos", 3)
        assert can is False
        assert "无权限" in (err or "")

    def test_record_not_found(self, db, monkeypatch):
        """记录不存在时返回 False"""
        monkeypatch.setattr("auth.get_user_by_id", lambda uid: {"id": uid, "role": "user"})
        can, err = can_modify(db, 99, "videos", 999)
        assert can is False
        assert "不存在" in (err or "")

    def test_admin_role(self, db, monkeypatch):
        """admin 角色可以修改"""
        monkeypatch.setattr("auth.get_user_by_id", lambda uid: {"id": uid, "role": "admin"})
        can, err = can_modify(db, 99, "videos", 3)
        assert can is True
        assert err is None


class TestMccChangeLabels:
    def test_all_keys_exist(self):
        assert MCC_CHANGE_TYPE_LABELS["manual"] == "手动编辑"
        assert MCC_CHANGE_TYPE_LABELS["batch"] == "批量修改"
        assert MCC_CHANGE_TYPE_LABELS["reassign"] == "认领转移"
        assert MCC_CHANGE_TYPE_LABELS["import"] == "批量导入"
        assert MCC_CHANGE_TYPE_LABELS["create"] == "新建账户"
