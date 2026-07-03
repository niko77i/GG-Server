<template>
  <div>
    <h2>⚙ 设置</h2>
    <el-tabs v-model="activeTab">
      <!-- Tab 1: 账户设置 -->
      <el-tab-pane label="账户设置" name="account">
        <p style="color:#888;margin-bottom:20px;">自定义下拉框选项，修改后全局生效</p>
        <el-row :gutter="16">
          <el-col :span="12">
            <el-form-item label="账户状态选项">
              <el-input v-model="form.account_statuses" type="textarea" :rows="5"
                placeholder="每行一个" />
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="代理名选项">
              <el-input v-model="form.account_agents" type="textarea" :rows="5"
                placeholder="每行一个（留空则自由输入）" />
            </el-form-item>
          </el-col>
        </el-row>
        <el-form-item label="MCC 等级选项">
          <el-input v-model="form.mcc_levels" type="textarea" :rows="3"
            placeholder="每行一个（留空则自由输入）" />
        </el-form-item>
        <el-button type="primary" @click="save" :loading="saving">💾 保存配置</el-button>
        <span v-if="msg" style="margin-left:8px;font-size:11px;color:#059669;">{{ msg }}</span>
      </el-tab-pane>

      <!-- Tab 2: 地区时区 -->
      <el-tab-pane label="地区时区" name="region">
        <p style="color:#888;margin-bottom:12px;">地区对应的时区，产品数据分析时使用</p>
        <el-table :data="regionList" size="small" border stripe style="max-width:450px;">
          <el-table-column prop="name" label="地区" width="120" />
          <el-table-column label="时区" min-width="200">
            <template #default="{ row }">
              <el-select v-model="row._editTz" placeholder="选择时区" size="small" style="width:100%;" filterable @change="v => saveRegionTz(row, v)">
                <el-option v-for="tz in timezoneOptions" :key="tz" :label="tz" :value="tz" />
              </el-select>
            </template>
          </el-table-column>
        </el-table>
        <div style="display:flex;gap:8px;margin-top:8px;max-width:450px;">
          <el-input v-model="newRegionName" placeholder="新地区名" size="small" style="flex:1;" />
          <el-select v-model="newRegionTz" placeholder="时区" size="small" style="width:170px;" filterable>
            <el-option v-for="tz in timezoneOptions" :key="tz" :label="tz" :value="tz" />
          </el-select>
          <el-button size="small" type="primary" @click="addRegion">新增</el-button>
        </div>
      </el-tab-pane>

      <!-- Tab 3: 数据管理 -->
      <el-tab-pane label="数据管理" name="data">
        <el-row :gutter="20">
          <!-- 导出区 -->
          <el-col :span="12">
            <el-card shadow="hover">
              <template #header>📤 导出数据</template>
              <p style="color:#888;margin-bottom:12px;">导出你的所有数据为 JSON 文件，可用于备份或迁移。</p>
              <el-button type="primary" @click="exportData" :loading="exporting">
                📥 导出我的数据
              </el-button>
            </el-card>
          </el-col>

          <!-- 导入区 -->
          <el-col :span="12">
            <el-card shadow="hover">
              <template #header>📥 导入数据</template>
              <p style="color:#888;margin-bottom:12px;">
                上传 ImageCrawling 的 app.db 或 JSON 导出文件。
              </p>
              <el-upload
                :auto-upload="false"
                :on-change="onFileChange"
                :limit="1"
                accept=".db,.json"
                drag
              >
                <el-icon><UploadFilled /></el-icon>
                <div>拖拽或点击上传 .db / .json 文件</div>
              </el-upload>
              <el-button
                type="success"
                @click="confirmImport"
                :loading="importing"
                :disabled="!importFile"
                style="margin-top:10px;"
              >
                ✅ 确认导入
              </el-button>
            </el-card>
          </el-col>
        </el-row>

        <!-- 导入历史 -->
        <el-card shadow="hover" style="margin-top:20px;">
          <template #header>📋 导入历史</template>
          <el-table :data="importHistory" v-if="importHistory.length" size="small">
            <el-table-column prop="file_name" label="文件名" />
            <el-table-column prop="file_type" label="类型" width="60" />
            <el-table-column prop="products_count" label="产品" width="60" />
            <el-table-column prop="accounts_count" label="账户" width="60" />
            <el-table-column prop="videos_count" label="视频" width="60" />
            <el-table-column prop="status" label="状态" width="80">
              <template #default="{ row }">
                <el-tag :type="row.status === 'success' ? 'success' : 'danger'" size="small">
                  {{ row.status }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="created_at" label="时间" width="160" />
          </el-table>
          <el-empty v-else description="暂无导入记录" :image-size="60" />
        </el-card>
      </el-tab-pane>
    </el-tabs>
  </div>
</template>

<script setup>
import { ref, reactive, onMounted } from 'vue'
import { useAccountStore } from '@/stores/accounts'
import { dataApi } from '@/api/data'
import { UploadFilled } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import api from '@/api/client'

const store = useAccountStore()
const saving = ref(false)
const msg = ref('')
const activeTab = ref('account')

const form = reactive({
  account_statuses: '',
  account_agents: '',
  mcc_levels: '',
})

// 数据管理
const exporting = ref(false)
const importing = ref(false)
const importFile = ref(null)
const importHistory = ref([])

// 地区时区
const regionList = ref([])
const newRegionName = ref('')
const newRegionTz = ref('')
function _buildTimezoneOptions() {
  const tzs = []
  for (let i = -12; i <= 12; i++) {
    const sign = i > 0 ? '+' : ''
    tzs.push(`UTC${sign}${i}`)
  }
  tzs.push('UTC+5:30', 'UTC+8:45', 'UTC-3:30')
  return tzs
}
const timezoneOptions = _buildTimezoneOptions()

onMounted(async () => {
  await store.loadSettings()
  form.account_statuses = (store.settings.account_statuses || []).join('\n')
  form.account_agents = (store.settings.account_agents || []).join('\n')
  form.mcc_levels = (store.settings.mcc_levels || []).join('\n')
  loadImportHistory()
  loadRegions()
})

// 地区时区
async function loadRegions() {
  try {
    const res = await api.get('/regions/list')
    regionList.value = (res.regions || []).map(r => ({ ...r, _editTz: r.timezone }))
  } catch { regionList.value = [] }
}

async function saveRegionTz(row, tz) {
  try {
    await api.put(`/regions/${row.id}`, { timezone: tz })
    row.timezone = tz
    ElMessage.success(`「${row.name}」时区已更新`)
  } catch { ElMessage.error('更新失败'); row._editTz = row.timezone }
}

async function addRegion() {
  const name = newRegionName.value.trim()
  const tz = newRegionTz.value
  if (!name) { ElMessage.warning('请输入地区名'); return }
  try {
    const res = await api.post('/regions/create', { name, timezone: tz })
    regionList.value.push({ id: res.id, name, timezone: tz, _editTz: tz })
    newRegionName.value = ''
    newRegionTz.value = ''
    ElMessage.success('地区已添加')
  } catch (e) { ElMessage.error('添加失败: ' + (e.message || '')) }
}

async function save() {
  saving.value = true
  const body = {
    account_statuses: form.account_statuses.split('\n').map(s => s.trim()).filter(Boolean),
    account_agents: form.account_agents.split('\n').map(s => s.trim()).filter(Boolean),
    mcc_levels: form.mcc_levels.split('\n').map(s => s.trim()).filter(Boolean),
  }
  await store.saveSettings(body)
  store.settings = body
  msg.value = '✅ 已保存'
  setTimeout(() => msg.value = '', 2000)
  saving.value = false
}

async function exportData() {
  exporting.value = true
  try {
    const blob = await dataApi.exportData()
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    // 从 Content-Disposition 提取文件名
    a.download = `gg-server-export-${Date.now()}.json`
    a.click()
    URL.revokeObjectURL(url)
    ElMessage.success('导出成功')
  } catch (e) {
    ElMessage.error('导出失败: ' + (e.response?.data?.error || e.message))
  }
  exporting.value = false
}

function onFileChange(file) {
  importFile.value = file.raw
}

async function confirmImport() {
  if (!importFile.value) return
  importing.value = true
  try {
    const res = await dataApi.importFile(importFile.value)
    ElMessage.success(`导入完成：产品 ${res.report?.products || 0}，账户 ${res.report?.accounts || 0}，视频 ${res.report?.videos || 0}`)
    importFile.value = null
    loadImportHistory()
  } catch (e) {
    ElMessage.error('导入失败: ' + (e.response?.data?.error || e.message))
  }
  importing.value = false
}

async function loadImportHistory() {
  try {
    const res = await dataApi.importHistory()
    importHistory.value = res.history || []
  } catch (e) { /* 静默失败 */ }
}
</script>
