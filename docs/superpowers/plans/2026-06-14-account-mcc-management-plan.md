# 账户与 MCC 管理 — 实现计划

**日期**：2026-06-14
**关联设计**：[design.md](../specs/2026-06-14-account-mcc-management-design.md)

## 实施步骤

### 步骤 1：数据库层 (`py/database.py`)

- [ ] 1.1 新建 `accounts` 表
- [ ] 1.2 新建 `mcc` 表
- [ ] 1.3 `products` 表新增 `mcc_id` 列（ALTER TABLE 迁移）
- [ ] 1.4 编写 CRUD 便捷函数：
  - `crud_accounts_create/create/update/delete/list/get_by_id`
  - `crud_mcc_create/create/update/delete/list/get_by_id`
- [ ] 1.5 编写辅助查询函数：
  - `mcc_get_account_count(mcc_id)` → 直属账户数
  - `mcc_get_account_count_recursive(mcc_id)` → 递归账户总数
  - `mcc_get_child_mccs(mcc_id)` → 子 MCC 列表
  - `mcc_get_products(mcc_id)` → MCC 关联的产品
  - `product_get_related_accounts(product_id)` → 产品通过 MCC 关联的账户列表

### 步骤 2：后端路由 (`py/main.py`)

- [ ] 2.1 账户 API：6 个路由
- [ ] 2.2 MCC API：7 个路由
- [ ] 2.3 产品 API 微调：`create`/`update` 支持 `mcc_id`，新增 `detail` 路由
- [ ] 2.4 路由注册（现有路由附近，按分组添加）

### 步骤 3：前端 HTML (`index.html`)

- [ ] 3.1 侧边栏：`📦 产品管理` → `🏢 账户管理`，调整 active 默认
- [ ] 3.2 面板重构：原 `panel-product` 改名为 `panel-account`，内含 3 个子标签
- [ ] 3.3 子标签 HTML：产品管理 / 广告账户 / MCC 管理
- [ ] 3.4 产品管理区域：保留现有结构，增加 MCC 筛选 + 详情弹窗容器
- [ ] 3.5 账户表格 HTML
- [ ] 3.6 MCC 表格 HTML + 详情弹窗 HTML
- [ ] 3.7 账户/MCC 编辑弹窗 HTML

### 步骤 4：前端 JS (`js/account.js`)

- [ ] 4.1 迁移 `product.js` 全部功能到 `account.js`
- [ ] 4.2 子标签切换逻辑（产品/账户/MCC）
- [ ] 4.3 账户表：搜索/筛选/分页/新增/编辑/删除
- [ ] 4.4 MCC 表：搜索/筛选/新增/编辑/删除 + 详情弹窗
- [ ] 4.5 产品详情弹窗：关联账户展示
- [ ] 4.6 产品表：增加 MCC 列 + 关联账户数列
- [ ] 4.7 批量操作（批量删除/批量修改状态）

### 步骤 5：样式 (`css/style.css`)

- [ ] 5.1 新增面板样式（子标签、详情弹窗、状态标签等）

### 步骤 6：清理

- [ ] 6.1 移除 `index.html` 中 `js/product.js` 的引用
- [ ] 6.2 移除侧边栏旧面板引用

### 步骤 7：验证

- [ ] 7.1 启动 Flask，创建 MCC → 创建账户 → 创建产品 → 验证关联展示
- [ ] 7.2 测试 MCC 树形关系（父子）
- [ ] 7.3 测试产品详情弹窗（递归账户统计）
- [ ] 7.4 测试批量操作
