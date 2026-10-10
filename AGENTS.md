# GG-Server 多人协作版设计文档

> 基于 ImageCrawling（谷歌广告图片爬取与处理工具）改造的多人协作服务器版本。
> 新增用户系统、数据隔离、权限管理，支持局域网内多人同时使用。

## 项目概述

谷歌广告运营工具箱的多人协作版本 — 包含图片爬取、AI 视频生成、YouTube 视频管理、产品管理、数据做表、广告账户管理、充值管理、掉包检测、数据分析、全局任务追踪、Facebook（FB）广告平台管理、TikTok（TT）广告平台管理、代理池等模块。

> **三平台并行**：GG（Google Ads）、FB（Facebook）、TT（TikTok）三套业务数据相互隔离，
> 各自有独立的页面、Blueprint 和表前缀（无前缀 / `fb_` / `tt_`）；仅 developer 可跨平台切换，
> 户管（huguan）角色只作用于 GG。

### 与 ImageCrawling 的关系
- **ImageCrawling**：单用户本地工具，PyInstaller 打包为独立 EXE
- **GG-Server**：从 ImageCrawling 复制的独立项目，叠加用户系统 + 数据隔离，作为常开 Flask 服务运行
- 两个项目互不干扰，可并存使用

## 技术栈

| 组件 | 选择 | 说明 |
|------|------|------|
| 后端框架 | Flask | 纯 API 服务，main.py ~9800 行 + routes/ 目录 |
| 数据库 | SQLite (WAL 模式) | `temp/data/app.db`，局域网 20 人以下足够 |
| 认证 | Flask-JWT-Extended | JWT token，24h 过期，支持滑动刷新 |
| 密码 | Werkzeug pbkdf2:sha256 | Flask 内置哈希 |
| 前端 | Vue 3 + Vite + Element Plus + Pinia + Vue Router | Composition API |
| HTTP | axios | 全局拦截器自动携带 JWT token |
| 定时任务 | 后台 daemon 线程 | 掉包检测（**GG 每小时 / TT 每 30 分钟**，走代理池）、每周清理 |
| 跨标签同步 | BroadcastChannel | 多 Tab 任务状态和通知同步 |
| 外部通知 | Telegram Bot + Email | 掉包通知推送到群组/邮件 |
| 代理池 | proxy_pool.py | 掉包检测随机切换代理 IP，避免风控/限流 |
| 部署 | 常开 Python 服务（`python main.py`） | 暂不打包 EXE |

## 核心架构

```
局域网内
  Server PC (常开)
  +-----------------------------------------+
  |  Flask (0.0.0.0:5001)                  |
  |  +- JWT Auth Middleware                 |
  |  +- API Routes (with user_id scoping)   |
  |  +- SQLite (WAL mode, temp/data/app.db) |
  |  +- 前端静态文件 (frontend/dist/)        |
  |  +- 后台定时线程 (掉包检测/每周清理)      |
  +-----------------------------------------+
          ↑ HTTP / JSON + JWT Bearer Token
  +-----------------------------------------+
  |  Vue 3 + Vite (frontend/)               |
  |  +- Login / Register pages              |
  |  +- Router guards (auth check)          |
  |  +- Per-user data display               |
  |  +- GlobalTaskPanel (全局任务浮动面板)    |
  |  +- BroadcastChannel (多标签同步)        |
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
    custom_name TEXT DEFAULT '',
    platform    TEXT DEFAULT 'gg',   -- 'gg' | 'fb' | 'tt'，developer 三平台
    created_at  TEXT NOT NULL DEFAULT (datetime('now')),
    last_login  TEXT,
    created_by  INTEGER REFERENCES users(id),
    config      TEXT DEFAULT '{}'
    -- telegram_username / email 由迁移新增
);
```

### 角色权限

| 角色 | 可创建 | 可管理用户 | 可删除数据 | 注册方式 |
|------|--------|-----------|-----------|---------|
| developer | 全部角色 | 全部 | 全部 | 配置文件中预置 |
| admin | 仅 user | 管理 user | 全部 | 由 developer 创建 |
| user | 不能创建 | 不可 | 自己的数据 | 开放注册 |
| viewer | 只读 | 不可 | 不可 | 由 admin 创建 |
| hidden | - | - | - | 被停用，无法登录 |

### 数据隔离设计

#### 共享数据（所有人可见）
- `products` / `packages` — GG 产品管理
- `scrape_cache` — 爬取缓存（同包名命中跳过爬取）
- `videos`（is_public=1）— YouTube 公共视频库
- `fb_products` / `fb_bms` / `fb_pixel_bms` / `fb_pixels` / `fb_lines` — FB 平台数据
- `tt_products` / `tt_packages` / `tt_bcs` / `tt_recycle_reasons` — TT 平台数据
- 字典表 `agents` / `account_statuses` / `mcc_levels` / `sales_persons` / `regions` — GG/FB/TT 共用

#### 个人数据（按 user_id 隔离）
- `accounts` — GG 广告账户管理（owner_id）
- `mcc` — GG MCC 管理（owner_id）
- `video_history` — AI 视频生成历史
- `videos`（is_public=0）— YouTube 个人视频库
- `ad_reports` / `fb_ad_reports` — 做表数据（TT 数据提取为纯前端解析，不落库）
- `recharge_records` / `tt_recharge_records` — 充值记录（created_by 隔离）

#### YouTube 双层模型
- `videos` 表有 `owner_id` 和 `is_public` 字段
- `is_public=1` → 公共库，所有人可查看
- `is_public=0` → 仅 owner 可见
- 导入时 admin/developer 默认私人，普通用户/viewer 默认公开

## 认证系统

### API 认证流程

1. 用户 POST `/api/auth/login` → 返回 JWT access_token + refresh_token
2. 前端 axios 拦截器自动携带 `Authorization: Bearer <token>`
3. 后端 `@jwt_required()` 装饰器验证 token，`get_jwt_identity()` 获取用户 ID
4. token 过期（24h）→ 前端自动跳转登录页
5. **JWT 滑动过期**：每次 API 请求自动刷新 token 过期时间

### 路由保护
- 所有 API 路由（除 /api/auth/login 和 /api/auth/register）都需 JWT 认证
- admin 路由额外检查 `role in ('developer', 'admin')`
- developer 专属路由检查 `role == 'developer'`
- viewer 角色对所有写操作返回 403
- 前端全局路由守卫：未登录 → /login，非 admin → /accounts

## 项目结构

```
GG-Server/
├── frontend/                       # Vue 3 前端
│   ├── src/
│   │   ├── api/                    # axios API 模块
│   │   │   ├── client.js           # axios 实例 + JWT 拦截器（滑动过期）
│   │   │   ├── auth.js             # 登录/注册 API
│   │   │   ├── admin.js            # 用户管理 API
│   │   │   ├── accounts.js         # 账户/MCC/充值 API
│   │   │   ├── products.js         # 产品管理 API（含掉包检测）
│   │   │   ├── youtube.js          # YouTube API
│   │   │   ├── video.js            # 视频生成 API
│   │   │   ├── scrape.js           # 爬取 API
│   │   │   ├── google-sheets.js    # Google Sheets 配置 API
│   │   │   ├── reports.js          # 做表数据 API
│   │   │   ├── data.js             # 数据分析 API
│   │   │   ├── browse.js           # 文件浏览 API
│   │   │   └── fb.js               # FB 平台 API
│   │   ├── stores/                 # Pinia 状态管理
│   │   │   ├── auth.js             # 认证状态
│   │   │   ├── products.js         # 产品状态
│   │   │   ├── accounts.js         # 账户状态
│   │   │   ├── youtube.js          # YouTube 状态
│   │   │   ├── video.js            # 视频状态
│   │   │   └── taskRunner.js       # 全局任务追踪（跨标签同步）
│   │   ├── utils/                  # 工具函数
│   │   │   ├── broadcast.js        # BroadcastChannel 封装（多标签同步）
│   │   │   ├── dedupLoader.js      # 防重复加载 guard
│   │   │   ├── statusTag.js        # 状态标签工具
│   │   │   ├── adsParser.js        # 广告数据解析
│   │   │   ├── clipboard.js        # 剪贴板工具
│   │   │   └── env.js              # 环境判断
│   │   ├── composables/            # 组合式函数
│   │   │   ├── useDebounce.js      # 防抖
│   │   │   └── usePagination.js    # 分页
│   │   ├── views/                  # 页面组件
│   │   │   ├── LoginView.vue
│   │   │   ├── RegisterView.vue
│   │   │   ├── UserManageView.vue
│   │   │   ├── UserProfileView.vue     # 用户配置（Google Sheets 等）
│   │   │   ├── AccountsView.vue        # 账户管理容器
│   │   │   ├── AdsAccountPanel.vue     # 广告账户面板
│   │   │   ├── MccPanel.vue            # MCC 管理面板
│   │   │   ├── ProductPanel.vue        # 产品管理面板
│   │   │   ├── SettingsPanel.vue       # 系统设置（商务管理/充值表配置）
│   │   │   ├── ScrapeView.vue
│   │   │   ├── MediaView.vue           # 统一媒体页面
│   │   │   ├── VideoView.vue
│   │   │   ├── YoutubeView.vue
│   │   │   ├── ToolkitView.vue         # 做表数据 + 音频替换
│   │   │   ├── AnalysisView.vue        # 数据分析看板
│   │   │   ├── DataManageView.vue      # 数据管理
│   │   │   ├── SchedulerView.vue       # 定时任务（按平台管理员）
│   │   │   ├── fb/                     # FB 平台页面
│   │   │       ├── FbAccountPanel.vue  # FB 账户管理
│   │   │       ├── FbBmPanel.vue       # FB 账户 BM 管理
│   │   │       ├── FbProductPanel.vue  # FB 产品管理
│   │   │       ├── FbPixelPanel.vue    # FB 像素管理
│   │   │       ├── FbPixelBmPanel.vue  # FB 像素 BM 管理
│   │   │       ├── FbDataExtract.vue   # FB 数据提取
│   │   │       ├── FbDataManage.vue    # FB 数据管理
│   │   │       └── FbSettingsPanel.vue # FB 系统设置
│   │   │   └── tt/                     # TT 平台页面
│   │   │       ├── TtView.vue          # TT 账户管理容器
│   │   │       ├── TtAccountPanel.vue  # TT 广告账户面板
│   │   │       ├── TtBcPanel.vue       # TT 商务中心（BC）管理
│   │   │       ├── TtProductPanel.vue  # TT 产品管理
│   │   │       ├── TtDataExtract.vue   # TT 数据提取
│   │   │       └── TtSettingsPanel.vue # TT 系统设置
│   │   ├── components/             # 公共组件
│   │   │   ├── AppSidebar.vue
│   │   │   ├── ProductCard.vue
│   │   │   ├── ProductModal.vue
│   │   │   ├── ProductDetailModal.vue
│   │   │   ├── AddPackageModal.vue
│   │   │   ├── AccountModal.vue        # 账户编辑弹窗（含死亡清账提醒）
│   │   │   ├── AccountDetailModal.vue  # 账户详情（含充值记录+MCC 历史）
│   │   │   ├── AccountSyncModal.vue     # 账户表格同步弹窗
│   │   │   ├── AccountDeletedModal.vue  # 已删除账户恢复/永久删除弹窗
│   │   │   ├── AccountBatchImportModal.vue
│   │   │   ├── AccountBatchLookupModal.vue  # 批量查户弹窗
│   │   │   ├── RechargeModal.vue       # 单次充值弹窗
│   │   │   ├── RechargeBatchModal.vue  # 批量充值弹窗
│   │   │   ├── MccModal.vue
│   │   │   ├── MccDetailModal.vue
│   │   │   ├── CopyImportModal.vue
│   │   │   ├── GlobalTaskPanel.vue     # 全局任务浮动面板
│   │   │   ├── TtProductCard.vue       # TT 产品卡片
│   │   │   ├── TtAddPackageModal.vue   # TT 新增投放对象弹窗
│   │   │   ├── tt/                     # TT 弹窗（账户/充值/回收，与 GG 同构）
│   │   │   │   ├── TtAccountModal.vue / TtAccountDetailModal.vue
│   │   │   │   ├── TtAccountBatchImportModal.vue / TtAccountBatchLookupModal.vue
│   │   │   │   ├── TtAccountSyncModal.vue / TtAccountDeletedModal.vue
│   │   │   │   ├── TtRechargeModal.vue / TtRechargeBatchModal.vue
│   │   │   │   └── TtRecycleReasonModal.vue
│   │   │   └── youtube/
│   │   │       ├── TagsConfig.vue      # YouTube 标签配置
│   │   │       ├── ImportTab.vue       # YouTube 导入 Tab
│   │   │       └── CopywritingTab.vue  # YouTube 文案 Tab
│   │   ├── router/index.js        # Vue Router
│   │   └── App.vue                # 根组件（全局通知轮询 + 任务面板）
│   └── dist/                      # 生产构建产物
├── py/
│   ├── main.py                    # Flask 入口 + 大量路由（~9800 行，持续拆分中）
│   ├── auth.py                    # 认证模块（登录/注册/角色管理）
│   ├── database.py                # SQLite 统一存储（40 张表，自动迁移）
│   ├── scraper.py                 # Google Play 图片爬取
│   ├── resizer.py                 # 图片缩放处理
│   ├── utils.py                   # 工具函数
│   ├── video_processor.py         # FFmpeg 视频生成
│   ├── ai_service.py              # AI 视频 API 调用
│   ├── cache.py                   # 缓存服务
│   ├── data_service.py            # 数据分析服务
│   ├── google_sheets_service.py   # Google Sheets API 封装（充值/做表写入）
│   ├── google_ads_service.py      # Google Ads API 封装
│   ├── delist_checker.py          # 掉包检测核心逻辑
│   ├── proxy_pool.py              # 代理池（掉包检测走代理 IP 防风控）
│   ├── telegram_sender.py         # Telegram Bot 通知
│   ├── email_sender.py            # 邮件通知
│   ├── manage.py                  # 管理工具脚本
│   ├── migrate_from_production.py # 生产环境数据迁移脚本
│   ├── routes/
│   │   ├── __init__.py            # 包标记（Blueprint 在 main.py 注册）
│   │   ├── decorators.py          # 权限装饰器（_reject_viewer、_require_developer 等）
│   │   ├── helpers.py             # 公共工具函数（scope_where、can_modify 等）
│   │   ├── auth_routes.py         # 认证相关 Blueprint（已激活，12 路由）
│   │   ├── fb_routes.py           # FB 平台 Blueprint（已激活，53 路由）
│   │   └── tt_routes.py           # TT 平台 Blueprint（已激活，30 路由）
│   └── tests/                     # 测试文件
├── config/
│   └── config.json                # 服务器配置（含 developer 账号）
├── temp/                          # 运行时数据
│   └── app.db                     # SQLite 数据库
├── fonts/                         # 用户字体文件
├── requirements.txt
└── AGENTS.md                      # 本文档
```

## API 路由一览

### 认证
| 方法 | 路径 | 说明 |
|------|------|------|
| POST | /api/auth/login | 登录，返回 JWT token |
| POST | /api/auth/register | 注册（仅 user 级别） |
| POST | /api/auth/refresh | 刷新 token |
| GET | /api/auth/me | 获取当前用户信息 |
| GET/PUT | /api/auth/custom-name | 自定义昵称 |
| GET/PUT | /api/auth/email | 邮箱 |
| PUT | /api/auth/telegram-username | Telegram 用户名 |
| PUT | /api/auth/password | 修改密码 |
| PUT | /api/auth/profile | 更新个人信息 |
| GET | /api/auth/names | 用户列表（下拉用） |

### 用户管理（admin/developer）
| 方法 | 路径 | 说明 |
|------|------|------|
| GET | /api/admin/users | 用户列表（搜索/分页） |
| POST | /api/admin/users/create | 创建用户（选 GG/FB 平台） |
| POST | /api/admin/users/:id/role | 修改用户角色 |
| POST | /api/admin/users/:id/toggle | 启用/禁用 |
| PUT | /api/admin/users/:id | 编辑用户 |
| PUT | /api/admin/users/:id/password | 重置密码 |
| PUT | /api/admin/users/:id/telegram-username | 设置 Telegram 用户名 |
| DELETE | /api/admin/users/:id | 删除用户 |

### 广告账户管理（GG）
| 方法 | 路径 | 说明 |
|------|------|------|
| GET | /api/accounts/list | 账户列表 |
| POST | /api/accounts/create | 创建账户 |
| POST | /api/accounts/batch-create | 批量导入 |
| POST | /api/accounts/batch-update | 批量更新 |
| POST | /api/accounts/sync-from-sheet | 从 Google Sheets 同步账户 |
| PUT | /api/accounts/:id | 编辑账户 |
| PUT | /api/accounts/:id/reassign | 账户认领转移 |
| DELETE | /api/accounts/:id | 删除账户（软删除） |
| GET | /api/accounts/deleted | 已删除账户列表 |
| POST | /api/accounts/:id/restore | 恢复账户 |
| DELETE | /api/accounts/:id/permanent | 永久删除 |

### 字典表（选项表，GG/FB 共用）
| 方法 | 路径 | 说明 |
|------|------|------|
| GET/POST/PUT/DELETE | /api/agents[/:id] | 代理管理 |
| GET/POST/PUT/DELETE | /api/statuses[/:id] | 账户状态管理 |
| GET/POST/PUT/DELETE | /api/mcc-levels[/:id] | MCC 等级管理 |
| GET/POST/PUT/DELETE | /api/sales-persons[/:id] | 商务管理 |
| GET/POST/PUT/DELETE | /api/regions[/:id] | 地区管理 |

### 充值管理
| 方法 | 路径 | 说明 |
|------|------|------|
| POST | /api/recharge/submit | 单次充值 |
| POST | /api/recharge/batch-submit | 批量充值 |
| GET | /api/accounts/:id/recharge-records | 查询充值记录（按账户ID） |
| PUT | /api/recharge/:id | 编辑充值记录 |
| DELETE | /api/recharge/:id | 删除充值记录 |
| POST | /api/recharge/:id/retry-sheets | 重试写充值表 |

### 掉包检测
| 方法 | 路径 | 说明 |
|------|------|------|
| POST | /api/products/:pid/check-delist | 手动检测产品掉包（走代理池） |
| GET | /api/products/delist-status | 获取掉包检测状态 |
| GET | /api/delist/pending | 获取当前用户待处理通知（按产品聚合） |
| POST | /api/delist/dismiss | 关闭掉包通知（支持批量） |

### 定时任务（按平台的管理员 / developer）
| 方法 | 路径 | 说明 |
|------|------|------|
| POST | /api/admin/trigger-delist-check | 手动触发掉包检测 |
| POST | /api/admin/trigger-tt-delist-check | 手动触发 TT 掉包检测 |
| POST | /api/admin/trigger-weekly-cleanup | 手动触发每周清理 |
| GET | /api/admin/scheduler/config | 读取定时任务配置 + 上次执行时间（admin 限本平台；developer 全部三项） |
| PUT | /api/admin/scheduler/config | 修改定时任务周期（admin 限本平台字段；developer 全部字段；越权字段 403） |

**权限归属**：GG 管理员 → `trigger-delist-check` + `trigger-weekly-cleanup`；TT 管理员 → `trigger-tt-delist-check`；
FB 管理员 → 该平台无定时任务（页面显示空态）；户管 / 普通用户 → 一律 403（首页菜单里本就没有入口）。
⚠️ **这层限制勿用 `require_platform`** —— `PLATFORM_SWITCH_ROLES` 含户管，用了等于给户管开后门。
三个 trigger 的 POST 与 PUT 走专用装饰器 `scheduler_required(platform)`（developer 跨平台放行，admin 须平台匹配）；
**GET 刻意不套它** —— 仅要求 admin/developer，好让无任务的 FB 管理员拿到**空数组**而非 403（空数组 ≠ 无权限），前端据此渲染空态。

### 做表数据 / Google Sheets
| 方法 | 路径 | 说明 |
|------|------|------|
| GET/POST | /api/config/google-sheets | 用户 Google Sheets 配置 |
| GET/POST | /api/settings/account | 账户设置（含 recharge_sheet_id） |
| POST | /api/google-sheets/update-zuobiao | 做表数据写入用户表格 |

### 数据分析
| 方法 | 路径 | 说明 |
|------|------|------|
| GET | /api/ad-reports/dashboard | 仪表盘关键指标 |
| GET | /api/ad-reports/trends | 趋势数据 |
| GET | /api/ad-reports/compare | 对比分析 |
| GET | /api/ad-reports/multi-analysis | 多维自由分析（散点图/相关性） |
| POST | /api/ad-reports/analyze | AI 智能解读 |

### FB 平台（fb_routes.py，53 路由）
| 方法 | 路径 | 说明 |
|------|------|------|
| GET/POST/PUT/DELETE | /api/fb/bms/... | 账户 BM 管理（含 ban-and-migrate） |
| GET/POST/PUT/DELETE | /api/fb/accounts/... | FB 账户管理（软删除/恢复/BM 历史） |
| POST | /api/fb/accounts/batch-lookup | 批量查户（归属隔离，字段含主 BM 名） |
| POST | /api/fb/accounts/batch-create | 批量建户（共用默认值 + 逐行 overrides） |
| POST | /api/fb/accounts/batch-delete | 批量软删（归属隔离，删不到的进 not_found） |
| GET/POST/PUT/DELETE | /api/fb/products/... | FB 产品管理（线名、在跑 BM） |
| GET/POST/PUT/DELETE | /api/fb/pixel-bms/... | 像素 BM 管理 |
| GET/POST/PUT/DELETE | /api/fb/pixels/... | 像素管理 |
| POST | /api/fb/extract/parse | 解析粘贴的 FB 数据透视表 |
| POST | /api/fb/extract/save | 保存提取数据（双写 DB + Sheets） |
| POST | /api/fb/extract/check-duplicates | 重复校验 |
| GET/POST/PUT/DELETE | /api/fb/reports/... | FB 做表数据管理 + Sheets 同步 |

### TT 平台（tt_routes.py，30 路由）
| 方法 | 路径 | 说明 |
|------|------|------|
| GET | /api/tt/products/list · runner-products · delist-status | 产品列表 / 在跑产品 / 掉包检测状态 |
| POST | /api/tt/products/create · merge · import-text | 新建 / 合并（含掉包行清理）/ 脏数据解析导入 |
| GET/PUT/DELETE | /api/tt/products/:pid[/detail] · /restore | 详情 / 编辑 / 归档 / 恢复 |
| POST | /api/tt/products/:pid/packages | 新增投放对象（跑包 / PWA） |
| PUT/DELETE | /api/tt/packages/:pkg_id | 编辑 / 删除单个投放对象 |
| POST | /api/tt/packages/batch-delete | 批量删除投放对象（含掉包通知清理） |
| GET/POST | /api/tt/products/:pid/assets | TT 产品成效素材列表 / 新增 |
| DELETE | /api/tt/products/:pid/assets/:video_id | 移除单个成效素材 |
| POST | /api/tt/products/:pid/check-delist | 手动检测 TT 产品掉包（口径同 GG：只查正常跑包，走代理池） |
| GET | /api/tt/delist/pending | TT 待处理掉包通知（按产品聚合，带平台闸门） |
| POST | /api/tt/delist/dismiss | 关闭 TT 掉包通知（支持批量） |
| GET/POST/PUT/DELETE | /api/tt/bcs/list · create · options · :id | TT 商务中心 BC 管理 |
| GET | /api/tt/data/export · POST /api/tt/data/import | TT 数据备份导入/导出（JSON，按外键依赖顺序重建 + ID 重映射） |
| GET/POST | /api/tt/settings | TT 系统设置 |
| GET | /api/tt/users | TT 用户列表（下拉用） |

> TT 的**广告账户 / 充值 / 回收**路由仍在 `main.py`（尚未拆入 Blueprint），
> 对应页面 `frontend/src/views/tt/TtAccountPanel.vue`、`TtBcPanel.vue`、`TtDataExtract.vue`、`TtSettingsPanel.vue`。

### 其他模块路由

所有路由均需 `@jwt_required()`，返回 `{"success": bool, ...}` 格式。路由总数 270 个（main.py 179 + fb_routes 49 + tt_routes 30 + auth_routes 12），分布在 GG/FB/TT 三平台 20+ 个模块中。

## 新增功能模块

### 充值管理

账户充值功能，支持单次充值和批量充值。采用**数据库 + Google Sheets 双写**方案。

**数据库表**：`recharge_records`
| 列 | 类型 | 说明 |
|---|---|---|
| id | INTEGER | 主键 |
| account_id | TEXT | 账户ID（如 `123-456-7890`） |
| amount | TEXT | 金额（数字或 `清`） |
| agent | TEXT | 代理（自动联动） |
| operator | TEXT | 运营（当前用户 display_name） |
| created_by | INTEGER | 提交人 user ID |
| created_at | TEXT | 创建时间 |
| status_changed_date | TEXT | 状态变更日期 |

**核心逻辑**：
- **单次充值**：AdsAccountPanel 操作列「💰」按钮 → RechargeModal 弹窗，账户ID 下拉搜索，代理自动联动
- **批量充值**：勾选账户后工具栏「💰 批量充值」→ RechargeBatchModal，金额可分别填或统一填
- **充值表配置**：SettingsPanel 中配置 Google Sheets ID（仅 admin/developer 可见），所有用户共用同一张表
- **双写顺序**：先写 DB → 后台异步写 Google Sheets（失败 30s 后自动重试一次，仍失败前端提示手动操作）
- **死亡清账**：账户状态变为「死亡」时，检查上次变存活后有无充值记录，有则自动追加一条 `amount='清'` 的充值记录
- **状态变更追踪**：新增 `status_changed_date` 字段记录状态变更时间，用于清账逻辑判断
- **充值记录编辑**：支持编辑和删除充值记录
- **非存活账户限制**：非存活状态账户禁止充值
- **去重规则**：普通充值不做去重；死亡清账按 account_id 去重
- 从存活变非存活时，检查上次存活后有充值才写清账；从死亡恢复存活时删除旧清账记录

### 掉包检测与通知

自动检测 Google Play 包的上下架状态，通过 Telegram 群组和前端弹窗通知在跑人员。

**数据库表**：`delist_checks`（检测结果）、`delist_notifications`（通知状态，按用户跟踪）

**核心逻辑**：
- **定时检测**：后台 daemon 线程每小时自动检测所有正常状态产品的正常状态包
- **手动检测**：产品名后"是否掉包"按钮，点击立即检测
- **群通知口径（2026-10-07 裁定）**：定时与手动**统一为「只发新掉包」**（`is_delisted and not was_delisted`，比对 `delist_checks` 上一轮值）。
  此前手动检测是「全部按新掉包处理」（该处注释原文），每点一次就把当前仍掉着的包在群里重报一遍，已作废；TT 侧同步改，口径见 TT 段落
- **并发口径**：两处**定时检测**走 **10 并发**（main.py 内各自写 `min(len(pkgs), 10)`，
  即 `_run_delist_check_once` / `_run_tt_delist_check_once`）；
  **手动检测的并发按代理池容量自适应** —— `delist_checker._resolve_max_workers()`，
  取 `min(_DEFAULT_MAX_WORKERS, proxy_pool.count × _WORKERS_PER_PROXY)`，
  无代理池（含直连）时退回 `_DEFAULT_MAX_WORKERS = 10`。
  ⚠️ **别把手动检测的并发也写死成 10**：手动检测通常只有几个到几十个包
  （定时检测跑的是全量 163 包，高并发才有意义）。保留自适应是为了
  「包少时别无谓加压 + 补代理后自动放开」，**不要**指望它解决「慢」。
  2026-09-25 曾据少量测量得出「代理 10 并发 17.7s vs 3 并发 8.8s」，
  随后被 4/10/10/4 交替对照推翻，见下条。
  手动检测改造前是**串行** `for pkg in packages`（当时 `_TIMEOUT = 15`：单包最坏 60s，
  24 个待检包最坏 1440s；换成现在的 5s 也仍有 480s）。而前端 axios 默认超时 30s
  （`frontend/src/api/client.js`），**包数略多的产品，手动检测在前端就会报错**，
  后端却仍在跑并照常写库、发 Telegram —— 用户看到「失败」，实际已生效。
  故 `check-delist` 这一条请求前端超时单条放宽到 **180s**。
  ⚠️ **单包最坏 20s 是这么来的**（别再用错模型估算）：`requests` 的 `timeout`
  传单值时**连接与读取各算一次** —— `HTTPAdapter.send` 的原文是
  「a single float to set both timeouts to the same value」，故 `_TIMEOUT = 5`
  ⇒ 单次请求最坏 10s（不是 5s）；代理池 2 个时 `next(exclude=tried)` 最多
  给出 2 次尝试 ⇒ 2 × 10s = **20s**。（池子补大后尝试次数受 `max_retries=3` 封顶，
  单包最坏 30s。）2 个代理 + 4 并发时 24 包要跑 6 批，最坏 6 × 20s = 120s，
  落在 180s 前端超时之内。
  ⚠️ **`_TIMEOUT` 于 2026-09-25 由 15 降到 5**（用户裁定）：正常响应仅 2-3s，
  15s 纯属浪费，而长尾（偶发单包吃满超时再重试）正是「慢」的主因。
  代价是网络抖动时更多包判「未判定」——语义安全（保留上次判定、不发通知）。
  ⚠️ **并发数不是主因，别在这上面使劲**：2026-09-25 用 6 包做 4/10/10/4 交替对照，
  4 并发均值 30.9s、10 并发均值 26.7s，单轮极差 55.7s↔6.1s —— 差异淹没在噪声里。
  长尾来自上面这个超时模型，真正的杠杆是 `_TIMEOUT`。
  ⚠️ 并发化后**结果必须与入参 packages 同序**（按输入下标回填，不是按完成顺序 append）：
  TT 手动检测用 `zip(pkg_list, results)` 配对（`routes/tt_routes.py`），
  错序会把 A 包的掉包状态挂到 B 包上，发出**错误的掉包通知**。
  回归测试见 `py/tests/test_delist_parallel.py`。
- **检测方式**：HTTP 请求 Google Play 链接，通过状态码和页面内容判断（404 / "not found" / "找不到请求的网址"）
- **判定第三态（未知）**：`is_delisted` 由 `bool` 扩为 **`bool | None`**，`None` = 判定未知。
  「拿不到判定」的七类一律归为 `None`：**非 200/404 的状态码（403 反爬、410、429、任意 5xx 等）**、
  请求超时、网络连接失败、
  链接解析失败（畸形 url）、代理池为空、代理全部失败、url 为空。
  （该口径由用户 2026-09-25 裁定拓宽（原为「429 或任意 5xx」，404 之外的 4xx 曾作为已知边界保留）。）
  （其中「代理池为空」= `ProxyPool.count == 0`。配置列表为空或未启用时
  `_build_delist_proxy_pool()` 返回 `None`、直接走直连分支，不进这一段；而列表
  **非空但条目全部非法**（非 dict / ip 去空白后为空 / port 转不了 int，
  `ProxyPool._load` 会逐条跳过）时，池子仍会以 count=0 建成，**这一段即会走到**。）
  消费方（GG 定时 / GG 手动 / TT 定时 / TT 手动四处）遇 `None` **一律不写判定结果**，
  保留上一轮判定结果，也不触发掉包通知。
  例外：GG 侧会把原因写进 `delist_checks.error_msg`（该表有这一列，TT 的
  `tt_delist_checks` 没有）；该 UPDATE 只更新**已存在的行**，没有行时不会新建，
  因此「无判定不产生新记录」的语义不变。
  反面边界：404 → 掉包、200 正常页 → 正常，**「拿到了判定」的结果不得改判 `None`**。
  起因：App Store 对掉包链接返回 404，被限流时返回 429，两者响应体同为
  2383 字节，只能靠状态码区分；旧逻辑只认 404 且无条件 `INSERT OR REPLACE`，
  会把 429（以及超时/代理失败等）当成正常，抹掉正确的掉包记录。
- **前端检测提示分四态**：GG/TT 产品卡片点「是否掉包」后，按本轮结果分四种提示 ——
  无包可检提示「没有需要检测的包/跑包」；有掉包提示「检测到 N 个包已掉包！」；
  无掉包但有未知提示「N 个包本轮未能判定，已保留上次判定结果（<真实原因>）」——
  原因取自后端每条结果的 `error`，**不得写死成「限流或网络异常」**（GG 空 url 包会让该文案永久失真）；
  全部拿到判定且正常才提示「所有包均正常 ✓」。
  起因：整批 429 限流时本轮结果全是 `None`，原实现仍弹「所有包均正常 ✓」，属失真提示。
  开发者调度页（`SchedulerView.vue`）同样分态：有掉包红、无掉包但有未判定琥珀并显示未判定个数、其余绿。
- **首次通知**：检测到掉包后，所有在跑人员收到前端弹窗通知
- **重复提醒**：关闭弹窗后 3 分钟，若包状态未设为"掉包"则再次弹窗
- **公平通知**：即使有人已将包状态设为"掉包"，其他在跑人员仍要收到第一次提醒
- **标红提示**：定时检测到掉包的包在列表中标记红色，手动设置状态为"掉包"后恢复
- **Telegram 通知**：首次检测到掉包时通过 Telegram Bot 向群组发送消息，@在跑人员（需用户绑定 Telegram 用户名）
- **暂停产品跳过**：暂停状态的产品不参与定时检测
- **前端轮询**：每 30 秒轮询 `/api/delist/pending` 检查新通知

### 全局任务追踪 & 跨标签同步

解决切换页面进度丢失和多标签页状态不同步的问题。

**核心机制**：
- **Pinia Store 持久化**：任务状态提升到 `taskRunner` Store，路由切换不影响
- **localStorage 恢复**：运行中任务持久化，刷新页面后恢复并重新轮询
- **BroadcastChannel 同步**：`gg-server-sync` 频道跨 Tab 同步任务列表和掉包通知状态
- **全局浮动面板**：`GlobalTaskPanel.vue` 固定在右下角，任何页面可见，展示运行中/已完成/失败任务

**支持的任务类型**：视频生成（video）、掉包检测（delist）、每周清理（cleanup）

### 数据分析板块

基于做表数据（ad_reports）提供多维度数据分析和 AI 智能解读。

- **仪表盘**：关键指标（花费、展示、安装、CPI、CTR、CVR）
- **趋势图**：产品/系列维度的数据变化趋势
- **对比分析**：不同产品/系列的投放效果对比
- **多维分析**：自由维度组合（X/Y轴指标、气泡大小、分组维度），散点图+相关性探索
- **AI 解读**：接入 AI 进行智能分析和对话

### 广告账户 MCC 变更历史

追踪广告账户的 MCC 归属变更，类似 git 提交记录。

**数据库表**：`account_mcc_history`
- 记录 old_mcc_id → new_mcc_id 的变更
- 支持 5 种变更类型：manual（手动）、batch（批量）、reassign（认领转移）、import（导入）、create（新建）
- 支持删除错误的历史记录
- 账户删除时 CASCADE 清理

### 批量查户

在 AdsAccountPanel 工具栏新增「🔍 批量查户」按钮，粘贴一批账户 ID 快速查看归属、状态、代理、MCC 等信息。纯查询操作，不涉及导入/创建。

### 批量导入按账户配置

批量导入新账户时，支持对每个新账户单独设置名称、时区、代理等字段。共用默认值作为初始值，逐行可覆盖编辑。

### 产品管理增强

- **商务字段**：产品新增 `sales_person`（商务）和 `agency_ratio`（代投比例）字段
- **产品删除审计日志**：软删除模式，`is_archived` 标记 + `audit_log` 表记录操作人和删除内容
- **产品合并优化**：合并时同步清理副产品的关联数据

### 视频/媒体功能增强

- **图片拖拽排序**：视频生成前可手动拖拽调整图片顺序
- **音频替换预览**：上传后可用 HTML5 播放器预览视频/音频
- **音频替换历史**：处理记录持久化到 `audio_replace_history` 表，支持回看和重新下载
- **视频批量可见性**：admin/developer 可批量设置视频公开/私有
- **视频消耗追踪**：手动录入广告消耗金额，`video_consumption` 表按人统计
- **视频上传者标签筛选**：YouTube 页面支持按上传者筛选

### Google Sheets 集成

- **用户表格配置**：每个用户可在 UserProfileView 配置自己的 Google Sheets ID
- **做表数据写入**：ToolkitView 一键将做表数据 upsert 到用户表格，按 14 列模板映射
- **充值表**：管理员配置共用充值表，充值记录自动追加
- **凭据统一**：所有 Google Sheets 操作复用做表同款凭据路径

### 定时任务系统

- **掉包检测**：后台 daemon 线程自动执行 —— 默认 **GG 每 1 小时、TT 每 30 分钟**（2026-10-07 起两侧刻意不同频）
- **每周清理**：清理过期爬取图片和生成视频，默认**周日 00:00**
- **手动触发**：SchedulerView 页面，**按平台的管理员可见**（GG 管理员见 GG 掉包检测 + 每周清理；TT 管理员见 TT 掉包检测；
  FB 管理员为空态），developer 可见全部三项，支持即时执行
- **周期可在页面配置**：存 `config.scheduler_config`（单键 JSON：`gg_delist_minutes` / `tt_delist_minutes` /
  `cleanup_weekday` / `cleanup_hour`），调度线程每 `_TICK_SECONDS = 30` 秒重读一次 ⇒ **改完 30 秒内生效、无需重启**
- **上次执行另存 `config.scheduler_last_run_{task_key}`（一个任务一个 key，无共享读改写）**：与配置分开存 ——
  配置由管理员 PUT 写、上次执行由调度线程写，混在一个键里会变成 read-modify-write 互相覆盖；
  而 last_run 自身也有 6 个写者，故再拆到每任务一个 key，写入是单条原子语句、无需加锁
- **周期下限 10 分钟 / 上限 1440 分钟**：下限是后端硬闸（越界一律 400），因为掉包检测要经代理池访问 Google Play，
  而现行 `_TIMEOUT = 5`、代理池只有 2 个代理，再短会把它打爆

### 大规模重构（进行中）

- **后端**：main.py (~9800 行) 逐步拆分为 Flask Blueprint，目标 18 个 route 文件
- **前端**：大组件（YoutubeView/MediaView/AnalysisView/VideoView）逐步拆分为子组件
- **已完成**：auth_routes.py、fb_routes.py、tt_routes.py Blueprint 激活、helpers 扩展、JWT 滑动过期、前端 3 个 Tab 独立、dedupLoader 公共化

### 数据库完整性改进

- 40 张表之间的关系梳理和孤儿数据清理
- 视频删除 → 同步清理 product_assets、video_consumption
- 包删除 → 同步清理 delist_notifications
- 用户删除 → 补充 7 处遗漏的关联清理
- MCC 删除 → 增加产品关联检查
- 产品合并 → 补充关联数据清理
- 所有改动为补充清理，不改现有业务逻辑

### FB 平台（Facebook 广告管理）

GG-Server 在 GG（Google Ads）基础上新增 FB（Facebook）广告管理能力，GG/FB 双平台并行。

**核心设计**：
- **用户平台划分**：users 表新增 `platform` 字段（'gg'/'fb'），仅 developer 可访问双平台
- **FB 独立页面**：不复用 GG 页面，新建 8 个视图（产品/账户/账户BM/像素BM/像素/数据提取/数据管理/设置）
- **结构差异**：FB 用 BM（Business Manager）而非 MCC，分**账户BM**和**像素BM**两种；产品可有多条"线"，一条线对应一个像素
- **后端独立**：`routes/fb_routes.py`（53 路由）+ `database.py` 新增 11 张 fb_* 表
- **共享层**：users/platform、侧边栏切换、路由守卫、数据分析、选项表（地区/商务/状态等）GG/FB 共用

**FB 数据提取**（FbDataExtract.vue）：
- 粘贴 FB 广告后台数据透视表 → 后端 `_parse_fb_extract()` 解析
- 支持"是否排序（提取全列）"两种模式，尾部校验（行数 + 总消耗一致性）
- 保存走**数据库 + Google Sheets 双写**，失败 30s 重试，精确轮询本次写表结果（sync_log_id）
- 保存前重复校验（check-duplicates）

### 代理池（掉包检测防风控）

掉包检测直接请求 Google Play 链接易被风控/限流，现通过代理池随机切换 IP 规避。

- `proxy_pool.py`：代理池封装，从 config 的 `delist_proxy.proxies` 读取代理列表，失败自动切换
- 配置项：`delist_proxy.enabled`（开关）、`max_retries`（重试次数）、`proxies`（代理列表）
- 掉包检测 HTTP 请求统一走代理，降低风控/限流概率

### 账户软删除 & 表格同步

- **软删除**：账户删除不再物理删除，标记为已删除，支持恢复（restore）和永久删除（permanent）
- **已删除账户列表**：AccountDeletedModal 弹窗查看/恢复/永久删除
- **账户表格同步**：从 Google Sheets 同步账户（sync-from-sheet），跳过已删除账户避免重复创建
- **Sheet 映射配置**：字段映射可配置（sheet-mappings-config）

### 字典表（选项表管理）

账户相关的枚举字段从硬编码改为字典表，支持在 SettingsPanel 中管理。

- `agents`（代理）、`account_statuses`（状态）、`mcc_levels`（MCC 等级）、`sales_persons`（商务）、`regions`（地区）
- 每个字典表提供标准 CRUD API，GG/FB 平台共用
- MCC 等级下拉懒加载修复

⚠️ **`account_statuses` 是 `UNIQUE(name, platform)` 的共享字典，「存活」在 gg/fb/tt
各有一行 —— 凡按名字取行都必须带 `platform`。** 2026-10-06 修的一处：
GG 侧读写状态字典的 6 处 SQL 都写 `WHERE name=? AND owner_id=?`，
(a) 缺 platform → 唯一索引按 (name, platform) 排序（`'fb' < 'gg' < 'tt'`），
`fetchone()` 稳定落在 **fb** 行，生产 43 个 GG 账户的状态 id 被写成 fb 的
（「存活」25 条、「死亡」8 条）；
(b) `owner_id` 记的是**创建者**（生产全是 developer=1），与账户归属无关，
普通用户按自己的 id 查永远查不到 —— 筛选恒空，写侧回退 `INSERT` 又撞 UNIQUE，
异常被通用分支误报成「账户 ID 'xxx' 已存在」409。
现口径：GG 侧统一走 `main._gg_status_id(db, name, owner_id)`（`WHERE name=? AND
platform='gg'` + `INSERT OR IGNORE ... VALUES(?,?,'gg')` 再重查，**去掉 owner_id**）；
存量由 `database._migrate_account_status_platform` 幂等归位。
**别把 `owner_id` 加回来**，也别省掉 platform。`agents` 无此问题
（它是 `UNIQUE(name, owner_id, platform)`，owner_id 在那里有意义）。
回归测试见 `py/tests/test_account_status_platform.py`（6 条，改回旧写法会全红）。

⚠️ **同一根因还有一处：`data_service._import_option_table` 的查重键。** 它此前对四张
选项表一律按 `(name, owner_id)` 查重，而真实唯一键逐表不同 —— `agents`
`(name, owner_id, platform)`、`account_statuses` / `sales_persons` `(name, platform)`、
`mcc_levels` `(name, owner_id)`。生产字典行 owner_id 全是创建者 developer=1，
于是**任何非 developer 的导入**都会撞 `UNIQUE(name, platform)` 把**整次导入**打崩
（`/api/data/import` 直接 500，业务表一条都进不去）。现按 `_OPTION_UNIQUE_COLS`
逐表取键；旧导出缺 platform 列时按建表默认 `'gg'` 补齐再查重（否则 NULL 配不上、
查重形同虚设）。回归测试见 `py/tests/test_data_import_option_dedup.py`（3 红 1 对照）。

⚠️ **`_migrate_account_status_platform` 的 try/except 不是装饰**：`_migrate_if_needed`
每个请求都跑，逃出异常 = 全站每次 get_db() 都 500。可达触发是非 gg 字典行的
`owner_id` 悬挂（跨库拷 app.db / 旧备份），此时补建 gg 行抛 FOREIGN KEY ——
**`INSERT OR IGNORE` 不吞外键错**（ON CONFLICT 算法不适用于 FOREIGN KEY）。
回归钉：`test_does_not_kill_get_db_when_owner_fk_dangles`（去掉 except 恰好 1 红）。
⚠️ **空状态（`status_id IS NULL`）的口径 = 「未知」**（2026-10-06 用户裁定）。
GG 侧三处必须同一口径：表格渲染（前端 `row.status || '未知'`）、`accounts_list`
的 `status_counts`（NULL 桶命名为「未知」，**不再 `COALESCE(...,'存活')`**）、
以及筛选（`status='未知'` → `status_id IS NULL OR 绑到名为「未知」的 gg 字典行`）。
三者必须绑在一起改：`status_counts` 的 key 会被前端 `availableStatuses` 直接渲染成
状态按钮、`toggleStatus` 又把它原样回传成 `status` 查询参数 —— 只改统计不改筛选，
那个按钮就是个**死链**（数字 N、点开 0 条）。生产影响：10 条空状态账户从
「存活 30」移到新的「未知 10」，总存活计数相应下降，属预期。
回归测试见 `py/tests/test_account_status_platform.py::TestUnknownStatusBucket`
（含不变式「出现过的 key，点开条数必须与计数相等」；两条改动各有独立红钉）。
**TT 侧刻意不动**：`tt_accounts_routes.py` 的同一句 `COALESCE` 与它自己的表格渲染
（`it['status'] = status_name or '存活'`）**自洽**，NULL 在 TT 显示也是「存活」，
改它等于替用户改一个未定行为。（TT 筛选走 `status_id` 而非名字，机制不同。）

### 掉包通知按产品聚合

掉包通知从按包聚合改为按产品聚合，同一产品多包掉包合并为一条通知。

- `delist/pending` 按产品聚合返回，前端弹窗按产品展示
- `delist/dismiss` 支持批量关闭
- Telegram 通知按产品分组发送

### 视频频道名

YouTube 视频新增频道名（channel name）字段，导入时自动获取频道信息。

### TT（TikTok）平台

继 GG、FB 之后的第三条业务线，页面与数据完全独立（`tt_` 前缀），仅 developer 可切换进入。

**核心设计**：
- **表结构**：11 张 `tt_*` 表（产品 / 投放对象 / 成效素材 / 在跑人员 / 账户 / 商务中心 BC / 账户-BC 变更历史 / 充值记录 / 回收原因 / 掉包检测 / 掉包通知）
- **结构差异**：TT 用 **BC（商务中心）** 而非 MCC 或 BM；产品的投放对象分 `package`（跑包）和 `pwa` 两种 `type`
- **后端**：`routes/tt_routes.py`（30 路由，产品 / 投放对象 / 素材 / BC / 数据提取 / 设置 / 掉包）；TT 的账户、充值、回收路由仍在 `main.py`
- **前端**：`views/tt/` 下 6 个视图（TtView 容器 / TtAccountPanel / TtBcPanel / TtProductPanel / TtDataExtract / TtSettingsPanel）+ `components/TtProductCard.vue`、`TtAddPackageModal.vue`
- **UI 对齐**：TT 页面视觉与交互对齐 GG（见 `2026-09-18-tt-ui-gg-alignment-design.md`）
- **数据提取**：TtDataExtract.vue **纯前端**解析（`utils/adsParser.js`），产出 TSV/表格供复制，不写库
- **投放对象支持 App Store 链接**：苹果包复用 `type='package'`，URL 是
  `apps.apple.com` / `itunes.apple.com` 时**包名允许留空**（不自动填数字 id），
  卡片上以灰色 `iOS` 占位展示；安卓包仍强制填写包名。域名判定按解析出的 host
  全等比较（防 `evil.com/?u=apps.apple.com` 误判）
- **投放对象字段类型闸门**：系列名 / 包名 / 链接三个文本字段必须为字符串
  （`None` 视同未填写），非字符串（数字 / 数组 / 对象）一律 **400**
  （`_check_pkg_text_types`）。三处入口（新建产品带包 / 编辑产品带包 / 单包 POST·PUT）
  同口径：`add_package` 与 `update_package` 的 `.strip()` 必须在闸门**之后**，
  否则 `123.strip()` 抛 `AttributeError` → 500。
  「只改系列名」这类部分更新仍须放行 —— 闸门只管类型，不管「跑包必须填包名」
- **数据备份**：`GET /api/tt/data/export` 导出 JSON、`POST /api/tt/data/import` 按外键依赖顺序重建（含 ID 重映射）
- **共享层**：用户 platform 字段、侧边栏切换、路由守卫、选项表（地区 / 商务等）三平台共用

### TT 掉包通知（独立机器人）

TT 掉包检测与通知**完整对齐 GG**，唯一差别是走**独立的 `tt_telegram` 机器人**；**不发邮件**。

**核心逻辑**：
- **定时检测**：后台 daemon 线程**每 30 分钟**检测正常状态 TT 产品的正常状态跑包
  （⚠️ **TT 30 分钟、GG 1 小时，两侧刻意不同频** —— 2026-10-07 用户裁定，别「顺手对齐」）
- **手动检测**：`POST /api/tt/products/:pid/check-delist`，同样走代理池、并发同样**按代理池容量自适应**（口径见 GG 侧「并发口径」）；
  ⚠️ 结果按 `package_id` 与原始包行建映射取 `series_name`（**2026-10-07 起不再用 `zip(pkg_list, results)`** —— 那依赖返回与入参同序，是脆弱点）
- **群通知口径（2026-10-07 裁定，GG/TT 两侧一致）**：定时与手动**统一为「只发新掉包」**（`is_delisted and not was_delisted`，比对 `tt_delist_checks` 上一轮值）。
  ⚠️ 此前**手动检测**是「全部按新掉包处理」—— 每点一次就把当前仍掉着的包在群里重报一遍，已作废。
  判定「未知」的轮次不写库、不参与比对（故不会误报）。掉包 → 恢复 → 再掉包仍会再发（那是新的掉包事件）
- **前端通知**：`GET /api/tt/delist/pending` 按产品聚合返回，首次弹窗 + 关闭后 3 分钟未处理再提醒
- **可见性**：`delist/pending` 与 `delist-status` 均只按**产品归属人（`tt_products.owner_id`）或在跑人员（`tt_product_runners`）**过滤，
  **无 developer/admin 特权**（2026-09-26 按用户裁定移除该特权分支；起因：developer 账号既非归属人也非在跑人员，
  却照样收到掉包弹窗。GG 侧本就无角色分支，故本条即「对齐 GG」）。
  平台闸门 `require_platform('tt')` / `@tt_required` 不受影响，仍保留。
  ⚠️ **别把 owner 轴也一并删掉**：owner 轴是设计过的需求（`2026-09-24-tt-delist-notification-design.md`），
  有具名测试 `test_owner_sees_own_delisted_notification` 钉住；GG 无 owner 轴是因为
  GG 的 `products` 表压根没有 owner 列（产品共享），不等于「刻意排斥归属人看自己的产品」。
  回归测试见 `py/tests/test_tt_delist_notification.py::TestTtDelistStatusScope`
  与 `::TestTtDelistPending::test_developer_no_longer_sees_all` / `test_developer_sees_when_runner`。
- **Telegram 通知**：首次检测到掉包时，通过 `tt_telegram` 机器人向群组发送消息并 @在跑人员（与 GG 的 `telegram` 节点**互不影响**，可分别配置不同的群）
- **配置**：`config.json` 保留空的 `tt_telegram.{bot_token,chat_id}` 结构，真实值放 `config/config.local.json`（已 gitignore）
- **数据清理**：TT 产品合并、投放对象批量删除时同步清理其掉包检测与通知行

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
- **全局任务追踪**：任务注册到 taskRunner Store，切换页面不丢进度

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
- **新增字段**：商务（sales_person）、代投比例（agency_ratio）

### 工具集

- **做表数据**：从 Google Ads 原始竖排数据解析账号/客户ID/广告系列/费用/展示/点击，三种视图（原始清洗/按客户ID+广告系列聚合/按广告系列聚合），一键复制 TSV + 导出 XLSX，支持写入 Google Sheets
- **音频替换**：FFmpeg `-c:v copy -map 0:v:0 -map 1:a:0 -shortest`，支持音频文件和视频文件作为音频源，上传预览 + 历史记录

### 导入约定

所有 Python 文件使用绝对导入（无前导点），`main.py` 开头通过 `sys.path.insert(0, _current_dir)` 确保导入正确。`database.py` 独立计算 `_db_path()`。

## 与 ImageCrawling 的关系

本项目从 ImageCrawling 演进而来（单用户本地工具 → 多人协作服务器）。核心业务逻辑（爬取/视频/YouTube/产品/脏数据解析/AI服务等）共享。

**文档同步规则**：
- 任何涉及共享功能的改动，必须在两个项目同步更新文档
- 修改共享逻辑时，检查是否需要同步更新 AGENTS.md / CLAUDE.md / NOTES.md / 设计文档
- ImageCrawling 路径：`f:\carl_work\carl\Google\cc\ImageCrawling\`

## 设计文档索引

> **文档更新规则**：每次新增或修改设计文档后，必须同步更新此索引。

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
- [脏数据解析](docs/superpowers/specs/2026-06-28-dirty-data-parsing-design.md)

### GG-Server 独立设计文档
- [GG-Server 多人协作版](docs/superpowers/specs/2026-06-23-gg-server-design.md)
- [数据迁移方案](docs/superpowers/specs/2026-06-26-data-migration-design.md)
- [用户管理改进](docs/superpowers/specs/2026-06-27-user-management-improvements-design.md)
- [视频上传者标签筛选](docs/superpowers/specs/2026-06-27-video-uploader-label-filter-design.md)
- [MCC 共享用户](docs/superpowers/specs/2026-06-29-mcc-shared-users-design.md)
- [视频文案权限修复](docs/superpowers/specs/2026-07-01-video-copywriting-permission-fix-design.md)
- [爬取远程下载](docs/superpowers/specs/2026-07-01-scrape-remote-download-design.md)
- [视频远程 UI](docs/superpowers/specs/2026-07-01-video-remote-ui-design.md)
- [统一媒体页面](docs/superpowers/specs/2026-07-01-unified-media-page-design.md)
- [媒体上传](docs/superpowers/specs/2026-07-01-media-upload-design.md)
- [产品客户字段](docs/superpowers/specs/2026-07-03-product-customer-field-design.md)
- [数据分析板块](docs/superpowers/specs/2026-07-03-data-analysis-design.md)
- [多维分析与 AI 智能解读](docs/superpowers/specs/2026-07-03-multi-dimension-analysis-design.md)
- [数据管理与聚合](docs/superpowers/specs/2026-07-04-data-manage-and-aggregation-design.md)
- [批量导入按账户配置](docs/superpowers/specs/2026-07-10-batch-import-per-account-config-design.md)
- [包掉包自动检测与通知](docs/superpowers/specs/2026-07-13-package-delist-detection-design.md)
- [定时任务手动调用](docs/superpowers/specs/2026-07-13-scheduler-manual-trigger-design.md)
- [音频替换预览与历史](docs/superpowers/specs/2026-07-14-audio-replace-preview-history-design.md)
- [产品删除审计日志](docs/superpowers/specs/2026-07-14-product-delete-audit-log-design.md)
- [视频批量可见性 & 消耗追踪](docs/superpowers/specs/2026-07-14-video-batch-visibility-and-consumption-design.md)
- [批量查户](docs/superpowers/specs/2026-07-15-batch-account-lookup-design.md)
- [图片手动拖拽排序](docs/superpowers/specs/2026-07-17-image-sort-drag-design.md)
- [账户 MCC 变更历史](docs/superpowers/specs/2026-07-20-account-mcc-history-design.md)
- [掉包 Telegram 群组通知](docs/superpowers/specs/2026-07-20-telegram-delist-notify-design.md)
- [全局任务进度追踪 & 跨标签同步](docs/superpowers/specs/2026-07-20-global-task-tracker-design.md)
- [Google Sheets 用户配置](docs/superpowers/specs/2026-07-21-google-sheets-user-config-design.md)
- [Google Sheets 做表数据写入](docs/superpowers/specs/2026-07-21-google-sheets-toolkit-update-design.md)
- [账户充值功能](docs/superpowers/specs/2026-07-22-recharge-feature-design.md)
- [大规模重构设计](docs/superpowers/specs/2026-07-22-large-scale-refactoring-design.md)
- [数据库完整性改进](docs/superpowers/specs/2026-07-22-db-integrity-improvement-design.md)
- [优化测试](docs/superpowers/specs/2026-07-22-optimization-tests-design.md)
- [Sheets 异步化 & 性能优化](docs/superpowers/specs/2026-07-22-async-sheets-performance-design.md)
- [账户表格同步](docs/superpowers/specs/2026-07-28-account-sheet-sync-design.md)
- [设置选项表（字典表）](docs/superpowers/specs/2026-07-28-settings-option-tables-design.md)
- [设置面板 UI 重构](docs/superpowers/specs/2026-07-28-settings-panel-ui-redesign.md)
- [Sheet 映射配置](docs/superpowers/specs/2026-07-28-sheet-mappings-config-design.md)
- [账户软删除](docs/superpowers/specs/2026-07-29-account-soft-delete-design.md)
- [FB 账户页面 UI 重构](docs/superpowers/specs/2026-07-30-fb-account-pages-ui-redesign.md)
- [FB 平台](docs/superpowers/specs/2026-07-30-fb-platform-design.md)
- [视频频道名](docs/superpowers/specs/2026-07-30-video-channel-name-design.md)
- [Spring Boot 迁移](docs/superpowers/specs/2026-07-31-spring-boot-migration-design.md)
- [FB 提取校验](docs/superpowers/specs/2026-08-01-fb-extract-validation-design.md)
- [掉包通知按产品聚合](docs/superpowers/specs/2026-08-13-delist-notification-group-by-product-design.md)
- [产品包筛选工具栏吸顶](docs/superpowers/specs/2026-08-13-product-pkg-filter-toolbar-sticky-design.md)
- [产品吸顶表头](docs/superpowers/specs/2026-08-13-product-sticky-header-design.md)
- [掉包检测代理](docs/superpowers/specs/2026-08-27-delist-check-proxy-design.md)
- [户管角色](docs/superpowers/specs/2026-09-22-huguan-role-design.md)
- [户管角色前端界面](docs/superpowers/specs/2026-09-22-huguan-frontend-design.md)
- [账户面板「归属人」下拉只列出有账户的用户](docs/superpowers/specs/2026-09-23-owner-filter-hide-empty-users-design.md)
- [账户面板「归属人」默认作用域](docs/superpowers/specs/2026-09-23-owner-filter-default-scope-design.md)
- [户管看板 Google Sheet 配置与双向同步（子项目 B）](docs/superpowers/specs/2026-09-23-huguan-sheet-design.md)
- [户管看板前端视觉设计（子项目 B / Task 10 + Task 11）](docs/superpowers/specs/2026-09-24-huguan-frontend-visual-design.md)
- [户管看板：归属变更「来源」标注 + 户管专用归属人列表](docs/superpowers/specs/2026-09-24-huguan-owner-source-and-picker-design.md)
- [TT 产品管理模块](docs/superpowers/specs/2026-09-18-tt-product-management-design.md)
- [TT 设置界面](docs/superpowers/specs/2026-09-18-tt-settings-design.md)
- [TT 模块 UI 对齐 GG 风格](docs/superpowers/specs/2026-09-18-tt-ui-gg-alignment-design.md)
- [TT 广告账户管理页面](docs/superpowers/specs/2026-09-21-tt-accounts-design.md)
- [TT 数据提取（解析预览）](docs/superpowers/specs/2026-09-22-tt-data-extract-design.md)
- [TT 充值表表头适配](docs/superpowers/specs/2026-09-22-tt-recharge-sheet-header-design.md)
- [TT 回收户清单写入（只写 3 列、保护公式、非存活即触发）](docs/superpowers/specs/2026-09-22-tt-recycle-sheet-columns-design.md)
- [TT 同步「是否回收」列驱动状态变更](docs/superpowers/specs/2026-09-22-tt-sync-recycle-status-design.md)
- [TT 掉包通知（独立机器人）](docs/superpowers/specs/2026-09-24-tt-delist-notification-design.md)
- [全站鉴权加固与既有缺陷收口](docs/superpowers/specs/2026-09-23-security-hardening-design.md)
- [下载签名按需签发 + scrape 产物归属校验](docs/superpowers/specs/2026-09-24-ondemand-download-signing-design.md)（含 §0.9：code-review 第 3 轮逐条处置；§0.10：曾用目录名认领 + 存量非法名豁免，及第 5 轮审查处置；§0.11：三条裁定落地 —— 换表 + last-writer-wins、墓碑表、并发改名 500→400；§0.12：第 6 轮两条裁定落地 —— 哨兵硬闸 + 无主目录补墓碑、越界退化同步进 `_dir_name_of`；§0.13：换判据加时间维度 —— 释放行须晚于目录创建时刻，扫盘退役、哨兵改按**化身**生效）
- [TT 支持苹果（App Store）包链接 + 掉包判定加固](docs/superpowers/specs/2026-09-24-tt-appstore-package-design.md)
- [TT 掉包可见性收窄（彻底对齐 GG，去掉 developer/admin 特权）](docs/superpowers/specs/2026-09-26-tt-delist-visibility-scope-design.md)
- [户归属下拉按平台隔离](docs/superpowers/specs/2026-09-28-huguan-owner-options-platform-isolation-design.md)
- [TT「换绑情况」列改造：归属变更通道 → 换绑记录字段](docs/superpowers/specs/2026-10-06-tt-owner-change-note-design.md)（仅 TT；取代 `2026-09-23-huguan-sheet-design.md` §7 的 TT 部分）
- [TT 备注（remark）跨看板同步优先级](docs/superpowers/specs/2026-10-06-tt-remark-sync-precedence-design.md)（方案 A：首次入库户管触发以投手为准、此后投手权威永久；新建「系统 → 投手看板」推送通路）
- [定时任务：权限下放到管理员 + 周期可配置](docs/superpowers/specs/2026-10-07-scheduler-admin-access-and-interval-config-design.md)（admin 按平台隔离；周期可配置存 `config.scheduler_config`，上次执行存 `scheduler_last_run`）
- [定时任务管理页：周期编辑视觉设计](docs/superpowers/specs/2026-10-07-scheduler-frontend-visual-design.md)（卡片内划「调度条」：左周期右上次执行；顺带修 TT 卡片写错的频率文案）
- [定时任务功能：审查发现清单（**已全部处理**）](docs/superpowers/specs/2026-10-07-scheduler-open-findings.md)（23 条：19 条可修的已修完并附提交号、4 条经判定不是问题；含一处对初版技术论断的勘误）
- [上万户规模下的看板同步延迟与数据安全治理](docs/superpowers/specs/2026-10-07-sheet-sync-scale-design.md)（设计分三部分，**目前只落地第 ③ 部分「分页与列表」**：17 处列表端点加 `size` 服务端上限（越界钳制 500、非数字回落不报错）+ `page` 上界、GG/TT「已删除账户」列表补分页与服务端搜索（含稳定排序 tiebreaker）、FB 列表 BM 改批量查消除 N+1、既有 `IN (...)` 接入 `chunk(900)`。实现计划见 `docs/superpowers/plans/2026-10-07-sheet-sync-scale-pagination.md`；连带记有 3 处清单勘误与 4 条后续工单）
- [FB 账户面板批量能力对齐](docs/superpowers/specs/2026-10-08-fb-account-panel-batch-actions-design.md)（批量查户 / 批量新增导入 / 批量删除 / 回收站四项；**不含**同步与批量充值）
- [TT 户类型与多账户表](docs/superpowers/specs/2026-10-08-tt-account-types-design.md)
- [续作指南](docs/superpowers/specs/NEXT-STEPS.md)

## 数据库表总览

> 共 52 张表：GG 平台 30 张 + FB 平台 11 张 + TT 平台 11 张。字典表（选项表）5 张三平台共用。

### GG 平台
| 表名 | 用途 | 隔离方式 |
|------|------|----------|
| `users` | 用户账户（含 platform 平台字段） | - |
| `config` | 键值配置（字体最近使用、Google Sheets/AI 配置等） | key |
| `tags` | 标签（通用 key-value，含 YouTube tags） | key |
| `products` | GG 产品管理 | 共享 |
| `packages` | GG 产品包 | 共享 |
| `product_assets` | 产品成效素材 | 共享 |
| `product_runners` | 产品在跑人员 | 共享 |
| `accounts` | GG 广告账户 | owner_id 隔离 |
| `mcc` | GG MCC 管理 | owner_id 隔离 |
| `account_mcc_history` | 账户 MCC 变更历史 | 关联 accounts |
| `agents` | 代理字典 | 共享 |
| `account_statuses` | 账户状态字典 | 共享 |
| `mcc_levels` | MCC 等级字典 | 共享 |
| `sales_persons` | 商务字典 | 共享 |
| `regions` | 地区字典 | 共享 |
| `scrape_cache` | 爬取缓存 | 共享 |
| `scrape_dn_history` | 爬取目录名历史 + **墓碑** + **哨兵硬闸**（曾用名认领判据：LWW **+ 时间维度**，释放行须晚于目录 `ctime`）；**无外键、刻意不进删用户清理** | 按名字判归属 |
| `import_history` | 导入历史 | user_id 隔离 |
| `video_history` | 视频生成历史 | user_id 隔离 |
| `video_tasks` | 视频任务追踪（DB 持久化） | 共享 |
| `videos` | YouTube 视频库 | owner_id + is_public |
| `video_consumption` | 视频广告消耗 | user_id 关联 |
| `copywritings` | 视频文案 | owner_id 隔离 |
| `ad_reports` | GG 做表数据 | user_id 隔离 |
| `recharge_records` | 充值记录 | created_by 隔离 |
| `delist_checks` | 掉包检测结果 | 关联 packages |
| `delist_notifications` | 掉包通知状态 | user_id 隔离 |
| `audio_replace_history` | 音频替换历史 | 共享 |
| `sheets_sync_log` | Sheets 同步失败日志 + 行数据 | user_id 隔离 |
| `audit_log` | 产品删除审计日志 | 共享 |

### FB 平台
| 表名 | 用途 | 隔离方式 |
|------|------|----------|
| `fb_bms` | FB 账户 BM | 共享 |
| `fb_accounts` | FB 广告账户 | 关联 bms |
| `fb_account_bm` | FB 账户-BM 归属 | 关联 |
| `fb_account_bm_history` | FB 账户 BM 变更历史 | 关联 |
| `fb_products` | FB 产品管理 | 共享 |
| `fb_product_runners` | FB 产品在跑人员 | 共享 |
| `fb_product_bms` | FB 产品在跑 BM | 共享 |
| `fb_pixel_bms` | FB 像素 BM | 共享 |
| `fb_pixels` | FB 像素 | 关联 pixel_bms |
| `fb_lines` | FB 产品线名 | 关联 fb_products |
| `fb_ad_reports` | FB 做表数据 | user_id 隔离 |

### TT 平台
| 表名 | 用途 | 隔离方式 |
|------|------|----------|
| `tt_products` | TT 产品管理 | 共享 |
| `tt_packages` | TT 投放对象（`type='package'` 跑包 / PWA） | 共享 |
| `tt_product_assets` | TT 产品成效素材 | 共享 |
| `tt_product_runners` | TT 产品在跑人员 | 共享 |
| `tt_bcs` | TT 商务中心（BC，对应 GG 的 MCC / FB 的 BM） | 共享 |
| `tt_accounts` | TT 广告账户；`account_type` 存**户类型名字符串**（加白户 / 企业户…），取值来自户管看板配置 `config.huguan_dashboard_<uid>.tt.tables[].name`，**改名必须级联 `UPDATE tt_accounts.account_type`**（在 `huguan_dashboard.save_config` 里做） | owner_id 隔离 |
| `tt_account_bc_history` | TT 账户 BC 变更历史 | 关联 tt_accounts |
| `tt_recycle_reasons` | TT 回收原因 | owner_id |
| `tt_recharge_records` | TT 充值记录 | created_by 隔离 |
| `tt_delist_checks` | TT 掉包检测结果 | 关联 tt_packages |
| `tt_delist_notifications` | TT 掉包通知状态 | user_id 隔离 |

> **删用户时的关联清理**：`admin_delete_user` 必须清理所有引用 `users(id)` 的列 —— 这些列
> 都是 `REFERENCES users(id)` 且**无 ON DELETE**，连接又开了 `PRAGMA foreign_keys=ON`，
> 漏一张表就会以 `删除失败: FOREIGN KEY constraint failed` 收场。口径：归属/创建人列置空
> （`owner_id` / `created_by` / `changed_by` / `added_by`），纯归属关系表直接删除
> （`*_product_runners`、`ad_reports` / `fb_ad_reports` 等 NOT NULL 列）。
> 新增任何带 `user_id` 的表后，务必同步补充清理，回归测试见
> `py/tests/test_user_delete_and_merge_cleanup.py`。
>
> ⚠️ **唯一例外：`scrape_dn_history` 刻意不清理，也刻意不加外键。** 它是**墓碑表** ——
> 删用户时 `admin_delete_user` 先写入该用户当前的爬取目录名（`auth.note_scrape_dn_release`），
> 那行必须**活过**本次删除。否则用户一删，他的名字就从认领判据里消失，本该无主的爬取目录
> 会被「曾用名含该名」的人认领并读到**被删用户**的产物。若有人顺手把这张表加进清理清单，
> 保护即失效 —— 用变异实测过：加一行 `DELETE FROM scrape_dn_history WHERE user_id = ?`
> 会让 `TestDeletedUserDirectoryIsTombstoned::test_directory_of_deleted_user_is_not_reclaimable`
> **恰好 1 红**（同组的对照腿保持绿）。回归测试见
> `py/tests/test_scrape_ownership.py::TestDeletedUserDirectoryIsTombstoned`。
>
> ⚠️ **`user_id = auth._DN_SENTINEL_UID`（= 0）的行是「硬闸」，不是「一个很大的序号」。**
> 该语义下的名字**无条件**不可被认领（**在该哨兵所判的那个化身仍在时** —— 见下「按化身生效」，
> 两句话合起来才是完整口径；`auth._dn_released_keys` 用独立 `blocked` 集合剔除，
> 不参与序号比较）。把哨兵改成「参与序号比较」会被后来者更大的 id 顶掉、阻断静默失效
> （变异 m17 恰好 1 红）。**写入点只剩一个**：迁移时**跨用户先后无法还原**的歧义名
> （`database._migrate_scrape_dn_history`）—— 第二个写入点（扫盘补墓碑）已随「时间维度」
> 判据退役，见 §0.13。
> **哨兵按「化身」生效**：只拦它写下的那一刻就已存在的那个目录（`ts >= ctime`），
> 目录在其后**重建**则旧哨兵失效（否则本人的认领路会被永久封死）。tie 取拦的一侧。
> 回归测试见 `py/tests/test_scrape_dn_history_migration.py::TestScanRetirementAndSentinelIncarnations`
> 与 `py/tests/test_scrape_ownership.py::TestSentinelIsAHardGate`。
>
> ⚠️ **（已作废）**「别把『已有释放行的名字排除出扫盘』当成修 bug」这条警示随扫盘退役
> 一并失效，保留在此仅为记录来路：那时代价是「上线前已改名者的旧目录认领路」被封
> （§0.12 收口 1）。§0.13 换判据后该路已恢复，扫盘整段删除。
>
> ⚠️ **判据现在带时间维度，改它之前先读 §0.13。** 释放行只有在 `created_at > 目录 ctime`
> 时才参与比较（自己与**他人**两侧一起过滤）；拿不到化身（目录不存在 / 越界 / stat 失败）
> 或时刻解析不出时，释放行**不过滤**、哨兵**照拦**（fail-closed）。存量秒级行的写入口径
> 仍是**向下截断** ⇒ 与目录同毫秒会判成「不覆盖」（生产不可达，方向安全）。
> 时刻列是 **UTC**（`calendar.timegm`），改成本地解析会让整批行偏移一个时区（变异 m31）。
> **任何写 `scrape_dn_history` 的地方都必须带亚秒**（`strftime('%Y-%m-%d %H:%M:%f','now')`）：
> 表默认值 `datetime('now')` 只到秒，对**释放行**是 fail-closed（更难覆盖），对**哨兵**
> 却是 **fail-open**（`ts >= ctime` 更难成立 ⇒ 拦不住它当年所判的化身）。迁移的哨兵写入口
> 曾漏了这一条，见 §0.13「code-review 第 7 轮」I-1（变异 m35）。

## 启动方式

```bash
# 1. 安装依赖
pip install -r requirements.txt
pip install flask-jwt-extended

# 2. 在 config/config.local.json 中填真实 developer 账号和 secret_key（敏感信息不入库）

# 3. 启动
cd py
python main.py
# 打开浏览器访问 http://localhost:5001

# 前端开发模式（另一个终端）
cd frontend
npm run dev
# Vite dev server :5173，自动代理 /api 到 Flask :5001
```

## 配置说明（config/config.json + config/config.local.json）

```json
{
  "secret_key": "jwt签名密钥",
  "jwt_expire_hours": 24,
  "jwt_refresh_days": 7,
  "developer": {
    "username": "developer",
    "password": ""
  },
  "server": {
    "host": "0.0.0.0",
    "port": 5001,
    "debug": false
  },
  "scrape_cache_dir": "temp/scrape_cache",
  "telegram": {
    "bot_token": "",
    "chat_id": ""
  },
  "smtp": {
    "host": "smtp.qq.com",
    "port": 465,
    "user": "xxx@qq.com",
    "password": "",
    "from_name": "GG-Server 掉包通知"
  },
  "delist_proxy": {
    "enabled": true,
    "max_retries": 3,
    "proxies": [
      {"ip": "x.x.x.x", "port": 0, "username": "", "password": ""}
    ]
  },
  "google_sheets": {
    "credentials_path": "config/xxx.json"
  }
}
```

> **敏感信息分离**：真实密钥（`secret_key`、developer 密码、smtp 密码、Telegram token、代理账号密码）放在 `config/config.local.json`（已加入 `.gitignore`，不入库）。`config.json` 只保留结构与非敏感默认值，启动时 `main.py` 将两者深合并。

## 开发注意

- 从 `py/` 目录内运行 `python main.py`（`sys.path` 依赖目录结构）
- Flask 端口 5001，Vite 端口 5173，CORS 已配置
- **Tailscale 部署**：其他电脑只能访问 5001，无法访问 5173。前端改动后必须 `npm run build` 其他人才能看到
- 首次启动自动创建 users 表 + developer 账号
- **任何前端改动后，必须提醒我 `npm run build` 重新构建**
- **任何后端代码（py/main.py 等）修改后，必须提醒我重启 Flask 服务才能生效**
- **每个新需求开工前，必须先问我一句「这次用不用 git worktree」——不要默认在 master 上直接改。**
  理由：需求多且并行推进，全都在 master 上修改 + 提交会**频繁互相冲突**（同文件被多个会话同时改、
  提交相互穿插）；用 worktree 隔离后，多个需求可以**同时开工**，不必等上一个做完才能开始下一个。
  **每次都要问，不要替我决定**（即使你觉得这个需求很小）。
- **每次改完 bug 或完成需求后，提醒我提交 git**
- **每次新的文档都要建立索引**
- /test-driven-development 使用这个测试新需求
- SQLite 数据库自动建表 + 迁移，位于 `temp/data/app.db`
- 本项目是 ImageCrawling 的独立副本，修改不影响原项目
- **后端重构进行中**：main.py 正逐步拆分为 Blueprint（`py/routes/`），新增路由优先写入独立 Blueprint 文件
- **前端大组件拆分进行中**：YoutubeView/MediaView/AnalysisView/VideoView 逐步拆分为子组件

## 数据操作记录（破坏性操作备份）

> **规则**：任何破坏性数据操作（批量硬删、清空表）执行前**必须先备份**，并在下表登记备份位置。
> 备份路径均相对于项目根目录。

| 日期 | 操作 | 影响范围 | 备份位置 |
|------|------|----------|----------|
| 2026-10-06 | TT 账户状态选项瘦身 | `account_statuses` platform='tt' 删除 89 行（94 → 5） | 库快照 `temp/data/backups/app.db.bak-before-tt-statuses-trim-20261006-200410`<br>CSV `temp/data/backups/tt-statuses-trim-20261006-200410/account_statuses.csv` |
| 2026-10-06 | TT 广告账户全部硬删 | `tt_accounts` 5097 行（正常 4582 + 回收站 515）、`tt_account_bc_history` 1493 行、`tt_recharge_records` 20 行 | 库快照 `temp/data/backups/app.db.bak-before-tt-accounts-clear-20261006-195957`<br>CSV `temp/data/backups/tt-accounts-clear-20261006-195957/` |
| 2026-09-24 | GG 状态悬空 69 户硬删 | GG 账户 69 行 | 库快照 `temp/data/backups/app.db.bak-before-69-delete-20260924-152405`<br>CSV `temp/data/backups/deleted-69-accounts-20260924-152525.csv` |

### 2026-10-06 TT 账户状态选项瘦身说明

- 保留 5 项：`存活`(31) / `回收`(30) / `死亡`(32) / `不花费`(29) / `验证`(34)
- 删除 TT 平台其余 89 项，**含其他用户（23/25/28/29/30/31）自建的杂项词条** ——
  `GET /api/statuses/list` 不按 owner 过滤，状态列表全局共用一份，故此操作对所有人生效
- **未触碰** gg（21 项）/ fb（6 项）的状态选项
- 删除前已确认 `accounts` / `fb_accounts` / `tt_accounts` 中**无任何行**指向被删的 TT 状态（无外键风险）；
  此时 `tt_accounts` 恰为空表，是最干净的时机
- ⚠️ **`存活` / `死亡` 是代码硬依赖，不可删除**（删了会被自动重建）：
  - `tt_accounts_routes.py:117,377` 建户默认状态写死 `存活`
  - `tt_accounts_routes.py:790,846` 充值校验「仅『存活』状态可充值」
  - `tt_accounts_routes.py:1095,1186` 表格同步由「是/空」推导 `死亡`/`存活`，且强制只接受这两个值
  - `tt_accounts_routes.py:71` `_resolve_status_id()` 查不到即自动 `INSERT`（`owner_id=1`）
  - `main.py:6442` 状态列表排序写死 `存活/死亡/验证/限额` 优先

### 2026-10-06 TT 账户清空说明

- 删除方式为**物理删除**（`DELETE FROM`），非软删，系统内不可恢复，**仅备份文件可回溯**
- 删除顺序沿用 `py/routes/tt_accounts_routes.py` 的 `permanent_delete_account()`：
  充值记录（按 `advertiser_id` 关联）→ BC 变更历史（按 `account_id` 关联）→ 账户本体
- **未触碰** `tt_bcs` / `tt_products` / `tt_packages` / `tt_recycle_reasons` 等非账户数据，也**未触碰 Google 表格**
- ⚠️ **复活路径**：`POST /api/tt/accounts/sync-from-sheet`（前端「从表格同步」按钮）会依据 Google 看板重新建户。
  清空后若误点该按钮，账户会被依据表格重新导入
- **备份方式**：服务运行中（WAL 模式）使用 sqlite3 backup API 在线快照，非直接拷贝 `app.db`
  （直接拷贝会丢失尚未 checkpoint 的 `-wal` 内容）；快照已通过 `PRAGMA integrity_check`
- **恢复方式**：停服后以快照覆盖 `temp/data/app.db`，并删除同目录 `app.db-wal` / `app.db-shm`；
  或从 CSV 按需重建（CSV 为 `utf-8-sig` 编码，Excel 可直接打开）
