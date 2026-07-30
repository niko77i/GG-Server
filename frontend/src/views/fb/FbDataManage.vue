<template>
  <div class="fb-panel">
    <div class="panel-header"><h2>📊 FB数据管理</h2></div>
    <div class="filter-bar">
      <el-select v-model="filterProduct" placeholder="全部产品" clearable style="width:160px" @change="onProductFilter">
        <el-option v-for="p in productOptions" :key="p" :label="p" :value="p" />
      </el-select>
      <el-select v-model="filterLine" placeholder="全部线名" clearable style="width:140px" @change="loadData">
        <el-option v-for="l in lineOptions" :key="l" :label="l" :value="l" />
      </el-select>
      <el-date-picker v-model="dateRange" type="daterange" range-separator="~" start-placeholder="开始" end-placeholder="结束"
        value-format="YYYY-MM-DD" style="width:260px" @change="loadData" />
      <el-button @click="loadData">🔄 刷新</el-button>
      <el-button type="danger" :disabled="selectedIds.length===0" @click="handleBatchDelete">🗑 批量删除({{ selectedIds.length }})</el-button>
      <el-checkbox v-model="showDetailCols" style="margin-left:8px">显示详情列</el-checkbox>
      <el-button type="primary" @click="loadStats" style="margin-left:auto">📈 查看统计</el-button>
      <el-button type="success" @click="handleExport">📥 导出CSV</el-button>
      <el-button type="warning" @click="retrySheets">🔄 重试写表</el-button>
    </div>

    <el-table :data="items" stripe border v-loading="loading" @selection-change="onSelect">
      <el-table-column type="selection" width="45" />
      <el-table-column prop="product_name" label="产品名" min-width="100" />
      <el-table-column prop="line_name" label="线名" min-width="100" />
      <el-table-column prop="report_date" label="日期" width="110" />
      <el-table-column prop="account_name" label="账户名称" min-width="120" />
      <el-table-column prop="account_id" label="账户ID" width="160" />
      <el-table-column label="消耗" width="100"><template #default="{row}">${{ row.cost?.toFixed(2) }}</template></el-table-column>
      <el-table-column v-if="showDetailCols" prop="impressions" label="展示" width="90" />
      <el-table-column v-if="showDetailCols" prop="clicks" label="点击" width="80" />
      <el-table-column v-if="showDetailCols" prop="registrations" label="注册" width="80" />
      <el-table-column v-if="showDetailCols" prop="purchases" label="购物" width="80" />
      <el-table-column v-if="showDetailCols" prop="cost_per_purchase" label="单词购物费用" width="120">
        <template #default="{row}">${{ row.cost_per_purchase?.toFixed(2) }}</template>
      </el-table-column>
      <el-table-column label="操作" width="140" fixed="right">
        <template #default="{row}">
          <el-button size="small" type="primary" link @click="openEdit(row)">编辑</el-button>
          <el-popconfirm title="确定删除？" @confirm="handleDelete(row.id)">
            <template #reference><el-button size="small" type="danger" link>删除</el-button></template>
          </el-popconfirm>
        </template>
      </el-table-column>
    </el-table>
    <el-pagination v-if="total>size" v-model:current-page="page" :page-size="size" :total="total" layout="prev,pager,next" @current-change="loadData" style="margin-top:16px;justify-content:flex-end" />

    <!-- 编辑弹窗 -->
    <el-dialog v-model="editVisible" title="编辑数据" width="480px">
      <el-form :model="editForm" label-width="100px">
        <el-form-item label="账户名称"><el-input v-model="editForm.account_name" /></el-form-item>
        <el-form-item label="账户ID"><el-input v-model="editForm.account_id" /></el-form-item>
        <el-form-item label="日期"><el-input v-model="editForm.report_date" /></el-form-item>
        <el-form-item label="消耗"><el-input-number v-model="editForm.cost" :precision="2" :min="0" style="width:100%" /></el-form-item>
        <el-form-item label="展示"><el-input-number v-model="editForm.impressions" :min="0" style="width:100%" /></el-form-item>
        <el-form-item label="点击"><el-input-number v-model="editForm.clicks" :min="0" style="width:100%" /></el-form-item>
        <el-form-item label="注册"><el-input-number v-model="editForm.registrations" :min="0" style="width:100%" /></el-form-item>
        <el-form-item label="购物"><el-input-number v-model="editForm.purchases" :min="0" style="width:100%" /></el-form-item>
        <el-form-item label="单词购物费用"><el-input-number v-model="editForm.cost_per_purchase" :precision="2" :min="0" style="width:100%" /></el-form-item>
      </el-form>
      <template #footer><el-button @click="editVisible=false">取消</el-button><el-button type="primary" :loading="savingEdit" @click="handleSaveEdit">保存</el-button></template>
    </el-dialog>

    <!-- 统计弹窗 -->
    <el-dialog v-model="statsVisible" title="数据统计" width="700px">
      <el-table :data="statsData" stripe border>
        <el-table-column prop="product_name" label="产品名" />
        <el-table-column prop="line_name" label="线名" />
        <el-table-column prop="report_date" label="日期" width="110" />
        <el-table-column prop="total_cost" label="总消耗" width="100"><template #default="{row}">${{ row.total_cost?.toFixed(2) }}</template></el-table-column>
        <el-table-column prop="total_impressions" label="总展示" width="90" />
        <el-table-column prop="total_clicks" label="总点击" width="80" />
        <el-table-column prop="account_count" label="账户数" width="80" />
      </el-table>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { fbApi } from '../../api/fb'
import { ElMessage } from 'element-plus'

const items = ref([]); const loading = ref(false); const page = ref(1); const size = ref(50); const total = ref(0)
const filterProduct = ref(''); const filterLine = ref(''); const dateRange = ref(null)
const selectedIds = ref([]); const productOptions = ref([]); const lineOptions = ref([])
const showDetailCols = ref(false)
const statsVisible = ref(false); const statsData = ref([])

// 编辑相关
const editVisible = ref(false); const savingEdit = ref(false)
const editForm = ref({})

function onSelect(v) { selectedIds.value = v.map(r=>r.id) }

async function loadFilterOptions() {
  try {
    const res = await fbApi.runnerProducts()
    const products = res.data || []
    productOptions.value = products.map(p => p.product_name).filter(Boolean)
    lineOptions.value = [...new Set(products.flatMap(p => (p.lines || []).map(l => l.line_name).filter(Boolean)))]
  } catch(e) { /* 静默失败 */ }
}

function onProductFilter() {
  filterLine.value = ''
  loadData()
}

async function loadData() {
  loading.value = true
  try {
    const p = { page: page.value, size: size.value }
    if (filterProduct.value) p.product_name = filterProduct.value
    if (filterLine.value) p.line_name = filterLine.value
    if (dateRange.value) { p.date_from = dateRange.value[0]; p.date_to = dateRange.value[1] }
    const res = await fbApi.listReports(p)
    items.value = res.items; total.value = res.total
    // 自动检测是否有详情数据
    if (items.value.some(r => r.impressions > 0 || r.clicks > 0)) showDetailCols.value = true
  } finally { loading.value = false }
}
async function loadStats() {
  const p = {}
  if (filterProduct.value) p.product_name = filterProduct.value
  if (filterLine.value) p.line_name = filterLine.value
  if (dateRange.value) { p.date_from = dateRange.value[0]; p.date_to = dateRange.value[1] }
  const res = await fbApi.reportStats(p)
  statsData.value = res.data || []
  statsVisible.value = true
}

function openEdit(row) {
  editForm.value = { ...row }
  editVisible.value = true
}
async function handleSaveEdit() {
  savingEdit.value = true
  try {
    await fbApi.updateReport(editForm.value.id, editForm.value)
    ElMessage.success('已更新')
    editVisible.value = false
    loadData()
  } catch(e) { ElMessage.error(e.response?.data?.error || '保存失败') }
  finally { savingEdit.value = false }
}

async function handleDelete(id) { await fbApi.deleteReport(id); ElMessage.success('已删除'); loadData() }
async function handleBatchDelete() {
  await fbApi.batchDeleteReports(selectedIds.value)
  ElMessage.success(`已删除${selectedIds.value.length}条`); selectedIds.value = []; loadData()
}

async function retrySheets() {
  try {
    const res = await fbApi.retrySheetsSync()
    ElMessage.success(`重试完成：${res.retried || 0} 条已同步`)
  } catch(e) { ElMessage.error(e.response?.data?.error || '重试失败') }
}

async function handleExport() {
  const p = {}
  if (filterProduct.value) p.product_name = filterProduct.value
  if (filterLine.value) p.line_name = filterLine.value
  if (dateRange.value) { p.date_from = dateRange.value[0]; p.date_to = dateRange.value[1] }
  try {
    const qs = new URLSearchParams(p).toString()
    const token = localStorage.getItem('access_token')
    const resp = await fetch(`/api/fb/reports/export?${qs}`, {
      headers: { 'Authorization': `Bearer ${token}` }
    })
    if (!resp.ok) throw new Error('导出失败')
    const blob = await resp.blob()
    const url = window.URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url; a.download = 'fb_reports.csv'; a.click()
    window.URL.revokeObjectURL(url)
    ElMessage.success('导出完成')
  } catch(e) { ElMessage.error('导出失败') }
}

onMounted(() => { loadFilterOptions(); loadData() })
</script>
<style scoped>
.fb-panel{padding:20px}.panel-header{margin-bottom:16px}.panel-header h2{margin:0;font-size:18px}.filter-bar{display:flex;gap:12px;margin-bottom:16px;align-items:center;flex-wrap:wrap}
</style>
