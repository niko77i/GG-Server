"""统一 SQLite 存储 — 替换散落的 JSON 文件。

数据库路径：{_DATA_ROOT}/temp/app.db
"""

import os
import sqlite3
import json
import datetime


def _db_path() -> str:
    """计算数据库路径。需要 DATA_ROOT，由调用方注入或在此延迟导入。"""
    # 与 main.py 共享 _DATA_ROOT 的方式：通过环境变量或模块属性
    # 最简单的方式：由 main.py 在启动时设置
    import sys
    frozen = getattr(sys, "frozen", False)
    if frozen:
        root = os.path.dirname(sys.executable)
    else:
        # 开发模式：database.py 在 py/ 下，上级是项目根
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(root, "temp", "app.db")


def get_db() -> sqlite3.Connection:
    """获取数据库连接，自动建表 + 迁移。"""
    db_path = _db_path()
    os.makedirs(os.path.dirname(db_path), exist_ok=True)

    conn = sqlite3.connect(db_path, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA foreign_keys=ON")
    _ensure_schema(conn)
    _migrate_if_needed(conn)
    return conn


def _ensure_schema(conn: sqlite3.Connection):
    """创建所有表（IF NOT EXISTS）。"""
    conn.executescript("""
        -- 视频生成历史（替换 temp/video_set/*.json）
        CREATE TABLE IF NOT EXISTS video_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            package TEXT NOT NULL,
            name TEXT DEFAULT '',
            settings TEXT NOT NULL,
            created_at TEXT DEFAULT (datetime('now','localtime')),
            updated_at TEXT DEFAULT (datetime('now','localtime'))
        );
        CREATE INDEX IF NOT EXISTS idx_history_pkg ON video_history(package);

        -- 视频任务记录（持久化，重启后仍可查询历史）
        CREATE TABLE IF NOT EXISTS video_tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id TEXT UNIQUE NOT NULL,
            package TEXT DEFAULT '',
            status TEXT DEFAULT 'pending',
            progress REAL DEFAULT 0,
            message TEXT DEFAULT '',
            output_path TEXT DEFAULT '',
            settings TEXT DEFAULT '{}',
            created_at TEXT DEFAULT (datetime('now','localtime')),
            finished_at TEXT DEFAULT ''
        );
        CREATE INDEX IF NOT EXISTS idx_tasks_status ON video_tasks(status);

        -- YouTube 视频（从 youtube.db 迁移）
        CREATE TABLE IF NOT EXISTS videos (
            id TEXT PRIMARY KEY,
            url TEXT,
            title TEXT,
            region TEXT DEFAULT '通用',
            frame_type TEXT DEFAULT '非融帧',
            effectiveness TEXT DEFAULT '',
            product_name TEXT DEFAULT '',
            review_status TEXT DEFAULT '能过审',
            imported_at TEXT
        );

        -- 标签（通用 key-value，含 YouTube tags + 全局 config）
        CREATE TABLE IF NOT EXISTS tags (
            key TEXT PRIMARY KEY,
            value TEXT
        );

        -- 字体最近使用（替换 fonts/.recent.json）
        CREATE TABLE IF NOT EXISTS config (
            key TEXT PRIMARY KEY,
            value TEXT
        );

        -- 账户与 MCC 管理
        CREATE TABLE IF NOT EXISTS mcc (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            mcc_id TEXT UNIQUE NOT NULL,
            level TEXT DEFAULT '',
            parent_mcc_id INTEGER REFERENCES mcc(id),
            created_at TEXT DEFAULT (datetime('now','localtime')),
            updated_at TEXT DEFAULT (datetime('now','localtime'))
        );

        CREATE TABLE IF NOT EXISTS accounts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            account_id TEXT UNIQUE NOT NULL,
            mcc_id INTEGER REFERENCES mcc(id),
            timezone TEXT DEFAULT '',
            agent TEXT DEFAULT '',
            status TEXT DEFAULT '存活',
            acquired_date TEXT DEFAULT (date('now','localtime')),
            death_date TEXT DEFAULT '',
            created_at TEXT DEFAULT (datetime('now','localtime')),
            updated_at TEXT DEFAULT (datetime('now','localtime'))
        );

        -- 文案管理
        CREATE TABLE IF NOT EXISTS copywritings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            region TEXT NOT NULL DEFAULT '通用',
            content TEXT NOT NULL,
            owner_id INTEGER REFERENCES users(id),
            effectiveness TEXT DEFAULT '',
            created_at TEXT DEFAULT (datetime('now','localtime'))
        );
        CREATE INDEX IF NOT EXISTS idx_copywritings_region ON copywritings(region);

        -- 产品与包管理
        CREATE TABLE IF NOT EXISTS products (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            product_name TEXT,
            kpi TEXT,
            region TEXT,
            status TEXT DEFAULT '',
            mcc_id INTEGER REFERENCES mcc(id),
            created_at TEXT DEFAULT (datetime('now','localtime'))
        );

        CREATE TABLE IF NOT EXISTS packages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            product_id INTEGER,
            series_name TEXT,
            package_name TEXT,
            url TEXT,
            status TEXT DEFAULT '',
            created_at TEXT DEFAULT (datetime('now','localtime')),
            FOREIGN KEY(product_id) REFERENCES products(id)
        );
        -- 用户表
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL UNIQUE,
            password TEXT NOT NULL,
            role TEXT NOT NULL DEFAULT 'user',
            display_name TEXT DEFAULT '',
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            last_login TEXT,
            created_by INTEGER REFERENCES users(id),
            config TEXT DEFAULT '{}'
        );

        -- 爬取缓存表
        CREATE TABLE IF NOT EXISTS scrape_cache (
            package_name TEXT PRIMARY KEY,
            image_count INTEGER DEFAULT 0,
            saved_path TEXT,
            logo_path TEXT,
            last_scraped TEXT DEFAULT (datetime('now')),
            scraped_by INTEGER REFERENCES users(id)
        );

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
    """)

    # 产品表迁移：补 mcc_id 和兼容 is_paused→status
    cols = [r[1] for r in conn.execute("PRAGMA table_info(products)").fetchall()]
    if "mcc_id" not in cols:
        conn.execute("ALTER TABLE products ADD COLUMN mcc_id INTEGER REFERENCES mcc(id)")
    for t in ["products", "packages"]:
        tcols = [r[1] for r in conn.execute(f"PRAGMA table_info({t})").fetchall()]
        if "is_paused" in tcols and "status" not in tcols:
            conn.execute(f"ALTER TABLE {t} RENAME COLUMN is_paused TO status")

    # 迁移：videos 表补 review_status 列（2026-06-16 新增）
    vcols = [r[1] for r in conn.execute("PRAGMA table_info(videos)").fetchall()]
    if "review_status" not in vcols:
        conn.execute("ALTER TABLE videos ADD COLUMN review_status TEXT DEFAULT '能过审'")

    # 迁移：accounts 表补 death_date 列（2026-06-21 新增）
    acols = [r[1] for r in conn.execute("PRAGMA table_info(accounts)").fetchall()]
    if "death_date" not in acols:
        conn.execute("ALTER TABLE accounts ADD COLUMN death_date TEXT DEFAULT ''")

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

    # 迁移：copywritings 表补 owner_id/effectiveness（2026-06-27 文案私有化）
    cwcols = [r[1] for r in conn.execute("PRAGMA table_info(copywritings)").fetchall()]
    if "owner_id" not in cwcols:
        conn.execute("ALTER TABLE copywritings ADD COLUMN owner_id INTEGER REFERENCES users(id)")
        conn.execute("UPDATE copywritings SET owner_id = 1 WHERE owner_id IS NULL")
    if "effectiveness" not in cwcols:
        conn.execute("ALTER TABLE copywritings ADD COLUMN effectiveness TEXT DEFAULT ''")

    # 初始化默认标签
    for k, v in [("regions", '["巴西","菲律宾","孟加拉","印尼","东南亚通用","通用"]'),
                 ("frame_types", '["融帧","非融帧"]'),
                 ("effectiveness", '["","成效","一般"]'),
                 ("product_names", '["p222","93ok"]'),
                 ("review_statuses", '["能过审","不能过审"]')]:
        conn.execute("INSERT OR IGNORE INTO tags(key,value) VALUES(?,?)", (k, v))

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


def _migrate_if_needed(conn: sqlite3.Connection):
    """首次启动时从旧格式导入数据。"""
    root = os.path.dirname(os.path.dirname(_db_path()))

    # 1. 迁移 video_set/*.json → video_history
    migrated = conn.execute(
        "SELECT value FROM config WHERE key='migrated_video_history'"
    ).fetchone()
    if not migrated:
        _migrate_video_history(conn, root)
        conn.execute("INSERT OR REPLACE INTO config(key,value) VALUES('migrated_video_history','1')")

    # 2. 迁移 youtube.db → videos / tags
    migrated_yt = conn.execute(
        "SELECT value FROM config WHERE key='migrated_youtube'"
    ).fetchone()
    if not migrated_yt:
        _migrate_youtube_db(conn, root)
        conn.execute("INSERT OR REPLACE INTO config(key,value) VALUES('migrated_youtube','1')")

    # 3. 迁移 fonts/.recent.json → config
    migrated_font = conn.execute(
        "SELECT value FROM config WHERE key='migrated_font_recent'"
    ).fetchone()
    if not migrated_font:
        _migrate_font_recent(conn, root)
        conn.execute("INSERT OR REPLACE INTO config(key,value) VALUES('migrated_font_recent','1')")

    conn.commit()


def _migrate_video_history(conn: sqlite3.Connection, root: str):
    """从 temp/video_set/*.json 导入到 video_history 表。"""
    history_dir = os.path.join(root, "temp", "video_set")
    if not os.path.isdir(history_dir):
        return

    imported = 0
    for f in sorted(os.listdir(history_dir)):
        if not f.endswith(".json"):
            continue
        pkg = f[:-5]  # 去掉 .json
        fp = os.path.join(history_dir, f)
        try:
            with open(fp, "r", encoding="utf-8") as fh:
                entries = json.load(fh)
        except Exception:
            continue
        if not isinstance(entries, list):
            continue
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            conn.execute(
                "INSERT INTO video_history(package, name, settings, created_at) VALUES(?,?,?,?)",
                (pkg, entry.get("name", ""), json.dumps(entry, ensure_ascii=False),
                 entry.get("saved_at", datetime.datetime.now().strftime("%m-%d %H:%M")))
            )
            imported += 1

    if imported > 0:
        # 备份原文件
        backup_dir = os.path.join(root, "temp", "video_set.bak")
        if not os.path.isdir(backup_dir):
            os.rename(history_dir, backup_dir)


def _migrate_youtube_db(conn: sqlite3.Connection, root: str):
    """从 youtube.db 导入到 app.db 的 videos / tags 表。"""
    yt_db = os.path.join(root, "temp", "youtube.db")
    if not os.path.isfile(yt_db):
        # 检查旧 JSON 备份
        json_bak = os.path.join(root, "temp", "youtube_videos.json.backup")
        if os.path.isfile(json_bak):
            _migrate_youtube_json(conn, json_bak)
        return

    try:
        yt_conn = sqlite3.connect(yt_db)
        yt_conn.row_factory = sqlite3.Row

        # 迁移 videos
        rows = yt_conn.execute("SELECT * FROM videos").fetchall()
        for r in rows:
            d = dict(r)
            conn.execute(
                "INSERT OR IGNORE INTO videos(id,url,title,region,frame_type,effectiveness,product_name,review_status,imported_at) "
                "VALUES(?,?,?,?,?,?,?,?,?)",
                (d.get("id"), d.get("url"), d.get("title"),
                 d.get("region", "通用"), d.get("frame_type", "非融帧"),
                 d.get("effectiveness", ""), d.get("product_name", ""),
                 d.get("review_status", "能过审"), d.get("imported_at", ""))
            )

        # 迁移 tags
        tag_rows = yt_conn.execute("SELECT * FROM tags").fetchall()
        for r in tag_rows:
            d = dict(r)
            conn.execute("INSERT OR IGNORE INTO tags(key,value) VALUES(?,?)",
                         (d.get("key"), d.get("value")))

        # 迁移 mcc / accounts / products / packages（如果存在）
        conn.execute("PRAGMA foreign_keys=OFF")
        for table, cols in [
            ("mcc", ["id","name","mcc_id","level","parent_mcc_id","created_at","updated_at"]),
            ("accounts", ["id","name","account_id","mcc_id","timezone","agent","status","acquired_date","created_at","updated_at"]),
            ("products", ["id","product_name","kpi","region","status","mcc_id","created_at"]),
            ("packages", ["id","product_id","series_name","package_name","url","status","created_at"]),
        ]:
            try:
                old_rows = yt_conn.execute(f"SELECT * FROM {table}").fetchall()
            except Exception:
                continue
            placeholders = ",".join(["?"] * len(cols))
            col_str = ",".join(cols)
            for r in old_rows:
                d = dict(r)
                vals = [d.get(c) for c in cols]
                try:
                    conn.execute(f"INSERT OR IGNORE INTO {table}({col_str}) VALUES({placeholders})", vals)
                except Exception:
                    pass
        conn.execute("PRAGMA foreign_keys=ON")

        yt_conn.close()
        # 备份
        os.rename(yt_db, yt_db + ".bak")
    except Exception:
        pass


def _migrate_youtube_json(conn: sqlite3.Connection, json_path: str):
    """从 youtube_videos.json.backup 导入。"""
    try:
        with open(json_path, "r", encoding="utf-8") as f:
            videos = json.load(f)
    except Exception:
        return
    if not isinstance(videos, list):
        return
    for v in videos:
        if not isinstance(v, dict):
            continue
        conn.execute(
            "INSERT OR IGNORE INTO videos(id,url,title,region,frame_type,effectiveness,product_name,review_status,imported_at) "
            "VALUES(?,?,?,?,?,?,?,?,?)",
            (v.get("id"), v.get("url"), v.get("title"),
             v.get("region", "通用"), v.get("frame_type", "非融帧"),
             v.get("effectiveness", ""), v.get("product_name", ""),
             v.get("review_status", "能过审"), v.get("imported_at", ""))
        )


def _migrate_font_recent(conn: sqlite3.Connection, root: str):
    """从 fonts/.recent.json 导入到 config 表。"""
    recent_file = os.path.join(root, "fonts", ".recent.json")
    if not os.path.isfile(recent_file):
        return
    try:
        with open(recent_file, "r", encoding="utf-8") as f:
            recent = json.load(f)
    except Exception:
        return
    if isinstance(recent, list):
        conn.execute("INSERT OR REPLACE INTO config(key,value) VALUES('font_recent',?)",
                     (json.dumps(recent),))
        os.rename(recent_file, recent_file + ".bak")


# ============================================================
#  便捷操作函数 — 供 main.py 调用
# ============================================================

# ---- 视频历史 ----

def history_save(package: str, entry: dict) -> int:
    """保存一条历史记录，返回当前该包的总条数。"""
    db = get_db()
    db.execute(
        "INSERT INTO video_history(package, name, settings, updated_at) VALUES(?,?,?,datetime('now','localtime'))",
        (package, entry.get("name", ""), json.dumps(entry, ensure_ascii=False)))
    # 超过 30 条则清理最旧的
    db.execute("""
        DELETE FROM video_history WHERE id NOT IN (
            SELECT id FROM video_history WHERE package=? ORDER BY created_at DESC LIMIT 30
        ) AND package=?
    """, (package, package))
    db.commit()
    count = db.execute("SELECT COUNT(*) FROM video_history WHERE package=?", (package,)).fetchone()[0]
    db.close()
    return count


def history_list() -> dict:
    """按包名分组返回所有历史。"""
    db = get_db()
    rows = db.execute("SELECT * FROM video_history ORDER BY created_at DESC").fetchall()
    result = {}
    for r in rows:
        d = dict(r)
        pkg = d["package"]
        if pkg not in result:
            result[pkg] = []
        try:
            settings = json.loads(d["settings"])
        except Exception:
            settings = {}
        settings["_id"] = d["id"]
        settings["_saved_at"] = d["created_at"]
        result[pkg].append(settings)
    db.close()
    return result


def history_delete(package: str, entry_ids: list[int] | None = None):
    """删除指定包或指定条目。ids=None 则删除整个包。"""
    db = get_db()
    if entry_ids is None:
        db.execute("DELETE FROM video_history WHERE package=?", (package,))
    else:
        for eid in entry_ids:
            db.execute("DELETE FROM video_history WHERE id=? AND package=?", (eid, package))
    db.commit()
    db.close()


# ---- 视频任务 ----

def task_create(task_id: str, package: str = "", settings: dict | None = None) -> None:
    """记录新任务。"""
    db = get_db()
    db.execute(
        "INSERT INTO video_tasks(task_id, package, status, settings) VALUES(?,?,'pending',?)",
        (task_id, package, json.dumps(settings or {}, ensure_ascii=False)))
    db.commit()
    db.close()


def task_update(task_id: str, **kwargs):
    """更新任务字段（status, progress, message, output_path, finished_at）。"""
    db = get_db()
    allowed = {"status", "progress", "message", "output_path", "finished_at"}
    sets = {k: v for k, v in kwargs.items() if k in allowed}
    if sets:
        clauses = ", ".join(f"{k}=?" for k in sets)
        vals = list(sets.values()) + [task_id]
        db.execute(f"UPDATE video_tasks SET {clauses} WHERE task_id=?", vals)
        db.commit()
    db.close()


def task_get(task_id: str) -> dict | None:
    """获取单条任务记录。"""
    db = get_db()
    row = db.execute("SELECT * FROM video_tasks WHERE task_id=?", (task_id,)).fetchone()
    db.close()
    return dict(row) if row else None


# ---- 配置 ----

def config_get(key: str, default: str = "") -> str:
    """读取配置值。"""
    db = get_db()
    row = db.execute("SELECT value FROM config WHERE key=?", (key,)).fetchone()
    db.close()
    return row["value"] if row else default


def config_set(key: str, value: str):
    """写入配置。"""
    db = get_db()
    db.execute("INSERT OR REPLACE INTO config(key,value) VALUES(?,?)", (key, value))
    db.commit()
    db.close()


# ---- 字体最近使用 ----

def font_recent_list() -> list[str]:
    """返回最近使用的字体 ID 列表。"""
    raw = config_get("font_recent", "[]")
    try:
        return json.loads(raw)
    except Exception:
        return []


def font_mark_used(font_id: str):
    """标记字体为最近使用。"""
    recent = font_recent_list()
    if font_id in recent:
        recent.remove(font_id)
    recent.insert(0, font_id)
    recent = recent[:20]
    config_set("font_recent", json.dumps(recent))
