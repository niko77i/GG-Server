# 掉包通知按产品聚合 — 设计文档

> **日期**: 2026-08-13
> **状态**: 待确认
> **关联迁移文档**: `docs/superpowers/specs/2026-07-31-spring-boot-migration-design.md`（本次将新增 v1.10 变更章节）

## 1. 需求描述

当前定时/手动掉包检测后，**每个掉包（package）** 各自触发一条通知：
- 前端每个包弹一个 `ElNotification` 弹窗
- Telegram 每个包发一条消息

由于一个产品（product）下常有多个包，一旦批量掉包会同时弹出大量弹窗、刷屏大量 Telegram 消息。

**目标**：将「一个产品」的掉包聚合为**一条通知**。

具体变更：

1. **前端弹窗**：一个产品统一为一个弹窗。弹窗展示：
   - 产品名（`product_name`）
   - 换行展示多个掉包的**系列名**（`series_name`，多个去重后逐行列出）
   - **不展示包名**（`package_name`）
   - 掉包 UI（列表标红）保持不变
   - 点击跳转 + 标红保持不变（改为定位到该产品，并高亮该产品下所有掉包包行）
2. **Telegram 通知**：一个产品的掉包统一为一条消息（产品名 + 多个系列名，不展示包名）。

## 2. 现状分析

### 2.1 后端（`py/main.py`）

| 位置 | 现状 |
|------|------|
| `_run_delist_check_once()` (L7742) | 定时检测，逐包写 `delist_checks`；对 `newly_delisted_list` 逐包调 `_send_telegram_notifications(db, [pkg], rids)` |
| `products_check_delist(pid)` (L3180) | 手动检测，逐包收集后构建 `tg_pkgs` 调 `_send_telegram_notifications(db, tg_pkgs, rids)` |
| `_send_telegram_notifications(db, pkgs, runner_ids)` (L7705) | 内部 `for pkg in pkgs` 逐包 `send_delist_notification` |
| `delist/pending` (L3314) | 按**包**返回 `notifications[]`，每项含 `package_id/product_id/product_name/package_name/series_name/url/type` |
| `delist/dismiss` (L3280) | 按单个 `package_id` 记录关闭时间 |

### 2.2 通知发送（`py/telegram_sender.py`）

`_build_message(pkg_info, usernames)` 目前按单包构建：产品 + 系列 + 包名 + 链接。

### 2.3 前端

| 位置 | 现状 |
|------|------|
| `App.vue` `checkDelistNotifications()` | 遍历 `notifications`（每项一个包），每包弹一个 `ElNotification`；`onClick` 跳 `/accounts/products?highlight_pkg=${package_id}`；`onClose` 调 `dismissDelist(package_id)` |
| `App.vue` 去重 | `_notifiedPkgIds` Set，key = `${package_id}-first` / `${package_id}-reminder-${reminder_count}` |
| `App.vue` 跨 Tab | `broadcast(MSG.DELIST_NOTIFIED/DELIST_DISMISSED)` 载荷为 `package_id` |
| `ProductPanel.vue` `scrollToHighlightedPackage()` | 读取 `route.query.highlight_pkg`，滚动到 `#pkg-{id}` 并闪烁红框 |
| `ProductCard.vue` | 包行标红 `pkg-row--delisted`（`is_delisted && status!=='dropped'`）——**保持不变** |

## 3. 技术方案

核心思路：**底层仍按包维护 `delist_notifications`（不改表结构），仅在上层（接口输出 + 弹窗 + Telegram）按产品聚合**。符合「纯增量原则」，不重构检测/去重/提醒核心逻辑。

### 3.1 后端 API 变更

#### 3.1.1 `GET /api/delist/pending` — 输出按产品聚合

查询逻辑不变（仍是当前用户作为 runner 的掉包且未 dropped 的包），但在返回前按 `product_id` 分组：

```json
{
  "success": true,
  "notifications": [
    {
      "product_id": 1,
      "product_name": "某游戏",
      "series_names": ["东南亚", "巴西"],   // 去重后的系列名列表
      "package_ids": [10, 11, 12],          // 该产品下所有掉包包 ID
      "type": "first",                       // "first" | "reminder"
      "reminder_count": 0
    }
  ]
}
```

分组与 `type` 判定规则（同一产品组内取「最紧急」）：

- 组内**任一**包 `first_notified == 0` → `type = "first"`
- 否则组内**任一**包已关闭且距今 ≥ 3 分钟 → `type = "reminder"`
- `series_names` 取组内各包 `series_name` 去重（空值丢弃）
- `package_ids` 为组内全部掉包包 ID（用于 dismiss 与跳转高亮）
- `reminder_count` 取组内 `reminder_count` 最大值

#### 3.1.2 `POST /api/delist/dismiss` — 支持批量

请求体改为：

```json
{ "package_ids": [10, 11, 12] }
```

对每个 `package_id` 复用现有单包逻辑（INSERT/UPDATE `delist_notifications`）。保留对旧字段 `package_id` 的兼容（若 `package_ids` 缺省则回退单包）。

### 3.2 Telegram 通知变更（`py/telegram_sender.py` + `py/main.py`）

`_build_message` 改为产品级构建，新增 `_build_product_message(product_name, series_names, usernames)`：

```
【GG-Server 掉包通知】

@carl567 @zhangsan
产品：某游戏
掉包系列：
· 东南亚
· 巴西

该产品的多个包已被下架，请尽快将包状态设置为"掉包"。
```

- 移除单包「包名」与「链接」行（链接按包区分，产品级不再展示）
- `series_names` 去重后逐行展示

`_send_telegram_notifications` 改为按产品分组后逐产品发送：

- 入参改为 `_send_telegram_notifications(db, pkgs)`（每个 pkg 需携带 `product_id`/`product_name`/`series_name`/`runner_ids`）
- 内部按 `product_id` 分组；每组抽取 `series_names`（去重）、合并 `runner_ids`（解析各 pkg 的 `runner_ids` 求并集）
- 每组调一次 `send_product_delist_notification(config, product_name, series_names, usernames)`

调用方改动：

| 调用方 | 改动 |
|--------|------|
| `_run_delist_check_once()` | 不再逐包循环，改为 `_send_telegram_notifications(db, newly_delisted_list)`（pkg 已含 `product_id`/`runner_ids`） |
| `products_check_delist()` | `tg_pkgs` 每个元素补 `product_id`（= `pid`）与 `runner_ids`，一次传入 |

### 3.3 前端变更

#### 3.3.1 `App.vue` `checkDelistNotifications()`

- 遍历聚合后的 `notifications`（每项一个产品）
- 每产品弹**一个** `ElNotification`：
  - title：`⚠️ 检测到包已掉包` / `⏰ 掉包提醒`（不变）
  - message：`【产品名】\n系列1\n系列2\n...\n请将包状态设置为"掉包"（点击跳转到对应包）`
- `onClick`：跳 `/accounts/products?highlight_pkgs=${package_ids.join(',')}`
- `onClose`：调 `dismissDelist(package_ids)`（批量）
- 去重 key 改为产品级：`${product_id}-first` / `${product_id}-reminder-${reminder_count}`
- 跨 Tab `broadcast` 载荷由 `package_id` 改为 `product_id` + `package_ids`

#### 3.3.2 `frontend/src/api/products.js`

- `dismissDelist(packageIds)` → `api.post('/delist/dismiss', { package_ids: packageIds })`

#### 3.3.3 `ProductPanel.vue` `scrollToHighlightedPackage()`

- 读取 `route.query.highlight_pkgs`（逗号分隔的多个 pkgId）
- 滚动到第一个 `#pkg-{id}`，并**依次闪烁红框**所有命中包行

#### 3.3.4 `ProductCard.vue` — **不变**

包行标红（`pkg-row--delisted`）逻辑保持不变。

## 4. 数据结构变更汇总

| 接口/对象 | 字段变化 |
|-----------|----------|
| `GET /api/delist/pending` | 每项由「单包」改为「产品聚合」：`package_id/package_name/url` 移除，新增 `package_ids[]/series_names[]`，`product_id/product_name/type/reminder_count` 保留 |
| `POST /api/delist/dismiss` | 入参 `package_id` → `package_ids[]`（兼容单值） |
| Telegram 消息体 | `pkg_info`（单包）→ `product_name + series_names[]` |

## 5. 涉及的文件

| 文件 | 变更类型 | 说明 |
|------|---------|------|
| `py/main.py` | 修改 | `delist_pending` 分组、`delist_dismiss` 批量、`_send_telegram_notifications` 分组、两个调用方 |
| `py/telegram_sender.py` | 修改 | 新增产品级消息构建 + 发送函数 |
| `frontend/src/App.vue` | 修改 | 弹窗聚合、去重 key、跳转、跨 Tab 载荷 |
| `frontend/src/api/products.js` | 修改 | `dismissDelist` 改批量 |
| `frontend/src/views/ProductPanel.vue` | 修改 | 多包跳转高亮 |
| `docs/superpowers/specs/2026-07-31-spring-boot-migration-design.md` | 修改 | 新增 v1.10 章节（见第 7 节） |

## 6. 边界情况

1. **同一产品多包共享同一系列名**：`series_names` 去重，避免重复行
2. **产品无有效系列名**（全为空）：`series_names` 为空，弹窗/消息仅显示产品名
3. **组内同时存在 first 与 reminder 包**：取 `first`（最紧急）
4. **跨产品**：定时检测的 `newly_delisted_list` 可跨产品，分组后按产品逐条发送
5. **未配置 Telegram**：`bot_token`/`chat_id` 空 → 跳过（不变）
6. **用户未绑定 telegram_username**：跳过 @ 提及（不变）
7. **旧字段兼容**：`dismiss` 仍接受单 `package_id`；`highlight_pkg` 跳转保留兼容（新参数 `highlight_pkgs`）

## 7. 迁移文档更新说明

在 `2026-07-31-spring-boot-migration-design.md` 顶部「变更记录」新增 **v1.10 变更**，并在正文补充：

- **9.6 Telegram 通知**：`TelegramSender.sendDelistNotification` 由 `PackageInfo`（单包）改为产品聚合（`ProductDelistInfo`：`productName + List<String> seriesNames`），一处描述产品级消息格式
- **DelistController / DelistService**：`delist/pending` 返回产品聚合结构、`delist/dismiss` 接受 `package_ids[]`
- 新增 `ProductDelistInfo` / `ProductDelistNotification` 响应 DTO 说明

## 8. 需要确认的问题

1. **系列名去重**：同一产品下多个包共享同一 `series_name` 时，弹窗/消息按去重后的系列名展示（默认「是」，避免重复行）—— 确认？
2. **跳转定位**：点击弹窗跳转到产品页后，默认「滚动到第一个掉包包行 + 闪烁高亮该产品下所有掉包包行」—— 确认？
3. **Telegram 消息移除链接行**：因链接按包区分，产品级不再展示「链接」—— 确认？（或改为列出所有掉包链接？）
4. **提醒计数**：聚合后 `reminder_count` 取组内最大值用于前端去重 key —— 确认？

---

请审阅以上设计，确认（或指出需调整处）后，我将制定实现计划并开始编码。
