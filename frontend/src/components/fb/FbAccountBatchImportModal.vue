<template>
  <el-dialog :model-value="visible" @update:model-value="$emit('update:visible', $event)"
    title="📥 批量导入账户" width="880px" @open="init">
    <el-form label-position="top">
      <el-form-item label="账户 ID 列表" required>
        <el-input v-model="idText" type="textarea" :rows="4"
          placeholder="每行一个账户 ID，自动识别提取&#10;支持 10 位以上纯数字 / 含千分位逗号 / 含额外文字的行&#10;例如：&#10;7282512345678901234 账户A&#10;7,282,512,345,678,901,235&#10;7282512345678901236 | 主BM-A | UTC+8"
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

      <!-- ===== 他人的账户（跨用户角色可勾选认领） ===== -->
      <template v-if="existingAccounts.length">
        <el-divider content-position="left" style="margin:8px 0;">
          <template v-if="auth.canManageAccounts">
            ⚠ 他人账户（{{ existingAccounts.length }} 个）— 勾选认领
          </template>
          <template v-else>
            ⚠ 他人账户（{{ existingAccounts.length }} 个）— 属于他人，需由户管或管理员转移
          </template>
        </el-divider>
        <el-table :data="existingAccounts" size="small" border stripe max-height="200"
          @selection-change="v => claimSelection = v" style="width:100%;">
          <el-table-column v-if="auth.canManageAccounts" type="selection" width="34" />
          <el-table-column prop="account_id" label="账户 ID" min-width="170" show-overflow-tooltip />
          <el-table-column prop="name" label="名称" min-width="90" show-overflow-tooltip />
          <el-table-column label="主 BM" min-width="110" show-overflow-tooltip>
            <template #default="{ row }">{{ row.bm_name || '未分配' }}</template>
          </el-table-column>
          <el-table-column prop="timezone" label="时区" width="80" align="center" show-overflow-tooltip />
          <el-table-column label="状态" width="70" align="center">
            <template #default="{ row }">
              <el-tag size="small" :type="statusTagType(row.status)">{{ row.status || '未知' }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column label="归属" width="90" align="center" show-overflow-tooltip>
            <template #default="{ row }">
              <el-tag v-if="row.owner_name" size="small" type="warning">{{ row.owner_name }}</el-tag>
              <span v-else style="color:#ccc;">—</span>
            </template>
          </el-table-column>
        </el-table>
      </template>

      <!-- ===== 新账户列表 + 逐行覆盖 + 共用默认值 ===== -->
      <template v-if="newIds.length">
        <el-divider content-position="left" style="margin:8px 0;">新账户（{{ newIds.length }} 个）</el-divider>
        <el-table :data="newAccountRows" size="small" border stripe max-height="260"
          :row-class-name="newRowClass" style="width:100%;">
          <el-table-column prop="account_id" label="账户 ID" min-width="170" show-overflow-tooltip />
          <el-table-column label="名称" min-width="90" show-overflow-tooltip>
            <template #default="{ row }">
              <span style="font-size:12px;">{{ getNewEdit(row.account_id, 'name') }}</span>
              <span v-if="isNewDirty(row.account_id)" style="color:#e6a23c;font-size:10px;">*</span>
            </template>
          </el-table-column>
          <el-table-column label="主 BM" min-width="110" show-overflow-tooltip>
            <template #default="{ row }">{{ bmNameById(getNewEdit(row.account_id, 'primary_bm_id')) || '-' }}</template>
          </el-table-column>
          <el-table-column label="时区" width="80" align="center">
            <template #default="{ row }">{{ getNewEdit(row.account_id, 'timezone') || '-' }}</template>
          </el-table-column>
          <el-table-column label="状态" width="70" align="center">
            <template #default="{ row }">
              <el-tag size="small" :type="statusTagType(statusNameById(getNewEdit(row.account_id, 'status_id')))">
                {{ statusNameById(getNewEdit(row.account_id, 'status_id')) }}
              </el-tag>
            </template>
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
            <el-col :span="12">
              <el-form-item label="名称" style="margin-bottom:8px;">
                <el-input v-model="newAccountEdits[newEditingId].name" size="small" />
              </el-form-item>
            </el-col>
            <el-col :span="12">
              <el-form-item label="主 BM" style="margin-bottom:8px;">
                <el-select v-model="newAccountEdits[newEditingId].primary_bm_id" size="small" clearable filterable
                  placeholder="（未分配）" style="width:100%;">
                  <el-option v-for="b in bmOptions" :key="b.id" :label="b.name + ' (' + b.bm_id + ')'" :value="b.id" />
                </el-select>
              </el-form-item>
            </el-col>
          </el-row>
          <el-row :gutter="10">
            <el-col :span="12">
              <el-form-item label="时区" style="margin-bottom:0;">
                <el-select v-model="newAccountEdits[newEditingId].timezone" size="small" filterable clearable
                  allow-create default-first-option placeholder="选择或输入时区" style="width:100%;">
                  <el-option v-for="tz in timezoneOptions" :key="tz" :label="tz" :value="tz" />
                </el-select>
              </el-form-item>
            </el-col>
            <el-col :span="12">
              <el-form-item label="状态" style="margin-bottom:0;">
                <!-- 逐行状态**不设 clearable**：后端 override 判定是
                     `'status_id' in ov and ov['status_id'] is not None` ⇒ 传 null 会被当成
                     「没覆盖」而回落到共用默认值。若这里可清空，用户清空某行后表格显示 `-`、
                     落库却是共用默认状态（呈现与落库不一致）。去掉 clearable 后，
                     逐行状态要么是所选值、要么是继承的默认值，两者与后端语义一致。
                     （共用默认值那栏的 clearable 保留：那里清空 = 整批不设状态，
                     后端 common.status_id 同样为 null，语义一致，不算歧义。） -->
                <el-select v-model="newAccountEdits[newEditingId].status_id" size="small" filterable
                  placeholder="选择状态" style="width:100%;">
                  <el-option v-for="s in statusOptions" :key="s.id" :label="s.name" :value="s.id" />
                </el-select>
              </el-form-item>
            </el-col>
          </el-row>
          <el-row :gutter="10">
            <el-col :span="12">
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
                <el-form-item label="主 BM（位置）" style="margin-bottom:8px;">
                  <el-select v-model="form.primary_bm_id" size="small" clearable filterable
                    placeholder="（未分配）" style="width:100%;">
                    <el-option v-for="b in bmOptions" :key="b.id" :label="b.name + ' (' + b.bm_id + ')'" :value="b.id" />
                  </el-select>
                </el-form-item>
              </el-col>
            </el-row>
            <el-row :gutter="12">
              <el-col :span="12">
                <el-form-item label="时区" style="margin-bottom:0;">
                  <el-select v-model="form.timezone" size="small" filterable clearable allow-create
                    default-first-option placeholder="选择或输入时区" style="width:100%;">
                    <el-option v-for="tz in timezoneOptions" :key="tz" :label="tz" :value="tz" />
                  </el-select>
                </el-form-item>
              </el-col>
              <el-col :span="12">
                <el-form-item label="状态" style="margin-bottom:0;">
                  <el-select v-model="form.status_id" size="small" clearable filterable
                    placeholder="选择状态" style="width:100%;">
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

    <!-- 导入结果（失败明细必须原样呈现，不能只报「成功 N 条」） -->
    <div v-if="result" style="margin-top:10px;">
      <el-alert :type="result.errors?.length || result.claimFailed?.length ? 'warning' : 'success'" :closable="false" show-icon>
        <template #title>
          导入完成：新建 {{ result.created }} 个，认领 {{ result.claimed }} 个
          <span v-if="result.skipped?.length">，跳过 {{ result.skipped.length }} 个</span>
          <span v-if="result.errors?.length">，失败 {{ result.errors.length }} 个</span>
          <span v-if="result.claimFailed?.length">，认领失败 {{ result.claimFailed.length }} 个</span>
        </template>
      </el-alert>
      <div v-if="result.skipped?.length" style="margin-top:4px;max-height:80px;overflow-y:auto;">
        <div v-for="(s, i) in result.skipped" :key="'s' + i" style="font-size:12px;color:#e6a23c;">· {{ s || '（空 ID）' }}</div>
      </div>
      <div v-if="result.errors?.length" style="margin-top:4px;max-height:120px;overflow-y:auto;">
        <div v-for="e in result.errors" :key="'e' + e.account_id" style="font-size:12px;color:#dc2626;">
          · {{ e.account_id }} — {{ e.error }}
        </div>
      </div>
      <div v-if="result.claimFailed?.length" style="margin-top:4px;max-height:120px;overflow-y:auto;">
        <div v-for="f in result.claimFailed" :key="'cf' + f.account_id" style="font-size:12px;color:#dc2626;">
          · {{ f.account_id }} — {{ f.reason }}
        </div>
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
import { fbApi } from '@/api/fb'
import client from '@/api/client'
import { useAuthStore } from '@/stores/auth'
import { ElMessage } from 'element-plus'

const props = defineProps({ visible: Boolean })
const emit = defineEmits(['update:visible', 'imported'])
const auth = useAuthStore()

const saving = ref(false)
const lookingUp = ref(false)
const bmOptions = ref([])
const statusOptions = ref([])
const idText = ref('')
const allFound = ref([])                 // 查询到的全部已存在账户
const claimSelection = ref([])           // 勾选认领的他人账户行
const newAccountEdits = reactive({})     // { [account_id]: { name, timezone, status_id, primary_bm_id } }
const newAccountBaselines = reactive({}) // 每行上次同步时的默认值快照，用于判断用户是否手动修改
const newEditingId = ref(null)
const result = ref(null)

// ===== ID 提取（FB 账户 ID 为 10 位以上纯数字） =====
// 形制与兄弟弹窗 `FbAccountBatchLookupModal.vue` 保持一致：先剥空格/千分位逗号，
// 再取 10 位以上的连续数字（后端 `batch_create` 亦要求 `aid.isdigit()`）。
function extractAccountId(line) {
  const s = line.trim()
  if (!s) return null
  const compact = s.replace(/[\s,]/g, '')
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
  const out = []
  for (const raw of idText.value.split(/[\n]+/)) {
    const id = extractAccountId(raw)
    if (id && !seen.has(id)) { seen.add(id); out.push(id) }
  }
  return out
})

const invalidIds = computed(() => {
  if (!idText.value.trim()) return []
  return idText.value.split(/[\n]+/).map(s => s.trim()).filter(s => s && !extractAccountId(s))
})

// 他人的账户（可认领）：跨用户角色可在 UI 上勾选，认领即调 reassign 转到自己名下。
// 依赖后端 batch-lookup 返回的主键 `id`（见 fb_routes.batch_lookup_accounts）。
const existingAccounts = computed(() =>
  allFound.value.filter(a => a.owner_id !== auth.user?.id)
)
// 已属于当前用户的（仅提示，无需认领）
const alreadyMine = computed(() =>
  allFound.value.filter(a => a.owner_id === auth.user?.id)
)

const newIds = computed(() => {
  const existSet = new Set(allFound.value.map(e => e.account_id))
  return parsedIds.value.filter(id => !existSet.has(id))
})

const form = reactive({
  name_prefix: '',
  timezone: '',
  status_id: null,
  primary_bm_id: null,
  acquired_date: '',
})

// ===== 新账户逐行编辑 =====
const newAccountRows = computed(() => newIds.value.map(id => ({ account_id: id })))

function defaultName(aid) {
  return form.name_prefix ? (form.name_prefix + ' ' + aid).trim() : aid
}

function getDefaultValues(aid) {
  return {
    name: defaultName(aid),
    timezone: form.timezone,
    status_id: form.status_id,
    primary_bm_id: form.primary_bm_id,
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
    || cur.status_id !== baseline.status_id
    || cur.primary_bm_id !== baseline.primary_bm_id
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

function bmNameById(id) {
  if (!id) return null
  const b = bmOptions.value.find(o => o.id === id)
  return b ? b.name : null
}

function statusNameById(id) {
  if (!id) return '-'
  const s = statusOptions.value.find(s => s.id === id)
  return s ? s.name : '-'
}

function statusTagType(status) {
  const map = { '存活': 'success', '验证': 'warning', '死亡': 'danger', '封禁': 'danger', '限额': 'danger' }
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
    const res = await fbApi.batchLookup({ account_ids: parsedIds.value })
    allFound.value = res.found || []
    claimSelection.value = []
    newEditingId.value = null
  } catch {
    allFound.value = []
    claimSelection.value = []
  } finally {
    lookingUp.value = false
  }
}

// ===== 初始化 =====
async function init() {
  try {
    const [bmRes, statusRes] = await Promise.all([
      fbApi.bmOptions(),
      client.get('/statuses/list'),
    ])
    bmOptions.value = bmRes.data || []
    statusOptions.value = statusRes.statuses || statusRes.data || []
  } catch (e) {
    ElMessage.error('加载选项失败: ' + (e.response?.data?.error || e.message))
  }
  const d = new Date()
  const today = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
  const defaultStatusId = statusOptions.value.find(s => s.name === '存活')?.id ?? null
  form.name_prefix = ''
  form.timezone = ''
  form.status_id = defaultStatusId
  form.primary_bm_id = null
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
  saving.value = true
  result.value = null

  let created = 0, claimed = 0
  const skipped = [], errors = [], claimFailed = []

  // overrides：与共用默认值逐字段比较，只传有差异的键
  const overrides = {}
  for (const aid of newIds.value) {
    if (!newAccountEdits[aid]) continue
    const cur = newAccountEdits[aid]
    const def = getDefaultValues(aid)
    const diff = {}
    if (cur.name !== def.name) diff.name = cur.name
    if (cur.timezone !== def.timezone) diff.timezone = cur.timezone
    if (cur.status_id !== def.status_id) diff.status_id = cur.status_id
    if (cur.primary_bm_id !== def.primary_bm_id) diff.primary_bm_id = cur.primary_bm_id
    if (cur.acquired_date !== def.acquired_date) diff.acquired_date = cur.acquired_date
    if (Object.keys(diff).length) overrides[aid] = diff
  }

  // 1. 批量创建新账户（fbApi.batchCreate 收裸 body，非 accountsApi 的包装体）
  if (newIds.value.length) {
    try {
      const res = await fbApi.batchCreate({
        account_ids: newIds.value,
        name_prefix: form.name_prefix,
        timezone: form.timezone,
        status_id: form.status_id,
        primary_bm_id: form.primary_bm_id,
        acquired_date: form.acquired_date,
        overrides: Object.keys(overrides).length ? overrides : undefined,
      })
      created = res.created || 0
      if (res.skipped) skipped.push(...res.skipped)
      if (res.errors) errors.push(...res.errors)
    } catch (e) {
      ElMessage.error('批量创建失败：' + (e.response?.data?.error || e.message))
    }
  }

  // 2. 认领选中的他人账户 —— 仅跨用户角色可认领。
  //    非跨用户角色在 UI 上拿不到勾选入口，这里再拦一道，确保 claimSelection
  //    即使残留也不会触发必然 403 的 reassign（后端归属闸：非跨用户角色认领他人账户 → 403）。
  //    FB 侧无「编辑后认领」面板（形状照 TT），故传空 body 走默认路径「转给调用者自己」。
  if (auth.canManageAccounts) {
    for (const row of claimSelection.value) {
      try {
        await fbApi.reassignAccount(row.id, {})
        claimed++
      } catch (e) {
        claimFailed.push({ account_id: row.account_id, reason: e.response?.data?.error || e.message })
      }
    }
  }

  result.value = { created, claimed, skipped, errors, claimFailed }
  if (created > 0 || claimed > 0) {
    emit('imported')
  }
  saving.value = false
}
</script>

<style scoped>
:deep(.editing-row) {
  background-color: #ecf5ff !important;
}
</style>
