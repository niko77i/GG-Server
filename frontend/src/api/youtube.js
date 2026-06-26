import api from './client'

export const youtubeApi = {
  list:    (params) => api.get('/api/youtube/list', { params }),
  import:  (body)   => api.post('/api/youtube/import', body),
  delete:  (body)   => api.post('/api/youtube/delete', body),
  edit:    (body)   => api.post('/api/youtube/edit', body),
  batchEdit: (body) => api.post('/api/youtube/batch-edit', body),
  tagsGet: ()       => api.get('/api/youtube/tags'),
  tagsSave:(body)   => api.post('/api/youtube/tags', body),
  dates:   (params) => api.get('/api/youtube/dates', { params }),
}

export const copywritingApi = {
  list:      (params) => api.get('/api/copywriting/list', { params }),
  import:    (body)   => api.post('/api/copywriting/import', body),
  edit:      (body)   => api.post('/api/copywriting/edit', body),
  delete:    (body)   => api.post('/api/copywriting/delete', body),
  batchEdit: (body)   => api.post('/api/copywriting/batch-edit', body),
}

export const translateApi = {
  translate: (body) => api.post('/api/translate', body),
}
