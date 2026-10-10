# 数据分析按平台隔离（FB 接自有数据 / TT 明确无数据）设计

日期：2026-10-11
状态：**已确认**（2026-10-11；4 个待确认项已定案，见 §6）
前置：本文档由一次 bug 诊断转成，用户已确认方向（原话：「三边都应该要，但是数据要分清 各自系统就是各自的 不要串了」「TT 先放弃，先弄 FB 就好，重点是 TT 不要乱读到其他系统的数据就好」）

---

## 1. 需求

### 1.1 用户报告的现象

> GG TT 都有数据分析这个模块，但是用开发者登录，明明是 GG 的数据，TT 那边也能看到。

### 1.2 确认后的目标

- **三边都要有「数据分析」这个入口**（GG / TT / FB）
- **各看各的数据，不串**
- **TT 本期不做分析功能**，但**绝不能显示别的平台的数据** —— 没有数据就明确说没有
- **FB 本期做**，先做与现有数据匹配的部分（花费）
- 之后另行处理「数据管理页对管理员/户管开放」那条需求（**不在本文档范围**）

### 1.3 非目标

- 不做 TT 的分析数据（TT 当前**没有任何报告类数据**，见 §2.3；要做需先让 TT 提取结果落库，那是独立的一件事）
- 不给 FB 做 GG 那套完整分析（FB 缺 `region`／安装／应用内操作，且展示/点击几乎全空，见 §2.4）
- 不动 GG 的分析功能

---

## 2. 现状与根因（已核实，附出处）

### 2.1 路由层：`/analysis` 是「中性页」

`frontend/src/router/index.js:70-73`：

```js
{ path: '/analysis', component: () => import('../views/AnalysisView.vue'),
  meta: { title: '数据分析' } }          // ← meta 里没有 platform
```

而 `frontend/src/components/AppSidebar.vue` 里 **GG / FB / TT 三套导航（`ggNavItems` / `fbNavItems` / `ttNavItems`）的「数据分析」都指向同一个 `/analysis`**。

### 2.2 请求层：按路径推平台 ⇒ 中性页一律判成 gg

`frontend/src/utils/platformPrefs.mjs`：

```js
export function platformFromPath(path) {
  if (p.startsWith('/admin/users')) return null
  if (p.startsWith('/tt')) return 'tt'
  if (p.startsWith('/fb')) return 'fb'
  return 'gg'                     // ← /analysis 落这里
}
```

`frontend/src/api/client.js` 对它判为 developer/huguan 的请求注入 `platform` 参数。**`/analysis` 不以 `/tt`/`/fb` 开头 → 永远注入 `platform=gg`。**

> 该文件头部已经点名了这个坑，并且**当天（2026-10-11）的另一轮修复只修了 store 侧**：
> ```js
> // ⚠️ 不要拿它当 store 的平台权威：/profile、/analysis 这类中性页会被它判成 gg。
> ```
> store（侧边栏/导航）改用了 `platformFamily`（只认路由**自己声明**的平台族），**请求层没跟着改**。

### 2.3 后端：`/api/ad-reports/*` 是 GG 专用，且 TT 没有可分析的数据

- `py/main.py:166` 的 `_GG_ONLY_PREFIXES` 把它们标注为 **`# GG 做表数据`**，守卫是 `_require_platform('gg')`（`py/main.py:~205`）。
- `ad_reports` 表 **没有 `platform` 列**（4658 行全是 GG 的做表数据）。
- **TT 没有任何报告类表**：`tt_*` 只有 `tt_accounts` / `tt_bcs` / `tt_products` / `tt_packages` / `tt_recharge_records` 等账户与业务数据。
- `frontend/src/views/tt/TtDataExtract.vue`（210 行）是**纯前端工具**：解析 → 生成 raw/坐标/客户三张表 → 一键复制 / 导出 CSV，**全程不落库**（整文件只调了 `ttApi.listProducts`）。

**⇒ 就算把平台参数传对，TT 也没有数据可看。**

### 2.4 FB：有数据，但没有分析接口，且字段比 GG 薄

- `fb_ad_reports` 有 **2418 行**（`cost` 2416 行有值；`impressions` 仅 20 行、`clicks` 19 行、`registrations`/`purchases` 各 4 行非零）。
- FB 的端点只有**数据管理**用途：`reports/list`、`<id>` PUT/DELETE、`batch-delete`、`stats`、`export`、`retry-sync`。
- **没有任何分析端点**（GG 的 `dashboard`/`trends`/`compare`/`multi-analysis`/`analyze` 在 FB 侧都不存在）。

FB 与 GG 的字段对照：

| 维度 | GG `ad_reports` | FB `fb_ad_reports` |
|---|---|---|
| 产品 | `product_name` | `product_name` |
| 地区 | `region` | **无** |
| 系列/线 | `campaign` | `line_name` |
| 花费 | `cost` | `cost` |
| 展示 / 点击 | `impressions` / `clicks` | 有列，但**几乎全 0** |
| 安装 / 应用内操作 | `installs` / `in_app_actions` | **无此概念** |

---

## 3. 技术方案

### 3.1 阶段 1（止血）：让分析页认自己的平台

**① 路由按平台分开**

`frontend/src/router/index.js` 新增两条（`/analysis` 保持 GG，与 GG 其它页面不加前缀的现状一致）：

```js
{ path: '/tt/analysis', component: () => import('../views/AnalysisView.vue'),
  meta: { title: '数据分析', platform: 'tt' } },
{ path: '/fb/analysis', component: () => import('../views/AnalysisView.vue'),
  meta: { title: '数据分析', platform: 'fb' } },
```

**② 侧边栏各自指向自己的路径**：`AppSidebar.vue` 里 `fbNavItems` 的 analysis 项改 `/fb/analysis`、`ttNavItems` 的改 `/tt/analysis`；`ggNavItems` 保持 `/analysis`。

> 这样 `platformFromPath('/fb/analysis')` → `'fb'`、`'/tt/analysis'` → `'tt'`，**请求层无需改动**即自动带对平台。

**③ `AnalysisView.vue` 按平台渲染**

- 从 `route.meta.platform`（缺省 `'gg'`）取平台
- `gg`：现有 6 个 tab **原样不动**
- `fb`：只渲染 FB 支持的 tab（阶段 2 落地前，先显示「FB 分析建设中」）
- `tt`：**整页只显示一个空状态**「TT 暂无分析数据」+ 原因（TT 数据提取目前不落库），**不调用任何 `/ad-reports/*` 接口**

**④ TT 的空状态必须是「不请求」而不是「请求后为空」** —— 否则仍会打到 GG 的端点（守卫会拦，但那是 403 而不是干净的「暂无数据」）。

### 3.2 阶段 2：FB 花费看板

**新增后端端点**（`py/routes/fb_routes.py`，前缀 `/api/fb/analysis`，沿用 `@fb_required` + 本平台数据）

| 端点 | 返回 |
|---|---|
| `GET /api/fb/analysis/dashboard` | `{ summary: {total_cost, total_impressions, total_clicks, record_count, account_count}, by_line: [{line_name, total_cost, total_impressions, total_clicks, record_count}], by_product: [...] }` |
| `GET /api/fb/analysis/trends` | `{ points: [{report_date, total_cost, total_impressions, total_clicks}] }` |

**过滤参数**：`product_name`（可多值逗号分隔）、`line_name`、`from_date`、`to_date` —— 与 GG 分析页的筛选口径一致，便于前端复用同一套筛选 UI。

**聚合口径**：`SUM(cost)` / `SUM(impressions)` / `SUM(clicks)`，按 `line_name`、`product_name`、`report_date` 分组。**只做「花费」为可信指标的展示**；展示/点击照实返回（当前几乎全 0，界面上标注「数据缺失」而不是假装有值）。

**前端**：`AnalysisView.vue` 的 `fb` 分支渲染：
- 指标卡：**总花费**、记录数、账户数、（展示/点击，带「数据不全」提示）
- 一张**按线（line_name）的花费表**
- 一条**花费趋势**折线

### 3.3 涉及的文件

| 文件 | 改动 |
|---|---|
| `frontend/src/router/index.js` | 新增 `/tt/analysis`、`/fb/analysis` |
| `frontend/src/components/AppSidebar.vue` | FB/TT 的 analysis 项改指向各自路径 |
| `frontend/src/views/AnalysisView.vue` | 按 `route.meta.platform` 分支渲染；TT 空状态；FB 看板 |
| `frontend/src/api/fb.js` | 加 `analysisDashboard` / `analysisTrends` |
| `py/routes/fb_routes.py` | 新增 2 个 `/api/fb/analysis/*` 端点 |

**不动的**：GG 的 6 个 tab 与 `/api/ad-reports/*`；`platformFromPath`（它「其余一律 gg」的默认对请求层是对的）；store 侧平台逻辑（当天刚修过）。

### 3.4 UI 改动

TT 的空状态与 FB 的看板都是**新 UI**。按项目规范，实现前**必须先调 `/frontend-design`** 做视觉设计（复用分析页现有的 `stat-card` 视觉语法，不另起一套）。

---

## 4. 边界与风险

| 场景 | 行为 |
|---|---|
| 开发者从 GG 侧进分析页 | 显示 GG 数据（现状不变） |
| 开发者从 TT 侧进 | 显示「TT 暂无分析数据」，**不产生任何 `/ad-reports/*` 请求** |
| 开发者从 FB 侧进 | 显示 FB 花费看板 |
| 直接手输 `/analysis` 且当前平台是 TT | 显示 GG 数据 —— 因为该 URL 就是 GG 的分析页。**这是刻意的**（路由前缀即平台），不是串 |
| 任何平台的角色访问别的平台的分析路由 | 由既有路由守卫拦截（沿用现有规则，本期不加新规则） |
| 旧书签 `/analysis` | 不失效（GG 页原样保留） |

**风险**：`/tt/analysis`、`/fb/analysis` 是**新路由**，需确认路由守卫（`router/index.js:166-246`）对它们放行且不误判——实现时逐一核对管理员/viewer/户管/普通用户四种角色。

### 4.1 守卫实测结论（2026-10-11，实现后补）

无头 Chromium 实测的**四种角色 × 三条分析路由**矩阵：

| 用户（角色, 平台） | `/analysis` | `/tt/analysis` | `/fb/analysis` |
|---|---|---|---|
| developer, gg | GG六tab | TT空态 | FB看板 |
| **admin, gg** | GG六tab | 弹回自己平台 | 弹回自己平台 |
| **viewer, gg** | GG六tab | 弹回自己平台 | 弹回自己平台 |
| huguan, gg（可切平台） | GG六tab | TT空态 | FB看板 |
| **user, tt** | **GG六tab（见下「已知限制」）** | TT空态 | 弹回 `/tt/products` |

**「弹回自己平台」是正确的**：admin/viewer **不在** `PLATFORM_SWITCH_ROLES`（管理员的平台隔离是刻意的），故访问**别的平台**的页面会被 R1 守卫弹回自己平台首页 —— 与 `/tt/products`、`/fb/products` 等**既有平台路由完全同构**，非本次引入。huguan/developer 可切平台 ⇒ 放行。**守卫本身无需改动**（该段无按 `/tt`/`/fb` 裸前缀的硬编码规则）。

### 4.2 已堵：`/analysis` 补 `meta.platform: 'gg'`（2026-10-11 用户裁定「先修复」）

**原状**：`/analysis` 没有 `meta.platform` ⇒ 平台守卫对它跳过 ⇒ **TT / FB 专用的用户手输 `/#/analysis` 能进入 GG 的分析页**。
（进去读到的仍是**他自己** uid 在 GG 数据集里的行、通常是空的，**非他人数据**；但它是「按平台隔离」唯一没堵住的口子。）

**已改为** `meta: { title: '数据分析', platform: 'gg' }`。效果：

| 角色 | 手输 `/#/analysis` |
|---|---|
| GG 平台用户（admin/viewer/user, platform=gg） | 照常进入 ✓ |
| developer / 户管（可切换平台） | 照常进入 ✓（他们本就被允许看 GG 数据） |
| TT / FB 平台的非可切换角色 | **弹回自己平台首页** ✓（与 `/tt/products` 等既有平台路由同构） |

> 这一处**推翻了 §4 表格里「直接手输 `/analysis` 即 GG 页 —— 刻意的」那条**：用户 2026-10-11 裁定把它堵上。

### 4.3 顺带发现的**既有缺陷**（不在本设计范围）

**`py/main.py` 的 `_guard_gg_platform` before_request 钩子实际不生效。**

实测：`platform=fb`、`role=user` 的账号对 `/api/accounts/list`、`/api/mcc/list`、`/api/products/list`、`/api/ad-reports/dashboard`（四个都在 `_GG_ONLY_PREFIXES` 里）**全部返回 200**；而该钩子 docstring 明写「FB 用户不可访问」。

机制：钩子里调 `get_jwt_identity()`，但在**没有 `@jwt_required()` 的 `before_request` 中** flask-jwt-extended 会抛 `RuntimeError`（要求先 `verify_jwt_in_request()`），被那句宽泛的 `except Exception: return None` **吞掉** ⇒ 守卫被静默跳过。

**影响面**：数据仍 uid 作用域（读到的是自己在那个数据集里的行），**不是跨用户泄露**；但**平台边界形同虚设**，且「守卫看起来在工作、其实不工作」比没有守卫更危险。**未擅自修**，单独报给用户裁定。

---

## 5. 测试与验收

**后端**（`py/tests/`）：
- FB 两个新端点的聚合口径（按线/产品/日期分组、日期区间过滤、多产品过滤）
- **数据隔离**：FB 端点只读 `fb_ad_reports`，拿不到 `ad_reports` 的数据（构造同名产品/线在两张表里各有数据，断言互不污染）
- 未登录 401、非 FB 角色按既有守卫行为

**前端**（无测试基建，走真实运行）：
- 三边各进一次分析页，确认**看板数据归属**与**网络面板里没有跨平台请求**
- TT 侧进分析页时，**DevTools Network 里不应出现任何 `/api/ad-reports/*` 请求**（这是本 bug 的核心判据）
- 四种角色各走一遍两条新路由

**验收判据（用户视角，最重要的一条）**：
> 用开发者登录，从 TT 进「数据分析」→ 看不到任何 GG 的数据；从 FB 进 → 看到的是 FB 自己的花费。

---

## 6. 已定案（用户 2026-10-11 回复「按你推荐来」）

1. **FB 看板的指标** —— **展示/点击摆上去，但标注「数据不全」**。不隐藏真实状态，也不假装有值。
2. **FB 的「地区」维度** —— **本期不做**（FB 无该字段）。
3. **TT 空状态文案** —— 「TT 暂无分析数据」，**并说明原因**（TT 数据提取目前不落库，故无数据可分析）。
4. **`/analysis` 保留为 GG 专属** —— 与 GG 其它页面（`/accounts/ads` 等）无前缀的现状一致。不改书签。

---

## 附录：分析页视觉决策

（Task 3 实现前调用 `/frontend-design` 的产出摘要。**本节只记录新增 UI 的视觉决策，不改动上文任何结论。**）

### 定位

这不是一个新页面，而是既有 Element Plus 管理页 `AnalysisView.vue` 里的一个分支。本任务的第一硬约束是**保真**：复用 `.stat-card` / `.stat-val` / `.stat-label`（`AnalysisView.vue` 的 `<style scoped>`），**不引入第二套视觉系统**。因此设计的职责不是立一套新身份，而是**信息诚实** —— 让「这个数可能是缺的」一眼可见，且不靠新增装饰件实现。

### Token（全部取自本页既有调色板，唯一新增的是 `#c0c4cc`）

| 值 | 用途 | 出处 |
|---|---|---|
| `#303133` | 主文字 / **可信**指标数值 | 既有 `.stat-val` |
| `#909399` | 次级说明文字 | 既有 `.stat-label` |
| `#f5f7fa` | stat-card 底 | 既有 |
| `#E6A23C` | Element Plus `warning`，「数据不全」标注色 | 简报指定 |
| `#c0c4cc` | （新增用法）**不可信**指标数值颜色 | 本页调色板的下一档灰 |
| `#409eff` | Element Plus primary（折线） | 既有 |

### 字体

沿用本页默认字体（Element Plus / 系统无衬线），**不另引字体**（引字体即违反「不另起一套」）。唯一的字体决策：可信指标保留 `.stat-val` 的 22px/700，不可信的两项**降为灰 `#c0c4cc`** —— 用字重与颜色把「可信度」编码进层级，而不是只靠一个小标签。

### 布局

```
TT（整页空状态，无筛选栏、无 tab）
┌────────────────────────────────┐
│                                │
│        TT 暂无分析数据          │  16px / #303133
│  TT 的数据提取目前不会把结果…    │  13px / #909399
│                                │
└────────────────────────────────┘
   单列居中，上下留白 64px；**不套卡片、不加边框** —— 空页面就该读起来是空的。

FB（花费看板）
[ $总花费 ] [ 记录数 ] [ 账户数 ] [ 展示·数据不全 ] [ 点击·数据不全 ]   ← 一行 flex-wrap 的 .stat-card
┌─ 按线花费表（限 200 行）──────────────────────────────┐
│ 仅显示花费前 200 条（共 N 条）  ← 仅在超限时出现        │
└───────────────────────────────────────────────────────┘
[ 花费趋势折线 echarts 340px ]
   左对齐，与仪表盘 tab 的卡片行（`AnalysisView.vue:26`）同款。
```

### 原则

1. **可信度编码在字重里，不只在标签里**：展示/点击既是灰数值又带「数据不全」小字 —— 那个 `0` 不会**喊**出来。
2. **不做任何静默截断**：表格截断要声明；缺失数据的列要标注。
3. **不新建任何东西**：每个类名、颜色、容器都借自本页或 Element Plus，GG 的身份一字未动。

### 自评（对照「AI 生成设计」的默认套路）

本设计的可发挥自由度只在一处 —— **如何标示不可信的数据**；这一处按简报的诚实性要求做了明确取舍（灰化 + 标注），其余全部受「复用」约束锁定，故整体天然克制，不存在「换一个项目也长这样」的默认套路。

### 实现侧的落点（供回溯）

- 空状态：`AnalysisView.vue` TT 分支 `<div v-if="analysisPlatform === 'tt'">`
- 指标卡 / 表 / 折线：FB 分支 `<template v-else-if="analysisPlatform === 'fb'">`
- **筛选栏的可见性也是本次的视觉决策**：TT 整页无数据 ⇒ 连筛选控件都不渲染（否则日期选择器 / 刷新按钮会打到 `/ad-reports/*`）；FB 无 `region` 字段 ⇒ 只去掉地区筛选。GG 的筛选栏一字未改。
- 与简报字面的一处**有意偏离（纯风格，非修 bug）**：简报给出的数值插值是 `row.total_cost.toLocaleString()`（无兜底），实现改为本页既有 idiom `(x || 0).toLocaleString()`，与 GG 分支的写法保持一致，**数据正常时渲染结果完全相同**。
  > 更正（2026-10-11 复审）：早先此处写成「`SUM()` 返回 NULL 会白屏」，**对本端点不成立** —— FB 端点的每个聚合量都做了 `COALESCE(...,0)`（`py/routes/fb_routes.py:2414-2420`、`:2429-2431`），`total_cost` 不可能为 NULL。保留 `(x || 0)` 的理由只是**与本页 idiom 统一**，不是防御真实存在的 NULL。
