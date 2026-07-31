<template>
  <div class="fb-panel">
    <!-- 页面头部 -->
    <div class="panel-header">
      <h2 class="panel-title">像素管理</h2>
      <el-button type="primary" @click="openCreate">添加像素</el-button>
    </div>

    <!-- 统计卡片行 -->
    <el-row :gutter="16" class="stat-row">
      <el-col :span="8">
        <div class="stat-card">
          <div class="stat-icon stat-icon-total">📊</div>
          <div class="stat-body"><div class="stat-value">{{ total }}</div><div class="stat-label">像素总数</div></div>
        </div>
      </el-col>
      <el-col :span="8">
        <div class="stat-card">
          <div class="stat-icon stat-icon-bm">📦</div>
          <div class="stat-body"><div class="stat-value">{{ bmCount }}</div><div class="stat-label">关联 BM 数</div></div>
        </div>
      </el-col>
      <el-col :span="8">
        <div class="stat-card">
          <div class="stat-icon stat-icon-search">🔍</div>
          <div class="stat-body"><div class="stat-value">{{ items.length }}</div><div class="stat-label">当前页</div></div>
        </div>
      </el-col>
    </el-row>

    <!-- 筛选栏 -->
    <div class="filter-card">
      <div class="filter-bar">
        <el-input v-model="search" placeholder="搜索像素名或像素 ID..." @input="onSearch" clearable size="small" style="width:260px" />
        <span class="total-badge">共 {{ total }} 个</span>
      </div>
    </div>

    <!-- 表格 -->
    <el-card class="table-card" shadow="never">
      <el-table :data="items" stripe border v-loading="loading">
        <el-table-column prop="pixel_name" label="像素名" min-width="150" />
        <el-table-column prop="pixel_id" label="像素 ID" width="180" />
        <el-table-column label="所属 BM" min-width="180">
          <template #default="{ row }">
            <span v-if="row.bm_name">{{ row.bm_name }} ({{ row.bm_bm_id }})</span>
            <span v-else class="no-data">-</span>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="200" fixed="right">
          <template #default="{ row }">
            <el-button size="small" type="primary" link @click="openEdit(row)">编辑</el-button>
            <el-popconfirm title="确定删除？" @confirm="handleDelete(row.id)">
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

    <!-- 像素弹窗 -->
    <el-dialog v-model="dialogVisible" :title="editingId?'编辑像素':'添加像素'" width="500px">
      <el-form :model="form" label-width="80px">
        <el-form-item label="像素名" required>
          <el-input v-model="form.pixel_name" placeholder="像素名" />
        </el-form-item>
        <el-form-item label="像素 ID" required v-if="!editingId">
          <el-input v-model="form.pixel_id" placeholder="纯数字" @input="form.pixel_id=form.pixel_id.replace(/\D/g,'')" />
        </el-form-item>
        <el-form-item v-else label="像素 ID">
          <el-input :model-value="form.pixel_id" disabled />
        </el-form-item>
        <el-form-item label="所属 BM" required v-if="!editingId">
          <el-select v-model="form.pixel_bm_id" placeholder="选择 BM" filterable style="width:100%">
            <el-option v-for="bm in pixelBmOptions" :key="bm.id" :label="bm.name+' ('+bm.bm_id+')'" :value="bm.id" />
          </el-select>
        </el-form-item>
        <el-form-item v-else label="所属 BM">
          <el-input :model-value="form.bm_name+' ('+form.bm_bm_id+')'" disabled />
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
import { ref, reactive, computed, onMounted } from 'vue'
import { fbApi } from '../../api/fb'
import { ElMessage } from 'element-plus'

const items = ref([]); const loading = ref(false)
const page = ref(1); const size = ref(50); const total = ref(0)
const search = ref('')
const pixelBmOptions = ref([])

const dialogVisible = ref(false); const editingId = ref(null); const saving = ref(false)
const form = reactive({ pixel_name:'', pixel_id:'', pixel_bm_id:null, bm_name:'', bm_bm_id:'' })

const bmCount = computed(() => {
  const bmIds = new Set(items.value.map(i => i.pixel_bm_id).filter(Boolean))
  return bmIds.size
})

let searchTimer = null
function onSearch() { clearTimeout(searchTimer); searchTimer = setTimeout(() => { page.value = 1; loadData() }, 300) }

async function loadData() {
  loading.value = true
  try {
    const params = { page: page.value, size: size.value }
    if (search.value) params.search = search.value
    const res = await fbApi.listAllPixels(params)
    items.value = res.items; total.value = res.total
  } catch (e) { ElMessage.error('加载失败') }
  finally { loading.value = false }
}

async function loadBmOptions() {
  try { const r = await fbApi.pixelBmOptions(); pixelBmOptions.value = r.data || [] } catch(e) {}
}

function openCreate() {
  editingId.value = null
  form.pixel_name = ''; form.pixel_id = ''; form.pixel_bm_id = null
  dialogVisible.value = true
}

function openEdit(row) {
  editingId.value = row.id
  form.pixel_name = row.pixel_name
  form.pixel_id = row.pixel_id
  form.pixel_bm_id = row.pixel_bm_id
  form.bm_name = row.bm_name
  form.bm_bm_id = row.bm_bm_id
  dialogVisible.value = true
}

async function handleSave() {
  if (!form.pixel_name) return ElMessage.warning('请填写像素名')
  if (!editingId.value && !form.pixel_id) return ElMessage.warning('请填写像素 ID')
  if (!editingId.value && !form.pixel_bm_id) return ElMessage.warning('请选择所属 BM')
  saving.value = true
  try {
    if (editingId.value) {
      await fbApi.updatePixel(editingId.value, { pixel_name: form.pixel_name })
    } else {
      await fbApi.createPixel(form.pixel_bm_id, { pixel_name: form.pixel_name, pixel_id: form.pixel_id })
    }
    ElMessage.success(editingId.value ? '已更新' : '已添加')
    dialogVisible.value = false; loadData()
  } catch (e) { ElMessage.error(e.response?.data?.error || '保存失败') }
  finally { saving.value = false }
}

async function handleDelete(id) {
  try { await fbApi.deletePixel(id); ElMessage.success('已删除'); loadData() }
  catch (e) { ElMessage.error(e.response?.data?.error || '删除失败') }
}

onMounted(() => { loadBmOptions(); loadData() })
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
.stat-icon-bm { background: #fef3c7; }
.stat-icon-search { background: #d1fae5; }
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
.no-data { color: #9ca3af; font-size: 12px; }
</style>
