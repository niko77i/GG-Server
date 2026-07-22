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
