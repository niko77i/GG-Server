import api from './client'

export const googleSheetsApi = {
  /** 检查 Google Sheets API 配置状态（OAuth 凭据等） */
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

  /** 将做表数据写入用户激活的 Google Sheets */
  updateZuobiao(body) {
    return api.post('/google-sheets/update-zuobiao', body)
  }
}
