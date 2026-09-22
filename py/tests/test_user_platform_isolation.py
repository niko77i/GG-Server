"""测试用户管理按平台（platform）隔离。"""
import database


def _create_user(client, username, role=None, platform=None):
    """注册用户并直接设置 role/platform，返回 headers。"""
    client.post("/api/auth/register", json={"username": username, "password": "test123"})
    db = database.get_db()
    db.execute("UPDATE users SET role=?, platform=? WHERE username=?",
               (role or "user", platform or "gg", username))
    db.commit()
    db.close()
    resp = client.post("/api/auth/login", json={"username": username, "password": "test123"})
    token = resp.get_json().get("access_token", "")
    return {"Authorization": f"Bearer {token}"}


class TestListUsersPlatformIsolation:
    def test_tt_admin_sees_only_tt_users(self, client):
        _create_user(client, "_iso_gg_user", role="user", platform="gg")
        _create_user(client, "_iso_tt_user", role="user", platform="tt")
        _create_user(client, "_iso_dev", role="developer", platform="gg")
        tt_admin = _create_user(client, "_iso_tt_admin", role="admin", platform="tt")

        resp = client.get("/api/admin/users", headers=tt_admin)
        data = resp.get_json()
        assert resp.status_code == 200
        platforms = {u["platform"] for u in data["users"]}
        assert platforms == {"tt"}
        roles = {u["role"] for u in data["users"]}
        assert "developer" not in roles

    def test_developer_sees_all_platforms(self, client):
        _create_user(client, "_iso2_gg", role="user", platform="gg")
        _create_user(client, "_iso2_tt", role="user", platform="tt")
        dev = _create_user(client, "_iso2_dev", role="developer", platform="gg")

        resp = client.get("/api/admin/users", headers=dev)
        data = resp.get_json()
        platforms = {u["platform"] for u in data["users"]}
        assert platforms >= {"gg", "tt"}

    def test_tt_admin_ignores_platform_param(self, client):
        _create_user(client, "_iso3_gg", role="user", platform="gg")
        _create_user(client, "_iso3_tt", role="user", platform="tt")
        tt_admin = _create_user(client, "_iso3_tt_admin", role="admin", platform="tt")

        resp = client.get("/api/admin/users?platform=gg", headers=tt_admin)
        data = resp.get_json()
        assert all(u["platform"] == "tt" for u in data["users"])


class TestCreateUserPlatformLock:
    def test_tt_admin_creates_tt_user(self, client):
        tt_admin = _create_user(client, "_iso4_tt_admin", role="admin", platform="tt")
        resp = client.post("/api/admin/users/create", json={
            "username": "_iso4_new", "password": "test123", "role": "user", "platform": "gg",
        }, headers=tt_admin)
        assert resp.status_code == 200
        db = database.get_db()
        row = db.execute("SELECT platform FROM users WHERE username='_iso4_new'").fetchone()
        db.close()
        assert row["platform"] == "tt"

    def test_developer_can_set_any_platform(self, client):
        dev = _create_user(client, "_iso5_dev", role="developer", platform="gg")
        resp = client.post("/api/admin/users/create", json={
            "username": "_iso5_new", "password": "test123", "role": "user", "platform": "tt",
        }, headers=dev)
        assert resp.status_code == 200
        db = database.get_db()
        row = db.execute("SELECT platform FROM users WHERE username='_iso5_new'").fetchone()
        db.close()
        assert row["platform"] == "tt"


class TestModifyUserPlatformIsolation:
    def _setup(self, client):
        _create_user(client, "_iso6_gg_user", role="user", platform="gg")
        _create_user(client, "_iso6_tt_user", role="user", platform="tt")
        tt_admin = _create_user(client, "_iso6_tt_admin", role="admin", platform="tt")
        db = database.get_db()
        gg_uid = db.execute("SELECT id FROM users WHERE username='_iso6_gg_user'").fetchone()["id"]
        tt_uid = db.execute("SELECT id FROM users WHERE username='_iso6_tt_user'").fetchone()["id"]
        db.close()
        return gg_uid, tt_uid, tt_admin

    def test_tt_admin_cannot_modify_gg_user(self, client):
        gg_uid, _, tt_admin = self._setup(client)
        resp = client.post(f"/api/admin/users/{gg_uid}/role", json={"role": "viewer"}, headers=tt_admin)
        assert resp.status_code == 403
        # 拒绝原因应为「平台」，与「同级管理员」区分，便于排查
        assert resp.get_json()["error"] == "不能操作其他平台的用户"

    def test_tt_admin_cannot_modify_same_platform_admin(self, client):
        """同平台的 admin 之间仍不可互相操作（角色层级限制保持不变）"""
        _create_user(client, "_iso7_tt_admin2", role="admin", platform="tt")
        tt_admin = _create_user(client, "_iso7_tt_admin1", role="admin", platform="tt")
        db = database.get_db()
        other_uid = db.execute("SELECT id FROM users WHERE username='_iso7_tt_admin2'").fetchone()["id"]
        db.close()
        resp = client.post(f"/api/admin/users/{other_uid}/role", json={"role": "viewer"}, headers=tt_admin)
        assert resp.status_code == 403
        assert resp.get_json()["error"] == "不能操作同级管理员"

    def test_tt_admin_can_modify_tt_user(self, client):
        _, tt_uid, tt_admin = self._setup(client)
        resp = client.post(f"/api/admin/users/{tt_uid}/role", json={"role": "viewer"}, headers=tt_admin)
        assert resp.status_code == 200


class TestEffectivePlatformForAdmin:
    """平台选项解析：非 developer 的管理员应取自己的 platform，而非默认 gg。"""

    def test_tt_admin_sees_tt_statuses(self, client):
        dev = _create_user(client, "_iso8_dev", role="developer", platform="gg")
        client.post("/api/statuses/create?platform=tt", json={"name": "TT测试状态"}, headers=dev)

        tt_admin = _create_user(client, "_iso8_tt_admin", role="admin", platform="tt")
        resp = client.get("/api/statuses/list", headers=tt_admin)
        names = [s["name"] for s in resp.get_json()["statuses"]]
        assert "TT测试状态" in names

    def test_developer_can_switch_platform(self, client):
        """developer 仍可按请求参数跨平台取选项"""
        _create_user(client, "_iso8b_tt_admin", role="admin", platform="tt")
        dev = _create_user(client, "_iso8b_dev", role="developer", platform="gg")
        client.post("/api/statuses/create?platform=tt", json={"name": "TT测试状态B"}, headers=dev)
        resp = client.get("/api/statuses/list?platform=tt", headers=dev)
        names = [s["name"] for s in resp.get_json()["statuses"]]
        assert "TT测试状态B" in names


class TestAdminDataPlatformIsolation:
    """数据导入/导出也应受平台隔离约束。"""

    def _gg_uid(self, client):
        _create_user(client, "_iso9_gg_user", role="user", platform="gg")
        db = database.get_db()
        uid = db.execute("SELECT id FROM users WHERE username='_iso9_gg_user'").fetchone()["id"]
        db.close()
        return uid

    def test_tt_admin_cannot_export_gg_user(self, client):
        gg_uid = self._gg_uid(client)
        tt_admin = _create_user(client, "_iso9_tt_admin", role="admin", platform="tt")
        resp = client.get(f"/api/admin/data/export/{gg_uid}", headers=tt_admin)
        assert resp.status_code == 403

    def test_tt_admin_can_export_tt_user(self, client):
        _create_user(client, "_iso9b_tt_user", role="user", platform="tt")
        db = database.get_db()
        tt_uid = db.execute("SELECT id FROM users WHERE username='_iso9b_tt_user'").fetchone()["id"]
        db.close()
        tt_admin = _create_user(client, "_iso9b_tt_admin", role="admin", platform="tt")
        resp = client.get(f"/api/admin/data/export/{tt_uid}", headers=tt_admin)
        assert resp.status_code == 200

    def test_developer_can_export_any(self, client):
        gg_uid = self._gg_uid(client)
        dev = _create_user(client, "_iso9c_dev", role="developer", platform="gg")
        resp = client.get(f"/api/admin/data/export/{gg_uid}", headers=dev)
        assert resp.status_code == 200


class TestCreateUserPlatformValidation:
    """创建者 platform 为非法存量值时应兜底为 gg，不写入新用户。"""

    def test_invalid_creator_platform_falls_back_to_gg(self, client):
        admin = _create_user(client, "_iso10_admin", role="admin", platform="gg")
        db = database.get_db()
        db.execute("UPDATE users SET platform='xx' WHERE username='_iso10_admin'")
        db.commit()
        db.close()

        resp = client.post("/api/admin/users/create", json={
            "username": "_iso10_new", "password": "test123", "role": "user",
        }, headers=admin)
        assert resp.status_code == 200
        db = database.get_db()
        row = db.execute("SELECT platform FROM users WHERE username='_iso10_new'").fetchone()
        db.close()
        assert row["platform"] == "gg"
