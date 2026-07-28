# 设置面板选项改为独立数据库表 + 外键关联

**日期**: 2026-07-28  
**状态**: 设计中  
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

### 3.4 旧设置 API 兼容

`GET/POST /api/settings/account` 改为从新表读写，过渡期间保持兼容。

### 3.5 业务 API 适配

现有接口涉及 `agent`、`status`、`level`、`sales_person` 文本字段的，创建/更新时改为写入对应的 `_id` 列，查询时 JOIN 选项表返回 `name`：

```python
# 账户列表查询示例
db.execute("""
    SELECT a.*, ag.name as agent_name, st.name as status_name
    FROM accounts a
    LEFT JOIN agents ag ON a.agent_id = ag.id
    LEFT JOIN account_statuses st ON a.status_id = st.id
""")

# 创建账户
db.execute(
    "INSERT INTO accounts(name,account_id,agent_id,status_id,...) VALUES(?,?,?,?,...)",
    (name, account_id, agent_id, status_id, ...)
)
```

### 3.6 缓存清理

修改选项后清除相关缓存：
```python
_app_cache.delete(f"accounts:agents:{user_id}")
_app_cache.delete(f"accounts:statuses:{user_id}")
```

---

## 4. 前端改造清单

### 4.1 设置面板

| 文件 | 改动 |
|------|------|
| [SettingsPanel.vue](frontend/src/views/SettingsPanel.vue) | 4 个 textarea 替换为表格组件：显示名称列表、行内编辑重命名、新增按钮、删除按钮（有引用时阻止） |
| [accounts.js](frontend/src/stores/accounts.js#L17) | `settings` 从 `string[]` 改为 `{id, name}[]`，新增按类型拉取选项的 action |

### 4.2 下拉框消费方 — 按选项分类

#### account_agents (代理名)

| 文件 | 行号 | 改动 |
|------|------|------|
| [AccountModal.vue](frontend/src/components/AccountModal.vue#L30) | L30 | 下拉 `:value` 从文本改为 `a.id`，`:label="a.name"` |
| [AccountModal.vue](frontend/src/components/AccountModal.vue#L196-L200) | L196-200 | **移除**自动追加新名称到 settings 的逻辑 |
| [AccountBatchImportModal.vue](frontend/src/components/AccountBatchImportModal.vue#L94) | L94, L185, L245 | 三处下拉 `:value` 改为 `a.id` |
| [AccountBatchImportModal.vue](frontend/src/components/AccountBatchImportModal.vue#L636-L648) | L636-648 | **移除**自动追加逻辑 |
| [AdsAccountPanel.vue](frontend/src/views/AdsAccountPanel.vue#L142) | L142 | 筛选下拉改为从 API 拉取，不再手动合并 `store.settings` |

#### account_statuses (账户状态)

| 文件 | 行号 | 改动 |
|------|------|------|
| [AccountModal.vue](frontend/src/components/AccountModal.vue#L35) | L35 | 下拉 `:value` 改为 `s.id`，`:label="s.name"` |
| [AccountBatchImportModal.vue](frontend/src/components/AccountBatchImportModal.vue#L103) | L103, L194, L252 | 三处下拉改为 ID 模式 |
| [AdsAccountPanel.vue](frontend/src/views/AdsAccountPanel.vue#L13) | L13 | 筛选下拉改为 API 模式，L150 状态合并逻辑调整 |

#### mcc_levels (MCC 等级)

| 文件 | 行号 | 改动 |
|------|------|------|
| [MccModal.vue](frontend/src/components/MccModal.vue#L13) | L13 | 下拉 `:value` 改为 `l.id`，`:label="l.name"` |

#### sales_persons (商务人员)

| 文件 | 行号 | 改动 |
|------|------|------|
| [ProductModal.vue](frontend/src/components/ProductModal.vue#L55) | L55 | `salesPersonOptions` computed 改为从 store 读取 `{id, name}[]`，下拉用 ID |

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

### 5.3 保障措施

- Step 1~2 期间旧列和新列并存，现有代码照常运行
- 迁移在事务中执行，失败回滚
- 迁移脚本预留 dry-run 模式，先验证再执行
- recharge_records 没有 `owner_id`，通过 `JOIN accounts ON account_id` 关联

### 5.4 特殊处理：recharge_records 存在跨用户同名代理

同一代理名可能在不同用户下是不同的代理，迁移时通过 `accounts.owner_id` 区分。

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

1. **recharge_records 迁移**：没有 owner_id，需 JOIN accounts 获取，同名跨用户需谨慎
2. **导入/导出功能**：`dataApi.importFile/exportData` 需要适配新字段结构
3. **Google Sheets 同步**：充值表同步如果涉及 agent 字段需要适配
4. **默认数据**：`account_statuses` 有默认值 `["存活","死亡","验证","限额"]`，迁移时需预置
5. **SQLite 版本**：当前环境 3.45.1，支持 `ALTER TABLE DROP COLUMN`，可直接删除旧列
