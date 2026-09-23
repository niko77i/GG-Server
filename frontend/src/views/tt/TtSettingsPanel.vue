<template>
  <div>
    <h2>⚙ 设置</h2>
    <el-tabs v-model="activeTab">
      <!-- Tab 1: 账户设置 -->
      <el-tab-pane label="账户设置" name="account">
        <p style="color:#909399;font-size:13px;margin-bottom:20px;">自定义下拉框选项，双击标签编辑名称，点击 × 删除</p>

        <!-- 商务人员选项卡片 -->
        <el-row :gutter="16">
          <el-col :span="12">
            <el-card shadow="never" style="margin-bottom:16px;">
              <template #header>
                <div style="display:flex;align-items:center;justify-content:space-between;">
                  <span style="font-weight:600;font-size:14px;">👤 商务人员选项</span>
                  <el-tag size="small" type="info" round>{{ salesPersons.length }} 项</el-tag>
                </div>
              </template>

              <!-- Tag 标签区 -->
              <div style="display:flex;flex-wrap:wrap;gap:8px;min-height:32px;align-items:center;">
                <template v-if="salesPersons.length">
                  <el-tag
                    v-for="item in salesPersons"
                    :key="item.id"
                    type="info"
                    closable
                    size="default"
                    @close="handleDelete(item)"
                    @dblclick="startTagEdit(item)"
                    style="cursor:pointer;user-select:none;"
                  >
                    <template v-if="editingTagId === item.id">
                      <el-input
                        v-model="item._editName"
                        size="small"
                        style="width:80px;"
                        @blur="finishTagEdit(item)"
                        @keyup.enter="finishTagEdit(item)"
                        @click.stop
                      />
                    </template>
                    <span v-else>{{ item.name }}</span>
                  </el-tag>
                </template>
                <span v-else style="color:#c0c4cc;font-size:13px;">暂无选项</span>

                <!-- 新增：展开输入或 + 按钮 -->
                <template v-if="addingOption">
                  <el-input
                    v-model="newOptionName"
                    size="small"
                    placeholder="新商务人名"
                    style="width:100px;"
                    @keyup.enter="addOption"
                    @blur="cancelAddOption"
                  />
                  <el-button size="small" type="primary" @click="addOption" :loading="addingLoading">确认</el-button>
                </template>
                <el-button v-else size="small" circle @click="showAddInput" style="width:24px;height:24px;font-size:14px;">+</el-button>
              </div>
            </el-card>
          </el-col>
        </el-row>

        <!-- 管理员专属 Google 表格配置 -->
        <template v-if="authStore.isAdmin || authStore.isDeveloper || authStore.isHuguan">
          <!-- 代理 / 状态 / 回收原因选项卡片 -->
          <el-row :gutter="16">
            <el-col :span="12" v-for="card in adminOptionCards" :key="card.key">
              <el-card shadow="never" style="margin-bottom:16px;">
                <template #header>
                  <div style="display:flex;align-items:center;justify-content:space-between;">
                    <span style="font-weight:600;font-size:14px;">{{ card.icon }} {{ card.label }}</span>
                    <el-tag size="small" type="info" round>{{ adminLists[card.key].length }} 项</el-tag>
                  </div>
                </template>

                <div style="display:flex;flex-wrap:wrap;gap:8px;min-height:32px;align-items:center;">
                  <template v-if="adminLists[card.key].length">
                    <el-tag
                      v-for="item in adminLists[card.key]"
                      :key="item.id"
                      :type="card.tagType"
                      closable
                      size="default"
                      @close="handleAdminDelete(card.key, item)"
                      @dblclick="startAdminTagEdit(card.key, item)"
                      style="cursor:pointer;user-select:none;"
                    >
                      <template v-if="adminEditingId[card.key] === item.id">
                        <el-input
                          v-model="item._editName"
                          size="small"
                          style="width:80px;"
                          @blur="finishAdminTagEdit(card.key, item)"
                          @keyup.enter="finishAdminTagEdit(card.key, item)"
                          @click.stop
                        />
                      </template>
                      <span v-else>{{ item.name }}</span>
                    </el-tag>
                  </template>
                  <span v-else style="color:#c0c4cc;font-size:13px;">暂无选项</span>

                  <template v-if="adminAdding[card.key]">
                    <el-input
                      v-model="adminNewNames[card.key]"
                      size="small"
                      :placeholder="card.addPlaceholder"
                      style="width:100px;"
                      @keyup.enter="addAdminOption(card.key)"
                      @blur="cancelAdminAddOption(card.key)"
                    />
                    <el-button size="small" type="primary" @click="addAdminOption(card.key)" :loading="adminAddingLoading">确认</el-button>
                  </template>
                  <el-button v-else size="small" circle @click="showAdminAddInput(card.key)" style="width:24px;height:24px;font-size:14px;">+</el-button>
                </div>
              </el-card>
            </el-col>
          </el-row>
        </template>

          <el-card v-if="!authStore.isHuguan" shadow="never" style="margin-top:20px;border-left:3px solid #0891b2;">
            <template #header>
              <span style="font-weight:600;">📊 Google 表格配置</span>
              <el-tag v-if="isAdmin" size="small" type="warning" style="margin-left:8px;">仅管理员</el-tag>
            </template>

            <!-- Google Sheets URL（读取对所有用户开放，内容仅管理员可改） -->
            <div style="margin-bottom:16px;">
              <div style="font-weight:500;font-size:13px;color:#374151;margin-bottom:6px;">
                Google Sheets（URL 或 ID）
                <el-tag v-if="!isAdmin" size="small" type="warning" style="margin-left:8px;">仅管理员可改</el-tag>
              </div>
              <div style="display:flex;gap:8px;">
                <el-input v-model="form.sheet_id" placeholder="粘贴表格链接或直接输入 spreadsheet ID" style="flex:1;" :disabled="!isAdmin" />
                <el-button @click="readSheets" :loading="readingSheets">📋 读取工作表</el-button>
              </div>
            </div>

            <!-- Sheet 映射 -->
            <div style="margin-bottom:16px;">
              <div style="font-weight:500;font-size:13px;color:#374151;margin-bottom:6px;">Sheet 映射</div>
              <div style="background:#f9fafb;border-radius:8px;padding:12px;">
                <div v-for="key in visibleSheetKeys" :key="key" style="display:flex;align-items:center;gap:8px;margin-bottom:8px;">
                  <span style="white-space:nowrap;font-size:13px;min-width:80px;color:#374151;">{{ (SHEET_MAPPING_META[key] && SHEET_MAPPING_META[key].label) || key }}<el-tag v-if="SHEET_MAPPING_META[key] && SHEET_MAPPING_META[key].adminOnly" size="small" type="warning" style="margin-left:4px;">仅管理员</el-tag></span>
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
                v-if="isAdmin || authStore.isHuguan"
                v-model="row._editTz"
                placeholder="选择时区"
                size="small"
                style="flex:1;"
                filterable
                @change="v => saveRegionTz(row, v)"
              >
                <el-option v-for="tz in timezoneOptions" :key="tz" :label="tz" :value="tz" />
              </el-select>
              <span v-else style="flex:1;font-size:13px;color:#6b7280;">{{ row.timezone || '—' }}</span>
              <el-button
                v-if="isAdmin || authStore.isHuguan"
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
          <div v-if="isAdmin || authStore.isHuguan" style="display:flex;align-items:center;gap:12px;padding:10px 12px;background:#f9fafb;border-radius:6px;margin-top:8px;">
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
              <p style="color:#909399;font-size:13px;margin-bottom:12px;">导出你的 TT 产品 / 包 / BC 数据为 JSON 文件，可用于备份或迁移。</p>
              <el-button type="primary" @click="exportData" :loading="exporting">📥 导出我的数据</el-button>
            </el-card>
          </el-col>

          <!-- 导入区 -->
          <el-col :span="12">
            <el-card shadow="never">
              <template #header>
                <span style="font-weight:600;">📥 导入数据</span>
              </template>
              <p style="color:#909399;font-size:13px;margin-bottom:12px;">上传 TT 导出的 JSON 文件。</p>
              <el-upload
                :auto-upload="false"
                :on-change="onFileChange"
                :limit="1"
                accept=".json"
                drag
              >
                <el-icon style="font-size:24px;color:#0891b2;"><UploadFilled /></el-icon>
                <div style="margin-top:8px;font-size:13px;color:#606266;">拖拽或点击上传 <b>.json</b> 文件</div>
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
      </el-tab-pane>
    </el-tabs>
  </div>
</template>

<script setup>
import { ref, reactive, computed, onMounted } from 'vue'
import { useAuthStore } from '@/stores/auth'
import { ttSettingsApi, ttDataApi, ttRecycleReasonApi } from '@/api/tt'
import { googleSheetsApi } from '@/api/google-sheets'
import { UploadFilled, Delete } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import api from '@/api/client'

// Sheet 映射功能注册表 — 已知 key 的显示名（未知 key 直接显示 key 名）
const SHEET_MAPPING_META = {
  accounts: { label: '账户明细', adminOnly: true },
  recharge: { label: '充值表', adminOnly: true },
  my_dashboard: { label: '我的看板', adminOnly: false },
  recycle: { label: '回收户清单', adminOnly: true },
}

const authStore = useAuthStore()
const isAdmin = computed(() => authStore.isAdmin || authStore.isDeveloper)
const saving = ref(false)
const msg = ref('')
const activeTab = ref('account')

const form = reactive({
  sheet_id: '',
  sheet_mappings: { accounts: '账户明细', recharge: '充值表', my_dashboard: '我的看板', recycle: '回收户清单' },
})
// 当前用户可见的 sheet 映射 key：管理员看全部，投手只看「我的看板」
const visibleSheetKeys = computed(() =>
  Object.keys(form.sheet_mappings).filter(k => isAdmin.value || !(SHEET_MAPPING_META[k] && SHEET_MAPPING_META[k].adminOnly))
)

// 商务人员
const salesPersons = ref([])
const editingTagId = ref(null)
const addingOption = ref(false)
const addingLoading = ref(false)
const newOptionName = ref('')

// ---- 管理员选项卡片（代理 / 状态 / 回收原因） ----
const agents = ref([])
const statuses = ref([])
const recycleReasons = ref([])

const adminOptionCards = [
  { key: 'agents',         icon: '🏷', label: '代理名选项',   tagType: 'success', addPlaceholder: '新代理名' },
  { key: 'statuses',       icon: '📊', label: '账户状态选项', tagType: '',        addPlaceholder: '新状态名' },
  { key: 'recycleReasons', icon: '♻️', label: '回收原因选项', tagType: 'warning', addPlaceholder: '新回收原因' },
]
const adminLists = computed(() => ({
  agents: agents.value,
  statuses: statuses.value,
  recycleReasons: recycleReasons.value,
}))
const adminEditingId = reactive({ agents: null, statuses: null, recycleReasons: null })
const adminAdding = reactive({ agents: false, statuses: false, recycleReasons: false })
const adminNewNames = reactive({ agents: '', statuses: '', recycleReasons: '' })
const adminAddingLoading = ref(false)

// Sheet 读取
const readingSheets = ref(false)
const sheetOptions = ref([])
const sheetOptionsLoaded = ref(false)

// 数据管理
const exporting = ref(false)
const importing = ref(false)
const importFile = ref(null)

// 地区时区
const regionList = ref([])
const newRegionName = ref('')
const newRegionTz = ref('')
function _buildTimezoneOptions() {
  const tzs = []
  for (let i = -12; i <= 12; i++) {
    const sign = i > 0 ? '+' : ''
    tzs.push(`${sign}${i}`)
  }
  tzs.push('+5:30', '+8:45', '-3:30')
  return tzs
}
const timezoneOptions = _buildTimezoneOptions()

onMounted(async () => {
  loadSalesPersons()
  loadSettings()
  loadRegions()
  loadAdminOptions()
})

// ---- 商务人员 ----
async function loadSalesPersons() {
  try {
    const res = await api.get('/sales-persons/list', { params: { platform: 'tt' } })
    salesPersons.value = res.sales_persons || []
  } catch { salesPersons.value = [] }
}

function startTagEdit(item) {
  item._editName = item.name
  editingTagId.value = item.id
}

async function finishTagEdit(item) {
  const newName = (item._editName || '').trim()
  editingTagId.value = null
  delete item._editName
  if (!newName || newName === item.name) return
  try {
    await api.put(`/sales-persons/${item.id}`, { name: newName })
    item.name = newName
    ElMessage.success('已更新')
  } catch (e) { ElMessage.error(e.response?.data?.error || '更新失败'); loadSalesPersons() }
}

function showAddInput() {
  addingOption.value = true
  newOptionName.value = ''
}

function cancelAddOption() {
  if (newOptionName.value.trim()) return
  addingOption.value = false
}

async function addOption() {
  const name = newOptionName.value.trim()
  if (!name) { ElMessage.warning('请输入名称'); return }
  addingLoading.value = true
  try {
    await api.post('/sales-persons/create', { name }, { params: { platform: 'tt' } })
    newOptionName.value = ''
    addingOption.value = false
    ElMessage.success('已添加')
    loadSalesPersons()
  } catch (e) { ElMessage.error(e.response?.data?.error || '添加失败') }
  finally { addingLoading.value = false }
}

async function handleDelete(item) {
  try {
    await ElMessageBox.confirm(`确定删除「${item.name}」吗？`, '确认删除', {
      confirmButtonText: '删除',
      cancelButtonText: '取消',
      type: 'warning',
    })
  } catch { return }

  try {
    await api.delete(`/sales-persons/${item.id}`)
    ElMessage.success('已删除')
    loadSalesPersons()
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

// ---- 管理员选项（代理 / 状态 / 回收原因） ----
async function loadAdminOptions() {
  try {
    const res = await api.get('/agents/list', { params: { platform: 'tt' } })
    agents.value = res.agents || []
  } catch { agents.value = [] }
  try {
    const res = await api.get('/statuses/list', { params: { platform: 'tt' } })
    statuses.value = res.statuses || []
  } catch { statuses.value = [] }
  try {
    const res = await ttRecycleReasonApi.list()
    recycleReasons.value = res.items || []
  } catch { recycleReasons.value = [] }
}

function startAdminTagEdit(key, item) {
  item._editName = item.name
  adminEditingId[key] = item.id
}

async function finishAdminTagEdit(key, item) {
  const newName = (item._editName || '').trim()
  adminEditingId[key] = null
  delete item._editName
  if (!newName || newName === item.name) return
  try {
    if (key === 'recycleReasons') await ttRecycleReasonApi.rename(item.id, newName)
    else if (key === 'agents') await api.put(`/agents/${item.id}`, { name: newName }, { params: { platform: 'tt' } })
    else await api.put(`/statuses/${item.id}`, { name: newName }, { params: { platform: 'tt' } })
    item.name = newName
    ElMessage.success('已更新')
  } catch (e) { ElMessage.error(e.response?.data?.error || '更新失败'); loadAdminOptions() }
}

function showAdminAddInput(key) {
  adminAdding[key] = true
  adminNewNames[key] = ''
}

function cancelAdminAddOption(key) {
  if (adminNewNames[key].trim()) return
  adminAdding[key] = false
}

async function addAdminOption(key) {
  const name = (adminNewNames[key] || '').trim()
  if (!name) { ElMessage.warning('请输入名称'); return }
  adminAddingLoading.value = true
  try {
    if (key === 'recycleReasons') await ttRecycleReasonApi.create(name)
    else if (key === 'agents') await api.post('/agents/create', { name }, { params: { platform: 'tt' } })
    else await api.post('/statuses/create', { name }, { params: { platform: 'tt' } })
    adminNewNames[key] = ''
    adminAdding[key] = false
    ElMessage.success('已添加')
    loadAdminOptions()
  } catch (e) { ElMessage.error(e.response?.data?.error || '添加失败') }
  finally { adminAddingLoading.value = false }
}

async function handleAdminDelete(key, item) {
  try {
    await ElMessageBox.confirm(`确定删除「${item.name}」吗？`, '确认删除', {
      confirmButtonText: '删除',
      cancelButtonText: '取消',
      type: 'warning',
    })
  } catch { return }

  try {
    if (key === 'recycleReasons') await ttRecycleReasonApi.delete(item.id)
    else if (key === 'agents') await api.delete(`/agents/${item.id}`, { params: { platform: 'tt' } })
    else await api.delete(`/statuses/${item.id}`, { params: { platform: 'tt' } })
    ElMessage.success('已删除')
    loadAdminOptions()
  } catch (e) { ElMessage.error(e.response?.data?.error || '无法删除') }
}

// ---- Google 表格配置 ----
async function loadSettings() {
  try {
    const res = await ttSettingsApi.getSettings()
    form.sheet_id = res.settings?.sheet_id || ''
    form.sheet_mappings = res.settings?.sheet_mappings || form.sheet_mappings
  } catch (e) { /* 静默失败，保留默认值 */ }
}

async function readSheets() {
  const rawId = form.sheet_id.trim()
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
  const rawId = form.sheet_id.trim()
  const m = rawId.match(/spreadsheets\/d\/([a-zA-Z0-9_-]+)/)
  const sheetId = m ? m[1] : rawId
  try {
    await ttSettingsApi.saveSettings({ sheet_id: sheetId, sheet_mappings: form.sheet_mappings })
    form.sheet_id = sheetId
    msg.value = '✅ 已保存'
    setTimeout(() => msg.value = '', 2000)
  } catch (e) { ElMessage.error('保存失败: ' + (e.response?.data?.error || e.message)) }
  saving.value = false
}

// ---- 地区时区 ----
async function loadRegions() {
  try {
    const res = await api.get('/regions/list', { params: { platform: 'tt' } })
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
    const res = await api.post('/regions/create', { name, timezone: tz }, { params: { platform: 'tt' } })
    regionList.value.push({ id: res.id, name, timezone: tz, _editTz: tz })
    newRegionName.value = ''
    newRegionTz.value = ''
    ElMessage.success('地区已添加')
  } catch (e) { ElMessage.error('添加失败: ' + (e.response?.data?.error || e.message)) }
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

// ---- 数据管理 ----
async function exportData() {
  exporting.value = true
  try {
    const blob = await ttDataApi.exportData()
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `tt-server-export-${Date.now()}.json`
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
    const res = await ttDataApi.importFile(importFile.value)
    const r = res.report || {}
    ElMessage.success(`导入完成：BC ${r.bcs || 0}，产品 ${r.products || 0}，包 ${r.packages || 0}，在跑 ${r.runners || 0}，掉包检测 ${r.delist_checks || 0}`)
    importFile.value = null
  } catch (e) {
    ElMessage.error('导入失败: ' + (e.response?.data?.error || e.message))
  }
  importing.value = false
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
