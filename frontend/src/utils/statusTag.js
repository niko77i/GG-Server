/**
 * 账户状态 → Element Plus el-tag type 映射
 * 替代各处重复的三元表达式：'存活' ? 'success' : '验证' ? 'warning' : '死亡' ? 'danger' : 'info'
 */
export function accountStatusTagType(status) {
  const map = { '存活': 'success', '验证': 'warning', '死亡': 'danger' }
  return map[status] || 'info'
}
