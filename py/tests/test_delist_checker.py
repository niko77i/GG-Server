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

    def test_returns_none_on_timeout(self):
        """请求超时 → 判定未知（拿不到判定，不得当作「正常」覆盖既有记录）。"""
        from delist_checker import check_url_delisted

        with patch("delist_checker.requests.get", side_effect=requests.Timeout("timed out")):
            is_delisted, error = check_url_delisted("https://play.google.com/store/apps/details?id=com.example.app")

        assert is_delisted is None
        assert "超时" in error

    def test_returns_none_on_connection_error(self):
        """网络连接错误 → 判定未知（拿不到判定，不得当作「正常」覆盖既有记录）。"""
        from delist_checker import check_url_delisted

        with patch("delist_checker.requests.get", side_effect=requests.ConnectionError("connection refused")):
            is_delisted, error = check_url_delisted("https://play.google.com/store/apps/details?id=com.example.app")

        assert is_delisted is None
        assert error != ""

    def test_returns_none_on_general_exception(self):
        """其他异常（含解析失败）→ 判定未知（拿不到判定，不得当作「正常」覆盖既有记录）。"""
        from delist_checker import check_url_delisted

        with patch("delist_checker.requests.get", side_effect=Exception("unknown error")):
            is_delisted, error = check_url_delisted("https://play.google.com/store/apps/details?id=com.example.app")

        assert is_delisted is None
        assert error != ""

    def test_empty_url_returns_none(self):
        """空 URL 无法判定 → 返回 None（调用方不得据此写「正常」）。

        语义变更（2026-09-24）：原返回 (False, "")，会被消费方无条件写库成
        is_delisted=0，抹掉上一轮正确的掉包记录 —— 与 429 属同一缺陷家族。
        """
        from delist_checker import check_url_delisted

        is_delisted, error = check_url_delisted("")

        assert is_delisted is None
        assert "无法判定" in error

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
        """没有 URL 的包跳过检测，且判为「未知」而非「正常」。

        语义变更（2026-09-24）：原 is_delisted=False，同样会被消费方写库成
        is_delisted=0 而抹掉既有掉包记录。空 url 仍不发请求（mock_get 不被调用）。
        """
        from delist_checker import check_product_packages

        packages = [
            {"id": 1, "url": "", "package_name": "test.a"},
            {"id": 2, "url": "", "package_name": "test.b"},
        ]

        with patch("delist_checker.requests.get") as mock_get:
            results = check_product_packages(1, packages)

        mock_get.assert_not_called()
        assert len(results) == 2
        assert all(r["is_delisted"] is None for r in results)

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


# ============================================================
# 测试 check_url_delisted 的代理重试逻辑
# ============================================================

class TestCheckUrlDelistedWithProxy:
    """测试带代理池的掉包检测。"""

    def _make_pool(self, n=2):
        from proxy_pool import ProxyPool
        proxies = [
            {"ip": f"1.2.3.{i}", "port": 800 + i, "username": "u", "password": "p"}
            for i in range(1, n + 1)
        ]
        return ProxyPool(proxies, max_retries=n)

    def test_retries_next_proxy_after_failure(self):
        """第一个代理失败后换下一个代理重试，最终成功。"""
        from delist_checker import check_url_delisted

        pool = self._make_pool(2)

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = "Normal app page"

        with patch("delist_checker.requests.get", side_effect=[requests.ConnectionError("fail"), mock_resp]) as mock_get:
            is_delisted, error = check_url_delisted(
                "https://play.google.com/store/apps/details?id=test.a", pool
            )

        assert is_delisted is False
        assert error == ""
        assert mock_get.call_count == 2

    def test_all_proxies_fail_returns_proxy_error(self):
        """代理全部失败 → 判定未知，返回带「代理」标识的错误（不判掉包，也不判正常）。

        语义变更（2026-09-24）：原 is_delisted=False，会被消费方写库成 is_delisted=0，
        抹掉上一轮正确的掉包记录 —— 与 429 属同一缺陷家族。逐代理重试行为不变。
        """
        from delist_checker import check_url_delisted

        pool = self._make_pool(2)

        with patch("delist_checker.requests.get", side_effect=requests.ConnectionError("fail")) as mock_get:
            is_delisted, error = check_url_delisted(
                "https://play.google.com/store/apps/details?id=test.a", pool
            )

        assert is_delisted is None
        assert "代理" in error
        assert mock_get.call_count == 2

    def test_judges_delisted_through_proxy(self):
        """通过代理请求成功，404 判定为掉包，且请求携带 proxies。"""
        from delist_checker import check_url_delisted

        pool = self._make_pool(1)

        mock_resp = MagicMock()
        mock_resp.status_code = 404
        mock_resp.text = ""

        with patch("delist_checker.requests.get", return_value=mock_resp) as mock_get:
            is_delisted, error = check_url_delisted(
                "https://play.google.com/store/apps/details?id=test.a", pool
            )

        assert is_delisted is True
        assert error == ""
        assert mock_get.call_args.kwargs.get("proxies") is not None

    def test_no_pool_keeps_direct_connection(self):
        """不传 proxy_pool 时，请求不带 proxies（直连）。"""
        from delist_checker import check_url_delisted

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = "Normal app page"

        with patch("delist_checker.requests.get", return_value=mock_resp) as mock_get:
            is_delisted, error = check_url_delisted(
                "https://play.google.com/store/apps/details?id=test.a"
            )

        assert is_delisted is False
        assert error == ""
        assert mock_get.call_args.kwargs.get("proxies") is None

    def test_empty_pool_returns_proxy_error(self):
        """空代理池 → 判定未知，返回「代理池为空」错误；不发请求。

        语义变更（2026-09-24）：原为精确断言 error == "代理池为空" 且 is_delisted=False，
        文案已追加「，无法判定」，判定改判未知（与 429 同型）。
        """
        from delist_checker import check_url_delisted
        from proxy_pool import ProxyPool

        pool = ProxyPool([])

        with patch("delist_checker.requests.get") as mock_get:
            is_delisted, error = check_url_delisted(
                "https://play.google.com/store/apps/details?id=test.a", pool
            )

        assert is_delisted is None
        assert "代理池为空" in error
        mock_get.assert_not_called()


# ============================================================
# 测试限流 / 服务端异常 → 判定未知（429/5xx）
# ============================================================

class TestIndeterminateStatus:
    """**非 200/404 的一切状态码**既不是 404（掉包）也不是正常页面，必须判为「未知」。

    实测依据：App Store 对掉包链接返回 404，被限流时返回 429，
    两者响应体同为 2383 字节，只能靠状态码区分。旧逻辑只认 404，
    会把 429（乃至 403 反爬、410、任意 5xx）当成「正常」，
    从而抹掉上一轮正确的掉包记录。
    口径由用户 2026-09-25 裁定拓宽（原为「429 或任意 5xx」）。
    """

    def _resp(self, status, text=""):
        m = MagicMock()
        m.status_code = status
        m.text = text
        return m

    def test_429_direct_returns_none(self):
        """直连遇 429 → is_delisted 为 None，error 带状态码。"""
        from delist_checker import check_url_delisted

        with patch("delist_checker.requests.get", return_value=self._resp(429, "Too Many Requests")):
            is_delisted, error = check_url_delisted("https://apps.apple.com/vn/app/id6813542964")

        assert is_delisted is None
        assert "429" in error

    def test_503_direct_returns_none(self):
        """直连遇 503 → 同样判为未知。"""
        from delist_checker import check_url_delisted

        with patch("delist_checker.requests.get", return_value=self._resp(503)):
            is_delisted, error = check_url_delisted("https://play.google.com/store/apps/details?id=com.a.b")

        assert is_delisted is None
        assert "503" in error

    def test_404_still_true(self):
        """404 不受影响，仍判掉包。"""
        from delist_checker import check_url_delisted

        with patch("delist_checker.requests.get", return_value=self._resp(404)):
            is_delisted, error = check_url_delisted("https://apps.apple.com/vn/app/id6813542964")

        assert is_delisted is True
        assert error == ""

    def test_200_normal_still_false(self):
        """正常页面不受影响，仍判未掉包。"""
        from delist_checker import check_url_delisted

        with patch("delist_checker.requests.get", return_value=self._resp(200, "App page")):
            is_delisted, error = check_url_delisted("https://apps.apple.com/vn/app/id6804355336")

        assert is_delisted is False
        assert error == ""

    def test_timeout_is_none_not_false(self):
        """超时改判未知（2026-09-24 裁定：与 429 同型，拿不到判定不得覆盖既有记录）。

        本用例的前身 test_timeout_still_false_not_none 钉的是「不让未知态扩大化」，
        该理由已被裁定作废。「失败绝不判掉包」不变量不受影响 —— None 既非 True 也非 False。
        """
        from delist_checker import check_url_delisted

        with patch("delist_checker.requests.get", side_effect=requests.Timeout("timed out")):
            is_delisted, error = check_url_delisted("https://play.google.com/store/apps/details?id=com.a.b")

        assert is_delisted is None
        assert error != ""

    def test_malformed_url_returns_none(self):
        """畸形 url（漏写 scheme）→ 判定未知，而非「正常」。

        requests.MissingSchema 不是 ConnectionError 子类，原兜底 except 会吞成 False，
        经消费方写库后抹掉既有掉包记录。实测确认过的事实。
        """
        from delist_checker import check_url_delisted

        is_delisted, error = check_url_delisted("play.google.com/store/apps/details?id=com.x.y")

        assert is_delisted is None
        assert error != ""

    def test_200_normal_still_false_after_unknown_widening(self):
        """边界：200 且无关键词仍是 False —— 「未知」不得吸收「判为正常」。"""
        from delist_checker import check_url_delisted

        resp = MagicMock(status_code=200, text="<html>welcome to the app page</html>")
        with patch("delist_checker.requests.get", return_value=resp):
            is_delisted, error = check_url_delisted("https://play.google.com/store/apps/details?id=com.a.b")

        assert is_delisted is False
        assert error == ""

    def test_proxy_retries_to_next_after_429(self):
        """第一个代理 429，第二个代理 200 → 最终判正常，且请求了两次。"""
        from delist_checker import check_url_delisted
        from proxy_pool import ProxyPool

        pool = ProxyPool([
            {"ip": "1.2.3.1", "port": 801, "username": "u", "password": "p"},
            {"ip": "1.2.3.2", "port": 802, "username": "u", "password": "p"},
        ], max_retries=2)

        with patch("delist_checker.requests.get",
                   side_effect=[self._resp(429), self._resp(200, "App page")]) as mock_get:
            is_delisted, error = check_url_delisted("https://apps.apple.com/vn/app/id6804355336", pool)

        assert is_delisted is False
        assert error == ""
        assert mock_get.call_count == 2

    def test_all_proxies_429_returns_none(self):
        """所有代理都 429 → 判为未知，不判掉包也不判正常。"""
        from delist_checker import check_url_delisted
        from proxy_pool import ProxyPool

        pool = ProxyPool([
            {"ip": "1.2.3.1", "port": 801, "username": "u", "password": "p"},
            {"ip": "1.2.3.2", "port": 802, "username": "u", "password": "p"},
        ], max_retries=2)

        with patch("delist_checker.requests.get", return_value=self._resp(429)):
            is_delisted, error = check_url_delisted("https://apps.apple.com/vn/app/id6813542964", pool)

        assert is_delisted is None
        assert "429" in error

    def test_request_and_judge_raises_on_429(self):
        """_request_and_judge 遇 429 抛 DelistIndeterminate。"""
        from delist_checker import _request_and_judge, DelistIndeterminate

        with patch("delist_checker.requests.get", return_value=self._resp(429)):
            with pytest.raises(DelistIndeterminate):
                _request_and_judge("https://apps.apple.com/vn/app/id6813542964", None)

    def test_check_product_packages_passes_none_through(self):
        """批量检测把未知态原样透传。"""
        from delist_checker import check_product_packages

        with patch("delist_checker.check_url_delisted", return_value=(None, "HTTP 429 限流，判定未知")):
            results = check_product_packages(1, [
                {"id": 7, "url": "https://apps.apple.com/vn/app/id6813542964", "package_name": ""},
            ])

        assert results[0]["is_delisted"] is None
        assert "429" in results[0]["error"]

    def test_501_is_indeterminate_not_normal(self):
        """501 也是 5xx，同样拿不到判定 —— 原枚举集合漏了它，会判成「正常」抹掉掉包记录。"""
        from delist_checker import check_url_delisted

        resp = MagicMock(status_code=501, text="<html>not implemented</html>")
        with patch("delist_checker.requests.get", return_value=resp):
            is_delisted, error = check_url_delisted("https://play.google.com/store/apps/details?id=com.a.b")

        assert is_delisted is None
        assert error != ""

    def test_505_is_indeterminate_not_normal(self):
        """505 HTTP Version Not Supported 同理。"""
        from delist_checker import check_url_delisted

        resp = MagicMock(status_code=505, text="<html>http version not supported</html>")
        with patch("delist_checker.requests.get", return_value=resp):
            is_delisted, error = check_url_delisted("https://play.google.com/store/apps/details?id=com.a.b")

        assert is_delisted is None
        assert error != ""

    def test_403_is_indeterminate_not_normal(self):
        """403 反爬拿不到判定 —— 判成「正常」会经 INSERT OR REPLACE 抹掉掉包记录。

        用户 2026-09-25 裁定：非 200/404 一律未知。
        """
        from delist_checker import check_url_delisted

        resp = MagicMock(status_code=403, text="<html>forbidden</html>")
        with patch("delist_checker.requests.get", return_value=resp):
            is_delisted, error = check_url_delisted("https://play.google.com/store/apps/details?id=com.a.b")

        assert is_delisted is None
        assert "403" in error

    def test_410_is_indeterminate_not_normal(self):
        """410 Gone 同理：拿不到判定，不得判「正常」。"""
        from delist_checker import check_url_delisted

        resp = MagicMock(status_code=410, text="<html>gone</html>")
        with patch("delist_checker.requests.get", return_value=resp):
            is_delisted, error = check_url_delisted("https://play.google.com/store/apps/details?id=com.a.b")

        assert is_delisted is None
        assert "410" in error

    def test_499_is_indeterminate_not_normal(self):
        """499 也属未知 —— 用户 2026-09-25 裁定拓宽：非 200/404 一律未知。

        本用例前身 test_499_is_not_indeterminate 钉的是「4xx 中只认 429，不得顺手拓宽」，
        该口径已被裁定推翻：403/410/499 等判「正常」同样会经 INSERT OR REPLACE
        抹掉上一轮正确的掉包记录，与 429 同型。
        """
        from delist_checker import check_url_delisted

        resp = MagicMock(status_code=499, text="<html>client closed request</html>")
        with patch("delist_checker.requests.get", return_value=resp):
            is_delisted, error = check_url_delisted("https://play.google.com/store/apps/details?id=com.a.b")

        assert is_delisted is None
        assert "499" in error
