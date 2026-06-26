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

    # === mcc: 归导入用户，跟踪 ID 映射 ===
    mcc_map = {}  # old_mcc_id -> new_mcc_id
    mcc_cols = [c[1] for c in db.execute("PRAGMA table_info(mcc)").fetchall()]
    for r in data.get("mcc", []):
        d = dict(r)
        old_id = d.pop("id", None)
        d["owner_id"] = target_user_id
        cols = [k for k in d if k in mcc_cols]
        placeholders = ", ".join(["?"] * len(cols))
        vals = [d[c] for c in cols]
        try:
            db.execute(f"INSERT INTO mcc({', '.join(cols)}) VALUES({placeholders})", vals)
            new_mid = db.execute("SELECT last_insert_rowid()").fetchone()[0]
            if old_id is not None:
                mcc_map[old_id] = new_mid
            report["mcc"] += 1
        except sqlite3.IntegrityError:
            report["skipped_count"] = report.get("skipped_count", 0) + 1

    # 修正 MCC 的 parent_mcc_id 映射
    for old_pid, new_pid in mcc_map.items():
        db.execute("UPDATE mcc SET parent_mcc_id=? WHERE parent_mcc_id=? AND owner_id=?",
                   (new_pid, old_pid, target_user_id))

    # === accounts: 归导入用户，mcc_id 映射到新 ID ===
    account_cols = [c[1] for c in db.execute("PRAGMA table_info(accounts)").fetchall()]
    for r in data.get("accounts", []):
        d = dict(r)
        d.pop("id", None)
        d["owner_id"] = target_user_id
        # 映射 mcc_id
        old_mcc = d.get("mcc_id")
        if old_mcc is not None and old_mcc in mcc_map:
            d["mcc_id"] = mcc_map[old_mcc]
        elif old_mcc is not None:
            d["mcc_id"] = None  # 映射不到，清空
        cols = [k for k in d if k in account_cols]
        placeholders = ", ".join(["?"] * len(cols))
        vals = [d[c] for c in cols]
        try:
            db.execute(f"INSERT INTO accounts({', '.join(cols)}) VALUES({placeholders})", vals)
            report["accounts"] += 1
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
            cur = db.execute(f"INSERT OR IGNORE INTO videos({', '.join(cols)}) VALUES({placeholders})", vals)
            if cur.rowcount > 0:
                report["videos"] += 1
            else:
                report["skipped_count"] = report.get("skipped_count", 0) + 1
        except sqlite3.IntegrityError:
            report["skipped_count"] = report.get("skipped_count", 0) + 1

    # === copywritings: 归导入用户 ===
    for r in data.get("copywritings", []):
        d = dict(r)
        d.pop("id", None)
        d["owner_id"] = target_user_id
        existing_cols = [c[1] for c in db.execute("PRAGMA table_info(copywritings)").fetchall()]
        cols = [k for k in d if k in existing_cols]
        if cols:
            placeholders = ", ".join(["?"] * len(cols))
            vals = [d[c] for c in cols]
            db.execute(f"INSERT INTO copywritings({', '.join(cols)}) VALUES({placeholders})", vals)
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

    # copywritings: 归入用户私有
    data["copywritings"] = [dict(r) for r in db.execute(
        "SELECT * FROM copywritings WHERE owner_id=?", (user_id,)
    ).fetchall()]

    # tags, config (共享数据也导出，方便备份)
    for table in ["tags"]:
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


def export_all_users() -> list[dict]:
    """导出所有用户的数据为列表。"""
    db = get_db()
    users = [dict(r) for r in db.execute("SELECT id, username FROM users").fetchall()]
    db.close()

    results = []
    for user in users:
        user_data = export_user_data(user["id"])
        user_data["user_id"] = user["id"]
        user_data["username"] = user["username"]
        results.append(user_data)

    return results


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
