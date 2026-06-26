# GG-Server 数据迁移方案设计

**日期**：2026-06-26
**状态**：待确认

## 1. 背景与目标

### 现状问题

- GG-Server 已支持多用户 + 数据隔离（owner_id），但现有数据全部归属 developer (id=1)
- 各老用户原本在自己电脑上使用 ImageCrawling，各自积累了独立的数据（products、packages、accounts、mcc、videos 等）
- 新用户加入 GG-Server 后看不到任何数据
- 没有服务器迁移机制，换机器后数据转移困难

### 目标

1. 老用户能把 ImageCrawling 的数据无缝迁移到 GG-Server 个人账号下
2. 新老用户都能自助导出/导入自己的数据
3. 管理员能整库备份/恢复，方便换服务器
4. 产品管理支持多人协作（多人可跑同一产品）

---

## 2. 方案总览：CLI + Web 互补

| 场景 | 方式 | 说明 |
|------|------|------|
| 个人从 ImageCrawling 迁数据 | Web 上传 JSON 文件 | 先在 ImageCrawling 电脑上跑导出脚本生成 JSON |
| 管理员帮用户批量导入 | CLI 或 Web 后台 | CLI 适合大文件 db，Web 适合日常 |
| 个人导出备份 | Web 下载 JSON | 设置页一键导出 |
| 服务器迁移 | CLI 整库备份/恢复 | 最稳定，不走 HTTP |

---

## 3. 数据模型变更

### 3.1 products 表

```sql
-- 新增字段（通过 ALTER TABLE 迁移）
ALTER TABLE products ADD COLUMN owner_id INTEGER REFERENCES users(id);
ALTER TABLE products ADD COLUMN runner_ids TEXT DEFAULT '[]';  -- JSON 数组如 '[1,2,5]'
ALTER TABLE products ADD COLUMN is_archived INTEGER DEFAULT 0;
```

- `owner_id`：产品创建者/导入者
- `runner_ids`：正在跑此产品的人员列表（JSON 数组，可编辑）
- `is_archived`：软删除/归档标记

### 3.2 import_history 表

```sql
CREATE TABLE IF NOT EXISTS import_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER REFERENCES users(id),
    file_name TEXT,
    file_type TEXT,           -- 'db' | 'json'
    products_count INTEGER DEFAULT 0,
    packages_count INTEGER DEFAULT 0,
    accounts_count INTEGER DEFAULT 0,
    mcc_count INTEGER DEFAULT 0,
    videos_count INTEGER DEFAULT 0,
    copywritings_count INTEGER DEFAULT 0,
    tags_count INTEGER DEFAULT 0,
    skipped_count INTEGER DEFAULT 0,
    status TEXT DEFAULT 'success',  -- 'success' | 'partial' | 'error'
    error_msg TEXT DEFAULT '',
    created_at TEXT DEFAULT (datetime('now','localtime'))
);
```

### 3.3 config 表新增 key

```
db_version → 数据库版本号，用于自动迁移检测
```

### 3.4 已有表

accounts、mcc、videos 已有 owner_id，无需额外变更。

---

## 4. 数据分流策略

导入时按以下策略决定数据归属：

| 数据类型 | 归属策略 |
|---------|---------|
| accounts | → 归导入用户（owner_id = 当前用户） |
| mcc | → 归导入用户（owner_id = 当前用户） |
| videos | → 归导入用户（owner_id = 当前用户） |
| products + 其 packages | → 归导入用户（owner_id = 当前用户），自动加入 runner |
| copywritings | → 合并到共享池（按 content 去重，INSERT OR IGNORE） |
| tags | → 合并到共享池（按 key 去重，INSERT OR IGNORE） |
| config | → 跳过 GG-Server 专属 key（migrated_*、gg_server_initialized 等） |

> **注意**：同一产品的包如果在 GG-Server 已存在（同 product_name），不会自动去重。用户可手动用「合并产品」功能处理重复。

---

## 5. 产品管理增强

### 5.1 产品筛选

产品列表新增 `runner` 筛选参数：

- `mine`（默认）：只显示「我在跑的产品」——当前用户在 `runner_ids` 中
- `all`：显示全部产品

### 5.2 产品合并

用户可勾选 ≥2 个产品，点击「合并产品」：

1. 选择第一个勾选的产品作为**主产品**（保留）
2. 副产品的 packages → 迁入主产品（按 package_name + url 去重）
3. 副产品的 runner_ids → 合并入主产品
4. 副产品的 accounts/mcc 关联 → 迁入主产品
5. 删除副产品

### 5.3 Runner 管理

产品详情弹窗中新增 Runner 区域：

- 展示当前在跑的成员列表
- [+ 添加 runner] 下拉选择已有用户
- 每个 runner 旁有 [x] 移除按钮
- 产品 owner 和管理员可编辑

---

## 6. 导入流程

### 6.1 ImageCrawling 端：直接取 db 文件

ImageCrawling 用户大部分跑的是 `.exe`，没有 Python 环境。他们只需找到 `.exe` 同目录下的 `temp/app.db` 文件，直接上传到 GG-Server 即可（Web 端支持 `.db` 上传）。

### 6.2 用户自助导入（Web 端）

```
POST /api/data/import
  上传 .json 或 .db 文件
  → 后端解析 → 智能分流 → 写入 → 记录 import_history
  → 返回导入报告：
    {
      "success": true,
      "report": {
        "products": 5, "packages": 30,
        "accounts": 8, "mcc": 3, "videos": 120,
        "copywritings": { "imported": 10, "skipped": 2 },
        "tags": { "imported": 3, "skipped": 1 },
        "skipped_config_keys": ["migrated_video_history"]
      }
    }
```

预览模式（先看再导）：

```
GET /api/data/import/preview
  先解析上传的文件，返回将导入的数据摘要，不写入
```

### 6.3 管理员后台导入

通过 `/api/admin/data/import` 上传 + 指定目标用户 ID。管理员用户管理页面每个用户行有 [导入数据] 按钮。

### 6.4 CLI 导入

```bash
python manage.py import-db <db路径> --user <用户名>
python manage.py import-json <json路径> --user <用户名>
```

---

## 7. 导出流程

### 7.1 个人导出（Web 端）

```
GET /api/data/export
  → 查询当前用户 owner_id 的所有数据
  → 返回 JSON 下载
  → 文件名: gg-server-export-{username}-{日期}.json
```

### 7.2 JSON 导出格式

```json
{
  "version": 1,
  "exported_at": "2026-06-26 20:30:00",
  "exported_by": "zhangsan",
  "source": "gg-server",
  "data": {
    "products": [{ "id": 1, "product_name": "xxx", "runner_ids": "[1,2]", ... }],
    "packages": [{ "id": 1, "product_id": 1, "package_name": "com.xxx", ... }],
    "accounts": [{ "id": 1, "name": "xxx", "account_id": "xxx", ... }],
    "mcc": [{ "id": 1, "name": "xxx", "mcc_id": "xxx", ... }],
    "videos": [{ "id": "abc123", "title": "xxx", ... }],
    "copywritings": [{ "id": 1, "region": "巴西", "content": "xxx", ... }],
    "tags": [{ "key": "regions", "value": "[\"巴西\"]", ... }],
    "config": [{ "key": "font_recent", "value": "..." }]
  }
}
```

---

## 8. CLI 管理工具 (`manage.py`)

```bash
cd GG-Server/py

# 整库备份
python manage.py backup
# → temp/backups/app_20260626_203000.db

# 列出备份
python manage.py list-backups

# 整库恢复
python manage.py restore temp/backups/app_20260626_203000.db
# → 自动备份当前库 → 替换

# 从 db 导入
python manage.py import-db <db路径> --user <用户名>

# 从 JSON 导入
python manage.py import-json <json路径> --user <用户名>

# 导出指定用户
python manage.py export-user <用户名> [-o output.json]

# 导出所有用户
python manage.py export-all [-o output_dir/]
```

---

## 9. API 列表

### 新增 API

| 方法 | 路径 | 说明 | 鉴权 |
|------|------|------|------|
| POST | `/api/data/import` | 上传文件导入（自动识别 db/json） | JWT |
| GET | `/api/data/import/preview` | 预览导入内容（解析不写入） | JWT |
| GET | `/api/data/export` | 导出当前用户数据为 JSON | JWT |
| GET | `/api/data/import-history` | 查询导入历史记录 | JWT |
| POST | `/api/admin/data/import` | 为指定用户导入数据 | admin |
| GET | `/api/admin/data/export/<user_id>` | 导出指定用户数据 | admin |

### 产品 API 变更

| 方法 | 路径 | 变更 |
|------|------|------|
| GET | `/api/products/list` | 新增 `runner` 参数（`mine`/`all`，默认 `mine`） |
| POST | `/api/products/merge` | 新增：合并产品 |
| PUT | `/api/products/<pid>/runners` | 新增：更新 runner 列表 |

---

## 10. 前端变更

### 10.1 设置页 — 新增「数据管理」标签

- [导出我的数据] 按钮 → 下载 JSON
- 导入数据：拖拽/点击上传 .json 或 .db 文件 → 预览 → [确认导入]
- 导入历史：最近 5 次记录

### 10.2 产品列表页改造

- 顶部筛选：[全部产品] [我在跑的产品]（默认）
- 产品卡片显示 Runner 头像列表
- [合并产品] 按钮（勾选 ≥2 个产品后可用）
- 产品详情弹窗新增 Runner 管理区域

### 10.3 用户管理页

- 每个用户行新增 [导入数据] 按钮（管理员）

---

## 11. 文件清单

### GG-Server 项目

| 文件 | 操作 | 说明 |
|------|------|------|
| `py/manage.py` | **新建** | CLI 管理工具 |
| `py/data_service.py` | **新建** | 导入/导出核心逻辑（Web 和 CLI 共用） |
| `py/main.py` | 修改 | 新增 data API 路由 + 产品 API 调整 |
| `py/database.py` | 修改 | products 表迁移 + import_history 表 |
| `py/migrate_from_production.py` | 弃用 | 功能由 manage.py import-db 取代 |
| `frontend/src/views/SettingsPanel.vue` | 修改 | 新增数据管理标签 |
| `frontend/src/views/ProductPanel.vue` | 修改 | 筛选 + 合并 + runner 管理 |
| `frontend/src/views/UserManageView.vue` | 修改 | 导入数据按钮 |

### ImageCrawling 项目

无需改动。用户直接取 `.exe` 同目录下的 `temp/app.db` 上传即可。

---

## 12. 注意事项

- **纯增量原则**：不修改原有功能逻辑，只在现有 API 上增加参数和路由
- **数据库迁移**：products 表新增列通过 ALTER TABLE，不影响已有数据
- **向后兼容**：现有 products 数据的 owner_id 和 runner_ids 初始化为 NULL，由迁移脚本补填（owner_id=1, runner_ids=[1]）
- **文件大小限制**：Web 上传限制 50MB（JSON）或 200MB（db），超过用 CLI
- **安全性**：导入操作记录 import_history，可追溯
