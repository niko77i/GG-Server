# 写表失败统一治理（五期：GG 做表线接入）设计

> 一/二/三/四期分别治理了 TT 回收户清单、GG 域（我的看板/充值）、户管看板域、FB 报告做表域。
> 四期设计 §7 把「GG 做表线（`main.py` 那套 `sheets_sync_log` 读写）」划为**独立一期** —— 本文件即那一期。

## 1. 需求与背景

GG 做表（`/api/google-sheets/update-zuobiao`，前端「做表数据」页）是**自成一套**的写表线：

- **两个写点**：
  1. `py/main.py` 的 `@app.route("/api/google-sheets/update-zuobiao")`（`:7428`）→ 内含 `_do_sync`（`:7594`）
     → `_sync_sheets_background(_do_sync, _on_fail)`（`:7634`）
  2. `@app.route("/api/google-sheets/retry-sync")`（`:7672`）手动重试：读 `sheets_sync_log` 行 → 重建 → 直写
- **自己的日志表** `sheets_sync_log`（键 `(user_id, product_name)`）+ 自己的状态端点
  `/api/google-sheets/sync-status`（`:7646`）
- **前端**：`views/ToolkitView.vue`（`syncStatus` 轮询 `:376/:543`、`retrySync` `:580`）+ `api/google-sheets.js`

**四期之后 `sheets_sync_log` 只剩这一条线在写**（FB 已停写、GG 看板/充值与户管看板走的是 `sheet_write_log`）。

## 2. 现状核出的两个真缺陷（本期内由构造消失，不打补丁）

### 缺陷 A：中间态就报警

`_on_fail(status, err_msg)` 是三支：

```
synced       → DELETE 日志行
retry_failed → DELETE 日志行 + 记内存事件 _retry_failed_events[(uid, product)] = now
else(=failed)→ INSERT OR REPLACE 一条失败行（error_msg=_SHEETS_SYNC_FAILED_MSG + rows_json）
```

`_sync_sheets_background` 会先回**中间态 `failed`**（30s 重试在途）⇒ 那一支当场 INSERT 一条失败记录
⇒ `/sync-status` 在**重试窗口内**就能查到失败 ⇒ 前端显示一个**可能马上自愈的报错**。
这与 TT 充值在 2026-10-09 修掉的那处（`b340dd3`）是**同一形态**。

### 缺陷 B：终态通知是内存的、且一次性

终态失败走 `_retry_failed_events`（`py/main.py:7110` 的**进程内字典**）：

- **进程重启就丢** —— 用户永远不知道那次做表没写进去
- 消费端是 `_retry_failed_events.pop(event_key, None)`（`:7670`）⇒ **前端漏掉那一次轮询，事件被 pop 掉就永久消失**

这正是本治理机制要消灭的「静默丢失」。

## 3. 目标行为

1. 两个写点登记进 `sheet_write_log`，失败有**持久**记录、可查、可逐条重试。
2. 写表**保持异步**；端点不因写表阻塞或失败。
3. 提示**只在最终结果产生时**发出 —— `pending` / `failed` 不得触发任何用户可见提示；
   终态（含 `synced`）可提示。
4. GG 做表线**不再写 `sheets_sync_log`**（表与历史数据保留，见 §6）。
5. 中间态假报警（A）与内存一次性通知（B）**由构造消失**：统一机制只暴露终态、
   且记录落在 `sheet_write_log`（持久、可重试）。

## 4. 架构

### 4.1 target 契约

| 项 | 值 |
|---|---|
| target | `gg_zuobiao`（稳定英文 token） |
| `business_key` | `product_name`（该线的日志本就按 `(user_id, product_name)` 定位） |
| `payload` | `{"product_name": …}` |
| `rebuild` | 复用现有重建逻辑：按 `(user_id, product_name)` 查做表数据表 + join `products` 取 `sales_person`/`agency_ratio` |
| `rollback` | **不注册**（做表是 upsert 镜像类；重试幂等） |
| 注册位置 | 新建 **`py/routes/gg_zuobiao_target.py`**（与 `huguan_sheet_targets.py` / `fb_sheet_targets.py` 同形），`main.py` 顶层 import 注册 |
| `user_id` | = 触发者本人（做表是本人操作） |
| 线程约束 | 所有 service 与 DB 连接在**函数/闭包内**新建（后台线程里跑） |

**重建函数要从现有重试端点里**抽出来**成一个可复用的 helper**（例如
`_rebuild_zuobiao_rows(db, user_id, product_name)`），供 target 的 rebuild 用 ——
现在那段查询是内联在 `/google-sheets/retry-sync` 里的。

**不做「登记前先重建」**：四期需要那一步是因为它有两个**用户可操作**的重建失败原因
（「缺少日期，请重新保存」）。GG 做表线没有这类原因（数据是保存时刚写的），
失败走统一固定文案即可。

### 4.2 两个写点改造

| # | 改法 |
|---|---|
| 1 | `/api/google-sheets/update-zuobiao`：把 `_do_sync` + `_on_fail` + `_sync_sheets_background(...)` 整段换成 `run_write(target='gg_zuobiao', business_key=product_name, payload={product_name}, sync_fn=build_sync(...))`。**登记必须发生在该端点自身写库的 `commit()` 之后** —— 否则 `run_write` 会在**持有未提交写事务**的连接上 `record_pending`，另一条连接拿不到 SQLite 写锁 ⇒ 等满 `timeout=30` 抛 `database is locked`（三期在 `tt_accounts_routes` 修过两处同族缺陷）。⚠️ **该端点当前的 commit 顺序尚未逐行核实** —— 实施时必须先读现场确认（本文件不假设它已经在前）。响应保持 `{success, sheets_status: "syncing", db_saved}` 不变（前端兼容）。 |
| 2 | `/api/google-sheets/retry-sync`：**退役** —— 逐条重试改用三期已上线的 `/api/sheet-write/retry`（`target=gg_zuobiao` + `business_key`）。 |

> **例外规则（T4.5 补充）**：「rebuild 一律从 DB 重算」在**养户行**这类「请求侧产生、
> 不落库」的数据上，让位于「随 payload 携带，且**绝不截断**」。养户行是请求侧数据、
> 不落库（保存端点写库时只落非养户行），DB 重算不出来 ⇒ 由 `payload.yanghu_rows` 携带、
> 重建时追加在 rows 末尾；`payload.report_date` / `payload.region` 兜底纯养户行场景。
> 老日志行没有这些键 ⇒ `.get()` 缺省 ⇒ 行为与现状一致（不写养户行）。

> **重建只取该 `report_date` 的行（I1 修复）**：做表表**按月切**（表名按「操作人名 + `YYYY.MM`」匹配），
> 而 `ad_reports` 对同一产品累积**多个月份**的行（本仓无按月清理逻辑）。重建时**按
> `payload.report_date` 过滤 `rows_raw`，只取该 `report_date`（当日）的行** ——
> 过滤是**精确日期相等**，不是按「月」聚合（前端传的是**日级**日期）。
> 否则会把旧月行以最新月日期统一写进最新月那张表
> （表键含 date，旧月行查不到 ⇒ append 成当月日期的重复行 ⇒ 静默数据污染）。

### 4.3 前端（用户裁定：复用统一汇总区）

- `views/ToolkitView.vue`：把现有「状态 + 重试按钮」换成**统一的失败汇总区 + 逐条重试**，
  与 FB 数据管理页、户管看板卡片**同一套视觉与语汇**（3px 琥珀左脊柱 + warning 色调 +
  三态语汇 + `sheetWriteUi` 唯一文案源），**不新增视觉决策**。
  - 数据源：`sheetWriteApi.status({platform:'gg', target:'gg_zuobiao'})`
  - 逐条重试：`sheetWriteApi.retry({platform:'gg', target:'gg_zuobiao', businessKey})`
  - 重试后起**有界轮询**（3s × 15 ≈ 45s，覆盖后端 30s 重试窗口）——
    否则重试后该行进 `pending` 被列表隐藏（看起来像成功），**再次失败要到手动刷新才回来**（假成功）
  - 做表保存后**保留「当场反馈」**：与四期 FB 提取页同形 —— 保存后按 `business_key`（= 产品名）
    轮询统一 status，**中间态静默续查、终态才提示**，轮询预算必须覆盖后端 30s 重试窗口
    （四期在这里栽过：15s 的预算短于 30s 窗口 ⇒ 失败终态在该页永不可观测）
- **退役**：`/api/google-sheets/sync-status`、`/api/google-sheets/retry-sync` +
  `api/google-sheets.js` 里对应包装
- **保留不动**：`/api/google-sheets/status`、`/api/config/google-sheets`、
  `/api/google-sheets/update-zuobiao` 本体、`/api/google-sheets/sheets`

### 4.4 缺陷 A/B 如何由构造消失

- A：写表结果只由 `/api/sheet-write/status` 暴露，而它**只回需要提示的终态**（`ATTENTION`）⇒
  中间态 `failed` 不再有任何落库点，前端也无从显示。
- B：终态失败落在 `sheet_write_log`（持久、可重试），不再依赖进程内字典与 `pop` 一次性事件。

## 5. 数据结构

**不新增表、不改 schema。** 复用 `sheet_write_log`：

| 列 | 值 |
|---|---|
| `user_id` | 触发者本人 |
| `platform` | `'gg'` |
| `target` | `'gg_zuobiao'` |
| `business_key` | 产品名 |
| `payload_json` | `{product_name}` |
| `status` | 统一状态机（`pending`→`synced` / `retry_failed`） |

## 6. `sheets_sync_log` 的处置（沿用四期先例）

GG 做表线**停写**该表；**表与历史数据保留不动**（里面有 `rows_json` 快照，是排查证据）。
做完本期它是**零生产者**的死表 —— 但保留成本为零，且「删表」会丢掉历史证据，故不删。

## 7. 测试

- **保住既有判据**：现有关于该线同步状态/重试的用例，**迁到新路径、语义不降**，不得删除
- **新增**：两个写点各自登记正确的 `target` / `business_key` / `user_id`；
  终态失败落 `retry_failed` 且**不得**出现 `rolled_back`（零回滚守卫）；
  脱敏（`error_msg` = 统一固定文案、异常原文只进日志）；
  `/status` 的 `target` 过滤（同一 `business_key` 下与三期 target 互不遮蔽）；
  **写表不阻塞请求**（Sheets mock 成慢/抛错，端点仍快速返回 2xx）
- **变异验证（必做，且必须落在本期的改动面上）**：
  ① 给 `gg_zuobiao` 注册一个 `rollback` ⇒ 「零回滚」守卫用例必须红（且最终失败不再落 `retry_failed`）；
  ② 把登记挪到该端点 `commit()` 之前 ⇒ 必须红（或出现 `database is locked`）。
  > 「缺陷 A/B 由构造消失」不设变异 —— 它们的消失来自**机制本身**（`/status` 只回终态、
  > 记录落 `sheet_write_log`），本期不碰 `py/sheet_write.py`，没有可改坏的本地代码路径。
  > 它们的证据是**行为断言**（中间态不可见、终态持久可查），不是变异。
- 前端：`npm run build` + 人工清单（无前端测试套件）

## 8. 不做

1. 做表数据本身的读写语义、`/api/config/google-sheets` 配置界面、`/api/google-sheets/status`
2. **`sheets_sync_log` 删表/迁移** —— 保留
3. GG 其它已治理的写点（我的看板 / 充值 —— 二期已治理）
4. 业务回滚（镜像类）
5. 重设计视觉（复用已定稿方案）

## 9. 风险与已知代价

1. **前端换组件**：做表页那块状态展示要整体替换 —— 但视觉复用已定稿方案，零新增设计决策。
2. **退役两个端点**会牵动既有测试与前端调用方 ⇒ 必须**先换调用方、再删端点**（四期的执行顺序教训）。
3. 做表线此前**没有**「登记前先重建」这类可操作原因，故失败一律走统一固定文案 ——
   用户看到的是「表格同步失败，详情见服务端日志」而非更具体的定位建议（与三期其它 target 同口径）。
