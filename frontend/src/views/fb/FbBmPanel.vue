<template>
  <div class="fb-panel">
    <!-- 页面头部 -->
    <div class="panel-header">
      <h2 class="panel-title">BM 管理</h2>
      <el-button type="primary" @click="openCreate">新增 BM</el-button>
    </div>

    <!-- 统计卡片行 -->
    <el-row :gutter="16" class="stat-row">
      <el-col :span="6">
        <div class="stat-card">
          <div class="stat-icon stat-icon-total">📦</div>
          <div class="stat-body"><div class="stat-value">{{ total }}</div><div class="stat-label">BM 总数</div></div>
        </div>
      </el-col>
      <el-col :span="6">
        <div class="stat-card">
          <div class="stat-icon stat-icon-account">🏢</div>
          <div class="stat-body"><div class="stat-value">{{ items.filter(i => i.bm_type==='account').length }}</div><div class="stat-label">账户 BM</div></div>
        </div>
      </el-col>
      <el-col :span="6">
        <div class="stat-card">
          <div class="stat-icon stat-icon-pixel">📊</div>
          <div class="stat-body"><div class="stat-value">{{ items.filter(i => i.bm_type==='pixel').length }}</div><div class="stat-label">像素 BM</div></div>
        </div>
      </el-col>
      <el-col :span="6">
        <div class="stat-card">
          <div class="stat-icon stat-icon-normal">✅</div>
          <div class="stat-body"><div class="stat-value">{{ items.filter(i => i.status==='normal').length }}</div><div class="stat-label">正常</div></div>
        </div>
      </el-col>
    </el-row>

    <!-- 筛选栏 -->
    <div class="filter-card">
      <div class="filter-bar">
        <el-input v-model="search" placeholder="搜索 BM 名称或 ID..." @input="onSearch" clearable size="small" style="width:240px" />
        <el-select v-model="filterBmType" placeholder="全部类型" clearable size="small" style="width:130px" @change="loadData">
          <el-option label="账户 BM" value="account" />
          <el-option label="像素 BM" value="pixel" />
        </el-select>
        <el-select v-model="filterStatus" placeholder="全部状态" clearable size="small" style="width:120px" @change="loadData">
          <el-option label="正常" value="normal" />
          <el-option label="已封禁" value="banned" />
        </el-select>
        <span class="total-badge">共 {{ total }} 个</span>
      </div>
    </div>

    <!-- 表格 -->
    <el-card class="table-card" shadow="never">
      <el-table :data="items" stripe border v-loading="loading">
        <el-table-column prop="name" label="BM 名称" min-width="140" />
        <el-table-column prop="bm_id" label="BM ID" width="150" />
        <el-table-column label="类型" width="90">
          <template #default="{ row }">
            <el-tag :type="row.bm_type==='account'?'':'warning'" size="small">
              {{ row.bm_type==='account'?'账户':'像素' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="note" label="备注" min-width="120">
          <template #default="{ row }">{{ row.note || '-' }}</template>
        </el-table-column>
        <el-table-column label="状态" width="80">
          <template #default="{ row }">
            <el-tag :type="row.status==='banned'?'danger':'success'" size="small">
              {{ row.status==='banned'?'已封禁':'正常' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="关联" width="90">
          <template #default="{ row }">
            <span v-if="row.bm_type==='account'">{{ row.account_count }} 账户</span>
            <span v-else>{{ row.pixel_count }} 像素</span>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="240" fixed="right">
          <template #default="{ row }">
            <el-button size="small" type="primary" link @click="openEdit(row)">编辑</el-button>
            <el-button v-if="row.bm_type==='account' && row.status!=='banned'" size="small" type="warning" link @click="openBan(row)">封禁</el-button>
            <el-popconfirm title="确定删除？" @confirm="handleDelete(row)">
              <template #reference>
                <el-button size="small" type="danger" link>删除</el-button>
              </template>
            </el-popconfirm>
          </template>
        </el-table-column>
      </el-table>

      <el-pagination
        v-if="total > size" v-model:current-page="page" :page-size="size" :total="total"
        layout="prev, pager, next" @current-change="loadData" style="margin-top:16px;justify-content:flex-end"
      />
    </el-card>

    <!-- BM 弹窗 -->
    <el-dialog v-model="dialogVisible" :title="editingId?'编辑 BM':'新增 BM'" width="500px">
      <el-form :model="form" label-width="80px">
        <el-form-item label="BM 类型" required v-if="!editingId">
          <el-radio-group v-model="form.bm_type">
            <el-radio value="account">账户 BM</el-radio>
            <el-radio value="pixel">像素 BM</el-radio>
          </el-radio-group>
        </el-form-item>
        <el-form-item label="BM 名称" required>
          <el-input v-model="form.name" placeholder="BM 名称" />
        </el-form-item>
        <el-form-item label="BM ID" required v-if="!editingId">
          <el-input v-model="form.bm_id" placeholder="纯数字" @input="form.bm_id=form.bm_id.replace(/\D/g,'')" />
        </el-form-item>
        <el-form-item v-else label="BM ID">
          <el-input :model-value="form.bm_id" disabled />
        </el-form-item>
        <el-form-item label="备注">
          <el-input v-model="form.note" placeholder="备注（如：像素 BM）" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible=false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="handleSave">保存</el-button>
      </template>
    </el-dialog>

    <!-- 封禁迁移弹窗（仅账户 BM） -->
    <el-dialog v-model="banDialogVisible" title="封禁 BM" width="500px">
      <el-alert type="warning" show-icon :closable="false" style="margin-bottom:16px">
        <template #title>封禁后该 BM 下的所有广告账户将被迁移至目标 BM，此操作不可逆。</template>
      </el-alert>
      <p>确定封禁 BM「{{ banTarget?.name }}」？(关联 {{ banTarget?.account_count }} 个账户)</p>
      <el-form label-width="80px" style="margin-top:16px">
        <el-form-item label="迁移到 BM">
          <el-select v-model="banForm.target_bm_id" filterable allow-create placeholder="选择或输入新 BM ID" style="width:100%">
            <el-option v-for="bm in bmOptions" :key="bm.id" :label="bm.name+' ('+bm.bm_id+')'" :value="bm.bm_id" />
          </el-select>
        </el-form-item>
        <el-form-item v-if="isNewBmId" label="新 BM 名">
          <el-input v-model="banForm.target_bm_name" placeholder="输入新 BM 名称" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="banDialogVisible=false">取消</el-button>
        <el-button type="danger" :loading="banning" @click="handleBanMigrate">确认封禁并迁移</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, reactive, computed, onMounted } from 'vue'
import { fbApi } from '../../api/fb'
import { ElMessage } from 'element-plus'

const items = ref([]); const loading = ref(false)
const page = ref(1); const size = ref(50); const total = ref(0)
const search = ref(''); const filterStatus = ref(''); const filterBmType = ref('')

const dialogVisible = ref(false); const editingId = ref(null); const saving = ref(false)
const form = reactive({ name:'', bm_id:'', note:'', bm_type:'account' })
const editingBmType = ref('')

const banDialogVisible = ref(false); const banTarget = ref(null)
const bmOptions = ref([]); const banning = ref(false)
const banForm = reactive({ target_bm_id:'', target_bm_name:'' })
const isNewBmId = computed(() => banForm.target_bm_id && !bmOptions.value.find(b => b.bm_id === banForm.target_bm_id))

let searchTimer = null
function onSearch() { clearTimeout(searchTimer); searchTimer = setTimeout(() => { page.value = 1; loadData() }, 300) }

async function loadData() {
  loading.value = true
  try {
    const params = { page: page.value, size: size.value }
    if (search.value) params.search = search.value
    if (filterStatus.value) params.status = filterStatus.value
    if (filterBmType.value) params.bm_type = filterBmType.value
    const res = await fbApi.listUnifiedBms(params)
    items.value = res.items; total.value = res.total
  } catch (e) { ElMessage.error('加载失败') }
  finally { loading.value = false }
}

function openCreate() {
  editingId.value = null; editingBmType.value = ''
  form.name = ''; form.bm_id = ''; form.note = ''; form.bm_type = 'account'
  dialogVisible.value = true
}

function openEdit(row) {
  editingId.value = row.id; editingBmType.value = row.bm_type
  form.name = row.name; form.bm_id = row.bm_id; form.note = row.note || ''
  form.bm_type = row.bm_type
  dialogVisible.value = true
}

async function handleSave() {
  if (!form.name) return ElMessage.warning('请填写 BM 名称')
  if (!editingId.value && !form.bm_id) return ElMessage.warning('请填写 BM ID')
  saving.value = true
  try {
    const bmType = editingId.value ? editingBmType.value : form.bm_type
    if (editingId.value) {
      const data = { name: form.name, note: form.note }
      bmType === 'pixel' ? await fbApi.updatePixelBm(editingId.value, data) : await fbApi.updateBm(editingId.value, data)
    } else {
      const data = { name: form.name, bm_id: form.bm_id, note: form.note }
      bmType === 'pixel' ? await fbApi.createPixelBm(data) : await fbApi.createBm(data)
    }
    ElMessage.success(editingId.value ? '已更新' : '已创建')
    dialogVisible.value = false; loadData()
  } catch (e) { ElMessage.error(e.response?.data?.error || '保存失败') }
  finally { saving.value = false }
}

async function handleDelete(row) {
  try {
    row.bm_type === 'pixel' ? await fbApi.deletePixelBm(row.id) : await fbApi.deleteBm(row.id)
    ElMessage.success('已删除'); loadData()
  } catch (e) { ElMessage.error(e.response?.data?.error || '删除失败') }
}

async function openBan(row) {
  banTarget.value = row
  banForm.target_bm_id = ''; banForm.target_bm_name = ''
  const res = await fbApi.bmOptions()
  bmOptions.value = (res.data || []).filter(b => b.id !== row.id)
  banDialogVisible.value = true
}

async function handleBanMigrate() {
  if (!banForm.target_bm_id) return ElMessage.warning('请选择目标 BM')
  if (isNewBmId.value && !banForm.target_bm_name) return ElMessage.warning('请输入新 BM 名称')
  banning.value = true
  try {
    const res = await fbApi.banAndMigrate(banTarget.value.id, banForm)
    ElMessage.success(`已封禁，${res.data.migrated_accounts} 个账户已迁移`)
    if (res.data.warnings?.length) {
      setTimeout(() => res.data.warnings.forEach(w => ElMessage.warning(w)), 500)
    }
    banDialogVisible.value = false; loadData()
  } catch (e) { ElMessage.error(e.response?.data?.error || '操作失败') }
  finally { banning.value = false }
}

onMounted(loadData)
</script>

<style scoped>
.fb-panel { padding: 24px; background: #f5f6f8; min-height: 100vh; }
.panel-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 20px; }
.panel-title { margin: 0; font-size: 20px; font-weight: 700; color: #1a1a2e; }

.stat-row { margin-bottom: 16px; }
.stat-card { display: flex; align-items: center; gap: 16px; background: #fff; border-radius: 12px; padding: 20px 24px; box-shadow: 0 1px 3px rgba(0,0,0,0.06); transition: transform 0.2s,box-shadow 0.2s; cursor: default; }
.stat-card:hover { transform: translateY(-2px); box-shadow: 0 4px 12px rgba(0,0,0,0.1); }
.stat-icon { width: 48px; height: 48px; border-radius: 12px; display: flex; align-items: center; justify-content: center; font-size: 24px; flex-shrink: 0; }
.stat-icon-total { background: #eef2ff; }
.stat-icon-account { background: #dbeafe; }
.stat-icon-pixel { background: #fef3c7; }
.stat-icon-normal { background: #d1fae5; }
.stat-body { flex: 1; min-width: 0; }
.stat-value { font-size: 28px; font-weight: 700; color: #1a1a2e; line-height: 1.2; }
.stat-label { font-size: 13px; color: #8b8fa3; margin-top: 4px; }

.filter-card { background: #f8f9fa; border-radius: 12px; padding: 12px 16px; margin-bottom: 16px; }
.filter-bar { display: flex; gap: 12px; align-items: center; }
.total-badge { font-size: 13px; color: #6b7280; font-weight: 500; white-space: nowrap; padding: 4px 10px; background: #fff; border-radius: 6px; border: 1px solid #e5e7eb; }

.table-card { border-radius: 12px; box-shadow: 0 1px 3px rgba(0,0,0,0.06); }
.table-card :deep(.el-card__body) { padding: 16px; }
:deep(.el-table th.el-table__cell) { background-color: #f5f7fa; color: #303133; font-weight: 600; }
:deep(.el-table) { border-radius: 8px; overflow: hidden; }
</style>
