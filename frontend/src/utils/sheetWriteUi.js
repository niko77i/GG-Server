/**
 * 写表失败治理的三态语汇与文案（跨平台、跨组件唯一文案源）。
 *
 * 原在 views/tt/TtAccountPanel.vue 内联，二期 GG 侧（AccountDetailModal / AdsAccountPanel）
 * 也要用同一套 —— 各写一份必然漂移，而「三种终态文案各自不同」是本功能的需求之一。
 * 故抽到这里，TT 与 GG 都从此 import（全仓只能有一份）。
 *
 * 本文件内容自 TtAccountPanel.vue 原样搬出，仅加 export 与 ElMessage 的 import。
 */
import { ElMessage } from 'element-plus'

// 写表状态三态。强度按「操作员要做什么」排，不按严重感：
//   retry_failed       表没写进去，但系统变更仍生效 → 要去补
//   rolled_back        表没写，系统已自动撤销       → 已了结，只有知情权（刻意压低）
//   rollback_abandoned 表没写，且未能自动撤销 → 数据可能不一致，须人工核对（最高）
// ✅ 沿用充值记录表「表格」列的既有符号
export const SHEET_WRITE_UI = {
  retry_failed:       { mark: '⚠️', tone: 'warning' },
  rolled_back:        { mark: '↩️', tone: 'info' },
  rollback_abandoned: { mark: '⛔', tone: 'danger' },
}
export const SHEET_WRITE_TOAST = {
  warning: ElMessage.warning, info: ElMessage.info, danger: ElMessage.error,
}
function sheetWriteUi(status) { return SHEET_WRITE_UI[status] || SHEET_WRITE_UI.retry_failed }
export function sheetWriteMark(status) { return sheetWriteUi(status).mark }
export function sheetWriteTone(status) { return sheetWriteUi(status).tone }

/** 行内 tooltip 与终态弹窗共用同一句文案：结构统一为「发生了什么 + 你要做什么」+ 原始原因 */
export function sheetWriteHint(f) {
  const reason = f.error_msg || '未知原因'
  if (f.status === 'rolled_back') {
    return `写表失败，已撤销本次状态变更。原因：${reason}`
  }
  if (f.status === 'rollback_abandoned') {
    // 成因由后端裁定（回滚器崩溃 / 守卫未过是两回事），前端不再自行断言
    return reason
  }
  return `写表失败，表中未写入。原因：${reason}`
}
