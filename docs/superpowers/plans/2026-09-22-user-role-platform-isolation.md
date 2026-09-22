# 用户角色平台隔离 实现计划

> **For agentic workers:** 按任务逐条实现。步骤用 `- [ ]` 勾选追踪。
> 设计文档：`docs/superpowers/specs/2026-09-22-user-role-platform-isolation-design.md`

**Goal:** 把用户管理（角色）权限从「全局」收紧为「按 platform 隔离」：非 developer 的管理员只能看到并操作自己平台的用户，developer 看/管全部。

**Architecture:** 复用现有 `users.platform` 字段做隔离维度，不改表结构、不改角色枚举。后端在「查询」（`list_users`）和「操作」（`_can_modify_user` + `admin_create_user`）两条链路加平台约束，`role == 'developer'` 短路豁免；前端按身份条件显示 Tab 和平台字段。

**Tech Stack:** Flask + SQLite（`py/`），Vue 3 + Element Plus（`frontend/`），pytest 集成测试。

## Global Constraints

- 纯增量：不修改原有功能的代码逻辑，只在原逻辑上增加平台约束。
- 空 platform 归一：所有平台比较统一 `(x.get("platform") or "gg")`。
- 权限边界由后端强制，前端隐藏只是体验。
- 测试运行：`cd py && python -m pytest tests/ -v`（从 `py/` 目录跑，避免本地 `py` 包遮蔽 pytest 依赖）。

---

## Task 1: 用户列表按平台隔离（`list_users`）

**Files:**
- Modify: `py/auth.py`（`list_users`，约第 60-109 行）
- Test: `py/tests/test_user_platform_isolation.py`（新建）

**Interfaces:**
- 消耗：`database.get_db()`、`current_user_id`（当前用户 id）、`platform`（可选筛选参数）。
- 产出：`list_users` 返回值结构不变 `{"users": [...], "total": int}`。

- [ ] **Step 1: 写失败测试**

新建 `py/tests/test_user_platform_isolation.py`：

```python
"""测试用户管理按平台（platform）隔离。"""
import database


def _create_user(client, username, role=None, platform=None):
    """注册用户并直接设置 role/platform，返回 headers。"""
    client.post("/api/auth/register", json={"username": username, "password": "test123"})
    db = database.get_db()
    db.execute("UPDATE users SET role=?, platform=? WHERE username=?",
               (role or "user", platform or "gg", username))
    db.commit()
    db.close()
    resp = client.post("/api/auth/login", json={"username": username, "password": "test123"})
    token = resp.get_json().get("access_token", "")
    return {"Authorization": f"Bearer {token}"}


class TestListUsersPlatformIsolation:
    def test_tt_admin_sees_only_tt_users(self, client):
        _create_user(client, "_iso_gg_user", role="user", platform="gg")
        _create_user(client, "_iso_tt_user", role="user", platform="tt")
        _create_user(client, "_iso_dev", role="developer", platform="gg")
        tt_admin = _create_user(client, "_iso_tt_admin", role="admin", platform="tt")

        resp = client.get("/api/admin/users", headers=tt_admin)
        data = resp.get_json()
        assert resp.status_code == 200
        platforms = {u["platform"] for u in data["users"]}
        assert platforms == {"tt"}
        roles = {u["role"] for u in data["users"]}
        assert "developer" not in roles

    def test_developer_sees_all_platforms(self, client):
        _create_user(client, "_iso2_gg", role="user", platform="gg")
        _create_user(client, "_iso2_tt", role="user", platform="tt")
        dev = _create_user(client, "_iso2_dev", role="developer", platform="gg")

        resp = client.get("/api/admin/users", headers=dev)
        data = resp.get_json()
        platforms = {u["platform"] for u in data["users"]}
        assert platforms >= {"gg", "tt"}

    def test_tt_admin_ignores_platform_param(self, client):
        _create_user(client, "_iso3_gg", role="user", platform="gg")
        _create_user(client, "_iso3_tt", role="user", platform="tt")
        tt_admin = _create_user(client, "_iso3_tt_admin", role="admin", platform="tt")

        resp = client.get("/api/admin/users?platform=gg", headers=tt_admin)
        data = resp.get_json()
        assert all(u["platform"] == "tt" for u in data["users"])
```

- [ ] **Step 2: 运行测试确认失败**

```bash
cd py && python -m pytest tests/test_user_platform_isolation.py -v
```
期望：`test_tt_admin_sees_only_tt_users` 和 `test_tt_admin_ignores_platform_param` 失败（当前列表不过滤 platform）。

- [ ] **Step 3: 修改 `list_users` 实现隔离**

将 `py/auth.py` 的 `list_users` 中「查询用户 + 过滤」部分改为：

```python
def list_users(search: str = "", page: int = 1, page_size: int = 20, current_user_id: int = None, platform: str = None) -> dict:
    """列出用户。非 developer 只看自己平台且看不到 developer；developer 看全部（可选按 platform 筛）。"""
    conn = database.get_db()
    try:
        is_dev = False
        my_platform = None
        if current_user_id:
            cur_user = conn.execute("SELECT role, platform FROM users WHERE id = ?", (current_user_id,)).fetchone()
            is_dev = cur_user and cur_user["role"] == "developer"
            my_platform = (cur_user["platform"] if cur_user else None) or "gg"

        filters = [""] if is_dev else ["role != 'developer'"]
        params = []

        if is_dev:
            if platform:
                filters.append("platform = ?")
                params.append(platform)
        else:
            filters.append("platform = ?")
            params.append(my_platform)

        base_where = " AND ".join(f for f in filters if f)
        where_clause = f" WHERE {base_where}" if base_where else ""

        SELECT_COLS = "id, username, role, display_name, created_at, last_login, created_by, telegram_username, platform"

        if search:
            like = f"%{search}%"
            search_clause = " AND (username LIKE ? OR display_name LIKE ?)"
            total = conn.execute(
                f"SELECT COUNT(*) as total FROM users{where_clause}{search_clause}",
                params + [like, like]
            ).fetchone()["total"]
            offset = (page - 1) * page_size
            rows = conn.execute(
                f"SELECT {SELECT_COLS} FROM users{where_clause}{search_clause} ORDER BY id DESC LIMIT ? OFFSET ?",
                params + [like, like, page_size, offset]
            ).fetchall()
        else:
            total = conn.execute(
                f"SELECT COUNT(*) as total FROM users{where_clause}",
                params
            ).fetchone()["total"]
            offset = (page - 1) * page_size
            rows = conn.execute(
                f"SELECT {SELECT_COLS} FROM users{where_clause} ORDER BY id DESC LIMIT ? OFFSET ?",
                params + [page_size, offset]
            ).fetchall()
        return {"users": [dict(r) for r in rows], "total": total}
    finally:
        conn.close()
```

- [ ] **Step 4: 运行测试确认通过**

```bash
cd py && python -m pytest tests/test_user_platform_isolation.py -v
```
期望：3 个用例全部 PASS。

- [ ] **Step 5: 回归全量测试**

```bash
cd py && python -m pytest tests/ -q
```

- [ ] **Step 6: Commit**

```bash
git add py/auth.py py/tests/test_user_platform_isolation.py
git commit -m "feat: 用户列表按平台隔离（非 developer 只看自己平台）"
```

---

## Task 2: 创建锁定平台 + 操作按平台隔离

**Files:**
- Modify: `py/main.py`（`admin_create_user` 约第 7406-7436 行；`_can_modify_user` 约第 7455-7459 行）
- Test: `py/tests/test_user_platform_isolation.py`（追加）

**Interfaces:**
- 消耗：`auth.get_user_by_id`（含 `platform` 字段）、`_can_modify_user(actor, target)`。
- 产出：`_can_modify_user` 返回 bool，被 role/toggle/delete/update/password/telegram 六接口复用。

- [ ] **Step 1: 追加失败测试**

在 `test_user_platform_isolation.py` 追加：

```python
class TestCreateUserPlatformLock:
    def test_tt_admin_creates_tt_user(self, client):
        tt_admin = _create_user(client, "_iso4_tt_admin", role="admin", platform="tt")
        resp = client.post("/api/admin/users/create", json={
            "username": "_iso4_new", "password": "test123", "role": "user", "platform": "gg",
        }, headers=tt_admin)
        assert resp.status_code == 200
        db = database.get_db()
        row = db.execute("SELECT platform FROM users WHERE username='_iso4_new'").fetchone()
        db.close()
        assert row["platform"] == "tt"

    def test_developer_can_set_any_platform(self, client):
        dev = _create_user(client, "_iso5_dev", role="developer", platform="gg")
        resp = client.post("/api/admin/users/create", json={
            "username": "_iso5_new", "password": "test123", "role": "user", "platform": "tt",
        }, headers=dev)
        assert resp.status_code == 200
        db = database.get_db()
        row = db.execute("SELECT platform FROM users WHERE username='_iso5_new'").fetchone()
        db.close()
        assert row["platform"] == "tt"


class TestModifyUserPlatformIsolation:
    def _setup(self, client):
        gg_user = _create_user(client, "_iso6_gg_user", role="user", platform="gg")
        tt_user = _create_user(client, "_iso6_tt_user", role="user", platform="tt")
        tt_admin = _create_user(client, "_iso6_tt_admin", role="admin", platform="tt")
        # 取 uid
        db = database.get_db()
        gg_uid = db.execute("SELECT id FROM users WHERE username='_iso6_gg_user'").fetchone()["id"]
        tt_uid = db.execute("SELECT id FROM users WHERE username='_iso6_tt_user'").fetchone()["id"]
        db.close()
        return gg_uid, tt_uid, tt_admin

    def test_tt_admin_cannot_modify_gg_user(self, client):
        gg_uid, _, tt_admin = self._setup(client)
        resp = client.post(f"/api/admin/users/{gg_uid}/role", json={"role": "viewer"}, headers=tt_admin)
        assert resp.status_code == 403

    def test_tt_admin_can_modify_tt_user(self, client):
        _, tt_uid, tt_admin = self._setup(client)
        resp = client.post(f"/api/admin/users/{tt_uid}/role", json={"role": "viewer"}, headers=tt_admin)
        assert resp.status_code == 200
```

- [ ] **Step 2: 运行测试确认失败**

```bash
cd py && python -m pytest tests/test_user_platform_isolation.py -v
```
期望：`test_tt_admin_creates_tt_user`（当前创建被强制 gg）、`test_tt_admin_cannot_modify_gg_user`（当前无平台判断）失败。

- [ ] **Step 3: 修改 `admin_create_user` 锁定平台**

将 `py/main.py` `admin_create_user` 中：

```python
    # 只有 developer 可以设置 platform
    if user["role"] != "developer" and platform != "gg":
        platform = "gg"
```

改为：

```python
    # 只有 developer 可以自由设置 platform；非 developer 锁定为自己的平台
    if user["role"] != "developer":
        platform = user.get("platform") or "gg"
```

- [ ] **Step 4: 修改 `_can_modify_user` 增加平台判断**

将 `py/main.py`：

```python
def _can_modify_user(actor: dict, target: dict) -> bool:
    """admin 只能操作 user/viewer/hidden，不能操作其他 admin。developer 不受限。"""
    if actor["role"] == "developer":
        return True
    return target["role"] in ("user", "viewer", "hidden")
```

改为：

```python
def _can_modify_user(actor: dict, target: dict) -> bool:
    """admin 只能操作 user/viewer/hidden，且仅限自己平台。developer 不受限。"""
    if actor["role"] == "developer":
        return True
    if target["role"] not in ("user", "viewer", "hidden"):
        return False
    if (actor.get("platform") or "gg") != (target.get("platform") or "gg"):
        return False
    return True
```

- [ ] **Step 5: 运行测试确认通过**

```bash
cd py && python -m pytest tests/test_user_platform_isolation.py -v
```
期望：全部 PASS。

- [ ] **Step 6: 回归全量测试**

```bash
cd py && python -m pytest tests/ -q
```

- [ ] **Step 7: Commit**

```bash
git add py/main.py py/tests/test_user_platform_isolation.py
git commit -m "feat: 用户创建/操作按平台隔离（admin 仅限自己平台）"
```

---

## Task 3: 前端用户管理页按平台显示

**Files:**
- Modify: `frontend/src/views/UserManageView.vue`

**Interfaces:**
- 消耗：`authStore.isDeveloper`、`authStore.user?.platform`、`authStore.effectivePlatform`。

- [ ] **Step 1: 平台 Tab 条件显示**

将模板中的平台 Tab（第 9-14 行）改为：

```vue
    <el-tabs v-model="platformFilter" @tab-change="onPlatformChange" style="margin-bottom:8px;">
      <el-tab-pane v-if="authStore.isDeveloper" label="全部" name="" />
      <el-tab-pane v-if="authStore.isDeveloper || authStore.effectivePlatform === 'gg'" label="GG" name="gg" />
      <el-tab-pane v-if="authStore.isDeveloper || authStore.effectivePlatform === 'fb'" label="FB" name="fb" />
      <el-tab-pane v-if="authStore.isDeveloper || authStore.effectivePlatform === 'tt'" label="TT" name="tt" />
    </el-tabs>
```

- [ ] **Step 2: `platformFilter` 初始值随身份**

将 `const platformFilter = ref('')` 改为：

```js
const platformFilter = ref(authStore.isDeveloper ? '' : (authStore.user?.platform || 'gg'))
```

- [ ] **Step 3: 创建弹窗隐藏平台字段**

将创建弹窗中的「平台」`el-form-item`（第 99-105 行）加 `v-if="authStore.isDeveloper"`：

```vue
        <el-form-item v-if="authStore.isDeveloper" label="平台">
          <el-select v-model="createForm.platform" style="width:100%">
            <el-option label="GG (Google Ads)" value="gg" />
            <el-option label="FB (Facebook)" value="fb" />
            <el-option label="TT (TikTok)" value="tt" />
          </el-select>
        </el-form-item>
```

- [ ] **Step 4: `createForm.platform` 初始值与重置随身份**

将 `createForm` 初始（第 276-282 行）与创建成功后重置（第 298 行）中的 `platform` 值改为按身份：

```js
const createForm = ref({
  username: "",
  password: "",
  display_name: "",
  role: "user",
  platform: authStore.isDeveloper ? 'gg' : (authStore.user?.platform || 'gg')
})
```

创建成功后重置同样改为：

```js
    createForm.value = { username: "", password: "", display_name: "", role: "user", platform: authStore.isDeveloper ? 'gg' : (authStore.user?.platform || 'gg') }
```

- [ ] **Step 5: 手动验证**

```bash
cd frontend && npm run dev
```
用 TT 管理员账号登录：用户管理页只显示「TT」一个 Tab；「创建用户」无平台字段，创建的用户平台为 tt；切换角色/改密/删除仅对自己平台的用户生效。用 developer 登录：四个 Tab 齐全，可自由选平台。

- [ ] **Step 6: Commit**

```bash
git add frontend/src/views/UserManageView.vue
git commit -m "feat: 用户管理页按平台显示 Tab 与创建选项"
```

---

## 完成后的代码审查

全部任务完成后，调用 `/code-review` 审查改动，修复发现的问题后再交付。
