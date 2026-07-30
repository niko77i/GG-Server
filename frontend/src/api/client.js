import axios from 'axios'

const api = axios.create({ baseURL: '/api', timeout: 30000 })

api.interceptors.request.use(config => {
  const token = localStorage.getItem('token')
  if (token) {
    config.headers.Authorization = 'Bearer ' + token
  }
  // developer 跨平台时传递 platform 参数
  try {
    const user = JSON.parse(localStorage.getItem('user') || '{}')
    if (user.role === 'developer') {
      const path = window.location.hash.replace('#', '')
      const platform = path.startsWith('/fb') ? 'fb' : 'gg'
      if (!config.params) config.params = {}
      if (!config.params.platform) config.params.platform = platform
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
