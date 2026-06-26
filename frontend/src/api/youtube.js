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

export const translateApi = {
  translate: (body) => api.post('/translate', body),
}
