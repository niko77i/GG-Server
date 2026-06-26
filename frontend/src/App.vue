<template>
  <div v-if="isAuthPage" class="full-page">
    <router-view />
  </div>
  <div v-else style="display:flex;height:100vh;overflow:hidden;">
    <AppSidebar />
    <div style="flex:1;padding:clamp(16px,2.5vw,32px);overflow-y:auto;background:#f5f7fa;">
      <router-view />
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted } from 'vue'
import { useRoute } from 'vue-router'
import { useAuthStore } from './stores/auth'
import AppSidebar from './components/AppSidebar.vue'

const route = useRoute()
const auth = useAuthStore()

const isAuthPage = computed(() => ['/login', '/register'].includes(route.path))

onMounted(async () => {
  auth.initFromStorage()
  if (auth.isLoggedIn) {
    await auth.fetchMe()
  }
})
</script>

<style>
.full-page {
  height: 100vh;
  overflow: hidden;
}
</style>
