/**
 * 输入防抖 composable — 替代各处重复的 searchTimer + setTimeout 300ms 模式
 * 用法：const { debounced } = useDebounce(fn, 300)
 */
export function useDebounce(fn, delay = 300) {
  let timer = null
  const debounced = (...args) => {
    clearTimeout(timer)
    timer = setTimeout(() => fn(...args), delay)
  }
  return { debounced }
}
