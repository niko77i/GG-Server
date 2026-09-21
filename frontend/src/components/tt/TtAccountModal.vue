<template>
  <el-dialog :model-value="visible" @update:model-value="$emit('update:visible', $event)"
    :title="editAccount ? '✏️ 编辑账户' : '➕ 新增账户'" width="500px" @open="init">
    <el-form label-position="top">
      <el-form-item label="账户名称" required>
        <el-input v-model="form.name" />
      </el-form-item>
      <el-form-item label="广告账户 ID" required :description="editAccount ? '不可修改' : ''" :error="accountIdError">
        <el-input v-model="form.advertiser_id" :disabled="!!editAccount" placeholder="纯数字 ID"
          @blur="onAdvertiserIdBlur" @input="accountIdError=''" />
      </el-form-item>
      <el-form-item label="所属 BC">
        <el-select v-model="form.bc_id" clearable filterable placeholder="（未分配）" style="width:100%;">
          <el-option v-for="b in bcOptions" :key="b.id" :label="b.name + ' (' + b.bc_id + ')'" :value="b.id" />
        </el-select>
      </el-form-item>
      <el-form-item label="时区">
        <el-select v-model="form.timezone" filterable clearable placeholder="选择时区" style="width:100%;">
          <el-option v-for="tz in timezoneOptions" :key="tz" :label="tz" :value="tz" />
        </el-select>
      </el-form-item>
      <el-form-item label="代理" required>
        <el-select v-model="form.agent" filterable placeholder="选择代理" style="width:100%;">
          <el-option v-for="a in agentOptions" :key="a.id" :label="a.name" :value="a.id" />
        </el-select>
      </el-form-item>
      <el-form-item label="状态" required>
        <el-select v-model="form.status" style="width:100%;" filterable>
          <el-option v-for="s in statusOptions" :key="s.id" :label="s.name" :value="s.id" />
        </el-select>
      </el-form-item>
      <el-form-item label="国家">
        <el-input v-model="form.country" />
      </el-form-item>
      <el-form-item label="消耗情况">
        <el-input v-model="form.consumption" />
      </el-form-item>
      <el-form-item label="到手时间">
        <el-date-picker v-model="form.acquired_date" type="date" style="width:100%;"
          value-format="YYYY-MM-DD" />
      </el-form-item>
      <!-- 死亡时间由后端在状态切换时自动处理，无需用户输入 -->
    </el-form>
    <template #footer>
      <el-button @click="$emit('update:visible', false)">取消</el-button>
      <el-button type="primary" @click="submit" :loading="saving">💾 保存</el-button>
    </template>
  </el-dialog>
</template>

<script setup>
import { ref, reactive } from 'vue'
import { ttApi, ttAccountsApi } from '@/api/tt'
import client from '@/api/client'
import { ElMessage } from 'element-plus'

const props = defineProps({ visible: Boolean, editAccount: { type: Object, default: null } })
const emit = defineEmits(['update:visible', 'saved'])
const saving = ref(false)
const bcOptions = ref([])
const agentOptions = ref([])
const statusOptions = ref([])
const accountIdError = ref('')
const form = reactive({
  name: '', advertiser_id: '', bc_id: '', timezone: '',
  agent: null, status: null, acquired_date: '', country: '', consumption: '',
})

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

function onAdvertiserIdBlur() {
  // TikTok 广告账户 ID 为纯数字，无自动格式化
  validateAdvertiserId()
}

function validateAdvertiserId() {
  const v = form.advertiser_id.trim()
  if (!v) return true // 空值由 required 检查处理
  if (!/^\d+$/.test(v)) {
    accountIdError.value = '格式错误，广告账户 ID 必须是纯数字'
    return false
  }
  return true
}

async function init() {
  accountIdError.value = ''
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

  if (props.editAccount) {
    const a = props.editAccount
    const matchedAgent = agentOptions.value.find(x => x.name === a.agent)
    const matchedStatus = statusOptions.value.find(x => x.name === a.status)
    Object.assign(form, {
      name: a.name || '', advertiser_id: a.advertiser_id || '', bc_id: a.bc_id || '',
      timezone: a.timezone || '', agent: matchedAgent ? matchedAgent.id : null,
      status: matchedStatus ? matchedStatus.id : null,
      acquired_date: a.acquired_date || '', country: a.country || '', consumption: a.consumption || '',
    })
  } else {
    const d = new Date()
    const today = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
    const defaultStatusId = statusOptions.value.find(s => s.name === '存活')?.id ?? null
    Object.assign(form, {
      name: '', advertiser_id: '', bc_id: '', timezone: '', agent: null,
      status: defaultStatusId, acquired_date: today, country: '', consumption: '',
    })
  }
}

async function submit() {
  if (!form.name) { ElMessage.warning('请输入账户名称'); return }
  if (!props.editAccount && !form.advertiser_id.trim()) { ElMessage.warning('请输入广告账户 ID'); return }
  if (!form.agent) { ElMessage.warning('请选择代理'); return }
  if (!validateAdvertiserId()) { ElMessage.warning('广告账户 ID 格式错误，必须是纯数字'); return }
  saving.value = true
  try {
    const body = {
      name: form.name, bc_id: form.bc_id || null, timezone: form.timezone,
      agent_id: form.agent, status_id: form.status,
      acquired_date: form.acquired_date, country: form.country, consumption: form.consumption,
    }
    if (props.editAccount) {
      await ttAccountsApi.update(props.editAccount.id, body)
    } else {
      await ttAccountsApi.create({ ...body, advertiser_id: form.advertiser_id.trim() })
    }
    emit('update:visible', false)
    emit('saved')
    ElMessage.success(props.editAccount ? '账户已更新' : '账户已创建')
  } catch (e) {
    ElMessage.error(e.response?.data?.error || e.message || '操作失败')
  } finally { saving.value = false }
}
</script>
