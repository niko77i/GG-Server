import api from './client'

export const productsApi = {
  list:        (params) => api.get('/api/products/list', { params }),
  create:      (body)   => api.post('/api/products/create', body),
  update:      (id, body) => api.put(`/api/products/${id}`, body),
  delete:      (id)     => api.delete(`/api/products/${id}`),
  detail:      (id)     => api.get(`/api/products/${id}/detail`),
  addPackage:  (pid, body) => api.post(`/api/products/${pid}/packages`, body),
  updatePackage: (pkgId, body) => api.put(`/api/products/packages/${pkgId}`, body),
  deletePackage: (pkgId) => api.delete(`/api/products/packages/${pkgId}`),
  importText:  (body)   => api.post('/api/products/import-text', body),
}
