# TT 掉包通知（独立机器人）设计文档

> 日期：2026-09-24
> 状态：已确认，已实现（2026-09-24）

## 1. 需求描述

TT 平台的掉包通知目前只有「手动检测 + 列表标红」，缺失 GG 已有的完整通知链路。本次将其对齐 GG，并**使用独立的 Telegram 机器人**（不复用 GG 的 `telegram.bot_token` / `chat_id`）。

对齐后 TT 掉包通知应具备（**经用户确认：不做 Email 通知**）：
1. **定时自动检测**：后台每小时检测所有正常状态的跑包
2. **Telegram 群组通知**：检测到掉包后按产品聚合发送，@在跑人员（走独立 `tt_telegram` 机器人）
3. **前端弹窗提醒**：30s 轮询，首次通知 + 3 分钟后重复提醒，可关闭
4. **手动检测补通知**：手动点「是否掉包」检测到掉包时也触发通知（对齐 GG 手动检测）

## 2. 现状与差异

### 2.1 GG 完整链路（参照物）
- `main.py::_start_delist_scheduler` 后台线程每小时 → `_run_delist_check_once()`
- 检测核心 `delist_checker.check_url_delisted()`（GG/TT 共用，TT 已在复用）
- 掉包后：`_send_telegram_notifications()`（按产品聚合 @在跑人员）+ `email_sender` 发邮件 + 写 `delist_checks`
- 前端 `App.vue` 每 30s 轮询 `/api/delist/pending` → 弹窗 → 关闭调 `/api/delist/dismiss` → 写 `delist_notifications`
- 手动检测 `products_check_delist` 掉包后也发 Telegram

### 2.2 TT 现状（`routes/tt_routes.py`）
- ✅ 已有：手动检测 `/api/tt/products/<pid>/check-delist`（写 `tt_delist_checks`）
- ✅ 已有：状态查询 `/api/tt/products/delist-status`（列表标红）
- ✅ 前端已有：`TtProductCard.vue` 的「🔍 是否掉包」按钮 + 标红样式
- ❌ 缺失：定时检测、Telegram 通知、Email 通知、前端弹窗（`pending`/`dismiss` 接口 + `tt_delist_notifications` 表）

### 2.3 关键数据结构差异（实现时须适配）

| 维度 | GG | TT |
|------|----|----|
| 在跑人员存储 | `products.runner_ids` JSON 字符串 | `tt_product_runners` 独立关联表 |
| 产品表 | `products`（status: ''/'0'/'paused'） | `tt_products`（status: 'active'/'paused'） |
| 包表 | `packages` | `tt_packages`（有 `type` 字段，掉包只测 `type='package'`） |
| 掉包结果表 | `delist_checks` | `tt_delist_checks` |
| 通知状态表 | `delist_notifications` | **新增 `tt_delist_notifications`** |
| 掉包状态值 | 包 `status='dropped'` | 同 GG，`status='dropped'` |
| 数据隔离 | runner_ids 包含判断 | `owner_id` 或 `tt_product_runners` 命中 |

## 3. 技术方案

### 3.1 配置：新增 `tt_telegram` 独立机器人

`config/config.json`（结构占位，不入真实密钥）：
```json
"tt_telegram": {
    "bot_token": "",
    "chat_id": ""
}
```

`config/config.local.json`（真实值，已 gitignore）：
```json
"tt_telegram": {
    "bot_token": "<TT 新机器人 token>",
    "chat_id": "<TT 群组 chat_id>"
}
```

> `main.py` 启动时已对 config.json 与 config.local.json 做深合并，无需额外处理。

### 3.2 数据库：新增 `tt_delist_notifications` 表

`database.py` 迁移块新增（对齐 `delist_notifications`）：
```sql
CREATE TABLE IF NOT EXISTS tt_delist_notifications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    package_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    first_notified INTEGER DEFAULT 0,
    dismissed_at TEXT,
    reminder_count INTEGER DEFAULT 0,
    UNIQUE(package_id, user_id)
);
CREATE INDEX IF NOT EXISTS idx_tt_delist_notif_user ON tt_delist_notifications(user_id);
```

### 3.3 后端改动

#### (1) `telegram_sender.py` — 消息标题参数化
`send_product_delist_notification()` 与 `_build_product_message()` 增加 `title` 参数（默认 `"GG-Server"`，保持既有调用不变）。TT 调用时传 `"TT-Server"`，标题显示 `【TT-Server 掉包通知】`。

#### (2) ~~`email_sender.py` — 平台文案参数化~~（已取消）

经用户确认，TT 不做 Email 通知，`email_sender.py` 保持原样不动。

#### (3) `routes/tt_routes.py` — 接口补齐
- **手动检测补通知**：`check_delist` 检测到掉包后，调用 `send_tt_delist_notifications()` 发 Telegram（对齐 GG `products_check_delist`）。**同时把检测范围收紧为「正常状态跑包」**（`status IS NULL/''/'0'/'normal'`，与 GG 手动检测 `products_check_delist` 的 WHERE 完全一致）——原先无状态过滤会把已掉包/暂停的包一并检测，补上通知后会变成噪声通知。
- **新增 `send_tt_delist_notifications(db, pkgs, title="TT-Server")`**：按产品聚合，在跑人员从 `tt_product_runners` 查（JOIN `users` 取 `telegram_username`），调 `telegram_sender` 传 `title` 前缀。**放在 `tt_routes.py` 而非 `main.py`**：`main.py` 在模块级 import 蓝图，`tt_routes` 反向 import `main` 会造成循环导入；`main.py` 的定时检测改为函数内延迟 import。
- **新增 `GET /api/tt/delist/pending`**（`@jwt_required()`，不加 `@tt_required`，与 GG `pending` 行为一致）：查 `tt_delist_checks` JOIN `tt_packages` JOIN `tt_products` LEFT JOIN `tt_delist_notifications`，返回当前用户可见（`owner_id` 命中或在 `tt_product_runners` 中；developer/admin 全部）的 first/reminder 通知，按产品聚合。返回结构对齐 GG `pending`。
- **新增 `POST /api/tt/delist/dismiss`**（`@jwt_required()`）：写 `tt_delist_notifications`（支持批量 package_ids），逻辑对齐 GG `delist_dismiss`。

> **检测范围口径（实现时确认）**：TT 包状态与 GG 同名同值（`normal/no_events/paused/dropped/rejected`，「正常」在库里存 `''`）。定时检测与手动检测均只跑**正常状态**的包（白名单 `IS NULL / '' / '0' / 'normal'`），与 GG 两处检测完全一致；已掉包/暂停/没事件/拒登的包既不检测也不通知。`pending` 接口的包状态过滤沿用 GG 的写法（`NOT IN ('dropped','paused')` 兜底），实际生效范围由检测侧白名单决定。

#### (4) `main.py` — 定时检测
- 新增 `_run_tt_delist_check_once()`：对齐 `_run_delist_check_once`，查 `tt_packages` JOIN `tt_products`（`type='package'`、`url!=''`、包/产品状态正常、`is_archived=0`），并行检测（走 `_build_delist_proxy_pool()`），写 `tt_delist_checks`，掉包后延迟 import 调用 `send_tt_delist_notifications()`（仅本轮新掉包，不发 Email）。
- 新增 `_start_tt_delist_scheduler()`：后台线程每小时执行一次（对齐 GG，出错 60s 后重试一次），在 `main.py` 启动处与 GG 调度器并列启动。
- 新增 `POST /api/admin/trigger-tt-delist-check`（仅 developer）：手动触发 TT 掉包检测。

### 3.4 前端改动

#### (1) `api/tt.js`
新增：
```js
getPendingDelist: () => client.get('/tt/delist/pending'),
dismissDelist: (packageIds) => client.post('/tt/delist/dismiss', { package_ids: packageIds }),
```

#### (2) `App.vue` — 轮询合并 TT
- `checkDelistNotifications()` 改为**同时轮询 GG `/api/delist/pending` 与 TT `/api/tt/delist/pending`**（TT 接口 catch 403 静默忽略），合并通知列表统一弹窗。
- 弹窗点击跳转按来源区分：GG 通知跳 `/accounts/products?highlight_pkgs=...`，TT 通知跳 `/tt/products?highlight_pkgs=...`（需在 TT 前端支持 `highlight_pkgs` 高亮，若尚未支持则本需求顺带实现）。
- `dismiss` 按来源调对应平台的 dismiss 接口。

#### (3) `views/tt/TtProductPanel.vue` / `TtProductCard.vue`
- 已有「是否掉包」按钮与标红，无需新增 UI。
- 若 `highlight_pkgs` 高亮跳转尚未支持，补一个锚点定位（对齐 GG ProductPanel 的 `highlight_pkgs`）。

## 4. 涉及文件清单

| 文件 | 改动 |
|------|------|
| `config/config.json` | 新增 `tt_telegram` 空结构 |
| `config/config.local.json` | 填入 TT 机器人真实 token/chat_id（用户提供） |
| `py/database.py` | 新增 `tt_delist_notifications` 表 |
| `py/telegram_sender.py` | 标题参数化 `title`（默认 "GG-Server"，兼容旧调用） |
| `py/routes/tt_routes.py` | 手动检测补通知 + 收紧检测范围 + 新增 pending/dismiss + `send_tt_delist_notifications` |
| `py/main.py` | 新增 `_run_tt_delist_check_once` / `_start_tt_delist_scheduler` / trigger 接口 |
| `py/tests/test_tt_delist_notification.py` | 新增：21 个测试 |
| `frontend/src/api/tt.js` | 新增 pending/dismiss API |
| `frontend/src/api/admin.js` | 新增 `triggerTtDelistCheck` |
| `frontend/src/App.vue` | 轮询合并 TT + 跳转区分 + 通知 key 带平台前缀 |
| `frontend/src/views/tt/TtProductPanel.vue` | `highlight_pkgs` 锚点滚动高亮（对齐 GG） |
| `frontend/src/views/SchedulerView.vue` | 新增「TT 掉包检测」手动触发卡片 |
| `frontend/src/components/GlobalTaskPanel.vue` | `tt-delist` 任务图标 |
| `AGENTS.md` | 设计文档索引新增本条 |

## 5. API 一览

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | /api/tt/products/:pid/check-delist | 手动检测（已有，补通知） |
| GET | /api/tt/delist/pending | 新增：TT 待处理掉包通知（按产品聚合） |
| POST | /api/tt/delist/dismiss | 新增：关闭 TT 掉包通知（批量） |
| POST | /api/admin/trigger-tt-delist-check | 新增：手动触发 TT 掉包检测（developer） |

## 6. 测试计划

`py/tests/` 下新增/扩展测试：
- `test_tt_delist_notification.py`：pending/dismiss 接口、`tt_delist_notifications` 读写、聚合与 first/reminder 判定
- 定时检测 `_run_tt_delist_check_once`：在跑人员查取（`tt_product_runners`）、新掉包去重、Telegram 调用（mock）
- `telegram_sender` 参数化标题的单测

## 7. 风险与注意

- **机器人配置未提供前**：`tt_telegram.bot_token` 为空时，`send_tt_delist_notifications` 静默跳过（对齐 GG 的 `if not (bot_token and chat_id) return`），不影响定时检测与前端弹窗。
- **户管（huguan）**：产品/包/素材域对户管拒绝（`no_huguan`），TT 掉包 pending 沿用 `delist_status` 的角色过滤（developer/admin 看全部，其余按 `owner_id` 或在跑人员），户管天然命中不到任何产品 → 返回空，不额外抛 403（避免前端每 30s 一次无意义报错）。
- **不碰 GG 原有逻辑**：所有改动为增量（新表、新接口、`telegram_sender` 参数默认值保持兼容），不改动 GG 掉包链路。
- **前端通知去重 key 加平台前缀**（`gg-5-first` / `tt-5-first`）：GG 与 TT 的 `product_id` 各自独立自增，不加前缀会误去重。
- **未在本次对齐项**：TT 手动检测仍走直连（`check_product_packages(..., None)`），GG 手动检测走代理池——属于本次改动之前就存在的差异，未纳入本次范围，如需对齐可单独提出。
