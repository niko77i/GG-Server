import api from './client'

export const huguanApi = {
  /** 当前户管的看板配置（GG / TT 两份） */
  getConfig: () => api.get('/huguan/dashboard'),

  /** 保存某平台的看板配置（platform: 'gg' | 'tt'） */
  saveConfig: (body) => api.post('/huguan/dashboard', body),

  /** 系统 → 表：全量刷新（body 由封装补 platform） */
  push: (platform) => api.post('/huguan/dashboard/push', { platform }),

  /** 表 → 系统：dry_run=true 出差异报告，false 才落库 */
  sync: (body) => api.post('/huguan/dashboard/sync', body),

  // 「户归属」下拉的数据源（编辑用途，全量用户）。**不要**换回 /platform/users：
  // 那个端点是给「归属人」筛选器用的，只列该平台有未删除账户的人；拿它当改归属的
  // 选项源，户管就没法把 GG 的户转给一个只在 TT 有户的合法用户（实测缺口）。
  // 见 docs/superpowers/specs/2026-09-24-huguan-owner-source-and-picker-design.md §2。
  ownerOptions: () => api.get('/huguan/dashboard/owner-options'),
}
