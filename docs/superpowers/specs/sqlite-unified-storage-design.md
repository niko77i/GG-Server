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

> **确认后生成实现计划 → 开始编码。**
