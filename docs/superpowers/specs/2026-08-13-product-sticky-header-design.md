# 产品列表 — 展开产品头部吸顶设计文档

## 需求描述

产品管理页里，一个产品可能包含很多包。展开产品后，往下滚包列表时，产品头部（含产品名、KPI、地区、操作按钮那一栏）会滚出视野，导致「现在看的是哪个产品的包」不再可见。

期望效果：

- 展开的产品，往下滑到头部到达列表区顶部后，**头部钉住（吸顶）**，下面的包继续往上滚；
- **只有当该产品的所有包都滚过去之后**，头部才被带着一起滚走（释放）；
- **往回滚**时，第一个包一回到视野，头部又自动重新钉住，直到回到原位。

## 当前状态

### 结构

- [ProductPanel.vue:36](frontend/src/views/ProductPanel.vue#L36)：列表滚动区 `flex:1;min-height:0;overflow-y:auto`（工具栏在其外部，是兄弟节点，固定不滚）。
- [ProductCard.vue:2](frontend/src/components/ProductCard.vue#L2)：每个产品是一个 `el-card`。
- [ProductCard.vue:3](frontend/src/components/ProductCard.vue#L3)：`<template #header>` 是产品头部（可点击展开/收起）。
- [ProductCard.vue:66](frontend/src/components/ProductCard.vue#L66)：`<div v-show="expanded">` 是包列表（每个包一行 `.pkg-row`）。

### Element Plus `el-card` 关键样式（已确认，element-plus 2.9.1）

```css
.el-card {
  display: flex;
  flex-direction: column;
  overflow: hidden;                      /* ← 挡 sticky 的关键 */
  border-radius: var(--el-card-border-radius); /* 4px */
  border: 1px solid var(--el-card-border-color);
  background-color: var(--el-card-bg-color);
}
.el-card__header {
  padding: calc(var(--el-card-padding) - 2px) var(--el-card-padding);
  border-bottom: 1px solid var(--el-card-border-color);
  box-sizing: border-box;
  /* 无背景色、无圆角 */
}
.el-card__body {
  padding: var(--el-card-padding);
  flex-grow: 1;
  overflow: auto;
}
```

### 为什么直接加 sticky 不生效

`position: sticky` 的「滚动容器」是离它最近的、`overflow` 非 `visible` 的祖先。因为 `.el-card` 默认 `overflow: hidden`，若把 `.el-card__header` 设成 sticky，它的滚动容器会变成卡片自身（卡片内部并不滚动），于是头部永远不会相对外层列表区钉住。

## 技术方案

纯 CSS 实现，不监听滚动、不改任何业务逻辑，改动全部集中在 [ProductCard.vue](frontend/src/components/ProductCard.vue) 的 `<style scoped>`。

给根 `el-card` 增加一个类名 `product-card`，然后：

1. **`.product-card` 覆盖 `overflow: visible`** —— 让 header 的滚动容器回到外层列表区，sticky 才能生效（`.product-card` 与 `.el-card` 是同一根元素，直接覆盖即可）。
2. **`.product-card :deep(.el-card__header)` 设为 sticky** —— `position: sticky; top: 0; z-index: 10`，并加不透明背景挡住滚上来的包。

```css
.product-card {
  overflow: visible;
}
.product-card :deep(.el-card__header) {
  position: sticky;
  top: 0;
  z-index: 10;
  background: var(--el-card-bg-color);
}
```

### sticky 天然满足「释放 / 重新钉住」语义

- header 的约束范围是它的父元素 `.el-card`（即整个产品卡片）；
- 头部滚到 `top: 0` 后钉住，包在它下方继续滚；
- 卡片底部（最后一个包）触到头部时，头部被「推」着一起滚走 → **所有包滚完才释放**；
- 往回滚，卡片底部重新降到头部下方后，头部自动重新钉住 → **首包出现即重新钉住**；
- 多个产品都展开时，上一个释放、下一个接着钉住，全部由 sticky 自动处理。

### 圆角裁剪完善（本次一并处理）

覆盖 `overflow: visible` 后，`el-card` 原本靠 `overflow: hidden` 做的圆角裁剪会失效。把裁剪责任下沉到 header / body 自身：

- **顶部**：header 加顶部圆角，避免吸顶时方角顶在列表区边缘。
- **底部**：body 加 `overflow: hidden` + 底部圆角，恢复对最后一行包 hover 背景的裁剪（body 原 `overflow: auto` 在本场景不产生内部滚动，改成 hidden 无副作用）。
- **水平溢出防护**：header 加 `overflow: hidden`，窄窗口时裁剪产品头部一行的内容，避免溢出卡片边缘产生横向滚动条（sticky 元素自身设 overflow 不影响吸顶）。

```css
.product-card :deep(.el-card__header) {
  /* 在上一段基础上追加 */
  overflow: hidden;
  border-radius: var(--el-card-border-radius) var(--el-card-border-radius) 0 0;
}
.product-card :deep(.el-card__body) {
  overflow: hidden;
  border-radius: 0 0 var(--el-card-border-radius) var(--el-card-border-radius);
}
```

### 背景色 / 圆角取值说明

使用 CSS 变量 `var(--el-card-bg-color)`、`var(--el-card-border-radius)`（均定义在 `.el-card` 上，header/body 是其子节点可继承访问），而非硬编码 `#fff` / `4px`，以兼容主题变量（含潜在暗色模式）。

## 涉及的文件

| 文件 | 改动 |
|---|---|
| [ProductCard.vue](frontend/src/components/ProductCard.vue) | 根 `el-card` 加 `class="product-card"`；`<style scoped>` 新增上述 4 段 CSS |

无后端改动、无数据结构改动、无 API 改动。

## UI 改动

| 区域 | 变化 |
|---|---|
| 展开且有多个包的产品 | 头部滚动到列表区顶部后吸顶，包从其下方滚过；包滚完头部才释放 |
| 折叠 / 短卡片 | 无任何变化（sticky 不会触发） |
| 卡片圆角 | 保持 4px，顶部/底部圆角由 header/body 自行裁剪，视觉与现状一致 |
| 吸顶头部 | 带底边框 + 不透明背景，与下方包有清晰分隔 |

## 风险评估

- **低风险**：纯 CSS 增量，不碰 JS 逻辑、不碰后端、无性能开销（sticky 由浏览器合成器处理，不触发 scroll 回调）。
- **不改动现有业务逻辑**：`overflow: visible` 仅作用于该卡片内部布局，折叠/展开、筛选、多选、批量操作等交互均不受影响。
- **兼容性**：`position: sticky` 在现代浏览器全面支持；项目为内部管理系统，无旧浏览器顾虑。

## 备注

- 本需求为纯前端 CSS 微调，视觉设计要点已在上文「圆角裁剪完善 / UI 改动」给出；环境内未安装 `/frontend-design` 技能，故直接以文档形式固化视觉细节。
