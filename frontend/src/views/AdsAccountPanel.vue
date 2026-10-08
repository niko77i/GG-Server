<template>
  <div style="display:flex;flex-direction:column;height:100%;">
    <!-- 工具栏 — 固定 -->
    <div style="flex-shrink:0;">
      <div style="display:flex;gap:8px;margin-bottom:8px;align-items:center;">
        <el-button type="primary" @click="showModal()">➕ 新增账户</el-button>
        <el-button @click="batchVisible = true">📥 批量导入</el-button>
        <el-button @click="lookupVisible = true">🔍 批量查户</el-button>
        <el-button @click="batchRechargeVisible = true" :disabled="!selected.length">💰 批量充值</el-button>
        <el-button @click="syncVisible = true">🔄 同步</el-button>
        <el-button @click="deletedVisible = true">🗑 已删除</el-button>
        <span style="color:#888;font-size:12px;">已选 {{ selected.length }} 条</span>
        <el-select v-model="batchStatus" @change="doBatchStatus" placeholder="批量修改状态..."
          style="width:160px;" :disabled="!selected.length" clearable filterable>
          <el-option v-for="s in store.options.statuses" :key="s.id" :label="s.name" :value="s.id" />
        </el-select>
        <el-select v-model="batchMcc" @change="doBatchMcc" placeholder="批量修改 MCC..."
          style="width:180px;" :disabled="!selected.length" clearable filterable>
          <el-option v-for="m in mccOptions" :key="m.id" :label="m.name + ' (' + m.mcc_id + ')'" :value="m.id" />
        </el-select>
        <el-button v-if="selected.length" @click="batchDelete" style="margin-left:auto;">🗑 批量删除</el-button>
      </div>

      <!-- 状态按钮 -->
      <div style="display:flex;gap:8px;margin-bottom:8px;flex-wrap:wrap;align-items:center;">
        <el-button v-for="s in availableStatuses" :key="s" :type="store.acFilters.status === s ? 'primary' : 'default'" size="small" @click="toggleStatus(s)" style="font-weight:600;">{{ s }} {{ statusCounts[s] || 0 }}</el-button>
        <el-button v-if="store.acFilters.status" size="small" @click="clearStatus" type="info" plain>展示全部</el-button>
      </div>

      <div style="display:flex;gap:8px;margin-bottom:8px;">
        <el-input v-model="store.acFilters.search" placeholder="🔍 搜索名称/ID..." @input="search" style="flex:1;" clearable />
        <el-select v-model="store.acFilters.mcc_id" @change="searchAndLoad" placeholder="全部 MCC" style="width:180px;" clearable filterable>
          <el-option v-for="m in mccOptions" :key="m.id" :label="m.name + ' (' + m.mcc_id + ')'" :value="m.id" />
        </el-select>
        <el-select v-model="store.acFilters.agent" @change="searchAndLoad" placeholder="全部代理" style="width:130px;" clearable filterable>
          <el-option v-for="a in agentOptions" :key="a.id" :label="a.name" :value="a.name" />
        </el-select>
        <el-select v-model="store.acFilters.timezone" @change="filterByTimezone" placeholder="全部时区" style="width:140px;" clearable filterable>
          <el-option v-for="tz in timezoneOptions" :key="tz" :label="tz" :value="tz" />
        </el-select>
        <OwnerFilterSelect v-model="store.acFilters.owner_id" @change="searchAndLoad" />
        <ColumnSettings :panel-key="PANEL_KEYS.GG_ADS" :registry="GG_ADS_COLUMNS" />
      </div>
    </div>

    <!-- 表格 + 分页 — 滚动区 -->
    <div style="flex:1;min-height:0;overflow-y:auto;">
      <el-table v-if="columnPrefs.ready" :data="store.accounts" @selection-change="val => selected = val" :row-class-name="mccRowClass">
        <el-table-column type="selection" width="45" />
        <template v-for="key in visibleOrder" :key="key">
          <el-table-column v-if="key === 'name'" v-bind="COL_ATTRS.name">
            <template #default="{ row }">
              <div class="inline-edit-cell" v-if="editingNameId === row.id">
                <el-input v-model="editNameValue" size="small" class="inline-name-input"
                  :ref="el => { if (el) nameInputRef = el }"
                  @blur="saveName(row)" @keyup.enter="saveName(row)" @keyup.escape="cancelNameEdit" />
              </div>
              <div class="inline-edit-cell" v-else>
                <span class="inline-cell-text">{{ row.name }}</span>
                <el-button link size="small" class="inline-edit-btn" @click.stop="startEditName(row)">✏️</el-button>
              </div>
            </template>
          </el-table-column>
          <!-- 写表状态。语汇 / 位置 / 宽度逐字沿用一期 TT 账户表：⚠️ 点它即重试、✅ 已同步，
               两张表并列出现时跨平台一致。紧跟「账号 ID」—— 本表列多，横向必滚，
               埋到表尾在左滚状态下会被漏看，那就等于没做。 -->
          <el-table-column v-else-if="key === 'sheet_write'" v-bind="COL_ATTRS.sheet_write">
            <template #default="{ row }">
              <SheetWriteCell :failure="sheetWriteFailures[row.account_id]"
                @retry="retrySheetWrite(row)" />
            </template>
          </el-table-column>
          <el-table-column v-else-if="key === 'mcc'" v-bind="COL_ATTRS.mcc">
            <template #default="{ row }">
              <div class="inline-edit-cell" v-if="editingMccId === row.id">
                <el-select v-model="editMccValue" size="small" class="inline-mcc-select"
                  filterable clearable placeholder="选择 MCC"
                  @change="saveMcc(row)" @blur="onMccBlur"
                  @visible-change="v => { if (!v && !mccPending) cancelMccEdit() }">
                  <el-option v-for="m in mccOptions" :key="m.id"
                    :label="m.name + ' (' + m.mcc_id + ')'" :value="m.id" />
                </el-select>
              </div>
              <div class="inline-edit-cell" v-else>
                <div class="mcc-text-block" v-if="row.mcc_name">
                  <div class="inline-cell-text" style="color:#0891b2;">{{ row.mcc_name }}</div>
                  <div style="font-size:10px;color:#0891b2;white-space:nowrap;">{{ row.mcc_code }}</div>
                </div>
                <span v-else style="color:#888;white-space:nowrap;">未分配</span>
                <el-button link size="small" class="inline-edit-btn" @click.stop="startEditMcc(row)">✏️</el-button>
              </div>
            </template>
          </el-table-column>
          <el-table-column v-else-if="key === 'timezone'" v-bind="COL_ATTRS.timezone">
            <template #default="{ row }">
              <div class="inline-edit-cell" v-if="editingTimezoneId === row.id">
                <el-select v-model="editTimezoneValue" size="small" class="inline-tz-select"
                  filterable allow-create default-first-option placeholder="时区"
                  @change="saveTimezone(row)" @blur="onTimezoneBlur"
                  @visible-change="v => { if (!v && !tzPending) cancelTimezoneEdit() }">
                  <el-option v-for="tz in timezoneOptions" :key="tz" :label="tz" :value="tz" />
                </el-select>
              </div>
              <div class="inline-edit-cell" v-else>
                <span class="inline-cell-text">{{ row.timezone || '—' }}</span>
                <el-button link size="small" class="inline-edit-btn" @click.stop="startEditTimezone(row)">✏️</el-button>
              </div>
            </template>
          </el-table-column>
          <el-table-column v-else-if="key === 'agent'" v-bind="COL_ATTRS.agent">
            <template #default="{ row }">
              <div class="inline-edit-cell" v-if="editingAgentId === row.id">
                <el-select v-model="editAgentValue" size="small" class="inline-agent-select"
                  filterable clearable placeholder="选择代理"
                  @change="saveAgent(row)" @blur="onAgentBlur"
                  @visible-change="v => { if (!v && !agentPending) cancelAgentEdit() }">
                  <el-option v-for="a in agentOptions" :key="a.id" :label="a.name" :value="a.id" />
                </el-select>
              </div>
              <div class="inline-edit-cell" v-else>
                <span class="inline-cell-text">{{ row.agent || '—' }}</span>
                <el-button link size="small" class="inline-edit-btn" @click.stop="startEditAgent(row)">✏️</el-button>
              </div>
            </template>
          </el-table-column>
          <el-table-column v-else-if="key === 'status'" v-bind="COL_ATTRS.status">
            <template #default="{ row }">
              <div class="inline-edit-cell" v-if="editingStatusId === row.id">
                <el-select v-model="editStatusValue" size="small" class="inline-status-select"
                  filterable placeholder="选择状态"
                  @change="saveStatus(row)" @blur="onStatusBlur"
                  @visible-change="v => { if (!v && !statusPending) cancelStatusEdit() }">
                  <el-option v-for="s in store.options.statuses" :key="s.id" :label="s.name" :value="s.id" />
                </el-select>
              </div>
              <div class="inline-edit-cell" v-else>
                <el-tag size="small" class="status-tag" :type="row.status === '存活' ? 'success' : row.status === '验证' ? 'warning' : row.status === '死亡' ? 'danger' : 'info'">{{ row.status || '未知' }}</el-tag>
                <el-button link size="small" class="inline-edit-btn" @click.stop="startEditStatus(row)">✏️</el-button>
              </div>
            </template>
          </el-table-column>
          <el-table-column v-else-if="key === 'status_changed'" v-bind="COL_ATTRS.status_changed">
            <template #default="{ row }">
              <span v-if="row.status_changed_date" style="font-size:12px;">{{ row.status_changed_date }}</span>
              <span v-else style="color:#ccc;">—</span>
            </template>
          </el-table-column>
          <!-- 户归属：只有户管可见可编辑（规格 §9.2）。管理员的入口在 AccountModal，不在这里。 -->
          <el-table-column v-else-if="key === 'owner'" v-bind="COL_ATTRS.owner">
            <template #header>
              <el-tooltip placement="top"
                content="这个户归谁管。如果配置了户管看板，改这里会把新归属写进看板的「重新分配」列（TT 是「换绑情况」列），等你在看板同步时生效。">
                <span style="cursor:help;">户归属 ⓘ</span>
              </el-tooltip>
            </template>
            <template #default="{ row }">
              <OwnerCell :row="row" account-key="account_id"
                :loaded="ownerOptionsLoaded" :failed="ownerOptionsFailed"
                :options="ownerOptions" :option-map="ownerOptionMap"
                :pending="ownerPending"
                @change="(v) => changeOwner(row, v)" />
            </template>
          </el-table-column>
          <!-- 纯 prop 列兜底：account_id / acquired_date 走这里 -->
          <el-table-column v-else v-bind="COL_ATTRS[key]" />
        </template>
        <el-table-column label="操作" width="200">
          <template #default="{ row }">
            <el-button link type="primary" size="small" @click="showModal(row.id)">✏️</el-button>
            <el-button link type="success" size="small" @click="showDetail(row.id)">📋</el-button>
            <el-button link type="warning" size="small" @click="openRecharge(row)">💰</el-button>
            <el-button link type="danger" size="small" @click="del(row)"><el-icon :size="14"><Delete /></el-icon></el-button>
          </template>
        </el-table-column>
      </el-table>

      <div style="display:flex;align-items:center;justify-content:center;gap:8px;margin-top:12px;">
        <el-pagination v-if="store.acTotal > store.acPageSize" v-model:current-page="store.acPage"
          :page-size="store.acPageSize" :total="store.acTotal" background
          layout="prev,pager,next" size="small" :pager-count="7" @current-change="load" />
        <el-select v-model="store.acPageSize" @change="store.acPage = 1; load()" size="small" style="width:90px;" filterable>
          <el-option v-for="s in [10,20,50,100]" :key="s" :label="s+'条/页'" :value="s" />
        </el-select>
      </div>
    </div>

    <AccountModal v-model:visible="acModalVisible" :edit-id="acEditId" @saved="load" />
    <AccountBatchImportModal v-model:visible="batchVisible" @saved="load" />
    <AccountBatchLookupModal v-model:visible="lookupVisible" />
    <AccountDetailModal v-model:visible="detailVisible" :account-id="detailAccountId" />
    <RechargeModal v-model:visible="rechargeVisible" :default-account-id="rechargeAccountId" @saved="onRecharged" />
    <RechargeBatchModal v-model:visible="batchRechargeVisible" :accounts="selected" @saved="onBatchRecharged" />
    <AccountSyncModal v-model:visible="syncVisible" @synced="onSynced" />
    <AccountDeletedModal v-model:visible="deletedVisible" @restored="onRestored" />
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted, nextTick } from 'vue'
import { useAccountStore } from '@/stores/accounts'
import { sheetWriteApi } from '@/api/sheetWrite'
import { SHEET_WRITE_TOAST, sheetWriteTone, sheetWriteHint } from '@/utils/sheetWriteUi'
import SheetWriteCell from '@/components/cells/SheetWriteCell.vue'
import OwnerCell from '@/components/cells/OwnerCell.vue'
import AccountModal from '@/components/AccountModal.vue'
import AccountBatchImportModal from '@/components/AccountBatchImportModal.vue'
import AccountBatchLookupModal from '@/components/AccountBatchLookupModal.vue'
import AccountDetailModal from '@/components/AccountDetailModal.vue'
import RechargeModal from '@/components/RechargeModal.vue'
import RechargeBatchModal from '@/components/RechargeBatchModal.vue'
import AccountSyncModal from '@/components/AccountSyncModal.vue'
import AccountDeletedModal from '@/components/AccountDeletedModal.vue'
import OwnerFilterSelect from '@/components/OwnerFilterSelect.vue'
import ColumnSettings from '@/components/ColumnSettings.vue'
import { PANEL_KEYS, GG_ADS_COLUMNS } from '@/constants/accountColumns'
import { indexByKey } from '@/utils/columnPrefsLogic.mjs'
import { useColumnPrefsStore } from '@/stores/columnPrefs'
import { useOwnerPicker } from '@/composables/useOwnerPicker'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Delete } from '@element-plus/icons-vue'

const store = useAccountStore()
// 自定义列：可见列顺序来自 columnPrefs store（缺省走注册表默认顺序）。
// COL_ATTRS 是 key → 可 v-bind 列属性的索引，供各 v-if 分支取用。
const columnPrefs = useColumnPrefsStore()
const COL_ATTRS = indexByKey(GG_ADS_COLUMNS)
const visibleOrder = computed(() => columnPrefs.visibleOrder(PANEL_KEYS.GG_ADS, GG_ADS_COLUMNS))
// 「默认只展示存活」必须在 **setup 顶层**落进筛选状态，不能放 onMounted：
// 子组件 OwnerFilterSelect 的 setup 恒早于本组件 onMounted，它会同步 emit('change')
// → searchAndLoad() → loadAccounts()，首次请求就以 status=''（全部状态）发出。
// 等 onMounted 再补 status='存活' 时，dedupLoader 见首次请求仍在途 → 返回同一 Promise
// 不重发，后端从未收到 status=存活 —— 表现为「按钮高亮存活、表格却是全部状态」。
// （同款抢跑教训见 OwnerFilterSelect.vue 顶部注释。）
if (!store.acFilters.status) store.acFilters.status = '存活'
const selected = ref([])
const acModalVisible = ref(false)
const acEditId = ref(null)
const batchVisible = ref(false)
const lookupVisible = ref(false)
const detailVisible = ref(false)
const detailAccountId = ref(null)
const rechargeVisible = ref(false)
const rechargeAccountId = ref('')
const batchRechargeVisible = ref(false)
const syncVisible = ref(false)
const deletedVisible = ref(false)
const batchStatus = ref('')
const batchMcc = ref('')
const mccOptions = ref([])
const agentOptions = ref([])
const timezoneOptions = ref([])
const statusCounts = ref({})

// ---------- 写表失败治理（GG 的 9 个写表点位） ----------
const SHEET_WRITE_POLL_MS = 3000
const SHEET_WRITE_POLL_MAX = 14          // ~42s，覆盖 30s 重试窗口
// GG 下两个 target 共用一个 business_key 命名空间：gg_my_dashboard 的键是
// accounts.account_id（带连字符的 Ads ID），gg_recharge 的键是充值记录主键（裸整数）。
// 两种格式今天不相交，但没有任何东西保证它俩永远不相交 —— 不按 target 过滤的后果是
// 把充值失败标到账户行上、并用错的 target 去重试。故本表这一列只认 gg_my_dashboard。
const DASH_TARGET = 'gg_my_dashboard'    // 「我的看板」：本表列与改状态/删户/恢复/批量/从表同步
const RECHARGE_TARGET = 'gg_recharge'    // 充值记录：改状态清账腿、单笔/批量充值
// 每个 (target, business_key) 一个轮询定时器。批量操作在 for 里逐键调度，共用一个变量
// 会让每次调用把上一个键的定时器 clear 掉 —— 批量 N 个只有最后 1 个会弹提示。
const sheetWriteTimers = new Map()       // `${target}|${business_key}` -> timerId
const sheetWriteFailures = ref({})       // account_id -> {target, status, error_msg}

// 内联编辑状态
const editingNameId = ref(null)
const editingMccId = ref(null)
const editingTimezoneId = ref(null)
const editingAgentId = ref(null)
const editingStatusId = ref(null)
const editNameValue = ref('')
const editMccValue = ref(null)
const editTimezoneValue = ref('')
const editAgentValue = ref(null)
const editStatusValue = ref(null)
let nameInputRef = null
let mccPending = false
let tzPending = false
let agentPending = false
let statusPending = false
let searchTimer = null

onMounted(() => {
  store.loadSettings()
  store.loadAgents()
  store.loadStatuses()
  load()
  // 初始拉一次写表标记。load() 成功分支里也会拉，但 load() 请求失败时会跳过那次，
  // 所以这里再保证一次：标记是「失败必须可见」的兜底，不能随列表请求的成败而丢。
  loadSheetWriteFailures()
})

onUnmounted(() => {
  for (const t of sheetWriteTimers.values()) clearTimeout(t)
  sheetWriteTimers.clear()
})

async function load() {
  const res = await store.loadAccounts()
  mccOptions.value = res.mcc_options || []
  // 代理下拉改取 accounts/list 的 agents：口径与当前列表一致，且跨用户角色（户管/admin）也有值。
  // 原先取 store.options.agents（= 自己名下的全部代理），户管名下没有代理 → 下拉恒为空。
  agentOptions.value = res.agents || []
  timezoneOptions.value = res.timezone_options || []
  if (res.status_counts) statusCounts.value = res.status_counts
  // 列表每次刷新都重拉标记：轮询到终态后也靠它把行标记补上（即时提示 + 持久标记要同时到位）
  loadSheetWriteFailures()
}

function filterByTimezone() { store.acPage = 1; load() }

const availableStatuses = computed(() => {
  const configStatuses = store.options.statuses || []
  const allNames = new Set([...Object.keys(statusCounts.value), ...configStatuses.map(s => s.name)])
  const orderMap = Object.fromEntries(configStatuses.map((s, i) => [s.name, i]))
  return [...allNames].filter(s => (statusCounts.value[s] || 0) > 0)
    .sort((a, b) => (orderMap[a] ?? 999) - (orderMap[b] ?? 999))
})

function toggleStatus(s) { store.acFilters.status = store.acFilters.status === s ? '' : s; store.acPage=1; load() }
function clearStatus() { store.acFilters.status=''; store.acPage=1; load() }

// MCC 分组：相邻相同 MCC 归一组，奇偶交替着色
const mccGroupIndex = computed(() => {
  const map = {}
  let key = null, idx = 0
  for (const r of store.accounts) {
    const k = r.mcc_code || r.mcc_name || '__none__'
    if (k !== key) { idx++; key = k }
    map[r.id] = idx
  }
  return map
})
function mccRowClass({ row }) {
  const g = mccGroupIndex.value[row.id] || 0
  return g % 2 === 0 ? 'mcc-row-even' : 'mcc-row-odd'
}

function search() {
  clearTimeout(searchTimer)
  searchTimer = setTimeout(() => { store.acPage = 1; load() }, 500)
}
function searchAndLoad() { store.acPage = 1; load() }
function showModal(id) { acEditId.value = id || null; acModalVisible.value = true }
function showDetail(id) { detailAccountId.value = id; detailVisible.value = true }

function openRecharge(row) {
  rechargeAccountId.value = row.account_id
  rechargeVisible.value = true
}

// 单笔充值的触发点 ⑥：id 是充值记录主键（gg_recharge 的 business_key）。
// 有 id 也可能没有写表（未配表格）—— 那是「无记录 = 不提示」，由 pollSheetWrite 兜。
function onRecharged(res) {
  load()
  if (res?.id != null) pollSheetWrite(RECHARGE_TARGET, String(res.id))
}

function onBatchRecharged(res) {
  selected.value = []
  load()
  // 触发点 ⑥（批量）：一记录一个键，逐键独立计时
  for (const id of res?.recharge_ids || []) pollSheetWrite(RECHARGE_TARGET, String(id))
}

async function del(row) {
  await ElMessageBox.confirm('确定删除此账户？', '确认', { type: 'warning' })
  await store.deleteAccount(row.id)
  // 触发点 ②：删户会写「我的看板」H 列（解绑）。行数据里就有 account_id。
  pollSheetWrite(DASH_TARGET, row.account_id)
}

async function batchDelete() {
  if (!selected.value.length) return
  await ElMessageBox.confirm(`确定删除选中的 ${selected.value.length} 个账户？`, '确认', { type: 'warning' })
  await store.batchDeleteAccounts(selected.value.map(s => s.id))
}

// 触发点 ③：恢复账户会写「我的看板」H 列（清空解绑）。被删的户已不在本列表里，
// 快照不到行数据，故由 AccountDeletedModal 把 account_id 带出来。
function onRestored(accountId) {
  load()
  if (accountId) pollSheetWrite(DASH_TARGET, accountId)
}

// 触发点 ⑤：从表同步的回写腿涉及的账户，由响应带出（未配表格时后端回空表 ⇒ 不轮询）
function onSynced(accountIds) {
  load()
  for (const id of accountIds || []) pollSheetWrite(DASH_TARGET, id)
}

// ===== 名称内联编辑 =====
function startEditName(row) {
  editingNameId.value = row.id
  editNameValue.value = row.name
  nextTick(() => {
    nameInputRef?.focus?.()
    nameInputRef?.select?.()
  })
}
function cancelNameEdit() {
  editingNameId.value = null
  editNameValue.value = ''
  nameInputRef = null
}
async function saveName(row) {
  const v = editNameValue.value.trim()
  if (!v || v === row.name) { cancelNameEdit(); return }
  try {
    await store.updateAccount(row.id, { name: v })
    row.name = v
    ElMessage.success('名称已更新')
  } catch (e) {
    ElMessage.error('更新名称失败')
  }
  cancelNameEdit()
}

// ===== MCC 内联编辑 =====
function startEditMcc(row) {
  editingMccId.value = row.id
  editMccValue.value = row.mcc_id ?? null
  mccPending = false
}
function cancelMccEdit() {
  editingMccId.value = null
  editMccValue.value = null
  mccPending = false
}
async function saveMcc(row) {
  const v = editMccValue.value ?? null
  if (v === (row.mcc_id ?? null)) { cancelMccEdit(); return }
  mccPending = true
  try {
    await store.updateAccount(row.id, { mcc_id: v })
    const m = mccOptions.value.find(x => x.id === v)
    row.mcc_name = m ? m.name : null
    row.mcc_code = m ? m.mcc_id : null
    row.mcc_id = v
    ElMessage.success('MCC 已更新')
  } catch (e) {
    ElMessage.error('更新 MCC 失败')
  }
  cancelMccEdit()
}
function onMccBlur() {
  setTimeout(() => {
    if (!mccPending && editingMccId.value !== null) cancelMccEdit()
  }, 200)
}

// ===== 时区内联编辑 =====
function startEditTimezone(row) {
  editingTimezoneId.value = row.id
  editTimezoneValue.value = row.timezone || ''
  tzPending = false
}
function cancelTimezoneEdit() {
  editingTimezoneId.value = null
  editTimezoneValue.value = ''
  tzPending = false
}
async function saveTimezone(row) {
  const v = editTimezoneValue.value || ''
  if (v === (row.timezone || '')) { cancelTimezoneEdit(); return }
  tzPending = true
  try {
    await store.updateAccount(row.id, { timezone: v })
    row.timezone = v
    // 如果新时区不在选项中，加入列表
    if (v && !timezoneOptions.value.includes(v)) {
      timezoneOptions.value.push(v)
    }
    ElMessage.success('时区已更新')
  } catch (e) {
    ElMessage.error('更新时区失败')
  }
  cancelTimezoneEdit()
}
function onTimezoneBlur() {
  setTimeout(() => {
    if (!tzPending && editingTimezoneId.value !== null) cancelTimezoneEdit()
  }, 200)
}

// ===== 代理内联编辑 =====
function startEditAgent(row) {
  editingAgentId.value = row.id
  // 根据 row.agent 名称找到对应的 agent_id
  const found = agentOptions.value.find(a => a.name === row.agent)
  editAgentValue.value = found ? found.id : null
  agentPending = false
}
function cancelAgentEdit() {
  editingAgentId.value = null
  editAgentValue.value = null
  agentPending = false
}
async function saveAgent(row) {
  const v = editAgentValue.value ?? null
  const currentAgentId = agentOptions.value.find(a => a.name === row.agent)?.id ?? null
  if (v === currentAgentId) { cancelAgentEdit(); return }
  agentPending = true
  try {
    await store.updateAccount(row.id, { agent_id: v })
    const a = agentOptions.value.find(x => x.id === v)
    row.agent = a ? a.name : null
    row.agent_name = a ? a.name : null
    ElMessage.success('代理已更新')
  } catch (e) {
    ElMessage.error('更新代理失败')
  }
  cancelAgentEdit()
}
function onAgentBlur() {
  setTimeout(() => {
    if (!agentPending && editingAgentId.value !== null) cancelAgentEdit()
  }, 200)
}

// ===== 状态内联编辑 =====
function startEditStatus(row) {
  editingStatusId.value = row.id
  // 根据 row.status 名称找到对应的 status_id
  const found = store.options.statuses.find(s => s.name === row.status)
  editStatusValue.value = found ? found.id : null
  statusPending = false
}
function cancelStatusEdit() {
  editingStatusId.value = null
  editStatusValue.value = null
  statusPending = false
}
async function saveStatus(row) {
  const v = editStatusValue.value ?? null
  const currentStatusId = store.options.statuses.find(s => s.name === row.status)?.id ?? null
  if (v === currentStatusId) { cancelStatusEdit(); return }
  statusPending = true
  try {
    const res = await store.updateAccount(row.id, { status_id: v })
    const s = store.options.statuses.find(x => x.id === v)
    row.status = s ? s.name : null
    row.status_name = s ? s.name : null
    // 后端会自动处理 status_changed_date，这里先乐观更新
    row.status_changed_date = new Date().toISOString().slice(0, 10)
    ElMessage.success('状态已更新')
    // 触发点 ①：改状态同时打两条写表腿 —— 本户的「我的看板」+ 可能的清账记录
    pollSheetWrite(DASH_TARGET, row.account_id)
    if (res?.clear_recharge_id != null) pollSheetWrite(RECHARGE_TARGET, String(res.clear_recharge_id))
  } catch (e) {
    ElMessage.error('更新状态失败')
  }
  cancelStatusEdit()
}
function onStatusBlur() {
  setTimeout(() => {
    if (!statusPending && editingStatusId.value !== null) cancelStatusEdit()
  }, 200)
}

async function doBatchStatus(val) {
  if (!val) return
  const st = store.options.statuses.find(s => s.id === val)
  const stName = st ? st.name : val
  try {
    await ElMessageBox.confirm(
      `确定将选中的 ${selected.value.length} 个账户状态改为「${stName}」？`,
      '批量修改状态', { type: 'warning', confirmButtonText: '确定', cancelButtonText: '取消' }
    )
  } catch { batchStatus.value = ''; return }
  // 快照本批账户与数量：batchUpdateAccounts 会重载列表，selected 随之清空
  const acctIds = selected.value.map(s => s.account_id)
  const count = selected.value.length
  const res = await store.batchUpdateAccounts({ ids: selected.value.map(s => s.id), field: 'status_id', value: val })
  ElMessage.success(`已将 ${count} 个账户状态改为「${stName}」`)
  batchStatus.value = ''
  // 触发点 ④：本批每户各一条「我的看板」写表腿，外加每笔清账记录
  for (const id of acctIds) pollSheetWrite(DASH_TARGET, id)
  for (const rid of res?.clear_recharge_ids || []) pollSheetWrite(RECHARGE_TARGET, String(rid))
}
async function doBatchMcc(val) {
  if (!val) return
  await store.batchUpdateAccounts({ ids: selected.value.map(s => s.id), field: 'mcc_id', value: val })
  batchMcc.value = ''
}

// ===== 写表失败治理：轮询 / 行标记 / 重试 =====
/** 列表标记用：拉本用户全部「需要提示」的写表终态。静默失败（不打扰用户）。 */
async function loadSheetWriteFailures() {
  try {
    const res = await sheetWriteApi.status({ platform: 'gg' })
    const map = {}
    for (const it of res.items || []) {
      if (it.target !== DASH_TARGET) continue   // 见 DASH_TARGET 处的说明：两个 target 共用键空间
      map[it.business_key] = it
    }
    sheetWriteFailures.value = map
  } catch { /* 标记拉不到不该打扰用户，保持上一次的结果 */ }
}

/**
 * 轮询单条直到终态。中间态（pending/failed）继续等，不提示。
 *
 * target 是本函数的第一参数（TT 那份不需要，TT 只有一个 target）：它既决定
 * 「这次查的是哪条写表腿」，也用来挡住同 business_key、不同 target 的记录。
 */
function pollSheetWrite(target, businessKey) {
  const timerKey = target + '|' + businessKey
  let attempts = 0
  // 本键轮询停止（终态 / 无记录 / synced / 超限 / 异常）时统一摘掉自己的表项，
  // 避免 Map 无界增长。每个 return 路径都要走到这里。
  const stop = () => { sheetWriteTimers.delete(timerKey) }
  const tick = async () => {
    if (attempts >= SHEET_WRITE_POLL_MAX) { stop(); return }
    attempts++
    try {
      const res = await sheetWriteApi.status({ platform: 'gg', businessKey })
      const it = res.item
      // 无记录 = 这条路径没触发写表，**不是失败**。Task 4 的 clear_recharge_id /
      // clear_recharge_ids / recharge_ids / id 只要 DB 行插进去了就回，未配表格时
      // 根本没登记 sheet_write_log ⇒ 这里 !it ⇒ 不提示。把「有 id」当失败
      // 正是 Task 2 修过的镜像 bug（没配表却冒 ⚠️），不能走回去。
      if (!it || it.target !== target) { stop(); return }
      if (it.status === 'synced') { loadSheetWriteFailures(); stop(); return }
      if (it.status === 'pending' || it.status === 'failed') {
        sheetWriteTimers.set(timerKey, setTimeout(tick, SHEET_WRITE_POLL_MS))
        return
      }
      // 三种需提示的终态 —— 文案与行内 tooltip 同源（sheetWriteHint），避免两处各写一份
      const hint = sheetWriteHint(it)
      SHEET_WRITE_TOAST[sheetWriteTone(it.status)](hint)
      loadSheetWriteFailures()
      stop()
    } catch { stop() /* 轮询失败静默，靠列表标记兜底 */ }
  }
  // 同键重入（例如重试按钮）时先清掉旧链，保证一个键只有一条在跑
  const prev = sheetWriteTimers.get(timerKey)
  if (prev) clearTimeout(prev)
  sheetWriteTimers.set(timerKey, setTimeout(tick, SHEET_WRITE_POLL_MS))
}

/** 重试按钮。target 取自日志行本身（本表列 = gg_my_dashboard），不硬编码。 */
async function retrySheetWrite(row) {
  const f = sheetWriteFailures.value[row.account_id]
  if (!f) return
  try {
    await sheetWriteApi.retry({ platform: 'gg', target: f.target, businessKey: row.account_id })
    ElMessage.success('已重新提交，请稍后查看结果')
    pollSheetWrite(f.target, row.account_id)
  } catch (e) {
    ElMessage.error(e.response?.data?.error || '重试失败')
  }
}

// ===== 「户归属」列（仅户管可见可编辑）=====
// 视觉规格：docs/superpowers/specs/2026-09-24-huguan-frontend-visual-design.md §5
// 状态 / 水合时机的惰性加载 / 乐观更新均封装在 useOwnerPicker（GG 与 TT 逐字同构，只差 reassign 实现）。
// 角色闸门（§5.2：非户管整个字段不渲染）已上移到列注册表 accountColumns.js 的
// `available: (auth) => auth.isHuguan`，模板与脚本均无 v-if 依赖，此处不再引入 authStore。
const {
  ownerOptions,
  ownerOptionsLoaded,
  ownerOptionsFailed,
  ownerPending,
  ownerOptionMap,
  changeOwner
} = useOwnerPicker((id, body) => store.reassignAccount(id, body))
</script>

<style scoped>
/* 固定表头：列表滚动时表头吸附在顶部（需同时覆盖 .el-table 默认 overflow:hidden） */
:deep(.el-table) {
  overflow: visible;
}
:deep(.el-table__header-wrapper) {
  position: sticky;
  top: 0;
  z-index: 10;
  background-color: var(--el-table-header-bg-color);
}
/* 修复勾选框被 cell overflow 裁切的问题 */
:deep(.el-table-column--selection .cell) {
  overflow: visible !important;
}
:deep(.mcc-row-even) td {
  background-color: #f2f4f7 !important;
}
:deep(.mcc-row-odd) td {
  background-color: #e2e6ed !important;
}
/* 覆盖默认 hover 浅色，改为微暗叠加，保持 MCC 分组色可辨 */
:deep(.el-table__body tr:hover > td) {
  background-color: rgba(0,0,0,0.10) !important;
}
/* 内联编辑 */
.inline-edit-cell {
  display: flex;
  align-items: center;
  gap: 4px;
  min-width: 0;
}
.inline-cell-text {
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  min-width: 0;
  flex: 1 1 auto;
}
.mcc-text-block {
  flex: 1 1 auto;
  min-width: 0;
  display: flex;
  flex-direction: column;
  line-height: 1.3;
}
.inline-edit-btn {
  opacity: 0;
  transition: opacity 0.15s;
  font-size: 13px;
  flex-shrink: 0;
}
.inline-edit-cell:hover .inline-edit-btn {
  opacity: 1;
}
.status-tag {
  max-width: 80px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  flex-shrink: 1;
}
.inline-name-input,
.inline-mcc-select,
.inline-tz-select,
.inline-agent-select,
.inline-status-select {
  width: 100%;
}
</style>
