"""短时效签名 URL 工具。

## 为什么需要

`<img src>` / CSS `@font-face url()` / `<audio src>` / `window.open()` 这类**浏览器原生请求**，
由渲染引擎发起，**无法附加 `Authorization` 头**，因此走不了 JWT 鉴权。

签名 URL 解决这个问题：由**受 JWT 保护的 axios 接口**下发一个带 HMAC 签名的完整 URL，
前端把它交给浏览器原生请求消费。下载权限因而绑定到「持有有效会话」。

## 安全性质

- `endpoint` 参与签名 ⇒ 一个下载 URL **不能**挪用到另一个端点。
- `path` 参与签名 ⇒ 改路径即失效。
- `exp` 参与签名 ⇒ 不能把过期时间改大。
- 比对用 `hmac.compare_digest` ⇒ 恒定时间，避免时序侧信道。
- 任何字段缺失 / 非数字 / 过期 ⇒ **一律 False**（fail-closed）。
- 默认 TTL 300 秒 —— 短到足以把「URL 被转发」的窗口压到最小。
"""
import hashlib
import hmac
import time
from urllib.parse import quote

DEFAULT_TTL = 300  # 秒


def _digest(endpoint: str, path: str, exp: int, secret: str) -> str:
    payload = f"{endpoint}\n{path}\n{exp}".encode("utf-8")
    return hmac.new(secret.encode("utf-8"), payload, hashlib.sha256).hexdigest()


def sign_query(endpoint: str, path: str, secret: str,
               ttl: int = DEFAULT_TTL, now: float | None = None) -> str:
    """生成签名 query 串：`path=...&exp=...&sig=...`（path 已 URL 编码）。"""
    exp = int((now if now is not None else time.time()) + ttl)
    sig = _digest(endpoint, path, exp, secret)
    return f"path={quote(path)}&exp={exp}&sig={sig}"


def verify_query(endpoint: str, path: str, exp: str, sig: str, secret: str,
                 now: float | None = None) -> bool:
    """校验签名。任何异常情况均返回 False（调用方据此返回 401）。"""
    if not path or not exp or not sig:
        return False
    try:
        exp_i = int(exp)
    except (TypeError, ValueError):
        return False
    if exp_i < int(now if now is not None else time.time()):
        return False
    return hmac.compare_digest(_digest(endpoint, path, exp_i, secret), sig)
