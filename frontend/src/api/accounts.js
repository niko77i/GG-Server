import api from './client'

export const accountsApi = {
  list:   (params) => api.get('/api/accounts/list', { params }),
  create: (body)   => api.post('/api/accounts/create', body),
  update: (id, body) => api.put(`/api/accounts/${id}`, body),
  delete: (id)     => api.delete(`/api/accounts/${id}`),
  batchDelete: (ids) => api.post('/api/accounts/batch-delete', { ids }),
  batchUpdate: (body) => api.post('/api/accounts/batch-update', body),
}

export const mccApi = {
  list:   (params) => api.get('/api/mcc/list', { params }),
  options:()       => api.get('/api/mcc/options'),
  create: (body)   => api.post('/api/mcc/create', body),
  update: (id, body) => api.put(`/api/mcc/${id}`, body),
  delete: (id)     => api.delete(`/api/mcc/${id}`),
  batchDelete: (ids) => api.post('/api/mcc/batch-delete', { ids }),
  detail: (id)     => api.get(`/api/mcc/${id}/detail`),
}

export const settingsApi = {
  get: ()     => api.get('/api/settings/account'),
  save: (body) => api.post('/api/settings/account', body),
}
