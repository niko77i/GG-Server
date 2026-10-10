<template>
  <el-dialog :model-value="visible" @update:model-value="$emit('update:visible', $event)"
    title="🔄 同步 — 我的看板" width="720px" @open="startSync">
    <div v-if="loading" style="text-align:center;padding:40px;">
      <el-icon class="is-loading" :size="32"><Loading /></el-icon>
      <p style="margin-top:12px;color:#888;">正在读取「我的看板」...</p>
    </div>

    <div v-else-if="error" style="text-align:center;padding:20px;">
      <el-result icon="error" :title="error" />
    </div>

    <div v-else-if="done">
      <div style="display:flex;align-items:center;gap:8px;margin-bottom:12px;">
        <span style="font-size:13px;color:#374151;white-space:nowrap;">本次新建账户的户类型</span>
        <el-select v-model="accountType" size="small" style="width:200px;" filterable allow-create>
          <el-option v-for="t in props.typeOptions" :key="t" :label="t" :value="t" />
        </el-select>
        <span style="font-size:12px;color:#909399;">只作用于新建的账户；已存在的账户类型不变</span>
      </div>

      <el-alert type="info" :closable="false" style="margin-bottom:16px;">
        Sheet 中共 <strong>{{ total }}</strong> 条记录
      </el-alert>

      <!-- 新增：① 动作类，限行 100（无勾选）。上万行直通 el-table（不做虚拟滚动）会崩标签页。 -->
      <div v-if="created.length" style="margin-bottom:16px;">
        <h4>🆕 新增账户（{{ created.length }} 条）</h4>
        <el-table :data="createdPrev.shown" size="small" border stripe>
          <el-table-column prop="advertiser_id" label="广告账户 ID" min-width="180" show-overflow-tooltip />
          <el-table-column label="户类型" width="100"><template #default>{{ accountType }}</template></el-table-column>
          <el-table-column prop="bc" label="BC" width="100" show-overflow-tooltip />
          <el-table-column prop="country" label="国家" width="80" />
          <el-table-column prop="agent" label="代理" width="90" show-overflow-tooltip />
          <el-table-column prop="timezone" label="时区" width="90" />
          <el-table-column label="状态" width="90">
            <template #default="{ row }">
              <el-tag :type="statusTagType(row.status)" size="small">{{ row.status || '存活' }}</el-tag>
            </template>
          </el-table-column>
        </el-table>
        <div v-if="createdPrev.hiddenCount > 0" style="margin-top:6px;font-size:12px;color:#909399;">
          …另有 {{ createdPrev.hiddenCount }} 行（共 {{ createdPrev.total }} 条，表里只画了前 {{ PREVIEW_LIMIT }} 行，确认后全部都会新建）
        </div>
      </div>

      <!-- 无变化 -->
      <div v-if="updated.length" style="margin-bottom:16px;">
        <p style="color:#16a34a;">✅ 无变化（{{ updated.length }} 条）</p>
      </div>

      <!-- 消耗情况冲突：② 预警类（「要你去处理的问题」，每行带独立单选「处理方式」）。
           每行决策互不相同、无同质「原因」可聚合 ⇒ 聚合会摧毁逐行决策（破坏既有功能）。
           故用前端分页保证「每一行都可达、可决」，而不是「另有 N 行」埋掉。 -->
      <div v-if="conflicts.length" style="margin-bottom:16px;">
        <h4>⚠️ 消耗情况冲突（{{ conflicts.length }} 条）— 请逐条选择处理方式</h4>
        <el-table :data="conflictPaged" size="small" border stripe row-key="advertiser_id">
          <el-table-column prop="advertiser_id" label="广告账户 ID" min-width="180" show-overflow-tooltip />
          <el-table-column label="Sheet 消耗情况" min-width="130">
            <template #default="{ row }">
              <span style="color:#2563eb;">{{ row.sheet_value || '—' }}</span>
            </template>
          </el-table-column>
          <el-table-column label="系统消耗情况" min-width="130">
            <template #default="{ row }">
              <span style="color:#16a34a;">{{ row.system_value || '—' }}</span>
            </template>
          </el-table-column>
          <el-table-column label="处理方式" min-width="210">
            <template #default="{ row }">
              <el-radio-group v-model="conflictChoices[row.advertiser_id]" size="small">
                <el-radio-button value="sheet">以 Sheet 为准</el-radio-button>
                <el-radio-button value="system">以系统为准</el-radio-button>
              </el-radio-group>
            </template>
          </el-table-column>
        </el-table>
        <el-pagination v-if="conflicts.length > CONFLICT_PAGE_SIZE" v-model:current-page="conflictPage"
          :page-size="CONFLICT_PAGE_SIZE" :total="conflicts.length" layout="prev,pager,next"
          style="margin-top:8px;justify-content:flex-end;" />
      </div>

      <!-- 状态冲突：同上（② 预警类 ⇒ 前端分页，保证逐行可决） -->
      <div v-if="statusConflicts.length" style="margin-bottom:16px;">
        <h4>⚠️ 状态冲突（{{ statusConflicts.length }} 条）— 请逐条选择处理方式</h4>
        <el-table :data="statusConflictPaged" size="small" border stripe row-key="advertiser_id">
          <el-table-column prop="advertiser_id" label="广告账户 ID" min-width="180" show-overflow-tooltip />
          <el-table-column label="Sheet 状态" min-width="110">
            <template #default="{ row }">
              <el-tag :type="statusTagType(row.sheet_status)" size="small">{{ row.sheet_status || '存活' }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column label="系统状态" min-width="110">
            <template #default="{ row }">
              <el-tag :type="statusTagType(row.system_status)" size="small">{{ row.system_status || '存活' }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column label="处理方式" min-width="210">
            <template #default="{ row }">
              <el-radio-group v-model="statusChoices[row.advertiser_id]" size="small">
                <el-radio-button value="sheet">以 Sheet 为准</el-radio-button>
                <el-radio-button value="system">以系统为准</el-radio-button>
              </el-radio-group>
            </template>
          </el-table-column>
        </el-table>
        <el-pagination v-if="statusConflicts.length > CONFLICT_PAGE_SIZE" v-model:current-page="statusPage"
          :page-size="CONFLICT_PAGE_SIZE" :total="statusConflicts.length" layout="prev,pager,next"
          style="margin-top:8px;justify-content:flex-end;" />
      </div>

      <!-- 无任何变化 -->
      <div v-if="!created.length && !updated.length && !conflicts.length && !statusConflicts.length">
        <p style="color:#909399;">看板中没有需要同步的账户。</p>
      </div>
    </div>

    <template #footer>
      <el-button @click="$emit('update:visible', false)">取消</el-button>
      <el-button v-if="done && canSync" type="primary" @click="doSync" :loading="submitting">
        确认同步
      </el-button>
    </template>
  </el-dialog>
</template>

<script setup>
import { ref, reactive, computed } from 'vue'
import { ttAccountsApi } from '@/api/tt'
import { ElMessage } from 'element-plus'
import { Loading } from '@element-plus/icons-vue'
// 大批量结果的「预览」纯逻辑（T1 已交付，node --test 覆盖，**不要改它**）。
import { DEFAULT_PREVIEW_LIMIT, slicePreview } from '@/utils/previewRows.mjs'

const props = defineProps({
  visible: Boolean,
  // 户类型候选由 TtAccountPanel 传入（弹窗自己不请求，理由见 TtAccountModal）
  typeOptions: { type: Array, default: () => ['加白户', '企业户'] },
})
const emit = defineEmits(['update:visible', 'synced'])

const accountType = ref('加白户')
const loading = ref(false)
const submitting = ref(false)
const error = ref('')
const done = ref(false)
const total = ref(0)
const created = ref([])
const updated = ref([])
const conflicts = ref([])
const conflictChoices = reactive({})
const statusConflicts = ref([])
const statusChoices = reactive({})

const canSync = computed(() => created.value.length > 0 || conflicts.value.length > 0 || statusConflicts.value.length > 0)

// 限行/分页（防上万行直通 el-table 崩标签页）。
// created：① 动作类，限行 100 即可（无勾选；提交不由这些行驱动）。
const PREVIEW_LIMIT = DEFAULT_PREVIEW_LIMIT
const createdPrev = computed(() => slicePreview(created.value, PREVIEW_LIMIT))
// conflicts / statusConflicts：② 预警类（要你去处理的问题），每行带独立单选决策。
// 前端分页（不是聚合、不是截断）：choices 是按 advertiser_id 存的 dict，与渲染行天然解耦，
// 翻页只换渲染的行，已选决策与隐藏行的默认决策都不会丢。
const CONFLICT_PAGE_SIZE = 50
const conflictPage = ref(1)
const statusPage = ref(1)
const conflictPaged = computed(() =>
  conflicts.value.slice((conflictPage.value - 1) * CONFLICT_PAGE_SIZE, conflictPage.value * CONFLICT_PAGE_SIZE))
const statusConflictPaged = computed(() =>
  statusConflicts.value.slice((statusPage.value - 1) * CONFLICT_PAGE_SIZE, statusPage.value * CONFLICT_PAGE_SIZE))

function statusTagType(status) {
  const map = { '存活': 'success', '验证': 'warning', '死亡': 'danger', '封禁': 'danger' }
  return map[status] || 'info'
}

async function startSync() {
  loading.value = true
  error.value = ''
  done.value = false
  total.value = 0
  created.value = []
  updated.value = []
  conflicts.value = []
  statusConflicts.value = []
  conflictPage.value = 1
  statusPage.value = 1
  for (const k of Object.keys(conflictChoices)) delete conflictChoices[k]
  for (const k of Object.keys(statusChoices)) delete statusChoices[k]
  try {
    const res = await ttAccountsApi.syncFromSheet({ dry_run: true, account_type: accountType.value })
    total.value = res.total || 0
    created.value = res.created || []
    updated.value = res.updated || []
    conflicts.value = res.conflicts || []
    statusConflicts.value = res.status_conflicts || []
    for (const c of conflicts.value) {
      conflictChoices[c.advertiser_id] = 'sheet'
    }
    for (const c of statusConflicts.value) {
      statusChoices[c.advertiser_id] = 'sheet'
    }
    done.value = true
  } catch (e) {
    error.value = e.response?.data?.error || e.message || '同步失败'
  } finally {
    loading.value = false
  }
}

async function doSync() {
  submitting.value = true
  try {
    // resolutions 按 dict {advertiser_id: value} 传（后端契约）
    const resolutions = {}
    for (const c of conflicts.value) {
      const choice = conflictChoices[c.advertiser_id] || 'sheet'
      resolutions[c.advertiser_id] = choice === 'sheet' ? c.sheet_value : c.system_value
    }
    // status_resolutions：只含选「以 Sheet 为准」的状态冲突项
    const statusResolutions = {}
    for (const c of statusConflicts.value) {
      const choice = statusChoices[c.advertiser_id] || 'sheet'
      if (choice === 'sheet') {
        statusResolutions[c.advertiser_id] = c.sheet_status
      }
    }
    const res = await ttAccountsApi.syncFromSheet({ dry_run: false, resolutions,
      status_resolutions: statusResolutions, account_type: accountType.value })
    const createdCount = Array.isArray(res.created) ? res.created.length : (res.created || 0)
    const conflictCount = conflicts.value.length
    const statusCount = Object.keys(statusResolutions).length
    ElMessage.success(`同步完成：新增 ${createdCount} 个账户${conflictCount ? '，处理消耗冲突 ' + conflictCount + ' 条' : ''}${statusCount ? '，变更状态 ' + statusCount + ' 个' : ''}`)
    emit('update:visible', false)
    emit('synced')
  } catch (e) {
    ElMessage.error(e.response?.data?.error || e.message || '同步失败')
  } finally {
    submitting.value = false
  }
}
</script>
