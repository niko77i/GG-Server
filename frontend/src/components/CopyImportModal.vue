<template>
  <el-dialog :model-value="visible" @update:model-value="$emit('update:visible', $event)"
    title="📋 复制导入" width="95vw" top="2vh" @open="init">
    <el-form label-position="top">
      <el-form-item label="产品 / 群名">
        <el-select v-model="form.product_name" filterable allow-create placeholder="选择已有或输入新产品名" style="width:100%;">
          <el-option v-for="p in productNames" :key="p.name" :label="p.name" :value="p.name" />
        </el-select>
      </el-form-item>
      <el-form-item label="KPI">
        <el-input v-model="form.kpi" />
      </el-form-item>
      <el-form-item label="地区">
        <el-input v-model="form.region" />
      </el-form-item>
      <el-form-item label="系列名前缀（可选）">
        <el-input v-model="form.prefix" placeholder="如 P222-A" />
      </el-form-item>
      <el-form-item label="系列名后缀（可选）">
        <el-input v-model="form.suffix" placeholder="如 carl" />
      </el-form-item>
      <el-form-item label="粘贴内容">
        <el-input v-model="form.text" type="textarea" :rows="6" placeholder="粘贴包含链接的文本..." />
      </el-form-item>
      <el-button @click="preview" :loading="parsing">🔍 预览解析结果</el-button>

      <div v-if="parsed.length" style="margin-top:8px;">
        <p>识别 <strong>{{ parsed.length }}</strong> 个包：</p>
        <el-table :data="parsed" size="small" max-height="250">
          <el-table-column prop="series_name" label="系列名">
            <template #default="{ row, $index }">
              <el-input v-model="parsed[$index].series_name" size="small" />
            </template>
          </el-table-column>
          <el-table-column prop="package_name" label="包名" />
          <el-table-column prop="url" label="链接">
            <template #default="{ row }">
              <span style="font-size:11px;">{{ row.url }}</span>
            </template>
          </el-table-column>
          <el-table-column width="50">
            <template #default="{ $index }">
              <el-button size="small" type="danger" @click="parsed.splice($index, 1)">✕</el-button>
            </template>
          </el-table-column>
        </el-table>
      </div>
    </el-form>
    <template #footer>
      <el-button @click="$emit('update:visible', false)">取消</el-button>
      <el-button type="primary" @click="submit" :loading="saving" :disabled="!parsed.length">💾 导入</el-button>
    </template>
  </el-dialog>
</template>

<script setup>
import { ref, reactive, onMounted } from 'vue'
import { useProductStore } from '@/stores/products'
import { ElMessage } from 'element-plus'

const props = defineProps({ visible: Boolean })
const emit = defineEmits(['update:visible', 'saved'])
const store = useProductStore()
const saving = ref(false)
const parsing = ref(false)
const parsed = ref([])
const productNames = ref([])

const form = reactive({ product_name: '', kpi: '', region: '', prefix: '', suffix: '', text: '' })

onMounted(async () => {
  const res = await store.loadProducts()
  productNames.value = (res.products || []).map(p => ({ name: p.product_name, kpi: p.kpi, region: p.region }))
})

function init() {
  Object.assign(form, { product_name: '', kpi: '', region: '', prefix: '', suffix: '', text: '' })
  parsed.value = []
}

async function preview() {
  if (!form.text.trim()) return
  parsing.value = true
  try {
    const res = await store.importText({
      text: form.text, product_name: form.product_name || '',
      kpi: form.kpi, region: form.region,
      prefix: form.prefix, suffix: form.suffix,
    })
    parsed.value = res.parsed || []
    if (!parsed.value.length) {
      ElMessage.warning('未找到有效的 Google Play 链接')
    }
  } catch (e) {
    ElMessage.error('解析失败：' + (e.message || '未知错误'))
  } finally {
    parsing.value = false
  }
}

async function submit() {
  if (!parsed.value.length) return
  saving.value = true
  await store.createProduct({
    product_name: form.product_name || parsed.value[0].package_name,
    kpi: form.kpi, region: form.region,
    packages: parsed.value.map(p => ({ series_name: p.series_name, package_name: p.package_name, url: p.url })),
  })
  saving.value = false
  emit('update:visible', false)
  emit('saved')
}
</script>
