# 户管角色 设计文档

> 日期：2026-09-22
> 状态：待确认
> 范围：子项目 A（角色与权限）。子项目 B（户管看板 Google Sheet 配置与写表）另出设计文档。

## 一、需求描述

新增「户管」角色，负责 GG / FB / TT 三个平台的广告账户与 MCC / BC / BM 管理。

1. **账户管理对象**：广告账户、MCC（GG）、BC（TT）、BM / 像素（FB）。
2. **全部编辑权限**：可对上述对象新增、编辑、删除，并可变更账户归属（重新分配）。
3. **按用户筛选**：可按用户筛选查看对应用户名下的账户；可见用户范围**按当前所在系统隔离** —— 切到 TT 就只看到 TT 平台的用户，切到 GG 就只看到 GG 平台的用户。
4. **可切换系统**：户管登录后可像 developer 一样在 GG / FB / TT 之间自由切换。
5. **设置下拉选项权限**：可编辑代理名、账户状态、MCC 等级、地区时区、商务人员等平台级下拉选项。
6. **不具备的权限**：用户管理、定时任务。

## 二、现状分析

### 2.1 角色与平台

- [py/auth.py:399-411](py/auth.py) 附近的 `users` 表：`role`（`developer` / `admin` / `user` / `viewer` / `hidden`）、`platform`（`gg` / `fb` / `tt`，默认 `gg`）。
- 前端角色判断集中在 `frontend/src/stores/auth.js` 的 getter：`isAdmin`、`isDeveloper`、`isViewer`、`canAccessProducts`、`effectivePlatform`。

### 2.2 平台切换机制（已有，可复用）

三层配合，无需新建机制：

| 层 | 位置 | 现状 |
|---|---|---|
| 前端状态 | `frontend/src/stores/auth.js` | `currentPlatform` + `effectivePlatform`：developer 用 `currentPlatform`，其他人用 `user.platform` |
| 请求注入 | `frontend/src/api/client.js:13` | `user.role === 'developer'` 时按当前路由前缀注入 `params.platform` |
| 后端解析 | `py/main.py:5775 _get_effective_platform()` | `role in ('developer', 'admin')` 时取 `request.args['platform']`，否则取 `user.platform` |

### 2.3 跨用户可见性现状（**关键：三平台不一致**）

| 平台 | 位置 | 现状 |
|---|---|---|
| TT 账户 | `py/routes/tt_accounts_routes.py:209` | `role in ('developer','admin')` → 不加 owner 过滤，且**已支持 `owner_id` 查询参数筛选**；非管理角色强制只看自己 |
| FB 账户 | `py/routes/fb_routes.py:264` | `role not in ('developer','admin')` → 强制只看自己；**无 `owner_id` 筛选参数** |
| GG 账户 | `py/main.py:3635` | **硬编码 `a.owner_id = ?`**，没有任何跨用户分支 |
| GG MCC | `py/main.py:5276` | 权限模型是 `owner_id = 自己 OR shared_user_ids 含自己`，没有跨用户分支 |

结论：**TT 已具备完整的目标形态**（跨用户 + `owner_id` 筛选），是本设计的参照模板；FB 缺筛选参数；GG 两项都缺。

### 2.4 前端现状

- TT 账户面板 `frontend/src/views/tt/TtAccountPanel.vue:45` **已有「全部投手」筛选下拉**（`v-if="isAdmin"`），:330 传 `params.owner_id`，:317 调 `/api/tt/users` 取列表。这是可复用的前端模板。
- GG 账户面板、FB 账户 / BM / 像素面板均无用户筛选下拉。
- 路由守卫 `frontend/src/router/index.js:170` 用 `!auth.isDeveloper` 判断是否允许跨平台访问。

### 2.5 已有缺口（本设计不修复，仅记录）

`py/main.py:4052 accounts_update`（GG 账户编辑）**没有归属校验**，按 `id` 直接更新，任意登录用户可修改任意账户。这不是本需求引入的，本设计不改变它的行为（纯增量原则），仅在设计文档中标注，供后续单独处理。

## 三、技术方案

核心思路：**把「户管」加入已有的跨用户角色集合，而不是新建一套权限机制**。不新增表、不新增分配关系、不引入权限位图。

### 3.1 角色常量（后端单一事实来源）

在 `py/routes/helpers.py` 中新增：

```python
HUGUAN_ROLE = "huguan"

# 可跨用户查看/编辑账户类数据的角色（账户、MCC、BC、BM、像素）
CROSS_USER_ROLES = ("developer", "admin", HUGUAN_ROLE)

# 可编辑平台级下拉选项的角色（代理名、账户状态、MCC等级、地区时区、商务人员）
GLOBAL_OPTION_ROLES = ("developer", "admin", HUGUAN_ROLE)
```

两个常量成员相同、语义不同，分开命名是为了在每个调用点自解释。

**替换方式（需确认）**：现有代码中 `role in ('developer', 'admin')` / `role not in ('developer', 'admin')` 字面量共约 37 处（`tt_routes.py`、`tt_accounts_routes.py`、`fb_routes.py`）+ `main.py` 约 30 处。替换为常量引用，属于**机械替换**：不改变任何现有角色的行为，只是把「户管」加入集合，并把魔法元组收敛为单一事实来源。

- 选项 1（推荐）：按上述语义替换为 `CROSS_USER_ROLES` / `GLOBAL_OPTION_ROLES`。
- 选项 2（最小 diff）：保持字面量，仅逐处把 `('developer', 'admin')` 改为 `('developer', 'admin', 'huguan')`，只在需要的地方加。

### 3.2 平台切换（让户管生效）

| 文件 | 改动 |
|---|---|
| `py/main.py:5775 _get_effective_platform()` | 判断从 `('developer','admin')` 改为 `CROSS_USER_ROLES` |
| `py/routes/decorators.py:50 require_platform()` | `role == 'developer'` 放行改为 `role in CROSS_USER_ROLES`，使户管跨平台调用不被 403 |
| `frontend/src/stores/auth.js` | 新增 `isHuguan`；新增 `canSwitchPlatform = isDeveloper \|\| isHuguan`；新增 `canManageAccounts = isAdmin \|\| isHuguan`；`effectivePlatform` 对 `canSwitchPlatform` 都用 `currentPlatform`；`setPlatform()` 放开给 `canSwitchPlatform` |
| `frontend/src/api/client.js:13` | `user.role === 'developer'` 改为 `['developer','huguan'].includes(user.role)`（需同步 `auth.js` 的 getter 语义） |
| `frontend/src/router/index.js:170` | 平台守卫 `!auth.isDeveloper` 改为 `!auth.canSwitchPlatform` |

**前端 getter 定义集中如下**（`stores/auth.js`）：

```js
isHuguan:        (s) => s.user?.role === 'huguan',
canSwitchPlatform:(s) => ['developer', 'huguan'].includes(s.user?.role),
canManageAccounts:(s) => ['developer', 'admin', 'huguan'].includes(s.user?.role),
```

### 3.3 跨用户账户可见 + 按用户筛选

统一模式（对齐 TT 现有实现）：

```python
if role in CROSS_USER_ROLES:
    if owner_id:            # 来自 ?owner_id= 查询参数
        where.append("a.owner_id = ?"); params.append(owner_id)
else:
    where.append("a.owner_id = ?"); params.append(uid)
```

按对象逐一落地：

| 对象 | 文件 | 改动 |
|---|---|---|
| TT 账户列表 | `py/routes/tt_accounts_routes.py:209,256` | 元组 → `CROSS_USER_ROLES`（筛选已具备） |
| FB 账户列表 | `py/routes/fb_routes.py:264` | 元组 → 常量，**新增 `owner_id` 筛选参数** |
| FB BM / 像素 列表 | `py/routes/fb_routes.py:29,64,387,471,739` | 元组 → 常量，按同类模式补 `owner_id` 筛选 |
| GG 账户列表 | `py/main.py:3623` | **新增跨用户分支 + `owner_id` 筛选**（原本完全无此能力） |
| GG MCC 列表 | `py/main.py:5265` | `perm_where` 在 `CROSS_USER_ROLES` 时短路为 `1=1`；新增 `owner_id` 筛选 |

GG 账户列表还需同步处理同一函数内的三处**辅助查询**（状态计数 `sc_where`、`mcc_options`、`agents`、`timezone_options` 缓存键），否则会出现「列表跨用户了、筛选下拉还是自己的」不一致。缓存 key 需按 `owner_id` 维度区分，例如 `accounts:mcc_options:{user_id}:{owner_id or 'all'}`。

**用户筛选下拉的数据源**：新增通用接口

```
GET /api/platform/users
```

返回 `platform = <当前平台> OR role = 'developer'` 且 `role != 'hidden'` 的用户，字段 `id / username / display_name / platform`。当前平台由 `_get_effective_platform()` 解析。

TT 现有的 `GET /api/tt/users`（`py/routes/tt_routes.py:810`）**保留不动**，前端 TT 面板可继续使用或改调通用接口；不删除旧接口。

### 3.4 账户编辑权限

| 文件 | 改动 |
|---|---|
| `py/routes/tt_accounts_routes.py`（多处的 `role not in (...) and row["owner_id"] != uid`） | 元组 → `CROSS_USER_ROLES`，户管即可编辑任意用户账户 |
| `py/routes/fb_routes.py`（:387, :471 等归属校验） | 同上 |
| `py/main.py:4186 accounts_reassign`（GG 归属转移） | 户管可把账户转移给**指定用户**（读取请求体 `owner_id`），而非固定转给自己 |
| `py/main.py:3827 accounts_create`（GG 新建账户） | 户管代建时可指定 `owner_id`；未指定则归属户管自己 |
| `py/main.py:3827` 内 agent / status 的 `owner_id=user_id` 兜底插入 | 代建场景下应使用目标 `owner_id`，避免新建的代理名挂到户管名下 |

### 3.5 设置下拉选项权限

以下接口中 `is_dev = role in ('developer','admin')` 改为 `role in GLOBAL_OPTION_ROLES`：

- `py/main.py` 代理名：`agents_create` / `agents_rename` / `agents_delete`
- `py/main.py` 账户状态：`statuses_create` / `statuses_update` / `statuses_delete`
- `py/main.py` MCC 等级：`mcc-levels` 四个接口
- `py/main.py` 商务人员：`sales-persons` 四个接口
- `py/main.py` 地区时区：`regions` 四个接口（`regions_*`）

### 3.6 用户管理接口（**明确不动**）

`py/main.py` 约 7400–7670 区间的用户管理接口（`admin_create_user`、`admin_update_user`、角色切换、启停、删改密等）保持原样，**不加入户管**。`py/routes/decorators.py:8 admin_required` 与 `py/routes/helpers.py:103 can_modify`、`can_modify_user` 同样保持不变。

> 注意：`can_modify` 目前的判断是 `role in ("developer","admin")`，用于产品 / 视频等内容的编辑权。户管按需求只管账户，**此处不改**，因此户管不会获得产品 / 视频的额外编辑权。

### 3.7 前端导航与路由

| 文件 | 改动 |
|---|---|
| `frontend/src/components/AppSidebar.vue:12` | 平台切换按钮的 `v-if="auth.isDeveloper"` → `auth.canSwitchPlatform` |
| `frontend/src/components/AppSidebar.vue:127` | 账户区菜单的可见性判断 `return auth.canAccessProducts` → `return auth.canAccessProducts \|\| auth.canManageAccounts`（**否则户管看不到账户菜单**） |
| `frontend/src/components/AppSidebar.vue:126-158` | 新增户管专用导航：仅保留账户区与设置，**排除**产品管理、视频管理、媒体工具、工具集、数据分析、管理（用户管理 / 定时任务） |
| `frontend/src/router/index.js:176` | `if (to.meta.admin && !auth.isAdmin) next(platformHome)` → 增加豁免：户管可进入账户区带 `meta.admin` 的路由。建议改为 `if (to.meta.admin && !auth.isAdmin && !(auth.isHuguan && isAccountRoute(to.path)))`，其中 `isAccountRoute` 匹配 `/accounts/{ads,mcc,settings}`、`/fb/{accounts,bms,pixels,settings}`、`/tt/{accounts,bcs,settings}`。**否则户管会被重定向回首页，三个平台的账户页全部打不开** |
| `frontend/src/views/AccountsView.vue:7-9` | GG 顶部 Tab（广告账户 / MCC 管理 / 设置）的 `auth.isAdmin` → `auth.canManageAccounts` |
| `frontend/src/views/UserManageView.vue` | 角色下拉 / 切换下拉新增「户管」选项（仅 developer 可见，见下） |
| `frontend/src/views/SettingsPanel.vue:65`、`tt/TtSettingsPanel.vue:67`、`fb/FbSettingsPanel.vue` | 选项编辑区块的 `authStore.isAdmin \|\| authStore.isDeveloper` → 含户管（与 3.5 后端一致） |

**谁可以授予「户管」角色**：仅 `developer`。理由是户管具备**跨平台**权限，而 `admin` 的作用域仍受平台限制（见另一份 `2026-09-22-user-role-platform-isolation-design.md`），由平台内的 admin 授予跨平台角色会突破隔离边界。后端在 `admin_create_user` / `admin_update_user` / 角色切换接口中校验：非 developer 传入 `role='huguan'` → 403。

**户管导航具体范围**：

| 平台 | 保留菜单 |
|---|---|
| GG | 广告账户、MCC 管理、设置 |
| FB | 广告账户、BM 管理、像素管理、FB 设置 |
| TT | 广告账户、BC 管理、TT 设置 |

### 3.8 前端用户筛选下拉

在以下面板新增「全部用户 / 选择用户」下拉（复用 `TtAccountPanel.vue:45` 的写法与 `ownerId` + `filterAndLoad` 模式）：

- `frontend/src/views/AdsAccountPanel.vue`（GG 广告账户）
- `frontend/src/views/MccPanel.vue`（GG MCC）
- `frontend/src/views/fb/FbAccountPanel.vue`、`FbBmPanel.vue`、`FbPixelPanel.vue`、`FbPixelBmPanel.vue`
- `frontend/src/views/tt/TtAccountPanel.vue`、`TtBcPanel.vue`（把现有 `isAdmin` 判断换成 `canManageAccounts` 即可）

## 四、涉及文件清单

| 文件 | 改动类型 |
|---|---|
| `py/routes/helpers.py` | 新增 `HUGUAN_ROLE`、`CROSS_USER_ROLES`、`GLOBAL_OPTION_ROLES` |
| `py/routes/decorators.py` | `require_platform` 放行户管 |
| `py/routes/tt_routes.py` | 角色元组 → 常量（:30, :125, :158, :569, :1145, :1157, :1169） |
| `py/routes/tt_accounts_routes.py` | 角色元组 → 常量（约 24 处） |
| `py/routes/fb_routes.py` | 角色元组 → 常量 + 列表补 `owner_id` 筛选 |
| `py/main.py` | `_get_effective_platform`；GG 账户列表跨用户 + 筛选；GG MCC 跨用户 + 筛选；`accounts_create` / `accounts_reassign` 归属；设置选项接口角色；新增 `/api/platform/users` |
| `frontend/src/stores/auth.js` | 新增 `isHuguan` / `canSwitchPlatform` / `canManageAccounts` / `roleLabel`，放开 `effectivePlatform`、`setPlatform` |
| `frontend/src/api/client.js` | platform 参数注入放开给户管 |
| `frontend/src/router/index.js` | 平台守卫、账户区守卫用新 getter |
| `frontend/src/components/AppSidebar.vue` | 平台切换按钮 + 户管导航 |
| `frontend/src/views/AccountsView.vue` | GG Tab 权限 |
| `frontend/src/views/SettingsPanel.vue`、`tt/TtSettingsPanel.vue`、`fb/FbSettingsPanel.vue` | 选项编辑权限 |
| `frontend/src/views/UserManageView.vue` | 角色下拉新增「户管」 |
| `frontend/src/views/AdsAccountPanel.vue`、`MccPanel.vue`、`fb/*.vue`、`tt/TtAccountPanel.vue`、`tt/TtBcPanel.vue` | 用户筛选下拉 |
| `py/tests/` | 新增户管权限测试 |

## 五、数据结构

**无表结构变更。**

- `users.role` 新增枚举值 `huguan`（`TEXT` 列，无需迁移）。
- `users.platform`：户管的该字段仅用于登录后的默认落地页，因其可自由切换平台；创建户管时由创建者选择，缺省 `gg`。
- 不新增「户管 ↔ 用户」分配表（用户已确认：可见范围 = 当前平台的全部用户）。

## 六、UI 改动

1. **侧边栏**：户管可见 GG / FB / TT 三个平台切换按钮；菜单按 3.7 的范围收窄。
2. **账户面板顶部筛选栏**：在原有搜索 / 状态下拉旁增加「全部用户」下拉（可清空回到全部）。
3. **用户管理页**：角色下拉列表新增「户管」项。
4. **设置页**：户管可见并可编辑下拉选项区块；管理员专属的全局 Google 表格配置区块对户管隐藏（户管的 sheet 配置属于子项目 B）。

## 七、边界情况

1. **户管操作「其他用户」的账户时，代理名 / 状态选项的归属**：GG 的代理名、账户状态是**按 owner 隔离**的（`agents.owner_id`、`account_statuses.owner_id`）。户管代建 / 代改账户时，若写入新代理名，应挂到**目标账户的 owner** 名下，否则会在列表 JOIN 上出现空值。TT 的选项是**按平台共享**的（`platform='tt'`），不受此影响。
2. **GG MCC 的 `shared_user_ids`**：现行权限是「自己的 + 被共享的」。户管短路为全量后，`shared_user_ids` 逻辑不再参与户管的查询，但这不影响该字段对其他角色的作用。
3. **户管自己的 `platform`**：始终以 `_get_effective_platform()` / `effectivePlatform` 的解析结果为准，`users.platform` 不参与权限判断，避免切换平台后出现「越权被拦」。
4. **老用户提升为户管**：仅改 `role` 字段，无数据迁移；反之从户管降级同样即时生效。
5. **`viewer` 与户管**：互斥角色，不做组合判断。若出现 `role='huguan'`，不适用 `reject_viewer` 的拦截逻辑。
6. **前端隐藏 ≠ 后端拦截**：所有权限边界由后端强制，前端仅做体验收敛，防止绕过前端直接调接口。

## 八、测试要点

**后端**
- 户管调 GG / TT / FB 账户列表 → 返回全部用户账户（不再限于自己）。
- 户管传 `owner_id` → 只返回该用户的账户；传不存在或跨平台的 `owner_id` → 返回空 / 400，不泄露其他平台数据。
- 户管跨平台调用（`?platform=tt` 访问 TT 接口）→ 不被 403 拦截。
- 户管编辑其他用户的 TT / FB 账户 → 成功；普通 user 编辑他人账户 → 403。
- 户管调用户管理接口（改角色 / 启停 / 删用户）→ 403。
- 非 developer 的 admin 尝试把用户提升为 `huguan` → 403；developer 操作 → 成功。
- 户管调定时任务接口 → 403。
- 户管编辑设置下拉选项（代理名 / 状态 / 地区时区）→ 成功。
- 户管看不到其他平台的用户（切到 TT 时 `/api/platform/users` 不返回 GG 用户）。
- GG 账户列表的筛选下拉（MCC / 代理 / 时区）与状态计数，随 `owner_id` 筛选同步变化。
- 回归：admin、developer、user、viewer 各角色行为与改动前**完全一致**。

**前端**
- 户管登录后可见平台切换按钮，可切到 TT / FB，页面正常加载。
- 户管侧边栏**能看到「账户管理」图标**（回归点：`canAccessProducts` 未放开时此处会消失）。
- 户管在 GG / FB / TT 下菜单仅显示账户相关项，无产品管理 / 视频 / 媒体 / 数据分析。
- 户管直接访问 `/accounts/ads`、`/fb/bms`、`/tt/bcs` 等带 `meta.admin` 的路由 → **不被重定向回首页**。
- 户管访问 `/admin/users`、`/admin/scheduler` → 被重定向。
- 户管账户面板出现「全部用户」下拉，选择后列表按用户过滤。
- 用户管理页角色下拉出现「户管」（developer 登录时）。
- 回归：非户管用户的侧边栏与菜单与改动前一致。

## 九、范围外（明确不做）

1. **户管看板 Google Sheet 的配置与写表** —— 子项目 B，另出设计文档。
2. **修复 GG `accounts_update` 缺失归属校验的历史缺口** —— 属既有问题，不随本需求夹带。
3. **户管 ↔ 用户的显式分配关系** —— 用户已确认按平台全量可见。
4. **户管操作审计日志** —— 现有 `audit_log` 表已记录部分操作，不新增户管专属审计。
