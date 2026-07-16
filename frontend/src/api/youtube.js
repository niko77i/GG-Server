import api from './client'

export const youtubeApi = {
  list:    (params) => api.get('/youtube/list', { params }),
  import:  (body)   => api.post('/youtube/import', body),
  delete:  (body)   => api.post('/youtube/delete', body),
  edit:    (body)   => api.post('/youtube/edit', body),
  batchEdit: (body) => api.post('/youtube/batch-edit', body),
  tagsGet: ()       => api.get('/youtube/tags'),
  tagsSave:(body)   => api.post('/youtube/tags', body),
  dates:   (params) => api.get('/youtube/dates', { params }),
}

export const copywritingApi = {
  list:      (params) => api.get('/copywriting/list', { params }),
  import:    (body)   => api.post('/copywriting/import', body),
  edit:      (body)   => api.post('/copywriting/edit', body),
  delete:    (body)   => api.post('/copywriting/delete', body),
  batchEdit: (body)   => api.post('/copywriting/batch-edit', body),
}

export const consumptionApi = {
  get:      (videoId) => api.get(`/youtube/${videoId}/consumption`),
  add:      (videoId, body) => api.post(`/youtube/${videoId}/consumption`, body),
  update:   (videoId, recordId, body) => api.put(`/youtube/${videoId}/consumption/${recordId}`, body),
  delete:   (videoId, recordId) => api.delete(`/youtube/${videoId}/consumption/${recordId}`),
  dates:    (params) => api.get('/youtube/consumption/dates', { params }),
}

export const productApi = {
  runnerProducts: () => api.get('/products/runner-products'),
}

export const translateApi = {
  translate: (body) => api.post('/translate', body),
}
