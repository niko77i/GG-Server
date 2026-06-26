<template>
  <el-dialog :model-value="visible" @update:model-value="$emit('update:visible', $event)"
    title="➕ 添加包" width="800px" top="5vh" @open="init">
    <el-form label-position="top">
      <el-form-item label="系列名前缀（可选）">
        <el-input v-model="form.prefix" placeholder="如 P222-A" />
      </el-form-item>
      <el-form-item label="系列名后缀（可选）">
        <el-input v-model="form.suffix" placeholder="如 carl" />
      </el-form-item>
      <el-form-item label="粘贴内容">
        <el-input v-model="form.text" type="textarea" :rows="6" placeholder="粘贴包含链接的文本..." />
      </el-form-item>
      <el-button @click="preview" :loading="parsing">🔍 预览解析</el-button>

      <div v-if="parsed.length" style="margin-top:8px;">
        <p>识别 <strong>{{ parsed.length }}</strong> 个包：</p>
        <el-input v-model="editText" type="textarea" :rows="Math.max(6, Math.min(parsed.length, 12))" style="font-size:12px;" />
      </div>
    </el-form>
    <template #footer>
      <el-button @click="$emit('update:visible', false)">取消</el-button>
      <el-button type="primary" @click="submit" :loading="saving" :disabled="!parsed.length">💾 添加</el-button>
    </template>
  </el-dialog>
</template>

<script setup>
import { ref, reactive } from 'vue'
import { useProductStore } from '@/stores/products'
import { ElMessage } from 'element-plus'

const props = defineProps({ visible: Boolean, prodId: Number })
const emit = defineEmits(['update:visible', 'saved'])
const store = useProductStore()
const saving = ref(false)
const parsing = ref(false)
const parsed = ref([])
const editText = ref('')

const form = reactive({ prefix: '', suffix: '', text: '' })

function init() {
  Object.assign(form, { prefix: '', suffix: '', text: '' })
  parsed.value = []
  editText.value = ''
}

async function preview() {
  if (!form.text.trim()) return
  parsing.value = true
  try {
    const res = await store.importText({
      text: form.text, prefix: form.prefix, suffix: form.suffix,
      product_name: '', kpi: '', region: '',
    })
    parsed.value = res.parsed || []
    if (!parsed.value.length) {
      ElMessage.warning('未找到有效的 Google Play 链接')
    }
    editText.value = parsed.value.map(p => (p.series_name || '') + ' | ' + (p.package_name || '') + ' | ' + (p.url || '')).join('\n')
  } catch (e) {
    ElMessage.error('解析失败：' + (e.message || '未知错误'))
  } finally {
    parsing.value = false
  }
}

async function submit() {
  // 从 editText 重新解析，确保用户的编辑生效
  const lines = editText.value.trim().split('\n').filter(Boolean)
  const pkgs = lines.map(line => {
    const parts = line.split('|').map(s => s.trim())
    return {
      series_name: parts[0] || '',
      package_name: parts[1] || '',
      url: parts[2] || '',
    }
  }).filter(p => p.url)

  if (!pkgs.length) {
    ElMessage.warning('未找到有效的链接')
    return
  }

  saving.value = true
  for (const pkg of pkgs) {
    await store.addPackage(props.prodId, { series_name: pkg.series_name, package_name: pkg.package_name, url: pkg.url })
  }
  saving.value = false
  emit('update:visible', false)
  emit('saved')
}
</script>
