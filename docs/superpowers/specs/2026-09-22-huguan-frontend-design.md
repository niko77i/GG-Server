# 户管角色前端界面设计文档

> 日期：2026-09-22
> 状态：待确认（仅设计，不含实现代码）
> 范围：Task 12–16 的五个前端界面改动（侧边栏导航 / GG 账户页 Tab / 用户管理页 / TT 设置页 / 账户面板用户筛选下拉）
> 上游依据：`2026-09-22-huguan-role-design.md`（产品需求）与 `.superpowers/sdd/task-12~16-brief.md`（实现简报）

## 0. 设计基线（从现有代码读出的既有约定，本设计沿用）

1. **侧边栏是两段式**：56px 图标轨（`.icon-rail`）+ 200px 详情面板（`.detail-panel`），见 `frontend/src/components/AppSidebar.vue`。图标轨顶部是品牌按钮，其下是平台切换按钮（现仅 developer 可见，`AppSidebar.vue:12`），再下是各分组的图标按钮。
2. **品牌主色 #0891b2（cyan-600）**，灰阶 `#f8f9fa / #e5e7eb / #9ca3af / #374151 / #111827`。**没有独立 design token 系统**，色值硬编码 + Element Plus 默认主题混用。本设计不新建 token、不换字体、不加依赖。
3. **筛选控件统一模式**（各账户面板 + TT 现有「全部投手」下拉）：`el-select` + `clearable` + `filterable` + 占位文案 + `@change` 触发重载并重置页码。新的用户筛选下拉必须完全套用此模式，宽度 130–180px 区间，与同行控件 `gap:8px`。
4. **角色判断集中在 `stores/auth.js` 的 getter**，视图层只读 getter。本次新增的 `isHuguan / canSwitchPlatform / canManageAccounts` 属于 Task 11 交付，本设计直接引用其语义（见需求文档 3.2）：
   - `canSwitchPlatform = developer || huguan`（平台切换）
   - `canManageAccounts = developer || admin || huguan`（账户域管理 + 用户筛选下拉可见性）
5. **后端为唯一权限事实来源**：前端只做体验收敛。所有「隐藏」都不替代后端 403 拦截。

---

## 1. Task 12 — 户管侧边栏导航

### 1.1 决定

**户管专用导航三套**（GG / FB / TT），由 `huguanNavItems` 按 `effectivePlatform` 短路返回（Task 12 简报 Step 3–4 的数组结构即为最终结构，无需另造）。户管菜单的语义是「账户域 + 系统设置 + 用户管理」，**彻底排除产品/视频/媒体/工具集/数据分析/数据管理/定时任务**。

**平台切换按钮**：户管可见（`v-if="auth.canSwitchPlatform"`，替换 `AppSidebar.vue:12` 的 `isDeveloper`）。户管登录后看到 GG / FB / TT 三个 `plat-btn`，行为与 developer 一致。

**分组标题措辞**：**不需要为户管单独立措辞**。顶层「账户管理」与「管理」两个分组标题沿用现有 `ggNavItems` / `fbNavItems` 的文案（`AppSidebar.vue:78,88`）。唯一例外是 TT——现有 `ttNavItems` 的账户区顶层 label 是「产品管理」（`AppSidebar.vue:106`），而户管的 TT 导航顶层 label 用「账户管理」，这是有意为之且正确（户管管的是账户不是产品）。

### 1.2 户管菜单树（带标注）

```
图标轨（户管，effectivePlatform = gg / fb / tt 分别渲染）
├─ 品牌按钮（🏠，跳转问题见「待人工确认」OQ-2）
├─ 平台切换：GG | FB | TT        ← canSwitchPlatform，替换 isDeveloper
├─ 🏢 账户管理  ──────────────（顶层 label 三平台统一「账户管理」）
│   └─ 详情面板 sections：
│      ├─ 账户
│      │   GG: 👤 广告账户 /accounts/ads   🏢 MCC管理 /accounts/mcc
│      │   FB: 👤 广告账户 /fb/accounts    🏢 BM管理 /fb/bms   📊 像素管理 /fb/pixels
│      │   TT: 👤 广告账户 /tt/accounts    🏢 BC管理 /tt/bcs
│      └─ 系统
│          GG: ⚙ 设置 /accounts/settings
│          FB: ⚙ FB设置 /fb/settings
│          TT: ⚙ TT设置 /tt/settings
├─ 🏴 管理  ──────────────────（admin: true，户管放行）
│   └─ 管理
│       └─ 👥 用户管理 /admin/users       ← 无 developer:true，故不会被过滤
│
└─ （下列分组对户管整体不渲染）
    ✗ 📦 产品管理  ✗ 📺 视频管理  ✗ 🎬 媒体工具  ✗ 🧰 工具集
    ✗ 📈 数据分析  ✗ 📋 数据管理  ✗ ⏰ 定时任务
```

要点：
- 像素管理（📊 `/fb/pixels`）**只在 FB 出现**，符合需求「FB 分组包括像素管理」。
- 「管理」分组对户管放行的关键：`visibleNavItems` 中 `n.admin` 分支由 `auth.isAdmin` 改为 `auth.isAdmin || auth.isHuguan`（Task 12 Step 4）。户管导航数组里的「用户管理」项**不带** `developer:true`，故既有的 `!auth.isDeveloper` 过滤（`AppSidebar.vue:145-150`）不会误删它。
- 点击「账户管理」图标后落点：户管三平台的账户区**首项即账户页**（`/accounts/ads`、`/fb/accounts`、`/tt/accounts`），因为户管导航数组里没有产品项；`selectTab`（`AppSidebar.vue:161-166`）取 `sections[0].items[0]`，落点自然正确，无需额外分支。此点 Task 12 Step 7 的手工核对应覆盖。

### 1.3 决策表

| 决定 | 理由 | 被否决的选项 |
|---|---|---|
| 户管看到 GG/FB/TT 三个平台切换按钮 | 需求明确「户管可像 developer 一样自由切换」（需求 4、2.2），复用 `canSwitchPlatform` | 隐藏切换按钮、或只给部分平台（违反需求） |
| 户管菜单 = 账户区 + 设置 + 用户管理，三平台各一套 | 需求 3.7 明确排除产品/视频/媒体/工具集/数据分析/定时任务；分组按平台差异（GG 有 MCC、FB 有 BM+像素、TT 有 BC） | 复用既有 `ggNavItems` 做逐项 `v-if`（脆弱、易漏，且会把「产品管理」一起带出来） |
| 分组标题沿用「账户管理」「管理」，户管不单独立措辞 | 与既有视觉语言一致，无新增术语 | 为户管单独改标题（如「账户与用户」），无信息增量 |
| TT 顶层 label 用「账户管理」而非「产品管理」 | 户管语义是账户不是产品；TT 现有「产品管理」是历史命名不一致，不引入户管视图 | 跟随 TT 现有「产品管理」（与户管实际能力冲突） |
| 定时任务对户管不渲染 | 需求 7「不具备定时任务」，且路由 `meta.developer` 守卫会拦截；隐藏而非置灰 | 置灰显示（制造无意义死入口） |

---

## 2. Task 13 — GG 账户页顶部 Tab 对户管开放

### 2.1 决定

- 户管在 GG 账户页看到 **3 个 Tab**：广告账户 / MCC 管理 / 设置，默认停在「广告账户」。
- 「产品管理」Tab 对户管**完全隐藏**（`v-if="!auth.isHuguan"`），**不是置灰**。
- 三个账户 Tab 的可见性由 `auth.isAdmin` 改为 `auth.canManageAccounts`（`AccountsView.vue:7-9`）。

### 2.2 「隐藏 vs 置灰」的选择与理由

**选「完全隐藏」**。理由：
1. 户管对产品域**没有任何权限**——后端 `reject_huguan`（需求 3.9）对产品端点直接 403，而非「只读」。置灰暗示「存在但暂不可用」，对用户是误导；隐藏才是「这个能力与你无关」的正确信号。
2. 与侧边栏一致：侧边栏已把产品/视频等分组整体隐藏，账户页 Tab 若保留一个置灰的「产品管理」会与导航口径矛盾。
3. Element Plus 的 `el-tab-pane` 本身不提供「禁用」态，硬做置灰需要额外 disabled 逻辑 + 样式，属于为错误语义买单。

### 2.3 默认 Tab 与重定向

- `AccountsView.vue` 的 `activeTab` 已按路由路径计算（`:31-38`），户管落在 `/accounts/ads` 时 `activeTab === 'ads'`，无需改。
- 平台根路由 `/accounts` 的静态 `redirect: '/accounts/products'`（`router/index.js:29`）会把户管送回产品页，**必须按身份分派**（同理 `/fb` `:90`、`/tt` `:132`）：户管 → `/accounts/ads` / `/fb/accounts` / `/tt/accounts`；其余角色保持 `/.../products`。
- **冲突提示**：Task 13 Step 3 的分派实现用 `localStorage.getItem('user')` 读角色，而需求 3.7 明确说「在 auth store 暴露 `homePath` getter」。两者结论一致但实现来源不同，见「待人工确认」OQ-3。

### 2.4 决策表

| 决定 | 理由 | 被否决的选项 |
|---|---|---|
| 产品管理 Tab 对户管完全隐藏 | 后端对户管产品域 403，置灰是误导；与侧边栏隐藏口径一致 | 置灰显示（死入口 + 需额外 disabled 逻辑） |
| 三个账户 Tab 用 `canManageAccounts` 门控 | 与 Task 11 getter 语义对齐，admin/developer 行为不变 | 单独写 `isAdmin || isHuguan` 字面量（绕开 getter 单一事实来源） |
| 户管默认落「广告账户」Tab | 账户域首项，与侧边栏 `selectTab` 落点一致 | 默认落 MCC 或设置（非首项，打断浏览节奏） |
| 根路由重定向按身份分派 | 静态 `/products` 会把户管送进无权限页面 | 保持静态重定向（户管被弹回或落到空 Tab） |

---

## 3. Task 14 — 用户管理页对户管收窄

### 3.1 决定（围绕「如何传达收窄」）

**页面标题**：保持「用户管理」（`UserManageView.vue:4` 的 h3），**不重命名**。理由：侧边栏导航项就叫「用户管理」（`AppSidebar.vue` 户管导航数组），页面标题与导航一致。为传达「收窄」，在标题下方**为户管增加一行灰色说明**：「仅可管理你创建的户管账号」（`font-size:13px;color:#6b7280`，与页面现有「共 N 个用户」同色系）。这条说明承载了「只能操作自己创建的」这条不可见规则，是本次收窄最重要的沟通点。

**平台 Tab**：对户管**整体隐藏**（`el-tabs` 加 `v-if="!authStore.isHuguan"`，`UserManageView.vue:9`）。户管的列表口径是「我创建的户管」，与平台维度无关，Tab 无意义（需求 3.7.1）。

**角色筛选/创建弹窗**：户管创建时角色**锁定为「户管」且不可改**。
- 推荐形态：创建弹窗的角色下拉对户管**只显示「户管」一个选项且禁用**（`el-select` 内单 option + disabled），而非禁用但保留「普通用户/观察者/管理员/户管」四个选项。
- 理由：禁用的四选项下拉暗示「这些角色都在你可选范围内，只是暂时不能动」，与实际「你只能创建户管」相反；单选项 + 禁用直白且视觉更短。后端 `ALLOWED_CREATE_ROLES`（需求 3.6.2）会兜底强制 `huguan`，前端形态只是体验。
- **冲突提示**：Task 14 Step 2 明确写「不需要按身份删选项——只需禁用与补上『户管』项」。这是实现简报的显式决定，与我的设计偏好冲突，见「待人工确认」OQ-7。

**创建入口（affordance）**：户管可见的「创建用户」按钮（`UserManageView.vue:26`）与弹窗标题「创建用户」（`:81`）对户管改为**「创建户管」**。理由：户管唯一能创建的对象就是户管，按钮文案如实反映能力；「创建用户」会让户管误以为能建普通用户。

**空状态（户管尚未创建任何户管）**：表格用 `el-table` 的 `empty` 插槽替换默认「暂无数据」：
- 文案：「你还没有创建任何户管账号」
- 附带一个 primary 按钮「创建户管」（复用 `openCreateDialog`）。
- 理由：默认「暂无数据」不含任何下一步指引；户管首次进入看到空表 + 明确 CTA 是唯一能引导其完成职责（建户管）的入口。被否决：只改文案不加按钮（失去行动入口）。

**行操作收窄的视觉表达**：
- 自己创建的户管行：显示「编辑 / 改密 / 切换角色（仅户管、禁用两项）/ 删除」。
- 非本人创建的户管行：只显示 🔒 图标（复用现有 `!canModify` 分支，`UserManageView.vue:70`）。
- **🔒 tooltip 文案必须为户管单独补一条**：现有文案是 `'不能操作' + (row.role === 'developer' ? '开发者' : '同级管理员')`（`:70`），对户管而言「同级管理员」是错的（对方是另一个户管，不是管理员）。户管专属文案应为「只能操作自己创建的户管」。此点 Task 14 简报未覆盖，是必须补的沟通细节（见 OQ-4）。

### 3.2 角色标签映射

`roleType` / `roleLabel` 需补 `huguan`（Task 14 Step 6 已给：`primary` / 「户管」）。此为纯增量，既有角色标签不变。

### 3.3 决策表

| 决定 | 理由 | 被否决的选项 |
|---|---|---|
| 标题保持「用户管理」+ 户管加一行灰色说明 | 与导航一致；用说明行传达「只能操作自己创建的」这条不可见规则 | 标题改为「户管账号管理」（与导航文案脱节，引入新术语） |
| 平台 Tab 对户管隐藏 | 户管列表口径是「我创建的户管」，与平台维度无关 | 显示但禁用（死控件） |
| 创建角色下拉：户管只显示「户管」单选项且禁用 | 如实传达「只能建户管」，视觉更短 | 禁用但保留四选项（简报 Step 2 的做法，暗示可选范围错误） |
| 创建按钮/弹窗标题改「创建户管」 | 如实反映唯一可创建对象 | 保持「创建用户」（误导） |
| 空状态给文案 + CTA | 首次进入无任何数据时引导完成唯一职责 | 默认「暂无数据」（无指引） |
| 非本人户管行 🔒 + 户管专属 tooltip | 明确「只能操作自己创建的」边界 | 沿用「同级管理员」文案（错误语义） |

---

## 4. Task 15 — TT 设置页拆出选项编辑区

### 4.1 现状与唯一需要改的地方

| 文件 | 现状 | 结论 |
|---|---|---|
| `tt/TtSettingsPanel.vue:66-70` | 一个 `v-if="isAdmin || isDeveloper"` 同时罩住「代理/状态/回收原因」选项卡片（`:68` 的 `adminOptionCards`）**和**「Google 表格配置」卡片 | **要拆**（唯一改动点） |
| `SettingsPanel.vue`（GG） | 4 张选项卡片在 `:10-64` 的 `v-if` **之外**，`:65-104` 的 `v-if` 只罩「充值表配置」 | **不改**，户管本就可见 |
| `fb/FbSettingsPanel.vue` | 全文无角色判断 | **不改** |

### 4.2 拆分的视觉方案

在 TT 设置「账户设置」Tab 内，目标视觉顺序（自上而下）：
1. **商务人员选项卡片**（现状已无任何 `v-if`，所有角色可见，保持不变）
2. **代理名 / 账户状态 / 回收原因 三张选项卡片** ← 从管理员块中**上移**，门控改为 `isAdmin || isDeveloper || isHuguan`
3. **Google 表格配置卡片**（含「仅管理员」标签、Sheet URL、Sheet 映射）← 保持 `isAdmin || isDeveloper`，户管不可见

做法：把 `adminOptionCards` 的 `el-row`（`:69-121`）**整体**搬到 `:67` 的 `<template v-if>` 之前，换一个 `v-if="authStore.isAdmin || authStore.isDeveloper || authStore.isHuguan"`；原 `<template>` 内只留 Google 表格配置。选项卡片的内部实现（`handleAdminDelete / startAdminTagEdit / ...` 及 `adminLists / adminEditingId` 等）**一行不改**，只换外层容器与 `v-if`（Task 15 Step 1 已明确此约束）。

### 4.3 决策表

| 决定 | 理由 | 被否决的选项 |
|---|---|---|
| 只改 `TtSettingsPanel.vue`，把选项卡片上移出管理员块 | GG/FB 两处核实无需改；改动最小、行为保持 | 顺手「统一」三个设置页（违反纯增量，Task 15 明确禁止） |
| 选项卡卡片独立门控 `|| isHuguan`，sheet 配置保持仅管理员 | 户管的 sheet 配置属子项目 B，本需求不开放 | 把 sheet 配置一起放行户管（越界到子项目 B） |
| 视觉上「选项卡片在上、管理员专属卡片在下」 | 保持管理员块仅剩「真正仅管理员」的内容，层级清晰 | 把选项卡片塞进一个单独的折叠/分区容器（引入新视觉组件，无必要） |

---

## 5. Task 16 — 账户面板「全部用户」筛选下拉

### 5.1 决定（核心新控件）

**组件**：一个共享组件 `OwnerFilterSelect.vue`，8 个面板复用。`visible = auth.canManageAccounts`（developer + admin + huguan 都看到）。

**位置**：各面板筛选栏内、**紧随最后一个既有筛选控件之后**，与同行控件 `gap:8px` 对齐。
- GG 广告账户（`AdsAccountPanel.vue`）：插在时区下拉之后（`:42` 后，`:34-44` 筛选行）。
- GG MCC（`MccPanel.vue`）：插在搜索/等级关键词同一行（`:11-14`）。
- FB 广告账户/BM/像素（`FbAccountPanel.vue:32-43`、`FbBmPanel.vue:38-51`、`FbPixelPanel.vue:31-37`）：插入 `filter-bar`。
- TT 广告账户（`TtAccountPanel.vue`）：**替换**现有「全部投手」下拉（`:45-47`）。
- TT BC（`TtBcPanel.vue:8-15`）：插入工具栏。

**默认值与标签**：默认 `''`（空 = 不筛选 = 显示全部用户），占位文案 **「全部用户」**，`clearable` + `filterable`，宽度 150px（与 TT 现有「全部投手」一致）。清空即回到全部。

**与搜索/既有筛选的交互**：`owner_id` 是**独立的 AND 筛选维度**，与搜索、状态下拉、MCC/代理/时区等叠加；`@change` 时重置页码到 1 并重载（复用各面板既有的 `searchAndLoad` / `filterAndLoad` / `loadData`，多数已内含页码重置）。

**空/加载行为**：
- 下拉数据来自 `GET /api/platform/users`，**加载失败或为空不阻塞主流程**（静默），下拉保持可见（占位「全部用户」），确保用户仍能清空已选值回到全部。
- `hidden` 用户不出现在下拉（接口口径已过滤）；developer 会出现在下拉（沿用 `/api/tt/users` 既有口径，需求 7.9 明确保持此行为不变）。

**对「户管 scope 是单用户」的澄清**：这个前提**不成立**。户管在**账户域**（Task 16 的下拉）的可见范围是**当前平台的全部用户**，不是单用户——需求 2.3 / 3.3 把户管并入 `CROSS_USER_ROLES`，无 `owner_id` 时列表返回全平台账户。「只能操作自己创建的」这一单用户收窄**只发生在用户管理页（Task 14）**，与账户面板筛选下拉无关。因此户管看到的下拉与 admin/developer 形态一致：全平台用户列表，默认「全部用户」。选中一个名下无账户的户管 → 得到空列表（需求 7.9 已预期，属可接受行为）。

### 5.2 决策表

| 决定 | 理由 | 被否决的选项 |
|---|---|---|
| 抽成共享组件 `OwnerFilterSelect`，8 面板复用 | 8 处结构完全同构（`v-model` + `@change`），复制粘贴 8 份是设计债 | 每面板各写一份（不一致、难维护） |
| `visible = canManageAccounts` | developer/admin/huguan 均跨用户可见（`CROSS_USER_ROLES`），三种角色都该看到 | 仅 `isHuguan`（admin/developer 看不到，且与后端能力不一致） |
| 默认「全部用户」（空值 = 全部） | 与后端无 `owner_id` 即返回全量一致，首次进入即看到完整列表 | 默认选中「自己」（缩小初始视野，与跨用户角色定位冲突） |
| 占位文案「全部用户」 | 需求 六.2 与 3.8 均用「全部用户」，语义最准确 | 沿用「全部投手」（仅 TT 术语，且对 admin/huguan 语义偏窄） |
| 与既有筛选叠加为 AND，`@change` 重置页码 | 复用各面板既有筛选模式，行为可预期 | 单选互斥（破坏「按用户 + 按状态」组合查询） |
| 加载失败静默、下拉保持可见 | 不阻塞主流程；保证已选值仍可清空 | 失败时隐藏下拉（用户无法清空已选的 `owner_id`） |
| 户管看全平台用户（非单用户） | 账户域户管是跨用户角色（需求 2.3/3.3） | 误把「单用户」收窄套到账户筛选（与后端矛盾） |

---

## 6. 待人工确认（Open Questions）

> 每项只列一句，供裁决。标 ⚠️ 的为需要跑起应用才能定，其余为文档冲突/歧义。

1. **OQ-1（Task 16 自相矛盾）**：简报 Step 6 写「admin 不应出现该下拉」又写「admin 也会看到该下拉，这是可接受的」——需确认 admin 是否在 FB/GG 面板看到「全部用户」下拉。**我的推荐：是**（`canManageAccounts` 含 admin、后端 `CROSS_USER_ROLES` 含 admin），但注意这会**把 admin 在 FB/GG 的可见性从「只看自己」扩大到「跨用户」**，是行为变化，需确认属预期。
2. **OQ-2（首页按钮未被覆盖）**：`AppSidebar.vue:4` 品牌按钮跳转既不在 Task 12 也不在 Task 13 覆盖范围内，且它把 path 传给 `selectTab`（该函数只认 key，疑似既有 bug）。需确认户管点品牌按钮的落点与是否需要一并修。
3. **OQ-3（重定向实现来源冲突）**：Task 13 Step 3 用 `localStorage.getItem('user')` 读角色，与需求 3.7「auth store 暴露 `homePath` getter」冲突。推荐用 `homePath`，但需确认 redirect 执行时 Pinia store 已初始化；否则退回 localStorage 方案。
4. **OQ-4（🔒 tooltip 文案缺口）**：`UserManageView.vue:70` 的「不能操作同级管理员」对户管（对方是另一个户管）语义错误，需补户管专属文案「只能操作自己创建的户管」；简报未覆盖，请确认采纳。
5. **OQ-5（TT 下拉文案变化）**：`TtAccountPanel.vue:45` 现有「全部投手」被共享组件替换后，占位从「全部投手」变「全部用户」，admin/developer 在 TT 面板会看到文案变化——是否接受。
6. **OQ-6（像素BM 面板无筛选栏）**：`FbPixelBmPanel.vue` 目前**没有任何筛选栏/搜索框**，Task 16 简报「与 search 同处」不成立。需决定：为其新增一个筛选栏容器，还是把下拉放在工具栏/表格卡片 header。
7. **OQ-7（创建角色下拉形态）**：Task 14 Step 2 显式要求「禁用但保留四选项」，与我的「只显示『户管』单选项」建议冲突，请裁决取哪种。
8. **OQ-8（户管列表的平台口径与平台列）**：需求 3.6.2 只给户管列表加 `role_filter=huguan`，未提平台过滤；户管列表是否跨平台显示其创建的全部户管？若跨平台，「平台」列对户管是否有意义、是否隐藏。
9. **⚠️ OQ-9（需人工确认）**：`/api/platform/users` 对户管返回正确平台的用户，依赖 `client.js` 的 platform 注入放开给户管（需求 3.2，属 Task 11）。需跑起应用确认户管切到 TT/FB 后该下拉数据随平台正确切换，且面板重挂载时会重新拉取。
