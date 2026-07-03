# 数据管理 & 做表数据聚合 — 设计文档

> 日期：2026-07-04
> 关联：[多维分析与 AI 智能解读设计文档](2026-07-03-multi-dimension-analysis-design.md)

## 1. 需求描述

当前多维分析的 ad_reports 数据保存存在以下问题：

1. **保存不做聚合**：ToolkitView 粘贴清洗后的 raw 数据逐行保存，去重策略是"重复直接跳过"而非累加。同一天、同产品、同账号、同广告系列的多条数据应该 SUM 合并。
2. **无法编辑已保存数据**：保存后只能通过 API 删除，无法修改字段值。
3. **无独立数据管理页**：已保存的数据没有集中查看、搜索、筛选、编辑、删除、导出的管理界面。

本次新增"数据管理"独立页面，并改造保存逻辑为聚合累加（做表数据）。

## 2. 核心原则

- **做表聚合优先**：保存时按 `(report_date + product_name + account + customer_id + campaign)` 维度聚合所有数值字段（SUM），和 ToolkitView 中 `zuobiao` 的聚合逻辑一致
- **纯增量**：新增页面和 API，不修改现有仪表盘/趋势/对比/多维分析的分析逻辑
- **复用现有模式**：编辑/删除/分页/筛选复用现有 API 和组件模式

## 3. 后端设计

### 3.1 改造：`POST /api/ad-reports/save`（聚合保存）

**文件**：`py/main.py` — `ad_reports_save()` 函数

**改动内容**：在现有插入逻辑之前，增加聚合步骤

```python
# 聚合逻辑（新增）
# 按 (report_date, product_name, account, customer_id, campaign) 分组
# 每组内 SUM(cost, impressions, clicks, installs, in_app_actions)
aggregated = {}
for row in rows:
    key = (report_date, product_name, row.get('account', ''), 
           row.get('customerId', ''), row.get('campaign', ''))
    if key not in aggregated:
        aggregated[key] = {**row}
    else:
        existing = aggregated[key]
        existing['cost'] = float(existing.get('cost', 0)) + float(row.get('cost', 0))
        existing['impressions'] = int(existing.get('impressions', 0)) + int(row.get('impressions', 0))
        existing['clicks'] = int(existing.get('clicks', 0)) + int(row.get('clicks', 0))
        existing['installs'] = float(existing.get('installs', 0)) + float(row.get('installs', 0))
        existing['in_app_actions'] = float(existing.get('in_app_actions', 0)) + float(row.get('in_app_actions', 0))

# 聚合后的 rows 替换原来的 rows
rows = list(aggregated.values())
```

**upsert 逻辑**（替换原有"跳过重复"）：

```python
# 对每条聚合后的 row：
# 1. 查是否存在同维度记录
# 2. 存在 → UPDATE，数值字段累加
# 3. 不存在 → INSERT
```

请求/响应格式不变，向前兼容。

### 3.2 新增：`PUT /api/ad-reports/<id>`（编辑单条）

**权限**：仅允许编辑自己的数据（`user_id` 校验）

**请求体**（所有字段可选，传了就更新）：
```json
{
  "product_name": "xxx",
  "report_date": "2026-07-03",
  "account": "acc1",
  "customer_id": "123-456-7890",
  "campaign": "cmp1",
  "cost": 150,
  "impressions": 5000,
  "clicks": 200,
  "installs": 50,
  "in_app_actions": 30,
  "region": "US"
}
```

**返回**：`{ "success": true }`

### 3.3 新增：`POST /api/ad-reports/batch-delete`（批量删除）

**请求体**：
```json
{ "ids": [1, 2, 3] }
```

**返回**：`{ "success": true, "deleted": 3 }`

**权限**：仅允许删除自己的数据

### 3.4 新增：`GET /api/ad-reports/export`（导出 CSV）

**参数**：同 `GET /api/ad-reports/list`（`product_name`、`from_date`、`to_date`、`search`）

**返回**：`Content-Type: text/csv`，`Content-Disposition: attachment; filename=ad_reports_export.csv`

**CSV 列**：产品名, 日期, 地区, 账户名, 客户ID, 广告系列, 花费, 展示, 点击, 安装, 应用内操作

### 3.5 改造：`GET /api/ad-reports/list`（增加搜索参数）

**新增参数**：
| 参数 | 类型 | 说明 |
|------|------|------|
| `search` | string | 模糊匹配 `account`、`campaign`、`customer_id` |

**SQL 改动**：WHERE 子句增加 `AND (account LIKE '%search%' OR campaign LIKE '%search%' OR customer_id LIKE '%search%')`

### 3.6 数据库改动

#### 去重索引降级

将 `UNIQUE INDEX idx_ad_reports_dedup` 改为普通 `INDEX`：

```sql
-- 迁移脚本
DROP INDEX IF EXISTS idx_ad_reports_dedup;
CREATE INDEX IF NOT EXISTS idx_ad_reports_dedup 
ON ad_reports(user_id, product_name, customer_id, campaign, report_date);
```

**迁移标记**：`migrated_ad_reports_dedup_v3`

#### 表结构不变

`ad_reports` 表字段已满足所有需求，无需修改。

## 4. 前端设计

### 4.1 路由和导航

**路由注册**（`frontend/src/router/index.js`）：
```js
{ 
  path: '/data-manage', 
  name: 'DataManage', 
  component: () => import('@/views/DataManageView.vue'), 
  meta: { title: '数据管理', requiresAuth: true } 
}
```

**左侧导航**：在"数据分析"下方增加"数据管理"菜单项。

### 4.2 页面布局

```
┌─────────────────────────────────────────────────────────┐
│  📋 数据管理                                             │
│                                                          │
│  筛选栏                                                  │
│  产品: [全部 ▼]  日期: [2026-07-01] ~ [2026-07-04]       │
│  🔍 搜索: [按账户/系列/客户ID搜索...]                      │
│                                                          │
│  [🔄 刷新]  [📥 导出CSV]  [➕ 新增数据]  [🗑 批量删除]     │
│  {已选 X 条}                                             │
├─────────────────────────────────────────────────────────┤
│                                                          │
│  ☐  产品    日期      账户    客户ID     系列    花费 ... │
│  ☐  xxx   07-03     acc1   123-456    cmp1   100   ... │
│  ☐  xxx   07-03     acc2   789-012    cmp2   200   ... │
│  ☐  ...                                                 │
│                                                          │
│                              每页 [20] 条   1 2 3 ... >  │
└─────────────────────────────────────────────────────────┘
```

### 4.3 表格列定义

| 列 | 字段 | 宽度 | 排序 | 说明 |
|------|------|------|------|------|
| ☐ | — | 40 | — | 多选 |
| 产品 | `product_name` | 120 | ✓ | |
| 日期 | `report_date` | 110 | ✓ | |
| 地区 | `region` | 80 | ✓ | |
| 账户 | `account` | 120 | ✓ | |
| 客户ID | `customer_id` | 130 | ✓ | |
| 广告系列 | `campaign` | 150 | ✓ | |
| 花费 | `cost` | 100 | ✓ | 右对齐，$ 格式 |
| 展示 | `impressions` | 100 | ✓ | 千分位 |
| 点击 | `clicks` | 80 | ✓ | 千分位 |
| 安装 | `installs` | 80 | ✓ | |
| 应用内操作 | `in_app_actions` | 100 | ✓ | |
| 操作 | — | 120 | — | 编辑 / 删除 |

### 4.4 交互逻辑

| 功能 | 触发器 | 行为 |
|------|--------|------|
| **加载数据** | 页面挂载 / 筛选变化 / 刷新按钮 | GET `/api/ad-reports/list` → 渲染表格 |
| **搜索** | el-input + debounce 300ms | 传 `search` 参数重新加载 |
| **分页** | el-pagination 变化 | 传 `page` / `page_size` 重新加载 |
| **排序** | 点击列头 | 传 `sort_by` / `sort_order` → 后端排序（或前端排序） |
| **编辑** | 行尾编辑按钮 | 打开编辑弹窗（el-dialog），预填当前值 → 保存 → PUT `/api/ad-reports/<id>` → 刷新 |
| **删除** | 行尾删除按钮 | el-popconfirm → 确认 → DELETE `/api/ad-reports/<id>` → 刷新 |
| **批量删除** | 勾选 + 批量删除按钮 | 确认弹窗 → POST `/api/ad-reports/batch-delete` → 清空勾选 → 刷新 |
| **导出** | 导出按钮 | 按当前筛选条件 GET `/api/ad-reports/export` → 下载 CSV |
| **新增** | 新增按钮 | 打开新增弹窗（空白表单）→ 填写 → POST `/api/ad-reports/save` → 刷新 |
| **错误处理** | 任何 API 调用失败 | ElMessage.error 提示，不关闭弹窗 |

### 4.5 编辑/新增弹窗

```
┌─────────────────────────────────┐
│  编辑数据 / 新增数据              │
│                                  │
│  产品名:  [____________] *必填   │
│  日期:    [2026-07-03 📅] *必填  │
│  地区:    [US ____________]      │
│  账户名:  [____________]         │
│  客户ID:  [____________]         │
│  广告系列: [____________]         │
│  花费:    [____________]         │
│  展示:    [____________]         │
│  点击:    [____________]         │
│  安装:    [____________]         │
│  应用内操作: [____________]      │
│                                  │
│         [取消]    [保存]         │
└─────────────────────────────────┘
```

- 编辑模式：预填当前数据库值
- 新增模式：空白表单，`product_name` 和 `report_date` 必填
- 数值字段默认 0
- 保存前做基本校验（必填项、数值格式）

### 4.6 前端排序策略

采用**前端排序**（数据量通常不大），避免修改 list API。表格列点击排序时对当前页数据做 `sort()`。

### 4.7 新增/修改文件清单

| 文件 | 变更类型 | 说明 |
|------|---------|------|
| `py/main.py` | 修改 | 改造 save 增加聚合+upsert；新增 PUT/批量删除/导出端点；list 增加 search 参数 |
| `py/database.py` | 修改 | 去重索引迁移 (UNIQUE → 普通 INDEX) |
| `frontend/src/views/DataManageView.vue` | **新建** | 数据管理页面主组件 |
| `frontend/src/api/reports.js` | 修改 | 新增 `updateReport()`, `batchDeleteReports()`, `exportReports()` |
| `frontend/src/router/index.js` | 修改 | 新增 `/data-manage` 路由 |
| `py/tests/test_ad_reports.py` | 修改 | 新增聚合保存、编辑、批量删除、导出测试 |

## 5. 错误处理

| 场景 | 处理 |
|------|------|
| 编辑时记录已被他人删除 | 返回 404，前端提示"该记录不存在或已被删除" |
| 批量删除包含他人数据 | 后端校验 `user_id`，只删除自己的数据，返回实际删除数 |
| 编辑必填字段为空 | 前端校验拦截，不发送请求 |
| 数值字段填非数字 | 前端校验 + 后端类型转换兜底 |
| 导出数据为空 | 返回含表头的空 CSV |

## 6. 验证方式

1. **聚合保存**：粘贴含同一天同产品同账号同系列多条数据 → 确认数据库只保存一条聚合后的记录
2. **upsert**：再次保存同维度数据 → 确认数值累加而非覆盖
3. **数据管理页加载**：左侧导航进入 → 表格正确显示所有已保存数据
4. **搜索筛选**：输入关键词 / 选择产品 / 选择日期范围 → 表格正确过滤
5. **编辑**：点击编辑 → 修改字段 → 保存 → 表格刷新显示新值
6. **删除**：单条删除 + 批量删除均正常
7. **导出 CSV**：下载文件内容与当前筛选结果一致
8. **新增**：空白表单填写 → 保存 → 表格出现新记录
9. **向后兼容**：现有仪表盘/趋势/对比/多维分析功能不受影响
