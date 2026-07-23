# 用户管理改进设计文档

## 需求描述

1. **管理员不能修改自己的权限/删除自己** — 当前管理员可以降级自己的角色或删除自己，不合理
2. **开发者(deve)用户对其他用户隐藏** — developer 角色的用户只能自己看到自己，其他用户（包括管理员）看不到
3. **增加编辑用户信息功能** — 管理员可以编辑用户的用户名、显示名
4. **增加修改密码功能** — 管理员可以给用户重置密码；用户自己也可以改密码
5. **用户个人信息页面** — 用户可以自己管理自己的信息（改显示名、改密码）

---

## 技术方案

### 一、后端改动

#### 1.1 防止管理员修改自己的角色/状态/删除自己

**涉及文件：** `py/main.py`

| 端点 | 修改内容 |
|------|---------|
| `PUT /api/admin/users/<uid>/role` | 新增判断：`if uid == user_id: return 403 "不能修改自己的角色"` |
| `POST /api/admin/users/<uid>/toggle` | 新增判断：`if uid == user_id: return 403 "不能禁用自己"` |
| `DELETE /api/admin/users/<uid>` | 新增判断：`if uid == user_id: return 403 "不能删除自己"` |

#### 1.2 开发者用户对其他用户隐藏

**涉及文件：** `py/auth.py`, `py/main.py`

**`auth.list_users` 修改：** 增加 `current_user_id` 参数，在 SQL 查询中排除 developer 角色的用户（除非请求者自己就是 developer）

```python
def list_users(search: str = "", page: int = 1, page_size: int = 20, current_user_id: int = None) -> dict:
    # 非 developer 用户看不到 developer 角色的用户
    # developer 用户能看到所有人（包括自己）
```

**`/api/users/names` 修改：** 增加 `@jwt_required(optional=True)`，获取当前用户身份，如果是 developer 则返回全部用户（不含 hidden），否则排除 developer 角色

#### 1.3 新增：编辑用户信息

**新端点：** `PUT /api/admin/users/<uid>`（需要 admin/developer 权限）

- 请求体：`{ "username": "新用户名", "display_name": "新显示名" }`
- 校验：用户名 4-20 字符，不能与已有用户重复
- 不能修改 developer 用户的信息（除非自己就是 developer）

**新增 `auth.update_user` 函数：**

```python
def update_user(uid: int, username: str = None, display_name: str = None) -> dict | None
```

#### 1.4 新增：修改密码

**新端点 A：** `PUT /api/admin/users/<uid>/password`（管理员给用户重置密码）

- 请求体：`{ "password": "新密码" }`
- 校验：密码至少 6 位
- 管理员不能修改 developer 的密码

**新端点 B：** `PUT /api/auth/password`（用户自己改密码）

- 请求体：`{ "old_password": "旧密码", "new_password": "新密码" }`
- 校验：旧密码必须正确，新密码至少 6 位

**新增 `auth.update_password` 函数：**

```python
def update_password(uid: int, new_password: str) -> bool
```

#### 1.5 新增：用户自己更新信息

**新端点：** `PUT /api/auth/profile`（用户自己改显示名）

- 请求体：`{ "display_name": "新显示名" }`

---

### 二、前端改动

#### 2.1 `UserManageView.vue` 修改

| 改动 | 说明 |
|------|------|
| 隐藏 developer 行 | 后端已过滤，前端无需额外处理 |
| 禁止操作自己 | 操作列（切换角色、删除）对当前登录用户的行 disabled + tooltip 提示"不能操作自己" |
| 新增"编辑"按钮 | 点击弹出编辑对话框，可修改用户名、显示名 |
| 新增"改密"按钮 | 点击弹出改密对话框，输入新密码 |
| 创建用户弹窗 | 角色选择中移除 `developer` 选项（只能系统初始化创建） |

#### 2.2 新增 `UserProfileView.vue` — 个人信息页面

用户自己可以访问的页面，包含：
- 显示当前用户信息（用户名、显示名、角色、创建时间、最后登录）
- 编辑显示名
- 修改密码（旧密码 + 新密码 + 确认新密码）

#### 2.3 路由

新增路由 `/profile`，`meta: { title: '个人信息' }`，需要登录即可访问（不需要 admin）

#### 2.4 API 扩展（`frontend/src/api/admin.js`）

新增方法：
```js
updateUser(uid, data)    // PUT /admin/users/<uid>
updatePassword(uid, pwd) // PUT /admin/users/<uid>/password
```

#### 2.5 API 扩展（`frontend/src/api/auth.js`）

新增方法：
```js
changePassword(oldPwd, newPwd)  // PUT /auth/password
updateProfile(data)              // PUT /auth/profile
```

---

### 三、涉及的文件

| 文件 | 类型 |
|------|------|
| `py/main.py` | 后端 - 新增/修改 API 端点 |
| `py/auth.py` | 后端 - 新增 update_user、update_password、修改 list_users |
| `frontend/src/views/UserManageView.vue` | 前端 - 修改用户管理页面 |
| `frontend/src/views/UserProfileView.vue` | 前端 - **新增**个人信息页面 |
| `frontend/src/api/admin.js` | 前端 - 新增 API 方法 |
| `frontend/src/api/auth.js` | 前端 - 新增 API 方法 |
| `frontend/src/router/index.js` | 前端 - 新增路由 |
| `frontend/src/stores/auth.js` | 前端 - 无需修改（已有 isDeveloper getter） |

---

### 四、数据结构

无数据库 schema 变更，仅修改查询逻辑。

---

### 五、UI 改动

- **UserManageView**：操作列增加"编辑"和"改密"按钮，自己的行操作按钮 disabled
- **UserProfileView（新页面）**：简洁的信息卡片 + 编辑表单，放在导航栏用户下拉菜单中可进入

---

## 实际代码逻辑补充（2026-07-23 审计）

### 1. `/api/users/names` 缺少 developer 过滤（需关注）

文档要求非 developer 用户调用此接口时不应看到 developer 角色用户。实际代码（`py/main.py:5679` 和 `py/routes/auth_routes.py:177`）仅过滤 `u.role != 'hidden'`，未排除 developer。且此端点存在两份实现代码。

### 2. 删除自己状态码不一致

`DELETE /api/admin/users/<uid>` 禁止删除自己时返回 **400**，而 role 和 toggle 端点正确返回 **403**。

### 3. 超规格实现

| 功能 | 说明 |
|---|---|
| Telegram 用户名管理 | 编辑弹窗含 Telegram 用户名字段 + 后端端点 |
| 导入数据按钮 | UserManageView 增加了导入数据功能 |
| `_can_modify_user` 权限 | admin 不能操作其他 admin（比规格更严格） |
| UserProfileView 扩展 | 含 Google Sheets 配置、邮箱通知等额外功能 |

### 4. toggleUser 前端未调用

后端 `POST /api/admin/users/<uid>/toggle` 已实现，前端 `admin.js` 也定义了 `toggleUser`，但 UserManageView 的角色切换通过 role dropdown 实现，toggle 端点未被调用。
