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

## 实际代码逻辑补充（2026-07-23 审计）

以下为对比设计文档与实际代码（master 分支截止 2026-07-23）后发现的差异和补充项。设计文档整体方向正确，但实际实现有大量扩展。

### 1. 后端架构差异

#### 1.1 路由分层（设计文档未提及）

设计文档假定所有路由在 `py/main.py` 中定义。实际代码引入了 `py/routes/` 包，将认证路由抽取为 Flask Blueprint：

| 文件 | 职责 |
|------|------|
| `py/routes/auth_routes.py` | `/api/auth/*` Blueprint，含登录/注册/JWT刷新/用户信息/密码修改/Telegram/邮箱等 |
| `py/routes/decorators.py` | `admin_required`、`developer_required`、`reject_viewer` 装饰器 |
| `py/routes/helpers.py` | 公共工具函数：`ok()`、`err()`、`parse_body()`、`get_uid()`、`get_db()`、`get_current_user()`、`runner_ids_where()`、`scope_where()`、`can_modify()`、`can_modify_user()` 等 |

`main.py` 仍包含大部分业务路由（products、accounts、mcc、youtube、scrape、video 等约 70+ 个端点），通过 `app.register_blueprint(auth_bp, url_prefix="/api/auth")` 挂载认证蓝图。

#### 1.2 Flask 请求生命周期钩子（设计文档未提及）

实际代码注册了多个全局钩子：

- `before_request: _attach_db` -- 每个请求自动创建数据库连接并挂到 `g.db`
- `before_request: _log_request` -- 记录请求开始时间
- `after_request: _close_db` -- 请求结束后自动关闭数据库连接
- `after_request: _log_response` -- 打印 `[时间] METHOD /path -> status (ms)` 日志（高频轮询接口 `/api/delist/pending` 跳过）
- `after_request: _add_static_cache` -- 带 hash 的静态资源添加 1 年缓存头
- `after_request: _refresh_jwt` -- 滑动过期：每次有效请求返回新 access_token 通过 `X-New-Access-Token` 响应头

#### 1.3 JWT 滑动过期（替代原 refresh token 方案）

设计文档第 10 节提到 "access_token 24h，refresh_token 7d"。实际代码改为**滑动过期机制**：只要用户 24h 内有操作，每次有效请求自动签发新 token 通过 `X-New-Access-Token` 响应头传回。前端 `client.js` 拦截器自动提取并更新 localStorage。闲置超过 24h 则需要重新登录。

Refresh token 接口 (`/api/auth/refresh`) 仍保留但非主要续期手段。

### 2. 新增后端模块（设计文档未提及）

| 文件 | 说明 |
|------|------|
| `py/cache.py` | 线程安全的内存 TTL 缓存层（`SimpleCache`），默认 60s TTL，用于缓存低频变化查询结果 |
| `py/data_service.py` | 数据导入/导出/备份核心逻辑（支持 db 和 JSON 格式），供 Web API 和 CLI 共用 |
| `py/manage.py` | CLI 工具：backup、list-backups、restore、import-db、import-json、export-user、export-all |
| `py/delist_checker.py` | Google Play 掉包检测：HTTP 请求 GP 链接判断应用是否下架，含关键词匹配 |
| `py/google_sheets_service.py` | Google Sheets API 集成（做表数据同步到 Google 表格） |
| `py/telegram_sender.py` | Telegram Bot 通知（掉包提醒等） |
| `py/email_sender.py` | 邮件发送服务 |
| `py/google_ads_service.py` | Google Ads API（按需加载，不打包进 EXE） |
| `py/migrate_from_production.py` | 从线上 db 迁移数据的专项脚本 |

### 3. 角色系统扩展

#### 3.1 新增 viewer 角色

设计文档仅定义 developer / admin / user / hidden 四级。实际代码新增第五级：

| 角色 | 说明 |
|------|------|
| **viewer** | 只读观察者，只能访问 `/accounts/products` 页面，不能访问任何其他账户子页面，无法执行任何写操作。路由守卫中 `isViewer` 强跳转。 |

#### 3.2 角色隔离细化

- 非 developer 用户看不到 developer 角色的用户（`list_users` 自动过滤）
- admin 只能操作 user/viewer/hidden 角色用户，不能操作其他 admin（`can_modify_user` 函数控制）
- `toggle_user_status`：hidden <-> 原角色（user/admin/viewer）互切；developer 不可被 toggle

### 4. 认证路由扩展（超出设计文档）

设计文档列了 4 个 auth 路由。实际实现的 `/api/auth/*` 路由远多于此：

| 方法 | 路径 | 说明 | 设计文档 |
|------|------|------|---------|
| POST | /api/auth/login | 登录 | 有 |
| POST | /api/auth/register | 注册 | 有 |
| POST | /api/auth/refresh | 刷新 token | 有 |
| GET | /api/auth/me | 当前用户信息 | 有 |
| PUT | /api/auth/password | 用户修改密码（需旧密码） | **无** |
| PUT | /api/auth/profile | 更新个人显示名 | **无** |
| GET/PUT | /api/auth/custom-name | 自定义名称 | **无** |
| GET/PUT | /api/auth/email | 邮箱地址 | **无** |
| PUT | /api/auth/telegram-username | Telegram 用户名（去 @ 前缀） | **无** |
| GET | /api/auth/names | 产品相关的用户名列表（runner 选择器用） | **无** |

### 5. 管理员路由扩展（超出设计文档）

设计文档列了 3 个 admin 路由（list/toggle/role）。实际还包含：

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | /api/admin/users/create | 管理员创建新用户 |
| DELETE | /api/admin/users/:id | 删除用户 |
| PUT | /api/admin/users/:id | 编辑用户（用户名/显示名） |
| PUT | /api/admin/users/:id/password | 重置用户密码 |
| PUT | /api/admin/users/:id/telegram-username | 设置用户 Telegram |
| POST | /api/admin/trigger-weekly-cleanup | 触发每周清理任务 |
| POST | /api/admin/trigger-delist-check | 手动触发掉包检测 |

### 6. 前端路由差异（与设计文档 5.1 节对比）

#### 6.1 路由模式

设计文档未明确路由模式。实际使用 **Hash 模式** (`createWebHashHistory`)，而非 History 模式。这避免了服务端需配置 SPA fallback 的问题。

#### 6.2 实际路由表（差异项加粗）

```
/login              -> LoginView          (公开) -- 一致
/register           -> RegisterView       (公开) -- 一致
/                   -> 重定向到 /youtube  -- **设计文档为 /accounts**
/accounts/products  -> ProductPanel       -- 一致
/accounts/ads       -> AdsAccountPanel    -- meta: { admin: true } **新增权限标记**
/accounts/mcc       -> MccPanel           -- meta: { admin: true } **新增权限标记**
/accounts/settings  -> SettingsPanel      -- meta: { admin: true } **新增权限标记**
/youtube            -> YoutubeView        -- **新增子路由**: view/copywriting/import/config
/media              -> MediaView          -- **设计文档无**
/toolkit            -> ToolkitView        -- **新增子路由**: zuobiao/audio/translate
/analysis           -> AnalysisView       -- **设计文档无**
/data-manage        -> DataManageView     -- **设计文档无**
/admin/users        -> UserManageView     -- 一致
/admin/scheduler    -> SchedulerView      -- **设计文档无**，仅 developer
/profile            -> UserProfileView    -- **设计文档无**
```

设计文档 5.1 列了 `/scrape`、`/video`、`/youtube/public`、`/youtube/private` 路由，实际代码中这些路由**不存在于前端路由表**。Scrape 和 Video 功能通过其他页面的组件/弹窗访问，YouTube 公开/私有切换通过页面内标签实现。

#### 6.3 路由守卫增强

实际路由守卫 (`router.beforeEach`) 增加了：

- `admin` meta 检查：非 admin 用户访问 `/accounts/ads`、`/accounts/mcc`、`/accounts/settings`、`/admin/users` 时重定向到 `/youtube`
- `developer` meta 检查：非 developer 访问 `/admin/scheduler` 时重定向
- **viewer 限制**：viewer 角色访问 `/accounts` 子页面（非 products）时强制跳回 `/accounts/products`

### 7. 数据库差异（与设计文档 3.1、3.2 节对比）

#### 7.1 users 表额外字段

设计文档列了 `username, password, role, display_name, created_at, last_login, created_by, config`。实际还包含：

- `custom_name TEXT` -- 用户自定义名称
- `email TEXT` -- 邮箱地址
- `telegram_username TEXT` -- Telegram 用户名（用于掉包 @ 通知）

#### 7.2 实际完整表清单（设计文档完全未提及的表）

| 表 | 说明 | 原因 |
|----|------|------|
| `video_history` | 视频生成历史（替换 temp/video_set/*.json） | 从旧项目迁移 |
| `video_tasks` | 视频任务记录（持久化，重启后仍可查询） | 支持后台任务状态追踪 |
| `tags` | 通用 key-value 标签（含 YT tags + 全局配置） | 替代分散配置文件 |
| `config` | 通用配置键值存储（字体/迁移标记等） | 替代分散 JSON 文件 |
| `account_mcc_history` | 账户 MCC 变更审计历史 | 追踪账户归属变更 |
| `recharge_records` | 充值记录 | 广告账户充值管理 |
| `sheets_sync_log` | Google Sheets 同步失败日志 | 异步重试 + 前端展示 |
| `product_runners` | 产品在跑人员关联表（独立 JOIN 表，与 `products.runner_ids` JSON 列并存） | 支持索引查询 |
| `product_assets` | 产品成效素材关联（产品-视频多对多） | 成效素材管理 |
| `video_consumption` | 视频消耗追踪（手动录入广告消耗） | 消耗数据分析 |
| `ad_reports` | 做表数据保存（广告投放报告） | 数据管理与分析模块 |
| `regions` | 地区与时区管理 | 独立的时区配置 |
| `import_history` | 导入历史审计记录 | 追踪数据导入操作 |
| `delist_checks` | 掉包检测结果 | 按包+产品跟踪掉包状态 |
| `delist_notifications` | 掉包通知状态（按用户跟踪通知/关闭/提醒） | 防止重复弹窗 |
| `audio_replace_history` | 音频替换操作历史 | 音频工具记录 |
| `audit_log` | 审计日志（产品删除等关键操作，支持恢复） | 操作追溯与数据恢复 |
| `copywritings` | 文案管理（含 `owner_id`/`is_public` 隔离） | 设计文档未提及文案系统 |

#### 7.3 数据库迁移策略

设计文档未描述迁移机制。实际实现了**双重迁移策略**：

1. **表级迁移**（首次连接执行，`_ensure_schema`）：`CREATE TABLE IF NOT EXISTS` + 初始化数据
2. **列级迁移**（每次连接执行，`_ensure_columns`）：`_add_column_if_missing()` 幂等增量添加列 + 索引创建
3. **门控迁移**（通过 `config` 表标记）：如 `migrated_owner_id`、`migrated_mcc_dedup`、`migrated_product_runners_v2` 等，确保一次性迁移只执行一次
4. **索引修复迁移**：如 `ad_reports` 去重索引从 UNIQUE 降级为普通 INDEX（v3 迁移）

### 8. 产品与数据隔离的实际实现

#### 8.1 runner_ids 双重机制

设计文档未提及 runner 机制。实际实现了产品分配在跑人员的**双重存储**：

- `products.runner_ids` TEXT 列（JSON 数组格式，如 `"[1, 3, 5]"`）
- `product_runners` 独立关联表（`product_id, user_id` 联合主键，支持高效索引查询）

两个数据源通过 `_ensure_schema` 中的迁移保持同步。并提供 `set_product_runners()`、`add_product_runners()`、`get_runner_product_ids()` 函数操作关联表。

#### 8.2 runner 数据可见性

普通用户（非 admin/developer）只能看到：
- 自己是 owner 的产品
- runner_ids 中包含自己的产品
- 通过 `product_runners` 关联的产品

对应 SQL 通过 `runner_ids_where()` 函数生成 LIKE 模式匹配 JSON 数组。

#### 8.3 MCC 多用户共享

设计文档未提及。实际实现了 MCC 级共享机制：

- `mcc.shared_user_ids` TEXT 列（JSON 数组），存储可访问该 MCC 的用户 ID
- `_migrate_mcc_share_runners` 迁移：自动将产品的 runner 回填到 MCC 的 shared_user_ids（含上级链遍历）
- `_assign_mcc_to_users` / `_link_mcc_chain_to_user`：将 MCC 及其子 MCC 关联给用户

#### 8.4 数据隔离实际表

设计文档 3.2 节列了数据隔离设计，实际代码**与设计有出入**：

- **products** 表也增加了 `owner_id` 字段——设计文档将其列为"共享数据"，实际支持按 owner/runner 过滤
- **mcc** 表增加了 `owner_id` 和 `shared_user_ids`
- **accounts** 表增加了 `owner_id`
- **copywritings** 表有 `owner_id` + `is_public`（与 videos 相同的双层模型）
- videos 的隔离使用 `owner_id` + `is_public`，通过 `scope_where()` 函数统一处理

### 9. 前端架构差异

#### 9.1 Pinia Store（超出设计文档）

设计文档仅提及 `auth.js` store。实际实现 6 个 store：

| Store | 文件 | 说明 |
|-------|------|------|
| auth | `stores/auth.js` | 认证状态（含 `isViewer`、`canAccessProducts`、`roleLabel` getter） |
| video | `stores/video.js` | 视频生成状态（进度/任务管理） |
| taskRunner | `stores/taskRunner.js` | 全局任务追踪（后台轮询、跨 Tab 同步） |
| products | `stores/products.js` | 产品管理状态 |
| youtube | `stores/youtube.js` | YouTube 视频/文案状态 |
| accounts | `stores/accounts.js` | 广告账户状态 |

#### 9.2 App.vue 全局功能

设计文档未描述。实际 `App.vue` 包含：

- 认证页（login/register）全屏渲染，其他页面侧边栏 + 内容布局
- `<AppSidebar />` 全局侧边栏组件
- `<GlobalTaskPanel />` 全局任务面板（视频生成等后台任务状态）
- **全局掉包通知轮询**（30s 间隔，`setInterval`），检测到掉包时弹出 `ElNotification` 并支持跨 Tab 同步
- **跨 Tab 同步**：通过 `BroadcastChannel` API（`utils/broadcast.js`），在多个浏览器 Tab 间同步掉包通知、任务状态

#### 9.3 HTTP 客户端增强

设计文档描述 axios + JWT 拦截器。实际实现的 `client.js` 还包含：

- 响应拦截器自动提取 `X-New-Access-Token` 响应头，更新 localStorage 实现滑动过期
- 401 错误自动清除 token 并跳转登录页（排除 auth 接口自身）
- 所有 API 响应自动解包 `resp.data`，调用方直接拿到业务数据

#### 9.4 前端 API 模块

设计文档列了 `auth.js`、`accounts.js`、`products.js`。实际 API 模块：

| 模块 | 文件 | 说明 |
|------|------|------|
| auth | `api/auth.js` | 登录/注册/用户信息/密码/Telegram/邮箱 |
| accounts | `api/accounts.js` | 账户 CRUD |
| products | `api/products.js` | 产品/包管理 + delist 检测 |
| youtube | `api/youtube.js` | 视频/消费/标签 |
| scrape | `api/scrape.js` | 爬取功能 |
| video | `api/video.js` | 视频生成 |
| admin | `api/admin.js` | 用户管理 + 手动触发清理/检测 |
| browse | `api/browse.js` | 文件浏览（设计文档无） |
| data | `api/data.js` | 数据管理（设计文档无） |
| reports | `api/reports.js` | 广告投放报告（设计文档无） |
| google-sheets | `api/google-sheets.js` | Google Sheets 同步（设计文档无） |

### 10. 打包与部署（与设计文档第 2 节差异）

设计文档第 10 节说"打包 EXE 暂缓"。实际代码完整实现了 PyInstaller 打包支持：

- `_FROZEN` 全局标志检测打包模式
- 打包后前端文件从 `sys._MEIPASS/dist/` 读取
- 数据目录固定在 EXE 所在目录（`sys.executable` 的目录）
- `_get_ffmpeg_path()` 支持打包后 bundle ffmpeg.exe

生产模式下，Flask 同时提供 API 和前端静态文件（SPA fallback 已实现）。

### 11. 其他值得注意的差异

| 项目 | 设计文档 | 实际代码 |
|------|---------|---------|
| Flask-Compress | 未提及 | `Compress(app)` 启用 gzip 压缩 |
| 内存缓存 | 未提及 | `py/cache.py` SimpleCache |
| campaign -> 产品映射 | 未提及 | `_build_campaign_product_map()` + `_resolve_product_name()`，通过 series_name 前缀匹配自动关联 |
| 掉包检测系统 | 未提及 | 完整实现：`delist_checker.py` + 通知/提醒/关闭 + Telegram @ 通知 |
| Google Sheets 集成 | 未提及 | `google_sheets_service.py` + 同步日志 + 异步重试 |
| 数据导入/导出 | 未提及 | `data_service.py` + `manage.py` CLI + import_history 审计 |
| 产品合并功能 | 未提及 | POST `/api/products/merge` 合并重复产品 |
| 批量操作 | 未提及 | 批量删除包/账户/MCC，批量创建账户，批量更新，批量导入视频/充值 |
| 审计日志 | 暂不包含 | **已实现**：`audit_log` 表 + 产品删除恢复 API |
| 定时任务 | 未提及 | scheduler 系统 + `/admin/scheduler` 管理页（仅 developer） |
| 地区时区管理 | 未提及 | `regions` 表 + CRUD API + 25+ 预设时区 |
| Python 包冲突处理 | 未提及 | `sys.path.insert(0, _current_dir)` 确保 `py/` 优先于 site-packages |
| 日志系统 | 未提及 | 全局 logging + Werkzeug 高频接口日志过滤 + 请求级 `[时间] METHOD /path -> status (ms)` |

### 12. 总结

设计文档作为初始规划文件，准确描述了用户系统、JWT 认证、数据隔离的核心方向。但实际代码在以下方面有显著扩展：

1. **模块化路由架构**（`routes/` 包 + Blueprint）
2. **viewer 角色**和更细粒度的角色隔离
3. **滑动 JWT 过期**替代固定 refresh token
4. **13 个额外数据库表**覆盖广告报告、掉包检测、审计日志、Google Sheets 集成等
5. **runner 机制**（product_runners 关联表 + JSON 列双存储）
6. **MCC 多用户共享**（shared_user_ids + 链式遍历）
7. **完整的 CLI 工具链**（manage.py 备份/恢复/导入/导出）
8. **掉包检测 + 通知系统**（轮询 + 跨 Tab 同步 + Telegram @ 通知）
9. **PyInstaller 打包**（已实现，含 ffmpeg bundle）
10. **定时任务系统**（scheduler）
11. **操作日志审计**（已在第 11 节标记为"暂不包含"，但实际已实现）