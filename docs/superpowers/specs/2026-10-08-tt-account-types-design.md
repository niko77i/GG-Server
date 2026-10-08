# TT 户类型（加白户 / 企业户）与多账户表（设计）

> 2026-10-08。用户原话：「现在tt户管 访问的账户表不止一个，需要新增。又因为表多了，
> 所以账户在系统保存的时得增加一个字段用于区分是什么表的字段，这样同步到账户表时候
> 才不会填错表，现在库里的tt账户，全部都是加白户，后面还有企业户。展示的时候也需要
> 增加按钮，区分不同的账户，默认展示加白户。配置表还是在TT设置里面，现在只有一个
> sheet表的配置。而且我希望这里的配置改为sheet表的选择逻辑不变，但是对应的表名可以
> 自定义，这个自定义的表名用于保存为账户新增字段的户类型区分，也就是我前面说的直接
> 用这个来增加按钮。另外里设计为可以新增的，现在是加白户和企业户，不知道后续会不会
> 有。先把这个大板块做好在同步到fb和TT那边」

## 一、需求描述

TT 户管的看板目前**一个平台只能配一张表**（`config.huguan_dashboard_<uid>.tt`
= `{spreadsheet_id, sheet_name}`）。实际上户管手里有**多张账户表**：加白户总表、
企业户总表，各自装**所有投手**的对应类型账户，同属一个 Google 表格（spreadsheet）
下的不同 worksheet。

需求：

1. 户管看板的 TT 配置从"一张表"扩成"**一个可新增的列表**"，每条 = 自定义表名 +
   一个 worksheet。表名即**户类型**，未来可再加第三种。
2. `tt_accounts` 增加**户类型**字段：读表时按所属表打标，回写时按标路由到对应
   worksheet —— 否则多表之后必然写错表。
3. 现有 TT 账户**全部是加白户**。
4. 账户列表页加**户类型按钮**，**默认展示加白户**。
5. 顺带（用户同批提出）：户管也要能配 **充值表 / 回收户清单**，并能操作充值记录与
   回收清单。后续确认「与投手同一张表，给户管全局写权限」。
6. 本次**只做 TT**，但配置结构要可推广到 GG / FB。

### 澄清结论（2026-10-08 逐条确认）

- 多出来的"表" = **同一 spreadsheet 下的多个 worksheet**，不是多个 spreadsheet。
- 户管看板指 `HuguanDashboardCard platform="tt"`，它**正挂在 TT 设置页**
  （`frontend/src/views/tt/TtSettingsPanel.vue:166`）——即用户说的"配置表还是在
  TT 设置里面"。
- 投手**不碰**这两张总表：投手只同步自己的看板、充值表、回收户清单。

## 二、已确认的决策

| # | 决策 | 出处 |
|---|---|---|
| 1 | 多表形态 = 同一 spreadsheet 下多个 worksheet | 用户选项 |
| 2 | 户类型清单随**户管看板配置私有**存放（方案甲） | 用户选项 |
| 3 | 手工建户 / 批量导入都加「户类型」下拉，**默认加白户** | 用户选项 |
| 4 | 按钮 = **多选**（可同时看多个），默认只勾加白户 | 用户选项 |
| 5 | 已存在账户的类型：**总表同步为准** + 人工可改 | 用户选项 |
| 6 | 范围 = **只做 TT**，配置结构做成可推广（GG/FB 行为不变） | 用户选项 |
| 7 | 类型名字即标识（字符串落库），改名时级联回填 | 本文 §5 |
| 8 | 投手看板同步：**同步弹窗里加「户类型」下拉**，作用于本次**新建**的账户，已存在的不动 | 用户选项 |
| 9 | 户管的「充值表 / 回收户清单」**与投手同一张表**：给户管**全局写权限**并放开 UI 隐藏 | 用户选项 |

## 三、现存事实（2026-10-08 实测代码）

| 事实 | 位置 |
|---|---|
| `tt_accounts` 无任何"户类型"字段；`advertiser_id` 唯一、`owner_id` 隔离 | `py/database.py:1002-1025` |
| 户管看板配置：`config.huguan_dashboard_<uid> = {gg:{...}, tt:{...}, fb:{...}}`，每平台一个 `{spreadsheet_id, sheet_name}` | `py/huguan_dashboard.py:180-236` |
| 配置读写端点 | `py/routes/huguan_dashboard_routes.py:24-65` |
| 户管同步：读 `conf["sheet_name"]` **一张表** → `parse_row` → `build_diff` → `apply_diff` | `py/routes/huguan_dashboard_routes.py:68-190` |
| TT 列规格：C=账户ID、G=接户运营、L=换绑情况、M=产品信息；读 `A:M` | `py/huguan_dashboard.py:48-61,88` |
| 合成字段惯例：`_is_dead` / `_pending_status` / `_primary_bm_name` 不是数据库列，由 `_collect_updates` 产出、`apply_diff` 拼 SQL 前显式 `pop`；`_dead_flag` / `_owner_channel` 是另一类，由 `parse_row` 产出、只供 `build_diff` 判定 | `py/huguan_dashboard.py:617-673`、`:1014-1022`、`:928-934` |
| 回写：`collect_rows_for_push` → `push_rows` → `update_rows_by_account_id(conf["sheet_name"])`，**只有一个 sheet** | `py/huguan_dashboard.py:1330-1527` |
| 撤回快照：`snapshot_push_targets` 返回**单表**快照 `{spreadsheet_id, sheet_name, cells}` | `py/huguan_dashboard.py:1446-1484` |
| 投手看板通路（与总表**两条不同的路**）：`tags.tt_sheet_id` + `tt_sheet_mappings_<uid>.my_dashboard` | `py/huguan_dashboard.py:1365-1444,1748` |
| 投手同步端点 + 门禁「A 列运营 == 当前账号」 | `py/routes/tt_accounts_routes.py:1216-1257` |
| 账户列表 + `status_counts` 口径 | `py/routes/tt_accounts_routes.py:202-320` |
| 前端状态按钮组（计数 + 高亮 + toggle） | `frontend/src/views/tt/TtAccountPanel.vue:29-32` |
| 列注册表 `TT_ADS_COLUMNS` | `frontend/src/constants/accountColumns.js:32-46` |
| 批量导入是"粘贴 ID → 批次公共表单（bc/时区/代理/名称前缀）" | `frontend/src/components/tt/TtAccountBatchImportModal.vue:6-175` |
| `HuguanDashboardCard` 是 **GG/TT/FB 共用组件** | 用于 `SettingsPanel.vue:110`、`TtSettingsPanel.vue:166`、`FbSettingsPanel.vue:146` |
| TT 的 `recharge` / `recycle` 映射是**全局 tags、仅 admin 可写** | `py/routes/tt_routes.py:1264-1296` |
| TT 数据导出/导入**不含** `tt_accounts`（本次不受影响，已核对） | `py/routes/tt_routes.py:1301-1330` |

## 四、技术方案

### 4.1 数据模型

`tt_accounts` 新增一列：

```sql
-- 走 _add_column_if_missing（py/database.py:109），与 owner_change_note 同处迁移区
account_type TEXT DEFAULT ''
```

- **存量回填**：`account_type` 为空的行一次性填成「加白户」。**只在列刚被新增的那一次
  执行** —— 否则以后户管改名 / 手工清值会被反复覆盖。
  ⚠️ 现 `_add_column_if_missing`（`py/database.py:109`）**不返回是否真的新增了**，
  需让它返回 `bool`（或加一个同形的返回版函数）。这是本节唯一必须改的既有函数。
- **存类型名字符串，不存 id**：查库直接可读、无需 join。代价是**改名必须级联**
  （见 §5）。
- **不加新索引**：TT 账户量级下 `account_type` 作为附加 `AND` 条件足够；确有需要再加。

### 4.2 配置结构（可推广）

`config.huguan_dashboard_<uid>`：

```json
{
  "gg": { "spreadsheet_id": "...", "sheet_name": "..." },
  "fb": { "spreadsheet_id": "...", "sheet_name": "..." },
  "tt": {
    "spreadsheet_id": "...",
    "tables": [
      { "name": "加白户", "sheet_name": "总户-加白" },
      { "name": "企业户", "sheet_name": "总户-企业" }
    ]
  }
}
```

**`gg` / `fb` 保持旧格式，一个字节不改。**

新增统一出口 `get_platform_tables(db, user_id, platform) -> [{"name", "sheet_name"}]`：

| 平台 | 返回 |
|---|---|
| tt 且有 `tables` | 原样返回 |
| tt 只有旧的 `sheet_name`（存量） | `[{"name": "加白户", "sheet_name": 旧值}]`，**不立刻改写磁盘**，下次保存时才写成新格式 |
| gg / fb | `[{"name": "", "sheet_name": conf["sheet_name"]}]` —— 与现状**行为等价** |

`save_config` 增加关键字参数：

```python
def save_config(db, user_id, platform, spreadsheet_id, sheet_name, *, tables=None) -> None
```

`tables` 非 `None` 时写新格式（仅 tt 允许）；为 `None` 时逐字节保持现有行为。
`get_platform_config` **签名与返回值不变**（`{spreadsheet_id, sheet_name}`），
继续服务 gg/fb 与既有测试。

**校验（400）**：`tables` 非空；每条 `name` 去空白后非空；`name` **互不重复**；
`sheet_name` 非空；`sheet_name` 互不重复（同一 worksheet 挂两个类型会让回写路由
产生歧义，同样必须拦）。类型名与工作表名均 `strip()` 后存储。

### 4.3 同步（表 → 系统）

`POST /api/huguan/dashboard/sync`，`platform=tt`：

1. 取 `get_platform_tables`，**按配置顺序逐张表各读一次** `READ_RANGE["tt"]`（`A:M`）。
2. 每张表的 `parse_row` 结果由**路由**打上合成字段 `"_account_type" = <该表 name>`
   （复用 `_is_dead` / `_primary_bm_name` 的既有惯例，见下方传递链）。
3. **所有表的行合并成一个列表**再进 `build_diff` —— 跨表去重、冲突检测、归属变更
   全部沿用现有逻辑，不另写一套。
4. 类型改写（决策 5）：
   - 新建 → 写入该行所属表的 name；
   - 已存在且 `account_type != 该行所属表 name` → 改写成 name。

#### `_account_type` 的传递链（严格照抄合成键惯例）

`account_type` **不是表里的列**，所以它必须走 `_is_dead` / `_primary_bm_name` 那套
合成键机制，不能混进 `_PLAIN_TEXT_FIELDS["tt"]`：

| 环节 | 位置 | 动作 |
|---|---|---|
| ① 注入 | 路由读表后 | 给每行的 parsed dict 塞 `p["_account_type"] = <表 name>` |
| ② 收集 | `_collect_updates`（`:617`） | `if platform == "tt": out["_account_type"] = _conf_text(p.get("_account_type"))` |
| ③ 建/改分流 | `build_diff`（`:467`） | create 进 `db_values`；update 进 `fields`，**且仅在值真的变了时**才放（比照 `_same_as_existing`）—— 否则每行都会被报成"将更新" |
| ④ 落库 | `apply_diff`（`:842`） | create / update 两条分支各在拼 SQL **之前** `pop("_account_type")`，仅 `platform == "tt"` 时用它写 `account_type` 列 |

- ③ 的"仅在变了才放"与 ④ 的"拼 SQL 前 pop"是硬要求：update 分支的
  `sets = [f"{k}=?" for k in fields]` 会**无条件**把 `fields` 的每个键拼进 SQL，
  漏 pop 就是 `UPDATE tt_accounts SET _account_type=?` 直接报错。
- **不放进 `_PLAIN_TEXT_FIELDS["tt"]`**：那个集合参与"文本列空着＝清空系统该列"的
  口径（`_blank_columns`，`:675`），而 `_account_type` 永远非空、语义也不同。
- gg/fb 的 parsed 行里根本没这个键 → 两条路径一行不改。

#### ⚠️ 行号不再唯一（必须处理，否则是本设计最大的坑）

现有 diff / warning / errors 里的 `row` **就是工作表行号**，前端也按它报"第 N 行"。
多表之后两张表的"第 5 行"会撞。因此：

- `build_diff` 产出的每一项（`to_create` / `to_update` / `owner_changes` / `to_skip` /
  `warnings`）**新增 `sheet` 字段**（该行所属表名）；
- 前端同步报告（`TtAccountSyncModal.vue`）**按表分组展示**，行号前带表名；
- `apply_diff` 的 `errors` 里报行号时同样带表名。

#### 跨表重复

同一账户同时出现在两张总表 → 沿用现有"**首次出现生效 + warning**"规则，
即**以配置里排在前面的那张表为准**（默认加白户在前）。warning 文案必须带**两张表名**，
否则户管不知道去哪张表删行。

### 4.4 回写（系统 → 表）

- `collect_rows_for_push`（`:1330`）：查询里带上 `a.account_type`，产出每个 row 带
  `account_type`。
- `push_rows`（`:1492`）：**按 `account_type` 分组**，每组经 `get_platform_tables`
  查得对应 `sheet_name`，分别调 `update_rows_by_account_id`。
  - gg / fb：只有一组（name 为空），等价现状。
- **类型在配置里查不到对应工作表（被删 / 改名未同步）→ 跳过该组 + 记 warning，
  绝不退回写第一张表** —— 那正是用户要消除的"填错表"。
  （`push_rows` 在后台线程跑、没有回头路，所以这条 warning **只能落日志**，
  与现有"回写失败只记日志"同口径；这也是它必须"宁可不写"的原因。）
- `snapshot_push_targets`（`:1446`）返回值从"单表快照"改成**每张表一份快照的列表**；
  `push_undo_cells`（`:1486`）相应迭代，`undo_push`（`:1529`）逐表还原。
  快照结构在 payload 里加 `sheet_name`，撤回时按它回写。
- `writeback_owner_channel`（`:1801`）等**定向单列写点**：按该账户的 `account_type`
  解析工作表。解析不到 → 跳过 + 日志。
- **完全不受影响**：`push_remark_to_operator_dashboard`（`:1748`）与
  `read_operator_remark_map`（`:1399`）走的是**投手看板**，与总户表是两条通路。

### 4.5 列表与统计

`GET /api/tt/accounts/list`（`py/routes/tt_accounts_routes.py:202`）：

- 新增查询参数 `account_types`，取**重复参数**（`?account_types=A&account_types=B`，
  即 `request.args.getlist`）。**不用逗号分隔** —— 自己起的类型名里完全可能有逗号，
  用逗号切会把一个名字劈成两个、静默变成"筛不到任何行"。逐项 `strip()`，忽略空项；
  最终列表为空 → 不加条件。
- 主 `where` 加 `a.account_type IN (...)`；`total` 与 `items` 同口径。
- 新增返回 `type_counts: {类型名: 数量}`，口径**与 `status_counts` 完全同底**
  （`sc_where2`：含 search / bc / agent / timezone / owner，**不含** status 与
  account_types 自身）——两个计数按钮组必须同底，否则会出现"两个按钮的数字加起来
  对不上总数"这类诡异感。
- 空值兜底：`COALESCE(NULLIF(a.account_type,''), ?)`，第二个参数绑
  `_default_account_type(db, uid)` 的返回值（§5），**不要把常量硬拼进 SQL** ——
  迁移后理论上不出现空值，这是防御性写法。

### 4.6 手工建户 / 批量导入

- `POST /api/tt/accounts/create`、`/batch-create`：接受 `account_type`。
  **服务端兜底**：缺失 / 空白 → 写默认类型（§5）。
- `PUT /api/tt/accounts/<aid>`：接受 `account_type`，可改（决策 5 的"人工可改"）。
- 前端：`TtAccountModal.vue` 加「户类型」下拉（默认加白户）；
  `TtAccountBatchImportModal.vue` 在**批次公共表单**（bc / 时区 / 代理 / 名称前缀那一块）
  加一个「户类型」下拉，作用于整批（该弹窗是"粘贴一堆 ID + 一套公共属性"，不是逐行编辑）。

### 4.7 前端

| 组件 | 改动 |
|---|---|
| `TtAccountPanel.vue` | 状态按钮组（`:29`）下面加「户类型」**多选**按钮组，同款写法（`:type` 高亮 + 点击 toggle + 计数） |
| `constants/accountColumns.js` | `TT_ADS_COLUMNS`（`:32`）加一列「户类型」，可在"📊 列显示"里隐藏 |
| `components/tt/TtAccountModal.vue` | 加「户类型」下拉 |
| `components/tt/TtAccountBatchImportModal.vue` | 批次公共表单加「户类型」下拉 |
| `components/HuguanDashboardCard.vue` | `platform === 'tt'` 时：表格 ID（**全平台共用**）+ 可新增列表，每行 `[类型名输入框] [工作表下拉] [删除]`，底部「＋ 新增户类型」 |
| `components/HuguanDashboardCard.vue` 的宿主页 | 随卡片一起（只传 platform，逻辑在卡片内） |
| `components/tt/TtAccountSyncModal.vue` | ①「户类型」下拉（决策 8，作用于本次新建的账户）；②报告按表分组，行号带表名 |
| `views/tt/TtSettingsPanel.vue` | 「📊 Google 表格配置」卡片对户管放开（`:121`），但按角色只渲染可写行（§4.9） |

> ⚠️ `HuguanDashboardCard` 是 **GG/TT/FB 共用组件**：新增分支必须只在 `platform === 'tt'`
> 时渲染，gg/fb 的 DOM 结构、事件与请求体保持原样。这是本次**最容易误伤**的地方。

**户类型按钮的口径**（三个细节都要定死，否则会出现"按钮上没有的类型"这类怪象）：

1. **候选集** = `type_counts` 的键（即库里实际存在的类型），**不是**配置清单 ——
   这样即使配置被清空，按钮也不会凭空消失。
2. **顺序** = 配置清单顺序优先，清单里没有的类型按首次出现顺序排在后面。
3. **计数为 0 的类型不生成按钮**（沿用 `availableStatuses` 的既有惯例）。
4. **默认勾选**：配置清单第一条（初始 = 加白户）；若它不在候选集里，则勾选候选集的
   第一个；候选集为空（一个新账户都没有）→ 不勾任何类型，也不加类型筛选条件。

配置读取接口 `GET /api/huguan/dashboard`（`huguan_dashboard_routes.py:24`）目前一次返回
三个平台。为不破坏 gg/fb 的响应形状，**tt 条目额外带 `tables`**，同时**保留
`sheet_name`**（= `tables[0].sheet_name`），老前端读到的仍是老形状。
即由**路由层**在 `get_platform_config` 的返回值上合并 `tables`，
`get_platform_config` 自身的签名与返回值维持 §4.2 的不变承诺。

### 4.8 投手看板同步（`sync-from-sheet`）—— 投手自己选类型

`POST /api/tt/accounts/sync-from-sheet`（`py/routes/tt_accounts_routes.py:1216`）读的是
**投手自己的看板**（`my_dashboard`），门禁「A 列运营 == 当前账号」，与 §4.3 的总表是
**两条不同的通路**，本次**不合并**。

**决策 8：投手在同步弹窗里自己选类型。**

- `TtAccountSyncModal.vue` 增加一个「户类型」下拉，取值来自 §4.7 的类型清单；
  默认选中清单第一条（初始 = 加白户）。
- 该下拉**作用于本次同步新建的账户**：`dry_run` 与确认两趟都要带上
  `account_type` 参数。
- **已存在的账户不动** `account_type` —— 这条通路不做"以表为准"改写；
  类型最终由户管从总表同步时按"总表为准"修正（决策 5）。
- 参数缺失 / 为空串 → 服务端退回默认类型（§5），保证落库值恒非空。
- 服务端**不做白名单校验**：类型名只要求 `strip()` 后非空。理由是类型清单本来就是
  用户自定义的，硬校验反而会在"户管刚改名、投手弹窗还是旧清单"的瞬间把同步打断；
  而且值一旦非法，只会变成一个待总表同步纠正的孤儿类型，不会写错表（回写路由按
  配置查表，查不到就跳过，见 §4.4）。

### 4.9 户管的「充值表 / 回收户清单」配置权限（决策 9）

**现状（2026-10-08 实测）**：TT 设置里那张「📊 Google 表格配置」卡片对户管是
`v-if="!authStore.isHuguan"` 直接隐藏的（`frontend/src/views/tt/TtSettingsPanel.vue:121`）；
后端 `tt_settings_save` 也只认 admin 写全局
（`py/routes/tt_routes.py:1286-1294`），非 admin 落到 else 分支**只存 `my_dashboard`**。

> ⚠️ 这是个**已存在的静默丢弃**：卡片的 key 过滤条件
> （`TtSettingsPanel.vue:328`）对 `isHuguan` 是放行的，卡片一旦显示，户管就能看见并
> 编辑 `accounts` / `recharge` / `recycle` 三行——但后端存的时候只留 `my_dashboard`。
> 用户填了一屏、点保存、提示"✅ 已保存"、实际什么都没存。**本次一并修掉**。

**改动**：

- 后端 `tt_settings_save` 分档：
  - admin / developer → 可写全局 `accounts` / `recharge` / `recycle`（现状不变）；
  - **户管 → 可写全局 `recharge` / `recycle` 两个 key**（不含 `accounts`，它是死配置，
    见 §7）；
  - 其余角色 → 只写自己私有的 `my_dashboard`（现状不变）。
- 前端卡片对户管放开显示：**去掉 `:121` 那个 `v-if="!authStore.isHuguan"`**，
  卡片改为所有人可见，再靠**逐行渲染范围**区分角色：
  - 户管看到 `充值表` / `回收户清单` 两行，可编辑可保存；
  - `accounts`（账户明细）与 `my_dashboard`（我的看板）对户管**不渲染**
    —— 注意 `visibleSheetKeys`（`:328`）现在的写法是
    `!c.adminOnly || isAdmin || isDeveloper || isHuguan`，对户管**放行了全部
    adminOnly 行**（这正是那个静默丢弃的由来），要改成**按角色的显式白名单**，
    而不是给 isHuguan 开后门；
  - `sheet_id` 对户管**只读**（`el-input :disabled`）—— 表格 ID 仍是全局的，
    户管只改 worksheet 名。保留「📋 读取工作表」按钮可用，否则下拉没有候选。

- **UI 渲染范围必须与后端可写白名单逐字对齐**，这是本次要修的那个 bug 的根因：
  "界面上能改"和"存得下去"必须是同一个集合。加任何新 key 时两边一起改。

**"能操作充值记录和回收清单"**：这两项是**现成功能**，户管的角色闸门本来就放行
（`tt_required` / `tt_write_required` 只按 `require_platform('tt')` 与 `reject_viewer()`
判定，`PLATFORM_SWITCH_ROLES` 含户管）。本次**不改**，但要**实测确认**户管在
TT 账户页确实能用「💰 充值」「批量充值」与死亡状态触发回收清单写入（见 §8）。
若实测发现有按钮因角色被隐藏，属于 bug 修复，单独处理，不扩大本设计范围。

## 五、默认类型与改名的语义

**默认类型解析顺序**（仅用于"新建账户时未指定类型"的兜底）：

1. 该用户自己的 `config.huguan_dashboard_<uid>.tt.tables[0].name`（若配过）；
2. 常量 `TT_DEFAULT_ACCOUNT_TYPE = "加白户"`。

**改名（户管把"加白户"改成"白户"）**：后端在同一事务里
`UPDATE tt_accounts SET account_type=新名 WHERE account_type=旧名`。
不做级联的话，改名会让**所有存量账户从按钮里凭空消失**（按钮清单来自实际数据）。

**已知残留风险（诚实记录）**：户管改名后，投手侧新建 / 投手看板同步新建的账户会
落到常量"加白户"，形成一个暂时无人对应的工作表之外的孤儿类型。窗口很小，且**会自愈**：
户管下次从总表同步时按"总表为准"把类型改写回来。若将来这成为实际问题，把类型清单
提升为全局（`tags.tt_account_types`）即可根除 —— §4.2 的结构已为此预留。

**删除类型**：不清理已用该类型的账户（保留原值）。按钮清单来自实际数据，所以该类型
仍会显示、仍可筛选；只是**回写时查不到工作表 → 跳过 + warning**（§4.4）。

## 六、权限

- 户管看板配置：沿用 `@huguan_required`（`py/routes/huguan_dashboard_routes.py:25`），
  **不新增权限面** —— 这是选方案甲的主要原因。
- **新增一处权限变更**（§4.9，决策 9）：`POST /api/tt/settings` 的全局写白名单
  从「仅 admin/developer」扩到「admin/developer + **户管可写 `recharge` / `recycle`**」。
  改的是**写权限的档位划分**，不是加新端点。`accounts` 与 `sheet_id` 仍仅 admin。
  ⚠️ 改这段时必须同时改前端渲染范围（`TtSettingsPanel.vue`），否则又造出
  "界面上能改、存不下去"的静默丢弃（§4.9 的根因）。
- 账户侧的类型筛选 / 显示：沿用 `@tt_required`；写接口沿用 `@tt_write_required`。
  ⚠️ 勿用 `require_platform` 做角色收窄（`PLATFORM_SWITCH_ROLES` 含户管，见 AGENTS.md:355）。
- 归属隔离不变：非跨用户角色只看 `owner_id = 自己`。

## 七、非目标（本次不做）

- 不动 GG / FB 的配置、DOM、后端路径（只让 `get_platform_tables` 对它们返回单元素列表）。
- 不动投手看板通路（`tags.tt_sheet_id` + `my_dashboard`）与 `push_remark_to_operator_dashboard`。
- 不动 `tt_recharge_records` 表结构、回收户清单的**写入逻辑**（只改配置写入权限，§4.9）；
  不动 TT 设置里 `accounts`「账户明细」这个 key（至今**无人读**，本次也不清理）。
- 不做：类型拖拽排序 / 批量改类型 / 按类型分组的统计卡片 / 一个 spreadsheet 之外的
  多表格（每张表各自一个 spreadsheet ID）。
- 不做 `tt_accounts.account_type` 的导出导入（TT 导出本就不含账户表，已核对）。

## 八、测试

| 用例 | 断言 |
|---|---|
| 配置：旧格式 → 多表 | 存量 `tt:{spreadsheet_id, sheet_name}` 经 `get_platform_tables` 得单条 `加白户`；磁盘内容**未被改写** |
| 配置：gg/fb 不变 | `get_platform_tables('gg')` 返回单元素；`get_platform_config` 返回值逐字段不变 |
| 配置校验 | 空名 / 重名 / 空工作表名 / 工作表重名 → 400 |
| 迁移 | 新增列后存量行 `account_type='加白户'`；**再跑一次迁移不会覆盖**已被改过的值 |
| 多表同步·新建 | 两张表各建账户，类型分别落对 |
| 多表同步·改写 | 已存在账户（加白户）在企业户表里 → 改写成企业户 |
| 多表同步·跨表重复 | 同一账户在两表 → 只落一次（按配置顺序前者），warning 带两张表名 |
| 多表同步·行号 | diff / warnings 的每项带 `sheet`，两张表的第 5 行可区分 |
| 回写路由 | mock `update_rows_by_account_id`，断言每个 `sheet_name` 的入参只含该类型的账户 |
| 回写·类型失配 | 账户类型在配置里已删 → 该组被跳过（**断言没有**退化成写第一张表） |
| 撤回 | `snapshot_push_targets` 返回多表单快照；`undo_push` 逐表还原 |
| 建户默认 | `create` / `batch-create` 不带 `account_type` → 落默认类型 |
| 列表 | `account_types` 筛选口径与 `total` 一致；`type_counts` 与 `status_counts` 同底 |
| 改名级联 | 配置改名后存量账户 `account_type` 同步改名 |
| 投手同步选类型 | `sync-from-sheet` 带 `account_type` → 本次**新建**的账户落该类型；**已存在的账户类型不变** |
| 户管配置权限 | 户管 POST `/api/tt/settings` 带 `recharge`/`recycle` → 全局 tags 被写入；带 `accounts` → **不被写入**；带 `sheet_id` → **不被写入** |
| 户管配置可见性 | 户管在 TT 设置页能看到并保存 `充值表`/`回收户清单`；看不到 `accounts`/`my_dashboard`；`sheet_id` 只读 |
| 户管操作充值/回收 | 实测：户管在 TT 账户页能用「💰 充值」「批量充值」，死亡状态能触发回收清单写入 |

## 九、未决项

无。

首轮记下的两处未决均已裁定，正文已落在对应小节：

1. 投手看板同步建出的账户打什么类型 → **投手在同步弹窗里选**（决策 8，§4.8）。
2. 「户管也需要充值表和回收表」 → **与投手同一张表，给户管全局写权限**（决策 9，§4.9）。

## 十、影响面清单

**后端**
- `py/database.py` —— 加列 + 一次性回填；`_add_column_if_missing` 返回 `bool`
- `py/huguan_dashboard.py` —— `load_config`/`get_platform_config`/`save_config`（加
  `tables` 分支）、新增 `get_platform_tables` 与默认类型解析
  `_default_account_type(db, uid)`、`build_diff`（`sheet` 字段 + 类型改写 + 仅在变了
  才进 `fields`）、`_collect_updates`（产出 `_account_type`）、`apply_diff`（拼 SQL 前
  pop `_account_type`）、`collect_rows_for_push`（`_TT_ROW_SQL` 带 `a.account_type`）、
  `push_rows`（按类型分组）、`snapshot_push_targets`、`push_undo_cells`、`undo_push`、
  `writeback_owner_channel`
- `py/routes/huguan_dashboard_routes.py` —— 配置 GET（tt 条目合并 `tables`）/ POST
  （tt 多表 + 改名级联）、sync（逐表读 + 注入 `_account_type`）
- `py/routes/tt_accounts_routes.py` —— `list`（`account_types` 重复参数筛选 +
  `type_counts`）、`create` / `batch-create` / `update`（类型字段 + 默认类型兜底）、
  `sync-from-sheet`（接受 `account_type`，只作用于本次新建，见 §4.8）
- `py/routes/tt_routes.py` —— `tt_settings_save` 分档授权：**户管可写全局
  `recharge`/`recycle`**（§4.9）；`accounts` / `sheet_id` 仍仅 admin。
  `recharge` / `recycle` 两个 key 的**读取与消费路径一行不改**

**前端**
- `views/tt/TtAccountPanel.vue`（户类型多选按钮组）
- `views/tt/TtSettingsPanel.vue`（① 户管看板卡片宿主；② Google 表格配置卡片对户管放开
  + **按角色只渲染可写行**，`sheet_id` 对户管只读 —— §4.9）
- `components/HuguanDashboardCard.vue`（**共用组件，只加 tt 分支**）
- `components/tt/TtAccountModal.vue`、`TtAccountBatchImportModal.vue`（户类型下拉）
- `components/tt/TtAccountSyncModal.vue`（户类型下拉 + 报告按表分组）
- `constants/accountColumns.js`（新增「户类型」列）
- `api/tt.js`（`list` 的 `account_types` 重复参数、`syncFromSheet` 带上 `account_type`）
- `api/huguan.js`（配置体新增 `tables`）

**测试**
- `py/tests/` 下 TT 账户、户管看板、TT 路由三组既有测试文件的扩充 + 上表新增用例
