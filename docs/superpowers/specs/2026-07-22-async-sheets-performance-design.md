# Google Sheets 异步化 & 性能优化 — 设计文档

> 日期：2026-07-22
> 需求：解决充值/做表时 Google Sheets 同步阻塞导致的卡顿，以及页面切换重复加载问题

## 一、核心改动：Google Sheets 异步化

### 1.1 充值 — 写入流程改为异步

**改前**（同步，2-5s）：
```
用户点击 → 先写 Sheets → 成功才写 DB → 返回
```

**改后**（异步，<200ms）：
```
用户点击 → 写 DB → 立即返回 { success: true, id, sheets_synced: 0 }
                ↓
          后台线程写 Sheets → 失败 → 等 30s → 重试一次
                ↓ 成功                    ↓ 再失败
         更新 sheets_synced=1         更新 sheets_error="原因"
```

### 1.2 做表数据 — 写入流程改为异步

**改前**（同步，3-8s）：
```
用户点击 → get_spreadsheet_info + upsert_zuobiao（3-5 次 API 调用）→ 写 DB → 返回
```

**改后**（异步，<200ms）：
```
用户点击 → 写 DB → 立即返回 { success: true, sheets_status: "syncing" }
                ↓
          后台线程写 Sheets → 失败 → 等 30s → 重试一次
                ↓ 成功                    ↓ 再失败
              静默完成             记 sheets_sync_log + 前端提示重试
```

### 1.3 通知提示

| 场景 | 充值 | 做表 |
|------|------|------|
| 写入成功 | 无提示（静默） | 无提示（静默） |
| 第一次失败 | 不弹通知，记录中 ⚠️ 可见 | 提示「填表失败，30秒后重试」 |
| 重试成功 | ⚠️ 消失 | 提示「表格同步成功」 |
| 重试失败 | ⚠️ 保留 + 错误信息 | 提示「重试失败，请手动操作」 |
| 手动重试 | 单条记录重试按钮 | 页面提示条「🔄 重新同步」，失败时展开数据表格 |

### 1.4 做表失败 — 数据兜底展示

手动重试也失败后，提示条下方展开一个**数据预览表格**，展示本应写入 Sheets 的数据（列头对齐表格模板），用户可以：
- 查看数据是否正确
- 点击「📋 复制 TSV」一键复制，粘贴到 Google Sheets
- 点击「✕ 关闭」收起

这样即使 Google Sheets 彻底不通，用户也能手动完成填表。

---

## 二、数据库改动

### 2.1 recharge_records 表加字段

```sql
ALTER TABLE recharge_records ADD COLUMN sheets_synced INTEGER DEFAULT 0;
ALTER TABLE recharge_records ADD COLUMN sheets_error TEXT DEFAULT '';
```

### 2.2 新建 sheets_sync_log 表

```sql
CREATE TABLE IF NOT EXISTS sheets_sync_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    product_name TEXT NOT NULL DEFAULT '',
    spreadsheet_id TEXT NOT NULL DEFAULT '',
    sheet_gid TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'failed',   -- failed | retrying | retry_failed
    error_msg TEXT DEFAULT '',
    rows_json TEXT DEFAULT '',               -- 格式化后的行数据（JSON，用于前端展示）
    retry_count INTEGER DEFAULT 0,
    created_at TEXT DEFAULT (datetime('now','localtime')),
    updated_at TEXT DEFAULT (datetime('now','localtime'))
);
```

`rows_json` 存储 `upsert_zuobiao` 生成的完整行数据，14 列（A-N），按 Google Sheets 模板列序排列。前端直接渲染为表格。

---

## 三、后端改动

### 3.1 通用后台同步函数（main.py）

```python
def _sync_sheets_in_background(sync_fn, on_fail_fn, *args):
    """后台线程写 Google Sheets，失败 30s 后重试一次。"""
    def _run():
        try:
            sync_fn(*args)
        except Exception as e:
            log.warning("Sheets sync 失败，30s 后重试: %s", e)
            if on_fail_fn:
                on_fail_fn("failed", str(e))
            time.sleep(30)
            try:
                sync_fn(*args)
                if on_fail_fn:
                    on_fail_fn("synced", "")
            except Exception as e2:
                log.error("Sheets sync 重试失败: %s", e2)
                if on_fail_fn:
                    on_fail_fn("retry_failed", str(e2))
    threading.Thread(target=_run, daemon=True).start()
```

### 3.2 充值 API 改动

- `recharge_submit` / `recharge_batch_submit`：
  1. 先写 DB（recharge_records，sheets_synced=0）
  2. 启动后台线程写 Sheets
  3. 立即返回

- 新增 `POST /api/recharge/records/<id>/retry-sheets`：手动重试

### 3.3 做表 API 改动

- `google_sheets_update_zuobiao`：
  1. 先写 ad_reports 到 DB
  2. 启动后台线程写 Sheets
  3. 立即返回 `{success: true, sheets_status: "syncing"}`

- `_zuobiao_sync_fail_callback(user_id, product_name, status, error_msg)`：
  1. upsert `sheets_sync_log` 表（status=failed/retry_failed）
  2. 失败时把格式化后的行数据（14 列）存入 `rows_json`
  3. 重试成功时删除该记录

- 新增 `GET /api/google-sheets/sync-status?product_name=xxx`：返回当前用户+产品的同步状态和失败行数据

- 新增 `POST /api/google-sheets/retry-sync`：手动重试，直接调用 `upsert_zuobiao`，成功删 log，失败更新 `rows_json`

### 3.4 充值记录查询 API

- `GET /api/recharge/records` 返回中增加 `sheets_synced` 和 `sheets_error` 字段

---

## 四、前端改动

### 4.1 充值相关

- **RechargeModal.vue** / **RechargeBatchModal.vue**：无需改动，API 快速返回
- **AccountDetailModal.vue**：充值记录列表展示同步状态
  - `sheets_synced=0` → 显示 ⚠️ 图标 + hover 显示错误
  - 点击 ⚠️ → 「🔄 重试同步」按钮

### 4.2 做表相关

- **ToolkitView.vue**：
  - 调用 API 后启动本地表单同步状态轮询（3 秒间隔，最多 2 分钟）
  - 第一次失败 → 产品选择器旁显示 ⚠️ + 「填表失败，30秒后自动重试...」
  - 重试成功 → ⚠️ 消失，提示「表格同步成功」
  - 重试失败 → 提示「重试失败，请手动操作」，产品选择器旁显示「🔄 重新同步」按钮
  - **失败数据展示**：手动重试也失败后，在该产品下展开一个数据预览表格（列头对齐 Sheets 模板 A-N 列），附带「📋 复制 TSV」按钮，用户可手动粘贴到 Google Sheets
  - 切换产品时，如果有该产品的失败记录，自动展示提示条

---

## 五、性能优化（P1-P2）

### 5.1 Store 数据缓存

给 Pinia Store 加 `_lastFetch` 时间戳，同一数据 2 分钟内不重复请求：

- `accounts.js` → `loadAccounts()` 加缓存检查
- `products.js` → `loadProducts()` 加缓存检查
- `youtube.js` → `loadVideos()` 加缓存检查

### 5.2 onMounted 请求并行化

ProductPanel 的 4 个独立请求改为 `Promise.all`。

MediaView 的 5 个独立请求改为 `Promise.all`。

### 5.3 搜索防抖延长

300ms → 500ms。

---

## 六、涉及文件

| 文件 | 改动 |
|------|------|
| `py/database.py` | recharge_records 加 2 列，新建 sheets_sync_log 表 |
| `py/main.py` | 充值/做表 API 改为异步 + 后台同步 + 新增重试端点 |
| `frontend/src/components/AccountDetailModal.vue` | 充值记录同步状态展示 + 重试按钮 |
| `frontend/src/views/ToolkitView.vue` | 做表同步状态轮询 + 通知 + 重试按钮 |
| `frontend/src/stores/accounts.js` | loadAccounts 加缓存 |
| `frontend/src/stores/products.js` | loadProducts 加缓存 |
| `frontend/src/stores/youtube.js` | loadVideos 加缓存 |
| `frontend/src/views/ProductPanel.vue` | 请求并行化 + 搜索防抖 |
| `frontend/src/views/AdsAccountPanel.vue` | 搜索防抖 |


---

## 实际代码逻辑补充（2026-07-23 审计）

> 以下内容记录了实现代码与原始设计文档之间的差异，供后续维护参考。审计范围覆盖 `py/main.py`、`py/google_sheets_service.py`、`py/database.py`、前端 stores 及 views。

### 一、通用后台同步函数 — 签名与实现变化

**设计文档描述**（3.1 节）：

```python
def _sync_sheets_in_background(sync_fn, on_fail_fn, *args):
```

**实际代码**（`py/main.py` 第 5463 行）：

```python
def _sync_sheets_background(sync_fn, on_fail_fn):
```

差异点：

| 项目 | 设计文档 | 实际代码 |
|------|---------|---------|
| 函数名 | `_sync_sheets_in_background` | `_sync_sheets_background` |
| 参数 `*args` | 有，传给 `sync_fn(*args)` | 无。所有上下文通过闭包捕获 |
| `on_fail_fn` 异常处理 | 无保护 | 每个回调调用外包裹 `try: ... except Exception: pass`，防止回调异常中断重试逻辑 |

闭包捕获方式在每个调用点通过局部变量拷贝实现（如 `_spreadsheet_id`、`_sheet_gid`、`_user_id` 等），避免了多线程环境下的变量引用问题。

### 二、充值 API 返回值差异

**设计文档**（1.1 节）要求返回：
```json
{ "success": true, "id": <record_id>, "sheets_synced": 0 }
```

**实际代码**返回值：

| API | 实际返回 |
|-----|---------|
| `recharge_submit` | `{ "success": True, "id": record_id }` — 无 `sheets_synced` 字段 |
| `recharge_batch_submit` | `{ "success": True, "count": len(valid_rows) }` — 无 `sheets_synced` 字段 |

`sheets_synced` 状态仅通过 `GET /api/accounts/<aid>/recharge-records` 查询接口暴露（该查询 SELECT 已包含 `sheets_synced` 和 `sheets_error` 字段，符合设计 3.4 节）。

### 三、做表更新 API 返回值 — 新增 `db_saved` 字段

**设计文档**（3.3 节）要求返回：
```json
{ "success": true, "sheets_status": "syncing" }
```

**实际代码**（第 4958 行）：
```json
{ "success": True, "sheets_status": "syncing", "db_saved": <实际写入 ad_reports 的记录数> }
```

新增 `db_saved` 字段让前端能在成功提示中显示实际入库条数（`ToolkitView.vue` 第 497 行使用了该字段）。

### 四、账户状态变更触发 Sheets 同步（设计文档未覆盖）

设计文档仅描述了"充值"和"做表"两处异步同步。实际代码中还有两处触发场景：

1. **单账户更新**（`accounts_update`，第 3662-3691 行）：当账户状态从"存活"切到非存活时，自动插入一条 `amount='清'` 的清账记录，并启动后台线程同步到 Google Sheets 的"充值表"。

2. **批量账户更新**（`accounts_batch_update`，第 3869-3900 行）：批量改状态时同样触发清账逻辑 + 后台 Sheets 同步。

这两处逻辑与充值异步化的模式一致：先写 DB（`sheets_synced=0`），后台线程写 Sheets，成功/失败更新 `sheets_synced` / `sheets_error`。

### 五、Store 缓存实现与设计存在差异

**设计文档**（5.1 节）描述方案：给 Pinia Store 加 `_lastFetch` 时间戳，同一数据 2 分钟内不重复请求。

**实际实现**使用了两种不同的模式：

| Store | 实际方法 | 机制 | 与设计的差异 |
|-------|---------|------|------------|
| `accounts.js` → `loadAccounts()` | `dedupLoader` | 请求级去重（并发相同请求共享 Promise），非时间缓存 | 切换页面后再切回来仍会重新请求 |
| `accounts.js` → `loadSettings()` | `cachedLoader` (ttl=300000ms) | 5 分钟时间缓存 | 与设计最接近但 TTL 是 5 分钟而非 2 分钟 |
| `products.js` → `loadProducts()` | `dedupLoader` | 请求级去重，非时间缓存 | 同 `loadAccounts` |
| `youtube.js` → `loadVideos()` | `dedupLoader` | 请求级去重，非时间缓存 | 同 `loadAccounts` |

`dedupLoader` 位于 `frontend/src/utils/dedupLoader.js`，作用是：同一个 key 的请求在完成前，后续调用直接返回同一个 Promise。这解决了"短时间内连续调用"（如同一个渲染周期内多个组件同时触发）的问题，但**不能解决页面切换重复加载**的问题。`cachedLoader` 叠加了时间戳检查（`_<key>FetchedAt`），才实现了设计文档描述的缓存行为，但目前仅 `loadSettings` 使用了它。

### 六、请求并行化 — 未按设计实现

**设计文档**（5.2 节）要求：
- ProductPanel 的 4 个独立请求改为 `Promise.all`
- MediaView 的 5 个独立请求改为 `Promise.all`

**实际代码**：

- `ProductPanel.vue` 第 141 行 `onMounted`：`load(); loadRunnerUsers(); loadRegionTimezone(); loadCustomName()` — 四个请求**顺序执行**，未使用 `Promise.all`。仅在产品列表加载函数内部对"主力产品"和"被合并产品"两个子请求做了 `Promise.all`（第 225 行）。

- `MediaView.vue` 第 640 行 `onMounted`：`loadRemotePackages(); loadMusicList(); loadHistory();` 等调用**顺序执行**，未使用 `Promise.all`。

### 七、搜索防抖 — 已按设计实现

ProductPanel（第 258 行）和 AdsAccountPanel（第 179 行）的搜索防抖均为 **500ms**，与设计文档 5.3 节一致。

### 八、数据库迁移方式

**设计文档**使用原始 DDL（`ALTER TABLE ADD COLUMN`、`CREATE TABLE`）。

**实际代码**（`py/database.py`）：
- `recharge_records` 加列使用 `_add_column_if_missing()` 辅助函数（幂等迁移）
- `sheets_sync_log` 表使用 `CREATE TABLE IF NOT EXISTS` + 额外创建了 `idx_ssl_user_product` 联合索引（设计文档未提及该索引，但对 `sync-status` 查询性能有益）

表结构与设计文档一致，字段名、类型、默认值均匹配。

### 九、手动重试接口行为

| 接口 | 设计文档 | 实际代码 | 差异 |
|------|---------|---------|------|
| `POST /api/recharge/<rid>/retry-sheets` | 文档提及 | 第 4134 行实现 | **同步调用** `gs.append_recharge`，成功即更新 DB，失败返回错误。未走后台线程。 |
| `POST /api/google-sheets/retry-sync` | 文档提及 | 第 4990 行实现 | **同步调用** `gs.upsert_zuobiao`（含 `get_spreadsheet_info`），成功删 log，失败更新 `error_msg` 和 `retry_count`。未走后台线程。 |
| `GET /api/google-sheets/sync-status` | 文档提及 | 第 4965 行实现 | 设计一致，返回格式 `{ success: true, log: {...} \| null }` |

重试接口均为**同步阻塞**，不走后台线程。这意味着如果 Sheets API 仍然不通，用户点击重试后仍会等待 2-8 秒才收到失败响应。

### 十、前端同步状态提示 — 产品选择器旁 vs 全局 Toast

**设计文档**（4.2 节）描述：
> "第一次失败 → 产品选择器旁显示 ⚠️ + 「填表失败，30秒后自动重试...」"

**实际代码**（`ToolkitView.vue`）：
1. 失败提示使用了 `ElMessage.warning`（全局 toast，duration=0 不自动消失），显示在页面右上角，而非产品选择器旁。
2. 同步状态提示条（第 34 行）显示在产品选择器**下方**，包含失败状态图标 + 错误信息 + 重试/查看数据按钮 + 数据预览表格。这个提示条仅在产品**已选中且存在失败记录时**渲染，而非始终在产品选择器旁。

实际实现与设计文档在 UI 位置上存在偏差，但功能完整性（失败通知、重试倒计时、手动重试、数据预览、TSV 复制）均符合设计。

### 汇总对比表

| 设计项 | 设计文档 | 实际代码 | 状态 |
|-------|---------|---------|------|
| 后台同步函数签名 | `_sync_sheets_in_background(fn, cb, *args)` | `_sync_sheets_background(fn, cb)` | 改名 + 简化 |
| `on_fail` 异常保护 | 无 | try/except 包裹 | 更健壮 |
| 充值 API 返回 `sheets_synced` | 有 | 无 | 缺失字段 |
| 做表 API 返回 `db_saved` | 无 | 有 | 增强 |
| 账户改状态触发清账同步 | 未提及 | 已实现 | 未文档化 |
| Store 时间缓存 (2min) | `_lastFetch` | `dedupLoader`（去重）+ `cachedLoader`（仅 settings） | 部分实现 |
| ProductPanel 请求并行 | `Promise.all` | 顺序调用 | 未实现 |
| MediaView 请求并行 | `Promise.all` | 顺序调用 | 未实现 |
| 搜索防抖 500ms | 300→500 | 500ms | 已实现 |
| `sheets_sync_log` 索引 | 未提及 | `idx_ssl_user_product` | 增强 |
| 手动重试方式 | 未明确 | 同步阻塞 | 合理但可注明 |
| 提示条位置 | 产品选择器旁 | ElMessage toast + 选择器下方横条 | UI 位置偏差 |
| 表结构 | 匹配 | 匹配 | 一致 |
| 通知提示文案 | 文档描述 | 基本一致 | 一致 |
| 做表失败数据预览 + TSV | 描述 | 实现 | 一致 |
| 充值前校验（仅存活） | 未提及 | 已实现 | 未文档化 |

---
> **审计结论**：核心异步化逻辑（先写 DB → 立即返回 → 后台线程写 Sheets → 30s 重试）完整实现，数据库表结构匹配，前端交互功能齐全。主要偏差集中在：(1) 函数签名简化；(2) API 返回值字段差异；(3) Store 缓存策略从"时间缓存"实际变为"请求去重"为主；(4) onMounted 请求并行化未实施；(5) 账户改状态触发的 Sheets 同步属于未文档化的扩展场景。
