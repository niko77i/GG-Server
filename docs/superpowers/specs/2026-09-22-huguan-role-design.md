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
6. **可创建户管账号**：户管可进入用户管理页，但**只能新建 / 编辑「户管」角色的账号**，且**只能操作自己创建的**户管；对 `user` / `viewer` / `admin` / `developer` 既不可见也不可操作。户管之间不能互相启停 / 删除。
7. **不具备的权限**：定时任务。

## 二、现状分析

### 2.1 角色与平台

- `py/database.py:399-411` 的 `users` 表：`role`（`developer` / `admin` / `user` / `viewer` / `hidden`）、`platform`（`gg` / `fb` / `tt`，默认 `gg`）、`created_by`（创建者 id，可为 `NULL`）。
- 前端角色判断集中在 `frontend/src/stores/auth.js` 的 getter：`isAdmin`、`isDeveloper`、`isViewer`、`canAccessProducts`、`effectivePlatform`。

### 2.2 平台切换机制（已有，可复用）

三层配合，无需新建机制：

| 层 | 位置 | 现状 |
|---|---|---|
| 前端状态 | `frontend/src/stores/auth.js` | `currentPlatform` + `effectivePlatform`：developer 用 `currentPlatform`，其他人用 `user.platform` |
| 请求注入 | `frontend/src/api/client.js:13` | `user.role === 'developer'` 时按当前路由前缀注入 `params.platform` |
| 后端解析 | `py/main.py:5776 _get_effective_platform()` | `role in PLATFORM_SWITCH_ROLES` 时取 `request.args['platform']`，否则取 `user.platform` |

> **勘误（2026-09-22，执行 Task 1 时发现）**：本节原先写的是 `role in ('developer','admin')`，那是**平台隔离改动之前的旧快照**。`c4b3d56`（用户管理按平台隔离）已**有意把 admin 移出**该判断——admin 自身按平台隔离，不再跨平台。同理 `require_platform` 自建立起只放行 `developer`。
>
> 因此户管接入时不能复用含 admin 的 `CROSS_USER_ROLES`，否则会（a）把 admin 的跨平台越权改回来、（b）打挂既有测试 `test_user_platform_isolation.py:115 test_tt_admin_sees_tt_statuses`。**两个平台切换闸门统一用 `PLATFORM_SWITCH_ROLES = ("developer", HUGUAN_ROLE)`。**
>
> 三个常量的分工（`py/routes/helpers.py`）：
> - `PLATFORM_SWITCH_ROLES` — **跨平台切换**（`require_platform`、`_get_effective_platform`），仅 developer + 户管
> - `CROSS_USER_ROLES` — **账户域跨用户可见性**（账户 / MCC / BC / BM / 像素），developer + admin + 户管
> - `GLOBAL_OPTION_ROLES` — **平台级下拉选项编辑**（代理名、账户状态、MCC 等级、地区时区、商务人员），developer + admin + 户管
>
> 三者语义不同，**不可互换**。文档中其余提到让户管「跨平台」的地方，一律指 `PLATFORM_SWITCH_ROLES`。

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

同类缺口还有 FB 侧：`py/routes/fb_routes.py:336`（账户编辑）、`:363`（账户删除）、`:135`（BM 编辑）、`:795`（像素BM 编辑）等接口同样**没有归属校验**。这些缺口的副作用是「户管本来就改得动 FB 的任何账户」，因此 FB 的编辑权无需任何改动即已满足需求；本设计同样不修复它们。

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

**替换方式（已定：常量替换）**：现有代码中 `role in ('developer', 'admin')` / `role not in ('developer', 'admin')` 字面量共约 37 处（`tt_routes.py`、`tt_accounts_routes.py`、`fb_routes.py`）+ `main.py` 约 30 处，**统一替换为上述常量引用**。

选择理由：

1. 约 67 处字面量，逐处手改的漏改风险远高于常量替换；漏一处的表现是「某个编辑入口对户管 403」，属于难排查的隐性故障。收敛为常量后，`CROSS_USER_ROLES` 一处决定全部。
2. 两处常量成员相同、语义不同，替换后调用点自解释，后续再调权限只需改定义。
3. 这是**行为保持的机械替换**：`CROSS_USER_ROLES` 对 `developer` / `admin` 的判定与原标题完全一致，现有角色行为不变、不失效，符合纯增量原则。唯一的行为变化是「户管」被加入，即本需求本身。

常量定义在 `py/routes/helpers.py`（该模块只依赖 `database` / `auth`，处于依赖链最底层，无循环导入风险）。`main.py` 已导入 `routes` 包，新增一行：

```python
from routes.helpers import CROSS_USER_ROLES, GLOBAL_OPTION_ROLES
```

各文件的替换清单：

| 文件 | 站点数 | 替换为 |
|---|---|---|
| `py/main.py` | ~30 | 按语义分派（见 3.3 / 3.4 / 3.6） |
| `py/routes/tt_routes.py` | ~12 | 按语义分派 |
| `py/routes/tt_accounts_routes.py` | ~12 | 按语义分派 |
| `py/routes/fb_routes.py` | ~5 | 按语义分派 |
| `py/routes/decorators.py` | 1（`require_platform`） | `PLATFORM_SWITCH_ROLES`（**非** `CROSS_USER_ROLES`，见 2.2 勘误） |

### 3.2 平台切换（让户管生效）

| 文件 | 改动 |
|---|---|
| `py/main.py:5776 _get_effective_platform()` | 判断从 `== 'developer'` 改为 `in PLATFORM_SWITCH_ROLES`（**不可**用含 admin 的 `CROSS_USER_ROLES`，见 2.2 勘误） |
| `py/routes/decorators.py:50 require_platform()` | `role == 'developer'` 放行改为 `role in PLATFORM_SWITCH_ROLES`，使户管跨平台调用不被 403 |
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
| `py/routes/tt_routes.py:1145 _check_bc_owner` | 元组 → `CROSS_USER_ROLES`（BC 属账户域） |
| `py/routes/fb_routes.py` BM / 账户 / 像素 的 PUT / DELETE | **无需改动** —— 核实后这些编辑接口本身就没有归属校验（与 GG `accounts_update` 同类历史缺口，见 2.5），户管天然可用 |
| `py/main.py:4186 accounts_reassign`（GG 归属转移） | 户管可把账户转移给**指定用户**（读取请求体 `owner_id`），而非固定转给自己 |
| `py/main.py:3827 accounts_create`（GG 新建账户） | 户管代建时可指定 `owner_id`；未指定则归属户管自己 |
| `py/main.py:3827` 内 agent / status 的 `owner_id=user_id` 兜底插入 | 代建场景下应使用目标 `owner_id`，避免新建的代理名挂到户管名下 |

### 3.5 设置下拉选项权限

以下接口中 `is_dev = role in ('developer','admin')` 改为 `role in GLOBAL_OPTION_ROLES`：

- `py/main.py` 代理名：`agents_create` / `agents_rename` / `agents_delete`
- `py/main.py` 账户状态：`statuses_create` / `statuses_update` / `statuses_delete`
- `py/main.py` MCC 等级：`mcc-levels` 四个接口
- `py/main.py` 商务人员：`sales-persons` 四个接口
- `py/main.py` 地区时区：`regions` 四个接口（`regions_*`）**无需改动** —— 核实后这四个接口当前**没有任何角色判断**（`regions_list_api` / `regions_update_api` / `regions_create_api` / `regions_delete_api`，`py/main.py:9856-9897`），任意登录用户均可调用，户管天然可用。其「无权限门槛」是既有状态，按纯增量原则不在本需求内收紧；前端是否显示编辑入口由 3.7 的设置页判断决定。

### 3.6 用户管理接口（**受限开放给户管**）

户管需要能创建户管账号，因此用户管理接口需要开放，但**权限被严格收窄到「自己创建的户管」**。

#### 3.6.1 单一闸门：`_check_modify_user`

`py/main.py:7455 _check_modify_user(actor, target)` 被角色切换 / 启停 / 删除 / 编辑 / 改密 / Telegram 六个接口复用，是唯一的收口点，改这一处即全局生效。

**注意实际签名与返回类型**：现有实现返回 `str | None`（`None` = 放行，字符串 = 拒绝原因），而不是布尔值。这是为了给不同拒绝原因返回不同错误文案。户管分支必须沿用该约定：

```python
def _check_modify_user(actor: dict, target: dict) -> str | None:
    """返回 None 表示可操作；否则返回具体的拒绝原因（供接口返回准确的错误消息）。"""
    if actor["role"] == "developer":
        return None
    if actor["role"] == "huguan":
        # 户管只能操作「自己创建的户管」
        if target["role"] != "huguan":
            return "户管只能操作户管账号"
        if target.get("created_by") != actor["id"]:
            return "只能操作自己创建的户管"
        return None
    if target["role"] not in ("user", "viewer", "hidden"):
        return "不能操作同级管理员"
    # 平台隔离：非 developer 只能操作自己平台的用户
    if (actor.get("platform") or "gg") != (target.get("platform") or "gg"):
        return "不能操作其他平台的用户"
    return None
```

> 现有各接口已有 `if uid == user_id: 拒绝` 判断（改角色 / 启停 / 删除），保持不动，户管同样不能操作自己。
>
> **现状说明**：「用户角色平台隔离」那份改动**已在工作区实现**（不是待合并的草稿），`_check_modify_user` 就是它引入的新名字，替换了原先的 `_can_modify_user`。本设计在它的基础上追加户管分支，是纯追加。

#### 3.6.2 接口清单改动

| 接口 | 位置 | 改动 |
|---|---|---|
| `admin_create_user` | `py/main.py:7406` | 入口放行户管；**户管强制 `role='huguan'`**，忽略请求体传入的 role；`platform` 取创建者自己的（`or 'gg'`） |
| `admin_list_users` | `py/main.py:7440` | 入口放行户管；**户管只返回 `role='huguan'` 的用户**（需给 `auth.list_users` 增加可选的 `role_filter` 参数，默认 `None` 时行为完全不变） |
| `admin_update_role` | `py/main.py:7467` | 入口放行户管；**户管仅允许把目标改为 `huguan` 或 `hidden`**，禁止 `user` / `admin` / `viewer` |
| `admin_toggle_user` | `py/main.py:7489` | 入口放行户管（启停自己创建的户管） |
| `admin_delete_user` | `py/main.py:7508` | 入口放行户管（删除自己创建的户管） |
| `admin_update_user` / 改密 / Telegram 等其余 | `py/main.py:7561-7653` | 入口放行户管，权限由 `_check_modify_user` 收口 |

**`admin_create_user` 的角色白名单按身份分档**（现有 `if role not in ("user","admin","viewer")` 需替换）：

```python
ALLOWED_CREATE_ROLES = {
    "developer": ("user", "admin", "viewer", "huguan"),
    "admin":     ("user", "admin", "viewer"),
    "huguan":    ("huguan",),
}
```

#### 3.6.3 `py/auth.py` 两处必须同步修改（否则产生提权 / 角色丢失）

| 位置 | 现状 | 风险 | 改动 |
|---|---|---|---|
| `py/auth.py:192 toggle_user_status` | `new_role = "hidden" if row["role"] in ("user","admin","viewer") else "user"` | `huguan` 不在元组里 → **一次启停就把户管降级成 `user`**（该函数只在「隐藏」方向查元组，不在元组里即落到 `else` 的 `"user"`） | 元组加入 `"huguan"` |

> **勘误（2026-09-22，执行 Task 2 时发现）**：本表原先写「再次启用也回不到户管」，容易让人以为要在元组之外再做文章。实查该函数**没有任何「隐藏前的角色」记忆**，且 `users` 无空闲列可存（本需求禁止加列）。取消隐藏时**对所有角色一律回落到 `user`**——这是 `admin` / `viewer` 同样存在的既有单向行为，不是户管独有的缺陷。
>
> 因此**元组加入 `"huguan"` 就是户管的完整修复**：户管启停后进入 `hidden` 而不再被误降为 `user`。取消隐藏后落到 `user` 属既有行为，本需求不改（改它会影响 admin/viewer，违反纯增量原则）。要恢复户管身份走角色下拉 `POST /api/admin/users/<id>/role {"role":"huguan"}`，由 Task 3 覆盖。
>
> 同理，`py/tests/test_huguan_role.py` 中**不得**断言「隐藏后再启停回到 `huguan`」——该断言与既有实现矛盾。改为断言「户管 → `hidden`」，并另用一条显式命名的用例锁定「取消隐藏回落到 `user`」这一既有行为供后人查阅。
| `py/auth.py:114 update_user_role` | 仅拦 `developer`，无角色白名单 | 若调用方漏校验，任何非 developer 都能把目标改成任意角色 | 白名单在 3.6.2 的调用方校验；**同时**在 `update_user_role` 内加一道 `new_role in ("user","admin","viewer","hidden","huguan")` 断言作为纵深防御 |

#### 3.6.4 产品 / 视频域：**必须显式收口**（原判断有误，已勘误）

> **勘误（2026-09-22，执行 Task 1 时发现）**：本节原先称「`can_modify` 保持不动 → 户管不会获得产品/视频的额外编辑权」。**这条防线不存在。**
>
> 实查：`py/routes/helpers.py` 的 `can_modify` / `can_modify_user` 在生产代码中**零调用**（仅 `py/tests/test_helpers.py` 引用）。真正生效的是 `py/main.py:1918 _can_modify`，且只用于 `videos`（`main.py:1990`）与 `copywritings`（`main.py:7288`）。TT / FB 产品域**根本不经过它**——它们的唯一关卡是 `require_platform`。

因此放宽 `require_platform`（3.2）后，户管的实际可达面为：

| 端点 | 现有闸门 | 放宽后户管可做什么 |
|---|---|---|
| `py/routes/fb_routes.py:546/590/633`（FB 产品增 / 改 / 删） | 仅 `@fb_required`，**无 owner 校验** | 可改**任意人**的 FB 产品（存量敞口，一并收口） |
| `py/routes/tt_routes.py:225`（TT 产品 create） | 仅 `@tt_write_required` | 可创建 TT 产品（创建后即 owner，进而可改它） |
| `py/routes/tt_routes.py:276/341/399/760/794`（TT 产品改 / 删 / 加包 / 素材增删） | `+ _check_product_owner` | 只限自己的，改不了别人的 |

结论：**「户管不获得产品/视频编辑权限」必须有后端机制落实，不能依赖 `can_modify`，也不能只靠前端菜单隐藏。** 收口方案见 3.9。

下列判断确实保持不动：`py/routes/decorators.py:8 admin_required`、`py/routes/tt_routes.py:1154 _check_product_owner`、`:1169 _check_product_view`、`py/routes/fb_routes.py:471`（FB 产品列表按 `fb_product_runners` 过滤）。而 `py/routes/tt_routes.py:1145 _check_bc_owner` **要改**（BC 属于账户域，BC 管理在户管菜单内）。

#### 3.9 产品域收口（新增 Task 17）

**目标**：户管可以在三个平台间切换、可读写账户域（账户 / MCC / BC / BM / 像素），但**产品域与视频素材域一律拒绝**——无论从 UI 还是直接调 API。

**方案**：在 `py/routes/decorators.py` 新增一个与 `reject_viewer` 同形状的守卫，并在产品域端点上叠加。

```python
def reject_huguan():
    """户管不参与产品/视频域。返回错误响应或 None。"""
    try:
        uid = int(get_jwt_identity())
    except Exception:
        return None  # 未登录由 @jwt_required() 处理
    user = auth.get_user_by_id(uid)
    if user and user.get("role") == HUGUAN_ROLE:
        return err("户管无产品/素材权限", 403)
    return None
```

**改造点**：FB 产品 create / update / delete、TT 产品 create，在其 `@fb_required` / `@tt_write_required` 之下叠加 `reject_huguan()` 检查（与现有 `reject_viewer()` 写法一致，函数体首行）。TT 产品的 update / delete / assets 已有 `_check_product_owner` 兜底（户管不可能是 owner），但**仍须叠加**，使「户管被产品域拒绝」是一个显式、可读、与 owner 无关的规则，而不是依赖巧合。

**注意**：`reject_huguan` 只用于产品 / 视频 / 素材域，**不得**加到账户域端点上。`tt_routes.py` 中账户域与产品域是同一蓝图，逐端点叠加而非整蓝图叠加。

**验收**：新增测试断言户管的下列调用返回 403 —— `POST /api/fb/products/create`、`PUT /api/fb/products/<pid>`、`DELETE /api/fb/products/<pid>`、`POST /api/tt/products/create`、`PUT /api/tt/products/<pid>`；同时断言 `developer` 与平台内 `admin` 的同一调用**行为不变**。回归断言户管调账户域端点仍为 200。

#### 3.6.5 提权路径自查

| 潜在路径 | 是否可被利用 | 防线 |
|---|---|---|
| 户管把自己创建的户管改成 `admin` | **不可** | `admin_update_role` 对户管限定 `huguan` / `hidden` |
| 户管创建时直接传 `role='admin'` | **不可** | `admin_create_user` 对户管强制 `role='huguan'` |
| 户管编辑其他户管的账号 | **不可** | `_check_modify_user`（`py/main.py:7561`）要求 `created_by == actor.id` |
| 户管停用 / 删除开发者或其他户管 | **不可** | 同上；且 `developer` 不落入户管分支 |
| 户管改自己的角色 | **不可** | 各接口既有的 `uid == user_id` 拦截 |

### 3.7 前端导航与路由

| 文件 | 改动 |
|---|---|
| `frontend/src/components/AppSidebar.vue:12` | 平台切换按钮的 `v-if="auth.isDeveloper"` → `auth.canSwitchPlatform` |
| `frontend/src/components/AppSidebar.vue:127` | 账户区菜单的可见性判断 `return auth.canAccessProducts` → `return auth.canAccessProducts \|\| auth.canManageAccounts`（**否则户管看不到账户菜单**） |
| `frontend/src/components/AppSidebar.vue:126-158` | 新增户管专用导航：仅保留账户区、设置、用户管理，**排除**产品管理、视频管理、媒体工具、工具集、数据分析、定时任务 |
| `frontend/src/router/index.js:176` | `if (to.meta.admin && !auth.isAdmin) next(platformHome)` → 增加豁免：户管可进入账户区与用户管理页带 `meta.admin` 的路由。改为 `if (to.meta.admin && !auth.isAdmin && !(auth.isHuguan && isHuguanAllowedRoute(to.path)))`，其中 `isHuguanAllowedRoute` 匹配 `/accounts/{ads,mcc,settings}`、`/fb/{accounts,bms,pixels,settings}`、`/tt/{accounts,bcs,settings}`、`/admin/users`。**否则户管会被重定向回首页，三个平台的账户页和用户管理页全部打不开** |
| `frontend/src/router/index.js:17-24` 与 `:164-167` | **`platformHome` / `/` 重定向当前读 `auth.user.platform`，会把户管送到 `/accounts/products` 这类产品页**。需在 `auth` store 暴露一个 `homePath` getter：户管 → `/accounts/ads` / `/fb/accounts` / `/tt/accounts`；其余角色沿用现有的 `user.platform` 推断（行为不变）。两处都改用它 |
| `frontend/src/router/index.js:170` 平台守卫的比较对象 | `to.meta.platform !== userPlatform` 改为与 `auth.effectivePlatform` 比较。非切换者的 `effectivePlatform` 恒等于 `user.platform \|\| 'gg'`，行为不变；户管因可切换平台而必须用 `effectivePlatform`，否则切到 TT 后访问 `/tt/accounts` 会被判为跨平台而弹回 |
| `frontend/src/components/AppSidebar.vue:61-74` `switchPlatform` | 跳转目标当前是 `/accounts/products`、`/fb/products`、`/tt/products` 三个**产品页**。改为按角色分派：户管跳账户页（`/accounts/ads` / `/fb/accounts` / `/tt/accounts`），其余角色保持不动 |
| `frontend/src/components/AppSidebar.vue:161-166` `selectTab` | 点击图标时取 `nav.sections[0].items[0]` 作为落点。户管的账户区首项若被过滤掉，落点会变成已被隐藏的产品页。改用 3.7.1 的户管专用导航数组，首项即为账户页 |
| `frontend/src/views/AccountsView.vue:7-9` | GG 顶部 Tab（广告账户 / MCC 管理 / 设置）的 `auth.isAdmin` → `auth.canManageAccounts` |
| `frontend/src/views/UserManageView.vue` | 户管可见页面，但按 3.7.1 收窄：角色下拉只有「户管」、列表只列户管、隐藏平台 Tab；「户管」选项对 developer 同样可见（见 3.7.1） |
| `frontend/src/views/tt/TtSettingsPanel.vue:66-70` | **唯一需要改的设置页**。该处一个 `v-if="authStore.isAdmin \|\| authStore.isDeveloper"` 同时罩住了「代理/状态/回收原因选项卡片」与「Google 表格配置」两块。需把选项卡片**上移**出该块并对户管放行，sheet 配置块保持仅管理员。<br>**已核实无需改动**：`SettingsPanel.vue:65` 的同一判断只罩住「充值表配置」一张 card（选项卡在它之外）→ 户管本就可见；`fb/FbSettingsPanel.vue` 全文无任何角色判断 → 同理 |

#### 3.7.1 用户管理页（`UserManageView.vue`）按身份分档

| 元素 | developer | admin | 户管 |
|---|---|---|---|
| 平台 Tab（全部/GG/FB/TT） | 全显 | 只显自己平台 | 隐藏（户管跨平台，按用户维度无意义） |
| 列表范围 | 全部 | 自己平台 | 仅 `role='huguan'` |
| 创建用户时的角色下拉 | `user` / `viewer` / `admin` / `huguan` | `user` / `viewer` / `admin` | 仅 `huguan`（且锁定，不可改） |
| 行的「切换角色」下拉 | `user` / `viewer` / `admin` / `huguan` / `hidden` | `user` / `viewer` / `admin` / `hidden` | 仅 `huguan` / `hidden`，且只对自己创建的户管显示 |
| 启停 / 删除按钮 | 全部行 | 自己平台行 | 仅自己创建的户管行 |

**谁可以授予「户管」角色**：`developer` 与 `huguan`。admin **不能**（admin 作用域受平台限制，而户管是跨平台角色，由平台内 admin 授予会突破隔离边界，见另一份 `2026-09-22-user-role-platform-isolation-design.md`）。后端在 `admin_create_user` / `admin_update_role` 中按 3.6.2 的 `ALLOWED_CREATE_ROLES` 校验，admin 传入 `role='huguan'` → 403。

**户管导航具体范围**：

| 平台 | 保留菜单 |
|---|---|
| GG | 广告账户、MCC 管理、设置、用户管理（受限） |
| FB | 广告账户、BM 管理、像素管理、FB 设置、用户管理（受限） |
| TT | 广告账户、BC 管理、TT 设置、用户管理（受限） |

三平台的「管理」分组由 `AppSidebar.vue:126-130` 的 `admin: true` 门控（过滤条件是 `auth.isAdmin`）。户管要看到「用户管理」，需把该门控改为 `auth.isAdmin || auth.isHuguan`，分组内的「定时任务」继续由既有的 `item.developer` 过滤剔除（该过滤已存在，无需新增）。

同时 `AppSidebar.vue:4` 的首页跳转、`router/index.js:17-24` 的 `/` 重定向都以 `user.platform` 决定落地页 —— 户管因 `platform` 只是默认值，落地页按 `platform` 走即可，无需特殊处理。

### 3.8 前端用户筛选下拉

在以下面板新增「全部用户 / 选择用户」下拉（复用 `TtAccountPanel.vue:45` 的写法与 `ownerId` + `filterAndLoad` 模式）：

- `frontend/src/views/AdsAccountPanel.vue`（GG 广告账户）
- `frontend/src/views/MccPanel.vue`（GG MCC）
- `frontend/src/views/fb/FbAccountPanel.vue`、`FbBmPanel.vue`、`FbPixelPanel.vue`、`FbPixelBmPanel.vue`
- `frontend/src/views/tt/TtAccountPanel.vue`、`TtBcPanel.vue`（把现有 `isAdmin` 判断换成 `canManageAccounts` 即可）

## 四、涉及文件清单

| 文件 | 改动类型 |
|---|---|
| `py/routes/helpers.py` | 新增 `HUGUAN_ROLE`、`PLATFORM_SWITCH_ROLES`、`CROSS_USER_ROLES`、`GLOBAL_OPTION_ROLES` |
| `py/routes/decorators.py` | `require_platform` 用 `PLATFORM_SWITCH_ROLES` 放行户管；新增 `reject_huguan`（产品域收口，3.9） |
| `py/routes/tt_routes.py` | 角色元组 → 常量（:30, :125, :158, :569, :1145, :1157, :1169） |
| `py/routes/tt_accounts_routes.py` | 角色元组 → 常量（约 24 处） |
| `py/routes/fb_routes.py` | 角色元组 → 常量 + 列表补 `owner_id` 筛选 |
| `py/main.py` | `_get_effective_platform`；GG 账户列表跨用户 + 筛选；GG MCC 跨用户 + 筛选；`accounts_create` / `accounts_reassign` 归属；设置选项接口角色；新增 `/api/platform/users`；用户管理六个接口放行户管 + `_can_modify_user` 加户管分支 + `ALLOWED_CREATE_ROLES` |
| `py/auth.py` | `toggle_user_status` 元组加 `huguan`；`update_user_role` 加角色白名单；`list_users` 加可选 `role_filter` 参数（默认 `None`，行为不变） |
| `frontend/src/stores/auth.js` | 新增 `isHuguan` / `canSwitchPlatform` / `canManageAccounts` / `roleLabel`，放开 `effectivePlatform`、`setPlatform` |
| `frontend/src/api/client.js` | platform 参数注入放开给户管 |
| `frontend/src/router/index.js` | 平台守卫、账户区守卫用新 getter |
| `frontend/src/components/AppSidebar.vue` | 平台切换按钮 + 户管导航（含受限的「管理」分组） |
| `frontend/src/views/AccountsView.vue` | GG Tab 权限 |
| `frontend/src/views/SettingsPanel.vue`、`tt/TtSettingsPanel.vue`、`fb/FbSettingsPanel.vue` | 选项编辑权限 |
| `frontend/src/views/UserManageView.vue` | 按 3.7.1 分档：角色下拉、列表范围、平台 Tab、行操作按钮 |
| `frontend/src/views/AdsAccountPanel.vue`、`MccPanel.vue`、`fb/*.vue`、`tt/TtAccountPanel.vue`、`tt/TtBcPanel.vue` | 用户筛选下拉 |
| `py/tests/` | 新增户管权限测试（账户跨用户 + 用户管理边界 + 提权路径） |

> **与「用户角色平台隔离」改动的关系**：该改动**已经在工作区落地**（`py/auth.py` 的 `list_users`、`py/main.py` 的 `_check_modify_user`、`frontend/src/views/UserManageView.vue` 的 Tab 分档都已改完），本设计以它为基线，只做**追加**：
> - `list_users` 增加一个默认 `None` 的可选 `role_filter` 参数 —— 不传时行为与现状完全一致；
> - `_check_modify_user` 在 `developer` 分支之后、原有分支之前插入 `huguan` 分支 —— 不影响 developer / admin 的判定路径；
> - 该改动引入的两个错误文案（`不能操作同级管理员` / `不能操作其他平台的用户`）及其测试断言**必须保留原样**，户管的拒绝文案用新字符串，不复用。
> - 合并顺序无冲突：本设计不修改该改动已有的任何一行。

## 五、数据结构

**无表结构变更。**

- `users.role` 新增枚举值 `huguan`（`TEXT` 列，无需迁移）。
- `users.platform`：户管的该字段仅用于登录后的默认落地页，因其可自由切换平台；户管创建户管时取创建者自己的 platform（`or 'gg'`）。
- `users.created_by`：**本设计新增依赖此字段**。它已存在于 `users` 表（`auth.create_user` 写入），此前未被用于权限判断。户管的「只能操作自己创建的户管」完全建立在该字段上，因此：
  - 历史上 `created_by` 为 `NULL` 的账号（如 `init_developer` 创建的开发者、自行注册的用户）**不会**被任何户管操作到 —— 这是期望行为。
  - 若后续需要「把某个已存在的户管指派给某个户管管理」，需要补 `created_by` 数据，本设计不做。
- 不新增「户管 ↔ 用户」分配表（用户已确认：可见范围 = 当前平台的全部用户）。

## 六、UI 改动

1. **侧边栏**：户管可见 GG / FB / TT 三个平台切换按钮；菜单按 3.7 的范围收窄，「管理」分组只保留「用户管理」（「定时任务」由既有 `item.developer` 过滤自动剔除）。
2. **账户面板顶部筛选栏**：在原有搜索 / 状态下拉旁增加「全部用户」下拉（可清空回到全部）。
3. **用户管理页**：按 3.7.1 分档 —— 户管看到的是「户管专用视图」：无平台 Tab、列表只有户管、创建时角色锁定为户管、行操作仅对自己创建的户管显示；developer 的角色下拉新增「户管」项。
4. **设置页**：户管可见并可编辑下拉选项区块；管理员专属的全局 Google 表格配置区块对户管隐藏（户管的 sheet 配置属于子项目 B）。

## 七、边界情况

1. **户管操作「其他用户」的账户时，代理名 / 状态选项的归属**：GG 的代理名、账户状态是**按 owner 隔离**的（`agents.owner_id`、`account_statuses.owner_id`）。户管代建 / 代改账户时，若写入新代理名，应挂到**目标账户的 owner** 名下，否则会在列表 JOIN 上出现空值。TT 的选项是**按平台共享**的（`platform='tt'`），不受此影响。
2. **GG MCC 的 `shared_user_ids`**：现行权限是「自己的 + 被共享的」。户管短路为全量后，`shared_user_ids` 逻辑不再参与户管的查询，但这不影响该字段对其他角色的作用。
3. **户管自己的 `platform`**：始终以 `_get_effective_platform()` / `effectivePlatform` 的解析结果为准，`users.platform` 不参与权限判断，避免切换平台后出现「越权被拦」。
4. **老用户提升为户管**：仅改 `role` 字段，无数据迁移；反之从户管降级同样即时生效。
5. **`viewer` 与户管**：互斥角色，不做组合判断。若出现 `role='huguan'`，不适用 `reject_viewer` 的拦截逻辑。
6. **前端隐藏 ≠ 后端拦截**：所有权限边界由后端强制，前端仅做体验收敛，防止绕过前端直接调接口。
7. **户管启停 / 删除后其创建的户管的归属**：`admin_delete_user` 的既有逻辑会把被删用户在其他表的 `created_by` 置为 `NULL`（见 `py/main.py:7527`），因此户管 A 被删除后，A 创建的户管会变成 `created_by = NULL`，**不再被任何户管操作**（开发者仍可管理）。这是可接受的兜底：宁可失去管理入口，也不要出现孤儿账号被误操作。
8. **自定义注册用户不会被户管触及**：`created_by = NULL`（见 `register_user`），落不到户管分支。
9. **用户筛选下拉的口径**：`/api/platform/users` **完全沿用现有 `/api/tt/users` 的口径**：`(platform = <当前平台> OR role = 'developer') AND role != 'hidden'`。这意味着现有的 TT 筛选下拉里本来就会出现开发者账号，本设计保持这一既有行为不变（纯增量），不额外过滤 admin / 户管。户管因名下没有账户，被选中时只会得到空列表，不影响使用。若要收窄口径，属独立于本需求的体验优化。

## 八、测试要点

**后端**
- 户管调 GG / TT / FB 账户列表 → 返回全部用户账户（不再限于自己）。
- 户管传 `owner_id` → 只返回该用户的账户；传不存在或跨平台的 `owner_id` → 返回空 / 400，不泄露其他平台数据。
- 户管跨平台调用（`?platform=tt` 访问 TT 接口）→ 不被 403 拦截。
- 户管编辑其他用户的 TT / FB 账户 → 成功；普通 user 编辑他人账户 → 403。
- 户管调定时任务接口 → 403。

**后端 — 用户管理边界（重点）**
- 户管创建用户，请求体传 `role='admin'` → 落库仍为 `huguan`（不被提权）。
- 户管创建用户成功 → `created_by` 为该户管 id。
- 户管列表接口 → 只返回 `role='huguan'`，不含 user / viewer / admin / developer。
- 户管把自己创建的户管改成 `admin` / `user` / `viewer` → 403；改成 `hidden` → 成功。
- 户管启停自己创建的户管 → 成功，且**启用后角色回到 `huguan` 而非 `user`**（回归点：`toggle_user_status` 元组未加 `huguan` 时会降级成 user）。
- 户管编辑 / 启停 / 删除**别人创建的**户管 → 403。
- 户管编辑 / 启停 / 删除 admin、developer、普通 user、viewer → 全部 403。
- 户管删除 / 启停自己 → 403。
- admin 尝试创建或提升 `huguan` → 403；developer 操作 → 成功。
- 回归：admin 的用户管理行为（平台隔离、可见范围）与改动前一致；`list_users` 不传 `role_filter` 时结果与改动前一致。
- 户管编辑设置下拉选项（代理名 / 状态 / 地区时区）→ 成功。
- 户管看不到其他平台的用户（切到 TT 时 `/api/platform/users` 不返回 GG 用户）。
- 回归：admin、developer、user、viewer 各角色行为与改动前**完全一致**。

**前端**
- 户管登录后可见平台切换按钮，可切到 TT / FB，页面正常加载。
- 户管侧边栏**能看到「账户管理」图标**（回归点：`canAccessProducts` 未放开时此处会消失）。
- 户管在 GG / FB / TT 下菜单显示：账户区（广告账户 / MCC 或 BC 或 BM+像素）、设置、用户管理；**不显示**产品管理、视频管理、媒体工具、工具集、数据分析、定时任务。
- 户管直接访问 `/accounts/ads`、`/fb/bms`、`/tt/bcs`、`/admin/users` 等带 `meta.admin` 的路由 → **不被重定向回首页**。
- 户管访问 `/admin/scheduler` → 被重定向。
- 户管账户面板出现「全部用户」下拉，选择后列表按用户过滤。
- 户管用户管理页：无平台 Tab；列表只有户管；创建弹窗角色锁定为「户管」且不可改；别人创建的户管行上不显示启停 / 删除按钮。
- developer 用户管理页：角色下拉出现「户管」项。
- 回归：非户管用户的侧边栏与菜单与改动前一致。

## 九、范围外（明确不做）

1. **户管看板 Google Sheet 的配置与写表** —— 子项目 B，另出设计文档。
2. **修复 GG `accounts_update` 缺失归属校验的历史缺口** —— 属既有问题，不随本需求夹带。
3. **户管 ↔ 用户的显式分配关系** —— 用户已确认按平台全量可见。
4. **户管操作审计日志** —— 现有 `audit_log` 表已记录部分操作，不新增户管专属审计。
