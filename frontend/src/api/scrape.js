import api from './client'

export const scrapeApi = {
  scrape: (body) => api.post('/api/scrape', body),
}
