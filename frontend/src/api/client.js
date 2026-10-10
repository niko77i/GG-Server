import axios from 'axios'
import { platformFromPath } from '../utils/platformPrefs.mjs'

const api = axios.create({ baseURL: '/api', timeout: 30000 })

api.interceptors.request.use(config => {
  const token = localStorage.getItem('token')
  if (token) {
    config.headers.Authorization = 'Bearer ' + token
  }
  // 跨平台角色（developer / 户管）请求时传递 platform 参数。
  // 规则抽到 `utils/platformPrefs.mjs` 的 `platformFromPath`（**请求层**专用：请求总得带一个平台，
  // 所以"其余一律 gg"是刻意的默认）；`/admin/users` 返回 null ⇒ 不带该参数
  //（该页有自己的平台 Tab，带 gg 会让「全部」看不到其它平台）。
  // ⚠️ store（侧边栏/导航）**不用**这条规则，它认 `to.meta.platform`（见 platformFamily）——
  // 按路径推会把 /profile、/analysis 这类中性页按成 gg（2026-10-11 审查抓到）。
  try {
    const user = JSON.parse(localStorage.getItem('user') || '{}')
    if (['developer', 'huguan'].includes(user.role)) {
      const platform = platformFromPath(window.location.hash.replace('#', ''))
      if (platform) {
        if (!config.params) config.params = {}
        if (!config.params.platform) config.params.platform = platform
      }
    }
  } catch(e) {}
  return config
})

api.interceptors.response.use(
  resp => {
    // 滑动过期：后端每次返回新 token，前端自动更新 localStorage
    const newToken = resp.headers['x-new-access-token']
    if (newToken) {
      localStorage.setItem('token', newToken)
    }
    return resp.data
  },
  err => {
    if (err.response?.status === 401 && !err.config.url?.includes('/auth/')) {
      localStorage.removeItem('token')
      localStorage.removeItem('user')
      window.location.hash = '#/login'
    }
    return Promise.reject(err)
  }
)

export default api
