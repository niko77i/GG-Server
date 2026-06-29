# 视频上传者标签与筛选 — 设计文档

**日期**: 2026-06-27  
**状态**: 待确认

---

## 1. 需求描述

在 YoutubeView 视频展示页中：
1. 每条视频显示**上传者标签**（用 display_name），一眼看到谁上传的
2. 新增**上传者筛选下拉框**，可以按上传者过滤视频（配合公有/私有切换使用）

视频导入区已有公有/私有选择（`is_public`），也会自动记录 `owner_id`。

---

## 2. 现状分析

### 2.1 数据库

- `videos` 表已有 `owner_id INTEGER REFERENCES users(id)`（2026-06-26 迁移添加）
- `users` 表有 `id`, `username`, `display_name`, `role` 等字段

### 2.2 后端 API

- `GET /api/youtube/list`：返回 `SELECT * FROM videos`，每条视频包含 `owner_id` 但不含用户名
- `GET /api/users/names`：已存在，返回所有非 hidden 用户的 `[{id, username, display_name}]`
- `GET /api/youtube/dates`：日期分布，也按 scope 筛选

### 2.3 前端

- `youtube.js` store：`filters` 包含 `scope`, `region`, `frame_type`, `effectiveness`, `product_name`, `review_status`
- `YoutubeView.vue`：筛选栏有公有/私有切换 + 地区/帧类型/成效/产品/审核状态下拉框
- `ProductCard.vue` 已有加载 `/api/users/names` 并显示 runner 标签的先例

---

## 3. 技术方案

### 3.1 后端改动

#### 3.1.1 `GET /api/youtube/list` — 两处改动

**A. JOIN users 表获取上传者名称**

将 `SELECT * FROM videos` 改为 JOIN 查询，每条视频附加 `owner_display_name` 和 `owner_username`：

```sql
SELECT v.*, u.display_name AS owner_display_name, u.username AS owner_username
FROM videos v
LEFT JOIN users u ON v.owner_id = u.id
WHERE ...
```

这样前端无需二次查询即可直接显示上传者标签。

**B. 新增 `uploader_id` 筛选参数**

在 WHERE 条件中追加：
```python
uploader_id = request.args.get("uploader_id", "").strip()
if uploader_id:
    where.append("v.owner_id = ?"); params.append(int(uploader_id))
```

**C. 新增 uploader 计数**

在 counts 中增加 `uploader` 字段，统计当前 scope 下有视频的上传者及其视频数：
```python
counts["uploader"] = {}
# 单独查询: SELECT v.owner_id, u.display_name, COUNT(*) FROM videos v LEFT JOIN users u ...
```

这样筛选下拉框可以显示每个上传者有多少视频。

#### 3.1.2 `GET /api/youtube/dates` — 增加 `uploader_id` 筛选（保持一致性）

同样增加 `uploader_id` 参数透传。

### 3.2 前端改动

#### 3.2.1 Store (`youtube.js`)

在 `filters` 中新增：
```js
uploader_id: '',
```

#### 3.2.2 视图 (`YoutubeView.vue`)

**A. 加载用户列表**  
在 `onMounted` 中调用 `/api/users/names`，存储到 `userList` ref，供上传者下拉框使用。或者直接用 `store.counts.uploader` 来构建下拉选项（包含计数）。

**B. 新增上传者筛选下拉框**  
在筛选栏（公有/私有切换旁边）增加：
```html
<el-select v-model="store.filters.uploader_id" @change="loadVideos" 
  placeholder="全部上传者" clearable size="small" style="flex:1;min-width:110px;">
  <el-option v-for="u in uploaderOptions" :key="u.id" 
    :label="u.label" :value="u.id" />
</el-select>
```
选项来自 `store.counts.uploader`（每个上传者的视频数）。

**C. 视频标题行显示上传者标签**  
在 `video-title-meta` 中增加：
```html
<el-tag size="small" type="warning" v-if="row.owner_display_name">
  👤 {{ row.owner_display_name }}
</el-tag>
```

**D. 导入区**  
导入区已有 `owner_id` 自动设为当前用户，无需额外改动。当前用户上传的视频在私有模式下自然可见。

---

## 4. 涉及文件

| 文件 | 改动类型 |
|------|----------|
| `py/main.py` — `youtube_list()` | 修改 SQL 加 JOIN + uploader_id 筛选 + uploader 计数 |
| `py/main.py` — `youtube_dates()` | 增加 uploader_id 筛选参数 |
| `frontend/src/stores/youtube.js` | filters 增加 uploader_id |
| `frontend/src/views/YoutubeView.vue` | 增加上传者下拉框 + 标签显示 + 加载逻辑 |

---

## 5. UI 改动示意

### 筛选栏（新增上传者下拉框）

```
[🌐 公有] [🔒 私有]  [全部上传者 ▾]  [全部地区 ▾]  [全部帧类型 ▾]  ...
```

下拉选项格式：`用户名 (视频数)`，例如 `张三 (12)`

### 视频列表行（新增上传者标签）

```
视频标题文字
[地区标签] [帧类型] [成效] [产品] [审核] [👤 张三]  已复制  2026-06-27
```

---

## 6. 注意事项

1. **向后兼容**：旧视频 `owner_id` 可能为 NULL（迁移前数据），LEFT JOIN 后 `owner_display_name` 为 NULL，前端判断 `v-if="row.owner_display_name"` 即可
2. **权限**：普通用户只能看到自己有权限看到的视频（scope 控制），上传者下拉框的计数也只统计当前 scope 内的视频
3. **计数一致性**：uploader 计数需要遵循与其他 counts 相同的过滤逻辑（scope + 其他筛选条件，但不含 uploader_id 自身）
4. **性能**：COUNT 子查询在视频量不大（<10万）时无压力
