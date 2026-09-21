# TT 回收户清单写入 — 只写 3 列、保护公式、非存活即触发 设计文档

> 日期：2026-09-22
> 状态：待确认

## 1. 需求描述

TT 账户页面把状态更新为**非「存活」**时，自动写 Google 表「回收户清单」。表头 12 列：

| 列 | A | B | C | D | E | F | G | H | I | J | K | L |
|----|---|---|---|---|---|---|---|---|---|---|---|---|
| 表头 | 时间 | 账户ID | 渠道 | 运营 | 国家 | 时区 | 有无消耗 | 回收原因 | 是否提交 | 清零金额 | 备注 | 是否二次提交 |

要求：
1. **时间**：当天日期，格式 `年-月-日`（YYYY-MM-DD）。
2. **只写 3 列**：时间(A)、账户ID(B)、回收原因(H)。
3. 其余列（C渠道/D运营/E国家/F时区/G有无消耗/I是否提交/J清零金额/K备注/L是否二次提交）**均有公式，写入时不得覆盖/清空**。
4. 回收原因：弹窗下拉框，用户从系统已有原因中选择，**可输入搜索**；若系统没有该原因，**自动新增到系统**。

## 2. 现状与问题

已有实现链路（已提交）：
`TtAccountPanel.vue 状态改「封禁/死亡」→ 弹 TtRecycleReasonModal 选原因 → update/batchUpdate 带 recycle_reason → 后端 _trigger_recycle_if_dead → _maybe_write_recycle → gs.append_recycle 后台异步写表`

现状问题（与需求不符）：

1. **清公式**：[append_recycle](py/google_sheets_service.py#L412-L427) 现在写 C渠道(agent)/D运营(operator)/E国家(country)/F时区(timezone) 实际值，且 G/I/J/K/L 写空串 —— 会清掉这些列的公式。
2. **触发范围窄**：仅「封禁/死亡」触发；需求是「所有非存活」。
3. 账户 ID 未强制文本：纯数字长 ID 经 `USER_ENTERED` 可能被解析成数值、丢失精度（与 C-L 公式按 B 列匹配会失败）。

## 3. 技术方案

### 3.1 `append_recycle`（py/google_sheets_service.py）

- 读 `A:B` 两列找最后一行（C-L 可能是公式，不作为「最后行」判定依据）。
- 只写 A/B/H 三列，用 `values().batchUpdate` 一次写 3 个 range：
  - `A{start}:A{end}` = 时间
  - `B{start}:B{end}` = 账户ID（前置 `'` 强制文本，对齐 `upsert_fb_reports` 写法）
  - `H{start}:H{end}` = 回收原因
- 行数不足时照旧 `appendDimension` 扩容。

### 3.2 `_maybe_write_recycle` / `_trigger_recycle_if_dead`（py/routes/tt_accounts_routes.py）

- `_maybe_write_recycle` 的 rows 只保留 `time / account_id / reason`，移除 `agent/operator/country/timezone`。
- `_trigger_recycle_if_dead` 不再查 `agent/country/timezone`；触发条件由 `in ("封禁","死亡")` 改为 **`!= "存活"`**（即所有非存活状态都触发）。

### 3.3 触发范围（前端）

- [TtAccountPanel.vue](frontend/src/views/tt/TtAccountPanel.vue#L578-L582) `saveStatus`：由 `stName === '封禁' || stName === '死亡'` 改为 **`stName !== '存活'`**。
- `doBatchStatus`（批量改状态）同步改为 `stName !== '存活'`。

> 说明：`death_date`（死亡日期）字段仍只在「死亡」时写入，与回收触发解耦，本需求不改。

## 4. 列映射（写入）

| 列 | 值 |
|----|-----|
| A 时间 | `datetime.now().strftime("%Y-%m-%d")` |
| B 账户ID | `advertiser_id`（文本，前置 `'`） |
| H 回收原因 | 用户选择的 `reason` |
| C/D/E/F/G/I/J/K/L | 不写（保留公式） |

## 5. 涉及文件

- 后端：`py/google_sheets_service.py`（append_recycle）
- 后端：`py/routes/tt_accounts_routes.py`（_maybe_write_recycle、_trigger_recycle_if_dead）
- 前端：`frontend/src/views/tt/TtAccountPanel.vue`（saveStatus、doBatchStatus 触发条件）
- 测试：`py/tests/test_tt_accounts.py`（补非存活触发、append_recycle 只写 3 列）

## 6. 边界与约束

- 后台异步写表失败不阻塞状态变更（维持现状）。
- reason 为空不触发（前端弹窗已强制必填）。
- 回收原因 CRUD 与自动新增逻辑不变。
- 「存活」状态不写回收清单（含状态从非存活改回存活）。
- 纯增量：不改动同步、充值、消耗冲突等既有逻辑。
