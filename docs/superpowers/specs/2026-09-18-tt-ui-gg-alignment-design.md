# TT 模块 UI 对齐 GG 风格 设计文档

> 状态：待确认
> 日期：2026-09-18

## 1. 需求描述

将 TT 模块的两个前端页面——**产品管理页**（`TtProductPanel.vue`）与 **BC 管理页**（`TtBcPanel.vue`）——的 UI 样式，改为与 GG 对应页面**完全一致的版本**。

- 产品管理页 → 对齐 GG `ProductPanel.vue` + `ProductCard.vue`
- BC 管理页 → 对齐 GG `MccPanel.vue` + `MccModal.vue`
- 粘贴解析 → 对齐 GG `CopyImportModal.vue`：改为**预览式**（先 `🔍 预览解析结果` 出可编辑表格，用户确认后再加入），并**去掉后缀输入框**（只保留「系列名前缀」，与 GG 一致）

**约束**：纯增量原则——只新增/修改 `frontend/src/views/tt/` 下的 TT 文件，以及新增 TT 专属组件到 `frontend/src/components/`；**不改动任何 GG/FB 现有文件**。

## 2. 现状 vs 目标

### 2.1 当前 TT 风格（要改掉的）

- 顶层 `page-wrapper`：灰底（`#f5f6f8`）+ `padding:24px` 卡片式容器
- `filter-card`：圆角（`border-radius:12px`）灰底筛选卡片
- `page-header` + `page-title`：大标题 `<h1>`
- 产品卡片：`el-card` + 大量自定义彩色 tag 覆盖（`!important`）、圆角、绿点
- 产品卡片展开后套 `el-table`（跑包/PWA 子表）
- 弹窗：`label-width="80px"`（label 在左侧）、无 emoji、两列 `el-row/el-col`
- BC 页：平铺 `el-table` + 行内弹窗

### 2.2 GG 风格（目标）

- 顶层：`display:flex;flex-direction:column;height:100%`，**无灰底/无卡片容器**（透明白底）
- 工具栏：顶部 `flex-shrink:0` 的一行 flex（按钮 + 筛选控件），`gap:10px;margin-bottom:12px`
- 产品卡片（`ProductCard.vue`）：`el-card` + `#header` 插槽（`position:sticky;top:0` 吸顶），body 内是**包列表行 `pkg-row`**（系列名/包名/链接/状态下拉，单行 flex），不是 `el-table`
- 状态点：内联 style 的 8px 圆点（active 绿 `#059669` / paused 红 `#dc2626`）
- tag：Element Plus 原生 `type`（success/warning/primary/info），**不用自定义颜色覆盖**
- 按钮/标题带 emoji（`➕ 新增产品`、`✏️ 编辑`、`🗑`、`💾 保存`）
- 弹窗：`el-form label-position="top"`（label 在输入框上方）、垂直单列、宽度 480px、emoji 标题
- MCC 页：树形 `el-table` + 层级彩色左边框（TT 的 BC 无层级，故此项不适用）

## 3. 技术方案

### 3.1 总体

纯前端改动，后端 API 契约**不变**（TT 后端路由、字段、数据结构零改动）。

新建 TT 专属组件，照 GG 视觉复刻；TT 页面改用 GG 的布局骨架（flex column + 工具栏 + 滚动区）。

### 3.2 新建组件

| 文件 | 说明 |
|------|------|
| `frontend/src/components/TtProductCard.vue` | TT 产品卡片，照 `ProductCard.vue` 视觉复刻，字段适配 TT（BC 代替 MCC，跑包/PWA 代替 GG 包状态） |

### 3.3 修改文件

| 文件 | 改动 |
|------|------|
| `frontend/src/views/tt/TtProductPanel.vue` | 顶层容器 → flex column；工具栏 → GG 一行 flex；卡片列表改用 `TtProductCard`；弹窗 → `label-position="top"` + emoji |
| `frontend/src/views/tt/TtBcPanel.vue` | 顶层容器 → flex column；工具栏 → GG 一行 flex；表格视觉对齐；弹窗 → `label-position="top"` + emoji |

## 4. UI 改动明细

### 4.1 产品管理页 `TtProductPanel.vue`

**顶层容器**
```html
<div style="display:flex;flex-direction:column;height:100%;">
```
- 删除 `page-wrapper` / `page-header` / `page-title` / `filter-card` 灰底容器
- 标题不再用 `<h1>`；页面语义通过工具栏与卡片承载

**工具栏**（对齐 GG ProductPanel 一行 flex，`gap:10px;margin-bottom:12px`）
- 左起：`➕ 新增产品` 按钮（type=primary）→ 搜索输入框（`flex:1`）→ 地区筛选 `el-select`（clearable）→ 在跑人筛选 `el-select`（clearable filterable）→ 状态 `el-radio-group`（正常/已暂停）→ 归档 `el-radio-group`（在用/已归档）

**产品卡片**（新建 `TtProductCard.vue`，照 GG ProductCard）
- `el-card` + `#header`（吸顶 sticky）
- 头部单行 flex：8px 状态点（内联 style）→ 产品名 `<strong>` → `掉包检测` 按钮（`type=warning plain`，loading）→ BC tag（`type=info`，如 `🏢 {{ bc.name }}`）→ kpi tag（`type=warning`）→ region tag（`type=primary`）→ customer tag（`type=success`）→ 在跑 tag（`type=info`，`🏃 N人`）
- 操作按钮（`#header` 右侧）：`📋 详情` → `⏸/▶ 暂停` → `✏️ 编辑` → `🗑 删除`（对齐 GG 排布；归档态显示 `恢复`）
- body 展开：**包列表行 `pkg-row`**（单行 flex），每行 = 系列名（monospace 点击复制）→ 包名（monospace 点击复制）→ 链接（点击复制 + 🔗 外链）→ 状态（跑包/PWA tag）；不是 `el-table`
- 删除 TT 的彩色 tag 覆盖、圆角、绿点自定义类

**新增/编辑弹窗**
- `el-form label-position="top"`（label 在输入框上方）
- 字段垂直单列（对齐 GG ProductModal），宽度 480px：
  - 产品名（required）→ KPI → 地区（select filterable）→ 客户 → 商务（select filterable）→ 代投比例（`el-input v-model.number`）→ BC（select filterable，label `所属 BC`）→ 状态（select）→ 在跑人员（select multiple）
- **投放对象**子表 + 粘贴解析仍保留（这是 TT 独有功能），但视觉对齐：`el-divider` 分隔 + 表格 header 灰底
- 标题带 emoji：`✏️ 编辑产品` / `➕ 新增产品`；保存按钮 `💾 保存`

**粘贴解析弹窗**（对齐 GG `CopyImportModal` 的预览式交互）
- 触发位置不变：仍由产品弹窗内的「粘贴解析」按钮打开（服务于「给当前产品加投放对象」）
- 弹窗内 `el-form label-position="top"`，字段垂直单列：
  - 「系列名前缀（可选）」`el-input`（**只有前缀，删除后缀输入框**，对齐 GG）
  - 「粘贴内容」`el-input type="textarea" :rows="6"`
- `🔍 预览解析结果` 按钮（`parsing` loading）→ 调 `importText` 解析
- 解析结果**预览表格**（`el-table size="small"`，可编辑，对齐 GG）：
  - 系列名（`el-input size="small"` 可改）
  - 包名
  - 链接（小字）
  - 操作列 `✕` 删除行
- footer：`取消` + `💾 加入`（`disabled` 直到有解析结果，`saving` loading）→ 点击后把预览结果 push 进产品表单的 `formPackages`，而不是直接创建产品
- 点击「加入」后回到产品弹窗，投放对象子表即时显示新增行

### 4.2 BC 管理页 `TtBcPanel.vue`

**顶层容器**：同 4.1，flex column，删除灰底容器

**工具栏**（对齐 GG MccPanel）
- 第一行：`➕ 新增 BC`（type=primary）→ 搜索输入框（`flex:1`）→ 状态筛选 `el-select`（正常/封禁，clearable）
- 删除 `filter-card` / `total-badge`

**表格**（对齐 GG MccPanel 视觉）
- `el-table` + `stripe` + `size="small"`
- 列：名称 → BCID → 备注 → 状态（`el-tag`）→ 操作
- 操作列用 `el-button link`（`✏️` / `封禁` / `🗑`），对齐 GG 的 link 按钮风格
- 分页：`el-pagination` + 每页条数 `el-select`（`[10,20,50]`），对齐 GG

**新增/编辑弹窗**
- `el-form label-position="top"`，垂直单列，宽度 480px
- 字段：名称（required）→ BCID（required）→ 备注（textarea）
- 标题 emoji：`✏️ 编辑 BC` / `➕ 新增 BC`；保存 `💾 保存`

## 5. 数据结构与 API

**不变**。所有后端契约（`ttApi` 方法、字段名 `bc_id`/`product_name`/`packages`/`runner_ids`/`type` 二值等）保持原样，仅前端视图层视觉对齐。

## 6. 涉及文件清单

- 新增：`frontend/src/components/TtProductCard.vue`
- 修改：`frontend/src/views/tt/TtProductPanel.vue`
- 修改：`frontend/src/views/tt/TtBcPanel.vue`
- 不动：GG/FB 任何文件

## 7. 验证

- `cd frontend && npm run build` 通过
- 手动浏览器：TT 用户登录，产品页 + BC 页逐项与 GG 对应页比对视觉
- 后端测试无需改动（无后端变更）
