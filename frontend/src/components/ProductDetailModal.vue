<template>
  <el-dialog :model-value="visible" @update:model-value="$emit('update:visible', $event)"
    title="📋 产品详情" width="750px" @open="load">
    <div v-if="product" style="font-size:13px;">
      <div style="margin-bottom:12px;">
        <strong>{{ product.product_name }}</strong> &nbsp;
        KPI: {{ product.kpi || '-' }} &nbsp; 地区: {{ product.region || '-' }} &nbsp;
        客户: {{ product.customer || '-' }} &nbsp;
        MCC: {{ product.mcc_name ? product.mcc_name + ' (' + product.mcc_code + ')' : '未分配' }}
      </div>

      <!-- 关联账户状态统计 -->
      <div v-if="product.related_account_count" style="display:flex;gap:8px;margin-bottom:12px;flex-wrap:wrap;">
        <el-tag v-for="(cnt, status) in product.status_count" :key="status" :type="status === '存活' ? 'success' : status === '验证' ? 'warning' : status === '死亡' ? 'danger' : 'info'">
          {{ status }} {{ cnt }}
        </el-tag>
      </div>

      <h4>📌 关联账户（{{ product.related_account_count || 0 }} 个）</h4>
      <el-table :data="sortedAccounts" size="small" v-if="sortedAccounts.length">
        <el-table-column prop="name" label="账户名称" />
        <el-table-column prop="account_id" label="账户 ID" />
        <el-table-column prop="status" label="状态">
          <template #default="{ row }">
            <el-tag size="small" :type="row.status === '存活' ? 'success' : row.status === '验证' ? 'warning' : row.status === '死亡' ? 'danger' : 'info'">{{ row.status }}</el-tag>
          </template>
        </el-table-column>
      </el-table>
      <el-empty v-else description="未关联 MCC 或 MCC 下无账户" :image-size="40" />

      <h4 style="margin-top:12px;">📦 包列表（{{ (product.packages || []).length }} 个）</h4>
      <el-table :data="product.packages" size="small" max-height="200">
        <el-table-column prop="series_name" label="系列名" />
        <el-table-column prop="package_name" label="包名" />
        <el-table-column label="状态">
          <template #default="{ row }">
            {{ row.status === 'paused' ? '暂停' : row.status === 'dropped' ? '掉包' : row.status === 'rejected' ? '拒登' : '正常' }}
          </template>
        </el-table-column>
      </el-table>

      <el-divider />
      <h4>🏃 在跑成员</h4>
      <div style="display:flex;gap:6px;flex-wrap:wrap;margin-bottom:10px;">
        <el-tag
          v-for="rid in runnerIds"
          :key="rid"
          closable
          @close="removeRunner(rid)"
          size="small"
        >
          {{ getUserName(rid) }}
        </el-tag>
        <span v-if="!runnerIds.length" style="color:#999;font-size:12px;">暂无 runner</span>
      </div>
      <el-select
        v-model="newRunnerId"
        placeholder="添加 runner..."
        size="small"
        style="width:200px;"
        filterable
        @change="addRunner"
      >
        <el-option
          v-for="u in availableUsers"
          :key="u.id"
          :label="u.display_name || u.username"
          :value="u.id"
          :disabled="runnerIds.includes(u.id)"
        />
      </el-select>

      <!-- 成效素材 -->
      <el-divider />
      <h4>🎬 成效素材</h4>
      <div v-if="assetGroups.length">
        <div v-for="group in assetGroups" :key="group.userId" style="margin-bottom:8px;">
          <div style="font-size:12px;color:#666;margin-bottom:4px;display:flex;align-items:center;gap:6px;">
            📌 {{ group.userName }} ({{ group.items.length }}个)
            <el-button link size="small" type="primary" @click="copyUserAssets(group)">
              📋 复制
            </el-button>
          </div>
          <div style="display:flex;gap:6px;flex-wrap:wrap;">
            <el-tag
              v-for="a in group.items"
              :key="a.id"
              closable
              @close="confirmRemoveAsset(a)"
              @click="playVideo(a)"
              size="small"
              type="warning"
              effect="plain"
              style="cursor:pointer;"
            >
              {{ a.title || a.id }}
            </el-tag>
          </div>
        </div>
      </div>
      <div v-if="!assetGroups.length" style="color:#999;font-size:12px;margin-bottom:8px;">
        暂无成效素材
      </div>
      <div style="display:flex;gap:6px;">
        <el-input
          v-model="assetUrlInput"
          type="textarea"
          :rows="2"
          placeholder="粘贴 YouTube 链接，每行一个，回车或点添加..."
          size="small"
          style="flex:1;"
        />
        <el-button size="small" type="primary" @click="addAsset" :loading="addingAsset" style="align-self:flex-end;">添加</el-button>
      </div>
    </div>
    <template #footer>
      <el-button @click="$emit('update:visible', false)">关闭</el-button>
    </template>
  </el-dialog>

  <!-- 视频播放弹窗 -->
  <el-dialog
    :model-value="!!playingVideo"
    @update:model-value="playingVideo = null"
    :title="playingVideo?.title || '视频播放'"
    width="720px"
    destroy-on-close
  >
    <div v-if="playingVideo" style="position:relative;padding-top:56.25%;">
      <iframe
        :src="'https://www.youtube.com/embed/' + playingVideo.id + '?autoplay=1'"
        style="position:absolute;top:0;left:0;width:100%;height:100%;border:0;border-radius:8px;"
        allow="autoplay; encrypted-media"
        allowfullscreen
      />
    </div>
    <template #footer>
      <el-button @click="playingVideo = null">关闭</el-button>
      <el-button type="primary" @click="copy(playingVideo?.id)">📋 复制链接</el-button>
    </template>
  </el-dialog>
</template>

<script setup>
import { ref, computed } from 'vue'
import { useProductStore } from '@/stores/products'
import { productsApi } from '@/api/products'
import api from '@/api/client'
import { ElMessage, ElMessageBox } from 'element-plus'
import { copyToClipboard } from '@/utils/clipboard'

const props = defineProps({ visible: Boolean, prodId: Number })
const emit = defineEmits(['update:visible', 'saved'])
const store = useProductStore()
const product = ref(null)
const availableUsers = ref([])
const newRunnerId = ref(null)

// 成效素材
const assets = ref([])
const assetUrlInput = ref('')
const addingAsset = ref(false)
const playingVideo = ref(null)

function playVideo(asset) {
  playingVideo.value = { id: asset.id, title: asset.title || asset.id }
}

function copy(id) {
  if (!id) return
  const url = `https://www.youtube.com/watch?v=${id}`
  copyToClipboard(url).then(() => ElMessage.success('已复制链接 ✓'))
}

// 按状态排序的关联账户：存活 > 验证 > 死亡 > 其他
const statusOrder = { '存活': 0, '验证': 1, '死亡': 2 }
const sortedAccounts = computed(() => {
  const accounts = product.value?.related_accounts
  if (!accounts?.length) return []
  return [...accounts].sort((a, b) => {
    const orderA = statusOrder[a.status] ?? 3
    const orderB = statusOrder[b.status] ?? 3
    return orderA - orderB
  })
})

const assetGroups = computed(() => {
  const map = {}
  for (const a of assets.value) {
    const uid = a.added_by || 0
    if (!map[uid]) map[uid] = { userId: uid, userName: a.added_by_name || `User #${uid}`, items: [] }
    map[uid].items.push(a)
  }
  return Object.values(map)
})

const runnerIds = computed(() => {
  if (!product.value) return []
  const ids = product.value.runner_ids
  if (!ids) return []
  if (Array.isArray(ids)) return ids
  try { const parsed = JSON.parse(ids); return Array.isArray(parsed) ? parsed : [] }
  catch { return [] }
})

async function load() {
  if (props.prodId) {
    const res = await store.loadProductDetail(props.prodId)
    product.value = res.product
    await loadUsers()
    await loadAssets()
  }
}

async function loadUsers() {
  try {
    const res = await api.get('/users/names')
    availableUsers.value = res.users || []
  } catch { availableUsers.value = [] }
}

async function loadAssets() {
  if (!product.value) return
  try {
    const res = await api.get(`/products/${product.value.id}/assets`)
    assets.value = res.assets || []
  } catch { assets.value = [] }
}

async function addAsset() {
  const text = assetUrlInput.value.trim()
  if (!text || !product.value) return
  // 支持多行，每行一个链接
  const urls = text.split(/[\n\r]+/).map(l => l.trim()).filter(Boolean)
  if (!urls.length) return
  addingAsset.value = true
  try {
    const res = await api.post(`/products/${product.value.id}/assets`, {
      urls,
      region: product.value.region || '通用',
      product_name: product.value.product_name || '',
    })
    if (res.imported > 0) ElMessage.success(`已添加 ${res.imported} 个成效素材`)
    if (res.duplicates?.length) ElMessage.warning(`${res.duplicates.length} 个已存在，已跳过`)
    assetUrlInput.value = ''
    await loadAssets()
  } catch (e) { ElMessage.error('添加失败: ' + (e.message || '')) }
  addingAsset.value = false
}

async function copyUserAssets(group) {
  const links = group.items.map(a => `https://www.youtube.com/watch?v=${a.id}`).join('\n')
  await copyToClipboard(links)
  ElMessage.success(`已复制 ${group.userName} 的 ${group.items.length} 个成效素材链接`)
}

async function confirmRemoveAsset(asset) {
  if (!product.value) return
  try {
    await ElMessageBox.confirm(
      `确定要删除成效素材「${asset.title || asset.id}」吗？`,
      '确认删除',
      { type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消' }
    )
  } catch { return }
  try {
    await api.delete(`/products/${product.value.id}/assets/${asset.id}`)
    assets.value = assets.value.filter(a => a.id !== asset.id)
    ElMessage.success('已移除')
  } catch { ElMessage.error('移除失败') }
}

function getUserName(rid) {
  const u = availableUsers.value.find(u => u.id === rid)
  return u ? (u.display_name || u.username) : `User #${rid}`
}

async function addRunner(newId) {
  if (!newId || !product.value) return
  const ids = [...runnerIds.value, newId]
  try {
    await productsApi.updateRunners(product.value.id, { runner_ids: ids })
    product.value.runner_ids = JSON.stringify(ids)
    emit('saved')
    ElMessage.success('Runner 已添加')
  } catch { ElMessage.error('添加失败') }
  newRunnerId.value = null
}

async function removeRunner(rid) {
  if (!product.value) return
  const ids = runnerIds.value.filter(id => id !== rid)
  try {
    await productsApi.updateRunners(product.value.id, { runner_ids: ids })
    product.value.runner_ids = JSON.stringify(ids)
    emit('saved')
    ElMessage.success('Runner 已移除')
  } catch { ElMessage.error('移除失败') }
}
</script>
