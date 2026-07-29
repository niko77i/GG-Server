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
      </div>
    </div>

    <!-- 表格 + 分页 — 滚动区 -->
    <div style="flex:1;min-height:0;overflow-y:auto;">
      <el-table :data="store.accounts" @selection-change="val => selected = val" :row-class-name="mccRowClass">
        <el-table-column type="selection" width="45" />
        <el-table-column label="账号名称" min-width="120">
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
        <el-table-column prop="account_id" label="账号 ID" min-width="130" show-overflow-tooltip />
        <el-table-column label="所属 MCC" min-width="130">
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
              <template v-if="row.mcc_name">
                <span style="color:#0891b2;">{{ row.mcc_name }}</span>
                <span style="font-size:10px;color:#0891b2;"> · {{ row.mcc_code }}</span>
              </template>
              <span v-else style="color:#888;">未分配</span>
              <el-button link size="small" class="inline-edit-btn" @click.stop="startEditMcc(row)">✏️</el-button>
            </div>
          </template>
        </el-table-column>
        <el-table-column prop="timezone" label="时区" min-width="60" />
        <el-table-column prop="agent" label="代理" min-width="70" />
        <el-table-column label="状态" width="105">
          <template #default="{ row }">
            <div style="display:flex;align-items:center;gap:4px;flex-wrap:nowrap;">
              <el-tag size="small" :type="row.status === '存活' ? 'success' : row.status === '验证' ? 'warning' : row.status === '死亡' ? 'danger' : 'info'">{{ row.status || '未知' }}</el-tag>
            </div>
          </template>
        </el-table-column>
        <el-table-column prop="acquired_date" label="到手时间" width="110" show-overflow-tooltip />
        <el-table-column label="状态变更时间" width="120" show-overflow-tooltip>
          <template #default="{ row }">
            <span v-if="row.status_changed_date" style="font-size:12px;">{{ row.status_changed_date }}</span>
            <span v-else style="color:#ccc;">—</span>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="200">
          <template #default="{ row }">
            <el-button link type="primary" size="small" @click="showModal(row.id)">✏️</el-button>
            <el-button link type="success" size="small" @click="showDetail(row.id)">📋</el-button>
            <el-button link type="warning" size="small" @click="openRecharge(row)">💰</el-button>
            <el-button link type="danger" size="small" @click="del(row.id)"><el-icon :size="14"><Delete /></el-icon></el-button>
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
    <RechargeModal v-model:visible="rechargeVisible" :default-account-id="rechargeAccountId" @saved="load" />
    <RechargeBatchModal v-model:visible="batchRechargeVisible" :accounts="selected" @saved="onBatchRecharged" />
    <AccountSyncModal v-model:visible="syncVisible" @synced="load" />
    <AccountDeletedModal v-model:visible="deletedVisible" @restored="load" />
  </div>
</template>

<script setup>
import { ref, computed, onMounted, nextTick } from 'vue'
import { useAccountStore } from '@/stores/accounts'
import AccountModal from '@/components/AccountModal.vue'
import AccountBatchImportModal from '@/components/AccountBatchImportModal.vue'
import AccountBatchLookupModal from '@/components/AccountBatchLookupModal.vue'
import AccountDetailModal from '@/components/AccountDetailModal.vue'
import RechargeModal from '@/components/RechargeModal.vue'
import RechargeBatchModal from '@/components/RechargeBatchModal.vue'
import AccountSyncModal from '@/components/AccountSyncModal.vue'
import AccountDeletedModal from '@/components/AccountDeletedModal.vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Delete } from '@element-plus/icons-vue'

const store = useAccountStore()
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
// 内联编辑状态
const editingNameId = ref(null)
const editingMccId = ref(null)
const editNameValue = ref('')
const editMccValue = ref(null)
let nameInputRef = null
let mccPending = false
let searchTimer = null

onMounted(() => {
  store.loadSettings()
  store.loadAgents()
  store.loadStatuses()
  if (!store.acFilters.status) store.acFilters.status = '存活'
  load()
})

async function load() {
  const res = await store.loadAccounts()
  mccOptions.value = res.mcc_options || []
  agentOptions.value = store.options.agents.map(a => ({ id: a.id, name: a.name }))
  timezoneOptions.value = res.timezone_options || []
  if (res.status_counts) statusCounts.value = res.status_counts
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

function onBatchRecharged() {
  selected.value = []
  load()
}

async function del(id) {
  await ElMessageBox.confirm('确定删除此账户？', '确认', { type: 'warning' })
  await store.deleteAccount(id)
}

async function batchDelete() {
  if (!selected.value.length) return
  await ElMessageBox.confirm(`确定删除选中的 ${selected.value.length} 个账户？`, '确认', { type: 'warning' })
  await store.batchDeleteAccounts(selected.value.map(s => s.id))
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
  await store.batchUpdateAccounts({ ids: selected.value.map(s => s.id), field: 'status_id', value: val })
  ElMessage.success(`已将 ${selected.value.length} 个账户状态改为「${stName}」`)
  batchStatus.value = ''
}
async function doBatchMcc(val) {
  if (!val) return
  await store.batchUpdateAccounts({ ids: selected.value.map(s => s.id), field: 'mcc_id', value: val })
  batchMcc.value = ''
}
</script>

<style scoped>
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
.inline-name-input,
.inline-mcc-select {
  width: 100%;
}
</style>
