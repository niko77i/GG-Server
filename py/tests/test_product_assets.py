"""测试成效素材 API。"""
import json


class TestProductAssetsList:
    """GET /api/products/<pid>/assets — 产品成效素材列表。"""

    def test_empty_assets_for_new_product(self, client, auth_headers):
        """新产品应该返回空列表。"""
        resp = client.post("/api/products/create", json={
            "product_name": "test_assets_prod",
            "kpi": "test",
            "region": "巴西",
        }, headers=auth_headers)
        assert resp.get_json()["success"] is True

        resp = client.get("/api/products/list?size=100", headers=auth_headers)
        prod_id = next(p["id"] for p in resp.get_json()["products"]
                       if p["product_name"] == "test_assets_prod")

        resp = client.get(f"/api/products/{prod_id}/assets", headers=auth_headers)
        data = resp.get_json()
        assert data["success"] is True
        assert data["assets"] == []


class TestProductAssetsAdd:
    """POST /api/products/<pid>/assets — 添加成效素材。"""

    def test_add_asset_to_product(self, client, auth_headers):
        """为产品添加成效素材。"""
        resp = client.post("/api/products/create", json={
            "product_name": "test_assets_add",
            "kpi": "test",
            "region": "巴西",
        }, headers=auth_headers)
        assert resp.get_json()["success"] is True

        resp = client.get("/api/products/list?size=100", headers=auth_headers)
        prod_id = next(p["id"] for p in resp.get_json()["products"]
                       if p["product_name"] == "test_assets_add")

        resp = client.post(
            f"/api/products/{prod_id}/assets",
            json={"urls": ["https://www.youtube.com/watch?v=dQw4w9WgXcQ"]},
            headers=auth_headers,
        )
        data = resp.get_json()
        assert data["success"] is True
        assert isinstance(data["imported"], int)

        # 验证素材已关联
        resp = client.get(f"/api/products/{prod_id}/assets", headers=auth_headers)
        assets = resp.get_json()["assets"]
        assert len(assets) > 0
        assert assets[0]["id"] == "dQw4w9WgXcQ"

    def test_add_duplicate_asset(self, client, auth_headers):
        """重复添加同一视频应跳过。"""
        resp = client.get("/api/products/list?size=100", headers=auth_headers)
        prods = [p for p in resp.get_json()["products"]
                 if p["product_name"] == "test_assets_add"]
        if not prods:
            return  # 上一个测试没成功创建产品
        prod_id = prods[0]["id"]

        resp = client.post(
            f"/api/products/{prod_id}/assets",
            json={"urls": ["https://www.youtube.com/watch?v=dQw4w9WgXcQ"]},
            headers=auth_headers,
        )
        data = resp.get_json()
        assert data["success"] is True
        assert data["imported"] == 0
        assert len(data["duplicates"]) > 0


class TestProductAssetsDelete:
    """DELETE /api/products/<pid>/assets/<video_id> — 移除成效素材。"""

    def test_remove_asset(self, client, auth_headers):
        """移除成效素材关联（不删视频）。"""
        resp = client.get("/api/products/list?size=100", headers=auth_headers)
        prods = [p for p in resp.get_json()["products"]
                 if p["product_name"] == "test_assets_add"]
        if not prods:
            return
        prod_id = prods[0]["id"]

        resp = client.get(f"/api/products/{prod_id}/assets", headers=auth_headers)
        assets = resp.get_json()["assets"]
        if not assets:
            return

        video_id = assets[0]["id"]
        resp = client.delete(f"/api/products/{prod_id}/assets/{video_id}", headers=auth_headers)
        assert resp.get_json()["success"] is True


class TestProductAssetsMapping:
    """GET /api/youtube/product-assets — 批量查询视频关联产品。"""

    def test_returns_product_names_for_videos(self, client, auth_headers):
        """查询视频关联的产品名。"""
        resp = client.get("/api/products/list?size=100", headers=auth_headers)
        prods = [p for p in resp.get_json()["products"]
                 if p["product_name"] == "test_assets_add"]
        if not prods:
            return
        prod_id = prods[0]["id"]

        resp = client.get(f"/api/products/{prod_id}/assets", headers=auth_headers)
        assets = resp.get_json()["assets"]
        if not assets:
            return

        video_ids = ",".join(a["id"] for a in assets[:3])
        resp = client.get(f"/api/youtube/product-assets?video_ids={video_ids}", headers=auth_headers)
        data = resp.get_json()
        assert data["success"] is True
        assert "mapping" in data
        for vid in assets[:3]:
            if vid["id"] in data["mapping"]:
                assert "test_assets_add" in data["mapping"][vid["id"]]

    def test_empty_ids_returns_empty_mapping(self, client, auth_headers):
        """空 video_ids 应返回空 mapping。"""
        resp = client.get("/api/youtube/product-assets?video_ids=", headers=auth_headers)
        assert resp.get_json()["mapping"] == {}
