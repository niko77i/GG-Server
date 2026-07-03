<template>
  <div style="display:flex;flex-direction:column;height:calc(100vh - 72px);">
    <h1 style="flex-shrink:0;">🧰 工具集</h1>
    <div class="sticky-tabs" style="flex-shrink:0;">
      <el-tabs :model-value="activeTab" @update:model-value="switchTab">
        <el-tab-pane label="📊 做表数据" name="zuobiao" />
        <el-tab-pane label="🎵 音频替换" name="audio" />
        <el-tab-pane label="🌐 翻译工具" name="translate" />
      </el-tabs>
    </div>

    <!-- ===== 做表数据 — 输入区固定 + 结果滚动 ===== -->
    <div v-show="activeTab === 'zuobiao'" style="flex:1;min-height:0;display:flex;flex-direction:column;">
      <div style="flex-shrink:0;">
        <p style="color:#888;margin-bottom:8px;font-size:13px;">粘贴包含"添加过滤条件"和"Total"的原始竖排数据：</p>
        <el-checkbox v-model="zbIncludeCampaignId" size="small" style="margin-bottom:8px;" :disabled="zbYanghu">包含广告系列ID（原数据11列，自动剔除第5列）</el-checkbox>
        <el-checkbox v-model="zbYanghu" size="small" style="margin-bottom:8px;margin-left:12px;">养户（7列：账号/客户ID/广告系列/状态/费用/展示/点击）</el-checkbox>
        <el-input v-model="zbInput" type="textarea" :rows="8" placeholder="在此粘贴原始数据..." />
        <div style="display:flex;gap:8px;margin-top:8px;">
          <el-button type="primary" @click="zbProcess">🚀 一键解析并生成所有报表</el-button>
          <el-button @click="zbExportExcel" :disabled="!zbRaw.length">📥 导出全部为 Excel</el-button>
          <el-button v-if="!zbYanghu" type="success" @click="zbSaveDialogVisible = true" :disabled="!zbRaw.length">💾 保存到数据库</el-button>
        </div>
        <div v-if="zbError" style="color:#dc2626;margin-top:8px;">{{ zbError }}</div>
      </div>

      <div style="flex:1;min-height:0;overflow-y:auto;">
        <!-- 原始清洗数据 -->
        <div v-if="zbRaw.length" style="margin-top:20px;">
          <h3>📋 原始清洗数据 <el-tag size="small">{{ zbRaw.length }}</el-tag>
            <el-button link size="small" @click="copyTable('zbRaw')">📋 一键复制</el-button>
          </h3>
          <el-table :data="zbRaw" size="small" border stripe max-height="300" :id="'zbTableRaw'">
            <el-table-column prop="account" label="账号" min-width="110" />
            <el-table-column prop="customerId" label="客户ID" min-width="120" />
            <el-table-column prop="campaign" label="广告系列" min-width="160" show-overflow-tooltip />
            <el-table-column prop="campaignStatus" label="状态" min-width="70">
              <template #default="{row}">{{ row.campaignStatus || '-' }}</template>
            </el-table-column>
            <el-table-column prop="cost" label="费用" min-width="80">
              <template #default="{row}">{{ row.cost.toFixed(2) }}</template>
            </el-table-column>
            <el-table-column prop="impressions" label="展示次数" min-width="80">
              <template #default="{row}">{{ row.impressions.toLocaleString() }}</template>
            </el-table-column>
            <el-table-column prop="clicks" label="点击次数" min-width="80">
              <template #default="{row}">{{ row.clicks.toLocaleString() }}</template>
            </el-table-column>
            <el-table-column prop="installs" label="安装次数" min-width="80">
              <template #default="{row}">{{ (row.installs || 0).toLocaleString() }}</template>
            </el-table-column>
            <el-table-column prop="inAppActions" label="应用内操作" min-width="100">
              <template #default="{row}">{{ row.inAppActions ?? '-' }}</template>
            </el-table-column>
            <el-table-column prop="costPerInApp" label="每次操作费用" min-width="110">
              <template #default="{row}">{{ row.costPerInApp ?? '-' }}</template>
            </el-table-column>
          </el-table>
        </div>

        <!-- 做表数据 -->
        <div v-if="zbZuobiao.length" style="margin-top:20px;">
          <h3>📑 做表数据 <el-tag size="small">{{ zbZuobiao.length }}</el-tag>
            <el-button link size="small" @click="copyTable('zbZuobiao')">📋 一键复制</el-button>
          </h3>
          <el-table :data="zbZuobiao" size="small" border stripe max-height="300">
            <el-table-column prop="account" label="账号" /><el-table-column prop="customerId" label="客户ID" />
            <el-table-column prop="cost" label="费用"><template #default="{row}">{{ row.cost.toFixed(2) }}</template></el-table-column>
            <el-table-column width="20" /><el-table-column width="20" /><el-table-column width="20" /><el-table-column width="20" />
            <el-table-column prop="campaign" label="广告系列" />
          </el-table>
        </div>

        <!-- 客户表数据 -->
        <div v-if="zbKehu.length" style="margin-top:20px;">
          <h3>📈 客户表数据 <el-tag size="small">{{ zbKehu.length }}</el-tag>
            <el-button link size="small" @click="copyTable('zbKehu')">📋 一键复制</el-button>
          </h3>
          <el-table :data="zbKehu" size="small" border stripe max-height="300">
            <el-table-column prop="campaign" label="广告系列" />
            <el-table-column prop="cost" label="费用"><template #default="{row}">{{ row.cost.toFixed(2) }}</template></el-table-column>
            <el-table-column prop="impressions" label="展示次数"><template #default="{row}">{{ row.impressions.toLocaleString() }}</template></el-table-column>
            <el-table-column prop="clicks" label="点击次数"><template #default="{row}">{{ row.clicks.toLocaleString() }}</template></el-table-column>
          </el-table>
        </div>
      </div>
    </div>

    <!-- ===== 音频替换 ===== -->
    <div v-show="activeTab === 'audio'" style="flex:1;min-height:0;overflow-y:auto;max-width:600px;">
      <el-form-item label="🎬 原视频">
        <div style="display:flex;gap:6px;">
          <el-input v-model="audioVideoPath" placeholder="F:\video\test.mp4" style="flex:1;" />
          <el-button v-if="isLocalhost()" @click="doBrowseFile('video')" style="width:44px;">📂</el-button>
        </div>
      </el-form-item>
      <el-form-item label="🎶 新音频源（音频或视频）">
        <div style="display:flex;gap:6px;">
          <el-input v-model="audioSourcePath" placeholder="F:\music\bg.mp3 或 F:\video\source.mp4" style="flex:1;" />
          <el-button v-if="isLocalhost()" @click="doBrowseFile('audio')" style="width:44px;">📂</el-button>
        </div>
        <span class="hint">支持 .mp3/.wav/.aac/.m4a 等音频，或 .mp4 等视频（自动提取音频）</span>
      </el-form-item>
      <el-button type="primary" @click="audioReplace" :loading="audioReplacing">🎵 替换音频</el-button>
      <div v-if="audioResult" style="margin-top:8px;font-size:12px;">{{ audioResult }}</div>
    </div>

    <!-- ===== 翻译工具 ===== -->
    <div v-show="activeTab === 'translate'" style="flex:1;min-height:0;overflow-y:auto;max-width:700px;">
      <el-form-item label="📝 源文本">
        <el-input v-model="tlInput" type="textarea" :rows="6" placeholder="输入要翻译的文本..." />
      </el-form-item>
      <div style="display:flex;gap:8px;align-items:center;margin-top:12px;">
        <span style="font-size:13px;white-space:nowrap;">目标语言：</span>
        <el-select v-model="tlTarget" placeholder="选择语言" style="width:200px;" filterable>
          <el-option v-for="l in TL_LANGS" :key="l.value" :label="l.label" :value="l.value" />
        </el-select>
        <el-button type="primary" @click="tlTranslate" :loading="tlLoading">🌐 翻译</el-button>
      </div>
      <div v-if="tlError" style="color:#dc2626;margin-top:8px;">{{ tlError }}</div>
      <div v-if="tlResult" style="margin-top:16px;">
        <div style="display:flex;align-items:center;gap:8px;">
          <h3 style="margin:0;">📋 翻译结果</h3>
          <el-button link size="small" @click="tlCopy">📋 复制</el-button>
        </div>
        <div style="background:#f5f7fa;padding:12px;border-radius:8px;margin-top:8px;white-space:pre-wrap;font-size:14px;line-height:1.6;">{{ tlResult }}</div>
      </div>
    </div>

    <!-- 保存弹窗 -->
    <el-dialog v-model="zbSaveDialogVisible" title="💾 保存做表数据" width="95%" top="3vh" @open="onSaveDialogOpen">
      <el-form :inline="true" label-width="80px">
        <el-form-item label="产品名" required>
          <el-select v-model="zbSaveProduct" placeholder="搜索并选择产品..." filterable style="width:200px;" :loading="zbSaveProductsLoading" @change="onProductSelect">
            <el-option v-for="p in zbSaveProducts" :key="p.id" :label="p.product_name + (p.region ? ' (' + p.region + ')' : '')" :value="p.product_name" />
          </el-select>
        </el-form-item>
        <el-form-item label="地区" required>
          <el-input v-model="zbSaveRegion" placeholder="地区" style="width:120px;" />
        </el-form-item>
        <el-form-item label="日期">
          <el-date-picker v-model="zbSaveDate" type="date" placeholder="选择日期" value-format="YYYY-MM-DD" style="width:150px;" />
        </el-form-item>
      </el-form>
      <div style="margin-top:8px;">
        <div style="font-weight:600;margin-bottom:6px;">📋 待保存数据 ({{ saveRows.length }} 条)</div>
        <el-table :data="saveRows" size="small" border stripe max-height="380">
          <el-table-column prop="account" label="账号" min-width="100" />
          <el-table-column prop="customerId" label="客户ID" min-width="120" />
          <el-table-column prop="campaign" label="广告系列" min-width="160" show-overflow-tooltip />
          <el-table-column prop="cost" label="费用" min-width="80">
            <template #default="{row}">{{ row.cost.toFixed(2) }}</template>
          </el-table-column>
          <el-table-column prop="impressions" label="展示" min-width="80">
            <template #default="{row}">{{ (row.impressions || 0).toLocaleString() }}</template>
          </el-table-column>
          <el-table-column prop="clicks" label="点击" min-width="70">
            <template #default="{row}">{{ (row.clicks || 0).toLocaleString() }}</template>
          </el-table-column>
          <el-table-column prop="installs" label="安装" min-width="70">
            <template #default="{row}">{{ (row.installs || 0).toLocaleString() }}</template>
          </el-table-column>
          <el-table-column prop="inAppActions" label="应用内操作" min-width="100">
            <template #default="{row}">{{ row.inAppActions ?? '-' }}</template>
          </el-table-column>
          <el-table-column prop="costPerInApp" label="每次操作费用" min-width="110">
            <template #default="{row}">{{ row.costPerInApp ?? '-' }}</template>
          </el-table-column>
          <el-table-column label="操作" min-width="60" fixed="right">
            <template #default="{ $index }">
              <el-button link size="small" type="danger" @click="removeSaveRow($index)">🗑 删除</el-button>
            </template>
          </el-table-column>
        </el-table>
      </div>
      <template #footer>
        <el-button @click="zbSaveDialogVisible = false">取消</el-button>
        <el-button type="primary" @click="zbDoSave" :loading="zbSaving">💾 保存</el-button>
      </template>
    </el-dialog>

    <!-- 重复数据对比弹窗 -->
    <el-dialog v-model="zbDupDialogVisible" title="⚠️ 发现重复数据" width="960px" top="5vh" :close-on-click-modal="false">
      <p style="color:#dc2626;margin-bottom:12px;">
        以下 {{ duplicateItems.length }} 条数据已存在（同产品+同客户ID+同系列）。请逐条选择保留旧数据还是用新数据覆盖。再次点击可取消选择。
      </p>
      <div v-for="(item, idx) in duplicateItems" :key="idx"
        style="display:flex;gap:12px;margin-bottom:12px;padding:8px;border:1px solid #e5e7eb;border-radius:8px;"
        :style="{ opacity: item.resolved ? 0.45 : 1 }">
        <!-- 左侧：旧数据 -->
        <div style="flex:1;background:#fef2f2;padding:10px;border-radius:6px;" :style="item.decision === 'keep-old' ? { border: '2px solid #22c55e' } : {}">
          <div style="font-weight:600;margin-bottom:4px;">📋 旧数据 (ID: {{ item.existing.id }})</div>
          <div style="font-size:12px;line-height:1.7;">
            <div>客户ID: {{ item.existing.customer_id }}</div>
            <div>系列: {{ item.existing.campaign }}</div>
            <div>费用: {{ item.existing.cost }}</div>
            <div>展示: {{ item.existing.impressions?.toLocaleString() }}</div>
            <div>点击: {{ item.existing.clicks?.toLocaleString() }}</div>
            <div v-if="item.existing.installs">安装: {{ item.existing.installs?.toLocaleString() }}</div>
            <div>日期: {{ item.existing.report_date }}</div>
          </div>
          <el-button size="small" :type="item.decision === 'keep-old' ? 'primary' : 'default'"
            :disabled="item.resolved && item.decision !== 'keep-old'"
            @click="resolveDuplicate(idx, 'keep-old')" style="margin-top:6px;">
            {{ item.decision === 'keep-old' ? '✓ 已选保留旧数据（再次点击取消）' : '保留旧数据' }}
          </el-button>
        </div>
        <!-- 右侧：新数据 -->
        <div style="flex:1;background:#f0fdf4;padding:10px;border-radius:6px;" :style="item.decision === 'keep-new' ? { border: '2px solid #22c55e' } : {}">
          <div style="font-weight:600;margin-bottom:4px;">🆕 新数据</div>
          <div style="font-size:12px;line-height:1.7;">
            <div>账号: {{ item.incoming.account || '-' }}</div>
            <div>客户ID: {{ item.incoming.customerId }}</div>
            <div>系列: {{ item.incoming.campaign }}</div>
            <div>费用: {{ item.incoming.cost }}</div>
            <div>展示: {{ (item.incoming.impressions || 0).toLocaleString() }}</div>
            <div>点击: {{ (item.incoming.clicks || 0).toLocaleString() }}</div>
            <div v-if="item.incoming.installs">安装: {{ (item.incoming.installs || 0).toLocaleString() }}</div>
          </div>
          <el-button size="small" :type="item.decision === 'keep-new' ? 'success' : 'default'"
            :disabled="item.resolved && item.decision !== 'keep-new'"
            @click="resolveDuplicate(idx, 'keep-new')" style="margin-top:6px;">
            {{ item.decision === 'keep-new' ? '✓ 已选用新数据覆盖（再次点击取消）' : '用新数据覆盖' }}
          </el-button>
        </div>
      </div>
      <template #footer>
        <el-button @click="zbDupDialogVisible = false">取消保存</el-button>
        <el-button type="primary" @click="zbConfirmSave" :loading="zbSaving"
          :disabled="duplicateItems.some(d => !d.resolved)">
          确认保存 ({{ duplicateItems.filter(d => d.resolved).length }}/{{ duplicateItems.length }})
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, computed, watch } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { useVideoStore } from '@/stores/video'
import { browseApi } from '@/api/browse'
import { isLocalhost } from '@/utils/env'
import { ElMessage } from 'element-plus'
import { copyToClipboard } from '@/utils/clipboard'
import { parseAdsData } from '@/utils/adsParser'
import { translateApi } from '@/api/youtube'
import api from '@/api/client'

const router = useRouter()
const route = useRoute()
const vStore = useVideoStore()

const activeTab = computed(() => {
  if (route.path.includes('/audio')) return 'audio'
  if (route.path.includes('/translate')) return 'translate'
  return 'zuobiao'
})
function switchTab(name) { router.push(`/toolkit/${name}`) }

// ========== 做表数据 ==========
const zbInput = ref('')
const zbIncludeCampaignId = ref(false)
const zbYanghu = ref(false)
const zbRaw = ref([])
const zbZuobiao = ref([])
const zbKehu = ref([])
const zbError = ref('')

// ========== 保存到数据库相关状态 ==========
const zbSaveDialogVisible = ref(false)
const zbSaveProduct = ref('')
const zbSaveRegion = ref('')
const zbSaveDate = ref('')  // 前一天
const zbSaveProducts = ref([])
const zbSaveProductsLoading = ref(false)
const zbSaving = ref(false)
const saveRows = ref([])  // 待保存的行（从 zbRaw 复制，允许删除）
const zbDupDialogVisible = ref(false)
const duplicateItems = ref([])

// 默认日期：前一天
function _yesterday() {
  const d = new Date(Date.now() - 86400000)
  return d.getFullYear() + '-' + String(d.getMonth() + 1).padStart(2, '0') + '-' + String(d.getDate()).padStart(2, '0')
}

async function onSaveDialogOpen() {
  zbSaveDate.value = _yesterday()
  saveRows.value = [...zbRaw.value]
  // 加载产品
  zbSaveProductsLoading.value = true
  try {
    const res = await api.get('/ad-reports/products')
    zbSaveProducts.value = res.products || []
  } catch { zbSaveProducts.value = [] }
  zbSaveProductsLoading.value = false
}

function onProductSelect(pname) {
  if (!pname) return
  const p = zbSaveProducts.value.find(x => x.product_name === pname)
  if (p && p.region) zbSaveRegion.value = p.region
}

function removeSaveRow(idx) {
  saveRows.value.splice(idx, 1)
}

async function zbDoSave() {
  if (!zbSaveProduct.value) { ElMessage.warning('请选择产品'); return }
  if (!zbSaveRegion.value) { ElMessage.warning('请填写地区'); return }
  if (!saveRows.value.length) { ElMessage.warning('没有可保存的数据'); return }
  zbSaving.value = true
  try {
    const checkRes = await api.post('/ad-reports/check-duplicates', {
      product_name: zbSaveProduct.value,
      region: zbSaveRegion.value,
      report_date: zbSaveDate.value,
      rows: saveRows.value,
    })
    if (checkRes.duplicates && checkRes.duplicates.length) {
      duplicateItems.value = checkRes.duplicates.map(d => ({ ...d, resolved: false, decision: null }))
      zbSaveDialogVisible.value = false
      zbDupDialogVisible.value = true
    } else {
      const saveRes = await api.post('/ad-reports/save', {
        product_name: zbSaveProduct.value,
        region: zbSaveRegion.value,
        report_date: zbSaveDate.value,
        rows: saveRows.value,
        override_ids: [],
      })
      ElMessage.success(`保存成功！已保存 ${saveRes.saved} 条`)
      zbSaveDialogVisible.value = false
    }
  } catch (e) { ElMessage.error('保存失败: ' + (e.message || '未知错误')) }
  zbSaving.value = false
}

function resolveDuplicate(idx, decision) {
  const item = duplicateItems.value[idx]
  if (item.decision === decision) {
    // 再次点击同一按钮 → 取消选择
    item.resolved = false
    item.decision = null
  } else {
    item.resolved = true
    item.decision = decision
  }
  // 触发响应式
  duplicateItems.value = [...duplicateItems.value]
}

async function zbConfirmSave() {
  const unresolved = duplicateItems.value.filter(d => !d.resolved)
  if (unresolved.length) { ElMessage.warning('请处理所有重复数据'); return }
  zbSaving.value = true
  try {
    const overrideIds = duplicateItems.value
      .filter(d => d.decision === 'keep-new')
      .map(d => d.existing.id)
    const saveRes = await api.post('/ad-reports/save', {
      product_name: zbSaveProduct.value,
      region: zbSaveRegion.value,
      report_date: zbSaveDate.value,
      rows: saveRows.value,
      override_ids: overrideIds,
    })
    ElMessage.success(`保存成功！已保存 ${saveRes.saved} 条，跳过 ${saveRes.skipped || 0} 条`)
    zbDupDialogVisible.value = false
  } catch (e) { ElMessage.error('保存失败: ' + (e.message || '未知错误')) }
  zbSaving.value = false
}

function zbProcess() {
  zbError.value = ''
  zbRaw.value = []; zbZuobiao.value = []; zbKehu.value = []
  try {
    const { raw, zuobiao, kehu } = parseAdsData(zbInput.value, {
      isYanghu: zbYanghu.value,
      includeCampaignId: zbIncludeCampaignId.value,
    })
    zbRaw.value = raw
    zbZuobiao.value = zuobiao
    zbKehu.value = kehu
  } catch(e) { zbError.value = e.message }
}

function copyTable(type) {
  const data = type === 'zbZuobiao' ? zbZuobiao.value : type === 'zbKehu' ? zbKehu.value : zbRaw.value
  if (!data.length) return
  let lines
  if (type === 'zbZuobiao') {
    lines = data.map(d => [d.account, d.customerId, d.cost.toFixed(2), '', '', '', '', d.campaign].join('\t'))
  } else if (type === 'zbKehu') {
    lines = data.map(d => [d.campaign, d.cost.toFixed(2), d.impressions, d.clicks].join('\t'))
  } else {
    lines = data.map(d => [d.account, d.customerId, d.campaign, d.cost.toFixed(2), d.impressions, d.clicks].join('\t'))
  }
  copyToClipboard(lines.join('\n')).then(() => ElMessage.success('已复制 ✓'))
}

function zbExportExcel() {
  const XLSX = window.XLSX
  if (!XLSX) { ElMessage.warning('Excel 导出需要加载 XLSX 库，请稍后重试'); return }
  try {
    const wb = XLSX.utils.book_new()
    const rawSheet = XLSX.utils.json_to_sheet(zbRaw.value.map(d => ({
      账号: d.account, 客户ID: d.customerId, 广告系列: d.campaign, 费用: d.cost, 展示次数: d.impressions, 点击次数: d.clicks
    })))
    XLSX.utils.book_append_sheet(wb, rawSheet, '原始清洗数据')

    const zbSheet = XLSX.utils.aoa_to_sheet([
      ['账号','客户ID','费用','','','','','广告系列'],
      ...zbZuobiao.value.map(d => [d.account, d.customerId, d.cost, '', '', '', '', d.campaign])
    ])
    XLSX.utils.book_append_sheet(wb, zbSheet, '做表数据')

    const khSheet = XLSX.utils.json_to_sheet(zbKehu.value)
    XLSX.utils.book_append_sheet(wb, khSheet, '客户表数据')

    XLSX.writeFile(wb, 'Ads多维分析_' + Date.now() + '.xlsx')
    ElMessage.success('导出成功')
  } catch(e) { ElMessage.error('导出失败: ' + e.message) }
}

// ========== 音频替换 ==========
const audioVideoPath = ref('')
const audioSourcePath = ref('')
const audioReplacing = ref(false)
const audioResult = ref('')

async function doBrowseFile(type) {
  const fileType = type === 'video' ? 'video' : 'audio'
  const curPath = type === 'video' ? audioVideoPath.value : audioSourcePath.value
  let initialDir = null
  if (curPath) {
    const lastSep = Math.max(curPath.lastIndexOf('/'), curPath.lastIndexOf('\\'))
    if (lastSep > -1) initialDir = curPath.substring(0, lastSep)
  }
  try {
    const res = await browseApi.file({ type: fileType, initial_dir: initialDir })
    if (res.path) {
      if (type === 'video') audioVideoPath.value = res.path
      else audioSourcePath.value = res.path
    }
  } catch(e) { ElMessage.error('文件选择失败: ' + e.message) }
}

async function audioReplace() {
  if (!audioVideoPath.value || !audioSourcePath.value) { ElMessage.warning('请选择原视频和音频源'); return }
  audioReplacing.value = true; audioResult.value = ''
  try {
    const res = await vStore.audioReplace({ video_path: audioVideoPath.value, audio_source: audioSourcePath.value })
    audioResult.value = `✅ 完成: ${res.output} (${res.size_mb} MB)`
  } catch(e) { audioResult.value = '❌ ' + e.message }
  audioReplacing.value = false
}

const hint = 'font-size:11px;color:#888;margin-top:4px;display:block;'

// ========== 翻译工具 ==========
const TL_LANGS = [
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

const tlInput = ref('')
const tlTarget = ref('zh-CN')
const tlLoading = ref(false)
const tlResult = ref('')
const tlError = ref('')

async function tlTranslate() {
  const text = tlInput.value.trim()
  if (!text) { tlError.value = '请输入要翻译的文本'; return }
  tlError.value = ''
  tlLoading.value = true
  try {
    const res = await translateApi.translate({ text, target: tlTarget.value })
    tlResult.value = res.translated
  } catch (e) {
    tlError.value = '翻译失败：' + (e.message || '未知错误')
  } finally {
    tlLoading.value = false
  }
}

function tlCopy() {
  if (tlResult.value) {
    copyToClipboard(tlResult.value).then(() => ElMessage.success('已复制译文 ✓'))
  }
}
</script>
