"""定时任务：权限、周期配置、调度计算。

运行：cd py && python -m pytest tests/test_scheduler_config.py -v
"""
import datetime
import json
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
