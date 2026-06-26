import api from './client'

export const browseApi = {
  file:   (body) => api.post('/browse-file', body),
  save:   (body) => api.post('/browse-save', body),
  folder: (body) => api.post('/browse-folder', body),
}
