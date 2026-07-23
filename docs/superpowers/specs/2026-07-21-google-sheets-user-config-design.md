# Google Sheets 用户配置页面 — 设计文档

## 需求描述

1. **配置页面**：让每个用户保存自己的 Google 在线表格 ID
2. **用户隔离**：每个用户有自己的表格配置，互不干扰
3. **与做表数据关联**：表格列与 ToolkitView「做表数据」字段有固定映射关系

用户提供的示例表格：
- URL: `https://docs.google.com/spreadsheets/d/13b-KX2LNisoVwO0s3fT0RqzIyu_Ngy-AgDQRqV1AsQY/edit?gid=0#gid=0`
- 列映射：`账号名称→账号` / `广告账户id→客户ID` / `账号消耗→费用` / `渠道号→广告系列`

## 技术方案

### 存储方案

遵循项目现有的 `config` 表 key-prefix 模式（参照 `ai_analysis_{user_id}`），使用 key `google_sheets_{user_id}`，value 为 JSON 字符串。

### 存储数据结构

```json
{
  "spreadsheet_id": "13b-KX2LNisoVwO0s3fT0RqzIyu_Ngy-AgDQRqV1AsQY",
  "spreadsheet_name": "",
  "sheet_gid": "0"
}
```

### 列映射（固定，仅供参考）

| Google Sheets 列 | 做表数据字段 | 说明 |
|---|---|---|
| A: 账号名称 | account（账号） | 广告账户名称 |
| B: 广告账户id | customerId（客户ID） | xxx-xxx-xxxx 格式 |
| C: 账号消耗 | cost（费用） | 美金金额 |
| D: 渠道号 | campaign（广告系列） | 广告系列名称 |

## 涉及的文件

| 文件 | 操作 | 说明 |
|------|------|------|
| `py/main.py` | 修改 | 新增 `GET/POST /api/config/google-sheets` 路由 |
| `frontend/src/api/google-sheets.js` | 修改 | 新增 `getConfig()` / `saveConfig()` 方法 |
| `frontend/src/views/UserProfileView.vue` | 修改 | 新增「Google Sheets 配置」卡片 |

## 后端 API

### GET /api/config/google-sheets
- 认证：`@jwt_required()`
- 返回当前用户的 Google Sheets 配置 JSON
- 用户级未配置时回退到 `config.json` 中的全局 `spreadsheet_id`

### POST /api/config/google-sheets
- 认证：`@jwt_required()`
- 接收 `{ spreadsheet_id, spreadsheet_name, sheet_gid }`
- 写入 `config` 表 key=`google_sheets_{user_id}`

## 前端 UI

在 `UserProfileView.vue` 中新增 `el-card`：
- 表格网址/ID 输入（支持粘贴完整 URL 自动提取）
- 表格名称输入
- 列映射参考表（小号字体）
- 保存按钮

## 扩展预留

后续可在以下位置扩展：
- `py/google_sheets_service.py`：新增 `read_range()`/`write_range()` 从用户配置读取 sheet ID
- `py/main.py`：新增数据同步路由
- `frontend/src/views/ToolkitView.vue`：新增「同步到 Google Sheets」按钮

---

## 实际代码逻辑补充（2026-07-23 审计）

> **审计结论**：设计文档与最终实现存在显著差异。主要方向是对的（用户级配置存储、URL 自动提取），但实际实现远比设计文档描述的更丰富——支持多表格、后台异步同步、同步失败日志、重试机制等。同时有若干设计文档中描述的功能并未按预期落地。

### 一、数据结构差异（显著变化）

| 项目 | 设计文档 | 实际实现 |
|---|---|---|
| 存储格式 | 单对象 `{spreadsheet_id, spreadsheet_name, sheet_gid}` | **数组** `[{id, spreadsheet_id, spreadsheet_name, sheet_gid}, ...]` |
| 配置键 | `google_sheets_{user_id}` | 两张表：`google_sheets_{user_id}`（数组）+ `google_sheets_active_{user_id}`（激活标记） |
| 表格数量 | 每个用户一个表格 | 每个用户支持**多个表格**，可增删改，通过 radio 激活一个 |

### 二、API 路由：从 2 个扩展到 7 个

设计文档只定义了 `GET/POST /api/config/google-sheets`。实际实现了以下全部路由：

| 路由 | 方法 | 说明 | 是否在设计文档中 |
|---|---|---|---|
| `/api/config/google-sheets` | GET | 获取当前用户的多表格列表 + active_id | 是 |
| `/api/config/google-sheets` | POST | 保存当前用户的多表格列表 + active_id | 是 |
| `/api/google-sheets/update-zuobiao` | POST | 将做表数据写入 Sheets（后台异步线程） | **否** |
| `/api/google-sheets/sync-status` | GET | 查询指定产品 Sheets 同步失败日志 | **否** |
| `/api/google-sheets/retry-sync` | POST | 手动重试失败的 Sheets 同步 | **否** |
| `/api/google-sheets/status` | GET | 检查服务账号配置状态（client_email 等） | **否** |
| `/api/settings/account` | GET/POST | 系统级设置（含管理员 recharge_sheet_id，存 `tags` 表） | **否** |

### 三、认证方式：OAuth 流程 vs Service Account

**设计文档未提及认证方式。** 实际实现：

- **没有 OAuth Web 授权流程**。在 `main.py` 中搜索 `oauth`、`google_auth`、`token_uri` 均无匹配。
- 使用 **Service Account（服务账号）** 进行服务器到服务器的认证。
- 服务账号凭据文件：`config/fit-boulevard-503111-u4-812bc02c2000.json`（类型为 `service_account`），由 `google_sheets_service.py` 中的 `_get_credentials()` 通过 `google.oauth2.service_account.Credentials.from_service_account_file()` 加载。
- `config/google_sheets_credentials.json` 是一个 **OAuth 客户端凭据文件**（类型为 `installed`，含 `client_secret`、`redirect_uris`），但**代码中完全未使用此文件**，属于冗余遗留文件。

### 四、凭据路径解析

实际路径解析优先级（`main.py` 第 5454-5460 行）：

1. 环境变量 `GOOGLE_SHEETS_CREDENTIALS_PATH`（最高优先级）
2. 硬编码默认路径：`{项目根}/config/fit-boulevard-503111-u4-812bc02c2000.json`

**注意**：`config.json` 中的 `google_sheets.credentials_path` 字段**并未被读取**，`_GOOGLE_SHEETS_CONFIG` 字典直接使用环境变量和硬编码路径。这意味着若需更换凭据文件，只能通过环境变量，修改 `config.json` 无效。

### 五、全局 spreadsheet_id 回退：设计有，实际未落地

设计文档描述：「用户级未配置时回退到 `config.json` 中的全局 `spreadsheet_id`」。

实际代码（`main.py` 第 4693 行）确实引用了 `_GOOGLE_SHEETS_CONFIG.get("spreadsheet_id", "")`，但：
- `_GOOGLE_SHEETS_CONFIG` 字典（第 5454 行）**只包含 `credentials_path` 一个键**。
- `spreadsheet_id` 从未被写入该字典。
- `config.json` 中的 `google_sheets` 配置段也只有 `credentials_path`，没有 `spreadsheet_id`。
- 因此，全局回退逻辑**永远返回空字符串**，等于无效代码。若用户未配置任何表格，做表数据同步会直接报错 "请先在个人中心配置 Google 表格"。

### 六、URL 自动提取：三处独立实现

设计文档要求"支持粘贴完整 URL 自动提取"。实际有三处**各自实现**的 URL 解析逻辑（不一致的风险点）：

| 位置 | 函数 | 提取能力 |
|---|---|---|
| 前端 `UserProfileView.vue` | `parseSheetsUrl()` | 提取 spreadsheet_id **和** gid（正则 `[?&#]gid=(\d+)`） |
| 前端 `SettingsPanel.vue` | 内联正则 | 仅提取 spreadsheet_id（正则 `spreadsheets\/d\/([a-zA-Z0-9_-]+)`） |
| 后端 `main.py` | `_parse_sheet_id()` | 仅提取 spreadsheet_id（正则 `r"/d/([a-zA-Z0-9_-]+)"`） |

### 七、做表数据列映射：从 4 列扩展到 14 列

设计文档定义了 4 列映射（A=账号名称→账号, B=广告账户id→客户ID, C=账号消耗→费用, D=渠道号→广告系列）。

实际 `upsert_zuobiao()` 写入 **A-N 共 14 列**，且包含公式：

| 列 | 内容 | 公式 |
|---|---|---|
| A | report_date | — |
| B | operator_name（从表格标题解析） | — |
| C | account（账号） | — |
| D | customer_id（客户ID） | — |
| E | cost（费用） | — |
| F | （空列） | — |
| G | product_name / "养户" | — |
| H | sales_person / "止戈" | — |
| I | region | — |
| J | campaign（广告系列） | — |
| K | （空列） | — |
| L | agency_ratio / "0%"（养户） | — |
| M | — | `=F{n}*L{n}` |
| N | — | `=F{n}-K{n}+M{n}` |

额外逻辑：
- 养户（`is_yanghu`）行：G 列写 "养户"，H 列写 "止戈"，L 列写 "0%"
- 不同日期之间自动空一行（commit `008032c`）
- D 列（customer_id）格式化为 TEXT 类型，E 列（cost）格式化为 `#,##0.00`
- 更新已有行 + 追加新行使用 upsert 策略（按 date+customer_id+campaign 三元组去重）

### 八、后台异步同步 + 失败重试

设计文档未提及。实际实现了一套完整的异步写 Google Sheets 机制：

- **`_sync_sheets_background()`**（`main.py` 第 5463 行）：在 daemon 线程中执行 Sheets 写入，失败后等待 **30 秒**自动重试一次。
- **状态三元组**：`failed`（首次失败）→ `synced`（重试成功）→ `retry_failed`（重试仍失败）。
- **`sheets_sync_log` 表**：持久化记录每次同步结果，包含 `rows_json`（失败行数据），支持前端展示具体哪些行失败。

### 九、新增数据库表：sheets_sync_log

设计文档未提及。实际在 `database.py` 第 232-245 行创建：

```sql
CREATE TABLE IF NOT EXISTS sheets_sync_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    product_name TEXT NOT NULL DEFAULT '',
    spreadsheet_id TEXT NOT NULL DEFAULT '',
    sheet_gid TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'failed',
    error_msg TEXT DEFAULT '',
    rows_json TEXT DEFAULT '',
    retry_count INTEGER DEFAULT 0,
    created_at TEXT DEFAULT (datetime('now','localtime')),
    updated_at TEXT DEFAULT (datetime('now','localtime'))
);
```

### 十、前端实现位置：两处而非一处

设计文档只提到 `UserProfileView.vue` 一个位置。实际有两处 Google Sheets 相关前端：

1. **UserProfileView.vue**（个人中心 — 第 81-137 行）：用户级多表格配置
   - 多表格列表（添加/编辑/删除）
   - Radio 按钮激活当前表格
   - URL 自动提取 spreadsheet_id + gid
   - 列映射参考表

2. **SettingsPanel.vue**（设置页 — 第 31-36 行）：管理员级充值表配置
   - 仅管理员/开发者可见的 `recharge_sheet_id` 输入
   - 存储在 `tags` 表而非 `config` 表（属于系统级设置）
   - 用于充值记录同步到「充值表」sheet，并非做表数据

3. **ToolkitView.vue**：做表数据同步操作按钮
   - "同步到 Google Sheets" 按钮（含加载状态、自动轮询结果、手动重试）
   - 调 `googleSheetsApi.updateZuobiao()` → `syncStatus()` 轮询 → `retrySync()` 重试

### 十一、google_sheets_service.py 模块

设计文档在扩展预留中提到该模块。实际已完整实现：

- `check_configured()`：验证服务账号凭据文件是否存在且有效
- `build_service()`：构建 Sheets API v4 服务对象
- `get_spreadsheet_info()`：获取表格标题、sheet 列表、解析运营名和年月（正则 `^(\D+)(\d{4}\.?\d{2})$`）
- `upsert_zuobiao()`：做表数据 upsert（更新 + 追加），含公式注入和格式化
- `append_recharge()`：充值记录追加到「充值表」sheet
- 异常类型：`GoogleSheetsServiceError`

### 十二、充值表（recharge_sheet_id）是独立的子系统

设计文档未区分"做表数据表格"和"充值表"。实际它们是两个独立概念：

| 维度 | 做表数据表格 | 充值表 |
|---|---|---|
| 配置位置 | `config` 表 `google_sheets_{user_id}`（用户级） | `tags` 表 `recharge_sheet_id`（系统级） |
| 配置权限 | 每个用户自己配置 | 仅管理员/开发者 |
| 前端位置 | UserProfileView.vue | SettingsPanel.vue（管理员 Tab） |
| 后端 API | `/api/config/google-sheets` | `/api/settings/account` |
| 写入函数 | `upsert_zuobiao()` | `append_recharge()` |
| 目标 Sheet | 配置中的 `sheet_gid` 指定 | 固定「充值表」sheet |
| 列映射 | 14 列 (A-N)，含公式 | 7 列 (A-G)，E/F 留空 |

### 十三、审计发现的风险点与建议

| 风险 | 位置 | 严重程度 | 建议 |
|---|---|---|---|
| 全局 spreadsheet_id 回退无效代码 | `main.py` L4693 | 低（有兜底报错） | 要么补全 `spreadsheet_id` 配置读取逻辑，要么移除无效判断 |
| `config/google_sheets_credentials.json` 冗余 | config/ | 低 | 确认是否废弃，移除或归档 |
| `config.json` 中 `google_sheets.credentials_path` 不被读取 | `main.py` L5454 | 中 | 应让 config.json 的配置生效，或移除该字段并更新文档 |
| URL 解析正则三处各自实现 | 前后端共 3 处 | 中 | 应提取为共享工具函数，或至少统一正则模式 |
| `google_sheets_credentials.json` 含 OAuth client_secret | config/ | **高（安全）** | 该文件类型为 `installed`，含 `client_secret`，且代码未使用——若仓库公开或泄露，凭据可能被滥用。建议立即从仓库中移除并轮换 GCP 凭据 |
