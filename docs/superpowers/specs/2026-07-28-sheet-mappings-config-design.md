# Sheet 映射动态配置 — 设计文档

## 一、需求描述

将 Google Sheets 充值表 sheet 名称从硬编码改为可配置的映射表。核心功能：

1. **动态读取**：输入 spreadsheet ID 后可读取该表格中所有 sheet 名称，前端下拉框展示
2. **可手动输入**：下拉框支持自由输入（API 读取失败时兜底）
3. **固定映射 + 私有值**：映射 key 是固定的（由后端 `_BUILTIN_SHEET_MAPPING_KEYS` 定义），不允许前端新增/删除；内置 key 的默认 value 全局共享，用户可覆盖为私有值
4. **三层叠加读取**：`_BUILTIN_SHEET_DEFAULTS`（兜底）→ `tags` 表全局值 → `config` 表用户私有覆盖值
5. **向后兼容**：旧数据缺失 key 时由内置默认值补齐

---

## 二、方案

在 `tags` 表中新增 `key="sheet_mappings"` 存储全局默认映射；在 `config` 表中按 `sheet_mappings_{user_id}` 存储用户私有覆盖值。

- 读取时三层叠加：内置默认 → 全局覆盖 → 用户覆盖
- 写入时：admin 的内置 key 值写 `tags`（全局）；所有 key 值写 `config`（用户私有）
- 前端映射列表渲染 `Object.keys(form.sheet_mappings)`，仅可编辑 value，不可增删 key

---

## 三、数据模型

### 3.1 `tags` 表 — 全局默认

```
key              | value
-----------------|----------------------------------------------
sheet_mappings   | {"recharge": "充值表", "received_accounts": "已接账户明细"}
```

仅 admin/developer 保存时写入内置 key。`my_dashboard` 不在此处（value 是每用户私有的）。

### 3.2 `config` 表 — 用户私有覆盖

```
key                         | value
----------------------------|----------------------------------------------
sheet_mappings_{user_id}    | {"received_accounts": "我的户", "my_dashboard": "张三的看板"}
```

所有用户保存时写入全部映射 key-value。读取时覆盖全局值。

### 3.3 功能注册表

| key | 中文名 | value 来源 |
|---|---|---|
| `recharge` | 充值表 | 全局共享（`tags`） |
| `received_accounts` | 已接账户明细 | 全局共享（`tags`） |
| `my_dashboard` | 我的看板 | 用户私有（`config`） |

### 3.4 读取逻辑（三层叠加）

```python
_BUILTIN_SHEET_DEFAULTS = {
    "recharge": "充值表",
    "received_accounts": "已接账户明细",
    "my_dashboard": "我的看板",
}

# 1. 以内置默认值为底（确保所有 key 始终存在）
mappings = dict(_BUILTIN_SHEET_DEFAULTS)

# 2. 全局 tags 值覆盖
if tags has sheet_mappings:
    mappings.update(json.loads(tags.sheet_mappings))

# 3. 用户私有 config 值覆盖
if user authenticated:
    mappings.update(config.sheet_mappings_{user_id})
```

### 3.5 写入逻辑

```
POST /api/settings/account (JWT required)
  if admin/developer:
    → _BUILTIN_SHEET_MAPPING_KEYS 中的 key → INSERT INTO tags (全局)
  → 全部 key → INSERT INTO config.sheet_mappings_{user_id} (用户私有)
```

> **关键区分**：`_BUILTIN_SHEET_DEFAULTS` 决定哪些 key 展示在 UI 上（读取用），`_BUILTIN_SHEET_MAPPING_KEYS` 决定哪些 key 的 value 写入全局 `tags`（写入用）。`my_dashboard` 在 `_BUILTIN_SHEET_DEFAULTS` 中但**不在** `_BUILTIN_SHEET_MAPPING_KEYS` 中，因此其 value 仅存用户私有 `config`，不会泄漏到全局。

```python
_BUILTIN_SHEET_MAPPING_KEYS = {"recharge", "received_accounts"}  # 写全局的 key
_BUILTIN_SHEET_DEFAULTS = {                                       # 展示兜底（所有 key）
    "recharge": "充值表",
    "received_accounts": "已接账户明细",
    "my_dashboard": "我的看板",
}
```

---

## 四、后端 API

### 4.1 `GET /api/settings/account` — 修改

- 新增 `@jwt_required(optional=True)`
- 响应 `settings.sheet_mappings` 按三层叠加返回
- `recharge_sheet_id` 读取时 `_json.loads` 解码（兼容旧 JSON 编码数据），异常时 fallback 到原始字符串

### 4.2 `POST /api/settings/account` — 修改

- 新增 `@jwt_required()`
- `sheet_mappings` 写入时拆分：内置 key → `tags`（admin 才写），全部 key → `config`（按 user_id）

### 4.3 `GET /api/google-sheets/sheets` — 新增

**认证**：`@jwt_required()`

**查询参数**：`spreadsheet_id`（必填，支持完整 URL 或纯 ID）

**响应**：

```json
{
  "success": true,
  "sheets": [
    {"name": "充值表", "gid": 0, "rowCount": 1000},
    {"name": "Sheet2", "gid": 123456, "rowCount": 500}
  ]
}
```

**错误处理**：

| 情况 | HTTP | 响应 |
|---|---|---|
| spreadsheet_id 为空 | 400 | `"缺少 spreadsheet_id"` |
| API 未配置 | 400 | `"Google Sheets 未配置"` |
| 表格无权访问 | 400 | `"无法访问表格: ..."` |

### 4.4 `append_recharge()` — 修改

函数签名：`append_recharge(service, spreadsheet_id, sheet_name, rows)`

`sheet_name` 由调用方从 `_get_recharge_sheet_name(db)` 获取，不再硬编码 `"充值表"`。空值时回退到 `"充值表"`。

### 4.5 新增辅助函数

```python
_get_recharge_sheet_name(db) -> str   # 从 tags.sheet_mappings 取 recharge 对应 sheet 名
_get_user_sheet_mappings(user_id) -> dict   # 读 config.sheet_mappings_{user_id}
_save_user_sheet_mappings(user_id, mappings) -> None  # 写 config.sheet_mappings_{user_id}
```

---

## 五、前端 UI

### 5.1 SettingsPanel.vue — 充值表配置区

```
📊 充值表配置（仅管理员可见）

Google Sheets（URL 或 ID）:
┌─────────────────────────────────────────┐  [📋 读取工作表]
│ https://docs.google.com/...             │
└─────────────────────────────────────────┘

Sheet 映射:
┌──────────────────┬──────────────────────────────┐
│ 功能              │ Sheet 名称                    │
├──────────────────┼──────────────────────────────┤
│ 充值表            │ [下拉框 ▼ 可搜索/可手动输入]   │
│ 已接账户明细      │ [下拉框 ▼ 可搜索/可手动输入]   │
│ 我的看板          │ [下拉框 ▼ 可搜索/可手动输入]   │
└──────────────────┴──────────────────────────────┘
```

### 5.2 交互细节

1. **「📋 读取工作表」**：提取 spreadsheet ID → 调 `GET /api/google-sheets/sheets` → 填充下拉 options
2. **下拉框**：`el-select` + `filterable` + `allow-create`，API 失败仍可手动输入
3. **映射列表**：`v-for="key in Object.keys(form.sheet_mappings)"`，渲染 `SHEET_MAPPING_META` 中的 label
4. **不可增删**：无新增按钮、无删除按钮，仅可修改已有映射的 value
5. **保存**：spreadsheet ID + sheet_mappings 一起提交

### 5.3 前端常量

```js
const SHEET_MAPPING_META = {
  recharge: { label: '充值表' },
  received_accounts: { label: '已接账户明细' },
  my_dashboard: { label: '我的看板' },
}
```

---

## 六、错误处理

| 情况 | 处理 |
|---|---|
| API 返回 sheet 列表失败 | `ElMessage.error()`，下拉框仍可手动输入 |
| 用户未点击「读取」直接保存 | 手动输入的 sheet 名正常保存 |
| 后端 sheet_mappings 缺失 | 返回 `_BUILTIN_SHEET_DEFAULTS` 兜底 |
| 旧数据缺少新 key | `_BUILTIN_SHEET_DEFAULTS` 补齐 |
| API 未授权 / 未配置 | 返回对应 400 错误 |
| spreadsheet ID 为空时点「读取」 | `ElMessage.warning("请先输入表格链接")` |
| `recharge_sheet_id` 旧数据 JSON 编码 | `_json.loads` 解码，异常 fallback 原始值 |

---

## 七、涉及文件

| 文件 | 操作 | 说明 |
|---|---|---|
| `py/main.py` | 修改 | `account_settings_get/save` 增加 `sheet_mappings` + 三层叠加 + per-user 存储；新增 `GET /api/google-sheets/sheets`；新增辅助函数；5 处 `append_recharge` 调用传入 sheet_name；`recharge_sheet_id` JSON 解码兼容 |
| `py/google_sheets_service.py` | 修改 | `append_recharge()` 增加 `sheet_name` 参数 |
| `frontend/src/views/SettingsPanel.vue` | 修改 | 充值配置区：读取按钮 + 动态下拉框 + 固定映射表（只读编辑，不可增删） |
| `frontend/src/api/google-sheets.js` | 修改 | 新增 `listSheets()` |
| `frontend/src/stores/accounts.js` | 修改 | settings state + loadSettings 增加 `sheet_mappings` |
