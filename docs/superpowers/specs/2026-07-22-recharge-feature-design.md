# 账户充值功能 — 设计文档

> 在 [2026-07-21 Google Sheets 做表数据自动写入设计](2026-07-21-google-sheets-toolkit-update-design.md) 基础上扩展。

## 一、需求描述

1. **单次充值**：在 AdsAccountPanel 操作列新增「💰」按钮，点击弹出充值弹窗，填写账户ID（下拉搜索）、金额，代理自动联动，运营取当前用户 display_name，提交后写入数据库 + Google Sheets
2. **批量充值**：勾选账户后工具栏「💰 批量充值」，弹窗展示勾选账户列表，金额可分别填或统一填
3. **充值表配置**：SettingsPanel 中配置 Google Sheets ID（仅 admin/developer 可见），所有用户共用同一张表
4. **数据库 + Sheets 双写**：`recharge_records` 表为数据源，Google Sheets「充值表」sheet 为共享视图
5. **死亡清账**：账户状态变为「死亡」时，自动追加一条金额为「清」的充值记录，按账户ID去重

---

## 二、方案选择

选择**方案 B：数据库 + Sheets 双写**。

- 数据库是记录源，可查询、统计、去重
- Google Sheets 是共享视图，充值人员在此基础上手动更新「是否充值」列
- 写入顺序：先写数据库，再异步追加 Sheets（Sheets 失败不影响数据库）

---

## 三、数据库新表

```sql
CREATE TABLE IF NOT EXISTS recharge_records (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id TEXT NOT NULL,
    amount TEXT NOT NULL,
    agent TEXT DEFAULT '',
    operator TEXT DEFAULT '',
    status TEXT DEFAULT '',
    created_by INTEGER REFERENCES users(id),
    created_at TEXT DEFAULT (datetime('now','localtime'))
);
CREATE INDEX IF NOT EXISTS idx_recharge_account ON recharge_records(account_id);
```

| 列 | 类型 | 说明 |
|---|---|---|
| `id` | INTEGER | 主键 |
| `account_id` | TEXT | 账户ID（如 `123-456-7890`） |
| `amount` | TEXT | 金额（数字或 `清`） |
| `agent` | TEXT | 代理（来自账户的 agent 字段） |
| `operator` | TEXT | 运营（当前用户 display_name） |
| `status` | TEXT | 账户状态（清账记录时填入触发状态，如「死亡」；普通充值留空） |
| `created_by` | INTEGER | 提交人 user ID |
| `created_at` | TEXT | 创建时间 |

> **迁移字段**（建表后通过 `_add_column_if_missing` 追加）：
> - `sheets_synced` INTEGER DEFAULT 0 — Sheets 同步状态（0=未同步，1=已同步）
> - `sheets_error` TEXT DEFAULT '' — Sheets 同步失败时的错误信息

---

## 四、Google Sheets 列映射

Sheet 名为「充值表」，从 spreadsheet 的所有 sheet 中按名称定位。

| 列 | 列头 | 写入值 | 说明 |
|---|---|---|---|
| A | 账户ID | ✅ `account_id` | |
| B | 金额 | ✅ 手动输入 / `清` | |
| C | 代理 | ✅ 账户 `agent` | 自动联动 |
| D | 运营 | ✅ 当前用户 `display_name` | 自动填入 |
| E | 时间 | ❌ 留空 | 不管理 |
| F | 是否充值 | ❌ 留空 | 留给充值人员手动填 |
| G | 状态 | ✅ 账户状态（清账时写入） | 普通充值留空，清账时填触发状态 |

---

## 五、后端 API

### 5.1 Settings 扩展

现有 `GET/POST /api/settings/account` 新增 key：

- `recharge_sheet_id`：充值表 Google Sheets ID（空字符串表示未配置）
  - 后端 `_parse_sheet_id()` 支持从完整 URL（`/d/<id>`）中提取，前端 SettingsPanel 也会自动提取

### 5.2 `POST /api/recharge/submit` — 单次充值

**认证：** `@jwt_required()`

**请求体：**
```json
{
  "account_id": "123-456-7890",
  "amount": "1000",
  "agent": "卡尔"
}
```

**前置校验：** 账户状态必须为「存活」，否则返回 `400 "仅存活状态的账户允许充值"`

**处理流程：**
1. 获取当前用户 `display_name` 作为运营
2. **校验账户必须存活**，非存活拒绝
3. 写入 `recharge_records` 表（`sheets_synced=0`）
4. `db.commit()` 提交数据库
5. 后台线程异步追加到 Google Sheets「充值表」sheet（失败后 30 秒重试一次）
6. Sheets 同步成功 → 更新 `sheets_synced=1`；失败 → 写入 `sheets_error`
7. Sheets 写入失败不影响数据库记录（catch 异常，返回 warning）

**响应：**
```json
{"success": true, "id": 1}
```
或（Sheets 未配置）：
```json
{"success": true, "id": 1, "warning": "充值记录已保存，但充值表格未配置"}
```

### 5.3 `POST /api/recharge/batch-submit` — 批量充值

**请求体：**
```json
{
  "records": [
    {"account_id": "123-456-7890", "amount": "500", "agent": "卡尔"},
    {"account_id": "987-654-3210", "amount": "1000", "agent": "止戈"}
  ]
}
```

**处理流程：**
1. 逐条校验：跳过 account_id/amount 为空 或 账户非存活 的记录（**静默跳过，不报错**）
2. 逐条 INSERT 到 `recharge_records`，收集 `inserted_ids`
3. `db.commit()`
4. 后台线程批量追加到 Google Sheets（所有有效行一次性写入）
5. 返回写入条数（仅有效记录数）

**响应：**
```json
{"success": true, "count": 2}
```

### 5.4 `GET /api/accounts/<aid>/recharge-records` — 查询充值记录

**认证：** `@jwt_required()`

按 `account_id` 查询该账户的所有充值记录，按 `created_at DESC` 排序。

**响应：**
```json
{
  "success": true,
  "records": [
    {"id": 1, "account_id": "123-456-7890", "amount": "1000", "agent": "卡尔", "operator": "张三", "status": "", "sheets_synced": 1, "sheets_error": "", "created_at": "2026-07-22 10:00:00"}
  ]
}
```

### 5.5 `PUT /api/recharge/<rid>` — 编辑充值记录

**认证：** `@jwt_required()`

可修改字段：`amount`（必填）、`agent`（选填）。

> 注意：编辑**不会**重新同步 Sheets，仅更新数据库。

### 5.6 `DELETE /api/recharge/<rid>` — 删除充值记录

**认证：** `@jwt_required()`

物理删除数据库记录。**不会**从 Sheets 中删除对应行。

### 5.7 `POST /api/recharge/<rid>/retry-sheets` — 手动重试 Sheets 同步

**认证：** `@jwt_required()`

读取数据库中的记录，重新调用 `append_recharge` 同步到 Sheets。
成功 → `sheets_synced=1, sheets_error=''`；失败 → 写入 `sheets_error`。

### 5.8 死亡自动写「清」（含批量）

在 `PUT /api/accounts/<id>` 和 `POST /api/accounts/batch-update` 更新账户时触发。

**触发条件（实际代码逻辑，比文档描述的更广）：**

- 当 `new_status != "存活"` 且 `old_status == "存活"` 时触发
- 这意味着状态切到「死亡」「验证」「限额」等任何非存活状态都会触发，不仅仅是「死亡」

**去重逻辑（实际代码逻辑，与文档不同）：**

1. 读取账户的 `status_changed_date`（上次变为存活的时间）
2. 如果 `status_changed_date` 为空（首次切换），直接写「清」记录
3. 如果 `status_changed_date` 有值，查询自该时间之后是否存在 `amount != '清'` 的充值记录
4. 有充值记录 → 写「清」；无充值记录 → 跳过
5. **去重依据不是 `account_id + amount='清'`，而是"上次存活后是否有过充值"**

**写入内容：**

- `amount = '清'`
- `status = new_status`（触发时的目标状态，如「死亡」）
- `agent` 取请求中的 agent 或账户当前的 agent
- `operator` 取当前用户的 display_name
- `sheets_synced = 0`

**响应：**
- 后端响应中新增 `recharge_note: "已追加清账记录"` 字段
- 前端 `AccountModal.vue` 据此 `ElMessage.success("该账户已自动追加清账记录")`

**批量场景：**
- 批量改状态时同样触发，收集所有 `new_clear_rows` 后统一后台同步 Sheets

### 5.9 账户删除时级联删除充值记录

`DELETE /api/accounts/<aid>` 和 `POST /api/accounts/batch-delete` 在删除账户前，
先 `DELETE FROM recharge_records WHERE account_id=?`。

### 5.10 `status_changed_date` 字段

- 账户表（`accounts`）通过迁移新增 `status_changed_date TEXT DEFAULT ''`
- 每次账户 status 变更时，更新为该时刻的时间戳
- 在前端 AdsAccountPanel 表格中作为「状态变更时间」列展示
- 是死亡清账去重逻辑的关键依据

---

## 六、前端 UI

### 6.1 AdsAccountPanel.vue

**操作列新增按钮：**
```
[✏️] [📋] [💰] [🗑]
```
- 「✏️」→ 编辑账户
- 「📋」→ 查看账户详情（含充值记录）
- 「💰」→ 打开 RechargeModal，默认带入该行账户
- 「🗑」→ 删除账户

**工具栏新增：**
```
[➕ 新增账户] [📥 批量导入] [🔍 批量查户] [💰 批量充值]  已选 N 条 ...
```
- 「💰 批量充值」：`selected.length > 0` 时可用

**表格展示：**
- 新增「状态变更时间」列，展示 `status_changed_date` 字段

### 6.2 RechargeModal.vue — 单次充值弹窗

```
┌──────────────────────────────────────┐
│  💰 充值                             │
│                                      │
│  账户ID: [下拉搜索框 ▼]              │  ← 默认当前点击的账户
│  代理:    自动显示（只读）            │  ← 账户ID变，代理自动联动
│  运营:    当前用户 display_name（只读）│
│  金额:    [手动输入]                  │
│                                      │
│  [取消]  [💰 确认充值]               │
└──────────────────────────────────────┘
```

- 账户ID 下拉数据源：当前用户的所有**存活**账户（`filter(a => a.status === '存活')`）
- 下拉显示格式：`account_id (name)`
- 账户ID 变化 → 查找对应 `agent` 自动填入
- 提交后关闭弹窗，刷新账户列表
- 处理响应中的 `warning` 字段（Sheets 未配置等情况）

### 6.3 RechargeBatchModal.vue — 批量充值弹窗

```
┌──────────────────────────────────────────────┐
│  💰 批量充值                                │
│                                              │
│  统一金额: [输入框]  [📝 应用]               │  ← 一键填充所有行
│                                              │
│  ┌──────────────────────────────────────┐    │
│  │ 账户ID          │ 代理 │ 金额        │    │
│  │ 123-456-7890    │ 卡尔 │ [____]     │    │
│  │ 987-654-3210    │ 止戈 │ [____]     │    │
│  │ ...                                   │    │
│  └──────────────────────────────────────┘    │
│                                              │
│  [取消]  [💰 确认批量充值]                   │
└──────────────────────────────────────────────┘
```

- 打开弹窗时自动过滤：仅保留**存活**账户
- 非存活账户被跳过时，弹窗提示 `已跳过 N 个非存活状态的账户，仅可对存活账户充值`
- 提交后关闭弹窗，清空勾选

### 6.4 SettingsPanel.vue

在「账户设置」Tab 底部，仅 admin/developer 可见：

```
📊 充值表配置（仅管理员可见）
Google Sheets（URL 或 ID）: [____________________]
[💾 保存]
```

- 支持直接粘贴完整 Google Sheets URL，前端自动提取 spreadsheet ID（正则 `/spreadsheets\/d\/([a-zA-Z0-9_-]+)/`）
- 后端 `_parse_sheet_id()` 同样支持 URL 提取
- 保存到 `/api/settings/account`

### 6.5 AccountModal.vue — 死亡清账提醒

- 提交账户编辑后，检查响应中的 `recharge_note` 字段
- 如果 `recharge_note === "已追加清账记录"`，`ElMessage.success("该账户已自动追加清账记录")`

### 6.6 AccountDetailModal.vue — 充值记录展示与操作

在账户详情弹窗中新增「💰 充值记录」区块：

- 表格列：金额、状态、代理、运营、表格同步状态、时间、操作
- **编辑**：行内编辑金额和代理，调用 `PUT /api/recharge/<id>`
- **删除**：确认后调用 `DELETE /api/recharge/<id>`（仅删数据库，不影响 Sheets）
- **Sheets 同步状态**：
  - `sheets_synced=0` 时显示 ⚠️ 图标，hover 显示错误信息
  - 点击 ⚠️ 触发 `POST /api/recharge/<id>/retry-sheets`
  - `sheets_synced=1` 时显示 ✅
- 状态列：展示 `row.status`（清账记录会显示触发状态如「死亡」）

---

## 七、去重规则

| 场景 | 规则 |
|---|---|
| 普通充值（单次/批量） | **不做去重**，直接追加 |
| 死亡清账（amount='清'） | **按上次存活后是否有充值判断**：查 `recharge_records` 中自 `status_changed_date` 以来是否有 `amount != '清'` 的记录，有则写清，无则跳过 |

---

## 八、错误处理

| 情况 | 处理 |
|---|---|
| 未配置充值表 | `"请先在设置中配置充值表格"` |
| Google Sheets API 未授权 | `"Google Sheets 未授权，请联系管理员"` |
| 表格 ID 无效/无权访问 | `"无法访问表格，请检查表格链接"` |
| 表格中没有「充值表」sheet | `"表格中未找到「充值表」工作表"` |
| Sheets 写入失败 | 数据库已写入成功，后台自动 30 秒后重试一次；两次都失败则写入 `sheets_error` |
| 账户ID下拉为空 | 前端展示空列表 |
| 账户非存活状态充值 | 单次：返回 400 `"仅存活状态的账户允许充值"`；批量：静默跳过非存活账户 |
| 充值记录编辑（金额为空） | 返回 400 `"金额不能为空"` |

---

## 九、涉及文件汇总

| 文件 | 操作 | 说明 |
|---|---|---|
| `py/database.py` | 修改 | 新增 `recharge_records` 表；迁移追加 `status`、`sheets_synced`、`sheets_error` 列；`accounts` 表追加 `status_changed_date` |
| `py/main.py` | 修改 | 新增 `POST /api/recharge/submit`、`POST /api/recharge/batch-submit`、`GET /api/accounts/<aid>/recharge-records`、`PUT /api/recharge/<rid>`、`DELETE /api/recharge/<rid>`、`POST /api/recharge/<rid>/retry-sheets`；settings 扩展 `recharge_sheet_id`；账户 status 更新挂钩死亡清账（含批量）；账户删除级联删除充值记录；`_parse_sheet_id` 辅助函数；`_sync_sheets_background` 后台线程+30s 重试 |
| `py/google_sheets_service.py` | 修改 | 新增 `append_recharge()`，写入 A-G 共 7 列 |
| `frontend/src/api/accounts.js` | 修改 | 新增 `rechargeSubmit()`、`rechargeBatchSubmit()`、`rechargeRecords()`、`rechargeUpdate()`、`rechargeDelete()`、`rechargeRetrySheets()` |
| `frontend/src/stores/accounts.js` | 修改 | 新增 `rechargeSubmit`、`rechargeBatchSubmit` actions |
| `frontend/src/views/AdsAccountPanel.vue` | 修改 | 操作列加「💰」、工具栏加「💰 批量充值」、表格展示「状态变更时间」列 |
| `frontend/src/components/RechargeModal.vue` | **新建** | 单次充值弹窗（仅展示存活账户，处理 warning 响应） |
| `frontend/src/components/RechargeBatchModal.vue` | **新建** | 批量充值弹窗（过滤非存活账户并提示） |
| `frontend/src/views/SettingsPanel.vue` | 修改 | 新增充值表配置（仅 admin/developer 可见，支持 URL 自动提取 ID） |
| `frontend/src/components/AccountModal.vue` | 修改 | 处理死亡清账返回的 `recharge_note` 弹窗提醒 |
| `frontend/src/components/AccountDetailModal.vue` | **修改** | 新增充值记录列表展示、编辑删除、Sheets 重试 |

---

## 十、代码实际逻辑补充（2026-07-23 审计）

以下记录设计文档与代码实际逻辑之间的差异，按发现的时间顺序排列。

### 10.1 数据库表结构差异

| 差异点 | 文档描述 | 代码实际 |
|---|---|---|
| `recharge_records` 列数 | 6 列（id, account_id, amount, agent, operator, created_by, created_at） | 9 列（额外包含 `status`、`sheets_synced`、`sheets_error`） |
| `status` 列 | 不存在 | `TEXT DEFAULT ''`，清账时写入触发状态（如「死亡」） |
| `sheets_synced` 列 | 不存在 | `INTEGER DEFAULT 0`，0=未同步，1=已同步 |
| `sheets_error` 列 | 不存在 | `TEXT DEFAULT ''`，存储 Sheets 同步失败原因 |
| `accounts.status_changed_date` | 不存在 | `TEXT DEFAULT ''`，状态变更时自动更新，是清账去重的关键依据 |

### 10.2 未记录的 API

| API | 方法 | 说明 |
|---|---|---|
| `/api/accounts/<aid>/recharge-records` | GET | 按账户查询充值记录列表（按 created_at DESC） |
| `/api/recharge/<rid>` | PUT | 编辑充值记录的金额和代理（仅改 DB，不同步 Sheets） |
| `/api/recharge/<rid>` | DELETE | 删除充值记录（仅删 DB，不影响 Sheets） |
| `/api/recharge/<rid>/retry-sheets` | POST | 手动重试单条记录的 Sheets 同步 |

### 10.3 写入流程实际逻辑

| 差异点 | 文档描述 | 代码实际 |
|---|---|---|
| 写入时序 | "先写数据库，再异步追加 Sheets" | 先写 DB → `db.commit()` → **关闭 DB 连接** → 启动后台线程写 Sheets |
| Sheets 同步机制 | 仅提"异步追加" | 后台线程 `_sync_sheets_background`：失败后 30 秒自动重试一次；成功/失败均更新 `sheets_synced`/`sheets_error` |
| 账户状态校验 | 未提及 | 单次充值：校验账户必须为「存活」，否则 400；批量充值：静默跳过非存活账户 |
| 响应 warning | 未提及 | 当 Sheets 未配置时，响应中附带 `warning` 字段，前端展示 |
| 批量提交无效记录 | 未提及 | 逐条校验 account_id/amount/status，无效记录**静默跳过**不报错；全部无效则 400 |

### 10.4 死亡清账逻辑差异

| 差异点 | 文档描述 | 代码实际 |
|---|---|---|
| 触发条件 | "status 变为「死亡」" | **任何非存活状态**（`new_status != "存活"` 且 `old_status == "存活"`），包括「验证」「限额」等 |
| 去重规则 | "查 `account_id + amount = '清'` 是否已有记录" | 查**上次变为存活后**是否有 `amount != '清'` 的充值记录；依赖 `status_changed_date` 判断 |
| 首次切换 | 未描述 | 如果 `status_changed_date` 为空（新账户或老数据迁移前），**直接写清**，不查充值记录 |
| 写入 `status` 列 | 未提及 | 清账记录写入时填充 `status` 列（值为触发时的目标状态） |
| 批量触发 | 仅描述单次更新 | `POST /api/accounts/batch-update` 同样触发，收集所有清账行统一后台同步 |
| 账户恢复存活 | 未提及 | 当 status 从非存活变回「存活」时，更新 `status_changed_date`，为下次清账提供新基线；**不删除历史清账记录** |
| 账户删除级联 | 未提及 | 删除账户时 `DELETE FROM recharge_records WHERE account_id=?` |

### 10.5 Google Sheets 列映射差异

| 差异点 | 文档描述 | 代码实际 |
|---|---|---|
| 写入列数 | A-F（6 列） | A-G（7 列），G 列为「状态」 |
| G 列内容 | 不存在 | 普通充值留空，清账记录写入触发状态（如「死亡」） |
| retry-sheets 数据 | — | 重试时不发送 `status` 字段（`append_recharge` 内 `r.get("status", "")` 默认空字符串） |

### 10.6 前端实际逻辑差异

| 差异点 | 文档描述 | 代码实际 |
|---|---|---|
| RechargeModal 账户下拉 | "当前用户的所有账户（不分页）" | **仅存活账户**（`filter(a => a.status === '存活')`），显示格式 `account_id (name)` |
| RechargeBatchModal 过滤 | "用户在 AdsAccountPanel 中勾选的账户" | 打开时**自动过滤非存活账户**，弹 `ElMessage.warning("已跳过 N 个非存活状态的账户...")` |
| SettingsPanel ID 输入 | 仅提 "Google Sheets ID" | 支持粘贴完整 URL，前端用正则 `/spreadsheets\/d\/([a-zA-Z0-9_-]+)/` 自动提取 |
| 充值记录展示 | 未提及 | `AccountDetailModal.vue` 展示完整的充值记录列表，含编辑、删除、Sheets 重试按钮 |
| Sheets 同步状态 | 未提及 | 列表中每条记录显示 ✅（已同步）或 ⚠️（未同步，hover 显示错误），点击 ⚠️ 触发重试 |
| AdsAccountPanel 表格 | 未提及 `status_changed_date` 列 | 表格展示「状态变更时间」列 |
| 操作列按钮 | 4 个（✏️ 📋 💰 🗑） | 5 个（✏️ 📋 💰 🗑），多了📋详情 |
| store 暴露 | 提及 recharge actions | store 仅暴露 `rechargeSubmit`、`rechargeBatchSubmit`；update/delete/retrySheets 由 AccountDetailModal 直接调用 API |

### 10.7 后台线程同步机制

文档仅提及"异步追加"，代码实际实现为 `_sync_sheets_background(sync_fn, on_fail_fn)`：

1. 启动 daemon 线程执行 `sync_fn`（Sheets 写入）
2. 失败 → 回调 `on_fail_fn("failed", err_msg)` → `sleep(30)` → 重试
3. 重试成功 → 回调 `on_fail_fn("synced", "")` → 更新 `sheets_synced=1`
4. 重试失败 → 回调 `on_fail_fn("retry_failed", err_msg)` → 更新 `sheets_error`
5. 此机制同时复用于做表数据写入

### 10.8 可疑/潜在问题

以下是在审计过程中发现的代码逻辑可疑点：

| 编号 | 问题 | 位置 | 严重程度 |
|---|---|---|---|
| 1 | **retry-sheets 不包含 status**：`POST /api/recharge/<rid>/retry-sheets` 调用 `append_recharge` 时未传 `status` 字段（只传了 account_id、amount、agent、operator）。清账记录重试后 Sheets 的 G 列会变成空白，与首次写入不一致。 | `main.py` 第 4158-4163 行 | 低（有兜底默认值） |
| 2 | **status_changed_date 为空时直接写清**：如果账户是存量数据（status_changed_date 为空），首次切非存活会**无条件**写入一条「清」记录，即使该账户从未有过充值。这可能产生无意义的清账记录。 | `main.py` 第 3644 行 | 低（设计意图明确注释为"第一次不用查，直接填清"） |
| 3 | **批量充值全部无效时错误信息**：当所有记录都被跳过（非存活或缺失字段），返回 `"所有充值记录缺少账户ID或金额，未写入任何数据"`。这个错误信息未提及"非存活状态"的可能性，可能误导排查。 | `main.py` 第 4024 行 | 低（用户体验问题） |
