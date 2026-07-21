import axios from 'axios'

const api = axios.create({ baseURL: '/api', timeout: 30000 })

api.interceptors.request.use(config => {
  const token = localStorage.getItem('token')
  if (token) {
    config.headers.Authorization = 'Bearer ' + token
  }
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
