# 写表失败统一治理（二期：GG 平台接入）设计

> **日期**: 2026-10-07
> **状态**: 待用户确认
> **前置**: 一期 `docs/superpowers/specs/2026-10-06-sheet-write-failure-governance-design.md`（基建 + TT 回收清单）
> **分支**: `feat/sheet-write-gg`（worktree）

---

## 1. 需求与背景

一期已交付统一机制：`py/sheet_write.py` 的 `run_write` 编排 + `sheet_write_log` 表 + `/api/sheet-write/*` 两个接口 + 条件回滚；并把 **TT 回收户清单**接入。

一期普查时发现全仓 21 个写表点里 **9 个是静默失败**（1 个连日志都没有）。TT 那个已收口；**GG 侧还有多个点未接**。二期目标：把 GG 平台的写表点接进同一套机制。

用户对本期的范围裁定（2026-10-07）：**B —— 接 5 个静默的「我的看板」点 + 4 个充值写表点；做表数据（`upsert_zuobiao`）不接**（它已有完整三分支 `sheets_sync_log` + `retry-sync`，工作正常，迁移收益低而风险不低）。

---

## 2. 现状（二期勘察结论，运行时代码为准）

GG 侧共 10 个 `_sync_sheets_background` 调用点，按失败行为分三档：

| 失败行为 | 点数 | 点位（`py/main.py`） |
|---|---|---|
| **(b) 只写日志**，无前端、无重试 | **5** | 4784 状态列 / 4955 解绑 / 5027 恢复 / 5256 批量状态 / 5531 sync 回写 |
| (c) 持久化 `recharge_records.sheets_synced/sheets_error` | 4 | 4762 清账 / 5233 批量清账 / 5697 单笔充值 / 5796 批量充值 |
| (c) 持久化 `sheets_sync_log` | 1 | 7548 做表数据（**本期不接**） |

无完全静默点、无同步返错点。

### 2.1 查出的一处语义冲突

4 个充值点的 `_on_fail`（4753 / 5222 / 5685 / 5784）**只有两分支**：

```python
if status == "synced":   # UPDATE recharge_records SET sheets_synced=1, sheets_error=''
else:                    # UPDATE recharge_records SET sheets_error=err_msg
```

`failed`（首次失败、30s 重试在途）与 `retry_failed` 落进同一个 `else` ⇒ **首次失败就把 `sheets_error` 写上**，前端 `AccountDetailModal.vue:56-63` 立刻显示 ⚠️。

这与用户在一期的裁定直接冲突：「提示**只在最终结果产生时**发出 —— `failed` 不得触发任何用户可见提示」。二期接统一机制后自然修正。

### 2.2 关键结论：GG 侧 **零回滚**

GG 侧 **10 个点全部是「主数据镜像」，无一属于「主数据延伸」**。理由一致：每个写表动作之前，对应业务事实**都已先落库** ——

| 写表内容 | 已落库的源 |
|---|---|
| 充值表追加行（含「清」） | `recharge_records` 行 |
| 我的看板 F 列（状态） | `accounts.status_id` |
| 我的看板 H 列（解绑/清空） | `accounts.deleted_at` |
| 做表数据 A–N | `ad_reports` 行 |

最有力的反证：做表数据的 `POST /api/google-sheets/retry-sync`（`main.py:7590`）正是**从 `ad_reports` 重建待写行** —— 证明 DB 是源、表是副本。

⇒ 按一期口径，GG 侧目标**一律不注册 `rollback`**，最终失败落 `retry_failed`。**这比一期简单**（一期 TT 回收清单是唯一有回滚的场景）。

---

## 3. 目标行为

1. 上述 9 个点（5 静默 + 4 充值）的**最终失败**产生持久记录（含原因），操作者可查、可重试
2. 提示**只在最终结果产生时**发出 —— 修掉充值点现行的「首次失败就报警」
3. 前端能看见：账户行标记（看板）/ 充值记录 tooltip（充值）
4. **不做业务回滚**（§2.2）
5. 充值写表从 `recharge_records.sheets_synced/sheets_error` **收敛到** `sheet_write_log`，全仓一套机制

---

## 4. 架构：加法式扩展「批量多键」

### 4.1 问题

`_sync_batch_dashboard`（5256）与 `_sync_back_to_dashboard`（5531）是「**一个后台任务写 N 个账户**」：单线程内循环调 `update_cell_by_account_id`。

而一期的 `run_write(db, ..., business_key=..., sync_fn=...)` 是「一个任务一个 business_key」，对应**一行**日志。

逐账户调用 `run_write` 会变成 **N 个后台线程 + N 次并行 Sheets API 突发**（原实现是一个线程串行 N 次调用）；被取消的还要各自睡 30s 重试。而若只登记一行日志（用批次键），**行内标记就失去按账户定位的能力** —— 那正是这个设计存在的意义。

### 4.2 方案：新增 `run_write_many`（`run_write` 不动）

```python
def run_write_many(db, *, user_id, platform, target, business_keys,
                   sync_fn, payload=None, snapshot=None) -> None:
    """一次后台写表，登记 N 行日志（每个 business_key 一行），结果统一落。

    与 run_write 的唯一区别：日志是 N 行、业务键是 N 个，而**后台线程仍只有一个**。
    用于「一次操作影响 N 个账户」的场景（批量改状态、sync-from-sheet 回写），
    避免 N 个线程 + N 次并行 API 突发，同时保住「行标记按账户定位」。
    """
```

- 逐键 `record_pending`（同一请求连接，一次 commit）
- 起**一个** `_sync_sheets_background`
- 结果回调按同一个 status 落到全部 N 行
- `_inflight` 登记 **N 个 key**（与 §一期 的 sweep 保护一致）

`run_write` 保持原签名不变 —— **纯增量**，一期已审代码零改动。

### 4.3 两个 target

| target | business_key | rebuild 从哪重建 | 回滚 |
|---|---|---|---|
| `gg_my_dashboard` | `account_id`（`accounts.id`） | 读 `accounts` 行 → F 列写状态名、H 列写 `"解绑"`/`""`（按 `deleted_at`） | ❌ 镜像 |
| `gg_recharge` | `recharge_records.id` | 读 `recharge_records` 行 → 构造追加行 | ❌ 镜像 |

两者都**从 DB 重建**（与一期同思路），`payload_json` 只存非 DB 派生的小参数（如清账行的 `status`）。

> **为什么 `gg_my_dashboard` 一个 target 就够**：F 列（状态）与 H 列（解绑）都可由 `accounts` 行的当前状态重算 —— 现有 `_sync_back_to_dashboard`（5516）正是「读账户 → 同时写 F 与 H」，重建逻辑与它同构。故一次重试即把该账户的看板行刷到与系统一致，无需区分哪一列失败。

### 4.4 线程与连接约束（沿一期）

`sync_fn` 与 `rollback_fn` 均在后台线程执行：必须在闭包内新建 sqlite 连接与 httplib2 service；调用点**不得**在请求线程预先 `build_service()`。

---

## 5. 改造点清单

### 5.1 五个「我的看板」点（改走 `run_write` / `run_write_many`）

| 现点位 | 触发 | 改造 |
|---|---|---|
| 4784 `_sync_dashboard` | `PUT /api/accounts/<aid>` 状态变更 | `run_write(target="gg_my_dashboard", business_key=aid)` |
| 4955 `_sync_unbind` | `DELETE /api/accounts/<aid>` | 同上 |
| 5027 `_sync_unbind_clear` | `POST /api/accounts/<aid>/restore` | 同上 |
| 5256 `_sync_batch_dashboard` | `POST /api/accounts/batch-update` | `run_write_many(business_keys=[每户 aid])` |
| 5531 `_sync_back_to_dashboard` | `POST /api/accounts/sync-from-sheet`（dry_run=false） | `run_write_many(business_keys=[每户 aid])` |

四个 `_sync_*` 闭包合并为一个 `_gg_dashboard_sync(db, account_ids)` 直写函数（读账户 → 写 F+H），既供首次执行也供重试 —— 与一期 `_tt_recycle_rebuild` 同一形态。

### 5.2 四个充值点（改走 `run_write` / `run_write_many`，退场 `sheets_synced`/`sheets_error`）

| 现点位 | 触发 | business_key |
|---|---|---|
| 4762 `_do_sync`（清账） | `PUT /api/accounts/<aid>` | 该 `recharge_records.id` |
| 5233 `_do_sync`（批量清账） | `POST /api/accounts/batch-update` | 每条 rid |
| 5697 `_do_sync` | `POST /api/recharge/submit` | rid |
| 5796 `_do_sync` | `POST /api/recharge/batch-submit` | 每条 rid |

四个 `_on_fail`（4753/5222/5685/5784）删除 —— 状态由统一机制落 `sheet_write_log`。

**`recharge_records.sheets_synced` / `sheets_error` 列保留不动**（存量兼容，且不重建表），但**不再写入**。前端改读新接口（§6.1）。

### 5.3 `retry-sheets` 的处置

`POST /api/recharge/<int:rid>/retry-sheets`（5883）现在**同步**在请求线程里重放。改造后重试统一走 `POST /api/sheet-write/retry`（异步，走后台线程），该端点**保留但改为内部转调统一入口**，以兼容既有前端调用；或前端直接切到新端点。

**处置决定**：前端切到 `POST /api/sheet-write/retry`（异步、走后台线程，与一期 TT 一致）。
`POST /api/recharge/<int:rid>/retry-sheets` **保留为转调统一入口的薄封装**，不删除 ——

- 它有一个既有的权限守卫用例 `test_recharge_retry_sheets_owner_guard`（`py/tests/test_tt_accounts.py:617`），删除端点会连带废掉该守卫；
- 保留转调的成本极低（几行），且能让任何未刷新的旧前端页面继续可用。

**它的语义随之改变**：由「同步重放并当场返回结果」变为「提交到统一入口后立即返回」。旧前端拿到的 200 不再代表写入成功 —— 这是**有意的**（旧语义正是「同步等 Sheets」那种会阻塞请求的形态）。

---

## 6. 前端

### 6.1 充值记录（`AccountDetailModal.vue`）

现状（`:56-63`）：`row.sheets_synced === 0` → ⚠️ tooltip + 点击重试。

改为：读 `GET /api/sheet-write/status?platform=gg`（不带 business_key，返回该用户全部需提示终态），按 `String(recharge_records.id)` 索引。语义与一期 TT 完全一致：只有 `retry_failed` 才显示标记。

### 6.2 GG 账户表（`AdsAccountPanel.vue`）

新增「写表」列，**逐字复用一期 TT 账户表那套设计**（已确认的视觉方案）：位置紧跟「账户 ID」、`width="54"`、三态语汇（⚠️ warning / ↩️ info / ⛔ danger）+ tooltip 显示原因 + 点击即重试、无记录渲染 ✅。

> 复用而非重设计：一期那套的视觉评审结论（不发明符号、沿用充值记录表「表格」列的既有语汇、三态强度按「操作员要做什么」排）在这里**完全适用**，且两张表并列出现时跨平台一致。

### 6.3 三个提示文案（与一期同源）

沿用一期 `sheetWriteHint()` 的三句，不改。

---

## 7. 测试

| 用例 | 判据 |
|---|---|
| `run_write_many` 登记 N 行 | N 个 business_key 各一行 `pending`，且**只起一个**后台线程 |
| `run_write_many` 结果统一落 | 成功 → N 行 `synced`；最终失败 → N 行 `retry_failed` |
| `_inflight` 登记 N 键 | sweep 对这 N 行全部跳过 |
| `gg_my_dashboard` 重建 | 从 `accounts` 重算 F+H；删除态写「解绑」、非删除态写空 |
| `gg_recharge` 重建 | 从 `recharge_records` 重算追加行 |
| **无回滚** | 两个 target 最终失败落 `retry_failed`（**不是** `rolled_back`/`rollback_abandoned`） |
| 充值点不再首败报警 | 首次失败后 `sheet_write_log.status='failed'`，且该状态**不在** `ATTENTION` 里（列表标记与终态提示都不出） |
| 前端 | 充值 tooltip 与账户行标记都只在 `retry_failed` 出现 |

回归：`test_security_hardening.py`、`test_ad_reports.py`、`test_huguan_dashboard.py`（GG 账户路径相关）。

---

## 8. 不做（二期）

1. **做表数据**（`upsert_zuobiao`）——已有完整三分支 + `retry-sync`，用户裁定不接
2. **业务回滚** —— GG 侧全部镜像类（§2.2）
3. **`recharge_records` 的列清理** —— `sheets_synced`/`sheets_error` 保留但不再写；不重建表
4. **FB 域 3 个点 / 户管看板 4 个点** —— 三、四期
5. **重设计视觉** —— 逐字复用一期已确认方案

---

## 9. 风险与已知代价

1. **充值路径是在工作的路径** —— 迁移会动 `_on_fail`、前端 tooltip 与重试入口。缓解：`recharge_records` 的列保留（可回退读），且改造前后前端行为一致（都是「失败才显示 ⚠️」）。
2. **`run_write_many` 是新契约** —— 但加法式：`run_write` 不动，一期已审代码零改动。
3. **批量点位从「一个线程串行 N 次 API」不变**（`run_write_many` 保持一个线程），只是多了 N 行日志。
4. **前端运行时行为仍需人工验证** —— 与一期同：`npm run build` 只证明能编译。
