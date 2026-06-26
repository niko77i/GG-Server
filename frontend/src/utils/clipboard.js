/**
 * 复制文本到剪切板。
 * - 安全上下文（HTTPS/localhost）→ 使用 Clipboard API
 * - 非安全上下文（HTTP/打包 EXE）→ 直接用 execCommand 降级
 * @param {string} text 要复制的文本
 * @returns {Promise<void>}
 */
export function copyToClipboard(text) {
  if (!text) return Promise.resolve()

  // 非安全上下文：跳过 Clipboard API，直接用 execCommand（避免 API 存在但不生效）
  if (!window.isSecureContext) {
    return copyViaExecCommand(text)
  }

  // 安全上下文：优先 Clipboard API
  return navigator.clipboard.writeText(text).catch(() => copyViaExecCommand(text))
}

function copyViaExecCommand(text) {
  return new Promise((resolve, reject) => {
    try {
      const ta = document.createElement('textarea')
      ta.value = text
      // 关键：必须可见且在 DOM 中，但用 opacity 隐藏避免闪烁
      ta.style.cssText = 'position:fixed;top:0;left:0;opacity:0;pointer-events:none;z-index:-1;'
      document.body.appendChild(ta)
      ta.focus()
      ta.select()
      const ok = document.execCommand('copy')
      document.body.removeChild(ta)
      if (ok) {
        resolve()
      } else {
        reject(new Error('execCommand 返回 false'))
      }
    } catch (e) {
      reject(e)
    }
  })
}
