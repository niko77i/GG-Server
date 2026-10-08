<template>
  <template v-if="failure">
    <el-tooltip placement="top" :content="hint(failure)">
      <el-button link size="small" :type="tone(failure.status)"
        @click.stop="$emit('retry')">{{ mark(failure.status) }}</el-button>
    </el-tooltip>
  </template>
  <span v-else style="color:#16a34a;font-size:14px;">✅</span>
</template>

<script setup>
// 「写表」列单元格。GG 与 TT 原本各有一份逐字复制的 markup（注释自述
// 「语汇 / 位置 / 宽度逐字沿用」），这里合并为一份，改一处两平台同时生效。
//
// 只收 failure 一个 prop：单元格只按失败状态决定渲染，行数据一概不需要
// （失败信息由调用方按 row 取出后传进来）。不预留没人用的 row prop。
import { sheetWriteMark as mark, sheetWriteTone as tone, sheetWriteHint as hint } from '@/utils/sheetWriteUi'

defineProps({
  failure: { type: Object, default: null },
})
defineEmits(['retry'])
</script>
