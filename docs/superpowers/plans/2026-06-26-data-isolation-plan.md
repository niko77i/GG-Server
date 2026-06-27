# 数据隔离实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 实现多用户数据隔离 — videos/accounts/mcc 表加 owner_id，所有 API 加 JWT 鉴权 + 按用户过滤查询，YouTube 支持 is_public 公开/私有双层模型。

**Architecture:** 后端在 SQLite 层面通过 ALTER TABLE 补字段（兼容已有数据库），所有 accounts/mcc/youtube API 加 `@jwt_required()` 装饰器，通过 `get_jwt_identity()` 获取当前用户 ID 进行数据过滤。前端 axios 拦截器已自动带 token，无需改动。

**Tech Stack:** Python Flask + Flask-JWT-Extended + SQLite

## Global Constraints

- 不修改原有功能的代码逻辑，只做增量
- 已有数据库通过 ALTER TABLE 迁移，不能重建
- 现有数据全部归属 developer (id=1)
- 前端 JWT 拦截器已就绪，无需改动

---

### Task 1: 数据库迁移 — 3 个表加 owner_id + videos 加 is_public

**Files:**
- Modify: `py/database.py` — `_ensure_schema()` 和 `_migrate_if_needed()` 之间加迁移逻辑

**Interfaces:**
- Produces: `videos.owner_id`, `videos.is_public`, `accounts.owner_id`, `mcc.owner_id` 列存在
- Migration runs automatically on `get_db()` call

- [ ] **Step 1: 在 `_ensure_schema()` 末尾（`conn.commit()` 之前）添加列迁移逻辑**

在 `database.py` 的 `_ensure_schema` 函数中，`# 初始化默认标签` 之前插入以下代码（已有类似 migration 模式在第 173-191 行）：

```python
    # 迁移：videos 表补 owner_id 列（2026-06-26 数据隔离）
    vcols2 = [r[1] for r in conn.execute("PRAGMA table_info(videos)").fetchall()]
    if "owner_id" not in vcols2:
        conn.execute("ALTER TABLE videos ADD COLUMN owner_id INTEGER REFERENCES users(id)")
    if "is_public" not in vcols2:
        conn.execute("ALTER TABLE videos ADD COLUMN is_public INTEGER DEFAULT 0")

    # 迁移：accounts 表补 owner_id 列（2026-06-26 数据隔离）
    acols2 = [r[1] for r in conn.execute("PRAGMA table_info(accounts)").fetchall()]
    if "owner_id" not in acols2:
        conn.execute("ALTER TABLE accounts ADD COLUMN owner_id INTEGER REFERENCES users(id)")

    # 迁移：mcc 表补 owner_id 列（2026-06-26 数据隔离）
    mcols2 = [r[1] for r in conn.execute("PRAGMA table_info(mcc)").fetchall()]
    if "owner_id" not in mcols2:
        conn.execute("ALTER TABLE mcc ADD COLUMN owner_id INTEGER REFERENCES users(id)")
```

- [ ] **Step 2: 在 `_ensure_schema()` 末尾（初始化默认标签之后，`conn.commit()` 之前）添加数据归属迁移**

在上一步代码之后、`conn.commit()` 之前加入：

```python
    # 迁移：现有数据归属 developer（2026-06-26 数据隔离）
    data_migrated = conn.execute(
        "SELECT value FROM config WHERE key='migrated_owner_id'"
    ).fetchone()
    if not data_migrated:
        # developer 用户 id 始终为 1
        conn.execute("UPDATE videos SET owner_id = 1 WHERE owner_id IS NULL")
        conn.execute("UPDATE accounts SET owner_id = 1 WHERE owner_id IS NULL")
        conn.execute("UPDATE mcc SET owner_id = 1 WHERE owner_id IS NULL")
        conn.execute(
            "INSERT OR REPLACE INTO config(key,value) VALUES('migrated_owner_id','1')"
        )
```

### Task 2: accounts API — 加 JWT 鉴权 + owner_id 过滤

**Files:**
- Modify: `py/main.py` — accounts_list, accounts_create, accounts_update, accounts_delete, accounts_batch_delete, accounts_batch_update

**Interfaces:**
- Consumes: `accounts.owner_id` 列（Task 1）
- All accounts APIs require JWT
- Query results filtered by current user's owner_id
- Create assigns owner_id = current user

- [ ] **Step 1: accounts_list — 加 `@jwt_required()` + owner_id 过滤**

修改 `accounts_list()` 函数，在 `def accounts_list():` 下一行添加 `@jwt_required()`，并在 where 条件中加入 owner_id 过滤。

当前代码（[main.py:1440-1486](py/main.py#L1440-L1486)）修改为：

```python
@app.route("/api/accounts/list", methods=["GET"])
@jwt_required()
def accounts_list():
    user_id = int(get_jwt_identity())
    search = request.args.get("search", "").strip()
    mcc_id = request.args.get("mcc_id", "").strip()
    status = request.args.get("status", "").strip()
    agent = request.args.get("agent", "").strip()
    page = int(request.args.get("page", 1) or 1)
    size = int(request.args.get("size", 20) or 20)
    db = _yt_db()
    where = ["a.owner_id = ?"]; params = [user_id]
    if search:
        where.append("(a.name LIKE ? OR a.account_id LIKE ?)")
        params += [f"%{search}%", f"%{search}%"]
    if mcc_id:
        where.append("a.mcc_id = ?"); params.append(mcc_id)
    if status:
        where.append("a.status = ?"); params.append(status)
    if agent:
        where.append("a.agent LIKE ?"); params.append(f"%{agent}%")
    sql = "SELECT a.*, m.name AS mcc_name, m.mcc_id AS mcc_code FROM accounts a LEFT JOIN mcc m ON a.mcc_id=m.id"
    if where:
        sql += " WHERE " + " AND ".join(where)
    # ... 其余排序、分页、统计逻辑不变 ...
```

注意：`where` 初始化从 `where = []` 改为 `where = ["a.owner_id = ?"]; params = [user_id]`。

统计查询 `count_sql` 也需要加同样的 where 条件。当前的 `count_sql = "SELECT COUNT(*) FROM accounts a"` 后拼接 where 的方式已经包含了 owner_id 过滤，因为 where 数组第一项就是 owner_id。

状态统计（`status_counts`）也要按 owner_id 过滤，改为：

```python
    status_counts = {}
    for r in db.execute(
        "SELECT status, COUNT(*) as cnt FROM accounts WHERE owner_id=? GROUP BY status",
        (user_id,)
    ).fetchall():
        s = r["status"] or "存活"; status_counts[s] = status_counts.get(s, 0) + r["cnt"]
```

- [ ] **Step 2: accounts_create — 加 `@jwt_required()` + 写入 owner_id**

```python
@app.route("/api/accounts/create", methods=["POST"])
@jwt_required()
def accounts_create():
    user_id = int(get_jwt_identity())
    # ... 原有逻辑 ...
    db.execute(
        "INSERT INTO accounts(name,account_id,mcc_id,timezone,agent,status,acquired_date,death_date,created_at,updated_at,owner_id) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
        (name, account_id,
         data.get("mcc_id") or None,
         (data.get("timezone") or "").strip(),
         (data.get("agent") or "").strip(),
         (data.get("status") or "存活").strip(),
         (data.get("acquired_date") or datetime.date.today().isoformat()),
         (data.get("death_date") or "").strip(),
         now, now, user_id))
```

- [ ] **Step 3: accounts_update — 加 `@jwt_required()`**

仅添加装饰器，UPDATE 逻辑不变（owner_id 不可修改，属于创建时确定）：

```python
@app.route("/api/accounts/<int:aid>", methods=["PUT"])
@jwt_required()
def accounts_update(aid):
```

- [ ] **Step 4: accounts_delete — 加 `@jwt_required()`**

```python
@app.route("/api/accounts/<int:aid>", methods=["DELETE"])
@jwt_required()
def accounts_delete(aid):
```

- [ ] **Step 5: accounts_batch_delete — 加 `@jwt_required()`**

```python
@app.route("/api/accounts/batch-delete", methods=["POST"])
@jwt_required()
def accounts_batch_delete():
```

- [ ] **Step 6: accounts_batch_update — 加 `@jwt_required()`**

```python
@app.route("/api/accounts/batch-update", methods=["POST"])
@jwt_required()
def accounts_batch_update():
```

### Task 3: mcc API — 加 JWT 鉴权 + owner_id 过滤

**Files:**
- Modify: `py/main.py` — mcc_list, mcc_options, mcc_create, mcc_update, mcc_delete, mcc_batch_delete, mcc_detail

**Interfaces:**
- Consumes: `mcc.owner_id` 列（Task 1）
- All mcc APIs require JWT
- Query results filtered by owner_id
- Create assigns owner_id = current user

- [ ] **Step 1: mcc_list — 加 `@jwt_required()` + owner_id 过滤**

```python
@app.route("/api/mcc/list", methods=["GET"])
@jwt_required()
def mcc_list():
    user_id = int(get_jwt_identity())
    search = request.args.get("search", "").strip()
    level = request.args.get("level", "").strip()
    parent_filter = request.args.get("parent_filter", "")
    page = int(request.args.get("page", 1) or 1)
    size = int(request.args.get("size", 20) or 20)
    db = _yt_db()
    where = ["m.owner_id = ?"]; params = [user_id]
    # ... 其余逻辑不变 ...
```

`count_sql` 同理经由 where 自动包含 owner_id 过滤。

- [ ] **Step 2: mcc_options — 加 `@jwt_required()` + owner_id 过滤**

```python
@app.route("/api/mcc/options", methods=["GET"])
@jwt_required()
def mcc_options():
    user_id = int(get_jwt_identity())
    db = _yt_db()
    rows = db.execute(
        "SELECT id, name, mcc_id FROM mcc WHERE owner_id=? ORDER BY name",
        (user_id,)
    ).fetchall()
    db.close()
    return jsonify({"success": True, "options": [dict(r) for r in rows]})
```

- [ ] **Step 3: mcc_create — 加 `@jwt_required()` + 写入 owner_id**

```python
@app.route("/api/mcc/create", methods=["POST"])
@jwt_required()
def mcc_create():
    user_id = int(get_jwt_identity())
    # ... 原有逻辑 ...
    db.execute(
        "INSERT INTO mcc(name,mcc_id,level,parent_mcc_id,created_at,updated_at,owner_id) VALUES(?,?,?,?,?,?,?)",
        (name, mcc_id,
         (data.get("level") or "").strip(),
         parent_mcc_id,
         now, now, user_id))
```

- [ ] **Step 4: mcc_update — 加 `@jwt_required()`**

```python
@app.route("/api/mcc/<int:mid>", methods=["PUT"])
@jwt_required()
def mcc_update(mid):
```

- [ ] **Step 5: mcc_delete — 加 `@jwt_required()`**

```python
@app.route("/api/mcc/<int:mid>", methods=["DELETE"])
@jwt_required()
def mcc_delete(mid):
```

- [ ] **Step 6: mcc_batch_delete — 加 `@jwt_required()`**

```python
@app.route("/api/mcc/batch-delete", methods=["POST"])
@jwt_required()
def mcc_batch_delete():
```

- [ ] **Step 7: mcc_detail — 加 `@jwt_required()`**

```python
@app.route("/api/mcc/<int:mid>/detail", methods=["GET"])
@jwt_required()
def mcc_detail(mid):
```

### Task 4: YouTube API — 加 JWT 鉴权 + is_public/owner_id 双层模型

**Files:**
- Modify: `py/main.py` — youtube_import, youtube_list, youtube_delete, youtube_edit, youtube_batch_edit

**Interfaces:**
- Consumes: `videos.owner_id`, `videos.is_public` 列（Task 1）
- Import 时 `owner_id = current_user`, `is_public = 0`
- List 支持 `scope` 参数：`public`（仅公开）、`private`（仅自己）、默认 `all`（公开+自己）

- [ ] **Step 1: youtube_import — 加 `@jwt_required()` + 写入 owner_id**

在 `db.execute("INSERT INTO videos...")` 的 SQL 和参数中加入 `owner_id`：

```python
@app.route("/api/youtube/import", methods=["POST"])
@jwt_required()
def youtube_import():
    user_id = int(get_jwt_identity())
    # ... 原有逻辑 ...
    db.execute(
        "INSERT INTO videos(id,url,title,region,frame_type,effectiveness,product_name,review_status,imported_at,owner_id,is_public) "
        "VALUES(?,?,?,?,?,?,?,?,?,?,?)",
        (vid, f"https://www.youtube.com/watch?v={vid}", title, region, frame_type,
         effectiveness, product_name, review_status,
         datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),
         user_id, 0))
```

- [ ] **Step 2: youtube_list — 加 `@jwt_required()` + scope 过滤**

```python
@app.route("/api/youtube/list", methods=["GET"])
@jwt_required()
def youtube_list():
    user_id = int(get_jwt_identity())
    scope = request.args.get("scope", "all").strip()  # "public" | "private" | "all"
    # ... 原有 filter 逻辑不变 ...
    db = _yt_db()
    where = []; params = []

    # 按 scope 过滤
    if scope == "public":
        where.append("is_public = 1")
    elif scope == "private":
        where.append("owner_id = ?"); params.append(user_id)
    else:  # all
        where.append("(is_public = 1 OR owner_id = ?)"); params.append(user_id)

    for f, v in [("region", region), ("frame_type", frame_type),
                 ("effectiveness", effectiveness), ("product_name", product_name)]:
        if v: where.append(f"{f}=?"); params.append(v)
    # ... 其余 review_status、日期过滤、排序不变 ...
```

- [ ] **Step 3: youtube_delete — 加 `@jwt_required()`**

```python
@app.route("/api/youtube/delete", methods=["POST"])
@jwt_required()
def youtube_delete():
```

- [ ] **Step 4: youtube_edit — 加 `@jwt_required()`**

```python
@app.route("/api/youtube/edit", methods=["POST"])
@jwt_required()
def youtube_edit():
```

- [ ] **Step 5: youtube_batch_edit — 加 `@jwt_required()`**

```python
@app.route("/api/youtube/batch-edit", methods=["POST"])
@jwt_required()
def youtube_batch_edit():
```

- [ ] **Step 6: youtube_edit — 支持修改 is_public**

在 `youtube_edit()` 的允许字段列表中加入 `is_public`：

```python
    for f in ["region", "frame_type", "effectiveness", "product_name", "review_status", "is_public"]:
        if f in data: db.execute(f"UPDATE videos SET {f}=? WHERE id=?", (data[f], vid))
```

### Task 5: 验证测试

**Files:**
- 无新建

- [ ] **Step 1: 启动服务，验证未登录访问被拒绝**

```bash
cd py && python main.py
# 另开终端
curl -s http://127.0.0.1:5001/api/accounts/list | python -m json.tool
# 期望: {"success": false, "error": "Missing Authorization Header"} 或类似 401
```

- [ ] **Step 2: 登录获取 token，验证数据访问正常**

```bash
# 登录
curl -s -X POST http://127.0.0.1:5001/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username":"admin","password":"admin123"}'
# 记录 access_token

# 用 token 访问 accounts
curl -s http://127.0.0.1:5001/api/accounts/list \
  -H "Authorization: Bearer <token>"
# 期望: 正常返回数据
```

- [ ] **Step 3: 验证现有数据已归属 developer（id=1）**

```bash
# 检查数据库
sqlite3 temp/app.db "SELECT owner_id, COUNT(*) FROM accounts GROUP BY owner_id"
sqlite3 temp/app.db "SELECT owner_id, COUNT(*) FROM mcc GROUP BY owner_id"
sqlite3 temp/app.db "SELECT owner_id, COUNT(*) FROM videos GROUP BY owner_id"
# 期望: 全部为 1
```

- [ ] **Step 4: 验证新用户看不到其他用户数据**

注册一个新用户，用新用户 token 访问 accounts/mcc，应该返回空列表。

- [ ] **Step 5: 验证 YouTube scope 过滤**

```bash
# public scope
curl -s "http://127.0.0.1:5001/api/youtube/list?scope=public" \
  -H "Authorization: Bearer <token>"
# private scope
curl -s "http://127.0.0.1:5001/api/youtube/list?scope=private" \
  -H "Authorization: Bearer <token>"
```
