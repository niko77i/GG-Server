# 「户归属」下拉按平台隔离 — 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让 `/api/huguan/dashboard/owner-options` 只返回**当前看板平台**的用户。

**Architecture:** 在 `huguan_dashboard_routes.py` 内加一个局部 helper 解析 `?platform=`（白名单外回落 `gg`），SQL 加 `platform = ?`。前端零代码改动。

**Tech Stack:** Flask Blueprint / pytest / SQLite

**设计文档：** [2026-09-28-huguan-owner-options-platform-isolation-design.md](../specs/2026-09-28-huguan-owner-options-platform-isolation-design.md)

> **⚠️ 本计划已被 code-review 收口，Task 2 的代码块不再是最新。** 实现落地后审查发现纯
> `platform = ?` 会让跨平台角色（developer / 户管）在 TT 看板建的户锁死（归属格退化成
> 禁用态且无 UI 可修），口径最终定为 `platform = ? OR role IN PLATFORM_SWITCH_ROLES`。
> **以设计文档 §3.2 为准**，Task 2 的 SQL 与 helper docstring 均已过时；Task 1 描述的
> 测试改动仍有效（另多了一条 `test_cross_platform_roles_stay_on_tt_board`）。
> 变异结论也以设计文档 §5.2 为准（本文 Step 4 只做了「去掉过滤」一个方向）。

## Global Constraints

- 前端**零代码改动**（只改 `useOwnerPicker.js` 的注释）→ 本次**不需要** `npm run build`
- 该蓝图**不得 import main**（main 注册本蓝图，反向 import 会循环导入）
- 平台白名单 = `hd.PLATFORMS` = `("gg", "tt")`；白名单外的值一律回落 `gg`，**不是**「返回全部」
- `developer` **不特判** —— 靠其 `users.platform='gg'` 自然保留在 GG 看板
- 必须保留「无账户的用户也能被选中」（**不得**引入 `EXISTS(账户)` 限制）
- `viewer` / `hidden` 的排除维持不变

---

### Task 1: 改写既有测试 + 新增隔离用例（先红）

**Files:**
- Modify: `py/tests/test_huguan_dashboard.py:2767-2818`（`TestOwnerOptionsEndpoint`）

**Interfaces:**
- Consumes: `_create_user(client, username, role=, platform=)`、`_seed(db, username, display_name, role=, platform=)`（均在本文件内定义）
- Produces: 新的测试类 `TestOwnerOptionsPlatformIsolation`（Task 2 的实现要靠它转绿）

- [ ] **Step 1: 改写 `test_huguan_gets_all_users_including_account_less`**

该用例造的 `platform='tt'` 用户在新口径下**不该**出现，故把它改为 `platform='gg'`
（保住它真正要守的原意），并改写类 docstring（原文整段是为「不按平台过滤」辩护的）：

```python
class TestOwnerOptionsEndpoint:
    """「改归属」下拉的专用数据源 `/api/huguan/dashboard/owner-options`。

    它与 `/api/platform/users` 各服务一个场景：那个服务**筛选**（只列该平台有未删除
    账户的人，选项才有筛选价值），本端点服务**编辑**（不要求名下已有账户 ——
    刚建号、还没分到户的新人也要能选）。

    ⚠️ 平台隔离自 2026-09-28 起生效（见同日期设计文档）：本端点只返回
    **当前看板平台**的用户。此前它返回全部非 viewer/hidden 用户，理由是「转给谁的真实
    全集」——该理由在 2026-09-28 被实测推翻（GG 275 户 / TT 403 户的归属人 100%
    是本平台用户，跨平台持有 0 例），而代价是 GG 看板混入 FB 6 人 + TT 8 人。
    """

    _URL = "/api/huguan/dashboard/owner-options"

    def test_huguan_gets_all_users_including_account_less(self, client):
        """户管调用 → 200，且列表包含「在该平台没有任何账户」的用户。

        这条钉的是**无账户也能被选中**：一旦有人给它加上 EXISTS(账户) 限制，
        刚建号、还没分到户的新人就选不到了。平台取 gg（= GG 看板平台）——
        平台本身的口径由 TestOwnerOptionsPlatformIsolation 负责。
        """
        hg, _ = _create_user(client, "_oo_hg", role="huguan", platform="gg")
        db = database.get_db()
        no_acc = _seed(db, "_oo_noacc", "无户用户", role="user", platform="gg")
        db.close()
        resp = client.get(self._URL, headers=hg)
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["success"] is True
        by_id = {u["id"]: u for u in body["users"]}
        assert no_acc in by_id, "无账户的用户必须出现在「改归属」下拉里"
        # 返回形状与 /api/platform/users 逐字段一致，前端可无缝换源
        assert set(by_id[no_acc]) == {"id", "username", "display_name", "platform"}
        assert by_id[no_acc]["username"] == "_oo_noacc"
        assert by_id[no_acc]["display_name"] == "无户用户"
        assert by_id[no_acc]["platform"] == "gg"
```

`test_non_huguan_gets_403` 与 `test_viewer_and_hidden_are_excluded` **不动**
（后者的对照行 `normal` 走 `_seed` 默认 `platform='gg'`，新口径下照常出现）。

- [ ] **Step 2: 新增测试类**

紧接 `TestOwnerOptionsEndpoint` 之后插入：

```python
class TestOwnerOptionsPlatformIsolation:
    """「户归属」下拉按当前看板平台隔离（2026-09-28 设计文档）。

    口径：`platform = ?platform`（缺省 gg；白名单 hd.PLATFORMS=("gg","tt") 之外的值
    一律回落 gg，**不是**返回全部）。developer 不特判 —— 他的 users.platform 本就是
    gg，故 GG 看板自然保留、TT 看板自然排除。
    """

    _URL = "/api/huguan/dashboard/owner-options"

    def _ids(self, client, hg, **params):
        resp = client.get(self._URL, headers=hg, query_string=params)
        assert resp.status_code == 200
        return {u["id"] for u in resp.get_json()["users"]}

    def test_gg_board_excludes_other_platforms(self, client):
        """用户报的就是这一条：GG 看板里混着 FB / TT 平台的人。"""
        hg, _ = _create_user(client, "_opi_hg", role="huguan", platform="gg")
        db = database.get_db()
        gg = _seed(db, "_opi_gg", "GG人", role="user", platform="gg")
        fb = _seed(db, "_opi_fb", "FB人", role="user", platform="fb")
        tt = _seed(db, "_opi_tt", "TT人", role="user", platform="tt")
        db.close()
        ids = self._ids(client, hg)
        assert gg in ids, "对照腿：本平台用户不得被一并滤掉"
        assert fb not in ids
        assert tt not in ids

    def test_platform_param_switches_board(self, client):
        """带 ?platform=tt → 换成 TT 看板的名单。"""
        hg, _ = _create_user(client, "_opi_hg2", role="huguan", platform="gg")
        db = database.get_db()
        gg = _seed(db, "_opi_gg2", "GG人2", role="user", platform="gg")
        tt = _seed(db, "_opi_tt2", "TT人2", role="user", platform="tt")
        db.close()
        ids = self._ids(client, hg, platform="tt")
        assert tt in ids
        assert gg not in ids

    def test_unknown_platform_falls_back_to_gg(self, client):
        """白名单外的值回落 gg，而不是「不过滤」（后者会把 FB/TT 的人漏回来）。"""
        hg, _ = _create_user(client, "_opi_hg3", role="huguan", platform="gg")
        db = database.get_db()
        gg = _seed(db, "_opi_gg3", "GG人3", role="user", platform="gg")
        tt = _seed(db, "_opi_tt3", "TT人3", role="user", platform="tt")
        db.close()
        for bad in ("fb", "xx", ""):
            ids = self._ids(client, hg, platform=bad)
            assert gg in ids, bad
            assert tt not in ids, bad

    def test_developer_kept_on_gg_board(self, client):
        """回归钉：GG 看板必须保留 developer。

        生产 265 个活跃 GG 账户（96%）挂在 developer 名下。他一旦不在名单里，
        AdsAccountPanel.vue 的「未知归属」分支会被触发，那些行的户归属格退化成
        禁用的「用户 #N」，户管一个都改不了。
        """
        hg, _ = _create_user(client, "_opi_hg4", role="huguan", platform="gg")
        db = database.get_db()
        dev = _seed(db, "_opi_dev", "开发者", role="developer", platform="gg")
        db.close()
        assert dev in self._ids(client, hg)
```

- [ ] **Step 3: 跑测试，确认按预期变红**

Run: `cd py && python -m pytest tests/test_huguan_dashboard.py::TestOwnerOptionsEndpoint tests/test_huguan_dashboard.py::TestOwnerOptionsPlatformIsolation -q`

Expected: **恰好 3 条红** —— `test_gg_board_excludes_other_platforms`、`test_platform_param_switches_board`、
`test_unknown_platform_falls_back_to_gg`（都因 fb/tt 用户仍在名单里）。
另两条**绿**且都属正常：改写过的那条（`platform='gg'` 在旧口径下也在）、
`test_developer_kept_on_gg_board`（它守的是「别过度排除」，旧口径下 developer 本就在名单里）。

### Task 2: 后端实现（转绿）

**Files:**
- Modify: `py/routes/huguan_dashboard_routes.py`（`dashboard_owner_options`，约 176-201 行）

**Interfaces:**
- Produces: 模块级函数 `_owner_option_platform() -> str`
- Consumes: `hd.PLATFORMS`

- [ ] **Step 1: 加 helper**

插在 `dashboard_owner_options` 之前：

```python
def _owner_option_platform():
    """owner-options 要按哪个平台隔离。

    户管是 PLATFORM_SWITCH_ROLES 成员，其「有效平台」就等于 ?platform=（缺省 gg）
    —— 与 main._get_effective_platform 对户管的取值逐字相同。本模块不 import main
    （main 注册本 blueprint，反向 import 会循环），故就地实现这一条。

    白名单是必要的，且方向要看清：白名单外的值必须回落 gg，而不是「不过滤」——
    后者会把 FB/TT 的人漏回名单里，正好抵消本次隔离。
    """
    p = request.args.get("platform", "gg")
    return p if p in hd.PLATFORMS else "gg"
```

- [ ] **Step 2: 改 SQL 与 docstring**

`dashboard_owner_options` 内，把取数与查询改为：

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
        return ok({"users": [dict(r) for r in rows]})
```

docstring 里那句「**不按平台过滤**：这是「转给谁」的真实全集」**必须删掉**，
替换为当前口径，并留下「曾经为什么不隔离、为什么现在可以隔离」的来路 ——
否则下一个人遇到跨平台需求时会以为这是 bug 直接改回去：

```python
        """「户归属」下拉的数据源：可以直接把户转给他的**本平台**用户。

        排除 `viewer`（只读角色，转给它在业务上无意义，用户已裁定）与 `hidden`
        （被停用、无法登录）。**按当前看板平台过滤**（`?platform=`，白名单外回落 gg）：
        GG 看板只列 gg 平台用户，TT 看板只列 tt 平台用户。

        `developer` 不做特判：其 `users.platform` 本就是 `gg`，故在 GG 看板自然保留
        （生产 265 户挂他名下，缺了他那些行的归属格会退化成禁用态）、在 TT 看板自然排除
        （TT 无任何户挂他名下）。**别在这里加「显式排除 developer」**。

        本端点此前**不**按平台过滤，理由是「户管可能要把 GG 户转给只在 TT 有户的合法用户」。
        2026-09-28 用生产数据核销了这条理由（GG 275 户 / TT 403 户的归属人 100% 是本平台
        用户，跨平台持有 0 例），而代价是 GG 看板混入 FB 6 人 + TT 8 人。见
        docs/superpowers/specs/2026-09-28-huguan-owner-options-platform-isolation-design.md。
        """
```

- [ ] **Step 3: 跑测试，确认转绿**

Run: `cd py && python -m pytest tests/test_huguan_dashboard.py -q`

Expected: 全绿（Task 1 的 4 条红转绿，其余不回归）。

- [ ] **Step 4: 变异实测（守卫有效性）**

把 `AND platform = ?` 整段去掉、参数表也去掉，重跑 Task 1 的 4 条用例：

Run: `cd py && python -m pytest tests/test_huguan_dashboard.py::TestOwnerOptionsPlatformIsolation -q`

Expected: **恰好 3 红**（`test_developer_kept_on_gg_board` 在「不过滤」变异下仍绿 ——
它守的是「别过度排除」，与「别不过滤」是相反方向，这是对的）。
立刻还原。

再反向变异一次（把 helper 改成 `return "nonexistent"`，即过滤过猛）：
Expected: **6 红** —— 两个方向的守卫都真实有效，对照腿不是摆设。

- [ ] **Step 5: Commit**

```bash
git add py/routes/huguan_dashboard_routes.py py/tests/test_huguan_dashboard.py
git commit -m "feat(huguan): 户归属下拉按当前看板平台隔离"
```

### Task 3: 注释与文档索引同步

**Files:**
- Modify: `frontend/src/composables/useOwnerPicker.js:41-45`
- Modify: `docs/superpowers/specs/2026-09-24-huguan-owner-source-and-picker-design.md`（§2.4）
- Modify: `AGENTS.md`（设计文档索引）

- [ ] **Step 1: 改 `useOwnerPicker.js` 的注释**

现在写着：

```js
  // 数据源必须是户管专用的 owner-options，**不是** /platform/users：后者是给上方「归属人」
  // 筛选器用的，只列**该平台有未删除账户**的用户（那是筛选场景的有意设计，见
  // docs/superpowers/specs/2026-09-23-owner-filter-hide-empty-users-design.md）。拿它当改归属
  // 的选项源，户管就没法把 GG 的户转给一个只在 TT 有户的合法用户（实测缺口）。
  // 依据：docs/superpowers/specs/2026-09-24-huguan-owner-source-and-picker-design.md §2.4
```

改为：

```js
  // 数据源必须是户管专用的 owner-options，**不是** /platform/users：后者要求「名下已有
  // 未删除账户」，拿它当改归属的选项源，户管就没法把户转给刚建号、还没分到户的新人。
  // 两者现在**都按平台隔离**（2026-09-28 起，owner-options 也加了平台过滤），
  // 差别只剩这一条「是否要求已有账户」。
  // 依据：docs/superpowers/specs/2026-09-28-huguan-owner-options-platform-isolation-design.md
```

- [ ] **Step 2: 给 2026-09-24 spec 的 §2.4 加废止标注**

在 §2.4 那段「不按平台过滤」的理由**之后**追加一行（不要删原文，保留来路）：

```markdown
> **⚠️ 2026-09-28 修订：本节「不按平台过滤」的口径已被取代。** owner-options 现按
> `?platform=` 隔离（白名单外回落 gg），developer 靠其 `platform='gg'` 自然保留。
> 推翻依据：上述「跨平台转户」场景在生产数据里 0 例（GG 275 户 / TT 403 户的归属人
> 100% 是本平台用户），而代价是 GG 看板混入 FB 6 人 + TT 8 人。
> 见 [2026-09-28-huguan-owner-options-platform-isolation-design.md](2026-09-28-huguan-owner-options-platform-isolation-design.md)。
```

- [ ] **Step 3: 加 AGENTS.md 索引**

在「GG-Server 独立设计文档」列表末尾（`[续作指南]` 之前）插入一行：

```markdown
- [户归属下拉按平台隔离](docs/superpowers/specs/2026-09-28-huguan-owner-options-platform-isolation-design.md)
```

- [ ] **Step 4: Commit**

```bash
git add frontend/src/composables/useOwnerPicker.js docs/superpowers/specs/2026-09-24-huguan-owner-source-and-picker-design.md AGENTS.md
git commit -m "docs(huguan): 户归属平台隔离的口径同步（旧注释与 §2.4 废止标注 + 索引）"
```

---

## 交付提醒

- 后端改动 → **需重启 Flask 才生效**
- 前端**零代码改动**（只有注释）→ **不需要 `npm run build`**
