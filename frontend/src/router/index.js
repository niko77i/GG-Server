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
    redirect: '/youtube'
  },
  {
    path: '/accounts',
    component: () => import('../views/AccountsView.vue'),
    redirect: '/accounts/products',
    meta: { admin: true },
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
      { path: 'copywriting', component: () => import('../views/YoutubeView.vue'), meta: { title: '文案展示' } },
      { path: 'import', component: () => import('../views/YoutubeView.vue'), meta: { title: '导入视频或文案' } },
      { path: 'config', component: () => import('../views/YoutubeView.vue'), meta: { title: '标签配置' } },
    ]
  },
  { path: '/media', component: () => import('../views/MediaView.vue'), meta: { title: '媒体工具' } },
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
    path: '/admin/users',
    component: () => import('../views/UserManageView.vue'),
    meta: { admin: true, title: '用户管理' }
  },
  {
    path: '/profile',
    component: () => import('../views/UserProfileView.vue'),
    meta: { title: '个人信息' }
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
  if (to.meta.admin && !auth.isAdmin) {
    next('/youtube')
    return
  }
  if (!auth.isLoggedIn) {
    next('/login?redirect=' + encodeURIComponent(to.fullPath))
    return
  }
  next()
})

export default router
