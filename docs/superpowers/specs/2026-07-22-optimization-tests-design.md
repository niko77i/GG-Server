# 代码优化回归测试 — 设计文档

## 背景

完成了 7 项代码优化，涉及 10 个文件。需要编写回归测试确保优化不引入 bug。

## 测试范围

仅后端测试（pytest），前端无测试基础设施（无 Vitest/Jest），跳过。

### 已存在但应修复的测试问题

**问题**：13 个测试因 `sales_person` 列不存在而失败。
**原因**：测试用临时空数据库，`_ensure_schema` 未执行 `_add_column_if_missing` 添加该列。
**修复**：在 `_ensure_schema` 末尾补充 `sales_person` + `agency_ratio` 的列检测（目前只在 `add_product`/`update_product` 中写入，但 schema 创建时未显式添加）。

**现状（已修复）**：`database.py` 中 `_ensure_columns()` 函数（第 100-118 行）已在每次连接时调用 `_add_column_if_missing(conn, "products", "sales_person", ...)` 和 `_add_column_if_missing(conn, "products", "agency_ratio", ...)`，因此临时空数据库也能自动创建这两个列，测试不再因此失败。

---

## 测试文件总览

实际 `py/tests/` 目录下共有 **10 个测试文件 + 1 个 fixture 文件**（不包括 `__pycache__`）：

| 文件 | 状态 | 说明 |
|------|------|------|
| `conftest.py` | **已有** | pytest fixture：`app`（Flask 测试应用+临时 DB）、`client`（测试客户端）、`auth_headers`（JWT 认证头） |
| `test_helpers.py` | **本次新增** | `_scope_where`、`can_modify`、`MCC_CHANGE_TYPE_LABELS` 常量测试 |
| `test_decorators.py` | **本次新增** | `reject_viewer` 单元测试 |
| `test_auth.py` | **本次新增** | JWT 滑动过期 + `_reject_viewer` 集成测试 + Auth Blueprint 路由验证 |
| `test_ad_reports.py` | 已有 | 做表数据保存/列表/分析/导出/删除/搜索等 |
| `test_product_assets.py` | 已有 | 成效素材关联、映射查询 |
| `test_regions.py` | 已有 | 地区时区 CRUD |
| `test_delist_checker.py` | 已有 | 掉包检测逻辑（URL 检查、批量检测） |
| `test_delist_api.py` | 已有 | 掉包 API（TestDismissDelist 可用；其余测试因依赖 mock HTTP 已整体注释） |
| `test_email_sender.py` | 已有 | SMTP 邮件发送、收件人邮箱获取 |
| `test_video_consumption.py` | 已有 | 消耗记录 CRUD、批量可见性编辑、日期标注、视频列表含消耗字段 |

**注意**：`__pycache__` 目录下有个 `test_delist_api.cpython-311-pytest-9.1.1.pyc` 缓存文件，对应已存在的 `test_delist_api.py`。

---

## 新增测试用例（本次优化回归测试）

### 1. `scope_where()` 函数 — `test_helpers.py` / `TestScopeWhere`

| 用例 | 输入 | 期望输出 |
|------|------|----------|
| scope=public 带 alias | `("public", 1, "v")` | `("v.is_public = 1", [])` |
| scope=private 带 alias | `("private", 1, "v")` | `("v.owner_id = ?", [1])` |
| scope=all 带 alias | `("all", 1, "v")` | `("(v.is_public = 1 OR v.owner_id = ?)", [1])` |
| scope=public 无 alias | `("public", 5)` | `("is_public = 1", [])` |
| scope=private 不同 alias | `("private", 3, "cw")` | `("cw.owner_id = ?", [3])` |
| scope=private user_id=42 | `("private", 42, "t")` | `("t.owner_id = ?", [42])` |

### 2. `can_modify()` 函数 — `test_helpers.py` / `TestCanModify`

| 用例 | 场景 | 期望 |
|------|------|------|
| admin 始终可修改 | developer role + 非 owner | `(True, None)` |
| admin 角色可修改 | admin role + 非 owner | `(True, None)` |
| 资源所有者 | owner_id == user_id | `(True, None)` |
| 公开资源 | is_public=1, 非 owner | `(True, None)` |
| 无权限 | 非 owner, 非公开 | `(False, "无权限...")` |
| 记录不存在 | id 不存在 | `(False, "不存在")` |

**注意**：测试使用 monkeypatch 注入 `auth.get_user_by_id`，数据库使用 SQLite `:memory:` 模式，自定义 `db` fixture 创建临时表 `videos(id, owner_id, is_public)`。

### 3. `MCC_CHANGE_TYPE_LABELS` 常量 — `test_helpers.py` / `TestMccChangeLabels`

| 用例 | 期望 |
|------|------|
| 所有键值验证 | `manual`→`"手动编辑"`, `batch`→`"批量修改"`, `reassign`→`"认领转移"`, `import`→`"批量导入"`, `create`→`"新建账户"` |

### 4. `reject_viewer()` 单元测试 — `test_decorators.py` / `TestRejectViewer`

| 用例 | 场景 | 期望 |
|------|------|------|
| viewer 被拒绝 | role=viewer | `(json, 403)` |
| admin 通过 | role=admin | `None` |
| user 通过 | role=user | `None` |
| developer 通过 | role=developer | `None` |
| 无 JWT（get_jwt_identity 抛异常） | monkeypatch 模拟异常 | `None`（由 `@jwt_required` 拦截处理） |

**注意**：使用独立 Flask 测试应用 `viewer_app` fixture（非 conftest 的 client/app），通过 `test_request_context` 模拟请求上下文，`get_jwt_identity` 和 `get_user_by_id` 均通过 monkeypatch 注入。

### 5. JWT 滑动过期 — `test_auth.py` / `TestJwtSliding`

| 用例 | 场景 | 期望 |
|------|------|------|
| 受保护路由返回新 token | GET /api/auth/me with valid JWT | `X-New-Access-Token` header 存在且长度 > 20 |
| 登录路由不返回新 token | POST /api/auth/login（无 JWT） | 无 `X-New-Access-Token` |
| 公开路由不返回新 token | GET /favicon.ico | 无 `X-New-Access-Token`，状态码 204 |
| 新 token 和旧 token 都有效 | 用新旧 token 分别请求 /api/auth/me | 均为 200 |
| 401 错误不生成 token | 无 token 访问 /api/auth/me | 401，无 `X-New-Access-Token` |
| 每次请求 token 不同 | 连续两次请求 /api/auth/me | 两次返回的 `X-New-Access-Token` 值不同（滑动过期轮换） |

### 6. `reject_viewer` 集成测试 — `test_auth.py` / `TestRejectViewerIntegration`

| 用例 | 场景 | 期望 |
|------|------|------|
| viewer 可以查看个人信息 | role=viewer GET /api/auth/me | 200 |
| viewer 无法创建产品 | role=viewer POST /api/products/create | 403 |

**注意**：`viewer_headers` fixture 先注册用户，再通过 `database.get_db()` 直接 `UPDATE users SET role='viewer'` 绕过角色修改权限限制。

### 7. Auth Blueprint 路由验证 — `test_auth.py` / `TestAuthBlueprint`

| 用例 | 场景 | 期望 |
|------|------|------|
| 登录通过 Blueprint | POST /api/auth/login | 200, `success=True`, 含 `access_token` |
| 获取用户信息通过 Blueprint | GET /api/auth/me | 200, `success=True` |
| 刷新 token 通过 Blueprint | POST /api/auth/refresh（用 refresh_token） | 200, 含新 `access_token` |

---

## 已有测试（非本次新增，已存在于仓库中）

### 8. 做表数据 API — `test_ad_reports.py`

共 **18 个 Test Class**，覆盖以下接口：

| Test Class | 接口 | 用例数 |
|------------|------|--------|
| `TestAdReportsSave` | POST /api/ad-reports/save | 7 |
| `TestAdReportsCheckDuplicates` | POST /api/ad-reports/check-duplicates | 2 |
| `TestAdReportsList` | GET /api/ad-reports/list | 2 |
| `TestAdReportsDelete` | DELETE /api/ad-reports/<id> | 1 |
| `TestAdReportsDashboard` | GET /api/ad-reports/dashboard | 2 |
| `TestAdReportsTrends` | GET /api/ad-reports/trends | 1 |
| `TestAdReportsCompare` | GET /api/ad-reports/compare | 1 |
| `TestAdReportsCrossUser` | GET /api/ad-reports/cross-user | 2 |
| `TestAdReportsProducts` | GET /api/ad-reports/products | 1 |
| `TestAdReportsAnalyze` | POST /api/ad-reports/analyze | 1（AI 默认禁用） |
| `TestAdReportsMultiAnalysis` | GET /api/ad-reports/multi-analysis | 8 |
| `TestAdReportsMultiAiChat` | POST /api/ad-reports/multi-ai-chat | 1（AI 默认禁用） |
| `TestAdReportsUpdate` | PUT /api/ad-reports/<id> | 3 |
| `TestAdReportsBatchDelete` | POST /api/ad-reports/batch-delete | 2 |
| `TestAdReportsExport` | GET /api/ad-reports/export | 1 |
| `TestAdReportsListSearch` | GET /api/ad-reports/list（搜索） | 2 |

**关键测试覆盖**：
- 保存时同维度聚合并 SUM 数值（`test_save_aggregates_same_dimension_rows`、`aggregated_from` 字段）
- upsert 累加到已有记录（`test_save_upsert_accumulates_on_existing`）
- override_ids 覆盖已有行（`test_save_with_override`）
- 多维分析按 account/campaign 分组，验证 stats（均值/中位数/相关系数）、insights、size_by 气泡大小
- CSV 导出含 BOM 的 UTF-8（`text/csv; charset=utf-8-sig`）

### 9. 成效素材 API — `test_product_assets.py`

共 **4 个 Test Class**：

| Test Class | 接口 | 用例数 |
|------------|------|--------|
| `TestProductAssetsList` | GET /api/products/<pid>/assets | 1 |
| `TestProductAssetsAdd` | POST /api/products/<pid>/assets | 2 |
| `TestProductAssetsDelete` | DELETE /api/products/<pid>/assets/<vid> | 1 |
| `TestProductAssetsMapping` | GET /api/youtube/product-assets | 2 |

**注意**：Add/Delete/Mapping 测试依赖前一个测试创建的产品，若产品不存在则通过 `return` 跳过（非 `assert` 失败）。

### 10. 地区时区管理 API — `test_regions.py`

共 **4 个 Test Class**：

| Test Class | 接口 | 用例数 |
|------------|------|--------|
| `TestRegionsList` | GET /api/regions/list | 2 |
| `TestRegionsUpdate` | PUT /api/regions/<id> | 2 |
| `TestRegionsCreate` | POST /api/regions/create | 2 |
| `TestRegionsDelete` | DELETE /api/regions/<id> | 1 |

**关键验证**：预设时区默认值（巴西=UTC-3、菲律宾=UTC+8、印尼=UTC+7）；空名称创建返回 400。

### 11. 掉包检测模块 — `test_delist_checker.py`

共 **2 个 Test Class**（纯单元测试，无 Flask client）：

| Test Class | 被测函数 | 用例数 |
|------------|----------|--------|
| `TestCheckUrlDelisted` | `check_url_delisted(url)` | 8 |
| `TestCheckProductPackages` | `check_product_packages(product_id, packages)` | 3 |

**关键覆盖**：404 判定掉包、英文/中文"not found"文本判定掉包、正常页面判定未掉包、超时/连接错误/通用异常均返回 `(False, error)`、空 URL 直接返回 `(False, "")`、验证 User-Agent 长度 > 10、空 URL 的包跳过 HTTP 请求、单个包出错不影响其他包继续检测。

**Mock 方式**：`unittest.mock.patch("delist_checker.requests.get")`，不依赖真实网络。

### 12. 掉包检测 API — `test_delist_api.py`

- **可用测试**：`TestDismissDelist` — `test_records_dismissal`、`test_requires_auth`（2 个）
- **已注释测试**（约 10 个，分布在 `TestManualCheckDelist` / `TestDelistStatus` / `TestPendingDelist`）：因依赖 `unittest.mock.patch` 模拟 HTTP 请求，与 Flask test client 的集成存在时序/隔离问题，已整体注释。注释代码保留作为参考，待后续改进测试基础设施后恢复。

### 13. 邮件发送模块 — `test_email_sender.py`

共 **2 个 Test Class**（纯单元测试，无 Flask client）：

| Test Class | 被测函数 | 用例数 |
|------------|----------|--------|
| `TestSendDelistEmail` | `send_delist_notification(config, emails, pkg_info)` | 5 |
| `TestGetRunnerEmails` | `get_runner_emails(db, user_ids)` | 2 |

**关键覆盖**：单/多收件人发送、SMTP 连接失败返回 False 不抛异常、空收件人列表直接返回 False 不发邮件、使用 SMTP_SSL 协议、空邮箱/NULL 邮箱被过滤、无 runner 时返回空列表且不执行 SQL。

**Mock 方式**：`unittest.mock.patch("email_sender.smtplib.SMTP_SSL")`，`MagicMock` 模拟数据库连接。

### 14. 视频消耗追踪 API — `test_video_consumption.py`

共 **8 个 Test Class**：

| Test Class | 接口 | 用例数 |
|------------|------|--------|
| `TestBatchEditIsPublic` | POST /api/youtube/batch-edit | 4 |
| `TestConsumptionCreate` | POST /api/youtube/<vid>/consumption | 4 |
| `TestConsumptionRead` | GET /api/youtube/<vid>/consumption | 3 |
| `TestConsumptionUpdate` | PUT /api/youtube/<vid>/consumption/<cid> | 2 |
| `TestConsumptionDelete` | DELETE /api/youtube/<vid>/consumption/<cid> | 2 |
| `TestConsumptionDates` | GET /api/youtube/consumption/dates | 1 |
| `TestConsumptionVideoList` | 视频列表含 total_consumption | 1 |
| `TestRunnerProducts` | GET /api/products/runner-products | 1 |

**关键覆盖**：
- 批量可见性：admin 改自己视频（公开/私有）、admin 不能改别人视频、普通用户可改自己视频（`owner_id` 匹配）
- 消耗记录权限：admin 可新增/编辑/删除自己记录、普通用户无法新增（403）、viewer 无法新增（403）、不能编辑/删除他人记录（403）
- 消耗明细：sum 总金额、按用户分组、viewer 可读、空记录返回 total=0
- 辅助函数 `_register_and_login` / `_import_video` / `_create_product` 封装了重复的注册-登录-导入逻辑

---

## conftest.py — 共享夹具

| Fixture | 作用 |
|---------|------|
| `app` | 创建临时 `.db` 文件，替换 `database._db_path` 指向临时路径，配置 `TESTING=True` 和 `JWT_SECRET_KEY`，yield 后清理临时文件并恢复原路径 |
| `client` | 调用 `app.test_client()` 返回 Flask 测试客户端 |
| `auth_headers` | 注册 `testuser` + 登录，返回 `{"Authorization": "Bearer <token>"}` dict |

**注意**：`app` fixture 通过 monkey-patch `database._db_path` 实现临时数据库隔离。每次测试有独立的 SQLite 文件，测试结束后删除。`_ensure_columns()` 在首次 `get_db()` 时自动执行列迁移，故 `sales_person` 等列可正常工作。

---

## 不测试的项目

| 项目 | 原因 |
|------|------|
| 前端 dedupLoader | 无前端测试基础设施 |
| 前端 loadSettings 防重复 | 同上 |
| 前端 MCC 悬停复制 | 同上 |
| scraper User-Agent 常量 | 值为静态字符串，风险极低 |
| 多余 import 清理 | 无行为变化 |

---

## 涉及文件

- **测试 fixture**：`py/tests/conftest.py` — Flask 测试应用 + 临时 DB + JWT 认证头（已有）
- **新增**：`py/tests/test_helpers.py` — `scope_where`、`can_modify`、`MCC_CHANGE_TYPE_LABELS`
- **新增**：`py/tests/test_auth.py` — JWT 滑动过期、`reject_viewer` 集成、Auth Blueprint 路由验证
- **新增**：`py/tests/test_decorators.py` — `reject_viewer` 单元测试
- **已有**：`py/tests/test_ad_reports.py` — 做表数据 API（18 类，约 37 个用例）
- **已有**：`py/tests/test_product_assets.py` — 成效素材 API（4 类，6 个用例）
- **已有**：`py/tests/test_regions.py` — 地区时区 API（4 类，7 个用例）
- **已有**：`py/tests/test_delist_checker.py` — 掉包检测逻辑（2 类，11 个用例）
- **已有**：`py/tests/test_delist_api.py` — 掉包 API（2 个可用用例，其余已注释）
- **已有**：`py/tests/test_email_sender.py` — 邮件发送（2 类，7 个用例）
- **已有**：`py/tests/test_video_consumption.py` — 视频消耗追踪（8 类，18 个用例）
- **修复**：`py/database.py` — `_ensure_columns()` 每次连接时执行 `_add_column_if_missing` 添加 `sales_person`/`agency_ratio` 列（已修复）

---

## 测试总数统计

| 类别 | 文件数 | Test Class 数 | 用例数（约） |
|------|--------|---------------|-------------|
| 本次新增 | 3 | 7 | 27 |
| 已有测试 | 7 | 42 | 88 |
| **合计** | **10** | **49** | **115** |

---

## 运行命令

```bash
cd py && python -m pytest tests/ -v
```
