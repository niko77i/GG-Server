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

### 其他模块路由

所有路由均需 `@jwt_required()`，返回 `{"success": bool, ...}` 格式。具体路由定义参考 ImageCrawling CLAUDE.md。

## 共享功能知识（来自 ImageCrawling）

> 以下核心业务逻辑与 ImageCrawling 共享，详见 ImageCrawling 的 CLAUDE.md。

### 图片爬取

- 只爬取 `<c-wiz jsrenderer="UZStuc">` 标签内的图片
- 高清 URL 升级：`scraper.py` 的 `_upgrade_image_url()` 将 Google CDN 图片 URL 中的 `=w数字-h数字` 替换为 `=w2400-h2400`
- 支持本地缓存命中：如果目标目录已有 PNG 文件，跳过爬取直接返回（`from_cache: true`）

### 图片缩放算法

1. `detect_format(w, h)` 根据宽高比判断规格：ratio > 1.3 → landscape，ratio ≤ 0.8 → portrait，否则 → square
2. 如果短边小于该规格的 `min_short`，等比放大到短边 = min_short，保持原始宽高比
3. 保存为 PNG（optimize=True，RGBA 转 RGB）
4. 如果文件 > 5 MiB，以 0.85 倍逐步缩小直到 ≤ 5 MiB 或低于最小尺寸

| 类型 | min_short | 宽高比判断 |
|------|-----------|-----------|
| landscape | 314 | 宽/高 > 1.3 |
| square    | 200 | > 0.8 且 ≤ 1.3 |
| portrait  | 320 | 宽/高 ≤ 0.8 |

### 异常设计

| 异常 | 所在模块 | 触发场景 |
|------|---------|---------|
| `ScrapeError` | `scraper.py` | 页面不可访问、未找到目标标签 |
| `ResizeError` | `resizer.py` | 图片下载失败、无法识别格式 |
| `VideoError` | `video_processor.py` | FFmpeg 执行失败、参数非法 |
| `AIServiceError` | `ai_service.py` | AI API 调用失败、认证错误 |
| `ValueError` | `utils.py` | 无法从 URL 提取包名 |

`main.py` 在顶层捕获这些异常并转为对应的 HTTP 错误响应。单张图片处理失败不中断其他图片，AI 单段生成失败降级为静态帧。

### 脏数据解析 (`_guess_series`)

`/api/products/import-text` 端点使用 `_guess_series()` 从聊天记录等脏数据中自动解析 Google Play 链接和系列名。

支持 7 种格式，按优先级匹配：
**类型2（神包上线）→ 类型7（广告命名/渠道命名）→ 类型1（APK行）→ 类型3（应用名在链接后）→ 类型4（名称行）→ 类型6（首列含 `-`）→ 类型5（包名兜底）**

详细格式示例见 ImageCrawling 的 `NOTES.md` 或 `docs/superpowers/specs/account-product-management-design.md`。新增脏数据类型时，需在两个项目同步更新此逻辑。

### AI 视频生成

- 视频面板流程：选择目录 → 扫描图片（缩略图网格预览）→ 勾选 → 设置参数 → 生成 MP4
- 混合方案：默认本地 FFmpeg 拼接（零成本），可选 AI 动态化
- Logo 水印：6 种效果（静态/淡入淡出/浮动弹跳/放大进入/从右滑入/脉冲缩放）+ 5 个位置（左上/右上/左下/右下/浮动）
- 转场效果：14 种（淡入淡出/黑场/白场/滑动/缩放/溶解/像素化/圆形/擦除等）
- 动态背景：呼吸/波浪/律动/流光
- 文案浮层：最多两条，随机浮现 2-3 秒，淡入淡出 + 阴影描边
- 任务队列：支持添加多个任务到队列，一键生成全部
- 视频设置历史：按包名保存/恢复设置（存储在 SQLite `video_history` 表）

| AI Provider | 后端模型 | 特点 |
|-------------|---------|------|
| doubao | 豆包 Seedance 1.5 Pro | 首选推荐，效果最佳 |
| doubao-fast | 豆包 Seedance 1.0 Pro Fast | 极速模式 |
| seedance | Seedance 2.0（字节/即梦） | 每日免费积分 |
| veo | Veo 3.1 Lite（Google） | 免费，视频自带音频 |
| atlas | Atlas Cloud 多模型 | 一个 Key 切换 300+ 模型 |

- FFmpeg 通过 `_get_ffmpeg_path()` 自动探测（开发模式从项目根目录，打包模式从 `sys._MEIPASS`）
- Flask 需 `threaded=True`（视频生成在后台线程执行，AI 动态化使用 ThreadPoolExecutor 并行）

### YouTube 视频管理

- SQLite 存储，地区/帧类型/成效/产品名 4 维分类
- 批量导入（自动通过 oEmbed 获取标题）、批量删除、批量编辑
- 搜索过滤 + 分页（10/20/50/100 条/页）
- 内嵌 YouTube 播放器 + 复制链接（记录复制历史到 localStorage）
- 标签配置面板：自定义下拉选项，修改后自动同步已有数据
- 成效排序优先（成效 > 一般 > 未标记），同级别按导入时间倒序

### 产品管理

- 产品-包 两级结构：一个产品可以有多个包
- 支持搜索（产品名/KPI）、地区筛选、暂停/正常切换
- 同一产品下相同包名+链接视为重复，只更新系列名

### 工具集

- **做表数据**：从 Google Ads 原始竖排数据解析账号/客户ID/广告系列/费用/展示/点击，三种视图（原始清洗/按客户ID+广告系列聚合/按广告系列聚合），一键复制 TSV + 导出 XLSX
- **音频替换**：FFmpeg `-c:v copy -map 0:v:0 -map 1:a:0 -shortest`，支持音频文件和视频文件作为音频源

### 导入约定

所有 Python 文件使用绝对导入（无前导点），`main.py` 开头通过 `sys.path.insert(0, _current_dir)` 确保导入正确。`database.py` 独立计算 `_db_path()`。

## 与 ImageCrawling 的关系

本项目从 ImageCrawling 演进而来（单用户本地工具 → 多人协作服务器）。核心业务逻辑（爬取/视频/YouTube/产品/脏数据解析/AI服务等）共享。

**文档同步规则**：
- 任何涉及共享功能的改动，必须在两个项目同步更新文档
- 修改共享逻辑时，检查是否需要同步更新 AGENTS.md / CLAUDE.md / NOTES.md / 设计文档
- ImageCrawling 路径：`f:\carl_work\carl\Google\cc\ImageCrawling\`

## 设计文档索引

### 共享功能设计文档
- [图片爬取](docs/superpowers/specs/image-scraping-design.md)
- [AI 视频生成](docs/superpowers/specs/ai-video-generation-design.md)
- [YouTube 视频管理](docs/superpowers/specs/youtube-video-management-design.md)
- [账户与产品管理](docs/superpowers/specs/account-product-management-design.md)
- [Google Ads API](docs/superpowers/specs/google-ads-api-design.md)
- [SQLite 统一存储](docs/superpowers/specs/sqlite-unified-storage-design.md)
- [Vue 前端重构](docs/superpowers/specs/vue-migration-design.md)
- [文案管理](docs/superpowers/specs/2026-06-15-copywriting-management-design.md)
- [审核状态筛选](docs/superpowers/specs/2026-06-16-review-status-filter-design.md)
- [日期选择器与视频标记](docs/superpowers/specs/2026-06-21-date-picker-video-markers-design.md)

### GG-Server 独立设计文档
- [GG-Server 多人协作版](docs/superpowers/specs/2026-06-23-gg-server-design.md)
- [数据迁移方案](docs/superpowers/specs/2026-06-26-data-migration-design.md)
- [用户管理改进](docs/superpowers/specs/2026-06-27-user-management-improvements-design.md)
- [视频上传者标签筛选](docs/superpowers/specs/2026-06-27-video-uploader-label-filter-design.md)

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
- **Tailscale 部署**：其他电脑只能访问 5001，无法访问 5173。前端改动后必须 `npm run build` 其他人才能看到
- 首次启动自动创建 users 表 + developer 账号
- **任何前端改动后，必须提醒我 `npm run build` 重新构建**
- **任何后端代码（py/main.py 等）修改后，必须提醒我重启 Flask 服务才能生效**
- **每次改完 bug 或完成需求后，提醒我提交 git**
- SQLite 数据库自动建表 + 迁移，位于 `temp/app.db`
- 本项目是 ImageCrawling 的独立副本，修改不影响原项目
