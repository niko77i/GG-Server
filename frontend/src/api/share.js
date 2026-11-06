import api from './client'

// 共享账号网关（广大大 / 有米云）
export const shareApi = {
  listSites: () => api.get('/share/sites'),
  enter: (id) => api.post(`/share/sites/${id}/enter`),
  logs: (id) => api.get(`/share/sites/${id}/logs`),
  reset: (id) => api.post(`/share/sites/${id}/reset`),
  check: (id) => api.post(`/share/sites/${id}/check`),
  update: (id, data) => api.put(`/share/sites/${id}`, data),
}
