# Google Ads API 直连 — 独立页面方案

## Context

用户目前手动从 Google Ads 后台下载 Excel/CSV 报告，然后粘贴到做表工具解析。希望直接对接 Google Ads API 自动拉取数据，省去手动下载步骤。

## 前端条件（用户需在 Google 后台完成）

Google Ads API 需要以下凭据，已全部获取：

- **Google Cloud 项目** — `golden-hologram-499109-d8`
- **OAuth 2.0 凭据** — Web 应用类型，重定向 URI `https://developers.google.com/oauthplayground`
- **开发者令牌** — 基本访问权限
- **刷新令牌** — 通过 OAuth Playground 获取
- **经理账户 ID** — `230-247-9968`（下有子账户 `208-320-2792`）

## 架构

独立页面 `google-ads.html` + 后端 API 路由，与主项目物理隔离：

- `google-ads.html` — 独立的 Google Ads 报告页面
- `py/google_ads_service.py` — Google Ads API 客户端封装
- `py/main.py` — 新增 API 路由
- `requirements.txt` — 添加 `google-ads` 库

**访问方式**：`http://localhost:5000/google-ads.html`

## 不涉及

- 不改动 index.html 任何代码
- 不改动 js/、css/ 任何文件
- 不打包进 EXE（除非用户明确要求）
- 不影响主项目任何功能

## 页面功能

1. 凭据配置区（已预填，可修改）
2. 选择账号 + 日期范围
3. 拉取广告系列级别报告（费用、展示、点击、点击率、转化）
4. 表格展示结果
5. 一键复制 / 导出 Excel

## 新增 API

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/google-ads/accounts` | 获取子账户列表 |
| POST | `/api/google-ads/report` | 拉取报告 |

## 验证

1. 启动 `python main.py`
2. 浏览器打开 `http://localhost:5000/google-ads.html`
3. 选择账号 + 日期，点拉取报告
4. 确认数据显示正常

---

## 审计补充（2026-07-23）

本章节对比设计文档（本文）与当前代码实际实现（`py/google_ads_service.py`、`py/main.py`），记录偏差、缺口和额外实现的细节。

### 审计范围

- **设计文档版本**: 本文（无版本号，推测为初始设计）
- **代码审计点**: `py/google_ads_service.py`（完整）、`py/main.py` L5387-L5448（Google Ads API 路由段）、`requirements.txt`、全项目 HTML/JS 前端文件搜索
- **审计日期**: 2026-07-23
- **审计结论**: 后端基本实现，**前端页面完全缺失**

### 1. 前端页面 — 完全缺失（阻塞级）

**设计文档声明**: 独立页面 `google-ads.html`，包含凭据配置区、账号选择、日期范围、报告表格、导出功能。通过 `http://localhost:5000/google-ads.html` 访问。

**实际情况**: `google-ads.html` 文件**不存在于项目任何位置**。全项目 glob 搜索 `**/*google*ads*` 和 `**/*google-ads*` 均未命中任何 HTML/JS/Vue 文件。前端 `frontend/src/views/` 下的 Vue 文件中出现的 `google_ads` 仅为目录路径占位符示例，与此功能无关。

**影响**: 终端用户无法以任何方式使用 Google Ads 功能——后端 API 虽然就绪，但没有前端界面来触发调用。

**建议**: 如下任选其一：
- 选项 A：按设计文档补建 `google-ads.html`，放置在 `dist/` 静态文件目录下，与 Flask 静态文件服务对齐。
- 选项 B：在 `frontend/src/views/` 下新建 Vue 组件 `GoogleAdsView.vue`，与现有前端架构统一。

### 2. 设计文档声明的 5 项页面功能 — 均未实现

| 设计功能 | 状态 |
|----------|------|
| 凭据配置区（预填，可修改） | 未实现（无前端页面） |
| 选择账号 + 日期范围 | 未实现（无前端页面） |
| 拉取广告系列级别报告 | 未实现（无前端页面） |
| 表格展示结果 | 未实现（无前端页面） |
| 一键复制 / 导出 Excel | 未实现（无前端页面） |

### 3. 后端 API — 已实现，存在设计文档未覆盖的细节

#### 3.1 路由已实现

| 方法 | 路径 | 设计文档 | 实际代码 |
|------|------|----------|----------|
| POST | `/api/google-ads/accounts` | 声明 | 已实现（L5401） |
| POST | `/api/google-ads/report` | 声明 | 已实现（L5422） |

#### 3.2 凭据管理 — 实现超出设计

**设计文档**: 凭据在页面中预填、可修改（隐含前端直传凭据给后端）。

**实际实现**（`main.py` L5391-L5398）:
- 后端通过环境变量 `GOOGLE_ADS_CLIENT_ID`、`GOOGLE_ADS_CLIENT_SECRET`、`GOOGLE_ADS_REFRESH_TOKEN`、`GOOGLE_ADS_DEVELOPER_TOKEN`、`GOOGLE_ADS_MANAGER_ID` 提供默认凭据。
- 路由中通过 `{**_GOOGLE_ADS_CONFIG, **data}` 合并，请求体中的字段可覆盖环境变量默认值。
- 这种"环境变量默认 + 请求覆盖"的混合策略在设计文档中未描述，但比纯前端传凭据更安全（令牌不暴露到浏览器本地存储）。

**建议**: 更新设计文档，记录凭据配置的两级覆盖策略。

#### 3.3 PyInstaller 排除策略 — 实现超出设计

**设计文档**: "不打包进 EXE（除非用户明确要求）"。

**实际实现**（`main.py` L5405-L5407、L5426-L5428）:
- `google_ads_service` 在路由函数内部按需 `import`，而非文件顶部全局导入。
- 若 `ImportError`（打包后 `google-ads` 库不可用），返回 `{"success": false, "error": "Google Ads 功能仅在开发模式可用"}` 及 HTTP 500。
- `main.py` L40 行注释明确标注："`google_ads_service` 按需加载，不打包进 EXE"。

**建议**: 设计文档补充说明按需导入机制和打包模式下的降级行为。

#### 3.4 参数验证 — 实现超出设计

**设计文档**: 未提及输入验证。

**实际实现**（`main.py` L5431-L5437）:
- `account_id` 为空 → 400 错误 "请选择账号"
- `start_date` 或 `end_date` 为空 → 400 错误 "请选择日期范围"
- 所有其他异常被 `except GoogleAdsServiceError` 和 `except Exception` 两级 catch 覆盖

### 4. `google_ads_service.py` — 实现超出设计

#### 4.1 设计文档未提及的内容

| 实现细节 | 说明 |
|----------|------|
| GAQL 查询模板 `_GAQL_CAMPAIGN_REPORT` | 查询 campaign/customer 维度的 cost_micros、impressions、clicks、ctr、conversions、cost_per_conversion |
| API 版本 v24 | 注释注明使用 v24 字段定义 |
| `GoogleAdsServiceError` 自定义异常 | 包装 `GoogleAdsException`，提供统一错误处理 |
| `login_customer_id` 中 `-` 字符自动清理 | `_build_client()` 中 `login_customer_id.replace("-", "")` |
| `account_id` 中 `-` 字符自动清理 | `fetch_campaign_report()` 中 `customer_id=account_id.replace("-", "")` |
| 微元（micros）转元 | `cost_micros / 1_000_000` 和 `cost_per_conversion / 1_000_000` |
| CTR 百分比转换 | `ctr * 100`（GAQL 返回小数，前端通常需要百分比） |
| 空值保护 | 每个字段都有 `if metrics.xxx else 0.0` 的 None 保护 |

#### 4.2 `list_accounts` 返回格式差异

**设计文档**: 未定义返回格式。

**实际实现**: 返回 `list[str]`（纯账号 ID 字符串列表，如 `["2083202792", ...]`），从 `customers/2083202792` 格式中提取纯数字。此细节需要在 API 文档/前后端协约中明确。

#### 4.3 `fetch_campaign_report` 返回格式

**设计文档**: 未定义返回格式。

**实际实现**: 返回 `list[dict]`，每个 dict 包含 `campaign_id`、`campaign_name`、`customer_id`、`customer_name`、`cost`、`impressions`、`clicks`、`ctr`、`conversions`、`cpa` 共 10 个字段。所有数值已在前端可直接使用的格式（元、百分比）。

### 5. `requirements.txt` — 已实现

设计文档声明添加 `google-ads` 库。实际 `requirements.txt` 中第 8 行包含：

```
google-ads>=24.0
```

与 `py/google_ads_service.py` 注释中的 API v24 版本一致。

### 6. "不涉及"项 — 全部满足

| 约束 | 状态 |
|------|------|
| 不改动 `index.html` 任何代码 | 满足 |
| 不改动 `js/`、`css/` 任何文件 | 满足 |
| 不打包进 EXE | 满足（按需导入 + ImportError 降级） |
| 不影响主项目任何功能 | 满足（独立路由，无侵入修改） |

### 7. 审计总结

| 维度 | 设计文档 | 实际代码 | 评估 |
|------|----------|----------|------|
| 后端 API 路由 | 2 个端点 | 2 个端点已实现 | 匹配 |
| 后端服务模块 | `google_ads_service.py` | 完整实现 + 额外健壮性 | **代码超出设计** |
| 前端页面 | `google-ads.html` | **不存在** | **阻塞级缺口** |
| 依赖管理 | `requirements.txt` 加 `google-ads` | 已添加 `google-ads>=24.0` | 匹配 |
| 打包排除 | 声明不打包 | 通过按需导入实现 | **实现超出设计** |
| 错误处理 | 未描述 | 三级异常处理 + 参数验证 | **实现超出设计** |

**结论**: 后端 API 完全就绪且健壮性超出设计预期，但前端页面完全缺失导致功能对终端用户不可用。建议下一步优先补齐前端页面（`google-ads.html` 或 Vue 组件），并将本文档中的实现细节（凭据覆盖策略、错误处理、返回字段格式、API 版本）同步到设计文档中。
