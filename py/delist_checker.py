"""Google Play 掉包检测模块。

通过 HTTP 请求 Google Play 链接，判断应用是否已被下架。
"""

import requests

# Google Play 移动端 User-Agent
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

_TIMEOUT = 15  # 请求超时秒数


def _request_and_judge(url: str, proxies: dict | None) -> tuple[bool, str]:
    """发请求并判掉包；网络异常直接抛出，由调用方处理。

    Args:
        url: Google Play 应用链接
        proxies: requests 的 proxies 参数，None 表示直连
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

    # 2. 检查页面内容关键词
    text_lower = resp.text.lower()
    for pattern in _DELISTED_PATTERNS:
        if pattern.lower() in text_lower:
            return True, ""

    return False, ""


def check_url_delisted(url: str, proxy_pool=None) -> tuple[bool, str]:
    """检测单个 Google Play URL 是否已掉包。

    Args:
        url: Google Play 应用链接
        proxy_pool: ProxyPool 实例；None 时走原直连逻辑

    Returns:
        (is_delisted, error): is_delisted=True 表示已掉包，
        error 为错误信息（正常为空字符串）
    """
    if not url or not url.strip():
        return False, ""

    # 无代理池：直连，行为与历史版本一致
    if proxy_pool is None:
        try:
            return _request_and_judge(url, None)
        except requests.Timeout:
            return False, "请求超时"
        except requests.ConnectionError:
            return False, "网络连接失败"
        except Exception as e:
            return False, str(e)

    # 有代理池：失败换下一个代理重试，绝不因代理失败误判为掉包
    if proxy_pool.count == 0:
        return False, "代理池为空"

    tried = set()
    last_error = ""
    for _ in range(proxy_pool.max_retries):
        proxy = proxy_pool.next(exclude=tried)
        if proxy is None:
            break
        tried.add((proxy["ip"], proxy["port"]))
        try:
            return _request_and_judge(url, proxy_pool.to_requests(proxy))
        except requests.Timeout:
            last_error = f"代理超时 {proxy['ip']}:{proxy['port']}"
        except requests.ConnectionError:
            last_error = f"代理连接失败 {proxy['ip']}:{proxy['port']}"
        except Exception as e:
            last_error = f"代理异常 {proxy['ip']}:{proxy['port']}: {e}"

    return False, f"代理全部失败: {last_error}"


def check_product_packages(product_id: int, packages: list[dict], proxy_pool=None) -> list[dict]:
    """检测一个产品下所有包的掉包状态。

    Args:
        product_id: 产品 ID
        packages: 包字典列表，每个包需包含 id, url, package_name
        proxy_pool: ProxyPool 实例；None 时直连

    Returns:
        检测结果列表，每个元素包含 package_id, is_delisted, error
    """
    results = []
    for pkg in packages:
        pkg_id = pkg.get("id")
        url = (pkg.get("url") or "").strip()

        if not url:
            results.append({
                "package_id": pkg_id,
                "product_id": product_id,
                "is_delisted": False,
                "error": "",
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
