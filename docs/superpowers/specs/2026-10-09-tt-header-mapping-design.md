# TT 多账户表：按表头映射字段（设计）

> 2026-10-09。触发：用户发现「户管每加一张 sheet，表头都不一样」，而现有同步**按固定列字母**读，
> 列一错位就**静默串列**。用户选定**方案丙**（自动识别 + 认不出可手工覆盖）。

## 一、问题

现有 TT 同步把列位置写死在 `COLUMN_SPEC["tt"]`（`py/huguan_dashboard.py:48-61`）：
`A=入库时间 B=是否回收 C=账户ID D=BC E=国家 F=所属渠道 G=接户运营 H=时区 I=状态 J=消耗 K=位置 L=换绑情况 M=产品信息`。

`parse_row`（`:144`）与 `cells_for_row`（`:125`）都**按列字母**取/写，**不看表头**。

**实测的企业户表表头**：

```
日期  是否回收  账户ID  主体名称  账户名称  BC  国家  所属渠道  接户运营  时区  下户链接
```

对到现有列规格上：**只有前 3 列对得上，第 4 列起全部串位**，而且不报错、也不进日志——
BC 栏会写成"主体名称"的值。

**加白户表的表头与现有 `COLUMN_SPEC["tt"]` 完全一致**（用户确认），所以只有非标准表受影响。

## 二、已确认的决策（用户 2026-10-08 / 10-09 逐条裁定）

| # | 决策 |
|---|---|
| 1 | 走**方案丙**：按表头名**自动识别**（内置别名表）+ **认不出可手工覆盖**；只存覆盖，不存识别结果 |
| 2 | **账户ID 列认不出 → 直接拒同步**；其他列认不出 → 不阻断，但在差异报告里**逐条列出**「未采集的列」 |
| 3 | 新增系统字段：**主体名称**（`subject_name`）、**下户链接**（`landing_url`，非必填） |
| 4 | **账户名称**改用表里的值（不再拿账户 ID 当名字）；加白户表无此列 ⇒ 保持现状 |
| 5 | 存量 2188 条的账户名**不刷**（加白户表没有那一列，刷也无从刷起） |
| 6 | 三列（账户名称/主体名称/下户链接）**全部双向** |
| 7 | **`landing_url` 在库里为空时：回写跳过、不清表**（防误删户管填的链接） |
| 8 | **GG / FB 完全不动**：继续走现有固定 `COLUMN_SPEC` |

## 三、现状事实（2026-10-09 合并后实测）

| 事实 | 位置 |
|---|---|
| 按列字母的常量（9 个） | `py/huguan_dashboard.py:28, 85-91, 545, 559` |
| 按列字母的函数（7 个） | 同文件 `:125, 144, 581, 824, 835, 878` |
| **合并后新增的消费点**：写表定位行也按 `KEY_COL` | `py/routes/huguan_sheet_targets.py:90, 159, 296` |
| 归属列、读范围的其他消费点 | `py/routes/huguan_dashboard_routes.py:155, 244, 343, 580` |
| 表头映射的「选表」部分**已被对方下沉**到 target rebuild（重试路径也覆盖） | `py/routes/huguan_sheet_targets.py:49-72` |
| 读表入口（逐表读 + 注入 `_sheet`/`_account_type`） | `py/routes/huguan_dashboard_routes.py:139-167` |
| 配置结构 `config.huguan_dashboard_<uid>.tt.tables[]` | 2026-10-08 规格 §4.2 |
| 表级校验（类型名/工作表名非空且互不重复） | `py/routes/huguan_dashboard_routes.py:71-96` |

> ⚠️ **合并带来的主要变化**：表头映射不能只改 `parse_row` / `cells_for_row` 了 ——
> 写表路径重构成了 `huguan_sheet_targets.py`，它**也在按列字母定位行**。
> 那三处（`:90, :159, :296`）必须一起改成按该表的映射取定位列。

## 四、技术方案

### 4.1 系统字段目录（别名表）

把散落的固定列规格凝成一份**字段目录**（新增于 `py/huguan_dashboard.py`，仅 tt 使用）：

```python
# 每项：(系统字段key, 中文名, 别名元组, 方向, 是否定位键, 空值是否跳过回写)
TT_FIELD_CATALOG = [
    ("acquired_date",      "入库时间", ("入库时间", "日期"),                "rw", False, False),
    ("_dead_flag",         "是否回收", ("是否回收",),                       "rw", False, False),
    ("advertiser_id",      "账户ID",   ("账户ID",),                         "rw", True,  False),
    ("subject_name",       "主体名称", ("主体名称",),                       "rw", False, False),  # 新字段
    ("name",               "账户名称", ("账户名称",),                       "rw", False, False),
    ("bc_name",            "BC",       ("BC",),                             "rw", False, False),
    ("country",            "国家",     ("国家",),                           "rw", False, False),
    ("agent_name",         "所属渠道", ("所属渠道",),                       "rw", False, False),
    ("owner_name",         "接户运营", ("接户运营",),                       "rw", False, False),
    ("timezone",           "时区",     ("时区",),                           "rw", False, False),
    ("landing_url",        "下户链接", ("下户链接",),                       "rw", False, True),   # 新字段
    ("status_name",        "状态",     ("状态",),                           "rw", False, False),
    ("consumption",        "消耗",     ("消耗",),                           "rw", False, False),
    ("remark",             "产品信息", ("产品信息",),                       "rw", False, False),
    ("owner_change_note",  "换绑情况", ("换绑情况",),                       "r",  False, False),  # 只读回
    ("",                   "位置",     ("位置",),                           "ignore", False, False),  # 认识但刻意不采集
]
```

- **别名表是"自动识别"的全部依据**。目前只放**有实测依据**的别名（`日期` ↔ 入库时间，来自企业户表）。
  以后遇到新叫法，**加一行即可**——因为配置里只存"手工覆盖"，别名表一改，所有表自动受益。
- `方向` = `rw` 双向 / `r` 只读回（不回写）/ `ignore` 认识但刻意不采集。
- `空值是否跳过回写` = 见 §4.7，目前只有 `landing_url`。
- **`ignore` 那一档很重要**：加白户表的 K 列是「位置」，legacy `COLUMN_SPEC["tt"]` 里它的
  `field` 就是 `None`（系统刻意不采集，留给户管自己用）。若把它算作"未识别"，加白户表
  **每次同步都会报「1 列未采集 —— 位置」** —— 永久噪音会把「未采集」这个信号训练成被忽略。
  所以「认识但刻意不采集」与「不认识」必须分开：前者静默，后者上报。

### 4.2 映射解析

```python
def resolve_column_map(headers: list, overrides: dict) -> tuple[dict, list]:
    """headers: 第 1 行的原始值（按列序）。返回 (字段key → 列字母, 未采集的表头名列表)。

    优先级：手工覆盖 > 别名自动匹配 > 不采集。
    """
```

- 表头文本 `strip()` 后比较；空表头跳过。
- 同一张表里**多个表头匹配到同一个字段** ⇒ 取**最左**那个，其余记入 warnings（不静默）。
- 表头名在表内重复 ⇒ 用名字定位会有歧义，记 warning。

### 4.3 校验与「认不出就报出来」

**前提假设（沿用现状，不新增配置）**：**表头恒在第 1 行**。加白户表与企业户表都满足；不满足的表不在本次范围。

同步每张表时（`dashboard_sync` 的逐表读循环内）：

1. 读**第 1 行**（见 §4.4 的读法）→ `resolve_column_map`。
2. **定位键（账户ID）认不出 ⇒ `err("工作表「X」里找不到「账户ID」列，无法同步")`，整次同步拒绝**。
   （没有定位键就无法定位行，硬做只会串列。）
3. 其他未采集的列 ⇒ **不阻断**，但塞进差异报告的 `unmatched_columns`：
   `[{"sheet": "企业户", "headers": ["备注二", "下户链接2"]}, ...]`，前端**逐条显示**。
4. 走完全部表后，若还有未采集列，差异报告顶部给一条提示：
   「有 N 列未识别，未采集。可在 TT 设置里为这张表指定它们对应的字段。」

### 4.4 读方向

- **读范围**：`READ_RANGE["tt"]` 从写死 `A:M` 改成 **`A:ZZ`**（一次读取即含表头行与全部数据列；
  Sheets 会按实际列数截断，多读的列不产生额外数据）。**只读一次**，不额外读表头行。
  **`READ_RANGE` 的 `gg` / `fb` 两项不动**（它们继续走固定列规格）。
- `parse_row(values, platform)` → **`parse_row(values, platform, col_map)`**：
  按 `col_map[字段key] → 列字母 → 索引` 取值。`account_id` 的取法不变（仍走定位键那一列）。

> **gg / fb 怎么保持不动**：给它们合成一份**等价于现状**的 `col_map` ——
> 直接从既有 `COLUMN_SPEC[platform]` 生成 `{字段key: 列字母}` 即可（那段规格本来就是
> 「字段 ↔ 列字母」的表）。所有调用方（tt 用解析出来的、gg/fb 用合成的）走同一个签名，
> gg/fb 的取/写列因此与改动前**逐字节相同**。这样只有一个函数体，不需要按平台分叉。
- `_owner_sheet_from` / `owner_channel_cells` / `_blank_columns` 同理改为按 `col_map` 取列字母；
  **未采集的列一律不出现在这些产出里**（系统不认识它，就不该读写它）。

### 4.5 写方向

- `cells_for_row(row, platform)` → **`cells_for_row(row, platform, col_map)`**：
  只产出 `col_map` 里映射到**可写字段**（方向含 `w`）的列。
  **未采集的列一个字不碰**（如企业户表的「主体名称」若用户选择"不采集"，系统绝不覆盖它）。
- 定位行的 `key_col` 从 `col_map` 取（不再是 `KEY_COL["tt"]` 常量）。
  ⚠️ 消费点共 4 处：`py/routes/huguan_sheet_targets.py:90, 159, 296` 与
  `py/routes/huguan_dashboard_routes.py:343`（撤回快照的写入）。
- **撤回快照**（`snapshot_push_targets`）同样按 `col_map` 记「会写到的列」。

> **写侧怎么拿到 `col_map`**：写表在后台线程里跑，而 `col_map` 要读表头行才能解析。
> 所以每次写表前**多读一次表头行**（`A1:ZZ1`，只一行，代价可忽略 ——
> 何况 `update_rows_by_account_id` 本来就要整表读一次去定位行）。
> **gg/fb 不走这条**：它们用 `COLUMN_SPEC` 合成的 map，零额外读。

### 4.6 新字段与账户名称

- `tt_accounts` 新增 `subject_name TEXT DEFAULT ''`、`landing_url TEXT DEFAULT ''`（走 `_add_column_if_missing`）。
- `name` 的取法：`apply_diff` 现在硬编码 `src["name"] = item["account_id"]`（`py/huguan_dashboard.py`），
  改为**映射里 `name` 有值就用它**，否则回落到账户 ID（加白户表没有「账户名称」列 ⇒ 行为不变）。
- 存量 2188 条**不动**。

### 4.7 空值回写语义

- 通用口径不变：**读方向**「表里文本列空着 = 清空系统该列」；**写方向**照库里值写（含空串）。
- **例外**：字段目录里标了「空值跳过回写」的字段（目前只有 `landing_url`），
  写方向**库里为空则跳过该格**，不清表。
  - 理由：它是非必填的、由户管维护的链接，系统没填不代表要把它删掉。

### 4.8 配置结构

`config.huguan_dashboard_<uid>.tt.tables[i]` 增加一个键：

```json
{"name": "企业户", "sheet_name": "企业户",
 "columns": {"负责人": "owner_name", "备注二": "remark"}}
```

- **只存手工覆盖**（表头名 → 字段key），不存自动识别的结果。
- 校验（在现有 POST 校验基础上追加）：`columns` 是对象；值必须是字段目录里的合法 key；
  同一个字段 key **不得在一张表里被指定两次**（否则写回时两列打架）。
- 键（表头名）允许是当前表里不存在的名字（表头可能还没加），**但同步时会记 warning**。

### 4.9 前端（TT 设置 → 户管看板卡片 → 每张账户表）

每张账户表加一个可折叠的「列映射」区：

1. 一个「读取表头」按钮 → 调新端点读该表第 1 行 → 列出每一列。
2. 每列一行：`[表头原文] → [下拉：系统字段 / （不采集）]`，
   下拉默认值 = 自动识别结果（**虚显**，不算覆盖）。
3. 用户改过的行 → 存进 `tables[i].columns`。
4. 未识别的列在同步报告的提示里点进去，能直接跳到这个区。

**GG / FB 的户管看板卡片不出现这个区**（`HD_PLATFORM === 'tt'` 门控，与既有写法一致）。

### 4.10 分期（建议）

这个改动跨了「读、写、撤回、配置、前端」五处，建议**分两批**，每批都能独立交付：

| 批次 | 内容 | 交付后能达到什么 |
|---|---|---|
| **第一批：后端机制** | §4.1 字段目录 + §4.2 解析 + §4.3 校验/上报 + §4.4–4.7 读写两端 + §4.6 新字段 | 企业户表**零配置就能正确同步**；认不出的列**会在报告里报出来**（但还只能在库里手改 `columns` 来覆盖） |
| **第二批：前端配置 UI** | §4.8 的 `columns` POST 校验 + §4.9 列映射区 | 户管能在设置页里自己指派认不出的列 |

分批的理由：**第一批就解决了"静默串列"这个当前最痛的问题**（串列会写坏数据，而"认不出"只是漏读＋报告里看得见）；前端那套读表头 + 逐列下拉的 UI 工作量不小，可以晚一批。

## 五、非目标

- **GG / FB 完全不动**：继续走固定 `COLUMN_SPEC`；本设计只加 tt 分支。
- 不做「表头改名后自动跟随」：户管改了表头 → 变成"认不出" → **报出来** → 他重配。
- 不做「按内容推断列」（如靠值的形状猜哪列是账户ID）—— 只认表头名。
- 不动 `received_accounts`（GG 的「已接账户明细」）那个死配置。
- 不动回收户清单 / 充值表的读写路径（它们不按列规格读）。
- 不做列映射的版本迁移（现在没有已存的 `columns`，是全新键）。

## 六、测试

| 用例 | 断言 |
|---|---|
| 企业户表零配置可读 | 用实测表头（含「日期」）→ 自动识别出 `acquired_date`/`subject_name`/`name`/`landing_url` 等；`unmatched_columns` 为空 |
| 别名 | `日期` 与 `入库时间` 都解析到 `acquired_date` |
| 定位键缺失 | 表头里没有「账户ID」→ 整次同步**被拒**，错误文案含表名 |
| 未采集列上报 | 表头含一个不认识的列 → 不进 `to_create`/`to_update` 的任何字段，且出现在 `unmatched_columns` |
| 手工覆盖优先 | `columns={"负责人":"owner_name"}` → 该列按覆盖解析，别名表里没有的也叫得应 |
| 覆盖指定了重复字段 | POST `columns` 里同一个 key 出现两次 → 400 |
| 未采集列不回写 | 写方向产出的 `cells` **不含**该列字母 |
| 新建字段落库 | `subject_name` / `landing_url` 能从表同步进 `tt_accounts` |
| 账户名称 | 表里有「账户名称」→ `tt_accounts.name` 用它；没这列 → 仍用账户ID |
| 空值跳过回写 | `landing_url` 库里为空 → 写方向的 `cells` 不含它；库里有值 → 含 |
| 加白户表不受影响 | 现有 A:M 那套表头 → 解析结果与改动前**逐字段相同** |
| GG/FB 不受影响 | `COLUMN_SPEC` 路径一字未改；既有 `test_gg_sheet_write` / `test_fb_huguan_dashboard` 全绿 |

## 七、影响面清单

**后端**
- `py/database.py` —— `tt_accounts` 加 `subject_name` / `landing_url` 两列
- `py/huguan_dashboard.py` —— 新增 `TT_FIELD_CATALOG` + `resolve_column_map`；
  **需要接 `col_map` 的只有 4 个函数**：`parse_row`（读表列）、`cells_for_row`（写表列）、
  `_owner_sheet_from`（撤回快照的表侧原值）、`owner_channel_cells`（写通道列）。
  ⚠️ `_target_column`（字段名→**数据库**列名，如 `bc_name→bc_id`）与
  `_blank_columns`（按**字段名**过滤）**不需要** `col_map` —— 它们不碰表列字母。
  `snapshot_push_targets` 按 `col_map` 记列；`COLUMN_SPEC` **保留**（gg/fb 仍用）
- ⚠️ 已有先例可循：`owner_role_col(platform, role)`（`py/huguan_dashboard.py:96-112`）就是
  「角色 → 列字母、未知一律抛错、绝不静默落到别的列」的同一哲学，可参照它的写法与注释口径
- `py/routes/huguan_dashboard_routes.py` —— `dashboard_sync` 逐表解析 `col_map`、定位键校验、
  `unmatched_columns` 上报；读范围改 `A:ZZ`；撤回写入按 `col_map` 取 `key_col`；
  配置 POST 校验 `columns`；新增「读表头」端点
- `py/routes/huguan_sheet_targets.py` —— 三处 `key_col=hd.KEY_COL[platform]` 改为按该表 `col_map`

**前端**
- `frontend/src/components/HuguanDashboardCard.vue` —— tt 的每张表加「列映射」区（含读表头）
- `frontend/src/components/AccountSyncModal.vue`（tt 侧同名组件）—— 显示 `unmatched_columns`
  > 注：TT 的同步报告在 `HuguanDashboardCard.vue` 的差异弹窗里，不在 `AccountSyncModal.vue`

**测试**
- `py/tests/test_huguan_dashboard.py`、`test_tt_accounts.py`、`test_huguan_sheet_write.py` 扩充

## 八、未决项

无。首轮两条待定（下户链接空值语义、存量账户名）已由用户裁定，落在 §4.6 / §4.7。
