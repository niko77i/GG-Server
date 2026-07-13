"""掉包检测模块测试。"""
import pytest
from unittest.mock import patch, MagicMock
import requests


# ============================================================
# 测试 check_url_delisted 函数
# ============================================================

class TestCheckUrlDelisted:
    """测试单个 URL 的掉包检测逻辑。"""

    def test_returns_true_when_http_404(self):
        """HTTP 404 状态码 → 判定为掉包。"""
        from delist_checker import check_url_delisted

        mock_resp = MagicMock()
        mock_resp.status_code = 404
        mock_resp.text = ""

        with patch("delist_checker.requests.get", return_value=mock_resp):
            is_delisted, error = check_url_delisted("https://play.google.com/store/apps/details?id=com.example.app")

        assert is_delisted is True
        assert error == ""

    def test_returns_true_when_english_not_found_text(self):
        """页面内容包含英文"not found on this server" → 判定为掉包。"""
        from delist_checker import check_url_delisted

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = "We're sorry, the requested URL was not found on this server."

        with patch("delist_checker.requests.get", return_value=mock_resp):
            is_delisted, error = check_url_delisted("https://play.google.com/store/apps/details?id=com.example.app")

        assert is_delisted is True
        assert error == ""

    def test_returns_true_when_chinese_not_found_text(self):
        """页面内容包含中文"找不到请求的网址" → 判定为掉包。"""
        from delist_checker import check_url_delisted

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = "很抱歉，在此服务器上找不到请求的网址。"

        with patch("delist_checker.requests.get", return_value=mock_resp):
            is_delisted, error = check_url_delisted("https://play.google.com/store/apps/details?id=com.example.app")

        assert is_delisted is True
        assert error == ""

    def test_returns_false_when_app_page_normal(self):
        """正常应用页面 → 判定为未掉包。"""
        from delist_checker import check_url_delisted

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = "<html><head><title>My App - Google Play</title></head><body>App description</body></html>"

        with patch("delist_checker.requests.get", return_value=mock_resp):
            is_delisted, error = check_url_delisted("https://play.google.com/store/apps/details?id=com.example.app")

        assert is_delisted is False
        assert error == ""

    def test_returns_false_with_error_on_timeout(self):
        """请求超时 → 判定为未掉包，返回错误信息。"""
        from delist_checker import check_url_delisted

        with patch("delist_checker.requests.get", side_effect=requests.Timeout("timed out")):
            is_delisted, error = check_url_delisted("https://play.google.com/store/apps/details?id=com.example.app")

        assert is_delisted is False
        assert "超时" in error or "timeout" in error.lower()

    def test_returns_false_with_error_on_connection_error(self):
        """网络连接错误 → 判定为未掉包，返回错误信息。"""
        from delist_checker import check_url_delisted

        with patch("delist_checker.requests.get", side_effect=requests.ConnectionError("connection refused")):
            is_delisted, error = check_url_delisted("https://play.google.com/store/apps/details?id=com.example.app")

        assert is_delisted is False
        assert error != ""

    def test_returns_false_with_error_on_general_exception(self):
        """其他异常 → 判定为未掉包，返回错误信息。"""
        from delist_checker import check_url_delisted

        with patch("delist_checker.requests.get", side_effect=Exception("unknown error")):
            is_delisted, error = check_url_delisted("https://play.google.com/store/apps/details?id=com.example.app")

        assert is_delisted is False
        assert error != ""

    def test_empty_url_returns_false(self):
        """空 URL → 直接返回未掉包。"""
        from delist_checker import check_url_delisted

        is_delisted, error = check_url_delisted("")

        assert is_delisted is False
        assert error == ""

    def test_uses_mobile_user_agent(self):
        """验证使用了移动端 User-Agent。"""
        from delist_checker import check_url_delisted

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = "App page"

        with patch("delist_checker.requests.get", return_value=mock_resp) as mock_get:
            check_url_delisted("https://play.google.com/store/apps/details?id=com.example.app")

        call_kwargs = mock_get.call_args
        headers = call_kwargs[1].get("headers", {})
        assert "User-Agent" in headers
        assert len(headers["User-Agent"]) > 10  # 不是空字符串


# ============================================================
# 测试 check_product_packages 函数
# ============================================================

class TestCheckProductPackages:
    """测试批量检测产品下所有包的逻辑。"""

    def test_skips_packages_without_url(self):
        """没有 URL 的包跳过检测。"""
        from delist_checker import check_product_packages

        packages = [
            {"id": 1, "url": "", "package_name": "test.a"},
            {"id": 2, "url": "", "package_name": "test.b"},
        ]

        with patch("delist_checker.requests.get") as mock_get:
            results = check_product_packages(1, packages)

        mock_get.assert_not_called()
        assert len(results) == 2
        assert all(r["is_delisted"] is False for r in results)

    def test_checks_packages_with_url(self):
        """有 URL 的包正常检测。"""
        from delist_checker import check_product_packages

        packages = [
            {"id": 1, "url": "https://play.google.com/store/apps/details?id=test.a", "package_name": "test.a"},
            {"id": 2, "url": "https://play.google.com/store/apps/details?id=test.b", "package_name": "test.b"},
        ]

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = "Normal app page"

        with patch("delist_checker.requests.get", return_value=mock_resp) as mock_get:
            results = check_product_packages(1, packages)

        assert mock_get.call_count == 2
        assert len(results) == 2
        assert all(r["is_delisted"] is False for r in results)

    def test_continues_on_individual_error(self):
        """某个包检测出错不影响其他包继续检测。"""
        from delist_checker import check_product_packages

        packages = [
            {"id": 1, "url": "https://play.google.com/store/apps/details?id=test.a", "package_name": "test.a"},
            {"id": 2, "url": "https://play.google.com/store/apps/details?id=test.b", "package_name": "test.b"},
            {"id": 3, "url": "https://play.google.com/store/apps/details?id=test.c", "package_name": "test.c"},
        ]

        # 第2个包请求超时，其余正常
        mock_normal = MagicMock()
        mock_normal.status_code = 200
        mock_normal.text = "Normal app page"

        from delist_checker import check_url_delisted
        original = check_url_delisted

        call_count = [0]

        def side_effect(url):
            call_count[0] += 1
            if call_count[0] == 2:
                return (False, "timeout")
            return (False, "")

        with patch("delist_checker.check_url_delisted", side_effect=side_effect):
            results = check_product_packages(1, packages)

        assert len(results) == 3
