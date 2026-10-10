# 数据分析按平台隔离（FB 接自有数据 / TT 明确无数据）设计

日期：2026-10-11
状态：待确认
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

## 6. 待确认项

1. **FB 看板的指标取舍**：只做「总花费 + 按线花费表 + 花费趋势」，还是也要把「展示/点击」摆上去（当前几乎全 0，摆上去会是空图）？本设计的建议是**摆上去但标注数据不全**。
2. **FB 的「地区」维度**：GG 分析按地区切，FB 没有该字段 —— 本期**不做**地区维度，确认可以。
3. **TT 空状态的文案**：写「TT 暂无分析数据」是否够（要不要顺带说明「因为 TT 数据提取不落库」）？
4. **是否保留 `/analysis` 作为 GG 专属**：本设计是保留（与 GG 其它页面无前缀的现状一致）；若你希望 GG 也显式用 `/gg/analysis`，改动会波及书签与首页跳转，需另议。
