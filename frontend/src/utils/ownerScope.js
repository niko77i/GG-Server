/**
 * 账户类面板「归属人」下拉的默认作用域。
 *
 * developer / admin 进本平台面板时默认选中自己；户管与跨平台场景保持「全部用户」。
 *
 * 为什么带平台条件：开发者可跨平台切面板，但本人在别的平台可能一个户都没有
 * （例如 GG 的开发者切到 TT 面板）。若无条件默认选自己，那边就是空表 —— 比默认「全部」更糟。
 *
 * @param {{id:number, role:string, platform:string}|null} user 当前登录用户
 * @param {string} effectivePlatform 当前所看面板的平台（'gg' | 'fb' | 'tt'）
 * @returns {number|string} 默认 owner_id；'' 表示「全部用户」
 */
export function defaultOwnerScope(user, effectivePlatform) {
  if (!user || !user.id) return ''
  // 户管保持「全部」（用户裁定）；其余非跨用户角色本就不显示该下拉
  if (user.role !== 'developer' && user.role !== 'admin') return ''
  // 跨平台面板不默认自己：本人可能在该平台一个户都没有，默认自己会得到空表
  if (user.platform !== effectivePlatform) return ''
  return user.id
}
