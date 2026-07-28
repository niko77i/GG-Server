<template>
  <div>
    <h2>⚙ 设置</h2>
    <el-tabs v-model="activeTab">
      <!-- Tab 1: 账户设置 -->
      <el-tab-pane label="账户设置" name="account">
        <p style="color:#888;margin-bottom:20px;">自定义下拉框选项，点击名称即可编辑，修改即时保存</p>
        <!-- 账户状态 & 代理名 并排 -->
        <el-row :gutter="16">
          <el-col :span="12">
            <h4 style="margin-bottom:8px;">账户状态选项</h4>
            <el-table :data="store.options.statuses" size="small" border stripe style="max-width:450px;" @cell-click="(row, col, cell, ev) => startEdit(row, col, cell, ev, 'statuses')">
              <el-table-column prop="name" label="名称">
                <template #default="{ row, $index }">
                  <el-input v-if="editing.statuses === $index" v-model="row._editName" size="small"
                    @blur="finishEdit('statuses', row)" @keyup.enter="finishEdit('statuses', row)" />
                  <span v-else>{{ row.name }}</span>
                </template>
              </el-table-column>
              <el-table-column label="操作" width="80">
                <template #default="{ row }">
                  <el-button size="small" type="danger" @click="deleteOption('statuses', row)">🗑</el-button>
                </template>
              </el-table-column>
            </el-table>
            <div style="display:flex;gap:8px;margin-top:8px;max-width:450px;">
              <el-input v-model="newOptionNames.statuses" placeholder="新状态名" size="small" style="flex:1;" @keyup.enter="addOption('statuses')" />
              <el-button size="small" type="primary" @click="addOption('statuses')">新增</el-button>
            </div>
          </el-col>
          <el-col :span="12">
            <h4 style="margin-bottom:8px;">代理名选项</h4>
            <el-table :data="store.options.agents" size="small" border stripe style="max-width:450px;" @cell-click="(row, col, cell, ev) => startEdit(row, col, cell, ev, 'agents')">
              <el-table-column prop="name" label="名称">
                <template #default="{ row, $index }">
                  <el-input v-if="editing.agents === $index" v-model="row._editName" size="small"
                    @blur="finishEdit('agents', row)" @keyup.enter="finishEdit('agents', row)" />
                  <span v-else>{{ row.name }}</span>
                </template>
              </el-table-column>
              <el-table-column label="操作" width="80">
                <template #default="{ row }">
                  <el-button size="small" type="danger" @click="deleteOption('agents', row)">🗑</el-button>
                </template>
              </el-table-column>
            </el-table>
            <div style="display:flex;gap:8px;margin-top:8px;max-width:450px;">
              <el-input v-model="newOptionNames.agents" placeholder="新代理名" size="small" style="flex:1;" @keyup.enter="addOption('agents')" />
              <el-button size="small" type="primary" @click="addOption('agents')">新增</el-button>
            </div>
          </el-col>
        </el-row>
        <!-- MCC 等级 & 商务人员 并排 -->
        <el-row :gutter="16" style="margin-top:20px;">
          <el-col :span="12">
            <h4 style="margin-bottom:8px;">MCC 等级选项</h4>
            <el-table :data="store.options.mccLevels" size="small" border stripe style="max-width:450px;" @cell-click="(row, col, cell, ev) => startEdit(row, col, cell, ev, 'mccLevels')">
              <el-table-column prop="name" label="名称">
                <template #default="{ row, $index }">
                  <el-input v-if="editing.mccLevels === $index" v-model="row._editName" size="small"
                    @blur="finishEdit('mccLevels', row)" @keyup.enter="finishEdit('mccLevels', row)" />
                  <span v-else>{{ row.name }}</span>
                </template>
              </el-table-column>
              <el-table-column label="操作" width="80">
                <template #default="{ row }">
                  <el-button size="small" type="danger" @click="deleteOption('mccLevels', row)">🗑</el-button>
                </template>
              </el-table-column>
            </el-table>
            <div style="display:flex;gap:8px;margin-top:8px;max-width:450px;">
              <el-input v-model="newOptionNames.mccLevels" placeholder="新等级名" size="small" style="flex:1;" @keyup.enter="addOption('mccLevels')" />
              <el-button size="small" type="primary" @click="addOption('mccLevels')">新增</el-button>
            </div>
          </el-col>
          <el-col :span="12">
            <h4 style="margin-bottom:8px;">商务人员选项</h4>
            <el-table :data="store.options.salesPersons" size="small" border stripe style="max-width:450px;" @cell-click="(row, col, cell, ev) => startEdit(row, col, cell, ev, 'salesPersons')">
              <el-table-column prop="name" label="名称">
                <template #default="{ row, $index }">
                  <el-input v-if="editing.salesPersons === $index" v-model="row._editName" size="small"
                    @blur="finishEdit('salesPersons', row)" @keyup.enter="finishEdit('salesPersons', row)" />
                  <span v-else>{{ row.name }}</span>
                </template>
              </el-table-column>
              <el-table-column label="操作" width="80">
                <template #default="{ row }">
                  <el-button size="small" type="danger" @click="deleteOption('salesPersons', row)">🗑</el-button>
                </template>
              </el-table-column>
            </el-table>
            <div style="display:flex;gap:8px;margin-top:8px;max-width:450px;">
              <el-input v-model="newOptionNames.salesPersons" placeholder="新商务人名" size="small" style="flex:1;" @keyup.enter="addOption('salesPersons')" />
              <el-button size="small" type="primary" @click="addOption('salesPersons')">新增</el-button>
            </div>
          </el-col>
        </el-row>
        <template v-if="authStore.isAdmin || authStore.isDeveloper">
          <el-divider />
          <h4 style="margin-bottom:8px;">📊 充值表配置（仅管理员可见）</h4>
          <el-form-item label="Google Sheets（URL 或 ID）">
            <el-input v-model="form.recharge_sheet_id" placeholder="粘贴表格链接或直接输入 spreadsheet ID" />
          </el-form-item>
        </template>
        <el-button type="primary" @click="save" :loading="saving" style="margin-top:16px;">💾 保存配置</el-button>
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
import { useAuthStore } from '@/stores/auth'
import { dataApi } from '@/api/data'
import { UploadFilled } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import api from '@/api/client'

const store = useAccountStore()
const authStore = useAuthStore()
const saving = ref(false)
const msg = ref('')
const activeTab = ref('account')

const form = reactive({
  recharge_sheet_id: '',
})

const newOptionNames = reactive({ statuses: '', agents: '', mccLevels: '', salesPersons: '' })
const editing = reactive({ statuses: -1, agents: -1, mccLevels: -1, salesPersons: -1 })

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
  await Promise.all([store.loadAgents(), store.loadStatuses(), store.loadMccLevels(), store.loadSalesPersons()])
  await store.loadSettings()
  form.recharge_sheet_id = store.settings.recharge_sheet_id || ''
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

// ---- 选项行内编辑 ----
function startEdit(row, _column, _cell, _event, type) {
  row._editName = row.name
  const arr = store.options[type]
  editing[type] = arr.indexOf(row)
}

async function finishEdit(type, row) {
  editing[type] = -1
  const newName = (row._editName || '').trim()
  if (!newName || newName === row.name) return
  const actions = { statuses: 'renameStatus', agents: 'renameAgent', mccLevels: 'renameMccLevel', salesPersons: 'renameSalesPerson' }
  try {
    await store[actions[type]](row.id, newName)
    ElMessage.success('已更新')
  } catch (e) { ElMessage.error(e.response?.data?.error || '更新失败') }
}

async function addOption(type) {
  const name = newOptionNames[type].trim()
  if (!name) { ElMessage.warning('请输入名称'); return }
  const actions = { statuses: 'createStatus', agents: 'createAgent', mccLevels: 'createMccLevel', salesPersons: 'createSalesPerson' }
  try {
    await store[actions[type]](name)
    newOptionNames[type] = ''
    ElMessage.success('已添加')
  } catch (e) { ElMessage.error(e.response?.data?.error || '添加失败') }
}

async function deleteOption(type, row) {
  const actions = { statuses: 'deleteStatus', agents: 'deleteAgent', mccLevels: 'deleteMccLevel', salesPersons: 'deleteSalesPerson' }
  try {
    await store[actions[type]](row.id)
    ElMessage.success('已删除')
  } catch (e) {
    if (e.response?.status === 409) {
      ElMessage.warning(e.response?.data?.error || '无法删除')
    } else {
      ElMessage.error(e.response?.data?.error || '删除失败')
    }
  }
}

async function save() {
  saving.value = true
  const rawId = form.recharge_sheet_id.trim()
  const m = rawId.match(/spreadsheets\/d\/([a-zA-Z0-9_-]+)/)
  const sheetId = m ? m[1] : rawId
  try {
    await store.saveSettings({ recharge_sheet_id: sheetId })
    store.settings.recharge_sheet_id = sheetId
    msg.value = '✅ 已保存'
    setTimeout(() => msg.value = '', 2000)
  } catch (e) { ElMessage.error('保存失败: ' + (e.response?.data?.error || e.message)) }
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
