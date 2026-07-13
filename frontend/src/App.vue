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
import { useRoute } from 'vue-router'
import { useAuthStore } from './stores/auth'
import AppSidebar from './components/AppSidebar.vue'
import { productsApi } from './api/products'
import { ElNotification } from 'element-plus'

const route = useRoute()
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
const _notifiedPkgIds = new Set()

watch(() => auth.isLoggedIn, (loggedIn) => {
  if (loggedIn) startDelistPolling()
  else stopDelistPolling()
}, { immediate: true })

onUnmounted(() => stopDelistPolling())

async function startDelistPolling() {
  if (_delistTimer) return  // 已经在轮询中
  await checkDelistNotifications()
  _delistTimer = setInterval(checkDelistNotifications, 30000)
}

function stopDelistPolling() {
  if (_delistTimer) { clearInterval(_delistTimer); _delistTimer = null }
}

async function checkDelistNotifications() {
  try {
    const res = await productsApi.getPendingDelist()
    const notifications = res.notifications || []
    for (const n of notifications) {
      const key = `${n.package_id}-${n.type}`
      if (_notifiedPkgIds.has(key)) continue
      _notifiedPkgIds.add(key)

      const title = n.type === 'first' ? '⚠️ 检测到包已掉包' : '⏰ 掉包提醒'
      const productInfo = n.product_name ? `【${n.product_name}】` : ''
      const pkgInfo = n.series_name ? `${n.series_name} / ${n.package_name}` : n.package_name

      ElNotification({
        title,
        message: `${productInfo}${pkgInfo}\n请将包状态设置为"掉包"`,
        type: 'warning',
        duration: 0,
        position: 'top-right',
        showClose: true,
        onClose: async () => {
          try { await productsApi.dismissDelist(n.package_id) } catch {}
        }
      })
    }
  } catch {}
}
</script>

<style>
.full-page {
  height: 100vh;
  overflow: hidden;
}
</style>
