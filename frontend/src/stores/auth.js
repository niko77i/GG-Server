import { defineStore } from 'pinia'
import { authApi } from '../api/auth'
import { PLATFORM_KEY, sanitizePlatform, platformFamily, resolvePlatform } from '../utils/platformPrefs.mjs'

export const useAuthStore = defineStore('auth', {
  state: () => ({
    user: null,
    token: localStorage.getItem('token') || '',
    isLoggedIn: !!localStorage.getItem('token'),
    // 平台上下文**必须持久化**。它原先只活在内存里（初始值硬编码 'gg'、setPlatform 不落盘、
    // initFromStorage 不恢复）⇒ 整页刷新后，**可切换平台的角色（户管/开发者）会静默掉回 GG**，
    // 而页面还停在刷新前那张表 ⇒ 侧边栏/导航/路由守卫/筛选器全按 GG 算：看着是 TT、实际是 GG。
    // 播种只用存储（路由要等 afterEach：首帧导航是异步的，这里读不到）；`initFromStorage`
    // 拿到 user 后再按角色归一。
    currentPlatform: sanitizePlatform(localStorage.getItem(PLATFORM_KEY))
  }),
  getters: {
    isAdmin: (state) => ['developer', 'admin'].includes(state.user?.role),
    isDeveloper: (state) => state.user?.role === 'developer',
    isViewer: (state) => state.user?.role === 'viewer',
    isHuguan: (state) => state.user?.role === 'huguan',
    canSwitchPlatform: (state) => ['developer', 'huguan'].includes(state.user?.role),
    canManageAccounts: (state) => ['developer', 'admin', 'huguan'].includes(state.user?.role),
    canAccessProducts: (state) => ['developer', 'admin', 'viewer', 'user'].includes(state.user?.role),
    // ⚠️ 下面三个只反映「**当前所看的平台**」（对可切换的角色才有意义）。
    // 非切换角色请用 `effectivePlatform`（它按 user.platform 推导）—— 直接读 currentPlatform
    // 会拿到与账号无关的值。
    isFbUser: (state) => state.currentPlatform === 'fb',
    isGgUser: (state) => state.currentPlatform === 'gg',
    isTtUser: (state) => state.currentPlatform === 'tt',
    effectivePlatform: (state) => {
      if (state.canSwitchPlatform) return state.currentPlatform
      return state.user?.platform || 'gg'
    },
    homePath: (state) => {
      // 户管跨平台：落地账户页，平台取其当前切换到的平台
      if (state.user?.role === 'huguan') {
        const p = state.effectivePlatform
        return p === 'fb' ? '/fb/accounts' : p === 'tt' ? '/tt/accounts' : '/accounts/ads'
      }
      // 其余角色沿用改动前的 user.platform 推断，落地页与弹回目标逐字不变
      const p = state.user?.platform || 'gg'
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
        this.currentPlatform = sanitizePlatform(res.user?.platform)
      }
      // 落盘：刷新后要恢复成同一个平台（见 state 上方注释）
      localStorage.setItem(PLATFORM_KEY, this.currentPlatform)
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
        this.currentPlatform = sanitizePlatform(platform)
        localStorage.setItem(PLATFORM_KEY, this.currentPlatform)
      }
    },
    /** 路由是平台的**最终依据**（切平台即导航，见 AppSidebar.switchPlatform）。
     *  入参是 `to.meta.platform` —— 路由**自己声明**的平台族，而不是按路径推（见 platformFamily 的注释：
     *  按路径推会把 `/profile`、`/analysis` 这类中性页按成 gg，害得 TT/FB 用户一点就掉回 GG）。
     *  **必须挂在 `router.afterEach` 上**（见 main.js）：首帧导航是异步的（守卫经微任务），
     *  放在 App.vue 的 onMounted 里那一刻 `route.meta` 还是空的 ⇒ 会是一次**空操作**（踩过）。
     *  路由没有平台声明时**不动平台、更不落盘**。 */
    syncPlatformFromRoute(metaPlatform) {
      if (!this.canSwitchPlatform) return
      const p = platformFamily(metaPlatform)
      if (p && this.currentPlatform !== p) this.setPlatform(p)
    },
    logout() {
      this.user = null
      this.token = ''
      this.isLoggedIn = false
      this.currentPlatform = 'gg'
      localStorage.removeItem(PLATFORM_KEY)
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
        // 拿到 user 才知道能不能切平台 ⇒ 平台按角色在这里归一（判据见 utils/platformPrefs.mjs）
        this.currentPlatform = resolvePlatform({
          stored: localStorage.getItem(PLATFORM_KEY),
          canSwitch: this.canSwitchPlatform,
          userPlatform: this.user?.platform,
        })
      }
    }
  }
})
