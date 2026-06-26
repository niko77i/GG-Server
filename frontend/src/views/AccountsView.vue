<template>
  <div style="display:flex;flex-direction:column;height:calc(100vh - 72px);">
    <h1 style="flex-shrink:0;">账户管理</h1>
    <div class="sticky-tabs" style="flex-shrink:0;">
      <el-tabs :model-value="activeTab" @update:model-value="switchTab">
        <el-tab-pane label="产品管理" name="products" />
        <el-tab-pane label="广告账户" name="ads" />
        <el-tab-pane label="MCC 管理" name="mcc" />
        <el-tab-pane label="设置" name="settings" />
      </el-tabs>
    </div>
    <div style="flex:1;min-height:0;overflow-y:auto;">
      <router-view />
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { useRouter, useRoute } from 'vue-router'

const router = useRouter()
const route = useRoute()
const activeTab = computed(() => {
  const p = route.path
  if (p.includes('/settings')) return 'settings'
  if (p.includes('/mcc')) return 'mcc'
  if (p.includes('/ads')) return 'ads'
  return 'products'
})

function switchTab(name) { router.push(`/accounts/${name}`) }
</script>
