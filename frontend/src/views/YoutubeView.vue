<template>
  <div class="yt-root">
    <h1>视频 文案管理</h1>
    <div class="sticky-tabs">
      <el-tabs :model-value="activeTab" @update:model-value="switchTab">
        <el-tab-pane label="Youtube视频展示" name="view" />
        <el-tab-pane label="文案展示" name="copywriting" />
        <el-tab-pane label="导入视频或文案" name="import" />
        <el-tab-pane label="标签配置" name="config" />
      </el-tabs>
    </div>

    <!-- ===== 视频展示 ===== -->
    <div v-show="activeTab === 'view'" class="yt-view-tab">
      <div style="flex-shrink:0;">
        <div style="display:flex;gap:8px;margin-bottom:8px;flex-wrap:wrap;">
          <el-select v-model="store.filters.region" @change="loadVideos" placeholder="全部地区" clearable size="small" style="flex:1;min-width:110px;">
            <el-option v-for="r in store.tags.regions" :key="r" :label="r + ' (' + (store.counts.region?.[r] || 0) + ')'" :value="r" />
          </el-select>
          <el-select v-model="store.filters.frame_type" @change="loadVideos" placeholder="全部帧类型" clearable size="small" style="flex:1;min-width:110px;">
            <el-option v-for="f in store.tags.frame_types" :key="f" :label="f + ' (' + (store.counts.frame_type?.[f] || 0) + ')'" :value="f" />
          </el-select>
          <el-select v-model="store.filters.effectiveness" @change="loadVideos" placeholder="全部成效" clearable size="small" style="flex:1;min-width:110px;">
            <el-option v-for="e in store.tags.effectiveness" :key="e" :label="e + ' (' + (store.counts.effectiveness?.[e] || 0) + ')'" :value="e" />
          </el-select>
          <el-select v-model="store.filters.product_name" @change="loadVideos" placeholder="全部产品" clearable size="small" style="flex:1;min-width:110px;">
            <el-option v-for="p in store.tags.product_names" :key="p" :label="p + ' (' + (store.counts.product_name?.[p] || 0) + ')'" :value="p" />
          </el-select>
          <el-select v-model="store.filters.review_status" @change="loadVideos" placeholder="审核状态" size="small" style="flex:1;min-width:110px;">
            <el-option label="全部" value="全部" />
            <el-option v-for="s in store.tags.review_statuses" :key="s" :label="s + ' (' + (store.counts.review_status?.[s] || 0) + ')'" :value="s" />
          </el-select>
          <el-date-picker v-model="dateRange" type="daterange" range-separator="~" start-placeholder="开始" end-placeholder="结束"
            size="small" value-format="YYYY-MM-DD" popper-class="yt-date-picker" :cell-class-name="dateCellClass" @change="onDateChange" style="width:210px;flex-shrink:0;" />
        </div>

        <div style="display:flex;gap:8px;margin-bottom:8px;align-items:center;flex-wrap:wrap;">
          <el-button size="small" @click="toggleSelectAll">☑ 全选</el-button>
          <el-button size="small" @click="invertSelection">↔ 反选</el-button>
          <el-button size="small" @click="selectUncopied">📋 选未复制</el-button>
          <el-button size="small" type="primary" @click="copySelectedLinks">📋 复制选中</el-button>
          <el-button v-if="copiedCount" size="small" @click="clearCopied">✕ 清除复制 ({{ copiedCount }})</el-button>
          <el-input v-model="searchText" placeholder="搜索链接或标题..." style="flex:1;min-width:160px;" size="small" clearable />
          <span style="font-size:12px;color:#888;">已选 {{ selected.length }} 条</span>
          <el-button size="small" type="danger" @click="deleteSelected">🗑 删除选中</el-button>
        </div>

        <!-- 批量编辑工具栏 -->
        <div v-if="selected.length" style="display:flex;gap:8px;margin-bottom:8px;align-items:center;flex-wrap:wrap;">
          <span style="font-size:12px;color:#666;">批量修改：</span>
          <el-select v-model="batchRegion" @change="val => doBatchEdit('region', val)" placeholder="地区..." size="small" style="width:110px;" clearable filterable>
            <el-option v-for="r in store.tags.regions" :key="r" :label="r" :value="r" />
          </el-select>
          <el-select v-model="batchFrame" @change="val => doBatchEdit('frame_type', val)" placeholder="帧类型..." size="small" style="width:120px;" clearable filterable>
            <el-option v-for="f in store.tags.frame_types" :key="f" :label="f" :value="f" />
          </el-select>
          <el-select v-model="batchEff" @change="val => doBatchEdit('effectiveness', val)" placeholder="成效..." size="small" style="width:110px;" clearable filterable>
            <el-option v-for="e in store.tags.effectiveness" :key="e" :label="e" :value="e" />
          </el-select>
          <el-select v-model="batchProd" @change="val => doBatchEdit('product_name', val)" placeholder="产品名..." size="small" style="width:120px;" clearable filterable>
            <el-option v-for="p in store.tags.product_names" :key="p" :label="p" :value="p" />
          </el-select>
          <el-select v-model="batchReview" @change="val => doBatchEdit('review_status', val)" placeholder="审核..." size="small" style="width:110px;" clearable filterable>
            <el-option v-for="s in store.tags.review_statuses" :key="s" :label="s" :value="s" />
          </el-select>
        </div>
      </div>

      <div class="yt-main">
        <div class="yt-list-col">
          <el-table ref="ytTableRef" :data="pagedVideos" @selection-change="v => selected = v" stripe size="small"
            highlight-current-row @row-click="onRowClick">
            <el-table-column type="selection" width="48" />
            <el-table-column label="标题" min-width="200">
              <template #default="{ row }">
                <div class="video-title-cell">
                  <div class="video-title-text" @click.stop="playVideo(row)">{{ row.title }}</div>
                  <div class="video-title-meta">
                    <el-tag size="small" type="warning" v-if="row.region">{{ row.region }}</el-tag>
                    <el-tag size="small" v-if="row.frame_type">{{ row.frame_type }}</el-tag>
                    <el-tag size="small" v-if="row.effectiveness" type="success">{{ row.effectiveness }}</el-tag>
                    <el-tag size="small" v-if="row.product_name" type="info">{{ row.product_name }}</el-tag>
                    <el-tag size="small" v-if="row.review_status" :type="row.review_status === '不能过审' ? 'danger' : 'success'">{{ row.review_status }}</el-tag>
                    <span v-if="copiedIds[row.id]" style="font-size:10px;color:#059669;">已复制</span>
                    <span class="video-time">{{ row.imported_at }}</span>
                  </div>
                </div>
              </template>
            </el-table-column>
            <el-table-column width="54" align="center" class-name="yt-actions-col">
              <template #default="{ row }">
                <el-popover trigger="click" placement="bottom" :width="140" :teleported="true" :show-arrow="false">
                  <template #reference>
                    <el-button size="small" circle @click.stop style="width:26px;height:26px;padding:0;font-weight:700;">⋯</el-button>
                  </template>
                  <div style="display:flex;flex-direction:column;gap:2px;">
                    <el-button link size="small" @click.stop="copyLink(row.id)" style="justify-content:flex-start;">📋 复制链接</el-button>
                    <el-button link size="small" type="primary" @click.stop="openEdit(row)" style="justify-content:flex-start;">✏️ 编辑</el-button>
                  </div>
                </el-popover>
              </template>
            </el-table-column>
          </el-table>
          <div style="display:flex;align-items:center;justify-content:space-between;margin-top:6px;">
            <el-pagination v-if="filteredVideos.length > ytPageSize"
              v-model:current-page="ytPage" :page-size="ytPageSize" :total="filteredVideos.length" background
              layout="prev,pager,next" size="small" :pager-count="7" />
            <el-select v-model="ytPageSize" size="small" style="width:90px;margin-left:auto;">
              <el-option v-for="s in [10,20,50,100]" :key="s" :label="s+'条/页'" :value="s" />
            </el-select>
          </div>
        </div>
        <div class="yt-player-col">
          <iframe v-if="playingId" :src="'https://www.youtube.com/embed/' + playingId"
            style="width:100%;aspect-ratio:16/9;border:0;border-radius:8px;" allowfullscreen />
          <div v-else style="width:100%;aspect-ratio:16/9;background:#f0f2f5;display:flex;align-items:center;justify-content:center;color:#999;border-radius:8px;">
            点击左侧视频播放
          </div>
          <div v-if="playingId" style="margin-top:8px;font-size:12px;color:#666;">
            {{ playingTitle }}
            <el-button link size="small" @click="copyLink(playingId)">复制链接</el-button>
          </div>
        </div>
      </div>
    </div>

    <!-- ===== 文案展示 ===== -->
    <div v-show="activeTab === 'copywriting'" class="yt-view-tab">
      <div style="flex-shrink:0;display:flex;gap:8px;margin-bottom:8px;flex-wrap:wrap;align-items:center;">
        <el-button size="small" @click="cwToggleSelectAll">☑ 全选</el-button>
        <el-button size="small" @click="cwInvertSelection">↔ 反选</el-button>
        <el-button size="small" type="danger" @click="cwDeleteSelected">🗑 删除选中</el-button>
        <el-select v-model="cwBatchRegion" @change="val => cwDoBatchEdit(val)" placeholder="批量改地区" size="small" style="width:140px;" clearable filterable>
          <el-option v-for="r in store.tags.regions" :key="r" :label="r" :value="r" />
        </el-select>
        <span style="font-size:12px;color:#888;margin-left:auto;">已选 {{ cwSelected.length }} 条</span>
      </div>

      <el-table ref="cwTableRef" :data="copywritingTree" row-key="id"
        :tree-props="{ children: 'children', hasChildren: 'hasChildren' }"
        default-expand-all :selectable="cwSelectable" :indent="28"
        :row-class-name="cwRowClass"
        @selection-change="v => cwSelected = v" stripe size="small"
        class="cw-table">
        <el-table-column type="selection" width="40" />
        <el-table-column label="文案内容" min-width="300">
          <template #default="{ row }">
            <div v-if="!row.isRegion" class="cw-content-cell">
              <div class="cw-content-row">
                <span class="cw-content-text" @click="copyCopywriting(row)" :title="row.content">{{ row.content }}</span>
                <span class="cw-content-actions">
                  <el-button link size="small" @click.stop="cwTranslate(row)"
                    :type="cwTransMap[row.id]?.expanded ? 'primary' : 'default'">
                    {{ cwTransMap[row.id]?.expanded ? '翻译 ▲' : '翻译' }}
                  </el-button>
                  <el-button link size="small" @click.stop="cwOpenEdit(row)">✏️</el-button>
                  <el-button link size="small" type="danger" @click.stop="cwDeleteOne(row)">🗑</el-button>
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
            <span v-else class="cw-region-name">{{ row.name }}</span>
          </template>
        </el-table-column>
      </el-table>
    </div>

    <!-- ===== 导入视频或文案 ===== -->
    <div v-show="activeTab === 'import'" style="max-width:600px;">
      <el-tabs v-model="importSubTab" size="small" style="margin-bottom:12px;">
        <el-tab-pane label="导入视频" name="video" />
        <el-tab-pane label="导入文案" name="copywriting" />
      </el-tabs>

      <div v-show="importSubTab === 'video'">
        <el-input v-model="importUrls" type="textarea" :rows="6" placeholder="每行一个 YouTube 链接..." />
        <div style="display:grid;grid-template-columns:repeat(5,1fr);gap:8px;margin-top:12px;">
          <el-select v-model="importRegion" placeholder="地区" size="small">
            <el-option v-for="r in store.tags.regions" :key="r" :label="r" :value="r" />
          </el-select>
          <el-select v-model="importFrame" placeholder="帧类型" size="small">
            <el-option v-for="f in store.tags.frame_types" :key="f" :label="f" :value="f" />
          </el-select>
          <el-select v-model="importEff" placeholder="成效" size="small" clearable>
            <el-option v-for="e in store.tags.effectiveness" :key="e" :label="e" :value="e" />
          </el-select>
          <el-select v-model="importProd" placeholder="产品名" size="small" clearable>
            <el-option v-for="p in store.tags.product_names" :key="p" :label="p" :value="p" />
          </el-select>
          <el-select v-model="importReview" placeholder="审核" size="small">
            <el-option v-for="s in store.tags.review_statuses" :key="s" :label="s" :value="s" />
          </el-select>
        </div>
        <el-button type="primary" @click="doImport" :loading="importing" style="margin-top:12px;">保存视频</el-button>
        <div v-if="importResult" style="margin-top:8px;font-size:12px;">{{ importResult }}</div>
      </div>

      <div v-show="importSubTab === 'copywriting'">
        <el-select v-model="cwImportRegion" placeholder="地区" size="small" style="width:100%;margin-bottom:12px;">
          <el-option v-for="r in store.tags.regions" :key="r" :label="r" :value="r" />
        </el-select>
        <el-input v-model="cwImportText" type="textarea" :rows="8" placeholder="每行一条文案，空行自动跳过" />
        <el-button type="primary" @click="cwDoImport" :loading="cwImporting" style="margin-top:12px;">导入文案</el-button>
        <div v-if="cwImportResult" style="margin-top:8px;font-size:12px;">{{ cwImportResult }}</div>
      </div>
    </div>

    <!-- ===== 标签配置 ===== -->
    <div v-show="activeTab === 'config'" style="max-width:600px;">
      <div style="display:grid;grid-template-columns:1fr 1fr;gap:12px;">
        <el-form-item label="地区选项"><el-input v-model="cfgRegions" type="textarea" :rows="5" /></el-form-item>
        <el-form-item label="帧类型选项"><el-input v-model="cfgFrames" type="textarea" :rows="5" /></el-form-item>
      </div>
      <el-form-item label="成效选项"><el-input v-model="cfgEffs" type="textarea" :rows="3" /></el-form-item>
      <el-form-item label="产品名称选项"><el-input v-model="cfgProds" type="textarea" :rows="3" /></el-form-item>
      <el-form-item label="审核状态选项"><el-input v-model="cfgReviewStatuses" type="textarea" :rows="3" /></el-form-item>
      <el-button type="primary" @click="saveConfig" :loading="savingCfg">保存配置</el-button>
      <span v-if="cfgMsg" style="margin-left:8px;font-size:11px;color:#059669;">{{ cfgMsg }}</span>
    </div>

    <!-- ===== 文案编辑弹窗 ===== -->
    <el-dialog v-model="cwEditVisible" title="✏️ 编辑文案" width="500px" top="10vh">
      <el-form label-position="top">
        <el-form-item label="地区">
          <el-select v-model="cwEditForm.region" style="width:100%;" filterable>
            <el-option v-for="r in store.tags.regions" :key="r" :label="r" :value="r" />
          </el-select>
        </el-form-item>
        <el-form-item label="文案内容">
          <el-input v-model="cwEditForm.content" type="textarea" :rows="4" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="cwEditVisible = false">取消</el-button>
        <el-button type="primary" @click="cwSaveEdit" :loading="cwSavingEdit">💾 保存</el-button>
      </template>
    </el-dialog>

    <!-- ===== 视频编辑弹窗 ===== -->
    <el-dialog v-model="editVisible" title="✏️ 编辑视频" width="450px" top="10vh">
      <el-form label-position="top">
        <el-form-item label="地区">
          <el-select v-model="editForm.region" style="width:100%;" filterable>
            <el-option v-for="r in store.tags.regions" :key="r" :label="r" :value="r" />
          </el-select>
        </el-form-item>
        <el-form-item label="帧类型">
          <el-select v-model="editForm.frame_type" style="width:100%;" filterable>
            <el-option v-for="f in store.tags.frame_types" :key="f" :label="f" :value="f" />
          </el-select>
        </el-form-item>
        <el-form-item label="成效">
          <el-select v-model="editForm.effectiveness" style="width:100%;" filterable clearable>
            <el-option v-for="e in store.tags.effectiveness" :key="e" :label="e" :value="e" />
          </el-select>
        </el-form-item>
        <el-form-item label="产品名">
          <el-select v-model="editForm.product_name" style="width:100%;" filterable clearable>
            <el-option v-for="p in store.tags.product_names" :key="p" :label="p" :value="p" />
          </el-select>
        </el-form-item>
        <el-form-item label="审核状态">
          <el-select v-model="editForm.review_status" style="width:100%;" filterable>
            <el-option v-for="s in store.tags.review_statuses" :key="s" :label="s" :value="s" />
          </el-select>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="editVisible = false">取消</el-button>
        <el-button type="primary" @click="saveEdit" :loading="savingEdit">💾 保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, watch } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { useYoutubeStore } from '@/stores/youtube'
import { ElMessageBox, ElMessage } from 'element-plus'
import { copyToClipboard } from '@/utils/clipboard'
import { translateApi } from '@/api/youtube'

const router = useRouter()
const route = useRoute()
const store = useYoutubeStore()

const activeTab = computed(() => {
  if (route.path.includes('/copywriting')) return 'copywriting'
  if (route.path.includes('/import')) return 'import'
  if (route.path.includes('/config')) return 'config'
  return 'view'
})
function switchTab(name) { router.push(`/youtube/${name}`) }

// View tab
const searchText = ref('')
const selected = ref([])
const playingId = ref('')
const playingTitle = ref('')
const ytPage = ref(1)
const ytPageSize = ref(20)
const ytTableRef = ref(null)
const copiedIds = ref(JSON.parse(localStorage.getItem('ytCopied')||'{}'))
const copiedCount = computed(()=>Object.keys(copiedIds.value).length)

function toggleSelectAll(){const t=ytTableRef.value;if(!t)return;const ids=pagedVideos.value.map(v=>v.id);const sel=selected.value.map(v=>v.id);const all=ids.every(id=>sel.includes(id));if(all)t.clearSelection();else pagedVideos.value.forEach(v=>t.toggleRowSelection(v,true))}
function invertSelection(){const t=ytTableRef.value;if(!t)return;const sel=new Set(selected.value.map(v=>v.id));pagedVideos.value.forEach(v=>{if(sel.has(v.id))t.toggleRowSelection(v,false);else t.toggleRowSelection(v,true)})}
function selectUncopied(){const t=ytTableRef.value;if(!t)return;pagedVideos.value.forEach(v=>t.toggleRowSelection(v,!!(!copiedIds.value[v.id])))}

const filteredVideos = computed(() => {
  if (!searchText.value) return store.videos
  const q = searchText.value.toLowerCase()
  return store.videos.filter(v => (v.title || '').toLowerCase().includes(q) || (v.id || '').toLowerCase().includes(q))
})

const pagedVideos = computed(() => {
  const start = (ytPage.value - 1) * ytPageSize.value
  return filteredVideos.value.slice(start, start + ytPageSize.value)
})

const dateRange = ref(null)

// 日期格子标记：有视频的日期加 has-video 类名
const dateSet = computed(() => new Set(Object.keys(store.videoDates)))
function dateCellClass(date) {
  const y = date.getFullYear()
  const m = String(date.getMonth() + 1).padStart(2, '0')
  const d = String(date.getDate()).padStart(2, '0')
  return dateSet.value.has(`${y}-${m}-${d}`) ? 'has-video' : ''
}

// 搜索文本变化时重置页码
watch(searchText, () => { ytPage.value = 1 })

function onDateChange(val) {
  store.filters.from_date = val ? val[0] : ''
  store.filters.to_date = val ? val[1] : ''
  loadVideos()
}

async function loadVideos() {
  ytPage.value = 1
  await store.loadVideos()
  store.loadDates(store.filters) // 同步刷新日期标记（与当前筛选联动）
}

onMounted(async () => {
  await store.loadTags()
  store.loadDates(store.filters) // 预加载视频日期分布，供日期选择器标记
  await loadVideos()
  cfgRegions.value = (store.tags.regions || []).join('\n')
  cfgFrames.value = (store.tags.frame_types || []).join('\n')
  cfgEffs.value = (store.tags.effectiveness || []).filter(Boolean).join('\n')
  cfgProds.value = (store.tags.product_names || []).join('\n')
  cfgReviewStatuses.value = (store.tags.review_statuses || []).join('\n')
})

function onRowClick(row) {
  if (ytTableRef.value) ytTableRef.value.toggleRowSelection(row)
}
function playVideo(row) {
  playingId.value = row.id
  playingTitle.value = row.title
}

function copyLink(id){const url=`https://www.youtube.com/watch?v=${id}`;copyToClipboard(url).then(()=>{ElMessage.success('已复制 ✓');copiedIds.value={...copiedIds.value,[id]:Date.now()};localStorage.setItem('ytCopied',JSON.stringify(copiedIds.value))})}
function clearCopied(){copiedIds.value={};localStorage.removeItem('ytCopied');ElMessage.success('已清除复制记录')}
function handleRowAction(cmd, row) { if (cmd === 'copy') copyLink(row.id); else if (cmd === 'edit') openEdit(row) }

async function copySelectedLinks(){if(!selected.value.length)return;const links=selected.value.map(v=>`https://www.youtube.com/watch?v=${v.id}`).join('\n');await copyToClipboard(links);const now=Date.now();const u={...copiedIds.value};selected.value.forEach(v=>{u[v.id]=now});copiedIds.value=u;localStorage.setItem('ytCopied',JSON.stringify(u));ElMessage.success(`已复制 ${selected.value.length} 个链接 ✓`)}

async function deleteSelected() {
  if (!selected.value.length) return
  await ElMessageBox.confirm(`确定删除选中的 ${selected.value.length} 个视频？`, '确认', { type: 'warning' })
  await store.deleteVideos(selected.value.map(v => v.id))
  selected.value = []
}

// Edit dialog
const editVisible = ref(false)
const editForm = ref({})
const savingEdit = ref(false)

function openEdit(row) {
  editForm.value = {
    id: row.id,
    region: row.region || '',
    frame_type: row.frame_type || '',
    effectiveness: row.effectiveness || '',
    product_name: row.product_name || '',
    review_status: row.review_status || '能过审',
  }
  editVisible.value = true
}

async function saveEdit() {
  savingEdit.value = true
  try {
    await store.editVideo(editForm.value)
    ElMessage.success('已保存 ✓')
    editVisible.value = false
    loadVideos()
  } catch (e) {
    ElMessage.error('保存失败：' + (e.message || '未知错误'))
  } finally {
    savingEdit.value = false
  }
}

// Batch edit
const batchRegion = ref('')
const batchFrame = ref('')
const batchEff = ref('')
const batchProd = ref('')
const batchReview = ref('')

async function doBatchEdit(field, val) {
  if (!val || !selected.value.length) return
  try {
    await store.batchEditVideos({ ids: selected.value.map(v => v.id), field, value: val })
    ElMessage.success(`已批量更新 ${selected.value.length} 个视频 ✓`)
  } catch (e) {
    ElMessage.error('批量更新失败：' + (e.message || '未知错误'))
  }
  // Reset dropdown
  if (field === 'region') batchRegion.value = ''
  else if (field === 'frame_type') batchFrame.value = ''
  else if (field === 'effectiveness') batchEff.value = ''
  else if (field === 'product_name') batchProd.value = ''
  else if (field === 'review_status') batchReview.value = ''
  loadVideos()
}

// Import tab
const importUrls = ref('')
const importRegion = ref('通用')
const importFrame = ref('非融帧')
const importEff = ref('')
const importProd = ref('')
const importReview = ref('能过审')
const importing = ref(false)
const importResult = ref('')

async function doImport() {
  const urls = importUrls.value.split(/[\n,]+/).map(s => s.trim()).filter(s => s && s.includes('youtu'))
  if (!urls.length) return
  importing.value = true
  const res = await store.importVideos({ urls, region: importRegion.value, frame_type: importFrame.value, effectiveness: importEff.value, product_name: importProd.value, review_status: importReview.value })
  importResult.value = `导入 ${res.imported} 个，重复 ${(res.duplicates || []).length} 个`
  importUrls.value = ''
  importing.value = false
  loadVideos()
}

// Config tab
const cfgRegions = ref(''); const cfgFrames = ref(''); const cfgEffs = ref(''); const cfgProds = ref(''); const cfgReviewStatuses = ref('')
const savingCfg = ref(false); const cfgMsg = ref('')

async function saveConfig() {
  savingCfg.value = true
  await store.saveTags({
    regions: cfgRegions.value.split('\n').map(s => s.trim()).filter(Boolean),
    frame_types: cfgFrames.value.split('\n').map(s => s.trim()).filter(Boolean),
    effectiveness: cfgEffs.value.split('\n').map(s => s.trim()).filter(Boolean),
    product_names: cfgProds.value.split('\n').map(s => s.trim()).filter(Boolean),
    review_statuses: cfgReviewStatuses.value.split('\n').map(s => s.trim()).filter(Boolean),
  })
  await store.loadTags()
  cfgMsg.value = '已保存'
  setTimeout(() => cfgMsg.value = '', 2000)
  savingCfg.value = false
}

// ---- 文案管理 ----
const cwTableRef = ref(null)
const cwSelected = ref([])
const cwImportText = ref('')
const cwImportRegion = ref('通用')
const cwImporting = ref(false)
const cwImportResult = ref('')
const cwBatchRegion = ref('')
const cwTransMap = ref({})

const CW_LANGS = [
  { label: '中文', value: 'zh-CN' },
  { label: '英语', value: 'en' },
  { label: '葡萄牙语', value: 'pt' },
  { label: '印尼语', value: 'id' },
  { label: '菲律宾语', value: 'tl' },
  { label: '西班牙语', value: 'es' },
  { label: '日语', value: 'ja' },
  { label: '韩语', value: 'ko' },
  { label: '泰语', value: 'th' },
  { label: '越南语', value: 'vi' },
]

const copywritingTree = computed(() => {
  const groups = {}
  for (const cw of store.copywritings) {
    const r = cw.region || '通用'
    if (!groups[r]) groups[r] = []
    groups[r].push(cw)
  }
  const tree = []
  for (const [region, items] of Object.entries(groups)) {
    const regionId = `region-${region}`
    tree.push({
      id: regionId,
      name: `${region} (${items.length}条)`,
      isRegion: true,
      hasChildren: true,
      children: items.map(cw => ({
        ...cw,
        isRegion: false,
        hasChildren: false,
        children: [],
      })),
    })
  }
  return tree
})

function cwSelectable(row) {
  return !row.isRegion
}

function cwRowClass({ row }) {
  return row.isRegion ? 'cw-row-region' : 'cw-row-item'
}

function cwToggleSelectAll() {
  if (!cwTableRef.value) return
  const leafs = copywritingTree.value.flatMap(r => r.children || [])
  const sel = new Set(cwSelected.value.map(v => v.id))
  const all = leafs.every(l => sel.has(l.id))
  if (all) {
    cwTableRef.value.clearSelection()
  } else {
    leafs.forEach(l => cwTableRef.value.toggleRowSelection(l, true))
  }
}

function cwInvertSelection() {
  if (!cwTableRef.value) return
  const leafs = copywritingTree.value.flatMap(r => r.children || [])
  const sel = new Set(cwSelected.value.map(v => v.id))
  leafs.forEach(l => {
    if (sel.has(l.id)) cwTableRef.value.toggleRowSelection(l, false)
    else cwTableRef.value.toggleRowSelection(l, true)
  })
}

function copyCopywriting(row) {
  copyToClipboard(row.content).then(() => ElMessage.success('已复制 ✓'))
}

async function cwTranslate(row, targetLang) {
  const cwId = row.id
  const target = targetLang || 'zh-CN'
  if (!cwTransMap.value[cwId]) {
    cwTransMap.value[cwId] = { text: '', target: 'zh-CN', loading: false, expanded: false }
  }
  cwTransMap.value[cwId].target = target
  // 如果已展开，切换语言时重新翻译；否则展开
  if (!cwTransMap.value[cwId].expanded) {
    cwTransMap.value[cwId].expanded = true
  }
  cwTransMap.value[cwId].loading = true
  try {
    const res = await translateApi.translate({ text: row.content, target })
    cwTransMap.value[cwId].text = res.translated
  } catch (e) {
    ElMessage.error('翻译失败：' + (e.message || '未知错误'))
  } finally {
    cwTransMap.value[cwId].loading = false
  }
}

function cwCopyTrans(cwId) {
  const t = cwTransMap.value[cwId]
  if (t && t.text) {
    copyToClipboard(t.text).then(() => ElMessage.success('已复制译文 ✓'))
  }
}

// 编辑
const cwEditVisible = ref(false)
const cwEditForm = ref({})
const cwSavingEdit = ref(false)

function cwOpenEdit(row) {
  cwEditForm.value = { id: row.id, region: row.region, content: row.content }
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
    ElMessage.error('保存失败：' + (e.message || '未知错误'))
  } finally {
    cwSavingEdit.value = false
  }
}

// 删除
async function cwDeleteOne(row) {
  await ElMessageBox.confirm('确定删除该文案？', '确认', { type: 'warning' })
  await store.deleteCopywritings([row.id])
  ElMessage.success('已删除')
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

// 导入
async function cwDoImport() {
  const text = cwImportText.value.trim()
  if (!text) return
  cwImporting.value = true
  try {
    const res = await store.importCopywritings({ text, region: cwImportRegion.value })
    cwImportResult.value = `导入 ${res.imported} 条`
    cwImportText.value = ''
    loadCopywritings()
  } catch (e) {
    ElMessage.error('导入失败：' + (e.message || '未知错误'))
  } finally {
    cwImporting.value = false
  }
}

const importSubTab = ref('video')

async function loadCopywritings() {
  await store.loadCopywritings()
  // 清除翻译缓存中已不存在的
  const curIds = new Set(store.copywritings.map(c => c.id))
  for (const key of Object.keys(cwTransMap.value)) {
    if (!curIds.has(Number(key))) delete cwTransMap.value[key]
  }
}

// 每次切换到文案 tab 都刷新（包括首次）
watch(activeTab, async (tab) => {
  if (tab === 'copywriting') await loadCopywritings()
}, { immediate: true })
</script>

<style scoped>
.yt-root { display: flex; flex-direction: column; height: calc(100vh - 72px); }
.yt-view-tab { flex: 1; min-height: 0; display: flex; flex-direction: column; overflow: hidden; }

.yt-main { flex: 1; min-height: 0; display: flex; gap: 16px; }
.yt-list-col { width: 440px; flex-shrink: 0; display: flex; flex-direction: column; min-height: 0; }
.yt-player-col { flex: 1; min-width: 280px; }

.yt-list-col :deep(.el-table) { flex: 1; min-height: 0; }
.yt-list-col :deep(.el-table__inner-wrapper) { height: 100%; display: flex; flex-direction: column; }
.yt-list-col :deep(.el-table__body-wrapper) { flex: 1; overflow-y: auto; }

/* 勾选列：让点击区域撑满整个单元格 */
.yt-list-col :deep(.el-table-column--selection .cell) { padding: 0 !important; display: flex; align-items: center; justify-content: center; }
.yt-list-col :deep(.el-table-column--selection .el-checkbox) { width: 100%; height: 100%; display: flex; align-items: center; justify-content: center; }
.yt-list-col :deep(.el-table-column--selection .el-checkbox__label) { display: none; }

/* 视频标题单元格 */
.video-title-cell { display: flex; flex-direction: column; gap: 5px; padding: 2px 0; }
.video-title-text { line-height: 1.4; display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; word-break: break-word; font-weight: 500; cursor: pointer; }
.video-title-meta { display: flex; align-items: center; flex-wrap: wrap; gap: 3px; }
.video-time { font-size: 10px; color: #aaa; margin-left: auto; white-space: nowrap; }

/* 让操作列按钮不被单元格裁剪 */
:deep(.yt-actions-col) { overflow: visible !important; }
:deep(.yt-actions-col .cell) { overflow: visible !important; }

/* 文案表格 */
.cw-table { flex: 1; min-height: 0; }
.cw-table :deep(.el-table__inner-wrapper) { height: 100%; display: flex; flex-direction: column; }
.cw-table :deep(.el-table__body-wrapper) { flex: 1; overflow-y: auto; }

/* 地区父节点 */
.cw-region-name { font-weight: 700; font-size: 14px; color: #303133; }

/* 文案内容行 */
.cw-content-cell { display: flex; flex-direction: column; gap: 6px; padding: 4px 0; }
.cw-content-row { display: flex; align-items: flex-start; gap: 8px; }
.cw-content-text { flex: 1; font-size: 13px; line-height: 1.6; cursor: pointer; word-break: break-word; }
.cw-content-text:hover { color: #409eff; }
.cw-content-actions { flex-shrink: 0; display: flex; gap: 2px; align-items: center; }
.cw-content-actions .el-button { font-size: 12px; }

/* 翻译内联展开 */
.cw-trans-inline { margin-top: 2px; padding: 10px 12px; background: linear-gradient(135deg, #f0f9eb 0%, #ecfdf5 100%); border: 1px solid #d1fae5; border-radius: 8px; border-left: 3px solid #10b981; }
.cw-trans-header { display: flex; align-items: center; justify-content: space-between; margin-bottom: 6px; }
.cw-trans-label { font-size: 12px; font-weight: 600; color: #059669; }
.cw-trans-body { font-size: 14px; color: #065f46; line-height: 1.7; word-break: break-word; white-space: pre-wrap; }
.cw-trans-footer { display: flex; align-items: center; gap: 8px; margin-top: 8px; padding-top: 6px; border-top: 1px solid #d1fae5; }

/* 勾选列撑满 */
.cw-table :deep(.el-table-column--selection .cell) { padding: 0 !important; display: flex; align-items: center; justify-content: center; }
.cw-table :deep(.el-table-column--selection .el-checkbox__label) { display: none; }

/* 层级颜色区分 — 行首彩色左边框 */
:deep(.cw-row-region td:nth-child(2)) { border-left: 3px solid #409EFF; padding-left: 10px; background: #f0f7ff; }
:deep(.cw-row-item td:nth-child(2)) { border-left: 3px solid #67C23A; padding-left: 10px; }
</style>

<!-- 日期选择器面板样式（非 scoped，因 el-date-picker 面板 teleport 到 body） -->
<style>
.yt-date-picker .has-video {
  background: #ecf5ff;
}
.yt-date-picker .has-video .el-date-table-cell__text {
  position: relative;
}
.yt-date-picker .has-video .el-date-table-cell__text::after {
  content: '';
  position: absolute;
  bottom: 2px;
  left: 50%;
  transform: translateX(-50%);
  width: 4px;
  height: 4px;
  border-radius: 50%;
  background: #409eff;
}
</style>
