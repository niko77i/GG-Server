# 账户逻辑删除 + Sheet 解绑列 — 实现计划

> **For agentic workers:** Use superpowers:subagent-driven-development or superpowers:executing-plans.

**Goal:** 账户删除改为软删除，Sheet H 列同步"是否解绑"，已删除账户可查看和恢复。

**Architecture:** accounts 表新增 `deleted_at` 字段，删除/恢复/列表 API 改动，`update_cell_by_account_id` 支持指定列索引，前端新增已删除账户弹窗。

**Tech Stack:** Python Flask + SQLite + Google Sheets API v4 + Vue 3 + Element Plus + Pinia

## Global Constraints

- 纯增量原则：现有硬删除逻辑保留（仅改 SQL 为 UPDATE），恢复功能为新增
- 删除时保留充值记录，不级联删除
- Sheet H 列写"解绑"为异步后台，失败记录日志
- 同步时 H 列="解绑"的账户直接跳过

---

### Task 1: 数据库 — accounts 表新增 `deleted_at` 字段

**Files:**
- Modify: `py/database.py`

**Interfaces:**
- Produces: accounts 表 `deleted_at TEXT DEFAULT NULL`

- [ ] 在 `_ensure_columns` 函数中追加 `_add_column_if_missing(conn, "accounts", "deleted_at", "deleted_at TEXT DEFAULT NULL")`
- [ ] 验证: `python -c "from py.database import init_db; print('OK')"`
- [ ] Commit

---

### Task 2: `update_cell_by_account_id` 支持指定列索引

**Files:**
- Modify: `py/google_sheets_service.py`

**Interfaces:**
- Modifies: `update_cell_by_account_id(service, spreadsheet_id, sheet_name, account_id, value, col_index=5)`
  - `col_index=5` → F列（备注），`col_index=7` → H列（是否解绑）

- [ ] 将当前硬编码的列索引 5 改为参数 `col_index`，默认值 5（向后兼容）
- [ ] 读取范围从 "A:G" 改为 "A:H"（支持 H 列）
- [ ] 验证: `python -c "import py.google_sheets_service as gs; print('OK')"`
- [ ] Commit

---

### Task 3: 删除改软删除 + 恢复端点 + 已删除列表

**Files:**
- Modify: `py/main.py`

**Interfaces:**
- Modifies: `DELETE /api/accounts/<id>` — 软删除
- Modifies: `POST /api/accounts/batch-delete` — 批量软删除
- Produces: `POST /api/accounts/<id>/restore` — 恢复
- Produces: `GET /api/accounts/deleted` — 已删除列表
- Modifies: `GET /api/accounts/list` — 默认过滤 `deleted_at IS NULL`

- [ ] `accounts_delete`: DELETE SQL → `UPDATE SET deleted_at=datetime('now','localtime')`，删除后后台写 Sheet H 列"解绑"
- [ ] `accounts_batch_delete`: 同改为软删除
- [ ] `accounts_restore`: 新增端点，`UPDATE SET deleted_at=NULL`，后台清空 Sheet H 列
- [ ] `accounts_deleted_list`: 新增端点，`WHERE deleted_at IS NOT NULL`
- [ ] `accounts_list`: WHERE 条件追加 `AND a.deleted_at IS NULL`
- [ ] `accounts_lookup` / `batch_lookup`: 同样过滤
- [ ] 验证: `python -c "import py.main; print('OK')"`
- [ ] Commit

---

### Task 4: sync-from-sheet 跳过解绑账户

**Files:**
- Modify: `py/main.py`

- [ ] 读取 Sheet 范围从 "A:G" 改为 "A:H"
- [ ] 解析时增加 H 列（索引7）"是否解绑"
- [ ] H 列="解绑"的账户跳过，不参与比对
- [ ] 验证: `python -c "import py.main; print('OK')"`
- [ ] Commit

---

### Task 5: 前端 API + Store + 弹窗

**Files:**
- Modify: `frontend/src/api/accounts.js`
- Modify: `frontend/src/stores/accounts.js`
- Create: `frontend/src/components/AccountDeletedModal.vue`
- Modify: `frontend/src/views/AdsAccountPanel.vue`

- [ ] API: 新增 `restore(id)`、`listDeleted()`
- [ ] Store: 新增 `restoreAccount`、`loadDeletedAccounts` action
- [ ] AccountDeletedModal: 已删除账户列表（account_id/名称/代理/删除时间），恢复按钮
- [ ] AdsAccountPanel: 新增「🗑 已删除」按钮
- [ ] 验证: `cd frontend && npm run build`
- [ ] Commit
