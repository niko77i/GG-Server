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


class TestParsePagination:
    """parse_pagination(default, maximum, name) 函数。

    需要 Flask 请求上下文（读 request.args），故用 app 夹具的 test_request_context。
    """

    def _call(self, app, query, **kwargs):
        from routes.helpers import parse_pagination
        with app.test_request_context("/?" + query):
            return parse_pagination(**kwargs)

    def test_defaults_when_no_params(self, app):
        assert self._call(app, "") == (1, 20)

    def test_explicit_values(self, app):
        assert self._call(app, "page=3&size=50") == (3, 50)

    def test_size_above_maximum_is_clamped_not_rejected(self, app):
        """上万级数据下这是「冲烂浏览器」的总闸门，必须钳制。"""
        assert self._call(app, "size=999999") == (1, 500)

    def test_size_exactly_maximum_passes(self, app):
        assert self._call(app, "size=500") == (1, 500)

    def test_size_just_above_maximum_clamps(self, app):
        assert self._call(app, "size=501") == (1, 500)

    def test_non_numeric_size_falls_back_to_default(self, app):
        """现状的裸 int() 会 ValueError ⇒ 500；本函数必须回落而不是抛。"""
        assert self._call(app, "size=abc") == (1, 20)

    def test_zero_and_negative_size_fall_back_to_one(self, app):
        assert self._call(app, "size=0") == (1, 1)
        assert self._call(app, "size=-5") == (1, 1)

    def test_negative_page_falls_back_to_one(self, app):
        """负数页在现状里会变成 OFFSET -N（SQLite 等价 0），是静默错值。"""
        assert self._call(app, "page=-3") == (1, 20)

    def test_non_numeric_page_falls_back_to_one(self, app):
        assert self._call(app, "page=abc") == (1, 20)

    def test_custom_default_preserves_caller_behavior(self, app):
        """TT/FB 的默认页尺寸是 50，迁移时不得把它变成 20。"""
        assert self._call(app, "", default=50) == (1, 50)

    def test_custom_maximum(self, app):
        assert self._call(app, "size=999", maximum=100) == (1, 100)

    def test_custom_param_name(self, app):
        """main.py:8423 用的是 page_size，不是 size。"""
        assert self._call(app, "page_size=30", name="page_size") == (1, 30)
