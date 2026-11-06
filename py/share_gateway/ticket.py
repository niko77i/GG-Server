"""共享账号网关的票据与会话签名。

两种令牌：
1. **进入票据**（ticket）：GG-Server 签发，60 秒有效、一次性（nonce 只能消费一次）。
   带在网关入口 URL 的 `?t=` 上，用来把「已登录 GG-Server 的用户」换成网关 cookie。
2. **网关会话 cookie**（`__sgw`）：进入时种下，12 小时有效；之后每个代理请求都验它，
   防止局域网里没登录 GG-Server 的人直接访问网关端口。

两者都是 `base64url(payload) + "." + HMAC-SHA256(secret, body)`，payload 里带 `typ`
区分，避免把票据当 cookie 用（反之亦然）。
"""
import base64
import hashlib
import hmac
import json
import secrets
import threading
import time

TICKET_TTL = 60
COOKIE_TTL = 12 * 3600
COOKIE_NAME = "__sgw"


def cookie_name(site: str) -> str:
    """每个站点一个 cookie 名。

    ⚠️ 浏览器 cookie **不区分端口**：网关 8901（广大大）与 8902（有米云）在同主机下
    共享 cookie 命名空间。若都用 `__sgw`，打开第二个站点会拿第一个站点的 cookie
    去验签（site 不匹配 → 401）。故按站点分名。
    """
    safe = "".join(ch for ch in (site or "") if ch.isalnum() or ch in "-_")
    return f"{COOKIE_NAME}_{safe or 'default'}"

# nonce -> 过期时刻；只在进程内（waitress 单进程多线程），重启即清空。
_nonces: dict[str, float] = {}
_nonce_lock = threading.Lock()


def _b64e(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _b64d(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def _sign(secret: str, body: str) -> str:
    return hmac.new(secret.encode("utf-8"), body.encode("ascii"), hashlib.sha256).hexdigest()


def _make(secret: str, payload: dict) -> str:
    body = _b64e(json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8"))
    return body + "." + _sign(secret, body)


def _parse(secret: str, token: str) -> dict | None:
    if not token or "." not in token:
        return None
    try:
        token.encode("ascii")  # 非 ASCII 的 t / cookie 直接当无效，别抛异常打 500 日志
    except UnicodeEncodeError:
        return None
    body, sig = token.rsplit(".", 1)
    try:
        if not hmac.compare_digest(_sign(secret, body), sig):
            return None
        payload = json.loads(_b64d(body).decode("utf-8"))
    except (ValueError, UnicodeDecodeError, TypeError):
        return None
    if not isinstance(payload, dict):
        return None
    return payload


def _prune(now: float) -> None:
    for nonce, exp in list(_nonces.items()):
        if exp <= now:
            _nonces.pop(nonce, None)


def issue_ticket(secret: str, site: str, uid: int, name: str, ttl: int = TICKET_TTL) -> str:
    """签发一次性进入票据。"""
    return _make(secret, {
        "typ": "ticket",
        "site": site,
        "uid": uid,
        "name": name,
        "exp": int(time.time()) + ttl,
        "nonce": secrets.token_hex(8),
    })


def verify_ticket(secret: str, token: str) -> dict | None:
    """校验票据并消费 nonce。重复使用同一张票据返回 None。"""
    payload = _parse(secret, token)
    if not payload or payload.get("typ") != "ticket":
        return None
    now = time.time()
    if int(payload.get("exp") or 0) <= now:
        return None
    nonce = payload.get("nonce")
    if not nonce:
        return None
    with _nonce_lock:
        _prune(now)
        if nonce in _nonces:
            return None
        _nonces[nonce] = now + TICKET_TTL + 5
    return payload


def make_cookie(secret: str, site: str, uid: int, name: str, ttl: int = COOKIE_TTL,
                ver: int = 0) -> str:
    """签发网关会话 cookie 值。

    `ver` 是站点会话代次：清空会话 / 停用站点时 +1，用来吊销已发出的 cookie。
    """
    return _make(secret, {
        "typ": "cookie",
        "site": site,
        "uid": uid,
        "name": name,
        "exp": int(time.time()) + ttl,
        "ver": int(ver),
    })


def verify_cookie(secret: str, token: str) -> dict | None:
    """校验网关会话 cookie（可重复使用，不消费）。"""
    payload = _parse(secret, token)
    if not payload or payload.get("typ") != "cookie":
        return None
    if int(payload.get("exp") or 0) <= time.time():
        return None
    return payload
