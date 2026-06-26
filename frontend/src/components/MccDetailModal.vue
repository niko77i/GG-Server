<template>
  <el-dialog :model-value="visible" @update:model-value="$emit('update:visible', $event)" title="📋 MCC 详情" width="700px" @open="load">
    <div v-if="data" style="font-size:13px;">
      <div style="display:flex;gap:8px;margin-bottom:12px;">
        <el-tag type="success">总计 {{ data.total_count }} 个账户</el-tag>
        <el-tag type="primary">直属 {{ data.direct_count }} 个</el-tag>
        <el-tag type="warning">子 MCC 来源 {{ (data.total_count||0)-(data.direct_count||0) }} 个</el-tag>
      </div>
      <h4>📌 直属账户（{{ data.direct_count }}）</h4>
      <el-table :data="data.direct_accounts" size="small" v-if="data.direct_accounts?.length">
        <el-table-column prop="name" label="账户名称" />
        <el-table-column prop="account_id" label="账户 ID" />
        <el-table-column label="状态" width="80"><template #default="{row}"><el-tag size="small" :type="row.status==='存活'?'success':row.status==='验证'?'warning':row.status==='死亡'?'danger':'info'">{{row.status||'未知'}}</el-tag></template></el-table-column>
      </el-table>
      <el-empty v-else description="无直属账户" :image-size="40" />
      <h4 style="margin-top:12px;">📦 子 MCC 贡献（{{ (data.total_count||0)-(data.direct_count||0) }}）</h4>
      <el-table :data="data.child_mccs" size="small" v-if="data.child_mccs?.length">
        <el-table-column prop="name" label="MCC 名称" /><el-table-column prop="mcc_id" label="MCC ID" /><el-table-column prop="account_count" label="贡献账户数" />
      </el-table>
      <el-empty v-else description="无子 MCC" :image-size="40" />
      <h4 v-if="data.indirect_accounts?.length" style="margin-top:12px;">🔗 间接账户（{{ data.indirect_accounts.length }}）</h4>
      <el-table :data="data.indirect_accounts" size="small" v-if="data.indirect_accounts?.length">
        <el-table-column prop="name" label="账户名称" />
        <el-table-column prop="account_id" label="账户 ID" />
        <el-table-column label="状态" width="80"><template #default="{row}"><el-tag size="small" :type="row.status==='存活'?'success':row.status==='验证'?'warning':row.status==='死亡'?'danger':'info'">{{row.status||'未知'}}</el-tag></template></el-table-column>
      </el-table>
    </div>
    <template #footer><el-button @click="$emit('update:visible',false)">关闭</el-button></template>
  </el-dialog>
</template>
<script setup>
import { ref } from 'vue'; import { useAccountStore } from '@/stores/accounts'
const props = defineProps({ visible: Boolean, mccId: Number }); defineEmits(['update:visible'])
const store = useAccountStore(); const data = ref(null)
async function load() { if(props.mccId) { const res = await store.loadMccDetail(props.mccId); data.value = res.mcc || res; } }
</script>
