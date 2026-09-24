<template>
  <el-card class="product-card" style="margin-bottom:12px;" :class="{ 'is-paused': product.status === 'paused' }">
    <template #header>
      <div style="display:flex;justify-content:space-between;align-items:center;cursor:pointer;" @click="expanded = !expanded">
        <div style="display:flex;align-items:center;gap:12px;">
          <span :style="{ width:'8px',height:'8px',borderRadius:'50%',background: product.status === 'paused' ? '#dc2626' : '#059669' }"></span>
          <strong>{{ product.product_name }}</strong>
          <el-button v-if="!product.is_archived && canEdit" size="small" type="warning" plain :loading="checkingDelist" @click.stop="checkDelist">
            {{ checkingDelist ? '检测中...' : '🔍 是否掉包' }}
          </el-button>
          <el-tag v-if="product.sales_person_name" size="small" type="success">💼 {{ product.sales_person_name }}</el-tag>
          <el-tag v-if="product.kpi" size="small" type="warning">{{ product.kpi }}</el-tag>
          <el-tag v-if="product.region" size="small" type="primary">{{ product.region }}</el-tag>
          <el-tag v-if="product.customer" size="small" type="success">👤 {{ product.customer }}</el-tag>
          <el-tooltip v-if="product.bc" placement="top">
            <template #content>
              <div>🏢 {{ product.bc.name }}</div>
              <div v-if="product.bc.bc_id">🆔 {{ product.bc.bc_id }}</div>
            </template>
            <el-tag size="small" type="info">🏢 {{ product.bc.name }}</el-tag>
          </el-tooltip>
          <el-tooltip v-if="product.runners && product.runners.length" placement="top">
            <template #content>
              <div v-for="r in product.runners" :key="r.id">{{ r.display_name || r.username }}</div>
            </template>
            <el-tag size="small" type="info">🏃 {{ product.runners.length }}人</el-tag>
          </el-tooltip>
          <el-tooltip content="复制系列名时的后缀" placement="top">
            <el-input v-model="productSuffix" size="small" style="width:80px;" placeholder="后缀" @click.stop @keydown.enter.stop />
          </el-tooltip>
        </div>
        <div style="display:flex;gap:4px;">
          <template v-if="product.is_archived">
            <el-button v-if="canEdit" size="small" type="success" @click.stop="$emit('restore', product.id)">恢复</el-button>
          </template>
          <template v-else>
            <el-button v-if="canEdit" size="small" @click.stop="$emit('toggle-pause', {id: product.id, paused: product.status !== 'paused'})">
              {{ product.status === 'paused' ? '▶' : '⏸' }}
            </el-button>
            <el-button v-if="canEdit" size="small" @click.stop="$emit('edit', product.id)">✏️</el-button>
            <el-button v-if="canEdit" size="small" @click.stop="$emit('add-pkg', product.id)" type="success">➕包</el-button>
            <el-button v-if="canEdit" size="small" @click.stop="$emit('del', product.id)" type="danger">🗑</el-button>
          </template>
          <span style="margin-left:4px;color:#888;">{{ expanded ? '▲' : '▼' }}</span>
        </div>
      </div>

      <!-- 展开后批量操作栏 -->
      <div v-show="expanded" style="display:flex;justify-content:space-between;align-items:center;padding:8px 0 0;margin-bottom:-10px;flex-wrap:wrap;gap:6px;">
        <span style="display:flex;align-items:center;gap:6px;flex-wrap:wrap;">
          <el-tag size="small" type="info" :effect="filterStatus === 'all' ? 'dark' : 'light'" style="cursor:pointer;" @click.stop="filterStatus = 'all'">
            {{ packages.length }} 全部
          </el-tag>
          <template v-for="(cnt, key) in pkgCounts" :key="key">
            <el-tag v-if="cnt > 0" size="small" :type="statusTagType(key)"
              :effect="filterStatus === key ? 'dark' : 'light'"
              style="cursor:pointer;" @click.stop="filterStatus = key">
              {{ cnt }} {{ statusLabel(key) }}
            </el-tag>
          </template>
          <el-button size="small" text @click.stop="cycleNameSort">{{ nameSortLabel }}</el-button>
          <el-button v-if="nameSort !== 'default'" size="small" text type="warning" @click.stop="resetNameSort">恢复默认排序</el-button>
        </span>
        <span style="display:flex;align-items:center;gap:6px;">
          <el-button size="small" text @click.stop="toggleAll">{{ allChecked ? '☑ 取消全选' : '☑ 全选' }}</el-button>
          <span style="font-size:11px;color:#888;">已选 {{ checkedIds.length }} 个</span>
          <el-button v-if="checkedIds.length" size="small" text type="info" @click.stop="clearSelection">✕ 取消选择</el-button>
          <el-select v-if="checkedIds.length && canEdit" :model-value="''" @change="v => batchStatusChange(v)" size="small" style="width:110px;" placeholder="批量改状态">
            <el-option label="正常" value="normal" /><el-option label="没事件" value="no_events" /><el-option label="暂停" value="paused" /><el-option label="掉包" value="dropped" /><el-option label="拒登" value="rejected" />
          </el-select>
          <el-button v-if="checkedIds.length" size="small" @click.stop="batchCopyLinks" type="primary">📋 复制链接</el-button>
          <el-button v-if="checkedIds.length && canEdit" size="small" @click.stop="batchDelPkgs" type="danger">🗑 批量删除</el-button>
        </span>
      </div>
    </template>

    <div v-show="expanded">
      <div v-for="pkg in filteredPackages" :key="pkg.id" :id="'pkg-' + pkg.id"
        class="pkg-row"
        :class="{ 'pkg-row--paused': normalizeStatus(pkg.status) === 'paused', 'pkg-row--no-events': normalizeStatus(pkg.status) === 'no_events', 'pkg-row--dropped': normalizeStatus(pkg.status) === 'dropped', 'pkg-row--delisted': pkg.is_delisted && normalizeStatus(pkg.status) !== 'dropped' }">
        <div style="display:flex;align-items:center;gap:6px;flex:1;min-width:0;overflow:hidden;">
          <input type="checkbox" :checked="checkedIds.includes(pkg.id)" @mousedown="shiftDown = $event.shiftKey" @change="onPkgChange(pkg, $event)" style="width:auto;flex-shrink:0;" />
          <el-tag :type="pkg.type === 'pwa' ? 'warning' : 'primary'" size="small" style="flex-shrink:0;">{{ pkg.type === 'pwa' ? 'PWA' : '跑包' }}</el-tag>
          <span style="font-weight:600;white-space:nowrap;flex-shrink:0;cursor:pointer;" @click.stop="copySeriesName(pkg)" :title="'点击复制'">{{ pkg.series_name || '-' }}</span>
          <span v-if="pkg.type !== 'pwa'" style="color:#ccc;flex-shrink:0;">│</span>
          <span v-if="pkg.type !== 'pwa'" style="font-family:monospace;cursor:pointer;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;" @click.stop="copy(pkg.package_name)">{{ pkg.package_name }}</span>
          <span style="color:#ccc;flex-shrink:0;" v-if="pkg.url">│</span>
          <span v-if="pkg.url" style="font-size:11px;color:var(--el-color-primary);overflow:hidden;text-overflow:ellipsis;white-space:nowrap;cursor:pointer;" @click.stop="copy(pkg.url)">{{ pkg.url }}</span>
          <a v-if="pkg.url" :href="pkg.url" target="_blank" style="font-size:11px;text-decoration:none;flex-shrink:0;" @click.stop>🔗</a>
        </div>
        <span style="font-size:11px;color:#888;white-space:nowrap;flex-shrink:0;margin:0 8px;">{{ pkg.created_at || '' }}</span>
        <div style="display:flex;gap:4px;flex-shrink:0;">
          <el-select v-if="canEdit" :model-value="normalizeStatus(pkg.status)" @change="v => setPkgStatus(pkg.id, v)" size="small" style="width:80px;">
            <el-option label="正常" value="normal" />
            <el-option label="没事件" value="no_events" />
            <el-option label="暂停" value="paused" />
            <el-option label="掉包" value="dropped" />
            <el-option label="拒登" value="rejected" />
          </el-select>
          <span v-else style="font-size:11px;color:#888;width:80px;text-align:center;">
            {{ statusLabel(normalizeStatus(pkg.status)) }}
          </span>
          <el-button v-if="canEdit" size="small" @click.stop="editPkg(pkg)">✏️</el-button>
          <el-button v-if="canEdit" size="small" type="danger" @click.stop="delPkg(pkg.id)">✕</el-button>
        </div>
      </div>
    </div>
  </el-card>
</template>

<script setup>
import { ref, computed, watch } from 'vue'
import { useAuthStore } from '@/stores/auth'
import { ttApi } from '@/api/tt'
import { ElMessageBox, ElMessage } from 'element-plus'
import { copyToClipboard } from '@/utils/clipboard'

const props = defineProps({
  product: Object,
  customName: { type: String, default: '' },
  // 掉包通知跳转后需要定位的包 ID 列表（父组件传入；仅用于自动展开，不影响其他逻辑）
  highlightPkgIds: { type: Array, default: () => [] },
})
const emit = defineEmits(['edit', 'add-pkg', 'del', 'toggle-pause', 'refresh', 'restore'])
const auth = useAuthStore()
const expanded = ref(false)
const checkedIds = ref([])
const anchorId = ref(null)
const shiftDown = ref(false)
const filterStatus = ref('normal')
const nameSort = ref('default')
const editPkgModal = ref(null)
const checkingDelist = ref(false)
const productSuffix = ref(props.customName || '')
watch(() => props.customName, (v) => { productSuffix.value = v || '' })

// 掉包通知点击后定位到具体包：包行包在 v-show="expanded" 容器里，卡片折叠时
// 元素虽然存在但是 display:none —— 没有布局盒，scrollIntoView 是空操作、
// 高亮也看不见。故命中本卡片的包就自动展开，父组件展开后再滚动。
watch(() => props.highlightPkgIds, (ids) => {
  if (!ids || !ids.length) return
  const mine = (props.product?.packages || []).some(p => ids.includes(String(p.id)))
  if (mine) expanded.value = true
}, { immediate: true })

// TT 后端 owner-only：编辑/删除/改状态/加包等操作仅 owner 或 developer/admin 有权
// （list_products 对非 developer/admin 返回「我拥有或在跑」，故不能只用 !isViewer 门控）
const canEdit = computed(() => auth.isAdmin || (auth.user != null && props.product.owner_id === auth.user.id))

const packages = computed(() => {
  const pkgs = [...(props.product.packages || [])]
  pkgs.sort((a, b) => {
    const o = { '': 0, '0': 0, no_events: 1, rejected: 2, paused: 3, dropped: 4 }
    const sa = o[(a.status || '').trim()] ?? 0; const sb = o[(b.status || '').trim()] ?? 0
    if (sa !== sb) return sa - sb
    return (a.created_at || '').localeCompare(b.created_at || '')
  })
  return pkgs
})

const pkgCounts = computed(() => {
  const c = { normal: 0, no_events: 0, rejected: 0, paused: 0, dropped: 0 }
  packages.value.forEach(p => { const s = normalizeStatus(p.status); c[s] = (c[s] || 0) + 1 })
  return c
})

const filteredPackages = computed(() => {
  let list = filterStatus.value === 'all'
    ? packages.value
    : packages.value.filter(p => normalizeStatus(p.status) === filterStatus.value)
  if (nameSort.value !== 'default') {
    const dir = nameSort.value === 'desc' ? -1 : 1
    const cmpName = (x, y) => dir * (x.series_name || '').localeCompare(y.series_name || '', undefined, { numeric: true })
    if (filterStatus.value === 'all') {
      const normal = list.filter(p => normalizeStatus(p.status) === 'normal').sort(cmpName)
      const others = list.filter(p => normalizeStatus(p.status) !== 'normal')
      list = [...normal, ...others]
    } else {
      list = [...list].sort(cmpName)
    }
  }
  return list
})

const nameSortLabel = computed(() => {
  if (nameSort.value === 'desc') return '🔤 名字 ↓'
  if (nameSort.value === 'asc') return '🔤 名字 ↑'
  return '🔤 名字排序'
})

const allChecked = computed(() => {
  const nonDropped = packages.value.filter(p => normalizeStatus(p.status) !== 'dropped')
  return nonDropped.length > 0 && nonDropped.every(p => checkedIds.value.includes(p.id))
})

function statusLabel(s) {
  return { normal: '正常', no_events: '没事件', paused: '暂停', dropped: '掉包', rejected: '拒登' }[s] || s
}
function statusTagType(s) {
  return { normal: 'success', no_events: '', rejected: 'warning', paused: 'danger', dropped: 'info' }[s] ?? ''
}
function normalizeStatus(s) {
  if (s === '0' || s === 0 || !s) return 'normal'
  return String(s).trim()
}

function cycleNameSort() { nameSort.value = (nameSort.value === 'desc') ? 'asc' : 'desc' }
function resetNameSort() { nameSort.value = 'default' }

function onPkgChange(pkg, event) {
  const target = event.target.checked
  if (shiftDown.value && anchorId.value != null && anchorId.value !== pkg.id) {
    const list = filteredPackages.value
    const i1 = list.findIndex(p => p.id === anchorId.value)
    const i2 = list.findIndex(p => p.id === pkg.id)
    if (i1 !== -1 && i2 !== -1) {
      const lo = Math.min(i1, i2), hi = Math.max(i1, i2)
      for (let i = lo; i <= hi; i++) setChecked(list[i].id, target)
    }
  } else {
    setChecked(pkg.id, target)
  }
  anchorId.value = pkg.id
  shiftDown.value = false
}

function setChecked(id, on) {
  const j = checkedIds.value.indexOf(id)
  if (on && j === -1) checkedIds.value.push(id)
  else if (!on && j !== -1) checkedIds.value.splice(j, 1)
}

function toggleAll() {
  if (allChecked.value) checkedIds.value = []
  else checkedIds.value = packages.value.filter(p => normalizeStatus(p.status) !== 'dropped').map(p => p.id)
}
function clearSelection() { checkedIds.value = []; anchorId.value = null }

function batchStatusChange(status) {
  if (!checkedIds.value.length) return
  const labels = { normal: '正常', no_events: '没事件', paused: '暂停', dropped: '掉包', rejected: '拒登' }
  ElMessageBox.confirm(`将选中的 ${checkedIds.value.length} 个包改为「${labels[status]}」？`, '批量改状态', { type: 'warning' }).then(async () => {
    const dbStatus = status === 'normal' ? '' : status
    for (const id of checkedIds.value) { await ttApi.updatePackage(id, { status: dbStatus }) }
    checkedIds.value = []; emit('refresh')
  }).catch(() => {})
}
function batchCopyLinks() {
  const links = packages.value.filter(p => checkedIds.value.includes(p.id) && p.url).map(p => p.url)
  if (!links.length) { ElMessage.warning('选中的包没有链接'); return }
  copyToClipboard(links.join('\n')).then(() => { ElMessage.success(`已复制 ${links.length} 个链接 ✓`) })
}
async function batchDelPkgs() {
  if (!checkedIds.value.length) return
  await ElMessageBox.confirm(`确定删除选中的 ${checkedIds.value.length} 个包？此操作不可撤销。`, '批量删除', { type: 'error' })
  await ttApi.batchDeletePackages(checkedIds.value)
  checkedIds.value = []
  ElMessage.success('批量删除完成')
  emit('refresh')
}

function copy(text) {
  if (!text) return
  copyToClipboard(text).then(() => { ElMessage.success('已复制 ✓') })
}

function copySeriesName(pkg) {
  const text = pkg.series_name || ''
  if (!text) return
  const suffix = (pkg.type !== 'pwa' && productSuffix.value) ? '-' + productSuffix.value : ''
  copyToClipboard(text + suffix).then(() => { ElMessage.success('已复制 ' + (text + suffix) + ' ✓') })
}

async function setPkgStatus(pkgId, status) {
  await ttApi.updatePackage(pkgId, { status: status === 'normal' ? '' : status })
  emit('refresh')
}

async function delPkg(pkgId) {
  await ElMessageBox.confirm('删除此包？', '确认', { type: 'warning' })
  await ttApi.deletePackage(pkgId)
  emit('refresh')
}

function editPkg(pkg) { editPkgModal.value = pkg }

watch(editPkgModal, async (pkg) => {
  if (!pkg) return
  try {
    const { value } = await ElMessageBox.prompt('编辑系列名', '编辑包', {
      confirmButtonText: '保存',
      inputValue: pkg.series_name || '',
    })
    await ttApi.updatePackage(pkg.id, { series_name: value })
    emit('refresh')
  } catch {}
  editPkgModal.value = null
})

async function checkDelist() {
  checkingDelist.value = true
  try {
    const res = await ttApi.checkDelist(props.product.id)
    const delisted = (res.results || []).filter(r => r.is_delisted)
    if (delisted.length) {
      ElMessage.warning(`检测到 ${delisted.length} 个包已掉包！`)
    } else {
      ElMessage.success('所有包均正常 ✓')
    }
    emit('refresh')
  } catch {
    ElMessage.error('检测失败，请稍后重试')
  } finally {
    checkingDelist.value = false
  }
}
</script>

<style scoped>
.is-paused { opacity: 0.88; }
.product-card {
  overflow: visible;
}
.product-card :deep(.el-card__header) {
  position: sticky;
  top: 0;
  z-index: 10;
  overflow: hidden;
  background: var(--el-card-bg-color);
  border-radius: var(--el-card-border-radius) var(--el-card-border-radius) 0 0;
}
.product-card :deep(.el-card__body) {
  overflow: hidden;
  border-radius: 0 0 var(--el-card-border-radius) var(--el-card-border-radius);
}
.pkg-row {
  display: flex; justify-content: space-between; align-items: center;
  padding: 6px 0; border-bottom: 1px solid #f5f5f5; font-size: 12px;
  transition: background .15s;
}
.pkg-row:hover { background: rgba(8,145,178,.06); }
.pkg-row--paused { opacity: 0.6; }
.pkg-row--no-events { opacity: 0.6; }
.pkg-row--dropped { opacity: 0.4; text-decoration: line-through; }
.pkg-row--delisted { background: #fef2f2; border-left: 3px solid #ef4444; }
</style>
