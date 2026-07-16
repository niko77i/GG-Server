# 产品删除审计日志 — 设计文档

## 需求描述

当前删除产品时没有任何业务日志，仅有一条 HTTP 请求日志（`[时间] DELETE /api/products/123 → 200`），无法追溯：
- 谁删的
- 什么时间删的
- 删了什么产品（产品名、包含哪些包、关联了哪些素材）

需要增加删除审计日志，确保删除操作可追溯、可恢复。

## 当前状态

### 删除接口（py/main.py:1733-1744）
```python
@app.route("/api/products/<int:pid>", methods=["DELETE"])
@jwt_required()
def products_delete(pid):
    db.execute("DELETE FROM product_assets WHERE product_id=?", (pid,))
    db.execute("DELETE FROM packages WHERE product_id=?", (pid,))
    db.execute("DELETE FROM products WHERE id=?", (pid,))
    db.commit(); db.close()
    return jsonify({"success": True})
```

当前存在的问题：

| 问题 | 说明 |
|---|---|
| **硬删除** | 直接从三个表物理删除，不可恢复 |
| **无审计日志** | 不记录操作人、被删数据内容 |
| **delist_checks 孤立行** | `delist_checks` 表有 FK 引用 `packages(id)`，但无 `ON DELETE CASCADE`，packages 被删后会产生孤立行 |
| **ad_reports 残留** | `ad_reports` 通过 `product_name` 文本关联产品，产品被删后数据残留 |

### 涉及的数据表

| 表 | 关键字段 |
|---|---|
| `products` | id, product_name, kpi, region, status, mcc_id, customer, owner_id, runner_ids, **is_archived**, created_at |
| `packages` | id, product_id, series_name, package_name, url, status, created_at |
| `product_assets` | id, product_id, video_id, added_by, added_at |
| `delist_checks` | id, package_id (FK→packages), product_id (FK→products), is_delisted, checked_at |

### 重要发现：is_archived 字段

`products` 表已有 `is_archived INTEGER DEFAULT 0` 字段（[database.py:341](py/database.py#L341)），且**所有产品查询已经过滤了它**：
- 所有列表/详情/统计查询都加了 `WHERE (is_archived IS NULL OR is_archived = 0)` 条件
- 即 `is_archived=1` 的行已经是"不可见"状态

**可以利用这个现有机制实现软删除**，无需修改任何现有查询。

## 技术方案

### 方案：利用 is_archived 做软删除 + 审计日志表

#### 1. products 表加 deleted_at 字段

```sql
ALTER TABLE products ADD COLUMN deleted_at TEXT DEFAULT '';
```

- 复用已有的 `is_archived` 做软删除标记（设为 1），所有现有查询自动过滤
- 新增 `deleted_at` 记录删除时间（区分"归档"和"删除"，归档可能没有 deleted_at）
- 不改动任何现有查询逻辑

#### 2. 新建审计日志表

```sql
CREATE TABLE IF NOT EXISTS audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id),
    action TEXT NOT NULL,           -- 'delete_product'
    target_type TEXT NOT NULL,      -- 'product'
    target_id INTEGER NOT NULL,     -- 被操作产品的 ID
    target_name TEXT DEFAULT '',    -- 产品名称
    detail TEXT DEFAULT '{}',       -- JSON 完整快照
    created_at TEXT DEFAULT (datetime('now','localtime'))
);
CREATE INDEX IF NOT EXISTS idx_audit_log_action ON audit_log(action);
CREATE INDEX IF NOT EXISTS idx_audit_log_created ON audit_log(created_at);
```

### 删除流程变更

**改动前**：
```
DELETE product_assets → DELETE packages → DELETE products → 返回成功
```

**改动后**：
```
1. 查询产品信息（含关联 packages 列表）
2. 将产品 + 包列表序列化为 JSON 快照
3. 写入 audit_log（user_id, action, target_type, target_id, target_name, detail）
4. DELETE FROM delist_checks WHERE product_id=?        ← 修复孤立行
5. DELETE FROM product_assets WHERE product_id=?
6. DELETE FROM packages WHERE product_id=?
7. UPDATE products SET is_archived=1, deleted_at=now() WHERE id=?  ← 软删除
8. 返回成功
```

### 涉及的文件

| 文件 | 改动 |
|---|---|
| `py/database.py` | `_ensure_schema()` 新增 `audit_log` 建表 + products 迁移加 `deleted_at` 列 |
| `py/main.py` | 修改 `products_delete()`：先记日志 → 清理关联表 → 软删除 |
| `frontend/` | **无需改动**（软删除对前端透明，已有查询自动过滤） |

### 不需要改产品查询

由于复用 `is_archived` 机制，现有 8 处产品查询不需要任何修改。它们已经过滤了 `is_archived=1` 的行：
- `GET /api/products` — 产品列表
- `GET /api/products/<pid>` — 产品详情
- `PUT /api/products/<pid>` — 产品更新
- `POST /api/products/merge` — 产品合并
- `GET /api/dashboard/stats` — 仪表盘统计
- `py/data_service.py` 中的统计查询
- 等其他涉及 products 表的查询

### 不做的

- **不建 UI 查看审计日志**：本期只记录，后续需要时再补管理界面
- **不处理恢复功能**：软删除后数据在库里，可以通过 SQLite 直接操作恢复，暂不做 UI
- **包删除（`DELETE /api/products/packages/<pkg_id>`）暂不改动**：只改产品级删除

## 数据结构

### audit_log.detail JSON 格式

```json
{
  "product": {
    "id": 123,
    "product_name": "示例产品",
    "kpi": "...",
    "region": "巴西",
    "status": "存活",
    "mcc_id": 5,
    "customer": "...",
    "owner_id": 1,
    "runner_ids": "[1, 2]",
    "created_at": "2026-01-01 12:00:00"
  },
  "packages": [
    {"id": 456, "package_name": "...", "series_name": "...", "url": "...", "status": "存活"},
    {"id": 457, "package_name": "...", "series_name": "...", "url": "...", "status": "存活"}
  ],
  "asset_count": 3
}
```

## 风险评估

- **低风险**：改动集中在删除路径，不涉及核心业务流程
- **利用现有 is_archived 机制**：不需要修改任何现有查询，减少引入 bug 的风险
- **向后兼容**：新增字段有默认值，不影响现有数据
