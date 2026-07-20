"""统一 SQLite 存储 — 替换散落的 JSON 文件。

数据库路径：{_DATA_ROOT}/temp/app.db
"""

import os
import sqlite3
import json
import datetime
import threading
from contextlib import contextmanager

_schema_lock = threading.Lock()
_schema_verified = False
_schema_verified_path = None


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
    """获取数据库连接，自动建表 + 迁移（仅首次检查 schema，同路径下缓存）。"""
    global _schema_verified, _schema_verified_path
    db_path = _db_path()
    os.makedirs(os.path.dirname(db_path), exist_ok=True)

    conn = sqlite3.connect(db_path, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA foreign_keys=ON")
    if not _schema_verified or _schema_verified_path != db_path:
        with _schema_lock:
            if not _schema_verified or _schema_verified_path != db_path:
                _ensure_schema(conn)
                _migrate_if_needed(conn)
                _schema_verified = True
                _schema_verified_path = db_path
    return conn


@contextmanager
def db_conn():
    """数据库连接上下文管理器，自动处理异常安全的关闭。

    用法:
        with db_conn() as db:
            row = db.execute("SELECT ...").fetchone()
    """
    db = get_db()
    try:
        yield db
    finally:
        db.close()


def _add_column_if_missing(conn: sqlite3.Connection, table: str, col_name: str, col_def: str):
    """仅在列不存在时添加。避免重复 PRAGMA table_info 样板代码。"""
    cols = [r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()]
    if col_name not in cols:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {col_def}")


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
            mcc_id TEXT NOT NULL,
            level TEXT DEFAULT '',
            parent_mcc_id INTEGER REFERENCES mcc(id),
            shared_user_ids TEXT DEFAULT '[]',
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

        -- 账户 MCC 变更历史
        CREATE TABLE IF NOT EXISTS account_mcc_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            account_id INTEGER NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
            old_mcc_id INTEGER,
            new_mcc_id INTEGER,
            changed_by INTEGER REFERENCES users(id),
            change_type TEXT NOT NULL DEFAULT 'manual',
            created_at TEXT DEFAULT (datetime('now','localtime'))
        );
        CREATE INDEX IF NOT EXISTS idx_acmh_account ON account_mcc_history(account_id);
        CREATE INDEX IF NOT EXISTS idx_acmh_changed_by ON account_mcc_history(changed_by);

        -- 文案管理
        CREATE TABLE IF NOT EXISTS copywritings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            region TEXT NOT NULL DEFAULT '通用',
            content TEXT NOT NULL,
            owner_id INTEGER REFERENCES users(id),
            effectiveness TEXT DEFAULT '',
            is_public INTEGER DEFAULT 0,
            created_at TEXT DEFAULT (datetime('now','localtime'))
        );
        CREATE INDEX IF NOT EXISTS idx_copywritings_region ON copywritings(region);

        -- 产品在跑人员关联表（替代 products.runner_ids JSON 列，支持索引查询）
        CREATE TABLE IF NOT EXISTS product_runners (
            product_id INTEGER NOT NULL REFERENCES products(id),
            user_id INTEGER NOT NULL REFERENCES users(id),
            PRIMARY KEY (product_id, user_id)
        );
        CREATE INDEX IF NOT EXISTS idx_product_runners_user ON product_runners(user_id);

        -- 产品与包管理
        CREATE TABLE IF NOT EXISTS products (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            product_name TEXT,
            kpi TEXT,
            region TEXT,
            status TEXT DEFAULT '',
            mcc_id INTEGER REFERENCES mcc(id),
            customer TEXT DEFAULT '',
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

        -- 产品成效素材关联
        CREATE TABLE IF NOT EXISTS product_assets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            product_id INTEGER NOT NULL REFERENCES products(id),
            video_id TEXT NOT NULL REFERENCES videos(id),
            added_by INTEGER REFERENCES users(id),
            added_at TEXT DEFAULT (datetime('now','localtime')),
            UNIQUE(product_id, video_id)
        );
        CREATE INDEX IF NOT EXISTS idx_product_assets_product ON product_assets(product_id);
        CREATE INDEX IF NOT EXISTS idx_product_assets_video ON product_assets(video_id);

        -- 视频消耗追踪（手动录入广告消耗）
        CREATE TABLE IF NOT EXISTS video_consumption (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            video_id TEXT NOT NULL REFERENCES videos(id),
            user_id INTEGER NOT NULL REFERENCES users(id),
            product_id INTEGER REFERENCES products(id),
            amount REAL NOT NULL DEFAULT 0,
            consume_date TEXT NOT NULL DEFAULT (date('now','localtime')),
            created_at TEXT DEFAULT (datetime('now','localtime'))
        );
        CREATE INDEX IF NOT EXISTS idx_vc_video ON video_consumption(video_id);
        CREATE INDEX IF NOT EXISTS idx_vc_user ON video_consumption(user_id);
        CREATE INDEX IF NOT EXISTS idx_vc_date ON video_consumption(consume_date);

        -- 做表数据保存（广告投放报告）
        CREATE TABLE IF NOT EXISTS ad_reports (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL REFERENCES users(id),
            product_name TEXT NOT NULL,
            region TEXT NOT NULL,
            report_date TEXT NOT NULL,
            account TEXT NOT NULL DEFAULT '',
            customer_id TEXT NOT NULL DEFAULT '',
            campaign TEXT NOT NULL DEFAULT '',
            cost REAL DEFAULT 0,
            impressions INTEGER DEFAULT 0,
            clicks INTEGER DEFAULT 0,
            installs REAL DEFAULT 0,
            in_app_actions REAL DEFAULT 0,
            cost_per_in_app REAL DEFAULT 0,
            saved_at TEXT DEFAULT (datetime('now','localtime'))
        );
        CREATE INDEX IF NOT EXISTS idx_ad_reports_user_product_date
            ON ad_reports(user_id, product_name, report_date);
        CREATE INDEX IF NOT EXISTS idx_ad_reports_dedup
            ON ad_reports(user_id, product_name, customer_id, campaign, report_date);
        CREATE INDEX IF NOT EXISTS idx_ad_reports_date ON ad_reports(report_date);

        -- 地区与时区管理
        CREATE TABLE IF NOT EXISTS regions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            timezone TEXT NOT NULL DEFAULT '',
            created_at TEXT DEFAULT (datetime('now','localtime'))
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
            config TEXT DEFAULT '{}',
            custom_name TEXT DEFAULT ''
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

        -- 掉包检测结果表
        CREATE TABLE IF NOT EXISTS delist_checks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            package_id INTEGER NOT NULL UNIQUE,
            product_id INTEGER NOT NULL,
            is_delisted INTEGER DEFAULT 0,
            checked_at TEXT,
            error_msg TEXT DEFAULT '',
            FOREIGN KEY(package_id) REFERENCES packages(id),
            FOREIGN KEY(product_id) REFERENCES products(id)
        );
        CREATE INDEX IF NOT EXISTS idx_delist_checks_product ON delist_checks(product_id);

        -- 掉包通知状态表（按用户跟踪通知/关闭/提醒状态）
        CREATE TABLE IF NOT EXISTS delist_notifications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            package_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            first_notified INTEGER DEFAULT 0,
            dismissed_at TEXT,
            reminder_count INTEGER DEFAULT 0,
            UNIQUE(package_id, user_id)
        );
        CREATE INDEX IF NOT EXISTS idx_delist_notif_user ON delist_notifications(user_id);

        -- 音频替换历史
        CREATE TABLE IF NOT EXISTS audio_replace_history (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            video_name  TEXT    NOT NULL,
            audio_name  TEXT    NOT NULL,
            output_name TEXT    NOT NULL,
            output_path TEXT    NOT NULL,
            size_mb     REAL    NOT NULL,
            created_at  TEXT    NOT NULL DEFAULT (datetime('now','localtime'))
        );

        -- 审计日志（产品删除等关键操作）
        CREATE TABLE IF NOT EXISTS audit_log (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id     INTEGER NOT NULL REFERENCES users(id),
            action      TEXT    NOT NULL,
            target_type TEXT    NOT NULL,
            target_id   INTEGER NOT NULL,
            target_name TEXT    DEFAULT '',
            detail      TEXT    DEFAULT '{}',
            created_at  TEXT    DEFAULT (datetime('now','localtime'))
        );
        CREATE INDEX IF NOT EXISTS idx_audit_log_action ON audit_log(action);
        CREATE INDEX IF NOT EXISTS idx_audit_log_created ON audit_log(created_at);
    """)

    # 产品表迁移：补 mcc_id 和兼容 is_paused→status
    cols = [r[1] for r in conn.execute("PRAGMA table_info(products)").fetchall()]
    if "mcc_id" not in cols:
        conn.execute("ALTER TABLE products ADD COLUMN mcc_id INTEGER REFERENCES mcc(id)")
    for t in ["products", "packages"]:
        tcols = [r[1] for r in conn.execute(f"PRAGMA table_info({t})").fetchall()]
        if "is_paused" in tcols and "status" not in tcols:
            conn.execute(f"ALTER TABLE {t} RENAME COLUMN is_paused TO status")

    # 增量迁移（使用公共函数缩减排板代码）
    _add_column_if_missing(conn, "videos", "review_status", "review_status TEXT DEFAULT '能过审'")
    _add_column_if_missing(conn, "accounts", "death_date", "death_date TEXT DEFAULT ''")
    _add_column_if_missing(conn, "videos", "owner_id", "owner_id INTEGER REFERENCES users(id)")
    _add_column_if_missing(conn, "videos", "is_public", "is_public INTEGER DEFAULT 0")
    _add_column_if_missing(conn, "accounts", "owner_id", "owner_id INTEGER REFERENCES users(id)")
    _add_column_if_missing(conn, "mcc", "owner_id", "owner_id INTEGER REFERENCES users(id)")
    _add_column_if_missing(conn, "mcc", "shared_user_ids", "shared_user_ids TEXT DEFAULT '[]'")

    # 增量迁移：产品/文案/用户 补列
    _add_column_if_missing(conn, "products", "owner_id", "owner_id INTEGER REFERENCES users(id)")
    _add_column_if_missing(conn, "products", "runner_ids", "runner_ids TEXT DEFAULT '[]'")
    _add_column_if_missing(conn, "products", "is_archived", "is_archived INTEGER DEFAULT 0")
    _add_column_if_missing(conn, "products", "customer", "customer TEXT DEFAULT ''")
    _add_column_if_missing(conn, "products", "deleted_at", "deleted_at TEXT DEFAULT ''")
    _add_column_if_missing(conn, "copywritings", "owner_id", "owner_id INTEGER REFERENCES users(id)")
    _add_column_if_missing(conn, "copywritings", "effectiveness", "effectiveness TEXT DEFAULT ''")
    _add_column_if_missing(conn, "copywritings", "is_public", "is_public INTEGER DEFAULT 0")
    _add_column_if_missing(conn, "users", "custom_name", "custom_name TEXT DEFAULT ''")
    _add_column_if_missing(conn, "users", "email", "email TEXT DEFAULT ''")
    _add_column_if_missing(conn, "users", "telegram_username", "telegram_username TEXT DEFAULT ''")

    # 初始化默认标签
    for k, v in [("regions", '["巴西","菲律宾","孟加拉","印尼","东南亚通用","通用"]'),
                 ("frame_types", '["融帧","非融帧"]'),
                 ("effectiveness", '["","成效","一般"]'),
                 ("product_names", '["p222","93ok"]'),
                 ("review_statuses", '["能过审","不能过审"]')]:
        conn.execute("INSERT OR IGNORE INTO tags(key,value) VALUES(?,?)", (k, v))

    # 迁移：ad_reports 表补 account 列
    ar_cols = [r[1] for r in conn.execute("PRAGMA table_info(ad_reports)").fetchall()]
    if ar_cols and "account" not in ar_cols:
        conn.execute("ALTER TABLE ad_reports ADD COLUMN account TEXT NOT NULL DEFAULT ''")

    # 迁移：更新 ad_reports 去重索引（加入 report_date）
    ar_migrated = conn.execute(
        "SELECT value FROM config WHERE key='migrated_ad_reports_dedup_v2'"
    ).fetchone()
    if not ar_migrated and ar_cols:
        conn.execute("DROP INDEX IF EXISTS idx_ad_reports_dedup")
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_ad_reports_dedup "
            "ON ad_reports(user_id, product_name, customer_id, campaign, report_date)"
        )
        conn.execute("INSERT OR REPLACE INTO config(key,value) VALUES('migrated_ad_reports_dedup_v2','1')")

    # 迁移：ad_reports 去重索引 v3 — 从 UNIQUE 降级为普通 INDEX（支持聚合 upsert）
    ar_migrated_v3 = conn.execute(
        "SELECT value FROM config WHERE key='migrated_ad_reports_dedup_v3'"
    ).fetchone()
    if not ar_migrated_v3:
        # 检查当前索引是否 UNIQUE
        idx_info = conn.execute(
            "SELECT sql FROM sqlite_master WHERE type='index' AND name='idx_ad_reports_dedup'"
        ).fetchone()
        if idx_info and 'UNIQUE' in (idx_info[0] or '').upper():
            conn.execute("DROP INDEX IF EXISTS idx_ad_reports_dedup")
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_ad_reports_dedup "
                "ON ad_reports(user_id, product_name, customer_id, campaign, report_date)"
            )
        conn.execute(
            "INSERT OR REPLACE INTO config(key,value) VALUES('migrated_ad_reports_dedup_v3','1')"
        )

    # 修复同步：确保 product_runners 关联表与 products.runner_ids JSON 列一致
    # 每次启动都执行，修复可能因 FK 约束静默失败等原因导致的数据不一致
    rows = conn.execute(
        "SELECT id, runner_ids FROM products WHERE runner_ids IS NOT NULL AND runner_ids != '' AND runner_ids != '[]'"
    ).fetchall()
    # 获取有效用户 ID（跳过不存在于 users 表的无效用户）
    valid_uids = set(r[0] for r in conn.execute("SELECT id FROM users").fetchall())
    for r in rows:
        try:
            runner_ids = json.loads(r["runner_ids"] or "[]")
        except Exception:
            runner_ids = []
        valid_rids = [uid for uid in runner_ids if uid in valid_uids]
        current = set(row[0] for row in conn.execute(
            "SELECT user_id FROM product_runners WHERE product_id=?", (r["id"],)
        ).fetchall())
        if set(valid_rids) != current:
            conn.execute("DELETE FROM product_runners WHERE product_id=?", (r["id"],))
            for uid in valid_rids:
                try:
                    conn.execute(
                        "INSERT OR IGNORE INTO product_runners(product_id, user_id) VALUES(?,?)",
                        (r["id"], uid)
                    )
                except Exception:
                    pass

    # 初始化地区时区（从 tags 同步已有地区，预设常见时区）
    _init_regions(conn)

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
    _migrate_mcc_dedup(conn)
    _migrate_mcc_share_runners(conn)


def _migrate_mcc_share_runners(conn: sqlite3.Connection):
    """回填已有产品的 runner 到 MCC 的 shared_user_ids（含上级链）。"""
    migrated = conn.execute(
        "SELECT value FROM config WHERE key='migrated_mcc_share_runners'"
    ).fetchone()
    if migrated:
        return

    products = conn.execute(
        "SELECT id, mcc_id, runner_ids FROM products WHERE mcc_id IS NOT NULL"
    ).fetchall()

    for prod in products:
        try:
            runners = json.loads(prod["runner_ids"] or "[]")
        except Exception:
            runners = []
        if not runners:
            continue

        mcc_id = prod["mcc_id"]
        visited = set()
        stack = [mcc_id]
        while stack:
            cur_id = stack.pop()
            if cur_id in visited:
                continue
            visited.add(cur_id)
            mcc = conn.execute(
                "SELECT id, owner_id, shared_user_ids, parent_mcc_id FROM mcc WHERE id=?",
                (cur_id,)
            ).fetchone()
            if not mcc:
                continue
            try:
                shared = json.loads(mcc["shared_user_ids"] or "[]")
            except Exception:
                shared = []
            modified = False
            for uid in runners:
                if uid != mcc["owner_id"] and uid not in shared:
                    shared.append(uid)
                    modified = True
            if modified:
                conn.execute(
                    "UPDATE mcc SET shared_user_ids=? WHERE id=?",
                    (json.dumps(shared), mcc["id"])
                )
            if mcc["parent_mcc_id"]:
                stack.append(mcc["parent_mcc_id"])

    conn.execute("INSERT OR REPLACE INTO config(key,value) VALUES('migrated_mcc_share_runners','1')")
    conn.commit()


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


# ---- 地区时区 ----

# 预设时区映射（初始化用，用户后续可自行编辑）
_DEFAULT_TIMEZONES = {
    "巴西": "UTC-3",
    "菲律宾": "UTC+8",
    "孟加拉": "UTC+6",
    "印尼": "UTC+7",
    "东南亚通用": "UTC+7",
    "通用": "UTC+8",
    "美国": "UTC-5",
    "印度": "UTC+5:30",
    "巴基斯坦": "UTC+5",
    "尼日利亚": "UTC+1",
    "墨西哥": "UTC-6",
    "日本": "UTC+9",
    "韩国": "UTC+9",
    "泰国": "UTC+7",
    "越南": "UTC+7",
    "土耳其": "UTC+3",
    "埃及": "UTC+2",
    "英国": "UTC+0",
    "德国": "UTC+1",
    "法国": "UTC+1",
    "西班牙": "UTC+1",
    "意大利": "UTC+1",
    "俄罗斯": "UTC+3",
    "澳大利亚": "UTC+10",
    "加拿大": "UTC-5",
    "阿根廷": "UTC-3",
    "哥伦比亚": "UTC-5",
    "秘鲁": "UTC-5",
    "智利": "UTC-4",
}


def _init_regions(conn: sqlite3.Connection):
    """初始化 regions 表：从 tags 同步已有地区，预设时区。"""
    existing = set(r[0] for r in conn.execute("SELECT name FROM regions").fetchall())
    if existing:
        return  # 已有数据，不覆盖

    # 从 tags 表读取已有地区列表
    tag_row = conn.execute("SELECT value FROM tags WHERE key='regions'").fetchone()
    if tag_row:
        try:
            region_list = json.loads(tag_row["value"])
        except Exception:
            region_list = []
    else:
        region_list = []

    for name in region_list:
        if not name or name in existing:
            continue
        tz = _DEFAULT_TIMEZONES.get(name, "")
        conn.execute(
            "INSERT OR IGNORE INTO regions(name, timezone) VALUES(?,?)", (name, tz)
        )
        existing.add(name)


def regions_list() -> list[dict]:
    """返回所有地区及其时区。"""
    db = get_db()
    rows = db.execute("SELECT * FROM regions ORDER BY name").fetchall()
    db.close()
    return [dict(r) for r in rows]


def regions_update(region_id: int, timezone: str):
    """更新地区时区。"""
    db = get_db()
    db.execute("UPDATE regions SET timezone=? WHERE id=?", (timezone, region_id))
    db.commit()
    db.close()


def regions_create(name: str, timezone: str = "") -> int:
    """新增地区，返回 id。"""
    db = get_db()
    db.execute("INSERT INTO regions(name, timezone) VALUES(?,?)", (name, timezone))
    db.commit()
    row = db.execute("SELECT id FROM regions WHERE name=?", (name,)).fetchone()
    db.close()
    return row["id"] if row else 0


def regions_delete(region_id: int):
    """删除地区。"""
    db = get_db()
    db.execute("DELETE FROM regions WHERE id=?", (region_id,))
    db.commit()
    db.close()


# ---- product_runners 关联表操作 ----

def set_product_runners(product_id: int, user_ids: list[int]):
    """原子替换产品的 runner 列表（先删后插）。"""
    db = get_db()
    db.execute("DELETE FROM product_runners WHERE product_id=?", (product_id,))
    for uid in user_ids:
        db.execute(
            "INSERT OR IGNORE INTO product_runners(product_id, user_id) VALUES(?,?)",
            (product_id, uid)
        )
    db.commit()
    db.close()


def add_product_runners(product_id: int, user_ids: list[int]):
    """追加 runner 到产品（不删除已有的）。"""
    db = get_db()
    for uid in user_ids:
        db.execute(
            "INSERT OR IGNORE INTO product_runners(product_id, user_id) VALUES(?,?)",
            (product_id, uid)
        )
    db.commit()
    db.close()


def get_runner_product_ids(user_id: int) -> list[int]:
    """获取某用户作为 runner 的所有产品 ID 列表（使用索引）。"""
    db = get_db()
    rows = db.execute(
        "SELECT product_id FROM product_runners WHERE user_id=?", (user_id,)
    ).fetchall()
    db.close()
    return [r["product_id"] for r in rows]
