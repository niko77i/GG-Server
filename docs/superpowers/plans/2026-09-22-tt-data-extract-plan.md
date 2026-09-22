# TT 数据提取（解析预览）实现计划

> **For agentic workers:** 按任务顺序执行，每步用 `- [ ]` 追踪。

**Goal:** 在 TT 平台新增「数据提取」页，复刻 GG「做表数据」Tab 的解析预览（粘贴 → 解析 → 三表预览 → 复制/导出），不写表。

**Architecture:** 纯前端。新增独立页面 `TtDataExtract.vue`，复用 `parseAdsData` 解析，产品下拉复用 `/api/tt/products/list`，侧边栏 + 路由接入。

**Tech Stack:** Vue 3 + Element Plus + Pinia，`adsParser.js` 纯函数。

## Global Constraints

- 纯增量：不改动 GG 的 `ToolkitView.vue`、`adsParser.js`、任何后端接口。
- 本期只做解析预览，**不得**加写表按钮/写库/同步状态逻辑。
- 数据格式先按 GG 的 Google Ads 竖排格式（含「添加过滤条件」「Total」）解析，不做 TT 格式适配。
- 产品下拉 value 用 `product_name`（与 GG 做表数据一致）。

---

## Task 1: 新增数据提取页面 `TtDataExtract.vue`

**Files:**
- Create: `frontend/src/views/tt/TtDataExtract.vue`

**Interfaces:**
- Consumes: `parseAdsData` from `@/utils/adsParser`（返回 `{ raw, zuobiao, kehu }`）；`api.get('/tt/products/list')`（返回 `{ items }`，item 含 `product_name/region/sales_person_name`）；`copyToClipboard` from `@/utils/clipboard`。
- Produces: 独立路由页面，无对外接口。

- [ ] **Step 1: 写页面**（完整代码见下）

```vue
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
        <el-button @click="exportExcel" :disabled="!raw.length">📥 导出全部为 Excel</el-button>
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
import { ref, watch, onMounted, onUnmounted } from 'vue'
import { ElMessage } from 'element-plus'
import { copyToClipboard } from '@/utils/clipboard'
import { parseAdsData } from '@/utils/adsParser'
import api from '@/api/client'

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
    const res = await api.get('/tt/products/list', { params: { size: 200 } })
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

function exportExcel() {
  const XLSX = window.XLSX
  if (!XLSX) { ElMessage.warning('Excel 导出需要加载 XLSX 库，请稍后重试'); return }
  try {
    const wb = XLSX.utils.book_new()
    const rawSheet = XLSX.utils.json_to_sheet(raw.value.map(d => ({
      账号: d.account, 客户ID: d.customerId, 广告系列: d.campaign, 费用: d.cost, 展示次数: d.impressions, 点击次数: d.clicks
    })))
    XLSX.utils.book_append_sheet(wb, rawSheet, '原始清洗数据')
    const zbSheet = XLSX.utils.aoa_to_sheet([
      ['账号','客户ID','费用','','','','','广告系列'],
      ...zuobiao.value.map(d => [d.account, d.customerId, d.cost, '', '', '', '', d.campaign])
    ])
    XLSX.utils.book_append_sheet(wb, zbSheet, '做表数据')
    const khSheet = XLSX.utils.json_to_sheet(kehu.value)
    XLSX.utils.book_append_sheet(wb, khSheet, '客户表数据')
    XLSX.writeFile(wb, 'TT数据提取_' + Date.now() + '.xlsx')
    ElMessage.success('导出成功')
  } catch (e) { ElMessage.error('导出失败: ' + e.message) }
}

onMounted(() => { loadProducts(); scheduleMidnightRefresh() })
onUnmounted(() => { if (_midnightTimer) clearTimeout(_midnightTimer) })
</script>
```

- [ ] **Step 2: 检查语法**（`npm run build` 或 IDE 无报错）

---

## Task 2: 接入路由

**Files:**
- Modify: `frontend/src/router/index.js`（TT children 区）

在 `children` 里新增一条：

```js
{ path: 'extract', component: () => import('../views/tt/TtDataExtract.vue'), meta: { title: 'TT数据提取' } },
```

注意：放在 `/tt` 的 `children` 内会走 `TtView` 的顶部 tab 布局（`TtView.vue` 里 `<router-view>` 渲染子页面，且 `activeTab` 默认回落 products）。但 `TtView` 顶部 tab 只有 4 项、没有「数据提取」tab，因此子页面会显示在无对应 tab 高亮的状态下。

**更推荐**：参照 FB 的 `/fb/extract` 做独立路由（不挂在 `TtView` 下），页面自带 header（本页面 `h1` 已自带）。即在 TT 路由区新增：

```js
{
  path: '/tt/extract',
  component: () => import('../views/tt/TtDataExtract.vue'),
  meta: { platform: 'tt', title: 'TT数据提取' },
},
```

并**保留** `/tt` children 不变。这样侧边栏入口直接进独立页。

- [ ] **Step 1: 加独立路由**（见上）
- [ ] **Step 2: 确认 `/tt/extract` 不被 `/tt` 的 children 拦截**

---

## Task 3: 侧边栏入口

**Files:**
- Modify: `frontend/src/components/AppSidebar.vue`（`ttNavItems`）

在 `ttNavItems` 数组里，`tt-accounts` 之后、`analysis` 之前新增：

```js
{ key: 'tt-extract', icon: '📥', label: '数据提取', sections: [{ title: '提取', items: [{ icon:'📥',label:'TT数据提取',path:'/tt/extract' }] }] },
```

- [ ] **Step 1: 加入口**（见上）
- [ ] **Step 2: 检查 `visibleNavItems`/`detailSections` 无需额外处理（该入口无 admin 标记，普通用户可见）**

---

## 验证清单

- [ ] `npm run build` 通过（或 dev 无报错）
- [ ] TT 平台侧边栏出现「数据提取」入口，点击进入 `/tt/extract`
- [ ] 粘贴含「添加过滤条件」「Total」的 Google Ads 竖排样本 → 三表正确解析
- [ ] 勾选「7列 / 含广告系列ID」→ 结果变化正确
- [ ] 「一键复制」「导出 Excel」可用
- [ ] GG 做表数据、FB 数据提取不受影响（未改动相关文件）

## 后续（不在本期）

- TikTok Ads 实际格式解析适配
- 「更新你的表格」写表 + 写库 + 个人信息配置 sheet
- TT 数据管理页
