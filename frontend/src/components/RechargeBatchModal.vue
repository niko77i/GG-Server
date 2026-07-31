<template>
  <el-dialog :model-value="visible" @update:model-value="$emit('update:visible', $event)"
    title="💰 批量充值" width="600px" @open="init">
    <div style="display:flex;gap:8px;margin-bottom:12px;align-items:center;">
      <span style="white-space:nowrap;">统一金额:</span>
      <el-input v-model="unifiedAmount" placeholder="输入金额（纯数字）" style="width:150px;" size="small"
        @input="unifiedAmount = unifiedAmount.replace(/[^0-9.]/g, '').replace(/(\..*)\./g, '$1')" />
      <el-button size="small" @click="applyUnified" :disabled="!unifiedAmount">📝 应用</el-button>
    </div>
    <el-table :data="rows" size="small" border stripe max-height="400">
      <el-table-column prop="account_id" label="账户ID" width="160" />
      <el-table-column prop="agent" label="代理" width="100" />
      <el-table-column label="金额" min-width="150">
        <template #default="{ row, $index }">
          <el-input v-model="row.amount" placeholder="输入金额（纯数字）" size="small"
          @input="row.amount = row.amount.replace(/[^0-9.]/g, '').replace(/(\..*)\./g, '$1')" />
        </template>
      </el-table-column>
    </el-table>
    <template #footer>
      <el-button @click="$emit('update:visible', false)">取消</el-button>
      <el-button type="primary" @click="submit" :loading="saving">
        💰 确认批量充值 ({{ rows.length }})
      </el-button>
    </template>
  </el-dialog>
</template>

<script setup>
import { ref, reactive, watch } from 'vue'
import { useAccountStore } from '@/stores/accounts'
import { useAuthStore } from '@/stores/auth'
import { ElMessage } from 'element-plus'

const props = defineProps({
  visible: Boolean,
  accounts: { type: Array, default: () => [] },
})
const emit = defineEmits(['update:visible', 'saved'])

const store = useAccountStore()
const authStore = useAuthStore()
const saving = ref(false)
const unifiedAmount = ref('')
const rows = ref([])

function init() {
  const alive = props.accounts.filter(a => a.status === '存活')
  const skipped = props.accounts.length - alive.length
  if (skipped > 0) {
    ElMessage.warning(`已跳过 ${skipped} 个非存活状态的账户，仅可对存活账户充值`)
  }
  rows.value = alive.map(a => ({
    account_id: a.account_id,
    agent: a.agent || '',
    amount: '',
  }))
  unifiedAmount.value = ''
}

function applyUnified() {
  if (!unifiedAmount.value) return
  rows.value.forEach(r => { r.amount = unifiedAmount.value })
}

async function submit() {
  const records = rows.value.filter(r => r.amount)
  if (!records.length) {
    ElMessage.warning('请至少填写一个金额')
    return
  }
  // 校验每个金额是否为合法正数
  for (const r of records) {
    const amt = parseFloat(r.amount)
    if (isNaN(amt) || amt <= 0) {
      ElMessage.warning(`账户 ${r.account_id} 的金额「${r.amount}」无效，请输入大于 0 的数字`)
      return
    }
  }
  saving.value = true
  try {
    const res = await store.rechargeBatchSubmit({ records })
    if (res.warning) ElMessage.warning(res.warning)
    else ElMessage.success(`已提交 ${res.count} 条充值记录`)
    emit('update:visible', false)
    emit('saved')
  } catch (e) {
    ElMessage.error(e.response?.data?.error || '批量充值失败')
  }
  saving.value = false
}
</script>
