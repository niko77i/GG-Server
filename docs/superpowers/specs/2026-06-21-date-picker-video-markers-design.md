# 日期选择器视频标记 — 设计规格

**日期**: 2026-06-21  
**状态**: 待实现

## 需求描述

在 YouTube 视频管理页面的日期选择器（`el-date-picker type="daterange"`）中，将实际存在视频的日期标记出来，方便用户快速定位有数据的日期范围。

## 视觉效果

- 有视频的日期：**浅蓝色背景** + 日期数字下方**小蓝圆点**
- 无视频的日期：保持 Element Plus 默认样式

## 技术方案

### Element Plus 支持

`el-date-picker` 提供 `cell-class-name` 属性：

```html
<el-date-picker
  :cell-class-name="dateCellClass"
  ...
/>
```

```js
function dateCellClass(date) {
  // date 是 Date 对象
  const key = toDateKey(date) // "2026-06-21"
  return dateSet.has(key) ? 'has-video' : ''
}
```

### 数据流

```
前端 onMounted → GET /api/youtube/dates
  → 返回 {"success": true, "dates": {"2026-06-01": 5, "2026-06-02": 3, ...}}
  → 前端转为 Set 用于 cell-class-name 判断
  → CSS 对 .has-video 类名添加背景色 + 圆点
```

### 涉及文件

| 层 | 文件 | 改动 |
|----|------|------|
| 后端 | `py/main.py` | 新增 `GET /api/youtube/dates` |
| 前端 API | `frontend/src/api/youtube.js` | 新增 `dates()` 方法 |
| 前端 Store | `frontend/src/stores/youtube.js` | 新增 `videoDates` 状态 + `loadDates()` action |
| 前端视图 | `frontend/src/views/YoutubeView.vue` | `cell-class-name` 属性 + CSS |

### 后端 API

**GET /api/youtube/dates**

返回所有有视频的日期及数量（不受筛选条件影响）：

```sql
SELECT substr(imported_at, 1, 10) AS date, COUNT(*) AS cnt
FROM videos
GROUP BY date
ORDER BY date DESC
```

响应：
```json
{
  "success": true,
  "dates": { "2026-06-21": 5, "2026-06-20": 3, "2026-06-19": 8 }
}
```

### CSS 样式

```css
/* 日期选择器中有视频的日期：浅蓝背景 + 圆点 */
:deep(.has-video .el-date-table-cell__text) {
  position: relative;
}
:deep(.has-video .el-date-table-cell__text)::after {
  content: '';
  position: absolute;
  bottom: 2px;
  left: 50%;
  transform: translateX(-50%);
  width: 4px;
  height: 4px;
  border-radius: 50%;
  background: #409eff;
}
:deep(.has-video) {
  background: #ecf5ff;
}

---

## 审计补充（2026-07-23）：设计文档 vs 实际代码差异

以下为代码已实现但设计文档未覆盖或描述有偏差的部分。

### 1. 后端 `/api/youtube/dates` 实际受筛选条件影响

设计文档写道"不受筛选条件影响"，但实际代码（`py/main.py` 第 1733-1765 行）从 query string 接收并应用了以下筛选参数：

- `scope`（`all` / `public` / `private`）
- `region`
- `frame_type`
- `effectiveness`
- `product_name`
- `review_status`
- `uploader_id`

所有这些参数均被加入 SQL WHERE 子句中。每次用户切换筛选条件时，前端会重新调用 `loadDates(store.filters)` 刷新日期标记数据。

### 2. 第二套日期标记：消耗日期（设计文档未提及）

实际代码存在一套完整的"消耗日期标记"机制，设计文档完全未涉及。包括：

**后端新端点**：`GET /api/youtube/consumption/dates`（`py/main.py` 第 2079-2105 行）
- 查询 `video_consumption` 表 JOIN `videos` 表
- 按 `scope` 参数过滤（仅传 scope，不传其他筛选条件）
- 返回格式与 `/api/youtube/dates` 相同：`{"success": true, "dates": {"2026-07-22": 3, ...}}`

**前端 API 层**：`consumptionApi.dates(params)`（`frontend/src/api/youtube.js` 第 27 行）
- 调用 `GET /api/youtube/consumption/dates`，传 `{ scope }` 参数

**前端组件新增**（`YoutubeView.vue`）：
- `consumptionDates` ref（第 324 行）
- `consumptionDateSet` computed（第 349 行）：从 `consumptionDates` 提取 key 集合
- `loadConsumptionDates()` 函数（第 341-346 行）：调用 `consumptionApi.dates()` 并写入 `consumptionDates`
- `dateCellClass()` 函数（第 308-316 行）同时检查两个集合：

```js
function dateCellClass(date) {
  const key = `${y}-${m}-${d}`
  if (dateSet.value.has(key)) return 'has-video'     // 有视频 → 蓝点
  if (consumptionDateSet.value.has(key)) return 'has-consumption'  // 仅消耗 → 红点
  return ''
}
```

注意优先级：视频标记优先于消耗标记（如果某天既有视频又有消耗，只显示蓝色视频标记）。

### 3. `loadDates` 调用时机与参数传递

设计文档描述：

```
onMounted → GET /api/youtube/dates
```

实际代码在两处调用 `loadDates`，且均传入筛选参数：

- `onMounted`（第 477-478 行）：`store.loadDates(store.filters)`
- `loadVideos()`（第 446 行）：`store.loadDates(store.filters)`

`loadVideos()` 在以下场景被调用：筛选条件变化、删除视频、编辑视频、提交消耗记录、删除消耗记录。每次 `loadVideos()` 都会连带刷新日期标记。

`loadConsumptionDates()` 在以下场景被调用：`loadVideos()` 内部（第 448 行）、`submitConsumption()` 成功后（第 401 行）、`deleteConsumptionRec()` 成功后（第 431 行）。

### 4. CSS 实现方式与设计文档不同

设计文档使用 scoped `:deep()` 写法：

```css
:deep(.has-video .el-date-table-cell__text) { ... }
```

实际代码使用**非 scoped 独立 `<style>` 块** + `popper-class` 属性（第 814-849 行）：

```css
.yt-date-picker .has-video { background: #ecf5ff; }
.yt-date-picker .has-video .el-date-table-cell__text { ... }
.yt-date-picker .has-video .el-date-table-cell__text::after { ... }
```

原因：Element Plus 的 `el-date-picker` 面板通过 Teleport 挂载到 `<body>` 下，不在组件 DOM 树内，scoped CSS（包括 `:deep()`）无法穿透到 Teleport 出去的元素。正确做法是：

1. 在 `<el-date-picker>` 上设置 `popper-class="yt-date-picker"`（第 44 行）
2. 在非 scoped `<style>` 块中用 `.yt-date-picker` 作为命名空间前缀

### 5. 消耗日期专用 CSS（设计文档未提及）

非 scoped 样式中新增 `.has-consumption` 类（第 832-848 行）：

```css
.yt-date-picker .has-consumption { background: #fef0f0; }            /* 浅红背景 */
.yt-date-picker .has-consumption .el-date-table-cell__text::after {
  background: #f56c6c;  /* 红色圆点，区别于视频的蓝色 */
}
```

### 6. 涉及文件清单更新

设计文档列了 4 个文件，实际还涉及：

| 层 | 文件 | 改动 |
|----|------|------|
| 后端 | `py/main.py` | 新增 `GET /api/youtube/consumption/dates`（设计文档未覆盖） |
| 前端 API | `frontend/src/api/youtube.js` | 新增 `consumptionApi.dates()`（设计文档未覆盖） |

### 7. Store 中 `loadDates` 签名

设计文档：`loadDates()` action（无参数）

实际代码（`frontend/src/stores/youtube.js` 第 33 行）：

```js
async loadDates(params = {}) { const res = await youtubeApi.dates(params); this.videoDates = res.dates; return res }
```

接受 `params` 对象并透传给 API，在 `YoutubeView.vue` 中以 `store.loadDates(store.filters)` 形式调用。
```
