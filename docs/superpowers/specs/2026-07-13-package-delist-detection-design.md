# 包掉包自动检测与通知系统 — 设计文档

## 1. 需求描述

Google Play 上的包可能被下架（掉包），目前只能手动点击链接跳转查看。需要一个自动化系统来检测掉包并通知在跑人员。

### 核心功能

1. **定时检测**：每小时自动检测所有正常状态产品的正常状态包的 Google Play 链接是否掉包
2. **手动检测**：每个产品名后面增加"是否掉包"按钮，点击手动触发检测
3. **弹窗通知**：检测到掉包后，所有在跑人员各自收到弹窗通知（每个人都要收到，不能只通知一个人）
4. **重复提醒**：在跑人员关闭弹窗后，等 3 分钟，如果包状态未设为"掉包"，则再次弹窗提醒该在跑人员
5. **公平通知**：即使有人已经将包状态设为"掉包"，其他在跑人员仍要收到第一次掉包提醒
6. **标红提示**：定时检测到掉包的包在列表中标记为红色，只有手动设置状态为"掉包"后才恢复默认颜色
7. **暂停产品跳过**：暂停状态的产品不参与定时检测

## 2. 技术方案

### 2.1 数据库变更（database.py）

新增两张表：

```sql
-- 掉包检测结果表（记录每个包的检测状态）
CREATE TABLE IF NOT EXISTS delist_checks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    package_id INTEGER NOT NULL UNIQUE,
    product_id INTEGER NOT NULL,
    is_delisted INTEGER DEFAULT 0,   -- 0=正常, 1=已掉包
    checked_at TEXT,                  -- 最后检测时间
    error_msg TEXT DEFAULT '',        -- 检测错误信息
    FOREIGN KEY(package_id) REFERENCES packages(id),
    FOREIGN KEY(product_id) REFERENCES products(id)
);
CREATE INDEX IF NOT EXISTS idx_delist_checks_product ON delist_checks(product_id);

-- 掉包通知状态表（按用户跟踪通知/关闭/提醒状态）
CREATE TABLE IF NOT EXISTS delist_notifications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    package_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    first_notified INTEGER DEFAULT 0,  -- 0=未通知, 1=已弹出过首次通知
    dismissed_at TEXT,                  -- 用户关闭弹窗的时间（ISO格式）
    reminder_count INTEGER DEFAULT 0,   -- 已发送的提醒次数
    UNIQUE(package_id, user_id)
);
```

### 2.2 后端新增模块

#### 2.2.1 检测模块（`py/delist_checker.py`）

核心函数：
- `check_url_delisted(url: str) -> (is_delisted: bool, error: str)`
  - 使用 `requests.get()` 带移动端 User-Agent 请求 Google Play 链接
  - 判断依据：
    1. HTTP 状态码为 404
    2. 页面内容包含 "not found on this server"（英文）
    3. 页面内容包含 "找不到请求的网址"（中文）
    4. 页面内容包含 "We're sorry, the requested URL was not found"
  - 超时设置为 15 秒，避免长时间阻塞
  - 返回 `(True, "")` 表示已掉包，`(False, "")` 表示正常，`(False, "error msg")` 表示检测失败

- `check_product_packages(product_id: int, packages: list[dict]) -> list[dict]`
  - 对产品下所有正常状态的包逐一检测
  - 更新 `delist_checks` 表
  - 返回检测结果列表

#### 2.2.2 定时任务（在 main.py 中启动后台线程）

```python
def start_delist_scheduler(app):
    """启动掉包检测定时任务（每小时执行一次）。"""
    def _run():
        while True:
            try:
                _run_delist_check()
            except Exception as e:
                print(f"[DelistScheduler] Error: {e}")
            time.sleep(3600)  # 1 小时

    def _run_delist_check():
        db = database.get_db()
        # 只检测：产品状态正常 + 包状态正常的包
        rows = db.execute("""
            SELECT pkg.id, pkg.product_id, pkg.url, pkg.package_name
            FROM packages pkg
            JOIN products prod ON pkg.product_id = prod.id
            WHERE (pkg.status IS NULL OR pkg.status = '' OR pkg.status = '0')
              AND (prod.status IS NULL OR prod.status = '' OR prod.status = '0')
              AND pkg.url IS NOT NULL AND pkg.url != ''
              AND (prod.is_archived IS NULL OR prod.is_archived = 0)
        """).fetchall()
        # 逐包检测...
```

#### 2.2.3 API 端点

**1. 手动检测产品掉包**
```
POST /api/products/<pid>/check-delist
```
- 权限：登录用户
- 逻辑：对该产品下所有正常状态的包检测掉包
- 返回：`{ success: true, results: [{package_id, is_delisted, ...}] }`

**2. 获取掉包检测状态（前端轮询）**
```
GET /api/products/delist-status
```
- 权限：登录用户（返回当前用户相关的数据）
- 返回：所有当前用户作为 runner 的产品中，已检测为掉包的包列表
- 包含每个包的通知状态（是否已通知、是否已关闭、提醒时间等）
- 用于前端判断是否需要弹窗

**3. 关闭通知/记录关闭时间**
```
POST /api/delist/dismiss
Body: { package_id: int }
```
- 权限：登录用户
- 逻辑：记录当前用户关闭了某个包的掉包通知，记录 `dismissed_at` 时间
- 返回：`{ success: true }`

**4. 获取当前用户待处理通知**
```
GET /api/delist/pending
```
- 权限：登录用户
- 返回：当前用户需要看到通知的掉包列表
- 逻辑：
  - 查询当前用户作为 runner 的产品
  - 其下已检测为掉包且 `packages.status != 'dropped'` 的包
  - 对于每个包，判断通知状态：
    - `first_notified == 0`：需要弹出首次通知
    - `dismissed_at` 距今超过 3 分钟 且 `packages.status != 'dropped'`：需要弹出提醒

### 2.3 前端变更

#### 2.3.1 ProductCard.vue 改造

1. **产品名后增加"是否掉包"按钮**
   - 位置：产品名 `<strong>` 标签后面
   - 样式：小型按钮，文字"是否掉包"
   - 点击：调用 `POST /api/products/<pid>/check-delist`
   - 检测中显示 loading 状态
   - 检测完成后刷新包列表

2. **包行标红**
   - 在 `packages` 数据中新增 `is_delisted` 字段（来自 `delist_checks` 表）
   - CSS 类 `.pkg-row--delisted`：红色背景（如 `background: #fef2f2` 或 `border-left: 3px solid #ef4444`）
   - 条件：`is_delisted == true` AND `status != 'dropped'`
   - 当 `status == 'dropped'` 时恢复默认颜色

3. **通知弹窗组件**
   - 使用 Element Plus 的 `ElNotification` 或自定义 `ElDialog`
   - 弹出条件：前端轮询发现有未通知的掉包
   - 内容：列出掉包的包名、系列名，提示设置状态为"掉包"
   - 关闭按钮：记录关闭，开始 3 分钟倒计时
   - 3 分钟后如果包状态未变，再次弹出（仅针对该用户）

#### 2.3.2 前端数据流

1. **页面加载时**：通过 `GET /api/products/list` 返回的包数据中包含 `delist_check` 信息（`is_delisted`）
2. **定时轮询**（每 30 秒）：调用 `GET /api/delist/pending` 检查是否有新的掉包通知
3. **通知弹窗**：当有 pending 通知时弹出 `ElMessageBox.alert` 或自定义弹窗
4. **关闭弹窗**：调用 `POST /api/delist/dismiss` 记录关闭时间

#### 2.3.3 API 客户端（api/products.js）

新增方法：
```javascript
checkDelist: (pid) => api.post(`/products/${pid}/check-delist`),
getDelistStatus: () => api.get('/products/delist-status'),
dismissDelist: (pkgId) => api.post('/delist/dismiss', { package_id: pkgId }),
getPendingDelist: () => api.get('/delist/pending'),
```

### 2.4 通知逻辑详细流程

```
定时任务检测到包 X 掉包
  ↓
delist_checks 表记录：package_id=X, is_delisted=1
  ↓
前端轮询 GET /api/delist/pending
  ↓
服务器判断：
  对每个在跑人员 R：
    检查 delist_notifications 表：
      - 无记录 → 返回需要"首次通知"
      - first_notified=0 → 返回需要"首次通知"（前端补录）
      - dismissed_at 距今 > 3分钟 且 packages.status != 'dropped' → 返回需要"提醒"
      - 其他 → 不返回
  ↓
前端收到列表 → 弹出通知弹窗
  ↓
用户关闭弹窗 → POST /api/delist/dismiss
  ↓
服务器记录/更新 delist_notifications：
  - 首次：INSERT (package_id, user_id, first_notified=1, dismissed_at=now)
  - 再次：UPDATE dismissed_at=now, reminder_count++
  ↓
3 分钟后前端再次轮询 → 如果 status 仍不是 'dropped' → 再次弹窗
```

### 2.5 性能考虑

1. **定时任务**：每小时一次，每次检测时使用 `requests.Session` 复用连接
2. **并发控制**：检测时使用线程池（max_workers=3），避免同时发起过多请求
3. **去重**：同一 URL 在一个周期内只检测一次
4. **前端轮询**：30 秒间隔，只查询当前用户相关的通知，SQL 查询高效
5. **后台线程**：不阻塞主 Flask 进程，使用 daemon 线程

### 2.6 边界情况

1. **包没有 URL**：跳过检测
2. **Google Play 请求超时**：标记 error_msg，不计为掉包
3. **网络错误**：标记 error_msg，下次定时任务重试
4. **产品被删除**：定时任务只查存在的产品
5. **包被删除**：delist_checks 中的孤立记录定期清理
6. **用户在通知期间登出**：下次登录时，pending 通知仍然存在，会弹出

## 3. 涉及的文件

| 文件 | 变更类型 | 说明 |
|------|---------|------|
| `py/database.py` | 修改 | 新增 delist_checks、delist_notifications 表 |
| `py/delist_checker.py` | **新建** | 掉包检测核心逻辑 |
| `py/main.py` | 修改 | 新增 4 个 API 端点 + 启动定时任务 |
| `frontend/src/api/products.js` | 修改 | 新增 4 个 API 方法 |
| `frontend/src/stores/products.js` | 修改 | 新增通知轮询逻辑 |
| `frontend/src/components/ProductCard.vue` | 修改 | 新增按钮、标红样式、通知弹窗 |
| `frontend/src/App.vue` | 修改 | 全局通知轮询入口 |

## 4. 需要确认的问题

1. **检测频率**：每小时一次是否合适？Google Play 是否有限流？
2. **通知弹窗样式**：使用 Element Plus 的 Notification 还是 Modal/Dialog？
3. **定时任务的首次执行**：是否在服务启动后立即执行一次，还是等第一个小时？
4. **标红的颜色**：红色边框（`border-left: 3px solid #ef4444`）还是红色背景（`background: #fef2f2`）？

---

请审阅以上设计，确认后我将制定实现计划并开始编码。
