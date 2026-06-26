<template>
  <div class="sidebar-wrap">
    <nav class="icon-rail">
      <div class="rail-brand" @click="selectTab('/accounts')" title="首页">
        <svg width="22" height="22" viewBox="0 0 24 24" fill="none">
          <rect x="2" y="2" width="20" height="20" rx="4" stroke="#0891b2" stroke-width="1.5"/>
          <circle cx="12" cy="10" r="3" stroke="#0891b2" stroke-width="1.5"/>
          <path d="M7 18c0-2.8 2.2-5 5-5s5 2.2 5 5" stroke="#0891b2" stroke-width="1.5" stroke-linecap="round"/>
        </svg>
      </div>
      <div class="rail-icons">
        <button v-for="item in visibleNavItems" :key="item.key" class="rail-btn" :class="{ active: activeSection === item.key }" :title="item.label" @click="selectTab(item.key)">
          <span class="rail-emoji">{{ item.icon }}</span>
        </button>
      </div>
      <div class="rail-spacer" />
      <button class="rail-btn" :class="{ active: activeSection === 'settings' }" title="设置" @click="selectTab('settings')">
        <span class="rail-emoji">⚙</span>
      </button>
    
      <button class="rail-btn" title="退出登录" @click="handleLogout" style="margin-top:4px;">
        <span class="rail-emoji">🚪</span>
      </button>
    </nav>
    <aside class="detail-panel" :class="{ collapsed: !detailOpen }" v-show="detailOpen">
      <div class="detail-header">
        <span class="detail-title">{{ detailTitle }}</span>
        <button class="collapse-btn" @click="detailOpen = false" title="收起">◀</button>
      </div>
      <div class="detail-sections">
        <div v-for="sec in detailSections" :key="sec.title" class="detail-section">
          <div class="detail-section-title">{{ sec.title }}</div>
          <button v-for="sub in sec.items" :key="sub.path" class="detail-item" :class="{ active: isActive(sub.path) }" @click="navigate(sub.path)">{{ sub.icon }} {{ sub.label }}</button>
        </div>
      </div>
    </aside>
  </div>
</template>

<script setup>
import { ref, computed, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
const route = useRoute(); const router = useRouter()
import { useAuthStore } from '../stores/auth'
const auth = useAuthStore()

function handleLogout() {
  auth.logout()
  router.push('/login')
}
const detailOpen = ref(true); const activeSection = ref('accounts')
const navItems = [
  { key: 'accounts', icon: '🏢', label: '账户管理', admin: true, sections: [{ title: '账户', items: [{ icon:'📦',label:'产品管理',path:'/accounts/products'},{ icon:'👤',label:'广告账户',path:'/accounts/ads'},{ icon:'🏢',label:'MCC管理',path:'/accounts/mcc'}]},{ title:'系统', items:[{ icon:'⚙',label:'设置',path:'/accounts/settings'}]}]},
  { key: 'youtube', icon: '📺', label: '视频管理', sections: [{ title: '视频', items: [{ icon:'▶',label:'视频展示',path:'/youtube/view'},{ icon:'📝',label:'文案展示',path:'/youtube/copywriting'},{ icon:'➕',label:'导入视频或文案',path:'/youtube/import'},{ icon:'🏷',label:'标签配置',path:'/youtube/config'}]}]},
  { key: 'scrape', icon: '📥', label: '图片爬取', sections: [{ title: '爬取', items: [{ icon:'🖼',label:'爬取图片',path:'/scrape'}]}]},
  { key: 'video', icon: '🎬', label: 'AI视频生成', sections: [{ title: '视频', items: [{ icon:'🎬',label:'视频生成',path:'/video'}]}]},
  { key: 'toolkit', icon: '🧰', label: '工具集', sections: [{ title: '工具', items: [{ icon:'📊',label:'做表数据',path:'/toolkit/zuobiao'},{ icon:'🎵',label:'音频替换',path:'/toolkit/audio'},{ icon:'🌐',label:'翻译工具',path:'/toolkit/translate'}]}]},
  { key: 'admin', icon: '🏴', label: '管理', admin: true, sections: [{ title: '管理', items: [{ icon:'⚙️',label:'用户管理',path:'/admin/users'}]}]},
]
  const visibleNavItems = computed(() => navItems.filter(n => !n.admin || auth.isAdmin))
const currentNav = computed(() => navItems.find(n => n.key === activeSection.value))
const detailTitle = computed(() => activeSection.value === 'settings' ? '设置' : (currentNav.value?.label || ''))
const detailSections = computed(() => {
  if (activeSection.value === 'settings') return [{ title: '系统', items: [{ icon:'⚙',label:'账户设置',path:'/accounts/settings'}] }]
  return currentNav.value?.sections || []
})
function isActive(p) { return route.path === p || route.path.startsWith(p + '/') }
function selectTab(key) {
  if (key === 'settings') { activeSection.value = 'settings'; detailOpen.value = true; router.push('/accounts/settings'); return }
  activeSection.value = key; detailOpen.value = true
  const nav = navItems.find(n => n.key === key)
  if (nav) { const f = nav.sections[0]?.items[0]; if (f) router.push(f.path) }
}
function navigate(path) { router.push(path) }
watch(() => route.path, (p) => {
  for (const item of navItems) { if (p.startsWith('/' + item.key) || (item.key === 'accounts' && p.startsWith('/accounts'))) { activeSection.value = item.key; return } }
  if (p.startsWith('/accounts/settings')) activeSection.value = 'settings'
}, { immediate: true })
</script>

<style scoped>
.sidebar-wrap { display:flex;height:100vh;position:sticky;top:0;flex-shrink:0;z-index:100; }
.icon-rail { width:56px;background:#f8f9fa;border-right:1px solid #e5e7eb;display:flex;flex-direction:column;align-items:center;padding:12px 0;gap:4px; }
.rail-brand { width:36px;height:36px;display:flex;align-items:center;justify-content:center;cursor:pointer;border-radius:8px;transition:background .15s;margin-bottom:8px; }
.rail-brand:hover { background:rgba(0,0,0,0.05); }
.rail-icons { display:flex;flex-direction:column;gap:2px; }
.rail-btn { width:40px;height:40px;border:none;background:transparent;border-radius:8px;cursor:pointer;display:flex;align-items:center;justify-content:center;transition:all .15s;position:relative;padding:0; }
.rail-btn:hover { background:rgba(0,0,0,0.06); }
.rail-btn.active { background:rgba(8,145,178,0.12); }
.rail-btn.active::before { content:'';position:absolute;left:0;top:50%;transform:translateY(-50%);width:3px;height:20px;background:#0891b2;border-radius:0 3px 3px 0; }
.rail-emoji { font-size:18px;line-height:1; }
.rail-spacer { flex:1; }
.detail-panel { width:200px;background:#fff;border-right:1px solid #e5e7eb;display:flex;flex-direction:column;overflow:hidden;transition:width .2s ease; }
.detail-panel.collapsed { width:0;border-right:none; }
.detail-header { display:flex;align-items:center;justify-content:space-between;padding:16px 16px 12px;border-bottom:1px solid #f3f4f6; }
.detail-title { font-size:15px;font-weight:600;color:#111827; }
.collapse-btn { width:28px;height:28px;border:none;background:transparent;border-radius:6px;cursor:pointer;font-size:11px;color:#9ca3af;display:flex;align-items:center;justify-content:center;transition:all .15s; }
.collapse-btn:hover { background:rgba(0,0,0,0.05);color:#374151; }
.detail-sections { flex:1;overflow-y:auto;padding:12px 8px;display:flex;flex-direction:column;gap:16px; }
.detail-section-title { font-size:11px;font-weight:500;color:#9ca3af;text-transform:uppercase;letter-spacing:.05em;padding:0 8px 4px; }
.detail-item { width:100%;border:none;background:transparent;border-radius:6px;padding:8px 12px;cursor:pointer;font-size:13px;color:#374151;text-align:left;transition:all .1s;display:block; }
.detail-item:hover { background:rgba(0,0,0,0.04); }
.detail-item.active { background:rgba(8,145,178,0.08);color:#0891b2;font-weight:500; }
</style>
