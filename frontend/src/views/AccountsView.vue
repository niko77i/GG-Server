<template>
  <div style="display:flex;flex-direction:column;height:calc(100vh - 72px);">
    <h1 style="flex-shrink:0;">账户管理</h1>
    <div class="sticky-tabs" style="flex-shrink:0;">
      <el-tabs :model-value="activeTab" @update:model-value="switchTab">
        <el-tab-pane v-if="!auth.isHuguan" label="产品管理" name="products" />
        <!-- 用 canAccessAccounts（含普通用户）而非 canManageAccounts —— 后者是
             「跨用户管账户」开关，拿它控 Tab 会把普通用户一并挡在 Tab 外。 -->
        <el-tab-pane v-if="auth.canAccessAccounts" label="广告账户" name="ads" />
        <el-tab-pane v-if="auth.canAccessAccounts" label="MCC 管理" name="mcc" />
        <el-tab-pane v-if="auth.canAccessAccounts" label="设置" name="settings" />

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
import { useAuthStore } from '@/stores/auth'

const auth = useAuthStore()
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
