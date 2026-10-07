# 定时任务权限下放 + 周期可配置 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把定时任务界面的权限从「仅 developer」下放到各平台 admin（按平台隔离），并让管理员能自行配置各任务的执行周期。

**Architecture:** 权限用新的 `scheduler_required(platform)` 装饰器（不复用 `require_platform` —— 它会把户管一并放行）；周期与上次执行时间存 `config` 表的两个独立 key；三个调度线程从「睡死一整个周期」改为「每 30 秒醒一次重算目标」，改配置**无需重启**即可生效。

**Tech Stack:** Flask + SQLite(config 表 key-value) + pytest(Flask test_client) + Vue 3 + Element Plus

**依据文档：**
- 设计文档 `docs/superpowers/specs/2026-10-07-scheduler-admin-access-and-interval-config-design.md`
- 视觉设计 `docs/superpowers/specs/2026-10-07-scheduler-frontend-visual-design.md`

## Global Constraints

- **纯增量**：三个 `_run_*_once`（`_run_delist_check_once` / `_run_tt_delist_check_once` / `_run_weekly_cleanup_once`）**本体一行不改**。
  **唯一例外**：`_start_weekly_cleanup` 内 `_run_weekly_cleanup_once()` 原本**裸调无 try/except**（异常会杀死该 daemon 线程，每周清理从此永久静默失效），本次补 try/except —— 已在设计文档 §5.3 显式标注为行为变更。
- **数值**（用户 2026-10-07 裁定）：掉包周期下限 **10 分钟**、上限 **1440 分钟**；默认 GG **60** / TT **30**；每周清理默认 **周日(6) 00:00**。
- `weekday` 用 Python 约定：**0=周一 … 6=周日**。
- **不新增前端依赖**，不改页面字体与主色（视觉设计 §4）。
- 注释与用户可见文案**一律中文**。
- **无对照行的断言 = 假绿**：每条测试要能说清「把它改回去，哪条会红」。
- 提交时**禁用 `git add -A`**（本仓库常有并行会话在途改文件），只 `git add` 明确路径。
- 新接口写在 `py/main.py` 现有「定时任务手动触发 API」区块（9161 起）—— 它们依赖 main 内部的 `_run_*_once`，拆到 `routes/` 会造成循环导入。

---

### Task 1: `scheduler_required` 装饰器

> **⚠️ 实施勘误（2026-10-07，实现时发现，已就地落地）**：本 Task Step 1 给的 `probe_client`
> 夹具**在夹具内注册探针路由**，这条**跑不通** —— `conftest.py` 的 `app` 夹具 yield 的是
> **模块级单例** `main.app`，而 Flask 3 在**首次请求后**会锁定 app（`setupmethod` 装饰器检查
> `_got_first_request`，再调 `.route()` 抛 `The setup method 'route' can no longer be called`）。
> 照抄的实测结果是 **1 passed / 5 errors**，不是本计划写的 6 passed。
>
> **正确做法（已采用）**：把两个探针路由放到**模块级**注册（import 时注册一次，早于任何请求），
> `probe_client` 只 `return app.test_client()`。六条用例的用例体与断言**逐字未改**。
> 副作用已评估：探针永久挂在共享 app 上，但**只影响枚举 POST 路由的测试**，
> 现存唯一的 `url_map` 枚举（`test_anon_surface`）只看 GET 且用下限而非精确数，不受影响。

**Files:**
- Modify: `py/routes/decorators.py`（在 `tt_write_required` 之后追加）
- Modify: `py/tests/conftest.py`（追加 4 个 fixtures）
- Create: `py/tests/test_scheduler_config.py`

**Interfaces:**
- Produces: `scheduler_required(platform: str)` —— 装饰器工厂；developer 放行、admin 须 `platform` 匹配、其余 403
- Produces（测试夹具）: `admin_gg_headers` / `admin_tt_headers` / `admin_fb_headers` / `huguan_headers`

- [ ] **Step 1: 写失败的测试**

新建 `py/tests/test_scheduler_config.py`：

```python
"""定时任务：权限、周期配置、调度计算。

运行：cd py && python -m pytest tests/test_scheduler_config.py -v
"""
import json
import pytest
from flask import jsonify
from flask_jwt_extended import jwt_required

import database
from routes.decorators import scheduler_required


@pytest.fixture
def probe_client(app):
    """挂两个探针路由，直接测装饰器本身（不依赖 Task 4 才落地的真实接口）。"""
    @app.route("/api/_probe/gg", methods=["POST"], endpoint="_probe_gg")
    @jwt_required()
    @scheduler_required("gg")
    def _probe_gg():
        return jsonify(success=True, platform="gg")

    @app.route("/api/_probe/tt", methods=["POST"], endpoint="_probe_tt")
    @jwt_required()
    @scheduler_required("tt")
    def _probe_tt():
        return jsonify(success=True, platform="tt")

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
```

- [ ] **Step 2: 跑测试确认失败**

```bash
cd py && python -m pytest tests/test_scheduler_config.py -v
```
预期：`ImportError: cannot import name 'scheduler_required'`（以及 fixtures 未定义）。

- [ ] **Step 3: 在 conftest.py 追加 fixtures**

在 `py/tests/conftest.py` 末尾追加。抽一个内部 helper 避免四段重复：

```python
def _make_user_with_headers(client, username, role, platform):
    """建用户 → 改角色/平台 → 登录 → 返回认证头。"""
    client.post("/api/auth/register", json={"username": username, "password": "test123"})
    db = database.get_db()
    db.execute("UPDATE users SET role=?, platform=? WHERE username=?", (role, platform, username))
    db.commit()
    db.close()
    resp = client.post("/api/auth/login", json={"username": username, "password": "test123"})
    token = resp.get_json().get("access_token", "")
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def admin_gg_headers(client):
    """GG 平台的 admin。"""
    return _make_user_with_headers(client, "admingg", "admin", "gg")


@pytest.fixture
def admin_tt_headers(client):
    """TT 平台的 admin。"""
    return _make_user_with_headers(client, "admintt", "admin", "tt")


@pytest.fixture
def admin_fb_headers(client):
    """FB 平台的 admin。"""
    return _make_user_with_headers(client, "adminfb", "admin", "fb")


@pytest.fixture
def huguan_headers(client):
    """户管。"""
    return _make_user_with_headers(client, "huguanuser", "huguan", "gg")
```

> ⚠️ `_make_user_with_headers` 放在 fixtures **之前**定义（模块级函数，不是 fixture）。

- [ ] **Step 4: 实现装饰器**

在 `py/routes/decorators.py` 的 `tt_write_required` 之后追加：

```python
def scheduler_required(platform):
    """定时任务权限：developer 跨平台放行；admin 须 platform 匹配；其余一律 403。

    ⚠️ 刻意不复用 require_platform() —— 它的 PLATFORM_SWITCH_ROLES 含 HUGUAN_ROLE，
    会把户管无条件放行，等于给户管开定时任务的后门。户管不参与定时任务。
    """
    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            try:
                uid = int(get_jwt_identity())
            except Exception:
                return err("未认证", 401)
            user = auth.get_user_by_id(uid)
            if not user:
                return err("用户不存在", 401)
            role = user.get("role")
            if role == "developer":
                return fn(*args, **kwargs)
            if role != "admin" or user.get("platform") != platform:
                return err("无权管理该定时任务", 403)
            return fn(*args, **kwargs)
        return wrapper
    return decorator
```

- [ ] **Step 5: 跑测试确认通过**

```bash
cd py && python -m pytest tests/test_scheduler_config.py -v
```
预期：6 passed。

- [ ] **Step 6: 变异验证（证明断言承重）**

把 Step 4 的 `if role != "admin" or user.get("platform") != platform:` 临时改成
`if role not in ("admin", HUGUAN_ROLE) or user.get("platform") != platform:`（模拟复用 `PLATFORM_SWITCH_ROLES` 的错误做法）。
跑测试：`test_huguan_rejected` **必须恰好 1 红**，其余保持绿。确认后**改回**并重跑至全绿。

- [ ] **Step 7: 提交**

```bash
git add py/routes/decorators.py py/tests/conftest.py py/tests/test_scheduler_config.py
git commit -m "feat(scheduler): scheduler_required 装饰器 — admin 按平台隔离，户管拒绝"
```

---

### Task 2: 配置读写 helper 与纯函数

> **实施勘误（2026-10-07）**：`last_run` 的存储结构已由「单 key 存整个 dict」改为
> **一个任务一个 key：`scheduler_last_run_{task_key}`**（如 `scheduler_last_run_gg_delist`）。
> 原因：`last_run` 有 6 个写者（3 调度线程 + 3 trigger 接口），单 key 的「读整个 dict → 改子键 →
> 写回」在交错时会丢更新；拆开后写入是单条 `INSERT OR REPLACE`，天然原子，**无需加锁**。
> 下方 Step 1 代码块里 `_get_last_run` / `_mark_task_run` 的读写仍按单 key 书写，**以实际实现为准**
> —— 现实现为：`_mark_task_run` 只写自己那一行、`_get_last_run` 遍历 `_SCHEDULER_TASKS` 逐 key 读回
> （返回值形状不变，仍是 `{task_key: {"ts":..., "ok":...}}`）。详见
> `docs/superpowers/specs/2026-10-07-scheduler-admin-access-and-interval-config-design.md` §4.1。

**Files:**
- Modify: `py/main.py`（新增 helper，放在 `_start_weekly_cleanup` 之前，约 8973 行前）
- Modify: `py/tests/test_scheduler_config.py`（追加）

**Interfaces:**
- Produces:
  - `_SCHEDULER_DEFAULTS: dict` —— `{"gg_delist_minutes": 60, "tt_delist_minutes": 30, "cleanup_weekday": 6, "cleanup_hour": 0}`
  - `_SCHEDULER_LIMITS: dict` —— `{"min_minutes": 10, "max_minutes": 1440}`
  - `_get_scheduler_config() -> dict` —— 永远返回含全部 4 个合法字段的 dict
  - `_get_scheduler_int(field: str, default: int) -> int`
  - `_next_cleanup_at(now: datetime, weekday: int, hour: int) -> datetime`
  - `_interval_tick(elapsed: int, target_seconds: int) -> tuple[bool, int]`
  - `_mark_task_run(task_key: str, ok: bool)`
  - `_get_last_run() -> dict`

- [ ] **Step 1: 写失败的测试**

在 `py/tests/test_scheduler_config.py` 追加（顶部 import 补 `import datetime`、`import main`）：

```python
import datetime


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
```

- [ ] **Step 2: 跑测试确认失败**

```bash
cd py && python -m pytest tests/test_scheduler_config.py -v
```
预期：`AttributeError: module 'main' has no attribute '_get_scheduler_config'` 等。

- [ ] **Step 3: 实现 helper**

在 `py/main.py` 约 8973 行（`def _start_weekly_cleanup` 之前）插入：

```python
# ============================================================
#  定时任务：周期配置与运行记录
# ============================================================

# 配置变更的生效粒度（秒）：调度循环每睡这么久就醒一次重算目标。
# 调小 = 改配置生效更快、数据库读取更频繁；30 秒是两头都合适的折中。
_TICK_SECONDS = 30

# 各任务的周期默认值 —— 与硬编码时代保持一致（GG 1 小时 / TT 30 分钟 / 周日 0 点）。
_SCHEDULER_DEFAULTS = {
    "gg_delist_minutes": 60,
    "tt_delist_minutes": 30,
    "cleanup_weekday": 6,     # 0=周一 … 6=周日（Python datetime.weekday() 约定）
    "cleanup_hour": 0,
}

# 掉包周期上下限（分钟）。下限 10 由用户 2026-10-07 裁定：更短会把 Google Play
# 与代理池打爆（现行 _TIMEOUT=5，代理池只有 2 个代理）。
_SCHEDULER_LIMITS = {"min_minutes": 10, "max_minutes": 1440}


def _get_scheduler_config() -> dict:
    """读定时任务配置；任何字段缺失/非法/整键不存在都回落默认值。

    调度线程每 30 秒调一次，必须永不抛异常 —— 它崩了等于定时任务全停。
    """
    try:
        raw = database.config_get("scheduler_config", "") or ""
        data = json.loads(raw) if raw else {}
        if not isinstance(data, dict):
            data = {}
    except Exception:
        data = {}

    cfg = dict(_SCHEDULER_DEFAULTS)
    lo, hi = _SCHEDULER_LIMITS["min_minutes"], _SCHEDULER_LIMITS["max_minutes"]

    for key in ("gg_delist_minutes", "tt_delist_minutes"):
        val = data.get(key)
        if isinstance(val, int) and not isinstance(val, bool) and lo <= val <= hi:
            cfg[key] = val

    val = data.get("cleanup_weekday")
    if isinstance(val, int) and not isinstance(val, bool) and 0 <= val <= 6:
        cfg["cleanup_weekday"] = val

    val = data.get("cleanup_hour")
    if isinstance(val, int) and not isinstance(val, bool) and 0 <= val <= 23:
        cfg["cleanup_hour"] = val

    return cfg


def _get_scheduler_int(field: str, default: int) -> int:
    """取单个整数配置项（带默认值兜底）。"""
    return int(_get_scheduler_config().get(field, default))


def _next_cleanup_at(now, weekday: int, hour: int):
    """算下一个清理时刻。

    等价于原实现 `timedelta(days=(days_until_sunday or 7))` —— 即「本周该时刻
    已过（含正好等于）就顺延一周」，不会同一天重复触发。
    """
    target = now.replace(hour=hour, minute=0, second=0, microsecond=0) \
        + datetime.timedelta(days=(weekday - now.weekday()) % 7)
    if target <= now:
        target += datetime.timedelta(days=7)
    return target


def _interval_tick(elapsed: int, target_seconds: int) -> tuple:
    """推进一步 tick，返回 (是否该执行, 新的 elapsed)。

    抽成纯函数是为了可测 —— 循环本体（while True + sleep）没法在测试里跑。
    """
    elapsed += _TICK_SECONDS
    if target_seconds > 0 and elapsed >= target_seconds:
        return True, 0
    return False, elapsed


def _get_last_run() -> dict:
    """读各任务上次执行记录：{task_key: {"ts": "...", "ok": bool}}。"""
    try:
        raw = database.config_get("scheduler_last_run", "") or ""
        data = json.loads(raw) if raw else {}
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _mark_task_run(task_key: str, ok: bool):
    """记一次执行（成功与否都记 —— 用户要看的是「上次跑没跑、成没成」）。"""
    last = _get_last_run()
    last[task_key] = {
        "ts": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "ok": bool(ok),
    }
    try:
        database.config_set("scheduler_last_run", json.dumps(last, ensure_ascii=False))
    except Exception as e:
        log.warning(f"记录任务执行时间失败（不影响任务本身）: {e}")
```

> **先确认 main.py 顶部已 `import json`**；若没有，补上。

- [ ] **Step 4: 跑测试确认通过**

```bash
cd py && python -m pytest tests/test_scheduler_config.py -v
```
预期：全部 passed（Task 1 的 6 条 + 本任务 16 条）。

- [ ] **Step 5: 变异验证**

把 `_next_cleanup_at` 里的 `if target <= now:` 改成 `if target < now:`，跑测试 ——
`test_sunday_exactly_at_zero_moves_to_next_week` **必须恰好 1 红**。改回后重跑至全绿。

- [ ] **Step 6: 提交**

```bash
git add py/main.py py/tests/test_scheduler_config.py
git commit -m "feat(scheduler): 周期配置读写 helper + 可测的 tick/时刻纯函数"
```

---

### Task 3: 三个调度线程改可配置周期

**Files:**
- Modify: `py/main.py`（`_start_weekly_cleanup` 8973 / `_start_delist_scheduler` 8996 / `_start_tt_delist_scheduler` 9137）

**Interfaces:**
- Consumes: `_TICK_SECONDS`、`_interval_tick`、`_next_cleanup_at`、`_get_scheduler_int`、`_get_scheduler_config`、`_mark_task_run`（Task 2）
- Produces: `_interval_loop(task_key, config_field, default_minutes, run_once, log_tag)`（供两个掉包调度复用）

- [ ] **Step 1: 新增 `_interval_loop` 并改写两个掉包调度**

在 `py/main.py` 的 Task 2 helper 区块之后、`def _start_weekly_cleanup():` 之前插入
（即 8973 附近；**别插到 8973 与 8996 之间**，那样会夹在 `_start_weekly_cleanup` 和
`_start_delist_scheduler` 中间，虽然能跑但读起来莫名其妙）：

```python
def _interval_loop(task_key, config_field, default_minutes, run_once, log_tag):
    """固定间隔任务的通用循环：每 _TICK_SECONDS 醒一次，重算目标周期。

    改配置最多 _TICK_SECONDS 秒生效，**不需要重启服务**。
    首次执行仍在启动后一整个周期（原实现「启动时立即执行一次」的代码本就是
    注释掉的，此处保持同一语义）。

    ⚠️ 周期变更**只在两次执行之间被采纳** —— 目标值是在 run_once() **之前**算的，
    正在跑的那一轮不会被打断（这是刻意设计：不想中途掐掉掉包检测）。别为了
    「让新周期立刻生效」把重算挪到执行中间或加中断。
    """
    elapsed = 0
    while True:
        _time.sleep(_TICK_SECONDS)
        target = _get_scheduler_int(config_field, default_minutes) * 60
        due, elapsed = _interval_tick(elapsed, target)
        if not due:
            continue
        try:
            run_once()
            _mark_task_run(task_key, ok=True)
        except Exception as e:
            log.warning(f"{log_tag}出错（将自动重试）: {e}")
            _time.sleep(60)          # 保留原有的出错重试语义
            try:
                run_once()
                _mark_task_run(task_key, ok=True)
            except Exception as e2:
                log.error(f"{log_tag}重试仍失败: {e2}")
                _mark_task_run(task_key, ok=False)
```

把 `_start_delist_scheduler` 整体替换为：

```python
def _start_delist_scheduler():
    """启动 GG 掉包检测定时任务（周期可配置，默认 1 小时）。"""
    t = threading.Thread(
        target=_interval_loop,
        args=("gg_delist", "gg_delist_minutes", 60, _run_delist_check_once, "掉包定时检测"),
        daemon=True,
    )
    t.start()
```

把 `_start_tt_delist_scheduler` 整体替换为：

```python
def _start_tt_delist_scheduler():
    """启动 TT 掉包检测定时任务（周期可配置，默认 30 分钟）。

    ⚠️ TT 默认 30 分钟、GG 默认 1 小时 —— 用户 2026-10-07 裁定，两侧刻意不同频。
    现在两者都可在界面上改，但**默认值不同**这一点别「顺手对齐」。
    """
    t = threading.Thread(
        target=_interval_loop,
        args=("tt_delist", "tt_delist_minutes", 30, _run_tt_delist_check_once, "TT 掉包定时检测"),
        daemon=True,
    )
    t.start()
```

- [ ] **Step 2: 改写每周清理调度**

把 `_start_weekly_cleanup` 整体替换为：

```python
def _start_weekly_cleanup():
    """每周清理定时任务（星期几 + 时刻均可配置，默认周日 00:00）。"""
    import datetime as _dt

    def _cleanup():
        while True:
            cfg = _get_scheduler_config()
            now = _dt.datetime.now()
            target = _next_cleanup_at(now, cfg["cleanup_weekday"], cfg["cleanup_hour"])
            # 分段等待：每 tick 重算目标，改配置最多 _TICK_SECONDS 秒生效
            wait = min(max((target - now).total_seconds(), 1), _TICK_SECONDS)
            _time.sleep(wait)
            if _dt.datetime.now() < target:
                continue
            # ⚠️ 原实现此处是裸调，抛异常会直接杀死该 daemon 线程、每周清理永久静默失效；
            #    补 try/except 是本次顺带的健壮性加固（见设计文档 §5.3）。
            try:
                _run_weekly_cleanup_once()
                _mark_task_run("cleanup", ok=True)
            except Exception as e:
                log.error(f"每周清理失败: {e}")
                _mark_task_run("cleanup", ok=False)

    t = threading.Thread(target=_cleanup, daemon=True)
    t.start()
```

- [ ] **Step 3: 语法与导入自检**

```bash
cd py && python -c "import ast,sys; ast.parse(open('main.py',encoding='utf-8').read()); print('AST OK')"
cd py && python -m pytest tests/ -q
```
预期：AST OK；全量测试全绿（本次改动不触碰任何既有行为）。

- [ ] **Step 4: 提交**

```bash
git add py/main.py
git commit -m "feat(scheduler): 调度线程改 tick 循环，周期可配置且免重启生效"
```

---

### Task 4: 三个 trigger 接口改造

**Files:**
- Modify: `py/main.py`（9165 / 9180 / 9195 三个路由）
- Modify: `py/tests/test_scheduler_config.py`（追加）

**Interfaces:**
- Consumes: `scheduler_required`（Task 1）、`_mark_task_run`（Task 2）

- [ ] **Step 1: 写失败的测试**

在 `py/tests/test_scheduler_config.py` 追加：

```python
class TestTriggerEndpoints:
    """真实接口上的权限与记录（Task 1 测的是装饰器本身，这里测接线是否正确）。"""

    ENDPOINTS = [
        ("/api/admin/trigger-delist-check", "gg"),
        ("/api/admin/trigger-tt-delist-check", "tt"),
        ("/api/admin/trigger-weekly-cleanup", "gg"),
    ]

    def test_admins_are_not_flat_403(self, client, admin_gg_headers, monkeypatch):
        """⚠️ 改造前三个接口对 admin 一律 403。这里断言「不再是权限拒绝」。

        不实际执行任务（会真跑检测/真删文件），只验权限闸门。
        """
        monkeypatch.setattr(main, "_run_delist_check_once", lambda: {"total": 0, "delisted": 0, "results": []})
        resp = client.post("/api/admin/trigger-delist-check", headers=admin_gg_headers)
        assert resp.status_code == 200

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
```

- [ ] **Step 2: 跑测试确认失败**

```bash
cd py && python -m pytest tests/test_scheduler_config.py::TestTriggerEndpoints -v
```
预期：`test_admins_are_not_flat_403` 失败（改造前 admin 拿 403）。

- [ ] **Step 3: 改造三个路由**

把 `py/main.py` 9165-9207 的三个路由改为（注意装饰器顺序：`@app.route` → `@jwt_required()` → `@scheduler_required(...)`）：

```python
@app.route("/api/admin/trigger-weekly-cleanup", methods=["POST"])
@jwt_required()
@scheduler_required("gg")
def admin_trigger_weekly_cleanup():
    """手动触发每周清理任务（GG 管理员 / developer）。"""
    try:
        _run_weekly_cleanup_once()
        _mark_task_run("cleanup", ok=True)
        return jsonify(success=True, message="每周清理已执行完成")
    except Exception as e:
        _mark_task_run("cleanup", ok=False)
        return jsonify(success=False, error=str(e)), 500


@app.route("/api/admin/trigger-delist-check", methods=["POST"])
@jwt_required()
@scheduler_required("gg")
def admin_trigger_delist_check():
    """手动触发 GG 掉包检测任务。"""
    try:
        result = _run_delist_check_once()
        _mark_task_run("gg_delist", ok=True)
        return jsonify(success=True, **result)
    except Exception as e:
        _mark_task_run("gg_delist", ok=False)
        return jsonify(success=False, error=str(e)), 500


@app.route("/api/admin/trigger-tt-delist-check", methods=["POST"])
@jwt_required()
@scheduler_required("tt")
def admin_trigger_tt_delist_check():
    """手动触发 TT 掉包检测任务。"""
    try:
        result = _run_tt_delist_check_once()
        _mark_task_run("tt_delist", ok=True)
        return jsonify(success=True, **result)
    except Exception as e:
        _mark_task_run("tt_delist", ok=False)
        return jsonify(success=False, error=str(e)), 500
```

补 import（第 44 行 `from routes.decorators import reject_viewer as _reject_viewer, require_platform as _require_platform, no_huguan`
是**重命名导入**风格；`scheduler_required` 无重名冲突，单独起一行即可，diff 最小）：

```python
from routes.decorators import scheduler_required
```

- [ ] **Step 4: 跑测试确认通过**

```bash
cd py && python -m pytest tests/test_scheduler_config.py -v
```
预期：全部 passed。

- [ ] **Step 5: 提交**

```bash
git add py/main.py py/tests/test_scheduler_config.py
git commit -m "feat(scheduler): 三个 trigger 接口改 scheduler_required + 记录上次执行"
```

---

### Task 5: 新增配置读写接口

**Files:**
- Modify: `py/main.py`（紧接三个 trigger 路由之后）
- Modify: `py/tests/test_scheduler_config.py`（追加）

**Interfaces:**
- Consumes: `_get_scheduler_config`、`_SCHEDULER_LIMITS`、`_get_last_run`（Task 2）、`scheduler_required`（Task 1）
- Produces: `GET /api/admin/scheduler/config`、`PUT /api/admin/scheduler/config`

**任务→字段→平台映射表**（GET 与 PUT 共用，实现时提为模块级常量）：

```python
_SCHEDULER_TASKS = [
    {"key": "gg_delist", "name": "掉包检测",    "platform": "gg", "kind": "interval", "field": "gg_delist_minutes"},
    {"key": "tt_delist", "name": "TT 掉包检测", "platform": "tt", "kind": "interval", "field": "tt_delist_minutes"},
    {"key": "cleanup",   "name": "每周清理",    "platform": "gg", "kind": "weekly",   "field": None},
]
```

- [ ] **Step 1: 写失败的测试**

在 `py/tests/test_scheduler_config.py` 追加：

```python
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
        """⚠️ 配置与运行记录分表存的意义：改周期不得抹掉上次执行时间。"""
        main._mark_task_run("gg_delist", ok=True)
        client.put("/api/admin/scheduler/config", headers=admin_gg_headers,
                   json={"gg_delist_minutes": 120})
        assert main._get_last_run()["gg_delist"]["ok"] is True

    def test_partial_update_keeps_other_fields(self, client, admin_gg_headers):
        client.put("/api/admin/scheduler/config", headers=admin_gg_headers,
                   json={"cleanup_hour": 5})
        cfg = main._get_scheduler_config()
        assert cfg["cleanup_hour"] == 5
        assert cfg["cleanup_weekday"] == 6 and cfg["gg_delist_minutes"] == 60   # 对照
```

- [ ] **Step 2: 跑测试确认失败**

```bash
cd py && python -m pytest tests/test_scheduler_config.py::TestSchedulerConfigApi -v
```
预期：404（路由不存在）。

- [ ] **Step 3: 实现两个接口**

在三个 trigger 路由之后追加（同一区块内）：

```python
# 任务 → 平台 / 配置字段映射。GET 与 PUT 共用，避免两处口径漂移。
_SCHEDULER_TASKS = [
    {"key": "gg_delist", "name": "掉包检测", "platform": "gg", "kind": "interval",
     "field": "gg_delist_minutes"},
    {"key": "tt_delist", "name": "TT 掉包检测", "platform": "tt", "kind": "interval",
     "field": "tt_delist_minutes"},
    {"key": "cleanup", "name": "每周清理", "platform": "gg", "kind": "weekly",
     "field": None},
]


def _visible_scheduler_tasks(user) -> list:
    """该用户有权管理的任务。developer 看全部；admin 只看本平台；其余为空。"""
    if user.get("role") == "developer":
        return list(_SCHEDULER_TASKS)
    if user.get("role") == "admin":
        return [t for t in _SCHEDULER_TASKS if t["platform"] == user.get("platform")]
    return []


@app.route("/api/admin/scheduler/config", methods=["GET"])
@jwt_required()
def admin_scheduler_config_get():
    """读取定时任务配置。

    权限：任何 admin/developer 都可读 —— 刻意**不用** scheduler_required(platform)，
    否则 FB 管理员（无任务）会拿到 403 而不是空列表，前端就没法渲染空态。
    """
    user = auth.get_user_by_id(int(get_jwt_identity()))
    if not user or user.get("role") not in ("developer", "admin"):
        return jsonify(success=False, error="权限不足，仅管理员可操作"), 403

    cfg = _get_scheduler_config()
    last = _get_last_run()
    lo, hi = _SCHEDULER_LIMITS["min_minutes"], _SCHEDULER_LIMITS["max_minutes"]

    tasks = []
    for t in _visible_scheduler_tasks(user):
        item = {"key": t["key"], "name": t["name"], "platform": t["platform"], "kind": t["kind"]}
        if t["kind"] == "interval":
            # 一并回传字段名：前端保存时直接用它拼 payload，
            # 避免前后端各维护一份 key → field 映射而漂移
            item.update({"value": cfg[t["field"]], "min": lo, "max": hi, "field": t["field"]})
        else:
            item.update({"weekday": cfg["cleanup_weekday"], "hour": cfg["cleanup_hour"]})
        item["last_run"] = last.get(t["key"])      # None = 从未执行（区别于 ok=False）
        tasks.append(item)

    return jsonify(success=True, tasks=tasks)


@app.route("/api/admin/scheduler/config", methods=["PUT"])
@jwt_required()
def admin_scheduler_config_put():
    """修改定时任务配置。只接受调用者有权管理的字段，越权字段一律 403。"""
    user = auth.get_user_by_id(int(get_jwt_identity()))
    if not user or user.get("role") not in ("developer", "admin"):
        return jsonify(success=False, error="权限不足，仅管理员可操作"), 403

    body = request.get_json(silent=True) or {}
    if not body:
        return jsonify(success=False, error="请求体为空"), 400

    allowed = set()
    for t in _visible_scheduler_tasks(user):
        if t["field"]:
            allowed.add(t["field"])
        else:
            allowed.update({"cleanup_weekday", "cleanup_hour"})
    known = {"gg_delist_minutes", "tt_delist_minutes", "cleanup_weekday", "cleanup_hour"}

    # 越权字段 → 403（不静默忽略：静默会让用户以为改成功了）
    if set(body) - allowed:
        if set(body) & known:
            return jsonify(success=False, error="无权修改该定时任务"), 403
        return jsonify(success=False, error=f"未知字段: {', '.join(sorted(set(body) - known))}"), 400

    lo, hi = _SCHEDULER_LIMITS["min_minutes"], _SCHEDULER_LIMITS["max_minutes"]
    cfg = _get_scheduler_config()

    for key, val in body.items():
        if not isinstance(val, int) or isinstance(val, bool):
            return jsonify(success=False, error=f"{key} 必须是整数"), 400
        if key in ("gg_delist_minutes", "tt_delist_minutes"):
            if not (lo <= val <= hi):
                return jsonify(success=False, error=f"{key} 需在 {lo}~{hi} 分钟之间"), 400
        elif key == "cleanup_weekday":
            if not (0 <= val <= 6):
                return jsonify(success=False, error="cleanup_weekday 需在 0~6 之间（0=周一）"), 400
        elif key == "cleanup_hour":
            if not (0 <= val <= 23):
                return jsonify(success=False, error="cleanup_hour 需在 0~23 之间"), 400
        cfg[key] = val

    database.config_set("scheduler_config", json.dumps(cfg, ensure_ascii=False))
    return jsonify(success=True, config=cfg)
```

> **注意**：GET 用 `scheduler_required_minimal` 是不存在的 —— 改为 `@jwt_required()` + 函数体内联角色判断（如上面所示），**不要**写 `scheduler_required_minimal` 这个占位名。GET 的权限是「admin 或 developer」，与平台无关（FB 管理员要能进页面看空态）。

- [ ] **Step 4: 跑测试确认通过**

```bash
cd py && python -m pytest tests/test_scheduler_config.py -v
```
预期：全部 passed。

- [ ] **Step 5: 变异验证**

把 PUT 里的 `if set(body) - allowed:` 分支临时删掉（改成只写不校验），跑测试 ——
`test_tt_admin_cannot_write_gg_field` 与 `test_unknown_field_rejected` **必须红**。改回后重跑至全绿。

- [ ] **Step 6: 提交**

```bash
git add py/main.py py/tests/test_scheduler_config.py
git commit -m "feat(scheduler): 新增 GET/PUT /api/admin/scheduler/config（按平台返回 + 越权 403）"
```

---

### Task 6: 前端接线（API / 侧边栏 / 路由）

**Files:**
- Modify: `frontend/src/api/admin.js`
- Modify: `frontend/src/components/AppSidebar.vue`（3 处）
- Modify: `frontend/src/router/index.js`（1 处）

**Interfaces:**
- Produces: `adminApi.getSchedulerConfig()` / `adminApi.updateSchedulerConfig(payload)`

- [ ] **Step 1: 补 API 方法**

`frontend/src/api/admin.js` 的 `adminApi` 对象内追加：

```js
  getSchedulerConfig() {
    return api.get('/admin/scheduler/config')
  },
  updateSchedulerConfig(data) {
    return api.put('/admin/scheduler/config', data)
  },
```

- [ ] **Step 2: 侧边栏放开**

`frontend/src/components/AppSidebar.vue` 第 78 / 96 / 112 行是**三行完全相同**的导航配置
（分别属于 gg / fb / tt 三份 nav），定时任务项内联在同一行里：

```js
{ icon:'⏰',label:'定时任务',path:'/admin/scheduler',developer:true }
```

把三处**同一子串** `path:'/admin/scheduler',developer:true }` 替换为
`path:'/admin/scheduler',admin:true }`
（三行内容一致，编辑时命中哪一行都一样；用 replace-all 一次改完）。

> ⚠️ **是「改成 `admin:true`」而不是「删掉标记」** —— 这两个选项差别很大，别图省事删掉。
>
> AppSidebar 的菜单过滤分两层（`AppSidebar.vue:184-196`）：
> ```js
> if (!auth.isDeveloper) items = items.filter(i => !i.developer)
> if (!auth.isAdmin)     items = items.filter(i => !i.admin)
> ```
> 而顶层「管理」组的准入是 `if (n.admin) return auth.isAdmin || auth.isHuguan`（165-167 行）
> —— **户管会进到这个组里**。于是：
>
> | 写法 | GG admin | 户管 | 普通 user |
> |---|---|---|---|
> | 删掉标记 | 可见 ✓ | **可见 ✗**（点进去才被路由踢） | **可见 ✗** |
> | 改成 `admin:true` | 可见 ✓ | 被第二条 filter 挡掉 ✓ | 被挡掉 ✓ |
>
> developer 两条 filter 都跳过，所以 `admin:true` 对 developer 也是可见的 ——
> 语义正好是「管理员 + developer」，即本次要的权限集合。
>
> 平台隔离靠**菜单归属**实现：GG 管理员的 nav 在 gg 组、TT 管理员在 tt 组，
> 各自只看到自己那份里的定时任务入口。

- [ ] **Step 3: 路由 meta 放开**

`frontend/src/router/index.js` 第 84-88 行，把 meta 从 `developer` 改为 `admin`：

```js
  {
    path: '/admin/scheduler',
    component: () => import('../views/SchedulerView.vue'),
    meta: { admin: true, title: '定时任务' }
  },
```

> 户管白名单 `HUGUAN_ROUTES`（180-185 行）**不含** `/admin/scheduler`，所以户管仍进不去。

- [ ] **Step 4: 校验改动**

```bash
cd frontend
grep -o "developer:true" src/components/AppSidebar.vue | wc -l            # 期望 0
grep -o "scheduler',admin:true" src/components/AppSidebar.vue | wc -l     # 期望 3
grep -n "title: '定时任务'" src/router/index.js                            # 期望 meta 行为 admin: true
```

预期：`0` / `3` / 一行 `meta: { admin: true, title: '定时任务' }`。

> 菜单可见性是纯前端行为，pytest 覆盖不到 —— 这一条靠上面的静态校验 + Task 7 完成后的人工确认
> （用 admin 与户管账号各看一次侧边栏）。**别只看接口 403 就认为菜单也对了**。

- [ ] **Step 5: 提交**

```bash
git add frontend/src/api/admin.js frontend/src/components/AppSidebar.vue frontend/src/router/index.js
git commit -m "feat(scheduler): 前端接线 — 定时任务页对 admin 开放（按平台菜单隔离）"
```

---

### Task 7: SchedulerView 改造

**Files:**
- Modify: `frontend/src/views/SchedulerView.vue`

**Interfaces:**
- Consumes: `adminApi.getSchedulerConfig()` / `adminApi.updateSchedulerConfig()`（Task 6）
- **依据**：`docs/superpowers/specs/2026-10-07-scheduler-frontend-visual-design.md`（线框、token、文案表）

- [ ] **Step 1: 改模板**

三个要点：

1. 三张硬编码 `el-card` → `v-for="task in tasks"` 数据驱动，按 `task.kind` 分派频率控件
2. 移除三处 `<el-tag>自动频率：…</el-tag>`（**含 TT 卡片那处写错的「每小时」**）；tag 行可能为空，用 `v-if` 兜住
3. 卡片内划「调度条」：分隔线 + 左周期编辑 + 右上次执行；`tasks.length === 0` 时渲染空态块

调度的骨架：

```vue
<div class="schedule-bar">
  <div class="schedule-edit">
    <template v-if="task.kind === 'interval'">
      <span class="schedule-label">每</span>
      <el-input-number v-model="draft[task.key]" :min="task.min" :max="task.max"
                       :step="10" size="small" controls-position="right" style="width:110px;" />
      <span class="schedule-label">分钟</span>
    </template>
    <template v-else>
      <span class="schedule-label">每周</span>
      <el-select v-model="draftWeekday" size="small" style="width:88px;">
        <el-option v-for="(d, i) in WEEKDAYS" :key="i" :label="d" :value="i" />
      </el-select>
      <el-select v-model="draftHour" size="small" style="width:96px;">
        <el-option v-for="h in 24" :key="h - 1" :label="pad2(h - 1) + ':00'" :value="h - 1" />
      </el-select>
    </template>
    <el-button size="small" type="primary" plain :disabled="!dirty(task)"
               :loading="saving" @click="saveTask(task)">保存</el-button>
  </div>
  <div class="schedule-last" :class="{ failed: task.last_run && !task.last_run.ok }">
    {{ lastRunText(task.last_run) }}
  </div>
</div>
```

空态块：

```vue
<div v-if="!loading && tasks.length === 0" class="scheduler-empty">
  <div class="empty-icon">🗓️</div>
  <div class="empty-title">当前平台暂无可管理的定时任务</div>
  <div class="empty-desc">
    定时任务按平台划分：Google Ads 掉包检测与每周清理归 GG，TikTok 掉包检测归 TT。
  </div>
</div>
```

- [ ] **Step 2: 改脚本**

新增（**不删改**既有 `triggerDelist` / `triggerTtDelist` / `triggerCleanup` 与 `unknownCount` / `onMounted` 恢复逻辑）。

> **import 行不用改**：文件已有 `import { ref, onMounted } from 'vue'`（第 114 行）、
> `import { adminApi } from '../api/admin'`（115）、`import { ElMessage } from 'element-plus'`（117），
> 全部够用。本任务不需要 `computed`（`dirty()` 用普通函数即可），**不要**顺手加进来。

```js
const WEEKDAYS = ['周一', '周二', '周三', '周四', '周五', '周六', '周日']

const tasks = ref([])
const loading = ref(true)
const saving = ref(false)
const draft = ref({})          // { gg_delist: 60, tt_delist: 30 }  —— interval 类
const draftWeekday = ref(6)
const draftHour = ref(0)

async function loadConfig() {
  loading.value = true
  try {
    const res = await adminApi.getSchedulerConfig()
    tasks.value = res.tasks || []
    for (const t of tasks.value) {
      if (t.kind === 'interval') draft.value[t.key] = t.value
      else { draftWeekday.value = t.weekday; draftHour.value = t.hour }
    }
  } catch (e) {
    ElMessage.error('读取定时任务配置失败：' + (e?.response?.data?.error || e.message))
  } finally {
    loading.value = false
  }
}

function dirty(task) {
  if (task.kind === 'interval') return draft.value[task.key] !== task.value
  return draftWeekday.value !== task.weekday || draftHour.value !== task.hour
}

async function saveTask(task) {
  // interval 类用后端回传的 task.field，不在这里硬编码字段名（防前后端漂移）
  const payload = task.kind === 'interval'
    ? { [task.field]: draft.value[task.key] }
    : { cleanup_weekday: draftWeekday.value, cleanup_hour: draftHour.value }
  saving.value = true
  try {
    await adminApi.updateSchedulerConfig(payload)
    ElMessage.success('已保存，将在 30 秒内生效')
    await loadConfig()
  } catch (e) {
    ElMessage.error('保存失败：' + (e?.response?.data?.error || e.message))
  } finally {
    saving.value = false
  }
}

function pad2(n) { return String(n).padStart(2, '0') }

// 今天 / 昨天 / MM-DD；失败与从未执行是两回事，必须分开
function lastRunText(last) {
  if (!last) return '尚未执行'
  const t = String(last.ts || '').replace('T', ' ')
  const hhmmss = t.slice(11, 19)
  const day = t.slice(0, 10)
  const now = new Date()
  const today = `${now.getFullYear()}-${pad2(now.getMonth() + 1)}-${pad2(now.getDate())}`
  const y = new Date(now.getTime() - 86400000)
  const yesterday = `${y.getFullYear()}-${pad2(y.getMonth() + 1)}-${pad2(y.getDate())}`
  const when = day === today ? '今天' : (day === yesterday ? '昨天' : day.slice(5))
  return last.ok ? `上次执行 ${when} ${hhmmss}` : `上次执行失败（${day.slice(5)} ${hhmmss}）`
}
```

`onMounted` 里加 `loadConfig()`；三个 `trigger*` 函数成功后各加一次 `loadConfig()`（刷新「上次执行」）。

- [ ] **Step 3: 加样式**

```css
.schedule-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
  margin-top: 14px;
  padding-top: 12px;
  border-top: 1px solid #f3f4f6;
}
.schedule-edit { display: flex; align-items: center; gap: 6px; }
.schedule-label { font-size: 13px; color: #6b7280; }
.schedule-last {
  font-size: 13px;
  color: #9ca3af;
  font-variant-numeric: tabular-nums;
}
.schedule-last.failed { color: #ef4444; }

.scheduler-empty { text-align: center; padding: 56px 20px; }
.empty-icon { font-size: 40px; line-height: 1; margin-bottom: 16px; }
.empty-title { font-size: 15px; font-weight: 600; color: #374151; margin-bottom: 8px; }
.empty-desc { font-size: 13px; color: #9ca3af; line-height: 1.6; }
```

- [ ] **Step 4: SFC 编译自检**

用项目自带的 `@vue/compiler-sfc` 解析并编译该文件（不跑完整 build）：

```bash
cd frontend && node -e "
const sfc=require('@vue/compiler-sfc');const fs=require('fs');
const f='src/views/SchedulerView.vue';const src=fs.readFileSync(f,'utf8');
const {descriptor,errors}=sfc.parse(src,{filename:f});
if(errors.length){console.log('FAIL parse',errors.map(e=>e.message));process.exit(1)}
const t=sfc.compileTemplate({source:descriptor.template.content,filename:f,id:'s'});
if(t.errors.length){console.log('FAIL template',t.errors);process.exit(1)}
sfc.compileScript(descriptor,{id:'s'});
console.log('PASS SFC ok');
"
```
预期：`PASS SFC ok`。

- [ ] **Step 5: 提交**

```bash
git add frontend/src/views/SchedulerView.vue
git commit -m "feat(scheduler): 页面数据驱动 — 周期可编辑 + 上次执行 + 平台空态"
```

---

### Task 8: 文档收口

**Files:**
- Modify: `AGENTS.md`

- [ ] **Step 1: 补接口表缺口**

「### 定时任务（仅 developer）」接口表：

1. 标题改为「### 定时任务（按平台的管理员 / developer）」
2. **补上漏掉的 `POST /api/admin/trigger-tt-delist-check`**
3. 新增两行 `GET/PUT /api/admin/scheduler/config`
4. 表下补一段权限说明：GG 管理员 → `trigger-delist-check` + `trigger-weekly-cleanup`；TT 管理员 → `trigger-tt-delist-check`；FB 管理员无任务（页面空态）；户管一律 403（⚠️ 勿用 `require_platform` —— `PLATFORM_SWITCH_ROLES` 含户管）

- [ ] **Step 2: 更新「定时任务系统」小节**

把「**手动触发**：SchedulerView 页面，仅 developer 角色可见」改为：管理员按平台可见，且**周期可在页面上配置**（存 `config.scheduler_config`，`_TICK_SECONDS=30` 秒内生效，无需重启）。同时记明默认值 GG 60 / TT 30 / 周日 0 点，及下限 10 分钟的理由。

- [ ] **Step 3: 更新项目结构注释**

`SchedulerView.vue` 后的注释 `# 定时任务手动触发（developer）` → `# 定时任务（按平台管理员）`。

- [ ] **Step 4: 提交**

```bash
git add AGENTS.md
git commit -m "docs(scheduler): 补 trigger-tt-delist-check 接口 + 权限与周期配置说明"
```

---

## 收尾（不属于任何 task）

- ⚠️ **后端改动后必须重启 Flask 才能生效** —— 先征得用户同意再重启。
- ⚠️ **前端改动后必须 `npm run build`**（Tailscale 部署下其他人看不到 5173）。
- 按项目规范，本次触及**权限/鉴权**，实现完成后**必须走 `/code-review`**。
- 全量回归：`cd py && python -m pytest tests/ -q`。
