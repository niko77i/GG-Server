# 产品增加"客户"字段 — 设计文档

> 日期：2026-07-03
> 需求：产品增加一个字段"客户"，用于保存当前产品所属客户，也作为标签展示在产品名后面。

## 需求描述

1. 产品表新增 `customer` 字段（TEXT，可为空）
2. 产品卡片（ProductCard.vue）在产品名后面展示客户标签，位置在地区标签后面
3. 编辑产品、新增产品、产品详情弹窗都展示并可编辑此字段

## 技术方案

### 1. 数据库变更

**文件：`py/database.py`**

- 在 `CREATE TABLE products` 中添加 `customer TEXT DEFAULT ''`
- 新增迁移块：`ALTER TABLE products ADD COLUMN customer TEXT DEFAULT ''`（用 PRAGMA 检测列是否存在后执行）

### 2. 后端 API 变更

**文件：`py/main.py`**

| 端点 | 变更 |
|------|------|
| `POST /api/products/create` | INSERT 列和值中加入 `customer` |
| `PUT /api/products/<id>` | 可更新字段列表中加 `"customer"` |
| `GET /api/products/list` | 无需改动（`SELECT p.*` 自动包含） |
| `GET /api/products/<id>/detail` | 无需改动（`SELECT p.*` 自动包含） |

### 3. 前端变更

#### 3.1 ProductCard.vue（产品卡片标签展示）

在地区标签 `<el-tag v-if="product.region">` 之后，MCC 标签之前，增加客户标签：

```html
<el-tag v-if="product.customer" size="small" type="success">{{ product.customer }}</el-tag>
```

#### 3.2 ProductModal.vue（新增/编辑产品弹窗）

- `form` 对象增加 `customer: ''`
- 模板增加 `<el-form-item label="客户">` + `<el-input v-model="form.customer" />`
- `init()` 函数填充和重置时包含 `customer` 字段

#### 3.3 ProductDetailModal.vue（产品详情弹窗）

- 在详情头部信息区添加客户字段的显示

### 4. 涉及文件清单

| 文件 | 变更类型 |
|------|---------|
| `py/database.py` | CREATE TABLE + 迁移 ALTER TABLE |
| `py/main.py` | INSERT/UPDATE 语句 + 可更新字段列表 |
| `frontend/src/components/ProductCard.vue` | 新增客户标签 |
| `frontend/src/components/ProductModal.vue` | 新增客户输入框 |
| `frontend/src/components/ProductDetailModal.vue` | 新增客户显示 |

## 注意事项

- `customer` 字段可为空（默认空字符串），不影响已有数据
- 前端所有组件通过 `p.customer` 访问，后端 `SELECT p.*` 自动包含此列
- 无需修改 Pinia store 和 API 层（数据透传）
- 无需修改筛选/搜索逻辑（客户不作为筛选条件）
