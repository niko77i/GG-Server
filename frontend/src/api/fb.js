/** FB 平台 API 调用模块 */
import client from './client'

export const fbApi = {
  // BM 管理
  listBms(params = {}) { return client.get('/api/fb/bms/list', { params }) },
  createBm(data) { return client.post('/api/fb/bms/create', data) },
  updateBm(id, data) { return client.put(`/api/fb/bms/${id}`, data) },
  deleteBm(id) { return client.delete(`/api/fb/bms/${id}`) },
  bmOptions() { return client.get('/api/fb/bms/options') },
  banAndMigrate(id, data) { return client.post(`/api/fb/bms/${id}/ban-and-migrate`, data) },

  // 账户管理
  listAccounts(params = {}) { return client.get('/api/fb/accounts/list', { params }) },
  createAccount(data) { return client.post('/api/fb/accounts/create', data) },
  updateAccount(id, data) { return client.put(`/api/fb/accounts/${id}`, data) },
  deleteAccount(id) { return client.delete(`/api/fb/accounts/${id}`) },
  restoreAccount(id) { return client.post(`/api/fb/accounts/${id}/restore`) },
  permanentDeleteAccount(id) { return client.delete(`/api/fb/accounts/${id}/permanent`) },
  accountBmHistory(id) { return client.get(`/api/fb/accounts/${id}/bm-history`) },

  // 产品管理
  listProducts(params = {}) { return client.get('/api/fb/products/list', { params }) },
  runnerProducts() { return client.get('/api/fb/products/runner-products') },
  createProduct(data) { return client.post('/api/fb/products/create', data) },
  updateProduct(id, data) { return client.put(`/api/fb/products/${id}`, data) },
  deleteProduct(id) { return client.delete(`/api/fb/products/${id}`) },
  productDetail(id) { return client.get(`/api/fb/products/${id}/detail`) },

  // 线名管理
  addLine(productId, data) { return client.post(`/api/fb/products/${productId}/lines`, data) },
  updateLine(id, data) { return client.put(`/api/fb/lines/${id}`, data) },
  deleteLine(id) { return client.delete(`/api/fb/lines/${id}`) },

  // 像素BM管理
  listPixelBms(params = {}) { return client.get('/api/fb/pixel-bms/list', { params }) },
  createPixelBm(data) { return client.post('/api/fb/pixel-bms/create', data) },
  updatePixelBm(id, data) { return client.put(`/api/fb/pixel-bms/${id}`, data) },
  deletePixelBm(id) { return client.delete(`/api/fb/pixel-bms/${id}`) },
  pixelBmOptions() { return client.get('/api/fb/pixel-bms/options') },

  // 像素管理
  listPixels(bmId) { return client.get(`/api/fb/pixel-bms/${bmId}/pixels`) },
  createPixel(bmId, data) { return client.post(`/api/fb/pixel-bms/${bmId}/pixels`, data) },
  updatePixel(id, data) { return client.put(`/api/fb/pixels/${id}`, data) },
  deletePixel(id) { return client.delete(`/api/fb/pixels/${id}`) },

  // 数据提取
  parseExtract(data) { return client.post('/api/fb/extract/parse', data) },
  saveExtract(data) { return client.post('/api/fb/extract/save', data) },

  // 用户查询
  listFbUsers() { return client.get('/api/fb/users') },

  // 数据管理
  listReports(params = {}) { return client.get('/api/fb/reports/list', { params }) },
  updateReport(id, data) { return client.put(`/api/fb/reports/${id}`, data) },
  deleteReport(id) { return client.delete(`/api/fb/reports/${id}`) },
  batchDeleteReports(ids) { return client.post('/api/fb/reports/batch-delete', { ids }) },
  reportStats(params = {}) { return client.get('/api/fb/reports/stats', { params }) },
  exportReports(params = {}) { return client.get('/api/fb/reports/export', { params }) },
}
