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

    def test_update_timezone(self, client, auth_headers):
        """更新地区的时区。"""
        # 获取巴西的 id
        resp = client.get("/api/regions/list", headers=auth_headers)
        regions = resp.get_json()["regions"]
        brazil = next(r for r in regions if r["name"] == "巴西")

        # 更新时区
        resp = client.put(
            f"/api/regions/{brazil['id']}",
            json={"timezone": "UTC-4"},
            headers=auth_headers,
        )
        assert resp.status_code == 200
        assert resp.get_json()["success"] is True

        # 验证更新生效
        resp = client.get("/api/regions/list", headers=auth_headers)
        updated = {r["name"]: r["timezone"] for r in resp.get_json()["regions"]}
        assert updated["巴西"] == "UTC-4"

    def test_update_nonexistent_region(self, client, auth_headers):
        """更新不存在的地区不应报错。"""
        resp = client.put(
            "/api/regions/99999",
            json={"timezone": "UTC"},
            headers=auth_headers,
        )
        assert resp.status_code == 200


class TestRegionsCreate:
    """POST /api/regions/create — 新增地区。"""

    def test_create_new_region(self, client, auth_headers):
        """新增一个地区。"""
        resp = client.post(
            "/api/regions/create",
            json={"name": "秘鲁", "timezone": "UTC-5"},
            headers=auth_headers,
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["success"] is True
        assert data["id"] > 0

        # 验证已加入列表
        resp = client.get("/api/regions/list", headers=auth_headers)
        names = [r["name"] for r in resp.get_json()["regions"]]
        assert "秘鲁" in names

    def test_create_empty_name_fails(self, client, auth_headers):
        """空名称应返回 400。"""
        resp = client.post(
            "/api/regions/create",
            json={"name": "", "timezone": "UTC"},
            headers=auth_headers,
        )
        assert resp.status_code == 400


class TestRegionsDelete:
    """DELETE /api/regions/<id> — 删除地区。"""

    def test_delete_region(self, client, auth_headers):
        """删除一个地区。"""
        # 先新增
        resp = client.post(
            "/api/regions/create",
            json={"name": "测试地区", "timezone": "UTC"},
            headers=auth_headers,
        )
        rid = resp.get_json()["id"]

        # 删除
        resp = client.delete(f"/api/regions/{rid}", headers=auth_headers)
        assert resp.status_code == 200

        # 验证已不在列表中
        resp = client.get("/api/regions/list", headers=auth_headers)
        names = [r["name"] for r in resp.get_json()["regions"]]
        assert "测试地区" not in names
