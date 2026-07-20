<template>
  <el-dialog :model-value="visible" @update:model-value="$emit('update:visible', $event)"
    title="📋 账户详情" width="650px" @open="load">
    <div v-if="account" style="font-size:13px;">
      <!-- 基本信息 -->
      <div style="display:grid;grid-template-columns:1fr 1fr;gap:8px 16px;margin-bottom:16px;">
        <div><strong>账户名称：</strong>{{ account.name }}</div>
        <div><strong>账户 ID：</strong>{{ account.account_id }}</div>
        <div>
          <strong>当前 MCC：</strong>
          <template v-if="account.mcc_name">
            <span style="color:#0891b2;">{{ account.mcc_name }}</span>
            <span style="font-size:10px;color:#0891b2;"> ({{ account.mcc_code }})</span>
          </template>
          <span v-else style="color:#888;">未分配</span>
        </div>
        <div><strong>时区：</strong>{{ account.timezone || '-' }}</div>
        <div><strong>代理：</strong>{{ account.agent || '-' }}</div>
        <div>
          <strong>状态：</strong>
          <el-tag size="small" :type="statusTagType(account.status)">{{ account.status || '未知' }}</el-tag>
        </div>
        <div><strong>到手时间：</strong>{{ account.acquired_date || '-' }}</div>
        <div v-if="account.death_date"><strong>死亡时间：</strong><span style="color:#dc2626;">{{ account.death_date }}</span></div>
      </div>

      <el-divider />

      <!-- MCC 变更历史 -->
      <h4>🕓 MCC 变更历史（{{ history.length }} 条）</h4>
      <el-timeline v-if="history.length" style="margin-top:12px;">
        <el-timeline-item
          v-for="h in history"
          :key="h.id"
          :timestamp="h.created_at"
          placement="top"
        >
          <div style="display:flex;align-items:flex-start;justify-content:space-between;">
            <div>
              <span style="color:#666;">{{ h.changed_by_name }}</span>
              <el-tag size="small" type="info" style="margin-left:6px;">{{ h.change_type_label }}</el-tag>
              <div style="margin-top:2px;">
                <template v-if="h.old_mcc_name">
                  <span style="color:#dc2626;">{{ h.old_mcc_name }} ({{ h.old_mcc_code }})</span>
                </template>
                <template v-else>
                  <span style="color:#999;">(未分配)</span>
                </template>
                <span style="margin:0 4px;color:#666;">→</span>
                <template v-if="h.new_mcc_name">
                  <span style="color:#16a34a;">{{ h.new_mcc_name }} ({{ h.new_mcc_code }})</span>
                </template>
                <template v-else>
                  <span style="color:#999;">(未分配)</span>
                </template>
              </div>
            </div>
            <el-button
              v-if="authStore.isAdmin"
              link
              type="danger"
              size="small"
              @click="deleteHistory(h.id)"
              :loading="deleting === h.id"
              style="flex-shrink:0;opacity:0.5;"
              @mouseenter="(e) => e.target.style.opacity = 1"
              @mouseleave="(e) => e.target.style.opacity = 0.5"
            >✕</el-button>
          </div>
        </el-timeline-item>
      </el-timeline>
      <el-empty v-else description="暂无 MCC 变更记录" :image-size="50" />
    </div>
    <el-empty v-else description="加载中..." :image-size="50" />

    <template #footer>
      <el-button @click="$emit('update:visible', false)">关闭</el-button>
    </template>
  </el-dialog>
</template>

<script setup>
import { ref } from 'vue'
import { accountsApi } from '@/api/accounts'
import { useAccountStore } from '@/stores/accounts'
import { useAuthStore } from '@/stores/auth'
import { ElMessage, ElMessageBox } from 'element-plus'

const props = defineProps({ visible: Boolean, accountId: [Number, null] })
const emit = defineEmits(['update:visible'])

const authStore = useAuthStore()
const account = ref(null)
const history = ref([])
const deleting = ref(null)

function statusTagType(status) {
  const map = { '存活': 'success', '验证': 'warning', '死亡': 'danger' }
  return map[status] || 'info'
}

async function load() {
  account.value = null
  history.value = []
  if (!props.accountId) return
  try {
    // 从 store 中查找账户基本信息
    const store = useAccountStore()
    const found = store.accounts.find(a => a.id === props.accountId)
    if (found) {
      account.value = { ...found }
    }
    // 加载历史
    const res = await accountsApi.history(props.accountId)
    history.value = res.history || []
  } catch (e) {
    ElMessage.error('加载失败: ' + (e.response?.data?.error || e.message))
  }
}

async function deleteHistory(hid) {
  try {
    await ElMessageBox.confirm('确定删除这条 MCC 变更记录？', '确认删除', {
      type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消',
    })
  } catch { return }

  deleting.value = hid
  try {
    await accountsApi.deleteHistory(props.accountId, hid)
    history.value = history.value.filter(h => h.id !== hid)
    ElMessage.success('已删除')
  } catch (e) {
    ElMessage.error('删除失败: ' + (e.response?.data?.error || e.message))
  } finally {
    deleting.value = null
  }
}
</script>
