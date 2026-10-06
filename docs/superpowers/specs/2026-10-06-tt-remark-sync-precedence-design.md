# TT 备注（`remark`）跨看板同步优先级

> 日期：2026-10-06
> 状态：待用户确认
> 范围：**仅 TT 平台的 `tt_accounts.remark` 一个字段**
> 采用方案：**方案 A（在现有同步链路上打补丁）** —— 用户 2026-10-06 选定

## 0. 背景

`tt_accounts.remark` 目前被**两张 Google 表同时读写**：

| 来源 | 列 | 映射 | 方向 |
|------|----|------|------|
| 投手「我的看板」 | J 列「备注」 | `remark` | 读（建户）+ 写 |
| 户管看板 | M 列「产品信息」 | `remark` | 读 + 写 |

两边都是 `writable=True` + `readable=True`，谁后同步谁赢。更严重的是 `_PLAIN_TEXT_FIELDS["tt"]`
含 `remark`，而「文本列空值照常落库」是既有口径（`_collect_updates()` docstring）——
**户管看板 M 列空着，同步一次就会把投手刚同步进来的备注清掉**。

### 附带发现：系统 → 投手看板的推送链路根本不存在

所有推送都走 `huguan_dashboard.push_rows(user_id, ...)`，它取 `get_platform_config(db, user_id, ...)`，
即 **`user_id` 自己的 `huguan_dashboard_{uid}` 配置**。投手（uid 23/25/28/30/31）没有这个键
（现存仅 `huguan_dashboard_1` 与 `huguan_dashboard_26`），所以：

> `tt_accounts_routes.py` 中 `sync_from_sheet()` 结尾的 `hd.writeback_rows(uid, "tt", ...)`
> 传的是**投手自己的 uid**，查不到配置 → `push_rows` 直接 `return`。**对投手是一句静默空转。**

本设计需要新建「系统 → 投手看板」的推送通路。

## 1. 裁定（用户逐条确认）

| 项 | 裁定 |
|----|------|
| 范围 | **只改 `remark` 一个字段**；状态 / 归属 / BC / 代理 / 消耗情况等一律不动 |
| 平台 | 仅 TT |
| 首次入库（户管触发） | 先读投手看板 J 列：**有值则投手赢**（覆盖户管看板 M + 系统）；空则户管赢（推给投手看板） |
| 首次入库（投手触发） | 直接用投手看板 J 列的值，**不额外读户管看板**（分触发方处理） |
| 之后（账户已存在） | **投手权威永久**：户管看板 M 列的改动**不再进系统** |
| 投手改备注的入口 | `TtAccountPanel.vue` 加「备注」列，**可内联编辑** |
| 不加的入口 | 不加编辑弹窗字段；不把投手看板 J 列作为**持续**修改入口 |

## 2. 目标行为

### 2.1 首次入库（户管触发的「从表同步到系统」）

```
系统里没有该账户（build_diff 的 to_create 分支）
  ├─ 解析该行归属 → 投手 uid
  ├─ 读该投手的「我的看板」J 列（一次读全表建映射，再按广告账户 ID 查）
  ├─ 投手 J 列非空  → remark := 投手值
  │                  并回写「户管看板」M 列 = 投手值（覆盖户管填的）
  ├─ 投手 J 列为空  → remark := 户管 M 列值
  │                  并推送「投手看板」J 列 = 户管值
  └─ 投手 uid 解析不到 / 没配 my_dashboard / 没配 tt_sheet_id
                     → remark := 户管 M 列值，跳过投手看板的读与写（记日志）
```

### 2.2 之后（账户已存在）

```
户管同步改 M 列        → remark 不更新（户管改动被忽略）
投手在系统内联编辑备注  → UPDATE tt_accounts.remark
                         → 推送「户管看板」M 列 + 「投手看板」J 列
投手同步（J 列）        → remark 不更新（只处理消耗/状态冲突，现状即如此）
```

## 3. 实现方案（方案 A）

改动集中在 5 处，**不新增表、不新增数据库列**。

### 3.1 已存在账户：`to_update` 剔除 `remark`

`py/huguan_dashboard.py` 的 `build_diff()` 中，对已存在账户的字段过滤处：

```python
changed = {k: v for k, v in fields.items()
           if not _same_as_existing(db, platform, existing, k, v)}
```

追加一个剔除条件：

```python
changed = {k: v for k, v in fields.items()
           if not _same_as_existing(db, platform, existing, k, v)
           and not (platform == "tt" and k == "remark")}
```

**不改 `_PLAIN_TEXT_FIELDS`** —— 因为 `to_create` 分支（`build_diff` 内 `existing is None` 时）
与 `to_update` 共用同一个 `_collect_updates()`。保留字段在列表里，`to_create` 才能继续收到
户管 M 列的值（2.1 里「户管赢」那一支要用），只在 `to_update` 里剔除。

**附带收益**：`_blank_columns()` 不会再为已存在账户把 `remark` 报进 `clears`，
**「户管空值清空投手备注」从此不可能发生**。

### 3.2 首次入库：读投手看板

在 `py/huguan_dashboard.py` 新增一个**只读**辅助函数（供 `apply_diff` 调用）：

```python
def read_operator_remark_map(db, owner_id: int) -> dict:
    """读该投手「我的看板」的 广告账户ID → J 列备注 映射。

    投手未配 my_dashboard、或全局未配 tt_sheet_id 时返回空 dict（调用方跳过）。
    读表失败不抛异常，返回空 dict —— 读不到投手看板不应阻断户管同步。
    """
```

- 表 ID 取 `tags.tt_sheet_id`；sheet 名取 `tags.tt_sheet_mappings` 里 `{owner_id}.my_dashboard`
  （默认 `"我的看板"`）—— 与 `tt_accounts_routes._get_tt_sheet_id` / `_get_tt_sheet_mappings` 同源。
- 读 `A:J`，跳过表头，按 D 列（`r[3]`）建索引，取 J 列（`r[9]`）。
- 一次读全表，供本次同步的所有新建账户共用（不要按账户逐个读）。

在 `apply_diff()` 的 `to_create` 循环内、`INSERT` 之前介入：

```python
src = dict(item.get("db_values") or {})
...
if platform == "tt" and "remark" in src:
    owner_id = item.get("owner_id")
    remark_map = _operator_remark_cache.get(owner_id)  # 见下
    op_value = (remark_map or {}).get(item["account_id"], "").strip() if owner_id else ""
    if op_value:
        src["remark"] = op_value          # 投手赢
        need_m_writeback.append(item["account_id"])
    else:
        need_push_to_operator.append((owner_id, item["account_id"]))
```

`_operator_remark_cache` 是本次 `apply_diff` 调用内的局部字典（`{owner_id: map}`），
按 owner 惰性读取，避免同一投手被重复读表。**不要做成模块级缓存** —— 表内容随时可能变，
跨请求缓存会让户管看到过期值。

**为什么把读放在 `apply_diff` 而不是 `build_diff`**：`build_diff` 承诺只读且会被 `dry_run`
调用；在其中发起 Google 表读取会让「空跑预览」变慢且引入网络失败面。代价是
`dry_run` 的预览**不会**显示「本次交付由投手看板决定的备注」——见 §5 已知后果。

### 3.3 首次入库后的两个写回

**`apply_diff` 的返回 dict 新增两个键**（与既有的 `applied_owner_rows` 同风格，
由路由层 `pop` 后消费）：

| 键 | 结构 | 含义 |
|----|------|------|
| `remark_m_writeback` | `[{"account_id": str, "value": str}]` | **投手赢**的行：需把 `value` 回写「户管看板」M 列（覆盖户管填的） |
| `remark_operator_push` | `[{"owner_id": int, "account_id": str, "value": str}]` | **户管赢**的行：需把 `value` 推到该投手看板的 J 列 |

两个键在 `platform != "tt"` 时恒为空列表（GG 路径不产生）。

在 `py/routes/huguan_dashboard_routes.py` 的 `dashboard_sync()` 中，`apply_diff` 返回后消费：

```python
result = hd.apply_diff(db, diff, platform, confirmed, user_id=uid)
...
# 与既有 applied_owner_rows 同法：先从 result 摘掉，再发起后台写回
m_writeback = result.pop("remark_m_writeback", [])
operator_push = result.pop("remark_operator_push", [])
```

写回契约：

- **户管看板 M 列**：`gs.update_rows_by_account_id(service, conf["spreadsheet_id"],
  conf["sheet_name"], [{"account_id": r["account_id"], "cells": {"M": r["value"]}} for r in m_writeback])`
  —— 用默认 `key_col="C"`（户管看板账户 ID 在 C 列），表 ID / sheet 名取自本次请求已解析的 `conf`
- **投手看板 J 列**：逐条调用 3.4 的 `push_remark_to_operator_dashboard(owner_id, account_id, value)`
- **只写 `M` / `J` 单列**，绝不整行推送 —— 避免顺手覆盖户管在表里的其他手工列
- 两者都走后台线程（`_write_background` / `_sync_sheets_background` 既有模式），
  失败只记日志，**不得改变同步接口的返回值**

### 3.4 系统 → 投手看板的推送通路（新建）

`py/huguan_dashboard.py` 新增：

```python
def push_remark_to_operator_dashboard(owner_id: int, account_id: str, value: str) -> None:
    """把备注写进该投手的「我的看板」J 列（按 D 列定位行）。

    投手未配 my_dashboard 或全局未配 tt_sheet_id → 静默返回。
    绝不抛异常（与 writeback_rows 同契约：回写失败不得影响主流程）。
    """
```

与 `push_rows` 的区别：`push_rows` 面向**户管看板**（配置来自 `huguan_dashboard_{uid}`），
本函数面向**投手看板**（配置来自全局 `tags.tt_sheet_id` + `tags.tt_sheet_mappings`）。

### 3.5 投手内联编辑接口

`py/routes/tt_accounts_routes.py`：

现有 `PUT /api/tt/accounts/<aid>` 的 `editable` 白名单**已含 `remark`**
（该文件 `editable = ["name", "country", "timezone", "consumption", "acquired_date", "death_date", "remark"]`），
所以**后端接口无需新增**。只需在该端点的更新逻辑之后补两个推送：

```python
if "remark" in data and data["remark"] is not None:
    hd.writeback_rows(uid, "tt", [advertiser_id])               # 户管看板 M 列
    hd.push_remark_to_operator_dashboard(owner_id, advertiser_id, value)   # 投手看板 J 列
```

`owner_id` 取该账户当前的 `owner_id`（不是调用者 uid）——投手改的是自己名下的户，
但户管也可能代改别人的户，推给**账户的归属人**才正确。

> ⚠️ **`writeback_rows(uid, ...)` 的 `uid` 在这里是调用者**。若投手调用，`uid` 是投手 →
> 查不到 `huguan_dashboard_{投手uid}` → 写户管看板这一步会**静默空转**，这是现有行为
> （户管看板只有户管能刷）。因此户管看板的推送实际只在**户管自己改**时生效；
> 投手改备注时，户管看板靠 `dashboard_push` 全量刷新对齐。此限制在 §5 记为已知后果。

### 3.6 前端：`TtAccountPanel.vue` 加可内联编辑的备注列

`frontend/src/views/tt/TtAccountPanel.vue` 在「消耗情况」列（第 141 行）之后新增：

```vue
<el-table-column label="备注" min-width="160">
  <!-- 内联编辑：失焦/回车提交，调 PUT /api/tt/accounts/{id} {'remark': value} -->
</el-table-column>
```

- 提交成功后就地更新行数据，不整表重载
- 失败回滚显示并提示
- 列表接口 `GET /api/tt/accounts/list` 用 `SELECT a.*`，`remark` 已在返回体里，后端无需改动

**这一列是新增交互**，按项目规矩需先过 `/frontend-design` 定视觉，再实现。

## 4. 不做什么（YAGNI）

- 不新增数据库列、不新增表、不引入「权威标记」字段（方案 B 被否决）
- 不改 `_PLAIN_TEXT_FIELDS` 的构成（见 3.1 的理由）
- 不把投手看板 J 列做成持续修改入口
- 不给编辑弹窗加备注字段
- 不动 GG、FB 的任何行为
- 不动 `consumption` 的双向同步（I 列 ↔ `consumption`）——那是另一套既有冲突弹窗逻辑

## 5. 已知后果

1. **`dry_run` 预览看不到投手看板的影响**。户管的确认弹窗里，新建账户的备注显示的是
   户管 M 列的值；实际落库可能被投手看板覆盖。这是 3.2 把读取放在落库阶段的直接代价。
   若必须让户管预先看到，需把读取上移到 `build_diff`（会让空跑变慢并引入网络失败面）。
2. **投手改备注时不会立即刷新户管看板**（3.5 的 `uid` 限制）。户管看板靠全量刷新对齐。
3. **投手看板读不到时静默降级**：投手没配 `my_dashboard`、或全局没配 `tt_sheet_id`、
   或读表失败 → 一律按「户管赢」处理并记日志。户管同步不会因此失败。
4. **首次入库后投手看板才建行的账户**：`update_rows_by_account_id` 找不到该账户会返回
   `not_found`，不会新建行（既有契约：系统只改单元格、不建行）。这些账户的备注
   要等投手自己把行加进看板。

## 6. 测试要点

| # | 用例 | 断言 |
|---|------|------|
| 1 | 户管同步、账户不存在、投手 J 列有值 | 落库 `remark` == 投手值；户管看板 M 列写回该值 |
| 2 | 户管同步、账户不存在、投手 J 列为空 | 落库 `remark` == 户管 M 列值；投手看板 J 列被推送该值 |
| 3 | 户管同步、账户已存在、M 列改了值 | `remark` **不变**；该字段不出现在 `to_update[].fields` |
| 4 | 户管同步、账户已存在、M 列清空 | `remark` **不变**；`clears` 里**不含** `remark`（回归：旧隐患已消除） |
| 5 | 投手同步建户 | `remark` == 投手 J 列值（现状保持，不额外读户管看板） |
| 6 | 投手未配 `my_dashboard` | 户管同步按「户管赢」落库，不抛异常 |
| 7 | 同一投手下多个新建账户 | 该投手的表**只被读一次**（打桩计数） |
| 8 | 投手内联编辑备注 | 户管看板 M 与投手看板 J 各收到一次单列写回调用 |
| 9 | 投手看板推送失败 | 主流程仍返回成功（异常被吞，仅记日志） |
| 10 | GG 全流程 | 行为逐字节不变（回归护栏：`platform == "tt"` 分支不得误伤 GG） |

用例 3、4、10 是**回归护栏**。

## 7. 与同期改动的冲突（务必先读）

本次改动与同期的
[TT「换绑情况」列改造](2026-10-06-tt-owner-change-note-design.md) **落在同一批文件与函数上**：

| 文件 / 函数 | 换绑情况改动 | 备注改动 | 是否冲突 |
|-------------|--------------|----------|----------|
| `huguan_dashboard.py` `COLUMN_SPEC["tt"]` | 改 L 列条目 | 不动 | 同文件，不同行 |
| `huguan_dashboard.py` `_PLAIN_TEXT_FIELDS["tt"]` | **追加** `owner_change_note` | **不动**（刻意不改，见 3.1） | ⚠️ 同一定义处，需合并 |
| `huguan_dashboard.py` `effective_owner_name()` | 加 `platform` 参数分叉 | 不动 | 无 |
| `huguan_dashboard.py` `build_diff()` | 不动 | `to_update` 的 `changed` 加剔除条件 | 无 |
| `huguan_dashboard.py` `apply_diff()` | 不动 | `to_create` 加读投手表与写回 | 无 |
| `huguan_dashboard.py` `writeback_owner_channel()` | 加 `text` 参数 | 不动 | 无 |
| `huguan_dashboard_routes.py` `dashboard_sync()` | 清空 L 改 GG-only | 加两处写回 | ⚠️ 同一函数体内 |
| `tt_accounts_routes.py` `reassign_account()` | 写 `owner_change_note` | 不动 | 无 |
| `tt_accounts_routes.py` `update_account()` | 不动 | 加两处推送 | 无 |
| `TtAccountPanel.vue` | 加「换绑情况」列（只读） | 加「备注」列（可编辑） | ⚠️ 同一表格 |

**结论**：两处真实冲突点（`_PLAIN_TEXT_FIELDS` 定义处、`dashboard_sync()` 函数体）。
建议**串行实施**：先做换绑情况（自包含、无网络读取、风险低），跑通测试后再做备注。
不并行改同一函数，避免互相覆盖。
