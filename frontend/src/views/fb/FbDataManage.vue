<template>
  <div class="fb-panel">
    <div class="panel-header"><h2>📊 FB数据管理<!-- 角色标识：只出现于本需求新开放的两个角色，普通 user 界面不受影响 -->
      <span v-if="auth.user?.role === 'admin'" class="role-chip role-chip--readonly">只读</span>
      <span v-else-if="auth.canEditReportCost" class="role-chip role-chip--cost">可改「消耗」</span>
    </h2></div>
    <div class="filter-bar">
      <!-- 「保存人」筛选：仅跨用户角色（户管/管理员/developer）可见。未选中 = 不传 user_id（看全部） -->
      <el-select v-if="auth.canFilterReportOwner" v-model="filterOwner" placeholder="全部用户"
        clearable filterable style="width:150px" @change="onOwnerFilter">
        <el-option v-for="u in ownerUsers" :key="u.id" :label="u.display_name || u.username" :value="u.id" />
      </el-select>
      <el-select v-model="filterProduct" placeholder="全部产品" clearable style="width:160px" @change="onProductFilter">
        <el-option v-for="p in productOptions" :key="p" :label="p" :value="p" />
      </el-select>
      <el-select v-model="filterLine" placeholder="全部线名" clearable style="width:140px" @change="loadData">
        <el-option v-for="l in lineOptions" :key="l" :label="l" :value="l" />
      </el-select>
      <el-date-picker v-model="dateRange" type="daterange" range-separator="~" start-placeholder="开始" end-placeholder="结束"
        value-format="YYYY-MM-DD" style="width:260px" @change="loadData" />
      <el-button @click="loadData">🔄 刷新</el-button>
      <!-- 批量删除：只对「能删自己行的角色」渲染（管理员只读、户管仅可改消耗）。
           谓词是 canWriteReportRows（developer + 普通 user + viewer），**不是** canManageReports
           （= developer）—— 后者会把普通 user 的按钮藏掉，破坏回归判据 -->
      <el-button v-if="auth.canWriteReportRows" type="danger" :disabled="selectedIds.length===0" @click="handleBatchDelete">🗑 批量删除({{ selectedIds.length }})</el-button>
      <!-- 列选择器：与 GG 数据管理页同构（逐列勾选，localStorage 持久化） -->
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
      <el-button type="primary" @click="loadStats" style="margin-left:auto">📈 查看统计</el-button>
      <el-button type="success" @click="handleExport">📥 导出CSV</el-button>
      <!-- 原「🔄 重试写表」按钮已移除：其入口并入下方失败汇总区的「重试全部失败的」。
           写表改走统一治理后 `/fb/reports/retry-sync` 不再接受空 body，旧的盲重试按钮
           只会拿到 400（缺少 groups 或 business_keys），故由汇总区内的定向重试取代。 -->
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
        <el-button v-if="auth.user?.role !== 'admin'" link size="small" :type="sheetWriteTone(f.status)"
                   @click="retryOne(f)">重试</el-button>
      </div>
      <!-- 重试写表：管理员只读（后端 /fb/reports/retry-sync 对 admin 403，设计文档 §3 矩阵）。
           auth.isAdmin 含 developer —— developer 仍可重试，所以这里只判 'admin' 角色。 -->
      <div v-if="auth.user?.role !== 'admin'" style="margin-top:8px;">
        <el-button size="small" @click="retryAll">重试全部失败的</el-button>
      </div>
    </div>

    <el-table :data="items" stripe border v-loading="loading" @selection-change="onSelect">
      <!-- 勾选框：只读角色（管理员/户管）没有批量删除动作，留着勾选框是误导 -->
      <el-table-column v-if="auth.canWriteReportRows" type="selection" width="45" />
      <!-- 数据列：可见性由「📊 列显示」控制（localStorage 持久化）。
           勾选框列与操作列不在此处 —— 它们由角色决定，不是展示偏好。 -->
      <el-table-column
        v-for="col in visibleColumnDefs" :key="col.prop"
        :prop="col.prop" :label="col.label"
        :min-width="col.cost ? costColWidth() : col.minWidth"
      >
        <template #default="{ row }">
          <!-- 「消耗」列：户管可内联改（仅此角色）；其余角色与改动前逐字一致。
               宽度：普通 user 100（几何不变）；户管多一个 ✏️ 按钮（flex-shrink:0，
               占位不收缩），100px 会把金额挤成省略号 ⇒ 仅对户管加宽到 150。 -->
          <template v-if="col.cost">
            <template v-if="auth.canEditReportCost">
              <div class="inline-edit-cell" v-if="editingCostId === row.id">
                <el-input v-model="editCostValue" size="small" class="inline-name-input"
                  :ref="el => { if (el) costInputRef = el }"
                  @blur="saveCost(row)" @keyup.enter="saveCost(row)" @keyup.escape="cancelCostEdit" />
              </div>
              <div class="inline-edit-cell" v-else>
                <span class="inline-cell-text">${{ row.cost?.toFixed(2) }}</span>
                <el-button link size="small" class="inline-edit-btn" @click.stop="startEditCost(row)">✏️</el-button>
              </div>
            </template>
            <template v-else>${{ row.cost?.toFixed(2) }}</template>
          </template>
          <template v-else-if="col.prop === 'cost_per_purchase'">${{ row.cost_per_purchase?.toFixed(2) }}</template>
          <template v-else>{{ row[col.prop] }}</template>
        </template>
      </el-table-column>
      <!-- 每行编辑/删除：只有能改自己整行的角色才渲染（管理员只读、户管仅可改消耗 →
           他们的改整行/删除走 API 会被后端 403，故整列不渲染） -->
      <el-table-column v-if="auth.canWriteReportRows" label="操作" width="140" fixed="right">
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

    <!-- 统计弹窗。③ 浏览类 · 前端分页：统计行 = 去重（产品×线名×日期）数，可上千，
         直通 el-table 会按行数建 DOM（Element Plus 不做虚拟滚动）。 -->
    <el-dialog v-model="statsVisible" title="数据统计" width="700px">
      <el-table :data="statsShown" stripe border>
        <el-table-column prop="product_name" label="产品名" />
        <el-table-column prop="line_name" label="线名" />
        <el-table-column prop="report_date" label="日期" width="110" />
        <el-table-column prop="total_cost" label="总消耗" width="100"><template #default="{row}">${{ row.total_cost?.toFixed(2) }}</template></el-table-column>
        <el-table-column prop="total_impressions" label="总展示" width="90" />
        <el-table-column prop="total_clicks" label="总点击" width="80" />
        <el-table-column prop="account_count" label="账户数" width="80" />
      </el-table>
      <div v-if="statsData.length > PAGE_SIZE" style="display:flex;justify-content:flex-end;margin-top:8px;">
        <el-pagination v-model:current-page="statsPage" :page-size="PAGE_SIZE"
          :total="statsData.length" layout="prev, pager, next" small background />
      </div>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted, nextTick } from 'vue'
import { fbApi } from '../../api/fb'
import { ElMessage } from 'element-plus'
import { sheetWriteApi } from '../../api/sheetWrite'
import { sheetWriteTone, sheetWriteHint } from '@/utils/sheetWriteUi'
import api from '../../api/client'
import { useAuthStore } from '../../stores/auth'

const auth = useAuthStore()
// 身份由 App.vue 根组件的 onMounted 水合，而子组件 setup 恒早于父组件 onMounted：
// 不补这一次，首帧 auth.user 还是 null ⇒ 按角色的 v-if 会算错。同类写法见
// components/OwnerFilterSelect.vue:22-27。
if (!auth.user) auth.initFromStorage()

const items = ref([]); const loading = ref(false); const page = ref(1); const size = ref(50); const total = ref(0)
const filterProduct = ref(''); const filterLine = ref(''); const dateRange = ref(null)

// 「保存人」筛选（仅跨用户角色渲染；未选中 = 不传该参数 = 看全部）
const filterOwner = ref('')
const ownerUsers = ref([])
async function loadOwnerUsers() {
  try {
    // 只列**有报表数据**的人。不能复用 /api/platform/users：那个口径是
    // 「该平台有未删除账户的人」（账户面板的筛选语义）。2026-10-19 实测：
    // fb_accounts 为空时下拉只剩户管一人，真有数据的 6 人全被漏掉。
    const res = await api.get('/fb/reports/owners')
    ownerUsers.value = res.users || []
  } catch { /* 下拉加载失败不阻塞主流程（同 OwnerFilterSelect.vue:56） */ }
}
function onOwnerFilter() { page.value = 1; loadData() }
const selectedIds = ref([]); const productOptions = ref([]); const lineOptions = ref([])
// ---------- 列选择（对齐 GG 数据管理页）----------
// 默认可见 = 改动前的默认形态：前 6 列可见、5 个详情列隐藏 ⇒ 普通 user 的表格几何不变。
// 偏好存 localStorage（key 与 GG 的分开），不落后端。
const COL_STORAGE_KEY = 'fb_data_manage_columns'
// 全部用 min-width（与 GG 页一致）：可见列少时，剩余宽度按比例分给**所有**列；
// 可见列多时各自收缩到最小值、出现横向滚动。
// ⚠️ 不要改回 `width` —— 固定宽度 + 列少 ⇒ 剩余宽度无处可去，列分配会很难看。
const allColumns = [
  { prop: 'report_date',       label: '日期',         minWidth: 110 },
  { prop: 'product_name',      label: '产品名',       minWidth: 100 },
  { prop: 'line_name',         label: '线名',         minWidth: 100 },
  { prop: 'account_name',      label: '账户名称',     minWidth: 120 },
  { prop: 'account_id',        label: '账户ID',       minWidth: 160 },
  { prop: 'cost',              label: '消耗',         cost: true },
  { prop: 'impressions',       label: '展示',         minWidth: 90 },
  { prop: 'clicks',            label: '点击',         minWidth: 80 },
  { prop: 'registrations',     label: '注册',         minWidth: 80 },
  { prop: 'purchases',         label: '购物',         minWidth: 80 },
  { prop: 'cost_per_purchase', label: '单词购物费用', minWidth: 120 },
]
const DEFAULT_VISIBLE_COLUMNS = ['report_date', 'product_name', 'line_name',
                                 'account_name', 'account_id', 'cost']
// 用户是否**显式**保存过列偏好。保存过 ⇒ 一切以用户选择为准，不再自动开详情列。
let hasExplicitColumnPrefs = false
function loadColumnPrefs() {
  try {
    const saved = localStorage.getItem(COL_STORAGE_KEY)
    if (saved) {
      const arr = JSON.parse(saved)
      // 过滤掉已不存在的列名（旧偏好指向已删列时不至于整表空掉）
      const known = arr.filter(p => allColumns.some(c => c.prop === p))
      if (known.length) { hasExplicitColumnPrefs = true; return known }
    }
  } catch (e) { /* 坏数据 ⇒ 回落默认 */ }
  return [...DEFAULT_VISIBLE_COLUMNS]
}
const visibleColumns = ref(loadColumnPrefs())
const visibleColumnDefs = computed(() =>
  allColumns.filter(c => visibleColumns.value.includes(c.prop)))
// 「消耗」列的最小宽：普通 user 100；户管多一个 ✏️ 按钮（不收缩） ⇒ 150。
function costColWidth() { return auth.canEditReportCost ? 150 : 100 }
function saveColumnPrefs() {
  hasExplicitColumnPrefs = true
  localStorage.setItem(COL_STORAGE_KEY, JSON.stringify(visibleColumns.value))
}
function toggleColumn(prop, checked) {
  if (checked) {
    // 按 allColumns 的顺序插回，避免勾选次序打乱表格列序
    const idx = allColumns.findIndex(c => c.prop === prop)
    const cur = [...visibleColumns.value]
    const at = cur.findIndex(p => allColumns.findIndex(c => c.prop === p) > idx)
    if (at === -1) cur.push(prop); else cur.splice(at, 0, prop)
    visibleColumns.value = cur
  } else {
    visibleColumns.value = visibleColumns.value.filter(p => p !== prop)
  }
  saveColumnPrefs()
}
const statsVisible = ref(false); const statsData = ref([])
// 前端分页（③ 浏览类）：见模板注释。权威数据是 `statsData`，这里只切当前页渲染。
const PAGE_SIZE = 50
const statsPage = ref(1)
const statsShown = computed(() =>
  statsData.value.slice((statsPage.value - 1) * PAGE_SIZE, statsPage.value * PAGE_SIZE))

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
    if (filterOwner.value) p.user_id = filterOwner.value      // 保存人筛选（仅跨用户角色会有值）
    const res = await fbApi.listReports(p)
    items.value = res.items; total.value = res.total
    // 与改动前一致：数据里有展示/点击时**自动打开详情列**。
    // 但一旦用户在「📊 列显示」里显式选择过，就以用户的选择为准，不再自动覆盖。
    if (!hasExplicitColumnPrefs &&
        items.value.some(r => r.impressions > 0 || r.clicks > 0)) {
      visibleColumns.value = allColumns.map(c => c.prop)
    }
  } finally { loading.value = false }
}
async function loadStats() {
  const p = {}
  if (filterProduct.value) p.product_name = filterProduct.value
  if (filterLine.value) p.line_name = filterLine.value
  if (dateRange.value) { p.date_from = dateRange.value[0]; p.date_to = dateRange.value[1] }
  if (filterOwner.value) p.user_id = filterOwner.value      // 统计的范围 = 屏幕上看到的范围
  const res = await fbApi.reportStats(p)
  statsData.value = res.data || []
  statsPage.value = 1    // 结果集变了 ⇒ 回第 1 页，否则当前页可能越过新末页
  statsVisible.value = true
}

// ===== 「消耗」内联编辑（仅户管；谓词 canEditReportCost 与后端 report_editable_fields 同口径）=====
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
  // blur 与 Enter 都会触发本函数：先落态的那次把 editingCostId 清掉 / 置 pending，
  // 后到的那次两个守卫之一即拦下，不会重复提交。
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
    await fbApi.updateReport(row.id, { cost: v })
    row.cost = v
    ElMessage.success('消耗已更新')
  } catch (e) {
    ElMessage.error('更新失败：' + (e.response?.data?.error || e.message))
  } finally {
    costPending = false
    cancelCostEdit()
  }
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

async function handleExport() {
  const p = {}
  if (filterProduct.value) p.product_name = filterProduct.value
  if (filterLine.value) p.line_name = filterLine.value
  if (dateRange.value) { p.date_from = dateRange.value[0]; p.date_to = dateRange.value[1] }
  if (filterOwner.value) p.user_id = filterOwner.value      // 导出的范围 = 屏幕上看到的范围
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

onMounted(() => { loadFilterOptions(); loadData(); loadFbSwFailures(); if (auth.canFilterReportOwner) loadOwnerUsers() })
</script>
<style scoped>
.fb-panel{padding:20px}.panel-header{margin-bottom:16px}.panel-header h2{margin:0;font-size:18px}.filter-bar{display:flex;gap:12px;margin-bottom:16px;align-items:center;flex-wrap:wrap}
/* 角色标识（只读 / 仅可改消耗）。只出现在本需求新开放的两个角色上，普通 user 界面无变化。
   配色沿用本仓既有语汇（薄荷青 #0891b2 = 能力色；中性灰 #6b7280），不引入新色。 */
.role-chip{display:inline-block;margin-left:8px;padding:1px 8px;border-radius:10px;font-size:12px;font-weight:500;vertical-align:middle}
.role-chip--readonly{background:#f3f4f6;color:#6b7280;border:1px solid #e5e7eb}
.role-chip--cost{background:rgba(8,145,178,0.10);color:#0891b2;border:1px solid rgba(8,145,178,0.25)}
/* 内联编辑：逐字沿用 views/AdsAccountPanel.vue:702-744 的范式（同一套交互心智） */
.inline-edit-cell{display:flex;align-items:center;gap:4px;min-width:0}
.inline-cell-text{white-space:nowrap;overflow:hidden;text-overflow:ellipsis;min-width:0;flex:1 1 auto}
.inline-edit-btn{opacity:0;transition:opacity .15s;font-size:13px;flex-shrink:0}
.inline-edit-cell:hover .inline-edit-btn{opacity:1}
.inline-name-input{width:100%}
/* 列选择器（与 GG 数据管理页同款） */
.column-selector{display:flex;flex-direction:column;gap:6px;max-height:300px;overflow-y:auto}
</style>
