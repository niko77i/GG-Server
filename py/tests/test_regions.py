"""测试地区时区管理 API。"""
import json


class TestRegionsList:
    """GET /api/regions/list — 获取所有地区+时区。"""

    def test_returns_regions_with_timezone(self, client, auth_headers):
        """初始化后应返回预设地区的时区。"""
        resp = client.get("/api/regions/list", headers=auth_headers)
        assert resp.status_code == 200

        data = resp.get_json()
        assert data["success"] is True
        assert "regions" in data
        assert isinstance(data["regions"], list)
        assert len(data["regions"]) > 0

        # 每个 region 应有 name 和 timezone 字段
        for r in data["regions"]:
            assert "id" in r
            assert "name" in r
            assert "timezone" in r

    def test_regions_have_default_timezones(self, client, auth_headers):
        """预设地区应有对应的默认时区。"""
        resp = client.get("/api/regions/list", headers=auth_headers)
        data = resp.get_json()
        regions = {r["name"]: r["timezone"] for r in data["regions"]}

        assert regions.get("巴西") == "UTC-3"
        assert regions.get("菲律宾") == "UTC+8"
        assert regions.get("印尼") == "UTC+7"


class TestRegionsUpdate:
    """PUT /api/regions/<id> — 编辑时区。"""

    def test_update_timezone(self, client, dev_headers):
        """更新地区的时区。"""
        # 获取巴西的 id
        resp = client.get("/api/regions/list", headers=dev_headers)
        regions = resp.get_json()["regions"]
        brazil = next(r for r in regions if r["name"] == "巴西")

        # 更新时区
        resp = client.put(
            f"/api/regions/{brazil['id']}",
            json={"timezone": "UTC-4"},
            headers=dev_headers,
        )
        assert resp.status_code == 200
        assert resp.get_json()["success"] is True

        # 验证更新生效
        resp = client.get("/api/regions/list", headers=dev_headers)
        updated = {r["name"]: r["timezone"] for r in resp.get_json()["regions"]}
        assert updated["巴西"] == "UTC-4"

    def test_update_nonexistent_region(self, client, dev_headers):
        """更新不存在的地区不应报错。"""
        resp = client.put(
            "/api/regions/99999",
            json={"timezone": "UTC"},
            headers=dev_headers,
        )
        assert resp.status_code == 200


class TestRegionsCreate:
    """POST /api/regions/create — 新增地区。"""

    def test_create_new_region(self, client, dev_headers):
        """新增一个地区。"""
        resp = client.post(
            "/api/regions/create",
            json={"name": "秘鲁", "timezone": "UTC-5"},
            headers=dev_headers,
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["success"] is True
        assert data["id"] > 0

        # 验证已加入列表
        resp = client.get("/api/regions/list", headers=dev_headers)
        names = [r["name"] for r in resp.get_json()["regions"]]
        assert "秘鲁" in names

    def test_create_empty_name_fails(self, client, dev_headers):
        """空名称应返回 400。"""
        resp = client.post(
            "/api/regions/create",
            json={"name": "", "timezone": "UTC"},
            headers=dev_headers,
        )
        assert resp.status_code == 400


class TestRegionsDelete:
    """DELETE /api/regions/<id> — 删除地区。"""

    def test_delete_region(self, client, dev_headers):
        """删除一个地区。"""
        # 先新增
        resp = client.post(
            "/api/regions/create",
            json={"name": "测试地区", "timezone": "UTC"},
            headers=dev_headers,
        )
        rid = resp.get_json()["id"]

        # 删除
        resp = client.delete(f"/api/regions/{rid}", headers=dev_headers)
        assert resp.status_code == 200

        # 验证已不在列表中
        resp = client.get("/api/regions/list", headers=dev_headers)
        names = [r["name"] for r in resp.get_json()["regions"]]
        assert "测试地区" not in names


class TestRegionsForbiddenForRegularUser:
    """B-5：regions 写操作收紧到 GLOBAL_OPTION_ROLES，普通 user 一律 403。"""

    def test_regular_user_cannot_create(self, client, auth_headers):
        resp = client.post("/api/regions/create",
                           json={"name": "越权地区", "timezone": "UTC"},
                           headers=auth_headers)
        assert resp.status_code == 403

    def test_regular_user_cannot_update(self, client, auth_headers):
        resp = client.get("/api/regions/list", headers=auth_headers)
        rid = resp.get_json()["regions"][0]["id"]
        resp = client.put(f"/api/regions/{rid}", json={"timezone": "UTC-0"}, headers=auth_headers)
        assert resp.status_code == 403

    def test_regular_user_cannot_delete(self, client, auth_headers):
        resp = client.get("/api/regions/list", headers=auth_headers)
        rid = resp.get_json()["regions"][0]["id"]
        resp = client.delete(f"/api/regions/{rid}", headers=auth_headers)
        assert resp.status_code == 403

    def test_regular_user_can_still_list(self, client, auth_headers):
        # list 对普通用户仍开放（产品表单需要读地区）
        resp = client.get("/api/regions/list", headers=auth_headers)
        assert resp.status_code == 200


class TestRegionsAllowedForCrossUserRoles:
    """B-5 对照：跨用户角色必须仍然可写（防「把闸门加宽到连 dev 也拦」）。"""

    def test_developer_can_create_update_delete(self, client, dev_headers):
        resp = client.post("/api/regions/create",
                           json={"name": "dev建的地区", "timezone": "UTC+1"},
                           headers=dev_headers)
        assert resp.status_code == 200
        rid = resp.get_json()["id"]
        resp = client.put(f"/api/regions/{rid}", json={"timezone": "UTC+2"}, headers=dev_headers)
        assert resp.status_code == 200
        resp = client.delete(f"/api/regions/{rid}", headers=dev_headers)
        assert resp.status_code == 200
