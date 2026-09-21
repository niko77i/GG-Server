<template>
  <div style="display:flex;flex-direction:column;height:100%;">
    <!-- 页面标题 -->
    <div style="flex-shrink:0;margin-bottom:12px;">
      <h2 style="margin:0;font-size:18px;font-weight:600;">TT 产品管理</h2>
    </div>
    <!-- 工具栏 — 固定 -->
    <div style="flex-shrink:0;display:flex;gap:10px;margin-bottom:12px;flex-wrap:wrap;align-items:center;">
      <el-button v-if="!auth.isViewer" type="primary" @click="openCreate">➕ 新增产品</el-button>
      <el-input v-model="search" placeholder="搜索产品..." @input="onSearch" style="flex:1;min-width:160px;" clearable />
      <el-select v-model="filterRegion" @change="loadData" placeholder="全部地区" clearable style="width:120px;" filterable>
        <el-option v-for="r in regionOptions" :key="r.name" :label="r.name" :value="r.name" />
      </el-select>
      <el-select v-model="filterRunner" @change="loadData" placeholder="按在跑人筛选" clearable filterable style="width:160px;">
        <el-option v-for="u in ttUsers" :key="u.id" :label="(u.display_name||u.username)+' ('+u.username+')'" :value="u.id" />
      </el-select>
      <el-radio-group v-model="filterStatus" @change="loadData" size="small">
        <el-radio-button value="active">正常</el-radio-button>
        <el-radio-button value="paused">已暂停</el-radio-button>
      </el-radio-group>
      <el-radio-group v-model="filterArchived" @change="loadData" size="small">
        <el-radio-button value="">在用</el-radio-button>
        <el-radio-button value="1">已归档</el-radio-button>
      </el-radio-group>
    </div>

    <!-- 产品卡片列表 — 滚动区 -->
    <div style="flex:1;min-height:0;overflow-y:auto;" v-loading="loading">
      <TtProductCard
        v-for="p in items" :key="p.id"
        :product="p"
        :custom-name="customName"
        @edit="openEdit"
        @add-pkg="showAddPkg"
        @del="handleDelete"
        @toggle-pause="togglePause"
        @restore="handleRestore"
        @refresh="loadData"
      />

      <el-empty v-if="!items.length" description="暂无产品" />

      <div v-if="total > size" style="display:flex;align-items:center;justify-content:center;gap:8px;margin-top:12px;">
        <el-pagination v-model:current-page="page" :page-size="size" :total="total" background
          layout="prev,pager,next" size="small" :pager-count="7" @current-change="loadData" />
        <el-select v-model="size" @change="page = 1; loadData()" size="small" style="width:90px;" filterable>
          <el-option v-for="s in [5,10,20,50]" :key="s" :label="s+'条/页'" :value="s" />
        </el-select>
      </div>
    </div>

    <!-- 新增/编辑产品弹窗（仅产品字段） -->
    <el-dialog v-model="dialogVisible" :title="editingId ? '✏️ 编辑产品' : '➕ 新增产品'" width="480px" top="3vh">
      <el-form label-position="top">
        <el-form-item label="产品 / 群名" required>
          <el-input v-model="form.product_name" />
        </el-form-item>
        <el-form-item label="KPI">
          <el-input v-model="form.kpi" />
        </el-form-item>
        <el-form-item label="地区">
          <el-select v-model="form.region" filterable clearable allow-create placeholder="选择地区" style="width:100%;">
            <el-option v-for="r in regionOptions" :key="r.name" :label="r.name" :value="r.name" />
          </el-select>
        </el-form-item>
        <el-form-item label="客户">
          <el-input v-model="form.customer" placeholder="产品所属客户" />
        </el-form-item>
        <el-form-item label="商务">
          <el-select v-model="form.sales_person_id" filterable clearable allow-create placeholder="选择商务人员" style="width:100%;">
            <el-option v-for="s in salesOptions" :key="s.id" :label="s.name" :value="s.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="代投比例">
          <el-input v-model.number="form.agency_ratio" placeholder="数字，如 6 表示 6%" />
        </el-form-item>
        <el-form-item label="所属 BC">
          <el-select v-model="form.bc_id" clearable placeholder="（未分配）" style="width:100%;" filterable>
            <el-option v-for="b in bcOptions" :key="b.id" :label="b.name + ' (' + b.bc_id + ')'" :value="b.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="状态">
          <el-select v-model="form.status" style="width:100%;">
            <el-option label="正常" value="active" />
            <el-option label="暂停" value="paused" />
          </el-select>
        </el-form-item>
        <el-form-item label="在跑人员">
          <el-select v-model="form.runner_ids" multiple filterable style="width:100%;">
            <el-option v-for="u in ttUsers" :key="u.id" :label="(u.display_name||u.username)+' ('+u.username+')'" :value="u.id" />
          </el-select>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible=false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="handleSave">💾 保存</el-button>
      </template>
    </el-dialog>

    <!-- 独立添加包弹窗 -->
    <TtAddPackageModal v-model:visible="addPkgVisible" :prod-id="addPkgProdId" @saved="loadData" />
  </div>
</template>

<script setup>
import { ref, reactive, onMounted } from 'vue'
import { useAuthStore } from '../../stores/auth'
import { ttApi } from '../../api/tt'
import TtProductCard from '../../components/TtProductCard.vue'
import TtAddPackageModal from '../../components/TtAddPackageModal.vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import client from '../../api/client'

const auth = useAuthStore()
const items = ref([]); const loading = ref(false)
const page = ref(1); const size = ref(5); const total = ref(0)
const search = ref(''); const filterStatus = ref('active'); const filterRegion = ref('')
const filterArchived = ref(''); const filterRunner = ref(null)
const dialogVisible = ref(false); const editingId = ref(null); const saving = ref(false)
const bcOptions = ref([]); const ttUsers = ref([]); const salesOptions = ref([]); const regionOptions = ref([])
const form = reactive({ product_name:'', kpi:'', region:'', status:'active', bc_id:null, sales_person_id:null, agency_ratio:null, customer:'', runner_ids:[] })
const addPkgVisible = ref(false); const addPkgProdId = ref(null)
const customName = ref('')

let searchTimer = null
function onSearch() { clearTimeout(searchTimer); searchTimer = setTimeout(() => { page.value = 1; loadData() }, 300) }

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
  } catch(e) { ElMessage.error(e.response?.data?.error || '加载失败') } finally { loading.value = false }
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
  Object.assign(form, { product_name:'', kpi:'', region:'', status:'active', bc_id:null, sales_person_id:null, agency_ratio:null, customer:'', runner_ids:[] })
  await refreshOptions()
  dialogVisible.value = true
}

async function openEdit(id) {
  const row = items.value.find(p => p.id === id)
  if (!row) return
  editingId.value = row.id
  Object.assign(form, {
    product_name: row.product_name, kpi: row.kpi, region: row.region, status: row.status || 'active',
    bc_id: row.bc ? row.bc.id : row.bc_id, sales_person_id: row.sales_person_id,
    agency_ratio: row.agency_ratio, customer: row.customer || '', runner_ids: (row.runners||[]).map(r => r.id),
  })
  await refreshOptions()
  dialogVisible.value = true
}

async function handleSave() {
  if (!form.product_name) return ElMessage.warning('请输入产品名')
  form.agency_ratio = Number(form.agency_ratio) || 0
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
    editingId.value ? await ttApi.updateProduct(editingId.value, { ...form }) : await ttApi.createProduct({ ...form })
    ElMessage.success(editingId.value ? '已更新' : '已创建')
    dialogVisible.value = false; loadData()
  } catch(e) { ElMessage.error(e.response?.data?.error || '保存失败') }
  finally { saving.value = false }
}

async function togglePause({ id, paused }) {
  const msg = paused ? '确定暂停此产品？' : '确定恢复此产品？'
  try { await ElMessageBox.confirm(msg, '确认', { type: 'warning' }) } catch { return }
  try {
    await ttApi.updateProduct(id, { status: paused ? 'paused' : 'active' })
    loadData()
  } catch (e) {
    ElMessage.error(e.response?.data?.error || '操作失败')
  }
}

async function handleDelete(id) {
  try {
    await ElMessageBox.confirm('确定归档此产品？', '确认', { type: 'warning' })
  } catch { return }
  try {
    await ttApi.deleteProduct(id)
    ElMessage.success('已归档')
    loadData()
  } catch (e) {
    ElMessage.error(e.response?.data?.error || '归档失败')
  }
}

function handleRestore(id) {
  ttApi.restoreProduct(id).then(() => { ElMessage.success('已恢复'); loadData() }).catch(e => ElMessage.error(e.response?.data?.error || '恢复失败'))
}

function showAddPkg(id) { addPkgProdId.value = id; addPkgVisible.value = true }

async function loadCustomName() {
  try { const r = await client.get('/auth/custom-name'); customName.value = r.custom_name || '' } catch(e) { customName.value = '' }
}

onMounted(() => { loadOptions(); loadData(); loadCustomName() })
</script>
