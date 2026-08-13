# 产品列表 — 包筛选工具栏吸顶设计文档

## 需求描述

承接「产品头部吸顶」需求。展开某个产品后，产品头部（产品名/KPI/地区那一栏）已经能吸顶固定。现在希望**展开后包列表上方的那一排「包筛选工具栏」也跟着一起固定**：

- 「N 全部 / N 正常 / N 没事件 / N 拒登 / N 暂停 / N 掉包」状态筛选标签
- 「名字排序」「恢复默认排序」
- 「全选」「已选 N 个」「取消选择」「批量改状态」「复制链接」「批量删除」

即：往下滚包列表时，产品头部和包筛选工具栏一起固定在列表区顶部，包从下方滚过；所有包滚完才一起释放；往回滚自动重新吸顶。

## 当前状态

### 结构（[ProductCard.vue](frontend/src/components/ProductCard.vue)）

```
<el-card class="product-card">                 ← 根，overflow:visible（已改）
  <template #header>
    <div @click="expanded=!expanded">产品头部</div>   ← 第4-63行
  </template>
  <div v-show="expanded">                        ← body 内容，第66-123行
    <div 包筛选工具栏>                            ← 第67-92行，要吸顶的对象
    <div v-for="pkg" class="pkg-row">…</div>     ← 第93-122行
  </div>
</el-card>
```

渲染后的 DOM 与吸顶关系：

- `.el-card__header` 已设为 `position: sticky; top: 0`（上一需求），约束范围是整个 `.el-card`。
- 包筛选工具栏目前位于 `.el-card__body` 内部的 `v-show="expanded"` div 里，滚动时随包列表一起滚走。

### 为什么不能直接给筛选栏单独加 sticky

1. **`top` 值不确定**：若要单独吸顶，筛选栏需要 `top: <产品头部高度>`。但产品头部内容很多、`flex-wrap` 会换行，高度不固定（一行约 40px，换行可能 60~90px），固定 `top` 会错位。
2. **body 的 `overflow: hidden` 会锁死 sticky**：上一需求给 `.el-card__body` 加了 `overflow: hidden`（用于底部圆角裁剪），和此前 `.el-card` 的 `overflow:hidden` 锁死 header 是同一个问题——它会成为筛选栏的滚动容器，导致筛选栏无法相对外层列表区吸顶。

## 技术方案

**把包筛选工具栏的 DOM 从 body 移进 header 插槽**，紧跟产品头部 div 之后。这样它天然成为 `.el-card__header`（已 sticky top:0）的一部分，随产品头部一起吸顶。

- 无需动态计算 `top`（header 整体 sticky，top:0）；
- 不触碰 `.el-card__body` 的 `overflow:hidden`（筛选栏已在 body 之外）；
- 包筛选工具栏的全部交互逻辑（状态筛选、名字排序、全选、批量操作等）**零改动**，只是 DOM 位置移动。

### 改动点（[ProductCard.vue](frontend/src/components/ProductCard.vue)）

1. **模板**：把第 67-92 行的「包筛选工具栏」div 整体移到 `<template #header>` 内、产品头部 div（第 4-63 行）之后；并给它加 `v-show="expanded"`（原来靠外层 `v-show="expanded"` 控制，移出后需自带）。
2. **样式微调**：
   - 去掉筛选栏自身的 `border-bottom: 1px solid #eee`（header 已自带 `border-bottom`，避免双线）；
   - 筛选栏与上方产品头部之间补一点间距（原来它上方是 body 的 20px padding，移动后需要显式 `margin-top`）。

### 视觉对照

改动前：
```
[产品头部]            ← header，底部有 border
[body 20px padding]
[包筛选工具栏]        ← 底部有 border
[包列表…]
```

改动后：
```
[产品头部]
[包筛选工具栏]        ← 新增的 header 内第二行
──────────────        ← header 自带 border-bottom
[包列表…]
```

滚动时，`[产品头部] + [包筛选工具栏]` 作为一个整体吸顶。

## 涉及的文件

| 文件 | 改动 |
|---|---|
| [ProductCard.vue](frontend/src/components/ProductCard.vue) | 模板移动筛选栏到 header；筛选栏加 `v-show="expanded"`；微调间距/边框 |

无后端、无数据结构、无 API 改动。

## UI 改动

| 区域 | 变化 |
|---|---|
| 展开产品 | 产品头部 + 包筛选工具栏一起吸顶；滚包时两者固定；包滚完一起释放 |
| 折叠产品 | 筛选栏随 `expanded` 隐藏，无变化 |
| 筛选/排序/全选/批量操作 | 交互逻辑完全不变，仅位置随头部固定 |

## 风险评估

- **低风险**：纯模板移动 + 样式微调，筛选栏内部逻辑（computed、方法、事件）一行不动。
- **点击展开/收起边界**：筛选栏移出产品头部 div 后，是它的兄弟节点，点击筛选栏不会再触发展开/收起（原来也不触发，因筛选栏在 body 内）；筛选栏内部元素仍保留原有 `@click.stop`，行为不变。
- **不与上一需求冲突**：header 的 sticky 规则不变，仅 header 内多了一行内容。

## 备注

- 本需求与「产品头部吸顶」同属一个吸顶系列，复用 `.el-card__header` 的 sticky 机制，无新增 sticky 元素、无 JS。
