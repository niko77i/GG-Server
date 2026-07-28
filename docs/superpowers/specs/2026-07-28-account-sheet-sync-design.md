# 账户管理 — Sheet 同步功能设计文档

## 一、需求描述

在账户管理页面（[AdsAccountPanel.vue](../../frontend/src/views/AdsAccountPanel.vue)）增加同步按钮，实现 Google Sheets「我的看板」与系统账户数据的双向同步。

### 核心功能

1. **Sheet → 系统（下载同步）**：点击同步按钮，读取「我的看板」sheet → 比对系统数据 → 展示差异报告 → 用户确认后执行
2. **系统 → Sheet（上传同步）**：系统内账户状态变更时，自动更新「我的看板」对应行的备注列
3. **状态变更时间展示**：在账户详情弹窗中展示 `status_changed_date`

### 关键规则

- **运营校验（门禁）**：同步时先校验 Sheet 中"运营"列是否匹配当前登录用户的 `display_name`，不匹配直接拒绝
- **新增账户**：系统没有的 account_id → 直接新增，不弹窗。账户名称和 MCC 留空，备注为空则状态=存活
- **状态更新**：系统已有的 account_id → 根据"是否封户"列弹窗提示状态变更，不自动修改
- **代理自动创建**：Sheet 中的"所属渠道"在系统 agents 表中不存在时，自动新增

---

## 二、字段映射

### 「我的看板」Sheet 列 → 系统字段

| Sheet 列 | 系统字段 | 同步行为 |
|----------|---------|---------|
| 运营 | `users.display_name` | 门禁校验（必须匹配当前用户） |
| 账户ID | `accounts.account_id` | 主键匹配 |
| 所属渠道 | `agents.name`（via `agent_id`） | 自动匹配或新建代理 |
| 时区 | `accounts.timezone` | 直接赋值 |
| 备注 | `accounts.status`（via `status_id`） | 新增时为空→存活；系统→Sheet 时写入状态名 |
| 是否封户 | 状态变更建议 | 是→死亡 / 否→存活 / 可用→非死亡即可（均弹窗确认） |
| 国家 | — | **不参与同步** |

### 「是否封户」→ 状态映射规则

| 是否封户 | 建议状态 | 当前已是目标状态 | 当前状态不同 |
|---------|---------|----------------|-------------|
| 是 | 死亡 | 无变化，不提示 | 弹窗提示改为死亡 |
| 否 | 存活 | 无变化，不提示 | 弹窗提示改为存活 |
| 可用 | 非死亡即可 | 状态≠死亡 → 不提示 | 状态=死亡 → 弹窗提示改为存活 |

---

## 三、数据流

### 流 A：Sheet → 系统（手动触发，两步确认）

```
用户点击 [🔄 同步]
       │
       ▼
读取「我的看板」Sheet 数据
       │
       ▼
门禁校验：运营列 == 当前用户 display_name？
       │
   ┌───┴───┐
   │  否   │ → ❌ "这不是你的私有看板表，请修改"
   │  是   │ → ✅ 继续
   └───────┘
       │
       ▼
按 account_id 批量查询系统现有账户
       │
       ▼
逐行比对，分类为：
  - to_create（系统没有 → 直接新增）
  - to_update（系统有 + 是否封户要求状态变更 → 弹窗确认）
  - unchanged（无变化）
       │
       ▼
返回 diff 报告 → 前端展示
       │
       ▼
用户确认 → 执行同步
  - 批量创建新账户
  - 执行确认后的状态变更（不触发清账逻辑）
```

### 流 B：系统 → Sheet（自动触发，后台线程）

```
accounts_update() 状态变更
       │
       ├──→ 充值表：追加"清"记录（已有逻辑，不变）
       │
       └──→ 我的看板：_sync_sheets_background()
             按 account_id 定位行 → 更新备注列（F列）
             写入当前状态名称
```

---

## 四、后端 API

### 4.1 `POST /api/accounts/sync-from-sheet` — 新增

**认证**：`@jwt_required()`

#### dry_run 模式（仅比对）

请求：
```json
{ "dry_run": true }
```

响应：
```json
{
  "success": true,
  "diff": {
    "to_create": [
      {
        "account_id": "123-456-7890",
        "agent": "卡尔",
        "timezone": "UTC+8",
        "operator": "张三"
      }
    ],
    "to_update": [
      {
        "account_id": "987-654-3210",
        "existing_id": 42,
        "current_status": "存活",
        "封户值": "是",
        "suggested_status": "死亡",
        "need_confirm": true
      }
    ],
    "unchanged": 10,
    "warnings": []
  },
  "summary": {
    "total_in_sheet": 15,
    "new_accounts": 2,
    "status_changes_pending": 3,
    "unchanged": 10
  }
}
```

#### execute 模式（执行同步）

请求：
```json
{
  "dry_run": false,
  "confirmed": {
    "create": ["account_id_1", "account_id_2"],
    "update": [
      {"account_id": "xxx", "new_status": "死亡"},
      {"account_id": "yyy", "new_status": "存活"}
    ]
  }
}
```

响应：
```json
{
  "success": true,
  "result": {
    "created": 2,
    "updated": 3,
    "errors": []
  }
}
```

#### 错误处理

| 场景 | HTTP | 消息 |
|------|------|------|
| 运营校验失败 | 400 | "这不是你的私有看板表，请修改" |
| Google Sheets 未配置 | 400 | "Google Sheets 未配置" |
| spreadsheet_id 为空 | 400 | "请先在设置中配置表格链接" |
| 我的看板 sheet 不存在 | 400 | "未找到「{sheet名}」工作表" |
| 读取 Sheet 失败 | 400 | "无法读取表格: ..." |

### 4.2 `PUT /api/accounts/<id>` — 修改

在现有状态变更逻辑（清账 + 充值表同步）之后，新增 my_dashboard 后台同步：

```python
# 新增：状态变更时同步「我的看板」备注列
if new_status and old_status and new_status != old_status["status_name"]:
    dashboard_name = _get_my_dashboard_name(db, user_id)
    sheet_id = _get_recharge_sheet_id(db)  # 复用同一个 spreadsheet
    if sheet_id and dashboard_name:
        def _sync_dashboard():
            gs.update_cell_by_account_id(
                service, sheet_id, dashboard_name,
                old_status["account_id"], new_status
            )
        _sync_sheets_background(_sync_dashboard, lambda s, e: None)
```

### 4.3 `PUT /api/accounts/batch-update` — 修改

同单账户更新，批量状态变更时每一条都触发 my_dashboard 后台同步。

---

## 五、Google Sheets 服务

### 5.1 `read_sheet_values()` — 新增

```python
def read_sheet_values(service, spreadsheet_id: str, sheet_name: str, range_str: str) -> list[list]:
    """通用读取 sheet 指定范围的值。
    
    Returns:
        二维列表，每行为一个 list[str]
    """
```

### 5.2 `update_cell_by_account_id()` — 新增

```python
def update_cell_by_account_id(service, spreadsheet_id: str, sheet_name: str,
                               account_id: str, new_status: str) -> dict:
    """在指定 sheet 中按 account_id 定位行，更新备注列（F列）。
    
    1. 读取全表 A-G 列
    2. 在 B 列（账户ID）中匹配 account_id
    3. 更新 F 列（备注）为该行的状态值
    4. 批量写回
    
    Returns:
        {"updated": N} 或 {"not_found": True}
    """
```

### 5.3 `append_recharge()` — 不变

现有充值表追加逻辑保持不变。

---

## 六、后端辅助函数

### `_get_my_dashboard_name(db, user_id) -> str`

三层叠加获取用户「我的看板」sheet 名：

```python
def _get_my_dashboard_name(db, user_id) -> str:
    name = "我的看板"  # 内置默认
    row = db.execute("SELECT value FROM tags WHERE key='sheet_mappings'").fetchone()
    if row:
        mappings = json.loads(row["value"])
        name = mappings.get("my_dashboard", name)
    row = db.execute("SELECT value FROM config WHERE key=?",
                     (f"sheet_mappings_{user_id}",)).fetchone()
    if row:
        mappings = json.loads(row["value"])
        name = mappings.get("my_dashboard", name)
    return name
```

### `_read_my_dashboard(service, spreadsheet_id, sheet_name) -> list[dict]`

读取「我的看板」sheet 数据，跳过表头行，返回结构化列表。

### `_get_spreadsheet_id(db) -> str`

从 tags/config 中获取当前有效的 spreadsheet ID。

---

## 七、前端

### 7.1 AdsAccountPanel.vue — 同步按钮

在工具栏按钮行新增：

```html
<el-button @click="syncVisible = true">🔄 同步</el-button>
```

### 7.2 AccountSyncModal.vue — 新增组件

三步流程弹窗：

**步骤 1**：加载中（读取 Sheet 中...）

**步骤 2**：差异报告
- 🆕 新增账户列表（account_id / 所属渠道 / 时区 / 运营）
- ⚠️ 状态变更确认列表（account_id / 当前状态 → 建议状态 / 封户值）
- ✅ 无变化数量
- 操作按钮：取消 / 确认同步

**步骤 3**：执行结果（已创建 N 个账户，已更新 N 个状态）

### 7.3 AccountDetailModal.vue — 状态变更时间

在 `info-grid` 中「状态」行下方增加：

```html
<div><strong>状态变更时间：</strong>{{ account.status_changed_date || '-' }}</div>
```

### 7.4 前端 API

```js
// frontend/src/api/accounts.js
export const accountsApi = {
  // ...existing...
  syncFromSheet: (body) => api.post('/accounts/sync-from-sheet', body),
}
```

### 7.5 前端 Store

```js
// frontend/src/stores/accounts.js
async syncFromSheet(body) {
  return accountsApi.syncFromSheet(body)
},
```

---

## 八、边界情况与错误处理

| 场景 | 处理 |
|------|------|
| Google Sheets API 未配置 | 返回 400，"请先配置 Google Sheets" |
| spreadsheet_id 为空 | 返回 400，"请先在设置中配置表格链接" |
| 我的看板 sheet 不存在 | 返回 400，"未找到「{sheet名}」工作表" |
| 运营列 ≠ 当前用户 display_name | 返回 400，"这不是你的私有看板表，请修改" |
| Sheet 中 account_id 为空的行 | 跳过，记入 warnings |
| Sheet 中"所属渠道"为空 | 新增时 agent 留空，记入 warnings |
| 新增时 account_id 与系统已有重复 | 自动归类到 to_update 处理 |
| 后台写 Sheet 失败 | 静默失败，不阻塞主流程 |
| 用户未配置 my_dashboard sheet 名 | 使用默认值"我的看板" |

---

## 九、涉及文件

| 文件 | 操作 | 说明 |
|------|------|------|
| `py/main.py` | 修改 | 新增 `sync-from-sheet` 接口；修改 `accounts_update`/`batch-update` 增加 my_dashboard 同步；新增辅助函数 |
| `py/google_sheets_service.py` | 修改 | 新增 `read_sheet_values()` 和 `update_cell_by_account_id()` |
| `frontend/src/views/AdsAccountPanel.vue` | 修改 | 新增「🔄 同步」按钮 |
| `frontend/src/components/AccountSyncModal.vue` | **新增** | 同步差异弹窗 |
| `frontend/src/components/AccountDetailModal.vue` | 修改 | 新增「状态变更时间」展示 |
| `frontend/src/api/accounts.js` | 修改 | 新增 `syncFromSheet()` |
| `frontend/src/stores/accounts.js` | 修改 | 新增 sync action |

---

## 十、不涉及

- **数据库变更**：不需要新增表或字段（status_changed_date 已存在，国家字段不参与同步）
- **账户名称/MCC 自动填充**：同步新增时留空
- **清账逻辑修改**：同步触发的状态变更不执行清账
- **已接账户明细 Sheet**：不参与同步流程，仅「我的看板」参与
