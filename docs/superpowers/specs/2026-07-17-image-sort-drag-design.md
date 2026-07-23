# 图片手动拖拽排序 — 设计文档

## 需求描述

视频生成使用的图片目前只能按扫描顺序或随机排序，用户希望能手动拖拽调整图片顺序。

## 当前状态

- 图片以网格展示，点击选中/取消（`selectedImgs`）
- 支持全选/取消全选、随机排序（`randomOrder`）
- `getSettings()` 生成的 `images` 数组顺序 = 原始扫描顺序（或随机打乱）

## 设计方案

### 新增：已选图片排序面板

在图片网格上方新增一个"排序面板"区域：

```
┌─────────────────────────────────────────┐
│ 📸 图片顺序（拖拽调整）  [随机] [清空]    │
│ ┌──────┐ ┌──────┐ ┌──────┐ ┌──────┐    │
│ │ 图1  │ │ 图3  │ │ 图5  │ │ 图2  │    │
│ │  ✕   │ │  ✕   │ │  ✕   │ │  ✕   │    │
│ └──────┘ └──────┘ └──────┘ └──────┘    │
│ ← 可拖拽调整顺序 →                        │
└─────────────────────────────────────────┘

┌─────────────────────────────────────────┐
│ 🖼️ 图片列表（点选添加到排序面板）          │
│ ┌────┐ ┌────┐ ┌────┐ ┌────┐ ┌────┐    │
│ │图1 │ │图2 │ │图3 │ │图4 │ │图5 │    │
│ └────┘ └────┘ └────┘ └────┘ └────┘    │
└─────────────────────────────────────────┘
```

### 数据结构

用一个新 ref `orderedImages` 替代原来直接依赖 `selectedImgs` 的逻辑：

```js
// 有序的已选图片列表（用户拖拽排序后的结果）
const orderedImages = ref([])  // Array<{filename, path}>
```

原来的 `selectedImgs` 保留用于网格高亮，但 `orderedImages` 是最终传给 `getSettings` 的图片顺序。

### 交互逻辑

1. **点选图片** → 同时更新 `selectedImgs`（高亮）和 `orderedImages`（追加到末尾）
2. **取消选中** → 同时从 `selectedImgs` 和 `orderedImages` 中移除
3. **全选** → `orderedImages` = 所有图片（保持网格顺序）
4. **取消全选** → `orderedImages` = []
5. **拖拽排序面板中的图片** → 只改变 `orderedImages` 中的顺序
6. **排序面板中的 ✕ 按钮** → 从排序面板移除（同时取消网格高亮）
7. **随机排序按钮** → 随机打乱 `orderedImages`（放在排序面板工具栏）
8. **生成视频时** → `getSettings()` 使用 `orderedImages` 的顺序，忽略 `randomOrder`

### 拖拽实现

使用 HTML5 原生 Drag & Drop API（无需额外依赖）：

- `draggable="true"` 在排序面板的图片卡片上
- `@dragstart` / `@dragover` / `@drop` 事件处理
- 拖拽时视觉反馈（半透明 + 插入位置指示线）

### UI 布局

排序面板特征：
- 水平滚动（图片多时不换行，超出可左右滚动）
- 每张卡片显示缩略图 + 文件名 + 右上角 ✕ 移除按钮
- 拖拽中的卡片半透明，目标位置显示蓝色竖线指示
- 面板右侧工具栏：[🎲 随机排序] [🗑 清空]

### 涉及文件

| 文件 | 改动 |
|------|------|
| `frontend/src/views/MediaView.vue` | 新增排序面板 UI + 拖拽逻辑，修改 `getSettings`、`toggleImg`、`toggleSelectAll` |
| 无需后端改动 | - |

### getSettings 改动

```js
// 原来：
images: sel.map(img => img.path)
// 改为（带 fallback）：
const ordered = orderedImages.value.length > 0
  ? orderedImages.value.map(img => img.path)
  : images.value.filter(img => selectedImgs[img.filename]).map(img => img.path)
return {
  images: ordered,
  random_order: false,  // 排序面板已确定顺序，不需后端再随机
  // ...
}
```

**设计决策**：`getSettings` 优先使用 `orderedImages`，但当排序面板为空时回退到勾选的图片（保持网格顺序）。这保证了用户在未使用排序面板时仍能正常生成视频。

### toggleSelectAll 增强

原来 `toggleSelectAll` 只是简单反转 `allSelected`，现在支持 `force` 参数：

```js
function toggleSelectAll(force) {
  const val = force !== undefined ? force : !allSelected.value
  // force=true  → 全选，排序面板同步为全部图片（保持网格顺序）
  // force=false → 取消全选，清空排序面板
}
```

`scanDir()` 扫描新目录后调用 `toggleSelectAll(true)`，自动全选并填充排序面板。

### 随机排序的增强行为（shuffleOrdered）

设计文档中 `shuffleOrdered` 只打乱已有 `orderedImages`。实现中增加了**面板为空时的自动填充逻辑**：

```
shuffleOrdered() 被调用 →
  ├── orderedImages 非空 → 仅打乱现有顺序（Fisher-Yates）
  └── orderedImages 为空但 images 有数据 → 把所有图片随机打乱塞入面板，同时全选
```

这覆盖了"排序面板为空时点击🎲随机排序"的场景。

### onRandomOrderChange 联动

当用户点击网格下方的 `randomOrder` checkbox 时：

```js
function onRandomOrderChange(val) {
  if (val) shuffleOrdered()  // 勾选随机排序 → 自动填充并打乱排序面板
}
```

注意 `getSettings` 始终传 `random_order: false` 给后端，因为排序已在 `orderedImages` 中确定，无需后端再次随机。

### CSS 拖拽样式

```css
.sort-card.dragging { opacity: 0.4; transform: scale(0.95); }   /* 拖拽中的卡片半透明 + 缩小 */
.sort-card.drag-over { border-color: #0891b2 !important; transform: scale(1.05); }  /* 目标位置高亮 + 放大 */
```

拖拽状态通过两个 ref 控制：
- `dragIndex`：当前被拖拽卡片的索引（-1 表示无拖拽）
- `dragOverIndex`：鼠标悬停的目标位置索引（-1 表示无悬停）

### 与现有功能的兼容

- `randomOrder` checkbox：点击后自动调用 `shuffleOrdered()` 填充排序面板。`getSettings` 始终传 `random_order: false` 给后端，排序由前端控制。
- 历史恢复：`applyHistory()` 恢复设置中 `random_order` 字段会同步到 `randomOrder.value`（见代码第 1001 行），但不影响 `orderedImages`（排序面板仍为空，用户需要手动操作或点击随机排序）。
- 队列：`addToQueue()` 调用 `getSettings()` 捕获当前 `orderedImages` 的快照，队列中每个任务独立保存排序结果。
- 后端兼容：后端 `/api/video/generate` 仍保留 `random_order` 处理逻辑（行 691-693），前端传 `false` 来绕过。后端无需修改，向后兼容。
