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

    <!-- 写表失败汇总（四期）。复用 T6 卡片已 /frontend-design 定稿的视觉语法：
         3px 琥珀左脊柱 + warning 色调（零回滚 ⇒ 只可能是 retry_failed，
         「表中未写入」不等于数据坏了）。有失败才渲染，无失败时连占位都没有。 -->
    <div v-if="fbSwFailures.length"
         style="background:var(--el-color-warning-light-9);border-left:3px solid var(--el-color-warning);border-radius:8px;padding:10px 12px;margin-bottom:12px;">
      <div style="font-weight:600;font-size:13px;color:#92400e;margin-bottom:6px;">
        ⚠️ {{ fbSwFailures.length }} 项没写进表
      </div>
      <div v-for="(f, i) in fbSwFailures" :key="f.business_key"
           :style="{ display:'flex', alignItems:'baseline', gap:'8px', padding:'5px 0',
                     borderTop: i ? '1px solid var(--el-color-warning-light-7)' : 'none' }">
        <el-tooltip placement="top" :content="sheetWriteHint(f)">
          <span style="font-family:monospace;font-size:12px;color:#374151;flex:none;max-width:45%;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">{{ f.business_key }}</span>
        </el-tooltip>
        <span style="font-size:12px;color:#6b7280;flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">{{ f.error_msg || '未知原因' }}</span>
        <el-button link size="small" :type="sheetWriteTone(f.status)"
                   @click="retryOne(f)">重试</el-button>
      </div>
      <div style="margin-top:8px;">
        <el-button size="small" @click="retryAll">重试全部失败的</el-button>
      </div>
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
import { ref, onMounted, onUnmounted } from 'vue'
import { fbApi } from '../../api/fb'
import { ElMessage } from 'element-plus'
import { sheetWriteApi } from '../../api/sheetWrite'
import { sheetWriteTone, sheetWriteHint } from '@/utils/sheetWriteUi'

const items = ref([]); const loading = ref(false); const page = ref(1); const size = ref(50); const total = ref(0)
const filterProduct = ref(''); const filterLine = ref(''); const dateRange = ref(null)
const selectedIds = ref([]); const productOptions = ref([]); const lineOptions = ref([])
const showDetailCols = ref(false)
const statsVisible = ref(false); const statsData = ref([])

// 编辑相关
const editVisible = ref(false); const savingEdit = ref(false)
const editForm = ref({})

function onSelect(v) { selectedIds.value = v.map(r=>r.id) }

// ---------- 写表失败汇总（四期） ----------
const FB_TARGET = 'fb_report'
const fbSwFailures = ref([])

// 重试提交后跟一段**有界轮询**：重试后该行转 `pending`，而 `/api/sheet-write/status`
// 不带 businessKey 时**只回需要提示的终态** ⇒ 汇总区立刻少一项（看着像成功了）；若重试
// 再次失败，那一项要等用户手动刷新才回来 —— 用户会以为已经好了。故提交后按固定节奏
// 刷新汇总区，让「重试又失败」的项自己回来。
// 3s × 15 ≈ 45s，**必须 > 后端 30s 重试窗口**（不能调小）：后端首次失败先落中间态
// failed → 睡 30s → 重试 → 终态 retry_failed 最早 ~30s 才落库；窗口短于 30s 会漏掉
// 走过后端重试的终态。
const SW_POLL_MS = 3000
const SW_POLL_MAX = 15
let swPollTimer = null
let swPollLeft = 0
let swPollGen = 0        // 每轮重试 +1：作废上一轮在途的 tick，防两条链并行

onUnmounted(() => {
  // 卸载即停：作废在途 tick（它会在 await 回来后自行退出），并清掉在途定时器。
  swPollGen++
  swPollLeft = 0
  if (swPollTimer) { clearTimeout(swPollTimer); swPollTimer = null }
})

/** 汇总区数据源：只取本 target 的终态；拉不到不该打扰用户，保持上一次结果。 */
async function loadFbSwFailures() {
  try {
    const res = await sheetWriteApi.status({ platform: 'fb', target: FB_TARGET })
    // 显式跳过中间态 **且** 不展示 synced：端点本就只回需要提示的终态，这里再兜一层，
    // 防「中间态 / 成功态误入汇总区」被当成已落定的失败（本功能反复踩过的坑）。
    fbSwFailures.value = (res.items || []).filter(
      f => f.status !== 'pending' && f.status !== 'failed' && f.status !== 'synced')
  } catch { /* 汇总拉不到不该打扰用户，保持上一次结果 */ }
}

/** 重试提交后按固定节奏刷新汇总区，有界（15 次后自动停）。
 *  全程不弹任何提示 —— 中间态与终态都由汇总区自身呈现，避免打断 / 重复提示。 */
function scheduleSwRefresh() {
  const gen = ++swPollGen                        // 开新一轮：作废上一轮（连点重试不叠链）
  if (swPollTimer) { clearTimeout(swPollTimer); swPollTimer = null }
  swPollLeft = SW_POLL_MAX
  const tick = async () => {
    swPollTimer = null
    if (gen !== swPollGen || swPollLeft <= 0) return   // 已被新一轮取代 / 到顶 / 已卸载即停
    swPollLeft--
    await loadFbSwFailures()
    if (gen !== swPollGen || swPollLeft <= 0) return
    swPollTimer = setTimeout(tick, SW_POLL_MS)
  }
  swPollTimer = setTimeout(tick, SW_POLL_MS)
}

/** 逐条重试：提交 → 立即刷新 → 起有界轮询跟结果。 */
async function retryOne(f) {
  try {
    await sheetWriteApi.retry({ platform: 'fb', target: FB_TARGET,
                                businessKey: f.business_key })
    ElMessage.success('已重新提交，请稍后查看结果')
    await loadFbSwFailures()
    scheduleSwRefresh()
  } catch (e) { ElMessage.error(e.response?.data?.error || '重试失败') }
}

/** 重试全部失败的：只回传 business_key 列表，**不拆 `产品|线|日期`**（名字含 `|` 会拆错）；
 *  三元组由端点从各行的 payload_json 取（Task 2 已支持 `{"business_keys": [...]}`）。 */
async function retryAll() {
  try {
    const res = await fbApi.retrySheetsSync({
      business_keys: fbSwFailures.value.map(f => f.business_key),
    })
    ElMessage.success(`已重新提交 ${res.accepted || 0} 项，请稍后查看结果`)
    await loadFbSwFailures()
    scheduleSwRefresh()
  } catch (e) { ElMessage.error(e.response?.data?.error || '重试失败') }
}

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
  // 用后端返回的真实删除数 `deleted`（cursor.rowcount），不按选中条数：
  // 非跨用户角色删「自己的 1 条 + 别人的 1 条」时后端只删 1 条，按选中数会谎报 2。
  const res = await fbApi.batchDeleteReports(selectedIds.value)
  ElMessage.success(`已删除${res.deleted}条`); selectedIds.value = []; loadData()
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

onMounted(() => { loadFilterOptions(); loadData(); loadFbSwFailures() })
</script>
<style scoped>
.fb-panel{padding:20px}.panel-header{margin-bottom:16px}.panel-header h2{margin:0;font-size:18px}.filter-bar{display:flex;gap:12px;margin-bottom:16px;align-items:center;flex-wrap:wrap}
</style>
