<template>
  <el-dialog :model-value="visible" @update:model-value="$emit('update:visible', $event)"
    title="📋 账户详情" width="650px" @open="load">
    <div v-if="account" class="detail-body">
      <!-- 基本信息 -->
      <div class="info-grid">
        <div><strong>账户名称：</strong>{{ account.name }}</div>
        <div><strong>广告账户 ID：</strong>{{ account.advertiser_id }}</div>
        <div>
          <strong>当前 BC：</strong>
          <span v-if="account.bc_name" class="bc-current">{{ account.bc_name }}</span>
          <span v-else class="text-muted">未分配</span>
        </div>
        <div><strong>时区：</strong>{{ account.timezone || '-' }}</div>
        <div><strong>代理：</strong>{{ account.agent || '-' }}</div>
        <div>
          <strong>状态：</strong>
          <el-tag size="small" :type="statusTagType(account.status)">{{ account.status || '未知' }}</el-tag>
        </div>
        <div><strong>国家：</strong>{{ account.country || '-' }}</div>
        <div><strong>消耗情况：</strong>{{ account.consumption || '-' }}</div>
        <div><strong>状态变更时间：</strong>{{ account.status_changed_date || '-' }}</div>
        <div><strong>到手时间：</strong>{{ account.acquired_date || '-' }}</div>
        <div v-if="account.death_date"><strong>死亡时间：</strong><span class="text-danger">{{ account.death_date }}</span></div>
      </div>

      <el-divider />

      <!-- 充值记录 -->
      <h4>💰 充值记录（{{ rechargeRecords.length }} 条）</h4>
      <el-table :data="rechargeRecords" size="small" border stripe v-if="rechargeRecords.length" style="margin-top:8px;">
        <el-table-column prop="amount" label="金额" width="90">
          <template #default="{ row }">
            <template v-if="editingId === row.id">
              <el-input v-model="editForm.amount" size="small" style="width:70px;" @keyup.enter="saveEdit(row)" />
            </template>
            <template v-else>{{ row.amount }}</template>
          </template>
        </el-table-column>
        <el-table-column prop="status" label="状态" width="80">
          <template #default="{ row }">
            <el-tag v-if="row.status" size="small" type="warning">{{ row.status }}</el-tag>
            <span v-else>-</span>
          </template>
        </el-table-column>
        <el-table-column prop="agent" label="代理" width="80">
          <template #default="{ row }">{{ row.agent || '-' }}</template>
        </el-table-column>
        <el-table-column prop="operator" label="运营" width="90" />
        <el-table-column label="表格" width="55" align="center">
          <template #default="{ row }">
            <el-tooltip v-if="row.sheets_synced === 0" :content="row.sheets_error || '未同步到表格'" placement="top">
              <el-button link size="small" type="warning" @click="retryRechargeSheets(row)" :loading="retryingId === row.id">⚠️</el-button>
            </el-tooltip>
            <span v-else style="color:#16a34a;font-size:14px;">✅</span>
          </template>
        </el-table-column>
        <el-table-column prop="created_at" label="时间" min-width="120" />
        <el-table-column label="操作" width="70">
          <template #default="{ row }">
            <template v-if="editingId === row.id">
              <el-button link type="success" size="small" @click="saveEdit(row)">保存</el-button>
              <el-button link size="small" @click="cancelEdit">取消</el-button>
            </template>
            <template v-else>
              <el-button link type="primary" size="small" @click="startEdit(row)">✏️</el-button>
              <el-button link type="danger" size="small" @click="deleteRecharge(row.id)">✕</el-button>
            </template>
          </template>
        </el-table-column>
      </el-table>
      <el-empty v-else description="暂无充值记录" :image-size="40" />

      <el-divider />

      <!-- BC 变更历史 -->
      <h4>🕓 BC 变更历史（{{ history.length }} 条）</h4>
      <el-timeline v-if="history.length" class="history-timeline">
        <el-timeline-item
          v-for="h in history"
          :key="h.id"
          :timestamp="h.created_at"
          placement="top"
        >
          <div class="timeline-row">
            <div>
              <span class="operator-name">{{ h.changed_by }}</span>
              <el-tag size="small" type="info" class="type-tag">{{ changeTypeLabel(h.change_type) }}</el-tag>
              <div class="bc-change">
                <template v-if="h.old_bc">
                  <span class="old-bc">{{ h.old_bc }}</span>
                </template>
                <template v-else>
                  <span class="text-muted">(未分配)</span>
                </template>
                <span class="arrow">→</span>
                <template v-if="h.new_bc">
                  <span class="new-bc">{{ h.new_bc }}</span>
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
      <el-empty v-else description="暂无 BC 变更记录" :image-size="50" />
    </div>
    <el-empty v-else description="加载中..." :image-size="50" />

    <template #footer>
      <el-button @click="$emit('update:visible', false)">关闭</el-button>
    </template>
  </el-dialog>
</template>

<script setup>
import { ref, reactive } from 'vue'
import { ttAccountsApi, ttRechargeApi } from '@/api/tt'
import { useAuthStore } from '@/stores/auth'
import { ElMessage, ElMessageBox } from 'element-plus'

const props = defineProps({ visible: Boolean, account: { type: Object, default: null } })
const emit = defineEmits(['update:visible'])

const authStore = useAuthStore()
const history = ref([])
const rechargeRecords = ref([])
const deleting = ref(null)
const editingId = ref(null)
const editForm = reactive({ amount: '' })
const retryingId = ref(null)

function statusTagType(status) {
  const map = { '存活': 'success', '验证': 'warning', '死亡': 'danger', '封禁': 'danger' }
  return map[status] || 'info'
}

function changeTypeLabel(t) {
  const map = { manual: '手动编辑', batch: '批量修改', reassign: '认领转移', import: '批量导入', create: '新建账户' }
  return map[t] || t
}

async function load() {
  history.value = []
  rechargeRecords.value = []
  editingId.value = null
  if (!props.account || !props.account.id) return
  try {
    const [hr, rr] = await Promise.all([
      ttAccountsApi.bcHistory(props.account.id),
      ttRechargeApi.records(props.account.id),
    ])
    history.value = hr.items || []
    rechargeRecords.value = rr.items || []
  } catch (e) {
    ElMessage.error('加载失败: ' + (e.response?.data?.error || e.message))
  }
}

async function deleteHistory(hid) {
  try {
    await ElMessageBox.confirm('确定删除这条 BC 变更记录？', '确认删除', {
      type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消',
    })
  } catch { return }

  deleting.value = hid
  try {
    await ttAccountsApi.deleteBcHistory(props.account.id, hid)
    history.value = history.value.filter(h => h.id !== hid)
    ElMessage.success('已删除')
  } catch (e) {
    ElMessage.error('删除失败: ' + (e.response?.data?.error || e.message))
  } finally {
    deleting.value = null
  }
}

function startEdit(row) {
  editingId.value = row.id
  editForm.amount = row.amount
}

function cancelEdit() {
  editingId.value = null
}

async function saveEdit(row) {
  if (!editForm.amount) { ElMessage.warning('金额不能为空'); return }
  try {
    await ttRechargeApi.update(row.id, { amount: editForm.amount })
    row.amount = editForm.amount
    editingId.value = null
    ElMessage.success('已更新')
  } catch (e) {
    ElMessage.error('更新失败: ' + (e.response?.data?.error || e.message))
  }
}

async function deleteRecharge(rid) {
  try {
    await ElMessageBox.confirm('确定删除这条充值记录？', '确认删除', {
      type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消',
    })
  } catch { return }
  try {
    await ttRechargeApi.delete(rid)
    rechargeRecords.value = rechargeRecords.value.filter(r => r.id !== rid)
    ElMessage.success('已删除')
  } catch (e) {
    ElMessage.error('删除失败: ' + (e.response?.data?.error || e.message))
  }
}

async function retryRechargeSheets(row) {
  retryingId.value = row.id
  try {
    await ttRechargeApi.retrySheets(row.id)
    row.sheets_synced = 1
    row.sheets_error = ''
    ElMessage.success('已同步到表格')
  } catch (e) {
    row.sheets_error = e.response?.data?.error || e.message || '同步失败'
    ElMessage.error('同步失败: ' + row.sheets_error)
  } finally {
    retryingId.value = null
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

.bc-current {
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

.bc-change {
  margin-top: 2px;
}

.old-bc {
  color: #dc2626;
}

.new-bc {
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
