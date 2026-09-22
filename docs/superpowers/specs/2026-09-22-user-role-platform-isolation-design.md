# 用户角色平台隔离 设计文档

> 日期：2026-09-22
> 状态：待确认

## 一、需求描述

优化用户管理（角色）功能的权限范围，把「管理员」从**全局**改为**按平台（系统）隔离**：

1. **平台隔离**：不同系统的管理员只能看到、只能操作自己所属平台（`platform`）的用户。GG 管理员只看/管 GG 用户，TT 管理员只看/管 TT 用户，FB 同理。
2. **开发者例外**：只有 `developer` 角色可以看到全部、操作全部，不受平台限制。
3. **创建锁定平台**：TT 管理员创建用户时，`platform` 锁定为 `tt`（当前实现是「非 developer 一律强制 `gg`」，这是错误的，需改为「强制为当前管理员自己的平台」）。
4. **前端 Tab**：用户管理页顶部「全部/GG/FB/TT」四个 Tab，非开发者只显示自己平台的 Tab。
5. **角色等级**：非开发者管理员仍可在自己平台内创建/提升「管理员」角色（保持现状能力），只是平台锁定。

## 二、现状分析

### 数据模型（`users` 表）
- `role`：`developer` / `admin` / `user` / `viewer` / `hidden`（全局角色）
- `platform`：`gg` / `fb` / `tt`（`TEXT DEFAULT 'gg'`，见 `database.py:410`）

### 现有逻辑（问题所在）

| 位置 | 现状 | 问题 |
|------|------|------|
| [auth.py:60-109](py/auth.py#L60-L109) `list_users` | 非 developer 仅过滤 `role != 'developer'`，**不过滤 platform** | 管理员能看到所有平台的用户 |
| [main.py:7406-7436](py/main.py#L7406-L7436) `admin_create_user` | 非 developer 创建用户时 `platform != 'gg'` 一律强制为 `gg` | TT 管理员创建用户会被强制成 gg，错误 |
| [main.py:7455-7459](py/main.py#L7455-L7459) `_can_modify_user` | admin 只能操作 `user/viewer/hidden`，**无平台判断** | 管理员能改角色/改密/删除其他平台的用户 |
| [UserManageView.vue:9-14](frontend/src/views/UserManageView.vue#L9-L14) | 平台 Tab 固定显示「全部/GG/FB/TT」 | 非开发者能看到其他平台 Tab |

## 三、技术方案

核心思路：**复用现有 `platform` 字段作为隔离维度**，不改表结构、不改角色枚举，只在「查询」和「操作」两条链路各加一处平台约束，由 `developer` 短路豁免。

### 3.1 后端

#### 改动 1：`auth.list_users` — 列表按平台隔离

非 developer 时，忽略传入的 `platform` 筛选参数，强制只看自己的平台。

```python
def list_users(search="", page=1, page_size=20, current_user_id=None, platform=None):
    conn = database.get_db()
    try:
        is_dev = False
        my_platform = None
        if current_user_id:
            cur_user = conn.execute(
                "SELECT role, platform FROM users WHERE id = ?", (current_user_id,)
            ).fetchone()
            is_dev = cur_user and cur_user["role"] == "developer"
            my_platform = (cur_user["platform"] if cur_user else None) or "gg"

        filters = [""] if is_dev else ["role != 'developer'"]
        params = []

        if is_dev:
            # developer 保持原行为：可选按 platform 筛选，None = 全部
            if platform:
                filters.append("platform = ?")
                params.append(platform)
        else:
            # 非 developer 强制只看自己平台
            filters.append("platform = ?")
            params.append(my_platform)

        base_where = " AND ".join(f for f in filters if f)
        # ... 后续查询不变
```

#### 改动 2：`admin_create_user` — 创建时平台锁定为自己的平台

```python
    # 只有 developer 可以自由设置 platform；非 developer 锁定为自己的平台
    if user["role"] != "developer":
        platform = (user.get("platform") or "gg")
```

（替换现有 `if user["role"] != "developer" and platform != "gg": platform = "gg"`）

#### 改动 3：`_can_modify_user` — 操作时增加平台隔离

`_can_modify_user` 被 `role/toggle/delete/update/password/telegram` 六个接口复用，一处改动全局生效。

```python
def _can_modify_user(actor: dict, target: dict) -> bool:
    """admin 只能操作 user/viewer/hidden，且仅限自己平台；developer 不受限。"""
    if actor["role"] == "developer":
        return True
    if target["role"] not in ("user", "viewer", "hidden"):
        return False
    # 平台隔离：非 developer 只能操作自己平台的用户
    if (actor.get("platform") or "gg") != (target.get("platform") or "gg"):
        return False
    return True
```

> 说明：`admin_update_user`（编辑）里已有的「非 developer 不可修改 platform」判断保持不动，与本次隔离互补。

### 3.2 前端（`UserManageView.vue`）

#### 改动 4：平台 Tab 只显示自己平台

```vue
<el-tabs v-model="platformFilter" @tab-change="onPlatformChange" style="margin-bottom:8px;">
  <el-tab-pane v-if="authStore.isDeveloper" label="全部" name="" />
  <el-tab-pane v-if="authStore.isDeveloper || authStore.effectivePlatform === 'gg'" label="GG" name="gg" />
  <el-tab-pane v-if="authStore.isDeveloper || authStore.effectivePlatform === 'fb'" label="FB" name="fb" />
  <el-tab-pane v-if="authStore.isDeveloper || authStore.effectivePlatform === 'tt'" label="TT" name="tt" />
</el-tabs>
```

`platformFilter` 初始值随身份变化（非 developer 默认选中自己的平台，避免「全部」Tab 被隐藏后处于空选中态）：

```js
const platformFilter = ref(authStore.isDeveloper ? '' : (authStore.user?.platform || 'gg'))
```

#### 改动 5：创建用户弹窗 — 非开发者隐藏平台选择、锁定平台

```vue
<el-form-item v-if="authStore.isDeveloper" label="平台">
  <el-select v-model="createForm.platform" style="width:100%">
    <el-option label="GG (Google Ads)" value="gg" />
    <el-option label="FB (Facebook)" value="fb" />
    <el-option label="TT (TikTok)" value="tt" />
  </el-select>
</el-form-item>
```

`createForm` 初始 platform 随身份：

```js
const createForm = ref({
  username: "", password: "", display_name: "",
  role: "user",
  platform: authStore.isDeveloper ? 'gg' : (authStore.user?.platform || 'gg')
})
```

创建成功后重置时同样按此规则重置。

#### 保持不动的部分
- 「角色」下拉（创建用户）：仍为 `user / viewer / admin` 三项（确认结果：同平台内可创建/提升管理员）。
- 「切换角色」下拉：仍为 `user / viewer / admin / hidden` 四项（可提升同平台 admin）。
- 编辑弹窗的「平台」字段：已由 `v-if="authStore.isDeveloper"` 控制，保持不动。

## 四、涉及文件

| 文件 | 改动 |
|------|------|
| `py/auth.py` | `list_users` 增加平台强制隔离 |
| `py/main.py` | `admin_create_user` 平台锁定；`_can_modify_user` 增加平台判断 |
| `frontend/src/views/UserManageView.vue` | 平台 Tab 条件显示；创建弹窗平台字段条件显示与默认值 |
| `py/tests/`（新增/扩展） | 平台隔离相关测试 |

## 五、边界情况

1. **developer 的 `platform`**：developer 可能 `platform` 为空或任意值，但所有判断都以 `role == 'developer'` 短路豁免，platform 不参与。
2. **现有 admin 账号**：`platform` 默认 `'gg'`（建表默认值 + `_add_column_if_missing`），隔离后 GG 管理员正常看到 GG 用户。若存在历史 admin 的 `platform` 为空串，统一按 `or "gg"` 兜底处理，不会出现「看不到任何用户」。
   **注意（存量数据风险）**：旧版 `admin_create_user` 对任何非 developer 一律把 platform 写死成 `'gg'`，因此**历史上由 TT/FB 管理员创建的用户，其 platform 全是 `'gg'`**。隔离生效后，这些行对原 TT/FB 管理员不再可见，反而落进 GG 管理员的可操作范围；且非 developer 不能改 platform，只能由 developer 逐个订正。若确有此类存量数据，需先做一次数据订正（见「七、遗留问题」）。
3. **空 platform 归一**：所有比较统一用 `(x.get("platform") or "gg")`，避免 `''` 与 `'gg'` 不一致。
4. **越权兜底**：前端隐藏 Tab/字段只是体验优化，真正的权限边界由后端 `list_users` 和 `_can_modify_user` 强制，防止绕过前端直接调接口。

## 六、测试要点

- 非 developer 管理员（platform=tt）列表只返回 platform=tt 的用户，且不含 developer。
- developer 列表无平台过滤（返回全部）。
- 非 developer 创建用户：即使前端传 `platform=gg`，后端仍写入自己的 platform。
- 非 developer 对「其他平台」用户执行改角色/改密/删除/编辑 → 返回 403，且错误消息为「不能操作其他平台的用户」。
- 非 developer 对「自己平台」的 user/viewer/hidden 操作 → 成功。
- 非 developer 不能操作同平台 admin → 403，错误消息为「不能操作同级管理员」。

## 七、遗留问题处理结果（2026-09-22 更新）

代码审查共发现 7 项，其中 4 项已在本轮修复，1 项经数据核查确认无需处理。

### 已修复

1. **「全部」Tab 实际只返回 GG**（前端）：`client.js` 对 developer 按 URL hash 前缀自动注入 `platform`，用户管理页路由 `/admin/users` 不以 `/tt`、`/fb` 开头 → 被推断成 `gg`。已在 `client.js` 中排除该路径，平台改由页面内 Tab 显式控制。
2. **用户管理页身份时序错位**（前端）：`App.vue` 的 `initFromStorage/fetchMe` 在父组件 `onMounted` 才执行，晚于子组件 setup，故 setup 时 `authStore.user` 必为 `null`。原实现在 `ref` 初始值里读身份（只算一次）会导致 Tab 与筛选值错位。已改为 `watch(() => authStore.user?.id, ...)`，等身份就绪后再定值并拉数据。
3. **`/api/admin/data/import` 与 `/api/admin/data/export/<uid>` 无平台隔离**：原仅 `@admin_required`，未校验 platform，非 developer 管理员可跨平台导入/导出。已新增 `_can_access_user_data(actor, target)` 并在两个接口处校验（403「不能导出其他平台用户的数据」/「不能为其他平台用户导入数据」）。
4. **`_get_effective_platform()` 语义不一致**：原判断 `role in ("developer", "admin")` 时取 `request.args.get("platform", "gg")`，而 `client.js` 只对 developer 注入 platform —— 导致**非 developer 管理员落到 GG 命名空间**。实际影响：TT 页面因前端显式传 `platform=tt` 而侥幸正确，**FB 页面不传参，FB 管理员看到的是 GG 的商务人员/账户状态选项**。已改为仅 `role == 'developer'` 才跨平台，其他角色一律取自己的 `platform`。
5. **创建时平台枚举兜底**：`admin_create_user` 中锁定平台时，若创建者的 `platform` 为存量非法值，按 `gg` 处理，避免把非法值写进新用户。

### 经核查无需处理

6. **存量数据订正**：已核查实际数据库（`temp/app.db`），全部 15 个用户中**仅 1 个**由非 developer 创建（`hld123`，创建者 `LM123`/TT 管理员），其 `platform='tt'` **正确**（应为创建后被 developer 订正过）。其余均为 developer 创建。**不存在需要订正的错配数据**。

### 尚未处理（属「户管角色」范畴）

7. **`_get_effective_platform()` 与户管角色的衔接**：本次已把 admin 从跨平台判断中移除；`2026-09-22-huguan-role-design.md` 计划将该判断改为 `CROSS_USER_ROLES`（含 developer 与户管）。**合并时需把本次的 `role == 'developer'` 扩展为该角色集合**，语义兼容（户管是跨平台角色）。
