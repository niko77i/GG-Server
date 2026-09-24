<template>
  <div class="scheduler-page">
    <div style="display:flex;align-items:center;margin-bottom:16px;">
      <h3 style="margin:0;font-size:18px;font-weight:600;color:#111827;">⏰ 定时任务管理</h3>
      <span style="font-size:13px;color:#9ca3af;margin-left:12px;">手动触发后端定时任务（仅开发者可见）</span>
    </div>

    <div class="task-cards">
      <!-- 掉包检测 -->
      <el-card shadow="never" class="task-card" :class="{ running: delistRunning }">
        <div class="task-header">
          <div class="task-icon">🔍</div>
          <div class="task-info">
            <div class="task-name">掉包检测</div>
            <div class="task-desc">检测所有正常产品的 Google Play 链接是否掉包，并发送邮件通知在跑人员</div>
            <div class="task-meta">
              <el-tag size="small" type="info">自动频率：每小时</el-tag>
              <el-tag size="small" type="warning">启动时立即执行一次</el-tag>
            </div>
          </div>
          <div class="task-action">
            <el-button type="primary" :loading="delistRunning" :disabled="delistRunning" @click="triggerDelist">
              {{ delistRunning ? '检测中...' : '立即执行' }}
            </el-button>
          </div>
        </div>
        <div v-if="delistResult !== null" class="task-result" :class="delistResult.success ? 'success' : 'error'">
          <template v-if="delistResult.success">
            ✅ 检测完成：共 <strong>{{ delistResult.total }}</strong> 个包，
            发现 <strong :style="{ color: delistResult.delisted > 0 ? '#ef4444' : (unknownCount(delistResult) > 0 ? '#f59e0b' : '#10b981') }">{{ delistResult.delisted }}</strong> 个掉包
            <span v-if="unknownCount(delistResult) > 0" style="color:#f59e0b;">
              ，{{ unknownCount(delistResult) }} 个未判定（已保留上次判定结果）
            </span>
            <div v-if="delistResult.delisted > 0" style="margin-top:8px;">
              <div v-for="r in delistResult.results.filter(x => x.is_delisted)" :key="r.package_id" class="delisted-item">
                ⚠️ {{ r.package_name }} (产品 #{{ r.product_id }})
              </div>
            </div>
          </template>
          <template v-else>
            ❌ 检测失败：{{ delistResult.error }}
          </template>
        </div>
      </el-card>

      <!-- TT 掉包检测 -->
      <el-card shadow="never" class="task-card" :class="{ running: ttDelistRunning }">
        <div class="task-header">
          <div class="task-icon">🔍</div>
          <div class="task-info">
            <div class="task-name">TT 掉包检测</div>
            <div class="task-desc">检测所有正常 TT 产品的跑包链接是否掉包，并通过 TT 机器人（Telegram）通知在跑人员</div>
            <div class="task-meta">
              <el-tag size="small" type="info">自动频率：每小时</el-tag>
              <el-tag size="small" type="success">独立机器人：TT-Server</el-tag>
            </div>
          </div>
          <div class="task-action">
            <el-button type="primary" :loading="ttDelistRunning" :disabled="ttDelistRunning" @click="triggerTtDelist">
              {{ ttDelistRunning ? '检测中...' : '立即执行' }}
            </el-button>
          </div>
        </div>
        <div v-if="ttDelistResult !== null" class="task-result" :class="ttDelistResult.success ? 'success' : 'error'">
          <template v-if="ttDelistResult.success">
            ✅ 检测完成：共 <strong>{{ ttDelistResult.total }}</strong> 个包，
            发现 <strong :style="{ color: ttDelistResult.delisted > 0 ? '#ef4444' : (unknownCount(ttDelistResult) > 0 ? '#f59e0b' : '#10b981') }">{{ ttDelistResult.delisted }}</strong> 个掉包
            <span v-if="unknownCount(ttDelistResult) > 0" style="color:#f59e0b;">
              ，{{ unknownCount(ttDelistResult) }} 个未判定（已保留上次判定结果）
            </span>
            <div v-if="ttDelistResult.delisted > 0" style="margin-top:8px;">
              <div v-for="r in ttDelistResult.results.filter(x => x.is_delisted)" :key="r.package_id" class="delisted-item">
                ⚠️ {{ r.package_name }} (产品 #{{ r.product_id }})
              </div>
            </div>
          </template>
          <template v-else>
            ❌ 检测失败：{{ ttDelistResult.error }}
          </template>
        </div>
      </el-card>

      <!-- 每周清理 -->
      <el-card shadow="never" class="task-card" :class="{ running: cleanupRunning }">
        <div class="task-header">
          <div class="task-icon">🧹</div>
          <div class="task-info">
            <div class="task-name">每周清理</div>
            <div class="task-desc">清理 scraped_images 目录下的爬取图片和生成视频文件（音乐库 ai 子目录保留）</div>
            <div class="task-meta">
              <el-tag size="small" type="info">自动频率：每周日 00:00</el-tag>
            </div>
          </div>
          <div class="task-action">
            <el-button type="primary" :loading="cleanupRunning" :disabled="cleanupRunning" @click="triggerCleanup">
              {{ cleanupRunning ? '清理中...' : '立即执行' }}
            </el-button>
          </div>
        </div>
        <div v-if="cleanupResult !== null" class="task-result" :class="cleanupResult.success ? 'success' : 'error'">
          <template v-if="cleanupResult.success">
            ✅ {{ cleanupResult.message || '清理完成' }}
          </template>
          <template v-else>
            ❌ 清理失败：{{ cleanupResult.error }}
          </template>
        </div>
      </el-card>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { adminApi } from '../api/admin'
import { useTaskStore } from '@/stores/taskRunner'
import { ElMessage } from 'element-plus'

const taskStore = useTaskStore()

// 未知 = is_delisted 为 null（限流/服务端异常/空 url 等），既不是掉包也不是正常
function unknownCount(res) {
  return (res?.results || []).filter(r => r.is_delisted == null).length
}

// 恢复上次执行结果（切换页面后回来）
onMounted(() => {
  for (const t of taskStore.visibleTasks) {
    if (t.type === 'delist' && t.status === 'completed' && t.result) {
      delistResult.value = { success: true, ...t.result }
    }
    if (t.type === 'tt-delist' && t.status === 'completed' && t.result) {
      ttDelistResult.value = { success: true, ...t.result }
    }
    if (t.type === 'cleanup' && t.status === 'completed' && t.result) {
      cleanupResult.value = { success: true, ...t.result }
    }
  }
})

// 掉包检测
const delistRunning = ref(false)
const delistResult = ref(null)

async function triggerDelist() {
  delistRunning.value = true
  delistResult.value = null
  const innerId = taskStore.addTask('delist', '掉包检测', null)
  try {
    const res = await adminApi.triggerDelistCheck()
    const unk = unknownCount(res)
    taskStore.updateTask(innerId, {
      status: 'completed', progress: 1,
      message: `共${res.total}包，${res.delisted}掉包` + (unk ? `，${unk}未判定` : ''),
      result: res,
      finishedAt: Date.now(),
    })
    delistResult.value = { success: true, ...res }
    const summary = `掉包检测完成：${res.total} 个包，${res.delisted} 个掉包` + (unk ? `，${unk} 个未判定` : '')
    if (unk) ElMessage.warning(summary)
    else ElMessage.success(summary)
    window.dispatchEvent(new CustomEvent('delist-check-completed'))
  } catch (e) {
    const msg = e?.response?.data?.error || e.message || '未知错误'
    taskStore.updateTask(innerId, {
      status: 'error', message: msg, finishedAt: Date.now(),
    })
    delistResult.value = { success: false, error: msg }
    ElMessage.error('掉包检测失败：' + msg)
  } finally {
    delistRunning.value = false
  }
}

// TT 掉包检测
const ttDelistRunning = ref(false)
const ttDelistResult = ref(null)

async function triggerTtDelist() {
  ttDelistRunning.value = true
  ttDelistResult.value = null
  const innerId = taskStore.addTask('tt-delist', 'TT 掉包检测', null)
  try {
    const res = await adminApi.triggerTtDelistCheck()
    const unk = unknownCount(res)
    taskStore.updateTask(innerId, {
      status: 'completed', progress: 1,
      message: `共${res.total}包，${res.delisted}掉包` + (unk ? `，${unk}未判定` : ''),
      result: res,
      finishedAt: Date.now(),
    })
    ttDelistResult.value = { success: true, ...res }
    const summary = `TT 掉包检测完成：${res.total} 个包，${res.delisted} 个掉包` + (unk ? `，${unk} 个未判定` : '')
    if (unk) ElMessage.warning(summary)
    else ElMessage.success(summary)
    window.dispatchEvent(new CustomEvent('delist-check-completed'))
  } catch (e) {
    const msg = e?.response?.data?.error || e.message || '未知错误'
    taskStore.updateTask(innerId, {
      status: 'error', message: msg, finishedAt: Date.now(),
    })
    ttDelistResult.value = { success: false, error: msg }
    ElMessage.error('TT 掉包检测失败：' + msg)
  } finally {
    ttDelistRunning.value = false
  }
}

// 每周清理
const cleanupRunning = ref(false)
const cleanupResult = ref(null)

async function triggerCleanup() {
  cleanupRunning.value = true
  cleanupResult.value = null
  const innerId = taskStore.addTask('cleanup', '每周清理', null)
  try {
    const res = await adminApi.triggerWeeklyCleanup()
    taskStore.updateTask(innerId, {
      status: 'completed', progress: 1,
      message: res.message || '清理完成',
      result: res,
      finishedAt: Date.now(),
    })
    cleanupResult.value = { success: true, ...res }
    ElMessage.success('每周清理已执行完成')
  } catch (e) {
    const msg = e?.response?.data?.error || e.message || '未知错误'
    taskStore.updateTask(innerId, {
      status: 'error', message: msg, finishedAt: Date.now(),
    })
    cleanupResult.value = { success: false, error: msg }
    ElMessage.error('清理失败：' + msg)
  } finally {
    cleanupRunning.value = false
  }
}
</script>

<style scoped>
.scheduler-page {
  max-width: 800px;
}

.task-cards {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.task-card {
  transition: box-shadow 0.2s;
}
.task-card.running {
  box-shadow: 0 0 0 2px rgba(8, 145, 178, 0.3);
}

.task-header {
  display: flex;
  align-items: flex-start;
  gap: 16px;
}

.task-icon {
  font-size: 32px;
  line-height: 1;
  flex-shrink: 0;
  width: 48px;
  height: 48px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: #f8f9fa;
  border-radius: 10px;
}

.task-info {
  flex: 1;
  min-width: 0;
}

.task-name {
  font-size: 16px;
  font-weight: 600;
  color: #111827;
  margin-bottom: 4px;
}

.task-desc {
  font-size: 13px;
  color: #6b7280;
  line-height: 1.5;
  margin-bottom: 8px;
}

.task-meta {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
}

.task-action {
  flex-shrink: 0;
  display: flex;
  align-items: center;
}

.task-result {
  margin-top: 14px;
  padding: 12px 16px;
  border-radius: 8px;
  font-size: 13px;
  line-height: 1.6;
}
.task-result.success {
  background: #f0fdf4;
  color: #166534;
  border: 1px solid #bbf7d0;
}
.task-result.error {
  background: #fef2f2;
  color: #991b1b;
  border: 1px solid #fecaca;
}

.delisted-item {
  padding: 2px 0;
  font-size: 12px;
  color: #991b1b;
}
</style>
