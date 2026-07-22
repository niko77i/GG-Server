<template>
  <div style="display:flex;flex-direction:column;height:100%;">
    <!-- 工具栏 — 固定 -->
    <div style="flex-shrink:0;display:flex;gap:10px;margin-bottom:12px;flex-wrap:wrap;align-items:center;">
      <el-button v-if="!auth.isViewer" type="primary" @click="showProductModal()">➕ 新增产品</el-button>
      <el-button v-if="!auth.isViewer" @click="copyVisible = true">📋 复制导入</el-button>
      <el-button @click="openAuditLog">📜 删除日志</el-button>
      <el-radio-group v-model="runnerFilter" @change="onRunnerFilterChange" size="small">
        <el-radio-button value="mine">我在跑的 ({{ runnerCounts.mine ?? '...' }})</el-radio-button>
        <el-radio-button value="all">全部产品 ({{ runnerCounts.all ?? '...' }})</el-radio-button>
      </el-radio-group>
      <el-select v-model="runnerUserId" @change="onRunnerUserChange" placeholder="按 runner 筛选" clearable size="small" style="width:160px;" filterable>
        <el-option v-for="u in runnerUserOptions" :key="u.id" :label="u.display_name || u.username" :value="u.id" />
      </el-select>
      <el-select v-model="store.filters.region" @change="load" placeholder="全部地区" clearable style="width:120px;" filterable>
        <el-option v-for="r in regions" :key="r" :label="r" :value="r" />
      </el-select>
      <el-select v-model="store.filters.mcc_id" @change="load" placeholder="全部 MCC" clearable style="width:180px;" filterable>
        <el-option v-for="m in mccOptions" :key="m.id" :label="m.name + ' (' + m.mcc_id + ')'" :value="m.id" />
      </el-select>
      <el-input v-model="store.filters.search" placeholder="搜索产品或 KPI..." @input="search" style="flex:1;min-width:160px;" clearable />
      <el-radio-group v-model="store.pausedMode" @change="load">
        <el-radio-button :value="false">正常</el-radio-button>
        <el-radio-button :value="true">已暂停</el-radio-button>
      </el-radio-group>
      <el-button
        v-if="selectedIds.length >= 2 && !auth.isViewer"
        type="warning"
        @click="mergeProducts"
      >
        🔀 合并产品 ({{ selectedIds.length }})
      </el-button>
    </div>

    <!-- 产品卡片列表 — 滚动区 -->
    <div style="flex:1;min-height:0;overflow-y:auto;">
      <ProductCard
        v-for="p in store.products" :key="p.id"
        :product="p"
        :region-timezone="regionTimezone"
        :runner-users="runnerUserOptions"
        :custom-name="customName"
        :selected="selectedIds.includes(p.id)"
        @select="toggleSelect(p.id)"
        @edit="showProductModal($event)"
        @detail="showDetail($event)"
        @add-pkg="showAddPkg($event)"
        @del="delProduct($event)"
        @toggle-pause="togglePause($event)"
        @refresh="load"
      />

      <el-empty v-if="!store.products.length" description="暂无产品" />

      <!-- 分页 -->
      <div v-if="store.total > store.pageSize" style="display:flex;align-items:center;justify-content:center;gap:8px;margin-top:12px;">
        <el-pagination v-model:current-page="store.page" :page-size="store.pageSize" :total="store.total" background
          layout="prev,pager,next" size="small" :pager-count="7" @current-change="load" />
        <el-select v-model="store.pageSize" @change="store.page = 1; load()" size="small" style="width:90px;" filterable>
          <el-option v-for="s in [5,10,20,50]" :key="s" :label="s+'条/页'" :value="s" />
        </el-select>
      </div>
    </div>

    <!-- 弹窗 -->
    <ProductModal v-model:visible="pmVisible" :edit-id="pmEditId" :mcc-options="mccOptions" @saved="load" />
    <ProductDetailModal v-model:visible="detailVisible" :prod-id="detailId" @saved="load" />
    <CopyImportModal v-model:visible="copyVisible" @saved="load" />
    <AddPackageModal v-model:visible="addPkgVisible" :prod-id="addPkgProdId" @saved="load" />

    <!-- 删除日志弹窗 -->
    <el-dialog v-model="auditVisible" title="📜 产品删除日志" width="800px" :close-on-click-modal="false" destroy-on-close @opened="loadAuditLogs">
      <el-table :data="auditLogs" size="small" stripe max-height="500">
        <el-table-column label="时间" prop="created_at" width="160" />
        <el-table-column label="操作人" prop="display_name" width="100" />
        <el-table-column label="产品名" prop="target_name" min-width="200" show-overflow-tooltip />
        <el-table-column label="操作" width="160" align="center">
          <template #default="{ row }">
            <el-button link size="small" type="primary" @click="toggleAuditDetail(row)">详情</el-button>
            <el-button v-if="auth.isDeveloper && row.action==='delete_product'" link size="small" type="success" @click="restoreProduct(row)">恢复</el-button>
          </template>
        </el-table-column>
      </el-table>
      <el-pagination v-if="auditTotal > 20" v-model:current-page="auditPage" :page-size="20" :total="auditTotal" layout="prev,pager,next" size="small" @change="loadAuditLogs" style="margin-top:10px;justify-content:center;" />
      <div v-if="auditDetailRow" style="margin-top:12px;padding:12px;background:#f5f7fa;border-radius:8px;font-size:13px;">
        <div style="font-weight:600;margin-bottom:8px;">📋 快照详情 — {{ auditDetailRow.target_name }}</div>
        <div v-if="auditDetailRow.detail.product">
          <div><b>产品:</b> {{ auditDetailRow.detail.product.product_name }}</div>
          <div><b>KPI:</b> {{ auditDetailRow.detail.product.kpi }} | <b>地区:</b> {{ auditDetailRow.detail.product.region }}</div>
          <div><b>MCC:</b> {{ auditDetailRow.detail.product.mcc_id }} | <b>customer:</b> {{ auditDetailRow.detail.product.customer || '-' }}</div>
        </div>
        <div v-if="auditDetailRow.detail.packages?.length" style="margin-top:6px;">
          <b>包 ({{ auditDetailRow.detail.packages.length }}):</b>
          <div v-for="(p, i) in auditDetailRow.detail.packages" :key="i" style="margin-left:12px;color:#666;">
            {{ p.package_name }} <el-tag size="small">{{ p.status || '正常' }}</el-tag>
          </div>
        </div>
        <div style="margin-top:4px;color:#999;">素材: {{ auditDetailRow.detail.asset_count ?? 0 }} 个</div>
      </div>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, onMounted, onUnmounted, nextTick, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import { useProductStore } from '@/stores/products'
import ProductCard from '@/components/ProductCard.vue'
import ProductModal from '@/components/ProductModal.vue'
import ProductDetailModal from '@/components/ProductDetailModal.vue'
import CopyImportModal from '@/components/CopyImportModal.vue'
import AddPackageModal from '@/components/AddPackageModal.vue'
import { ElMessageBox, ElMessage } from 'element-plus'
import { productsApi } from '@/api/products'
import api from '@/api/client'

const auth = useAuthStore()
const route = useRoute()
const router = useRouter()
const store = useProductStore()
const regions = ref([])
const mccOptions = ref([])
const runnerFilter = ref(auth.isViewer ? 'all' : 'mine')
const runnerUserId = ref(null)
const runnerUserOptions = ref([])
const runnerCounts = ref({ mine: '...', all: '...' })
const selectedIds = ref([])

const pmVisible = ref(false); const pmEditId = ref(null)
const detailVisible = ref(false); const detailId = ref(null)
const copyVisible = ref(false)
const addPkgVisible = ref(false); const addPkgProdId = ref(null)

let searchTimer = null

const regionTimezone = ref({})

const customName = ref('')

onMounted(() => { load(); loadRunnerUsers(); loadRegionTimezone(); loadCustomName() })

// 监听手动掉包检测完成事件，自动刷新产品列表
window.addEventListener('delist-check-completed', load)
onUnmounted(() => { window.removeEventListener('delist-check-completed', load) })

async function loadCustomName() {
  try {
    const res = await api.get('/auth/custom-name')
    customName.value = res.custom_name || ''
  } catch { customName.value = '' }
}

async function loadRegionTimezone() {
  try {
    const res = await api.get('/regions/list')
    const map = {}
    for (const r of (res.regions || [])) { map[r.name] = r.timezone }
    regionTimezone.value = map
  } catch {}
}

function runnerParam() {
  return runnerUserId.value ? String(runnerUserId.value) : runnerFilter.value
}

async function load() {
  const res = await store.loadProducts({ runner: runnerParam() })
  regions.value = res.regions || []
  mccOptions.value = res.mcc_options || []
  if (res.runner_counts) runnerCounts.value = res.runner_counts
  selectedIds.value = []

  // 从通知点击跳转过来的，自动滚动到对应包
  scrollToHighlightedPackage()
}

// 已在产品页时点击通知（路由 query 变化），同样滚动
watch(() => route.query.highlight_pkg, () => { scrollToHighlightedPackage() })

async function scrollToHighlightedPackage() {
  const pkgId = route.query.highlight_pkg
  if (!pkgId) return
  router.replace({ query: {} })  // 清除 query，避免后续重复滚动
  await nextTick()
  const el = document.getElementById('pkg-' + pkgId)
  if (el) {
    el.scrollIntoView({ behavior: 'smooth', block: 'center' })
    el.style.boxShadow = '0 0 0 3px #ef4444'
    el.style.transition = 'box-shadow 0.3s'
    setTimeout(() => { el.style.boxShadow = '' }, 2000)
  }
}

async function loadRunnerUsers() {
  try {
    const res = await api.get('/users/names')
    runnerUserOptions.value = res.users || []
  } catch { runnerUserOptions.value = [] }
}

function onRunnerFilterChange() {
  runnerUserId.value = null
  load()
}

function onRunnerUserChange(uid) {
  load()
}

function toggleSelect(id) {
  const idx = selectedIds.value.indexOf(id)
  if (idx >= 0) selectedIds.value.splice(idx, 1)
  else selectedIds.value.push(id)
}

async function mergeProducts() {
  if (selectedIds.value.length < 2) return
  const masterId = selectedIds.value[0]
  const mergeId = selectedIds.value[1]  // 只比第一个被合并的

  // 获取两边产品的包名
  let masterPkgs = [], mergePkgs = []
  try {
    const [masterRes, mergeRes] = await Promise.all([
      productsApi.detail(masterId),
      productsApi.detail(mergeId),
    ])
    masterPkgs = (masterRes.product?.packages || []).map(p => p.package_name)
    mergePkgs = (mergeRes.product?.packages || []).map(p => p.package_name)
  } catch {}

  const hasMatch = masterPkgs.some(n => mergePkgs.includes(n))
  const confirmMsg = hasMatch
    ? `将 ${selectedIds.value.length - 1} 个产品合并到第一个？此操作不可撤销。`
    : `⚠ 两个产品的包名完全不同，确定合并？`

  try {
    await ElMessageBox.confirm(confirmMsg, '确认合并', {
      type: hasMatch ? 'warning' : 'error',
      confirmButtonText: '合并',
      cancelButtonText: '取消',
    })
    await productsApi.merge({
      master_id: masterId,
      merge_ids: selectedIds.value.slice(1),
    })
    ElMessage.success('合并完成')
    selectedIds.value = []
    load()
  } catch (e) {
    if (e !== 'cancel') ElMessage.error('合并失败')
  }
}

function search() {
  clearTimeout(searchTimer)
  searchTimer = setTimeout(() => { store.page = 1; load() }, 500)
}

function showProductModal(id) { pmEditId.value = id || null; pmVisible.value = true }
function showDetail(id) { detailId.value = id; detailVisible.value = true }
function showAddPkg(id) { addPkgProdId.value = id; addPkgVisible.value = true }

async function delProduct(id) {
  await ElMessageBox.confirm('确定删除此产品及所有包？', '确认', { type: 'warning' })
  await store.deleteProduct(id)
}

async function togglePause({ id, paused }) {
  const msg = paused ? '确定暂停此产品？' : '确定恢复此产品？'
  await ElMessageBox.confirm(msg, '确认', { type: 'warning' })
  await store.updateProduct(id, { status: paused ? 'paused' : '' })
  load()
}

// 删除日志
const auditVisible = ref(false)
const auditLogs = ref([])
const auditTotal = ref(0)
const auditPage = ref(1)
const auditDetailRow = ref(null)

function openAuditLog() {
  auditVisible.value = true
  auditPage.value = 1
  auditDetailRow.value = null
}

async function loadAuditLogs() {
  try {
    const res = await productsApi.auditLogList({ page: auditPage.value, size: 20 })
    auditLogs.value = res.logs || []
    auditTotal.value = res.total || 0
  } catch { auditLogs.value = [] }
}

function toggleAuditDetail(row) {
  auditDetailRow.value = auditDetailRow.value?.id === row.id ? null : row
}

async function restoreProduct(row) {
  try {
    await ElMessageBox.confirm(`确定恢复产品「${row.target_name}」？`, '确认恢复', { type: 'warning' })
  } catch { return }
  try {
    const res = await productsApi.auditLogRestore(row.id)
    ElMessage.success(res.message || '产品已恢复')
    await loadAuditLogs()
    load()
  } catch (e) {
    ElMessage.error(e.response?.data?.error || '恢复失败')
  }
}
</script>
