<template>
  <div style="display:flex;flex-direction:column;height:100%;">
    <!-- 页面标题 -->
    <div style="flex-shrink:0;margin-bottom:12px;">
      <h2 style="margin:0;font-size:18px;font-weight:600;">BC 管理</h2>
    </div>
    <!-- 工具栏 — 固定 -->
    <div style="flex-shrink:0;display:flex;gap:10px;margin-bottom:12px;flex-wrap:wrap;align-items:center;">
      <el-button type="primary" @click="openCreate">➕ 新增 BC</el-button>
      <el-input v-model="search" placeholder="🔍 搜索名称/BCID..." @input="onSearch" style="flex:1;" clearable />
      <el-select v-model="filterStatus" placeholder="全部状态" clearable style="width:140px;" @change="loadData">
        <el-option label="正常" value="normal" />
        <el-option label="封禁" value="banned" />
      </el-select>
    </div>

    <!-- 表格 + 分页 — 滚动区 -->
    <div style="flex:1;min-height:0;overflow-y:auto;">
      <el-table :data="items" stripe size="small" v-loading="loading">
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
        <el-table-column label="操作" width="160">
          <template #default="{ row }">
            <el-button link type="primary" size="small" @click="openEdit(row)">✏️</el-button>
            <el-button v-if="row.status !== 'banned'" link type="warning" size="small" @click="toggleBan(row)">封禁</el-button>
            <el-button link type="danger" size="small" @click="handleDelete(row.id)">🗑</el-button>
          </template>
        </el-table-column>
      </el-table>

      <div style="display:flex;align-items:center;justify-content:center;gap:8px;margin-top:12px;">
        <el-pagination v-if="total > size" v-model:current-page="page" :page-size="size" :total="total" background
          layout="prev,pager,next" size="small" :pager-count="7" @current-change="loadData" />
        <el-select v-model="size" @change="page = 1; loadData()" size="small" style="width:90px;">
          <el-option v-for="s in [10,20,50]" :key="s" :label="s+'条/页'" :value="s" />
        </el-select>
      </div>
    </div>

    <!-- 新增/编辑弹窗 -->
    <el-dialog v-model="dialogVisible" :title="editingId ? '✏️ 编辑 BC' : '➕ 新增 BC'" width="480px">
      <el-form label-position="top">
        <el-form-item label="BC 名称" required>
          <el-input v-model="form.name" />
        </el-form-item>
        <el-form-item label="BCID" :description="editingId ? '不可修改' : ''" required>
          <el-input v-model="form.bc_id" :disabled="!!editingId" />
        </el-form-item>
        <el-form-item label="备注">
          <el-input v-model="form.note" type="textarea" :rows="2" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible=false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="handleSave">💾 保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, reactive, onMounted } from 'vue'
import { ttApi } from '../../api/tt'
import { ElMessage, ElMessageBox } from 'element-plus'

const items = ref([]); const loading = ref(false)
const page = ref(1); const size = ref(20); const total = ref(0)
const search = ref(''); const filterStatus = ref('')
const dialogVisible = ref(false); const editingId = ref(null); const saving = ref(false)
const form = reactive({ name: '', bc_id: '', note: '' })

let searchTimer = null
function onSearch() { clearTimeout(searchTimer); searchTimer = setTimeout(() => { page.value = 1; loadData() }, 300) }

async function loadData() {
  loading.value = true
  try {
    const p = { page: page.value, size: size.value }
    if (search.value) p.search = search.value
    if (filterStatus.value) p.status = filterStatus.value
    const res = await ttApi.listBcs(p)
    items.value = res.items || []; total.value = res.total || 0
  } catch(e) { ElMessage.error(e.response?.data?.error || '加载失败') } finally { loading.value = false }
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
  try {
    await ElMessageBox.confirm(`确定封禁 BC「${row.name}」？`, '确认', { type: 'warning' })
  } catch { return }
  try {
    await ttApi.updateBc(row.id, { status: 'banned' })
    ElMessage.success('已封禁'); loadData()
  } catch (e) { ElMessage.error(e.response?.data?.error || '封禁失败') }
}

async function handleDelete(id) {
  try {
    await ElMessageBox.confirm('确定删除此 BC？', '确认', { type: 'warning' })
  } catch { return }
  try {
    await ttApi.deleteBc(id)
    ElMessage.success('已删除'); loadData()
  } catch (e) { ElMessage.error(e.response?.data?.error || '删除失败') }
}

onMounted(loadData)
</script>
