/**
 * 分页 composable — 替代各处重复的 el-pagination + pageSize el-select 模式
 * 用法：const { page, pageSize, total, onPageChange, onSizeChange } = usePagination(loadFn)
 */
import { ref } from 'vue'

export function usePagination(loadFn, defaultSize = 20) {
  const page = ref(1)
  const pageSize = ref(defaultSize)

  function onPageChange(p) {
    page.value = p
    loadFn()
  }

  function onSizeChange(size) {
    pageSize.value = size
    page.value = 1
    loadFn()
  }

  function reset() {
    page.value = 1
    loadFn()
  }

  return { page, pageSize, onPageChange, onSizeChange, reset }
}
