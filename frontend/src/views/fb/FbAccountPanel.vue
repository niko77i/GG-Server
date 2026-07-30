<template>
  <div class="fb-panel">
    <div class="panel-header">
      <h2>👤 FB账户管理</h2>
      <el-button type="primary" @click="openCreate">➕ 新增账户</el-button>
    </div>
    <div class="filter-bar">
      <el-input v-model="search" placeholder="搜索ID/名称" clearable style="width:200px" @input="onSearch" />
      <el-select v-model="filterBm" placeholder="全部BM" clearable style="width:180px" @change="loadData">
        <el-option v-for="b in bmOptions" :key="b.id" :label="b.name" :value="b.id" />
      </el-select>
      <el-button @click="loadData">🔄 刷新</el-button>
      <el-button type="danger" :disabled="selectedIds.length===0" @click="handleBatchDelete">🗑 批量删除({{ selectedIds.length }})</el-button>
    </div>
    <el-table :data="items" stripe border v-loading="loading" @selection-change="onSelect">
      <el-table-column type="selection" width="45" />
      <el-table-column prop="name" label="账户名" min-width="120" />
      <el-table-column prop="account_id" label="账户ID" width="160" />
      <el-table-column label="所属BM" min-width="140">
        <template #default="{ row }">{{ row.bms?.map(b=>b.name).join(', ') }}</template>
      </el-table-column>
      <el-table-column prop="timezone" label="时区" width="100" />
      <el-table-column prop="acquired_date" label="到手时间" width="110" />
      <el-table-column label="操作" width="140" fixed="right">
        <template #default="{ row }">
          <el-button size="small" type="primary" link @click="openEdit(row)">编辑</el-button>
          <el-popconfirm title="确定删除？" @confirm="handleDelete(row.id)">
            <template #reference><el-button size="small" type="danger" link>删除</el-button></template>
          </el-popconfirm>
        </template>
      </el-table-column>
    </el-table>
    <el-pagination v-if="total>size" v-model:current-page="page" :page-size="size" :total="total"
      layout="prev,pager,next" @current-change="loadData" style="margin-top:16px;justify-content:flex-end" />

    <el-dialog v-model="dialogVisible" :title="editingId?'编辑账户':'新增账户'" width="500px">
      <el-form :model="form" label-width="80px">
        <el-form-item label="账户名" required><el-input v-model="form.name" /></el-form-item>
        <el-form-item label="账户ID" required>
          <el-input v-model="form.account_id" @input="form.account_id=form.account_id.replace(/\D/g,'')" />
        </el-form-item>
        <el-form-item label="关联BM"><el-select v-model="form.bm_ids" multiple placeholder="选择BM" style="width:100%">
          <el-option v-for="b in bmOptions" :key="b.id" :label="b.name+' ('+b.bm_id+')'" :value="b.id" /></el-select>
        </el-form-item>
        <el-form-item label="时区"><el-input v-model="form.timezone" /></el-form-item>
        <el-form-item label="到手时间"><el-input v-model="form.acquired_date" placeholder="YYYY-MM-DD" /></el-form-item>
        <el-form-item label="状态"><el-select v-model="form.status_id" clearable style="width:100%">
          <el-option v-for="s in statusOptions" :key="s.id" :label="s.name" :value="s.id" /></el-select>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible=false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="handleSave">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, reactive, onMounted } from 'vue'
import { fbApi } from '../../api/fb'
import { ElMessage } from 'element-plus'
import client from '../../api/client'

const items = ref([]); const loading = ref(false); const page = ref(1); const size = ref(50); const total = ref(0)
const search = ref(''); const filterBm = ref(''); const selectedIds = ref([])
const bmOptions = ref([]); const statusOptions = ref([]); const dialogVisible = ref(false)
const editingId = ref(null); const saving = ref(false)
const form = reactive({ name:'', account_id:'', bm_ids:[], timezone:'', acquired_date:'', status_id:null })

let searchTimer = null
function onSearch() { clearTimeout(searchTimer); searchTimer = setTimeout(loadData, 300) }
function onSelect(v) { selectedIds.value = v.map(r=>r.id) }

async function loadData() {
  loading.value = true
  try {
    const p = { page: page.value, size: size.value }
    if (search.value) p.search = search.value
    if (filterBm.value) p.bm_id = filterBm.value
    const res = await fbApi.listAccounts(p)
    items.value = res.items; total.value = res.total
  } finally { loading.value = false }
}
async function loadOptions() {
  try { const r = await fbApi.bmOptions(); bmOptions.value = r.data || [] } catch(e) { console.warn('loadOptions bm', e) }
  try { const r = await client.get('/statuses/list'); statusOptions.value = r.statuses || r.data || [] } catch(e) { console.warn('loadOptions statuses', e) }
}

function openCreate() {
  editingId.value = null; form.name=''; form.account_id=''; form.bm_ids=[]; form.timezone=''; form.acquired_date=''; form.status_id=null
  dialogVisible.value = true
}
function openEdit(row) {
  editingId.value = row.id; form.name = row.name; form.account_id = row.account_id; form.bm_ids = (row.bms||[]).map(b=>b.id)
  form.timezone = row.timezone; form.acquired_date = row.acquired_date; form.status_id = row.status_id
  dialogVisible.value = true
}
async function handleSave() {
  if (!form.name || !form.account_id) return ElMessage.warning('请填写账户名和账户ID')
  saving.value = true
  try {
    if (editingId.value) {
      await fbApi.updateAccount(editingId.value, form)
    } else {
      await fbApi.createAccount(form)
    }
    ElMessage.success(editingId.value?'已更新':'已创建'); dialogVisible.value = false; loadData()
  } catch(e) { ElMessage.error(e.response?.data?.error||'保存失败') }
  finally { saving.value = false }
}
async function handleDelete(id) { await fbApi.deleteAccount(id); ElMessage.success('已删除'); loadData() }
async function handleBatchDelete() {
  for (const id of selectedIds.value) { await fbApi.deleteAccount(id) }
  ElMessage.success(`已删除${selectedIds.value.length}个`); loadData()
}
onMounted(() => { loadOptions(); loadData() })
</script>

<style scoped>
.fb-panel{padding:20px}.panel-header{display:flex;justify-content:space-between;align-items:center;margin-bottom:16px}.panel-header h2{margin:0;font-size:18px}.filter-bar{display:flex;gap:12px;margin-bottom:16px;align-items:center;flex-wrap:wrap}
</style>
