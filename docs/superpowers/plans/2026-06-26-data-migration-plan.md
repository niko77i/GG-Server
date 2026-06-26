# 数据迁移与产品协作 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 实现 ImageCrawling → GG-Server 数据迁移（Web + CLI）、整库备份恢复、产品多人协作（runner/筛选/合并）

**Architecture:** 新增 `data_service.py` 作为导入导出核心逻辑（Web API 和 CLI 共用），`manage.py` 提供 CLI 管理命令。products 表新增 owner_id/runner_ids/is_archived，产品列表默认筛选当前用户参与的产品。Web 上传支持 .db 和 .json 双格式。

**Tech Stack:** Python Flask + SQLite + Vue 3 + Element Plus

## Global Constraints

- 纯增量原则：不修改原有功能逻辑，只在现有 API 上增加参数和路由
- 数据库迁移通过 ALTER TABLE，不影响已有数据
- 现有数据回填 owner_id=1, runner_ids=[1]
- Web 上传限制 50MB（JSON）/ 200MB（db）
- 导入操作记录 import_history 表

---

### Task 1: 数据库迁移 — products 表 + import_history 表

**Files:**
- Modify: `py/database.py` — `_ensure_schema()` 末尾

**Interfaces:**
- Produces: `products.owner_id`, `products.runner_ids`, `products.is_archived` 列
- Produces: `import_history` 表
- Migration runs automatically on `get_db()` call

- [ ] **Step 1: 在 `_ensure_schema()` 末尾（`conn.commit()` 之前）加 products 表迁移**

在 `database.py` 的 `_ensure_schema` 函数中，`conn.commit()` 之前插入以下代码：

```python
    # 迁移：products 表补 owner_id/runner_ids/is_archived（2026-06-26 数据迁移）
    pcols = [r[1] for r in conn.execute("PRAGMA table_info(products)").fetchall()]
    if "owner_id" not in pcols:
        conn.execute("ALTER TABLE products ADD COLUMN owner_id INTEGER REFERENCES users(id)")
        conn.execute("UPDATE products SET owner_id = 1 WHERE owner_id IS NULL")
    if "runner_ids" not in pcols:
        conn.execute("ALTER TABLE products ADD COLUMN runner_ids TEXT DEFAULT '[]'")
        conn.execute("UPDATE products SET runner_ids = '[1]' WHERE runner_ids IS NULL OR runner_ids = '[]'")
    if "is_archived" not in pcols:
        conn.execute("ALTER TABLE products ADD COLUMN is_archived INTEGER DEFAULT 0")
```

- [ ] **Step 2: 在 `_ensure_schema()` 的 `conn.executescript()` 中加入 import_history 建表**

在 `conn.executescript("""...` 的 SQL 块末尾（`users` 表之后、`scrape_cache` 表之前或之后均可）加入：

```sql
        -- 导入历史记录
        CREATE TABLE IF NOT EXISTS import_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER REFERENCES users(id),
            file_name TEXT,
            file_type TEXT,
            products_count INTEGER DEFAULT 0,
            packages_count INTEGER DEFAULT 0,
            accounts_count INTEGER DEFAULT 0,
            mcc_count INTEGER DEFAULT 0,
            videos_count INTEGER DEFAULT 0,
            copywritings_count INTEGER DEFAULT 0,
            tags_count INTEGER DEFAULT 0,
            skipped_count INTEGER DEFAULT 0,
            status TEXT DEFAULT 'success',
            error_msg TEXT DEFAULT '',
            created_at TEXT DEFAULT (datetime('now','localtime'))
        );
```

- [ ] **Step 3: 提交**

```bash
git add py/database.py
git commit -m "feat: add products owner_id/runner_ids and import_history table"
```

---

### Task 2: data_service.py — 导入导出核心逻辑

**Files:**
- Create: `py/data_service.py`

**Interfaces:**
- Produces:
  - `preview_import(file_path, file_type) -> dict` — 预览导入数据摘要
  - `execute_import(file_path, file_type, target_user_id) -> dict` — 执行导入
  - `export_user_data(user_id) -> dict` — 导出用户数据为 dict
  - `export_all_users() -> list[dict]` — 导出所有用户
  - `backup_database() -> str` — 返回备份路径
  - `restore_database(backup_path) -> None` — 恢复
  - `list_backups() -> list[dict]` — 列出备份
- Consumes: `database.get_db()`, `database._db_path()`

- [ ] **Step 1: 创建文件骨架**

```python
"""数据导入/导出核心逻辑，供 Web API 和 CLI 共用。"""
import sqlite3
import os
import json
import shutil
import datetime
from database import get_db, _db_path

# GG-Server 专属 config key，导入时跳过
GG_CONFIG_KEYS = {
    "migrated_video_history",
    "migrated_youtube",
    "migrated_font_recent",
    "gg_server_initialized",
    "migrated_owner_id",
    "db_version",
}
```

- [ ] **Step 2: 实现 `_read_source_db(path)` — 从 db 文件读取所有表数据**

```python
def _read_source_db(db_path: str) -> dict:
    """从源 db 文件读取所有表数据，返回 {table: [rows]}。"""
    if not os.path.isfile(db_path):
        raise FileNotFoundError(f"源数据库不存在: {db_path}")
    
    src = sqlite3.connect(db_path)
    src.row_factory = sqlite3.Row
    
    tables = {
        "products":      {"pk": "auto"},
        "packages":      {"pk": "auto"},
        "mcc":           {"pk": "auto"},
        "accounts":      {"pk": "auto"},
        "videos":        {"pk": "text", "pk_col": "id"},
        "video_history": {"pk": "auto"},
        "video_tasks":   {"pk": "auto"},
        "copywritings":  {"pk": "auto"},
        "tags":          {"pk": "text", "pk_col": "key"},
        "config":        {"pk": "text", "pk_col": "key"},
    }
    
    data = {}
    for table, info in tables.items():
        try:
            rows = src.execute(f"SELECT * FROM {table}").fetchall()
            data[table] = [dict(r) for r in rows]
        except sqlite3.OperationalError:
            data[table] = []
    
    src.close()
    return data
```

- [ ] **Step 3: 实现 `_read_source_json(path)` — 从 JSON 文件读取数据**

```python
def _read_source_json(json_path: str) -> dict:
    """从 JSON 文件读取数据，支持有 data 包裹和无包裹两种格式。"""
    if not os.path.isfile(json_path):
        raise FileNotFoundError(f"JSON 文件不存在: {json_path}")
    
    with open(json_path, "r", encoding="utf-8") as f:
        raw = json.load(f)
    
    # 兼容有 data 包裹的格式（GG-Server 导出格式）和裸格式（ImageCrawling 导出）
    if isinstance(raw, dict) and "data" in raw:
        return raw["data"]
    return raw
```

- [ ] **Step 4: 实现 `preview_import(file_path, file_type)` — 预览导入**

```python
def preview_import(file_path: str, file_type: str) -> dict:
    """解析文件返回将导入的数据摘要，不写入。"""
    if file_type == "db":
        data = _read_source_db(file_path)
    elif file_type == "json":
        data = _read_source_json(file_path)
    else:
        raise ValueError(f"不支持的文件类型: {file_type}")
    
    summary = {}
    for table in ["products", "packages", "accounts", "mcc", "videos",
                   "video_history", "video_tasks", "copywritings", "tags", "config"]:
        rows = data.get(table, [])
        if table == "config":
            rows = [r for r in rows if r.get("key") not in GG_CONFIG_KEYS]
        summary[table] = len(rows)
    
    return {"file_type": file_type, "summary": summary}
```

- [ ] **Step 5: 实现 `execute_import(file_path, file_type, target_user_id)` — 执行导入**

```python
def execute_import(file_path: str, file_type: str, target_user_id: int) -> dict:
    """解析文件、智能分流、写入目标库，返回导入报告。"""
    if file_type == "db":
        data = _read_source_db(file_path)
    elif file_type == "json":
        data = _read_source_json(file_path)
    else:
        raise ValueError(f"不支持的文件类型: {file_type}")

    db = get_db()
    db.execute("PRAGMA foreign_keys=OFF")

    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    report = {
        "products": 0, "packages": 0, "accounts": 0, "mcc": 0,
        "videos": 0, "video_history": 0, "video_tasks": 0,
        "copywritings": {"imported": 0, "skipped": 0},
        "tags": {"imported": 0, "skipped": 0},
        "skipped_config_keys": [],
    }

    # === products + packages: 归导入用户，跟踪 ID 映射 ===
    pid_map = {}  # old_product_id -> new_product_id
    product_cols = [c[1] for c in db.execute("PRAGMA table_info(products)").fetchall()]

    for r in data.get("products", []):
        d = dict(r)
        old_id = d.pop("id", None)
        d["owner_id"] = target_user_id
        d["runner_ids"] = json.dumps([target_user_id])
        cols = [k for k in d if k in product_cols]
        placeholders = ", ".join(["?"] * len(cols))
        vals = [d[c] for c in cols]
        db.execute(f"INSERT INTO products({', '.join(cols)}) VALUES({placeholders})", vals)
        new_pid = db.execute("SELECT last_insert_rowid()").fetchone()[0]
        if old_id is not None:
            pid_map[old_id] = new_pid
        report["products"] += 1

    # packages: 根据 product_id 映射归入新产品
    pkg_cols = [c[1] for c in db.execute("PRAGMA table_info(packages)").fetchall()]
    for p in data.get("packages", []):
        pd = dict(p)
        old_pid = pd.pop("id", None)
        old_product_id = pd.get("product_id")
        # 映射到新产品 ID，映射不到则跳过
        if old_product_id in pid_map:
            pd["product_id"] = pid_map[old_product_id]
        else:
            continue  # 孤儿包，跳过
        cols = [k for k in pd if k in pkg_cols]
        placeholders = ", ".join(["?"] * len(cols))
        vals = [pd[c] for c in cols]
        try:
            db.execute(f"INSERT INTO packages({', '.join(cols)}) VALUES({placeholders})", vals)
            report["packages"] += 1
        except sqlite3.IntegrityError:
            pass
    
    # === accounts: 归导入用户 ===
    for r in data.get("accounts", []):
        d = dict(r)
        d.pop("id", None)
        d["owner_id"] = target_user_id
        existing_cols = [c[1] for c in db.execute("PRAGMA table_info(accounts)").fetchall()]
        cols = [k for k in d if k in existing_cols]
        placeholders = ", ".join(["?"] * len(cols))
        vals = [d[c] for c in cols]
        try:
            db.execute(f"INSERT INTO accounts({', '.join(cols)}) VALUES({placeholders})", vals)
            report["accounts"] += 1
        except sqlite3.IntegrityError:
            report["skipped_count"] = report.get("skipped_count", 0) + 1
    
    # === mcc: 归导入用户 ===
    for r in data.get("mcc", []):
        d = dict(r)
        d.pop("id", None)
        d["owner_id"] = target_user_id
        existing_cols = [c[1] for c in db.execute("PRAGMA table_info(mcc)").fetchall()]
        cols = [k for k in d if k in existing_cols]
        placeholders = ", ".join(["?"] * len(cols))
        vals = [d[c] for c in cols]
        try:
            db.execute(f"INSERT INTO mcc({', '.join(cols)}) VALUES({placeholders})", vals)
            report["mcc"] += 1
        except sqlite3.IntegrityError:
            report["skipped_count"] = report.get("skipped_count", 0) + 1
    
    # === videos: 归导入用户 ===
    for r in data.get("videos", []):
        d = dict(r)
        d["owner_id"] = target_user_id
        d["is_public"] = 0
        existing_cols = [c[1] for c in db.execute("PRAGMA table_info(videos)").fetchall()]
        cols = [k for k in d if k in existing_cols]
        placeholders = ", ".join(["?"] * len(cols))
        vals = [d[c] for c in cols]
        try:
            db.execute(f"INSERT OR IGNORE INTO videos({', '.join(cols)}) VALUES({placeholders})", vals)
            if db.changes():
                report["videos"] += 1
            else:
                report["skipped_count"] = report.get("skipped_count", 0) + 1
        except sqlite3.IntegrityError:
            report["skipped_count"] = report.get("skipped_count", 0) + 1
    
    # === copywritings: 合并到共享池（按 content 去重） ===
    for r in data.get("copywritings", []):
        d = dict(r)
        d.pop("id", None)
        content = d.get("content", "")
        region = d.get("region", "通用")
        existing = db.execute(
            "SELECT id FROM copywritings WHERE content=? AND region=?", (content, region)
        ).fetchone()
        if existing:
            report["copywritings"]["skipped"] += 1
        else:
            db.execute(
                "INSERT INTO copywritings(region, content, created_at) VALUES(?,?,?)",
                (region, content, now)
            )
            report["copywritings"]["imported"] += 1
    
    # === tags: 合并到共享池（按 key 去重） ===
    for r in data.get("tags", []):
        d = dict(r)
        key = d.get("key", "")
        value = d.get("value", "")
        existing = db.execute("SELECT key FROM tags WHERE key=?", (key,)).fetchone()
        if existing:
            report["tags"]["skipped"] += 1
        else:
            db.execute("INSERT OR REPLACE INTO tags(key,value) VALUES(?,?)", (key, value))
            report["tags"]["imported"] += 1
    
    # === config: 只复制非 GG-Server 专属 key ===
    for r in data.get("config", []):
        d = dict(r)
        key = d.get("key", "")
        if key in GG_CONFIG_KEYS:
            report["skipped_config_keys"].append(key)
            continue
        value = d.get("value", "")
        db.execute("INSERT OR REPLACE INTO config(key,value) VALUES(?,?)", (key, value))
    
    # === video_history, video_tasks: 归导入用户（如果有） ===
    for table in ["video_history", "video_tasks"]:
        for r in data.get(table, []):
            d = dict(r)
            d.pop("id", None)
            existing_cols = [c[1] for c in db.execute(f"PRAGMA table_info({table})").fetchall()]
            cols = [k for k in d if k in existing_cols]
            if cols:
                placeholders = ", ".join(["?"] * len(cols))
                vals = [d[c] for c in cols]
                try:
                    db.execute(f"INSERT INTO {table}({', '.join(cols)}) VALUES({placeholders})", vals)
                    report[table] = report.get(table, 0) + 1
                except sqlite3.IntegrityError:
                    pass
    
    db.execute("PRAGMA foreign_keys=ON")
    db.commit()
    db.close()
    
    return {"success": True, "report": report}
```

- [ ] **Step 6: 实现 `export_user_data(user_id)` — 导出用户数据**

```python
def export_user_data(user_id: int) -> dict:
    """导出指定用户的所有数据为 dict。"""
    db = get_db()
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    # 获取用户名
    user = db.execute("SELECT username FROM users WHERE id=?", (user_id,)).fetchone()
    username = user["username"] if user else str(user_id)
    
    data = {}
    
    # products + packages
    products = [dict(r) for r in db.execute(
        "SELECT * FROM products WHERE owner_id=? AND is_archived=0", (user_id,)
    ).fetchall()]
    pkg_ids = [p["id"] for p in products]
    packages = []
    if pkg_ids:
        placeholders = ",".join(["?"] * len(pkg_ids))
        packages = [dict(r) for r in db.execute(
            f"SELECT * FROM packages WHERE product_id IN ({placeholders})", pkg_ids
        ).fetchall()]
    data["products"] = products
    data["packages"] = packages
    
    # accounts, mcc, videos
    for table in ["accounts", "mcc", "videos"]:
        data[table] = [dict(r) for r in db.execute(
            f"SELECT * FROM {table} WHERE owner_id=?", (user_id,)
        ).fetchall()]
    
    # video_history, video_tasks
    for table in ["video_history", "video_tasks"]:
        try:
            data[table] = [dict(r) for r in db.execute(
                f"SELECT * FROM {table}"
            ).fetchall()]
        except sqlite3.OperationalError:
            data[table] = []
    
    # copywritings, tags, config (共享数据也导出，方便备份)
    for table in ["copywritings", "tags"]:
        data[table] = [dict(r) for r in db.execute(f"SELECT * FROM {table}").fetchall()]
    
    # config: 只导出非系统 key
    data["config"] = [dict(r) for r in db.execute("SELECT * FROM config").fetchall()
                      if r["key"] not in GG_CONFIG_KEYS]
    
    db.close()
    
    return {
        "version": 1,
        "exported_at": now,
        "exported_by": username,
        "source": "gg-server",
        "data": data,
    }
```

- [ ] **Step 7: 实现备份/恢复函数**

```python
def backup_database() -> str:
    """复制 app.db 到 temp/backups/ 目录，返回备份路径。"""
    db_path = _db_path()
    backup_dir = os.path.join(os.path.dirname(db_path), "backups")
    os.makedirs(backup_dir, exist_ok=True)
    
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = os.path.join(backup_dir, f"app_{timestamp}.db")
    shutil.copy2(db_path, backup_path)
    return backup_path


def restore_database(backup_path: str) -> str:
    """用备份文件替换当前数据库。替换前自动备份当前库。"""
    if not os.path.isfile(backup_path):
        raise FileNotFoundError(f"备份文件不存在: {backup_path}")
    
    db_path = _db_path()
    
    # 先备份当前库
    current_backup = backup_database()
    
    # 替换
    shutil.copy2(backup_path, db_path)
    return current_backup


def list_backups() -> list[dict]:
    """列出所有备份文件。"""
    db_path = _db_path()
    backup_dir = os.path.join(os.path.dirname(db_path), "backups")
    if not os.path.isdir(backup_dir):
        return []
    
    backups = []
    for f in sorted(os.listdir(backup_dir), reverse=True):
        if f.endswith(".db"):
            fp = os.path.join(backup_dir, f)
            size_mb = os.path.getsize(fp) / (1024 * 1024)
            mtime = datetime.datetime.fromtimestamp(os.path.getmtime(fp)).strftime("%Y-%m-%d %H:%M:%S")
            backups.append({"name": f, "path": fp, "size_mb": round(size_mb, 1), "mtime": mtime})
    return backups
```

- [ ] **Step 8: 提交**

```bash
git add py/data_service.py
git commit -m "feat: add data import/export service module"
```

---

### Task 3: Web API — 新增数据导入导出路由

**Files:**
- Modify: `py/main.py` — 在文件末尾 `if __name__` 之前添加路由

**Interfaces:**
- Consumes: `data_service.py` 的所有导出函数

- [ ] **Step 1: 添加 import 和辅助函数**

在 `py/main.py` 顶部的 import 区域加入：

```python
import data_service
```

在 app 定义之后、`if __name__` 之前加入 admin 鉴权装饰器（如果已存在则跳过）：

```python
from functools import wraps

def admin_required(fn):
    @wraps(fn)
    @jwt_required()
    def wrapper(*args, **kwargs):
        user_id = int(get_jwt_identity())
        user = auth.get_user_by_id(user_id)
        if not user or user["role"] not in ("developer", "admin"):
            return jsonify({"success": False, "error": "权限不足"}), 403
        return fn(*args, **kwargs)
    return wrapper
```

- [ ] **Step 2: 添加 POST /api/data/import — 上传导入**

```python
@app.route("/api/data/import", methods=["POST"])
@jwt_required()
def data_import():
    """上传 db 或 json 文件，导入数据到当前用户。"""
    user_id = int(get_jwt_identity())
    
    if "file" not in request.files:
        return jsonify({"success": False, "error": "请上传文件"}), 400
    
    file = request.files["file"]
    if not file.filename:
        return jsonify({"success": False, "error": "文件名为空"}), 400
    
    # 识别文件类型
    fname = file.filename.lower()
    if fname.endswith(".db"):
        file_type = "db"
    elif fname.endswith(".json"):
        file_type = "json"
    else:
        return jsonify({"success": False, "error": "仅支持 .db 或 .json 文件"}), 400
    
    # 保存临时文件
    import tempfile
    suffix = ".db" if file_type == "db" else ".json"
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        file.save(tmp.name)
        tmp_path = tmp.name
    
    try:
        report = data_service.execute_import(tmp_path, file_type, user_id)
        
        # 记录导入历史
        db = database.get_db()
        history_report = report.get("report", {})
        db.execute(
            "INSERT INTO import_history(user_id, file_name, file_type, "
            "products_count, packages_count, accounts_count, mcc_count, videos_count, "
            "copywritings_count, tags_count, skipped_count, status) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
            (user_id, file.filename, file_type,
             history_report.get("products", 0),
             history_report.get("packages", 0),
             history_report.get("accounts", 0),
             history_report.get("mcc", 0),
             history_report.get("videos", 0),
             history_report.get("copywritings", {}).get("imported", 0),
             history_report.get("tags", {}).get("imported", 0),
             history_report.get("skipped_count", 0),
             "success")
        )
        db.commit()
        db.close()
        
        return jsonify(report)
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
```

- [ ] **Step 3: 添加 GET /api/data/export — 导出当前用户数据**

```python
@app.route("/api/data/export", methods=["GET"])
@jwt_required()
def data_export():
    """导出当前用户的数据为 JSON 文件下载。"""
    user_id = int(get_jwt_identity())
    user = auth.get_user_by_id(user_id)
    username = user["username"] if user else str(user_id)
    
    export_data = data_service.export_user_data(user_id)
    
    from flask import Response
    json_str = json.dumps(export_data, ensure_ascii=False, indent=2)
    date_str = datetime.datetime.now().strftime("%Y%m%d")
    filename = f"gg-server-export-{username}-{date_str}.json"
    
    return Response(
        json_str,
        mimetype="application/json",
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )
```

- [ ] **Step 4: 添加 GET /api/data/import-history**

```python
@app.route("/api/data/import-history", methods=["GET"])
@jwt_required()
def data_import_history():
    """返回当前用户的导入历史（最近 10 条）。"""
    user_id = int(get_jwt_identity())
    db = database.get_db()
    rows = db.execute(
        "SELECT * FROM import_history WHERE user_id=? ORDER BY created_at DESC LIMIT 10",
        (user_id,)
    ).fetchall()
    db.close()
    return jsonify({"success": True, "history": [dict(r) for r in rows]})
```

- [ ] **Step 5: 添加管理员导入导出路由**

```python
@app.route("/api/admin/data/import", methods=["POST"])
@admin_required
def admin_data_import():
    """管理员为指定用户导入数据。"""
    user_id = request.form.get("user_id", type=int)
    if not user_id:
        return jsonify({"success": False, "error": "请指定目标用户"}), 400
    
    if "file" not in request.files:
        return jsonify({"success": False, "error": "请上传文件"}), 400
    
    file = request.files["file"]
    fname = file.filename.lower()
    file_type = "db" if fname.endswith(".db") else "json"
    
    import tempfile
    suffix = ".db" if file_type == "db" else ".json"
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        file.save(tmp.name)
        tmp_path = tmp.name
    
    try:
        report = data_service.execute_import(tmp_path, file_type, user_id)
        return jsonify(report)
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass


@app.route("/api/admin/data/export/<int:uid>", methods=["GET"])
@admin_required
def admin_data_export(uid):
    """管理员导出指定用户的数据。"""
    user = auth.get_user_by_id(uid)
    if not user:
        return jsonify({"success": False, "error": "用户不存在"}), 404
    
    export_data = data_service.export_user_data(uid)
    
    from flask import Response
    json_str = json.dumps(export_data, ensure_ascii=False, indent=2)
    date_str = datetime.datetime.now().strftime("%Y%m%d")
    filename = f"gg-server-export-{user['username']}-{date_str}.json"
    
    return Response(
        json_str,
        mimetype="application/json",
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )
```

- [ ] **Step 6: 确认 datetime 和 json 已 import**

在 main.py 顶部确认有：

```python
import datetime
```

- [ ] **Step 7: 提交**

```bash
git add py/main.py
git commit -m "feat: add data import/export web API routes"
```

---

### Task 4: Web API — 产品管理增强

**Files:**
- Modify: `py/main.py` — 修改 `products_list()`，新增 `products_merge()` 和 `products_update_runners()`

- [ ] **Step 1: 修改 products_list — 加 runner 筛选**

在 `products_list()` 函数中，参数区域加：

```python
    runner = request.args.get("runner", "mine").strip()  # "mine" | "all"
```

在 `where` 构建区（`if search:` 之前）加 runner 过滤逻辑：

```python
    if runner == "mine":
        # 需要用户登录才能筛选"我在跑的"
        try:
            user_id = int(get_jwt_identity())
        except Exception:
            user_id = None
        if user_id:
            where.append("(p.runner_ids LIKE ? OR p.owner_id = ?)")
            params += [f'%{user_id}%', user_id]
```

- [ ] **Step 2: 添加 POST /api/products/merge — 合并产品**

```python
@app.route("/api/products/merge", methods=["POST"])
@jwt_required()
def products_merge():
    """合并多个产品到主产品。"""
    data = request.get_json(silent=True) or {}
    master_id = data.get("master_id")  # 主产品 ID（保留）
    merge_ids = data.get("merge_ids") or []  # 被合并产品 ID 列表
    
    if not master_id or not merge_ids:
        return jsonify({"success": False, "error": "请指定主产品和被合并产品"}), 400
    if master_id in merge_ids:
        return jsonify({"success": False, "error": "主产品不能在被合并列表中"}), 400
    
    db = _yt_db()
    db.execute("PRAGMA foreign_keys=OFF")
    
    # 获取主产品的 runner_ids
    master = db.execute("SELECT runner_ids FROM products WHERE id=?", (master_id,)).fetchone()
    if not master:
        db.close()
        return jsonify({"success": False, "error": "主产品不存在"}), 404
    
    try:
        master_runners = json.loads(master["runner_ids"] or "[]")
    except Exception:
        master_runners = []
    
    merged_packages = 0
    merged_runners = set()
    
    for mid in merge_ids:
        sub = db.execute("SELECT * FROM products WHERE id=?", (mid,)).fetchone()
        if not sub:
            continue
        
        # 合并 runner_ids
        try:
            sub_runners = json.loads(sub["runner_ids"] or "[]")
        except Exception:
            sub_runners = []
        for r in sub_runners:
            master_runners.append(r)
            merged_runners.update(sub_runners)
        
        # 迁移 packages
        pkgs = db.execute("SELECT * FROM packages WHERE product_id=?", (mid,)).fetchall()
        for p in pkgs:
            pd = dict(p)
            # 检查主产品中是否已有同名+同链接的包
            existing = db.execute(
                "SELECT id FROM packages WHERE product_id=? AND package_name=? AND url=?",
                (master_id, pd.get("package_name", ""), pd.get("url", ""))
            ).fetchone()
            if not existing:
                pd.pop("id", None)
                pd["product_id"] = master_id
                cols = list(pd.keys())
                placeholders = ", ".join(["?"] * len(cols))
                vals = [pd[c] for c in cols]
                db.execute(
                    f"INSERT INTO packages({', '.join(cols)}) VALUES({placeholders})", vals
                )
                merged_packages += 1
        
        # 删除副产品
        db.execute("DELETE FROM packages WHERE product_id=?", (mid,))
        db.execute("DELETE FROM products WHERE id=?", (mid,))
    
    # 去重并更新主产品 runner_ids
    master_runners = list(set(master_runners))
    db.execute("UPDATE products SET runner_ids=? WHERE id=?",
               (json.dumps(master_runners), master_id))
    
    db.execute("PRAGMA foreign_keys=ON")
    db.commit()
    db.close()
    
    return jsonify({
        "success": True,
        "merged_packages": merged_packages,
        "merged_products": len(merge_ids),
        "total_runners": len(master_runners),
    })
```

- [ ] **Step 3: 添加 PUT /api/products/<pid>/runners — 更新 runner 列表**

```python
@app.route("/api/products/<int:pid>/runners", methods=["PUT"])
@jwt_required()
def products_update_runners(pid):
    """更新产品的 runner 列表。"""
    data = request.get_json(silent=True) or {}
    runner_ids = data.get("runner_ids")  # list of user IDs
    
    if runner_ids is None or not isinstance(runner_ids, list):
        return jsonify({"success": False, "error": "请提供 runner_ids 列表"}), 400
    
    db = _yt_db()
    existing = db.execute("SELECT id FROM products WHERE id=?", (pid,)).fetchone()
    if not existing:
        db.close()
        return jsonify({"success": False, "error": "产品不存在"}), 404
    
    db.execute("UPDATE products SET runner_ids=? WHERE id=?",
               (json.dumps(runner_ids), pid))
    db.commit()
    db.close()
    
    return jsonify({"success": True, "runner_ids": runner_ids})
```

- [ ] **Step 4: 提交**

```bash
git add py/main.py
git commit -m "feat: add product runner filter, merge, and runner management APIs"
```

---

### Task 5: CLI 管理工具 — manage.py

**Files:**
- Create: `py/manage.py`

- [ ] **Step 1: 创建 manage.py**

```python
"""GG-Server 数据管理 CLI 工具。

用法：
  python manage.py backup                          # 整库备份
  python manage.py list-backups                    # 列出备份
  python manage.py restore <备份路径>               # 整库恢复
  python manage.py import-db <db路径> --user <用户名>    # 从 db 导入
  python manage.py import-json <json路径> --user <用户名> # 从 JSON 导入
  python manage.py export-user <用户名> [-o output.json] # 导出用户
  python manage.py export-all [-o output_dir/]          # 导出所有用户
"""
import sys
import os
import json
import argparse

# 确保当前目录在 path 中
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import data_service
import auth
import database


def cmd_backup():
    path = data_service.backup_database()
    print(f"✅ 备份完成: {path}")


def cmd_list_backups():
    backups = data_service.list_backups()
    if not backups:
        print("(无备份文件)")
        return
    print(f"{'文件名':<40} {'大小':>8} {'时间':>20}")
    print("-" * 70)
    for b in backups:
        print(f"{b['name']:<40} {b['size_mb']:>6.1f}MB {b['mtime']:>20}")


def cmd_restore(args):
    backup_path = args.path
    if not os.path.isfile(backup_path):
        print(f"❌ 备份文件不存在: {backup_path}")
        sys.exit(1)
    current = data_service.restore_database(backup_path)
    print(f"✅ 已恢复。原库备份至: {current}")


def cmd_import(args):
    file_path = args.path
    username = args.user
    
    user = auth.get_user_by_username(username)
    if not user:
        print(f"❌ 用户不存在: {username}")
        sys.exit(1)
    
    file_type = "db" if file_path.endswith(".db") else "json"
    print(f"导入 {file_type} 文件: {file_path}")
    print(f"目标用户: {username} (id={user['id']})")
    
    report = data_service.execute_import(file_path, file_type, user["id"])
    
    r = report.get("report", {})
    print(f"✅ 导入完成:")
    print(f"  products: {r.get('products', 0)}")
    print(f"  packages: {r.get('packages', 0)}")
    print(f"  accounts: {r.get('accounts', 0)}")
    print(f"  mcc:      {r.get('mcc', 0)}")
    print(f"  videos:   {r.get('videos', 0)}")
    cw = r.get("copywritings", {})
    print(f"  copywritings: {cw.get('imported', 0)} 条导入, {cw.get('skipped', 0)} 条跳过")
    tg = r.get("tags", {})
    print(f"  tags:         {tg.get('imported', 0)} 条导入, {tg.get('skipped', 0)} 条跳过")


def cmd_export_user(args):
    username = args.user
    user = auth.get_user_by_username(username)
    if not user:
        print(f"❌ 用户不存在: {username}")
        sys.exit(1)
    
    data = data_service.export_user_data(user["id"])
    output = args.output or f"gg-server-export-{username}.json"
    
    with open(output, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    
    print(f"✅ 已导出到: {output}")


def cmd_export_all(args):
    output_dir = args.output or "exports"
    os.makedirs(output_dir, exist_ok=True)
    
    db = database.get_db()
    users = db.execute("SELECT id, username FROM users WHERE role != 'hidden'").fetchall()
    db.close()
    
    for u in users:
        data = data_service.export_user_data(u["id"])
        fname = f"gg-server-export-{u['username']}.json"
        fpath = os.path.join(output_dir, fname)
        with open(fpath, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        print(f"  ✅ {u['username']} → {fname}")
    
    print(f"\n共导出 {len(users)} 个用户到: {output_dir}")


def main():
    parser = argparse.ArgumentParser(description="GG-Server 数据管理工具")
    sub = parser.add_subparsers(dest="command")
    
    sub.add_parser("backup", help="整库备份")
    sub.add_parser("list-backups", help="列出备份")
    
    p = sub.add_parser("restore", help="整库恢复")
    p.add_argument("path", help="备份文件路径")
    
    p = sub.add_parser("import-db", help="从 db 文件导入")
    p.add_argument("path", help="db 文件路径")
    p.add_argument("--user", required=True, help="目标用户名")
    
    p = sub.add_parser("import-json", help="从 JSON 文件导入")
    p.add_argument("path", help="JSON 文件路径")
    p.add_argument("--user", required=True, help="目标用户名")
    
    p = sub.add_parser("export-user", help="导出指定用户")
    p.add_argument("user", help="用户名")
    p.add_argument("-o", "--output", help="输出文件路径")
    
    p = sub.add_parser("export-all", help="导出所有用户")
    p.add_argument("-o", "--output", help="输出目录")
    
    args = parser.parse_args()
    
    if not args.command:
        parser.print_help()
        return
    
    commands = {
        "backup": cmd_backup,
        "list-backups": cmd_list_backups,
        "restore": lambda: cmd_restore(args),
        "import-db": lambda: cmd_import(args),
        "import-json": lambda: cmd_import(args),
        "export-user": lambda: cmd_export_user(args),
        "export-all": lambda: cmd_export_all(args),
    }
    
    try:
        commands[args.command]()
    except Exception as e:
        print(f"❌ 错误: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: 提交**

```bash
git add py/manage.py
git commit -m "feat: add CLI manage tool for backup/import/export"
```

---

### Task 6: 前端 API 层 — 新增数据传输函数

**Files:**
- Create: `frontend/src/api/data.js`
- Modify: `frontend/src/api/products.js`

- [ ] **Step 1: 创建 frontend/src/api/data.js**

```javascript
import api from './client'

export const dataApi = {
  // 上传文件导入（自动识别 db/json）
  importFile(file) {
    const formData = new FormData()
    formData.append('file', file)
    return api.post('/data/import', formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
      timeout: 120000,
    })
  },

  // 导出当前用户数据
  exportData() {
    return api.get('/data/export', { responseType: 'blob' })
  },

  // 导入历史
  importHistory() {
    return api.get('/data/import-history')
  },
}

export const adminDataApi = {
  // 管理员为指定用户导入
  importForUser(file, userId) {
    const formData = new FormData()
    formData.append('file', file)
    formData.append('user_id', userId)
    return api.post('/admin/data/import', formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
      timeout: 120000,
    })
  },

  // 管理员导出指定用户
  exportUserData(userId) {
    return api.get(`/admin/data/export/${userId}`, { responseType: 'blob' })
  },
}
```

- [ ] **Step 2: 扩展 frontend/src/api/products.js**

```javascript
import api from './client'

export const productsApi = {
  list:        (params) => api.get('/api/products/list', { params }),
  create:      (body)   => api.post('/api/products/create', body),
  update:      (id, body) => api.put(`/api/products/${id}`, body),
  delete:      (id)     => api.delete(`/api/products/${id}`),
  detail:      (id)     => api.get(`/api/products/${id}/detail`),
  addPackage:  (pid, body) => api.post(`/api/products/${pid}/packages`, body),
  updatePackage: (pkgId, body) => api.put(`/api/products/packages/${pkgId}`, body),
  deletePackage: (pkgId) => api.delete(`/api/products/packages/${pkgId}`),
  importText:  (body)   => api.post('/api/products/import-text', body),
  // 新增
  merge:       (body)   => api.post('/api/products/merge', body),
  updateRunners: (pid, body) => api.put(`/api/products/${pid}/runners`, body),
}
```

- [ ] **Step 3: 提交**

```bash
git add frontend/src/api/data.js frontend/src/api/products.js
git commit -m "feat: add frontend API layer for data import/export and product enhancements"
```

---

### Task 7: 前端 — 设置页新增数据管理标签

**Files:**
- Modify: `frontend/src/views/SettingsPanel.vue`

**UI 说明**：SettingsPanel 目前只有账户设置表单。需改为 tabs 结构：账户设置 / 数据管理。

- [ ] **Step 1: 重构为 tabs 布局**

将现有内容放入「账户设置」tab，新增「数据管理」tab：

```vue
<template>
  <div>
    <h2>⚙ 设置</h2>
    <el-tabs v-model="activeTab">
      <!-- Tab 1: 账户设置 -->
      <el-tab-pane label="账户设置" name="account">
        <p style="color:#888;margin-bottom:20px;">自定义下拉框选项，修改后全局生效</p>
        <el-row :gutter="16">
          <el-col :span="12">
            <el-form-item label="账户状态选项">
              <el-input v-model="form.account_statuses" type="textarea" :rows="5"
                placeholder="每行一个" />
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="代理名选项">
              <el-input v-model="form.account_agents" type="textarea" :rows="5"
                placeholder="每行一个（留空则自由输入）" />
            </el-form-item>
          </el-col>
        </el-row>
        <el-form-item label="MCC 等级选项">
          <el-input v-model="form.mcc_levels" type="textarea" :rows="3"
            placeholder="每行一个（留空则自由输入）" />
        </el-form-item>
        <el-button type="primary" @click="save" :loading="saving">💾 保存配置</el-button>
        <span v-if="msg" style="margin-left:8px;font-size:11px;color:#059669;">{{ msg }}</span>
      </el-tab-pane>

      <!-- Tab 2: 数据管理 -->
      <el-tab-pane label="数据管理" name="data">
        <el-row :gutter="20">
          <!-- 导出区 -->
          <el-col :span="12">
            <el-card shadow="hover">
              <template #header>📤 导出数据</template>
              <p style="color:#888;margin-bottom:12px;">导出你的所有数据为 JSON 文件，可用于备份或迁移。</p>
              <el-button type="primary" @click="exportData" :loading="exporting">
                📥 导出我的数据
              </el-button>
            </el-card>
          </el-col>

          <!-- 导入区 -->
          <el-col :span="12">
            <el-card shadow="hover">
              <template #header>📥 导入数据</template>
              <p style="color:#888;margin-bottom:12px;">
                上传 ImageCrawling 的 app.db 或 JSON 导出文件。
              </p>
              <el-upload
                :auto-upload="false"
                :on-change="onFileChange"
                :limit="1"
                accept=".db,.json"
                drag
              >
                <el-icon><UploadFilled /></el-icon>
                <div>拖拽或点击上传 .db / .json 文件</div>
              </el-upload>
              <el-button
                type="success"
                @click="confirmImport"
                :loading="importing"
                :disabled="!importFile"
                style="margin-top:10px;"
              >
                ✅ 确认导入
              </el-button>
            </el-card>
          </el-col>
        </el-row>

        <!-- 导入历史 -->
        <el-card shadow="hover" style="margin-top:20px;">
          <template #header>📋 导入历史</template>
          <el-table :data="importHistory" v-if="importHistory.length" size="small">
            <el-table-column prop="file_name" label="文件名" />
            <el-table-column prop="file_type" label="类型" width="60" />
            <el-table-column prop="products_count" label="产品" width="60" />
            <el-table-column prop="accounts_count" label="账户" width="60" />
            <el-table-column prop="videos_count" label="视频" width="60" />
            <el-table-column prop="status" label="状态" width="80">
              <template #default="{ row }">
                <el-tag :type="row.status === 'success' ? 'success' : 'danger'" size="small">
                  {{ row.status }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="created_at" label="时间" width="160" />
          </el-table>
          <el-empty v-else description="暂无导入记录" :image-size="60" />
        </el-card>
      </el-tab-pane>
    </el-tabs>
  </div>
</template>
```

- [ ] **Step 2: 添加 script 逻辑**

```javascript
<script setup>
import { ref, reactive, onMounted } from 'vue'
import { useAccountStore } from '@/stores/accounts'
import { dataApi } from '@/api/data'
import { ElMessage } from 'element-plus'

const store = useAccountStore()
const saving = ref(false)
const msg = ref('')
const activeTab = ref('account')

const form = reactive({
  account_statuses: '',
  account_agents: '',
  mcc_levels: '',
})

// 数据管理
const exporting = ref(false)
const importing = ref(false)
const importFile = ref(null)
const importHistory = ref([])

onMounted(async () => {
  await store.loadSettings()
  form.account_statuses = (store.settings.account_statuses || []).join('\n')
  form.account_agents = (store.settings.account_agents || []).join('\n')
  form.mcc_levels = (store.settings.mcc_levels || []).join('\n')
  loadImportHistory()
})

async function save() { /* 原有逻辑不变 */ }

async function exportData() {
  exporting.value = true
  try {
    const blob = await dataApi.exportData()
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    // 从 Content-Disposition 提取文件名
    a.download = `gg-server-export-${Date.now()}.json`
    a.click()
    URL.revokeObjectURL(url)
    ElMessage.success('导出成功')
  } catch (e) {
    ElMessage.error('导出失败: ' + (e.response?.data?.error || e.message))
  }
  exporting.value = false
}

function onFileChange(file) {
  importFile.value = file.raw
}

async function confirmImport() {
  if (!importFile.value) return
  importing.value = true
  try {
    const res = await dataApi.importFile(importFile.value)
    ElMessage.success(`导入完成：产品 ${res.report?.products || 0}，账户 ${res.report?.accounts || 0}，视频 ${res.report?.videos || 0}`)
    importFile.value = null
    loadImportHistory()
  } catch (e) {
    ElMessage.error('导入失败: ' + (e.response?.data?.error || e.message))
  }
  importing.value = false
}

async function loadImportHistory() {
  try {
    const res = await dataApi.importHistory()
    importHistory.value = res.history || []
  } catch (e) { /* 静默失败 */ }
}
</script>
```

- [ ] **Step 3: 提交**

```bash
git add frontend/src/views/SettingsPanel.vue
git commit -m "feat: add data management tab to settings panel"
```

---

### Task 8: 前端 — 产品列表改造（筛选 + 合并 + runner）

**Files:**
- Modify: `frontend/src/views/ProductPanel.vue`
- Modify: `frontend/src/stores/products.js`（如果有的话）

- [ ] **Step 1: 加 runner 筛选和合并按钮**

在 ProductPanel.vue 的工具栏中，新增 runner 筛选和合并按钮：

```vue
<!-- 在现有 <el-select v-model="store.filters.region" ...> 之前加 -->
<el-radio-group v-model="runnerFilter" @change="load" size="small">
  <el-radio-button value="mine">我在跑的</el-radio-button>
  <el-radio-button value="all">全部产品</el-radio-button>
</el-radio-group>

<!-- 在现有工具栏末尾加合并按钮 -->
<el-button
  v-if="selectedIds.length >= 2"
  type="warning"
  @click="mergeProducts"
>
  🔀 合并产品 ({{ selectedIds.length }})
</el-button>
```

- [ ] **Step 2: 加产品勾选逻辑**

在 script 中加：

```javascript
const runnerFilter = ref('mine')
const selectedIds = ref([])

// 修改 load 函数传参
async function load() {
  const res = await store.loadProducts({ runner: runnerFilter.value })
  regions.value = res.regions || []
  mccOptions.value = res.mcc_options || []
  selectedIds.value = []
}

// 合并产品
async function mergeProducts() {
  if (selectedIds.value.length < 2) return
  try {
    await ElMessageBox.confirm(
      `将 ${selectedIds.value.length - 1} 个产品合并到第一个选中产品中？此操作不可撤销。`,
      '确认合并', { type: 'warning', confirmButtonText: '合并', cancelButtonText: '取消' }
    )
    await productsApi.merge({
      master_id: selectedIds.value[0],
      merge_ids: selectedIds.value.slice(1),
    })
    ElMessage.success('合并完成')
    selectedIds.value = []
    load()
  } catch (e) {
    if (e !== 'cancel') ElMessage.error('合并失败')
  }
}
```

- [ ] **Step 3: 在 ProductCard 组件加勾选框**

修改 ProductCard 使用处：

```vue
<ProductCard
  v-for="p in store.products" :key="p.id"
  :product="p"
  :selected="selectedIds.includes(p.id)"
  @select="toggleSelect(p.id)"
  @edit="showProductModal($event)"
  ...
/>
```

在 script 中加：

```javascript
function toggleSelect(id) {
  const idx = selectedIds.value.indexOf(id)
  if (idx >= 0) selectedIds.value.splice(idx, 1)
  else selectedIds.value.push(id)
}
```

- [ ] **Step 4: 在 ProductDetailModal 加 runner 管理区**

在 ProductDetailModal 中添加 Runner 管理区域（使用 el-tag 显示现有 runner，el-select 添加新 runner）：

```vue
<!-- 在产品详情弹窗中添加 -->
<el-divider />
<h4>🏃 在跑成员</h4>
<div style="display:flex;gap:6px;flex-wrap:wrap;margin-bottom:10px;">
  <el-tag
    v-for="rid in product?.runner_ids || []"
    :key="rid"
    closable
    @close="removeRunner(rid)"
    size="small"
  >
    {{ getUserName(rid) }}
  </el-tag>
</div>
<el-select
  v-model="newRunnerId"
  placeholder="添加 runner..."
  size="small"
  style="width:200px;"
  @change="addRunner"
>
  <el-option
    v-for="u in availableUsers"
    :key="u.id"
    :label="u.display_name || u.username"
    :value="u.id"
    :disabled="(product?.runner_ids || []).includes(u.id)"
  />
</el-select>
```

在 ProductDetailModal 的 script 中加对应的加载用户列表和添加/移除 runner 逻辑。

- [ ] **Step 5: 提交**

```bash
git add frontend/src/views/ProductPanel.vue frontend/src/components/ProductCard.vue frontend/src/components/ProductDetailModal.vue
git commit -m "feat: add product runner filter, merge, and runner management UI"
```

---

### Task 9: 前端 — 用户管理页加导入按钮

**Files:**
- Modify: `frontend/src/views/UserManageView.vue`

- [ ] **Step 1: 在每个用户行加导入按钮**

在用户表格的操作列加：

```vue
<el-table-column label="操作" width="280" fixed="right">
  <template #default="{ row }">
    <el-button size="small" @click="showImportDialog(row)">📥 导入数据</el-button>
    <!-- 原有按钮... -->
  </template>
</el-table-column>
```

- [ ] **Step 2: 加导入弹窗**

```vue
<el-dialog v-model="importDialogVisible" title="导入数据" width="400px">
  <p>为 <b>{{ importTargetUser?.display_name || importTargetUser?.username }}</b> 导入数据</p>
  <el-upload
    :auto-upload="false"
    :on-change="onAdminFileChange"
    :limit="1"
    accept=".db,.json"
    drag
  >
    <el-icon><UploadFilled /></el-icon>
    <div>拖拽或点击上传 .db / .json 文件</div>
  </el-upload>
  <template #footer>
    <el-button @click="importDialogVisible = false">取消</el-button>
    <el-button type="primary" @click="adminConfirmImport" :loading="adminImporting" :disabled="!adminImportFile">
      确认导入
    </el-button>
  </template>
</el-dialog>
```

在 script 中加：

```javascript
import { adminDataApi } from '@/api/data'

const importDialogVisible = ref(false)
const importTargetUser = ref(null)
const adminImportFile = ref(null)
const adminImporting = ref(false)

function showImportDialog(user) {
  importTargetUser.value = user
  importDialogVisible.value = true
}

function onAdminFileChange(file) {
  adminImportFile.value = file.raw
}

async function adminConfirmImport() {
  if (!adminImportFile.value || !importTargetUser.value) return
  adminImporting.value = true
  try {
    const res = await adminDataApi.importForUser(adminImportFile.value, importTargetUser.value.id)
    ElMessage.success(`导入完成`)
    importDialogVisible.value = false
    adminImportFile.value = null
  } catch (e) {
    ElMessage.error('导入失败: ' + (e.response?.data?.error || e.message))
  }
  adminImporting.value = false
}
```

- [ ] **Step 2: 提交**

```bash
git add frontend/src/views/UserManageView.vue
git commit -m "feat: add admin import button to user management page"
```

---

### Task 10: 现有数据回填 + 最终验证

- [ ] **Step 1: 启动服务验证**

```bash
cd py && python main.py
# 检查控制台无错误，访问 http://127.0.0.1:5000
```

- [ ] **Step 2: 验证数据库迁移**

```bash
sqlite3 temp/app.db "PRAGMA table_info(products)"
# 确认有 owner_id, runner_ids, is_archived 列
sqlite3 temp/app.db "SELECT * FROM import_history LIMIT 1"
# 确认表存在
```

- [ ] **Step 3: 验证 CLI**

```bash
python manage.py backup
# 应在 temp/backups/ 下生成 .db 文件
python manage.py list-backups
# 应列出备份文件
```

- [ ] **Step 4: 验证 API**

```bash
# 登录
curl -s -X POST http://127.0.0.1:5000/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username":"admin","password":"admin123"}'
# 用 token 测试导出
curl -s http://127.0.0.1:5000/api/data/export \
  -H "Authorization: Bearer <token>"
```

- [ ] **Step 5: 提交**

```bash
git add -A
git commit -m "chore: final verification and adjustments"
```
