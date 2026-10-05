"""check_product_packages 并行化测试。

背景（2026-09-25）：手动掉包检测原先在 delist_checker.check_product_packages
里串行执行（`for pkg in packages` 逐个发请求）。单包最坏 20s —— `requests` 的
`timeout` 传单值时连接与读取各算一次（_TIMEOUT=5 时单次请求最坏 10s），2 个代理
时 `next(exclude=tried)` 最多给出 2 次尝试；现网 GG 单个产品最多 24 个待检包，
串行即最坏 480s。而前端 axios 硬超时 30s（frontend/src/api/client.js），
两个包的最坏耗时就已越过它，后端却仍在跑并照常写库/发通知 —— 该接口前端
超时因此单条放宽到 180s。

改造口径（两轮）：
1. 先与两处定时检测（main.py 的 _run_delist_check_once /
   _run_tt_delist_check_once）拉平，把串行改为并发；
2. 再把并发数从写死的 10 改为**按代理池容量自适应**
   （proxy_pool.count × _WORKERS_PER_PROXY，封顶 _DEFAULT_MAX_WORKERS）。
   自适应是为了「包少时别无谓加压 + 补代理后自动放开」，**不要**指望它解决
   「慢」：2026-09-25 曾据少量测量（代理 10 并发 17.7s vs 3 并发 8.8s）判断
   「代理池是这条链路的瓶颈」，随后被 4/10/10/4 交替对照推翻（均值
   26.7s vs 30.9s，单轮极差 55.7s↔6.1s）。真正的杠杆是 _TIMEOUT（15 → 5）。

必须守住的三条：
1. 结果与入参 packages 严格同序 —— TT 手动检测用 zip(pkg_list, results)
   配对（routes/tt_routes.py），错序会把 A 包的掉包状态挂到 B 包上，
   进而发出错误的掉包通知；
2. 并发上限受控且与代理池容量匹配 —— 无上限并发会放大对 Google Play 的
   请求压力，触发 429，而现行口径下非 200/404 一律降级为「未知」，等于把
   能判定的包判没了；
3. 空 url 的包仍不发请求、仍按下标占位判「未知」（口径与改造前一致）。
"""
import threading
import time
from unittest.mock import patch

import pytest


def _pkg(pid, name):
    return {
        "id": pid,
        "url": f"https://play.google.com/store/apps/details?id={name}",
        "package_name": name,
    }


class TestCheckProductPackagesParallel:
    """并行化后的行为与顺序保证。"""

    def test_results_keep_input_order_despite_out_of_order_completion(self):
        """慢包最后完成，结果仍按下标回填，顺序不被完成顺序打乱。

        构造：第 1 个包 sleep 最久（最后完成），第 3 个最快返回。
        若实现按完成顺序 append，results[0] 会变成第 3 个包的结果 ——
        这正是 TT 手动检测 zip 配对会踩的坑。
        """
        from delist_checker import check_product_packages

        packages = [_pkg(11, "slow"), _pkg(22, "mid"), _pkg(33, "fast")]
        delays = {"slow": 0.30, "mid": 0.15, "fast": 0.0}
        verdicts = {"slow": True, "mid": False, "fast": True}

        def fake_check(url, *args, **kwargs):
            key = url.rsplit("=", 1)[-1]
            time.sleep(delays[key])
            return verdicts[key], ""

        with patch("delist_checker.check_url_delisted", side_effect=fake_check):
            results = check_product_packages(1, packages)

        assert [r["package_id"] for r in results] == [11, 22, 33]
        assert [r["is_delisted"] for r in results] == [True, False, True]
        assert [r["product_id"] for r in results] == [1, 1, 1]

    def test_runs_concurrently_not_serially(self):
        """并发生效：3 个各 0.3s 的检测总耗时接近 0.3s，而非串行的 0.9s。

        对照行：把实现改回串行 for 循环，本断言必然失败（0.9s > 0.7s）。
        """
        from delist_checker import check_product_packages

        packages = [_pkg(i, f"c{i}") for i in (1, 2, 3)]

        def fake_check(url, *args, **kwargs):
            time.sleep(0.3)
            return False, ""

        with patch("delist_checker.check_url_delisted", side_effect=fake_check):
            started = time.monotonic()
            results = check_product_packages(1, packages)
            elapsed = time.monotonic() - started

        assert len(results) == 3
        assert elapsed < 0.7, f"耗时 {elapsed:.2f}s，未见并发（串行约 0.9s）"

    def test_concurrency_is_capped(self):
        """并发峰值受 max_workers 约束，不会无上限打 Google Play。"""
        from delist_checker import check_product_packages

        packages = [_pkg(i, f"cap{i}") for i in range(1, 9)]

        lock = threading.Lock()
        inflight = 0
        peak = 0

        def fake_check(url, *args, **kwargs):
            nonlocal inflight, peak
            with lock:
                inflight += 1
                peak = max(peak, inflight)
            time.sleep(0.05)
            with lock:
                inflight -= 1
            return False, ""

        with patch("delist_checker.check_url_delisted", side_effect=fake_check):
            results = check_product_packages(1, packages, max_workers=2)

        assert len(results) == 8
        assert peak <= 2, f"并发峰值 {peak} 超过上限 2"

    def test_proxy_pool_is_passed_through_for_every_package(self):
        """有代理池时每个包都带池调用 —— 走代理防风控的口径不因并行丢失。"""
        from delist_checker import check_product_packages

        packages = [_pkg(1, "p1"), _pkg(2, "p2")]
        pool = object()
        seen = []
        lock = threading.Lock()

        def fake_check(url, proxy_pool=None):
            with lock:
                seen.append(proxy_pool)
            return False, ""

        with patch("delist_checker.check_url_delisted", side_effect=fake_check):
            results = check_product_packages(1, packages, pool)

        assert len(results) == 2
        assert len(seen) == 2
        assert all(p is pool for p in seen), "代理池未原样透传"


class TestEmptyUrlPlacementUnderParallel:
    """并行化不得改变空 url 包的处理口径。"""

    def test_empty_url_keeps_position_and_sends_no_request(self):
        """空 url（含纯空白）按下标占位判「未知」，且不发任何请求。"""
        from delist_checker import check_product_packages

        packages = [
            {"id": 1, "url": "", "package_name": "a"},
            _pkg(2, "b"),
            {"id": 3, "url": "   ", "package_name": "c"},
        ]

        with patch("delist_checker.check_url_delisted", side_effect=lambda url, *a, **k: (False, "")) as mock_check:
            results = check_product_packages(1, packages)

        assert [r["package_id"] for r in results] == [1, 2, 3]
        assert [r["is_delisted"] for r in results] == [None, False, None]
        assert results[0]["error"] == "URL 为空，无法判定"
        assert mock_check.call_count == 1, "空 url 不应发请求"

    def test_all_empty_urls_never_touch_thread_pool(self):
        """全部为空 url 时不建线程池、不调检测函数，直接返回占位结果。"""
        from delist_checker import check_product_packages

        packages = [
            {"id": 1, "url": "", "package_name": "a"},
            {"id": 2, "url": "", "package_name": "b"},
        ]

        with patch("delist_checker.check_url_delisted", side_effect=AssertionError("不该被调用")):
            results = check_product_packages(1, packages)

        assert len(results) == 2
        assert all(r["is_delisted"] is None for r in results)

    def test_empty_package_list_returns_empty(self):
        """空列表直接返回空结果（调用方据此提示「没有需要检测的包」）。"""
        from delist_checker import check_product_packages

        assert check_product_packages(1, []) == []


class _FakePool:
    """只带 count 的假代理池 —— 手动检测只关心出口容量。"""

    def __init__(self, count):
        self.count = count


class TestAdaptiveWorkers:
    """并发上限按代理池容量自适应（见文件头「改造口径」第 2 条）。"""

    def test_explicit_max_workers_still_wins(self):
        """显式传参仍然优先 —— 既有调用方与测试靠这条保持可控。"""
        from delist_checker import _resolve_max_workers

        assert _resolve_max_workers(_FakePool(2), 7) == 7
        assert _resolve_max_workers(None, 3) == 3

    def test_scales_with_proxy_pool_size(self):
        """代理越多，允许的并发越大（用户补代理后自动放开，无需改代码）。"""
        from delist_checker import _resolve_max_workers, _WORKERS_PER_PROXY

        assert _resolve_max_workers(_FakePool(2), None) == 2 * _WORKERS_PER_PROXY
        assert _resolve_max_workers(_FakePool(3), None) == 3 * _WORKERS_PER_PROXY

    def test_capped_at_default_max_workers(self):
        """代理再多也不突破 _DEFAULT_MAX_WORKERS —— 别把 Google 打急眼。"""
        from delist_checker import _resolve_max_workers, _DEFAULT_MAX_WORKERS

        assert _resolve_max_workers(_FakePool(50), None) == _DEFAULT_MAX_WORKERS

    def test_falls_back_to_default_without_usable_pool(self):
        """无池 / 空池 / 没有 count 属性的对象，一律退回默认值。"""
        from delist_checker import _resolve_max_workers, _DEFAULT_MAX_WORKERS

        assert _resolve_max_workers(None, None) == _DEFAULT_MAX_WORKERS
        assert _resolve_max_workers(_FakePool(0), None) == _DEFAULT_MAX_WORKERS
        assert _resolve_max_workers(object(), None) == _DEFAULT_MAX_WORKERS
        # count 不是 int（代理池实现变化 / 被换成 mock）时同样退回默认，
        # 不能让 `capacity * _WORKERS_PER_PROXY` 在非数值上炸掉整个检测
        assert _resolve_max_workers(_FakePool("2"), None) == _DEFAULT_MAX_WORKERS

    def test_end_to_end_peak_respects_pool_capacity(self):
        """走真实入口：2 个代理的池 + 12 个包，并发峰值不得超过 4。

        对照腿：若自适应失效回退成 10，峰值会到 10，本断言转红。
        """
        from delist_checker import check_product_packages

        packages = [_pkg(i, f"p{i}") for i in range(1, 13)]
        pool = _FakePool(2)
        inflight = 0
        peak = 0
        lock = threading.Lock()

        def slow_check(url, proxy_pool=None):
            nonlocal inflight, peak
            with lock:
                inflight += 1
                peak = max(peak, inflight)
            time.sleep(0.05)
            with lock:
                inflight -= 1
            return False, ""

        with patch("delist_checker.check_url_delisted", side_effect=slow_check):
            results = check_product_packages(1, packages, pool)

        assert len(results) == 12
        assert peak <= 2 * 2, f"并发峰值 {peak} 超过 2 个代理的容量上限 4"
