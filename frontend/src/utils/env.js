/** 当前是否通过 localhost/127.0.0.1 访问（本机） */
export function isLocalhost() {
  return ['localhost', '127.0.0.1', '::1'].includes(window.location.hostname)
}
