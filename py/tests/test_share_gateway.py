"""共享账号网关单测：会话罐 / 票据 / 重写 / 端到端代理。

不访问真实站点：用本机 127.0.0.1 起一个假上游，覆盖
- 页面文本重写、Set-Cookie 落罐与下发规则
- 同站跳转改写 / 跨主机跳转内部跟随
- 票据一次性、网关 cookie 鉴权
"""
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from werkzeug.test import Client

import database
from share_gateway import jar as jar_mod, store, ticket as ticket_mod
from share_gateway.proxy import GatewayApp, rewrite_text
from share_gateway.runtime import SiteRuntime


# ---------------------------------------------------------------- 假上游

class _Handler(BaseHTTPRequestHandler):
    seen_cookie = None
    seen_headers = {}
    seen_method = None
    seen_auth = None

    def log_message(self, *args):  # 静音
        pass

    def _send(self, code, body, headers=None, ctype="text/html; charset=utf-8"):
        raw = body.encode("utf-8") if isinstance(body, str) else body
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(raw)))
        for k, v in (headers or []):
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        type(self).seen_cookie = self.headers.get("Cookie")
        type(self).seen_headers = dict(self.headers.items())
        type(self).seen_auth = self.headers.get("Authorization")
        type(self).seen_method = "GET"
        if self.path.startswith("/html"):
            self._send(200,
                       "<html><a href='https://www.guangdada.net/modules/x'>go</a>"
                       "<script>window.host=\"https://guangdada.net\"</script></html>")
        elif self.path.startswith("/cookies"):
            self._send(200, "ok", headers=[
                ("Set-Cookie", "user-token=abc123; Path=/; Max-Age=3600"),
                ("Set-Cookie", "ZFSESSID=zzz; Path=/; HttpOnly; Max-Age=3600"),
            ])
        elif self.path.startswith("/auth-redirect"):
            port = self.server.server_address[1]
            self._send(302, "", headers=[
                ("Location", f"http://127.0.0.1:{port}/modules/auth/login"),
            ])
        elif self.path.startswith("/cross-host"):
            # 跨主机跳转到 apex（不在 127.0.0.1 集合里时不会被内部跟随）
            self._send(302, "", headers=[("Location", "https://guangdada.net/napi/v1/user/jwt")])
        elif self.path.startswith("/json"):
            self._send(200, json.dumps({"url": "https://www.guangdada.net/api/x"}),
                       ctype="application/json; charset=utf-8")
        else:
            self._send(404, "not found")
            return

    def do_POST(self):
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length)
        type(self).seen_method = "POST"
        type(self).seen_headers = dict(self.headers.items())
        self._send(200, json.dumps({"received": body.decode("utf-8", "replace")}),
                   ctype="application/json")


@pytest.fixture
def fake_upstream():
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()


# ---------------------------------------------------------------- 会话罐

class TestJar:
    def test_parse_and_merge(self):
        c1 = jar_mod.parse_set_cookie("a=1; Path=/; Max-Age=100; HttpOnly", "example.com", now=1000)
        assert c1["n"] == "a" and c1["h"] is True and c1["d"] == "example.com" and c1["ho"] is True
        jar = jar_mod.merge([], c1, now=1000)
        c2 = jar_mod.parse_set_cookie("a=2; Path=/; Max-Age=100", "example.com", now=1100)
        jar = jar_mod.merge(jar, c2, now=1100)
        assert len(jar) == 1 and jar[0]["v"] == "2"

    def test_expired_not_stored_and_dropped(self):
        jar = []
        c = jar_mod.parse_set_cookie("x=1; Path=/; Max-Age=10", "example.com", now=1000)
        jar = jar_mod.merge(jar, c, now=1000)
        assert jar_mod.cookie_header(jar, "example.com", "/", now=1005) == "x=1"
        assert jar_mod.cookie_header(jar, "example.com", "/", now=1011) == ""
        expired = jar_mod.parse_set_cookie("y=1; Path=/; Max-Age=-1", "example.com", now=1000)
        assert jar_mod.merge(jar, expired, now=1000) == jar

    def test_domain_matching(self):
        c = jar_mod.parse_set_cookie("d=1; Domain=.guangdada.net; Path=/; Max-Age=100", "", now=1000)
        jar = [c]
        assert jar_mod.cookie_header(jar, "www.guangdada.net", "/x", now=1001) == "d=1"
        assert jar_mod.cookie_header(jar, "guangdada.net", "/", now=1001) == "d=1"
        assert jar_mod.cookie_header(jar, "evilguangdada.net", "/", now=1001) == ""

    def test_seal_roundtrip_and_tamper(self):
        key = jar_mod.key_for("secret", "site")
        blob = jar_mod.seal('{"a":1}', key)
        assert jar_mod.unseal(blob, key) == '{"a":1}'
        assert jar_mod.unseal(blob[:-2] + "AA", key) is None
        assert jar_mod.unseal(blob, jar_mod.key_for("other", "site")) is None

    def test_expiry_helpers(self):
        jar = jar_mod.parse_set_cookie("user-token=1; Path=/; Max-Age=100", "h", now=1000)
        jar = jar_mod.merge([], jar, now=1000)
        assert jar_mod.has_unexpired(jar, ("user-token",), now=1050) is True
        assert jar_mod.has_unexpired(jar, ("user-token",), now=1200) is False
        assert jar_mod.cookie_expiry(jar, ("user-token",)) == 1100


# ---------------------------------------------------------------- 票据

class TestTicket:
    def test_ticket_once(self):
        tk = ticket_mod.issue_ticket("s", "guangdada", 7, "张三")
        payload = ticket_mod.verify_ticket("s", tk)
        assert payload and payload["uid"] == 7 and payload["site"] == "guangdada"
        assert ticket_mod.verify_ticket("s", tk) is None  # 一次性

    def test_ticket_bad_secret_and_expired(self):
        tk = ticket_mod.issue_ticket("s", "guangdada", 7, "张三", ttl=-1)
        assert ticket_mod.verify_ticket("s", tk) is None
        tk2 = ticket_mod.issue_ticket("s", "guangdada", 7, "张三")
        assert ticket_mod.verify_ticket("other", tk2) is None

    def test_cookie_reusable_and_typed(self):
        ck = ticket_mod.make_cookie("s", "guangdada", 7, "张三")
        assert ticket_mod.verify_cookie("s", ck)["uid"] == 7
        assert ticket_mod.verify_cookie("s", ck) is not None
        # 票据不能当 cookie 用
        tk = ticket_mod.issue_ticket("s", "guangdada", 7, "张三")
        assert ticket_mod.verify_cookie("s", tk) is None


# ---------------------------------------------------------------- 重写

class TestRewrite:
    def test_rewrites_all_schemes_and_boundaries(self):
        hosts = ["www.guangdada.net", "guangdada.net"]
        text = (
            "a=https://www.guangdada.net/x "
            "b=http://guangdada.net/y "
            "c=//www.guangdada.net/z "
            "d=https://www.guangdada.net.evil.com/no"
        )
        out = rewrite_text(text, hosts, "http://gw:8901")
        assert "a=http://gw:8901/x" in out
        assert "b=http://gw:8901/y" in out
        assert "c=http://gw:8901/z" in out
        assert "guangdada.net.evil.com" in out  # 边界外的域名不能被改

    def test_no_hosts_noop(self):
        assert rewrite_text("https://x/y", [], "http://gw") == "https://x/y"

    def test_host_with_port_is_replaced_entirely(self):
        out = rewrite_text("x=http://127.0.0.1:18091/a", ["127.0.0.1"], "http://gw:8901")
        assert out == "x=http://gw:8901/a"


# ---------------------------------------------------------------- 端到端

@pytest.fixture
def gateway(app, fake_upstream):
    """建好一个指向假上游的网关（依赖 conftest 的临时库）。"""
    site = {
        "id": "guangdada",
        "name": "广大大",
        "upstream": fake_upstream,
        "extra_hosts": ["guangdada.net", "www.guangdada.net"],
        "landing_path": "/modules/creative/display-ads",
        "port": 8901,
        "enabled": True,
    }
    store.ensure_site(site)
    rt = SiteRuntime(site, "test-secret")
    return GatewayApp(site, rt, "test-secret"), rt


def _enter(client, site_id="guangdada", secret="test-secret"):
    tk = ticket_mod.issue_ticket(secret, site_id, 7, "张三")
    return client.get(f"/__sgw/enter?t={tk}", headers={"Host": "gw.test"})


class TestGateway:
    def test_requires_gateway_cookie(self, gateway):
        gw, _ = gateway
        client = Client(gw)
        r = client.get("/", headers={"Host": "gw.test"})
        assert r.status_code == 401
        assert "GG-Server" in r.get_data(as_text=True)

    def test_enter_sets_cookie_and_reuse_fails(self, gateway):
        gw, _ = gateway
        client = Client(gw)
        tk = ticket_mod.issue_ticket("test-secret", "guangdada", 7, "张三")
        r = client.get(f"/__sgw/enter?t={tk}", headers={"Host": "gw.test"})
        assert r.status_code == 302
        # 进入后落到工作台，而不是原站营销首页
        assert r.headers.get("Location") == "/modules/creative/display-ads"
        r2 = client.get("/html", headers={"Host": "gw.test"})
        assert r2.status_code == 200
        # 同一张票据第二次使用 → 401
        r3 = client.get(f"/__sgw/enter?t={tk}", headers={"Host": "gw.test"})
        assert r3.status_code == 401

    def test_learns_user_token_from_browser_and_injects_it(self, gateway):
        """user-token 是 SPA 用 document.cookie 写的，必须学习并下发给其他浏览器。"""
        gw, rt = gateway
        rt.learn_browser_cookies("user-token=abc.def.ghi; x-token=zzz; other=1")
        names = {c["n"] for c in rt.snapshot()}
        assert "user-token" in names and "x-token" in names
        assert "other" not in names  # 白名单外不学

        client = Client(gw)
        _enter(client)
        r = client.get("/html", headers={"Host": "gw.test"})
        cookies = [v for k, v in r.headers if k.lower() == "set-cookie"]
        assert any("user-token=abc.def.ghi" in v for v in cookies)
        # 同时上游请求也带上了
        assert "user-token=abc.def.ghi" in (_Handler.seen_cookie or "")

    def test_page_rewritten_to_gateway_origin(self, gateway):
        gw, _ = gateway
        client = Client(gw)
        _enter(client)
        r = client.get("/html", headers={"Host": "gw.test"})
        html = r.get_data(as_text=True)
        assert "http://gw.test/modules/x" in html
        assert "https://www.guangdada.net/modules/x" not in html
        assert 'window.host="http://gw.test"' in html

    def test_html_disables_referrer(self, gateway):
        """CDN 有 Referer 防盗链：网关页必须带 no-referrer，否则 main.js 被 403（白屏）。"""
        gw, _ = gateway
        client = Client(gw)
        _enter(client)
        r = client.get("/html", headers={"Host": "gw.test"})
        html = r.get_data(as_text=True)
        assert '<meta name="referrer" content="no-referrer">' in html
        policies = [v for k, v in r.headers if k.lower() == "referrer-policy"]
        assert policies == ["no-referrer"]

    def test_set_cookie_split_and_jar(self, gateway):
        gw, rt = gateway
        client = Client(gw)
        _enter(client)
        r = client.get("/cookies", headers={"Host": "gw.test"})
        cookies = [v for k, v in r.headers if k.lower() == "set-cookie"]
        joined = "\n".join(cookies)
        assert "user-token=abc123" in joined
        assert "ZFSESSID" not in joined  # httpOnly 不下发
        assert rt.count() == 2
        # 第二次请求要把服务端罐里的两个 cookie 都带上
        client.get("/html", headers={"Host": "gw.test"})
        seen = _Handler.seen_cookie or ""
        assert "user-token=abc123" in seen and "ZFSESSID=zzz" in seen

    def test_same_host_redirect_rewritten(self, gateway):
        gw, _ = gateway
        client = Client(gw)
        _enter(client)
        r = client.get("/auth-redirect", headers={"Host": "gw.test"})
        assert r.status_code == 302
        loc = r.headers.get("Location")
        assert loc == "http://gw.test/modules/auth/login"

    def test_json_body_rewritten(self, gateway):
        gw, _ = gateway
        client = Client(gw)
        _enter(client)
        r = client.get("/json", headers={"Host": "gw.test"})
        assert "http://gw.test/api/x" in r.get_data(as_text=True)

    def test_post_body_forwarded(self, gateway):
        gw, _ = gateway
        client = Client(gw)
        _enter(client)
        r = client.post("/echo", data=json.dumps({"q": 1}),
                        headers={"Host": "gw.test", "Content-Type": "application/json"})
        assert r.status_code == 200
        assert json.loads(r.get_data(as_text=True))["received"] == '{"q": 1}'
        assert _Handler.seen_method == "POST"


# ---------------------------------------------------------------- 安全/吊销

class TestSecurity:
    def test_valid_token_is_never_overwritten(self, gateway):
        """已有未过期令牌时，谁发来的新 token 都不覆盖（防同事顶号 / 旧浏览器回滚）。"""
        gw, rt = gateway
        rt.learn_browser_cookies("user-token=first", uid=1)
        rt.learn_browser_cookies("user-token=other", uid=2)
        rt.learn_browser_cookies("user-token=stale", uid=1)
        assert any(c["n"] == "user-token" and c["v"] == "first" for c in rt.snapshot())

    def test_mark_invalid_allows_relogin(self, gateway):
        """上游 401 后把旧 token 标过期，新登录的 token 才能学进来。"""
        gw, rt = gateway
        rt.learn_browser_cookies("user-token=first", uid=1)
        rt.mark_auth_invalid()
        assert rt.snapshot()[0]["e"] is not None and rt.snapshot()[0]["e"] < __import__("time").time()
        rt.learn_browser_cookies("user-token=second", uid=1)
        assert any(c["n"] == "user-token" and c["v"] == "second" for c in rt.snapshot())

    def test_learn_ignores_same_value(self, gateway):
        gw, rt = gateway
        rt.learn_browser_cookies("user-token=same", uid=1)
        rt.learn_browser_cookies("user-token=same", uid=1)
        assert len([c for c in rt.snapshot() if c["n"] == "user-token"]) == 1

    def test_learn_without_uid_does_not_overwrite_valid_token(self, gateway):
        gw, rt = gateway
        rt.learn_browser_cookies("user-token=first", uid=1)
        rt.learn_browser_cookies("user-token=stale")  # 来源不明（脚本/旧浏览器）
        assert any(c["n"] == "user-token" and c["v"] == "first" for c in rt.snapshot())

    def test_clear_invalidates_existing_gateway_cookie(self, gateway):
        gw, rt = gateway
        client = Client(gw)
        _enter(client)
        assert client.get("/html", headers={"Host": "gw.test"}).status_code == 200
        rt.clear()  # 代次 +1
        assert client.get("/html", headers={"Host": "gw.test"}).status_code == 401

    def test_disabled_site_is_denied(self, gateway):
        from share_gateway import proxy as proxy_mod, store
        gw, rt = gateway
        client = Client(gw)
        _enter(client)
        store.set_enabled("guangdada", False)
        proxy_mod._enabled_cache.clear()
        try:
            assert client.get("/html", headers={"Host": "gw.test"}).status_code == 401
        finally:
            store.set_enabled("guangdada", True)
            proxy_mod._enabled_cache.clear()

    def test_non_ascii_ticket_is_401_not_500(self, gateway):
        gw, _ = gateway
        client = Client(gw)
        r = client.get("/__sgw/enter?t=%C3%A9.x", headers={"Host": "gw.test"})
        assert r.status_code == 401

    def test_session_cookie_without_expiry_uses_first_seen_ttl(self, gateway):
        import time as _time
        gw, rt = gateway
        now = _time.time()
        fresh = {"n": "ZFSESSID", "fs": now}
        stale = {"n": "ZFSESSID", "fs": now - 31 * 86400}
        assert rt._effective_expiry(fresh, now) > now
        assert rt._effective_expiry(stale, now) <= now

    def test_auth_header_site_learns_and_injects(self, app, fake_upstream):
        """localStorage/Authorization 型站点：学 Authorization、回注 + 写 localStorage。"""
        from share_gateway import store
        from share_gateway.proxy import GatewayApp
        from share_gateway.runtime import SiteRuntime
        site = {
            "id": "insightrackr", "name": "Insightrackr", "upstream": fake_upstream,
            "extra_hosts": [], "landing_path": "/", "login_path": "/login",
            "auth_header": "Authorization", "local_storage_token_key": "token",
            "port": 8904, "enabled": True,
        }
        store.ensure_site(site)
        rt = SiteRuntime(site, "test-secret")
        gw = GatewayApp(site, rt, "test-secret")
        client = Client(gw)
        _enter(client, site_id="insightrackr")

        client.get("/html", headers={"Host": "gw.test", "Authorization": "tok123"})
        assert any(c["n"] == "__auth_header" and c["v"] == "tok123" for c in rt.snapshot())
        assert _Handler.seen_auth == "tok123"

        html = client.get("/html", headers={"Host": "gw.test"}).get_data(as_text=True)
        assert "localStorage.setItem" in html
        assert '"token": "tok123"' in html
        assert "tok123" in _Handler.seen_auth

        # 再进入时应跳到 /?t=<token>（原站原生 token 登录，规避 CSP/时序）
        tk = ticket_mod.issue_ticket("test-secret", "insightrackr", 1, "tester")
        r = client.get(f"/__sgw/enter?t={tk}", headers={"Host": "gw.test"})
        assert r.status_code == 302
        assert r.headers["Location"] == "/?t=tok123"

    def test_login_request_does_not_relearn_stale_token(self, app, fake_upstream):
        """登录接口带的旧 token 不能学回罐里，否则新登录永远被旧令牌覆盖。"""
        from share_gateway import store
        from share_gateway.proxy import GatewayApp
        from share_gateway.runtime import SiteRuntime
        site = {
            "id": "ir2", "name": "IR2", "upstream": fake_upstream,
            "extra_hosts": [], "landing_path": "/", "login_path": "/login",
            "auth_header": "Authorization", "local_storage_token_key": "token",
            "port": 8905, "enabled": True,
        }
        store.ensure_site(site)
        rt = SiteRuntime(site, "test-secret")
        gw = GatewayApp(site, rt, "test-secret")
        client = Client(gw)
        _enter(client, site_id="ir2")
        rt.learn_auth_header("old")
        rt.mark_auth_invalid()

        client.get("/cas/api/logon/login", headers={"Host": "gw.test", "Authorization": "old"})
        assert rt.auth_header_value() == ""  # 没有把旧 token 学回来
        client.get("/api/v1/user/findSelf", headers={"Host": "gw.test", "Authorization": "fresh"})
        assert rt.auth_header_value() == "fresh"



class TestShareApi:
    def test_list_requires_login(self, client):
        assert client.get("/api/share/sites").status_code == 401

    def test_list_returns_configured_sites(self, client, auth_headers):
        resp = client.get("/api/share/sites", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["success"] is True
        ids = [s["id"] for s in data["sites"]]
        assert "guangdada" in ids
        # 普通用户能看列表，但没有管理权
        assert data["sites"][0]["can_manage"] is False

    def test_enter_without_gateway_is_503(self, client, auth_headers):
        resp = client.post("/api/share/sites/guangdada/enter", headers=auth_headers)
        assert resp.status_code == 503

    def test_management_requires_developer(self, client, auth_headers):
        assert client.get("/api/share/sites/guangdada/logs", headers=auth_headers).status_code == 403
        assert client.post("/api/share/sites/guangdada/reset", headers=auth_headers).status_code == 403

    def test_enter_unknown_site_404(self, client, auth_headers):
        assert client.post("/api/share/sites/nope/enter", headers=auth_headers).status_code == 404


class TestPublicHost:
    """拼网关 URL 的主机名：本机 127.0.0.1 时必须回退，否则复制出去的链接指向同事自己。"""

    def test_real_host_is_reused(self, app):
        from routes import share_routes
        with app.app_context():
            assert share_routes._public_host("100.80.178.20:5001") == "100.80.178.20"

    def test_loopback_uses_configured_public_host(self, app, monkeypatch):
        from routes import share_routes
        monkeypatch.setitem(app.config, "SHARE_GATEWAY_CFG", {"public_host": "100.1.2.3", "sites": []})
        with app.app_context():
            assert share_routes._public_host("127.0.0.1:5001") == "100.1.2.3"
            assert share_routes._public_host("localhost:5001") == "100.1.2.3"

    def test_loopback_detects_tailscale_first(self, app, monkeypatch):
        from routes import share_routes
        monkeypatch.setitem(app.config, "SHARE_GATEWAY_CFG", {"public_host": "", "sites": []})
        monkeypatch.setattr(share_routes, "_local_ips", lambda: {"172.30.3.237", "100.80.178.20"})
        with app.app_context():
            assert share_routes._public_host("127.0.0.1:5001") == "100.80.178.20"

    def test_loopback_without_candidates_keeps_host(self, app, monkeypatch):
        from routes import share_routes
        monkeypatch.setitem(app.config, "SHARE_GATEWAY_CFG", {"public_host": "", "sites": []})
        monkeypatch.setattr(share_routes, "_local_ips", lambda: set())
        with app.app_context():
            assert share_routes._public_host("127.0.0.1:5001") == "127.0.0.1"
