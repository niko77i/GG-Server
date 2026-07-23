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

---

## 7. 审计补充（2026-07-23）

以下基于 `py/main.py` 第 162-1755 行及 `frontend/src/views/YoutubeView.vue`、`frontend/src/stores/youtube.js`、`frontend/src/api/youtube.js` 的实时代码比对。

### 7.1 设计与实现一致的部分

| 条目 | 设计描述 | 代码位置 | 状态 |
|------|---------|----------|------|
| 后端 `uploader_id` 筛选参数 | `request.args.get("uploader_id")` → `WHERE v.owner_id = ?` | `main.py:1706-1707` | 一致 |
| SQL JOIN users 表 | `LEFT JOIN users u ON v.owner_id = u.id`，返回 `owner_display_name` / `owner_username` | `main.py:1709` | 一致（另有额外 JOIN，见 7.2.1） |
| `youtube_dates()` 增加 `uploader_id` 筛选 | 透传参数 | `main.py:1744, 1754-1755` | 一致 |
| Store `filters` 新增 `uploader_id: ''` | Pinia state | `youtube.js:10` | 一致 |
| 上传者下拉框 | `el-select` 绑定 `store.filters.uploader_id`，`@change="loadVideos"` | `YoutubeView.vue:21-23` | 一致（详见 7.2.3） |
| 视频行显示上传者标签 | `el-tag type="warning" v-if="row.owner_display_name"` | `YoutubeView.vue:98` | 基本一致，细节差异见 7.2.4 |
| `counts.uploader` 返回结构 | `{owner_id: {display_name, cnt}}` | `main.py:1722-1727` | 一致 |

### 7.2 设计与实现的差异

#### 7.2.1 SQL 查询额外 JOIN 了 `video_consumption` 子查询（设计未覆盖）

**设计文档（3.1.1.A）** 仅描述了 `LEFT JOIN users`。实际代码（`main.py:1709`）的 SQL 为：

```sql
SELECT v.*, u.display_name AS owner_display_name, u.username AS owner_username,
       COALESCE(vc.total_consumption, 0) AS total_consumption
FROM videos v
LEFT JOIN users u ON v.owner_id = u.id
LEFT JOIN (SELECT video_id, SUM(amount) AS total_consumption
           FROM video_consumption GROUP BY video_id) vc ON v.id = vc.video_id
```

多了一个对 `video_consumption` 的子查询 JOIN，为每条视频附加 `total_consumption` 字段。这是消耗追踪功能所需的，与上传者标签/筛选无直接关系，但在同一条 SQL 中完成。

**影响**：无功能影响，但文档未反映真实 SQL 结构。

#### 7.2.2 上传者计数实现方式：从"单独查询"变为"遍历内存计算"

**设计文档（3.1.1.C）** 明确写明"单独查询"：

> ```python
> counts["uploader"] = {}
> # 单独查询: SELECT v.owner_id, u.display_name, COUNT(*)
> #   FROM videos v LEFT JOIN users u ...
> ```

**实际代码（`main.py:1716-1727`）** 完全未使用单独查询，而是在已获取的 `videos` 列表上直接遍历：

```python
counts = {"region": {}, "frame_type": {}, ..., "uploader": {}}
for v in videos:
    for field in ["region", "frame_type", ...]:
        ...  # 其他字段正常计数
    # uploader 计数：用 owner_id 作为 key，存 display_name 和 count
    oid = v.get("owner_id")
    if oid:
        if oid not in counts["uploader"]:
            dname = v.get("owner_display_name") or v.get("owner_username") or f"用户{oid}"
            counts["uploader"][oid] = {"display_name": dname, "cnt": 0}
        counts["uploader"][oid]["cnt"] += 1
```

**差异分析**：
- 设计方案的独立 SQL 可以只统计上传者，不受其他条件影响（提供全局概览）。
- 实际方案的上传者计数完全依赖已筛选的视频结果集，即**不同筛选条件下 uploader 下拉框的选项会动态变化**——只显示当前结果集中出现的上传者。这是合理的选择，因为用户已选了 scope/地区/产品等条件后，下拉框应只显示有效选项。
- 需要注意：当筛选条件选中后，`uploader` 计数只反映该筛选下的分布，不反映全局。这与其他 count 字段（`region`、`frame_type` 等）的行为一致。

#### 7.2.3 上传者下拉框选项使用 `Number(id)` 转换键类型

**设计文档（3.2.2.B）** 使用 `el-option v-for="u in uploaderOptions"`（数组），`label="u.label"`、`value="u.id"`。

**实际代码（`YoutubeView.vue:21-23`）**：

```html
<el-select v-model="store.filters.uploader_id" @change="loadVideos"
  placeholder="全部上传者" clearable size="small" style="flex:1;min-width:110px;">
  <el-option v-for="(info, id) in store.counts.uploader" :key="id"
    :label="info.display_name + ' (' + info.cnt + ')'" :value="Number(id)" />
</el-select>
```

**差异**：
- 遍历对象而非数组：`v-for="(info, id) in store.counts.uploader"`，直接迭代 `counts.uploader` 对象。
- `:value="Number(id)"`：对象 key 在 JavaScript 中强制转为字符串，而 `store.filters.uploader_id` 初始值为空字符串 `''`，后端期望 `int`。`Number(id)` 将字符串 key 转回数字，确保 `v-model` 绑定值与 option value 类型匹配。
- 格式为 `display_name (cnt)`，如 `张三 (12)`，与设计描述一致。

#### 7.2.4 上传者标签样式微调：去掉了 👤 emoji，增加了 `effect="plain"`

**设计（3.2.2.C）**：
```html
<el-tag size="small" type="warning" v-if="row.owner_display_name">
  👤 {{ row.owner_display_name }}
</el-tag>
```

**代码（`YoutubeView.vue:98`）**：
```html
<el-tag size="small" type="warning" v-if="row.owner_display_name" effect="plain">
  {{ row.owner_display_name }}
</el-tag>
```

**差异**：
- 去掉了 `👤` emoji 前缀。
- 增加了 `effect="plain"`，使标签显示为浅色背景 + 深色文字，视觉上比纯色填充标签更轻量。

#### 7.2.5 未使用 `/api/users/names` 接口加载用户列表

**设计（3.2.2.A）** 明确提到两种方案，首选在 `onMounted` 中调用 `/api/users/names`：

> "在 `onMounted` 中调用 `/api/users/names`，存储到 `userList` ref，供上传者下拉框使用。或者直接用 `store.counts.uploader` 来构建下拉选项（包含计数）。"

**实际代码**（`YoutubeView.vue:471-481`）完全采用第二种方案——直接使用 `store.counts.uploader`。`/api/users/names` 接口未被 YoutubeView 调用。

**原因判断**：第二种方案避免了额外 HTTP 请求，且 `counts.uploader` 天然携带当前筛选项下的计数信息，是更优选择。设计文档的"首选方案"未被执行。

#### 7.2.6 `canModifyVideo` — 设计未涉及的权限逻辑

虽然不属于本需求范围，但 `YoutubeView.vue:491` 及 `main.py:1768-1789` 的 `_can_modify()` 权限函数依赖于 `owner_id`：

```javascript
function canModifyVideo(row) {
  return authStore.isAdmin || row.owner_id === authStore.user?.id || row.is_public
}
```

普通用户只能编辑自己上传的视频或公开视频，admin/developer 可以编辑所有。这与 `owner_id` 字段的存在密切相关，但设计文档中未提及此权限约束。

### 7.3 审核状态筛选默认值

Store 中 filters 的默认值为 `review_status: '能过审'`（`youtube.js:10`），这意味着用户打开页面时的默认筛选是"只看能过审的视频"。这与设计文档中提到的"公有/私有切换"配合上传者筛选的场景一致，但设计未明确 review_status 默认值的存在。后端在 `review_status and review_status != "全部"` 时才添加 WHERE 条件（`main.py:1695`）。

### 7.4 总结

整体而言，代码实现了设计文档中的所有核心功能（上传者标签显示、上传者筛选下拉框、后端 JOIN + 过滤），但有以下几个实际执行的偏差：

1. **SQL 比设计多了一个 JOIN**（`video_consumption` 消耗汇总），属于相邻功能的合并。
2. **上传者计数从"独立 SQL"改为"内存遍历"**，使计数与其他筛选联动，是一个合理的架构选择。
3. **前端 UI 细节调整**（去掉 emoji、加 `effect="plain"`），属于视觉层面的微调。
4. **未使用 `/api/users/names`**，直接用 API 返回的 counts 数据，减少了请求数。

无阻塞性偏差，所有功能均已按预期交付。
