"""测试 JWT 滑动过期 + reject_viewer 集成"""
import pytest
import auth as auth_module


class TestJwtSliding:
    """JWT 滑动过期 — _refresh_jwt after_request 钩子"""

    def test_protected_route_returns_new_token(self, client, auth_headers):
        """受保护路由返回 X-New-Access-Token 头"""
        resp = client.get("/api/auth/me", headers=auth_headers)
        assert resp.status_code == 200
        new_token = resp.headers.get("X-New-Access-Token")
        assert new_token is not None
        assert len(new_token) > 20

    def test_login_does_not_return_new_token(self, client):
        """登录请求不带 JWT，不应返回新 token"""
        client.post("/api/auth/register", json={
            "username": "_slide_test_", "password": "test123",
        })
        resp = client.post("/api/auth/login", json={
            "username": "_slide_test_", "password": "test123",
        })
        assert resp.status_code == 200
        assert resp.headers.get("X-New-Access-Token") is None

    def test_public_route_no_token(self, client):
        """公开路由不返回 X-New-Access-Token"""
        resp = client.get("/favicon.ico")
        assert resp.status_code == 204
        assert resp.headers.get("X-New-Access-Token") is None

    def test_new_token_is_valid(self, client, auth_headers):
        """新 token 和旧 token 都有效"""
        resp = client.get("/api/auth/me", headers=auth_headers)
        new_token = resp.headers.get("X-New-Access-Token")
        # 旧 token 仍然有效
        old_resp = client.get("/api/auth/me", headers=auth_headers)
        assert old_resp.status_code == 200
        # 新 token 也有效
        new_resp = client.get("/api/auth/me",
                              headers={"Authorization": f"Bearer {new_token}"})
        assert new_resp.status_code == 200

    def test_no_token_on_401(self, client):
        """401 错误不生成 token"""
        resp = client.get("/api/auth/me")
        assert resp.status_code == 401
        assert resp.headers.get("X-New-Access-Token") is None

    def test_sliding_token_different_each_time(self, client, auth_headers):
        """每次请求生成不同的 token（滑动过期轮换）"""
        resp1 = client.get("/api/auth/me", headers=auth_headers)
        resp2 = client.get("/api/auth/me", headers=auth_headers)
        t1 = resp1.headers.get("X-New-Access-Token")
        t2 = resp2.headers.get("X-New-Access-Token")
        assert t1 is not None
        assert t2 is not None
        # 两次 token 不同（因为 exp 不同）
        assert t1 != t2


class TestRejectViewerIntegration:
    """reject_viewer 在 API 中的集成测试"""

    @pytest.fixture
    def viewer_headers(self, client):
        """创建一个 viewer 用户并返回其 auth headers"""
        client.post("/api/auth/register", json={
            "username": "_viewer_test_", "password": "test123",
        })
        resp = client.post("/api/auth/login", json={
            "username": "_viewer_test_", "password": "test123",
        })
        data = resp.get_json()
        user_id = data["user"]["id"]
        # 将角色改为 viewer（需要 developer 权限，这里直接改数据库）
        import database
        db = database.get_db()
        db.execute("UPDATE users SET role='viewer' WHERE id=?", (user_id,))
        db.commit()
        db.close()
        return {"Authorization": f"Bearer {data['access_token']}"}

    def test_viewer_can_read(self, client, viewer_headers):
        """viewer 可以查看个人信息"""
        resp = client.get("/api/auth/me", headers=viewer_headers)
        assert resp.status_code == 200

    def test_viewer_cannot_create_product(self, client, viewer_headers):
        """viewer 无法创建产品（403）"""
        resp = client.post("/api/products/create", json={
            "product_name": "Test Product",
        }, headers=viewer_headers)
        # viewer 应该被拒绝 — reject_viewer 返回 403
        assert resp.status_code == 403


class TestAuthBlueprint:
    """验证 auth Blueprint 路由正常工作"""

    def test_login_via_blueprint(self, client):
        """登录通过 Blueprint 路由"""
        client.post("/api/auth/register", json={
            "username": "_bp_test_", "password": "test123",
        })
        resp = client.post("/api/auth/login", json={
            "username": "_bp_test_", "password": "test123",
        })
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["success"] is True
        assert "access_token" in data

    def test_me_via_blueprint(self, client, auth_headers):
        """获取用户信息通过 Blueprint 路由"""
        resp = client.get("/api/auth/me", headers=auth_headers)
        assert resp.status_code == 200
        assert resp.get_json()["success"] is True

    def test_refresh_via_blueprint(self, client):
        """刷新 token 通过 Blueprint 路由"""
        client.post("/api/auth/register", json={
            "username": "_ref_test_", "password": "test123",
        })
        resp = client.post("/api/auth/login", json={
            "username": "_ref_test_", "password": "test123",
        })
        refresh_token = resp.get_json()["refresh_token"]
        resp2 = client.post("/api/auth/refresh",
                            headers={"Authorization": f"Bearer {refresh_token}"})
        assert resp2.status_code == 200
        assert "access_token" in resp2.get_json()
