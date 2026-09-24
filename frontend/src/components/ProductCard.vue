<template>
  <el-card class="product-card" style="margin-bottom:12px;" :class="{ 'is-paused': product.status }">
    <template #header>
      <div style="display:flex;justify-content:space-between;align-items:center;cursor:pointer;" @click="expanded = !expanded">
        <div style="display:flex;align-items:center;gap:12px;">
          <input type="checkbox" :checked="selected" @click.stop="$emit('select')" style="width:auto;cursor:pointer;" />
          <span :style="{ width:'8px',height:'8px',borderRadius:'50%',background: product.status ? '#dc2626' : '#059669' }"></span>
          <strong>{{ product.product_name }}</strong>
          <el-button size="small" type="warning" plain :loading="checkingDelist" @click.stop="checkDelist">
            {{ checkingDelist ? '检测中...' : '🔍 是否掉包' }}
          </el-button>
          <el-tag v-if="product.sales_person" size="small" type="success">💼 {{ product.sales_person }}</el-tag>
          <el-tag v-if="product.kpi" size="small" type="warning">{{ product.kpi }}</el-tag>
          <el-tooltip v-if="product.region" placement="top">
            <template #content>时区：{{ regionTimezone[product.region] || '未设置' }}</template>
            <el-tag size="small" type="primary">{{ product.region }}</el-tag>
          </el-tooltip>
          <el-tag v-if="product.customer" size="small" type="success">👤 {{ product.customer }}</el-tag>
          <el-tooltip v-if="product.mcc_name" placement="top">
            <template #content>
              <div>🏢 {{ product.mcc_name }}</div>
              <div v-if="product.mcc_code">🆔 {{ product.mcc_code }}</div>
              <div style="margin-top:4px;color:#aaa;font-size:11px;">点击复制完整信息</div>
            </template>
            <el-tag size="small" type="info" style="cursor:pointer;" @click.stop="copyMcc">
              🏢 {{ product.mcc_name }}
            </el-tag>
          </el-tooltip>
          <el-tooltip v-if="parsedRunnerIds.length" placement="top">
            <template #content>
              <div v-for="rid in parsedRunnerIds" :key="rid">{{ getRunnerName(rid) }}</div>
            </template>
            <el-tag size="small" type="info">🏃 {{ parsedRunnerIds.length }}人</el-tag>
          </el-tooltip>
          <el-tooltip v-if="product.asset_count > 0" placement="top">
            <template #content>点击复制成效素材链接</template>
            <el-tag size="small" type="warning" effect="dark" style="cursor:pointer;" @click.stop="copyAssets">🎬 {{ product.asset_count }}</el-tag>
          </el-tooltip>
          <el-tooltip content="复制系列名时的后缀" placement="top">
            <el-input
              v-model="productSuffix"
              size="small"
              style="width:80px;"
              placeholder="后缀"
              @click.stop
              @keydown.enter.stop
            />
          </el-tooltip>
          <span v-if="product.related_account_count" style="font-size:12px;color:#888;">
            👤 {{ product.related_account_count }} 账户
          </span>
        </div>
        <div style="display:flex;gap:4px;">
          <el-button size="small" @click.stop="$emit('detail', product.id)">📋</el-button>
          <el-button v-if="!auth.isViewer" size="small" @click.stop="$emit('toggle-pause', {id: product.id, paused: !product.status})">
            {{ product.status ? '▶' : '⏸' }}
          </el-button>
          <el-button v-if="!auth.isViewer" size="small" @click.stop="$emit('edit', product.id)">✏️</el-button>
          <el-button v-if="!auth.isViewer" size="small" @click.stop="$emit('add-pkg', product.id)" type="success">➕包</el-button>
          <el-button v-if="!auth.isViewer" size="small" @click.stop="$emit('del', product.id)" type="danger">🗑</el-button>
          <span style="margin-left:4px;color:#888;">{{ expanded ? '▲' : '▼' }}</span>
        </div>
      </div>
      <div v-show="expanded" style="display:flex;justify-content:space-between;align-items:center;padding:8px 0 0;margin-bottom:-10px;flex-wrap:wrap;gap:6px;">
        <span style="display:flex;align-items:center;gap:6px;flex-wrap:wrap;">
          <el-tag size="small" type="info" :effect="filterStatus === 'all' ? 'dark' : 'light'" style="cursor:pointer;" @click.stop="filterStatus = 'all'">
            {{ packages.length }} 全部
          </el-tag>
          <template v-for="(cnt, key) in pkgCounts" :key="key">
            <el-tag v-if="cnt > 0" size="small" :type="key === 'normal' ? 'success' : key === 'rejected' ? 'warning' : key === 'no_events' ? '' : key === 'paused' ? 'danger' : 'info'"
              :effect="filterStatus === key ? 'dark' : 'light'"
              style="cursor:pointer;" @click.stop="filterStatus = key">
              {{ cnt }} {{ key === 'normal' ? '正常' : key === 'no_events' ? '没事件' : key === 'rejected' ? '拒登' : key === 'paused' ? '暂停' : '掉包' }}
            </el-tag>
          </template>
          <el-button size="small" text @click.stop="cycleNameSort">{{ nameSortLabel }}</el-button>
          <el-button v-if="nameSort !== 'default'" size="small" text type="warning" @click.stop="resetNameSort">恢复默认排序</el-button>
        </span>
        <span style="display:flex;align-items:center;gap:6px;">
          <el-button size="small" text @click.stop="toggleAll">{{ allChecked ? '☑ 取消全选' : '☑ 全选' }}</el-button>
          <span style="font-size:11px;color:#888;">已选 {{ checkedIds.length }} 个</span>
          <el-button v-if="checkedIds.length" size="small" text type="info" @click.stop="clearSelection">✕ 取消选择</el-button>
          <el-select v-if="checkedIds.length && !auth.isViewer" :model-value="''" @change="v => batchStatusChange(v)" size="small" style="width:110px;" placeholder="批量改状态">
            <el-option label="正常" value="normal" /><el-option label="没事件" value="no_events" /><el-option label="暂停" value="paused" /><el-option label="掉包" value="dropped" /><el-option label="拒登" value="rejected" />
          </el-select>
          <el-button v-if="checkedIds.length" size="small" @click.stop="batchCopyLinks" type="primary">📋 复制链接</el-button>
          <el-button v-if="checkedIds.length && !auth.isViewer" size="small" @click.stop="batchDelPkgs" type="danger">🗑 批量删除</el-button>
        </span>
      </div>
    </template>

    <div v-show="expanded">
      <div v-for="pkg in filteredPackages" :key="pkg.id" :id="'pkg-' + pkg.id"
        class="pkg-row"
        :class="{ 'pkg-row--paused': normalizeStatus(pkg.status) === 'paused', 'pkg-row--no-events': normalizeStatus(pkg.status) === 'no_events', 'pkg-row--dropped': normalizeStatus(pkg.status) === 'dropped', 'pkg-row--delisted': pkg.is_delisted && normalizeStatus(pkg.status) !== 'dropped' }">
        <div style="display:flex;align-items:center;gap:6px;flex:1;min-width:0;overflow:hidden;">
          <input type="checkbox" :checked="checkedIds.includes(pkg.id)" @mousedown="shiftDown = $event.shiftKey" @change="onPkgChange(pkg, $event)" style="width:auto;flex-shrink:0;" />
          <span style="font-weight:600;white-space:nowrap;flex-shrink:0;cursor:pointer;"
  @click.stop="copySeriesName(pkg.series_name)"
  :title="'点击复制'">{{ pkg.series_name || '-' }}</span>
          <span style="color:#ccc;flex-shrink:0;">│</span>
          <span style="font-family:monospace;cursor:pointer;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;" @click.stop="copy(pkg.package_name)">{{ pkg.package_name }}</span>
          <span style="color:#ccc;flex-shrink:0;" v-if="pkg.url">│</span>
          <span v-if="pkg.url" style="font-size:11px;color:var(--el-color-primary);overflow:hidden;text-overflow:ellipsis;white-space:nowrap;cursor:pointer;" @click.stop="copy(pkg.url)">{{ pkg.url }}</span>
          <a v-if="pkg.url" :href="pkg.url" target="_blank" style="font-size:11px;text-decoration:none;flex-shrink:0;" @click.stop>🔗</a>
        </div>
        <span style="font-size:11px;color:#888;white-space:nowrap;flex-shrink:0;margin:0 8px;">{{ pkg.created_at || '' }}</span>
        <div style="display:flex;gap:4px;flex-shrink:0;">
          <el-select v-if="!auth.isViewer" :model-value="normalizeStatus(pkg.status)" @change="v => setPkgStatus(pkg.id, v)" size="small" style="width:80px;">
            <el-option label="正常" value="normal" />
            <el-option label="没事件" value="no_events" />
            <el-option label="暂停" value="paused" />
            <el-option label="掉包" value="dropped" />
            <el-option label="拒登" value="rejected" />
          </el-select>
          <span v-else style="font-size:11px;color:#888;width:80px;text-align:center;">
            {{ { normal: '正常', no_events: '没事件', paused: '暂停', dropped: '掉包', rejected: '拒登' }[normalizeStatus(pkg.status)] || normalizeStatus(pkg.status) }}
          </span>
          <el-button v-if="!auth.isViewer" size="small" @click.stop="editPkg(pkg)">✏️</el-button>
          <el-button v-if="!auth.isViewer" size="small" type="danger" @click.stop="delPkg(pkg.id)">✕</el-button>
        </div>
      </div>
    </div>
  </el-card>
</template>

<script setup>
import { ref, computed, watch } from 'vue'
import { useAuthStore } from '@/stores/auth'
import { useProductStore } from '@/stores/products'
import { ElMessageBox, ElMessage } from 'element-plus'
import { copyToClipboard } from '@/utils/clipboard'
import api from '@/api/client'

const props = defineProps({
  product: Object,
  selected: { type: Boolean, default: false },
  regionTimezone: { type: Object, default: () => ({}) },
  runnerUsers: { type: Array, default: () => [] },
  customName: { type: String, default: '' },
  // 掉包通知跳转后需要定位的包 ID 列表（父组件传入；仅用于自动展开，不影响其他逻辑）
  highlightPkgIds: { type: Array, default: () => [] },
})
const emit = defineEmits(['edit', 'detail', 'add-pkg', 'del', 'toggle-pause', 'refresh', 'select'])
const auth = useAuthStore()
const store = useProductStore()
const expanded = ref(false)
const checkedIds = ref([])
const anchorId = ref(null)
const shiftDown = ref(false)
const filterStatus = ref('normal')
const nameSort = ref('default')
const editPkgModal = ref(null)
const productSuffix = ref(props.customName)
const checkingDelist = ref(false)

// 监听 props 变化（切换筛选时卡片复用），重置后缀
watch(() => props.customName, (v) => {
  productSuffix.value = v || ''
})

// 掉包通知点击后定位到具体包：包行包在 v-show="expanded" 容器里，卡片折叠时
// 元素虽然存在但是 display:none —— 没有布局盒，scrollIntoView 是空操作、
// 高亮也看不见。故命中本卡片的包就自动展开，父组件展开后再滚动。
watch(() => props.highlightPkgIds, (ids) => {
  if (!ids || !ids.length) return
  const mine = (props.product?.packages || []).some(p => ids.includes(String(p.id)))
  if (mine) expanded.value = true
}, { immediate: true })

function getRunnerName(rid) {
  const u = props.runnerUsers.find(u => u.id === rid)
  return u ? (u.display_name || u.username) : 'User #' + rid
}

async function copyAssets() {
  try {
    const res = await api.get(`/products/${props.product.id}/assets`)
    const assets = res.assets || []
    if (!assets.length) { ElMessage.warning('暂无成效素材'); return }
    const links = assets.map(a => `https://www.youtube.com/watch?v=${a.id}`).join('\n')
    await copyToClipboard(links)
    ElMessage.success(`已复制 ${assets.length} 个成效素材链接`)
  } catch { ElMessage.error('获取成效素材失败') }
}

async function checkDelist() {
  checkingDelist.value = true
  try {
    const res = await api.post(`/products/${props.product.id}/check-delist`)
    if (res.success) {
      const results = res.results || []
      const delisted = results.filter(r => r.is_delisted)
      // 判定未知（限流/网络异常/空 url）：is_delisted 为 null 或缺失
      const unknown = results.filter(r => r.is_delisted == null)
      if (!results.length) {
        ElMessage.info(res.message || '没有需要检测的包')
      } else if (delisted.length) {
        ElMessage.warning(`检测到 ${delisted.length} 个包已掉包！`)
        emit('refresh')
      } else if (unknown.length) {
        ElMessage.warning(`${unknown.length} 个包本轮未能判定（限流或网络异常），已保留上次判定结果`)
      } else {
        ElMessage.success('所有包均正常 ✓')
      }
    }
  } catch {
    ElMessage.error('检测失败，请稍后重试')
  } finally {
    checkingDelist.value = false
  }
}

const parsedRunnerIds = computed(() => {
  const ids = props.product.runner_ids
  if (!ids) return []
  if (Array.isArray(ids)) return ids
  try { const parsed = JSON.parse(ids); return Array.isArray(parsed) ? parsed : [] }
  catch { return [] }
})

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
      // 展示所有包：只对「正常」包按名字排序，其它状态保持原有顺序
      const normal = list.filter(p => normalizeStatus(p.status) === 'normal').sort(cmpName)
      const others = list.filter(p => normalizeStatus(p.status) !== 'normal')
      list = [...normal, ...others]
    } else {
      // 筛选单一状态：对当前展示的所有包整体按名字排序
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

function cycleNameSort() {
  nameSort.value = (nameSort.value === 'desc') ? 'asc' : 'desc'
}

function resetNameSort() {
  nameSort.value = 'default'
}

function onPkgChange(pkg, event) {
  const target = event.target.checked
  // Shift 范围选择：按住 Shift 点击，将锚点包 ↔ 当前包之间的所有包统一设为当前包的目标状态（支持选中/取消）
  if (shiftDown.value && anchorId.value != null && anchorId.value !== pkg.id) {
    const list = filteredPackages.value
    const i1 = list.findIndex(p => p.id === anchorId.value)
    const i2 = list.findIndex(p => p.id === pkg.id)
    if (i1 !== -1 && i2 !== -1) {
      const lo = Math.min(i1, i2), hi = Math.max(i1, i2)
      for (let i = lo; i <= hi; i++) {
        setChecked(list[i].id, target)
      }
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

const allChecked = computed(() => {
  const nonDropped = packages.value.filter(p => normalizeStatus(p.status) !== 'dropped')
  return nonDropped.length > 0 && nonDropped.every(p => checkedIds.value.includes(p.id))
})
function toggleAll() {
  if (allChecked.value) { checkedIds.value = [] }
  else { checkedIds.value = packages.value.filter(p => normalizeStatus(p.status) !== 'dropped').map(p => p.id) }
}
function clearSelection() {
  checkedIds.value = []
  anchorId.value = null
}
function batchStatusChange(status) {
  if (!checkedIds.value.length) return
  const labels = { normal:'正常',no_events:'没事件',paused:'暂停',dropped:'掉包',rejected:'拒登' }
  ElMessageBox.confirm(`将选中的 ${checkedIds.value.length} 个包改为「${labels[status]}」？`,'批量改状态',{type:'warning'}).then(async()=>{
    const dbStatus = status==='normal'?'':status
    for(const id of checkedIds.value){ await store.updatePackage(id,{status:dbStatus}) }
    checkedIds.value=[]; emit('refresh')
  }).catch(()=>{})
}
function batchCopyLinks() {
  const links = packages.value.filter(p=>checkedIds.value.includes(p.id)&&p.url).map(p=>p.url)
  if(!links.length){ElMessage.warning('选中的包没有链接');return}
  copyToClipboard(links.join('\n')).then(()=>{ElMessage.success(`已复制 ${links.length} 个链接 ✓`)})
}
async function batchDelPkgs() {
  if (!checkedIds.value.length) return
  await ElMessageBox.confirm(`确定删除选中的 ${checkedIds.value.length} 个包？此操作不可撤销。`, '批量删除', { type: 'error' })
  await store.batchDeletePackages(checkedIds.value)
  checkedIds.value = []
  ElMessage.success('批量删除完成')
  emit('refresh')
}
function copy(text) {
  if (!text) return
  copyToClipboard(text).then(() => { ElMessage.success('已复制 ✓') })
}

function copyMcc() {
  const parts = [props.product.mcc_name]
  if (props.product.mcc_code) parts.push(props.product.mcc_code)
  copyToClipboard(parts.join('\n')).then(() => { ElMessage.success('已复制 MCC 信息 ✓') })
}

function copySeriesName(text) {
  if (!text) return
  const suffix = productSuffix.value ? '-' + productSuffix.value : ''
  copyToClipboard(text + suffix).then(() => { ElMessage.success('已复制 ' + (text + suffix) + ' ✓') })
}

function normalizeStatus(s) {
  // 映射数据库值 → 展示值：空/0/null → 'normal'
  if (s === '0' || s === 0 || !s) return 'normal'
  return s
}

async function setPkgStatus(pkgId, status) {
  // 映射展示值 → 数据库值：'normal' → ''
  await store.updatePackage(pkgId, { status: status === 'normal' ? '' : status })
  emit('refresh')
}

async function delPkg(pkgId) {
  await ElMessageBox.confirm('删除此包？', '确认', { type: 'warning' })
  await store.deletePackage(pkgId)
}

function editPkg(pkg) {
  editPkgModal.value = pkg
}

// 监听 editPkgModal 变化，弹出编辑框
watch(editPkgModal, async (pkg) => {
  if (!pkg) return
  try {
    const { value } = await ElMessageBox.prompt('编辑系列名', '编辑包', {
      confirmButtonText: '保存',
      inputValue: pkg.series_name || '',
    })
    await store.updatePackage(pkg.id, { series_name: value })
    emit('refresh')
  } catch {}
  editPkgModal.value = null
})
</script>

<style scoped>
.is-paused { opacity: 0.88; }
/* 展开产品头部吸顶：解除 el-card 默认 overflow:hidden 对 sticky 的锁定 */
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
