# TT 广告账户管理页面设计文档

> **文档版本**: v1.1
> **日期**: 2026-09-21
> **状态**: 待确认

## 1. 需求描述

TT 平台新增「广告账户」管理页面，**完整对标 GG 广告账户**（[AdsAccountPanel.vue](../../../frontend/src/views/AdsAccountPanel.vue)），并叠加 TikTok 特有的业务规则。

GG 广告账户区含「产品管理 / 广告账户 / MCC 管理 / 设置」四个 tab。TT 目前已有「产品管理 / BC 管理 / TT 设置」，**唯独缺「广告账户」**，本次补齐。

### 1.1 完整对标 GG 的功能

| 功能 | 说明 |
|------|------|
| 列表 + 分页 | 广告账户列表，按 owner 隔离；**管理员可查看所有户，顶部下拉筛选投手**；单页默认 50 起 |
| BC 分组展示 | 按所属 BC 分组，相邻 BC 颜色交替区分（复用 GG 广告账户逻辑） |
| 搜索筛选 | 名称/ID 搜索、所属 BC、代理、时区、状态筛选 |
| 状态按钮 | 存活/验证/死亡等状态按钮 + 计数 |
| 新增/编辑/删除 | 单账户 CRUD，advertiser_id 全局唯一 |
| 批量删除 | 勾选多条软删除 |
| 批量导入 | 批量录入账户 |
| 批量查户 | 查本地库，判断一批 ID 哪些已录入（**不依赖外部 API**） |
| 批量充值 + 单充值 | 写 DB + 后台异步写 Google Sheets「充值表」 |
| 同步 | 从 Google Sheets「我的看板」读账户、比对、确认写入 |
| 已删除回收站 | 软删除列表、恢复、永久删除 |
| 内联编辑 | 名称/BC/时区/代理/状态 单元格内联编辑 |
| 批量修改 | 批量改状态、批量改 BC |
| 详情 | 充值记录 + BC 变更历史 |

### 1.2 TikTok 特有（GG 没有）

| 差异 | 说明 |
|------|------|
| 消耗情况双向同步 | 账户有「一周内消耗情况」字段，Sheet ↔ 系统双向同步，冲突时弹窗选择 |
| 回收户清单子 sheet | 状态改为「封禁/死亡」时自动写入独立子 sheet「回收户清单」 |
| 回收原因 | 封禁/死亡时填写，下拉 + 手动输入 + 自动新增 |
| 独立代理/状态 | TT 的代理、状态与 GG 完全独立，在 TT 设置页配置 |

## 2. 语义映射（GG → TikTok）

| GG 概念 | TikTok 概念 | 处理方式 |
|---------|-------------|----------|
| `account_id`（`123-456-7890`）| `advertiser_id`（**十多位纯数字，无 `-`**）| 字段更名，格式解析不同 |
| `mcc`（经理账户）| `bc`（Business Center）| 关联 `tt_bcs` 表（已存在） |
| `agent`（代理）| 所属渠道 / 代理（同一概念）| 复用 `agents` 表 + platform 列隔离 |
| `status` | 状态 | 复用 `account_statuses` + platform 列隔离（TT 独立选项值） |
| `recharge_records` | `tt_recharge_records` | 新建独立表 |
| `account_mcc_history` | `tt_account_bc_history` | 新建独立表（BC 变更历史） |
| 同步读「我的看板」| 同步读 `tt_sheet_mappings.my_dashboard` | 复用 Sheets 机制，列结构不同（见 4.2） |
| 充值写「充值表」| 充值写 `tt_sheet_mappings.recharge` | 复用 Sheets 机制 |

> 「批量查户」「同步」均**不依赖 Google Ads API**（查本地库 / 读 Sheets），TikTok 侧无需对接 TikTok Marketing API。

## 3. 数据模型

### 3.1 新增表

**`tt_accounts`**：

```sql
CREATE TABLE IF NOT EXISTS tt_accounts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT DEFAULT '',                     -- 账户名（保留，可留空，显示用）
    advertiser_id TEXT NOT NULL UNIQUE,       -- 广告账户 ID（十多位纯数字）
    bc_id INTEGER REFERENCES tt_bcs(id),      -- 所属 BC
    country TEXT DEFAULT '',                  -- 国家
    agent_id INTEGER REFERENCES agents(id),   -- 所属渠道/代理
    timezone TEXT DEFAULT '',                 -- 时区
    consumption TEXT DEFAULT '',              -- 一周内消耗情况（双向同步）
    status_id INTEGER REFERENCES account_statuses(id),  -- 状态
    acquired_date TEXT DEFAULT (date('now','localtime')),  -- 入库时间
    death_date TEXT DEFAULT '',
    status_changed_date TEXT DEFAULT '',
    remark TEXT DEFAULT '',                   -- 备注
    owner_id INTEGER REFERENCES users(id),
    deleted_at TEXT DEFAULT NULL,             -- 软删除
    created_at TEXT DEFAULT (datetime('now','localtime')),
    updated_at TEXT DEFAULT (datetime('now','localtime'))
);
CREATE INDEX IF NOT EXISTS idx_tt_accounts_owner ON tt_accounts(owner_id);
CREATE INDEX IF NOT EXISTS idx_tt_accounts_bc ON tt_accounts(bc_id);
CREATE INDEX IF NOT EXISTS idx_tt_accounts_list ON tt_accounts(owner_id, status_id, deleted_at);
```

**`tt_account_bc_history`**（对标 `account_mcc_history`）：

```sql
CREATE TABLE IF NOT EXISTS tt_account_bc_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id INTEGER NOT NULL REFERENCES tt_accounts(id) ON DELETE CASCADE,
    old_bc_id INTEGER,
    new_bc_id INTEGER,
    changed_by INTEGER REFERENCES users(id),
    change_type TEXT NOT NULL DEFAULT 'manual',   -- create/manual
    created_at TEXT DEFAULT (datetime('now','localtime'))
);
CREATE INDEX IF NOT EXISTS idx_tt_acbh_account ON tt_account_bc_history(account_id);
```

**`tt_recharge_records`**（对标 `recharge_records`）：

```sql
CREATE TABLE IF NOT EXISTS tt_recharge_records (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id TEXT NOT NULL,                 -- advertiser_id（文本，与 GG 一致）
    amount TEXT NOT NULL,
    agent_id INTEGER REFERENCES agents(id),
    operator TEXT DEFAULT '',
    status TEXT DEFAULT '',
    created_by INTEGER REFERENCES users(id),
    sheets_synced INTEGER DEFAULT 0,
    sheets_error TEXT DEFAULT '',
    created_at TEXT DEFAULT (datetime('now','localtime'))
);
CREATE INDEX IF NOT EXISTS idx_tt_recharge_account ON tt_recharge_records(account_id);
```

**`tt_recycle_reasons`**（回收原因，TT 特有）：

```sql
CREATE TABLE IF NOT EXISTS tt_recycle_reasons (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    owner_id INTEGER REFERENCES users(id),
    created_at TEXT DEFAULT (datetime('now','localtime')),
    UNIQUE(name, owner_id)
);
```

### 3.2 复用/扩展

- **`agents` 表加 platform 列**（对齐 `account_statuses` 已有做法）：
  ```sql
  _add_column_if_missing(conn, "agents", "platform", "platform TEXT DEFAULT 'gg'")
  ```
  并把 GG 已有代理复制一份到 `platform='tt'`（对齐 database.py 对 statuses 的复制逻辑）。
- **`account_statuses`**：已有 platform 列，直接复用 `platform='tt'`。
- **`regions`**：复用为「时区」选项（TT 设置页「地区时区」tab 已用）。
- **`tags.tt_sheet_mappings`**：从 `{"accounts": "账户明细"}` 扩展为：
  ```json
  { "accounts": "账户明细", "recharge": "充值表", "my_dashboard": "我的看板", "recycle": "回收户清单" }
  ```

## 4. 同步设计（TikTok 核心差异）

### 4.1 「我的看板」Sheet（10 列）

| 列 | 字段 | 映射 |
|----|------|------|
| A | 运营 | 门禁校验（匹配当前用户 display_name），存 owner |
| B | 入库时间 | `acquired_date` |
| C | 是否回收 | 不触发状态自动变更（仅读取，系统状态靠手动） |
| D | 账户ID | `advertiser_id` |
| E | BC | `bc_id` |
| F | 国家 | `country` |
| G | 所属渠道 | `agent_id` |
| H | 时区 | `timezone`（文本，格式 `+8`/`-3` 数字，非 UTC） |
| I | 一周内消耗情况 | `consumption`（双向同步） |
| J | 备注 | `remark` |

### 4.2 同步流程（dry_run 比对 → 确认）

1. 读 `tt_sheet_mappings.my_dashboard`，门禁校验 A 列「运营」匹配当前用户。
2. **自动新增选项**：`BC`（E 列）、`所属渠道`（G 列）在系统不存在时**直接新增**到系统（tt_bcs / agents）。
3. **时区处理**（H 列）：直接读取看板时区值存 `timezone`（格式 `+8`/`-3` 数字，非 UTC）；看板时区为空时，用 TT 设置页「地区时区」(regions) 的时区补上。
4. **消耗情况双向同步**（I 列 ↔ `consumption`）：
   - Sheet 值 == 系统值 → 无变化
   - 不一致 → 弹窗提示，用户选择「以 Sheet 为准」或「以系统为准」保存
   - 系统侧手动改 `consumption` → 同步时若 Sheet 未变，写回 Sheet
5. 状态变更：GG 靠看板「封户值」判定，**TT 不靠看板自动改状态**，状态变更走系统手动（见 4.3）。

### 4.3 「回收户清单」子 sheet（12 列，TT 特有）

列：时间 | 账户ID | 渠道 | 运营 | 国家 | 时区 | 有无消耗 | 回收原因 | 是否提交 | 清零金额 | 备注 | 是否二次提交

- **触发**：系统里把户状态改为「封禁」或「死亡」时，后台异步写入该 sheet。
- **系统写入的字段**：时间 | 账户ID | 渠道 | 运营 | 国家 | 时区 | 回收原因。
- **回收原因**：下拉框可选 + 手动输入；系统没有该原因时自动新增到 `tt_recycle_reasons`（与代理自动新增机制一致）。
- **权限**：任何用户（owner）都能改自己户的状态为封禁/死亡并触发写入；「回收户清单」相关的**配置**（回收原因下拉选项、sheet 映射）仅管理员可在 TT 设置页修改。

## 5. 后端 API 设计

新增路由独立文件 `py/routes/tt_accounts_routes.py`，注册 blueprint，在 `main.py` 注册。全部 `@jwt_required()` + `tt_required`。

### 5.1 广告账户 CRUD

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/tt/accounts/list` | 列表 + 筛选（search/bc_id/agent/status/timezone/page/size/owner_id）；普通用户强制 owner_id=自己，管理员可传 owner_id 查看任意投手的户 |
| GET | `/api/tt/accounts/lookup` | 按 advertiser_id 查本地库 |
| POST | `/api/tt/accounts/batch-lookup` | 批量查本地库 |
| POST | `/api/tt/accounts/create` | 新增 |
| POST | `/api/tt/accounts/batch-create` | 批量导入 |
| PUT | `/api/tt/accounts/<id>` | 更新（含 `consumption` 手动修改） |
| PUT | `/api/tt/accounts/<id>/reassign` | 换绑 BC（记录历史） |
| DELETE | `/api/tt/accounts/<id>` | 软删除 |
| POST | `/api/tt/accounts/batch-delete` | 批量软删除 |
| POST | `/api/tt/accounts/<id>/restore` | 恢复 |
| DELETE | `/api/tt/accounts/<id>/permanent` | 永久删除 |
| GET | `/api/tt/accounts/deleted` | 已删除列表 |
| POST | `/api/tt/accounts/batch-update` | 批量改状态/BC |
| POST | `/api/tt/accounts/sync-from-sheet` | 同步（dry_run/确认） |
| GET | `/api/tt/accounts/<id>/bc-history` | BC 变更历史 |
| DELETE | `/api/tt/accounts/<id>/bc-history/<hid>` | 删除历史 |

### 5.2 充值

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/tt/accounts/<id>/recharge-records` | 账户充值记录 |
| POST | `/api/tt/recharge/submit` | 单充值 |
| POST | `/api/tt/recharge/batch-submit` | 批量充值 |
| PUT | `/api/tt/recharge/<rid>` | 修改充值记录 |
| DELETE | `/api/tt/recharge/<rid>` | 删除充值记录 |
| POST | `/api/tt/recharge/<rid>/retry-sheets` | 重试写 Sheets |

### 5.3 回收原因（TT 特有）

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/tt/recycle-reasons/list` | 列表 |
| POST | `/api/tt/recycle-reasons/create` | 新增 |
| PUT | `/api/tt/recycle-reasons/<id>` | 改名 |
| DELETE | `/api/tt/recycle-reasons/<id>` | 删除 |

### 5.4 复用共享端点（加 platform 参数）

- `/api/agents/*`：补 `platform` 参数支持（`platform='tt'` 隔离）。
- `/api/statuses/*`：补 `platform` 参数支持（若尚未支持）。
- `/api/regions/*`：复用为时区选项。
- `/api/tt/bcs/options`：复用为「所属 BC」下拉。

### 5.5 关键实现语义

- **owner 隔离**：普通用户所有查询 `WHERE owner_id = 当前用户 AND deleted_at IS NULL`；管理员（或 developer）可传 `owner_id` 参数查看任意投手的户（列表顶部分页）。
- **advertiser_id 全局唯一**：`UNIQUE` 约束，冲突返回 409 + 已有账户详情。
- **BC 变更历史**：首次分配 `change_type='create'`，后续 `'manual'`。
- **软删除**：`deleted_at` 打时间戳；恢复置 NULL；永久删除物理删行 + 级联历史。
- **充值写 Sheet**：写 DB → 后台异步 `append_recharge` → 成功置 `sheets_synced=1`，失败写 `sheets_error`；仅「存活」状态可充值。
- **状态改封禁/死亡**：更新 `tt_accounts.status_id` 后，后台异步写「回收户清单」sheet（时间/账户ID/渠道/运营/国家/时区/回收原因）。
- **消耗情况**：`consumption` 为普通文本字段，系统手动改走 `PUT /api/tt/accounts/<id>`；同步双向对齐（冲突弹窗）。

## 6. 前端 UI 设计

UI 直接复用 GG 广告账户布局与交互，做 TikTok 语义替换。**不重新做视觉设计**，保持与 GG 一致。

### 6.1 主页面 `frontend/src/views/tt/TtAccountPanel.vue`

对标 `AdsAccountPanel.vue`：工具栏 + 状态按钮 + 搜索筛选栏 + 表格 + 分页。
- **管理员专属「投手」筛选**：顶部新增「投手」下拉（数据源 `/api/tt/users`），切换查看对应投手的户；普通用户隐藏该下拉、只看自己的户。
- **BC 分组展示**：表格按所属 BC 分组，相邻 BC 颜色交替区分（复用 GG `mccRowClass`/`mccGroupIndex` 逻辑，MCC→BC）。
- **分页**：单页默认 50 起，选项 `[50, 100, 200]`。
- 表格在 GG 基础上**新增「消耗情况」列**（可内联编辑），状态列改「封禁/死亡」时弹出回收原因填写框。

### 6.2 子组件（`frontend/src/components/tt/`）

| 组件 | 对标 | 职责 |
|------|------|------|
| `TtAccountModal.vue` | `AccountModal.vue` | 新增/编辑（含国家、消耗情况字段） |
| `TtAccountBatchImportModal.vue` | `AccountBatchImportModal.vue` | 批量导入 |
| `TtAccountBatchLookupModal.vue` | `AccountBatchLookupModal.vue` | 批量查户（ID 解析改为十多位纯数字） |
| `TtAccountDetailModal.vue` | `AccountDetailModal.vue` | 详情（充值记录 + BC 历史） |
| `TtRechargeModal.vue` | `RechargeModal.vue` | 单账户充值 |
| `TtRechargeBatchModal.vue` | `RechargeBatchModal.vue` | 批量充值 |
| `TtAccountSyncModal.vue` | `AccountSyncModal.vue` | 同步（含消耗冲突弹窗） |
| `TtAccountDeletedModal.vue` | `AccountDeletedModal.vue` | 已删除回收站 |
| `TtRecycleReasonModal.vue` | — | 封禁/死亡时填回收原因（新增） |

### 6.3 API 模块 `frontend/src/api/tt.js`

新增 `ttAccountsApi`（账户 CRUD + lookup + sync + bc-history + consumption）、`ttRechargeApi`（充值）、`ttRecycleReasonApi`（回收原因）。代理/状态复用 `optionApi`（加 platform 参数）。

### 6.4 TT 设置页扩展（`TtSettingsPanel.vue`）

「账户设置」tab 新增（仅管理员可见）：
- **代理配置**（复用 `agents` + `platform='tt'`，增删改）
- **状态配置**（复用 `statuses` + `platform='tt'`，增删改）
- **回收原因配置**（`tt_recycle_reasons`，增删改）
- Google 表格配置的 `sheet_mappings` 扩展为 4 个 key（accounts/recharge/my_dashboard/recycle）

### 6.5 导航与路由

- `router/index.js`：`{ path: '/tt/accounts', component: TtAccountPanel, meta: { platform: 'tt', title: 'TT广告账户' } }`
- `AppSidebar.vue`：`ttNavItems`「产品管理」区新增「👤 广告账户」`/tt/accounts`

## 7. 涉及的文件清单

**后端**：
- `py/database.py`：新增 4 张表；`agents` 加 platform 列；复制 GG 代理到 `platform='tt'`
- `py/routes/tt_accounts_routes.py`（新建）：账户 + 充值 + 回收原因 + 同步端点
- `py/main.py`：注册 blueprint；`agents`/`statuses` 端点补 platform 支持
- `py/google_sheets_service.py`：复用 `read_sheet_values`/`append_recharge`，补 `append_recycle`（写回收清单）

**前端**：
- `frontend/src/views/tt/TtAccountPanel.vue`（新建）
- `frontend/src/components/tt/`（新建 9 个子组件）
- `frontend/src/views/tt/TtSettingsPanel.vue`（扩展：代理/状态/回收原因配置）
- `frontend/src/api/tt.js`（扩展）
- `frontend/src/router/index.js`（扩展）
- `frontend/src/components/AppSidebar.vue`（扩展）

**测试**：`py/tests/test_tt_accounts.py`（新建）

## 8. 测试计划

- 账户 CRUD：list 筛选、create 唯一冲突、软删除/恢复/永久删除、批量删除
- 批量查户：十多位纯数字 ID 解析、found/not_found
- BC 变更历史：首次 create、reassign 变更
- 充值：写 DB、仅存活可充值、后台写 Sheets（mock）
- 同步：dry_run diff、门禁校验、BC/渠道/时区自动新增、消耗双向同步（冲突弹窗）
- 状态改封禁/死亡：写回收清单 sheet（mock）、回收原因自动新增
- 回收原因 CRUD + owner 隔离
- 代理/状态 platform 隔离（TT 独立）

## 9. 风险与注意事项

1. **agents 加 platform 列**：属既有表结构变更，默认 `'gg'`，迁移只增不改，保证 GG/FB 不受影响。
2. **纯增量原则**：不修改 GG/FB 广告账户现有逻辑，全部新增 `tt_*` 文件/端点/表。
3. **advertiser_id 校验**：十多位纯数字，创建/导入时做数字校验（去空格、拒绝非数字）。
4. **回收清单写 Sheet 异步失败**：写「回收户清单」失败不阻塞状态变更本身，需记录错误便于排查（对齐充值 `sheets_error` 的思路）。
