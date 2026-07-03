<template>
  <div style="display:flex;flex-direction:column;height:calc(100vh - 72px);">
    <h1 style="flex-shrink:0;">📊 数据分析</h1>

    <!-- 筛选栏 -->
    <div style="flex-shrink:0;display:flex;gap:10px;margin-bottom:12px;flex-wrap:wrap;align-items:center;">
      <el-select v-model="filterProduct" placeholder="全部产品" clearable style="width:160px;" filterable @change="refreshAll">
        <el-option v-for="p in filterProducts" :key="p" :label="p" :value="p" />
      </el-select>
      <el-select v-model="filterRegion" placeholder="全部地区" clearable style="width:140px;" @change="refreshAll">
        <el-option v-for="r in filterRegions" :key="r" :label="r" :value="r" />
      </el-select>
      <el-date-picker v-model="filterDateRange" type="daterange" range-separator="~" start-placeholder="开始" end-placeholder="结束"
        value-format="YYYY-MM-DD" style="width:260px;" @change="refreshAll" popper-class="analysis-date-picker" :cell-class-name="dateCellClass" />
      <el-button @click="refreshAll">🔄 刷新</el-button>
    </div>

    <!-- Tab 页 -->
    <div style="flex:1;min-height:0;overflow-y:auto;">
      <el-tabs v-model="activeTab" type="border-card">
        <!-- 仪表盘 -->
        <el-tab-pane label="📊 仪表盘" name="dashboard">
          <div v-if="dashboardData" style="padding:8px;">
            <div style="display:flex;gap:16px;align-items:flex-start;">
              <div style="flex:1;">
                <div style="display:flex;gap:12px;flex-wrap:wrap;margin-bottom:16px;">
                  <div class="stat-card"><div class="stat-val">${{ (dashboardData.summary.total_cost || 0).toLocaleString() }}</div><div class="stat-label">总花费</div></div>
                  <div class="stat-card"><div class="stat-val">{{ (dashboardData.summary.total_impressions || 0).toLocaleString() }}</div><div class="stat-label">总展示</div></div>
                  <div class="stat-card"><div class="stat-val">{{ (dashboardData.summary.total_installs || 0).toLocaleString() }}</div><div class="stat-label">总安装</div></div>
                  <div class="stat-card"><div class="stat-val">{{ (dashboardData.summary.total_in_app || 0).toLocaleString() }}</div><div class="stat-label">应用内操作</div></div>
                  <div class="stat-card">
                    <div class="stat-val">${{ dashboardData.summary.avg_cpi || 0 }}</div>
                    <div class="stat-label">
                      每次操作费用
                      <span v-if="dashboardData.summary.product_kpi != null" :style="{color: dashboardData.summary.kpi_met ? '#16a34a' : '#dc2626'}">
                        / KPI ${{ dashboardData.summary.product_kpi }}
                        {{ dashboardData.summary.kpi_met ? '✓' : '✗' }}
                      </span>
                    </div>
                  </div>
                  <div class="stat-card"><div class="stat-val">{{ ((dashboardData.summary.avg_ctr || 0) * 100).toFixed(2) }}%</div><div class="stat-label">CTR</div></div>
                  <div class="stat-card"><div class="stat-val">{{ ((dashboardData.summary.avg_cvr || 0) * 100).toFixed(2) }}%</div><div class="stat-label">CVR</div></div>
                </div>
              </div>
              <div style="width:200px;flex-shrink:0;background:#f5f7fa;border-radius:8px;padding:12px;font-size:12px;line-height:1.8;">
                <div style="font-weight:600;margin-bottom:4px;color:#303133;">📖 指标说明</div>
                <div><b>CPI</b> — Cost Per In-app Action，每次应用内操作费用（花费 ÷ 应用内操作数）</div>
                <div><b>CTR</b> — Click Through Rate，点击率（点击 ÷ 展示 × 100%）</div>
                <div><b>CVR</b> — Conversion Rate，安装转化率（安装 ÷ 点击 × 100%）</div>
                <div><b>KPI</b> — 产品目标 CPI，实际 ≤ KPI 为消耗合格 ✓</div>
              </div>
            </div>

            <div v-if="dashboardData.period_compare && Object.keys(dashboardData.period_compare).length" style="margin-bottom:12px;font-size:13px;color:#666;">
              环比变化：
              <span v-if="dashboardData.period_compare.cost_change_pct !== undefined" :style="{color: dashboardData.period_compare.cost_change_pct > 0 ? '#dc2626' : '#16a34a'}">
                花费 {{ dashboardData.period_compare.cost_change_pct > 0 ? '↑' : '↓' }}{{ Math.abs(dashboardData.period_compare.cost_change_pct) }}%
              </span>
              <span v-if="dashboardData.period_compare.installs_change_pct !== undefined" :style="{color: dashboardData.period_compare.installs_change_pct > 0 ? '#16a34a' : '#dc2626'}" style="margin-left:12px;">
                安装 {{ dashboardData.period_compare.installs_change_pct > 0 ? '↑' : '↓' }}{{ Math.abs(dashboardData.period_compare.installs_change_pct) }}%
              </span>
            </div>

            <div v-if="dashboardData.anomalies?.length" style="margin-bottom:12px;">
              <div style="font-weight:600;color:#dc2626;margin-bottom:6px;">⚠️ 异常提醒</div>
              <div v-for="(a, i) in dashboardData.anomalies" :key="i" style="font-size:13px;color:#666;margin-bottom:2px;">
                · {{ a.date }} {{ a.campaign }}：{{ a.detail }}
              </div>
            </div>

            <div v-if="dashboardData.asset_count !== undefined" style="font-size:13px;color:#666;">
              🎬 成效素材关联：{{ dashboardData.asset_count }} 个
            </div>
          </div>
          <el-empty v-else description="暂无数据，请先保存做表数据" />
        </el-tab-pane>

        <!-- 趋势 -->
        <el-tab-pane label="📈 趋势" name="trends">
          <div style="margin-bottom:8px;">
            指标：
            <el-radio-group v-model="trendMetric" size="small" @change="loadTrends">
              <el-radio-button value="cpi">CPI</el-radio-button>
              <el-radio-button value="cost">花费</el-radio-button>
              <el-radio-button value="installs">安装</el-radio-button>
              <el-radio-button value="ctr">CTR</el-radio-button>
            </el-radio-group>
          </div>
          <div v-if="trendSeries.length" ref="trendChart" style="width:100%;height:360px;"></div>
          <el-empty v-else description="暂无趋势数据" />
        </el-tab-pane>

        <!-- 对比 -->
        <el-tab-pane label="📋 对比" name="compare">
          <div style="margin-bottom:8px;">
            分组：
            <el-radio-group v-model="compareGroupBy" size="small" @change="loadCompare">
              <el-radio-button value="product_name">按产品</el-radio-button>
              <el-radio-button value="campaign">按系列</el-radio-button>
            </el-radio-group>
          </div>
          <el-table :data="compareItems" size="small" border stripe max-height="400" v-if="compareItems.length">
            <el-table-column prop="name" label="名称" min-width="140" />
            <el-table-column prop="total_cost" label="花费" width="100" sortable>
              <template #default="{row}">${{ (row.total_cost || 0).toFixed(0) }}</template>
            </el-table-column>
            <el-table-column prop="total_installs" label="安装" width="80" sortable>
              <template #default="{row}">{{ (row.total_installs || 0).toLocaleString() }}</template>
            </el-table-column>
            <el-table-column prop="avg_cpi" label="CPI" width="90" sortable>
              <template #default="{row}">${{ (row.avg_cpi || 0).toFixed(2) }}</template>
            </el-table-column>
            <el-table-column prop="ctr" label="CTR" width="80" sortable>
              <template #default="{row}">{{ ((row.ctr || 0) * 100).toFixed(2) }}%</template>
            </el-table-column>
            <el-table-column prop="cvr" label="CVR" width="80" sortable>
              <template #default="{row}">{{ ((row.cvr || 0) * 100).toFixed(2) }}%</template>
            </el-table-column>
            <el-table-column prop="total_impressions" label="展示" width="90" sortable>
              <template #default="{row}">{{ (row.total_impressions || 0).toLocaleString() }}</template>
            </el-table-column>
          </el-table>
          <el-empty v-else description="暂无对比数据" />
        </el-tab-pane>

        <!-- 跨用户 -->
        <el-tab-pane label="👥 跨用户" name="crossUser">
          <el-table :data="crossUserData" size="small" border stripe v-if="crossUserData.length">
            <el-table-column prop="display_name" label="用户" width="140">
              <template #default="{row}">{{ row.display_name || row.username || 'User#'+row.user_id }}</template>
            </el-table-column>
            <el-table-column prop="total_cost" label="花费">
              <template #default="{row}">${{ (row.total_cost || 0).toFixed(0) }}</template>
            </el-table-column>
            <el-table-column prop="total_installs" label="安装">
              <template #default="{row}">{{ (row.total_installs || 0).toLocaleString() }}</template>
            </el-table-column>
            <el-table-column prop="avg_cpi" label="CPI">
              <template #default="{row}">${{ (row.avg_cpi || 0).toFixed(2) }}</template>
            </el-table-column>
            <el-table-column prop="report_days" label="上报天数" width="80" />
          </el-table>
          <el-empty v-else description="请先选择产品" />
        </el-tab-pane>

        <!-- AI 分析 -->
        <el-tab-pane label="🤖 AI分析" name="ai">
          <div v-if="aiEnabled === false" style="color:#999;text-align:center;padding:40px;">
            AI 分析未启用，请联系管理员在 config.json 中设置 ai_analysis.enabled = true
          </div>
          <div v-else-if="aiEnabled === null" style="text-align:center;padding:40px;">加载中...</div>
          <div v-else style="display:flex;flex-direction:column;height:400px;">
            <div style="flex:1;min-height:0;overflow-y:auto;background:#f5f7fa;padding:12px;border-radius:8px;margin-bottom:8px;">
              <div v-if="!aiMessages.length" style="color:#999;text-align:center;padding-top:60px;">
                💬 输入问题开始 AI 分析
              </div>
              <div v-for="(msg, i) in aiMessages" :key="i" style="margin-bottom:8px;">
                <div v-if="msg.role === 'user'" style="text-align:right;">
                  <span style="background:#409eff;color:#fff;padding:6px 12px;border-radius:12px;display:inline-block;max-width:80%;font-size:13px;">{{ msg.content }}</span>
                </div>
                <div v-else style="text-align:left;">
                  <span style="background:#fff;padding:8px 14px;border-radius:12px;display:inline-block;max-width:85%;font-size:13px;white-space:pre-wrap;border:1px solid #e5e7eb;">{{ msg.content }}</span>
                </div>
              </div>
              <div v-if="aiLoading" style="text-align:left;color:#999;">分析中...</div>
            </div>
            <div style="display:flex;gap:8px;">
              <el-input v-model="aiQuestion" placeholder="输入问题，如：哪个系列 CPI 最低？" @keyup.enter="askAI" />
              <el-button type="primary" @click="askAI" :loading="aiLoading">发送</el-button>
            </div>
          </div>
        </el-tab-pane>
      </el-tabs>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, nextTick, watch } from 'vue'
import { reportsApi } from '@/api/reports'
import { ElMessage } from 'element-plus'
import api from '@/api/client'

const activeTab = ref('dashboard')
const filterProduct = ref('')
const filterRegion = ref('')
const filterDateRange = ref(null)
const filterProducts = ref([])
const filterRegions = ref([])
const dateDates = ref({})  // { "YYYY-MM-DD": count }
const dateSet = computed(() => new Set(Object.keys(dateDates.value)))

function dateCellClass(date) {
  const y = date.getFullYear()
  const m = String(date.getMonth() + 1).padStart(2, '0')
  const d = String(date.getDate()).padStart(2, '0')
  return dateSet.value.has(`${y}-${m}-${d}`) ? 'has-data' : ''
}

// 仪表盘
const dashboardData = ref(null)

// 趋势
const trendMetric = ref('cpi')
const trendSeries = ref([])
const trendChart = ref(null)
let echartsInst = null

// 对比
const compareGroupBy = ref('product_name')
const compareItems = ref([])

// 跨用户
const crossUserData = ref([])

// AI
const aiEnabled = ref(null)
const aiMessages = ref([])
const aiQuestion = ref('')
const aiLoading = ref(false)

// 筛选参数
function filterParams() {
  const p = {}
  if (filterProduct.value) p.product_name = filterProduct.value
  if (filterRegion.value) p.region = filterRegion.value
  if (filterDateRange.value) {
    p.from_date = filterDateRange.value[0]
    p.to_date = filterDateRange.value[1]
  }
  return p
}

async function refreshAll() {
  loadDates()
  loadDashboard()
  loadTrends()
  loadCompare()
  loadCrossUser()
}

async function loadDates() {
  try {
    const res = await api.get('/ad-reports/dates', { params: filterParams() })
    dateDates.value = res.dates || {}
  } catch { dateDates.value = {} }
}

async function loadDashboard() {
  try {
    const res = await reportsApi.dashboard(filterParams())
    dashboardData.value = res
  } catch { dashboardData.value = null }
}

async function loadTrends() {
  try {
    const res = await reportsApi.trends({ ...filterParams(), metric: trendMetric.value })
    trendSeries.value = res.series || []
    await nextTick()
    renderTrendChart()
  } catch { trendSeries.value = [] }
}

function renderTrendChart() {
  if (!trendChart.value || !trendSeries.value.length) return
  // 懒加载 ECharts
  if (!echartsInst) {
    try {
      const ec = window.echarts || require('echarts')
      echartsInst = ec
    } catch { return }
  }
  let chart = trendChart.value._echart
  if (!chart) {
    chart = echartsInst.init(trendChart.value)
    trendChart.value._echart = chart
  }
  chart.setOption({
    tooltip: { trigger: 'axis' },
    legend: { data: trendSeries.value.map(s => s.name), bottom: 0 },
    grid: { left: 60, right: 30, top: 20, bottom: 30 },
    xAxis: { type: 'category', data: [...new Set(trendSeries.value.flatMap(s => s.data.map(d => d.date)))].sort() },
    yAxis: { type: 'value' },
    series: trendSeries.value.map(s => ({
      name: s.name, type: 'line', data: s.data.map(d => d.value),
      smooth: true,
    })),
  }, true)
}

async function loadCompare() {
  try {
    const res = await reportsApi.compare({ ...filterParams(), group_by: compareGroupBy.value })
    compareItems.value = res.items || []
  } catch { compareItems.value = [] }
}

async function loadCrossUser() {
  if (!filterProduct.value) { crossUserData.value = []; return }
  try {
    const res = await reportsApi.crossUser({ ...filterParams() })
    crossUserData.value = res.users || []
  } catch { crossUserData.value = [] }
}

async function checkAIEnabled() {
  try {
    const res = await reportsApi.analyze({ question: '', filters: {} })
    aiEnabled.value = res.enabled
  } catch { aiEnabled.value = false }
}

async function askAI() {
  const q = aiQuestion.value.trim()
  if (!q) return
  aiQuestion.value = ''
  aiMessages.value.push({ role: 'user', content: q })
  aiLoading.value = true
  try {
    const res = await reportsApi.analyze({ question: q, filters: filterParams() })
    if (!res.enabled) {
      aiMessages.value.push({ role: 'assistant', content: 'AI 分析未启用。' })
    } else {
      aiMessages.value.push({ role: 'assistant', content: res.answer || '暂无回复' })
    }
  } catch (e) {
    aiMessages.value.push({ role: 'assistant', content: '请求失败: ' + (e.message || '') })
  }
  aiLoading.value = false
}

// 初始化加载筛选选项
async function loadFilterOptions() {
  try {
    const res = await reportsApi.list({ size: 1 })
    filterProducts.value = res.products || []
    filterRegions.value = res.regions || []
  } catch {}
}

onMounted(() => {
  loadFilterOptions()
  loadDates()
  loadDashboard()
  checkAIEnabled()
})

// 切换到趋势 tab 时加载
watch(activeTab, (tab) => {
  if (tab === 'trends') loadTrends()
  if (tab === 'compare') loadCompare()
  if (tab === 'crossUser') loadCrossUser()
  if (tab === 'ai') checkAIEnabled()
})
</script>

<style scoped>
.stat-card {
  background: #f5f7fa;
  border-radius: 8px;
  padding: 16px 20px;
  min-width: 120px;
  text-align: center;
}
.stat-val {
  font-size: 22px;
  font-weight: 700;
  color: #303133;
}
.stat-label {
  font-size: 12px;
  color: #909399;
  margin-top: 4px;
}
</style>

<style>
.analysis-date-picker .has-data {
  background: #ecf5ff;
}
.analysis-date-picker .has-data .el-date-table-cell__text {
  position: relative;
}
.analysis-date-picker .has-data .el-date-table-cell__text::after {
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
