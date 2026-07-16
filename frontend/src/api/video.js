import api from './client'

export const videoApi = {
  scanDir:     (body) => api.post('/video/scan-dir', body),
  generate:    (body) => api.post('/video/generate', body),
  progress:    (taskId) => api.get(`/video/progress?task_id=${taskId}`),
  nextFilename:(body) => api.post('/video/next-filename', body),
  historyList: ()     => api.get('/video/history/list'),
  historySave: (body) => api.post('/video/history/save', body),
  historyDelete:(body)=> api.post('/video/history/delete', body),
  audioReplace:(body) => api.post('/audio-replace', body),
  audioHistoryList:  ()     => api.get('/audio-replace/history'),
  audioHistoryDelete:(id)   => api.delete(`/audio-replace/history/${id}`),
  audioHistoryClear: ()     => api.delete('/audio-replace/history'),
  fontsList:   ()     => api.get('/fonts/list'),
  fontsImport: (body) => api.post('/fonts/import', body),
  fontsUpload: (formData) => api.post('/fonts/upload', formData, { headers: { 'Content-Type': 'multipart/form-data' } }),
  fontsMarkUsed:(body)=> api.post('/fonts/mark-used', body),
  packages:    (userDn) => api.get('/scrape/packages' + (userDn ? '?user_dn=' + encodeURIComponent(userDn) : '')),
  scrapeUsers:   ()     => api.get('/scrape/users'),
  uploadImages:  (formData) => api.post('/scrape/upload-images', formData, { headers: { 'Content-Type': 'multipart/form-data' } }),
  musicList:   ()     => api.get('/video/music-list'),
  uploadMusic: (formData) => api.post('/video/upload-music', formData, { headers: { 'Content-Type': 'multipart/form-data' } }),
}
