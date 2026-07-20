import api from './client'

export const adminApi = {
  listUsers(params) {
    return api.get('/admin/users', { params })
  },
  createUser(data) {
    return api.post('/admin/users/create', data)
  },
  updateRole(uid, role) {
    return api.post(`/admin/users/${uid}/role`, { role })
  },
  toggleUser(uid) {
    return api.post(`/admin/users/${uid}/toggle`)
  },
  deleteUser(uid) {
    return api.delete(`/admin/users/${uid}`)
  },
  updateUser(uid, data) {
    return api.put(`/admin/users/${uid}`, data)
  },
  resetPassword(uid, password) {
    return api.put(`/admin/users/${uid}/password`, { password })
  },
  updateUserTelegram(uid, username) {
    return api.put(`/admin/users/${uid}/telegram-username`, { telegram_username: username })
  },
  triggerWeeklyCleanup() {
    return api.post('/admin/trigger-weekly-cleanup')
  },
  triggerDelistCheck() {
    return api.post('/admin/trigger-delist-check')
  }
}