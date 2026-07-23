"""掉包检测 API 测试。"""
import json
import pytest
# from unittest.mock import patch, MagicMock


# ============================================================
# 手动检测 API
# ============================================================

# class TestManualCheckDelist:
#     """测试 POST /api/products/<pid>/check-delist"""

#     def test_returns_results_for_product_packages(self, client, auth_headers):
#         """手动检测返回产品下所有包的检测结果。"""
#         # 创建产品
#         client.post("/api/products/create", json={
#             "product_name": "测试产品",
#             "packages": [
#                 {"series_name": "S1", "package_name": "com.test.a",
#                  "url": "https://play.google.com/store/apps/details?id=com.test.a"},
#                 {"series_name": "S2", "package_name": "com.test.b",
#                  "url": "https://play.google.com/store/apps/details?id=com.test.b"},
#             ]
#         }, headers=auth_headers)

#         # 获取产品列表找到 ID
#         resp = client.get("/api/products/list", headers=auth_headers)
#         products = resp.get_json()["products"]
#         pid = products[0]["id"]

#         mock_resp = MagicMock()
#         mock_resp.status_code = 200
#         mock_resp.text = "Normal app page"

#         with patch("delist_checker.requests.get", return_value=mock_resp):
#             resp = client.post(f"/api/products/{pid}/check-delist", headers=auth_headers)

#         data = resp.get_json()
#         assert data["success"] is True
#         assert len(data["results"]) == 2
#         for r in data["results"]:
#             assert "package_id" in r
#             assert "is_delisted" in r

#     def test_skips_paused_packages(self, client, auth_headers):
#         """只检测正常状态的包，跳过暂停的包。"""
#         client.post("/api/products/create", json={
#             "product_name": "测试产品2",
#             "packages": [
#                 {"series_name": "S1", "package_name": "com.test.a",
#                  "url": "https://play.google.com/store/apps/details?id=com.test.a"},
#             ]
#         }, headers=auth_headers)

#         resp = client.get("/api/products/list", headers=auth_headers)
#         products = resp.get_json()["products"]
#         pid = products[0]["id"]
#         pkg_id = products[0]["packages"][0]["id"]

#         # 将包设为暂停
#         client.put(f"/api/products/packages/{pkg_id}", json={"status": "paused"}, headers=auth_headers)

#         # 检测 — 暂停的包不应该被检测
#         mock_resp = MagicMock()
#         mock_resp.status_code = 200
#         mock_resp.text = "Normal"

#         with patch("delist_checker.requests.get", return_value=mock_resp) as mock_get:
#             resp = client.post(f"/api/products/{pid}/check-delist", headers=auth_headers)

#         data = resp.get_json()
#         assert data["success"] is True
#         # 暂停的包被跳过，不发起 HTTP 请求
#         mock_get.assert_not_called()

#     def test_requires_auth(self, client):
#         """未登录返回 401。"""
#         resp = client.post("/api/products/1/check-delist")
#         assert resp.status_code == 401

#     def test_viewer_rejected(self, client, auth_headers):
#         """viewer 角色被拒绝。"""
#         # 注册 viewer 用户
#         client.post("/api/auth/register", json={
#             "username": "viewer_test", "password": "test123",
#         })
#         # 需要 admin 权限才能改角色，这里简化：直接用 viewer 不行就跳过
#         # 实际 viewer 会被 _reject_viewer 拦截


# ============================================================
# 获取掉包状态 API
# ============================================================

# class TestDelistStatus:
#     """测试 GET /api/products/delist-status"""
#
#     def test_returns_delisted_packages_for_runner(self, client, auth_headers):
#         """返回当前用户作为 runner 的产品中已掉包的列表。"""
#         client.post("/api/products/create", json={
#             "product_name": "掉包测试产品",
#             "packages": [
#                 {"series_name": "S1", "package_name": "com.test.a",
#                  "url": "https://play.google.com/store/apps/details?id=com.test.a"},
#             ]
#         }, headers=auth_headers)
#
#         resp = client.get("/api/products/list", headers=auth_headers)
#         products = resp.get_json()["products"]
#         pid = products[0]["id"]
#         pkg_id = products[0]["packages"][0]["id"]
#
#         # 模拟掉包检测结果
#         mock_resp = MagicMock()
#         mock_resp.status_code = 404
#         mock_resp.text = ""
#
#         with patch("delist_checker.requests.get", return_value=mock_resp):
#             client.post(f"/api/products/{pid}/check-delist", headers=auth_headers)
#
#         # 获取掉包状态
#         resp = client.get("/api/products/delist-status", headers=auth_headers)
#         data = resp.get_json()
#         assert data["success"] is True
#         assert "delisted_packages" in data
#         # 应该有 1 个掉包
#         delisted = [d for d in data["delisted_packages"] if d["package_id"] == pkg_id]
#         assert len(delisted) == 1
#
#     def test_excludes_dropped_packages(self, client, auth_headers):
#         """已被标记为 dropped 的包不返回在掉包列表中。"""
#         client.post("/api/products/create", json={
#             "product_name": "已掉包产品",
#             "packages": [
#                 {"series_name": "S1", "package_name": "com.test.a",
#                  "url": "https://play.google.com/store/apps/details?id=com.test.a"},
#             ]
#         }, headers=auth_headers)
#
#         resp = client.get("/api/products/list", headers=auth_headers)
#         products = resp.get_json()["products"]
#         pid = products[0]["id"]
#         pkg_id = products[0]["packages"][0]["id"]
#
#         # 检测后设置 dropped
#         mock_resp = MagicMock()
#         mock_resp.status_code = 404
#         mock_resp.text = ""
#         with patch("delist_checker.requests.get", return_value=mock_resp):
#             client.post(f"/api/products/{pid}/check-delist", headers=auth_headers)
#
#         client.put(f"/api/products/packages/{pkg_id}", json={"status": "dropped"}, headers=auth_headers)
#
#         resp = client.get("/api/products/delist-status", headers=auth_headers)
#         data = resp.get_json()
#         # dropped 的包不返回
#         delisted = [d for d in data["delisted_packages"] if d["package_id"] == pkg_id]
#         assert len(delisted) == 0


# ============================================================
# 关闭通知 API
# ============================================================

class TestDismissDelist:
    """测试 POST /api/delist/dismiss"""

    def test_records_dismissal(self, client, auth_headers):
        """记录用户关闭通知的时间。"""
        # 先创建产品和包
        client.post("/api/products/create", json={
            "product_name": "关闭测试产品",
            "packages": [
                {"series_name": "S1", "package_name": "com.test.a",
                 "url": "https://play.google.com/store/apps/details?id=com.test.a"},
            ]
        }, headers=auth_headers)

        resp = client.get("/api/products/list", headers=auth_headers)
        pkg_id = resp.get_json()["products"][0]["packages"][0]["id"]

        resp = client.post("/api/delist/dismiss", json={
            "package_id": pkg_id
        }, headers=auth_headers)

        data = resp.get_json()
        assert data["success"] is True

    def test_requires_auth(self, client):
        """未登录返回 401。"""
        resp = client.post("/api/delist/dismiss", json={"package_id": 1})
        assert resp.status_code == 401


# ============================================================
# 获取待处理通知 API
# ============================================================

class TestPendingDelist:
    """测试 GET /api/delist/pending"""

    # def test_returns_pending_first_notification(self, client, auth_headers):
    #     """新掉包的包出现在待通知列表中。"""
    #     client.post("/api/products/create", json={
    #         "product_name": "待通知产品",
    #         "packages": [
    #             {"series_name": "S1", "package_name": "com.test.a",
    #              "url": "https://play.google.com/store/apps/details?id=com.test.a"},
    #         ]
    #     }, headers=auth_headers)
    #
    #     resp = client.get("/api/products/list", headers=auth_headers)
    #     products = resp.get_json()["products"]
    #     pid = products[0]["id"]
    #     pkg_id = products[0]["packages"][0]["id"]
    #
    #     # 模拟掉包
    #     mock_resp = MagicMock()
    #     mock_resp.status_code = 404
    #     mock_resp.text = ""
    #     with patch("delist_checker.requests.get", return_value=mock_resp):
    #         client.post(f"/api/products/{pid}/check-delist", headers=auth_headers)
    #
    #     resp = client.get("/api/delist/pending", headers=auth_headers)
    #     data = resp.get_json()
    #     assert data["success"] is True
    #     assert "notifications" in data
    #     # 首次通知
    #     pending = [n for n in data["notifications"] if n["package_id"] == pkg_id]
    #     assert len(pending) == 1
    #     assert pending[0]["type"] == "first"

    # def test_returns_reminder_after_dismiss_and_wait(self, client, auth_headers):
    #     """关闭通知 3 分钟后且包未设为 dropped，应返回提醒。"""
    #     client.post("/api/products/create", json={
    #         "product_name": "提醒产品",
    #         "packages": [
    #             {"series_name": "S1", "package_name": "com.test.a",
    #              "url": "https://play.google.com/store/apps/details?id=com.test.a"},
    #         ]
    #     }, headers=auth_headers)
    #
    #     resp = client.get("/api/products/list", headers=auth_headers)
    #     products = resp.get_json()["products"]
    #     pid = products[0]["id"]
    #     pkg_id = products[0]["packages"][0]["id"]
    #
    #     # 模拟掉包
    #     mock_resp = MagicMock()
    #     mock_resp.status_code = 404
    #     mock_resp.text = ""
    #     with patch("delist_checker.requests.get", return_value=mock_resp):
    #         client.post(f"/api/products/{pid}/check-delist", headers=auth_headers)
    #
    #     # 第一次 pending
    #     resp = client.get("/api/delist/pending", headers=auth_headers)
    #     assert len(resp.get_json()["notifications"]) == 1
    #
    #     # 用户关闭通知（使用真正的 dismiss API）
    #     client.post("/api/delist/dismiss", json={"package_id": pkg_id}, headers=auth_headers)
    #
    #     # 手动修改 dismissed_at 为 4 分钟前（模拟时间流逝）
    #     import datetime
    #     db = __import__("database").get_db()
    #     four_min_ago = (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(minutes=4)).isoformat()
    #     db.execute(
    #         "UPDATE delist_notifications SET dismissed_at=? WHERE package_id=?",
    #         (four_min_ago, pkg_id)
    #     )
    #     db.commit()
    #     db.close()
    #
    #     # 再次获取 pending — 应该返回提醒
    #     resp = client.get("/api/delist/pending", headers=auth_headers)
    #     data = resp.get_json()
    #     pending = [n for n in data["notifications"] if n["package_id"] == pkg_id]
    #     assert len(pending) == 1
    #     assert pending[0]["type"] == "reminder"

    # def test_no_reminder_if_package_dropped(self, client, auth_headers):
    #     """包已被设为 dropped 后不再发送提醒。"""
    #     client.post("/api/products/create", json={
    #         "product_name": "已处理产品",
    #         "packages": [
    #             {"series_name": "S1", "package_name": "com.test.a",
    #              "url": "https://play.google.com/store/apps/details?id=com.test.a"},
    #         ]
    #     }, headers=auth_headers)

    #     resp = client.get("/api/products/list", headers=auth_headers)
    #     products = resp.get_json()["products"]
    #     pid = products[0]["id"]
    #     pkg_id = products[0]["packages"][0]["id"]

    #     # 模拟掉包
    #     mock_resp = MagicMock()
    #     mock_resp.status_code = 404
    #     mock_resp.text = ""
    #     with patch("delist_checker.requests.get", return_value=mock_resp):
    #         client.post(f"/api/products/{pid}/check-delist", headers=auth_headers)

    #     # 模拟之前已通知过
    #     import datetime
    #     db = __import__("database").get_db()
    #     four_min_ago = (datetime.datetime.utcnow() - datetime.timedelta(minutes=4)).isoformat()
    #     db.execute(
    #         "INSERT OR REPLACE INTO delist_notifications(package_id, user_id, first_notified, dismissed_at, reminder_count) "
    #         "VALUES(?, ?, 1, ?, 0)",
    #         (pkg_id, 2, four_min_ago)
    #     )
    #     db.commit()

    #     # 设置包为 dropped
    #     db.execute("UPDATE packages SET status='dropped' WHERE id=?", (pkg_id,))
    #     db.commit()
    #     db.close()

    #     # pending 不应返回此包
    #     resp = client.get("/api/delist/pending", headers=auth_headers)
    #     data = resp.get_json()
    #     pending = [n for n in data["notifications"] if n["package_id"] == pkg_id]
    #     assert len(pending) == 0
