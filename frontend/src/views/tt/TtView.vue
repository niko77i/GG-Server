<template>
  <div style="display:flex;flex-direction:column;height:calc(100vh - 72px);">
    <h1 style="flex-shrink:0;">广告账户管理</h1>
    <div class="sticky-tabs" style="flex-shrink:0;">
      <el-tabs :model-value="activeTab" @update:model-value="switchTab">
        <el-tab-pane label="产品管理" name="products" />
        <el-tab-pane label="广告账户" name="accounts" />
        <el-tab-pane label="BC管理" name="bcs" />
        <el-tab-pane label="TT设置" name="settings" />
      </el-tabs>
    </div>
    <div style="flex:1;min-height:0;overflow-y:auto;">
      <router-view v-slot="{ Component }">
        <keep-alive>
          <component :is="Component" />
        </keep-alive>
      </router-view>
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
  if (p.includes('/accounts')) return 'accounts'
  if (p.includes('/bcs')) return 'bcs'
  return 'products'
})

function switchTab(name) { router.push(`/tt/${name}`) }
</script>
