# 定时任务功能：审查发现清单（**已全部处理**）

> 日期：2026-10-07（初版登记）｜2026-10-07 收口
> 对应功能：定时任务权限下放 + 周期可配置
> 计划：`2026-10-07-scheduler-admin-access-and-interval-config.md`
> **来源**：8 个任务的逐任务审查 + 一次 opus 整支最终审查

**本文档现在是一份结项记录**：初版登记了 23 条发现（用户要求「把这些都修复」），
其中 **19 条可修的已全部修完**，**4 条经审查判定「不是问题」**（见第三节）。
每条都附**处置**与**提交**，供追溯。

建它的原因（保留，作为流程教训）：这些发现此前只散落在两处不持久的地方 ——
gitignored 的 SDD 账本（21 条）与一次对话回复里的 triage（**从未落盘，关会话即失**）。
**评审结论必须落盘**，否则无从跟办。

---

## 一、守护硬闸的两条（初版标「建议排期」）

这两条不是「代码有错」而是**缺少守护**：它们保护的正是「防 500」与「防静默改错周期」两道闸。

| # | 位置 | 缺什么 | 处置 | 提交 |
|---|------|--------|------|------|
| 1 | `py/tests/test_scheduler_config.py` | `isinstance(body, dict)` 守卫无回归用例 —— 全库 PUT 用例都只发 dict body，删掉守卫时无测试会红 | 补用例：truthy 的非对象（`123`/`"abc"`/`[1]`）断言 **400 而非 500** | `b94404c` |
| 2 | 同上 | **布尔字段拒绝**无用例 | 补用例（见下方**勘误**） | `b94404c` |

### ⚠️ 勘误：初版第 2 条的**技术论断是错的**

初版写「`{"gg_delist_minutes": true}` 会静默把周期变成 1 分钟」。**这是错的**，实现时推演才发现：

- `True == 1` 而 `1 < 10`（下限）⇒ **范围校验本来就拦住它**，`not isinstance(val, bool)` 在这条上不起作用。
- 真正靠 `not isinstance(val, bool)` 才拦住的是 **`cleanup_weekday` / `cleanup_hour`** ——
  它们的合法区间是 `0..6` / `0..23`，`True == 1` **正好落在区间内** ⇒
  少了这一句，`{"cleanup_weekday": true}` 会**静默变成「周一」**。

用例的判别腿据此放在 weekday/hour，并在 docstring 写明「哪个字段靠哪道闸拦」。
**教训**：写评审结论时**必须实际推演数值**，不能靠「`True == 1` 所以危险」这种直觉下判断 ——
危险与否取决于该字段的**合法区间**与 `1` 的位置关系。

---

## 二、其余可延后项（17 条）

| # | 出处 | 内容 | 处置 | 提交 |
|---|------|------|------|------|
| 3 | T1 | 探针路由**永久挂在共享 `main.app` 上、无 teardown** | 加契约注释（点明将来枚举 POST 路由/断言路由总数的测试会看到 `/api/_probe/*`） | `b94404c` |
| 4 | T1 | 装饰器两个 401 分支（`未认证`/`用户不存在`）经探针不可达 | 补中文注释说明是外层 `@jwt_required()` 之外的兜底；`未认证` 分支用**直接调用绕过 Flask 栈**的低成本用例钉住 | `c64b0bf` |
| 5 | T2 | `TestIntervalTick` 以 `main._TICK_SECONDS` 自引用，字面值 30 未钉住 | 加 `assert main._TICK_SECONDS == 30` 并注明它是「配置变更生效粒度」的契约值 | `b94404c` |
| 6 | T2 | 边界值未钉住（`10`/`1440` 接受、`1441` 拒绝、hour `0`/`23`、weekday `0`/`6`） | 全部补齐（「把 `<=` 翻成 `<` 就会红」的守护） | `b94404c` |
| 7 | T2 | 非法存量值被静默丢弃、无 log | 拒绝时加 `log.warning`（**只在值确实非法时**打，避免每 30 秒热路径刷屏） | `b94404c` |
| 8 | T3 | `_interval_loop` 的 `default_minutes` 是**死参**（`_get_scheduler_config` 恒从默认表播种） | 选**去掉死参**：`_interval_loop` 与 `_get_scheduler_int` 均删 `default` 形参，默认值唯一来源留在 `_SCHEDULER_DEFAULTS`（GG 60 / TT 30 未变） | `c64b0bf` |
| 9 | T3 | 测试注释「第 3 次 sleep 抛哨兵」与 `_FakeTime(stop_after=1)` 实际（第 2 次）不符 | 改注释 | `b94404c` |
| 10 | T3 | `_capture_thread` 直接 patch `threading` **模块级全局** `Thread` | 收窄到只 patch `main` 上的引用 | `b94404c` |
| 11 | T3 | 「周期改小 → 下一 tick 立即生效」缺 `_interval_loop` 层端到端用例 | 补用例（**在循环运行中途改配置值**，否则与既有 `test_recomputes_target_each_tick` 重复）；另做隔离变异证明其不重复 | `b94404c` |
| 12 | T5 | `json=0/false/""/[]` 落到「请求体为空」而非「必须是 JSON 对象」 | 统一：**非对象**（含 falsy）一律报「必须是 JSON 对象」；真正的空体与空对象 `{}` 行为**原样保留** | `c64b0bf` |
| 13 | T6 | `router/index.js` 的 `meta.developer` 守卫**已成死代码** | 删掉（删前 grep 确认全库无路由再设该 meta；`isDeveloper` getter 保留） | `1cb9777` |
| 14 | T7 | `saving` 是单个全局 ref ⇒ 任一卡保存点亮**所有**卡 | 改 `savingKey`，只点亮正在保存那张卡；`:disabled="!dirty(task)"` 语义未变 | `1cb9777` |
| 15 | T7 | `saveTask` 忽略 PUT 响应的 `config`、改走 `loadConfig()` 重拉 | 改为**用响应 `config` 就地回填**。**保存周期不触发执行**（`_mark_task_run` 仅在真跑完后调用），故 `last_run` 保持原值即最新、不陈旧 —— 代码注释已写明该依据 | `1cb9777` |
| 16 | T7 | 加载失败时页面除标题外**空白**（只有瞬时 `ElMessage`，无出路） | 加**持久错误态 + 「重试」按钮**，**复用既有 `.scheduler-empty` 结构**做 `v-else-if` 分支（无新样式/token） | `1cb9777` |
| 17 | T7 | weekly payload **硬编码** `cleanup_weekday`/`cleanup_hour`，与上方注释矛盾 | 选**前端方案**（字段名收进 `TASK_META`）—— 后端 weekly 不分回传 `field`，改后端会牵动 Task 5 已验收的接口契约；旧注释已改得不自相矛盾 | `1cb9777` |
| 18 | T8 | `AGENTS.md` 两处「本平台」对 **developer 不准确**（developer 实际拿到全部三项） | 改准措辞（admin 限本平台；developer 全部） | `c64b0bf` |
| 19 | T8 | 权限归属段未覆盖 GET/PUT 差异（GET **刻意不用** `scheduler_required`，好让 FB 管理员拿空列表而非 403） | 补半句点明「空数组 ≠ 无权限」，消除与同段的自相矛盾 | `c64b0bf` |

---

## 三、判定「不是问题」的 4 条（**未改，附理由**）

| # | 出处 | 内容 | 为何不改 |
|---|------|------|---------|
| 20 | T1 | 「`import json` / `import database` 未使用」 | **该 finding 不成立** —— 最终审查核实：测试文件里 `json.dumps`、`database.config_set` 被大量使用，两个 import 都在用 |
| 21 | T4 | 既有三条权限用例已被新矩阵**完全包含**（冗余） | 冗余但无害，删不删不影响交付 |
| 22 | T4 | 矩阵无 developer/huguan 腿 | 由 `test_developer_passes_all_real_endpoints` 与 `test_huguan_blocked_everywhere` 覆盖，**非缺口** |
| 23 | T5 | `json=0/false/""/[]` 的文案差异 | 与 #12 同源；#12 已统一文案，本条随之消解 |

---

## 附表：更早一轮已处理的重要发现（供追溯）

| 出处 | 内容 | 处置 |
|------|------|------|
| 最终审查 **Important** | `_mark_task_run` 对 `scheduler_last_run` **单 key** 做 RMW，6 个写者会丢更新；**设计 §4.1 只考虑了「配置 vs 运行事实」那一组，漏了 last_run 自己的多写者** | `8cf1909` 先加锁 → `e8f4329` 按用户裁定**改为一任务一 key**，结构性根除（无共享状态即无需锁） |
| 最终审查 Minor | `_interval_loop` docstring 与代码矛盾（写「两次执行之间采纳」，实际**每 tick 重算**） | `8cf1909` 订正 |
| 最终审查 Minor | 前端 `gg_delist` 的「启动时立即执行一次」tag 与事实不符（该代码本就是注释掉的） | `8cf1909` 移除 |
| T4 待办 | `py/main.py` 分区注释「仅 developer 可调用」已过时 | `4d46d70` 改为「按平台的管理员 / developer」 |
| T5 **Important** | `test_update_does_not_clobber_last_run` 非判别性（RED 阶段就绿、且「PUT 没生效」也通过） | `b3d142b` 补正向对照（断言读**库里的值**而非响应回显，故「返回 200 但不落库」也会红） |
| T4 **Important** | 覆盖缺口：weekly 无 admin 用例、tt 只被「≠gg」钉死 | `bbcbd8d` 补表驱动 3×3 双向矩阵 |
| T1 计划缺陷 | brief 的 `probe_client` 夹具在 Flask 3 下跑不通（实测 1 passed / 5 errors） | 实现时改为模块级注册探针路由，用例体与断言逐字未改（计划文档已加勘误） |
| T5 计划缺陷 | `json=123` 之类的非对象 body 会 500 | `b3d142b` 加 `isinstance(body, dict)` 守卫 → 400 |

---

## 四、与本功能无关、但仍在的两件事

1. **全量套件有 1 条红**：`py/tests/test_huguan_undo.py::TestDeleteUserCleanup::test_undo_table_is_in_delete_user_cleanup_list`
   —— **单独跑通过**、该文件**零处引用本功能**，属跨文件测试污染（该文件当时正被另一会话编辑）。
   控制器 2026-10-07 独立复核确认与本功能无关。**未修**（不属本功能范围）。
2. **人工验收未做**：浏览器里的菜单可见性、周期编辑控件、平台空态、错误态重试、
   单卡 loading、「上次执行」显示，均需**真实登录**核验。
   清单见各任务报告（`groupA/B/C-report.md` 及各 task 报告）。

## 五、验证状态

| 项 | 结果 |
|---|---|
| `py/tests/test_scheduler_config.py` | 57 → **69 passed**（三组共新增 12 条用例，含 1 条参数化展开） |
| `test_scheduler_config + test_decorators + test_anon_surface` | **76 passed / 0 failed** |
| 前端 `npm run build` | ✓ 通过（三组各跑一次） |
