import { defineStore } from 'pinia'
import { authApi } from '../api/auth'

export const useAuthStore = defineStore('auth', {
  state: () => ({
    user: null,
    token: localStorage.getItem('token') || '',
    isLoggedIn: !!localStorage.getItem('token')
  }),
  getters: {
    isAdmin: (state) => ['developer', 'admin'].includes(state.user?.role),
    isDeveloper: (state) => state.user?.role === 'developer',
    roleLabel: (state) => {
      const labels = { developer: '开发者', admin: '管理员', user: '用户', hidden: '已禁用' }
      return labels[state.user?.role] || state.user?.role || ''
    }
  },
  actions: {
    async login(username, password) {
      const res = await authApi.login(username, password)
      this.token = res.access_token
      this.user = res.user
      this.isLoggedIn = true
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
    logout() {
      this.user = null
      this.token = ''
      this.isLoggedIn = false
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
