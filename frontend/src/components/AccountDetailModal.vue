<template>
  <el-dialog :model-value="visible" @update:model-value="$emit('update:visible', $event)"
    title="📋 账户详情" width="650px" @open="load">
    <div v-if="account" class="detail-body">
      <!-- 基本信息 -->
      <div class="info-grid">
        <div><strong>账户名称：</strong>{{ account.name }}</div>
        <div><strong>账户 ID：</strong>{{ account.account_id }}</div>
        <div>
          <strong>当前 MCC：</strong>
          <template v-if="account.mcc_name">
            <span class="mcc-current">{{ account.mcc_name }}</span>
            <span class="mcc-code"> ({{ account.mcc_code }})</span>
          </template>
          <span v-else class="text-muted">未分配</span>
        </div>
        <div><strong>时区：</strong>{{ account.timezone || '-' }}</div>
        <div><strong>代理：</strong>{{ account.agent || '-' }}</div>
        <div>
          <strong>状态：</strong>
          <el-tag size="small" :type="statusTagType(account.status)">{{ account.status || '未知' }}</el-tag>
        </div>
        <div><strong>到手时间：</strong>{{ account.acquired_date || '-' }}</div>
        <div v-if="account.death_date"><strong>死亡时间：</strong><span class="text-danger">{{ account.death_date }}</span></div>
      </div>

      <el-divider />

      <!-- 充值记录 -->
      <h4>💰 充值记录（{{ rechargeRecords.length }} 条）</h4>
      <el-table :data="rechargeRecords" size="small" border stripe v-if="rechargeRecords.length" style="margin-top:8px;">
        <el-table-column prop="amount" label="金额" width="80" />
        <el-table-column prop="agent" label="代理" width="80" />
        <el-table-column prop="operator" label="运营" width="80" />
        <el-table-column prop="created_at" label="时间" min-width="140" />
      </el-table>
      <el-empty v-else description="暂无充值记录" :image-size="40" />

      <el-divider />

      <!-- MCC 变更历史 -->
      <h4>🕓 MCC 变更历史（{{ history.length }} 条）</h4>
      <el-timeline v-if="history.length" class="history-timeline">
        <el-timeline-item
          v-for="h in history"
          :key="h.id"
          :timestamp="h.created_at"
          placement="top"
        >
          <div class="timeline-row">
            <div>
              <span class="operator-name">{{ h.changed_by_name }}</span>
              <el-tag size="small" type="info" class="type-tag">{{ h.change_type_label }}</el-tag>
              <div class="mcc-change">
                <template v-if="h.old_mcc_name">
                  <span class="old-mcc">{{ h.old_mcc_name }} ({{ h.old_mcc_code }})</span>
                </template>
                <template v-else>
                  <span class="text-muted">(未分配)</span>
                </template>
                <span class="arrow">→</span>
                <template v-if="h.new_mcc_name">
                  <span class="new-mcc">{{ h.new_mcc_name }} ({{ h.new_mcc_code }})</span>
                </template>
                <template v-else>
                  <span class="text-muted">(未分配)</span>
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
              class="delete-btn"
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
const rechargeRecords = ref([])
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
    // 加载充值记录
    const rr = await accountsApi.rechargeRecords(props.accountId)
    rechargeRecords.value = rr.records || []
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

<style scoped>
.detail-body {
  font-size: 13px;
}

.info-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 8px 16px;
  margin-bottom: 16px;
}

.mcc-current {
  color: #0891b2;
}

.mcc-code {
  font-size: 10px;
  color: #0891b2;
}

.text-muted {
  color: #999;
}

.text-danger {
  color: #dc2626;
}

.history-timeline {
  margin-top: 12px;
}

.timeline-row {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
}

.operator-name {
  color: #666;
}

.type-tag {
  margin-left: 6px;
}

.mcc-change {
  margin-top: 2px;
}

.old-mcc {
  color: #dc2626;
}

.new-mcc {
  color: #16a34a;
}

.arrow {
  margin: 0 4px;
  color: #666;
}

.delete-btn {
  flex-shrink: 0;
  opacity: 0.5;
}

.delete-btn:hover {
  opacity: 1;
}
</style>
