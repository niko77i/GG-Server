<template>
  <div style="display:flex;flex-direction:column;height:100%;">
    <!-- 工具栏 -->
    <div style="flex-shrink:0;display:flex;gap:10px;margin-bottom:12px;flex-wrap:wrap;align-items:center;">
      <el-button type="primary" @click="openCreate">➕ 新增产品</el-button>
      <el-radio-group v-model="runnerFilter" @change="loadData" size="small">
        <el-radio-button value="mine">我在跑的</el-radio-button>
        <el-radio-button value="all">全部产品</el-radio-button>
      </el-radio-group>
      <el-select v-model="filterRegion" placeholder="全部地区" clearable size="small" style="width:120px" @change="loadData">
        <el-option v-for="r in regionOptions" :key="r.name" :label="r.name" :value="r.name" />
      </el-select>
      <el-input v-model="search" placeholder="搜索产品或KPI..." @input="onSearch" clearable size="small" style="flex:1;min-width:160px" />
      <el-radio-group v-model="filterStatus" size="small" @change="loadData">
        <el-radio-button value="">正常</el-radio-button>
        <el-radio-button value="paused">已暂停</el-radio-button>
      </el-radio-group>
      <span style="font-size:13px;color:#6b7280">共 {{ total }} 个</span>
    </div>

    <!-- 产品列表 -->
    <div style="flex:1;min-height:0;overflow-y:auto;">
      <el-card v-for="item in items" :key="item.id" style="margin-bottom:12px" :body-style="{ padding:'12px 16px' }"
        :class="{ 'is-paused': item.status === 'paused' }">
        <div style="display:flex;justify-content:space-between;align-items:flex-start">
          <div style="flex:1;cursor:pointer" @click="openDetail(item)">
            <div style="display:flex;align-items:center;gap:8px;margin-bottom:4px">
              <span :style="{ width:'8px',height:'8px',borderRadius:'50%',background: item.status==='paused' ? '#dc2626' : '#059669' }"></span>
              <strong>{{ item.product_name }}</strong>
              <el-tag v-if="item.sales_person_name" size="small" type="success">💼 {{ item.sales_person_name }}</el-tag>
              <el-tag v-if="item.kpi" size="small" type="warning">{{ item.kpi }}</el-tag>
              <el-tag v-if="item.region" size="small" type="primary">{{ item.region }}</el-tag>
              <el-tag v-if="item.agency_ratio" size="small">📊 {{ item.agency_ratio }}%</el-tag>
            </div>
            <div v-if="item.bms?.length" style="margin-bottom:2px">
              <el-tag v-for="b in item.bms" :key="b.id" size="small" type="info" style="margin-right:4px">🏢 {{ b.name }}</el-tag>
            </div>
            <div v-if="item.runners?.length" style="font-size:12px;color:#9ca3af">
              在跑: {{ item.runners.map(r=>r.display_name||r.username).join('、') }}
            </div>
            <div style="font-size:12px;color:#9ca3af;margin-top:2px">
              线名: {{ (item.lines||[]).map(l=>l.line_name).join(', ') || '无' }}
            </div>
          </div>
          <div style="display:flex;gap:4px;flex-shrink:0">
            <el-button size="small" @click="openEdit(item)">编辑</el-button>
            <el-button size="small" @click="togglePause(item)" :type="item.status==='paused'?'success':'warning'">
              {{ item.status==='paused'?'恢复':'暂停' }}
            </el-button>
            <el-popconfirm title="确定删除？" @confirm="handleDelete(item.id)">
              <template #reference><el-button size="small" type="danger">删除</el-button></template>
            </el-popconfirm>
          </div>
        </div>
      </el-card>

      <el-empty v-if="!items.length" description="暂无产品" />

      <div v-if="total>size" style="display:flex;justify-content:center;gap:8px;margin-top:12px">
        <el-pagination v-model:current-page="page" :page-size="size" :total="total" background
          layout="prev,pager,next" size="small" :pager-count="7" @current-change="loadData" />
        <el-select v-model="size" @change="page=1;loadData()" size="small" style="width:90px">
          <el-option v-for="s in [5,10,20,50]" :key="s" :label="s+'条/页'" :value="s" />
        </el-select>
      </div>
    </div>

    <!-- 产品弹窗 -->
    <el-dialog v-model="dialogVisible" :title="editingId?'编辑产品':'新增产品'" width="680px" top="3vh">
      <el-form :model="form" label-width="80px">
        <el-row :gutter="16">
          <el-col :span="12"><el-form-item label="产品名" required><el-input v-model="form.product_name" /></el-form-item></el-col>
          <el-col :span="12"><el-form-item label="KPI"><el-input v-model="form.kpi" /></el-form-item></el-col>
        </el-row>
        <el-row :gutter="16">
          <el-col :span="12">
            <el-form-item label="地区">
              <el-select v-model="form.region" clearable filterable style="width:100%">
                <el-option v-for="r in regionOptions" :key="r.name" :label="r.name" :value="r.name" />
              </el-select>
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="商务">
              <el-select v-model="form.sales_person_id" clearable filterable style="width:100%">
                <el-option v-for="s in salesOptions" :key="s.id" :label="s.name" :value="s.id" />
              </el-select>
            </el-form-item>
          </el-col>
        </el-row>
        <el-row :gutter="16">
          <el-col :span="12">
            <el-form-item label="代投比例"><el-input-number v-model="form.agency_ratio" :min="0" :max="100" style="width:100%" /></el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="状态">
              <el-select v-model="form.status" style="width:100%">
                <el-option label="正常" value="active" /><el-option label="暂停" value="paused" />
              </el-select>
            </el-form-item>
          </el-col>
        </el-row>
        <el-form-item label="在跑BM">
          <el-select v-model="form.bm_ids" multiple filterable style="width:100%">
            <el-option v-for="b in bmOptions" :key="b.id" :label="b.name+' ('+b.bm_id+')'" :value="b.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="在跑人员">
          <el-select v-model="form.runner_ids" multiple filterable style="width:100%">
            <el-option v-for="u in fbUsers" :key="u.id" :label="(u.display_name||u.username)+' ('+u.username+')'" :value="u.id" />
          </el-select>
        </el-form-item>

        <el-divider content-position="left">线名管理</el-divider>
        <el-button size="small" type="success" @click="addLineRow" style="margin-bottom:8px">➕ 添加线名</el-button>
        <el-table :data="formLines" border size="small">
          <el-table-column label="线名" min-width="120">
            <template #default="{row,$index}"><el-input v-model="formLines[$index].line_name" size="small" /></template>
          </el-table-column>
          <el-table-column label="链接" min-width="160">
            <template #default="{row,$index}"><el-input v-model="formLines[$index].link" size="small" /></template>
          </el-table-column>
          <el-table-column label="像素" width="200">
            <template #default="{row,$index}">
              <el-select v-model="formLines[$index].pixel_id" size="small" clearable style="width:100%">
                <el-option-group v-for="pbm in pixelBmGroups" :key="pbm.id" :label="pbm.name+'('+pbm.bm_id+')'">
                  <el-option v-for="px in pbm.pixels" :key="px.id" :label="px.pixel_name+'('+px.pixel_id+')'" :value="px.id" />
                </el-option-group>
              </el-select>
            </template>
          </el-table-column>
          <el-table-column label="操作" width="70">
            <template #default="{ $index }"><el-button size="small" type="danger" @click="formLines.splice($index,1)">删除</el-button></template>
          </el-table-column>
        </el-table>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible=false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="handleSave">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, reactive, onMounted } from 'vue'
import { useAuthStore } from '../../stores/auth'
import { fbApi } from '../../api/fb'
import { ElMessage } from 'element-plus'
import client from '../../api/client'

const auth = useAuthStore()
const items = ref([]); const loading = ref(false)
const page = ref(1); const size = ref(5); const total = ref(0)
const search = ref(''); const filterStatus = ref(''); const filterRegion = ref('')
const runnerFilter = ref('mine')
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
    const p = { page: page.value, size: size.value }
    if (search.value) p.search = search.value
    if (filterStatus.value) p.status = filterStatus.value
    if (filterRegion.value) p.region = filterRegion.value
    if (runnerFilter.value === 'mine') p.runner = auth.user?.id
    const res = await fbApi.listProducts(p)
    items.value = res.items || []; total.value = res.total || 0
  } finally { loading.value = false }
}

async function loadOptions() {
  try { const r = await fbApi.bmOptions(); bmOptions.value = r.data || [] } catch(e) {}
  try { const r = await fbApi.listFbUsers(); fbUsers.value = r.users || [] } catch(e) {}
  try { const r = await client.get('/sales-persons/list'); salesOptions.value = r.sales_persons || [] } catch(e) {}
  try { const r = await client.get('/regions/list'); regionOptions.value = (r.regions || []).map(r => typeof r === 'string' ? { name: r } : r) } catch(e) {}
  try {
    const pxBmRes = await fbApi.pixelBmOptions()
    pixelBmGroups.value = []
    for (const pb of (pxBmRes.data || [])) {
      try { const pxRes = await fbApi.listPixels(pb.id); pixelBmGroups.value.push({ id: pb.id, name: pb.name, bm_id: pb.bm_id, pixels: pxRes.data || [] }) } catch(e) {}
    }
  } catch(e) {}
}

function openCreate() {
  editingId.value = null
  Object.assign(form, { product_name:'', kpi:'', region:'', status:'active', sales_person_id:null, agency_ratio:0, bm_ids:[], runner_ids:[] })
  formLines.value = []
  dialogVisible.value = true
}

function openEdit(row) {
  editingId.value = row.id
  Object.assign(form, { product_name: row.product_name, kpi: row.kpi, region: row.region, status: row.status || 'active', sales_person_id: row.sales_person_id, agency_ratio: row.agency_ratio, bm_ids: (row.bms||[]).map(b=>b.id), runner_ids: (row.runners||[]).map(r=>r.id) })
  formLines.value = (row.lines||[]).map(l=>({ line_name:l.line_name, link:l.link, pixel_id:l.pixel_id }))
  dialogVisible.value = true
}

function openDetail(row) { openEdit(row) }

async function handleSave() {
  if (!form.product_name) return ElMessage.warning('请输入产品名')
  if (!editingId.value && auth.user && !form.runner_ids.includes(auth.user.id)) form.runner_ids.push(auth.user.id)
  saving.value = true
  try {
    const data = { ...form, lines: formLines.value }
    editingId.value ? await fbApi.updateProduct(editingId.value, data) : await fbApi.createProduct(data)
    ElMessage.success(editingId.value?'已更新':'已创建')
    dialogVisible.value = false; loadData()
  } catch(e) { ElMessage.error(e.response?.data?.error||'保存失败') }
  finally { saving.value = false }
}

async function togglePause(item) {
  const newStatus = item.status === 'paused' ? 'active' : 'paused'
  await fbApi.updateProduct(item.id, { status: newStatus })
  ElMessage.success(newStatus === 'paused' ? '已暂停' : '已恢复')
  loadData()
}

function handleDelete(id) { fbApi.deleteProduct(id).then(() => { ElMessage.success('已删除'); loadData() }) }

onMounted(() => { loadOptions(); loadData() })
</script>

<style scoped>
.is-paused { opacity: 0.6; }
</style>
