import api from './client'

export const reportsApi = {
  checkDuplicates: (body) => api.post('/ad-reports/check-duplicates', body),
  save:          (body) => api.post('/ad-reports/save', body),
  list:          (params) => api.get('/ad-reports/list', { params }),
  products:      () => api.get('/ad-reports/products'),
  delete:        (id) => api.delete(`/ad-reports/${id}`),
  dashboard:     (params) => api.get('/ad-reports/dashboard', { params }),
  trends:        (params) => api.get('/ad-reports/trends', { params }),
  compare:       (params) => api.get('/ad-reports/compare', { params }),
  crossUser:     (params) => api.get('/ad-reports/cross-user', { params }),
  analyze:       (body) => api.post('/ad-reports/analyze', body),
}
