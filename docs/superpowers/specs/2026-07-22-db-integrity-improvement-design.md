# 数据库完整性改进 — 关联表增删改查补充

> 日期: 2026-07-22
> 类型: 数据库优化 / 数据完整性修复

## 一、需求背景

当前项目使用 SQLite 数据库，有 24 张表，表之间存在大量关联关系。经审查发现，多个删除操作用缺少对关联数据的清理，导致**孤儿数据**（orphan data）问题。

## 二、表关系图

```
users (中心)
  ├── owner_id → accounts, mcc, products, videos, copywritings
  ├── user_id  → ad_reports, import_history, product_runners, video_consumption, delist_notifications
  ├── created_by → recharge_records, users(自引用)
  ├── changed_by → account_mcc_history
  ├── added_by → product_assets
  ├── scraped_by → scrape_cache
  └── user_id → audit_log

accounts
  ├── account_id (TEXT, 无FK) → recharge_records.account_id
  ├── id (INT, CASCADE) → account_mcc_history.account_id
  └── mcc_id → mcc.id

mcc
  ├── id → accounts.mcc_id, products.mcc_id
  ├── id → mcc.parent_mcc_id (自引用)
  └── id → account_mcc_history.old_mcc_id / new_mcc_id

products
  ├── id → packages.product_id
  ├── id → product_assets.product_id
  ├── id → product_runners.product_id
  └── id → delist_checks.product_id

packages
  ├── id → delist_checks.package_id
  └── id → delist_notifications.package_id (无FK)

videos
  ├── id → product_assets.video_id
  └── id → video_consumption.video_id
```

## 三、发现的问题

### 问题 1: 账户删除 — account_mcc_history 仅依赖 CASCADE

**位置**: [main.py:3653-3666](py/main.py#L3653-L3666) `accounts_delete` / [main.py:3669-3687](py/main.py#L3669-L3687) `accounts_batch_delete`

**现状**:
- `recharge_records` 手动清理了 ✅
- `account_mcc_history` 依赖 `ON DELETE CASCADE` 自动清理
- 但 `account_mcc_history.old_mcc_id` / `new_mcc_id` 没有 FK 约束，MCC 被删后这些引用变成孤儿

**风险**: 依赖隐式 CASCADE，如果某次操作关闭了 `PRAGMA foreign_keys`，历史记录会残留。建议显式清理，增加健壮性。

**建议**: 中优先级 — 当前 foreign_keys=ON 时正常工作，仅加固。

---

### 问题 2: 视频删除 — 关联数据未清理 ⚠️ 严重

**位置**: [main.py:1711-1729](py/main.py#L1711-L1729) `youtube_delete`

**现状**:
```python
# 仅删除 videos 表记录
db.execute("DELETE FROM videos WHERE id=?", (vid,))
```

**未清理的表**:
- ❌ `product_assets` — 视频删除后，产品-素材关联仍存在，查询会出错
- ❌ `video_consumption` — 视频删除后，消耗记录仍在，数据不一致

**建议**: **高优先级**，删除视频前清理 `product_assets` 和 `video_consumption`。

---

### 问题 3: 包删除 — delist_notifications 未清理 ⚠️ 严重

**位置**: [main.py:2689-2700](py/main.py#L2689-L2700) `products_delete_package` / [main.py:2703-2718](py/main.py#L2703-L2718) `products_batch_delete_packages`

**现状**:
```python
db.execute("DELETE FROM delist_checks WHERE package_id=?", (pkg_id,))
db.execute("DELETE FROM packages WHERE id=?", (pkg_id,))
```

**未清理的表**:
- ❌ `delist_notifications` — 包删除了，通知状态仍然存在

另外 `delist_notifications.package_id` **没有 FOREIGN KEY 约束**，无法通过 CASCADE 自动清理。

**建议**: **高优先级**，删除包前清理 `delist_notifications`。

---

### 问题 4: 用户删除 — 大量关联数据未清理 ⚠️ 严重

**位置**: [main.py:5406-5441](py/main.py#L5406-L5441) `admin_delete_user`

**现状**:
- ✅ `users.created_by` → NULL
- ✅ `products.owner_id` → NULL
- ✅ `accounts.owner_id` → NULL
- ✅ `mcc.owner_id` → NULL
- ✅ `videos.owner_id` → NULL
- ✅ `copywritings.owner_id` → NULL
- ✅ `scrape_cache.scraped_by` → NULL
- ✅ `import_history` → DELETE
- ✅ `ad_reports` → DELETE

**未清理的表**:
- ❌ `product_runners` — user_id FK，用户删了 runner 关联还在
- ❌ `product_assets` — added_by FK
- ❌ `video_consumption` — user_id FK
- ❌ `recharge_records` — created_by FK
- ❌ `account_mcc_history` — changed_by FK
- ❌ `audit_log` — user_id FK
- ❌ `delist_notifications` — user_id FK

**建议**: **高优先级**，补充所有遗漏的关联清理。

---

### 问题 5: MCC 删除 — products.mcc_id 未检查 ⚠️ 中等

**位置**: [main.py:4251-4276](py/main.py#L4251-L4276) `mcc_delete` / [main.py:4279-4310](py/main.py#L4279-L4310) `mcc_batch_delete`

**现状**: 检查了子 MCC 和关联账户，但**未检查产品**:
```python
children = db.execute("SELECT COUNT(*) FROM mcc WHERE parent_mcc_id=?", (mid,)).fetchone()[0]
acct_count = db.execute("SELECT COUNT(*) FROM accounts WHERE mcc_id=?", (mid,)).fetchone()[0]
```

而 `products` 表有 `mcc_id INTEGER REFERENCES mcc(id)` 外键。如果有产品关联到此 MCC，删除会因 FK 约束失败（这是好事），但错误信息不友好。应提前检查并给出友好提示。

**建议**: **中优先级**，加入 products 检查。

---

### 问题 6: 产品合并删除 — 关联数据未完整清理

**位置**: [main.py:2432-2513](py/main.py#L2432-L2513) `products_merge`

**现状**: 合并副产品时:
```python
db.execute("DELETE FROM packages WHERE product_id=?", (mid,))
db.execute("DELETE FROM products WHERE id=?", (mid,))
```

**未清理的表**:
- ❌ `product_assets` — 副产品的成效素材关联未清理
- ❌ `delist_checks` — 副产品的掉包检测未清理
- ❌ `product_runners` — 副产品的 runner 关联未清理

**建议**: **高优先级**，删除副产品前清理所有关联。

---

### 问题 7: recharge_records.account_id 无 FK 约束

**位置**: [database.py:169-180](py/database.py#L169-L180)

**现状**: `recharge_records.account_id` 定义为 `TEXT NOT NULL`，没有 FOREIGN KEY 约束到 `accounts.account_id`。

虽然有手动清理逻辑，但依赖代码而非数据库约束来保证完整性。

**建议**: **低优先级** — 当前有手动清理，考虑加索引但暂不加 FK（因为 account_id 是 TEXT 类型，不是 accounts.id INTEGER）。

---

### 问题 8: delist_notifications 缺少外键约束

**位置**: [database.py:344-353](py/database.py#L344-L353)

**现状**: `delist_notifications.package_id` 和 `user_id` 都没有 FOREIGN KEY 约束。

**建议**: **中优先级** — 无法加 FK（SQLite 不支持 ALTER TABLE ADD CONSTRAINT），但需要在代码层面保证清理。

---

## 四、修复方案

### 4.1 视频删除 — 补充关联清理

**文件**: `py/main.py`
**改动**: `youtube_delete` 函数

在 `DELETE FROM videos` 之前增加:
```python
# 清理关联数据
db.execute(f"DELETE FROM product_assets WHERE video_id IN ({placeholders})", ids)
db.execute(f"DELETE FROM video_consumption WHERE video_id IN ({placeholders})", ids)
```

### 4.2 包删除 — 补充 delist_notifications 清理

**文件**: `py/main.py`
**改动**: `products_delete_package` 和 `products_batch_delete_packages`

在删除 delist_checks 之后、删除包之前增加:
```python
db.execute("DELETE FROM delist_notifications WHERE package_id=?", (pkg_id,))
# 或批量:
db.execute(f"DELETE FROM delist_notifications WHERE package_id IN ({placeholders})", ids)
```

### 4.3 用户删除 — 补充全部遗漏的关联清理

**文件**: `py/main.py`
**改动**: `admin_delete_user` 函数

在现有清理之后、`DELETE FROM users` 之前增加:
```python
conn.execute("DELETE FROM product_runners WHERE user_id = ?", (uid,))
conn.execute("UPDATE product_assets SET added_by = NULL WHERE added_by = ?", (uid,))
conn.execute("UPDATE video_consumption SET user_id = NULL WHERE user_id = ?", (uid,))  # 或 DELETE
conn.execute("UPDATE recharge_records SET created_by = NULL WHERE created_by = ?", (uid,))
conn.execute("UPDATE account_mcc_history SET changed_by = NULL WHERE changed_by = ?", (uid,))
conn.execute("DELETE FROM audit_log WHERE user_id = ?", (uid,))
conn.execute("DELETE FROM delist_notifications WHERE user_id = ?", (uid,))
```

### 4.4 MCC 删除 — 补充产品检查

**文件**: `py/main.py`
**改动**: `mcc_delete` 和 `mcc_batch_delete`

增加产品关联检查:
```python
prod_count = db.execute("SELECT COUNT(*) FROM products WHERE mcc_id=?", (mid,)).fetchone()[0]
if prod_count > 0:
    return error(f"该 MCC 下有 {prod_count} 个关联产品，请先解除关联")
```

### 4.5 产品合并 — 补充关联清理

**文件**: `py/main.py`
**改动**: `products_merge` 函数

在删除副产品之前增加:
```python
db.execute("DELETE FROM product_assets WHERE product_id=?", (mid,))
db.execute("DELETE FROM delist_checks WHERE product_id=?", (mid,))
db.execute("DELETE FROM product_runners WHERE product_id=?", (mid,))
```

### 4.6 账户删除 — 显式清理 account_mcc_history（加固）

**文件**: `py/main.py`
**改动**: `accounts_delete` 和 `accounts_batch_delete`

增加显式清理:
```python
db.execute("DELETE FROM account_mcc_history WHERE account_id=?", (aid,))
```

## 五、涉及文件

| 文件 | 改动内容 |
|------|----------|
| `py/main.py` | 6 处删除操作的关联清理补充 |
| `py/database.py` | 可能需要加索引（可选） |

## 六、影响评估

- **风险**: 低。所有改动均为**补充清理**，不改变现有业务逻辑
- **测试**: 需要验证删除操作后，关联表是否正确清理
- **数据库迁移**: 不需要（不改 schema，仅改代码逻辑）
- **回滚**: 简单（仅改 Python 代码）
