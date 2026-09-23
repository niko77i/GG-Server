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

// 身份由 App.vue 根组件的 onMounted 调 initFromStorage 水合，而子组件 setup 恒早于父组件
// onMounted，面板的首次 load() 正落在父组件 onMounted 里（同类教训见 UserManageView.vue:218）。
// 若等到 watch 触发才写默认值，GG/MCC 面板的 dedupLoader 会把那次 change 触发的重载吞掉
// （首次请求仍在途 → 返回同一 Promise，不重发），表现为「下拉显示自己、表格却是全部用户」的
// 静默错数据。故在 setup 阶段先幂等补一次水合，让默认值赶在首次请求之前落进筛选状态。
if (!auth.user) auth.initFromStorage()

// 用 watch 而非 onMounted：user 一就绪就拉取用户列表并套默认值，且只做一次。
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
