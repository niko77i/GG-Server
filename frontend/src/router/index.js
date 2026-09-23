import { createRouter, createWebHashHistory } from 'vue-router'
import { useAuthStore } from '../stores/auth'

const routes = [
  {
    path: '/login',
    component: () => import('../views/LoginView.vue'),
    meta: { guest: true, title: '登录' }
  },
  {
    path: '/register',
    component: () => import('../views/RegisterView.vue'),
    meta: { guest: true, title: '注册' }
  },
  {
    path: '/',
    redirect: () => {
      const token = localStorage.getItem('token')
      if (!token) return '/login'
      const user = JSON.parse(localStorage.getItem('user') || '{}')
      if (user.role === 'huguan') {
        // 户管跨平台，以 GG 账户页为默认落地，随后可在侧边栏切换平台
        return '/accounts/ads'
      }
      if (user.platform === 'fb') return '/fb/products'
      if (user.platform === 'tt') return '/tt/products'
      return '/accounts/products'
    }
  },
  {
    path: '/accounts',
    component: () => import('../views/AccountsView.vue'),
    redirect: () => {
      const user = JSON.parse(localStorage.getItem('user') || '{}')
      return (user.role === 'huguan') ? '/accounts/ads' : '/accounts/products'
    },
    meta: { platform: 'gg' },
    children: [
      { path: 'products', component: () => import('../views/ProductPanel.vue'), meta: { title: '产品管理' } },
      { path: 'ads', component: () => import('../views/AdsAccountPanel.vue'), meta: { admin: true, title: '广告账户' } },
      { path: 'mcc', component: () => import('../views/MccPanel.vue'), meta: { admin: true, title: 'MCC 管理' } },
      { path: 'settings', component: () => import('../views/SettingsPanel.vue'), meta: { admin: true, title: '设置' } },

    ]
  },
  {
    path: '/youtube',
    component: () => import('../views/YoutubeView.vue'),
    redirect: '/youtube/view',
    meta: { platform: 'gg' },
    children: [
      { path: 'view', component: () => import('../views/YoutubeView.vue'), meta: { title: '视频展示' } },
      { path: 'copywriting', component: () => import('../views/YoutubeView.vue'), meta: { title: '文案展示' } },
      { path: 'import', component: () => import('../views/YoutubeView.vue'), meta: { title: '导入视频或文案' } },
      { path: 'config', component: () => import('../views/YoutubeView.vue'), meta: { title: '标签配置' } },
    ]
  },
  { path: '/media', component: () => import('../views/MediaView.vue'), meta: { title: '媒体工具', platform: 'gg' } },
  {
    path: '/toolkit',
    component: () => import('../views/ToolkitView.vue'),
    redirect: '/toolkit/zuobiao',
    children: [
      { path: 'zuobiao', component: () => import('../views/ToolkitView.vue'), meta: { title: '做表数据' } },
      { path: 'audio', component: () => import('../views/ToolkitView.vue'), meta: { title: '音频替换' } },
      { path: 'translate', component: () => import('../views/ToolkitView.vue'), meta: { title: '翻译工具' } },
    ]
  },
  {
    path: '/analysis',
    component: () => import('../views/AnalysisView.vue'),
    meta: { title: '数据分析' }
  },
  {
    path: '/data-manage',
    component: () => import('../views/DataManageView.vue'),
    meta: { title: '数据管理', platform: 'gg' }
  },
  {
    path: '/admin/users',
    component: () => import('../views/UserManageView.vue'),
    meta: { admin: true, title: '用户管理' }
  },
  {
    path: '/admin/scheduler',
    component: () => import('../views/SchedulerView.vue'),
    meta: { developer: true, title: '定时任务' }
  },
  {
    path: '/profile',
    component: () => import('../views/UserProfileView.vue'),
    meta: { title: '个人信息' }
  },
  // ==================== FB 平台路由 ====================
  {
    path: '/fb',
    redirect: () => {
      const user = JSON.parse(localStorage.getItem('user') || '{}')
      return (user.role === 'huguan') ? '/fb/accounts' : '/fb/products'
    },
    meta: { platform: 'fb' }
  },
  {
    path: '/fb/products',
    component: () => import('../views/fb/FbProductPanel.vue'),
    meta: { platform: 'fb', title: 'FB产品管理' }
  },
  {
    path: '/fb/accounts',
    component: () => import('../views/fb/FbAccountPanel.vue'),
    meta: { platform: 'fb', title: 'FB账户管理' }
  },
  {
    path: '/fb/bms',
    component: () => import('../views/fb/FbBmPanel.vue'),
    meta: { platform: 'fb', title: 'BM管理' }
  },
  {
    path: '/fb/pixels',
    component: () => import('../views/fb/FbPixelPanel.vue'),
    meta: { platform: 'fb', title: '像素管理' }
  },
  {
    path: '/fb/extract',
    component: () => import('../views/fb/FbDataExtract.vue'),
    meta: { platform: 'fb', title: 'FB数据提取' }
  },
  {
    path: '/fb/data-manage',
    component: () => import('../views/fb/FbDataManage.vue'),
    meta: { platform: 'fb', title: 'FB数据管理' }
  },
  {
    path: '/fb/settings',
    component: () => import('../views/fb/FbSettingsPanel.vue'),
    meta: { platform: 'fb', title: 'FB设置' }
  },
  // ==================== TT 平台路由 ====================
  {
    path: '/tt',
    component: () => import('../views/tt/TtView.vue'),
    redirect: () => {
      const user = JSON.parse(localStorage.getItem('user') || '{}')
      return (user.role === 'huguan') ? '/tt/accounts' : '/tt/products'
    },
    meta: { platform: 'tt' },
    children: [
      { path: 'products', component: () => import('../views/tt/TtProductPanel.vue'), meta: { title: 'TT产品管理' } },
      { path: 'bcs', component: () => import('../views/tt/TtBcPanel.vue'), meta: { title: 'BC管理' } },
      { path: 'accounts', component: () => import('../views/tt/TtAccountPanel.vue'), meta: { title: 'TT广告账户' } },
      { path: 'settings', component: () => import('../views/tt/TtSettingsPanel.vue'), meta: { title: 'TT设置' } },
    ]
  },
  {
    path: '/tt/extract',
    component: () => import('../views/tt/TtDataExtract.vue'),
    meta: { platform: 'tt', title: 'TT数据提取' },
  },
]

const router = createRouter({
  history: createWebHashHistory(),
  routes,
})

router.beforeEach((to, from, next) => {
  const auth = useAuthStore()
  if (to.meta.guest) {
    next()
    return
  }
  if (!auth.isLoggedIn) {
    next('/login?redirect=' + encodeURIComponent(to.fullPath))
    return
  }
  // 当前身份与平台的默认落地页
  const platformHome = auth.homePath

  // 户管可进入的带 meta.admin 的账户区/用户管理路由
  const HUGUAN_ROUTES = [
    '/accounts/ads', '/accounts/mcc', '/accounts/settings',
    '/fb/accounts', '/fb/bms', '/fb/pixels', '/fb/settings',
    '/tt/accounts', '/tt/bcs', '/tt/settings',
    '/admin/users',
  ]
  const isHuguanAllowedRoute = (p) =>
    HUGUAN_ROUTES.some(r => p === r || p.startsWith(r + '/'))

  // 平台守卫
  if (to.meta.platform && !auth.canSwitchPlatform) {
    if (to.meta.platform !== auth.effectivePlatform) {
      next(platformHome)
      return
    }
  }
  if (to.meta.admin && !auth.isAdmin && !(auth.isHuguan && isHuguanAllowedRoute(to.path))) {
    next(platformHome)
    return
  }
  if (to.meta.developer && !auth.isDeveloper) {
    next(platformHome)
    return
  }
  // viewer 只能访问 /accounts/products，不能访问其他账户子页面
  if (auth.isViewer && to.path.startsWith('/accounts') && to.path !== '/accounts/products' && !to.path.startsWith('/accounts/products/')) {
    next('/accounts/products')
    return
  }
  // 户管不进产品页：无对应 Tab，后端对产品域也 403
  if (auth.isHuguan && (to.path === '/accounts/products' || to.path.startsWith('/accounts/products/'))) {
    next('/accounts/ads')
    return
  }
  if (auth.isHuguan && (to.path === '/fb/products' || to.path.startsWith('/fb/products/'))) {
    next('/fb/accounts')
    return
  }
  if (auth.isHuguan && (to.path === '/tt/products' || to.path.startsWith('/tt/products/'))) {
    next('/tt/accounts')
    return
  }
  if (auth.isHuguan && (to.path === '/fb/extract' || to.path.startsWith('/fb/extract/'))) {
    next('/fb/accounts')
    return
  }
  if (auth.isHuguan && (to.path === '/fb/data-manage' || to.path.startsWith('/fb/data-manage/'))) {
    next('/fb/accounts')
    return
  }
  if (auth.isHuguan && (to.path === '/tt/extract' || to.path.startsWith('/tt/extract/'))) {
    next('/tt/accounts')
    return
  }
  // 户管不进 YouTube 素材域：后端 /api/youtube/* 16 条已全部对户管 403
  if (auth.isHuguan && (to.path === '/youtube' || to.path.startsWith('/youtube/'))) {
    next('/accounts/ads')
    return
  }
  // 户管不进媒体工具（视频域 / 音频域）：后端 /api/video/*、/api/audio* 已对户管 403
  if (auth.isHuguan && (to.path === '/media' || to.path.startsWith('/media/'))) {
    next('/accounts/ads')
    return
  }
  // 户管不进音频替换入口（仅此子页；/toolkit/zuobiao 按裁定放行）
  if (auth.isHuguan && (to.path === '/toolkit/audio' || to.path.startsWith('/toolkit/audio/'))) {
    next('/accounts/ads')
    return
  }
  next()
})

export default router
