# FB 户管看板 Implementation Plan（子项目 ②）

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把户管看板的 Google Sheet 双向同步扩到 FB 平台，让 FB 户管能配置自己的看板表并与系统互相同步。

**Architecture:** 纯增量扩张。`py/huguan_dashboard.py` 是纯逻辑层，原本按 `platform` 做**二元**分支（`"tt_accounts" if platform == "tt" else "accounts"`）；本计划把 5 处二元改成以平台为键的字典查表（缺键即 `KeyError`，避免静默回落 GG 表），再补上 FB 的列规格、行查询与三处 FB 特有逻辑（沿用 TT / GG 既有形状）。

**Tech Stack:** Python 3 + Flask + sqlite3（原生 SQL）；Vue 3 + Element Plus；pytest + Flask test client。

## Global Constraints

- 设计依据：`docs/superpowers/specs/2026-10-06-fb-huguan-dashboard-design.md`。与本文冲突时以该 spec 为准。
- **行号不可靠**：本仓库有并行会话在持续改这些文件，**一律用锚点（函数名 / 特征行）定位，不要按行号改**。
- **纯增量**：GG / TT 的既有行为**逐字节不变**。唯一的例外是 Task 5 对子项目 ① 的 `acceptor_id` 修订，用户已明确同意。
- **`COLUMN_SPEC["fb"]` 的标志位照 spec §4 的表抄**：`A/C/E/F/G/H/J/K/L/M/N/O/P/Q` = `(True, True)`；`B` = `(True, False)`；`D` = `(True, False)`；**`I` = `(False, True)`**。
- **FB 的 `OWNER_CHANNEL_COL` 不登记键**（spec §6.5）。任何按平台分流的地方，FB 必须走自己的路径。
- **提交时只 `git add` 本任务明确列出的文件**，禁止 `git add -A`（并行会话在途改文件）。
- 测试门禁：`cd py && python -m pytest tests/ -q`，只增不减。前端门禁：`cd frontend && npm run build`。

---

## File Structure

| 文件 | 动作 | 职责 |
|---|---|---|
| `py/huguan_dashboard.py` | 修改 | 平台分支骨架、FB 列规格与行查询、名称解析、death 跳过、主 BM、归属协议 |
| `py/database.py` | 修改 | 补 `fb_accounts.acceptor TEXT`（Task 5） |
| `py/routes/fb_routes.py` | 修改 | 承载 `acceptor`（Task 5）、三个写表触发点（Task 6） |
| `py/main.py` | 修改 | 无（确认不需要动） |
| `py/tests/test_fb_huguan_dashboard.py` | 新建 | 本子项目的全部后端测试 |
| `frontend/src/components/HuguanDashboardCard.vue` | 修改 | 支持 `platform="fb"` |
| `frontend/src/views/fb/FbSettingsPanel.vue` | 修改 | 挂载看板卡片 |
| `frontend/src/views/fb/FbAccountPanel.vue` | 修改 | 接户运营改文本输入（Task 5） |

---

## Task 1: 平台骨架 —— PLATFORMS 扩三元 + 消除二元回落

**Files:**
- Modify: `py/huguan_dashboard.py`
- Test: `py/tests/test_fb_huguan_dashboard.py`（新建）

**Interfaces:**
- Consumes: 无
- Produces:
  - `PLATFORMS = ("gg", "tt", "fb")`
  - 模块级字典 `_TABLE_FOR_PLATFORM = {"gg": "accounts", "tt": "tt_accounts", "fb": "fb_accounts"}`
  - 模块级字典 `_AGENT_SQL = {"gg": _SQL_AGENT_GG, "tt": _SQL_AGENT_TT, "fb": None}`（FB 的渠道不走 agents，见 Task 2）
  - 模块级字典 `_ROW_SQL = {"gg": _GG_ROW_SQL, "tt": _TT_ROW_SQL, "fb": _FB_ROW_SQL}`
  - `COLUMN_SPEC["fb"]`（17 列）、`KEY_COL["fb"]="D"`、`OWNER_COL["fb"]="J"`、`READ_RANGE["fb"]="A:Q"`、`ACCOUNT_KEY_FIELD["fb"]="account_id"`、`_PLAIN_TEXT_FIELDS["fb"]`
  - `_FB_ROW_SQL`

- [ ] **Step 1: 写失败测试**

新建 `py/tests/test_fb_huguan_dashboard.py`：

```python
"""FB 户管看板（子项目 ②）测试。

设计见 docs/superpowers/specs/2026-10-06-fb-huguan-dashboard-design.md。
本文件不打真实 Google API。
"""
import pytest

import database
import huguan_dashboard as hd


class TestPlatformSkeleton:
    def test_platforms_includes_fb(self):
        assert hd.PLATFORMS == ("gg", "tt", "fb")

    def test_table_for_platform_has_all_three(self):
        assert hd._TABLE_FOR_PLATFORM["gg"] == "accounts"
        assert hd._TABLE_FOR_PLATFORM["tt"] == "tt_accounts"
        assert hd._TABLE_FOR_PLATFORM["fb"] == "fb_accounts"

    def test_table_lookup_raises_on_unknown_platform(self):
        """缺键必须 KeyError —— 不能像二元 else 那样静默回落 GG 表。"""
        with pytest.raises(KeyError):
            hd._TABLE_FOR_PLATFORM["fbx"]

    def test_row_sql_has_all_three(self):
        for p in hd.PLATFORMS:
            assert p in hd._ROW_SQL, p

    def test_fb_row_sql_selects_from_fb_accounts(self):
        assert "FROM fb_accounts" in hd._FB_ROW_SQL

    def test_fb_row_sql_joins_primary_bm_only(self):
        """主 BM 的 join 必须带 is_primary=1，否则多 BM 账户会让行数翻倍。"""
        assert "ab.is_primary = 1" in hd._FB_ROW_SQL


class TestFbColumnSpec:
    def test_seventeen_columns(self):
        assert len(hd.COLUMN_SPEC["fb"]) == 17
        letters = [c[0] for c in hd.COLUMN_SPEC["fb"]]
        assert letters == [chr(ord("A") + i) for i in range(17)]

    def test_writable_readable_flags(self):
        flags = {c[0]: (c[3], c[4]) for c in hd.COLUMN_SPEC["fb"]}
        # B 操作人与 D 资产UID：写但不读
        assert flags["B"] == (True, False)
        assert flags["D"] == (True, False)
        # I 接户运营：只读回 + 定向写，不参与批量回写
        assert flags["I"] == (False, True)
        # 其余全部双向
        for col in "ACEFGHJKLMNOPQ":
            assert flags[col] == (True, True), col

    def test_key_and_owner_cols(self):
        assert hd.KEY_COL["fb"] == "D"
        assert hd.OWNER_COL["fb"] == "J"
        assert hd.READ_RANGE["fb"] == "A:Q"
        assert hd.ACCOUNT_KEY_FIELD["fb"] == "account_id"

    def test_owner_channel_col_has_no_fb_key(self):
        """FB 刻意不登记 —— 见 spec §6.5。"""
        assert "fb" not in hd.OWNER_CHANNEL_COL

    def test_cells_for_row_excludes_column_i(self):
        """cells_for_row 产出 = A:Q 除去 I。"""
        row = {c[2]: "x" for c in hd.COLUMN_SPEC["fb"] if c[2]}
        row["account_id"] = "123"
        cells = hd.cells_for_row(row, "fb")
        assert "I" not in cells
        assert set(cells) == set("ABCDEFGHJKLMNOPQ")   # A:Q 共 17 列，除去 I 剩 16
```

- [ ] **Step 2: 跑测试确认失败**

```bash
cd py && python -m pytest tests/test_fb_huguan_dashboard.py -q
```

Expected: FAIL —— `AttributeError: module 'huguan_dashboard' has no attribute '_TABLE_FOR_PLATFORM'` 等。

- [ ] **Step 3: 扩 PLATFORMS 与各字典**

在 `py/huguan_dashboard.py` 顶部，把 `PLATFORMS = ("gg", "tt")` 改为：

```python
PLATFORMS = ("gg", "tt", "fb")
```

在 `COLUMN_SPEC` 字典里，`"tt": [...]` 那一段**之后**追加：

```python
    "fb": [
        ("A", "日期",     "acquired_date",   True,  True),
        ("B", "操作人",   "operator",        True,  False),  # 冻结字段，系统写、绝不读回
        ("C", "账户名称", "name",            True,  True),
        ("D", "资产UID",  "account_id",      True,  False),  # 定位键
        ("E", "所属渠道", "channel_name",    True,  True),
        ("F", "资产类型", "asset_type_name", True,  True),
        ("G", "单价",     "unit_price",      True,  True),
        ("H", "入库",     "inbound_qty",     True,  True),
        # I 只读回、不参与批量回写：它是系统生成的换绑记录，由三个定向写点维护
        # （建号 / reassign / apply_diff 收尾）。与 TT 的 L 列同形。
        ("I", "接户运营", "acceptor",        False, True),
        ("J", "在用运营", "owner_name",      True,  True),
        ("K", "出库时间", "outbound_date",   True,  True),
        ("L", "出库",     "outbound_qty",    True,  True),
        ("M", "时区",     "timezone",        True,  True),
        ("N", "消耗",     "consumption",     True,  True),
        ("O", "状态",     "status_name",     True,  True),
        ("P", "位置",     "primary_bm_name", True,  True),
        ("Q", "产品信息", "remark",          True,  True),
    ],
```

把三个字典行改为（**追加 fb 键**）：

```python
KEY_COL = {"gg": "C", "tt": "C", "fb": "D"}
OWNER_COL = {"gg": "G", "tt": "G", "fb": "J"}
OWNER_CHANNEL_COL = {"gg": "H", "tt": "L"}      # 刻意不含 fb，见 spec §6.5
READ_RANGE = {"gg": "A:N", "tt": "A:M", "fb": "A:Q"}

ACCOUNT_KEY_FIELD = {"gg": "account_id", "tt": "advertiser_id", "fb": "account_id"}
```

把 `_PLAIN_TEXT_FIELDS` 改为（追加 fb）：

```python
_PLAIN_TEXT_FIELDS = {
    "gg": ("acquired_date", "timezone"),
    "tt": ("acquired_date", "country", "timezone", "consumption", "remark",
           "owner_change_note"),
    # FB 的文本列。注意不含 acceptor —— 那是定向写列，不参与「空值=清空」批量口径。
    "fb": ("acquired_date", "name", "unit_price", "inbound_qty", "outbound_date",
           "outbound_qty", "timezone", "consumption", "remark"),
}
```

- [ ] **Step 4: 新增 `_FB_ROW_SQL` 与三张映射表**

在 `_TT_ROW_SQL` 那一段**之后**、`collect_rows_for_push` **之前**插入：

```python
_FB_ROW_SQL = """
SELECT a.account_id, a.acquired_date, a.name, a.timezone, a.operator, a.acceptor,
       a.unit_price, a.inbound_qty, a.outbound_date, a.outbound_qty, a.consumption, a.remark,
       ch.name AS channel_name, at.name AS asset_type_name,
       bm.name AS primary_bm_name,
       COALESCE(NULLIF(u.display_name, ''), u.username, '') AS owner_name,
       s.name AS status_name
FROM fb_accounts a
LEFT JOIN fb_channels ch ON a.channel_id = ch.id
LEFT JOIN fb_asset_types at ON a.asset_type_id = at.id
LEFT JOIN fb_account_bm ab ON ab.account_id = a.id AND ab.is_primary = 1
LEFT JOIN fb_bms bm ON ab.bm_id = bm.id
LEFT JOIN users u ON a.owner_id = u.id
LEFT JOIN account_statuses s ON a.status_id = s.id
"""
# 主 BM 的 join **必须带 ab.is_primary = 1**：一个账户可挂多个 BM，
# 不加这个条件会让同一个账户产出多行，而 collect_rows_for_push 按行产 cells。

# 平台 → 业务表名。**刻意用字典查表而不是 `if platform == "tt" else ...`**：
# 后者的 else 会把未知平台静默导向 GG 表（accounts），是本子项目最大的回归风险。
_TABLE_FOR_PLATFORM = {"gg": "accounts", "tt": "tt_accounts", "fb": "fb_accounts"}

# 平台 → 系统→表 的行查询语句
_ROW_SQL = {"gg": _GG_ROW_SQL, "tt": _TT_ROW_SQL, "fb": _FB_ROW_SQL}
```

- [ ] **Step 5: 把 5 处二元表达式改成字典查表**

逐处替换（**用锚点定位，不要按行号**）：

**a)** `_resolve_field` 里带 `_SQL_AGENT_TT if platform == "tt" else _SQL_AGENT_GG` 的那行 →
本任务先保持 GG/TT 行为不变，加一行 FB 的占位分支（Task 2 填实）：

```python
    if field == "agent_name":
        # FB 的「所属渠道」不在 agents 表里（在 fb_channels），见 Task 2
        sql = _AGENT_SQL[platform]
        return True, resolve_named_id(db, sql, (value,))
```

并在 `_SQL_BC` 那一段附近加：

```python
# 平台 → 「所属渠道」的查名 SQL。FB 为 None：它不走 agents，由 Task 2 单独处理。
_AGENT_SQL = {"gg": _SQL_AGENT_GG, "tt": _SQL_AGENT_TT, "fb": None}
```

**b)** `build_diff` 里 `table = "tt_accounts" if platform == "tt" else "accounts"` →

```python
    table = _TABLE_FOR_PLATFORM[platform]
```

**c)** `apply_diff` 里同样那行 → 同样替换为 `table = _TABLE_FOR_PLATFORM[platform]`

**d)** `_apply_death` 里同样那行 → 同样替换为 `table = _TABLE_FOR_PLATFORM[platform]`
（Task 3 会在这函数开头加 FB 提前 return）

**e)** `collect_rows_for_push` 里 `sql = _TT_ROW_SQL if platform == "tt" else _GG_ROW_SQL` →

```python
    sql = _ROW_SQL[platform]
```

- [ ] **Step 6: 跑测试确认通过**

```bash
cd py && python -m pytest tests/test_fb_huguan_dashboard.py -q
```

Expected: PASS（Step 1 的全部用例）。

- [ ] **Step 7: re-baseline 4 条把 "fb" 钉成非法平台的既有用例**

`py/tests/test_huguan_dashboard.py` 里有 **4** 条用例断言 `"fb"` 是非法平台 ——
而本任务的目的正是让 fb 合法。**这是计划初稿的漏项**（Task 1 原先没认领这一步，实施时由
实现者发现）。它们不是 GG/TT 行为回归，是断言本身被本次改动作废。

逐条改，**保强度不变**：

| 用例 | 改法 |
|---|---|
| `test_parsed_key_name_is_normalized_to_account_id`（断言 `ACCOUNT_KEY_FIELD == {...}` 精确相等） | 期望字典补 `"fb": "account_id"` |
| `test_invalid_platform_rejected`（POST `platform="fb"` 期望 400） | `"fb"` → `"xx"`（仍非法的值） |
| `test_malformed_body_is_400_not_500`（循环含 `{"platform": "fb"}`） | 同上，`"fb"` → `"xx"` |
| `test_unknown_platform_falls_back_to_gg`（`for bad in ("fb", "xx", "")`） | 循环里去掉 `"fb"` |

> ⚠️ **另有一条也 POST `platform="fb"` 期望 400 的用例不要动** —— 它在 malformed-body
> 那一段附近，注释写着「必然先命中『未配置 → 400』」。那条 400 的原因是**未配置**而非平台非法，
> fb 变合法后它仍然是 400。动了反而错。

**改之前先确认该文件干净**：`git diff --stat py/tests/test_huguan_dashboard.py`
（本仓库有并行会话，该文件被多轮改过）。有未提交改动就停下来报告。

- [ ] **Step 8: 跑全量回归**

```bash
cd py && python -m pytest tests/ -q
```

Expected: 全绿（含 Step 7 改过的 4 条），总数 ≥ 开工时的基线。
**回归点**：GG/TT 行为必须逐字节不变 —— 除了那 4 条被本次改动作废的断言。

- [ ] **Step 9: 提交**

```bash
git add py/huguan_dashboard.py py/tests/test_fb_huguan_dashboard.py py/tests/test_huguan_dashboard.py
git commit -m "feat(fb): 户管看板扩到三平台：消除二元回落 + FB 列规格与行查询

- PLATFORMS 加 fb；5 处 'tt_accounts if platform == \"tt\" else accounts'
  改成 _TABLE_FOR_PLATFORM 字典查表（缺键 KeyError，不再静默回落 GG 表）
- _FB_ROW_SQL（主 BM 的 join 带 is_primary=1，否则多 BM 账户行数翻倍）
- COLUMN_SPEC['fb'] 17 列，I 列 (False, True) 不参与批量回写
- OWNER_CHANNEL_COL 刻意不含 fb"
```

---

## Task 2: FB 的名称解析与字段映射

**Files:**
- Modify: `py/huguan_dashboard.py`
- Test: `py/tests/test_fb_huguan_dashboard.py`（追加）

**Interfaces:**
- Consumes: Task 1 的 `COLUMN_SPEC["fb"]`、`_AGENT_SQL`
- Produces:
  - `_SQL_CHANNEL = "SELECT id FROM fb_channels WHERE name=? AND platform='fb'"`
  - `_SQL_ASSET_TYPE = "SELECT id FROM fb_asset_types WHERE name=? AND platform='fb'"`
  - `_resolve_field` 认 `channel_name` / `asset_type_name`
  - `_target_column` 认 `channel_name → channel_id`、`asset_type_name → asset_type_id`
  - `_parseable_fields` 按平台返回，FB 为 `("channel_name", "asset_type_name", "status_name")`

- [ ] **Step 1: 写失败测试**

追加到 `py/tests/test_fb_huguan_dashboard.py`：

```python
class TestFbNameResolution:
    @pytest.fixture
    def fb_seed(self, client):
        """一个 FB 用户 + 一条渠道 + 一条资产类型。"""
        db = database.get_db()
        db.execute("INSERT INTO users(username, password, role, platform) "
                   "VALUES('fb_res', 'x', 'user', 'fb')")
        uid = db.execute("SELECT last_insert_rowid()").fetchone()[0]
        db.execute("INSERT INTO fb_channels(name, owner_id, platform) VALUES('渠道甲', ?, 'fb')",
                   (uid,))
        ch = db.execute("SELECT last_insert_rowid()").fetchone()[0]
        db.execute("INSERT INTO fb_asset_types(name, owner_id, platform) VALUES('类型乙', ?, 'fb')",
                   (uid,))
        at = db.execute("SELECT last_insert_rowid()").fetchone()[0]
        db.commit()
        db.close()
        return {"uid": uid, "channel_id": ch, "asset_type_id": at}

    def test_resolves_channel_name(self, client, fb_seed):
        db = database.get_db()
        known, resolved = hd._resolve_field(db, "fb", "channel_name", "渠道甲")
        db.close()
        assert known is True
        assert resolved == fb_seed["channel_id"]

    def test_resolves_asset_type_name(self, client, fb_seed):
        db = database.get_db()
        known, resolved = hd._resolve_field(db, "fb", "asset_type_name", "类型乙")
        db.close()
        assert known is True
        assert resolved == fb_seed["asset_type_id"]

    def test_unknown_channel_gives_none_not_warning_lookup(self, client, fb_seed):
        """查不到 → resolved is None（调用方记 warning），不是歧义档。"""
        db = database.get_db()
        known, resolved = hd._resolve_field(db, "fb", "channel_name", "不存在的渠道")
        db.close()
        assert known is True and resolved is None

    def test_target_column_mapping(self):
        assert hd._target_column("fb", "channel_name") == "channel_id"
        assert hd._target_column("fb", "asset_type_name") == "asset_type_id"

    def test_parseable_fields_fb(self):
        assert hd._parseable_fields("fb") == ("channel_name", "asset_type_name", "status_name")

    def test_parseable_fields_gg_tt_unchanged(self):
        """回归点：GG / TT 的可解析字段集不得变化。"""
        assert hd._parseable_fields("gg") == ("mcc_name", "agent_name", "bc_name", "status_name")
        assert hd._parseable_fields("tt") == ("mcc_name", "agent_name", "bc_name", "status_name")
```

- [ ] **Step 2: 跑测试确认失败**

```bash
cd py && python -m pytest tests/test_fb_huguan_dashboard.py -q -k FbNameResolution
```

Expected: FAIL —— `_resolve_field` 对 `channel_name` 返回 `(False, None)`。

- [ ] **Step 3: 实现**

在 `_SQL_BC` 那一段**之后**追加：

```python
# FB 的两个公用词表（子项目 ① §4.2）。唯一约束都是 (name, platform)，
# 因此**至多命中 1 行**，不存在「命中 ≥2 条」的歧义档 —— 与 status_name 同档。
_SQL_CHANNEL = "SELECT id FROM fb_channels WHERE name=? AND platform='fb'"
_SQL_ASSET_TYPE = "SELECT id FROM fb_asset_types WHERE name=? AND platform='fb'"
```

把 `_resolve_field` 改为（保留既有 mcc/bc 分支不动，替换 agent 分支并新增两个）：

```python
def _resolve_field(db, platform: str, field: str, value: str):
    """（docstring 保持原样，不修改）"""
    if field == "mcc_name":
        return True, resolve_named_id(db, _SQL_MCC, (value,))
    if field == "agent_name":
        sql = _AGENT_SQL[platform]
        if sql is None:
            # FB 的「所属渠道」不在 agents 表里，走 fb_channels（见下方独立分支）
            return False, None
        return True, resolve_named_id(db, sql, (value,))
    if field == "bc_name":
        return True, resolve_named_id(db, _SQL_BC, (value,))
    # FB 专有：所属渠道 / 资产类型
    if field == "channel_name":
        return True, resolve_named_id(db, _SQL_CHANNEL, (value,))
    if field == "asset_type_name":
        return True, resolve_named_id(db, _SQL_ASSET_TYPE, (value,))
    return False, None
```

把 `_parseable_fields` 改为：

```python
# 各平台可读且需要名称解析的字段。FB 没有 MCC / BC，改为两个公用词表。
_PARSEABLE_FIELDS = {
    "gg": ("mcc_name", "agent_name", "bc_name", "status_name"),
    "tt": ("mcc_name", "agent_name", "bc_name", "status_name"),
    "fb": ("channel_name", "asset_type_name", "status_name"),
}


def _parseable_fields(platform: str) -> tuple:
    """该平台可读且需要名称解析的字段（值非空时才解析）。"""
    return _PARSEABLE_FIELDS[platform]
```

把 `_target_column` 的返回字典改为：

```python
    return {
        "mcc_name": "mcc_id",
        "agent_name": "agent_id",
        "bc_name": "bc_id",
        "status_name": "status_id",
        "channel_name": "channel_id",
        "asset_type_name": "asset_type_id",
    }[field]
```

- [ ] **Step 4: 跑测试确认通过**

```bash
cd py && python -m pytest tests/test_fb_huguan_dashboard.py -q
```

Expected: PASS。

- [ ] **Step 5: 跑全量回归并提交**

```bash
cd py && python -m pytest tests/ -q
git add py/huguan_dashboard.py py/tests/test_fb_huguan_dashboard.py
git commit -m "feat(fb): FB 的所属渠道 / 资产类型名称解析

_resolve_field 新增 channel_name / asset_type_name 两个分支，
走 fb_channels / fb_asset_types（UNIQUE(name, platform) ⇒ 至多命中 1 行，无歧义档）。
_parseable_fields 改为按平台查表，GG/TT 的字段集不变。"
```

---

## Task 3: `_apply_death` 对 FB 跳过

**Files:**
- Modify: `py/huguan_dashboard.py`
- Test: `py/tests/test_fb_huguan_dashboard.py`（追加）

**Interfaces:**
- Consumes: Task 1 的 `_TABLE_FOR_PLATFORM`
- Produces: `_apply_death` 对 `platform="fb"` 是 no-op

- [ ] **Step 1: 写失败测试**

```python
class TestFbApplyDeathIsNoop:
    def test_death_does_not_touch_fb_accounts(self, client):
        """fb_accounts 没有 death_date 列 —— 走到这里会 OperationalError。

        这条是防回归的关键断言：FB 分支忘记 return 会让整批同步挂掉，
        而不是静默出错，所以必须有一个用例钉住「调用不抛异常且不改任何列」。
        """
        db = database.get_db()
        db.execute("INSERT INTO users(username, password, role, platform) "
                   "VALUES('fb_d', 'x', 'user', 'fb')")
        uid = db.execute("SELECT last_insert_rowid()").fetchone()[0]
        db.execute("INSERT INTO fb_accounts(name, account_id, owner_id) VALUES('户', 'DE-1', ?)",
                   (uid,))
        pk = db.execute("SELECT last_insert_rowid()").fetchone()[0]
        db.commit()
        before = dict(db.execute("SELECT * FROM fb_accounts WHERE id=?", (pk,)).fetchone())
        # 两个方向都不能抛异常（走到 UPDATE death_date 就会 OperationalError）
        hd._apply_death(db, "fb", pk, True)
        hd._apply_death(db, "fb", pk, False)
        db.commit()
        after = dict(db.execute("SELECT * FROM fb_accounts WHERE id=?", (pk,)).fetchone())
        db.close()
        # 真的什么都没改 —— 不只是「没崩」
        assert after == before

    def test_gg_apply_death_still_works(self, client):
        """回归点：GG / TT 的死亡标记行为不变。"""
        db = database.get_db()
        db.execute("INSERT INTO users(username, password, role, platform) "
                   "VALUES('gg_d', 'x', 'user', 'gg')")
        uid = db.execute("SELECT last_insert_rowid()").fetchone()[0]
        db.execute("INSERT INTO accounts(name, account_id, owner_id) VALUES('户', 'GD-1', ?)",
                   (uid,))
        pk = db.execute("SELECT last_insert_rowid()").fetchone()[0]
        db.commit()
        hd._apply_death(db, "gg", pk, True)
        db.commit()
        row = db.execute("SELECT death_date, status_changed_date FROM accounts WHERE id=?",
                         (pk,)).fetchone()
        db.close()
        assert row["death_date"] != ""
        assert row["status_changed_date"] != ""
```

- [ ] **Step 2: 跑测试确认失败**

```bash
cd py && python -m pytest tests/test_fb_huguan_dashboard.py -q -k ApplyDeath
```

Expected: FAIL —— `sqlite3.OperationalError: no such column: death_date`。

- [ ] **Step 3: 实现**

在 `_apply_death` 函数体**第一行**（`table = ...` 之前）插入：

```python
    # FB 没有 death_date 列（子项目 ① 已确认），生死完全由状态列承载 ——
    # is_dead() 对 FB 只看 status_name == "死亡"，落库时已经通过 status_id 表达。
    # 这里必须直接返回：继续走下去会 UPDATE 一个不存在的列，整批同步报错。
    if platform == "fb":
        return
```

- [ ] **Step 4: 跑测试确认通过**

```bash
cd py && python -m pytest tests/test_fb_huguan_dashboard.py -q
```

Expected: PASS。

- [ ] **Step 5: 跑全量回归并提交**

```bash
cd py && python -m pytest tests/ -q
git add py/huguan_dashboard.py py/tests/test_fb_huguan_dashboard.py
git commit -m "fix(fb): _apply_death 对 FB 直接返回

fb_accounts 没有 death_date 列，不 return 会 OperationalError 让整批同步挂掉。
FB 的生死由状态列（O 列）承载。"
```

---

## Task 4: 「位置」列 = 主 BM 的读写与留痕

**Files:**
- Modify: `py/huguan_dashboard.py`
- Test: `py/tests/test_fb_huguan_dashboard.py`（追加）

**Interfaces:**
- Consumes: Task 1 的 `COLUMN_SPEC["fb"]`（P 列 `primary_bm_name`）、`_FB_ROW_SQL`
- Produces: 两个模块级函数
  - `_set_primary_bm(db, acc_pk: int, bm_id: int) -> None` —— 换主 BM，先清后设，不 commit
  - `_record_bm_change(db, acc_pk: int, old_bm_id, new_bm_id, changed_by: int) -> None` —— 写 `fb_account_bm_history`，值没变不写，不 commit

> **重复说明**：`py/routes/fb_routes.py` 已有一个 `_set_primary_bm`（子项目 ① Task 3）。本任务是**纯逻辑层**的对应实现，供 `apply_diff` 使用 —— 逻辑层刻意不 import flask / routes，所以不能复用那个。两处实现必须保持同一契约（先清后设）。

- [ ] **Step 1: 写失败测试**

```python
class TestFbPrimaryBmSync:
    @pytest.fixture
    def fb_bm_seed(self, client):
        db = database.get_db()
        db.execute("INSERT INTO users(username, password, role, platform) "
                   "VALUES('fb_bm', 'x', 'user', 'fb')")
        uid = db.execute("SELECT last_insert_rowid()").fetchone()[0]
        ids = []
        for nm, bid in (("BM一", "b1"), ("BM二", "b2")):
            db.execute("INSERT INTO fb_bms(name, bm_id, owner_id) VALUES(?,?,?)", (nm, bid, uid))
            ids.append(db.execute("SELECT last_insert_rowid()").fetchone()[0])
        db.execute("INSERT INTO fb_accounts(name, account_id, owner_id) VALUES('户', 'BM-1', ?)",
                   (uid,))
        acc = db.execute("SELECT last_insert_rowid()").fetchone()[0]
        db.commit()
        db.close()
        return {"uid": uid, "bm1": ids[0], "bm2": ids[1], "acc": acc}

    def test_set_primary_bm_switches(self, client, fb_bm_seed):
        s = fb_bm_seed
        db = database.get_db()
        hd._set_primary_bm(db, s["acc"], s["bm1"])
        db.commit()
        hd._set_primary_bm(db, s["acc"], s["bm2"])   # 换 BM
        db.commit()
        row = db.execute("SELECT bm_id FROM fb_account_bm WHERE account_id=? AND is_primary=1",
                         (s["acc"],)).fetchone()
        db.close()
        assert row["bm_id"] == s["bm2"]

    def test_record_bm_change_writes_history(self, client, fb_bm_seed):
        s = fb_bm_seed
        db = database.get_db()
        hd._record_bm_change(db, s["acc"], None, s["bm1"], s["uid"])
        db.commit()
        row = db.execute("SELECT old_bm_id, new_bm_id, changed_by FROM fb_account_bm_history "
                         "WHERE account_id=?", (s["acc"],)).fetchone()
        db.close()
        assert row["old_bm_id"] is None and row["new_bm_id"] == s["bm1"]

    def test_record_bm_change_skips_when_unchanged(self, client, fb_bm_seed):
        """值没变不写历史 —— 否则历史面板会被 A→A 刷屏。"""
        s = fb_bm_seed
        db = database.get_db()
        hd._record_bm_change(db, s["acc"], s["bm1"], s["bm1"], s["uid"])
        db.commit()
        n = db.execute("SELECT COUNT(*) FROM fb_account_bm_history WHERE account_id=?",
                       (s["acc"],)).fetchone()[0]
        db.close()
        assert n == 0

    def test_record_bm_change_skips_without_changed_by(self, client, fb_bm_seed):
        """changed_by REFERENCES users(id)，写 None 会撞 FK —— 宁可漏记。"""
        s = fb_bm_seed
        db = database.get_db()
        hd._record_bm_change(db, s["acc"], None, s["bm1"], 0)
        db.commit()
        n = db.execute("SELECT COUNT(*) FROM fb_account_bm_history WHERE account_id=?",
                       (s["acc"],)).fetchone()[0]
        db.close()
        assert n == 0
```

- [ ] **Step 2: 跑测试确认失败**

```bash
cd py && python -m pytest tests/test_fb_huguan_dashboard.py -q -k FbPrimaryBmSync
```

Expected: FAIL —— `AttributeError: module 'huguan_dashboard' has no attribute '_set_primary_bm'`。

- [ ] **Step 3: 实现**

在 `_apply_death` **之前**插入：

```python
def _set_primary_bm(db, acc_pk: int, bm_id: int) -> None:
    """把某账户的主 BM 换成 bm_id。**不 commit**，事务边界由调用方负责。

    ⚠️ **必须先清后设，顺序不能反。** `idx_fb_account_bm_primary` 是
    `WHERE is_primary = 1` 的部分唯一索引（子项目 ① §4.3）。SQLite 的唯一索引是
    **逐语句**检查的，先设新的（此刻旧的主 BM 还是 1）会立刻 UNIQUE constraint failed。
    """
    db.execute("UPDATE fb_account_bm SET is_primary=0 WHERE account_id=?", (acc_pk,))
    cur = db.execute("UPDATE fb_account_bm SET is_primary=1 WHERE account_id=? AND bm_id=?",
                     (acc_pk, bm_id))
    if cur.rowcount == 0:
        db.execute("INSERT INTO fb_account_bm(account_id, bm_id, is_primary) VALUES(?,?,1)",
                   (acc_pk, bm_id))


def _norm_ref_id(value):
    """外键列的空值归一：0 / "0" / 空串 / None 一律算「没挂」。"""
    if value is None:
        return None
    if isinstance(value, str) and not value.strip():
        return None
    if value == 0 or value == "0":
        return None
    return value


def _record_bm_change(db, acc_pk: int, old_bm_id, new_bm_id, changed_by: int) -> None:
    """主 BM 真变了才写一行 `fb_account_bm_history`。**不 commit**。

    与 GG 的 `account_mcc_history` / TT 的 `tt_account_bc_history` 同契约：
    任何 MCC / BC 变更都要留痕，FB 的对应物是 BM。`change_type` 取既有的 `batch`
    （表驱动的一批账户改列，与 main.py 的批量修改同档）。

    changed_by 为假值时不写：该列 `REFERENCES users(id)`，写 None/0 会撞 FK 或
    记出一行无主历史，宁可漏记也不能写坏（同 `_insert_channel_history` 的口径）。
    """
    old_val = _norm_ref_id(old_bm_id)
    new_val = _norm_ref_id(new_bm_id)
    if old_val == new_val:
        return
    if not changed_by:
        log.warning("FB 主 BM 变更但缺少 changed_by，跳过历史记录 acc=%s", acc_pk)
        return
    db.execute("INSERT INTO fb_account_bm_history"
               "(account_id, old_bm_id, new_bm_id, changed_by, change_type) "
               "VALUES(?,?,?,?,?)", (acc_pk, old_val, new_val, changed_by, "batch"))
```

> **注意**：模块里**已有一个 `_norm_ref_id`**（`_CHANNEL_HISTORY_SPEC` 那一节）。先确认它存在再决定：若已存在**不要重复定义**，直接复用；只有不存在时才把上面那段加进去。同样地，`log` 已在模块顶部定义。

- [ ] **Step 4: 接入 `build_diff` 与 `apply_diff`**

**4a) 读回（表 → 系统）**：在 `_collect_updates` 里，`_PLAIN_TEXT_FIELDS` 之后，为 FB 增加主 BM 的解析。在 `_collect_updates` 的 `for f in _parseable_fields(platform):` 循环**之前**插入：

```python
    # FB 的「位置」列：BM 名 → 主 BM。它不是普通外键列（主 BM 存在中间表上），
    # 所以不能走 _resolve_field / _target_column 那条通用路径。
    if platform == "fb":
        bm_name = (p.get("primary_bm_name") or "").strip()
        if bm_name:
            out["_primary_bm_name"] = bm_name
```

**4b) 落库（`apply_diff` 的 `to_create` 分支）**：在 `_record_channel_assign(...)` 调用**之后**加：

```python
            if platform == "fb":
                bm_name = src.pop("_primary_bm_name", None)
                if bm_name:
                    bid = resolve_named_id(
                        db, "SELECT id FROM fb_bms WHERE name=? AND deleted_at IS NULL",
                        (bm_name,))
                    if bid:
                        _set_primary_bm(db, new_id, bid)
                        _record_bm_change(db, new_id, None, bid, user_id)
```

> **注意**：`src` 是 `dict(item.get("db_values"))` 的副本，`_primary_bm_name` 是合成键不是数据库列 —— 必须 pop 掉，否则会拼进 INSERT 的列清单。

**4c) 落库（`apply_diff` 的 `to_update` 分支）**：在 `_record_channel_change(...)` 调用**之后**、`db.execute(f"UPDATE {table} SET ...")` **之前**加：

```python
            if platform == "fb":
                new_bm_name = fields.pop("_primary_bm_name", None)
                if new_bm_name is not None:
                    old = db.execute(
                        "SELECT b.bm_id FROM fb_account_bm ab JOIN fb_bms b ON ab.bm_id=b.id "
                        "WHERE ab.account_id=? AND ab.is_primary=1",
                        (item["existing_id"],)).fetchone()
                    bid = resolve_named_id(
                        db, "SELECT id FROM fb_bms WHERE name=? AND deleted_at IS NULL",
                        (new_bm_name,)) if new_bm_name else None
                    if new_bm_name and bid is None:
                        warnings.append({"row": item["row"],
                                         "message": f"位置「{new_bm_name}」无法唯一匹配，已跳过"})
                    else:
                        _set_primary_bm(db, item["existing_id"], bid) if bid else \
                            db.execute("UPDATE fb_account_bm SET is_primary=0 WHERE account_id=?",
                                       (item["existing_id"],))
                        _record_bm_change(db, item["existing_id"],
                                          old["bm_id"] if old else None, bid, user_id)
```

> **`fields.pop` 必须在拼 `sets` 之前**：`_primary_bm_name` 不是数据库列，留在 `fields` 里会拼进 `UPDATE ... SET _primary_bm_name=?` 直接报错。
>
> **空值语义**：表里「位置」空着 → `new_bm_name` 为空串（不是 None），走 `else` 分支只清主 BM 标记、**不删**任何关联行（spec §6.3）。

**4d) `_blank_columns` 不认这个合成键**：`_PLAIN_TEXT_FIELDS["fb"]` 里没有 `_primary_bm_name`，所以它天然不会被算进「将清空」清单 —— 这是对的，BM 的清除不在那个口径内。无需改动。

- [ ] **Step 5: 跑测试确认通过**

```bash
cd py && python -m pytest tests/test_fb_huguan_dashboard.py -q
```

Expected: PASS。

- [ ] **Step 6: 跑全量回归并提交**

```bash
cd py && python -m pytest tests/ -q
git add py/huguan_dashboard.py py/tests/test_fb_huguan_dashboard.py
git commit -m "feat(fb): 位置列 = 主 BM 的读写与留痕

_set_primary_bm（先清后设）+ _record_bm_change（写 fb_account_bm_history）。
表里填 BM 名 → 换主 BM；空着 → 只清标记不删关联。留痕走 batch 档。"
```

---

## Task 5: 归属协议 + 子项目 ① 的 `acceptor` 修订

**Files:**
- Modify: `py/database.py`（补 `acceptor` 列）
- Modify: `py/huguan_dashboard.py`（接户运营的写点）
- Modify: `py/routes/fb_routes.py`（create/update 改读写 `acceptor`）
- Modify: `frontend/src/views/fb/FbAccountPanel.vue`（接户运营改文本输入）
- Test: `py/tests/test_fb_huguan_dashboard.py`（追加）

**Interfaces:**
- Consumes: 无（本任务定义）
- Produces:
  - `fb_accounts.acceptor TEXT DEFAULT ''`（新列）
  - `_fb_acceptor_cells(rows: list, value: str) -> list` —— 构造只写 I 列的 rows
  - `_fb_owner_transition(old_name: str, new_name: str) -> str` —— 拼 `"{旧}转{新}"`

- [ ] **Step 1: 写失败测试**

```python
class TestFbAcceptor:
    def test_column_exists_and_defaults_empty(self, client):
        db = database.get_db()
        cols = {r[1]: r[2] for r in db.execute("PRAGMA table_info(fb_accounts)").fetchall()}
        db.close()
        assert "acceptor" in cols
        assert cols["acceptor"] == "TEXT"

    def test_owner_transition_format(self):
        assert hd._fb_owner_transition("张三", "李四") == "张三转李四"

    def test_owner_transition_handles_empty_old(self):
        """首任（没有旧归属）不该拼出「转李四」。"""
        assert hd._fb_owner_transition("", "李四") == "李四"

    def test_acceptor_cells_only_contains_column_i(self):
        rows = [{"account_id": "A1"}, {"account_id": "A2"}]
        cells = hd._fb_acceptor_cells(rows, "张三转李四")
        assert cells == [{"account_id": "A1", "cells": {"I": "张三转李四"}},
                         {"account_id": "A2", "cells": {"I": "张三转李四"}}]

    def test_acceptor_is_read_back_verbatim(self, client):
        """接户运营双向：表里的串原样落进 acceptor，不做名称解析、不出警告。"""
        db = database.get_db()
        db.execute("INSERT INTO users(username, password, role, platform) "
                   "VALUES('fb_acc', 'x', 'user', 'fb')")
        db.commit()
        db.close()
        values = [""] * 17
        values[hd.col_index("D")] = "AC-1"
        values[hd.col_index("I")] = "张三转李四"
        parsed = hd.parse_row(values, "fb")
        assert parsed["acceptor"] == "张三转李四"
        assert "_owner_channel" not in parsed
```

- [ ] **Step 2: 跑测试确认失败**

```bash
cd py && python -m pytest tests/test_fb_huguan_dashboard.py -q -k FbAcceptor
```

Expected: FAIL —— `acceptor` 列不存在 / 函数未定义。

- [ ] **Step 3: 补 `acceptor` 列**

在 `py/database.py` 的 `_ensure_columns` 里，`_add_column_if_missing(conn, "fb_accounts", "remark", ...)` 那一行**之后**插入：

```python
    # FB 的「接户运营」＝归属变更记录（"{旧}转{新}"），用户 2026-10-06 定为一格放整串、
    # 且双向。外键装不下复合串，所以是 TEXT。
    # ⚠️ 子项目 ① 曾加过 `acceptor_id INTEGER REFERENCES users(id)`，该列**已废弃**、
    # 本处刻意**不删**（SQLite 的 DROP COLUMN 与 _add_column_if_missing 的幂等语义
    # 相冲，删了下次连库又会被补回来）。读写一律走 acceptor，acceptor_id 不再有任何引用。
    _add_column_if_missing(conn, "fb_accounts", "acceptor", "acceptor TEXT DEFAULT ''")
```

- [ ] **Step 4: 实现两个辅助函数**

在 `_set_primary_bm` **之前**插入：

```python
def _fb_owner_transition(old_name: str, new_name: str) -> str:
    """拼 FB 的换绑记录：`"{旧}转{新}"`。

    没有旧归属（首任）时只返回新名 —— 否则会拼出「转李四」这种半截串，
    户管在表里读不出是谁转给李四的。
    """
    old_name = (old_name or "").strip()
    new_name = (new_name or "").strip()
    if not old_name:
        return new_name
    return f"{old_name}转{new_name}"


def _fb_acceptor_cells(rows: list, value: str) -> list:
    """构造只写 I 列（接户运营）的 rows。

    刻意只含这一列 —— 与 `owner_channel_cells` 同一理由：收尾写入若顺手带上别的列，
    就会把户管在表里的其他手工改动一起冲掉。
    """
    return [{"account_id": r["account_id"], "cells": {"I": value}} for r in rows]
```

- [ ] **Step 5: 改 `fb_routes.py` 读写 `acceptor`**

`create_account`：把 `acceptor_id = data.get('acceptor_id') or None` 改为

```python
    acceptor = (data.get('acceptor') or '').strip()
```

并把 INSERT 的列清单里的 `acceptor_id` 改成 `acceptor`、绑定值同步替换（值用 `acceptor` 变量）。

`update_account`：同样把 `acceptor_id = data.get('acceptor_id') or None` 改为

```python
    acceptor = (data.get('acceptor') or '').strip()
```

并把 UPDATE 的列清单与绑定值里的 `acceptor_id` 改成 `acceptor`。

- [ ] **Step 6: 前端「接户运营」改文本输入**

在 `frontend/src/views/fb/FbAccountPanel.vue`：把 `acceptor_id` 相关的 `<el-select>` 换成

```vue
        <el-form-item label="接户运营">
          <el-input v-model="form.acceptor" placeholder="如：张三转李四" />
        </el-form-item>
```

并把 `form` 的键 `acceptor_id:null` 改为 `acceptor:''`（`reactive` 初始化、`openCreate`、`openEdit` 三处同步改）。

- [ ] **Step 7: 跑测试确认通过**

```bash
cd py && python -m pytest tests/test_fb_huguan_dashboard.py -q
```

Expected: PASS。

- [ ] **Step 8: 跑全量回归 + 前端构建并提交**

```bash
cd py && python -m pytest tests/ -q
cd ../frontend && npm run build
git add py/database.py py/huguan_dashboard.py py/routes/fb_routes.py frontend/src/views/fb/FbAccountPanel.vue py/tests/test_fb_huguan_dashboard.py
git commit -m "feat(fb): 接户运营改文本列 + 归属协议辅助函数

- fb_accounts 新增 acceptor TEXT（acceptor_id 废弃但保留，避免删了又补的陷阱）
- _fb_owner_transition 拼 '{旧}转{新}'，首任不拼半截串
- _fb_acceptor_cells 只写 I 列
- fb_routes 的 create/update 改读写 acceptor；前端改文本输入"
```

---

## Task 6: 接上写表触发点 + 前端看板卡片

**Files:**
- Modify: `py/routes/fb_routes.py`
- Modify: `py/routes/huguan_dashboard_routes.py`
- Modify: `frontend/src/components/HuguanDashboardCard.vue`
- Modify: `frontend/src/views/fb/FbSettingsPanel.vue`
- Test: `py/tests/test_fb_huguan_dashboard.py`（追加）

**Interfaces:**
- Consumes: Task 1–5 的全部产物
- Produces: FB 三个端点的写表副作用

- [ ] **Step 1: 写失败测试**

```python
class TestFbWritebackTriggers:
    """FB 端点必须触发户管看板回写；软删 / 恢复 / 永久删不触发。"""

    def test_create_triggers_writeback(self, client, monkeypatch):
        calls = []
        monkeypatch.setattr(hd, "writeback_rows",
                            lambda uid, plat, ids=None: calls.append((plat, ids)))
        # 用真实端点建一个账户
        db = database.get_db()
        db.execute("INSERT INTO users(username, password, role, platform) "
                   "VALUES('fb_wb', 'test123', 'huguan', 'fb')")
        db.commit()
        db.close()
        token = client.post("/api/auth/login",
                            json={"username": "fb_wb", "password": "test123"}
                            ).get_json()["access_token"]
        h = {"Authorization": f"Bearer {token}"}
        r = client.post("/api/fb/accounts/create", headers=h,
                        json={"name": "户wb", "account_id": "WB-1"})
        assert r.status_code == 200
        assert any(plat == "fb" for plat, _ in calls)

    def test_soft_delete_does_not_trigger(self, client, monkeypatch):
        calls = []
        monkeypatch.setattr(hd, "writeback_rows",
                            lambda uid, plat, ids=None: calls.append((plat, ids)))
        db = database.get_db()
        db.execute("INSERT INTO users(username, password, role, platform) "
                   "VALUES('fb_wb2', 'test123', 'huguan', 'fb')")
        uid = db.execute("SELECT last_insert_rowid()").fetchone()[0]
        db.execute("INSERT INTO fb_accounts(name, account_id, owner_id) VALUES('户','WB-2',?)",
                   (uid,))
        aid = db.execute("SELECT last_insert_rowid()").fetchone()[0]
        db.commit()
        db.close()
        token = client.post("/api/auth/login",
                            json={"username": "fb_wb2", "password": "test123"}
                            ).get_json()["access_token"]
        h = {"Authorization": f"Bearer {token}"}
        client.delete(f"/api/fb/accounts/{aid}", headers=h)
        assert calls == []
```

- [ ] **Step 2: 跑测试确认失败**

```bash
cd py && python -m pytest tests/test_fb_huguan_dashboard.py -q -k WritebackTriggers
```

Expected: FAIL —— `calls` 为空。

- [ ] **Step 3: 在 `fb_routes.py` 接上三个触发点**

文件顶部加 `import huguan_dashboard as hd`（若尚无）。

`create_account`：在 `db.commit()` **之后**、`return ok(...)` **之前**加

```python
        hd.writeback_rows(uid, "fb", [account_id])
```

`update_account`：在 `db.commit()` **之后**加

```python
    _row = db.execute("SELECT account_id FROM fb_accounts WHERE id=?", (aid,)).fetchone()
    if _row:
        hd.writeback_rows(uid, "fb", [_row["account_id"]])
```

> `update_account` 目前没有 `uid` 变量（它没调 `get_uid()`）—— 需要在函数开头补 `uid = get_uid()`。

`reassign_account`：在 `db.commit()` **之后**加

```python
    # 规格 §8：归属变了 → 刷该行可写列 + 定向写「接户运营」记录
    hd.writeback_rows(uid, "fb", [existing["account_id"]])
    _old_name = existing["display_name"] or existing["username"] or ""
    _new_name = (t["display_name"] or t["username"] or "") if t else ""
    hd.writeback_fb_acceptor(uid, "fb", existing["account_id"],
                             _fb_owner_transition(_old_name, _new_name))
```

> `t` 是 `reassign_account` 里已有的目标用户查询结果（跨用户分支）。**单用户分支**（`target_owner == uid`）没有 `t` —— 那条分支上归属没变（本来就属于自己），不会走到这里（前面已 409 拦截）。确认一下再落笔。

- [ ] **Step 4: 新增 `writeback_fb_acceptor`**

在 `py/huguan_dashboard.py` 里，紧跟 `writeback_owner_channel` **之后**插入（**复制该函数的形状**，只换写入内容与列）：

```python
def writeback_fb_acceptor(user_id, platform, account_id, note):
    """把 FB 的换绑记录（"{旧}转{新}"）定向写进表里的 I 列。

    与 `writeback_owner_channel` 同形但**语义不同**：那个写的是「新归属名」，
    这个写的是「旧转新」整串（spec §6.5）。因此刻意不复用 `OWNER_CHANNEL_COL`
    （它不含 fb 键，硬塞会 KeyError）。

    绝不抛异常（理由同 `writeback_rows`）。
    """
    try:
        db = _open_db()
        try:
            conf = get_platform_config(db, user_id, platform)
            if not conf["spreadsheet_id"] or not conf["sheet_name"]:
                return
        finally:
            db.close()
        if not (note or "").strip():
            return
        rows = _fb_acceptor_cells([{"account_id": account_id}], note)

        def _do():
            import google_sheets_service as gs
            from main import _GOOGLE_SHEETS_CONFIG
            service = gs.build_service(_GOOGLE_SHEETS_CONFIG["credentials_path"])
            gs.update_rows_by_account_id(service, conf["spreadsheet_id"],
                                         conf["sheet_name"], rows)

        from main import _sync_sheets_background
        _sync_sheets_background(
            _do, lambda s, e: log.warning("FB 接户运营回写失败: %s", e) if e else None)
    except Exception as e:
        log.warning("FB 接户运营回写触发失败: %s", e)
```

- [ ] **Step 5: 归属变更时同步写 `acceptor`（表 → 系统方向）**

在 `apply_diff` 的 `owner_changes` 分支里，`db.execute(f"UPDATE {table} SET owner_id=?...")` **之后**加：

```python
            if platform == "fb":
                # 换绑记录：旧名 → 新名（spec §6.4 写点 3）
                old_name = item.get("from") or ""
                new_name = item.get("to") or ""
                db.execute("UPDATE fb_accounts SET acceptor=? WHERE id=?",
                           (_fb_owner_transition(old_name, new_name), item["existing_id"]))
```

同时在路由收尾（`huguan_dashboard_routes.py` 的 `dashboard_sync`）里，对 `applied` 的行**追加**一次 FB 定向回写。在既有 `_write_background(conf, hd.owner_channel_cells(applied, platform, ""))` 那一行**之后**加：

```python
            if platform == "fb":
                # FB 没有通道列可清；改为把换绑记录定向写进 I 列。
                # 注意 _fb_acceptor_cells 的签名是 (rows, value)，value 是**同一个串**
                # 写给所有行 —— 而这里每行的串不同，所以不能用它，直接构造 rows。
                _write_background(conf, [
                    {"account_id": r["account_id"],
                     "cells": {"I": hd._fb_owner_transition(r.get("from", ""), r["to"])}}
                    for r in applied])
```

> `applied` 的元素来自 `apply_diff` 的 `applied_owner_rows`，当前只有 `account_id` 与 `to`。**`from` 需要在 `apply_diff` 里一并带上** —— 在 `applied_owner_rows.append({...})` 处补 `"from": item.get("from", "")`。这是本步骤的前置改动，别漏。

- [ ] **Step 6: 前端卡片**

`frontend/src/components/HuguanDashboardCard.vue`：
- `props.platform` 的 validator 从 `['gg','tt']` 改为 `['gg','tt','fb']`
- `VIA_LABELS` / `FIELD_LABELS` / `WARN_TOKENS` / `PUSH_COVER` / `PUSH_SAFE` / `PUSH_SAFE_NOTE` / `PUSH_EXTRA_NOTE` / `OWNER_WRITEBACK_TEXT` 各补 `fb` 条目，**照抄下面这段**：

```js
// VIA_LABELS：FB 没有通道列，变更来源恒为「在用运营」列
fb: { owner_name: '在用运营' },

// FIELD_LABELS：FB 的字段名 → 表头（_is_dead 是合成键，_collect_updates 无条件放进去）
fb: {
  acquired_date: '日期', name: '账户名称',
  channel_id: '所属渠道', asset_type_id: '资产类型',
  unit_price: '单价', inbound_qty: '入库',
  outbound_date: '出库时间', outbound_qty: '出库',
  timezone: '时区', consumption: '消耗', remark: '产品信息',
  status_id: '状态', _primary_bm_name: '位置',
  _is_dead: '死亡',
},

// WARN_TOKENS：后端 warnings[].message 会夹带英文字段名
// （FB 用 channel_name / asset_type_name，不是 agent_name / bc_name）
fb: { channel_name: '所属渠道', asset_type_name: '资产类型', status_name: '状态' },

// PUSH_COVER：会被批量覆盖、且户管可能手改过的列
fb: [
  { col: 'C 列',  head: '账户名称', to: '系统里的「账户名称」' },
  { col: 'E 列',  head: '所属渠道', to: '系统里的「所属渠道」' },
  { col: 'F 列',  head: '资产类型', to: '系统里的「资产类型」' },
  { col: 'G 列',  head: '单价',     to: '系统里的「单价」' },
  { col: 'H 列',  head: '入库',     to: '系统里的「入库」' },
  { col: 'J 列',  head: '在用运营', to: '系统里的「归属人」' },
  { col: 'K 列',  head: '出库时间', to: '系统里的「出库时间」' },
  { col: 'L 列',  head: '出库',     to: '系统里的「出库」' },
  { col: 'M 列',  head: '时区',     to: '系统里的「时区」' },
  { col: 'N 列',  head: '消耗',     to: '系统里的「消耗」' },
  { col: 'O 列',  head: '状态',     to: '系统里的「状态」' },
  { col: 'P 列',  head: '位置',     to: '该账户的主 BM' },
  { col: 'Q 列',  head: '产品信息', to: '系统里的「备注」' },
],

// PUSH_SAFE：批量回写不碰的列
// B/D 系统本来就当权威（操作人是建号时冻结的、资产UID 是定位键）
// I 是换绑记录，只由三个定向写点维护 —— 这是 FB 与 GG/TT 最大的不同
fb: ['B 列 · 操作人', 'D 列 · 资产UID', 'I 列 · 接户运营'],

// PUSH_SAFE_NOTE
fb: '其中「接户运营」列是系统记的换绑流水，系统只在归属变更时写它，其余时候不碰。',

// PUSH_EXTRA_NOTE
fb: '另外系统还会按自己的数据重写：A 列 · 日期。表里有、系统里没有的账户不会被写入，只会在结果里报一个数。',

// OWNER_WRITEBACK_TEXT
fb: '表里「在用运营」列已改写成新归属名，「接户运营」列已记下本次换绑。下次同步不会重复应用这些变更。',
```

`frontend/src/views/fb/FbSettingsPanel.vue`：在既有的五张卡**之后**、`</el-row>` **之前**插入

```vue
      <!-- 户管看板配置。只有户管可见（卡片内部自带 v-if）。 -->
      <el-col :span="24">
        <HuguanDashboardCard platform="fb" />
      </el-col>
```

并在 `<script setup>` 顶部加 `import HuguanDashboardCard from '@/components/HuguanDashboardCard.vue'`。

- [ ] **Step 7: 跑测试 + 构建**

```bash
cd py && python -m pytest tests/test_fb_huguan_dashboard.py -q
cd ../frontend && npm run build
```

Expected: 测试 PASS；构建成功。

- [ ] **Step 8: 跑全量回归并提交**

```bash
cd py && python -m pytest tests/ -q
git add py/routes/fb_routes.py py/routes/huguan_dashboard_routes.py py/huguan_dashboard.py frontend/src/components/HuguanDashboardCard.vue frontend/src/views/fb/FbSettingsPanel.vue py/tests/test_fb_huguan_dashboard.py
git commit -m "feat(fb): FB 写表触发点 + 看板卡片

- fb_routes 的 create/update/reassign 接上 hd.writeback_rows
- 新增 writeback_fb_acceptor 写「{旧}转{新}」到 I 列
- apply_diff 的 owner_changes 带上 from，并同步写 acceptor
- HuguanDashboardCard 支持 platform=fb，FbSettingsPanel 挂载"
```

---

## 完成后

子项目 ② 交付后，FB 的看板已可双向同步。剩 **子项目 ③（双向撤回）**，其中 FB 特有的两点已在 spec 里记着：

- `fb_account_bm_history` **没有 `ON DELETE CASCADE`** —— 撤回删新建 FB 账户时必须显式先删历史行
- `fb_accounts` 的 `acceptor` 是 TEXT，撤回时按普通文本列处理
