# FB 账户管理页面 UI 美化 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 统一美化 FB 平台"账户管理"下 5 个页面的 UI，采用卡片式布局 + 统计卡片 + 统一设计语言

**Architecture:** 不改 `<script setup>` 逻辑，仅重写 `<template>` 和 `<style scoped>`。所有页面共享同一套视觉规范（页面背景 `#f5f6f8`、卡片白底圆角阴影、筛选栏灰底卡片包裹、表格卡片化）。

**Tech Stack:** Vue 3 + Element Plus + scoped CSS

## Global Constraints

- 不改 `<script setup>` 中的任何逻辑（API 调用、方法名、响应式变量名）
- 不引入新依赖
- 保持所有现有功能完整
- 使用 scoped CSS，不污染全局样式
- 页面背景 `#f5f6f8`，卡片 `#fff` 圆角 `12px` 阴影 `0 1px 3px rgba(0,0,0,0.06)`
- 统计卡片 hover 上移 2px + 阴影增强

---

### Task 1: FB设置 — 三栏卡片布局

**Files:**
- Modify: `frontend/src/views/fb/FbSettingsPanel.vue`

**改动点：**
- 页面背景 `#f5f6f8`，padding 24px
- 头部统一风格：标题 20px/700 + 副标题说明
- 三栏 el-row 并排：地区管理 | 商务人员管理 | 账户状态管理
- 每栏一张卡片，内含 inline 添加表单（input + button 同行）+ 列表（tag + 删除）
- 空状态用 `el-empty` 占位

- [ ] 重写 `<template>`：三栏卡片布局替代三个堆叠的 el-card
- [ ] 重写 `<style scoped>`：完整设计系统样式

---

### Task 2: 像素BM管理 — 统计卡片 + 表格卡片化

**Files:**
- Modify: `frontend/src/views/fb/FbPixelBmPanel.vue`

**改动点：**
- 顶部统计行：总像素 BM / 总像素数（从 items 计算）
- 表格包进白色卡片
- 像素管理弹窗内像素列表也用卡片包裹

- [ ] 重写 `<template>`：加统计行、表格卡片化、弹窗优化
- [ ] 重写 `<style scoped>`：统计卡片动画、表格卡片样式

---

### Task 3: 账户BM管理 — 统计 + 表格卡片化 + 封禁弹窗优化

**Files:**
- Modify: `frontend/src/views/fb/FbBmPanel.vue`

**改动点：**
- 顶部统计行：总 BM / 正常 / 已封禁 / 关联账户总数
- 表格包进白色卡片
- 封禁弹窗加警告提示卡片

- [ ] 重写 `<template>`：统计行、表格卡片化、封禁弹窗优化
- [ ] 重写 `<style scoped>`：统计卡片动画、表格卡片样式

---

### Task 4: 广告账户 — 统计 + 筛选栏卡片化 + 表格卡片化

**Files:**
- Modify: `frontend/src/views/fb/FbAccountPanel.vue`

**改动点：**
- 顶部统计行：总账户 / 关联 BM 数（从 items/bmOptions 计算）
- 筛选栏包进浅灰底卡片
- 批量删除按钮移到表格卡片头部
- 表格包进白色卡片

- [ ] 重写 `<template>`：统计行、筛选栏卡片、表格卡片+批量操作
- [ ] 重写 `<style scoped>`：统计卡片动画、筛选卡片、表格卡片样式

---

### Task 5: 产品管理 — 统计卡片 + 筛选栏卡片化 + 产品卡片美化

**Files:**
- Modify: `frontend/src/views/fb/FbProductPanel.vue`

**改动点：**
- 顶部统计行：总产品 / 正常 / 已暂停 / 我的
- 筛选栏包进浅灰底卡片
- 产品卡片微调：圆角、阴影、hover 效果
- 展开区线名表格样式优化

- [ ] 重写 `<template>`：统计行、筛选栏卡片、产品卡片美化
- [ ] 重写 `<style scoped>`：完整设计系统样式

---

### Task 6: 验证所有页面

- [ ] 检查 5 个页面 `<script setup>` 逻辑未被修改
- [ ] 确认侧边栏路由正确（FB设置 在账户管理下）
- [ ] 确认所有功能按钮（添加/编辑/删除/筛选/分页）正常
