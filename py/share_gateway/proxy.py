"""共享账号网关的代理核心：请求转发 + 响应重写（纯 WSGI，不依赖 Flask）。

为什么不用 Flask：需要**流式**转发大响应（视频/图片）并完全控制响应头，
Flask 的 Response 会带来额外缓冲与头处理；WSGI 直写更可控。

关键取舍见设计文档 §5.3：
- 浏览器请求的 Cookie **不直接透传**，用服务端会话罐重建（jar 优先）。
- 上游的 `Set-Cookie` 先落罐，再决定要不要下发浏览器（只下发非 httpOnly）。
- 文本响应把站点绝对域名改写成「当前网关 origin」；二进制流式原样透传。
- `www` → `apex` 的跨主机 301（广大大的 `/napi/*` 走这条）在**服务端内部跟随**，
  不把浏览器送去原站（否则会绕过代理、丢掉会话）。
"""
import gzip
import html as html_mod
import json
import logging
import re
import threading
import time
import zlib
from urllib.parse import parse_qs, quote, urljoin, urlsplit

import requests

from share_gateway import jar as jar_mod, store, ticket as ticket_mod

_log = logging.getLogger(__name__)

TEXT_TYPES = (
    "text/", "application/json", "application/javascript", "application/x-javascript",
    "application/xml", "application/xhtml+xml", "application/ecmascript",
)
HOP_BY_HOP = {
    "connection", "keep-alive", "proxy-authenticate", "proxy-authorization",
    "te", "trailer", "transfer-encoding", "upgrade",
}
REQ_STRIP = HOP_BY_HOP | {"host", "cookie", "content-length", "accept-encoding"}
DROP_RESP_HEADERS = HOP_BY_HOP | {
    "content-length", "set-cookie", "strict-transport-security",
    "content-security-policy", "content-security-policy-report-only", "referrer-policy",
}
REDIRECT_CODES = {301, 302, 303, 307, 308}
MAX_REDIRECTS = 3
MAX_TEXT_BYTES = 8 * 1024 * 1024
MAX_BODY_BYTES = 20 * 1024 * 1024
TIMEOUT = (10, 60)
CHUNK = 64 * 1024

# 共享会话站点会按「设备指纹」踢人：不同浏览器（Chrome/Edge）带着同一个 token
# 会被认成多设备登录，把共享会话踢掉。统一成一个 UA，平台就只看到一台设备。
DEFAULT_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")

# 站点启用状态缓存：网关每个请求都查库代价太高，5 秒内的「停用」生效延迟可接受。
_ENABLED_TTL = 5.0
_enabled_cache: dict[str, tuple[float, bool]] = {}
_enabled_lock = threading.Lock()

# 复用上游 TCP/TLS 连接：每个 waitress 线程一个 Session（requests.Session 非线程安全），
# 否则每个请求都重新 TLS 握手，页面几十个接口叠加起来会明显慢。
_tls = threading.local()


def _session_for_thread() -> requests.Session:
    sess = getattr(_tls, "session", None)
    if sess is None:
        sess = requests.Session()
        adapter = requests.adapters.HTTPAdapter(
            pool_connections=10, pool_maxsize=50, max_retries=0)
        sess.mount("http://", adapter)
        sess.mount("https://", adapter)
        _tls.session = sess
    # 不依赖 Session 的 cookie jar：cookie 由我们自己的加密罐管理，
    # 清空避免跨请求/跨站点残留。
    sess.cookies.clear()
    return sess


def site_enabled(site_id: str, default: bool = True) -> bool:
    now = time.time()
    with _enabled_lock:
        hit = _enabled_cache.get(site_id)
        if hit and now - hit[0] < _ENABLED_TTL:
            return hit[1]
    try:
        row = store.get_site(site_id)
        value = bool(row.get("enabled", 1)) if row else default
    except Exception:
        value = default
    with _enabled_lock:
        _enabled_cache[site_id] = (now, value)
    return value


def _looks_like_login(path: str, login_path: str = "") -> bool:
    """判断是不是登录相关请求（页面或接口）。

    登录请求本身可能带着**过期**的 Authorization 头，不能拿它去学共享令牌，
    否则刚清掉的旧 token 又会被学回罐里，新登录反而永远生效不了。

    只匹配「登录端点本身」（`/login`、`/logon`、`/signin` 结尾或其子路径），
    不要用「路径里含 login」那种宽匹配 —— 会把 `/api/v1/user/login/status`
    这类登录后的接口也当成登录请求，导致管理员每调一次就被标记失效。
    """
    p = (path or "").lower().rstrip("/")
    lp = (login_path or "").lower().rstrip("/")
    if lp and (p == lp or p.startswith(lp + "/")):
        return True
    return p.endswith(("/login", "/logon", "/signin", "/sign-in"))


def _site_hosts(upstream: str, extra_hosts: list[str]) -> list[str]:
    """代理涉及的主机名：主站 + 去掉/补上 www 的变体 + 配置附加。"""
    host = (urlsplit(upstream).hostname or "").lower()
    hosts = []
    for h in [host] + list(extra_hosts or []):
        h = (h or "").strip().lower()
        if h and h not in hosts:
            hosts.append(h)
    if host:
        variant = host[4:] if host.startswith("www.") else "www." + host
        if variant not in hosts:
            hosts.append(variant)
    return hosts


def _is_text(content_type: str) -> bool:
    ct = (content_type or "").lower()
    return any(ct.startswith(t) for t in TEXT_TYPES)


def _charset(content_type: str) -> str:
    m = re.search(r"charset=([a-zA-Z0-9_\-]+)", content_type or "")
    return m.group(1) if m else "utf-8"


def _with_utf8(content_type: str) -> str:
    ct = content_type or "text/plain"
    if re.search(r"charset=", ct, re.I):
        return re.sub(r"charset=[a-zA-Z0-9_\-]+", "charset=utf-8", ct, flags=re.I)
    return ct + "; charset=utf-8"


def _decompress(raw: bytes, encoding: str) -> bytes:
    enc = (encoding or "").lower().strip()
    if enc in ("", "identity"):
        return raw
    if enc == "gzip":
        try:
            return gzip.decompress(raw)
        except OSError:
            return raw
    if enc == "deflate":
        try:
            return zlib.decompress(raw)
        except zlib.error:
            try:
                return zlib.decompress(raw, -zlib.MAX_WBITS)
            except zlib.error:
                return raw
    return raw


def rewrite_text(text: str, hosts: list[str], gw_origin: str) -> str:
    """把站点绝对地址改写成网关 origin。

    覆盖 `https://host`、`http://host`、`//host` 三种写法；用域名边界负向断言，
    避免把 `guangdada.net.evil.com` 误改。
    """
    if not hosts or not text:
        return text
    alternation = "|".join(re.escape(h) for h in hosts if h)
    if not alternation:
        return text
    pattern = re.compile(
        r"(?:https?:)?//(?:" + alternation + r")(?::\d+)?(?![A-Za-z0-9.\-])", re.I)
    return pattern.sub(gw_origin.rstrip("/"), text)


def parse_cookie_header(header: str) -> dict[str, str]:
    return jar_mod.parse_cookie_header(header)


def inject_no_referrer(html: str) -> str:
    """给页面注入 no-referrer。

    广大大的 CDN（`nbs-bj-global.zingfront.com` / `static-global.zingfront.com`）开了
    **Referer 防盗链**：Referer 是 `http://<局域网IP>:8901/...` 时直接 403，
    浏览器随后以 `ERR_BLOCKED_BY_ORB` 丢掉 main.js/CSS → 页面白屏。
    实测「无 Referer」返回 200，所以在文档级把 Referer 关掉，跨域静态资源就正常了。
    """
    if not html:
        return html
    if re.search(r'<meta[^>]+name=["\']?referrer', html, re.I):
        return html
    tag = '<meta name="referrer" content="no-referrer">'
    m = re.search(r"<head[^>]*>", html, re.I)
    if m:
        return html[:m.end()] + tag + html[m.end():]
    return tag + html


def inject_local_storage(html: str, key: str, value: str) -> str:
    """把共享令牌写进页面的 localStorage（insightrackr 这类站点靠它判断登录）。"""
    if not html or not key or not value:
        return html
    payload = json.dumps({key: value}, ensure_ascii=False).replace("<", "\\u003c")
    script = (
        "<script>try{var __sgw_ls=" + payload +
        ";for(var __k in __sgw_ls){localStorage.setItem(__k,__sgw_ls[__k]);}}catch(e){}</script>"
    )
    return _inject_head(html, script)


def inject_script(html: str, code: str) -> str:
    if not html or not code:
        return html
    return _inject_head(html, "<script>" + code.replace("<", "\\u003c") + "</script>")


def _inject_head(html: str, tag: str) -> str:
    m = re.search(r"<head[^>]*>", html, re.I)
    if m:
        return html[:m.end()] + tag + html[m.end():]
    return tag + html


class GatewayApp:
    """单个站点的 WSGI 应用。"""

    def __init__(self, site: dict, runtime, secret: str):
        self.site = site
        self.rt = runtime
        self.secret = secret
        self.origin = (site.get("upstream") or "").rstrip("/")
        self.upstream_host = (urlsplit(self.origin).hostname or "").lower()
        self.hosts = _site_hosts(self.origin, site.get("extra_hosts") or [])

    # ---------------- WSGI 入口 ----------------

    def __call__(self, environ, start_response):
        try:
            return self._handle(environ, start_response)
        except Exception:
            # 兜底：任何未预料异常都不能把 waitress 线程打挂 / 吐堆栈
            _log.exception("[ShareGW] %s 未捕获异常", self.rt.site_id)
            try:
                return self._error_page(start_response, 502, "网关内部错误，请重试")
            except Exception:
                return [b""]

    def _handle(self, environ, start_response):
        path = environ.get("PATH_INFO") or "/"
        query = environ.get("QUERY_STRING") or ""
        host_header = environ.get("HTTP_HOST") or environ.get("SERVER_NAME") or ""
        gw_origin = ("http://" + host_header).rstrip("/") if host_header else "http://localhost"

        if path == "/__sgw/enter":
            return self._enter(start_response, query)

        cookie_val = parse_cookie_header(environ.get("HTTP_COOKIE", "")).get(
            ticket_mod.cookie_name(self.rt.site_id))
        payload = ticket_mod.verify_cookie(self.secret, cookie_val) if cookie_val else None
        if not payload or payload.get("site") != self.rt.site_id:
            self._log_deny(environ, "无有效网关 cookie（没点打开 / cookie 被清 / 链接过期）")
            return self._unauthorized(start_response)
        # 会话代次：清空会话 / 停用后，旧 cookie 立即失效
        if int(payload.get("ver") or 0) != int(self.rt.ver or 0):
            self._log_deny(environ, f"cookie 代次不符 cookie_ver={payload.get('ver')} site_ver={self.rt.ver}")
            return self._unauthorized(
                start_response,
                "会话已失效（管理员可能清空或停用了站点），请回到 GG-Server 重新打开。")
        if not site_enabled(self.rt.site_id):
            self._log_deny(environ, "站点已停用")
            return self._unauthorized(start_response, "该共享站点已停用。")
        # 只有管理员/开发者能登录原站：同事一登录就会把共享会话顶掉
        if _looks_like_login(path, (self.site.get("login_path") or "").strip()):
            try:
                uid = int(payload.get("uid") or 0)
            except (TypeError, ValueError):
                uid = 0
            if not self._can_manage_login(uid):
                self._log_deny(environ, f"非管理员尝试登录原站 uid={uid}")
                return self._error_page(
                    start_response, 403,
                    "共享会话已失效，请联系管理员重新登录。"
                    "请勿自行登录原站，否则会把所有人的共享会话顶掉。")

        return self._proxy(environ, start_response, path, query, gw_origin,
                           uid=payload.get("uid"))

    def _can_manage_login(self, uid: int) -> bool:
        """能否登录原站：显式配置的 uid，或 GG-Server 角色在 manage_roles 里。"""
        uids = [int(x) for x in (self.site.get("manage_uids") or [1])]
        if uid in uids:
            return True
        roles = [str(r).lower() for r in
                 (self.site.get("manage_roles") or ["developer", "admin"])]
        try:
            return (store.user_role(uid) or "").lower() in roles
        except Exception:
            return False

    def _log_deny(self, environ, reason: str) -> None:
        _log.warning(
            "[ShareGW] %s 拒绝访问：%s | host=%s ip=%s ua=%s",
            self.rt.site_id, reason,
            environ.get("HTTP_HOST") or "", environ.get("REMOTE_ADDR") or "",
            (environ.get("HTTP_USER_AGENT") or "")[:80],
        )

    # ---------------- 进入票据 ----------------

    def _enter(self, start_response, query):
        token = (parse_qs(query).get("t") or [""])[0]
        payload = ticket_mod.verify_ticket(self.secret, token)
        if not payload or payload.get("site") != self.rt.site_id:
            # 一次性票据的常见失败：已用过 / 超过 60 秒 / 不是本站点 / 签名不符
            _log.warning("[ShareGW] %s 进入票据无效（已使用或已过期）", self.rt.site_id)
            return self._unauthorized(
                start_response,
                "链接已失效或已被使用。请回到 GG-Server「共享账号」页面，点「打开」重新生成。")
        if not site_enabled(self.rt.site_id):
            return self._unauthorized(start_response, "该共享站点已停用。")
        _log.info("[ShareGW] %s 进入：uid=%s", self.rt.site_id, payload.get("uid"))
        value = ticket_mod.make_cookie(
            self.secret, self.rt.site_id, int(payload.get("uid") or 0),
            payload.get("name") or "", ver=self.rt.ver)
        cookie = (
            f"{ticket_mod.cookie_name(self.rt.site_id)}={value}; Path=/; HttpOnly; SameSite=Lax; "
            f"Max-Age={ticket_mod.COOKIE_TTL}"
        )
        # 进入后直接落到工作台（原站 `/` 是营销首页，登着也看不出已登录）
        landing = (self.site.get("landing_path") or "/").strip() or "/"
        # localStorage 型站点：原站自带 `?t=<token>` 登录参数（SPA 会存进 localStorage
        # 并立刻从地址栏移除），比注入 inline script 更稳（不受 CSP / 时序影响）。
        if self.site.get("auth_header") and self.site.get("local_storage_token_key"):
            shared = self.rt.auth_header_value()
            if shared:
                sep = "&" if "?" in landing else "?"
                landing = landing + sep + "t=" + quote(shared, safe="")
        start_response("302 Found", [
            ("Set-Cookie", cookie),
            ("Location", landing),
            ("Cache-Control", "no-store"),
            ("Content-Length", "0"),
        ])
        return [b""]

    # ---------------- 代理 ----------------

    def _proxy(self, environ, start_response, path, query, gw_origin, uid=None):
        t0 = time.time()
        method = (environ.get("REQUEST_METHOD") or "GET").upper()
        try:
            raw_length = int(environ.get("CONTENT_LENGTH") or 0)
        except (TypeError, ValueError):
            raw_length = 0
        if raw_length > MAX_BODY_BYTES:
            return self._error_page(start_response, 413, "请求体过大，已拒绝转发。")
        body = self._read_body(environ, raw_length)

        headers = self._request_headers(environ)
        # 统一 UA，避免平台把 Chrome/Edge 当成两台设备踢共享会话。
        # TikTok 这类有反爬签名的站点必须保留浏览器原始 UA（X-Bogus 等签名跟 UA 绑定）。
        if not self.site.get("keep_client_headers"):
            headers["User-Agent"] = (self.site.get("user_agent") or DEFAULT_UA)
            for k in [k for k in headers if k.lower().startswith("sec-ch-ua")]:
                headers.pop(k, None)
        browser_cookies = parse_cookie_header(environ.get("HTTP_COOKIE", ""))
        # 网关自己的 cookie 一个都不往上游带（含其它站点的 `__sgw_*`）
        browser_cookies = {
            k: v for k, v in browser_cookies.items() if not k.startswith(ticket_mod.COOKIE_NAME)
        }
        # 学习 SPA 写的 user-token（它不在上游 Set-Cookie 里），否则换主机打开会显示未登录。
        # ⚠️ 只在「cookie 型」站点学：浏览器 cookie 不区分端口，insightrackr 的页面也会
        # 带上网关同主机下广大大的 user-token，学进来就是串站污染。
        auth_header_name = (self.site.get("auth_header") or "").strip()
        login_path = (self.site.get("login_path") or "").strip()
        is_login_req = _looks_like_login(path, login_path)
        try:
            uid_int = int(uid or 0)
        except (TypeError, ValueError):
            uid_int = 0
        if is_login_req:
            # 登录请求本身可能带着旧令牌：不学；管理员登录前先把旧会话标失效，
            # 新登录的令牌才能被学进来。
            if self._can_manage_login(uid_int):
                self.rt.mark_auth_invalid()
        elif not auth_header_name:
            self.rt.learn_browser_cookies(environ.get("HTTP_COOKIE", ""), uid=uid)
        else:
            # 非 cookie 型站点：从 Authorization 头学习共享令牌
            env_key = "HTTP_" + auth_header_name.upper().replace("-", "_")
            self.rt.learn_auth_header(environ.get(env_key, ""))
        merged = dict(browser_cookies)
        for pair in self.rt.cookie_header(self.upstream_host, path).split("; "):
            if "=" in pair:
                k, v = pair.split("=", 1)
                merged[k] = v
        if merged:
            headers["Cookie"] = "; ".join(f"{k}={v}" for k, v in merged.items())
        headers["Accept-Encoding"] = "gzip, deflate"
        headers["Host"] = self.upstream_host
        if "Origin" in headers:
            headers["Origin"] = self.origin
        if "Referer" in headers:
            headers["Referer"] = self._rewrite_ref(headers["Referer"])
        if auth_header_name:
            shared_auth = self.rt.auth_header_value()
            if shared_auth:
                headers[auth_header_name] = shared_auth

        url = self.origin + quote(path, safe="/:@!$&'()*+,;=~.-") + (("?" + query) if query else "")
        sess = _session_for_thread()
        try:
            resp = sess.request(
                method, url, headers=headers, data=body, stream=True,
                timeout=TIMEOUT, allow_redirects=False,
            )
            resp = self._follow_cross_host(resp, url, headers, body, method, sess)
        except requests.RequestException as exc:
            return self._error_page(start_response, 502, f"无法连接上游：{exc}")

        # 上游判 401/403：只有「请求里带的就是罐里的当前令牌」才算共享会话失效。
        # 旧浏览器可能还揣着上一轮的令牌，它 401 不能把全员的会话判死
        # （否则会「页面显示需重登，但点开其实还能用」）。
        login_path = (self.site.get("login_path") or "").strip()
        if resp.status_code in (401, 403) and path != login_path and (
                path.startswith("/napi/") or auth_header_name):
            if auth_header_name:
                sent = (environ.get("HTTP_AUTHORIZATION") or "").strip()
                current = self.rt.raw_auth_value()
            else:
                sent = (environ.get("HTTP_X_NBS_USER_TOKEN")
                        or parse_cookie_header(environ.get("HTTP_COOKIE", "")).get("user-token")
                        or "").strip()
                current = self.rt.raw_cookie_value("user-token")
            stale = bool(sent and current and sent != current)
            if stale:
                _log.info("[ShareGW] %s 旧令牌 401（%s），忽略", self.rt.site_id, path[:80])
            else:
                _log.warning("[ShareGW] %s 上游 %s：path=%s ip=%s（会话已失效）",
                             self.rt.site_id, resp.status_code, path[:120],
                             environ.get("REMOTE_ADDR") or "")
                try:
                    self.rt.mark_auth_invalid()
                except Exception:
                    pass
        # 诊断日志：只记文档和错误（静态资源太吵）
        if resp.status_code == 200 and path.startswith("/napi/"):
            # 已鉴权接口 200 = 共享会话可用；修掉「旧浏览器 401 导致页面显示需重登」的情况
            try:
                self.rt.mark_auth_ok()
            except Exception:
                pass
        if resp.status_code >= 400 or "text/html" in (resp.headers.get("Content-Type") or "").lower():
            _log.info("[ShareGW] %s %s %s ip=%s %.0fms",
                      self.rt.site_id, resp.status_code, path[:100],
                      environ.get("REMOTE_ADDR") or "", (time.time() - t0) * 1000)

        try:
            return self._respond(resp, start_response, gw_origin, method,
                                 environ.get("HTTP_ACCEPT_ENCODING", ""),
                                 environ.get("HTTP_AUTHORIZATION", ""))
        except Exception as exc:  # 任何意外都别把 waitress 线程炸掉
            try:
                resp.close()
            except Exception:
                pass
            return self._error_page(start_response, 502, f"代理响应处理失败：{exc}")

    def _follow_cross_host(self, resp, url, headers, body, method, sess=None):
        """www → apex 这类**跨主机**的同站跳转，在服务端内部跟随。

        只跟随「主机变了且仍在站点主机集合里」的跳转；同主机跳转（例如去登录页）
        交给浏览器处理，否则会把登录页 HTML 直接当接口结果返回。
        """
        current = url
        for _ in range(MAX_REDIRECTS):
            if resp.status_code not in REDIRECT_CODES:
                return resp
            loc = resp.headers.get("Location")
            if not loc:
                return resp
            nxt = urljoin(current, loc)
            nxt_host = (urlsplit(nxt).hostname or "").lower()
            cur_host = (urlsplit(current).hostname or "").lower()
            if nxt_host == cur_host or nxt_host not in self.hosts:
                return resp
            # 中间跳转也可能带会话刷新 cookie（WAF / ZFSESSID 续期），先落罐再丢弃响应
            self._absorb_response_cookies(resp)
            resp.close()
            current = nxt
            headers = dict(headers)
            headers["Host"] = nxt_host
            sess = sess or requests
            resp = sess.request(
                method, nxt, headers=headers, data=body, stream=True,
                timeout=TIMEOUT, allow_redirects=False,
            )
        return resp

    def _respond(self, resp, start_response, gw_origin, method, accept_encoding="",
                 client_auth=""):
        ctype = resp.headers.get("Content-Type", "") or ""
        encoding = (resp.headers.get("Content-Encoding") or "").lower().strip()
        status = f"{resp.status_code} {resp.reason or ''}".strip()
        auth_header_name = (self.site.get("auth_header") or "").strip()

        set_cookies = self._browser_cookies(resp)
        # ?????? user-token ???????SPA ??????????????
        # ?? HTML ?????????????????????? XHR ???? Set-Cookie?
        if _is_text(ctype) and "html" in ctype.lower() and not auth_header_name:
            existing_names = {c.split("=", 1)[0].strip() for c in set_cookies}
            for c in self.rt.browser_sync_cookies():
                if c["n"] in existing_names:
                    continue
                set_cookies.append(f"{c['n']}={c['v']}; Path={c.get('p') or '/'}; SameSite=Lax")
                existing_names.add(c["n"])

        # ?????**????**??????????? Content-Length????? ??
        # ???? SPA ??? chunked???????????? no-referrer?
        # CDN ?? 403 ? ???2026-11-06 ??????
        wants_buffer = (
            _is_text(ctype)
            and encoding in ("", "identity", "gzip", "deflate")
            and method != "HEAD"
        )
        if not wants_buffer:
            headers = self._response_headers(resp, gw_origin, drop_content_encoding=False)
            headers.extend(("Set-Cookie", c) for c in set_cookies)
            start_response(status, headers)
            return self._stream(resp)

        raw = resp.raw.read(MAX_TEXT_BYTES + 1)
        if len(raw) > MAX_TEXT_BYTES:
            # ????????????????? ?? ????? + ???????
            headers = self._response_headers(resp, gw_origin, drop_content_encoding=False)
            headers.extend(("Set-Cookie", c) for c in set_cookies)
            start_response(status, headers)
            return self._stream_with_prefix(raw, resp)

        raw = _decompress(raw, encoding)
        if len(raw) > MAX_TEXT_BYTES * 4:
            resp.close()
            return self._error_page(start_response, 502, "?????????????????")
        text = raw.decode(_charset(ctype), errors="replace")
        # Insightrackr 这类站点过期时返回的是 200/404 + `{"code":-3106,"message":"登录已过期"}`，
        # 不是 401；不识别就会一直显示「可用」。
        if auth_header_name and "json" in ctype.lower() and (
                '"code":-3106' in text or "登录已过期" in text):
            sent = (client_auth or "").strip()
            current = self.rt.raw_auth_value()
            if not (sent and current and sent != current):
                try:
                    self.rt.mark_auth_invalid()
                except Exception:
                    pass
        text = rewrite_text(text, self.hosts, gw_origin)
        is_html = "html" in ctype.lower()
        if is_html:
            text = inject_no_referrer(text)
            ls_key = (self.site.get("local_storage_token_key") or "").strip()
            if ls_key:
                shared_token = self.rt.auth_header_value()
                if shared_token:
                    text = inject_local_storage(text, ls_key, shared_token)
            elif self.rt.browser_sync_cookies():
                # cookie 型站点：同事浏览器里可能存着上一轮的 jwt，SPA 会优先用它，
                # 401 后又被我们标成会话失效 → 全员被踢、页面反复刷新。
                # 每次加载都清掉缓存 jwt，强制 SPA 用刚注入的 user-token 重新换。
                text = inject_script(
                    text, "try{localStorage.removeItem('jwt')}catch(e){}")
        out = text.encode("utf-8")
        resp.close()
        # 上游是 gzip、我们重写后必须发明文；对较大的响应再压回去，
        # 否则详情页那种大 JSON/JS 在慢网络上会明显变卡。
        encoded = ""
        if len(out) > 1024 and "gzip" in (accept_encoding or "").lower():
            compressed = gzip.compress(out, 6)
            if len(compressed) < len(out):
                out = compressed
                encoded = "gzip"
        headers = self._response_headers(resp, gw_origin, drop_content_encoding=True)
        headers = [
            (k, v) for k, v in headers
            if k.lower() not in ("content-type", "content-length",
                                 "cache-control", "expires", "pragma",
                                 "content-encoding")
        ]
        headers.append(("Content-Type", _with_utf8(ctype)))
        if encoded:
            headers.append(("Content-Encoding", encoded))
        headers.append(("Content-Length", str(len(out))))
        if is_html:
            # 页面必须每次重新取：缓存住旧版 HTML 会出现「别人都好了，他还是白屏」
            # （旧 HTML 没有 no-referrer，CDN 403 → main.js 被 ORB 丢掉）
            headers.append(("Cache-Control", "no-store"))
            headers.append(("Referrer-Policy", "no-referrer"))
        headers.extend(("Set-Cookie", c) for c in set_cookies)
        start_response(status, headers)
        return [out]

    def _stream(self, resp):
        def gen():
            try:
                for chunk in resp.raw.stream(CHUNK, decode_content=False):
                    if chunk:
                        yield chunk
            finally:
                try:
                    resp.close()
                except Exception:
                    pass
        return gen()

    def _stream_with_prefix(self, prefix: bytes, resp):
        def gen():
            try:
                if prefix:
                    yield prefix
                for chunk in resp.raw.stream(CHUNK, decode_content=False):
                    if chunk:
                        yield chunk
            finally:
                try:
                    resp.close()
                except Exception:
                    pass
        return gen()

    # ---------------- 头处理 ----------------

    def _read_body(self, environ, length: int):
        if length <= 0:
            return None
        return environ["wsgi.input"].read(length)

    def _request_headers(self, environ) -> dict:
        headers = {}
        for key, value in environ.items():
            if not key.startswith("HTTP_"):
                continue
            name = key[5:].replace("_", "-").title()
            if name.lower() in REQ_STRIP:
                continue
            headers[name] = value
        ctype = environ.get("CONTENT_TYPE")
        if ctype:
            headers["Content-Type"] = ctype
        return headers

    def _rewrite_ref(self, referer: str) -> str:
        parts = urlsplit(referer)
        if (parts.hostname or "").lower() in self.hosts:
            return self.origin + (parts.path or "/") + (("?" + parts.query) if parts.query else "")
        return referer

    def _response_headers(self, resp, gw_origin, drop_content_encoding: bool) -> list:
        headers = []
        for key, value in resp.headers.items():
            lk = key.lower()
            if lk in DROP_RESP_HEADERS:
                continue
            if drop_content_encoding and lk == "content-encoding":
                continue
            if lk == "location":
                value = self._rewrite_location(value, gw_origin)
            headers.append((key, value))
        headers.append(("Cache-Control", "no-store"))
        return headers

    def _rewrite_location(self, location: str, gw_origin: str) -> str:
        parts = urlsplit(location)
        if (parts.hostname or "").lower() in self.hosts:
            out = gw_origin + (parts.path or "/")
            if parts.query:
                out += "?" + parts.query
            if parts.fragment:
                out += "#" + parts.fragment
            return out
        return location

    def _set_cookie_list(self, resp) -> list[str]:
        raw_headers = getattr(resp.raw, "headers", None)
        cookies = []
        if raw_headers is not None and hasattr(raw_headers, "getlist"):
            cookies = list(raw_headers.getlist("Set-Cookie") or [])
        if not cookies:
            single = resp.headers.get("Set-Cookie")
            if single:
                cookies = [single]
        return [c for c in cookies if c]

    def _absorb_response_cookies(self, resp) -> None:
        for sc in self._set_cookie_list(resp):
            self.rt.absorb(sc, self.upstream_host)

    def _browser_cookies(self, resp) -> list[str]:
        """先落罐，再返回可下发浏览器的 Set-Cookie 值列表（httpOnly 不下发）。"""
        values = []
        now_ts = time.time()
        for sc in self._set_cookie_list(resp):
            self.rt.absorb(sc, self.upstream_host)
            parsed = jar_mod.parse_set_cookie(sc, self.upstream_host, now_ts)
            if not parsed or parsed.get("h"):
                continue
            parts = [f"{parsed['n']}={parsed['v']}", f"Path={parsed.get('p') or '/'}"]
            if parsed.get("e"):
                parts.append(f"Max-Age={max(0, int(parsed['e'] - now_ts))}")
            parts.append("SameSite=Lax")
            values.append("; ".join(parts))
        return values

    # ---------------- 错误页 ----------------

    def _unauthorized(self, start_response, message: str = ""):
        msg = html_mod.escape(
            message or "请从 GG-Server 的「共享账号」页面打开，本页面不支持直接访问。")
        body = (
            "<!doctype html><meta charset='utf-8'><title>需要登录 GG-Server</title>"
            "<body style='font-family:system-ui;background:#f8fafc;color:#334155;padding:10vh 8vw'>"
            "<h2>需要从 GG-Server 进入</h2><p>" + msg + "</p>"
            "<p style='color:#94a3b8'>共享账号网关 · 会话保护中</p></body>"
        ).encode("utf-8")
        start_response("401 Unauthorized", [
            ("Content-Type", "text/html; charset=utf-8"),
            ("Content-Length", str(len(body))),
        ])
        return [body]

    def _error_page(self, start_response, code: int, message: str):
        body = (
            "<!doctype html><meta charset='utf-8'><title>网关错误</title>"
            "<body style='font-family:system-ui;background:#fff7ed;color:#7c2d12;padding:10vh 8vw'>"
            f"<h2>共享账号网关错误（{code}）</h2><p>{html_mod.escape(message)}</p>"
            "<p><a href='javascript:location.reload()'>重试</a></p></body>"
        ).encode("utf-8")
        reason = {413: "Payload Too Large", 502: "Bad Gateway", 403: "Forbidden"}.get(code, "Error")
        start_response(f"{code} {reason}", [
            ("Content-Type", "text/html; charset=utf-8"),
            ("Content-Length", str(len(body))),
        ])
        return [body]
