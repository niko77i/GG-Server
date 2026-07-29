<template>
  <el-dialog :model-value="visible" @update:model-value="$emit('update:visible', $event)"
    title="🗑 已删除账户" width="750px" @open="load">
    <div v-if="allAccounts.length" style="display:flex;gap:8px;margin-bottom:12px;align-items:center;">
      <el-input v-model="searchText" placeholder="🔍 搜索账户ID / 名称 / 代理..." clearable style="flex:1;" />
      <span style="color:#888;font-size:12px;white-space:nowrap;">{{ filteredAccounts.length }} / {{ allAccounts.length }} 条</span>
    </div>
    <el-table :data="filteredAccounts" size="small" border stripe v-if="filteredAccounts.length">
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
      <el-table-column label="操作" width="130">
        <template #default="{ row }">
          <el-button link type="success" size="small" @click="doRestore(row)" :loading="restoring === row.id">恢复</el-button>
          <el-button link type="danger" size="small" @click="doPermanentDelete(row)" :loading="deleting === row.id">删除</el-button>
        </template>
      </el-table-column>
    </el-table>
    <el-empty v-else :description="allAccounts.length ? '无匹配结果' : '暂无已删除账户'" :image-size="50" />

    <template #footer>
      <el-button @click="$emit('update:visible', false)">关闭</el-button>
    </template>
  </el-dialog>
</template>

<script setup>
import { ref, computed } from 'vue'
import { useAccountStore } from '@/stores/accounts'
import { ElMessage, ElMessageBox } from 'element-plus'

const props = defineProps({ visible: Boolean })
const emit = defineEmits(['update:visible', 'restored'])

const store = useAccountStore()
const allAccounts = ref([])
const searchText = ref('')
const restoring = ref(null)
const deleting = ref(null)

const filteredAccounts = computed(() => {
  const q = searchText.value.toLowerCase().trim()
  if (!q) return allAccounts.value
  return allAccounts.value.filter(a =>
    (a.account_id || '').toLowerCase().includes(q) ||
    (a.name || '').toLowerCase().includes(q) ||
    (a.agent || '').toLowerCase().includes(q)
  )
})

async function load() {
  allAccounts.value = await store.loadDeletedAccounts()
  searchText.value = ''
}

async function doRestore(row) {
  restoring.value = row.id
  try {
    await store.restoreAccount(row.id)
    allAccounts.value = allAccounts.value.filter(a => a.id !== row.id)
    ElMessage.success('账户已恢复')
    emit('restored')
  } catch (e) {
    ElMessage.error(e.response?.data?.error || '恢复失败')
  } finally {
    restoring.value = null
  }
}

async function doPermanentDelete(row) {
  try {
    await ElMessageBox.confirm(
      `确定永久删除账户「${row.account_id}」？此操作不可恢复，充值记录也将被清除。`,
      '确认物理删除', { type: 'warning', confirmButtonText: '确定删除', cancelButtonText: '取消' }
    )
  } catch { return }

  deleting.value = row.id
  try {
    await store.permanentDeleteAccount(row.id)
    allAccounts.value = allAccounts.value.filter(a => a.id !== row.id)
    ElMessage.success('已永久删除')
  } catch (e) {
    ElMessage.error(e.response?.data?.error || '删除失败')
  } finally {
    deleting.value = null
  }
}
</script>
