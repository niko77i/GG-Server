<template>
  <div v-if="isAuthPage" class="full-page">
    <router-view />
  </div>
  <div v-else style="display:flex;height:100vh;overflow:hidden;">
    <AppSidebar />
    <div style="flex:1;padding:clamp(16px,2.5vw,32px);overflow-y:auto;background:#f5f7fa;">
      <router-view v-slot="{ Component }">
        <keep-alive>
          <component :is="Component" />
        </keep-alive>
      </router-view>
    </div>
    <GlobalTaskPanel />
  </div>
</template>

<script setup>
import { computed, onMounted, onUnmounted, watch, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useAuthStore } from './stores/auth'
import { useTaskStore } from './stores/taskRunner'
import AppSidebar from './components/AppSidebar.vue'
import GlobalTaskPanel from './components/GlobalTaskPanel.vue'
import { productsApi } from './api/products'
import { ElNotification, ElMessage } from 'element-plus'
import { MSG, broadcast, onMessage } from './utils/broadcast'

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()
const taskStore = useTaskStore()

const isAuthPage = computed(() => ['/login', '/register'].includes(route.path))

onMounted(async () => {
  auth.initFromStorage()
  if (auth.isLoggedIn) {
    await auth.fetchMe()
  }
  // 初始化全局任务追踪
  taskStore.init()
  taskStore.startPolling()
})

// ---------- 全局掉包通知轮询（所有页面生效） ----------
let _delistTimer = null
let _checking = false  // 防止并发重复弹窗
const _notifiedProductIds = new Set()
let _tgWarned = false  // Telegram 未配置提醒只弹一次

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

// ---------- 跨 Tab 同步：掉包通知 ----------
onMessage((msg) => {
  if (msg.type === MSG.DELIST_NOTIFIED) {
    const { product_id, type, reminder_count } = msg.payload
    // 与 checkDelistNotifications 中保持一致的 key 计算逻辑
    const key = type === 'reminder'
      ? `${product_id}-reminder-${reminder_count || 0}`
      : `${product_id}-first`
    _notifiedProductIds.add(key)
  }
  if (msg.type === MSG.DELIST_DISMISSED) {
    const productId = msg.payload?.product_id
    if (productId) _dismissRemoteProduct(productId)
  }
  // TASK_ADDED / TASK_UPDATED 由 taskStore 内部 _setupBroadcastListener 处理，此处不重复
})

// 远程 dismiss：关闭本地同名 ElNotification（需持有引用，key 为 product_id）
const _notifRefs = {}
function _dismissRemoteProduct(productId) {
  const ref = _notifRefs[productId]
  if (ref) { ref.close(); delete _notifRefs[productId] }
}

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

    // 有掉包通知但未配置 Telegram 用户名时，提醒一次
    if (notifications.length > 0 && !_tgWarned && !auth.user?.telegram_username) {
      _tgWarned = true
      ElMessage.warning({
        message: '检测到包掉包！请在个人信息页配置 Telegram 用户名以接收群组 @ 通知',
        duration: 8000,
        showClose: true,
      })
    }

    for (const n of notifications) {
      // reminder 用 reminder_count 区分，避免重复提醒被去重；key 为产品级
      const key = n.type === 'reminder'
        ? `${n.product_id}-reminder-${n.reminder_count || 0}`
        : `${n.product_id}-first`
      if (_notifiedProductIds.has(key)) continue
      _notifiedProductIds.add(key)
      // 通知其他 Tab 同步跳过此通知
      broadcast(MSG.DELIST_NOTIFIED, {
        product_id: n.product_id,
        type: n.type,
        reminder_count: n.reminder_count || 0,
      })

      const title = n.type === 'first' ? '⚠️ 检测到包已掉包' : '⏰ 掉包提醒'
      const lines = []
      if (n.product_name) lines.push(`【${n.product_name}】`)
      for (const s of [...new Set(n.series_names || [])]) lines.push(s)
      lines.push('请将包状态设置为"掉包"（点击跳转到对应包）')

      const notifInst = ElNotification({
        title,
        message: lines.join('\n'),
        type: 'warning',
        duration: 0,
        position: 'top-right',
        showClose: true,
        onClick: () => {
          router.push(`/accounts/products?highlight_pkgs=${(n.package_ids || []).join(',')}`)
        },
        onClose: async () => {
          try { await productsApi.dismissDelist(n.package_ids || []) } catch {}
          delete _notifRefs[n.product_id]
          broadcast(MSG.DELIST_DISMISSED, { product_id: n.product_id, package_ids: n.package_ids })
        }
      })
      // 持有引用以便远程 dismiss
      if (notifInst) _notifRefs[n.product_id] = notifInst
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
