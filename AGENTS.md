# GG-Server 多人协作版设计文档

> 基于 ImageCrawling（谷歌广告图片爬取与处理工具）改造的多人协作服务器版本。
> 新增用户系统、数据隔离、权限管理，支持局域网内多人同时使用。

## 项目概述

谷歌广告运营工具箱的多人协作版本 — 包含图片爬取、AI 视频生成、YouTube 视频管理、产品管理、数据做表、广告账户管理、充值管理、掉包检测、数据分析、全局任务追踪、Facebook（FB）广告平台管理、代理池等模块。

### 与 ImageCrawling 的关系
- **ImageCrawling**：单用户本地工具，PyInstaller 打包为独立 EXE
- **GG-Server**：从 ImageCrawling 复制的独立项目，叠加用户系统 + 数据隔离，作为常开 Flask 服务运行
- 两个项目互不干扰，可并存使用

## 技术栈

| 组件 | 选择 | 说明 |
|------|------|------|
| 后端框架 | Flask | 纯 API 服务，main.py ~9800 行 + routes/ 目录 |
| 数据库 | SQLite (WAL 模式) | `temp/app.db`，局域网 20 人以下足够 |
| 认证 | Flask-JWT-Extended | JWT token，24h 过期，支持滑动刷新 |
| 密码 | Werkzeug pbkdf2:sha256 | Flask 内置哈希 |
| 前端 | Vue 3 + Vite + Element Plus + Pinia + Vue Router | Composition API |
| HTTP | axios | 全局拦截器自动携带 JWT token |
| 定时任务 | 后台 daemon 线程 | 掉包检测（每小时，走代理池）、每周清理 |
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
  |  +- SQLite (WAL mode, temp/app.db)      |
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
    platform    TEXT DEFAULT 'gg',   -- 'gg' | 'fb'，developer 双平台
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
- 字典表 `agents` / `account_statuses` / `mcc_levels` / `sales_persons` / `regions` — GG/FB 共用

#### 个人数据（按 user_id 隔离）
- `accounts` — GG 广告账户管理（owner_id）
- `mcc` — GG MCC 管理（owner_id）
- `video_history` — AI 视频生成历史
- `videos`（is_public=0）— YouTube 个人视频库
- `ad_reports` / `fb_ad_reports` — 做表数据
- `recharge_records` — 充值记录（created_by 隔离）

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
│   │   │   ├── SchedulerView.vue       # 定时任务手动触发（developer）
│   │   │   └── fb/                     # FB 平台页面
│   │   │       ├── FbAccountPanel.vue  # FB 账户管理
│   │   │       ├── FbBmPanel.vue       # FB 账户 BM 管理
│   │   │       ├── FbProductPanel.vue  # FB 产品管理
│   │   │       ├── FbPixelPanel.vue    # FB 像素管理
│   │   │       ├── FbPixelBmPanel.vue  # FB 像素 BM 管理
│   │   │       ├── FbDataExtract.vue   # FB 数据提取
│   │   │       ├── FbDataManage.vue    # FB 数据管理
│   │   │       └── FbSettingsPanel.vue # FB 系统设置
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
│   │   ├── auth_routes.py         # 认证相关 Blueprint（已激活）
│   │   └── fb_routes.py           # FB 平台 Blueprint（已激活，49 路由）
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

### 定时任务（仅 developer）
| 方法 | 路径 | 说明 |
|------|------|------|
| POST | /api/admin/trigger-delist-check | 手动触发掉包检测 |
| POST | /api/admin/trigger-weekly-cleanup | 手动触发每周清理 |

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

### FB 平台（fb_routes.py，49 路由）
| 方法 | 路径 | 说明 |
|------|------|------|
| GET/POST/PUT/DELETE | /api/fb/bms/... | 账户 BM 管理（含 ban-and-migrate） |
| GET/POST/PUT/DELETE | /api/fb/accounts/... | FB 账户管理（软删除/恢复/BM 历史） |
| GET/POST/PUT/DELETE | /api/fb/products/... | FB 产品管理（线名、在跑 BM） |
| GET/POST/PUT/DELETE | /api/fb/pixel-bms/... | 像素 BM 管理 |
| GET/POST/PUT/DELETE | /api/fb/pixels/... | 像素管理 |
| POST | /api/fb/extract/parse | 解析粘贴的 FB 数据透视表 |
| POST | /api/fb/extract/save | 保存提取数据（双写 DB + Sheets） |
| POST | /api/fb/extract/check-duplicates | 重复校验 |
| GET/POST/PUT/DELETE | /api/fb/reports/... | FB 做表数据管理 + Sheets 同步 |

### 其他模块路由

所有路由均需 `@jwt_required()`，返回 `{"success": bool, ...}` 格式。路由总数约 240 个（main.py 177 + fb_routes 49 + auth_routes 12），分布在 GG/FB 双平台 15+ 个模块中。

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
- **检测方式**：HTTP 请求 Google Play 链接，通过状态码和页面内容判断（404 / "not found" / "找不到请求的网址"）
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

- **掉包检测**：每小时自动执行，后台 daemon 线程
- **每周清理**：清理过期爬取图片和生成视频
- **手动触发**：SchedulerView 页面，仅 developer 角色可见，支持即时执行

### 大规模重构（进行中）

- **后端**：main.py (~9800 行) 逐步拆分为 Flask Blueprint，目标 18 个 route 文件
- **前端**：大组件（YoutubeView/MediaView/AnalysisView/VideoView）逐步拆分为子组件
- **已完成**：auth_routes.py、fb_routes.py Blueprint 激活、helpers 扩展、JWT 滑动过期、前端 3 个 Tab 独立、dedupLoader 公共化

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
- **后端独立**：`routes/fb_routes.py`（49 路由）+ `database.py` 新增 11 张 fb_* 表
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

### 掉包通知按产品聚合

掉包通知从按包聚合改为按产品聚合，同一产品多包掉包合并为一条通知。

- `delist/pending` 按产品聚合返回，前端弹窗按产品展示
- `delist/dismiss` 支持批量关闭
- Telegram 通知按产品分组发送

### 视频频道名

YouTube 视频新增频道名（channel name）字段，导入时自动获取频道信息。

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
- [TT 掉包通知（独立机器人）](docs/superpowers/specs/2026-09-24-tt-delist-notification-design.md)
- [续作指南](docs/superpowers/specs/NEXT-STEPS.md)

## 数据库表总览

> 共 40 张表：GG 平台 29 张 + FB 平台 11 张。字典表（选项表）5 张 GG/FB 共用。

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
- **每次改完 bug 或完成需求后，提醒我提交 git**
- **每次新的文档都要建立索引**
- /test-driven-development 使用这个测试新需求
- SQLite 数据库自动建表 + 迁移，位于 `temp/app.db`
- 本项目是 ImageCrawling 的独立副本，修改不影响原项目
- **后端重构进行中**：main.py 正逐步拆分为 Blueprint（`py/routes/`），新增路由优先写入独立 Blueprint 文件
- **前端大组件拆分进行中**：YoutubeView/MediaView/AnalysisView/VideoView 逐步拆分为子组件
