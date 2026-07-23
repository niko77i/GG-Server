# 产品增加"客户"字段 — 设计文档

> 日期：2026-07-03
> 需求：产品增加一个字段"客户"，用于保存当前产品所属客户，也作为标签展示在产品名后面。
> 状态：已实现（实际实现超出原始设计，同步增加了"商务"和"代投比例"字段）

## 需求描述

1. 产品表新增 `customer` 字段（TEXT，可为空）
2. 产品卡片（ProductCard.vue）在产品名后面展示客户标签
3. 编辑产品、新增产品、产品详情弹窗都展示并可编辑此字段
4. （实际实现扩展）同步增加了 `sales_person`（商务）和 `agency_ratio`（代投比例）两个字段

## 技术方案（实际实现）

### 1. 数据库变更

**文件：`py/database.py`**

- 在 `CREATE TABLE products` 中添加 `customer TEXT DEFAULT ''`（第 275 行）
- 列级迁移 `_ensure_columns()` 中通过 `_add_column_if_missing` 添加以下列（第 110-113 行）：
  - `customer TEXT DEFAULT ''`
  - `deleted_at TEXT DEFAULT ''`
  - `sales_person TEXT DEFAULT ''`
  - `agency_ratio REAL DEFAULT NULL`

**products 表完整字段列表**（CREATE TABLE 中的定义，第 268-277 行）：

```sql
CREATE TABLE IF NOT EXISTS products (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    product_name TEXT,
    kpi TEXT,
    region TEXT,
    status TEXT DEFAULT '',
    mcc_id INTEGER REFERENCES mcc(id),
    customer TEXT DEFAULT '',
    created_at TEXT DEFAULT (datetime('now','localtime'))
);
-- 注：owner_id, runner_ids, is_archived, deleted_at, sales_person, agency_ratio
-- 均通过 _ensure_columns() 中的 _add_column_if_missing 迁移添加
```

### 2. 后端 API 变更

**文件：`py/main.py`**

| 端点 | 变更 |
|------|------|
| `POST /api/products/create` | INSERT 列和值中加入 `customer`、`sales_person`、`agency_ratio`（第 2392-2399、2438 行） |
| `PUT /api/products/<id>` | 可更新字段白名单 `_product_fields` 中包含 `"customer"`、`"sales_person"`、`"agency_ratio"`（第 2458-2461 行） |
| `GET /api/products/list` | 无需改动（`SELECT p.*` 自动包含） |
| `GET /api/products/<id>/detail` | 无需改动（`SELECT p.*` 自动包含） |

**`POST /api/products/create` 详细处理逻辑**（第 2384-2446 行）：

- 从请求体中提取 `customer`、`sales_person`、`agency_ratio` 三个字段
- `agency_ratio` 会尝试转为 float，失败则置为 None
- 新建产品时 INSERT 语句包含全部字段：`product_name, kpi, region, mcc_id, customer, sales_person, agency_ratio, owner_id, runner_ids, created_at`
- 同名产品追加包时，会同步更新 `mcc_id`、`sales_person`、`agency_ratio`（但不更新 `customer`）

**`PUT /api/products/<id>` 可更新字段白名单**（第 2458-2461 行）：

```python
_product_fields = {
    "product_name": "product_name", "kpi": "kpi", "region": "region",
    "status": "status", "mcc_id": "mcc_id", "customer": "customer",
    "sales_person": "sales_person", "agency_ratio": "agency_ratio",
}
```

### 3. 前端变更

#### 3.1 ProductCard.vue（产品卡片标签展示）

**文件**：`frontend/src/components/ProductCard.vue`

标签展示顺序（第 12-28 行）：

```
💼 商务标签 (sales_person) → KPI 标签 → 地区标签 → 👤 客户标签 (customer) → 🏢 MCC 标签 → 🏃 在跑人员 → 🎬 成效素材
```

- 商务标签（第 12 行）：`type="success"`，带 `💼` emoji
- 客户标签（第 18 行）：`type="success"`，带 `👤` emoji

```html
<el-tag v-if="product.sales_person" size="small" type="success">💼 {{ product.sales_person }}</el-tag>
<el-tag v-if="product.customer" size="small" type="success">👤 {{ product.customer }}</el-tag>
```

**与原始设计的差异**：
- 原始设计：`type="success"` 无 emoji，位置在地区标签后、MCC 标签前
- 实际实现：`type="success"` 带 `👤` emoji，实际位于地区标签后、MCC 标签前
- 额外增加了商务标签 `💼`（设计文档未提及）

#### 3.2 ProductModal.vue（新增/编辑产品弹窗）

**文件**：`frontend/src/components/ProductModal.vue`

表单字段顺序（第 5-32 行）：

1. 产品/群名（必填）
2. KPI
3. 地区（下拉选择）
4. **客户**（文本输入，placeholder="产品所属客户"）
5. **商务**（下拉选择，支持手动输入创建，数据源 `accountStore.settings.sales_persons`）
6. **代投比例**（数字输入，placeholder="数字，如 6 表示 6%"）
7. 所属 MCC（下拉选择）

`form` 对象初始化（第 53 行）：
```javascript
const form = reactive({ product_name: '', kpi: '', region: '', customer: '', sales_person: '', agency_ratio: null, mcc_id: '' })
```

`init()` 函数编辑模式填充（第 68-73 行）：
```javascript
Object.assign(form, {
  product_name: p.product_name || '', kpi: p.kpi || '',
  region: p.region || '', customer: p.customer || '',
  sales_person: p.sales_person || '', agency_ratio: p.agency_ratio ?? null, mcc_id: p.mcc_id || '',
})
```

`init()` 函数新增模式重置（第 75 行）：
```javascript
Object.assign(form, { product_name: '', kpi: '', region: '', customer: '', sales_person: '', agency_ratio: null, mcc_id: '' })
```

#### 3.3 ProductDetailModal.vue（产品详情弹窗）

**文件**：`frontend/src/components/ProductDetailModal.vue`

详情头部信息行（第 5-9 行）：
```html
<strong>{{ product.product_name }}</strong> &nbsp;
KPI: {{ product.kpi || '-' }} &nbsp; 地区: {{ product.region || '-' }} &nbsp;
客户: {{ product.customer || '-' }} &nbsp;
MCC: {{ product.mcc_name ? product.mcc_name + ' (' + product.mcc_code + ')' : '未分配' }}
```

- 客户字段直接以内联文本形式展示在头部信息行，与产品名、KPI、地区并列
- 未使用 `<el-tag>`，而是纯文本 `客户: {{ product.customer || '-' }}`

#### 3.4 ProductPanel.vue（审计日志）

**文件**：`frontend/src/views/ProductPanel.vue`

审计日志详情快照中展示了 `customer` 字段（第 90 行）：
```html
<div><b>MCC:</b> {{ auditDetailRow.detail.product.mcc_id }} | <b>customer:</b> {{ auditDetailRow.detail.product.customer || '-' }}</div>
```

### 4. 涉及文件清单（实际变更）

| 文件 | 变更类型 | 说明 |
|------|---------|------|
| `py/database.py` | CREATE TABLE + 迁移 `_add_column_if_missing` | `customer`、`sales_person`、`agency_ratio`、`deleted_at` |
| `py/main.py` | INSERT/UPDATE 语句 + 可更新字段白名单 | `POST /api/products/create`、`PUT /api/products/<id>` |
| `frontend/src/components/ProductCard.vue` | 新增客户标签 + 商务标签 | 👤 customer、💼 sales_person |
| `frontend/src/components/ProductModal.vue` | 新增客户、商务、代投比例输入控件 | 表单初始化/填充/重置均包含这三个字段 |
| `frontend/src/components/ProductDetailModal.vue` | 新增客户显示 | 头部信息行纯文本展示 |
| `frontend/src/views/ProductPanel.vue` | 审计日志详情增加 customer 显示 | 删除日志快照中展示 |

### 5. 未涉及文件（确认无需修改）

| 文件 | 原因 |
|------|------|
| `frontend/src/api/products.js` | REST 层透传 JSON，字段由后端/前端自行处理 |
| `frontend/src/stores/products.js` | Pinia store 透传数据，不感知具体字段 |
| 筛选/搜索逻辑 | 客户、商务、代投比例均不作为筛选条件 |

## 注意事项

- `customer` 字段可为空（默认空字符串），不影响已有数据
- `sales_person` 字段可为空（默认空字符串），ProductModal 中以 `allow-create` 模式支持输入新商务人员
- `agency_ratio` 可为 NULL（默认 NULL），ProductModal 中使用 `v-model.number` 绑定
- 前端所有组件通过 `p.customer` / `p.sales_person` / `p.agency_ratio` 访问，后端 `SELECT p.*` 自动包含这些列
- 无需修改 Pinia store 和 API 层（数据透传）
- 无需修改筛选/搜索逻辑（这些字段均不作为筛选条件）
- 同名产品追加包时，会更新 `sales_person` 和 `agency_ratio`，但不会更新 `customer`
