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

    conn = sqlite3.connect(db_path, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA foreign_keys=ON")

    # 先建表，再补列，最后数据迁移（顺序依赖）
    if not _schema_verified or _schema_verified_path != db_path:
        with _schema_lock:
            if not _schema_verified or _schema_verified_path != db_path:
                _ensure_schema(conn)
                _schema_verified = True
                _schema_verified_path = db_path

    # 列级迁移每次连接都执行（_add_column_if_missing 在表存在时幂等）
    _ensure_columns(conn)
    # 数据迁移（首次连接时执行，依赖 _ensure_columns 补全的列）
    _migrate_if_needed(conn)
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
    """仅在列不存在时添加。如果表不存在则跳过。"""
    if not _table_exists(conn, table):
        return
    cols = [r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()]
    if col_name not in cols:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {col_def}")


def _table_exists(conn: sqlite3.Connection, table_name: str) -> bool:
    """检查表是否存在（用于迁移时的安全判断）。"""
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table_name,)
    ).fetchone()
    return row is not None


def _ensure_columns(conn: sqlite3.Connection):
    """每次数据库连接都执行的列级迁移（幂等，仅 PRAGMA + 条件 ALTER TABLE）。"""
    # 产品表迁移：补 mcc_id 和兼容 is_paused→status
    if _table_exists(conn, "products"):
        cols = [r[1] for r in conn.execute("PRAGMA table_info(products)").fetchall()]
        if "mcc_id" not in cols:
            conn.execute("ALTER TABLE products ADD COLUMN mcc_id INTEGER REFERENCES mcc(id)")
    for t in ["products", "packages"]:
        if not _table_exists(conn, t):
            continue
        tcols = [r[1] for r in conn.execute(f"PRAGMA table_info({t})").fetchall()]
        if "is_paused" in tcols and "status" not in tcols:
            conn.execute(f"ALTER TABLE {t} RENAME COLUMN is_paused TO status")

    # 增量迁移（使用公共函数缩减排板代码）
    _add_column_if_missing(conn, "videos", "review_status", "review_status TEXT DEFAULT '能过审'")
    _add_column_if_missing(conn, "videos", "channel_name", "channel_name TEXT DEFAULT ''")
    _add_column_if_missing(conn, "accounts", "death_date", "death_date TEXT DEFAULT ''")
    _add_column_if_missing(conn, "accounts", "status_changed_date", "status_changed_date TEXT DEFAULT ''")
    _add_column_if_missing(conn, "videos", "owner_id", "owner_id INTEGER REFERENCES users(id)")
    _add_column_if_missing(conn, "videos", "is_public", "is_public INTEGER DEFAULT 0")
    _add_column_if_missing(conn, "accounts", "owner_id", "owner_id INTEGER REFERENCES users(id)")
    _add_column_if_missing(conn, "mcc", "owner_id", "owner_id INTEGER REFERENCES users(id)")
    _add_column_if_missing(conn, "mcc", "shared_user_ids", "shared_user_ids TEXT DEFAULT '[]'")

    # 增量迁移：产品/文案/用户 补列
    _add_column_if_missing(conn, "products", "owner_id", "owner_id INTEGER REFERENCES users(id)")
    _add_column_if_missing(conn, "products", "runner_ids", "runner_ids TEXT DEFAULT '[]'")
    _add_column_if_missing(conn, "products", "is_archived", "is_archived INTEGER DEFAULT 0")
    _add_column_if_missing(conn, "recharge_records", "status", "status TEXT DEFAULT ''")
    _add_column_if_missing(conn, "recharge_records", "sheets_synced", "sheets_synced INTEGER DEFAULT 0")
    _add_column_if_missing(conn, "recharge_records", "sheets_error", "sheets_error TEXT DEFAULT ''")
    # 高频查询字段索引（_add_column_if_missing 之后创建，确保列已存在）
    if _table_exists(conn, "accounts"):
        conn.execute("CREATE INDEX IF NOT EXISTS idx_accounts_owner ON accounts(owner_id)")
    if _table_exists(conn, "products"):
        conn.execute("CREATE INDEX IF NOT EXISTS idx_products_owner ON products(owner_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_products_created ON products(created_at)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_products_archived ON products(is_archived)")
    # 回收原因改为全平台公用词表（2026-09-24）：name 全局唯一。
    # 防御：存量若有重名则跳过建索引——否则唯一索引创建失败会让每次连库都抛异常。
    if _table_exists(conn, "tt_recycle_reasons"):
        _dup = conn.execute(
            "SELECT name FROM tt_recycle_reasons GROUP BY name HAVING COUNT(*) > 1 LIMIT 1"
        ).fetchone()
        if _dup is None:
            conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_tt_recycle_reasons_name "
                         "ON tt_recycle_reasons(name)")
    _add_column_if_missing(conn, "products", "customer", "customer TEXT DEFAULT ''")
    _add_column_if_missing(conn, "products", "deleted_at", "deleted_at TEXT DEFAULT ''")
    _add_column_if_missing(conn, "products", "agency_ratio", "agency_ratio REAL DEFAULT NULL")
    _add_column_if_missing(conn, "copywritings", "owner_id", "owner_id INTEGER REFERENCES users(id)")
    _add_column_if_missing(conn, "copywritings", "effectiveness", "effectiveness TEXT DEFAULT ''")
    _add_column_if_missing(conn, "copywritings", "is_public", "is_public INTEGER DEFAULT 0")
    # videos 复合主键后，关联表需 video_owner_id 列
    _add_column_if_missing(conn, "product_assets", "video_owner_id", "video_owner_id INTEGER NOT NULL DEFAULT 1")
    _add_column_if_missing(conn, "video_consumption", "video_owner_id", "video_owner_id INTEGER NOT NULL DEFAULT 1")
    _add_column_if_missing(conn, "users", "custom_name", "custom_name TEXT DEFAULT ''")
    _add_column_if_missing(conn, "users", "email", "email TEXT DEFAULT ''")
    _add_column_if_missing(conn, "users", "telegram_username", "telegram_username TEXT DEFAULT ''")
    _add_column_if_missing(conn, "users", "platform", "platform TEXT DEFAULT 'gg'")
    # ⚠️ users.prev_scrape_dns（曾用爬取目录名，JSON 文本）已**废弃**：2026-09-24
    # code-review 第 5 轮把它升级成 scrape_dn_history 表（一行一个名字 + 自增序号），
    # 并**删除了这个列**（见 _migrate_scrape_dn_history）。此处**绝不能**再
    # _add_column_if_missing 补它：_ensure_columns 每次连库都跑，补回来 = 迁移刚
    # DROP 掉的列下一毫秒又出现，且新的写入方（auth.update_user）只写表不写列，
    # 该列会永远停在迁移那一刻的旧值上，成为一颗定时炸弹。
    # 爬取目录名唯一约束（2026-09-24，code-review 第 3 轮 H2）：
    # users 表此前只有 username 一个唯一索引，display_name 无任何约束，而爬取
    # 产物目录名 = `display_name or username`。于是 `/api/auth/register` 这种
    # 开放注册的 check-then-act 在并发下可以插出多个**同名目录**的用户 ——
    # 实测 8 线程并发 8/8 全部落库同名。应用层的 directory_name_error 是
    # 「读快照 → 判断 → INSERT」，天生非原子，原子性只能交给 DB。
    #
    # scrape_dn 是**生成列**（VIRTUAL，随行计算，不占存储）：
    #   解析规则必须与 auth._effective_dn / main._scrape_dn_for 一致，
    #   即 `COALESCE(NULLIF(TRIM(display_name),''), username)`，
    #   两者都空时退化成 `'user_' || id`（对应 _scrape_dn_for 的兜底）。
    #   一致性由 test_scrape_ownership.py 的**两条**测试钉住，缺一不可：
    #     · TestDbGeneratedColumnMatchesPython::test_same_key
    #       —— 直接比「DB 生成列 vs Python 解析」是否同键（钉 DB 这一腿）
    #     · TestEffectiveDnMatchesScrapeDnFor
    #       —— 钉 auth._effective_dn ≡ main._scrape_dn_for（Python 侧内部不自漂）
    #   ⚠️ 本注释此前只写了 TestEffectiveDnMatchesScrapeDnFor，而那个类当时**根本
    #   不存在**；补上之后，它又只覆盖了 Python 两个函数之间、**没碰 DB 生成列**
    #   —— 等于"钉住的"和"这里声称的"始终不是同一件事（code-review 第 3 轮指出）。
    #   现已补齐，且下一条测试是实打实比对 DB 生成列本身的。
    #
    # COLLATE NOCASE 补齐应用层 os.path.normcase 的大小写折叠（NTFS 不区分
    # 大小写，alice/ALICE 是同一个目录）。NOCASE 只折 ASCII，比 normcase 窄 ——
    # 在**大小写**这一维上应用层更严，方向 fail-closed，两者不一致时先被应用层拒掉。
    #
    # ⚠️ 该"更严"的论断**只覆盖大小写这一维，不覆盖 TRIM 顺序**：`_ensure` 之外
    # 还存在一处已知差异（由
    # TestDbGeneratedColumnMatchesPython::test_whitespace_only_display_name_is_a_known_divergence
    # 记录）：display_name 为**纯空白非空串**（如 "   "）时，Python 侧
    # `(display_name or username).strip()` 先判 falsy 再 strip ⇒ 得 `user_<id>`；
    # 而本生成列 `NULLIF(TRIM(display_name),'')` 先 TRIM 再判空 ⇒ 回退 username。
    # 两者**不同键**。方向仍是 fail-closed（攻击者取某人的 username 时应用层会
    # 放行、但本列会撞上索引 ⇒ IntegrityError ⇒ 拒绝），**只会误拒、不会漏越权**。
    # 当前不可触发：两条写路径都已 strip，真实库逐行核对亦无不一致。
    # 修法未做 —— 统一求值顺序会改变既有目录名语义（`"   "` 的目录会从
    # `user_<id>` 变成 username），有产物"搬家"风险，属改既有功能逻辑，需裁定。
    #
    # 防御：存量若有重名则**跳过**建索引 —— 否则唯一索引创建失败会让**每次连库**
    # 都抛异常，把整个应用打死（与上面 idx_tt_recycle_reasons_name 同一处理）。
    if _table_exists(conn, "users"):
        # ⚠️ 此处**不能**用 _add_column_if_missing：它查的是 PRAGMA table_info，
        # 而该 PRAGMA **不列出生成列**（生成列在 table_xinfo 里）—— 于是它每次都
        # 判定"列不存在"→ 重复 ALTER → `duplicate column name: scrape_dn`，
        # 而 _ensure_columns 每次连库都跑 ⇒ 整个应用当场打死（实测：全量套件
        # 从 717 passed 掉到 304 failed）。故这里用 table_xinfo 自行判存在性。
        _cols = [r[1] for r in conn.execute("PRAGMA table_xinfo(users)").fetchall()]
        if "scrape_dn" not in _cols:
            conn.execute(
                "ALTER TABLE users ADD COLUMN scrape_dn TEXT GENERATED ALWAYS AS ("
                "COALESCE(NULLIF(TRIM(display_name), ''), "
                "NULLIF(TRIM(username), ''), 'user_' || id)) VIRTUAL")
        # ⚠️ 重复检测与索引必须用**同一 collation**：生成列默认 BINARY，而索引是
        # NOCASE（折 ASCII 大小写）。若检测漏了大小写变体（如 `alice` / `Alice`），
        # BINARY 报"无重复"而建 NOCASE 索引当场抛 IntegrityError —— 该异常从
        # get_db() 冒出，而 get_db() 在 _before_request 里**每个请求都调**、
        # 启动预初始化也调 ⇒ 整个服务起不来 / 每个请求 500（实测已复现）。
        _dup = conn.execute(
            "SELECT COUNT(*) FROM (SELECT 1 FROM users GROUP BY scrape_dn COLLATE NOCASE "
            "HAVING COUNT(*) > 1)").fetchone()[0]
        if _dup:
            print(f"[Migrate] users 表有 {_dup} 组爬取目录名重复（含大小写变体），"
                  f"跳过 idx_users_scrape_dn 唯一索引：并发注册/改名的原子性保障缺失，"
                  f"仅剩应用层闸门。请先清理重名用户。")
        else:
            try:
                conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_users_scrape_dn "
                             "ON users(scrape_dn COLLATE NOCASE)")
            except sqlite3.IntegrityError as exc:
                # 兜底：即便上面检测与索引口径仍有差（或建索引期间有并发写入），
                # 也绝不让异常打死 get_db()。此处**不是 fail-open** —— 应用层
                # directory_name_error 闸门仍在，降级的只是并发原子性。
                print(f"[Migrate] idx_users_scrape_dn 创建失败（{exc}），仅剩应用层闸门")
    # 选项表外键列（从 TEXT 迁移到 ID 引用）
    _add_column_if_missing(conn, "accounts", "agent_id", "agent_id INTEGER REFERENCES agents(id)")
    _add_column_if_missing(conn, "accounts", "status_id", "status_id INTEGER REFERENCES account_statuses(id)")
    _add_column_if_missing(conn, "accounts", "deleted_at", "deleted_at TEXT DEFAULT NULL")
    _add_column_if_missing(conn, "recharge_records", "agent_id", "agent_id INTEGER REFERENCES agents(id)")
    _add_column_if_missing(conn, "mcc", "level_id", "level_id INTEGER REFERENCES mcc_levels(id)")
    _add_column_if_missing(conn, "products", "sales_person", "sales_person TEXT DEFAULT ''")
    _add_column_if_missing(conn, "products", "sales_person_id", "sales_person_id INTEGER REFERENCES sales_persons(id)")
    # 选项表加 platform 字段（GG/FB 隔离）
    _add_column_if_missing(conn, "sales_persons", "platform", "platform TEXT DEFAULT 'gg'")
    _add_column_if_missing(conn, "account_statuses", "platform", "platform TEXT DEFAULT 'gg'")
    _add_column_if_missing(conn, "regions", "platform", "platform TEXT DEFAULT 'gg'")
    _add_column_if_missing(conn, "agents", "platform", "platform TEXT DEFAULT 'gg'")


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
            id TEXT NOT NULL,
            owner_id INTEGER NOT NULL DEFAULT 1 REFERENCES users(id),
            url TEXT,
            title TEXT,
            region TEXT DEFAULT '通用',
            frame_type TEXT DEFAULT '非融帧',
            effectiveness TEXT DEFAULT '',
            product_name TEXT DEFAULT '',
            review_status TEXT DEFAULT '能过审',
            is_public INTEGER DEFAULT 0,
            imported_at TEXT,
            PRIMARY KEY (id, owner_id)
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
            owner_id INTEGER REFERENCES users(id),
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
            owner_id INTEGER REFERENCES users(id),
            created_at TEXT DEFAULT (datetime('now','localtime')),
            updated_at TEXT DEFAULT (datetime('now','localtime'))
        );
        CREATE INDEX IF NOT EXISTS idx_accounts_mcc ON accounts(mcc_id);

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

        -- 充值记录
        CREATE TABLE IF NOT EXISTS recharge_records (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            account_id TEXT NOT NULL,
            amount TEXT NOT NULL,
            agent TEXT DEFAULT '',
            operator TEXT DEFAULT '',
            status TEXT DEFAULT '',
            created_by INTEGER REFERENCES users(id),
            created_at TEXT DEFAULT (datetime('now','localtime'))
        );
        CREATE INDEX IF NOT EXISTS idx_recharge_account ON recharge_records(account_id);

        -- Sheets 同步失败日志（做表数据，用于异步重试 & 前端展示）
        CREATE TABLE IF NOT EXISTS sheets_sync_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            product_name TEXT NOT NULL DEFAULT '',
            spreadsheet_id TEXT NOT NULL DEFAULT '',
            sheet_gid TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'failed',
            error_msg TEXT DEFAULT '',
            rows_json TEXT DEFAULT '',
            retry_count INTEGER DEFAULT 0,
            created_at TEXT DEFAULT (datetime('now','localtime')),
            updated_at TEXT DEFAULT (datetime('now','localtime'))
        );
        CREATE INDEX IF NOT EXISTS idx_ssl_user_product ON sheets_sync_log(user_id, product_name);

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
        CREATE INDEX IF NOT EXISTS idx_products_name ON products(product_name);
        CREATE INDEX IF NOT EXISTS idx_products_region ON products(region);
        CREATE INDEX IF NOT EXISTS idx_products_mcc ON products(mcc_id);
        CREATE INDEX IF NOT EXISTS idx_products_created ON products(created_at);

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
        CREATE INDEX IF NOT EXISTS idx_packages_product ON packages(product_id);

        -- 产品成效素材关联
        CREATE TABLE IF NOT EXISTS product_assets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            product_id INTEGER NOT NULL REFERENCES products(id),
            video_id TEXT NOT NULL,
            video_owner_id INTEGER NOT NULL DEFAULT 1,
            added_by INTEGER REFERENCES users(id),
            added_at TEXT DEFAULT (datetime('now','localtime')),
            UNIQUE(product_id, video_id),
            FOREIGN KEY (video_id, video_owner_id) REFERENCES videos(id, owner_id)
        );
        CREATE INDEX IF NOT EXISTS idx_product_assets_product ON product_assets(product_id);
        CREATE INDEX IF NOT EXISTS idx_product_assets_video ON product_assets(video_id);

        -- 视频消耗追踪（手动录入广告消耗）
        CREATE TABLE IF NOT EXISTS video_consumption (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            video_id TEXT NOT NULL,
            video_owner_id INTEGER NOT NULL DEFAULT 1,
            user_id INTEGER NOT NULL REFERENCES users(id),
            product_id INTEGER REFERENCES products(id),
            amount REAL NOT NULL DEFAULT 0,
            consume_date TEXT NOT NULL DEFAULT (date('now','localtime')),
            created_at TEXT DEFAULT (datetime('now','localtime')),
            FOREIGN KEY (video_id, video_owner_id) REFERENCES videos(id, owner_id)
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
            name TEXT NOT NULL,
            timezone TEXT NOT NULL DEFAULT '',
            platform TEXT DEFAULT 'gg',
            created_at TEXT DEFAULT (datetime('now','localtime')),
            UNIQUE(name, platform)
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
            custom_name TEXT DEFAULT '',
            platform TEXT DEFAULT 'gg'
        );

        -- 爬取目录名历史 + 墓碑（2026-09-24，code-review 第 5 轮 Important #1/#2）
        -- 取代原先的 users.prev_scrape_dns（JSON 文本，已被本表取代后 DROP）。
        -- 一行一个名字，id 即**跨用户单调序号** ⇒ 认领判据用 last-writer-wins；
        -- 名字存在行里 ⇒ 逗号/换行只是普通字符，整类「分隔符串味」缺陷不再存在。
        -- ⚠️ 刻意**无外键**（故删用户时不会级联消失）：它是**墓碑表**，删用户时写入
        -- 的行必须活过用户删除，否则「被删用户的爬取目录」会重新变成无主目录、
        -- 被曾用名持有者认领读到（Important #2）。admin_delete_user 刻意不清理本表。
        -- 读写见 auth._dn_released_keys（认领）与 auth.update_user（改名时落库）。
        CREATE TABLE IF NOT EXISTS scrape_dn_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            dn TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
        CREATE INDEX IF NOT EXISTS idx_scrape_dn_history_dn ON scrape_dn_history(dn);
        CREATE INDEX IF NOT EXISTS idx_scrape_dn_history_user ON scrape_dn_history(user_id);

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

    # 选项表（设置面板下拉选项独立管理，支持外键关联和重命名自动生效）
    conn.execute("""
        CREATE TABLE IF NOT EXISTS agents (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            owner_id INTEGER REFERENCES users(id),
            created_at TEXT DEFAULT (datetime('now','localtime')),
            platform TEXT DEFAULT 'gg',
            UNIQUE(name, owner_id, platform)
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

    # ==================== FB 平台表 ====================
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS fb_bms (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            bm_id TEXT NOT NULL UNIQUE,
            note TEXT DEFAULT '',
            status TEXT DEFAULT 'normal',
            owner_id INTEGER REFERENCES users(id),
            deleted_at TEXT DEFAULT NULL,
            created_at TEXT DEFAULT (datetime('now','localtime')),
            updated_at TEXT DEFAULT (datetime('now','localtime'))
        );
        CREATE INDEX IF NOT EXISTS idx_fb_bms_owner ON fb_bms(owner_id);
        CREATE INDEX IF NOT EXISTS idx_fb_bms_status ON fb_bms(status);
        CREATE INDEX IF NOT EXISTS idx_fb_bms_list ON fb_bms(owner_id, status, deleted_at);

        CREATE TABLE IF NOT EXISTS fb_accounts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            account_id TEXT NOT NULL UNIQUE,
            timezone TEXT DEFAULT '',
            status_id INTEGER REFERENCES account_statuses(id),
            acquired_date TEXT DEFAULT (date('now','localtime')),
            status_changed_date TEXT DEFAULT '',
            owner_id INTEGER REFERENCES users(id),
            deleted_at TEXT DEFAULT NULL,
            created_at TEXT DEFAULT (datetime('now','localtime')),
            updated_at TEXT DEFAULT (datetime('now','localtime'))
        );
        CREATE INDEX IF NOT EXISTS idx_fb_accounts_owner ON fb_accounts(owner_id);
        CREATE INDEX IF NOT EXISTS idx_fb_accounts_list ON fb_accounts(owner_id, status_id, deleted_at);

        CREATE TABLE IF NOT EXISTS fb_account_bm (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            account_id INTEGER NOT NULL REFERENCES fb_accounts(id) ON DELETE CASCADE,
            bm_id INTEGER NOT NULL REFERENCES fb_bms(id) ON DELETE CASCADE,
            created_at TEXT DEFAULT (datetime('now','localtime')),
            UNIQUE(account_id, bm_id)
        );
        CREATE INDEX IF NOT EXISTS idx_fb_account_bm_bm ON fb_account_bm(bm_id);

        CREATE TABLE IF NOT EXISTS fb_account_bm_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            account_id INTEGER NOT NULL REFERENCES fb_accounts(id),
            old_bm_id INTEGER REFERENCES fb_bms(id),
            new_bm_id INTEGER REFERENCES fb_bms(id),
            changed_by INTEGER REFERENCES users(id),
            change_type TEXT NOT NULL DEFAULT 'manual',
            created_at TEXT DEFAULT (datetime('now','localtime'))
        );

        CREATE TABLE IF NOT EXISTS fb_products (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            product_name TEXT NOT NULL,
            kpi TEXT DEFAULT '',
            region TEXT DEFAULT '',
            status TEXT DEFAULT 'active',
            sales_person_id INTEGER REFERENCES sales_persons(id),
            agency_ratio REAL DEFAULT 0,
            owner_id INTEGER REFERENCES users(id),
            is_archived INTEGER DEFAULT 0,
            created_at TEXT DEFAULT (datetime('now','localtime')),
            updated_at TEXT DEFAULT (datetime('now','localtime'))
        );
        CREATE INDEX IF NOT EXISTS idx_fb_products_owner ON fb_products(owner_id);

        CREATE TABLE IF NOT EXISTS fb_product_runners (
            product_id INTEGER NOT NULL REFERENCES fb_products(id) ON DELETE CASCADE,
            user_id INTEGER NOT NULL REFERENCES users(id),
            PRIMARY KEY (product_id, user_id)
        );
        CREATE INDEX IF NOT EXISTS idx_fb_product_runners_user ON fb_product_runners(user_id);

        CREATE TABLE IF NOT EXISTS fb_product_bms (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            product_id INTEGER NOT NULL REFERENCES fb_products(id) ON DELETE CASCADE,
            bm_id INTEGER NOT NULL REFERENCES fb_bms(id) ON DELETE CASCADE,
            UNIQUE(product_id, bm_id)
        );
        CREATE INDEX IF NOT EXISTS idx_fb_product_bms_bm ON fb_product_bms(bm_id);

        CREATE TABLE IF NOT EXISTS fb_pixel_bms (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            bm_id TEXT NOT NULL UNIQUE,
            note TEXT DEFAULT '',
            status TEXT DEFAULT 'normal',
            owner_id INTEGER REFERENCES users(id),
            deleted_at TEXT DEFAULT NULL,
            created_at TEXT DEFAULT (datetime('now','localtime')),
            updated_at TEXT DEFAULT (datetime('now','localtime'))
        );
        CREATE INDEX IF NOT EXISTS idx_fb_pixel_bms_owner ON fb_pixel_bms(owner_id);
        CREATE INDEX IF NOT EXISTS idx_fb_pixel_bms_list ON fb_pixel_bms(owner_id, status, deleted_at);

        CREATE TABLE IF NOT EXISTS fb_pixels (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            pixel_bm_id INTEGER NOT NULL REFERENCES fb_pixel_bms(id) ON DELETE CASCADE,
            pixel_name TEXT NOT NULL,
            pixel_id TEXT NOT NULL UNIQUE,
            created_at TEXT DEFAULT (datetime('now','localtime'))
        );
        CREATE INDEX IF NOT EXISTS idx_fb_pixels_bm ON fb_pixels(pixel_bm_id);

        CREATE TABLE IF NOT EXISTS fb_lines (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            product_id INTEGER NOT NULL REFERENCES fb_products(id) ON DELETE CASCADE,
            line_name TEXT NOT NULL,
            link TEXT DEFAULT '',
            pixel_id INTEGER REFERENCES fb_pixels(id) ON DELETE SET NULL,
            created_at TEXT DEFAULT (datetime('now','localtime')),
            UNIQUE(product_id, line_name)
        );
        CREATE INDEX IF NOT EXISTS idx_fb_lines_product ON fb_lines(product_id);
        CREATE INDEX IF NOT EXISTS idx_fb_lines_pixel ON fb_lines(pixel_id);

        CREATE TABLE IF NOT EXISTS fb_ad_reports (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL REFERENCES users(id),
            product_name TEXT NOT NULL,
            line_name TEXT DEFAULT '',
            report_date TEXT NOT NULL,
            account_name TEXT DEFAULT '',
            account_id TEXT DEFAULT '',
            cost REAL DEFAULT 0,
            impressions INTEGER DEFAULT 0,
            clicks INTEGER DEFAULT 0,
            registrations INTEGER DEFAULT 0,
            purchases INTEGER DEFAULT 0,
            cost_per_purchase REAL DEFAULT 0,
            updated_at TEXT DEFAULT NULL,
            saved_at TEXT DEFAULT (datetime('now','localtime'))
        );
        CREATE UNIQUE INDEX IF NOT EXISTS idx_fb_ad_reports_upsert
            ON fb_ad_reports(user_id, product_name, line_name, account_id, report_date);
        CREATE INDEX IF NOT EXISTS idx_fb_ad_reports_user_date
            ON fb_ad_reports(user_id, report_date);
        CREATE INDEX IF NOT EXISTS idx_fb_ad_reports_product_date
            ON fb_ad_reports(product_name, report_date);
    """)

    # ==================== TT 平台表 ====================
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS tt_bcs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            bc_id TEXT NOT NULL UNIQUE,
            note TEXT DEFAULT '',
            status TEXT DEFAULT 'normal',
            owner_id INTEGER REFERENCES users(id),
            deleted_at TEXT DEFAULT NULL,
            created_at TEXT DEFAULT (datetime('now','localtime')),
            updated_at TEXT DEFAULT (datetime('now','localtime'))
        );
        CREATE INDEX IF NOT EXISTS idx_tt_bcs_owner ON tt_bcs(owner_id);
        CREATE INDEX IF NOT EXISTS idx_tt_bcs_status ON tt_bcs(status);

        CREATE TABLE IF NOT EXISTS tt_products (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            product_name TEXT NOT NULL,
            kpi TEXT DEFAULT '',
            region TEXT DEFAULT '',
            status TEXT DEFAULT 'active',
            bc_id INTEGER REFERENCES tt_bcs(id),
            sales_person_id INTEGER REFERENCES sales_persons(id),
            agency_ratio REAL DEFAULT 0,
            customer TEXT DEFAULT '',
            owner_id INTEGER REFERENCES users(id),
            is_archived INTEGER DEFAULT 0,
            created_at TEXT DEFAULT (datetime('now','localtime')),
            updated_at TEXT DEFAULT (datetime('now','localtime'))
        );
        CREATE INDEX IF NOT EXISTS idx_tt_products_owner ON tt_products(owner_id);
        CREATE INDEX IF NOT EXISTS idx_tt_products_region ON tt_products(region);
        CREATE INDEX IF NOT EXISTS idx_tt_products_bc ON tt_products(bc_id);

        CREATE TABLE IF NOT EXISTS tt_product_runners (
            product_id INTEGER NOT NULL REFERENCES tt_products(id) ON DELETE CASCADE,
            user_id INTEGER NOT NULL REFERENCES users(id),
            PRIMARY KEY (product_id, user_id)
        );
        CREATE INDEX IF NOT EXISTS idx_tt_product_runners_user ON tt_product_runners(user_id);

        CREATE TABLE IF NOT EXISTS tt_packages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            product_id INTEGER NOT NULL REFERENCES tt_products(id) ON DELETE CASCADE,
            type TEXT DEFAULT 'package',
            series_name TEXT DEFAULT '',
            package_name TEXT DEFAULT '',
            url TEXT DEFAULT '',
            status TEXT DEFAULT '',
            created_at TEXT DEFAULT (datetime('now','localtime')),
            updated_at TEXT DEFAULT (datetime('now','localtime'))
        );
        CREATE INDEX IF NOT EXISTS idx_tt_packages_product ON tt_packages(product_id);
        CREATE INDEX IF NOT EXISTS idx_tt_packages_type ON tt_packages(type);

        CREATE TABLE IF NOT EXISTS tt_delist_checks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            package_id INTEGER NOT NULL REFERENCES tt_packages(id) ON DELETE CASCADE,
            is_delisted INTEGER DEFAULT 0,
            checked_at TEXT DEFAULT (datetime('now','localtime')),
            UNIQUE(package_id)
        );
        CREATE INDEX IF NOT EXISTS idx_tt_delist_checks_package ON tt_delist_checks(package_id);

        -- 掉包通知状态表（TT 平台，按用户跟踪通知/关闭/提醒状态）
        CREATE TABLE IF NOT EXISTS tt_delist_notifications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            package_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            first_notified INTEGER DEFAULT 0,
            dismissed_at TEXT,
            reminder_count INTEGER DEFAULT 0,
            UNIQUE(package_id, user_id)
        );
        CREATE INDEX IF NOT EXISTS idx_tt_delist_notif_user ON tt_delist_notifications(user_id);

        CREATE TABLE IF NOT EXISTS tt_product_assets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            product_id INTEGER NOT NULL REFERENCES tt_products(id),
            video_id TEXT NOT NULL,
            video_owner_id INTEGER NOT NULL DEFAULT 1,
            added_by INTEGER REFERENCES users(id),
            added_at TEXT DEFAULT (datetime('now','localtime')),
            UNIQUE(product_id, video_id)
        );
        CREATE INDEX IF NOT EXISTS idx_tt_product_assets_product ON tt_product_assets(product_id);
        CREATE INDEX IF NOT EXISTS idx_tt_product_assets_video ON tt_product_assets(video_id);

        -- ==================== TT 广告账户表 ====================
        CREATE TABLE IF NOT EXISTS tt_accounts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT DEFAULT '',
            advertiser_id TEXT NOT NULL UNIQUE,
            bc_id INTEGER REFERENCES tt_bcs(id),
            country TEXT DEFAULT '',
            agent_id INTEGER REFERENCES agents(id),
            timezone TEXT DEFAULT '',
            consumption TEXT DEFAULT '',
            status_id INTEGER REFERENCES account_statuses(id),
            acquired_date TEXT DEFAULT (date('now','localtime')),
            death_date TEXT DEFAULT '',
            status_changed_date TEXT DEFAULT '',
            remark TEXT DEFAULT '',
            owner_id INTEGER REFERENCES users(id),
            deleted_at TEXT DEFAULT NULL,
            created_at TEXT DEFAULT (datetime('now','localtime')),
            updated_at TEXT DEFAULT (datetime('now','localtime'))
        );
        CREATE INDEX IF NOT EXISTS idx_tt_accounts_owner ON tt_accounts(owner_id);
        CREATE INDEX IF NOT EXISTS idx_tt_accounts_bc ON tt_accounts(bc_id);
        CREATE INDEX IF NOT EXISTS idx_tt_accounts_list ON tt_accounts(owner_id, status_id, deleted_at);

        CREATE TABLE IF NOT EXISTS tt_account_bc_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            account_id INTEGER NOT NULL REFERENCES tt_accounts(id) ON DELETE CASCADE,
            old_bc_id INTEGER,
            new_bc_id INTEGER,
            changed_by INTEGER REFERENCES users(id),
            change_type TEXT NOT NULL DEFAULT 'manual',
            created_at TEXT DEFAULT (datetime('now','localtime'))
        );
        CREATE INDEX IF NOT EXISTS idx_tt_acbh_account ON tt_account_bc_history(account_id);

        CREATE TABLE IF NOT EXISTS tt_recharge_records (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            account_id TEXT NOT NULL,
            amount TEXT NOT NULL,
            agent_id INTEGER REFERENCES agents(id),
            operator TEXT DEFAULT '',
            status TEXT DEFAULT '',
            created_by INTEGER REFERENCES users(id),
            sheets_synced INTEGER DEFAULT 0,
            sheets_error TEXT DEFAULT '',
            created_at TEXT DEFAULT (datetime('now','localtime'))
        );
        CREATE INDEX IF NOT EXISTS idx_tt_recharge_account ON tt_recharge_records(account_id);

        CREATE TABLE IF NOT EXISTS tt_recycle_reasons (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            owner_id INTEGER REFERENCES users(id),
            created_at TEXT DEFAULT (datetime('now','localtime')),
            UNIQUE(name, owner_id)
        );
    """)

    # 列迁移已移至 _ensure_columns()（每次连接都执行）

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
    # 仅在首次执行（门控），后续 runner 变更由 updateRunners 等接口实时同步
    pr_migrated_v2 = conn.execute(
        "SELECT value FROM config WHERE key='migrated_product_runners_v2'"
    ).fetchone()
    if not pr_migrated_v2:
        # 检查 runner_ids 列是否已存在（_ensure_columns 之后才添加）
        cols = [r[1] for r in conn.execute("PRAGMA table_info(products)").fetchall()]
        if "runner_ids" in cols:
            rows = conn.execute(
                "SELECT id, runner_ids FROM products WHERE runner_ids IS NOT NULL AND runner_ids != '' AND runner_ids != '[]'"
            ).fetchall()
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
            conn.execute(
                "INSERT OR REPLACE INTO config(key,value) VALUES('migrated_product_runners_v2','1')"
        )

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

    # 检查 runner_ids 和 mcc_id 列是否存在
    cols = [r[1] for r in conn.execute("PRAGMA table_info(products)").fetchall()]
    if "runner_ids" not in cols or "mcc_id" not in cols:
        conn.execute(
            "INSERT OR REPLACE INTO config(key,value) VALUES('migrated_mcc_share_runners','1')"
        )
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


def _migrate_options_tables(conn: sqlite3.Connection):
    """将旧 TEXT 列中的选项值迁移到新选项表，并填充外键列。"""
    # 若旧 agent 列已被清理（_cleanup_old_option_columns 已 DROP），说明迁移已完成，跳过
    acct_cols = [r[1] for r in conn.execute("PRAGMA table_info(accounts)").fetchall()]
    if "agent" not in acct_cols:
        return
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

    # === 回退：recharge_records 孤儿记录（account_id 无匹配账户）===
    # 先插入缺失的 agent（用 owner_id=1 兜底）
    conn.execute("""
        INSERT OR IGNORE INTO agents(name, owner_id)
        SELECT DISTINCT r.agent, 1
        FROM recharge_records r
        WHERE r.agent IS NOT NULL AND r.agent != ''
          AND r.agent_id IS NULL
    """)
    # 对仍未填充的记录，仅按名称匹配（不再要求 JOIN accounts）
    conn.execute("""
        UPDATE recharge_records SET agent_id = (
            SELECT agents.id FROM agents
            WHERE agents.name = recharge_records.agent
            ORDER BY agents.owner_id ASC LIMIT 1
        ) WHERE recharge_records.agent IS NOT NULL AND recharge_records.agent != ''
          AND recharge_records.agent_id IS NULL
    """)

    # === 回退：products 的 owner_id 为 NULL 时按 IS NULL 匹配 ===
    conn.execute("""
        UPDATE products SET sales_person_id = (
            SELECT sales_persons.id FROM sales_persons
            WHERE sales_persons.name = products.sales_person
              AND sales_persons.owner_id IS NULL
        ) WHERE products.sales_person IS NOT NULL AND products.sales_person != ''
          AND products.owner_id IS NULL
          AND products.sales_person_id IS NULL
    """)

    conn.commit()


def _cleanup_old_option_columns(conn: sqlite3.Connection):
    """在所有代码切换到外键列之后，删除旧 TEXT 列和 tags 中的旧配置（仅执行一次）。"""
    migrated = conn.execute(
        "SELECT value FROM config WHERE key='migrated_cleanup_old_option_columns'"
    ).fetchone()
    if migrated:
        return

    conn.execute("PRAGMA foreign_keys=OFF")

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

    for key in ["account_agents", "account_statuses", "mcc_levels", "sales_persons"]:
        conn.execute("DELETE FROM tags WHERE key=?", (key,))

    conn.execute(
        "INSERT OR REPLACE INTO config(key,value) VALUES('migrated_cleanup_old_option_columns','1')"
    )
    conn.commit()


def _copy_gg_options_to_fb(conn: sqlite3.Connection):
    """一次性迁移：将 GG 平台的选项数据复制一份到 FB 平台。"""
    migrated = conn.execute(
        "SELECT value FROM config WHERE key='migrated_copy_options_to_fb'"
    ).fetchone()
    if migrated:
        return

    conn.execute("PRAGMA foreign_keys=OFF")

    # 重建三张选项表：UNIQUE 加入 platform（保留数据 + id）
    for tbl, cols_def, cols_sel in [
        ("regions", "id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, timezone TEXT DEFAULT '', platform TEXT DEFAULT 'gg', UNIQUE(name, platform)",
         "id, name, timezone, platform"),
        ("sales_persons", "id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, owner_id INTEGER REFERENCES users(id), platform TEXT DEFAULT 'gg', created_at TEXT DEFAULT (datetime('now','localtime')), UNIQUE(name, platform)",
         "id, name, owner_id, platform, created_at"),
        ("account_statuses", "id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, owner_id INTEGER REFERENCES users(id), platform TEXT DEFAULT 'gg', created_at TEXT DEFAULT (datetime('now','localtime')), UNIQUE(name, platform)",
         "id, name, owner_id, platform, created_at"),
    ]:
        conn.execute(f"DROP TABLE IF EXISTS {tbl}_new")
        conn.execute(f"CREATE TABLE {tbl}_new ({cols_def})")
        conn.execute(f"INSERT OR IGNORE INTO {tbl}_new({cols_sel}) SELECT {cols_sel} FROM {tbl}")
        conn.execute(f"DROP TABLE {tbl}")
        conn.execute(f"ALTER TABLE {tbl}_new RENAME TO {tbl}")

    conn.execute("PRAGMA foreign_keys=OFF")

    # 复制地区
    for r in conn.execute("SELECT name, timezone FROM regions WHERE platform='gg'").fetchall():
        conn.execute(
            "INSERT OR IGNORE INTO regions(name, timezone, platform) VALUES(?,?,'fb')",
            (r["name"], r["timezone"]))

    # 复制商务
    for s in conn.execute("SELECT DISTINCT name FROM sales_persons WHERE platform='gg'").fetchall():
        conn.execute(
            "INSERT OR IGNORE INTO sales_persons(name, owner_id, platform) VALUES(?,1,'fb')",
            (s["name"],))

    # 复制状态
    for s in conn.execute("SELECT DISTINCT name FROM account_statuses WHERE platform='gg'").fetchall():
        conn.execute(
            "INSERT OR IGNORE INTO account_statuses(name, owner_id, platform) VALUES(?,1,'fb')",
            (s["name"],))

    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("INSERT OR REPLACE INTO config(key,value) VALUES('migrated_copy_options_to_fb','1')")
    conn.commit()


def _copy_gg_options_to_tt(conn: sqlite3.Connection):
    """一次性迁移：将 GG 平台的选项数据复制一份到 TT 平台。

    注意：选项表（regions/sales_persons/account_statuses）已含 platform 列，
    无需重建表，只需插入 platform='tt' 数据即可。
    """
    migrated = conn.execute(
        "SELECT value FROM config WHERE key='migrated_copy_options_to_tt'"
    ).fetchone()
    if migrated:
        return

    # 复制地区
    for r in conn.execute("SELECT name, timezone FROM regions WHERE platform='gg'").fetchall():
        conn.execute(
            "INSERT OR IGNORE INTO regions(name, timezone, platform) VALUES(?,?,'tt')",
            (r["name"], r["timezone"]))

    # 复制商务
    for s in conn.execute("SELECT DISTINCT name FROM sales_persons WHERE platform='gg'").fetchall():
        conn.execute(
            "INSERT OR IGNORE INTO sales_persons(name, owner_id, platform) VALUES(?,1,'tt')",
            (s["name"],))

    # 复制状态
    for s in conn.execute("SELECT DISTINCT name FROM account_statuses WHERE platform='gg'").fetchall():
        conn.execute(
            "INSERT OR IGNORE INTO account_statuses(name, owner_id, platform) VALUES(?,1,'tt')",
            (s["name"],))

    conn.execute("INSERT OR REPLACE INTO config(key,value) VALUES('migrated_copy_options_to_tt','1')")
    conn.commit()


def _rebuild_agents_platform_unique(conn: sqlite3.Connection):
    """一次性迁移：将 agents 唯一约束重建为 UNIQUE(name, owner_id, platform)。

    原 UNIQUE(name, owner_id) 无法让 GG/TT 同名同 owner 的代理共存，导致
    _copy_gg_agents_to_tt 用 INSERT OR IGNORE 复制时被静默跳过（只复制出少数代理）。
    重建为 (name, owner_id, platform) 后，platform 参与唯一性，GG/TT 隔离。
    保留全部现有行与 id；同时重置复制标记，让 _copy_gg_agents_to_tt 重跑补全。
    """
    migrated = conn.execute(
        "SELECT value FROM config WHERE key='migrated_rebuild_agents_unique'"
    ).fetchone()
    if migrated:
        return
    # PRAGMA foreign_keys 无法在事务中切换：_ensure_columns 补列（ALTER TABLE）后会留下
    # 隐式事务，此时直接 OFF 会被静默忽略，导致下方 DROP TABLE agents 因被
    # accounts/recharge_records/tt_accounts 等外键引用而报 FOREIGN KEY constraint failed。
    # 先提交，让 foreign_keys=OFF 生效。
    conn.commit()
    conn.execute("PRAGMA foreign_keys=OFF")
    conn.execute("DROP TABLE IF EXISTS agents_new")
    conn.execute("""
        CREATE TABLE agents_new (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            owner_id INTEGER REFERENCES users(id),
            created_at TEXT DEFAULT (datetime('now','localtime')),
            platform TEXT DEFAULT 'gg',
            UNIQUE(name, owner_id, platform)
        )
    """)
    conn.execute("""
        INSERT OR IGNORE INTO agents_new(id, name, owner_id, created_at, platform)
        SELECT id, name, owner_id, created_at, platform FROM agents
    """)
    conn.execute("DROP TABLE agents")
    conn.execute("ALTER TABLE agents_new RENAME TO agents")
    conn.execute("PRAGMA foreign_keys=ON")
    # 重置复制标记，让 _copy_gg_agents_to_tt 重跑补全遗漏的 GG 代理
    conn.execute("DELETE FROM config WHERE key='migrated_copy_agents_to_tt'")
    conn.execute("INSERT OR REPLACE INTO config(key,value) VALUES('migrated_rebuild_agents_unique','1')")
    conn.commit()


def _copy_gg_agents_to_tt(conn: sqlite3.Connection):
    """一次性迁移：将 GG 代理复制一份到 TT 平台（owner_id 统一为 1，冲突跳过）。

    注意：agents 唯一约束已重建为 UNIQUE(name, owner_id, platform)，故
    GG 的 (name, owner_id=1, 'gg') 与 TT 的 (name, owner_id=1, 'tt') 不冲突；
    INSERT OR IGNORE 仅在 TT 已存在同名代理时跳过，不报错。
    """
    migrated = conn.execute(
        "SELECT value FROM config WHERE key='migrated_copy_agents_to_tt'"
    ).fetchone()
    if migrated:
        return
    for s in conn.execute("SELECT DISTINCT name FROM agents WHERE platform='gg'").fetchall():
        conn.execute(
            "INSERT OR IGNORE INTO agents(name, owner_id, platform) VALUES(?,1,'tt')",
            (s["name"],))
    conn.execute("INSERT OR REPLACE INTO config(key,value) VALUES('migrated_copy_agents_to_tt','1')")
    conn.commit()


def _migrate_scrape_dn_history(conn: sqlite3.Connection):
    """一次性迁移：users.prev_scrape_dns（JSON 文本）→ scrape_dn_history 表，随后删掉旧列。

    为什么换存储（2026-09-24，code-review 第 5 轮 Important #1）：
      · JSON 文本只记录了「谁用过这个名字」，**没有先后顺序**，于是认领判据只能做成
        「除我之外没人用过」⇒ 一个名字被 ≥2 人先后用过时，**最后持有者**也取不回自己
        的产物（误拒；用户可见后果与原 MEDIUM-1 缺陷一致：产物在盘上、应用内无恢复
        路径）。换成表后每行有自增 id 作**跨用户单调序号**，认领改为 last-writer-wins
        （我的释放序 > 所有他人的释放序），误拒消除，同值仍拒。
      · 顺带消灭「分隔符串味」整类缺陷：名字存在**行**里，逗号/换行只是普通字符。

    灌入顺序：按每个用户 JSON 数组内的原顺序逐条 INSERT ⇒ 自增 id 递增，与「数组
    顺序即释放先后」一致（数组由 auth 的追加逻辑维护，新释放的追加在尾部）。
    坏值（非 JSON / 非数组 / 非字符串项）跳过 —— 与旧读法「坏值当空」方向一致：
    读**自己**的曾用名读不出来只是自己不再认领，fail-closed。

    ⚠️ 但**跨用户**的先后无论如何都还原不出来（JSON 里没有时间戳，只剩「谁用过」），
    所以「被 ≥2 人的历史同时提到」的名字一律插一行哨兵（`auth._DN_SENTINEL_UID`）
    ⇒ 谁也不判给他。猜一个顺序的风险是**误放**（先释放的人反倒成了最后持有者 ⇒
    认领到别人的产物目录），比误拒严重得多。代价：存量数据的 last-writer-wins 提升
    是**单向**的，只对升级之后发生的改名生效。见 test_scrape_dn_history_migration.py。

    ⚠️ 哨兵是**硬闸**（无条件阻断该名字的认领），不是「一个很大的序号」——
    2026-09-24 code-review 第 6 轮第 1 条：若哨兵只按序号参与比较，它在迁移那一刻
    拿到的是当时的最大 id，此后任何真实用户再释放一次同名（新 id 更大）就赢过它，
    阻断失效。见 `auth._dn_released_keys`。

    失败处理：本函数由 _migrate_if_needed 调用，而后者**每个请求**都跑 ⇒ 异常绝不能
    逃出去打死 get_db()（那会让整个服务 500）。故整体 try/except：失败则回滚且**不**
    打标记，下次重试。

    ⚠️ 此处**不**用 `PRAGMA foreign_keys=OFF` 包 DROP COLUMN：SQLite 的 PRAGMA 在
    事务内是**空操作**，而本函数此前已有 INSERT（事务已开始）—— 写了也只是看着像
    防护。实测不需要：该列无外键、未被索引/生成列引用，在 foreign_keys=ON 且有子表
    引用 users(id) 的情况下 DROP 成功且 PRAGMA foreign_key_check 为空。
    """
    done = conn.execute(
        "SELECT value FROM config WHERE key='migrated_scrape_dn_history'"
    ).fetchone()
    if done:
        return

    cols = [r[1] for r in conn.execute("PRAGMA table_info(users)").fetchall()]
    if "prev_scrape_dns" not in cols:
        # 新库：建表时就没有这个列，无事可做
        conn.execute("INSERT OR REPLACE INTO config(key,value) "
                     "VALUES('migrated_scrape_dn_history','1')")
        conn.commit()
        return

    try:
        # 延迟导入：auth 顶层 `import database`，模块级会成环。放在 try 之内 ——
        # 本函数的契约是「异常绝不逃出去打死 get_db()」，import 失败也算异常。
        import auth

        pending = []           # [(user_id, dn)]
        seen_users = {}        # 归一键 → 用过它的 user_id 集合（判跨用户歧义）
        for row in conn.execute(
                "SELECT id, prev_scrape_dns FROM users "
                "WHERE COALESCE(prev_scrape_dns, '') != ''").fetchall():
            try:
                names = json.loads(row["prev_scrape_dns"])
            except (ValueError, TypeError):
                continue
            if not isinstance(names, list):
                continue
            for n in names:
                if isinstance(n, str) and n:
                    pending.append((row["id"], n))
                    seen_users.setdefault(os.path.normcase(n), set()).add(row["id"])

        for uid, dn in pending:
            conn.execute("INSERT INTO scrape_dn_history(user_id, dn) VALUES(?, ?)",
                         (uid, dn))

        # ⚠️ 跨用户先后**无法还原** —— JSON 里没有时间戳，只剩「谁用过」。
        # 而 last-writer-wins 判据一旦把顺序判反，方向是**误放**：先释放的人反倒
        # 成了「最后持有者」，于是他能认领那个目录、读到别人留在里面的产物。
        # 故对「被 ≥2 人的历史同时提到」的名字**谁也不给** —— 插一行 user_id=0 的
        # 哨兵（0 不是任何真实用户，自增主键从 1 起；同一个 dn 若有多条也只需一条，
        # 但多插无害，取 MAX(id) 仍是它），它在 LWW 比较里对该名字永远最大 ⇒
        # 每个真实用户对这一档都退回修复前的「拒」。只被一个人提到过的名字没有
        # 歧义，仍判给他。
        # 这让旧数据的修复保持**单向**：只有升级**之后**发生的改名才享受
        # last-writer-wins。代价是「被多人先后用过」的存量名字仍取不回自己的产物，
        # 但方向 fail-closed，不会漏读 —— 见设计文档 §0.10。
        sentinel = set()
        for dn_key, users in seen_users.items():
            if len(users) > 1:
                sentinel.add(dn_key)
        for uid, dn in pending:
            if os.path.normcase(dn) in sentinel:   # 与 auth._dn_key 同一口径
                # ⚠️ 必须带**亚秒**（2026-09-25，code-review 第 7 轮 Important #1）：
                # 表默认值 `datetime('now')` 只到秒，而哨兵判据是 `ts >= ctime` ——
                # 同一个截断方向对**释放行**是 fail-closed（`ts > ctime` 更难成立），
                # 对**哨兵**却成了 **fail-open**：时刻被截小就拦不住它当年所判的那个化身，
                # 「同一秒内先建目录、后跑迁移」会把这条歧义名悄悄放开。
                conn.execute(
                    "INSERT INTO scrape_dn_history(user_id, dn, created_at) "
                    "VALUES(?, ?, strftime('%Y-%m-%d %H:%M:%f', 'now'))",
                    (auth._DN_SENTINEL_UID, dn))

        conn.execute("ALTER TABLE users DROP COLUMN prev_scrape_dns")
        conn.execute("INSERT OR REPLACE INTO config(key,value) "
                     "VALUES('migrated_scrape_dn_history','1')")
        conn.commit()
    except Exception as e:
        print(f"[Migrate] scrape_dn_history 迁移失败（不回滚标记，下次重试）：{e}")
        conn.rollback()


# ⚠️ 2026-09-25（设计文档 §0.13）：这里原有 `_tombstone_orphan_scrape_dirs` ——
# 「扫一次盘、给不属于任何存活用户的目录名补哨兵墓碑」。**已退役删除**，理由：
# 它当年之所以把这一档一刀切封死，是因为认领判据**没有时间维度** —— 「我自己的旧目录」
# 与「被删用户的目录」在数据上完全同形（§0.12 收口 1 已论证），只能取严。
# 判据升级为「我的最后释放时刻 > 该目录创建时刻」之后，这一档由判据本身接住：曾用名
# 持有者的行**不覆盖**建于更早的无主目录 ⇒ 拒；而没有释放行的人本来就越不过判据 3
# （目录存在、不在 own_keys）。而哨兵留下的是**永久**硬闸，会把「目录被清理后重建、
# 本人想改回原名」这条路一并封死。
# 它当年写下的哨兵行**保留在表里**（新判据按「化身」判，见 auth._sentinel_row_blocks_dir）
# ⇒ 无需任何破坏性清理、无需新迁移步骤。旧一次性标记键 `tombstoned_orphan_scrape_dirs`
# 保留（历史记录，无代码读取）。



def _migrate_if_needed(conn: sqlite3.Connection):
    """首次启动时从旧格式导入数据。"""
    root = os.path.dirname(os.path.dirname(_db_path()))

    # 复制 GG 选项到 FB
    _copy_gg_options_to_fb(conn)
    # 复制 GG 选项到 TT
    _copy_gg_options_to_tt(conn)
    # 重建 agents UNIQUE（含 platform）+ 重置复制标记
    _rebuild_agents_platform_unique(conn)
    # 复制 GG 代理到 TT
    _copy_gg_agents_to_tt(conn)

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

    # 4. 迁移 videos 表为复合主键 (id, owner_id) — 支持多人私有同一视频
    # 先 SELECT 判断是否已迁移，避免每个请求都执行写操作（INSERT OR IGNORE 也会抢占 SQLite 写锁）
    claimed = conn.execute(
        "SELECT value FROM config WHERE key='migrated_videos_composite_pk'"
    ).fetchone()
    if not claimed:
        # 首次：INSERT OR IGNORE 抢占标记，避免并发时多个连接同时执行 DDL 导致锁冲突
        conn.execute("INSERT OR IGNORE INTO config(key,value) VALUES('migrated_videos_composite_pk','0')")
        conn.commit()
        claimed = conn.execute(
            "SELECT value FROM config WHERE key='migrated_videos_composite_pk'"
        ).fetchone()
    if claimed and claimed["value"] == "0":
        try:
            _migrate_videos_composite_pk(conn)
            conn.execute("UPDATE config SET value='1' WHERE key='migrated_videos_composite_pk'")
            conn.commit()
        except Exception as e:
            # 迁移失败（如并发锁冲突），清除标记让下次重试
            print(f"[Migrate] videos composite PK migration failed: {e}")
            conn.rollback()

    # 4.1 重建 product_assets / video_consumption 的 FK 引用（DROP+RENAME 后 FK 内部 ID 失效）
    fk_claim = conn.execute(
        "SELECT value FROM config WHERE key='migrated_fk_rebuild_after_composite_pk'"
    ).fetchone()
    if not fk_claim:
        conn.execute("INSERT OR IGNORE INTO config(key,value) VALUES('migrated_fk_rebuild_after_composite_pk','0')")
        conn.commit()
        fk_claim = conn.execute(
            "SELECT value FROM config WHERE key='migrated_fk_rebuild_after_composite_pk'"
        ).fetchone()
    if fk_claim and fk_claim["value"] == "0":
        try:
            _rebuild_dependent_fks(conn)
            conn.execute("UPDATE config SET value='1' WHERE key='migrated_fk_rebuild_after_composite_pk'")
            conn.commit()
        except Exception as e:
            print(f"[Migrate] FK rebuild failed: {e}")
            conn.rollback()

    _migrate_options_tables(conn)
    # 5. users.prev_scrape_dns（JSON）→ scrape_dn_history 表，并删掉旧列
    _migrate_scrape_dn_history(conn)
    # 6. （已退役）磁盘上的无主爬取目录 → 补哨兵墓碑。
    #    2026-09-25（设计文档 §0.13）：认领判据加了时间维度后，这一档由判据本身接住
    #    （曾用名持有者的释放行不覆盖建于更早的无主目录 ⇒ 拒），扫盘整段删除；它当年写下
    #    的哨兵行保留（新判据按「化身」判，不误伤）。详见被删函数位置的注释。
    _cleanup_old_option_columns(conn)

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


def _migrate_videos_composite_pk(conn: sqlite3.Connection):
    """将 videos 表从单主键 (id) 改为复合主键 (id, owner_id)。
    同时为 product_assets / video_consumption 加 video_owner_id 并回填。"""
    # 检测是否已是新结构
    cols = [r[1] for r in conn.execute("PRAGMA table_info(videos)").fetchall()]
    pks = [r[1] for r in conn.execute("PRAGMA table_info(videos)").fetchall()
           if r[5]]  # pk column
    if "owner_id" not in cols:
        return  # 尚未添加 owner_id 列，等下次 _ensure_columns 后再迁移
    if len(pks) > 1:
        return  # 已是复合主键

    # 1. 清理上次失败的残留，创建新表
    conn.execute("DROP TABLE IF EXISTS videos_new")
    conn.execute("""CREATE TABLE videos_new (
        id TEXT NOT NULL,
        owner_id INTEGER NOT NULL DEFAULT 1 REFERENCES users(id),
        url TEXT,
        title TEXT,
        region TEXT DEFAULT '通用',
        frame_type TEXT DEFAULT '非融帧',
        effectiveness TEXT DEFAULT '',
        product_name TEXT DEFAULT '',
        review_status TEXT DEFAULT '能过审',
        is_public INTEGER DEFAULT 0,
        imported_at TEXT,
        channel_name TEXT DEFAULT '',
        PRIMARY KEY (id, owner_id)
    )""")

    # 2. 复制数据（临时关闭 FK，因为旧数据可能存在无效 owner_id）
    conn.execute("PRAGMA foreign_keys=OFF")
    conn.execute("""
        INSERT INTO videos_new (id, owner_id, url, title, region, frame_type,
            effectiveness, product_name, review_status, is_public, imported_at, channel_name)
        SELECT id, COALESCE(owner_id, 1), url, title, region, frame_type,
            COALESCE(effectiveness, ''), COALESCE(product_name, ''),
            COALESCE(review_status, '能过审'), COALESCE(is_public, 0), imported_at,
            COALESCE(channel_name, '')
        FROM videos
    """)

    # 3. 替换表
    conn.execute("DROP TABLE videos")
    conn.execute("ALTER TABLE videos_new RENAME TO videos")
    conn.execute("PRAGMA foreign_keys=ON")

    # 4. 回填 product_assets.video_owner_id
    conn.execute("""
        UPDATE product_assets SET video_owner_id = (
            SELECT owner_id FROM videos WHERE videos.id = product_assets.video_id LIMIT 1
        )
    """)

    # 5. 回填 video_consumption.video_owner_id
    conn.execute("""
        UPDATE video_consumption SET video_owner_id = (
            SELECT owner_id FROM videos WHERE videos.id = video_consumption.video_id LIMIT 1
        )
    """)


def _rebuild_dependent_fks(conn: sqlite3.Connection):
    """重建 product_assets 和 video_consumption 表，修复因 videos 复合主键迁移
    (DROP + RENAME) 导致的 FK 内部引用 ID 失效。"""
    # --- product_assets ---
    conn.execute("PRAGMA foreign_keys=OFF")
    conn.execute("DROP TABLE IF EXISTS product_assets_new")
    conn.execute("""CREATE TABLE product_assets_new (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        product_id INTEGER NOT NULL REFERENCES products(id),
        video_id TEXT NOT NULL,
        video_owner_id INTEGER NOT NULL DEFAULT 1,
        added_by INTEGER REFERENCES users(id),
        added_at TEXT DEFAULT (datetime('now','localtime')),
        UNIQUE(product_id, video_id),
        FOREIGN KEY (video_id, video_owner_id) REFERENCES videos(id, owner_id)
    )""")
    conn.execute("""
        INSERT INTO product_assets_new (id, product_id, video_id, video_owner_id, added_by, added_at)
        SELECT id, product_id, video_id, video_owner_id, added_by, added_at FROM product_assets
    """)
    conn.execute("DROP TABLE product_assets")
    conn.execute("ALTER TABLE product_assets_new RENAME TO product_assets")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_product_assets_product ON product_assets(product_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_product_assets_video ON product_assets(video_id)")

    # --- video_consumption ---
    conn.execute("DROP TABLE IF EXISTS video_consumption_new")
    conn.execute("""CREATE TABLE video_consumption_new (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        video_id TEXT NOT NULL,
        video_owner_id INTEGER NOT NULL DEFAULT 1,
        user_id INTEGER,
        product_id INTEGER REFERENCES products(id),
        amount REAL NOT NULL,
        consume_date TEXT DEFAULT '',
        created_at TEXT,
        FOREIGN KEY (video_id, video_owner_id) REFERENCES videos(id, owner_id)
    )""")
    conn.execute("""
        INSERT INTO video_consumption_new (id, video_id, video_owner_id, user_id, product_id, amount, consume_date, created_at)
        SELECT id, video_id, video_owner_id, user_id, product_id, amount, consume_date, created_at FROM video_consumption
    """)
    conn.execute("DROP TABLE video_consumption")
    conn.execute("ALTER TABLE video_consumption_new RENAME TO video_consumption")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_vc_video ON video_consumption(video_id, video_owner_id)")
    conn.execute("PRAGMA foreign_keys=ON")


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


def task_delete(task_id: str):
    """删除单条任务记录。"""
    db = get_db()
    db.execute("DELETE FROM video_tasks WHERE task_id=?", (task_id,))
    db.commit()
    db.close()


def task_cleanup_old(retention_days: int = 7):
    """删除超过保留天数的已完成/错误任务记录。"""
    db = get_db()
    db.execute(
        "DELETE FROM video_tasks WHERE status IN ('completed', 'error') "
        "AND finished_at != '' "
        "AND datetime(finished_at) < datetime('now', 'localtime', ?)",
        (f'-{retention_days} days',)
    )
    # 同时清理长时间卡在 pending/processing 的僵尸任务（超过 1 天）
    db.execute(
        "DELETE FROM video_tasks WHERE status IN ('pending', 'processing') "
        "AND datetime(created_at) < datetime('now', 'localtime', '-1 day')"
    )
    db.commit()
    db.close()


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


def regions_list(platform: str = None) -> list[dict]:
    """返回所有地区及其时区。platform 可选过滤。"""
    db = get_db()
    if platform:
        rows = db.execute("SELECT * FROM regions WHERE platform=? ORDER BY name", (platform,)).fetchall()
    else:
        rows = db.execute("SELECT * FROM regions ORDER BY name").fetchall()
    db.close()
    return [dict(r) for r in rows]


def regions_update(region_id: int, timezone: str):
    """更新地区时区。"""
    db = get_db()
    db.execute("UPDATE regions SET timezone=? WHERE id=?", (timezone, region_id))
    db.commit()
    db.close()


def regions_create(name: str, timezone: str = "", platform: str = "gg") -> int:
    """新增地区，返回 id。"""
    db = get_db()
    db.execute(
        "INSERT INTO regions(name, timezone, platform) VALUES(?,?,?)",
        (name, timezone, platform))
    db.commit()
    row = db.execute("SELECT id FROM regions WHERE name=? AND platform=?", (name, platform)).fetchone()
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
