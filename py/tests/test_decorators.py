"""测试 routes/decorators.py — reject_viewer 权限检查"""
import pytest
from flask import Flask
from routes.decorators import reject_viewer


@pytest.fixture
def viewer_app():
    """创建带 JWT 上下文的 Flask 应用"""
    app = Flask(__name__)
    app.config["JWT_SECRET_KEY"] = "test-secret"
    return app


class TestRejectViewer:
    """reject_viewer() 函数 — 单元测试"""

    def test_viewer_rejected(self, viewer_app, monkeypatch):
        """viewer 角色返回 403"""
        monkeypatch.setattr("routes.decorators.get_jwt_identity", lambda: "1")
        monkeypatch.setattr("auth.get_user_by_id", lambda uid: {"id": int(uid), "role": "viewer"})
        with viewer_app.test_request_context("/"):
            result = reject_viewer()
            assert result is not None
            resp, code = result
            assert code == 403

    def test_admin_passes(self, viewer_app, monkeypatch):
        """admin 角色返回 None（通过）"""
        monkeypatch.setattr("routes.decorators.get_jwt_identity", lambda: "1")
        monkeypatch.setattr("auth.get_user_by_id", lambda uid: {"id": int(uid), "role": "admin"})
        with viewer_app.test_request_context("/"):
            result = reject_viewer()
            assert result is None

    def test_user_passes(self, viewer_app, monkeypatch):
        """普通 user 角色返回 None（通过）"""
        monkeypatch.setattr("routes.decorators.get_jwt_identity", lambda: "1")
        monkeypatch.setattr("auth.get_user_by_id", lambda uid: {"id": int(uid), "role": "user"})
        with viewer_app.test_request_context("/"):
            result = reject_viewer()
            assert result is None

    def test_developer_passes(self, viewer_app, monkeypatch):
        """developer 角色返回 None（通过）"""
        monkeypatch.setattr("routes.decorators.get_jwt_identity", lambda: "1")
        monkeypatch.setattr("auth.get_user_by_id", lambda uid: {"id": int(uid), "role": "developer"})
        with viewer_app.test_request_context("/"):
            result = reject_viewer()
            assert result is None

    def test_no_jwt_returns_none(self, viewer_app, monkeypatch):
        """无 JWT 时返回 None（由 @jwt_required 处理）"""
        monkeypatch.setattr("routes.decorators.get_jwt_identity",
                            lambda: (_ for _ in ()).throw(Exception("no jwt")))
        with viewer_app.test_request_context("/"):
            result = reject_viewer()
            assert result is None
