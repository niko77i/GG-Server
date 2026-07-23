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

## 实际代码逻辑补充（2026-07-23 审计）

> 审计范围：对照 `py/database.py`（第 1–1142 行）的完整表定义、列迁移、数据迁移逻辑，逐项校验设计文档的准确性。**仅读取代码，未修改任何代码。**

---

### 1. 表数量修正：25 张表，非 24 张

`_ensure_schema()` 中共有 25 张 `CREATE TABLE IF NOT EXISTS`：

| # | 表名 | 文档是否涉及 |
|---|------|-------------|
| 1 | `video_history` | 未涉及 |
| 2 | `video_tasks` | 未涉及 |
| 3 | `videos` | 涉及 |
| 4 | `tags` | 未涉及 |
| 5 | `config` | 未涉及 |
| 6 | `mcc` | 涉及 |
| 7 | `accounts` | 涉及 |
| 8 | `account_mcc_history` | 涉及 |
| 9 | `recharge_records` | 涉及 |
| 10 | `sheets_sync_log` | 未涉及 |
| 11 | `copywritings` | 涉及 |
| 12 | `product_runners` | 涉及 |
| 13 | `products` | 涉及 |
| 14 | `packages` | 涉及 |
| 15 | `product_assets` | 涉及 |
| 16 | `video_consumption` | 涉及 |
| 17 | `ad_reports` | 涉及 |
| 18 | `regions` | 未涉及 |
| 19 | `users` | 涉及 |
| 20 | `scrape_cache` | 涉及 |
| 21 | `import_history` | 涉及 |
| 22 | `delist_checks` | 涉及 |
| 23 | `delist_notifications` | 涉及 |
| 24 | `audio_replace_history` | 未涉及 |
| 25 | `audit_log` | 涉及 |

文档描述为"24 张表"，实际为 **25 张**。未涉及的 7 张表（`video_history`、`video_tasks`、`tags`、`config`、`sheets_sync_log`、`regions`、`audio_replace_history`）均为无外键或仅作工具用途的表，不影响完整性分析的结论，但数量应修正。

---

### 2. 表关系图遗漏

#### 2.1 遗漏 FK：`video_consumption.product_id → products(id)`

代码（第 307–315 行）：

```sql
CREATE TABLE IF NOT EXISTS video_consumption (
    ...
    product_id INTEGER REFERENCES products(id),
    ...
);
```

文档关系图中只画了 `videos.id → video_consumption.video_id`，**遗漏了 `products.id → video_consumption.product_id`**。这意味着删除产品时，`video_consumption` 中的关联行会因 FK 约束导致删除失败（或产生孤儿数据，如果约束未启用）。这是一个文档未覆盖的完整性风险点，应在产品删除（问题 6 产品合并）中一并检查。

#### 2.2 遗漏 FK：`products.owner_id → users(id)`（列迁移添加）

代码第 101 行通过 `_add_column_if_missing` 补充：

```python
_add_column_if_missing(conn, "products", "owner_id", "owner_id INTEGER REFERENCES users(id)")
```

文档在"问题 4: 用户删除"中提到了 `products.owner_id → NULL` 的处理，说明文档作者知道此列存在，但关系图未画出。建议补入关系图。

#### 2.3 遗漏 FK：`mcc.owner_id → users(id)`（列迁移添加）

代码第 97 行：

```python
_add_column_if_missing(conn, "mcc", "owner_id", "owner_id INTEGER REFERENCES users(id)")
```

文档关系图中 `users` 下面列出了 `owner_id → accounts, mcc, products, videos, copywritings`，已覆盖 MCC，但未在 MCC 节点下单独标出。实际 FK 由列迁移添加，`_ensure_schema` 中的原始 CREATE TABLE 并不包含此列（第 177–187 行原始定义无 `owner_id`）。

#### 2.4 `account_mcc_history.old_mcc_id` / `new_mcc_id` 无 FK

代码第 209–210 行：

```sql
old_mcc_id INTEGER,
new_mcc_id INTEGER,
```

两个列均为裸 `INTEGER`，无 `REFERENCES mcc(id)`。文档在"问题 1"中提及此事，但关系图用实线连接 `mcc.id → account_mcc_history.old_mcc_id / new_mcc_id`，未标注"无 FK"。建议改为虚线或加注。

---

### 3. 列迁移逻辑（`_ensure_columns`）的隐含关系

`_ensure_columns()`（第 79–119 行）在每次 `get_db()` 连接时执行，以 `_add_column_if_missing` 幂等补列。以下是文档未覆盖但对完整性分析有影响的迁移列：

| 表 | 迁移列 | 含义 | 对完整性的影响 |
|----|--------|------|---------------|
| `videos` | `owner_id INTEGER REFERENCES users(id)` | 视频归属 | 用户删除时需处理（文档问题 4 已覆盖 ✅） |
| `videos` | `is_public INTEGER DEFAULT 0` | 公开标记 | 无 FK，不影响 |
| `accounts` | `owner_id INTEGER REFERENCES users(id)` | 账户归属 | 用户删除时需处理（文档问题 4 已覆盖 ✅） |
| `accounts` | `death_date TEXT` / `status_changed_date TEXT` | 业务字段 | 无 FK，不影响 |
| `mcc` | `owner_id INTEGER REFERENCES users(id)` | MCC 归属 | 用户删除时需处理（文档问题 4 已覆盖 ✅） |
| `mcc` | `shared_user_ids TEXT DEFAULT '[]'` | 共享用户 JSON 数组 | 非 FK，但包含用户 ID 引用，用户删除时 JSON 中的引用可能变成孤儿。**文档未覆盖此风险。** |
| `products` | `owner_id INTEGER REFERENCES users(id)` | 产品归属 | 文档问题 4 已覆盖 ✅ |
| `products` | `runner_ids TEXT DEFAULT '[]'` | runner JSON 数组 | 与 `product_runners` 表并行存在。**文档未覆盖 JSON 数组中的孤儿引用风险。** |
| `products` | `is_archived` / `customer` / `deleted_at` / `sales_person` / `agency_ratio` | 业务字段 | 无 FK，不影响 |
| `recharge_records` | `status` / `sheets_synced` / `sheets_error` | 业务字段 | 无 FK，不影响 |
| `copywritings` | `owner_id INTEGER REFERENCES users(id)` | 文案归属 | 文档问题 4 已覆盖 ✅ |
| `copywritings` | `effectiveness` / `is_public` | 业务字段 | 无 FK，不影响 |
| `users` | `custom_name` / `email` / `telegram_username` | 用户属性 | 无 FK，不影响 |

**关键发现**：`mcc.shared_user_ids` 和 `products.runner_ids` 是两个 JSON 数组列，存储用户 ID 但不受 FK 约束保护。用户删除时，这些 JSON 中的 ID 引用会变成孤儿——当前文档的问题 4 修复方案未包含清理这两个 JSON 列。

---

### 4. 数据迁移逻辑（文档未覆盖）

`_ensure_schema()`（第 122–541 行）包含多个仅在首次执行时触发的迁移逻辑，它们在数据库完整性方面有直接影响：

#### 4.1 `migrated_owner_id` — 存量数据归属（第 529–539 行）

```python
conn.execute("UPDATE videos SET owner_id = 1 WHERE owner_id IS NULL")
conn.execute("UPDATE accounts SET owner_id = 1 WHERE owner_id IS NULL")
conn.execute("UPDATE mcc SET owner_id = 1 WHERE owner_id IS NULL")
```

所有无主的历史数据被分配给 developer（用户 id=1）。如果 developer 账号被删除，大量数据将失去归属。**文档未讨论 developer 用户删除的特殊风险。**

#### 4.2 `_migrate_mcc_dedup` — MCC 去重合并（第 599–684 行）

合并重复 `mcc_id` 字符串的记录，更新 `products.mcc_id`、`accounts.mcc_id`、`mcc.parent_mcc_id` 指向主记录，并删除重复行。与文档的问题 5（MCC 删除）直接相关——去重逻辑本身就是一个批量"删除"操作，其关联清理策略（指向主记录而非删除关联数据）可以作为问题 5 修复方案的参考模式。

#### 4.3 `_migrate_mcc_share_runners` — 回填共享用户（第 544–596 行）

从已有产品的 `runner_ids` 中提取 runner，沿 MCC 上级链回填到 `mcc.shared_user_ids`。这建立了产品 runner 与 MCC 之间的隐含关联，且这些关联完全依赖 JSON 数组（无 FK）。**文档未覆盖此链路。**

#### 4.4 `migrated_product_runners_v2` — 关联表同步（第 493–523 行）

将 `products.runner_ids` JSON 列与 `product_runners` 关联表同步。说明系统中存在 JSON 列和关联表两套 runner 数据，文档对此未作说明。

---

### 5. 各问题的代码对照

#### 问题 1 — 账户删除 / account_mcc_history

- 文档描述 `account_mcc_history.account_id` 有 `ON DELETE CASCADE`：代码第 208 行确认为 `REFERENCES accounts(id) ON DELETE CASCADE` ✅
- 文档指出 `old_mcc_id` / `new_mcc_id` 无 FK：代码确认为裸 `INTEGER` ✅
- **补充**：`account_mcc_history.changed_by REFERENCES users(id)` 有 FK 但无 CASCADE。用户删除时若未显式 SET NULL，FK 约束会阻止删除。文档问题 4 的修复方案已包含此处理 ✅

#### 问题 2 — 视频删除

- `product_assets.video_id REFERENCES videos(id)`：代码第 298 行确认，**无 ON DELETE CASCADE**。因此直接 `DELETE FROM videos` 会因 FK 约束失败（而非静默产生孤儿）。文档建议手动清理是正确的 ✅
- `video_consumption.video_id REFERENCES videos(id)`：代码第 309 行确认，**无 ON DELETE CASCADE**，同上 ✅
- **补充**：`videos.id` 是 `TEXT PRIMARY KEY`（第 153 行），而 `product_assets.video_id` 也是 `TEXT`。这是 YouTube 视频 ID 字符串，不是自增整数。文档未明确指出此类型差异。

#### 问题 3 — 包删除

- `delist_checks.package_id REFERENCES packages(id)`：代码第 398–403 行确认有 FK，且为 `UNIQUE`，**无 CASCADE** ✅
- `delist_notifications.package_id`：代码第 411 行确认为 `INTEGER NOT NULL`，**无 FK** ✅
- **补充**：`delist_notifications` 有 `UNIQUE(package_id, user_id)`（第 416 行），文档未提及此约束。

#### 问题 4 — 用户删除

对照代码逐一验证 FK 约束：

| 关联列 | FK 约束 | 文档处理建议 | 评价 |
|--------|---------|-------------|------|
| `product_runners.user_id` | `REFERENCES users(id)` 无 CASCADE（第 262 行） | DELETE | ✅ 如不手动清理，FK 会阻止用户删除 |
| `product_assets.added_by` | `REFERENCES users(id)` 无 CASCADE（第 299 行） | SET NULL | ✅ |
| `video_consumption.user_id` | `REFERENCES users(id)` 无 CASCADE（第 310 行） | SET NULL 或 DELETE | 文档写"或 DELETE"，需确定策略 |
| `recharge_records.created_by` | `REFERENCES users(id)` 无 CASCADE（第 226 行） | SET NULL | ✅ |
| `account_mcc_history.changed_by` | `REFERENCES users(id)` 无 CASCADE（第 211 行） | SET NULL | ✅ |
| `audit_log.user_id` | `REFERENCES users(id)` 无 CASCADE（第 434 行） | DELETE | ✅ |
| `delist_notifications.user_id` | **无 FK**（第 412 行） | DELETE | ✅ 文档问题 8 已正确指出无 FK |

**遗漏的关联**（文档未列出）：
- `mcc.shared_user_ids`（JSON 数组，第 184 行）— 用户删除后 JSON 中残留孤儿 ID
- `products.runner_ids`（JSON 数组，第 102 行）— 同上

#### 问题 5 — MCC 删除

- `products.mcc_id REFERENCES mcc(id)`：代码第 274 行确认有 FK，**无 CASCADE** ✅。直接删除会因 FK 失败
- `accounts.mcc_id REFERENCES mcc(id)`：代码第 193 行确认有 FK，**无 CASCADE**。文档中 MCC 删除逻辑已检查 ✅
- `mcc.parent_mcc_id REFERENCES mcc(id)`：代码第 182 行确认自引用 FK，**无 CASCADE**。文档中 MCC 删除逻辑已检查子 MCC ✅
- **补充**：`mcc.mcc_id`（TEXT 业务 ID）和 `mcc.id`（INTEGER 主键）是两个不同的列。`accounts.mcc_id` 引用的是 `mcc.id`（INTEGER），而 `recharge_records.account_id` 引用的是 `accounts.account_id`（TEXT）。这种双重标识体系容易混淆，文档未作说明。

#### 问题 6 — 产品合并删除

- `product_assets.product_id REFERENCES products(id)`：代码第 297 行确认，**无 CASCADE**，且有 `UNIQUE(product_id, video_id)` ✅
- `delist_checks.product_id REFERENCES products(id)`：代码第 403 行确认，**无 CASCADE** ✅
- `product_runners.product_id REFERENCES products(id)`：代码第 261 行确认，**无 CASCADE**，联合主键 `PRIMARY KEY (product_id, user_id)` ✅
- **补充遗漏**：`packages.product_id` 也有 FK（第 290 行），文档在合并副产品的代码片段中已删除 packages ✅
- **补充遗漏**：`video_consumption.product_id REFERENCES products(id)`（第 311 行）— 文档未在问题 6 中列出此表。如果副产品有关联的消耗记录，这些行会因 FK 阻止删除。

#### 问题 7 — recharge_records.account_id 无 FK

- 代码确认第 221 行：`account_id TEXT NOT NULL`，无 `REFERENCES` ✅
- `accounts` 表有两套标识：`id INTEGER PK` 和 `account_id TEXT UNIQUE`（第 191–192 行）。`recharge_records` 用 TEXT 的 `account_id` 作关联，而非 INTEGER 的 `id`。这在设计上是合理选择（account_id 是业务主键），但确实无法加 FK 约束。
- 索引 `idx_recharge_account ON recharge_records(account_id)` 已存在（第 229 行） ✅

#### 问题 8 — delist_notifications 缺少 FK

- `package_id INTEGER NOT NULL`：代码第 411 行，无 FK ✅
- `user_id INTEGER NOT NULL`：代码第 412 行，无 FK ✅
- `UNIQUE(package_id, user_id)`：第 416 行，文档未提及 ✅
- 索引 `idx_delist_notif_user ON delist_notifications(user_id)`：第 418 行 ✅

---

### 6. 审计总结

| 类别 | 数量 | 说明 |
|------|------|------|
| 文档准确的描述 | 8/8 个问题核心分析 | 所有 FK 存在性、CASCADE 行为判断均正确 |
| 表数量偏差 | 1 处 | 24→25 |
| 关系图遗漏 FK | 2 处 | `video_consumption.product_id`、`products.owner_id` |
| 关系图未标注"无 FK" | 2 处 | `account_mcc_history.old/new_mcc_id` 应虚线 |
| 遗漏的完整性风险 | 3 处 | `mcc.shared_user_ids` 孤儿、`products.runner_ids` 孤儿、`video_consumption.product_id` 产品删除阻塞 |
| 未覆盖的迁移逻辑 | 4 处 | owner_id 迁移、MCC 去重、MCC 共享回填、runner 同步 |
| 文档总体评价 | **高质量** | 核心分析精准，FK 约束判断与代码完全一致。上述补充为增强完整性，不否定原文档结论。 |
