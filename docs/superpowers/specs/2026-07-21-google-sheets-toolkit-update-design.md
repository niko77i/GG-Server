# Google Sheets 做表数据自动写入 — 设计文档

> 在 [2026-07-21 Google Sheets 用户配置设计](2026-07-21-google-sheets-user-config-design.md) 基础上扩展。

## 一、需求描述

1. **产品管理新增字段**：商务 (`sales_person`)、代投比例 (`agency_ratio`)，供做表数据写入时使用
2. **ToolkitView 增加产品/日期选择**：解析数据前选好产品和日期，与保存弹窗共享逻辑
3. **「更新你的表格」按钮**：选择产品后可见，点击自动将做表数据 upsert 到用户激活的 Google Sheet
4. **保存弹窗简化**：产品/日期/地区移到外层后，弹窗只展示可编辑的数据表格
5. **表格列映射**：按 14 列（A-N）模板写入，自动填入产品信息

---

## 二、产品管理新增字段

### 数据库变更

```sql
ALTER TABLE products ADD COLUMN sales_person TEXT DEFAULT '';
ALTER TABLE products ADD COLUMN agency_ratio REAL DEFAULT NULL;
```

### 后端变更

**`py/main.py`:**

- `products_create`（第 2296 行）：接收 `sales_person`、`agency_ratio`，写入 INSERT 语句
- `products_update`（第 2353 行）：`_product_fields` 白名单加入 `sales_person`、`agency_ratio`
- `products_list`（第 2123 行）：SELECT `p.*` 自动包含新列，无需改查询
- `/ad-reports/products`（第 5777 行）：返回 `sales_person`、`agency_ratio`，供 ToolkitView 使用

### 前端变更

**`frontend/src/components/ProductModal.vue`:**

- 表单新增两个 `el-form-item`：
  - 「商务」：`el-input`，文本输入
  - 「代投比例」：`el-input`，数字输入（存数字如 `6`）
- `form` 对象新增 `sales_person`、`agency_ratio`
- `init()` 和 `submit()` 适配新字段

---

## 三、Google Sheets 列映射

### 完整映射表

| 列 | 列头 | 数据来源 | 格式 | 说明 |
|---|---|---|---|---|
| A | 日期 | `report_date` | 文本 `YYYY-MM-DD` | 用户选择的日期 |
| B | 运营 | 表格标题解析 → 运营名 | 文本 | 从 spreadsheet title 提取（如"卡尔202607"→"卡尔"） |
| C | 账户名称 | `row.account` | 文本 | 做表数据 |
| D | 广告账户ID | `row.customerId` | **文本**（强制） | 防止 `xxx-xxx-xxxx` 被转数字 |
| E | 账号消耗 | `row.cost` | **数字** | 美金金额 |
| F | 报给客户 | 留空 | — | — |
| G | 客户名称 | `product_name` | 文本 | 产品的产品名 |
| H | 商务 | `sales_person` | 文本 | 产品的商务字段 |
| I | 投放国家 | `region` | 文本 | 产品的地区 |
| J | 渠道号 | `row.campaign` | 文本 | 做表数据 |
| K | 平台实际 | 留空 | — | — |
| L | 代投比例 | `agency_ratio` | **百分比文本** | 数据库存 `6` → 写入 `"6%"` |
| M | 代投费 | 留空 | — | — |
| N | 利润 | 留空 | — | — |

### 表格标题解析

通过 `spreadsheets.get(spreadsheetId)` 获取 `.properties.title`，格式为 `<运营名><年月>`，如 `"卡尔202607"`。

- 正则 `^(\D+)(\d{6})$` 提取运营名和年月
- 提取失败则 B 列留空，不阻塞写入

---

## 四、前端 UI 改动

### ToolkitView.vue — 做表数据区域

```
┌──────────────────────────────────────────────────────────────┐
│ 产品: [下拉搜索框 ▼]  日期: [📅]                              │
│                                                              │
│ ☐ 包含广告系列ID   ☐ 养户                                     │
│ [ 在此粘贴原始数据... ]                                        │
│ [🚀 一键解析] [📥 导出Excel] [💾 保存到数据库] [📊 更新你的表格] │
└──────────────────────────────────────────────────────────────┘
```

**产品下拉 (`el-select` + `filterable`)：**
- 数据源：`/ad-reports/products`（与保存弹窗复用）
- 选中后自动获取产品的 `region`、`sales_person`、`agency_ratio`

**日期选择 (`el-date-picker`)：**
- 默认前一天
- 格式 `YYYY-MM-DD`

**两个按钮（保存到数据库 & 更新你的表格）可见条件一致：**
```
选择了产品 && zbRaw.length > 0 && !zbIncludeCampaignId && !zbYanghu
```

### 保存弹窗简化

```
┌───────────────────────────────────────┐
│  💾 保存做表数据                       │
│                                       │
│  产品: xxx / 地区: xxx / 日期: xxx     │  ← 只读展示，不可编辑
│                                       │
│  📋 待保存数据 (N 条)                   │
│  ┌───────────────────────────────┐    │
│  │ 账号 │ 客户ID │ 费用 │ ... │ 🗑 │    │  ← 行数据可 inline 编辑
│  │ ...                            │    │
│  └───────────────────────────────┘    │
│                                       │
│  [取消]  [💾 保存]                     │
└───────────────────────────────────────┘
```

- 移除产品/地区/日期三个 `el-form-item`
- 改为只读标签展示外层已选值
- 数据表格单元格可编辑（`el-table-column` 内用 `el-input` + cell-edit 或点击编辑）

---

## 五、后端 API

### 新增路由：`POST /api/google-sheets/update-zuobiao`

**认证：** `@jwt_required()`

**请求体：**
```json
{
  "product_name": "xxx",
  "region": "US",
  "report_date": "2026-07-20",
  "rows": [
    {
      "account": "账户名",
      "customerId": "xxx-xxx-xxxx",
      "cost": 123.45,
      "campaign": "广告系列名"
    }
  ]
}
```

**处理流程：**

1. 读取当前用户激活的 Google Sheets 配置（`google_sheets_{user_id}` + `google_sheets_active_{user_id}`）
2. 未配置 → 返回 `{"success": false, "error": "请先在个人中心配置 Google 表格"}`
3. 通过 `spreadsheets.get()` 获取表格标题，解析运营名
4. 从用户产品配置中获取 `sales_person`、`agency_ratio`
5. 读取表格现有全部数据（A-N 列）
6. 以 `(A列日期, D列客户ID, J列渠道号)` 为唯一键做 upsert：
   - **匹配到** → 覆盖该行
   - **未匹配到** → 在同日期行范围下方插入新行；若行不够则 `insertDimension` 扩充
   - **不碰其他日期/产品的数据**
7. 写入格式：
   - D列（广告账户ID）强制文本格式（`setUserEnteredFormat` → `numberFormat: "@"`）
   - E列（账号消耗）强制数字格式
   - L列百分比格式
8. 返回 `{"success": true, "updated": 3, "inserted": 5, "total": 8}`

### `google_sheets_service.py` 新增方法

```python
def get_spreadsheet_title(service, spreadsheet_id):
    """获取表格标题（文件名）。"""
    
def upsert_zuobiao(service, spreadsheet_id, sheet_gid, rows, 
                   product_name, region, report_date,
                   sales_person, agency_ratio):
    """将做表数据 upsert 到 Google Sheets。
    
    以 (日期, 客户ID, 渠道号) 为唯一键，
    匹配到则覆盖，未匹配则插入新行。
    
    Returns: {"updated": int, "inserted": int}
    """
```

---

## 六、错误处理

| 情况 | 处理 |
|---|---|
| 用户未配置 Google Sheets | `"请先在个人中心配置 Google 表格"` |
| Google Sheets API 未授权 | `"Google Sheets 未授权，请联系管理员"` |
| 表格 ID 无效/无权访问 | `"无法访问表格，请检查表格链接"` |
| 做表数据为空 | 前端按钮 disabled |
| 选中「包含广告系列ID」或「养户」 | 按钮隐藏 |
| 表格标题无法解析运营名 | B列留空，正常写入其余数据 |
| 同日期有其他产品数据 | 只在同日期行范围操作，不影响其他产品 |
| 产品无 sales_person/agency_ratio | 留空 |

---

## 七、涉及文件汇总

| 文件 | 操作 | 说明 |
|---|---|---|
| 数据库 `products` 表 | 修改 | 新增 `sales_person`、`agency_ratio` 列 |
| `py/google_sheets_service.py` | 修改 | 新增 `get_spreadsheet_title()`、`upsert_zuobiao()` |
| `py/main.py` | 修改 | 新增 `POST /api/google-sheets/update-zuobiao`；产品 CRUD 适配新字段；`/ad-reports/products` 返回新字段 |
| `frontend/src/api/google-sheets.js` | 修改 | 新增 `updateZuobiao()` |
| `frontend/src/components/ProductModal.vue` | 修改 | 新增商务、代投比例输入框 |
| `frontend/src/views/ToolkitView.vue` | 修改 | 新增产品下拉+日期+「更新你的表格」按钮；弹窗简化 |
