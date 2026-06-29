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
