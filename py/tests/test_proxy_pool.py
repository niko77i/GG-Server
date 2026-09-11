"""代理池模块测试。"""


class TestProxyPoolLoad:
    """测试配置解析与去重。"""

    def test_parses_proxy_list(self):
        from proxy_pool import ProxyPool

        pool = ProxyPool([
            {"ip": "1.2.3.4", "port": 800, "username": "u1", "password": "p1"},
            {"ip": "5.6.7.8", "port": 443, "username": "u2", "password": "p2"},
        ])
        assert pool.count == 2
        assert pool.max_retries == 3

    def test_dedups_by_ip_and_port(self):
        from proxy_pool import ProxyPool

        pool = ProxyPool([
            {"ip": "1.2.3.4", "port": 800, "username": "u1", "password": "p1"},
            {"ip": "1.2.3.4", "port": 800, "username": "u1", "password": "p1"},
            {"ip": "1.2.3.4", "port": 801, "username": "u2", "password": "p2"},
        ])
        # 同 ip+port 去重，不同 port 保留
        assert pool.count == 2

    def test_skips_invalid_entries(self):
        from proxy_pool import ProxyPool

        pool = ProxyPool([
            {"ip": "", "port": 800},
            {"ip": "1.2.3.4", "port": None},
            {"ip": "1.2.3.4", "port": "abc"},
            "not-a-dict",
            None,
            {"ip": "5.6.7.8", "port": 800},
        ])
        assert pool.count == 1

    def test_custom_max_retries(self):
        from proxy_pool import ProxyPool

        pool = ProxyPool([], max_retries=5)
        assert pool.max_retries == 5


class TestProxyPoolNext:
    """测试代理取用。"""

    def test_next_returns_none_when_empty(self):
        from proxy_pool import ProxyPool

        pool = ProxyPool([])
        assert pool.next() is None

    def test_next_returns_a_proxy(self):
        from proxy_pool import ProxyPool

        pool = ProxyPool([{"ip": "1.2.3.4", "port": 800, "username": "u", "password": "p"}])
        proxy = pool.next()
        assert proxy is not None
        assert proxy["ip"] == "1.2.3.4"

    def test_next_excludes_tried(self):
        from proxy_pool import ProxyPool

        pool = ProxyPool([
            {"ip": "1.2.3.4", "port": 800},
            {"ip": "5.6.7.8", "port": 800},
        ])
        proxy = pool.next(exclude={("1.2.3.4", 800)})
        assert proxy is not None
        assert proxy["ip"] == "5.6.7.8"

    def test_next_returns_none_when_all_excluded(self):
        from proxy_pool import ProxyPool

        pool = ProxyPool([{"ip": "1.2.3.4", "port": 800}])
        assert pool.next(exclude={("1.2.3.4", 800)}) is None


class TestProxyPoolToRequests:
    """测试转 requests proxies 格式。"""

    def test_with_auth(self):
        from proxy_pool import ProxyPool

        proxy = {"ip": "1.2.3.4", "port": 800, "username": "user", "password": "pass", "scheme": "http"}
        result = ProxyPool.to_requests(proxy)
        assert result == {
            "http": "http://user:pass@1.2.3.4:800",
            "https": "http://user:pass@1.2.3.4:800",
        }

    def test_without_auth(self):
        from proxy_pool import ProxyPool

        proxy = {"ip": "1.2.3.4", "port": 800, "username": "", "password": "", "scheme": "http"}
        result = ProxyPool.to_requests(proxy)
        assert result == {
            "http": "http://1.2.3.4:800",
            "https": "http://1.2.3.4:800",
        }

    def test_socks5_scheme(self):
        from proxy_pool import ProxyPool

        proxy = {"ip": "1.2.3.4", "port": 1080, "username": "u", "password": "p", "scheme": "socks5"}
        result = ProxyPool.to_requests(proxy)
        assert result["http"] == "socks5://u:p@1.2.3.4:1080"
