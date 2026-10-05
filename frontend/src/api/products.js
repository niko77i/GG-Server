import api from './client'

export const productsApi = {
  list:        (params) => api.get('/products/list', { params }),
  create:      (body)   => api.post('/products/create', body),
  update:      (id, body) => api.put(`/products/${id}`, body),
  delete:      (id)     => api.delete(`/products/${id}`),
  restore:     (id)     => api.post(`/products/${id}/restore`),
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
  // check-delist 后端并发按代理池容量自适应（2 个代理时 4 并发）：正常几秒返回，
  // 但单包最坏 20s（连接/读取各 5s × 2 次代理尝试），24 包 6 批最坏 120s；
  // 默认 30s 超时连正常路径都不够。
  // 单条放宽到 180s，否则前端先报超时、后端仍在跑并照常写库发通知。
  checkDelist:  (pid)    => api.post(`/products/${pid}/check-delist`, null, { timeout: 180000 }),
  getDelistStatus: ()    => api.get('/products/delist-status'),
  dismissDelist: (packageIds) => api.post('/delist/dismiss', { package_ids: packageIds }),
  getPendingDelist: ()   => api.get('/delist/pending'),
  // 审计日志
  auditLogList: (params) => api.get('/audit-log/list', { params }),
  auditLogRestore: (logId) => api.post(`/audit-log/restore/${logId}`),

}
