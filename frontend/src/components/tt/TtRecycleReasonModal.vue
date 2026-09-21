<template>
  <el-dialog :model-value="visible" @update:model-value="$emit('update:visible', $event)"
    title="♻ 填写回收原因" width="460px" @open="init">
    <el-alert type="warning" :closable="false" show-icon style="margin-bottom:12px;">
      <template #title>
        <template v-if="mode === 'batch'">
          选中的 {{ accounts.length }} 个账户状态将改为「{{ statusName }}」，请填写回收原因
        </template>
        <template v-else>
          账户「{{ account?.advertiser_id || account?.name || '' }}」状态将改为「{{ statusName }}」，请填写回收原因
        </template>
      </template>
    </el-alert>

    <el-form label-position="top">
      <el-form-item label="回收原因" required>
        <el-select v-model="form.reason" filterable allow-create default-first-option
          placeholder="选择已有原因，或输入新原因后回车自动新增"
          style="width:100%;">
          <el-option v-for="r in reasons" :key="r.id" :label="r.name" :value="r.name" />
        </el-select>
      </el-form-item>
    </el-form>

    <template #footer>
      <el-button @click="$emit('update:visible', false)">取消</el-button>
      <el-button type="primary" @click="confirm" :loading="saving">确定</el-button>
    </template>
  </el-dialog>
</template>

<script setup>
import { ref, reactive } from 'vue'
import { ttAccountsApi, ttRecycleReasonApi } from '@/api/tt'
import { ElMessage } from 'element-plus'

const props = defineProps({
  visible: Boolean,
  mode: { type: String, default: 'single' },        // 'single' | 'batch'
  account: { type: Object, default: null },          // single: 账户行 { id, advertiser_id, name, status }
  accounts: { type: Array, default: () => [] },      // batch: 选中的账户行
  statusId: { type: [Number, String], default: null },
  statusName: { type: String, default: '' },
})
const emit = defineEmits(['update:visible', 'saved'])

const saving = ref(false)
const reasons = ref([])
const form = reactive({ reason: '' })

async function init() {
  saving.value = false
  form.reason = ''
  reasons.value = []
  try {
    const res = await ttRecycleReasonApi.list()
    reasons.value = res.items || []
  } catch {
    reasons.value = []
  }
}

async function confirm() {
  const reason = (form.reason || '').trim()
  if (!reason) {
    ElMessage.warning('请选择或输入回收原因')
    return
  }
  saving.value = true
  try {
    // 自动新增（若后端已存在会返回 409，此处忽略）
    if (!reasons.value.some(r => r.name === reason)) {
      try {
        await ttRecycleReasonApi.create(reason)
      } catch (e) {
        if (e.response?.status !== 409) throw e
      }
    }
    if (props.mode === 'batch') {
      await ttAccountsApi.batchUpdate({
        ids: props.accounts.map(a => a.id),
        field: 'status_id',
        value: props.statusId,
        recycle_reason: reason,
      })
    } else {
      await ttAccountsApi.update(props.account.id, { status_id: props.statusId, recycle_reason: reason })
      // 就地更新行状态，主页面无需整表刷新即可反映
      if (props.account) {
        props.account.status = props.statusName
        props.account.status_changed_date = new Date().toISOString().slice(0, 10)
      }
    }
    ElMessage.success('状态已更新')
    emit('update:visible', false)
    emit('saved')
  } catch (e) {
    ElMessage.error(e.response?.data?.error || '更新失败')
  } finally {
    saving.value = false
  }
}
</script>
