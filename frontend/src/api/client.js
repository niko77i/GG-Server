import axios from 'axios'

const api = axios.create({ baseURL: '/api', timeout: 30000 })

api.interceptors.request.use(config => {
  const token = localStorage.getItem('token')
  if (token) {
    config.headers.Authorization = 'Bearer ' + token
  }
  // 跨平台角色（developer / 户管）请求时传递 platform 参数
  try {
    const user = JSON.parse(localStorage.getItem('user') || '{}')
    if (['developer', 'huguan'].includes(user.role)) {
      const path = window.location.hash.replace('#', '')
      // 用户管理页有自己的平台 Tab 显式控制平台，不由路由推断
      // （该页路由为 /admin/users，不以 /tt、/fb 开头，会被误判成 gg，导致「全部」看不到其他平台）
      if (!path.startsWith('/admin/users')) {
        const platform = path.startsWith('/tt') ? 'tt' : path.startsWith('/fb') ? 'fb' : 'gg'
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
