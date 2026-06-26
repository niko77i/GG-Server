import api from './client'

export const browseApi = {
  file:   (body) => api.post('/api/browse-file', body),
  save:   (body) => api.post('/api/browse-save', body),
  folder: (body) => api.post('/api/browse-folder', body),
}
