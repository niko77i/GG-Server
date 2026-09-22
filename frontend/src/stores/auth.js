import { defineStore } from 'pinia'
import { authApi } from '../api/auth'

export const useAuthStore = defineStore('auth', {
  state: () => ({
    user: null,
    token: localStorage.getItem('token') || '',
    isLoggedIn: !!localStorage.getItem('token'),
    currentPlatform: 'gg'  // developer 可切换，普通用户登录后根据 user.platform 设置
  }),
  getters: {
    isAdmin: (state) => ['developer', 'admin'].includes(state.user?.role),
    isDeveloper: (state) => state.user?.role === 'developer',
    isViewer: (state) => state.user?.role === 'viewer',
    isHuguan: (state) => state.user?.role === 'huguan',
    canSwitchPlatform: (state) => ['developer', 'huguan'].includes(state.user?.role),
    canManageAccounts: (state) => ['developer', 'admin', 'huguan'].includes(state.user?.role),
    canAccessProducts: (state) => ['developer', 'admin', 'viewer', 'user'].includes(state.user?.role),
    isFbUser: (state) => state.currentPlatform === 'fb',
    isGgUser: (state) => state.currentPlatform === 'gg',
    isTtUser: (state) => state.currentPlatform === 'tt',
    effectivePlatform: (state) => {
      if (state.canSwitchPlatform) return state.currentPlatform
      return state.user?.platform || 'gg'
    },
    homePath: (state) => {
      const p = state.effectivePlatform
      if (state.canSwitchPlatform) {
        // 户管与开发者可跨平台，落地账户页而非产品页
        return p === 'fb' ? '/fb/accounts' : p === 'tt' ? '/tt/accounts' : '/accounts/ads'
      }
      return p === 'fb' ? '/fb/products' : p === 'tt' ? '/tt/products' : '/accounts/products'
    },
    roleLabel: (state) => {
      const labels = { developer: '开发者', admin: '管理员', viewer: '观察者', user: '用户', hidden: '已禁用', huguan: '户管' }
      return labels[state.user?.role] || state.user?.role || ''
    }
  },
  actions: {
    async login(username, password) {
      const res = await authApi.login(username, password)
      this.token = res.access_token
      this.user = res.user
      this.isLoggedIn = true
      // 设置当前平台
      if (this.canSwitchPlatform) {
        this.currentPlatform = 'gg' // developer 默认进 GG
      } else {
        this.currentPlatform = res.user?.platform || 'gg'
      }
      localStorage.setItem('token', res.access_token)
      localStorage.setItem('user', JSON.stringify(res.user))
      return res
    },
    async register(username, password, display_name) {
      const res = await authApi.register(username, password, display_name)
      return res
    },
    async fetchMe() {
      try {
        const res = await authApi.me()
        this.user = res.user
        localStorage.setItem('user', JSON.stringify(res.user))
        return res.user
      } catch (e) {
        this.logout()
        return null
      }
    },
    setPlatform(platform) {
      if (this.canSwitchPlatform) {
        this.currentPlatform = platform
      }
    },
    logout() {
      this.user = null
      this.token = ''
      this.isLoggedIn = false
      this.currentPlatform = 'gg'
      localStorage.removeItem('token')
      localStorage.removeItem('user')
    },
    initFromStorage() {
      const token = localStorage.getItem('token')
      const user = localStorage.getItem('user')
      if (token && user) {
        this.token = token
        this.user = JSON.parse(user)
        this.isLoggedIn = true
      }
    }
  }
})
