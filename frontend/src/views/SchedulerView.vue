<template>
  <div class="scheduler-page">
    <div style="display:flex;align-items:center;margin-bottom:16px;">
      <h3 style="margin:0;font-size:18px;font-weight:600;color:#111827;">⏰ 定时任务管理</h3>
      <span style="font-size:13px;color:#9ca3af;margin-left:12px;">管理本平台的定时任务</span>
    </div>

    <div class="task-cards">
      <!-- 卡片由接口 tasks 驱动渲染：FB 管理员拿到空数组 → 渲染空态 -->
      <el-card v-for="task in tasks" :key="task.key" shadow="never" class="task-card"
               :class="{ running: taskRunning(task) }">
        <div class="task-header">
          <div class="task-icon">{{ meta(task).icon }}</div>
          <div class="task-info">
            <div class="task-name">{{ task.name }}</div>
            <div class="task-desc">{{ meta(task).desc }}</div>
            <div v-if="meta(task).tags.length" class="task-meta">
              <el-tag v-for="tag in meta(task).tags" :key="tag.text" size="small" :type="tag.type">{{ tag.text }}</el-tag>
            </div>
          </div>
          <div class="task-action">
            <el-button type="primary" :loading="taskRunning(task)" :disabled="taskRunning(task)" @click="runTask(task)">
              {{ taskRunning(task) ? meta(task).busyText : '立即执行' }}
            </el-button>
          </div>
        </div>

        <!-- 掉包检测结果（GG / TT 同构，四态展示原样保留） -->
        <div v-if="taskResult(task) && meta(task).resultType === 'delist'"
             class="task-result" :class="taskResult(task).success ? 'success' : 'error'">
          <template v-if="taskResult(task).success">
            ✅ 检测完成：共 <strong>{{ taskResult(task).total }}</strong> 个包，
            发现 <strong :style="{ color: taskResult(task).delisted > 0 ? '#ef4444' : (unknownCount(taskResult(task)) > 0 ? '#f59e0b' : '#10b981') }">{{ taskResult(task).delisted }}</strong> 个掉包
            <span v-if="unknownCount(taskResult(task)) > 0" style="color:#f59e0b;">
              ，{{ unknownCount(taskResult(task)) }} 个未判定（已保留上次判定结果）
            </span>
            <div v-if="taskResult(task).delisted > 0" style="margin-top:8px;">
              <div v-for="r in taskResult(task).results.filter(x => x.is_delisted)" :key="r.package_id" class="delisted-item">
                ⚠️ {{ r.package_name }} (产品 #{{ r.product_id }})
              </div>
            </div>
          </template>
          <template v-else>
            ❌ 检测失败：{{ taskResult(task).error }}
          </template>
        </div>

        <!-- 清理结果 -->
        <div v-if="taskResult(task) && meta(task).resultType === 'cleanup'"
             class="task-result" :class="taskResult(task).success ? 'success' : 'error'">
          <template v-if="taskResult(task).success">
            ✅ {{ taskResult(task).message || '清理完成' }}
          </template>
          <template v-else>
            ❌ 清理失败：{{ taskResult(task).error }}
          </template>
        </div>

        <!-- 调度条：线上是「它现在是什么」，线下是「你能调什么」 -->
        <div class="schedule-bar">
          <div class="schedule-edit">
            <template v-if="task.kind === 'interval'">
              <span class="schedule-label">每</span>
              <el-input-number v-model="draft[task.key]" :min="task.min" :max="task.max"
                               :step="10" size="small" controls-position="right" style="width:110px;" />
              <span class="schedule-label">分钟</span>
            </template>
            <template v-else>
              <span class="schedule-label">每周</span>
              <el-select v-model="draftWeekday" size="small" style="width:88px;">
                <el-option v-for="(d, i) in WEEKDAYS" :key="i" :label="d" :value="i" />
              </el-select>
              <el-select v-model="draftHour" size="small" style="width:96px;">
                <el-option v-for="h in 24" :key="h - 1" :label="pad2(h - 1) + ':00'" :value="h - 1" />
              </el-select>
            </template>
            <el-button size="small" type="primary" plain :disabled="!dirty(task)"
                       :loading="savingKey === task.key" @click="saveTask(task)">保存</el-button>
          </div>
          <div class="schedule-last" :class="{ failed: task.last_run && !task.last_run.ok }">
            {{ lastRunText(task.last_run) }}
          </div>
        </div>
      </el-card>

      <!-- 空态 / 错误态：同一套结构（图标 + 标题 + 说明）的两个分支，复用 .scheduler-empty。
           空态 = FB 管理员有权进入但本平台无任务（空数组 ≠ 接口 403 无权限，故失败时不渲染空态）；
           错误态 = 读取失败（含无权限），多一个「重试」按钮，给用户一个下一步。 -->
      <div v-if="!loading && !loadError && tasks.length === 0" class="scheduler-empty">
        <div class="empty-icon">🗓️</div>
        <div class="empty-title">当前平台暂无可管理的定时任务</div>
        <div class="empty-desc">定时任务按平台划分：Google Ads 掉包检测与每周清理归 GG，TikTok 掉包检测归 TT。</div>
      </div>
      <div v-else-if="!loading && loadError" class="scheduler-empty">
        <div class="empty-icon">⚠️</div>
        <div class="empty-title">定时任务配置加载失败</div>
        <div class="empty-desc">{{ loadErrorMsg || '请稍后重试；若持续失败，请联系管理员。' }}</div>
        <el-button size="small" type="primary" plain style="margin-top:16px;" @click="loadConfig">重试</el-button>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { adminApi } from '../api/admin'
import { useTaskStore } from '@/stores/taskRunner'
import { ElMessage } from 'element-plus'

const taskStore = useTaskStore()

// ===== 定时任务配置：数据驱动渲染 + 周期可编辑 + 上次执行 =====

const WEEKDAYS = ['周一', '周二', '周三', '周四', '周五', '周六', '周日']

// 后端 tasks 只回传调度字段（key / name / kind / value / min / max / weekday / hour / field / last_run），
// 图标、说明、非频率标签属展示层，留在前端按 key 映射；后端新增任务时补一条即可。
//
// 保存 / 回填用到的「配置字段名」也集中在此，不散在业务逻辑里：
//   - interval 类：后端 GET 已回传 task.field（如 gg_delist_minutes），直接用它；
//   - weekly 类：后端 GET **不回传** field，故在此表登记 weekdayField / hourField，
//     保存与回填两处共用同一来源，避免在逻辑里硬编码字段名。
const TASK_META = {
  gg_delist: {
    icon: '🔍',
    desc: '检测所有正常产品的 Google Play 链接是否掉包，并发送邮件通知在跑人员',
    // 「启动时立即执行一次」的代码本就注释掉了，首次执行在启动后一整个周期 ⇒ 不挂 tag
    tags: [],
    resultType: 'delist',
    busyText: '检测中...',
  },
  tt_delist: {
    icon: '🔍',
    desc: '检测所有正常 TT 产品的跑包链接是否掉包，并通过 TT 机器人（Telegram）通知在跑人员',
    tags: [{ text: '独立机器人：TT-Server', type: 'success' }],
    resultType: 'delist',
    busyText: '检测中...',
  },
  cleanup: {
    icon: '🧹',
    desc: '清理 scraped_images 目录下的爬取图片和生成视频文件（音乐库 ai 子目录保留）',
    tags: [],
    resultType: 'cleanup',
    busyText: '清理中...',
    // weekly 的 payload / config 字段名（后端 scheduler_config 的键）
    weekdayField: 'cleanup_weekday',
    hourField: 'cleanup_hour',
  },
}

// 兜底：接口将来加了前端还没配元信息的任务，也不至于渲染成空白卡
function meta(task) {
  return TASK_META[task.key]
    || { icon: '⏱️', desc: '', tags: [], resultType: 'delist', busyText: '执行中...' }
}

const tasks = ref([])
const loading = ref(true)
// 按任务 key 记录「正在保存的是哪张卡」——只点亮该卡的保存按钮
// （单例 ref 会让任一卡保存时所有卡的按钮一起转圈，见 findings #14）
const savingKey = ref(null)
const draft = ref({})          // { gg_delist: 60, tt_delist: 30 }  —— interval 类
const draftWeekday = ref(6)
const draftHour = ref(0)
// 读取失败（含 403 无权限）与「本平台确实没有任务」是两回事，空态只在后者出现
const loadError = ref(false)
const loadErrorMsg = ref('')   // 失败原因（后端 error 原文），供错误态持久展示

async function loadConfig() {
  loading.value = true
  loadError.value = false
  loadErrorMsg.value = ''
  try {
    const res = await adminApi.getSchedulerConfig()
    tasks.value = res.tasks || []
    for (const t of tasks.value) {
      if (t.kind === 'interval') draft.value[t.key] = t.value
      else { draftWeekday.value = t.weekday; draftHour.value = t.hour }
    }
  } catch (e) {
    loadError.value = true
    loadErrorMsg.value = e?.response?.data?.error || e.message || ''
    ElMessage.error('读取定时任务配置失败：' + (loadErrorMsg.value || '未知错误'))
  } finally {
    loading.value = false
  }
}

// 用 PUT 响应里的全量配置就地回填（设计 §5）——省去保存后重拉一次的往返。
// 字段名与 saveTask 同源：interval 用 task.field，weekly 用 TASK_META 的 weekday/hourField。
function applyConfig(config) {
  if (!config) return
  for (const t of tasks.value) {
    if (t.kind === 'interval') {
      if (t.field in config) { t.value = config[t.field]; draft.value[t.key] = config[t.field] }
    } else {
      const m = meta(t)
      if (m.weekdayField in config) { t.weekday = config[m.weekdayField]; draftWeekday.value = config[m.weekdayField] }
      if (m.hourField in config) { t.hour = config[m.hourField]; draftHour.value = config[m.hourField] }
    }
  }
}

function dirty(task) {
  if (task.kind === 'interval') return draft.value[task.key] !== task.value
  return draftWeekday.value !== task.weekday || draftHour.value !== task.hour
}

async function saveTask(task) {
  // 字段名不散在逻辑里：interval 用后端回传的 task.field，weekly 用 TASK_META 登记的字段名
  const m = meta(task)
  const payload = task.kind === 'interval'
    ? { [task.field]: draft.value[task.key] }
    : { [m.weekdayField]: draftWeekday.value, [m.hourField]: draftHour.value }
  savingKey.value = task.key
  try {
    const res = await adminApi.updateSchedulerConfig(payload)
    ElMessage.success('已保存，将在 30 秒内生效')
    // 就地回填接口返回的全量配置（设计 §5）——不再为配置多拉一次 GET。
    // 「上次执行」不必随之刷新：改周期只改「下次何时跑」，不触发任何执行
    //（_interval_loop 每 tick 重算目标 / 周清分段等待，均不会立即 run；last_run 只在
    // 真跑完后由 _mark_task_run 写入），故 task.last_run 保持原值即是最新、不陈旧。
    // 真正会推进 last_run 的是「立即执行」，那三处成功后仍各自调用 loadConfig()。
    applyConfig(res.config)
  } catch (e) {
    ElMessage.error('保存失败：' + (e?.response?.data?.error || e.message))
  } finally {
    savingKey.value = null
  }
}

function pad2(n) { return String(n).padStart(2, '0') }

// 今天 / 昨天 / MM-DD；失败与从未执行是两回事，必须分开
function lastRunText(last) {
  if (!last) return '尚未执行'
  const t = String(last.ts || '').replace('T', ' ')
  const hhmmss = t.slice(11, 19)
  const day = t.slice(0, 10)
  const now = new Date()
  const today = `${now.getFullYear()}-${pad2(now.getMonth() + 1)}-${pad2(now.getDate())}`
  const y = new Date(now.getTime() - 86400000)
  const yesterday = `${y.getFullYear()}-${pad2(y.getMonth() + 1)}-${pad2(y.getDate())}`
  const when = day === today ? '今天' : (day === yesterday ? '昨天' : day.slice(5))
  return last.ok ? `上次执行 ${when} ${hhmmss}` : `上次执行失败（${day.slice(5)} ${hhmmss}）`
}

// ===== 以下为既有逻辑（仅按 task.key 分派到三个执行函数，函数本身不变） =====

// 未知 = is_delisted 为 null（限流/服务端异常/空 url 等），既不是掉包也不是正常
function unknownCount(res) {
  return (res?.results || []).filter(r => r.is_delisted == null).length
}

// 恢复上次执行结果（切换页面后回来）+ 拉取定时任务配置
onMounted(() => {
  loadConfig()
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
    await loadConfig()
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
    await loadConfig()
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
    await loadConfig()
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

// 按 task.key 分派到上面三个执行函数与各自的状态 ref（卡片是数据驱动的，模板无法直接写死某一个）
function taskRunning(task) {
  if (task.key === 'gg_delist') return delistRunning.value
  if (task.key === 'tt_delist') return ttDelistRunning.value
  return cleanupRunning.value
}

function taskResult(task) {
  if (task.key === 'gg_delist') return delistResult.value
  if (task.key === 'tt_delist') return ttDelistResult.value
  return cleanupResult.value
}

function runTask(task) {
  if (task.key === 'gg_delist') return triggerDelist()
  if (task.key === 'tt_delist') return triggerTtDelist()
  return triggerCleanup()
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

/* 卡片内调度条：线上是「它现在是什么」，线下是「你能调什么」 */
.schedule-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
  margin-top: 14px;
  padding-top: 12px;
  border-top: 1px solid #f3f4f6;
}
.schedule-edit { display: flex; align-items: center; gap: 6px; }
.schedule-label { font-size: 13px; color: #6b7280; }
.schedule-last {
  font-size: 13px;
  color: #9ca3af;
  font-variant-numeric: tabular-nums;
}
.schedule-last.failed { color: #ef4444; }

.scheduler-empty { text-align: center; padding: 56px 20px; }
.empty-icon { font-size: 40px; line-height: 1; margin-bottom: 16px; }
.empty-title { font-size: 15px; font-weight: 600; color: #374151; margin-bottom: 8px; }
.empty-desc { font-size: 13px; color: #9ca3af; line-height: 1.6; }
</style>
