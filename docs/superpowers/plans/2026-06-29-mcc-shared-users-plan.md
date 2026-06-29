# MCC 多人共享与去重整合 — 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 实现 MCC 全局去重、多人共享、runner 自动分配、owner-only 编辑保护

**Architecture:** 在 `mcc` 表新增 `shared_user_ids` JSON 字段实现多用户可见；启动时执行数据迁移合并重复 MCC（developer 优先）；API 层加去重检查、owner 权限校验、自动级联分配；前端弹窗处理已存在确认关联流程

**Tech Stack:** Python Flask + SQLite, Vue 3 + Pinia + Element Plus

## Global Constraints

- 纯增量原则：只修改涉及 MCC 共享/去重的逻辑，不动其他功能
- 仅 owner 可编辑/删除 MCC，shared 用户只能查看和使用
- 分配子 MCC 时必须递归分配所有上级 MCC
- `mcc.mcc_id` 全局唯一（唯一索引保证）
- 数据迁移在服务启动时自动执行，幂等（通过 config 标记）

---

## 文件结构

| 文件 | 职责 | 改动类型 |
|------|------|---------|
| `py/database.py` | Schema 迁移 + 数据去重迁移 | 修改 |
| `py/main.py` | 7 个 API 端点改动 + 1 个新增 | 修改 |
| `frontend/src/api/accounts.js` | 新增 `linkMcc` 方法 | 修改 |
| `frontend/src/stores/accounts.js` | 新增 `linkMcc` action | 修改 |
| `frontend/src/components/MccModal.vue` | 处理 MCC 已存在的确认关联流程 | 修改 |
| `frontend/src/views/MccPanel.vue` | 根据 `is_owner` 控制编辑/删除按钮 | 修改 |

---

### Task 1: 数据库 Schema 迁移 + 数据去重

**Files:**
- Modify: `py/database.py`

**Interfaces:**
- Consumes: 现有 `mcc` 表结构
- Produces: `mcc.shared_user_ids TEXT DEFAULT '[]'` 列，`idx_mcc_mcc_id_unique` 唯一索引，现有重复数据已合并

#### 子任务 1.1：在 `init_db()` 的 CREATE TABLE 中增加 `shared_user_ids`

修改 `py/database.py` 第 96-104 行的 `mcc` 建表语句，增加 `shared_user_ids` 字段：

- [ ] **Step 1: 修改 CREATE TABLE 语句**

找到约第 96-104 行：

```python
        CREATE TABLE IF NOT EXISTS mcc (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            mcc_id TEXT NOT NULL,
            level TEXT DEFAULT '',
            parent_mcc_id INTEGER REFERENCES mcc(id),
            created_at TEXT DEFAULT (datetime('now','localtime')),
            updated_at TEXT DEFAULT (datetime('now','localtime'))
        );
```

替换为：

```python
        CREATE TABLE IF NOT EXISTS mcc (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            mcc_id TEXT NOT NULL,
            level TEXT DEFAULT '',
            parent_mcc_id INTEGER REFERENCES mcc(id),
            shared_user_ids TEXT DEFAULT '[]',
            created_at TEXT DEFAULT (datetime('now','localtime')),
            updated_at TEXT DEFAULT (datetime('now','localtime'))
        );
```

- [ ] **Step 2: Commit**

```bash
git add py/database.py
git commit -m "feat: mcc 表新增 shared_user_ids 字段"
```

#### 子任务 1.2：添加 `shared_user_ids` 列的迁移逻辑

在现有迁移代码块附近（约第 227-230 行附近，`owner_id` 迁移之后）添加：

- [ ] **Step 1: 添加列迁移代码**

在 `py/database.py` 约第 230 行后（`mcc` 的 `owner_id` 迁移之后）插入：

```python
    # 迁移：mcc 表补 shared_user_ids 列（2026-06-29 MCC 共享）
    mcols3 = [r[1] for r in conn.execute("PRAGMA table_info(mcc)").fetchall()]
    if "shared_user_ids" not in mcols3:
        conn.execute("ALTER TABLE mcc ADD COLUMN shared_user_ids TEXT DEFAULT '[]'")
```

- [ ] **Step 2: Commit**

```bash
git add py/database.py
git commit -m "feat: mcc 表 shared_user_ids 列迁移"
```

#### 子任务 1.3：数据去重迁移 + 唯一索引

在现有迁移逻辑末尾（`_migrate_if_needed` 调用之前，约第 276 行之前）添加：

- [ ] **Step 1: 添加去重迁移代码**

在 `py/database.py` 中 `# 迁移：现有数据归属 developer` 块之后、`_migrate_if_needed` 之前，插入以下迁移函数调用：

```python
    _migrate_mcc_dedup(conn)
```

并在文件顶部区域（`_migrate_if_needed` 函数之前）添加迁移函数：

```python
def _migrate_mcc_dedup(conn: sqlite3.Connection):
    """合并重复 MCC（同一 mcc_id 字符串），developer 的记录优先保留。"""
    migrated = conn.execute(
        "SELECT value FROM config WHERE key='migrated_mcc_dedup'"
    ).fetchone()
    if migrated:
        return

    # 查找重复的 mcc_id
    dupes = conn.execute(
        "SELECT mcc_id, COUNT(*) as cnt FROM mcc GROUP BY mcc_id HAVING cnt > 1"
    ).fetchall()

    if not dupes:
        # 无重复，直接建唯一索引
        conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_mcc_mcc_id_unique ON mcc(mcc_id)")
        conn.execute("INSERT OR REPLACE INTO config(key,value) VALUES('migrated_mcc_dedup','1')")
        conn.commit()
        return

    # 获取 developer 用户 ID
    dev = conn.execute("SELECT id FROM users WHERE role='developer' LIMIT 1").fetchone()
    dev_id = dev["id"] if dev else 1

    for row in dupes:
        mcc_id_str = row["mcc_id"]
        # 获取该 mcc_id 的所有记录
        all_rows = conn.execute(
            "SELECT * FROM mcc WHERE mcc_id=? ORDER BY id ASC", (mcc_id_str,)
        ).fetchall()

        # 确定主记录：developer 的优先，否则最早创建的
        master = None
        for r in all_rows:
            if r["owner_id"] == dev_id:
                master = r
                break
        if not master:
            master = all_rows[0]  # 最早创建的

        master_id = master["id"]
        master_owner = master["owner_id"] or 0

        # 收集所有 shared 用户（排除 master owner）
        shared_ids = set()
        for r in all_rows:
            oid = r["owner_id"] or 0
            if oid and oid != master_owner:
                shared_ids.add(oid)

        # 合并已有的 shared_user_ids
        try:
            existing_shared = json.loads(master["shared_user_ids"] or "[]")
        except Exception:
            existing_shared = []
        all_shared = list(set(existing_shared + list(shared_ids)))

        # 更新关联数据：products 和 accounts 指向主记录
        for r in all_rows:
            if r["id"] == master_id:
                continue
            conn.execute("UPDATE products SET mcc_id=? WHERE mcc_id=?", (master_id, r["id"]))
            conn.execute("UPDATE accounts SET mcc_id=? WHERE mcc_id=?", (master_id, r["id"]))
            # 更新子 MCC 的 parent_mcc_id
            conn.execute("UPDATE mcc SET parent_mcc_id=? WHERE parent_mcc_id=?", (master_id, r["id"]))

        # 写入 shared_user_ids
        conn.execute(
            "UPDATE mcc SET shared_user_ids=? WHERE id=?",
            (json.dumps(all_shared), master_id)
        )

        # 删除重复记录
        for r in all_rows:
            if r["id"] != master_id:
                conn.execute("DELETE FROM mcc WHERE id=?", (r["id"],))

    # 初始化无 shared_user_ids 的记录
    conn.execute("UPDATE mcc SET shared_user_ids='[]' WHERE shared_user_ids IS NULL")

    # 创建唯一索引
    conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_mcc_mcc_id_unique ON mcc(mcc_id)")

    # 标记迁移完成
    conn.execute("INSERT OR REPLACE INTO config(key,value) VALUES('migrated_mcc_dedup','1')")
    conn.commit()
```

- [ ] **Step 2: 确保文件顶部有 `import json`**

检查 `py/database.py` 顶部是否有 `import json`。如果没有，在 import 区域添加。

- [ ] **Step 3: Commit**

```bash
git add py/database.py
git commit -m "feat: MCC 去重数据迁移 + mcc_id 唯一索引"
```

---

### Task 2: MCC 列表 API — 改为 shared 可见 + is_owner 标记

**Files:**
- Modify: `py/main.py:1893-1924`

**Interfaces:**
- Consumes: `mcc.shared_user_ids` 列（Task 1 产出）
- Produces: `mcc_list` 返回数据中每条含 `is_owner` 字段

- [ ] **Step 1: 修改 `mcc_list()` 的 WHERE 条件**

找到 `py/main.py` 约第 1903 行：

```python
    where = ["m.owner_id = ?"]; params = [user_id]
```

替换为：

```python
    where = ["(m.owner_id = ? OR m.shared_user_ids LIKE '%' || ? || '%')"]
    params = [user_id, user_id]
```

- [ ] **Step 2: 修改 `_mcc_to_dict()` 增加 `is_owner` 字段**

找到 `py/main.py` 约第 1675-1685 行的 `_mcc_to_dict` 函数：

```python
def _mcc_to_dict(r, db=None):
    d = dict(r)
    if db:
        d["direct_count"] = db.execute(
            "SELECT COUNT(*) FROM accounts WHERE mcc_id=?", (r["id"],)
        ).fetchone()[0]
        d["total_accounts"] = len(_mcc_recursive_account_ids(r["id"]))
    else:
        d["direct_count"] = 0
        d["total_accounts"] = 0
    return d
```

需要增加 `current_user_id` 参数。修改为：

```python
def _mcc_to_dict(r, db=None, current_user_id=None):
    d = dict(r)
    if db:
        d["direct_count"] = db.execute(
            "SELECT COUNT(*) FROM accounts WHERE mcc_id=?", (r["id"],)
        ).fetchone()[0]
        d["total_accounts"] = len(_mcc_recursive_account_ids(r["id"]))
    else:
        d["direct_count"] = 0
        d["total_accounts"] = 0
    # 标记当前用户是否是 owner
    d["is_owner"] = (current_user_id is not None and r.get("owner_id") == current_user_id)
    return d
```

- [ ] **Step 3: 修改 `mcc_list()` 中对 `_mcc_to_dict` 的调用**

将约第 1922 行：

```python
    mcc_list_data = [_mcc_to_dict(r, db) for r in rows]
```

改为：

```python
    mcc_list_data = [_mcc_to_dict(r, db, user_id) for r in rows]
```

- [ ] **Step 4: Commit**

```bash
git add py/main.py
git commit -m "feat: MCC 列表按 shared_user_ids 过滤，返回 is_owner 标记"
```

---

### Task 3: MCC Options API — 改为 shared 可见

**Files:**
- Modify: `py/main.py:1927-1937`

**Interfaces:**
- Consumes: `mcc.shared_user_ids` 列
- Produces: options 下拉数据包含该用户可见的所有 MCC

- [ ] **Step 1: 修改 `mcc_options()` 的 WHERE 条件**

找到 `py/main.py` 约第 1932-1934 行：

```python
    rows = db.execute(
        "SELECT id, name, mcc_id FROM mcc WHERE owner_id=? ORDER BY name",
        (user_id,)
    ).fetchall()
```

替换为：

```python
    rows = db.execute(
        "SELECT id, name, mcc_id FROM mcc WHERE (owner_id=? OR shared_user_ids LIKE '%' || ? || '%') ORDER BY name",
        (user_id, user_id)
    ).fetchall()
```

- [ ] **Step 2: Commit**

```bash
git add py/main.py
git commit -m "feat: MCC options 下拉按 shared_user_ids 过滤"
```

---

### Task 4: MCC Create API — 去重检查

**Files:**
- Modify: `py/main.py:1940-1973`

**Interfaces:**
- Consumes: 唯一索引 `idx_mcc_mcc_id_unique`
- Produces: 正常创建返回 `{success, id}`，已存在返回 `{success, exists, existing_mcc, owner_name}`

- [ ] **Step 1: 重写 `mcc_create()` 函数**

将 `py/main.py` 约第 1940-1973 行的 `mcc_create` 替换为：

```python
@app.route("/api/mcc/create", methods=["POST"])
@jwt_required()
def mcc_create():
    user_id = int(get_jwt_identity())
    data = request.get_json(silent=True) or {}
    name = (data.get("name") or "").strip()
    mcc_id = (data.get("mcc_id") or "").strip()
    if not name or not mcc_id:
        return jsonify({"success": False, "error": "MCC 名称和 ID 不能为空"}), 400

    db = _yt_db()

    # 检查 mcc_id 是否已存在（按 Google Ads manager ID 字符串）
    existing = db.execute(
        "SELECT m.*, u.display_name, u.username FROM mcc m "
        "LEFT JOIN users u ON m.owner_id = u.id "
        "WHERE m.mcc_id=?", (mcc_id,)
    ).fetchone()

    if existing:
        ed = dict(existing)
        owner_name = ed.get("display_name") or ed.get("username") or "未知"
        # 检查当前用户是否已经在 shared 中或为 owner
        try:
            shared = json.loads(ed.get("shared_user_ids") or "[]")
        except Exception:
            shared = []
        if ed["owner_id"] == user_id or user_id in shared:
            db.close()
            return jsonify({"success": False, "error": "该 MCC 已关联到您的账户"}), 409
        # 存在但用户不在 shared 中 — 返回现有 MCC 信息等前端确认
        db.close()
        return jsonify({
            "success": True,
            "exists": True,
            "existing_mcc": {
                "id": ed["id"],
                "name": ed["name"],
                "mcc_id": ed["mcc_id"]
            },
            "owner_name": owner_name
        })

    # 验证上级 MCC 存在
    parent_mcc_id = data.get("parent_mcc_id") or None
    if parent_mcc_id:
        parent_row = db.execute("SELECT id FROM mcc WHERE id=?", (int(parent_mcc_id),)).fetchone()
        if not parent_row:
            db.close()
            return jsonify({"success": False, "error": "上级 MCC 不存在"}), 400

    import datetime
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    try:
        db.execute(
            "INSERT INTO mcc(name,mcc_id,level,parent_mcc_id,shared_user_ids,created_at,updated_at,owner_id) "
            "VALUES(?,?,?,?,?,?,?,?)",
            (name, mcc_id,
             (data.get("level") or "").strip(),
             parent_mcc_id,
             json.dumps([user_id]),
             now, now, user_id))
        db.commit()
        new_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]
        db.close()
        return jsonify({"success": True, "id": new_id})
    except sqlite3.IntegrityError:
        db.close()
        return jsonify({"success": False, "error": f"MCC ID '{mcc_id}' 已存在"}), 409
```

- [ ] **Step 2: 确保文件顶部有 `import json` 和 `import sqlite3`**

检查 `py/main.py` 顶部。`json` 和 `sqlite3` 应该已经导入。如果没有 `json` 的顶层导入（看到用的是 `_json` 别名或局部导入），需要统一。查看第 1303 行有 `import json as _json`，第 1971 行有 `except _sqlite3.IntegrityError`。

**注意：** 本函数内使用 `json.dumps` 和 `sqlite3.IntegrityError`。如果文件顶部没有 `import json` 和 `import sqlite3`，在本函数内部局部导入即可（参照现有模式在第 1303 行的局部导入）。

- [ ] **Step 3: Commit**

```bash
git add py/main.py
git commit -m "feat: MCC 创建时去重检查，已存在返回确认信息"
```

---

### Task 5: MCC Link API（新增）— 关联已有 MCC 到当前用户

**Files:**
- Modify: `py/main.py`（在 `mcc_detail` 之前插入新端点）

**Interfaces:**
- Consumes: MCC 的 `shared_user_ids`、`parent_mcc_id`
- Produces: `POST /api/mcc/<mid>/link` → `{success}`

- [ ] **Step 1: 在 `mcc_detail` 之前添加 `mcc_link` 端点**

在 `py/main.py` 约第 2049 行（`mcc_detail` 之前）插入：

```python
@app.route("/api/mcc/<int:mid>/link", methods=["POST"])
@jwt_required()
def mcc_link(mid):
    """将当前用户关联到已有 MCC（含上级链）。"""
    user_id = int(get_jwt_identity())
    db = _yt_db()

    mcc = db.execute("SELECT * FROM mcc WHERE id=?", (mid,)).fetchone()
    if not mcc:
        db.close()
        return jsonify({"success": False, "error": "MCC 不存在"}), 404

    def _link_user_to_mcc(mcc_id, uid, visited=None):
        """递归将用户加入 MCC 及其所有上级的 shared_user_ids。"""
        if visited is None:
            visited = set()
        if mcc_id in visited:
            return
        visited.add(mcc_id)
        row = db.execute(
            "SELECT id, owner_id, shared_user_ids, parent_mcc_id FROM mcc WHERE id=?",
            (mcc_id,)
        ).fetchone()
        if not row:
            return
        if row["owner_id"] == uid:
            # 已是 owner，无需加入 shared
            pass
        else:
            try:
                shared = json.loads(row["shared_user_ids"] or "[]")
            except Exception:
                shared = []
            if uid not in shared:
                shared.append(uid)
                db.execute(
                    "UPDATE mcc SET shared_user_ids=? WHERE id=?",
                    (json.dumps(shared), row["id"])
                )
        # 递归处理上级
        if row["parent_mcc_id"]:
            _link_user_to_mcc(row["parent_mcc_id"], uid, visited)

    _link_user_to_mcc(mid, user_id)
    db.commit()
    db.close()
    return jsonify({"success": True, "message": "MCC 已关联到您的账户"})
```

- [ ] **Step 2: Commit**

```bash
git add py/main.py
git commit -m "feat: 新增 POST /api/mcc/<id>/link 端点，含上级链级联关联"
```

---

### Task 6: MCC Update / Delete / Batch-Delete — Owner 权限检查

**Files:**
- Modify: `py/main.py:1976-2047`

**Interfaces:**
- Consumes: `mcc.owner_id`
- Produces: 非 owner 返回 403

- [ ] **Step 1: 修改 `mcc_update()` 加 owner 检查**

在 `py/main.py` 的 `mcc_update` 函数体中，`data = ...` 之后、`db = _yt_db()` 之前，插入 owner 检查：

```python
    user_id = int(get_jwt_identity())
```

然后将约第 1980 行的 `db = _yt_db()` 之后插入 owner 查询和检查：

```python
    db = _yt_db()
    mcc_row = db.execute("SELECT owner_id FROM mcc WHERE id=?", (mid,)).fetchone()
    if not mcc_row:
        db.close()
        return jsonify({"success": False, "error": "MCC 不存在"}), 404
    if mcc_row["owner_id"] != user_id:
        db.close()
        return jsonify({"success": False, "error": "只有创建者才能编辑此 MCC"}), 403
```

修改后的 `mcc_update` 完整代码：

```python
@app.route("/api/mcc/<int:mid>", methods=["PUT"])
@jwt_required()
def mcc_update(mid):
    user_id = int(get_jwt_identity())
    data = request.get_json(silent=True) or {}
    db = _yt_db()
    mcc_row = db.execute("SELECT owner_id FROM mcc WHERE id=?", (mid,)).fetchone()
    if not mcc_row:
        db.close()
        return jsonify({"success": False, "error": "MCC 不存在"}), 404
    if mcc_row["owner_id"] != user_id:
        db.close()
        return jsonify({"success": False, "error": "只有创建者才能编辑此 MCC"}), 403
    # 循环引用检测：新 parent_mcc_id 不能是当前 MCC 的子孙
    if "parent_mcc_id" in data and data["parent_mcc_id"]:
        new_parent = int(data["parent_mcc_id"])
        if new_parent == mid:
            db.close()
            return jsonify({"success": False, "error": "上级 MCC 不能设为自己"}), 400
        descendants = _mcc_get_descendant_ids(mid)
        if new_parent in descendants:
            db.close()
            return jsonify({"success": False, "error": "不能设置为下属 MCC，这会造成循环引用"}), 400
        # 验证父级存在
        parent_row = db.execute("SELECT id FROM mcc WHERE id=?", (new_parent,)).fetchone()
        if not parent_row:
            db.close()
            return jsonify({"success": False, "error": "上级 MCC 不存在"}), 400
    for f in ["name", "level", "parent_mcc_id"]:
        if f in data:
            db.execute(f"UPDATE mcc SET {f}=?, updated_at=datetime('now','localtime') WHERE id=?",
                       (data[f], mid))
    db.commit(); db.close()
    return jsonify({"success": True})
```

- [ ] **Step 2: 修改 `mcc_delete()` 加 owner 检查**

找到 `py/main.py` 约第 2006-2007 行，将现有的删除条件（`WHERE id=? AND owner_id=?`）已包含 owner 检查，但需要更明确的错误信息。修改如下：

```python
@app.route("/api/mcc/<int:mid>", methods=["DELETE"])
@jwt_required()
def mcc_delete(mid):
    user_id = int(get_jwt_identity())
    db = _yt_db()
    # 检查 ownership
    mcc_row = db.execute("SELECT owner_id FROM mcc WHERE id=?", (mid,)).fetchone()
    if not mcc_row:
        db.close()
        return jsonify({"success": False, "error": "MCC 不存在"}), 404
    if mcc_row["owner_id"] != user_id:
        db.close()
        return jsonify({"success": False, "error": "只有创建者才能删除此 MCC"}), 403
    # 检查是否有子 MCC
    children = db.execute("SELECT COUNT(*) FROM mcc WHERE parent_mcc_id=?", (mid,)).fetchone()[0]
    if children > 0:
        db.close()
        return jsonify({"success": False, "error": f"该 MCC 下有 {children} 个子 MCC，请先删除子 MCC"}), 400
    # 检查是否有直接关联的账户
    acct_count = db.execute("SELECT COUNT(*) FROM accounts WHERE mcc_id=?", (mid,)).fetchone()[0]
    if acct_count > 0:
        db.close()
        return jsonify({"success": False, "error": f"该 MCC 下有 {acct_count} 个直接关联账户，请先解除关联"}), 400
    db.execute("DELETE FROM mcc WHERE id=?", (mid,))
    db.commit(); db.close()
    return jsonify({"success": True})
```

- [ ] **Step 3: 修改 `mcc_batch_delete()` 加 owner 检查**

找到 `py/main.py` 约第 2024-2047 行，在循环中增加 owner 检查：

```python
@app.route("/api/mcc/batch-delete", methods=["POST"])
@jwt_required()
def mcc_batch_delete():
    user_id = int(get_jwt_identity())
    data = request.get_json(silent=True) or {}
    ids = data.get("ids") or []
    if not ids:
        return jsonify({"success": False, "error": "未选择 MCC"}), 400
    db = _yt_db()
    skipped = []
    deleted = 0
    for mid in ids:
        # Owner 检查
        mcc_row = db.execute("SELECT owner_id FROM mcc WHERE id=?", (mid,)).fetchone()
        if not mcc_row:
            skipped.append({"id": mid, "reason": "MCC 不存在"})
            continue
        if mcc_row["owner_id"] != user_id:
            skipped.append({"id": mid, "reason": "非创建者，无法删除"})
            continue
        children = db.execute("SELECT COUNT(*) FROM mcc WHERE parent_mcc_id=?", (mid,)).fetchone()[0]
        if children > 0:
            skipped.append({"id": mid, "reason": f"有 {children} 个子 MCC"})
            continue
        acct_count = db.execute("SELECT COUNT(*) FROM accounts WHERE mcc_id=?", (mid,)).fetchone()[0]
        if acct_count > 0:
            skipped.append({"id": mid, "reason": f"有 {acct_count} 个关联账户"})
            continue
        db.execute("DELETE FROM mcc WHERE id=?", (mid,))
        deleted += 1
    db.commit(); db.close()
    return jsonify({"success": True, "deleted": deleted, "skipped": skipped})
```

- [ ] **Step 4: Commit**

```bash
git add py/main.py
git commit -m "feat: MCC 编辑/删除加 owner 权限校验"
```

---

### Task 7: Products Update Runners — 自动分配 MCC 给新 runner

**Files:**
- Modify: `py/main.py:1459-1478`

**Interfaces:**
- Consumes: `products.mcc_id`, `mcc.shared_user_ids`, `mcc.parent_mcc_id`
- Produces: 新 runner 自动加入产品 MCC（含上级链）的 `shared_user_ids`

- [ ] **Step 1: 重写 `products_update_runners()`**

将 `py/main.py` 约第 1459-1478 行的函数替换为：

```python
def products_update_runners(pid):
    """更新产品的 runner 列表。新增 runner 时自动分配产品 MCC。"""
    data = request.get_json(silent=True) or {}
    runner_ids = data.get("runner_ids")  # list of user IDs

    if runner_ids is None or not isinstance(runner_ids, list):
        return jsonify({"success": False, "error": "请提供 runner_ids 列表"}), 400

    db = _yt_db()
    existing = db.execute(
        "SELECT id, runner_ids, mcc_id FROM products WHERE id=?", (pid,)
    ).fetchone()
    if not existing:
        db.close()
        return jsonify({"success": False, "error": "产品不存在"}), 404

    # 计算新增的 runner
    try:
        old_runners = json.loads(existing["runner_ids"] or "[]")
    except Exception:
        old_runners = []
    new_runners = [uid for uid in runner_ids if uid not in old_runners]

    # 更新 runner_ids
    db.execute("UPDATE products SET runner_ids=? WHERE id=?",
               (json.dumps(runner_ids), pid))

    # 自动分配产品 MCC 给新增的 runner
    product_mcc_id = existing["mcc_id"]
    if product_mcc_id and new_runners:
        _assign_mcc_to_users(db, product_mcc_id, new_runners)

    db.commit()
    db.close()
    return jsonify({"success": True, "runner_ids": runner_ids})
```

- [ ] **Step 2: 添加辅助函数 `_assign_mcc_to_users`**

在 `products_update_runners` 函数之前（约第 1458 行之前）添加：

```python
def _assign_mcc_to_users(db, mcc_id, user_ids):
    """将 MCC（含上级链）分配给指定用户列表。"""
    for uid in user_ids:
        _link_mcc_chain_to_user(db, mcc_id, uid)


def _link_mcc_chain_to_user(db, mcc_id, uid, visited=None):
    """递归将用户加入 MCC 及其所有上级的 shared_user_ids。"""
    if visited is None:
        visited = set()
    if mcc_id in visited:
        return
    visited.add(mcc_id)
    row = db.execute(
        "SELECT id, owner_id, shared_user_ids, parent_mcc_id FROM mcc WHERE id=?",
        (mcc_id,)
    ).fetchone()
    if not row:
        return
    if row["owner_id"] == uid:
        pass  # 已是 owner，不需要在 shared 中
    else:
        try:
            shared = json.loads(row["shared_user_ids"] or "[]")
        except Exception:
            shared = []
        if uid not in shared:
            shared.append(uid)
            db.execute(
                "UPDATE mcc SET shared_user_ids=? WHERE id=?",
                (json.dumps(shared), row["id"])
            )
    # 递归处理上级
    if row["parent_mcc_id"]:
        _link_mcc_chain_to_user(db, row["parent_mcc_id"], uid, visited)
```

- [ ] **Step 3: 同时也修改产品创建时的 MCC 自动分配**

在 `py/main.py` 的产品创建逻辑中（约第 1313-1326 行），当已有同名产品、当前用户被加入 runner 时，也应自动分配 MCC。找到约第 1324-1326 行：

```python
            if user_id not in runners:
                runners.append(user_id)
                db.execute("UPDATE products SET runner_ids=? WHERE id=?", (_json.dumps(runners), pid))
```

在 `db.execute("UPDATE products SET runner_ids...` 之后添加：

```python
                # 自动分配产品 MCC 给当前用户
                if mcc_id:
                    _assign_mcc_to_users(db, mcc_id, [user_id])
```

完整代码变为：

```python
            if user_id not in runners:
                runners.append(user_id)
                db.execute("UPDATE products SET runner_ids=? WHERE id=?", (_json.dumps(runners), pid))
                # 自动分配产品 MCC 给当前用户
                if mcc_id:
                    _assign_mcc_to_users(db, mcc_id, [user_id])
```

- [ ] **Step 4: Commit**

```bash
git add py/main.py
git commit -m "feat: 新增 runner 时自动分配产品 MCC（含上级链）"
```

---

### Task 8: 前端 API + Store — 新增 linkMcc 方法

**Files:**
- Modify: `frontend/src/api/accounts.js`
- Modify: `frontend/src/stores/accounts.js`

**Interfaces:**
- Consumes: `POST /api/mcc/<id>/link`（Task 5 产出）
- Produces: `mccApi.link(id)`, `store.linkMcc(id)`

- [ ] **Step 1: 在 `accounts.js` API 文件中添加 `link` 方法**

在 `frontend/src/api/accounts.js` 的 `mccApi` 对象中添加：

```js
  link:   (id)       => api.post(`/mcc/${id}/link`),
```

完整 `mccApi` 变为：

```js
export const mccApi = {
  list:   (params) => api.get('/mcc/list', { params }),
  options:()       => api.get('/mcc/options'),
  create: (body)   => api.post('/mcc/create', body),
  update: (id, body) => api.put(`/mcc/${id}`, body),
  delete: (id)     => api.delete(`/mcc/${id}`),
  batchDelete: (ids) => api.post('/mcc/batch-delete', { ids }),
  detail: (id)     => api.get(`/mcc/${id}/detail`),
  link:   (id)     => api.post(`/mcc/${id}/link`),
}
```

- [ ] **Step 2: 在 store 中新增 `linkMcc` action**

在 `frontend/src/stores/accounts.js` 的 `actions` 中添加（约第 43 行之后）：

```js
    async linkMcc(id) { return mccApi.link(id) },
```

- [ ] **Step 3: Commit**

```bash
git add frontend/src/api/accounts.js frontend/src/stores/accounts.js
git commit -m "feat: 前端新增 linkMcc API 和 store action"
```

---

### Task 9: 前端 MccModal.vue — 处理 MCC 已存在确认关联

**Files:**
- Modify: `frontend/src/components/MccModal.vue`

**Interfaces:**
- Consumes: `store.linkMcc(id)`（Task 8 产出），后端返回 `{exists, existing_mcc, owner_name}`
- Produces: 提交后弹确认框，确认后调 link 接口

- [ ] **Step 1: 修改 `submit()` 函数处理 exists 响应**

将 `frontend/src/components/MccModal.vue` 中的 `submit` 函数（约第 53-65 行）替换为：

```js
async function submit() {
  if (!form.name || !form.mcc_id) return
  saving.value = true
  try {
    if (props.editId) {
      await store.updateMcc(props.editId, { name: form.name, level: form.level, parent_mcc_id: form.parent_mcc_id || null })
    } else {
      const res = await store.createMcc(form)
      // 处理 MCC 已存在的情况
      if (res.exists && res.existing_mcc) {
        saving.value = false
        try {
          await ElMessageBox.confirm(
            `MCC "${res.existing_mcc.name} (${res.existing_mcc.mcc_id})" 已存在（属于 ${res.owner_name}），是否关联到您的列表？`,
            'MCC 已存在',
            { confirmButtonText: '关联', cancelButtonText: '取消', type: 'warning' }
          )
          saving.value = true
          await store.linkMcc(res.existing_mcc.id)
          ElMessage.success('MCC 已关联到您的账户')
        } catch (e) {
          // 用户取消关联
          return
        }
      }
    }
    emit('update:visible', false)
    emit('saved')
  } finally { saving.value = false }
}
```

- [ ] **Step 2: 在 `<script setup>` 顶部添加 `ElMessageBox` 和 `ElMessage` 导入**

检查现有导入。在约第 31 行：

```js
import { ref, reactive } from 'vue'
import { useAccountStore } from '@/stores/accounts'
import { mccApi } from '@/api/accounts'
```

添加：

```js
import { ElMessageBox, ElMessage } from 'element-plus'
```

完整导入：

```js
import { ref, reactive } from 'vue'
import { useAccountStore } from '@/stores/accounts'
import { mccApi } from '@/api/accounts'
import { ElMessageBox, ElMessage } from 'element-plus'
```

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/MccModal.vue
git commit -m "feat: MCC 新增弹窗处理已存在确认关联流程"
```

---

### Task 10: 前端 MccPanel.vue — is_owner 控制编辑/删除按钮

**Files:**
- Modify: `frontend/src/views/MccPanel.vue`

**Interfaces:**
- Consumes: MCC 列表项中的 `is_owner` 字段（Task 2 产出）
- Produces: 非 owner 行隐藏编辑和删除按钮

- [ ] **Step 1: 修改操作列模板，根据 `is_owner` 控制按钮**

找到 `frontend/src/views/MccPanel.vue` 约第 30-36 行的操作列模板：

```html
        <el-table-column label="操作" width="160">
          <template #default="{ row }">
            <el-button link type="primary" size="small" @click="showDetail(row.id)">📋</el-button>
            <el-button link type="primary" size="small" @click="showModal(row.id)">✏️</el-button>
            <el-button link type="danger" size="small" @click="del(row.id)">🗑</el-button>
          </template>
        </el-table-column>
```

替换为：

```html
        <el-table-column label="操作" width="160">
          <template #default="{ row }">
            <el-button link type="primary" size="small" @click="showDetail(row.id)">📋</el-button>
            <template v-if="row.is_owner">
              <el-button link type="primary" size="small" @click="showModal(row.id)">✏️</el-button>
              <el-button link type="danger" size="small" @click="del(row.id)">🗑</el-button>
            </template>
            <span v-else style="color:#aaa;font-size:11px;">共享</span>
          </template>
        </el-table-column>
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/views/MccPanel.vue
git commit -m "feat: MCC 面板根据 is_owner 控制编辑/删除按钮显隐"
```

---

## 任务依赖关系

```
Task 1 (DB) ──┬──> Task 2 (List API)
              ├──> Task 3 (Options API)
              ├──> Task 4 (Create API)
              ├──> Task 5 (Link API)
              ├──> Task 6 (Update/Delete API)
              └──> Task 7 (Runners API)
                          │
Task 5 ──> Task 8 (Frontend API/Store)
                          │
Task 8 ──> Task 9 (MccModal)
                          │
Task 2 + Task 6 ──> Task 10 (MccPanel)
```

Tasks 2-7 之间互相独立，可并行实现。Tasks 8-10 依赖后端先完成。
