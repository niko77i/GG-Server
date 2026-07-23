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

---

## 附录：代码审计补充（2026-07-23）

本章节对照实际代码实现，逐项验证设计文档的落地情况，标记偏差、遗漏和新增内容。

审计范围：
- `py/database.py` — 数据库 schema、迁移逻辑
- `py/data_service.py` — 导入/导出核心逻辑
- `py/migrate_from_production.py` — 生产数据迁移脚本
- `py/manage.py` — CLI 管理工具
- `py/main.py` — Web API 路由（导入/导出/产品合并/runner 管理相关路由）

---

### A. 与设计一致（已验证通过）

| 设计项 | 对应代码 | 状态 |
|--------|----------|------|
| products 表新增 `owner_id`、`runner_ids`、`is_archived` | `database.py` L101-103 `_ensure_columns()` 中的 `_add_column_if_missing` | 一致 |
| import_history 表结构（所有列） | `database.py` L377-393 `_ensure_schema()` 中 CREATE TABLE | 一致 |
| accounts → 导入时归入目标用户（owner_id） | `data_service.py` L175 `d["owner_id"] = target_user_id` | 一致 |
| mcc → 导入时归入目标用户（owner_id） | `data_service.py` L152 `d["owner_id"] = target_user_id` | 一致 |
| videos → 导入时归入目标用户（owner_id） | `data_service.py` L194 `d["owner_id"] = target_user_id` | 一致 |
| products+packages → 归入目标用户，自动加入 runner | `data_service.py` L115-116: `owner_id` + `runner_ids = json.dumps([target_user_id])` | 一致 |
| tags → 合并到共享池，按 key 去重 | `data_service.py` L223-232: `INSERT OR REPLACE`，按 key 判断 | 一致（实现用 REPLACE 而非 IGNORE，效果等价） |
| config → 跳过 GG-Server 专属 key | `data_service.py` L235-242: 检查 `key in GG_CONFIG_KEYS` | 一致 |
| 导出格式：version/exported_at/exported_by/source/data | `data_service.py` L322-328 `export_user_data()` 返回值 | 一致 |
| 导出文件名格式 | `main.py` L6020: `gg-server-export-{username}-{date_str}.json` | 一致 |
| CLI 命令：backup / list-backups / restore / import-db / import-json / export-user / export-all | `manage.py` L117-137 argparse 子命令 | 一致 |
| POST /api/data/import（Web 上传导入） | `main.py` L5943-6004 | 一致 |
| GET /api/data/export（Web 导出） | `main.py` L6007-6026 | 一致 |
| GET /api/data/import-history | `main.py` L6029-6040 | 一致 |
| POST /api/admin/data/import（管理员为指定用户导入） | `main.py` L6043-6073 | 一致 |
| GET /api/admin/data/export/<uid>（管理员导出指定用户） | `main.py` L6076-6095 | 一致 |
| 产品列表 `runner` 筛选参数（mine/all/指定user_id） | `main.py` L2217-2253 | 一致 |
| PUT /api/products/<pid>/runners（更新 runner 列表） | `main.py` L2658-2700 | 一致 |
| POST /api/products/merge（合并产品） | `main.py` L2526-2618 | 一致 |
| 产品合并：packages 按 package_name+url 去重 | `main.py` L2577-2580 `SELECT ... WHERE package_name=? AND url=?` | 一致 |
| 产品合并：合并 runner_ids + 去重 | `main.py` L2600-2601 `list(set(master_runners))` | 一致 |

---

### B. 与设计有偏差（需关注）

#### B.1 copywritings 分流策略变更（重要）

| | 设计 | 实际代码 |
|------|------|-----------|
| 归属 | 合并到共享池，按 content 去重，INSERT OR IGNORE | 归入导入用户，`owner_id = target_user_id`，不做去重 |
| 代码位置 | — | `data_service.py` L209-220 |

**影响**：copywritings 从"全平台共享"变为"用户私有"。导出时也按 `owner_id` 过滤（`data_service.py` L308-310），逻辑自洽。如果后续需要共享池模式，需额外开发。

#### B.2 tags 实现用 REPLACE 替代设计中的 IGNORE

设计写的是 `INSERT OR IGNORE`，代码实现为 `INSERT OR REPLACE`（`data_service.py` L231）。对于 key 为主键的场景，REPLACE 会覆盖旧值，IGNORE 会保留旧值。当前行为是新数据覆盖旧数据。

#### B.3 产品合并未迁移 accounts/mcc 关联

设计文档 5.2 节第 4 条明确写了"副产品的 accounts/mcc 关联 → 迁入主产品"，但 `main.py` `products_merge()`（L2526-2618）中：

- 迁移了 packages（L2573-2590）
- 清理了 product_assets、delist_checks、product_runners
- 删除了副产品的 packages 和 products
- **未迁移 accounts/mcc 关联**

**影响**：副产品关联的 accounts 和 mcc 在合并后变为孤儿数据（accounts.mcc_id 指向已删除的产品 mcc）。

#### B.4 import_history 记录范围不一致

| 调用路径 | 是否记录 import_history | 代码位置 |
|----------|------------------------|----------|
| Web API POST /api/data/import | 是 | `main.py` L5976-5995 |
| 管理员 API POST /api/admin/data/import | **否** | `main.py` L6043-6073（只有 execute_import，无 INSERT INTO import_history） |
| CLI manage.py import-db / import-json | **否** | `manage.py` L50-75（cmd_import 只调用 execute_import，无 import_history 写入） |

此外，`data_service.py` 的 `execute_import()` 核心函数本身不负责记录历史，符合职责分离原则，但文档应明确调用方必须记录。

---

### C. 设计提及但代码未实现

| 设计项 | 设计位置 | 代码现状 |
|--------|----------|----------|
| **GET /api/data/import/preview**（预览导入） | 设计 6.2 节 | **未实现**。`data_service.py` 有 `preview_import()` 函数（L67-84），但 `main.py` 中没有对应的 API 路由 |
| **config 表 `db_version` 键** | 设计 3.3 节 | **未添加**。代码使用的是功能粒度的迁移标记（如 `migrated_owner_id`、`migrated_mcc_dedup`、`migrated_product_runners_v2` 等），而非统一的版本号。当前方案更灵活，但失去了全局版本追踪能力 |
| **migrate_from_production.py 弃用** | 设计 11 节 | **未执行**。文件仍然存在且功能完整（`py/migrate_from_production.py`），未被删除或标记为 deprecated |

---

### D. 代码新增但设计未提及（架构演化）

以下为实际代码中新增、而设计文档未覆盖的内容：

#### D.1 product_runners 关联表（重要架构决策）

设计只规划了 `products.runner_ids` JSON 列，但代码额外创建了规范化的关联表：

```sql
-- database.py L260-265
CREATE TABLE IF NOT EXISTS product_runners (
    product_id INTEGER NOT NULL REFERENCES products(id),
    user_id INTEGER NOT NULL REFERENCES users(id),
    PRIMARY KEY (product_id, user_id)
);
CREATE INDEX IF NOT EXISTS idx_product_runners_user ON product_runners(user_id);
```

配套代码：
- `database.py` L1109-1141：`set_product_runners()`、`add_product_runners()`、`get_runner_product_ids()` 便捷函数
- `database.py` L492-523：`_migrate_product_runners_v2` 迁移逻辑，将 JSON 列数据同步到关联表
- `main.py` L2190-2199：`/api/products/runner-products` 使用 product_runners 表查询
- `main.py` L2689-2691：更新 runner 时双写（JSON 列 + 关联表）
- `main.py` L2423-2432：创建产品时双写

**评估**：这是正确的架构演化。JSON 列便于兼容旧数据和全量序列化，关联表支持索引查询。但双写带来了数据一致性风险——目前的 `_migrate_product_runners_v2` 迁移在启动时修复差异，是合理的兜底方案。

#### D.2 MCC 去重迁移（`_migrate_mcc_dedup`）

`database.py` L599-684：合并同一 `mcc_id` 字符串的重复 MCC 记录，developer 的优先保留，合并 shared_user_ids，更新 products/accounts/子 MCC 的外键引用，然后创建唯一索引。

此逻辑是为了处理多用户导入时产生的 MCC 重复问题，设计文档未提及。

#### D.3 MCC runner 共享迁移（`_migrate_mcc_share_runners`）

`database.py` L544-596：将产品 runner 回填到 MCC 的 `shared_user_ids` 字段（含上级 MCC 链），保证有产品共同协作的用户能看到对应的 MCC。

#### D.4 mcc.shared_user_ids 列

设计未提及此字段。代码 `database.py` L98 添加了 `mcc.shared_user_ids TEXT DEFAULT '[]'`。用于 MCC 的跨用户共享可见性控制。

#### D.5 products 表额外字段

设计 3.1 节只列了 `owner_id`、`runner_ids`、`is_archived`。代码额外添加：

| 列名 | 代码位置 | 说明 |
|------|----------|------|
| `customer` | L110 | 客户名称 |
| `deleted_at` | L111 | 软删除时间戳 |
| `sales_person` | L112 | 销售人员 |
| `agency_ratio` | L113 | 代理分成比例 |

这些属于产品管理增强，建议补充到 3.1 节。

#### D.6 users 表额外字段

代码添加了设计未提及的列：`email`、`telegram_username`（`database.py` L118-119）。

#### D.7 copywritings 表额外字段

设计只提到 `copywritings` 需要按 content 去重。代码添加了 `owner_id`、`effectiveness`、`is_public` 列（`database.py` L114-116）。

#### D.8 accounts 表额外字段

设计说"已有 owner_id，无需额外变更"。代码额外添加了 `death_date`、`status_changed_date`（`database.py` L92-93），属其他功能的增量。

#### D.9 recharge_records 表额外字段

`database.py` L104-106：添加了 `status`、`sheets_synced`、`sheets_error`，不属于迁移功能本身但在此次 schema 变更中一并执行。

#### D.10 video_history / video_tasks 导出不按 owner 过滤

`data_service.py` L299-305：`export_user_data()` 对 `video_history` 和 `video_tasks` 导出全表数据，未按 `owner_id` 过滤。这会导致用户 A 导出时带出用户 B 的视频历史和任务记录。需确认这两个表是否设计为全局共享——与当前数据隔离原则不一致。

#### D.11 导入时 product_runners 关联表未同步

`data_service.py` `execute_import()` 中导入 products 时（L112-124）设置了 `runner_ids` JSON 列，但未同时插入 `product_runners` 关联表。当前依赖 `_migrate_product_runners_v2` 在下一次连接启动时修复，但如果用户导入后立即查询 `/api/products/runner-products`，可能查不到新导入的产品。建议在 `execute_import` 中增加 `INSERT INTO product_runners` 调用。

#### D.12 新增的迁移标记键未加入 GG_CONFIG_KEYS 排除列表

`data_service.py` L10-17 `GG_CONFIG_KEYS` 集合包含 5 个键，但 `database.py` 的 `_ensure_schema()` 中实际使用了更多的迁移标记键：

| 迁移标记 | 是否在 GG_CONFIG_KEYS 中 |
|----------|------------------------|
| `migrated_video_history` | 是 |
| `migrated_youtube` | 是 |
| `migrated_font_recent` | 是 |
| `gg_server_initialized` | 是 |
| `migrated_owner_id` | 是 |
| `migrated_ad_reports_dedup_v2` | **否** |
| `migrated_ad_reports_dedup_v3` | **否** |
| `migrated_product_runners_v2` | **否** |
| `migrated_mcc_dedup` | **否** |
| `migrated_mcc_share_runners` | **否** |

如果用户 A 导入了一个包含这些 key 的 config 数据，这些迁移标记可能被错误覆盖，导致数据库启动时重复执行迁移。建议将缺失的键补充到 `GG_CONFIG_KEYS`。

---

### E. 风险与建议汇总

| 风险等级 | 问题 | 建议 |
|----------|------|------|
| **中** | copywritings 从共享池变为用户私有，与设计不符 | 明确产品决策：如果是故意的设计变更，更新设计文档；否则修改代码恢复共享池行为 |
| **中** | 产品合并未迁移 accounts/mcc 关联，导致孤儿数据 | 在 `products_merge()` 中增加 `UPDATE accounts SET mcc_id=...` 逻辑 |
| **中** | 导入时 product_runners 表未同步，存在时间窗口不一致 | 在 `execute_import()` 的 products 导入循环中增加 `INSERT INTO product_runners` |
| **中** | GG_CONFIG_KEYS 不完整，可能被导入覆盖 | 补充 5 个缺失的迁移标记键 |
| **低** | CLI 和管理员 API 的导入不记录 import_history | 在 `cmd_import()` 和 `admin_data_import()` 中增加 import_history INSERT |
| **低** | GET /api/data/import/preview 未暴露 | 在 main.py 添加路由，调用已有的 `preview_import()` |
| **低** | video_history/video_tasks 导出未按 owner 过滤 | 确认设计意图后，决定是否添加 owner_id 过滤或标注为共享数据 |
| **信息** | `migrate_from_production.py` 未弃用/删除 | 按设计执行弃用（标注注释 + 确认 manage.py 完全覆盖其功能后删除） |
| **信息** | `db_version` 统一版本键未实现 | 当前功能粒度标记方案可行，但建议在设计文档中更新说明，标注为"已变更" |
