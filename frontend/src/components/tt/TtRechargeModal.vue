<template>
  <el-dialog :model-value="visible" @update:model-value="$emit('update:visible', $event)"
    title="💰 充值" width="450px" @open="init">
    <el-form label-position="top">
      <el-form-item label="广告账户 ID" required>
        <el-select v-model="form.account_id" filterable remote :remote-method="searchAccounts"
          :loading="searching" placeholder="搜索广告账户 ID..."
          style="width:100%;" @change="onAccountChange">
          <el-option v-for="ac in accountOptions" :key="ac.advertiser_id"
            :label="ac.advertiser_id + ' (' + (ac.name || '') + ')'" :value="ac.advertiser_id" />
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
import { ref, reactive, computed } from 'vue'
import { useAuthStore } from '@/stores/auth'
import { ttAccountsApi, ttRechargeApi } from '@/api/tt'
import { ElMessage } from 'element-plus'

const props = defineProps({
  visible: Boolean,
  defaultAccountId: { type: String, default: '' },
})
const emit = defineEmits(['update:visible', 'saved'])

const authStore = useAuthStore()
const saving = ref(false)
const searching = ref(false)
const accountOptions = ref([])

const operator = computed(() => authStore.user?.display_name || '')

const form = reactive({
  account_id: '',
  agent: '',
  amount: '',
})

async function init() {
  saving.value = false
  form.account_id = props.defaultAccountId || ''
  form.agent = ''
  form.amount = ''
  accountOptions.value = []
  if (form.account_id) {
    try {
      const res = await ttAccountsApi.lookup(form.account_id)
      if (res.found) {
        accountOptions.value = [res]
        form.agent = res.agent || ''
      }
    } catch { /* 忽略默认账户查询失败，允许重新搜索 */ }
  } else {
    await searchAccounts('')
  }
}

async function searchAccounts(query) {
  searching.value = true
  try {
    const res = await ttAccountsApi.list({ page: 1, size: 20, search: query })
    accountOptions.value = (res.items || []).filter(a => a.status === '存活')
  } catch {
    accountOptions.value = []
  } finally {
    searching.value = false
  }
}

async function onAccountChange(accountId) {
  if (!accountId) { form.agent = ''; return }
  let ac = accountOptions.value.find(a => a.advertiser_id === accountId)
  if (!ac) {
    try {
      const res = await ttAccountsApi.lookup(accountId)
      if (res.found) ac = res
    } catch { /* ignore */ }
  }
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
    await ttRechargeApi.submit({
      account_id: form.account_id,
      amount: form.amount,
      agent: form.agent,
    })
    ElMessage.success('充值记录已提交')
    emit('update:visible', false)
    emit('saved')
  } catch (e) {
    ElMessage.error(e.response?.data?.error || '充值失败')
  } finally {
    saving.value = false
  }
}
</script>
