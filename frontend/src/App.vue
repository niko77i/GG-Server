<template>
  <div v-if="isAuthPage" class="full-page">
    <router-view />
  </div>
  <div v-else style="display:flex;height:100vh;overflow:hidden;">
    <AppSidebar />
    <div style="flex:1;padding:clamp(16px,2.5vw,32px);overflow-y:auto;background:#f5f7fa;">
      <router-view />
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, onUnmounted, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useAuthStore } from './stores/auth'
import AppSidebar from './components/AppSidebar.vue'
import { productsApi } from './api/products'
import { ElNotification } from 'element-plus'

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()

const isAuthPage = computed(() => ['/login', '/register'].includes(route.path))

onMounted(async () => {
  auth.initFromStorage()
  if (auth.isLoggedIn) {
    await auth.fetchMe()
  }
})

// ---------- 全局掉包通知轮询（所有页面生效） ----------
let _delistTimer = null
let _checking = false  // 防止并发重复弹窗
const _notifiedPkgIds = new Set()

watch(() => auth.isLoggedIn, (loggedIn) => {
  if (loggedIn) startDelistPolling()
  else stopDelistPolling()
}, { immediate: true })

onUnmounted(() => {
  stopDelistPolling()
  window.removeEventListener('delist-check-completed', checkDelistNotifications)
})

// 监听手动触发事件，立即执行通知检查
window.addEventListener('delist-check-completed', checkDelistNotifications)

async function startDelistPolling() {
  if (_delistTimer) return  // 已经在轮询中
  await checkDelistNotifications()
  _delistTimer = setInterval(checkDelistNotifications, 30000)
}

function stopDelistPolling() {
  if (_delistTimer) { clearInterval(_delistTimer); _delistTimer = null }
}

async function checkDelistNotifications() {
  if (_checking) return  // 上一次检查未完成，跳过
  _checking = true
  try {
    const res = await productsApi.getPendingDelist()
    const notifications = res.notifications || []
    for (const n of notifications) {
      // reminder 用 reminder_count 区分，避免重复提醒被去重
      const key = n.type === 'reminder'
        ? `${n.package_id}-reminder-${n.reminder_count || 0}`
        : `${n.package_id}-first`
      if (_notifiedPkgIds.has(key)) continue
      _notifiedPkgIds.add(key)

      const title = n.type === 'first' ? '⚠️ 检测到包已掉包' : '⏰ 掉包提醒'
      const productInfo = n.product_name ? `【${n.product_name}】` : ''
      const pkgInfo = n.series_name ? `${n.series_name} / ${n.package_name}` : n.package_name

      ElNotification({
        title,
        message: `${productInfo}${pkgInfo}\n请将包状态设置为"掉包"（点击跳转到对应包）`,
        type: 'warning',
        duration: 0,
        position: 'top-right',
        showClose: true,
        onClick: () => {
          router.push(`/accounts/products?highlight_pkg=${n.package_id}`)
        },
        onClose: async () => {
          try { await productsApi.dismissDelist(n.package_id) } catch {}
        }
      })
    }
  } catch {} finally {
    _checking = false
  }
}
</script>

<style>
.full-page {
  height: 100vh;
  overflow: hidden;
}
</style>
