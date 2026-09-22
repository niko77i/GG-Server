# 户管角色与权限 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 新增「户管」角色，使其可跨平台切换、跨用户查看/编辑 GG/FB/TT 的账户类数据（账户、MCC、BC、BM、像素），可编辑平台级下拉选项，并只能创建/管理自己创建的户管账号。

**Architecture:** 不改表结构。把 `huguan` 加入三个**语义不同**的角色集合（跨平台切换 / 跨用户账户可见性 / 平台级选项编辑），并按 TT 平台**已有的**「跨用户可见 + `owner_id` 筛选」模式复刻到 GG / FB。前端复用现有的三层平台切换链路（`effectivePlatform` → `client.js` 注入 `?platform=` → 后端 `_get_effective_platform`）。用户管理靠已有的 `users.created_by` 字段把户管的操作范围收窄到「自己创建的户管」。最后（Task 17）为产品 / 素材域补一个 `@no_huguan` 守卫，把「户管只管账户域」这条约束真正落到后端。

**Tech Stack:** Flask + flask_jwt_extended + SQLite（后端 `py/`）；Vue 3 + Element Plus + Pinia + Vue Router hash history（前端 `frontend/`）；pytest（后端测试）。

**设计文档：** [docs/superpowers/specs/2026-09-22-huguan-role-design.md](../specs/2026-09-22-huguan-role-design.md)

## Global Constraints

- **角色名恒为字符串 `"huguan"`**（后端）与 `'huguan'`（前端），全库统一，不出现 `huguan_role` / `account_manager` 等变体。
- **纯增量原则**：不修改任何现有角色的行为。所有改动对 `developer` / `admin` / `user` / `viewer` / `hidden` 必须保持当前判定结果。唯一允许的行为变化是把 `huguan` 加入集合。
- **不新增数据库表、不新增列**。`users.role` 是 `TEXT`，新枚举值无需迁移。
- **常量单一事实来源**：`py/routes/helpers.py` 定义四个常量，**语义不同、不可互换**：
  - `HUGUAN_ROLE = "huguan"`
  - `PLATFORM_SWITCH_ROLES = ("developer", HUGUAN_ROLE)` — **跨平台切换**（`require_platform`、`_get_effective_platform`）。**不含 admin**：admin 自身按平台隔离（`c4b3d56` 已落地，`test_user_platform_isolation.py:115` 锁定）。
  - `CROSS_USER_ROLES = ("developer", "admin", HUGUAN_ROLE)` — **账户域跨用户可见性**（账户 / MCC / BC / BM / 像素）。
  - `GLOBAL_OPTION_ROLES = ("developer", "admin", HUGUAN_ROLE)` — **平台级下拉选项编辑**。

  禁止在各调用点重新写字面量元组。任何「让户管跨平台」的改动一律用 `PLATFORM_SWITCH_ROLES`；误用 `CROSS_USER_ROLES` 会把 admin 的跨平台越权改回来并打挂既有测试。
- **保留既有错误文案**：`不能操作同级管理员`、`不能操作其他平台的用户` 两条字符串及其测试断言是已落地的「用户角色平台隔离」功能的一部分，**不得改动**。户管的拒绝原因用新字符串。
- **前端无测试框架**（`frontend/package.json` 只有 `dev` / `build` / `preview`）。前端任务的验证门槛是 `npm run build` 成功 + 计划内逐条列出的手工核对清单。不为本需求引入测试框架。
- **后端测试命令**：`cd py && python -m pytest tests/ -v`。测试依赖 `py/tests/conftest.py` 提供的 `app` / `client` 夹具（临时数据库 + JWT）。
- **`huguan` 不获得产品/视频的编辑权**，且这一条**必须由后端机制落实**（Task 17）。`helpers.can_modify` 在生产代码中零调用，**不能作为防线**；TT / FB 产品域的唯一关卡是 `require_platform`，放宽后户管即可直达。`tt_routes._check_product_owner` / `_check_product_view` / `fb_routes.py:471` 的产品过滤保持不动。

---

### Task 1: 角色常量与跨平台后端放行

> **执行勘误（2026-09-22）**：本任务已按 `fb7b755` 完成。执行时发现原计划 Step 4 / Step 5 引用的「before」代码是**平台隔离改动之前的旧快照**，照字面执行会让 `admin` 首次获得跨平台路由/写权限，并打挂既有测试 `test_user_platform_isolation.py:115`。实际执行改为：两个平台切换闸门统一使用新增的第 4 个常量 `PLATFORM_SWITCH_ROLES = ("developer", HUGUAN_ROLE)`。下方 Step 3 / 4 / 5 已按实际执行修订。后续任务（尤其 Task 8 的常量替换）**一律以本节的常量语义为准**。

**Files:**
- Modify: `py/routes/helpers.py`（在文件头部 docstring 之后新增常量）
- Modify: `py/routes/decorators.py:59-60`（`require_platform` 的放行判断）
- Modify: `py/main.py`（新增一行 import；`_get_effective_platform` 在 `py/main.py:5779`）
- Test: `py/tests/test_huguan_role.py`（新建）

**Interfaces:**
- Consumes: 无（本任务是最底层）
- Produces:
  - `py/routes/helpers.py` 模块级常量：`HUGUAN_ROLE: str = "huguan"`、`CROSS_USER_ROLES: tuple = ("developer", "admin", "huguan")`、`GLOBAL_OPTION_ROLES: tuple = ("developer", "admin", "huguan")`
  - `require_platform(platform) -> None | flask.Response`（语义扩展：`role in CROSS_USER_ROLES` 时放行）
  - `_get_effective_platform() -> str`（语义扩展：`role in GLOBAL_OPTION_ROLES` 时按 `?platform=` 取值）
  - 测试辅助函数 `_create_user(client, username, role="user", platform="gg", created_by=None) -> tuple[dict, int]`，返回 `(headers, user_id)`，供后续所有任务复用

- [ ] **Step 1: 写失败测试**

新建 `py/tests/test_huguan_role.py`：

```python
"""户管（huguan）角色权限测试。"""
import database


def _create_user(client, username, role="user", platform="gg", created_by=None):
    """注册用户 → 直接改写 role/platform/created_by → 登录，返回 (headers, user_id)。"""
    client.post("/api/auth/register", json={"username": username, "password": "test123"})
    db = database.get_db()
    db.execute("UPDATE users SET role=?, platform=?, created_by=? WHERE username=?",
               (role, platform, created_by, username))
    db.commit()
    row = db.execute("SELECT id FROM users WHERE username=?", (username,)).fetchone()
    db.close()
    resp = client.post("/api/auth/login", json={"username": username, "password": "test123"})
    token = resp.get_json().get("access_token", "")
    return {"Authorization": f"Bearer {token}"}, row["id"]


def _huguan(client, username="_hg_main", platform="gg"):
    return _create_user(client, username, role="huguan", platform=platform)


class TestHuguanCrossPlatformAccess:
    def test_huguan_can_call_tt_endpoint(self, client):
        """户管的 users.platform 是 gg，但切到 TT 后调 TT 接口不应被 403。"""
        hg, _ = _huguan(client, "_hg_xplat")
        resp = client.get("/api/tt/users?platform=tt", headers=hg)
        assert resp.status_code == 200

    def test_huguan_effective_platform_follows_query_param(self, client):
        """户管的 _get_effective_platform 应跟随 ?platform=，而非固定用 users.platform。"""
        hg, _ = _huguan(client, "_hg_effplat")
        db = database.get_db()
        db.execute("INSERT INTO account_statuses(name, platform, owner_id) VALUES(?,?,?)",
                   ("TT专属状态", "tt", None))
        db.execute("INSERT INTO account_statuses(name, platform, owner_id) VALUES(?,?,?)",
                   ("GG专属状态", "gg", None))
        db.commit()
        db.close()
        resp = client.get("/api/statuses/list?platform=tt", headers=hg)
        names = [s["name"] for s in resp.get_json()["statuses"]]
        assert "TT专属状态" in names
        assert "GG专属状态" not in names

    def test_regular_user_still_blocked_on_other_platform(self, client):
        """回归：普通 GG 用户调 TT 接口仍然 403。"""
        u, _ = _create_user(client, "_hg_reg_gg", role="user", platform="gg")
        resp = client.get("/api/tt/users?platform=tt", headers=u)
        assert resp.status_code == 403
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd py && python -m pytest tests/test_huguan_role.py -v`
Expected: `TestHuguanCrossPlatformAccess` 两条 FAIL（`test_huguan_can_call_tt_endpoint` 得到 403；`test_huguan_effective_platform_follows_query_param` 报 `KeyError: 'TT专属状态'` 不在列表中）。第三条回归用例 PASS。

- [ ] **Step 3: 在 `py/routes/helpers.py` 新增常量**

在文件第 1 行 docstring 之后、`from flask import ...` 之前插入：

```python
HUGUAN_ROLE = "huguan"

# 可跨用户查看/编辑账户类数据的角色（账户、MCC、BC、BM、像素）
CROSS_USER_ROLES = ("developer", "admin", HUGUAN_ROLE)

# 可编辑平台级下拉选项的角色（代理名、账户状态、MCC等级、地区时区、商务人员）
GLOBAL_OPTION_ROLES = ("developer", "admin", HUGUAN_ROLE)

# 可跨平台切换的角色（require_platform / _get_effective_platform）。
# 注意不含 admin —— admin 自身按平台隔离。
PLATFORM_SWITCH_ROLES = ("developer", HUGUAN_ROLE)
```

- [ ] **Step 4: 修改 `py/routes/decorators.py` 的 `require_platform`**

该文件第 5 行已是 `from routes.helpers import err`，改为：

```python
from routes.helpers import err, PLATFORM_SWITCH_ROLES
```

把第 59-60 行：

```python
    if user.get("role") == "developer":
        return None
```

改为：

```python
    if user.get("role") in PLATFORM_SWITCH_ROLES:
        return None
```

并把函数 docstring 从 `"""检查当前用户是否属于指定平台。developer 直接放行。返回错误响应或 None。"""` 改为 `"""检查当前用户是否属于指定平台。可切换平台的角色（developer/户管）直接放行。返回错误响应或 None。"""`

- [ ] **Step 5: 在 `py/main.py` 引入常量并修改 `_get_effective_platform`**

在 `py/main.py:38`（`from routes.decorators import ...` 那行）之后新增一行：

```python
from routes.helpers import PLATFORM_SWITCH_ROLES
```

把 `py/main.py:5776`（`_get_effective_platform` 内）的：

```python
    if user and user.get("role") == "developer":
        return request.args.get("platform", "gg")
```

改为：

```python
    if user and user.get("role") in PLATFORM_SWITCH_ROLES:
        return request.args.get("platform", "gg")
```

并把函数 docstring 改为：

```python
    """获取当前用户的有效平台。developer/户管 可按请求参数跨平台（缺省 'gg'）；其他角色一律取自己的 platform。
    注意：admin 不再视为跨平台 —— 管理员本身按平台隔离（见用户角色平台隔离设计）。
    """
```

> 注意：**不要**用 `GLOBAL_OPTION_ROLES`（含 admin）—— 它用于「平台级下拉选项编辑」这一**不同**语义（Task 10），与平台切换闸门无关。两者混用会让 admin 重新跨平台。

- [ ] **Step 6: 运行测试确认通过**

Run: `cd py && python -m pytest tests/test_huguan_role.py -v`
Expected: 3 passed

- [ ] **Step 7: 跑全量后端测试，确认零回归**

Run: `cd py && python -m pytest tests/ -v`
Expected: 全部 passed（`test_user_platform_isolation.py`、`test_tt_platform.py`、`test_fb_platform.py` 等均不得出现 FAILED）

- [ ] **Step 8: 提交**

```bash
git add py/routes/helpers.py py/routes/decorators.py py/main.py py/tests/test_huguan_role.py
git commit -m "feat: 新增户管角色常量与跨平台后端放行"
```

---

### Task 2: `py/auth.py` 三处基础修复

**Files:**
- Modify: `py/auth.py:191`（`toggle_user_status`）
- Modify: `py/auth.py:121-132`（`update_user_role`）
- Modify: `py/auth.py:60-118`（`list_users`）
- Test: `py/tests/test_huguan_role.py`（追加）

**Interfaces:**
- Consumes: Task 1 的 `_create_user` / `_huguan` 测试辅助函数
- Produces:
  - `auth.toggle_user_status(user_id: int) -> dict | None`（启停户管后进入 `hidden`，不再被误降级为 `user`；取消隐藏回落 `user` 属既有单向行为，本需求不改）
  - `auth.update_user_role(user_id: int, new_role: str) -> bool`（新增白名单断言：`new_role in ("user","admin","viewer","hidden","huguan")`）
  - `auth.list_users(search="", page=1, page_size=20, current_user_id=None, platform=None, role_filter=None) -> dict`（新增第 6 个**可选**参数，默认 `None` 时行为与现状完全一致）

- [ ] **Step 1: 写失败测试**

在 `py/tests/test_huguan_role.py` 末尾追加：

```python
class TestAuthRoleFixes:
    def test_toggle_huguan_hides_instead_of_demoting(self, client):
        """启停户管应进入 hidden；修复前因元组缺 huguan 会直接被降级成 user。"""
        import auth
        _, uid = _huguan(client, "_hg_toggle")
        assert auth.toggle_user_status(uid)["role"] == "hidden"

    def test_unhide_falls_back_to_user_for_all_roles(self, client):
        """前半锁定**本次新增**的户管隐藏行为（huguan → hidden，由 `py/auth.py:199` 元组修复带来）；
        后半锁定**既有**语义：取消隐藏一律回落 user —— 该语义对 admin / viewer 在改动前即成立。

        保护范围说明：循环第 0 腿是 huguan，其 `== "hidden"` 断言**依赖本次修复**，
        因此本用例在修复前是失败的，不是纯回归锁定。户管隐藏方向的独立覆盖见
        `test_toggle_huguan_hides_instead_of_demoting`。
        如需改成「取消隐藏恢复原角色」，那是独立的产品决策（需记忆字段），不在本需求范围。
        """
        import auth
        for idx, role in enumerate(("huguan", "admin", "viewer")):
            _, uid = _create_user(client, f"_hg_unhide_{idx}", role=role)
            assert auth.toggle_user_status(uid)["role"] == "hidden"
            assert auth.toggle_user_status(uid)["role"] == "user"

    def test_update_user_role_rejects_unknown_role(self, client):
        """角色白名单：非法角色值一律拒绝。"""
        import auth
        _, uid = _create_user(client, "_hg_badrole", role="user")
        assert auth.update_user_role(uid, "superuser") is False
        assert auth.update_user_role(uid, "huguan") is True

    def test_list_users_role_filter_default_unchanged(self, client):
        """不传 role_filter 时结果与改动前一致。

        注意 developer 视角下 list_users 不加任何角色过滤（filters = [""]），
        因此 developer 账号本身也会出现在结果里——这正是改动前的行为，必须保持。
        """
        import auth
        _, dev_id = _create_user(client, "_hg_lf_dev", role="developer")
        _create_user(client, "_hg_lf_admin", role="admin")
        _create_user(client, "_hg_lf_user", role="user")
        res = auth.list_users(current_user_id=dev_id)
        roles = {u["role"] for u in res["users"]}
        assert roles == {"developer", "admin", "user"}

    def test_list_users_role_filter_huguan_only(self, client):
        import auth
        _, dev_id = _create_user(client, "_hg_lf2_dev", role="developer")
        _create_user(client, "_hg_lf2_hg", role="huguan")
        _create_user(client, "_hg_lf2_user", role="user")
        res = auth.list_users(current_user_id=dev_id, role_filter="huguan")
        assert {u["role"] for u in res["users"]} == {"huguan"}
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd py && python -m pytest tests/test_huguan_role.py -v -k AuthRoleFixes`
Expected: `test_toggle_huguan_hides_instead_of_demoting` FAIL（得到 `user` 而非 `hidden`）；`test_update_user_role_rejects_unknown_role` FAIL（写入了 `superuser`）；`test_list_users_role_filter_huguan_only` FAIL（`TypeError: list_users() got an unexpected keyword argument 'role_filter'`）。

`test_unhide_falls_back_to_user_for_all_roles` 与 `test_list_users_role_filter_default_unchanged` 属**回归锁定**用例，改动前就应 PASS；若它们 FAIL，说明测试数据构造有误，先修测试再继续。

- [ ] **Step 3: 修复 `toggle_user_status`**

`py/auth.py:191` 把：

```python
        new_role = "hidden" if row["role"] in ("user", "admin", "viewer") else "user"
```

改为：

```python
        new_role = "hidden" if row["role"] in ("user", "admin", "viewer", "huguan") else "user"
```

- [ ] **Step 4: 给 `update_user_role` 加白名单**

`py/auth.py:121` 的函数开头改为：

```python
def update_user_role(user_id: int, new_role: str) -> bool:
    # 纵深防御：即使调用方漏校验，也不允许写入未知角色
    if new_role not in ("user", "admin", "viewer", "hidden", "huguan"):
        return False
    conn = database.get_db()
    try:
        cur = conn.execute("SELECT role FROM users WHERE id = ?", (user_id,))
        row = cur.fetchone()
        if not row or row["role"] == "developer":
            return False
        conn.execute("UPDATE users SET role = ? WHERE id = ?", (new_role, user_id))
        conn.commit()
        return True
    finally:
        conn.close()
```

- [ ] **Step 5: 给 `list_users` 加 `role_filter`**

`py/auth.py:60` 签名改为：

```python
def list_users(search: str = "", page: int = 1, page_size: int = 20, current_user_id: int = None, platform: str = None, role_filter: str = None) -> dict:
    """列出用户。非 developer 只看自己平台且看不到 developer；developer 看全部（可选按 platform 筛）。
    platform: 可选筛选 ('gg' | 'fb' | 'tt')，仅 developer 生效，None 表示不过滤。
    role_filter: 可选角色筛选，None 表示不过滤（默认行为与历史一致）。
    """
```

在 `py/auth.py:85-86` 之间（`elif platform:` 分支之后、`base_where = ...` 之前）插入：

```python
        if role_filter:
            filters.append("role = ?")
            params.append(role_filter)
```

并把 docstring 下方原有的 `# 非 developer 用户看不到 developer 角色，且只能看自己平台` 注释保持原样不动。

- [ ] **Step 6: 运行测试确认通过**

Run: `cd py && python -m pytest tests/test_huguan_role.py -v -k AuthRoleFixes`
Expected: 4 passed

- [ ] **Step 7: 跑全量后端测试**

Run: `cd py && python -m pytest tests/ -v`
Expected: 全部 passed

- [ ] **Step 8: 提交**

```bash
git add py/auth.py py/tests/test_huguan_role.py
git commit -m "fix: 户管角色在启停与角色白名单中的缺失"
```

---

### Task 3: 用户管理接口放行户管并收窄范围

> **执行勘误（2026-09-22，派发前预检）**：
>
> **(1) 行号一律按内容定位，勿信本节的数字。** 本节写入后仓库又落了 `c4b3d56`，全部行号已漂移：`_check_modify_user` 实际在 `py/main.py:7460-7469`（非 7455-7464），`admin_list_users` 在 `:7447`（非 7445），`admin_update_role` 在 `:7485`（非 7472），`admin_toggle_user` 在 `:7508`，`admin_delete_user` 在 `:7528`，`admin_update_user` 在 `:7579`，`admin_reset_password` 在 `:7619`，`admin_set_telegram_username` 在 `:7648`。**照数字替换会砸掉相邻函数**（例如 7455-7464 实际横跨 `admin_list_users` 尾部与 `_check_modify_user` 开头）。一律 grep 函数名后再改。
>
> **(2) Step 4 中 `admin_update_role` 的 `allowed` 计算会破坏纯增量原则，已修订。** 原写法 `allowed = _huguan_allowed_roles(user["role"])` 直接复用 `ALLOWED_CREATE_ROLES`，而该表的四个值里**都没有 `hidden`**；但现状 `py/main.py:7500` 是 `if new_role not in ("user", "admin", "viewer", "hidden")` —— 即 developer / admin **目前可以通过该接口把角色设为 `hidden`**。沿用原写法会让这一能力从 200 变 400，属「修改现有角色行为」，违反 Global Constraints，且既有测试零覆盖（全 `py/tests/` 无 `role.*hidden` 断言），不会被红灯拦下。修订为「创建白名单 ∪ {hidden}」。下方 Step 4 已改正。
>
> **(3) 确认 `_check_modify_user` 是唯一收口点。** 全仓 6 处调用（`py/main.py:7495,7518,7538,7592,7632,7658`）覆盖本任务涉及的全部接口，因此户管分支只需加在该函数内，**不需要**在每个接口里重复写角色判断。
>
> **(4) 已知设计后效（不在本任务修，记录备查）。** 户管把自己的下属户管设为 `hidden` 后，该账号 `role` 变为 `hidden`，此后 `_check_modify_user` 的 `target["role"] != "huguan"` 分支会拒绝户管对其再做任何操作（含取消隐藏、删除）；同时 `role_filter="huguan"` 使其不再出现在户管的列表里，户管无从点选。即：**户管一旦停用下属户管，就再也无法自行恢复**。是否允许户管操作「自己创建的、当前为 hidden 的账号」属独立产品决策，本任务按计划原样执行，不擅自扩权。

**Files:**
- Modify: `py/main.py:7411`（`admin_create_user` 入口 + 角色白名单）
- Modify: `py/main.py:7447`（`admin_list_users` 入口 + `role_filter`）
- Modify: `py/main.py:7460-7469`（`_check_modify_user` 增加户管分支，并在其上新增两个模块级定义）
- Modify: `py/main.py:7485`、`:7500`（`admin_update_role` 入口 + 户管可选角色）
- Modify: `py/main.py:7508`（`admin_toggle_user` 入口）
- Modify: `py/main.py:7528`（`admin_delete_user` 入口）
- Modify: `py/main.py:7579`（`admin_update_user` 入口）
- Modify: `py/main.py:7607`（`admin_reset_password` 入口）
- Modify: `py/main.py:7636`（`admin_set_telegram_username` 入口）
- Test: `py/tests/test_huguan_role.py`（追加）

**Interfaces:**
- Consumes: Task 1 的 `_create_user` / `_huguan`；Task 2 的 `auth.list_users(..., role_filter=...)`
- Produces:
  - `_check_modify_user(actor: dict, target: dict) -> str | None`
  - 模块级常量 `ALLOWED_CREATE_ROLES: dict[str, tuple[str, ...]]`
  - 模块级辅助函数 `_huguan_allowed_roles(actor_role: str) -> tuple[str, ...]`（返回该角色的创建白名单，未收录时返回 `()`）
  - 户管分支拒绝文案：`"户管只能操作户管账号"`、`"只能操作自己创建的户管"`

- [ ] **Step 1: 写失败测试**

在 `py/tests/test_huguan_role.py` 末尾追加：

```python
class TestHuguanUserManagement:
    def test_create_ignores_requested_role(self, client):
        """户管创建用户时传 role=admin，落库仍为 huguan。"""
        hg, hg_id = _huguan(client, "_hgm_create")
        resp = client.post("/api/admin/users/create", json={
            "username": "_hgm_new1", "password": "test123", "role": "admin",
        }, headers=hg)
        assert resp.status_code == 200
        db = database.get_db()
        row = db.execute("SELECT role, platform, created_by FROM users WHERE username='_hgm_new1'").fetchone()
        db.close()
        assert row["role"] == "huguan"
        assert row["platform"] == "gg"
        assert row["created_by"] == hg_id

    def test_list_returns_only_huguan(self, client):
        hg, _ = _huguan(client, "_hgm_list")
        db = database.get_db()
        db.execute("INSERT INTO users(username, password, role, platform) VALUES('_hgm_u','x','user','gg')")
        db.commit()
        db.close()
        resp = client.get("/api/admin/users", headers=hg)
        assert resp.status_code == 200
        roles = {u["role"] for u in resp.get_json()["users"]}
        assert roles == {"huguan"}

    def test_huguan_cannot_promote_own_huguan(self, client):
        hg, _ = _huguan(client, "_hgm_promote")
        client.post("/api/admin/users/create", json={
            "username": "_hgm_sub1", "password": "test123"}, headers=hg)
        db = database.get_db()
        sub_id = db.execute("SELECT id FROM users WHERE username='_hgm_sub1'").fetchone()["id"]
        db.close()
        resp = client.post(f"/api/admin/users/{sub_id}/role", json={"role": "admin"}, headers=hg)
        assert resp.status_code == 400
        resp = client.post(f"/api/admin/users/{sub_id}/role", json={"role": "hidden"}, headers=hg)
        assert resp.status_code == 200

    def test_huguan_cannot_touch_others_huguan(self, client):
        hg_a, _ = _huguan(client, "_hgm_ownerA")
        hg_b, _ = _huguan(client, "_hgm_ownerB")
        client.post("/api/admin/users/create", json={
            "username": "_hgm_subB", "password": "test123"}, headers=hg_b)
        db = database.get_db()
        sub_b = db.execute("SELECT id FROM users WHERE username='_hgm_subB'").fetchone()["id"]
        db.close()
        resp = client.delete(f"/api/admin/users/{sub_b}", headers=hg_a)
        assert resp.status_code == 403
        assert resp.get_json()["error"] == "只能操作自己创建的户管"

    def test_huguan_cannot_touch_admin_or_user(self, client):
        hg, _ = _huguan(client, "_hgm_touch")
        _, user_id = _create_user(client, "_hgm_plain", role="user")
        _, admin_id = _create_user(client, "_hgm_admin", role="admin")
        for target in (user_id, admin_id):
            resp = client.post(f"/api/admin/users/{target}/toggle", headers=hg)
            assert resp.status_code == 403
            assert resp.get_json()["error"] == "户管只能操作户管账号"

    def test_huguan_cannot_toggle_self(self, client):
        hg, hg_id = _huguan(client, "_hgm_self")
        resp = client.post(f"/api/admin/users/{hg_id}/toggle", headers=hg)
        assert resp.status_code == 403
        assert resp.get_json()["error"] == "不能禁用自己"

    def test_admin_cannot_create_huguan(self, client):
        admin, _ = _create_user(client, "_hgm_admin2", role="admin")
        resp = client.post("/api/admin/users/create", json={
            "username": "_hgm_byadmin", "password": "test123", "role": "huguan",
        }, headers=admin)
        assert resp.status_code == 400
        assert resp.get_json()["error"] == "Invalid role"

    def test_developer_can_create_huguan(self, client):
        dev, _ = _create_user(client, "_hgm_dev", role="developer")
        resp = client.post("/api/admin/users/create", json={
            "username": "_hgm_bydev", "password": "test123", "role": "huguan",
        }, headers=dev)
        assert resp.status_code == 200

    def test_admin_platform_isolation_regression(self, client):
        """回归：平台隔离的错误文案与行为不变。"""
        _create_user(client, "_hgm_gg_user", role="user", platform="gg")
        tt_admin, _ = _create_user(client, "_hgm_tt_admin", role="admin", platform="tt")
        db = database.get_db()
        gg_uid = db.execute("SELECT id FROM users WHERE username='_hgm_gg_user'").fetchone()["id"]
        db.close()
        resp = client.post(f"/api/admin/users/{gg_uid}/role", json={"role": "viewer"}, headers=tt_admin)
        assert resp.status_code == 403
        assert resp.get_json()["error"] == "不能操作其他平台的用户"

    def test_huguan_cannot_trigger_scheduler(self, client):
        """户管不得获得定时任务权限（该接口只认 developer）。"""
        hg, _ = _huguan(client, "_hgm_sched")
        resp = client.post("/api/admin/trigger-weekly-cleanup", headers=hg)
        assert resp.status_code == 403

    def test_developer_and_admin_can_still_set_hidden(self, client):
        """回归：改角色接口对 developer / admin 仍能把用户设为 `hidden`。

        改动前 `py/main.py:7500` 的白名单是 `("user","admin","viewer","hidden")`，本任务把它
        换成「创建白名单 ∪ {hidden}」。若漏掉 `"hidden"` 的并集，developer / admin 会从 200 变 400 ——
        既违反纯增量原则，又因全仓无 `role.*hidden` 断言而不会被任何红灯拦下。本用例即为此设的守卫。
        """
        dev, _ = _create_user(client, "_hgm_dev_h", role="developer")
        admin, _ = _create_user(client, "_hgm_admin_h", role="admin")
        _, u1 = _create_user(client, "_hgm_h1", role="user")
        _, u2 = _create_user(client, "_hgm_h2", role="user")
        assert client.post(f"/api/admin/users/{u1}/role",
                           json={"role": "hidden"}, headers=dev).status_code == 200
        assert client.post(f"/api/admin/users/{u2}/role",
                           json={"role": "hidden"}, headers=admin).status_code == 200
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd py && python -m pytest tests/test_huguan_role.py -v -k HuguanUserManagement`
Expected: 除两条**回归锁定**用例外全部 FAIL（户管调这些接口现在一律 403 `Permission denied`）。
两条应 PASS 的回归锁定用例：`test_admin_platform_isolation_regression`、`test_developer_and_admin_can_still_set_hidden`。
后者若在改动前就 FAIL，说明你改坏了 developer/admin 设 `hidden` 的能力，先修实现再继续。`test_admin_cannot_create_huguan` 改动前也应 PASS（admin 原本就无权建 huguan）。

- [ ] **Step 3: 新增 `ALLOWED_CREATE_ROLES` 与改写 `_check_modify_user`**

先在 `py/main.py:7460` 之前插入两个模块级定义（即 `admin_list_users` 与 `_check_modify_user` 之间），再整体替换 `py/main.py:7460-7469` 的 `_check_modify_user`。合并后的结果应为：

```python
ALLOWED_CREATE_ROLES = {
    "developer": ("user", "admin", "viewer", "huguan"),
    "admin": ("user", "admin", "viewer"),
    "huguan": ("huguan",),
}


def _huguan_allowed_roles(actor_role: str) -> tuple:
    """该角色允许创建/切换到的角色集合。未收录角色返回空元组。"""
    return ALLOWED_CREATE_ROLES.get(actor_role, ())


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

- [ ] **Step 4: 逐接口放行户管**

以下每一处都是把同一个判断表达式替换掉。

`admin_create_user`（`py/main.py:7411`）：

```python
    if not user or user["role"] not in ("developer", "admin"):
```

改为：

```python
    if not user or user["role"] not in ("developer", "admin", "huguan"):
```

同一函数内 `py/main.py:7417-7424`，把：

```python
    role = data.get("role", "user")
    platform = data.get("platform", "gg")
```
...
```python
    if role not in ("user", "admin", "viewer"):
        return jsonify(success=False, error="Invalid role"), 400
```

改为（在取 `role` 之后立即按身份收窄）：

```python
    role = data.get("role", "user")
    platform = data.get("platform", "gg")
    allowed = _huguan_allowed_roles(user["role"])
    # 户管：忽略请求体传入的 role，强制为 huguan
    if user["role"] == "huguan":
        role = "huguan"
    if role not in allowed:
        return jsonify(success=False, error="Invalid role"), 400
```

`admin_list_users`（`py/main.py:7445`）同法加上 `"huguan"`；并把 `py/main.py:7451` 改为：

```python
    role_filter = "huguan" if user["role"] == "huguan" else None
    result = auth.list_users(search, page, page_size, current_user_id=user_id,
                             platform=platform, role_filter=role_filter)
```

`admin_update_role`（`py/main.py:7485`）同法加上 `"huguan"`；并把 `py/main.py:7500` 的：

```python
    if new_role not in ("user", "admin", "viewer", "hidden"):
```

改为（**注意必须并入 `"hidden"`**，理由见本节执行勘误 (2)）：

```python
    # 改角色接口的白名单 = 创建白名单 ∪ {hidden}（沿用既有「可设为 hidden」的能力）
    # 户管额外只能在自己的 huguan / hidden 之间切换
    allowed = tuple(_huguan_allowed_roles(user["role"])) + ("hidden",)
    if user["role"] == "huguan":
        allowed = ("huguan", "hidden")
    if new_role not in allowed:
        return jsonify(success=False, error="Invalid role"), 400
```

等价性核对（必须逐条成立，实现后自查）：
- developer：`("user","admin","viewer","huguan","hidden")` ⊇ 现状 `("user","admin","viewer","hidden")` —— 只多出 `huguan`（本需求要的增量）。
- admin：`("user","admin","viewer","hidden")` —— 与现状**逐位相同**。
- huguan：`("huguan","hidden")` —— 既不能提权为 admin（`test_huguan_cannot_promote_own_huguan` 断言 400），又能把下属设为 hidden（同一用例断言 200）。

`admin_toggle_user`（`py/main.py:7508`）、`admin_delete_user`（`py/main.py:7528`）、`admin_update_user`（`py/main.py:7579`）、`admin_reset_password`（`py/main.py:7619`）、`admin_set_telegram_username`（`py/main.py:7648`）五处，一律把：

```python
    if not user or user["role"] not in ("developer", "admin"):
```

改为：

```python
    if not user or user["role"] not in ("developer", "admin", "huguan"):
```

`admin_delete_user` 内 `py/main.py:7541-7542` 的 `if target["role"] == "developer"` 兜底保持不动（户管已在上方 `_check_modify_user` 被拒，到不了这里）。

- [ ] **Step 5: 运行测试确认通过**

Run: `cd py && python -m pytest tests/test_huguan_role.py -v -k HuguanUserManagement`
Expected: 11 passed

- [ ] **Step 6: 跑全量后端测试**

Run: `cd py && python -m pytest tests/ -v`
Expected: 全部 passed。特别确认 `tests/test_user_platform_isolation.py` 的 9 个用例全绿——它断言的正是 Task 3 必须保留的两条错误文案。

- [ ] **Step 7: 提交**

```bash
git add py/main.py py/tests/test_huguan_role.py
git commit -m "feat: 用户管理接口放行户管并收窄到自己创建的户管"
```

---

### Task 4: 通用用户列表接口 `GET /api/platform/users`

> **执行勘误（2026-09-22，评审后修订）**：Step 1 原稿的两条用例**验证不了自己命名的分支**，已加强如下，实现须按加强版落地。
>
> **(1) `test_includes_developer_excludes_hidden` 的 `OR role = 'developer'` 分支零覆盖。** 原稿把 `_hgpu_dev` 插成 `role='developer', platform='gg'`，而查询用的是 `?platform=gg` —— 该行**被 `platform = ?` 条件本身命中**，因此即使把 `OR role = 'developer'` 整段删掉，`assert "_hgpu_dev" in names` 依然通过。修法：把该行插成 `platform='tt'`，使其**只能**经 developer 分支命中（`role='developer'` 与 `platform='gg'` 两条路径互斥），断言才真正承载语义。缓存侧断言（`"_hgpu_hid" not in names`）原稿本来就可靠。
>
> **(2) `test_huguan_sees_only_current_platform` 未覆盖平台切换。** `_huguan` 默认 `platform='gg'`，而请求也是 `?platform=gg` —— 与调用者自身平台相同，因此即使 `_get_effective_platform()` 完全忽略查询参数，该用例照样通过。修法：改为请求 `?platform=tt` 并断言 `"_hgpu_gg" not in names`，使其真正验证「按 `?platform=` 切换」。
>
> **(3) 新增一条非切换角色的隔离用例。** 本接口是本计划中唯一**只挂 `@jwt_required()`、不挂平台装饰器**的新路由（`/api/tt/users` 挂 `@tt_required`、`/api/fb/users` 挂 `@fb_required`，见 `py/routes/tt_routes.py:812`、`py/routes/fb_routes.py:1508`）。因此「非切换角色传 `?platform=` 被忽略」这一访问控制属性只能靠本用例守护。
>
> 上述三条均为**加强**（不改变任何接口要求、不触碰生产代码），不削弱 Step 2 的「先红后绿」要求。

**Files:**
- Modify: `py/main.py`（在 `_get_effective_platform` 定义之后，约 `py/main.py:5782`，新增路由）
- Test: `py/tests/test_huguan_role.py`（追加）

**Interfaces:**
- Consumes: Task 1 的 `_get_effective_platform()`
- Produces: `GET /api/platform/users` → `200 {"success": true, "users": [{"id": int, "username": str, "display_name": str, "platform": str}]}`，口径为 `(platform = <有效平台> OR role = 'developer') AND role != 'hidden'`，按 `display_name, username` 排序。前端所有「全部用户」筛选下拉的数据源。

- [ ] **Step 1: 写失败测试**

```python
class TestPlatformUsersEndpoint:
    def test_huguan_sees_only_current_platform(self, client):
        """户管切到 TT 时只应看到 TT + developer，不该看到 GG 行。

        注意这里用 `?platform=tt` 而**不是**调用者自身的 gg —— 否则即使
        `_get_effective_platform()` 完全忽略查询参数，本用例也会通过。
        """
        hg, _ = _huguan(client, "_hgpu_hg")  # users.platform == 'gg'
        db = database.get_db()
        db.execute("INSERT INTO users(username, password, role, platform) VALUES('_hgpu_gg','x','user','gg')")
        db.execute("INSERT INTO users(username, password, role, platform) VALUES('_hgpu_tt','x','user','tt')")
        db.commit()
        db.close()
        resp = client.get("/api/platform/users?platform=tt", headers=hg)
        assert resp.status_code == 200
        names = {u["username"] for u in resp.get_json()["users"]}
        assert "_hgpu_tt" in names
        assert "_hgpu_gg" not in names

    def test_includes_developer_excludes_hidden(self, client):
        """developer 行必须经 `OR role = 'developer'` 命中，hidden 行必须被排除。

        `_hgpu_dev` 故意插成 platform='tt'：调用者只查 platform='gg'，因此该行
        **只能**经 developer 分支出现。若把它插成 'gg'，它会被 `platform = ?`
        命中，删掉 `OR role = 'developer'` 断言也不会红 —— 那就成了空断言。
        """
        hg, _ = _huguan(client, "_hgpu_hg2")
        db = database.get_db()
        db.execute("INSERT INTO users(username, password, role, platform) VALUES('_hgpu_dev','x','developer','tt')")
        db.execute("INSERT INTO users(username, password, role, platform) VALUES('_hgpu_hid','x','hidden','gg')")
        db.commit()
        db.close()
        resp = client.get("/api/platform/users?platform=gg", headers=hg)
        assert resp.status_code == 200
        names = {u["username"] for u in resp.get_json()["users"]}
        assert "_hgpu_dev" in names
        assert "_hgpu_hid" not in names

    def test_non_switch_role_cannot_pick_platform(self, client):
        """非切换角色传 ?platform= 必须被忽略，只能拿到自己平台的数据。

        本接口只挂 @jwt_required()，不像 /api/tt/users、/api/fb/users 那样挂平台
        装饰器，因此这条隔离属性只能靠本用例守护。
        """
        u, _ = _create_user(client, "_hgpu_plain", role="user", platform="gg")
        db = database.get_db()
        db.execute("INSERT INTO users(username, password, role, platform) VALUES('_hgpu_leak','x','user','tt')")
        db.commit()
        db.close()
        resp = client.get("/api/platform/users?platform=tt", headers=u)
        assert resp.status_code == 200
        names = {x["username"] for x in resp.get_json()["users"]}
        assert "_hgpu_leak" not in names
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd py && python -m pytest tests/test_huguan_role.py -v -k PlatformUsers`
Expected: 三条 FAIL，`resp.status_code == 404`（路由不存在）。

- [ ] **Step 3: 新增路由**

在 `py/main.py` 的 `_get_effective_platform` 函数定义之后（`py/main.py:5782` 之后、`@app.route("/api/statuses/list"...)` 之前）插入：

```python
@app.route("/api/platform/users", methods=["GET"])
@jwt_required()
def platform_users():
    """当前有效平台下的用户列表，供账户面板的「全部用户」筛选下拉使用。

    口径与既有的 /api/tt/users、/api/fb/users 完全一致：
        (platform = <有效平台> OR role = 'developer') AND role != 'hidden'
    """
    platform = _get_effective_platform()
    db = _yt_db()
    rows = db.execute(
        "SELECT id, username, display_name, platform FROM users "
        "WHERE (platform = ? OR role = 'developer') AND role != 'hidden' "
        "ORDER BY display_name, username",
        (platform,)
    ).fetchall()
    db.close()
    return jsonify({"success": True, "users": [dict(r) for r in rows]})
```

- [ ] **Step 4: 运行测试确认通过**

Run: `cd py && python -m pytest tests/test_huguan_role.py -v -k PlatformUsers`
Expected: 3 passed

- [ ] **Step 5: 提交**

```bash
git add py/main.py py/tests/test_huguan_role.py
git commit -m "feat: 新增通用用户列表接口 /api/platform/users"
```

---

### Task 5: GG 账户列表跨用户可见 + 按用户筛选

> **执行勘误（2026-09-22，派发前预检）**：Step 3 正确，**Step 4 有两处会破坏纯增量原则、Step 5 有一处逻辑错误**，均已在下方改正。权威参照是 `py/routes/tt_accounts_routes.py:193-281`（TT 的同类实现）——请通读该函数后再动手，本任务是「按它的模式复刻」，不是自由发挥。
>
> **(1) 参照实现的真实形状。** TT 的 `list_accounts` 只在 `a.owner_id` 上做归属收放：
> ```python
>     if role in ('developer', 'admin'):
>         if owner_id:
>             where.append("a.owner_id = ?"); params.append(owner_id)
>     else:
>         where.append("a.owner_id = ?"); params.append(uid)
> ```
> 它**从不**对 agent / status 筛选加归属限制（TT 用的是 `agent_id` / `status_id` 直等，没有名称子查询）。本步骤把 GG 的归属条件改成同一形状（`CROSS_USER_ROLES` 取代 `('developer','admin')`），`sc_where` 同法 —— Step 3 已正确。
>
> **(2) Step 4 的 `owner_filter or user_id` 是错的。** 对**不带 `owner_id` 的户管**，`owner_filter` 为 `""`，`"" or user_id` 求值为**户管自己的 id**，于是 `AND ag.owner_id = <户管自己>` 会把别人账户上的代理全部过滤掉 —— 与本任务「跨用户可见」的目的直接矛盾（且因新增用例都没设 agent，测试不会发现）。正确形状是**三态**：非跨用户角色 ⟹ 原样 `user_id`（逐字节不变）；跨用户 + 有 `owner_filter` ⟹ 用 `owner_filter`；跨用户 + 无筛选 ⟹ **不加归属条件**（与参照实现一致）。
>
> **(3) Step 4 想无条件删除 status 子查询的 `AND owner_id=?`，会改动现有角色的行为。** 简报称「`account_statuses` 的归属列可能不是 `owner_id` 而是按 platform 隔离」—— 该说法**不成立**：`py/database.py:505-511` 的 `account_statuses` 表确有 `owner_id INTEGER REFERENCES users(id)` 且 `UNIQUE(name, owner_id)`，是**按 owner 隔离**的。因此无条件删除会让 `user` / `viewer` 按状态名筛选时匹配到**其他 owner** 的同名状态行，属修改现有角色行为。必须与 (2) 同法做三态处理。
>
> **(4) Step 5 的 `scope` 表达式本身正确**（`(owner_filter or "all") if cross_user else str(user_id)`；条件表达式优先级低于 `or`），缓存键加维度是必要的 —— `_app_cache` 是进程级全局缓存，不区分维度会串数据。**但 `mcc_options` / `agents` / `timezone_options` 这三个「下拉选项」查询保持简报的 `owner_filter or user_id` 不变**：对非跨用户角色它恒等于 `user_id`（与今天逐字节一致），对带筛选的户管收窄到该 owner。**已知局限（不在本任务修，记录备查）**：不带 `owner_id` 的户管，其三个下拉选项仍只覆盖自己名下的数据（对户管通常为空），即「能看全部账户但下拉里选不到别人的代理/时区/MCC」。这是下拉数据源的口径问题，需与前端 Task 11-13 的 owner 选择器一起定，本任务不擅自扩权、不改这三个查询的既有形状。
>
> **(5) 本路由结尾 `py/main.py:3729` 的 `db.close()` 是既有代码**（`db` 来自请求级共享连接 `_yt_db()`）。本任务**不要动它** —— 修它属于另一件事，不在本需求范围。

**Files:**
- Modify: `py/main.py:3623-3729`（`accounts_list`）
- Test: `py/tests/test_huguan_role.py`（追加）

**Interfaces:**
- Consumes: Task 1 的 `CROSS_USER_ROLES`
- Produces: `GET /api/accounts/list?owner_id=<int>` — 跨用户角色不传 `owner_id` 时返回全部用户的账户；传了则只看该用户；非跨用户角色行为完全不变（强制只看自己）。响应结构不变，另新增 `owner_id` 已知的筛选下拉缓存维度（缓存键加 `:{owner_id or 'all'}` 后缀）。

- [ ] **Step 1: 写失败测试**

```python
def _mk_account(db, owner_id, account_id, name="测试账户"):
    db.execute("INSERT INTO accounts(name, account_id, owner_id) VALUES(?,?,?)",
               (name, account_id, owner_id))
    db.commit()


class TestGgAccountListCrossUser:
    def _setup(self, client):
        hg, hg_id = _huguan(client, "_ggac_hg")
        _, u1 = _create_user(client, "_ggac_u1", role="user")
        _, u2 = _create_user(client, "_ggac_u2", role="user")
        db = database.get_db()
        _mk_account(db, u1, "GG-AC-1", "U1账户")
        _mk_account(db, u2, "GG-AC-2", "U2账户")
        db.close()
        return hg, hg_id, u1, u2

    def test_regular_user_sees_only_own(self, client):
        _, _, u1, _ = self._setup(client)
        hdr, _ = _create_user(client, "_ggac_u1b", role="user")
        resp = client.get("/api/accounts/list?size=50", headers=hdr)
        assert [a["account_id"] for a in resp.get_json()["accounts"]] == []

    def test_huguan_sees_all_users(self, client):
        hg, _, _, _ = self._setup(client)
        resp = client.get("/api/accounts/list?size=50", headers=hg)
        ids = {a["account_id"] for a in resp.get_json()["accounts"]}
        assert ids == {"GG-AC-1", "GG-AC-2"}

    def test_huguan_filters_by_owner_id(self, client):
        hg, _, u1, _ = self._setup(client)
        resp = client.get(f"/api/accounts/list?size=50&owner_id={u1}", headers=hg)
        ids = {a["account_id"] for a in resp.get_json()["accounts"]}
        assert ids == {"GG-AC-1"}

    def test_status_counts_follow_owner_filter(self, client):
        """状态计数必须与 owner_id 筛选同步，否则出现「列表1条、计数3条」。"""
        hg, _, u1, _ = self._setup(client)
        resp = client.get(f"/api/accounts/list?size=50&owner_id={u1}", headers=hg)
        assert resp.get_json()["status_counts"].get("存活", 0) == 1

    def test_regular_user_ignores_owner_id(self, client):
        """回归：普通用户传 owner_id 不能越权看到别人的账户。"""
        _, _, u1, _ = self._setup(client)
        hdr, _ = _create_user(client, "_ggac_u3", role="user")
        db = database.get_db()
        _mk_account(db, _create_user(client, "_ggac_u3b", role="user")[1], "GG-AC-3")
        db.close()
        resp = client.get(f"/api/accounts/list?size=50&owner_id={u1}", headers=hdr)
        assert [a["account_id"] for a in resp.get_json()["accounts"]] == []

    def test_huguan_agent_filter_not_scoped_to_self(self, client):
        """户管不带 owner_id 时按代理名筛选，必须匹配到别人账户上的代理。

        回归点：若 agent / status 四处子查询写成 `owner_filter or user_id`，无筛选时
        `"" or user_id` 退化为**户管自己的 id**，会把别人账户上的代理整片滤掉 ——
        与「跨用户可见」的目的直接矛盾。上面 5 条用例都没有设 agent，抓不到这个 bug，
        本用例即为此设的守卫。
        """
        hg, _, u1, _ = self._setup(client)
        db = database.get_db()
        db.execute("INSERT INTO agents(name, owner_id, platform) VALUES('代理甲', ?, 'gg')", (u1,))
        ag_id = db.execute("SELECT id FROM agents WHERE name='代理甲'").fetchone()["id"]
        db.execute("UPDATE accounts SET agent_id=? WHERE account_id='GG-AC-1'", (ag_id,))
        db.commit()
        db.close()
        resp = client.get("/api/accounts/list?size=50&agent=代理甲", headers=hg)
        ids = {a["account_id"] for a in resp.get_json()["accounts"]}
        assert ids == {"GG-AC-1"}

    def test_regular_user_agent_filter_still_scoped_to_self(self, client):
        """回归：普通用户按代理名筛选仍然是「只看自己的账户」，不得因本次改动放宽。"""
        _, _, u1, _ = self._setup(client)
        db = database.get_db()
        db.execute("INSERT INTO agents(name, owner_id, platform) VALUES('代理乙', ?, 'gg')", (u1,))
        ag_id = db.execute("SELECT id FROM agents WHERE name='代理乙'").fetchone()["id"]
        db.execute("UPDATE accounts SET agent_id=? WHERE account_id='GG-AC-1'", (ag_id,))
        db.commit()
        db.close()
        hdr, _ = _create_user(client, "_ggac_u4", role="user")
        resp = client.get("/api/accounts/list?size=50&agent=代理乙", headers=hdr)
        assert [a["account_id"] for a in resp.get_json()["accounts"]] == []
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd py && python -m pytest tests/test_huguan_role.py -v -k GgAccountListCrossUser`
Expected: `test_huguan_sees_all_users`、`test_huguan_filters_by_owner_id`、`test_status_counts_follow_owner_filter`、`test_huguan_agent_filter_not_scoped_to_self` FAIL；三条回归（`test_regular_user_sees_only_own`、`test_regular_user_ignores_owner_id`、`test_regular_user_agent_filter_still_scoped_to_self`）PASS。

- [ ] **Step 3: 改写 `accounts_list` 的归属条件**

`py/main.py:3626`（`user_id = int(get_jwt_identity())` 之后）插入：

```python
    actor = auth.get_user_by_id(user_id)
    actor_role = (actor or {}).get("role", "user")
    cross_user = actor_role in CROSS_USER_ROLES
    owner_filter = request.args.get("owner_id", "").strip()
    if not cross_user:
        owner_filter = ""
```

把 `py/main.py:3635`：

```python
    where = ["a.owner_id = ?", "a.deleted_at IS NULL"]; params = [user_id]
```

改为：

```python
    where = ["a.deleted_at IS NULL"]; params = []
    if cross_user:
        if owner_filter:
            where.append("a.owner_id = ?"); params.append(owner_filter)
    else:
        where.append("a.owner_id = ?"); params.append(user_id)
```

把 `py/main.py:3682`：

```python
    sc_where = ["a.owner_id = ?", "a.deleted_at IS NULL"]; sc_params = [user_id]
```

改为：

```python
    sc_where = ["a.deleted_at IS NULL"]; sc_params = []
    if cross_user:
        if owner_filter:
            sc_where.append("a.owner_id = ?"); sc_params.append(owner_filter)
    else:
        sc_where.append("a.owner_id = ?"); sc_params.append(user_id)
```

- [ ] **Step 4: 让 agent / status 两个筛选条件的归属收放与列表一致**

`agent` / `status` 的筛选条件在 `py/main.py:3642-3647`（主查询）与 `:3689-3691`（`sc_where` 状态计数）共 4 个 SQL 片段，用的是**名称子查询 + `owner_id = user_id`**。这 4 处必须与 Step 3 的归属收放保持**同一三态语义**，否则会出现「列表看全部、筛选只搜自己」。

先在 Step 3 插入的归属块里补一个三态变量（紧跟在 `owner_filter` 之后、`db = _yt_db()` 之前或之后均可，只要在四处使用之前）：

```python
    # 子查询归属收放三态：非跨用户角色恒为自身 id（逐字节等于改动前）；
    # 跨用户 + 有 owner_id 筛选 → 收窄到该 owner；跨用户 + 无筛选 → None 表示不加归属条件
    sub_owner = None if cross_user else user_id
    if cross_user and owner_filter:
        sub_owner = owner_filter
```

然后 4 处一律改为按 `sub_owner` 分支。`py/main.py:3642-3644`（status，主查询）：

```python
    if status:
        if sub_owner is None:
            where.append("a.status_id IN (SELECT id FROM account_statuses WHERE name=?)")
            params += [status]
        else:
            where.append("a.status_id IN (SELECT id FROM account_statuses WHERE name=? AND owner_id=?)")
            params += [status, sub_owner]
```

`py/main.py:3645-3647`（agent，主查询）：

```python
    if agent:
        if sub_owner is None:
            where.append("a.agent_id IN (SELECT id FROM agents WHERE name LIKE ?)")
            params += [f"%{agent}%"]
        else:
            where.append("a.agent_id IN (SELECT id FROM agents WHERE name LIKE ? AND owner_id=?)")
            params += [f"%{agent}%", sub_owner]
```

`py/main.py:3689-3691`（agent，`sc_where`）与 status 在 `sc_where` 中的对应位置同法处理 —— 注意 `sc_where` **本来就没有** status 条件（它的用途正是「不含 status 以便展示各状态数量」），因此 `sc_where` 侧只需改 agent 这一处：

```python
    if agent:
        if sub_owner is None:
            sc_where.append("a.agent_id IN (SELECT id FROM agents WHERE name LIKE ?)")
            sc_params += [f"%{agent}%"]
        else:
            sc_where.append("a.agent_id IN (SELECT id FROM agents WHERE name LIKE ? AND owner_id=?)")
            sc_params += [f"%{agent}%", sub_owner]
```

**等价性核对（必须逐条成立，实现后自查）**：
- 非跨用户角色（`user` / `viewer` / `admin` / `hidden`）：`sub_owner == user_id`，四处 SQL 文本与参数与改动前**逐字节相同** ✅
- 户管带 `owner_id=U`：四处收窄到 `U`，与列表的 `a.owner_id = U` 一致 ✅
- 户管不带 `owner_id`：四处不加归属条件，能看到全部账户对应的代理/状态名 ✅
- 与参照实现 `py/routes/tt_accounts_routes.py:209-226` 的取向一致（TT 也只收放 `a.owner_id`，不对 agent/status 加归属限制）

- [ ] **Step 5: 给四个缓存键加 `owner_id` 维度**

`py/main.py:3703-3727` 的四处缓存键，把 `uid_str` 定义保留，并新增一个维度后缀变量：

```python
    scope = owner_filter or "all" if cross_user else str(user_id)
```

把 `mcc_cache_key = f"accounts:mcc_options:{user_id}"` 改为 `mcc_cache_key = f"accounts:mcc_options:{user_id}:{scope}"`；
`agents_cache_key = f"accounts:agents:{user_id}"` 改为 `f"accounts:agents:{user_id}:{scope}"`；
`tz_cache_key = f"accounts:tz:{user_id}"` 改为 `f"accounts:tz:{user_id}:{scope}"`。

`mcc_options` 与 `timezone_options` 的查询本身也要跟随归属筛选：`mcc_options` 的 `WHERE (owner_id=? OR shared_...)` 在 `owner_filter` 非空时改为 `WHERE owner_id = ?`（参数 `[owner_filter]`）；`timezone_options` 的 `WHERE timezone!='' AND owner_id=?` 参数由 `(user_id,)` 改为 `(owner_filter or user_id,)`。

- [ ] **Step 6: 运行测试确认通过**

Run: `cd py && python -m pytest tests/test_huguan_role.py -v -k GgAccountListCrossUser`
Expected: 7 passed

- [ ] **Step 7: 跑全量后端测试**

Run: `cd py && python -m pytest tests/ -v`
Expected: 全部 passed

- [ ] **Step 8: 提交**

```bash
git add py/main.py py/tests/test_huguan_role.py
git commit -m "feat: GG 账户列表支持跨用户可见与按用户筛选"
```

---

### Task 6: GG MCC 列表跨用户可见 + 按用户筛选

> **执行勘误（2026-09-22，派发前预检）**：
>
> **(1) 行号一律按内容定位，勿信本节的数字。** `mcc_list` 实际在 `py/main.py:5311-5387`（非 5265-5410），
> `perm_where` / `perm_params` 在 `:5319-5321`（非 5275-5277），下游 4 处使用在 `:5328-5329`、`:5345`、
> `:5362-5363`、`:5370-5371`。
>
> **(2) Step 3 的替换块本身正确，且已核实 `"1=1"` 在 4 个使用点都拼得出合法 SQL**：
> `WHERE 1=1 AND (m.name LIKE ? ...)`、`WHERE 1=1`、`WHERE m.id IN (...) AND 1=1`、
> `FROM mcc m WHERE 1=1 ORDER BY ... LIMIT ? OFFSET ?` 全部合法；`uid_str` 在替换块中保留，下游无其它引用。
>
> **(3) Step 1 的 `test_regular_user_still_scoped` 确实咬得住 `if not cross_user: owner_filter = ""`，本任务不需要另加守卫用例。**
> 理由：本函数的构造顺序是 `if owner_filter: ... elif cross_user: ... else: ...`，若删掉那行，
> 非跨用户角色传 `owner_id` 会落进**第一个分支** `perm_where = "m.owner_id = ?"` 从而看到别人的 MCC，断言变红。
> （Task 5 的 `accounts_list` 结构不同——它的归属条件在 `where` 列表里由 `else` 兜底，所以那里必须另加用例。）
>
> **(4) 已知局限（不在本任务修，记录备查）**：`/api/mcc/options`（`py/main.py:5390`，另一条路由）不改，
> 因此不带 `owner_id` 的户管在 MCC 下拉里仍只看到自己可访问的 MCC。与 Task 5 勘误 (4) 同性质，
> 一并留给 Task 16 的前端 owner 选择器定口径。**本任务不得擅自扩权到该路由。**
>
> **(5) 本任务只让户管「看得到」别人的 MCC，改不动。** 三个写接口（`mcc_update` / `mcc_delete` /
> `mcc_batch_delete`）的硬编码归属校验与前端 `MccPanel.vue:33` 的 `is_owner` 按钮门控由 **Task 18** 处理。

**Files:**
- Modify: `py/main.py:5311-5387`（`mcc_list`）
- Test: `py/tests/test_huguan_role.py`（追加）

**Interfaces:**
- Consumes: Task 1 的 `CROSS_USER_ROLES`
- Produces: `GET /api/mcc/list?owner_id=<int>` — 跨用户角色不传时看全部 MCC，传了只看该用户的；非跨用户角色完全沿用现有 `owner_id = 自己 OR shared_user_ids 含自己` 权限模型。

- [ ] **Step 1: 写失败测试**

```python
def _mk_mcc(db, owner_id, mcc_code, name="测试MCC"):
    db.execute("INSERT INTO mcc(name, mcc_id, owner_id) VALUES(?,?,?)", (name, mcc_code, owner_id))
    db.commit()


class TestGgMccListCrossUser:
    def _setup(self, client):
        hg, hg_id = _huguan(client, "_ggmcc_hg")
        _, u1 = _create_user(client, "_ggmcc_u1", role="user")
        _, u2 = _create_user(client, "_ggmcc_u2", role="user")
        db = database.get_db()
        _mk_mcc(db, u1, "MCC-1", "U1的MCC")
        _mk_mcc(db, u2, "MCC-2", "U2的MCC")
        db.close()
        return hg, hg_id, u1, u2

    def test_huguan_sees_all_mcc(self, client):
        hg, _, _, _ = self._setup(client)
        resp = client.get("/api/mcc/list?size=50", headers=hg)
        assert resp.status_code == 200
        codes = {m["mcc_id"] for m in resp.get_json()["mcc_list"]}
        assert codes == {"MCC-1", "MCC-2"}

    def test_huguan_filters_by_owner(self, client):
        hg, _, u1, _ = self._setup(client)
        resp = client.get(f"/api/mcc/list?size=50&owner_id={u1}", headers=hg)
        codes = {m["mcc_id"] for m in resp.get_json()["mcc_list"]}
        assert codes == {"MCC-1"}

    def test_regular_user_still_scoped(self, client):
        """回归：普通用户看不到别人的 MCC，且 owner_id 参数无效。"""
        _, _, u1, _ = self._setup(client)
        hdr, _ = _create_user(client, "_ggmcc_u3", role="user")
        resp = client.get(f"/api/mcc/list?size=50&owner_id={u1}", headers=hdr)
        assert resp.get_json()["mcc_list"] == []
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd py && python -m pytest tests/test_huguan_role.py -v -k GgMccList`
Expected: 两条户管用例 FAIL，回归用例 PASS。

- [ ] **Step 3: 改写 `perm_where` 的构造**

`py/main.py:5275-5277` 整段替换为：

```python
    uid_str = str(user_id)
    actor = auth.get_user_by_id(user_id)
    actor_role = (actor or {}).get("role", "user")
    cross_user = actor_role in CROSS_USER_ROLES
    owner_filter = request.args.get("owner_id", "").strip()
    if not cross_user:
        owner_filter = ""
    if owner_filter:
        perm_where = "m.owner_id = ?"
        perm_params = [owner_filter]
    elif cross_user:
        perm_where = "1=1"
        perm_params = []
    else:
        perm_where = "(m.owner_id = ? OR m.shared_user_ids = ? OR m.shared_user_ids LIKE ? OR m.shared_user_ids LIKE ? OR m.shared_user_ids LIKE ?)"
        perm_params = [user_id, f"[{uid_str}]", f"[{uid_str},%", f"%, {uid_str},%", f"%, {uid_str}]"]
```

下游 4 处对 `perm_where` / `perm_params` 的使用（`py/main.py:5284-5285`、`:5301`、`:5318`、`:5326-5327`）**全部不用改**——这正是集中构造这两个变量的意义。

- [ ] **Step 4: 运行测试确认通过**

Run: `cd py && python -m pytest tests/test_huguan_role.py -v -k GgMccList`
Expected: 3 passed

- [ ] **Step 5: 跑全量后端测试**

Run: `cd py && python -m pytest tests/ -v`
Expected: 全部 passed

- [ ] **Step 6: 提交**

```bash
git add py/main.py py/tests/test_huguan_role.py
git commit -m "feat: GG MCC 列表支持跨用户可见与按用户筛选"
```

---

### Task 7: GG 账户创建与归属转移支持代建

> **执行勘误（2026-09-22，派发前预检）**：
>
> **(1) 行号一律按内容定位，勿信本节的数字。** `accounts_create` 实际在 `py/main.py:3871-3979`（非 3827-3892），
> `accounts_reassign` 实际在 `py/main.py:4230-4283`（非 4186-4240）。
>
> **(2) ⚠️ Step 3 的插入位置照字面执行会抛 `UnboundLocalError`。** 本节写「在 `user_id = int(get_jwt_identity())`
> 之后插入」，但插入块第一句就用了 `data`，而 `data = request.get_json(silent=True) or {}` 在**它下一行**（`:3875`）。
> **必须插在 `data = ...` 之后。** Step 4 写的位置（`data = ...` 之后）是对的 —— 两处不对称，注意区分。
>
> **(3) 逐处替换清单（按内容找，共 5 处，brief 的行号均已漂移）：**
> - `accounts_create` 的 agent 查找：`"SELECT id FROM agents WHERE name=? AND owner_id=?", (agent_name, user_id)`
> - `accounts_create` 的 agent 兜底插入：`"INSERT INTO agents(name, owner_id) VALUES(?,?)", (agent_name, user_id)`
> - `accounts_create` 的 status 查找：`"SELECT id FROM account_statuses WHERE name=? AND owner_id=?", (status_name, user_id)`
> - `accounts_create` 的 status 兜底插入：`"INSERT INTO account_statuses(name, owner_id) VALUES(?,?)", (status_name, user_id)`
> - `accounts_create` 的账户 INSERT 参数末位：`now, now, user_id))`
>
> **(4) `changed_by` 保持操作者，不要跟着改。** `accounts_create` 里 `account_mcc_history` 的
> `changed_by` 传 `user_id`（`:3932`），`accounts_reassign` 里 `_record_mcc_change(db, aid, mcc_val, user_id, "reassign")`
> 的第四参数同理（`:4272`）。这两处语义是「**谁做的这次改动**」，即户管本人，**不是** `target_owner`。
>
> **(5) `accounts_reassign` 的返回文案对代转场景是错的。** 原句
> `f"账户「{existing['name']}」已从 {old_owner} 转移至当前用户"` 在「转给别人」时说反了。改为双分支，
> **保证既有角色（`target_owner` 恒等于 `user_id`）拿到逐字节相同的那一句**：
> ```python
>         if target_owner == user_id:
>             msg = f"账户「{existing['name']}」已从 {old_owner} 转移至当前用户"
>         else:
>             _t = db.execute("SELECT display_name, username FROM users WHERE id=?", (target_owner,)).fetchone()
>             _label = (_t["display_name"] or _t["username"]) if _t else str(target_owner)
>             msg = f"账户「{existing['name']}」已从 {old_owner} 转移至 {_label}"
> ```
> 并把 `return jsonify({"success": True, "message": ...})` 的 message 换成 `msg`。
>
> **(6) 新增一条 reassign 的回归用例（Step 1 已补）**：`test_regular_user_owner_id_ignored_on_reassign`。
> 只测 create 是不够的 —— reassign 的 `owner_id` 分支是**独立的第二处**，漏改一样会全绿。
>
> **(7) 既有缺口（不在本任务修，记录备查）**：`accounts_reassign` **没有源账户归属校验** ——
> 它只检查「目标是不是已经是自己的」，不检查「调用者是不是当前 owner」。因此任意登录用户都能把
> **任意**账户转给自己。这是既有缺陷（与设计文档 §2.5 记录的 `accounts_update` / FB 侧同类缺口同性质），
> 本任务不修，仅记录。副效应是「户管能转移别人的账户」这条需求本就已被该缺口满足。
>
> **(8) Step 1 的 `test_huguan_reassigns_to_target_user` 里 `aid = 0` 一行是冗余占位**，实现时去掉。

**Files:**
- Modify: `py/main.py:3871-3979`（`accounts_create`）
- Modify: `py/main.py:4230-4283`（`accounts_reassign`）
- Test: `py/tests/test_huguan_role.py`（追加）

**Interfaces:**
- Consumes: Task 1 的 `CROSS_USER_ROLES`
- Produces:
  - `POST /api/accounts/create` 接受可选 `owner_id`（仅跨用户角色生效）；未传或非跨用户角色时归属调用者自己
  - `PUT /api/accounts/<aid>/reassign` 接受可选 `owner_id`（仅跨用户角色生效）；未传时行为与现状一致（转给自己）
  - 代建时 `agents` / `account_statuses` 的兜底插入使用**目标 owner**，避免代理名挂到户管名下

- [ ] **Step 1: 写失败测试**

```python
class TestGgAccountOwnership:
    def test_huguan_creates_for_other_user(self, client):
        hg, hg_id = _huguan(client, "_ggown_hg")
        _, u1 = _create_user(client, "_ggown_u1", role="user")
        resp = client.post("/api/accounts/create", json={
            "name": "代建账户", "account_id": "GG-OWN-1",
            "owner_id": u1, "agent": "代建代理",
        }, headers=hg)
        assert resp.status_code == 200
        db = database.get_db()
        acc = db.execute("SELECT owner_id FROM accounts WHERE account_id='GG-OWN-1'").fetchone()
        ag = db.execute("SELECT owner_id FROM agents WHERE name='代建代理'").fetchone()
        db.close()
        assert acc["owner_id"] == u1
        assert ag["owner_id"] == u1

    def test_huguan_creates_without_owner_defaults_to_self(self, client):
        hg, hg_id = _huguan(client, "_ggown_hg2")
        resp = client.post("/api/accounts/create", json={
            "name": "自建账户", "account_id": "GG-OWN-2"}, headers=hg)
        assert resp.status_code == 200
        db = database.get_db()
        acc = db.execute("SELECT owner_id FROM accounts WHERE account_id='GG-OWN-2'").fetchone()
        db.close()
        assert acc["owner_id"] == hg_id

    def test_regular_user_owner_id_ignored_on_create(self, client):
        """回归：普通用户传 owner_id 不能把账户建到别人名下。"""
        _, u1 = _create_user(client, "_ggown_u2", role="user")
        hdr, me = _create_user(client, "_ggown_u3", role="user")
        resp = client.post("/api/accounts/create", json={
            "name": "越权账户", "account_id": "GG-OWN-3", "owner_id": u1}, headers=hdr)
        assert resp.status_code == 200
        db = database.get_db()
        acc = db.execute("SELECT owner_id FROM accounts WHERE account_id='GG-OWN-3'").fetchone()
        db.close()
        assert acc["owner_id"] == me

    def test_huguan_reassigns_to_target_user(self, client):
        hg, hg_id = _huguan(client, "_ggown_hg3")
        _, u1 = _create_user(client, "_ggown_u4", role="user")
        db = database.get_db()
        _mk_account(db, hg_id, "GG-OWN-4", "待转移")
        aid = db.execute("SELECT id FROM accounts WHERE account_id='GG-OWN-4'").fetchone()["id"]
        db.close()
        resp = client.put(f"/api/accounts/{aid}/reassign", json={"owner_id": u1}, headers=hg)
        assert resp.status_code == 200
        db = database.get_db()
        acc = db.execute("SELECT owner_id FROM accounts WHERE id=?", (aid,)).fetchone()
        db.close()
        assert acc["owner_id"] == u1

    def test_regular_user_owner_id_ignored_on_reassign(self, client):
        """回归：普通用户传 owner_id 不能把账户转给别人。

        reassign 的 `owner_id` 分支与 create 的**互相独立**（两处 `target_owner` 计算），
        只测 create 会让漏改这里的情况全绿。本用例即为此设的守卫：账户原属 u1，
        普通用户 caller 传 `owner_id=u1` 时应转给 caller 自己，而不是留在 u1 名下。
        """
        _, u1 = _create_user(client, "_ggown_u5", role="user")
        hdr, me = _create_user(client, "_ggown_u6", role="user")
        db = database.get_db()
        _mk_account(db, u1, "GG-OWN-5", "u1的账户")
        aid = db.execute("SELECT id FROM accounts WHERE account_id='GG-OWN-5'").fetchone()["id"]
        db.close()
        resp = client.put(f"/api/accounts/{aid}/reassign", json={"owner_id": u1}, headers=hdr)
        assert resp.status_code == 200
        db = database.get_db()
        owner = db.execute("SELECT owner_id FROM accounts WHERE id=?", (aid,)).fetchone()["owner_id"]
        db.close()
        assert owner == me
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd py && python -m pytest tests/test_huguan_role.py -v -k GgAccountOwnership`
Expected: `test_huguan_creates_for_other_user` FAIL（owner 是户管自己、代理挂在户管名下）；`test_huguan_reassigns_to_target_user` FAIL（`owner_id` 仍是户管，或返回 409「该账户已属于当前用户」）；三条回归（`test_huguan_creates_without_owner_defaults_to_self`、`test_regular_user_owner_id_ignored_on_create`、`test_regular_user_owner_id_ignored_on_reassign`）PASS。

- [ ] **Step 3: 改写 `accounts_create` 的目标归属**

在 `py/main.py:3830`（`user_id = int(get_jwt_identity())` 之后）插入：

```python
    actor = auth.get_user_by_id(user_id)
    actor_role = (actor or {}).get("role", "user")
    target_owner = user_id
    if actor_role in CROSS_USER_ROLES:
        raw_owner = (data.get("owner_id") or "")
        if str(raw_owner).strip().isdigit():
            target_owner = int(str(raw_owner).strip())
```

把 `py/main.py:3846`、`:3851` 两处（agent 的查找与插入）的 `user_id` 改为 `target_owner`：

```python
                    "SELECT id FROM agents WHERE name=? AND owner_id=?", (agent_name, target_owner)
```
```python
                    db.execute("INSERT INTO agents(name, owner_id) VALUES(?,?)", (agent_name, target_owner))
```

把 `py/main.py:3859`、`:3864` 两处（status 的查找与插入）的 `user_id` 改为 `target_owner`。

把 `py/main.py:3877` 的 INSERT 参数末尾 `now, now, user_id))` 改为 `now, now, target_owner))`。

- [ ] **Step 4: 改写 `accounts_reassign` 的目标归属**

在 `py/main.py:4191`（`data = request.get_json(silent=True) or {}` 之后）插入：

```python
    actor = auth.get_user_by_id(user_id)
    actor_role = (actor or {}).get("role", "user")
    target_owner = user_id
    if actor_role in CROSS_USER_ROLES:
        raw_owner = (data.get("owner_id") or "")
        if str(raw_owner).strip().isdigit():
            target_owner = int(str(raw_owner).strip())
```

把 `py/main.py:4203`：

```python
        if int(existing["owner_id"] or 0) == user_id:
```

改为：

```python
        if int(existing["owner_id"] or 0) == target_owner:
```

把 `py/main.py:4210-4213` 的 `(user_id, aid)` 改为 `(target_owner, aid)`。

同时把该接口的 docstring 从 `"""将已有账户归属权转移给当前用户，同时可选更新其他字段"""` 改为 `"""将已有账户归属权转移给指定用户（跨用户角色）或当前用户，同时可选更新其他字段"""`。

- [ ] **Step 5: 运行测试确认通过**

Run: `cd py && python -m pytest tests/test_huguan_role.py -v -k GgAccountOwnership`
Expected: 5 passed

- [ ] **Step 6: 跑全量后端测试**

Run: `cd py && python -m pytest tests/ -v`
Expected: 全部 passed

- [ ] **Step 7: 提交**

```bash
git add py/main.py py/tests/test_huguan_role.py
git commit -m "feat: GG 账户代建与归属转移支持指定目标用户"
```

---

### Task 8: TT 路由角色常量替换（账户域与 BC）

**Files:**
- Modify: `py/routes/tt_accounts_routes.py`（22 处角色元组）
- Modify: `py/routes/tt_routes.py`（账户域与 BC 相关的角色元组）
- Test: `py/tests/test_huguan_role.py`（追加）

**Interfaces:**
- Consumes: Task 1 的 `CROSS_USER_ROLES`
- Produces: 户管对任意用户的 TT 账户拥有编辑权；对 BC 拥有编辑权。**产品域不动**。

**范围界定：**
- **要改**：`tt_accounts_routes.py` 全部 22 处（该文件全是账户域）；`tt_routes.py:1145`（`_check_bc_owner`）；`tt_routes.py:125`、`:158`、`:569`（BC / 账户域）。
- **不改**：`tt_routes.py:1154`（`_check_product_owner`）、`:1169`（`_check_product_view`）、`:892`（`sheet_id` 全局配置写入，属子项目 B）、`:818`（`/api/tt/users` 的查询口径，保持原样）、`:30`（`_get_role` 辅助，无判断语义）。

- [ ] **Step 1: 写失败测试**

```python
def _mk_tt_account(db, owner_id, adv_id, name="TT账户"):
    db.execute("INSERT INTO tt_accounts(name, advertiser_id, owner_id) VALUES(?,?,?)",
               (name, adv_id, owner_id))
    db.commit()


class TestTtCrossUser:
    def test_huguan_edits_other_users_tt_account(self, client):
        hg, _ = _huguan(client, "_tt_cs_hg")
        _, u1 = _create_user(client, "_tt_cs_u1", role="user", platform="tt")
        db = database.get_db()
        _mk_tt_account(db, u1, "TT-ADV-1")
        aid = db.execute("SELECT id FROM tt_accounts WHERE advertiser_id='TT-ADV-1'").fetchone()["id"]
        db.close()
        resp = client.put(f"/api/tt/accounts/{aid}", json={"name": "改名后"},
                          headers=hg)
        assert resp.status_code == 200
        db = database.get_db()
        row = db.execute("SELECT name FROM tt_accounts WHERE id=?", (aid,)).fetchone()
        db.close()
        assert row["name"] == "改名后"

    def test_regular_user_cannot_edit_other_users_tt_account(self, client):
        """回归：普通用户编辑他人 TT 账户仍 403。"""
        _, u1 = _create_user(client, "_tt_cs_u2", role="user", platform="tt")
        other, _ = _create_user(client, "_tt_cs_u3", role="user", platform="tt")
        db = database.get_db()
        _mk_tt_account(db, u1, "TT-ADV-2")
        aid = db.execute("SELECT id FROM tt_accounts WHERE advertiser_id='TT-ADV-2'").fetchone()["id"]
        db.close()
        resp = client.put(f"/api/tt/accounts/{aid}", json={"name": "越权改名"}, headers=other)
        assert resp.status_code == 403

    def test_huguan_edits_other_users_bc(self, client):
        hg, _ = _huguan(client, "_tt_bc_hg")
        _, u1 = _create_user(client, "_tt_bc_u1", role="user", platform="tt")
        db = database.get_db()
        db.execute("INSERT INTO tt_bcs(name, bc_id, owner_id) VALUES('BC1','BC-1',?)", (u1,))
        db.commit()
        bid = db.execute("SELECT id FROM tt_bcs WHERE bc_id='BC-1'").fetchone()["id"]
        db.close()
        resp = client.put(f"/api/tt/bcs/{bid}", json={"name": "BC改名"}, headers=hg)
        assert resp.status_code == 200
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd py && python -m pytest tests/test_huguan_role.py -v -k TtCrossUser`
Expected: 两条户管用例 FAIL（403）；回归用例 PASS。

- [ ] **Step 3: 机械替换两个文件中的角色元组**

在 `py/routes/tt_accounts_routes.py` 第 11 行的 `from .helpers import ok, err, get_uid, get_db, parse_body` 改为：

```python
from .helpers import ok, err, get_uid, get_db, parse_body, CROSS_USER_ROLES
```

然后对该文件**全部 22 处**执行替换（行号：209、256、298、436、506、525、543、560、577、611、639、696、732、786、821、841、860、881、920、937、1079、1121、1135 —— 以 `grep -n "developer" py/routes/tt_accounts_routes.py` 现查为准）：

```
role in ('developer', 'admin')      →  role in CROSS_USER_ROLES
role not in ('developer', 'admin')  →  role not in CROSS_USER_ROLES
```

注意 `:821`、`:841`、`:860` 三处比较的是 `row["created_by"]`，也一并按上面替换（户管可操作他人创建的下级数据）。

对 `py/routes/tt_routes.py`：第 11 行的 import 同样追加 `CROSS_USER_ROLES`，然后**只**替换 `:125`、`:158`、`:569`、`:1145` 四处（BC 与账户域）；**`:1154`、`:1169` 保持不变**（产品域）。

替换后用下面两条命令自查替换范围：

```bash
grep -n "developer" py/routes/tt_accounts_routes.py
grep -n "developer" py/routes/tt_routes.py
```

Expected: `tt_accounts_routes.py` 无任何 `developer` 字面量残留；`tt_routes.py` 仅剩 `:818`、`:892`、`:1154`、`:1169` 四处（均为明确不改的站点）。

- [ ] **Step 4: 运行测试确认通过**

Run: `cd py && python -m pytest tests/test_huguan_role.py -v -k TtCrossUser`
Expected: 3 passed

- [ ] **Step 5: 跑全量后端测试**

Run: `cd py && python -m pytest tests/ -v`
Expected: 全部 passed，重点是 `tests/test_tt_accounts.py` 与 `tests/test_tt_routes.py`（合计 100+ 用例）零 FAILED —— 它们覆盖了替换到的大部分站点。

- [ ] **Step 6: 提交**

```bash
git add py/routes/tt_accounts_routes.py py/routes/tt_routes.py py/tests/test_huguan_role.py
git commit -m "refactor: TT 账户与 BC 的角色判断收敛为 CROSS_USER_ROLES"
```

---

### Task 9: FB 列表跨用户可见 + 按用户筛选

**Files:**
- Modify: `py/routes/fb_routes.py:29`（BM 列表）、`:64`（BM 统一列表）、`:264`（账户列表）、`:387`（账户回收站）、`:739`（像素 BM 列表）
- Test: `py/tests/test_huguan_role.py`（追加）

**Interfaces:**
- Consumes: Task 1 的 `CROSS_USER_ROLES`
- Produces: `GET /api/fb/bms/list`、`/api/fb/bms/unified`、`/api/fb/accounts/list`、`/api/fb/accounts/deleted`、`/api/fb/pixel-bms/list` 均接受可选 `owner_id`，跨用户角色不传时看全部。**`py/routes/fb_routes.py:471`（FB 产品列表）不改**。

- [ ] **Step 1: 写失败测试**

```python
def _mk_fb_bm(db, owner_id, bm_code, name="测试BM"):
    db.execute("INSERT INTO fb_bms(name, bm_id, owner_id) VALUES(?,?,?)", (name, bm_code, owner_id))
    db.commit()


def _mk_fb_account(db, owner_id, account_id, name="FB账户"):
    db.execute("INSERT INTO fb_accounts(name, account_id, owner_id) VALUES(?,?,?)",
               (name, account_id, owner_id))
    db.commit()


class TestFbCrossUser:
    def _setup(self, client):
        hg, _ = _huguan(client, "_fb_cs_hg")
        _, u1 = _create_user(client, "_fb_cs_u1", role="user", platform="fb")
        _, u2 = _create_user(client, "_fb_cs_u2", role="user", platform="fb")
        db = database.get_db()
        _mk_fb_bm(db, u1, "BM-1", "U1的BM")
        _mk_fb_bm(db, u2, "BM-2", "U2的BM")
        _mk_fb_account(db, u1, "FB-AC-1")
        _mk_fb_account(db, u2, "FB-AC-2")
        db.close()
        return hg, u1, u2

    def test_huguan_sees_all_bms(self, client):
        hg, _, _ = self._setup(client)
        resp = client.get("/api/fb/bms/list?size=50", headers=hg)
        assert resp.status_code == 200
        assert {b["bm_id"] for b in resp.get_json()["items"]} == {"BM-1", "BM-2"}

    def test_huguan_filters_bms_by_owner(self, client):
        hg, u1, _ = self._setup(client)
        resp = client.get(f"/api/fb/bms/list?size=50&owner_id={u1}", headers=hg)
        assert {b["bm_id"] for b in resp.get_json()["items"]} == {"BM-1"}

    def test_huguan_sees_all_accounts(self, client):
        hg, _, _ = self._setup(client)
        resp = client.get("/api/fb/accounts/list?size=50", headers=hg)
        assert {a["account_id"] for a in resp.get_json()["items"]} == {"FB-AC-1", "FB-AC-2"}

    def test_huguan_filters_accounts_by_owner(self, client):
        hg, _, u2 = self._setup(client)
        resp = client.get(f"/api/fb/accounts/list?size=50&owner_id={u2}", headers=hg)
        assert {a["account_id"] for a in resp.get_json()["items"]} == {"FB-AC-2"}

    def test_regular_fb_user_ignores_owner_id(self, client):
        """回归：普通 FB 用户传 owner_id 不能越权。"""
        _, u1, _ = self._setup(client)
        other, _ = _create_user(client, "_fb_cs_u3", role="user", platform="fb")
        resp = client.get(f"/api/fb/accounts/list?size=50&owner_id={u1}", headers=other)
        assert resp.get_json()["items"] == []
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd py && python -m pytest tests/test_huguan_role.py -v -k FbCrossUser`
Expected: 4 条户管用例 FAIL；回归用例 PASS。

- [ ] **Step 3: 在 `py/routes/fb_routes.py` 顶部引入常量**

第 4 行改为：

```python
from .helpers import ok, err, get_uid, get_db, parse_body, CROSS_USER_ROLES
```

- [ ] **Step 4: 五处列表统一改造**

每个列表函数都是同一个形状（`role = _get_role(db, uid)` 之后跟着一段归属过滤），统一替换为下面这段（把 `<TABLE>` 换成该函数实际用的表别名，`<ALIAS>` 换成该函数实际用的列前缀）：

```python
    role = _get_role(db, uid)
    cross_user = role in CROSS_USER_ROLES
    owner_filter = (request.args.get('owner_id') or '').strip()
    if not cross_user:
        owner_filter = ''
    if cross_user:
        if owner_filter:
            where.append("owner_id = ?")
            params.append(owner_filter)
    else:
        where.append("owner_id = ?")
        params.append(uid)
```

逐处落地：

- `py/routes/fb_routes.py:29`（`/api/fb/bms/list`，用 `where` / `params`，无别名）：

```python
    if role not in ('developer', 'admin'):
        where.append("owner_id = ?")
        params.append(uid)
```
→ 上述统一片段。

- `py/routes/fb_routes.py:64`（`/api/fb/bms/unified`，变量名是 `base_where` / `base_params`）：

```python
    if role not in ('developer', 'admin'):
        base_where.append("owner_id = ?")
        base_params.append(uid)
```
→

```python
    cross_user = role in CROSS_USER_ROLES
    owner_filter = (request.args.get('owner_id') or '').strip()
    if not cross_user:
        owner_filter = ''
    if cross_user:
        if owner_filter:
            base_where.append("owner_id = ?")
            base_params.append(owner_filter)
    else:
        base_where.append("owner_id = ?")
        base_params.append(uid)
```

- `py/routes/fb_routes.py:264`（`/api/fb/accounts/list`，带别名 `a.`）：

```python
    if role not in ('developer', 'admin'):
        where.append("a.owner_id = ?")
        params.append(uid)
```
→ 统一片段，但列名写 `a.owner_id`。

- `py/routes/fb_routes.py:387`（`/api/fb/accounts/deleted`，带别名 `a.`）：同上处理。

- `py/routes/fb_routes.py:739`（`/api/fb/pixel-bms/list`，用 `where` / `params`，无别名）：同上处理。

- [ ] **Step 5: 运行测试确认通过**

Run: `cd py && python -m pytest tests/test_huguan_role.py -v -k FbCrossUser`
Expected: 5 passed

- [ ] **Step 6: 跑全量后端测试**

Run: `cd py && python -m pytest tests/ -v`
Expected: 全部 passed，重点是 `tests/test_fb_platform.py`

- [ ] **Step 7: 提交**

```bash
git add py/routes/fb_routes.py py/tests/test_huguan_role.py
git commit -m "feat: FB BM/账户/像素列表支持跨用户可见与按用户筛选"
```

---

### Task 10: 设置下拉选项权限开放给户管

**Files:**
- Modify: `py/main.py`（9 处 `is_dev = user and user.get("role") in ("developer", "admin")`，行号 5697、5737、5834、5863、5935、5962、6030、6060，以 `grep -n 'is_dev = user' py/main.py` 现查为准）
- Test: `py/tests/test_huguan_role.py`（追加）

**Interfaces:**
- Consumes: Task 1 的 `GLOBAL_OPTION_ROLES`
- Produces: 户管可创建/改名/删除平台级下拉选项（代理名、账户状态、MCC 等级、商务人员）。地区时区接口本来就无权限门槛，无需改动。

- [ ] **Step 1: 写失败测试**

```python
class TestHuguanGlobalOptions:
    def test_huguan_creates_agent(self, client):
        hg, _ = _huguan(client, "_opt_hg")
        resp = client.post("/api/agents/create?platform=gg", json={"name": "户管代理"},
                           headers=hg)
        assert resp.status_code == 200

    def test_huguan_creates_status(self, client):
        hg, _ = _huguan(client, "_opt_hg2")
        resp = client.post("/api/statuses/create?platform=gg", json={"name": "户管状态"},
                           headers=hg)
        assert resp.status_code == 200

    def test_regular_user_cannot_create_agent(self, client):
        """回归：普通用户仍不能创建代理名。"""
        u, _ = _create_user(client, "_opt_user", role="user", platform="gg")
        resp = client.post("/api/agents/create?platform=gg", json={"name": "越权代理"},
                           headers=u)
        assert resp.status_code == 403
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd py && python -m pytest tests/test_huguan_role.py -v -k HuguanGlobalOptions`
Expected: 两条户管用例 FAIL（403）；回归用例 PASS。

- [ ] **Step 3: 机械替换 9 处 `is_dev`**

```bash
grep -n 'is_dev = user' py/main.py
```

对每一处把：

```python
    is_dev = user and user.get("role") in ("developer", "admin")
```

改为：

```python
    is_dev = user and user.get("role") in GLOBAL_OPTION_ROLES
```

替换后自查：

```bash
grep -c 'in ("developer", "admin")' py/main.py
```

Expected: 只剩 Task 3 尚未替换的接口入口判断（若 Task 3 已完成，则应为 0）。

**注意**：`is_dev` 变量名保持不变。它是「平台级选项管理员」语义，改名会扩大 diff；语义由 `GLOBAL_OPTION_ROLES` 承担。若希望更清晰，可在同一函数内加一行注释 `# 平台级下拉选项的编辑权（含户管）`，但**不要**改变量名——该变量在 `:5700`、`:5740`、`:5835`、`:5864`、`:5936`、`:5963`、`:6031`、`:6041`、`:6061` 等 9 处被引用。

- [ ] **Step 4: 运行测试确认通过**

Run: `cd py && python -m pytest tests/test_huguan_role.py -v -k HuguanGlobalOptions`
Expected: 3 passed

- [ ] **Step 5: 跑全量后端测试**

Run: `cd py && python -m pytest tests/ -v`
Expected: 全部 passed

- [ ] **Step 6: 提交**

```bash
git add py/main.py py/tests/test_huguan_role.py
git commit -m "feat: 平台级下拉选项的编辑权开放给户管"
```

---

### Task 11: 前端 auth store / client.js / 路由守卫

**Files:**
- Modify: `frontend/src/stores/auth.js`
- Modify: `frontend/src/api/client.js:13`
- Modify: `frontend/src/router/index.js:17-24`、`:164-179`
- Test: 无自动化测试 → 验证为 `npm run build` + 手工核对清单

**Interfaces:**
- Consumes: 后端 Task 1（跨平台）与 Task 4（`/api/platform/users`）
- Produces（`useAuthStore` 的 getters，供 Task 12–16 使用）：
  - `isHuguan: boolean`
  - `canSwitchPlatform: boolean`
  - `canManageAccounts: boolean`
  - `homePath: string`（当前身份与平台的默认落地页）
  - `roleLabel` 增加 `huguan` → `'户管'`

- [ ] **Step 1: 改造 `frontend/src/stores/auth.js`**

在 `getters` 中 `isViewer` 之后插入：

```js
    isHuguan: (state) => state.user?.role === 'huguan',
    canSwitchPlatform: (state) => ['developer', 'huguan'].includes(state.user?.role),
    canManageAccounts: (state) => ['developer', 'admin', 'huguan'].includes(state.user?.role),
```

把 `effectivePlatform` 改为：

```js
    effectivePlatform: (state) => {
      if (state.canSwitchPlatform) return state.currentPlatform
      return state.user?.platform || 'gg'
    },
    homePath: (state) => {
      const p = state.effectivePlatform
      if (state.canSwitchPlatform) {
        // 户管与开发者可跨平台，落地账户页而非产品页
        return p === 'fb' ? '/fb/accounts' : p === 'tt' ? '/tt/accounts' : '/accounts/ads'
      }
      return p === 'fb' ? '/fb/products' : p === 'tt' ? '/tt/products' : '/accounts/products'
    },
```

`roleLabel` 的 labels 对象加入 `huguan: '户管'`：

```js
      const labels = { developer: '开发者', admin: '管理员', viewer: '观察者', user: '用户', hidden: '已禁用', huguan: '户管' }
```

`login` action 中 `if (this.isDeveloper) {` 改为 `if (this.canSwitchPlatform) {`；`setPlatform` 中 `if (this.isDeveloper) {` 改为 `if (this.canSwitchPlatform) {`。

- [ ] **Step 2: 改造 `frontend/src/api/client.js`**

把第 13 行：

```js
    if (user.role === 'developer') {
```

改为：

```js
    if (['developer', 'huguan'].includes(user.role)) {
```

并把第 10 行的注释从 `// developer 跨平台时传递 platform 参数` 改为 `// 跨平台角色（developer / 户管）请求时传递 platform 参数`。

**注意**：第 17 行的 `if (!path.startsWith('/admin/users'))` 判断必须保留——户管在用户管理页同样不该被注入推断出的平台。

- [ ] **Step 3: 改造路由守卫 `frontend/src/router/index.js`**

把 `/` 的 redirect（第 17-24 行）整段替换为：

```js
    redirect: () => {
      const token = localStorage.getItem('token')
      if (!token) return '/login'
      const user = JSON.parse(localStorage.getItem('user') || '{}')
      if (user.role === 'developer' || user.role === 'huguan') {
        // 跨平台角色以 GG 为默认落地，随后可在侧边栏切换
        return '/accounts/ads'
      }
      if (user.platform === 'fb') return '/fb/products'
      if (user.platform === 'tt') return '/tt/products'
      return '/accounts/products'
    }
```

在 `router.beforeEach` 内、`const platformHome = ...` 之后插入户管路由白名单：

```js
  // 户管可进入的带 meta.admin 的账户区/用户管理路由
  const HUGUAN_ROUTES = [
    '/accounts/ads', '/accounts/mcc', '/accounts/settings',
    '/fb/accounts', '/fb/bms', '/fb/pixels', '/fb/settings',
    '/tt/accounts', '/tt/bcs', '/tt/settings',
    '/admin/users',
  ]
  const isHuguanAllowedRoute = (p) =>
    HUGUAN_ROUTES.some(r => p === r || p.startsWith(r + '/'))
```

把平台守卫（第 170-175 行）改为：

```js
  if (to.meta.platform && !auth.canSwitchPlatform) {
    if (to.meta.platform !== auth.effectivePlatform) {
      next(platformHome)
      return
    }
  }
```

把 admin 守卫（第 176-179 行）改为：

```js
  if (to.meta.admin && !auth.isAdmin && !(auth.isHuguan && isHuguanAllowedRoute(to.path))) {
    next(platformHome)
    return
  }
```

并把 `platformHome` 的计算（第 164-167 行）替换为使用 store 的 getter：

```js
  const platformHome = auth.homePath
```

（`userPlatform` 变量随之删除；确认全文件再无引用：`grep -n userPlatform frontend/src/router/index.js` 应无输出。）

- [ ] **Step 4: 构建验证**

Run: `cd frontend && npm run build`
Expected: 构建成功，无 `error` 级别输出。

- [ ] **Step 5: 手工核对**

用一个 `role='huguan'`、`platform='gg'` 的账号登录后逐条确认：

1. 登录后落地在 `/accounts/ads`（不是 `/accounts/products`）。
2. 直接访问 `#/accounts/ads`、`#/accounts/mcc`、`#/accounts/settings`、`#/admin/users` → 页面正常打开，**不被弹回首页**。
3. 直接访问 `#/admin/scheduler` → 被重定向。
4. 点击 FB 切换按钮后落地在 `/fb/accounts`（不是 `/fb/products`）；TT 同理。
5. 切到 TT 后访问 `#/tt/accounts` → 页面正常打开（**不被平台守卫弹回**）。

同时用 developer 账号回归：落地 `/accounts/products`，各平台切换与守卫行为与改动前一致。

- [ ] **Step 6: 提交**

```bash
git add frontend/src/stores/auth.js frontend/src/api/client.js frontend/src/router/index.js
git commit -m "feat: 前端跨平台判断与路由守卫支持户管"
```

---

### Task 12: 户管侧边栏导航

**Files:**
- Modify: `frontend/src/components/AppSidebar.vue`
- Test: `npm run build` + 手工核对

**Interfaces:**
- Consumes: Task 11 的 `isHuguan`、`canSwitchPlatform`、`canManageAccounts`、`homePath`
- Produces: `huguanNavItems` 计算属性（按 `effectivePlatform` 返回户管专用导航），`currentNavItems` 在 `auth.isHuguan` 时短路到它。

- [ ] **Step 1: 平台切换按钮放开**

第 12 行：

```html
      <div v-if="auth.isDeveloper" class="platform-switch">
```

改为：

```html
      <div v-if="auth.canSwitchPlatform" class="platform-switch">
```

- [ ] **Step 2: `switchPlatform` 按角色分派落点**

把第 61-74 行整段替换为：

```js
function switchPlatform(platform) {
  auth.setPlatform(platform)
  const accountPath = platform === 'fb' ? '/fb/accounts' : platform === 'tt' ? '/tt/accounts' : '/accounts/ads'
  const productPath = platform === 'fb' ? '/fb/products' : platform === 'tt' ? '/tt/products' : '/accounts/products'
  const target = auth.isHuguan ? accountPath : productPath
  router.push(target)
  activeSection.value = platform === 'fb' ? 'fb-accounts' : platform === 'tt' ? 'tt-accounts' : 'accounts'
}
```

- [ ] **Step 3: 新增户管专用导航数组**

在 `ttNavItems` 定义（第 105-119 行）之后插入：

```js
// 户管：只有账户区、设置、用户管理；不含产品 / 视频 / 媒体 / 工具集 / 数据分析 / 定时任务
const huguanNavItems = [
  { key: 'accounts', icon: '🏢', label: '账户管理', sections: [
    { title: '账户', items: [
      { icon:'👤',label:'广告账户',path:'/accounts/ads'},
      { icon:'🏢',label:'MCC管理',path:'/accounts/mcc'},
    ]},
    { title: '系统', items: [{ icon:'⚙',label:'设置',path:'/accounts/settings' }]},
  ]},
  { key: 'admin', icon: '🏴', label: '管理', admin: true, sections: [
    { title: '管理', items: [{ icon:'👥',label:'用户管理',path:'/admin/users' }]},
  ]},
]
const huguanFbNavItems = [
  { key: 'fb-accounts', icon: '🏢', label: '账户管理', sections: [
    { title: '账户', items: [
      { icon:'👤',label:'广告账户',path:'/fb/accounts'},
      { icon:'🏢',label:'BM管理',path:'/fb/bms'},
      { icon:'📊',label:'像素管理',path:'/fb/pixels'},
    ]},
    { title: '系统', items: [{ icon:'⚙',label:'FB设置',path:'/fb/settings' }]},
  ]},
  { key: 'admin', icon: '🏴', label: '管理', admin: true, sections: [
    { title: '管理', items: [{ icon:'👥',label:'用户管理',path:'/admin/users' }]},
  ]},
]
const huguanTtNavItems = [
  { key: 'tt-accounts', icon: '🏢', label: '账户管理', sections: [
    { title: '账户', items: [
      { icon:'👤',label:'广告账户',path:'/tt/accounts'},
      { icon:'🏢',label:'BC管理',path:'/tt/bcs'},
    ]},
    { title: '系统', items: [{ icon:'⚙',label:'TT设置',path:'/tt/settings' }]},
  ]},
  { key: 'admin', icon: '🏴', label: '管理', admin: true, sections: [
    { title: '管理', items: [{ icon:'👥',label:'用户管理',path:'/admin/users' }]},
  ]},
]
```

- [ ] **Step 4: 让 `currentNavItems` 与 `visibleNavItems` 短路到户管导航**

把第 121-130 行整段替换为：

```js
const currentNavItems = computed(() => {
  if (auth.isHuguan) {
    return auth.effectivePlatform === 'fb' ? huguanFbNavItems
      : auth.effectivePlatform === 'tt' ? huguanTtNavItems
      : huguanNavItems
  }
  return auth.effectivePlatform === 'fb' ? fbNavItems
    : auth.effectivePlatform === 'tt' ? ttNavItems
    : ggNavItems
})

const visibleNavItems = computed(() => currentNavItems.value.filter(n => {
  if (n.admin) return auth.isAdmin || auth.isHuguan
  return true
}))
```

**说明**：原判断 `if (n.key === 'accounts' || ...) return auth.canAccessProducts` 被删除，改为对 `n.admin` 显式放行户管。这样做的效果是——户管的导航来自 `huguanNavItems`，「管理」分组对户管可见；而既有角色的导航数组（`ggNavItems` 等）中，账户区这一项**不再受 `canAccessProducts` 门控**。为避免影响既有角色，必须在同一处保留原语义：把 `ggNavItems` / `fbNavItems` / `ttNavItems` 的账户区项加上 `requireProducts: true` 标记，并在 `visibleNavItems` 里补回判断。

即：`ggNavItems` 第 78 行的 `{ key: 'accounts', icon: '🏢', label: '账户管理', admin: true, sections: [...]}` 加一个字段 `requireProducts: true`；`fbNavItems` 第 88 行的 `{ key: 'fb-accounts', ...}` 与 `ttNavItems` 第 106 行的 `{ key: 'tt-accounts', ...}` 同样加上。`huguanNavItems` / `huguanFbNavItems` / `huguanTtNavItems` 的三个账户区项**不加**该字段。

然后 `visibleNavItems` 最终写法为：

```js
const visibleNavItems = computed(() => currentNavItems.value.filter(n => {
  if (n.requireProducts) return auth.canAccessProducts
  if (n.admin) return auth.isAdmin || auth.isHuguan
  return true
}))
```

- [ ] **Step 5: 「管理」分组内的 developer 专属项过滤**

第 145-157 行的两个过滤块保持不动。户管导航数组里本就没有 `developer: true` 的项，`!auth.isDeveloper` 分支会原样通过；`!auth.isAdmin` 分支会因 `!auth.isAdmin` 为真而尝试过滤 `item.admin`——但户管导航数组里的「用户管理」项没有 `admin: true` 字段（只有外层的 nav 对象有），所以不会被误删。**Step 7 的手工核对必须确认「用户管理」菜单项对户管可见。**

- [ ] **Step 6: 构建验证**

Run: `cd frontend && npm run build`
Expected: 构建成功

- [ ] **Step 7: 手工核对**

户管账号（GG）：侧边栏出现 GG/FB/TT 三个切换按钮；账户管理分组里只有「广告账户」「MCC管理」「设置」；管理分组里**能看到「用户管理」**，看不到「定时任务」；侧边栏**没有**产品管理、视频管理、媒体工具、工具集、数据分析图标。点击「账户管理」图标 → 落在 `/accounts/ads`（不是产品页）。

切到 FB：只有「广告账户/BM管理/像素管理/FB设置」+「用户管理」。切到 TT：只有「广告账户/BC管理/TT设置」+「用户管理」。

回归用 user / admin / developer 三种账号：侧边栏与改动前完全一致。

- [ ] **Step 8: 提交**

```bash
git add frontend/src/components/AppSidebar.vue
git commit -m "feat: 户管专用侧边栏导航与账户页落地"
```

---

### Task 13: GG 账户页顶部 Tab 对户管开放

**Files:**
- Modify: `frontend/src/views/AccountsView.vue`
- Test: `npm run build` + 手工核对

**Interfaces:**
- Consumes: Task 11 的 `canManageAccounts`、`isHuguan`
- Produces: 户管在 GG 账户页可见「广告账户 / MCC管理 / 设置」三个 Tab，看不到「产品管理」，且默认停在「广告账户」。

- [ ] **Step 1: 改 Tab 可见性与默认页**

把第 6-9 行：

```html
        <el-tab-pane label="产品管理" name="products" />
        <el-tab-pane v-if="auth.isAdmin" label="广告账户" name="ads" />
        <el-tab-pane v-if="auth.isAdmin" label="MCC 管理" name="mcc" />
        <el-tab-pane v-if="auth.isAdmin" label="设置" name="settings" />
```

改为：

```html
        <el-tab-pane v-if="!auth.isHuguan" label="产品管理" name="products" />
        <el-tab-pane v-if="auth.canManageAccounts" label="广告账户" name="ads" />
        <el-tab-pane v-if="auth.canManageAccounts" label="MCC 管理" name="mcc" />
        <el-tab-pane v-if="auth.canManageAccounts" label="设置" name="settings" />
```

- [ ] **Step 2: 构建验证**

Run: `cd frontend && npm run build`
Expected: 构建成功

- [ ] **Step 3: 手工核对**

户管访问 `#/accounts` → 被重定向到 `/accounts/ads`（路由里 `redirect: '/accounts/products'`）。

⚠️ **这里有一个必须处理的点**：`frontend/src/router/index.js:29` 的 `/accounts` 路由 `redirect: '/accounts/products'` 是静态字符串。户管访问 `#/accounts` 会被送到产品页。把该行改为函数式重定向：

```js
    redirect: () => '/accounts/ads',
```

**但这会改变既有角色的行为**，违反纯增量原则。因此改为按身份分派：

```js
    redirect: () => {
      const user = JSON.parse(localStorage.getItem('user') || '{}')
      return (user.role === 'huguan') ? '/accounts/ads' : '/accounts/products'
    }
```

同样处理 `frontend/src/router/index.js:90` 的 `/fb` 与 `:132` 的 `/tt`：

```js
    redirect: () => {
      const user = JSON.parse(localStorage.getItem('user') || '{}')
      return (user.role === 'huguan') ? '/fb/accounts' : '/fb/products'
    }
```

```js
    redirect: () => {
      const user = JSON.parse(localStorage.getItem('user') || '{}')
      return (user.role === 'huguan') ? '/tt/accounts' : '/tt/products'
    }
```

（`/tt` 的 redirect 与 children 同在一个对象里，只改 `redirect` 字段。）

- [ ] **Step 4: 复查构建**

Run: `cd frontend && npm run build`
Expected: 构建成功

- [ ] **Step 5: 手工核对**

户管访问 `#/accounts`、`#/fb`、`#/tt` → 分别落在 `/accounts/ads`、`/fb/accounts`、`/tt/accounts`。GG 账户页只显示三个 Tab（无「产品管理」）。

用 admin / user 账号回归：`#/accounts` 仍落在 `/accounts/products`。

- [ ] **Step 6: 提交**

```bash
git add frontend/src/views/AccountsView.vue frontend/src/router/index.js
git commit -m "feat: GG 账户页 Tab 对户管开放，平台根路由按身份分派"
```

---

### Task 14: 用户管理页对户管收窄

**Files:**
- Modify: `frontend/src/views/UserManageView.vue`
- Test: `npm run build` + 手工核对

**Interfaces:**
- Consumes: Task 3 的后端边界（创建强制 `huguan`、列表只返回 `huguan`、角色只能切到 `huguan`/`hidden`）、Task 11 的 `isHuguan`
- Produces: 户管看到的是「户管专用视图」——无平台 Tab、无平台字段、创建角色锁定、行操作只对自己创建的户管显示。

- [ ] **Step 1: 隐藏平台 Tab**

第 9-14 行的 `<el-tabs>` 外层加条件：

```html
    <el-tabs v-if="!authStore.isHuguan" v-model="platformFilter" @tab-change="onPlatformChange" style="margin-bottom:8px;">
```

- [ ] **Step 2: 创建弹窗的角色下拉按身份分档**

第 92-98 行整段替换为（**现有 option 的 label 文案 `普通用户/观察者/管理员` 保持不变**）：

```html
        <el-form-item label="角色">
          <el-select v-model="createForm.role" :disabled="authStore.isHuguan" style="width:100%">
            <el-option label="普通用户" value="user" />
            <el-option label="观察者" value="viewer" />
            <el-option label="管理员" value="admin" />
            <el-option v-if="authStore.isDeveloper || authStore.isHuguan" label="户管" value="huguan" />
          </el-select>
        </el-form-item>
```

`disabled` 对户管为真、选项集合由后端 `ALLOWED_CREATE_ROLES` 兜底（户管传任何 role 都会落库为 `huguan`），因此这里不需要按身份删选项——只需禁用与补上「户管」项。

- [ ] **Step 3: 创建表单的初始 role 与平台**

第 285 行附近的 `createForm` 初始化，`role` 改为按身份：

```js
const createForm = ref({
  username: "",
  password: "",
  display_name: "",
  role: authStore.isHuguan ? "huguan" : "user",
  platform: authStore.isDeveloper
    ? (platformFilter.value || 'gg')
    : authStore.effectivePlatform
})
```

第 317 行创建成功后的重置同样处理：

```js
    createForm.value = {
      username: "", password: "", display_name: "",
      role: authStore.isHuguan ? "huguan" : "user",
      platform: authStore.isDeveloper ? (platformFilter.value || 'gg') : authStore.effectivePlatform
    }
```

（第 99 行与第 125 行的平台字段 `v-if="authStore.isDeveloper"` **保持不动**——户管不是 developer，字段本就不显示，无需额外条件。）

- [ ] **Step 4: 行操作按钮对户管收窄**

第 204-209 行的 `canModify(row)` 替换为：

```js
function canModify(row) {
  if (isSelf(row.id)) return false
  if (authStore.isDeveloper) return true
  // 户管只能操作自己创建的户管
  if (authStore.isHuguan) {
    return row.role === 'huguan' && row.created_by === authStore.user?.id
  }
  // 管理员只能操作普通用户、观察者和已禁用用户，不能操作其他管理员
  return ['user', 'viewer', 'hidden'].includes(row.role)
}
```

`list_users` 的 `SELECT_COLS` 已含 `created_by`（`py/auth.py:90`），因此 `row.created_by` 直接可用。

- [ ] **Step 5: 行内「切换角色」下拉按身份分档**

第 56-61 行的 `el-dropdown-menu` 替换为：

```html
                <el-dropdown-menu>
                  <template v-if="authStore.isHuguan">
                    <el-dropdown-item command="huguan" :disabled="row.role === 'huguan'">户管</el-dropdown-item>
                    <el-dropdown-item command="hidden" :disabled="row.role === 'hidden'">禁用</el-dropdown-item>
                  </template>
                  <template v-else>
                    <el-dropdown-item command="user" :disabled="row.role === 'user'">普通用户</el-dropdown-item>
                    <el-dropdown-item command="viewer" :disabled="row.role === 'viewer'">观察者</el-dropdown-item>
                    <el-dropdown-item command="admin" :disabled="row.role === 'admin'">管理员</el-dropdown-item>
                    <el-dropdown-item v-if="authStore.isDeveloper" command="huguan" :disabled="row.role === 'huguan'">户管</el-dropdown-item>
                    <el-dropdown-item command="hidden" :disabled="row.role === 'hidden'">禁用</el-dropdown-item>
                  </template>
                </el-dropdown-menu>
```

- [ ] **Step 6: 补角色标签映射**

第 211-218 行的 `roleType` 与 `roleLabel` 各加一项，否则户管的标签会渲染成默认灰色 + 英文原文：

```js
function roleType(role) {
  const m = { developer: 'danger', admin: 'warning', viewer: '', user: 'success', hidden: 'info', huguan: 'primary' }
  return m[role] || 'info'
}
function roleLabel(role) {
  const m = { developer: '开发者', admin: '管理员', viewer: '观察者', user: '用户', hidden: '已禁用', huguan: '户管' }
  return m[role] || role
}
```

- [ ] **Step 7: 构建验证**

Run: `cd frontend && npm run build`
Expected: 构建成功

- [ ] **Step 8: 手工核对**

户管账号进入 `#/admin/users`：无平台 Tab；列表里只有 `huguan` 角色的用户（角色列显示「户管」蓝色标签）；创建弹窗角色锁定为「户管」且灰显、无平台字段；自己创建的户管行上有「编辑/改密/切换角色/删除」按钮且切换角色只有「户管/禁用」两项；别人创建的户管行上**只有一个 🔒 图标**。

developer 账号：创建弹窗与行内下拉都出现「户管」项，其余不变。
admin 账号：创建弹窗**没有**「户管」项（控制台直接构造请求也会被后端 400 拒绝），其余不变。
普通 user 账号：与改动前完全一致。

- [ ] **Step 9: 提交**

```bash
git add frontend/src/views/UserManageView.vue
git commit -m "feat: 用户管理页按户管身份收窄"
```

---

### Task 15: TT 设置页把选项编辑区从「仅管理员」块中拆出

**Files:**
- Modify: `frontend/src/views/tt/TtSettingsPanel.vue:66-70`
- 不改：`frontend/src/views/SettingsPanel.vue`、`frontend/src/views/fb/FbSettingsPanel.vue`
- Test: `npm run build` + 手工核对

**Interfaces:**
- Consumes: Task 10 的后端权限（`GLOBAL_OPTION_ROLES`）、Task 11 的路由守卫（让户管能进 `/tt/settings`）
- Produces: 户管在 TT 设置页能看到并编辑「代理名 / 账户状态 / 回收原因」等选项卡片；**TT 的 Google 表格配置块对户管继续保持隐藏**（户管的 sheet 配置属子项目 B）。

**为什么只有 TT 要改（已核实，不要顺手改另外两个）**：

| 文件 | 现状 | 是否需要改 |
|---|---|---|
| `frontend/src/views/tt/TtSettingsPanel.vue:67` | 一个 `v-if="authStore.isAdmin \|\| authStore.isDeveloper"` 同时罩住了 **选项卡片**（第 68-70 行的 `adminOptionCards`）和 **Google 表格配置** | **要改**——不拆的话户管在 TT 看不到任何选项卡片 |
| `frontend/src/views/SettingsPanel.vue:65` | 同一个 `v-if` 只罩住「📊 充值表配置」这一张 card（第 66-103 行）；选项卡片在它**之外** | **不改**——户管本来就看得见 |
| `frontend/src/views/fb/FbSettingsPanel.vue` | 全文无任何 `isAdmin` / `isDeveloper` 判断 | **不改** |

- [ ] **Step 1: 把选项卡片移出管理员专属块**

`py`/前端行号以 `frontend/src/views/tt/TtSettingsPanel.vue` 为准。当前结构：

```html
        <!-- 管理员专属 Google 表格配置 -->
        <template v-if="authStore.isAdmin || authStore.isDeveloper">
          <!-- 代理 / 状态 / 回收原因选项卡片 -->
          <el-row :gutter="16">
            <el-col :span="12" v-for="card in adminOptionCards" :key="card.key">
```

在第 67 行的 `<template v-if=...>` **之前**插入同一段选项卡片的可见版本，并把原块内的选项卡片整段删除。改完后结构为：

```html
        <!-- 平台级选项（代理 / 状态 / 回收原因）— 管理员与户管均可编辑 -->
        <el-row v-if="authStore.isAdmin || authStore.isDeveloper || authStore.isHuguan" :gutter="16">
          <el-col :span="12" v-for="card in adminOptionCards" :key="card.key">
            <!-- ⬇️ 此处原样搬移第 70-125 行（选项卡片内部）的全部内容，一行都不改 -->
          </el-col>
        </el-row>

        <!-- 管理员专属 Google 表格配置 -->
        <template v-if="authStore.isAdmin || authStore.isDeveloper">
          <!-- ⬇️ 原来罩在这里的选项卡片已上移；只留下 sheet_id 与 sheet_mappings 部分（原第 126-164 行） -->
```

**关键约束**：选项卡片的内部实现（`handleAdminDelete` / `startAdminTagEdit` / `finishAdminTagEdit` / `showAddInput` / `adminLists` / `adminEditingId`）**一行都不改**，只是换了外层容器和 `v-if`。搬运后必须核对标签闭合——`<el-col>` 与 `<el-row>` 的配对是最容易出错的地方。

- [ ] **Step 2: 构建验证**

Run: `cd frontend && npm run build`
Expected: 构建成功，无 Vue 模板编译错误（标签不配对会在这里报出来）

- [ ] **Step 3: 手工核对**

户管在 `#/tt/settings`：**能**看到并增删改「代理名 / 账户状态 / 回收原因」三张选项卡片（双击标签改名、点 × 删除、点 + 新增都能用）；**看不到** Google 表格配置块（表格链接、Sheet 映射、《仅管理员》标签那一整块）。

户管在 `#/accounts/settings`（GG）与 `#/fb/settings`：选项卡片能看能改，GG 的「📊 充值表配置」卡片看不到。

admin 与 developer 在三个设置页：与改动前完全一致（选项卡片 + sheet 配置都在）。

- [ ] **Step 4: 提交**

```bash
git add frontend/src/views/tt/TtSettingsPanel.vue
git commit -m "feat: TT 设置页选项编辑区对户管开放"
```

---

### Task 16: 账户面板新增「全部用户」筛选下拉

**Files:**
- Modify: `frontend/src/stores/accounts.js:11`（`acFilters` 增加 `owner_id`）
- Modify: `frontend/src/views/AdsAccountPanel.vue`
- Modify: `frontend/src/views/MccPanel.vue`
- Modify: `frontend/src/views/fb/FbAccountPanel.vue`、`fb/FbBmPanel.vue`、`fb/FbPixelPanel.vue`、`fb/FbPixelBmPanel.vue`
- Modify: `frontend/src/views/tt/TtAccountPanel.vue`、`tt/TtBcPanel.vue`
- Test: `npm run build` + 手工核对

**Interfaces:**
- Consumes: Task 4 的 `GET /api/platform/users`；Task 5/6/9 的 `owner_id` 查询参数
- Produces: 一个可复用的前端小组件 `frontend/src/components/OwnerFilterSelect.vue`（`v-model` 绑定 `owner_id`，`@change` 触发重载），供上述 8 个面板复用。

- [ ] **Step 1: 新建 `frontend/src/components/OwnerFilterSelect.vue`**

```vue
<template>
  <el-select v-if="visible" :model-value="modelValue" @update:model-value="onChange"
    placeholder="全部用户" style="width:150px;" clearable filterable>
    <el-option v-for="u in users" :key="u.id" :label="u.display_name || u.username" :value="u.id" />
  </el-select>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { useAuthStore } from '@/stores/auth'
import api from '@/api/client'

const props = defineProps({ modelValue: { type: [String, Number], default: '' } })
const emit = defineEmits(['update:modelValue', 'change'])

const auth = useAuthStore()
const visible = computed(() => auth.canManageAccounts)
const users = ref([])

onMounted(async () => {
  if (!visible.value) return
  try {
    const res = await api.get('/platform/users')
    users.value = res.users || []
  } catch { /* 用户下拉加载失败不阻塞主流程 */ }
})

function onChange(val) {
  emit('update:modelValue', val)
  emit('change', val)
}
</script>
```

- [ ] **Step 2: GG 账户面板接入**

`frontend/src/stores/accounts.js:11` 把：

```js
    acFilters: { search: '', status: '', mcc_id: '', agent: '', timezone: '' },
```

改为：

```js
    acFilters: { search: '', status: '', mcc_id: '', agent: '', timezone: '', owner_id: '' },
```

（`stores/accounts.js:29` 的 `const params = { page: this.acPage, size: this.acPageSize, ...this.acFilters }` 会自动带上 `owner_id`，无需改。）

在 `frontend/src/views/AdsAccountPanel.vue` 第 40 行（时区下拉 `</el-select>`）之后插入：

```html
        <OwnerFilterSelect v-model="store.acFilters.owner_id" @change="searchAndLoad" />
```

在 `<script setup>` 的 import 区加入：

```js
import OwnerFilterSelect from '@/components/OwnerFilterSelect.vue'
```

`searchAndLoad` 是该文件既有函数（第 269 行 `function searchAndLoad() { store.acPage = 1; load() }`），已经把页码重置为 1，直接复用。

- [ ] **Step 3: GG MCC 面板接入**

`frontend/src/stores/accounts.js:16` 把：

```js
    mccFilters: { search: '', level: '', parent_filter: '' },
```

改为：

```js
    mccFilters: { search: '', level: '', parent_filter: '', owner_id: '' },
```

（`stores/accounts.js:46` 的 `const params = { page: this.mccPage, size: this.mccPageSize, ...this.mccFilters }` 会自动带上。）

在 `frontend/src/views/MccPanel.vue` 的筛选栏（与现有搜索框、等级下拉同一行）插入：

```html
        <OwnerFilterSelect v-model="store.mccFilters.owner_id" @change="load" />
```

在 `<script setup>` 的 import 区加入：

```js
import OwnerFilterSelect from '@/components/OwnerFilterSelect.vue'
```

`load()` 是该文件既有函数（第 74 行 `function load() { store.loadMccList() }`）。MCC 面板不分页（`mccPage` 由 `store` 管理），无需重置页码。

- [ ] **Step 4: FB / TT 面板接入**

以下五个文件结构一致，逐个照做：

| 文件 | 加载函数 | 筛选栏 ref 命名参考 |
|---|---|---|
| `fb/FbAccountPanel.vue` | `loadData()`（第 124 行） | 与 `search` / `statusFilter` 同处 |
| `fb/FbBmPanel.vue` | `loadData()`（第 173 行） | 与 `search` / `status` 同处 |
| `fb/FbPixelPanel.vue` | `loadData()`（第 118 行） | 与 `search` 同处 |
| `fb/FbPixelBmPanel.vue` | `loadData()`（第 142 行） | 与 `search` 同处 |
| `tt/TtBcPanel.vue` | `loadData()`（第 85 行） | 与 `search` 同处 |

每个文件的三步改动：

1. `<script setup>` 中新增 `const ownerId = ref('')` 并 import 组件（与 `search` ref 放在一起，import 放在其它 `@/components` 之后）。
2. 筛选栏里对应的 `el-select` 之后插入 `<OwnerFilterSelect v-model="ownerId" @change="loadData" />`。
3. `loadData()` 构造请求参数处加一行 `if (ownerId.value) params.owner_id = ownerId.value`（参数对象名以该函数实际写法为准，通常是 `params` 或直接内联对象）。

若某个 `loadData()` 在 `@change` 后还需重置页码，参照该文件内相邻筛选控件的做法（多数 FB 面板是一次性加载不分页，无需额外处理）。

`tt/TtAccountPanel.vue` 已有自己的「全部投手」下拉（第 45-47 行，`v-if="isAdmin"`）。改为复用公共组件：删除第 45-47 行的 `<el-select v-if="isAdmin" ...>` 整段，替换为：

```html
        <OwnerFilterSelect v-model="ownerId" @change="filterAndLoad" />
```

第 224 行的 `const isAdmin = computed(() => authStore.isAdmin || authStore.isDeveloper)` 保留不动（文件其他处仍在用）；第 315-320 行的 `listTtUsers()` 加载逻辑与第 330 行的 `if (isAdmin.value && ownerId.value) params.owner_id = ownerId.value` **保留不动**——组件会额外拉一次 `/api/platform/users`，多一次请求但不影响正确性。若想去掉这次重复请求，可把第 330 行的条件改为 `if (ownerId.value)` 并删除 315-320 的加载块——**可选**，不做也不影响功能。

- [ ] **Step 5: 构建验证**

Run: `cd frontend && npm run build`
Expected: 构建成功

- [ ] **Step 6: 手工核对**

户管在 GG 广告账户 / MCC、FB 广告账户 / BM / 像素 / 像素BM、TT 广告账户 / BC 八个面板：都能看到「全部用户」下拉；选择某个用户后列表与顶部状态计数同步收窄；清空下拉后回到全部。下拉里没有 `hidden` 用户，包含 developer。

admin 账号：FB 与 GG 面板**不应**出现该下拉（`canManageAccounts` 对 admin 为 true——**注意**：admin 也会看到该下拉，这是可接受的，因为后端对 admin 同样按 `CROSS_USER_ROLES` 放行，行为一致）。普通 user / viewer 账号：看不到该下拉。

- [ ] **Step 7: 提交**

```bash
git add frontend/src/components/OwnerFilterSelect.vue frontend/src/stores/accounts.js frontend/src/views/AdsAccountPanel.vue frontend/src/views/MccPanel.vue frontend/src/views/fb/ frontend/src/views/tt/TtAccountPanel.vue frontend/src/views/tt/TtBcPanel.vue
git commit -m "feat: 各账户面板新增全部用户筛选下拉"
```

---

### Task 17: 产品域与素材域对户管收口

> **为什么有这个任务**：Task 1 放宽 `require_platform` 后，户管可以跨平台调用 TT / FB 的**全部**路由。而 TT / FB 产品域的唯一关卡就是 `require_platform`（`helpers.can_modify` 在生产代码中零调用，设计文档 §3.6.4 原先误以为它是防线）。不收口则「户管不获得产品/视频编辑权限」这条约束无法兑现——前端菜单隐藏挡不住直接调 API。详见设计文档 §3.9。

**Files:**
- Modify: `py/routes/decorators.py`（新增 `reject_huguan()` 与装饰器 `no_huguan`；import 增加 `HUGUAN_ROLE`）
- Modify: `py/routes/fb_routes.py`（产品域写端点叠加 `@no_huguan`）
- Modify: `py/routes/tt_routes.py`（产品/包/素材域写端点叠加 `@no_huguan`）
- Test: `py/tests/test_huguan_role.py`（追加）

**Interfaces:**
- Consumes: `HUGUAN_ROLE`（Task 1，`py/routes/helpers.py`）
- Produces:
  - `reject_huguan() -> flask.Response | None`（与既有 `reject_viewer()` 同形状：返回错误响应或 `None`）
  - `no_huguan(fn)` 装饰器，叠加在 `@fb_required` / `@tt_write_required` 之内层

**范围规则（本任务的核心，务必按规则判定而非按行号）：**

| 归属 | 路由前缀 | 处理 |
|---|---|---|
| **产品域**（要收口） | `/api/fb/products/`、`/api/fb/lines/`、`/api/tt/products/`、`/api/tt/packages/` | 所有 POST / PUT / DELETE 端点叠加 `@no_huguan` |
| **账户域**（**不得**收口） | `/api/fb/bms/`、`/api/fb/accounts/`、`/api/fb/pixels/`、`/api/tt/bcs/`、`/api/tt/accounts/` | 一律不动 |
| **设置 / 数据域**（**不得**收口） | `/api/tt/settings`、`/api/tt/data/import`、`/api/fb/extract/`、`/api/fb/reports/` | 一律不动 |

产品域的**读**端点（GET）保持不动——约束是「不获得**编辑**权」，且新增读权限不构成提权。

- [ ] **Step 1: 清点待改端点**

Run:
```bash
cd py && grep -nE "^@(fb|tt)_bp\.route\('/api/(fb|tt)/(products|lines|packages)" -A 3 routes/fb_routes.py routes/tt_routes.py | grep -E "@(fb|tt)_bp\.route|@(fb_required|tt_write_required|tt_required)|^[0-9]+-def "
```
把输出的每个 POST / PUT / DELETE 端点记下来（GET 端点跳过）。预期：FB 侧 `products/create`、`products/<pid>`(PUT)、`products/<pid>`(DELETE)、`products/<pid>/restore`、`products/<pid>/lines`、`lines/<lid>`(PUT) 等；TT 侧 `products/create`、`products/<pid>`(PUT)、`products/<pid>`(DELETE)、`products/<pid>/restore`、`products/<pid>/packages`、`packages/<pkg_id>`(PUT)、`packages/<pkg_id>`(DELETE)、`packages/batch-delete`、`products/<pid>/check-delist`、`products/merge`、`products/import-text`、`products/<pid>/assets`、`products/<pid>/assets/<video_id>`。

**特别提醒**：`tt_routes.py` 的 `products/import-text` 只挂了 `@tt_required`（不是 `@tt_write_required`）——它是产品写入接口，同样必须收口，别因为它长得不一样就漏掉。

- [ ] **Step 2: 写失败测试**

追加到 `py/tests/test_huguan_role.py`：

```python
class TestHuguanBlockedFromProductDomain:
    """户管可跨平台，但不得写产品 / 包 / 素材（设计文档 §3.9）。"""

    def _fb_product_by_developer(self, client):
        """借开发者身份造一个 FB 产品，供户管越权尝试。"""
        dev, _ = _create_user(client, "_hg_pd_dev", role="developer", platform="fb")
        resp = client.post("/api/fb/products/create", json={"product_name": "户管越权靶子"},
                           headers=dev)
        assert resp.status_code == 200, resp.get_json()
        return dev, resp.get_json()["id"]

    def test_huguan_cannot_create_fb_product(self, client):
        hg, _ = _huguan(client, "_hg_pd_fb_create")
        resp = client.post("/api/fb/products/create", json={"product_name": "越权"},
                           headers=hg)
        assert resp.status_code == 403

    def test_huguan_cannot_update_fb_product(self, client):
        _, pid = self._fb_product_by_developer(client)
        hg, _ = _huguan(client, "_hg_pd_fb_update")
        resp = client.put(f"/api/fb/products/{pid}", json={"product_name": "被篡改"},
                          headers=hg)
        assert resp.status_code == 403

    def test_huguan_cannot_delete_fb_product(self, client):
        _, pid = self._fb_product_by_developer(client)
        hg, _ = _huguan(client, "_hg_pd_fb_delete")
        resp = client.delete(f"/api/fb/products/{pid}", headers=hg)
        assert resp.status_code == 403

    def test_huguan_cannot_create_tt_product(self, client):
        hg, _ = _huguan(client, "_hg_pd_tt_create")
        resp = client.post("/api/tt/products/create", json={"product_name": "越权"},
                           headers=hg)
        assert resp.status_code == 403

    def test_huguan_cannot_import_tt_products(self, client):
        """import-text 只挂 @tt_required，是易漏的写入面。"""
        hg, _ = _huguan(client, "_hg_pd_tt_import")
        resp = client.post("/api/tt/products/import-text", json={"text": "x"},
                           headers=hg)
        assert resp.status_code == 403

    def test_huguan_can_still_write_account_domain(self, client):
        """回归：收口不得误伤账户域——户管仍可建 BC。"""
        hg, _ = _huguan(client, "_hg_pd_bc", platform="tt")
        resp = client.post("/api/tt/bcs/create", json={"name": "户管建的BC"}, headers=hg)
        assert resp.status_code == 200

    def test_developer_can_still_write_products(self, client):
        """回归：developer 的产品写权限不受影响。"""
        dev, _ = _create_user(client, "_hg_pd_dev2", role="developer", platform="gg")
        resp = client.post("/api/tt/products/create", json={"product_name": "开发者的产品"},
                           headers=dev)
        assert resp.status_code == 200
```

> `resp.get_json()["id"]` 的键名以 FB 产品创建接口的实际返回为准；先跑一次确认，若是 `{'id': ...}` 之外的形状（如 `{'product': {'id': ...}}`），按实际调整。`/api/tt/bcs/create` 与 `/api/tt/products/import-text` 的请求体字段名同理，以实际接口为准；若字段不符导致 400 而非 403，修正请求体使请求合法后再断言 403。

- [ ] **Step 3: 运行测试确认失败**

Run: `cd py && python -m pytest tests/test_huguan_role.py -v -k ProductDomain`
Expected: 5 条越权用例 FAIL（得到 200 或 400 而非 403）；两条回归用例 PASS。若回归用例此时就 FAIL，说明测试数据构造有误，先修测试。

- [ ] **Step 4: 在 `py/routes/decorators.py` 新增守卫**

把第 5 行的 import 改为：

```python
from routes.helpers import err, PLATFORM_SWITCH_ROLES, HUGUAN_ROLE
```

在 `reject_viewer()` 之后新增：

```python
def reject_huguan():
    """户管不参与产品 / 包 / 素材域。返回错误响应或 None。"""
    try:
        uid = int(get_jwt_identity())
    except Exception:
        return None  # 未登录由 @jwt_required() 处理
    user = auth.get_user_by_id(uid)
    if user and user.get("role") == HUGUAN_ROLE:
        return err("户管无产品/素材权限", 403)
    return None


def no_huguan(fn):
    """产品 / 素材域专用装饰器：户管一律拒绝。叠加在平台装饰器之内层。"""
    @wraps(fn)
    def wrapper(*args, **kwargs):
        err_resp = reject_huguan()
        if err_resp:
            return err_resp
        return fn(*args, **kwargs)
    return wrapper
```

- [ ] **Step 5: 逐端点叠加 `@no_huguan`**

对 Step 1 清点出的**每个**产品域 POST / PUT / DELETE 端点，在现有平台装饰器**之下一行**插入 `@no_huguan`。以 FB 产品创建为例（`py/routes/fb_routes.py`）：

```python
@fb_bp.route('/api/fb/products/create', methods=['POST'])
@jwt_required()
@fb_required
@no_huguan
def create_product():
```

TT 侧同理（`py/routes/tt_routes.py`）：

```python
@tt_bp.route('/api/tt/products/create', methods=['POST'])
@jwt_required()
@tt_write_required
@no_huguan
def create_product():
```

并在两个文件的 import 区把 `no_huguan` 加入既有的 `from routes.decorators import ...`。

**不要**给 `/api/fb/bms/`、`/api/fb/accounts/`、`/api/fb/pixels/`、`/api/tt/bcs/`、`/api/tt/accounts/`、`/api/tt/settings`、`/api/tt/data/import`、`/api/fb/extract/`、`/api/fb/reports/` 下的任何端点加 `@no_huguan`——那些属于账户域 / 设置域 / 数据域。

- [ ] **Step 6: 验证覆盖完整（防漏）**

Run:
```bash
cd py && echo "--- 产品域写端点 ---" && grep -nE "^@(fb|tt)_bp\.route\('/api/(fb|tt)/(products|lines|packages)" -A 6 routes/fb_routes.py routes/tt_routes.py | grep -E "^[0-9]+-@(fb|tt)_bp\.route|^[0-9]+-@no_huguan"
```
Expected: 每个 `products/` / `lines/` / `packages/` 的 **POST / PUT / DELETE** 路由行下方都能看到配对的 `@no_huguan`；GET 路由行下方没有。逐条核对数量一致，若有落单的路由行，补上 `@no_huguan` 并重跑。

- [ ] **Step 7: 运行测试确认通过**

Run: `cd py && python -m pytest tests/test_huguan_role.py -v`
Expected: 全部 passed

- [ ] **Step 8: 跑全量后端测试**

Run: `cd py && python -m pytest tests/ -v`
Expected: 全部 passed。重点确认 `test_tt_products.py`（若存在）、`test_fb_platform.py`、`test_tt_platform.py` 无 FAILED——`@no_huguan` 不应影响任何现有角色。

- [ ] **Step 9: 提交**

```bash
git add py/routes/decorators.py py/routes/fb_routes.py py/routes/tt_routes.py py/tests/test_huguan_role.py
git commit -m "feat: 产品域与素材域对户管收口（兑现户管无产品编辑权）"
```

---

### Task 18: GG 账户与 MCC 写操作对跨用户角色放行

> **为什么有这个任务（2026-09-22 预检发现，用户已确认新增）**：
> 需求是「户管对账户类对象有**全部编辑权限**」。查证三平台现状后发现**只有 GG 是漏的**：
> - **TT**：写接口用 `role not in ('developer','admin')` 守卫（`routes/tt_accounts_routes.py:506,543,560,611,696,732,786`），
>   Task 8 换成 `CROSS_USER_ROLES` 后户管自动获得写权限 ✅
> - **FB**：写接口**没有归属校验**（设计文档 §2.5 已记录）✅
> - **GG**：**8 处硬编码 `owner_id == 自己`**，一律拒绝 ❌ —— 本任务收口这 8 处
>
> 若不修，出现的是「看得见、点不动」：户管能列出别人的 MCC/账户，但编辑按钮不显示（前端 `is_owner` 门控）、
> 绕过前端直接调 API 也一律 403/404。这与「全部编辑权限」直接矛盾。
>
> **本任务不在 Task 6 里做**，是为了让 Task 6 保持「只改读路径」的单一关注点——两者评审标准不同。

**Files:**
- Modify: `py/main.py`（新增模块级 `_cross_user_actor`；改写 8 处校验）
- Modify: `frontend/src/views/MccPanel.vue`（编辑/删除按钮的显示条件）
- Test: `py/tests/test_huguan_role.py`（追加）

**Interfaces:**
- Consumes: Task 1 的 `CROSS_USER_ROLES`（`py/main.py:39` 已 import）；Task 11 的 `useAuthStore().canManageAccounts`
- Produces:
  - `_cross_user_actor(user_id: int) -> bool` — 模块级函数，当前请求者是否为可跨用户操作账户类资源的角色
  - 错误文案**全部保持原样**：`只有创建者才能编辑此 MCC`、`只有创建者才能删除此 MCC`、
    `非创建者，无法删除`、`账户不存在或已删除`、`账户不存在或未被删除`、`权限不足`

- [ ] **Step 1: 写失败测试**

追加到 `py/tests/test_huguan_role.py` 末尾（`_mk_mcc` 来自 Task 6、`_mk_account` 来自 Task 5，均已存在，**不要重复定义**）：

```python
class TestGgWriteOpsCrossUser:
    """GG 侧「硬编码 owner_id == 自己」的 8 处写校验对跨用户角色放行（Task 18）。"""

    def _fixture(self, client):
        hg, hg_id = _huguan(client, "_ggw_hg")
        _, u1 = _create_user(client, "_ggw_u1", role="user")
        db = database.get_db()
        _mk_mcc(db, u1, "MCC-W1", "别人的MCC")
        _mk_account(db, u1, "GG-W-1", "别人的账户")
        mcc_id = db.execute("SELECT id FROM mcc WHERE mcc_id='MCC-W1'").fetchone()["id"]
        acc_id = db.execute("SELECT id FROM accounts WHERE account_id='GG-W-1'").fetchone()["id"]
        db.close()
        return hg, u1, mcc_id, acc_id

    def test_huguan_can_update_others_mcc(self, client):
        hg, _, mcc_id, _ = self._fixture(client)
        resp = client.put(f"/api/mcc/{mcc_id}", json={"name": "改过的名字"}, headers=hg)
        assert resp.status_code == 200
        db = database.get_db()
        name = db.execute("SELECT name FROM mcc WHERE id=?", (mcc_id,)).fetchone()["name"]
        db.close()
        assert name == "改过的名字"

    def test_huguan_can_delete_others_mcc(self, client):
        hg, _, mcc_id, _ = self._fixture(client)
        assert client.delete(f"/api/mcc/{mcc_id}", headers=hg).status_code == 200

    def test_huguan_can_soft_delete_and_restore_others_account(self, client):
        hg, _, _, acc_id = self._fixture(client)
        assert client.delete(f"/api/accounts/{acc_id}", headers=hg).status_code == 200
        assert client.post(f"/api/accounts/{acc_id}/restore", headers=hg).status_code == 200

    def test_huguan_can_delete_others_mcc_history(self, client):
        """跨用户角色的 MCC 历史删除白名单（该接口原本只认 developer / admin）。"""
        hg, _, _, acc_id = self._fixture(client)
        db = database.get_db()
        db.execute("INSERT INTO account_mcc_history(account_id, old_mcc_id, new_mcc_id) VALUES(?,?,?)",
                   (acc_id, 1, 2))
        db.commit()
        hid = db.execute("SELECT id FROM account_mcc_history WHERE account_id=?", (acc_id,)).fetchone()["id"]
        db.close()
        resp = client.delete(f"/api/accounts/{acc_id}/mcc-history/{hid}", headers=hg)
        assert resp.status_code == 200
        assert resp.get_json()["deleted"] == 1

    def test_regular_user_still_blocked_from_others_mcc(self, client):
        """回归：普通用户改别人 MCC 仍是 403，且文案逐字节不变。"""
        _, _, mcc_id, _ = self._fixture(client)
        hdr, _ = _create_user(client, "_ggw_u2", role="user")
        resp = client.put(f"/api/mcc/{mcc_id}", json={"name": "越权"}, headers=hdr)
        assert resp.status_code == 403
        assert resp.get_json()["error"] == "只有创建者才能编辑此 MCC"

    def test_regular_user_still_blocked_from_others_account(self, client):
        """回归：普通用户删别人账户仍是 404，且账户**真的没被**软删除。"""
        _, _, _, acc_id = self._fixture(client)
        hdr, _ = _create_user(client, "_ggw_u3", role="user")
        assert client.delete(f"/api/accounts/{acc_id}", headers=hdr).status_code == 404
        db = database.get_db()
        deleted = db.execute("SELECT deleted_at FROM accounts WHERE id=?", (acc_id,)).fetchone()["deleted_at"]
        db.close()
        assert deleted is None

    def test_regular_user_still_blocked_from_others_mcc_history(self, client):
        """回归：普通用户删别人的 MCC 历史仍是 403。"""
        hdr, _ = _create_user(client, "_ggw_u4", role="user")
        _, _, _, acc_id = self._fixture(client)
        assert client.delete(f"/api/accounts/{acc_id}/mcc-history/1", headers=hdr).status_code == 403
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd py && python -m pytest tests/test_huguan_role.py -v -k GgWriteOpsCrossUser`
Expected: 四条户管用例 FAIL（403/404），三条回归用例 PASS。

- [ ] **Step 3: 新增模块级辅助函数**

在 `py/main.py` 的 `_mcc_to_dict`（`py/main.py:3580`）**之前**插入：

```python
def _cross_user_actor(user_id: int) -> bool:
    """当前请求者是否为可跨用户操作账户类资源的角色（developer / admin / 户管）。

    GG 侧原本硬编码「owner_id == 自己」的写校验统一改用本函数判定：
    自己的资源照旧放行；别人的资源仅跨用户角色放行。
    非跨用户角色（user / viewer / hidden）的判定结果与改动前**逐字节一致**。
    """
    actor = auth.get_user_by_id(user_id)
    return bool(actor) and actor.get("role") in CROSS_USER_ROLES
```

**注意**：一次请求内只调用一次，不要放进循环（`auth.get_user_by_id` 会新开一条数据库连接）。

- [ ] **Step 4: 改写 MCC 三处写校验**

三处都是同一个形状，只改 `if` 条件、**不动错误文案**。

`mcc_update`（`py/main.py:5499`）：

```python
    if mcc_row["owner_id"] != user_id and not _cross_user_actor(user_id):
```
（原为 `if mcc_row["owner_id"] != user_id:`，错误文案 `只有创建者才能编辑此 MCC` 保持不变）

`mcc_delete`（`py/main.py:5536`）：

```python
    if mcc_row["owner_id"] != user_id and not _cross_user_actor(user_id):
```
（错误文案 `只有创建者才能删除此 MCC` 保持不变）

`mcc_batch_delete`（`py/main.py:5576`）：在 `for mid in ids:` **之前**加一行

```python
    cross_user = _cross_user_actor(user_id)
```

循环内 `py/main.py:5576` 改为：

```python
        if mcc_row["owner_id"] != user_id and not cross_user:
            skipped.append({"id": mid, "reason": "非创建者，无法删除"})
            continue
```

- [ ] **Step 5: 改写 GG 账户四处写校验**

`accounts_delete`（`py/main.py:4292-4297`）把：

```python
        ac = db.execute(
            "SELECT account_id FROM accounts WHERE id=? AND owner_id=? AND deleted_at IS NULL",
            (aid, user_id)
        ).fetchone()
        if not ac:
            return jsonify({"success": False, "error": "账户不存在或已删除"}), 404
```

改为：

```python
        ac = db.execute(
            "SELECT account_id, owner_id FROM accounts WHERE id=? AND deleted_at IS NULL",
            (aid,)
        ).fetchone()
        if not ac or (ac["owner_id"] != user_id and not _cross_user_actor(user_id)):
            return jsonify({"success": False, "error": "账户不存在或已删除"}), 404
```

同一函数下方（`py/main.py:4310` 附近）的 `dashboard_name = _get_my_dashboard_name(db, user_id)`
改为 `_get_my_dashboard_name(db, ac["owner_id"])`。**这是逐字节等价的**——原代码能走到这里就保证
`ac["owner_id"] == user_id`；改为按行归属取，户管代删时才会落到 **owner 的**看板，而不是户管自己的。

`accounts_restore`（`py/main.py:4352-4357`）同法：`SELECT account_id, owner_id FROM accounts WHERE id=? AND deleted_at IS NOT NULL`
+ `if not ac or (ac["owner_id"] != user_id and not _cross_user_actor(user_id)):`，错误文案
`账户不存在或未被删除` 不变；其 `dashboard_name` 同样改用 `ac["owner_id"]`。

`accounts_permanent_delete`（`py/main.py:4389-4394`）同法：`SELECT account_id, owner_id FROM accounts WHERE id=? AND deleted_at IS NOT NULL`
+ 同一个 `if` 条件，错误文案 `账户不存在或未被删除` 不变。

`accounts_batch_delete`（`py/main.py:4336-4340`）把：

```python
        for aid in ids:
            db.execute(
                "UPDATE accounts SET deleted_at=datetime('now','localtime'), "
                "updated_at=datetime('now','localtime') WHERE id=? AND owner_id=? AND deleted_at IS NULL",
                (aid, user_id)
            )
```

改为：

```python
        cross_user = _cross_user_actor(user_id)
        owner_clause = "" if cross_user else " AND owner_id=?"
        for aid in ids:
            db.execute(
                "UPDATE accounts SET deleted_at=datetime('now','localtime'), "
                "updated_at=datetime('now','localtime') "
                f"WHERE id=?{owner_clause} AND deleted_at IS NULL",
                (aid,) if cross_user else (aid, user_id)
            )
```

**等价性核对（必须逐条成立，实现后自查）**：
- 非跨用户角色：`owner_clause == " AND owner_id=?"`、参数 `(aid, user_id)` —— SQL 文本与改动前**逐字节相同** ✅
- 户管 / developer / admin：`owner_clause == ""`、参数 `(aid,)` ✅
- **不改**该函数返回的 `deleted: len(ids)`（它本来就谎报条数，是既有缺陷，不在本需求范围）

- [ ] **Step 6: 改写 MCC 历史删除的角色白名单**

`accounts_mcc_history_delete`（`py/main.py:5289-5291`）把：

```python
    if not user or user["role"] not in ("developer", "admin"):
        return jsonify({"success": False, "error": "权限不足"}), 403
```

改为：

```python
    if not user or user["role"] not in CROSS_USER_ROLES:
        return jsonify({"success": False, "error": "权限不足"}), 403
```

（这是 GG 侧唯一一处用角色白名单而非归属校验的账户写操作；文案不变，仅把户管并入白名单。）

- [ ] **Step 7: 运行测试确认通过**

Run: `cd py && python -m pytest tests/test_huguan_role.py -v -k GgWriteOpsCrossUser`
Expected: 7 passed

- [ ] **Step 8: 放开前端 MCC 面板的编辑/删除按钮**

`frontend/src/views/MccPanel.vue:33` 把：

```vue
            <template v-if="row.is_owner">
```

改为：

```vue
            <template v-if="row.is_owner || auth.canManageAccounts">
```

在 `<script setup>` 中（`import { useAccountStore } from '@/stores/accounts'` 之后）加：

```js
import { useAuthStore } from '@/stores/auth'
```

并在 `const store = useAccountStore()` 之后加：

```js
const auth = useAuthStore()
```

**注意**：`row.is_owner` 是后端 `_mcc_to_dict` 按 `owner_id == 当前用户` 算出来的，**不要改后端去伪造 `is_owner`** ——
那会把 developer/admin 看到的、本当显示「共享」的行也变成「自己的」，属改动现有角色行为。
门槛放在前端：`is_owner`（自己的）**或** `canManageAccounts`（跨用户角色，Task 11 定义）。

- [ ] **Step 9: 跑全量后端测试 + 前端构建**

Run:
```bash
cd py && python -m pytest tests/ -v
cd ../frontend && npm run build
```
Expected: 后端全部 passed；前端 build 成功。

- [ ] **Step 10: 提交**

```bash
git add py/main.py py/tests/test_huguan_role.py frontend/src/views/MccPanel.vue
git commit -m "feat: GG 账户与 MCC 写操作对跨用户角色放行"
```

---

## 收尾

- [ ] **跑一次全量后端测试**：`cd py && python -m pytest tests/ -v` → 全部 passed
- [ ] **跑一次前端构建**：`cd frontend && npm run build` → 成功
- [ ] **按 CLAUDE.md 调用 `/code-review` 做代码审查**，修复发现的问题后再交付
- [ ] **端到端验收**：用一个新建的户管账号走一遍——登录 → 三平台切换 → 看/改他人账户 → 用用户下拉筛选 → 改设置选项 → 创建一个户管 → 停用该户管（确认进入**已禁用**，而不是被降级成「用户」）→ 再用角色下拉恢复为户管 → 确认开发者账号能管到它
- [ ] **产品域负向验收**（Task 17）：用户管 token 直接调 `POST /api/fb/products/create`、`PUT /api/fb/products/<pid>`、`POST /api/tt/products/create`、`POST /api/tt/products/import-text` → 四者均须 403；再确认户管调 `POST /api/tt/bcs/create` 仍为 200（未误伤账户域）
- [ ] **admin 不变量验收**（Task 1）：用 `platform='gg'` 的 admin token 调 `/api/tt/users?platform=tt` → 须 403（admin 不跨平台）
- [ ] **GG 写操作验收**（Task 18）：户管 token 调 `PUT /api/mcc/<别人的id>`、`DELETE /api/mcc/<别人的id>`、`DELETE /api/accounts/<别人的id>` → 三者均 200；换普通 user token 重试 → 403 / 403 / 404，且文案不变
