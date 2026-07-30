<template>
  <div class="fb-settings">
    <!-- 页面头部 -->
    <div class="page-header">
      <h2 class="page-title">⚙ FB设置</h2>
      <p class="page-subtitle">管理地区、商务人员和账户状态等基础配置数据</p>
    </div>

    <!-- 三栏布局 -->
    <el-row :gutter="20">
      <!-- 第一栏：地区管理 -->
      <el-col :xs="24" :md="12" :lg="8">
        <el-card class="setting-card" shadow="never">
          <template #header>
            <span class="card-title">🌍 地区管理</span>
          </template>

          <div class="add-form">
            <el-input v-model="newRegionName" placeholder="地区名" size="small" />
            <el-input v-model="newRegionTz" placeholder="时区（如 GMT+8）" size="small" />
            <el-button type="primary" size="small" @click="createRegion">添加</el-button>
          </div>

          <div v-if="regionOptions.length" class="tag-list">
            <div v-for="item in regionOptions" :key="item.id" class="tag-row">
              <el-tag size="default">{{ item.name }}{{ item.timezone ? ' · ' + item.timezone : '' }}</el-tag>
              <el-popconfirm title="确定删除？" @confirm="deleteRegion(item.id)">
                <template #reference>
                  <el-button class="tag-delete-btn" size="small" type="danger" link>删除</el-button>
                </template>
              </el-popconfirm>
            </div>
          </div>
          <el-empty v-else description="暂无地区" :image-size="60" />
        </el-card>
      </el-col>

      <!-- 第二栏：商务人员管理 -->
      <el-col :xs="24" :md="12" :lg="8">
        <el-card class="setting-card" shadow="never">
          <template #header>
            <span class="card-title">👤 商务人员管理</span>
          </template>

          <div class="add-form">
            <el-input v-model="newSalesName" placeholder="新建商务名称" size="small" @keyup.enter="createSalesPerson" />
            <el-button type="primary" size="small" @click="createSalesPerson">添加</el-button>
          </div>

          <div v-if="salesPersons.length" class="tag-list">
            <div v-for="item in salesPersons" :key="item.id" class="tag-row">
              <el-tag size="default">{{ item.name }}</el-tag>
              <el-popconfirm title="确定删除？" @confirm="deleteSalesPerson(item.id)">
                <template #reference>
                  <el-button class="tag-delete-btn" size="small" type="danger" link>删除</el-button>
                </template>
              </el-popconfirm>
            </div>
          </div>
          <el-empty v-else description="暂无商务人员" :image-size="60" />
        </el-card>
      </el-col>

      <!-- 第三栏：账户状态管理 -->
      <el-col :xs="24" :md="12" :lg="8">
        <el-card class="setting-card" shadow="never">
          <template #header>
            <span class="card-title">📊 账户状态管理</span>
          </template>

          <div class="add-form">
            <el-input v-model="newStatusName" placeholder="新建状态名称" size="small" @keyup.enter="createStatus" />
            <el-button type="primary" size="small" @click="createStatus">添加</el-button>
          </div>

          <div v-if="statuses.length" class="tag-list">
            <div v-for="item in statuses" :key="item.id" class="tag-row">
              <el-tag size="default">{{ item.name }}</el-tag>
              <el-popconfirm title="确定删除？" @confirm="deleteStatus(item.id)">
                <template #reference>
                  <el-button class="tag-delete-btn" size="small" type="danger" link>删除</el-button>
                </template>
              </el-popconfirm>
            </div>
          </div>
          <el-empty v-else description="暂无状态" :image-size="60" />
        </el-card>
      </el-col>
    </el-row>
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
  try { const r = await client.get('/sales-persons/list'); salesPersons.value = r.sales_persons || [] } catch(e) { console.warn(e) }
  try { const r = await client.get('/statuses/list'); statuses.value = r.statuses || r.data || [] } catch(e) { console.warn(e) }
  try { const r = await client.get('/regions/list'); regionOptions.value = (r.regions || []).map(r => typeof r === 'string' ? { name: r, timezone: '' } : r) } catch(e) { console.warn(e) }
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
async function deleteSalesPerson(id) {
  try {
    await client.delete(`/sales-persons/${id}`)
    ElMessage.success('已删除'); loadData()
  } catch(e) {
    const msg = e.response?.data?.error || '删除失败'
    const products = e.response?.data?.products
    ElMessage.error(products ? `${msg}：${products.join('、')}` : msg)
  }
}

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
/* ===== 页面容器 ===== */
.fb-settings {
  background: #f5f6f8;
  min-height: 100vh;
  padding: 24px;
}

/* ===== 页面头部 ===== */
.page-header {
  margin-bottom: 24px;
}

.page-title {
  margin: 0 0 6px 0;
  font-size: 20px;
  font-weight: 700;
  color: #1a1a1a;
  line-height: 1.4;
}

.page-subtitle {
  margin: 0;
  font-size: 13px;
  color: #999;
  line-height: 1.4;
}

/* ===== 卡片通用 ===== */
.setting-card {
  border-radius: 12px;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.06);
  border: none;
  margin-bottom: 20px;
  transition: box-shadow 0.25s ease;
}

.setting-card:hover {
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.1);
}

.setting-card :deep(.el-card__header) {
  padding: 16px 20px;
  border-bottom: 1px solid #f0f0f0;
}

.setting-card :deep(.el-card__body) {
  padding: 20px;
}

.card-title {
  font-size: 15px;
  font-weight: 600;
  color: #303133;
}

/* ===== 添加表单 ===== */
.add-form {
  display: flex;
  gap: 8px;
  margin-bottom: 16px;
  flex-wrap: wrap;
}

.add-form .el-input {
  flex: 1;
  min-width: 100px;
}

.add-form .el-button {
  flex-shrink: 0;
  white-space: nowrap;
}

/* ===== 标签列表 ===== */
.tag-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.tag-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 8px 12px;
  background: #fafafa;
  border-radius: 8px;
  transition: background 0.2s ease;
}

.tag-row:hover {
  background: #f0f5ff;
}

.tag-row .el-tag {
  font-size: 13px;
  max-width: 100%;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.tag-delete-btn {
  font-size: 12px;
  padding: 0 4px;
  flex-shrink: 0;
  margin-left: 8px;
  opacity: 0;
  transition: opacity 0.2s ease;
}

.tag-row:hover .tag-delete-btn {
  opacity: 1;
}

/* ===== 空状态 ===== */
.setting-card :deep(.el-empty) {
  padding: 20px 0;
}

.setting-card :deep(.el-empty__description) {
  margin-top: 8px;
  font-size: 13px;
  color: #c0c4cc;
}

/* ===== 响应式 ===== */
@media (max-width: 768px) {
  .fb-settings {
    padding: 16px;
  }

  .page-header {
    margin-bottom: 16px;
  }

  .page-title {
    font-size: 18px;
  }

  .add-form {
    flex-direction: column;
  }

  .add-form .el-input {
    min-width: unset;
    width: 100%;
  }

  .add-form .el-button {
    width: 100%;
  }
}
</style>
