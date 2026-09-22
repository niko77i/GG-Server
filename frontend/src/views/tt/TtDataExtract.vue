<template>
  <div style="display:flex;flex-direction:column;height:calc(100vh - 72px);">
    <h1 style="flex-shrink:0;">📥 TT数据提取</h1>

    <!-- 输入区（固定） -->
    <div style="flex-shrink:0;padding:0 20px;">
      <div style="display:flex;gap:12px;align-items:center;margin-bottom:8px;">
        <el-select v-model="selectedProduct" placeholder="搜索并选择产品..." filterable clearable
          style="width:220px;" :loading="productsLoading">
          <el-option v-for="p in products" :key="p.product_name"
            :label="p.product_name + (p.region ? ' (' + p.region + ')' : '') + (p.sales_person ? ' - ' + p.sales_person : '')"
            :value="p.product_name" />
        </el-select>
        <el-date-picker v-model="selectedDate" type="date" placeholder="选择日期" value-format="YYYY-MM-DD" style="width:150px;" />
        <el-select v-model="yanghuKeywords" multiple filterable allow-create
          placeholder="养户关键词（匹配到的行→养户/止戈）" style="flex:1;min-width:250px;" size="small" />
      </div>
      <p style="color:#888;margin-bottom:8px;font-size:13px;">粘贴包含"添加过滤条件"和"Total"的原始竖排数据：</p>
      <el-checkbox v-model="includeCampaignId" size="small" style="margin-bottom:8px;">包含广告系列ID（自动剔除第5列）</el-checkbox>
      <el-checkbox v-model="sevenCols" size="small" style="margin-bottom:8px;margin-left:12px;">7列数据（无安装/应用指标）</el-checkbox>
      <el-input v-model="input" type="textarea" :rows="8" placeholder="在此粘贴原始数据..." />
      <div style="display:flex;gap:8px;margin-top:8px;">
        <el-button type="primary" @click="process">🚀 一键解析并生成所有报表</el-button>
        <el-button @click="exportExcel" :disabled="!raw.length">📥 导出 CSV（Excel 可打开）</el-button>
      </div>
      <div v-if="error" style="color:#dc2626;margin-top:8px;">{{ error }}</div>
    </div>

    <!-- 结果区（滚动） -->
    <div style="flex:1;min-height:0;overflow-y:auto;padding:0 20px;">
      <!-- 原始清洗数据 -->
      <div v-if="raw.length" style="margin-top:20px;">
        <h3>📋 原始清洗数据 <el-tag size="small">{{ raw.length }}</el-tag>
          <el-button link size="small" @click="copyTable('raw')">📋 一键复制</el-button>
        </h3>
        <el-table :data="raw" size="small" border stripe max-height="300">
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
      <div v-if="zuobiao.length" style="margin-top:20px;">
        <h3>📑 做表数据 <el-tag size="small">{{ zuobiao.length }}</el-tag>
          <el-button link size="small" @click="copyTable('zuobiao')">📋 一键复制</el-button>
        </h3>
        <el-table :data="zuobiao" size="small" border stripe max-height="300">
          <el-table-column prop="account" label="账号" />
          <el-table-column prop="customerId" label="客户ID" />
          <el-table-column prop="cost" label="费用"><template #default="{row}">{{ row.cost.toFixed(2) }}</template></el-table-column>
          <el-table-column width="20" /><el-table-column width="20" /><el-table-column width="20" /><el-table-column width="20" />
          <el-table-column prop="campaign" label="广告系列" />
        </el-table>
      </div>

      <!-- 客户表数据 -->
      <div v-if="kehu.length" style="margin-top:20px;">
        <h3>📈 客户表数据 <el-tag size="small">{{ kehu.length }}</el-tag>
          <el-button link size="small" @click="copyTable('kehu')">📋 一键复制</el-button>
        </h3>
        <el-table :data="kehu" size="small" border stripe max-height="300">
          <el-table-column prop="campaign" label="广告系列" />
          <el-table-column prop="cost" label="费用"><template #default="{row}">{{ row.cost.toFixed(2) }}</template></el-table-column>
          <el-table-column prop="impressions" label="展示次数"><template #default="{row}">{{ row.impressions.toLocaleString() }}</template></el-table-column>
          <el-table-column prop="clicks" label="点击次数"><template #default="{row}">{{ row.clicks.toLocaleString() }}</template></el-table-column>
        </el-table>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, watch, onMounted, onUnmounted, onActivated, onDeactivated } from 'vue'
import { ElMessage } from 'element-plus'
import { copyToClipboard } from '@/utils/clipboard'
import { parseAdsData } from '@/utils/adsParser'
import { ttApi } from '@/api/tt'

// ========== 解析相关 ==========
const input = ref('')
const includeCampaignId = ref(false)
const sevenCols = ref(false)
const raw = ref([])
const zuobiao = ref([])
const kehu = ref([])
const error = ref('')

// ========== 产品/日期/关键词（本期 UI 占位，为写表预留） ==========
const selectedProduct = ref('')
const selectedDate = ref(_yesterday())
const products = ref([])
const productsLoading = ref(false)
const YANGHU_KEY = 'tt_zb_yanghu_keywords'
const yanghuKeywords = ref(
  (() => { try { const v = localStorage.getItem(YANGHU_KEY); return v ? JSON.parse(v) : ['养户', 'Website traffic-Search', 'Campaign #1'] } catch { return ['养户', 'Website traffic-Search', 'Campaign #1'] } })()
)
watch(yanghuKeywords, (v) => { localStorage.setItem(YANGHU_KEY, JSON.stringify(v)) }, { deep: true })

function _yesterday() {
  const d = new Date(Date.now() - 86400000)
  return d.getFullYear() + '-' + String(d.getMonth() + 1).padStart(2, '0') + '-' + String(d.getDate()).padStart(2, '0')
}

let _midnightTimer = null
function scheduleMidnightRefresh() {
  if (_midnightTimer) clearTimeout(_midnightTimer)
  const now = new Date()
  const next = new Date(now.getFullYear(), now.getMonth(), now.getDate() + 1, 0, 0, 0)
  _midnightTimer = setTimeout(() => { selectedDate.value = _yesterday(); scheduleMidnightRefresh() }, next.getTime() - now.getTime() + 1000)
}

async function loadProducts() {
  productsLoading.value = true
  try {
    const res = await ttApi.listProducts({ size: 200 })
    products.value = (res.items || []).map(p => ({
      product_name: p.product_name,
      region: p.region || '',
      sales_person: p.sales_person_name || '',
    }))
  } catch { products.value = [] }
  productsLoading.value = false
}

function process() {
  error.value = ''
  raw.value = []; zuobiao.value = []; kehu.value = []
  try {
    const r = parseAdsData(input.value, { isSevenCols: sevenCols.value, includeCampaignId: includeCampaignId.value })
    raw.value = r.raw
    zuobiao.value = r.zuobiao
    kehu.value = r.kehu
  } catch (e) { error.value = e.message }
}

function copyTable(type) {
  const data = type === 'zuobiao' ? zuobiao.value : type === 'kehu' ? kehu.value : raw.value
  if (!data.length) return
  let lines
  if (type === 'zuobiao') {
    lines = data.map(d => [d.account, d.customerId, d.cost.toFixed(2), '', '', '', '', d.campaign].join('\t'))
  } else if (type === 'kehu') {
    lines = data.map(d => [d.campaign, d.cost.toFixed(2), d.impressions, d.clicks].join('\t'))
  } else {
    lines = data.map(d => [d.account, d.customerId, d.campaign, d.cost.toFixed(2), d.impressions, d.clicks].join('\t'))
  }
  copyToClipboard(lines.join('\n')).then(() => ElMessage.success('已复制 ✓'))
}

function _csvCell(v) {
  const s = String(v ?? '')
  return /[",\n]/.test(s) ? '"' + s.replace(/"/g, '""') + '"' : s
}

function exportExcel() {
  if (!raw.value.length) return
  const sections = [
    ['原始清洗数据', ['账号','客户ID','广告系列','状态','费用','展示次数','点击次数'],
      raw.value.map(d => [d.account, d.customerId, d.campaign, d.campaignStatus || '', d.cost, d.impressions, d.clicks])],
    ['做表数据', ['账号','客户ID','费用','','','','','广告系列'],
      zuobiao.value.map(d => [d.account, d.customerId, d.cost, '', '', '', '', d.campaign])],
    ['客户表数据', ['广告系列','费用','展示次数','点击次数'],
      kehu.value.map(d => [d.campaign, d.cost, d.impressions, d.clicks])],
  ]
  const lines = []
  sections.forEach(([title, header, rows], i) => {
    if (i) lines.push('')
    lines.push(title)
    lines.push(header.map(_csvCell).join(','))
    rows.forEach(r => lines.push(r.map(_csvCell).join(',')))
  })
  const blob = new Blob(['﻿' + lines.join('\n')], { type: 'text/csv;charset=utf-8;' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = 'TT数据提取_' + Date.now() + '.csv'
  document.body.appendChild(a)
  a.click()
  document.body.removeChild(a)
  URL.revokeObjectURL(url)
  ElMessage.success('导出成功')
}

onMounted(() => { loadProducts() })
onActivated(() => { scheduleMidnightRefresh() })
onDeactivated(() => { if (_midnightTimer) { clearTimeout(_midnightTimer); _midnightTimer = null } })
onUnmounted(() => { if (_midnightTimer) clearTimeout(_midnightTimer) })
</script>
