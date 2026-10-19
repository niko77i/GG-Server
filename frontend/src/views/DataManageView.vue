<template>
  <div class="data-manage-page">
    <div class="page-header">
      <h2>📋 数据管理<!-- 角色标识：只出现于本需求新开放的两个角色，普通 user 界面不受影响 -->
        <span v-if="auth.user?.role === 'admin'" class="role-chip role-chip--readonly">只读</span>
        <span v-else-if="auth.canEditReportCost" class="role-chip role-chip--cost">可改「消耗」</span>
      </h2>
      <p class="page-desc">查看、编辑、删除已保存的做表数据</p>
    </div>

    <!-- 筛选栏 -->
    <div class="filter-bar">
      <div class="filter-left">
        <!-- 「保存人」筛选：仅跨用户角色（户管/管理员/developer）可见。未选中 = 不传 user_id（看全部） -->
        <el-select
          v-if="auth.canFilterReportOwner"
          v-model="filterOwner" placeholder="全部用户" clearable filterable
          style="width:150px" @change="onOwnerFilter"
        >
          <el-option v-for="u in ownerUsers" :key="u.id" :label="u.display_name || u.username" :value="u.id" />
        </el-select>
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
              :disabled="childDisabled(col.prop, visibleColumns, AGG_CFG)"
              @change="(checked) => onColumnChecked(col.prop, checked)"
            >{{ col.label }}</el-checkbox>
          </div>
        </el-popover>
        <!-- 聚合开关：只在「有维度列被隐藏」时出现；聚合态只读，点击后切回明细可编辑 -->
        <el-button v-if="aggregationAvailable" @click="toggleAggregation">
          {{ aggregating ? '放弃聚合' : '恢复聚合' }}
        </el-button>
      </div>
      <div class="filter-right">
        <el-button @click="loadData">🔄 刷新</el-button>
        <el-button type="primary" @click="handleExport" :loading="exporting">📥 导出CSV</el-button>
        <!-- 新增 / 批量删除：只对「能增删自己行的角色」渲染（管理员只读、户管仅可改消耗）
             ⚠️ 谓词是 canWriteReportRows（developer + 普通 user + viewer），**不是**
             canManageReports（= developer）—— 后者会把普通 user 的按钮一并藏掉，破坏回归判据 -->
        <el-button v-if="auth.canWriteReportRows && !aggregating" type="success" @click="openAddDialog">➕ 新增数据</el-button>
        <el-button v-if="auth.canWriteReportRows && !aggregating" type="danger" :disabled="selectedIds.length === 0" @click="handleBatchDelete">
          🗑 批量删除 ({{ selectedIds.length }})
        </el-button>
      </div>
    </div>

    <!-- 数据表格 -->
    <el-table
      :data="reports" stripe border style="width:100%" v-loading="loading"
      @selection-change="onSelectionChange" @sort-change="onSortChange"
    >
      <!-- 勾选框：只读角色（管理员/户管）没有批量删除动作，留着勾选框是误导 -->
      <el-table-column v-if="auth.canWriteReportRows && !aggregating" type="selection" width="45" />
      <el-table-column
        v-for="col in visibleColumnDefs" :key="col.prop"
        :prop="col.prop" :label="col.label" :min-width="col.minWidth"
        :sortable="col.sortable ? 'custom' : false" :align="col.align || 'left'"
      >
        <template v-if="col.format" #default="{ row }">
          <!-- 「花费」列：户管可内联改（仅此角色）。其余角色走下面两个分支，与改动前逐字一致 -->
          <!-- 聚合行对应多条库记录，无法定位到单条 ⇒ 聚合态不可内联编辑 -->
          <template v-if="col.format === 'cost' && auth.canEditReportCost && !aggregating">
            <div class="inline-edit-cell" v-if="editingCostId === row.id">
              <el-input v-model="editCostValue" size="small" class="inline-name-input"
                :ref="el => { if (el) costInputRef = el }"
                @blur="saveCost(row)" @keyup.enter="saveCost(row)" @keyup.escape="cancelCostEdit" />
            </div>
            <div class="inline-edit-cell" v-else>
              <span class="inline-cell-text">${{ formatNum(row[col.prop]) }}</span>
              <el-button link size="small" class="inline-edit-btn" @click.stop="startEditCost(row)">✏️</el-button>
            </div>
          </template>
          <template v-else-if="col.format === 'cost'">${{ formatNum(row[col.prop]) }}</template>
          <template v-else>{{ formatNum(row[col.prop]) }}</template>
        </template>
      </el-table-column>
      <!-- 每行编辑/删除：只有能改自己整行的角色才渲染（管理员只读、户管仅可改消耗 →
           他们的改整行走 API 会被后端 403，故整列不渲染） -->
      <el-table-column v-if="auth.canWriteReportRows && !aggregating" label="操作" width="140" fixed="right">
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
import { ref, reactive, computed, onMounted, nextTick } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { reportsApi } from '../api/reports'
import api from '../api/client'
import { useAuthStore } from '../stores/auth'
import { isAggregating, visibleDimensions, childDisabled, applyLinkage, normalizePrefs }
  from '../utils/reportAggregation.mjs'

const auth = useAuthStore()
// 身份由 App.vue 根组件的 onMounted 水合，而子组件 setup 恒早于父组件 onMounted：
// 不补这一次，首帧 auth.user 还是 null ⇒ 按角色的 v-if 会算错（多渲染一瞬按钮）。
// 同类教训与写法见 components/OwnerFilterSelect.vue:22-27。
if (!auth.user) auth.initFromStorage()

// 全部可选列定义
const COL_STORAGE_KEY = 'gg_data_manage_columns'

const allColumns = [
  { prop: 'report_date', label: '日期', minWidth: 100, role: 'dimension' },
  { prop: 'display_product', label: '产品', minWidth: 100, role: 'dimension' },
  { prop: 'region', label: '地区', minWidth: 70, role: 'dimension' },
  { prop: 'account', label: '账户', minWidth: 110, role: 'dimension' },
  { prop: 'customer_id', label: '客户ID', minWidth: 120, role: 'dimension' },
  { prop: 'campaign', label: '广告系列', minWidth: 130, role: 'dimension' },
  { prop: 'cost', label: '花费', minWidth: 90, align: 'right', format: 'cost', role: 'metric' },
  { prop: 'impressions', label: '展示', minWidth: 80, align: 'right', format: 'number', role: 'metric' },
  { prop: 'clicks', label: '点击', minWidth: 70, align: 'right', format: 'number', role: 'metric' },
  { prop: 'installs', label: '安装', minWidth: 70, align: 'right', format: 'number', role: 'metric' },
  { prop: 'in_app_actions', label: '应用内操作', minWidth: 100, align: 'right', format: 'number', role: 'metric' },
]
// 聚合与联动配置（纯逻辑在 utils/reportAggregation.mjs，有单测）
const AGG_CFG = {
  columns: allColumns.map(c => ({ prop: c.prop, role: c.role })),
  defaultVisible: allColumns.map(c => c.prop),
  links: [{ parent: 'display_product', child: 'campaign' }],
}

// 从 localStorage 恢复列可见性（含父子列归一化；空/坏数据回落默认全部可见）
function loadColumnPrefs() {
  try {
    const saved = localStorage.getItem(COL_STORAGE_KEY)
    if (saved) return normalizePrefs(JSON.parse(saved), AGG_CFG)
  } catch (e) { /* ignore */ }
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

// ---------- 自动聚合（2026-10-19 设计）----------
// 可见维度列少于维度总数 ⇒ 自动按可见维度分组（服务端 GROUP BY）；聚合态只读。
const aggregationOff = ref(false)
const aggregationAvailable = computed(() =>
  isAggregating(visibleColumns.value, AGG_CFG, false))
const aggregating = computed(() =>
  isAggregating(visibleColumns.value, AGG_CFG, aggregationOff.value))
function toggleAggregation() {
  aggregationOff.value = !aggregationOff.value
  page.value = 1
  loadData()
}
function onColumnChecked(prop, checked) {
  const wasAggregating = aggregating.value
  const isDim = allColumns.find(c => c.prop === prop)?.role === 'dimension'
  visibleColumns.value = applyLinkage(visibleColumns.value, prop, checked, AGG_CFG)
  aggregationOff.value = false            // 列变了 ⇒ 重新按可见列自动判定
  saveColumnPrefs()
  // 维度变化会改变分组键；聚合状态翻转也要重取。只切数值列不影响服务端结果。
  if (isDim || aggregating.value !== wasAggregating) {
    page.value = 1
    loadData()
  }
}

// 筛选状态
const filterProduct = ref('')
const dateRange = ref(null)
const searchKeyword = ref('')
const products = ref([])

// 「保存人」筛选（仅跨用户角色渲染；未选中 = 不传该参数 = 看全部）
const filterOwner = ref('')
const ownerUsers = ref([])
async function loadOwnerUsers() {
  try {
    // 只列**有报表数据**的人。不能复用 /api/platform/users：那个口径是
    // 「该平台有未删除账户的人」（账户面板的筛选语义），会混入无报表的人、
    // 漏掉有报表但名下没户的人。
    const res = await api.get('/ad-reports/owners')
    ownerUsers.value = res.users || []
  } catch { /* 下拉加载失败不阻塞主流程（同 OwnerFilterSelect.vue:56） */ }
}
function onOwnerFilter() { page.value = 1; loadData() }

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
    if (filterOwner.value) params.user_id = filterOwner.value   // 保存人筛选（仅跨用户角色会有值）
    // 聚合态：服务端按可见维度 GROUP BY；全部维度隐藏时只出总计（grouped=1，不带 group_by）
    if (aggregating.value) {
      params.grouped = 1
      const dims = visibleDimensions(visibleColumns.value, AGG_CFG)
      if (dims.length) params.group_by = dims.join(',')
    }

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
    if (filterOwner.value) params.user_id = filterOwner.value   // 导出的范围 = 屏幕上看到的范围

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

// ===== 「花费/消耗」内联编辑（仅户管；谓词 canEditReportCost 与后端 report_editable_fields 同口径）=====
const editingCostId = ref(null)
const editCostValue = ref('')
let costInputRef = null
let costPending = false

function startEditCost(row) {
  editingCostId.value = row.id
  editCostValue.value = row.cost == null ? '' : String(row.cost)
  nextTick(() => {
    costInputRef?.focus?.()
    costInputRef?.select?.()
  })
}
function cancelCostEdit() {
  editingCostId.value = null
  editCostValue.value = ''
  costInputRef = null
}
async function saveCost(row) {
  // blur 与 Enter 都会触发本函数（见 AdsAccountPanel.vue 的同类范式）：先落态的那次把
  // editingCostId 清掉 / 置 pending，后到的那次两个守卫之一即拦下，不会重复提交。
  if (costPending || editingCostId.value !== row.id) return
  const raw = String(editCostValue.value).trim()
  const v = Number(raw)
  if (raw === '' || !Number.isFinite(v) || v < 0) {
    if (raw !== '') ElMessage.warning('消耗需为不小于 0 的数字')
    cancelCostEdit(); return
  }
  if (row.cost != null && v === Number(row.cost)) { cancelCostEdit(); return }  // 没变，不发请求
  costPending = true
  try {
    // **只发 cost 一个字段**：后端对白名单外的字段回 403（设计文档 §4.2 / §6），整行回传必被拒
    await reportsApi.update(row.id, { cost: v })
    row.cost = v
    if (sortProp.value) applyClientSort()
    ElMessage.success('消耗已更新')
  } catch (e) {
    ElMessage.error('更新失败：' + (e.response?.data?.error || e.message))
  } finally {
    costPending = false
    cancelCostEdit()
  }
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
  if (auth.canFilterReportOwner) loadOwnerUsers()
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

/* 角色标识（只读 / 仅可改消耗）。只出现在本需求新开放的两个角色上，普通 user 界面无变化。
   配色沿用本仓既有语汇：薄荷青 #0891b2 是本应用唯一的能力色（按钮/激活态），
   中性灰 #6b7280 与下方 .page-desc 同值 —— 不引入新色。 */
.role-chip {
  display: inline-block; margin-left: 8px; padding: 1px 8px;
  border-radius: 10px; font-size: 12px; font-weight: 500; vertical-align: middle;
}
.role-chip--readonly { background: #f3f4f6; color: #6b7280; border: 1px solid #e5e7eb; }
.role-chip--cost { background: rgba(8,145,178,0.10); color: #0891b2; border: 1px solid rgba(8,145,178,0.25); }

/* 内联编辑：逐字沿用 views/AdsAccountPanel.vue:702-744 的范式（同一套交互心智） */
.inline-edit-cell { display: flex; align-items: center; gap: 4px; min-width: 0; }
.inline-cell-text { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; min-width: 0; flex: 1 1 auto; }
.inline-edit-btn { opacity: 0; transition: opacity 0.15s; font-size: 13px; flex-shrink: 0; }
.inline-edit-cell:hover .inline-edit-btn { opacity: 1; }
.inline-name-input { width: 100%; }
</style>
