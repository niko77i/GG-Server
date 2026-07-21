<template>
  <div style="max-width:600px;">
    <div style="display:grid;grid-template-columns:1fr 1fr;gap:12px;">
      <el-form-item label="地区选项"><el-input v-model="cfgRegions" type="textarea" :rows="5" /></el-form-item>
      <el-form-item label="帧类型选项"><el-input v-model="cfgFrames" type="textarea" :rows="5" /></el-form-item>
    </div>
    <el-form-item label="成效选项"><el-input v-model="cfgEffs" type="textarea" :rows="3" /></el-form-item>
    <el-form-item label="产品名称选项"><el-input v-model="cfgProds" type="textarea" :rows="3" /></el-form-item>
    <el-form-item label="审核状态选项"><el-input v-model="cfgReviewStatuses" type="textarea" :rows="3" /></el-form-item>
    <el-button type="primary" @click="saveConfig" :loading="savingCfg">保存配置</el-button>
    <span v-if="cfgMsg" style="margin-left:8px;font-size:11px;color:#059669;">{{ cfgMsg }}</span>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { useYoutubeStore } from '@/stores/youtube'

const store = useYoutubeStore()
const cfgRegions = ref('')
const cfgFrames = ref('')
const cfgEffs = ref('')
const cfgProds = ref('')
const cfgReviewStatuses = ref('')
const savingCfg = ref(false)
const cfgMsg = ref('')

function loadCfgFromStore() {
  cfgRegions.value = (store.tags.regions || []).join('\n')
  cfgFrames.value = (store.tags.frame_types || []).join('\n')
  cfgEffs.value = (store.tags.effectiveness || []).filter(Boolean).join('\n')
  cfgProds.value = (store.tags.product_names || []).join('\n')
  cfgReviewStatuses.value = (store.tags.review_statuses || []).join('\n')
}

async function saveConfig() {
  savingCfg.value = true
  await store.saveTags({
    regions: cfgRegions.value.split('\n').map(s => s.trim()).filter(Boolean),
    frame_types: cfgFrames.value.split('\n').map(s => s.trim()).filter(Boolean),
    effectiveness: cfgEffs.value.split('\n').map(s => s.trim()).filter(Boolean),
    product_names: cfgProds.value.split('\n').map(s => s.trim()).filter(Boolean),
    review_statuses: cfgReviewStatuses.value.split('\n').map(s => s.trim()).filter(Boolean),
  })
  cfgMsg.value = '已保存'
  setTimeout(() => cfgMsg.value = '', 2000)
  savingCfg.value = false
}

onMounted(() => loadCfgFromStore())
</script>
