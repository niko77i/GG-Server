<template>
  <el-dialog :model-value="visible" @update:model-value="$emit('update:visible', $event)"
    :title="editId ? '✏️ 编辑产品' : '➕ 新增产品'" width="480px" @open="init">
    <el-form label-position="top">
      <el-form-item label="产品 / 群名" required>
        <el-input v-model="form.product_name" />
      </el-form-item>
      <el-form-item label="KPI">
        <el-input v-model="form.kpi" />
      </el-form-item>
      <el-form-item label="地区">
        <el-input v-model="form.region" />
      </el-form-item>
      <el-form-item label="所属 MCC">
        <el-select v-model="form.mcc_id" clearable placeholder="（未分配）" style="width:100%;" filterable>
          <el-option v-for="m in mccOptions" :key="m.id" :label="m.name + ' (' + m.mcc_id + ')'" :value="m.id" />
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
import { useProductStore } from '@/stores/products'

const props = defineProps({ visible: Boolean, editId: [Number, null], mccOptions: Array })
const emit = defineEmits(['update:visible', 'saved'])
const store = useProductStore()
const saving = ref(false)
const form = reactive({ product_name: '', kpi: '', region: '', mcc_id: '' })

function init() {
  if (props.editId) {
    const p = store.products.find(p => p.id === props.editId)
    if (p) Object.assign(form, {
      product_name: p.product_name || '', kpi: p.kpi || '',
      region: p.region || '', mcc_id: p.mcc_id || '',
    })
  } else {
    Object.assign(form, { product_name: '', kpi: '', region: '', mcc_id: '' })
  }
}

async function submit() {
  if (!form.product_name) return
  saving.value = true
  try {
    if (props.editId) {
      await store.updateProduct(props.editId, { ...form, mcc_id: form.mcc_id || null })
    } else {
      await store.createProduct(form)
    }
    emit('update:visible', false)
    emit('saved')
  } finally { saving.value = false }
}
</script>
