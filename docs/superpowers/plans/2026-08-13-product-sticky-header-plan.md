# 产品列表 — 展开产品头部吸顶 实现计划

## 目标

展开的产品卡片，其头部滚动到列表区顶部后吸顶，包滚完才释放，往回滚自动重新钉住；同时保留卡片圆角裁剪的视觉效果。

## 任务分解

1. [ProductCard.vue](frontend/src/components/ProductCard.vue) 根 `el-card` 增加类名 `product-card`。
2. `<style scoped>` 新增 CSS：
   - `.product-card` → `overflow: visible`（解除 sticky 被卡片自身锁定的问题）；
   - `.product-card :deep(.el-card__header)` → `position: sticky; top: 0; z-index: 10; overflow: hidden; background: var(--el-card-bg-color)` + 顶部圆角；
   - `.product-card :deep(.el-card__body)` → `overflow: hidden` + 底部圆角。

## 验收标准

- 展开多包产品，往下滚：头部吸顶，包从下方滚过；全部包滚完头部释放。
- 往回滚：首包回到视野时头部重新吸顶。
- 折叠/短卡片不受影响。
- 卡片顶部/底部圆角视觉与改动前一致，无内容溢出圆角。

## 完成后

调用 `/code-review` 审查本次改动。
