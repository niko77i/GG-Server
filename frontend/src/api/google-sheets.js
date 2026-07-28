import api from './client'

export const googleSheetsApi = {
  /** 检查 Google Sheets API 配置状态 */
  status() {
    return api.get('/google-sheets/status')
  },

  /** 获取当前用户的 Google Sheets 配置 */
  getConfig() {
    return api.get('/config/google-sheets')
  },

  /** 保存当前用户的 Google Sheets 配置 */
  saveConfig(body) {
    return api.post('/config/google-sheets', body)
  },

  /** 将做表数据写入用户激活的 Google Sheets（后台异步） */
  updateZuobiao(body) {
    return api.post('/google-sheets/update-zuobiao', body)
  },

  /** 查询指定产品的 Sheets 同步状态（含失败行数据） */
  syncStatus(productName) {
    return api.get('/google-sheets/sync-status', { params: { product_name: productName } })
  },

  /** 手动重试做表数据 Sheets 同步 */
  retrySync(body) {
    return api.post('/google-sheets/retry-sync', body)
  },

  /** 读取指定 spreadsheet 中的所有 sheet 列表 */
  listSheets(spreadsheetId) {
    return api.get('/google-sheets/sheets', { params: { spreadsheet_id: spreadsheetId } })
  },
}
