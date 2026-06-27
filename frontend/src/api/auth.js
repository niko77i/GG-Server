import api from './client'

export const authApi = {
  login(username, password) {
    return api.post('/auth/login', { username, password })
  },
  register(username, password, display_name) {
    return api.post('/auth/register', { username, password, display_name })
  },
  refresh() {
    return api.post('/auth/refresh')
  },
  me() {
    return api.get('/auth/me')
  },
  changePassword(oldPassword, newPassword) {
    return api.put('/auth/password', { old_password: oldPassword, new_password: newPassword })
  },
  updateProfile(data) {
    return api.put('/auth/profile', data)
  }
}
