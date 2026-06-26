<template>
  <div>
    <h2>⚙ 设置</h2>
    <p style="color:#888;margin-bottom:20px;">自定义下拉框选项，修改后全局生效</p>

    <el-row :gutter="16">
      <el-col :span="12">
        <el-form-item label="账户状态选项">
          <el-input v-model="form.account_statuses" type="textarea" :rows="5"
            placeholder="每行一个" />
        </el-form-item>
      </el-col>
      <el-col :span="12">
        <el-form-item label="代理名选项">
          <el-input v-model="form.account_agents" type="textarea" :rows="5"
            placeholder="每行一个（留空则自由输入）" />
        </el-form-item>
      </el-col>
    </el-row>
    <el-form-item label="MCC 等级选项">
      <el-input v-model="form.mcc_levels" type="textarea" :rows="3"
        placeholder="每行一个（留空则自由输入）" />
    </el-form-item>

    <el-button type="primary" @click="save" :loading="saving">💾 保存配置</el-button>
    <span v-if="msg" style="margin-left:8px;font-size:11px;color:#059669;">{{ msg }}</span>
  </div>
</template>

<script setup>
import { ref, reactive, onMounted } from 'vue'
import { useAccountStore } from '@/stores/accounts'

const store = useAccountStore()
const saving = ref(false)
const msg = ref('')

const form = reactive({
  account_statuses: '',
  account_agents: '',
  mcc_levels: '',
})

onMounted(async () => {
  await store.loadSettings()
  form.account_statuses = (store.settings.account_statuses || []).join('\n')
  form.account_agents = (store.settings.account_agents || []).join('\n')
  form.mcc_levels = (store.settings.mcc_levels || []).join('\n')
})

async function save() {
  saving.value = true
  const body = {
    account_statuses: form.account_statuses.split('\n').map(s => s.trim()).filter(Boolean),
    account_agents: form.account_agents.split('\n').map(s => s.trim()).filter(Boolean),
    mcc_levels: form.mcc_levels.split('\n').map(s => s.trim()).filter(Boolean),
  }
  await store.saveSettings(body)
  store.settings = body
  msg.value = '✅ 已保存'
  setTimeout(() => msg.value = '', 2000)
  saving.value = false
}
</script>
