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

---

## 实际代码逻辑补充（2026-07-23 审计）

以下内容基于对实际代码（含关键 git 提交）的审计，记录与原始设计的差异及设计文档未覆盖的实现细节。

### 一、`google_sheets_service.py` 函数签名变更

#### 1.1 函数 `get_spreadsheet_title` 更名为 `get_spreadsheet_info`

**设计文档：** `get_spreadsheet_title(service, spreadsheet_id)` 仅返回标题。

**实际代码：** `get_spreadsheet_info(service, spreadsheet_id) -> dict` 返回：
```python
{
    "title": "卡尔202607",
    "operator": "卡尔",
    "year_month": "202607",
    "sheets": [{"name": "Sheet1", "gid": 0, "rowCount": 1000}, ...]
}
```
- 增加了 `sheets` 列表，每个 sheet 含 `rowCount`（避免后续再调用 API 取行数）
- 增加 `operator`、`year_month` 解析字段

**提交：** `251a70c`

#### 1.2 函数 `upsert_zuobiao` 新增 `info` 和 `operator_name` 参数

**设计文档签名：**
```python
def upsert_zuobiao(service, spreadsheet_id, sheet_gid, rows,
                   product_name, region, report_date,
                   sales_person, agency_ratio):
```

**实际代码签名：**
```python
def upsert_zuobiao(service, info: dict, spreadsheet_id: str, sheet_gid: str,
                   rows: list, product_name: str, region: str, report_date: str,
                   sales_person: str, agency_ratio, operator_name: str) -> dict:
```

**差异：**
- 新增 `info` 参数（`get_spreadsheet_info` 的返回值）：调用方先获取一次 info，传入 `upsert_zuobiao`，避免函数内部重复调用 API
- 新增 `operator_name` 参数：由调用方从 `info["operator"]` 提取后传入，解耦函数内部对 info 的依赖
- 返回值明确为 `{"updated": int, "inserted": int}`

**提交：** `251a70c`

### 二、标题运营名解析正则变更

**设计文档：** `^(\D+)(\d{6})$` — 只匹配纯 6 位数字年月（如 `"202607"`）

**实际代码：** `r'^(\D+)(\d{4}\.?\d{2})$'` — 同时支持 `"202607"` 和 `"2026.07"` 两种格式
- `\.?` 可选小数点，兼容 Google Sheets 自动格式化日期导致的点号

**提交：** `ae64329`

### 三、`last_row` 计算演进（三次修复）

#### 3.1 修复一：跳过 API 返回的空行（`f8c2676`）

**设计文档：** 使用 `len(existing)` 作为 last_row，认为 API 返回行数就是有效行数。

**实际代码：** 从末尾向前遍历，找到第一个任意列有内容的行：
```python
last_row = 0
for i in range(len(existing) - 1, -1, -1):
    if any(cell for cell in existing[i] if cell):
        last_row = i + 1  # 1-based
        break
```
**原因：** API 返回的 `values` 可能包含末尾全空行，`len(existing)` 会高估最后一行位置。

#### 3.2 修复二：只看 A-J 列，忽略 M/N 公式列（`22e8770`）

**设计文档：** 未考虑 M/N 列含公式默认值。

**实际代码：**
```python
if any(row[j] for j in range(min(10, len(row))) if row[j]):
    last_row = i + 1
```
**原因：** M 列（`=F*L`）和 N 列（`=F-K+M`）在空白行上也会被 Google Sheets 自动填充公式，导致 `any()` 判为有内容。改为只看 A-J 列（索引 0-9）避免误判。

#### 3.3 新增：记录最后一行的日期（`008032c`）

**设计文档：** 未提及。

**实际代码：**
```python
last_date = ""
for i in range(len(existing) - 1, -1, -1):
    row = existing[i]
    if any(row[j] for j in range(min(10, len(row))) if row[j]):
        last_row = i + 1
        last_date = (row[0] or "").strip() if len(row) > 0 else ""
        break
```
**用途：** 追加新行时判断是否与前一行日期不同，不同则空一行（见下文第七节）。

### 四、Upsert 写入策略：`INSERT_ROWS` 改为精确 `update`（`c374809`）

**设计文档：** 使用 `spreadsheets().values().append()` + `insertDataOption="INSERT_ROWS"` 追加。

**实际代码：**
```python
start = last_row + 1
end = last_row + len(appends)
service.spreadsheets().values().update(
    spreadsheetId=spreadsheet_id,
    range=f"'{sheet_name}'!A{start}:N{end}",
    valueInputOption="USER_ENTERED",
    body={"values": appends},
).execute()
```
**原因：**
- `INSERT_ROWS` 会在每个追加行后插入空行，导致列偏移和重复数据
- 改用精确范围的 `update`，先确保行数足够（`appendDimension` 扩充），再精确写入指定区域

**相关改进：** 扩充行数只在 `end > sheet_rows` 时才触发 `appendDimension`，避免不必要的 API 调用。

### 五、批量更新优化（`251a70c`）

**设计文档：** 逐行调用 `values().update()` 更新已匹配的行。

**实际代码：** 使用单次 `values().batchUpdate()`：
```python
if updates:
    data = []
    for row_idx, row_data in updates:
        data.append({
            "range": f"'{sheet_name}'!A{row_idx + 1}:N{row_idx + 1}",
            "values": [row_data],
        })
    service.spreadsheets().values().batchUpdate(
        spreadsheetId=spreadsheet_id,
        body={"valueInputOption": "USER_ENTERED", "data": data},
    ).execute()
```
**效果：** 当匹配到多行更新时，从 N 次 API 调用降为 1 次。

### 六、养户行处理机制（`d23492b` + `f98901e`）

**设计文档：** 未涉及养户概念，所有行统一填入产品信息。

**实际代码：** `upsert_zuobiao` 构建行时检查 `row.get("is_yanghu", False)`：
```python
is_yanghu = row.get("is_yanghu", False)
g_val = "养户" if is_yanghu else product_name       # G列
h_val = "止戈" if is_yanghu else (sales_person or "") # H列
l_val = "0%" if is_yanghu else percent_str          # L列
```

养户行的三处覆盖：
| 列 | 普通行 | 养户行 |
|---|---|---|
| G（客户名称） | 产品名 | `"养户"` |
| H（商务） | 产品的 sales_person | `"止戈"` |
| L（代投比例） | `"6%"` | `"0%"` |

**前端关键词匹配（`d23492b`）：**
- `ToolkitView.vue` 新增 `zbYanghuKeywords` 多选输入框（`el-select` + `multiple + filterable + allow-create`）
- 关键词持久化到 `localStorage`（key: `zb_yanghu_keywords`），默认值：`['养户', 'Website traffic-Search', 'Campaign #1']`
- 发送前对 `zbZuobiao` 每一行做关键词匹配：`campaign.toLowerCase().includes(kw.toLowerCase())`
- 命中关键词的行自动打上 `is_yanghu: true`
- `zbYanghu` 复选框（全部标记为养户）和关键词匹配是 **OR** 关系：`zbYanghu.value || keywords.some(...)`

**提交：** `d23492b`（关键词匹配）、`f98901e`（L列填 0%）

### 七、不同日期自动空行（`008032c`）

**设计文档：** 未提及。

**实际代码：**
```python
start = last_row + 1
# 不同日期之间空一行
if last_date and last_date != (report_date or "").strip():
    start += 1
end = start + len(appends) - 1
```
**行为：** 当新写入的日期与表中最后一行日期不同时，自动在中间插入一个空行作为视觉分隔。

### 八、M/N 列自动填入公式

**设计文档：** M 列和 N 列标记为"留空"。

**实际代码：** 在更新和追加时均填入公式：
```python
# 更新
row_data[12] = f"=F{row_num}*L{row_num}"     # M = 报给客户 × 代投比例
row_data[13] = f"=F{row_num}-K{row_num}+M{row_num}"  # N = 报给客户 - 平台实际 + 代投费
# 追加
row_data[12] = f"=F{row_num}*L{row_num}"
row_data[13] = f"=F{row_num}-K{row_num}+M{row_num}"
```

### 九、异步后台同步 + 失败重试机制

**设计文档：** 同步写入，直接返回 `{"updated": 3, "inserted": 5}`。

**实际代码：** 三层异步保障：

1. **后台线程执行：** `_sync_sheets_background(sync_fn, on_fail_fn)` 将 Sheets 写入放入 daemon 线程，API 立即返回 `{"success": True, "sheets_status": "syncing", "db_saved": N}`

2. **30 秒自动重试：** 失败后等 30 秒自动重试一次，状态流转：
   ```
   failed → (30s后) → synced（成功）
                    → retry_failed（二次失败，需手动操作）
   ```

3. **失败记录持久化：** `sheets_sync_log` 表记录失败行数据（`rows_json` 存完整 14 列数据），支持：
   - 前端轮询 `/api/google-sheets/sync-status` 展示失败行
   - 前端手动重试 `/api/google-sheets/retry-sync`（从 `ad_reports` 表重新取数据写入）
   - 成功后自动删除日志记录

**涉及文件：**
- `py/main.py`：`_sync_sheets_background()` 函数、`/api/google-sheets/sync-status`、`/api/google-sheets/retry-sync`
- `py/database.py`：`sheets_sync_log` 表
- `frontend/src/views/ToolkitView.vue`：`zbSyncStatus`、轮询、倒计时、展示失败行

### 十、API 同时保存数据库

**设计文档：** API 仅写入 Google Sheets。

**实际代码：** `zbUpdateSheet` 前端调用时同时传 `rows` 和 `raw_rows`：
```javascript
const res = await googleSheetsApi.updateZuobiao({
    product_name, region, report_date,
    rows: taggedRows,      // 精简做表行（A/C/D/E/J列 + is_yanghu 标记）
    raw_rows: taggedRaw,   // 完整行（含 impressions/clicks/installs 等）
    sales_person, agency_ratio,
})
```

后端 `google_sheets_update_zuobiao()` 处理流程：
1. **先写数据库（同步）：** 过滤掉 `is_yanghu=True` 的行，按 `(report_date, user_id, product_name, customer_id, campaign)` 去重后 upsert 到 `ad_reports` 表
2. **后台写 Sheets（异步）：** 所有行（含养户）写入 Google Sheets

**数据库写入细节：**
- 调用 `_auto_link_mcc_and_accounts()` 自动关联 MCC 和账户
- 以 `(user_id, product_name, account, customer_id, campaign, report_date)` 为唯一键
- 存在则 UPDATE（覆盖 cost/impressions/clicks/installs/in_app_actions/cost_per_in_app/region）
- 不存在则 INSERT

### 十一、产品校验：包系列名匹配

**设计文档：** 无此逻辑。

**实际代码：**
```python
pkgs = db.execute(
    "SELECT pkg.series_name FROM packages pkg "
    "JOIN products prod ON pkg.product_id = prod.id "
    "WHERE prod.product_name=? AND (pkg.status IS NULL OR pkg.status='' OR pkg.status='0')",
    (product_name,)
).fetchall()
pkg_names = set((p["series_name"] or "").strip() for p in pkgs)
if pkg_names:
    campaigns = set((r.get("campaign") or "").strip() for r in rows)
    matched = pkg_names & campaigns
    if not matched:
        has_yanghu = any(r.get("is_yanghu") for r in rows)
        if not has_yanghu:
            return error("产品选择有误！包系列与数据中的广告系列不匹配")
```
**逻辑：** 如果数据中的广告系列名没有匹配到产品的包系列名，且没有养户行，则报错阻止写入。有养户行时放行（纯养户数据场景）。

**提交：** `ae64329`（养户校验放宽）

### 十二、前端：`sales_person` 从 `el-input` 变为 `el-select`

**设计文档：** 商务字段为 `el-input`（纯文本输入）。

**实际代码（`ProductModal.vue`）：**
```html
<el-select v-model="form.sales_person" filterable allow-create clearable
    placeholder="选择或输入商务人员" style="width:100%;">
    <el-option v-for="sp in salesPersonOptions" :key="sp" :label="sp" :value="sp" />
</el-select>
```
- 数据源：`accountStore.settings.sales_persons`（从 `/api/accounts/settings` 获取）
- 支持下拉选择已有商务 + 自由输入新商务（`allow-create`）

### 十三、前端：「更新你的表格」按钮可见条件

**设计文档：**
```
选择了产品 && zbRaw.length > 0 && !zbIncludeCampaignId && !zbYanghu
```

**实际代码：**
```html
<el-button v-if="zbSelectedProduct && zbRaw.length" type="warning"
    @click="zbUpdateSheet" :loading="zbUpdatingSheet">📊 更新你的表格</el-button>
```
**差异：** 实际代码未检查 `!zbIncludeCampaignId && !zbYanghu`。勾选了"包含广告系列ID"或"养户"时按钮仍然可见并可点击。这是因为 `zbUpdateSheet` 内部已处理养户标记逻辑，且做表数据生成（`zbZuobiao`）时已按解析模式筛选。但设计文档中的条件更保守，建议评估是否需要恢复此约束。

### 十四、前端：「保存到数据库」独立按钮未实现

**设计文档：** 按钮区有四个按钮，包含「💾 保存到数据库」（打开简化弹窗）。

**实际代码：** 按钮区只有三个按钮：
- 「🚀 一键解析并生成所有报表」
- 「📥 导出全部为 Excel」
- 「📊 更新你的表格」

"保存到数据库"功能已嵌入 `zbUpdateSheet`（即"更新你的表格"按钮），同步完成 DB 保存 + Sheets 写入。简化的保存弹窗（`zbSaveDialogVisible`）代码存在但未被触发——弹窗内容展示了只读产品/地区/日期标签和待保存数据表格，遵循了设计文档的简化方案，只是缺少一个入口按钮。建议补充或移除未使用代码。

### 十五、格式化细节

| 项目 | 设计文档 | 实际代码 |
|---|---|---|
| D列格式 | "强制文本格式" | `numberFormat: {"type": "TEXT"}` — 一致 |
| E列格式 | "强制数字格式" | `numberFormat: {"type": "NUMBER", "pattern": "#,##0.00"}` — 增加了千分位+两位小数 |
| 格式化范围 | 未指定 | 仅对新写入的行（`start-1` 到 `end`），不重复格式化已有行 |
| L列格式 | "百分比文本 `6%`" | `f"{int(agency_ratio)}%"` — 整数的百分比文本 |

### 十六、后端公共函数提取（`251a70c`）

**`_get_user_sheets_config(user_id)`：**
- 同时被 `GET /api/config/google-sheets` 和 `POST /api/google-sheets/update-zuobiao` 复用
- 自动处理激活表格选择（优先激活标记 → 第一个表格 → 全局默认回退）
- 全局回退兼容旧单表配置（`_GOOGLE_SHEETS_CONFIG["spreadsheet_id"]`）

### 十七、未在设计文档中提及的新增文件/接口

| 文件/接口 | 说明 |
|---|---|
| `GET /api/google-sheets/sync-status?product_name=xxx` | 查询 Sheets 同步失败记录（含行数据） |
| `POST /api/google-sheets/retry-sync` | 手动重试失败同步（从 ad_reports 重新取数据） |
| `py/main.py` → `_sync_sheets_background()` | 后台线程 + 30s 重试 |
| `py/database.py` → `sheets_sync_log` 表 | 同步失败日志持久化 |
| 数据库自动迁移 `sales_person`/`agency_ratio` | `database.py` → `_ensure_columns()` 幂等添加（不再依赖首次运行 ALTER） |

### 十八、数据流完整时序

```
用户点击「📊 更新你的表格」
  │
  ├─ 前端 ToolkitView.vue:
  │   1. 关键词匹配行打 is_yanghu 标记
  │   2. 调用 POST /api/google-sheets/update-zuobiao
  │      {rows: taggedRows, raw_rows: taggedRaw, ...}
  │
  ├─ 后端 main.py google_sheets_update_zuobiao():
  │   1. 校验产品名非空、数据非空
  │   2. 校验包系列名匹配（有养户行则跳过）
  │   3. ── 同步阶段 ──
  │      a. 过滤 out non-yanghu 行 → raw_rows
  │      b. 写 ad_reports 表（upsert）
  │      c. 调用 _auto_link_mcc_and_accounts()
  │      d. 返回 db_saved 数量给前端
  │   4. ── 异步阶段 ──
  │      a. 启动后台线程 _sync_sheets_background()
  │      b. 线程内：build_service → get_spreadsheet_info → upsert_zuobiao
  │      c. 失败 → 30s 后重试一次 → 仍失败则记入 sheets_sync_log
  │      d. 成功 → 删除 sheets_sync_log 记录
  │   5. 前端立即收到 {success: true, sheets_status: "syncing", db_saved: N}
  │
  └─ 前端轮询 sync-status:
      每 3s 检查 → 无记录=成功 → 有失败记录→展示警告+自动重试倒计时
```
