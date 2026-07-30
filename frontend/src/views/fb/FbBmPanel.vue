<template>
  <div class="fb-panel">
    <div class="panel-header">
      <h2>🏢 账户BM管理</h2>
      <el-button type="primary" @click="openCreate">➕ 新增BM</el-button>
    </div>

    <div class="filter-bar">
      <el-select v-model="filterStatus" placeholder="全部状态" clearable style="width:140px" @change="loadData">
        <el-option label="正常" value="normal" />
        <el-option label="已封禁" value="banned" />
      </el-select>
      <el-button @click="loadData">🔄 刷新</el-button>
    </div>

    <el-table :data="items" stripe border v-loading="loading" style="width:100%">
      <el-table-column prop="name" label="BM名称" min-width="150" />
      <el-table-column prop="bm_id" label="BMID" width="150" />
      <el-table-column prop="note" label="备注" min-width="120" />
      <el-table-column prop="status" label="状态" width="80">
        <template #default="{ row }">
          <el-tag :type="row.status === 'banned' ? 'danger' : 'success'" size="small">
            {{ row.status === 'banned' ? '已封禁' : '正常' }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="account_count" label="关联账户数" width="100" />
      <el-table-column label="操作" width="220" fixed="right">
        <template #default="{ row }">
          <el-button size="small" type="primary" link @click="openEdit(row)">编辑</el-button>
          <el-button v-if="row.status !== 'banned'" size="small" type="warning" link @click="openBan(row)">封禁</el-button>
          <el-popconfirm title="确定删除？" @confirm="handleDelete(row.id)">
            <template #reference>
              <el-button size="small" type="danger" link>删除</el-button>
            </template>
          </el-popconfirm>
        </template>
      </el-table-column>
    </el-table>

    <el-pagination
      v-if="total > size"
      v-model:current-page="page" :page-size="size" :total="total"
      layout="prev, pager, next" @current-change="loadData" style="margin-top:16px;justify-content:flex-end"
    />

    <!-- BM弹窗 -->
    <el-dialog v-model="dialogVisible" :title="editingId ? '编辑BM' : '新增BM'" width="480px">
      <el-form :model="form" label-width="80px">
        <el-form-item label="BM名称" required>
          <el-input v-model="form.name" placeholder="BM名称" />
        </el-form-item>
        <el-form-item label="BMID" required>
          <el-input v-model="form.bm_id" placeholder="纯数字" @input="form.bm_id = form.bm_id.replace(/\D/g,'')" />
        </el-form-item>
        <el-form-item label="备注">
          <el-input v-model="form.note" placeholder="备注" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="handleSave">保存</el-button>
      </template>
    </el-dialog>

    <!-- 封禁迁移弹窗 -->
    <el-dialog v-model="banDialogVisible" title="封禁BM" width="500px">
      <p>确定封禁 BM「{{ banTarget?.name }}」？(关联 {{ banTarget?.account_count }} 个账户)</p>
      <el-form label-width="80px" style="margin-top:16px">
        <el-form-item label="迁移到BM">
          <el-select v-model="banForm.target_bm_id" filterable allow-create placeholder="选择或输入新BM ID" style="width:100%">
            <el-option v-for="bm in bmOptions" :key="bm.id" :label="bm.name + ' (' + bm.bm_id + ')'" :value="bm.bm_id" />
          </el-select>
        </el-form-item>
        <el-form-item v-if="isNewBmId" label="新BM名">
          <el-input v-model="banForm.target_bm_name" placeholder="输入新BM名称" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="banDialogVisible = false">取消</el-button>
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
const filterStatus = ref('')

const dialogVisible = ref(false); const editingId = ref(null); const saving = ref(false)
const form = reactive({ name: '', bm_id: '', note: '' })

const banDialogVisible = ref(false); const banTarget = ref(null)
const bmOptions = ref([]); const banning = ref(false)
const banForm = reactive({ target_bm_id: '', target_bm_name: '' })
const isNewBmId = computed(() => banForm.target_bm_id && !bmOptions.value.find(b => b.bm_id === banForm.target_bm_id))

async function loadData() {
  loading.value = true
  try {
    const params = { page: page.value, size: size.value }
    if (filterStatus.value) params.status = filterStatus.value
    const res = await fbApi.listBms(params)
    items.value = res.data.items; total.value = res.data.total
  } catch (e) { ElMessage.error('加载失败') }
  finally { loading.value = false }
}

function openCreate() {
  editingId.value = null
  form.name = ''; form.bm_id = ''; form.note = ''
  dialogVisible.value = true
}
function openEdit(row) {
  editingId.value = row.id
  form.name = row.name; form.bm_id = row.bm_id; form.note = row.note
  dialogVisible.value = true
}
async function handleSave() {
  if (!form.name || !form.bm_id) return ElMessage.warning('请填写BM名称和BMID')
  saving.value = true
  try {
    if (editingId.value) {
      await fbApi.updateBm(editingId.value, { name: form.name, note: form.note })
    } else {
      await fbApi.createBm({ name: form.name, bm_id: form.bm_id, note: form.note })
    }
    ElMessage.success(editingId.value ? '已更新' : '已创建')
    dialogVisible.value = false
    loadData()
  } catch (e) { ElMessage.error(e.response?.data?.error || '保存失败') }
  finally { saving.value = false }
}
async function handleDelete(id) {
  await fbApi.deleteBm(id)
  ElMessage.success('已删除')
  loadData()
}

async function openBan(row) {
  banTarget.value = row
  banForm.target_bm_id = ''
  banForm.target_bm_name = ''
  const res = await fbApi.bmOptions()
  bmOptions.value = (res.data || []).filter(b => b.id !== row.id)
  banDialogVisible.value = true
}
async function handleBanMigrate() {
  if (!banForm.target_bm_id) return ElMessage.warning('请选择目标BM')
  if (isNewBmId.value && !banForm.target_bm_name) return ElMessage.warning('请输入新BM名称')
  banning.value = true
  try {
    const res = await fbApi.banAndMigrate(banTarget.value.id, banForm)
    ElMessage.success(`已封禁，${res.data.migrated_accounts} 个账户已迁移`)
    if (res.data.warnings?.length) {
      setTimeout(() => res.data.warnings.forEach(w => ElMessage.warning(w)), 500)
    }
    banDialogVisible.value = false
    loadData()
  } catch (e) { ElMessage.error(e.response?.data?.error || '操作失败') }
  finally { banning.value = false }
}

onMounted(loadData)
</script>

<style scoped>
.fb-panel { padding: 20px; }
.panel-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 16px; }
.panel-header h2 { margin: 0; font-size: 18px; }
.filter-bar { display: flex; gap: 12px; margin-bottom: 16px; align-items: center; }
</style>
