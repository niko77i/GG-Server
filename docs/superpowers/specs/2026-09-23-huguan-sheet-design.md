# 户管看板 Google Sheet 配置与双向同步设计（子项目 B）

> 范围：**子项目 B**（户管看板 sheet 的配置、写表、读回同步）。
> 子项目 A（角色与权限）已完成，见 `2026-09-22-huguan-role-design.md`。

---

## 一、需求描述

### 背景

户管（`role='huguan'`，`HUGUAN_ROLE` in `py/routes/helpers.py:2`）是跨用户角色：可切换 GG / TT / FB 三个平台（`PLATFORM_SWITCH_ROLES`，`helpers.py:12`），可查看并编辑全部用户的账户。

用户原始需求（2026-09-22）原文：

> 「另外GG和TT的设置哪里，户管只有一个单独的sheet配置，户管可以直接像开发者那样，直接登陆后切换不同的GG tt fb系统，所以这个sheet在gg和tt配置的是不一样的」

子项目 A 把这部分**从界面上藏掉了**：`frontend/src/views/SettingsPanel.vue:65` 用 `v-if="authStore.isAdmin || authStore.isDeveloper"` 包住 GG 的「📊 充值表配置」卡片，`frontend/src/views/tt/TtSettingsPanel.vue:124` 用 `v-if="!authStore.isHuguan"` 反向排除 TT 的「📊 Google 表格配置」卡片。户管目前看不到任何 sheet 配置。本设计补齐。

### 一句话目标

每个户管在 GG 与 TT 两个设置页各配置一张属于自己的看板表；系统把账户数据写进表，户管在表里改的数据（尤其**归属变更**）能同步回系统。

### 双向语义（用户 2026-09-23 明确）

> 「到时候户管就可以直接操作系统，从而自动更新表格，或则表更新，同步到系统」

- **系统 → 表**：账户变更时自动回写那一行；另有一个手动「同步到看板」按钮做全量刷新。
- **表 → 系统**：手动「从看板同步」按钮，先出差异报告，户管确认后才落库。

### 归属变更协议（本次设计的核心）

用户原话：

> 「这个归属需要完善一下，按表里的为准，另外一个用来保存这个户归属变化，ui增加一个户归属，只有户管角色可以看见这个，并且只有户管角色可以编辑运营变化，系统变化需要更新到表里的重新分配这一列，同步的时候表里运营列和重新分配列不一致，就以表里的重新分配为准，更新系统的数据。」

即：`运营`（TT 为 `接户运营`）列表示**当前归属**；`重新分配`（TT 为 `换绑情况`）列是**变更通道**，承载待应用的归属变更。两者不一致时以变更通道为准。

---

## 二、已定决策汇总

| # | 决策点 | 结论 | 来源 |
|---|---|---|---|
| 1 | 归属 | 每个户管独立一份；GG / TT 各一份（按平台分开配置） | 2026-09-22 |
| 2 | 用途 | 户管自己的账户管理看板（跨用户） | 2026-09-22 |
| 3 | 行由谁维护 | 户管自己维护行；系统只改单元格，不建行 | 2026-09-23 |
| 4 | 系统写哪些列 | 全部可映射列（含 `重新分配` / `换绑情况`） | 2026-09-23 |
| 5 | 写表时机 | 两者都要：账户变更时自动回写该行 + 手动「同步到看板」全量 | 2026-09-23 |
| 6 | 读回哪些列 | 全部可映射列 | 2026-09-23 |
| 7 | 读回触发 | 按钮 + 差异确认（`dry_run` → 确认 → 落库） | 2026-09-23 |
| 8 | 归属判据 | 按表里的为准；表里没有的账户自动建到该行运营名下 | 2026-09-23 |
| 9 | 表里有系统无 | 自动创建；运营列有值则归属该运营，无值则 `owner_id` 留空 | 2026-09-23 |
| 10 | TT `换绑情况` 列 | 与 GG `重新分配` 同义，是同一套归属变更通道 | 2026-09-23 |
| 11 | 编辑权 | 保持现状：admin / developer / 户管 均可改归属 | 2026-09-23 |
| 12 | 变更列收尾 | 落库后回写 `运营` 列 + 清空 `重新分配` 列 | 2026-09-23 |
| 13 | GG 列尾 | 用户先前给的 `账户ID 时区 MCC 运营` 是误粘贴，去掉。GG 14 列 / TT 13 列 | 2026-09-23 |

---

## 三、范围边界

### 做

- 户管专属的看板 sheet 配置（GG / TT 各一份，存 per-user）
- 系统 → 表：单行局部回写 + 全量刷新
- 表 → 系统：差异报告 + 确认落库
- 归属变更协议（运营列 / 重新分配列）
- 账户面板新增「户归属」字段（仅户管可见可编辑）

### 不做（YAGNI）

- 不从表里新建 MCC / BC / 渠道 / 用户。表中出现系统中不存在的 MCC 名、BC 名、渠道名、运营名时，只在差异报告里列为警告，不落库。
- 不做定时 / 自动触发的读回。只有户管点按钮才读。
- 不做 FB 平台。户管的 FB sheet 配置不在本设计内（用户只提了 GG 和 TT）。
- 不处理表里的删除 / 逻辑删除标记列。软删账户在差异报告里单独列出，不参与落库。
- 不新建工作表、不写表头、不调列宽。

---

## 四、数据结构与存储

### 4.1 配置存储

沿用现有的「`config` 表 key/value + JSON」模式（对照 `py/routes/tt_routes.py:855` 的 `tt_sheet_mappings_<uid>`）。

- 表：`config`（列 `key`, `value`）
- key：`huguan_dashboard_{user_id}`
- value：

```json
{
  "gg": { "spreadsheet_id": "1AbC...", "sheet_name": "户管看板" },
  "tt": { "spreadsheet_id": "1XyZ...", "sheet_name": "TT户管看板" }
}
```

两个平台各自独立的 `spreadsheet_id` 与 `sheet_name`（对应需求原文「这个sheet在gg和tt配置的是不一样的」）。

**不复用现有的「我的看板」配置**（`sheet_mappings_{uid}.my_dashboard`，`py/main.py:6424`）。理由：两者的列布局完全不同——「我的看板」是 8 列 `A运营 B账户ID C所属渠道 D国家 E时区 F备注 G是否封户 H是否解绑`，且按 B 列定位行、`display_name` 门禁、表 ID 取自全局 `tags.recharge_sheet_id`（`py/main.py:6406`）；户管看板是 14 / 13 列、跨用户、表 ID 来自户管自己的配置。混用会互相破坏。

### 4.2 账户表新增字段

**不新增数据库列**。归属复用已有的 `accounts.owner_id` / `tt_accounts.owner_id`（`INTEGER REFERENCES users(id)`，**可为空**，现库 0 条空归属）。「户归属」是 UI 层概念，落到 `owner_id`。

---

## 五、列 ↔ 字段映射

### 5.1 GG（14 列）

| 列 | 表头 | 系统字段 | 写 | 读 |
|---|---|---|---|---|
| A | 日期 | `accounts.acquired_date` | ✓ | ✓ |
| B | 是否封户 | `death_date` 非空 → `是`，空 → 空串 | ✓ | ✓（是 → 死亡；否/可用 → 存活） |
| C | 账户ID | `accounts.account_id` | ✓ | **定位键，不读回** |
| D | MCC | `mcc.name`（`accounts.mcc_id`） | ✓ | ✓ |
| E | 国家 | —（`accounts` 无此字段） | ✗ | ✗ |
| F | 所属渠道 | `agents.name`（`agent_id`） | ✓ | ✓ |
| G | 运营 | `users.display_name`（`owner_id`） | ✓ | ✓ |
| H | 重新分配 | `users.display_name`（`owner_id`） | ✓（按 §7 规则） | ✓（按 §7 规则） |
| I | 时区 | `accounts.timezone` | ✓ | ✓ |
| J | 大MCC | 父 `mcc.name`（`mcc.parent_mcc_id`） | ✓（派生，由 D 列推出） | ✗（派生列，读回会与 D 列打架） |
| K | 状态 | `account_statuses.name`（`status_id`） | ✓ | ✓ |
| L | 位置 | — | ✗ | ✗ |
| M | 消耗 | —（`accounts` 无此字段） | ✗ | ✗ |
| N | 产品信息 | — | ✗ | ✗ |

- 可写范围（非连续，跳过 E / L / M / N）：**`A:D` + `F:H` + `I:K`**
- 读回范围：**`A:N`**（14 列整段读，未映射列直接忽略）
- 读回**忽略**的列：`C`（定位键）、`J`（派生列，由 D 列 MCC 的父级推出，独立读回会与 D 列互相打架）、`E` / `L` / `M` / `N`（系统无对应字段）

### 5.2 TT（13 列）

| 列 | 表头 | 系统字段 | 写 | 读 |
|---|---|---|---|---|
| A | 入库时间 | `tt_accounts.acquired_date` | ✓ | ✓ |
| B | 是否回收 | `death_date` 非空 → `是`，空 → 空串 | ✓ | ✓ |
| C | 账户ID | `tt_accounts.advertiser_id` | ✓ | **定位键，不读回** |
| D | BC | `tt_bcs.name`（`bc_id`） | ✓ | ✓ |
| E | 国家 | `tt_accounts.country` | ✓ | ✓ |
| F | 所属渠道 | `agents.name`（`agent_id`） | ✓ | ✓ |
| G | 接户运营 | `users.display_name`（`owner_id`） | ✓ | ✓ |
| H | 时区 | `tt_accounts.timezone` | ✓ | ✓ |
| I | 状态 | `account_statuses.name`（`status_id`） | ✓ | ✓ |
| J | 消耗 | `tt_accounts.consumption` | ✓ | ✓ |
| K | 位置 | — | ✗ | ✗ |
| L | 换绑情况 | `users.display_name`（`owner_id`） | ✓（按 §7 规则） | ✓（按 §7 规则） |
| M | 产品信息 | `tt_accounts.remark` | ✓ | ✓ |

- 可写范围：**`A:J` + `L:M`**（跳过 K）
- 读回范围：**`A:M`**
- 读回**忽略**的列：`C`（定位键）、`K`（系统无对应字段）

---

## 六、系统 → 表（写）

### 6.1 服务层新增函数

`py/google_sheets_service.py` 新增（**不改** `update_cell_by_account_id`，纯增量）：

```python
def update_rows_by_account_id(service, spreadsheet_id, sheet_name, rows, key_col="C"):
    """按「账户ID 列」定位行，一次写多列。

    rows: [{"account_id": "123", "cells": {"A": "2026-09-23", "B": "", "G": "张三"}}]
    实现：读一次整表建立 账户ID → 行号 索引；再对每行做一次 values.batchUpdate，
    把 cells 按连续列合并成区间（如 A-D / F-H / I-K），非连续处断开，
    未出现在 cells 里的列一律不碰（保护公式列）。

    返回 {"updated": n, "not_found": ["<account_id>", ...]}
    """
```

关键点（对照 `append_recycle`，`google_sheets_service.py:450` 的既有先例——「只写 A/B/H 三列，其余列含公式，不写入以免清掉公式」）：

- 账户ID 写入时前缀 `'` 强制文本，避免长数字精度丢失（沿用 `append_recycle` 的做法）。
- 用 `valueInputOption="USER_ENTERED"`（与现有 `update_cell_by_account_id` 一致）。
- 账户ID 列（C）也在可写区间内，写回的是它自己的值，属幂等无副作用。
- 表里找不到该账户ID → 计入 `not_found`，不报错（户管的表不必包含所有账户）。

### 6.2 触发点（自动回写该行）

只在这些**会改动可映射列**的写操作之后触发：

**GG**（`py/main.py`）

| 端点 | 行号 |
|---|---|
| `POST /api/accounts` （新建） | :3993 |
| `POST /api/accounts/batch`（批量新建） | :4114 |
| `PUT /api/accounts/<aid>` | :4230 |
| `PUT /api/accounts/<aid>/reassign` | :4364 |
| `POST /api/accounts/batch-update` | :4584 |
| `POST /api/accounts/sync-from-sheet` | :4732 |

**TT**（`py/routes/tt_accounts_routes.py`）

| 端点 | 行号 |
|---|---|
| `POST /api/tt/accounts` | :86 |
| `POST /api/tt/accounts/batch` | :355 |
| `PUT /api/tt/accounts/<aid>` | :287 |
| `PUT /api/tt/accounts/<aid>/reassign` | :466 |
| `POST /api/tt/accounts/batch-update` | :419 |
| `POST /api/tt/accounts/sync-from-sheet` | :995 |

**不触发**：软删（`accounts_delete` :4435 / TT :499）、恢复（`accounts_restore` :4497 / TT :536）、永久删（:4534 / TT :553）。

理由：这三个操作只改 `deleted_at`，不触碰任何可映射列。入户管看板没有「是否解绑」列，所以也不该像现有「我的看板」那样在删除时写标记（`main.py:4450-4470`）。这是**有意的不对称**，写进注释以免后人「顺手补齐」。

### 6.3 触发后做什么

1. 解析发起者自己配置的看板（`huguan_dashboard_{uid}` → 对应平台）。**未配置 → 直接返回，静默跳过**（不是每个用户都是户管）。
2. 记录受影响账户 ID（变更前后的归属都要覆盖，因为可能换了 owner 导致行归属列变化）。
3. 起一个后台线程（沿用 `_sync_sheets_background` 模式，`main.py:5006`）：
   - 重新查库取这些账户的当前值
   - 调 `update_rows_by_account_id` 写 `运营`/`接户运营` 列
   - **不写** `重新分配` / `换绑情况` 列（见 §7 规则 2）
4. 异常只 `log.warning`，不影响主流程返回。

### 6.4 手动「同步到看板」（全量刷新）

`POST /api/huguan/dashboard/push`，body `{"platform": "gg"|"tt"}`。
取该系统内该户管可见的**全部**账户（GG：`accounts`；TT：`tt_accounts`），按 §5 逐列生成 cells，走 `update_rows_by_account_id` 一次性刷。同步返回 `{"total": n, "updated": n, "not_found": [...]}`。

---

## 七、归属变更协议

### 7.1 有效归属的判定（读回时）

对表中每一行：

```
重新分配 列非空  →  该行归属 = 重新分配 的值
重新分配 列为空  →  该行归属 = 运营 列的值
```

这就是用户说的「表里运营列和重新分配列不一致，就以表里的重新分配为准」。

### 7.2 四条硬规则

- **规则 1（变更通道优先）**：如上，`重新分配` / `换绑情况` 非空时压过 `运营` / `接户运营`。
- **规则 2（变更通道不被自动回写碰）**：§6.2 的全部自动回写，**都不得写** `重新分配` / `换绑情况` 列。
  *为什么*：这一列是户管在表里的输入通道。若某次无关的账户变更自动回写顺手把它清空，户管刚填的变更就被静默吞掉了。
- **规则 3（这一列只有两个写点）**：
  - ① 户管在**系统 UI** 改归属 → 写该行 `重新分配` = 新归属的 `display_name`。
  - ② 「从看板同步」**成功应用**归属变更后 → 写该行 `重新分配` = `""`（清空）。
- **规则 4（落库后回写运营列）**：同步中一旦应用了某行的归属变更，该行的 `运营` / `接户运营` 列改写为新归属名。这样两列重新一致，下一次同步不会重复应用同一条变更。

### 7.3 归属名 → `owner_id` 的解析

按 `users.display_name` 精确匹配，匹配不到回退 `users.username`。

- 命中唯一一条 → 落库 `owner_id`。
- 命中 0 条或 ≥2 条 → 该行归属列为警告（`{"row": i, "message": "运营「X」无法识别，已跳过归属变更"}`），**不落库归属**，该行其余列照常处理。

### 7.4 空归属

`运营` 与 `重新分配` **都为空**的表行：

- 系统里已有该账户 → 归属保持不变（不因表里空着就把 `owner_id` 清空）。
- 系统里没有该账户 → 新建，`owner_id` 留 `NULL`（用户原话「没有的运营列就空着就好，户管随时可以更改运营归属」）。

⚠️ 已知后果：`owner_id` 为 `NULL` 的账户对普通用户不可见（列表按 owner 过滤），只有户管 / admin / developer 看得到——这正是「户管随时可以更改」所要求的中间态。

### 7.5 TT `reassign` 的既有缺口（需要一并处理）

GG 的 `accounts_reassign`（`py/main.py:4364-4426`）在 `actor_role in CROSS_USER_ROLES` 时接受 body 里的 `owner_id`，可转给任意用户。

TT 的 `reassign_account`（`py/routes/tt_accounts_routes.py:466-496`）**完全忽略 body 里的 `owner_id`**，永远 `UPDATE tt_accounts SET owner_id = uid` —— 只能「认领给自己」，不支持转给别人。

因此 TT 侧「户管更改归属」目前**没有通路**。本设计需扩展 TT 的 reassign：当 `actor_role in CROSS_USER_ROLES` 且 body 带合法 `owner_id` 时转给该用户，否则维持原行为（转给调用者）。这是对既有接口的**行为扩展**，按纯增量原则在此明确报备：

- 默认路径（不带 `owner_id`，或调用者非跨用户角色）逐字节保持原逻辑与原返回文案。
- 新增路径仅在 `CROSS_USER_ROLES` + 合法 `owner_id` 时生效。
- 返回文案需区分「已转移至当前用户」与「已从 A 转移至 B」（对照 GG 的 `main.py:4419-4424`）。

---

## 八、表 → 系统（读）

### 8.1 接口

`POST /api/huguan/dashboard/sync`
body：`{"platform": "gg"|"tt", "dry_run": true}` / `{"platform": ..., "dry_run": false, "confirmed": {...}}`

全部 `@jwt_required()` + **户管限定**（非户管 403）。

### 8.2 归属门禁的替换（重要）

现有 `accounts_sync_from_sheet`（`py/main.py:4732`）有一个身份门禁：收集 A 列「运营」的所有值，当前登录用户的 `display_name` 不在其中就返回 400

> 「这不是你的私有看板表，请修改。Sheet 中运营为「{operators}」，当前登录用户为「{current_display_name}」」

**这道门禁对户管看板不适用、也不该复用**——户管看板是跨用户的，一张表里躺着多个运营的账户。

**新的防护口径**：只允许同步**当前户管自己配置的那张表**。`spreadsheet_id` 与 `sheet_name` **一律从 `huguan_dashboard_{uid}` 配置里取**，请求体不接受、也不返回任何表地址。这样户管既不能对着别人的表发起同步，也无法通过改请求体指向别的表。跨用户是这张表**配置好了就该有的**属性，不是漏洞。

### 8.3 读回流程

1. 取配置里的 `spreadsheet_id` / `sheet_name`；未配置 → 400「请先在设置页配置户管看板」。
2. `build_service` + `read_sheet_values(..., "A:N" / "A:M")`。
3. 跳过第 1 行表头。**不跳过任何数据行**（没有「是否解绑」列可用来跳过）。
4. 逐行解析：
   - 账户ID（C 列）为空 → 警告跳过。
   - 其余列按 §5 解析；未映射列（GG 的 E/L/M/N、TT 的 K）直接忽略。
5. 批量查库：按本行账户ID 集合查 `accounts` / `tt_accounts`（**不按 owner 过滤**——跨用户）。
6. 逐行比对，产出五类差异：

| 类别 | 判定 | 落库动作 |
|---|---|---|
| `to_create` | 系统无此账户ID | 新建，归属按 §7.4 |
| `to_update` | 系统有，且任一可映射列有差异 | 按表覆盖该列 |
| `owner_changes` | 归属判定结果 ≠ 系统当前 `owner_id` | 改 `owner_id`，并记入 §7.2 规则的收尾动作 |
| `to_skip` | 系统有但已软删（`deleted_at` 非空） | 不动，报告里单列 |
| `warnings` | 名称无法唯一匹配、账户ID 为空等 | 不动 |

7. `dry_run=true` → 返回差异报告（含 `summary` 计数），前端展示给户管确认。
8. `dry_run=false` → 只执行 `confirmed` 里户管勾选的部分，`db.commit()`，清缓存。
9. 收尾：对应用了归属变更的行，回写 `运营` 列 + 清空 `重新分配` 列（§7.2 规则 3②、规则 4）。

### 8.4 名称 → 主键的解析规则

统一口径（MCC / 大MCC / BC / 渠道 / 状态 / 归属都适用）：

- **唯一命中才落库**；命中 0 条或 ≥2 条 → 警告，该列不落库，该行其余列照常。
- 状态（GG K 列 / TT I 列）解析时按**该账户的 owner** 作用域查 `account_statuses(name, owner_id)`；查不到则在该 owner 下 `INSERT` 新建（对照 `main.py:4922-4931` 的现有做法）。
- `是否封户`（GG B）与 `状态`（GG K）都能表达状态，**冲突时 K 列为准**（更具体）；`is_dead = (K == "死亡") or (B in ("是",))`，实际落库时由最终状态反推 `death_date`。TT 的 `是否回收`（B）与 `状态`（I）同理。

---

## 九、UI 改动

> 涉及前端 UI，按 CLAUDE.md 规定，实现前须先走 `/frontend-design`。

### 9.1 设置页新增户管看板配置卡片

- `frontend/src/views/SettingsPanel.vue`（GG）：新增 `<el-card v-if="authStore.isHuguan">`「📊 户管看板配置」，与既有的 `v-if="authStore.isAdmin || authStore.isDeveloper"` 充值表卡片**并列且互不干扰**（户管看不到后者，管理员看不到前者）。
- `frontend/src/views/tt/TtSettingsPanel.vue`（TT）：同上，「📊 户管看板配置」。

卡片内容：

| 控件 | 行为 |
|---|---|
| 表格 ID / 链接输入框 | 接受裸 ID 或完整 URL（沿用 `_parse_sheet_id` 口径，`main.py:6406`） |
| 「📋 读取工作表」按钮 | 复用既有 `GET /api/google-sheets/sheets`（`main.py:7453`，户管已可达，无需新增接口） |
| 工作表名下拉 | 选择 `sheet_name` |
| 「💾 保存配置」 | `POST /api/huguan/dashboard` |
| 「🔄 同步到看板」 | `POST /api/huguan/dashboard/push`，全量刷新，出 toast |
| 「⬇️ 从看板同步」 | `POST /api/huguan/dashboard/sync` `dry_run=true` → 弹差异确认框 → 确认后 `dry_run=false` |

### 9.2 账户面板新增「户归属」字段（仅户管可见可编辑）

- `frontend/src/views/AdsAccountPanel.vue`（GG）
- `frontend/src/views/tt/TtAccountPanel.vue`（TT）

新增一列「户归属」+ 编辑入口（下拉选用户）：

- 可见性用 `v-if="authStore.isHuguan"`（`frontend/src/stores/auth.js:15`，已存在）控制——只有户管角色看得见这一列。
- 下拉数据源复用 `GET /platform/users`，取 `res.users`，label 为 `display_name || username`，value 为 `id`（对照 `frontend/src/components/OwnerFilterSelect.vue:52-59`）。**户管的「户归属」下拉不做「只列有账户的用户」过滤**——跨平台/跨用户改归属正是户管的职责，这与既有的户管豁免口径（`ownerScope.js`）一致。
- **仅户管可编辑**（用户原话「只有户管角色可以编辑运营变化」）。
- 提交走既有的 `PUT /api/accounts/<aid>/reassign`（GG）/ `PUT /api/tt/accounts/<aid>/reassign`（TT），body 带 `owner_id`。
- 归属变更成功后，若当前操作者是户管且已配置看板，系统写该行 `重新分配` / `换绑情况` 列 = 新归属名（§7.2 规则 3①）。

> 注：决策 #11「编辑权保持现状」指的是**接口层权限**不变（admin / developer / 户管 仍都可改归属）；本节的「仅户管可见可编辑」是**这个新增 UI 字段**的可见性口径，两者不冲突。

---

## 十、回归保障

### 10.1 后端测试

新建 `py/tests/test_huguan_dashboard.py`，覆盖：

1. **配置读写**：POST 后 GET 能取回；GG / TT 互不覆盖（平台隔离）。
2. **权限**：非户管访问 `/api/huguan/dashboard*` 全部 403。
3. **列映射**：给定账户 fixture，验证 §5 的 GG 9 项 / TT 11 项写值正确，且**跳过列（GG E/L/M/N、TT K）不在写入区间内**。
4. **区间合并**：`update_rows_by_account_id` 按连续列合区间，`not_found` 正确回传。
5. **归属协议**：
   - `重新分配` 非空 → 压过 `运营`（规则 1）
   - 自动回写**不写** `重新分配` 列（规则 2，用写入区间断言）
   - 同步应用后 `运营` 被回写、`重新分配` 被清空（规则 3②、4）
6. **差异报告**：`dry_run=true` 不改库；`to_create` / `to_update` / `owner_changes` / `to_skip` / `warnings` 五类各自的判定。
7. **空归属**：`运营` 与 `重新分配` 全空 → 新建账户 `owner_id IS NULL`。
8. **不触发**：软删 / 恢复 / 永久删不产生任何 sheet 写调用。
9. **TT reassign 扩展**：`CROSS_USER_ROLES` + `owner_id` → 转给目标；不带 `owner_id` → 原行为与原文案逐字节不变。

Google Sheets 调用在测试中一律 mock（对照现有测试做法），不打真实 API。

门禁：`cd py && python -m pytest tests/ -q`，基线 **420 passed**，新增后只增不减。

### 10.2 前端

无测试框架，门禁为 `npm run build` 通过。

---

## 十一、涉及文件清单

| 文件 | 动作 |
|---|---|
| `py/routes/huguan_dashboard_routes.py` | **新建** blueprint：配置读写 + push + sync |
| `py/main.py` | 注册 blueprint（对照 :351-361）；6 个 GG 触发点接上回写；`_execute_sync_create` 支持空归属 |
| `py/google_sheets_service.py` | 新增 `update_rows_by_account_id`（不改既有函数） |
| `py/routes/tt_accounts_routes.py` | 6 个 TT 触发点接上回写；`reassign_account` 支持跨用户 `owner_id` |
| `py/routes/helpers.py` | 可能新增归属名→`owner_id` 解析辅助（复用于两个平台） |
| `frontend/src/views/SettingsPanel.vue` | 新增户管看板配置卡片 |
| `frontend/src/views/tt/TtSettingsPanel.vue` | 同上 |
| `frontend/src/views/AdsAccountPanel.vue` | 新增「户归属」列 |
| `frontend/src/views/tt/TtAccountPanel.vue` | 同上 |
| `frontend/src/api/huguan.js` | **新建** API 封装 |
| `py/tests/test_huguan_dashboard.py` | **新建**测试 |

---

## 十二、风险与已知代价

1. **户管手改 `运营` 列会被自动回写覆盖。** 系统把 `运营` 列当可写列，任何账户变更都会重刷该行。若户管在表里手改了 `运营` 但**尚未同步**，这次回写会把他的改动冲掉。缓解：变更通道是 `重新分配` 列，UI 文案与文档都引导户管「改归属请填重新分配列」。这是决策 #4「系统写全部可映射列」的已知代价。
2. **归属变更权限很大。** 按「表里为准」，户管表里一行写谁的名，同步后就归谁。护栏是**差异确认页**——`owner_changes` 单列一类，户管逐个确认才落库。
3. **`account_id` / `advertiser_id` 全局 UNIQUE。** 表里出现系统已存在的同一账户ID 但归属不同 → 走 `owner_changes` 改归属，而不是新建（否则撞 UNIQUE 约束）。
4. **名称歧义。** MCC / BC / 渠道 / 状态名重名时该列不落库（§8.4）。户管会在差异报告里看到警告，需要自己去把表里的名字写准确。
5. **一次同步的请求耗时。** 全量 push 会逐行调 Sheets API。首版不做并发，账户量大时可能较慢；若实测超时，再考虑 `spreadsheets.values.batchUpdate` 聚合成单次请求（已在 §6.1 的区间合并里留了余地）。

---

## 十三、范围外（明确不做）

1. FB 平台的户管看板配置。
2. 定时 / 自动触发的读回同步。
3. 从表里反向创建 MCC / BC / 渠道 / 用户。
4. 表结束列之外的任何结构改动（新建工作表、写表头、调列宽、设数据验证）。
5. 户管看板的变更历史 / 审计日志。
