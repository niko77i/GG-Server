import api from './client'

export const productsApi = {
  list:        (params) => api.get('/products/list', { params }),
  create:      (body)   => api.post('/products/create', body),
  update:      (id, body) => api.put(`/products/${id}`, body),
  delete:      (id)     => api.delete(`/products/${id}`),
  detail:      (id)     => api.get(`/products/${id}/detail`),
  addPackage:  (pid, body) => api.post(`/products/${pid}/packages`, body),
  updatePackage: (pkgId, body) => api.put(`/products/packages/${pkgId}`, body),
  deletePackage: (pkgId) => api.delete(`/products/packages/${pkgId}`),
  importText:  (body)   => api.post('/products/import-text', body),
  // 新增
  merge:       (body)   => api.post('/products/merge', body),
  updateRunners: (pid, body) => api.put(`/products/${pid}/runners`, body),
}
