/** FB 平台 API 调用模块 */
import client from './client'

export const fbApi = {
  // BM 管理
  listBms(params = {}) { return client.get('/fb/bms/list', { params }) },
  createBm(data) { return client.post('/fb/bms/create', data) },
  updateBm(id, data) { return client.put(`/fb/bms/${id}`, data) },
  deleteBm(id) { return client.delete(`/fb/bms/${id}`) },
  bmOptions() { return client.get('/fb/bms/options') },
  banAndMigrate(id, data) { return client.post(`/fb/bms/${id}/ban-and-migrate`, data) },
  listUnifiedBms(params = {}) { return client.get('/fb/bms/unified', { params }) },

  // 账户管理
  listAccounts(params = {}) { return client.get('/fb/accounts/list', { params }) },
  createAccount(data) { return client.post('/fb/accounts/create', data) },
  updateAccount(id, data) { return client.put(`/fb/accounts/${id}`, data) },
  deleteAccount(id) { return client.delete(`/fb/accounts/${id}`) },
  restoreAccount(id) { return client.post(`/fb/accounts/${id}/restore`) },
  permanentDeleteAccount(id) { return client.delete(`/fb/accounts/${id}/permanent`) },
  accountBmHistory(id) { return client.get(`/fb/accounts/${id}/bm-history`) },

  // 产品管理
  listProducts(params = {}) { return client.get('/fb/products/list', { params }) },
  runnerProducts() { return client.get('/fb/products/runner-products') },
  createProduct(data) { return client.post('/fb/products/create', data) },
  updateProduct(id, data) { return client.put(`/fb/products/${id}`, data) },
  deleteProduct(id) { return client.delete(`/fb/products/${id}`) },
  restoreProduct(id) { return client.post(`/fb/products/${id}/restore`) },
  productDetail(id) { return client.get(`/fb/products/${id}/detail`) },

  // 线名管理
  addLine(productId, data) { return client.post(`/fb/products/${productId}/lines`, data) },
  updateLine(id, data) { return client.put(`/fb/lines/${id}`, data) },
  deleteLine(id) { return client.delete(`/fb/lines/${id}`) },

  // 像素BM管理
  listPixelBms(params = {}) { return client.get('/fb/pixel-bms/list', { params }) },
  createPixelBm(data) { return client.post('/fb/pixel-bms/create', data) },
  updatePixelBm(id, data) { return client.put(`/fb/pixel-bms/${id}`, data) },
  deletePixelBm(id) { return client.delete(`/fb/pixel-bms/${id}`) },
  pixelBmOptions() { return client.get('/fb/pixel-bms/options') },

  // 像素管理
  listPixels(bmId) { return client.get(`/fb/pixel-bms/${bmId}/pixels`) },
  listAllPixels(params = {}) { return client.get('/fb/pixels/list', { params }) },
  createPixel(bmId, data) { return client.post(`/fb/pixel-bms/${bmId}/pixels`, data) },
  updatePixel(id, data) { return client.put(`/fb/pixels/${id}`, data) },
  deletePixel(id) { return client.delete(`/fb/pixels/${id}`) },

  // 数据提取
  parseExtract(data) { return client.post('/fb/extract/parse', data) },
  checkDuplicates(data) { return client.post('/fb/extract/check-duplicates', data) },
  saveExtract(data) { return client.post('/fb/extract/save', data) },

  // 用户查询
  listFbUsers() { return client.get('/fb/users') },

  // 数据管理
  listReports(params = {}) { return client.get('/fb/reports/list', { params }) },
  updateReport(id, data) { return client.put(`/fb/reports/${id}`, data) },
  deleteReport(id) { return client.delete(`/fb/reports/${id}`) },
  batchDeleteReports(ids) { return client.post('/fb/reports/batch-delete', { ids }) },
  reportStats(params = {}) { return client.get('/fb/reports/stats', { params }) },
  exportReports(params = {}) { return client.get('/fb/reports/export', { params }) },
  retrySheetsSync() { return client.post('/fb/reports/retry-sync') },
  lastSyncStatus() { return client.get('/fb/reports/last-sync') },
}
