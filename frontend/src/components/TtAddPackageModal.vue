<template>
  <el-dialog :model-value="visible" @update:model-value="$emit('update:visible', $event)"
    title="➕ 添加包" width="800px" top="5vh" @open="init">
    <el-form label-position="top">
      <el-form-item label="系列名前缀（可选）">
        <el-input v-model="form.prefix" placeholder="如 P222-A" />
      </el-form-item>
      <el-form-item label="粘贴内容">
        <el-input v-model="form.text" type="textarea" :rows="6" placeholder="粘贴包含 Google Play / App Store 链接的文本..." />
      </el-form-item>
      <el-button @click="preview" :loading="parsing">🔍 预览解析</el-button>

      <div v-if="parsed.length" style="margin-top:8px;">
        <p>识别 <strong>{{ parsed.length }}</strong> 个包：</p>
        <el-table :data="parsed" size="small" max-height="250">
          <el-table-column label="类型" width="80">
            <template #default="{ row }">
              <el-select v-model="row.type" size="small" style="width:70px;">
                <el-option label="跑包" value="package" />
                <el-option label="PWA" value="pwa" />
              </el-select>
            </template>
          </el-table-column>
          <el-table-column label="系列名">
            <template #default="{ row }"><el-input v-model="row.series_name" size="small" /></template>
          </el-table-column>
          <el-table-column label="包名">
            <template #default="{ row }"><el-input v-model="row.package_name" size="small" :disabled="row.type === 'pwa'" /></template>
          </el-table-column>
          <el-table-column label="链接">
            <template #default="{ row }"><el-input v-model="row.url" size="small" /></template>
          </el-table-column>
          <el-table-column width="50">
            <template #default="{ $index }">
              <el-button size="small" type="danger" @click="parsed.splice($index, 1)">✕</el-button>
            </template>
          </el-table-column>
        </el-table>
      </div>

      <el-divider content-position="left">手动添加</el-divider>
      <div style="display:flex;gap:8px;flex-wrap:wrap;align-items:center;">
        <el-select v-model="manual.type" size="small" style="width:80px;">
          <el-option label="跑包" value="package" />
          <el-option label="PWA" value="pwa" />
        </el-select>
        <el-input v-model="manual.series_name" size="small" placeholder="系列名" style="width:140px;" />
        <el-input v-model="manual.package_name" size="small" placeholder="包名（仅跑包）" :disabled="manual.type === 'pwa'" style="width:180px;" />
        <el-input v-model="manual.url" size="small" placeholder="链接" style="flex:1;min-width:200px;" />
        <el-button size="small" type="primary" @click="addManual" :loading="manualSaving">添加</el-button>
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
import { ttApi } from '@/api/tt'
import { ElMessage } from 'element-plus'

// App Store 的两个合法 host（与后端 _is_appstore_url 同口径）
const APPSTORE_HOSTS = ['apps.apple.com', 'itunes.apple.com']
function isAppstoreUrl(url) {
  try {
    return APPSTORE_HOSTS.includes(new URL(String(url || '').trim()).hostname.toLowerCase())
  } catch {
    return false
  }
}

const props = defineProps({ visible: Boolean, prodId: Number })
const emit = defineEmits(['update:visible', 'saved'])
const saving = ref(false)
const parsing = ref(false)
const manualSaving = ref(false)
const parsed = ref([])
const form = reactive({ prefix: '', text: '' })
const manual = reactive({ type: 'package', series_name: '', package_name: '', url: '' })

function init() {
  Object.assign(form, { prefix: '', text: '' })
  parsed.value = []
  Object.assign(manual, { type: 'package', series_name: '', package_name: '', url: '' })
}

async function preview() {
  if (!form.text.trim()) return ElMessage.warning('请粘贴文本')
  parsing.value = true
  try {
    const res = await ttApi.importText({ text: form.text, prefix: form.prefix })
    parsed.value = (res.parsed || []).map(p => ({ type: p.type || 'package', series_name: p.series_name, package_name: p.package_name, url: p.url }))
    if (!parsed.value.length) ElMessage.warning('未找到有效的 Google Play / App Store 链接')
  } catch (e) { ElMessage.error(e.response?.data?.error || '解析失败') }
  finally { parsing.value = false }
}

async function addManual() {
  if (!manual.url.trim()) return ElMessage.warning('请输入链接')
  if (manual.type === 'package' && !manual.package_name.trim() && !isAppstoreUrl(manual.url)) {
    return ElMessage.warning('跑包必须填写包名（App Store 链接可留空）')
  }
  manualSaving.value = true
  try {
    await ttApi.addPackage(props.prodId, {
      type: manual.type,
      series_name: manual.series_name,
      package_name: manual.type === 'pwa' ? '' : manual.package_name,
      url: manual.url,
    })
    ElMessage.success('已添加')
    Object.assign(manual, { type: 'package', series_name: '', package_name: '', url: '' })
    emit('saved')
  } catch (e) { ElMessage.error(e.response?.data?.error || '添加失败') }
  finally { manualSaving.value = false }
}

async function submit() {
  if (!parsed.value.length) return
  saving.value = true
  try {
    for (const pkg of parsed.value) {
      await ttApi.addPackage(props.prodId, {
        type: pkg.type || 'package',
        series_name: pkg.series_name,
        package_name: pkg.type === 'pwa' ? '' : pkg.package_name,
        url: pkg.url,
      })
    }
    ElMessage.success(`已添加 ${parsed.value.length} 个包`)
    emit('update:visible', false)
    emit('saved')
  } catch (e) { ElMessage.error(e.response?.data?.error || '添加失败') }
  finally { saving.value = false }
}
</script>
