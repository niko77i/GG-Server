<template>
  <div class="data-manage-page">
    <div class="page-header">
      <h2>📋 数据管理</h2>
      <p class="page-desc">查看、编辑、删除已保存的做表数据</p>
    </div>

    <!-- 筛选栏 -->
    <div class="filter-bar">
      <div class="filter-left">
        <el-select v-model="filterProduct" placeholder="全部产品" clearable style="width:160px" @change="loadData">
          <el-option
            v-for="p in products" :key="p.product_name"
            :label="p.product_name + (p.sales_person ? ' ' + p.sales_person : '')"
            :value="p.product_name"
          />
        </el-select>
        <el-date-picker
          v-model="dateRange" type="daterange" range-separator="~"
          start-placeholder="开始日期" end-placeholder="结束日期"
          value-format="YYYY-MM-DD" style="width:260px"
          @change="loadData"
        />
        <el-input
          v-model="searchKeyword" placeholder="搜索账户/系列/客户ID..."
          style="width:240px" clearable @input="onSearchDebounced"
        >
          <template #prefix><span>🔍</span></template>
        </el-input>
        <!-- 列选择器 -->
        <el-popover placement="bottom-start" :width="220" trigger="click">
          <template #reference>
            <el-button>📊 列显示</el-button>
          </template>
          <div class="column-selector">
            <el-checkbox
              v-for="col in allColumns" :key="col.prop"
              :model-value="visibleColumns.includes(col.prop)"
              :label="col.prop"
              @change="(checked) => toggleColumn(col.prop, checked)"
            >{{ col.label }}</el-checkbox>
          </div>
        </el-popover>
      </div>
      <div class="filter-right">
        <el-button @click="loadData">🔄 刷新</el-button>
        <el-button type="primary" @click="handleExport" :loading="exporting">📥 导出CSV</el-button>
        <el-button type="success" @click="openAddDialog">➕ 新增数据</el-button>
        <el-button type="danger" :disabled="selectedIds.length === 0" @click="handleBatchDelete">
          🗑 批量删除 ({{ selectedIds.length }})
        </el-button>
      </div>
    </div>

    <!-- 数据表格 -->
    <el-table
      :data="reports" stripe border style="width:100%" v-loading="loading"
      @selection-change="onSelectionChange" @sort-change="onSortChange"
    >
      <el-table-column type="selection" width="45" />
      <el-table-column
        v-for="col in visibleColumnDefs" :key="col.prop"
        :prop="col.prop" :label="col.label" :min-width="col.minWidth"
        :sortable="col.sortable ? 'custom' : false" :align="col.align || 'left'"
      >
        <template v-if="col.format" #default="{ row }">
          <template v-if="col.format === 'cost'">${{ formatNum(row[col.prop]) }}</template>
          <template v-else>{{ formatNum(row[col.prop]) }}</template>
        </template>
      </el-table-column>
      <el-table-column label="操作" width="140" fixed="right">
        <template #default="{ row }">
          <el-button size="small" type="primary" link @click="openEditDialog(row)">编辑</el-button>
          <el-popconfirm title="确定删除这条数据？" @confirm="handleDelete(row.id)">
            <template #reference>
              <el-button size="small" type="danger" link>删除</el-button>
            </template>
          </el-popconfirm>
        </template>
      </el-table-column>
    </el-table>

    <!-- 分页 -->
    <div class="pagination-wrap">
      <el-pagination
        v-model:current-page="page" v-model:page-size="pageSize"
        :page-sizes="[20, 50, 100, 200]" :total="total"
        layout="total, sizes, prev, pager, next"
        @current-change="loadData" @size-change="loadData"
      />
    </div>

    <!-- 编辑/新增弹窗 -->
    <el-dialog
      v-model="dialogVisible" :title="dialogTitle" width="480px"
      :close-on-click-modal="false"
    >
      <el-form :model="form" label-width="90px" label-position="left">
        <el-form-item label="产品名" required>
          <el-input v-model="form.product_name" placeholder="请输入产品名" />
        </el-form-item>
        <el-form-item label="日期" required>
          <el-date-picker v-model="form.report_date" type="date" value-format="YYYY-MM-DD" style="width:100%" />
        </el-form-item>
        <el-form-item label="地区">
          <el-input v-model="form.region" placeholder="如：巴西" />
        </el-form-item>
        <el-form-item label="账户名">
          <el-input v-model="form.account" placeholder="账户名" />
        </el-form-item>
        <el-form-item label="客户ID">
          <el-input v-model="form.customer_id" placeholder="xxx-xxx-xxxx" />
        </el-form-item>
        <el-form-item label="广告系列">
          <el-input v-model="form.campaign" placeholder="广告系列名" />
        </el-form-item>
        <el-form-item label="花费">
          <el-input-number v-model="form.cost" :min="0" :precision="2" style="width:100%" controls-position="right" />
        </el-form-item>
        <el-form-item label="展示">
          <el-input-number v-model="form.impressions" :min="0" :step="100" style="width:100%" controls-position="right" />
        </el-form-item>
        <el-form-item label="点击">
          <el-input-number v-model="form.clicks" :min="0" style="width:100%" controls-position="right" />
        </el-form-item>
        <el-form-item label="安装">
          <el-input-number v-model="form.installs" :min="0" :precision="1" style="width:100%" controls-position="right" />
        </el-form-item>
        <el-form-item label="应用内操作">
          <el-input-number v-model="form.in_app_actions" :min="0" :precision="1" style="width:100%" controls-position="right" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="handleSave">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, reactive, computed, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { reportsApi } from '../api/reports'

// 全部可选列定义
const COL_STORAGE_KEY = 'gg_data_manage_columns'

const allColumns = [
  { prop: 'display_product', label: '产品', minWidth: 100 },
  { prop: 'report_date', label: '日期', minWidth: 100 },
  { prop: 'region', label: '地区', minWidth: 70 },
  { prop: 'account', label: '账户', minWidth: 110 },
  { prop: 'customer_id', label: '客户ID', minWidth: 120 },
  { prop: 'campaign', label: '广告系列', minWidth: 130 },
  { prop: 'cost', label: '花费', minWidth: 90, align: 'right', format: 'cost' },
  { prop: 'impressions', label: '展示', minWidth: 80, align: 'right', format: 'number' },
  { prop: 'clicks', label: '点击', minWidth: 70, align: 'right', format: 'number' },
  { prop: 'installs', label: '安装', minWidth: 70, align: 'right', format: 'number' },
  { prop: 'in_app_actions', label: '应用内操作', minWidth: 100, align: 'right', format: 'number' },
]

// 从 localStorage 恢复列可见性
function loadColumnPrefs() {
  try {
    const saved = localStorage.getItem(COL_STORAGE_KEY)
    if (saved) {
      const arr = JSON.parse(saved)
      if (Array.isArray(arr) && arr.length > 0) return arr
    }
  } catch (e) { /* ignore */ }
  // 默认全部可见
  return allColumns.map(c => c.prop)
}

function saveColumnPrefs() {
  localStorage.setItem(COL_STORAGE_KEY, JSON.stringify(visibleColumns.value))
}

// 可见列 prop 列表
const visibleColumns = ref(loadColumnPrefs())

// 根据 visibleColumns 过滤后的列定义（保持 allColumns 的顺序）
const visibleColumnDefs = computed(() =>
  allColumns.filter(c => visibleColumns.value.includes(c.prop))
)

function toggleColumn(prop, checked) {
  if (checked) {
    // 按 allColumns 顺序插入
    const idx = allColumns.findIndex(c => c.prop === prop)
    const current = [...visibleColumns.value]
    const insertAt = current.findIndex(p => {
      const ci = allColumns.findIndex(c => c.prop === p)
      return ci > idx
    })
    if (insertAt === -1) {
      current.push(prop)
    } else {
      current.splice(insertAt, 0, prop)
    }
    visibleColumns.value = current
  } else {
    visibleColumns.value = visibleColumns.value.filter(p => p !== prop)
  }
  saveColumnPrefs()
}

// 筛选状态
const filterProduct = ref('')
const dateRange = ref(null)
const searchKeyword = ref('')
const products = ref([])

// 表格状态
const reports = ref([])
const loading = ref(false)
const total = ref(0)
const page = ref(1)
const pageSize = ref(50)
const selectedIds = ref([])
const sortProp = ref('')
const sortOrder = ref('')

// 弹窗状态
const dialogVisible = ref(false)
const dialogTitle = ref('')
const editingId = ref(null)
const saving = ref(false)
const exporting = ref(false)

const form = reactive({
  product_name: '', report_date: '', region: '',
  account: '', customer_id: '', campaign: '',
  cost: 0, impressions: 0, clicks: 0,
  installs: 0, in_app_actions: 0,
})

// 加载数据
async function loadData() {
  loading.value = true
  try {
    const params = { page: page.value, size: pageSize.value }
    if (filterProduct.value) params.product_name = filterProduct.value
    if (dateRange.value && dateRange.value.length === 2) {
      params.from_date = dateRange.value[0]
      params.to_date = dateRange.value[1]
    }
    if (searchKeyword.value) params.search = searchKeyword.value

    const data = await reportsApi.list(params)
    reports.value = (data.reports || []).map(r => ({
      ...r,
      display_product: r.resolved_product_name || r.product_name
    }))
    total.value = data.total || 0

    if (sortProp.value) applyClientSort()
  } catch (e) {
    ElMessage.error('加载数据失败：' + (e.response?.data?.error || e.message))
  } finally {
    loading.value = false
  }
}

// 搜索 debounce
let searchTimer = null
function onSearchDebounced() {
  clearTimeout(searchTimer)
  searchTimer = setTimeout(() => { page.value = 1; loadData() }, 300)
}

// 客户端排序
function onSortChange({ prop, order }) {
  sortProp.value = prop
  sortOrder.value = order
  applyClientSort()
}

function applyClientSort() {
  if (!sortProp.value) return
  const key = sortProp.value
  const dir = sortOrder.value === 'ascending' ? 1 : -1
  reports.value.sort((a, b) => {
    const va = a[key] ?? '', vb = b[key] ?? ''
    if (typeof va === 'number') return (va - vb) * dir
    return String(va).localeCompare(String(vb)) * dir
  })
}

// 编辑弹窗
function openEditDialog(row) {
  dialogTitle.value = '编辑数据'
  editingId.value = row.id
  Object.assign(form, {
    product_name: row.display_product || row.product_name,
    report_date: row.report_date,
    region: row.region || '',
    account: row.account || '',
    customer_id: row.customer_id || '',
    campaign: row.campaign || '',
    cost: row.cost || 0,
    impressions: row.impressions || 0,
    clicks: row.clicks || 0,
    installs: row.installs || 0,
    in_app_actions: row.in_app_actions || 0,
  })
  dialogVisible.value = true
}

// 新增弹窗
function openAddDialog() {
  dialogTitle.value = '新增数据'
  editingId.value = null
  Object.assign(form, {
    product_name: '', report_date: '', region: '',
    account: '', customer_id: '', campaign: '',
    cost: 0, impressions: 0, clicks: 0,
    installs: 0, in_app_actions: 0,
  })
  dialogVisible.value = true
}

// 保存（编辑或新增）
async function handleSave() {
  if (!form.product_name.trim()) { ElMessage.warning('请输入产品名'); return }
  if (!form.report_date) { ElMessage.warning('请选择日期'); return }

  saving.value = true
  try {
    if (editingId.value) {
      await reportsApi.update(editingId.value, {
        product_name: form.product_name.trim(),
        report_date: form.report_date,
        region: form.region.trim(),
        account: form.account.trim(),
        customer_id: form.customer_id.trim(),
        campaign: form.campaign.trim(),
        cost: form.cost,
        impressions: form.impressions,
        clicks: form.clicks,
        installs: form.installs,
        in_app_actions: form.in_app_actions,
      })
      ElMessage.success('保存成功')
    } else {
      await reportsApi.save({
        product_name: form.product_name.trim(),
        region: form.region.trim() || '未指定',
        report_date: form.report_date,
        rows: [{
          account: form.account,
          customerId: form.customer_id,
          campaign: form.campaign,
          cost: form.cost,
          impressions: form.impressions,
          clicks: form.clicks,
          installs: form.installs,
          inAppActions: form.in_app_actions,
        }],
      })
      ElMessage.success('新增成功')
    }
    dialogVisible.value = false
    loadData()
  } catch (e) {
    ElMessage.error('保存失败：' + (e.response?.data?.error || e.message))
  } finally {
    saving.value = false
  }
}

// 单条删除
async function handleDelete(id) {
  try {
    await reportsApi.delete(id)
    ElMessage.success('删除成功')
    loadData()
  } catch (e) {
    ElMessage.error('删除失败：' + (e.response?.data?.error || e.message))
  }
}

// 批量删除
async function handleBatchDelete() {
  try {
    await ElMessageBox.confirm(
      `确定删除选中的 ${selectedIds.value.length} 条数据？此操作不可撤销。`,
      '批量删除', { confirmButtonText: '确定', cancelButtonText: '取消', type: 'warning' }
    )
    await reportsApi.batchDelete({ ids: selectedIds.value })
    ElMessage.success(`成功删除 ${selectedIds.value.length} 条`)
    selectedIds.value = []
    loadData()
  } catch (e) {
    if (e !== 'cancel' && e !== 'close') {
      ElMessage.error('批量删除失败：' + (e.response?.data?.error || e.message))
    }
  }
}

// 导出 CSV
async function handleExport() {
  exporting.value = true
  try {
    const params = {}
    if (filterProduct.value) params.product_name = filterProduct.value
    if (dateRange.value && dateRange.value.length === 2) {
      params.from_date = dateRange.value[0]
      params.to_date = dateRange.value[1]
    }
    if (searchKeyword.value) params.search = searchKeyword.value

    const blob = await reportsApi.export(params)
    const url = window.URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.download = 'ad_reports_export.csv'
    link.click()
    window.URL.revokeObjectURL(url)
    ElMessage.success('导出成功')
  } catch (e) {
    ElMessage.error('导出失败：' + (e.response?.data?.error || e.message))
  } finally {
    exporting.value = false
  }
}

function onSelectionChange(selection) {
  selectedIds.value = selection.map(r => r.id)
}

function formatNum(v) {
  if (v == null) return '0'
  return Number(v).toLocaleString('en-US', { maximumFractionDigits: 2 })
}

async function loadProducts() {
  try {
    const res = await reportsApi.products()
    products.value = res.products || []
  } catch { products.value = [] }
}

onMounted(() => {
  loadProducts()
  loadData()
})
</script>

<style scoped>
.data-manage-page { padding: 20px 24px; }
.page-header { margin-bottom: 16px; }
.page-header h2 { margin: 0 0 4px; font-size: 20px; color: #111827; }
.page-desc { margin: 0; font-size: 13px; color: #6b7280; }

.filter-bar { display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 10px; margin-bottom: 16px; }
.filter-left { display: flex; gap: 10px; align-items: center; flex-wrap: wrap; }
.filter-right { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }

.pagination-wrap { display: flex; justify-content: flex-end; margin-top: 16px; }

.column-selector {
  display: flex; flex-direction: column; gap: 6px;
  max-height: 300px; overflow-y: auto;
}
</style>
