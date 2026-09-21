# TT 设置界面 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: 使用 superpowers:subagent-driven-development 或 superpowers:executing-plans 按任务逐条实现。步骤用 `- [ ]` 语法跟踪。

**Goal:** 为 TT 平台新增设置界面（三 tab：账户设置/地区时区/数据管理），UI 直接对齐 GG `SettingsPanel.vue`。

**Architecture:** 前端复用 GG 设置页骨架，仅保留 TT 用到的卡片；后端在 `tt_routes.py` 新增 4 个端点（settings GET/POST、data export/import），在 `main.py` 的 `sales_persons_delete` 补 TT 引用检查。商务人员/地区复用共享端点 `/sales-persons/*`、`/regions/*`（平台自动隔离）。

**Tech Stack:** Vue 3 + Element Plus（前端）、Flask + SQLite（后端）。

## Global Constraints

- **纯增量**：只新增/修改 `frontend/src/views/tt/TtSettingsPanel.vue`（新增）、`frontend/src/api/tt.js`、`frontend/src/router/index.js`、`frontend/src/components/AppSidebar.vue`、`py/routes/tt_routes.py`、`py/main.py`（仅 `sales_persons_delete` 一处），及 `py/tests/test_tt_routes.py`。**不改 GG/FB 任何业务逻辑**。
- Google 表格配置用 TT 独立 key：`tags` 表 `tt_sheet_id`（字符串）、`tt_sheet_mappings`（JSON，默认 `{"accounts": "账户明细"}`）。
- 保存 Google 表格配置仅 admin/developer 可写（403 拒绝）。
- `tt_product_assets` 不导出/导入（关联 `videos`）；仅支持 `.json`。
- 后端端点路由前缀 `/api/tt/`，均 `@jwt_required()` + `@tt_required`。

---

## Task 1: 后端 — tt_routes.py 新增 settings/data 端点

**Files:**
- Modify: `py/routes/tt_routes.py`（顶部加 `import json`；新增 4 个端点）

**Interfaces:**
- 复用已有 `ok`/`err`/`get_uid`/`get_db`/`parse_body`（helpers.py）、`tt_required`（decorators.py）、`_get_role`（tt_routes.py 已有工具函数）。
- `_TT_SHEET_MAPPING_DEFAULTS = {"accounts": "账户明细"}` 常量。

端点契约：
- `GET /api/tt/settings` → `{success, settings: {sheet_id, sheet_mappings}}`（读 tags）
- `POST /api/tt/settings` → body `{sheet_id, sheet_mappings}`；非 admin/developer 返回 403；写 tags `tt_sheet_id`/`tt_sheet_mappings`
- `GET /api/tt/data/export` → JSON 文件下载（`Content-Disposition`），`{version, exported_at, source:"tt-server", data:{bcs,products,packages,product_runners,delist_checks,sales_persons}}`
- `POST /api/tt/data/import` → multipart `file`（仅 `.json`），返回 `{success, report:{bcs,products,packages,runners,delist_checks}}`

## Task 2: 后端 — main.py sales_persons_delete 补 TT 引用检查

**Files:**
- Modify: `py/main.py`（`sales_persons_delete` 函数，约 6021-6038 行）

在 GG/FB 引用检查后补 `tt_products` 查询、`all_products` 合并、解除引用 `UPDATE tt_products SET sales_person_id=NULL`。只新增 TT 分支，不改 GG/FB 分支。

## Task 3: 前端 — api/tt.js 新增 ttSettingsApi / ttDataApi

**Files:**
- Modify: `frontend/src/api/tt.js`

新增 `ttSettingsApi`（getSettings/saveSettings → `/tt/settings`）、`ttDataApi`（exportData → `/tt/data/export` blob、importFile → `/tt/data/import` multipart）。

## Task 4: 前端 — router + AppSidebar 导航入口

**Files:**
- Modify: `frontend/src/router/index.js`（TT 路由区加 `/tt/settings`，`meta: { platform:'tt', title:'TT设置' }`，不加 admin）
- Modify: `frontend/src/components/AppSidebar.vue`（`settingsPath` 加 TT 分支；`ttNavItems` 的「产品管理」区加「系统 > TT设置」）

## Task 5: 前端 — 新建 TtSettingsPanel.vue

**Files:**
- Create: `frontend/src/views/tt/TtSettingsPanel.vue`

对齐 GG `SettingsPanel.vue` 三 tab：
- **Tab1 账户设置**：`👤 商务人员选项` 卡片（直接调 `/sales-persons/*`，tag 双击改名/×删除/+新增）+ 管理员专属 `📊 Google 表格配置` 卡片（`sheet_id` + `sheet_mappings.accounts`，读工作表用 `googleSheetsApi.listSheets`，保存用 `ttSettingsApi.saveSettings`）。不放账户状态/代理/MCC 等级卡片。
- **Tab2 地区时区**：复用 `/regions/*`（与 GG 相同逻辑）。
- **Tab3 数据管理**：导出/导入（用 `ttDataApi`），不做导入历史。

## Task 6: 测试 + 验证

**Files:**
- Modify: `py/tests/test_tt_routes.py`（新增 settings GET/POST、非 admin 403、export/import 往返、sales_persons_delete 的 TT 引用检查测试）

验证：
- `cd py && python -m pytest tests/test_tt_routes.py -q` 全绿
- `cd frontend && npm run build` 通过
