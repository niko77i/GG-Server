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
