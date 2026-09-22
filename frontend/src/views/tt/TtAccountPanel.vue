<template>
  <div style="display:flex;flex-direction:column;height:100%;">
    <!-- 页面标题 -->
    <div style="flex-shrink:0;margin-bottom:12px;">
      <h2 style="margin:0;font-size:18px;font-weight:600;">广告账户</h2>
    </div>
    <!-- 工具栏 — 固定 -->
    <div style="flex-shrink:0;">
      <div style="display:flex;gap:8px;margin-bottom:8px;align-items:center;">
        <el-button type="primary" @click="showModal()">➕ 新增账户</el-button>
        <el-button @click="importVisible = true">📥 批量导入</el-button>
        <el-button @click="lookupVisible = true">🔍 批量查户</el-button>
        <el-button @click="rechargeBatchVisible = true" :disabled="!selected.length">💰 批量充值</el-button>
        <el-button @click="syncVisible = true">🔄 同步</el-button>
        <el-button @click="deletedVisible = true">🗑 回收站</el-button>
        <span style="color:#888;font-size:12px;">已选 {{ selected.length }} 条</span>
        <el-select v-model="batchStatus" @change="doBatchStatus" placeholder="批量修改状态..."
          style="width:160px;" :disabled="!selected.length" clearable filterable>
          <el-option v-for="s in statusOptions" :key="s.id" :label="s.name" :value="s.id" />
        </el-select>
        <el-select v-model="batchBc" @change="doBatchBc" placeholder="批量修改 BC..."
          style="width:180px;" :disabled="!selected.length" clearable filterable>
          <el-option v-for="b in bcOptions" :key="b.id" :label="b.name + ' (' + b.bc_id + ')'" :value="b.id" />
        </el-select>
        <el-button v-if="selected.length" @click="batchDelete" style="margin-left:auto;">🗑 批量删除</el-button>
      </div>

      <!-- 状态按钮 -->
      <div style="display:flex;gap:8px;margin-bottom:8px;flex-wrap:wrap;align-items:center;">
        <el-button v-for="s in availableStatuses" :key="s" :type="isStatusActive(s) ? 'primary' : 'default'" size="small" @click="toggleStatus(s)" style="font-weight:600;">{{ s }} {{ statusCounts[s] || 0 }}</el-button>
        <el-button v-if="statusId" size="small" @click="clearStatus" type="info" plain>展示全部</el-button>
      </div>

      <div style="display:flex;gap:8px;margin-bottom:8px;">
        <el-input v-model="search" placeholder="🔍 搜索名称/广告账户 ID..." @input="onSearch" style="flex:1;" clearable />
        <el-select v-model="bcId" @change="filterAndLoad" placeholder="全部 BC" style="width:180px;" clearable filterable>
          <el-option v-for="b in bcOptions" :key="b.id" :label="b.name + ' (' + b.bc_id + ')'" :value="b.id" />
        </el-select>
        <el-select v-model="agentId" @change="filterAndLoad" placeholder="全部代理" style="width:130px;" clearable filterable>
          <el-option v-for="a in agentOptions" :key="a.id" :label="a.name" :value="a.id" />
        </el-select>
        <el-select v-model="timezone" @change="filterAndLoad" placeholder="全部时区" style="width:140px;" clearable filterable>
          <el-option v-for="tz in timezoneOptions" :key="tz" :label="tz" :value="tz" />
        </el-select>
        <OwnerFilterSelect v-model="ownerId" @change="filterAndLoad" />
      </div>
    </div>

    <!-- 表格 + 分页 — 滚动区 -->
    <div style="flex:1;min-height:0;overflow-y:auto;">
      <el-table :data="items" @selection-change="val => selected = val" :row-class-name="bcRowClass">
        <el-table-column type="selection" width="45" />
        <el-table-column label="账户名称" min-width="140">
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
        <el-table-column prop="advertiser_id" label="广告账户 ID" min-width="150" show-overflow-tooltip />
        <el-table-column label="所属 BC" min-width="160">
          <template #default="{ row }">
            <div class="inline-edit-cell" v-if="editingBcId === row.id">
              <el-select v-model="editBcValue" size="small" class="inline-bc-select"
                filterable clearable placeholder="选择 BC"
                @change="saveBc(row)" @blur="onBcBlur"
                @visible-change="v => { if (!v && !bcPending) cancelBcEdit() }">
                <el-option v-for="b in bcOptions" :key="b.id"
                  :label="b.name + ' (' + b.bc_id + ')'" :value="b.id" />
              </el-select>
            </div>
            <div class="inline-edit-cell" v-else>
              <el-tooltip v-if="row.bc_name" placement="top" :show-after="300"
                :content="row.bc_name + (bcCode(row) ? '（' + bcCode(row) + '）' : '')">
                <div class="bc-text-block">
                  <div class="inline-cell-text" style="color:#0891b2;">{{ row.bc_name }}</div>
                  <div v-if="bcCode(row)" style="font-size:10px;color:#0891b2;white-space:nowrap;">{{ bcCode(row) }}</div>
                </div>
              </el-tooltip>
              <span v-else style="color:#888;white-space:nowrap;">未分配</span>
              <el-button link size="small" class="inline-edit-btn" @click.stop="startEditBc(row)">✏️</el-button>
            </div>
          </template>
        </el-table-column>
        <el-table-column label="时区" min-width="120">
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
        <el-table-column label="代理" min-width="140">
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
        <el-table-column label="状态" min-width="120">
          <template #default="{ row }">
            <div class="inline-edit-cell" v-if="editingStatusId === row.id">
              <el-select v-model="editStatusValue" size="small" class="inline-status-select"
                filterable placeholder="选择状态"
                @change="saveStatus(row)" @blur="onStatusBlur"
                @visible-change="v => { if (!v && !statusPending) cancelStatusEdit() }">
                <el-option v-for="s in statusOptions" :key="s.id" :label="s.name" :value="s.id" />
              </el-select>
            </div>
            <div class="inline-edit-cell" v-else>
              <el-tag size="small" class="status-tag" :type="statusTagType(row.status)">{{ row.status || '未知' }}</el-tag>
              <el-button link size="small" class="inline-edit-btn" @click.stop="startEditStatus(row)">✏️</el-button>
            </div>
          </template>
        </el-table-column>
        <el-table-column label="国家" min-width="110">
          <template #default="{ row }">
            <div class="inline-edit-cell" v-if="editingCountryId === row.id">
              <el-input v-model="editCountryValue" size="small" class="inline-name-input"
                :ref="el => { if (el) countryInputRef = el }"
                @blur="saveCountry(row)" @keyup.enter="saveCountry(row)" @keyup.escape="cancelCountryEdit" />
            </div>
            <div class="inline-edit-cell" v-else>
              <span class="inline-cell-text">{{ row.country || '—' }}</span>
              <el-button link size="small" class="inline-edit-btn" @click.stop="startEditCountry(row)">✏️</el-button>
            </div>
          </template>
        </el-table-column>
        <el-table-column label="消耗情况" min-width="120">
          <template #default="{ row }">
            <div class="inline-edit-cell" v-if="editingConsumptionId === row.id">
              <el-input v-model="editConsumptionValue" size="small" class="inline-name-input"
                :ref="el => { if (el) consumptionInputRef = el }"
                @blur="saveConsumption(row)" @keyup.enter="saveConsumption(row)" @keyup.escape="cancelConsumptionEdit" />
            </div>
            <div class="inline-edit-cell" v-else>
              <span class="inline-cell-text">{{ row.consumption || '—' }}</span>
              <el-button link size="small" class="inline-edit-btn" @click.stop="startEditConsumption(row)">✏️</el-button>
            </div>
          </template>
        </el-table-column>
        <el-table-column prop="acquired_date" label="到手时间" min-width="100" show-overflow-tooltip />
        <el-table-column label="状态变更时间" min-width="110" show-overflow-tooltip>
          <template #default="{ row }">
            <span v-if="row.status_changed_date" style="font-size:12px;">{{ row.status_changed_date }}</span>
            <span v-else style="color:#ccc;">—</span>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="200">
          <template #default="{ row }">
            <el-button link type="primary" size="small" @click="showModal(row)">✏️</el-button>
            <el-button link type="success" size="small" @click="showDetail(row)">📋</el-button>
            <el-button link type="warning" size="small" @click="openRecharge(row)">💰</el-button>
            <el-button link type="danger" size="small" @click="del(row.id)"><el-icon :size="14"><Delete /></el-icon></el-button>
          </template>
        </el-table-column>
      </el-table>

      <div style="display:flex;align-items:center;justify-content:center;gap:8px;margin-top:12px;">
        <el-pagination v-if="total > size" v-model:current-page="page"
          :page-size="size" :total="total" background
          layout="prev,pager,next" size="small" :pager-count="7" @current-change="load" />
        <el-select v-model="size" @change="page = 1; load()" size="small" style="width:90px;" filterable>
          <el-option v-for="s in pageSizes" :key="s" :label="s+'条/页'" :value="s" />
        </el-select>
      </div>
    </div>

    <TtAccountModal v-model:visible="acModalVisible" :edit-account="acEditAccount" @saved="load" />
    <TtAccountDetailModal v-model:visible="detailVisible" :account="detailAccount" />
    <TtAccountDeletedModal v-model:visible="deletedVisible" @restored="load" />
    <TtAccountBatchImportModal v-model:visible="importVisible" @saved="load" />
    <TtAccountBatchLookupModal v-model:visible="lookupVisible" />
    <TtRechargeModal v-model:visible="rechargeVisible" :default-account-id="rechargeDefaultAccountId" @saved="load" />
    <TtRechargeBatchModal v-model:visible="rechargeBatchVisible" :accounts="selected" @saved="load" />
    <TtAccountSyncModal v-model:visible="syncVisible" @synced="load" />
    <TtRecycleReasonModal v-model:visible="recycleVisible" :mode="recycleTarget?.mode" :account="recycleTarget?.account" :accounts="recycleTarget?.accounts" :status-id="recycleTarget?.statusId" :status-name="recycleTarget?.statusName" @saved="onRecycleSaved" />
  </div>
</template>

<script setup>
import { ref, computed, onMounted, nextTick } from 'vue'
import { ttApi, ttAccountsApi } from '@/api/tt'
import client from '@/api/client'
import TtAccountModal from '@/components/tt/TtAccountModal.vue'
import TtAccountDetailModal from '@/components/tt/TtAccountDetailModal.vue'
import TtAccountDeletedModal from '@/components/tt/TtAccountDeletedModal.vue'
import TtAccountBatchImportModal from '@/components/tt/TtAccountBatchImportModal.vue'
import TtAccountBatchLookupModal from '@/components/tt/TtAccountBatchLookupModal.vue'
import TtRechargeModal from '@/components/tt/TtRechargeModal.vue'
import TtRechargeBatchModal from '@/components/tt/TtRechargeBatchModal.vue'
import TtAccountSyncModal from '@/components/tt/TtAccountSyncModal.vue'
import TtRecycleReasonModal from '@/components/tt/TtRecycleReasonModal.vue'
import OwnerFilterSelect from '@/components/OwnerFilterSelect.vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Delete } from '@element-plus/icons-vue'

const items = ref([])
const total = ref(0)
const page = ref(1)
const size = ref(50)
const pageSizes = [50, 100, 200]
const search = ref('')
const bcId = ref('')
const agentId = ref('')
const statusId = ref('')
const timezone = ref('')
const statusCounts = ref({})

const selected = ref([])
const bcOptions = ref([])
const agentOptions = ref([])
const statusOptions = ref([])
const timezoneOptions = ref(buildTimezoneOptions())
const ownerId = ref('')

const acModalVisible = ref(false)
const acEditAccount = ref(null)
const detailVisible = ref(false)
const detailAccount = ref(null)
const deletedVisible = ref(false)
const importVisible = ref(false)
const lookupVisible = ref(false)
const rechargeVisible = ref(false)
const rechargeDefaultAccountId = ref('')
const rechargeBatchVisible = ref(false)
const syncVisible = ref(false)
const recycleVisible = ref(false)
const recycleTarget = ref(null)

const batchStatus = ref('')
const batchBc = ref('')

// 内联编辑状态
const editingNameId = ref(null)
const editingBcId = ref(null)
const editingTimezoneId = ref(null)
const editingAgentId = ref(null)
const editingStatusId = ref(null)
const editingCountryId = ref(null)
const editingConsumptionId = ref(null)
const editNameValue = ref('')
const editBcValue = ref(null)
const editTimezoneValue = ref('')
const editAgentValue = ref(null)
const editStatusValue = ref(null)
const editCountryValue = ref('')
const editConsumptionValue = ref('')
let nameInputRef = null
let countryInputRef = null
let consumptionInputRef = null
let bcPending = false
let tzPending = false
let agentPending = false
let statusPending = false
let searchTimer = null

function buildTimezoneOptions() {
  const tzs = []
  for (let i = -12; i <= 12; i++) {
    const sign = i > 0 ? '+' : ''
    tzs.push(`${sign}${i}`)
  }
  tzs.push('+5:30', '+8:45', '-3:30')
  return tzs
}

onMounted(async () => {
  await loadOptions()
  await load()
})

async function loadOptions() {
  try {
    const [bcRes, agentRes, statusRes] = await Promise.all([
      ttApi.bcOptions(),
      client.get('/agents/list', { params: { platform: 'tt' } }),
      client.get('/statuses/list', { params: { platform: 'tt' } }),
    ])
    bcOptions.value = bcRes.data || []
    agentOptions.value = agentRes.agents || []
    statusOptions.value = statusRes.statuses || []
  } catch (e) {
    ElMessage.error('加载选项失败: ' + (e.response?.data?.error || e.message))
  }
}

async function load() {
  const params = { page: page.value, size: size.value }
  if (search.value) params.search = search.value
  if (bcId.value) params.bc_id = bcId.value
  if (agentId.value) params.agent_id = agentId.value
  if (statusId.value) params.status_id = statusId.value
  if (timezone.value) params.timezone = timezone.value
  if (ownerId.value) params.owner_id = ownerId.value
  try {
    const res = await ttAccountsApi.list(params)
    items.value = res.items || []
    total.value = res.total || 0
    statusCounts.value = res.status_counts || {}
  } catch (e) {
    ElMessage.error('加载失败: ' + (e.response?.data?.error || e.message))
  }
}

function filterAndLoad() { page.value = 1; load() }

const availableStatuses = computed(() => {
  const allNames = new Set([...Object.keys(statusCounts.value), ...statusOptions.value.map(s => s.name)])
  const orderMap = Object.fromEntries(statusOptions.value.map((s, i) => [s.name, i]))
  return [...allNames].filter(s => (statusCounts.value[s] || 0) > 0)
    .sort((a, b) => (orderMap[a] ?? 999) - (orderMap[b] ?? 999))
})

function isStatusActive(name) {
  const s = statusOptions.value.find(x => x.name === name)
  return s ? String(statusId.value) === String(s.id) : false
}

function toggleStatus(name) {
  const s = statusOptions.value.find(x => x.name === name)
  const id = s ? s.id : ''
  statusId.value = (String(statusId.value) === String(id)) ? '' : id
  page.value = 1
  load()
}
function clearStatus() { statusId.value = ''; page.value = 1; load() }

// BC 分组：相邻相同 BC 归一组，奇偶交替着色
const bcGroupIndex = computed(() => {
  const map = {}
  let key = null, idx = 0
  for (const r of items.value) {
    const k = r.bc_id ?? '__none__'
    if (k !== key) { idx++; key = k }
    map[r.id] = idx
  }
  return map
})
function bcRowClass({ row }) {
  const g = bcGroupIndex.value[row.id] || 0
  return g % 2 === 0 ? 'bc-row-even' : 'bc-row-odd'
}

function bcCode(row) {
  const b = bcOptions.value.find(x => x.id === row.bc_id)
  return b ? b.bc_id : ''
}

function statusTagType(status) {
  const map = { '存活': 'success', '验证': 'warning', '死亡': 'danger', '封禁': 'danger' }
  return map[status] || 'info'
}

function onSearch() {
  clearTimeout(searchTimer)
  searchTimer = setTimeout(() => { page.value = 1; load() }, 500)
}

function showModal(account) { acEditAccount.value = account || null; acModalVisible.value = true }
function showDetail(row) { detailAccount.value = row; detailVisible.value = true }
function openRecharge(row) { rechargeDefaultAccountId.value = row.advertiser_id || ''; rechargeVisible.value = true }
function onRecycleSaved() { load() }

function notImplemented(feature) {
  ElMessage.info((feature || '该功能') + '将在后续任务接入')
}

async function del(id) {
  try {
    await ElMessageBox.confirm('确定删除此账户？', '确认', { type: 'warning' })
  } catch { return }
  try {
    await ttAccountsApi.delete(id)
    ElMessage.success('已删除')
    load()
  } catch (e) {
    ElMessage.error(e.response?.data?.error || '删除失败')
  }
}

async function batchDelete() {
  if (!selected.value.length) return
  try {
    await ElMessageBox.confirm(`确定删除选中的 ${selected.value.length} 个账户？`, '确认', { type: 'warning' })
  } catch { return }
  try {
    await ttAccountsApi.batchDelete(selected.value.map(s => s.id))
    ElMessage.success('已删除')
    selected.value = []
    load()
  } catch (e) {
    ElMessage.error(e.response?.data?.error || '删除失败')
  }
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
    await ttAccountsApi.update(row.id, { name: v })
    row.name = v
    ElMessage.success('名称已更新')
  } catch (e) {
    ElMessage.error('更新名称失败')
  }
  cancelNameEdit()
}

// ===== BC 内联编辑 =====
function startEditBc(row) {
  editingBcId.value = row.id
  editBcValue.value = row.bc_id ?? null
  bcPending = false
}
function cancelBcEdit() {
  editingBcId.value = null
  editBcValue.value = null
  bcPending = false
}
async function saveBc(row) {
  const v = editBcValue.value ?? null
  if (v === (row.bc_id ?? null)) { cancelBcEdit(); return }
  bcPending = true
  try {
    await ttAccountsApi.update(row.id, { bc_id: v })
    const b = bcOptions.value.find(x => x.id === v)
    row.bc_name = b ? b.name : null
    row.bc = b ? b.name : null
    row.bc_id = v
    ElMessage.success('BC 已更新')
  } catch (e) {
    ElMessage.error('更新 BC 失败')
  }
  cancelBcEdit()
}
function onBcBlur() {
  setTimeout(() => {
    if (!bcPending && editingBcId.value !== null) cancelBcEdit()
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
    await ttAccountsApi.update(row.id, { timezone: v })
    row.timezone = v
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
    await ttAccountsApi.update(row.id, { agent_id: v })
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
  const found = statusOptions.value.find(s => s.name === row.status)
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
  const currentStatusId = statusOptions.value.find(s => s.name === row.status)?.id ?? null
  if (v === currentStatusId) { cancelStatusEdit(); return }
  const st = statusOptions.value.find(x => x.id === v)
  const stName = st ? st.name : ''
  cancelStatusEdit()
  if (stName !== '存活') {
    recycleTarget.value = { mode: 'single', account: row, accounts: [], statusId: v, statusName: stName }
    recycleVisible.value = true
    return
  }
  statusPending = true
  try {
    await ttAccountsApi.update(row.id, { status_id: v })
    row.status = stName
    row.status_name = stName
    row.status_changed_date = new Date().toISOString().slice(0, 10)
    ElMessage.success('状态已更新')
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

// ===== 国家内联编辑 =====
function startEditCountry(row) {
  editingCountryId.value = row.id
  editCountryValue.value = row.country || ''
  nextTick(() => { countryInputRef?.focus?.() })
}
function cancelCountryEdit() {
  editingCountryId.value = null
  editCountryValue.value = ''
  countryInputRef = null
}
async function saveCountry(row) {
  const v = editCountryValue.value.trim()
  if (v === (row.country || '')) { cancelCountryEdit(); return }
  try {
    await ttAccountsApi.update(row.id, { country: v })
    row.country = v
    ElMessage.success('国家已更新')
  } catch (e) {
    ElMessage.error('更新国家失败')
  }
  cancelCountryEdit()
}

// ===== 消耗情况内联编辑 =====
function startEditConsumption(row) {
  editingConsumptionId.value = row.id
  editConsumptionValue.value = row.consumption || ''
  nextTick(() => { consumptionInputRef?.focus?.() })
}
function cancelConsumptionEdit() {
  editingConsumptionId.value = null
  editConsumptionValue.value = ''
  consumptionInputRef = null
}
async function saveConsumption(row) {
  const v = editConsumptionValue.value.trim()
  if (v === (row.consumption || '')) { cancelConsumptionEdit(); return }
  try {
    await ttAccountsApi.update(row.id, { consumption: v })
    row.consumption = v
    ElMessage.success('消耗情况已更新')
  } catch (e) {
    ElMessage.error('更新消耗情况失败')
  }
  cancelConsumptionEdit()
}

// ===== 批量修改 =====
async function doBatchStatus(val) {
  if (!val) return
  const st = statusOptions.value.find(s => s.id === val)
  const stName = st ? st.name : val
  try {
    await ElMessageBox.confirm(
      `确定将选中的 ${selected.value.length} 个账户状态改为「${stName}」？`,
      '批量修改状态', { type: 'warning', confirmButtonText: '确定', cancelButtonText: '取消' }
    )
  } catch { batchStatus.value = ''; return }
  if (stName !== '存活') {
    recycleTarget.value = { mode: 'batch', account: null, accounts: [...selected.value], statusId: val, statusName: stName }
    recycleVisible.value = true
    batchStatus.value = ''
    return
  }
  try {
    await ttAccountsApi.batchUpdate({ ids: selected.value.map(s => s.id), field: 'status_id', value: val })
    ElMessage.success(`已将 ${selected.value.length} 个账户状态改为「${stName}」`)
    batchStatus.value = ''
    load()
  } catch (e) {
    ElMessage.error(e.response?.data?.error || '批量修改失败')
    batchStatus.value = ''
  }
}
async function doBatchBc(val) {
  if (!val) return
  try {
    await ttAccountsApi.batchUpdate({ ids: selected.value.map(s => s.id), field: 'bc_id', value: val })
    ElMessage.success('BC 已批量更新')
    batchBc.value = ''
    load()
  } catch (e) {
    ElMessage.error(e.response?.data?.error || '批量修改失败')
    batchBc.value = ''
  }
}
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
:deep(.bc-row-even) td {
  background-color: #f2f4f7 !important;
}
:deep(.bc-row-odd) td {
  background-color: #e2e6ed !important;
}
/* 覆盖默认 hover 浅色，改为微暗叠加，保持 BC 分组色可辨 */
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
.bc-text-block {
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
.inline-bc-select,
.inline-tz-select,
.inline-agent-select,
.inline-status-select {
  width: 100%;
}
</style>
