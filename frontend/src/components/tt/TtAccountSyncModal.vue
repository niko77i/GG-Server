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
      <el-alert type="info" :closable="false" style="margin-bottom:16px;">
        Sheet 中共 <strong>{{ total }}</strong> 条记录
      </el-alert>

      <!-- 新增 -->
      <div v-if="created.length" style="margin-bottom:16px;">
        <h4>🆕 新增账户（{{ created.length }} 条）</h4>
        <el-table :data="created" size="small" border stripe>
          <el-table-column prop="advertiser_id" label="广告账户 ID" min-width="180" show-overflow-tooltip />
          <el-table-column prop="bc" label="BC" width="100" show-overflow-tooltip />
          <el-table-column prop="country" label="国家" width="80" />
          <el-table-column prop="agent" label="代理" width="90" show-overflow-tooltip />
          <el-table-column prop="timezone" label="时区" width="90" />
        </el-table>
      </div>

      <!-- 无变化 -->
      <div v-if="updated.length" style="margin-bottom:16px;">
        <p style="color:#16a34a;">✅ 无变化（{{ updated.length }} 条）</p>
      </div>

      <!-- 消耗情况冲突 -->
      <div v-if="conflicts.length" style="margin-bottom:16px;">
        <h4>⚠️ 消耗情况冲突（{{ conflicts.length }} 条）— 请逐条选择处理方式</h4>
        <el-table :data="conflicts" size="small" border stripe>
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
      </div>

      <!-- 无任何变化 -->
      <div v-if="!created.length && !updated.length && !conflicts.length">
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

const props = defineProps({ visible: Boolean })
const emit = defineEmits(['update:visible', 'synced'])

const loading = ref(false)
const submitting = ref(false)
const error = ref('')
const done = ref(false)
const total = ref(0)
const created = ref([])
const updated = ref([])
const conflicts = ref([])
const conflictChoices = reactive({})

const canSync = computed(() => created.value.length > 0 || conflicts.value.length > 0)

async function startSync() {
  loading.value = true
  error.value = ''
  done.value = false
  total.value = 0
  created.value = []
  updated.value = []
  conflicts.value = []
  for (const k of Object.keys(conflictChoices)) delete conflictChoices[k]
  try {
    const res = await ttAccountsApi.syncFromSheet({ dry_run: true })
    total.value = res.total || 0
    created.value = res.created || []
    updated.value = res.updated || []
    conflicts.value = res.conflicts || []
    for (const c of conflicts.value) {
      conflictChoices[c.advertiser_id] = 'sheet'
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
    const res = await ttAccountsApi.syncFromSheet({ dry_run: false, resolutions })
    const createdCount = Array.isArray(res.created) ? res.created.length : (res.created || 0)
    const conflictCount = conflicts.value.length
    ElMessage.success(`同步完成：新增 ${createdCount} 个账户${conflictCount ? '，处理冲突 ' + conflictCount + ' 条' : ''}`)
    emit('update:visible', false)
    emit('synced')
  } catch (e) {
    ElMessage.error(e.response?.data?.error || e.message || '同步失败')
  } finally {
    submitting.value = false
  }
}
</script>
