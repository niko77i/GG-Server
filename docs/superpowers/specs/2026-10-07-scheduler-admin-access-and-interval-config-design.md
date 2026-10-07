# 定时任务：权限下放到管理员 + 周期可配置

> 状态：**已确认**（2026-10-07），待写实现计划
> 日期：2026-10-07

## 1. 需求

来自用户 2026-10-07 口述，四件事：

1. **补文档缺口**：AGENTS.md 的「定时任务（仅 developer）」表漏了 `POST /api/admin/trigger-tt-delist-check`。
2. **定时界面权限下放到所有管理员**（不再仅 developer）。
3. **管理员按平台看到对应任务**，后端也按平台限制调用：
   - GG 管理员 → GG 掉包检测 + 每周清理
   - TT 管理员 → TT 掉包检测
   - 每周清理**属于 GG**
   - （用户已裁定：FB 管理员显示**空态提示**，保留入口）
4. **新增「手动修改定时周期」的接口与界面**，管理员可设置各任务的执行周期。

### 用户已裁定的三个决策点

| 问题 | 裁定 |
|---|---|
| FB 管理员（平台无任务）看到什么 | **显示空态提示**，保留菜单入口 |
| 每周清理怎么配 | **星期几 + 时刻**（保留日历语义，默认仍周日 00:00） |
| 掉包检测周期下限 | **下限 10 分钟** |

## 2. 现状（已核实的代码事实）

### 2.1 调度实现：周期全是硬编码

| 任务 | 函数 | 现状 | 位置 |
|---|---|---|---|
| GG 掉包检测 | `_start_delist_scheduler` | `while True: time.sleep(3600)` | `main.py:8996` |
| TT 掉包检测 | `_start_tt_delist_scheduler` | `while True: time.sleep(1800)` | `main.py:9137` |
| 每周清理 | `_start_weekly_cleanup` | 算下个周日 00:00 后 `sleep` 到位 | `main.py:8973` |

三者在 `main.py:11020-11022` 启动。**周期没有任何持久化，改一次要改代码重启。**

### 2.2 权限：三重 developer 限制

| 层 | 现状 |
|---|---|
| 侧边栏 | `ggNavItems` / `fbNavItems` / `ttNavItems` 三份配置里，定时任务项带 `developer: true`（`AppSidebar.vue:78/96/112`） |
| 路由 | `meta: { developer: true }`（`router/index.js:87`） |
| 后端 | 三个 trigger 接口各自 `user["role"] != "developer"` → 403 |

### 2.3 关键约束（决定了方案怎么写）

- ⚠️ **`require_platform()` 不能直接复用**：`PLATFORM_SWITCH_ROLES = ("developer", HUGUAN_ROLE)`（`routes/helpers.py:12`），**户管会被无条件放行**。用它做定时任务限制等于给户管开后门。
- ✅ 户管白名单 `HUGUAN_ROUTES`（`router/index.js:180-185`）**不含** `/admin/scheduler` → 路由改成 `meta.admin` 后户管自动进不去。
- ✅ 户管用的是独立的三份 nav（`huguanNavItems` / `huguanFbNavItems` / `huguanTtNavItems`），**里面本就没有定时任务项** → 侧边栏天然隔离。
- ✅ `database.config_get(key, default)` / `config_set(key, value)` 现成可用（`database.py:2210/2218`），config 表是 key-value。
- ✅ 实库 admin 分布：gg×6、tt×2、fb×1；developer 2 人（platform 均为 gg）。**各平台确实都有管理员。**

## 3. 权限模型

### 3.1 任务与平台归属

| task key | 名称 | 平台 | 可配置项 | 默认值 |
|---|---|---|---|---|
| `gg_delist` | 掉包检测 | gg | 间隔（分钟） | 60 |
| `tt_delist` | TT 掉包检测 | tt | 间隔（分钟） | 30 |
| `cleanup` | 每周清理 | gg | 星期几 + 小时 | 周日(6) + 0 点 |

### 3.2 权限矩阵

| 角色 | 可见 | 可「立即执行」 | 可改周期 |
|---|---|---|---|
| developer | 全部三项 | 全部 | 全部 |
| admin (platform=gg) | `gg_delist` + `cleanup` | 同左 | 同左 |
| admin (platform=tt) | `tt_delist` | 同左 | 同左 |
| admin (platform=fb) | 无 → **空态提示** | — | — |
| huguan / user / viewer | 无（入口不可见） | 403 | 403 |

### 3.3 后端装饰器（新增）

`routes/decorators.py` 新增：

```python
def scheduler_required(platform):
    """定时任务权限：developer 跨平台放行；admin 须 platform 匹配；其余 403。

    刻意不复用 require_platform —— 后者把户管也放行（PLATFORM_SWITCH_ROLES）。
    """
    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            uid = int(get_jwt_identity())
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

三个已存在的 trigger 接口改用它：

| 接口 | 改为 |
|---|---|
| `POST /api/admin/trigger-delist-check` | `@scheduler_required("gg")` |
| `POST /api/admin/trigger-tt-delist-check` | `@scheduler_required("tt")` |
| `POST /api/admin/trigger-weekly-cleanup` | `@scheduler_required("gg")` |

> 保留 `@jwt_required()` 在外层。

## 4. 周期配置的数据结构

**存储**：`config` 表单键 JSON（`key = 'scheduler_config'`）。

```json
{
  "gg_delist_minutes": 60,
  "tt_delist_minutes": 30,
  "cleanup_weekday": 6,
  "cleanup_hour": 0
}
```

**为什么不拆成多个 key**：原子读写（一次 `config_get` 拿全）、加任务不用改 schema、出问题好回滚（单键删掉即回默认）。

**读取**：`_get_scheduler_config()` 解析 JSON；**任何字段缺失/非法/整键不存在，都回落到上表默认值**（键不存在 = 首次运行，不能崩）。

**校验规则**（写侧，违反一律 400）：

| 字段 | 规则 |
|---|---|
| `gg_delist_minutes` / `tt_delist_minutes` | 整数，**≥ 10**（用户裁定下限），≤ 1440（24 小时） |
| `cleanup_weekday` | 整数 0-6（0=周一 … 6=周日） |
| `cleanup_hour` | 整数 0-23 |

### 4.1 上次执行时间（用户 2026-10-07 确认要做）

**一个任务一个 key**：`scheduler_last_run_{task_key}`（如 `scheduler_last_run_gg_delist` /
`scheduler_last_run_tt_delist` / `scheduler_last_run_cleanup`），与配置**分开**。

每个 key 只存**单个任务**的记录，不再是一个 dict 装全部任务：

```json
"scheduler_last_run_gg_delist" = {"ts": "2026-10-07 12:00:03", "ok": true}
"scheduler_last_run_tt_delist" = {"ts": "2026-10-07 12:30:01", "ok": false}
"scheduler_last_run_cleanup"   = {"ts": "2026-10-05 00:00:02", "ok": true}
```

写入端把每个任务收敛成自己那一行；读取端（`_get_last_run`）遍历任务清单逐 key 读回，
仍**拼成同一形状**的 `{task_key: {"ts":..., "ok":...}}` 返回，故接口与既有测试不受影响。

**为什么另起一个 key 而不是塞进 `scheduler_config`**：

1. **写侧不同**：config 只有管理员 PUT 时写；last_run 只有调度线程写。混在一起，两个写侧就变成 read-modify-write 竞争 —— 管理员保存周期的同时任务跑完，后写的一方会把另一方抹掉。
2. **权限不同**：config 是「有权限才能改」，last_run 是「人人可读」的运行时状态。分开后 PUT 接口不必费心保护哪些字段不许覆盖。
3. `scheduler_config` 是**用户意图**，`scheduler_last_run` 是**运行事实**，出问题时能各自回滚。

**为什么还要再拆到每任务一个 key**：`last_run` 自己也有 **6 个写者**（3 个调度线程 + 3 个
trigger 接口）。单个 key 存整个 dict 时，写入路径是「读整个 dict → 改子键 → 写回整个 dict」，
读写之间无事务，两个写者交错就会丢更新（后写者拿旧快照覆盖先写者）。拆成每任务一个 key 后，
每个写者只写**自己那一个** key，写入退化为单条 `INSERT OR REPLACE`，天然原子，**无需任何锁**
—— 共享状态根本不存在。这是「与 `scheduler_config` 分开」之上再加的一层。

**写入时机**：**任何一次执行完成都记**（定时调度与管理员点「立即执行」都算），`ok` 记本轮成功与否。

**落点**：不写进 `_run_*_once` 本体（保持「检测逻辑一行不动」），而在**调用点**包一层 —— 调度循环与三个 trigger 接口都调 `_mark_task_run(task_key, ok)`。

## 5. 调度线程改造

### 5.1 核心思路：分段等待 + 每段重读配置

现有循环是「睡满一整个周期再执行」，周期写死。改成**每 `_TICK_SECONDS = 30` 秒醒一次**，醒来时重算目标：配置改动最多 30 秒生效，**不需要重启**。

### 5.2 掉包检测（两个循环合一）

```python
_TICK_SECONDS = 30  # 配置变更的生效粒度

def _interval_loop(task_key, config_field, default_minutes, run_once, log_tag):
    elapsed = 0
    while True:
        _time.sleep(_TICK_SECONDS)
        elapsed += _TICK_SECONDS
        target = _scheduler_int(config_field, default_minutes) * 60
        if elapsed >= target:
            elapsed = 0
            try:
                run_once()
                _mark_task_run(task_key, ok=True)     # 见 §4.1
            except Exception as e:
                log.warning(f"{log_tag}出错（将自动重试）: {e}")
                _time.sleep(60)          # 保留既有的出错重试语义
                try:
                    run_once()
                    _mark_task_run(task_key, ok=True)
                except Exception as e2:
                    log.error(f"{log_tag}重试仍失败: {e2}")
                    _mark_task_run(task_key, ok=False)
```

- GG 调 `_interval_loop("gg_delist", "gg_delist_minutes", 60, _run_delist_check_once, "掉包定时检测")`
- TT 调 `_interval_loop("tt_delist", "tt_delist_minutes", 30, _run_tt_delist_check_once, "TT 掉包定时检测")`

> ⚠️ `_mark_task_run` 必须写在 `run_once()` **之后**、且在 `except` 分支里各自成对出现 ——
> 失败时也要记（用户要看的是「上次跑没跑、成没成」，不是「上次成功是什么时候」）。

**行为边界**：
- 首次执行仍在启动后一整个周期（现状「启动时立即执行一次」的代码本就是注释掉的，**不改这个语义**）。
- 周期改小 → `elapsed` 可能已超新周期 → 下一 tick 就触发（用户想要更快，符合预期）。
- 周期改大 → `elapsed` 保留 → 按新周期等（不会因为改大就立刻跑）。

### 5.3 每周清理

```python
def _cleanup_loop():
    while True:
        weekday, hour = _scheduler_cleanup_schedule()   # 每 tick 重读
        now = _dt.datetime.now()
        target = now.replace(hour=hour, minute=0, second=0, microsecond=0) \
                 + _dt.timedelta(days=(weekday - now.weekday()) % 7)
        if target <= now:                 # 本周该时刻已过 → 顺延一周
            target += _dt.timedelta(days=7)
        _time.sleep(min(max((target - now).total_seconds(), 1), _TICK_SECONDS))
        if _dt.datetime.now() >= target:
            try:
                _run_weekly_cleanup_once()
                _mark_task_run("cleanup", ok=True)
            except Exception as e:
                log.error(f"每周清理失败: {e}")
                _mark_task_run("cleanup", ok=False)
```

**必须保住原语义**：原实现里 `days_until_sunday or 7` 意味着「今天是周日但 00:00 已过 → 等下周」，`target <= now → += 7 days` 是等价写法。**不得因为重构变成同一天重复触发。**

> ⚠️ **一处顺带的行为变更（需用户知悉）**：原 `_cleanup()` 里 `_run_weekly_cleanup_once()` 是**裸调**，
> **没有 try/except** —— 一旦抛异常，这个 daemon 线程直接死掉，**每周清理从此永久失效且无人知晓**
> （另两个调度循环都有「出错 sleep 60 重试一次」的保护，唯独它没有）。
> 本次改写时补上 try/except + `_mark_task_run(..., ok=False)`：失败不再杀线程，且界面上能看到失败。
> 这不是重构等价改写，是**新增的健壮性**；除此之外清理逻辑一行不动。

### 5.4 并发安全

配置读取是「每 tick 读一次数据库」，无需锁：写侧是单条 `INSERT OR REPLACE`，读到旧值最多多跑一轮。

## 6. 接口

### 6.1 新增：读取配置

```
GET /api/admin/scheduler/config
→ { "success": true,
    "tasks": [
      {"key":"gg_delist",  "name":"掉包检测",   "platform":"gg", "kind":"interval", "value":60, "min":10, "max":1440,
       "last_run": {"ts":"2026-10-07 12:00:03","ok":true}},
      {"key":"tt_delist",  "name":"TT 掉包检测","platform":"tt", "kind":"interval", "value":30, "min":10, "max":1440,
       "last_run": {"ts":"2026-10-07 12:30:01","ok":false}},
      {"key":"cleanup",    "name":"每周清理",   "platform":"gg", "kind":"weekly",   "weekday":6, "hour":0,
       "last_run": null}
    ] }
```

- **只返回该用户有权管理的任务**（FB 管理员拿到空数组 → 前端渲染空态）。**不能只靠前端过滤**，否则 F12 就能看到越权任务。
- `last_run` 为 `null` 表示**从未执行过**（不是「执行失败」）—— 前端要能区分这两种情况。
- `last_run` 从 `scheduler_last_run_{task_key}` 逐 key 读回（一个任务一个 key，见 §4.1），与本接口的写入路径**互不相干**。

### 6.2 新增：修改配置

```
PUT /api/admin/scheduler/config
body: {"gg_delist_minutes": 120}        或   {"cleanup_weekday": 3, "cleanup_hour": 8}
→ { "success": true, "config": {...更新后的全量...} }
```

- **只接受当前用户有权管理的字段**；body 里出现越权字段（如 TT 管理员传 `gg_delist_minutes`）→ **403**，不做「静默忽略」。
- 校验失败 → 400，错误信息指明字段与合法区间。
- 返回全量配置（前端直接回填）。

### 6.3 已存在的三个 trigger 接口（改造，不新增）

| 接口 | 改动 |
|---|---|
| `POST /api/admin/trigger-delist-check` | `role != "developer"` 手写判断 → `@scheduler_required("gg")`；执行前后加 `_mark_task_run("gg_delist", ok=...)` |
| `POST /api/admin/trigger-tt-delist-check` | 同上，`@scheduler_required("tt")` / `"tt_delist"` |
| `POST /api/admin/trigger-weekly-cleanup` | 同上，`@scheduler_required("gg")` / `"cleanup"` |

三个接口原结构一致（`try: 执行 → success=True` / `except: 500`），`ok` 直接取哪条分支即可。

## 7. 前端改动

### 7.1 侧边栏（`AppSidebar.vue`）

三份 nav（gg/fb/tt）里的定时任务项**去掉 `developer: true`**。父级 `admin: true` 已经把它限制在管理员组内，户管用独立 nav 天然看不到 —— **不需要新标记**。

### 7.2 路由（`router/index.js:87`）

`meta: { developer: true }` → `meta: { admin: true }`。户管白名单不含此路径，自动被挡。

### 7.3 页面（`SchedulerView.vue`）

- 顶部说明文案：「仅开发者可见」→「管理本平台的定时任务」。
- **按平台过滤卡片**：只渲染 `tasks` 里返回的任务（数据驱动，不再硬编码三张卡）。
- 每张卡片的结构改为：

  | 区域 | 内容 |
  |---|---|
  | 标题 | 任务名（`name`） |
  | 频率 | 「自动频率」+ 可编辑控件（见下） |
  | **上次执行** | `last_run.ts`；`ok === false` 时标红加「失败」；`last_run === null` 显示「尚未执行」 |
  | 操作 | 「立即执行」按钮（沿用现有四态结果展示）+「保存」按钮 |

- 频率编辑控件按 `kind` 分派：
  - `kind: 'interval'` → 数字输入 + 「分钟」（`min`/`max` 用接口返回值，不写死）
  - `kind: 'weekly'` → 星期几下拉 + 小时下拉
  - 「保存」按钮仅在**有改动时**可点
- **FB 管理员**：`tasks` 为空 → 显示空态（「当前平台暂无可管理的定时任务」）。
- 保存成功后提示「已保存，将在 30 秒内生效」。
- 现有「四态结果展示」（有掉包红 / 未判定琥珀 / 全正常绿 / 无包可检）**原样保留**，不因本次改造丢失。

> **「立即执行」不刷新 `last_run` 的显示问题**：手动执行后本页的 `last_run` 会过期（值是接口拉的）。
> 前端在手动执行成功后**重新拉一次 config**（或本地按当前时刻与执行结果就地更新），避免显示陈旧时间。

> **视觉设计**：本项新增了配置交互控件，按项目规则先走 `/frontend-design`。

### 7.4 API 模块（`api/admin.js`）

新增 `getSchedulerConfig()` / `updateSchedulerConfig(payload)`。

## 8. 涉及文件

| 文件 | 改动 |
|---|---|
| `py/routes/decorators.py` | 新增 `scheduler_required(platform)` |
| `py/main.py` | 三个 trigger 换装饰器 + 记 `last_run`；`_start_*` 三个调度函数改造；新增 2 个 config 接口 + `_get_scheduler_config` / `_mark_task_run` 等 helper |
| `py/tests/test_scheduler_config.py` | **新增**：权限矩阵、校验、默认值回落、清理时刻计算、`last_run` 读写 |
| `frontend/src/views/SchedulerView.vue` | 主改动（数据驱动 + 周期编辑） |
| `frontend/src/api/admin.js` | 新增 2 个方法 |
| `frontend/src/components/AppSidebar.vue` | 三处去掉 `developer: true` |
| `frontend/src/router/index.js` | `meta.developer` → `meta.admin` |
| `AGENTS.md` | 补 `trigger-tt-delist-check`；登记本次改动 |

## 9. 边界与风险

1. **配置是全局单例**：同一平台多个 admin 改会互相覆盖（后台任务本身只有一个）。UI 上要能看到「当前值」以免误判。
2. **下限 10 分钟**是硬闸：更短的周期会让 Google Play 与代理池承受不住（现行的 `_TIMEOUT=5` + 代理池只有 2 个代理）。绕过下限的路径必须被 400 堵死。
3. **改周期不打断正在跑的那一轮**：本轮跑完，下一轮才按新周期。这是刻意的（不想中断掉包检测）。
4. **改动不触及 `_run_*_once` 本体**：只改「什么时候调它」，检测逻辑一行不动。
5. **FB 的空数组不能等于「无权限」**：FB 管理员是**有权进入页面**、只是没有任务 —— 与 403 是两回事，前端要能区分（`tasks: []` 渲染空态，接口 403 才是没权限）。
6. **`last_run` 与配置分开存**（§4.1）就是为了避开写竞争。若将来有人图省事把两者并进同一个 key，管理员的「保存」与任务的「跑完」会互相覆盖 —— 届时要自己补 read-modify-write 的原子性。
7. **补文档缺口是一并做的**：AGENTS.md「定时任务（仅 developer）」表要补 `trigger-tt-delist-check`，且整节的「仅 developer」表述随本次改动失效，需一并改（含接口表标题、SchedulerView 在项目结构里的注释「（developer）」）。

## 10. 已确认事项（2026-10-07）

| # | 事项 | 结论 |
|---|---|---|
| 1 | 间隔上限 | **1440 分钟（24 小时）** —— 用户确认 |
| 2 | 是否显示「上次执行时间」 | **要显示** —— 用户确认，已纳入 §4.1 / §6.1 / §7.3 |
| 3 | FB 空态文案 | 「当前平台暂无可管理的定时任务」 —— 用户确认 |
