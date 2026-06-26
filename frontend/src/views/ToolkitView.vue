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
            <el-table-column prop="account" label="账号" /><el-table-column prop="customerId" label="客户ID" />
            <el-table-column prop="campaign" label="广告系列" />
            <el-table-column prop="cost" label="费用"><template #default="{row}">{{ row.cost.toFixed(2) }}</template></el-table-column>
            <el-table-column prop="impressions" label="展示次数"><template #default="{row}">{{ row.impressions.toLocaleString() }}</template></el-table-column>
            <el-table-column prop="clicks" label="点击次数"><template #default="{row}">{{ row.clicks.toLocaleString() }}</template></el-table-column>
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
          <el-button @click="doBrowseFile('video')" style="width:44px;">📂</el-button>
        </div>
      </el-form-item>
      <el-form-item label="🎶 新音频源（音频或视频）">
        <div style="display:flex;gap:6px;">
          <el-input v-model="audioSourcePath" placeholder="F:\music\bg.mp3 或 F:\video\source.mp4" style="flex:1;" />
          <el-button @click="doBrowseFile('audio')" style="width:44px;">📂</el-button>
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
  </div>
</template>

<script setup>
import { ref, computed } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { useVideoStore } from '@/stores/video'
import { browseApi } from '@/api/browse'
import { ElMessage } from 'element-plus'
import { copyToClipboard } from '@/utils/clipboard'
import { translateApi } from '@/api/youtube'

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

function zbProcess() {
  zbError.value = ''
  zbRaw.value = []; zbZuobiao.value = []; zbKehu.value = []
  const input = zbInput.value.trim()
  if (!input) { zbError.value = '请输入数据'; return }
  try {
    const lines = input.split(/\r?\n/).map(l => l.trim()).filter(l => l)
    const starts = []; lines.forEach((l, i) => { if (l === '添加过滤条件') starts.push(i) })
    if (!starts.length) throw new Error('未找到"添加过滤条件"')
    const startIdx = starts[starts.length - 1]
    const endIdx = lines.indexOf('Total')
    if (endIdx < 0) throw new Error('未找到"Total"')
    if (startIdx >= endIdx) throw new Error('数据顺序异常')

    const isYanghu = zbYanghu.value
    let step, costIdx, imprIdx, clickIdx
    if (isYanghu) {
      // 养户模式：7 列 — 账号/客户ID/广告系列/广告系列状态/费用/展示次数/点击次数
      step = 7; costIdx = 4; imprIdx = 5; clickIdx = 6
    } else {
      const includeCampaignId = zbIncludeCampaignId.value
      step = includeCampaignId ? 11 : 10
      costIdx = includeCampaignId ? 5 : 4
      imprIdx = includeCampaignId ? 6 : 5
      clickIdx = includeCampaignId ? 7 : 6
    }

    const validLines = lines.slice(startIdx + 1, endIdx)
    const rows = []
    for (let i = 0; i < validLines.length; i += step) {
      const row = validLines.slice(i, i + step)
      if (row.length === step && /^\d{3}-\d{3}-\d{4}$/.test(row[1]) && row[costIdx].includes('US$')) {
        rows.push(row)
      }
    }
    if (!rows.length) throw new Error('未找到有效数据（请确认费用列是否包含 "US$"）')

    if (isYanghu) {
      // 养户：7 列提取
      zbRaw.value = rows.map(r => ({
        account: r[0], customerId: r[1],
        campaign: r[2].replace(/-[^-]*$/, '').trim(),
        campaignStatus: r[3] || '',
        cost: parseFloat(r[costIdx].replace(/[^0-9.-]+/g, '')) || 0,
        impressions: parseInt(r[imprIdx].replace(/[^0-9]/g, '')) || 0,
        clicks: parseInt(r[clickIdx].replace(/[^0-9]/g, '')) || 0,
      })).filter(d => d.cost > 0)
    } else {
      // 普通模式：完整提取（含安装次数/应用内操作等）
      const installIdx = zbIncludeCampaignId.value ? 8 : 7
      const inAppIdx = zbIncludeCampaignId.value ? 9 : 8
      const cpiIdx = zbIncludeCampaignId.value ? 10 : 9
      zbRaw.value = rows.map(r => ({
        account: r[0], customerId: r[1],
        campaign: r[2].replace(/-[^-]*$/, '').trim(),
        campaignStatus: r[3] || '',
        cost: parseFloat(r[costIdx].replace(/[^0-9.-]+/g, '')) || 0,
        impressions: parseInt(r[imprIdx].replace(/[^0-9]/g, '')) || 0,
        clicks: parseInt(r[clickIdx].replace(/[^0-9]/g, '')) || 0,
        installs: parseInt((r[installIdx] || '').replace(/[^0-9]/g, '')) || 0,
        inAppActions: parseFloat((r[inAppIdx] || '').replace(/[^0-9.]/g, '')) || 0,
        costPerInApp: parseFloat((r[cpiIdx] || '').replace(/[^0-9.]/g, '')) || 0,
      })).filter(d => d.cost > 0)
    }

    // 做表数据：按客户ID+广告系列聚合费用
    const zbMap = new Map()
    zbRaw.value.forEach(d => {
      const key = d.customerId + '|||' + d.campaign
      if (!zbMap.has(key)) zbMap.set(key, { account: d.account, customerId: d.customerId, cost: d.cost, campaign: d.campaign })
      else zbMap.get(key).cost += d.cost
    })
    zbZuobiao.value = Array.from(zbMap.values()).filter(d => d.cost > 0)

    // 客户表：按广告系列聚合
    const khMap = new Map()
    zbRaw.value.forEach(d => {
      if (!khMap.has(d.campaign)) khMap.set(d.campaign, { campaign: d.campaign, cost: 0, impressions: 0, clicks: 0 })
      const item = khMap.get(d.campaign)
      item.cost += d.cost; item.impressions += d.impressions; item.clicks += d.clicks
    })
    zbKehu.value = Array.from(khMap.values()).filter(d => d.cost > 0)
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
