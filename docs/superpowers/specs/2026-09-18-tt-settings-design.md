# TT 设置界面 设计文档

> 状态：待确认
> 日期：2026-09-18

## 1. 需求描述

TT 平台目前只有「产品管理」「BC 管理」两个页面，**没有设置界面**（GG / FB 都有）。后续 TT 要增加账户管理等功能，这些功能都需要读取 Google 表格，因此需要一个像 GG 一样「配置 Google 表格后读取」的设置入口。

本次目标：为 TT 新增设置界面，**结构对齐 GG 设置页**（`SettingsPanel.vue` 的三 tab 结构），内容适配 TT。核心是 **Google 表格配置**（管理员全局一个表格，供后续 TT 账户管理读取），并一并实现「数据管理」tab（导出/导入 TT 数据）。

**已确认的三个方向**：
1. 设置页范围 = 完整对齐 GG 设置页（三 tab 结构）
2. Google 表格粒度 = 管理员全局一个表格（像 GG 充值表 `recharge_sheet_id`）
3. Tab3 数据管理 = 本次一并实现（TT 数据导出/导入）
4. Tab1 选项卡片 = 只放「商务人员」一张（账户状态/代理/MCC 等级是 GG 广告账户专属，TT 无对应概念）

**约束（纯增量）**：只新增/修改 `frontend/src/views/tt/`、`frontend/src/api/tt.js`、`py/routes/tt_routes.py`，以及 `AppSidebar.vue` / `router/index.js` 两处导航入口；另在 `py/main.py` 的 `sales_persons_delete` 做一处增量修复（补 TT 引用检查）。**不改动 GG / FB 现有业务逻辑**。复用现有共享端点（`/sales-persons/*`、`/regions/*`、`/api/google-sheets/sheets`）时不做行为变更。

## 2. 现状 vs 目标

### 2.1 现状（TT）

- 路由只有 `/tt/products`、`/tt/bcs`，无 `/tt/settings`
- `AppSidebar.vue` 底部 ⚙ 设置按钮，在 TT 平台点击会跳到 `/accounts/settings`（GG 的设置页，`settingsPath` 未区分 TT）
- `ttNavItems` 的「产品管理」区只有「产品管理 / BC 管理」两个菜单项，无「系统 > 设置」

### 2.2 目标

- 新增 `/tt/settings` 路由 + `TtSettingsPanel.vue`，三 tab：**账户设置 / 地区时区 / 数据管理**
- TT 平台点 ⚙ 或菜单「系统 > TT设置」均进入 `/tt/settings`
- Google 表格配置用 **TT 独立 key**，不与 GG 的 `recharge_sheet_id` / `sheet_mappings` 冲突
- 数据管理 tab 支持 TT 数据导出/导入

## 3. 技术方案

### 3.1 后端（Google 表格配置的存取）

GG 的充值表配置走 `/api/settings/account`，把 `recharge_sheet_id` 与 `sheet_mappings` 存在**全局 `tags` 表**（key 分别为 `recharge_sheet_id`、`sheet_mappings`），不分平台。若 TT 直接复用，会和 GG 共享同一个表格 ID，冲突。

因此新增 **TT 专属端点** `/api/tt/settings`（GET / POST），用独立 key 存全局 `tags` 表：

| 字段 | 存储 | key |
|------|------|-----|
| spreadsheet ID | 全局 `tags` | `tt_sheet_id` |
| sheet 映射 | 全局 `tags` | `tt_sheet_mappings` |

- **读取工作表**：复用现有 `/api/google-sheets/sheets`（`spreadsheet_id` 参数），该端点用全局服务账号，**不限制平台**，TT 可直接用。
- **保存权限**：仅 admin / developer 可写（对齐 GG「仅管理员」充值表配置）。
- **sheet 映射默认值**：`{ "accounts": "账户明细" }`（TT 账户管理读取账户数据的 sheet）。后续账户管理实现时按需扩展 key。

### 3.2 后端（商务人员 / 地区的复用）

- 商务人员：复用 `/api/sales-persons/list`（GET）、`/api/sales-persons/create`（POST）、`/api/sales-persons/<id>`（PUT 改名 / DELETE）。
- 地区时区：复用 `/api/regions/list`（GET）、`/api/regions/create`（POST）、`/api/regions/<id>`（PUT 改时区 / DELETE）。

这两组端点都通过 `_get_effective_platform()` **按当前登录用户平台自动隔离**（`sales_persons` 表有 `platform` 字段，`regions_list` 按平台过滤），TT 用户访问自动返回 TT 数据，**后端无需改动**。

### 3.3 后端（增量修复：商务人员删除的 TT 引用检查）

现状 `sales_persons_delete`（`py/main.py:6007`）只检查 GG `products` 与 FB `fb_products` 的引用，**未检查 TT `tt_products`**。TT 设置页开放删除后，若删除被 TT 产品引用的商务人员，会产生悬空引用。

**增量修复**：在删除检查中补上 `tt_products`（`sales_person_id=? AND is_archived=0`）与解除引用（`UPDATE tt_products SET sales_person_id=NULL`），只新增 TT 分支，不改 GG/FB 分支。

### 3.4 后端（TT 数据导出 / 导入）

新增 `py/routes/tt_routes.py` 内的两个端点，逻辑内联（TT 专属，独立于 GG 的 `data_service.py`）：

**导出 `GET /api/tt/data/export`**（`@jwt_required()`）：按当前用户 `owner_id` 导出，返回 JSON 文件下载。导出 `data` 结构：
```json
{
  "bcs": [],              // tt_bcs WHERE owner_id=? AND deleted_at IS NULL
  "products": [],         // tt_products WHERE owner_id=? AND is_archived=0
  "packages": [],         // tt_packages WHERE product_id IN (上述 products)
  "product_runners": [],  // tt_product_runners WHERE product_id IN (products)
  "delist_checks": [],    // tt_delist_checks WHERE package_id IN (packages)
  "sales_persons": []     // sales_persons WHERE platform='tt'（供导入时映射商务人员）
}
```
外层 `{ version, exported_at, source: "tt-server", data }`。

**导入 `POST /api/tt/data/import`**（`@jwt_required()`，multipart 上传 `.json`）：解析 JSON（兼容 `data` 包裹），`PRAGMA foreign_keys=OFF`，按外键依赖顺序重建，返回计数报告：

1. `sales_persons`：按 name 匹配/新建 TT 平台商务人员，建 `old_id → new_id` 映射
2. `tt_bcs`：按 `bc_id`（UNIQUE）匹配已有或新建，建 `old_id → new_id` 映射
3. `tt_products`：`owner_id = target_user_id`，映射 `bc_id`、`sales_person_id`，建 `old_id → new_id` 映射
4. `tt_packages`：映射 `product_id`
5. `tt_product_runners`：映射 `product_id`，`user_id = target_user_id`
6. `tt_delist_checks`：映射 `package_id`

报告：`{ success, report: { bcs, products, packages, runners, delist_checks } }`。

**范围取舍**：`tt_product_assets`（素材）关联 `videos` 表，导入时 video 未必存在，本次不导出/导入；`.db` 文件导入（GG 读取旧库）TT 无历史库迁移需求，本次仅支持 `.json`。

### 3.5 前端

| 文件 | 改动 |
|------|------|
| 新增 `frontend/src/views/tt/TtSettingsPanel.vue` | TT 设置页，三 tab（见 §4） |
| `frontend/src/api/tt.js` | 加 `ttSettingsApi`（`getSettings()` / `saveSettings()` → `/tt/settings`）与 `ttDataApi`（`exportData()` / `importFile()` → `/tt/data/export` / `/tt/data/import`）；商务/地区直接用 `client` 调用共享端点 |
| `frontend/src/router/index.js` | 新增 `{ path: '/tt/settings', component: TtSettingsPanel, meta: { platform: 'tt', title: 'TT设置' } }`（**不加 `admin`**，普通 TT 用户可进，Google 表格卡片内部再做 admin 门控） |
| `frontend/src/components/AppSidebar.vue` | ① `settingsPath` computed 增加 TT 分支；② `ttNavItems` 的「产品管理」区加「系统 > TT设置」菜单项 |

## 4. UI 改动明细

### 4.1 页面骨架

`TtSettingsPanel.vue` 复用 GG `SettingsPanel.vue` 的整体骨架：顶部 `<h2>⚙ 设置</h2>` + `el-tabs`（`activeTab`），三 tab。

### 4.2 Tab1 账户设置

对齐 GG 的「账户设置」tab，但**只保留 TT 实际用到的选项卡片 + Google 表格配置**：

**（a）商务人员选项卡片**（复用 `sales_persons`，平台隔离）
- 单张 `el-card`，头部 `👤 商务人员选项` + `N 项` 计数 tag
- 交互对齐 GG 选项卡片：`el-tag` 双击编辑（`el-input` 内联改名 → PUT）、`×` 关闭删除（确认后 DELETE）、`+` 展开输入新增
- **不放** GG 的 `账户状态 / 代理名 / MCC 等级` 三张卡片

**（b）管理员专属「📊 Google 表格配置」卡片**（`v-if="authStore.isAdmin || authStore.isDeveloper"`）
- 对齐 GG 充值表配置卡片：左边框 `border-left:3px solid #0891b2` + `仅管理员` tag
- Google Sheets（URL 或 ID）`el-input`（`form.sheet_id`）→ `📋 读取工作表` 按钮（调 `googleSheetsApi.listSheets(sid)`）
- Sheet 映射区：遍历 `form.sheet_mappings` 的 key，`el-select filterable allow-create` 选 sheet 名（支持手动输入），未读取时提示「点击读取工作表加载可选 sheet 列表」
- `💾 保存配置` 按钮 → `ttSettingsApi.saveSettings({ sheet_id, sheet_mappings })`

### 4.3 Tab2 地区时区

对齐 GG 的「地区时区」tab（复用 `/regions/*`，平台隔离）：
- 地区列表：每行 = 地区名 + 时区 `el-select`（`@change` 保存时区）+ 悬停删除按钮
- 底部新增行：地区名 `el-input` + 时区 `el-select` + `新增` 按钮
- 时区选项复用 GG 的 `_buildTimezoneOptions()` 生成逻辑

### 4.4 Tab3 数据管理

对齐 GG 的「数据管理」tab，内容适配 TT：

**（a）导出区卡片** `📤 导出数据`
- 说明文字「导出你的 TT 产品 / 包 / BC 数据为 JSON 文件，可用于备份或迁移。」
- `📥 导出我的数据` 按钮 → `ttDataApi.exportData()`（blob 下载，文件名 `tt-server-export-<username>-<date>.json`）

**（b）导入区卡片** `📥 导入数据`
- 说明文字「上传 TT 导出的 JSON 文件。」
- `el-upload`（`accept=".json"`，`auto-upload=false`，`limit=1`，drag）
- `✅ 确认导入` 按钮 → `ttDataApi.importFile(file)`，成功后 toast 显示各表导入计数

（本次不做「导入历史」——TT 无多用户导入需求，GG 的历史表字段也不匹配 TT 数据模型。）

## 5. 数据结构与 API

### 5.1 新增后端端点

`GET /api/tt/settings`（`@jwt_required()`）
```json
{ "success": true, "settings": { "sheet_id": "", "sheet_mappings": { "accounts": "账户明细" } } }
```

`POST /api/tt/settings`（`@jwt_required()`，body 内校验 admin/developer）
```json
{ "sheet_id": "<spreadsheet id>", "sheet_mappings": { "accounts": "账户明细" } }
```
- 保存逻辑：`INSERT OR REPLACE INTO tags(key,value)` 写 `tt_sheet_id` / `tt_sheet_mappings`（后者 JSON 序列化）
- 读取逻辑：读 `tt_sheet_id`（字符串）、`tt_sheet_mappings`（JSON → dict，无则用默认 `{ "accounts": "账户明细" }`）
- `_TT_SHEET_MAPPING_KEYS = {"accounts"}` 常量，后续扩展

`GET /api/tt/data/export`（`@jwt_required()`）→ JSON 文件下载

`POST /api/tt/data/import`（`@jwt_required()`，multipart `.json`）→ `{ success, report }`

### 5.2 复用端点（无改动）

| 端点 | 用途 |
|------|------|
| `GET /api/sales-persons/list` | 商务人员列表（平台隔离） |
| `POST /api/sales-persons/create` | 新增商务 |
| `PUT /api/sales-persons/<id>` | 改名 |
| `DELETE /api/sales-persons/<id>` | 删除（增量补 tt_products 引用检查） |
| `GET /api/regions/list` | 地区列表（平台隔离） |
| `POST /api/regions/create` | 新增地区 |
| `PUT /api/regions/<id>` | 改时区 |
| `DELETE /api/regions/<id>` | 删除地区 |
| `GET /api/google-sheets/sheets?spreadsheet_id=` | 读取工作表列表 |

## 6. 涉及文件清单

- 新增：`frontend/src/views/tt/TtSettingsPanel.vue`
- 修改：`frontend/src/api/tt.js`（加 `ttSettingsApi`、`ttDataApi`）
- 修改：`frontend/src/router/index.js`（加 `/tt/settings`）
- 修改：`frontend/src/components/AppSidebar.vue`（`settingsPath` + `ttNavItems`）
- 修改：`py/routes/tt_routes.py`（新增 `/api/tt/settings` GET/POST、`/api/tt/data/export` GET、`/api/tt/data/import` POST）
- 修改：`py/main.py`（`sales_persons_delete` 增量补 `tt_products` 引用检查）
- 不动：GG / FB 任何业务文件

## 7. 验证

- `cd py && python -m pytest` 通过（新增 `/api/tt/settings`、`/api/tt/data/export`、`/api/tt/data/import` 与商务删除 TT 引用检查的测试）
- `cd frontend && npm run build` 通过
- 手动：TT 用户登录 → 点 ⚙ / 菜单进入 `/tt/settings` → 商务人员增删改、地区时区配置、数据导出/导入正常；admin 登录 → Google 表格配置卡片可见，输入 spreadsheet 后「读取工作表」列出 sheet、保存成功；GG 管理员登录确认 GG 设置页不受影响（key 隔离）
