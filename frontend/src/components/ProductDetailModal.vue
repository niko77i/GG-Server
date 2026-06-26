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
    </div>
    <template #footer>
      <el-button @click="$emit('update:visible', false)">关闭</el-button>
    </template>
  </el-dialog>
</template>

<script setup>
import { ref } from 'vue'
import { useProductStore } from '@/stores/products'

const props = defineProps({ visible: Boolean, prodId: Number })
defineEmits(['update:visible'])
const store = useProductStore()
const product = ref(null)

async function load() {
  if (props.prodId) {
    const res = await store.loadProductDetail(props.prodId)
    product.value = res.product
  }
}
</script>
