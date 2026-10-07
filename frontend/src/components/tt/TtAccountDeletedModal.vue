<template>
  <el-dialog :model-value="visible" @update:model-value="$emit('update:visible', $event)"
    title="🗑 已删除账户" width="750px">
    <div style="display:flex;gap:8px;margin-bottom:12px;align-items:center;">
      <el-input v-model="searchText" @input="onSearchInput"
        placeholder="🔍 搜索广告账户 ID / 名称 / 代理..." clearable style="flex:1;" />
      <span style="color:#888;font-size:12px;white-space:nowrap;">共 {{ total }} 条</span>
    </div>
    <el-table :data="rows" size="small" border stripe v-if="rows.length">
      <el-table-column prop="advertiser_id" label="广告账户 ID" min-width="150" show-overflow-tooltip />
      <el-table-column prop="name" label="账户名称" min-width="120">
        <template #default="{ row }">
          <span v-if="row.name">{{ row.name }}</span>
          <span v-else style="color:#ccc;">—</span>
        </template>
      </el-table-column>
      <el-table-column prop="agent" label="代理" width="90">
        <template #default="{ row }">
          <span v-if="row.agent">{{ row.agent }}</span>
          <span v-else style="color:#ccc;">—</span>
        </template>
      </el-table-column>
      <el-table-column label="状态" width="80">
        <template #default="{ row }">
          <el-tag size="small" type="info">{{ row.status || '未知' }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="deleted_at" label="删除时间" min-width="120" />
      <el-table-column label="操作" width="130">
        <template #default="{ row }">
          <el-button link type="success" size="small" @click="doRestore(row)" :loading="restoring === row.id">恢复</el-button>
          <el-button link type="danger" size="small" @click="doPermanentDelete(row)" :loading="deleting === row.id">删除</el-button>
        </template>
      </el-table-column>
    </el-table>
    <el-empty v-else :description="searchText ? '无匹配结果' : '暂无已删除账户'" :image-size="50" />

    <div v-if="total > size" style="display:flex;justify-content:flex-end;margin-top:12px;">
      <el-pagination v-model:current-page="page" :page-size="size" :total="total"
        :page-sizes="[20, 50, 100, 200]" layout="sizes, prev, pager, next"
        background small
        @current-change="onPageChange" @size-change="onSizeChange" />
    </div>

    <template #footer>
      <el-button @click="$emit('update:visible', false)">关闭</el-button>
    </template>
  </el-dialog>
</template>

<script setup>
import { ref, watch } from 'vue'
import { ttAccountsApi } from '@/api/tt'
import { ElMessage, ElMessageBox } from 'element-plus'

const props = defineProps({ visible: Boolean })
const emit = defineEmits(['update:visible', 'restored'])

const rows = ref([])
const total = ref(0)
const page = ref(1)
const size = ref(20)
const searchText = ref('')
const restoring = ref(null)
const deleting = ref(null)

let searchTimer = null

async function load() {
  try {
    const res = await ttAccountsApi.listDeleted({
      page: page.value, size: size.value, search: searchText.value,
    })
    rows.value = res.items || []
    total.value = res.total || 0
  } catch (e) {
    ElMessage.error(e.response?.data?.error || '加载失败')
  }
}

function onSearchInput() {
  // 搜索走服务端：分页后前端只有当前页，本地过滤会漏掉其余页的匹配项。
  clearTimeout(searchTimer)
  searchTimer = setTimeout(() => { page.value = 1; load() }, 300)
}

function onPageChange(p) { page.value = p; load() }
function onSizeChange(s) { size.value = s; page.value = 1; load() }

watch(() => props.visible, (v) => {
  if (v) { page.value = 1; searchText.value = ''; load() }
  else { clearTimeout(searchTimer) }
})

async function doRestore(row) {
  restoring.value = row.id
  try {
    await ttAccountsApi.restore(row.id)
    await load()
    ElMessage.success('账户已恢复')
    emit('restored')
  } catch (e) {
    ElMessage.error(e.response?.data?.error || '恢复失败')
  } finally {
    restoring.value = null
  }
}

async function doPermanentDelete(row) {
  try {
    await ElMessageBox.confirm(
      `确定永久删除账户「${row.advertiser_id}」？此操作不可恢复，充值记录也将被清除。`,
      '确认物理删除', { type: 'warning', confirmButtonText: '确定删除', cancelButtonText: '取消' }
    )
  } catch { return }

  deleting.value = row.id
  try {
    await ttAccountsApi.permanentDelete(row.id)
    await load()
    ElMessage.success('已永久删除')
  } catch (e) {
    ElMessage.error(e.response?.data?.error || '删除失败')
  } finally {
    deleting.value = null
  }
}
</script>
