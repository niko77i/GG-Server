<template>
  <div class="fb-panel">
    <div class="panel-header">
      <h2>🔷 像素BM管理</h2>
      <el-button type="primary" @click="openCreate">➕ 新增像素BM</el-button>
    </div>

    <el-table :data="items" stripe border v-loading="loading">
      <el-table-column prop="name" label="BM名称" min-width="150" />
      <el-table-column prop="bm_id" label="BMID" width="150" />
      <el-table-column prop="note" label="备注" min-width="120" />
      <el-table-column prop="pixel_count" label="像素数" width="80" />
      <el-table-column label="操作" width="240" fixed="right">
        <template #default="{ row }">
          <el-button size="small" type="primary" link @click="openPixels(row)">管理像素</el-button>
          <el-button size="small" link @click="openEdit(row)">编辑</el-button>
          <el-popconfirm title="确定删除？" @confirm="handleDelete(row.id)">
            <template #reference>
              <el-button size="small" type="danger" link>删除</el-button>
            </template>
          </el-popconfirm>
        </template>
      </el-table-column>
    </el-table>

    <el-pagination v-if="total > size" v-model:current-page="page" :page-size="size" :total="total"
      layout="prev, pager, next" @current-change="loadData" style="margin-top:16px;justify-content:flex-end" />

    <!-- BM弹窗 -->
    <el-dialog v-model="dialogVisible" :title="editingId ? '编辑像素BM' : '新增像素BM'" width="450px">
      <el-form :model="form" label-width="80px">
        <el-form-item label="BM名称" required><el-input v-model="form.name" /></el-form-item>
        <el-form-item label="BMID" required>
          <el-input v-model="form.bm_id" @input="form.bm_id = form.bm_id.replace(/\D/g,'')" />
        </el-form-item>
        <el-form-item label="备注"><el-input v-model="form.note" /></el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="handleSave">保存</el-button>
      </template>
    </el-dialog>

    <!-- 像素管理弹窗 -->
    <el-dialog v-model="pixelDialogVisible" :title="'管理像素 — ' + pixelBmTarget?.name" width="550px">
      <el-button type="primary" size="small" @click="openAddPixel" style="margin-bottom:12px">➕ 添加像素</el-button>
      <el-table :data="pixels" stripe border size="small">
        <el-table-column prop="pixel_name" label="像素名" min-width="150" />
        <el-table-column prop="pixel_id" label="像素ID" width="180" />
        <el-table-column label="操作" width="100">
          <template #default="{ row: px }">
            <el-popconfirm title="确定删除？" @confirm="handleDeletePixel(px.id)">
              <template #reference>
                <el-button size="small" type="danger" link>删除</el-button>
              </template>
            </el-popconfirm>
          </template>
        </el-table-column>
      </el-table>
    </el-dialog>

    <!-- 添加像素弹窗 -->
    <el-dialog v-model="addPixelVisible" title="添加像素" width="400px">
      <el-form :model="pixelForm" label-width="80px">
        <el-form-item label="像素名" required><el-input v-model="pixelForm.pixel_name" /></el-form-item>
        <el-form-item label="像素ID" required>
          <el-input v-model="pixelForm.pixel_id" @input="pixelForm.pixel_id = pixelForm.pixel_id.replace(/\D/g,'')" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="addPixelVisible = false">取消</el-button>
        <el-button type="primary" :loading="addingPixel" @click="handleAddPixel">添加</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, reactive, onMounted } from 'vue'
import { fbApi } from '../../api/fb'
import { ElMessage } from 'element-plus'

const items = ref([]); const loading = ref(false)
const page = ref(1); const size = ref(50); const total = ref(0)
const dialogVisible = ref(false); const editingId = ref(null); const saving = ref(false)
const form = reactive({ name: '', bm_id: '', note: '' })

const pixelDialogVisible = ref(false); const pixelBmTarget = ref(null); const pixels = ref([])
const addPixelVisible = ref(false); const addingPixel = ref(false)
const pixelForm = reactive({ pixel_name: '', pixel_id: '' })

async function loadData() {
  loading.value = true
  try {
    const res = await fbApi.listPixelBms({ page: page.value, size: size.value })
    items.value = res.items; total.value = res.total
  } finally { loading.value = false }
}

function openCreate() { editingId.value = null; form.name = ''; form.bm_id = ''; form.note = ''; dialogVisible.value = true }
function openEdit(row) { editingId.value = row.id; form.name = row.name; form.bm_id = row.bm_id; form.note = row.note; dialogVisible.value = true }
async function handleSave() {
  if (!form.name || !form.bm_id) return ElMessage.warning('请填写完整')
  saving.value = true
  try {
    if (editingId.value) {
      await fbApi.updatePixelBm(editingId.value, { name: form.name, note: form.note })
    } else {
      await fbApi.createPixelBm({ name: form.name, bm_id: form.bm_id, note: form.note })
    }
    ElMessage.success(editingId.value ? '已更新' : '已创建')
    dialogVisible.value = false; loadData()
  } catch (e) { ElMessage.error(e.response?.data?.error || '保存失败') }
  finally { saving.value = false }
}
async function handleDelete(id) { await fbApi.deletePixelBm(id); ElMessage.success('已删除'); loadData() }

async function openPixels(row) {
  pixelBmTarget.value = row
  const res = await fbApi.listPixels(row.id)
  pixels.value = res.data || []
  pixelDialogVisible.value = true
}
function openAddPixel() { pixelForm.pixel_name = ''; pixelForm.pixel_id = ''; addPixelVisible.value = true }
async function handleAddPixel() {
  if (!pixelForm.pixel_name || !pixelForm.pixel_id) return ElMessage.warning('请填写完整')
  addingPixel.value = true
  try {
    await fbApi.createPixel(pixelBmTarget.value.id, pixelForm)
    ElMessage.success('已添加')
    addPixelVisible.value = false
    openPixels(pixelBmTarget.value)
  } catch (e) { ElMessage.error(e.response?.data?.error || '添加失败') }
  finally { addingPixel.value = false }
}
async function handleDeletePixel(id) { await fbApi.deletePixel(id); ElMessage.success('已删除'); openPixels(pixelBmTarget.value) }

onMounted(loadData)
</script>

<style scoped>
.fb-panel { padding: 20px; }
.panel-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 16px; }
.panel-header h2 { margin: 0; font-size: 18px; }
</style>
