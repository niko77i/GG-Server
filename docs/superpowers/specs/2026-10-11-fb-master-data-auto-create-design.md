# FB 户管看板：所属渠道 / 资产类型 自动补建（设计）

> 2026-10-11。用户报「所属渠道、资产类型不是自动新增，系统没有的话」。
> 本文只覆盖这一件事，且**只做 FB 的这两个字典**。

## 一、问题

FB 的「从表同步到系统」遇到系统里没有的名字时，三个字段行为不一致：

| FB 字段 | 现状 | 位置 |
|---|---|---|
| 状态 | **已经会自动建**（`_pending_status` → `resolve_status_id(create_missing=True)`） | `py/huguan_dashboard.py:1655` / `:1746` |
| **所属渠道** | ❌ 只记警告、**整列跳过** | `:1315-1322` |
| **资产类型** | ❌ 同上 | 同上 |
| 位置（主 BM 名） | 只记警告、跳过（**本次也不改**，见 §五） | — |

根因是一句写死的平台门控（`:1316`）：

```python
if hits == 0 and platform == "tt" and f in ("bc_name", "agent_name"):
    pending_master.append({...})      # ← 只有 tt 走这里
    continue
warnings.append({"row": row_no, ..., "message": f"{f}「{value}」无法唯一匹配，已跳过该列"})
```

FB 的 `channel_name` / `asset_type_name` 永远落到下面那句警告 ⇒ **户管看到的是
「channel_name「XX」无法唯一匹配，已跳过该列」，且这一列根本不落库**。

## 二、已确认的决策（用户 2026-10-11 逐条裁定）

| # | 决策 | 出处 |
|---|---|---|
| 1 | **只做「所属渠道 + 资产类型」**；位置（主 BM）不补建 | 用户选「只做所属渠道+资产类型（推荐）」 |
| 2 | 补建**无条件执行**，不跟着行勾选走（照 TT 口径） | 用户选「无条件执行（照 TT，推荐）」 |
| 3 | 走**方案 1**：门控改成映射表 + kind 分派显式化 + 新增两个 `ensure_*`；模块改名 `master_data.py` | 用户选「按方案 1 走，去写 spec」 |

## 三、现状事实（2026-10-11 实测）

- `_PARSEABLE_FIELDS["fb"] = ("channel_name", "asset_type_name", "status_name")`
  （`:980`），三者都走名称解析。
- `_SQL_CHANNEL` / `_SQL_ASSET_TYPE`（`:929-930`）是**纯名字查表**：
  `SELECT id FROM fb_channels WHERE name=? AND platform='fb'`。
- `fb_channels` / `fb_asset_types` 的建表（`database.py:823-841`）：
  `name` + `owner_id` + `platform` + `UNIQUE(name, platform)`，**没有 `deleted_at`**。
  ⇒ 与 TT 的 `tt_bcs`（有 `deleted_at`、`ensure_bc` 要处理「软删复活」）不同，
  **FB 这两个表的 ensure 更简单：查名字 → 没有就 INSERT**。
- `UNIQUE(name, platform)` ⇒ 至多命中 1 行 ⇒ **FB 这两个字段没有「歧义档」**，
  解析不到就一定是「系统里没有」。这对本设计是好消息：不需要 `hits >= 2` 的分支。
  （TT 的 BC 有 name / bc_id 两个键，才需要歧义判定。）
- `_named_hits`（`:812-828`）现在**认不出** FB 的两个字段：`else: return 0`，
  且注释明写「fb 的『所属渠道』不在 agents 表里 ⇒ 不走本 pending 分支」。
- **`apply_diff` 里判 kind 用的是「末位 else 兜底」**，三处形状：

  | 位置 | 分支 | 兜底 `else` |
  |---|---|---|
  | 新建账户 `:1662-1667` | `src["bc_id"] = ensure_bc(...)` / `src["agent_id"] = ensure_agent(...)` | `_ensure_region(...)` |
  | 更新账户 `:1754-1759` | `fields["bc_id"] = ...` / `fields["agent_id"] = ...`（`owner_id` 取的是 **`scope_owner_id`**） | `_ensure_region(...)` |
  | 孤儿行 `:1903-1912` | `link["bc_id"] = bc_id`（**`if bc_id is not None` 才写**） | `_ensure_region(...)` |

  新建用的是 `item.get("owner_id")`，更新/孤儿用的是 `item.get("scope_owner_id")` ——
  键名不同，改的时候别混。
- 前端 `HD_MASTER_KIND_LABEL = { bc: 'BC', agent: '渠道', region: '国家时区' }`（`:1211`），
  渲染一节「将新增的字典项 / 已补建的字典项」（`:702-741`），**机制本身是通用的**。
- 前端另有**三处写死**的文案「BC / 渠道 / 国家时区」（`:728` / `:729` / `:731`）。

## 四、技术方案

### 4.1 门控改成映射表（不再堆平台分支）

```python
# 字段 → 待补建的字典项类别。**唯一的门控**：命中这个表才产 pending。
# 用数据表而不是 `platform == ".."` 分支 —— 将来加平台/加字段只是加一行，
# 不会再多一个「某平台走某分支」的地方（那种分支正是漏算新类别的温床）。
_PENDING_MASTER_FIELDS = {
    ("tt", "bc_name"): "bc",
    ("tt", "agent_name"): "agent",
    ("fb", "channel_name"): "channel",
    ("fb", "asset_type_name"): "asset_type",
}
```

`_collect_updates` 里把 `:1315-1322` 改成：

```python
            hits = _named_hits(db, platform, f, value)
            kind = _PENDING_MASTER_FIELDS.get((platform, f))
            if kind and hits == 0:
                pending_master.append({"kind": kind, "name": value, "timezone": None})
                continue
            warnings.append({"row": row_no, "sheet": _conf_text(p.get("_sheet")),
                             "message": f"{f}「{value}」无法唯一匹配，已跳过该列"})
            continue
```

（`hits` 仍照原样先算——`_named_hits` 对不认识的字段是常量 0、不发查询，保持最小改动。）

### 4.2 `_named_hits` 认下 FB 的两个字段

```python
    elif field == "channel_name":
        sql = _SQL_CHANNEL
    elif field == "asset_type_name":
        sql = _SQL_ASSET_TYPE
```

并把「fb 的『所属渠道』不在 agents 表里 ⇒ 不走本 pending 分支」那句注释改掉
（它现在只对 `agent_name` 成立）。

### 4.3 kind 分派显式化 —— 拿掉 `else` 兜底（**本单最要害的一改**）

三处 `else: _ensure_region(...)` 是一个**兜底谓词**：新增 kind 若漏改这里，
渠道名会被当国家**静默写进 `regions` 表**，而且不报错。本仓库已经栽过一次
「加新类别撞上兜底谓词」（见台账里的门控谓词教训），所以这次**先把它拆掉**。

抽一个共享函数 `ensure_pending_master`。**它住在 `py/huguan_dashboard.py`，不住 `master_data.py`** ——
分工是：`master_data.py` = 按表的「确保存在」原语（`ensure_bc` / `ensure_agent` /
`ensure_channel` / `ensure_asset_type`），`huguan_dashboard.py` = 把 kind 分派到原语。

> ⚠️ **为什么不能放进 `master_data.py`**：那个分派要处理 `kind == "region"`，而
> `_ensure_region` 住在 `huguan_dashboard.py`。若把分派挪进 `master_data.py`，就得
> `master_data → huguan_dashboard`，而 `huguan_dashboard` 已经 `→ master_data`
> ⇒ **循环 import**。（初稿就是这么写的，自审时抓到的。）

```python
def ensure_pending_master(db, items, owner_id) -> dict:
    """补建一行引用的全部字典项，返回要写进账户行的 `{列名: id}`。

    **kind 必须显式穷举，末位 raise** —— 这里曾经是 `else: _ensure_region(...)` 兜底，
    新增 kind 漏改就会被静默写进 regions 表（把渠道名当国家），且不报错。
    不知道的类别要当场炸，不要猜。
    region 没有可挂的 id，只建、不进返回值。
    """
    out = {}
    for x in items or []:
        kind = x.get("kind")
        if kind == "bc":
            out["bc_id"] = ensure_bc(db, x["name"], owner_id)
        elif kind == "agent":
            out["agent_id"] = ensure_agent(db, x["name"], owner_id)
        elif kind == "channel":
            out["channel_id"] = ensure_channel(db, x["name"], owner_id)
        elif kind == "asset_type":
            out["asset_type_id"] = ensure_asset_type(db, x["name"], owner_id)
        elif kind == "region":
            _ensure_region(db, x["name"], x.get("timezone"))
        else:
            raise ValueError(f"未知的字典项类别: {kind!r}")
    return out
```

三处调用点相应改成（**逐处保持各自原有的 NULL 口径**）：

```python
# 新建（:1662）
            src.update(ensure_pending_master(db, item.get("pending_master"),
                                             item.get("owner_id")))
# 更新（:1754）
            fields.update(ensure_pending_master(db, item.get("pending_master"),
                                                item.get("scope_owner_id")))
# 孤儿行（:1903）—— 原有的「None 不挂链」口径保留
            link = {k: v for k, v in ensure_pending_master(
                db, item.get("pending_master"), item.get("scope_owner_id")).items()
                if v is not None}
```

`_ensure_region` **留在原处**（`huguan_dashboard.py`），不进 `master_data.py` —— 理由见上。
它与 `_region_exists`（只读）成对，同住 `huguan_dashboard.py` 反而更整齐。

### 4.4 新增两个 ensure（照 `ensure_agent` 的形状，但更简单）

```python
def ensure_channel(db, name, uid):
    """fb_channels 里没有就建。**无软删**（该表没有 deleted_at 列）⇒ 比 ensure_bc 简单。"""
    name = (name or "").strip()
    if not name:
        return None
    row = db.execute("SELECT id FROM fb_channels WHERE name=? AND platform='fb'",
                     (name,)).fetchone()
    if row:
        return row["id"]
    db.execute("INSERT INTO fb_channels(name, owner_id, platform) VALUES(?,?, 'fb')",
               (name, uid))
    return db.execute("SELECT last_insert_rowid()").fetchone()[0]
```

`ensure_asset_type` 同形，换表名 `fb_asset_types`。

### 4.4bis 与既有「选项表 API」对齐（写 spec 时新查到的事实）

`fb_channels` / `fb_asset_types` **已经有一组现成的 list/create/rename/delete 端点**，
由 `py/main.py:6889` 的通用工厂注册：

```python
_register_shared_option_api("fb_channels",     "/api/fb-channels",     "channel_id",   "渠道")
_register_shared_option_api("fb_asset_types",  "/api/fb-asset-types",  "asset_type_id", "资产类型")
```

它对 `ensure_channel` / `ensure_asset_type` 有**三条硬约束**：

1. **`platform` 必须写死 `'fb'`，不能用请求侧的值。**
   工厂的 `/list` 与 `/create` 都用 `_get_effective_platform()`，而
   `_SQL_CHANNEL` / `_SQL_ASSET_TYPE`（同步侧的解析）**写死 `platform='fb'`**。
   自动补建若跟着请求侧走，一旦调用方的 effective platform 不是 fb，
   建出来的行**同步侧永远查不到**（看不见地重复建）。故照 `ensure_agent` 的做法写死。
2. **语义必须与那个 create 端点一致**：它「同名已存在 ⇒ 409 拒绝」，不做 upsert。
   我们的 `ensure_*` 是**幂等**的（先查、有就返回、没有才 INSERT），
   INSERT 的列形状照抄它：`INSERT INTO {table}(name, owner_id, platform) VALUES(?,?,?)`。
   （不能直接复用那个端点：它是 HTTP 层、依赖 jwt 上下文，纯逻辑层调不到。）
3. **没有缓存**：工厂的 `/list` 是**直查**（`SELECT id, name FROM …`），
   没有走 `_app_cache`。⇒ `ensure_channel` / `ensure_asset_type` **不需要**清缓存。
   （`ensure_agent` 要清是因为 `agents` 的列表走了缓存；这两张表不是。）
   实现时**再核一遍**并写进报告，别沉默跳过。

### 4.5 模块改名

`py/tt_master_data.py` 加 FB 函数后就名不副实了 ⇒ 改名 `py/master_data.py`，
更新全部引用点（`huguan_dashboard.py`、`routes/tt_accounts_routes.py`、
以及 import 它的测试）。**这是纯改名，行为不变**，既有测试全绿即为证据。

> 它与 `ensure_bc`/`ensure_agent` 的提取是同一性质的整理：那次是从
> `tt_accounts_routes` 提到共享模块，这次是把「共享模块」的名字纠正过来。

### 4.6 数据流（与 TT 逐条对齐）

| 环节 | 行为 |
|---|---|
| 干跑（`dry_run`） | 只**产出** `_pending_master`（`build_diff` 用 `create_missing=False`），**不写库** |
| 报告层 | 聚合进 `diff.pending_master`（按 kind+name 汇总 `rows` 计数），前端渲染「将新增的字典项」 |
| 落库（确认后） | `apply_diff` 走 `ensure_pending_master` 补建，并把新建 id 挂到该账户行 |
| 行勾选 | **不影响字典项补建**（无条件执行）。`hdCanApply` 已有「选中数 > 0 **或** 有待补建字典项」的口径，本功能自动适用 |
| 孤儿行 | 账户本身既不新建也不更新、但它引用的字典项缺 ⇒ 仍补建并定向挂链（`pending_master_rows` 机制，已有，自动适用） |
| 歧义（≥2 同名） | **FB 不存在此档**（`UNIQUE(name, platform)`）；即便将来有，也只警告不建（TT 同口径） |
| 空值 | 表里该列空着 ⇒ 不建也不改（`_parseable_fields` 只在值非空时解析） |

### 4.7 前端

1. `HD_MASTER_KIND_LABEL` 补两项：
   ```js
   const HD_MASTER_KIND_LABEL = {
     bc: 'BC', agent: '渠道', region: '国家时区',
     channel: '所属渠道', asset_type: '资产类型',
   }
   ```
   （`agent: '渠道'` 是 **TT** 的所属渠道；FB 的走 `channel`，标签用 FB 表头原文「所属渠道」，
   两平台各自对齐自己的表头，不互相改。）
2. **三处写死的「BC / 渠道 / 国家时区」（`:728`/`:729`/`:731`）改成由数据推导**：
   取本次 `hdPendingMaster` 里出现的 kind 去重、按固定顺序映射成标签再拼。
   理由：写死的那串**已经漏了 FB 的两个新类别**——这正是「写死的清单必漂」，
   改成从数据推就不会再有第二次。
3. 渲染那一节本身（`v-for` + `hdMasterKindLabel`）**不用改**，它已经是通用的。

## 五、非目标

- **位置（主 BM 名）不补建**：`fb_bms.bm_id` 是 `NOT NULL UNIQUE`，而表里那列只有名字
  ⇒ 系统凭空造不出 bm_id，硬建会产出一个**没有 bm_id 的假 BM**，污染 BM 下拉与账户关联。
  名字对不上时继续「只警告、跳过」（现状）。用户已裁定。
- **状态不动**：它已经会自动建（`_pending_status`），本次只核实、不修改。
- **GG / TT 的行为逐字节不变**：门控改成映射表后，TT 命中的两条完全一样；
  GG 一个都不命中（`_PENDING_MASTER_FIELDS` 里没有 gg 的键）。
- 不新增字典的「管理界面」（渠道/资产类型仍只在设置页维护 + 同步时自动补）。
- 不做「补建失败重试」的独立机制（沿用既有写表治理/日志）。

## 六、测试

**锚（证明没改坏）**
1. TT 既有测试**全绿**（门控换映射表、kind 分派抽函数、模块改名**都不改变 TT 行为**）。
2. GG 既有测试全绿（GG 不认识这些 kind，一个都不命中）。

**新增**
- FB 表里一个系统没有的渠道名 ⇒ 干跑产 `pending_master` 含 `{"kind":"channel","name":…}`，
  **且该行不再出现「channel_name「X」无法唯一匹配」这条警告**（这是问题本身的回归钉）
- 资产类型同款
- **`ensure_pending_master` 遇到未知 kind 必须 raise**（拿掉兜底谓词的回归钉）
- 落库：确认后 `fb_channels` / `fb_asset_types` 各多一行，且**账户行挂上了新 id**
- 干跑**不写库**（`fb_channels` 行数不变）
- 已存在的渠道名 ⇒ **不重复建**（不加行），且该列照常落库（走原来的解析路径）
- 孤儿行：账户不变但渠道缺 ⇒ 字典项仍被补建、且挂链
- 无软删复活：`fb_channels` 里同名软删行**不存在**（该表无 `deleted_at`），
  故**不需要**测复活；但要钉「同名已存在时不新增行」

**前端无法单测**：这个仓库没有组件测试框架（`node --test` 只跑纯逻辑），
所以 `HD_MASTER_KIND_LABEL` 的新标签与「文案由数据推导」只能靠
`npx vite build` + **人工验收**（见 §六之后列出的验收项），不写成自动化用例。

## 六之二、人工验收（你来点）

- [ ] FB 同步一张含**系统里没有的渠道名**的表 → 预演弹窗出现「将新增的字典项」一节，
      列出「所属渠道 · XX · N 行」
- [ ] 同一张表**不再**出现「channel_name「XX」无法唯一匹配，已跳过该列」这条警告
- [ ] 该行**其他列**照常出现在新增/更新里（渠道不再拖累整行）
- [ ] 点确认后：`fb_channels` 里多了那一行，且该账户的「所属渠道」**显示出了名字**
- [ ] 资产类型同款
- [ ] **只干跑不确认** → `fb_channels` / `fb_asset_types` **行数不变**
- [ ] 同一批表数据**再同步一次** → 「将新增的字典项」一节**为空**（不会重复建）
- [ ] 该节里那句文案按平台/按数据说对了词（FB 该出现「所属渠道 / 资产类型」，
      不该出现「BC / 国家时区」）

## 七、影响面清单

| 文件 | 改动 |
|---|---|
| `py/tt_master_data.py` → **`py/master_data.py`** | 改名；新增 `ensure_channel` / `ensure_asset_type`（`ensure_pending_master` **不在这里**，见 §4.3） |
| `py/huguan_dashboard.py` | 新增 `_PENDING_MASTER_FIELDS` 与 `ensure_pending_master`；`_collect_updates` 门控改查表；`_named_hits` 认两个 FB 字段；三处 kind 分派改调 `ensure_pending_master`；import 改名；**`_ensure_region` / `_region_exists` 留在原处不动** |
| `py/routes/tt_accounts_routes.py` | import 改名（它已从该模块取 `ensure_bc`/`ensure_agent`） |
| `py/routes/huguan_dashboard_routes.py` | 若有对 `tt_master_data` 的引用则改名（实现时 grep 确认） |
| `py/tests/*` | 引用 `tt_master_data` 的测试改名；新增 FB 用例（落点 `py/tests/test_fb_huguan_dashboard.py`） |
| `frontend/src/components/HuguanDashboardCard.vue` | `HD_MASTER_KIND_LABEL` 加两项；三处写死文案改成按数据推导 |

## 八、未决项

1. **新建字典项的 `owner_id` 取谁**：照 `ensure_agent` 的口径取**当前户管 uid**
   （新建分支用 `item["owner_id"]`、更新与孤儿用 `item["scope_owner_id"]`，保持现状）。
   若你希望「字典项归属建它的人」以外的口径，实现前说。
2. **是否也要给渠道/资产类型加「软删」**（对齐 `tt_bcs` 的 `deleted_at`）：本次**不加**
   （该表本来就没有，加列是独立的事）。
