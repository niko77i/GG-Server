# 「户归属」下拉按平台隔离 — 设计文档

> 日期：2026-09-28
> 状态：**已实现**（`4eaa954` 实现、`853c6cf` 口径同步；§3.2 经同日 code-review 收口后修订）
> 修订：[2026-09-24-huguan-owner-source-and-picker-design.md](2026-09-24-huguan-owner-source-and-picker-design.md)
> §2.1 / §2.2（「不按平台过滤」的口径由本文取代；§2.4 是 UI 改动，本无此口径）

## 1. 需求描述

「户归属」列的下拉数据源是 `GET /api/huguan/dashboard/owner-options`
（[huguan_dashboard_routes.py:176](../../../py/routes/huguan_dashboard_routes.py#L176)），
它返回**全部**非 `viewer` / `hidden` 用户，**不区分平台**。

户管在 GG 面板打开该下拉，会看到 24 人里有 **14 个不可能持有 GG 户的人**
（FB 平台 6 人 + TT 平台 8 人）。用户 2026-09-28 报「这里的用户没有进行系统隔离」，
裁定：**按当前看板平台隔离**。

## 2. 与既有裁定的冲突（已由用户重新裁定）

`dashboard_owner_options` 的 docstring 与上述设计文档 §2.4 都明确写着
「**不按平台过滤**：这是『转给谁』的真实全集」，理由为：

> 拿 `/api/platform/users` 当改归属的选项源，户管就没法把 GG 的户转给一个
> 只在 TT 有户的合法用户（实测缺口）。

**本次推翻该口径** —— 依据是实测该场景在生产数据里**没有任何实例**：

| 核查项 | 结果 |
|---|---|
| 活跃 GG 账户的归属人平台 | 275 户 **100%** 是 `platform='gg'` 的用户 |
| TT 账户的归属人平台 | 403 户 **100%** 是 `platform='tt'` 的用户 |
| 跨平台持有 | 0 例 |

即：这条理由成立的前提（存在跨平台归属）在当前数据里不成立，而它带来的代价
（14 个无关用户混进名单）是户管每天都要面对的。

## 3. 口径裁定

| 项 | 值 |
|---|---|
| 生效平台 | `?platform=`，缺省 `gg`，**白名单校验**（非 `gg`/`tt` 一律回落 `gg`） |
| 过滤条件 | `role NOT IN ('viewer','hidden') AND (platform = ? OR role IN PLATFORM_SWITCH_ROLES)` |
| `PLATFORM_SWITCH_ROLES`（developer / 户管） | **无条件保留**，不随平台过滤（§3.2 的收口，见下） |
| `viewer` / `hidden` | 维持排除（原口径不变） |
| 「必须已有账户」 | **不加**。保留户管把户转给「刚建号、还没户」的新人这一能力 |

### 3.1 developer 为什么不显式排除

`developer` 的 `users.platform` 就是 `gg`（生产库 2 个 developer 均是），
所以 `platform = 'gg'` 天然把他留在 GG 看板的名单里 —— 这正是必需的：
**265 个活跃 GG 账户（占 96%）的当前归属人就是 developer**。

若显式排除 developer，`ownerOptionMap` 里就没有他，
[AdsAccountPanel.vue:156](../../../frontend/src/views/AdsAccountPanel.vue#L156)
的「未知归属」分支会被触发 —— 这 265 行的户归属格会集体退化成**禁用的
「用户 #1」**，户管一个都改不了。这是本次设计里最容易踩空的一处。

### 3.2 跨平台角色必须无条件保留（code-review 收口，取代初稿的「已知后果」）

**初稿的结论是错的，此处更正。** 初稿写「TT 看板按 `platform='tt'` 过滤后 developer
自然不在名单里……零影响」「户管本人在 TT 看板不可选，当前无实例，将来需要再改」——
这只核对了**存量**行的归属人平台，漏掉了一条**可达路径**：

> 户管 / developer 的 `users.platform` 是 `gg`，却能在 TT 看板建户 ——
> 「新增账户 / 批量导入 / 从表格同步」三条路径都把 `owner_id` 设成**操作者自己**
> （`py/routes/tt_accounts_routes.py:122 / 405 / 1122`），而
> `decorators.require_platform('tt')` 对 `PLATFORM_SWITCH_ROLES` **直接放行**。

于是纯 `platform = 'tt'` 过滤下，这些 TT 户的归属人不在名单里 →
`TtAccountPanel.vue:189` 的「未知归属」分支触发 → 归属格渲染成**禁用的「用户 #N」**，
而 `components/tt/TtAccountModal.vue` **没有归属字段** ⇒ 户管没有任何 UI 能把它改回来
（改归属正是这一列存在的唯一目的）。存量 0 例，但 developer 点一次「同步」就会批量产生。

**故口径定为 `platform = ? OR role IN PLATFORM_SWITCH_ROLES`。** 代价仅限 TT 看板多出
跨平台角色（生产 3 人：2 developer + 1 户管），**GG 看板名单逐字不变** ——
生产里这 3 人全是 `platform='gg'`，本就在 GG 名单内（实测核对）。

回归钉：`test_cross_platform_roles_stay_on_tt_board`（变异「去掉 OR」恰好 1 红）。

### 3.3 与 `_get_effective_platform` 的有意差异

本端点的平台取名函数对 `?platform=fb` **回落 `gg`**，而
`main._get_effective_platform` 会原样返回 `'fb'`（账户表随之切到 `fb_accounts`）。
这是有意的：本端点只服务 GG/TT 两份看板（`hd.PLATFORMS`），FB 没有看板表配置。
**将来若给 FB 面板接上归属下拉，必须先扩展 `hd.PLATFORMS`**，否则会出现
「列表是 FB 户、改归属下拉是 GG 人」的错配（`fb_routes` 的 reassign 只校验目标用户存在）。

## 4. 技术方案

### 4.1 后端

文件：[py/routes/huguan_dashboard_routes.py](../../../py/routes/huguan_dashboard_routes.py)

该模块**刻意不 import main**（main 注册本 blueprint，反向 import 会循环），
故不复用 `main._get_effective_platform`，改用等价的局部 helper ——
对户管而言两者的取值逐字相同（户管是 `PLATFORM_SWITCH_ROLES` 成员，
`_get_effective_platform` 对这类角色返回的就是 `request.args.get("platform", "gg")`）。

新增：

```python
def _owner_option_platform():
    """owner-options 要按哪个平台隔离。

    户管是 PLATFORM_SWITCH_ROLES 成员，其「有效平台」在 GG/TT 两份看板上就等于
    ?platform=（缺省 gg）—— 与 main._get_effective_platform 对户管的取值相同。
    本模块不 import main（main 注册本 blueprint，反向 import 会循环），故就地实现。

    ⚠️ 与 `_get_effective_platform` 有一处**有意**的差异：那个函数对 `?platform=fb`
    原样返回 'fb'（账户表随之切到 `fb_accounts`），本函数却回落 'gg' —— 因为本端点
    只服务 GG/TT 两份看板（`hd.PLATFORMS`），FB 没有看板表配置。**将来若给 FB 面板
    接上归属下拉，必须先扩展 `hd.PLATFORMS`**，否则会出现「列表是 FB 户、改归属
    下拉是 GG 人」的错配（`fb_routes` 的 reassign 只校验目标用户存在）。

    白名单的方向也要看清：白名单外的值必须回落 gg，而不是「不过滤」—— 后者会把
    FB/TT 的人漏回名单里，正好抵消本次隔离。
    """
    p = request.args.get("platform", "gg")
    return p if p in hd.PLATFORMS else "gg"
```

> **⚠️ 初稿理由有误，已更正**：初稿写「`hd.PLATFORMS` 之外的值会让名单变空」——
> 事实相反。实测生产库，`platform='fb'` 会返回 **6 个 fb 用户**（`admin-fb` 1 + `user-fb` 5），
> 既不空也不回落。真正的理由如上：必须显式回落 `gg`，否则等于撤回了本次隔离。

`dashboard_owner_options` 改为：

```python
    platform = _owner_option_platform()
    # SQL 里只拼接「? 的个数」，角色名仍走参数位 —— 不是把用户输入拼进 SQL。
    switch_roles = ", ".join("?" for _ in PLATFORM_SWITCH_ROLES)
    db = database.get_db()
    try:
        rows = db.execute(
            "SELECT id, username, display_name, platform FROM users "
            "WHERE role NOT IN ('viewer', 'hidden') "
            f"AND (platform = ? OR role IN ({switch_roles})) "
            "ORDER BY display_name, username",
            (platform, *PLATFORM_SWITCH_ROLES)
        ).fetchall()
    finally:
        db.close()
```

同时**重写 docstring**：删去「不按平台过滤」那段，改为说明按平台隔离的口径，
并留下「曾经不隔离的理由是什么、为什么现在可以隔离（零实例实测）」——
否则下一个人只会看到结论，遇到跨平台需求时会以为是 bug 而改回去。

### 4.2 前端

**零改动。** 请求拦截器已为 `developer` / `huguan` 自动附带 `?platform=`，
且在 GG 面板传的就是 `gg`（[client.js:13-21](../../../frontend/src/api/client.js#L13-L21)）。

唯一要动的是**注释**：
[useOwnerPicker.js:41-45](../../../frontend/src/composables/useOwnerPicker.js#L41-L45)
现在写着「本端点必须全量，否则户管没法把 GG 户转给只在 TT 有户的用户」——
该理由已被本次裁定取代，需同步改写，否则前端留着一句与后端行为相悖的告诫。

### 4.3 数据结构

响应形状**不变**，仍是：

```json
{"success": true, "users": [{"id": 1, "username": "...", "display_name": "...", "platform": "gg"}]}
```

只是集合从「全部 24 人」变为「本平台用户」。前端 `ownerOptions` /
`ownerOptionMap` 的消费方式无需调整。

### 4.4 UI 改动

**无。** 下拉的渲染、骨架态、失败态、未知归属态、未分配态（§5.4/§5.6）全部不变。
变化的只是选项集合 —— 隔离后 GG 看板 10 人、TT 看板 8 人。

## 5. 测试

### 5.1 必须改写的既有测试（本次是规格变更，非 bug）

[test_huguan_dashboard.py:2777](../../../py/tests/test_huguan_dashboard.py#L2777)
`TestOwnerOptionsEndpoint.test_huguan_gets_all_users_including_account_less`
造的正是 `platform='tt'` 的无户用户，并断言户管（GG）调用时**他必须在结果里** ——
这条钉子钉的就是旧口径，本次会把它打红。**并列的类 docstring 也必须重写。**

改写原则：**保住原意**。该用例真正要守的是「无账户的用户也能被选中」（防止有人给它加
`EXISTS(账户)`），这一点与平台无关，继续守。故改为：造一个 `platform='gg'` 的无户用户
→ 断言在，`platform` 字段断言同步由 `'tt'` 改为 `'gg'`。

「非本平台用户不得出现」由 §5.2 新类的 `test_gg_board_excludes_other_platforms` 承担，
不往这条里塞 —— 一条用例守一件事。

`test_viewer_and_hidden_are_excluded` 的对照行 `normal` 走 `_seed` 默认
`platform='gg'`，**不受影响**，无需改动。

### 5.2 新增用例

| 用例 | 断言 |
|---|---|
| 非本平台用户不出现（GG） | 造 fb 用户 + tt 用户（各带一个账户）→ 户管不带参数调用 → **两个都不在**结果里 |
| GG 看板含 gg 用户 | 造 gg 用户 → 在结果里（对照行，防「过滤过猛全滤掉」也绿） |
| `?platform=tt` 切换名单 | 同一次调用带 `?platform=tt` → tt 用户在、gg 用户不在 |
| 非法 platform 回落 gg | `?platform=fb` / `?platform=xx` / `?platform=`（空串）→ 等同不带参数 |
| developer 在 GG 看板保留 | 造 developer（platform='gg'）→ 在结果里（§3.1 的回归钉） |
| **跨平台角色在 TT 看板保留** | 造 developer(gg) + 户管(gg) + tt 普通用户 → `?platform=tt` → tt 用户与跨平台角色**都在**（§3.2 的回归钉） |

后两条尤其重要，它们各守一个方向的真实代价：前者守「265 户挂 developer 名下不会退化成
禁用格」，后者守「跨平台角色在 TT 建出的户不会锁死」。

变异实测（两方向各一次）：
- 去掉 `AND platform = ?` 整段 → **3 红**（隔离那一面失效）；
- 去掉 `OR role IN (...)` 只留 `platform = ?` → **1 红**（`test_cross_platform_roles_stay_on_tt_board`）；
- 把 helper 改成 `return "nonexistent"`（过滤过猛）→ **6 红**（对照腿全部生效）。

> 删 `OR` 时**必须同时删掉参数位的 `*PLATFORM_SWITCH_ROLES`**，否则占位符与参数个数
> 失配、整组报 `Incorrect number of bindings` —— 那是假红，会把变异结论带偏
> （第一次变异就踩到了这个坑）。

## 6. 涉及文件

| 文件 | 改动 |
|---|---|
| `py/routes/huguan_dashboard_routes.py` | 新增 `_owner_option_platform()`；`dashboard_owner_options` 加平台条件 + `OR role IN PLATFORM_SWITCH_ROLES` + 重写 docstring |
| `py/tests/test_huguan_dashboard.py` | 改写 1 个用例 + 类 docstring；`TestOwnerOptionsPlatformIsolation` 新增 5 条用例 |
| `frontend/src/composables/useOwnerPicker.js` | 仅注释（3 处「全量用户」措辞） |
| `frontend/src/api/huguan.js` | 仅注释（`ownerOptions` 上方同款旧告诫） |
| `docs/superpowers/specs/2026-09-24-huguan-owner-source-and-picker-design.md` | §2.1 / §2.2 标注被本文取代（§2.4 是 UI 改动，本无该口径） |
| `docs/superpowers/specs/2026-09-24-huguan-frontend-visual-design.md` | §5.4「✅ 更正」段加修订标注 |
| `docs/superpowers/specs/2026-07-31-spring-boot-migration-design.md` | 迁移参考的 2 处端点口径同步（前瞻文档，照旧写会丢隔离） |
| `AGENTS.md` | 设计文档索引 |

前端零代码改动 → **无需 `npm run build`**；后端改动 → **需重启 Flask**。
