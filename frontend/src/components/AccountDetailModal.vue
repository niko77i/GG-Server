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
        <div><strong>状态变更时间：</strong>{{ account.status_changed_date || '-' }}</div>
        <div><strong>到手时间：</strong>{{ account.acquired_date || '-' }}</div>
        <div v-if="account.death_date"><strong>死亡时间：</strong><span class="text-danger">{{ account.death_date }}</span></div>
      </div>

      <el-divider />

      <!-- 充值记录 -->
      <h4>💰 充值记录（{{ rechargeRecords.length }} 条）</h4>
      <el-table :data="rechargeRecords" size="small" border stripe v-if="rechargeRecords.length" style="margin-top:8px;">
        <el-table-column prop="amount" label="金额" width="80">
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
          <template #default="{ row }">
            <template v-if="editingId === row.id">
              <el-input v-model="editForm.agent" size="small" style="width:70px;" @keyup.enter="saveEdit(row)" />
            </template>
            <template v-else>{{ row.agent }}</template>
          </template>
        </el-table-column>
        <el-table-column prop="operator" label="运营" width="80" />
        <!-- 写表状态。数据源为 /api/sheet-write/status（recharge_records.sheets_synced/sheets_error
             已不再写入）。三态语汇复用一期 TT 账户表那套（@/utils/sheetWriteUi），只是换了数据源。
             有 id 但接口没有该条日志（未配表 ⇒ 根本没排写表）= 无标记，不是失败。 -->
        <el-table-column label="表格" width="55" align="center">
          <template #default="{ row }">
            <template v-if="sheetWriteFailures[String(row.id)]">
              <el-tooltip placement="top"
                :content="sheetWriteHint(sheetWriteFailures[String(row.id)])">
                <el-button link size="small"
                  :type="sheetWriteTone(sheetWriteFailures[String(row.id)].status)"
                  @click.stop="retrySheetWrite(row)">{{ sheetWriteMark(sheetWriteFailures[String(row.id)].status) }}</el-button>
              </el-tooltip>
            </template>
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
import { ref, reactive, onUnmounted } from 'vue'
import { accountsApi, rechargeApi } from '@/api/accounts'
import { sheetWriteApi } from '@/api/sheetWrite'
import { SHEET_WRITE_TOAST, sheetWriteMark, sheetWriteTone, sheetWriteHint } from '@/utils/sheetWriteUi'
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
const editingId = ref(null)
const editForm = reactive({ amount: '', agent: '' })
// 写表失败治理：business_key（= recharge_records.id 的字符串）-> 该条的终态记录
const sheetWriteFailures = ref({})

const SHEET_WRITE_POLL_MS = 3000
const SHEET_WRITE_POLL_MAX = 14          // ~42s，覆盖 30s 重试窗口
// 本弹窗只认 gg_recharge。GG 下 gg_my_dashboard（键 = accounts.account_id，带连字符的
// Ads ID）与 gg_recharge（键 = 充值记录主键，裸整数）共用一个 business_key 命名空间：
// 不按 target 过滤，就可能把「我的看板」的失败标到充值行上，并用错的 target 去重试。
const RECHARGE_TARGET = 'gg_recharge'
// 每个 business_key 一个定时器（批量/多次重试下共用一个变量会互相 clear）。
const sheetWriteTimers = new Map()       // business_key -> timerId

onUnmounted(() => {
  for (const t of sheetWriteTimers.values()) clearTimeout(t)
  sheetWriteTimers.clear()
})

function statusTagType(status) {
  const map = { '存活': 'success', '验证': 'warning', '死亡': 'danger' }
  return map[status] || 'info'
}

async function load() {
  account.value = null
  history.value = []
  rechargeRecords.value = []
  editingId.value = null
  if (!props.accountId) return
  // 与充值记录请求分开：标记是「失败必须可见」的兜底，不能随列表请求的成败而丢
  loadSheetWriteFailures()
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

/**
 * 拉本用户全部「需提示」的写表终态，按 business_key 索引。
 *
 * 只有终态才回（后端已滤 ATTENTION），中间态在这里天然不显示 —— 与「只在最终结果
 * 提示」的裁定一致。**有 id 但这里没有对应项 = 不提示**：Task 4 的 clear_recharge_id /
 * clear_recharge_ids / recharge_ids 三个字段只要记录落了库就返回，哪怕未配表格、
 * 根本没排写表（只有 affected_account_ids 是按写表闸门给的），故不能把「有 id」当失败。
 */
async function loadSheetWriteFailures() {
  try {
    const res = await sheetWriteApi.status({ platform: 'gg' })
    const map = {}
    for (const it of res.items || []) {
      if (it.target !== RECHARGE_TARGET) continue
      map[it.business_key] = it
    }
    sheetWriteFailures.value = map
  } catch { /* 标记拉不到不该打扰用户，保持上一次的结果 */ }
}

/**
 * 轮询单条直到终态（照搬一期 TtAccountPanel 的形状：按 business_key 独立计时）。
 * 中间态（pending/failed）继续等，不提示。
 */
function pollSheetWrite(businessKey) {
  let attempts = 0
  const stop = () => { sheetWriteTimers.delete(businessKey) }
  const tick = async () => {
    if (attempts >= SHEET_WRITE_POLL_MAX) { stop(); return }
    attempts++
    try {
      const res = await sheetWriteApi.status({ platform: 'gg', businessKey })
      const it = res.item
      // 无记录 = 这条路径没触发写表，**不是失败**（未配表格时 Task 4 的字段照样回，
      // 但根本没登记 sheet_write_log）。把它当失败正是 Task 2 修过的镜像 bug。
      if (!it || it.target !== RECHARGE_TARGET) { stop(); return }
      if (it.status === 'synced') { loadSheetWriteFailures(); stop(); return }
      if (it.status === 'pending' || it.status === 'failed') {
        sheetWriteTimers.set(businessKey, setTimeout(tick, SHEET_WRITE_POLL_MS))
        return
      }
      SHEET_WRITE_TOAST[sheetWriteTone(it.status)](sheetWriteHint(it))
      loadSheetWriteFailures()
      stop()
    } catch { stop() /* 轮询失败静默，靠持久标记兜底 */ }
  }
  const prev = sheetWriteTimers.get(businessKey)
  if (prev) clearTimeout(prev)
  sheetWriteTimers.set(businessKey, setTimeout(tick, SHEET_WRITE_POLL_MS))
}

/** 重试按钮：异步提交到统一入口、立即返回，随后主动轮询 —— 再失败当场就能看到 */
async function retrySheetWrite(row) {
  const f = sheetWriteFailures.value[String(row.id)]
  if (!f) return
  try {
    await sheetWriteApi.retry({ platform: 'gg', target: f.target, businessKey: String(row.id) })
    ElMessage.success('已重新提交，请稍后查看结果')
    pollSheetWrite(String(row.id))
  } catch (e) {
    ElMessage.error(e.response?.data?.error || '重试失败')
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

function startEdit(row) {
  editingId.value = row.id
  editForm.amount = row.amount
  editForm.agent = row.agent || ''
}

function cancelEdit() {
  editingId.value = null
}

async function saveEdit(row) {
  if (!editForm.amount) { ElMessage.warning('金额不能为空'); return }
  try {
    await rechargeApi.update(row.id, { amount: editForm.amount, agent: editForm.agent })
    row.amount = editForm.amount
    row.agent = editForm.agent
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
    await rechargeApi.delete(rid)
    rechargeRecords.value = rechargeRecords.value.filter(r => r.id !== rid)
    ElMessage.success('已删除')
  } catch (e) {
    ElMessage.error('删除失败: ' + (e.response?.data?.error || e.message))
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
