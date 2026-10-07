"""写表并发探测的单测。

设计见 docs/superpowers/specs/2026-10-07-sheet-concurrent-write-probe-design.md。

探测器必须对业务**完全透明** —— 不阻塞、不排序、不改返回值、不吞异常。
本文件既验证探测本身的行为，也用回归守卫锁住「哪些函数被装饰」这个事实。

末尾三组「回归守卫」对应 2026-10-07 code review 发现的 I1/I2/I3，
它们锁的都是**漏报**方向 —— 只断言「不误报」的测试是测不出漏报的。
"""
import logging
import threading

import pytest

import google_sheets_service as gs

_WRITE_FUNCS = (
    "upsert_zuobiao",
    "append_recharge",
    "append_recharge_tt",
    "append_recycle",
    "update_cell_by_account_id",
    "update_rows_by_account_id",
    "_upsert_rows",
)


@pytest.fixture(autouse=True)
def _clean_registry():
    """每个用例前后清空 registry，避免用例间串扰、也顺带检验它不会残留。"""
    gs._active_writes.clear()
    yield
    gs._active_writes.clear()


def _run_concurrently(target, args_list, timeout=5):
    """并发跑同一函数，用 Barrier 保证线程**同时在函数体内**。

    不用 Barrier 的话两个线程可能一前一后错开，探测不到并发 ——
    那样测试会静默地什么都没验到。
    """
    barrier = threading.Barrier(len(args_list))
    errors = []

    def _worker(a):
        try:
            target(*a, _barrier=barrier)
        except Exception as e:  # noqa: BLE001 - 测试里只需记录
            errors.append(e)

    threads = [threading.Thread(target=_worker, args=(a,)) for a in args_list]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=timeout)
    return errors


def _run_pair(fn_a, args_a, fn_b, args_b, timeout=5):
    """并发跑**两个不同函数**（签名可以不同），同样用 Barrier 对齐。"""
    barrier = threading.Barrier(2)
    errors = []

    def _worker(fn, a):
        try:
            fn(*a, _barrier=barrier)
        except Exception as e:  # noqa: BLE001
            errors.append(e)

    threads = [
        threading.Thread(target=_worker, args=(fn_a, args_a)),
        threading.Thread(target=_worker, args=(fn_b, args_b)),
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=timeout)
    return errors


# ── 探测行为 ──────────────────────────────────────────────────────

def test_single_thread_sequential_does_not_warn(caplog):
    """同一线程先后写同一张表不是并发，不该告警。"""
    @gs.probe_concurrent_write
    def write(service, spreadsheet_id, sheet_name, rows, _barrier=None):
        return "ok"

    with caplog.at_level(logging.WARNING, logger="gg-server"):
        write(None, "sid", "sheet1", [])
        write(None, "sid", "sheet1", [])

    assert "并发写探测" not in caplog.text


def test_two_threads_same_sheet_warns(caplog):
    """两个线程同时写同一张表 —— 这正是 read-modify-write 会丢更新的场景。"""
    @gs.probe_concurrent_write
    def write(service, spreadsheet_id, sheet_name, rows, _barrier=None):
        _barrier.wait(timeout=5)  # 两个线程都进了函数体才放行
        return "ok"

    with caplog.at_level(logging.WARNING, logger="gg-server"):
        errors = _run_concurrently(
            write, [(None, "sid", "sheet1", []), (None, "sid", "sheet1", [])]
        )

    assert not errors, f"并发执行出错: {errors}"
    assert "并发写探测" in caplog.text
    assert "2 个线程" in caplog.text
    assert "sheet1" in caplog.text


def test_two_threads_different_sheets_same_spreadsheet_does_not_warn(caplog):
    """同一 spreadsheet 内写**不同 sheet** 不冲突。

    这条覆盖的是 sheet_name 维度 —— 早先的版本把 spreadsheet_id 当成变量，
    用例名说「不同表」实际却从没验过 sheet_name。
    """
    @gs.probe_concurrent_write
    def write(service, spreadsheet_id, sheet_name, rows, _barrier=None):
        _barrier.wait(timeout=5)
        return "ok"

    with caplog.at_level(logging.WARNING, logger="gg-server"):
        errors = _run_concurrently(
            write, [(None, "sid", "sheet1", []), (None, "sid", "sheet2", [])]
        )

    assert not errors
    assert "并发写探测" not in caplog.text


def test_two_threads_different_spreadsheets_does_not_warn(caplog):
    """不同 spreadsheet 更不该告警。"""
    @gs.probe_concurrent_write
    def write(service, spreadsheet_id, sheet_name, rows, _barrier=None):
        _barrier.wait(timeout=5)
        return "ok"

    with caplog.at_level(logging.WARNING, logger="gg-server"):
        errors = _run_concurrently(
            write, [(None, "sid-A", "sheet1", []), (None, "sid-B", "sheet1", [])]
        )

    assert not errors
    assert "并发写探测" not in caplog.text


def test_same_thread_nested_does_not_warn(caplog):
    """同一线程嵌套调用（外层调内层）不是并发，不该告警。"""
    @gs.probe_concurrent_write
    def inner(service, spreadsheet_id, sheet_name, rows, _barrier=None):
        return "inner"

    @gs.probe_concurrent_write
    def outer(service, spreadsheet_id, sheet_name, rows, _barrier=None):
        return inner(service, spreadsheet_id, sheet_name, rows)

    with caplog.at_level(logging.WARNING, logger="gg-server"):
        outer(None, "sid", "sheet1", [])

    assert "并发写探测" not in caplog.text
    assert gs._active_writes == {}, "嵌套退出后 registry 未清空"


def test_exception_releases_registry():
    """被装饰函数抛异常时，registry 必须释放 —— 否则后续写入会被误判成并发。"""
    @gs.probe_concurrent_write
    def boom(service, spreadsheet_id, sheet_name, rows, _barrier=None):
        raise ValueError("boom")

    with pytest.raises(ValueError, match="boom"):
        boom(None, "sid", "sheet1", [])

    assert gs._active_writes == {}, "异常路径未清理 registry"


def test_registry_empty_after_concurrency():
    """并发结束后 registry 不得残留。"""
    @gs.probe_concurrent_write
    def write(service, spreadsheet_id, sheet_name, rows, _barrier=None):
        _barrier.wait(timeout=5)
        return "ok"

    _run_concurrently(
        write, [(None, "sid", "sheet1", []), (None, "sid", "sheet1", [])]
    )
    assert gs._active_writes == {}


# ── I1 回归守卫：嵌套不得让外层「隐身」 ────────────────────────────
# 只存线程集合时，内层退出即 del key，而外层仍在写表 —— 注册表谎报
# 「没人写」，外层在途期间的所有并发都漏报。只断言「不误报」的测试看不见它。

def test_nested_inner_return_keeps_outer_visible():
    """内层返回后，registry 必须仍记录着本线程（外层还在途）。"""
    observed = {}

    @gs.probe_concurrent_write
    def inner(service, spreadsheet_id, sheet_name, rows, _barrier=None):
        return "inner"

    @gs.probe_concurrent_write
    def outer(service, spreadsheet_id, sheet_name, rows, _barrier=None):
        inner(service, spreadsheet_id, sheet_name, rows)
        observed["after_inner"] = dict(gs._active_writes)
        return "outer"

    outer(None, "sid", "sheet1", [])

    assert observed["after_inner"], (
        "内层返回后 registry 被清空 —— 外层在途却对外不可见，此间的并发会全部漏报"
    )
    assert gs._active_writes == {}, "外层返回后 registry 应彻底清空"


def test_nested_outer_inflight_is_detected_by_other_thread(caplog):
    """外层在途（内层已返回）时，另一线程写同一张表**必须告警**。

    这条是 I1 的端到端版本：光断言「内层返回后 registry 非空」还不够，
    要真的让第二个线程在这个窗口里进来，看它是否被探测到。
    """
    inner_returned = threading.Event()
    hold = threading.Event()

    @gs.probe_concurrent_write
    def inner(service, spreadsheet_id, sheet_name, rows, _barrier=None):
        return "inner"

    @gs.probe_concurrent_write
    def outer(service, spreadsheet_id, sheet_name, rows, _barrier=None):
        inner(service, spreadsheet_id, sheet_name, rows)
        inner_returned.set()   # 内层已返回，外层仍在途
        hold.wait(timeout=5)   # 停在这个窗口里等另一个线程
        return "outer"

    @gs.probe_concurrent_write
    def other(service, spreadsheet_id, sheet_name, rows, _barrier=None):
        return "other"

    with caplog.at_level(logging.WARNING, logger="gg-server"):
        t = threading.Thread(target=outer, args=(None, "sid", "sheet1", []))
        t.start()
        assert inner_returned.wait(timeout=5), "外层未走到内层返回之后的窗口"
        other(None, "sid", "sheet1", [])   # 恰在外层在途的窗口内进入
        hold.set()
        t.join(timeout=5)

    assert "并发写探测" in caplog.text, (
        "外层在途时另一线程进入同一张表未被探测到 —— I1 漏报"
    )


# ── I2 回归守卫：sheet_name 缺失时按整个 spreadsheet 保守匹配 ──────
# upsert_zuobiao / _upsert_rows 签名里没有 sheet_name，取到 None。
# 若让 None 作为普通值参与比较，它与 (sid, "看板") 永不相等 —— 跨路径写
# 同一张表的并发会漏报，而这两个函数恰是最容易丢更新的 read-modify-write。

def test_none_sheet_name_matches_named_sheet_same_spreadsheet(caplog):
    """无 sheet_name 的入口与具名入口写同一 spreadsheet，必须视为可能冲突。"""
    @gs.probe_concurrent_write
    def no_sheet(service, spreadsheet_id, rows, _barrier=None):
        _barrier.wait(timeout=5)
        return "no_sheet"

    @gs.probe_concurrent_write
    def with_sheet(service, spreadsheet_id, sheet_name, rows, _barrier=None):
        _barrier.wait(timeout=5)
        return "with_sheet"

    with caplog.at_level(logging.WARNING, logger="gg-server"):
        errors = _run_pair(
            no_sheet, (None, "sid", []),
            with_sheet, (None, "sid", "看板", []),
        )

    assert not errors
    assert "并发写探测" in caplog.text, (
        "无 sheet_name 的入口与具名入口未匹配上 —— 该路径存在漏报盲区"
    )


def test_none_sheet_name_does_not_match_other_spreadsheet(caplog):
    """保守匹配只限同一 spreadsheet —— 不同 spreadsheet 仍不该告警。"""
    @gs.probe_concurrent_write
    def no_sheet(service, spreadsheet_id, rows, _barrier=None):
        _barrier.wait(timeout=5)
        return "no_sheet"

    @gs.probe_concurrent_write
    def with_sheet(service, spreadsheet_id, sheet_name, rows, _barrier=None):
        _barrier.wait(timeout=5)
        return "with_sheet"

    with caplog.at_level(logging.WARNING, logger="gg-server"):
        errors = _run_pair(
            no_sheet, (None, "sid-A", []),
            with_sheet, (None, "sid-B", "看板", []),
        )

    assert not errors
    assert "并发写探测" not in caplog.text


# ── I3 回归守卫：解析不出 spreadsheet_id 时跳过探测 ────────────────
# 否则键退化成 (None, None)，所有这类调用挤在同一键上互相误报。

def test_missing_spreadsheet_id_skips_probe(caplog):
    """没有 spreadsheet_id 形参的入口不参与探测，也不产生假告警。"""
    @gs.probe_concurrent_write
    def no_sid(service, rows, _barrier=None):
        _barrier.wait(timeout=5)
        return "ok"

    with caplog.at_level(logging.WARNING, logger="gg-server"):
        errors = _run_concurrently(no_sid, [(None, []), (None, [])])

    assert not errors
    assert "并发写探测" not in caplog.text, (
        "无 spreadsheet_id 的入口被当成 (None, None) 挤在同一键上 —— 假告警"
    )
    assert gs._active_writes == {}


# ── 对业务透明（回归门禁）─────────────────────────────────────────

def test_passthrough_return_value():
    @gs.probe_concurrent_write
    def write(service, spreadsheet_id, sheet_name, rows, _barrier=None):
        return {"updated": 7}

    assert write(None, "sid", "sheet1", []) == {"updated": 7}


def test_passthrough_exception_type():
    """异常类型必须原样透传，不能被包装成别的异常。"""
    @gs.probe_concurrent_write
    def write(service, spreadsheet_id, sheet_name, rows, _barrier=None):
        raise KeyError("原始异常")

    with pytest.raises(KeyError, match="原始异常"):
        write(None, "sid", "sheet1", [])


def test_passthrough_positional_and_keyword():
    """位置参数与关键字参数两种调用方式都要能正确提取 key。"""
    seen = {}

    @gs.probe_concurrent_write
    def write(service, spreadsheet_id, sheet_name, rows, _barrier=None):
        seen["sid"] = spreadsheet_id
        return "ok"

    write(None, "sid-A", "sheet1", [])
    assert seen["sid"] == "sid-A"

    write(None, spreadsheet_id="sid-B", sheet_name="sheet2", rows=[])
    assert seen["sid"] == "sid-B"


def test_signature_mismatch_still_calls_through():
    """签名绑定失败时原样调用 —— 原函数该抛什么错就抛什么错，不被吞掉。"""
    @gs.probe_concurrent_write
    def write(service, spreadsheet_id, sheet_name, rows, _barrier=None):
        return "ok"

    with pytest.raises(TypeError):
        write(None, "sid", "sheet1")  # 少传 rows


# ── 装饰覆盖面（防止将来有人改签名时静默失效）─────────────────────

def test_all_write_functions_are_wrapped():
    for name in _WRITE_FUNCS:
        fn = getattr(gs, name)
        assert getattr(fn, "__wrapped__", None) is not None, (
            f"{name} 未被 @probe_concurrent_write 装饰 —— 该写路径将不受探测覆盖"
        )


def test_fb_reports_not_wrapped():
    """upsert_fb_reports 不应被装饰。

    真正原因：它签名里**没有** spreadsheet_id，装饰后 key 会退化成 (None, None)，
    与所有其它此类调用挤在同一键上互相误报（而非早先误以为的「重复计数」）。
    它已通过内部调用的 _upsert_rows 被覆盖。
    """
    assert getattr(gs.upsert_fb_reports, "__wrapped__", None) is None, (
        "upsert_fb_reports 不应被装饰 —— 它没有 spreadsheet_id 形参，"
        "装饰会让键退化成 (None, None) 造成跨表误报"
    )


def test_read_functions_not_wrapped():
    """读函数不写表，不需要探测。"""
    for name in ("read_sheet_values", "get_spreadsheet_info"):
        fn = getattr(gs, name)
        assert getattr(fn, "__wrapped__", None) is None, f"{name} 不该被装饰"
