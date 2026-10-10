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

      <!-- 新增：① 动作类，限行 100（无勾选）。上万行直通 el-table（不做虚拟滚动）会崩标签页。 -->
      <div v-if="diff.to_create?.length" style="margin-bottom:16px;">
        <h4>🆕 新增账户（{{ diff.to_create.length }} 条）</h4>
        <p style="font-size:12px;color:#909399;margin:4px 0;">已存在的账户不会出现在这里</p>
        <el-table :data="createPrev.shown" size="small" border stripe>
          <el-table-column prop="account_id" label="账户ID" min-width="130" />
          <el-table-column prop="agent" label="所属渠道" width="100" />
          <el-table-column prop="timezone" label="时区" width="80" />
          <el-table-column prop="operator" label="运营" width="80" />
        </el-table>
        <div v-if="createPrev.hiddenCount > 0" style="margin-top:6px;font-size:12px;color:#909399;">
          …另有 {{ createPrev.hiddenCount }} 行（共 {{ createPrev.total }} 条，表里只画了前 {{ PREVIEW_LIMIT }} 行，确认后全部都会新建）
        </div>
      </div>

      <!-- 他人账户（可认领） -->
      <div v-if="diff.to_claim?.length" style="margin-bottom:16px;">
        <h4>⚠ 他人账户（{{ diff.to_claim.length }} 条）{{ canClaim ? '— 可勾选认领' : '' }}</h4>
        <el-alert v-if="!canClaim" type="info" :closable="false" style="margin-bottom:8px;"
                  title="以下账户已属于他人，无法同步给你。" />
        <!-- ① 动作类：限行 100 + 勾选解耦。to_claim 默认**不勾**（用户逐条主动认领）
             ⇒ 用「已勾集」（白名单）。@select 第一参是「已选行数组」不是布尔，必须自己取值。 -->
        <el-table ref="claimTableRef" :data="claimPrev.shown" size="small" border stripe row-key="account_id"
                  @select="(sel, row) => toggleClaim(row.account_id, sel.some(r => r.account_id === row.account_id))"
                  @select-all="sel => selectAllClaimPreview(sel.length > 0)">
          <el-table-column v-if="canClaim" type="selection" width="45" />
          <el-table-column prop="account_id" label="账户ID" min-width="130" />
          <el-table-column label="当前归属" width="110">
            <template #default="{ row }">{{ row.owner_name || '（未分配）' }}</template>
          </el-table-column>
          <el-table-column label="状态" width="120">
            <template #default="{ row }">
              <el-tag v-if="row.deleted" size="small" type="warning">已被他人删除</el-tag>
              <span v-else>—</span>
            </template>
          </el-table-column>
        </el-table>
        <div v-if="claimPrev.hiddenCount > 0" style="margin-top:6px;font-size:12px;color:#909399;">
          已选 {{ selClaimIds.length }} / 共 {{ claimPrev.total }}（表里只画了前 {{ PREVIEW_LIMIT }} 行）
          <el-button link type="primary" @click="selectAllClaim(true)">全部选中</el-button>
          <el-button link type="primary" @click="selectAllClaim(false)">全部取消</el-button>
        </div>
      </div>

      <!-- 状态变更 -->
      <div v-if="diff.to_update?.length" style="margin-bottom:16px;">
        <h4>⚠️ 状态变更确认（{{ diff.to_update.length }} 条）</h4>
        <!-- ① 动作类：限行 100 + 勾选解耦。to_update 默认**全选**（既有语义：startSync 里
             toggleRowSelection(row, true)）⇒ 用「排除集」（黑名单）表示「没被排除即选中」。 -->
        <el-table ref="updateTableRef" :data="updatePrev.shown" size="small" border stripe row-key="account_id"
          @select="(sel, row) => toggleUpdate(row.account_id, sel.some(r => r.account_id === row.account_id))"
          @select-all="sel => selectAllUpdatePreview(sel.length > 0)">
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
        <div v-if="updatePrev.hiddenCount > 0" style="margin-top:6px;font-size:12px;color:#909399;">
          已选 {{ selUpdateIds.length }} / 共 {{ updatePrev.total }}（表里只画了前 {{ PREVIEW_LIMIT }} 行）
          <el-button link type="primary" @click="selectAllUpdate(true)">全部选中</el-button>
          <el-button link type="primary" @click="selectAllUpdate(false)">全部取消</el-button>
        </div>
      </div>

      <!-- 无变化 -->
      <div v-if="(diff.unchanged || 0) > 0" style="margin-bottom:16px;">
        <p style="color:#16a34a;">✅ 无变化（{{ diff.unchanged }} 条）</p>
      </div>
    </div>

    <!-- 失败明细：执行后有未落库的条目时展示（弹窗保持打开）。
         ② 预警类：「要你去处理的问题」，**不能靠截断埋掉** ⇒ 按原因（相同 error 文案）聚合，
         用 v-for 而非 el-table（聚合后条数很少）。组数限 50、给「展开全部」入口；
         组内逐行明细也限行 100 + 「另有 N 行」。 -->
    <div v-if="errors.length" style="margin-top:16px;">
      <el-alert type="error" :closable="false" show-icon
                :title="`有 ${errors.length} 条没有同步成功`" />
      <div v-for="(g, gi) in errorGroupsShown.shown" :key="'err' + gi" style="margin-top:8px;">
        <div style="font-size:13px;color:#374151;line-height:1.8;">
          <el-tag size="small" type="danger" effect="plain" style="margin-right:6px;">⚠</el-tag>{{ g.label }}
          <span v-if="g.count > 1"> · 影响 {{ g.count }} 行</span>
          <el-button link type="primary" size="small" style="margin-left:8px;"
                     @click="toggleGroup(gi)">{{ groupOpen[gi] ? '收起' : '展开' }}</el-button>
        </div>
        <div v-if="groupOpen[gi]" style="padding:2px 0 2px 22px;">
          <div v-for="(r, ri) in groupRows(g).shown" :key="'errrow' + gi + '-' + ri"
               style="display:flex;align-items:center;gap:8px;font-size:12px;color:#909399;line-height:1.9;">
            <span style="font-family:monospace;">{{ r.account_id }}</span>
          </div>
          <div v-if="groupRows(g).hiddenCount > 0" style="font-size:12px;color:#909399;">
            …另有 {{ groupRows(g).hiddenCount }} 行
          </div>
        </div>
      </div>
      <div v-if="errorGroupsShown.hiddenCount > 0" style="margin-top:8px;font-size:12px;color:#909399;">
        …另有 {{ errorGroupsShown.hiddenCount }} 类原因
        <el-button v-if="!groupsAllOpen" link type="primary"
                   @click="groupsAllOpen = true">展开全部 {{ errorGroups.length }} 类</el-button>
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
import { ref, computed, nextTick, watch } from 'vue'
import { useAccountStore } from '@/stores/accounts'
import { useAuthStore } from '@/stores/auth'
import { ElMessage } from 'element-plus'
import { Loading } from '@element-plus/icons-vue'
// 大批量结果的「预览」纯逻辑（T1 已交付，node --test 覆盖，**不要改它**）。
// slicePreview 限行、selectedIds 把「默认全选」表示成「全量 − 排除集」，
// groupWarnings 把上千条重复失败按原因压成可读的几条。
import { DEFAULT_PREVIEW_LIMIT, slicePreview, selectedIds, groupWarnings } from '@/utils/previewRows.mjs'

const props = defineProps({ visible: Boolean })
const emit = defineEmits(['update:visible', 'synced'])

const store = useAccountStore()
const auth = useAuthStore()
const loading = ref(false)
const submitting = ref(false)
const error = ref('')
const diff = ref(null)
const summary = ref(null)
const updateTableRef = ref(null)
const claimTableRef = ref(null)
const errors = ref([])

const PREVIEW_LIMIT = DEFAULT_PREVIEW_LIMIT
// 勾选态的权威表示与「渲染出来的行」解耦（限行后 @selection-change 只报画出来的那 ≤100 行）：
//   to_update 默认**全选**（既有语义）⇒ 用「排除集」（黑名单）：选中 = 全量 id − 排除集。
//   to_claim  默认**不勾**（用户逐条主动认领）⇒ 用「已勾集」（白名单）。
const updateExcluded = ref([])
const claimPicked = ref([])

// 认领判据与「批量导入」的认领入口同源（跨用户角色才能认领他人账户）
const canClaim = computed(() => auth.canManageAccounts)

const updateIds = computed(() => (diff.value?.to_update || []).map(r => r.account_id))
const claimIds = computed(() => (diff.value?.to_claim || []).map(r => r.account_id))
const selUpdateIds = computed(() => selectedIds(updateIds.value, updateExcluded.value))
const selClaimIds = computed(() => claimIds.value.filter(id => claimPicked.value.includes(id)))

// 限行渲染：三张表只画前 PREVIEW_LIMIT 行（DOM 节点数封顶，防上万行崩标签页）。
const createPrev = computed(() => slicePreview(diff.value?.to_create || [], PREVIEW_LIMIT))
const updatePrev = computed(() => slicePreview(diff.value?.to_update || [], PREVIEW_LIMIT))
const claimPrev = computed(() => slicePreview(diff.value?.to_claim || [], PREVIEW_LIMIT))

// ② 失败明细：按原因聚合（error → message 归一，浅拷贝不原地改对象；展开明细仍带 account_id）。
const GROUP_LIMIT = 50
const GROUP_LIMIT_EXPANDED = 500
const groupsAllOpen = ref(false)
const groupOpen = ref({})
const errorGroups = computed(() => groupWarnings(errors.value.map(r => ({ ...r, message: r.error || '' }))))
const errorGroupsShown = computed(() =>
  slicePreview(errorGroups.value, groupsAllOpen.value ? GROUP_LIMIT_EXPANDED : GROUP_LIMIT))
function toggleGroup(i) { groupOpen.value = { ...groupOpen.value, [i]: !groupOpen.value[i] } }
function groupRows(g) { return slicePreview(g.rows, PREVIEW_LIMIT) }

const canSync = computed(() => {
  if (!diff.value) return false
  const hasCreates = (diff.value.to_create?.length || 0) > 0
  const hasUpdates = (diff.value.to_update?.length || 0) > 0
  // 没有新账户、且状态变更未勾选任何项时，才禁用（勾选了认领项也应放行）
  if (!hasCreates && hasUpdates && selUpdateIds.value.length === 0
      && selClaimIds.value.length === 0) return false
  return hasCreates || hasUpdates || selClaimIds.value.length > 0
})

// ---- 单行 / 表头 / 脚注 的勾选切换（都与渲染行解耦）----
function toggleUpdate(id, on) {
  updateExcluded.value = on
    ? updateExcluded.value.filter(x => x !== id)
    : [...new Set([...updateExcluded.value, id])]
}
function toggleClaim(id, on) {
  claimPicked.value = on
    ? [...new Set([...claimPicked.value, id])]
    : claimPicked.value.filter(x => x !== id)
}
/** 表头「全选」勾：只作用**本页渲染出来的 ≤100 行**。 */
function selectAllUpdatePreview(on) {
  const shownIds = updatePrev.value.shown.map(r => r.account_id)
  updateExcluded.value = on
    ? updateExcluded.value.filter(id => !shownIds.includes(id))
    : [...new Set([...updateExcluded.value, ...shownIds])]
}
function selectAllClaimPreview(on) {
  const shownIds = claimPrev.value.shown.map(r => r.account_id)
  claimPicked.value = on
    ? [...new Set([...claimPicked.value, ...shownIds])]
    : claimPicked.value.filter(id => !shownIds.includes(id))
}
/** 脚注「全部选中 / 全部取消」：作用**全量**（不只渲染行）。 */
function selectAllUpdate(on) {
  updateExcluded.value = on ? [] : [...updateIds.value]
  syncTableSelection()
}
function selectAllClaim(on) {
  claimPicked.value = on ? [...claimIds.value] : []
  syncTableSelection()
}
/** 表格内建的勾选态不在状态模型里（权威是 id 集合）⇒ 渲染完成后按模型把**画出来的那几行**
 *  同步一次。调用点：① startSync 拿到 diff、表格挂载后；② shown 变化后（watch, flush:'post'）。
 *  不要用 setTimeout 等渲染。 */
function syncTableSelection() {
  const exU = new Set(updateExcluded.value)
  const pickedC = new Set(claimPicked.value)
  updatePrev.value.shown.forEach(r => updateTableRef.value?.toggleRowSelection(r, !exU.has(r.account_id)))
  claimPrev.value.shown.forEach(r => claimTableRef.value?.toggleRowSelection(r, pickedC.has(r.account_id)))
}
watch([updatePrev, claimPrev], () => { syncTableSelection() }, { flush: 'post' })

function statusTag(status) {
  const map = { '存活': 'success', '验证': 'warning', '死亡': 'danger' }
  return map[status] || 'info'
}

async function startSync() {
  loading.value = true
  error.value = ''
  diff.value = null
  // 打开弹窗即恢复默认态：to_update 默认全选（排除集清空）、to_claim 默认不勾（已勾集清空）。
  updateExcluded.value = []
  claimPicked.value = []
  errors.value = []
  groupsAllOpen.value = false
  groupOpen.value = {}
  try {
    const res = await store.syncFromSheet({ dry_run: true })
    if (res.success) {
      diff.value = res.diff
      summary.value = res.summary
    } else {
      error.value = res.error || '读取失败'
    }
  } catch (e) {
    error.value = e.response?.data?.error || e.message || '同步失败'
  } finally {
    loading.value = false
  }
  // 表格在 loading 结束后才挂载 ⇒ 这里再等一帧，把「默认全选」的勾选态按模型画上去
  // （不用 setTimeout 等渲染）。
  await nextTick()
  syncTableSelection()
}

async function doSync() {
  submitting.value = true
  try {
    // 请求体形状不变：create 仍是全部新增行；update / claim 仍按「勾选的行」提交，
    // 只是勾选权威从「渲染行数组」换成「id 集合」（限行 100 也不会丢另外上万行的勾选）。
    const confirmed = {
      create: diff.value?.to_create || [],
      update: (diff.value?.to_update || [])
        .filter(u => selUpdateIds.value.includes(u.account_id))
        .map(u => ({
          account_id: u.account_id,
          new_status: u.suggested_status,
        })),
      claim: selClaimIds.value,
    }
    const res = await store.syncFromSheet({ dry_run: false, confirmed })
    if (res.success) {
      const r = res.result
      ElMessage.success(`同步完成：新增 ${r.created} 个账户，认领 ${r.claimed || 0} 个，更新 ${r.updated} 个状态`)
      if (r.errors?.length) {
        // 有失败明细时**不关闭弹窗** —— 让用户看得见哪几条没落库
        errors.value = r.errors
      } else {
        emit('update:visible', false)
      }
      // 带上回写腿涉及的账户：父组件靠它们对 gg_my_dashboard 轮询写表结果
      emit('synced', res.affected_account_ids || [])
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
