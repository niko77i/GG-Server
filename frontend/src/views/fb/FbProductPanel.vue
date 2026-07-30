<template>
  <div class="fb-panel">
    <div class="panel-header"><h2>📦 FB产品管理</h2><el-button type="primary" @click="openCreate">➕ 新增产品</el-button></div>
    <div class="filter-bar">
      <el-input v-model="search" placeholder="搜索产品名" clearable style="width:200px" @input="onSearch" />
      <el-select v-model="filterStatus" placeholder="全部状态" clearable style="width:120px" @change="loadData">
        <el-option label="正常" value="active" /><el-option label="暂停" value="paused" />
      </el-select>
      <el-button @click="loadData">🔄 刷新</el-button>
    </div>
    <el-table :data="items" stripe border v-loading="loading">
      <el-table-column prop="product_name" label="产品名" min-width="120" />
      <el-table-column prop="kpi" label="KPI" width="100" />
      <el-table-column prop="region" label="地区" width="80" />
      <el-table-column label="在跑BM" min-width="140"><template #default="{row}">{{ row.bms?.map(b=>b.name).join(', ') }}</template></el-table-column>
      <el-table-column prop="agency_ratio" label="代投比例" width="90" />
      <el-table-column prop="status" label="状态" width="70"><template #default="{row}"><el-tag :type="row.status==='paused'?'warning':'success'" size="small">{{ row.status==='paused'?'暂停':'正常' }}</el-tag></template></el-table-column>
      <el-table-column label="操作" width="180" fixed="right">
        <template #default="{row}">
          <el-button size="small" type="primary" link @click="openEdit(row)">编辑</el-button>
          <el-button size="small" type="danger" link @click="handleDelete(row.id)">删除</el-button>
        </template>
      </el-table-column>
    </el-table>
    <el-pagination v-if="total>size" v-model:current-page="page" :page-size="size" :total="total" layout="prev,pager,next" @current-change="loadData" style="margin-top:16px;justify-content:flex-end" />

    <el-dialog v-model="dialogVisible" :title="editingId?'编辑产品':'新增产品'" width="650px">
      <el-form :model="form" label-width="80px">
        <el-row :gutter="16">
          <el-col :span="12"><el-form-item label="产品名" required><el-input v-model="form.product_name" /></el-form-item></el-col>
          <el-col :span="12"><el-form-item label="KPI"><el-input v-model="form.kpi" /></el-form-item></el-col>
        </el-row>
        <el-row :gutter="16">
          <el-col :span="12"><el-form-item label="地区"><el-select v-model="form.region" clearable filterable style="width:100%"><el-option v-for="r in regionOptions" :key="r.name" :label="r.name" :value="r.name" /></el-select></el-form-item></el-col>
          <el-col :span="12"><el-form-item label="商务"><el-select v-model="form.sales_person_id" clearable style="width:100%"><el-option v-for="s in salesOptions" :key="s.id" :label="s.name" :value="s.id" /></el-select></el-form-item></el-col>
        </el-row>
        <el-row :gutter="16">
          <el-col :span="12"><el-form-item label="代投比例"><el-input-number v-model="form.agency_ratio" :min="0" :max="100" style="width:100%" /></el-form-item></el-col>
          <el-col :span="12"><el-form-item label="状态"><el-select v-model="form.status" style="width:100%"><el-option label="正常" value="active" /><el-option label="暂停" value="paused" /></el-select></el-form-item></el-col>
        </el-row>
        <el-form-item label="在跑BM"><el-select v-model="form.bm_ids" multiple style="width:100%"><el-option v-for="b in bmOptions" :key="b.id" :label="b.name+'('+b.bm_id+')'" :value="b.id" /></el-select></el-form-item>
        <el-form-item label="在跑人员"><el-select v-model="form.runner_ids" multiple style="width:100%"><el-option v-for="u in fbUsers" :key="u.id" :label="u.display_name||u.username" :value="u.id" /></el-select></el-form-item>

        <!-- 线名子表 -->
        <el-divider content-position="left">线名管理</el-divider>
        <el-button size="small" type="success" @click="addLineRow" style="margin-bottom:8px">➕ 添加线名</el-button>
        <el-table :data="formLines" border size="small">
          <el-table-column prop="line_name" label="线名" min-width="120"><template #default="{row,$index}"><el-input v-model="formLines[$index].line_name" size="small" /></template></el-table-column>
          <el-table-column prop="link" label="链接" min-width="160"><template #default="{row,$index}"><el-input v-model="formLines[$index].link" size="small" /></template></el-table-column>
          <el-table-column label="像素" width="160">
            <template #default="{row,$index}">
              <el-select v-model="formLines[$index].pixel_id" size="small" clearable style="width:100%">
                <el-option-group v-for="pbm in pixelBmGroups" :key="pbm.id" :label="pbm.name+'('+pbm.bm_id+')'">
                  <el-option v-for="px in pbm.pixels" :key="px.id" :label="px.pixel_name+'('+px.pixel_id+')'" :value="px.id" />
                </el-option-group>
              </el-select>
            </template>
          </el-table-column>
          <el-table-column label="操作" width="70"><template #default="{row,$index}"><el-button size="small" type="danger" @click="formLines.splice($index,1)">删除</el-button></template></el-table-column>
        </el-table>
      </el-form>
      <template #footer><el-button @click="dialogVisible=false">取消</el-button><el-button type="primary" :loading="saving" @click="handleSave">保存</el-button></template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, reactive, onMounted } from 'vue'
import { fbApi } from '../../api/fb'
import { ElMessage } from 'element-plus'
import client from '../../api/client'

const items = ref([]); const loading = ref(false); const page = ref(1); const size = ref(50); const total = ref(0)
const search = ref(''); const filterStatus = ref('')
const dialogVisible = ref(false); const editingId = ref(null); const saving = ref(false)
const bmOptions = ref([]); const fbUsers = ref([]); const salesOptions = ref([]); const regionOptions = ref([])
const form = reactive({ product_name:'', kpi:'', region:'', status:'active', sales_person_id:null, agency_ratio:0, bm_ids:[], runner_ids:[] })
const formLines = ref([])
const pixelBmGroups = ref([])

let searchTimer = null
function onSearch() { clearTimeout(searchTimer); searchTimer = setTimeout(loadData, 300) }
function addLineRow() { formLines.value.push({ line_name:'', link:'', pixel_id:null }) }

async function loadData() {
  loading.value = true
  try {
    const p = { page:page.value, size:size.value }
    if (search.value) p.search = search.value
    if (filterStatus.value) p.status = filterStatus.value
    const res = await fbApi.listProducts(p)
    items.value = res.data.items; total.value = res.data.total
  } finally { loading.value = false }
}
async function loadOptions() {
  const [bmRes, pxBmRes, userRes, salesRes, regionsRes] = await Promise.all([
    fbApi.bmOptions(),
    fbApi.pixelBmOptions(),
    client.get('/api/auth/names'),
    client.get('/api/sales-persons/list'),
    client.get('/api/regions/list'),
  ])
  bmOptions.value = bmRes.data || []
  // fbUsers: /api/auth/names 返回 {users: [...]}
  fbUsers.value = (userRes.users || []).filter(u => u.platform === 'fb' || !u.platform)
  // salesOptions: /api/sales-persons/list 返回 {sales_persons: [...]}
  salesOptions.value = salesRes.sales_persons || []
  // regionOptions: /api/regions/list 返回 {regions: [...]}
  regionOptions.value = (regionsRes.regions || []).map(r => typeof r === 'string' ? { name: r } : r)
  // 加载像素BM分组
  for (const pb of (pxBmRes.data || [])) {
    const pxRes = await fbApi.listPixels(pb.id)
    pixelBmGroups.value.push({ id: pb.id, name: pb.name, bm_id: pb.bm_id, pixels: pxRes.data || [] })
  }
}

function openCreate() {
  editingId.value = null; form.product_name=''; form.kpi=''; form.region=''; form.status='active'; form.sales_person_id=null; form.agency_ratio=0; form.bm_ids=[]; form.runner_ids=[]
  formLines.value = []; dialogVisible.value = true
}
function openEdit(row) {
  editingId.value = row.id; form.product_name = row.product_name; form.kpi = row.kpi; form.region = row.region; form.status = row.status || 'active'
  form.sales_person_id = row.sales_person_id; form.agency_ratio = row.agency_ratio
  form.bm_ids = (row.bms||[]).map(b=>b.id); form.runner_ids = (row.runners||[]).map(r=>r.id)
  formLines.value = (row.lines||[]).map(l=>({ line_name:l.line_name, link:l.link, pixel_id:l.pixel_id }))
  dialogVisible.value = true
}
async function handleSave() {
  if (!form.product_name) return ElMessage.warning('请输入产品名')
  saving.value = true
  try {
    const data = { ...form, lines: formLines.value }
    if (editingId.value) {
      await fbApi.updateProduct(editingId.value, data)
    } else {
      await fbApi.createProduct(data)
    }
    ElMessage.success(editingId.value?'已更新':'已创建'); dialogVisible.value = false; loadData()
  } catch(e) { ElMessage.error(e.response?.data?.error||'保存失败') }
  finally { saving.value = false }
}
async function handleDelete(id) { await fbApi.deleteProduct(id); ElMessage.success('已删除'); loadData() }

onMounted(() => { loadOptions(); loadData() })
</script>

<style scoped>
.fb-panel{padding:20px}.panel-header{display:flex;justify-content:space-between;align-items:center;margin-bottom:16px}.panel-header h2{margin:0;font-size:18px}.filter-bar{display:flex;gap:12px;margin-bottom:16px;align-items:center}
</style>
