"""会话罐：Set-Cookie 解析、合并、按请求筛选，以及 AES-256-GCM 落库加密。

存储格式（列表，每项一个 cookie）：
    {"n": 名称, "v": 值, "d": 域名, "p": 路径, "e": 到期 epoch 或 null,
     "s": secure, "h": httpOnly, "ho": 是否 host-only}

⚠️ 浏览器 cookie **不区分端口**：网关在 8901 种下的 `__sgw`、以及原站下发到浏览器的
`user-token`，也会随请求发到 GG-Server 的 5001 端口。所以这里只下发**非 httpOnly**
的 cookie（JS 需要读），httpOnly 的会话锚点（如 `ZFSESSID`）只留在服务端。
"""
import base64
import hashlib
import os
import time
from email.utils import parsedate_to_datetime
from http.cookies import SimpleCookie

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

MAX_COOKIES = 200


def parse_cookie_header(header: str) -> dict[str, str]:
    """把浏览器发来的 Cookie 头解析成 {name: value}。"""
    out = {}
    for part in (header or "").split(";"):
        if "=" not in part:
            continue
        name, value = part.split("=", 1)
        name = name.strip()
        if name:
            out[name] = value.strip()
    return out


def key_for(secret: str, site: str) -> bytes:
    """从全局 secret 派生每个站点独立的 32 字节密钥。"""
    return hashlib.sha256(f"{secret}|share-gateway|{site}".encode("utf-8")).digest()


def parse_set_cookie(header: str, default_domain: str = "", now: float | None = None) -> dict | None:
    """解析一条 Set-Cookie。失败或空值返回 None。"""
    cookie = SimpleCookie()
    try:
        cookie.load(header)
    except Exception:
        return None
    if not cookie:
        return None
    name, morsel = next(iter(cookie.items()))
    if not name or name.startswith("$"):
        return None

    raw_domain = (morsel["domain"] or "").strip().lower()
    host_only = not raw_domain
    domain = (default_domain if host_only else raw_domain).strip().lower().lstrip(".")

    expires = None
    max_age = morsel["max-age"]
    if max_age:
        try:
            expires = (now if now is not None else time.time()) + int(max_age)
        except (TypeError, ValueError):
            expires = None
    if expires is None and morsel["expires"]:
        try:
            dt = parsedate_to_datetime(morsel["expires"])
            if dt.tzinfo is None:
                from datetime import timezone
                dt = dt.replace(tzinfo=timezone.utc)
            expires = dt.timestamp()
        except Exception:
            expires = None

    return {
        "n": name,
        "v": morsel.value,
        "d": domain,
        "p": morsel["path"] or "/",
        "e": expires,
        "s": bool(morsel["secure"]),
        "h": bool(morsel["httponly"]),
        "ho": host_only,
        "ss": (morsel["samesite"] or "").strip().lower(),
    }


def merge(jar: list, cookie: dict, now: float | None = None) -> list:
    """把一条 cookie 合并进罐子（同 name+domain+path 覆盖）。过期的不入罐。"""
    now = time.time() if now is None else now
    out = [c for c in jar if not (
        c.get("n") == cookie.get("n")
        and c.get("d") == cookie.get("d")
        and c.get("p") == cookie.get("p")
    )]
    if cookie.get("e") is None or cookie["e"] > now:
        out.append(cookie)
    if len(out) > MAX_COOKIES:
        out = out[-MAX_COOKIES:]
    return out


def match(jar: list, host: str, path: str, now: float | None = None) -> list:
    """筛出适用于 host/path 且未过期的 cookie，按 path 长度倒序。"""
    now = time.time() if now is None else now
    host = (host or "").lower()
    path = path or "/"
    hits = []
    for c in jar:
        if (c.get("n") or "").startswith("__"):
            continue  # 内部伪条目（如 __auth_header），不属于 Cookie 头
        if c.get("e") is not None and c["e"] <= now:
            continue
        domain = (c.get("d") or "").lower()
        if not domain:
            continue
        if c.get("ho"):
            if host != domain:
                continue
        elif not (host == domain or host.endswith("." + domain)):
            continue
        cpath = c.get("p") or "/"
        if not path.startswith(cpath):
            continue
        hits.append(c)
    hits.sort(key=lambda c: len(c.get("p") or "/"), reverse=True)
    return hits


def cookie_header(jar: list, host: str, path: str, now: float | None = None) -> str:
    """拼 Cookie 请求头。"""
    return "; ".join(f"{c['n']}={c['v']}" for c in match(jar, host, path, now))


def cookie_expiry(jar: list, names: tuple[str, ...] = ()) -> float | None:
    """返回指定名字（或全部）cookie 里最早的到期时刻；无绝对到期时间返回 None。"""
    exps = []
    for c in jar:
        if names and c.get("n") not in names:
            continue
        if c.get("e") is not None:
            exps.append(c["e"])
    return min(exps) if exps else None


def has_unexpired(jar: list, names: tuple[str, ...], now: float | None = None) -> bool:
    now = time.time() if now is None else now
    for c in jar:
        if c.get("n") in names and (c.get("e") is None or c["e"] > now):
            return True
    return False


def seal(text: str, key: bytes) -> str:
    """AES-256-GCM 加密，返回 base64url(nonce + 密文)。"""
    nonce = os.urandom(12)
    data = AESGCM(key).encrypt(nonce, text.encode("utf-8"), None)
    return base64.urlsafe_b64encode(nonce + data).decode("ascii")


def unseal(blob: str, key: bytes) -> str | None:
    """解密 seal() 的产物；失败（密钥变了 / 数据被改）返回 None。"""
    if not blob:
        return None
    try:
        raw = base64.urlsafe_b64decode(blob.encode("ascii"))
        nonce, data = raw[:12], raw[12:]
        return AESGCM(key).decrypt(nonce, data, None).decode("utf-8")
    except Exception:
        return None
