<template>
  <div class="owner-cell">
    <!-- ① 加载中：不用裸 el-select，否则会退化成显示裸 owner_id 数字（§5.4） -->
    <el-skeleton v-if="!loaded" :rows="1" animated />
    <!-- ⑤ 失败态：列表没回来，写操作不能静默（§5.6） -->
    <el-select v-else-if="failed" :model-value="null" size="small" disabled
      style="width:100%;" placeholder="暂时无法加载用户列表"
      :aria-label="`账户 ${row[accountKey]} 的户归属`" />
    <!-- ③ 未知归属：不在列表里（账号可能已停用），禁用并说明，不让户管以为能保持现状（§5.4） -->
    <el-tooltip v-else-if="row.owner_id && !optionMap[row.owner_id]"
      content="这个归属人不在用户列表里（账号可能已停用）。请重新选择。">
      <el-select :model-value="row.owner_id" size="small" filterable disabled
        style="width:100%;" placeholder="未知用户"
        :aria-label="`账户 ${row[accountKey]} 的户归属`">
        <el-option :key="row.owner_id" :label="`用户 #${row.owner_id}`" :value="row.owner_id" />
      </el-select>
    </el-tooltip>
    <!-- ④ 未分配 -->
    <el-tooltip v-else-if="!row.owner_id"
      content="这个账户还没有归属人，普通用户看不到它，只有户管和管理员可见。">
      <el-select :model-value="row.owner_id" size="small" filterable
        placeholder="未分配" style="width:100%;"
        :disabled="pending.has(row.id)"
        :aria-label="`账户 ${row[accountKey]} 的户归属`"
        @change="(v) => $emit('change', v)">
        <el-option v-for="u in options" :key="u.id"
          :label="u.display_name || u.username" :value="u.id" />
        <template #empty>
          <div style="padding:8px 12px;font-size:12px;color:#6b7280;line-height:1.6;">
            没有匹配的用户。<br />停用的账号不会出现在这里。
          </div>
        </template>
      </el-select>
    </el-tooltip>
    <!-- ② 正常 -->
    <el-select v-else :model-value="row.owner_id" size="small" filterable
      placeholder="未分配" style="width:100%;"
      :disabled="pending.has(row.id)"
      :aria-label="`账户 ${row[accountKey]} 的户归属`"
      @change="(v) => $emit('change', v)">
      <el-option v-for="u in options" :key="u.id"
        :label="u.display_name || u.username" :value="u.id" />
      <template #empty>
        <div style="padding:8px 12px;font-size:12px;color:#6b7280;line-height:1.6;">
          没有匹配的用户。<br />停用的账号不会出现在这里。
        </div>
      </template>
    </el-select>
  </div>
</template>

<script setup>
// 「户归属」列单元格。GG 与 TT 原本各有一份逐字复制的 markup（注释自述
// 「GG 与 TT 逐字同构，只差 reassign 实现」）——逻辑早已抽到 useOwnerPicker，
// 只剩 markup 是两份。这里合并。
//
// 唯一差异：aria-label 里用的账户标识字段，GG 是 account_id、TT 是 advertiser_id，
// 故做成 accountKey prop。**漏掉这一项会让 TT 的无障碍标签变成 undefined**，
// 是本次抽取最容易出错的地方。
defineProps({
  row: { type: Object, required: true },
  accountKey: { type: String, required: true },
  loaded: { type: Boolean, default: false },
  failed: { type: Boolean, default: false },
  options: { type: Array, default: () => [] },
  optionMap: { type: Object, default: () => ({}) },
  pending: { type: Set, default: () => new Set() },
})
defineEmits(['change'])
</script>

<style scoped>
/* 「户归属」列：静息态看去边框（看起来是一段人名文本），悬浮/聚焦时恢复成控件（§5.2）。
   padding-left 的变化是为了让文本在两种状态下不左右跳动（EP 的 wrapper 默认有内边距）。
   原样从 AdsAccountPanel.vue / tt/TtAccountPanel.vue 各一份的 scoped 样式迁入。 */
.owner-cell :deep(.el-select__wrapper) {
  box-shadow: none;
  background: transparent;
  padding-left: 0;
}
.owner-cell:hover :deep(.el-select__wrapper),
.owner-cell :deep(.el-select__wrapper.is-focused) {
  box-shadow: 0 0 0 1px var(--el-border-color) inset;
  background: var(--el-fill-color-blank);
  padding-left: 11px;
}
</style>
