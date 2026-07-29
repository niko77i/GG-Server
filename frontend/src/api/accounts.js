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
  rechargeRecords: (aid) => api.get(`/accounts/${aid}/recharge-records`),
  syncFromSheet: (body) => api.post('/accounts/sync-from-sheet', body),
  restore: (id) => api.post(`/accounts/${id}/restore`),
  permanentDelete: (id) => api.delete(`/accounts/${id}/permanent`),
  listDeleted: () => api.get('/accounts/deleted'),
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
  update: (id, body) => api.put(`/recharge/${id}`, body),
  delete: (id) => api.delete(`/recharge/${id}`),
  retrySheets: (id) => api.post(`/recharge/${id}/retry-sheets`),
}

export const optionApi = {
  // agents
  agents:    { list: () => api.get('/agents/list'), create: (name) => api.post('/agents/create', {name}),
               rename: (id, name) => api.put(`/agents/${id}`, {name}), delete: (id) => api.delete(`/agents/${id}`) },
  // statuses
  statuses:  { list: () => api.get('/statuses/list'), create: (name) => api.post('/statuses/create', {name}),
               rename: (id, name) => api.put(`/statuses/${id}`, {name}), delete: (id) => api.delete(`/statuses/${id}`) },
  // mcc levels
  mccLevels: { list: () => api.get('/mcc-levels/list'), create: (name) => api.post('/mcc-levels/create', {name}),
               rename: (id, name) => api.put(`/mcc-levels/${id}`, {name}), delete: (id) => api.delete(`/mcc-levels/${id}`) },
  // sales persons
  salesPersons: { list: () => api.get('/sales-persons/list'), create: (name) => api.post('/sales-persons/create', {name}),
                  rename: (id, name) => api.put(`/sales-persons/${id}`, {name}), delete: (id) => api.delete(`/sales-persons/${id}`) },
}
