# GG-Server 多人协作版设计文档

> 基于 ImageCrawling（谷歌广告图片爬取与处理工具）改造的多人协作服务器版本。
> 新增用户系统、数据隔离、权限管理，支持局域网内多人同时使用。

## 项目概述

谷歌广告运营工具箱的多人协作版本 — 包含图片爬取、AI 视频生成、YouTube 视频管理、产品管理、数据做表、广告账户管理等模块。

### 与 ImageCrawling 的关系
- **ImageCrawling**：单用户本地工具，PyInstaller 打包为独立 EXE
- **GG-Server**：从 ImageCrawling 复制的独立项目，叠加用户系统 + 数据隔离，作为常开 Flask 服务运行
- 两个项目互不干扰，可并存使用

## 技术栈

| 组件 | 选择 | 说明 |
|------|------|------|
| 后端框架 | Flask | 纯 API 服务，~2000 行集中在 main.py |
| 数据库 | SQLite (WAL 模式) | `temp/app.db`，局域网 20 人以下足够 |
| 认证 | Flask-JWT-Extended | JWT token，24h 过期 |
| 密码 | Werkzeug pbkdf2:sha256 | Flask 内置哈希 |
| 前端 | Vue 3 + Vite + Element Plus + Pinia + Vue Router | Composition API |
| HTTP | axios | 全局拦截器自动携带 JWT token |
| 部署 | 常开 Python 服务（`python main.py`） | 暂不打包 EXE |

## 核心架构

```
局域网内
  Server PC (常开)
  +-----------------------------------------+
  |  Flask (0.0.0.0:5001)                  |
  |  +- JWT Auth Middleware                 |
  |  +- API Routes (with user_id scoping)   |
  |  +- SQLite (WAL mode, temp/app.db)      |
  |  +- 前端静态文件 (frontend/dist/)        |
  +-----------------------------------------+
          ↑ HTTP / JSON + JWT Bearer Token
  +-----------------------------------------+
  |  Vue 3 + Vite (frontend/)               |
  |  +- Login / Register pages              |
  |  +- Router guards (auth check)          |
  |  +- Per-user data display               |
  +-----------------------------------------+

  PC1 浏览器    PC2 浏览器    PC3 浏览器
  访问 :5001    访问 :5001    访问 :5001
```

## 数据模型

### 用户表 (users)

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

### 角色权限

| 角色 | 可创建 | 可管理用户 | 可删除数据 | 注册方式 |
|------|--------|-----------|-----------|---------|
| developer | 全部角色 | 全部 | 全部 | 配置文件中预置 |
| admin | 仅 user | 管理 user | 全部 | 由 developer 创建 |
| user | 不能创建 | 不可 | 自己的数据 | 开放注册 |
| hidden | - | - | - | 被停用，无法登录 |

### 数据隔离设计

#### 共享数据（所有人可见）
- `products` / `packages` — 产品管理
- `scrape_cache` — 爬取缓存（同包名命中跳过爬取）
- `yt_videos`（is_public=1）— YouTube 公共视频库

#### 个人数据（按 user_id 隔离）
- `user_accounts` — 广告账户管理
- `user_mcc` — MCC 管理
- `scrape_history` — 图片爬取记录
- `video_history` — AI 视频生成历史
- `yt_videos`（is_public=0）— YouTube 个人视频库

#### YouTube 双层模型
- `yt_videos` 表有 `owner_id` 和 `is_public` 字段
- `is_public=1` → 公共库，所有人可查看
- `is_public=0` → 仅 owner 可见
- 导入时默认私人，用户可手动标记为公开

## 认证系统

### API 认证流程

1. 用户 POST `/api/auth/login` → 返回 JWT access_token + refresh_token
2. 前端 axios 拦截器自动携带 `Authorization: Bearer <token>`
3. 后端 `@jwt_required()` 装饰器验证 token，`get_jwt_identity()` 获取用户 ID
4. token 过期（24h）→ 前端自动跳转登录页

### 路由保护
- 所有 API 路由（除 /api/auth/login 和 /api/auth/register）都需 JWT 认证
- admin 路由额外检查 `role in ('developer', 'admin')`
- 前端全局路由守卫：未登录 → /login，非 admin → /accounts

## 项目结构

```
GG-Server/
├── frontend/                  # Vue 3 前端
│   ├── src/
│   │   ├── api/               # axios API 模块
│   │   │   ├── client.js      # axios 实例 + JWT 拦截器
│   │   │   ├── auth.js        # 登录/注册 API
│   │   │   ├── admin.js       # 用户管理 API
│   │   │   ├── accounts.js    # 账户/MCC API
│   │   │   ├── products.js    # 产品管理 API
│   │   │   ├── youtube.js     # YouTube API
│   │   │   ├── video.js       # 视频生成 API
│   │   │   └── scrape.js      # 爬取 API
│   │   ├── stores/            # Pinia 状态管理
│   │   │   ├── auth.js        # 认证状态
│   │   │   ├── products.js    # 产品状态
│   │   │   ├── accounts.js    # 账户状态
│   │   │   ├── youtube.js     # YouTube 状态
│   │   │   └── video.js       # 视频状态
│   │   ├── views/             # 页面组件
│   │   │   ├── LoginView.vue
│   │   │   ├── RegisterView.vue
│   │   │   ├── UserManageView.vue
│   │   │   ├── AccountsView.vue
│   │   │   ├── ScrapeView.vue
│   │   │   ├── VideoView.vue
│   │   │   ├── YoutubeView.vue
│   │   │   └── ToolkitView.vue
│   │   ├── router/index.js    # Vue Router
│   │   └── App.vue            # 根组件
│   └── dist/                  # 生产构建产物
├── py/
│   ├── main.py               # Flask API 入口（所有路由）
│   ├── auth.py               # 认证模块（登录/注册/角色管理）
│   ├── database.py            # SQLite 统一存储
│   ├── scraper.py             # Google Play 图片爬取
│   ├── resizer.py             # 图片缩放处理
│   ├── utils.py               # 工具函数
│   ├── video_processor.py     # FFmpeg 视频生成
│   └── ai_service.py          # AI 视频 API 调用
├── config/
│   └── config.json           # 服务器配置（含 developer 账号）
├── temp/                     # 运行时数据
│   └── app.db                # SQLite 数据库
├── fonts/                    # 用户字体文件
├── requirements.txt
└── AGENTS.md                 # 本文档
```

## API 路由一览

### 认证
| 方法 | 路径 | 说明 |
|------|------|------|
| POST | /api/auth/login | 登录，返回 JWT token |
| POST | /api/auth/register | 注册（仅 user 级别） |
| POST | /api/auth/refresh | 刷新 token |
| GET | /api/auth/me | 获取当前用户信息 |

### 用户管理（admin/developer）
| 方法 | 路径 | 说明 |
|------|------|------|
| GET | /api/admin/users | 用户列表（搜索/分页） |
| POST | /api/admin/users/:id/role | 修改用户角色 |
| POST | /api/admin/users/:id/toggle | 启用/禁用 |
| DELETE | /api/admin/users/:id | 删除用户 |

### 其他模块路由（参考 ImageCrawling 文档）
- 图片爬取、AI 视频生成、YouTube 管理、产品管理、广告账户、工具集等
- 所有路由均需 `@jwt_required()`，返回 `{"success": bool, ...}` 格式

## 启动方式

```bash
# 1. 安装依赖
pip install -r requirements.txt
pip install flask-jwt-extended

# 2. 修改 config/config.json 中的 developer 账号和 secret_key

# 3. 启动
cd py
python main.py
# 打开浏览器访问 http://localhost:5001

# 前端开发模式（另一个终端）
cd frontend
npm run dev
# Vite dev server :5173，自动代理 /api 到 Flask :5001
```

## 配置说明 (config/config.json)

```json
{
  "secret_key": "jwt签名密钥",
  "jwt_expire_hours": 24,
  "jwt_refresh_days": 7,
  "developer": {
    "username": "carl567",
    "password": "1976xiaobai"
  },
  "server": {
    "host": "0.0.0.0",
    "port": 5001,
    "debug": false
  },
  "scrape_cache_dir": "temp/scrape_cache"
}
```

## 开发注意

- 从 `py/` 目录内运行 `python main.py`（`sys.path` 依赖目录结构）
- Flask 端口 5001，Vite 端口 5173，CORS 已配置
- 首次启动自动创建 users 表 + developer 账号
- 新建 Vue 组件后需 `npm run build` 刷新前端静态文件
- SQLite 数据库自动建表 + 迁移，位于 `temp/app.db`
- 本项目是 ImageCrawling 的独立副本，修改不影响原项目
