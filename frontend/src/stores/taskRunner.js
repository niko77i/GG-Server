/**
 * 全局任务运行状态 Store (Pinia)
 *
 * 管理所有长时间运行的任务（视频生成、定时任务手动执行等）。
 * 提供三种同步保障：
 *   1. Pinia 单例 — 路由切换不销毁
 *   2. localStorage — 页面刷新可恢复
 *   3. BroadcastChannel — 多 Tab 实时同步
 */

import { defineStore } from 'pinia'
import { videoApi } from '@/api/video'
import { MSG, broadcast, onMessage } from '@/utils/broadcast'

const LS_KEY = 'gg_active_tasks'
const POLL_INTERVAL = 3000       // 全局轮询间隔（毫秒）
const COMPLETED_TTL = 5 * 60 * 1000  // 已完成任务保留时间

export const useTaskStore = defineStore('taskRunner', {
  state: () => ({
    tasks: {},     // { [internalId]: Task }
    _nextId: 1,
    _timer: null,  // 轮询定时器
    _cleanupTimer: null,  // 清理定时器
    _ready: false, // 是否已完成初始化
  }),

  getters: {
    /** 运行中的任务列表 */
    activeTasks: (s) => Object.values(s.tasks)
      .filter(t => t.status === 'running')
      .sort((a, b) => b.startedAt - a.startedAt),

    /** 运行中任务数量 */
    runningCount() { return this.activeTasks.length },

    /** 面板中可见的任务：运行中 + 最近完成的（由清理定时器维护） */
    visibleTasks: (s) => Object.values(s.tasks)
      .filter(t => !t._dismissed)
      .sort((a, b) => b.startedAt - a.startedAt),
  },

  actions: {
    // ========== 初始化 ==========

    /**
     * 初始化 store：恢复 localStorage 中的任务 + 启动广播监听 + 启动清理
     * 应在 App.vue onMounted 中调用一次
     */
    init() {
      if (this._ready) return
      this._ready = true
      this._recoverFromStorage()
      this._setupBroadcastListener()
      this._startCleanupTimer()
    },

    // ========== 任务管理 ==========

    /**
     * 注册一个新任务
     * @param {'video'|'delist'|'cleanup'} type
     * @param {string} label
     * @param {string|null} backendTaskId - 后端返回的 task_id
     * @returns {number} store 内部 id
     */
    addTask(type, label, backendTaskId = null) {
      const id = this._nextId++
      const task = {
        id,
        type,
        label,
        taskId: backendTaskId,
        status: backendTaskId ? 'running' : 'pending',
        progress: 0,
        message: backendTaskId ? '已提交' : '等待中...',
        result: null,
        error: null,
        startedAt: Date.now(),
        finishedAt: null,
      }
      this.tasks[id] = task
      this._persist()
      broadcast(MSG.TASK_ADDED, task)
      // 确保轮询在运行
      if (!this._timer) this.startPolling()
      return id
    },

    /**
     * 更新任务状态
     * @param {number} id - store 内部 id
     * @param {object} patch - 要更新的字段
     * @param {object} [opts]
     * @param {boolean} [opts.sync=true] - 是否同步到其他 Tab（接收远程消息时应为 false）
     */
    updateTask(id, patch, opts = {}) {
      const { sync = true } = opts
      const task = this.tasks[id]
      if (!task) return
      Object.assign(task, patch)
      if (sync) {
        this._persist()
        broadcast(MSG.TASK_UPDATED, { id, patch })
      }
    },

    /**
     * 软隐藏任务（面板中不再显示）
     */
    dismissTask(id) {
      const task = this.tasks[id]
      if (!task) return
      task._dismissed = true
      this._persist()
      broadcast(MSG.TASK_UPDATED, { id, patch: { _dismissed: true } })
    },

    /**
     * 将其他 Tab 广播的任务变更同步到本地
     */
    applyRemote(data) {
      if (!data) return

      if (data.id && data.patch !== undefined) {
        // TASK_UPDATED: 增量更新
        this.updateTask(data.id, data.patch, { sync: false })
      } else if (data.id && data.type) {
        // TASK_ADDED: 完整任务对象
        if (!this.tasks[data.id]) {
          this.tasks[data.id] = data
          if (data.id >= this._nextId) this._nextId = data.id + 1
          this._persist()
        }
      }
      // 确保轮询在运行
      if (!this._timer) this.startPolling()
    },

    // ========== 轮询 ==========

    startPolling() {
      if (this._timer) return
      this._poll()
      this._timer = setInterval(() => this._poll(), POLL_INTERVAL)
    },

    stopPolling() {
      if (this._timer) {
        clearInterval(this._timer)
        this._timer = null
      }
    },

    /** @private 并行轮询所有运行中的视频任务 */
    async _poll() {
      const running = Object.values(this.tasks).filter(
        t => t.status === 'running' && t.taskId && t.type === 'video'
      )
      if (!running.length) { this.stopPolling(); return }

      // Promise.all 并行查询，N 个任务只花 1 次 RTT
      const results = await Promise.allSettled(
        running.map(t => videoApi.progress(t.taskId).then(p => ({ taskId: t.taskId, id: t.id, p })))
      )

      for (const r of results) {
        if (r.status !== 'fulfilled') continue
        const { id, p } = r.value
        this.updateTask(id, {
          status: p.status === 'completed' ? 'completed' :
                  p.status === 'error' ? 'error' : 'running',
          progress: p.progress || 0,
          message: p.message || '',
          result: p.status === 'completed' ? p : null,
          error: p.status === 'error' ? (p.message || '未知错误') : null,
          finishedAt: (p.status === 'completed' || p.status === 'error') ? Date.now() : null,
        }, { sync: false })
      }
    },

    // ========== 内部方法 ==========

    /** @private 从 localStorage 恢复 running 任务 */
    _recoverFromStorage() {
      try {
        const raw = localStorage.getItem(LS_KEY)
        if (!raw) return
        const list = JSON.parse(raw)
        if (!Array.isArray(list)) return
        for (const t of list) {
          if (!t || !t.id || t.status !== 'running') continue
          // 恢复时 _nextId 需跳过已有的 id
          if (t.id >= this._nextId) this._nextId = t.id + 1
          this.tasks[t.id] = {
            ...t,
            progress: 0,
            message: '正在重新连接...',
          }
        }
        // 有恢复的任务就启动轮询
        if (Object.keys(this.tasks).length > 0) {
          this.startPolling()
        }
      } catch { /* localStorage 不可用 */ }
    },

    /** @private 持久化 running 任务到 localStorage */
    _persist() {
      try {
        const running = Object.values(this.tasks)
          .filter(t => t.status === 'running')
          .map(t => ({
            id: t.id,
            type: t.type,
            label: t.label,
            taskId: t.taskId,
            status: t.status,
            startedAt: t.startedAt,
            ...(t.meta ? { meta: t.meta } : {}),
          }))
        if (running.length) {
          localStorage.setItem(LS_KEY, JSON.stringify(running))
        } else {
          localStorage.removeItem(LS_KEY)
        }
      } catch { /* localStorage 不可用 */ }
    },

    /** @private 监听其他 Tab 的广播 */
    _setupBroadcastListener() {
      onMessage((msg) => {
        if (msg.type === MSG.TASK_ADDED || msg.type === MSG.TASK_UPDATED) {
          this.applyRemote(msg.payload)
        }
      })
    },

    /** @private 定时清理过期任务 */
    _startCleanupTimer() {
      if (this._cleanupTimer) return
      this._cleanupTimer = setInterval(() => {
        const now = Date.now()
        for (const id of Object.keys(this.tasks)) {
          const t = this.tasks[id]
          if (!t) continue
          if (t.status !== 'running' && t.finishedAt && (now - t.finishedAt > COMPLETED_TTL)) {
            delete this.tasks[id]
          }
        }
        this._persist()
      }, 60000) // 每分钟清理一次
    },
  },
})
