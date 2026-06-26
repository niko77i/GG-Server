<template>
  <el-dialog :model-value="visible" @update:model-value="$emit('update:visible', $event)"
    title="📋 产品详情" width="750px" @open="load">
    <div v-if="product" style="font-size:13px;">
      <div style="margin-bottom:12px;">
        <strong>{{ product.product_name }}</strong> &nbsp;
        KPI: {{ product.kpi || '-' }} &nbsp; 地区: {{ product.region || '-' }} &nbsp;
        MCC: {{ product.mcc_name ? product.mcc_name + ' (' + product.mcc_code + ')' : '未分配' }}
      </div>

      <!-- 关联账户状态统计 -->
      <div v-if="product.related_account_count" style="display:flex;gap:8px;margin-bottom:12px;flex-wrap:wrap;">
        <el-tag v-for="(cnt, status) in product.status_count" :key="status" :type="status === '存活' ? 'success' : status === '验证' ? 'warning' : status === '死亡' ? 'danger' : 'info'">
          {{ status }} {{ cnt }}
        </el-tag>
      </div>

      <h4>📌 关联账户（{{ product.related_account_count || 0 }} 个）</h4>
      <el-table :data="product.related_accounts" size="small" v-if="product.related_accounts?.length">
        <el-table-column prop="name" label="账户名称" />
        <el-table-column prop="account_id" label="账户 ID" />
        <el-table-column prop="status" label="状态">
          <template #default="{ row }">
            <el-tag size="small" :type="row.status === '存活' ? 'success' : row.status === '验证' ? 'warning' : row.status === '死亡' ? 'danger' : 'info'">{{ row.status }}</el-tag>
          </template>
        </el-table-column>
      </el-table>
      <el-empty v-else description="未关联 MCC 或 MCC 下无账户" :image-size="40" />

      <h4 style="margin-top:12px;">📦 包列表（{{ (product.packages || []).length }} 个）</h4>
      <el-table :data="product.packages" size="small" max-height="200">
        <el-table-column prop="series_name" label="系列名" />
        <el-table-column prop="package_name" label="包名" />
        <el-table-column label="状态">
          <template #default="{ row }">
            {{ row.status === 'paused' ? '暂停' : row.status === 'dropped' ? '掉包' : row.status === 'rejected' ? '拒登' : '正常' }}
          </template>
        </el-table-column>
      </el-table>

      <el-divider />
      <h4>🏃 在跑成员</h4>
      <div style="display:flex;gap:6px;flex-wrap:wrap;margin-bottom:10px;">
        <el-tag
          v-for="rid in runnerIds"
          :key="rid"
          closable
          @close="removeRunner(rid)"
          size="small"
        >
          {{ getUserName(rid) }}
        </el-tag>
        <span v-if="!runnerIds.length" style="color:#999;font-size:12px;">暂无 runner</span>
      </div>
      <el-select
        v-model="newRunnerId"
        placeholder="添加 runner..."
        size="small"
        style="width:200px;"
        @change="addRunner"
      >
        <el-option
          v-for="u in availableUsers"
          :key="u.id"
          :label="u.display_name || u.username"
          :value="u.id"
          :disabled="runnerIds.includes(u.id)"
        />
      </el-select>
    </div>
    <template #footer>
      <el-button @click="$emit('update:visible', false)">关闭</el-button>
    </template>
  </el-dialog>
</template>

<script setup>
import { ref, computed } from 'vue'
import { useProductStore } from '@/stores/products'
import { productsApi } from '@/api/products'
import { adminApi } from '@/api/admin'
import { ElMessage } from 'element-plus'

const props = defineProps({ visible: Boolean, prodId: Number })
defineEmits(['update:visible'])
const store = useProductStore()
const product = ref(null)
const availableUsers = ref([])
const newRunnerId = ref(null)

const runnerIds = computed(() => {
  if (!product.value) return []
  const ids = product.value.runner_ids
  if (!ids) return []
  if (Array.isArray(ids)) return ids
  try { const parsed = JSON.parse(ids); return Array.isArray(parsed) ? parsed : [] }
  catch { return [] }
})

async function load() {
  if (props.prodId) {
    const res = await store.loadProductDetail(props.prodId)
    product.value = res.product
    loadUsers()
  }
}

async function loadUsers() {
  try {
    const res = await adminApi.listUsers()
    availableUsers.value = res.users || []
  } catch { availableUsers.value = [] }
}

function getUserName(rid) {
  const u = availableUsers.value.find(u => u.id === rid)
  return u ? (u.display_name || u.username) : `User #${rid}`
}

async function addRunner(newId) {
  if (!newId || !product.value) return
  const ids = [...runnerIds.value, newId]
  try {
    await productsApi.updateRunners(product.value.id, { runner_ids: ids })
    product.value.runner_ids = JSON.stringify(ids)
    ElMessage.success('Runner 已添加')
  } catch { ElMessage.error('添加失败') }
  newRunnerId.value = null
}

async function removeRunner(rid) {
  if (!product.value) return
  const ids = runnerIds.value.filter(id => id !== rid)
  try {
    await productsApi.updateRunners(product.value.id, { runner_ids: ids })
    product.value.runner_ids = JSON.stringify(ids)
    ElMessage.success('Runner 已移除')
  } catch { ElMessage.error('移除失败') }
}
</script>
