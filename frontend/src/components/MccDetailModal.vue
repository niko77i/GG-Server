<template>
  <el-dialog :model-value="visible" @update:model-value="$emit('update:visible', $event)" title="📋 MCC 详情" width="700px" @open="load">
    <div v-if="data" style="font-size:13px;">
      <div style="display:flex;gap:8px;margin-bottom:12px;">
        <el-tag type="success">总计 {{ data.total_count }} 个账户</el-tag>
        <el-tag type="primary">直属 {{ data.direct_count }} 个</el-tag>
        <el-tag type="warning">子 MCC 来源 {{ (data.total_count||0)-(data.direct_count||0) }} 个</el-tag>
      </div>
      <h4>📌 直属账户（{{ data.direct_count }}）</h4>
      <!-- ③ 浏览类 · 前端分页。MCC 下的账户可能上万，Element Plus 的 el-table 不做虚拟
           滚动 ⇒ 直通会按行数建 DOM。后端 `/api/mcc/<id>/detail` 一次全量返回，故这里
           只把当前页交给 el-table；权威数据仍是 `data.direct_accounts`。 -->
      <el-table :data="directShown" size="small" v-if="data.direct_accounts?.length">
        <el-table-column prop="name" label="账户名称" />
        <el-table-column prop="account_id" label="账户 ID" />
        <el-table-column label="状态" width="80"><template #default="{row}"><el-tag size="small" :type="row.status==='存活'?'success':row.status==='验证'?'warning':row.status==='死亡'?'danger':'info'">{{row.status||'未知'}}</el-tag></template></el-table-column>
      </el-table>
      <el-empty v-else description="无直属账户" :image-size="40" />
      <div v-if="(data.direct_accounts?.length || 0) > PAGE_SIZE" style="display:flex;justify-content:flex-end;margin-top:6px;">
        <el-pagination v-model:current-page="directPage" :page-size="PAGE_SIZE"
          :total="data.direct_accounts.length" layout="prev, pager, next" small background />
      </div>
      <h4 style="margin-top:12px;">📦 子 MCC 贡献（{{ (data.total_count||0)-(data.direct_count||0) }}）</h4>
      <el-table :data="data.child_mccs" size="small" v-if="data.child_mccs?.length">
        <el-table-column prop="name" label="MCC 名称" /><el-table-column prop="mcc_id" label="MCC ID" /><el-table-column prop="account_count" label="贡献账户数" />
      </el-table>
      <el-empty v-else description="无子 MCC" :image-size="40" />
      <h4 v-if="data.indirect_accounts?.length" style="margin-top:12px;">🔗 间接账户（{{ data.indirect_accounts.length }}）</h4>
      <!-- 间接账户同上：走独立页码分页。 -->
      <el-table :data="indirectShown" size="small" v-if="data.indirect_accounts?.length">
        <el-table-column prop="name" label="账户名称" />
        <el-table-column prop="account_id" label="账户 ID" />
        <el-table-column label="状态" width="80"><template #default="{row}"><el-tag size="small" :type="row.status==='存活'?'success':row.status==='验证'?'warning':row.status==='死亡'?'danger':'info'">{{row.status||'未知'}}</el-tag></template></el-table-column>
      </el-table>
      <div v-if="(data.indirect_accounts?.length || 0) > PAGE_SIZE" style="display:flex;justify-content:flex-end;margin-top:6px;">
        <el-pagination v-model:current-page="indirectPage" :page-size="PAGE_SIZE"
          :total="data.indirect_accounts.length" layout="prev, pager, next" small background />
      </div>
    </div>
    <template #footer><el-button @click="$emit('update:visible',false)">关闭</el-button></template>
  </el-dialog>
</template>
<script setup>
import { ref, computed } from 'vue'; import { useAccountStore } from '@/stores/accounts'
const props = defineProps({ visible: Boolean, mccId: Number }); defineEmits(['update:visible'])
const store = useAccountStore(); const data = ref(null)
// 前端分页（③ 浏览类）：渲染行数封在 PAGE_SIZE 以内，见模板注释。
const PAGE_SIZE = 50
const directPage = ref(1)
const indirectPage = ref(1)
const directShown = computed(() => {
  const list = data.value?.direct_accounts || []
  return list.slice((directPage.value - 1) * PAGE_SIZE, directPage.value * PAGE_SIZE)
})
const indirectShown = computed(() => {
  const list = data.value?.indirect_accounts || []
  return list.slice((indirectPage.value - 1) * PAGE_SIZE, indirectPage.value * PAGE_SIZE)
})
async function load() {
  // 换 MCC ⇒ 两页都归 1，否则当前页码可能越过新结果集的末页（列表空白且分页控件消失）。
  directPage.value = 1
  indirectPage.value = 1
  if(props.mccId) { const res = await store.loadMccDetail(props.mccId); data.value = res.mcc || res }
}
</script>
