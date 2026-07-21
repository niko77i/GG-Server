import api from './client'

export const accountsApi = {
  list:   (params) => api.get('/accounts/list', { params }),
  create: (body)   => api.post('/accounts/create', body),
  update: (id, body) => api.put(`/accounts/${id}`, body),
  delete: (id)     => api.delete(`/accounts/${id}`),
  batchDelete: (ids) => api.post('/accounts/batch-delete', { ids }),
  batchUpdate: (body) => api.post('/accounts/batch-update', body),
  batchCreate: (body) => api.post('/accounts/batch-create', body),
  batchLookup: (accountIds) => api.post('/accounts/batch-lookup', { account_ids: accountIds }),
  lookup:  (accountId) => api.get('/accounts/lookup', { params: { account_id: accountId } }),
  reassign: (id, body) => api.put(`/accounts/${id}/reassign`, body || {}),
  history: (aid) => api.get(`/accounts/${aid}/mcc-history`),
  deleteHistory: (aid, hid) => api.delete(`/accounts/${aid}/mcc-history/${hid}`),
}

export const mccApi = {
  list:   (params) => api.get('/mcc/list', { params }),
  options:()       => api.get('/mcc/options'),
  create: (body)   => api.post('/mcc/create', body),
  update: (id, body) => api.put(`/mcc/${id}`, body),
  delete: (id)     => api.delete(`/mcc/${id}`),
  batchDelete: (ids) => api.post('/mcc/batch-delete', { ids }),
  detail: (id)     => api.get(`/mcc/${id}/detail`),
  link:   (id)     => api.post(`/mcc/${id}/link`),
}

export const settingsApi = {
  get: ()     => api.get('/settings/account'),
  save: (body) => api.post('/settings/account', body),
}

export const rechargeApi = {
  submit: (body) => api.post('/recharge/submit', body),
  batchSubmit: (body) => api.post('/recharge/batch-submit', body),
}
