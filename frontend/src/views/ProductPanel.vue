<template>
  <div style="display:flex;flex-direction:column;height:100%;">
    <!-- 工具栏 — 固定 -->
    <div style="flex-shrink:0;display:flex;gap:10px;margin-bottom:12px;flex-wrap:wrap;align-items:center;">
      <el-button type="primary" @click="showProductModal()">➕ 新增产品</el-button>
      <el-button @click="copyVisible = true">📋 复制导入</el-button>
      <el-select v-model="store.filters.region" @change="load" placeholder="全部地区" clearable style="width:120px;" filterable>
        <el-option v-for="r in regions" :key="r" :label="r" :value="r" />
      </el-select>
      <el-select v-model="store.filters.mcc_id" @change="load" placeholder="全部 MCC" clearable style="width:180px;" filterable>
        <el-option v-for="m in mccOptions" :key="m.id" :label="m.name + ' (' + m.mcc_id + ')'" :value="m.id" />
      </el-select>
      <el-input v-model="store.filters.search" placeholder="搜索产品或 KPI..." @input="search" style="flex:1;min-width:160px;" clearable />
      <el-radio-group v-model="store.pausedMode" @change="load">
        <el-radio-button :value="false">正常</el-radio-button>
        <el-radio-button :value="true">已暂停</el-radio-button>
      </el-radio-group>
    </div>

    <!-- 产品卡片列表 — 滚动区 -->
    <div style="flex:1;min-height:0;overflow-y:auto;">
      <ProductCard
        v-for="p in store.products" :key="p.id"
        :product="p"
        @edit="showProductModal($event)"
        @detail="showDetail($event)"
        @add-pkg="showAddPkg($event)"
        @del="delProduct($event)"
        @toggle-pause="togglePause($event)"
        @refresh="load"
      />

      <el-empty v-if="!store.products.length" description="暂无产品" />

      <!-- 分页 -->
      <div v-if="store.total > store.pageSize" style="display:flex;align-items:center;justify-content:center;gap:8px;margin-top:12px;">
        <el-pagination v-model:current-page="store.page" :page-size="store.pageSize" :total="store.total" background
          layout="prev,pager,next" size="small" :pager-count="7" @current-change="load" />
        <el-select v-model="store.pageSize" @change="store.page = 1; load()" size="small" style="width:90px;" filterable>
          <el-option v-for="s in [5,10,20,50]" :key="s" :label="s+'条/页'" :value="s" />
        </el-select>
      </div>
    </div>

    <!-- 弹窗 -->
    <ProductModal v-model:visible="pmVisible" :edit-id="pmEditId" :mcc-options="mccOptions" @saved="load" />
    <ProductDetailModal v-model:visible="detailVisible" :prod-id="detailId" />
    <CopyImportModal v-model:visible="copyVisible" @saved="load" />
    <AddPackageModal v-model:visible="addPkgVisible" :prod-id="addPkgProdId" @saved="load" />
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { useProductStore } from '@/stores/products'
import ProductCard from '@/components/ProductCard.vue'
import ProductModal from '@/components/ProductModal.vue'
import ProductDetailModal from '@/components/ProductDetailModal.vue'
import CopyImportModal from '@/components/CopyImportModal.vue'
import AddPackageModal from '@/components/AddPackageModal.vue'
import { ElMessageBox } from 'element-plus'

const store = useProductStore()
const regions = ref([])
const mccOptions = ref([])

const pmVisible = ref(false); const pmEditId = ref(null)
const detailVisible = ref(false); const detailId = ref(null)
const copyVisible = ref(false)
const addPkgVisible = ref(false); const addPkgProdId = ref(null)

let searchTimer = null

onMounted(() => load())

async function load() {
  const res = await store.loadProducts()
  regions.value = res.regions || []
  mccOptions.value = res.mcc_options || []
}

function search() {
  clearTimeout(searchTimer)
  searchTimer = setTimeout(() => { store.page = 1; load() }, 300)
}

function showProductModal(id) { pmEditId.value = id || null; pmVisible.value = true }
function showDetail(id) { detailId.value = id; detailVisible.value = true }
function showAddPkg(id) { addPkgProdId.value = id; addPkgVisible.value = true }

async function delProduct(id) {
  await ElMessageBox.confirm('确定删除此产品及所有包？', '确认', { type: 'warning' })
  await store.deleteProduct(id)
}

async function togglePause({ id, paused }) {
  const msg = paused ? '确定暂停此产品？' : '确定恢复此产品？'
  await ElMessageBox.confirm(msg, '确认', { type: 'warning' })
  await store.updateProduct(id, { status: paused ? 'paused' : '' })
  load()
}
</script>
