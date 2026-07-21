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
| `created_by` | INTEGER | 提交人 user ID |
| `created_at` | TEXT | 创建时间 |

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

---

## 五、后端 API

### 5.1 Settings 扩展

现有 `GET/POST /api/settings/account` 新增 key：

- `recharge_sheet_id`：充值表 Google Sheets ID（空字符串表示未配置）

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

**处理流程：**
1. 获取当前用户 `display_name` 作为运营
2. 写入 `recharge_records` 表
3. 异步追加到 Google Sheets「充值表」sheet
4. Sheets 写入失败不影响数据库记录（catch 异常，返回 warning）

**响应：**
```json
{"success": true, "id": 1}
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
1. 批量 INSERT 到 `recharge_records`
2. 异步批量追加到 Google Sheets
3. 返回写入条数

**响应：**
```json
{"success": true, "count": 2}
```

### 5.4 死亡自动写「清」

在 `PUT /api/accounts/<id>` 更新账户时，如果 `status` 变为「死亡」：

1. 先查 `recharge_records` 是否已有该 `account_id` + `amount = '清'` 的记录
2. 没有 → 写入一条 `amount='清'`, `agent` 取账户当前代理, `operator` 取当前用户 `display_name`
3. 异步追加到 Google Sheets
4. 已有 → 跳过
5. 后端响应中新增 `recharge_note: "已追加清账记录"` 字段，前端据此弹窗提醒

---

## 六、前端 UI

### 6.1 AdsAccountPanel.vue

**操作列新增按钮：**
```
[✏️] [📋] [💰] [🗑]
```
- 「💰」→ 打开 RechargeModal，默认带入该行账户

**工具栏新增：**
```
[➕ 新增账户] [📥 批量导入] [🔍 批量查户] [💰 批量充值]  已选 N 条 ...
```
- 「💰 批量充值」：`selected.length > 0` 时可用

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

- 账户ID 下拉数据源：当前用户的所有账户（不分页）
- 账户ID 变化 → 查找对应 `agent` 自动填入
- 提交后关闭弹窗，刷新账户列表

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

- 数据行 = 用户在 AdsAccountPanel 中勾选的账户
- 每行金额可独立编辑，也可通过「统一金额」一键填充
- 提交后关闭弹窗，清空勾选

### 6.4 SettingsPanel.vue

在「账户设置」Tab 底部，仅 admin/developer 可见：

```
📊 充值表配置（仅管理员可见）
Google Sheets ID: [____________________]
[💾 保存]
```

- 数据从 `store.settings.recharge_sheet_id` 读写
- 保存到 `/api/settings/account`

### 6.5 AccountModal.vue — 死亡清账提醒

- 提交账户编辑后，检查响应中的 `recharge_note` 字段
- 如果 `recharge_note === "已追加清账记录"`，`ElMessage.success("该账户已自动追加清账记录")`

---

## 七、去重规则

| 场景 | 规则 |
|---|---|
| 普通充值（单次/批量） | **不做去重**，直接追加 |
| 死亡清账（amount='清'） | **按 account_id 去重**，同一个账户ID + '清' 只写入一次 |

---

## 八、错误处理

| 情况 | 处理 |
|---|---|
| 未配置充值表 | `"请先在设置中配置充值表格"` |
| Google Sheets API 未授权 | `"Google Sheets 未授权，请联系管理员"` |
| 表格 ID 无效/无权访问 | `"无法访问表格，请检查表格链接"` |
| 表格中没有「充值表」sheet | `"表格中未找到「充值表」工作表"` |
| Sheets 写入失败 | 数据库已写入成功，返回 warning 信息 |
| 账户ID下拉为空 | 前端展示空列表 |

---

## 九、涉及文件汇总

| 文件 | 操作 | 说明 |
|---|---|---|
| `py/database.py` | 修改 | 新增 `recharge_records` 表 |
| `py/main.py` | 修改 | 新增 `POST /api/recharge/submit`、`POST /api/recharge/batch-submit`；settings 扩展 `recharge_sheet_id`；账户 status 更新挂钩死亡清账 |
| `py/google_sheets_service.py` | 修改 | 新增 `append_recharge()` |
| `frontend/src/api/accounts.js` | 修改 | 新增 `rechargeSubmit()`、`rechargeBatchSubmit()` |
| `frontend/src/stores/accounts.js` | 修改 | 新增 recharge actions |
| `frontend/src/views/AdsAccountPanel.vue` | 修改 | 操作列加「💰」、工具栏加「💰 批量充值」 |
| `frontend/src/components/RechargeModal.vue` | **新建** | 单次充值弹窗 |
| `frontend/src/components/RechargeBatchModal.vue` | **新建** | 批量充值弹窗 |
| `frontend/src/views/SettingsPanel.vue` | 修改 | 新增充值表配置（仅 admin/developer 可见） |
| `frontend/src/components/AccountModal.vue` | 修改 | 处理死亡清账返回的 `recharge_note` 弹窗提醒 |
