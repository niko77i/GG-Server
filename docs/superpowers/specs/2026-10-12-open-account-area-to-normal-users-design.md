# 普通用户放开账户区（广告账户 / MCC / 设置）（设计）

> 2026-10-12。用户原话：「帮我吧用户权限放开，除了没有管理，广告账户，mcc这些都放开」。
> 追加确认：连「设置」页一起放开。

## 一、需求描述

普通用户（`role='user'`）此前进不了 GG 账户区的三页 —— **广告账户**（`/accounts/ads`）、
**MCC 管理**（`/accounts/mcc`）、**设置**（`/accounts/settings`），点进去被弹回
`/accounts/products`。本次放开这三页；**「管理」（用户管理 / 定时任务）保持仅管理员**。

### 现状诊断（2026-10-12 实测代码）

**挡住普通用户的纯粹是前端路由守卫**，后端本来就是放行的：

- `frontend/src/router/index.js` 三页带 `meta: { admin: true }`，
  守卫 `if (to.meta.admin && !auth.isAdmin && !(...))` 把普通用户弹回。
- 后端 `py/main.py` 的 `/api/accounts/*`、`/api/mcc/*`、`/api/recharge/*`
  **全部只有 `@jwt_required()`**（已逐条核对全部 45 条路由的装饰器栈），
  数据按 `owner_id` 隔离；`mcc_update` / `mcc_delete` / `mcc_batch_delete`
  另有归属校验（`owner_id != user_id and not _cross_user_actor` → 403）。
- 即：**这是「UI 挡了、API 没挡」的错配**，去掉 `meta.admin` 即通。

FB / TT 的账户页**本来就没有 `meta.admin`** —— GG 侧是三个平台里的例外，本次改动即对齐 FB/TT。

## 二、已确认的决策（用户 2026-10-12 逐条裁定）

| # | 决策 |
|---|---|
| 1 | 走 **master 直接改**，**不开 worktree**（改动小、冲突面窄） |
| 2 | 范围 = **广告账户 + MCC 管理 + 设置** 三页 |
| 3 | 「管理」（用户管理 / 定时任务）**不放开** |
| 4 | 设置页里字典表的写入口对普通用户**隐藏**（用户已知悉后端仍会 403） |

## 三、技术方案

### 3.1 关键判断：不能放宽 `canManageAccounts`

`authStore.canManageAccounts` = `['developer','admin','huguan']`，看着像「能不能用账户功能」，
实际是**「跨用户管账户」开关**，全站 20 处在用：归属人下拉（`OwnerFilterSelect`）、
批量导入的逐行编辑、`AccountModal` 的认领分支、`MccPanel` 的行内编辑按钮、FB 三张
全局字典的写入口……**放宽它等于把编辑别人数据的权限一并给了普通用户**。

### 3.2 把一条判据拆成三条（新增 `src/utils/accessLogic.mjs`）

纯函数模块（`.mjs`，供 `node --test` 直接 import，同 `columnPrefsLogic` / `platformPrefs` 的做法）：

| 常量 | 值 | 含义 |
|---|---|---|
| `ACCOUNT_PAGE_ROLES` | developer / admin / huguan / **user** | 能进账户区三页 |
| `GLOBAL_OPTION_ROLES` | developer / admin / huguan | 能改全局字典（镜像后端同名的 `GLOBAL_OPTION_ROLES`） |
| `CROSS_USER_ACCOUNT_ROLES` | developer / admin / huguan | 能管**别人**的账户 / MCC（= 原 `canManageAccounts`） |

三条组成阶梯：`跨用户管账户 ⊆ 改全局字典 ⊆ 能进账户区`，**只有 `user` 落在「进得去、改不了」那一档**。
`viewer` 三档全否（它止步于 `/accounts/products`，router 另有硬拦）。

⚠️ 这三个常量**镜像后端** `py/routes/helpers.py`，改一侧必须同步改另一侧。

### 3.3 改动清单（全部前端）

| 文件 | 改动 |
|---|---|
| `src/utils/accessLogic.mjs` | **新增**，三个常量 + 三个谓词 |
| `src/stores/auth.js` | 新增 `canAccessAccounts` / `canEditGlobalOptions`；`canManageAccounts` 改为走模块（值不变） |
| `src/views/AccountsView.vue` | 三个 Tab 的 `v-if` 由 `canManageAccounts` → **`canAccessAccounts`** |
| `src/router/index.js` | 三页去掉 `meta.admin`；`HUGUAN_ROUTES` 注释更新（该表现仅对 `/admin/users` 生效） |
| `src/views/SettingsPanel.vue` | **仅**地区/时区三处编辑控件由 `canManageAccounts` → `canEditGlobalOptions`（语义对齐）；四张 owner 隔离字典卡片的写入口**保持原样** |

**侧边栏无需改动**：账户区的四个子项本就没有 `admin` 标记（此前是「菜单看得见、点进去被弹回」
的既有瑕疵），Tab 放开后自然通；「管理」项由 `visibleNavItems` 的 `n.admin` 过滤，普通用户看不到。

### 3.4 设置页为什么只动了「地区/时区」那一处（含一次自我纠错）

最初我把「账户设置」Tab 里**五张**字典卡片的写入口（`+` / 可关闭标签 / 双击改名 / 提示语）
统一按 `canEditGlobalOptions` 隐藏了，**这是错的，已回退**（`git checkout -- SettingsPanel.vue`）。

错在把「五张字典都有后端 403 闸门」当成了事实。逐条核对 `main.py` 后确认
**只有 `regions`（地区）**被硬校验 `GLOBAL_OPTION_ROLES`：

| 字典表 | `_create` 闸门 | `_rename` / `_delete` | 实际归属 |
|---|---|---|---|
| `regions` | **有**（`GLOBAL_OPTION_ROLES`，全书唯一硬闸） | 有 | 全平台共享，一改对所有人生效 |
| `agents` / `account_statuses` / `mcc_levels` / `sales_persons` | **无闸门** | 限 `owner_id` 本人行 | **owner 隔离**，普通用户本就能增删改**自己的** |

所以按「五张都藏」去做，等于**把普通用户建自己的 MCC 等级的能力也一并砍掉** ——
而 MCC 等级恰恰是他建 MCC 时的必填下拉（见 `2026-10-12-mcc-level-default-design.md`）。
现口径：只把地区/时区三处控件改判据为 `canEditGlobalOptions`，其余四张卡片不动。

设置页其余各 Tab 无需改动：充值表配置本就 `isAdmin || isDeveloper`；户管看板卡片自带
`v-if="isHuguan"`。

## 四、验证

- `frontend/tests/accessLogic.test.mjs`：**9 条**用例（含全角色真值表、viewer 全否、
  未知角色不 fail-open、`跨用户 ⊆ 全局字典 ⊆ 账户区` 的子集不变式）。`node --test` → 79 通过 / 0 失败。
- 后端闸门：逐条导出全部账户/MCC/充值/字典路由的装饰器栈，确认账户类仅有 `@jwt_required()`、
  字典写有 `GLOBAL_OPTION_ROLES` 校验。
- 产物核对：`npm run build` 后确认 dist 包内含 `canAccessAccounts`，且 `path:"ads"` /
  `path:"settings"` 的 `meta` 已无 `admin`。

## 五、遗留 / 范围外

- ~~**未做真机端到端实测**~~ → **2026-10-12 已由用户在运行中的服务上实测**（新增 MCC 时命中
  一条与权限无关的既有 bug，见 `2026-10-12-mcc-level-default-design.md`）。三页路由与 Tab
  确实对普通用户放开了，「设置」页也因此暴露了上面那次自我纠错。
- `frontend/package.json` 的 `npm test`（`node --test tests/`）在 Node 24 上**本来就跑不起来**
  （把 `tests/` 当成模块名加载 → `MODULE_NOT_FOUND`）。本次未修，需用
  `node --test tests/*.test.mjs` 绕过。**属既有缺陷，与本次改动无关**（已在改动前用 git stash 验证）。
