<template>
  <div style="max-width:600px;">
    <el-tabs v-model="importSubTab" size="small" style="margin-bottom:12px;">
      <el-tab-pane label="导入视频" name="video" />
      <el-tab-pane label="导入文案" name="copywriting" />
    </el-tabs>

    <div v-show="importSubTab === 'video'">
      <el-input v-model="importUrls" type="textarea" :rows="6" placeholder="每行一个 YouTube 链接..." />
      <div style="display:grid;grid-template-columns:repeat(4,1fr);gap:8px;margin-top:12px;">
        <el-select v-model="importRegion" placeholder="地区" size="small">
          <el-option v-for="r in store.tags.regions" :key="r" :label="r" :value="r" />
        </el-select>
        <el-select v-model="importFrame" placeholder="帧类型" size="small">
          <el-option v-for="f in store.tags.frame_types" :key="f" :label="f" :value="f" />
        </el-select>
        <el-select v-model="importEff" placeholder="成效" size="small" clearable>
          <el-option v-for="e in store.tags.effectiveness" :key="e" :label="e" :value="e" />
        </el-select>
        <el-select v-model="importProd" placeholder="产品名" size="small" clearable>
          <el-option v-for="p in store.tags.product_names" :key="p" :label="p" :value="p" />
        </el-select>
        <el-select v-model="importReview" placeholder="审核" size="small">
          <el-option v-for="s in store.tags.review_statuses" :key="s" :label="s" :value="s" />
        </el-select>
        <el-date-picker v-model="importTime" type="datetime" placeholder="视频时间（可选）"
          size="small" format="YYYY-MM-DD HH:mm" value-format="YYYY-MM-DD HH:mm" :clearable="true" />
      </div>
      <div style="display:flex;align-items:center;gap:12px;margin-top:10px;">
        <span style="font-size:13px;color:#606266;">可见范围：</span>
        <el-radio-group v-if="canChooseScope" v-model="importIsPublic" size="small">
          <el-radio-button :value="false">🔒 私有</el-radio-button>
          <el-radio-button :value="true">🌐 公开</el-radio-button>
        </el-radio-group>
        <el-tag v-else size="small" type="info">🌐 公开</el-tag>
        <span v-if="!canChooseScope" style="font-size:11px;color:#999;">（普通用户仅可导入公开视频）</span>
        <el-button type="primary" @click="doImport" :loading="importing" style="margin-left:auto;">保存视频</el-button>
      </div>
      <div v-if="importResult" style="margin-top:8px;font-size:12px;">{{ importResult }}</div>
    </div>

    <div v-show="importSubTab === 'copywriting'">
      <el-select v-model="cwImportRegion" placeholder="地区" size="small" style="width:100%;margin-bottom:12px;">
        <el-option v-for="r in store.tags.regions" :key="r" :label="r" :value="r" />
      </el-select>
      <el-select v-model="cwImportEff" placeholder="成效（可选）" size="small" clearable style="width:100%;margin-bottom:12px;">
        <el-option v-for="e in store.tags.effectiveness" :key="e" :label="e || '(空)'" :value="e" />
      </el-select>
      <div style="display:flex;align-items:center;gap:12px;margin-bottom:12px;">
        <span style="font-size:13px;color:#606266;">可见范围：</span>
        <el-radio-group v-if="canChooseScope" v-model="cwImportPublic" size="small">
          <el-radio-button :value="false">🔒 私有</el-radio-button>
          <el-radio-button :value="true">🌐 公开</el-radio-button>
        </el-radio-group>
        <el-tag v-else size="small" type="info">🌐 公开</el-tag>
      </div>
      <el-input v-model="cwImportText" type="textarea" :rows="8" placeholder="每行一条文案，空行自动跳过" />
      <el-button type="primary" @click="cwDoImport" :loading="cwImporting" style="margin-top:12px;">导入文案</el-button>
      <div v-if="cwImportResult" style="margin-top:8px;font-size:12px;">{{ cwImportResult }}</div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed } from 'vue'
import { useYoutubeStore } from '@/stores/youtube'
import { useAuthStore } from '@/stores/auth'
import { youtubeApi, copywritingApi } from '@/api/youtube'

const store = useYoutubeStore()
const authStore = useAuthStore()

const importSubTab = ref('video')
const importUrls = ref('')
const importRegion = ref('通用')
const importFrame = ref('非融帧')
const importEff = ref('')
const importProd = ref('')
const importReview = ref('能过审')
const importTime = ref('')
const importIsPublic = ref(!authStore.isAdmin)
const importing = ref(false)
const importResult = ref('')
const canChooseScope = computed(() => authStore.isAdmin)

async function doImport() {
  const urls = importUrls.value.split(/[\n,]+/).map(s => s.trim()).filter(s => s && s.includes('youtu'))
  if (!urls.length) return
  importing.value = true
  const res = await youtubeApi.import({
    urls,
    region: importRegion.value,
    frame_type: importFrame.value,
    effectiveness: importEff.value,
    product_name: importProd.value,
    review_status: importReview.value,
    imported_at: importTime.value || undefined,
    is_public: canChooseScope.value ? (importIsPublic.value ? 1 : 0) : 1,
  })
  importResult.value = `导入 ${res.imported} 个，重复 ${(res.duplicates || []).length} 个`
  importUrls.value = ''
  importTime.value = ''
  importing.value = false
  store.loadVideos()
}

const cwImportText = ref('')
const cwImportPublic = ref(false)
const cwImportRegion = ref('通用')
const cwImportEff = ref('')
const cwImporting = ref(false)
const cwImportResult = ref('')

async function cwDoImport() {
  const text = cwImportText.value.trim()
  if (!text) return
  cwImporting.value = true
  try {
    const res = await copywritingApi.import({
      text, region: cwImportRegion.value, effectiveness: cwImportEff.value,
      is_public: canChooseScope.value ? (cwImportPublic.value ? 1 : 0) : 1,
    })
    cwImportResult.value = `导入 ${res.imported} 条`
    cwImportText.value = ''
    store.loadCopywritings()
  } catch (e) {
    cwImportResult.value = '导入失败: ' + (e.response?.data?.error || e.message)
  } finally {
    cwImporting.value = false
  }
}
</script>
