<template>
  <el-select v-if="visible" :model-value="modelValue" @update:model-value="onChange"
    placeholder="全部用户" style="width:150px;" clearable filterable>
    <el-option v-for="u in users" :key="u.id" :label="u.display_name || u.username" :value="u.id" />
  </el-select>
</template>

<script setup>
import { ref, computed, watch } from 'vue'
import { useAuthStore } from '@/stores/auth'
import api from '@/api/client'

defineProps({ modelValue: { type: [String, Number], default: '' } })
const emit = defineEmits(['update:modelValue', 'change'])

const auth = useAuthStore()
const visible = computed(() => auth.canManageAccounts)
const users = ref([])
let loaded = false

// 身份可能晚于组件挂载就绪（auth.user 由 App.vue 根组件的 onMounted 或异步 fetchMe 写入），
// 故用 watch 而不是 onMounted：user 一就绪就拉取，且只拉一次。
watch(
  () => auth.user?.id,
  (uid) => {
    if (uid && visible.value) fetchUsers()
  },
  { immediate: true }
)

async function fetchUsers() {
  if (loaded) return
  try {
    const res = await api.get('/platform/users')
    users.value = res.users || []
    loaded = true
  } catch { /* 用户下拉加载失败不阻塞主流程 */ }
}

function onChange(val) {
  emit('update:modelValue', val)
  emit('change', val)
}
</script>
