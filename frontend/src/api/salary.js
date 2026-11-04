import api from './client'

export const salaryApi = {
  /** 读取某张做表 → 聚合结果 + 默认参数下的薪资明细 */
  overview(spreadsheetId) {
    return api.get('/salary/overview', {
      params: { spreadsheet_id: spreadsheetId || '' },
    })
  },

  /** 只重算薪资（不读表）：底薪 / 成本 / 汇率变化时调用 */
  compute(body) {
    return api.post('/salary/compute', body)
  },
}
