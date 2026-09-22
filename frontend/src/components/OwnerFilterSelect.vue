<template>
  <el-select v-if="visible" :model-value="modelValue" @update:model-value="onChange"
    placeholder="全部用户" style="width:150px;" clearable filterable>
    <el-option v-for="u in users" :key="u.id" :label="u.display_name || u.username" :value="u.id" />
  </el-select>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { useAuthStore } from '@/stores/auth'
import api from '@/api/client'

const props = defineProps({ modelValue: { type: [String, Number], default: '' } })
const emit = defineEmits(['update:modelValue', 'change'])

const auth = useAuthStore()
const visible = computed(() => auth.canManageAccounts)
const users = ref([])

onMounted(async () => {
  if (!visible.value) return
  try {
    const res = await api.get('/platform/users')
    users.value = res.users || []
  } catch { /* 用户下拉加载失败不阻塞主流程 */ }
})

function onChange(val) {
  emit('update:modelValue', val)
  emit('change', val)
}
</script>
