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
  batchDeletePackages: (ids) => api.post('/products/packages/batch-delete', { ids }),
  importText:  (body)   => api.post('/products/import-text', body),
  // 新增
  merge:       (body)   => api.post('/products/merge', body),
  updateRunners: (pid, body) => api.put(`/products/${pid}/runners`, body),
  // 掉包检测
  checkDelist:  (pid)    => api.post(`/products/${pid}/check-delist`),
  getDelistStatus: ()    => api.get('/products/delist-status'),
  dismissDelist: (pkgId) => api.post('/delist/dismiss', { package_id: pkgId }),
  getPendingDelist: ()   => api.get('/delist/pending'),
  // 审计日志
  auditLogList: (params) => api.get('/audit-log/list', { params }),
  auditLogRestore: (logId) => api.post(`/audit-log/restore/${logId}`),

}
