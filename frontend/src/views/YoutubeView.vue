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
          <el-radio-group v-if="authStore.isAdmin" v-model="store.filters.scope" @change="loadVideos" size="small">
            <el-radio-button value="public">公用</el-radio-button>
            <el-radio-button value="private">私有</el-radio-button>
          </el-radio-group>
          <el-select v-model="store.filters.uploader_id" @change="loadVideos" placeholder="全部上传者" clearable size="small" style="flex:1;min-width:110px;">
            <el-option v-for="(info, id) in store.counts.uploader" :key="id" :label="info.display_name + ' (' + info.cnt + ')'" :value="Number(id)" />
          </el-select>
          <el-select v-if="authStore.isAdmin" v-model="assetFilterProduct" @change="applyAssetFilter" placeholder="成效素材产品" clearable size="small" style="flex:1;min-width:130px;">
            <el-option v-for="p in assetProductOptions" :key="p" :label="p" :value="p" />
          </el-select>
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
          <el-select v-model="store.filters.channel_name" @change="loadVideos" placeholder="全部频道" clearable size="small" style="flex:1;min-width:130px;" filterable>
            <el-option v-for="(cnt, name) in store.counts.channel_name" :key="name" :label="name + ' (' + cnt + ')'" :value="name" />
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
          <el-select v-if="authStore.isAdmin" v-model="batchPublic" @change="val => doBatchEdit('is_public', val)" placeholder="可见性..." size="small" style="width:110px;" clearable>
            <el-option label="🌐 公开" value="1" />
            <el-option label="🔒 私有" value="0" />
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
                    <el-tag size="small" type="warning" v-if="row.owner_display_name" effect="plain">{{ row.owner_display_name }}</el-tag>
                    <el-tag size="small" type="info" v-if="row.channel_name" effect="plain">📺 {{ row.channel_name }}</el-tag>
                    <el-tag v-if="row.total_consumption > 0" size="small" type="danger" effect="dark" style="cursor:pointer;" @click.stop="openConsumption(row)">💰 {{ fmtAmount(row.total_consumption) }}</el-tag>
                    <el-tooltip v-if="productAssetMap[row.id] && productAssetMap[row.id].length" placement="top">
                      <template #content>
                        <div v-for="pname in productAssetMap[row.id]" :key="pname">{{ pname }}</div>
                      </template>
                      <el-tag size="small" type="warning" effect="dark">🎬 {{ productAssetMap[row.id].length }}</el-tag>
                    </el-tooltip>
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
                    <el-button v-if="canModifyVideo(row)" link size="small" type="primary" @click.stop="openEdit(row)" style="justify-content:flex-start;">✏️ 编辑</el-button>
                    <el-button link size="small" type="warning" @click="openConsumption(row)" style="justify-content:flex-start;">💰 消耗</el-button>
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

    <!-- 消耗详情弹窗 -->
    <el-dialog v-model="consumptionVisible" :title="'💰 消耗详情 — ' + consumptionVideo?.title" width="700px" :close-on-click-modal="false" destroy-on-close>
      <div v-if="consumptionLoading" style="text-align:center;padding:40px;">加载中...</div>
      <template v-else>
        <div style="margin-bottom:16px;font-size:16px;font-weight:600;">
          总消耗：<span style="color:#f56c6c;">¥{{ consumptionTotal.toLocaleString() }}</span>
        </div>
        <div v-if="!consumptionUsers.length" style="color:#999;text-align:center;padding:20px;">暂无消耗记录</div>
        <div v-for="user in consumptionUsers" :key="user.user_id" style="margin-bottom:12px;border:1px solid #ebeef5;border-radius:8px;overflow:hidden;">
          <div @click="user._expanded = !user._expanded" style="display:flex;align-items:center;justify-content:space-between;padding:10px 14px;background:#f5f7fa;cursor:pointer;">
            <span style="font-weight:600;">{{ user.display_name }}</span>
            <span style="color:#f56c6c;font-weight:600;">¥{{ user.total.toLocaleString() }}</span>
            <span style="font-size:12px;color:#999;">{{ user._expanded ? '▲' : '▼' }}</span>
          </div>
          <div v-show="user._expanded" style="padding:8px 14px;">
            <div v-for="rec in user.records" :key="rec.id" style="display:flex;align-items:center;gap:12px;padding:6px 0;border-bottom:1px solid #f0f0f0;font-size:13px;">
              <span style="color:#666;width:90px;">{{ rec.consume_date }}</span>
              <span v-if="rec.product_name" style="color:#409eff;flex:1;">{{ rec.product_name }}</span>
              <span v-else style="color:#999;flex:1;">-</span>
              <span style="color:#f56c6c;font-weight:500;width:80px;text-align:right;">¥{{ rec.amount.toLocaleString() }}</span>
              <template v-if="authStore.isAdmin && authStore.user?.id === user.user_id">
                <el-button link size="small" type="primary" @click.stop="editConsumptionRec(rec)">✏️</el-button>
                <el-button link size="small" type="danger" @click.stop="deleteConsumptionRec(rec)">🗑</el-button>
              </template>
            </div>
          </div>
        </div>
        <!-- 录入表单 (仅 admin/developer 可见，只能给自己加) -->
        <div v-if="authStore.isAdmin" style="margin-top:20px;padding-top:16px;border-top:2px solid #ebeef5;">
          <div style="font-weight:600;margin-bottom:10px;">📝 {{ consumptionEditId ? '编辑消耗' : '录入消耗' }}</div>
          <div style="display:flex;gap:10px;align-items:center;flex-wrap:wrap;">
            <el-input v-model="consumptionForm.amount" placeholder="金额" type="number" size="small" style="width:130px;" />
            <el-date-picker v-model="consumptionForm.consume_date" placeholder="日期" size="small" value-format="YYYY-MM-DD" style="width:150px;" />
            <el-select v-model="consumptionForm.product_id" placeholder="产品(可选)" size="small" filterable clearable style="width:180px;">
              <el-option v-for="p in runnerProducts" :key="p.id" :label="p.product_name" :value="p.id" />
            </el-select>
            <el-button size="small" type="primary" @click="submitConsumption" :loading="consumptionSaving">
              {{ consumptionEditId ? '更新' : '保存' }}
            </el-button>
            <el-button v-if="consumptionEditId" size="small" @click="cancelEditConsumption">取消</el-button>
          </div>
        </div>
      </template>
    </el-dialog>

    <!-- ===== 文案展示 ===== -->
    <CopywritingTab ref="cwTabRef" v-show="activeTab === 'copywriting'" />

    <!-- ===== 导入视频或文案 ===== -->
    <ImportTab v-show="activeTab === 'import'" />

    <!-- ===== 标签配置 ===== -->
    <TagsConfig v-show="activeTab === 'config'" />

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
import { useAuthStore } from '@/stores/auth'
import { ElMessageBox, ElMessage } from 'element-plus'
import { copyToClipboard } from '@/utils/clipboard'
import { translateApi, consumptionApi, productApi } from '@/api/youtube'
import api from '@/api/client'
import TagsConfig from '@/components/youtube/TagsConfig.vue'
import ImportTab from '@/components/youtube/ImportTab.vue'
import CopywritingTab from '@/components/youtube/CopywritingTab.vue'

const router = useRouter()
const route = useRoute()
const store = useYoutubeStore()
const authStore = useAuthStore()

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
const productAssetMap = ref({})
const assetFilterProduct = ref('')
const assetProductOptions = ref([])
const copiedIds = ref(JSON.parse(localStorage.getItem('ytCopied')||'{}'))
const copiedCount = computed(()=>Object.keys(copiedIds.value).length)

function toggleSelectAll(){const t=ytTableRef.value;if(!t)return;const ids=pagedVideos.value.map(v=>v.id);const sel=selected.value.map(v=>v.id);const all=ids.every(id=>sel.includes(id));if(all)t.clearSelection();else pagedVideos.value.forEach(v=>t.toggleRowSelection(v,true))}
function invertSelection(){const t=ytTableRef.value;if(!t)return;const sel=new Set(selected.value.map(v=>v.id));pagedVideos.value.forEach(v=>{if(sel.has(v.id))t.toggleRowSelection(v,false);else t.toggleRowSelection(v,true)})}
function selectUncopied(){const t=ytTableRef.value;if(!t)return;pagedVideos.value.forEach(v=>t.toggleRowSelection(v,!!(!copiedIds.value[v.id])))}

const filteredVideos = computed(() => {
  let list = store.videos
  // 成效素材产品筛选
  if (assetFilterProduct.value) {
    list = list.filter(v => {
      const pnames = productAssetMap.value[v.id] || []
      return pnames.includes(assetFilterProduct.value)
    })
  }
  if (!searchText.value) return list
  const q = searchText.value.toLowerCase()
  return list.filter(v => (v.title || '').toLowerCase().includes(q) || (v.id || '').toLowerCase().includes(q))
})

const pagedVideos = computed(() => {
  const start = (ytPage.value - 1) * ytPageSize.value
  return filteredVideos.value.slice(start, start + ytPageSize.value)
})

const dateRange = ref(null)

// 日期格子标记：有视频或有消耗的日期加标记类名
const dateSet = computed(() => new Set(Object.keys(store.videoDates)))
function dateCellClass(date) {
  const y = date.getFullYear()
  const m = String(date.getMonth() + 1).padStart(2, '0')
  const d = String(date.getDate()).padStart(2, '0')
  const key = `${y}-${m}-${d}`
  if (dateSet.value.has(key)) return 'has-video'
  if (consumptionDateSet.value.has(key)) return 'has-consumption'
  return ''
}

// 搜索文本变化时重置页码
watch(searchText, () => { ytPage.value = 1 })
// 每页条数变化时重置页码，防止当前页码超出新总页数导致空数据
watch(ytPageSize, () => { ytPage.value = 1 })

// ═══════════════════════ 消耗追踪 ═══════════════════════
const consumptionDates = ref({})
const consumptionVisible = ref(false)
const consumptionVideo = ref(null)
const consumptionLoading = ref(false)
const consumptionSaving = ref(false)
const consumptionTotal = ref(0)
const consumptionUsers = ref([])
const consumptionEditId = ref(null)
const consumptionForm = ref({ amount: null, consume_date: '', product_id: null })
const runnerProducts = ref([])

function fmtAmount(val) {
  if (!val) return '¥0'
  if (val >= 10000) return '¥' + (val / 10000).toFixed(1) + '万'
  return '¥' + val.toLocaleString()
}

async function loadConsumptionDates() {
  try {
    const res = await consumptionApi.dates({ scope: store.filters.scope })
    consumptionDates.value = res.dates || {}
  } catch { consumptionDates.value = {} }
}

// 更新日期标记（含视频导入日期 + 消耗日期）
const consumptionDateSet = computed(() => new Set(Object.keys(consumptionDates.value)))
// dateCellClass 中合并两个集合

async function openConsumption(video) {
  consumptionVideo.value = video
  consumptionVisible.value = true
  consumptionEditId.value = null
  consumptionForm.value = { amount: null, consume_date: '', product_id: null }
  await loadConsumptionDetail()
  if (authStore.isAdmin) await loadRunnerProducts()
}

async function loadConsumptionDetail() {
  if (!consumptionVideo.value) return
  consumptionLoading.value = true
  try {
    const res = await consumptionApi.get(consumptionVideo.value.id)
    consumptionTotal.value = res.total || 0
    consumptionUsers.value = (res.users || []).map(u => ({ ...u, _expanded: false }))
  } catch { consumptionTotal.value = 0; consumptionUsers.value = [] }
  consumptionLoading.value = false
}

async function loadRunnerProducts() {
  try {
    const res = await productApi.runnerProducts()
    runnerProducts.value = res.products || []
  } catch { runnerProducts.value = [] }
}

async function submitConsumption() {
  const f = consumptionForm.value
  if (!f.amount || parseFloat(f.amount) <= 0) { ElMessage.warning('请输入金额'); return }
  if (!f.consume_date) { ElMessage.warning('请选择日期'); return }
  consumptionSaving.value = true
  try {
    if (consumptionEditId.value) {
      await consumptionApi.update(consumptionVideo.value.id, consumptionEditId.value, {
        amount: parseFloat(f.amount), consume_date: f.consume_date, product_id: f.product_id
      })
      ElMessage.success('消耗记录已更新')
    } else {
      await consumptionApi.add(consumptionVideo.value.id, {
        amount: parseFloat(f.amount), consume_date: f.consume_date, product_id: f.product_id
      })
      ElMessage.success('消耗记录已添加')
    }
    consumptionEditId.value = null
    consumptionForm.value = { amount: null, consume_date: '', product_id: null }
    await loadConsumptionDetail()
    // 刷新视频列表以更新 total_consumption
    await loadVideos()
    await loadConsumptionDates()
  } catch (e) {
    ElMessage.error(e.response?.data?.error || '操作失败')
  }
  consumptionSaving.value = false
}

function editConsumptionRec(rec) {
  consumptionEditId.value = rec.id
  consumptionForm.value = {
    amount: rec.amount,
    consume_date: rec.consume_date,
    product_id: rec.product_id || null
  }
}

function cancelEditConsumption() {
  consumptionEditId.value = null
  consumptionForm.value = { amount: null, consume_date: '', product_id: null }
}

async function deleteConsumptionRec(rec) {
  try {
    await ElMessageBox.confirm(`确定删除 ¥${rec.amount.toLocaleString()} 的消耗记录？`, '确认删除', { type: 'warning' })
  } catch { return }
  try {
    await consumptionApi.delete(consumptionVideo.value.id, rec.id)
    ElMessage.success('已删除')
    await loadConsumptionDetail()
    await loadVideos()
    await loadConsumptionDates()
  } catch (e) {
    ElMessage.error(e.response?.data?.error || '删除失败')
  }
}

function onDateChange(val) {
  store.filters.from_date = val ? val[0] : ''
  store.filters.to_date = val ? val[1] : ''
  loadVideos()
}

async function loadVideos() {
  ytPage.value = 1
  await store.loadVideos()
  store.loadDates(store.filters)
  loadProductAssetMap()
  loadConsumptionDates()
}

async function loadProductAssetMap() {
  const ids = store.videos.map(v => v.id)
  if (!ids.length) { productAssetMap.value = {}; return }
  try {
    const res = await api.get('/youtube/product-assets', { params: { video_ids: ids.join(',') } })
    productAssetMap.value = res.mapping || {}
  } catch { productAssetMap.value = {} }
}

async function loadAssetProductOptions() {
  try {
    const res = await api.get('/youtube/asset-products')
    assetProductOptions.value = res.products || []
  } catch { assetProductOptions.value = [] }
}

function applyAssetFilter() {
  ytPage.value = 1
}

onMounted(async () => {
  // 普通用户只能看公开视频和公开文案
  if (!authStore.isAdmin) {
    store.filters.scope = 'public'
    store.cwScope = 'public'
  }
  await store.loadTags()
  store.loadDates(store.filters)
  await loadVideos()
  loadAssetProductOptions()
})

function onRowClick(row) {
  if (ytTableRef.value) ytTableRef.value.toggleRowSelection(row)
}
function playVideo(row) {
  playingId.value = row.id
  playingTitle.value = row.title
}

function canModifyVideo(row) { return authStore.isAdmin || row.owner_id === authStore.user?.id || row.is_public }
function canModifyCopywriting(row) { return authStore.isAdmin || row.owner_id === authStore.user?.id || row.is_public }
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
const batchPublic = ref('')

async function doBatchEdit(field, val) {
  if ((!val && val !== 0) || !selected.value.length) return
  try {
    const res = await store.batchEditVideos({ ids: selected.value.map(v => v.id), field, value: val })
    const updated = res?.updated ?? 0
    if (updated > 0) {
      ElMessage.success(`已批量更新 ${updated} 个视频 ✓`)
    } else {
      ElMessage.warning('没有视频被更新，请确认你有权限编辑所选视频')
    }
  } catch (e) {
    ElMessage.error('批量更新失败：' + (e.message || '未知错误'))
  }
  // Reset dropdown
  if (field === 'region') batchRegion.value = ''
  else if (field === 'frame_type') batchFrame.value = ''
  else if (field === 'effectiveness') batchEff.value = ''
  else if (field === 'product_name') batchProd.value = ''
  else if (field === 'review_status') batchReview.value = ''
  else if (field === 'is_public') batchPublic.value = ''
  loadVideos()
}

// Import tab — moved to ImportTab.vue

// Config tab — moved to TagsConfig.vue

// ---- 文案管理 ----
const cwTableRef = ref(null)
const cwSelected = ref([])
const cwBatchRegion = ref('')
const cwBatchEff = ref('')
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

async function cwDoBatchEffEdit(effectiveness) {
  if (effectiveness === undefined || effectiveness === null || !cwSelected.value.length) return
  await store.batchEditCopywritings({ ids: cwSelected.value.map(v => v.id), effectiveness })
  cwBatchEff.value = ''
  ElMessage.success(`已更新 ${cwSelected.value.length} 条文案成效 ✓`)
  loadCopywritings()
}

async function loadCopywritings() {
  await store.loadCopywritings()
  // 清除翻译缓存中已不存在的
  const curIds = new Set(store.copywritings.map(c => c.id))
  for (const key of Object.keys(cwTransMap.value)) {
    if (!curIds.has(Number(key))) delete cwTransMap.value[key]
  }
}

// 每次切换到文案 tab 都刷新（包括首次）
const cwTabRef = ref(null)

watch(activeTab, async (tab) => {
  if (tab === 'copywriting') await cwTabRef.value?.loadCopywritings()
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
.yt-date-picker .has-consumption {
  background: #fef0f0;
}
.yt-date-picker .has-consumption .el-date-table-cell__text {
  position: relative;
}
.yt-date-picker .has-consumption .el-date-table-cell__text::after {
  content: '';
  position: absolute;
  bottom: 2px;
  left: 50%;
  transform: translateX(-50%);
  width: 4px;
  height: 4px;
  border-radius: 50%;
  background: #f56c6c;
}
</style>
