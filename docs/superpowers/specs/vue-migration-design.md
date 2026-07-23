# Vue 前端重构设计

**日期**：2026-06-14
**状态**：已确认

## 1. 背景与目标

当前前端为单文件 HTML + 6 个独立 JS 文件，无框架、无模块化、无构建工具。项目规模增长后，代码组织困难（`main.py` ~2000 行，`account.js` ~1100 行），全局变量散落，DOM 操作与数据逻辑混杂。

**目标**：用 Vue 3 + Vite + Element Plus 重构前端，保持后端 Flask API 不变。

## 2. 架构

```
开发：  cd frontend && npm run dev     (Vite :5173, HMR, 代理 /api → Flask :5000)
        cd py && python main.py         (Flask API :5000)

生产：  npm run build → dist/           (纯静态 HTML/JS/CSS)
        PyInstaller py/main.py + dist/  → 单一 EXE (~VTier 0)
        EXE 启动 → Flask 提供 API + 静态文件
```

Flask 改为纯 API 服务，前端由 Vite 独立构建。

## 3. 技术选型

| 组件 | 选择 | 版本 |
|------|------|------|
| 框架 | Vue 3 | Composition API + `<script setup>` |
| 构建 | Vite | 5.x |
| UI 库 | Element Plus | 2.x |
| 路由 | Vue Router | 4.x |
| 状态 | Pinia | 2.x |
| HTTP | axios | 1.x |
| 语言 | JavaScript（后续可选迁移 TypeScript） | — |

## 4. 项目结构

```
ImageCrawling/
├── frontend/                  ← 新增：Vue + Vite 项目
│   ├── index.html
│   ├── vite.config.js
│   ├── package.json
│   └── src/
│       ├── main.js            ← 入口：创建 app、注册插件
│       ├── App.vue            ← 根组件：侧边栏 + <router-view>
│       ├── router/
│       │   └── index.js       ← 路由配置
│       ├── stores/
│       │   ├── auth.js        ← useAuthStore（骨架）
│       │   ├── accounts.js    ← 账户 + MCC + 设置
│       │   ├── products.js    ← 产品 + 包
│       │   ├── youtube.js     ← YouTube 视频
│       │   └── video.js       ← 视频生成
│       ├── api/
│       │   ├── client.js      ← axios 实例
│       │   ├── accounts.js    ← 账户/MCC/设置 API
│       │   ├── products.js    ← 产品/包 API
│       │   ├── youtube.js     ← YouTube API
│       │   ├── video.js       ← 视频生成 API
│       │   ├── scrape.js      ← 爬取 API
│       │   └── fonts.js       ← 字体 API
│       ├── views/
│       │   ├── AccountsView.vue   ← 账户管理（含子标签）
│       │   ├── ProductPanel.vue   ← 产品管理子面板
│       │   ├── AdsAccountPanel.vue← 广告账户子面板
│       │   ├── MccPanel.vue       ← MCC 管理子面板
│       │   ├── SettingsPanel.vue  ← 设置子面板
│       │   ├── YoutubeView.vue    ← YouTube 视频管理
│       │   ├── ScrapeView.vue     ← 图片爬取
│       │   ├── VideoView.vue      ← AI 视频生成
│       │   └── ToolkitView.vue    ← 工具集
│       └── components/
│           ├── AppSidebar.vue     ← 侧边栏导航
│           ├── ProductCard.vue    ← 产品卡片
│           ├── PackageRow.vue     ← 包行
│           ├── AccountModal.vue   ← 账户编辑弹窗
│           ├── MccModal.vue       ← MCC 编辑弹窗
│           ├── MccDetailModal.vue ← MCC 详情弹窗
│           ├── ProductModal.vue   ← 产品编辑弹窗
│           ├── YoutubeVideoItem.vue← YouTube 视频条目
│           └── common/            ← 通用组件（文件选择器等）
├── py/
│   └── main.py                ← 保持不变（纯 API）
├── index.html                 ← 废弃，由 frontend/dist/ 替代
├── js/                        ← 废弃，迁移后删除
├── css/                       ← 废弃
└── temp/                      ← 运行时数据，不变
```

## 5. 路由设计

```
/                        → redirect /accounts
/accounts                → AccountsView（默认子标签：产品管理）
/accounts/products       → ProductPanel
/accounts/ads            → AdsAccountPanel
/accounts/mcc            → MccPanel
/accounts/settings       → SettingsPanel
/youtube                 → YoutubeView
/youtube/view            → 视频展示
/youtube/import          → 导入视频
/youtube/config          → 标签配置
/scrape                  → ScrapeView
/video                   → VideoView
/toolkit                 → ToolkitView
/toolkit/zuobiao         → 做表数据
/toolkit/audio           → 音频替换
```

## 6. 状态管理

| Store | 主要状态 | 替代对象 |
|-------|---------|---------|
| `useAuthStore` | user, token, isLoggedIn | 新增 |
| `useProductStore` | products, total, page, filters | `prodState` |
| `useAccountStore` | accounts, mccList, settings | `acState`, `mccState`, `acSettings` |
| `useYoutubeStore` | videos, tags | YouTube 全局变量 |
| `useVideoStore` | images, tasks, config | 视频面板全局变量 |

每个 Store 内聚：状态 + getters + actions（包含 API 调用）。

## 7. API 层

```js
// api/client.js — axios 实例
const api = axios.create({ baseURL: '/api', timeout: 30000 })
api.interceptors.response.use(resp => resp.data, err => ...)

// api/accounts.js — 按模块组织
export const accountsApi = {
  list:   (params) => api.get('/accounts/list', { params }),
  create: (body)   => api.post('/accounts/create', body),
  update: (id, b)  => api.put(`/accounts/${id}`, b),
  delete: (id)     => api.delete(`/accounts/${id}`),
  batchDelete: (ids)   => api.post('/accounts/batch-delete', { ids }),
  batchUpdate: (body)  => api.post('/accounts/batch-update', body),
}
// 其他模块同理
```

后端 API 路由**不需要改动**——URI、请求体、响应格式全部不变。

## 8. UI 迁移

- 毛玻璃主题 → Element Plus 默认主题（后续可用 CSS 变量微调）
- 手写表格/弹窗/分页 → `<el-table>`, `<el-dialog>`, `<el-pagination>`
- `switchTab()` + display:none → `<router-view>`
- 手风琴产品卡片 → `<el-collapse>` 或自定义
- 文件选择器依赖 PowerShell 子进程 → 保持不变（通过 API 调用，与前端无关）

## 9. 打包

```
npm run build              → frontend/dist/
PyInstaller 打包           → 将 dist/ 作为静态文件打包进 EXE
main.py 适配               → static_folder 指向打包后的 dist 目录
```

开发模式下 Vite dev server 代理 `/api` 到 Flask；打包后 Flask 直接提供 `dist/` 文件。

## 10. 涉及的文件

| 文件 | 操作 |
|------|------|
| `frontend/` | **新建**（完整 Vue 项目） |
| `index.html` | **废弃**（Vite 生成） |
| `js/` | **废弃**（迁移后删除） |
| `css/style.css` | **废弃** |
| `py/main.py` | 微调静态文件路径适配 dev/prod |
| `requirements.txt` | 不变 |

## 11. 不在范围内

- 用户登录/权限系统（后续 brainstorming）
- Google Ads API 独立页面 `google-ads.html`（后续纳入 Vue）
- 后端 Flask 拆分/重构（保持不变）
- TypeScript 迁移（后续可选）

---

## 12. 审计补充（2026-07-23）

以下章节对比设计文档（2026-06-14）与当前 `frontend/src/` 实际代码，逐项列出差异。

### 12.1 路由设计差异

| 项目 | 设计文档 | 实际代码 | 说明 |
|------|---------|---------|------|
| 默认首页 | `/` → redirect `/accounts` | `/` → redirect `/youtube` | 默认入口改为 YouTube |
| `/login` | 无 | 有（`LoginView.vue`，`meta: { guest: true }`） | 新增登录页 |
| `/register` | 无 | 有（`RegisterView.vue`，`meta: { guest: true }`） | 新增注册页 |
| `/media` | 无 | 有（`MediaView.vue`） | 新增媒体工具页 |
| `/analysis` | 无 | 有（`AnalysisView.vue`） | 新增数据分析页 |
| `/data-manage` | 无 | 有（`DataManageView.vue`） | 新增数据管理页 |
| `/admin/users` | 无 | 有（`UserManageView.vue`，`meta: { admin: true }`） | 新增用户管理页 |
| `/admin/scheduler` | 无 | 有（`SchedulerView.vue`，`meta: { developer: true }`） | 新增定时任务页 |
| `/profile` | 无 | 有（`UserProfileView.vue`） | 新增个人信息页 |
| `/scrape` | 有（`ScrapeView`） | **未注册**（`ScrapeView.vue` 文件存在但路由中无此条目） | 疑似已废弃或合并到其他页面 |
| `/video` | 有（`VideoView`） | **未注册**（`VideoView.vue` 文件存在但路由中无此条目） | 疑似已废弃或合并到其他页面 |
| `/youtube/copywriting` | 无 | 有（`/youtube/copywriting`，指向 `YoutubeView.vue`） | 新增文案展示子标签 |
| `/toolkit/translate` | 无 | 有（`/toolkit/translate`，指向 `ToolkitView.vue`） | 新增翻译工具子标签 |
| Hash 模式 | 未提及 | `createWebHashHistory()`（即 `#/xxx` 格式 URL） | 避免 Flask 静态文件服务时的路由回退问题 |
| 路由守卫 | 未涉及 | 完整实现（见 12.2 节） | — |

### 12.2 路由守卫（设计文档未涉及，已完整实现）

`router/index.js` 的 `beforeEach` 守卫实现了四层权限控制：

1. **`guest` 白名单**：`/login`、`/register` 在未登录状态下可访问。
2. **`admin` 权限**：`/accounts/ads`、`/accounts/mcc`、`/accounts/settings`、`/admin/users` 仅 `admin` / `developer` 角色可访问。
3. **`developer` 权限**：`/admin/scheduler` 仅 `developer` 角色可访问。
4. **`viewer` 限制**：`viewer` 角色仅能访问 `/accounts/products`，访问其他 `/accounts/*` 子页面会被重定向到 `/accounts/products`。
5. **未登录拦截**：非 guest 页面在未登录状态下重定向到 `/login?redirect=原路径`。

### 12.3 项目结构差异

#### 12.3.1 新增文件（设计文档未列出）

**`api/` 目录**（设计文档列出 7 个，实际 12 个）：

| 文件 | 用途 |
|------|------|
| `auth.js` | 登录/注册/me API |
| `admin.js` | 用户管理 API（管理员功能） |
| `browse.js` | 浏览/文件操作 API |
| `data.js` | 数据管理 API |
| `google-sheets.js` | Google Sheets 导入导出 API |
| `reports.js` | 报表/广告报告 API |

**`stores/` 目录**（设计文档列出 5 个，实际 6 个）：

| 文件 | 用途 |
|------|------|
| `taskRunner.js` | 全局任务运行状态（Pinia + localStorage + BroadcastChannel 三重同步），管理视频生成、定时任务等长任务的状态轮询与跨 Tab 同步 |

**`views/` 目录**（设计文档列出 9 个，实际 17 个）：

| 文件 | 用途 |
|------|------|
| `LoginView.vue` | 登录页面 |
| `RegisterView.vue` | 注册页面 |
| `MediaView.vue` | 媒体工具页 |
| `AnalysisView.vue` | 数据分析页 |
| `DataManageView.vue` | 数据管理页 |
| `UserManageView.vue` | 用户管理页（管理员） |
| `UserProfileView.vue` | 个人信息/设置页 |
| `SchedulerView.vue` | 定时任务页（开发者） |

**`components/` 目录**（设计文档列出 9 个 + `common/`，实际 16 个 + `youtube/` 子目录）：

设计文档中有但实际不存在的：
- `PackageRow.vue` — 未找到，包行组件可能已被合并到 `ProductCard.vue` 或其他组件中。
- `YoutubeVideoItem.vue` — 未找到，YouTube 视频条目可能已重构为 Tab 组件。
- `common/` 目录 — 未创建，通用组件可能已分散放置或暂不需要。

设计文档中无但实际新增的：

| 文件 | 用途 |
|------|------|
| `AccountDetailModal.vue` | 账户详情弹窗 |
| `AccountBatchImportModal.vue` | 批量导入账户弹窗 |
| `AccountBatchLookupModal.vue` | 批量查询账户弹窗 |
| `AddPackageModal.vue` | 添加包弹窗 |
| `CopyImportModal.vue` | 复制导入弹窗 |
| `GlobalTaskPanel.vue` | 全局任务面板（右下角浮动面板） |
| `ProductDetailModal.vue` | 产品详情弹窗 |
| `RechargeModal.vue` | 充值弹窗 |
| `RechargeBatchModal.vue` | 批量充值弹窗 |
| `youtube/CopywritingTab.vue` | YouTube 文案 Tab |
| `youtube/ImportTab.vue` | YouTube 导入 Tab |
| `youtube/TagsConfig.vue` | YouTube 标签配置 |

**全新目录**：

| 目录 | 文件 | 用途 |
|------|------|------|
| `src/composables/` | `useDebounce.js`、`usePagination.js` | Vue 3 组合式函数 |
| `src/utils/` | `adsParser.js`、`broadcast.js`、`clipboard.js`、`dedupLoader.js`、`env.js`、`statusTag.js` | 工具函数（广告解析、跨 Tab 广播、剪贴板、去重、环境变量、状态标签） |
| `src/assets/` | `global.css` | 全局样式 |

### 12.4 API 层差异

`client.js` 与设计文档的差异：

| 项目 | 设计文档 | 实际代码 |
|------|---------|---------|
| 请求拦截器 | 无 | 自动从 `localStorage` 读取 `token` 并注入 `Authorization: Bearer xxx` 请求头 |
| 响应拦截器（成功） | `resp => resp.data` | 先检查 `x-new-access-token` 响应头，存在则自动更新 localStorage（滑动过期机制），然后返回 `resp.data` |
| 响应拦截器（错误） | `err => ...`（仅占位） | 401 错误时清除 token/user，跳转到 `#/login`；跳过 `/auth/` 路径避免死循环 |

### 12.5 Store 差异

| 设计文档 | 实际代码 | 差异说明 |
|---------|---------|---------|
| `useAuthStore` — 骨架 | 完整实现 | 包含 `login()`、`register()`、`fetchMe()`、`logout()`、`initFromStorage()` actions；getters: `isAdmin`、`isDeveloper`、`isViewer`、`canAccessProducts`、`roleLabel`。支持 5 种角色：`developer`、`admin`、`viewer`、`user`、`hidden` |
| `useProductStore` | `stores/products.js` | 已实现 |
| `useAccountStore` | `stores/accounts.js` | 已实现 |
| `useYoutubeStore` | `stores/youtube.js` | 已实现 |
| `useVideoStore` | `stores/video.js` | 已实现 |
| —（未设计） | `stores/taskRunner.js` | 全局任务运行状态管理，支持 Pinia + localStorage + BroadcastChannel 三重同步（详见 12.3.1） |

### 12.6 App.vue 差异

设计文档描述为简单的 "侧边栏 + `<router-view>`"，实际实现大幅增强：

1. **认证页面判断**：`/login`、`/register` 页面全屏渲染、无侧边栏布局（`isAuthPage` computed）。
2. **`<keep-alive>`**：包裹 `<router-view>` 以保持页面组件状态，路由切换时不销毁。
3. **`GlobalTaskPanel`**：全局右侧浮动任务面板，显示视频生成等长任务的进度。
4. **掉包通知轮询**：每 30 秒检查掉包通知，通过 `ElNotification` 弹窗提醒用户。
5. **跨 Tab 同步**：使用 `BroadcastChannel` 同步掉包通知的已读/已关闭状态（`DELIST_NOTIFIED`、`DELIST_DISMISSED` 消息类型）。
6. **Telegram 未配置提醒**：检测到掉包但用户未配置 Telegram 用户名时，弹 `ElMessage.warning` 提示（仅一次）。

### 12.7 main.js 差异

| 项目 | 设计文档描述 | 实际代码 |
|------|------------|---------|
| Element Plus | 未提及细节 | 注册了中文本地化（`zhCn`），全局组件尺寸设为 `large` |
| 全局样式 | 未提及 | 引入 `assets/global.css` |
| Pinia | 仅提及选型 | 通过 `createPinia()` 实例化并注册 |

### 12.8 技术栈版本差异

| 组件 | 设计文档预期 | 实际 package.json | 说明 |
|------|------------|-------------------|------|
| Vite | 5.x | `^6.0.5` | 升级到 Vite 6 |
| 额外依赖 | 未提及 | `@element-plus/icons-vue: ^2.3.1` | Element Plus 图标库 |
| 额外依赖 | 未提及 | `echarts: ^6.1.0`、`vue-echarts: ^8.0.1` | 图表库 |
| devDependencies | 未提及 | `terser: ^5.49.0` | 生产构建时代码压缩 |

### 12.9 构建配置差异

`vite.config.js` 实现了设计文档未详细描述的配置：

| 配置项 | 实际值 | 说明 |
|--------|--------|------|
| `resolve.alias` | `@` → `./src` | 路径别名，组件中使用 `@/api/xxx` 导入 |
| `server.host` | `0.0.0.0` | 允许局域网访问 Vite dev server |
| `server.proxy` | `/api` → `http://127.0.0.1:5001` | **注意：端口为 5001，设计文档写的是 5000** |
| `build.target` | `es2015` | 兼容旧浏览器 |
| `build.minify` | `terser`（`drop_console: true, drop_debugger: true`） | 生产构建自动移除 console 和 debugger |
| `manualChunks` | 拆分为 `vue-vendor`、`element-plus`、`echarts` 三个独立 chunk | 优化缓存策略 |

### 12.10 "不在范围内" 功能的实际实现情况

| 设计文档声明"不在范围内" | 实际状态 |
|-------------------------|---------|
| 用户登录/权限系统 | **已完整实现**：注册 (`/register`)、登录 (`/login`)、JWT token 认证、5 级角色系统 (developer/admin/viewer/user/hidden)、`beforeEach` 路由守卫、滑动过期 token、个人信息页 (`/profile`)、用户管理页 (`/admin/users`) |
| Google Ads API 独立页面 | 状态未明，`google-ads.html` 未在 `frontend/src/` 目录内发现 |

### 12.11 其他发现

1. **`ScrapeView.vue` 和 `VideoView.vue` 为孤立文件**：这两个 Vue 组件在 `src/views/` 目录下存在，但未在 `router/index.js` 中注册任何路由。可能是已废弃但未清理的残留文件，或被合并到其他视图后遗留。建议确认后清理。
2. **YoutubeView 和 ToolkitView 子路由实现方式**：设计文档暗示每个子路由对应独立组件，实际所有子路由都指向同一个视图组件（`YoutubeView.vue` 或 `ToolkitView.vue`），由组件内部通过 `el-tabs` 或类似方式切换子视图。这是一种简化的实现策略，优点是不需要为每个子标签创建单独组件，缺点是所有子标签的代码集中在一个文件中。
3. **Flask 端口不匹配**：设计文档声明 Flask 运行在 5000 端口，但 `vite.config.js` 的 proxy 目标为 `127.0.0.1:5001`。如果在实际开发中使用 5001 端口（例如 `python main.py` 命令行参数指定），则文档需同步更新；如果是配置错误，则需修正 `vite.config.js`。
4. **Hash 路由模式**：使用 `createWebHashHistory` 而非 HTML5 History 模式。原因是后端为 Flask，非 SPA 专用的静态文件服务器，Hash 模式避免了 URL 路由回退的配置问题。此为合理的设计决策，但设计文档应予以说明。
