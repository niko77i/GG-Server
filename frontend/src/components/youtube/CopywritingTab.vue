<template>
  <div class="yt-view-tab">
    <!-- 地区标签页 -->
    <div class="region-tabs">
      <button
        v-for="tab in regionTabs"
        :key="tab.region"
        class="region-tab"
        :class="{ active: activeRegion === tab.region }"
        @click="activeRegion = tab.region"
      >
        {{ tab.label }} <span class="region-count">{{ tab.count }}</span>
      </button>
    </div>

    <!-- 工具栏 -->
    <div style="flex-shrink:0;display:flex;gap:8px;margin-bottom:8px;flex-wrap:wrap;align-items:center;">
      <el-radio-group v-if="authStore.isAdmin" v-model="store.cwScope" @change="loadCopywritings" size="small">
        <el-radio-button value="public">公用</el-radio-button>
        <el-radio-button value="private">私有</el-radio-button>
      </el-radio-group>
      <el-button size="small" @click="cwToggleSelectAll">☑ 全选</el-button>
      <el-button size="small" @click="cwInvertSelection">↔ 反选</el-button>
      <el-button size="small" type="danger" @click="cwDeleteSelected">🗑 删除选中</el-button>
      <el-select v-model="cwBatchRegion" @change="val => cwDoBatchEdit(val)" placeholder="批量改地区" size="small" style="width:140px;" clearable filterable>
        <el-option v-for="r in store.tags.regions" :key="r" :label="r" :value="r" />
      </el-select>
      <el-select v-model="cwBatchEff" @change="val => cwDoBatchEffEdit(val)" placeholder="批量改成效" size="small" style="width:140px;" clearable filterable>
        <el-option v-for="e in store.tags.effectiveness" :key="e" :label="e || '(空)'" :value="e" />
      </el-select>
      <span style="font-size:12px;color:#888;margin-left:auto;">已选 {{ cwSelected.length }} 条</span>
    </div>

    <!-- 文案表格（扁平列表，按地区分组排序） -->
    <el-table ref="cwTableRef" :data="filteredCopywritings" row-key="id"
      @selection-change="v => cwSelected = v" stripe size="small"
      class="cw-table">
      <el-table-column type="selection" width="40" />
      <el-table-column label="文案内容" min-width="300">
        <template #default="{ row }">
          <div class="cw-content-cell">
            <div class="cw-content-row">
              <el-tag v-if="row.effectiveness" size="small" :type="row.effectiveness === '成效' ? 'success' : 'warning'" style="margin-right:6px;flex-shrink:0;">{{ row.effectiveness }}</el-tag>
              <el-tag size="small" type="info" style="margin-right:6px;flex-shrink:0;">{{ row.region || '未分类' }}</el-tag>
              <span class="cw-content-text" @click="copyCopywriting(row)" :title="row.content">{{ row.content }}</span>
              <span class="cw-content-actions">
                <el-button link size="small" @click.stop="cwTranslate(row)"
                  :type="cwTransMap[row.id]?.expanded ? 'primary' : 'default'">
                  {{ cwTransMap[row.id]?.expanded ? '翻译 ▲' : '翻译' }}
                </el-button>
                <el-button v-if="canModifyCopywriting(row)" link size="small" @click.stop="cwOpenEdit(row)">✏️</el-button>
                <el-button v-if="canModifyCopywriting(row)" link size="small" type="danger" @click.stop="cwDeleteOne(row)">🗑</el-button>
              </span>
            </div>
            <div v-if="cwTransMap[row.id]?.expanded" class="cw-trans-inline">
              <div class="cw-trans-header">
                <span class="cw-trans-label">🌐 翻译结果</span>
                <el-button link size="small" @click="cwTransMap[row.id].expanded = false">关闭 ✕</el-button>
              </div>
              <div class="cw-trans-body">{{ cwTransMap[row.id].text || '翻译中...' }}</div>
              <div class="cw-trans-footer">
                <el-select v-model="cwTransMap[row.id].target" @change="v => cwTranslate(row, v)" size="small" style="width:120px;" filterable>
                  <el-option v-for="l in CW_LANGS" :key="l.value" :label="l.label" :value="l.value" />
                </el-select>
                <el-button link size="small" @click.stop="cwCopyTrans(row.id)">📋 复制译文</el-button>
              </div>
            </div>
          </div>
        </template>
      </el-table-column>
    </el-table>

    <!-- 文案编辑弹窗 -->
    <el-dialog v-model="cwEditVisible" title="✏️ 编辑文案" width="500px" top="10vh">
      <el-form label-position="top">
        <el-form-item label="地区">
          <el-select v-model="cwEditForm.region" style="width:100%;" filterable>
            <el-option v-for="r in store.tags.regions" :key="r" :label="r" :value="r" />
          </el-select>
        </el-form-item>
        <el-form-item label="成效">
          <el-select v-model="cwEditForm.effectiveness" style="width:100%;" clearable>
            <el-option v-for="e in store.tags.effectiveness" :key="e" :label="e || '(空)'" :value="e" />
          </el-select>
        </el-form-item>
        <el-form-item label="内容">
          <el-input v-model="cwEditForm.content" type="textarea" :rows="4" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="cwEditVisible = false">取消</el-button>
        <el-button type="primary" @click="cwSaveEdit" :loading="cwSavingEdit">💾 保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { useYoutubeStore } from '@/stores/youtube'
import { useAuthStore } from '@/stores/auth'
import { ElMessageBox, ElMessage } from 'element-plus'
import { copyToClipboard } from '@/utils/clipboard'
import { translateApi } from '@/api/youtube'

const store = useYoutubeStore()
const authStore = useAuthStore()

const cwTableRef = ref(null)
const cwSelected = ref([])
const cwBatchRegion = ref('')
const cwBatchEff = ref('')
const cwTransMap = ref({})
const activeRegion = ref('')

const CW_LANGS = [
  { label: '中文', value: 'zh-CN' },
  { label: 'English', value: 'en' },
  { label: '日本語', value: 'ja' },
  { label: '한국어', value: 'ko' },
  { label: 'Português', value: 'pt' },
  { label: 'Español', value: 'es' },
  { label: 'Français', value: 'fr' },
  { label: 'Deutsch', value: 'de' },
  { label: 'Русский', value: 'ru' },
  { label: 'العربية', value: 'ar' },
  { label: 'हिन्दी', value: 'hi' },
  { label: 'ไทย', value: 'th' },
  { label: 'Tiếng Việt', value: 'vi' },
]

function canModifyCopywriting(row) {
  return authStore.isAdmin || row.owner_id === authStore.user?.id || row.is_public
}

// 按地区分组统计（排序与表格一致）
const regionTabs = computed(() => {
  const items = store.copywritings || []
  const map = {}
  items.forEach(item => {
    const r = item.region || '未分类'
    if (!map[r]) map[r] = 0
    map[r]++
  })
  const tabs = Object.keys(map).sort().map(r => ({
    region: r,
    label: r,
    count: map[r],
  }))
  // 全部 tab 插在最前面
  tabs.unshift({ region: '', label: '全部', count: items.length })
  return tabs
})

// 按 activeRegion 过滤，按(地区,内容)排序
const filteredCopywritings = computed(() => {
  const items = store.copywritings || []
  let list = items
  if (activeRegion.value) {
    const target = activeRegion.value === '未分类' ? '' : activeRegion.value
    list = items.filter(item => (item.region || '未分类') === (target || '未分类'))
  }
  // 按（成效优先 → 地区 → 内容）排序
  return [...list].sort((a, b) => {
    const effA = a.effectiveness === '成效' ? 0 : 1
    const effB = b.effectiveness === '成效' ? 0 : 1
    if (effA !== effB) return effA - effB
    const ra = a.region || ''
    const rb = b.region || ''
    if (ra !== rb) return ra.localeCompare(rb)
    return (a.content || '').localeCompare(b.content || '')
  })
})

function cwToggleSelectAll() {
  if (!cwTableRef.value) return
  const list = filteredCopywritings.value
  const sel = new Set(cwSelected.value.map(v => v.id))
  if (sel.size === 0) {
    cwTableRef.value.clearSelection()
  } else if (list.every(l => sel.has(l.id))) {
    cwTableRef.value.clearSelection()
  } else {
    list.forEach(l => cwTableRef.value.toggleRowSelection(l, true))
  }
}

function cwInvertSelection() {
  if (!cwTableRef.value) return
  const list = filteredCopywritings.value
  const sel = new Set(cwSelected.value.map(v => v.id))
  list.forEach(l => {
    if (sel.has(l.id)) cwTableRef.value.toggleRowSelection(l, false)
    else cwTableRef.value.toggleRowSelection(l, true)
  })
}

function copyCopywriting(row) {
  copyToClipboard(row.content).then(() => ElMessage.success('已复制 ✓'))
}

async function cwTranslate(row, targetLang) {
  const cwId = row.id
  if (!cwTransMap.value[cwId]) {
    cwTransMap.value[cwId] = { text: '', target: 'zh-CN', loading: false, expanded: false }
  }
  if (targetLang) cwTransMap.value[cwId].target = targetLang
  if (!cwTransMap.value[cwId].expanded) {
    cwTransMap.value[cwId].expanded = true
  }
  cwTransMap.value[cwId].loading = true
  try {
    const res = await translateApi.translate({ text: row.content, target: cwTransMap.value[cwId].target })
    cwTransMap.value[cwId].text = res.translated
  } catch {
    cwTransMap.value[cwId].text = '翻译失败'
  } finally {
    cwTransMap.value[cwId].loading = false
  }
}

function cwCopyTrans(cwId) {
  const t = cwTransMap.value[cwId]
  if (t?.text) copyToClipboard(t.text).then(() => ElMessage.success('已复制译文 ✓'))
}

const cwEditVisible = ref(false)
const cwEditForm = ref({})
const cwSavingEdit = ref(false)

function cwOpenEdit(row) {
  cwEditForm.value = { id: row.id, region: row.region, effectiveness: row.effectiveness || '', content: row.content }
  cwEditVisible.value = true
}

async function cwSaveEdit() {
  cwSavingEdit.value = true
  try {
    await store.editCopywriting(cwEditForm.value)
    ElMessage.success('已保存 ✓')
    cwEditVisible.value = false
    loadCopywritings()
  } catch (e) {
    ElMessage.error('保存失败')
  } finally {
    cwSavingEdit.value = false
  }
}

async function cwDeleteOne(row) {
  await ElMessageBox.confirm('确定删除此文案？', '确认', { type: 'warning' })
  await store.deleteCopywritings([row.id])
  ElMessage.success('已删除 ✓')
  loadCopywritings()
}

async function cwDeleteSelected() {
  if (!cwSelected.value.length) return
  await ElMessageBox.confirm(`确定删除选中的 ${cwSelected.value.length} 条文案？`, '确认', { type: 'warning' })
  await store.deleteCopywritings(cwSelected.value.map(v => v.id))
  cwSelected.value = []
  loadCopywritings()
}

async function cwDoBatchEdit(region) {
  if (!region || !cwSelected.value.length) return
  await store.batchEditCopywritings({ ids: cwSelected.value.map(v => v.id), region })
  cwBatchRegion.value = ''
  ElMessage.success(`已更新 ${cwSelected.value.length} 条文案地区 ✓`)
  loadCopywritings()
}

async function cwDoBatchEffEdit(effectiveness) {
  if (effectiveness === undefined || effectiveness === null || !cwSelected.value.length) return
  await store.batchEditCopywritings({ ids: cwSelected.value.map(v => v.id), effectiveness })
  cwBatchEff.value = ''
  ElMessage.success(`已更新 ${cwSelected.value.length} 条文案成效 ✓`)
  loadCopywritings()
}

async function loadCopywritings() {
  await store.loadCopywritings()
  const curIds = new Set(store.copywritings.map(c => c.id))
  for (const key of Object.keys(cwTransMap.value)) {
    if (!curIds.has(Number(key))) delete cwTransMap.value[key]
  }
}

onMounted(() => loadCopywritings())

// 供父组件在切换 tab 时调用
defineExpose({ loadCopywritings })
</script>

<style scoped>
/* 地区标签页 */
.region-tabs {
  display: flex;
  gap: 4px;
  margin-bottom: 10px;
  flex-wrap: wrap;
}
.region-tab {
  padding: 5px 14px;
  border: 1px solid #d9d9d9;
  border-radius: 16px;
  background: #fff;
  color: #555;
  font-size: 13px;
  cursor: pointer;
  transition: all .2s;
  white-space: nowrap;
}
.region-tab:hover {
  border-color: var(--el-color-primary);
  color: var(--el-color-primary);
}
.region-tab.active {
  background: var(--el-color-primary);
  border-color: var(--el-color-primary);
  color: #fff;
}
.region-tab.active .region-count {
  background: rgba(255,255,255,.25);
  color: #fff;
}
.region-count {
  display: inline-block;
  margin-left: 4px;
  padding: 0 6px;
  border-radius: 10px;
  background: #f0f0f0;
  font-size: 11px;
  color: #888;
}

.cw-content-cell { padding: 2px 0; }
.cw-content-row { display: flex; align-items: center; gap: 4px; }
.cw-content-text { flex: 1; cursor: pointer; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.cw-content-text:hover { color: var(--el-color-primary); }
.cw-content-actions { flex-shrink: 0; display: flex; gap: 2px; }
.cw-trans-inline { margin-top: 6px; padding: 8px; background: #f8f9fa; border-radius: 4px; }
.cw-trans-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 4px; }
.cw-trans-label { font-size: 12px; color: #888; }
.cw-trans-body { font-size: 13px; white-space: pre-wrap; margin-bottom: 6px; }
.cw-trans-footer { display: flex; gap: 8px; align-items: center; }
</style>
