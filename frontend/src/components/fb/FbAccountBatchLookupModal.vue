<template>
  <el-dialog :model-value="visible" @update:model-value="$emit('update:visible', $event)"
    title="🔍 批量查户" width="800px" @open="init">
    <el-form label-position="top">
      <el-form-item label="账户 ID 列表">
        <el-input v-model="idText" type="textarea" :rows="4"
          placeholder="每行一个账户 ID，自动识别提取&#10;支持格式：10 位以上纯数字 / 含千分位逗号 / 含额外文字的行"
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
            <el-table-column prop="account_id" label="账户 ID" width="160" show-overflow-tooltip />
            <el-table-column prop="name" label="名称" min-width="110" show-overflow-tooltip />
            <el-table-column label="主 BM" min-width="140" show-overflow-tooltip>
              <template #default="{ row }">
                <span v-if="row.bm_name" style="color:#0891b2;">{{ row.bm_name }}</span>
                <span v-else style="color:#888;">未分配</span>
              </template>
            </el-table-column>
            <el-table-column prop="timezone" label="时区" width="90" align="center" show-overflow-tooltip />
            <el-table-column label="状态" width="80" align="center">
              <template #default="{ row }">
                <el-tag size="small" :type="row.status === '死亡' ? 'danger' : row.status === '存活' ? 'success' : row.status === '验证' ? 'warning' : 'info'">
                  {{ row.status || '未知' }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column label="归属人" width="90" align="center" show-overflow-tooltip>
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
import { fbApi } from '@/api/fb'
import { ElMessage } from 'element-plus'

const props = defineProps({ visible: Boolean })
const emit = defineEmits(['update:visible'])

const idText = ref('')
const searching = ref(false)
const result = ref(null)

// ===== ID 提取（FB 广告账户 ID 为 10 位以上纯数字） =====
// 与 GG 版的关键差异：GG 的账户 ID 是 `123-456-7890` 带连字符，
// FB 是纯数字（后端 `batch_create` 亦要求 `aid.isdigit()`）。
// FB 自带的透视表导出里同一串常带千分位逗号（见后端 `_parse_fb_extract` 的 `replace(',', '')`），
// 故这里先剥逗号再取 10 位以上的连续数字。
function extractAccountId(line) {
  const s = line.trim()
  if (!s) return null
  const compact = s.replace(/[\s,]/g, '')
  const m = compact.match(/\d{10,}/)
  return m ? m[0] : null
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

function onIdTextChange() {
  result.value = null
}

// ===== 查询 =====
async function doSearch() {
  if (!parsedIds.value.length) return
  searching.value = true
  result.value = null
  try {
    const res = await fbApi.batchLookup({ account_ids: parsedIds.value })
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
