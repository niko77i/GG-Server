import api from './client'

export const dataApi = {
  // 上传文件导入（自动识别 db/json）
  importFile(file) {
    const formData = new FormData()
    formData.append('file', file)
    return api.post('/data/import', formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
      timeout: 120000,
    })
  },

  // 导出当前用户数据
  exportData() {
    return api.get('/data/export', { responseType: 'blob' })
  },

  // 导入历史
  importHistory() {
    return api.get('/data/import-history')
  },
}

export const adminDataApi = {
  // 管理员为指定用户导入
  importForUser(file, userId) {
    const formData = new FormData()
    formData.append('file', file)
    formData.append('user_id', userId)
    return api.post('/admin/data/import', formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
      timeout: 120000,
    })
  },

  // 管理员导出指定用户
  exportUserData(userId) {
    return api.get(`/admin/data/export/${userId}`, { responseType: 'blob' })
  },
}
