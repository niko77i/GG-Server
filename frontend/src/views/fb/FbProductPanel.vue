<template>
  <div class="page-wrapper">
    <!-- 页面头部 -->
    <div class="page-header">
      <h1 class="page-title">产品管理</h1>
      <el-button type="primary" @click="openCreate">新增产品</el-button>
    </div>

    <!-- 统计卡片行 -->
    <el-row v-if="!filterArchived" :gutter="16" class="stats-row">
      <el-col :xs="12" :sm="6">
        <div class="stat-card">
          <div class="stat-number" style="color: #3b82f6">{{ total }}</div>
          <div class="stat-label">总产品</div>
        </div>
      </el-col>
      <el-col :xs="12" :sm="6">
        <div class="stat-card">
          <div class="stat-number" style="color: #059669">{{ items.filter(function(i){return i.status!=='paused'}).length }}</div>
          <div class="stat-label">正常</div>
        </div>
      </el-col>
      <el-col :xs="12" :sm="6">
        <div class="stat-card">
          <div class="stat-number" style="color: #dc2626">{{ items.filter(function(i){return i.status==='paused'}).length }}</div>
          <div class="stat-label">已暂停</div>
        </div>
      </el-col>
      <el-col :xs="12" :sm="6">
        <div class="stat-card">
          <div class="stat-number" style="color: #7c3aed">{{ filterRunner ? total : (runnerFilter === 'mine' ? total : items.filter(function(i){return i.runners && i.runners.some(function(r){return r.id === auth.user.id})}).length) }}</div>
          <div class="stat-label">我在跑的</div>
        </div>
      </el-col>
    </el-row>

    <!-- 筛选栏卡片 -->
    <div class="filter-card">
      <el-radio-group v-if="!filterArchived && !filterRunner" v-model="runnerFilter" @change="loadData" size="small">
        <el-radio-button value="mine">我在跑的</el-radio-button>
        <el-radio-button value="all">全部产品</el-radio-button>
      </el-radio-group>
      <el-select v-model="filterRegion" placeholder="全部地区" clearable size="small" style="width:120px" @change="loadData">
        <el-option v-for="r in regionOptions" :key="r.name" :label="r.name" :value="r.name" />
      </el-select>
      <el-select v-if="!filterArchived" v-model="filterRunner" placeholder="筛选在跑人" clearable filterable size="small" style="width:160px" @change="loadData">
        <el-option v-for="u in fbUsers" :key="u.id" :label="(u.display_name||u.username)+' ('+u.username+')'" :value="u.id" />
      </el-select>
      <el-input v-model="search" placeholder="搜索产品或KPI..." @input="onSearch" clearable size="small" style="flex:1;min-width:160px" />
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

    <!-- 产品列表 -->
    <div class="product-list">
      <el-card
        v-for="item in items"
        :key="item.id"
        class="product-card"
        :class="{ 'is-paused': item.status === 'paused', 'is-archived': filterArchived==='1' }"
        :body-style="{ padding: 0 }"
      >
        <!-- 状态左边框 -->
        <div v-if="filterArchived==='1'" class="archived-indicator"></div>
        <div v-else-if="item.status === 'paused'" class="paused-indicator"></div>

        <!-- 卡片内部 -->
        <div class="product-card-inner">
          <!-- 头部 -- 点击展开 -->
          <div class="product-card-header" @click="toggleExpand(item.id)">
            <div class="product-card-info">
              <div class="product-card-tags">
                <span class="status-dot" :class="filterArchived==='1' ? 'dot-archived' : (item.status === 'paused' ? 'dot-paused' : 'dot-active')"></span>
                <strong class="product-name">{{ item.product_name }}</strong>
                <el-tag v-if="item.sales_person_name" size="small" class="tag-sales">{{ item.sales_person_name }}</el-tag>
                <el-tag v-if="item.kpi" size="small" class="tag-kpi">{{ item.kpi }}</el-tag>
                <el-tag v-if="item.region" size="small" class="tag-region">{{ item.region }}</el-tag>
                <el-tag v-if="item.agency_ratio" size="small" class="tag-ratio">{{ item.agency_ratio }}%</el-tag>
              </div>
              <div v-if="item.bms && item.bms.length" class="product-card-bms">
                <el-tag v-for="b in item.bms" :key="b.id" size="small" type="info">{{ b.name }}</el-tag>
              </div>
              <div v-if="item.runners && item.runners.length" class="product-card-runners">
                在跑: {{ item.runners.map(function(r){return r.display_name||r.username}).join('、') }}
              </div>
              <div class="product-card-lines">
                线名: {{ (item.lines||[]).map(function(l){return l.line_name}).join(', ') || '无' }}
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
                <el-button size="small" @click="togglePause(item)" :type="item.status==='paused'?'success':'warning'">
                  {{ item.status==='paused'?'恢复':'暂停' }}
                </el-button>
                <el-popconfirm title="确定删除？" @confirm="handleDelete(item.id)">
                  <template #reference><el-button size="small" type="danger">删除</el-button></template>
                </el-popconfirm>
              </template>
            </div>
          </div>

          <!-- 展开区 -- 线名列表 -->
          <div v-if="expanded[item.id]" class="product-card-expand" @click.stop>
            <el-table
              v-if="(item.lines||[]).length"
              :data="item.lines"
              border
              size="small"
              class="lines-table"
              :header-cell-style="{ background:'#f8f9fa', color:'#374151', fontWeight:600 }"
            >
              <el-table-column prop="line_name" label="线名" min-width="140">
                <template #default="{ row: ln }">
                  <span class="copy-link" @click="copy(ln.line_name)" :title="'点击复制: '+ln.line_name">{{ ln.line_name }}</span>
                </template>
              </el-table-column>
              <el-table-column prop="link" label="链接" min-width="200">
                <template #default="{ row: ln }">
                  <span v-if="ln.link" class="copy-link" @click="copy(ln.link)" :title="'点击复制: '+ln.link">{{ ln.link }}</span>
                  <span v-else class="no-data">-</span>
                </template>
              </el-table-column>
            </el-table>
            <div v-else class="no-lines">无线名</div>
          </div>
        </div>
      </el-card>

      <el-empty v-if="!items.length" description="暂无产品" />

      <div v-if="total>size" class="pagination-row">
        <el-pagination
          v-model:current-page="page"
          :page-size="size"
          :total="total"
          background
          layout="prev,pager,next"
          size="small"
          :pager-count="7"
          @current-change="loadData"
        />
        <el-select v-model="size" @change="page=1;loadData()" size="small" style="width:90px">
          <el-option v-for="s in [5,10,20,50]" :key="s" :label="s+'条/页'" :value="s" />
        </el-select>
      </div>
    </div>

    <!-- 产品弹窗 -->
    <el-dialog v-model="dialogVisible" :title="editingId?'编辑产品':'新增产品'" width="720px" top="3vh" class="product-dialog">
      <el-form :model="form" label-width="80px">
        <el-row :gutter="16">
          <el-col :span="12"><el-form-item label="产品名" required><el-input v-model="form.product_name" /></el-form-item></el-col>
          <el-col :span="12"><el-form-item label="KPI"><el-input v-model="form.kpi" /></el-form-item></el-col>
        </el-row>
        <el-row :gutter="16">
          <el-col :span="12">
            <el-form-item label="地区">
              <el-select v-model="form.region" clearable filterable allow-create style="width:100%">
                <el-option v-for="r in regionOptions" :key="typeof r === 'string' ? r : r.name" :label="typeof r === 'string' ? r : r.name" :value="typeof r === 'string' ? r : r.name" />
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
        <el-button size="small" type="success" @click="addLineRow" class="add-line-btn">添加线名</el-button>
        <el-table
          :data="formLines"
          border
          size="small"
          class="dialog-lines-table"
          :header-cell-style="{ background:'#f8f9fa', color:'#374151', fontWeight:600 }"
        >
          <el-table-column label="线名" min-width="120">
            <template #default="{row,$index}"><el-input v-model="formLines[$index].line_name" size="small" /></template>
          </el-table-column>
          <el-table-column label="链接" min-width="160">
            <template #default="{row,$index}"><el-input v-model="formLines[$index].link" size="small" /></template>
          </el-table-column>
          <el-table-column label="像素" width="200">
            <template #default="{row,$index}">
              <el-select v-model="formLines[$index].pixel_id" size="small" clearable filterable :filter-method="onPixelFilter" style="width:100%">
                <el-option-group v-for="pbm in filteredPixelBmGroups" :key="pbm.id" :label="pbm.name+'('+pbm.bm_id+')'">
                  <el-option v-for="px in pbm.pixels" :key="px.id" :label="px.pixel_name+'('+px.pixel_id+')'" :value="px.id" />
                </el-option-group>
              </el-select>
            </template>
          </el-table-column>
          <el-table-column label="操作" width="70" align="center">
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
import { ref, reactive, computed, onMounted } from 'vue'
import { useAuthStore } from '../../stores/auth'
import { fbApi } from '../../api/fb'
import { ElMessage } from 'element-plus'
import { copyToClipboard } from '../../utils/clipboard'
import client from '../../api/client'

const auth = useAuthStore()
const items = ref([]); const loading = ref(false)
const page = ref(1); const size = ref(5); const total = ref(0)
const search = ref(''); const filterStatus = ref(''); const filterRegion = ref('')
const filterArchived = ref(''); const filterRunner = ref(null)
const runnerFilter = ref('mine')
const dialogVisible = ref(false); const editingId = ref(null); const saving = ref(false)
const bmOptions = ref([]); const fbUsers = ref([]); const salesOptions = ref([]); const regionOptions = ref([])
const form = reactive({ product_name:'', kpi:'', region:'', status:'active', sales_person_id:null, agency_ratio:0, bm_ids:[], runner_ids:[] })
const formLines = ref([])
const pixelBmGroups = ref([])
const pixelFilterQuery = ref('')
const filteredPixelBmGroups = computed(() => {
  if (!pixelFilterQuery.value) return pixelBmGroups.value
  const q = pixelFilterQuery.value.toLowerCase()
  return pixelBmGroups.value
    .map(pbm => ({
      ...pbm,
      pixels: (pbm.pixels || []).filter(px =>
        (px.pixel_name || '').toLowerCase().includes(q) ||
        (px.pixel_id || '').toLowerCase().includes(q)
      )
    }))
    .filter(pbm => pbm.pixels.length > 0)
})
function onPixelFilter(query) { pixelFilterQuery.value = query }
const expanded = ref({})

function toggleExpand(id) { expanded.value[id] = !expanded.value[id] }
async function copy(val) { await copyToClipboard(val); ElMessage.success('已复制 ✓') }

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
    if (filterRunner.value) { p.runner = filterRunner.value }
    else if (runnerFilter.value === 'mine') p.runner = auth.user?.id
    if (filterArchived.value) p.archived = filterArchived.value
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

// 快速刷新地区/商务选项（每次打开弹窗时调用，确保最新）
async function refreshOptions() {
  try { const r = await client.get('/sales-persons/list'); salesOptions.value = r.sales_persons || [] } catch(e) {}
  try { const r = await client.get('/regions/list'); regionOptions.value = (r.regions || []).map(r => typeof r === 'string' ? { name: r } : r) } catch(e) {}
}

async function openCreate() {
  editingId.value = null
  Object.assign(form, { product_name:'', kpi:'', region:'', status:'active', sales_person_id:null, agency_ratio:0, bm_ids:[], runner_ids:[] })
  formLines.value = []
  pixelFilterQuery.value = ''
  await refreshOptions()
  dialogVisible.value = true
}

async function openEdit(row) {
  editingId.value = row.id
  Object.assign(form, { product_name: row.product_name, kpi: row.kpi, region: row.region, status: row.status || 'active', sales_person_id: row.sales_person_id, agency_ratio: row.agency_ratio, bm_ids: (row.bms||[]).map(b=>b.id), runner_ids: (row.runners||[]).map(r=>r.id) })
  formLines.value = (row.lines||[]).map(l=>({ line_name:l.line_name, link:l.link, pixel_id:l.pixel_id }))
  pixelFilterQuery.value = ''
  await refreshOptions()
  dialogVisible.value = true
}

async function handleSave() {
  if (!form.product_name) return ElMessage.warning('请输入产品名')
  if (!editingId.value && auth.user && !form.runner_ids.includes(auth.user.id)) form.runner_ids.push(auth.user.id)
  saving.value = true
  try {
    // 地区：如果是手动输入的新地区，自动创建
    if (form.region && !regionOptions.value.some(r => (typeof r === 'string' ? r : r.name) === form.region)) {
      await client.post('/regions/create', { name: form.region, timezone: '' })
      try { const r = await client.get('/regions/list'); regionOptions.value = (r.regions || []).map(r => typeof r === 'string' ? { name: r } : r) } catch(e) {}
    }
    // 商务：如果是手动输入的新商务（值为字符串表示新名字），先创建再获取 ID
    if (typeof form.sales_person_id === 'string' && form.sales_person_id) {
      const res = await client.post('/sales-persons/create', { name: form.sales_person_id })
      form.sales_person_id = res.id
      try { const r = await client.get('/sales-persons/list'); salesOptions.value = r.sales_persons || [] } catch(e) {}
    }
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
function handleRestore(id) { fbApi.restoreProduct(id).then(() => { ElMessage.success('已恢复'); loadData() }) }

onMounted(() => { loadOptions(); loadData() })
</script>

<style scoped>
/* ========== 页面容器 ========== */
.page-wrapper {
  background: #f5f6f8;
  padding: 24px;
  min-height: 100%;
  display: flex;
  flex-direction: column;
  gap: 16px;
}

/* ========== 页面头部 ========== */
.page-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.page-title {
  margin: 0;
  font-size: 20px;
  font-weight: 700;
  color: #1f2937;
  letter-spacing: -0.2px;
}

/* ========== 统计卡片行 ========== */
.stats-row {
  margin-left: 0 !important;
  margin-right: 0 !important;
}

.stat-card {
  background: #fff;
  border-radius: 12px;
  padding: 20px;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.06);
  text-align: center;
  cursor: default;
  transition: all 0.2s ease;
  border: 1px solid transparent;
}

.stat-card:hover {
  transform: translateY(-2px);
  box-shadow: 0 6px 20px rgba(0, 0, 0, 0.1);
  border-color: #e5e7eb;
}

.stat-number {
  font-size: 28px;
  font-weight: 700;
  line-height: 1.2;
}

.stat-label {
  font-size: 13px;
  color: #6b7280;
  margin-top: 6px;
  font-weight: 500;
}

/* ========== 筛选栏卡片 ========== */
.filter-card {
  background: #f8f9fa;
  border-radius: 12px;
  padding: 14px 16px;
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
  border: 1px solid #e5e7eb;
}

.total-badge {
  font-size: 13px;
  color: #6b7280;
  font-weight: 500;
  white-space: nowrap;
  padding: 4px 10px;
  background: #fff;
  border-radius: 6px;
  border: 1px solid #e5e7eb;
}

/* ========== 产品列表 ========== */
.product-list {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
}

.product-card {
  margin-bottom: 12px;
  border-radius: 12px;
  border: 1px solid #e5e7eb;
  overflow: hidden;
  transition: all 0.2s ease;
  position: relative;
}

.product-card:hover {
  box-shadow: 0 4px 16px rgba(0, 0, 0, 0.1);
  border-color: #d1d5db;
}

.product-card.is-paused {
  opacity: 0.7;
}

.product-card.is-paused:hover {
  opacity: 0.85;
}

.product-card.is-archived {
  opacity: 0.65;
}

.product-card.is-archived:hover {
  opacity: 0.8;
}

.paused-indicator {
  position: absolute;
  left: 0;
  top: 0;
  bottom: 0;
  width: 4px;
  background: #dc2626;
  border-radius: 12px 0 0 12px;
  z-index: 1;
}

.archived-indicator {
  position: absolute;
  left: 0;
  top: 0;
  bottom: 0;
  width: 4px;
  background: #9ca3af;
  border-radius: 12px 0 0 12px;
  z-index: 1;
}

.product-card-inner {
  padding: 16px;
}

.product-card-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  cursor: pointer;
  gap: 16px;
}

.product-card-info {
  flex: 1;
  min-width: 0;
}

.product-card-tags {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 6px;
  flex-wrap: wrap;
}

.status-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  display: inline-block;
  flex-shrink: 0;
}

.dot-active {
  background: #059669;
}

.dot-paused {
  background: #dc2626;
}

.dot-archived {
  background: #9ca3af;
}

.product-name {
  font-size: 15px;
  color: #1f2937;
}

.tag-sales {
  background: #ecfdf5 !important;
  color: #059669 !important;
  border-color: #a7f3d0 !important;
}

.tag-kpi {
  background: #fffbeb !important;
  color: #d97706 !important;
  border-color: #fde68a !important;
}

.tag-region {
  background: #eff6ff !important;
  color: #2563eb !important;
  border-color: #bfdbfe !important;
}

.tag-ratio {
  background: #f5f3ff !important;
  color: #7c3aed !important;
  border-color: #ddd6fe !important;
}

.product-card-bms {
  margin-bottom: 4px;
  display: flex;
  gap: 4px;
  flex-wrap: wrap;
}

.product-card-runners {
  font-size: 12px;
  color: #9ca3af;
  margin-bottom: 2px;
}

.product-card-lines {
  font-size: 12px;
  color: #9ca3af;
}

.expand-hint {
  display: inline-block;
  margin-left: 8px;
  color: #0891b2;
  font-size: 11px;
  cursor: pointer;
}

.product-card-actions {
  display: flex;
  gap: 4px;
  flex-shrink: 0;
}

/* ========== 展开区 ========== */
.product-card-expand {
  margin-top: 14px;
  padding-top: 14px;
  border-top: 1px solid #f3f4f6;
}

.lines-table {
  border-radius: 8px;
  overflow: hidden;
}

.lines-table :deep(.el-table__row:hover) {
  background: #f0f9ff;
}

.copy-link {
  cursor: pointer;
  color: #0891b2;
  font-size: 13px;
  transition: color 0.15s;
}

.copy-link:hover {
  color: #06b6d4;
  text-decoration: underline;
}

.no-data {
  color: #9ca3af;
  font-size: 12px;
}

.no-lines {
  color: #9ca3af;
  font-size: 13px;
  padding: 8px 0;
  text-align: center;
}

/* ========== 分页 ========== */
.pagination-row {
  display: flex;
  justify-content: center;
  gap: 8px;
  margin-top: 16px;
  padding-bottom: 4px;
}

/* ========== 弹窗 ========== */
.add-line-btn {
  margin-bottom: 10px;
}

.dialog-lines-table {
  border-radius: 8px;
  overflow: hidden;
}

.dialog-lines-table :deep(.el-table__row:hover) {
  background: #f0f9ff;
}

.dialog-lines-table :deep(.el-input__inner) {
  border-radius: 4px;
}
</style>
