<template>
  <el-dialog :model-value="visible" @update:model-value="$emit('update:visible', $event)"
    title="📥 批量导入账户" width="880px" @open="init">
    <el-form label-position="top">
      <el-form-item label="账户 ID 列表" required>
        <el-input v-model="idText" type="textarea" :rows="4"
          placeholder="每行一个账户 ID，自动识别提取&#10;支持格式：123-456-7890 / 1234567890 / 含额外文字的行&#10;例如：&#10;123-456-7890 账户A&#10;2345678901&#10;345-678-9012 | 代理X | UTC+8"
          @input="onIdTextChange" />
      </el-form-item>

      <!-- 解析统计 -->
      <div v-if="parsedIds.length" style="margin-bottom:8px;font-size:13px;color:#666;">
        共识别 <strong>{{ parsedIds.length }}</strong> 个：
        <span v-if="existingAccounts.length" style="color:#e6a23c;margin-left:4px;">⚠ {{ existingAccounts.length }} 个他人账户</span>
        <span v-if="alreadyMine.length" style="color:#909399;margin-left:4px;">🔒 {{ alreadyMine.length }} 个已属于你</span>
        <span v-if="newIds.length" style="color:#16a34a;margin-left:4px;">✓ {{ newIds.length }} 个新账户</span>
        <span v-if="invalidIds.length" style="color:#dc2626;margin-left:4px;">✕ {{ invalidIds.length }} 个格式不符</span>
        <span v-if="lookingUp" style="color:#909399;margin-left:8px;">查询中...</span>
      </div>

      <!-- 已属于当前用户的账户 — 仅提示 -->
      <el-alert v-if="alreadyMine.length" type="info" :closable="false" show-icon style="margin-bottom:8px;">
        <template #title>
          以下 {{ alreadyMine.length }} 个账户已属于你，无需认领：{{ alreadyMine.map(a => a.account_id).join('、') }}
        </template>
      </el-alert>

      <!-- ===== 他人的账户 ===== -->
      <template v-if="existingAccounts.length">
        <el-divider content-position="left" style="margin:8px 0;">
          ⚠ 他人账户（{{ existingAccounts.length }} 个）— 可编辑后勾选认领
        </el-divider>
        <el-table :data="existingAccounts" size="small" border stripe max-height="260"
          @selection-change="v => claimSelection = v" :row-class-name="existingRowClass" style="width:100%;">
          <el-table-column type="selection" width="34" />
          <el-table-column prop="account_id" label="账户 ID" width="118" />
          <el-table-column label="名称" min-width="70" show-overflow-tooltip>
            <template #default="{ row }">
              <span style="font-size:12px;">{{ getClaimEdit(row, 'name') }}</span>
              <span v-if="getClaimEdit(row, 'name') !== row.name" style="color:#e6a23c;font-size:10px;">*</span>
            </template>
          </el-table-column>
          <el-table-column label="时区" width="70" align="center">
            <template #default="{ row }">{{ getClaimEdit(row, 'timezone') || '-' }}</template>
          </el-table-column>
          <el-table-column label="代理" width="55" align="center" show-overflow-tooltip>
            <template #default="{ row }">{{ agentNameById(getClaimEdit(row, 'agent')) }}</template>
          </el-table-column>
          <el-table-column label="状态" width="55" align="center">
            <template #default="{ row }">
              <el-tag size="small" :type="statusNameById(getClaimEdit(row, 'status')) === '死亡' ? 'danger' : statusNameById(getClaimEdit(row, 'status')) === '存活' ? 'success' : 'info'">
                {{ statusNameById(getClaimEdit(row, 'status')) }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column label="MCC" min-width="75" show-overflow-tooltip>
            <template #default="{ row }">{{ mccNameById(getClaimEdit(row, 'mcc_id')) || row.mcc_name || '-' }}</template>
          </el-table-column>
          <el-table-column label="归属" min-width="65" show-overflow-tooltip>
            <template #default="{ row }">
              <el-tag size="small" type="warning">{{ row.owner_name }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column label="编辑" width="48" align="center">
            <template #default="{ row }">
              <el-button link size="small" :type="editingId === row.account_id ? 'primary' : ''"
                @click="toggleEdit(row)" style="padding:0;">✏️</el-button>
            </template>
          </el-table-column>
        </el-table>

        <!-- 编辑面板 — 展开在表格下方 -->
        <div v-if="editingId" style="background:#f5f7fa;border:1px solid #e5e7eb;border-radius:8px;padding:12px;margin-top:8px;">
          <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:8px;">
            <span style="font-weight:600;font-size:13px;">✏️ 编辑 {{ editingId }}</span>
            <el-button link size="small" @click="editingId = null">关闭 ✕</el-button>
          </div>
          <el-row :gutter="10">
            <el-col :span="8">
              <el-form-item label="名称" style="margin-bottom:8px;">
                <el-input v-model="claimEdits[editingId].name" size="small" />
              </el-form-item>
            </el-col>
            <el-col :span="8">
              <el-form-item label="时区" style="margin-bottom:8px;">
                <el-select v-model="claimEdits[editingId].timezone" size="small" filterable style="width:100%;">
                  <el-option v-for="tz in timezoneOptions" :key="tz" :label="tz" :value="tz" />
                </el-select>
              </el-form-item>
            </el-col>
            <el-col :span="8">
              <el-form-item label="代理" style="margin-bottom:8px;">
                <el-select v-model="claimEdits[editingId].agent" size="small" filterable style="width:100%;">
                  <el-option v-for="a in store.options.agents" :key="a.id" :label="a.name" :value="a.id" />
                </el-select>
              </el-form-item>
            </el-col>
          </el-row>
          <el-row :gutter="10">
            <el-col :span="8">
              <el-form-item label="状态" style="margin-bottom:0;">
                <el-select v-model="claimEdits[editingId].status" size="small" filterable style="width:100%;">
                  <el-option v-for="s in store.options.statuses" :key="s.id" :label="s.name" :value="s.id" />
                </el-select>
              </el-form-item>
            </el-col>
            <el-col :span="8">
              <el-form-item label="MCC" style="margin-bottom:0;">
                <el-select v-model="claimEdits[editingId].mcc_id" size="small" clearable filterable style="width:100%;">
                  <el-option v-for="m in mccOptions" :key="m.id" :label="m.name + ' (' + m.mcc_id + ')'" :value="m.id" />
                </el-select>
              </el-form-item>
            </el-col>
            <el-col :span="8">
              <el-form-item label="到手时间" style="margin-bottom:0;">
                <el-date-picker v-model="claimEdits[editingId].acquired_date" type="date" size="small"
                  style="width:100%;" value-format="YYYY-MM-DD" />
              </el-form-item>
            </el-col>
          </el-row>
        </div>
      </template>

      <!-- ===== 新账户列表 + 共用默认值 ===== -->
      <template v-if="newIds.length">
        <el-divider content-position="left" style="margin:8px 0;">新账户（{{ newIds.length }} 个）</el-divider>
        <el-table :data="newAccountRows" size="small" border stripe max-height="260"
          :row-class-name="newRowClass" style="width:100%;">
          <el-table-column prop="account_id" label="账户 ID" width="118" />
          <el-table-column label="名称" min-width="80" show-overflow-tooltip>
            <template #default="{ row }">
              <span style="font-size:12px;">{{ getNewEdit(row.account_id, 'name') }}</span>
              <span v-if="isNewDirty(row.account_id)" style="color:#e6a23c;font-size:10px;">*</span>
            </template>
          </el-table-column>
          <el-table-column label="时区" width="75" align="center">
            <template #default="{ row }">{{ getNewEdit(row.account_id, 'timezone') || '-' }}</template>
          </el-table-column>
          <el-table-column label="代理" width="60" align="center" show-overflow-tooltip>
            <template #default="{ row }">{{ agentNameById(getNewEdit(row.account_id, 'agent')) }}</template>
          </el-table-column>
          <el-table-column label="状态" width="55" align="center">
            <template #default="{ row }">
              <el-tag size="small" :type="statusNameById(getNewEdit(row.account_id, 'status')) === '死亡' ? 'danger' : statusNameById(getNewEdit(row.account_id, 'status')) === '存活' ? 'success' : 'info'">
                {{ statusNameById(getNewEdit(row.account_id, 'status')) }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column label="MCC" min-width="75" show-overflow-tooltip>
            <template #default="{ row }">{{ mccNameById(getNewEdit(row.account_id, 'mcc_id')) || '-' }}</template>
          </el-table-column>
          <el-table-column label="编辑" width="48" align="center">
            <template #default="{ row }">
              <el-button link size="small" :type="newEditingId === row.account_id ? 'primary' : ''"
                @click="toggleNewEdit(row.account_id)" style="padding:0;">✏️</el-button>
            </template>
          </el-table-column>
        </el-table>

        <!-- 新账户编辑面板 -->
        <div v-if="newEditingId" style="background:#f0fdf4;border:1px solid #bbf7d0;border-radius:8px;padding:12px;margin-top:8px;">
          <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:8px;">
            <span style="font-weight:600;font-size:13px;">✏️ 编辑 {{ newEditingId }}</span>
            <div>
              <el-button link size="small" type="warning" @click="resetNewEdit(newEditingId)" style="margin-right:12px;">恢复默认</el-button>
              <el-button link size="small" @click="newEditingId = null">关闭 ✕</el-button>
            </div>
          </div>
          <el-row :gutter="10">
            <el-col :span="8">
              <el-form-item label="名称" style="margin-bottom:8px;">
                <el-input v-model="newAccountEdits[newEditingId].name" size="small" />
              </el-form-item>
            </el-col>
            <el-col :span="8">
              <el-form-item label="时区" style="margin-bottom:8px;">
                <el-select v-model="newAccountEdits[newEditingId].timezone" size="small" filterable style="width:100%;">
                  <el-option v-for="tz in timezoneOptions" :key="tz" :label="tz" :value="tz" />
                </el-select>
              </el-form-item>
            </el-col>
            <el-col :span="8">
              <el-form-item label="代理" style="margin-bottom:8px;">
                <el-select v-model="newAccountEdits[newEditingId].agent" size="small" filterable style="width:100%;">
                  <el-option v-for="a in store.options.agents" :key="a.id" :label="a.name" :value="a.id" />
                </el-select>
              </el-form-item>
            </el-col>
          </el-row>
          <el-row :gutter="10">
            <el-col :span="8">
              <el-form-item label="状态" style="margin-bottom:0;">
                <el-select v-model="newAccountEdits[newEditingId].status" size="small" filterable style="width:100%;">
                  <el-option v-for="s in store.options.statuses" :key="s.id" :label="s.name" :value="s.id" />
                </el-select>
              </el-form-item>
            </el-col>
            <el-col :span="8">
              <el-form-item label="MCC" style="margin-bottom:0;">
                <el-select v-model="newAccountEdits[newEditingId].mcc_id" size="small" clearable filterable style="width:100%;">
                  <el-option v-for="m in mccOptions" :key="m.id" :label="m.name + ' (' + m.mcc_id + ')'" :value="m.id" />
                </el-select>
              </el-form-item>
            </el-col>
            <el-col :span="8">
              <el-form-item label="到手时间" style="margin-bottom:0;">
                <el-date-picker v-model="newAccountEdits[newEditingId].acquired_date" type="date" size="small"
                  style="width:100%;" value-format="YYYY-MM-DD" />
              </el-form-item>
            </el-col>
          </el-row>
        </div>

        <!-- 共用默认值（折叠） -->
        <el-collapse style="margin-top:8px;">
          <el-collapse-item>
            <template #title>
              <span style="font-size:13px;color:#606266;">⚙ 共用默认值（修改后自动应用到未单独编辑的行）</span>
            </template>
            <el-row :gutter="12">
              <el-col :span="12">
                <el-form-item label="名称前缀（可选）" style="margin-bottom:8px;">
                  <el-input v-model="defaultForm.name_prefix" size="small" placeholder="留空则用 ID 作名称" />
                </el-form-item>
              </el-col>
              <el-col :span="12">
                <el-form-item label="所属 MCC" style="margin-bottom:8px;">
                  <el-select v-model="defaultForm.mcc_id" size="small" clearable filterable placeholder="（未分配）" style="width:100%;">
                    <el-option v-for="m in mccOptions" :key="m.id" :label="m.name + ' (' + m.mcc_id + ')'" :value="m.id" />
                  </el-select>
                </el-form-item>
              </el-col>
            </el-row>
            <el-row :gutter="12">
              <el-col :span="8">
                <el-form-item label="时区" style="margin-bottom:8px;">
                  <el-select v-model="defaultForm.timezone" size="small" filterable clearable placeholder="选择时区" style="width:100%;">
                    <el-option v-for="tz in timezoneOptions" :key="tz" :label="tz" :value="tz" />
                  </el-select>
                </el-form-item>
              </el-col>
              <el-col :span="8">
                <el-form-item label="代理" required style="margin-bottom:8px;">
                  <el-select v-model="defaultForm.agent" size="small" filterable placeholder="选择代理" style="width:100%;">
                    <el-option v-for="a in store.options.agents" :key="a.id" :label="a.name" :value="a.id" />
                  </el-select>
                </el-form-item>
              </el-col>
              <el-col :span="8">
                <el-form-item label="状态" style="margin-bottom:8px;">
                  <el-select v-model="defaultForm.status" size="small" style="width:100%;" filterable>
                    <el-option v-for="s in store.options.statuses" :key="s.id" :label="s.name" :value="s.id" />
                  </el-select>
                </el-form-item>
              </el-col>
            </el-row>
            <el-form-item label="到手时间" style="margin-bottom:0;">
              <el-date-picker v-model="defaultForm.acquired_date" type="date" size="small" style="width:200px;" value-format="YYYY-MM-DD" />
            </el-form-item>
          </el-collapse-item>
        </el-collapse>
      </template>
    </el-form>

    <!-- 导入结果 -->
    <div v-if="result" style="margin-top:10px;">
      <el-alert :type="result.claimFailed?.length ? 'warning' : 'success'" :closable="false" show-icon>
        <template #title>
          导入完成：新建 {{ result.created }} 个，认领 {{ result.claimed }} 个
          <span v-if="result.skipped?.length">，跳过 {{ result.skipped.length }} 个</span>
          <span v-if="result.claimFailed?.length">，认领失败 {{ result.claimFailed.length }} 个</span>
        </template>
      </el-alert>
      <div v-if="result.skipped?.length" style="margin-top:4px;max-height:80px;overflow-y:auto;">
        <div v-for="s in result.skipped" :key="s.account_id" style="font-size:12px;color:#e6a23c;">· {{ s.account_id }} — {{ s.reason }}</div>
      </div>
      <div v-if="result.claimFailed?.length" style="margin-top:4px;max-height:80px;overflow-y:auto;">
        <div v-for="f in result.claimFailed" :key="f.account_id" style="font-size:12px;color:#dc2626;">· {{ f.account_id }} — {{ f.reason }}</div>
      </div>
    </div>

    <template #footer>
      <el-button @click="$emit('update:visible', false)">取消</el-button>
      <el-button type="primary" @click="submit" :loading="saving"
        :disabled="!newIds.length && !claimSelection.length">
        📥 导入{{ newIds.length ? ' ' + newIds.length + ' 个' : '' }}{{ claimSelection.length ? ' + 认领 ' + claimSelection.length + ' 个' : '' }}
      </el-button>
    </template>
  </el-dialog>
</template>

<script setup>
import { ref, reactive, computed, watch } from 'vue'
import { useAccountStore } from '@/stores/accounts'
import { useAuthStore } from '@/stores/auth'
import { mccApi, accountsApi } from '@/api/accounts'
import { ElMessage } from 'element-plus'

const props = defineProps({ visible: Boolean })
const emit = defineEmits(['update:visible', 'saved'])
const store = useAccountStore()
const auth = useAuthStore()
const saving = ref(false)
const lookingUp = ref(false)
const mccOptions = ref([])
const idText = ref('')
const allFound = ref([])           // 查询到的全部已有账户
const claimSelection = ref([])
const claimEdits = reactive({})  // { [account_id]: { name, timezone, agent, status, mcc_id, acquired_date } }
const editingId = ref(null)     // 当前正在编辑的 account_id
const result = ref(null)

// 他人的账户（可认领）
const existingAccounts = computed(() =>
  allFound.value.filter(a => a.owner_id !== auth.user?.id)
)
// 已属于当前用户的
const alreadyMine = computed(() =>
  allFound.value.filter(a => a.owner_id === auth.user?.id)
)

const ID_PATTERN = /^\d{3}-\d{3}-\d{4}$/

// ===== ID 提取 =====
function extractAccountId(line) {
  const s = line.trim()
  if (!s) return null
  if (ID_PATTERN.test(s)) return s
  const m = s.match(/\d{3}-\d{3}-\d{4}/)
  if (m) return m[0]
  const digits = s.replace(/\D/g, '')
  if (digits.length === 10) {
    return `${digits.slice(0, 3)}-${digits.slice(3, 6)}-${digits.slice(6, 10)}`
  }
  const m10 = s.match(/\d{10}/)
  if (m10) {
    const d = m10[0]
    return `${d.slice(0, 3)}-${d.slice(3, 6)}-${d.slice(6, 10)}`
  }
  return null
}

function buildTimezoneOptions() {
  const tzs = []
  for (let i = -12; i <= 12; i++) {
    const sign = i > 0 ? '+' : ''
    tzs.push(`UTC${sign}${i}`)
  }
  tzs.push('UTC+5:30', 'UTC+8:45', 'UTC-3:30')
  return tzs
}
const timezoneOptions = buildTimezoneOptions()

// ===== 解析 =====
const parsedLines = computed(() => {
  if (!idText.value.trim()) return []
  const seen = new Set()
  const result = []
  for (const raw of idText.value.split(/[\n]+/)) {
    const line = raw.trim()
    if (!line) continue
    const id = extractAccountId(line)
    if (id && !seen.has(id)) { seen.add(id); result.push({ id, raw: line }) }
  }
  return result
})

const parsedIds = computed(() => parsedLines.value.map(p => p.id))

const invalidIds = computed(() => {
  if (!idText.value.trim()) return []
  return idText.value.split(/[\n]+/).map(s => s.trim()).filter(s => s && !extractAccountId(s))
})

const newIds = computed(() => {
  const existSet = new Set(allFound.value.map(e => e.account_id))
  return parsedIds.value.filter(id => !existSet.has(id))
})

const form = reactive({
  name_prefix: '',
  mcc_id: '',
  timezone: '',
  agent: null,
  status: null,
  acquired_date: '',
})
const defaultForm = form  // 共用默认值（保持原名兼容）

// ===== 新账户逐行编辑 =====
const newAccountEdits = reactive({})   // { [account_id]: { name, timezone, agent, status, mcc_id, acquired_date } }
const newAccountBaselines = reactive({}) // 每行上次同步时的默认值快照，用于判断用户是否手动修改
const newEditingId = ref(null)         // 当前正在编辑的新账户 account_id

// 新账户表格行数据
const newAccountRows = computed(() =>
  newIds.value.map(id => ({ account_id: id }))
)

function defaultName(aid) {
  return defaultForm.name_prefix ? (defaultForm.name_prefix + ' ' + aid).trim() : aid
}

function getDefaultValues(aid) {
  return {
    name: defaultName(aid),
    timezone: defaultForm.timezone,
    agent: defaultForm.agent,
    status: defaultForm.status,
    mcc_id: defaultForm.mcc_id || '',
    acquired_date: defaultForm.acquired_date,
  }
}

function initNewAccountEdit(aid) {
  if (!newAccountEdits[aid]) {
    const defaults = getDefaultValues(aid)
    newAccountEdits[aid] = { ...defaults }
    newAccountBaselines[aid] = { ...defaults }
  }
}

function getNewEdit(aid, field) {
  initNewAccountEdit(aid)
  return newAccountEdits[aid][field]
}

// 比较当前值与基线快照，判断是否被用户手动修改过（基线记录的是上次同步默认值时的快照）
function isNewDirty(aid) {
  const cur = newAccountEdits[aid]
  const baseline = newAccountBaselines[aid]
  if (!cur || !baseline) return false
  return cur.name !== baseline.name
    || cur.timezone !== baseline.timezone
    || cur.agent !== baseline.agent
    || cur.status !== baseline.status
    || cur.mcc_id !== baseline.mcc_id
    || cur.acquired_date !== baseline.acquired_date
}

function toggleNewEdit(aid) {
  initNewAccountEdit(aid)
  newEditingId.value = newEditingId.value === aid ? null : aid
}

function resetNewEdit(aid) {
  const defaults = getDefaultValues(aid)
  newAccountEdits[aid] = { ...defaults }
  newAccountBaselines[aid] = { ...defaults }
}

function newRowClass({ row }) {
  return newEditingId.value === row.account_id ? 'editing-row' : ''
}

// 将共用默认值同步到所有未单独编辑的行
function syncDefaultsToNewAccounts() {
  for (const aid of newIds.value) {
    if (isNewDirty(aid)) continue
    if (!newAccountEdits[aid]) {
      newAccountEdits[aid] = {}
    }
    const newDefaults = getDefaultValues(aid)
    Object.assign(newAccountEdits[aid], newDefaults)
    // 同步更新基线快照，确保后续 isNewDirty 能正确判断
    if (!newAccountBaselines[aid]) {
      newAccountBaselines[aid] = {}
    }
    Object.assign(newAccountBaselines[aid], newDefaults)
  }
}

// 监听共用默认值变化 → 同步到非 dirty 行
watch(() => ({ ...defaultForm }), () => {
  syncDefaultsToNewAccounts()
})

// 监听新账户 ID 列表变化 → 初始化编辑数据
watch(newIds, (ids) => {
  // 清理已不存在的 ID
  const idSet = new Set(ids)
  for (const key of Object.keys(newAccountEdits)) {
    if (!idSet.has(key)) delete newAccountEdits[key]
  }
  for (const key of Object.keys(newAccountBaselines)) {
    if (!idSet.has(key)) delete newAccountBaselines[key]
  }
  // 初始化新 ID
  for (const aid of ids) {
    initNewAccountEdit(aid)
  }
  newEditingId.value = null
})

// ===== 已有账户编辑 =====
function initClaimEdits(row) {
  if (!claimEdits[row.account_id]) {
    const matchedAgent = store.options.agents.find(a => a.name === row.agent)
    const matchedStatus = store.options.statuses.find(s => s.name === row.status)
    claimEdits[row.account_id] = {
      name: row.name,
      timezone: row.timezone || '',
      agent: matchedAgent ? matchedAgent.id : null,
      status: matchedStatus ? matchedStatus.id : null,
      mcc_id: row.mcc_id || '',
      acquired_date: row.acquired_date || '',
    }
  }
}

function getClaimEdit(row, field) {
  initClaimEdits(row)
  return claimEdits[row.account_id][field]
}

function toggleEdit(row) {
  initClaimEdits(row)
  editingId.value = editingId.value === row.account_id ? null : row.account_id
}

function mccNameById(mccId) {
  if (!mccId) return null
  const m = mccOptions.value.find(o => o.id === mccId)
  return m ? m.name + ' (' + m.mcc_id + ')' : null
}

function agentNameById(id) {
  if (!id) return '-'
  const a = store.options.agents.find(a => a.id === id)
  return a ? a.name : '-'
}

function statusNameById(id) {
  if (!id) return '-'
  const s = store.options.statuses.find(s => s.id === id)
  return s ? s.name : '-'
}

function existingRowClass({ row }) {
  return editingId.value === row.account_id ? 'editing-row' : ''
}

// ===== 防抖查询 =====
let lookupTimer = null
function onIdTextChange() {
  clearTimeout(lookupTimer)
  lookupTimer = setTimeout(doLookup, 400)
}

async function doLookup() {
  if (!parsedIds.value.length) {
    allFound.value = []
    return
  }
  lookingUp.value = true
  try {
    const res = await accountsApi.batchLookup(parsedIds.value)
    allFound.value = res.found || []
    claimSelection.value = []
    editingId.value = null
    newEditingId.value = null
    for (const key of Object.keys(claimEdits)) {
      if (!allFound.value.find(e => e.account_id === key)) delete claimEdits[key]
    }
  } catch {
    allFound.value = []
  } finally {
    lookingUp.value = false
  }
}

// ===== 初始化 =====
function init() {
  // 确保选项已加载
  if (!store.options.agents.length) store.loadAgents()
  if (!store.options.statuses.length) store.loadStatuses()
  const d = new Date()
  const defaultStatusId = store.options.statuses.find(s => s.name === '存活')?.id ?? null
  form.acquired_date = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
  form.name_prefix = ''
  form.mcc_id = ''
  form.timezone = ''
  form.agent = null
  form.status = defaultStatusId
  idText.value = ''
  allFound.value = []
  claimSelection.value = []
  editingId.value = null
  newEditingId.value = null
  result.value = null
  for (const k of Object.keys(claimEdits)) delete claimEdits[k]
  for (const k of Object.keys(newAccountEdits)) delete newAccountEdits[k]
  for (const k of Object.keys(newAccountBaselines)) delete newAccountBaselines[k]
  loadMccOptions()
}

async function loadMccOptions() {
  try {
    const res = await mccApi.options()
    mccOptions.value = res.options || []
  } catch { mccOptions.value = [] }
}

// ===== 提交 =====
async function submit() {
  if (!newIds.value.length && !claimSelection.value.length) {
    ElMessage.warning('没有可导入或认领的账户'); return
  }
  // 校验：至少有一个新账户有代理（共用默认值或逐行覆盖）
  const allAgents = [defaultForm.agent]
  for (const aid of newIds.value) {
    if (newAccountEdits[aid]?.agent) allAgents.push(newAccountEdits[aid].agent)
  }
  if (newIds.value.length && !allAgents.some(Boolean)) {
    ElMessage.warning('代理不能为空'); return
  }
  saving.value = true
  result.value = null

  let created = 0, claimed = 0
  const skipped = [], claimFailed = []

  // 1. 批量创建新账户
  if (newIds.value.length) {
    // 构建 overrides：比较每个新账户的当前值与默认值，只传有差异的字段
    const overrides = {}
    for (const aid of newIds.value) {
      if (!newAccountEdits[aid]) continue
      const cur = newAccountEdits[aid]
      const def = getDefaultValues(aid)
      const diff = {}
      if (cur.name !== def.name) diff.name = cur.name
      if (cur.timezone !== def.timezone) diff.timezone = cur.timezone
      if (cur.agent !== def.agent) diff.agent_id = cur.agent
      if (cur.status !== def.status) diff.status_id = cur.status
      if (cur.mcc_id !== def.mcc_id) diff.mcc_id = cur.mcc_id
      if (cur.acquired_date !== def.acquired_date) diff.acquired_date = cur.acquired_date
      if (Object.keys(diff).length) overrides[aid] = diff
    }
    try {
      const res = await accountsApi.batchCreate({
        account_ids: newIds.value,
        name_prefix: defaultForm.name_prefix,
        mcc_id: defaultForm.mcc_id || null,
        timezone: defaultForm.timezone,
        agent_id: defaultForm.agent,
        status_id: defaultForm.status,
        acquired_date: defaultForm.acquired_date,
        overrides: Object.keys(overrides).length ? overrides : undefined,
      })
      created = res.created || 0
      if (res.skipped) skipped.push(...res.skipped)
    } catch (e) {
      ElMessage.error('批量创建失败：' + (e.response?.data?.error || e.message))
    }
  }

  // 2. 认领选中的已有账户（带编辑后的字段）
  for (const row of claimSelection.value) {
    try {
      initClaimEdits(row)
      const edits = claimEdits[row.account_id]
      await accountsApi.reassign(row.id, {
        name: edits.name !== row.name ? edits.name : undefined,
        timezone: edits.timezone,
        agent_id: edits.agent,
        status_id: edits.status,
        mcc_id: edits.mcc_id,
        acquired_date: edits.acquired_date,
      })
      claimed++
    } catch (e) {
      claimFailed.push({ account_id: row.account_id, reason: e.response?.data?.error || e.message })
    }
  }

  result.value = { created, claimed, skipped, claimFailed }

  if (created > 0 || claimed > 0) {
    emit('saved')
  }
  saving.value = false
}
</script>

<style scoped>
:deep(.editing-row) {
  background-color: #ecf5ff !important;
}
</style>
