"""Google Play / App Store 掉包检测模块。

通过 HTTP 请求应用商店链接，判断应用是否已被下架。
"""

from concurrent.futures import ThreadPoolExecutor, as_completed
import logging

import requests

log = logging.getLogger("gg-server")

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

# 判定未知的响应状态码：**非 200/404 的一切状态码**。
#   404 = 已下架（拿到了判定）；200 = 页面正常（拿到了判定，再由下面按内容关键词兜底）；
#   其余（403 反爬、410、429、任意 5xx、未被跟随的 3xx……）都无法据此判断在架与否，
#   判成「正常」会经 INSERT OR REPLACE 抹掉上一轮正确的掉包记录。
# 实测依据：App Store 对掉包链接返回 404，被限流时返回 429，两者响应体同为
# 2383 字节，只能靠状态码区分；旧逻辑只认 404，会把 429 当成「正常」。
def _is_indeterminate_status(status_code: int) -> bool:
    """非 200/404 的一切状态码均视为「拿不到判定」。"""
    return status_code not in (200, 404)


# 请求超时秒数。⚠️ requests 传单值时**连接与读取各算一次**
# （HTTPAdapter.send: "a single float to set both timeouts to the same value"），
# 故单次请求最坏 2 × _TIMEOUT。2026-09-25 由 15 降到 5：正常响应仅 2-3s，
# 15s 纯属浪费，而长尾（偶发单包吃满超时再重试）才是手动检测「慢」的主因。
_TIMEOUT = 5


class DelistIndeterminate(Exception):
    """响应状态非 200/404，本次判定结果未知。

    调用方应保留上一轮判定结果，不得当作「正常」写入。
    """


def _request_and_judge(url: str, proxies: dict | None) -> tuple[bool, str]:
    """发请求并判掉包；网络异常直接抛出，由调用方处理。

    Args:
        url: 应用商店链接（Google Play 或 App Store）
        proxies: requests 的 proxies 参数，None 表示直连

    Raises:
        DelistIndeterminate: 状态码非 200/404，本次无法判定
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

    # 2. 非 200/404 一律未知：拿不到判定，抛出让调用方换代理重试（403 反爬、410、429、任意 5xx…）
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
          None  → 判定未知（非 200/404 的状态码/超时/连接失败/解析失败/空 url），
                  调用方应保留上一次判定结果，不得覆盖
    """
    if not url or not url.strip():
        return None, "URL 为空，无法判定"

    # 无代理池：直连；拿不到判定（非 200/404 的状态码/超时/连接失败/解析失败）一律返回「未知」
    if proxy_pool is None:
        try:
            return _request_and_judge(url, None)
        except DelistIndeterminate as e:
            return None, f"{e}，无法判定"
        except requests.Timeout:
            return None, "请求超时，无法判定"
        except requests.ConnectionError:
            return None, "网络连接失败，无法判定"
        except Exception as e:
            # `{e}` 是任意异常的英文原文（requests / 解析库 / …）。该文案经
            # `delist_checks.error_msg` 回进 /api/products/delist-status 响应体 ⇒ 不内插。
            log.warning("掉包检测直连异常 url=%s: %s", url, e)
            return None, "请求异常，无法判定"

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
            log.warning("掉包检测代理异常 %s:%s: %s", proxy['ip'], proxy['port'], e)
            last_error = f"代理异常 {proxy['ip']}:{proxy['port']}"

    # 出现过「拿不到判定」的响应 → 整体判为未知（保守：既不算掉包也不算正常）。
    # 文案不再写死「限流/服务端」：新口径下非 200/404 一律未知，走这条最多的是
    # 403 反爬，写窄了会把用户往「等一会儿重试」的方向误导。具体状态码在
    # last_indeterminate 里（形如 `HTTP 403 @ 1.2.3.4:8080`），原样带出即可。
    if last_indeterminate:
        return None, f"代理响应异常，无法判定: {last_indeterminate}"
    return None, f"代理全部失败: {last_error}，无法判定"


# 手动检测的并发上限：与两处定时检测（main.py 的 _run_delist_check_once /
# _run_tt_delist_check_once）取同一口径。
# 刻意不设无上限并发：放大对 Google Play 的请求压力会触发 429，而现行口径下
# 非 200/404 一律降级为「未知」，等于把本可判定的包判没了。
_DEFAULT_MAX_WORKERS = 10


def _check_one_url(url: str, proxy_pool) -> tuple[bool | None, str]:
    """单个 url 的检测（保留既有的直连 / 代理两条调用分支）。

    单独抽出，是为了让并发池里的调用形态与改造前逐字一致：无代理池时只传
    一个位置参数（既有测试以 `side_effect(url)` 单参数 mock 本函数）。
    """
    if proxy_pool is None:
        return check_url_delisted(url)
    return check_url_delisted(url, proxy_pool)


# 每个代理允许的并发连接数。这个自适应只为「包少时别无谓加压 + 补代理后自动放开」，
# **不要**指望它解决「慢」：2026-09-25 用 6 包做 4/10/10/4 交替对照，4 并发均值 30.9s、
# 10 并发均值 26.7s、单轮极差 55.7s↔6.1s —— 差异淹没在噪声里。长尾来自单包超时模型
# （见 _TIMEOUT），真正的杠杆是 _TIMEOUT。
_WORKERS_PER_PROXY = 2


def _resolve_max_workers(proxy_pool, requested: int | None) -> int:
    """手动检测的并发上限：显式传参 > 按代理池容量 > 默认值。

    代理池为空（含直连）时没有出口瓶颈，用 _DEFAULT_MAX_WORKERS。
    """
    if requested is not None:
        return requested
    capacity = getattr(proxy_pool, "count", 0) if proxy_pool is not None else 0
    if not isinstance(capacity, int) or capacity < 1:
        return _DEFAULT_MAX_WORKERS
    return max(1, min(_DEFAULT_MAX_WORKERS, capacity * _WORKERS_PER_PROXY))


def check_product_packages(product_id: int, packages: list[dict], proxy_pool=None,
                           max_workers: int | None = None) -> list[dict]:
    """检测一个产品下所有包的掉包状态（并发执行）。

    2026-09-25 改造：原为串行 `for pkg in packages` 逐个请求。单包最坏
    2 × _TIMEOUT × 尝试次数（`requests` 单值 timeout 是连接、读取**各算一次**，
    不是一次），`_TIMEOUT` 15 → 5 后为 20s；现网单个产品最多 24 个待检包，
    串行最坏 480s，而前端 axios 硬超时 30s —— 手动检测在前端会先报错
    （后端仍在跑并照常写库、发通知）。改为并发，口径与两处定时检测拉平。

    Args:
        product_id: 产品 ID
        packages: 包字典列表，每个包需包含 id, url, package_name
        proxy_pool: ProxyPool 实例；None 时直连
        max_workers: 并发上限；None 时按代理池容量自适应
                     （见 _resolve_max_workers），无代理池时取 _DEFAULT_MAX_WORKERS

    Returns:
        检测结果列表，**与入参 packages 严格同序**（TT 手动检测按 zip 配对）。
        每个元素包含 package_id, product_id, is_delisted, error。
        is_delisted 为 True/False/None（None 表示判定未知）。
        空 url 由本函数直接判为 None（无法判定），其余原样透传 check_url_delisted 的结果。
    """
    results: list[dict | None] = [None] * len(packages)

    # 空 url 的包不发请求，按下标直接占位（口径与改造前一致）
    pending = []  # (下标, url)
    for idx, pkg in enumerate(packages):
        url = (pkg.get("url") or "").strip()
        if not url:
            results[idx] = {
                "package_id": pkg.get("id"),
                "product_id": product_id,
                "is_delisted": None,
                "error": "URL 为空，无法判定",
            }
        else:
            pending.append((idx, url))

    if pending:
        limit = _resolve_max_workers(proxy_pool, max_workers)
        workers = min(len(pending), max(1, limit))
        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = {
                executor.submit(_check_one_url, url, proxy_pool): idx
                for idx, url in pending
            }
            for future in as_completed(futures):
                idx = futures[future]
                is_delisted, error = future.result()
                # 按输入下标回填：保证 results 与入参 packages 同序。
                # TT 手动检测用 zip(pkg_list, results) 配对（routes/tt_routes.py），
                # 若按完成顺序 append，慢包的结果会挂到别的包上，发出错误的掉包通知。
                results[idx] = {
                    "package_id": packages[idx].get("id"),
                    "product_id": product_id,
                    "is_delisted": is_delisted,
                    "error": error,
                }

    return results
