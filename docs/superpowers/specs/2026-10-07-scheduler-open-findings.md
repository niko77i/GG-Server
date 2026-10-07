# 定时任务功能：审查发现清单（含三态裁定）

> 日期：2026-10-07
> 对应功能：定时任务权限下放 + 周期可配置
> 计划：`2026-10-07-scheduler-admin-access-and-interval-config.md`
> **来源**：8 个任务的逐任务审查 + 一次 opus 整支最终审查

本文档**只登记未处理项**，不重复已修的东西（已修项列在文末附表，供追溯）。
建它的原因：这些发现此前只散落在 gitignored 的 SDD 账本与一次对话回复里，
其中「最终审查的三态裁定」**从未落盘** —— 关掉会话即失，无从跟办。

## 一、建议排期（守护硬闸的两条）

这两条不是「代码有错」，而是**缺少守护**：它们保护的正是「防 500」与「防静默改错周期」两道闸，
将来有人图省事删掉那几行守卫时，**没有任何测试会红**。

| # | 位置 | 缺什么 | 为什么值得排 |
|---|------|--------|-------------|
| 1 | `py/tests/test_scheduler_config.py`（PUT 相关用例旁） | **`isinstance(body, dict)` 守卫没有回归用例** —— 全库 PUT 用例都只发 dict body | 该守卫拦的是「非对象 JSON 标量（如 `123`）触发 `set(123)` → 500」。删掉它，全套测试仍绿 |
| 2 | 同上（`_get_scheduler_config` 相关用例旁） | **布尔字段拒绝没有用例** —— `not isinstance(val, bool)` 那一句是唯一拦住 `{"gg_delist_minutes": true}` 的东西 | Python 里 `True == 1`，少了这一句，`true` 会通过 `10 <= val <= 1440`，**静默把周期变成 1 分钟** |

两条都是一次 PUT + 一条断言的小活。

## 二、可延后（不影响正确性，属测试强度 / 可观测性 / 一致性）

| # | 出处 | 内容 | 位置 |
|---|------|------|------|
| 3 | T1 | 探针路由**永久挂在共享 `main.app` 上、无 teardown** —— 今日无害（已核实唯一枚举路由的测试只看 GET 且用下限），但将来若有人写枚举 POST 路由或断言路由总数的测试会踩雷 | `py/tests/test_scheduler_config.py` 顶部 |
| 4 | T1 | 装饰器的两个 401 分支（`未认证` / `用户不存在`）经探针**不可达**（`@jwt_required()` 在外层先拦），无用例覆盖 | `py/routes/decorators.py` |
| 5 | T2 | `TestIntervalTick` 三条用例以 `main._TICK_SECONDS` **自引用** —— 不削弱 `_interval_tick` 本体的判别力，但**字面值 30 未被独立钉住** | `py/tests/test_scheduler_config.py` |
| 6 | T2 | **边界值未钉住**：`10` / `1440` 应接受、`1441` 应拒绝、`cleanup_hour` 0/23、`cleanup_weekday` 0/6 —— 低侧只测了 `3`。把 `<=` 翻成 `<` 不会有测试红 | `py/main.py` 的 `_get_scheduler_config` 校验段 |
| 7 | T2 | **非法存量值被静默丢弃、无 log** —— 有人手工改库写越界值，会悄悄回落到默认，无任何可观测痕迹 | 同上 |
| 8 | T3 | `_interval_loop` 的 `default_minutes` 形参**实为死参** —— `_get_scheduler_config()` 恒从 `_SCHEDULER_DEFAULTS` 播种，形参永不生效。当前两处调用与默认表同值无碍，日后分叉会**静默**以默认表为准 | `py/main.py` |
| 9 | T3 | 测试注释「第 3 次 sleep 抛哨兵」与 `_FakeTime(stop_after=1)` 的**实际行为（第 2 次）**不符 | `py/tests/test_scheduler_config.py` |
| 10 | T3 | `_capture_thread` **直接 patch `threading` 模块的全局 `Thread`** —— 当前单线程用例无害，将来同进程跑并发用例会踩雷 | 同上 |
| 11 | T3 | **「周期改小 → 下一 tick 立即生效」缺 `_interval_loop` 层的端到端用例**（纯函数层已验 + `test_recomputes_target_each_tick` 覆盖机制，两层组合足以推出结论） | 同上 |
| 12 | T5 | `json=0 / false / "" / []` 会落到既有的「请求体为空」文案，而非「必须是 JSON 对象」（**都是 400**，仅文案差异） | `py/main.py` PUT 路由 |
| 13 | T6 | `router/index.js` 的 `if (to.meta.developer && !auth.isDeveloper)` 守卫**已成死代码**（全库已无路由再设 `meta.developer`） | `frontend/src/router/index.js` |
| 14 | T7 | `saving` 是**单个全局 ref** —— 任一卡保存会点亮**所有**卡的保存按钮 loading（brief 如此规定） | `frontend/src/views/SchedulerView.vue` |
| 15 | T7 | `saveTask` **忽略 PUT 响应的 `config`**、改走 `loadConfig()` 重拉 —— 行为等价，多一次往返；设计 §5 原话是「回填接口返回的全量配置」 | 同上 |
| 16 | T7 | **加载失败时页面除标题外空白**（只有瞬时 `ElMessage`，无重试入口）。`loadError` 已防住「空态误显」，但没有下一步可做 | 同上 |
| 17 | T7 | weekly 的 payload **硬编码** `cleanup_weekday` / `cleanup_hour`，与其上方注释倡导的「不硬编码字段名」不一致（weekly 只有一个任务，当前无害） | 同上 |
| 18 | T8 | `AGENTS.md` 两处「本平台」对 **developer 不准确** —— developer 实际拿到**全部三项**而非本平台 | `AGENTS.md` |
| 19 | T8 | 权限归属段**未覆盖 GET/PUT 的差异** —— GET 是**刻意不用** `scheduler_required(platform)`，好让 FB 管理员拿到空列表而非 403。补半句可免读成自相矛盾 | 同上 |

## 三、无需处理（审查已判定不是问题）

| # | 出处 | 内容 | 为何不处理 |
|---|------|------|-----------|
| 20 | T1 | 「`import json` / `import database` 未使用」 | **该 finding 不成立** —— 最终审查核实：测试文件里 `json.dumps`、`database.config_set` 被大量使用，两个 import 都在用 |
| 21 | T4 | 既有三条权限用例已被新矩阵**完全包含**（冗余） | 冗余但无害，删不删不影响交付 |
| 22 | T4 | 矩阵无 developer/huguan 腿 | 由 `test_developer_passes_all_real_endpoints` 与 `test_huguan_blocked_everywhere` 覆盖，**非缺口** |
| 23 | T5 | `json=0/false/""/[]` 的文案差异 | 与 #12 同源，都是 400，仅措辞 |

## 附表：本次已处理的发现（供追溯）

| 出处 | 内容 | 处置 |
|------|------|------|
| 最终审查 Important | `_mark_task_run` 对 `scheduler_last_run` 单 key 做 RMW，6 个写者会丢更新 | `8cf1909` 先加锁 → `e8f4329` 按用户裁定**改为一任务一 key**，结构性根除（无共享状态即无需锁） |
| 最终审查 Minor | `_interval_loop` 的 docstring 与代码矛盾（写「两次执行之间采纳」，实际每 tick 重算） | `8cf1909` 订正 |
| 最终审查 Minor | 前端 `gg_delist` 的「启动时立即执行一次」tag 与事实不符（该代码本就是注释掉的） | `8cf1909` 移除 |
| T4 待办 | `py/main.py` 分区注释「仅 developer 可调用」已过时 | `4d46d70` 改为「按平台的管理员 / developer」 |
| T5 Important | `test_update_does_not_clobber_last_run` 非判别性（RED 阶段就绿） | `b3d142b` 补正向对照（断言读库里的值而非响应回显） |
| T4 Important | 覆盖缺口：weekly 无 admin 用例、tt 只被「≠gg」钉死 | `bbcbd8d` 补表驱动 3×3 双向矩阵 |
| T1 计划缺陷 | brief 的 `probe_client` 夹具在 Flask 3 下跑不通（实测 1 passed / 5 errors） | 实现时改为模块级注册探针路由，用例体与断言逐字未改（计划文档已加勘误） |
| T5 计划缺陷 | PUT 无 `remark`… 类同型：`json=123` 会 500 | `b3d142b` 加 `isinstance(body, dict)` 守卫 → 400 |

## 与本功能无关但仍在的两件事

1. **全量套件有 1 条红**：`py/tests/test_huguan_undo.py::TestDeleteUserCleanup::test_undo_table_is_in_delete_user_cleanup_list`
   —— **单独跑通过**、该文件**零处引用本功能**，属跨文件测试污染。控制器 2026-10-07 复核确认与本功能无关。
2. **人工验收未做**：浏览器里的菜单可见性、周期编辑控件、平台空态、「上次执行」显示，
   均需真实登录核验（详见计划文档与各任务报告）。
