# YouTube 视频管理功能 — 设计规格

**日期**: 2026-06-09
**状态**: 设计完成，待审核

---

## 1. 概述

在左侧侧边栏新增「📺 视频管理」标签页，用于管理 YouTube 视频链接。支持导入、分类、播放。

## 2. 面板结构

```
┌──────────────┬──────────────────────────────────────────┐
│  Sidebar     │  视频管理面板                              │
│              │  ┌─ 标签页 ──────────────────────────┐    │
│  📥 图片爬取  │  │ [ 📺 视频展示 ] [ ➕ 导入视频 ] │    │
│  🎬 AI 视频  │  └──────────────────────────────────┘    │
│  🎵 音频替换  │                                          │
│  📺 视频管理  │  (根据选中的子标签页显示不同内容)           │
│              │                                          │
└──────────────┴──────────────────────────────────────────┘
```

## 3. 子标签页 1：视频展示

- 从 `temp/youtube_videos.json` 加载已保存的视频列表
- 左侧显示视频列表（可滚动），每个条目显示：**名称、链接（截断）、地区标签、帧类型标签**
- 点击列表中的视频 → 右侧嵌入 YouTube iframe 播放器
- 播放器下方显示：完整链接、名称、地区、帧类型
- 视频列表支持按地区/帧类型筛选

## 4. 子标签页 2：导入视频

- 多行文本输入框，用于粘贴 YouTube 链接（每行一个）
- 地区下拉框：巴西 / 菲律宾 / 孟加拉 / 印尼 / 东南亚通用 / 通用
- 帧类型下拉框：融帧 / 非融帧
- 保存按钮 → 存储到本地 `temp/youtube_videos.json`
- 保存成功自动刷新视频展示列表

## 5. 数据存储

**位置**: `temp/youtube_videos.json`

```json
[
  {
    "id": "mpfKMV9PCKs",
    "url": "https://www.youtube.com/watch?v=mpfKMV9PCKs",
    "title": "视频标题",
    "region": "巴西",
    "frame_type": "融帧",
    "imported_at": "2026-06-09 12:00"
  }
]
```

- YouTube 视频 ID 从 URL 中提取
- 视频标题通过 YouTube oEmbed API 获取（`https://www.youtube.com/oembed?url=...`）
- 持久化：开发模式存在 `temp/`，EXE 模式存在 EXE 同目录

## 6. 后端 API

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/youtube/import` | 批量导入视频链接，提取 ID + 标题 |
| GET | `/api/youtube/list` | 返回所有已保存的视频 |
| POST | `/api/youtube/delete` | 删除指定视频 |
| GET | `/api/youtube/title?url=` | 获取视频标题 |

## 7. 文件变更

| 文件 | 变更 |
|------|------|
| `index.html` | 新增侧边栏项 + 视频管理面板 + 子标签页 |
| `css/style.css` | 新增视频面板样式（列表、播放器、筛选栏） |
| `js/youtube.js` | 新建，视频管理前端逻辑 |
| `py/main.py` | 新增 4 个 API 端点 |
| `js/app.js` | switchTab 增加 youtube 支持 |

## 8. 子标签页切换

视频管理面板内部有自己的子标签页（视频展示 / 导入视频），与外层侧边栏标签页独立。使用类似 `switchTab` 的模式，新增 `switchYoutubeTab(subtab)` 函数。

## 9. YouTube URL 提取

支持以下格式：
- `https://www.youtube.com/watch?v=VIDEO_ID`
- `https://youtu.be/VIDEO_ID`
- `https://www.youtube.com/embed/VIDEO_ID`
- `https://m.youtube.com/watch?v=VIDEO_ID`
- 带参数的 `?v=ID&t=123&list=...`

## 10. 验证

1. 切换到 📺 视频管理标签页
2. 点击「➕ 导入视频」，粘贴 YouTube 链接，选地区+帧类型，保存
3. 切换到「📺 视频展示」，确认视频出现在列表中
4. 点击视频 → 右侧嵌入播放器可播放
5. 切换地区/帧类型筛选，确认列表过滤正确

---

## 附录 A：审计补充（2026-07-23）

> 以下内容基于代码实际实现与原始设计文档的逐项对比。标记 [新增] 为设计文档未覆盖但已实现的功能；标记 [变更] 为设计有述但与实现不一致的部分；标记 [废弃] 为设计中规划但最终未采用的内容。

### A.1 面板结构 [变更]

设计文档规划了两个子标签页：「视频展示」和「导入视频」。实际实现扩展为**四个**子标签页，通过 Vue Router (`/youtube/view`、`/youtube/copywriting`、`/youtube/import`、`/youtube/config`) 进行切换：

| 子标签页 | 设计文档 | 实际实现 |
|----------|---------|---------|
| Youtube视频展示 | 有（视频展示） | 有，更名为"Youtube视频展示" |
| 文案展示 | **无** | [新增] 管理广告文案，支持按地区分组、翻译、批量编辑 |
| 导入视频或文案 | 有（仅导入视频） | [变更] 扩展为视频导入 + 文案导入两个子标签 |
| 标签配置 | **无** | [新增] 动态配置地区/帧类型/成效/产品名/审核状态的选项列表 |

### A.2 数据存储 [变更]

**设计文档**：规划使用 `temp/youtube_videos.json` 作为 JSON 文件存储。

**实际实现**：所有数据存储在 SQLite 数据库 `temp/app.db` 的 `videos` 表中，属于系统级统一数据库迁移的一部分。具体迁移路径：

1. 初始阶段使用了独立的 `temp/youtube.db`（SQLite）
2. 随后通过 `_migrate_youtube_db()` 函数将 `youtube.db` 的表和数据迁移到 `app.db`
3. 也支持从旧版 `temp/youtube_videos.json.backup` 迁移的兼容路径

### A.3 数据库表结构 [变更]

`videos` 表实际 schema（定义于 `py/database.py::_ensure_schema()`）：

```sql
CREATE TABLE IF NOT EXISTS videos (
    id TEXT PRIMARY KEY,              -- YouTube 视频 ID (11位)
    url TEXT,                          -- 完整 YouTube URL
    title TEXT,                        -- 视频标题（通过 oEmbed 获取）
    region TEXT DEFAULT '通用',         -- 地区标签
    frame_type TEXT DEFAULT '非融帧',   -- 帧类型标签
    effectiveness TEXT DEFAULT '',      -- [新增] 成效标记：成效/一般/空
    product_name TEXT DEFAULT '',       -- [新增] 关联产品名
    review_status TEXT DEFAULT '能过审', -- [新增] 审核状态：能过审/不能过审
    imported_at TEXT                    -- 导入时间
);
```

后续通过 `_ensure_columns()` 增量迁移新增的字段：

| 字段 | 默认值 | 说明 |
|------|--------|------|
| `review_status` | `'能过审'` | [新增] 审核状态 |
| `owner_id` | NULL (后迁移为 1) | [新增] 数据归属用户 ID，外键关联 `users(id)` |
| `is_public` | `0` | [新增] 可见性：0=私有, 1=公开（公用） |

### A.4 后端 API 完整清单 [变更]

设计文档列出 4 个 API 端点。实际实现共 **16+ 个端点**（所有端点均受 `@jwt_required()` 保护）：

#### 视频 CRUD（部分与设计一致，部分新增）

| 方法 | 路径 | 设计 | 实际 | 说明 |
|------|------|------|------|------|
| POST | `/api/youtube/import` | 有 | 有 | [变更] 增加了 effectiveness、product_name、review_status、imported_at、is_public 参数 |
| GET | `/api/youtube/list` | 有 | 有 | [变更] 增加了 scope、effectiveness、product_name、review_status、from_date、to_date、uploader_id 筛选参数；返回 JOIN 了 total_consumption 和 owner 信息 |
| POST | `/api/youtube/delete` | 有 | 有 | [变更] 增加了权限校验（owner_id/is_public），同时清理 product_assets 和 video_consumption 关联数据 |
| GET | `/api/youtube/title?url=` | 有 | **已废弃** | 标题获取已内嵌到 import 流程的 `_batch_import_videos()` 中，使用 ThreadPoolExecutor 并行 oEmbed |
| POST | `/api/youtube/edit` | **无** | [新增] | 单个视频字段编辑，含权限校验 |
| POST | `/api/youtube/batch-edit` | **无** | [新增] | 批量修改选定视频的 region/frame_type/effectiveness/product_name/review_status/is_public |
| GET | `/api/youtube/dates` | **无** | [新增] | 返回当前筛选条件下有视频的日期分布（供日期选择器标记） |

#### 标签配置 [新增]

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/youtube/tags` | 获取 regions/frame_types/effectiveness/product_names/review_statuses 标签选项 |
| POST | `/api/youtube/tags` | 保存标签配置，支持重命名（自动更新已关联视频）和删除（返回受影响视频列表） |

#### 消耗追踪 [新增]

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/youtube/<vid>/consumption` | 获取视频的消耗明细，按用户分组聚合（所有角色可查看） |
| POST | `/api/youtube/<vid>/consumption` | 新增消耗记录（仅 admin/developer，且只能给自己添加） |
| PUT | `/api/youtube/<vid>/consumption/<cid>` | 编辑消耗记录（仅记录 owner 本人） |
| DELETE | `/api/youtube/<vid>/consumption/<cid>` | 删除消耗记录（仅记录 owner 本人） |
| GET | `/api/youtube/consumption/dates` | 返回有消耗记录的日期分布 |

消耗数据存储在 `video_consumption` 表（定义于 `py/database.py`），字段包含 `video_id`、`user_id`、`product_id`、`amount`、`consume_date`。

#### 成效素材关联 [新增]

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/youtube/asset-products` | 返回有成效素材关联的产品名列表（供筛选下拉框） |
| GET | `/api/youtube/product-assets` | 批量查询视频关联的产品名映射，参数 `video_ids`（逗号分隔） |
| DELETE | `/api/products/<pid>/assets/<video_id>` | 移除产品的成效素材关联 |

关联关系存储在 `product_assets` 表（`product_id` + `video_id` 联合唯一）。

#### 文案管理 API [新增]

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/copywriting/list` | 获取文案列表，支持 scope/region 筛选 |
| POST | `/api/copywriting/import` | 批量导入文案（按行分割），支持 region、effectiveness、is_public |
| POST | `/api/copywriting/edit` | 单条文案编辑（region、effectiveness、content） |
| POST | `/api/copywriting/delete` | 批量删除文案 |
| POST | `/api/copywriting/batch-edit` | 批量修改文案的 region/effectiveness |

文案数据存储在 `copywritings` 表（字段：`id`、`region`、`content`、`owner_id`、`effectiveness`、`is_public`、`created_at`）。

### A.5 前端架构 [变更]

**设计文档**：基于 jQuery/原生 JS 的单页应用架构，规划修改 `index.html`、`css/style.css`、`js/youtube.js`、`js/app.js`。

**实际实现**：基于 **Vue 3 + Element Plus + Pinia** 的 SPA 架构，文件分布如下：

| 文件 | 说明 |
|------|------|
| `frontend/src/views/YoutubeView.vue` | 主视图组件（~850 行），包含视频展示、消耗弹窗、视频编辑弹窗、文案管理（内联） |
| `frontend/src/components/youtube/ImportTab.vue` | 导入子组件，支持视频导入 + 文案导入两个子标签 |
| `frontend/src/components/youtube/TagsConfig.vue` | 标签配置子组件，管理各区下拉框的选项列表 |
| `frontend/src/components/youtube/CopywritingTab.vue` | 文案展示子组件，含翻译、编辑等完整功能 |
| `frontend/src/stores/youtube.js` | Pinia 状态管理，管理 videos/copywritings/tags/filters 等状态 |
| `frontend/src/api/youtube.js` | API 客户端模块，封装 youtubeApi、copywritingApi、consumptionApi、productApi、translateApi |

### A.6 导入功能 [变更]

**设计文档**：
- 多行文本框 + 两个下拉框（地区、帧类型）
- 保存到 JSON 文件

**实际实现**：
- 多行文本框（支持换行或逗号分隔）+ **五个**下拉框（地区、帧类型、成效、产品名、审核状态）+ 日期选择器 + 公开/私有可见性切换
- 通过 `_batch_import_videos()` 函数批量处理：先批量查库去重 → 并行 ThreadPoolExecutor(5) 调用 YouTube oEmbed API 获取标题 → 批量 INSERT
- 返回导入数量和重复列表
- 支持用户指定导入时间（`imported_at` 参数）

### A.7 YouTube URL 格式支持 [变更]

设计文档列出的 5 种格式均已实现。额外增加了对 `youtube.com/shorts/` 格式的支持。

实际实现的正则表达式（`_extract_youtube_id()`）：
```python
r'(?:youtube\.com/watch\?v=|youtu\.be/|youtube\.com/embed/|youtube\.com/shorts/|m\.youtube\.com/watch\?v=)([a-zA-Z0-9_-]{11})'
```

### A.8 数据隔离与权限模型 [新增]

设计文档未涉及多用户场景。实际实现了一套完整的数据隔离模型：

- **`owner_id`**：每条视频/文案记录归属创建者
- **`is_public`**：0=私有（仅 owner 可见），1=公开（所有人可见）
- **`scope` 筛选**：`private`（仅自己的）、`public`（公开的）、`all`（自己的+公开的）
- **权限校验函数 `_can_modify()`**：admin/developer 全权；普通用户仅可操作自己的或公开记录
- **初始数据迁移**：所有历史数据的 `owner_id` 设为 developer（`user_id=1`）
- **批量编辑权限**：`is_public` 字段仅 owner 本人可修改（admin 也不例外）；其他字段 admin 可批量修改任意视频，普通用户仅可修改自己的或公开的

### A.9 视频列表排序规则 [新增]

视频列表按以下优先级排序（`/api/youtube/list` 的 ORDER BY）：
1. 审核状态：`不能过审` 排最后（`CASE WHEN '不能过审' THEN 1 ELSE 0 END`）
2. 成效：`成效` > `一般` > 其他
3. 导入时间：最新的在前

### A.10 筛选器功能 [新增]

视频展示页面提供以下筛选维度：
- **可见范围**（仅 admin）：公用 / 私有
- **上传者**：按 owner 筛选，下拉显示各上传者的视频数量
- **成效素材产品**：按关联的产品筛选
- **地区**：下拉显示各地区视频数量
- **帧类型**：下拉显示各类型视频数量
- **成效**：下拉显示各成效等级视频数量
- **产品名**：下拉显示各产品视频数量
- **审核状态**：能过审 / 不能过审 / 全部
- **日期范围**：日期选择器，日历格子标记有视频的日期（蓝点）和有消耗的日期（红点）

### A.11 其他未在设计中体现的功能 [新增]

1. **视频消耗追踪**：每个视频可按用户录入多条广告消耗记录，支持金额/日期/产品关联。消耗弹窗按用户分组展示，支持展开/折叠，含编辑和删除功能。视频列表的 total_consumption 通过 SQL 子查询实时聚合。

2. **成效素材关联**：可将视频关联到产品（通过 `product_assets` 表），在视频列表中显示关联的产品标签（🎬 图标），支持按产品筛选。该关联由产品管理模块维护。

3. **复制追踪**：通过 `localStorage` 记录哪些视频链接已被复制（`ytCopied` key），在列表中显示"已复制"标记。提供"选未复制"快捷按钮和清除复制记录功能。

4. **文案翻译**：文案展示 tab 内嵌了翻译功能，调用 `/api/translate` 接口。支持中文/英语/葡萄牙语/印尼语/菲律宾语/西班牙语/日语/韩语/泰语/越南语等目标语言，以绿色渐变的行内展开面板呈现译文。

5. **标签重命名与级联更新**：修改标签配置中的选项名时，会自动更新所有已关联同值视频（但仅限当前用户 owner 的视频）。删除标签值时，会列出受影响的视频供用户处理。

6. **分页与每页条数**：视频列表支持 10/20/50/100 条每页，带分页器。

### A.12 设计文档中已废弃的内容

| 内容 | 原因 |
|------|------|
| `/api/youtube/title?url=` 端点 | 标题获取已内嵌到 import 流程中，无需独立端点 |
| `temp/youtube_videos.json` 文件存储 | 已全面迁移到 SQLite，JSON 仅保留 `.backup` 作为迁移来源 |
| `switchYoutubeTab(subtab)` 函数 | 已改用 Vue Router 路由切换 |
| 原生 JS/jQuery 架构 | 已升级为 Vue 3 + Element Plus + Pinia |
