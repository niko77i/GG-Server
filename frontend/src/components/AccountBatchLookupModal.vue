<template>
  <el-dialog :model-value="visible" @update:model-value="$emit('update:visible', $event)"
    title="🔍 批量查户" width="900px" @open="init">
    <el-form label-position="top">
      <el-form-item label="账户 ID 列表">
        <el-input v-model="idText" type="textarea" :rows="4"
          placeholder="每行一个账户 ID，自动识别提取&#10;支持格式：123-456-7890 / 1234567890 / 含额外文字的行"
          @input="onIdTextChange" />
      </el-form-item>

      <!-- 解析统计 -->
      <div v-if="parsedIds.length" style="margin-bottom:12px;font-size:13px;color:#666;">
        共识别 <strong>{{ parsedIds.length }}</strong> 个
        <span v-if="invalidIds.length" style="color:#dc2626;margin-left:8px;">✕ {{ invalidIds.length }} 个格式不符</span>
      </div>

      <el-button type="primary" @click="doSearch" :loading="searching"
        :disabled="!parsedIds.length" style="margin-bottom:12px;">
        🔍 查询{{ parsedIds.length ? '（' + parsedIds.length + ' 个）' : '' }}
      </el-button>

      <!-- 查询结果 -->
      <template v-if="result">
        <!-- 找到的 -->
        <div v-if="result.found.length" style="margin-bottom:12px;">
          <div style="font-size:13px;color:#16a34a;margin-bottom:4px;font-weight:600;">
            ✓ 找到 {{ result.found.length }} 个
          </div>
          <el-table :data="result.found" size="small" border stripe max-height="350" style="width:100%;">
            <el-table-column prop="account_id" label="账户 ID" width="130" show-overflow-tooltip />
            <el-table-column prop="name" label="名称" min-width="90" show-overflow-tooltip />
            <el-table-column label="所属 MCC" min-width="100" show-overflow-tooltip>
              <template #default="{ row }">
                <template v-if="row.mcc_name">
                  <span style="color:#0891b2;">{{ row.mcc_name }}</span>
                  <span style="font-size:10px;color:#0891b2;"> · {{ row.mcc_code }}</span>
                </template>
                <span v-else style="color:#888;">未分配</span>
              </template>
            </el-table-column>
            <el-table-column prop="timezone" label="时区" width="75" align="center" />
            <el-table-column prop="agent" label="代理" width="70" align="center" show-overflow-tooltip />
            <el-table-column label="状态" width="70" align="center">
              <template #default="{ row }">
                <el-tag size="small" :type="row.status === '死亡' ? 'danger' : row.status === '存活' ? 'success' : row.status === '验证' ? 'warning' : 'info'">
                  {{ row.status || '未知' }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="acquired_date" label="到手时间" width="105" show-overflow-tooltip />
            <el-table-column prop="owner_name" label="归属人" width="80" align="center" show-overflow-tooltip>
              <template #default="{ row }">
                <el-tag v-if="row.owner_name" size="small" type="warning">{{ row.owner_name }}</el-tag>
                <span v-else style="color:#ccc;">—</span>
              </template>
            </el-table-column>
          </el-table>
        </div>

        <!-- 未找到的 -->
        <div v-if="result.not_found.length">
          <div style="font-size:13px;color:#dc2626;margin-bottom:4px;font-weight:600;">
            ✕ 未找到 {{ result.not_found.length }} 个
          </div>
          <div style="max-height:120px;overflow-y:auto;background:#fef2f2;border:1px solid #fecaca;border-radius:6px;padding:8px;">
            <div v-for="aid in result.not_found" :key="aid" style="font-size:12px;color:#991b1b;line-height:1.8;">
              · {{ aid }}
            </div>
          </div>
        </div>
      </template>
    </el-form>

    <template #footer>
      <el-button @click="$emit('update:visible', false)">关闭</el-button>
    </template>
  </el-dialog>
</template>

<script setup>
import { ref, computed } from 'vue'
import { accountsApi } from '@/api/accounts'
import { ElMessage } from 'element-plus'

const props = defineProps({ visible: Boolean })
const emit = defineEmits(['update:visible'])

const idText = ref('')
const searching = ref(false)
const result = ref(null)

const ID_PATTERN = /^\d{3}-\d{3}-\d{4}$/

// ===== ID 提取（与批量导入共用逻辑） =====
function extractAccountId(line) {
  const s = line.trim()
  if (!s) return null
  if (ID_PATTERN.test(s)) return s
  const m = s.match(/\d{3}-\d{3}-\d{4}/)
  if (m) return m[0]
  const digits = s.replace(/\D/g, '')
  if (digits.length === 10) {
    return `${digits.slice(0, 3)}-${digits.slice(3, 6)}-${digits.slice(6, 10)}`
  }
  const m10 = s.match(/\d{10}/)
  if (m10) {
    const d = m10[0]
    return `${d.slice(0, 3)}-${d.slice(3, 6)}-${d.slice(6, 10)}`
  }
  return null
}

const parsedIds = computed(() => {
  if (!idText.value.trim()) return []
  const seen = new Set()
  const result = []
  for (const raw of idText.value.split(/[\n]+/)) {
    const line = raw.trim()
    if (!line) continue
    const id = extractAccountId(line)
    if (id && !seen.has(id)) { seen.add(id); result.push(id) }
  }
  return result
})

const invalidIds = computed(() => {
  if (!idText.value.trim()) return []
  return idText.value.split(/[\n]+/).map(s => s.trim()).filter(s => s && !extractAccountId(s))
})

// ===== 防抖提示（仅用于 UX，无实际请求） =====
let parseTimer = null
function onIdTextChange() {
  clearTimeout(parseTimer)
  result.value = null
}

// ===== 查询 =====
async function doSearch() {
  if (!parsedIds.value.length) return
  searching.value = true
  result.value = null
  try {
    const res = await accountsApi.batchLookup(parsedIds.value)
    result.value = { found: res.found || [], not_found: res.not_found || [] }
  } catch (e) {
    ElMessage.error('查询失败：' + (e.response?.data?.error || e.message))
  } finally {
    searching.value = false
  }
}

// ===== 初始化 =====
function init() {
  idText.value = ''
  result.value = null
}
</script>
