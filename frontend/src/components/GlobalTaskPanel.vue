<template>
  <div v-if="store.visibleTasks.length > 0 || showPanel" class="global-task-panel">
    <!-- FAB 触发按钮 -->
    <div class="task-fab" @click="showPanel = !showPanel">
      <el-badge :value="store.runningCount" :hidden="store.runningCount === 0" :max="99">
        <span class="fab-icon">{{ store.runningCount > 0 ? '⏳' : '✅' }}</span>
      </el-badge>
    </div>

    <!-- 展开面板 -->
    <Transition name="panel-slide">
      <div v-if="showPanel" class="task-panel">
        <div class="panel-header">
          <span class="panel-title">任务进度</span>
          <el-button text size="small" @click="showPanel = false">✕</el-button>
        </div>
        <div class="panel-body">
          <!-- 空态 -->
          <div v-if="store.visibleTasks.length === 0" class="empty-state">
            没有正在运行的任务
          </div>

          <!-- 任务列表 -->
          <div
            v-for="task in store.visibleTasks"
            :key="task.id"
            class="task-item"
          >
            <div class="task-top">
              <span class="task-icon">{{ typeIcon(task.type) }}</span>
              <span class="task-label">{{ task.label }}</span>
              <span class="task-status-tag" :class="task.status">
                {{ statusText(task.status) }}
              </span>
              <el-button
                v-if="task.status !== 'running'"
                text
                size="small"
                class="task-close"
                @click="store.dismissTask(task.id)"
              >✕</el-button>
            </div>
            <el-progress
              v-if="task.status === 'running'"
              :percentage="Math.round(task.progress * 100)"
              :stroke-width="6"
              :show-text="true"
            />
            <div class="task-msg" :class="task.status">
              {{ task.message }}
            </div>
          </div>
        </div>
      </div>
    </Transition>
  </div>
</template>

<script setup>
import { ref } from 'vue'
import { useTaskStore } from '@/stores/taskRunner'

const store = useTaskStore()
const showPanel = ref(false)

function typeIcon(type) {
  switch (type) {
    case 'video': return '🎬'
    case 'delist': return '🔍'
    case 'cleanup': return '🧹'
    default: return '📋'
  }
}

function statusText(status) {
  switch (status) {
    case 'running': return '运行中'
    case 'completed': return '已完成'
    case 'error': return '失败'
    default: return status
  }
}
</script>

<style scoped>
.global-task-panel {
  position: fixed;
  bottom: 24px;
  right: 24px;
  z-index: 2000;
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  gap: 8px;
}

/* ---- FAB ---- */
.task-fab {
  width: 48px;
  height: 48px;
  border-radius: 50%;
  background: #fff;
  box-shadow: 0 2px 12px rgba(0,0,0,.15);
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  transition: box-shadow .2s, transform .15s;
  user-select: none;
}
.task-fab:hover {
  box-shadow: 0 4px 18px rgba(0,0,0,.22);
  transform: scale(1.05);
}
.task-fab:active {
  transform: scale(.95);
}
.fab-icon {
  font-size: 22px;
  line-height: 1;
}

/* ---- 面板 ---- */
.task-panel {
  width: 360px;
  max-height: 420px;
  background: #fff;
  border-radius: 12px;
  box-shadow: 0 4px 24px rgba(0,0,0,.15);
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.panel-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 16px;
  border-bottom: 1px solid #f0f0f0;
  flex-shrink: 0;
}
.panel-title {
  font-size: 14px;
  font-weight: 600;
  color: #303133;
}

.panel-body {
  flex: 1;
  overflow-y: auto;
  padding: 8px 0;
}

.empty-state {
  text-align: center;
  padding: 32px 16px;
  font-size: 13px;
  color: #909399;
}

/* ---- 任务项 ---- */
.task-item {
  padding: 10px 16px;
  border-bottom: 1px solid #f5f5f5;
}
.task-item:last-child {
  border-bottom: none;
}

.task-top {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-bottom: 6px;
}
.task-icon {
  font-size: 14px;
  flex-shrink: 0;
}
.task-label {
  flex: 1;
  font-size: 13px;
  color: #303133;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.task-status-tag {
  font-size: 11px;
  padding: 1px 6px;
  border-radius: 3px;
  flex-shrink: 0;
}
.task-status-tag.running {
  background: #e6f7ff;
  color: #1890ff;
}
.task-status-tag.completed {
  background: #f6ffed;
  color: #52c41a;
}
.task-status-tag.error {
  background: #fff2f0;
  color: #ff4d4f;
}
.task-close {
  flex-shrink: 0;
  color: #909399;
}

.task-msg {
  font-size: 12px;
  color: #909399;
  margin-top: 2px;
  word-break: break-all;
}
.task-msg.error {
  color: #ff4d4f;
}

/* ---- 过渡动画 ---- */
.panel-slide-enter-active,
.panel-slide-leave-active {
  transition: all .2s ease;
}
.panel-slide-enter-from,
.panel-slide-leave-to {
  opacity: 0;
  transform: translateY(8px);
}
</style>
