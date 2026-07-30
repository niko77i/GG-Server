<template>
  <div class="fb-panel">
    <div class="panel-header"><h2>⚙ FB设置</h2></div>

    <el-card style="margin-bottom:16px">
      <template #header><span>🌍 地区管理</span></template>
      <div style="margin-bottom:8px">
        <el-input v-model="newRegionName" placeholder="地区名" style="width:140px" size="small" />
        <el-input v-model="newRegionTz" placeholder="时区（如 GMT+8）" style="width:120px;margin-left:8px" size="small" />
        <el-button type="primary" size="small" @click="createRegion" style="margin-left:8px">添加</el-button>
      </div>
      <el-table :data="regionOptions" border size="small">
        <el-table-column prop="name" label="地区名称" />
        <el-table-column prop="timezone" label="时区" width="140" />
        <el-table-column label="操作" width="80">
          <template #default="{row}">
            <el-popconfirm title="确定删除？" @confirm="deleteRegion(row.id)">
              <template #reference><el-button size="small" type="danger" link>删除</el-button></template>
            </el-popconfirm>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <el-card style="margin-bottom:16px">
      <template #header><span>👤 商务人员管理</span></template>
      <div style="margin-bottom:8px">
        <el-input v-model="newSalesName" placeholder="新建商务名称" style="width:200px" size="small" @keyup.enter="createSalesPerson" />
        <el-button type="primary" size="small" @click="createSalesPerson" style="margin-left:8px">添加</el-button>
      </div>
      <el-table :data="salesPersons" border size="small">
        <el-table-column prop="name" label="名称" />
        <el-table-column label="操作" width="80">
          <template #default="{row}">
            <el-popconfirm title="确定删除？" @confirm="deleteSalesPerson(row.id)">
              <template #reference><el-button size="small" type="danger" link>删除</el-button></template>
            </el-popconfirm>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <el-card>
      <template #header><span>📊 账户状态管理</span></template>
      <div style="margin-bottom:8px">
        <el-input v-model="newStatusName" placeholder="新建状态名称" style="width:200px" size="small" @keyup.enter="createStatus" />
        <el-button type="primary" size="small" @click="createStatus" style="margin-left:8px">添加</el-button>
      </div>
      <el-table :data="statuses" border size="small">
        <el-table-column prop="name" label="名称" />
        <el-table-column label="操作" width="80">
          <template #default="{row}">
            <el-popconfirm title="确定删除？" @confirm="deleteStatus(row.id)">
              <template #reference><el-button size="small" type="danger" link>删除</el-button></template>
            </el-popconfirm>
          </template>
        </el-table-column>
      </el-table>
    </el-card>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import client from '../../api/client'
import { ElMessage } from 'element-plus'

const regionOptions = ref([]); const newRegionName = ref(''); const newRegionTz = ref('')
const salesPersons = ref([]); const newSalesName = ref('')
const statuses = ref([]); const newStatusName = ref('')

async function loadData() {
  const [spRes, stRes, regRes] = await Promise.all([
    client.get('/sales-persons/list'),
    client.get('/statuses/list'),
    client.get('/regions/list'),
  ])
  salesPersons.value = spRes.sales_persons || []
  statuses.value = stRes.statuses || stRes.data || []
  regionOptions.value = (regRes.regions || []).map(r => typeof r === 'string' ? { name: r, timezone: '' } : r)
}

// 地区
async function createRegion() {
  if (!newRegionName.value.trim()) return
  await client.post('/regions/create', { name: newRegionName.value.trim(), timezone: newRegionTz.value.trim() })
  ElMessage.success('已添加'); newRegionName.value = ''; newRegionTz.value = ''; loadData()
}
async function deleteRegion(id) { await client.delete(`/regions/${id}`); ElMessage.success('已删除'); loadData() }

// 商务
async function createSalesPerson() {
  if (!newSalesName.value.trim()) return
  await client.post('/sales-persons/create', { name: newSalesName.value.trim() })
  ElMessage.success('已添加'); newSalesName.value = ''; loadData()
}
async function deleteSalesPerson(id) { await client.delete(`/sales-persons/${id}`); ElMessage.success('已删除'); loadData() }

// 状态
async function createStatus() {
  if (!newStatusName.value.trim()) return
  await client.post('/statuses/create', { name: newStatusName.value.trim() })
  ElMessage.success('已添加'); newStatusName.value = ''; loadData()
}
async function deleteStatus(id) { await client.delete(`/statuses/${id}`); ElMessage.success('已删除'); loadData() }

onMounted(loadData)
</script>

<style scoped>
.fb-panel{padding:20px}.panel-header{margin-bottom:16px}.panel-header h2{margin:0;font-size:18px}
</style>
