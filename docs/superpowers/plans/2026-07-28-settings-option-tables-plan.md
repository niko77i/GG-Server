# 设置面板选项改为独立数据库表 + 外键关联 — 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 4 个设置选项（代理名、账户状态、MCC 等级、商务人员）从 tags 表 JSON 数组改为独立数据库表，通过外键关联实现重命名自动生效、删除保护。

**Architecture:** 新建 4 张选项表（agents, account_statuses, mcc_levels, sales_persons），给现有业务表加外键列，原有文本列保留做数据迁移。迁移完成后代码切换到读写外键列，最后删除旧列。前端设置面板 4 个 textarea 改为行内编辑表格，所有下拉框改为 ID 模式。

**Tech Stack:** Python Flask + SQLite 3.45.1 + Vue 3 + Pinia + Element Plus

## Global Constraints

- SQLite 3.45.1 支持 `ALTER TABLE DROP COLUMN`
- 每个选项表带 `owner_id` 用户隔离
- 删除选项时检查引用，有引用则阻止并返回 409
- 重命名选项无需级联 UPDATE（JOIN 自动生效）
- 迁移期间旧列和新列共存，代码逐步切换
- 所有 SQL 操作在事务中执行

---

## File Structure

```
py/
├── database.py          # 修改：_migrate_if_needed() 加迁移函数
├── main.py              # 修改：新增 16 个选项 API + 适配现有业务 API
└── data_service.py      # 修改：导入/导出适配新字段

frontend/src/
├── api/accounts.js      # 修改：新增 4 组选项 API 方法
├── stores/accounts.js   # 修改：新增 options state + actions
├── views/
│   ├── SettingsPanel.vue        # 重写：textarea → 表格组件
│   └── AdsAccountPanel.vue      # 修改：筛选下拉走 API
├── components/
│   ├── AccountModal.vue         # 修改：下拉走 ID，移除自动追加逻辑
│   ├── AccountBatchImportModal.vue  # 修改：3 处下拉走 ID，移除自动追加逻辑
│   ├── MccModal.vue             # 修改：下拉走 ID
│   └── ProductModal.vue         # 修改：下拉走 ID
```

---

### Task 1: 数据库 — 新建选项表

**Files:**
- Modify: `py/database.py` — `_ensure_schema()` 加建表 SQL

**Interfaces:**
- Produces: 4 张新表 `agents`, `account_statuses`, `mcc_levels`, `sales_persons`

- [ ] **Step 1: 在 `_ensure_schema()` 中添加建表语句**

在 `py/database.py` 的 `_ensure_schema()` 函数末尾（PRAGMA 语句之前），添加建表语句。找到现有 `CREATE TABLE IF NOT EXISTS` 块的最后一个，在其后添加：

```python
# 选项表（设置面板下拉选项独立管理，支持外键关联和重命名自动生效）
conn.execute("""
    CREATE TABLE IF NOT EXISTS agents (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        owner_id INTEGER REFERENCES users(id),
        created_at TEXT DEFAULT (datetime('now','localtime')),
        UNIQUE(name, owner_id)
    )
""")
conn.execute("""
    CREATE TABLE IF NOT EXISTS account_statuses (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        owner_id INTEGER REFERENCES users(id),
        created_at TEXT DEFAULT (datetime('now','localtime')),
        UNIQUE(name, owner_id)
    )
""")
conn.execute("""
    CREATE TABLE IF NOT EXISTS mcc_levels (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        owner_id INTEGER REFERENCES users(id),
        created_at TEXT DEFAULT (datetime('now','localtime')),
        UNIQUE(name, owner_id)
    )
""")
conn.execute("""
    CREATE TABLE IF NOT EXISTS sales_persons (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        owner_id INTEGER REFERENCES users(id),
        created_at TEXT DEFAULT (datetime('now','localtime')),
        UNIQUE(name, owner_id)
    )
""")
```

- [ ] **Step 2: 在 `_ensure_columns()` 中添加外键列**

在 `py/database.py` 的 `_ensure_columns()` 函数末尾添加：

```python
# 选项表外键列（从 TEXT 迁移到 ID 引用）
_add_column_if_missing(conn, "accounts", "agent_id", "agent_id INTEGER REFERENCES agents(id)")
_add_column_if_missing(conn, "accounts", "status_id", "status_id INTEGER REFERENCES account_statuses(id)")
_add_column_if_missing(conn, "recharge_records", "agent_id", "agent_id INTEGER REFERENCES agents(id)")
_add_column_if_missing(conn, "mcc", "level_id", "level_id INTEGER REFERENCES mcc_levels(id)")
_add_column_if_missing(conn, "products", "sales_person_id", "sales_person_id INTEGER REFERENCES sales_persons(id)")
```

- [ ] **Step 3: 验证**

```bash
cd d:/server/cc/GG-Server && python -c "from database import get_db; db=get_db(); tables=db.execute(\"SELECT name FROM sqlite_master WHERE type='table' AND name IN ('agents','account_statuses','mcc_levels','sales_persons')\").fetchall(); print('Tables:', [t[0] for t in tables]); db.close()"
```

预期输出包含全部 4 张新表。

- [ ] **Step 4: Commit**

```bash
git add py/database.py && git commit -m "feat: 新建 4 张选项表 + 给业务表加外键列"
```

---

### Task 2: 数据库 — 数据迁移脚本

**Files:**
- Modify: `py/database.py` — `_migrate_if_needed()` 添加迁移逻辑

**Interfaces:**
- Consumes: Task 1 的新表和外键列
- Produces: 外键列已填充的数据库

- [ ] **Step 1: 在 `_migrate_if_needed()` 中添加迁移函数调用**

在 `py/database.py` 的 `_migrate_if_needed()` 函数末尾，添加：

```python
_migrate_options_tables(conn)
```

- [ ] **Step 2: 在 `_migrate_if_needed()` 前面定义迁移函数**

```python
def _migrate_options_tables(conn: sqlite3.Connection):
    """将旧 TEXT 列中的选项值迁移到新选项表，并填充外键列。"""
    # 检查是否已迁移：如果 accounts 表已有 agent_id 不为 NULL 的记录，跳过
    count = conn.execute("SELECT COUNT(*) FROM accounts WHERE agent_id IS NOT NULL").fetchone()[0]
    if count > 0:
        return

    # === agents ===
    # 从 accounts 迁移
    conn.execute("""
        INSERT OR IGNORE INTO agents(name, owner_id)
        SELECT DISTINCT agent, owner_id FROM accounts
        WHERE agent IS NOT NULL AND agent != ''
    """)
    # 从 recharge_records 迁移（通过 accounts 关联 owner_id）
    conn.execute("""
        INSERT OR IGNORE INTO agents(name, owner_id)
        SELECT DISTINCT r.agent, a.owner_id
        FROM recharge_records r
        JOIN accounts a ON a.account_id = r.account_id
        WHERE r.agent IS NOT NULL AND r.agent != ''
    """)
    # 填充 accounts.agent_id
    conn.execute("""
        UPDATE accounts SET agent_id = (
            SELECT agents.id FROM agents
            WHERE agents.name = accounts.agent AND agents.owner_id = accounts.owner_id
        ) WHERE accounts.agent IS NOT NULL AND accounts.agent != ''
    """)
    # 填充 recharge_records.agent_id
    conn.execute("""
        UPDATE recharge_records SET agent_id = (
            SELECT agents.id FROM agents
            JOIN accounts a ON a.account_id = recharge_records.account_id
            WHERE agents.name = recharge_records.agent AND agents.owner_id = a.owner_id
        ) WHERE recharge_records.agent IS NOT NULL AND recharge_records.agent != ''
    """)

    # === account_statuses ===
    conn.execute("""
        INSERT OR IGNORE INTO account_statuses(name, owner_id)
        SELECT DISTINCT status, owner_id FROM accounts
        WHERE status IS NOT NULL AND status != ''
    """)
    conn.execute("""
        UPDATE accounts SET status_id = (
            SELECT account_statuses.id FROM account_statuses
            WHERE account_statuses.name = accounts.status
              AND account_statuses.owner_id = accounts.owner_id
        ) WHERE accounts.status IS NOT NULL AND accounts.status != ''
    """)

    # === mcc_levels ===
    conn.execute("""
        INSERT OR IGNORE INTO mcc_levels(name, owner_id)
        SELECT DISTINCT m.level, m.owner_id FROM mcc m
        WHERE m.level IS NOT NULL AND m.level != ''
    """)
    conn.execute("""
        UPDATE mcc SET level_id = (
            SELECT mcc_levels.id FROM mcc_levels
            WHERE mcc_levels.name = mcc.level AND mcc_levels.owner_id = mcc.owner_id
        ) WHERE mcc.level IS NOT NULL AND mcc.level != ''
    """)

    # === sales_persons ===
    conn.execute("""
        INSERT OR IGNORE INTO sales_persons(name, owner_id)
        SELECT DISTINCT p.sales_person, p.owner_id FROM products p
        WHERE p.sales_person IS NOT NULL AND p.sales_person != ''
    """)
    conn.execute("""
        UPDATE products SET sales_person_id = (
            SELECT sales_persons.id FROM sales_persons
            WHERE sales_persons.name = products.sales_person
              AND sales_persons.owner_id = products.owner_id
        ) WHERE products.sales_person IS NOT NULL AND products.sales_person != ''
    """)

    conn.commit()
```

- [ ] **Step 3: 运行迁移验证**

```bash
cd d:/server/cc/GG-Server && python -c "
from database import get_db
db = get_db()
# 验证外键覆盖率
checks = [
    ('accounts.agent_id', \"SELECT COUNT(*) FROM accounts WHERE agent IS NOT NULL AND agent!='' AND agent_id IS NULL\"),
    ('accounts.status_id', \"SELECT COUNT(*) FROM accounts WHERE status IS NOT NULL AND status!='' AND status_id IS NULL\"),
    ('recharge_records.agent_id', \"SELECT COUNT(*) FROM recharge_records WHERE agent IS NOT NULL AND agent!='' AND agent_id IS NULL\"),
    ('mcc.level_id', \"SELECT COUNT(*) FROM mcc WHERE level IS NOT NULL AND level!='' AND level_id IS NULL\"),
    ('products.sales_person_id', \"SELECT COUNT(*) FROM products WHERE sales_person IS NOT NULL AND sales_person!='' AND sales_person_id IS NULL\"),
]
for label, sql in checks:
    cnt = db.execute(sql).fetchone()[0]
    status = 'OK' if cnt == 0 else f'FAIL ({cnt} unmatched)'
    print(f'{label}: {status}')
db.close()
"
```

全部应输出 `OK`。

- [ ] **Step 4: Commit**

```bash
git add py/database.py && git commit -m "feat: 数据迁移 — 旧 TEXT 列值迁移到选项表外键"
```

---

### Task 3: 后端 — 选项 CRUD API (agents + account_statuses)

**Files:**
- Modify: `py/main.py` — 新增 `/api/agents/*` 和 `/api/statuses/*` 路由

**Interfaces:**
- Consumes: Task 2 的数据库结构
- Produces: 8 个 API 端点

- [ ] **Step 1: 在 `py/main.py` 中添加 agents API**

找到某个现有路由区块后（例如 `# ---------- 账户设置 API ----------` 之前），插入：

```python
# ========== Agents 选项 API ==========

@app.route("/api/agents/list", methods=["GET"])
@jwt_required()
def agents_list():
    """返回当前用户的代理名选项列表。"""
    user_id = int(get_jwt_identity())
    db = _yt_db()
    rows = db.execute(
        "SELECT id, name FROM agents WHERE owner_id=? ORDER BY id",
        (user_id,)
    ).fetchall()
    db.close()
    return jsonify({"success": True, "agents": [dict(r) for r in rows]})


@app.route("/api/agents/create", methods=["POST"])
@jwt_required()
def agents_create():
    """新增代理名。"""
    user_id = int(get_jwt_identity())
    data = request.get_json(silent=True) or {}
    name = (data.get("name") or "").strip()
    if not name:
        return jsonify({"success": False, "error": "名称不能为空"}), 400
    db = _yt_db()
    existing = db.execute(
        "SELECT id FROM agents WHERE name=? AND owner_id=?", (name, user_id)
    ).fetchone()
    if existing:
        db.close()
        return jsonify({"success": False, "error": f"代理「{name}」已存在"}), 409
    db.execute("INSERT INTO agents(name, owner_id) VALUES(?,?)", (name, user_id))
    db.commit()
    new_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]
    db.close()
    return jsonify({"success": True, "id": new_id})


@app.route("/api/agents/<int:aid>", methods=["PUT"])
@jwt_required()
def agents_rename(aid):
    """重命名代理 — 所有 JOIN 引用自动生效。"""
    user_id = int(get_jwt_identity())
    data = request.get_json(silent=True) or {}
    name = (data.get("name") or "").strip()
    if not name:
        return jsonify({"success": False, "error": "名称不能为空"}), 400
    db = _yt_db()
    # 检查是否存在
    row = db.execute("SELECT id FROM agents WHERE id=? AND owner_id=?", (aid, user_id)).fetchone()
    if not row:
        db.close()
        return jsonify({"success": False, "error": "代理不存在或无权修改"}), 404
    # 检查重名
    dup = db.execute(
        "SELECT id FROM agents WHERE name=? AND owner_id=? AND id!=?",
        (name, user_id, aid)
    ).fetchone()
    if dup:
        db.close()
        return jsonify({"success": False, "error": f"代理「{name}」已存在"}), 409
    db.execute("UPDATE agents SET name=? WHERE id=?", (name, aid))
    db.commit()
    # 清除缓存
    _app_cache.delete(f"accounts:agents:{user_id}")
    db.close()
    return jsonify({"success": True})


@app.route("/api/agents/<int:aid>", methods=["DELETE"])
@jwt_required()
def agents_delete(aid):
    """删除代理 — 有引用则阻止。"""
    user_id = int(get_jwt_identity())
    db = _yt_db()
    row = db.execute("SELECT id FROM agents WHERE id=? AND owner_id=?", (aid, user_id)).fetchone()
    if not row:
        db.close()
        return jsonify({"success": False, "error": "代理不存在或无权操作"}), 404
    # 检查引用
    refs = []
    ac = db.execute("SELECT COUNT(*) FROM accounts WHERE agent_id=?", (aid,)).fetchone()[0]
    if ac > 0:
        refs.append(f"{ac} 个账户")
    rc = db.execute("SELECT COUNT(*) FROM recharge_records WHERE agent_id=?", (aid,)).fetchone()[0]
    if rc > 0:
        refs.append(f"{rc} 条充值记录")
    if refs:
        db.close()
        return jsonify({"success": False, "error": f"无法删除：被 {'、'.join(refs)} 引用，请先解除关联"}), 409
    db.execute("DELETE FROM agents WHERE id=?", (aid,))
    db.commit()
    _app_cache.delete(f"accounts:agents:{user_id}")
    db.close()
    return jsonify({"success": True})
```

- [ ] **Step 2: 在 `py/main.py` 中添加 account_statuses API**

紧接 agents 之后：

```python
# ========== Account Statuses 选项 API ==========

@app.route("/api/statuses/list", methods=["GET"])
@jwt_required()
def statuses_list():
    user_id = int(get_jwt_identity())
    db = _yt_db()
    rows = db.execute(
        "SELECT id, name FROM account_statuses WHERE owner_id=? ORDER BY id",
        (user_id,)
    ).fetchall()
    db.close()
    return jsonify({"success": True, "statuses": [dict(r) for r in rows]})


@app.route("/api/statuses/create", methods=["POST"])
@jwt_required()
def statuses_create():
    user_id = int(get_jwt_identity())
    data = request.get_json(silent=True) or {}
    name = (data.get("name") or "").strip()
    if not name:
        return jsonify({"success": False, "error": "名称不能为空"}), 400
    db = _yt_db()
    existing = db.execute(
        "SELECT id FROM account_statuses WHERE name=? AND owner_id=?", (name, user_id)
    ).fetchone()
    if existing:
        db.close()
        return jsonify({"success": False, "error": f"状态「{name}」已存在"}), 409
    db.execute("INSERT INTO account_statuses(name, owner_id) VALUES(?,?)", (name, user_id))
    db.commit()
    new_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]
    db.close()
    return jsonify({"success": True, "id": new_id})


@app.route("/api/statuses/<int:sid>", methods=["PUT"])
@jwt_required()
def statuses_rename(sid):
    user_id = int(get_jwt_identity())
    data = request.get_json(silent=True) or {}
    name = (data.get("name") or "").strip()
    if not name:
        return jsonify({"success": False, "error": "名称不能为空"}), 400
    db = _yt_db()
    row = db.execute("SELECT id FROM account_statuses WHERE id=? AND owner_id=?", (sid, user_id)).fetchone()
    if not row:
        db.close()
        return jsonify({"success": False, "error": "状态不存在或无权修改"}), 404
    dup = db.execute(
        "SELECT id FROM account_statuses WHERE name=? AND owner_id=? AND id!=?",
        (name, user_id, sid)
    ).fetchone()
    if dup:
        db.close()
        return jsonify({"success": False, "error": f"状态「{name}」已存在"}), 409
    db.execute("UPDATE account_statuses SET name=? WHERE id=?", (name, sid))
    db.commit()
    _app_cache.delete(f"accounts:statuses:{user_id}")
    db.close()
    return jsonify({"success": True})


@app.route("/api/statuses/<int:sid>", methods=["DELETE"])
@jwt_required()
def statuses_delete(sid):
    user_id = int(get_jwt_identity())
    db = _yt_db()
    row = db.execute("SELECT id FROM account_statuses WHERE id=? AND owner_id=?", (sid, user_id)).fetchone()
    if not row:
        db.close()
        return jsonify({"success": False, "error": "状态不存在或无权操作"}), 404
    ac = db.execute("SELECT COUNT(*) FROM accounts WHERE status_id=?", (sid,)).fetchone()[0]
    if ac > 0:
        db.close()
        return jsonify({"success": False, "error": f"无法删除：被 {ac} 个账户引用，请先解除关联"}), 409
    db.execute("DELETE FROM account_statuses WHERE id=?", (sid,))
    db.commit()
    _app_cache.delete(f"accounts:statuses:{user_id}")
    db.close()
    return jsonify({"success": True})
```

- [ ] **Step 3: 验证**

```bash
# 启动服务器后测试
curl -X POST http://localhost:5000/api/login -H "Content-Type: application/json" -d '{"username":"admin","password":"xxx"}' -c cookies.txt
# 获取列表
curl -b cookies.txt http://localhost:5000/api/agents/list
# 创建
curl -b cookies.txt -X POST http://localhost:5000/api/agents/create -H "Content-Type: application/json" -d '{"name":"测试代理"}'
```

- [ ] **Step 4: Commit**

```bash
git add py/main.py && git commit -m "feat: 新增 agents + statuses 选项 CRUD API (8 endpoints)"
```

---

### Task 4: 后端 — 选项 CRUD API (mcc_levels + sales_persons)

**Files:**
- Modify: `py/main.py` — 新增 `/api/mcc-levels/*` 和 `/api/sales-persons/*` 路由

**Interfaces:**
- Consumes: Task 2 的数据库结构
- Produces: 8 个 API 端点

- [ ] **Step 1: 添加 mcc_levels API**

```python
# ========== MCC Levels 选项 API ==========

@app.route("/api/mcc-levels/list", methods=["GET"])
@jwt_required()
def mcc_levels_list():
    user_id = int(get_jwt_identity())
    db = _yt_db()
    rows = db.execute(
        "SELECT id, name FROM mcc_levels WHERE owner_id=? ORDER BY id",
        (user_id,)
    ).fetchall()
    db.close()
    return jsonify({"success": True, "mcc_levels": [dict(r) for r in rows]})


@app.route("/api/mcc-levels/create", methods=["POST"])
@jwt_required()
def mcc_levels_create():
    user_id = int(get_jwt_identity())
    data = request.get_json(silent=True) or {}
    name = (data.get("name") or "").strip()
    if not name:
        return jsonify({"success": False, "error": "名称不能为空"}), 400
    db = _yt_db()
    existing = db.execute(
        "SELECT id FROM mcc_levels WHERE name=? AND owner_id=?", (name, user_id)
    ).fetchone()
    if existing:
        db.close()
        return jsonify({"success": False, "error": f"等级「{name}」已存在"}), 409
    db.execute("INSERT INTO mcc_levels(name, owner_id) VALUES(?,?)", (name, user_id))
    db.commit()
    new_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]
    db.close()
    return jsonify({"success": True, "id": new_id})


@app.route("/api/mcc-levels/<int:lid>", methods=["PUT"])
@jwt_required()
def mcc_levels_rename(lid):
    user_id = int(get_jwt_identity())
    data = request.get_json(silent=True) or {}
    name = (data.get("name") or "").strip()
    if not name:
        return jsonify({"success": False, "error": "名称不能为空"}), 400
    db = _yt_db()
    row = db.execute("SELECT id FROM mcc_levels WHERE id=? AND owner_id=?", (lid, user_id)).fetchone()
    if not row:
        db.close()
        return jsonify({"success": False, "error": "等级不存在或无权修改"}), 404
    dup = db.execute(
        "SELECT id FROM mcc_levels WHERE name=? AND owner_id=? AND id!=?",
        (name, user_id, lid)
    ).fetchone()
    if dup:
        db.close()
        return jsonify({"success": False, "error": f"等级「{name}」已存在"}), 409
    db.execute("UPDATE mcc_levels SET name=? WHERE id=?", (name, lid))
    db.commit()
    db.close()
    return jsonify({"success": True})


@app.route("/api/mcc-levels/<int:lid>", methods=["DELETE"])
@jwt_required()
def mcc_levels_delete(lid):
    user_id = int(get_jwt_identity())
    db = _yt_db()
    row = db.execute("SELECT id FROM mcc_levels WHERE id=? AND owner_id=?", (lid, user_id)).fetchone()
    if not row:
        db.close()
        return jsonify({"success": False, "error": "等级不存在或无权操作"}), 404
    mc = db.execute("SELECT COUNT(*) FROM mcc WHERE level_id=?", (lid,)).fetchone()[0]
    if mc > 0:
        db.close()
        return jsonify({"success": False, "error": f"无法删除：被 {mc} 个 MCC 引用，请先解除关联"}), 409
    db.execute("DELETE FROM mcc_levels WHERE id=?", (lid,))
    db.commit()
    db.close()
    return jsonify({"success": True})


# ========== Sales Persons 选项 API ==========

@app.route("/api/sales-persons/list", methods=["GET"])
@jwt_required()
def sales_persons_list():
    user_id = int(get_jwt_identity())
    db = _yt_db()
    rows = db.execute(
        "SELECT id, name FROM sales_persons WHERE owner_id=? ORDER BY id",
        (user_id,)
    ).fetchall()
    db.close()
    return jsonify({"success": True, "sales_persons": [dict(r) for r in rows]})


@app.route("/api/sales-persons/create", methods=["POST"])
@jwt_required()
def sales_persons_create():
    user_id = int(get_jwt_identity())
    data = request.get_json(silent=True) or {}
    name = (data.get("name") or "").strip()
    if not name:
        return jsonify({"success": False, "error": "名称不能为空"}), 400
    db = _yt_db()
    existing = db.execute(
        "SELECT id FROM sales_persons WHERE name=? AND owner_id=?", (name, user_id)
    ).fetchone()
    if existing:
        db.close()
        return jsonify({"success": False, "error": f"商务人员「{name}」已存在"}), 409
    db.execute("INSERT INTO sales_persons(name, owner_id) VALUES(?,?)", (name, user_id))
    db.commit()
    new_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]
    db.close()
    return jsonify({"success": True, "id": new_id})


@app.route("/api/sales-persons/<int:sid>", methods=["PUT"])
@jwt_required()
def sales_persons_rename(sid):
    user_id = int(get_jwt_identity())
    data = request.get_json(silent=True) or {}
    name = (data.get("name") or "").strip()
    if not name:
        return jsonify({"success": False, "error": "名称不能为空"}), 400
    db = _yt_db()
    row = db.execute("SELECT id FROM sales_persons WHERE id=? AND owner_id=?", (sid, user_id)).fetchone()
    if not row:
        db.close()
        return jsonify({"success": False, "error": "商务人员不存在或无权修改"}), 404
    dup = db.execute(
        "SELECT id FROM sales_persons WHERE name=? AND owner_id=? AND id!=?",
        (name, user_id, sid)
    ).fetchone()
    if dup:
        db.close()
        return jsonify({"success": False, "error": f"商务人员「{name}」已存在"}), 409
    db.execute("UPDATE sales_persons SET name=? WHERE id=?", (name, sid))
    db.commit()
    db.close()
    return jsonify({"success": True})


@app.route("/api/sales-persons/<int:sid>", methods=["DELETE"])
@jwt_required()
def sales_persons_delete(sid):
    user_id = int(get_jwt_identity())
    db = _yt_db()
    row = db.execute("SELECT id FROM sales_persons WHERE id=? AND owner_id=?", (sid, user_id)).fetchone()
    if not row:
        db.close()
        return jsonify({"success": False, "error": "商务人员不存在或无权操作"}), 404
    pc = db.execute("SELECT COUNT(*) FROM products WHERE sales_person_id=?", (sid,)).fetchone()[0]
    if pc > 0:
        db.close()
        return jsonify({"success": False, "error": f"无法删除：被 {pc} 个产品引用，请先解除关联"}), 409
    db.execute("DELETE FROM sales_persons WHERE id=?", (sid,))
    db.commit()
    db.close()
    return jsonify({"success": True})
```

- [ ] **Step 2: Commit**

```bash
git add py/main.py && git commit -m "feat: 新增 mcc-levels + sales-persons 选项 CRUD API (8 endpoints)"
```

---

### Task 5: 后端 — 适配业务 API (accounts 相关)

**Files:**
- Modify: `py/main.py` — accounts 创建/更新/列表/批量等接口

**Interfaces:**
- Consumes: Task 2 的数据库结构, Task 3 的 agents/statuses API
- Produces: 所有 accounts 接口同时支持旧 TEXT 和新 ID 字段

> **策略**：过渡期接口同时接受 `agent`(TEXT) 和 `agent_id`(INT)，优先使用 `agent_id`。这样前后端可以独立部署，不会因升级顺序导致 API 错误。

- [ ] **Step 1: 修改 `accounts_list()` — 查询时 JOIN 返回 agent_name/status_name**

修改 [main.py:3336](py/main.py#L3336) 的 SQL：

```python
# 旧:
sql = "SELECT a.*, m.name AS mcc_name, m.mcc_id AS mcc_code FROM accounts a LEFT JOIN mcc m ON a.mcc_id=m.id"

# 新:
sql = """
    SELECT a.*, m.name AS mcc_name, m.mcc_id AS mcc_code,
           ag.name AS agent_name, st.name AS status_name
    FROM accounts a
    LEFT JOIN mcc m ON a.mcc_id = m.id
    LEFT JOIN agents ag ON a.agent_id = ag.id
    LEFT JOIN account_statuses st ON a.status_id = st.id
"""
```

同时修改筛选逻辑（L3330-L3333），agent 和 status 筛选改为通过 JOIN 表匹配：

```python
if status:
    # 新逻辑：筛选 status_id（也兼容前端仍在传文本）
    where.append("a.status_id IN (SELECT id FROM account_statuses WHERE name=? AND owner_id=?)")
    params += [status, user_id]
if agent:
    where.append("a.agent_id IN (SELECT id FROM agents WHERE name LIKE ? AND owner_id=?)")
    params += [f"%{agent}%", user_id]
```

返回的 accounts 列表中每条记录增加 `agent_name` 和 `status_name`：

```python
accounts = [dict(r) for r in rows]
# 同时继续提供旧字段兼容（前端过渡期需要）
for a in accounts:
    if "agent_name" in a and a["agent_name"]:
        a["agent"] = a["agent_name"]
    if "status_name" in a and a["status_name"]:
        a["status"] = a["status_name"]
```

状态计数查询也相应修改：

```python
# 旧:
for r in db.execute("SELECT status, COUNT(*) as cnt FROM accounts WHERE owner_id=? GROUP BY status", (user_id,)).fetchall():

# 新:
for r in db.execute("""
    SELECT COALESCE(st.name, a.status) as status, COUNT(*) as cnt
    FROM accounts a
    LEFT JOIN account_statuses st ON a.status_id = st.id
    WHERE a.owner_id=?
    GROUP BY COALESCE(st.name, a.status)
""", (user_id,)).fetchall():
```

- [ ] **Step 2: 修改 `accounts_create()` — 接受 agent_id/status_id**

修改 [main.py:3481](py/main.py#L3481) 创建语句：

```python
agent_id = data.get("agent_id")
if agent_id is None and data.get("agent"):
    # 兼容：前端仍传文本时，自动查找或创建
    agent_name = data.get("agent", "").strip()
    if agent_name:
        existing = db.execute(
            "SELECT id FROM agents WHERE name=? AND owner_id=?", (agent_name, user_id)
        ).fetchone()
        if existing:
            agent_id = existing["id"]
        else:
            db.execute("INSERT INTO agents(name, owner_id) VALUES(?,?)", (agent_name, user_id))
            agent_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]

status_id = data.get("status_id")
if status_id is None and data.get("status"):
    status_name = data.get("status", "").strip()
    if status_name:
        existing = db.execute(
            "SELECT id FROM account_statuses WHERE name=? AND owner_id=?", (status_name, user_id)
        ).fetchone()
        if existing:
            status_id = existing["id"]
        else:
            db.execute("INSERT INTO account_statuses(name, owner_id) VALUES(?,?)", (status_name, user_id))
            status_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]

db.execute(
    "INSERT INTO accounts(name,account_id,mcc_id,timezone,agent,agent_id,status,status_id,acquired_date,death_date,created_at,updated_at,owner_id) "
    "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
    (name, account_id,
     data.get("mcc_id") or None,
     (data.get("timezone") or "").strip(),
     (data.get("agent") or "").strip(),    # 旧字段，填兼容值
     agent_id,
     (data.get("status") or "存活").strip(),  # 旧字段，填兼容值
     status_id,
     (data.get("acquired_date") or datetime.date.today().isoformat()),
     (data.get("death_date") or "").strip(),
     now, now, user_id))
```

- [ ] **Step 3: 修改 `accounts_update()` — 接受 agent_id/status_id**

修改 [main.py:3640](py/main.py#L3640) 的字段列表和更新逻辑：

```python
# 字段列表新增 agent_id, status_id，同时保留 agent, status 兼容
_new_style_fields = {"agent_id": "agent_id", "status_id": "status_id"}
for f in ["name", "mcc_id", "timezone", "agent", "agent_id", "status", "status_id", "acquired_date", "death_date"]:
    if f in data:
        val = data[f]
        if f == "mcc_id":
            if val is None or val == 0 or val == "0" or (isinstance(val, str) and not val.strip()):
                val = None
            _record_mcc_change(db, aid, val, user_id, "manual")
        # 如果传了 agent_id 但没传 agent(old)，同步文本字段用于兼容
        elif f == "agent_id" and "agent" not in data:
            if val:
                ag_name = db.execute("SELECT name FROM agents WHERE id=?", (val,)).fetchone()
                if ag_name:
                    db.execute("UPDATE accounts SET agent=?, updated_at=datetime('now','localtime') WHERE id=?",
                               (ag_name["name"], aid))
        elif f == "status_id" and "status" not in data:
            if val:
                st_name = db.execute("SELECT name FROM account_statuses WHERE id=?", (val,)).fetchone()
                if st_name:
                    db.execute("UPDATE accounts SET status=?, updated_at=datetime('now','localtime') WHERE id=?",
                               (st_name["name"], aid))
        db.execute(f"UPDATE accounts SET {f}=?, updated_at=datetime('now','localtime') WHERE id=?",
                   (val, aid))
```

- [ ] **Step 4: 修改 `accounts_batch_update()`**

修改 [main.py:3833](py/main.py#L3833) 的 allowed fields 和清账逻辑：

```python
allowed = ["status", "status_id", "agent", "agent_id", "mcc_id", "timezone"]
```

当 field 为 `status_id` 时，清账逻辑需通过 JOIN 获取 status name：

```python
if field == "status_id" and value:
    # 需要 status name 用于清账比较
    status_name = db.execute("SELECT name FROM account_statuses WHERE id=?", (value,)).fetchone()
    if status_name:
        field_for_check = "status"
        value_for_check = status_name["name"]
    else:
        field_for_check = "status_id"
        value_for_check = value
else:
    field_for_check = field
    value_for_check = value
```

- [ ] **Step 5: 修改 `accounts_lookup()`**

修改 [main.py:3411](py/main.py#L3411) 返回的 existing 字段，增加 `agent_name` 和 `status_name`。

- [ ] **Step 6: Commit**

```bash
git add py/main.py && git commit -m "feat: accounts API 适配 agent_id/status_id 外键 + JOIN 返回名称"
```

---

### Task 6: 后端 — 适配业务 API (mcc, products, recharge)

**Files:**
- Modify: `py/main.py` — mcc 创建/更新, products 创建/更新, recharge 提交

**Interfaces:**
- Consumes: Tasks 2-5
- Produces: 所有业务 API 支持新外键字段

- [ ] **Step 1: mcc_create — 支持 level_id**

修改 [main.py:4406-4413](py/main.py#L4406-L4413) 的 INSERT 语句。处理逻辑：

```python
# 在 mcc_create() 中，level 字段处理后添加:
level = (data.get("level") or "").strip()
level_id = data.get("level_id")
if level_id is None and level:
    # 兼容文本：自动查找或创建
    existing = db.execute(
        "SELECT id FROM mcc_levels WHERE name=? AND owner_id=?", (level, user_id)
    ).fetchone()
    if existing:
        level_id = existing["id"]
    elif level:
        db.execute("INSERT INTO mcc_levels(name, owner_id) VALUES(?,?)", (level, user_id))
        level_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]

# INSERT 改为同时写 level(旧) 和 level_id(新)
db.execute(
    "INSERT INTO mcc(name,mcc_id,level,level_id,parent_mcc_id,shared_user_ids,created_at,updated_at,owner_id) "
    "VALUES(?,?,?,?,?,?,?,?,?)",
    (name, mcc_id, level, level_id,
     parent_mcc_id, json.dumps([user_id]), now, now, user_id))
```

**mcc_update** — 修改 [main.py:4451](py/main.py#L4451) 的 `_mcc_fields`：

```python
_mcc_fields = {"name": "name", "level": "level", "level_id": "level_id", "parent_mcc_id": "parent_mcc_id"}
```

同时处理当 `level_id` 被设置时自动同步 `level` 文本列：

```python
if "level_id" in data and "level" not in data:
    if data["level_id"]:
        lvl_name = db.execute("SELECT name FROM mcc_levels WHERE id=?", (data["level_id"],)).fetchone()
        if lvl_name:
            db.execute("UPDATE mcc SET level=?, updated_at=datetime('now','localtime') WHERE id=?",
                       (lvl_name["name"], mid))
```

- [ ] **Step 2: recharge_submit — 接受 agent_id**

修改 [main.py:3949](py/main.py#L3949)：

```python
agent_id = data.get("agent_id")
agent = data.get("agent", "").strip()
if agent_id is None and agent:
    # 兼容文本
    user_id = int(get_jwt_identity())
    existing = db.execute(
        "SELECT id FROM agents WHERE name=? AND owner_id=?", (agent, user_id)
    ).fetchone()
    if existing:
        agent_id = existing["id"]
    elif agent:
        db.execute("INSERT INTO agents(name, owner_id) VALUES(?,?)", (agent, user_id))
        agent_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]
```

INSERT 语句改为同时写 agent(旧) 和 agent_id(新)：

```python
db.execute(
    "INSERT INTO recharge_records (account_id, amount, agent, agent_id, operator, created_by, sheets_synced) "
    "VALUES (?, ?, ?, ?, ?, ?, 0)",
    (account_id, amount, agent, agent_id, operator, user_id)
)
```

同样适配 `recharge_batch_submit()` 和 `recharge_update()`。

- [ ] **Step 3: products_create/update — 支持 sales_person_id**

**products_create** — 修改 [main.py:2412](py/main.py#L2412)：

```python
sales_person = (data.get("sales_person") or "").strip()
sales_person_id = data.get("sales_person_id")
if sales_person_id is None and sales_person:
    existing = db.execute(
        "SELECT id FROM sales_persons WHERE name=? AND owner_id=?", (sales_person, user_id)
    ).fetchone()
    if existing:
        sales_person_id = existing["id"]
    elif sales_person:
        db.execute("INSERT INTO sales_persons(name, owner_id) VALUES(?,?)", (sales_person, user_id))
        sales_person_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]

# INSERT 和 UPDATE existing 产品时，同时写 sales_person(旧) + sales_person_id(新)
db.execute(
    "INSERT INTO products(product_name,kpi,region,mcc_id,customer,sales_person,sales_person_id,agency_ratio,owner_id,runner_ids,created_at) "
    "VALUES(?,?,?,?,?,?,?,?,?,?,?)",
    (product_name, kpi, region, mcc_id, customer, sales_person, sales_person_id, agency_ratio, user_id, runner_ids, now))

# existing 分支也加:
if sales_person_id:
    db.execute("UPDATE products SET sales_person_id=? WHERE id=?", (sales_person_id, pid))
```

**products_update** — 修改 [main.py:2477-2480](py/main.py#L2477-L2480)：

```python
_product_fields = {
    "product_name": "product_name", "kpi": "kpi", "region": "region",
    "status": "status", "mcc_id": "mcc_id", "customer": "customer",
    "sales_person": "sales_person", "sales_person_id": "sales_person_id",
    "agency_ratio": "agency_ratio",
}
```

```python
# 当 sales_person_id 变化时同步 sales_person 文本列
if "sales_person_id" in data and "sales_person" not in data:
    if data["sales_person_id"]:
        sp_name = db.execute("SELECT name FROM sales_persons WHERE id=?", (data["sales_person_id"],)).fetchone()
        if sp_name:
            db.execute("UPDATE products SET sales_person=?, updated_at=datetime('now','localtime') WHERE id=?",
                       (sp_name["name"], pid))
```

- [ ] **Step 4: Commit**

```bash
git add py/main.py && git commit -m "feat: mcc/products/recharge API 适配选项表外键"
```

---

### Task 7: 后端 — 适配数据导入/导出 + settings API

**Files:**
- Modify: `py/data_service.py` — 导出时包含新表，导入时适配新列
- Modify: `py/main.py` — settings API 改为从新表读写

- [ ] **Step 1: data_service — export 增加新表**

修改 `export_user_data()` ([data_service.py:267](py/data_service.py#L267))，在 `data["tags"]` 行之后增加：

```python
# 选项表
for table in ["agents", "account_statuses", "mcc_levels", "sales_persons"]:
    data[table] = [dict(r) for r in db.execute(
        f"SELECT * FROM {table} WHERE owner_id=?", (user_id,)
    ).fetchall()]
```

- [ ] **Step 2: data_service — import 增加新表处理**

修改 `execute_import()` ([data_service.py:87](py/data_service.py#L87))，在现有导入循环后增加 4 张选项表的导入：

```python
# 导入选项表
for table in ["agents", "account_statuses", "mcc_levels", "sales_persons"]:
    existing_cols = [c[1] for c in db.execute(f"PRAGMA table_info({table})").fetchall()]
    for r in data.get(table, []):
        d = dict(r)
        d.pop("id", None)
        d["owner_id"] = target_user_id
        cols = [k for k in d if k in existing_cols]
        if cols:
            placeholders = ", ".join(["?"] * len(cols))
            vals = [d[c] for c in cols]
            try:
                db.execute(f"INSERT OR IGNORE INTO {table}({', '.join(cols)}) VALUES({placeholders})", vals)
            except sqlite3.IntegrityError:
                pass
```

- [ ] **Step 3: settings API — 兼容改造**

修改 `account_settings_get()` 和 `account_settings_save()`：

```python
@app.route("/api/settings/account", methods=["GET"])
def account_settings_get():
    """从新选项表读取，同时兼容旧格式。"""
    db = _yt_db()
    result = {}
    # 从新表读取
    tables = {"account_agents": "agents", "account_statuses": "account_statuses",
              "mcc_levels": "mcc_levels", "sales_persons": "sales_persons"}
    for key, table in tables.items():
        rows = db.execute(f"SELECT name FROM {table} ORDER BY id").fetchall()
        result[key] = [r["name"] for r in rows]
    # recharge_sheet_id 仍从 tags 读
    row = db.execute("SELECT value FROM tags WHERE key='recharge_sheet_id'").fetchone()
    result["recharge_sheet_id"] = _json.loads(row["value"]) if row else ""
    db.close()
    return jsonify({"success": True, "settings": result})
```

save 改为忽略（前端不再通过此接口保存选项，改为调用 Task 3/4 的新 API）：

```python
@app.route("/api/settings/account", methods=["POST"])
def account_settings_save():
    """仅保存 recharge_sheet_id；选项通过独立 API 管理。"""
    data = request.get_json(silent=True) or {}
    db = _yt_db()
    if "recharge_sheet_id" in data:
        db.execute("INSERT OR REPLACE INTO tags(key,value) VALUES(?,?)",
                   ("recharge_sheet_id", _json.dumps(data["recharge_sheet_id"], ensure_ascii=False)))
    db.commit()
    db.close()
    return jsonify({"success": True})
```

- [ ] **Step 4: Commit**

```bash
git add py/main.py py/data_service.py && git commit -m "feat: 数据导入导出 + settings API 适配选项表"
```

---

### Task 8: 前端 — Store 改造

**Files:**
- Modify: `frontend/src/stores/accounts.js`
- Modify: `frontend/src/api/accounts.js`

- [ ] **Step 1: accounts.js API — 新增选项 API 方法**

```javascript
// 在现有 export 后添加
export const optionApi = {
  // agents
  agents:    { list: () => api.get('/agents/list'), create: (name) => api.post('/agents/create', {name}),
               rename: (id, name) => api.put(`/agents/${id}`, {name}), delete: (id) => api.delete(`/agents/${id}`) },
  // statuses
  statuses:  { list: () => api.get('/statuses/list'), create: (name) => api.post('/statuses/create', {name}),
               rename: (id, name) => api.put(`/statuses/${id}`, {name}), delete: (id) => api.delete(`/statuses/${id}`) },
  // mcc levels
  mccLevels: { list: () => api.get('/mcc-levels/list'), create: (name) => api.post('/mcc-levels/create', {name}),
               rename: (id, name) => api.put(`/mcc-levels/${id}`, {name}), delete: (id) => api.delete(`/mcc-levels/${id}`) },
  // sales persons
  salesPersons: { list: () => api.get('/sales-persons/list'), create: (name) => api.post('/sales-persons/create', {name}),
                  rename: (id, name) => api.put(`/sales-persons/${id}`, {name}), delete: (id) => api.delete(`/sales-persons/${id}`) },
}
```

- [ ] **Step 2: accounts.js Store — 新增 state + actions**

```javascript
// state 中新增:
options: {
  agents: [],
  statuses: [],
  mccLevels: [],
  salesPersons: [],
},

// actions 中新增:
async loadAgents() {
  const res = await optionApi.agents.list()
  this.options.agents = res.agents || []
  return this.options.agents
},
async createAgent(name) { const res = await optionApi.agents.create(name); await this.loadAgents(); return res },
async renameAgent(id, name) { await optionApi.agents.rename(id, name); await this.loadAgents() },
async deleteAgent(id) { await optionApi.agents.delete(id); await this.loadAgents() },

async loadStatuses() {
  const res = await optionApi.statuses.list()
  this.options.statuses = res.statuses || []
  return this.options.statuses
},
async createStatus(name) { const res = await optionApi.statuses.create(name); await this.loadStatuses(); return res },
async renameStatus(id, name) { await optionApi.statuses.rename(id, name); await this.loadStatuses() },
async deleteStatus(id) { await optionApi.statuses.delete(id); await this.loadStatuses() },

async loadMccLevels() {
  const res = await optionApi.mccLevels.list()
  this.options.mccLevels = res.mcc_levels || []
  return this.options.mccLevels
},
async createMccLevel(name) { const res = await optionApi.mccLevels.create(name); await this.loadMccLevels(); return res },
async renameMccLevel(id, name) { await optionApi.mccLevels.rename(id, name); await this.loadMccLevels() },
async deleteMccLevel(id) { await optionApi.mccLevels.delete(id); await this.loadMccLevels() },

async loadSalesPersons() {
  const res = await optionApi.salesPersons.list()
  this.options.salesPersons = res.sales_persons || []
  return this.options.salesPersons
},
async createSalesPerson(name) { const res = await optionApi.salesPersons.create(name); await this.loadSalesPersons(); return res },
async renameSalesPerson(id, name) { await optionApi.salesPersons.rename(id, name); await this.loadSalesPersons() },
async deleteSalesPerson(id) { await optionApi.salesPersons.delete(id); await this.loadSalesPersons() },
```

- [ ] **Step 3: settings 保持兼容**

store 的 `settings` 字段不再需要 `/api/settings/account` 来获取选项列表，但 `recharge_sheet_id` 仍需保留。`loadSettings()` 改为只获取 sheet_id，`settings` state 简化为 `{ recharge_sheet_id: '' }`。

- [ ] **Step 4: Commit**

```bash
git add frontend/src/stores/accounts.js frontend/src/api/accounts.js && git commit -m "feat: 前端 Store 新增选项 API + state/actions"
```

---

### Task 9: 前端 — SettingsPanel 重写（4 个 textarea → 表格）

**Files:**
- Modify: `frontend/src/views/SettingsPanel.vue`

- [ ] **Step 1: 添加选项表格组件**

将 template 中 4 个 el-input 替换为选项行内编辑表格。在 `<script setup>` 中添加数据和方法：

```html
<!-- 账户状态选项 -->
<el-table :data="store.options.statuses" size="small" border stripe style="max-width:450px;" @cell-click="startEdit">
  <el-table-column prop="name" label="名称">
    <template #default="{ row, $index }">
      <el-input v-if="editing.statuses === $index" v-model="row._editName" size="small"
        @blur="finishEdit('statuses', row)" @keyup.enter="finishEdit('statuses', row)" />
      <span v-else>{{ row.name }}</span>
    </template>
  </el-table-column>
  <el-table-column label="操作" width="80">
    <template #default="{ row }">
      <el-button size="small" type="danger" @click="deleteOption('statuses', row)">🗑</el-button>
    </template>
  </el-table-column>
</el-table>
<div style="display:flex;gap:8px;margin-top:8px;max-width:450px;">
  <el-input v-model="newOptionNames.statuses" placeholder="新状态名" size="small" style="flex:1;" />
  <el-button size="small" type="primary" @click="addOption('statuses')">新增</el-button>
</div>
```

4 个选项（statuses, agents, mcc_levels, sales_persons）都采用相同模式，可抽取为一个通用的选项编辑区域。

- [ ] **Step 2: script 中添加编辑逻辑**

```javascript
import { reactive, onMounted } from 'vue'

const newOptionNames = reactive({ statuses: '', agents: '', mcc_levels: '', sales_persons: '' })
const editing = reactive({ statuses: -1, agents: -1, mcc_levels: -1, sales_persons: -1 })

function startEdit(row, column, cell, event, type) { /* 点击行触发编辑 */ }
async function finishEdit(type, row) {
  editing[type] = -1
  const newName = (row._editName || '').trim()
  if (!newName || newName === row.name) return
  const actions = { statuses: 'renameStatus', agents: 'renameAgent', mcc_levels: 'renameMccLevel', sales_persons: 'renameSalesPerson' }
  try {
    await store[actions[type]](row.id, newName)
    ElMessage.success('已更新')
  } catch (e) { ElMessage.error(e.response?.data?.error || '更新失败') }
}
async function addOption(type) { /* 新增 */ }
async function deleteOption(type, row) { /* 删除 */ }
```

- [ ] **Step 3: onMounted 加载选项数据**

```javascript
onMounted(async () => {
  await Promise.all([store.loadAgents(), store.loadStatuses(), store.loadMccLevels(), store.loadSalesPersons()])
  // recharge_sheet_id 仍从 settings 加载
  await store.loadSettings()
  form.recharge_sheet_id = store.settings.recharge_sheet_id || ''
})
```

- [ ] **Step 4: 调整 save 按钮**

save 按钮现在只保存 `recharge_sheet_id`（选项通过行内编辑即时保存，不再需要"保存配置"按钮来保存选项）。

- [ ] **Step 5: Commit**

```bash
git add frontend/src/views/SettingsPanel.vue && git commit -m "feat: SettingsPanel textarea 改为行内编辑表格"
```

---

### Task 10: 前端 — 下拉框消费者适配 (Agent + Status)

**Files:**
- Modify: `frontend/src/components/AccountModal.vue`
- Modify: `frontend/src/components/AccountBatchImportModal.vue`
- Modify: `frontend/src/views/AdsAccountPanel.vue`

- [ ] **Step 1: AccountModal.vue — agent 下拉走 ID**

```html
<!-- 旧 -->
<el-option v-for="a in store.settings.account_agents" :key="a" :label="a" :value="a" />

<!-- 新 -->
<el-option v-for="a in store.options.agents" :key="a.id" :label="a.name" :value="a.id" />
```

status 下拉同理：`:value="s.id"` `:label="s.name"` `store.options.statuses`

- [ ] **Step 2: AccountModal.vue — 移除自动追加逻辑**

删除 [L196-200](frontend/src/components/AccountModal.vue#L196-L200) 的 agents 自动追加逻辑（约 5 行）。

- [ ] **Step 3: AccountModal.vue — 表单提交发送 agent_id**

```javascript
// 在 submit() 中
const body = {
  name: form.name,
  account_id: form.account_id,
  agent_id: form.agent,      // v-model 绑定的就是 ID
  status_id: form.status,    // v-model 绑定的就是 ID
  ...
}
```

- [ ] **Step 4: AccountBatchImportModal.vue — 3 处下拉 + 移除自动追加**

同理修改 L94, L185, L245 三处 agent/status 下拉，删除 L636-648 自动追加逻辑。

- [ ] **Step 5: AdsAccountPanel.vue — 筛选下拉改 API**

筛选栏下拉选项改为从 store.options 读取：

```javascript
// 旧: 合并 store.settings.account_agents + res.agents
agentOptions.value = [...new Set([...store.settings.account_agents, ...(res.agents||[])])].filter(Boolean).sort()

// 新: 直接从 store.options 读取
agentOptions.value = store.options.agents.map(a => ({ id: a.id, name: a.name }))
```

筛选参数发送 `agent_id` 而不是 `agent`：

```javascript
// 旧: params.agent = ...
// 新: params.agent_id = ...
```

status 筛选同理。

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/AccountModal.vue frontend/src/components/AccountBatchImportModal.vue frontend/src/views/AdsAccountPanel.vue && git commit -m "feat: agent/status 下拉框迁移到 option ID 模式"
```

---

### Task 11: 前端 — 下拉框消费者适配 (mcc_levels + sales_persons)

**Files:**
- Modify: `frontend/src/components/MccModal.vue`
- Modify: `frontend/src/components/ProductModal.vue`

- [ ] **Step 1: MccModal.vue — level 下拉走 ID**

```html
<!-- 旧 -->
<el-option v-for="l in store.settings.mcc_levels" :key="l" :label="l" :value="l" />

<!-- 新 -->
<el-option v-for="l in store.options.mccLevels" :key="l.id" :label="l.name" :value="l.id" />
```

创建/编辑表单提交时发送 `level_id`。

- [ ] **Step 2: ProductModal.vue — sales_person 下拉走 ID**

```javascript
// 旧
const salesPersonOptions = computed(() => accountStore.settings.sales_persons || [])

// 新
const salesPersonOptions = computed(() => accountStore.options.salesPersons || [])
```

```html
<el-option v-for="sp in salesPersonOptions" :key="sp.id" :label="sp.name" :value="sp.id" />
```

创建/编辑时发送 `sales_person_id`。

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/MccModal.vue frontend/src/components/ProductModal.vue && git commit -m "feat: mcc_levels + sales_persons 下拉框迁移到 option ID 模式"
```

---

### Task 12: 清理 — 删除旧列 + 旧 tags 配置

**Files:**
- Modify: `py/database.py` — 添加清理迁移

**⚠️ 所有前后端代码部署完成并验证通过后才能执行此 Task。**

- [ ] **Step 1: 添加清理迁移函数**

```python
def _cleanup_old_option_columns(conn: sqlite3.Connection):
    """在所有代码切换到外键列之后，删除旧 TEXT 列和 tags 中的旧配置。"""
    # 使用 PRAGMA foreign_keys=OFF 避免约束问题
    conn.execute("PRAGMA foreign_keys=OFF")

    # 删除旧文本列
    for table, col in [
        ("accounts", "agent"),
        ("accounts", "status"),
        ("mcc", "level"),
        ("products", "sales_person"),
        ("recharge_records", "agent"),
    ]:
        cols = [r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()]
        if col in cols:
            conn.execute(f"ALTER TABLE {table} DROP COLUMN {col}")

    conn.execute("PRAGMA foreign_keys=ON")

    # 删除 tags 表中的旧配置
    for key in ["account_agents", "account_statuses", "mcc_levels", "sales_persons"]:
        conn.execute("DELETE FROM tags WHERE key=?", (key,))

    conn.commit()
```

- [ ] **Step 2: 在 `_migrate_if_needed()` 中调用**

```python
_cleanup_old_option_columns(conn)
```

- [ ] **Step 3: 验证**

```bash
cd d:/server/cc/GG-Server && python -c "
from database import get_db
db = get_db()
# 确认旧列已删除
for t, c in [('accounts','agent'),('accounts','status'),('mcc','level'),('products','sales_person'),('recharge_records','agent')]:
    cols = [r[1] for r in db.execute(f'PRAGMA table_info({t})')]
    print(f'{t}.{c}: {\"EXISTS\" if c in cols else \"REMOVED\"}')
# 确认旧 tags 已清理
for k in ['account_agents','account_statuses','mcc_levels','sales_persons']:
    r = db.execute('SELECT key FROM tags WHERE key=?', (k,)).fetchone()
    print(f'tags.{k}: {\"EXISTS\" if r else \"REMOVED\"}')
db.close()
"
```

全部应输出 `REMOVED`。

- [ ] **Step 4: Commit**

```bash
git add py/database.py && git commit -m "feat: 清理旧 TEXT 列 + 旧 tags 配置"
```

---

### 实施顺序总结

```
Task 1 ──→ Task 2 ──→ Task 3 ──→ Task 4 ──→ Task 5 ──→ Task 6 ──→ Task 7
                                                                        │
                                                                        ▼
Task 8 ──→ Task 9 ──→ Task 10 ──→ Task 11                              │
    │                                                                   │
    └────────────────────── 全部部署验证 ───────────────────────→ Task 12
```

Task 1-2（数据库迁移）必须先于所有其他任务。Task 3-7（后端 API）和 Task 8-11（前端）可并行开发。Task 12（清理）必须在所有代码部署验证后执行。
