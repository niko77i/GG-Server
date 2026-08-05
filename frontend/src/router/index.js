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
      return user.platform === 'fb' ? '/fb/products' : '/accounts/products'
    }
  },
  {
    path: '/accounts',
    component: () => import('../views/AccountsView.vue'),
    redirect: '/accounts/products',
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
    redirect: '/fb/products',
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
  // 根据用户平台获取首页
  const userPlatform = auth.user?.platform || 'gg'
  const platformHome = userPlatform === 'fb' ? '/fb/products' : '/accounts/products'

  // 平台守卫
  if (to.meta.platform && !auth.isDeveloper) {
    if (to.meta.platform !== userPlatform) {
      next(platformHome)
      return
    }
  }
  if (to.meta.admin && !auth.isAdmin) {
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
  next()
})

export default router
