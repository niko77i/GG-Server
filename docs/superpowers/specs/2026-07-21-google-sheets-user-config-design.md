# Google Sheets 用户配置页面 — 设计文档

## 需求描述

1. **配置页面**：让每个用户保存自己的 Google 在线表格 ID
2. **用户隔离**：每个用户有自己的表格配置，互不干扰
3. **与做表数据关联**：表格列与 ToolkitView「做表数据」字段有固定映射关系

用户提供的示例表格：
- URL: `https://docs.google.com/spreadsheets/d/13b-KX2LNisoVwO0s3fT0RqzIyu_Ngy-AgDQRqV1AsQY/edit?gid=0#gid=0`
- 列映射：`账号名称→账号` / `广告账户id→客户ID` / `账号消耗→费用` / `渠道号→广告系列`

## 技术方案

### 存储方案

遵循项目现有的 `config` 表 key-prefix 模式（参照 `ai_analysis_{user_id}`），使用 key `google_sheets_{user_id}`，value 为 JSON 字符串。

### 存储数据结构

```json
{
  "spreadsheet_id": "13b-KX2LNisoVwO0s3fT0RqzIyu_Ngy-AgDQRqV1AsQY",
  "spreadsheet_name": "",
  "sheet_gid": "0"
}
```

### 列映射（固定，仅供参考）

| Google Sheets 列 | 做表数据字段 | 说明 |
|---|---|---|
| A: 账号名称 | account（账号） | 广告账户名称 |
| B: 广告账户id | customerId（客户ID） | xxx-xxx-xxxx 格式 |
| C: 账号消耗 | cost（费用） | 美金金额 |
| D: 渠道号 | campaign（广告系列） | 广告系列名称 |

## 涉及的文件

| 文件 | 操作 | 说明 |
|------|------|------|
| `py/main.py` | 修改 | 新增 `GET/POST /api/config/google-sheets` 路由 |
| `frontend/src/api/google-sheets.js` | 修改 | 新增 `getConfig()` / `saveConfig()` 方法 |
| `frontend/src/views/UserProfileView.vue` | 修改 | 新增「Google Sheets 配置」卡片 |

## 后端 API

### GET /api/config/google-sheets
- 认证：`@jwt_required()`
- 返回当前用户的 Google Sheets 配置 JSON
- 用户级未配置时回退到 `config.json` 中的全局 `spreadsheet_id`

### POST /api/config/google-sheets
- 认证：`@jwt_required()`
- 接收 `{ spreadsheet_id, spreadsheet_name, sheet_gid }`
- 写入 `config` 表 key=`google_sheets_{user_id}`

## 前端 UI

在 `UserProfileView.vue` 中新增 `el-card`：
- 表格网址/ID 输入（支持粘贴完整 URL 自动提取）
- 表格名称输入
- 列映射参考表（小号字体）
- 保存按钮

## 扩展预留

后续可在以下位置扩展：
- `py/google_sheets_service.py`：新增 `read_range()`/`write_range()` 从用户配置读取 sheet ID
- `py/main.py`：新增数据同步路由
- `frontend/src/views/ToolkitView.vue`：新增「同步到 Google Sheets」按钮
