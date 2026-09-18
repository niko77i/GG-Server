<template>
  <div class="page-wrapper">
    <div class="page-header">
      <h1 class="page-title">BC 管理</h1>
      <el-button type="primary" @click="openCreate">新增 BC</el-button>
    </div>

    <div class="filter-card">
      <el-input v-model="search" placeholder="搜索 BC 名称或 BCID..." @input="onSearch" clearable size="small" style="width:220px" />
      <el-select v-model="filterStatus" placeholder="全部状态" clearable size="small" style="width:140px" @change="loadData">
        <el-option label="正常" value="normal" />
        <el-option label="封禁" value="banned" />
      </el-select>
      <span class="total-badge">共 {{ total }} 个</span>
    </div>

    <el-table :data="items" border size="small" v-loading="loading" :header-cell-style="{ background:'#f8f9fa', color:'#374151', fontWeight:600 }">
      <el-table-column prop="name" label="名称" min-width="160" />
      <el-table-column prop="bc_id" label="BCID" min-width="140" />
      <el-table-column prop="note" label="备注" min-width="180">
        <template #default="{ row }">{{ row.note || '-' }}</template>
      </el-table-column>
      <el-table-column label="状态" width="90">
        <template #default="{ row }">
          <el-tag :type="row.status === 'banned' ? 'danger' : 'success'" size="small">
            {{ row.status === 'banned' ? '封禁' : '正常' }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column label="操作" width="180" align="center">
        <template #default="{ row }">
          <el-button size="small" @click="openEdit(row)">编辑</el-button>
          <el-button v-if="row.status !== 'banned'" size="small" type="warning" @click="toggleBan(row)">封禁</el-button>
          <el-popconfirm title="确定删除？" @confirm="handleDelete(row.id)">
            <template #reference><el-button size="small" type="danger">删除</el-button></template>
          </el-popconfirm>
        </template>
      </el-table-column>
    </el-table>

    <div v-if="total>size" class="pagination-row">
      <el-pagination v-model:current-page="page" :page-size="size" :total="total" background
        layout="prev,pager,next" size="small" :pager-count="7" @current-change="loadData" />
    </div>

    <el-dialog v-model="dialogVisible" :title="editingId?'编辑 BC':'新增 BC'" width="480px">
      <el-form :model="form" label-width="80px">
        <el-form-item label="名称" required><el-input v-model="form.name" /></el-form-item>
        <el-form-item label="BCID" required><el-input v-model="form.bc_id" /></el-form-item>
        <el-form-item label="备注"><el-input v-model="form.note" type="textarea" :rows="2" /></el-form-item>
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
import { ttApi } from '../../api/tt'
import { ElMessage } from 'element-plus'

const items = ref([]); const loading = ref(false)
const page = ref(1); const size = ref(20); const total = ref(0)
const search = ref(''); const filterStatus = ref('')
const dialogVisible = ref(false); const editingId = ref(null); const saving = ref(false)
const form = reactive({ name: '', bc_id: '', note: '' })

let searchTimer = null
function onSearch() { clearTimeout(searchTimer); searchTimer = setTimeout(loadData, 300) }

async function loadData() {
  loading.value = true
  try {
    const p = { page: page.value, size: size.value }
    if (search.value) p.search = search.value
    if (filterStatus.value) p.status = filterStatus.value
    const res = await ttApi.listBcs(p)
    items.value = res.items || []; total.value = res.total || 0
  } finally { loading.value = false }
}

function openCreate() {
  editingId.value = null
  Object.assign(form, { name: '', bc_id: '', note: '' })
  dialogVisible.value = true
}
function openEdit(row) {
  editingId.value = row.id
  Object.assign(form, { name: row.name, bc_id: row.bc_id, note: row.note || '' })
  dialogVisible.value = true
}

async function handleSave() {
  if (!form.name) return ElMessage.warning('请输入名称')
  if (!form.bc_id) return ElMessage.warning('请输入 BCID')
  saving.value = true
  try {
    editingId.value ? await ttApi.updateBc(editingId.value, { name: form.name, note: form.note })
      : await ttApi.createBc({ name: form.name, bc_id: form.bc_id, note: form.note })
    ElMessage.success(editingId.value ? '已更新' : '已创建')
    dialogVisible.value = false; loadData()
  } catch (e) { ElMessage.error(e.response?.data?.error || '保存失败') }
  finally { saving.value = false }
}

async function toggleBan(row) {
  await ttApi.updateBc(row.id, { status: 'banned' })
  ElMessage.success('已封禁'); loadData()
}
function handleDelete(id) { ttApi.deleteBc(id).then(() => { ElMessage.success('已删除'); loadData() }) }

onMounted(loadData)
</script>

<style scoped>
.page-wrapper { background:#f5f6f8;padding:24px;min-height:100%;display:flex;flex-direction:column;gap:16px; }
.page-header { display:flex;justify-content:space-between;align-items:center; }
.page-title { margin:0;font-size:20px;font-weight:700;color:#1f2937; }
.filter-card { background:#f8f9fa;border-radius:12px;padding:14px 16px;display:flex;align-items:center;gap:12px;flex-wrap:wrap;border:1px solid #e5e7eb; }
.total-badge { font-size:13px;color:#6b7280;font-weight:500;white-space:nowrap;padding:4px 10px;background:#fff;border-radius:6px;border:1px solid #e5e7eb; }
.pagination-row { display:flex;justify-content:center;gap:8px;margin-top:16px; }
</style>
