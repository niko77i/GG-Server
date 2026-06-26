# GG-Server 多人协作版设计规格

**日期**：2026-06-23
**状态**：草稿，待确认

## 1. 背景与目标

当前项目 (ImageCrawling) 为单用户本地工具，需要改造为局域网内多人协作的服务器版本。
新建独立项目 `GG-Server`，不修改现有项目代码。

### 核心目标

- 用户系统（注册/登录/权限分级）
- 数据按用户隔离（个人模块）或共享（公共模块）
- 局域网内多人同时使用
- 兼容现有数据库逻辑、API 设计、前端交互

## 2. 总体架构

```
                   局域网内
  Server PC (常开)
  +-----------------------------------------+
  |  Flask (0.0.0.0:5000)                  |
  |  +- JWT Auth Middleware                 |
  |  +- API Routes (with user_id scoping)   |
  |  +- SQLite (WAL mode, temp/app.db)      |
  +-----------------------------------------+
          ↑ HTTP / JSON + JWT
  +-----------------------------------------+
  |  Vue 3 + Vite (frontend/)               |
  |  +- Login / Register pages              |
  |  +- Router guards (auth check)          |
  |  +- Per-user data display               |
  +-----------------------------------------+

  PC1 浏览器    PC2 浏览器    PC3 浏览器
  访问 :5000    访问 :5000    访问 :5000
```

### 开发模式

```
cd GG-Server/py && python main.py           (Flask API :5000)
cd GG-Server/frontend && npm run dev        (Vite :5173, 代理 /api -> Flask)
```

### 生产模式

```
cd GG-Server/py && python main.py
# Flask 直接提供后端 API + dist/ 前端静态文件
```

### 技术栈

| 组件 | 选择 | 说明 |
|------|------|------|
| 后端框架 | Flask | 沿用，纯 API |
| 数据库 | SQLite (WAL 模式) | 轻量，20人以下够用 |
| 认证 | Flask-JWT-Extended | JWT token，适合 SPA |
| 密码 | Werkzeug generate_password_hash | Flask 内置 |
| 前端 | Vue 3 + Vite + Element Plus | 沿用现有方案 |
| 状态 | Pinia | 沿用 |
| HTTP | axios | 沿用，全局拦截器带 token |
| 打包 | 暂不打包 EXE | 服务器模式无需打包 |

## 3. 数据模型

### 3.1 用户表 (users)

```sql
CREATE TABLE users (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    username    TEXT NOT NULL UNIQUE,
    password    TEXT NOT NULL,
    role        TEXT NOT NULL DEFAULT 'user',
    display_name TEXT DEFAULT '',
    created_at  TEXT NOT NULL DEFAULT (datetime('now')),
    last_login  TEXT,
    created_by  INTEGER REFERENCES users(id),
    config      TEXT DEFAULT '{}'
);
```

**角色说明**：

| 角色 | 可创建 | 可管理用户 | 可删除数据 | 备注 |
|------|--------|-----------|-----------|------|
| developer | 全部角色 | 全部 | 全部 | 唯一，系统最高 |
| admin | 仅 user | 管理 user | 全部 | 由 developer 创建 |
| user | 不能创建用户 | 不可 | 自己的数据 | 通过注册创建 |
| hidden | - | - | - | 被停用，无法登录 |


### 3.2 数据隔离设计

每个数据表增加 owner_id 字段（可为 NULL，表示全局共享），或使用独立表。

#### 共享数据（无 owner_id 或 owner_id IS NULL）

| 表 | 说明 |
|----|------|
| products | 产品管理，所有人可见 |
| packages | 产品的包，通过 products 继承 |
| scrape_cache | 爬取缓存（包名 -> 截图），共享去重 |
| yt_videos (is_public=1) | YouTube 公共视频库 |

#### 个人数据（owner_id NOT NULL）

| 表 | 说明 |
|----|------|
| user_accounts | 广告账户管理 per-user |
| user_mcc | MCC 管理 per-user |
| scrape_history | 个人爬取记录 |
| video_history | AI 视频生成历史 per-user |
| yt_videos (is_public=0) | YouTube 个人视频库 |

#### YouTube 视频：共享 + 个人 双层模型

```sql
CREATE TABLE yt_videos (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    owner_id      INTEGER REFERENCES users(id),
    is_public     INTEGER DEFAULT 0,
    url           TEXT NOT NULL,
    title         TEXT,
    region        TEXT,
    frame_type    TEXT,
    effectiveness TEXT,
    product_name  TEXT,
    created_at    TEXT DEFAULT (datetime('now')),
    updated_at    TEXT DEFAULT (datetime('now'))
);
```

- is_public=1 -> 属于公共库，所有人可查看
- is_public=0 -> 仅 owner 自己可见
- 导入时默认 is_public=0，用户可手动标记为公开
- 筛选时切换到我的视频或公共视频库

#### 爬取缓存共享

```sql
CREATE TABLE scrape_cache (
    package_name TEXT PRIMARY KEY,
    image_count  INTEGER DEFAULT 0,
    saved_path   TEXT,
    logo_path    TEXT,
    last_scraped TEXT DEFAULT (datetime('now')),
    scraped_by   INTEGER REFERENCES users(id)
);
```

当用户 A 爬取过包 com.xxx，用户 B 再爬同一包时直接命中缓存。
## 4. 认证设计

### 4.1 API 认证

采用 JWT（JSON Web Token），Flask-JWT-Extended：

| 方法 | 路径 | 说明 | 鉴权 |
|------|------|------|------|
| POST | /api/auth/login | 登录，返回 JWT token | 无 |
| POST | /api/auth/register | 注册（仅 user 级别） | 无 |
| POST | /api/auth/refresh | 刷新 token | JWT |
| GET | /api/auth/me | 获取当前用户信息 | JWT |

Token 携带：前端 axios 拦截器自动带 Authorization: Bearer <token>

### 4.2 路由保护

后端装饰器 @jwt_required() + 自定义 @role_required：

```python
from flask_jwt_extended import jwt_required, get_jwt_identity

def admin_required(fn):
    @wraps(fn)
    @jwt_required()
    def wrapper(*args, **kwargs):
        user_id = get_jwt_identity()
        user = get_user_by_id(user_id)
        if user['role'] not in ('developer', 'admin'):
            return jsonify(success=False, error='权限不足'), 403
        return fn(*args, **kwargs)
    return wrapper
```

### 4.3 登录密码 vs 操作权限

- **密码**控制是否能登录系统 (pbkdf2:sha256 哈希)
- **role** 控制登录后的操作权限
- hidden 角色：密码校验通过也不能登录

### 4.4 注册流程

- 开放 /api/auth/register 接口
- 注册成功后自动创建 user 级别账号
- developer 在后台可将其升级为 admin，或降级为 hidden
- 注册需要：username, password, display_name（可选）
## 5. 前端变更

### 5.1 路由结构

```
/login              -> LoginView          (公开)
/register           -> RegisterView       (公开)
/                   -> 重定向到 /accounts  (需登录)
/accounts/products  -> ProductPanel       (共享数据)
/accounts/ads       -> AdsAccountPanel    (个人，owner_id 过滤)
/accounts/mcc       -> MccPanel           (个人，owner_id 过滤)
/accounts/settings  -> SettingsPanel      (个人 + 部分全局)
/youtube            -> YoutubeView        (共享 + 个人标签)
/youtube/public     -> 公共视频库
/youtube/private    -> 我的视频
/scrape             -> ScrapeView         (个人，缓存共享)
/video              -> VideoView          (个人)
/toolkit            -> ToolkitView        (个人)
/admin/users        -> UserManageView     (仅 developer/admin)
```

### 5.2 Pinia Store 调整

**auth.js**（从骨架实现完整）：

```js
export const useAuthStore = defineStore('auth', {
  state: () => ({
    user: null,
    token: '',
    isLoggedIn: false,
  }),
  actions: {
    async login(username, password) {},
    async register(username, password) {},
    async fetchMe() {},
    logout() { this.$reset(); localStorage.removeItem('token') },
    initFromStorage() {},
  },
  getters: {
    isAdmin: (state) => ['developer', 'admin'].includes(state.user?.role),
    isDeveloper: (state) => state.user?.role === 'developer',
  },
})
```

### 5.3 登录页

- 简洁的登录表单（用户名 + 密码）
- 注册链接（注册后自动登录）
- 记住登录状态（localStorage 存 token）
- 登录后跳转到之前的页面 (?redirect=)

### 5.4 用户管理页

- 仅 developer/admin 可见
- 表格展示所有用户（用户名、角色、创建时间、最后登录、状态）
- 操作：编辑角色（user <-> admin <-> hidden）、删除用户
- 搜索/筛选
- 提示：无法删除自己、无法删除 developer 账号
## 6. 涉及的后端文件

| 文件 | 操作 |
|------|------|
| py/main.py | 新增 auth 路由 + @jwt_required() + user_id 作用域调整 |
| py/auth.py | 新建：用户认证逻辑（登录/注册/JWT/角色校验） |
| py/database.py | 新增 users 表、scrape_cache 表；现有表增加 owner_id/is_public |
| py/scraper.py | 增加缓存查询逻辑（先查 scrape_cache） |

## 7. 项目结构 (GG-Server)

```
GG-Server/
├── frontend/                  # Vue 3 前端（从现有复制修改）
│   ├── src/
│   │   ├── api/
│   │   │   ├── client.js      # axios + JWT 拦截器
│   │   │   ├── auth.js        # 登录/注册/用户管理 API
│   │   │   ├── accounts.js    # 沿用
│   │   │   ├── products.js    # 沿用
│   │   │   └── ...
│   │   ├── stores/
│   │   │   ├── auth.js        # 完整实现
│   │   │   └── ...
│   │   ├── views/
│   │   │   ├── LoginView.vue
│   │   │   ├── RegisterView.vue
│   │   │   ├── UserManageView.vue   # 新增
│   │   │   └── ...
│   │   ├── router/index.js    # 增加 /login, /register, /admin/users
│   │   └── App.vue            # 路由守卫 + 用户状态初始化
│   └── ...
├── py/
│   ├── main.py                # 沿用现有 API + 新增 auth 路由
│   ├── auth.py                # 新建：认证模块
│   ├── database.py            # 调整：user_id 作用域
│   ├── scraper.py             # 调整：缓存查询
│   ├── resizer.py             # 沿用
│   ├── utils.py               # 沿用
│   ├── video_processor.py     # 沿用
│   └── ai_service.py          # 沿用
├── temp/
│   └── app.db                 # SQLite (WAL 模式)
└── docs/
    └── superpowers/
        └── specs/             # 设计文档
```

## 8. API 路由调整

### 新增路由

| 方法 | 路径 | 说明 | 鉴权 |
|------|------|------|------|
| POST | /api/auth/login | 登录，返回 JWT token | 无 |
| POST | /api/auth/register | 注册（仅 user 级别） | 无 |
| POST | /api/auth/refresh | 刷新 token | JWT |
| GET | /api/auth/me | 获取当前用户信息 | JWT |
| GET | /api/admin/users | 用户列表（搜索/分页） | developer/admin |
| POST | /api/admin/users/:id/role | 修改用户角色 | developer/admin |
| POST | /api/admin/users/:id/toggle | 启用/禁用用户 | developer/admin |

### 现有路由调整

所有现有路由增加 @jwt_required()。通过 get_jwt_identity() 获取当前用户 ID：

```python
# 共享数据（products）- 无需 owner_id 过滤
def list_products():
    return db_query("SELECT * FROM products WHERE ...")

# 个人数据（accounts）- 需要 owner_id 过滤
def list_accounts():
    user_id = get_jwt_identity()
    return db_query("SELECT * FROM user_accounts WHERE owner_id = ?", [user_id])

# YouTube - 混合
def list_yt_videos(scope='all'):
    user_id = get_jwt_identity()
    if scope == 'public':
        return db_query("SELECT * FROM yt_videos WHERE is_public = 1")
    elif scope == 'private':
        return db_query("SELECT * FROM yt_videos WHERE owner_id = ?", [user_id])
    else:
        return db_query("SELECT * FROM yt_videos WHERE is_public = 1 OR owner_id = ?", [user_id])
```

## 9. 实现优先级

### Phase 1 - 用户系统基础（核心）
- [ ] 创建 GG-Server 项目目录结构
- [ ] py/auth.py：用户 CRUD + JWT 登录/注册
- [ ] py/database.py：新增 users 表 + migration
- [ ] py/main.py：新增 auth 路由 + @jwt_required() 装饰器
- [ ] 前端：LoginView + RegisterView + auth store + router guards
- [ ] 前端：client.js axios 拦截器自动带 token

### Phase 2 - 数据隔离
- [ ] 产品管理：保持共享
- [ ] 账户/MCC：改为 per-user 作用域
- [ ] YouTube：is_public / owner_id 双层模型
- [ ] 爬取缓存：scrape_cache 表 + 命中逻辑
- [ ] 视频历史：owner_id 过滤个人记录

### Phase 3 - 用户管理后台
- [ ] GET /api/admin/users + 角色管理
- [ ] UserManageView.vue 用户管理页
- [ ] 注册审核配置

### Phase 4 - 软装与稳定
- [ ] 登录页 UI 美化
- [ ] 错误处理（token 过期自动跳转登录页）
- [ ] SQLite WAL 模式启用
- [ ] 启动脚本 + 说明文档
- [ ] 局域网访问测试

## 10. 注意事项

- **不修改现有项目**：GG-Server 是全新项目，从现有项目复制代码并修改
- **SQLite WAL 模式**：PRAGMA journal_mode=WAL; 启用并发读写
- **JWT 过期时间**：access_token 24h，refresh_token 7d
- **密码安全**：使用 Werkzeug 的 generate_password_hash
- **CORS 配置**：开发模式允许 Vite dev server port 5173；生产模式同源
- **打包 EXE 暂缓**：服务器模式无需打包；后续如需再考虑
- **前端框架**：从现有 frontend/ 复制，已包含 Vue 3 + Element Plus 依赖
- **开发启动**：需要同时启动 Flask 后端和 Vite dev server

## 11. 暂不包含

- 异地互联网部署（非局域网）
- Docker 容器化
- WebSocket 实时推送
- 操作日志审计
- 文件上传权限控制