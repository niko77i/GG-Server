import axios from 'axios'
import { platformFromPath } from '../utils/platformPrefs.mjs'

const api = axios.create({ baseURL: '/api', timeout: 30000 })

api.interceptors.request.use(config => {
  const token = localStorage.getItem('token')
  if (token) {
    config.headers.Authorization = 'Bearer ' + token
  }
  // 跨平台角色（developer / 户管）请求时传递 platform 参数。
  // 推导规则与 store（侧边栏/导航）**共用同一份**（`utils/platformPrefs.mjs`）—— 两处口径必须一致，
  // 否则会出现「数据是 TT、导航是 GG」这种割裂（2026-10-11 修）。路由"没有意见"（null：/admin/users、
  // 首帧未解析、根路径）时不带该参数，绝不凭空按 GG。
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
