# 上万户规模下的看板同步延迟与数据安全治理

> **日期**: 2026-10-07
> **状态**: 待用户复核
> **落点**: **只做 GG-Server（Python）**。用户 2026-10-07 裁定，不并入 LM-Server（Spring Boot）迁移。
> **覆盖平台**: gg / tt / fb 三个（GG-Server 是服务三平台的项目，不是只做 gg 平台）

---

## 1. 需求

用户 2026-10-07 原话：

> 「现在广告账户管理，后续每个系统都是上万个户，会对系统性能有影响吗」
> 「先完成设计文档，重点就是大量户情况下，不要让用户觉得有延迟的感觉，越快越好，但要保证数据的安全」

### 1.1 三条硬指标（用户勾选）

| # | 场景 | 目标 |
|---|---|---|
| ① | 系统→表：改完切到 Google 表里看 | 基本即时（秒级） |
| ② | 表→系统：点「从表同步」等结果 | 不撞前端 30s 硬超时 |
| ③ | 系统内部：列表 / 翻页 / 批量操作 | 跟手，不卡浏览器 |

用户明确**未**把「投手在表里改完、系统里多快看到」列为硬指标（投手侧仅要求不被拖累）。

### 1.2 三条安全边界（用户勾选，都不可牺牲）

| # | 担心 | 本设计的对应机制 |
|---|---|---|
| S1 | **攒批合并会丢中间改动** | 脏表 merge 取 cells **并集**（§4.2） |
| S2 | **写失败静默** | 脏行写成功才删 + 落 `sheet_write_log`（§4.7） |
| S3 | **并发覆盖（静默丢更新）** | 按 `(spreadsheet_id, sheet_name)` 的单写者锁（§4.5） |

用户未勾选「写错行/列」，但 §4.4 的目标注册表仍显式处理它 —— 见该节的定位列风险。

### 1.3 用户对分页的特别强调

> 「特别是户管的分页，一定要控制好，不要全量返回 冲烂浏览器，这个系统是为了方便使用的，不是一用就卡」

→ 分页独立成 §6，并补一条通用闸门：**所有列表端点的 `size` 参数加服务端上限**。

---

## 2. 现状诊断（已核实的代码事实）

### 2.1 实测数据（2026-10-07）

| 项 | 值 | 来源 |
|---|---|---|
| `accounts`（GG） | 1912 户 | `temp/app.db` 只读查询 |
| `tt_accounts` | 58 户 | 同上 |
| `fb_accounts` | 0 户 | 同上 |
| `packages` | 2937 个 | 同上 |
| `app.db` 体积 | 6.9 MB | 文件系统 |
| SQLite 版本 | 3.45.1（`SQLITE_LIMIT_VARIABLE_NUMBER` = 32766） | `sqlite3.sqlite_version` |
| Sheets 凭据类型 | **service_account** | `config/fit-boulevard-503111-u4-812bc02c2000.json` |

→ GG 已在 1912 户，距「上万户」约 5 倍；TT/FB 尚在起步。**设计按 1 万户/平台做预算。**

### 2.2 配额真相（决定了「能多快」）

凭据是**服务账号**，整个服务器共用**一个** Google API 身份。因此官方配额里的
「每分钟 60 次/用户」不是每个自然人用户的配额，而是**全服务器共享**的：

| | 每分钟/项目 | 每分钟/用户 |
|---|---|---|
| 读请求 | 300 | **60** |
| 写请求 | 300 | **60** |

读写**分开计**。两条对本设计极关键：

1. **一次 `values.batchUpdate` 无论含多少子请求，只算 1 个 API 请求** —— 这是方案 A 的核心收益：合并写 1 万户仍然只是 1 个写请求。
2. 撞配额返回 **429**，官方建议指数退避。**当前全仓没有任何 429 退避**（§4.7）。

### 2.3 三类看板表，定位列各不相同

这是本设计最容易踩的坑：`update_rows_by_account_id` 的 `key_col` **默认 `"C"`**，漏传不报错、静默定位到错误的行。

| 表 | 谁的 | 配置来源 | 账户ID 定位列 | 列范围 | 规模 |
|---|---|---|---|---|---|
| **户管看板** | 每个户管一张 | `huguan_dashboard_{uid}` | GG/TT = **C**，FB = **D** | A:N / A:M / A:Q | **上万行** |
| **GG「我的看板」** | 每个投手一张 | `sheet_mappings` / `sheet_mappings_{uid}` | **B** | A:H | 几十~几百行 |
| **TT「我的看板」** | 每个投手一张 | `tt_sheet_id` + `tt_sheet_mappings_{uid}` | **D** | 10 列 | 几十~几百行 |

- 户管看板的 `KEY_COL = {"gg": "C", "tt": "C", "fb": "D"}`（`huguan_dashboard.py:84`）
- GG 我的看板按 **B 列** 定位（`google_sheets_service.py:693-723`，即 `row[1]`）
- TT 我的看板按 **D 列** 定位（`huguan_dashboard.py:1749`，显式传 `key_col="D"`）

用户 2026-10-07 指出：**大量改户的角色是户管，且户管与运营之间的表有差别。** 据此把
「目标表」提升为设计的一等维度（§4.4）。

### 2.4 病灶清单

| # | 位置 | 病灶 | 影响 |
|---|---|---|---|
| B1 | `main.py:5473-5481` `_sync_back_to_dashboard` | 逐户调 2 次 `update_cell_by_account_id`，而该函数**每次调用重读整张 A:H**（`google_sheets_service.py:716`）+ 写一个格 | **O(N²)**。1912 户 = 3824 读 + 3824 写；1 万户 = 各 2 万次 |
| B2 | `main.py:5205` `_sync_batch_dashboard` | 同一端点内**另一条**逐户路径，与 `main.py:5158` 的新批量路径**并存**，同一操作写两遍 | 同上；且是重复劳动 |
| B3 | `tt_accounts_routes.py:1190-1229` `sync_from_sheet` | 循环内逐行 `SELECT * FROM tt_accounts WHERE advertiser_id=?`、逐行 `_ensure_bc`/`_ensure_agent`、逐行 `db.commit()` | 1 万行 ≈ 2~5 万次查询 + 2~3 万次 commit，撞前端 30s 超时 |
| B4 | `main.py:5020` `GET /api/accounts/deleted` | **无分页**，全量返回 → `AccountDeletedModal.vue:64` 全量 DOM + 前端过滤 | 上万行卡死浏览器 |
| B5 | `tt_accounts_routes.py:700` `GET /api/tt/accounts/deleted` | 同上 → `TtAccountDeletedModal.vue:68` | 同上 |
| B6 | `fb_routes.py:311`、`488` | 列表每行**单独查一次** BM（N+1） | 常数级（≤页大小），但每页多几百次往返 |
| B7 | 全仓 **15 处** `size = int(request.args.get("size", …))` | **无上限** | 任何客户端 `size=999999` 即可绕过所有分页 |
| B8 | `_sync_sheets_background`（`main.py:8067`） | 每次调用起**一个裸线程**，无池无上限；失败仅固定 30s 重试一次，**无 429 退避** | 批量操作瞬时起大量线程；撞配额后持续撞墙 |

### 2.5 已经是对的，不要动

| 位置 | 为什么是对的 |
|---|---|
| `dashboard_push`（`huguan_dashboard_routes.py:194`） | 手动全量刷新，**已经是**一次 `update_rows_by_account_id`，且**自己抓撤回快照** |
| `main.py:5306-5443` GG 从表同步 | 已是批量 `IN` 查 + 内存 diff + **末尾一次 commit** |
| `update_rows_by_account_id`（`google_sheets_service.py:754`） | 已把所有行合并进**一次** `values.batchUpdate` |
| `probe_concurrent_write`（`google_sheets_service.py:63`） | 并发探测一期，key 恰好就是本设计要用的 `(spreadsheet_id, sheet_name)` |

---

## 3. 目标 / 非目标

### 3.1 目标

1. 系统→表的自动回写改为**合并 + 按表序列化 + 持久化**的冲刷，延迟秒级且不撞配额
2. 表→系统的落库改为**批量**，1 万行落在 30s 内
3. 所有列表端点**有服务端上限**，已删除列表**分页**
4. 三条安全边界 S1/S2/S3 全部满足

### 3.2 非目标（明确不做）

1. 改 `dashboard_push` 的手动全量刷新语义（它已正确，且撤回快照绑在它上面）
2. 改撤回（`huguan_sync_undo`）的语义与快照时机 —— 自动回写路径本来就不写快照（撤回规格决策 4）
3. 把从表同步改成后台任务 + 进度轮询（YAGNI，见 §5.4 的判断阈值）
4. 给并发探测一期补历史对账（那是另一件事）
5. 压缩跨投手扇出的**请求数**（API 一次只能打一张表，见 §4.6）
6. 投手侧「表→系统」的实时性（用户未列为硬指标）

---

## 4. 架构：写表通道（①）

### 4.1 数据模型

```sql
CREATE TABLE IF NOT EXISTS sheet_dirty_cells (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    scope_id    INTEGER NOT NULL REFERENCES users(id),  -- 户管 uid（户管看板）/ 投手 uid（我的看板）
    target      TEXT    NOT NULL,                       -- 'huguan_dashboard' | 'my_dashboard'
    platform    TEXT    NOT NULL,                       -- gg / tt / fb
    account_id  TEXT    NOT NULL,                       -- 业务键，不用行主键
    cells_json  TEXT    NOT NULL DEFAULT '{}',          -- {列字母: 值}
    enqueued_at TEXT    DEFAULT (datetime('now','localtime')),
    UNIQUE(scope_id, target, platform, account_id)
);
CREATE INDEX IF NOT EXISTS idx_sdc_flush ON sheet_dirty_cells(scope_id, target, platform);
```

**为什么是 `(scope_id, target, platform, account_id)` 而不是 `(user_id, platform, account_id)`**：
同一户可能**同时**要写户管看板和某个投手的表，两者列不同、表不同、定位列不同，必须是两行。

**为什么存业务键 `account_id` 而不是行主键**：与撤回规格 §5.2 同口径 —— 反查即可，更抗数据变化。

**为什么 `target` 是英文 token**：沿用 `sheet_write_log.target` 的稳定 token 惯例，改中文文案不影响契约。

**删用户清理**：本表 `REFERENCES users(id)` 且无 `ON DELETE`，而连接开着 `PRAGMA foreign_keys=ON`
（`database.py:43`）。按仓库既有口径（撤回规格 §5.4），**必须把 `sheet_dirty_cells` 加进
`admin_delete_user` 的关联清理清单**，否则删任何有脏行的用户都会以 `FOREIGN KEY constraint failed` 收场。

### 4.2 入队：一条 SQL 完成原子合并（S1 的守卫）

```sql
INSERT INTO sheet_dirty_cells(scope_id, target, platform, account_id, cells_json)
VALUES(?,?,?,?,?)
ON CONFLICT(scope_id, target, platform, account_id)
DO UPDATE SET cells_json = json_patch(sheet_dirty_cells.cells_json, excluded.cells_json)
```

`json_patch` 的语义正是「同名键覆盖、不同键保留」。2026-10-07 已实测验证：连续三次入队
`{F:死亡}` → `{M:备注}` → `{F:存活,G:张三}`，最终 cells 为三列的并集，F 取最后一次。

这一条 SQL 同时解决三件事：

1. **不丢中间改动**（S1）：同一户先改状态（F 列）再改备注（M 列），两次入队后两列都在，不是后者覆盖前者
2. **无读改写竞态**：不需要「先读 JSON 再合并再写回」，并发入队也不会互相冲掉
3. **幂等**：同一列重复入队只是覆盖成同值

**入队必须与业务变更同一个事务**：写操作改完库、在**同一事务里**调 `queue_cells(db, …)`，一起 `commit`。

- 业务回滚 → 脏行一起没，表不会被写上一次没落库的改动
- 业务提交 → 脏行一定在，不存在「库改了但没入队」的静默丢失窗口

这是 S2 的地基：**入队本身不会失败**（纯本地 SQLite 写，与业务同事务），所以失败只可能
发生在后面真正的 Sheets 调用上，而那时脏行还在库里。

### 4.3 合并的语义边界：cells 是「整列快照」而非「增量差值」

`cells_for_row`（`huguan_dashboard.py:104`）产出的是该行**所有可写列**的当前值，不是增量。
因此单户入队时写的是「这一户现在长什么样」，多户合并后每户仍是各自的完整列集。

**后果要写进实现注意事项**：不能把「用户 A 改了 X 户的状态」和「用户 B 改了 X 户的备注」
理解成两次增量 —— 后者入队时 `cells_for_row` 已经带上了它读到的状态值。若两者读库时刻
不同，先入队者可能被后入队者的**陈旧但完整**的列集覆盖。

**这是本设计已知的语义代价**，与现状**完全一致**（现状每次回写也是整列集），**不是新增风险**。
真正的防重依赖 S3 的单写者序列化 + 每次入队前重新读库。列入 §10 风险表。

### 4.4 目标注册表（声明式，加表 = 加一行）

用户 2026-10-07：**「现在系统其实并不完善，后续可能又有变化」**。故目标是**一张声明式的表**，
冲刷引擎不出现任何 `if target == …` 分支：

| target | platform | 解析函数（冲刷时调用） | key_col | 列规格 |
|---|---|---|---|---|
| `huguan_dashboard` | gg | `hd.get_platform_config(db, uid, "gg")` | `C` | `COLUMN_SPEC["gg"]` |
| `huguan_dashboard` | tt | `hd.get_platform_config(db, uid, "tt")` | `C` | `COLUMN_SPEC["tt"]` |
| `huguan_dashboard` | fb | `hd.get_platform_config(db, uid, "fb")` | `D` | `COLUMN_SPEC["fb"]` |
| `my_dashboard` | gg | `main._get_my_dashboard_name` + `_get_sync_spreadsheet_id` | **`B`** | 8 列（`update_cell_by_account_id` 布局） |
| `my_dashboard` | tt | `hd._operator_dashboard_name` + `tags.tt_sheet_id` | **`D`** | 10 列 |

注册表项的形状：

```python
TARGETS = {
    ("huguan_dashboard", "gg"): Resolver(spreadsheet=…, sheet_name=…, key_col="C"),
    …
}
```

**两条硬性约束**（写进实现注意事项，避免将来加表时踩）：

1. **配置在冲刷时解析，不存进脏表** —— 沿用治理规格 §4.3 的口径：户管改了配置，重试要写进**新表**。
2. **解析不出 `key_col` 必须显式失败，绝不回落默认值**。`update_rows_by_account_id` 默认 `"C"`，
   而 GG 我的看板是 `B`、FB 户管看板与 TT 我的看板是 `D` —— 回落就是静默写错行。
   冲刷器遇到无法解析的目标：**保留脏行 + 落 `sheet_write_log` 报错**，不猜测。

### 4.5 冲刷协议：按表序列化（S3 的守卫）

后台线程池（初始 4 worker），周期 `I`（见 §4.6）：

```
每轮：
  按 (scope_id, target, platform) 取脏行
  → 用注册表解析各自配置，得到 (spreadsheet_id, sheet_name)
  → 聚合成「表级任务」，每张表带上它的全部脏行
  逐表任务：
      拿不到该表的锁 → 跳过（别的 worker 正在写这张表），下轮再来
      拿到锁 → 读一次定位列 → 合并该表所有脏户的 cells
             → 一次 batchUpdate（按行分块，见 §4.7）
             → 成功：删掉这批脏行的 id
             → 失败：保留脏行（下轮重试）+ 落 sheet_write_log
```

**锁的粒度是 `(spreadsheet_id, sheet_name)`** —— 与 `probe_concurrent_write` 现成算出的 key
完全一致。**同一张表永远只有一个写者在途**，read-modify-write 竞争从根上消失（S3）。

用 `try_lock` **跳过**而非阻塞等待：避免一张慢表把 worker 全占住。

**这同时是并发探测规格 §9 里二期待定的那把锁**，而且带着批量与持久化。若将来探测数据显示
确有并发，可直接引用本实现，无需另做。

### 4.6 自适应周期（把「越快越好」与「不撞配额」做成同一件事）

每张表冲刷一轮 = 1 读 + 1 写。设周期 `I` 秒、本轮有 `T` 张脏表，每分钟消耗 `T × 60/I` 次读、同次写。
留一半配额给手动按钮、充值、回收清单等既有写表点，得 **`I ≥ 2T`**：

```
I = min(30, max(2 × T, 1.5))    # 秒
```

| 本轮脏表数 T | 周期 I | 用户感知 |
|---|---|---|
| 1 | 2s | ~2s ✅ |
| 3 | 6s | ~6s |
| 10 | 20s | ~20s |
| ≥15 | 30s（封顶） | ~30s |

**正常情况几乎总落在 2s 那一档** —— 并发探测规格实测的历史写入量是 13 次/**天**，配额有三个数量级
余量，`T = 1` 是常态。表多时才自动放慢，不会撞墙。30s 封顶正好与治理规格的 30s 重试窗口对齐。

**已知代价**：脏表多时延迟会退到 30s。用户 2026-10-07 已确认接受（「可以」）。

### 4.7 失败、重试与 429 退避（S2 的守卫）

- 冲刷失败 → **脏行不删**，下轮重试，天然无限重试
- 失败要落既有 `sheet_write_log`，复用现成的 status 机与前端提示链路
- 户管看板属**镜像类**，按治理规格只提示 + 重试，**不回滚**（`snapshot=None`）
- **最终失败口径沿用治理规格的时序**：同一批脏行连续失败超过 **30 秒** 落 `retry_failed` 并提示，
  之后继续重试但**不再重复打扰**
- **新增 429 退避**（当前全仓没有）：识别 HTTP 429 → 指数退避（1s/2s/4s/… 封顶 60s），
  并**临时抬高本轮周期 `I`**，退避恢复后回落。没有这条，撞配额后会持续撞墙

**`values.batchUpdate` 按行分块**：代码现状假设「一次刷新通常几百行…无需分块」
（`google_sheets_service.py:792`）。1 万户时必须分块，建议**每 2000 行一个 batchUpdate**。
按 §2.2，分块后 1 万户 = 5 个写请求，仍然极省。

### 4.8 与手动「刷新到看板」的关系

`dashboard_push`（`huguan_dashboard_routes.py:194`）**不动**（含它自己的撤回快照）。但两者会互相踩，
要加两条规则：

1. **共用同一把表锁**：手动推送也要先拿该表的锁，否则推送与冲刷并发写同一张表 —— 正是 S3
2. **成功推送吞掉旧脏行**：推送开始读库时记下 `max(dirty.id)`，写表成功后删掉 `id <= 该值` 的脏行。
   理由：全量推送已把每个户的当前值都写上去，这些脏行已被**包含**，留着只会白费配额。
   推送期间**新入队**的脏行 id 更大，不在区间内，保留照常冲刷

**撤回快照无需重新定义抓取时机**：核实过，自动回写路径（`push_rows` / `writeback_rows`）本来就
**不写** `huguan_sync_undo` —— 撤回只覆盖两个手动按钮（撤回规格决策 4 + §十测试 9）。故本节只加
「串行化 + 吞并」两条规则，**不动快照语义**。

### 4.9 崩溃恢复

脏行持久化在库里，进程重启后冲刷器照常捡起未完成的 —— **无需特殊恢复逻辑**。这正是
方案 B（纯内存队列）被否掉的直接原因：内存队列一重启就丢，等于静默丢更新。

---

## 5. 表 → 系统落库（②）

### 5.1 形状：把 GG 的搬给 TT

GG 侧**已经是对的**（`main.py:5306` 批量 `IN` 查 + 内存 diff + `main.py:5443` 末尾一次 commit）。
问题只在 TT 的 `sync_from_sheet`（`tt_accounts_routes.py:1190-1229`）。

### 5.2 四步改法

1. 读表后**一次性批量**查现有账户（`IN` + `chunk(900)`）建内存索引
2. `_ensure_bc` / `_ensure_agent` 改为**先扫全表收集所有名字** → 批量查 + 批量建 → 建
   `name → id` 内存映射；循环内只查内存，不再打库
3. 落库**分批 commit（每 500 行）** —— 既不逐行（现状），也不是单个长事务。
   WAL 下单个长写事务会持有写锁让其它写请求排队，分批把锁窗口收短
4. 沿用 GG 的「**逐条 try 收集 errors**」：一条坏数据不阻塞其余，与逐行 commit 时代的
   容错口径一致（分块事务 + 逐条 try 后，容错性与现状**不降级**）

### 5.3 事务语义的变更（须显式记录）

现状是逐行 commit ⇒ 中途失败留**半截**数据。改后是分批 commit ⇒ 中途失败留**整批**数据。
两者都不是全局原子。撤回能力不受影响（`sync` 方向撤回用的是快照 + CAS，与提交粒度无关）。

### 5.4 前端 30s 超时的处理

改后 1 万行预计：读表 2~5s + 批量查 <1s + 落库 1~3s ≈ **5~10s**，在 30s 内。

**故本期不改后台任务 + 进度轮询**（YAGNI）。判断阈值写在这里：**若实测超过 20s，再考虑后台化**，
届时复用仓库既有的轮询范式（`ToolkitView.vue` 的 `startZbSyncPolling`）。

---

## 6. 分页与列表（③）

用户特别强调：**「不要全量返回 冲烂浏览器」**。

### 6.1 两个无分页端点（必修）

| 端点 | 前端消费者 | 改法 |
|---|---|---|
| `GET /api/accounts/deleted`（`main.py:5020`） | `AccountDeletedModal.vue:64`（全量 DOM + 前端过滤） | 服务端补 `page`/`size`/`total`，照 FB 的形状（`fb_routes.py:457`）；前端改分页渲染 + 服务端搜索 |
| `GET /api/tt/accounts/deleted`（`tt_accounts_routes.py:700`） | `TtAccountDeletedModal.vue:68` | 同上 |

FB 的已删除列表**已经分页**（`fb_routes.py:457`），照它抄。

### 6.2 通用闸门：`size` 上限（B7）

全仓 **15 处** `size = int(request.args.get("size", …))` 全部无上限。

**复用既有的 `helpers.parse_pagination`，不新增 helper**：

```python
# py/routes/helpers.py:74 —— 现状：size 上限 100
def parse_pagination(maximum: int = 500) -> tuple[int, int]:
    """解析分页参数，返回 (page, size)。越界一律钳制，不报错。"""
    page = max(1, int(request.args.get("page", 1) or 1))
    size = max(1, min(maximum, int(request.args.get("size", 20) or 20)))
    return page, size
```

- **它是死代码**：全仓只此一处定义、**零调用点**，所以把上限从 100 提到 **500** 不影响任何现有端点
- 上限取 500 的理由：前端最大页尺寸是 200（`TtAccountPanel.vue:307`），留 2.5 倍余量
- **钳制而非报错**：这些端点的既有契约是「坏参数走默认值」（如 `int(request.args.get("page", 1) or 1)`），
  报错会改变前端行为
- 除 `size` 外还顺带钳制了 `page ≥ 1` —— 现状的裸 `int()` 允许负数页，`LIMIT ? OFFSET -N` 在
  SQLite 里等价于 OFFSET 0，是个静默的错值

应用点：`main.py:2775/3513/4074/6005/8423/9987`、`tt_accounts_routes.py:211`、
`fb_routes.py:21/63/270/464/638/921/1146/1653`。

### 6.3 FB 列表 N+1（B6）

`fb_routes.py:311`、`488`：每行单独查 BM。改为 `WHERE ab.account_id IN (…)` 一次查回 + 内存按
`account_id` 分组。页大小上限 500 ⇒ 最多 1 次替代 500 次。

### 6.4 `IN (...)` 分块

SQLite 3.45.1 的变量上限是 32766。1 万户现在能跑，但**超过 3.2 万户必然抛
`too many SQL variables`**。加统一 `chunk(900)` helper（900 取整、留足余量）。

应用点：`main.py:5070/5155`、`batch-lookup`（`main.py:4337`）、GG sync（`main.py:5307`）、
`huguan_dashboard.py:500/956/1331`，以及 §5 新增的批量查询。

> 行号会随后续改动漂移，定位时以**函数名**为准。

---

## 7. 配额预算（汇总）

| 消耗方 | 单次请求数 | 频次 |
|---|---|---|
| 冲刷（按表） | 1 读 + 1 写 | 由 §4.6 的 `I` 控制 |
| 其中分块 | 每 2000 行 +1 写 | 1 万户 = 5 写 |
| 手动「刷新到看板」 | 1 读（快照）+ 1 读（定位）+ 1~5 写 | 用户点击 |
| 从表同步 | 1 读 | 用户点击 |
| 充值 / 回收清单 / 做表 | 各 1 读 + 1 写 | 既有 |

写写、读读**分开计**，各自 60/分钟。§4.6 的 `I ≥ 2T` 已按「留一半余量」推导。

---

## 8. 涉及文件

| 文件 | 动作 | 职责 |
|---|---|---|
| `py/database.py` | 修改 | `sheet_dirty_cells` 建表 + 索引；`admin_delete_user` 清理清单加本表 |
| `py/huguan_dashboard.py` | 修改 | 新增 `TARGETS` 注册表 + `queue_cells`；`push_rows` / `push_remark_to_operator_dashboard` 改为入队 |
| `py/sheet_flush.py` | **新建** | 冲刷器：分组、按表锁、合并、batchUpdate、失败落 `sheet_write_log`、429 退避、自适应周期 |
| `py/main.py` | 修改 | 删除 `_sync_back_to_dashboard`（B1）与 `_sync_batch_dashboard`（B2）两条逐户路径；改调入队；`/accounts/deleted` 补分页；`parse_pagination` / `chunk` 应用 |
| `py/routes/tt_accounts_routes.py` | 修改 | `sync_from_sheet` 批量化（§5）；`/tt/accounts/deleted` 补分页 |
| `py/routes/fb_routes.py` | 修改 | 列表 N+1 改批查（§6.3）；`parse_pagination` 应用 |
| `py/routes/huguan_dashboard_routes.py` | 修改 | `dashboard_push` 加表锁 + 吞并旧脏行（§4.8） |
| `py/google_sheets_service.py` | 修改 | `update_rows_by_account_id` 加按行分块；429 识别与退避 |
| `py/routes/helpers.py` | 修改 | `parse_pagination` 上限 100→500（死代码，无调用点）；新增 `chunk` |
| `frontend/src/components/AccountDeletedModal.vue` | 修改 | 改分页渲染 + 服务端搜索 |
| `frontend/src/components/tt/TtAccountDeletedModal.vue` | 修改 | 同上 |
| `frontend/src/api/accounts.js`、`tt.js` | 修改 | `listDeleted` 接收分页参数 |

---

## 9. 测试策略

### 9.1 后端

| 用例 | 判据 |
|---|---|
| **S1 守卫：并集合并** | 同一户先入队 `{F:…}` 再入队 `{M:…}` ⇒ 冲刷时两列都被写；**只有后的列**即为回归 |
| **S1 守卫：重复入队** | 同一户同一列入队三次 ⇒ 只写最后值，不产生三行 |
| **S2 守卫：失败保留脏行** | 冲刷抛异常 ⇒ 脏行**仍在**，`sheet_write_log` 有记录 |
| **S2 守卫：成功才删** | 冲刷成功 ⇒ 该批脏行被删，且**只删本批** |
| **S3 守卫：按表串行** | 两 worker 同时冲刷同一 `(spreadsheet_id, sheet_name)` ⇒ 第二个跳过，不并发写 |
| **S3 守卫：不同表可并行** | 两张不同表 ⇒ 同时进行，不互相阻塞 |
| **定位列不回落** | 注册表解析不出 key_col ⇒ **不入队也冲刷不了**，落错误记录；绝不传默认 `"C"` |
| **定位列正确性（三平台）** | gg/tt 户管看板用 `C`、fb 户管看板用 `D`、GG 我的看板用 `B`、TT 我的看板用 `D` 各一条 |
| **同户双目标** | 同一户同时入队 `huguan_dashboard` 与 `my_dashboard` ⇒ 两行独立，互不覆盖 |
| **自适应周期** | `T=1` ⇒ 2s；`T=10` ⇒ 20s；`T=100` ⇒ 封顶 30s（纯函数，可测） |
| **429 退避** | mock 返回 429 ⇒ 退避序列递增且封顶，恢复后回落 |
| **push 吞并脏行** | 手动推送成功 ⇒ `id <= max_id` 的脏行被删，之后入队的**保留** |
| **push 与冲刷互斥** | 冲刷在途时手动推送 ⇒ 不并发写同一表 |
| **从表同步批量化** | 1 万行 mock ⇒ 查询数与 commit 数从 O(N) 降到常数级（断言上限） |
| **从表同步容错不降级** | 中间一条坏数据 ⇒ 其余照常落库，errors 收集到那一条 |
| **分页闸门** | `size=999999` ⇒ 实际返回 ≤ 500；`size=abc` ⇒ 回落默认值，不 500 |
| **已删除列表分页** | 返回 `page`/`size`/`total`；`total > size` 时只返回一页 |
| **`IN` 分块** | 构成 5000 个 id 的查询 ⇒ 分块执行，不抛 `too many SQL variables` |
| **删用户清理** | 有脏行的用户被删 ⇒ 不抛 `FOREIGN KEY constraint failed` |
| **FB N+1 消除** | 一页 50 行 ⇒ BM 查询次数为 1 而非 50 |

**时间类**（周期、退避、30s 最终失败）必须把 `sleep` monkeypatch 掉，否则单测跑不动。
既有测试已有 monkeypatch `_GOOGLE_SHEETS_CONFIG` 的先例（`test_huguan_dashboard.py:3008`）。

### 9.2 前端

- 已删除列表分页可翻页、搜索走后端、总数为 0 时显示空态
- 页尺寸切到上限仍不卡（模拟上万行总量）
- 冲刷失败时 `sheet_write_log` 的提示与「重试」按钮按既有链路工作

### 9.3 门禁

```
cd py && python -m pytest tests/ -q
cd frontend && npm run build
```

基线以执行时的实际为准（注册表改动面大，须先跑一次拿到干净基线）。
> 注意：既有 `test_fb_asset_model.py` 的 24 个测试是红的（4 位密码 `t123` vs 注册端点要求 ≥6 位，
> `main.py:8212`），与本设计无关，但会让全量回归不干净。修复应作为独立 bug 修复进行。

### 9.4 交付前置

按项目规范，**实现完成后必须调 `/code-review`**，修完发现的问题再交付。

本设计**必然触发**该门槛：改动触及数据归属语义（`cells_for_row` 的整列快照口径）、
SQL 拼接（`json_patch` 合并、`IN` 分块）、以及并发写入（按表单写者锁）——
三项都在「需评审」清单里。

---

## 10. 风险与已知代价

| # | 风险 | 评估 |
|---|---|---|
| 1 | **脏表多时延迟退到 30s** | §4.6 的直接结果，用户 2026-10-07 已确认接受 |
| 2 | **`cells_for_row` 是整列快照而非增量**，后入队者可能带着陈旧但完整的列集覆盖先入队者 | 与现状**完全一致**，非新增风险（§4.3）。真正的防重依赖单写者序列化 |
| 3 | 从表同步由逐行 commit 改为分批 commit，中途失败的残留粒度从「一行」变成「一批」 | §5.3。容错性（逐条 try）不降级；撤回不受影响 |
| 4 | 自适应周期是估算，真实配额行为需实测校准 | `I = min(30, max(2T, 1.5))` 的参数集中在一处，便于按实测调整 |
| 5 | 冲刷器是**新增的常驻后台线程** | 与既有 `_interval_loop` / 每周清理线程同形；崩溃不影响主流程（脏行在库里） |
| 6 | 删除两条逐户路径（B1/B2）会改动既有端点行为 | 这两条路径是纯劣化（逐户读整表），删除即修复；但**必须跑相关回归**确认没有依赖其特殊行为的调用方 |

---

## 11. 范围外

1. LM-Server（Spring Boot）侧的对应实现 —— 用户 2026-10-07 裁定本期只做 GG-Server
2. 投手侧「表→系统」的实时性（用户未列为硬指标）
3. 压缩跨投手扇出的**请求数**（API 一次只能打一张表，只有并发度可优化）
4. 并发探测一期补历史对账
5. 把从表同步改成后台任务 + 进度轮询（§5.4 给了判断阈值）
6. 前端视觉设计 —— 本设计的前端改动是「给既有列表补分页 + 搜索走后端」，属**既有页面改动**
   （加分页控件、挪搜索位置），按项目规矩**不触发** `/frontend-design`（该技能只对新增 UI 触发）。
   这是判断项：若你希望分页控件做视觉重做，另行调用

---

## 12. 决策记录（用户逐条确认）

| # | 决策点 | 结论 |
|---|---|---|
| 1 | 落点 | **只做 GG-Server（Python）**，不并入 Spring Boot 迁移 |
| 2 | 硬指标场景 | 系统→表即时、从表同步不超时、系统内部跟手（投手侧不列） |
| 3 | 安全边界 | 攒批不丢改动 + 写失败不静默 + 不并发覆盖（写错行/列未勾，仍显式处理） |
| 4 | 架构方案 | **方案 A：脏标记表 + 按表序列化的冲刷器** |
| 5 | 自适应周期的代价 | 脏表多时退到 30s，**接受** |
| 6 | 扩展性 | 目标注册表必须声明式，加表 = 加一行（用户：后续可能又有变化） |
| 7 | 分页 | 户管分页必须控制好，**不许全量返回** |
