/**
 * BroadcastChannel 封装 — 跨标签页/窗口状态同步
 *
 * 使用 BroadcastChannel API 在同源的所有 Tab 之间广播消息。
 * 不支持  的浏览器静默降级（功能退化到单 Tab 模式）。
 */

const CHANNEL_NAME = 'gg-server-sync'

/** 消息类型 */
export const MSG = {
  TASK_ADDED: 'task_added',
  TASK_UPDATED: 'task_updated',
  DELIST_NOTIFIED: 'delist_notified',
  DELIST_DISMISSED: 'delist_dismissed',
}

// ---------- Channel 单例 ----------

let _channel = null
function getChannel() {
  if (_channel === null) {
    try {
      _channel = new BroadcastChannel(CHANNEL_NAME)
    } catch {
      _channel = undefined // undefined = 尝试过但不支持
    }
  }
  return _channel || null
}

// ---------- Tab 唯一 ID ----------

let _tabId = null
export function tabId() {
  if (!_tabId) {
    _tabId = sessionStorage.getItem('_gg_tabId')
    if (!_tabId) {
      _tabId = crypto.randomUUID ? crypto.randomUUID() : Date.now().toString(36) + Math.random().toString(36).slice(2)
      sessionStorage.setItem('_gg_tabId', _tabId)
    }
  }
  return _tabId
}

// ---------- 发送 ----------

/**
 * 向其他 Tab 广播消息
 * @param {string} type - 消息类型 (MSG.*)
 * @param {*} payload - 消息数据
 */
export function broadcast(type, payload) {
  try {
    const ch = getChannel()
    if (ch) {
      ch.postMessage({ type, payload, tabId: tabId(), ts: Date.now() })
    }
  } catch { /* 静默降级 */ }
}

// ---------- 接收 ----------

/**
 * 监听来自其他 Tab 的消息（自动过滤自身发出的消息）
 * @param {(msg: {type: string, payload: any, tabId: string, ts: number}) => void} handler
 */
export function onMessage(handler) {
  try {
    const ch = getChannel()
    if (ch) {
      ch.addEventListener('message', (e) => {
        // 忽略自己发出的消息
        if (!e.data || e.data.tabId === tabId()) return
        handler(e.data)
      })
    }
  } catch { /* 静默降级 */ }
}
