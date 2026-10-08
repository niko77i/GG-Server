<template>
  <el-dialog :model-value="visible" @update:model-value="$emit('update:visible', $event)"
    title="🗑 已删除账户" width="820px" @open="init">
    <!-- 搜索行：没有可搜内容时不显示「共 0 条」+ 空输入框（略怪）。
         但**不能只看 total** —— 搜索结果恰好 0 条时 total 也是 0，若据此隐藏，
         用户就清不掉搜索词、困死在空结果里。故「有内容(total>0) 或 正在搜索
         (searchText 非空)」才显示：后者保证结果为空时输入框仍在。 -->
    <div v-if="total > 0 || searchText" style="display:flex;gap:8px;align-items:center;margin-bottom:12px;">
      <el-input v-model="searchText" @input="onSearchInput"
        placeholder="🔍 搜索账户ID / 名称 / 所属BM..." clearable style="flex:1;" />
      <span style="color:#888;font-size:12px;white-space:nowrap;">共 {{ total }} 条</span>
    </div>
    <el-table :data="allAccounts" size="small" border stripe v-if="allAccounts.length">
      <el-table-column prop="account_id" label="账户ID" min-width="130" show-overflow-tooltip />
      <el-table-column prop="name" label="账户名称" min-width="110">
        <template #default="{ row }">
          <span v-if="row.name">{{ row.name }}</span>
          <span v-else style="color:#ccc;">—</span>
        </template>
      </el-table-column>
      <el-table-column label="所属BM" min-width="130" show-overflow-tooltip>
        <template #default="{ row }">
          <span v-if="row.bms?.length">{{ row.bms.map(b => b.name).join(', ') }}</span>
          <span v-else style="color:#ccc;">—</span>
        </template>
      </el-table-column>
      <el-table-column prop="timezone" label="时区" width="90" />
      <el-table-column label="状态" width="80">
        <template #default="{ row }">
          <el-tag size="small" type="info">{{ optName(row.status_id) || '未知' }}</el-tag>
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
        layout="prev,pager,next" @current-change="load" />
    </div>

    <template #footer>
      <el-button @click="$emit('update:visible', false)">关闭</el-button>
    </template>
  </el-dialog>
</template>

<script setup>
import { ref } from 'vue'
import { fbApi } from '@/api/fb'
import client from '@/api/client'
import { ElMessage, ElMessageBox } from 'element-plus'

const props = defineProps({ visible: Boolean })
const emit = defineEmits(['update:visible', 'changed'])

const allAccounts = ref([])
const searchText = ref('')
const restoring = ref(null)
const deleting = ref(null)
// 与 GG/TT 版的关键差异：FB 的 `GET /api/fb/accounts/deleted` 是**分页端点**
// （`page`/`size` 默认 50，返回 `total`）；GG/TT 的 deleted 端点一次全量返回，
// 故那两个弹窗没有分页。这里补一个分页控件，否则第 50 条之后的已删除账户永远看不见。
const page = ref(1)
const size = ref(50)
const total = ref(0)
// 状态列：FB 的 deleted 端点只回 `a.*` 原始行（`status_id` 是数值），不像 TT 那样
// JOIN 出 `status_name`。沿用本页 `FbAccountPanel.vue` 既有的 id → 名映射口径
// （读 `/statuses/list` 到本地再查表），避免为此改后端查询。
const statusOptions = ref([])

let searchTimer = null

// 请求序号：搜索有 300ms 防抖，但防抖只减少请求数、**不保证返回顺序**。
// 快速输入时先发的请求可能后返回，把新结果覆盖成旧的（列表与输入框不符）。
// 每次 load 自增并记住自己的序号，只有序号仍是最新的才落地结果 —— 过期响应丢弃。
let searchSeq = 0

function optName(id) {
  if (id === null || id === undefined || id === '') return ''
  const o = statusOptions.value.find(x => x.id === id)
  return o ? o.name : ''
}

async function loadStatusOptions() {
  try {
    const r = await client.get('/statuses/list')
    statusOptions.value = r.statuses || r.data || []
  } catch (e) { console.warn('loadStatusOptions', e) }
}

async function load() {
  const seq = ++searchSeq
  try {
    const res = await fbApi.listDeleted({
      page: page.value, size: size.value, search: searchText.value,
    })
    // 已有更新的请求在飞 ⇒ 丢弃本次结果，避免旧响应覆盖新列表
    if (seq !== searchSeq) return
    allAccounts.value = res.items || []
    total.value = res.total || 0
  } catch (e) {
    if (seq !== searchSeq) return
    ElMessage.error(e.response?.data?.error || '加载失败')
  }
}

// 搜索走服务端：分页后前端只有当前页，本地过滤会漏掉其余页的匹配项。
// 必须重置到第 1 页 —— 否则搜完停在第 5 页可能落在空页、看不到结果。
function onSearchInput() {
  clearTimeout(searchTimer)
  searchTimer = setTimeout(() => { page.value = 1; load() }, 300)
}

// 每次打开重置到第 1 页、清空搜索并重取状态表（状态表可能在别处被改过）
function init() {
  clearTimeout(searchTimer)
  page.value = 1
  searchText.value = ''
  loadStatusOptions()
  load()
}

// 删/恢复后：先通知父组件刷新在用的账户列表（父组件的加载函数是 `loadData`，
// 挂载侧写 `@changed="loadData"`）；随后本页局部移除即可（照 GG 样板）。
// 例外：当前页被删空且不在第一页时，回退一页重取，避免停在空白页。
async function afterRowRemoved() {
  emit('changed')
  // 本页是局部移除（不重取），total 是服务端真值快照，得同步减一，
  // 否则「共 N 条」与表里实际行数对不上。回退页时 load() 会刷成新值。
  total.value = Math.max(0, total.value - 1)
  if (!allAccounts.value.length && page.value > 1) {
    page.value -= 1
    await load()
  }
}

async function doRestore(row) {
  restoring.value = row.id
  try {
    await fbApi.restoreAccount(row.id)
    allAccounts.value = allAccounts.value.filter(a => a.id !== row.id)
    ElMessage.success('账户已恢复')
    await afterRowRemoved()
  } catch (e) {
    ElMessage.error(e.response?.data?.error || '恢复失败')
  } finally {
    restoring.value = null
  }
}

async function doPermanentDelete(row) {
  try {
    await ElMessageBox.confirm(
      `确定永久删除账户「${row.account_id}」？此操作不可恢复，关联 BM 关系也将被清除。`,
      '确认物理删除', { type: 'warning', confirmButtonText: '确定删除', cancelButtonText: '取消' }
    )
  } catch { return }

  deleting.value = row.id
  try {
    await fbApi.permanentDeleteAccount(row.id)
    allAccounts.value = allAccounts.value.filter(a => a.id !== row.id)
    ElMessage.success('已永久删除')
    await afterRowRemoved()
  } catch (e) {
    ElMessage.error(e.response?.data?.error || '删除失败')
  } finally {
    deleting.value = null
  }
}
</script>
