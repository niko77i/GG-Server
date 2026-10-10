# 数据管理页开放给管理员/户管 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** GG 与 FB 两张数据管理页从「只看自己的数据」扩展到跨用户角色（户管 / 管理员）看**全部用户**的数据；**户管只能改「消耗」一个字段**（列表内联编辑），**管理员只读**（可导出、不能重试写表）；**普通 user 权限逐字不变**。

**Architecture:** 把「可见作用域」与「可改字段」两个判定抽到 `py/routes/helpers.py` 共用，GG 的 `/api/ad-reports/*` 与 FB 的 `/api/fb/reports/*` 都调同一份 —— 这样两边口径不可能漂移（FB 现有的「写接口已放宽、读接口没放宽」不一致会被顺带修掉）。前端按角色控制入口显隐，并给「消耗」列加内联编辑。

**Tech Stack:** Flask + SQLite（后端）、Vue 3 `<script setup>` + Element Plus（前端）、pytest。

**设计文档:** `docs/superpowers/specs/2026-10-11-report-data-permission-design.md`（已定案）

## Global Constraints

- **隔离轴是 `user_id`，不是 `owner_id`**：`ad_reports`（`py/database.py:584`）与 `fb_ad_reports`（`:924`）**都没有 `owner_id` 列**。**不要**照搬 `helpers.py` 那套按 owner 的 `scope_where` / `can_modify`。
- **普通 user 的行为必须逐字不变**：非跨用户角色走 `report_scope_where` 后拿到的仍是 `user_id = ?` + 自己 uid（与各端点原有写法**逐字等价**）。这是回归的硬判据。
- **管理员只读**：`report_editable_fields("admin")` 必须是空集 ⇒ 任何写端点对 admin 一律 **403**。
- **户管只能改 `cost`**：传了白名单外的字段 → **403**（不是静默忽略）。
- **`owner_uid`（「保存人」筛选）不得成为越权口**：非跨用户角色即使传了它，也**只返回自己的行**。
- **不碰** `py/routes/tt_accounts_routes.py`、TT 的任何端点、账户面板（`AdsAccountPanel.vue` 等）。
- **提交规范**：本仓库多会话共享工作区，**当前 `py/main.py`、`py/database.py`、`py/routes/tt_accounts_routes.py` 正被另一个会话改动**。
  - **禁用 `git add -A`**；只 pathspec 提交本任务列出的文件。
  - **提交前先 `git diff --stat -- <你的文件>` 确认改动都是你的**，若混入他人改动 → 停下报告，不要提交。
  - 新文件须先 `git add <文件>` 再 `git commit -- <同一文件>`（pathspec 提交对未跟踪的新文件会报 `did not match`）。
- **不推 origin。**

---

## 文件结构

| 文件 | 职责 | 改动 |
|---|---|---|
| `py/routes/helpers.py` | 路由层共用件 | 新增 3 个共用件 |
| `py/tests/test_report_scope.py` | 上述共用件的测试 | **新建** |
| `py/main.py` | GG 端点 | 6 处接入 |
| `py/routes/fb_routes.py` | FB 端点 | 7 处接入 + `_get_role` 改委派 |
| `py/tests/test_report_data_permission.py` | 端到端权限测试 | **新建** |
| `frontend/src/stores/auth.js` | 角色 getter | 加 3 个 getter |
| `frontend/src/components/AppSidebar.vue` | 户管导航 | 加入口 |
| `frontend/src/router/index.js` | 路由守卫 | 去掉 FB 对户管的拦截 |
| `frontend/src/views/DataManageView.vue` | GG 页 | 按角色显隐 + 内联编辑 + 保存人筛选 |
| `frontend/src/views/fb/FbDataManage.vue` | FB 页 | 同上 |

**依赖**：Task 1 → Task 2、3（并行）→ Task 4 → Task 5。

---

## Task 1: `helpers.py` 共用件

**Files:**
- Modify: `py/routes/helpers.py`（在 `CROSS_USER_ROLES` 附近加常量；在 `can_modify` 之后加两个函数）
- Test: `py/tests/test_report_scope.py`（新建）

**Interfaces:**
- Consumes: `CROSS_USER_ROLES`（`:5`）、`HUGUAN_ROLE`（`:2`）
- Produces:
  - `REPORT_VIEW_ALL_ROLES: tuple` = `CROSS_USER_ROLES`
  - `REPORT_COST_ONLY_ROLES: tuple` = `(HUGUAN_ROLE,)`
  - `user_role(db, uid) -> str`
  - `report_scope_where(role, uid, owner_uid=None, alias=None) -> (str, list)`
  - `report_editable_fields(role) -> set | None`

- [ ] **Step 1: 写失败测试**

创建 `py/tests/test_report_scope.py`：

```python
"""报表类资源的作用域与可改字段判定。

设计见 docs/superpowers/specs/2026-10-11-report-data-permission-design.md。
运行：cd py && python -m pytest tests/test_report_scope.py -v
"""
import pytest

import database
from routes.helpers import (
    report_scope_where, report_editable_fields, user_role,
    REPORT_VIEW_ALL_ROLES, REPORT_COST_ONLY_ROLES,
)


# ---------- 常量口径 ----------

def test_cost_only_roles_is_huguan_only():
    """**管理员不在其中** ⇒ 管理员只读。这是本设计最核心的一条。"""
    assert REPORT_COST_ONLY_ROLES == ("huguan",)
    assert "admin" not in REPORT_COST_ONLY_ROLES


def test_view_all_roles_reuses_cross_user_roles():
    assert REPORT_VIEW_ALL_ROLES == ("developer", "admin", "huguan")


# ---------- 作用域 ----------

@pytest.mark.parametrize("role", ["user", "viewer", "hidden", ""])
def test_non_cross_user_sees_only_self(role):
    """非跨用户角色 → 只看自己（与各端点原有写法逐字等价）。"""
    sql, params = report_scope_where(role, 42)
    assert sql == "user_id = ?"
    assert params == [42]


@pytest.mark.parametrize("role", ["developer", "admin", "huguan"])
def test_cross_user_sees_all(role):
    """跨用户角色 → 不加 user_id 限定（看全部）。"""
    sql, params = report_scope_where(role, 42)
    assert params == []
    assert "user_id" not in sql


@pytest.mark.parametrize("role", ["developer", "admin", "huguan"])
def test_cross_user_can_narrow_by_owner(role):
    """「保存人」筛选：跨用户角色传 owner_uid 就收窄到该人。"""
    sql, params = report_scope_where(role, 42, owner_uid=7)
    assert sql == "user_id = ?"
    assert params == [7]


@pytest.mark.parametrize("role", ["user", "viewer"])
def test_owner_uid_must_not_widen_non_cross_user(role):
    """**越权硬判据**：非跨用户角色即使传了 owner_uid，也只看自己。"""
    sql, params = report_scope_where(role, 42, owner_uid=7)
    assert sql == "user_id = ?"
    assert params == [42], "传 owner_uid 不得让普通用户看到别人的行"


def test_alias_is_prefixed():
    sql, _ = report_scope_where("user", 42, alias="r")
    assert sql == "r.user_id = ?"


# ---------- 可改字段 ----------

def test_developer_fields_is_none_meaning_no_whitelist():
    assert report_editable_fields("developer") is None


def test_huguan_can_only_edit_cost():
    assert report_editable_fields("huguan") == {"cost"}


@pytest.mark.parametrize("role", ["admin", "user", "viewer", "hidden", ""])
def test_others_are_readonly(role):
    assert report_editable_fields(role) == set()


# ---------- user_role ----------

def test_user_role_reads_db(app):
    db = database.get_db()
    try:
        db.execute("INSERT INTO users (username, password, role) VALUES (?,?,?)",
                   ("rs_probe", "x", "huguan"))
        db.commit()
        uid = db.execute("SELECT id FROM users WHERE username='rs_probe'").fetchone()["id"]
        assert user_role(db, uid) == "huguan"
    finally:
        db.close()


def test_user_role_unknown_uid_falls_back_to_user(app):
    db = database.get_db()
    try:
        assert user_role(db, 999999) == "user"
    finally:
        db.close()
```

- [ ] **Step 2: 跑测试确认失败**

```bash
cd py && python -m pytest tests/test_report_scope.py -q
```

预期：`ImportError: cannot import name 'report_scope_where'`

- [ ] **Step 3: 实现**

在 `py/routes/helpers.py` 的 `CROSS_USER_ROLES`（`:5`）之后追加常量：

```python
# 报表类资源（ad_reports / fb_ad_reports）：
# ⚠️ 这两张表**没有 owner_id 列**，归属轴是 **user_id（谁保存的这条）** ——
#    与账户类的 owner_id 不是一回事，**不能**套用本文件按 owner 的 scope_where / can_modify。
# 可跨用户查看报表数据的角色（与账户类同集合）。
REPORT_VIEW_ALL_ROLES = CROSS_USER_ROLES

# 在数据管理页**只能改「消耗」一个字段**的角色。
# ⚠️ admin **不在**其中 ⇒ 管理员只读（本设计最核心的一条，改动前请先读设计 §3）。
REPORT_COST_ONLY_ROLES = (HUGUAN_ROLE,)
```

在文件末尾（`can_modify` 之后）追加三个函数：

```python
def user_role(db, uid) -> str:
    """取用户角色，查不到回落 'user'（**不是 None** —— 调用方一律按"最低权限"处理）。

    FB 侧原有一个同义的 `_get_role`；本函数落地后它改为委派到这里，避免两份。
    """
    row = db.execute("SELECT role FROM users WHERE id=?", (uid,)).fetchone()
    return row["role"] if row else "user"


def report_scope_where(role, uid, owner_uid=None, alias=None):
    """报表类资源的可见作用域 → (SQL 片段, 参数列表)。

    - 非跨用户角色 → `user_id = ?` + [uid]（**与各端点原有写法逐字等价**）
    - 跨用户角色   → 不加 user_id 限定（看全部）；owner_uid 非空时收窄到该人
      （前端「保存人」筛选）

    ⚠️ **非跨用户角色即使传了 owner_uid 也只返回自己的行** —— 该参数不得成为越权口。
    """
    col = f"{alias}." if alias else ""
    if role in REPORT_VIEW_ALL_ROLES:
        if owner_uid is not None:
            return f"{col}user_id = ?", [owner_uid]
        return "1=1", []
    return f"{col}user_id = ?", [uid]


def report_editable_fields(role):
    """该角色在数据管理页可改的字段集合。**None = 不设白名单（全字段可改）**。

    - developer → None
    - 户管      → {"cost"}
    - 其余（含 **admin**）→ set() ⇒ 空集 = **只读**
    """
    if role == "developer":
        return None
    if role in REPORT_COST_ONLY_ROLES:
        return {"cost"}
    return set()
```

- [ ] **Step 4: 跑测试确认通过**

```bash
cd py && python -m pytest tests/test_report_scope.py -v
```

预期：全部 PASS

- [ ] **Step 5: 提交**

```bash
cd "D:/server/cc/GG-Server" && git diff --stat -- py/routes/helpers.py && git add py/routes/helpers.py py/tests/test_report_scope.py && git commit -m "feat(report-perm): helpers 加报表类资源的作用域与可改字段判定

ad_reports / fb_ad_reports **没有 owner_id**，归属轴是 user_id，故不套用
本文件按 owner 的 scope_where / can_modify，另立一对共用件：

- report_scope_where：非跨用户角色 → user_id = ?（与各端点原写法逐字等价）；
  跨用户角色 → 看全部，可用 owner_uid（保存人筛选）收窄。
  **非跨用户角色传 owner_uid 也只返回自己**（越权硬判据，有测试钉住）。
- report_editable_fields：developer → None（不设白名单）；
  户管 → {cost}；**其余含 admin → 空集（只读）**。
- user_role：取角色的单一来源（FB 的 _get_role 后续改为委派到这里）。" -- py/routes/helpers.py py/tests/test_report_scope.py
```

---

## Task 2: GG 端点接入

**Files:**
- Modify: `py/main.py`：`list`(`:10033`)、`export`(`:10153`)、`PUT <id>`(`:10216`)、`DELETE`(`:10268`)、`batch-delete`(`:10279`)、`save`(`:9900`)
- Test: `py/tests/test_report_data_permission.py`（新建，本任务写 GG 部分）

**Interfaces:**
- Consumes: Task 1 的 `report_scope_where` / `report_editable_fields` / `user_role`
- Produces: 无（端点行为）

- [ ] **Step 1: 写失败测试**

创建 `py/tests/test_report_data_permission.py`：

```python
"""数据管理页的跨用户权限（GG + FB）。

设计见 docs/superpowers/specs/2026-10-11-report-data-permission-design.md。
运行：cd py && python -m pytest tests/test_report_data_permission.py -v
"""
import pytest

import database

# ---------- 夹具 ----------

def _mk_user(client, username, role, platform="gg"):
    client.post("/api/auth/register", json={"username": username, "password": "test123"})
    db = database.get_db()
    db.execute("UPDATE users SET role=?, platform=? WHERE username=?", (role, platform, username))
    db.commit()
    uid = db.execute("SELECT id FROM users WHERE username=?", (username,)).fetchone()["id"]
    db.close()
    resp = client.post("/api/auth/login", json={"username": username, "password": "test123"})
    assert resp.status_code == 200, resp.get_json()
    tok = resp.get_json().get("access_token", "")
    assert tok, "登录未返回 token"
    return {"Authorization": f"Bearer {tok}"}, uid


def _mk_report(uid, product="P1", date="2026-10-01", cost=10.0, campaign="C1"):
    db = database.get_db()
    db.execute(
        "INSERT INTO ad_reports (user_id, product_name, region, report_date, customer_id, "
        "campaign, cost) VALUES (?,?,?,?,?,?,?)",
        (uid, product, "R", date, "cust1", campaign, cost))
    db.commit()
    rid = db.execute("SELECT id FROM ad_reports ORDER BY id DESC LIMIT 1").fetchone()["id"]
    db.close()
    return rid


@pytest.fixture
def three(client):
    """三个账号：普通 user / 户管 / 管理员，各造一条自己的 GG 报表。"""
    user_h, user_uid = _mk_user(client, "perm_user", "user")
    hug_h, hug_uid = _mk_user(client, "perm_hug", "huguan")
    adm_h, adm_uid = _mk_user(client, "perm_adm", "admin")
    user_rid = _mk_report(user_uid, cost=11.0)
    hug_rid = _mk_report(hug_uid, cost=22.0)
    adm_rid = _mk_report(adm_uid, cost=33.0)
    return {
        "user": (user_h, user_uid, user_rid),
        "huguan": (hug_h, hug_uid, hug_rid),
        "admin": (adm_h, adm_uid, adm_rid),
    }


def _items(client, headers, **params):
    r = client.get("/api/ad-reports/list", headers=headers, query_string=params)
    assert r.status_code == 200, r.get_data(as_text=True)[:300]
    return r.get_json()["data"]


# ---------- GG：可见范围 ----------

def test_gg_plain_user_still_sees_only_self(client, three):
    """**回归硬判据**：普通用户的行为与改动前逐字一致。"""
    h, uid, _ = three["user"]
    got = _items(client, h)
    assert len(got) == 1
    assert got[0]["cost"] == 11.0


def test_gg_huguan_sees_all(client, three):
    h, _, _ = three["huguan"]
    assert len(_items(client, h)) == 3, "户管应看到全部用户的数据"


def test_gg_admin_sees_all(client, three):
    h, _, _ = three["admin"]
    assert len(_items(client, h)) == 3, "管理员应看到全部用户的数据"


def test_gg_owner_filter_narrows_for_cross_user(client, three):
    """「保存人」筛选：跨用户角色传 user_id 只拿到该人的行。"""
    h, _, _ = three["huguan"]
    _, user_uid, _ = three["user"]
    got = _items(client, h, user_id=user_uid)
    assert len(got) == 1 and got[0]["cost"] == 11.0


def test_gg_owner_filter_cannot_widen_plain_user(client, three):
    """**越权硬判据**：普通用户传别人的 user_id 也只看自己。"""
    h, _, _ = three["user"]
    _, hug_uid, _ = three["huguan"]
    got = _items(client, h, user_id=hug_uid)
    assert len(got) == 1 and got[0]["cost"] == 11.0, "owner 筛选不得让普通用户看到别人的行"


# ---------- GG：写权限 ----------

def test_gg_huguan_can_edit_cost_of_others_row(client, three):
    h, _, _ = three["huguan"]
    _, user_uid, user_rid = three["user"]
    r = client.put(f"/api/ad-reports/{user_rid}", json={"cost": 99.5}, headers=h)
    assert r.status_code == 200, r.get_data(as_text=True)[:300]
    db = database.get_db()
    got = db.execute("SELECT cost FROM ad_reports WHERE id=?", (user_rid,)).fetchone()["cost"]
    db.close()
    assert got == 99.5


def test_gg_huguan_cannot_edit_other_fields(client, three):
    """**白名单外字段 → 403**（不是静默忽略）。"""
    h, _, _ = three["huguan"]
    _, _, user_rid = three["user"]
    for payload in ({"campaign": "改过的"}, {"cost": 1.0, "campaign": "改过的"},
                    {"region": "XX"}, {"report_date": "2030-01-01"}):
        r = client.put(f"/api/ad-reports/{user_rid}", json=payload, headers=h)
        assert r.status_code == 403, f"{payload} 应被拒，实际 {r.status_code}"


def test_gg_admin_cannot_edit_anything(client, three):
    h, _, _ = three["admin"]
    _, _, user_rid = three["user"]
    for payload in ({"cost": 1.0}, {"campaign": "x"}):
        assert client.put(f"/api/ad-reports/{user_rid}", json=payload, headers=h).status_code == 403


def test_gg_admin_and_huguan_cannot_delete(client, three):
    for who in ("admin", "huguan"):
        h, _, own_rid = three[who]
        assert client.delete(f"/api/ad-reports/{own_rid}", headers=h).status_code == 403, who
        r = client.post("/api/ad-reports/batch-delete", json={"ids": [own_rid]}, headers=h)
        assert r.status_code == 403, who


def test_gg_admin_and_huguan_cannot_create(client, three):
    payload = {"product_name": "P1", "report_date": "2026-10-01", "region": "R",
               "records": [{"campaign": "C9", "cost": 1}]}
    for who in ("admin", "huguan"):
        h, _, _ = three[who]
        assert client.post("/api/ad-reports/save", json=payload, headers=h).status_code == 403, who


def test_gg_export_allowed_for_admin_and_huguan(client, three):
    for who in ("admin", "huguan"):
        h, _, _ = three[who]
        assert client.get("/api/ad-reports/export", headers=h).status_code == 200, who


def test_gg_plain_user_write_paths_unchanged(client, three):
    """普通用户对自己行的增删改仍是 200（回归）。"""
    h, _, own_rid = three["user"]
    assert client.put(f"/api/ad-reports/{own_rid}", json={"cost": 5.0}, headers=h).status_code == 200
    assert client.delete(f"/api/ad-reports/{own_rid}", headers=h).status_code == 200
```

- [ ] **Step 2: 跑测试确认失败**

```bash
cd py && python -m pytest tests/test_report_data_permission.py -q -k gg
```

预期：`test_gg_huguan_sees_all` / `test_gg_admin_sees_all` / 白名单相关用例 FAIL（户管/管理员现在只看得到自己的 1 行；写端点还没收紧）

- [ ] **Step 3: 接入 GG 端点**

在 `py/main.py` 顶部 import 区补（若已有则跳过）：

```python
from routes.helpers import report_scope_where, report_editable_fields, user_role
```

**① `list`（`:10033`）与 ② `export`（`:10153`）** —— 两个端点的上下文**逐字同形**（都已确认：`user_id = int(get_jwt_identity())`、`db = _yt_db()`），且要改的都是这一行：
```python
    where = ["user_id=?"]; params = [user_id]
```
改成：
```python
    # 报表类资源没有 owner_id，归属轴是 user_id（见设计 §2.3）。
    _role = user_role(db, user_id)
    _owner_uid = request.args.get("user_id", type=int)
    _scope_sql, _scope_params = report_scope_where(_role, user_id, _owner_uid)
    where = [_scope_sql]; params = list(_scope_params)
```
> 两处都要改（`list` 与 `export`）。变量名 `db` / `user_id` 两边一致，可逐字套用。

**③ `PUT <id>`（`:10216`）** —— 现在的所有权校验是：
```python
        "SELECT id FROM ad_reports WHERE id=? AND user_id=?",
```
改成先按角色取字段白名单、并放宽归属：

```python
    _role = user_role(db, user_id)
    _editable = report_editable_fields(_role)
    if _editable is not None and not set(data.keys()) <= _editable:
        return err("无权限：仅可修改消耗", 403)
    if _editable == set():
        return err("无权限：只读角色不可修改数据", 403)
```
并把那句 `SELECT id FROM ad_reports WHERE id=? AND user_id=?` 改为：

```python
        # 跨用户角色（developer/户管）可改他人的行；其余仍限自己。
        if _role in REPORT_VIEW_ALL_ROLES:
            _row = db.execute("SELECT id FROM ad_reports WHERE id=?", (report_id,)).fetchone()
        else:
            _row = db.execute("SELECT id FROM ad_reports WHERE id=? AND user_id=?",
                              (report_id, user_id)).fetchone()
```
（`REPORT_VIEW_ALL_ROLES` 一并加进那行 import。）

**④ `DELETE`（`:10268`）与 ⑤ `batch-delete`（`:10279`）** —— 两处都在函数体开头加：

```python
    _role = user_role(db, user_id)
    if _role in REPORT_COST_ONLY_ROLES or _role == "admin":
        return err("无权限：只读角色不可删除数据", 403)
```
（`REPORT_COST_ONLY_ROLES` 一并 import。）**developer 不在其中 ⇒ 仍可删**（Developer 全权）。其余 SQL 不动 —— 非跨用户角色走的还是原来的 `AND user_id=?`。

**⑥ `save`（`:9900`）** —— 函数体开头加同款守卫（文案改「不可新增数据」）。

- [ ] **Step 4: 跑测试确认通过**

```bash
cd py && python -m pytest tests/test_report_data_permission.py -v -k gg
```

预期：GG 部分全部 PASS

- [ ] **Step 5: 提交**

```bash
cd "D:/server/cc/GG-Server" && git diff --stat -- py/main.py && git add py/main.py py/tests/test_report_data_permission.py && git commit -m "feat(report-perm): GG 数据管理端点接入跨用户作用域与可改字段

list/export 走 report_scope_where ⇒ 户管/管理员看全部、普通 user 不变；
PUT 放宽归属 + 叠字段白名单（户管仅 cost，白名单外 → 403；admin 只读）；
DELETE/batch-delete/save 对 admin 与户管 → 403（developer 仍全权）。" -- py/main.py py/tests/test_report_data_permission.py
```

---

## Task 3: FB 端点接入

**Files:**
- Modify: `py/routes/fb_routes.py`：`list`(`:2188`)、`stats`(`:2319`)、`export`(`:2466`)、`PUT <rid>`(`:2226`)、`DELETE`(`:2254`)、`batch-delete`(`:2270`)、`retry-sync`(`:2076`)、`_get_role`(`:2534`)
- Test: `py/tests/test_report_data_permission.py`（追加 FB 部分）

**Interfaces:**
- Consumes: Task 1 的三个共用件
- Produces: 无

- [ ] **Step 1: 追加 FB 测试**

在 `py/tests/test_report_data_permission.py` 末尾追加（**复用同一份夹具风格**，但 FB 需要 platform='fb' 的账号，且报表表是 `fb_ad_reports`）：

```python
# ---------- FB ----------

def _mk_fb_user(client, username, role):
    return _mk_user(client, username, role, platform="fb")


def _mk_fb_report(uid, product="P1", line="L1", date="2026-10-01", cost=10.0, aid="accX"):
    db = database.get_db()
    db.execute(
        "INSERT INTO fb_ad_reports (user_id, product_name, line_name, report_date, "
        "account_name, account_id, cost) VALUES (?,?,?,?,?,?,?)",
        (uid, product, line, date, "n-" + aid, aid, cost))
    db.commit()
    rid = db.execute("SELECT id FROM fb_ad_reports ORDER BY id DESC LIMIT 1").fetchone()["id"]
    db.close()
    return rid


@pytest.fixture
def fb_three(client):
    u_h, u_uid = _mk_fb_user(client, "fperm_user", "user")
    g_h, g_uid = _mk_fb_user(client, "fperm_hug", "huguan")
    a_h, a_uid = _mk_fb_user(client, "fperm_adm", "admin")
    return {
        "user": (u_h, u_uid, _mk_fb_report(u_uid, aid="u1", cost=11.0)),
        "huguan": (g_h, g_uid, _mk_fb_report(g_uid, aid="g1", cost=22.0)),
        "admin": (a_h, a_uid, _mk_fb_report(a_uid, aid="a1", cost=33.0)),
    }


def _fb_items(client, headers, **params):
    r = client.get("/api/fb/reports/list", headers=headers, query_string=params)
    assert r.status_code == 200, r.get_data(as_text=True)[:300]
    return r.get_json()


def test_fb_plain_user_still_sees_only_self(client, fb_three):
    h, _, _ = fb_three["user"]
    body = _fb_items(client, h)
    rows = body.get("data") or body.get("items") or body.get("reports")
    assert rows is not None, f"list 返回结构变了：{list(body)}"
    assert len(rows) == 1


@pytest.mark.parametrize("who", ["huguan", "admin"])
def test_fb_cross_user_sees_all(client, fb_three, who):
    h, _, _ = fb_three[who]
    body = _fb_items(client, h)
    rows = body.get("data") or body.get("items") or body.get("reports")
    assert len(rows) == 3, f"{who} 应看到全部"


def test_fb_owner_filter_cannot_widen_plain_user(client, fb_three):
    h, _, _ = fb_three["user"]
    _, hug_uid, _ = fb_three["huguan"]
    body = _fb_items(client, h, user_id=hug_uid)
    rows = body.get("data") or body.get("items") or body.get("reports")
    assert len(rows) == 1, "owner 筛选不得让普通用户看到别人的行"


def test_fb_huguan_can_edit_cost(client, fb_three):
    h, _, _ = fb_three["huguan"]
    _, _, u_rid = fb_three["user"]
    r = client.put(f"/api/fb/reports/{u_rid}", json={"cost": 77.0}, headers=h)
    assert r.status_code == 200, r.get_data(as_text=True)[:300]


def test_fb_huguan_cannot_edit_other_fields(client, fb_three):
    """**现存行为被收窄**：户管此前能改整行，现在只剩 cost。"""
    h, _, _ = fb_three["huguan"]
    _, _, u_rid = fb_three["user"]
    for payload in ({"line_name": "L9"}, {"cost": 1.0, "line_name": "L9"}):
        assert client.put(f"/api/fb/reports/{u_rid}", json=payload, headers=h).status_code == 403


def test_fb_admin_readonly(client, fb_three):
    """**现存行为被收紧**：FB 的写接口此前对 admin 开放。"""
    h, _, own = fb_three["admin"]
    _, _, u_rid = fb_three["user"]
    assert client.put(f"/api/fb/reports/{u_rid}", json={"cost": 1.0}, headers=h).status_code == 403
    assert client.delete(f"/api/fb/reports/{own}", headers=h).status_code == 403
    assert client.post("/api/fb/reports/batch-delete", json={"ids": [own]}, headers=h).status_code == 403
    assert client.post("/api/fb/reports/retry-sync",
                       json={"groups": [["P1", "L1", "2026-10-01"]]}, headers=h).status_code == 403


def test_fb_huguan_cannot_delete(client, fb_three):
    h, _, own = fb_three["huguan"]
    assert client.delete(f"/api/fb/reports/{own}", headers=h).status_code == 403
    assert client.post("/api/fb/reports/batch-delete", json={"ids": [own]}, headers=h).status_code == 403


def test_fb_export_allowed_for_cross_user(client, fb_three):
    for who in ("admin", "huguan"):
        h, _, _ = fb_three[who]
        assert client.get("/api/fb/reports/export", headers=h).status_code == 200, who
```

> **若 `list` 的返回结构不是 `data`/`items`/`reports`**，按实际结构调整 `_fb_items` 里那行三元表达式，并在报告里写明实际键名 —— **不要去改端点返回结构**。

- [ ] **Step 2: 跑测试确认失败**

```bash
cd py && python -m pytest tests/test_report_data_permission.py -q -k fb
```

预期：`test_fb_cross_user_sees_all` 与两条收紧用例 FAIL

- [ ] **Step 3: 接入 FB 端点**

**① `_get_role`（`:2534`）改为委派**：
```python
def _get_role(db, uid):
    """取用户角色 —— 委派到共用的 `helpers.user_role`（避免两份口径漂移）。"""
    return user_role(db, uid)
```
并在该文件 import 区补：
```python
from routes.helpers import report_scope_where, report_editable_fields, user_role, REPORT_VIEW_ALL_ROLES, REPORT_COST_ONLY_ROLES
```

**② `list`（`:2188`）、③ `stats`（`:2319`）、④ `export`（`:2466`）** —— 三处都是：
```python
    where = ["user_id = ?"]
    params = [uid]
```
改成：
```python
    _role = _get_role(db, uid)
    _scope_sql, _scope_params = report_scope_where(_role, uid,
                                                   request.args.get("user_id", type=int))
    where = [_scope_sql]
    params = list(_scope_params)
```

**⑤ `PUT <rid>`（`:2226`）** —— 现有归属校验（`:2236`）保留（跨用户角色放行已经有了），**在它之前**插入字段白名单：
```python
    _role = _get_role(db, uid)
    _editable = report_editable_fields(_role)
    if _editable is not None and not set(data.keys()) <= _editable:
        return err("无权限：仅可修改消耗", 403)
    if _editable == set():
        return err("无权限：只读角色不可修改数据", 403)
```

**⑥ `DELETE`（`:2254`）与 ⑦ `batch-delete`（`:2270`）** —— 函数体开头加：
```python
    _role = _get_role(db, uid)
    if _role in REPORT_COST_ONLY_ROLES or _role == "admin":
        return err("无权限：只读角色不可删除数据", 403)
```
**并把原有的 `CROSS_USER_ROLES` 放宽去掉**（developer 之外不再跨用户删）：把
```python
    if row and _get_role(db, uid) not in CROSS_USER_ROLES and row["user_id"] != uid:
```
改为
```python
    if row and _role not in ("developer",) and row["user_id"] != uid:
```
（`batch-delete` 里那句「跨用户角色 DELETE 不限 owner」的分支同样只留给 developer。）

**⑧ `retry-sync`（`:2076`）** —— 函数体开头加：
```python
    if _get_role(db, uid) == "admin":
        return err("无权限：管理员不可重试写表", 403)
```

- [ ] **Step 4: 跑测试确认通过**

```bash
cd py && python -m pytest tests/test_report_data_permission.py tests/test_report_scope.py -v
```

预期：全部 PASS

- [ ] **Step 5: 跑全量确认没碰坏别的**

```bash
cd py && python -m pytest tests/ -q
```

预期：无新增失败（约 2000 用例、**约 11 分钟**，耐心等）

- [ ] **Step 6: 提交**

```bash
cd "D:/server/cc/GG-Server" && git diff --stat -- py/routes/fb_routes.py && git add py/routes/fb_routes.py py/tests/test_report_data_permission.py && git commit -m "feat(report-perm): FB 数据管理端点接入同一份判定

list/stats/export 走 report_scope_where ⇒ 户管/管理员看全部、普通 user 不变；
PUT 叠字段白名单（户管仅 cost，白名单外 403；admin 只读）；
DELETE/batch-delete 收窄到 developer（户管与 admin → 403）；retry-sync 对 admin → 403。

顺带修掉一处现存不一致：读写此前判据不同（写已放宽、读没放宽），
户管/管理员能改自己看不见的行；现两边同源。
_get_role 改为委派 helpers.user_role，避免两份角色判定漂移。" -- py/routes/fb_routes.py py/tests/test_report_data_permission.py
```

---

## Task 4: 前端 —— 按角色控制 + 内联编辑 + 保存人筛选

**Files:**
- Modify: `frontend/src/stores/auth.js`、`frontend/src/components/AppSidebar.vue`、`frontend/src/router/index.js`、`frontend/src/views/DataManageView.vue`、`frontend/src/views/fb/FbDataManage.vue`
- 设计文档附录：`docs/superpowers/specs/2026-10-11-report-data-permission-design.md`

**Interfaces:**
- Consumes: Task 1–3 的后端行为（跨用户列表、cost-only 写、admin 只读）
- Produces: 无

- [ ] **Step 1: 先调 `/frontend-design`（项目规范硬性要求）**

本任务含**新增 UI**（内联编辑入口、按角色显隐、「保存人」筛选控件）。**动组件之前必须先调 `frontend-design` 技能**。

给设计的输入：
1. **沿用两页既有的 Element Plus 形态**，不另起一套视觉（GG 页与 FB 页风格本就相近）
2. **「消耗」列的内联编辑**：照 `AdsAccountPanel.vue` 的既有范式（点 ✏️ → 输入框 → 回车/失焦保存；失败有提示），只对**户管**出现
3. **按角色显隐**：非 owner 角色不渲染「新增 / 删除 / 批量删除」；**管理员连内联编辑的 ✏️ 都不出现**
4. **「保存人」筛选**：仅跨用户角色可见的下拉（放在现有筛选栏里），文案与既有的「产品/日期」筛选一致
5. 只读角色（管理员）的界面要让人**一眼看出是只读**（而不是点了才被拒）

把产出记入设计文档末尾新增的 `## 附录：数据管理页视觉决策`（**不改既有结论章节**）。

- [ ] **Step 2: auth store 加 getter**

`frontend/src/stores/auth.js` 的 getters 里（紧跟 `canManageAccounts` 之后）加：

```js
    // 报表数据（数据管理页）的权限。与后端 helpers.report_editable_fields 同口径：
    // developer → 全权；户管 → 仅可改「消耗」；其余（含 admin）→ 只读。
    canEditReportCost: (s) => s.user?.role === 'huguan',
    canManageReports: (s) => s.user?.role === 'developer',
    canFilterReportOwner: (s) => ['developer', 'admin', 'huguan'].includes(s.user?.role),
```

- [ ] **Step 3: 户管侧边栏加入口**

`frontend/src/components/AppSidebar.vue`：给 `huguanNavItems`（GG 版）与 `huguanFbNavItems` 各加一个「数据管理」项。**照抄同文件里已有项的结构**（`key` / `icon` / `label` / `sections[].items[]` 的 `icon`+`label`+`path`）：

- GG 户管导航 → `path: '/data-manage'`
- FB 户管导航 → `path: '/fb/data-manage'`

（**注意**：`huguanNavItems` 里现有项的 `key` 命名风格照抄邻近项；TT 的户管导航**不要**加 —— TT 没有这个页面。）

- [ ] **Step 4: 去掉 FB 对户管的路由拦截**

`frontend/src/router/index.js` 约 `:236-239` 有一处把户管从 `/fb/data-manage` 重定向走。**删除该重定向**（让户管能进）。删完确认 GG 的 `/data-manage` 对户管本来就放行（无对应拦截）。

- [ ] **Step 5: 两页按角色改造**

`frontend/src/views/DataManageView.vue` 与 `frontend/src/views/fb/FbDataManage.vue`，**改动同构**：

1. **按角色显隐**（模板上加 `v-if`，沿用两页现有的按钮结构）：
   - 「新增」：`v-if="auth.canManageReports"`（FB 页没有新增，跳过）
   - 「删除」「批量删除」：`v-if="auth.canManageReports"`
   - **管理员/户管**：这些按钮一律不渲染
2. **「消耗」列内联编辑**（`v-if="auth.canEditReportCost"`）：
   - 照 `AdsAccountPanel.vue` 的 `.inline-edit-cell` / `.inline-edit-btn` 范式
   - 保存时**只发 `{ cost: <数字> }`**（其余字段一律不带 —— 后端会拒白名单外的字段）
3. **「保存人」筛选**（`v-if="auth.canFilterReportOwner"`）：
   - 一个下拉，选项来自 **`GET /api/platform/users`**（`OwnerFilterSelect.vue:53` 用的就是它，照抄那个调用形态即可；不要新造接口）
   - 选中后把 `user_id` 加进 list 请求参数
   - **未选中 = 不传该参数**（跨用户角色即看全部）
   - **普通 user 不渲染这个下拉**（后端即使被塞了 `user_id` 也只返回他自己的行，但前端不该给出误导性的入口）

- [ ] **Step 6: 起前端验证（需后端）**

```bash
cd frontend && npm run build && npm run dev
```

**起服务前先问协调者**（用户约定：起进程前必须先问）。

逐角色核对：普通 user 的两页与改动前**完全一致**；户管能看到全部数据、能内联改消耗、看不到新增/删除、有保存人筛选；管理员能看到全部、**一个都改不了**、有保存人筛选。

- [ ] **Step 7: 提交**

```bash
cd "D:/server/cc/GG-Server" && git add frontend/src/stores/auth.js frontend/src/components/AppSidebar.vue frontend/src/router/index.js frontend/src/views/DataManageView.vue frontend/src/views/fb/FbDataManage.vue docs/superpowers/specs/2026-10-11-report-data-permission-design.md && git commit -m "feat(report-perm): 数据管理页按角色控制入口 + 消耗内联编辑 + 保存人筛选

户管侧边栏补入口、去掉 FB 的路由拦截；非 owner 角色不渲染新增/删除/批量删除；
户管可内联改消耗（只发 cost 一个字段）；跨用户角色可见「保存人」筛选；
管理员界面一眼可见只读。视觉按 /frontend-design 产出。" -- frontend/src/stores/auth.js frontend/src/components/AppSidebar.vue frontend/src/router/index.js frontend/src/views/DataManageView.vue frontend/src/views/fb/FbDataManage.vue docs/superpowers/specs/2026-10-11-report-data-permission-design.md
```

---

## Task 5: 端到端验收 + 代码审查

**Files:** 无新增；可能按审查意见回头改

- [ ] **Step 1: 逐条跑验收清单**

| # | 操作 | 期望 |
|---|---|---|
| 1 | 普通 user 进两页 | 与改动前**完全一致**（只看自己、能增删改自己的） |
| 2 | 户管进两页 | 看到**全部用户**的行；有「保存人」筛选；**无**新增/删除/批量删除；「消耗」可内联编辑 |
| 3 | 户管改一行的消耗 | 落库成功；刷新后仍在 |
| 4 | 户管改别的字段（构造请求） | **403**，前端有提示 |
| 5 | 管理员进两页 | 看到全部；**没有任何可写入口**；有保存人筛选；导出可用 |
| 6 | 管理员调写接口（构造请求） | **403**（前端藏了按钮，后端也必须拒） |
| 7 | 户管/管理员删行、批量删、「新增」 | **403** |
| 8 | 「保存人」筛选选中某人 | 只剩该人的行 |
| 9 | 普通 user 构造 `?user_id=<别人>` | **仍只看自己**（越权硬判据） |
| 10 | developer | 全权不变 |

- [ ] **Step 2: 跑全量**

```bash
cd py && python -m pytest tests/ -q
cd ../frontend && npm run build && npm test
```

- [ ] **Step 3: 调 `/code-review`**

本次改动触及**权限与数据归属**（项目规范要求必须审查）。重点请审查者关注：
- `report_scope_where` 的**非跨用户分支**是否与各端点原写法逐字等价（普通 user 不得被放宽）
- `owner_uid` 是否在任何路径上成为**越权口**
- 白名单校验是否**覆盖了所有写入口**（漏掉任一个端点 = 户管/管理员能绕过）
- FB 侧删掉 `CROSS_USER_ROLES` 放宽后，**developer 的路径是否仍然通畅**

- [ ] **Step 4: 修完重跑 Step 1-2**

- [ ] **Step 5: 更新设计文档状态**为「已实现」

---

## 附：验收判据汇总

- [ ] `tests/test_report_scope.py` 与 `tests/test_report_data_permission.py` 全绿
- [ ] **普通 user 的 list/export/update/delete 行为与改动前逐字一致**（有专门用例）
- [ ] 户管看全部、**只能改 cost**、不能增删
- [ ] 管理员看全部、**任何写都 403**（前端藏按钮 + 后端拒）
- [ ] `?user_id=` 对普通 user **不越权**
- [ ] 全量 pytest 无新增失败
- [ ] `/frontend-design` 已调用且产出记入设计文档附录
- [ ] `/code-review` 已执行，问题已修复并重跑验收
