<template>
  <el-dialog :model-value="visible" @update:model-value="$emit('update:visible', $event)"
    title="🔄 同步 — 我的看板" width="700px" @open="startSync">
    <div v-if="loading" style="text-align:center;padding:40px;">
      <el-icon class="is-loading" :size="32"><Loading /></el-icon>
      <p style="margin-top:12px;color:#888;">正在读取「我的看板」...</p>
    </div>

    <div v-else-if="error" style="text-align:center;padding:20px;">
      <el-result icon="error" :title="error" />
    </div>

    <div v-else-if="diff">
      <el-alert type="info" :closable="false" style="margin-bottom:16px;">
        Sheet 中共 <strong>{{ summary?.total_in_sheet || 0 }}</strong> 条记录
      </el-alert>

      <!-- 新增 -->
      <div v-if="diff.to_create?.length" style="margin-bottom:16px;">
        <h4>🆕 新增账户（{{ diff.to_create.length }} 条）</h4>
        <el-table :data="diff.to_create" size="small" border stripe>
          <el-table-column prop="account_id" label="账户ID" min-width="130" />
          <el-table-column prop="agent" label="所属渠道" width="100" />
          <el-table-column prop="timezone" label="时区" width="80" />
          <el-table-column prop="operator" label="运营" width="80" />
        </el-table>
      </div>

      <!-- 状态变更 -->
      <div v-if="diff.to_update?.length" style="margin-bottom:16px;">
        <h4>⚠️ 状态变更确认（{{ diff.to_update.length }} 条）</h4>
        <el-table ref="updateTableRef" :data="diff.to_update" size="small" border stripe
          @selection-change="val => selectedUpdates = val">
          <el-table-column type="selection" width="45" />
          <el-table-column prop="account_id" label="账户ID" min-width="130" />
          <el-table-column prop="current_status" label="当前状态" width="90">
            <template #default="{ row }">
              <el-tag size="small" :type="statusTag(row.current_status)">{{ row.current_status }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column label="建议状态" width="90">
            <template #default="{ row }">
              <el-tag size="small" :type="statusTag(row.suggested_status)">{{ row.suggested_status }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="封户值" label="封户值" width="70" />
        </el-table>
      </div>

      <!-- 无变化 -->
      <div v-if="(diff.unchanged || 0) > 0" style="margin-bottom:16px;">
        <p style="color:#16a34a;">✅ 无变化（{{ diff.unchanged }} 条）</p>
      </div>
    </div>

    <template #footer>
      <el-button @click="$emit('update:visible', false)">取消</el-button>
      <el-button v-if="diff && !submitting" type="primary" @click="doSync" :disabled="!canSync">
        确认同步
      </el-button>
      <el-button v-if="submitting" type="primary" loading>同步中...</el-button>
    </template>
  </el-dialog>
</template>

<script setup>
import { ref, computed, nextTick } from 'vue'
import { useAccountStore } from '@/stores/accounts'
import { ElMessage } from 'element-plus'
import { Loading } from '@element-plus/icons-vue'

const props = defineProps({ visible: Boolean })
const emit = defineEmits(['update:visible', 'synced'])

const store = useAccountStore()
const loading = ref(false)
const submitting = ref(false)
const error = ref('')
const diff = ref(null)
const summary = ref(null)
const selectedUpdates = ref([])
const updateTableRef = ref(null)

const canSync = computed(() => {
  if (!diff.value) return false
  const hasCreates = (diff.value.to_create?.length || 0) > 0
  const hasUpdates = (diff.value.to_update?.length || 0) > 0
  if (hasUpdates && selectedUpdates.value.length === 0) return false
  return hasCreates || hasUpdates
})

function statusTag(status) {
  const map = { '存活': 'success', '验证': 'warning', '死亡': 'danger' }
  return map[status] || 'info'
}

async function startSync() {
  loading.value = true
  error.value = ''
  diff.value = null
  selectedUpdates.value = []
  try {
    const res = await store.syncFromSheet({ dry_run: true })
    if (res.success) {
      diff.value = res.diff
      summary.value = res.summary
      // 默认全选状态变更项 — 用 toggleRowSelection 确保 UI 复选框和数据一致
      await nextTick()
      const toUpdate = res.diff?.to_update || []
      if (updateTableRef.value && toUpdate.length) {
        toUpdate.forEach(row => updateTableRef.value.toggleRowSelection(row, true))
      }
    } else {
      error.value = res.error || '读取失败'
    }
  } catch (e) {
    error.value = e.response?.data?.error || e.message || '同步失败'
  } finally {
    loading.value = false
  }
}

async function doSync() {
  submitting.value = true
  try {
    const confirmed = {
      create: diff.value?.to_create || [],
      update: selectedUpdates.value.map(u => ({
        account_id: u.account_id,
        new_status: u.suggested_status,
      })),
    }
    const res = await store.syncFromSheet({ dry_run: false, confirmed })
    if (res.success) {
      const r = res.result
      ElMessage.success(`同步完成：新增 ${r.created} 个账户，更新 ${r.updated} 个状态`)
      emit('update:visible', false)
      emit('synced')
    } else {
      ElMessage.error(res.error || '同步失败')
    }
  } catch (e) {
    ElMessage.error(e.response?.data?.error || e.message || '同步失败')
  } finally {
    submitting.value = false
  }
}
</script>
