# TT「换绑情况」列改造：归属变更通道 → 换绑记录字段

> 日期：2026-10-06
> 状态：已确认并实现（2026-10-06）
> 取代范围：`2026-09-23-huguan-sheet-design.md` 的 §7.1、§7.2 规则 1、规则 3② 中**仅 TT 的部分**

## 0. 定性与范围

**这是改需求，不是 bug 修复。**

2026-09-23 的设计中，用户明确要求把「换绑情况」列作为**归属变更通道**：该列非空时压过「接户运营」列
（设计文档 `2026-09-23-huguan-sheet-design.md:35` 留有原话：「同步的时候表里运营列和重新分配列不一致，
就以表里的重新分配为准，更新系统的数据」）。该要求被固化为 §7.2 规则 1，实现于
`py/huguan_dashboard.py:123` 的 `effective_owner_name()`。

2026-10-06 用户裁定：**该规则取消**，「换绑情况」列改作**换绑记录字段**。

| 项 | 裁定 |
|----|------|
| 定性 | 改需求（当时要，现在不要了） |
| 平台范围 | **仅 TT**。GG 的「重新分配」（H 列）逐字节保持现状 |
| 归属判定 | TT 只认「接户运营」（G 列）；「换绑情况」（L 列）不再参与归属判定 |
| L 列新职责 | 换绑记录文本，格式 `变更前归属人转新归属人月.日`，例：`阿轩转黎明10.7` |
| 写 L 的触发点 | **只在系统 UI 改归属时**；从表同步应用归属变更时**不写** |
| 读 L | 原样读回存进系统，**不影响归属** |
| 月日格式 | 不补零（`10.7`；10 月 10 日为 `10.10`）。用户已确认接受 |
| 空值语义 | 读回按表覆盖：表里清空 → 系统里的记录也清空。用户已确认接受 |

### 为什么只改 TT

用户原话：「这是针对于 tt 的广告账户的」。GG 的「重新分配」列承载的是另一套已上线并被使用的流程，
本次不动。因此所有改动点都必须**按平台分叉**，GG 路径的行为、文案、写入内容均不得变化。

## 1. 现状（改动前的四条链路）

| 环节 | 代码位置 | 现状 |
|------|----------|------|
| 列定义 | `py/huguan_dashboard.py:56` | `("L", "换绑情况", "_owner_channel", True, True)` —— 合成字段 |
| GG 同名概念 | `py/huguan_dashboard.py:36` | `("H", "重新分配", "_owner_channel", True, True)` |
| 归属判定 | `py/huguan_dashboard.py:123` | `effective_owner_name()`：`_owner_channel` 非空则压过 `owner_name` |
| 判定调用点 | `py/huguan_dashboard.py:363` | `want_owner_name = effective_owner_name(p)` |
| 系统 UI 改归属写 L | `py/huguan_dashboard.py:892` | `writeback_owner_channel()` 写**新归属人名**到 L |
| 该函数调用点 | `py/routes/tt_accounts_routes.py:539` | TT reassign 落库后调用 |
| 同函数 GG 调用点 | `py/main.py:4797` | GG reassign 落库后调用 |
| 同步后清空 L | `py/routes/huguan_dashboard_routes.py:138` | `owner_channel_cells(applied, platform, "")` —— 规则 3② |
| 同步后回写 G | `py/routes/huguan_dashboard_routes.py:135` | 写 `OWNER_COL[platform]` = 新归属名 —— 规则 4 |
| 表→系统字段收集 | `py/huguan_dashboard.py:300` | `_PLAIN_TEXT_FIELDS["tt"]` 当前为 `("acquired_date","country","timezone","consumption","remark")` |
| 系统→表单元格产出 | `py/huguan_dashboard.py:81` | `cells_for_row()`：跳过 `writable=False`、`field is None`、`field == "_owner_channel"` |

> **行号时效**：以上行号取自 2026-10-06 编写时的工作区。`py/database.py` 正有并行会话在修改
> （`git status` 显示 `M`），其行号已发生过漂移。实现时请按**符号名**定位，行号仅作参考。

TT 的 `tt_accounts` 表**没有**任何 `_add_column_if_missing` 迁移记录（`py/database.py` 中该表只出现在
建表语句与索引里），新增列需同时补建表语句与迁移条目。

## 2. 目标行为

### 2.1 归属判定

| 平台 | 判定 |
|------|------|
| TT | 恒取 G 列「接户运营」（`parsed["owner_name"]`） |
| GG | 维持现状：H 列「重新分配」（`_owner_channel`）非空则压过 G 列「运营」 |

### 2.2 「换绑情况」列的完整生命周期（TT）

```
系统 UI 改归属  ──►  L 列 = "{旧归属人}转{新归属人}{月}.{日}"
                     （同时写入 tt_accounts.owner_change_note，两处同值）
从表同步应用归属变更 ──►  不写 L（与 GG 的规则 3② 分叉）
全量刷新到看板  ──►  不写 L（writable=False，L 不进 cells_for_row）
表里改 L 后同步  ──►  L 的值读回存进 owner_change_note，不影响归属
表里清空 L 后同步  ──►  owner_change_note 被清空，并出现在 clears 列表里提示户管
```

## 3. 实现方案

### 3.1 新增数据库列

`py/database.py`：

1. `tt_accounts` 建表语句（`database.py:963` 起的 `CREATE TABLE IF NOT EXISTS tt_accounts`）中，
   在 `remark TEXT DEFAULT ''` 之后加入：
   ```sql
   owner_change_note TEXT DEFAULT '',
   ```
2. `_ensure_columns()` 中补迁移条目（对存量库生效，参照 `fb_accounts` 的 `remark` 先例
   `database.py:188`）：
   ```python
   _add_column_if_missing(conn, "tt_accounts", "owner_change_note",
                          "owner_change_note TEXT DEFAULT ''")
   ```

两处都要加：建表语句服务全新库，`_add_column_if_missing` 服务存量库（每次连库幂等执行）。

### 3.2 归属判定按平台分叉

`py/huguan_dashboard.py:123`：

```python
def effective_owner_name(parsed: dict, platform: str) -> str:
    """规格 §7.1（GG）/ 2026-10-06 规格（TT）。

    TT：归属恒取「接户运营」列，不看「换绑情况」。
    GG：维持 §7.1 —— 变更通道非空时压过当前归属列。
    """
    if platform == "tt":
        return (parsed.get("owner_name") or "").strip()
    channel = (parsed.get("_owner_channel") or "").strip()
    if channel:
        return channel
    return (parsed.get("owner_name") or "").strip()
```

调用点 `py/huguan_dashboard.py:363` 补传 `platform`。`build_diff()` 已有 `platform` 参数，无需改签名。

### 3.3 列定义改为普通文本字段

`py/huguan_dashboard.py:56`：

```python
("L", "换绑情况", "owner_change_note", False, True),
```

- `writable=False`：L 列**不参与任何全量/单行回写**（`cells_for_row` 跳过它）。
  这保留了原规则 2「自动回写不得碰这一列」的实际效果，且比原先靠
  `field == "_owner_channel"` 的守卫更直白。L 只由 3.5 的单点写入更新。
- `readable=True`：读回，见 3.4。

GG 的 H 列条目（`huguan_dashboard.py:36`）**保持不变**，仍走 `_owner_channel` 合成字段与既有的
`field == "_owner_channel"` 守卫。

### 3.4 读回按表覆盖

`py/huguan_dashboard.py:300` 的 `_PLAIN_TEXT_FIELDS["tt"]` 追加 `"owner_change_note"`：

```python
"tt": ("acquired_date", "country", "timezone", "consumption", "remark",
       "owner_change_note"),
```

效果：`_collect_updates()` 把 L 列的值原样收进 `db_values`，按既有「文本列空值照常落库」口径
（该函数 docstring 已明确此约定，实现时勿加 `if not value: continue`）覆盖系统值；空串会被 `_blank_columns()` 收进 `clears`，
在前端确认弹窗的「将清空以下字段」区块里显式提示户管。

`owner_change_note` 是真实数据库列，`_target_column()` 的映射表无需改动（它只处理需解析的名称类字段）。

### 3.5 系统 UI 改归属时写 L

分两处，**同一份文本**：

**(a) 落库**：`py/routes/tt_accounts_routes.py` 的 `reassign_account()`。

该函数在 `db.execute("UPDATE tt_accounts SET owner_id=?...")` 之后、`db.commit()` 之前，
按已有变量构造并落库：

```python
old_label = (existing["display_name"] or existing["username"] or "未分配").strip()
# 新归属名 label 已在该函数末尾为返回文案查询过，上移到 commit 之前复用，避免二次查询
now = datetime.datetime.now()
note = f"{old_label}转{label}{now.month}.{now.day}"
db.execute("UPDATE tt_accounts SET owner_change_note=? WHERE id=?", (note, aid))
```

注意：`label` / `old_owner` 目前是在 `db.commit()` **之后**才计算的（只为拼返回文案）。
本改动需把这段取值上移到 commit 之前。这是**计算位置**的移动，返回文案字符串本身不变。

月日**不得**用 `strftime("%-m")` —— Windows 平台不支持该格式符。用 `f"{now.month}.{now.day}"`。

**(b) 写表**：`py/huguan_dashboard.py:892` 的 `writeback_owner_channel()` 增加可选参数：

```python
def writeback_owner_channel(user_id, platform, account_id, new_owner_id, text=None):
    ...
    name = (r["n"] if r else "").strip()
    if not name:
        return
    value = text if text is not None else name   # GG 不传 text，逐字节保持原行为
    rows = owner_channel_cells([{"account_id": account_id}], platform, value)
```

TT 调用点（`tt_accounts_routes.py:544`）传 `text=note`；GG 调用点（`main.py:4797`）不传，行为不变。

**为什么不在 `writeback_owner_channel` 内部构造文本**：文本里含「变更前归属人」，那是 reassign 端点
才知道的信息（它已查出 `existing`）；在该函数里重新推断会引入第二次查询与不一致风险。

### 3.6 取消 TT「同步后清空 L」

`py/routes/huguan_dashboard_routes.py:138`：

```python
_write_background(conf, hd.owner_channel_cells(applied, platform, ""))
```

改为**仅 GG 执行**：

```python
if applied and platform != "tt":
    _write_background(conf, hd.owner_channel_cells(applied, platform, ""))
```

**必须改**：L 列现在是换绑记录。这条清空若对 TT 生效，每次同步都会抹掉记录；且因为 3.4 的读回是
按表覆盖，清空还会连带把系统里的 `owner_change_note` 读成空 —— 记录被双重抹除。

同段的规则 4 回写（`huguan_dashboard_routes.py:132` 写 `OWNER_COL`）**保持不变**：
TT 的 G 列现在是唯一的归属列，同步应用归属变更后回写它，两列才一致、不会重复应用同一条变更。

### 3.7 前端展示

`frontend/src/views/tt/TtAccountPanel.vue`：在既有「户归属」列（第 162 行，
`v-if="authStore.isHuguan"`，`width="160"`）之后新增一列：

```vue
<el-table-column v-if="authStore.isHuguan" prop="owner_change_note"
                 label="换绑情况" min-width="160" show-overflow-tooltip />
```

只读展示，无交互。列表接口 `GET /api/tt/accounts/list` 用 `SELECT a.*` 取数
（`tt_accounts_routes.py:241`），新增列会自动随响应返回，后端接口无需改动。

## 4. 被取代的既有条款

`docs/superpowers/specs/2026-09-23-huguan-sheet-design.md` 中的下列条款**仅对 TT 失效**，GG 部分继续有效：

| 条款 | 位置 | 处理 |
|------|------|------|
| §7.1 有效归属判定（通道优先） | 设计文档 :253-262 | TT 作废；GG 保留 |
| §7.2 规则 1（变更通道优先） | 设计文档 :266 | TT 作废；GG 保留 |
| §7.2 规则 2（自动回写不碰通道列） | 设计文档 :267-269 | TT **效果保留**（改由 `writable=False` 实现）；GG 保留原实现 |
| §7.2 规则 3①（系统 UI 改归属写 L） | 设计文档 :270 | TT **保留但内容变更**：由「写新归属名」改为「写 旧转新月.日」 |
| §7.2 规则 3②（同步后清空通道列） | 设计文档 :271 | TT 作废；GG 保留 |
| §7.2 规则 4（落库后回写运营列） | 设计文档 :272-273 | TT / GG 均保留 |
| 决策 #10（TT「换绑情况」与 GG「重新分配」同义） | 设计文档 :54 | TT 部分作废：不再是同义的变更通道 |
| 表 4.2 备注（L 列「系统实际回写区间」说明） | 设计文档 :150 | 实质失效：L 改 `writable=False`，彻底不在回写区间内 |

**旧文档的处理**：已在其「七、归属变更协议」标题下加入一条指向本文档的**取代声明**（2026-10-06），
正文逐条未重写，以保留决策历史。

## 5. 已知后果

1. **换绑历史只留最后一次**。格式是 `变更前→新` 且每次覆盖，`阿豪→阿轩→黎明` 最终只留
   `阿轩转黎明10.7`，`阿豪` 这一跳信息丢失。这是用户明确选择的（「只记本次」），不是缺陷。
   若将来需要完整链路，需另建归属变更历史表。
2. **系统 UI 改归属与表里手改 L 可能冲突但不会丢数据**：系统改归属时写 L 会覆盖户管在表里手填的
   L 内容。但该手填内容若已同步过，则已存进系统；系统写的是同一次变更的最新记录，语义一致。
3. **TT 的 L 列不再由全量刷新维护**。户管在表里手改 L 而不同步时，系统不会把它覆盖回去 —— 这是
   「只在系统 UI 改时写」的直接结果，符合需求。
4. **`owner_id` 为空的账户改归属**：旧归属人取不到显示名，写 `未分配转{新}月.日`。

## 6. 测试要点

测试落在 `py/tests/test_huguan_dashboard.py`（既有夹具与打桩齐备）。

| # | 用例 | 断言 |
|---|------|------|
| 1 | TT 行 L 列有值、G 列为另一人 | 归属取 G 列的人，**不**取 L 列 |
| 2 | GG 行 H 列有值、G 列为另一人 | 归属取 H 列的人（回归：GG 未受影响） |
| 3 | GG 行 H 列为空 | 归属取 G 列的人（回归） |
| 4 | TT 建户行带 L 值 | `owner_change_note` 落库为该值 |
| 5 | TT 已存在账户，表里改 L | `owner_change_note` 按表覆盖更新 |
| 6 | TT 已存在账户，表里清空 L | `owner_change_note` 被清空，且该字段出现在 `clears` 里 |
| 7 | TT 同步应用归属变更后 | **不**产生 L 列的写回调用 |
| 8 | GG 同步应用归属变更后 | 仍产生 H 列清空写回（回归） |
| 9 | TT reassign（户管改归属） | DB 的 `owner_change_note` == 写表的 L 值 == `旧转新月.日` |
| 10 | TT reassign 时旧归属为 NULL | 文本以 `未分配转` 开头 |
| 11 | TT 全量 push | 产出的 cells **不含** L 列 |
| 12 | 月日格式 | `10 月 7 日` → `10.7`（不补零），且不依赖 `strftime("%-m")` |

用例 2、3、8 是**回归护栏** —— 本次改动的最大风险是「按平台分叉时把 GG 一起改了」。

## 7. 不做什么（YAGNI）

- **不**新建归属变更历史表。用户要的是单元格里的一行文本，不是完整审计链。
- **不**改 GG 的任何行为、文案、写入内容、列定义。
- **不**在前端加编辑入口。L 列由系统在改归属时生成，户管在系统内只读查看。
- **不**动 `tt_account_bc_history`（那是 BC 变更历史，与归属无关，仅命名相近）。
- **不**动本次同期讨论的 `remark`（备注）同步优先级问题 —— 那是独立需求，另行设计。
