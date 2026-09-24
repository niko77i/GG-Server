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
  getPendingDelist() { return client.get('/tt/delist/pending') },
  dismissDelist(packageIds) { return client.post('/tt/delist/dismiss', { package_ids: packageIds }) },

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

/** TT 广告账户 */
export const ttAccountsApi = {
  list:   (params) => client.get('/tt/accounts/list', { params }),
  lookup: (advertiserId) => client.get('/tt/accounts/lookup', { params: { advertiser_id: advertiserId } }),
  batchLookup: (accountIds) => client.post('/tt/accounts/batch-lookup', { account_ids: accountIds }),
  create: (body) => client.post('/tt/accounts/create', body),
  batchCreate: (body) => client.post('/tt/accounts/batch-create', body),
  update: (id, body) => client.put(`/tt/accounts/${id}`, body),
  reassign: (id, body) => client.put(`/tt/accounts/${id}/reassign`, body || {}),
  delete: (id) => client.delete(`/tt/accounts/${id}`),
  batchDelete: (ids) => client.post('/tt/accounts/batch-delete', { ids }),
  batchUpdate: (body) => client.post('/tt/accounts/batch-update', body),
  restore: (id) => client.post(`/tt/accounts/${id}/restore`),
  permanentDelete: (id) => client.delete(`/tt/accounts/${id}/permanent`),
  listDeleted: () => client.get('/tt/accounts/deleted'),
  bcHistory: (id) => client.get(`/tt/accounts/${id}/bc-history`),
  deleteBcHistory: (id, hid) => client.delete(`/tt/accounts/${id}/bc-history/${hid}`),
  syncFromSheet: (body) => client.post('/tt/accounts/sync-from-sheet', body),
}

/** TT 充值 */
export const ttRechargeApi = {
  records: (aid) => client.get(`/tt/accounts/${aid}/recharge-records`),
  submit: (body) => client.post('/tt/recharge/submit', body),
  batchSubmit: (body) => client.post('/tt/recharge/batch-submit', body),
  update: (id, body) => client.put(`/tt/recharge/${id}`, body),
  delete: (id) => client.delete(`/tt/recharge/${id}`),
  retrySheets: (id) => client.post(`/tt/recharge/${id}/retry-sheets`),
}

/** TT 回收原因 */
export const ttRecycleReasonApi = {
  list: () => client.get('/tt/recycle-reasons/list'),
  create: (name) => client.post('/tt/recycle-reasons/create', { name }),
  rename: (id, name) => client.put(`/tt/recycle-reasons/${id}`, { name }),
  delete: (id) => client.delete(`/tt/recycle-reasons/${id}`),
}
