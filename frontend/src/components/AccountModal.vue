<template>
  <el-dialog :model-value="visible" @update:model-value="$emit('update:visible', $event)"
    :title="editId ? '✏️ 编辑账户' : '➕ 新增账户'" width="500px" @open="init">
    <el-form label-position="top">
      <el-form-item label="账号名称" required>
        <el-input v-model="form.name" />
      </el-form-item>
      <el-form-item label="账号 ID" required :description="editId ? '不可修改' : ''" :error="accountIdError">
        <el-input v-model="form.account_id" :disabled="!!editId" placeholder="XXX-XXX-XXXX" @blur="formatAccountId" @input="accountIdError=''" />
      </el-form-item>
      <el-form-item label="所属 MCC">
        <el-select v-model="form.mcc_id" clearable filterable placeholder="（未分配）" style="width:100%;">
          <el-option v-for="m in mccOptions" :key="m.id" :label="m.name + ' (' + m.mcc_id + ')'" :value="m.id" />
        </el-select>
      </el-form-item>
      <el-form-item label="时区">
        <el-select v-model="form.timezone" filterable clearable placeholder="选择时区" style="width:100%;">
          <el-option v-for="tz in timezoneOptions" :key="tz" :label="tz" :value="tz" />
        </el-select>
      </el-form-item>
      <el-form-item label="代理" required>
        <el-select v-model="form.agent" filterable allow-create placeholder="输入或选择" style="width:100%;">
          <el-option v-for="a in store.settings.account_agents" :key="a" :label="a" :value="a" />
        </el-select>
      </el-form-item>
      <el-form-item label="状态" required>
        <el-select v-model="form.status" style="width:100%;" filterable>
          <el-option v-for="s in store.settings.account_statuses" :key="s" :label="s" :value="s" />
        </el-select>
      </el-form-item>
      <el-form-item label="到手时间">
        <el-date-picker v-model="form.acquired_date" type="date" style="width:100%;"
          value-format="YYYY-MM-DD" />
      </el-form-item>
<!-- 死亡时间自动处理，无需用户输入 -->
    </el-form>
    <template #footer>
      <el-button @click="$emit('update:visible', false)">取消</el-button>
      <el-button type="primary" @click="submit" :loading="saving">💾 保存</el-button>
    </template>
  </el-dialog>
</template>

<script setup>
import { ref, reactive, watch } from 'vue'
import { useAccountStore } from '@/stores/accounts'
import { mccApi } from '@/api/accounts'
import { ElMessage } from 'element-plus'

const props = defineProps({ visible: Boolean, editId: [Number, null] })
const emit = defineEmits(['update:visible', 'saved'])
const store = useAccountStore()
const saving = ref(false)
const mccOptions = ref([])
const accountIdError = ref('')
const form = reactive({ name: '', account_id: '', mcc_id: '', timezone: '', agent: '', status: '存活', acquired_date: '', death_date: '' })

// Google Ads 账户 ID 格式：XXX-XXX-XXXX（10位数字，含分隔符）
const ACCOUNT_ID_PATTERN = /^\d{3}-\d{3}-\d{4}$/

function formatAccountId() {
  const v = form.account_id.trim()
  if (!v) return
  // 如果已经是标准格式，不处理
  if (ACCOUNT_ID_PATTERN.test(v)) return
  // 如果是纯10位数字，自动格式化为 XXX-XXX-XXXX
  const digits = v.replace(/\D/g, '')
  if (digits.length === 10) {
    form.account_id = `${digits.slice(0, 3)}-${digits.slice(3, 6)}-${digits.slice(6, 10)}`
  }
}

function validateAccountId() {
  const v = form.account_id.trim()
  if (!v) return true // 空值由 required 检查处理
  if (!ACCOUNT_ID_PATTERN.test(v)) {
    accountIdError.value = '格式错误，应为 XXX-XXX-XXXX（10位数字）'
    return false
  }
  return true
}

// 时区选项（与 SettingsPanel 保持一致）
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

// 监听状态变化，自动处理死亡时间
watch(() => form.status, (newStatus, oldStatus) => {
  // 获取本地当前日期，避免时区问题
  const d = new Date()
  const today = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
  if (newStatus === '死亡' && oldStatus !== '死亡') {
    // 切换到死亡状态，自动设置死亡时间为今天
    form.death_date = today
  } else if (oldStatus === '死亡' && newStatus !== '死亡') {
    // 从死亡状态切换到其他状态，清空死亡时间
    form.death_date = ''
  }
})

async function init() {
  const res = await mccApi.options()
  mccOptions.value = res.options || []
  if (props.editId) {
    const a = store.accounts.find(a => a.id === props.editId)
    if (a) Object.assign(form, {
      name: a.name || '', account_id: a.account_id || '', mcc_id: a.mcc_id || '',
      timezone: a.timezone || '', agent: a.agent || '', status: a.status || '存活',
      acquired_date: a.acquired_date || '', death_date: a.death_date || '',
    })
  } else {
    // 获取本地当前日期，避免时区问题
    const d = new Date()
    const today = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
    Object.assign(form, { name: '', account_id: '', mcc_id: '', timezone: '', agent: '', status: '存活',
      acquired_date: today, death_date: '' })
  }
}

async function submit() {
  if (!form.name || !form.account_id || !form.agent) { ElMessage.warning('账号名称、ID 和代理不能为空'); return }
  if (!validateAccountId()) { ElMessage.warning('账号 ID 格式错误，应为 XXX-XXX-XXXX'); return }
  saving.value = true
  try {
    if (props.editId) {
      await store.updateAccount(props.editId, form)
    } else {
      await store.createAccount(form)
    }
    // 自动保存新代理名到设置
    const agents = [...(store.settings.account_agents || [])]
    if (form.agent && !agents.includes(form.agent)) {
      agents.push(form.agent)
      await store.saveSettings({ account_agents: agents })
      store.settings.account_agents = agents
    }
    emit('update:visible', false)
    emit('saved')
    ElMessage.success(props.editId ? '账户已更新' : '账户已创建')
  } catch (e) {
    ElMessage.error(e.message || '操作失败')
  } finally { saving.value = false }
}
</script>
