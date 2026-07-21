# 代码优化回归测试 — 设计文档

## 背景

完成了 7 项代码优化，涉及 10 个文件。需要编写回归测试确保优化不引入 bug。

## 测试范围

仅后端测试（pytest），前端无测试基础设施（无 Vitest/Jest），跳过。

### 已存在但应修复的测试问题

**问题**：13 个测试因 `sales_person` 列不存在而失败。
**原因**：测试用临时空数据库，`_ensure_schema` 未执行 `_add_column_if_missing` 添加该列。
**修复**：在 `_ensure_schema` 末尾补充 `sales_person` + `agency_ratio` 的列检测（目前只在 `add_product`/`update_product` 中写入，但 schema 创建时未显式添加）。

## 新增测试用例

### 1. `_scope_where()` 函数 (test_helpers.py)

| 用例 | 输入 | 期望输出 |
|------|------|----------|
| scope=public | `("public", 1, "v")` | `("v.is_public = 1", [])` |
| scope=private | `("private", 1, "v")` | `("v.owner_id = ?", [1])` |
| scope=all | `("all", 1, "v")` | `("(v.is_public = 1 OR v.owner_id = ?)", [1])` |
| 无 alias | `("public", 5)` | `("is_public = 1", [])` |
| 不同 alias | `("private", 3, "cw")` | `("cw.owner_id = ?", [3])` |

### 2. `_can_modify()` 函数 (test_helpers.py)

| 用例 | 场景 | 期望 |
|------|------|------|
| admin 始终可修改 | developer role | `(True, None)` |
| 资源所有者 | owner_id == user_id | `(True, None)` |
| 公开资源 | is_public=1, 非 owner | `(True, None)` |
| 无权限 | 非 owner, 非公开 | `(False, "无权限...")` |
| 记录不存在 | id 不存在 | `(False, "记录不存在")` |

### 3. `_reject_viewer()` 函数 (test_decorators.py)

| 用例 | 场景 | 期望 |
|------|------|------|
| viewer 被拒绝 | role=viewer | `(json, 403)` |
| admin 通过 | role=admin | `None` |
| user 通过 | role=user | `None` |
| 未登录 | 无 JWT | `None` (由 @jwt_required 处理) |

### 4. `_refresh_jwt` 钩子 — JWT 滑动过期 (test_auth.py)

| 用例 | 场景 | 期望 |
|------|------|------|
| 受保护路由返回新 token | GET /api/auth/me with valid JWT | `X-New-Access-Token` header 存在 |
| 登录路由不返回新 token | POST /api/auth/login (无 JWT) | 无 `X-New-Access-Token` |
| 公开路由不返回新 token | GET /favicon.ico | 无 `X-New-Access-Token` |
| 新 token 和旧 token 都有效 | 用新旧 token 分别请求 | 都是 200 |
| 401 错误不生成 token | 无 token 访问受保护路由 | 无 `X-New-Access-Token` |

### 5. `_reject_viewer` 集成测试 (test_auth.py)

| 用例 | 场景 | 期望 |
|------|------|------|
| viewer 无法创建产品 | role=viewer POST /api/products | 403 |
| viewer 可以查看产品 | role=viewer GET /api/products | 200 |

## 不测试的项目

| 项目 | 原因 |
|------|------|
| 前端 dedupLoader | 无前端测试基础设施 |
| 前端 loadSettings 防重复 | 同上 |
| 前端 MCC 悬停复制 | 同上 |
| scraper User-Agent 常量 | 值为静态字符串，风险极低 |
| 多余 import 清理 | 无行为变化 |

## 涉及文件

- 新增：`py/tests/test_helpers.py` — _scope_where、_can_modify
- 新增：`py/tests/test_auth.py` — JWT 滑动过期、_reject_viewer 集成
- 新增：`py/tests/test_decorators.py` — reject_viewer 单元测试
- 修复：`py/database.py` — _ensure_schema 添加 sales_person 列迁移

## 运行命令

```bash
cd py && python -m pytest tests/ -v
```
