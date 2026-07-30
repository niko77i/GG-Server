# 视频展示所属 YouTube 频道 + 按频道筛选

## 需求

1. 视频列表中展示每个视频所属的 YouTube 频道名
2. 筛选栏增加按频道名搜索/过滤

## 现状

- `videos` 表无频道相关字段
- 导入时 oEmbed API 返回 `author_name`（频道名），但只取了 `title`，丢弃了频道信息
- `accounts` 表是 Google Ads 账户，与 YouTube 频道无关

## 技术方案

### 1. 数据库 — 新增 `channel_name` 列

**文件**: `py/database.py` — 在 `_run_column_migrations` 中新增：

```python
_add_column_if_missing(conn, "videos", "channel_name", "channel_name TEXT DEFAULT ''")
```

存量视频 `channel_name` 为空字符串。

### 2. 后端 — 导入时提取频道名

**文件**: `py/main.py` — `_batch_import_videos` 函数

oEmbed 接口 `https://www.youtube.com/oembed?url=...&format=json` 返回：

```json
{ "title": "...", "author_name": "频道名", "author_url": "https://..." }
```

修改 `_fetch_title` 函数，同时返回 `author_name`：

```python
def _fetch_title(vid):
    try:
        r = _requests.get(
            f"https://www.youtube.com/oembed?url=https://www.youtube.com/watch?v={vid}&format=json",
            timeout=8
        )
        if r.status_code == 200:
            data = r.json()
            return vid, data.get("title", vid), data.get("author_name", "")
    except Exception:
        pass
    return vid, vid, ""
```

INSERT 语句增加 `channel_name` 字段。

### 3. 后端 — 列表 API 增加频道筛选

**文件**: `py/main.py` — `youtube_list` 函数

- 查询参数新增 `channel_name` 筛选
- SQL 增加 `WHERE v.channel_name LIKE ?` 条件
- counts 聚合新增 `channel_name` 维度
- 返回字段包含 `channel_name`

### 4. 后端 — 批量补全存量视频频道名

**文件**: `py/main.py` — 新增 `POST /api/youtube/backfill-channels` 接口

对 `channel_name = ''` 的视频，复用 **oEmbed 公开接口**（无需 API Key）逐个查询 `author_name`，更新入库。oEmbed 无官方并发限制，可用线程池加速。

```python
@app.route("/api/youtube/backfill-channels", methods=["POST"])
@jwt_required()
def youtube_backfill_channels():
    # 查询 channel_name='' 的视频
    # 逐视频调用 oEmbed → 提取 author_name → UPDATE
    # 返回补全数量
```

### 5. 前端 — 展示 + 筛选

**文件**: `frontend/src/views/YoutubeView.vue`

- 视频标题下方 meta 行新增频道标签：`<el-tag size="small" type="info" effect="plain">📺 频道名</el-tag>`
- 筛选栏新增频道下拉框：`<el-select v-model="store.filters.channel_name" filterable>`，选项来自 `store.counts.channel_name`
- Store 增加 `channel_name` 到 filters、counts

**文件**: `frontend/src/stores/youtube.js`

- filters 增加 `channel_name: ''`
- counts 解析新增 `channel_name` 维度

## 涉及文件

| 文件 | 改动 |
|---|---|
| `py/database.py` | 新增 `channel_name` 列迁移 |
| `py/main.py` | 修改 `_batch_import_videos`，修改 `youtube_list`，新增 `backfill_channels` |
| `frontend/src/stores/youtube.js` | filters/counts 增加 `channel_name` |
| `frontend/src/views/YoutubeView.vue` | 展示频道标签 + 筛选下拉框 |

## 数据流

```
导入视频 URL
  → oEmbed API → author_name（频道名）
  → INSERT videos (channel_name=频道名)

列表展示
  → GET /api/youtube/list?channel_name=xxx
  → 返回 videos[].channel_name + counts.channel_name
  → 前端：tag 展示 + 下拉筛选

存量补全
  → POST /api/youtube/backfill-channels
  → 批量查 YouTube Data API v3
  → UPDATE videos SET channel_name=?
```
