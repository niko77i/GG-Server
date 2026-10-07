<template>
  <div class="fb-panel">
    <!-- 页面头部 -->
    <div class="panel-header">
      <h2 class="panel-title">FB账户管理</h2>
      <div class="header-actions">
        <el-button type="primary" @click="openCreate">新增账户</el-button>
        <el-button @click="batchImportVisible = true">📥 批量导入</el-button>
        <el-button @click="lookupVisible = true">🔍 批量查户</el-button>
        <el-button @click="deletedVisible = true">🗑 回收站</el-button>
        <el-button v-if="selected.length" @click="batchDelete" style="margin-left:auto;">🗑 批量删除</el-button>
      </div>
    </div>

    <!-- 统计卡片 -->
    <el-row :gutter="16" class="stats-row">
      <el-col :span="8">
        <div class="stat-card stat-card--blue">
          <div class="stat-card__label">总账户</div>
          <div class="stat-card__value">{{ total }}</div>
        </div>
      </el-col>
      <el-col :span="8">
        <div class="stat-card stat-card--green">
          <div class="stat-card__label">关联 BM</div>
          <div class="stat-card__value">{{ [...new Set(items.flatMap(i => (i.bms || []).map(b => b.id)))].length }}</div>
        </div>
      </el-col>
      <el-col :span="8">
        <div class="stat-card stat-card--orange">
          <div class="stat-card__label">当前筛选结果</div>
          <div class="stat-card__value">{{ items.length }}</div>
        </div>
      </el-col>
    </el-row>

    <!-- 筛选栏卡片 -->
    <el-card class="filter-card" shadow="never">
      <div class="filter-bar">
        <el-input v-model="search" placeholder="搜索ID/名称" clearable style="width:200px" @input="onSearch" />
        <el-select v-model="filterBm" placeholder="全部BM" clearable style="width:180px" @change="loadData">
          <el-option v-for="b in bmOptions" :key="b.id" :label="b.name" :value="b.id" />
        </el-select>
        <OwnerFilterSelect v-model="ownerId" @change="onOwnerChange" />
        <el-button @click="loadData">刷新</el-button>
      </div>
    </el-card>

    <!-- 表格卡片 -->
    <el-card class="table-card" shadow="never">
      <template #header>
        <span class="table-card__header-text">共 {{ total }} 个账户</span>
      </template>
      <el-table :data="items" stripe border v-loading="loading" @selection-change="val => selected = val">
        <el-table-column type="selection" width="45" />
        <el-table-column prop="name" label="账户名" min-width="120" />
        <el-table-column prop="account_id" label="账户ID" width="160" />
        <el-table-column label="所属BM" min-width="140">
          <template #default="{ row }">{{ row.bms?.map(b=>b.name).join(', ') }}</template>
        </el-table-column>
        <el-table-column label="位置" min-width="120">
          <template #default="{ row }">
            <span v-if="row.primary_bm_name">{{ row.primary_bm_name }}</span>
            <span v-else style="color:#c0c4cc;">—</span>
          </template>
        </el-table-column>
        <el-table-column label="所属渠道" width="110">
          <template #default="{ row }">{{ optName(channelOptions, row.channel_id) }}</template>
        </el-table-column>
        <el-table-column label="资产类型" width="110">
          <template #default="{ row }">{{ optName(assetTypeOptions, row.asset_type_id) }}</template>
        </el-table-column>
        <el-table-column label="状态" width="100">
          <template #default="{ row }">{{ optName(statusOptions, row.status_id) }}</template>
        </el-table-column>
        <el-table-column prop="operator" label="操作人" width="100" />
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
        layout="prev,pager,next" @current-change="loadData" class="table-pagination" />
    </el-card>

    <!-- 弹窗 -->
    <FbAccountBatchImportModal v-model:visible="batchImportVisible" @imported="loadData" />
    <FbAccountBatchLookupModal v-model:visible="lookupVisible" />

    <el-dialog v-model="dialogVisible" :title="editingId?'编辑账户':'新增账户'" width="520px" class="account-dialog">
      <el-form :model="form" label-width="90px" class="account-form">
        <el-form-item label="账户名" required>
          <el-input v-model="form.name" placeholder="请输入账户名" />
        </el-form-item>
        <el-form-item label="账户ID" required>
          <el-input v-model="form.account_id" placeholder="请输入纯数字ID" @input="form.account_id=form.account_id.replace(/\D/g,'')" />
        </el-form-item>
        <el-form-item label="关联BM">
          <el-select v-model="form.bm_ids" multiple placeholder="选择BM" style="width:100%">
            <el-option v-for="b in bmOptions" :key="b.id" :label="b.name+' ('+b.bm_id+')'" :value="b.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="时区">
          <el-input v-model="form.timezone" placeholder="如 Asia/Shanghai" />
        </el-form-item>
        <el-form-item label="到手时间">
          <el-input v-model="form.acquired_date" placeholder="YYYY-MM-DD" />
        </el-form-item>
        <el-form-item label="状态">
          <el-select v-model="form.status_id" clearable style="width:100%" placeholder="请选择状态">
            <el-option v-for="s in statusOptions" :key="s.id" :label="s.name" :value="s.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="主BM（位置）">
          <el-select v-model="form.primary_bm_id" clearable placeholder="从已关联的BM中选择" style="width:100%">
            <el-option v-for="b in form.bm_ids" :key="b"
                       :label="(bmOptions.find(x=>x.id===b)||{}).name || ('BM#'+b)" :value="b" />
          </el-select>
        </el-form-item>
        <el-form-item label="所属渠道">
          <el-select v-model="form.channel_id" clearable placeholder="请选择渠道" style="width:100%">
            <el-option v-for="c in channelOptions" :key="c.id" :label="c.name" :value="c.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="资产类型">
          <el-select v-model="form.asset_type_id" clearable placeholder="请选择资产类型" style="width:100%">
            <el-option v-for="t in assetTypeOptions" :key="t.id" :label="t.name" :value="t.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="接户运营">
          <el-input v-model="form.acceptor" placeholder="如：张三转李四" />
        </el-form-item>
        <el-form-item label="单价">
          <el-input v-model="form.unit_price" placeholder="数字" />
        </el-form-item>
        <el-form-item label="入库">
          <el-input v-model="form.inbound_qty" placeholder="数量" />
        </el-form-item>
        <el-form-item label="出库时间">
          <el-input v-model="form.outbound_date" placeholder="YYYY-MM-DD" />
        </el-form-item>
        <el-form-item label="出库">
          <el-input v-model="form.outbound_qty" placeholder="数量" />
        </el-form-item>
        <el-form-item label="消耗">
          <el-input v-model="form.consumption" />
        </el-form-item>
        <el-form-item label="产品信息">
          <el-input v-model="form.remark" type="textarea" :rows="2" />
        </el-form-item>
      </el-form>
      <template #footer>
        <div class="dialog-footer">
          <el-button @click="dialogVisible=false">取消</el-button>
          <el-button type="primary" :loading="saving" @click="handleSave">保存</el-button>
        </div>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, reactive, onMounted } from 'vue'
import { fbApi } from '../../api/fb'
import { ElMessage, ElMessageBox } from 'element-plus'
import client from '../../api/client'
import OwnerFilterSelect from '@/components/OwnerFilterSelect.vue'
import FbAccountBatchImportModal from '@/components/fb/FbAccountBatchImportModal.vue'
import FbAccountBatchLookupModal from '@/components/fb/FbAccountBatchLookupModal.vue'

const items = ref([]); const loading = ref(false); const page = ref(1); const size = ref(50); const total = ref(0)
const search = ref(''); const filterBm = ref(''); const ownerId = ref(''); const selected = ref([])
const lookupVisible = ref(false); const batchImportVisible = ref(false); const deletedVisible = ref(false)
const bmOptions = ref([]); const statusOptions = ref([]); const dialogVisible = ref(false)
const channelOptions = ref([]); const assetTypeOptions = ref([]); const fbUsers = ref([])
const editingId = ref(null); const saving = ref(false)

// 选项 id → 名字。后端 list_accounts 只返回 *_id，不返回名字（见 Step 2 的说明），
// 用本页已加载的选项表映射，避免为此改后端查询。
//
// ⚠️ 形参 list 收的是**普通数组**不是 ref：本函数只在模板里调用，而 `<script setup>`
// 的顶层 ref 在模板中会自动解包，传进来的是 `channelOptions.value` 那个数组。
// 写成 `list.value.find(...)` 会 TypeError。
function optName(list, id) {
  if (id === null || id === undefined || id === '') return ''
  const o = (list || []).find(x => x.id === id)
  return o ? o.name : ''
}

const form = reactive({
  name:'', account_id:'', bm_ids:[], primary_bm_id:null, timezone:'', acquired_date:'',
  status_id:null, channel_id:null, asset_type_id:null, unit_price:'', inbound_qty:'',
  acceptor:'', outbound_date:'', outbound_qty:'', consumption:'', remark:'',
})

let searchTimer = null
function onSearch() { clearTimeout(searchTimer); searchTimer = setTimeout(loadData, 300) }

async function loadData() {
  loading.value = true
  try {
    const p = { page: page.value, size: size.value }
    if (search.value) p.search = search.value
    if (filterBm.value) p.bm_id = filterBm.value
    if (ownerId.value) p.owner_id = ownerId.value
    const res = await fbApi.listAccounts(p)
    items.value = res.items; total.value = res.total
  } finally { loading.value = false }
}

// 切换用户筛选后回到第 1 页，避免当前页码超出新结果集导致列表空白且分页控件消失
function onOwnerChange() {
  page.value = 1
  loadData()
}

async function loadOptions() {
  try { const r = await fbApi.bmOptions(); bmOptions.value = r.data || [] } catch(e) { console.warn('loadOptions bm', e) }
  try { const r = await client.get('/statuses/list'); statusOptions.value = r.statuses || r.data || [] } catch(e) { console.warn('loadOptions statuses', e) }
  try { const r = await fbApi.listChannels(); channelOptions.value = r.items || [] } catch(e) { console.warn('loadOptions channels', e) }
  try { const r = await fbApi.listAssetTypes(); assetTypeOptions.value = r.items || [] } catch(e) { console.warn('loadOptions assetTypes', e) }
  try { const r = await fbApi.listFbUsers(); fbUsers.value = r.users || [] } catch(e) { console.warn('loadOptions users', e) }
}

function openCreate() {
  editingId.value = null
  Object.assign(form, {
    name:'', account_id:'', bm_ids:[], primary_bm_id:null, timezone:'', acquired_date:'',
    status_id:null, channel_id:null, asset_type_id:null, unit_price:'', inbound_qty:'',
    acceptor:'', outbound_date:'', outbound_qty:'', consumption:'', remark:'',
  })
  dialogVisible.value = true
}
function openEdit(row) {
  editingId.value = row.id
  Object.assign(form, {
    name: row.name, account_id: row.account_id,
    bm_ids: (row.bms||[]).map(b=>b.id),
    primary_bm_id: (row.bms||[]).find(b=>b.is_primary)?.id || null,
    timezone: row.timezone, acquired_date: row.acquired_date, status_id: row.status_id,
    channel_id: row.channel_id, asset_type_id: row.asset_type_id,
    unit_price: row.unit_price, inbound_qty: row.inbound_qty,
    acceptor: row.acceptor, outbound_date: row.outbound_date,
    outbound_qty: row.outbound_qty, consumption: row.consumption, remark: row.remark,
  })
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
async function batchDelete() {
  if (!selected.value.length) return
  try {
    await ElMessageBox.confirm(`确定删除选中的 ${selected.value.length} 个账户？`, '确认', { type: 'warning' })
  } catch { return }
  try {
    await fbApi.batchDelete({ ids: selected.value.map(s => s.id) })
    ElMessage.success('已删除')
    selected.value = []
    loadData()
  } catch (e) {
    ElMessage.error(e.response?.data?.error || '删除失败')
  }
}
onMounted(() => { loadOptions(); loadData() })
</script>

<style scoped>
/* ========== 页面容器 ========== */
.fb-panel {
  padding: 24px;
  background: #f5f6f8;
  min-height: 100vh;
}

/* ========== 页面头部 ========== */
.panel-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 20px;
}

.header-actions {
  display: flex;
  gap: 8px;
  align-items: center;
}

.panel-title {
  margin: 0;
  font-size: 20px;
  font-weight: 700;
  color: #1a1a2e;
  letter-spacing: -0.3px;
}

/* ========== 统计卡片行 ========== */
.stats-row {
  margin-bottom: 16px;
}

.stat-card {
  background: #fff;
  border-radius: 12px;
  padding: 20px 24px;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.06);
  cursor: default;
  transition: transform 0.2s ease, box-shadow 0.2s ease;
  position: relative;
  overflow: hidden;
}

.stat-card::before {
  content: '';
  position: absolute;
  left: 0;
  top: 0;
  bottom: 0;
  width: 4px;
  border-radius: 12px 0 0 12px;
}

.stat-card:hover {
  transform: translateY(-2px);
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.1);
}

.stat-card--blue::before { background: #409eff; }
.stat-card--green::before { background: #67c23a; }
.stat-card--orange::before { background: #e6a23c; }

.stat-card__label {
  font-size: 13px;
  color: #909399;
  margin-bottom: 8px;
  font-weight: 500;
}

.stat-card__value {
  font-size: 28px;
  font-weight: 700;
  color: #1a1a2e;
  line-height: 1;
}

/* ========== 筛选栏卡片 ========== */
.filter-card {
  margin-bottom: 16px;
  border-radius: 12px;
  border: none;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.06);
}

.filter-card :deep(.el-card__body) {
  padding: 16px 20px;
  background: #f8f9fa;
  border-radius: 12px;
}

.filter-bar {
  display: flex;
  gap: 12px;
  align-items: center;
  flex-wrap: wrap;
}

/* ========== 表格卡片 ========== */
.table-card {
  border-radius: 12px;
  border: none;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.06);
}

.table-card :deep(.el-card__header) {
  padding: 16px 20px;
  border-bottom: 1px solid #ebeef5;
  background: #fff;
  border-radius: 12px 12px 0 0;
}

.table-card :deep(.el-card__body) {
  padding: 0 20px 20px;
}

.table-card__header-text {
  font-size: 15px;
  font-weight: 600;
  color: #303133;
}

/* 表格样式优化 */
:deep(.el-table) {
  --el-table-header-bg-color: #f5f7fa;
}

:deep(.el-table th.el-table__cell) {
  background-color: #f5f7fa;
  color: #606266;
  font-weight: 600;
  font-size: 13px;
  height: 48px;
}

:deep(.el-table td.el-table__cell) {
  font-size: 13px;
}

:deep(.el-table--striped .el-table__body tr.el-table__row--striped td.el-table__cell) {
  background-color: #fafbfc;
}

:deep(.el-table__body tr:hover > td.el-table__cell) {
  background-color: #f0f5ff;
}

/* 分页 */
.table-pagination {
  margin-top: 16px;
  display: flex;
  justify-content: flex-end;
}

/* ========== 弹窗优化 ========== */
.account-form .el-form-item {
  margin-bottom: 18px;
}

.account-form .el-form-item:last-child {
  margin-bottom: 0;
}

.account-form :deep(.el-form-item__label) {
  font-weight: 500;
  color: #303133;
}

.dialog-footer {
  display: flex;
  justify-content: flex-end;
  gap: 12px;
}

/* ========== 响应式 ========== */
@media (max-width: 992px) {
  .stats-row .el-col {
    margin-bottom: 12px;
  }

  .fb-panel {
    padding: 16px;
  }
}
</style>
