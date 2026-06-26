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
  }
}