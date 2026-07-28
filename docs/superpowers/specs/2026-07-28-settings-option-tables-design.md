# 设置面板选项改为独立数据库表 + 外键关联

**日期**: 2026-07-28  
**状态**: 已实现（文档已同步实际实现差异）  
**方案**: 方案 A — 独立选项表 + 外键引用

---

## 1. 需求描述

当前设置面板的 4 个下拉选项（代理名、账户状态、MCC 等级、商务人员）以 JSON 数组形式存储在 `tags` 表（key-value）中，与数据表（`accounts.agent`、`products.sales_person` 等）完全独立，修改选项名称后已有数据不会同步更新。

**目标**：将这 4 个选项改为独立数据库表，数据表通过外键引用选项表。重命名选项时，所有引用自动生效（无需级联 UPDATE）；删除选项时，有引用则阻止删除保证数据完整性。

### 当前映射关系

| 设置项 (tags key) | 数据库表 | 数据库列（旧 TEXT） |
|---|---|---|
| `account_agents` | `accounts` | `agent` |
| `account_agents` | `recharge_records` | `agent` |
| `account_statuses` | `accounts` | `status` |
| `mcc_levels` | `mcc` | `level` |
| `sales_persons` | `products` | `sales_person` |

---

## 2. 数据库 Schema

### 2.1 新建 4 张选项表

```sql
-- 代理名
CREATE TABLE IF NOT EXISTS agents (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    owner_id INTEGER REFERENCES users(id),
    created_at TEXT DEFAULT (datetime('now','localtime'))
);

-- 账户状态
CREATE TABLE IF NOT EXISTS account_statuses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    owner_id INTEGER REFERENCES users(id),
    created_at TEXT DEFAULT (datetime('now','localtime'))
);

-- MCC 等级
CREATE TABLE IF NOT EXISTS mcc_levels (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    owner_id INTEGER REFERENCES users(id),
    created_at TEXT DEFAULT (datetime('now','localtime'))
);

-- 商务人员
CREATE TABLE IF NOT EXISTS sales_persons (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    owner_id INTEGER REFERENCES users(id),
    created_at TEXT DEFAULT (datetime('now','localtime'))
);
```

### 2.2 修改现有表（加外键列）

```sql
-- accounts 表
ALTER TABLE accounts ADD COLUMN agent_id INTEGER REFERENCES agents(id);
ALTER TABLE accounts ADD COLUMN status_id INTEGER REFERENCES account_statuses(id);

-- recharge_records 表
ALTER TABLE recharge_records ADD COLUMN agent_id INTEGER REFERENCES agents(id);

-- mcc 表
ALTER TABLE mcc ADD COLUMN level_id INTEGER REFERENCES mcc_levels(id);

-- products 表
ALTER TABLE products ADD COLUMN sales_person_id INTEGER REFERENCES sales_persons(id);
```

### 2.3 迁移后清理

```sql
-- 删除旧文本列（在 Step 5 执行）
ALTER TABLE accounts DROP COLUMN agent;
ALTER TABLE accounts DROP COLUMN status;
ALTER TABLE mcc DROP COLUMN level;
ALTER TABLE products DROP COLUMN sales_person;
ALTER TABLE recharge_records DROP COLUMN agent;

-- 删除 tags 表中的旧配置
DELETE FROM tags WHERE key IN (
  'account_agents', 'account_statuses', 'mcc_levels', 'sales_persons'
);
```

---

## 3. API 设计

### 3.1 选项 CRUD（4 套统一模式）

以 agents 为例，其他三张表同理：

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/agents/list` | 获取当前用户的代理列表 `[{id, name}]` |
| POST | `/api/agents/create` | 新增 `{name: "张三"}` |
| PUT | `/api/agents/<id>` | 重命名 `{name: "张三丰"}` |
| DELETE | `/api/agents/<id>` | 删除（有引用则阻止） |

对应的路由：
- `/api/statuses/list|create` + `/api/statuses/<id>`
- `/api/mcc-levels/list|create` + `/api/mcc-levels/<id>`
- `/api/sales-persons/list|create` + `/api/sales-persons/<id>`

### 3.2 重命名（核心优势）

因为外键存的是 ID，重命名只需更新选项表本身，**所有引用自动生效**：

```python
# PUT /api/agents/1 { name: "张三丰" }
db.execute("UPDATE agents SET name=? WHERE id=?", (new_name, aid))
# 无需 UPDATE accounts、recharge_records，JOIN 查询自动拿到新名字
```

### 3.3 删除保护

```python
# DELETE /api/agents/1
# 检查引用计数
refs = []
acct_count = db.execute("SELECT COUNT(*) FROM accounts WHERE agent_id=?", (aid,)).fetchone()[0]
if acct_count > 0: refs.append(f"{acct_count} 个账户")
rech_count = db.execute("SELECT COUNT(*) FROM recharge_records WHERE agent_id=?", (aid,)).fetchone()[0]
if recharges > 0: refs.append(f"{rech_count} 条充值记录")

if refs:
    return {"success": False, "error": f"无法删除：被 {'、'.join(refs)} 引用"}, 409

db.execute("DELETE FROM agents WHERE id=?", (aid,))
```

### 3.4 设置 API 兼容

`GET/POST /api/settings/account` 改为从新选项表读取（4 表），`recharge_sheet_id` 仍从 `tags` 表读写。

**重要**：`recharge_sheet_id` 在 `tags` 表中以 JSON 字符串格式存储（历史遗留），GET 必须用 `_json.loads()` 解包，POST 必须用 `_json.dumps()` 编码。否则会出现双引号被 URL 编码导致 Google Sheets API 404 的问题。

```python
# GET - 从新选项表读取 + tags 表读取 recharge_sheet_id/sheet_mappings
result["recharge_sheet_id"] = _json.loads(row["value"])  # JSON 解包

# POST - 只保存 recharge_sheet_id 和 sheet_mappings
db.execute("INSERT OR REPLACE INTO tags(key,value) VALUES(?,?)",
           ("recharge_sheet_id", _json.dumps(data["recharge_sheet_id"], ensure_ascii=False)))
```

### 3.5 业务 API 适配

所有涉及旧文本字段的 API 改为读写 `_id` 列：

**查询时 JOIN 选项表返回名称**（全部使用 LEFT JOIN，避免 agent_id/status_id 为 NULL 的记录丢失）：

```python
# 账户列表查询示例
db.execute("""
    SELECT a.*, ag.name as agent_name, st.name as status_name
    FROM accounts a
    LEFT JOIN agents ag ON a.agent_id = ag.id
    LEFT JOIN account_statuses st ON a.status_id = st.id
""")
```

**筛选改为外键子查询**：

```python
# 状态筛选 — 通过 status_id 匹配
if status:
    where.append("a.status_id IN (SELECT id FROM account_statuses WHERE name=? AND owner_id=?)")

# 代理筛选 — 通过 agent_id 匹配
if agent:
    where.append("a.agent_id IN (SELECT id FROM agents WHERE name LIKE ? AND owner_id=?)")
```

**创建/更新时只写 `_id` 列**（移除旧文本列的读写）：

```python
# INSERT — 不含 agent/status 文本列
db.execute(
    "INSERT INTO accounts(name,account_id,agent_id,status_id,...) VALUES(?,?,?,?,...)",
    (name, account_id, agent_id, status_id, ...))

# UPDATE — 只更新 _id 列
allowed = ["status_id", "agent_id", "mcc_id", "timezone"]
```

**状态排序**：`account_statuses` 列表按固定顺序返回（存活→死亡→验证→限额→其他），通过 CASE 表达式实现：

```python
ORDER BY CASE name WHEN '存活' THEN 1 WHEN '死亡' THEN 2
WHEN '验证' THEN 3 WHEN '限额' THEN 4 ELSE 5 END, id
```

### 3.6 缓存清理

修改选项后清除相关缓存：
```python
_app_cache.delete(f"accounts:agents:{user_id}")
```

---

## 4. 前端改造清单

### 4.1 设置面板

| 文件 | 改动 |
|------|------|
| [SettingsPanel.vue](frontend/src/views/SettingsPanel.vue) | 4 个 textarea 替换为表格组件：显示名称列表、行内编辑重命名、新增按钮、删除按钮（有引用时阻止） |
| [accounts.js](frontend/src/stores/accounts.js#L17) | `settings` 从 `string[]` 改为 `{id, name}[]`，新增按类型拉取选项的 action |

### 4.2 下拉框消费方 — 按选项分类

**所有下拉框统一改为 ID 模式**：`:value="item.id"` `:label="item.name"`，移除 `allow-create`（选项统一在设置面板管理）。

#### account_agents (代理名)

| 文件 | 行号 | 改动 |
|------|------|------|
| [AccountModal.vue](frontend/src/components/AccountModal.vue#L30) | 多处 | 下拉 `:value="a.id"` `:label="a.name"`；提交用 `agent_id`；**移除**自动追加逻辑 |
| [AccountBatchImportModal.vue](frontend/src/components/AccountBatchImportModal.vue#L94) | 3 处下拉 | 同上 + 表格显示用 `agentNameById` 辅助函数 |
| [AdsAccountPanel.vue](frontend/src/views/AdsAccountPanel.vue#L142) | 筛选+批量 | 筛选从 `store.options.agents` 读取；批量改代理传 `agent_id` |

#### account_statuses (账户状态)

| 文件 | 行号 | 改动 |
|------|------|------|
| [AccountModal.vue](frontend/src/components/AccountModal.vue#L35) | 多处 | 下拉 `:value="s.id"` `:label="s.name"`；提交用 `status_id` |
| [AccountBatchImportModal.vue](frontend/src/components/AccountBatchImportModal.vue#L103) | 3 处下拉 | 同上 + `statusNameById` 辅助函数 |
| [AdsAccountPanel.vue](frontend/src/views/AdsAccountPanel.vue#L13) | 筛选+批量 | `store.options.statuses`；批量改状态传 `status_id`，确认对话框显示名称而非 ID；`availableStatuses` 适配 `{id, name}[]` |

#### mcc_levels (MCC 等级)

| 文件 | 行号 | 改动 |
|------|------|------|
| [MccModal.vue](frontend/src/components/MccModal.vue#L13) | 下拉+提交 | `store.options.mccLevels`；提交用 `level_id` |

#### sales_persons (商务人员)

| 文件 | 行号 | 改动 |
|------|------|------|
| [ProductModal.vue](frontend/src/components/ProductModal.vue#L55) | 下拉+提交 | `accountStore.options.salesPersons`；提交用 `sales_person_id` |

### 4.3 Store 适配

[accounts.js](frontend/src/stores/accounts.js) 增加：
- `agents: []`、`statuses: []`、`mccLevels: []`、`salesPersons: []` 状态
- `loadAgents()`、`loadStatuses()` 等加载方法
- `createAgent(name)`、`renameAgent(id, name)`、`deleteAgent(id)` 等操作方法

---

## 5. 数据迁移策略

### 5.1 迁移流程（按顺序，不可跳跃）

```
Step 1 — 建新表 + 加新列（不影响现有逻辑）
  创建 agents, account_statuses, mcc_levels, sales_persons
  给 accounts, recharge_records, mcc, products 加 _id 列

Step 2 — 数据迁移（在事务中执行）
  2a. 从旧文本列提取去重值 → 插入新选项表（按 owner_id 隔离）
  2b. 更新外键列（文本匹配）
  2c. 验证外键列覆盖率 = 100%

Step 3 — 切换代码
  前后端改造完成 → 读写走新表 + 外键列

Step 4 — 清理
  删旧文本列 + 删 tags 表旧配置
```

### 5.2 关键 SQL

```sql
-- Step 2a: 迁移代理名（以 agents 为例）
INSERT INTO agents(name, owner_id)
SELECT DISTINCT a.agent, a.owner_id
FROM accounts a
WHERE a.agent != '' AND a.agent IS NOT NULL
  AND NOT EXISTS (SELECT 1 FROM agents ag WHERE ag.name = a.agent AND ag.owner_id = a.owner_id);

-- recharge_records 的 agent 也需迁移（通过 accounts 关联 owner_id）
INSERT INTO agents(name, owner_id)
SELECT DISTINCT r.agent, a.owner_id
FROM recharge_records r
JOIN accounts a ON a.account_id = r.account_id
WHERE r.agent != '' AND r.agent IS NOT NULL
  AND NOT EXISTS (SELECT 1 FROM agents ag WHERE ag.name = r.agent AND ag.owner_id = a.owner_id);

-- Step 2b: 更新外键
UPDATE accounts SET agent_id = (
  SELECT ag.id FROM agents ag
  WHERE ag.name = accounts.agent AND ag.owner_id = accounts.owner_id
) WHERE accounts.agent != '' AND accounts.agent IS NOT NULL;

UPDATE recharge_records SET agent_id = (
  SELECT ag.id FROM agents ag
  JOIN accounts a ON a.account_id = recharge_records.account_id
  WHERE ag.name = recharge_records.agent AND ag.owner_id = a.owner_id
) WHERE recharge_records.agent != '' AND recharge_records.agent IS NOT NULL;

-- statuses
INSERT INTO account_statuses(name, owner_id)
SELECT DISTINCT status, owner_id FROM accounts WHERE status != '' AND status IS NOT NULL;

UPDATE accounts SET status_id = (
  SELECT id FROM account_statuses
  WHERE name = accounts.status AND owner_id = accounts.owner_id
) WHERE accounts.status != '' AND accounts.status IS NOT NULL;

-- mcc_levels
INSERT INTO mcc_levels(name, owner_id)
SELECT DISTINCT m.level, m.owner_id FROM mcc m WHERE m.level != '' AND m.level IS NOT NULL;

UPDATE mcc SET level_id = (
  SELECT id FROM mcc_levels WHERE name = mcc.level AND owner_id = mcc.owner_id
) WHERE mcc.level != '' AND mcc.level IS NOT NULL;

-- sales_persons
INSERT INTO sales_persons(name, owner_id)
SELECT DISTINCT p.sales_person, p.owner_id FROM products p WHERE p.sales_person != '' AND p.sales_person IS NOT NULL;

UPDATE products SET sales_person_id = (
  SELECT id FROM sales_persons WHERE name = products.sales_person AND owner_id = products.owner_id
) WHERE products.sales_person != '' AND products.sales_person IS NOT NULL;

-- Step 2c: 验证
SELECT COUNT(*) AS unmatched FROM accounts WHERE agent != '' AND agent IS NOT NULL AND agent_id IS NULL;
SELECT COUNT(*) AS unmatched FROM accounts WHERE status != '' AND status IS NOT NULL AND status_id IS NULL;
SELECT COUNT(*) AS unmatched FROM recharge_records WHERE agent != '' AND agent IS NOT NULL AND agent_id IS NULL;
SELECT COUNT(*) AS unmatched FROM mcc WHERE level != '' AND level IS NOT NULL AND level_id IS NULL;
SELECT COUNT(*) AS unmatched FROM products WHERE sales_person != '' AND sales_person IS NOT NULL AND sales_person_id IS NULL;
-- 全部应返回 0
```

### 5.3 边缘情况处理（实际发现）

**recharge_records 孤儿记录**：部分 `recharge_records` 的 `account_id` 在 `accounts` 表中无匹配。回退策略：
1. 以 `owner_id=1`（管理员）插入缺失的 agent 名称
2. 再按纯名称匹配（`ORDER BY owner_id ASC LIMIT 1`）填充 `agent_id`

**products owner_id 为 NULL**：SQLite 中 `NULL = NULL` 不成立，导致子查询无结果。添加回退 UPDATE：当 `products.owner_id IS NULL` 时，使用 `sales_persons.owner_id IS NULL` 进行匹配。

**SQLite UNIQUE 约束中 NULL 的特殊处理**：SQLite 在 UNIQUE 约束中把每个 NULL 视为不同值，因此 `owner_id=NULL` 的同名记录可能产生重复行。当前数据未触发，但需注意。

### 5.4 保障措施

- Step 1~2 期间旧列和新列并存，现有代码照常运行
- 迁移在事务中执行，失败回滚
- 采用幂等性门控 `COUNT(*) WHERE agent_id IS NOT NULL > 0` 确保只执行一次
- recharge_records 没有 `owner_id`，通过 `JOIN accounts ON account_id` 关联
- 同一代理名可能在不同用户下是不同的代理，迁移时通过 `accounts.owner_id` 区分

### 5.5 关键注意事项：`_add_column_if_missing` 冲突

**`_ensure_columns()` 中的 `_add_column_if_missing(conn, "products", "sales_person", ...)` 必须在代码中移除**。因为：
1. 迁移 → cleanup 删除了 `products.sales_person` 列
2. `_ensure_columns()` 在每次数据库连接时执行
3. 如果该行保留，下次连接时 `sales_person` 列会被自动复活

此问题已确认：部署后发现 `products.sales_person` 列被意外复活（0 条非空数据但列存在）。修复后删除该行，并手动 DROP COLUMN 清理。

---

## 6. 涉及文件总览

### 后端 (py/)

| 文件 | 改动 |
|------|------|
| `database.py` | 新增 4 张表；accounts/recharge_records/mcc/products 加外键列；迁移函数 |
| `main.py` | 新增 16 个 API（4 表 × CRUD）；适配现有业务 API 走外键；旧 settings API 兼容 |

### 前端 (frontend/src/)

| 文件 | 改动 |
|------|------|
| `views/SettingsPanel.vue` | textarea → 表格组件 |
| `stores/accounts.js` | 新增选项数据状态和方法 |
| `components/AccountModal.vue` | 下拉走 ID；移除自动追加逻辑 |
| `components/AccountBatchImportModal.vue` | 3 处下拉走 ID；移除自动追加逻辑 |
| `components/MccModal.vue` | 下拉走 ID |
| `components/ProductModal.vue` | 下拉走 ID |
| `views/AdsAccountPanel.vue` | 筛选下拉改为 API 模式 |

---

## 7. 风险与注意事项

1. **recharge_records 迁移**：没有 owner_id，需 JOIN accounts 获取。孤儿记录（account_id 在 accounts 表中无匹配）通过 owner_id=1 兜底 + 纯名称回退匹配处理。
2. **导入/导出功能**：`dataApi.importFile/exportData` 需要适配新字段结构。导入时选项表先于业务表导入，建立 ID 映射后重映射外键。
3. **Google Sheets 同步**：充值表同步的 `agent` 文本字段通过 JOIN agents 表获取名称，`status` 使用已解析的文本名（非原始 ID）。
4. **默认数据**：`account_statuses` 有默认值 `["存活","死亡","验证","限额"]`，迁移时通过 `INSERT OR IGNORE ... SELECT DISTINCT` 从旧数据导入。状态列表排序通过 CASE 表达式确保固定顺序。
5. **SQLite 版本**：当前环境 3.45.1，支持 `ALTER TABLE DROP COLUMN`，可直接删除旧列。
6. **`_add_column_if_missing` 冲突**（已修复）：`_ensure_columns()` 中 `products.sales_person` 的 `_add_column_if_missing` 会在每次连接时复活已被 cleanup 删除的列，必须移除。其他旧列（accounts.agent, accounts.status 等）无此问题，因为 `_ensure_columns()` 中没有对应的 `_add_column_if_missing` 调用。
7. **`recharge_sheet_id` JSON 编码**（已修复）：旧代码以 `_json.dumps()` 存储，新 settings API 必须用 `_json.loads()` 读取。否则会返回带引号的 JSON 字符串，导致 Google Sheets API 收到 URL 编码的假 ID。
8. **`_ensure_schema` CREATE TABLE 定义**：建表语句中仍定义了已删除的旧列（`accounts.agent`, `accounts.status`, `mcc.level`, `recharge_records.agent`），对已有数据库无害（IF NOT EXISTS），但新部署时会先创建再被 cleanup 删除，属于不必要的操作。建议后续清理。
