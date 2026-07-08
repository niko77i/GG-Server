<template>
  <el-dialog :model-value="visible" @update:model-value="$emit('update:visible', $event)"
    :title="editId ? '✏️ 编辑账户' : claimExistingId ? '📥 认领账户' : '➕ 新增账户'" width="500px" @open="init">
    <el-form label-position="top">
      <el-form-item label="账号名称" required>
        <el-input v-model="form.name" />
      </el-form-item>
      <el-form-item label="账号 ID" required :description="editId || claimExistingId ? '不可修改' : ''" :error="accountIdError">
        <el-input v-model="form.account_id" :disabled="!!editId || !!claimExistingId" placeholder="XXX-XXX-XXXX"
          @blur="onAccountIdBlur" @input="accountIdError=''" :loading="lookingUp" />
      </el-form-item>
      <!-- 认领模式提示 -->
      <el-alert v-if="claimExistingId" type="warning" :closable="false" show-icon style="margin-bottom:12px;">
        <template #title>
          该账户已存在，当前归属「{{ claimOwnerName }}」。可修改下方信息后点击「转移给我」认领。
        </template>
      </el-alert>
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
      <el-button type="primary" @click="submit" :loading="saving">{{ claimExistingId ? '📥 转移给我' : '💾 保存' }}</el-button>
    </template>
  </el-dialog>
</template>

<script setup>
import { ref, reactive, watch } from 'vue'
import { useAccountStore } from '@/stores/accounts'
import { mccApi, accountsApi } from '@/api/accounts'
import { ElMessage, ElMessageBox } from 'element-plus'

const props = defineProps({ visible: Boolean, editId: [Number, null] })
const emit = defineEmits(['update:visible', 'saved'])
const store = useAccountStore()
const saving = ref(false)
const lookingUp = ref(false)
const mccOptions = ref([])
const accountIdError = ref('')
const claimExistingId = ref(null)   // DB 中已有账户的 id，非空表示认领模式
const claimOwnerName = ref('')
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

async function onAccountIdBlur() {
  // 先格式化
  formatAccountId()
  // 编辑模式或认领模式不查询
  if (props.editId || claimExistingId.value) return
  const v = form.account_id.trim()
  if (!v || !ACCOUNT_ID_PATTERN.test(v)) return

  lookingUp.value = true
  try {
    const res = await accountsApi.lookup(v)
    if (res.found && res.existing) {
      const ex = res.existing
      // 预填表单
      Object.assign(form, {
        name: ex.name || '',
        account_id: ex.account_id,
        mcc_id: ex.mcc_id || '',
        timezone: ex.timezone || '',
        agent: ex.agent || '',
        status: ex.status || '存活',
        acquired_date: ex.acquired_date || '',
        death_date: '',
      })
      claimExistingId.value = ex.id
      claimOwnerName.value = ex.owner_name
    }
  } catch {
    // 查询失败忽略，不影响正常新建流程
  } finally {
    lookingUp.value = false
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
  // 重置认领状态
  claimExistingId.value = null
  claimOwnerName.value = ''
  accountIdError.value = ''
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
    if (claimExistingId.value) {
      // 认领模式：转移归属权 + 更新字段
      await store.reassignAccount(claimExistingId.value, {
        name: form.name, timezone: form.timezone, agent: form.agent,
        status: form.status, acquired_date: form.acquired_date, mcc_id: form.mcc_id,
      })
    } else if (props.editId) {
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
    ElMessage.success(claimExistingId.value ? '账户已认领' : props.editId ? '账户已更新' : '账户已创建')
  } catch (e) {
    // 409 冲突：账户 ID 已存在，弹窗展示详情并询问是否转户
    if (e.response?.status === 409 && e.response?.data?.existing) {
      const ex = e.response.data.existing
      try {
        await ElMessageBox.confirm(
          `该账户 ID 已被「${ex.owner_name}」占用，账户详情如下：\n\n` +
          `  名称：${ex.name}\n` +
          `  ID：${ex.account_id}\n` +
          `  时区：${ex.timezone || '无'}\n` +
          `  代理：${ex.agent || '无'}\n` +
          `  状态：${ex.status || '未知'}\n` +
          `  MCC：${ex.mcc_name ? ex.mcc_name + ' (' + ex.mcc_code + ')' : '未分配'}\n` +
          `  到手时间：${ex.acquired_date || '无'}\n\n` +
          `是否将该账户转移至当前用户？`,
          '账户 ID 已存在',
          { confirmButtonText: '转移给我', cancelButtonText: '取消', type: 'warning', distinguishCancelAndClose: true }
        )
        // 用户确认 → 调用转户 API
        await store.reassignAccount(ex.id)
        ElMessage.success(`账户「${ex.name}」已转移至当前用户`)
        emit('update:visible', false)
        emit('saved')
      } catch (cancelErr) {
        // 用户取消或关闭弹窗，不做操作
      }
    } else {
      ElMessage.error(e.response?.data?.error || e.message || '操作失败')
    }
  } finally { saving.value = false }
}
</script>
