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

  // 「户归属」下拉的数据源（**编辑**用途：当前看板平台的用户 + developer/户管）。
  // **不要**换回 /platform/users：那个端点是给「归属人」筛选器用的，只列该平台有未
  // 删除账户的人；拿它当改归属的选项源，户管就没法把户转给刚建号、还没分到户的新人。
  // 两者现在都按平台隔离（2026-09-28 起），差别只剩这一条「是否要求已有账户」。
  // 见 docs/superpowers/specs/2026-09-28-huguan-owner-options-platform-isolation-design.md。
  ownerOptions: () => api.get('/huguan/dashboard/owner-options'),
}
