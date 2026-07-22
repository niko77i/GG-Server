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

/**
 * 带缓存的 dedupLoader：在 ms 内已有数据则跳过加载。
 * 用于页面切换时避免重复请求（keep-alive 场景）。
 *
 * @param {object} store - Pinia store 实例
 * @param {string} key - 唯一标识
 * @param {number} ttlMs - 缓存有效期（毫秒），默认 2 分钟
 * @param {Function} loaderFn - 实际加载函数
 * @param {Function} hasDataFn - 检查是否已有有效数据的函数，默认检查 store[key]
 */
export function cachedLoader(store, key, ttlMs, loaderFn, hasDataFn) {
  const tsKey = `_${key}FetchedAt`
  const now = Date.now()
  // 有数据且未过期 → 跳过
  if (store[tsKey] && (now - store[tsKey]) < (ttlMs || 120000)) {
    const hasData = hasDataFn ? hasDataFn() : (Array.isArray(store[key]) ? store[key].length > 0 : !!store[key])
    if (hasData) return Promise.resolve({ from_cache: true })
  }
  return dedupLoader(store, key, () => {
    return loaderFn().then(res => {
      store[tsKey] = Date.now()
      return res
    })
  })
}
