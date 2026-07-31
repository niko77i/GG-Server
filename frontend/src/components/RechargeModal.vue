<template>
  <el-dialog :model-value="visible" @update:model-value="$emit('update:visible', $event)"
    title="💰 充值" width="450px" @open="init">
    <el-form label-position="top">
      <el-form-item label="账户ID" required>
        <el-select v-model="form.account_id" filterable placeholder="搜索账户ID..."
          style="width:100%;" @change="onAccountChange">
          <el-option v-for="ac in accountOptions" :key="ac.account_id"
            :label="ac.account_id + ' (' + ac.name + ')'" :value="ac.account_id" />
        </el-select>
      </el-form-item>
      <el-form-item label="代理">
        <el-input :model-value="form.agent" disabled />
      </el-form-item>
      <el-form-item label="运营">
        <el-input :model-value="operator" disabled />
      </el-form-item>
      <el-form-item label="金额" required>
        <el-input v-model="form.amount" placeholder="输入充值金额（纯数字）"
          @input="form.amount = form.amount.replace(/[^0-9.]/g, '').replace(/(\..*)\./g, '$1')" />
      </el-form-item>
    </el-form>
    <template #footer>
      <el-button @click="$emit('update:visible', false)">取消</el-button>
      <el-button type="primary" @click="submit" :loading="saving">💰 确认充值</el-button>
    </template>
  </el-dialog>
</template>

<script setup>
import { ref, reactive, computed, watch } from 'vue'
import { useAccountStore } from '@/stores/accounts'
import { useAuthStore } from '@/stores/auth'
import { ElMessage } from 'element-plus'

const props = defineProps({
  visible: Boolean,
  defaultAccountId: { type: String, default: '' },
})
const emit = defineEmits(['update:visible', 'saved'])

const store = useAccountStore()
const authStore = useAuthStore()
const saving = ref(false)

const accountOptions = computed(() => (store.accounts || []).filter(a => a.status === '存活'))

const operator = computed(() => authStore.user?.display_name || '')

const form = reactive({
  account_id: '',
  agent: '',
  amount: '',
})

function init() {
  form.account_id = props.defaultAccountId || ''
  form.amount = ''
  onAccountChange(props.defaultAccountId || '')
}

function onAccountChange(accountId) {
  const ac = store.accounts.find(a => a.account_id === accountId)
  form.agent = ac ? (ac.agent || '') : ''
}

async function submit() {
  if (!form.account_id || !form.amount) {
    ElMessage.warning('账户ID和金额不能为空')
    return
  }
  const amt = parseFloat(form.amount)
  if (isNaN(amt) || amt <= 0) {
    ElMessage.warning('金额必须为大于 0 的数字')
    return
  }
  saving.value = true
  try {
    const res = await store.rechargeSubmit({
      account_id: form.account_id,
      amount: form.amount,
      agent: form.agent,
    })
    if (res.warning) ElMessage.warning(res.warning)
    else ElMessage.success('充值记录已提交')
    emit('update:visible', false)
    emit('saved')
  } catch (e) {
    ElMessage.error(e.response?.data?.error || '充值失败')
  }
  saving.value = false
}
</script>
