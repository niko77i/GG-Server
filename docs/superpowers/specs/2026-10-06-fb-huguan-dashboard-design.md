# FB 户管看板（子项目 ②）设计

> 日期：2026-10-06
> 范围：把户管看板的 Google Sheet 双向同步扩到 FB 平台。
> 前置：子项目 ①（FB 资产数据模型）已交付并门禁全绿（`bdef5e0`），见
> `docs/superpowers/specs/2026-10-06-fb-asset-data-model-design.md`。
> 后续：子项目 ③（双向撤回）另出文档。

---

## 一、需求描述

### 背景

GG / TT 的户管看板已上线（`2026-09-23-huguan-sheet-design.md`）。FB 户管的资产模型由子项目 ① 补齐后，
本子项目把看板本身接上：配置、写表、读回同步。

用户 2026-10-06 给出的 FB 看板列（17 列，原文）：

> 日期 / 操作人 / 账户名称 / 资产UID / 所属渠道 / 资产类型 / 单价 / 入库 / 接户运营 /
> 在用运营 / 出库时间 / 出库 / 时区 / 消耗 / 状态 / 位置 / 产品信息（备注）

### 一句话目标

每个 FB 户管在 FB 设置页配置一张自己的看板表，系统与表之间双向同步，语义与 GG / TT 一致，
但**归属协议不同**（见第三节）。

---

## 二、已定决策汇总

| # | 决策点 | 结论 | 来源 |
|---|---|---|---|
| 1 | 权威归属列 | **「在用运营」** → `fb_accounts.owner_id` | 2026-10-06 |
| 2 | 变更通道列 | **无**。FB 不用通道协议（GG 仍在用，TT 已于 2026-10-06 弃用，见 §3） | 2026-10-06 |
| 3 | 「在用运营」列回写 | **系统会回写**（镜像列），同时也读回作变更源 | 2026-10-06 |
| 4 | 「接户运营」列内容 | 系统在归属变更时写 `"{旧}转{新}"`（一格里放整串） | 2026-10-06 |
| 5 | 「接户运营」读写 | **双向**（户管填的也写回系统） | 2026-10-06 |
| 6 | 「接户运营」存储 | ① 的 `acceptor_id` **改成 TEXT 列**，整串原样存、不解析 | 2026-10-06 |
| 7 | 「位置」列 | 主 BM 名（`fb_account_bm.is_primary`），① 已定 | 2026-10-06 |
| 8 | 主 BM 变更留痕 | **写 `fb_account_bm_history`** | 2026-10-06 |
| 9 | 「是否封户」列 | **无**。FB 无 `death_date`，生死只由状态列表达 | 子项目 ① |

---

## 三、归属协议（FB 版，与 GG/TT 不同）

### 3.0 三个平台现在各走一套 —— 先看清现状

原设计（`2026-09-23-huguan-sheet-design.md` §7）是**三平台统一的变更通道协议**：户管在
`重新分配` / `换绑情况` 列填报变更，§7.2 规则 2 规定自动回写**永不碰**该列，以免户管刚填的
变更被一次无关的回写静默吞掉。

**这个前提已经不成立了。** TT 于 2026-10-06（提交 `fa0fed5`）弃用了通道协议：

```python
# COLUMN_SPEC["tt"]
("L", "换绑情况", "owner_change_note", False, True),   # 原 ("_owner_channel", True, True)
```

新增 `tt_accounts.owner_change_note TEXT DEFAULT ''`，语义是「系统单点写入（`reassign` 端点）、
只读回、**不参与任何全量/单行回写**」—— 靠 `writable=False` 把该列排除出 `cells_for_row`。

现状因此是三套：

| 平台 | 归属列 | 记录/通道列 | `COLUMN_SPEC` 里的可写标志 |
|---|---|---|---|
| GG | G 运营 | H 重新分配（`_owner_channel`，**通道协议**） | `True, True`（自动回写另行跳过） |
| TT | G 接户运营 | L 换绑情况（`owner_change_note`） | **`False, True`**（批量回写天然跳过） |
| **FB** | **J 在用运营** | **I 接户运营**（`acceptor`） | **`False, True`** —— 与 TT 同形 |

> `OWNER_CHANNEL_COL = {"gg": "H", "tt": "L"}` 与 `writeback_owner_channel` 仍在，GG 用它写通道列、
> TT 用它写换绑记录（定向写，不走批量）。**FB 不登记进这张表** —— 见 §6.5。

### 3.1 FB 的协议

**FB 没有通道列。** 协议改为：

| 动作 | FB 的行为 |
|---|---|
| 读回时判归属 | 取**在用运营**列的值 → `resolve_owner_id` → 与 `owner_id` 比对 |
| 系统 → 表（自动回写 / 全量刷新） | 写**在用运营**列 = 当前归属人；写**接户运营**列 = `"{旧}转{新}"`（仅当归属刚变过） |
| 表 → 系统（同步落库） | 在用运营列变了 → 改 `owner_id`，同时把 `acceptor` 写成 `"{旧}转{新}"` |
| 接户运营列 | 可读可写。读回时**原样存进 `acceptor`（TEXT）**，不做名称解析、不参与归属判定 |

### ⚠️ 已知代价（必须在 UI 文案里交代）

**「在用运营」既是系统回写的镜像列，又是户管的输入列。** 户管在表里改了归属但**还没同步**时，
一次无关的账户变更触发的自动回写会把他的改动冲掉 —— 这正是 GG/TT 当初加通道列要解决的问题。

FB 按用户 2026-10-06 的选择不走通道列，接受该代价。缓解手段只有一条：
**同步确认框必须把「归属变更」单列一类、逐条勾选**（沿用 GG/TT §8.3 的做法），
让户管在落库前看得见。

---

## 四、列映射（17 列）

`READ_RANGE["fb"] = "A:Q"`，定位键 `KEY_COL["fb"] = "D"`（资产UID = `fb_accounts.account_id`）。

| 列 | 表头 | 系统字段 | 写 | 读 | 备注 |
|---|---|---|---|---|---|
| A | 日期 | `acquired_date` | ✓ | ✓ | |
| B | 操作人 | `operator` | ✓ | **✗** | **冻结字段**：系统写，绝不读回（子项目 ① §6.1） |
| C | 账户名称 | `name` | ✓ | ✓ | |
| D | 资产UID | `account_id` | ✓ | **✗** | 定位键 |
| E | 所属渠道 | `channel_id` ← `fb_channels.name` | ✓ | ✓ | 名称解析走 `fb_channels` |
| F | 资产类型 | `asset_type_id` ← `fb_asset_types.name` | ✓ | ✓ | 名称解析走 `fb_asset_types` |
| G | 单价 | `unit_price` | ✓ | ✓ | TEXT |
| H | 入库 | `inbound_qty` | ✓ | ✓ | TEXT（数量） |
| I | 接户运营 | `acceptor` | ✓ **定向** | ✓ | TEXT，整串 `"A转B"`，不解析；**不走批量回写**（§4.1） |
| J | 在用运营 | `owner_id` ← `display_name` | ✓ | ✓ | 归属列 |
| K | 出库时间 | `outbound_date` | ✓ | ✓ | |
| L | 出库 | `outbound_qty` | ✓ | ✓ | TEXT（数量） |
| M | 时区 | `timezone` | ✓ | ✓ | |
| N | 消耗 | `consumption` | ✓ | ✓ | |
| O | 状态 | `status_id` ← `account_statuses.name` | ✓ | ✓ | 查重键 `(name, platform='fb')` |
| P | 位置 | 主 BM 名 | ✓ | ✓ | `fb_account_bm.is_primary=1` 那条的 `fb_bms.name` |
| Q | 产品信息 | `remark` | ✓ | ✓ | |

- 可写区间：**`A:Q`**（B 与 D 标 ✓ 但语义特殊：`operator` 由系统填、`account_id` 是幂等自写）
- 不可读：**B**（冻结）、**D**（定位键）
- 无「是否封户 / 是否回收」列

### 4.1 I 列（接户运营）：系统维护它，但只走定向写入

**先说清楚系统确实会写这一列** —— 它的内容是归属变更的记录（`"{旧}转{新}"`），
由系统在两个时刻写入：

1. 系统侧归属变更（`reassign` 端点）→ 写 `"{旧}转{新}"`
2. 同步落库应用了归属变更（`apply_diff` 的 `owner_changes` 收尾）→ 写 `"{旧}转{新}"`

两个写点都走**定向写入**：只带该一列，不碰同行其它列。

**唯一被排除的是「批量回写」**（`刷新到看板` 与账户变更触发的单行回写）。实现方式是
`COLUMN_SPEC["fb"]` 里把 I 列标成 `writable=False` —— 于是 `cells_for_row`
（`huguan_dashboard.py:88-89` 的 `if not writable ... continue`）天然不产出它。理由：

> 若批量回写照常重算 I 列，那么**每一次刷新到看板都会把它重写一遍**。它记的是
> 「上一次换绑是从谁到谁」，不是由账户当前状态能推导出来的东西 —— 账户当前只有
> `owner_id`（现任），推不出前任。批量重算只会用存储值覆盖，看似幂等，但一旦
> 表里刚被户管改过还没同步，这次刷新就静默吞掉了那个改动。

**这与 TT 刚落地的形状完全一致**（§3.0 表格：TT 的 L 列也是 `False, True`），
不是 FB 的特例。三个平台的共同规则是：**批量回写只写「由账户当前状态可推导」的列。**

---

## 五、`hd.PLATFORMS` 扩三元的连带改动

`py/huguan_dashboard.py` 里的分平台分支**共 7 处**，逐处列出（不改的后果在右列）：

| 行 | 现状 | 不改的后果 |
|---|---|---|
| `:16` | `PLATFORMS = ("gg", "tt")` | 配置接口 400 拒掉 fb；路由的 `platform not in hd.PLATFORMS` 同样拒 |
| `:292` | `_SQL_AGENT_TT if platform == "tt" else _SQL_AGENT_GG` | FB 的渠道去查 `agents` 表 —— 而 FB 渠道在 `fb_channels`（子项目 ① §4.2 刻意不复用 agents） |
| `:346` | `table = "tt_accounts" if platform == "tt" else "accounts"` | **静默写进 GG 表** |
| `:664` | 同上 | **静默写进 GG 表** |
| `:766` | 同上（`_apply_death` 内） | **静默写进 GG 表** + FB 无 `death_date` 列 → SQL 报错 |
| `:822` | `_TT_ROW_SQL if platform == "tt" else _GG_ROW_SQL` | FB 的行数据从 GG 表取 |

**改法**：把 5 处二元表达式改成以 `platform` 为键的字典查表（`_TABLE_FOR_PLATFORM`、
`_AGENT_SQL`、`_ROW_SQL`），缺键即 `KeyError` —— 比 `else` 兜底安全，后者会把未知平台静默导向 GG。

需要补 "fb" 键的既有字典：`COLUMN_SPEC` / `KEY_COL` / `OWNER_COL` / `READ_RANGE` /
`ACCOUNT_KEY_FIELD` / `_PLAIN_TEXT_FIELDS`。`OWNER_CHANNEL_COL` 对 FB **无对应列** ——
需要把它改成「FB 没有」的显式表达，而不是硬塞一个字母。

`_CHANNEL_HISTORY_SPEC`（MCC/BC 变更历史）对 FB **没有对应物**：FB 的历史表是
`fb_account_bm_history`，而它挂在**中间表**上、不是 `fb_accounts` 的一个外键列，
现有 `_record_channel_change` 的形状装不下。见第六节第 4 点。

---

## 六、FB 特有的实现点

### 6.1 `_apply_death` 对 FB 必须跳过

`_apply_death` 执行 `UPDATE {table} SET death_date=...`。`fb_accounts` **没有 `death_date` 列**
（子项目 ① 已确认），FB 走到这里会 `OperationalError`。

FB 的生死完全由状态列（O 列）承载：`is_dead()` 对 FB 只看 `status_name == "死亡"`，
落库时已经通过 `status_id` 表达，不需要额外的死亡日期。**FB 分支直接 return。**

`build_diff` 里 `_collect_updates` 仍在结果里放 `_is_dead`（合成键）—— 对 FB 保持该键存在但
`apply_diff` 不据此写 `death_date`，以免留下一个「FB 有死亡标记但没人消费」的隐式契约。

### 6.2 `_resolve_field` 要认 FB 的两个新名称字段

现有实现只认 `mcc_name` / `agent_name` / `bc_name`，各平台同名字段走不同 SQL。FB 需要：

| 字段 | SQL | 说明 |
|---|---|---|
| `channel_name` | `SELECT id FROM fb_channels WHERE name=? AND platform='fb'` | 唯一约束 `(name, platform)` ⇒ 至多命中 1 行，**无歧义档** |
| `asset_type_name` | `SELECT id FROM fb_asset_types WHERE name=? AND platform='fb'` | 同上 |

两者与 `status_name` 一样是「至多命中 1 行」，因此**不属于** `_resolve_field` 的
「命中 0 或 ≥2 条即警告」档 —— 但要保持既有形状（`_resolve_field` 返回 `(known, resolved)`），
查不到时记 warning 并跳过该列，与 `mcc_name` 一致。

`_target_column` 要补 `channel_name → channel_id`、`asset_type_name → asset_type_id`。

### 6.3 「位置」列 = 主 BM 的读写

- **写**（系统 → 表）：取 `is_primary=1` 那条的 `fb_bms.name`；没有主 BM 则空
- **读**（表 → 系统）：表里填了 BM 名 → 解析成 `bm_id` → **换主 BM**（先清后设，子项目 ① §4.3）；
  表里空着 → 只把所有 `is_primary` 置 0，**不删**任何关联行
- **留痕**：主 BM 真变了（旧值 ≠ 新值）→ 写一行 `fb_account_bm_history`
  （`old_bm_id` / `new_bm_id` / `changed_by` / `change_type='batch'`，与既有值同档）

> ⚠️ `fb_account_bm_history.account_id` **没有 `ON DELETE CASCADE`**（`account_mcc_history` /
> `tt_account_bc_history` 都有）。子项目 ③ 的撤回若删新建账户，必须显式先删该表历史行，
> 否则外键会挡下删除。

### 6.4 「接户运营」的写点

两处，都要写 `"{旧}转{新}"`：

1. **系统 → 表**：归属在系统侧变更时（`reassign` 端点），写该行 I 列
2. **表 → 系统**：同步落库应用归属变更时（`apply_diff` 的 `owner_changes` 分支），
   写 `acceptor = f"{旧名}转{新名}"`，并在收尾时回写表

**旧名怎么取**：从库里读该账户变更**之前**的 owner 显示名（`display_name or username`），
与 GG/TT 的 `old_owner` 取法一致（`main.py:4609`）。

### 6.5 `writeback_owner_channel` / `OWNER_CHANNEL_COL` 不能扩到 FB

`OWNER_CHANNEL_COL = {"gg": "H", "tt": "L"}` 驱动 `owner_channel_cells` +
`writeback_owner_channel`，它的语义是「把**新归属人的名字**写进那一列」：

- GG 写 H「重新分配」= 新归属名（通道协议）
- TT 写 L「换绑情况」= 新归属名（单点记录）

FB 要写的内容**不是新归属名，而是 `"{旧}转{新}"` 整串**，语义不同。
把 `"fb"` 加进 `OWNER_CHANNEL_COL` 会让 FB 走进一个写错内容的路径。

因此：**该表不登记 fb 键**，FB 新增一个专用回写函数（暂名 `writeback_fb_acceptor`），
调用点与 GG/TT 对称。GG/TT 的既有行为**逐字节不变**。

> 若将来要合并这两个函数，合并的前提是先把「写什么内容」参数化 —— 不要为了复用而
> 让 FB 借用 GG/TT 的语义。

---

## 七、对子项目 ① 的修订（需明确记录）

`fb_accounts.acceptor_id` 从 `INTEGER REFERENCES users(id)` **改成 TEXT**。

理由：用户 2026-10-06 明确「接户运营一格里放『A转B』」且「双向」。一个外键装不下复合串。

- 该列由子项目 ① 在 `2026-10-06` 当天新增，**无生产数据**
- 改法：`_ensure_columns` 里新增 `acceptor TEXT DEFAULT ''`；旧列 `acceptor_id` 不再被读写
  （SQLite 支持 `DROP COLUMN`，但仓库既有迁移不轻易删列；本次**保留旧列不管**，
  在列注释里写清已废弃，避免 `_add_column_if_missing` 那种「删了又补」的陷阱）
- ① 的 `create_account` / `update_account` 同步改写 `acceptor` 而非 `acceptor_id`
- ① 的前端表单把「接户运营」从用户下拉改成文本输入

> 这违反「纯增量」的字面要求，属于**已交付子项目的语义修订**，用户 2026-10-06 已明确同意。

---

## 八、触发点（FB 侧接上回写）

子项目 ① **刻意**没有在 FB 端点里调 `hd.writeback_*`（等本子项目落地）。本次接上：

| 端点 | 文件 | 动作 |
|---|---|---|
| `POST /api/fb/accounts/create` | `py/routes/fb_routes.py` | `hd.writeback_rows(uid, "fb", [account_id])` |
| `PUT /api/fb/accounts/<aid>` | 同上 | 同上 |
| `PUT /api/fb/accounts/<aid>/reassign` | 同上 | `writeback_rows` + FB 专用的「接户运营」回写 |

**不触发**：软删（`delete_account`）、恢复（`restore_account`）、永久删（`permanent_delete_account`）
—— 理由与 GG/TT 一致（只改 `deleted_at`，不碰任何可映射列）。

---

## 九、前端

按用户 2026-10-06 指定，**不走 `/frontend-design`**，沿用 GG/TT 既有样式。

| 文件 | 动作 |
|---|---|
| `frontend/src/views/fb/FbSettingsPanel.vue` | 挂 `<HuguanDashboardCard platform="fb" />` |
| `frontend/src/components/HuguanDashboardCard.vue` | `props.platform` 加 `'fb'`；`VIA_LABELS` / `FIELD_LABELS` / `PUSH_COVER` / `PUSH_SAFE` 补 fb 分支 |
| `frontend/src/views/fb/FbAccountPanel.vue` | 「接户运营」从用户下拉改成文本输入（第七节） |

`HuguanDashboardCard` 里 FB 的分支要处理：FB **没有变更通道列**，所以
`OWNER_WRITEBACK_TEXT` 与 `PUSH_SAFE` 的文案要按 FB 的协议改写。

---

## 十、回归保障

新增 `py/tests/test_fb_huguan_dashboard.py`：

1. **三平台的表名映射**：`build_diff` / `apply_diff` / `_apply_death` / `collect_rows_for_push`
   对 `platform="fb"` 全部解析到 `fb_accounts`（**回归点**：二元判断漏改会静默写 GG 表，
   断言必须验到真实落库表，不能只看返回码）
2. **17 列映射**：给定 FB fixture，验证写值列与跳过列（B、D 不读）
3. **归属协议**：在用运营非空 → 改 `owner_id`；`acceptor` 被写成 `"{旧}转{新}"`
4. **接户运营双向**：表里填的串原样落进 `acceptor`，**不做名称解析、不因解析失败出警告**
5. **位置列**：写主 BM 名；读回换主 BM（先清后设）；填了不存在的 BM 名 → 警告不落库
6. **主 BM 留痕**：真变更写 `fb_account_bm_history`，值没变不写
7. **`_apply_death` 对 FB 是 no-op**：状态为「死亡」时**不**尝试写 `death_date`
   （SQL 会报错，这条是防回归的关键断言）
8. **未配置看板时静默跳过**（不是每个 FB 用户都是户管）
9. **GG/TT 行为逐字节不变**：既有 `test_huguan_dashboard.py` 全绿

门禁：`cd py && python -m pytest tests/ -q`（基线 1011 passed）；`cd frontend && npm run build`。

---

## 十一、风险与已知代价

1. **「在用运营」列会被自动回写冲掉**（§3.1）。FB 无通道列的直接代价，用户已知悉。
   TT 用「该列只读回、不回写」回避了这个风险，但 FB 的「在用运营」**必须可读可写**
   （户管要靠它在表里改归属），所以回避不了 —— 这是 FB 独有的敞口，三个平台里最大的一个。
2. **`acceptor` 是自由文本，不校验、不解析。** 户管填什么就存什么。
   好处是不会因人名含「转」而解析错；代价是这一列的数据质量完全靠人。
3. **三处静默写错表的二元判断**是本子项目最大的回归风险。改法用字典查表 + 缺键 `KeyError`，
   并且测试要断言**真实落库表**而不只是响应。
4. **`fb_account_bm_history` 无 `ON DELETE CASCADE`** —— 子项目 ③ 的撤回必须显式处理。
5. **`PUT /api/fb/accounts/<aid>` 是全量覆盖写法**（没传的字段被写成空）。
   当前无调用方只发部分字段（`apply_diff` 走直接 SQL 打补丁、`reassign` 是独立端点、
   面板整套提交），但这是个留给将来调用方的坑，记入台账不修。

---

## 十二、范围外

1. **双向撤回**（子项目 ③）
2. FB 的 BM / 像素 / 产品域改动
3. 把 `PUT /api/fb/accounts/<aid>` 改成字段存在性驱动（风险 5）
4. 给 FB 补变更通道列（用户已明确不走该协议）
