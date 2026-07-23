# 批量导入 — 新账户支持逐个配置

**日期**: 2026-07-10  
**状态**: 待确认

## 需求描述

当前批量导入时，所有**新账户**（系统中不存在的账户 ID）共用一套配置：名称前缀、时区、代理、状态、MCC、到手时间。但实际场景中，同一批次导入的账户可能来自不同渠道，每个账户的名称、时区、代理等都可能不同。

需要支持：**在导入前，对每个新账户单独设置名称、时区、代理等字段**，同时保留共用配置作为默认值（减少重复操作）。

## 技术方案

### 前端改动

**文件**: `frontend/src/components/AccountBatchImportModal.vue`

#### 1. 新账户展示从纯统计改为可编辑表格

当前 `newIds` 只是一个字符串数组，改成带编辑数据的响应式对象。

**新增数据结构**:
```js
// { [account_id]: { name, timezone, agent, status, mcc_id, acquired_date } }
const newAccountEdits = reactive({})
```

#### 2. 新账户区域改为表格 + 编辑面板

将当前的「新账户共用配置」区域改为：

```
┌─ 新账户（N 个） ─────────────────────────────┐
│ 表格（可勾选、可逐行编辑）                      │
│ ┌─────────┬────────┬──────┬──────┬──────┬────┐ │
│ │ 账户 ID   │ 名称    │ 时区  │ 代理  │ 状态  │…│ │
│ ├─────────┼────────┼──────┼──────┼──────┼────┤ │
│ │ 123-…    │ 账户A   │ UTC+8│ 代理X │ 存活  │✏️│ │
│ │ 234-…    │ 234-…   │ UTC+8│ 代理X │ 存活  │✏️│ │  ← 默认值来自共用配置
│ └─────────┴────────┴──────┴──────┴──────┴────┘ │
│                                                │
│ ┌─ 共用默认值（修改后自动同步到未单独编辑的行）──┐ │
│ │ 名称前缀 时区 代理 状态 MCC 到手时间          │ │
│ └────────────────────────────────────────────┘ │
│                                                │
│ ┌─ 逐行编辑面板（点击 ✏️ 展开）────────────────┐ │
│ │ 名称 时区 代理 状态 MCC 到手时间              │ │
│ └────────────────────────────────────────────┘ │
└────────────────────────────────────────────────┘
```

#### 3. 交互逻辑

- **共用默认值**：作为所有新账户的初始默认值
- **修改共用默认值**：自动同步到**尚未单独编辑过**的行（用 `dirty` 标记区分）
- **逐行编辑**：点击某行的 ✏️ 按钮，展开编辑面板，修改后仅影响该行，并标记 `dirty`
- **恢复默认**：编辑面板提供「恢复默认」按钮，将该行重置回共用默认值

#### 4. 共用默认值字段精简

名称字段改为「名称前缀」，新账户的默认名称 = `前缀 + 账户ID`（与现在一致）。逐行编辑时直接填写完整名称。

### 后端改动

**文件**: `py/main.py`

#### 接口改造: `POST /api/accounts/batch-create`

**现有请求体**:
```json
{
  "account_ids": ["123-456-7890"],
  "name_prefix": "前缀",
  "timezone": "UTC+8",
  "agent": "代理X",
  "status": "存活",
  "mcc_id": null,
  "acquired_date": "2026-07-10"
}
```

**新请求体**（向后兼容）:
```json
{
  "account_ids": ["123-456-7890", "234-567-8901"],
  "name_prefix": "前缀",
  "timezone": "UTC+8",
  "agent": "代理X",
  "status": "存活",
  "mcc_id": null,
  "acquired_date": "2026-07-10",
  "overrides": {
    "123-456-7890": {
      "name": "自定义名称A",
      "timezone": "UTC-5",
      "agent": "代理Y"
    },
    "234-567-8901": {
      "name": "自定义名称B"
    }
  }
}
```

- `overrides` 为可选字段，key 为 `account_id`，value 为覆盖的字段（只传需要覆盖的字段）
- 后端创建每个账户时，先用共用配置，再用 `overrides[account_id]` 中的字段覆盖
- 如果 `overrides` 为空或不传，行为与现在完全一致（向后兼容）

**后端改动量**：约 15 行，在创建循环中加一段 merge 逻辑。

### 不改动的部分

- 他人账户的认领编辑（已有逐行编辑功能，无需改动）
- ID 解析逻辑
- 批量查询逻辑

## 涉及文件

| 文件 | 改动类型 |
|------|---------|
| `frontend/src/components/AccountBatchImportModal.vue` | 主要改动 — 新账户表格 + 逐行编辑 |
| `py/main.py` | 接口改动 — 支持 `overrides` 参数 |

## 风险

- **低风险**：后端改动小且向后兼容，overrides 为空时行为不变
- 前端重构涉及模板和逻辑，需要仔细处理共用默认值 → 逐行覆盖的数据流

---

## 实际代码逻辑补充（2026-07-23 审计）

以下内容基于实际代码与设计文档的对比，记录设计文档未覆盖或与设计存在出入的实现细节。

### 一、前端实现细节（`AccountBatchImportModal.vue`）

#### 1. Dirty 判定机制：基线快照对比（与文档「dirty 标记」的设计差异）

文档描述为"用 `dirty` 标记区分"，实际代码**没有使用布尔标记**，而是采用**基线快照对比**机制：

- 引入独立的 `newAccountBaselines` 响应式对象，结构与 `newAccountEdits` 相同
- `initNewAccountEdit(aid)` 时，同时用当前默认值初始化 `newAccountEdits[aid]` 和 `newAccountBaselines[aid]`
- `isNewDirty(aid)` 将 `newAccountEdits[aid]` 的 6 个字段（name/timezone/agent/status/mcc_id/acquired_date）与 `newAccountBaselines[aid]` 逐字段比较，任一不等即为 dirty
- `syncDefaultsToNewAccounts()` 在合并新默认值到非 dirty 行时，**同时更新 `newAccountBaselines`**，确保基线始终与"上次同步时的默认值"一致

**设计意图**：直接比较当前值与 live 默认值无法区分"用户手动改过"和"默认值变了导致不同"——需要基线记录"上次同步那一刻的默认值快照"。

#### 2. 共用默认值同步的完整数据流

```
watch(defaultForm 变化)
  → syncDefaultsToNewAccounts()
    → 遍历 newIds.value 中每个 aid
      → isNewDirty(aid) ? 跳过（保留用户手动编辑）
      → 未 dirty: Object.assign(newAccountEdits[aid], newDefaults)
                   Object.assign(newAccountBaselines[aid], newDefaults)  // 同步基线
```

- 共用默认值 watch 使用 `watch(() => ({ ...defaultForm }))` ——浅拷贝触发（Vue 3 深度监听变通方案）
- `newIds` 变更时触发另一 watch：清理已移除 ID 的 `newAccountEdits` / `newAccountBaselines` 条目，并为新增 ID 初始化默认编辑数据

#### 3. `overrides` 的 diff 构造逻辑

前端提交时，只对**与默认值不同的字段**构造 overrides：

```js
// 每个新账户的 6 个字段逐一比较
if (cur.name !== def.name) diff.name = cur.name
if (cur.timezone !== def.timezone) diff.timezone = cur.timezone
// ... mcc_id, agent, status, acquired_date 同理
```

- 如果某个账户所有字段都与默认值相同，该账户不在 `overrides` 中出现
- `overrides` 为空对象时不发送（`Object.keys(overrides).length ? overrides : undefined`）

#### 4. 代理自动收集与持久化

批量创建成功后，代码自动收集所有新出现的代理值并保存到系统设置：

- 收集来源：`defaultForm.agent` + 所有 `overrides` 中的 `agent` 值
- 去重：与现有 `store.settings.account_agents` 合并去重
- 持久化：调用 `store.saveSettings({ account_agents: agents })`
- 这意味着用户在批量导入时输入的代理会自动出现在后续下拉选项中

#### 5. 提交前置校验

除了按钮的 `disabled` 条件（无新账户且无选中认领），提交时还有额外的客户端校验：

- **代理校验**：检查 `defaultForm.agent` 和所有新账户逐行覆盖的 `agent` 中，至少有一个非空值；否则弹出"代理不能为空"

#### 6. ID 提取与解析（文档标注为"不改动"）

虽然文档标注为不改动，但实际逻辑值得记录：

- 支持的格式：标准格式 `123-456-7890`、纯数字 10 位、以及上述格式嵌入在任意文字中的行
- `ID_PATTERN = /^\d{3}-\d{3}-\d{4}$/` 仅用于匹配纯标准格式
- `invalidIds`：无法从该行提取任何合规 ID 的原始文本行，单独显示
- 输入解析有**去重**：同一 ID 在文本中出现多次仅保留一次

#### 7. 防抖查询

输入 ID 文本后，通过 `setTimeout` 实现 400ms 防抖再触发 `batchLookup` API 调用。每次调用前清除旧 timer。

#### 8. 对话框初始化（`init()`）

每次打开对话框时完整重置：

- `acquired_date` 设为当天日期
- 所有编辑状态（`claimEdits`、`newAccountEdits`、`newAccountBaselines`、`editingId`、`newEditingId`）清空
- `idText` 和 `result` 清空
- 重新加载 MCC 选项列表

#### 9. 已有账户认领编辑面板（文档仅简述）

虽然文档说"已有逐行编辑功能，无需改动"，但实际实现的编辑面板包含完整功能：

- 编辑字段：名称、时区、代理、状态、MCC、到手时间（与新建账户编辑面板完全对称）
- 编辑面板初始化：从行数据（`row.name`、`row.timezone` 等）复制初始值
- 提交时：每个选中的已有账户单独调用 `accountsApi.reassign(row.id, body)`，仅发送用户实际修改过的字段
- 认领失败的账户单独收集并以红色列表显示

#### 10. 外部数据依赖

| 数据 | 来源 | 用途 |
|------|------|------|
| MCC 选项列表 | `GET /mcc/options` | 共用默认值和编辑面板的 MCC 下拉 |
| 代理选项列表 | `store.settings.account_agents` | 编辑面板的代理下拉（支持 allow-create） |
| 状态选项列表 | `store.settings.account_statuses` | 编辑面板的状态下拉 |

- 时区选项**不依赖外部数据**，由 `buildTimezoneOptions()` 本地生成：UTC-12 到 UTC+12 的整数偏移 + `UTC+5:30`、`UTC+8:45`、`UTC-3:30` 三个特殊偏移

#### 11. 导入结果展示

结果包含 4 类信息：

| 字段 | 含义 | 颜色 |
|------|------|------|
| `created` | 成功新建数量 | 绿色（success） |
| `claimed` | 成功认领数量 | 绿色（success） |
| `skipped` | 跳过（含原因） | 黄色（warning） |
| `claimFailed` | 认领失败（含原因） | 红色（error） |

### 二、后端实现细节（`py/main.py`）

#### 1. `overrides` 字段合并：key-existence 语义

后端对所有字段（除 `name`）使用 **key-existence 检查**而非 truthiness 检查：

```python
mcc_id = ov.get("mcc_id") if "mcc_id" in ov else common["mcc_id"]
```

这意味着：只要 override dict 中**存在该 key**，就使用其值（即使值为空字符串 `""`）。这与 `ov.get("field") or common["field"]` 有本质区别——后者在空字符串时会回退到共用配置。

**`name` 字段是例外**：使用 truthiness 检查 `if ov.get("name")`，空字符串名称 override 将回退到 `name_prefix + account_id`。

#### 2. 新建账户的 MCC 变更历史

批量创建时，如果为新账户分配了 MCC：

- 记录到 `account_mcc_history` 表，`change_type = "import"`
- 空值处理：`mcc_id` 为 `0`、`"0"` 或空字符串时统一转为 `None`，不记录历史
- 该逻辑在 INSERT 成功后的同一个事务批次中执行

#### 3. 重复账户的友好错误信息

当 INSERT 触发 `IntegrityError` 时（账户已存在），后端会：

- 查询 `accounts LEFT JOIN users` 获取已有归属人
- 返回 `{ account_id: "xxx", reason: "已存在，归属人：张三" }`
- 如果查不到归属人，显示"未知"
- 其他类型的 `IntegrityError` 直接返回原始错误信息

#### 4. `batch-lookup` 查询逻辑

- 使用 `WHERE account_id IN (...)` 单次查询
- 返回 `found`（已存在账户列表）+ `not_found`（未找到的 ID 列表）
- 已存在的账户通过 `_account_row_to_dict` 格式化，包含 12 个字段：`id`、`name`、`account_id`、`timezone`、`agent`、`status`、`acquired_date`、`mcc_id`、`mcc_name`、`mcc_code`、`owner_id`、`owner_name`
- 关联查询了 `users` 表获取归属人信息

#### 5. `reassign` 接口的字段更新逻辑

认领时可选更新字段 `["name", "timezone", "agent", "status", "acquired_date"]`，只在请求体中有该 key 且值非 `None` 时才更新。MCC 单独处理：空值转 `None` 后记录变更历史。

#### 6. 交互时序

完整的批量导入交互包含以下 API 调用：

```
1. GET  /mcc/options                  — 加载 MCC 下拉选项
2. POST /accounts/batch-lookup        — 输入 ID 后查询已有账户
3. POST /accounts/batch-create        — 创建新账户（含 overrides）
4. PUT  /accounts/:id/reassign (×N)   — 逐个认领已有账户
5. POST /settings/account             — 保存新代理到系统设置（如有）
```
