<template>
  <div class="sidebar-wrap">
    <nav class="icon-rail">
      <div class="rail-brand" @click="selectTab(auth.effectivePlatform === 'fb' ? '/fb/products' : '/accounts')" title="首页">
        <svg width="22" height="22" viewBox="0 0 24 24" fill="none">
          <rect x="2" y="2" width="20" height="20" rx="4" stroke="#0891b2" stroke-width="1.5"/>
          <circle cx="12" cy="10" r="3" stroke="#0891b2" stroke-width="1.5"/>
          <path d="M7 18c0-2.8 2.2-5 5-5s5 2.2 5 5" stroke="#0891b2" stroke-width="1.5" stroke-linecap="round"/>
        </svg>
      </div>
      <!-- Developer 平台切换 -->
      <div v-if="auth.isDeveloper" class="platform-switch">
        <button class="plat-btn" :class="{ active: auth.currentPlatform === 'gg' }" @click="switchPlatform('gg')">GG</button>
        <button class="plat-btn" :class="{ active: auth.currentPlatform === 'fb' }" @click="switchPlatform('fb')">FB</button>
      </div>
      <div class="rail-icons">
        <button v-for="item in visibleNavItems" :key="item.key" class="rail-btn" :class="{ active: activeSection === item.key }" :title="item.label" @click="selectTab(item.key)">
          <span class="rail-emoji">{{ item.icon }}</span>
        </button>
      </div>
      <div class="rail-spacer" />
      <button class="rail-btn" title="个人信息" @click="router.push('/profile')">
        <span class="rail-emoji">👤</span>
      </button>
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

function switchPlatform(platform) {
  auth.setPlatform(platform)
  // 跳转到该平台的默认页面
  if (platform === 'fb') {
    router.push('/fb/products')
    activeSection.value = 'fb-accounts'
  } else {
    router.push('/accounts/products')
    activeSection.value = 'accounts'
  }
}

const detailOpen = ref(true); const activeSection = ref('accounts')
const ggNavItems = [
  { key: 'accounts', icon: '🏢', label: '账户管理', admin: true, sections: [{ title: '账户', items: [{ icon:'📦',label:'产品管理',path:'/accounts/products'},{ icon:'👤',label:'广告账户',path:'/accounts/ads'},{ icon:'🏢',label:'MCC管理',path:'/accounts/mcc'}]},{ title:'系统', items:[{ icon:'⚙',label:'设置',path:'/accounts/settings'}]}]},
  { key: 'youtube', icon: '📺', label: '视频管理', sections: [{ title: '视频', items: [{ icon:'▶',label:'视频展示',path:'/youtube/view'},{ icon:'📝',label:'文案展示',path:'/youtube/copywriting'},{ icon:'➕',label:'导入视频或文案',path:'/youtube/import'},{ icon:'🏷',label:'标签配置',path:'/youtube/config'}]}]},
  { key: 'media', icon: '🎬', label: '媒体工具', sections: [{ title: '媒体', items: [{ icon:'🖼',label:'爬取&视频',path:'/media'}]}]},
  { key: 'toolkit', icon: '🧰', label: '工具集', sections: [{ title: '工具', items: [{ icon:'📊',label:'做表数据',path:'/toolkit/zuobiao'},{ icon:'🎵',label:'音频替换',path:'/toolkit/audio'},{ icon:'🌐',label:'翻译工具',path:'/toolkit/translate'}]}]},
  { key: 'analysis', icon: '📈', label: '数据分析', sections: [{ title: '分析', items: [{ icon:'📊',label:'数据看板',path:'/analysis'}]}]},
  { key: 'data-manage', icon: '📋', label: '数据管理', sections: [{ title: '数据', items: [{ icon:'📋',label:'数据管理',path:'/data-manage'}]}]},
  { key: 'admin', icon: '🏴', label: '管理', admin: true, sections: [{ title: '管理', items: [{ icon:'👥',label:'用户管理',path:'/admin/users'},{ icon:'⏰',label:'定时任务',path:'/admin/scheduler',developer:true }] }]},
]

const fbNavItems = [
  { key: 'fb-accounts', icon: '🏢', label: '账户管理', sections: [
    { title: '账户', items: [
      { icon:'📦',label:'产品管理',path:'/fb/products'},
      { icon:'👤',label:'广告账户',path:'/fb/accounts'},
      { icon:'🏢',label:'BM管理',path:'/fb/bms'},
      { icon:'📊',label:'像素管理',path:'/fb/pixels'},
    ]},
    { title: '系统', items: [
      { icon:'⚙',label:'FB设置',path:'/fb/settings'},
    ]}
  ]},
  { key: 'fb-extract', icon: '📋', label: '数据提取', sections: [{ title: '提取', items: [{ icon:'📥',label:'FB数据提取',path:'/fb/extract'}]}]},
  { key: 'fb-data', icon: '📊', label: '数据管理', sections: [{ title: '数据', items: [{ icon:'📋',label:'FB数据管理',path:'/fb/data-manage'}]}]},
  { key: 'analysis', icon: '📈', label: '数据分析', sections: [{ title: '分析', items: [{ icon:'📊',label:'数据看板',path:'/analysis'}]}]},
  { key: 'admin', icon: '🏴', label: '管理', admin: true, sections: [{ title: '管理', items: [{ icon:'👥',label:'用户管理',path:'/admin/users'},{ icon:'⏰',label:'定时任务',path:'/admin/scheduler',developer:true }] }]},
]

const currentNavItems = computed(() => auth.effectivePlatform === 'fb' ? fbNavItems : ggNavItems)

const visibleNavItems = computed(() => currentNavItems.value.filter(n => {
  if (n.key === 'accounts' || n.key === 'fb-accounts') return auth.canAccessProducts
  if (n.admin) return auth.isAdmin
  return true
}))
const currentNav = computed(() => currentNavItems.value.find(n => n.key === activeSection.value))
const detailTitle = computed(() => activeSection.value === 'settings' ? '设置' : (currentNav.value?.label || ''))
const settingsPath = computed(() => auth.effectivePlatform === 'fb' ? '/fb/settings' : '/accounts/settings')
const detailSections = computed(() => {
  if (activeSection.value === 'settings') return [{ title: '系统', items: [{ icon:'⚙',label:'设置',path:settingsPath.value}] }]
  let sections = currentNav.value?.sections || []
  // viewer 只能看到产品管理的侧边栏入口
  if (auth.isViewer && activeSection.value === 'accounts') {
    return sections.map(sec => ({
      ...sec,
      items: sec.items.filter(item => item.path === '/accounts/products')
    })).filter(sec => sec.items.length > 0)
  }
  // 非 developer 看不到 developer 专属菜单项
  if (!auth.isDeveloper) {
    sections = sections.map(sec => ({
      ...sec,
      items: sec.items.filter(item => !item.developer)
    })).filter(sec => sec.items.length > 0)
  }
  // 非 admin 看不到 admin 专属菜单项
  if (!auth.isAdmin) {
    sections = sections.map(sec => ({
      ...sec,
      items: sec.items.filter(item => !item.admin)
    })).filter(sec => sec.items.length > 0)
  }
  return sections
})
function isActive(p) { return route.path === p || route.path.startsWith(p + '/') }
function selectTab(key) {
  if (key === 'settings') { activeSection.value = 'settings'; detailOpen.value = true; router.push(settingsPath.value); return }
  activeSection.value = key; detailOpen.value = true
  const nav = currentNavItems.value.find(n => n.key === key)
  if (nav) { const f = nav.sections[0]?.items[0]; if (f) router.push(f.path) }
}
function navigate(path) { router.push(path) }
watch(() => route.path, (p) => {
  const items = currentNavItems.value
  for (const item of items) {
    // 优先用子项的具体路径匹配（解决 FB 菜单全部 /fb 前缀冲突）
    const subPaths = item.sections?.flatMap(s => s.items.map(i => i.path)) || []
    if (subPaths.some(sp => p === sp || p.startsWith(sp + '/'))) {
      activeSection.value = item.key; return
    }
  }
  if (p.startsWith('/accounts/settings') || p.startsWith('/fb/settings')) activeSection.value = 'settings'
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
.platform-switch { display:flex;flex-direction:column;gap:2px;margin:4px 0; }
.plat-btn { width:40px;height:24px;border:1px solid #e5e7eb;background:transparent;border-radius:6px;cursor:pointer;font-size:10px;font-weight:600;color:#9ca3af;transition:all .15s;padding:0; }
.plat-btn:hover { border-color:#0891b2;color:#0891b2; }
.plat-btn.active { background:#0891b2;color:#fff;border-color:#0891b2; }
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
