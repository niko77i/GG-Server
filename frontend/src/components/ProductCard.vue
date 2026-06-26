<template>
  <el-card style="margin-bottom:12px;" :class="{ 'is-paused': product.status }">
    <template #header>
      <div style="display:flex;justify-content:space-between;align-items:center;cursor:pointer;" @click="expanded = !expanded">
        <div style="display:flex;align-items:center;gap:12px;">
          <span :style="{ width:'8px',height:'8px',borderRadius:'50%',background: product.status ? '#dc2626' : '#059669' }"></span>
          <strong>{{ product.product_name }}</strong>
          <el-tag v-if="product.kpi" size="small" type="warning">{{ product.kpi }}</el-tag>
          <el-tag v-if="product.region" size="small" type="primary">{{ product.region }}</el-tag>
          <el-tag v-if="product.mcc_name" size="small" type="info">🏢 {{ product.mcc_name }}</el-tag>
          <span v-if="product.related_account_count" style="font-size:12px;color:#888;">
            👤 {{ product.related_account_count }} 账户
          </span>
          <template v-for="(cnt, key) in pkgCounts" :key="key">
            <el-tag v-if="cnt > 0" size="small" :type="key === 'normal' ? 'success' : key === 'rejected' ? 'warning' : key === 'paused' ? 'danger' : 'info'"
              style="cursor:pointer;" @click.stop="filterStatus = filterStatus === key ? 'all' : key">
              {{ cnt }} {{ key === 'normal' ? '正常' : key === 'rejected' ? '拒登' : key === 'paused' ? '暂停' : '掉包' }}
            </el-tag>
          </template>
        </div>
        <div style="display:flex;gap:4px;">
          <el-button size="small" @click.stop="$emit('detail', product.id)">📋</el-button>
          <el-button size="small" @click.stop="$emit('toggle-pause', {id: product.id, paused: !product.status})">
            {{ product.status ? '▶' : '⏸' }}
          </el-button>
          <el-button size="small" @click.stop="$emit('edit', product.id)">✏️</el-button>
          <el-button size="small" @click.stop="$emit('add-pkg', product.id)" type="success">➕包</el-button>
          <el-button size="small" @click.stop="$emit('del', product.id)" type="danger">🗑</el-button>
          <span style="margin-left:4px;color:#888;">{{ expanded ? '▲' : '▼' }}</span>
        </div>
      </div>
    </template>

    <div v-show="expanded">
      <div style="display:flex;justify-content:space-between;align-items:center;padding:4px 0;border-bottom:1px solid #eee;flex-wrap:wrap;gap:6px;">
        <span style="display:flex;align-items:center;gap:6px;">
          <el-button size="small" text @click.stop="toggleAll">{{ allChecked ? '☑ 取消全选' : '☑ 全选' }}</el-button>
          <span style="font-size:11px;color:#888;">包含 {{ packages.length }} 个包</span>
          <el-select v-if="checkedIds.length" :model-value="''" @change="v => batchStatusChange(v)" size="small" style="width:110px;" placeholder="批量改状态">
            <el-option label="正常" value="normal" /><el-option label="暂停" value="paused" /><el-option label="掉包" value="dropped" /><el-option label="拒登" value="rejected" />
          </el-select>
          <el-button v-if="checkedIds.length" size="small" @click.stop="batchCopyLinks" type="primary">📋 复制链接</el-button>
        </span>
        <span style="font-size:11px;color:#888;">已选 {{ checkedIds.length }} 个</span>
      </div>
      <div v-for="pkg in filteredPackages" :key="pkg.id"
        style="display:flex;justify-content:space-between;align-items:center;padding:6px 0;border-bottom:1px solid #f5f5f5;font-size:12px;"
        :style="normalizeStatus(pkg.status) === 'paused' ? 'opacity:0.6;' : normalizeStatus(pkg.status) === 'dropped' ? 'opacity:0.4;text-decoration:line-through;' : ''">
        <div style="display:flex;align-items:center;gap:6px;flex:1;overflow:hidden;">
          <input type="checkbox" :value="pkg.id" v-model="checkedIds" @click.stop style="width:auto;" />
          <span style="font-weight:600;white-space:nowrap;cursor:pointer;" @click.stop="copy(pkg.series_name)">{{ pkg.series_name || '-' }}</span>
          <span style="color:#ccc;">│</span>
          <span style="font-family:monospace;cursor:pointer;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;" @click.stop="copy(pkg.package_name)">{{ pkg.package_name }}</span>
          <span style="color:#ccc;" v-if="pkg.url">│</span>
          <span v-if="pkg.url" style="font-size:11px;color:var(--el-color-primary);overflow:hidden;text-overflow:ellipsis;white-space:nowrap;cursor:pointer;" @click.stop="copy(pkg.url)">{{ pkg.url }}</span>
          <a v-if="pkg.url" :href="pkg.url" target="_blank" style="font-size:11px;text-decoration:none;flex-shrink:0;" @click.stop>🔗</a>
        </div>
        <div style="display:flex;gap:4px;">
          <el-select :model-value="normalizeStatus(pkg.status)" @change="v => setPkgStatus(pkg.id, v)" size="small" style="width:80px;">
            <el-option label="正常" value="normal" />
            <el-option label="暂停" value="paused" />
            <el-option label="掉包" value="dropped" />
            <el-option label="拒登" value="rejected" />
          </el-select>
          <el-button size="small" @click.stop="editPkg(pkg)">✏️</el-button>
          <el-button size="small" type="danger" @click.stop="delPkg(pkg.id)">✕</el-button>
        </div>
      </div>
    </div>
  </el-card>
</template>

<script setup>
import { ref, computed, watch } from 'vue'
import { useProductStore } from '@/stores/products'
import { ElMessageBox, ElMessage } from 'element-plus'
import { copyToClipboard } from '@/utils/clipboard'

const props = defineProps({ product: Object })
const emit = defineEmits(['edit', 'detail', 'add-pkg', 'del', 'toggle-pause', 'refresh'])
const store = useProductStore()
const expanded = ref(false)
const checkedIds = ref([])
const filterStatus = ref('all')
const editPkgModal = ref(null)

const packages = computed(() => {
  const pkgs = [...(props.product.packages || [])]
  pkgs.sort((a, b) => {
    const o = { '': 0, rejected: 1, paused: 2, dropped: 3 }
    const sa = o[a.status || ''] || 0; const sb = o[b.status || ''] || 0
    if (sa !== sb) return sa - sb
    return (a.series_name || '').localeCompare(b.series_name || '', undefined, { numeric: true })
  })
  return pkgs
})

const pkgCounts = computed(() => {
  const c = { normal: 0, rejected: 0, paused: 0, dropped: 0 }
  packages.value.forEach(p => { const s = normalizeStatus(p.status); c[s] = (c[s] || 0) + 1 })
  return c
})

const filteredPackages = computed(() => {
  if (filterStatus.value === 'all') return packages.value
  return packages.value.filter(p => normalizeStatus(p.status) === filterStatus.value)
})

const allChecked = computed(() => {
  const nonDropped = packages.value.filter(p => normalizeStatus(p.status) !== 'dropped')
  return nonDropped.length > 0 && nonDropped.every(p => checkedIds.value.includes(p.id))
})
function toggleAll() {
  if (allChecked.value) { checkedIds.value = [] }
  else { checkedIds.value = packages.value.filter(p => normalizeStatus(p.status) !== 'dropped').map(p => p.id) }
}
function batchStatusChange(status) {
  if (!checkedIds.value.length) return
  const labels = { normal:'正常',paused:'暂停',dropped:'掉包',rejected:'拒登' }
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
function copy(text) {
  if (!text) return
  copyToClipboard(text).then(() => { ElMessage.success('已复制 ✓') })
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
</style>
