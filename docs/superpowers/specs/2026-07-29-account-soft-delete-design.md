# 账户逻辑删除 + Sheet 解绑列 — 设计文档

## 一、需求描述

1. **逻辑删除**：账户删除改为软删除，新增 `deleted_at` 字段（NULL=正常，有值=已删除），可恢复
2. **已删除账户查看**：新增按钮查看已删除账户列表，支持恢复
3. **Sheet "是否解绑"列（H列）**：删除账户时写"解绑"，恢复时清空该列
4. **同步时跳过解绑**：Sheet→系统同步时，H列="解绑"的账户直接跳过
5. **系统→Sheet 自动同步**：删除/恢复时自动更新 Sheet H 列

---

## 二、数据库变更

### accounts 表新增字段

```sql
ALTER TABLE accounts ADD COLUMN deleted_at TEXT DEFAULT NULL;
```

`deleted_at` 在 `database.py` 的 `_ensure_columns` 中迁移。

### 现有删除逻辑改动

| 现有 | 改为 |
|------|------|
| `DELETE FROM accounts WHERE id=?` | `UPDATE accounts SET deleted_at=datetime('now','localtime') WHERE id=?` |
| `DELETE FROM recharge_records WHERE account_id=?` (级联) | **不删除**，保留充值记录 |
| 列表默认过滤已删除 | `WHERE a.deleted_at IS NULL` |

---

## 三、后端 API

### 3.1 `DELETE /api/accounts/<id>` — 修改

改为软删除：
```python
db.execute("UPDATE accounts SET deleted_at=datetime('now','localtime') WHERE id=?", (aid,))
```

删除后后台更新 Sheet H 列（"是否解绑"）为"解绑"。H 列索引=7。

### 3.2 `POST /api/accounts/<id>/restore` — 新增

恢复账户：
```python
db.execute("UPDATE accounts SET deleted_at=NULL WHERE id=?", (aid,))
```

恢复后后台清空 Sheet H 列。

### 3.3 `GET /api/accounts/deleted` — 新增

返回当前用户已删除的账户列表（`WHERE deleted_at IS NOT NULL`）。

### 3.4 `accounts_list` — 修改

默认查询条件追加 `AND a.deleted_at IS NULL`。

### 3.5 `batch_delete` — 修改

同单删除改为软删除。

### 3.6 `sync-from-sheet` — 修改

解析 Sheet 时增加 H 列（索引7="是否解绑"）。值为"解绑"的账户直接跳过，不参与比对。

### 3.7 `update_cell_by_account_id` — 修改

当前硬编码写 F 列（索引5）。需要支持指定目标列。改为：

```python
def update_cell_by_account_id(service, spreadsheet_id, sheet_name, account_id, value, col_index=5):
    """col_index: 目标列索引，默认 5=F列（备注），7=H列（是否解绑）"""
```

---

## 四、前端

### 4.1 AdsAccountPanel.vue

- 删除按钮改为软删除（调现有 API，后端改为软删除）
- 新增「🗑 已删除」按钮
- 列表仅显示未删除账户（后端过滤）

### 4.2 AccountDeletedModal.vue — 新增

展示已删除账户列表：

```
┌──────────────┬──────────┬──────────┬──────────────┬────────┐
│ 账户ID        │ 名称      │ 代理     │ 删除时间      │ 操作   │
├──────────────┼──────────┼──────────┼──────────────┼────────┤
│ xxx-xxx-xxx  │ 账户A    │ 卡尔     │ 2026-07-29   │ [恢复] │
└──────────────┴──────────┴──────────┴──────────────┴────────┘
```

恢复按钮调 `POST /api/accounts/<id>/restore`。

### 4.3 AccountDetailModal.vue

已删除账户详情中显示 `deleted_at`。

---

## 五、Sheet 列结构更新

| 列 | 字段 | 说明 |
|----|------|------|
| A | 运营 | 门禁校验 |
| B | 账户ID | 主键匹配 |
| C | 所属渠道 | agent |
| D | 国家 | 不参与 |
| E | 时区 | timezone |
| F | 备注 | 系统状态 |
| G | 是否封户 | 状态变更建议 |
| H | 是否解绑 | **新增**，系统删除时写"解绑"，恢复时清空 |

---

## 六、涉及文件

| 文件 | 操作 | 说明 |
|------|------|------|
| `py/database.py` | 修改 | `_ensure_columns` 新增 `deleted_at` |
| `py/main.py` | 修改 | 删除改软删除 + 恢复端点 + 已删除列表 + 列表过滤 + sync 跳过解绑 + 写 H 列 |
| `py/google_sheets_service.py` | 修改 | `update_cell_by_account_id` 支持指定列索引 |
| `frontend/src/views/AdsAccountPanel.vue` | 修改 | 新增已删除按钮 |
| `frontend/src/components/AccountDeletedModal.vue` | **新增** | 已删除账户列表弹窗 |
| `frontend/src/api/accounts.js` | 修改 | 新增 `restore`、`listDeleted` API |
| `frontend/src/stores/accounts.js` | 修改 | 新增 restore/listDeleted action |
