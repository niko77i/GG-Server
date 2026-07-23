# 全局任务进度追踪 & 跨标签同步 设计文档

## 1. 需求描述

GG-Server 前端所有长操作（视频生成、定时任务手动执行等）在两个场景下状态丢失或不同步：

### 1.1 切换页面进度丢失

视频生成、定时任务手动执行等操作触发后，用户切换到其他页面再回来，进度条消失、结果丢失。根因是所有任务状态绑定在 Vue 组件局部变量（ref）上，路由切换时组件销毁，状态随之销毁。

### 1.2 多标签页状态不同步

掉包通知的 `_notifiedPkgIds` 每个 Tab 独立维护。Tab A 关闭了通知，Tab B 还会重复弹出。同理，Tab A 提交的视频生成任务，Tab B 中完全看不到。

### 1.3 核心功能

1. **切换页面不丢进度**：任务状态提升到全局 Pinia Store，路由切换不影响
2. **刷新页面恢复进度**：运行中任务持久化到 localStorage，页面加载时恢复并重新轮询
3. **多标签页状态同步**：通过 BroadcastChannel 跨 Tab 同步任务列表和掉包通知状态
4. **全局可视**：右下角浮动面板显示所有运行中的任务，任何页面可见

---

## 2. 技术方案

### 2.1 架构总览

```
                         BroadcastChannel ('gg-server-sync')
                         ════════════════════════════════════
                         ▲          ▲          ▲
                         │          │          │
                   ┌─────┴──┐ ┌────┴───┐ ┌───┴──────┐
                   │ Tab A  │ │ Tab B  │ │  Tab C   │
                   └───┬────┘ └───┬────┘ └────┬─────┘
                       │          │           │
              ┌────────▼──────────▼───────────▼───────┐
              │          Pinia taskRunner Store        │
              │  · tasks: {}          (任务列表)       │
              │  · startPolling()     (3s 全局轮询)    │
              │  · recoverFromStorage (刷新恢复)       │
              │  · broadcast events   (跨 Tab 广播)    │
              └────────┬──────────────────────────────┘
                       │
          ┌────────────┼────────────┐
          ▼            ▼            ▼
   localStorage   GlobalTaskPanel   App.vue 掉包通知轮询
   (刷新恢复)     (浮动 UI)         (已有，增加广播同步)
```

### 2.2 三种同步机制对照

| 场景 | 机制 | 原理 |
|------|------|------|
| 切换页面不丢 | Pinia Store 单例 | Vue Router 销毁组件但不断销毁 Pinia store 实例 |
| 刷新页面恢复 | localStorage | 存 running 任务的 taskId，加载时恢复并重新轮询 |
| 多 Tab 同步 | BroadcastChannel | 一个 Tab 的 task/delist 变更广播给同源所有 Tab |

### 2.3 同步防循环

接收广播时更新 store 传 `{ sync: false }` 标记，跳过：
1. 二次广播（不发 BroadcastChannel）
2. 二次写 localStorage
3. 触发的 watch 副作用

---

## 3. 涉及的文件

### 3.1 新建文件

| 文件 | 说明 |
|------|------|
| `frontend/src/utils/broadcast.js` | BroadcastChannel 封装：消息类型、tabId 去重、发送/监听 |
| `frontend/src/stores/taskRunner.js` | Pinia Store：任务 CRUD、3s 轮询、localStorage 持久化、广播 |
| `frontend/src/components/GlobalTaskPanel.vue` | 浮动任务面板：FAB + 可展开面板，所有页面可见 |

### 3.2 修改文件

| 文件 | 变更说明 |
|------|---------|
| `py/main.py` | ① `video_generate()` 加 `database.task_create()` ② `_run()` 线程加 `database.task_update()` ③ `video_progress()` 加惰性清理（过期任务 >1h）和 DB 回退查询 ④ 新增 `GET /api/tasks`（用 `_yt_db()` 请求级共享连接） |
| `frontend/src/App.vue` | ① 挂载 `<GlobalTaskPanel />` ② `onMounted` 调 `taskStore.init()` + `taskStore.startPolling()` ③ `checkDelistNotifications()` 增广播同步 ④ 跨 Tab 消息处理（掉包通知同步） |
| `frontend/src/views/VideoView.vue` | `doGenerate()` 调 `taskStore.addTask()`；本地进度 watch store |
| `frontend/src/views/MediaView.vue` | 同上 |
| `frontend/src/views/SchedulerView.vue` | ① `onMounted` 从 store 恢复上次 delist/cleanup 结果 ② `triggerDelist()` / `triggerCleanup()` 通过 store 追踪结果 |

### 3.3 不修改

- `py/database.py`（`task_create`、`task_update`、`task_get`、`task_delete` 已存在）
- 其他 Vue 组件和 Store

---

## 4. 数据结构

### 4.1 任务对象（taskRunner Store）

```javascript
{
  id: 1,                             // store 内部自增 ID
  type: 'video' | 'delist' | 'cleanup',
  label: 'com.example.game.mp4',
  taskId: 'abc123...',               // 后端 task_id（轮询和恢复靠它），同步任务为 null
  status: 'pending' | 'running' | 'completed' | 'error',
                                     // pending: 已注册但未开始（如 delist 同步调用期间）
                                     // running: 正在执行（视频生成排队/执行中）
  progress: 0.45,                    // 0.0 - 1.0
  message: '正在合成第 3/10 张...',
  result: null,                      // 完成后存后端返回数据
  error: null,
  startedAt: 1700000000000,
  finishedAt: null,
}
```

### 4.2 localStorage 持久化格式

Key: `gg_active_tasks`
Value: 只存 running 任务的精简版 `[{id, type, label, taskId, status, startedAt, meta?}]`，无 running 任务时删除该 key

### 4.3 BroadcastChannel 消息格式

```javascript
{
  type: 'task_added' | 'task_updated' | 'delist_notified' | 'delist_dismissed',
  payload: { ... },      // 具体数据
  tabId: 'uuid-xxxx',    // 发送方 Tab ID，接收方用于去重
  ts: 1700000000000,
}
```

Channel name: `gg-server-sync`

---

## 5. 后端改动详情（py/main.py）

### 5.1 `video_generate()` 增加 DB 写入

在 `_video_tasks[task.task_id] = task` 之后增加：

```python
try:
    database.task_create(
        task_id=task.task_id,
        package=data.get("settings", {}).get("output_path", ""),
        settings=data,
    )
except Exception:
    pass  # DB 写入失败不影响主流程
```

### 5.2 `_run()` 线程增加 DB 更新

在 `task.run()` 之后（FFmpeg 完成或出错），增加：

```python
try:
    status = "completed" if task.status == "completed" else "error"
    database.task_update(
        task_id=task.task_id,
        status=status,
        progress=1.0 if status == "completed" else task.progress,
        message=task.message or "",
        output_path=task.result().get("path", "") if task.result() else "",
        finished_at=datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    )
except Exception:
    pass
```

### 5.3 `video_progress()` 增加 DB 回退 + 惰性清理

在内存查找之前，先执行惰性清理：每次查询进度时，清理 `_video_tasks` 中超过 1 小时的已完成/错误任务（同时从 SQLite 删除对应记录）。

```python
# 惰性清理：每次查询进度时，清理超过 1 小时的已完成/错误任务
_now = _time.time()
_expired = [tid for tid, t in _video_tasks.items()
            if t.status in ("completed", "error")
            and (_now - getattr(t, '_completed_at', 0)) > 3600]
for tid in _expired:
    _video_tasks.pop(tid, None)
    try:
        database.task_delete(tid)
    except Exception:
        pass
```

当前逻辑：`task = _video_tasks.get(task_id)` → 若 `None` → 返回 404。

改后：内存找不到时，尝试 DB 查询：

```python
if task is None:
    db_task = database.task_get(task_id)
    if db_task:
        _out = None
        if db_task.get("output_path"):
            _out = {"path": db_task["output_path"]}
        return jsonify({
            "task_id": db_task["task_id"],
            "status": db_task["status"],
            "progress": db_task["progress"],
            "message": db_task["message"],
            "output": _out,
        })
```

**场景**：服务器重启后 `_video_tasks` 清空，但 DB 中有历史记录。用户刷新页面后仍能从 DB 查到已完成任务的结果。

### 5.4 新增 `GET /api/tasks`

```python
@app.route("/api/tasks", methods=["GET"])
@jwt_required()
def list_active_tasks():
    """返回活跃任务及最近完成的任务列表。页面刷新后用于恢复。"""
    db = _yt_db()  # 请求级共享连接，通过 Flask g 管理，无需手动 close
    rows = db.execute("""
        SELECT task_id, status, progress, message, output_path, created_at, finished_at
        FROM video_tasks
        WHERE status IN ('pending', 'processing')
           OR (status IN ('completed', 'error')
               AND finished_at >= datetime('now', 'localtime', '-1 hour'))
        ORDER BY created_at DESC
        LIMIT 50
    """).fetchall()

    tasks = []
    for r in rows:
        d = dict(r)
        # 内存中有更新的数据则用内存覆盖 DB
        mem = _video_tasks.get(d["task_id"])
        if mem:
            d["status"] = mem.status
            d["progress"] = mem.progress
            d["message"] = mem.message
        tasks.append(d)
    return jsonify({"success": True, "tasks": tasks})
```

### 5.5 定时任务端点 — 不修改

`admin_trigger_delist_check` 和 `admin_trigger_weekly_cleanup` 保持同步 API。前端通过 store 追踪结果。

---

## 6. 前端改动详情

### 6.1 `utils/broadcast.js` — BroadcastChannel 封装

```javascript
const CHANNEL_NAME = 'gg-server-sync'

const MSG = {
  TASK_ADDED: 'task_added',
  TASK_UPDATED: 'task_updated',
  DELIST_NOTIFIED: 'delist_notified',
  DELIST_DISMISSED: 'delist_dismissed',
}

let _channel = null
function getChannel() {
  if (_channel === null) {
    try {
      _channel = new BroadcastChannel(CHANNEL_NAME)
    } catch {
      _channel = undefined // undefined = 尝试过但不支持（与 null "未尝试"区分）
    }
  }
  return _channel || null
}

let _tabId = null
export function tabId() {
  if (!_tabId) {
    _tabId = sessionStorage.getItem('_gg_tabId')
    if (!_tabId) {
      _tabId = crypto.randomUUID
        ? crypto.randomUUID()
        : Date.now().toString(36) + Math.random().toString(36).slice(2)
      sessionStorage.setItem('_gg_tabId', _tabId)
    }
  }
  return _tabId
}

export function broadcast(type, payload) {
  try {
    const ch = getChannel()
    if (ch) {
      ch.postMessage({ type, payload, tabId: tabId(), ts: Date.now() })
    }
  } catch { /* 静默降级 */ }
}

export function onMessage(handler) {
  try {
    const ch = getChannel()
    if (ch) {
      ch.addEventListener('message', (e) => {
        // 忽略自己发出的消息
        if (!e.data || e.data.tabId === tabId()) return
        handler(e.data)
      })
    }
  } catch { /* 静默降级 */ }
}

// tabId 也作为命名导出，供外部排障使用
export { MSG, broadcast, onMessage, tabId }
```

### 6.2 `stores/taskRunner.js` — 核心 Store

#### State

```javascript
state: () => ({
  tasks: {},           // { [internalId]: Task }
  _nextId: 1,
  _timer: null,        // 轮询定时器
  _cleanupTimer: null, // 清理过期任务的定时器
  _ready: false,       // 是否已完成初始化
})
```

#### Getters

```javascript
getters: {
  /** 运行中的任务列表（按启动时间倒序） */
  activeTasks: (s) => Object.values(s.tasks)
    .filter(t => t.status === 'running')
    .sort((a, b) => b.startedAt - a.startedAt),

  /** 运行中任务数量 */
  runningCount() { return this.activeTasks.length },

  /** 面板中可见的任务：未 dismiss 的所有任务（过期由 _startCleanupTimer 定时删除） */
  visibleTasks: (s) => Object.values(s.tasks)
    .filter(t => !t._dismissed)
    .sort((a, b) => b.startedAt - a.startedAt),
}
```

#### Actions

`init()`
- 初始化入口，幂等（`_ready` 标记防止重复初始化）
- 调 `_recoverFromStorage()` 恢复上次 running 任务
- 调 `_setupBroadcastListener()` 监听其他 Tab 的 BroadcastChannel 消息
- 调 `_startCleanupTimer()` 启动过期任务定时清理

`addTask(type, label, taskId)` → internal id
- 创建任务对象，加入 `tasks`
- 无 `taskId` 时（如 delist/cleanup 同步任务），status 为 `pending`
- 有 `taskId` 时（视频生成），status 为 `running`
- 调 `_persist()` 写 localStorage
- 调 `broadcast(MSG.TASK_ADDED, task)`
- 确保轮询已启动

`updateTask(id, patch, opts = { sync: true })`
- 更新任务字段
- 如果 opts.sync：写 localStorage + broadcast
- 如果接收其他 Tab 广播：`opts.sync = false`，只更新本地

`dismissTask(id)` — 标记 `_dismissed = true`
- 写 localStorage + 广播给其他 Tab

`startPolling()` / `stopPolling()` / `_poll()`
- 3 秒间隔轮询所有 running 视频任务的 `/api/video/progress`
- `_poll` 内部使用 `Promise.allSettled` 并行查询，N 个任务只花 1 次 RTT
- 没有任何 running 视频任务时自动 `stopPolling`
- `_poll` 内部的 `updateTask` 调 `{ sync: false }` 避免广播风暴

`applyRemote(msg)`
- 收到其他 Tab 广播后同步到本地
- 支持两种格式：完整任务对象（TASK_ADDED）或增量 patch（TASK_UPDATED）
- 调 `updateTask(id, patch, { sync: false })` 防止二次广播

#### 内部方法

`_recoverFromStorage()`
- 读 localStorage `gg_active_tasks`
- 恢复 status === 'running' 的任务到 store，`_nextId` 跳过已有 ID
- 恢复后 `progress` 重置为 0，`message` 设为 `"正在重新连接..."`
- 有恢复的任务则启动轮询

`_persist()`
- 持久化所有 running 任务到 localStorage（含 `id, type, label, taskId, status, startedAt`，以及可选的 `meta`）
- 无 running 任务时删除 localStorage key

`_setupBroadcastListener()`
- 注册 `onMessage` 处理 TASK_ADDED / TASK_UPDATED 消息
- 收到广播后调 `applyRemote(payload)`

`_startCleanupTimer()`
- 每分钟清理一次：删除 `finishedAt` 超过 5 分钟（`COMPLETED_TTL`）的非 running 任务
- 清理后写 localStorage

#### 初始化

Store 不自动初始化。需在 `App.vue onMounted` 中显式调用 `taskStore.init()`，该方法内部完成：
1. 调 `_recoverFromStorage()` 恢复上次 running 任务
2. 启动 `_setupBroadcastListener()` 监听其他 Tab
3. 启动 `_startCleanupTimer()` 定期清理过期任务

### 6.3 `components/GlobalTaskPanel.vue` — 浮动面板

**外观**：
- 固定在页面右下角 `position: fixed; bottom: 24px; right: 24px; z-index: 2000`
- 圆形 FAB 按钮 48×48px，`el-badge` 显示 `runningCount` 角标
- 有运行中任务时图标为 ⏳，否则为 ✅
- 点击展开 360×420px 面板，带 `panel-slide` 上滑过渡动画

**面板内容**：
- 列表项：类型图标（🎬/🔍/🧹）+ 名称 + 状态标签 + 进度条 + 消息文字
- 运行中：`el-progress` 动态进度条，蓝色"运行中"标签
- 已完成：绿色"已完成"标签，可点击关闭按钮 dismiss
- 失败：红色"失败"标签 + 错误消息，可点击关闭
- 空态：显示"没有正在运行的任务"
- 容器使用自定义 CSS 样式（白色背景、圆角、阴影），未使用 `el-card`
- 使用 `el-progress`、`el-badge`、`el-button` 保持与项目风格一致

### 6.4 `App.vue` 改动

```javascript
// 新增 import
import GlobalTaskPanel from './components/GlobalTaskPanel.vue'
import { useTaskStore } from './stores/taskRunner'
import { MSG, broadcast, onMessage } from './utils/broadcast'

const taskStore = useTaskStore()

// onMounted 中新增：
taskStore.init()          // 恢复 localStorage + 启动广播监听 + 启动清理定时器
taskStore.startPolling()  // 启动视频任务轮询

// 监听跨 Tab 事件（主要是掉包通知，TASK_* 由 taskRunner 内部处理）：
onMessage((msg) => {
  if (msg.type === MSG.DELIST_NOTIFIED) {
    const { package_id, type, reminder_count } = msg.payload
    // 与 checkDelistNotifications 中保持一致的 key 计算逻辑
    const key = type === 'reminder'
      ? `${package_id}-reminder-${reminder_count || 0}`
      : `${package_id}-first`
    _notifiedPkgIds.add(key)
  }
  if (msg.type === MSG.DELIST_DISMISSED) {
    // 关闭本地同名通知（需持有 ElNotification 引用）
    closeNotificationByPkgId(msg.payload.package_id)
  }
  // TASK_ADDED / TASK_UPDATED 由 taskStore 内部 _setupBroadcastListener 处理，此处不重复
})

// checkDelistNotifications() 中弹通知后广播（type 用于区分首次/提醒）：
broadcast(MSG.DELIST_NOTIFIED, {
  package_id: n.package_id,
  type: n.type,
  reminder_count: n.reminder_count || 0,
})

// 通知 onClose 回调中广播：
broadcast(MSG.DELIST_DISMISSED, { package_id: n.package_id })
```

Template 中主内容区之后挂载：
```html
<GlobalTaskPanel />
```

### 6.5 VideoView.vue / MediaView.vue 改动

**改动点**：`doGenerate()` 中拿到 `task_id` 后注册到全局 store。

```javascript
// 改前：
store.generate(s).then(res => {
  const tid = res.task_id
  // 本地 poll 自己改 progressPct / progressMsg
})

// 改后：
const s = getSettings()
const res = await store.generate(s)
const tid = res.task_id
const label = (logo.value ? logo.value.filename : (images.value[0]?.filename || '未命名'))
const innerId = taskStore.addTask('video', label, tid)
// 保存页面上下文（目录 + 输出路径），便于切换页面后恢复表单状态
taskStore.updateTask(innerId, {
  meta: { videoDir: videoDir.value, outputPath: outputPath.value },
})
// 本地通过 watch taskStore.tasks[innerId] 同步 progressPct
// 全局轮询并行更新同一 store 条目
```

**保留**：
- 本地 `pollTimer`（2 秒精确轮询，比全局 3 秒快）
- `taskQueue` 页面内队列逻辑

**新增**：
- `onMounted` 中检查 store 是否有活跃视频任务，有则恢复进度 UI

### 6.6 SchedulerView.vue 改动

**`onMounted` 中恢复上次执行结果**（切换页面后回来能看到上次的掉包检测/清理结果）：

```javascript
onMounted(() => {
  for (const t of taskStore.visibleTasks) {
    if (t.type === 'delist' && t.status === 'completed' && t.result) {
      delistResult.value = { success: true, ...t.result }
    }
    if (t.type === 'cleanup' && t.status === 'completed' && t.result) {
      cleanupResult.value = { success: true, ...t.result }
    }
  }
})
```

**`triggerDelist` 函数**：

```javascript
async function triggerDelist() {
  delistRunning.value = true
  delistResult.value = null
  const innerId = taskStore.addTask('delist', '掉包检测', null)

  try {
    const res = await adminApi.triggerDelistCheck()
    taskStore.updateTask(innerId, {
      status: 'completed', progress: 1,
      message: `共${res.total}包，${res.delisted}掉包`,
      finishedAt: Date.now(),
    })
    delistResult.value = { success: true, ...res }
    ElMessage.success(...)
    window.dispatchEvent(new CustomEvent('delist-check-completed'))
  } catch (e) {
    taskStore.updateTask(innerId, {
      status: 'error',
      message: e?.response?.data?.error || e.message,
      finishedAt: Date.now(),
    })
    delistResult.value = { success: false, error: msg }
    ElMessage.error(...)
  } finally {
    delistRunning.value = false
  }
}
```

API 仍为同步调用——store 的作用是保存结果，确保切换页面或刷新后仍可读取。

---

## 7. 边界情况

| 场景 | 处理方式 |
|------|---------|
| **页面刷新** | localStorage 恢复 running 任务 → 重新轮询 taskId（恢复后 progress 重置为 0，message 显示"正在重新连接..."） |
| **服务器重启** | `_video_tasks` 清空 → 轮询 taskId → `video_progress` DB 回退查询兜底，仍查不到则 404 → 标记 error |
| **惰性清理（服务器端）** | 每次 `video_progress()` 调用时惰性清理 `_video_tasks` 中 >1h 的已完成/错误任务（同时删 SQLite 记录） |
| **惰性清理（前端）** | `_startCleanupTimer` 每分钟清理 `finishedAt` 超过 5 分钟的非 running 任务并更新 localStorage |
| **BroadcastChannel 不可用** | try/catch 降级，`_channel` 设为 `undefined`（与 `null`"未尝试"区分），功能退化到单 Tab 模式 |
| **localStorage 满** | try/catch 降级，刷新恢复失效但不影响当前操作；无 running 任务时删除 key 而非留空数组 |
| **广播风暴** | 接收方 `{ sync: false }` 禁止二次广播和写 localStorage；`_poll` 内部 `updateTask` 也使用 `{ sync: false }` |
| **轮询自动启停** | 有 running 视频任务时 `startPolling`；`_poll` 检测到无 running 视频任务时自动 `stopPolling` |
| **init() 重复调用** | `_ready` 标记保证幂等，多次调用不重复初始化 |
| **相同任务多 Tab 提交** | 后端独立 `task_id`，不冲突 |
| **多 Tab 同通知** | Tab A 弹通知时广播（含 `type` 字段区分首次/提醒），Tab B 收到后加入本地 `_notifiedPkgIds` 跳过 |

---

## 8. 验证方式

1. **切换页面**：生成视频 → 立即切到 YouTube → 看右下角面板进度条 → 完成后点开面板看结果
2. **刷新页面**：任务运行中按 F5 → 面板恢复显示进度 → 继续追踪到完成
3. **多 Tab 同步**：Tab A 提交视频生成 → 打开 Tab B → Tab B 面板同步显示任务 → Tab A 关闭掉包通知 → Tab B 不再弹
4. **多任务并发**：队列生成 5 个视频 → 面板显示 `⏳ 5` → 逐个完成
