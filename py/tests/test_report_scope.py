"""报表类资源的作用域与可改字段判定。

设计见 docs/superpowers/specs/2026-10-11-report-data-permission-design.md。
运行：cd py && python -m pytest tests/test_report_scope.py -v
"""
import pytest

import database
from routes.helpers import (
    report_scope_where, report_editable_fields, user_role,
    REPORT_VIEW_ALL_ROLES, REPORT_COST_ONLY_ROLES,
)


# ---------- 常量口径 ----------

def test_cost_only_roles_is_huguan_only():
    """**管理员不在其中** ⇒ 管理员只读。这是本设计最核心的一条。"""
    assert REPORT_COST_ONLY_ROLES == ("huguan",)
    assert "admin" not in REPORT_COST_ONLY_ROLES


def test_view_all_roles_reuses_cross_user_roles():
    assert REPORT_VIEW_ALL_ROLES == ("developer", "admin", "huguan")


# ---------- 作用域 ----------

@pytest.mark.parametrize("role", ["user", "viewer", "hidden", ""])
def test_non_cross_user_sees_only_self(role):
    """非跨用户角色 → 只看自己（与各端点原有写法逐字等价）。"""
    sql, params = report_scope_where(role, 42)
    assert sql == "user_id = ?"
    assert params == [42]


@pytest.mark.parametrize("role", ["developer", "admin", "huguan"])
def test_cross_user_sees_all(role):
    """跨用户角色 → 不加 user_id 限定（看全部）。"""
    sql, params = report_scope_where(role, 42)
    assert params == []
    assert "user_id" not in sql


@pytest.mark.parametrize("role", ["developer", "admin", "huguan"])
def test_cross_user_can_narrow_by_owner(role):
    """「保存人」筛选：跨用户角色传 owner_uid 就收窄到该人。"""
    sql, params = report_scope_where(role, 42, owner_uid=7)
    assert sql == "user_id = ?"
    assert params == [7]


@pytest.mark.parametrize("role", ["user", "viewer"])
def test_owner_uid_must_not_widen_non_cross_user(role):
    """**越权硬判据**：非跨用户角色即使传了 owner_uid，也只看自己。"""
    sql, params = report_scope_where(role, 42, owner_uid=7)
    assert sql == "user_id = ?"
    assert params == [42], "传 owner_uid 不得让普通用户看到别人的行"


def test_alias_is_prefixed():
    sql, _ = report_scope_where("user", 42, alias="r")
    assert sql == "r.user_id = ?"


# ---------- 可改字段 ----------

def test_developer_fields_is_none_meaning_no_whitelist():
    assert report_editable_fields("developer") is None


def test_huguan_can_only_edit_cost():
    assert report_editable_fields("huguan") == {"cost"}


@pytest.mark.parametrize("role", ["admin", "user", "viewer", "hidden", ""])
def test_others_are_readonly(role):
    assert report_editable_fields(role) == set()


# ---------- user_role ----------

def test_user_role_reads_db(app):
    db = database.get_db()
    try:
        db.execute("INSERT INTO users (username, password, role) VALUES (?,?,?)",
                   ("rs_probe", "x", "huguan"))
        db.commit()
        uid = db.execute("SELECT id FROM users WHERE username='rs_probe'").fetchone()["id"]
        assert user_role(db, uid) == "huguan"
    finally:
        db.close()


def test_user_role_unknown_uid_falls_back_to_user(app):
    db = database.get_db()
    try:
        assert user_role(db, 999999) == "user"
    finally:
        db.close()
