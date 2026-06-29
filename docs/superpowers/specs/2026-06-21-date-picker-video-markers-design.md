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
```
