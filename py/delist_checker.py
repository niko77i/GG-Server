"""Google Play / App Store 掉包检测模块。

通过 HTTP 请求应用商店链接，判断应用是否已被下架。
"""

import requests

# 移动端 User-Agent（Google Play 与 App Store 通用）
_USER_AGENT = (
    "Mozilla/5.0 (Linux; Android 13; Pixel 7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Mobile Safari/537.36"
)

# 掉包判定关键词
_DELISTED_PATTERNS = [
    "not found on this server",
    "找不到请求的网址",
    "We're sorry, the requested URL was not found",
]

# 判定未知的响应状态码：429（限流）与**任意** 5xx（500-599，服务端异常）。
# 命中时本次无法判定，交由调用方换代理重试。
# 实测依据：App Store 对掉包链接返回 404，被限流时返回 429，两者响应体同为
# 2383 字节，只能靠状态码区分；旧逻辑只认 404，会把 429 当成「正常」，
# 进而用 INSERT OR REPLACE 抹掉上一轮正确的掉包记录。
# 原实现是枚举集合 {429, 500, 502, 503, 504}，501/505 等冷门 5xx 会漏成「正常」，
# 后果同型 —— 故改为按区间判定。
def _is_indeterminate_status(status_code: int) -> bool:
    """429 或任意 5xx 均视为「拿不到判定」。"""
    return status_code == 429 or 500 <= status_code < 600


_TIMEOUT = 15  # 请求超时秒数


class DelistIndeterminate(Exception):
    """响应状态为 429 或任意 5xx，本次判定结果未知。

    调用方应保留上一轮判定结果，不得当作「正常」写入。
    """


def _request_and_judge(url: str, proxies: dict | None) -> tuple[bool, str]:
    """发请求并判掉包；网络异常直接抛出，由调用方处理。

    Args:
        url: 应用商店链接（Google Play 或 App Store）
        proxies: requests 的 proxies 参数，None 表示直连

    Raises:
        DelistIndeterminate: 状态码为 429 或任意 5xx（500-599），本次无法判定
    """
    resp = requests.get(
        url,
        headers={"User-Agent": _USER_AGENT},
        timeout=_TIMEOUT,
        allow_redirects=True,
        proxies=proxies,
    )

    # 1. HTTP 404
    if resp.status_code == 404:
        return True, ""

    # 2. 限流 / 服务端异常：结果未知，抛出让调用方换代理重试
    if _is_indeterminate_status(resp.status_code):
        raise DelistIndeterminate(f"HTTP {resp.status_code}")

    # 3. 检查页面内容关键词
    text_lower = resp.text.lower()
    for pattern in _DELISTED_PATTERNS:
        if pattern.lower() in text_lower:
            return True, ""

    return False, ""


def check_url_delisted(url: str, proxy_pool=None) -> tuple[bool | None, str]:
    """检测单个应用链接是否已掉包。

    Args:
        url: 应用商店链接（Google Play 或 App Store）
        proxy_pool: ProxyPool 实例；None 时走原直连逻辑

    Returns:
        (is_delisted, error)：
          True  → 已掉包
          False → 正常（拿到了判定，且判为在架）
          None  → 判定未知（限流/服务端异常/超时/连接失败/解析失败/空 url），
                  调用方应保留上一次判定结果，不得覆盖
    """
    if not url or not url.strip():
        return None, "URL 为空，无法判定"

    # 无代理池：直连；拿不到判定（限流/服务端异常/超时/连接失败/解析失败）一律返回「未知」
    if proxy_pool is None:
        try:
            return _request_and_judge(url, None)
        except DelistIndeterminate as e:
            return None, f"{e} 限流或服务端异常，判定未知"
        except requests.Timeout:
            return None, "请求超时，无法判定"
        except requests.ConnectionError:
            return None, "网络连接失败，无法判定"
        except Exception as e:
            return None, f"{e}，无法判定"

    # 有代理池：失败换下一个代理重试，绝不因代理失败误判为掉包
    if proxy_pool.count == 0:
        return None, "代理池为空，无法判定"

    tried = set()
    last_error = ""
    last_indeterminate = ""
    for _ in range(proxy_pool.max_retries):
        proxy = proxy_pool.next(exclude=tried)
        if proxy is None:
            break
        tried.add((proxy["ip"], proxy["port"]))
        try:
            return _request_and_judge(url, proxy_pool.to_requests(proxy))
        except DelistIndeterminate as e:
            last_indeterminate = f"{e} @ {proxy['ip']}:{proxy['port']}"
        except requests.Timeout:
            last_error = f"代理超时 {proxy['ip']}:{proxy['port']}"
        except requests.ConnectionError:
            last_error = f"代理连接失败 {proxy['ip']}:{proxy['port']}"
        except Exception as e:
            last_error = f"代理异常 {proxy['ip']}:{proxy['port']}: {e}"

    # 出现过限流/服务端异常 → 整体判为未知（保守：既不算掉包也不算正常）
    if last_indeterminate:
        return None, f"代理响应异常（限流/服务端）: {last_indeterminate}"
    return None, f"代理全部失败: {last_error}，无法判定"


def check_product_packages(product_id: int, packages: list[dict], proxy_pool=None) -> list[dict]:
    """检测一个产品下所有包的掉包状态。

    Args:
        product_id: 产品 ID
        packages: 包字典列表，每个包需包含 id, url, package_name
        proxy_pool: ProxyPool 实例；None 时直连

    Returns:
        检测结果列表，每个元素包含 package_id, is_delisted, error。
        is_delisted 为 True/False/None（None 表示判定未知）。
        空 url 由本函数直接判为 None（无法判定），其余原样透传 check_url_delisted 的结果。
    """
    results = []
    for pkg in packages:
        pkg_id = pkg.get("id")
        url = (pkg.get("url") or "").strip()

        if not url:
            results.append({
                "package_id": pkg_id,
                "product_id": product_id,
                "is_delisted": None,
                "error": "URL 为空，无法判定",
            })
            continue

        if proxy_pool is None:
            is_delisted, error = check_url_delisted(url)
        else:
            is_delisted, error = check_url_delisted(url, proxy_pool)
        results.append({
            "package_id": pkg_id,
            "product_id": product_id,
            "is_delisted": is_delisted,
            "error": error,
        })

    return results
