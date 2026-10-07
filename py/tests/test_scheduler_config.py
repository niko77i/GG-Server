"""定时任务：权限、周期配置、调度计算。

运行：cd py && python -m pytest tests/test_scheduler_config.py -v
"""
import datetime
import json
import logging
import threading
import pytest
from flask import jsonify
from flask_jwt_extended import jwt_required

import database
import main
from main import app as _shared_app
from routes.decorators import scheduler_required


# 探针路由：直接测装饰器本身（不依赖 Task 4 才落地的真实接口）。
#
# ⚠️ 为何注册在模块级、而不是 fixture 里：
# conftest.py 的 app fixture 复用的是 main.py 的全局 app 单例（跨测试同一个对象），
# 且 Flask 3 在 app 处理过首个请求后即锁定，再调 @app.route 会抛
# 「The setup method 'route' can no longer be called on the application」。
# 若放在 fixture 中逐测试注册，第一个用到的测试能过、其后全部报错。
# 模块导入发生在本次会话的任何请求之前、且每进程只执行一次，故在此注册一次。
#
# ⚠️ 契约（潜在陷阱）：这两条探针路由**在模块级注册一次、永久挂在共享 main.app 上，
# 没有任何 teardown** —— 导入本模块即等于给进程内全局 app 添了两条 POST 路由。
# 今日无害：全库唯一遍历路由表的 tests/test_anon_surface.py 只取 GET 规则
# （且另有 _MIN_EXPECTED_GET_RULES 下界兜底），看不到这两条 POST。
# 将来若有人写「枚举全部 POST 路由」或「断言路由总数 == N」的测试，
# 会额外看到 `/api/_probe/gg`、`/api/_probe/tt` 而莫名变红 —— 届时请来此收口，别去改那边的期望值。
@_shared_app.route("/api/_probe/gg", methods=["POST"], endpoint="_probe_gg")
@jwt_required()
@scheduler_required("gg")
def _probe_gg():
    return jsonify(success=True, platform="gg")


@_shared_app.route("/api/_probe/tt", methods=["POST"], endpoint="_probe_tt")
@jwt_required()
@scheduler_required("tt")
def _probe_tt():
    return jsonify(success=True, platform="tt")


@pytest.fixture
def probe_client(app):
    """返回挂了探针路由的 test client。"""
    return app.test_client()


class TestSchedulerRequired:
    def test_developer_passes_both_platforms(self, probe_client, dev_headers):
        """developer 跨平台放行。"""
        assert probe_client.post("/api/_probe/gg", headers=dev_headers).status_code == 200
        assert probe_client.post("/api/_probe/tt", headers=dev_headers).status_code == 200

    def test_gg_admin_passes_gg_only(self, probe_client, admin_gg_headers):
        """GG 管理员：自己的平台放行，别的平台 403。"""
        assert probe_client.post("/api/_probe/gg", headers=admin_gg_headers).status_code == 200
        assert probe_client.post("/api/_probe/tt", headers=admin_gg_headers).status_code == 403

    def test_tt_admin_passes_tt_only(self, probe_client, admin_tt_headers):
        assert probe_client.post("/api/_probe/tt", headers=admin_tt_headers).status_code == 200
        assert probe_client.post("/api/_probe/gg", headers=admin_tt_headers).status_code == 403

    def test_fb_admin_passes_neither(self, probe_client, admin_fb_headers):
        """FB 管理员：两个探针都 403（FB 没有定时任务）。"""
        assert probe_client.post("/api/_probe/gg", headers=admin_fb_headers).status_code == 403
        assert probe_client.post("/api/_probe/tt", headers=admin_fb_headers).status_code == 403

    def test_huguan_rejected(self, probe_client, huguan_headers):
        """⚠️ 核心对照腿：户管必须被拒。

        require_platform() 的 PLATFORM_SWITCH_ROLES 含 HUGUAN_ROLE，会放行户管 ——
        若有人图省事改用 require_platform，本类会红。
        """
        assert probe_client.post("/api/_probe/gg", headers=huguan_headers).status_code == 403
        assert probe_client.post("/api/_probe/tt", headers=huguan_headers).status_code == 403

    def test_plain_user_rejected(self, probe_client, auth_headers):
        """普通 user（platform=gg）也是 403 —— 只有 admin 才够格，平台匹配不是唯一条件。"""
        assert probe_client.post("/api/_probe/gg", headers=auth_headers).status_code == 403


class TestSchedulerConfigDefaults:
    def test_missing_key_falls_back_to_defaults(self, app):
        """键不存在（首次运行）→ 全默认值，不得抛异常。"""
        database.config_set("scheduler_config", "")
        cfg = main._get_scheduler_config()
        assert cfg == main._SCHEDULER_DEFAULTS

    def test_partial_json_fills_missing_fields(self, app):
        """只写了一个字段 → 其余回落默认。"""
        database.config_set("scheduler_config", json.dumps({"gg_delist_minutes": 120}))
        cfg = main._get_scheduler_config()
        assert cfg["gg_delist_minutes"] == 120
        assert cfg["tt_delist_minutes"] == 30          # 对照：未被覆盖的字段
        assert cfg["cleanup_weekday"] == 6
        assert cfg["cleanup_hour"] == 0

    def test_corrupt_json_falls_back_to_defaults(self, app):
        """坏 JSON 不得让调度线程崩。"""
        database.config_set("scheduler_config", "{not json")
        assert main._get_scheduler_config() == main._SCHEDULER_DEFAULTS

    def test_out_of_range_stored_value_falls_back(self, app):
        """库里存了越界值（如手工改库）→ 回落默认，不照单全收。"""
        database.config_set("scheduler_config", json.dumps({"gg_delist_minutes": 3}))
        assert main._get_scheduler_config()["gg_delist_minutes"] == 60

    def test_bool_stored_value_falls_back(self, app):
        """⚠️ 布尔值不是合法的周期/时刻，必须回落默认 —— 不得照单全收。

        Python 里 `True == 1`，少了 `not isinstance(val, bool)` 那一句就会：
          - `cleanup_weekday=true` → 通过 `0 <= val <= 6`，把「周日」静默改成「周一」(1)；
          - `cleanup_hour=true`    → 通过 `0 <= val <= 23`，把「0 点」静默改成「1 点」。
        故本用例的**判别腿是 cleanup_weekday / cleanup_hour**；`gg_delist_minutes=true`
        在 lo=10 下 True==1 本就落在范围外（连删掉类型守卫也不被采纳），属非判别腿，
        一并留着当回归钉。
        """
        for field, default in (("gg_delist_minutes", 60),
                               ("cleanup_weekday", 6),
                               ("cleanup_hour", 0)):
            database.config_set("scheduler_config", json.dumps({field: True}))
            got = main._get_scheduler_config()[field]
            assert got == default, f"{field}=true 应回落 {default}，实得 {got!r}"

    def test_invalid_stored_value_is_logged(self, app, caplog):
        """⚠️ 存量值非法必须留痕：手工改库写了越界值不能「悄悄不生效、查无实据」。

        正反两条腿缺一不可：
          - 非法值（越界/类型错）→ **必须**有 warning；
          - 字段**缺失**（首次运行、只配了部分字段，都属正常情形）→ **必须没有** warning，
            否则本函数每 30 秒被调度线程调一次，日志会被刷屏。
        删掉 main.py 里的 `log.warning(...)`，第一条腿即红。
        """
        database.config_set("scheduler_config", json.dumps({"gg_delist_minutes": 3}))
        with caplog.at_level(logging.WARNING, logger="gg-server"):
            assert main._get_scheduler_config()["gg_delist_minutes"] == 60
        assert any("gg_delist_minutes" in r.getMessage() for r in caplog.records), \
            "越界存量值回落默认时必须留下 warning"

        caplog.clear()
        database.config_set("scheduler_config", json.dumps({"tt_delist_minutes": 30}))
        with caplog.at_level(logging.WARNING, logger="gg-server"):
            main._get_scheduler_config()
        assert [r.getMessage() for r in caplog.records
                if "gg_delist_minutes" in r.getMessage()] == [], \
            "字段缺失属正常情形，不得打 warning（否则每 30 秒刷屏）"


class TestLastRun:
    def test_mark_and_read(self, app):
        main._mark_task_run("gg_delist", ok=True)
        last = main._get_last_run()
        assert last["gg_delist"]["ok"] is True
        assert last["gg_delist"]["ts"]                  # 有非空时间戳

    def test_read_without_any_run_returns_empty(self, app):
        """从未跑过 → 空 dict（前端据此显示「尚未执行」，区别于「执行失败」）。"""
        assert main._get_last_run() == {}

    def test_marking_one_task_keeps_others(self, app):
        """对照腿：写 A 不能抹掉已存在的 B。"""
        main._mark_task_run("gg_delist", ok=True)
        main._mark_task_run("cleanup", ok=False)
        last = main._get_last_run()
        assert last["gg_delist"]["ok"] is True
        assert last["cleanup"]["ok"] is False


class TestNextCleanupAt:
    """cleanup 触发时刻计算。原实现 `days_until_sunday or 7` 的等价改写。"""

    def test_saturday_night_targets_next_sunday(self, app):
        now = datetime.datetime(2026, 10, 10, 23, 0, 0)      # 周六
        assert main._next_cleanup_at(now, 6, 0) == datetime.datetime(2026, 10, 11, 0, 0, 0)

    def test_sunday_exactly_at_zero_moves_to_next_week(self, app):
        """⚠️ 核心边界：周日 00:00:00 整点 → 下周日（原实现 `or 7` 的语义）。"""
        now = datetime.datetime(2026, 10, 11, 0, 0, 0)
        assert main._next_cleanup_at(now, 6, 0) == datetime.datetime(2026, 10, 18, 0, 0, 0)

    def test_sunday_noon_moves_to_next_week(self, app):
        """周日中午 → 下周日，不得当天重复触发。"""
        now = datetime.datetime(2026, 10, 11, 12, 0, 0)
        assert main._next_cleanup_at(now, 6, 0) == datetime.datetime(2026, 10, 18, 0, 0, 0)

    def test_weekday_schedule_later_this_week(self, app):
        now = datetime.datetime(2026, 10, 12, 8, 0, 0)       # 周一
        assert main._next_cleanup_at(now, 2, 8) == datetime.datetime(2026, 10, 14, 8, 0, 0)   # 周三

    def test_same_weekday_after_hour_moves_to_next_week(self, app):
        """今天就是周三但已过 8 点 → 下周三。"""
        now = datetime.datetime(2026, 10, 14, 9, 0, 0)
        assert main._next_cleanup_at(now, 2, 8) == datetime.datetime(2026, 10, 21, 8, 0, 0)


class TestIntervalTick:
    """tick 累加与触发判定（把循环里的判断抽成纯函数才可测）。"""

    def test_not_reached_keeps_accumulating(self, app):
        assert main._interval_tick(0, 3600) == (False, main._TICK_SECONDS)

    def test_reaches_target_triggers_and_resets(self, app):
        """累计到 3600 秒 → 触发，elapsed 归零。"""
        elapsed = 3600 - main._TICK_SECONDS
        assert main._interval_tick(elapsed, 3600) == (True, 0)

    def test_shrinking_interval_triggers_immediately(self, app):
        """周期被改小到已累计的时间之下 → 下一 tick 立刻触发（用户想更快）。"""
        assert main._interval_tick(600, 60) == (True, 0)

    def test_zero_target_does_not_busy_loop(self, app):
        """防御：target <= 0 不得变成每 tick 都跑。"""
        assert main._interval_tick(0, 0) == (False, main._TICK_SECONDS)

    def test_tick_seconds_is_pinned_to_30(self, app):
        """⚠️ `_TICK_SECONDS == 30` 是「配置变更生效粒度」的契约值：用户看到的是
        「改周期最多 30 秒生效」，30 直接决定这个承诺（调大 = 承诺变谎，调小 = 每 30 秒
        改成更频繁地连库）。

        上面三条用例都以 `main._TICK_SECONDS` 自引用（左右两边同一个值），
        故字面值本身没被任何用例钉住 —— 把常量改成 1 或 3600，全库仍绿。这里独立钉死。
        """
        assert main._TICK_SECONDS == 30


# ============================================================
#  Task 3：三个调度线程改 tick 循环（周期可配置、免重启生效）
# ============================================================

class _StopLoop(Exception):
    """哨兵异常：把 while True 的死循环在测试里可控地打断（不参与生产逻辑）。"""


class _FakeTime:
    """time 模块替身：记录每次 sleep 的秒数；调用超过 stop_after 次即抛 _StopLoop 终止循环。"""

    def __init__(self, stop_after):
        self.secs = []
        self.stop_after = stop_after

    def sleep(self, s):
        self.secs.append(s)
        if len(self.secs) > self.stop_after:
            raise _StopLoop()


class _ThreadingStub:
    """threading 模块的替身：仅覆盖 Thread，其余属性透传给真模块。"""

    def __init__(self, thread_cls):
        self.Thread = thread_cls

    def __getattr__(self, name):
        return getattr(threading, name)


def _capture_thread(monkeypatch):
    """把 main 里的 threading.Thread 换成替身：捕获 target/args/daemon，不真正起线程。

    ⚠️ 只替换 `main` 命名空间里的 threading 引用，**不碰全局 threading 模块**。
    早先写法是 `monkeypatch.setattr(main.threading, "Thread", ...)`，那改的是
    threading 模块的全局属性 —— 测试期间本进程内**任何**线程创建（包括别处的
    并发用例）都会被顶替；当前单线程用例幸免，将来必踩雷。此处把影响面收在 main 内。
    """
    box = {}

    class _FakeThread:
        def __init__(self, target=None, args=(), daemon=None, **kw):
            box["target"] = target
            box["args"] = tuple(args)
            box["daemon"] = daemon

        def start(self):
            box["started"] = True

    monkeypatch.setattr(main, "threading", _ThreadingStub(_FakeThread))
    return box


class TestIntervalLoop:
    """两个掉包调度复用的通用循环（GG / TT）。

    循环本体是 while True + sleep，无法直接跑；这里用「替身 sleep 累计 N 次后抛哨兵」
    把每一轮都驱动起来，再断言行为。
    """

    def test_recomputes_target_each_tick(self, app, monkeypatch):
        """⚠️ 每个 tick 都重读配置 —— 把 _get_scheduler_int 提到循环外只读一次，本测试即红。

        这正是「改周期最多 30 秒生效」的实现依据；读一次就退化成旧的硬编码语义。
        """
        monkeypatch.setattr(main, "_TICK_SECONDS", 1)
        ft = _FakeTime(stop_after=5)          # 5 次成功 tick，第 6 次 sleep 抛哨兵
        monkeypatch.setattr(main, "_time", ft)
        reads = []

        def _spy(field, default):
            reads.append(field)
            return 1440                       # 目标 86400 秒，测试期内永不触发

        monkeypatch.setattr(main, "_get_scheduler_int", _spy)
        with pytest.raises(_StopLoop):
            main._interval_loop("gg_delist", "gg_delist_minutes", 60, lambda: None, "测试")

        assert reads == ["gg_delist_minutes"] * 5

    def test_shrinking_config_mid_loop_takes_effect_on_next_tick(self, app, monkeypatch):
        """⚠️ 循环**跑到一半**把周期改小 → 下一 tick 立刻触发（免重启生效的端到端证据）。

        与 test_recomputes_target_each_tick 的分工（实测验证过，非推测）：
        那条 spy 恒返回 1440、只**数**读取次数 —— 它钉的是「每 tick 确实读了一次」，
        钉不住「读到的值真的参与了决策」。实测：把目标冻结成形参、每 tick 照读但不采用
        （读取次数不变），**那条仍绿**，而本用例红。
        本用例在 sleep 替身里**真改库**（走 `_get_scheduler_int` → `_get_scheduler_config`
        → DB 整条读链），断言的是行为的改变而非读取的计数：
          - tick1：目标 60 分钟 = 3600s，累计 300s，未到；
          - tick2 之前把库里的值改成 10 分钟 → 目标 600s，而 tick2 累计正好 600s ⇒ 触发。
        故断言 runs == [2]（[2] 是触发时所在的那次 sleep 序号）：读值若没被采用，
        目标恒为 3600s，要到 tick12 才可能触发，runs 会是 [] 或 [12]，本用例即红。
        """
        monkeypatch.setattr(main, "_TICK_SECONDS", 300)   # 每 tick 攒 5 分钟，便于凑整
        database.config_set("scheduler_config", json.dumps({"gg_delist_minutes": 60}))

        ticks = {"n": 0}
        runs = []

        class _MutatingTime:
            """sleep 替身：第 2 次 sleep 时把周期改小（模拟「运行途中改配置」）。"""

            def sleep(self, s):
                ticks["n"] += 1
                if ticks["n"] == 2:
                    database.config_set("scheduler_config",
                                        json.dumps({"gg_delist_minutes": 10}))
                if ticks["n"] > 3:
                    raise _StopLoop()

        monkeypatch.setattr(main, "_time", _MutatingTime())
        with pytest.raises(_StopLoop):
            main._interval_loop("gg_delist", "gg_delist_minutes", 60,
                                lambda: runs.append(ticks["n"]), "测试")

        assert main._get_scheduler_config()["gg_delist_minutes"] == 10   # 对照：改值确已落库
        assert runs == [2]        # 恰在改小后的那一 tick 触发，且全程只触发一次

    def test_does_not_run_before_full_period(self, app, monkeypatch):
        """启动后不足一个周期 → 不执行（原实现「启动立即执行一次」本就是注释掉的，语义保持）。"""
        monkeypatch.setattr(main, "_TICK_SECONDS", 1)
        monkeypatch.setattr(main, "_get_scheduler_int", lambda f, d: 1)   # 目标 60 秒
        ft = _FakeTime(stop_after=30)         # 只累计 30 秒 < 60 秒
        monkeypatch.setattr(main, "_time", ft)
        runs = []
        with pytest.raises(_StopLoop):
            main._interval_loop("gg_delist", "gg_delist_minutes", 60, lambda: runs.append(1), "测试")
        assert runs == []

    def test_due_runs_once_and_marks_ok(self, app, monkeypatch):
        """累计满一个周期 → 执行一次，并记 ok=True。"""
        monkeypatch.setattr(main, "_TICK_SECONDS", 1)
        monkeypatch.setattr(main, "_get_scheduler_int", lambda f, d: 1)   # 目标 60 秒
        ft = _FakeTime(stop_after=60)         # 第 60 次 tick 刚好触发
        monkeypatch.setattr(main, "_time", ft)
        runs = []
        with pytest.raises(_StopLoop):
            main._interval_loop("gg_delist", "gg_delist_minutes", 60, lambda: runs.append(1), "测试")
        assert runs == [1]
        assert main._get_last_run()["gg_delist"]["ok"] is True

    def test_first_failure_retries_after_60s_then_ok(self, app, monkeypatch):
        """首次抛异常 → 等 60 秒重试；重试成功记 ok=True（原实现的重试语义保留）。"""
        monkeypatch.setattr(main, "_TICK_SECONDS", 1)
        monkeypatch.setattr(main, "_get_scheduler_int", lambda f, d: 1)   # 目标 60 秒
        ft = _FakeTime(stop_after=61)         # 60 tick + 1 次出错重试的 sleep(60)
        monkeypatch.setattr(main, "_time", ft)
        calls = []

        def _run():
            calls.append(1)
            if len(calls) == 1:
                raise RuntimeError("网络炸了")

        with pytest.raises(_StopLoop):
            main._interval_loop("gg_delist", "gg_delist_minutes", 60, _run, "测试")

        assert len(calls) == 2
        assert ft.secs[60] == 60              # 第 61 次 sleep 是出错重试的 60 秒
        assert main._get_last_run()["gg_delist"]["ok"] is True

    def test_retry_failure_marks_not_ok_and_keeps_looping(self, app, monkeypatch):
        """两次都失败 → 记 ok=False，且线程不得死（还能继续下一轮 tick）。"""
        monkeypatch.setattr(main, "_TICK_SECONDS", 1)
        monkeypatch.setattr(main, "_get_scheduler_int", lambda f, d: 1)   # 目标 60 秒
        ft = _FakeTime(stop_after=61)         # 第 62 次 sleep 抛哨兵 ⇒ 证明循环活着
        monkeypatch.setattr(main, "_time", ft)

        def _run():
            raise RuntimeError("还是炸")

        with pytest.raises(_StopLoop):
            main._interval_loop("gg_delist", "gg_delist_minutes", 60, _run, "测试")

        assert main._get_last_run()["gg_delist"]["ok"] is False


class TestSchedulerWiring:
    """两个掉包调度线程的接线：target/args/daemon。"""

    def test_gg_delist_wiring(self, app, monkeypatch):
        box = _capture_thread(monkeypatch)
        main._start_delist_scheduler()
        assert box["target"] is main._interval_loop
        assert box["args"] == ("gg_delist", "gg_delist_minutes", 60,
                               main._run_delist_check_once, "掉包定时检测")
        assert box["daemon"] is True
        assert box["started"] is True

    def test_tt_delist_wiring(self, app, monkeypatch):
        """TT 默认 30 分钟、key 独立 —— 顺手「对齐」成 GG 的 60/gg_delist 本测试即红。"""
        box = _capture_thread(monkeypatch)
        main._start_tt_delist_scheduler()
        assert box["target"] is main._interval_loop
        assert box["args"] == ("tt_delist", "tt_delist_minutes", 30,
                               main._run_tt_delist_check_once, "TT 掉包定时检测")
        assert box["daemon"] is True
        assert box["started"] is True


class TestWeeklyCleanupLoop:
    """每周清理调度：分段等待 + 配置每 tick 重算 + 异常兜底。"""

    def test_wait_capped_at_tick_and_config_reread(self, app, monkeypatch):
        """⚠️ 单次 sleep 不得超过 _TICK_SECONDS，且每 tick 重读配置。

        改回「一次性 sleep(整个周期)」，本测试即红（secs 会是一个巨大的秒数）。
        """
        monkeypatch.setattr(main, "_TICK_SECONDS", 30)
        # 目标在 5 小时后 → 分段等待应封顶为 30 秒
        monkeypatch.setattr(main, "_next_cleanup_at",
                            lambda now, wd, h: now + datetime.timedelta(hours=5))
        monkeypatch.setattr(main, "_run_weekly_cleanup_once", lambda: None)  # 兜底，绝不真清理
        ft = _FakeTime(stop_after=1)          # 两个 tick（第 2 次 sleep 抛哨兵）
        monkeypatch.setattr(main, "_time", ft)
        reads = []
        _real_cfg = main._get_scheduler_config

        def _spy_cfg():
            reads.append(1)
            return _real_cfg()

        monkeypatch.setattr(main, "_get_scheduler_config", _spy_cfg)
        box = _capture_thread(monkeypatch)
        main._start_weekly_cleanup()
        with pytest.raises(_StopLoop):
            box["target"]()

        assert ft.secs == [30, 30]
        assert len(reads) == 2                # 每 tick 重读一次配置

    def test_failure_is_caught_and_marked(self, app, monkeypatch):
        """⚠️ 核心对照腿：原实现是裸调，抛异常会杀死 daemon 线程、每周清理永久静默失效。

        补 try/except 后必须吞掉异常、记 ok=False，并继续循环（否则 RuntimeError 会
        直接逸出，pytest.raises(_StopLoop) 收不到哨兵）。
        """
        monkeypatch.setattr(main, "_TICK_SECONDS", 30)
        # 目标落在过去 → sleep 后立即进入执行分支
        monkeypatch.setattr(main, "_next_cleanup_at",
                            lambda now, wd, h: now - datetime.timedelta(hours=1))

        def _boom():
            raise RuntimeError("清理炸了")

        monkeypatch.setattr(main, "_run_weekly_cleanup_once", _boom)
        ft = _FakeTime(stop_after=1)          # 第二次 sleep 抛哨兵 ⇒ 证明线程没死
        monkeypatch.setattr(main, "_time", ft)
        box = _capture_thread(monkeypatch)
        main._start_weekly_cleanup()
        with pytest.raises(_StopLoop):
            box["target"]()

        assert main._get_last_run()["cleanup"]["ok"] is False

    def test_success_marks_ok(self, app, monkeypatch):
        """成功路径记 ok=True（与失败路径的 ok=False 互为对照）。"""
        monkeypatch.setattr(main, "_TICK_SECONDS", 30)
        monkeypatch.setattr(main, "_next_cleanup_at",
                            lambda now, wd, h: now - datetime.timedelta(hours=1))
        monkeypatch.setattr(main, "_run_weekly_cleanup_once", lambda: None)
        ft = _FakeTime(stop_after=1)
        monkeypatch.setattr(main, "_time", ft)
        box = _capture_thread(monkeypatch)
        main._start_weekly_cleanup()
        with pytest.raises(_StopLoop):
            box["target"]()

        assert main._get_last_run()["cleanup"]["ok"] is True


# ============================================================
#  Task 4：三个 trigger 接口改 scheduler_required + 记录上次执行
# ============================================================

class TestTriggerEndpoints:
    """真实接口上的权限与记录（Task 1 测的是装饰器本身，这里测接线是否正确）。"""

    ENDPOINTS = [
        ("/api/admin/trigger-delist-check", "gg"),
        ("/api/admin/trigger-tt-delist-check", "tt"),
        ("/api/admin/trigger-weekly-cleanup", "gg"),
    ]

    def test_admin_platform_matrix(self, client, admin_gg_headers, admin_tt_headers,
                                   admin_fb_headers, monkeypatch):
        """⚠️ 平台映射矩阵：逐接口、双向断言「本平台 admin 200 / 其余平台 admin 403」。

        驱动式：遍历 ENDPOINTS（接口 → 期望平台）这张表，而非写死三条断言。
        将来新增接口、或改某接口的平台，只需改表，本用例自动覆盖。

        判别力来源（把任一接口的平台参数改错，哪一格会红）：
          - trigger-weekly-cleanup 的 "gg" 误写成 "tt" ⇒ admin_gg 得 403（本平台腿红）、
            admin_tt 得 200（非本平台腿红）；误写成 "fb" 同理（admin_gg 403 腿红）。
          - trigger-tt-delist-check 的 "tt" 误写成 "gg"/"fb" ⇒ admin_tt 得 403（本平台腿红）。
          - trigger-delist-check 的 "gg" 误写成 "tt"/"fb" ⇒ admin_gg 得 403（本平台腿红）。
        两条腿缺一不可：只断言 403 一侧，误写成 "fb" 仍全绿（FB 不是任何接口的本平台）；
        只断言 200 一侧，谁都被放行（403 腿丢）也看不出来。
        """
        # 三个接口都会真跑任务（掉包检测 / 每周清理），全部 stub 掉，绝不真执行。
        monkeypatch.setattr(main, "_run_delist_check_once",
                            lambda: {"total": 0, "delisted": 0, "results": []})
        monkeypatch.setattr(main, "_run_tt_delist_check_once",
                            lambda: {"total": 0, "delisted": 0, "results": []})
        monkeypatch.setattr(main, "_run_weekly_cleanup_once", lambda: None)

        admins = {"gg": admin_gg_headers, "tt": admin_tt_headers, "fb": admin_fb_headers}
        for path, expect_platform in self.ENDPOINTS:
            for platform, headers in admins.items():
                status = client.post(path, headers=headers).status_code
                if platform == expect_platform:
                    assert status == 200, (
                        f"{path} 期望平台={expect_platform}：{platform} admin 应放行，实得 {status}")
                else:
                    assert status == 403, (
                        f"{path} 期望平台={expect_platform}：{platform} admin 应被拒，实得 {status}")

    def test_admins_are_not_flat_403(self, client, admin_gg_headers, monkeypatch):
        """⚠️ 改造前三个接口对 admin 一律 403。这里断言「不再是权限拒绝」。

        不实际执行任务（会真跑检测/真删文件），只验权限闸门。
        """
        monkeypatch.setattr(main, "_run_delist_check_once", lambda: {"total": 0, "delisted": 0, "results": []})
        resp = client.post("/api/admin/trigger-delist-check", headers=admin_gg_headers)
        assert resp.status_code == 200

    def test_developer_passes_all_real_endpoints(self, client, dev_headers, monkeypatch):
        """⚠️ developer 本是改造前**唯一**被放行的角色，改造后必须照旧放行 —— 纯增量的底线。

        三个接口都过一遍：若某个接口漏挂 / 挂错装饰器（或 scheduler_required 的
        developer 分支写漏），本用例即红。Task 1 只测了探针路由，测不到接线。
        """
        monkeypatch.setattr(main, "_run_delist_check_once",
                            lambda: {"total": 0, "delisted": 0, "results": []})
        monkeypatch.setattr(main, "_run_tt_delist_check_once",
                            lambda: {"total": 0, "delisted": 0, "results": []})
        monkeypatch.setattr(main, "_run_weekly_cleanup_once", lambda: None)
        for path, _ in self.ENDPOINTS:
            assert client.post(path, headers=dev_headers).status_code == 200

    def test_tt_admin_blocked_from_gg_endpoint(self, client, admin_tt_headers):
        assert client.post("/api/admin/trigger-delist-check", headers=admin_tt_headers).status_code == 403

    def test_gg_admin_blocked_from_tt_endpoint(self, client, admin_gg_headers):
        assert client.post("/api/admin/trigger-tt-delist-check", headers=admin_gg_headers).status_code == 403

    def test_huguan_blocked_everywhere(self, client, huguan_headers):
        for path, _ in self.ENDPOINTS:
            assert client.post(path, headers=huguan_headers).status_code == 403

    def test_trigger_records_last_run(self, client, admin_gg_headers, monkeypatch):
        """执行完要留下记录 —— 界面上「上次执行」才有来源。"""
        monkeypatch.setattr(main, "_run_delist_check_once", lambda: {"total": 0, "delisted": 0, "results": []})
        client.post("/api/admin/trigger-delist-check", headers=admin_gg_headers)
        assert main._get_last_run()["gg_delist"]["ok"] is True

    def test_trigger_failure_records_not_ok(self, client, admin_gg_headers, monkeypatch):
        """⚠️ 失败分支也要记账（ok=False）—— 界面据此区分「失败」与「未执行」。

        与上一条的 ok=True 互为对照：删掉 except 里的
        `_mark_task_run("gg_delist", ok=False)`，本测试即红（KeyError: 'gg_delist'）。
        """
        def _boom():
            raise RuntimeError("检测炸了")

        monkeypatch.setattr(main, "_run_delist_check_once", _boom)
        resp = client.post("/api/admin/trigger-delist-check", headers=admin_gg_headers)
        assert resp.status_code == 500
        assert main._get_last_run()["gg_delist"]["ok"] is False


# ============================================================
#  Task 5：GET / PUT /api/admin/scheduler/config
# ============================================================

class TestSchedulerConfigApi:
    def test_gg_admin_sees_gg_tasks_only(self, client, admin_gg_headers):
        """GG 管理员：看到掉包检测 + 每周清理，看不到 TT。"""
        res = client.get("/api/admin/scheduler/config", headers=admin_gg_headers).get_json()
        keys = [t["key"] for t in res["tasks"]]
        assert keys == ["gg_delist", "cleanup"]

    def test_tt_admin_sees_tt_task_only(self, client, admin_tt_headers):
        res = client.get("/api/admin/scheduler/config", headers=admin_tt_headers).get_json()
        assert [t["key"] for t in res["tasks"]] == ["tt_delist"]

    def test_fb_admin_gets_empty_list(self, client, admin_fb_headers):
        """⚠️ FB 管理员是「200 + 空数组」，不是 403 —— 前端据此渲染空态。"""
        resp = client.get("/api/admin/scheduler/config", headers=admin_fb_headers)
        assert resp.status_code == 200
        assert resp.get_json()["tasks"] == []

    def test_developer_sees_all_three(self, client, dev_headers):
        res = client.get("/api/admin/scheduler/config", headers=dev_headers).get_json()
        assert [t["key"] for t in res["tasks"]] == ["gg_delist", "tt_delist", "cleanup"]

    def test_defaults_are_reported(self, client, admin_gg_headers):
        res = client.get("/api/admin/scheduler/config", headers=admin_gg_headers).get_json()
        gg = next(t for t in res["tasks"] if t["key"] == "gg_delist")
        assert gg["value"] == 60 and gg["min"] == 10 and gg["max"] == 1440
        assert gg["last_run"] is None          # 从未执行

    def test_update_interval(self, client, admin_gg_headers):
        res = client.put("/api/admin/scheduler/config", headers=admin_gg_headers,
                         json={"gg_delist_minutes": 120}).get_json()
        assert res["success"] is True
        assert main._get_scheduler_config()["gg_delist_minutes"] == 120

    def test_below_lower_bound_rejected(self, client, admin_gg_headers):
        """下限 10 分钟是硬闸：绕过它的路径必须被 400 堵死。"""
        resp = client.put("/api/admin/scheduler/config", headers=admin_gg_headers,
                          json={"gg_delist_minutes": 9})
        assert resp.status_code == 400
        assert main._get_scheduler_config()["gg_delist_minutes"] == 60   # 未被写入

    def test_above_upper_bound_rejected(self, client, admin_gg_headers):
        assert client.put("/api/admin/scheduler/config", headers=admin_gg_headers,
                          json={"gg_delist_minutes": 1441}).status_code == 400

    def test_boundary_values_accepted(self, client, admin_gg_headers):
        """⚠️ 边界值必须**接受**（把 `<=` 翻成 `<`，本用例即红）。

        此前低侧只测了 9（拒绝）、高侧只测了 1441（拒绝）—— 两端「恰好等于」的接受侧
        从未被钉住。两条腿分工：
          - `status_code == 200` 钉住 **PUT 侧**的 `lo <= val <= hi` / `0 <= val <= N`；
          - `_get_scheduler_config()` 回读钉住**读侧**自己那一份边界（读侧若把 `<=`
            翻成 `<`，值会被静默回落成默认值，第二句断言即红）。
        例外：`cleanup_hour=0` 在**读侧**不具判别力（默认值本就是 0，回落与接受同值），
        它只钉 PUT 侧 —— 明确记在此，免得日后误以为它守住了读侧下界。
        """
        for field, val in (("gg_delist_minutes", 10),
                           ("gg_delist_minutes", 1440),
                           ("cleanup_hour", 0),
                           ("cleanup_hour", 23),
                           ("cleanup_weekday", 0),
                           ("cleanup_weekday", 6)):
            resp = client.put("/api/admin/scheduler/config", headers=admin_gg_headers,
                              json={field: val})
            assert resp.status_code == 200, f"{field}={val} 应接受，实得 {resp.status_code}"
            got = main._get_scheduler_config()[field]
            assert got == val, f"{field}={val} 未落库或被读侧丢弃，实得 {got!r}"

    def test_boundary_values_rejected(self, client, admin_gg_headers):
        """边界外一格必须拒绝（与上一条的接受侧互为对照）。

        `-1` 此前从未测过（只测了 24 / 7 / 1441 / 9）—— 负数是「无符号解析」类改动
        最容易漏的方向。末尾断言「一个都没写进去」，防「400 了但其实先写后校验」。
        """
        for field, val in (("gg_delist_minutes", 9),
                           ("gg_delist_minutes", 1441),
                           ("cleanup_hour", -1),
                           ("cleanup_hour", 24),
                           ("cleanup_weekday", -1),
                           ("cleanup_weekday", 7)):
            resp = client.put("/api/admin/scheduler/config", headers=admin_gg_headers,
                              json={field: val})
            assert resp.status_code == 400, f"{field}={val} 应拒绝，实得 {resp.status_code}"
        assert main._get_scheduler_config() == main._SCHEDULER_DEFAULTS   # 一个都没写进去

    # 逐字段参数化：判别腿（weekday/hour）必须独立跑到，不能被前面某字段的断言提前中断
    @pytest.mark.parametrize("field", ["gg_delist_minutes", "cleanup_weekday", "cleanup_hour"])
    def test_bool_value_rejected(self, client, admin_gg_headers, field):
        """⚠️ PUT 布尔值必须 400，且一个都不许落库。

        删掉 PUT 侧那句 `or isinstance(val, bool)` 后：
          - `cleanup_weekday=true` / `cleanup_hour=true` → 通过 `0 <= val <= N`
            （`True == 1`）被静默写成「周一」/「1 点」并**返回 200** ⇒ 状态码断言即红
            —— 这两条是判别腿；
          - `gg_delist_minutes=true` → True==1 本就落在 `10~1440` 之外，状态码仍是 400，
            判别力来自**错误文案**断言（必须是整数，而不是「需在 10~1440 分钟之间」）。
        """
        resp = client.put("/api/admin/scheduler/config", headers=admin_gg_headers,
                          json={field: True})
        assert resp.status_code == 400, f"{field}=true 应 400，实得 {resp.status_code}"
        assert resp.get_json()["error"] == f"{field} 必须是整数"
        assert main._get_scheduler_config() == main._SCHEDULER_DEFAULTS   # 一个都没写进去

    def test_non_object_json_body_rejected(self, client, admin_gg_headers):
        """⚠️ truthy 的非对象 JSON（标量/字符串/数组）必须 400，不能 500。

        守卫是 `isinstance(body, dict)`：删掉它，`set(123)` 直接抛 TypeError → 500；
        `"abc"` 会走过 `set(...)`、在 `', '.join(...)` 处炸 → 也是 500。
        ⚠️ 刻意只用 **truthy** 的非对象：`0 / false / "" / []` 会先落进既有的
        「请求体为空」分支（同为 400 但文案不同），命中不了这一条守卫 —— 用它们
        等于测了另一条闸门，守卫删掉也不会红。
        """
        for bad in (123, "abc", [1]):
            resp = client.put("/api/admin/scheduler/config", headers=admin_gg_headers, json=bad)
            assert resp.status_code == 400, f"body={bad!r} 应 400，实得 {resp.status_code}"
            assert resp.get_json()["error"] == "请求体必须是 JSON 对象"

    def test_non_integer_rejected(self, client, admin_gg_headers):
        assert client.put("/api/admin/scheduler/config", headers=admin_gg_headers,
                          json={"gg_delist_minutes": "60"}).status_code == 400

    def test_tt_admin_cannot_write_gg_field(self, client, admin_tt_headers):
        """⚠️ 越权字段必须 403，不能静默忽略 —— 静默忽略会让用户以为改成功了。"""
        resp = client.put("/api/admin/scheduler/config", headers=admin_tt_headers,
                          json={"gg_delist_minutes": 120})
        assert resp.status_code == 403
        assert main._get_scheduler_config()["gg_delist_minutes"] == 60

    def test_fb_admin_cannot_write_anything(self, client, admin_fb_headers):
        assert client.put("/api/admin/scheduler/config", headers=admin_fb_headers,
                          json={"gg_delist_minutes": 120}).status_code == 403

    def test_update_cleanup_schedule(self, client, admin_gg_headers):
        client.put("/api/admin/scheduler/config", headers=admin_gg_headers,
                   json={"cleanup_weekday": 3, "cleanup_hour": 8})
        cfg = main._get_scheduler_config()
        assert cfg["cleanup_weekday"] == 3 and cfg["cleanup_hour"] == 8

    def test_invalid_hour_rejected(self, client, admin_gg_headers):
        assert client.put("/api/admin/scheduler/config", headers=admin_gg_headers,
                          json={"cleanup_hour": 24}).status_code == 400

    def test_invalid_weekday_rejected(self, client, admin_gg_headers):
        assert client.put("/api/admin/scheduler/config", headers=admin_gg_headers,
                          json={"cleanup_weekday": 7}).status_code == 400

    def test_unknown_field_rejected(self, client, admin_gg_headers):
        """未知字段直接 400 —— 防拼错字段名后「保存成功」却没生效。"""
        assert client.put("/api/admin/scheduler/config", headers=admin_gg_headers,
                          json={"gg_delist_minutse": 120}).status_code == 400

    def test_update_does_not_clobber_last_run(self, client, admin_gg_headers):
        """⚠️ 配置与运行记录分表存的意义：改周期不得抹掉上次执行时间。

        正向对照：先断言 PUT 确实生效（200 + 新值落库），再断言 last_run 仍在 ——
        否则「PUT 根本没生效」（404/403/500/静默 no-op）也会让末尾断言通过，用例形同虚设。
        """
        main._mark_task_run("gg_delist", ok=True)
        resp = client.put("/api/admin/scheduler/config", headers=admin_gg_headers,
                          json={"gg_delist_minutes": 120})
        assert resp.status_code == 200                                   # 对照：PUT 确实生效
        assert main._get_scheduler_config()["gg_delist_minutes"] == 120  # 对照：新值已落库
        assert main._get_last_run()["gg_delist"]["ok"] is True

    def test_partial_update_keeps_other_fields(self, client, admin_gg_headers):
        client.put("/api/admin/scheduler/config", headers=admin_gg_headers,
                   json={"cleanup_hour": 5})
        cfg = main._get_scheduler_config()
        assert cfg["cleanup_hour"] == 5
        assert cfg["cleanup_weekday"] == 6 and cfg["gg_delist_minutes"] == 60   # 对照

