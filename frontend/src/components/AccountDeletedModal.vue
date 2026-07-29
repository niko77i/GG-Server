<template>
  <el-dialog :model-value="visible" @update:model-value="$emit('update:visible', $event)"
    title="🗑 已删除账户" width="700px" @open="load">
    <el-table :data="accounts" size="small" border stripe v-if="accounts.length">
      <el-table-column prop="account_id" label="账户ID" min-width="130" show-overflow-tooltip />
      <el-table-column prop="name" label="账户名称" min-width="100">
        <template #default="{ row }">
          <span v-if="row.name">{{ row.name }}</span>
          <span v-else style="color:#ccc;">—</span>
        </template>
      </el-table-column>
      <el-table-column prop="agent" label="代理" width="80" />
      <el-table-column prop="timezone" label="时区" width="80" />
      <el-table-column label="状态" width="80">
        <template #default="{ row }">
          <el-tag size="small" type="info">{{ row.status || '未知' }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="deleted_at" label="删除时间" min-width="120" />
      <el-table-column label="操作" width="80">
        <template #default="{ row }">
          <el-button link type="success" size="small" @click="doRestore(row)" :loading="restoring === row.id">恢复</el-button>
        </template>
      </el-table-column>
    </el-table>
    <el-empty v-else description="暂无已删除账户" :image-size="50" />

    <template #footer>
      <el-button @click="$emit('update:visible', false)">关闭</el-button>
    </template>
  </el-dialog>
</template>

<script setup>
import { ref } from 'vue'
import { useAccountStore } from '@/stores/accounts'
import { ElMessage } from 'element-plus'

const props = defineProps({ visible: Boolean })
const emit = defineEmits(['update:visible', 'restored'])

const store = useAccountStore()
const accounts = ref([])
const restoring = ref(null)

async function load() {
  accounts.value = await store.loadDeletedAccounts()
}

async function doRestore(row) {
  restoring.value = row.id
  try {
    await store.restoreAccount(row.id)
    accounts.value = accounts.value.filter(a => a.id !== row.id)
    ElMessage.success('账户已恢复')
    emit('restored')
  } catch (e) {
    ElMessage.error(e.response?.data?.error || '恢复失败')
  } finally {
    restoring.value = null
  }
}
</script>
