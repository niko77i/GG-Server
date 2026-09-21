# TT 同步「是否回收」列驱动状态变更 设计文档

> 日期：2026-09-22
> 状态：待确认

## 1. 需求描述

TT 平台「我的看板」同步时，C 列「是否回收」字段要参与账户状态判定：

| C 列值 | 含义 | 推导状态 |
|--------|------|----------|
| 「可用」 | 户存活 | 存活 |
| 「是」 | 户已回收 | 死亡 |

同步时对比 C 列推导出的状态与系统内该户的状态：

1. **新户（系统里没有）**：直接导入到系统，状态按 C 列推导（「是」→死亡，「可用」→存活）。
2. **已存在 + 状态不一致**：**不自动改**，而是提示用户，由用户手动确认是否变更（与 GG 同步的「封户值判定」一致）。
3. **反向也提示**：C 列=「可用」但系统已是「死亡」，同样提示确认，不自动改回。
4. **不写回收清单**：C 列「是」代表「回收户清单」那边已确认回收（上游），同步只需把该状态反映到系统，**不触发** `_trigger_recycle_if_dead`。

## 2. 技术方案

### 2.1 状态映射

```python
# C 列 = r[2]
sheet_status = "死亡" if (r[2] or "").strip() == "是" else "存活"
```

状态 id 通过现有 `_resolve_status_id(db, name, None)` 获取（按 `platform='tt'` 查/插 `account_statuses`）。

### 2.2 后端 `sync_from_sheet`（py/routes/tt_accounts_routes.py）

- **dry_run 阶段**：遍历行时新增状态比对
  - 新户：`created` 条目新增 `status` 字段（"存活"/"死亡"）。
  - 已存在：对比 `sheet_status` vs 系统 `status_name`（`COALESCE(st.name,'存活')`）
    - 一致 → 走现有 `updated`
    - 不一致 → 新增 `status_conflicts` 列表，条目 `{advertiser_id, sheet_status, system_status}`
  - 返回结构新增 `status_conflicts`。

- **confirm 阶段（dry_run=False）**：
  - 创建新户时，INSERT 新增 `status_id`（按 C 列推导）。
  - 新增处理 `status_resolutions`（用户对状态冲突的选择），更新 `tt_accounts.status_id` 与 `status_changed_date`。
  - 更新状态时**不调用** `_trigger_recycle_if_dead`（不写回收清单）。

### 2.3 状态冲突的确认契约

参照现有「消耗冲突」的 resolutions 模式（dict 按 advertiser_id 传），保持前端契约一致。

## 3. 涉及文件

- 后端：`py/routes/tt_accounts_routes.py` — `sync_from_sheet`
- 前端：`frontend/src/components/tt/TtAccountSyncModal.vue` — 同步弹窗
- 测试：`py/tests/test_tt_accounts.py`

## 4. 数据结构（API 契约）

### 4.1 dry_run 返回（新增 `status_conflicts`，`created` 新增 `status`）

```json
{
  "dry_run": true,
  "total": 3,
  "created": [
    { "advertiser_id": "123", "bc": "BC-A", "country": "US", "agent": "渠道X", "timezone": "+8", "consumption": "高", "status": "死亡" }
  ],
  "updated": [ { "advertiser_id": "456" } ],
  "conflicts": [
    { "advertiser_id": "789", "sheet_value": "高", "system_value": "低" }
  ],
  "status_conflicts": [
    { "advertiser_id": "111", "sheet_status": "死亡", "system_status": "存活" },
    { "advertiser_id": "222", "sheet_status": "存活", "system_status": "死亡" }
  ]
}
```

### 4.2 confirm 请求（新增 `status_resolutions`）

```json
{
  "dry_run": false,
  "resolutions": { "789": "高" },
  "status_resolutions": { "111": "死亡", "222": "存活" }
}
```

`status_resolutions` 只含用户选择「以 Sheet 为准」的项，value 为目标状态名（"存活"/"死亡"）。

## 5. UI 改动（TtAccountSyncModal.vue）

1. **新增账户表**：新增「状态」列，展示 `status`（死亡用红色标签突出）。
2. **新增「状态冲突」区块**（类似现有「消耗冲突」区块）：
   - 表格列：广告账户 ID、Sheet 状态（C 列推导）、系统状态、处理方式。
   - 处理方式 radio：「以 Sheet 为准（改为 X）」/「以系统为准（保持 Y）」。
3. **doSync**：把选「以 Sheet 为准」的项组装成 `status_resolutions` 随请求提交。
4. `canSync` 判断加入 `status_conflicts.length > 0`。

## 6. 边界与约束

- C 列只有「可用」「是」两种值（用户确认）；空值按「存活」处理（安全兜底）。
- 越权保护：`status_resolutions` 只处理当前用户看板行内的 advertiser_id（复用 `valid_ids` 校验）。
- 不改动现有「消耗冲突」「新增」「无变化」逻辑（纯增量）。
