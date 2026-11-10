"""每个站点的运行时状态：内存会话罐 + 落库 + 状态自检。

一个站点对应一个网关端口、一个 `SiteRuntime`。会话罐启动时从库里解密加载，
此后所有 Set-Cookie 先更新内存、再整串加密落库（崩溃后能恢复，不用重新登录）。
"""
import json
import threading
import time
from urllib.parse import urljoin, urlsplit

import requests

from share_gateway import jar as jar_mod, store

AUTH_COOKIES = ("ZFSESSID", "user-token")

# 只同步这两类「原站 SPA 自己写进 document.cookie」的令牌。
# 原因：服务端 Set-Cookie 里根本没有 user-token（它是登录成功后 JS 写的），
# 而 SPA 每个接口都要 `x-nbs-user-token`；换一个端口/主机打开时浏览器里没有它，
# 前端就会认为「未登录」。
#
# ⚠️ 不放开成「同步所有 cookie」：任何登录用户都能随手改 document.cookie，
# 全量学习等于允许他污染共享会话罐。只认这两个鉴权名。
BROWSER_SYNC_COOKIES = ("user-token", "x-token")

# 有些站点（如 insightrackr）不用 cookie，而是 localStorage 存 token、
# 每个请求带 `Authorization: <token>`。用一个内部伪条目存在同一个加密罐里。
AUTH_PSEUDO = "__auth_header"

# SPA 用 `setCookie("user-token", token, 72)` 写 cookie，即 72 小时。
# 学习时按这个口径记到期时间：否则罐里会留一个「永不过期」的假会话，
# 过期后页面一直报错、状态却显示正常。
LEARNED_TOKEN_TTL = 72 * 3600

# 没有绝对到期时间的会话 cookie（`Set-Cookie` 不带 Max-Age/Expires）不能当永不过期。
# 按已知形态给一个保守 TTL，状态自检才能真的变成「需重新登录」。
SESSION_TTL = {
    "ZFSESSID": 30 * 24 * 3600,   # 扩展实测约 30 天
    "user-token": LEARNED_TOKEN_TTL,
    "x-token": LEARNED_TOKEN_TTL,
}
DEFAULT_SESSION_TTL = 24 * 3600


class SiteRuntime:
    def __init__(self, site: dict, secret: str):
        self.site = dict(site)
        self.site_id = site["id"]
        self.upstream = (site.get("upstream") or "").rstrip("/")
        self.upstream_host = (urlsplit(self.upstream).hostname or "").lower()
        self.extra_hosts = [h.strip().lower() for h in (site.get("extra_hosts") or []) if h.strip()]
        self.secret = secret
        self.key = jar_mod.key_for(secret, self.site_id)
        self._lock = threading.Lock()
        self._jar: list = []
        self.status = "unknown"
        self.last_error = None
        self.listening = False
        self.ver = 0
        # 学到 user-token 的那个 GG-Server 用户；只允许本人再更新它，
        # 防止「任何登录用户登录原站后把自己的 token 变成全员共享会话」。
        self.token_uid: str | None = None
        self.load()

    # ---------------- 会话罐 ----------------

    def load(self) -> None:
        row = store.get_session(self.site_id)
        if not row:
            return
        self.status = row.get("status") or "unknown"
        self.last_error = row.get("last_error")
        self.ver = int(row.get("ver") or 0)
        blob = row.get("cookies_enc")
        if not blob:
            return
        text = jar_mod.unseal(blob, self.key)
        if not text:
            # 密钥变了 / 数据损坏：当作未登录，但保留状态提示
            self.last_error = "会话罐解密失败，需要重新登录"
            self.status = "expired"
            return
        try:
            data = json.loads(text)
        except ValueError:
            return
        if isinstance(data, list):
            self._jar = [c for c in data if isinstance(c, dict) and c.get("n")]
        # 非 cookie 型站点不保留浏览器 cookie 令牌：同主机不同端口会串站
        if self.site.get("auth_header"):
            self._jar = [c for c in self._jar if c.get("n") not in BROWSER_SYNC_COOKIES]
        # 兼容早期版本学到的「无到期时间」令牌：按 72 小时口径补上，避免永不过期
        now = time.time()
        for cookie in self._jar:
            if cookie.get("n") in BROWSER_SYNC_COOKIES and cookie.get("e") is None:
                cookie["e"] = now + LEARNED_TOKEN_TTL
            cookie.setdefault("fs", now)

    def _persist_locked(self) -> None:
        try:
            blob = jar_mod.seal(json.dumps(self._jar, ensure_ascii=False), self.key)
            store.save_session(self.site_id, blob)
        except Exception as exc:  # 落库失败不能影响转发
            self.last_error = f"会话罐落库失败: {exc}"

    def absorb(self, set_cookie_header: str, default_domain: str) -> None:
        """把上游 Set-Cookie 并进罐子并落库。"""
        cookie = jar_mod.parse_set_cookie(set_cookie_header, default_domain)
        if not cookie:
            return
        cookie.setdefault("fs", time.time())
        with self._lock:
            self._jar = jar_mod.merge(self._jar, cookie)
            self._persist_locked()
            if self.status != "ok":
                self.status = "ok"
                self.last_error = None
                try:
                    store.update_status(self.site_id, "ok", None, ok=True)
                except Exception:
                    pass

    def cookie_header(self, host: str, path: str) -> str:
        with self._lock:
            return jar_mod.cookie_header(self._jar, host, path)

    # ---------------- 浏览器侧令牌同步 ----------------

    def learn_browser_cookies(self, cookie_header: str, uid=None) -> None:
        """把 SPA 写在 document.cookie 里的鉴权令牌收进会话罐。

        `user-token` 是登录后 JS 通过 `document.cookie` 写的，**不会出现在上游的
        Set-Cookie 里**；不学习它，换一个主机/端口打开时 SPA 会认为未登录
        （前端逻辑：`getJwt() || !user-token` ⇒ 不发请求）。

        防污染（2026-11-06 审查）：
        **罐里已有「未过期」令牌时，一律不接受别的值**（不论来源 uid）。
        想换令牌只有两条路：
        - 会话被上游判 401 → `mark_auth_invalid()` 把旧令牌标成过期，下一次登录自然学进来；
        - 管理员点「清空会话」。
        这样既不会被同事的号顶掉，也不会被旧浏览器把管理员刚重登的 token 回滚。
        """
        cookies = jar_mod.parse_cookie_header(cookie_header)
        now = time.time()
        changed = False
        with self._lock:
            for name in BROWSER_SYNC_COOKIES:
                value = cookies.get(name)
                if not value:
                    continue
                existing = next(
                    (c for c in self._jar
                     if c.get("n") == name and c.get("d") == self.upstream_host),
                    None,
                )
                if existing and existing.get("v") == value:
                    continue
                if existing and (existing.get("e") is None or existing["e"] > now):
                    # 旧令牌还没过期：不覆盖。真失效由 401 侧标记，见 mark_auth_invalid
                    continue
                self._jar = jar_mod.merge(self._jar, {
                    "n": name, "v": value, "d": self.upstream_host, "p": "/",
                    "e": now + LEARNED_TOKEN_TTL, "s": False, "h": False,
                    "ho": True, "ss": "", "fs": now,
                })
                changed = True
                if uid is not None:
                    self.token_uid = str(uid)
            if changed:
                self._persist_locked()

    def mark_auth_invalid(self) -> None:
        """上游判 401 时调用：把已学到的浏览器令牌标成过期。

        不这么做的话，令牌在服务端已失效、但本地 `e` 还没到，状态会一直显示可用，
        而且新登录的 token 也学不进来（被「已有有效令牌不覆盖」挡住）。
        """
        now = time.time()
        changed = False
        with self._lock:
            for cookie in self._jar:
                if cookie.get("n") in BROWSER_SYNC_COOKIES or cookie.get("n") == AUTH_PSEUDO:
                    cookie["e"] = now - 1
                    changed = True
            if changed:
                self._persist_locked()
            self.status = "expired"
            self.last_error = "上游返回 401，会话已失效，需要重新登录"
        try:
            store.update_status(self.site_id, "expired", self.last_error, ok=False)
        except Exception:
            pass

    # ---------------- 非 cookie 型令牌（Authorization 头 + localStorage） ----------------

    def learn_auth_header(self, value: str) -> None:
        """学站点用 `Authorization` 头携带的令牌（insightrackr 这类 localStorage 站点）。"""
        value = (value or "").strip()
        # insightrackr 的接口只认裸 token；带 Bearer 会被判「token 转码错误」
        if value[:7].lower() == "bearer ":
            value = value[7:].strip()
        if not value or value.lower() in ("undefined", "null", "none"):
            return
        now = time.time()
        with self._lock:
            existing = next((c for c in self._jar if c.get("n") == AUTH_PSEUDO), None)
            if existing and existing.get("v") == value:
                return
            if existing and (existing.get("e") is None or existing["e"] > now):
                return
            self._jar = jar_mod.merge(self._jar, {
                "n": AUTH_PSEUDO, "v": value, "d": self.upstream_host, "p": "/",
                "e": now + LEARNED_TOKEN_TTL, "s": False, "h": True, "ho": True,
                "ss": "", "fs": now,
            })
            self._persist_locked()

    def auth_header_value(self) -> str:
        now = time.time()
        with self._lock:
            for c in self._jar:
                if c.get("n") == AUTH_PSEUDO and (c.get("e") is None or c["e"] > now):
                    return c.get("v") or ""
        return ""

    def raw_auth_value(self) -> str:
        """不看过期时间，拿 Authorization 伪条目的值（用于判断 401 是不是旧令牌造成）。"""
        with self._lock:
            for c in self._jar:
                if c.get("n") == AUTH_PSEUDO:
                    return c.get("v") or ""
        return ""

    def raw_cookie_value(self, name: str) -> str:
        """不看过期时间，拿某个 cookie 的值。"""
        with self._lock:
            for c in self._jar:
                if c.get("n") == name:
                    return c.get("v") or ""
        return ""

    def _restore_cookie(self, name: str, value: str) -> None:
        now = time.time()
        with self._lock:
            self._jar = jar_mod.merge(self._jar, {
                "n": name, "v": value, "d": self.upstream_host, "p": "/",
                "e": now + LEARNED_TOKEN_TTL, "s": False, "h": False, "ho": False,
                "ss": "", "fs": now,
            })
            self._persist_locked()

    def probe_auth(self) -> tuple[str, str | None]:
        """真的拿令牌去调一次上游接口，判断会话是否还有效。

        - `auth_header` 型（Insightrackr）：用 Authorization 头；
        - cookie 型（广大大）：配置 `auth_check_cookie` 后，用 Cookie + x-nbs-user-token 探。
          即便本地已经把 cookie 标成过期，也会拿原始值试一次 —— 探通就恢复有效期，
          避免「一个旧浏览器的 401 把全员的会话判死，但点开其实还能用」。
        """
        path = (self.site.get("auth_check_path") or "").strip()
        if not path:
            return "unknown", None
        auth_header = (self.site.get("auth_header") or "").strip()
        cookie_name = (self.site.get("auth_check_cookie") or "").strip()
        token = self.auth_header_value() if auth_header else (
            self.raw_cookie_value(cookie_name) if cookie_name else "")
        if not token:
            return "unknown", None
        headers = {
            "Accept": "application/json, text/plain, */*",
            "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                           "AppleWebKit/537.36 (KHTML, like Gecko) "
                           "Chrome/126.0.0.0 Safari/537.36"),
        }
        if auth_header:
            headers[auth_header] = token
        else:
            headers["Cookie"] = f"{cookie_name}={token}"
            headers["x-nbs-user-token"] = token
        try:
            resp = requests.get(
                urljoin(self.upstream + "/", path.lstrip("/")),
                headers=headers, timeout=15,
            )
        except requests.RequestException as exc:
            return "unknown", f"检测失败：{exc}"
        body = resp.text[:800]
        expired = (resp.status_code in (401, 403)
                   or "-3106" in body or "登录已过期" in body)
        if expired:
            self.mark_auth_invalid()
            return "expired", "登录已过期，需要重新登录"
        if resp.status_code == 200:
            # 探测通过：cookie 型站点如果之前被旧浏览器的 401 误标过期，这里恢复有效期
            if not auth_header and cookie_name:
                self._restore_cookie(cookie_name, token)
            return "ok", None
        if resp.status_code >= 500:
            return "unknown", f"检测失败：上游 {resp.status_code}"
        return "unknown", f"检测返回 {resp.status_code}"

    def mark_auth_ok(self) -> None:
        """有已鉴权接口返回 200 时调用：如果之前被误标过期，把 cookie 有效期恢复。

        典型场景：某个旧浏览器 401 把共享会话标成「需重新登录」，但其实令牌还能用；
        只要有人用共享会话成功调通一个接口，就说明它是好的。
        """
        now = time.time()
        changed = False
        with self._lock:
            for c in self._jar:
                if c.get("n") in AUTH_COOKIES and c.get("e") is not None and c["e"] <= now:
                    c["e"] = now + LEARNED_TOKEN_TTL
                    changed = True
            if changed:
                self._persist_locked()
            if self.status != "ok":
                self.status = "ok"
                self.last_error = None
        try:
            store.update_status(self.site_id, "ok", None, ok=True)
        except Exception:
            pass

    def browser_sync_cookies(self) -> list[dict]:
        """需要下发到浏览器、让 SPA 读到的非 httpOnly 令牌。"""
        with self._lock:
            return [
                {"n": c["n"], "v": c["v"], "p": c.get("p") or "/"}
                for c in self._jar
                if not c.get("h") and c.get("n") in BROWSER_SYNC_COOKIES
            ]


    def clear(self) -> None:
        with self._lock:
            self._jar = []
            self._persist_locked()
            self.status = "unknown"
            self.last_error = None
            self.token_uid = None
        # 代次 +1：已发出去的 __sgw cookie 立即失效（否则 12 小时内仍能进）
        try:
            self.ver = store.bump_ver(self.site_id)
        except Exception:
            pass
        store.update_status(self.site_id, "unknown", "会话已清空，等待重新登录", ok=False)

    def bump_ver(self) -> None:
        """停用站点时调用：让已发出的网关 cookie 立即失效。"""
        try:
            self.ver = store.bump_ver(self.site_id)
        except Exception:
            pass

    def snapshot(self) -> list:
        with self._lock:
            return list(self._jar)

    def count(self) -> int:
        with self._lock:
            return len(self._jar)

    # ---------------- 状态自检 ----------------

    def check_status(self) -> tuple[str, str | None]:
        """按会话罐判断登录态；不发起额外网络请求。

        - 罐子为空 → unknown（还没人登录过）
        - 有未过期的鉴权 cookie → ok
        - 鉴权 cookie 全部过期 → expired（需要管理员重登）

        ⚠️ 没有绝对到期时间的会话 cookie（典型：`ZFSESSID`）不能直接当「永不过期」，
        这里按 `first_seen + 该类 cookie 的保守 TTL` 估一个到期时刻。
        """
        now = time.time()
        jar = self.snapshot()
        if not jar:
            return "unknown", "尚未登录"
        if self.site.get("auth_header"):
            if self.auth_header_value():
                return "ok", None
            return "expired", "会话已过期，需要重新登录"
        auth = [c for c in jar if c.get("n") in AUTH_COOKIES]
        if not auth:
            # 有 cookie 但没有已知鉴权名：无法判断，按 ok 处理（避免误报）
            return "ok", None
        if any(self._effective_expiry(c, now) > now for c in auth):
            return "ok", None
        return "expired", "会话已过期，需要重新登录"

    @staticmethod
    def _effective_expiry(cookie: dict, now: float) -> float:
        exp = cookie.get("e")
        if exp is not None:
            return float(exp)
        first_seen = cookie.get("fs") or now
        return float(first_seen) + SESSION_TTL.get(
            cookie.get("n"), DEFAULT_SESSION_TTL)

    def refresh_status(self) -> tuple[str, str | None]:
        probed_status, probed_error = "unknown", None
        if self.site.get("auth_check_path"):
            probed_status, probed_error = self.probe_auth()
        if probed_status == "expired":
            status, error = "expired", probed_error
        elif probed_status == "ok":
            status, error = "ok", None
        else:
            status, error = self.check_status()
        self.status, self.last_error = status, error
        try:
            if status == "ok":
                store.update_status(self.site_id, "ok", None, ok=True)
            else:
                store.update_status(self.site_id, status, error, ok=False)
        except Exception:
            pass
        return status, error

    def describe(self) -> dict:
        jar = self.snapshot()
        now = time.time()
        exp = None
        if self.site.get("auth_header"):
            pseudo = next((c for c in jar if c.get("n") == AUTH_PSEUDO), None)
            if pseudo and (pseudo.get("e") is None or pseudo["e"] > now):
                exp = pseudo.get("e")
        if exp is None:
            auth = [c for c in jar if c.get("n") in AUTH_COOKIES]
            exp = min((self._effective_expiry(c, now) for c in auth), default=None)
        return {
            "site_id": self.site_id,
            "status": self.status,
            "last_error": self.last_error,
            "cookie_count": len([c for c in jar if not (c.get("n") or "").startswith("__")]),
            "expires_at": exp,
            "running": True,
        }
