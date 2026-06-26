<template>
  <div style="display:flex;flex-direction:column;height:100%;">
    <!-- 工具栏 — 固定 -->
    <div style="flex-shrink:0;">
      <div style="display:flex;gap:8px;margin-bottom:8px;align-items:center;">
        <el-button type="primary" @click="showModal()">➕ 新增 MCC</el-button>
        <span style="color:#888;font-size:12px;">已选 {{ selected.length }} 条</span>
        <el-button @click="batchDelete" :disabled="!selected.length">🗑 批量删除</el-button>
      </div>

      <div style="display:flex;gap:8px;margin-bottom:8px;">
        <el-input v-model="store.mccFilters.search" placeholder="🔍 搜索名称/ID..." @input="search" style="flex:1;" clearable />
        <el-input v-model="store.mccFilters.level" placeholder="等级关键词..." @input="search" style="width:150px;" clearable />
      </div>
    </div>

    <!-- 表格 + 分页 — 滚动区 -->
    <div style="flex:1;min-height:0;overflow-y:auto;">
      <el-table :data="mccTree" @selection-change="val => selected = val" stripe size="small"
        row-key="id" :tree-props="{ children: 'children', hasChildren: 'hasChildren' }" default-expand-all
        :row-class-name="mccRowClass">
        <el-table-column type="selection" width="40" />
        <el-table-column prop="name" label="MCC 名称" />
        <el-table-column prop="mcc_id" label="MCC ID" width="150" />
        <el-table-column prop="level" label="等级" width="70" />
        <el-table-column prop="direct_count" label="账户数（直属）" width="110" />
        <el-table-column label="总账户" width="70">
          <template #default="{ row }">{{ row.total_accounts != null ? row.total_accounts : '-' }}</template>
        </el-table-column>
        <el-table-column label="操作" width="160">
          <template #default="{ row }">
            <el-button link type="primary" size="small" @click="showDetail(row.id)">📋</el-button>
            <el-button link type="primary" size="small" @click="showModal(row.id)">✏️</el-button>
            <el-button link type="danger" size="small" @click="del(row.id)">🗑</el-button>
          </template>
        </el-table-column>
      </el-table>

      <div style="display:flex;align-items:center;justify-content:center;gap:8px;margin-top:12px;">
        <el-pagination v-if="store.mccTotal > store.mccPageSize" v-model:current-page="store.mccPage"
          :page-size="store.mccPageSize" :total="store.mccTotal" background
          layout="prev,pager,next" size="small" :pager-count="7" @current-change="load" />
        <el-select v-model="store.mccPageSize" @change="load" size="small" style="width:90px;">
          <el-option v-for="s in [10,20,50]" :key="s" :label="s+'条/页'" :value="s" />
        </el-select>
      </div>
    </div>

    <MccModal v-model:visible="modalVisible" :edit-id="editId" @saved="load" />
    <MccDetailModal v-model:visible="detailVisible" :mcc-id="detailId" />
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { useAccountStore } from '@/stores/accounts'
import MccModal from '@/components/MccModal.vue'
import MccDetailModal from '@/components/MccDetailModal.vue'
import { ElMessageBox, ElMessage } from 'element-plus'

const store = useAccountStore()
const selected = ref([])
const modalVisible = ref(false)
const editId = ref(null)
const detailVisible = ref(false)
const detailId = ref(null)
let searchTimer = null

onMounted(async () => { await store.loadSettings(); load() })

function load() { store.loadMccList() }

// Build tree recursively with _depth for color coding
const mccTree = computed(() => {
  const list = store.mccList || []
  function buildChildren(parentId, depth) {
    return list
      .filter(m => m.parent_mcc_id === parentId)
      .map(m => ({ ...m, _depth: depth, children: buildChildren(m.id, depth + 1) }))
  }
  return list
    .filter(m => !m.parent_mcc_id)
    .map(r => ({ ...r, _depth: 0, children: buildChildren(r.id, 1) }))
})

function mccRowClass({ row }) {
  return `mcc-level-${Math.min(row._depth || 0, 4)}`
}

function search() {
  clearTimeout(searchTimer)
  searchTimer = setTimeout(() => { store.mccPage = 1; load() }, 300)
}
function showModal(id) { editId.value = id || null; modalVisible.value = true }
function showDetail(id) { detailId.value = id; detailVisible.value = true }

async function del(id) {
  await ElMessageBox.confirm('确定删除此 MCC？', '确认', { type: 'warning' })
  await store.deleteMcc(id)
}

async function batchDelete() {
  if (!selected.value.length) return
  await ElMessageBox.confirm(`确定删除选中的 ${selected.value.length} 个 MCC？`, '确认', { type: 'warning' })
  const res = await store.batchDeleteMcc(selected.value.map(s => s.id))
  if (res.skipped?.length) {
    ElMessage.warning(`${res.skipped.length} 个被跳过：${res.skipped.map(s => s.reason).join('；')}`)
  }
}
</script>

<style scoped>
/* 层级颜色区分 — 行首彩色左边框，:deep() 穿透 el-table 内部渲染的 tr */
:deep(.mcc-level-0 td:nth-child(2)) { border-left: 3px solid #409EFF; padding-left: 8px; }
:deep(.mcc-level-1 td:nth-child(2)) { border-left: 3px solid #67C23A; padding-left: 8px; }
:deep(.mcc-level-2 td:nth-child(2)) { border-left: 3px solid #E6A23C; padding-left: 8px; }
:deep(.mcc-level-3 td:nth-child(2)) { border-left: 3px solid #F56C6C; padding-left: 8px; }
:deep(.mcc-level-4 td:nth-child(2)) { border-left: 3px solid #909399; padding-left: 8px; }
</style>
