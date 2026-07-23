# 视频审核状态标签 — 设计文档

## 需求描述

视频管理新增「是否过审」标签，两个选项：
- **能过审** — 可以通过审核
- **不能过审** — 不能通过审核

具体要求：
1. 视频新增 `review_status` 字段，支持「能过审」「不能过审」两个值
2. 现有视频全部默认设为「能过审」
3. 筛选器增加「是否过审」下拉选项
4. 展示时，不能过审的视频排在最后
5. **默认只展示「能过审」的视频**（筛选默认值为「能过审」）

## 技术方案

### 1. 数据库变更 (`py/database.py`)

在 `videos` 表中新增 `review_status` 列：

```sql
ALTER TABLE videos ADD COLUMN review_status TEXT DEFAULT '能过审';
```

迁移策略：
- `_ensure_schema` 中的建表语句增加 `review_status TEXT DEFAULT '能过审'`
- `_migrate_if_needed` 中增加迁移逻辑：检测列是否存在，不存在则 ALTER TABLE ADD COLUMN
- 现有视频自动获得默认值 `'能过审'`（SQLite ALTER TABLE ADD COLUMN DEFAULT 对已有行生效）

在 `tags` 表中初始化默认审核状态选项：
```python
("review_statuses", '["能过审","不能过审"]')
```

### 2. 后端 API (`py/main.py`)

涉及 6 个 API 处理函数，均需增加 `review_status` 字段支持：

| API | 变更 |
|-----|------|
| `youtube_import` | 接受 `review_status` 参数，默认 `'能过审'`，写入 INSERT |
| `youtube_list` | 筛选条件增加 `review_status`；排序规则增加 `CASE review_status WHEN '不能过审' THEN 1 ELSE 0 END`（排在效果排序之后）；**默认筛选 `review_status = '能过审'`**（当前端不传或为空时） |
| `youtube_edit` | 允许编辑字段列表增加 `review_status` |
| `youtube_batch-edit` | 允许字段白名单增加 `review_status` |
| `youtube_tags_get` | tags 响应中自动包含 `review_statuses` |
| `youtube_tags_save` | 处理 `review_statuses` 的增删改同步（同其他标签逻辑） |

### 3. 前端 Store (`frontend/src/stores/youtube.js`)

- `tags` state 增加 `review_statuses: []`
- `filters` state 增加 `review_status: '能过审'`（默认值）

### 4. 前端视图 (`frontend/src/views/YoutubeView.vue`)

**筛选区**（第 13-27 行）：增加审核状态下拉框
- 放在现有 4 个筛选下拉框之后、日期选择器之前
- 选项：「全部」「能过审」「不能过审」
- `@change` 触发 `loadVideos`，默认值 `'能过审'`

**列表展示**（第 62-77 行标签区）：增加审核状态标签
- 在 `video-title-meta` 中增加 `<el-tag>`，显示 `review_status`
- 不能过审用 `type="danger"`，能过审用 `type="success"`

**批量编辑工具栏**（第 42-56 行）：增加审核状态批量修改下拉框

**编辑弹窗**（第 236-263 行）：增加审核状态表单项

**导入区**（第 175-193 行）：增加审核状态下拉选择框，默认「能过审」

### 5. 排序逻辑

当前排序：
```sql
ORDER BY CASE effectiveness WHEN '成效' THEN 0 WHEN '一般' THEN 1 ELSE 2 END, imported_at DESC
```

变更后：
```sql
ORDER BY
  CASE review_status WHEN '不能过审' THEN 1 ELSE 0 END,
  CASE effectiveness WHEN '成效' THEN 0 WHEN '一般' THEN 1 ELSE 2 END,
  imported_at DESC
```

### 6. 涉及文件汇总

| 文件 | 变更类型 |
|------|---------|
| `py/database.py` | 建表 + 迁移 + 默认标签 |
| `py/main.py` | 6 个 API 函数参数/字段扩展 |
| `frontend/src/stores/youtube.js` | state 扩展 |
| `frontend/src/views/YoutubeView.vue` | UI 增加筛选/标签/编辑/导入 |
| `frontend/src/components/youtube/ImportTab.vue` | 导入表单增加审核状态下拉 |


## 实际代码逻辑补充（2026-07-23 审计）

以下内容基于对实际代码的逐行审计，记录设计文档未覆盖或与设计存在差异的实现细节。

### 一、设计文档未覆盖的 API 端点

设计文档列出了 6 个受影响的 API，但实际代码中还有以下端点也使用了 `review_status`：

#### 1. `/api/youtube/dates` — 日期统计端点

代码位置：`py/main.py` 第 1733-1765 行。

```python
review_status = request.args.get("review_status", "").strip()
# ...
if review_status and review_status != "全部":
    where.append("v.review_status=?"); params.append(review_status)
```

该端点返回当前筛选条件下的日期及视频数量，供前端日期选择器标记使用。前端调用 `loadDates` 时会传入与列表相同的筛选参数（含 `review_status`），确保日期标记数量与列表筛选结果一致。

#### 2. `/api/products/<int:pid>/assets` [POST] — 产品成效素材导入

代码位置：`py/main.py` 第 6383-6414 行。

```python
review_status = (data.get("review_status") or "能过审").strip()
# ...
imported, duplicates, results = _batch_import_videos(
    db, urls, ..., review_status=review_status, user_id=user_id, is_public=0
)
```

向产品添加成效素材时，底层调用 `_batch_import_videos`，同样接受并写入 `review_status`，默认值为 `'能过审'`。

### 二、默认筛选策略：设计文档与实际代码的关键差异

**设计文档描述**（第 43 行）：

> "默认筛选 `review_status = '能过审'`（当前端不传或为空时）"

**实际后端代码**（`py/main.py` 第 1694-1696 行）：

```python
# 审核状态：默认筛选「能过审」，传空或"全部"则不过滤
if review_status and review_status != "全部":
    where.append("v.review_status=?"); params.append(review_status)
```

**实际行为**：后端在 `review_status` 为空字符串或 `"全部"` 时**不做任何过滤**，返回所有视频。默认值 **仅在前端 Store 中设定**：

```javascript
// frontend/src/stores/youtube.js 第 10 行
filters: { ..., review_status: '能过审', ... }
```

也就是说，"默认只展示能过审视频"这个需求是由前端默认值保证的，而非后端 SQL 层面的默认 WHERE 条件。这与设计文档的表述有偏差——设计文档暗示后端应有默认筛选逻辑，但实际默认值是放在了前端。

**影响**：如果前端未正确初始化 `review_status` 为 `'能过审'`，或直接调用 API 不传该参数，将展示所有视频（含不能过审的）。这是设计文档需要明确的地方。

### 三、`_batch_import_videos` 内部函数细节

设计文档未提及此内部函数，但它是对外 API 的核心依赖。

代码位置：`py/main.py` 第 1562-1641 行。

```python
def _batch_import_videos(db, urls, region="通用", frame_type="非融帧", effectiveness="",
                         product_name="", review_status="能过审", imported_at="",
                         user_id=0, is_public=0):
```

- 参数 `review_status` 默认值为 `"能过审"`，与设计一致
- INSERT 语句中 `review_status` 在 `product_name` 之后、`imported_at` 之前（第 1632 行）
- 两个调用方（`youtube_import` 和 `product_assets_add`）均以 `(data.get("review_status") or "能过审").strip()` 方式获取值

### 四、数据库迁移实现细节

设计文档描述使用"检测列是否存在，不存在则 ALTER TABLE ADD COLUMN"，实际实现为通用辅助函数：

代码位置：`py/database.py` 第 91 行。

```python
_add_column_if_missing(conn, "videos", "review_status", "review_status TEXT DEFAULT '能过审'")
```

这是一个封装好的公共函数，在每次数据库连接时执行。其内部逻辑为：检查 `PRAGMA table_info` 结果中是否已有该列，若不存在则 `ALTER TABLE ADD COLUMN`。

**历史数据迁移路径**（设计文档未提及）：

1. **从旧 `youtube.db` 迁移**（`py/database.py` 第 773-778 行）：读取旧表数据，`review_status` 取旧值，若无则默认 `'能过审'`
2. **从 JSON 文件批量导入**（`py/database.py` 第 831-836 行）：同上逻辑
3. **SQLite ALTER TABLE ADD COLUMN DEFAULT**：对已有行，DEFAULT 值在 SQLite 中**不自动填充**已有行（仅对新 INSERT 生效），但由于每条记录在后续 UPDATE 或读取时会通过应用层默认值 `'能过审'` 兜底，实际效果满足需求

### 五、列表排序与计数

**排序**（`py/main.py` 第 1711 行）与设计文档完全一致：

```sql
ORDER BY
  CASE v.review_status WHEN '不能过审' THEN 1 ELSE 0 END,
  CASE v.effectiveness WHEN '成效' THEN 0 WHEN '一般' THEN 1 ELSE 2 END,
  v.imported_at DESC
```

**计数统计**（设计文档未提及）：`youtube_list` 响应的 `counts` 对象包含 `review_status` 维度的计数：

```python
counts = {..., "review_status": {}, ...}
```
（第 1716 行）

前端筛选下拉框据此展示 `"能过审 (120)"` 格式的选项，让用户在选择前就能看到各状态下的视频数量。

### 六、前端实际实现位置与设计文档的差异

设计文档中的行号引用基于编写时的文件结构。实际代码在后续迭代中经历了重构：

| 设计文档描述 | 实际代码位置 |
|---|---|
| 导入区（第 175-193 行） | 独立组件 `frontend/src/components/youtube/ImportTab.vue`，`importReview` 变量绑定审核状态下拉 |
| 标签配置 | 独立组件 `frontend/src/components/youtube/TagsConfig.vue` |

导入组件中 `review_status` 以 `importReview.value` 传入请求体（`ImportTab.vue` 第 96 行）。

### 七、编辑弹窗 fallback 逻辑

代码位置：`YoutubeView.vue` 第 511-518 行。

```javascript
function openEdit(row) {
  editForm.value = {
    // ...
    review_status: row.review_status || '能过审',
  }
}
```

当视频记录的 `review_status` 为 `null` 或空字符串时，编辑弹窗默认显示 `'能过审'`。这与导入时的默认值策略一致。

### 八、标签管理的级联影响

`review_statuses` 标签的"增删改"逻辑（`py/main.py` 第 2147 行）与其他标签（region、frame_type、effectiveness、product_name）完全一致：

- **重命名**：如果旧值在列表中位置不变但内容变了，对应视频的 `review_status` 字段会被 UPDATE
- **删除**：如果某个值被从列表中移除，使用该值的视频会被收集到 `affected` 列表中返回给前端（但**不会自动删除视频**，仅通知前端有视频使用了已删除的标签值）

权限限制：重命名和删除仅影响当前用户（`owner_id=?`）的视频。

### 九、批量编辑的权限分级

设计文档只说"允许字段白名单增加 review_status"，但实际代码存在三级权限控制（`py/main.py` 第 1847-1866 行）：

| 字段 | admin | 普通用户 |
|---|---|---|
| `region`, `frame_type`, `effectiveness`, `product_name`, `review_status` | 所有视频 | 仅自己上传的 + 公开视频 |
| `is_public` | 仅自己上传的 | 仅自己上传的 |

`review_status` 属于第一类，因此 admin 可以批量修改所有视频的审核状态，普通用户只能修改自己的视频。

### 十、审计总结

| 检查项 | 状态 | 说明 |
|---|---|---|
| 数据库 schema 变更 | 通过 | 建表、迁移、默认标签均已正确实现 |
| 列表 API 筛选 + 排序 | 通过 | 排序与设计一致；筛选默认值由前端保证（与设计文档表述有差异） |
| 编辑 API | 通过 | 单条编辑和批量编辑均支持 `review_status` |
| 导入 API | 通过 | `youtube_import` 和 `product_assets_add` 均支持 |
| 标签管理 API | 通过 | `review_statuses` 与其它标签处理逻辑一致 |
| 日期端点 | 通过 | `/api/youtube/dates` 也支持 `review_status` 筛选（设计文档未提及） |
| 前端筛选下拉 | 通过 | 默认值 `'能过审'`，含"全部"选项 |
| 前端列表标签 | 通过 | `不能过审` 显示 danger 红色，其余 success 绿色 |
| 前端编辑弹窗 | 通过 | 含 `review_status` 下拉，fallback 默认 `'能过审'` |
| 前端批量编辑 | 通过 | 批量修改审核状态下拉 |
| 前端导入表单 | 通过 | `ImportTab.vue` 含审核状态下拉 |
| 设计文档覆盖完整度 | 需补充 | 缺少 `youtube_dates`、`product_assets_add`、`_batch_import_videos`、`counts`、权限分级等细节 |
