<template>
  <el-popover placement="bottom-start" :width="260" trigger="click">
    <template #reference>
      <el-button>📊 列显示</el-button>
    </template>

    <div class="column-settings">
      <p class="column-settings__hint">拖动调整顺序，取消勾选即隐藏</p>

      <ul class="column-settings__list">
        <li
          v-for="(col, i) in list" :key="col.key"
          class="column-settings__item"
          :class="{
            'is-dragging': dragIndex === i,
            'is-over': dragIndex > -1 && overIndex === i && dragIndex !== i,
            'is-hidden': col.hidden,
          }"
          draggable="true"
          @dragstart="onDragStart(i, $event)"
          @dragover.prevent="onDragOver(i)"
          @drop.prevent="onDrop(i)"
          @dragend="onDragEnd"
        >
          <span class="column-settings__handle" aria-hidden="true"></span>

          <el-checkbox
            class="column-settings__check"
            :model-value="!col.hidden"
            :disabled="isLockedKey(col.key)"
            @change="(v) => onToggle(col.key, v)"
          >{{ col.label }}</el-checkbox>

          <span class="column-settings__arrows">
            <el-button
              link size="small" :disabled="i === 0"
              aria-label="上移" title="上移" @click="onMoveUp(i)"
            >↑</el-button>
            <el-button
              link size="small" :disabled="i === list.length - 1"
              aria-label="下移" title="下移" @click="onMoveDown(i)"
            >↓</el-button>
          </span>
        </li>
      </ul>

      <p v-if="hasLocked" class="column-settings__lock-hint">至少保留一列，该项无法取消</p>

      <div class="column-settings__footer">
        <el-button link size="small" @click="onReset">恢复默认</el-button>
      </div>
    </div>
  </el-popover>
</template>

<script setup>
import { computed, ref } from 'vue'
import { ElMessage } from 'element-plus'

import { useColumnPrefsStore } from '@/stores/columnPrefs'

const props = defineProps({
  panelKey: { type: String, required: true },
  registry: { type: Array, required: true },
})

const store = useColumnPrefsStore()

// 列表顺序 = 表格显示顺序（含隐藏列，隐藏项留在原位）。
// 下面的拖拽下标一律取自这个数组，与 store.move 期望的「完整顺序表下标」一致。
const list = computed(() => store.settingsList(props.panelKey, props.registry))

// 只剩一列可见时不许再取消，否则表格只剩选择框和「操作」列，用户会以为坏了。
// 隐藏项不会被 onlyVisible 命中（它不在可见列表里），所以不会被误禁用。
function isLockedKey(key) {
  return store.onlyVisible(props.panelKey, props.registry, key)
}

const hasLocked = computed(() => list.value.filter((c) => !c.hidden).length === 1)

function onToggle(key, checked) {
  store.toggle(props.panelKey, props.registry, key, checked)
}

function onReset() {
  store.reset(props.panelKey, props.registry)
  ElMessage.success('已恢复默认列')
}

// --- 键盘 / 触屏的调序替代：拖拽是纯鼠标手势，这两颗箭头补上等价路径 ---
function move(from, to) {
  if (from === to || to < 0 || to >= list.value.length) return
  store.move(props.panelKey, props.registry, from, to)
}
function onMoveUp(i) { move(i, i - 1) }
function onMoveDown(i) { move(i, i + 1) }

// --- 原生 HTML5 拖拽（不引入 sortablejs） ---
const dragIndex = ref(-1)
const overIndex = ref(-1)

function onDragStart(i, e) {
  dragIndex.value = i
  // Firefox 不显式 setData 就不会启动拖拽；effectAllowed 让光标显示为「移动」。
  if (e?.dataTransfer) {
    e.dataTransfer.effectAllowed = 'move'
    e.dataTransfer.setData('text/plain', String(i))
  }
}

function onDragOver(i) {
  overIndex.value = i
}

function onDrop(i) {
  const from = dragIndex.value
  if (from > -1 && from !== i) {
    // 指示条恒画在「第 i 行上方」。向上拖（from > i）时 i 之前的元素没位移，
    // 落点就是 i；向下拖（from < i）时移除操作让目标行前移一格，故落点是 i - 1。
    // 不区分方向的话，向下拖的实际落点会比指示条低一行。
    store.move(props.panelKey, props.registry, from, from < i ? i - 1 : i)
  }
  onDragEnd()
}

function onDragEnd() {
  dragIndex.value = -1
  overIndex.value = -1
}
</script>

<style scoped>
.column-settings {
  font-size: 14px;
  color: #303133;
}

.column-settings__hint {
  margin: 0 0 6px;
  font-size: 12px;
  line-height: 1.4;
  color: #909399;
}

.column-settings__list {
  margin: 0;
  padding: 0;
  list-style: none;
  max-height: 320px;
  overflow-y: auto;
}

/* 每行预留 2px 的插入条位置，落点出现时行高不跳动 */
.column-settings__item {
  display: flex;
  align-items: center;
  gap: 8px;
  height: 32px;
  padding: 0 4px;
  border-top: 2px solid transparent;
  border-radius: 4px;
  cursor: grab;
}

.column-settings__item:hover {
  background: #f5f7fa;
}

/* 落点：顶边亮起一条主色插入条，语义 = 「松手后落到这一格」 */
.column-settings__item.is-over {
  border-top-color: #409eff;
}

/* 被拖项：压暗留在原位，不做浮层，避免与 el-popover 的层级打架 */
.column-settings__item.is-dragging {
  opacity: 0.4;
  background: #f5f7fa;
  cursor: grabbing;
}

/* 6 点抓手，比文字字形更明确地表示「可拖」 */
.column-settings__handle {
  flex: 0 0 auto;
  width: 10px;
  height: 18px;
  background-image: radial-gradient(circle, #c0c4cc 1.1px, transparent 1.4px);
  background-size: 5px 6px;
  background-position: 1px 1px;
}

.column-settings__item:hover .column-settings__handle {
  background-image: radial-gradient(circle, #909399 1.1px, transparent 1.4px);
}

.column-settings__check {
  flex: 1 1 auto;
  min-width: 0;
  margin-right: 0;
}

.column-settings__check :deep(.el-checkbox__label) {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

/* 已隐藏的列：文字压暗，方便一屏扫出「哪些是关掉的」 */
.column-settings__item.is-hidden .column-settings__check :deep(.el-checkbox__label) {
  color: #909399;
}

/* 调序箭头：默认隐形保持列表安静，悬停或键盘聚焦时淡入（opacity 不挡 Tab 焦点） */
.column-settings__arrows {
  flex: 0 0 auto;
  display: inline-flex;
  gap: 2px;
  opacity: 0;
  transition: opacity 0.15s;
}

.column-settings__item:hover .column-settings__arrows,
.column-settings__item:focus-within .column-settings__arrows {
  opacity: 1;
}

.column-settings__arrows :deep(.el-button) {
  height: 22px;
  padding: 0 4px;
}

.column-settings__lock-hint {
  margin: 6px 0 0;
  font-size: 12px;
  line-height: 1.4;
  color: #e6a23c;
}

.column-settings__footer {
  margin-top: 8px;
  padding-top: 8px;
  border-top: 1px solid #ebeef5;
}
</style>
