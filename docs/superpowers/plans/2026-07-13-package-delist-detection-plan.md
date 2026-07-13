# 包掉包检测 — 实现计划

## 实现顺序（TDD）

### 阶段 1：检测模块 + 测试
1. 创建 `py/tests/test_delist_checker.py` — 写掉包检测逻辑的测试
2. 创建 `py/delist_checker.py` — 实现检测逻辑
3. 运行测试确认通过

### 阶段 2：数据库表 + API
4. 在 `py/database.py` 新增 `delist_checks` 和 `delist_notifications` 表
5. 在 `py/main.py` 新增 4 个 API 端点
6. 创建 `py/tests/test_delist_api.py` — API 测试
7. 运行测试确认通过

### 阶段 3：定时任务
8. 在 `py/main.py` 新增后台定时检测线程
9. 启动时立即执行一次

### 阶段 4：前端
10. 更新 `frontend/src/api/products.js` — 新增 API 方法
11. 更新 `frontend/src/stores/products.js` — 新增通知轮询
12. 更新 `frontend/src/components/ProductCard.vue` — 按钮 + 标红 + 通知弹窗
13. 手动验证功能完整性

## 涉及文件清单

| 文件 | 操作 |
|------|------|
| `py/tests/test_delist_checker.py` | **新建** |
| `py/delist_checker.py` | **新建** |
| `py/database.py` | 修改（新增 2 张表） |
| `py/main.py` | 修改（新增 API + 定时任务） |
| `py/tests/test_delist_api.py` | **新建** |
| `frontend/src/api/products.js` | 修改（新增方法） |
| `frontend/src/stores/products.js` | 修改（新增轮询） |
| `frontend/src/components/ProductCard.vue` | 修改（UI 交互） |
