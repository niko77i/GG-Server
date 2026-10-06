# 写表失败统一治理（一期：基建 + TT 回收清单接入）

> **日期**: 2026-10-06
> **状态**: 已确认，待写实现计划
> **一期范围**: 统一基建 + TT「回收户清单」接入 + 条件回滚
> **后续**: GG 账户域 / FB 域 / 户管看板逐期接入（见 §11）

---

## 1. 需求描述

用户原话：

> 「提交可以异步，但是失败必须有提示，或则直接回滚后再提示。提示需要给出失败的原因」
> 「这个操作应该同步到 gg 和 FB，而且应该是所有异步操作写表失败，都应提示加重试以及回滚」

即：**写 Google Sheets 仍然可以异步，但失败不能再无声无息** —— 必须有提示、提示里要带原因、并且能重试或回滚。

### 触发这件事的具体场景

TT 运营把一个广告账户的状态改成「非存活」（验证 / 封禁 / 死亡…），系统会在后台异步写「回收户清单」表。这条路径目前**完全静默** —— 写失败连日志都没有（`tt_accounts_routes.py:1229` 传的是 `lambda s, e: None`），用户以为写进去了，实际表里少一行，无人知晓。

### 已确认的决策（用户裁定）

| 决策 | 结论 |
|---|---|
| 覆盖范围 | 全部 21 个写表点，**分平台逐期接入**；一期只做基建 + TT 回收清单 |
| 提示形式 | 即时提示 + 持久标记（刷新/离开页面不丢） |
| 提示时机 | **等最终结果才提示**（首次失败不弹，30s 重试后仍失败才弹） |
| 回滚范围 | **只回滚「主数据延伸」类**；镜像类（户管看板回写）只提示+重试，不回滚 |
| 回滚时机 | **等最终失败（`retry_failed`）才回滚**，不在首次失败时回滚 |

---

## 2. 现状诊断（运行时代码为准）

### 2.1 全仓 21 个写表点，按失败行为分四类

| 失败时行为 | 数量 | 点位 |
|---|---|---|
| **(a) 完全静默**（错误直接丢弃，无日志无记录） | **1** | TT 回收清单（`tt_accounts_routes.py:1229`） |
| **(b) 只写日志** | **8** | GG 我的看板单格（`main.py:4690/4845/4909/5121/5395`）、户管看板（`huguan_dashboard.py:872/921`、`huguan_dashboard_routes.py:267`） |
| (c) 有持久记录 | 7 | GG 充值（`main.py:4663/5090/5551/5649`）、TT 充值（`tt_accounts_routes.py:724`）、GG 做表（`main.py:7364`）、FB（`fb_routes.py:1346`） |
| (d) 同步返回错误（已有提示） | 5 | `main.py:5767/7501`、`huguan_dashboard_routes.py:170`、`fb_routes.py:1469/1493` |

跨 GG / FB / TT 三平台。

### 2.2 基础设施的两个缺陷（本设计必须一并修）

**缺陷 A：`_sync_sheets_background` 首次成功不调用回调。**

`main.py:7917-7935` 的结构是：

```python
try:
    sync_fn()                      # ← 首次成功直接跳出，on_fail_fn 一次都不调
except Exception as e:
    on_fail_fn("failed", str(e))
    time.sleep(30)
    try:
        sync_fn()
        on_fail_fn("synced", "")   # ← 只有「失败后重试成功」才走到这里
    except Exception as e2:
        on_fail_fn("retry_failed", str(e2))
```

而各调用点把 `sheets_synced=1` 写在回调里。记录插入时是 `sheets_synced=0`，首次成功又不回调 ⇒ **标志位永远停在 0**，前端 `TtAccountDetailModal.vue:52` 的 `v-if="row.sheets_synced === 0"` 显示「未同步到表格」**误报**。影响 5 个充值写表点。

同源影响：GG 做表（`main.py:7364`）在 `synced` 分支里 `DELETE FROM sheets_sync_log`。首次成功不回调 ⇒ 那条 `pending` 日志行**永久残留**，前端 `startZbSyncPolling` 拿到的 `log.status === 'pending'` 既不等于 `failed` 也不为 `null`，于是**空转到轮询上限**。

**缺陷 B：回调自身的异常被吞掉。**

`main.py:7924/7930/7935` 三处都是 `try: on_fail_fn(...) except Exception: pass`。回调是唯一负责落记录的地方，它失败就彻底没痕迹了。至少要落日志。

### 2.3 回滚：全仓 21 个写表点，一个都没有

所有异步路径都是「先 `db.commit()` 提交业务变更 → 再写表」，失败时回调只 `UPDATE` 一个同步状态列，**从不撤销已提交的业务变更**。同步路径（`main.py:5767/7501` 等）失败返回 500，已提交的行同样留在库里。回滚能力是**净新增**。

### 2.4 FB 的异步写表不走统一通道

`fb_routes.py:1363` 用自己的 `threading.Thread`，**没有 30s 重试**。一期不改它的行为（避免范围失控），但统一入口需为其预留位置，二期切过来。

---

## 3. 目标行为

1. 任何接入统一入口的写表，**最终失败**（首次失败 + 30s 重试仍失败）时必须产生一条**持久记录**，含具体失败原因
2. 操作者在界面上能看到该失败（即时提示 + 账户行持久标记），**刷新/离开页面后仍可查**
3. 操作者能**一键重试**
4. 「主数据延伸」类写表的最终失败，在**守卫条件通过时自动回滚**业务变更，并告知操作者
5. 写表成功时**不打扰**用户，且**成功信号必须真实**（修掉缺陷 A）

---

## 4. 架构

### 4.1 统一入口

新增 `py/sheet_write.py`，对外只暴露一个函数：

```python
def run_write(*, user_id, platform, target, business_key,
              sync_fn, payload=None, snapshot=None,
              rollback_fn=None) -> None:
    """统一写表入口：登记任务 → 后台写表 → 按最终结果落状态 / 回滚。

    绝不抛异常（写表是业务端点的副作用，不得影响主流程）。
    """
```

参数语义：

| 参数 | 含义 |
|---|---|
| `user_id` | 操作者。失败记录只给他看 |
| `platform` | `gg` / `tt` / `fb` |
| `target` | **稳定 token**（`tt_recycle` / `huguan_dashboard` / …），不是中文名 —— 文案改名不影响契约 |
| `business_key` | 业务定位键。TT 回收清单 = `advertiser_id` |
| `sync_fn` | 无参函数，执行真正的 Sheets 写 |
| `payload` | 重试所需的最小重建参数（JSON-able），如 `{"reason": "封禁回收"}` |
| `snapshot` | 回滚所需的前置快照（JSON-able）。为 `None` 表示该类不回滚 |
| `rollback_fn` | `(db, snapshot) -> bool`。返回 `True`=已回滚，`False`=放弃回滚 |

### 4.2 线程与连接约束（实现时的硬性要求）

`sync_fn` 与 `rollback_fn` 都在**后台线程**执行，而 SQLite 连接不可跨线程共享。因此：

- `sync_fn` 必须在**自身闭包内**用 `google_sheets_service.build_service()` 新建 service
- `rollback_fn` 收到的 `db` 由 `run_write` 在后台线程内用 `database.get_db()` **新建**，**不得**捕获请求线程的连接

既有正确先例：`tt_accounts_routes.py:724-734` 的 `_on_fail` 注释「后台线程无应用上下文，必须用 `database.get_db()` 新建连接（不能碰 flask.g）」。

同理，`run_write` 的调用点**不得在请求线程里预先 build service 再传进来** —— `huguan_dashboard_routes.py:246-254` 的 `_write_background` docstring 记录了原因：`dashboard_sync` 背靠背调两次，两个线程并发复用同一个 httplib2 客户端（httplib2 非线程安全）。

### 4.3 目标注册表

重试要能**从零重建**一次写表，故 `target` 需对应一组可重建的执行器：

```python
TARGETS = {
    "tt_recycle": {"sync": _tt_recycle_sync, "rollback": _tt_recycle_rollback},
}
```

`_tt_recycle_sync(db, user_id, business_key, payload)` 在**重试时**重新解析表地址与工作表名（从 `tags` 的 `tt_sheet_id` / `tt_sheet_mappings.recycle` 现取），**不**把 `spreadsheet_id` 存进任务记录 —— 户管改了配置后重试应写进新表。

### 4.4 修掉缺陷 A / B

`_sync_sheets_background`（`main.py:7909`）改为**首次成功也回调**：

```python
try:
    sync_fn()
    if on_fail_fn: on_fail_fn("synced", "")     # ← 新增
except Exception as e:
    ...  # 其余不变
```

**影响面**：全仓 21 个写表点中，**经 `_sync_sheets_background` 的 15 个**受影响（异步点 #1–9、#11、#13、#14、#16、#17、#18；同步点 #10/#12/#15/#20/#21 不走此函数，FB 的 #19 走自建线程，三者均不受影响）。逐类核对：

| 调用点类别 | 首成回调后的行为 | 判定 |
|---|---|---|
| 5 个充值点（回调里 `sheets_synced=1`） | 标志位正确地变成 1 | ✅ 这正是修复目标 |
| GG 做表（回调里 `DELETE FROM sheets_sync_log`） | `pending` 行成功后被清掉，前端轮询拿到 `null` → 判定成功 | ✅ 修掉空转 |
| 户管看板 3 处（回调只 `log.warning`） | 成功时 `e` 为空串，`if e` 为假，不写日志 | ✅ 无变化 |
| 6 个「我的看板」单格（回调只 `log.warning`） | 同上 | ✅ 无变化 |

参数名 `on_fail_fn` 在此之后名不副实（成功也会调）。**不改名** —— 经 `_sync_sheets_background` 的异步写表点是 **15 个**（同步点与 FB 自建线程不走此函数，见 §4.4），为这 15 处改名的收益不抵改动面，改为在 docstring 首行显著说明语义是「结果回调」。

缺陷 B：三处 `except Exception: pass` 改为**至少落 `log.error`**。

---

## 5. 数据模型

```sql
CREATE TABLE IF NOT EXISTS sheet_write_log (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id       INTEGER NOT NULL,            -- 操作者：提示只给他看
    platform      TEXT    NOT NULL,            -- gg / tt / fb
    target        TEXT    NOT NULL,            -- 稳定 token
    business_key  TEXT    NOT NULL DEFAULT '', -- 业务定位键
    status        TEXT    NOT NULL,            -- 见 §5.1
    error_msg     TEXT    DEFAULT '',
    payload_json  TEXT    DEFAULT '',          -- 重试所需的最小重建参数
    snapshot_json TEXT    DEFAULT '',          -- 回滚所需前置快照
    created_at    TEXT    DEFAULT (datetime('now','localtime')),
    updated_at    TEXT    DEFAULT (datetime('now','localtime')),
    settled_at    TEXT    DEFAULT NULL,        -- 最终态时刻；非 NULL 即「已定案」
    UNIQUE(user_id, target, business_key)
);
CREATE INDEX IF NOT EXISTS idx_swl_user_platform ON sheet_write_log(user_id, platform);
```

**为什么 `UNIQUE(user_id, target, business_key)` 而不是 append-only 日志**：本次要回答的是「这个账户的这个写表目标**现在**是不是处于失败态」，不是「历史发生过几次」。按业务键 upsert，同一账户同一目标的并发写互相覆盖，取最新事实。

**为什么不做历史审计**：YAGNI。真需要时再加 append-only 表，不影响本表结构。

### 5.1 status 取值

| 值 | 含义 | 前端行为 |
|---|---|---|
| `pending` | 已登记，写表在途 | 不提示、不标记 |
| `failed` | 首次失败（30s 重试在途的中间态） | **不提示**（用户选了「等最终结果」） |
| `synced` | 写表成功（含重试成功） | 清除标记，**不打扰** |
| `retry_failed` | 30s 重试也失败，**最终失败** | 提示 + 标记 + 重试按钮 |
| `rolled_back` | 最终失败，且**已回滚**业务变更 | 提示（文案说明已撤销）+ 可重试 |
| `rollback_abandoned` | 最终失败，但**守卫未过 → 放弃回滚** | 提示（文案说明未撤销，请手工核对）+ 可重试 |

`rollback_abandoned` 必须与 `retry_failed` 区分：前者用户的操作**还生效着**，后者已经被撤销 —— 两者的后续动作完全不同，文案混用会误导。

### 5.2 给谁看

按 `user_id` 隔离，**只看自己的失败**。回收清单虽是全平台共用一张表，但「我这次同步没写进去」是操作者自己的事 —— 与既有 `sheets_sync_log` 的 `WHERE user_id=?` 口径一致。

「管理员查看所有人的失败」**不在本期**（见 §10）。

---

## 6. 回滚协议

### 6.1 适用判定

只有**主数据延伸**类写表才注册 `rollback_fn` —— 即「写表内容就是这次业务变更本身」的那类：

| 写表目标 | 是否回滚 | 理由 |
|---|---|---|
| TT 回收清单 | ✅ | 表里那一行记的就是「这个户被回收了」这件事。表没写成 ⇒ 这件事没完成 ⇒ 状态改回去 |
| 户管看板回写 | ❌ | 那是系统状态的**镜像**。把系统回滚了，镜像反而变成错的 |

### 6.2 条件回滚（核心）

回滚前**必须**校验业务对象是否仍是当初写下的那个值：

```
若 status_id 仍 == 快照里的 new_status_id  ⇒ 执行回滚
否则                                        ⇒ 放弃回滚，落 status='rollback_abandoned'
```

**守卫未过时放弃回滚，比回滚本身更重要**：快照是 30 秒前的，这期间用户完全可能又改了状态。拿陈旧快照覆盖用户的后续操作，就是伪造数据。

放弃回滚时 `error_msg` 要写清「因该账户在写表期间被再次修改，未自动撤销」，让用户知道要手工核对。

### 6.3 TT 回收清单的回滚实现

**写入前快照**（在 `_trigger_recycle_if_dead` 之前抓）：

```python
snapshot = {
    "account_pk": row["id"],
    "prev_status_id": row["status_id"],
    "prev_status_changed_date": row["status_changed_date"],
    "prev_death_date": row["death_date"],
    "new_status_id": status_id,
}
```

改前的值只在两个调用点手里，**两处都必须抓快照**：

| 调用点 | 改前值的来源 | 触发条件 |
|---|---|---|
| 单条更新 `tt_accounts_routes.py:323-340` | 函数开头 `:299-302` 的 `SELECT a.*, st.name AS status_name` —— **已含** `status_id` / `death_date` / `status_changed_date`，**无需补查询** | 状态名与当前不同（`:331`） |
| 批量更新 `tt_accounts_routes.py:461-468` | 循环内 `:449` / `:453` 的 `SELECT owner_id, bc_id, advertiser_id, status_id` —— 是**显式列清单**，缺 `death_date` / `status_changed_date`，**需扩展 SELECT** | `status_id` 与当前不同（`:466`） |

**单条路径有个时序坑**：`:308-313` 的 `editable` 列表里**包含 `death_date`**，会先于状态块执行。所以快照必须在 `:302` 查到 `row`、`:305-306` 权限校验之后**立即抓**，不能挪到 `:323` 的状态块里 —— 否则抓到的是已被 `editable` 循环改写过的值，回滚会还原成错的。

批量路径无此问题（`:447-456` 之后直接进状态块，中间没有改 `death_date` 的分支）。

**回滚执行**：

```sql
UPDATE tt_accounts
   SET status_id=?, status_changed_date=?, death_date=?,
       updated_at=datetime('now','localtime')
 WHERE id=? AND status_id=?     -- ← 最后这个 ? 就是守卫
```

守卫写在 `WHERE` 里，用**一条原子的 UPDATE** 完成「校验 + 回滚」，避免「先查后写」之间的竞态。受影响行数为 0 即视为守卫未过 → 返回 `False`。

### 6.4 回滚后的表侧处理

回滚**不回写表** —— 表里根本没写成功，无需清理。这不违反「镜像类不回滚」的边界：回收清单这一行压根不存在。

### 6.5 已知代价（用户已确认接受）

用户点完「改状态」后，**最多 30 秒**才可能被撤销。这期间：

- 界面上显示的是「已改」的状态 —— 一个**暂时的假状态**
- 其它用户看到的状态也是「已改」

换来的是：不会出现「表写成功但系统已回滚」的永久不一致。

---

## 7. 前端交互

### 7.1 轮询（照搬既有范式）

`ToolkitView.vue:535-562` 的 `startZbSyncPolling` 是现成范式，直接照搬其结构：

```
改状态成功 → 启动轮询 GET /api/sheet-write/status?platform=tt&business_key=<advertiser_id>
  轮询间隔 ~3s，上限 ~40s（覆盖 30s 重试窗口）
  status ∈ {synced, 无记录} → 静默退出
  status == 'retry_failed'      → ElMessage.error(具体原因)
  status == 'rolled_back'       → ElMessage.warning('写表失败，已撤销本次状态变更')
  status == 'rollback_abandoned'→ ElMessage.warning('写表失败，且该账户期间被再次修改，未自动撤销，请手工核对')
  到达上限          → 静默退出（靠列表标记兜底，不打扰）
```

`failed` / `pending` 两个中间态**继续轮询**，不提示。

### 7.2 持久标记

账户列表加载时另发一次 `GET /api/sheet-write/status?platform=tt`（不带 `business_key`，返回该用户全部未定案项），按 `business_key` 索引：

- `retry_failed` / `rolled_back` / `rollback_abandoned` → 该行显示红色标记
- tooltip 内容 = `error_msg`（具体原因）
- 「重试」按钮 → `POST /api/sheet-write/retry`

### 7.3 接口清单

| 方法 | 路径 | 用途 |
|---|---|---|
| GET | `/api/sheet-write/status?platform=&business_key=` | 带 `business_key` → 轮询单条；不带 → 列表标记用全量 |
| POST | `/api/sheet-write/retry` | body `{platform, target, business_key}`，按注册表重建并重写 |

两个接口都 `@jwt_required()`，且**只返回 / 只处理当前 `user_id` 的记录**（在 SQL 的 `WHERE user_id=?` 里约束，不在 Python 侧过滤）。

### 7.4 新增 UI 的处置

本节新增了 UI（行内失败标记 + tooltip + 重试按钮 + 三种提示文案）。按项目规矩，**设计文档确认后、动手实现前调用 `/frontend-design`**。

---

## 8. 一期交付范围

**做**：

1. 新增 `py/sheet_write.py`（`run_write` + `TARGETS` 注册表）
2. 新增 `sheet_write_log` 表（`database.py` 的 `_ensure_schema` + `_ensure_columns` 双侧同步）
3. 修缺陷 A、B（`_sync_sheets_background`）
4. 新增两个 HTTP 接口（`py/routes/sheet_write_routes.py`，新 blueprint）
5. TT 回收清单接入：`_trigger_recycle_if_dead` 改走 `run_write`，含快照抓取与回滚注册
6. 前端：轮询 + 行标记 + 重试按钮

**不做**：见 §10。

---

## 9. 测试策略

### 9.1 后端

| 用例 | 判据 |
|---|---|
| 缺陷 A 守卫 | `sync_fn` 首次成功 ⇒ 回调收到 `("synced", "")`。**这是缺陷 A 的唯一守卫**，必须有 |
| 缺陷 B 守卫 | 回调自身抛异常时 `log.error` 被调用（monkeypatch logger） |
| 首次失败不提示 | `status='failed'` 时前端轮询继续，不产生终态 |
| 最终失败落终态 | 重试也失败 ⇒ `status='retry_failed'`、`settled_at` 非空、`error_msg` 有值 |
| **条件回滚：守卫通过** | 快照与当前 `status_id` 一致 ⇒ 状态被改回，`status='rolled_back'` |
| **条件回滚：守卫未过** | 回滚前把状态改成第三个值 ⇒ **不改回**，`status='rollback_abandoned'`，`error_msg` 含「被再次修改」 |
| 镜像类不回滚 | `snapshot=None` 的 target 最终失败后业务数据一字不变 |
| 重试 | `POST /retry` 后重新执行 `sync_fn`，成功则 `status='synced'` |
| 隔离 | A 用户的 status 接口查不到 B 用户的记录 |

**时间**：`_sync_sheets_background` 的 30s `sleep` 必须 monkeypatch 掉，否则单测跑不动。既有测试已有 monkeypatch `_GOOGLE_SHEETS_CONFIG` 的先例（`test_huguan_dashboard.py:3008`）。

### 9.2 前端

- 轮询在 `synced` / 无记录时静默退出，不发提示
- `retry_failed` / `rolled_back` / `rollback_abandoned` 三种文案各自正确
- 列表标记按 `business_key` 正确匹配到行

### 9.3 端到端

mock Sheets 抛错 → 走完 30s 重试（时间需 mock）→ 断言：账户状态被撤销、`sheet_write_log` 落 `rolled_back`、接口返回该记录。

---

## 10. 明确不做（一期）

1. **GG 账户域 9 个写表点**、**FB 域 3 个**、**户管看板 4 个** —— 二期起逐平台接入（§11）
2. **镜像类写表的回滚**（户管看板回写）—— 用户裁定只提示+重试
3. **FB 异步写表切换到统一通道** —— 它现在连 30s 重试都没有，但切换会改变其重试行为，属独立变更
4. **历史审计 / 失败统计报表**
5. **管理员查看他人失败**
6. **`_sync_sheets_background` 参数改名为 `on_result_fn`** —— 21 个调用点，收益不抵改动面；改为在 docstring 显著说明

---

## 11. 后续路线图（不在本期实现）

| 期 | 内容 | 备注 |
|---|---|---|
| 二期 | GG 账户域 9 个写表点接入 | 含 5 个 `log.warning` 的「我的看板」单格写、4 个充值点统一到新机制 |
| 三期 | FB 域 3 个写表点接入 | 须先把 `fb_routes.py:1363` 的自建线程切到统一通道，以获取 30s 重试 |
| 四期 | 户管看板 4 个写表点接入 | 只提示+重试，不回滚（镜像类） |

---

## 12. 风险与已知代价

1. **回滚窗口内的假状态**（§6.5）—— 用户已确认接受
2. **回滚是补偿式写入，不是事务回滚** —— 它发生在原事务提交之后 30s+。守卫（§6.2）只能防「用户又改过」，防不了「账户在同一瞬间被别处修改且恰好改成了同一个值」。该极端情形下会回滚掉一次并非本操作引起的变更。评估：TT 账户状态变更的入口只有 `PUT /api/tt/accounts/<aid>` 与 `POST /api/tt/accounts/batch-update` 两个，且都要求状态名与当前不同才触发（`tt_accounts_routes.py:331/466`），撞车概率极低，接受
3. **`UNIQUE(user_id, target, business_key)` 会覆盖未定案记录** —— 同一账户连续两次改状态，第一次的记录被第二次覆盖，第一次的失败提示可能丢失。评估：第二次操作本身会产生新的提示，用户不会漏掉「这个账户写表有问题」这个事实，接受
4. **既有 `test_fb_asset_model.py` 的 24 个测试是红的**（4 位密码 `t123` vs 注册端点要求 ≥6 位，`main.py:8212`），与本设计无关，但会让全量回归不干净。修复应作为独立 bug 修复进行
