# 定时任务手动调用页面 — 设计文档

## 1. 需求描述

在侧边栏新增"定时任务"页面，开发者可手动触发后端定时任务：
- 每周清理（爬取图片和生成视频）
- 掉包检测

**权限**：仅 `developer` 角色可见并可调用，`admin` 和 `viewer` 不可见。

## 2. 技术方案

### 2.1 后端 API（py/main.py）

新增 2 个 API 端点，权限限定 developer：

**1. 手动触发掉包检测**
```
POST /api/admin/trigger-delist-check
```
- 权限：JWT + developer 角色
- 逻辑：立即执行一次掉包检测（复用现有 `_start_delist_scheduler` 中的检测逻辑）
- 返回：`{ success: true, total: int, delisted: int, results: [...] }`

**2. 手动触发每周清理**
```
POST /api/admin/trigger-weekly-cleanup
```
- 权限：JWT + developer 角色
- 逻辑：立即执行一次清理（复用现有 `_start_weekly_cleanup` 中的清理逻辑）
- 返回：`{ success: true, message: str }`

**实现方式**：将现有 scheduler 内部函数中的核心逻辑提取为模块级函数，供 API 端点和定时任务共用。原有定时任务行为不变。

### 2.2 前端变更

#### 2.2.1 新页面（`frontend/src/views/SchedulerView.vue`）

- 卡片布局展示两个定时任务
- 每张卡片包含：任务名称、描述、执行频率、上次执行时间（可选）、手动触发按钮
- 按钮点击后调用对应 API，显示 loading 状态和执行结果

#### 2.2.2 API 方法（`frontend/src/api/admin.js`）

新增：
```javascript
triggerDelistCheck: () => api.post('/admin/trigger-delist-check'),
triggerWeeklyCleanup: () => api.post('/admin/trigger-weekly-cleanup'),
```

#### 2.2.3 路由（`frontend/src/router/index.js`）

新增路由：
```javascript
{
  path: '/admin/scheduler',
  component: () => import('../views/SchedulerView.vue'),
  meta: { developer: true, title: '定时任务' }
}
```

路由守卫新增：检查 `meta.developer` → 验证 `auth.isDeveloper`。

#### 2.2.4 侧边栏（`frontend/src/components/AppSidebar.vue`）

在"管理" tab 的 sections 中新增：
```javascript
{ icon:'⏰', label:'定时任务', path:'/admin/scheduler', developer: true }
```

`visibleNavItems` 和 `detailSections` 过滤逻辑新增 developer 检查。

## 3. 涉及的文件

| 文件 | 变更类型 | 说明 |
|------|---------|------|
| `py/main.py` | 修改 | 提取核心逻辑 + 新增 2 个 API 端点 |
| `frontend/src/api/admin.js` | 修改 | 新增 2 个 API 方法 |
| `frontend/src/views/SchedulerView.vue` | **新建** | 定时任务手动触发页面 |
| `frontend/src/router/index.js` | 修改 | 新增路由 + 路由守卫 developer 检查 |
| `frontend/src/components/AppSidebar.vue` | 修改 | 新增菜单项 + developer 过滤 |

## 4. UI 草图

```
╔══════════════════════════════════════════╗
║  定时任务管理                            ║
║  ⏰ 手动触发后端定时任务                  ║
╠══════════════════════════════════════════╣
║  ┌──────────────────────────────────┐   ║
║  │ 🔍 掉包检测                      │   ║
║  │ 检测所有正常产品的 Google Play    │   ║
║  │ 链接是否掉包，并发送邮件通知      │   ║
║  │ 自动频率：每小时                  │   ║
║  │                    [ 立即执行 ]   │   ║
║  └──────────────────────────────────┘   ║
║  ┌──────────────────────────────────┐   ║
║  │ 🧹 每周清理                      │   ║
║  │ 清理爬取图片和生成视频文件        │   ║
║  │ 自动频率：每周日 00:00           │   ║
║  │                    [ 立即执行 ]   │   ║
║  └──────────────────────────────────┘   ║
╚══════════════════════════════════════════╝
```
