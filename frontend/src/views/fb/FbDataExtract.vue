<template>
  <div class="fb-panel">
    <div class="panel-header"><h2>📥 FB数据提取</h2></div>

    <!-- 输入区 -->
    <el-card>
      <el-form label-width="80px" inline>
        <el-form-item label="产品">
          <el-select v-model="selectedProductId" placeholder="选择产品" style="width:200px" @change="onProductChange">
            <el-option v-for="p in products" :key="p.id" :label="p.product_name" :value="p.id" />
          </el-select>
        </el-form-item>
        <el-form-item v-if="selectedLines.length > 1" label="线名">
          <el-select v-model="selectedLineId" placeholder="选择线名" style="width:160px">
            <el-option v-for="l in selectedLines" :key="l.id" :label="l.line_name" :value="l.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="日期">
          <el-date-picker v-model="reportDate" type="date" placeholder="选择日期" value-format="YYYY-MM-DD" />
        </el-form-item>
        <el-form-item>
          <el-checkbox v-model="sortedMode">是否排序（提取全列）</el-checkbox>
        </el-form-item>
      </el-form>
      <el-input v-model="pasteText" type="textarea" :rows="6" placeholder="在此粘贴 FB 数据透视表内容..." style="margin-bottom:12px" />
      <div style="display:flex;gap:8px">
        <el-button type="primary" :loading="parsing" @click="handleParse">🔍 解析数据</el-button>
        <el-button type="success" :disabled="!parsedData.length || !selectedProductId" :loading="saving" @click="openSaveDialog">💾 保存到数据管理</el-button>
      </div>
    </el-card>

    <!-- 解析结果区域 -->
    <template v-if="parsedData.length">
      <!-- 1. 原始数据 -->
      <el-card style="margin-top:16px">
        <template #header>
          📋 原始清洗数据 <el-tag size="small">{{ parsedData.length }} 条</el-tag>
          <span v-if="warnings.length" style="color:#e6a23c;margin-left:12px;font-size:13px">⚠ {{ warnings.join(', ') }} 的$符号超过2个</span>
          <el-button link size="small" style="float:right" @click="copyTable('rawData')">📋 一键复制</el-button>
        </template>
        <el-table :data="parsedData" stripe border size="small" max-height="350" ref="rawData">
          <el-table-column prop="account_name" label="账户名称" min-width="150" />
          <el-table-column prop="account_id" label="广告账户ID" width="170" />
          <el-table-column prop="cost" label="账号消耗" width="110">
            <template #default="{ row }">{{ row.cost?.toFixed(2) }}</template>
          </el-table-column>
          <template v-if="sortedMode">
            <el-table-column prop="impressions" label="展示次数" width="100">
              <template #default="{ row }">{{ row.impressions?.toLocaleString() }}</template>
            </el-table-column>
            <el-table-column prop="clicks" label="点击" width="80" />
            <el-table-column prop="registrations" label="完成注册" width="100" />
            <el-table-column prop="purchases" label="购物次数" width="100" />
            <el-table-column prop="cost_per_purchase" label="单词购物费用" width="130">
              <template #default="{ row }">{{ row.cost_per_purchase?.toFixed(2) }}</template>
            </el-table-column>
          </template>
        </el-table>
      </el-card>

      <!-- 2. 做表数据（按账户ID累加） -->
      <el-card style="margin-top:16px">
        <template #header>
          📑 做表数据 <el-tag size="small">{{ zbData.length }} 条</el-tag>
          <span style="margin-left:8px;font-size:13px;color:#6b7280">（按账户ID + 广告系列合并，费用累加）</span>
          <el-button link size="small" style="float:right" @click="copyTable('zbData')">📋 一键复制</el-button>
        </template>
        <el-table :data="zbData" stripe border size="small" max-height="350" ref="zbData">
          <el-table-column prop="account_name" label="账户名称" min-width="150" />
          <el-table-column prop="account_id" label="广告账户ID" width="170" />
          <el-table-column prop="cost" label="费用" width="110">
            <template #default="{ row }">{{ row.cost?.toFixed(2) }}</template>
          </el-table-column>
          <el-table-column width="20" /><el-table-column width="20" /><el-table-column width="20" /><el-table-column width="20" />
          <el-table-column prop="campaign" label="线名" min-width="120" />
        </el-table>
      </el-card>

    </template>

    <!-- 保存弹窗 -->
    <el-dialog v-model="saveDialogVisible" title="💾 保存数据" width="90%" top="3vh">
      <div style="margin-bottom:12px;font-size:13px;color:#555">
        产品：<b>{{ selectedProduct?.product_name }}</b> | 线名：<b>{{ selectedLineName }}</b> | 日期：<b>{{ reportDate }}</b>
      </div>
      <el-table :data="parsedData" stripe border size="small" max-height="400">
        <el-table-column prop="account_name" label="账户名称" min-width="140" />
        <el-table-column prop="account_id" label="账户ID" width="160" />
        <el-table-column prop="cost" label="消耗" width="100"><template #default="{row}">${{ row.cost?.toFixed(2) }}</template></el-table-column>
        <template v-if="sortedMode">
          <el-table-column prop="impressions" label="展示" width="80" />
          <el-table-column prop="clicks" label="点击" width="80" />
          <el-table-column prop="registrations" label="注册" width="80" />
          <el-table-column prop="purchases" label="购物" width="80" />
          <el-table-column prop="cost_per_purchase" label="单词购物费用" width="120" />
        </template>
      </el-table>
      <el-alert v-if="dupCount > 0" :title="`发现 ${dupCount} 条重复数据，点击保存将覆盖（UPSERT）`" type="warning" show-icon style="margin-top:12px" />
      <template #footer>
        <el-button @click="saveDialogVisible=false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="doSave">💾 确认保存 ({{ parsedData.length }} 条)</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { fbApi } from '../../api/fb'
import { ElMessage } from 'element-plus'
import { copyToClipboard } from '../../utils/clipboard'

const products = ref([]); const selectedProductId = ref(null); const selectedLineId = ref(null)
const yesterday = new Date(); yesterday.setDate(yesterday.getDate() - 1)
const reportDate = ref(yesterday.toISOString().slice(0, 10)); const sortedMode = ref(false)
const pasteText = ref(''); const parsedData = ref([]); const warnings = ref([])
const parsing = ref(false); const saving = ref(false)

const selectedLines = computed(() => {
  const p = products.value.find(p => p.id === selectedProductId.value)
  return p?.lines || []
})
// 做表数据：按账户ID累加
const zbData = computed(() => {
  const lineName = selectedLines.value.find(l => l.id === selectedLineId.value)?.line_name || ''
  const map = {}
  for (const r of parsedData.value) {
    const key = r.account_id
    if (!map[key]) {
      map[key] = {
        account_name: r.account_name,
        account_id: r.account_id,
        cost: 0,
        campaign: lineName
      }
    }
    map[key].cost += r.cost || 0
  }
  return Object.values(map).sort((a, b) => b.cost - a.cost)
})

function copyTable(type) {
  const data = type === 'zbData' ? zbData.value : parsedData.value
  if (!data.length) return
  const headers = type === 'zbData'
    ? ['账户名称', '广告账户ID', '费用', '', '', '', '', '线名']
    : sortedMode.value
      ? ['账户名称', '广告账户ID', '账号消耗', '展示次数', '点击', '完成注册', '购物次数', '单词购物费用']
      : ['账户名称', '广告账户ID', '账号消耗']
  const lines = [headers.join('\t')]
  for (const r of data) {
    if (type === 'zbData') {
      lines.push([r.account_name, r.account_id, r.cost?.toFixed(2), '', '', '', '', r.campaign].join('\t'))
    } else {
      lines.push(sortedMode.value
        ? [r.account_name, r.account_id, r.cost?.toFixed(2), r.impressions, r.clicks, r.registrations, r.purchases, r.cost_per_purchase].join('\t')
        : [r.account_name, r.account_id, r.cost?.toFixed(2)].join('\t'))
    }
  }
  copyToClipboard(lines.join('\n')).then(() => ElMessage.success('已复制 ✓'))
}

async function loadProducts() {
  try {
    const res = await fbApi.runnerProducts()
    products.value = (res.data || []).map(p => ({ ...p, sales_person_name: '' }))
    // 加载产品详情获取商务名
    for (const p of products.value) {
      try {
        const detail = await fbApi.productDetail(p.id)
        const sp = detail.data?.sales_person
        p.sales_person_name = sp?.name || ''
      } catch (e) { /* ignore */ }
    }
  } catch (e) { /* ignore */ }
}

function onProductChange() {
  selectedLineId.value = null
  const p = products.value.find(p => p.id === selectedProductId.value)
  if (p?.lines?.length === 1) selectedLineId.value = p.lines[0].id
}

async function handleParse() {
  if (!pasteText.value.trim()) return ElMessage.warning('请粘贴数据')
  parsing.value = true
  try {
    const res = await fbApi.parseExtract({ text: pasteText.value, sorted: sortedMode.value })
    parsedData.value = res.data || []
    warnings.value = res.warnings || []
    const validation = res.validation
    const count = parsedData.value.length
    const gs = res.group_size
    ElMessage.success(`解析完成：${count} 条数据（每组 ${gs} 行）`)

    // 尾部校验
    if (validation) {
      const vt = validation
      if (vt.declared_rows > 0 && vt.extracted_rows < vt.declared_rows) {
        ElMessage.warning({ message: `⚠ 复制的数据小于总行数（已提取 ${vt.extracted_rows} 行，共 ${vt.declared_rows} 行），请检查`, duration: 4000 })
      }
      if (vt.declared_spend > 0 && Math.abs(vt.extracted_spend - vt.declared_spend) > 0.01) {
        ElMessage.warning({ message: `⚠ 总消耗不一致（汇总 $${vt.extracted_spend.toFixed(2)}，报告 $${vt.declared_spend.toFixed(2)}），请刷新广告报告后重新复制数据`, duration: 4000 })
      }
    }

    if (warnings.value.length) ElMessage.warning(`${warnings.value.join('、')} 的$符号超过2个`)
  } catch (e) {
    ElMessage.error(e.response?.data?.error || '解析失败')
    parsedData.value = []
  } finally { parsing.value = false }
}

const saveDialogVisible = ref(false); const dupCount = ref(0)
const selectedProduct = computed(() => products.value.find(p => p.id === selectedProductId.value))
const selectedLineName = computed(() => selectedLines.value.find(l => l.id === selectedLineId.value)?.line_name || '')

async function openSaveDialog() {
  if (!selectedProductId.value) return ElMessage.warning('请选择产品')
  if (!reportDate.value) return ElMessage.warning('请选择日期')
  const prod = selectedProduct.value
  const ln = selectedLineName.value
  // 检查重复
  try {
    const res = await fbApi.checkDuplicates({
      product_name: prod.product_name,
      line_name: ln,
      report_date: reportDate.value,
      records: parsedData.value
    })
    dupCount.value = (res.duplicates || []).length
  } catch(e) { dupCount.value = 0 }
  saveDialogVisible.value = true
}

async function doSave() {
  const prod = selectedProduct.value
  const ln = selectedLineName.value
  saving.value = true
  try {
    await fbApi.saveExtract({
      product_name: prod.product_name,
      line_name: ln,
      report_date: reportDate.value,
      records: parsedData.value
    })
    ElMessage.success(`已保存 ${parsedData.value.length} 条` + (dupCount.value ? `（覆盖 ${dupCount.value} 条）` : '') + `，后台写表中...`)
    saveDialogVisible.value = false
    // 3秒后检查写表结果
    setTimeout(async () => {
      try {
        const r = await fbApi.lastSyncStatus()
        if (r.status === 'synced') ElMessage.success('✅ 写表成功')
        else if (r.status === 'failed') ElMessage.error(`❌ 写表失败: ${r.error_msg || ''}`)
      } catch(e) {}
    }, 1500)
  } catch (e) { ElMessage.error(e.response?.data?.error || '保存失败') }
  finally { saving.value = false }
}

onMounted(loadProducts)
</script>

<style scoped>
.fb-panel { padding: 20px; }
.panel-header { margin-bottom: 16px; }
.panel-header h2 { margin: 0; font-size: 18px; }
</style>
