# Vue 前端重构 — 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将现有零框架 HTML+JS 前端迁移到 Vue 3 + Vite + Element Plus，后端 Flask API 不变

**Architecture:** `frontend/` 目录为独立 Vue 项目，开发时 Vite dev server 代理 `/api` 到 Flask :5000；生产时 `npm run build` 产出 `dist/` 静态文件，PyInstaller 打包进 EXE

**Tech Stack:** Vue 3 (Composition API + `<script setup>`), Vite 5, Element Plus 2, Vue Router 4, Pinia 2, axios 1

---

## 文件结构总览

```
frontend/
├── index.html
├── package.json
├── vite.config.js
└── src/
    ├── main.js
    ├── App.vue
    ├── router/index.js
    ├── api/
    │   ├── client.js          # axios 实例 (baseURL: "", 代理 /api → Flask)
    │   ├── accounts.js        # 账户 / MCC / 设置 API
    │   ├── products.js        # 产品 / 包 API
    │   ├── youtube.js         # YouTube 视频 API
    │   ├── video.js           # 视频生成 / 历史 / 字体 API
    │   ├── scrape.js          # 爬取 API
    │   └── browse.js          # 文件对话框 API (仅本机)
    ├── stores/
    │   ├── accounts.js        # useAccountStore (账户 + MCC + 设置)
    │   ├── products.js        # useProductStore (产品 + 包)
    │   ├── youtube.js         # useYoutubeStore
    │   ├── video.js           # useVideoStore
    │   └── auth.js            # useAuthStore (骨架)
    ├── views/
    │   ├── AccountsView.vue   # 账户管理容器 (router-view 嵌套子路由)
    │   ├── ProductPanel.vue   # 产品管理子面板
    │   ├── AdsAccountPanel.vue# 广告账户子面板
    │   ├── MccPanel.vue       # MCC 管理子面板
    │   ├── SettingsPanel.vue  # 设置子面板
    │   ├── YoutubeView.vue    # YouTube 管理容器
    │   ├── ScrapeView.vue     # 图片爬取
    │   ├── VideoView.vue      # AI 视频生成
    │   └── ToolkitView.vue    # 工具集 (做表 + 音频替换)
    └── components/
        ├── AppSidebar.vue
        ├── ProductCard.vue
        ├── PackageRow.vue
        ├── AccountModal.vue
        ├── MccModal.vue
        ├── MccDetailModal.vue
        ├── ProductModal.vue
        ├── ProductDetailModal.vue
        ├── CopyImportModal.vue
        ├── AddPackageModal.vue
        └── YouTubeVideoItem.vue
```

---

## Task 1: 脚手架 — 创建 Vue + Vite 项目

**Files:** Create `frontend/` 目录下所有基础文件

- [ ] **Step 1: 创建 package.json**

```bash
mkdir -p frontend/src/{views,components,api,stores,router}
```

创建 `frontend/package.json`:
```json
{
  "name": "gp-image-scraper",
  "private": true,
  "version": "1.0.0",
  "scripts": {
    "dev": "vite",
    "build": "vite build",
    "preview": "vite preview"
  },
  "dependencies": {
    "vue": "^3.5.13",
    "vue-router": "^4.5.0",
    "pinia": "^2.3.0",
    "axios": "^1.7.9",
    "element-plus": "^2.9.1",
    "@element-plus/icons-vue": "^2.3.1"
  },
  "devDependencies": {
    "@vitejs/plugin-vue": "^5.2.1",
    "vite": "^6.0.5"
  }
}
```

- [ ] **Step 2: 安装依赖**

```bash
cd frontend && npm install
```

- [ ] **Step 3: 创建 vite.config.js**

```js
import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

export default defineConfig({
  plugins: [vue()],
  server: {
    proxy: {
      '/api': 'http://localhost:5000',
      '/js': 'http://localhost:5000',    // 字体文件等
      '/fonts': 'http://localhost:5000',
    }
  },
  build: {
    outDir: 'dist',
    assetsDir: 'assets',
  }
})
```

- [ ] **Step 4: 创建 frontend/index.html**

```html
<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>卡天皇运营工具箱</title>
</head>
<body>
  <div id="app"></div>
  <script type="module" src="/src/main.js"></script>
</body>
</html>
```

- [ ] **Step 5: 创建 src/main.js**

```js
import { createApp } from 'vue'
import { createPinia } from 'pinia'
import ElementPlus from 'element-plus'
import 'element-plus/dist/index.css'
import zhCn from 'element-plus/es/locale/lang/zh-cn'
import App from './App.vue'
import router from './router'

const app = createApp(App)
app.use(createPinia())
app.use(router)
app.use(ElementPlus, { locale: zhCn })
app.mount('#app')
```

- [ ] **Step 6: 验证脚手架**

```bash
cd frontend && npx vite --host 0.0.0.0
# 浏览器打开 http://localhost:5173，应该看到空白页（App.vue 还是空的）
```

- [ ] **Step 7: Commit**

```bash
git add frontend/package.json frontend/package-lock.json frontend/vite.config.js frontend/index.html frontend/src/main.js
git commit -m "feat: scaffold Vue + Vite + Element Plus project"
```

---

## Task 2: 路由 + App 骨架 + 侧边栏

**Files:** Create `src/router/index.js`, `src/App.vue`, `src/components/AppSidebar.vue`

- [ ] **Step 1: 创建路由配置 `src/router/index.js`**

```js
import { createRouter, createWebHashHistory } from 'vue-router'

const routes = [
  {
    path: '/',
    redirect: '/accounts'
  },
  {
    path: '/accounts',
    component: () => import('../views/AccountsView.vue'),
    redirect: '/accounts/products',
    children: [
      { path: 'products', component: () => import('../views/ProductPanel.vue'), meta: { title: '产品管理' } },
      { path: 'ads', component: () => import('../views/AdsAccountPanel.vue'), meta: { title: '广告账户' } },
      { path: 'mcc', component: () => import('../views/MccPanel.vue'), meta: { title: 'MCC 管理' } },
      { path: 'settings', component: () => import('../views/SettingsPanel.vue'), meta: { title: '设置' } },
    ]
  },
  {
    path: '/youtube',
    component: () => import('../views/YoutubeView.vue'),
    redirect: '/youtube/view',
    children: [
      { path: 'view', component: () => import('../views/YoutubeView.vue'), meta: { title: '视频展示' } },
      { path: 'import', component: () => import('../views/YoutubeView.vue'), meta: { title: '导入视频' } },
      { path: 'config', component: () => import('../views/YoutubeView.vue'), meta: { title: '标签配置' } },
    ]
  },
  { path: '/scrape', component: () => import('../views/ScrapeView.vue'), meta: { title: '图片爬取' } },
  { path: '/video', component: () => import('../views/VideoView.vue'), meta: { title: 'AI 视频生成' } },
  {
    path: '/toolkit',
    component: () => import('../views/ToolkitView.vue'),
    redirect: '/toolkit/zuobiao',
    children: [
      { path: 'zuobiao', component: () => import('../views/ToolkitView.vue'), meta: { title: '做表数据' } },
      { path: 'audio', component: () => import('../views/ToolkitView.vue'), meta: { title: '音频替换' } },
    ]
  },
]

export default createRouter({
  history: createWebHashHistory(),
  routes,
})
```

说明：使用 `createWebHashHistory` 而非 `createWebHistory`，因为打包后 Flask 只能提供 SPA 入口（无需 Flask 配置 URL 重写）。

- [ ] **Step 2: 创建侧边栏组件 `src/components/AppSidebar.vue`**

```vue
<template>
  <el-menu
    :default-active="activeMenu"
    :collapse="false"
    background-color="#fafbfc"
    text-color="#555770"
    active-text-color="#0891b2"
    router
    style="height:100vh;border-right:1px solid #e5e7eb;"
  >
    <div style="padding:20px 20px 12px;font-size:13px;font-weight:600;color:#555770;letter-spacing:0.15em;">
      🖼️ 卡天皇莫乱来
    </div>
    <el-menu-item index="/accounts">
      <span>🏢 账户管理</span>
    </el-menu-item>
    <el-menu-item index="/youtube">
      <span>📺 视频管理</span>
    </el-menu-item>
    <el-menu-item index="/scrape">
      <span>📥 图片爬取</span>
    </el-menu-item>
    <el-menu-item index="/video">
      <span>🎬 AI 视频生成</span>
    </el-menu-item>
    <el-menu-item index="/toolkit">
      <span>🧰 工具集</span>
    </el-menu-item>
  </el-menu>
</template>

<script setup>
import { computed } from 'vue'
import { useRoute } from 'vue-router'

const route = useRoute()
const activeMenu = computed(() => {
  const p = route.path
  if (p.startsWith('/accounts')) return '/accounts'
  if (p.startsWith('/youtube')) return '/youtube'
  if (p.startsWith('/toolkit')) return '/toolkit'
  return p
})
</script>
```

- [ ] **Step 3: 创建 App.vue**

```vue
<template>
  <div style="display:flex;min-height:100vh;">
    <AppSidebar />
    <div style="flex:1;padding:24px;overflow-y:auto;">
      <router-view />
    </div>
  </div>
</template>

<script setup>
import AppSidebar from './components/AppSidebar.vue'
</script>
```

- [ ] **Step 4: 创建占位视图页面（7 个空壳）**

每个视图文件先写最小内容，例如 `src/views/ProductPanel.vue`:
```vue
<template>
  <div>
    <h2>📦 产品管理</h2>
    <p style="color:#888;">迁移中...</p>
  </div>
</template>
```

同样创建: `AccountsView.vue`, `AdsAccountPanel.vue`, `MccPanel.vue`, `SettingsPanel.vue`, `YoutubeView.vue`, `ScrapeView.vue`, `VideoView.vue`, `ToolkitView.vue`。

- [ ] **Step 5: 验证路由**

```bash
cd frontend && npx vite --host 0.0.0.0
# 浏览器打开 http://localhost:5173
# 应看到侧边栏 + 页面切换（URL hash 变化）
# 确保 Flask 也在运行: cd py && python main.py
```

- [ ] **Step 6: Commit**

```bash
git add frontend/src/
git commit -m "feat: Vue Router + AppSidebar + 视图占位页面"
```

---

## Task 3: API 层

**Files:** Create `src/api/` 目录下所有文件

- [ ] **Step 1: 创建 axios 实例 `src/api/client.js`**

```js
import axios from 'axios'

const api = axios.create({
  baseURL: '',  // 相对路径，开发时 Vite 代理到 Flask，生产时同域
  timeout: 60000,
})

api.interceptors.response.use(
  resp => resp.data,
  err => {
    const msg = err.response?.data?.error || err.message || '请求失败'
    return Promise.reject(new Error(msg))
  }
)

export default api
```

- [ ] **Step 2: 创建 `src/api/accounts.js`**

```js
import api from './client'

export const accountsApi = {
  list:   (params) => api.get('/api/accounts/list', { params }),
  create: (body)   => api.post('/api/accounts/create', body),
  update: (id, body) => api.put(`/api/accounts/${id}`, body),
  delete: (id)     => api.delete(`/api/accounts/${id}`),
  batchDelete: (ids) => api.post('/api/accounts/batch-delete', { ids }),
  batchUpdate: (body) => api.post('/api/accounts/batch-update', body),
}

export const mccApi = {
  list:   (params) => api.get('/api/mcc/list', { params }),
  options:()       => api.get('/api/mcc/options'),
  create: (body)   => api.post('/api/mcc/create', body),
  update: (id, body) => api.put(`/api/mcc/${id}`, body),
  delete: (id)     => api.delete(`/api/mcc/${id}`),
  batchDelete: (ids) => api.post('/api/mcc/batch-delete', { ids }),
  detail: (id)     => api.get(`/api/mcc/${id}/detail`),
}

export const settingsApi = {
  get: ()     => api.get('/api/settings/account'),
  save: (body) => api.post('/api/settings/account', body),
}
```

- [ ] **Step 3: 创建 `src/api/products.js`**

```js
import api from './client'

export const productsApi = {
  list:        (params) => api.get('/api/products/list', { params }),
  create:      (body)   => api.post('/api/products/create', body),
  update:      (id, body) => api.put(`/api/products/${id}`, body),
  delete:      (id)     => api.delete(`/api/products/${id}`),
  detail:      (id)     => api.get(`/api/products/${id}/detail`),
  addPackage:  (pid, body) => api.post(`/api/products/${pid}/packages`, body),
  updatePackage: (pkgId, body) => api.put(`/api/products/packages/${pkgId}`, body),
  deletePackage: (pkgId) => api.delete(`/api/products/packages/${pkgId}`),
  importText:  (body)   => api.post('/api/products/import-text', body),
}
```

- [ ] **Step 4: 创建 `src/api/youtube.js`**

```js
import api from './client'

export const youtubeApi = {
  list:    (params) => api.get('/api/youtube/list', { params }),
  import:  (body)   => api.post('/api/youtube/import', body),
  delete:  (body)   => api.post('/api/youtube/delete', body),
  edit:    (body)   => api.post('/api/youtube/edit', body),
  tagsGet: ()       => api.get('/api/youtube/tags'),
  tagsSave:(body)   => api.post('/api/youtube/tags', body),
}
```

- [ ] **Step 5: 创建 `src/api/video.js`**

```js
import api from './client'

export const videoApi = {
  scanDir:     (body) => api.post('/api/video/scan-dir', body),
  generate:    (body) => api.post('/api/video/generate', body),
  progress:    (taskId) => api.get(`/api/video/progress?task_id=${taskId}`),
  nextFilename:(body) => api.post('/api/video/next-filename', body),
  historyList: ()     => api.get('/api/video/history/list'),
  historySave: (body) => api.post('/api/video/history/save', body),
  historyDelete:(body)=> api.post('/api/video/history/delete', body),
  audioReplace:(body) => api.post('/api/audio-replace', body),
  fontsList:   ()     => api.get('/api/fonts/list'),
  fontsImport: (body) => api.post('/api/fonts/import', body),
  fontsMarkUsed:(body)=> api.post('/api/fonts/mark-used', body),
}
```

- [ ] **Step 6: 创建 `src/api/scrape.js`**

```js
import api from './client'

export const scrapeApi = {
  scrape: (body) => api.post('/api/scrape', body),
}
```

- [ ] **Step 7: 创建 `src/api/browse.js`**

```js
import api from './client'

export const browseApi = {
  file:   (body) => api.post('/api/browse-file', body),
  save:   (body) => api.post('/api/browse-save', body),
  folder: (body) => api.post('/api/browse-folder', body),
}
```

- [ ] **Step 8: Commit**

```bash
git add frontend/src/api/
git commit -m "feat: axios API 层 — accounts/mcc/products/youtube/video/scrape/browse"
```

---

## Task 4: Pinia Stores

**Files:** Create `src/stores/` 目录下所有文件

- [ ] **Step 1: 创建 `src/stores/auth.js`（骨架）**

```js
import { defineStore } from 'pinia'

export const useAuthStore = defineStore('auth', {
  state: () => ({
    user: null,
    token: '',
    isLoggedIn: false,
  }),
  actions: {
    login(credentials) { /* 后续实现 */ },
    logout() { this.user = null; this.token = ''; this.isLoggedIn = false; },
  },
})
```

- [ ] **Step 2: 创建 `src/stores/accounts.js`**

```js
import { defineStore } from 'pinia'
import { accountsApi, mccApi, settingsApi } from '@/api/accounts'

export const useAccountStore = defineStore('accounts', {
  state: () => ({
    // 账户
    accounts: [],
    acTotal: 0,
    acPage: 1,
    acPageSize: 20,
    acFilters: { search: '', status: '', mcc_id: '', agent: '' },
    // MCC
    mccList: [],
    mccTotal: 0,
    mccPage: 1,
    mccPageSize: 20,
    mccFilters: { search: '', level: '', parent_filter: '' },
    // 设置
    settings: { account_statuses: ['存活','死亡','验证','限额'], account_agents: [], mcc_levels: [] },
  }),

  actions: {
    // ---- 账户 ----
    async loadAccounts() {
      const params = { page: this.acPage, size: this.acPageSize, ...this.acFilters }
      const res = await accountsApi.list(params)
      this.accounts = res.accounts
      this.acTotal = res.total
      return res  // 返回完整响应（含 mcc_options, agents）
    },
    async createAccount(body) { return accountsApi.create(body) },
    async updateAccount(id, body) { return accountsApi.update(id, body) },
    async deleteAccount(id) { await accountsApi.delete(id); return this.loadAccounts() },
    async batchDeleteAccounts(ids) { await accountsApi.batchDelete(ids); return this.loadAccounts() },
    async batchUpdateAccounts(body) { await accountsApi.batchUpdate(body); return this.loadAccounts() },

    // ---- MCC ----
    async loadMccList() {
      const params = { page: this.mccPage, size: this.mccPageSize, ...this.mccFilters }
      const res = await mccApi.list(params)
      this.mccList = res.mcc_list
      this.mccTotal = res.total
    },
    async createMcc(body) { return mccApi.create(body) },
    async updateMcc(id, body) { return mccApi.update(id, body) },
    async deleteMcc(id) { await mccApi.delete(id); return this.loadMccList() },
    async batchDeleteMcc(ids) { await mccApi.batchDelete(ids); return this.loadMccList() },
    async loadMccDetail(id) { return mccApi.detail(id) },

    // ---- 设置 ----
    async loadSettings() {
      const res = await settingsApi.get()
      this.settings = res.settings
    },
    async saveSettings(body) { return settingsApi.save(body) },
  },
})
```

- [ ] **Step 3: 创建 `src/stores/products.js`**

```js
import { defineStore } from 'pinia'
import { productsApi } from '@/api/products'

export const useProductStore = defineStore('products', {
  state: () => ({
    products: [],
    total: 0,
    page: 1,
    pageSize: 10,
    pausedMode: false,
    filters: { search: '', region: '', mcc_id: '' },
  }),

  actions: {
    async loadProducts() {
      const params = {
        page: this.page, size: this.pageSize,
        search: this.filters.search || undefined,
        region: this.filters.region || undefined,
        mcc_id: this.filters.mcc_id || undefined,
        status: this.pausedMode ? 'paused' : '',
      }
      const res = await productsApi.list(params)
      this.products = res.products
      this.total = res.total
      return res
    },
    async createProduct(body) { return productsApi.create(body) },
    async updateProduct(id, body) { return productsApi.update(id, body) },
    async deleteProduct(id) { await productsApi.delete(id); return this.loadProducts() },
    async loadProductDetail(id) { return productsApi.detail(id) },
    async addPackage(pid, body) { return productsApi.addPackage(pid, body) },
    async updatePackage(pkgId, body) { return productsApi.updatePackage(pkgId, body) },
    async deletePackage(pkgId) { await productsApi.deletePackage(pkgId); return this.loadProducts() },
    async importText(body) { return productsApi.importText(body) },
  },
})
```

- [ ] **Step 4: 创建 `src/stores/youtube.js`**

```js
import { defineStore } from 'pinia'
import { youtubeApi } from '@/api/youtube'

export const useYoutubeStore = defineStore('youtube', {
  state: () => ({
    videos: [],
    counts: {},
    tags: { regions: [], frame_types: [], effectiveness: [], product_names: [] },
    filters: { region: '', frame_type: '', effectiveness: '', product_name: '' },
  }),

  actions: {
    async loadVideos() {
      const res = await youtubeApi.list(this.filters)
      this.videos = res.videos
      this.counts = res.counts
      return res
    },
    async importVideos(body) { return youtubeApi.import(body) },
    async deleteVideos(ids) { await youtubeApi.delete({ ids }); return this.loadVideos() },
    async editVideo(body) { return youtubeApi.edit(body) },
    async loadTags() { const res = await youtubeApi.tagsGet(); this.tags = res.tags; return res },
    async saveTags(body) { return youtubeApi.tagsSave(body) },
  },
})
```

- [ ] **Step 5: 创建 `src/stores/video.js`**

```js
import { defineStore } from 'pinia'
import { videoApi } from '@/api/video'

export const useVideoStore = defineStore('video', {
  state: () => ({
    images: [],
    logo: null,
    taskId: '',
    tasks: [],
    history: {},
    fonts: [],
    settings: { /* 视频参数暂存 */ },
  }),

  actions: {
    async scanDir(dir) { const res = await videoApi.scanDir({ dir }); this.images = res.images; this.logo = res.logo; return res },
    async generate(body) { const res = await videoApi.generate(body); return res },
    async checkProgress(taskId) { return videoApi.progress(taskId) },
    async loadHistory() { const res = await videoApi.historyList(); this.history = res.packages; return res },
    async saveHistory(entry) { return videoApi.historySave({ entry }) },
    async deleteHistory(pkg, indices) { return videoApi.historyDelete({ pkg, indices }) },
    async loadFonts() { const res = await videoApi.fontsList(); this.fonts = res.fonts; return res },
    async audioReplace(body) { return videoApi.audioReplace(body) },
  },
})
```

- [ ] **Step 6: Commit**

```bash
git add frontend/src/stores/
git commit -m "feat: Pinia stores — auth/accounts/products/youtube/video"
```

---

## Task 5: 迁移账户管理 — 设置子面板

**Files:** Modify `src/views/SettingsPanel.vue`

这是最简单的面板，先做它验证 Store + API 联调。

- [ ] **Step 1: 实现 SettingsPanel.vue**

```vue
<template>
  <div>
    <h2>⚙ 设置</h2>
    <p style="color:#888;margin-bottom:20px;">自定义下拉框选项，修改后全局生效</p>

    <el-row :gutter="16">
      <el-col :span="12">
        <el-form-item label="账户状态选项">
          <el-input v-model="form.account_statuses" type="textarea" :rows="5"
            placeholder="每行一个" />
        </el-form-item>
      </el-col>
      <el-col :span="12">
        <el-form-item label="代理名选项">
          <el-input v-model="form.account_agents" type="textarea" :rows="5"
            placeholder="每行一个（留空则自由输入）" />
        </el-form-item>
      </el-col>
    </el-row>
    <el-form-item label="MCC 等级选项">
      <el-input v-model="form.mcc_levels" type="textarea" :rows="3"
        placeholder="每行一个（留空则自由输入）" />
    </el-form-item>

    <el-button type="primary" @click="save" :loading="saving">💾 保存配置</el-button>
    <span v-if="msg" style="margin-left:8px;font-size:11px;color:#059669;">{{ msg }}</span>
  </div>
</template>

<script setup>
import { ref, reactive, onMounted } from 'vue'
import { useAccountStore } from '@/stores/accounts'

const store = useAccountStore()
const saving = ref(false)
const msg = ref('')

const form = reactive({
  account_statuses: '',
  account_agents: '',
  mcc_levels: '',
})

onMounted(async () => {
  if (!store.settings.account_statuses.length) await store.loadSettings()
  form.account_statuses = (store.settings.account_statuses || []).join('\n')
  form.account_agents = (store.settings.account_agents || []).join('\n')
  form.mcc_levels = (store.settings.mcc_levels || []).join('\n')
})

async function save() {
  saving.value = true
  const body = {
    account_statuses: form.account_statuses.split('\n').map(s => s.trim()).filter(Boolean),
    account_agents: form.account_agents.split('\n').map(s => s.trim()).filter(Boolean),
    mcc_levels: form.mcc_levels.split('\n').map(s => s.trim()).filter(Boolean),
  }
  await store.saveSettings(body)
  store.settings = body  // 本地立即更新
  msg.value = '✅ 已保存'
  setTimeout(() => msg.value = '', 2000)
  saving.value = false
}
</script>
```

- [ ] **Step 2: 验证**

```bash
# 确保 Flask 运行中: cd py && python main.py
cd frontend && npx vite
# 打开 http://localhost:5173/#/accounts/settings
# 修改状态 → 保存 → 刷新确认持久化
```

- [ ] **Step 3: Commit**

```bash
git add frontend/src/views/SettingsPanel.vue
git commit -m "feat: 设置子面板 — 账户状态/代理/MCC等级配置"
```

---

## Task 6: 迁移账户管理 — MCC 管理子面板

**Files:** Modify `src/views/MccPanel.vue`, create `src/components/MccModal.vue`, `src/components/MccDetailModal.vue`

- [ ] **Step 1: 实现 MccPanel.vue — 列表 + 筛选 + 分页**

```vue
<template>
  <div>
    <div style="display:flex;gap:8px;margin-bottom:12px;align-items:center;">
      <el-button type="primary" @click="showModal()">➕ 新增 MCC</el-button>
      <span style="color:#888;font-size:12px;">已选 {{ selected.length }} 条</span>
      <el-button @click="batchDelete" :disabled="!selected.length">🗑 批量删除</el-button>
    </div>

    <div style="display:flex;gap:8px;margin-bottom:12px;">
      <el-input v-model="store.mccFilters.search" placeholder="🔍 搜索名称/ID..." @input="search" style="flex:1;" clearable />
      <el-input v-model="store.mccFilters.level" placeholder="等级关键词..." @input="search" style="width:150px;" clearable />
      <el-select v-model="store.mccFilters.parent_filter" @change="search" style="width:130px;" clearable placeholder="全部上级">
        <el-option label="有上级" value="has_parent" />
        <el-option label="顶级节点" value="top" />
      </el-select>
    </div>

    <el-table :data="store.mccList" @selection-change="val => selected = val" stripe size="small">
      <el-table-column type="selection" width="40" />
      <el-table-column prop="name" label="MCC 名称" />
      <el-table-column prop="mcc_id" label="MCC ID" />
      <el-table-column prop="level" label="等级" />
      <el-table-column label="上级 MCC">
        <template #default="{ row }">
          {{ row.parent_mcc_id ? '有上级' : '—（顶级）' }}
        </template>
      </el-table-column>
      <el-table-column prop="direct_count" label="账户数（直属）" width="110" />
      <el-table-column label="操作" width="180">
        <template #default="{ row }">
          <el-button link type="primary" @click="showDetail(row.id)">📋</el-button>
          <el-button link type="primary" @click="showModal(row.id)">✏️</el-button>
          <el-button link type="danger" @click="del(row.id)">🗑</el-button>
        </template>
      </el-table-column>
    </el-table>

    <el-pagination v-if="store.mccTotal > store.mccPageSize"
      v-model:current-page="store.mccPage" :page-size="store.mccPageSize" :total="store.mccTotal"
      layout="prev,pager,next" @current-change="load" style="margin-top:12px;justify-content:center;" />

    <!-- MCC 编辑弹窗 -->
    <MccModal v-model:visible="modalVisible" :edit-id="editId" @saved="load" />
    <!-- MCC 详情弹窗 -->
    <MccDetailModal v-model:visible="detailVisible" :mcc-id="detailId" />
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { useAccountStore } from '@/stores/accounts'
import MccModal from '@/components/MccModal.vue'
import MccDetailModal from '@/components/MccDetailModal.vue'
import { ElMessageBox } from 'element-plus'

const store = useAccountStore()
const selected = ref([])
const modalVisible = ref(false)
const editId = ref(null)
const detailVisible = ref(false)
const detailId = ref(null)
let searchTimer = null

onMounted(() => load())

function load() { store.loadMccList() }

function search() {
  clearTimeout(searchTimer)
  searchTimer = setTimeout(() => { store.mccPage = 1; load() }, 300)
}

function showModal(id) {
  editId.value = id || null
  modalVisible.value = true
}

function showDetail(id) {
  detailId.value = id
  detailVisible.value = true
}

async function del(id) {
  await ElMessageBox.confirm('确定删除此 MCC？', '确认', { type: 'warning' })
  await store.deleteMcc(id)
}

async function batchDelete() {
  await ElMessageBox.confirm(`确定删除选中的 ${selected.value.length} 个 MCC？`, '确认', { type: 'warning' })
  await store.batchDeleteMcc(selected.value.map(s => s.id))
}
</script>
```

- [ ] **Step 2: 实现 MccModal.vue**

```vue
<template>
  <el-dialog :model-value="visible" @update:model-value="$emit('update:visible', $event)"
    :title="editId ? '✏️ 编辑 MCC' : '➕ 新增 MCC'" width="480px" @open="init">
    <el-form label-position="top">
      <el-form-item label="MCC 名称">
        <el-input v-model="form.name" />
      </el-form-item>
      <el-form-item label="MCC ID" :description="editId ? '不可修改' : ''">
        <el-input v-model="form.mcc_id" :disabled="!!editId" />
      </el-form-item>
      <el-form-item label="等级">
        <el-select v-model="form.level" filterable allow-create placeholder="输入或选择">
          <el-option v-for="l in store.settings.mcc_levels" :key="l" :label="l" :value="l" />
        </el-select>
      </el-form-item>
      <el-form-item label="上级 MCC">
        <el-select v-model="form.parent_mcc_id" clearable placeholder="（顶级）">
          <el-option value="" label="（顶级）" />
          <el-option v-for="m in parentOpts" :key="m.id" :label="m.name + ' (' + m.mcc_id + ')'" :value="m.id" />
        </el-select>
      </el-form-item>
    </el-form>
    <template #footer>
      <el-button @click="$emit('update:visible', false)">取消</el-button>
      <el-button type="primary" @click="submit" :loading="saving">💾 保存</el-button>
    </template>
  </el-dialog>
</template>

<script setup>
import { ref, reactive } from 'vue'
import { useAccountStore } from '@/stores/accounts'
import { mccApi } from '@/api/accounts'

const props = defineProps({ visible: Boolean, editId: Number })
const emit = defineEmits(['update:visible', 'saved'])

const store = useAccountStore()
const saving = ref(false)
const parentOpts = ref([])
const form = reactive({ name: '', mcc_id: '', level: '', parent_mcc_id: '' })

async function init() {
  const res = await mccApi.options()
  parentOpts.value = (res.options || []).filter(m => m.id !== props.editId)
  if (props.editId) {
    const mcc = store.mccList.find(m => m.id === props.editId)
    if (mcc) Object.assign(form, { name: mcc.name, mcc_id: mcc.mcc_id, level: mcc.level || '', parent_mcc_id: mcc.parent_mcc_id || '' })
  } else {
    Object.assign(form, { name: '', mcc_id: '', level: '', parent_mcc_id: '' })
  }
}

async function submit() {
  if (!form.name || !form.mcc_id) return
  saving.value = true
  try {
    if (props.editId) {
      await store.updateMcc(props.editId, { name: form.name, level: form.level, parent_mcc_id: form.parent_mcc_id || null })
    } else {
      await store.createMcc(form)
    }
    emit('update:visible', false)
    emit('saved')
  } catch(e) { /* api client 已 toast */ }
  saving.value = false
}
</script>
```

- [ ] **Step 3: 实现 MccDetailModal.vue**

```vue
<template>
  <el-dialog :model-value="visible" @update:model-value="$emit('update:visible', $event)"
    title="📋 MCC 详情" width="700px" @open="load">
    <div v-if="data" style="font-size:13px;">
      <div style="display:flex;gap:8px;margin-bottom:12px;">
        <el-tag type="success">总计 {{ data.total_count }} 个账户</el-tag>
        <el-tag type="primary">直属 {{ data.direct_count }} 个</el-tag>
        <el-tag type="warning">子 MCC 来源 {{ data.total_count - data.direct_count }} 个</el-tag>
      </div>
      <h4>📌 直属账户（{{ data.direct_count }}）</h4>
      <el-table :data="data.direct_accounts" size="small" v-if="data.direct_accounts?.length">
        <el-table-column prop="name" label="账户名称" />
        <el-table-column prop="account_id" label="账户 ID" />
        <el-table-column prop="status" label="状态">
          <template #default="{ row }"><el-tag size="small">{{ row.status }}</el-tag></template>
        </el-table-column>
      </el-table>
      <el-empty v-else description="无直属账户" :image-size="40" />

      <h4 style="margin-top:12px;">📦 子 MCC 贡献（{{ data.total_count - data.direct_count }}）</h4>
      <el-table :data="data.child_mccs" size="small" v-if="data.child_mccs?.length">
        <el-table-column prop="name" label="MCC 名称" />
        <el-table-column prop="mcc_id" label="MCC ID" />
        <el-table-column prop="account_count" label="贡献账户数" />
      </el-table>
      <el-empty v-else description="无子 MCC" :image-size="40" />
    </div>
    <template #footer>
      <el-button @click="$emit('update:visible', false)">关闭</el-button>
    </template>
  </el-dialog>
</template>

<script setup>
import { ref } from 'vue'
import { useAccountStore } from '@/stores/accounts'

const props = defineProps({ visible: Boolean, mccId: Number })
const emit = defineEmits(['update:visible'])
const store = useAccountStore()
const data = ref(null)

async function load() {
  if (props.mccId) data.value = await store.loadMccDetail(props.mccId)
}
</script>
```

- [ ] **Step 4: Commit**

```bash
git add frontend/src/views/MccPanel.vue frontend/src/components/MccModal.vue frontend/src/components/MccDetailModal.vue
git commit -m "feat: MCC 管理面板 — 列表/新增/编辑/详情弹窗"
```

---

## Task 7: 迁移账户管理 — 广告账户子面板

**Files:** Modify `src/views/AdsAccountPanel.vue`, create `src/components/AccountModal.vue`

- [ ] **Step 1: 实现 AdsAccountPanel.vue**

完整移植 `account.js` 中 660-812 行的账户表格逻辑，使用 Element Plus 组件：

```vue
<template>
  <div>
    <div style="display:flex;gap:8px;margin-bottom:12px;align-items:center;">
      <el-button type="primary" @click="showModal()">➕ 新增账户</el-button>
      <span style="color:#888;font-size:12px;">已选 {{ selected.length }} 条</span>
      <el-button @click="batchDelete" :disabled="!selected.length">🗑 批量删除</el-button>
      <el-select v-model="batchStatus" @change="doBatchStatus" placeholder="批量修改状态..."
        style="width:160px;" :disabled="!selected.length" clearable>
        <el-option v-for="s in store.settings.account_statuses" :key="s" :label="s" :value="s" />
      </el-select>
    </div>

    <div style="display:flex;gap:8px;margin-bottom:12px;">
      <el-input v-model="store.acFilters.search" placeholder="🔍 搜索名称/ID..." @input="search" style="flex:1;" clearable />
      <el-select v-model="store.acFilters.status" @change="searchAndLoad" placeholder="全部状态" style="width:120px;" clearable>
        <el-option v-for="s in store.settings.account_statuses" :key="s" :label="s" :value="s" />
      </el-select>
      <el-select v-model="store.acFilters.mcc_id" @change="searchAndLoad" placeholder="全部 MCC" style="width:160px;" clearable>
        <el-option v-for="m in mccOptions" :key="m.id" :label="m.name + ' (' + m.mcc_id + ')'" :value="m.id" />
      </el-select>
      <el-select v-model="store.acFilters.agent" @change="searchAndLoad" placeholder="全部代理" style="width:120px;" clearable>
        <el-option v-for="a in agentOptions" :key="a" :label="a" :value="a" />
      </el-select>
    </div>

    <el-table :data="store.accounts" @selection-change="val => selected = val" stripe size="small">
      <el-table-column type="selection" width="40" />
      <el-table-column prop="name" label="账号名称" />
      <el-table-column prop="account_id" label="账号 ID" />
      <el-table-column label="所属 MCC">
        <template #default="{ row }">
          <template v-if="row.mcc_name">
            <span style="color:#0891b2;">{{ row.mcc_name }}</span><br/>
            <span style="font-size:10px;color:#888;">{{ row.mcc_code }}</span>
          </template>
          <span v-else style="color:#888;">未分配</span>
        </template>
      </el-table-column>
      <el-table-column prop="timezone" label="时区" />
      <el-table-column prop="agent" label="代理" />
      <el-table-column prop="status" label="状态">
        <template #default="{ row }"><el-tag size="small">{{ row.status }}</el-tag></template>
      </el-table-column>
      <el-table-column prop="acquired_date" label="到手时间" />
      <el-table-column label="操作" width="120">
        <template #default="{ row }">
          <el-button link type="primary" @click="showModal(row.id)">✏️</el-button>
          <el-button link type="danger" @click="del(row.id)">🗑</el-button>
        </template>
      </el-table-column>
    </el-table>

    <el-pagination v-if="store.acTotal > store.acPageSize"
      v-model:current-page="store.acPage" :page-size="store.acPageSize" :total="store.acTotal"
      layout="prev,pager,next" @current-change="load" style="margin-top:12px;justify-content:center;" />

    <AccountModal v-model:visible="acModalVisible" :edit-id="acEditId" @saved="load" />
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { useAccountStore } from '@/stores/accounts'
import AccountModal from '@/components/AccountModal.vue'
import { ElMessageBox } from 'element-plus'

const store = useAccountStore()
const selected = ref([])
const acModalVisible = ref(false)
const acEditId = ref(null)
const batchStatus = ref('')
const mccOptions = ref([])
const agentOptions = ref([])
let searchTimer = null

onMounted(async () => {
  if (!store.settings.account_statuses.length) await store.loadSettings()
  await load()
})

async function load() {
  const res = await store.loadAccounts()
  mccOptions.value = res.mcc_options || []
  // 合并已配置代理 + 数据中的代理
  const set = new Set([...store.settings.account_agents, ...(res.agents || [])])
  agentOptions.value = [...set].filter(Boolean).sort()
}

function search() {
  clearTimeout(searchTimer)
  searchTimer = setTimeout(() => { store.acPage = 1; load() }, 300)
}

function searchAndLoad() { store.acPage = 1; load() }

function showModal(id) {
  acEditId.value = id || null
  acModalVisible.value = true
}

async function del(id) {
  await ElMessageBox.confirm('确定删除此账户？', '确认', { type: 'warning' })
  await store.deleteAccount(id)
}

async function batchDelete() {
  await ElMessageBox.confirm(`确定删除选中的 ${selected.value.length} 个账户？`, '确认', { type: 'warning' })
  await store.batchDeleteAccounts(selected.value.map(s => s.id))
}

async function doBatchStatus(val) {
  if (!val) return
  await store.batchUpdateAccounts({ ids: selected.value.map(s => s.id), field: 'status', value: val })
  batchStatus.value = ''
}
</script>
```

- [ ] **Step 2: 实现 AccountModal.vue**

```vue
<template>
  <el-dialog :model-value="visible" @update:model-value="$emit('update:visible', $event)"
    :title="editId ? '✏️ 编辑账户' : '➕ 新增账户'" width="500px" @open="init">
    <el-form label-position="top">
      <el-form-item label="账号名称">
        <el-input v-model="form.name" />
      </el-form-item>
      <el-form-item label="账号 ID" :description="editId ? '不可修改' : ''">
        <el-input v-model="form.account_id" :disabled="!!editId" />
      </el-form-item>
      <el-form-item label="所属 MCC">
        <el-select v-model="form.mcc_id" clearable placeholder="（未分配）" style="width:100%;">
          <el-option v-for="m in mccOptions" :key="m.id" :label="m.name + ' (' + m.mcc_id + ')'" :value="m.id" />
        </el-select>
      </el-form-item>
      <el-form-item label="时区">
        <el-input v-model="form.timezone" />
      </el-form-item>
      <el-form-item label="代理">
        <el-select v-model="form.agent" filterable allow-create placeholder="输入或选择" style="width:100%;">
          <el-option v-for="a in store.settings.account_agents" :key="a" :label="a" :value="a" />
        </el-select>
      </el-form-item>
      <el-form-item label="状态" required>
        <el-select v-model="form.status" style="width:100%;">
          <el-option v-for="s in store.settings.account_statuses" :key="s" :label="s" :value="s" />
        </el-select>
      </el-form-item>
      <el-form-item label="到手时间">
        <el-date-picker v-model="form.acquired_date" type="date" style="width:100%;"
          value-format="YYYY-MM-DD" />
      </el-form-item>
    </el-form>
    <template #footer>
      <el-button @click="$emit('update:visible', false)">取消</el-button>
      <el-button type="primary" @click="submit" :loading="saving">💾 保存</el-button>
    </template>
  </el-dialog>
</template>

<script setup>
import { ref, reactive } from 'vue'
import { useAccountStore } from '@/stores/accounts'
import { mccApi } from '@/api/accounts'

const props = defineProps({ visible: Boolean, editId: Number })
const emit = defineEmits(['update:visible', 'saved'])
const store = useAccountStore()
const saving = ref(false)
const mccOptions = ref([])
const form = reactive({ name: '', account_id: '', mcc_id: '', timezone: '', agent: '', status: '存活', acquired_date: '' })

async function init() {
  const res = await mccApi.options()
  mccOptions.value = res.options || []
  if (props.editId) {
    const a = store.accounts.find(a => a.id === props.editId)
    if (a) Object.assign(form, {
      name: a.name, account_id: a.account_id, mcc_id: a.mcc_id || '',
      timezone: a.timezone || '', agent: a.agent || '', status: a.status || '存活',
      acquired_date: a.acquired_date || '',
    })
  } else {
    Object.assign(form, { name: '', account_id: '', mcc_id: '', timezone: '', agent: '', status: '存活', acquired_date: new Date().toISOString().split('T')[0] })
  }
}

async function submit() {
  if (!form.name || !form.account_id || !form.agent) { alert('账号名称、ID 和代理不能为空'); return }
  saving.value = true
  try {
    if (props.editId) {
      await store.updateAccount(props.editId, form)
    } else {
      await store.createAccount(form)
    }
    // 自动保存新代理名到设置
    const agents = store.settings.account_agents || []
    if (form.agent && !agents.includes(form.agent)) {
      agents.push(form.agent)
      await store.saveSettings({ account_agents: agents })
      store.settings.account_agents = agents
    }
    emit('update:visible', false)
    emit('saved')
  } catch(e) {}
  saving.value = false
}
</script>
```

- [ ] **Step 3: Commit**

```bash
git add frontend/src/views/AdsAccountPanel.vue frontend/src/components/AccountModal.vue
git commit -m "feat: 广告账户面板 — 表格/筛选/新增/编辑/批量操作"
```

---

## Task 8: 迁移账户管理 — 产品管理子面板

**Files:** Modify `src/views/ProductPanel.vue`, create `src/components/ProductCard.vue`, `src/components/ProductModal.vue`, `src/components/ProductDetailModal.vue`, `src/components/CopyImportModal.vue`, `src/components/AddPackageModal.vue`, `src/components/PackageRow.vue`

这是最大的面板，移植 `account.js` 中 17-656 行的全部产品 + 包逻辑。

- [ ] **Step 1: 实现 ProductPanel.vue**（工具栏 + 产品卡片列表 + 分页）

```vue
<template>
  <div>
    <!-- 工具栏 -->
    <div style="display:flex;gap:10px;margin-bottom:16px;flex-wrap:wrap;align-items:center;">
      <el-button type="primary" @click="showProductModal()">➕ 新增产品</el-button>
      <el-button @click="copyVisible = true">📋 复制导入</el-button>
      <el-select v-model="store.filters.region" @change="load" placeholder="全部地区" clearable style="width:120px;">
        <el-option v-for="r in regions" :key="r" :label="r" :value="r" />
      </el-select>
      <el-select v-model="store.filters.mcc_id" @change="load" placeholder="全部 MCC" clearable style="width:180px;">
        <el-option v-for="m in mccOptions" :key="m.id" :label="m.name + ' (' + m.mcc_id + ')'" :value="m.id" />
      </el-select>
      <el-input v-model="store.filters.search" placeholder="搜索产品或 KPI..." @input="search" style="flex:1;min-width:160px;" clearable />
      <el-radio-group v-model="store.pausedMode" @change="load" size="small">
        <el-radio-button :value="false">正常</el-radio-button>
        <el-radio-button :value="true">已暂停</el-radio-button>
      </el-radio-group>
    </div>

    <!-- 产品卡片列表 -->
    <ProductCard
      v-for="p in store.products" :key="p.id"
      :product="p"
      @edit="showProductModal($event)"
      @detail="showDetail($event)"
      @add-pkg="showAddPkg($event)"
      @del="delProduct($event)"
      @toggle-pause="togglePause($event)"
      @refresh="load"
    />

    <el-empty v-if="!store.products.length" description="暂无产品" />

    <!-- 分页 -->
    <el-pagination v-if="store.total > store.pageSize"
      v-model:current-page="store.page" :page-size="store.pageSize" :total="store.total"
      layout="prev,pager,next" @current-change="load" style="margin-top:12px;justify-content:center;" />

    <!-- 弹窗 -->
    <ProductModal v-model:visible="pmVisible" :edit-id="pmEditId" :mcc-options="mccOptions" @saved="load" />
    <ProductDetailModal v-model:visible="detailVisible" :prod-id="detailId" />
    <CopyImportModal v-model:visible="copyVisible" @saved="load" />
    <AddPackageModal v-model:visible="addPkgVisible" :prod-id="addPkgProdId" @saved="load" />
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { useProductStore } from '@/stores/products'
import { useAccountStore } from '@/stores/accounts'
import { mccApi } from '@/api/accounts'
import ProductCard from '@/components/ProductCard.vue'
import ProductModal from '@/components/ProductModal.vue'
import ProductDetailModal from '@/components/ProductDetailModal.vue'
import CopyImportModal from '@/components/CopyImportModal.vue'
import AddPackageModal from '@/components/AddPackageModal.vue'
import { ElMessageBox } from 'element-plus'

const store = useProductStore()
const acStore = useAccountStore()
const regions = ref([])
const mccOptions = ref([])

const pmVisible = ref(false); const pmEditId = ref(null)
const detailVisible = ref(false); const detailId = ref(null)
const copyVisible = ref(false)
const addPkgVisible = ref(false); const addPkgProdId = ref(null)

let searchTimer = null

onMounted(async () => {
  const res = await store.loadProducts()
  regions.value = res.regions || []
  mccOptions.value = res.mcc_options || []
})

function load() { store.loadProducts().then(r => { regions.value = r.regions || []; mccOptions.value = r.mcc_options || [] }) }
function search() { clearTimeout(searchTimer); searchTimer = setTimeout(() => { store.page = 1; load() }, 300) }
function showProductModal(id) { pmEditId.value = id || null; pmVisible.value = true }
function showDetail(id) { detailId.value = id; detailVisible.value = true }
function showAddPkg(id) { addPkgProdId.value = id; addPkgVisible.value = true }
async function delProduct(id) { await ElMessageBox.confirm('确定删除此产品及所有包？','确认',{type:'warning'}); await store.deleteProduct(id) }
async function togglePause({id, paused}) { await store.updateProduct(id, { status: paused ? 'paused' : '' }); load() }
</script>
```

- [ ] **Step 2: 实现 ProductCard.vue**（可展开卡片 + 包列表）

由于篇幅限制，核心结构：
- `<el-card>` 作为产品卡片，header 显示产品名/KPI/地区/MCC/badge
- 可展开区域（v-show）显示 PackageRow 列表
- 操作按钮：暂停/编辑/加包/删除
- 包批量操作栏

- [ ] **Step 3: 实现 PackageRow.vue**

- [ ] **Step 4: 实现 ProductModal.vue, ProductDetailModal.vue, CopyImportModal.vue, AddPackageModal.vue**

（完整 Vue 代码迁移自 account.js 中对应函数，使用 Element Plus 对话框 + 表单）

- [ ] **Step 5: Commit**

```bash
git add frontend/src/views/ProductPanel.vue frontend/src/components/Product{Card,Modal,DetailModal}.vue frontend/src/components/{CopyImportModal,AddPackageModal,PackageRow}.vue
git commit -m "feat: 产品管理面板 — 产品列表/包管理/复制导入/详情弹窗"
```

---

## Task 9: 迁移 YouTube 视频管理

**Files:** Modify `src/views/YoutubeView.vue`, create `src/components/YoutubeVideoItem.vue`

- [ ] **Step 1: 实现 YoutubeView.vue**

移植 `youtube.js` 全部逻辑（视频展示 + 导入 + 标签配置），使用 `<el-tabs>` 替代手写子标签切换：

三栏布局：左侧视频列表 + 右侧播放器
- 筛选：地区/帧类型/成效/产品名 下拉
- 操作：搜索/全选/反选/批量修改/复制链接/批量删除
- 分页 + 每页条数选择
- 导入子标签：textarea + 属性设置 + 保存
- 标签配置子标签：4 个 textarea + 保存

- [ ] **Step 2: 验证 YouTube 面板与后端联调**

```bash
# Flask 运行中
cd frontend && npx vite
# /#/youtube/view — 视频列表加载
# /#/youtube/import — 导入
# /#/youtube/config — 标签配置
```

- [ ] **Step 3: Commit**

```bash
git add frontend/src/views/YoutubeView.vue frontend/src/components/YoutubeVideoItem.vue
git commit -m "feat: YouTube 视频管理面板"
```

---

## Task 10: 迁移图片爬取

**Files:** Modify `src/views/ScrapeView.vue`

- [ ] **Step 1: 实现 ScrapeView.vue**

移植 `app.js` 中爬取逻辑：
- URL 多行输入框
- 保存路径 + 📂 文件夹选择按钮
- "按 Google Ads 规格放大" 复选框
- "开始爬取" 按钮
- 结果列表（逐条显示状态）+ 汇总

- [ ] **Step 2: Commit**

```bash
git add frontend/src/views/ScrapeView.vue
git commit -m "feat: 图片爬取面板"
```

---

## Task 11: 迁移 AI 视频生成 + 工具集

**Files:** Modify `src/views/VideoView.vue`, `src/views/ToolkitView.vue`

- [ ] **Step 1: 实现 VideoView.vue**

移植 `video.js` 全部逻辑：
- 选择目录 → 扫描图片 → 缩略图网格 → 勾选
- Logo 叠加设置 / AI 动态化设置
- 视频参数（背景/缩放/帧长/转场/分辨率/音乐/文案/字体）
- 任务队列 + 一键生成
- 历史设置侧边栏

- [ ] **Step 2: 实现 ToolkitView.vue**

- 子标签 1 — 做表数据：文本输入 → 解析 → 三种视图表格 + 复制 + 导出 Excel
- 子标签 2 — 音频替换：原视频/音频源 文件选择 + 替换按钮

- [ ] **Step 3: Commit**

```bash
git add frontend/src/views/VideoView.vue frontend/src/views/ToolkitView.vue
git commit -m "feat: AI 视频生成面板 + 工具集面板"
```

---

## Task 12: 更新 AccountsView.vue 容器

**Files:** Modify `src/views/AccountsView.vue`

- [ ] **Step 1: 添加子标签导航**

```vue
<template>
  <div>
    <h1>🏢 账户管理</h1>
    <el-tabs :model-value="activeTab" @update:model-value="switchTab">
      <el-tab-pane label="📦 产品管理" name="products" />
      <el-tab-pane label="👤 广告账户" name="ads" />
      <el-tab-pane label="🏢 MCC 管理" name="mcc" />
      <el-tab-pane label="⚙ 设置" name="settings" />
    </el-tabs>
    <router-view />
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { useRouter, useRoute } from 'vue-router'

const router = useRouter()
const route = useRoute()
const activeTab = computed(() => {
  const p = route.path
  if (p.includes('/settings')) return 'settings'
  if (p.includes('/mcc')) return 'mcc'
  if (p.includes('/ads')) return 'ads'
  return 'products'
})

function switchTab(name) {
  router.push(`/accounts/${name}`)
}
</script>
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/views/AccountsView.vue
git commit -m "feat: 账户管理容器 — el-tabs 子标签导航"
```

---

## Task 13: 清理旧前端文件 + 适配 main.py

**Files:** Delete `index.html`, `js/`, `css/`; modify `py/main.py`

- [ ] **Step 1: 适配 main.py 支持双模式（开发/生产）**

在 `py/main.py` 中修改 `static_folder` 和 `index` 路由：

```python
# 静态文件：生产模式用 dist/，开发模式 Vite 独立运行
if _FROZEN:
    _FRONTEND_DIR = os.path.join(sys._MEIPASS, "dist")
else:
    # 开发模式：如果 frontend/dist/ 存在则用它，否则回退旧目录
    _dist = os.path.join(_DATA_ROOT, "frontend", "dist")
    if os.path.isdir(_dist):
        _FRONTEND_DIR = _dist
    else:
        _FRONTEND_DIR = os.path.dirname(_current_dir)  # 回退

app = Flask(__name__, static_folder=_FRONTEND_DIR, static_url_path="")
```

- [ ] **Step 2: 删除旧前端文件**

```bash
rm -rf js/ css/ index.html google-ads.html
```

注意：`google-ads.html` 暂保留（独立页面，后续纳入 Vue）。

- [ ] **Step 3: 验证生产构建**

```bash
cd frontend && npm run build
# 输出在 dist/ 目录
cd ../py && python main.py
# 浏览器打开 http://localhost:5000，应看到完整 Vue 应用
```

- [ ] **Step 4: Commit**

```bash
git add py/main.py
git rm -r js/ css/ index.html
git add frontend/dist/ -f  # 提交构建产物用于打包
git commit -m "chore: 清理旧前端文件，适配 main.py 双模式"
```

---

## Task 14: 最终验证

- [ ] **Step 1: 开发模式联调**

```bash
# 终端 1
cd py && python main.py
# 终端 2
cd frontend && npx vite
# 浏览器打开 http://localhost:5173
```

逐一验证所有面板功能：爬取、视频生成、YouTube CRUD、产品 CRUD、账户 CRUD、MCC CRUD、设置配置、工具集。

- [ ] **Step 2: 生产模式验证**

```bash
cd frontend && npm run build
cd ../py && python main.py
# http://localhost:5000 — 确认无 404
```

- [ ] **Step 3: PyInstaller 打包验证（可选）**

```bash
pyinstaller --onefile --clean --name "gp-image-scraper" \
  --paths py \
  --add-data "frontend/dist;dist" \
  py/main.py
# 运行 EXE 验证
```

- [ ] **Step 4: Commit**

```bash
git commit -am "chore: 最终验证通过"
```

---

## 验证清单

- [ ] 爬取：输入 URL → 爬取 → 图片保存 → 结果展示
- [ ] 视频：扫描目录 → 勾选图片 → 生成视频
- [ ] YouTube：导入链接 → 列表筛选 → 播放 → 编辑 → 删除
- [ ] 产品：新增 → 加包 → 编辑 → 暂停 → 复制导入 → 详情弹窗
- [ ] 账户：新增 → 编辑 → 状态筛选 → 代理下拉 → 批量操作
- [ ] MCC：新增 → 树形层级 → 详情弹窗 → 递归统计
- [ ] 设置：修改状态/代理/等级 → 保存 → 下拉同步
- [ ] 工具集：做表解析 → 复制 → 导出 Excel → 音频替换
- [ ] 路由：浏览器前进/后退 → URL 正确
- [ ] 打包：npm run build → Flask 提供 dist/ → 正常访问
