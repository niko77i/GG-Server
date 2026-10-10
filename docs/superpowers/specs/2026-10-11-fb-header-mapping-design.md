# FB 户管看板：按表头映射字段（设计）

> 2026-10-11。本文件只覆盖**子项目 A**：把 FB 从「按列字母读」改成「按表头名读」，
> 并给它一块与 TT 同款的**列映射**面板。仍是**单表**。
> 子项目 B（FB 多表 + 户类型 + 账户页筛选）**另立 spec**，见 §五非目标。

## 一、问题

FB 的 17 列在 2026-10-06 就分配好了（`COLUMN_SPEC["fb"]`，设计见
`2026-10-06-fb-huguan-dashboard-design.md` §四「列映射（17 列）」）。但那份分配现在的键是
**列字母**：

```
A→acquired_date  D→account_id  J→owner_name  …
READ_RANGE["fb"] = "A:Q"      KEY_COL["fb"] = "D"
```

**表头那一栏只是文档里的注释，运行时从不读它。** 户管一旦改名、插列、或两列对调，
映射就悄悄错位：读的时候把「时区」的值塞进「消耗」，写的时候把运营名写进国家列 ——
**静默串列**。这正是 TT 在 2026-10-09 修掉的那个 bug
（`2026-10-09-tt-header-mapping-design.md`），FB 当时不在该次范围内。

这次把 FB 的映射键从「列字母」换成「表头名」，别的都不动。

## 二、已确认的决策（用户 2026-10-11 逐条裁定）

| # | 决策 | 出处 |
|---|---|---|
| 1 | FB 最终要「多表 + 户类型」，**但对齐 TT 是一大步**，本轮**只做 A**（单表 + 表头映射），A 验收后再开 B | 用户选「先 A，A 验收后再开 B」 |
| 2 | FB 表（账户管理分配）第 1 行就是那 **17 个干净中文名**（无括号提示；第一列是「日期」不是「时间」） | 用户答「就是那 17 个干净中文名」 |
| 3 | 走**方案 1**：字段目录按平台归一，FB 的目录**从 `COLUMN_SPEC["fb"]` 推导**，不手抄 | 用户选「方案 1（推荐）」 |
| 4 | 四个实现判断全按推荐：函数**显式要求 `platform` 无默认值** / 保留 `spec_column_map` 作回归锚 / 前端**不抽新组件** / 定位键字母兜底**当作要修的雷** | 用户答「全部认可」 |

## 三、现状事实（2026-10-11 实测）

- `COLUMN_SPEC["fb"]` 元组形状是 `(列字母, 表头, 字段名, 可写, 可读)`——
  **它已经能表达 FB 全部三种方向**：`操作人 (True, False)` 只写、`资产UID (True, False)`
  只写且是定位键、`接户运营 (False, True)` 只读回，其余 `(True, True)`。
  （TT 的 `TT_FIELD_CATALOG` 只有 `"rw"` / `"r"` 两档，因为它只服务 TT。）
- 表头原文与用户口述、与设计文档 §四**三方逐字一致**，可放心当别名源。
- 命名空间提醒：文档 §四的「系统字段」栏写的是 DB 列名（`channel_id`/`status_id`/`owner_id`），
  而 col_map 里用的是解析前的名字（`channel_name`/`status_name`/`owner_name`）。
  **本次以代码为准**（`COLUMN_SPEC["fb"]` 的第 3 项），并在 §4.1 的推导表里逐项列出。
- FB 侧目前**没有**：多表配置、`columns` 覆盖、表头解析、未采集上报、按表按钮、
  `fb_accounts.account_type`。
- 既有的表头映射层**全部写死 tt**：`resolve_column_map` 用模块级的 `_TT_ALIAS_TO_FIELD`；
  `field_spec` 里 `if platform == "tt"` 分叉；`tt_field_catalog()` 只出 TT；
  `resolve_table_col_map` 里 `if platform != "tt": return spec_column_map(...)`；
  `/sheet-headers` 直接 `if platform != "tt": return 400`。

## 四、技术方案

### 4.1 字段目录：一份数据，两种来源

```python
FIELD_CATALOG = {"tt": TT_FIELD_CATALOG, "fb": _derive_catalog("fb")}
```

`_derive_catalog(platform)` 从 `COLUMN_SPEC[platform]` 逐项推导
（目录条目形状与 TT 的 6 元组**完全一致**：`(字段key, 中文名, 别名元组, 方向, 是否定位键, 空值跳过)`）：

| `COLUMN_SPEC` 元组位 | 推导成目录的哪一位 | 例（A 列） |
|---|---|---|
| 第 2 项（表头） | label（下拉显示）+ **别名元组 = `(表头,)`** | 「日期」 |
| 第 3 项（字段名） | key | `acquired_date` |
| 第 4 项 可写 / 第 5 项 可读 | 方向：`(T,T)→"rw"`、`(T,F)→"w"`、`(F,T)→"r"` | `"rw"` |
| 字段名 == `ACCOUNT_KEY_FIELD[platform]` | 是否定位键 | `False` |
| — | 空值跳过回写**恒 False**（`COLUMN_SPEC` 没有这个语义） | `False` |

FB 的推导结果（17 项，**实现时按此逐项核对**）：

| 列 | key | label / 别名 | 方向 | 定位键 |
|---|---|---|---|---|
| A | `acquired_date` | 日期 | rw | |
| B | `operator` | 操作人 | **w（只写）** | |
| C | `name` | 账户名称 | rw | |
| D | `account_id` | 资产UID | **w（只写）** | **✓** |
| E | `channel_name` | 所属渠道 | rw | |
| F | `asset_type_name` | 资产类型 | rw | |
| G | `unit_price` | 单价 | rw | |
| H | `inbound_qty` | 入库 | rw | |
| I | `acceptor` | 接户运营 | **r（只读回）** | |
| J | `owner_name` | 在用运营 | rw | |
| K | `outbound_date` | 出库时间 | rw | |
| L | `outbound_qty` | 出库 | rw | |
| M | `timezone` | 时区 | rw | |
| N | `consumption` | 消耗 | rw | |
| O | `status_name` | 状态 | rw | |
| P | `primary_bm_name` | 位置 | rw | |
| Q | `remark` | 产品信息 | rw | |

**「w」是新引入的方向。** 现有取值只有 `"rw"`、`"r"`，以及**哨兵条目**用的 `"ignore"`
（`TT_FIELD_CATALOG` 里那条空串字段key「位置」）—— `"w"` 是**数据字段的第三种方向**。
语义：系统写、绝不读回（FB 的 `操作人` 是冻结字段；`资产UID` 是定位键，本来就不读回）。
它只影响两处：
① `field_spec` 里 `readable=False`（这正是今天 `COLUMN_SPEC` 推导出来的值，**值不变**）；
② 前端下拉的标记文案（现在只有「必选 / 只读回」，加第三种「只写」）。

**别名表**：现在只有模块级的一份 `_TT_ALIAS_TO_FIELD`，改成按平台预计算两份
（`_ALIAS_TO_FIELD = {p: {别名: 字段key} for p in FIELD_CATALOG}`）。
同名字段只取最先出现的那个别名条目（与现状同口径）。

**本次不加任何补充别名。** 17 个表头已确认唯一且齐备，`COLUMN_SPEC` 表达不了的两件事
（同一字段的第二种叫法、「认识但刻意不采集」的哨兵）FB 都不需要。将来真需要时，
在 `_derive_catalog` 调用处多传一层覆盖表即可（一行），**现在不预先搭这个结构**。

**追加一条纪律**：`COLUMN_SPEC` 的表头这一栏从今天起**是运行依据，不是注释**。
以后改表头名 = 改别名 = 影响自动识别，必须在 PR 里显式说明。

### 4.2 平台化：函数的签名变化

| 函数 | 现在 | 改成 |
|---|---|---|
| `resolve_column_map` | `(headers, overrides)` | `(headers, overrides, platform)` |
| `describe_header_columns` | `(headers, overrides, col_map, unmatched)` | `+ platform`（末位） |
| `tt_field_catalog()` | `()` | `field_catalog(platform)` |
| `_TT_CATALOG_FIELDS` | 模块常量 | `_catalog_fields(platform)`（= `set(field_spec(platform))`） |
| `_TT_ALIAS_TO_FIELD` | 模块常量 | `_ALIAS_TO_FIELD[platform]` |
| `field_spec(platform)` | `tt` 走目录 / 其余走 `COLUMN_SPEC` | `gg` 走 `COLUMN_SPEC`；`tt`/`fb` 走目录 |
| `spec_column_map(platform)` | 全部平台 | **不改**（见下） |

**为什么 `platform` 不给默认值**（决策 4）：给 `"tt"` 默认值能让 diff 小很多，
但漏传时**静默按 TT 处理**——正是「两份真相」的变体。代价是约 40 处既有测试调用要
机械加参数，收益是漏传会当场 `TypeError`。TT 的既有测试改完后**仍然全绿**，
本身就是「TT 行为未变」的证据（见 §六锚 3）。

**`spec_column_map` 保留、不改、不删**：生产路径里它只剩 gg 在用，但它定义了
「什么叫等价」——§六的两条锚都要拿它做右值。注释里写明「fb 的调用只在测试里」。

### 4.3 映射解析（无新逻辑）

`resolve_column_map` 的两轮（手工覆盖 → 别名自动匹配）、去重口径、空串哨兵、
同名表头只采集最左那列且后一个不报未采集 —— **全部逐字不动**，只把
「字段目录从哪来」换成按 `platform` 取。`describe_header_columns` 同理
（它内部那次 `resolve_column_map(headers, {})` 也要带上 platform）。

### 4.4 读路径

- `READ_RANGE["fb"]`：`"A:Q"` → **`"A:ZZ"`**（同 tt：表头映射后列数不定、
  「刻意不采集」的列也占位，固定 A:Q 会读漏右侧列）。
- 同步路由（`dashboard_sync`）里那段 `if platform == "tt":`（读表头 → 解析 → 校验定位键
  → 收未采集）改成 `if platform in ("tt", "fb"):`。`_account_type` 的注入**仍只给 tt**
  （FB 没有户类型，本轮不引入）。
- **定位键认不出 ⇒ 拒绝本次同步**，判据与 TT 同款（同一条 `if`，只是平台扩展到 fb）。
  理由：没有定位键，读出来的每一行都无法与系统账户对应，继续跑只会产出垃圾差异。
  ⚠️ **错误文案要按平台取列名**：现在有两处写死「账户ID」
  （`huguan_dashboard.py:386` 的写表侧、`huguan_dashboard_routes.py:244` 的同步侧），
  FB 必须显示「**资产UID**」——户管是拿这句去自己的表里找那一列的，
  说错名字他就找不到。抽一句平台无关的取词（`KEY_COL_LABEL = {"gg": "账户ID", "tt": "账户ID", "fb": "资产UID"}`）
  或等价做法。
- 未采集列照旧进 `diff["unmatched_columns"]`，前端按表分组显示。
- **gg 一个字不动**（`col_map=None` ⇒ 走 `spec_column_map`）。

### 4.5 写路径：三处硬编码列字母

`cells_for_row` / `parse_row` 本来就接 `col_map`，**逻辑不用改**。必须改的是三处
**绕过 col_map、直接写死字母**的地方（不改的话，表头一挪就写错列）：

| 位置 | 现在 | 改成 |
|---|---|---|
| `_fb_acceptor_cells` / `_fb_owner_transition` 的 cells 键 | 写死 `"I"` | col_map 里 `acceptor` 字段的列字母 |
| 归属回写的落点 | `OWNER_COL["fb"]` = `"J"` | `owner_role_col("fb", "owner", col_map)`（该函数**已支持** col_map，取不到返回 `None` = 一个字不碰） |
| `huguan_sheet_targets.py:183` 的角色列解析 | `owner_role_col(platform, role, cm if platform == "tt" else None)` —— **fb 落进 `None` 分支、拿固定字母** | 改成 `cm`（tt/fb 都按本表 col_map 取；fb 的 `role="channel"` 因没有通道列而返回 `None`，即一个字不碰 —— 与今天的 fb 行为一致） |
| `resolve_table_col_map` 的分叉 | `if platform != "tt": return spec_column_map(...)` | 只有 **gg** 走固定；tt/fb 读 `A1:ZZ1` 解析 |

> 这一处是自审时补上的：`owner_role_col` 的第三个参数决定了走 col_map 还是走固定字母表，
> 而 fb 现在被显式排除在外（`if platform == "tt" else None`）—— 表头一挪就会把运营名
> 写进错列。同文件 `:108-110` 已有一条「不用 `or spec_column_map` 兜底」的注释，
> 说明这个方向是对的，fb 只是当时还没纳入。

`resolve_table_col_map` 里的定位键校验也要按平台取名字
（`col_map.get("advertiser_id") or col_map.get(TT_KEY_FIELD)` → 按 `ACCOUNT_KEY_FIELD[platform]`
与解析结果命名空间两个名字查），生成写表器用的定位键列时同理
（`key_col_of_col_map` 已经同时认两个命名空间，确认它对 fb 也成立即可）。

> 写表器的「该表被两个户类型共用」等守卫是 B 阶段的事，本轮不碰。

### 4.6 配置结构

FB 配置从

```json
{ "spreadsheet_id": "...", "sheet_name": "账户管理分配" }
```

变成（`columns` **可选**，缺省 `{}`）：

```json
{ "spreadsheet_id": "...", "sheet_name": "账户管理分配",
  "columns": { "时区": "consumption" } }
```

- **无需迁移**：老配置读出来 `columns` 就是 `{}`，全走别名自动识别，行为与今天一致。
- `get_platform_tables("fb")` 开始带 `columns`（缺省 `{}`，与 tt 的归一做法一致）；
  **gg 仍不带**（载荷形状逐字节不变）。
- `tables[]`（多表）**仍然只有 tt 有**：POST 层继续对非 tt 拒绝，`get_platform_tables`
  的 fb 分支仍返回单元素列表。B 阶段再动。

### 4.7 校验与未采集上报

- POST 配置的 `columns` 白名单校验（现 `hd._TT_CATALOG_FIELDS`）改成按平台取
  `_catalog_fields(platform)`。其余规则逐字不动：空串合法（刻意不采集，且允许多列同指）、
  非字符串一律 400、同一字段被两列指定 ⇒ 400。
- `/sheet-headers`：`if platform != "tt"` → `platform not in ("tt", "fb")`
  （gg 仍 400）。归属门禁不变：表地址取用户自己的配置，`sheet_name` 必须是他配置里的那张。
- 配置 GET：`entry["tt_field_catalog"]` → **按平台**给 `f"{platform}_field_catalog"`
  （tt 的键名不变 ⇒ 零破坏；gg 不给这个键，载荷形状不变）。

### 4.8 定位键兜底（要修掉的雷）

`parse_row` 末尾现在是：

```python
key_col = cm.get(TT_KEY_FIELD) or cm.get(ACCOUNT_KEY_FIELD[platform]) or KEY_COL[platform]
```

最后那个 `or KEY_COL[platform]`（fb ⇒ `"D"`）在 col_map 缺定位键时会**静默用 D 列**。
路由的前置校验会让它不可达，但「不可达」是靠另一处代码维持的，属于隐式契约。
本次把它**显式化**：缺定位键就抛错（gg 走 `spec_column_map` 恒有定位键，抛不出来）。
配一条测试钉死「col_map 缺定位键时绝不静默落到 D 列」。

### 4.9 前端（FB 设置 → 户管看板卡片）

`HuguanDashboardCard.vue` 现在是「tt 走多表那一支 / 其余走单表 select」的二选一。
本次让 **fb 复用 tt 那一支模板**，对 fb 隐藏四样：

1. 「户类型名」输入框
2. 每行的「删除」按钮
3. 每行的「⬇️ 导入这张表 / ⬆️ 刷新回这张表」两个按钮
4. 「添加账户表」入口

隐藏之后，fb 的那一行恰好等于今天的「工作表名下拉 + 列映射区」——位置与 TT 完全一致。

其余改动：

- 挂载时 `if (HD_PLATFORM === 'tt')` 加 fb；fb 把扁平的 `sheet_name + columns`
  **展开成一条 `tables`** 供渲染，保存时再**折叠回扁平**（适配层就这一处）。
- 字段目录取 `conf[`${HD_PLATFORM}_field_catalog`]`。
- 「未采集列」区块的 `v-if` 加 fb。
- 列映射下拉的选项标记加第三种「只写」（数据来自后端的 `direction`）。
- `hdConfigured` / 两个平台级按钮文案 / `hdTablesTip` 等对 fb 的取值**保持今天的样子**
  （fb 仍只有一张表，沿用「刷新到看板 / 从表同步到系统」文案，不出现"全部"字样）。

**不抽新组件**（决策 4）：复用既有模板 + 几处 `v-if`。因此本次不属于
「新增 UI」（新页面 / 新组件 / 新交互），**不触发 `/frontend-design`**。
若审查时判定它算新增 UI，再补一次视觉设计。

## 五、非目标

- **FB 多表 / 户类型**（`fb_accounts.account_type` 列 + 存量迁移、多表配置、
  按表导入·刷新两个按钮、FB 账户页户类型筛选按钮）—— **子项目 B**，另立 spec。
- FB 的字典项自动补建（渠道 / 资产类型 / 状态）—— 用户未提，单独评估。
- `tables[]` 结构对 FB 开放。
- **GG 的任何行为改动**（`COLUMN_SPEC["gg"]`、`READ_RANGE["gg"]="A:N"`、
  `col_map=None` 路径、配置载荷形状）—— 逐字节不变，是硬约束。
- **TT 的行为改动**——只有函数签名/改名的机械改动，行为逐字节不变。

## 六、测试

**三条锚（这就是"行为不变"的证据，不靠读 diff 判断）：**

1. `resolve_column_map(FB表头行, {}, "fb") == spec_column_map("fb")` ——
   FB 表头正常时**逐字节等价**。
2. `field_spec("fb")` 与「从 `COLUMN_SPEC["fb"]` 推导」的结果**逐字段相同**，
   尤其 `operator` 的 `readable=False`、`account_id` 的 `key=True`。
3. **GG 既有测试全绿 + TT 既有测试全绿**（改签名后仍全绿 = 两平台行为未变）。

**新增用例（落点 `py/tests/test_fb_huguan_dashboard.py` 与 `test_huguan_dashboard.py`）：**

- FB 表头**换序** ⇒ 映射跟着走，不串列（读出的字段与换序前逐个相同）
- FB 表头**插列**（中间插一列不认识的）⇒ 该列进未采集、其余列不受影响
- FB 表头**改名**（如「时区」→「时区2」）⇒ 原列进未采集，不同步该字段
- FB 缺「资产UID」列 ⇒ **拒绝同步**（不是静默用 D 列），且错误文案里出现的是
  **「资产UID」**而不是「账户ID」（户管拿这句去表里找列）
- `parse_row` 在 col_map 缺定位键时**抛错**，绝不落 `KEY_COL["fb"]`
- 手工覆盖生效：`{"时区": "consumption"}` ⇒ 时区列的值进 `consumption`
- 覆盖值为空串 ⇒ 该列既不映射也不上报（同 TT）
- 同名表头 ⇒ 只采集最左那列，后一个不报未采集
- `_fb_acceptor_cells` 在「接户运营」列**不在 I 列**时，仍写对列
- 归属回写落点在「在用运营」列**不在 J 列**时仍写对列
- `/sheet-headers`：`platform=fb` 可用；`platform=gg` 仍 400
- 配置 POST：fb 的 `columns` 白名单（未知字段 400；gg 的 columns 仍被拒）
- 配置 GET：fb 载荷带 `fb_field_catalog`；**gg 的载荷形状不变**（无该键）

**前端**：`frontend/tests/columnMappingLogic.test.mjs` 若有平台相关分支则补 fb 覆盖；
`npm test` 全绿 + `vite build` 通过。

## 七、影响面清单

**后端**

| 文件 | 改动 |
|---|---|
| `py/huguan_dashboard.py` | `FIELD_CATALOG` / `_derive_catalog` / `_ALIAS_TO_FIELD`；`resolve_column_map` `+platform`；`describe_header_columns` `+platform`；`field_spec` 分叉改写；`field_catalog(platform)`（原 `tt_field_catalog`）；`_catalog_fields(platform)`；`READ_RANGE["fb"]="A:ZZ"`；`resolve_table_col_map` 分叉；`parse_row` 去掉字母兜底；`_fb_acceptor_cells`/`_fb_owner_transition` 接 col_map |
| `py/routes/huguan_dashboard_routes.py` | 同步路由 `platform in ("tt","fb")`；`/sheet-headers` 放行 fb；配置 GET 的 `{platform}_field_catalog`；POST 白名单按平台；fb 的 push 仍拒 `sheet_name`（沿用现状） |
| `py/routes/huguan_sheet_targets.py` | `:183` 的 `owner_role_col(..., cm if platform == "tt" else None)` 改成无条件传 `cm`（见 §4.5 第三行）；`:85` 的 `resolve_table_col_map` 调用跟着签名走 |
| `py/tests/test_huguan_dashboard.py` | 约 27 处 `resolve_column_map` + 4 处 `field_spec` + 6 处 `spec_column_map` + 6 处 `tt_field_catalog` 加参数/改名 —— **机械改动，断言不变** |
| `py/tests/test_huguan_sheet_write.py` | 9 处 `resolve_table_col_map` + 2 处 `spec_column_map` + 1 处 `resolve_column_map` 同上 |
| `py/tests/test_huguan_undo.py` | 1 处 `resolve_column_map` + 2 处 `resolve_table_col_map` 同上 |
| `py/tests/test_fb_huguan_dashboard.py` | **新增** FB 表头映射用例（§六） |

**前端**

| 文件 | 改动 |
|---|---|
| `frontend/src/components/HuguanDashboardCard.vue` | fb 复用 tt 模板 + 四处隐藏；适配层展开/折叠；目录键按平台取；未采集区块放行 fb；下拉加「只写」标记 |
| `frontend/src/utils/columnMapping.mjs` | 预计不改（已是纯换算）；若需新增平台分支则补 |
| `frontend/tests/columnMappingLogic.test.mjs` | 补齐新增分支的用例 |
| `frontend/dist/**` | `npm run build` 产物（**由用户执行构建**） |

## 八、未决项

1. **FB 的「操作人」列出现在列映射下拉里是否合适**。方案：出现在，标「只写」——
   好处是户管改了这一列的标题也能重新指派。若你不希望它可指派，实现时从
   `field_catalog("fb")` 里过滤掉即可（一行）。
2. **`COLUMN_SPEC["fb"]` 与设计文档 §四「系统字段」栏的用词不一致**
   （文档 `channel_id` / 代码 `channel_name`）。本次以代码为准，**不改文档**；
   若你要文档也对齐，我另开一笔。
3. **构建与重启由谁做**：前端改动要 `npm run build` 才生效，后端要重启 Flask。
   按既有约定这两步都由你执行。
