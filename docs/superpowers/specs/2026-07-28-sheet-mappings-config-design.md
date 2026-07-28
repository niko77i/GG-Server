# Sheet 映射动态配置 — 设计文档

## 一、需求描述

当前充值功能的 Google Sheets sheet 名称是硬编码的 `"充值表"`（`google_sheets_service.py` 第 279 行）。需要改为：

1. **动态读取**：输入 spreadsheet ID 后可读取该表格中所有 sheet 名称，前端下拉框展示
2. **可手动输入**：下拉框支持自由输入（API 读取失败时兜底）
3. **通用映射表**：用功能 key → sheet 名称的映射结构，后续新增功能只需改后端注册表，前端自动渲染
4. **向后兼容**：老数据没有 `sheet_mappings` 时默认 `{"recharge": "充值表"}`

---

## 二、方案选择

选择**方案 B：sheet 映射表**。

- 在 `tags` 表中新增一条 `key="sheet_mappings"`，value 为 JSON 对象
- 每个功能 key 映射到对应的 sheet 名称
- 前端用动态列表渲染，新增功能时无需改前端

---

## 三、数据模型

### 3.1 存储

`tags` 表新增一行：

```
key              | value
-----------------|---------------------------
sheet_mappings   | {"recharge": "充值表"}
```

### 3.2 功能注册表（后端定义）

| key | 标签 | 说明 |
|---|---|---|
| `recharge` | 充值表 | 充值记录写入目标 sheet |

后续新增功能时在此表加一行即可，前端自动出现对应的映射行。

### 3.3 默认值

当 `sheet_mappings` 不存在或为空时，默认 `{"recharge": "充值表"}`，保持向后兼容。

---

## 四、后端 API

### 4.1 `GET /api/settings/account` — 修改

响应 `settings` 中新增 `sheet_mappings` 字段：

```json
{
  "success": true,
  "settings": {
    "account_statuses": ["存活", "死亡"],
    "account_agents": [],
    "mcc_levels": [],
    "sales_persons": [],
    "recharge_sheet_id": "abc123",
    "sheet_mappings": {
      "recharge": "充值表"
    }
  }
}
```

默认值处理：如果 `tags` 表中无 `sheet_mappings`，返回 `{"recharge": "充值表"}`。

### 4.2 `POST /api/settings/account` — 修改

请求体新增可选字段 `sheet_mappings`，与现有字段一起 `INSERT OR REPLACE` 到 `tags` 表。

### 4.3 `GET /api/google-sheets/sheets` — 新增

**认证**：`@jwt_required()`

**查询参数**：`spreadsheet_id`（必填）

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

**实现**：复用 `google_sheets_service.get_spreadsheet_info()`，只返回 `sheets` 字段。

**错误处理**：

| 情况 | HTTP | 响应 |
|---|---|---|
| spreadsheet_id 为空 | 400 | `{"success": false, "error": "缺少 spreadsheet_id"}` |
| API 未配置 | 400 | `{"success": false, "error": "Google Sheets 未配置"}` |
| 表格无权访问 | 400 | `{"success": false, "error": "无法访问表格: ..."}` |

### 4.4 `append_recharge()` — 修改

`google_sheets_service.py` 中的函数签名变更：

```python
# 旧
def append_recharge(service, spreadsheet_id: str, rows: list) -> dict:

# 新
def append_recharge(service, spreadsheet_id: str, sheet_name: str, rows: list) -> dict:
```

sheet 名由调用方从 `sheet_mappings` 中取 `recharge` 对应的值传入，不再硬编码。

**向后兼容**：如果传入的 `sheet_name` 为空，回退到 `"充值表"`。

### 4.5 调用方修改

`py/main.py` 中所有调用 `append_recharge()` 的位置（共 5 处），需要：
1. 从 `tags` 表读取 `sheet_mappings`
2. 取 `mappings.get("recharge", "充值表")` 作为 sheet 名
3. 传入 `append_recharge()`

---

## 五、前端 UI

### 5.1 SettingsPanel.vue — 充值配置区改造

**改造前**（当前）：

```
Google Sheets（URL 或 ID）: [________________]  [💾 保存]
```

**改造后**：

```
📊 充值表配置（仅管理员可见）

Google Sheets（URL 或 ID）:
┌─────────────────────────────────────────┐  [📋 读取工作表]
│ https://docs.google.com/...             │
└─────────────────────────────────────────┘

Sheet 映射:
┌────────────┬──────────────────────────────┐
│ 功能        │ Sheet 名称                    │
├────────────┼──────────────────────────────┤
│ 充值表      │ [下拉框 ▼ 可搜索/可手动输入]   │
└────────────┴──────────────────────────────┘
```

### 5.2 交互细节

1. **「📋 读取工作表」按钮**：
   - 从输入框中提取 spreadsheet ID（复用现有正则）
   - 调用 `GET /api/google-sheets/sheets?spreadsheet_id=xxx`
   - 成功 → 将返回的 sheet 名列表填入下拉框的 options
   - 失败 → `ElMessage.error()` 提示，下拉框保持可手动输入
   - 按钮展示 loading 状态

2. **Sheet 下拉框**：
   - 使用 `el-select` + `filterable` + `allow-create`（支持搜索和手动输入）
   - 如果 API 未调用或失败，options 为空，用户直接手动输入
   - 选中的值绑定到 `form.sheet_mappings.recharge`

3. **映射表渲染**：
   - 使用 `v-for` 遍历功能注册表，动态渲染每一行
   - 功能注册表在前端定义为常量：
     ```js
     const SHEET_MAPPING_META = {
       recharge: { label: '充值表', description: '充值记录写入目标 sheet' },
     }
     ```
   - 后续新增功能只需在此常量加一行，UI 自动出现新行

4. **保存逻辑**：
   - spreadsheet ID 和 sheet_mappings 一起通过 `POST /api/settings/account` 提交
   - `sheet_mappings` 以 JSON 对象格式提交

### 5.3 API 层新增

`frontend/src/api/google-sheets.js` 新增方法：

```js
listSheets(spreadsheetId) {
  return api.get('/google-sheets/sheets', { params: { spreadsheet_id: spreadsheetId } })
}
```

### 5.4 Store 改动

`frontend/src/stores/accounts.js`：
- `state.settings` 增加 `sheet_mappings: { recharge: '充值表' }`
- `saveSettings` 无需改动（透传 body）

---

## 六、错误处理

| 情况 | 处理 |
|---|---|
| API 返回 sheet 列表失败 | `ElMessage.error("读取工作表失败: ...")`，下拉框仍可手动输入 |
| 用户未点击「读取」直接保存 | 手动输入的 sheet 名正常保存 |
| 后端 sheet_mappings 缺失 | 默认 `{"recharge": "充值表"}` |
| API 未授权 / 未配置 | 同现有错误处理，返回对应错误信息 |
| spreadsheet ID 为空时点「读取」 | `ElMessage.warning("请先输入表格链接")` |

---

## 七、涉及文件汇总

| 文件 | 操作 | 说明 |
|---|---|---|
| `py/main.py` | 修改 | `account_settings_get/save` 增加 `sheet_mappings`；新增 `GET /api/google-sheets/sheets`；5 处 `append_recharge` 调用改为传入 sheet_name |
| `py/google_sheets_service.py` | 修改 | `append_recharge()` 增加 `sheet_name` 参数，去掉硬编码 |
| `frontend/src/views/SettingsPanel.vue` | 修改 | 充值配置区改造为 spreadsheet ID + 读取按钮 + 映射表 |
| `frontend/src/api/google-sheets.js` | 修改 | 新增 `listSheets()` |
| `frontend/src/stores/accounts.js` | 修改 | settings state 增加 `sheet_mappings` |
