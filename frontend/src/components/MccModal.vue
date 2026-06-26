<template>
  <el-dialog :model-value="visible" @update:model-value="$emit('update:visible', $event)"
    :title="editId ? '✏️ 编辑 MCC' : '➕ 新增 MCC'" width="480px" @open="init">
    <el-form label-position="top">
      <el-form-item label="MCC 名称">
        <el-input v-model="form.name" />
      </el-form-item>
      <el-form-item label="MCC ID" :description="editId ? '不可修改' : ''">
        <el-input v-model="form.mcc_id" :disabled="!!editId" />
      </el-form-item>
      <el-form-item label="等级">
        <el-select v-model="form.level" filterable allow-create placeholder="输入或选择" style="width:100%;">
          <el-option v-for="l in store.settings.mcc_levels" :key="l" :label="l" :value="l" />
        </el-select>
      </el-form-item>
      <el-form-item label="上级 MCC">
        <el-select v-model="form.parent_mcc_id" clearable placeholder="（顶级）" style="width:100%;">
          <el-option label="（顶级）" value="" />
          <el-option v-for="m in parentOpts" :key="m.id" :label="m.name + ' (' + m.mcc_id + ')'" :value="m.id" />
        </el-select>
      </el-form-item>
    </el-form>
    <template #footer>
      <el-button @click="$emit('update:visible', false)">取消</el-button>
      <el-button type="primary" @click="submit" :loading="saving">💾 保存</el-button>
    </template>
  </el-dialog>
</template>

<script setup>
import { ref, reactive } from 'vue'
import { useAccountStore } from '@/stores/accounts'
import { mccApi } from '@/api/accounts'

const props = defineProps({ visible: Boolean, editId: [Number, null] })
const emit = defineEmits(['update:visible', 'saved'])
const store = useAccountStore()
const saving = ref(false)
const parentOpts = ref([])
const form = reactive({ name: '', mcc_id: '', level: '', parent_mcc_id: '' })

async function init() {
  const res = await mccApi.options()
  parentOpts.value = (res.options || []).filter(m => m.id !== props.editId)
  if (props.editId) {
    const mcc = store.mccList.find(m => m.id === props.editId)
    if (mcc) Object.assign(form, { name: mcc.name || '', mcc_id: mcc.mcc_id || '', level: mcc.level || '', parent_mcc_id: mcc.parent_mcc_id || '' })
  } else {
    Object.assign(form, { name: '', mcc_id: '', level: '', parent_mcc_id: '' })
  }
}

async function submit() {
  if (!form.name || !form.mcc_id) return
  saving.value = true
  try {
    if (props.editId) {
      await store.updateMcc(props.editId, { name: form.name, level: form.level, parent_mcc_id: form.parent_mcc_id || null })
    } else {
      await store.createMcc(form)
    }
    emit('update:visible', false)
    emit('saved')
  } finally { saving.value = false }
}
</script>
