<template>
  <div style="max-width:1000px;padding-top:4px;">
    <!-- 表格选择 -->
    <div style="display:flex;gap:12px;align-items:center;flex-wrap:wrap;margin-bottom:10px;">
      <el-select v-model="sheetId" placeholder="选择你的做表..." filterable clearable
                 style="width:320px;" :loading="loadingSheets" @change="loadOverview">
        <el-option v-for="s in sheets" :key="s.id"
                   :label="s.spreadsheet_name || s.spreadsheet_id"
                   :value="s.spreadsheet_id" />
      </el-select>
      <el-button type="primary" :loading="loading" :disabled="!sheetId" @click="loadOverview">🔄 读取表格</el-button>
      <span style="color:#909399;font-size:12px;">读表格第一个工作表的 A–N 列，只统计 K 列（平台实际）有值的行</span>
    </div>

    <el-alert v-if="error" :title="error" type="error" show-icon :closable="false" style="margin-bottom:10px;" />

    <el-empty v-if="!loadingSheets && !sheets.length && !error"
              description="还没有配置 Google 表格，请先到「个人中心 → Google Sheets 配置」添加做表" />

    <template v-else-if="aggregates">
      <!-- 计算进度：算到几号 -->
      <div style="background:#f0f9ff;border-left:3px solid #0284c7;border-radius:8px;padding:10px 12px;margin-bottom:12px;">
        <div style="font-size:14px;">
          <template v-if="aggregates.latest_date">
            📅 当前薪资计算到 <b style="color:#0284c7;">{{ aggregates.latest_date }}</b>
            <span style="color:#6b7280;font-size:12px;">（K 列最后一条有值的行）</span>
          </template>
          <template v-else>
            ⚠️ 表里还没有 K 列有值的行，无法计算出薪资
          </template>
        </div>
        <div style="font-size:12px;color:#6b7280;margin-top:4px;">
          共统计 {{ aggregates.rows_counted }} 行；跳过 {{ aggregates.rows_skipped_empty_k }} 行（K 未填）
          <span v-if="aggregates.sheet_name"> · 工作表「{{ aggregates.sheet_name }}」</span>
        </div>
      </div>

      <el-alert v-if="recomputeError" :title="recomputeError" type="error" show-icon
                :closable="false" style="margin-bottom:10px;" />

      <!-- 没有任何 K 有值的行：不给「总薪资 4000」这种假结果 -->
      <el-empty v-if="!salary" :image-size="80"
                description="这张表里还没有 K 列有值的行，暂无薪资可算" />

      <template v-else>
      <!-- 参数 -->
      <div style="display:flex;gap:18px;align-items:flex-end;flex-wrap:wrap;margin-bottom:6px;">
        <div>
          <div style="font-size:12px;color:#606266;margin-bottom:4px;">底薪（元）</div>
          <el-select v-model="baseSalary" style="width:150px;" @change="recompute">
            <el-option v-for="v in baseOptions" :key="v" :label="v + ' 元'" :value="v" />
          </el-select>
        </div>
        <div>
          <div style="font-size:12px;color:#606266;margin-bottom:4px;">成本（USDT）</div>
          <el-input-number v-model="cost" :min="0" :step="100" :controls="false"
                           style="width:150px;" @change="recompute" />
        </div>
        <div>
          <div style="font-size:12px;color:#606266;margin-bottom:4px;">USDT 汇率</div>
          <el-input-number v-model="usdtRate" :min="0.01" :step="0.01" :precision="2"
                           :controls="false" style="width:120px;" @change="recompute" />
        </div>
        <span style="font-size:12px;color:#909399;padding-bottom:6px;">
          按基数应落 {{ salary?.base_salary_auto ?? '-' }} 元（{{ salary?.base_salary_auto_band ?? '-' }}），可改选
        </span>
      </div>

      <el-alert v-for="w in aggregates.warnings" :key="w" :title="w" type="warning"
                :closable="false" show-icon style="margin:8px 0;" />

      <!-- 明细 -->
      <el-table :data="rows" size="small" border stripe style="margin-top:12px;">
        <el-table-column prop="label" label="项目" min-width="180" />
        <el-table-column prop="value" label="金额" min-width="150" align="right">
          <template #default="{ row }">
            <span :style="{ color: row.negative ? '#dc2626' : 'inherit' }">{{ row.value }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="note" label="说明" min-width="280" />
      </el-table>

      <div style="display:flex;justify-content:flex-end;align-items:baseline;gap:10px;margin-top:14px;">
        <span style="font-size:12px;color:#909399;">
          总薪资 = 底薪 + (消耗提成 + 利润提成) × 汇率
        </span>
        <span style="font-size:13px;color:#606266;">总薪资(RMB)</span>
        <span style="font-size:26px;font-weight:700;color:#16a34a;">{{ money(salary.total) }} 元</span>
        <span v-if="recomputing" style="font-size:12px;color:#909399;">重算中…</span>
      </div>
      </template>

      <!-- 按日期明细 -->
      <el-collapse v-if="aggregates.by_date && aggregates.by_date.length" style="margin-top:16px;">
        <el-collapse-item :title="`📆 按日期明细（${aggregates.by_date.length} 天）`" name="byday">
          <el-table :data="aggregates.by_date" size="small" border>
            <el-table-column prop="date" label="日期" min-width="110" />
            <el-table-column prop="rows" label="行数" width="70" align="right" />
            <el-table-column label="代投费" min-width="110" align="right">
              <template #default="{ row }">{{ money(row.agency_fee) }}</template>
            </el-table-column>
            <el-table-column label="纯增值" min-width="110" align="right">
              <template #default="{ row }">{{ money(row.net_value) }}</template>
            </el-table-column>
            <el-table-column label="消耗" min-width="110" align="right">
              <template #default="{ row }">{{ money(row.spend) }}</template>
            </el-table-column>
          </el-table>
        </el-collapse-item>
      </el-collapse>
    </template>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { googleSheetsApi } from '@/api/google-sheets'
import { salaryApi } from '@/api/salary'

const LS_KEY = 'salary_last_spreadsheet'
// 底薪四档：以后端 defaults.base_salary_options 为准（这里只是首帧占位）
const baseOptions = ref([4000, 6000, 8000, 10000])

const sheets = ref([])
const sheetId = ref('')
const loadingSheets = ref(false)
const loading = ref(false)
const recomputing = ref(false)
const error = ref('')
const recomputeError = ref('')
const aggregates = ref(null)
const salary = ref(null)

// 页面可调参数（默认值来自后端：成本 0 / 汇率 6.6 / 底薪默认 6000）
const baseSalary = ref(6000)
const cost = ref(0)
const usdtRate = ref(6.6)

let overviewSeq = 0  // 读表请求序号（见 loadOverview 的竞态守卫）
let lastLoadedSid = ''  // 上一次成功读表的是哪一张（用于「刷新同表」时保留用户填的参数）

function money(v) {
  const n = Number(v ?? 0)
  if (!Number.isFinite(n)) return '0.00'
  return n.toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
}

const rows = computed(() => {
  const s = salary.value
  if (!s) return []
  return [
    { label: '代投费（M 列合计）', value: money(s.agency_fee), note: 'USDT · 做表 M = F×L' },
    { label: '纯增值（F−K 合计）', value: money(s.net_value), note: 'USDT · 可为负', negative: s.net_value < 0 },
    { label: '消耗（K 列合计）', value: money(s.spend), note: 'USDT · 只算 K 有值的行' },
    { label: '基数（代投费 + 纯增值）', value: money(s.core), note: '底薪只看它，不扣成本' },
    { label: '底薪', value: money(s.base_salary), note: `人民币 · 档位 ${s.base_salary_band}` },
    { label: `消耗提成（×${s.spend_rate}）`, value: money(s.spend_bonus), note: 'USDT · 全额按档位（≥20万整体 0.003）' },
    { label: '成本', value: money(s.cost), note: 'USDT · 从利润里扣' },
    { label: '利润（基数 − 成本）', value: money(s.profit), note: s.profit < 0 ? '负利润：提成按 0，不倒扣' : 'USDT', negative: s.profit < 0 },
    { label: `利润提成（×${s.profit_rate}）`, value: money(s.profit_bonus), note: `USDT · 费率看纯增值（${s.profit_rate_band}）` },
    { label: 'USDT 小计', value: money(s.usdt_total), note: '消耗提成 + 利润提成' },
    { label: '折人民币', value: money(s.usdt_rmb), note: `${money(s.usdt_total)} × ${s.usdt_rate}` },
  ]
})

async function loadSheets() {
  loadingSheets.value = true
  error.value = ''
  try {
    const res = await googleSheetsApi.getConfig()
    sheets.value = res.sheets || []
    if (!sheets.value.length) return

    let saved = ''
    try { saved = localStorage.getItem(LS_KEY) || '' } catch { /* 隐私模式下不可用 */ }
    const has = (sid) => sheets.value.some(s => (s.spreadsheet_id || '') === sid)
    let sid = has(saved) ? saved : ''
    if (!sid) {
      // 默认选「当月」那张：配置里的 active 常停在历史月份（真机实测 active 是 2026.07），
      // 而薪资要看的是本月。找不到当月就退到列表最后一张（配置顺序即月份顺序）。
      const now = new Date()
      const monthKey = `${now.getFullYear()}.${String(now.getMonth() + 1).padStart(2, '0')}`
      const current = sheets.value.find(s => (s.spreadsheet_name || '').includes(monthKey))
      const fallback = current || sheets.value[sheets.value.length - 1]
      sid = fallback?.spreadsheet_id || ''
    }
    sheetId.value = sid
    if (sid) await loadOverview()
  } catch (e) {
    error.value = e?.response?.data?.error || '加载表格配置失败'
  } finally {
    loadingSheets.value = false
  }
}

async function loadOverview() {
  // 序号守卫：快速切换表格时会有多个请求在飞，只认最后一次 —— 否则先发的慢响应
  // 回来会把后选那张表的数据覆盖掉（口径/日期都会张冠李戴）。
  const seq = ++overviewSeq
  if (!sheetId.value) {
    // 手动清空下拉框：把上一张表的结果一并清掉，别让用户以为还在看当前选择
    aggregates.value = null
    salary.value = null
    error.value = ''
    return
  }
  loading.value = true
  error.value = ''
  try {
    const res = await salaryApi.overview(sheetId.value)
    if (seq !== overviewSeq) return
    aggregates.value = res.aggregates
    // 空表不给「总薪资 4000」的假结果（月初 K 还没填是常态）
    salary.value = res.aggregates.rows_counted ? res.salary : null
    recomputeError.value = ''
    // 换表才重置参数；点「读取表格」刷新同一张表时保留用户填的成本/汇率/底薪，
    // 否则金额会静默跳回默认值，用户以为数据变了。
    if (res.spreadsheet_id !== lastLoadedSid) {
      baseSalary.value = res.defaults.base_salary
      cost.value = res.defaults.cost
      usdtRate.value = res.defaults.usdt_rate
      if (Array.isArray(res.defaults.base_salary_options) && res.defaults.base_salary_options.length) {
        baseOptions.value = res.defaults.base_salary_options
      }
    }
    lastLoadedSid = res.spreadsheet_id
    try {
      localStorage.setItem(LS_KEY, sheetId.value)
    } catch { /* 隐私模式下 localStorage 可能抛错：不影响本次结果 */ }
    if (!res.aggregates.rows_counted) {
      ElMessage.warning('这张表里还没有 K 列有值的行')
    }
  } catch (e) {
    if (seq !== overviewSeq) return
    aggregates.value = null
    salary.value = null
    error.value = e?.response?.data?.error || '读取表格失败'
  } finally {
    if (seq === overviewSeq) loading.value = false
  }
}

async function recompute() {
  const a = aggregates.value
  if (!a || !salary.value) return
  recomputing.value = true
  recomputeError.value = ''
  try {
    const res = await salaryApi.compute({
      agency_fee: a.agency_fee,
      net_value: a.net_value,
      spend: a.spend,
      cost: cost.value ?? 0,
      base_salary: baseSalary.value,
      usdt_rate: usdtRate.value ?? 6.6,
    })
    salary.value = res.salary
  } catch (e) {
    const msg = e?.response?.data?.error || '重算失败'
    // 旧金额还留在页面上 ⇒ 必须点明它对应的是上一次成功的参数，不是当前输入
    recomputeError.value = `${msg}（下方金额仍是上一次成功计算的结果）`
  } finally {
    recomputing.value = false
  }
}

onMounted(loadSheets)
</script>
