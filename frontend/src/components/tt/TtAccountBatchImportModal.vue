<template>
  <el-dialog :model-value="visible" @update:model-value="$emit('update:visible', $event)"
    title="📥 批量导入账户" width="880px" @open="init">
    <el-form label-position="top">
      <el-form-item label="广告账户 ID 列表" required>
        <el-input v-model="idText" type="textarea" :rows="4"
          placeholder="每行一个广告账户 ID，自动识别提取&#10;支持十位以上纯数字、按换行或逗号分隔、含额外文字的行&#10;例如：&#10;7282512345678901234 账户A&#10;7282512345678901235, 7282512345678901236&#10;7282512345678901237 | 代理X | UTC+8"
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
          以下 {{ alreadyMine.length }} 个账户已属于你，无需认领：{{ alreadyMine.map(a => a.advertiser_id).join('、') }}
        </template>
      </el-alert>

      <!-- ===== 他人的账户 ===== -->
      <template v-if="existingAccounts.length">
        <el-divider content-position="left" style="margin:8px 0;">
          ⚠ 他人账户（{{ existingAccounts.length }} 个）— 勾选认领
        </el-divider>
        <el-table :data="existingAccounts" size="small" border stripe max-height="240"
          @selection-change="v => claimSelection = v" style="width:100%;">
          <el-table-column type="selection" width="34" />
          <el-table-column prop="advertiser_id" label="广告账户 ID" min-width="180" show-overflow-tooltip />
          <el-table-column label="归属" min-width="100" show-overflow-tooltip>
            <template #default="{ row }">
              <el-tag size="small" type="warning">{{ row.owner || '未知' }}</el-tag>
            </template>
          </el-table-column>
        </el-table>
      </template>

      <!-- ===== 新账户列表 + 共用默认值 ===== -->
      <template v-if="newIds.length">
        <el-divider content-position="left" style="margin:8px 0;">新账户（{{ newIds.length }} 个）</el-divider>
        <el-table :data="newAccountRows" size="small" border stripe max-height="260"
          :row-class-name="newRowClass" style="width:100%;">
          <el-table-column prop="advertiser_id" label="广告账户 ID" min-width="180" show-overflow-tooltip />
          <el-table-column label="名称" min-width="80" show-overflow-tooltip>
            <template #default="{ row }">
              <span style="font-size:12px;">{{ getNewEdit(row.advertiser_id, 'name') }}</span>
              <span v-if="isNewDirty(row.advertiser_id)" style="color:#e6a23c;font-size:10px;">*</span>
            </template>
          </el-table-column>
          <el-table-column label="时区" width="75" align="center">
            <template #default="{ row }">{{ getNewEdit(row.advertiser_id, 'timezone') || '-' }}</template>
          </el-table-column>
          <el-table-column label="代理" width="70" align="center" show-overflow-tooltip>
            <template #default="{ row }">{{ agentNameById(getNewEdit(row.advertiser_id, 'agent')) }}</template>
          </el-table-column>
          <el-table-column label="状态" width="60" align="center">
            <template #default="{ row }">
              <el-tag size="small" :type="statusTagType(statusNameById(getNewEdit(row.advertiser_id, 'status')))">
                {{ statusNameById(getNewEdit(row.advertiser_id, 'status')) }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column label="BC" min-width="80" show-overflow-tooltip>
            <template #default="{ row }">{{ bcNameById(getNewEdit(row.advertiser_id, 'bc_id')) || '-' }}</template>
          </el-table-column>
          <el-table-column label="编辑" width="48" align="center">
            <template #default="{ row }">
              <el-button link size="small" :type="newEditingId === row.advertiser_id ? 'primary' : ''"
                @click="toggleNewEdit(row.advertiser_id)" style="padding:0;">✏️</el-button>
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
                  <el-option v-for="a in agentOptions" :key="a.id" :label="a.name" :value="a.id" />
                </el-select>
              </el-form-item>
            </el-col>
          </el-row>
          <el-row :gutter="10">
            <el-col :span="8">
              <el-form-item label="状态" style="margin-bottom:0;">
                <el-select v-model="newAccountEdits[newEditingId].status" size="small" filterable style="width:100%;">
                  <el-option v-for="s in statusOptions" :key="s.id" :label="s.name" :value="s.id" />
                </el-select>
              </el-form-item>
            </el-col>
            <el-col :span="8">
              <el-form-item label="BC" style="margin-bottom:0;">
                <el-select v-model="newAccountEdits[newEditingId].bc_id" size="small" clearable filterable style="width:100%;">
                  <el-option v-for="b in bcOptions" :key="b.id" :label="b.name + ' (' + b.bc_id + ')'" :value="b.id" />
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
                  <el-input v-model="form.name_prefix" size="small" placeholder="留空则用 ID 作名称" />
                </el-form-item>
              </el-col>
              <el-col :span="12">
                <el-form-item label="所属 BC" style="margin-bottom:8px;">
                  <el-select v-model="form.bc_id" size="small" clearable filterable placeholder="（未分配）" style="width:100%;">
                    <el-option v-for="b in bcOptions" :key="b.id" :label="b.name + ' (' + b.bc_id + ')'" :value="b.id" />
                  </el-select>
                </el-form-item>
              </el-col>
            </el-row>
            <el-row :gutter="12">
              <el-col :span="8">
                <el-form-item label="时区" style="margin-bottom:8px;">
                  <el-select v-model="form.timezone" size="small" filterable clearable placeholder="选择时区" style="width:100%;">
                    <el-option v-for="tz in timezoneOptions" :key="tz" :label="tz" :value="tz" />
                  </el-select>
                </el-form-item>
              </el-col>
              <el-col :span="8">
                <el-form-item label="代理" required style="margin-bottom:8px;">
                  <el-select v-model="form.agent" size="small" filterable placeholder="选择代理" style="width:100%;">
                    <el-option v-for="a in agentOptions" :key="a.id" :label="a.name" :value="a.id" />
                  </el-select>
                </el-form-item>
              </el-col>
              <el-col :span="8">
                <el-form-item label="状态" style="margin-bottom:8px;">
                  <el-select v-model="form.status" size="small" style="width:100%;" filterable>
                    <el-option v-for="s in statusOptions" :key="s.id" :label="s.name" :value="s.id" />
                  </el-select>
                </el-form-item>
              </el-col>
            </el-row>
            <el-form-item label="到手时间" style="margin-bottom:0;">
              <el-date-picker v-model="form.acquired_date" type="date" size="small" style="width:200px;" value-format="YYYY-MM-DD" />
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
        <div v-for="s in result.skipped" :key="s.advertiser_id" style="font-size:12px;color:#e6a23c;">· {{ s.advertiser_id }} — {{ s.reason }}</div>
      </div>
      <div v-if="result.claimFailed?.length" style="margin-top:4px;max-height:80px;overflow-y:auto;">
        <div v-for="f in result.claimFailed" :key="f.advertiser_id" style="font-size:12px;color:#dc2626;">· {{ f.advertiser_id }} — {{ f.reason }}</div>
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
import { useAuthStore } from '@/stores/auth'
import { ttApi, ttAccountsApi } from '@/api/tt'
import client from '@/api/client'
import { ElMessage } from 'element-plus'

const props = defineProps({ visible: Boolean })
const emit = defineEmits(['update:visible', 'saved'])
const auth = useAuthStore()
const saving = ref(false)
const lookingUp = ref(false)
const bcOptions = ref([])
const agentOptions = ref([])
const statusOptions = ref([])
const idText = ref('')
const allFound = ref([])           // 查询到的全部已有账户
const claimSelection = ref([])
const newAccountEdits = reactive({})   // { [advertiser_id]: { name, timezone, agent, status, bc_id, acquired_date } }
const newAccountBaselines = reactive({})
const newEditingId = ref(null)
const result = ref(null)

const myName = computed(() => auth.user?.display_name || auth.user?.username || '')

// 他人的账户（可认领）
const existingAccounts = computed(() =>
  allFound.value.filter(a => (a.owner || '') !== myName.value)
)
// 已属于当前用户的
const alreadyMine = computed(() =>
  allFound.value.filter(a => (a.owner || '') === myName.value)
)

// ===== ID 提取（TikTok 广告账户 ID 为十位以上纯数字） =====
function extractAdvertiserId(line) {
  const s = line.trim()
  if (!s) return null
  const compact = s.replace(/\s+/g, '')
  const m = compact.match(/\d{10,}/)
  return m ? m[0] : null
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
const parsedIds = computed(() => {
  if (!idText.value.trim()) return []
  const seen = new Set()
  const result = []
  for (const raw of idText.value.split(/[\n,]+/)) {
    const line = raw.trim()
    if (!line) continue
    const id = extractAdvertiserId(line)
    if (id && !seen.has(id)) { seen.add(id); result.push(id) }
  }
  return result
})

const invalidIds = computed(() => {
  if (!idText.value.trim()) return []
  return idText.value.split(/[\n,]+/).map(s => s.trim()).filter(s => s && !extractAdvertiserId(s))
})

const newIds = computed(() => {
  const existSet = new Set(allFound.value.map(e => e.advertiser_id))
  return parsedIds.value.filter(id => !existSet.has(id))
})

const form = reactive({
  name_prefix: '',
  bc_id: '',
  timezone: '',
  agent: null,
  status: null,
  acquired_date: '',
})

// ===== 新账户逐行编辑 =====
const newAccountRows = computed(() =>
  newIds.value.map(id => ({ advertiser_id: id }))
)

function defaultName(aid) {
  return form.name_prefix ? (form.name_prefix + ' ' + aid).trim() : aid
}

function getDefaultValues(aid) {
  return {
    name: defaultName(aid),
    timezone: form.timezone,
    agent: form.agent,
    status: form.status,
    bc_id: form.bc_id || '',
    acquired_date: form.acquired_date,
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

function isNewDirty(aid) {
  const cur = newAccountEdits[aid]
  const baseline = newAccountBaselines[aid]
  if (!cur || !baseline) return false
  return cur.name !== baseline.name
    || cur.timezone !== baseline.timezone
    || cur.agent !== baseline.agent
    || cur.status !== baseline.status
    || cur.bc_id !== baseline.bc_id
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
  return newEditingId.value === row.advertiser_id ? 'editing-row' : ''
}

function syncDefaultsToNewAccounts() {
  for (const aid of newIds.value) {
    if (isNewDirty(aid)) continue
    if (!newAccountEdits[aid]) newAccountEdits[aid] = {}
    const newDefaults = getDefaultValues(aid)
    Object.assign(newAccountEdits[aid], newDefaults)
    if (!newAccountBaselines[aid]) newAccountBaselines[aid] = {}
    Object.assign(newAccountBaselines[aid], newDefaults)
  }
}

watch(() => ({ ...form }), () => {
  syncDefaultsToNewAccounts()
})

watch(newIds, (ids) => {
  const idSet = new Set(ids)
  for (const key of Object.keys(newAccountEdits)) {
    if (!idSet.has(key)) delete newAccountEdits[key]
  }
  for (const key of Object.keys(newAccountBaselines)) {
    if (!idSet.has(key)) delete newAccountBaselines[key]
  }
  for (const aid of ids) initNewAccountEdit(aid)
  newEditingId.value = null
})

function bcNameById(id) {
  if (!id) return null
  const b = bcOptions.value.find(o => o.id === id)
  return b ? b.name + ' (' + b.bc_id + ')' : null
}

function agentNameById(id) {
  if (!id) return '-'
  const a = agentOptions.value.find(a => a.id === id)
  return a ? a.name : '-'
}

function statusNameById(id) {
  if (!id) return '-'
  const s = statusOptions.value.find(s => s.id === id)
  return s ? s.name : '-'
}

function statusTagType(status) {
  const map = { '存活': 'success', '验证': 'warning', '死亡': 'danger', '封禁': 'danger' }
  return map[status] || 'info'
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
    const res = await ttAccountsApi.batchLookup(parsedIds.value)
    allFound.value = res.found || []
    claimSelection.value = []
    newEditingId.value = null
  } catch {
    allFound.value = []
  } finally {
    lookingUp.value = false
  }
}

// ===== 初始化 =====
async function init() {
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
  const d = new Date()
  const today = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
  const defaultStatusId = statusOptions.value.find(s => s.name === '存活')?.id ?? null
  form.name_prefix = ''
  form.bc_id = ''
  form.timezone = ''
  form.agent = null
  form.status = defaultStatusId
  form.acquired_date = today
  idText.value = ''
  allFound.value = []
  claimSelection.value = []
  newEditingId.value = null
  result.value = null
  for (const k of Object.keys(newAccountEdits)) delete newAccountEdits[k]
  for (const k of Object.keys(newAccountBaselines)) delete newAccountBaselines[k]
}

// ===== 提交 =====
async function submit() {
  if (!newIds.value.length && !claimSelection.value.length) {
    ElMessage.warning('没有可导入或认领的账户'); return
  }
  const allAgents = [form.agent]
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
      if (cur.bc_id !== def.bc_id) diff.bc_id = cur.bc_id
      if (cur.acquired_date !== def.acquired_date) diff.acquired_date = cur.acquired_date
      if (Object.keys(diff).length) overrides[aid] = diff
    }
    try {
      const res = await ttAccountsApi.batchCreate({
        account_ids: newIds.value,
        name_prefix: form.name_prefix,
        bc_id: form.bc_id || null,
        timezone: form.timezone,
        agent_id: form.agent,
        status_id: form.status,
        acquired_date: form.acquired_date,
        overrides: Object.keys(overrides).length ? overrides : undefined,
      })
      created = res.created || 0
      if (res.skipped) skipped.push(...res.skipped)
    } catch (e) {
      ElMessage.error('批量创建失败：' + (e.response?.data?.error || e.message))
    }
  }

  // 2. 认领选中的已有账户
  for (const row of claimSelection.value) {
    try {
      await ttAccountsApi.reassign(row.id, {})
      claimed++
    } catch (e) {
      claimFailed.push({ advertiser_id: row.advertiser_id, reason: e.response?.data?.error || e.message })
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
