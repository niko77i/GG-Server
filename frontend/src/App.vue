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
import { ttApi } from './api/tt'
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

// ---------- 全局掉包通知轮询（GG + TT 双平台，所有页面生效） ----------
let _delistTimer = null
let _checking = false  // 防止并发重复弹窗
const _notifiedProductIds = new Set()
const _tgWarned = new Set()  // Telegram 未配置提醒每个平台只弹一次（'gg' / 'tt'）

// 各平台的 API 句柄与跳转目标（key 为通知的 platform 字段）
const _PLATFORM_API = { gg: productsApi, tt: ttApi }
const _PLATFORM_PRODUCTS_PATH = { gg: '/accounts/products', tt: '/tt/products' }
function _platOf(n) { return n.platform === 'tt' ? 'tt' : 'gg' }

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
    const { product_id, type, reminder_count, platform } = msg.payload
    // 与 checkDelistNotifications 中保持一致的 key 计算逻辑（缺省 gg，兼容旧 Tab）
    const plat = platform === 'tt' ? 'tt' : 'gg'
    const key = type === 'reminder'
      ? `${plat}-${product_id}-reminder-${reminder_count || 0}`
      : `${plat}-${product_id}-first`
    _notifiedProductIds.add(key)
  }
  if (msg.type === MSG.DELIST_DISMISSED) {
    const { product_id, platform } = msg.payload || {}
    if (product_id) _dismissRemoteProduct(platform === 'tt' ? 'tt' : 'gg', product_id)
  }
  // TASK_ADDED / TASK_UPDATED 由 taskStore 内部 _setupBroadcastListener 处理，此处不重复
})

// 远程 dismiss：按「平台 + 产品」关闭本地对应的 ElNotification。
// _notifRefs 以完整通知 key 为键（如 "gg-5-first"、"tt-5-reminder-0"），
// 故这里用前缀匹配关闭该产品下所有类型的通知。
const _notifRefs = {}
function _dismissRemoteProduct(plat, productId) {
  const prefix = `${plat}-${productId}-`
  for (const key of Object.keys(_notifRefs)) {
    if (key.startsWith(prefix)) {
      _notifRefs[key].close()
      delete _notifRefs[key]
    }
  }
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
    // GG + TT 双平台并行轮询：任一失败（如平台无权访问）不影响另一方
    const [ggRes, ttRes] = await Promise.allSettled([
      productsApi.getPendingDelist(),
      ttApi.getPendingDelist(),
    ])
    const notifications = [
      ...(ggRes.status === 'fulfilled' ? (ggRes.value?.notifications || []) : [])
        .map(n => ({ ...n, platform: 'gg' })),
      ...(ttRes.status === 'fulfilled' ? (ttRes.value?.notifications || []) : [])
        .map(n => ({ ...n, platform: 'tt' })),
    ]

    for (const n of notifications) {
      const plat = _platOf(n)
      // 有掉包通知但未配置 Telegram 用户名时，每个平台各提醒一次
      if (!_tgWarned.has(plat) && !auth.user?.telegram_username) {
        _tgWarned.add(plat)
        ElMessage.warning({
          message: '检测到包掉包！请在个人信息页配置 Telegram 用户名以接收群组 @ 通知',
          duration: 8000,
          showClose: true,
        })
      }

      // reminder 用 reminder_count 区分，避免重复提醒被去重；
      // key 含平台前缀，避免 GG 与 TT 的 product_id 撞号误去重
      const key = n.type === 'reminder'
        ? `${plat}-${n.product_id}-reminder-${n.reminder_count || 0}`
        : `${plat}-${n.product_id}-first`
      if (_notifiedProductIds.has(key)) continue
      _notifiedProductIds.add(key)
      // 通知其他 Tab 同步跳过此通知
      broadcast(MSG.DELIST_NOTIFIED, {
        product_id: n.product_id,
        type: n.type,
        reminder_count: n.reminder_count || 0,
        platform: plat,
      })

      const baseTitle = n.type === 'first' ? '⚠️ 检测到包已掉包' : '⏰ 掉包提醒'
      const title = plat === 'tt' ? `[TT] ${baseTitle}` : baseTitle
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
          router.push(`${_PLATFORM_PRODUCTS_PATH[plat]}?highlight_pkgs=${(n.package_ids || []).join(',')}`)
        },
        onClose: async () => {
          try { await _PLATFORM_API[plat].dismissDelist(n.package_ids || []) } catch {}
          delete _notifRefs[key]
          broadcast(MSG.DELIST_DISMISSED, {
            product_id: n.product_id, package_ids: n.package_ids, platform: plat,
          })
        }
      })
      // 持有引用以便远程 dismiss
      if (notifInst) _notifRefs[key] = notifInst
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
