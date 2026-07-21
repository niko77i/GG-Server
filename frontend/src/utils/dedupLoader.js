/**
 * 为 Pinia store action 创建防重复加载包装。
 * 在上一请求完成前，重复调用返回同一个 Promise。
 *
 * 用法：
 *   async loadData() {
 *     return dedupLoader(this, 'data', () => api.list().then(res => { this.data = res }))
 *   }
 */
export function dedupLoader(store, key, loaderFn) {
  const loadingKey = `_${key}Loading`
  const promiseKey = `_${key}LastPromise`
  if (store[loadingKey]) return store[promiseKey]
  store[loadingKey] = true
  const promise = loaderFn().finally(() => { store[loadingKey] = false })
  store[promiseKey] = promise
  return promise
}
