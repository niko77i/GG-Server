# 文案管理 — 实现计划

**日期**：2026-06-15  
**关联设计**：[2026-06-15-copywriting-management-design.md](../specs/2026-06-15-copywriting-management-design.md)

---

## 实施步骤

### 步骤 1：数据库 — 新增 `copywritings` 表
- 文件：`py/database.py`
- 在 `_ensure_schema()` 中添加建表语句
- 字段：id, region, content, created_at

### 步骤 2：后端 API
- 文件：`py/main.py`
- 新增 5 个路由：
  - `POST /api/copywriting/import`
  - `GET /api/copywriting/list`
  - `POST /api/copywriting/edit`
  - `POST /api/copywriting/delete`
  - `POST /api/copywriting/batch-edit`

### 步骤 3：前端 API 层
- 文件：`frontend/src/api/youtube.js`
- 新增 `copywritingApi` 对象（5 个方法）

### 步骤 4：前端 Store
- 文件：`frontend/src/stores/youtube.js`
- 新增 state：`copywritings`, `copywritingCounts`
- 新增 actions：`loadCopywritings`, `importCopywritings`, `editCopywriting`, `deleteCopywritings`, `batchEditCopywritings`

### 步骤 5：前端路由
- 文件：`frontend/src/router/index.js`
- 新增 `/youtube/copywriting` 子路由

### 步骤 6：前端 UI
- 文件：`frontend/src/views/YoutubeView.vue`
- 新增"文案展示"标签页（树形展示 + 批量操作 + 编辑弹窗）
- "导入视频"标签页内增加子标签（导入视频 / 导入文案）
- 点击文案子节点 → 复制到剪贴板
