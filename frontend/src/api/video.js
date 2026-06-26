import api from './client'

export const videoApi = {
  scanDir:     (body) => api.post('/api/video/scan-dir', body),
  generate:    (body) => api.post('/api/video/generate', body),
  progress:    (taskId) => api.get(`/api/video/progress?task_id=${taskId}`),
  nextFilename:(body) => api.post('/api/video/next-filename', body),
  historyList: ()     => api.get('/api/video/history/list'),
  historySave: (body) => api.post('/api/video/history/save', body),
  historyDelete:(body)=> api.post('/api/video/history/delete', body),
  audioReplace:(body) => api.post('/api/audio-replace', body),
  fontsList:   ()     => api.get('/api/fonts/list'),
  fontsImport: (body) => api.post('/api/fonts/import', body),
  fontsMarkUsed:(body)=> api.post('/api/fonts/mark-used', body),
}
