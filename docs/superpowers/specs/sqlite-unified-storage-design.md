# SQLite 统一存储设计

> 日期：2026-06-09 | 状态：待确认

## 1. 背景

项目已有 `temp/youtube.db`（YouTube 视频管理），但其他数据散落各处：

| 数据 | 当前存储 | 问题 |
|------|---------|------|
| 视频生成历史 | `temp/video_set/*.json`（每包一个文件） | 文件数量随包增长，查询不便 |
| 字体最近使用 | `fonts/.recent.json` | 单个 JSON，数据小，问题不大 |
| 视频任务状态 | 内存 `_video_tasks` dict | 重启丢失，无法追踪历史 |
| YouTube 视频 | `temp/youtube.db` ✅ | 已经是 SQLite |

## 2. 目标

用一个 SQLite 数据库 `temp/app.db` 统一管理**所有持久化数据**，替换散落的 JSON 文件，同时保持向后兼容（旧的 JSON 文件首次迁移后不再使用）。

## 3. 数据库设计

### 3.1 表结构

```sql
-- YouTube 视频（从 youtube.db 迁移）
CREATE TABLE videos (
    id TEXT PRIMARY KEY,
    url TEXT,
    title TEXT,
    region TEXT DEFAULT '通用',
    frame_type TEXT DEFAULT '非融帧',
    effectiveness TEXT DEFAULT '',
    product_name TEXT DEFAULT '',
    imported_at TEXT
);

-- 视频标签 / 元数据（从 youtube.db.tags 迁移）
CREATE TABLE tags (
    key TEXT PRIMARY KEY,
    value TEXT
);

-- 视频生成历史（替换 temp/video_set/*.json）
CREATE TABLE video_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    package TEXT NOT NULL,
    name TEXT,                          -- 用户命名的方案名
    settings TEXT NOT NULL,             -- JSON：完整设置快照
    created_at TEXT DEFAULT (datetime('now','localtime')),
    updated_at TEXT DEFAULT (datetime('now','localtime'))
);
CREATE INDEX idx_video_history_pkg ON video_history(package);

-- 视频生成任务记录（替换内存 _video_tasks）
CREATE TABLE video_tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id TEXT UNIQUE NOT NULL,       -- UUID
    package TEXT,
    status TEXT DEFAULT 'pending',      -- pending/running/done/failed
    progress REAL DEFAULT 0,            -- 0~1
    message TEXT DEFAULT '',
    output_path TEXT,
    settings TEXT,                      -- JSON：任务参数
    created_at TEXT DEFAULT (datetime('now','localtime')),
    finished_at TEXT
);
CREATE INDEX idx_video_tasks_status ON video_tasks(status);

-- 全局配置（替换各种散落的配置）
CREATE TABLE config (
    key TEXT PRIMARY KEY,
    value TEXT
);
```

### 3.2 数据迁移策略

- **首次启动**时检测旧数据，自动导入后保留原文件（加 `.bak` 后缀）
- `temp/video_set/*.json` → 逐包读取，写入 `video_history` 表
- `youtube.db` 的 `videos` / `tags` 表 → 直接 ATTACH 导入
- `.recent.json` → 写入 `config` 表，key = `font_recent`

## 4. 代码改动

### 4.1 新增文件

| 文件 | 说明 |
|------|------|
| `py/database.py` | 数据库连接管理、建表、迁移逻辑，暴露 `get_db()` 函数 |

### 4.2 改动文件

| 文件 | 改动 |
|------|------|
| `py/main.py` | 删除 `_yt_db()` 及相关 JSON 文件操作函数（`_history_file`, `_load_pkg_history`, `_save_pkg_history`），改为调用 `database.py` |
| `js/video.js` | API 路径不变，前后端通过 JSON 通信，无需改动 |

### 4.3 API 不变

所有现有 API 路径保持不变，只改后端实现（JSON 文件 → SQLite），前端无感。

## 5. 数据库路径

```
{_DATA_ROOT}/temp/app.db
```

- 开发模式：`项目/temp/app.db`
- EXE 模式：`exe所在目录/temp/app.db`

沿用已有的 `_DATA_ROOT` 变量。

## 6. 依赖

无需新增 Python 包 —— `sqlite3` 是 Python 标准库自带（项目已在 `main.py` 第 808 行使用）。

## 7. 不纳入 SQLite 的数据

| 数据 | 理由 |
|------|------|
| 爬取的图片 (`.png`) | 文件数据，不适合放数据库 |
| 字体文件 (`.ttf/.otf`) | 同上 |
| AI 生成的临时视频 (`.mp4`) | 同上 |

---

## 附录 A：审计补充（2026-07-23）

> 审计人：技术文档工程师  
> 审计范围：对比 `py/database.py`（完整建表 + 迁移逻辑 + 便捷操作函数）和 `py/data_service.py`（导入/导出/备份核心逻辑）

### A.1 表结构严重不完整 — 文档只覆盖 5/26 张表

设计文档第 3.1 节仅列出 5 张表（`videos`, `tags`, `video_history`, `video_tasks`, `config`），但 `_ensure_schema()` 实际创建了 **26 张表**。以下 21 张表在文档中完全缺失：

| 表名 | 用途 | 关键列 |
|------|------|--------|
| `mcc` | MCC 管理 | `id`, `name`, `mcc_id`, `level`, `parent_mcc_id`, `owner_id`, `shared_user_ids` |
| `accounts` | 广告账户管理 | `id`, `name`, `account_id`, `mcc_id`, `timezone`, `agent`, `status`, `acquired_date`, `death_date`, `status_changed_date`, `owner_id` |
| `account_mcc_history` | 账户 MCC 变更审计 | `account_id`, `old_mcc_id`, `new_mcc_id`, `changed_by`, `change_type` |
| `recharge_records` | 充值记录 | `account_id`, `amount`, `agent`, `operator`, `status`, `created_by`, `sheets_synced`, `sheets_error` |
| `sheets_sync_log` | Google Sheets 同步失败日志 | `user_id`, `product_name`, `spreadsheet_id`, `sheet_gid`, `status`, `error_msg`, `rows_json`, `retry_count` |
| `copywritings` | 文案管理 | `id`, `region`, `content`, `owner_id`, `effectiveness`, `is_public` |
| `product_runners` | 产品-跑量人员关联（多对多） | `product_id`, `user_id`（联合主键） |
| `products` | 产品管理 | `id`, `product_name`, `kpi`, `region`, `status`, `mcc_id`, `customer`, `owner_id`, `runner_ids`, `is_archived`, `deleted_at`, `sales_person`, `agency_ratio` |
| `packages` | 产品包管理 | `id`, `product_id`, `series_name`, `package_name`, `url`, `status` |
| `product_assets` | 产品成效素材关联 | `product_id`, `video_id`, `added_by`（UNIQUE 约束防重复） |
| `video_consumption` | 视频消耗追踪（手动录入） | `video_id`, `user_id`, `product_id`, `amount`, `consume_date` |
| `ad_reports` | 广告投放报表（做表数据） | `user_id`, `product_name`, `region`, `report_date`, `account`, `customer_id`, `campaign`, `cost`, `impressions`, `clicks`, `installs`, `in_app_actions`, `cost_per_in_app` |
| `regions` | 地区与时区管理 | `id`, `name`（UNIQUE）, `timezone` |
| `users` | 用户表 | `id`, `username`, `password`, `role`, `display_name`, `last_login`, `created_by`, `config`, `custom_name`, `email`, `telegram_username` |
| `scrape_cache` | 爬取缓存 | `package_name`（PK）, `image_count`, `saved_path`, `logo_path`, `last_scraped`, `scraped_by` |
| `import_history` | 导入操作审计 | `user_id`, `file_name`, `file_type`, `products_count`, `packages_count`, `accounts_count`, `mcc_count`, `videos_count`, `copywritings_count`, `tags_count`, `skipped_count`, `status`, `error_msg` |
| `delist_checks` | 掉包检测结果 | `package_id`（UNIQUE）, `product_id`, `is_delisted`, `checked_at`, `error_msg` |
| `delist_notifications` | 掉包通知状态（按用户） | `package_id`, `user_id`, `first_notified`, `dismissed_at`, `reminder_count`（UNIQUE 约束） |
| `audio_replace_history` | 音频替换历史 | `video_name`, `audio_name`, `output_name`, `output_path`, `size_mb` |
| `audit_log` | 通用审计日志 | `user_id`, `action`, `target_type`, `target_id`, `target_name`, `detail` |

### A.2 已文档化的表也存在列级差异

#### `videos` 表 — 缺少 3 列

| 列名 | 设计文档 | 实际代码 | 差异 |
|------|---------|---------|------|
| `review_status` | **无** | `TEXT DEFAULT '能过审'` | 建表语句中就已存在，非后续迁移添加 |
| `owner_id` | **无** | `INTEGER REFERENCES users(id)` | 通过 `_ensure_columns()` 增量添加，用于多用户数据隔离 |
| `is_public` | **无** | `INTEGER DEFAULT 0` | 通过 `_ensure_columns()` 增量添加 |

#### `video_history` 表 — 默认值差异

| 列名 | 设计文档 | 实际代码 |
|------|---------|---------|
| `name` | `name TEXT`（无默认值） | `name TEXT DEFAULT ''` |

#### `video_tasks` 表 — 默认值差异

| 列名 | 设计文档 | 实际代码 |
|------|---------|---------|
| `package` | `package TEXT`（无默认值） | `package TEXT DEFAULT ''` |
| `settings` | `settings TEXT`（无默认值） | `settings TEXT DEFAULT '{}'` |
| `finished_at` | `finished_at TEXT`（无默认值） | `finished_at TEXT DEFAULT ''` |

#### 索引命名不一致

| 设计文档 | 实际代码 |
|---------|---------|
| `idx_video_history_pkg` | `idx_history_pkg` |
| `idx_video_tasks_status` | `idx_tasks_status` |

### A.3 缺少增量迁移机制的说明

设计文档第 3.2 节描述了"首次启动自动导入"的数据迁移策略，但没有覆盖实际代码中更复杂的迁移体系：

1. **`_ensure_columns()`（每次连接执行）**：通过 `PRAGMA table_info` + 条件 `ALTER TABLE ADD COLUMN` 实现幂等列级迁移，涵盖 `videos.review_status`、`accounts.death_date`、`accounts.status_changed_date`、`videos.owner_id`、`videos.is_public`、`accounts.owner_id`、`mcc.owner_id`、`mcc.shared_user_ids`、`products.owner_id`、`products.runner_ids`、`products.is_archived`、`products.customer`、`products.deleted_at`、`products.sales_person`、`products.agency_ratio`、`recharge_records.status`、`recharge_records.sheets_synced`、`recharge_records.sheets_error`、`copywritings.owner_id`、`copywritings.effectiveness`、`copywritings.is_public`、`users.custom_name`、`users.email`、`users.telegram_username` 等。

2. **`_ensure_schema()` 内的索引迁移**：
   - `ad_reports` 去重索引从 v2 → v3 升级（从 UNIQUE 降级为普通 INDEX，支持聚合 upsert）
   - `product_runners` 关联表与 `products.runner_ids` JSON 列的一致性修复（`migrated_product_runners_v2`）

3. **`_ensure_schema()` 内的数据迁移（设计文档未提及）**：
   - 默认标签初始化：`regions`、`frame_types`、`effectiveness`、`product_names`、`review_statuses` 写入 `tags` 表
   - `migrated_owner_id`：将现有数据归属于 developer（user id=1），涉及 `videos`、`accounts`、`mcc` 三表
   - `_migrate_mcc_dedup()`：合并重复 MCC 记录（同一 `mcc_id` 字符串），developer 记录优先保留，完成后建唯一索引
   - `_migrate_mcc_share_runners()`：回填产品 runner 到 MCC 的 `shared_user_ids`（沿 `parent_mcc_id` 链向上传播）
   - `_init_regions()`：从 `tags` 表同步已有地区到 `regions` 表并预设 24 个地区的时区

### A.4 缺少便捷操作函数层的文档

设计文档第 4 节仅提到 `get_db()` 函数，但实际 `database.py`（第 856-1141 行）暴露了大量便捷操作函数：

| 分类 | 函数 |
|------|------|
| 视频历史 | `history_save()`, `history_list()`, `history_delete()` — 含 30 条上限自动清理逻辑 |
| 视频任务 | `task_create()`, `task_update()`, `task_get()`, `task_delete()`, `task_cleanup_old()` — 含 7 天保留 + 僵尸任务清理（1 天） |
| 配置读写 | `config_get()`, `config_set()` |
| 字体最近使用 | `font_recent_list()`, `font_mark_used()` — 基于 `config` 表的 `font_recent` key，最多 20 条 |
| 地区时区 | `regions_list()`, `regions_update()`, `regions_create()`, `regions_delete()` |
| 产品跑量关联 | `set_product_runners()`, `add_product_runners()`, `get_runner_product_ids()` |

另外还有一个上下文管理器 `db_conn()` 和线程安全的 schema 锁 `_schema_lock`，设计文档也未提及。

### A.5 缺少 `py/data_service.py` 模块的文档

`py/data_service.py`（389 行）是实现数据导入/导出/备份的核心模块，设计文档完全未提及。其包含：

| 函数 | 用途 |
|------|------|
| `preview_import()` | 解析文件返回导入摘要（不写入） |
| `execute_import()` | 实际执行导入：ID 重映射（products→packages、mcc→accounts 的外键级联）、`parent_mcc_id` 修正、config key 白名单过滤（`GG_CONFIG_KEYS` 黑名单） |
| `export_user_data()` | 按 user_id 导出所有关联数据 |
| `export_all_users()` | 批量导出所有用户数据 |
| `backup_database()` | 复制 `app.db` 到 `temp/backups/` |
| `restore_database()` | 从备份恢复（自动备份当前库后再替换） |
| `list_backups()` | 列出所有备份文件及元数据 |

关键设计细节：
- 导入支持 `.db` 和 `.json` 两种格式
- JSON 导入兼容有 `data` 包裹和无包裹两种格式
- 导入时智能跳过 GG-Server 专属 config key（`GG_CONFIG_KEYS` 黑名单）
- 导入时 `products` → `packages` 通过 `pid_map` 做 ID 映射，孤儿包跳过
- 导入时 `mcc` → `accounts` 通过 `mcc_map` 做外键映射，映射不到的 MCC 清空为 NULL
- 导入时 `videos` 用 `INSERT OR IGNORE`（按 `id` 主键去重）

### A.6 架构层面的缺失描述

设计文档缺少以下重要架构决策和实现细节：

1. **多用户数据隔离（owner_id 体系）**：实际代码通过 `owner_id` 字段实现用户级数据隔离，涉及 `videos`、`accounts`、`mcc`、`products`、`copywritings`、`users` 等表。设计文档完全没有提及多用户概念。

2. **共享机制**：`mcc.shared_user_ids`（JSON 数组）允许 MCC 被多用户共享访问；`product_runners` 关联表实现产品维度的跑量人员共享。设计文档未覆盖。

3. **软删除模式**：`products.is_archived` 和 `products.deleted_at` 实现产品软删除，而非物理删除。导出时过滤 `is_archived=1` 的记录。

4. **WAL 模式 + 线程安全**：`get_db()` 设置 `PRAGMA journal_mode=WAL`、`PRAGMA synchronous=NORMAL`、`PRAGMA foreign_keys=ON`，并使用 `threading.Lock` 保护 schema 初始化。

5. **数据库路径计算**：`_db_path()` 通过 `sys.frozen` 判断 EXE 模式 vs 开发模式，自动适配路径。设计文档第 5 节提到了 `_DATA_ROOT`，但实际代码通过独立函数自行计算，不依赖外部变量。

6. **状态迁移**：`accounts` 和 `products`/`packages` 表有 `is_paused` → `status` 的列重命名迁移逻辑。设计文档未提及。

### A.7 建议修正

| 优先级 | 修正项 |
|--------|--------|
| **P0** | 补充全部 26 张表的完整表结构文档（至少涵盖核心表：`products`、`packages`、`accounts`、`mcc`、`users`、`ad_reports`、`regions`、`copywritings`） |
| **P0** | 补充 `videos` 表缺失的 `review_status`、`owner_id`、`is_public` 列；修正 `video_history`/`video_tasks` 的列默认值 |
| **P0** | 新增"多用户数据隔离"架构章节，说明 `owner_id` 体系和 `shared_user_ids` / `product_runners` 共享机制 |
| **P1** | 补充增量迁移机制文档（`_ensure_columns` 列级幂等迁移、门控数据迁移） |
| **P1** | 补充便捷操作函数 API 参考（至少覆盖 `history_*`、`task_*`、`config_*`、`font_*`） |
| **P1** | 新增 `py/data_service.py` 导入/导出/备份模块的完整文档 |
| **P2** | 修正索引名：`idx_video_history_pkg` → `idx_history_pkg`，`idx_video_tasks_status` → `idx_tasks_status` |
| **P2** | 补充 WAL 模式、线程安全、路径计算等基础设施决策 |

---

> **确认后生成实现计划 → 开始编码。**
