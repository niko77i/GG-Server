# 写表失败统一治理（四期：FB 报告写表域接入）设计

> 一/二/三期分别治理了 TT 回收户清单、GG 域、户管看板域。
> 三期设计 §7 明确把「FB 域剩余写表点」划给四期 —— 本文件即那一期。

## 1. 需求与背景

FB 域的写表分两批，性质不同：

| 批次 | 位置 | 现状 |
|---|---|---|
| **A 账户域回写** | `fb_routes.py:607/662/667/732/736/919/920` | 走 `hd.writeback_rows` / `hd.writeback_fb_acceptor` ⇒ **三期已接入治理** ✓ |
| **B 报告做表写表** | `fb_routes.py` 的 3 个写点（见 §2） | **未治理** ✗ —— 本期对象 |

B 批是「FB 数据提取 → 写进 Google 做表」这条业务线，现状是**自成一套**：自建后台线程 /
请求线程直写 / 自己的日志表 `sheets_sync_log` / 自己的状态与重试端点 / 前端 toast。
它**有记录、非静默**，但有三个真问题：

1. **重试在请求线程里直接打 Google Sheets** —— 端点会阻塞在外部 API 上（慢、超时、失败即 500），
   违反三期确立的「业务端点的响应不得因写表而阻塞或失败」。
2. **没有自动重试**（三期机制有 30s 重试一次 + `sweep_stale` 收敛卡死行）。
3. **失败没有持久可见的清单** —— 只有一次性的 toast；错过就再也看不见，
   用户只能靠「重试同步」按钮瞎点。这正是本治理机制要消灭的形态。

## 2. 现状（运行时核实）

### 2.1 三个写点

| # | 位置 | 机制 | 问题 |
|---|---|---|---|
| 1 | `fb_routes.py:1751` → `_schedule_fb_sheets_write`（`:1798`） | **自建 `threading.Thread`（`:1832`）** → `gs.upsert_fb_reports(...)` → 写 `sheets_sync_log` 为 `synced`/`failed` | 绕开统一机制；无自动重试 |
| 2 | `fb_retry_sheets_sync` 单条分支（`:1948+`） | **请求线程直写** `gs.upsert_fb_reports(...)`，成功删行，失败 `error_msg=固定文案` + 返回 500 | 阻塞请求线程 |
| 3 | `fb_retry_sheets_sync` 批量分支（同一函数，最多 20 条） | 同上，逐条同步写，失败的收进 `failed[]` 回传 | 同上 |

### 2.2 可直接复用的重建逻辑

`_rebuild_fb_records(db, user_id, log_row)`：按 `(产品名, 线名, 日期)` 回查 `fb_ad_reports`
重建待写 `records`，返回 `(records, None)` 或 `(None, 失败原因)`。

它的 docstring 记录了一个关键事实：**`sheets_sync_log.rows_json` 不可靠** ——
写入时被 `[:10000]` 截断，每条 record 约 200 字符，超过约 50 条就从中间断开。
所以**本来就必须靠 DB 重建**。这正是统一治理要求的「rebuild 一律从 DB 重算」。

### 2.3 其他事实

- `gs.upsert_fb_reports(db, user_id, product_name, line_name, report_date, records)` —— **幂等**：
  一次调用写该组全部记录 ⇒ **重试天然安全**，可放心注册 `rollback=None`。
- **FB 是单表**：配置 key 为 `google_sheets_fb_{uid}`（`_get_sheet_config_key`），
  不存在 tt 那种「按户类型分 worksheet」的多表问题。
- `sheets_sync_log` **不是 FB 独占**：`main.py:7609–7754` 也在读写它，
  前端 `api/google-sheets.js:26` 走 `/google-sheets/sync-status` 读它 —— 那是 **GG 做表**那条线。
- 三个 FB 专属端点：`/fb/reports/last-sync`、`/fb/reports/sync-status/<id>`、`/fb/reports/retry-sync`。
- 前端消费：`FbDataExtract.vue:260`（`getSyncStatus` 轮询）、`FbDataManage.vue:157`（`retrySheetsSync`）。
  **`fb.js:80 lastSyncStatus` 零调用**（死 API 包装）。
- 既有测试：`py/tests/test_fb_sheets_retry.py`（多条）、`py/tests/test_fb_platform.py:660-719`
  —— 它们守的是**真缺陷**：「重建失败的原因必须回传前端，否则用户永远不知道哪条没成功、为什么」。

## 3. 目标行为

1. 三个写点全部登记进 `sheet_write_log`，失败有持久记录、可查、可重试。
2. 写表**保持异步**：端点不因写表阻塞或失败；**重试端点也异步化**（用户点完起轮询）。
3. 提示**只在终态**发出（`pending`/`failed` 不提示；**终态含 `synced` 可提示**）。
   > **勘误（2026-10-09 终审）**：原文括注把 `synced` 也写成「不提示」，与 §4.4
   > 「保存后轮询 → 终态 toast」及 Task 6 人工清单第 1 条矛盾。`synced` 是终态，可提示；
   > 提取页的成功确认（弹 ✅）是一次**显式用户动作的闭环**，不在禁止之列。
   >
   > **显式例外**：轮询预算耗尽后，提取页**单发一次**「结果未返回」告知
   > （`ElMessage.warning('写表结果未返回，请稍后到「数据管理」页查看或重试')`）。
   > 这不是「中间态报警」，而是「无法确认结果」的**一次**告知，把用户指到能查看/重试的页面 ——
   > 属对「只在终态提示」的有意偏离，**故记为例外**，非违例。
4. FB 不再写 `sheets_sync_log`（表与数据保留，GG 那条线继续用）。

## 4. 架构

### 4.1 target 契约

| 项 | 值 |
|---|---|
| target | `fb_report`（稳定英文 token） |
| `business_key` | `"{产品名}\|{线名}\|{日期}"` —— **仅作前端展示** |
| `payload` | `{"product_name":…, "line_name":…, "report_date":…}` —— **重建的权威来源** |
| `rebuild` | 复用 `_rebuild_fb_records`；失败时 `raise` 带原因 |
| `rollback` | **不注册**（镜像类；`upsert` 幂等 ⇒ 重试安全） |
| 注册位置 | 新建 **`py/routes/fb_sheet_targets.py`**（与 `huguan_sheet_targets.py` 同形），`main.py` 顶层 import 注册 |
| `user_id` | = 触发者本人（FB 做表是本人操作，不存在三期 #2 那种「给别人写表」的第三方） |

`business_key` 只作展示，是因为 T6 风格的汇总区要显示「是哪一组失败」；
**重建只认 payload** —— 名字里若含 `|`，拆 key 会拆错，payload 无此风险。

### 4.2 关键取舍：重建失败的原因怎么留住

三期的 `run_write` 落库前会把 `error_msg` 统一换成**固定文案**
（`_WRITE_FAILED_MSG`「表格同步失败，详情见服务端日志」），因为 `sheet_write_log.error_msg`
会被原样回给客户端（防 CWE-209，见 `test_security_hardening.py` 的 E11 系列）。

但 FB 的两个重建失败原因是**用户可操作的**：

- 「这条同步记录缺少日期，无法重建待写数据，请重新保存一次数据」
- 「找不到对应的原始数据，无法重建待写数据，请重新保存一次数据」

换成固定文案就把 `test_fb_sheets_retry.py` 守住的判据弄丢了。

**解法：登记前先重建一次。** 纯 DB 读、不碰 Sheets，失败就**当场**回 actionable 原因、
**不登记**（与现有 `err(why, 400)` 行为一致）；重建成功才登记。

- 好处：**不改一期已审的 `sheet_write.py`**；保住可操作原因；真正落到 `retry_failed`
  的只剩「Sheets 写失败」这类服务端问题，用固定文案是对的。
- 代价：请求线程多一次 DB 读（可忽略）。
- 残余：若数据在「登记」与「重试」之间消失，重试会落固定文案（少见，且提示「详情见服务端日志」）。

### 4.3 三个写点改造

| # | 改法 |
|---|---|
| 1 | `_schedule_fb_sheets_write` 改名为 **`_register_fb_report_write`**（改造后它不再「起后台线程」，而是「重建前置 + 登记」，旧名会误导）。**唯一调用点 `fb_routes.py:1751` 同步改**；`test_fb_platform.py:698` 的 docstring 里提到该名字，一并改。 |
| 2 | 重试单条：重建前置 → 不可重建则 `err(why, 400)`；可重建则 `run_write` 并回「已受理」 |
| 3 | 重试批量：逐组重建；可重建的走 `run_write_many`（**一个后台线程、N 行日志**）；不可重建的收进 `failed[]` 原样回传 |

**`_rebuild_fb_records` 的签名要改**：现签名为 `(db, user_id, log_row)`，依赖 `log_row` 的
`report_date` / `product_name` / `line_name` 三列。新路径没有 `sheets_sync_log` 行可传，
故改为收三元组：**`(db, user_id, product_name, line_name, report_date)`**。
旧签名只有即将退役的那两条重试路径在用，改完即无遗留调用者。

写表值不在请求线程碰 Sheets；`run_write` / `run_write_many` 的签名与实现**一字不改**。

### 4.4 前端

- **`FbDataExtract.vue`**：保留「保存后轮询 → 终态 toast」的当场反馈，
  只把数据源从 `fbApi.getSyncStatus(sync_log_id)` 换成
  `sheetWriteApi.status({platform:'fb', target:'fb_report', businessKey})`；
  终态文案复用 `sheetWriteHint` / `sheetWriteTone`（全仓唯一文案源）。
  保存接口的响应把 `sync_log_id` 换成 `business_key`。
- **`FbDataManage.vue`**：新增**页级失败汇总区** —— 按 (产品,线,日期) 列出失败的写表任务，
  每条带自己的重试按钮。**复用 T6 卡片已 `/frontend-design` 定稿的视觉方案**
  （3px 琥珀左脊柱 + warning 色调 + 三态语汇），不新增视觉决策。
  原「重试同步」按钮改为「重试全部失败的」。
  - 数据源：`sheetWriteApi.status({platform:'fb', target:'fb_report'})`（带 `target` 过滤，
    防与三期 target 互相遮蔽）
  - 逐条重试：`sheetWriteApi.retry({platform:'fb', target:'fb_report', businessKey})`
    —— 即**复用三期已上线的 `/api/sheet-write/retry`**，FB 不新增重试端点
  - 重试后起有界轮询（与 T6 卡片同形：3s × 15 次，覆盖 30s 重试窗口）
- **退役**：三个 FB 专属端点 + `fb.js` 里对应的三个包装（含零调用的 `lastSyncStatus`）。

### 4.5 `sheets_sync_log` 与存量（用户裁定：保留不动）

FB 停写该表；表与历史数据**原样保留**给 GG 做表那条线，**不做迁移**。

已知代价：现存 FB 的 `failed` 行**失去 UI 入口**（前端已换源）。
如需追溯，直接查 `sheets_sync_log` 表（数据未丢，只是不再展示）。

## 5. 数据结构

**不新增表、不改 schema。** 复用 `sheet_write_log`：

| 列 | 值 |
|---|---|
| `user_id` | 触发者本人（= 表主人） |
| `platform` | `'fb'` |
| `target` | `'fb_report'` |
| `business_key` | `产品\|线\|日期` |
| `payload_json` | `{product_name, line_name, report_date}` |
| `status` | 走统一状态机（`pending`→`synced` / `retry_failed`） |

## 6. 测试

**保住既有判据（改成对新路径断言，语义不降）**
- 重建失败的原因回传（`test_fb_sheets_retry.py` 那几条）
- 落库文案不泄露异常原文（`test_fb_platform.py:660-719`）

**新增**
- 三个写点各自登记正确的 `target` / `business_key` / `user_id`
- 终态失败落 `retry_failed`，**不得**出现 `rolled_back`（零回滚守卫）
- 批量重试走 `run_write_many` 且**覆盖全部 N 组**（单键工厂会漏写，二期踩过）
- 重建前置失败 ⇒ **不登记**（零行）且回 actionable 原因
- `/status` 的 `target` 过滤：同一 `business_key` 下 `fb_report` 与三期 target 互不遮蔽
- **写表不阻塞请求**：Sheets 层 mock 成慢/抛错，端点仍应快速返回 2xx

**变异验证（必做）**
- 把批量重试的 N 组改成只写第一组 ⇒ 对应用例必须红
- 去掉「重建前置」，让不可重建的行照样登记 ⇒ 对应用例必须红

## 7. 不做

1. **GG 做表线**（`main.py` 里那套 `sheets_sync_log` 读写）—— 独立一期
2. **`sheets_sync_log` 迁移/清理** —— 用户裁定保留不动（§4.5）
3. **FB 账户域回写** —— 三期已治理
4. **业务回滚** —— 镜像类
5. **重设计视觉** —— 复用 T6 已定稿方案

## 8. 风险与已知代价

1. **重试从「当场出结果」变「异步 + 轮询」** —— 用户已裁定接受（与三期 TT/GG 手感一致）。
2. **退役端点**会让现存 FB `failed` 行失去 UI 入口 —— 用户已裁定接受，数据保留在表里。
3. **重建前置多一次 DB 读** —— 可忽略。
4. 端点退役会牵动既有测试（`test_fb_sheets_retry.py` / `test_fb_platform.py`）——
   必须把判据**迁到新路径**而不是删掉。
