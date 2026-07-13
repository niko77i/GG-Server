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


def check_url_delisted(url: str) -> tuple[bool, str]:
    """检测单个 Google Play URL 是否已掉包。

    Args:
        url: Google Play 应用链接

    Returns:
        (is_delisted, error): is_delisted=True 表示已掉包，
        error 为错误信息（正常为空字符串）
    """
    if not url or not url.strip():
        return False, ""

    try:
        resp = requests.get(
            url,
            headers={"User-Agent": _USER_AGENT},
            timeout=_TIMEOUT,
            allow_redirects=True,
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

    except requests.Timeout:
        return False, "请求超时"
    except requests.ConnectionError:
        return False, "网络连接失败"
    except Exception as e:
        return False, str(e)


def check_product_packages(product_id: int, packages: list[dict]) -> list[dict]:
    """检测一个产品下所有包的掉包状态。

    Args:
        product_id: 产品 ID
        packages: 包字典列表，每个包需包含 id, url, package_name

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

        is_delisted, error = check_url_delisted(url)
        results.append({
            "package_id": pkg_id,
            "product_id": product_id,
            "is_delisted": is_delisted,
            "error": error,
        })

    return results
