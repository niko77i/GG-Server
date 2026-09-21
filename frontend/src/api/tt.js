/** TT 平台 API 调用模块 */
import client from './client'

export const ttApi = {
  // BC 管理
  listBcs(params = {}) { return client.get('/tt/bcs/list', { params }) },
  createBc(data) { return client.post('/tt/bcs/create', data) },
  updateBc(id, data) { return client.put(`/tt/bcs/${id}`, data) },
  deleteBc(id) { return client.delete(`/tt/bcs/${id}`) },
  bcOptions() { return client.get('/tt/bcs/options') },

  // 产品管理
  listProducts(params = {}) { return client.get('/tt/products/list', { params }) },
  runnerProducts() { return client.get('/tt/products/runner-products') },
  createProduct(data) { return client.post('/tt/products/create', data) },
  updateProduct(id, data) { return client.put(`/tt/products/${id}`, data) },
  deleteProduct(id) { return client.delete(`/tt/products/${id}`) },
  restoreProduct(id) { return client.post(`/tt/products/${id}/restore`) },
  productDetail(id) { return client.get(`/tt/products/${id}/detail`) },
  mergeProducts(data) { return client.post('/tt/products/merge', data) },

  // 投放对象
  addPackage(productId, data) { return client.post(`/tt/products/${productId}/packages`, data) },
  updatePackage(id, data) { return client.put(`/tt/packages/${id}`, data) },
  deletePackage(id) { return client.delete(`/tt/packages/${id}`) },
  batchDeletePackages(ids) { return client.post('/tt/packages/batch-delete', { ids }) },

  // 掉包检测
  checkDelist(productId) { return client.post(`/tt/products/${productId}/check-delist`) },
  delistStatus() { return client.get('/tt/products/delist-status') },

  // 粘贴解析
  importText(data) { return client.post('/tt/products/import-text', data) },

  // 素材
  listAssets(productId) { return client.get(`/tt/products/${productId}/assets`) },
  addAssets(productId, data) { return client.post(`/tt/products/${productId}/assets`, data) },
  deleteAsset(productId, videoId) { return client.delete(`/tt/products/${productId}/assets/${videoId}`) },

  // 用户
  listTtUsers() { return client.get('/tt/users') },
}

/** TT 设置（Google 表格配置） */
export const ttSettingsApi = {
  getSettings() { return client.get('/tt/settings') },
  saveSettings(data) { return client.post('/tt/settings', data) },
}

/** TT 数据管理（导出/导入） */
export const ttDataApi = {
  exportData() {
    return client.get('/tt/data/export', { responseType: 'blob' })
  },
  importFile(file) {
    const form = new FormData()
    form.append('file', file)
    return client.post('/tt/data/import', form, {
      headers: { 'Content-Type': 'multipart/form-data' }
    })
  },
}
