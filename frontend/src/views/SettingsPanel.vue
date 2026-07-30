<template>
  <div>
    <h2>⚙ 设置</h2>
    <el-tabs v-model="activeTab">
      <!-- Tab 1: 账户设置 -->
      <el-tab-pane label="账户设置" name="account">
        <p style="color:#909399;font-size:13px;margin-bottom:20px;">自定义下拉框选项，双击标签编辑名称，点击 × 删除</p>

        <!-- 4 张选项卡片 2x2 网格 -->
        <el-row :gutter="16">
          <el-col :span="12" v-for="card in optionCards" :key="card.key">
            <el-card shadow="never" style="margin-bottom:16px;">
              <template #header>
                <div style="display:flex;align-items:center;justify-content:space-between;">
                  <span style="font-weight:600;font-size:14px;">{{ card.icon }} {{ card.label }}</span>
                  <el-tag size="small" type="info" round>{{ store.options[card.key].length }} 项</el-tag>
                </div>
              </template>

              <!-- Tag 标签区 -->
              <div style="display:flex;flex-wrap:wrap;gap:8px;min-height:32px;align-items:center;">
                <template v-if="store.options[card.key].length">
                  <el-tag
                    v-for="item in store.options[card.key]"
                    :key="item.id"
                    :type="card.tagType"
                    closable
                    size="default"
                    @close="handleDelete(card.key, item)"
                    @dblclick="startTagEdit(card.key, item)"
                    style="cursor:pointer;user-select:none;"
                  >
                    <template v-if="editingTagId[card.key] === item.id">
                      <el-input
                        v-model="item._editName"
                        size="small"
                        style="width:80px;"
                        @blur="finishTagEdit(card.key, item)"
                        @keyup.enter="finishTagEdit(card.key, item)"
                        @click.stop
                      />
                    </template>
                    <span v-else>{{ item.name }}</span>
                  </el-tag>
                </template>
                <span v-else style="color:#c0c4cc;font-size:13px;">暂无选项</span>

                <!-- 新增：展开输入或 + 按钮 -->
                <template v-if="addingOption[card.key]">
                  <el-input
                    v-model="newOptionNames[card.key]"
                    size="small"
                    :placeholder="card.addPlaceholder"
                    style="width:100px;"
                    @keyup.enter="addOption(card.key)"
                    @blur="cancelAddOption(card.key)"
                  />
                  <el-button size="small" type="primary" @click="addOption(card.key)" :loading="addingLoading">确认</el-button>
                </template>
                <el-button v-else size="small" circle @click="showAddInput(card.key)" style="width:24px;height:24px;font-size:14px;">+</el-button>
              </div>
            </el-card>
          </el-col>
        </el-row>
        <template v-if="authStore.isAdmin || authStore.isDeveloper">
          <el-card shadow="never" style="margin-top:20px;border-left:3px solid #0891b2;">
            <template #header>
              <span style="font-weight:600;">📊 充值表配置</span>
              <el-tag size="small" type="warning" style="margin-left:8px;">仅管理员</el-tag>
            </template>

            <!-- Google Sheets URL -->
            <div style="margin-bottom:16px;">
              <div style="font-weight:500;font-size:13px;color:#374151;margin-bottom:6px;">Google Sheets（URL 或 ID）</div>
              <div style="display:flex;gap:8px;">
                <el-input v-model="form.recharge_sheet_id" placeholder="粘贴表格链接或直接输入 spreadsheet ID" style="flex:1;" />
                <el-button @click="readSheets" :loading="readingSheets">📋 读取工作表</el-button>
              </div>
            </div>

            <!-- Sheet 映射 -->
            <div style="margin-bottom:16px;">
              <div style="font-weight:500;font-size:13px;color:#374151;margin-bottom:6px;">Sheet 映射</div>
              <div style="background:#f9fafb;border-radius:8px;padding:12px;">
                <div v-for="key in Object.keys(form.sheet_mappings)" :key="key" style="display:flex;align-items:center;gap:8px;margin-bottom:8px;">
                  <span style="white-space:nowrap;font-size:13px;min-width:80px;color:#374151;">{{ (SHEET_MAPPING_META[key] && SHEET_MAPPING_META[key].label) || key }}</span>
                  <el-select
                    v-model="form.sheet_mappings[key]"
                    filterable allow-create default-first-option
                    placeholder="选择或输入 sheet 名"
                    style="flex:1;"
                  >
                    <el-option v-for="name in sheetOptions" :key="name" :label="name" :value="name" />
                  </el-select>
                </div>
                <span v-if="!sheetOptionsLoaded" style="font-size:11px;color:#909399;">点击「📋 读取工作表」加载可选 sheet 列表，也可直接手动输入</span>
                <span v-else style="font-size:11px;color:#059669;">✅ 已加载 {{ sheetOptions.length }} 个工作表可供选择</span>
              </div>
            </div>

            <el-button type="primary" @click="save" :loading="saving">💾 保存配置</el-button>
            <span v-if="msg" style="margin-left:8px;font-size:12px;color:#059669;">{{ msg }}</span>
          </el-card>
        </template>
      </el-tab-pane>

      <!-- Tab 2: 地区时区 -->
      <el-tab-pane label="地区时区" name="region">
        <p style="color:#909399;font-size:13px;margin-bottom:16px;">地区对应的时区，产品数据分析时使用</p>

        <el-card shadow="never" style="max-width:600px;">
          <template #header>
            <div style="display:flex;align-items:center;justify-content:space-between;">
              <span style="font-weight:600;font-size:14px;">🌍 地区时区配置</span>
              <el-tag size="small" type="info" round>{{ regionList.length }} 个地区</el-tag>
            </div>
          </template>

          <!-- 地区列表 -->
          <div v-if="regionList.length">
            <div
              v-for="row in regionList"
              :key="row.id"
              style="display:flex;align-items:center;gap:12px;padding:10px 12px;border-bottom:1px solid #f3f4f6;transition:background 0.15s;"
              class="region-row"
            >
              <span style="flex:0 0 100px;font-size:14px;font-weight:500;color:#374151;">{{ row.name }}</span>
              <el-select
                v-model="row._editTz"
                placeholder="选择时区"
                size="small"
                style="flex:1;"
                filterable
                @change="v => saveRegionTz(row, v)"
              >
                <el-option v-for="tz in timezoneOptions" :key="tz" :label="tz" :value="tz" />
              </el-select>
              <el-button
                size="small"
                type="danger"
                :icon="Delete"
                circle
                text
                @click="deleteRegion(row)"
                style="opacity:0;transition:opacity 0.15s;"
                class="region-delete-btn"
              />
            </div>
          </div>
          <div v-else style="text-align:center;padding:20px;color:#c0c4cc;">
            <span style="font-size:13px;">暂无地区配置</span>
          </div>

          <!-- 新增行 -->
          <div style="display:flex;align-items:center;gap:12px;padding:10px 12px;background:#f9fafb;border-radius:6px;margin-top:8px;">
            <el-input v-model="newRegionName" placeholder="新地区名" size="small" style="flex:0 0 100px;" @keyup.enter="addRegion" />
            <el-select v-model="newRegionTz" placeholder="时区" size="small" style="flex:1;" filterable>
              <el-option v-for="tz in timezoneOptions" :key="tz" :label="tz" :value="tz" />
            </el-select>
            <el-button size="small" type="primary" @click="addRegion">新增</el-button>
          </div>
        </el-card>
      </el-tab-pane>

      <!-- Tab 3: 数据管理 -->
      <el-tab-pane label="数据管理" name="data">
        <el-row :gutter="16">
          <!-- 导出区 -->
          <el-col :span="12">
            <el-card shadow="never">
              <template #header>
                <span style="font-weight:600;">📤 导出数据</span>
              </template>
              <p style="color:#909399;font-size:13px;margin-bottom:12px;">导出你的所有数据为 JSON 文件，可用于备份或迁移。</p>
              <el-button type="primary" @click="exportData" :loading="exporting">📥 导出我的数据</el-button>
            </el-card>
          </el-col>

          <!-- 导入区 -->
          <el-col :span="12">
            <el-card shadow="never">
              <template #header>
                <span style="font-weight:600;">📥 导入数据</span>
              </template>
              <p style="color:#909399;font-size:13px;margin-bottom:12px;">上传 ImageCrawling 的 app.db 或 JSON 导出文件。</p>
              <el-upload
                :auto-upload="false"
                :on-change="onFileChange"
                :limit="1"
                accept=".db,.json"
                drag
              >
                <el-icon style="font-size:24px;color:#0891b2;"><UploadFilled /></el-icon>
                <div style="margin-top:8px;font-size:13px;color:#606266;">拖拽或点击上传 <b>.db</b> / <b>.json</b> 文件</div>
              </el-upload>
              <el-button
                type="success"
                @click="confirmImport"
                :loading="importing"
                :disabled="!importFile"
                style="margin-top:12px;"
              >✅ 确认导入</el-button>
            </el-card>
          </el-col>
        </el-row>

        <!-- 导入历史 -->
        <el-card shadow="never" style="margin-top:16px;">
          <template #header>
            <span style="font-weight:600;">📋 导入历史</span>
          </template>
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
import { googleSheetsApi } from '@/api/google-sheets'
import { UploadFilled, Delete } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import api from '@/api/client'

// Sheet 映射功能注册表 — 已知 key 的显示名（未知 key 直接显示 key 名）
const SHEET_MAPPING_META = {
  recharge: { label: '充值表' },
  received_accounts: { label: '已接账户明细' },
  my_dashboard: { label: '我的看板' },
}

const store = useAccountStore()
const authStore = useAuthStore()
const saving = ref(false)
const msg = ref('')
const activeTab = ref('account')

const form = reactive({
  recharge_sheet_id: '',
  sheet_mappings: { recharge: '充值表', received_accounts: '已接账户明细', my_dashboard: '我的看板' },
})

const newOptionNames = reactive({ statuses: '', agents: '', mccLevels: '', salesPersons: '' })
const editingTagId = reactive({ statuses: null, agents: null, mccLevels: null, salesPersons: null })
const addingOption = reactive({ statuses: false, agents: false, mccLevels: false, salesPersons: false })
const addingLoading = ref(false)

// ---- 选项卡片配置 ----
const optionCards = [
  { key: 'statuses',     icon: '📊', label: '账户状态选项',  tagType: '',        addPlaceholder: '新状态名' },
  { key: 'agents',       icon: '🏷', label: '代理名选项',    tagType: 'success', addPlaceholder: '新代理名' },
  { key: 'mccLevels',    icon: '📈', label: 'MCC 等级选项',  tagType: 'warning', addPlaceholder: '新等级名' },
  { key: 'salesPersons', icon: '👤', label: '商务人员选项',  tagType: 'info',    addPlaceholder: '新商务人名' },
]

// Sheet 读取
const readingSheets = ref(false)
const sheetOptions = ref([])
const sheetOptionsLoaded = ref(false)

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
  form.sheet_mappings = store.settings.sheet_mappings || { recharge: '充值表' }
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

async function deleteRegion(row) {
  try {
    await ElMessageBox.confirm(`确定删除地区「${row.name}」吗？`, '确认删除', {
      confirmButtonText: '删除',
      cancelButtonText: '取消',
      type: 'warning',
    })
  } catch { return }

  try {
    await api.delete(`/regions/${row.id}`)
    const idx = regionList.value.findIndex(r => r.id === row.id)
    if (idx >= 0) regionList.value.splice(idx, 1)
    ElMessage.success('已删除')
  } catch (e) { ElMessage.error('删除失败: ' + (e.response?.data?.error || e.message)) }
}

// ---- Tag 标签交互 ----
function startTagEdit(type, item) {
  item._editName = item.name
  editingTagId[type] = item.id
}

function cancelTagEdit(type, item) {
  editingTagId[type] = null
  delete item._editName
}

async function finishTagEdit(type, item) {
  const newName = (item._editName || '').trim()
  editingTagId[type] = null
  delete item._editName
  if (!newName || newName === item.name) return

  const actions = { statuses: 'renameStatus', agents: 'renameAgent', mccLevels: 'renameMccLevel', salesPersons: 'renameSalesPerson' }
  try {
    await store[actions[type]](item.id, newName)
    ElMessage.success('已更新')
  } catch (e) { ElMessage.error(e.response?.data?.error || '更新失败') }
}

function showAddInput(type) {
  addingOption[type] = true
  newOptionNames[type] = ''
}

function cancelAddOption(type) {
  if (newOptionNames[type].trim()) return
  addingOption[type] = false
}

async function addOption(type) {
  const name = newOptionNames[type].trim()
  if (!name) { ElMessage.warning('请输入名称'); return }
  const actions = { statuses: 'createStatus', agents: 'createAgent', mccLevels: 'createMccLevel', salesPersons: 'createSalesPerson' }
  try {
    await store[actions[type]](name)
    newOptionNames[type] = ''
    addingOption[type] = false
    ElMessage.success('已添加')
  } catch (e) { ElMessage.error(e.response?.data?.error || '添加失败') }
}

async function handleDelete(type, item) {
  try {
    await ElMessageBox.confirm(`确定删除「${item.name}」吗？`, '确认删除', {
      confirmButtonText: '删除',
      cancelButtonText: '取消',
      type: 'warning',
    })
  } catch { return }

  const actions = { statuses: 'deleteStatus', agents: 'deleteAgent', mccLevels: 'deleteMccLevel', salesPersons: 'deleteSalesPerson' }
  try {
    await store[actions[type]](item.id)
    ElMessage.success('已删除')
  } catch (e) {
    const msg = e.response?.data?.error || '无法删除'
    const products = e.response?.data?.products
    if (e.response?.status === 409) {
      ElMessage.warning(products ? `${msg}：${products.join('、')}` : msg)
    } else {
      ElMessage.error(msg)
    }
  }
}

async function readSheets() {
  const rawId = form.recharge_sheet_id.trim()
  if (!rawId) {
    ElMessage.warning('请先输入表格链接或 ID')
    return
  }
  const m = rawId.match(/spreadsheets\/d\/([a-zA-Z0-9_-]+)/)
  const sid = m ? m[1] : rawId

  readingSheets.value = true
  sheetOptionsLoaded.value = false
  try {
    const res = await googleSheetsApi.listSheets(sid)
    sheetOptions.value = (res.sheets || []).map(s => s.name)
    sheetOptionsLoaded.value = true
    ElMessage.success(`已读取 ${sheetOptions.value.length} 个工作表`)
  } catch (e) {
    sheetOptions.value = []
    ElMessage.error('读取工作表失败: ' + (e.response?.data?.error || e.message))
  } finally {
    readingSheets.value = false
  }
}

async function save() {
  saving.value = true
  const rawId = form.recharge_sheet_id.trim()
  const m = rawId.match(/spreadsheets\/d\/([a-zA-Z0-9_-]+)/)
  const sheetId = m ? m[1] : rawId
  try {
    await store.saveSettings({ recharge_sheet_id: sheetId, sheet_mappings: form.sheet_mappings })
    store.settings.recharge_sheet_id = sheetId
    store.settings.sheet_mappings = { ...form.sheet_mappings }
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

<style scoped>
.region-row:hover {
  background: #f9fafb;
}
.region-row:hover .region-delete-btn {
  opacity: 1 !important;
}
</style>
