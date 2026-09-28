# 「户归属」下拉按平台隔离 — 设计文档

> 日期：2026-09-28
> 状态：**待用户确认**
> 修订：[2026-09-24-huguan-owner-source-and-picker-design.md](2026-09-24-huguan-owner-source-and-picker-design.md)
> §2.4（「不按平台过滤」的口径由本文取代）

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
| 过滤条件 | `role NOT IN ('viewer','hidden') AND platform = ?` |
| `developer` | **不特判**。其 `users.platform='gg'` → GG 看板自然保留、TT 看板自然排除 |
| `viewer` / `hidden` | 维持排除（原口径不变） |
| 「必须已有账户」 | **不加**。保留户管把户转给「刚建号、还没户」的新人这一能力 |

### 3.1 developer 为什么不特判

`developer` 的 `users.platform` 就是 `gg`（生产库 2 个 developer 均是），
所以 `platform = 'gg'` 天然把他留在 GG 看板的名单里 —— 这正是必需的：
**265 个活跃 GG 账户（占 96%）的当前归属人就是 developer**。

若显式排除 developer，`ownerOptionMap` 里就没有他，
[AdsAccountPanel.vue:156](../../../frontend/src/views/AdsAccountPanel.vue#L156)
的「未知归属」分支会被触发 —— 这 265 行的户归属格会集体退化成**禁用的
「用户 #1」**，户管一个都改不了。这是本次设计里最容易踩空的一处。

反向也成立：TT 看板按 `platform='tt'` 过滤后，developer 自然不在名单里，
而 TT 的 403 个账户**没有任何一个**挂在 developer 名下 —— 零影响。

### 3.2 已知后果（用户已知晓）

户管本人的 `platform` 也是 `gg`，因此**在 TT 看板不可选**（无法把 TT 户转给户管自己）。
当前无实例（TT 无 huguan 持有的户）。若将来需要，把口径改为
`platform = ? OR role IN PLATFORM_SWITCH_ROLES` 即可，但本次不做。

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

    户管是 PLATFORM_SWITCH_ROLES 成员，其「有效平台」就等于 ?platform=（缺省 gg）
    —— 与 main._get_effective_platform 对户管的取值逐字相同。本模块不 import main
    （main 注册本 blueprint，反向 import 会循环），故就地实现这一条。

    白名单是必要的：platform 直接进 SQL 的参数位，但更关键的是 `hd.PLATFORMS`
    之外的值会让名单变空，而不是回落成「全部」。
    """
    p = request.args.get("platform", "gg")
    return p if p in hd.PLATFORMS else "gg"
```

`dashboard_owner_options` 改为：

```python
    platform = _owner_option_platform()
    db = database.get_db()
    try:
        rows = db.execute(
            "SELECT id, username, display_name, platform FROM users "
            "WHERE role NOT IN ('viewer', 'hidden') AND platform = ? "
            "ORDER BY display_name, username", (platform,)).fetchall()
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

改写原则：**保住原意，加上隔离这一面**。该用例真正要守的是
「无账户的用户也能被选中」（防止有人给它加 `EXISTS(账户)`），
这一点与平台无关，继续守；同时新增一条「非本平台用户不得出现」。
故改为：造一个 `platform='gg'` 的无户用户 → 断言在；造一个 `platform='tt'` 的 → 断言不在。

`test_viewer_and_hidden_are_excluded` 的对照行 `normal` 走 `_seed` 默认
`platform='gg'`，**不受影响**，无需改动。

### 5.2 新增用例

| 用例 | 断言 |
|---|---|
| 非本平台用户不出现（GG） | 造 fb 用户 + tt 用户（各带一个账户）→ 户管不带参数调用 → **两个都不在**结果里 |
| GG 看板含 gg 用户 | 造 gg 用户 → 在结果里（对照行，防「过滤过猛全滤掉」也绿） |
| `?platform=tt` 切换名单 | 同一次调用带 `?platform=tt` → tt 用户在、gg 用户不在 |
| 非法 platform 回落 gg | `?platform=fb` / `?platform=xx` → 等同不带参数 |
| developer 在 GG 看板保留 | 造 developer（platform='gg'）→ 在结果里（§3.1 的回归钉） |

最后一条尤其重要：它同时守住「265 户挂 developer 名下不会退化成禁用格」这个真实代价。

## 6. 涉及文件

| 文件 | 改动 |
|---|---|
| `py/routes/huguan_dashboard_routes.py` | 新增 `_owner_option_platform()`；`dashboard_owner_options` 加平台条件 + 重写 docstring |
| `py/tests/test_huguan_dashboard.py` | 改写 1 个用例 + 类 docstring；新增 5 条用例 |
| `frontend/src/composables/useOwnerPicker.js` | 仅注释 |
| `docs/superpowers/specs/2026-09-24-huguan-owner-source-and-picker-design.md` | §2.4 标注被本文取代 |
| `AGENTS.md` | 设计文档索引 + TT/户管相关段落的口径同步 |

前端零代码改动 → **无需 `npm run build`**；后端改动 → **需重启 Flask**。
