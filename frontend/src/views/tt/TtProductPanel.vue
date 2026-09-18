<template>
  <div class="page-wrapper">
    <div class="page-header">
      <h1 class="page-title">TT 产品管理</h1>
      <el-button type="primary" @click="openCreate">新增产品</el-button>
    </div>

    <div class="filter-card">
      <el-input v-model="search" placeholder="搜索产品..." @input="onSearch" clearable size="small" style="flex:1;min-width:160px" />
      <el-select v-model="filterRegion" placeholder="全部地区" clearable size="small" style="width:120px" @change="loadData">
        <el-option v-for="r in regionOptions" :key="r.name" :label="r.name" :value="r.name" />
      </el-select>
      <el-select v-model="filterRunner" placeholder="筛选在跑人" clearable filterable size="small" style="width:160px" @change="loadData">
        <el-option v-for="u in ttUsers" :key="u.id" :label="(u.display_name||u.username)+' ('+u.username+')'" :value="u.id" />
      </el-select>
      <el-radio-group v-model="filterStatus" size="small" @change="loadData">
        <el-radio-button value="">正常</el-radio-button>
        <el-radio-button value="paused">已暂停</el-radio-button>
      </el-radio-group>
      <el-radio-group v-model="filterArchived" size="small" @change="loadData">
        <el-radio-button value="">在用</el-radio-button>
        <el-radio-button value="1">已归档</el-radio-button>
      </el-radio-group>
      <span class="total-badge">共 {{ total }} 个</span>
    </div>

    <div class="product-list">
      <el-card v-for="item in items" :key="item.id" class="product-card"
        :class="{ 'is-paused': item.status === 'paused' }" :body-style="{ padding: 0 }">
        <div class="product-card-inner">
          <div class="product-card-header" @click="toggleExpand(item.id)">
            <div class="product-card-info">
              <div class="product-card-tags">
                <span class="status-dot" :class="item.status === 'paused' ? 'dot-paused' : 'dot-active'"></span>
                <strong class="product-name">{{ item.product_name }}</strong>
                <el-tag v-if="item.sales_person_name" size="small" class="tag-sales">{{ item.sales_person_name }}</el-tag>
                <el-tag v-if="item.kpi" size="small" class="tag-kpi">{{ item.kpi }}</el-tag>
                <el-tag v-if="item.region" size="small" class="tag-region">{{ item.region }}</el-tag>
                <el-tag v-if="item.customer" size="small" class="tag-customer">{{ item.customer }}</el-tag>
              </div>
              <div v-if="item.bc" class="product-card-bc">
                <el-tag size="small" type="info">BC: {{ item.bc.name }}</el-tag>
              </div>
              <div v-if="item.runners && item.runners.length" class="product-card-runners">
                在跑: {{ item.runners.map(r => r.display_name||r.username).join('、') }}
              </div>
              <div class="product-card-lines">
                投放对象: {{ (item.packages||[]).length }} 个
                <span class="expand-hint">展开</span>
              </div>
            </div>
            <div class="product-card-actions" @click.stop>
              <template v-if="filterArchived==='1'">
                <el-popconfirm title="确定恢复？" @confirm="handleRestore(item.id)">
                  <template #reference><el-button size="small" type="success">恢复</el-button></template>
                </el-popconfirm>
              </template>
              <template v-else>
                <el-button size="small" @click="openEdit(item)">编辑</el-button>
                <el-button size="small" @click="handleCheckDelist(item)" :loading="checkingId===item.id">掉包检测</el-button>
                <el-popconfirm title="确定删除？" @confirm="handleDelete(item.id)">
                  <template #reference><el-button size="small" type="danger">删除</el-button></template>
                </el-popconfirm>
              </template>
            </div>
          </div>

          <div v-if="expanded[item.id]" class="product-card-expand" @click.stop>
            <el-table v-if="(item.packages||[]).length" :data="item.packages" border size="small" class="pkg-table"
              :header-cell-style="{ background:'#f8f9fa', color:'#374151', fontWeight:600 }">
              <el-table-column label="类型" width="80">
                <template #default="{ row: pk }">
                  <el-tag :type="pk.type === 'pwa' ? 'warning' : 'primary'" size="small">{{ pk.type === 'pwa' ? 'PWA' : '跑包' }}</el-tag>
                </template>
              </el-table-column>
              <el-table-column prop="series_name" label="系列名" min-width="120" />
              <el-table-column label="包名" min-width="140">
                <template #default="{ row: pk }"><span class="copy-link" @click="copy(pk.package_name)">{{ pk.package_name || '-' }}</span></template>
              </el-table-column>
              <el-table-column label="链接" min-width="220">
                <template #default="{ row: pk }"><span v-if="pk.url" class="copy-link" @click="copy(pk.url)">{{ pk.url }}</span><span v-else class="no-data">-</span></template>
              </el-table-column>
              <el-table-column prop="status" label="状态" width="90">
                <template #default="{ row: pk }">{{ pk.status || '-' }}</template>
              </el-table-column>
            </el-table>
            <div v-else class="no-lines">无投放对象</div>
          </div>
        </div>
      </el-card>

      <el-empty v-if="!items.length" description="暂无产品" />

      <div v-if="total>size" class="pagination-row">
        <el-pagination v-model:current-page="page" :page-size="size" :total="total" background
          layout="prev,pager,next" size="small" :pager-count="7" @current-change="loadData" />
      </div>
    </div>

    <el-dialog v-model="dialogVisible" :title="editingId?'编辑产品':'新增产品'" width="760px" top="3vh">
      <el-form :model="form" label-width="80px">
        <el-row :gutter="16">
          <el-col :span="12"><el-form-item label="产品名" required><el-input v-model="form.product_name" /></el-form-item></el-col>
          <el-col :span="12"><el-form-item label="KPI"><el-input v-model="form.kpi" /></el-form-item></el-col>
        </el-row>
        <el-row :gutter="16">
          <el-col :span="12">
            <el-form-item label="地区">
              <el-select v-model="form.region" clearable filterable allow-create style="width:100%">
                <el-option v-for="r in regionOptions" :key="r.name" :label="r.name" :value="r.name" />
              </el-select>
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="商务">
              <el-select v-model="form.sales_person_id" clearable filterable allow-create style="width:100%">
                <el-option v-for="s in salesOptions" :key="s.id" :label="s.name" :value="s.id" />
              </el-select>
            </el-form-item>
          </el-col>
        </el-row>
        <el-row :gutter="16">
          <el-col :span="12">
            <el-form-item label="BC">
              <el-select v-model="form.bc_id" clearable filterable style="width:100%">
                <el-option v-for="b in bcOptions" :key="b.id" :label="b.name+' ('+b.bc_id+')'" :value="b.id" />
              </el-select>
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="代投比例"><el-input-number v-model="form.agency_ratio" :min="0" :max="100" style="width:100%" /></el-form-item>
          </el-col>
        </el-row>
        <el-row :gutter="16">
          <el-col :span="12"><el-form-item label="客户"><el-input v-model="form.customer" /></el-form-item></el-col>
          <el-col :span="12">
            <el-form-item label="状态">
              <el-select v-model="form.status" style="width:100%">
                <el-option label="正常" value="active" /><el-option label="暂停" value="paused" />
              </el-select>
            </el-form-item>
          </el-col>
        </el-row>
        <el-form-item label="在跑人员">
          <el-select v-model="form.runner_ids" multiple filterable style="width:100%">
            <el-option v-for="u in ttUsers" :key="u.id" :label="(u.display_name||u.username)+' ('+u.username+')'" :value="u.id" />
          </el-select>
        </el-form-item>

        <el-divider content-position="left">投放对象</el-divider>
        <el-button size="small" type="success" @click="addPkgRow('package')" class="add-btn">+ 跑包</el-button>
        <el-button size="small" type="warning" @click="addPkgRow('pwa')" class="add-btn">+ PWA</el-button>
        <el-button size="small" @click="openImportText" class="add-btn">粘贴解析</el-button>
        <el-table :data="formPackages" border size="small" class="dialog-pkg-table"
          :header-cell-style="{ background:'#f8f9fa', color:'#374151', fontWeight:600 }">
          <el-table-column label="类型" width="80">
            <template #default="{ row }"><el-tag :type="row.type === 'pwa' ? 'warning' : 'primary'" size="small">{{ row.type === 'pwa' ? 'PWA' : '跑包' }}</el-tag></template>
          </el-table-column>
          <el-table-column label="系列名" min-width="130">
            <template #default="{row,$index}"><el-input v-model="formPackages[$index].series_name" size="small" /></template>
          </el-table-column>
          <el-table-column label="包名（仅跑包）" min-width="140">
            <template #default="{row,$index}"><el-input v-model="formPackages[$index].package_name" size="small" :disabled="row.type==='pwa'" /></template>
          </el-table-column>
          <el-table-column label="链接" min-width="180">
            <template #default="{row,$index}"><el-input v-model="formPackages[$index].url" size="small" /></template>
          </el-table-column>
          <el-table-column label="状态" width="100">
            <template #default="{row,$index}"><el-input v-model="formPackages[$index].status" size="small" /></template>
          </el-table-column>
          <el-table-column label="操作" width="70" align="center">
            <template #default="{ $index }"><el-button size="small" type="danger" @click="formPackages.splice($index,1)">删除</el-button></template>
          </el-table-column>
        </el-table>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible=false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="handleSave">保存</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="importVisible" title="粘贴解析投放对象" width="560px">
      <el-input v-model="importTextRaw" type="textarea" :rows="6" placeholder="粘贴 Google Play 链接文本（跑包）..." />
      <div style="margin-top:8px;display:flex;gap:8px;">
        <el-input v-model="importPrefix" placeholder="前缀（可选）" size="small" style="width:140px" />
        <el-input v-model="importSuffix" placeholder="后缀（可选）" size="small" style="width:140px" />
      </div>
      <template #footer>
        <el-button @click="importVisible=false">取消</el-button>
        <el-button type="primary" @click="handleImportText">解析并加入</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, reactive, onMounted } from 'vue'
import { useAuthStore } from '../../stores/auth'
import { ttApi } from '../../api/tt'
import { ElMessage } from 'element-plus'
import { copyToClipboard } from '../../utils/clipboard'
import client from '../../api/client'

const auth = useAuthStore()
const items = ref([]); const loading = ref(false)
const page = ref(1); const size = ref(5); const total = ref(0)
const search = ref(''); const filterStatus = ref(''); const filterRegion = ref('')
const filterArchived = ref(''); const filterRunner = ref(null)
const dialogVisible = ref(false); const editingId = ref(null); const saving = ref(false)
const checkingId = ref(null)
const bcOptions = ref([]); const ttUsers = ref([]); const salesOptions = ref([]); const regionOptions = ref([])
const form = reactive({ product_name:'', kpi:'', region:'', status:'active', bc_id:null, sales_person_id:null, agency_ratio:0, customer:'', runner_ids:[] })
const formPackages = ref([])
const expanded = ref({})
const importVisible = ref(false); const importTextRaw = ref(''); const importPrefix = ref(''); const importSuffix = ref('')

function toggleExpand(id) { expanded.value[id] = !expanded.value[id] }
async function copy(val) { if (!val) return; await copyToClipboard(val); ElMessage.success('已复制 ✓') }

let searchTimer = null
function onSearch() { clearTimeout(searchTimer); searchTimer = setTimeout(loadData, 300) }
function addPkgRow(type) { formPackages.value.push({ type, series_name:'', package_name:'', url:'', status:'' }) }

async function loadData() {
  loading.value = true
  try {
    const p = { page: page.value, size: size.value }
    if (search.value) p.search = search.value
    if (filterStatus.value) p.status = filterStatus.value
    if (filterRegion.value) p.region = filterRegion.value
    if (filterRunner.value) p.runner = filterRunner.value
    if (filterArchived.value) p.archived = filterArchived.value
    const res = await ttApi.listProducts(p)
    items.value = res.items || []; total.value = res.total || 0
  } finally { loading.value = false }
}

async function loadOptions() {
  try { const r = await ttApi.bcOptions(); bcOptions.value = r.data || [] } catch(e) {}
  try { const r = await ttApi.listTtUsers(); ttUsers.value = r.users || [] } catch(e) {}
  try { const r = await client.get('/sales-persons/list'); salesOptions.value = r.sales_persons || [] } catch(e) {}
  try { const r = await client.get('/regions/list'); regionOptions.value = (r.regions || []).map(r => typeof r === 'string' ? { name: r } : r) } catch(e) {}
}

async function refreshOptions() {
  try { const r = await ttApi.bcOptions(); bcOptions.value = r.data || [] } catch(e) {}
  try { const r = await client.get('/sales-persons/list'); salesOptions.value = r.sales_persons || [] } catch(e) {}
  try { const r = await client.get('/regions/list'); regionOptions.value = (r.regions || []).map(r => typeof r === 'string' ? { name: r } : r) } catch(e) {}
}

async function openCreate() {
  editingId.value = null
  Object.assign(form, { product_name:'', kpi:'', region:'', status:'active', bc_id:null, sales_person_id:null, agency_ratio:0, customer:'', runner_ids:[] })
  formPackages.value = []
  await refreshOptions()
  dialogVisible.value = true
}

async function openEdit(row) {
  editingId.value = row.id
  Object.assign(form, {
    product_name: row.product_name, kpi: row.kpi, region: row.region, status: row.status || 'active',
    bc_id: row.bc ? row.bc.id : row.bc_id, sales_person_id: row.sales_person_id,
    agency_ratio: row.agency_ratio, customer: row.customer || '', runner_ids: (row.runners||[]).map(r => r.id),
  })
  formPackages.value = (row.packages||[]).map(p => ({ type: p.type, series_name: p.series_name, package_name: p.package_name, url: p.url, status: p.status }))
  await refreshOptions()
  dialogVisible.value = true
}

async function handleSave() {
  if (!form.product_name) return ElMessage.warning('请输入产品名')
  if (!editingId.value && auth.user && !form.runner_ids.includes(auth.user.id)) form.runner_ids.push(auth.user.id)
  saving.value = true
  try {
    if (form.region && !regionOptions.value.some(r => r.name === form.region)) {
      await client.post('/regions/create', { name: form.region, timezone: '' })
      try { const r = await client.get('/regions/list'); regionOptions.value = (r.regions || []).map(r => typeof r === 'string' ? { name: r } : r) } catch(e) {}
    }
    if (typeof form.sales_person_id === 'string' && form.sales_person_id) {
      const res = await client.post('/sales-persons/create', { name: form.sales_person_id })
      form.sales_person_id = res.id
    }
    const data = { ...form, packages: formPackages.value }
    editingId.value ? await ttApi.updateProduct(editingId.value, data) : await ttApi.createProduct(data)
    ElMessage.success(editingId.value ? '已更新' : '已创建')
    dialogVisible.value = false; loadData()
  } catch(e) { ElMessage.error(e.response?.data?.error || '保存失败') }
  finally { saving.value = false }
}

async function handleCheckDelist(item) {
  checkingId.value = item.id
  try {
    const res = await ttApi.checkDelist(item.id)
    const results = res.results || []
    const delisted = results.filter(r => r.is_delisted).length
    ElMessage.success(`检测完成：${results.length} 个跑包，${delisted} 个掉包`)
    loadData()
  } catch(e) { ElMessage.error(e.response?.data?.error || '检测失败') }
  finally { checkingId.value = null }
}

function openImportText() { importTextRaw.value = ''; importPrefix.value = ''; importSuffix.value = ''; importVisible.value = true }

async function handleImportText() {
  if (!importTextRaw.value.trim()) return ElMessage.warning('请粘贴文本')
  try {
    const res = await ttApi.importText({ text: importTextRaw.value, prefix: importPrefix.value, suffix: importSuffix.value })
    const parsed = res.parsed || []
    if (!parsed.length) return ElMessage.warning('未解析到 Google Play 链接')
    for (const p of parsed) formPackages.value.push(p)
    importVisible.value = false
    ElMessage.success(`已解析 ${parsed.length} 个跑包`)
  } catch(e) { ElMessage.error(e.response?.data?.error || '解析失败') }
}

function handleDelete(id) { ttApi.deleteProduct(id).then(() => { ElMessage.success('已删除'); loadData() }) }
function handleRestore(id) { ttApi.restoreProduct(id).then(() => { ElMessage.success('已恢复'); loadData() }) }

onMounted(() => { loadOptions(); loadData() })
</script>

<style scoped>
.page-wrapper { background:#f5f6f8;padding:24px;min-height:100%;display:flex;flex-direction:column;gap:16px; }
.page-header { display:flex;justify-content:space-between;align-items:center; }
.page-title { margin:0;font-size:20px;font-weight:700;color:#1f2937; }
.filter-card { background:#f8f9fa;border-radius:12px;padding:14px 16px;display:flex;align-items:center;gap:12px;flex-wrap:wrap;border:1px solid #e5e7eb; }
.total-badge { font-size:13px;color:#6b7280;font-weight:500;white-space:nowrap;padding:4px 10px;background:#fff;border-radius:6px;border:1px solid #e5e7eb; }
.product-list { flex:1;min-height:0;overflow-y:auto; }
.product-card { margin-bottom:12px;border-radius:12px;border:1px solid #e5e7eb;overflow:hidden; }
.product-card.is-paused { opacity:0.7; }
.product-card-inner { padding:16px; }
.product-card-header { display:flex;justify-content:space-between;align-items:flex-start;cursor:pointer;gap:16px; }
.product-card-info { flex:1;min-width:0; }
.product-card-tags { display:flex;align-items:center;gap:8px;margin-bottom:6px;flex-wrap:wrap; }
.status-dot { width:8px;height:8px;border-radius:50%;display:inline-block;flex-shrink:0; }
.dot-active { background:#059669; }
.dot-paused { background:#dc2626; }
.product-name { font-size:15px;color:#1f2937; }
.tag-sales { background:#ecfdf5 !important;color:#059669 !important;border-color:#a7f3d0 !important; }
.tag-kpi { background:#fffbeb !important;color:#d97706 !important;border-color:#fde68a !important; }
.tag-region { background:#eff6ff !important;color:#2563eb !important;border-color:#bfdbfe !important; }
.tag-customer { background:#fdf4ff !important;color:#c026d3 !important;border-color:#f5d0fe !important; }
.product-card-bc { margin-bottom:4px; }
.product-card-runners { font-size:12px;color:#9ca3af;margin-bottom:2px; }
.product-card-lines { font-size:12px;color:#9ca3af; }
.expand-hint { display:inline-block;margin-left:8px;color:#0891b2;font-size:11px;cursor:pointer; }
.product-card-actions { display:flex;gap:4px;flex-shrink:0; }
.product-card-expand { margin-top:14px;padding-top:14px;border-top:1px solid #f3f4f6; }
.pkg-table, .dialog-pkg-table { border-radius:8px;overflow:hidden; }
.copy-link { cursor:pointer;color:#0891b2;font-size:13px; }
.copy-link:hover { color:#06b6d4;text-decoration:underline; }
.no-data { color:#9ca3af;font-size:12px; }
.no-lines { color:#9ca3af;font-size:13px;padding:8px 0;text-align:center; }
.pagination-row { display:flex;justify-content:center;gap:8px;margin-top:16px;padding-bottom:4px; }
.add-btn { margin-bottom:10px; }
</style>
