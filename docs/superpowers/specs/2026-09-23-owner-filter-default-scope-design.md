# 账户面板「归属人」默认作用域（默认只看自己）设计

- 日期：2026-09-23
- 状态：已确认（2026-09-23）
- 类型：前端行为变更（默认筛选值），不涉及后端接口语义变更

---

## 1. 需求背景

开发者（卡尔）登录后进入「账户管理 → 广告账户」，看到的各状态户数量是 **存活 99**，而他自己的户只有 23 个。原因不是跨系统混算（`accounts`/`fb_accounts`/`tt_accounts` 是三张独立物理表，不可能混），而是：

- `developer`/`admin`/`huguan` 属于 `CROSS_USER_ROLES`，后端 `/api/accounts/list` 对这三个角色 **不加 owner 约束**，返回全部人的户；
- 前端「归属人」下拉 `OwnerFilterSelect` 的默认值恒为空（placeholder 字面写死 `全部用户`），所以进页面即等于「全部用户」。

结果：进入账户面板的默认视图是「全公司所有人的户」，与使用者的直觉（"我进来是看我自己的户"）相反，数字也对不上自己名下的量。

**用户裁定**：developer / admin 进入页面时「归属人」默认选中自己；「全部用户」仍可手动切换；**户管（huguan）保持默认「全部」**。

---

## 2. 需求描述

| 角色 | 面板默认「归属人」 |
|---|---|
| developer | 自己 |
| admin | 自己 |
| huguan | 全部（不变） |
| user / viewer | 不显示该下拉（不变） |

「全部用户」与「任意指定用户」必须仍可手动选到——默认值只影响首屏，不限制能力。

---

## 3. 关键约束（本次排查新发现，决定了方案形态）

### 3.1 跨平台会做出「空表」，默认值必须带平台条件

各人在各平台的实际户数：

| 用户 | 角色 | `users.platform` | GG 户 | TT 户 |
|---|---|---|---|---|
| 卡尔 | developer | gg | 263 | **0** |
| 阿伟 | admin | gg | 58 | **0** |
| 黎明 | admin | tt | 0 | 49 |
| 户部尚书 | huguan | gg | 0 | 0 |

开发者可以通过侧边栏切到 TT 面板。如果 TT 面板也无条件「默认选自己」，**卡尔一进 TT 账户页会看到空表**（他在 TT 一个户都没有）——那不是「只看自己」，是「什么都看不到」，比现状更糟。

因此默认值必须带平台判定：**只有当「本人所属平台」== 「当前所看面板的平台」时才默认自己**，否则回退「全部」。

### 3.2 该条件天然覆盖三种角色，无需分别写分支

- **admin**：`PLATFORM_SWITCH_ROLES = ("developer", "huguan")` 不含 admin，且路由守卫 `if (to.meta.platform && !auth.canSwitchPlatform)` 会把跨平台访问弹回，所以 admin 的 `effectivePlatform` 恒等于 `user.platform` → 条件恒真 → 等于「admin 默认自己」。已核实：FB 管理员白白、TT 管理员黎明都只会看到本平台面板。
- **developer**：`effectivePlatform` = `currentPlatform`（侧边栏 `switchPlatform` 写入），条件等价于「我在看我本平台的账户」。
- **huguan**：单独短路 → 恒为「全部」（用户裁定）。

### 3.3 已知边界（诚实记录）

平台条件只排除「跨平台必然为空」这一种情况，不保证同平台一定有户。同平台但名下 0 户的用户（如 GG 的 阿信/柠檬/蜻蜓）依然会看到空表。**不为此加额外逻辑**：下拉就在旁边，点 × 清空即回到「全部用户」，成本极低；若加「自动回退全部」会引入「为什么有时默认我、有时默认全部」的不可预期行为。

---

## 4. 技术方案

### 4.1 落点：共用组件内实现（单点改动）

`OwnerFilterSelect.vue` 被 **8 个面板**共用：

| 平台 | 面板 | 位置 |
|---|---|---|
| GG | 广告账户 | `views/AdsAccountPanel.vue:41` |
| GG | MCC 管理 | `views/MccPanel.vue:13` |
| FB | 广告账户 | `views/fb/FbAccountPanel.vue:38` |
| FB | BM | `views/fb/FbBmPanel.vue:49` |
| FB | 像素 | `views/fb/FbPixelPanel.vue:35` |
| FB | 像素-BM | `views/fb/FbPixelBmPanel.vue:56` |
| TT | 广告账户 | `views/tt/TtAccountPanel.vue:45` |
| TT | BC | `views/tt/TtBcPanel.vue:15` |

已核实这 8 个面板的后端**全部**支持 `owner_id` 过滤（`main.py:3735`、`main.py:5481`、`fb_routes.py` 6 处、`tt_accounts_routes.py:208`、`tt_routes.py:35`），所以在组件内实现默认值在每一处都成立。

在组件内做的理由：
1. **口径统一**——同平台内不会出现「账户页默认自己、MCC/BC 页默认全部」的分裂；
2. **DRY**——1 个文件 vs 8 处（其中 GG 走 Pinia `acFilters.owner_id`、TT/FB 走本地 `ref`，分散实现易漏改）；
3. 组件已有 `watch(() => auth.user?.id, …, { immediate: true })` 的生命周期处理，复用即可。

> 说明：用户此前的授权是「GG / TT 一起改」。共用组件方案会把 FB 4 个面板与 MCC/BC 面板一并纳入。**此超出原有授权范围之处已于 2026-09-23 确认通过**（选择「共用组件，各处统一」），落地范围为全部 8 处。

### 4.2 默认值规则（单一表达式）

```
默认「归属人」= 本人 id   ⟺  canManageAccounts
                          AND role !== 'huguan'
                          AND user.platform === effectivePlatform
          否则            = ''（即「全部用户」）
```

### 4.3 代码骨架

`frontend/src/components/OwnerFilterSelect.vue`（增量，不改现有 `fetchUsers` / `onChange` / `visible`）：

```js
const props = defineProps({ modelValue: { type: [String, Number], default: '' } })

// ★ 关键：身份水合必须赶在面板首次 load() 之前（理由见下方「首屏时序」）
if (!auth.user) auth.initFromStorage()

// 身份就绪后：拉用户列表 + 首次套用默认作用域（沿用既有 watch，不新增生命周期钩子）
watch(
  () => auth.user?.id,
  (uid) => {
    if (uid && visible.value) {
      fetchUsers()
      applyDefaultScope()
    }
  },
  { immediate: true }
)

// 默认作用域：developer/admin 进本平台面板时默认选中自己；户管与跨平台面板保持「全部」。
// 只在「父组件尚无值」时套用 —— 用户手动清空/选择后不再干预（watch 只认 user.id 变化）。
function applyDefaultScope() {
  const v = props.modelValue
  if (v !== '' && v !== null && v !== undefined) return   // 父组件已有值（含用户已选）→ 不干预
  const def = defaultOwnerScope(auth.user, auth.effectivePlatform)
  if (def !== '') onChange(def)
}
```

要点：
- `onChange` 同时 `emit('update:modelValue')` 与 `emit('change')`，父组件的 `v-model` 同步赋值先于 `@change` 回调执行（`TtAccountPanel` 的 `ownerId.value`、GG 的 `store.acFilters.owner_id` 都是同步写入），因此 `@change="searchAndLoad"` 里读到的已是新值，**不会**出现「用旧值查一次」。

#### 首屏时序（本方案的核心风险点，初版曾在此处出错）

`App.vue` 把 `initFromStorage()` 放在**根组件的 `onMounted`** 里，而 Vue 的挂载顺序是「子先父后」：面板的 `onMounted`（发起首次 `load()`）**早于** 根组件的 `onMounted`。本仓库 `UserManageView.vue:218` 已记录过同一教训（「不能在 ref 初始值里读 authStore，此刻 user 可能仍为 null」）。

于是刷新页面时的时序是：

1. 面板 setup → 子组件（本组件）setup → **面板 `onMounted` → `load()` 带着 `owner_id=''` 发出 R1**；
2. 根组件 `onMounted` → `initFromStorage()` 写入 `auth.user` → 本组件 watch 触发 → 写入 `owner_id` 并 `emit('change')`；
3. 但 GG/MCC 面板的 `loadAccounts`/`loadMccList` 走 `dedupLoader`（`utils/dedupLoader.js`）：**R1 仍在途 → 直接返回 R1 的 Promise，不会重发**。

结果：**下拉显示「自己」，表格却是全部用户** —— 恰是本次要修的 99 症状原样复现，且无任何报错。

因此本组件在 setup 阶段先补一次 `auth.initFromStorage()`（幂等，只读 localStorage 回填，与根组件稍后的调用结果一致）。组件 setup 恒早于面板 `onMounted`，默认值于是赶在 R1 之前写进筛选状态：

- `auth.user` 原本就绪（SPA 内部跳转）→ 首次请求即带对 `owner_id`；
- `auth.user` 尚未水合（刷新）→ 本组件补完水合 → 同上。

首屏请求次数按面板分两类（均已核实）：

| 面板 | 次数 | 原因 |
|---|---|---|
| GG 广告账户 / MCC | **1** | 走 `dedupLoader`：`onMounted` 的第二次 `load()` 被在途的首次请求吞掉，合并为一次 |
| FB ×4 / TT ×2 | **2** | 无 dedup：本组件 setup 期的 `emit('change')` 触发一次，面板 `onMounted` 再触发一次 |

FB/TT 的两次请求**值都正确**（都带默认 `owner_id`），仅多一次冗余请求、无正确性影响。若要去掉，需让主路径只 `emit('update:modelValue')` 不 `emit('change')`（仅身份晚于面板首次 load 时才补 `change`）—— 代价是引入一个 `mounted` 标志与分支，而为兜的残留边界（见下）经正常 UI 操作不可达，故**不采用**，维持现状。

> 残留边界：若浏览器存在 token 但 localStorage 无缓存的 user 对象（UI 登录流程不会产生此状态，`login()` 必同时写入两者），则身份只能由异步 `fetchMe()` 补齐，此时 `user.id` 的首次变化发生在面板已 load 之后，`change` 仍会被 dedup 吞掉。该状态无法经正常操作产生，不额外加防护。

### 4.4 「全部用户」可达性（不得破坏）

- `el-select` 保留了 `clearable` → 点 × 即回到「全部」；
- 下拉仍列出 `/api/platform/users` 的全部用户 → 可切到任意他人；
- 默认值只在 `user.id` 变化且 `modelValue` 为空时套用 → 用户清空后不会被打回。

### 4.5 后端：零改动

`/api/accounts/list` 等接口的 `owner_id` 语义（空 = 不约束 = 全部）保持不变。前端只改「默认传什么」，不新增参数、不改判定。这满足**纯增量原则**：户管的「默认全部」、后端对 `CROSS_USER_ROLES` 的放行逻辑全部原样保留。

---

## 5. 涉及文件

| 文件 | 改动 |
|---|---|
| `frontend/src/utils/ownerScope.js` | 新增纯函数 `defaultOwnerScope(user, effectivePlatform)` |
| `frontend/src/components/OwnerFilterSelect.vue` | 新增 `props` 具名接收、setup 阶段的 `auth.initFromStorage()` 兜底水合、`applyDefaultScope()`，并在既有 watch 内调用 |

**不改动**：全部 8 个面板、`stores/accounts.js`、`stores/auth.js`、所有后端文件。
（`stores/auth.js` 仅被**调用**其既有公开 action `initFromStorage()`，文件本身零改动。）

前端无组件测试框架，故不新增测试文件；`ownerScope.js` 的纯函数用仓库外的 Node 脚本验证（见 §6.2）。

---

## 6. 测试

前端无既有组件测试框架时，按 §6.1 手工验收；若仓库已有 vitest 等设施则补 §6.2 单测。

### 6.1 手工验收矩阵

| # | 身份 | 面板 | 期望 |
|---|---|---|---|
| 1 | 卡尔 / developer / gg | GG 广告账户（**刷新页面进入**） | 下拉默认显示「卡尔」，**且表格确实是其名下 263 户**（存活 22，非 98）—— 验证 §4.3 的时序修复 |
| 2 | 卡尔 / developer / gg | 同上，从别的页面**跳转**进入 | 同 1，且只发 1 次列表请求（Network 面板确认） |
| 3 | 卡尔 / developer / gg | 切到 TT 广告账户 | 下拉为「全部用户」（**不得**是空表） |
| 4 | 阿伟 / admin / gg | GG 广告账户 | 默认「阿伟」 |
| 5 | 阿伟 / admin / gg | 访问 `/tt/accounts` | 被路由守卫弹回本平台（不因默认值出现异常） |
| 6 | 黎明 / admin / tt | TT 广告账户 | 默认「黎明」 |
| 7 | 户部尚书 / huguan / gg | GG / FB / TT 账户面板（含刷新） | 一律「全部用户」（**关键回归，不得改变**） |
| 8 | 卡尔 / developer / gg | GG 广告账户 → 点下拉 × 清空 | 切回「全部用户」且不被自动打回自己 |
| 9 | 卡尔 / developer / gg | GG 广告账户 → 手动选「阿伟」 | 正常按其筛选，刷新前不被覆盖 |
| 10 | 卡尔 / developer / gg | GG「MCC 管理」（刷新进入） | 同样默认「卡尔」（验证 8 处口径统一） |

> 若在 Network 面板核对：GG 两个面板首屏应为 **1 次**列表请求；FB/TT 面板为 **2 次**（两次都带默认 `owner_id`，属已知冗余，见 §4.3）。

### 6.2 组件单测（若有设施）

- `role='huguan'` → 不 emit 默认值；
- `role='developer'` 且 `user.platform === effectivePlatform` → emit `user.id`；
- `role='developer'` 且 `user.platform !== effectivePlatform` → 不 emit；
- `modelValue` 已非空 → 不 emit。

### 6.3 回归

`cd py && python -m pytest tests/ -q` 应保持全绿（本次不动后端，预期无影响，作为兜底）。

---

## 7. 不做的事（YAGNI）

- **不改后端**，不新增「默认只看自己」的服务端参数；
- **不处理**「同平台但名下 0 户 → 空表」的自动回退（见 §3.3）；
- **不持久化**默认值到 localStorage（刷新即重算，行为可预期）；
- **不顺手改** 历史遗留的 `COALESCE(st.name,'存活')` 显示层掩盖问题，以及 69 户 `status_id` 悬空——那是独立的**数据订正**议题，已有取证与恢复方案，与本需求解耦，另行裁定。

---

## 8. 已确认决议（2026-09-23）

1. **落地范围**：按 §4.1 在共用组件 `OwnerFilterSelect.vue` 实现，覆盖全部 8 处，口径统一。
2. **`/frontend-design`**：不需要。本次无新增视觉元素、无样式与布局改动，仅是既有下拉的初始值变化，按 CLAUDE.md「简单样式微调不受限」的口径跳过视觉设计流程。
