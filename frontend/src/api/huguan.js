import api from './client'

export const huguanApi = {
  /** 当前户管的看板配置（GG / TT / FB 各一份）。tt 条目额外带
   *  `tables: [{name, sheet_name}]`（多张账户表），并保留 `sheet_name`
   *  （= tables[0].sheet_name）供老前端；gg/fb 不返回 tables。 */
  getConfig: () => api.get('/huguan/dashboard'),

  /** 保存某平台的看板配置（platform: 'gg' | 'tt' | 'fb'）。
   *  tt 传 `tables: [{name, sheet_name}]`（非空、类型名与工作表名互不重复）；
   *  gg/fb 传单个 `sheet_name`。 */
  saveConfig: (body) => api.post('/huguan/dashboard', body),

  /** 读某张 tt 表的第 1 行，摊成逐列「表头 → 字段 + 来源」，供列映射区显示。
   * 只有 TT 支持（gg/fb 调会 400）；sheet_name 必须是该户管自己配置里的某张表。 */
  getSheetHeaders: (platform, sheetName) =>
    api.get('/huguan/dashboard/sheet-headers', { params: { platform, sheet_name: sheetName } }),

  /** 系统 → 表：全量刷新（body 由封装补 platform） */
  push: (platform) => api.post('/huguan/dashboard/push', { platform }),

  /** 表 → 系统：dry_run=true 出差异报告，false 才落库 */
  sync: (body) => api.post('/huguan/dashboard/sync', body),

  /** 两个方向各有没有可撤的快照（子项目 ③）。平铺：res.push / res.sync，各为
   *  `{count, created_at}` 或 null。⚠️ **不是** res.undo.push（计划里的写法已弃用）。 */
  getUndo: (platform) => api.get('/huguan/dashboard/undo', { params: { platform } }),

  /** 执行一次撤回。direction: 'push' | 'sync'。uid 由后端从 JWT 取，请求体不带。 */
  doUndo: (platform, direction) => api.post('/huguan/dashboard/undo', { platform, direction }),

  // 「户归属」下拉的数据源（**编辑**用途：当前看板平台的用户 + developer/户管）。
  // **不要**换回 /platform/users：那个端点是给「归属人」筛选器用的，只列该平台有未
  // 删除账户的人；拿它当改归属的选项源，户管就没法把户转给刚建号、还没分到户的新人。
  // 两者现在都按平台隔离（2026-09-28 起），差别只剩这一条「是否要求已有账户」。
  // 见 docs/superpowers/specs/2026-09-28-huguan-owner-options-platform-isolation-design.md。
  ownerOptions: () => api.get('/huguan/dashboard/owner-options'),
}
