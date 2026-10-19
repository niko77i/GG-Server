# FB 数据管理页：自选展示列（对齐 GG）设计

日期：2026-10-19
状态：**已确认（2026-10-19）** —— 决策：① 移除「显示详情列」复选框，统一用列选择器；② 列偏好存 `localStorage`（与 GG 一致，不做后端持久化）。
相关：`docs/superpowers/specs/2026-10-11-report-data-permission-design.md`（同一页面的权限改造，已实现）

---

## 1. 需求

FB 数据管理页（`/fb/data-manage`）当前只有**一个粗粒度开关**「显示详情列」，
只能整体控制 5 个详情列。用户要求：**像 GG 数据管理页一样，可以逐列勾选要展示的列**。

GG 页的对应实现：`frontend/src/views/DataManageView.vue:41-54`（UI）与 `:182-240`（逻辑）。

---

## 2. 现状

### FB 页（`frontend/src/views/fb/FbDataManage.vue`）

| 列 | 当前控制方式 | 宽度 |
|---|---|---|
| 勾选框 | `v-if="auth.canWriteReportRows"` | 45 |
| 产品名 / 线名 | 固定 | min-width 100 |
| 日期 | 固定 | 110 |
| 账户名称 | 固定 | min-width 120 |
| 账户ID | 固定 | 160 |
| **消耗** | 固定（户管内联编辑） | 户管 150 / 其余 100（`336b5bc`） |
| 展示 / 点击 / 注册 / 购物 / 单词购物费用 | **`v-if="showDetailCols"`** 整体开关 | 90/80/80/80/120 |
| 操作 | `v-if="auth.canWriteReportRows"` | 140, fixed right |

`showDetailCols = ref(false)`（`:173`）—— 默认隐藏 5 个详情列，**不持久化**（刷新即复位）。

### GG 页（对照实现）

- `allColumns`：列定义数组（`prop / label / minWidth / align / format`）。
- `visibleColumns`：`ref`，从 `localStorage`（key `gg_data_manage_columns`）恢复；默认全部可见。
- `visibleColumnDefs`：computed，按 `visibleColumns` 过滤并保持 `allColumns` 顺序。
- `toggleColumn(prop, checked)`：勾选时按原顺序插回，取消时移除。
- UI：筛选栏里一个 `📊 列显示` 按钮 → `el-popover` + `el-checkbox` 列表。
- 勾选框列 / 操作列**不在**选择范围内（它们由角色决定，不是展示偏好）。

---

## 3. 方案

**直接把 GG 的模式移植到 FB 页**（同一套交互与持久化语义），不引入新组件、不改后端。

### 3.1 列定义

在 FB 页新增 `allColumns`，覆盖 11 个数据列：

```js
const allColumns = [
  { prop: 'product_name',      label: '产品名',       minWidth: 100 },
  { prop: 'line_name',         label: '线名',         minWidth: 100 },
  { prop: 'report_date',       label: '日期',         width: 110 },
  { prop: 'account_name',      label: '账户名称',     minWidth: 120 },
  { prop: 'account_id',        label: '账户ID',       width: 160 },
  { prop: 'cost',              label: '消耗',         costCol: true },   // 宽度/内联编辑特判
  { prop: 'impressions',       label: '展示',         width: 90 },
  { prop: 'clicks',            label: '点击',         width: 80 },
  { prop: 'registrations',     label: '注册',         width: 80 },
  { prop: 'purchases',         label: '购物',         width: 80 },
  { prop: 'cost_per_purchase', label: '单词购物费用', width: 120 },
]
```

表格改用 `v-for="col in visibleColumnDefs"`，`cost` 列在模板里保留现有的两个分支
（户管内联编辑 / 其余只读），宽度规则继续沿用「户管 150、其余 100」。

### 3.2 默认可见列 = **当前默认行为**

默认：前 6 列（产品名、线名、日期、账户名称、账户ID、消耗）可见，**5 个详情列隐藏**。
这样**普通 user 打开页面看到的表格与改动前逐字一致**（回归硬判据）。

> **既有行为也要保留（实现时补充）**：改动前，当本次数据里存在「展示/点击 > 0」的行时，
> 页面会**自动打开** 5 个详情列（原 `showDetailCols` 自动置真）。
> 实现保留了该逻辑：**用户未显式勾选过列**时，有详情数据就显示全部列；
> 一旦用户在「📊 列显示」里动过，就以用户的选择为准（不再自动覆盖）。

### 3.3 持久化

`localStorage`，key 用 **`fb_data_manage_columns`**（与 GG 的 `gg_data_manage_columns` 分开，
两边互不影响）。读取失败 / 读到空数组 ⇒ 回落到「默认可见列」。**不落库**（与 GG 一致）。

### 3.4 与现有「显示详情列」开关的关系

**移除** `showDetailCols` 复选框与其 `v-if`（`:26`、`:85-91`、`:173`）。

理由：两个机制同时控制同一批列会互相打架（勾了详情列但开关关着 ⇒ 看不到，用户会困惑）。
新选择器是它的**严格超集**（原来能一键显隐 5 列，现在能逐列控制，默认值也一样）。

> 这是**用户可见的交互变化**：原来那个「显示详情列」复选框会消失。需求已明确要"像 GG 那样"，
> 故按此处理；若希望保留，改动很小（把 5 个详情列的默认可见性与之联动），需确认。

### 3.5 不动的部分

- 勾选框列、操作列：仍按 `auth.canWriteReportRows` 控制，**不进**选择器。
- 消耗列的内联编辑与角色显隐：不变。
- **导出 CSV**：走服务端导出全部字段，**不受列可见性影响**（与 GG 一致）。
- 后端：零改动。
- GG 页：零改动。

---

## 4. 涉及文件

| 文件 | 改动 |
|---|---|
| `frontend/src/views/fb/FbDataManage.vue` | 唯一涉及文件：列定义 + v-for + popover + localStorage + 移除旧开关 |

无后端、无数据库、无接口改动。

---

## 5. 验收判据

- [ ] 普通 user 首次打开 FB 页：可见列与改动前**完全一致**（6 列 + 操作列，详情列隐藏）。
- [ ] 点击「📊 列显示」可逐列勾选；勾选后表格立即变化。
- [ ] 刷新页面后选择**保持**（localStorage）。
- [ ] 户管的「消耗」列仍可内联编辑，且金额不再被截断。
- [ ] 勾选框列 / 操作列**不出现在**列选择器里，且其角色显隐行为不变。
- [ ] 清除 localStorage 后回到默认列。
- [ ] 导出 CSV 内容不受列可见性影响。
- [ ] `npm run build` 通过、`npm test` 全绿。

---

## 6. 实施说明

按项目规范：本需求含**新增 UI**，实施前先调 `/frontend-design` 产出视觉决策
（沿用 GG 页既有的 popover + checkbox 形态，不另起视觉），再写实现计划并逐步实现。

---

## 7. 已确认的决策（2026-10-19）

1. **移除「显示详情列」复选框**，统一用列选择器（选择器是它的严格超集，默认可见列不变）。
2. **持久化用 `localStorage`**（key `fb_data_manage_columns`），与 GG 一致，不做后端持久化。

---

## 附录：视觉决策（2026-10-19，已按项目规范调用 `/frontend-design`）

**结论：不引入任何新的视觉语言，逐字复用 GG 页的既有形态。**

- **形态**：筛选栏里的 `📊 列显示` 按钮 → `el-popover`（`placement="bottom-start"`, `:width="220"`）→ 垂直排列的 `el-checkbox` 列表。与 `DataManageView.vue:41-54` 同构。
- **色 / 字体**：零新增。全部取 Element Plus 默认令牌；不引入新色值、新字族、新圆角或阴影。
- **布局**：按钮放在筛选栏中原来「显示详情列」复选框的位置（区域语义不变），不改变筛选栏的分组与对齐。
- **动效**：无。popover 的展开由 Element Plus 自带。
- **可访问性**：勾选框与按钮的键盘焦点、读屏语义由 Element Plus 组件提供；不额外覆盖样式。
- **文案**：按钮 `📊 列显示`；复选框用列名本身（产品名/线名/日期/账户名称/账户ID/消耗/展示/点击/注册/购物/单词购物费用）。
