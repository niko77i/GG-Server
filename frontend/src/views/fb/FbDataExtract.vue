<template>
  <div class="fb-panel">
    <div class="panel-header"><h2>📥 FB数据提取</h2></div>
    <el-card>
      <el-form label-width="80px" inline>
        <el-form-item label="产品"><el-select v-model="selectedProductId" placeholder="选择产品" style="width:200px" @change="onProductChange">
          <el-option v-for="p in products" :key="p.id" :label="p.product_name" :value="p.id" /></el-select></el-form-item>
        <el-form-item v-if="selectedLines.length>1" label="线名"><el-select v-model="selectedLineId" placeholder="选择线名" style="width:160px"><el-option v-for="l in selectedLines" :key="l.id" :label="l.line_name" :value="l.id" /></el-select></el-form-item>
        <el-form-item label="日期"><el-date-picker v-model="reportDate" type="date" placeholder="选择日期" value-format="YYYY-MM-DD" /></el-form-item>
        <el-form-item><el-checkbox v-model="sortedMode">是否排序（提取全列）</el-checkbox></el-form-item>
      </el-form>
      <el-input v-model="pasteText" type="textarea" :rows="8" placeholder="在此粘贴 FB 数据透视表内容..." style="margin-bottom:12px" />
      <div style="display:flex;gap:8px">
        <el-button type="primary" :loading="parsing" @click="handleParse">🔍 解析数据</el-button>
        <el-button type="success" :disabled="!parsedData.length" :loading="saving" @click="handleSave">💾 保存到数据管理</el-button>
      </div>
    </el-card>

    <!-- 解析预览 -->
    <el-card v-if="parsedData.length" style="margin-top:16px">
      <template #header>📋 解析预览 ({{ parsedData.length }} 条)
        <span v-if="warnings.length" style="color:#e6a23c;margin-left:12px">⚠ 警告: {{ warnings.join(', ') }} 的$符号超过2个</span>
      </template>
      <el-table :data="parsedData" stripe border size="small" max-height="400">
        <el-table-column prop="account_name" label="账户名称" min-width="140" />
        <el-table-column prop="account_id" label="账户ID" width="160" />
        <el-table-column prop="cost" label="消耗" width="100"><template #default="{row}">${{ row.cost?.toFixed(2) }}</template></el-table-column>
        <template v-if="sortedMode">
          <el-table-column prop="impressions" label="展示" width="90" />
          <el-table-column prop="clicks" label="点击" width="80" />
          <el-table-column prop="registrations" label="注册" width="80" />
          <el-table-column prop="purchases" label="购物" width="80" />
          <el-table-column prop="cost_per_purchase" label="单词购物费用" width="120" />
        </template>
      </el-table>
    </el-card>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { fbApi } from '../../api/fb'
import { ElMessage } from 'element-plus'

const products = ref([]); const selectedProductId = ref(null); const selectedLineId = ref(null)
const reportDate = ref(new Date().toISOString().slice(0,10)); const sortedMode = ref(false)
const pasteText = ref(''); const parsedData = ref([]); const warnings = ref([])
const parsing = ref(false); const saving = ref(false)

const selectedLines = computed(() => {
  const p = products.value.find(p => p.id === selectedProductId.value)
  return p?.lines || []
})

async function loadProducts() {
  const res = await fbApi.runnerProducts()
  products.value = res.data || []
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
    parsedData.value = res.data.data || []
    warnings.value = res.data.warnings || []
    if (warnings.value.length) ElMessage.warning(`${warnings.value.length} 个账户的$符号超过2个`)
    ElMessage.success(`解析完成，${parsedData.value.length} 条数据（每组${res.data.group_size}行）`)
  } catch(e) { ElMessage.error(e.response?.data?.error||'解析失败') }
  finally { parsing.value = false }
}

async function handleSave() {
  if (!selectedProductId.value) return ElMessage.warning('请选择产品')
  if (!reportDate.value) return ElMessage.warning('请选择日期')
  const prod = products.value.find(p => p.id === selectedProductId.value)
  const lineName = selectedLines.value.find(l => l.id === selectedLineId.value)?.line_name || ''
  saving.value = true
  try {
    await fbApi.saveExtract({
      product_name: prod.product_name,
      line_name: lineName,
      report_date: reportDate.value,
      records: parsedData.value
    })
    ElMessage.success(`已保存 ${parsedData.value.length} 条数据`)
    parsedData.value = []; pasteText.value = ''
  } catch(e) { ElMessage.error(e.response?.data?.error||'保存失败') }
  finally { saving.value = false }
}

onMounted(loadProducts)
</script>
<style scoped>.fb-panel{padding:20px}.panel-header h2{margin:0 0 16px;font-size:18px}</style>
