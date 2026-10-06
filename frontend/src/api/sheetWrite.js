/** 写表失败治理（跨平台） */
import client from './client'

export const sheetWriteApi = {
  // 带 business_key 供轮询单条；不带则只回需要提示的终态，供列表标记
  status({ platform, businessKey } = {}) {
    const params = { platform }
    if (businessKey) params.business_key = businessKey
    return client.get('/sheet-write/status', { params })
  },
  retry({ platform, target, businessKey }) {
    return client.post('/sheet-write/retry', {
      platform, target, business_key: businessKey,
    })
  },
}
