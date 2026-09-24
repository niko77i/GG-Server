# TT 掉包通知（独立机器人）实现计划

> 对应设计文档：[2026-09-24-tt-delist-notification-design.md](../specs/2026-09-24-tt-delist-notification-design.md)
> 状态：已确认（2026-09-24，**不做 Email**，机器人已配好）

## Goal

TT 平台补齐掉包通知链路（对齐 GG）：定时检测 + Telegram 群组通知（独立 `tt_telegram` 机器人）+ 前端弹窗（first/reminder），手动检测也补发通知。**不做 Email**。

## 全局约束

- **纯增量**：不改 GG 掉包链路，不碰 `delist_checks` / `delist_notifications` / `packages` / `products` 等 GG 表与接口。
- **`telegram_sender` 参数化向后兼容**：新增 `title` 参数默认 `"GG-Server"`，既有 GG 调用不传参、行为不变。
- **TT 数据隔离**：pending 接口按 `owner_id` 或 `tt_product_runners` 命中过滤；developer/admin 看全部。
- **测试运行**：`cd py && python -m pytest tests/ -v`。
- **git**：本仓库常有并行会话在途改文件，**禁用 `git add -A`**，commit 只 add 本任务涉及文件。
- **配置已就绪**：`tt_telegram` 已写入 `config.local.json`（真实值）与 `config.json`（空结构）。

## 文件结构总览

| 文件 | 改动 |
|---|---|
| `py/database.py` | 新增 `tt_delist_notifications` 表 |
| `py/telegram_sender.py` | `send_product_delist_notification` / `_build_product_message` 加 `title` 参数 |
| `py/routes/tt_routes.py` | 手动检测补通知；新增 `delist_pending` / `delist_dismiss` |
| `py/main.py` | 新增 `_send_tt_telegram_notifications` / `_run_tt_delist_check_once` / `_start_tt_delist_scheduler` / `trigger-tt-delist-check` |
| `frontend/src/api/tt.js` | 新增 `getPendingDelist` / `dismissDelist` |
| `frontend/src/App.vue` | 轮询合并 TT pending + 跳转按来源区分 |
| `py/tests/test_tt_delist_notification.py` | **新建**：接口 + 定时检测 + telegram 参数化测试 |

---

## Task 1: 数据库 — `tt_delist_notifications` 表

**Files:** `py/database.py`

- [ ] 在 `tt_delist_checks` 表定义之后追加 `tt_delist_notifications`（对齐 `delist_notifications`）：

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

- [ ] 确认迁移块已包含（`database.py` 的建表 SQL 与 GG `delist_notifications` 在同一批 `conn.execute` 或独立执行均可，走自动建表）。
- [ ] 用 `python -c "import database; database.get_db().close()"` 冒烟确认表创建无报错。

---

## Task 2: `telegram_sender.py` 标题参数化

**Files:** `py/telegram_sender.py`

- [ ] `_build_product_message(product_name, series_names, usernames, title="GG-Server")`：首行改为 `f"<b>【{title} 掉包通知】</b>"`。
- [ ] `send_product_delist_notification(config, product_name, series_names, usernames, title="GG-Server")`：透传 `title`。
- [ ] 既有 `main.py::_send_telegram_notifications` 不传 `title`，行为不变（仍 `【GG-Server 掉包通知】`）。

---

## Task 3: `tt_routes.py` — 手动检测补通知 + pending/dismiss

**Files:** `py/routes/tt_routes.py`

- [ ] **手动检测补通知**：`check_delist` 检测出掉包后，收集掉包包 → 调 `_send_tt_telegram_notifications(db, dropped_pkgs)`（需带 product_name/series_name/在跑人员）。掉包包信息需 JOIN `tt_products` 拿 product_name。
- [ ] **新增 `GET /api/tt/delist/pending`**（`@jwt_required()`，不加 `@tt_required`，与 GG `delist_pending` 一致）：
  - 查 `tt_delist_checks dc JOIN tt_packages pkg JOIN tt_products prod LEFT JOIN tt_delist_notifications dn`
  - 过滤：`is_delisted=1`、`prod.is_archived=0`、产品状态 active、包 status 非 dropped
  - 可见性：developer/admin 全部；否则 `prod.owner_id=?` 或 `pkg.product_id IN (SELECT product_id FROM tt_product_runners WHERE user_id=?)`
  - first/reminder 判定与 GG `delist_pending` 一致（180s），按产品聚合返回 `notifications`
- [ ] **新增 `POST /api/tt/delist/dismiss`**（`@jwt_required()`）：写 `tt_delist_notifications`（批量 package_ids），逻辑对齐 GG `delist_dismiss`。

---

## Task 4: `main.py` — 定时检测 + Telegram 发送 + 调度器 + trigger

**Files:** `py/main.py`

- [ ] 新增 `_send_tt_telegram_notifications(db, pkgs)`：
  - 读 `APP_CONFIG.get("tt_telegram", {})`，`bot_token`/`chat_id` 为空则 return
  - 按 `product_id` 分组，系列名去重
  - 在跑人员：`SELECT user_id FROM tt_product_runners WHERE product_id=?` → `SELECT telegram_username FROM users WHERE id IN (...)`
  - 调 `telegram_sender.send_product_delist_notification(config, product_name, series_names, usernames, title="TT-Server")`
- [ ] 新增 `_run_tt_delist_check_once()`（对齐 `_run_delist_check_once`）：
  - 查 `tt_packages pkg JOIN tt_products prod`，条件 `pkg.type='package'`、`pkg.url!=''`、包/产品状态正常、`prod.is_archived=0`
  - ThreadPoolExecutor 并行检测（走 `_build_delist_proxy_pool()`）
  - 写 `tt_delist_checks`（INSERT OR REPLACE），新掉包去重（对比旧 `is_delisted`）
  - 掉包 → 仅本轮新掉包调 `_send_tt_telegram_notifications`（**不发 Email**）
- [ ] 新增 `_start_tt_delist_scheduler()`：后台线程每小时一次，出错 60s 重试（对齐 `_start_delist_scheduler`）。在 `main.py` 启动处（`_start_delist_scheduler()` 旁）调用。
- [ ] 新增 `POST /api/admin/trigger-tt-delist-check`（仅 developer）：手动触发 `_run_tt_delist_check_once()`。

---

## Task 5: 前端 — API + 轮询合并 + 跳转

**Files:** `frontend/src/api/tt.js`、`frontend/src/App.vue`

- [ ] `tt.js` 新增：`getPendingDelist`、`dismissDelist`。
- [ ] `App.vue::checkDelistNotifications`：同时请求 GG `productsApi.getPendingDelist()` 与 TT `ttApi.getPendingDelist()`（TT 用 `Promise.allSettled` 或 try/catch，403 静默），合并 `notifications`。
- [ ] 弹窗 `onClick` 跳转按来源区分：GG → `/accounts/products?highlight_pkgs=...`；TT → `/tt/products?highlight_pkgs=...`。
- [ ] `onClose` dismiss 按来源调对应接口。
- [ ] 通知里为 TT 来源加平台标识（如 `platform: 'tt'`），供跳转/dismiss 判断。

---

## Task 6: 测试 + 验收

**Files:** `py/tests/test_tt_delist_notification.py`（新建）

- [ ] 复用 `test_tt_routes.py` / `test_delist_api.py` 的 fixture 与建数据 helper。
- [ ] 用例：
  - pending：普通 TT 用户只看自己（owner 或在跑）的掉包通知；developer 看全部
  - pending：first/reminder 判定（dismiss 后 180s 内不重复、超 180s 转 reminder）
  - dismiss：批量写 `tt_delist_notifications`
  - `_run_tt_delist_check_once`：mock `delist_checker.check_url_delisted` 与 `telegram_sender`，验证新掉包去重 + 只发一次 Telegram
  - `_send_tt_telegram_notifications`：tt_telegram 配置为空时静默跳过；在跑人员从 `tt_product_runners` 正确查取
  - `telegram_sender`：`title` 参数化后 GG/TT 标题不同
- [ ] `cd py && python -m pytest tests/ -v` 全绿。
- [ ] 前端 `npm run build` 重新构建（Tailscale 部署其他人才能看到）。

## 验收清单

- [ ] TT 产品页手动「是否掉包」检测到掉包 → TT 机器人收到群组通知（@在跑人员，标题 `【TT-Server 掉包通知】`）。
- [ ] 定时检测（或 developer 手动触发）掉包 → TT 机器人通知，GG 群不收到（独立机器人）。
- [ ] TT 平台用户浏览器弹窗提示，关闭后 3 分钟未处理再提醒。
- [ ] GG 掉包通知不受影响（回归）。
- [ ] 重启 Flask 后配置生效。
