<template>
  <div style="display:flex;flex-direction:column;height:100%;">
    <!-- 工具栏 — 固定 -->
    <div style="flex-shrink:0;">
      <div style="display:flex;gap:8px;margin-bottom:8px;align-items:center;">
        <el-button type="primary" @click="showModal()">➕ 新增账户</el-button>
        <span style="color:#888;font-size:12px;">已选 {{ selected.length }} 条</span>
        <el-select v-model="batchStatus" @change="doBatchStatus" placeholder="批量修改状态..."
          style="width:160px;" :disabled="!selected.length" clearable filterable>
          <el-option v-for="s in store.settings.account_statuses" :key="s" :label="s" :value="s" />
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
          <el-option v-for="a in agentOptions" :key="a" :label="a" :value="a" />
        </el-select>
        <el-select v-model="acSort" @change="changeSort" style="width:120px;" filterable>
          <el-option label="MCC+时区" value="mcc_tz" />
          <el-option label="时区优先" value="tz" />
          <el-option label="名称排序" value="name" />
          <el-option label="代理排序" value="agent" />
        </el-select>
      </div>
    </div>

    <!-- 表格 + 分页 — 滚动区 -->
    <div style="flex:1;min-height:0;overflow-y:auto;">
      <el-table :data="store.accounts" @selection-change="val => selected = val" :row-class-name="mccRowClass">
        <el-table-column type="selection" width="45" />
        <el-table-column prop="name" label="账号名称" min-width="100" />
        <el-table-column prop="account_id" label="账号 ID" min-width="130" show-overflow-tooltip />
        <el-table-column label="所属 MCC" min-width="100">
          <template #default="{ row }">
            <template v-if="row.mcc_name">
              <span style="color:#0891b2;">{{ row.mcc_name }}</span>
              <span style="font-size:10px;color:#0891b2;"> · {{ row.mcc_code }}</span>
            </template>
            <span v-else style="color:#888;">未分配</span>
          </template>
        </el-table-column>
        <el-table-column prop="timezone" label="时区" min-width="60" />
        <el-table-column prop="agent" label="代理" min-width="70" />
        <el-table-column label="状态" width="105">
          <template #default="{ row }">
            <div style="display:flex;align-items:center;gap:4px;flex-wrap:nowrap;">
              <el-tag size="small" :type="row.status === '存活' ? 'success' : row.status === '验证' ? 'warning' : row.status === '死亡' ? 'danger' : 'info'">{{ row.status || '未知' }}</el-tag>
              <span v-if="row.status === '死亡' && row.death_date" style="font-size:10px;color:#dc2626;white-space:nowrap;">{{ row.death_date }}</span>
            </div>
          </template>
        </el-table-column>
        <el-table-column prop="acquired_date" label="到手时间" width="110" show-overflow-tooltip />
        <el-table-column v-if="store.acFilters.status === '死亡'" label="死亡时间" width="110" show-overflow-tooltip>
          <template #default="{ row }"><span v-if="row.death_date" style="color:#dc2626;">{{ row.death_date }}</span><span v-else style="color:#ccc;">—</span></template>
        </el-table-column>
        <el-table-column label="操作" width="120">
          <template #default="{ row }">
            <el-button link type="primary" size="small" @click="showModal(row.id)">✏️</el-button>
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
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { useAccountStore } from '@/stores/accounts'
import AccountModal from '@/components/AccountModal.vue'
import { ElMessageBox } from 'element-plus'
import { Delete } from '@element-plus/icons-vue'

const store = useAccountStore()
const selected = ref([])
const acModalVisible = ref(false)
const acEditId = ref(null)
const batchStatus = ref('')
const batchMcc = ref('')
const mccOptions = ref([])
const agentOptions = ref([])
const statusCounts = ref({})
const acSort = ref('mcc_tz')
let searchTimer = null

onMounted(async () => {
  await store.loadSettings()
  if (!store.acFilters.status) store.acFilters.status = '存活'
  await load()
})

async function load() {
  store.acFilters.sort = acSort.value
  const res = await store.loadAccounts()
  mccOptions.value = res.mcc_options || []
  agentOptions.value = [...new Set([...store.settings.account_agents, ...(res.agents||[])])].filter(Boolean).sort()
  if (res.status_counts) statusCounts.value = res.status_counts
}

function changeSort() { store.acPage = 1; load() }

const availableStatuses = computed(() => {
  const configStatuses = store.settings.account_statuses || []
  const all = new Set([...Object.keys(statusCounts.value), ...configStatuses])
  // 只显示实际有账户的状态（count > 0），按 settings 配置顺序排列
  const orderMap = Object.fromEntries(configStatuses.map((s, i) => [s, i]))
  return [...all].filter(s => (statusCounts.value[s] || 0) > 0)
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
  searchTimer = setTimeout(() => { store.acPage = 1; load() }, 300)
}
function searchAndLoad() { store.acPage = 1; load() }
function showModal(id) { acEditId.value = id || null; acModalVisible.value = true }

async function del(id) {
  await ElMessageBox.confirm('确定删除此账户？', '确认', { type: 'warning' })
  await store.deleteAccount(id)
}

async function batchDelete() {
  if (!selected.value.length) return
  await ElMessageBox.confirm(`确定删除选中的 ${selected.value.length} 个账户？`, '确认', { type: 'warning' })
  await store.batchDeleteAccounts(selected.value.map(s => s.id))
}

async function doBatchStatus(val) {
  if (!val) return
  await store.batchUpdateAccounts({ ids: selected.value.map(s => s.id), field: 'status', value: val })
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
</style>
