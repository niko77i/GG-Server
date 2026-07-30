<template>
  <div class="fb-panel">
    <div class="panel-header"><h2>📊 FB数据管理</h2></div>
    <div class="filter-bar">
      <el-select v-model="filterProduct" placeholder="全部产品" clearable style="width:160px" @change="loadData">
        <el-option v-for="p in productOptions" :key="p" :label="p" :value="p" />
      </el-select>
      <el-select v-model="filterLine" placeholder="全部线名" clearable style="width:140px" @change="loadData">
        <el-option v-for="l in lineOptions" :key="l" :label="l" :value="l" />
      </el-select>
      <el-date-picker v-model="dateRange" type="daterange" range-separator="~" start-placeholder="开始" end-placeholder="结束"
        value-format="YYYY-MM-DD" style="width:260px" @change="loadData" />
      <el-button @click="loadData">🔄 刷新</el-button>
      <el-button type="danger" :disabled="selectedIds.length===0" @click="handleBatchDelete">🗑 批量删除({{ selectedIds.length }})</el-button>
      <el-button type="primary" @click="loadStats" style="margin-left:auto">📈 查看统计</el-button>
    </div>

    <el-table :data="items" stripe border v-loading="loading" @selection-change="onSelect">
      <el-table-column type="selection" width="45" />
      <el-table-column prop="product_name" label="产品名" min-width="100" />
      <el-table-column prop="line_name" label="线名" min-width="100" />
      <el-table-column prop="report_date" label="日期" width="110" />
      <el-table-column prop="account_name" label="账户名称" min-width="120" />
      <el-table-column prop="account_id" label="账户ID" width="160" />
      <el-table-column label="消耗" width="100"><template #default="{row}">${{ row.cost?.toFixed(2) }}</template></el-table-column>
      <el-table-column v-if="hasDetailCols" prop="impressions" label="展示" width="90" />
      <el-table-column v-if="hasDetailCols" prop="clicks" label="点击" width="80" />
      <el-table-column v-if="hasDetailCols" prop="registrations" label="注册" width="80" />
      <el-table-column v-if="hasDetailCols" prop="purchases" label="购物" width="80" />
      <el-table-column label="操作" width="100" fixed="right">
        <template #default="{row}"><el-popconfirm title="确定删除？" @confirm="handleDelete(row.id)"><template #reference><el-button size="small" type="danger" link>删除</el-button></template></el-popconfirm></template>
      </el-table-column>
    </el-table>
    <el-pagination v-if="total>size" v-model:current-page="page" :page-size="size" :total="total" layout="prev,pager,next" @current-change="loadData" style="margin-top:16px;justify-content:flex-end" />

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
import { ref, computed, onMounted } from 'vue'
import { fbApi } from '../../api/fb'
import { ElMessage } from 'element-plus'

const items = ref([]); const loading = ref(false); const page = ref(1); const size = ref(50); const total = ref(0)
const filterProduct = ref(''); const filterLine = ref(''); const dateRange = ref(null)
const selectedIds = ref([]); const productOptions = ref([]); const lineOptions = ref([])
const statsVisible = ref(false); const statsData = ref([])

const hasDetailCols = computed(() => items.value.some(r => r.impressions > 0 || r.clicks > 0))

function onSelect(v) { selectedIds.value = v.map(r=>r.id) }

async function loadData() {
  loading.value = true
  try {
    const p = { page: page.value, size: size.value }
    if (filterProduct.value) p.product_name = filterProduct.value
    if (filterLine.value) p.line_name = filterLine.value
    if (dateRange.value) { p.date_from = dateRange.value[0]; p.date_to = dateRange.value[1] }
    const res = await fbApi.listReports(p)
    items.value = res.data.items; total.value = res.data.total
    // 更新筛选选项
    if (!productOptions.value.length) {
      productOptions.value = [...new Set(items.value.map(r=>r.product_name))]
      lineOptions.value = [...new Set(items.value.map(r=>r.line_name).filter(Boolean))]
    }
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
async function handleDelete(id) { await fbApi.deleteReport(id); ElMessage.success('已删除'); loadData() }
async function handleBatchDelete() {
  await fbApi.batchDeleteReports(selectedIds.value)
  ElMessage.success(`已删除${selectedIds.value.length}条`); loadData()
}
onMounted(loadData)
</script>
<style scoped>
.fb-panel{padding:20px}.panel-header{margin-bottom:16px}.panel-header h2{margin:0;font-size:18px}.filter-bar{display:flex;gap:12px;margin-bottom:16px;align-items:center;flex-wrap:wrap}
</style>
