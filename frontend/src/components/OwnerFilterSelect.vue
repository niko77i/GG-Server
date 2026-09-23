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
import { defaultOwnerScope } from '@/utils/ownerScope'

const props = defineProps({ modelValue: { type: [String, Number], default: '' } })
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
    if (uid && visible.value) {
      fetchUsers()
      applyDefaultScope()
    }
  },
  { immediate: true }
)

// 首次进入面板时套用默认作用域（developer/admin → 自己；户管 → 全部）。
// 只在父组件尚无值时生效：用户手动清空或另选后不会被打回（watch 只认 user.id 变化）。
function applyDefaultScope() {
  const v = props.modelValue
  if (v !== '' && v !== null && v !== undefined) return
  const def = defaultOwnerScope(auth.user, auth.effectivePlatform)
  if (def !== '') onChange(def)
}

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
