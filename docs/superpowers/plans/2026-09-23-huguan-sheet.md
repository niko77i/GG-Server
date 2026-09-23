# 户管看板 Google Sheet 双向同步 实现计划（子项目 B）

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让每个户管在 GG / TT 设置页各配置一张专属看板表，系统把账户数据写进表，户管在表里改的数据（尤其归属变更）能经差异确认后同步回系统。

**Architecture:** 新增一个**纯逻辑模块** `py/huguan_dashboard.py`（列规格、双向映射、差异比对，不 import flask、不碰网络，便于单测直接调用）+ 一个**瘦 blueprint** `py/routes/huguan_dashboard_routes.py`（只做鉴权、取参、调用逻辑层）。Sheets I/O 走 `py/google_sheets_service.py` 新增的批量行写入函数；账户增删改的既有端点通过一个公共钩子触发单行回写。

**Tech Stack:** Flask + SQLite（`temp/app.db`）+ flask_jwt_extended；Vue 3 + Element Plus + Pinia；Google Sheets API v4；pytest。

## Global Constraints

- **语言**：代码注释与 UI 文案用中文；标识符用英文。
- **纯增量原则**：不得修改既有函数的行为。`google_sheets_service.update_cell_by_account_id`、`accounts_sync_from_sheet`、现有的「我的看板」逻辑一律不动。
- **TT `reassign_account` 例外已报备**：唯一允许改既有行为的地方是 Task 9，且默认路径必须逐字节保持原逻辑与原返回文案。
- **列规格（写死，不得擅自增删）**：
  - GG 14 列，可写列（`COLUMN_SPEC` 中 writable=True）**`A:D` + `F:K`**，读回 **`A:N`**。注意 **H 列（重新分配）虽标记可写，自动回写永不写入**（规则 2），故系统实际回写的区间是 **`A:D` + `F:G` + `I:K`** —— 真正被跳过的列是 `E` / `H` / `L` / `M` / `N`。
  - TT 13 列，可写范围 **`A:J` + `L:M`**，读回 **`A:M`**，跳过可写的是 `K`。
  - 两张表的定位键都是 **C 列**。
- **§7.2 四条硬规则（违反任何一条都是缺陷）**：
  1. `重新分配`（GG H）/ `换绑情况`（TT L）非空时**压过** `运营`（GG G）/ `接户运营`（TT G）。
  2. 任何**自动回写**都不得写这两列。
  3. 这两列只有两个写点：户管在系统 UI 改归属时写新名；同步成功应用归属变更后写 `""`。
  4. 应用归属变更后，回写 `运营` / `接户运营` 列为新归属名。
- **配置 key**：`config` 表，key = `huguan_dashboard_{user_id}`，value 为 JSON `{"gg": {...}, "tt": {...}}`。
- **名称 → 主键的唯一口径（§8.4）**：唯一命中才落库；命中 0 条或 ≥2 条 → 记 warning，**该列**不落库，该行其余列照常处理。
- **状态解析必须带平台（Task 6 起）**：`resolve_status_id(db, name, owner_id, platform)`。`account_statuses.platform` 默认 `'gg'`、唯一约束是 `(name, platform)`、下拉按平台过滤（`main.py:6059`）—— 漏平台会让 TT 的状态落进 gg 命名空间。
- **请求体读字段的统一口径（所有 `/api/huguan/*` 端点）**：`data = request.get_json(silent=True)` 后先判 `isinstance(data, dict)`，否则 400；字段一律 `str(... or "")` 兜底再 `.strip()`。**禁止**写 `(data.get(x) or "").strip()` —— 客户端给个数字或 `null` 就会 `AttributeError` 炸成 500（Task 5 审查实测 `{"platform": 5}` / `{"spreadsheet_id": 123}` / `[1,2]` 三种 body 全中）。
- **同一口径适用于「容器型字段」**：`confirmed` 这类期望 dict 的字段，`data.get(x) or {}` 只能兜住 `None`/`""`/`0`，兜不住真值非 dict（`[1,2]`、`"abc"`）—— 那样会把 `AttributeError` 带到逻辑层炸成 500。必须显式判类型，非 dict 一律 400。判据与上一条相同：**客户端能构造出的畸形 body，只能是 4xx，不能是 5xx**。
- **「畸形」的边界（避免两种口径打架）**：畸形 = ①body 不是 JSON 对象；②容器型字段的类型不符。**标量字段给数字/`None` 不算畸形** —— 按 `str(... or "")` 兜底后照常走后续校验，该 200 就 200（`sheet_name: 5` → `"5"` 存下来），该 400 才 400（`platform: 5` → `"5"` 不在 `PLATFORMS` 里）。**不要**为了「数字也该拒绝」而对标量字段加 `isinstance(x, str)` 检查，那会与 `test_numeric_fields_are_coerced_not_500` 直接冲突（Task 5 修复时计划里真出现过这对互斥断言，一站一立才收敛）。
- **测试门禁**：`cd py && python -m pytest tests/ -q`，基线 **424 passed**（2026-09-23 实测；子项目 A 收尾时为 420，其后 `f46007c` 净增 4 条）。每次提交后不得低于此数。
- **各任务的计数是「累计预期」，为下界而非精确值**：以 `.superpowers/sdd/progress.md` 里记的**上一任务实测值**为准。若实际条数与预期不符，**先核实是计划写错还是实现漏做**：计划写错就改计划（并顺移后续累计值），实现漏做就补实现 —— 不要为了对上数字而删测试或改断言（Task 2 就因计划漏数而多出 1 条）。
- **前端门禁**：`cd frontend && npm run build` 必须通过。
- **前端 UI 前置**：Task 10 / Task 11 动手前必须先调用 `/frontend-design` 技能完成视觉设计（CLAUDE.md 硬性要求）。
- **git**：本仓库常有并行会话在途改文件，**禁用 `git add -A` / `git add .`**，每次只 `git add` 本任务明确列出的文件。
- **测试不得打真实 Google API**：所有 Sheets 调用在测试中必须被 monkeypatch 或替换为桩。

---

## File Structure

| 文件 | 职责 |
|---|---|
| `py/google_sheets_service.py` | **改**：新增列工具（`col_index` / `col_letter` / `merge_ranges`）与 `update_rows_by_account_id`。既有函数不动。 |
| `py/huguan_dashboard.py` | **新建**。纯逻辑：列规格、`cells_for_row`（系统→表）、`parse_row` + `effective_owner_name`（表→系统）、`build_diff`、`push_rows` 调度、配置读写。不 import flask。 |
| `py/routes/decorators.py` | **改**：新增 `huguan_required`（对照既有的 `developer_required`）。 |
| `py/routes/huguan_dashboard_routes.py` | **新建**。瘦 blueprint：`GET/POST /api/huguan/dashboard`、`POST /api/huguan/dashboard/push`、`POST /api/huguan/dashboard/sync`。 |
| `py/main.py` | **改**：注册 blueprint；6 个 GG 触发点接上单行回写。 |
| `py/routes/tt_accounts_routes.py` | **改**：6 个 TT 触发点接上单行回写；`reassign_account` 支持跨用户 `owner_id`。 |
| `py/tests/test_huguan_dashboard.py` | **新建**。 |
| `frontend/src/api/huguan.js` | **新建**。 |
| `frontend/src/views/SettingsPanel.vue` | **改**：新增户管看板配置卡片。 |
| `frontend/src/views/tt/TtSettingsPanel.vue` | **改**：同上。 |
| `frontend/src/views/AdsAccountPanel.vue` | **改**：新增「户归属」列。 |
| `frontend/src/views/tt/TtAccountPanel.vue` | **改**：同上。 |

---

## Task 1: Google Sheets 列工具

**Files:**
- Modify: `py/google_sheets_service.py`（在 `read_sheet_values` 之前插入，约 `:524` 前）
- Test: `py/tests/test_huguan_dashboard.py`（新建）

**Interfaces:**
- Consumes: 无
- Produces:
  - `col_index(letter: str) -> int` — `"A" → 0`，`"N" → 13`
  - `col_letter(idx: int) -> str` — `0 → "A"`
  - `merge_ranges(cols: list[str]) -> list[str]` — `["A","B","D"] → ["A:B","D:D"]`

- [ ] **Step 1: 写失败的测试**

创建 `py/tests/test_huguan_dashboard.py`：

```python
"""户管看板（Google Sheet 双向同步）测试。

设计见 docs/superpowers/specs/2026-09-23-huguan-sheet-design.md。
本文件不打真实 Google API：服务层调用一律用桩替换。
"""
import json

import database


# ---------- Task 1: 列工具 ----------

class TestColumnUtils:
    def test_col_index(self):
        from google_sheets_service import col_index
        assert col_index("A") == 0
        assert col_index("C") == 2
        assert col_index("N") == 13

    def test_col_letter(self):
        from google_sheets_service import col_letter
        assert col_letter(0) == "A"
        assert col_letter(2) == "C"
        assert col_letter(13) == "N"

    def test_merge_ranges_contiguous(self):
        from google_sheets_service import merge_ranges
        assert merge_ranges(["A", "B", "C", "D"]) == ["A:D"]

    def test_merge_ranges_with_gap(self):
        """非连续处必须断开：E 是唯一断口，故 A:D 与 F:K 分成两条。

        注意 F..K 本身是连续的（E 不在其中），所以只会断一次。
        """
        from google_sheets_service import merge_ranges
        cols = ["A", "B", "C", "D", "F", "G", "H", "I", "J", "K"]
        assert merge_ranges(cols) == ["A:D", "F:K"]

    def test_merge_ranges_single_and_empty(self):
        from google_sheets_service import merge_ranges
        assert merge_ranges(["D"]) == ["D:D"]
        assert merge_ranges([]) == []

    def test_merge_ranges_dedups_and_sorts(self):
        from google_sheets_service import merge_ranges
        assert merge_ranges(["B", "A", "B"]) == ["A:B"]
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd py && python -m pytest tests/test_huguan_dashboard.py -q`
Expected: FAIL — `ImportError: cannot import name 'col_index' from 'google_sheets_service'`

- [ ] **Step 3: 实现**

在 `py/google_sheets_service.py` 中，紧接 `read_sheet_values` 之前插入：

```python
def col_index(letter: str) -> int:
    """列字母 → 0 基下标：'A' → 0、'C' → 2。"""
    return ord(letter.strip().upper()) - 65


def col_letter(idx: int) -> str:
    """0 基下标 → 列字母：0 → 'A'、13 → 'N'。"""
    return chr(65 + idx)


def merge_ranges(cols: list) -> list:
    """把列字母集合合并成连续区间。

    ['A','B','C','D','F','G','H','I','J','K'] → ['A:D','F:K']   # E 是唯一断口

    用于「一次写多列但必须绕开公式列」的场景：非连续处断开，
    中间被跳过的列（如 GG 的 E）绝不落进任何区间，从而不被清掉。
    """
    idx = sorted({col_index(c) for c in cols})
    if not idx:
        return []
    out = []
    start = prev = idx[0]
    for i in idx[1:]:
        if i == prev + 1:
            prev = i
            continue
        out.append(f"{col_letter(start)}:{col_letter(prev)}")
        start = prev = i
    out.append(f"{col_letter(start)}:{col_letter(prev)}")
    return out
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd py && python -m pytest tests/test_huguan_dashboard.py -q`
Expected: PASS（6 passed）

- [ ] **Step 5: 提交**

```bash
git add py/google_sheets_service.py py/tests/test_huguan_dashboard.py
git commit -m "feat: Google Sheets 列工具（col_index/col_letter/merge_ranges）"
```

---

## Task 2: 列规格 + 系统→表映射

**Files:**
- Create: `py/huguan_dashboard.py`
- Test: `py/tests/test_huguan_dashboard.py`

**Interfaces:**
- Consumes: `google_sheets_service.col_index`
- Produces:
  - `COLUMN_SPEC: dict[str, list[tuple]]` — 每项 `(列字母, 表头, 字段名, 可写, 可读)`；字段名为 `None` 表示该列系统不映射
  - `KEY_COL: dict[str, str]` = `{"gg": "C", "tt": "C"}`
  - `OWNER_CHANNEL_COL` = `{"gg": "H", "tt": "L"}`
  - `OWNER_COL` = `{"gg": "G", "tt": "G"}`
  - `READ_RANGE` = `{"gg": "A:N", "tt": "A:M"}`
  - `DEAD_STATUS = "死亡"`、`ALIVE_STATUS = "存活"`
  - `cells_for_row(row: dict, platform: str) -> dict[str, str]` — 系统→表。**绝不产出** `_owner_channel` 列（规格规则 2）

- [ ] **Step 1: 写失败的测试**

追加到 `py/tests/test_huguan_dashboard.py`：

```python
# ---------- Task 2: 列规格 + 系统→表 ----------

def _gg_row(**over):
    row = {
        "account_id": "1234567890",
        "acquired_date": "2026-09-01",
        "death_date": "",
        "timezone": "America/New_York",
        "mcc_name": "MCC-A",
        "agent_name": "渠道甲",
        "owner_name": "张三",
        "parent_mcc_name": "大MCC-A",
        "status_name": "存活",
    }
    row.update(over)
    return row


def _tt_row(**over):
    row = {
        "account_id": "7001234567890",
        "acquired_date": "2026-09-02",
        "death_date": "",
        "country": "US",
        "bc_name": "BC-1",
        "agent_name": "渠道乙",
        "owner_name": "李四",
        "timezone": "Asia/Shanghai",
        "status_name": "存活",
        "consumption": "120.5",
        "remark": "产品X",
    }
    row.update(over)
    return row


class TestColumnSpec:
    def test_gg_has_14_columns(self):
        from huguan_dashboard import COLUMN_SPEC
        assert len(COLUMN_SPEC["gg"]) == 14
        assert [c[0] for c in COLUMN_SPEC["gg"]] == list("ABCDEFGHIJKLMN")

    def test_tt_has_13_columns(self):
        from huguan_dashboard import COLUMN_SPEC
        assert len(COLUMN_SPEC["tt"]) == 13
        assert [c[0] for c in COLUMN_SPEC["tt"]] == list("ABCDEFGHIJKLM")

    def test_unmapped_columns_gg(self):
        """GG 的 E 国家 / L 位置 / M 消耗 / N 产品信息 系统不映射。"""
        from huguan_dashboard import COLUMN_SPEC
        unmapped = {c[0] for c in COLUMN_SPEC["gg"] if c[2] is None}
        assert unmapped == {"E", "L", "M", "N"}

    def test_unmapped_columns_tt(self):
        """TT 的 K 位置 系统不映射。"""
        from huguan_dashboard import COLUMN_SPEC
        unmapped = {c[0] for c in COLUMN_SPEC["tt"] if c[2] is None}
        assert unmapped == {"K"}

    def test_writable_cols_produce_expected_ranges(self):
        """COLUMN_SPEC 中标了 writable 的列 → A1 区间。

        H 列虽然 writable=True，但见下一条测试：它绝不出现在回写区间里。
        """
        from huguan_dashboard import COLUMN_SPEC
        from google_sheets_service import merge_ranges
        for platform in ("gg", "tt"):
            cols = [c[0] for c in COLUMN_SPEC[platform] if c[3]]
            if platform == "gg":
                # A..D 连续；E 跳过；F..K 连续 —— 只断一次
                assert merge_ranges(cols) == ["A:D", "F:K"]
            else:
                # A..J 连续；K 跳过；L、M 连续
                assert merge_ranges(cols) == ["A:J", "L:M"]

    def test_real_writeback_ranges_never_span_owner_channel(self):
        """★这是规则 2 的守门测试：自动回写合并出的区间不得覆盖 H 列。

        cells_for_row 不产出 H（§7.2 规则 2），而 merge_ranges 只合并 cells 里
        相邻的列，因此 H 必然落在 F:G 与 I:K 之间的断口上。若哪天有人给
        cells_for_row 加了 H，或改了 merge_ranges 的合并规则，这条会红。
        """
        from huguan_dashboard import cells_for_row
        from google_sheets_service import merge_ranges
        cells = cells_for_row(_gg_row(), "gg")
        assert "H" not in cells
        ranges = merge_ranges(list(cells.keys()))
        assert ranges == ["A:D", "F:G", "I:K"]
        # 逐列展开，确认 H 不在任何一个区间覆盖到的列里
        covered = set()
        for rng in ranges:
            first, last = rng.split(":")
            covered.update(chr(c) for c in range(ord(first), ord(last) + 1))
        assert "H" not in covered
        assert "E" not in covered

    def test_parent_mcc_is_writable_but_not_readable(self):
        """J 大MCC 是派生列：写回要用，读回必须忽略。"""
        from huguan_dashboard import COLUMN_SPEC
        spec = {c[0]: c for c in COLUMN_SPEC["gg"]}
        assert spec["J"][3] is True   # 可写
        assert spec["J"][4] is False  # 不可读


class TestCellsForRow:
    def test_gg_cells(self):
        from huguan_dashboard import cells_for_row
        cells = cells_for_row(_gg_row(), "gg")
        assert cells["A"] == "2026-09-01"
        assert cells["B"] == ""            # 未封户
        assert cells["D"] == "MCC-A"
        assert cells["F"] == "渠道甲"
        assert cells["G"] == "张三"
        assert cells["I"] == "America/New_York"
        assert cells["J"] == "大MCC-A"
        assert cells["K"] == "存活"
        # 未映射列一个都不能出现
        for col in ("E", "L", "M", "N"):
            assert col not in cells

    def test_gg_dead_flag(self):
        from huguan_dashboard import cells_for_row
        assert cells_for_row(_gg_row(death_date="2026-09-10"), "gg")["B"] == "是"

    def test_account_id_forced_to_text(self):
        """长数字账户ID 必须加 ' 前缀，否则 Sheets 会按数字处理丢精度。"""
        from huguan_dashboard import cells_for_row
        assert cells_for_row(_gg_row(), "gg")["C"] == "'1234567890"

    def test_never_emits_owner_channel(self):
        """规格 §7.2 规则 2：自动回写绝不产出 重新分配 / 换绑情况 列。"""
        from huguan_dashboard import cells_for_row
        assert "H" not in cells_for_row(_gg_row(), "gg")
        assert "L" not in cells_for_row(_tt_row(), "tt")

    def test_tt_cells(self):
        from huguan_dashboard import cells_for_row
        cells = cells_for_row(_tt_row(), "tt")
        assert cells["C"] == "'7001234567890"
        assert cells["D"] == "BC-1"
        assert cells["E"] == "US"
        assert cells["G"] == "李四"
        assert cells["H"] == "Asia/Shanghai"
        assert cells["J"] == "120.5"
        assert "K" not in cells   # 位置列不映射
        assert cells["M"] == "产品X"

    def test_missing_field_becomes_empty_string(self):
        from huguan_dashboard import cells_for_row
        cells = cells_for_row({"account_id": "1"}, "gg")
        assert cells["A"] == ""
        assert cells["K"] == ""
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd py && python -m pytest tests/test_huguan_dashboard.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'huguan_dashboard'`

- [ ] **Step 3: 实现**

创建 `py/huguan_dashboard.py`：

```python
"""户管看板（Google Sheet）双向同步的纯逻辑层。

设计见 docs/superpowers/specs/2026-09-23-huguan-sheet-design.md。

本模块刻意不 import flask、不碰网络：列规格、双向映射、差异比对都放在这里，
单测可直接调用。真正的 Sheets I/O 在 google_sheets_service，HTTP 入口在
routes/huguan_dashboard_routes.py。
"""
import json

from google_sheets_service import col_index

PLATFORMS = ("gg", "tt")

DEAD_STATUS = "死亡"
ALIVE_STATUS = "存活"

# 列规格：每项 (列字母, 表头, 系统字段名, 可写, 可读)
# 字段名为 None → 该列系统不映射，户管自己用公式维护，读写都不碰。
#
# 字段名里以 "_" 开头的两个是合成字段，不对应数据库列：
#   _dead_flag      ← death_date 是否非空，写"是"/空
#   _owner_channel  ← 重新分配 / 换绑情况，归属变更通道（规格 §7）
COLUMN_SPEC = {
    "gg": [
        ("A", "日期",     "acquired_date",   True,  True),
        ("B", "是否封户", "_dead_flag",      True,  True),
        ("C", "账户ID",   "account_id",      True,  False),  # 定位键
        ("D", "MCC",      "mcc_name",        True,  True),
        ("E", "国家",     None,              False, False),
        ("F", "所属渠道", "agent_name",      True,  True),
        ("G", "运营",     "owner_name",      True,  True),
        ("H", "重新分配", "_owner_channel",  True,  True),
        ("I", "时区",     "timezone",        True,  True),
        ("J", "大MCC",    "parent_mcc_name", True,  False),  # 派生列，读回会与 D 打架
        ("K", "状态",     "status_name",     True,  True),
        ("L", "位置",     None,              False, False),
        ("M", "消耗",     None,              False, False),
        ("N", "产品信息", None,              False, False),
    ],
    "tt": [
        ("A", "入库时间",  "acquired_date",   True,  True),
        ("B", "是否回收",  "_dead_flag",      True,  True),
        ("C", "账户ID",    "account_id",      True,  False),  # 定位键（取自 advertiser_id）
        ("D", "BC",        "bc_name",         True,  True),
        ("E", "国家",      "country",         True,  True),
        ("F", "所属渠道",  "agent_name",      True,  True),
        ("G", "接户运营",  "owner_name",      True,  True),
        ("H", "时区",      "timezone",        True,  True),
        ("I", "状态",      "status_name",     True,  True),
        ("J", "消耗",      "consumption",     True,  True),
        ("K", "位置",      None,              False, False),
        ("L", "换绑情况",  "_owner_channel",  True,  True),
        ("M", "产品信息",  "remark",          True,  True),
    ],
}

KEY_COL = {"gg": "C", "tt": "C"}
OWNER_COL = {"gg": "G", "tt": "G"}
OWNER_CHANNEL_COL = {"gg": "H", "tt": "L"}
READ_RANGE = {"gg": "A:N", "tt": "A:M"}

# 系统里「账户ID」列在两张表下的实际字段名
ACCOUNT_KEY_FIELD = {"gg": "account_id", "tt": "advertiser_id"}


def _text(value) -> str:
    """账户ID 等长数字强制文本，避免 Sheets 按数字处理丢精度。

    对照 append_recycle（google_sheets_service.py:450）的既有做法。
    """
    s = "" if value is None else str(value).strip()
    if s and s.isdigit():
        return "'" + s
    return s


def cells_for_row(row: dict, platform: str) -> dict:
    """系统 → 表：把一行账户数据转成 {列字母: 待写值}。

    只产出可写列，且**绝不产出归属变更通道列**（规格 §7.2 规则 2）——
    自动回写若顺手把户管刚填的重新分配清掉，那个变更就被静默吞了。
    """
    cells = {}
    for col, _header, field, writable, _readable in COLUMN_SPEC[platform]:
        if not writable or field is None or field == "_owner_channel":
            continue
        if field == "_dead_flag":
            cells[col] = "是" if (row.get("death_date") or "").strip() else ""
        elif field == "account_id":
            cells[col] = _text(row.get("account_id", ""))
        else:
            cells[col] = "" if row.get(field) is None else str(row.get(field)).strip()
    return cells
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd py && python -m pytest tests/test_huguan_dashboard.py -q`
Expected: PASS（聚焦 19 passed：Task 1 的 6 条 + 本任务 13 条）

- [ ] **Step 5: 提交**

```bash
git add py/huguan_dashboard.py py/tests/test_huguan_dashboard.py
git commit -m "feat: 户管看板列规格与系统→表映射"
```

---

## Task 3: 表→系统解析 + 归属优先规则

**Files:**
- Modify: `py/huguan_dashboard.py`
- Test: `py/tests/test_huguan_dashboard.py`

**Interfaces:**
- Consumes: `COLUMN_SPEC`、`col_index`
- Produces:
  - `parse_row(values: list, platform: str) -> dict` — 表→系统。忽略不可读列；`account_id` 已去掉 `'` 前缀
  - `effective_owner_name(parsed: dict) -> str` — 规格 §7.1：通道非空压过当前归属
  - `is_dead(parsed: dict) -> bool` — 状态列优先，回退 `_dead_flag`

- [ ] **Step 1: 写失败的测试**

追加到 `py/tests/test_huguan_dashboard.py`：

```python
# ---------- Task 3: 表→系统 ----------

class TestParseRow:
    def test_gg_parse_full_row(self):
        from huguan_dashboard import parse_row
        values = ["2026-09-01", "", "1234567890", "MCC-A", "美国", "渠道甲",
                  "张三", "", "America/New_York", "大MCC-A", "存活", "位置X", "", ""]
        p = parse_row(values, "gg")
        assert p["account_id"] == "1234567890"
        assert p["acquired_date"] == "2026-09-01"
        assert p["_dead_flag"] == ""
        assert p["mcc_name"] == "MCC-A"
        assert p["agent_name"] == "渠道甲"
        assert p["owner_name"] == "张三"
        assert p["_owner_channel"] == ""
        assert p["timezone"] == "America/New_York"
        assert p["status_name"] == "存活"

    def test_strips_leading_apostrophe_from_key(self):
        from huguan_dashboard import parse_row
        p = parse_row(["", "", "'1234567890"], "gg")
        assert p["account_id"] == "1234567890"

    def test_ignores_derived_and_unmapped_columns(self):
        """J 大MCC 是派生列、E/L/M/N 不映射 —— 解析结果里都不该有。"""
        from huguan_dashboard import parse_row
        p = parse_row(["", "", "1", "MCC-A", "美国", "", "", "", "", "大MCC-A",
                       "", "位置X", "999", "产品Y"], "gg")
        assert "parent_mcc_name" not in p
        assert set(p) == {"account_id", "acquired_date", "_dead_flag", "mcc_name",
                          "agent_name", "owner_name", "_owner_channel",
                          "timezone", "status_name"}

    def test_short_row_pads_empty(self):
        from huguan_dashboard import parse_row
        p = parse_row([], "tt")
        assert p["account_id"] == ""
        assert p["bc_name"] == ""
        assert p["remark"] == ""

    def test_tt_parse(self):
        from huguan_dashboard import parse_row
        values = ["2026-09-02", "是", "7001234567890", "BC-1", "US", "渠道乙",
                  "李四", "Asia/Shanghai", "死亡", "120.5", "位置Y", "王五", "产品X"]
        p = parse_row(values, "tt")
        assert p["account_id"] == "7001234567890"
        assert p["_dead_flag"] == "是"
        assert p["bc_name"] == "BC-1"
        assert p["country"] == "US"
        assert p["_owner_channel"] == "王五"   # L 换绑情况
        assert p["consumption"] == "120.5"
        assert p["remark"] == "产品X"

    def test_whitespace_is_stripped(self):
        from huguan_dashboard import parse_row
        p = parse_row(["  2026-09-01  ", "", "  123  "], "gg")
        assert p["acquired_date"] == "2026-09-01"
        assert p["account_id"] == "123"


class TestEffectiveOwnerName:
    def test_channel_wins_when_present(self):
        """规格 §7.1：运营与重新分配不一致时以重新分配为准。"""
        from huguan_dashboard import effective_owner_name
        p = {"owner_name": "张三", "_owner_channel": "李四"}
        assert effective_owner_name(p) == "李四"

    def test_falls_back_to_owner_when_channel_empty(self):
        from huguan_dashboard import effective_owner_name
        assert effective_owner_name({"owner_name": "张三", "_owner_channel": ""}) == "张三"

    def test_blank_when_both_empty(self):
        from huguan_dashboard import effective_owner_name
        assert effective_owner_name({"owner_name": "", "_owner_channel": "  "}) == ""


class TestIsDead:
    def test_status_column_wins(self):
        """状态列更具体：状态=死亡 时，是否封户 不填也算死亡。"""
        from huguan_dashboard import is_dead
        assert is_dead({"status_name": "死亡", "_dead_flag": ""}) is True

    def test_dead_flag_fallback(self):
        from huguan_dashboard import is_dead
        assert is_dead({"status_name": "", "_dead_flag": "是"}) is True

    def test_alive(self):
        from huguan_dashboard import is_dead
        assert is_dead({"status_name": "存活", "_dead_flag": ""}) is False
        assert is_dead({"status_name": "", "_dead_flag": "否"}) is False
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd py && python -m pytest tests/test_huguan_dashboard.py -q`
Expected: FAIL — `ImportError: cannot import name 'parse_row' from 'huguan_dashboard'`

- [ ] **Step 3: 实现**

追加到 `py/huguan_dashboard.py`：

```python
def parse_row(values: list, platform: str) -> dict:
    """表 → 系统：把一行原始单元格值转成 {字段名: 字符串值}。

    不可读列（定位键 C、派生列、未映射列）一律不出现在结果里，
    `_owner_channel` 与 `_dead_flag` 是合成字段，供上层判归属与生死。
    """
    out = {}
    for col, _header, field, _writable, readable in COLUMN_SPEC[platform]:
        if not readable or field is None:
            continue
        i = col_index(col)
        raw = values[i] if len(values) > i else ""
        out[field] = ("" if raw is None else str(raw)).strip()
    # C 列是定位键，单独取，并去掉 _text() 加的强制文本前缀
    key_i = col_index(KEY_COL[platform])
    raw_key = values[key_i] if len(values) > key_i else ""
    out["account_id"] = ("" if raw_key is None else str(raw_key)).strip().lstrip("'").strip()
    return out


def effective_owner_name(parsed: dict) -> str:
    """规格 §7.1：归属变更通道非空时压过当前归属列。

    「表里运营列和重新分配列不一致，就以表里的重新分配为准」（用户原话）。
    """
    channel = (parsed.get("_owner_channel") or "").strip()
    if channel:
        return channel
    return (parsed.get("owner_name") or "").strip()


def is_dead(parsed: dict) -> bool:
    """该行是否应判为死亡。

    状态列（GG K / TT I）比 是否封户 / 是否回收 更具体，有值时以它为准。
    """
    status = (parsed.get("status_name") or "").strip()
    if status:
        return status == DEAD_STATUS
    return (parsed.get("_dead_flag") or "").strip() == "是"
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd py && python -m pytest tests/test_huguan_dashboard.py -q`
Expected: PASS（聚焦 31 passed）

- [ ] **Step 5: 提交**

```bash
git add py/huguan_dashboard.py py/tests/test_huguan_dashboard.py
git commit -m "feat: 户管看板表→系统解析与归属优先规则"
```

---

## Task 4: 批量行写入服务函数

**Files:**
- Modify: `py/google_sheets_service.py`（紧接 `update_cell_by_account_id` 之后，约 `:606` 后）
- Test: `py/tests/test_huguan_dashboard.py`

**Interfaces:**
- Consumes: `read_sheet_values`、`col_index`、`col_letter`、`merge_ranges`
- Produces: `update_rows_by_account_id(service, spreadsheet_id, sheet_name, rows, key_col="C") -> dict`
  - `rows`: `[{"account_id": "123", "cells": {"A": "v", "G": "张三"}}]`
  - 返回 `{"updated": n, "not_found": ["<account_id>", ...]}`

- [ ] **Step 1: 写失败的测试**

追加到 `py/tests/test_huguan_dashboard.py`。用一个记录调用的假 service：

```python
# ---------- Task 4: 批量行写入 ----------

class _FakeExec:
    def __init__(self, recorder, payload):
        self._recorder = recorder
        self._payload = payload

    def execute(self):
        self._recorder.append(self._payload)
        # 必须回传 payload，不能 return {}：read_sheet_values 取的是 .execute() 的
        # **返回值**（result.get("values", [])），不是 recorder 里记的那份。
        # 早期本计划写成 return {}，导致键列网格恒为空、7 条测试里 5 条不可能通过。
        return self._payload


class _FakeValues:
    def __init__(self, recorder, grid):
        self._recorder = recorder
        self._grid = grid

    def get(self, spreadsheetId=None, range=None):
        self._recorder.append({"op": "get", "range": range})
        return _FakeExec(self._recorder, {"values": self._grid})

    def batchUpdate(self, spreadsheetId=None, body=None):
        return _FakeExec(self._recorder, {"op": "batchUpdate", "body": body})


class _FakeSheets:
    def __init__(self, recorder, grid):
        self._values = _FakeValues(recorder, grid)

    def values(self):
        return self._values


class _FakeService:
    def __init__(self, grid):
        self.recorder = []
        self._sheets = _FakeSheets(self.recorder, grid)

    def spreadsheets(self):
        return self._sheets


def _grid(rows):
    """rows: [account_id, ...] → C 列在 index 2 的最小网格。"""
    return [["", "", aid] for aid in rows]


class TestUpdateRowsByAccountId:
    def test_writes_only_listed_columns(self):
        from google_sheets_service import update_rows_by_account_id
        svc = _FakeService(_grid(["111", "222"]))
        res = update_rows_by_account_id(
            svc, "SS", "看板", [{"account_id": "222", "cells": {"A": "x", "G": "张三"}}]
        )
        assert res == {"updated": 1, "not_found": []}
        batch = [r for r in svc.recorder if r.get("op") == "batchUpdate"]
        assert len(batch) == 1
        data = batch[0]["body"]["data"]
        # A 与 G 不连续 → 两条区间，D~F 中间被跳过的列绝不落进区间
        assert [d["range"] for d in data] == ["'看板'!A2:A2", "'看板'!G2:G2"]
        assert data[0]["values"] == [["x"]]
        assert data[1]["values"] == [["张三"]]

    def test_contiguous_columns_merge_into_one_range(self):
        from google_sheets_service import update_rows_by_account_id
        svc = _FakeService(_grid(["111"]))
        update_rows_by_account_id(
            svc, "SS", "看板",
            [{"account_id": "111", "cells": {"A": "1", "B": "2", "C": "3", "D": "4"}}],
        )
        data = [r for r in svc.recorder if r.get("op") == "batchUpdate"][0]["body"]["data"]
        assert len(data) == 1
        assert data[0]["range"] == "'看板'!A1:D1"
        assert data[0]["values"] == [["1", "2", "3", "4"]]

    def test_gap_in_cells_splits_into_separate_ranges(self):
        """cells 里有空洞时区间会断开，而不是补空串。

        这正是「未出现在 cells 里的列一律不碰」的实现保证：merge_ranges 只会把
        在 cells 里**相邻**的列并成区间，所以 B、C 绝不会被顺带写进去。
        """
        from google_sheets_service import update_rows_by_account_id
        svc = _FakeService(_grid(["111"]))
        update_rows_by_account_id(
            svc, "SS", "看板", [{"account_id": "111", "cells": {"A": "1", "D": "4"}}]
        )
        data = [r for r in svc.recorder if r.get("op") == "batchUpdate"][0]["body"]["data"]
        assert [d["range"] for d in data] == ["'看板'!A1:A1", "'看板'!D1:D1"]
        assert data[0]["values"] == [["1"]]
        assert data[1]["values"] == [["4"]]

    def test_not_found_reported_not_raised(self):
        """表里没有这个账户是正常情况（户管的表不必包含所有账户），不能抛。"""
        from google_sheets_service import update_rows_by_account_id
        svc = _FakeService(_grid(["111"]))
        res = update_rows_by_account_id(
            svc, "SS", "看板",
            [{"account_id": "111", "cells": {"A": "1"}},
             {"account_id": "999", "cells": {"A": "2"}}],
        )
        assert res["updated"] == 1
        assert res["not_found"] == ["999"]

    def test_matches_apostrophe_prefixed_key(self):
        """定位时要剥掉 ' 前缀：表里存的可能是强制文本形式。"""
        from google_sheets_service import update_rows_by_account_id
        svc = _FakeService([["", "", "'111"]])
        res = update_rows_by_account_id(
            svc, "SS", "看板", [{"account_id": "111", "cells": {"A": "1"}}]
        )
        assert res == {"updated": 1, "not_found": []}

    def test_key_column_read_range_is_minimal(self):
        """只读 A:C 找键，不读整表。"""
        from google_sheets_service import update_rows_by_account_id
        svc = _FakeService(_grid(["111"]))
        update_rows_by_account_id(svc, "SS", "看板", [{"account_id": "111", "cells": {"A": "1"}}])
        gets = [r for r in svc.recorder if r.get("op") == "get"]
        assert gets[0]["range"] == "'看板'!A:C"

    def test_empty_rows_is_noop(self):
        from google_sheets_service import update_rows_by_account_id
        svc = _FakeService(_grid(["111"]))
        assert update_rows_by_account_id(svc, "SS", "看板", []) == {"updated": 0, "not_found": []}
        assert svc.recorder == []
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd py && python -m pytest tests/test_huguan_dashboard.py -q`
Expected: FAIL — `ImportError: cannot import name 'update_rows_by_account_id'`

- [ ] **Step 3: 实现**

在 `py/google_sheets_service.py` 的 `update_cell_by_account_id` 之后追加：

```python
def update_rows_by_account_id(service, spreadsheet_id: str, sheet_name: str,
                              rows: list, key_col: str = "C") -> dict:
    """按「账户ID 列」定位行，一次写多列；未出现在 cells 里的列一律不碰。

    与 update_cell_by_account_id 的区别：那个写单列、按 B 列定位、并假定
    「我的看板」的 8 列布局；这个写多列、列位置可配、且用区间合并绕开公式列。

    Args:
        rows: [{"account_id": "123", "cells": {"A": "2026-09-23", "G": "张三"}}]
              cells 的键是列字母。只有相邻列会并成区间，空洞处断开，
              因此没出现在 cells 里的列绝不会被写到（公式列靠这个保命）。
        key_col: 账户ID 所在列字母。

    Returns:
        {"updated": n, "not_found": ["<account_id>", ...]}
        表里找不到该账户不算错误 —— 户管的表不必包含所有账户。
    """
    import logging
    log = logging.getLogger("gg-server")

    if not rows:
        return {"updated": 0, "not_found": []}

    key_i = col_index(key_col)
    grid = read_sheet_values(service, spreadsheet_id, sheet_name, f"A:{key_col}")

    row_of = {}
    for i, r in enumerate(grid):
        if len(r) > key_i:
            v = (r[key_i] or "").strip().lstrip("'").strip()
            if v and v not in row_of:
                row_of[v] = i + 1  # 1-indexed

    updated, not_found = 0, []
    for item in rows:
        aid = (item.get("account_id") or "").strip()
        cells = item.get("cells") or {}
        row_num = row_of.get(aid)
        if row_num is None:
            not_found.append(aid)
            continue

        data = []
        for rng in merge_ranges(list(cells.keys())):
            first, last = rng.split(":")
            start, end = col_index(first), col_index(last)
            data.append({
                "range": f"'{sheet_name}'!{first}{row_num}:{last}{row_num}",
                "values": [[cells.get(col_letter(c), "") for c in range(start, end + 1)]],
            })

        try:
            service.spreadsheets().values().batchUpdate(
                spreadsheetId=spreadsheet_id,
                body={"valueInputOption": "USER_ENTERED", "data": data},
            ).execute()
            updated += 1
        except Exception as e:
            raise GoogleSheetsServiceError(f"批量更新行失败 account_id={aid}: {e}") from e

    log.info("update_rows_by_account_id: 更新 %d 行，未找到 %d 行", updated, len(not_found))
    return {"updated": updated, "not_found": not_found}
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd py && python -m pytest tests/test_huguan_dashboard.py -q`
Expected: PASS（聚焦 38 passed）

- [ ] **Step 5: 提交**

```bash
git add py/google_sheets_service.py py/tests/test_huguan_dashboard.py
git commit -m "feat: 按账户ID批量写多列（区间合并绕开公式列）"
```

---

## Task 5: 配置读写 + 户管限定装饰器 + blueprint 骨架

**Files:**
- Modify: `py/routes/decorators.py`（在 `developer_required` 之后，约 `:36` 后）
- Modify: `py/huguan_dashboard.py`
- Create: `py/routes/huguan_dashboard_routes.py`
- Modify: `py/main.py`（blueprint 注册，`main.py:361` 后）
- Test: `py/tests/test_huguan_dashboard.py`

**Interfaces:**
- Consumes: 无
- Produces:
  - `routes.decorators.huguan_required` — 非户管一律 403
  - `huguan_dashboard.load_config(db, user_id) -> dict` — `{"gg": {...}, "tt": {...}}`，缺省为空 dict
  - `huguan_dashboard.save_config(db, user_id, platform, spreadsheet_id, sheet_name) -> None`
  - `huguan_dashboard.get_platform_config(db, user_id, platform) -> dict` — `{"spreadsheet_id": str, "sheet_name": str}`，未配置时两项均为 `""`
  - HTTP：`GET /api/huguan/dashboard` → `{"success": true, "config": {...}}`；`POST /api/huguan/dashboard` body `{"platform","spreadsheet_id","sheet_name"}`

- [ ] **Step 1: 写失败的测试**

追加到 `py/tests/test_huguan_dashboard.py`：

```python
# ---------- Task 5: 配置读写 + 权限 ----------

def _create_user(client, username, role="user", platform="gg"):
    """注册用户 → 改写 role/platform → 登录。返回 (headers, user_id)。"""
    client.post("/api/auth/register", json={"username": username, "password": "test123"})
    db = database.get_db()
    db.execute("UPDATE users SET role=?, platform=? WHERE username=?", (role, platform, username))
    db.commit()
    row = db.execute("SELECT id FROM users WHERE username=?", (username,)).fetchone()
    db.close()
    resp = client.post("/api/auth/login", json={"username": username, "password": "test123"})
    return {"Authorization": f"Bearer {resp.get_json()['access_token']}"}, row["id"]


class TestDashboardConfig:
    def test_save_then_get_roundtrip(self, client):
        hg, _ = _create_user(client, "_hg_cfg1", role="huguan")
        resp = client.post("/api/huguan/dashboard", headers=hg, json={
            "platform": "gg", "spreadsheet_id": "SS-GG", "sheet_name": "户管看板",
        })
        assert resp.status_code == 200
        got = client.get("/api/huguan/dashboard", headers=hg).get_json()["config"]
        assert got["gg"] == {"spreadsheet_id": "SS-GG", "sheet_name": "户管看板"}

    def test_platforms_are_isolated(self, client):
        """GG 与 TT 各配各的，互不覆盖（需求原文：这个sheet在gg和tt配置的是不一样的）。"""
        hg, _ = _create_user(client, "_hg_cfg2", role="huguan")
        client.post("/api/huguan/dashboard", headers=hg,
                    json={"platform": "gg", "spreadsheet_id": "SS-GG", "sheet_name": "G"})
        client.post("/api/huguan/dashboard", headers=hg,
                    json={"platform": "tt", "spreadsheet_id": "SS-TT", "sheet_name": "T"})
        got = client.get("/api/huguan/dashboard", headers=hg).get_json()["config"]
        assert got["gg"]["spreadsheet_id"] == "SS-GG"
        assert got["tt"]["spreadsheet_id"] == "SS-TT"

    def test_users_are_isolated(self, client):
        hg1, _ = _create_user(client, "_hg_cfg_a", role="huguan")
        hg2, _ = _create_user(client, "_hg_cfg_b", role="huguan")
        client.post("/api/huguan/dashboard", headers=hg1,
                    json={"platform": "gg", "spreadsheet_id": "SS-1", "sheet_name": "A"})
        got2 = client.get("/api/huguan/dashboard", headers=hg2).get_json()["config"]
        assert got2.get("gg", {}).get("spreadsheet_id", "") == ""

    def test_url_is_parsed_to_id(self, client):
        hg, _ = _create_user(client, "_hg_cfg3", role="huguan")
        client.post("/api/huguan/dashboard", headers=hg, json={
            "platform": "gg",
            "spreadsheet_id": "https://docs.google.com/spreadsheets/d/ABC-123_x/edit#gid=0",
            "sheet_name": "S",
        })
        got = client.get("/api/huguan/dashboard", headers=hg).get_json()["config"]
        assert got["gg"]["spreadsheet_id"] == "ABC-123_x"

    def test_invalid_platform_rejected(self, client):
        hg, _ = _create_user(client, "_hg_cfg4", role="huguan")
        resp = client.post("/api/huguan/dashboard", headers=hg,
                           json={"platform": "fb", "spreadsheet_id": "S", "sheet_name": "N"})
        assert resp.status_code == 400

    def test_non_huguan_gets_403(self, client):
        """规格：全部 /api/huguan/dashboard* 仅户管可达。"""
        for role in ("user", "viewer", "admin", "developer"):
            h, _ = _create_user(client, f"_nothg_{role}", role=role)
            assert client.get("/api/huguan/dashboard", headers=h).status_code == 403
            assert client.post("/api/huguan/dashboard", headers=h,
                               json={"platform": "gg", "spreadsheet_id": "S",
                                     "sheet_name": "N"}).status_code == 403

    def test_requires_jwt(self, client):
        assert client.get("/api/huguan/dashboard").status_code == 401

    def test_malformed_body_is_400_not_500(self, client):
        """畸形 body 必须 400 而不是 500 —— 非 dict body，以及 platform 非法。

        这三条以前会 AttributeError 炸成 500。
        注意 `sheet_name` 给数字**不算**畸形：按全局约束与 spreadsheet_id 一致地
        `str()` 兜底（见下一条），所以这里只钉 body 结构与 platform 非法两条路径。
        """
        hg, _ = _create_user(client, "_hg_badbody", role="huguan")
        for payload in ({"platform": 5}, {"spreadsheet_id": 123}, {"platform": "fb"}):
            resp = client.post("/api/huguan/dashboard", headers=hg, json=payload)
            assert resp.status_code == 400, payload
        assert client.post("/api/huguan/dashboard", headers=hg,
                           json=[1, 2]).status_code == 400

    def test_numeric_fields_are_coerced_not_500(self, client):
        """数字型字段一律 `str()` 兜底后按字符串处理，既不 500 也不当畸形拒掉。

        与 spreadsheet_id 同一口径：户管粘进来的表格名/ID 是数字串很常见。
        """
        hg, _ = _create_user(client, "_hg_numeric", role="huguan")
        resp = client.post("/api/huguan/dashboard", headers=hg, json={
            "platform": "gg", "spreadsheet_id": 123456, "sheet_name": 5,
        })
        assert resp.status_code == 200
        got = client.get("/api/huguan/dashboard", headers=hg).get_json()["config"]
        assert got["gg"] == {"spreadsheet_id": "123456", "sheet_name": "5"}

    def test_non_dict_platform_entry_is_tolerated(self, client):
        """config 里平台条目是「真值非 dict」时不得抛异常（该表被别处共用）。"""
        from huguan_dashboard import get_platform_config
        _, uid = _create_user(client, "_hg_nondict", role="huguan")
        db = database.get_db()
        db.execute("INSERT OR REPLACE INTO config(key,value) VALUES(?,?)",
                   (f"huguan_dashboard_{uid}", '{"gg": "just-a-string", "tt": null}'))
        db.commit()
        empty = {"spreadsheet_id": "", "sheet_name": ""}
        assert get_platform_config(db, uid, "gg") == empty
        assert get_platform_config(db, uid, "tt") == empty
        db.close()

    def test_non_string_inner_values_are_tolerated(self, client):
        """平台条目**内层值**不是字符串时也不得抛异常。

        外层判了 dict 不代表里面存的是字符串：`config` 表全仓共用，值可能是数字或列表。
        `(v or "").strip()` 会 `AttributeError` → 500。
        """
        from huguan_dashboard import get_platform_config
        _, uid = _create_user(client, "_hg_inner", role="huguan")
        db = database.get_db()
        db.execute("INSERT OR REPLACE INTO config(key,value) VALUES(?,?)",
                   (f"huguan_dashboard_{uid}",
                    '{"gg": {"spreadsheet_id": 123, "sheet_name": ["x"]}}'))
        db.commit()
        got = get_platform_config(db, uid, "gg")
        assert got["spreadsheet_id"] == "123"
        assert isinstance(got["sheet_name"], str)   # 关键是不抛异常
        db.close()

    def test_save_config_tolerates_non_string_args(self, client):
        """save_config 直接收到数字/None 也不能炸（Task 7–9 会直接调它）。"""
        from huguan_dashboard import get_platform_config, save_config
        _, uid = _create_user(client, "_hg_savearg", role="huguan")
        db = database.get_db()
        save_config(db, uid, "gg", 123, None)
        assert get_platform_config(db, uid, "gg") == {"spreadsheet_id": "123",
                                                      "sheet_name": ""}
        db.close()

    def test_get_normalizes_non_dict_platform_entry(self, client):
        """`config` 里平台条目是「真值非 dict」时，GET 也要返回结构完整的对象。

        不归一化就会把字符串/数字原样透传，破坏 {"spreadsheet_id","sheet_name"} 契约。
        """
        hg, uid = _create_user(client, "_hg_getnorm", role="huguan")
        db = database.get_db()
        db.execute("INSERT OR REPLACE INTO config(key,value) VALUES(?,?)",
                   (f"huguan_dashboard_{uid}", '{"gg": "just-a-string"}'))
        db.commit()
        db.close()
        got = client.get("/api/huguan/dashboard", headers=hg).get_json()["config"]
        assert got["gg"] == {"spreadsheet_id": "", "sheet_name": ""}
        assert got["tt"] == {"spreadsheet_id": "", "sheet_name": ""}
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd py && python -m pytest tests/test_huguan_dashboard.py -q`
Expected: FAIL — `test_save_then_get_roundtrip` 404（路由不存在）

- [ ] **Step 3: 实现装饰器**

在 `py/routes/decorators.py` 的 `developer_required` 之后插入：

```python
def huguan_required(fn):
    """要求户管角色（户管看板专用）。"""
    @wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            uid = int(get_jwt_identity())
        except Exception:
            return err("未认证", 401)
        user = auth.get_user_by_id(uid)
        if not user or user["role"] != HUGUAN_ROLE:
            return err("权限不足，仅户管可操作", 403)
        return fn(*args, **kwargs)
    return wrapper
```

- [ ] **Step 4: 实现配置读写**

追加到 `py/huguan_dashboard.py`：

```python
CONFIG_KEY = "huguan_dashboard_{uid}"


def load_config(db, user_id: int) -> dict:
    """读取该户管的看板配置：{"gg": {...}, "tt": {...}}，未配置时为空 dict。"""
    row = db.execute("SELECT value FROM config WHERE key=?",
                     (CONFIG_KEY.format(uid=user_id),)).fetchone()
    if row and row["value"]:
        try:
            loaded = json.loads(row["value"])
            if isinstance(loaded, dict):
                return loaded
        except Exception:
            pass
    return {}


def _conf_text(value) -> str:
    """配置值一律转成去空白的字符串。

    不能写 `(value or "").strip()` —— `config` 表是全仓共用的，里面存的可能是数字或
    列表（真值非 str），`.strip()` 会直接 `AttributeError` 炸成 500。同类兜底先例见
    本模块 `_text()`（:67）。
    """
    return "" if value is None else str(value).strip()


def get_platform_config(db, user_id: int, platform: str) -> dict:
    """取某平台的看板配置，永远返回两项（未配置时为空串，调用方无需判 None）。"""
    entry = load_config(db, user_id).get(platform)
    # config 表被其它功能共用，平台条目可能是「真值非 dict」；不判类型会 AttributeError
    if not isinstance(entry, dict):
        entry = {}
    return {
        # 内层值同样不能假设是 str —— 外层判了 dict 不代表里面存的是字符串
        "spreadsheet_id": _conf_text(entry.get("spreadsheet_id")),
        "sheet_name": _conf_text(entry.get("sheet_name")),
    }


def save_config(db, user_id: int, platform: str, spreadsheet_id: str, sheet_name: str) -> None:
    """写入某平台的看板配置，另一个平台的配置保持不变。"""
    if platform not in PLATFORMS:
        raise ValueError(f"不支持的平台: {platform}")
    conf = load_config(db, user_id)
    conf[platform] = {
        "spreadsheet_id": _conf_text(spreadsheet_id),
        "sheet_name": _conf_text(sheet_name),
    }
    db.execute("INSERT OR REPLACE INTO config(key,value) VALUES(?,?)",
               (CONFIG_KEY.format(uid=user_id), json.dumps(conf, ensure_ascii=False)))
    db.commit()
```

- [ ] **Step 5: 实现 blueprint**

创建 `py/routes/huguan_dashboard_routes.py`：

```python
"""户管看板（Google Sheet）配置与双向同步的 HTTP 入口。

设计见 docs/superpowers/specs/2026-09-23-huguan-sheet-design.md。
本文件只做取参/鉴权/调逻辑层，双向同步的实际判断都在 huguan_dashboard.py，
Sheets I/O 在 google_sheets_service.py。
"""
from flask import Blueprint, request
from flask_jwt_extended import jwt_required

import database
import huguan_dashboard as hd

from .helpers import ok, err, get_uid
from .decorators import huguan_required

huguan_dashboard_bp = Blueprint("huguan_dashboard", __name__)


@huguan_dashboard_bp.route("/api/huguan/dashboard", methods=["GET"])
@jwt_required()
@huguan_required
def dashboard_config_get():
    """返回当前户管的看板配置（GG 与 TT 两份）。

    两份都经 `get_platform_config` 归一化后再返回：`config` 表是全仓共用的，
    平台条目可能是「真值非 dict」，直接透传会让 `config.gg` 变成字符串/数字，
    破坏 `{"spreadsheet_id","sheet_name"}` 这个响应契约。
    """
    db = database.get_db()
    try:
        uid = get_uid()
        conf = {p: hd.get_platform_config(db, uid, p) for p in hd.PLATFORMS}
    finally:
        db.close()
    return ok({"config": conf})


@huguan_dashboard_bp.route("/api/huguan/dashboard", methods=["POST"])
@jwt_required()
@huguan_required
def dashboard_config_save():
    """保存某平台的看板配置。表格 ID 接受裸 ID 或完整 URL。"""
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return err("请求体必须是 JSON 对象", 400)
    # 字段一律先 str() 兜底：给个数字或 null 不该炸成 500，按取不到值处理
    platform = str(data.get("platform") or "").strip()
    if platform not in hd.PLATFORMS:
        return err("platform 必须是 gg 或 tt", 400)

    from main import _parse_sheet_id
    ss_id = _parse_sheet_id(str(data.get("spreadsheet_id") or "").strip())
    sheet_name = str(data.get("sheet_name") or "").strip()

    db = database.get_db()
    try:
        hd.save_config(db, get_uid(), platform, ss_id, sheet_name)
    finally:
        db.close()
    return ok({"message": "配置已保存"})
```

- [ ] **Step 6: 注册 blueprint**

在 `py/main.py:361`（`app.register_blueprint(tt_accounts_bp)`）之后插入：

```python
# 户管看板路由
from routes.huguan_dashboard_routes import huguan_dashboard_bp
app.register_blueprint(huguan_dashboard_bp)
```

- [ ] **Step 7: 跑测试确认通过**

Run: `cd py && python -m pytest tests/test_huguan_dashboard.py -q`
Expected: PASS（聚焦 ≥ 52 passed：Task 1–4 实测 42 条 + 本任务 7 条 + 审查修复 3 条）

- [ ] **Step 8: 跑全量测试确认无回归**

Run: `cd py && python -m pytest tests/ -q`
Expected: PASS（全量 ≥ 476 passed，不得低于上一任务实测值）

- [ ] **Step 9: 提交**

```bash
git add py/routes/decorators.py py/huguan_dashboard.py py/routes/huguan_dashboard_routes.py py/main.py py/tests/test_huguan_dashboard.py
git commit -m "feat: 户管看板配置读写接口与户管限定装饰器"
```

---

## Task 6: 差异比对（五类）+ 名称解析

**Files:**
- Modify: `py/huguan_dashboard.py`
- Test: `py/tests/test_huguan_dashboard.py`

**Interfaces:**
- Consumes: `parse_row`、`effective_owner_name`、`is_dead`、`COLUMN_SPEC`
- Produces:
  - `resolve_owner_id(db, name: str) -> int | None`
  - `resolve_named_id(db, sql: str, params: tuple) -> int | None` — 唯一命中才返回
  - `resolve_status_id(db, name: str, owner_id, platform: str) -> int | None` — 查不到则在该 owner 的**该平台**下新建
  - `build_diff(db, parsed_rows: list, platform: str) -> dict` — 返回 `{"to_create": [...], "to_update": [...], "owner_changes": [...], "to_skip": [...], "warnings": [...], "summary": {...}}`
  - 每个 diff 项都带 `"row"`（表里 1-indexed 行号，供前端回传确认）

- [ ] **Step 1: 写失败的测试**

追加到 `py/tests/test_huguan_dashboard.py`：

```python
# ---------- Task 6: 差异比对 ----------

def _seed(db, username, display_name, role="user", platform="gg"):
    db.execute("INSERT INTO users(username, password, role, display_name, platform) "
               "VALUES(?,?,?,?,?)", (username, "x", role, display_name, platform))
    db.commit()
    return db.execute("SELECT id FROM users WHERE username=?", (username,)).fetchone()["id"]


def _seed_account(db, account_id, owner_id, **over):
    cols = {"account_id": account_id, "name": account_id, "owner_id": owner_id,
            "timezone": "", "death_date": "", "deleted_at": None}
    cols.update(over)
    keys = ", ".join(cols)
    marks = ", ".join("?" for _ in cols)
    db.execute(f"INSERT INTO accounts({keys}) VALUES({marks})", tuple(cols.values()))
    db.commit()
    return db.execute("SELECT id FROM accounts WHERE account_id=?", (account_id,)).fetchone()["id"]


class TestResolvers:
    def test_resolve_owner_prefers_display_name(self, client):
        from huguan_dashboard import resolve_owner_id
        db = database.get_db()
        uid = _seed(db, "_r1", "张三")
        assert resolve_owner_id(db, "张三") == uid
        db.close()

    def test_resolve_owner_falls_back_to_username(self, client):
        from huguan_dashboard import resolve_owner_id
        db = database.get_db()
        uid = _seed(db, "_r2", "")
        assert resolve_owner_id(db, "_r2") == uid
        db.close()

    def test_ambiguous_name_returns_none(self, client):
        """名称命中 ≥2 条 → None（规格 §8.4：该列不落库）。"""
        from huguan_dashboard import resolve_owner_id
        db = database.get_db()
        _seed(db, "_r3a", "重名")
        _seed(db, "_r3b", "重名")
        assert resolve_owner_id(db, "重名") is None
        db.close()

    def test_unknown_name_returns_none(self, client):
        from huguan_dashboard import resolve_owner_id
        db = database.get_db()
        assert resolve_owner_id(db, "查无此人") is None
        assert resolve_owner_id(db, "") is None
        db.close()

    def test_resolve_status_creates_under_owner(self, client):
        """按 owner + 平台双作用域：同名同 owner 但平台不同必须是两行。

        account_statuses.platform 默认 'gg'（database.py:153），不显式写平台
        会让 TT 的状态落进 gg 命名空间（状态下拉按平台过滤，main.py:6059）。
        """
        from huguan_dashboard import resolve_status_id
        db = database.get_db()
        uid = _seed(db, "_r4", "王五")
        sid = resolve_status_id(db, "待优化", uid, "gg")
        db.commit()
        row = db.execute("SELECT owner_id, platform FROM account_statuses WHERE id=?",
                         (sid,)).fetchone()
        assert row["owner_id"] == uid
        assert row["platform"] == "gg"
        # 再解析同名同平台，应复用同一行而不是重复新建
        assert resolve_status_id(db, "待优化", uid, "gg") == sid
        # 同名同 owner 换平台 → 另一行，且平台正确
        sid_tt = resolve_status_id(db, "待优化", uid, "tt")
        db.commit()
        assert sid_tt != sid
        assert db.execute("SELECT platform FROM account_statuses WHERE id=?",
                          (sid_tt,)).fetchone()["platform"] == "tt"
        assert resolve_status_id(db, "待优化", uid, "tt") == sid_tt
        db.close()


class TestBuildDiff:
    def _prepare(self, client):
        db = database.get_db()
        u1 = _seed(db, "_bd_zhang", "张三")
        u2 = _seed(db, "_bd_li", "李四")
        return db, u1, u2

    def test_new_account_goes_to_create(self, client):
        from huguan_dashboard import build_diff, parse_row
        db, u1, _ = self._prepare(client)
        parsed = [dict(parse_row(["", "", "NEW-1", "", "", "", "张三"], "gg"), row=2)]
        diff = build_diff(db, parsed, "gg")
        assert len(diff["to_create"]) == 1
        assert diff["to_create"][0]["account_id"] == "NEW-1"
        assert diff["to_create"][0]["owner_id"] == u1
        db.close()

    def test_new_account_without_owner_leaves_null(self, client):
        """规格 §7.4：运营列空着就空着，户管随时可以改。"""
        from huguan_dashboard import build_diff, parse_row
        db, _, _ = self._prepare(client)
        parsed = [dict(parse_row(["", "", "NEW-2"], "gg"), row=2)]
        diff = build_diff(db, parsed, "gg")
        assert diff["to_create"][0]["owner_id"] is None
        db.close()

    def test_existing_deleted_account_is_skipped(self, client):
        from huguan_dashboard import build_diff, parse_row
        db, u1, _ = self._prepare(client)
        _seed_account(db, "DEL-1", u1, deleted_at="2026-09-01 00:00:00")
        parsed = [dict(parse_row(["", "", "DEL-1"], "gg"), row=2)]
        diff = build_diff(db, parsed, "gg")
        assert len(diff["to_skip"]) == 1
        assert diff["to_create"] == []
        db.close()

    def test_owner_channel_overrides_current_owner(self, client):
        """规格 §7.1 + 规则 1：重新分配 压过 运营。"""
        from huguan_dashboard import build_diff, parse_row
        db, u1, u2 = self._prepare(client)
        _seed_account(db, "OWN-1", u1)
        # G=张三（当前）、H=李四（重新分配）
        parsed = [dict(parse_row(["", "", "OWN-1", "", "", "", "张三", "李四"], "gg"), row=2)]
        diff = build_diff(db, parsed, "gg")
        assert len(diff["owner_changes"]) == 1
        assert diff["owner_changes"][0]["to_owner_id"] == u2
        assert diff["owner_changes"][0]["from"] == "张三"
        assert diff["owner_changes"][0]["to"] == "李四"
        db.close()

    def test_matching_owner_produces_no_change(self, client):
        from huguan_dashboard import build_diff, parse_row
        db, u1, _ = self._prepare(client)
        _seed_account(db, "OWN-2", u1)
        parsed = [dict(parse_row(["", "", "OWN-2", "", "", "", "张三"], "gg"), row=2)]
        assert build_diff(db, parsed, "gg")["owner_changes"] == []
        db.close()

    def test_unknown_owner_is_warning_not_change(self, client):
        from huguan_dashboard import build_diff, parse_row
        db, u1, _ = self._prepare(client)
        _seed_account(db, "OWN-3", u1)
        parsed = [dict(parse_row(["", "", "OWN-3", "", "", "", "查无此人"], "gg"), row=2)]
        diff = build_diff(db, parsed, "gg")
        assert diff["owner_changes"] == []
        assert any("查无此人" in w["message"] for w in diff["warnings"])
        db.close()

    def test_blank_owner_keeps_existing_owner(self, client):
        """规格 §7.4：表里两列都空时，不得把系统里已有的归属清掉。"""
        from huguan_dashboard import build_diff, parse_row
        db, u1, _ = self._prepare(client)
        _seed_account(db, "OWN-4", u1)
        parsed = [dict(parse_row(["", "", "OWN-4"], "gg"), row=2)]
        assert build_diff(db, parsed, "gg")["owner_changes"] == []
        db.close()

    def test_missing_account_id_is_warning(self, client):
        from huguan_dashboard import build_diff, parse_row
        db, _, _ = self._prepare(client)
        parsed = [dict(parse_row(["", "", "   "], "gg"), row=7)]
        diff = build_diff(db, parsed, "gg")
        assert diff["to_create"] == []
        assert any(w["row"] == 7 for w in diff["warnings"])
        db.close()

    def test_ambiguous_mcc_name_is_warning(self, client):
        """重名 MCC 不落库，但同一行的其他列照常更新。

        ★ `to_update` 必须非空，否则下面那条断言是**空集上的恒真式**。
        所以这里让 I 列（时区）与库里不同，先制造出一条真实更新。
        """
        from huguan_dashboard import build_diff, parse_row
        db, u1, _ = self._prepare(client)
        _seed_account(db, "MCCACC", u1)
        db.execute("INSERT INTO mcc(name, mcc_id) VALUES('同名MCC','1')")
        db.execute("INSERT INTO mcc(name, mcc_id) VALUES('同名MCC','2')")
        db.commit()
        parsed = [dict(parse_row(["", "", "MCCACC", "同名MCC", "", "", "", "",
                                  "Asia/Shanghai"], "gg"), row=2)]
        diff = build_diff(db, parsed, "gg")
        assert len(diff["to_update"]) == 1          # 非空，下面的断言才有意义
        assert diff["to_update"][0]["fields"] == {"timezone": "Asia/Shanghai"}
        assert "mcc_id" not in diff["to_update"][0]["fields"]
        assert any("同名MCC" in w["message"] for w in diff["warnings"])
        db.close()

    def test_summary_counts(self, client):
        from huguan_dashboard import build_diff, parse_row
        db, u1, u2 = self._prepare(client)
        _seed_account(db, "S-1", u1)
        parsed = [
            dict(parse_row(["", "", "S-1", "", "", "", "张三", "李四"], "gg"), row=2),
            dict(parse_row(["", "", "S-NEW", "", "", "", "张三"], "gg"), row=3),
        ]
        s = build_diff(db, parsed, "gg")["summary"]
        assert s["total_in_sheet"] == 2
        assert s["owner_changes"] == 1
        assert s["new_accounts"] == 1
        db.close()
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd py && python -m pytest tests/test_huguan_dashboard.py -q`
Expected: FAIL — `ImportError: cannot import name 'build_diff'`

- [ ] **Step 3: 实现**

追加到 `py/huguan_dashboard.py`：

```python
def resolve_named_id(db, sql: str, params: tuple = ()) -> int | None:
    """按名称查唯一主键。命中 0 条或 ≥2 条都返回 None（规格 §8.4）。

    重名时不猜 —— 猜错就是把账户挂到了错误的 MCC / BC / 渠道上。
    """
    rows = db.execute(sql, params).fetchall()
    return rows[0]["id"] if len(rows) == 1 else None


def resolve_owner_id(db, name: str):
    """归属名 → users.id。display_name 优先，回退 username。"""
    name = (name or "").strip()
    if not name:
        return None
    for sql in ("SELECT id FROM users WHERE display_name=?",
                "SELECT id FROM users WHERE username=?"):
        rows = db.execute(sql, (name,)).fetchall()
        if len(rows) == 1:
            return rows[0]["id"]
        if len(rows) > 1:
            return None
    return None


def resolve_status_id(db, name: str, owner_id, platform: str):
    """状态名 → account_statuses.id，按「该账户的 owner + 平台」作用域。

    **必须带 platform**：account_statuses.platform 默认 'gg'（database.py:153），
    唯一约束是 (name, platform)（database.py:1225），而状态下拉按平台过滤
    （main.py:6059 `/api/statuses/list`）。不写平台会让 TT 同步新建的状态落进
    gg 命名空间 —— TT 下拉里看不见，反而出现在 GG 下拉里。
    既有代码的两种写法可对照：GG 侧靠默认值吃 'gg'（main.py:4042/4184/4944/5068），
    TT 侧显式写 'tt'（main.py:6085、tt_accounts_routes.py:69）。
    """
    name = (name or "").strip()
    if not name:
        return None
    # 查重也必须带 platform：唯一约束含 platform，同名不同平台可并存，
    # 不带平台过滤会命中 2 行而 fetchone() 任取一条。
    row = db.execute(
        "SELECT id FROM account_statuses WHERE name=? AND owner_id IS ? AND platform=?",
        (name, owner_id, platform)).fetchone()
    if row:
        return row["id"]
    db.execute("INSERT INTO account_statuses(name, owner_id, platform) VALUES(?,?,?)",
               (name, owner_id, platform))
    return db.execute("SELECT last_insert_rowid() AS id").fetchone()["id"]


# 各可读列 → (解析器种类, 查名 SQL 模板)
_SQL_MCC = "SELECT id FROM mcc WHERE name=?"
_SQL_AGENT_GG = "SELECT id FROM agents WHERE name=? AND (platform='gg' OR platform IS NULL)"
_SQL_AGENT_TT = "SELECT id FROM agents WHERE name=? AND platform='tt'"
_SQL_BC = "SELECT id FROM tt_bcs WHERE name=?"


def _resolve_field(db, platform: str, field: str, value: str, owner_id):
    """把表里的一个名称解析成系统主键；不认识的字段返回 (True, None) 表示无需解析。

    返回 (ok, resolved)：ok=False 表示该列要记 warning 且不落库。
    """
    if field == "mcc_name":
        return True, resolve_named_id(db, _SQL_MCC, (value,))
    if field == "agent_name":
        sql = _SQL_AGENT_TT if platform == "tt" else _SQL_AGENT_GG
        return True, resolve_named_id(db, sql, (value,))
    if field == "bc_name":
        return True, resolve_named_id(db, _SQL_BC, (value,))
    if field == "status_name":
        return True, resolve_status_id(db, value, owner_id, platform)
    return False, None


# 可直接覆盖的文本列（不需要名称解析）
_PLAIN_TEXT_FIELDS = {
    "gg": ("acquired_date", "timezone"),
    "tt": ("acquired_date", "country", "timezone", "consumption", "remark"),
}


def _parseable_fields(platform: str) -> tuple:
    """该平台可读且需要名称解析的字段（值非空时才解析）。"""
    return ("mcc_name", "agent_name", "bc_name", "status_name")


def build_diff(db, parsed_rows: list, platform: str) -> dict:
    """表 → 系统 的逐行比对，产出五类差异（规格 §8.3）。

    parsed_rows: [{"row": 表里行号, **parse_row(...)}]
    每个产出项都带 "row"，供前端回传确认。
    """
    key_field = ACCOUNT_KEY_FIELD[platform]
    ids = [p.get("account_id") for p in parsed_rows if p.get("account_id")]

    existing_map = {}
    if ids:
        marks = ",".join("?" for _ in ids)
        table = "tt_accounts" if platform == "tt" else "accounts"
        rows = db.execute(
            f"""SELECT a.*, u.display_name AS owner_display, u.username AS owner_username
                FROM {table} a LEFT JOIN users u ON a.owner_id = u.id
                WHERE a.{key_field} IN ({marks})""",
            ids,
        ).fetchall()
        for r in rows:
            existing_map[r[key_field]] = dict(r)

    to_create, to_update, owner_changes, to_skip, warnings = [], [], [], [], []

    for p in parsed_rows:
        row_no = p.get("row")
        aid = p.get("account_id", "")
        if not aid:
            warnings.append({"row": row_no, "message": "账户ID为空，跳过"})
            continue

        want_owner_name = effective_owner_name(p)
        want_owner_id = None
        if want_owner_name:
            want_owner_id = resolve_owner_id(db, want_owner_name)
            if want_owner_id is None:
                warnings.append({"row": row_no,
                                 "message": f"运营「{want_owner_name}」无法识别，已跳过归属变更"})

        existing = existing_map.get(aid)
        if existing is None:
            to_create.append({
                "row": row_no,
                "account_id": aid,
                "owner_id": want_owner_id,
                "owner_name": want_owner_name,
                # 键名刻意不叫 "cells"：本模块里 "cells" 一律指「表列字母 → 单元格值」
                # （Task 4 的 update_rows_by_account_id 契约），这里装的是
                # 「数据库列名 → 值」，供 apply_diff 拼 INSERT。两者同名会被误用。
                "db_values": _collect_updates(db, platform, p, want_owner_id, row_no, warnings),
            })
            continue

        if existing.get("deleted_at"):
            to_skip.append({"row": row_no, "account_id": aid,
                            "reason": "系统中已逻辑删除，不动"})
            continue

        cur_owner = existing.get("owner_id")
        if want_owner_id is not None and int(cur_owner or 0) != int(want_owner_id):
            owner_changes.append({
                "row": row_no,
                "account_id": aid,
                "existing_id": existing["id"],
                "from": existing.get("owner_display") or existing.get("owner_username") or "",
                "to": want_owner_name,
                "to_owner_id": want_owner_id,
            })

        # 归属变更后，状态/渠道等要按新 owner 作用域解析
        scope_owner = want_owner_id if want_owner_id is not None else cur_owner
        fields = _collect_updates(db, platform, p, scope_owner, row_no, warnings)
        changed = {k: v for k, v in fields.items()
                   if not _same_as_existing(db, platform, existing, k, v)}
        if changed:
            to_update.append({"row": row_no, "account_id": aid,
                              "existing_id": existing["id"], "fields": changed})

    return {
        "to_create": to_create,
        "to_update": to_update,
        "owner_changes": owner_changes,
        "to_skip": to_skip,
        "warnings": warnings,
        "summary": {
            "total_in_sheet": len(parsed_rows),
            "new_accounts": len(to_create),
            "updates": len(to_update),
            "owner_changes": len(owner_changes),
            "skipped": len(to_skip),
            "warnings": len(warnings),
        },
    }


def _collect_updates(db, platform, p, owner_id, row_no, warnings) -> dict:
    """把一行解析结果里「要写进系统」的字段收集成 {字段名: 值}。

    名称类字段先解析成主键，解析不唯一则记 warning 并丢弃该字段。
    """
    out = {}
    for f in _PLAIN_TEXT_FIELDS[platform]:
        out[f] = p.get(f, "")
    for f in _parseable_fields(platform):
        value = (p.get(f) or "").strip()
        if not value:
            continue
        _known, resolved = _resolve_field(db, platform, f, value, owner_id)
        if not _known:
            continue
        if resolved is None:
            warnings.append({"row": row_no,
                             "message": f"{f}「{value}」无法唯一匹配，已跳过该列"})
            continue
        out[_target_column(platform, f)] = resolved
    out["_is_dead"] = is_dead(p)
    return out


def _target_column(platform: str, field: str) -> str:
    """解析后的字段名 → 真实数据库列名。"""
    return {
        "mcc_name": "mcc_id",
        "agent_name": "agent_id",
        "bc_name": "bc_id",
        "status_name": "status_id",
    }[field]


def _same_as_existing(db, platform, existing: dict, key: str, value) -> bool:
    """比较待写值与库里当前值，决定是否真的需要更新（避免无意义写入）。"""
    if key == "_is_dead":
        cur_dead = bool((existing.get("death_date") or "").strip())
        return cur_dead == bool(value)
    cur = existing.get(key)
    if cur is None and value in (None, ""):
        return True
    return str(cur if cur is not None else "") == str(value if value is not None else "")
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd py && python -m pytest tests/test_huguan_dashboard.py -q`
Expected: PASS（聚焦 ≥ 67 passed：上一任务实测 52 条 + 本任务 15 条）

- [ ] **Step 5: 跑全量测试确认无回归**

Run: `cd py && python -m pytest tests/ -q`
Expected: PASS（全量 ≥ 491 passed，不得低于上一任务实测值）

- [ ] **Step 6: 提交**

```bash
git add py/huguan_dashboard.py py/tests/test_huguan_dashboard.py
git commit -m "feat: 户管看板差异比对与名称解析（唯一命中才落库）"
```

---

## Task 7: 同步端点（差异确认 + 落库 + 归属收尾）

**Files:**
- Modify: `py/huguan_dashboard.py`（新增 `apply_diff`）
- Modify: `py/routes/huguan_dashboard_routes.py`（新增 `/sync`）
- Test: `py/tests/test_huguan_dashboard.py`

**Interfaces:**
- Consumes: `build_diff`、`cells_for_row`、`OWNER_CHANNEL_COL`、`OWNER_COL`、`get_platform_config`、`update_rows_by_account_id`、`_text`
- Produces:
  - `apply_diff(db, diff: dict, platform: str, confirmed: dict, user_id: int) -> dict` — `confirmed` 形如 `{"create": [2,5], "update": [7], "owner": [9]}`（值为表里行号）。返回 `{"created": n, "updated": n, "owner_changed": n, "errors": [...]}`
  - `owner_channel_cells(rows: list, platform: str, value: str) -> list` — 构造只写归属变更通道列的 rows
  - HTTP：`POST /api/huguan/dashboard/sync`

- [ ] **Step 1: 写失败的测试**

追加到 `py/tests/test_huguan_dashboard.py`：

```python
# ---------- Task 7: 同步落库 ----------

def _stub_sheets(monkeypatch, captured):
    """把 update_rows_by_account_id 换成桩，记录调用（同步执行，见下）。"""
    import google_sheets_service as gs
    import main as m

    def _fake(service, spreadsheet_id, sheet_name, rows, key_col="C"):
        captured.append({"spreadsheet_id": spreadsheet_id, "sheet_name": sheet_name,
                         "rows": rows})
        return {"updated": len(rows), "not_found": []}

    monkeypatch.setattr(gs, "update_rows_by_account_id", _fake)
    monkeypatch.setattr(gs, "build_service", lambda path: object())
    # 端点经 main._sync_sheets_background 起**后台线程**写表。不拦住它，断言就会
    # 和后台线程抢时间 —— 本机快时偶然通过、CI 慢时红，是最难查的一类间歇失败。
    # 换成直接调用，让「后台」在测试里同步发生。端点用的是函数体内
    # `from main import ...`，调用时才取属性，故此处 patch 生效。
    monkeypatch.setattr(m, "_sync_sheets_background", lambda fn, on_fail: fn())


class TestOwnerChannelCells:
    def test_only_channel_column_is_written(self):
        """规格 §7.2 规则 3②：收尾只清 重新分配 / 换绑情况 这一列。"""
        from huguan_dashboard import owner_channel_cells
        got = owner_channel_cells(
            [{"row": 2, "account_id": "A1"}, {"row": 3, "account_id": "A2"}], "gg", "")
        assert got == [{"account_id": "A1", "cells": {"H": ""}},
                       {"account_id": "A2", "cells": {"H": ""}}]

    def test_tt_uses_its_own_column(self):
        from huguan_dashboard import owner_channel_cells
        got = owner_channel_cells([{"row": 2, "account_id": "A1"}], "tt", "李四")
        assert got == [{"account_id": "A1", "cells": {"L": "李四"}}]


class TestApplyDiff:
    def _setup(self, client):
        db = database.get_db()
        u1 = _seed(db, "_ap_zhang", "张三")
        u2 = _seed(db, "_ap_li", "李四")
        return db, u1, u2

    def test_creates_confirmed_accounts_only(self, client):
        from huguan_dashboard import build_diff, parse_row, apply_diff
        db, u1, _ = self._setup(client)
        parsed = [
            dict(parse_row(["", "", "C-1", "", "", "", "张三"], "gg"), row=2),
            dict(parse_row(["", "", "C-2", "", "", "", "张三"], "gg"), row=3),
        ]
        diff = build_diff(db, parsed, "gg")
        res = apply_diff(db, diff, "gg", {"create": [2]}, user_id=u1)
        assert res["created"] == 1
        assert db.execute("SELECT COUNT(*) AS c FROM accounts WHERE account_id='C-1'").fetchone()["c"] == 1
        assert db.execute("SELECT COUNT(*) AS c FROM accounts WHERE account_id='C-2'").fetchone()["c"] == 0
        db.close()

    def test_create_with_null_owner(self, client):
        from huguan_dashboard import build_diff, parse_row, apply_diff
        db, u1, _ = self._setup(client)
        parsed = [dict(parse_row(["", "", "C-3"], "gg"), row=2)]
        apply_diff(db, build_diff(db, parsed, "gg"), "gg", {"create": [2]}, user_id=u1)
        row = db.execute("SELECT owner_id FROM accounts WHERE account_id='C-3'").fetchone()
        assert row["owner_id"] is None
        db.close()

    def test_owner_change_applies_to_new_owner(self, client):
        """归属变更只改 owner_id；death_date 归 B 列「是否封户」管，两者不相干。"""
        from huguan_dashboard import build_diff, parse_row, apply_diff
        db, u1, u2 = self._setup(client)
        _seed_account(db, "OC-1", u1)
        parsed = [dict(parse_row(["", "", "OC-1", "", "", "", "张三", "李四"], "gg"), row=2)]
        res = apply_diff(db, build_diff(db, parsed, "gg"), "gg", {"owner": [2]}, user_id=u1)
        assert res["owner_changed"] == 1
        row = db.execute("SELECT owner_id, death_date FROM accounts "
                         "WHERE account_id='OC-1'").fetchone()
        assert row["owner_id"] == u2
        assert not (row["death_date"] or "").strip()
        db.close()

    def test_status_dead_sets_death_date(self, client):
        from huguan_dashboard import build_diff, parse_row, apply_diff
        db, u1, _ = self._setup(client)
        _seed_account(db, "ST-1", u1)
        parsed = [dict(parse_row(["", "是", "ST-1", "", "", "", "张三"], "gg"), row=2)]
        apply_diff(db, build_diff(db, parsed, "gg"), "gg", {"update": [2]}, user_id=u1)
        row = db.execute("SELECT death_date FROM accounts WHERE account_id='ST-1'").fetchone()
        assert (row["death_date"] or "").strip() != ""
        db.close()

    def test_unconfirmed_rows_are_not_applied(self, client):
        from huguan_dashboard import build_diff, parse_row, apply_diff
        db, u1, u2 = self._setup(client)
        _seed_account(db, "UN-1", u1)
        parsed = [dict(parse_row(["", "", "UN-1", "", "", "", "张三", "李四"], "gg"), row=2)]
        res = apply_diff(db, build_diff(db, parsed, "gg"), "gg", {}, user_id=u1)
        assert res["owner_changed"] == 0
        assert db.execute("SELECT owner_id FROM accounts WHERE account_id='UN-1'").fetchone()["owner_id"] == u1
        db.close()


class TestSyncEndpoint:
    def test_dry_run_does_not_touch_db(self, client, monkeypatch):
        hg, uid = _create_user(client, "_syn_dry", role="huguan")
        db = database.get_db()
        hd_conf = {"gg": {"spreadsheet_id": "SS", "sheet_name": "S"}}
        db.execute("INSERT OR REPLACE INTO config(key,value) VALUES(?,?)",
                   (f"huguan_dashboard_{uid}", json.dumps(hd_conf)))
        db.commit()
        db.close()

        import google_sheets_service as gs
        monkeypatch.setattr(gs, "read_sheet_values",
                            lambda *a, **k: [["日期", "是否封户", "账户ID"],
                                             ["", "", "DRY-1"]])
        monkeypatch.setattr(gs, "build_service", lambda path: object())

        resp = client.post("/api/huguan/dashboard/sync", headers=hg,
                           json={"platform": "gg", "dry_run": True})
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["diff"]["summary"]["new_accounts"] == 1
        db = database.get_db()
        assert db.execute("SELECT COUNT(*) AS c FROM accounts WHERE account_id='DRY-1'").fetchone()["c"] == 0
        db.close()

    def test_unconfigured_returns_400(self, client):
        hg, _ = _create_user(client, "_syn_nocfg", role="huguan")
        resp = client.post("/api/huguan/dashboard/sync", headers=hg,
                           json={"platform": "gg", "dry_run": True})
        assert resp.status_code == 400

    def test_non_huguan_403(self, client):
        h, _ = _create_user(client, "_syn_user", role="user")
        assert client.post("/api/huguan/dashboard/sync", headers=h,
                           json={"platform": "gg", "dry_run": True}).status_code == 403

    def test_applies_owner_change_and_rewrites_channel(self, client, monkeypatch):
        """规格 §7.2 规则 3② + 规则 4：应用后回写运营列、清空重新分配列。"""
        hg, uid = _create_user(client, "_syn_apply", role="huguan")
        db = database.get_db()
        target = _seed(db, "_syn_target", "李四")
        db.execute("INSERT OR REPLACE INTO config(key,value) VALUES(?,?)",
                   (f"huguan_dashboard_{uid}",
                    json.dumps({"gg": {"spreadsheet_id": "SS", "sheet_name": "S"}})))
        db.execute("INSERT INTO accounts(account_id, name, owner_id) VALUES('AP-1','AP-1',?)", (uid,))
        db.commit()
        db.close()

        import google_sheets_service as gs
        monkeypatch.setattr(gs, "read_sheet_values", lambda *a, **k: [
            ["日期", "是否封户", "账户ID", "MCC", "国家", "所属渠道", "运营", "重新分配"],
            ["", "", "AP-1", "", "", "", "  户管本人 ", "李四"],
        ])
        captured = []
        _stub_sheets(monkeypatch, captured)

        resp = client.post("/api/huguan/dashboard/sync", headers=hg,
                           json={"platform": "gg", "dry_run": False,
                                 "confirmed": {"owner": [2]}})
        assert resp.status_code == 200
        db = database.get_db()
        assert db.execute("SELECT owner_id FROM accounts WHERE account_id='AP-1'").fetchone()["owner_id"] == target
        db.close()

        # 收尾写入分两次：先回写运营列(G)，再清空变更通道列(H)。
        # 两列刻意分开写 —— owner_channel_cells 只含 H，不会顺手冲掉别的手工列。
        g_rows = [r for c in captured for r in c["rows"] if "G" in r["cells"]]
        assert {r["account_id"]: r["cells"]["G"] for r in g_rows}["AP-1"] == "李四"
        h_rows = [r for c in captured for r in c["rows"] if "H" in r["cells"]]
        assert h_rows, "应收尾清空归属变更通道列"
        assert {r["account_id"]: r["cells"]["H"] for r in h_rows}["AP-1"] == ""

    def test_malformed_confirmed_is_400(self, client, monkeypatch):
        """畸形 confirmed 只能是 4xx，不能把 AttributeError 带成 500。"""
        hg, uid = _create_user(client, "_syn_badcf", role="huguan")
        db = database.get_db()
        db.execute("INSERT OR REPLACE INTO config(key,value) VALUES(?,?)",
                   (f"huguan_dashboard_{uid}",
                    json.dumps({"gg": {"spreadsheet_id": "SS", "sheet_name": "S"}})))
        db.commit()
        db.close()

        import google_sheets_service as gs
        monkeypatch.setattr(gs, "read_sheet_values",
                            lambda *a, **k: [["日期", "是否封户", "账户ID"], ["", "", "BAD-1"]])
        monkeypatch.setattr(gs, "build_service", lambda path: object())

        # 外层不是 dict，以及值是数组以外的类型，两条路径都要挡在 4xx
        for bad in ([1, 2], "abc", 5, {"create": 2}, {"owner": "2"}):
            resp = client.post("/api/huguan/dashboard/sync", headers=hg,
                               json={"platform": "gg", "dry_run": False, "confirmed": bad})
            assert resp.status_code == 400, f"confirmed={bad!r} 应返回 400"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd py && python -m pytest tests/test_huguan_dashboard.py -q`
Expected: FAIL — `ImportError: cannot import name 'owner_channel_cells'`

- [ ] **Step 3: 实现 `owner_channel_cells` 与 `apply_diff`**

追加到 `py/huguan_dashboard.py`：

```python
def owner_channel_cells(rows: list, platform: str, value: str) -> list:
    """构造只写归属变更通道列的 rows（规格 §7.2 规则 3②）。

    刻意只含这一列 —— 收尾写入若顺手带上别的列，就会把户管在表里的
    其他手工改动一起冲掉。
    """
    col = OWNER_CHANNEL_COL[platform]
    return [{"account_id": r["account_id"], "cells": {col: value}} for r in rows]


def apply_diff(db, diff: dict, platform: str, confirmed: dict, user_id: int) -> dict:
    """执行户管确认过的差异（规格 §8.3 步骤 8）。

    confirmed: {"create": [行号...], "update": [行号...], "owner": [行号...]}
               缺哪个键就完全不执行该类别。
    """
    conf = confirmed or {}
    created = updated = owner_changed = 0
    errors = []
    applied_owner_rows = []

    table = "tt_accounts" if platform == "tt" else "accounts"
    key_field = ACCOUNT_KEY_FIELD[platform]

    for item in diff.get("to_create", []):
        if item["row"] not in conf.get("create", []):
            continue
        try:
            # db_values 装的是「数据库列名 → 值」（见 build_diff 的 to_create），
            # 与表列字母的 cells 不是一回事，切勿混用。
            src = dict(item.get("db_values") or {})
            # _is_dead 是合成标记，不是数据库列，必须先摘掉再拼 INSERT
            want_dead = bool(src.pop("_is_dead", False))
            src[key_field] = item["account_id"]
            src["name"] = item["account_id"]
            src["owner_id"] = item.get("owner_id")
            src["death_date"] = ""
            cols = ", ".join(src)
            marks = ", ".join("?" for _ in src)
            db.execute(f"INSERT INTO {table}({cols}) VALUES({marks})", tuple(src.values()))
            new_id = db.execute("SELECT last_insert_rowid() AS id").fetchone()["id"]
            _apply_death(db, platform, new_id, want_dead)
            created += 1
        except Exception as e:
            errors.append({"row": item["row"], "error": str(e)})

    for item in diff.get("to_update", []):
        if item["row"] not in conf.get("update", []):
            continue
        try:
            fields = dict(item.get("fields") or {})
            is_dead_val = fields.pop("_is_dead", None)
            if fields:
                sets = ", ".join(f"{k}=?" for k in fields)
                db.execute(f"UPDATE {table} SET {sets}, "
                           "updated_at=datetime('now','localtime') WHERE id=?",
                           tuple(fields.values()) + (item["existing_id"],))
            if is_dead_val is not None:
                _apply_death(db, platform, item["existing_id"], bool(is_dead_val))
            updated += 1
        except Exception as e:
            errors.append({"row": item["row"], "error": str(e)})

    for item in diff.get("owner_changes", []):
        if item["row"] not in conf.get("owner", []):
            continue
        try:
            db.execute(f"UPDATE {table} SET owner_id=?, "
                       "updated_at=datetime('now','localtime') WHERE id=?",
                       (item["to_owner_id"], item["existing_id"]))
            owner_changed += 1
            applied_owner_rows.append({"row": item["row"],
                                       "account_id": item["account_id"]})
        except Exception as e:
            errors.append({"row": item["row"], "error": str(e)})

    db.commit()
    return {"created": created, "updated": updated, "owner_changed": owner_changed,
            "applied_owner_rows": applied_owner_rows, "errors": errors}


def _apply_death(db, platform: str, account_pk: int, want_dead: bool) -> None:
    """按死亡标记同步 death_date（对照 main.py:4638 的既有语义）。"""
    table = "tt_accounts" if platform == "tt" else "accounts"
    if want_dead:
        db.execute(f"UPDATE {table} SET death_date=date('now','localtime'), "
                   "status_changed_date=datetime('now','localtime') WHERE id=?", (account_pk,))
    else:
        db.execute(f"UPDATE {table} SET death_date='' WHERE id=?", (account_pk,))
```

- [ ] **Step 4: 实现 sync 端点**

追加到 `py/routes/huguan_dashboard_routes.py`：

```python
@huguan_dashboard_bp.route("/api/huguan/dashboard/sync", methods=["POST"])
@jwt_required()
@huguan_required
def dashboard_sync():
    """表 → 系统：先出差异报告（dry_run=true），户管确认后再落库。

    归属门禁（规格 §8.2）：表地址一律取自该户管自己的配置，请求体不接受表地址，
    因此不存在「对着别人的表发起同步」这条路。
    """
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return err("请求体必须是 JSON 对象", 400)
    platform = str(data.get("platform") or "").strip()
    if platform not in hd.PLATFORMS:
        return err("platform 必须是 gg 或 tt", 400)

    uid = get_uid()
    db = database.get_db()
    try:
        conf = hd.get_platform_config(db, uid, platform)
        if not conf["spreadsheet_id"] or not conf["sheet_name"]:
            return err("请先在设置页配置户管看板的表格 ID 与工作表名", 400)

        import google_sheets_service as gs
        from main import _GOOGLE_SHEETS_CONFIG
        service = gs.build_service(_GOOGLE_SHEETS_CONFIG["credentials_path"])
        grid = gs.read_sheet_values(service, conf["spreadsheet_id"],
                                   conf["sheet_name"], hd.READ_RANGE[platform])

        # 第 1 行是表头；不跳任何数据行（户管看板没有「是否解绑」列可用作跳过标记）
        parsed_rows = []
        for i, values in enumerate(grid[1:], start=2):
            parsed = hd.parse_row(values, platform)
            parsed["row"] = i
            parsed_rows.append(parsed)

        diff = hd.build_diff(db, parsed_rows, platform)

        if data.get("dry_run", True):
            return ok({"diff": diff})

        # confirmed 期望 {"create": [行号], "update": [行号], "owner": [行号]}。
        # `or {}` 兜不住真值非 dict（[1,2] / "abc"）→ apply_diff 里 conf.get 炸 500；
        # 值不是数组同样炸（`2 not in 2` → TypeError）。两层都在这里挡住。
        confirmed = data.get("confirmed")
        if not isinstance(confirmed, dict):
            return err("confirmed 必须是对象", 400)
        for k in ("create", "update", "owner"):
            v = confirmed.get(k)
            if v is not None and not isinstance(v, list):
                return err(f"confirmed.{k} 必须是行号数组", 400)

        result = hd.apply_diff(db, diff, platform, confirmed, user_id=uid)

        # 规格 §7.2 规则 3② + 规则 4：应用了归属变更的行，回写运营列并清空变更通道列
        applied = result.pop("applied_owner_rows", [])
        if applied:
            rows = []
            for item in applied:
                new_owner = next((c["to"] for c in diff["owner_changes"]
                                  if c["row"] == item["row"]), "")
                rows.append({"account_id": item["account_id"],
                             "cells": {hd.OWNER_COL[platform]: new_owner}})
            _write_background(service, conf, rows)
            _write_background(service, conf,
                              hd.owner_channel_cells(applied, platform, ""))
    finally:
        db.close()

    return ok({"result": result, "diff": diff})


def _write_background(service, conf, rows):
    """后台写表；失败只记日志，不影响同步接口的返回（对照 main.py:5006 的做法）。"""
    import logging
    log = logging.getLogger("gg-server")

    def _do():
        import google_sheets_service as gs
        gs.update_rows_by_account_id(service, conf["spreadsheet_id"],
                                     conf["sheet_name"], rows)

    from main import _sync_sheets_background
    _sync_sheets_background(_do, lambda s, e: log.warning("户管看板回写失败: %s", e) if e else None)
```

- [ ] **Step 5: 跑测试确认通过**

Run: `cd py && python -m pytest tests/test_huguan_dashboard.py -q`
Expected: PASS（聚焦 ≥ 79 passed）

- [ ] **Step 6: 跑全量测试确认无回归**

Run: `cd py && python -m pytest tests/ -q`
Expected: PASS（全量 ≥ 503 passed，不得低于上一任务实测值）

- [ ] **Step 7: 提交**

```bash
git add py/huguan_dashboard.py py/routes/huguan_dashboard_routes.py py/tests/test_huguan_dashboard.py
git commit -m "feat: 户管看板从表同步（差异确认落库 + 归属变更收尾）"
```

---

## Task 8: 全量刷新端点 `push` + GG 触发点接入

**Files:**
- Modify: `py/huguan_dashboard.py`（新增 `push_rows`、`collect_rows_for_push`）
- Modify: `py/routes/huguan_dashboard_routes.py`（新增 `/push`）
- Modify: `py/main.py`（6 个 GG 触发点 + 注册 `/push`）
- Test: `py/tests/test_huguan_dashboard.py`

**Interfaces:**
- Consumes: `get_platform_config`、`cells_for_row`、`update_rows_by_account_id`
- Produces:
  - `collect_rows_for_push(db, platform, account_ids=None) -> list` — 生成 `[{"account_id","cells"}]`；`account_ids=None` 表示全部
  - `push_rows(user_id: int, platform: str, account_ids=None) -> None` — 未配置则静默返回；已配置则后台写表

- [ ] **Step 1: 写失败的测试**

追加到 `py/tests/test_huguan_dashboard.py`：

```python
# ---------- Task 8: 全量刷新 + GG 触发点 ----------

class TestCollectRowsForPush:
    def test_gg_rows_have_no_owner_channel(self, client):
        from huguan_dashboard import collect_rows_for_push
        db = database.get_db()
        u1 = _seed(db, "_push_u1", "张三")
        db.execute("INSERT INTO mcc(name, mcc_id) VALUES('MCC-P','9')")
        db.execute("INSERT INTO agents(name, platform) VALUES('渠道P','gg')")
        db.commit()
        mcc = db.execute("SELECT id FROM mcc WHERE name='MCC-P'").fetchone()["id"]
        ag = db.execute("SELECT id FROM agents WHERE name='渠道P'").fetchone()["id"]
        _seed_account(db, "P-1", u1, mcc_id=mcc, agent_id=ag, timezone="UTC")
        rows = collect_rows_for_push(db, "gg", ["P-1"])
        assert len(rows) == 1
        assert rows[0]["account_id"] == "P-1"
        assert rows[0]["cells"]["D"] == "MCC-P"
        assert rows[0]["cells"]["F"] == "渠道P"
        assert rows[0]["cells"]["G"] == "张三"
        assert "H" not in rows[0]["cells"]
        db.close()

    def test_missing_account_ids_skipped(self, client):
        from huguan_dashboard import collect_rows_for_push
        db = database.get_db()
        assert collect_rows_for_push(db, "gg", ["NOPE"]) == []
        db.close()

    def test_blank_display_name_falls_back_to_username(self, client):
        """运营的 display_name 是空串时，运营列写 username 而不是留空。

        仓库既有一致的写法是 Python 侧 `display_name or username`（main.py:4427/6738/6997）。
        SQL 里 `COALESCE(display_name, username, '')` 只回退 NULL，**漏掉空串**这一支 ——
        会把有归属的账户在表里写成「运营留空」。故两边都用 NULLIF 挡一层。
        """
        from huguan_dashboard import collect_rows_for_push
        db = database.get_db()
        u1 = _seed(db, "_push_blankgg", "")
        _seed_account(db, "P-BLANK", u1)
        rows = collect_rows_for_push(db, "gg", ["P-BLANK"])
        assert rows[0]["cells"]["G"] == "_push_blankgg"
        db.close()

    def test_tt_blank_display_name_falls_back_to_username(self, client):
        from huguan_dashboard import collect_rows_for_push
        db = database.get_db()
        u1 = _seed(db, "_push_blanktt", "")
        db.execute("INSERT INTO tt_accounts(advertiser_id, name, owner_id) "
                   "VALUES('TP-BLANK','TP-BLANK',?)", (u1,))
        db.commit()
        rows = collect_rows_for_push(db, "tt", ["TP-BLANK"])
        assert rows[0]["cells"]["G"] == "_push_blanktt"
        db.close()

    def test_tt_rows(self, client):
        from huguan_dashboard import collect_rows_for_push
        db = database.get_db()
        u1 = _seed(db, "_push_u2", "李四")
        db.execute("INSERT INTO tt_bcs(name) VALUES('BC-P')")
        db.commit()
        bc = db.execute("SELECT id FROM tt_bcs WHERE name='BC-P'").fetchone()["id"]
        db.execute("INSERT INTO tt_accounts(advertiser_id, name, owner_id, bc_id, country, "
                   "consumption, remark) VALUES('TP-1','TP-1',?,?,'US','9.9','备注Z')", (u1, bc))
        db.commit()
        rows = collect_rows_for_push(db, "tt", ["TP-1"])
        assert rows[0]["cells"]["D"] == "BC-P"
        assert rows[0]["cells"]["E"] == "US"
        assert rows[0]["cells"]["G"] == "李四"
        assert rows[0]["cells"]["J"] == "9.9"
        assert rows[0]["cells"]["M"] == "备注Z"
        assert "L" not in rows[0]["cells"]     # 换绑情况绝不自动回写
        db.close()


class TestPushEndpoint:
    def test_unconfigured_is_silent_noop(self, client, monkeypatch):
        """不是每个用户都是户管；未配置就静默跳过，不能报错。"""
        from huguan_dashboard import push_rows
        import huguan_dashboard as hd_mod
        called = []
        monkeypatch.setattr(hd_mod, "get_platform_config",
                            lambda db, uid, p: {"spreadsheet_id": "", "sheet_name": ""})
        push_rows(99999, "gg")
        assert called == []

    def test_push_writes_all_visible_accounts(self, client, monkeypatch):
        hg, uid = _create_user(client, "_push_ep", role="huguan")
        db = database.get_db()
        db.execute("INSERT OR REPLACE INTO config(key,value) VALUES(?,?)",
                   (f"huguan_dashboard_{uid}",
                    json.dumps({"gg": {"spreadsheet_id": "SS", "sheet_name": "S"}})))
        _seed_account(db, "PE-1", uid)
        db.commit()
        db.close()

        captured = []
        _stub_sheets(monkeypatch, captured)
        resp = client.post("/api/huguan/dashboard/push", headers=hg, json={"platform": "gg"})
        assert resp.status_code == 200
        assert resp.get_json()["result"]["rows"] == 1

    def test_non_huguan_403(self, client):
        h, _ = _create_user(client, "_push_user", role="user")
        assert client.post("/api/huguan/dashboard/push", headers=h,
                           json={"platform": "gg"}).status_code == 403


class TestGGTriggerPoints:
    def test_create_account_triggers_writeback(self, client, monkeypatch):
        """新建账户后应触发该行回写（且绝不写 H 列）。"""
        hg, uid = _create_user(client, "_trig_create", role="huguan")
        db = database.get_db()
        db.execute("INSERT OR REPLACE INTO config(key,value) VALUES(?,?)",
                   (f"huguan_dashboard_{uid}",
                    json.dumps({"gg": {"spreadsheet_id": "SS", "sheet_name": "S"}})))
        db.commit()
        db.close()

        captured = []
        _stub_sheets(monkeypatch, captured)
        resp = client.post("/api/accounts", headers=hg,
                           json={"account_id": "TRIG-1", "name": "TRIG-1"})
        assert resp.status_code in (200, 201)
        all_cells = [r["cells"] for c in captured for r in c["rows"]]
        assert any(c.get("C") == "'TRIG-1" for c in all_cells)
        assert all("H" not in c for c in all_cells)

    def test_soft_delete_does_not_trigger(self, client, monkeypatch):
        """软删只改 deleted_at，不动任何可映射列 → 不得触发回写。"""
        hg, uid = _create_user(client, "_trig_del", role="huguan")
        db = database.get_db()
        db.execute("INSERT OR REPLACE INTO config(key,value) VALUES(?,?)",
                   (f"huguan_dashboard_{uid}",
                    json.dumps({"gg": {"spreadsheet_id": "SS", "sheet_name": "S"}})))
        aid = _seed_account(db, "TRIG-DEL", uid)
        db.commit()
        db.close()

        captured = []
        _stub_sheets(monkeypatch, captured)
        resp = client.delete(f"/api/accounts/{aid}", headers=hg)
        assert resp.status_code == 200
        assert captured == []
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd py && python -m pytest tests/test_huguan_dashboard.py -q`
Expected: FAIL — `ImportError: cannot import name 'collect_rows_for_push'`

- [ ] **Step 3: 实现 `collect_rows_for_push` 与 `push_rows`**

追加到 `py/huguan_dashboard.py`：

```python
# 系统 → 表 的行查询语句。owner_name 取 display_name（回退 username）。
_GG_ROW_SQL = """
SELECT a.account_id, a.acquired_date, a.death_date, a.timezone,
       m.name AS mcc_name, pm.name AS parent_mcc_name,
       ag.name AS agent_name, COALESCE(NULLIF(u.display_name, ''), u.username, '') AS owner_name,
       s.name AS status_name
FROM accounts a
LEFT JOIN mcc m ON a.mcc_id = m.id
LEFT JOIN mcc pm ON m.parent_mcc_id = pm.id
LEFT JOIN agents ag ON a.agent_id = ag.id
LEFT JOIN users u ON a.owner_id = u.id
LEFT JOIN account_statuses s ON a.status_id = s.id
"""

_TT_ROW_SQL = """
SELECT a.advertiser_id AS account_id, a.acquired_date, a.death_date, a.country,
       a.timezone, a.consumption, a.remark,
       b.name AS bc_name, ag.name AS agent_name,
       COALESCE(NULLIF(u.display_name, ''), u.username, '') AS owner_name,
       s.name AS status_name
FROM tt_accounts a
LEFT JOIN tt_bcs b ON a.bc_id = b.id
LEFT JOIN agents ag ON a.agent_id = ag.id
LEFT JOIN users u ON a.owner_id = u.id
LEFT JOIN account_statuses s ON a.status_id = s.id
"""


def collect_rows_for_push(db, platform: str, account_ids=None) -> list:
    """系统 → 表：查出待写账户并转成 update_rows_by_account_id 的入参。

    产出里刻意不含归属变更通道列（规格 §7.2 规则 2）。
    account_ids=None 表示全部；给了具体 ID 时只取这些。
    """
    sql = _TT_ROW_SQL if platform == "tt" else _GG_ROW_SQL
    params = ()
    if account_ids is not None:
        if not account_ids:
            return []
        marks = ",".join("?" for _ in account_ids)
        sql += f" WHERE a.{ACCOUNT_KEY_FIELD[platform]} IN ({marks})"
        params = tuple(account_ids)

    out = []
    for r in db.execute(sql, params).fetchall():
        row = dict(r)
        out.append({"account_id": str(row.get("account_id") or "").strip(),
                    "cells": cells_for_row(row, platform)})
    return [o for o in out if o["account_id"]]


def push_rows(user_id: int, platform: str, account_ids=None) -> None:
    """把账户当前值写进该户管自己的看板表。

    未配置看板 → 静默返回（不是每个用户都是户管，这不是错误）。
    后台线程写，失败只记日志，不影响调用方的接口返回。
    """
    import logging
    log = logging.getLogger("gg-server")

    db = _open_db()
    try:
        conf = get_platform_config(db, user_id, platform)
        if not conf["spreadsheet_id"] or not conf["sheet_name"]:
            return
        rows = collect_rows_for_push(db, platform, account_ids)
    finally:
        db.close()

    if not rows:
        return

    def _do():
        import google_sheets_service as gs
        from main import _GOOGLE_SHEETS_CONFIG
        service = gs.build_service(_GOOGLE_SHEETS_CONFIG["credentials_path"])
        gs.update_rows_by_account_id(service, conf["spreadsheet_id"],
                                     conf["sheet_name"], rows)

    from main import _sync_sheets_background
    _sync_sheets_background(_do, lambda s, e: log.warning("户管看板回写失败: %s", e) if e else None)


def _open_db():
    """惰性取库连接（避免本模块在 import 期依赖 database）。"""
    import database
    return database.get_db()
```

- [ ] **Step 4: 实现 `/push` 端点**

追加到 `py/routes/huguan_dashboard_routes.py`：

```python
@huguan_dashboard_bp.route("/api/huguan/dashboard/push", methods=["POST"])
@jwt_required()
@huguan_required
def dashboard_push():
    """系统 → 表：全量刷新。同步执行，返回实际写入行数。"""
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return err("请求体必须是 JSON 对象", 400)
    platform = str(data.get("platform") or "").strip()
    if platform not in hd.PLATFORMS:
        return err("platform 必须是 gg 或 tt", 400)

    uid = get_uid()
    db = database.get_db()
    try:
        conf = hd.get_platform_config(db, uid, platform)
        if not conf["spreadsheet_id"] or not conf["sheet_name"]:
            return err("请先在设置页配置户管看板的表格 ID 与工作表名", 400)
        rows = hd.collect_rows_for_push(db, platform)
    finally:
        db.close()

    import google_sheets_service as gs
    from main import _GOOGLE_SHEETS_CONFIG
    service = gs.build_service(_GOOGLE_SHEETS_CONFIG["credentials_path"])
    res = gs.update_rows_by_account_id(service, conf["spreadsheet_id"],
                                       conf["sheet_name"], rows)
    return ok({"result": {"rows": len(rows), "updated": res["updated"],
                          "not_found": res["not_found"]}})
```

- [ ] **Step 5: 接入 GG 6 个触发点**

在 `py/main.py` 的以下 6 处，各自在**提交事务之后**插入同一行调用（示例以新建账户 `:3993` 之外的位置为准，每处都用该处的实际账户 ID 变量）：

```python
# 户管看板单行回写（规格 §6.2）。只写可写列，绝不碰「重新分配」列。
_huguan_push(user_id, "gg", [<该处受影响账户的 account_id 变量>])
```

在 `py/main.py` 中新增辅助函数（放在 `_sync_sheets_background` 定义 `:7404` 之前）：

```python
def _huguan_push(user_id, platform, account_ids):
    """触发户管看板的单行回写。用户没配看板时静默跳过。"""
    try:
        import huguan_dashboard as hd
        hd.push_rows(user_id, platform, account_ids)
    except Exception as e:
        log.warning("户管看板回写触发失败: %s", e)
```

6 处插入点与各自的账户 ID 变量：

| 行号（约） | 端点 | 插入的调用 |
|---|---|---|
| `:4350` | `POST /api/accounts`（新建） | `_huguan_push(user_id, "gg", [account_id])` |
| `:4180` | `POST /api/accounts/batch`（批量新建） | `_huguan_push(user_id, "gg", created_ids)` |
| `:4300` | `PUT /api/accounts/<aid>` | `_huguan_push(user_id, "gg", [existing["account_id"]])` |
| `:4417` | `PUT /api/accounts/<aid>/reassign` | `_huguan_push(user_id, "gg", [existing["account_id"]])` 之后追加 `_huguan_owner_channel(user_id, "gg", existing["account_id"], target_owner)` |
| `:4725` | `POST /api/accounts/batch-update` | `_huguan_push(user_id, "gg", affected_account_ids)` |
| `:5013` | `POST /api/accounts/sync-from-sheet` | `_huguan_push(user_id, "gg", sheet_ids)` |

**reassign 是唯一需要额外写归属变更通道列的地方**（规格 §7.2 规则 3①）。在 `py/main.py` 新增：

```python
def _huguan_owner_channel(user_id, platform, account_id, new_owner_id):
    """户管在系统里改了归属 → 把新归属写进表里的「重新分配」列（规格规则 3①）。"""
    try:
        import database
        import huguan_dashboard as hd
        db = database.get_db()
        try:
            conf = hd.get_platform_config(db, user_id, platform)
            if not conf["spreadsheet_id"] or not conf["sheet_name"]:
                return
            r = db.execute("SELECT COALESCE(NULLIF(display_name, ''), username, '') AS n "
                           "FROM users WHERE id=?", (new_owner_id,)).fetchone()
            name = (r["n"] if r else "").strip()
        finally:
            db.close()
        if not name:
            return
        rows = hd.owner_channel_cells([{"account_id": account_id}], platform, name)
        import google_sheets_service as gs
        service = gs.build_service(_GOOGLE_SHEETS_CONFIG["credentials_path"])

        def _do():
            gs.update_rows_by_account_id(service, conf["spreadsheet_id"],
                                         conf["sheet_name"], rows)
        _sync_sheets_background(_do, lambda s, e: log.warning("重新分配列回写失败: %s", e) if e else None)
    except Exception as e:
        log.warning("重新分配列回写触发失败: %s", e)
```

**注意**：`accounts_reassign` 里 `target_owner` 在 `:4374-4377` 已经算好；`existing`（`:4381`）也已有 `account_id`。直接在 `db.commit()`（`:4417`）之后调用即可。**不要**改动 `accounts_reassign` 的既有判断与返回文案。

- [ ] **Step 6: 跑测试确认通过**

Run: `cd py && python -m pytest tests/test_huguan_dashboard.py -q`
Expected: PASS（聚焦 ≥ 90 passed）

- [ ] **Step 7: 跑全量测试确认无回归**

Run: `cd py && python -m pytest tests/ -q`
Expected: PASS（全量 ≥ 514 passed，不得低于上一任务实测值）

- [ ] **Step 8: 提交**

```bash
git add py/huguan_dashboard.py py/routes/huguan_dashboard_routes.py py/main.py py/tests/test_huguan_dashboard.py
git commit -m "feat: 户管看板全量刷新与 GG 账户变更单行回写"
```

---

## Task 9: TT 触发点接入 + TT reassign 支持跨用户归属

**Files:**
- Modify: `py/routes/tt_accounts_routes.py`（6 个触发点；`reassign_account`）
- Test: `py/tests/test_huguan_dashboard.py`

**Interfaces:**
- Consumes: `huguan_dashboard.push_rows`、`huguan_dashboard.get_platform_config`、`huguan_dashboard.owner_channel_cells`
- Produces: TT 侧与 GG 侧对称的回写行为；`PUT /api/tt/accounts/<aid>/reassign` 在 `CROSS_USER_ROLES` + 合法 `owner_id` 时可转给他人

- [ ] **Step 1: 写失败的测试**

追加到 `py/tests/test_huguan_dashboard.py`：

```python
# ---------- Task 9: TT 触发点 + TT reassign 跨用户 ----------

def _seed_tt(db, advertiser_id, owner_id, **over):
    cols = {"advertiser_id": advertiser_id, "name": advertiser_id,
            "owner_id": owner_id, "country": "", "timezone": "",
            "consumption": "", "remark": "", "death_date": "", "deleted_at": None}
    cols.update(over)
    keys = ", ".join(cols)
    marks = ", ".join("?" for _ in cols)
    db.execute(f"INSERT INTO tt_accounts({keys}) VALUES({marks})", tuple(cols.values()))
    db.commit()
    return db.execute("SELECT id FROM tt_accounts WHERE advertiser_id=?",
                      (advertiser_id,)).fetchone()["id"]


class TestTtReassignCrossUser:
    def test_huguan_can_transfer_to_another_user(self, client):
        """TT 原本只能认领给自己；户管要能转给别人（规格 §7.5）。"""
        hg, hid = _create_user(client, "_tt_rg_hg", role="huguan", platform="tt")
        db = database.get_db()
        target = _seed(db, "_tt_rg_target", "王五")
        aid = _seed_tt(db, "TTR-1", hid)
        db.close()
        resp = client.put(f"/api/tt/accounts/{aid}/reassign", headers=hg,
                          json={"owner_id": target})
        assert resp.status_code == 200
        db = database.get_db()
        assert db.execute("SELECT owner_id FROM tt_accounts WHERE id=?", (aid,)).fetchone()["owner_id"] == target
        db.close()

    def test_plain_user_still_only_claims_for_self(self, client):
        """回归：非跨用户角色即使传 owner_id 也只能认领给自己（默认路径逐字节不变）。"""
        u, uid = _create_user(client, "_tt_rg_user", role="user", platform="tt")
        db = database.get_db()
        other = _seed(db, "_tt_rg_other", "赵六")
        aid = _seed_tt(db, "TTR-2", other)
        db.close()
        resp = client.put(f"/api/tt/accounts/{aid}/reassign", headers=u,
                          json={"owner_id": uid})
        assert resp.status_code == 200
        db = database.get_db()
        assert db.execute("SELECT owner_id FROM tt_accounts WHERE id=?", (aid,)).fetchone()["owner_id"] == uid
        db.close()

    def test_developer_can_transfer(self, client):
        dev, _ = _create_user(client, "_tt_rg_dev", role="developer", platform="tt")
        db = database.get_db()
        target = _seed(db, "_tt_rg_t2", "钱七")
        aid = _seed_tt(db, "TTR-3", target)
        other = _seed(db, "_tt_rg_t3", "孙八")
        db.close()
        assert client.put(f"/api/tt/accounts/{aid}/reassign", headers=dev,
                          json={"owner_id": other}).status_code == 200

    def test_zero_owner_id_falls_back_to_self(self, client):
        """owner_id 给 0 不得被当成合法目标。

        `"0".isdigit()` 为真，所以必须先 `or ""` 吃掉 —— 否则归属会被设成
        不存在的用户 0。这一步与 GG 既有写法（main.py:4378-4381）逐字对齐。
        """
        hg, hid = _create_user(client, "_tt_rg_zero", role="huguan", platform="tt")
        db = database.get_db()
        aid = _seed_tt(db, "TTR-4", _seed(db, "_tt_rg_zother", "周九"))
        db.close()
        resp = client.put(f"/api/tt/accounts/{aid}/reassign", headers=hg,
                          json={"owner_id": 0})
        assert resp.status_code == 200
        db = database.get_db()
        assert db.execute("SELECT owner_id FROM tt_accounts WHERE id=?",
                          (aid,)).fetchone()["owner_id"] == hid
        db.close()


class TestTTTriggerPoints:
    def test_tt_create_triggers_writeback(self, client, monkeypatch):
        hg, uid = _create_user(client, "_tt_trig_c", role="huguan", platform="tt")
        db = database.get_db()
        db.execute("INSERT OR REPLACE INTO config(key,value) VALUES(?,?)",
                   (f"huguan_dashboard_{uid}",
                    json.dumps({"tt": {"spreadsheet_id": "SS", "sheet_name": "S"}})))
        db.commit()
        db.close()

        captured = []
        _stub_sheets(monkeypatch, captured)
        resp = client.post("/api/tt/accounts", headers=hg,
                           json={"advertiser_id": "TTTRIG-1", "name": "TTTRIG-1"})
        assert resp.status_code in (200, 201)
        all_cells = [r["cells"] for c in captured for r in c["rows"]]
        assert any(c.get("C") == "'TTTRIG-1" for c in all_cells)
        assert all("L" not in c for c in all_cells)

    def test_tt_soft_delete_does_not_trigger(self, client, monkeypatch):
        hg, uid = _create_user(client, "_tt_trig_d", role="huguan", platform="tt")
        db = database.get_db()
        db.execute("INSERT OR REPLACE INTO config(key,value) VALUES(?,?)",
                   (f"huguan_dashboard_{uid}",
                    json.dumps({"tt": {"spreadsheet_id": "SS", "sheet_name": "S"}})))
        aid = _seed_tt(db, "TTTRIG-D", uid)
        db.close()

        captured = []
        _stub_sheets(monkeypatch, captured)
        assert client.delete(f"/api/tt/accounts/{aid}", headers=hg).status_code == 200
        assert captured == []
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd py && python -m pytest tests/test_huguan_dashboard.py -q -k "TtReassign or TTTrigger"`
Expected: FAIL — `test_huguan_can_transfer_to_another_user` 断言 owner_id 仍是户管自己

- [ ] **Step 3: 扩展 TT reassign**

修改 `py/routes/tt_accounts_routes.py` 的 `reassign_account`（按**函数名**定位，行号会漂）。**只加一小段，其余逐字节不动**：

在 `data = parse_body()` 之后（该函数前几行依次是 `db = get_db()` / `uid = get_uid()` / `data = parse_body()`）插入目标归属的计算。
**注意必须排在 `data = parse_body()` 之后**——下面这段读 `data.get("owner_id")`，插在它前面会直接 `NameError`：

```python
    # 目标归属：跨用户角色（developer/admin/户管）可用 owner_id 转给指定用户，
    # 其余角色恒为调用者自己（默认路径与改动前逐字节一致）。
    # `or ""` 不能省：owner_id 给 0 时 `"0".isdigit()` 为真，会把手属设成不存在的用户 0；
    # 这一步与 GG 的既有写法（main.py:4378-4381）逐字对齐。
    target_owner = uid
    if _get_role(db, uid) in CROSS_USER_ROLES:
        raw_owner = (data.get("owner_id") or "")
        if str(raw_owner).strip().isdigit():
            target_owner = int(str(raw_owner).strip())
```

然后把该函数中两处 `uid` 的归属用途替换为 `target_owner`：

- `if int(existing["owner_id"] or 0) == uid:` → `if int(existing["owner_id"] or 0) == target_owner:`
- `db.execute("UPDATE tt_accounts SET owner_id=?, ...", (uid, aid))` → `(target_owner, aid)`

并把返回文案改为区分两种情况（对照 `main.py:4419-4424`）：

```python
    if target_owner == uid:
        return ok({"message": f"账户「{existing['name'] or existing['advertiser_id']}」已转移至当前用户"})
    t = db.execute("SELECT display_name, username FROM users WHERE id=?", (target_owner,)).fetchone()
    label = (t["display_name"] or t["username"]) if t else str(target_owner)
    return ok({"message": f"账户「{existing['name'] or existing['advertiser_id']}」已转移至 {label}"})
```

- [ ] **Step 4: 接入 TT 6 个触发点**

在 `py/routes/tt_accounts_routes.py` 顶部 import 之后新增辅助函数：

```python
def _huguan_push(uid, account_ids):
    """触发户管看板的 TT 单行回写。未配置看板时静默跳过。"""
    try:
        import huguan_dashboard as hd
        hd.push_rows(uid, "tt", account_ids)
    except Exception as e:
        import logging
        logging.getLogger("gg-server").warning("户管看板 TT 回写触发失败: %s", e)


def _huguan_owner_channel(uid, account_id, new_owner_id):
    """TT 侧户管改归属 → 写「换绑情况」列（规格 §7.2 规则 3①）。"""
    try:
        import huguan_dashboard as hd
        db = database.get_db()
        try:
            conf = hd.get_platform_config(db, uid, "tt")
            if not conf["spreadsheet_id"] or not conf["sheet_name"]:
                return
            r = db.execute("SELECT COALESCE(NULLIF(display_name, ''), username, '') AS n "
                           "FROM users WHERE id=?", (new_owner_id,)).fetchone()
            name = (r["n"] if r else "").strip()
        finally:
            db.close()
        if not name:
            return

        rows = hd.owner_channel_cells([{"account_id": account_id}], "tt", name)

        def _do():
            from main import _GOOGLE_SHEETS_CONFIG, _sync_sheets_background
            import google_sheets_service as gs
            svc = gs.build_service(_GOOGLE_SHEETS_CONFIG["credentials_path"])
            gs.update_rows_by_account_id(svc, conf["spreadsheet_id"], conf["sheet_name"], rows)

        from main import _sync_sheets_background
        _sync_sheets_background(_do, lambda s, e: None)
    except Exception as e:
        import logging
        logging.getLogger("gg-server").warning("TT 换绑情况列回写触发失败: %s", e)
```

6 处插入点：

| 行号（约） | 端点 | 插入的调用 |
|---|---|---|
| `:150` | `POST /api/tt/accounts` | `_huguan_push(uid, [advertiser_id])` |
| `:410` | `POST /api/tt/accounts/batch` | `_huguan_push(uid, created_ids)` |
| `:350` | `PUT /api/tt/accounts/<aid>` | `_huguan_push(uid, [existing["advertiser_id"]])` |
| `:490` | `PUT /api/tt/accounts/<aid>/reassign` | `_huguan_push(uid, [existing["advertiser_id"]])` + `_huguan_owner_channel(uid, existing["advertiser_id"], target_owner)` |
| `:455` | `POST /api/tt/accounts/batch-update` | `_huguan_push(uid, affected_advertiser_ids)` |
| `:1050` | `POST /api/tt/accounts/sync-from-sheet` | `_huguan_push(uid, [对应 advertiser_id])` |

**不接入**：`:499` 软删、`:536` 恢复、`:553` 永久删 —— 只改 `deleted_at`，不动任何可映射列。

- [ ] **Step 5: 跑测试确认通过**

Run: `cd py && python -m pytest tests/test_huguan_dashboard.py -q`
Expected: PASS（聚焦 ≥ 96 passed）

- [ ] **Step 6: 跑全量测试确认无回归**

Run: `cd py && python -m pytest tests/ -q`
Expected: PASS（全量 ≥ 520 passed，不得低于上一任务实测值）

- [ ] **Step 7: 提交**

```bash
git add py/routes/tt_accounts_routes.py py/tests/test_huguan_dashboard.py
git commit -m "feat: 户管看板 TT 回写接入与 TT 跨用户归属转移"
```

---

## Task 10: 前端 —— 设置页看板配置卡片

> **前置（CLAUDE.md 硬性要求）**：动手前必须先调用 `/frontend-design` 技能完成视觉设计。下面的代码是**功能基线**，视觉细节以 `/frontend-design` 的产出为准。

**Files:**
- Create: `frontend/src/api/huguan.js`
- Modify: `frontend/src/views/SettingsPanel.vue`（GG）
- Modify: `frontend/src/views/tt/TtSettingsPanel.vue`（TT）
- Test: `cd frontend && npm run build`（无单测框架，构建即门禁）

**Interfaces:**
- Consumes: `GET/POST /api/huguan/dashboard`、`POST /api/huguan/dashboard/push`、`POST /api/huguan/dashboard/sync`、`GET /api/google-sheets/sheets`（既有，户管已可达）
- Produces: 户管可见的配置卡片

- [ ] **Step 1: 调用 /frontend-design**

Run: `/frontend-design`

产出必须覆盖：卡片的视觉层级（与既有的「充值表配置」/「Google 表格配置」卡片并列时的主次关系）、六个控件的排布、差异确认对话框的信息层级（五类差异如何分组呈现，`owner_changes` 要最醒目）。把产出落进下面的实现。

- [ ] **Step 2: 新建 API 封装**

创建 `frontend/src/api/huguan.js`：

```js
import api from './client'

export const huguanApi = {
  getConfig: () => api.get('/huguan/dashboard'),
  saveConfig: (body) => api.post('/huguan/dashboard', body),
  push: (platform) => api.post('/huguan/dashboard/push', { platform }),
  sync: (body) => api.post('/huguan/dashboard/sync', body),
}
```

- [ ] **Step 3: GG 设置页加卡片**

在 `frontend/src/views/SettingsPanel.vue` 的「📊 充值表配置」卡片（`:65` 那个 `v-if="authStore.isAdmin || authStore.isDeveloper"` 的 `<el-card>`）**之后**追加新卡片。**不要改动既有卡片**：

```vue
<!-- 户管看板配置（子项目 B）。只有户管可见，管理员看到的是上面那张充值表卡片。 -->
<el-card v-if="authStore.isHuguan" shadow="never"
         style="margin-top:20px;border-left:3px solid #7c3aed;">
  <template #header>
    <div style="display:flex;align-items:center;justify-content:space-between;">
      <span>📊 户管看板配置</span>
      <span style="color:#7c3aed;font-size:12px;">仅户管</span>
    </div>
  </template>
  <el-form label-width="120px">
    <el-form-item label="表格 ID / 链接">
      <el-input v-model="hdForm.spreadsheet_id" placeholder="粘贴 Google 表格 URL 或 ID" />
    </el-form-item>
    <el-form-item label="工作表名">
      <div style="display:flex;gap:8px;width:100%;">
        <el-select v-model="hdForm.sheet_name" filterable allow-create
                   placeholder="点右侧按钮读取后选择" style="flex:1;">
          <el-option v-for="s in hdSheets" :key="s" :label="s" :value="s" />
        </el-select>
        <el-button :loading="hdReading" @click="readHdSheets">📋 读取工作表</el-button>
      </div>
    </el-form-item>
    <el-form-item>
      <el-button type="primary" :loading="hdSaving" @click="saveHdConfig">💾 保存配置</el-button>
      <el-button :loading="hdPushing" @click="pushHd">🔄 同步到看板</el-button>
      <el-button :loading="hdSyncing" @click="syncHd">⬇️ 从看板同步</el-button>
    </el-form-item>
  </el-form>
  <el-alert v-if="hdHint" :title="hdHint" type="info" :closable="false" show-icon />
</el-card>
```

在 `<script setup>` 中追加（`hdForm` 等状态与三个方法）。差异确认用 `ElMessageBox`，`owner_changes` 单独醒目展示：

```js
import { huguanApi } from '@/api/huguan'
import { ElMessage, ElMessageBox } from 'element-plus'
import api from '@/api/client'

const hdForm = ref({ spreadsheet_id: '', sheet_name: '' })
const hdSheets = ref([])
const hdReading = ref(false)
const hdSaving = ref(false)
const hdPushing = ref(false)
const hdSyncing = ref(false)
const hdHint = ref('')

async function loadHdConfig() {
  if (!authStore.isHuguan) return
  const res = await huguanApi.getConfig()
  const gg = (res.config && res.config.gg) || {}
  hdForm.value = {
    spreadsheet_id: gg.spreadsheet_id || '',
    sheet_name: gg.sheet_name || '',
  }
}

async function readHdSheets() {
  if (!hdForm.value.spreadsheet_id) { ElMessage.warning('请先填表格 ID 或链接'); return }
  hdReading.value = true
  try {
    const res = await api.get('/google-sheets/sheets', {
      params: { spreadsheet_id: hdForm.value.spreadsheet_id },
    })
    hdSheets.value = res.sheets || []
    if (!hdSheets.value.length) ElMessage.warning('该表格没有可读的工作表')
  } catch (e) {
    ElMessage.error(e?.response?.data?.error || '读取工作表失败')
  } finally { hdReading.value = false }
}

async function saveHdConfig() {
  hdSaving.value = true
  try {
    await huguanApi.saveConfig({ platform: 'gg', ...hdForm.value })
    ElMessage.success('配置已保存')
  } catch (e) {
    ElMessage.error(e?.response?.data?.error || '保存失败')
  } finally { hdSaving.value = false }
}

async function pushHd() {
  hdPushing.value = true
  try {
    const res = await huguanApi.push('gg')
    const r = res.result
    ElMessage.success(`已写入 ${r.updated} 行${r.not_found.length ? `，表里没有 ${r.not_found.length} 个账户` : ''}`)
  } catch (e) {
    ElMessage.error(e?.response?.data?.error || '同步到看板失败')
  } finally { hdPushing.value = false }
}

async function syncHd() {
  hdSyncing.value = true
  try {
    const res = await huguanApi.sync({ platform: 'gg', dry_run: true })
    const d = res.diff
    const s = d.summary
    const lines = [
      `表里共 ${s.total_in_sheet} 行`,
      `新增账户 ${s.new_accounts} 个`,
      `字段更新 ${s.updates} 处`,
      `归属变更 ${s.owner_changes} 个`,
      `跳过 ${s.skipped} 个`,
      `警告 ${s.warnings} 条`,
    ]
    if (d.owner_changes.length) {
      lines.push('', '【归属变更】')
      d.owner_changes.forEach(c => lines.push(`  第 ${c.row} 行 ${c.account_id}：${c.from || '（空）'} → ${c.to}`))
    }
    if (!s.new_accounts && !s.updates && !s.owner_changes) {
      hdHint.value = '看板与系统已一致，无需同步'
      return
    }
    await ElMessageBox.confirm(lines.join('\n'), '确认从看板同步', {
      confirmButtonText: '确认同步',
      cancelButtonText: '取消',
      customStyle: { whiteSpace: 'pre-line' },
    })
    const applied = await huguanApi.sync({
      platform: 'gg',
      dry_run: false,
      confirmed: {
        create: d.to_create.map(x => x.row),
        update: d.to_update.map(x => x.row),
        owner: d.owner_changes.map(x => x.row),
      },
    })
    const r = applied.result
    ElMessage.success(`已应用：新增 ${r.created}，更新 ${r.updated}，归属变更 ${r.owner_changed}`)
    hdHint.value = ''
  } catch (e) {
    if (e !== 'cancel') ElMessage.error(e?.response?.data?.error || '从看板同步失败')
  } finally { hdSyncing.value = false }
}

onMounted(loadHdConfig)
```

若该文件的 `<script setup>` 里没有 `ref` / `onMounted` 的 import，补上。

- [ ] **Step 4: TT 设置页加同样的卡片**

在 `frontend/src/views/tt/TtSettingsPanel.vue` 的 sheet 配置卡片（`:124` 的 `v-if="!authStore.isHuguan"`）之后追加同样的卡片，改动三点：
- `platform: 'gg'` 全部改为 `'tt'`
- `res.config.gg` 改为 `res.config.tt`
- 卡片抬头保持「📊 户管看板配置」

- [ ] **Step 5: 构建验证**

Run: `cd frontend && npm run build`
Expected: 构建成功，无编译错误

- [ ] **Step 6: 提交**

```bash
git add frontend/src/api/huguan.js frontend/src/views/SettingsPanel.vue frontend/src/views/tt/TtSettingsPanel.vue
git commit -m "feat: 户管看板配置卡片（GG/TT 设置页）"
```

---

## Task 11: 前端 —— 账户面板「户归属」字段

> **前置（CLAUDE.md 硬性要求）**：动手前必须先调用 `/frontend-design` 技能。

**Files:**
- Modify: `frontend/src/views/AdsAccountPanel.vue`（GG）
- Modify: `frontend/src/views/tt/TtAccountPanel.vue`（TT）
- Test: `cd frontend && npm run build`

**Interfaces:**
- Consumes: `PUT /api/accounts/<aid>/reassign`（GG，既有）、`PUT /api/tt/accounts/<aid>/reassign`（TT，Task 9 扩展后）、`GET /platform/users`（下拉数据源）
- Produces: 仅户管可见可编辑的「户归属」列

- [ ] **Step 1: 调用 /frontend-design**

Run: `/frontend-design`

产出必须覆盖：「户归属」列在表格里的呈现（是常显下拉还是「点击编辑」）、与既有「归属人」筛选下拉的区分（一个是筛选、一个是编辑，别让户管混淆）、编辑后的反馈。

- [ ] **Step 2: GG 面板加列**

在 `frontend/src/views/AdsAccountPanel.vue` 的账户表格里加一列，并用 `v-if="authStore.isHuguan"` 控制**可见性**：

```vue
<!-- 户归属：只有户管可见可编辑（规格 §9.2）。管理员的入口不在这里。 -->
<el-table-column v-if="authStore.isHuguan" label="户归属" width="150" align="center">
  <template #default="{ row }">
    <el-select :model-value="row.owner_id" size="small" filterable placeholder="未分配"
               @change="(v) => changeOwner(row, v)">
      <el-option v-for="u in ownerOptions" :key="u.id"
                 :label="u.display_name || u.username" :value="u.id" />
    </el-select>
  </template>
</el-table-column>
```

在 `<script setup>` 中追加：

```js
const ownerOptions = ref([])

async function loadOwnerOptions() {
  if (!authStore.isHuguan) return
  try {
    const res = await api.get('/platform/users')
    ownerOptions.value = res.users || []
  } catch { /* 下拉加载失败不阻塞主流程 */ }
}

async function changeOwner(row, newOwnerId) {
  const prev = row.owner_id
  row.owner_id = newOwnerId                       // 乐观更新，失败回滚
  try {
    await accountsApi.reassign(row.id, { owner_id: newOwnerId })
    ElMessage.success('归属已变更，系统已把新归属写进看板的「重新分配」列')
  } catch (e) {
    row.owner_id = prev
    ElMessage.error(e?.response?.data?.error || '归属变更失败')
  }
}

onMounted(loadOwnerOptions)
```

- [ ] **Step 3: TT 面板加同样的列**

在 `frontend/src/views/tt/TtAccountPanel.vue` 里加同样的列，改动两点：
- `accountsApi.reassign` 改为 `ttAccountsApi.reassign`（`frontend/src/api/tt.js:71`）
- 成功文案里的「重新分配」改为「换绑情况」

- [ ] **Step 4: 构建验证**

Run: `cd frontend && npm run build`
Expected: 构建成功

- [ ] **Step 5: 提交**

```bash
git add frontend/src/views/AdsAccountPanel.vue frontend/src/views/tt/TtAccountPanel.vue
git commit -m "feat: 账户面板新增户管专属「户归属」列"
```

---

## Task 12: 全量回归 + 代码审查

**Files:**
- 无新增；只做验证与修复

- [ ] **Step 1: 后端全量测试**

Run: `cd py && python -m pytest tests/ -q`
Expected: PASS，全量总数 ≥ 509（基线 424 + 本计划新增 ≈ 85）

- [ ] **Step 2: 前端构建**

Run: `cd frontend && npm run build`
Expected: 成功

- [ ] **Step 3: 逐条核对规格的「Global Constraints」**

打开 `docs/superpowers/specs/2026-09-23-huguan-sheet-design.md`，逐条对照：
- §7.2 规则 1 / 2 / 3 / 4 各有一条测试覆盖
- GG 可写列确为 `A:D` + `F:K`；且 `cells_for_row` 产出的实际回写区间是 `A:D` + `F:G` + `I:K`，H 列不在任何区间覆盖范围内（`E` / `H` / `L` / `M` / `N` 未被写入）
- TT 可写列确为 `A:J` + `L:M`（`K` 未被写入）
- 软删 / 恢复 / 永久删在两张表下都不触发回写
- 非户管访问 `/api/huguan/dashboard*` 全部 403

- [ ] **Step 4: 调用 /code-review**

Run: `/code-review`

按 CLAUDE.md 要求，修复审查发现的问题后再交付。**注意**：审查发现的问题若与计划文本冲突（例如审查认为某个计划明确要求的写法是缺陷），先把「发现」与「计划原文」一起拿给用户裁定，不要自行改动。

- [ ] **Step 5: 修复后重跑门禁**

Run: `cd py && python -m pytest tests/ -q && cd ../frontend && npm run build`
Expected: 双双通过

- [ ] **Step 6: 提交审查修复**

```bash
git add <本次修复涉及的具体文件>
git commit -m "fix: 代码审查收口"
```

- [ ] **Step 7: 更新进度账本**

往 `.superpowers/sdd/progress.md` 追加一行，记录子项目 B 完成状态与提交范围（该文件是 gitignore 的恢复地图）。

---

## 自查记录（Self-Review）

**1. 规格覆盖检查**

| 规格章节 | 覆盖任务 |
|---|---|
| §4.1 配置存储（key / JSON / 平台隔离 / 不复用我的看板） | Task 5 |
| §4.2 不新增数据库列 | 全程（复用 `owner_id`） |
| §5 列映射（GG 14 / TT 13、可写区间、可读范围、J 派生列） | Task 2、Task 3 |
| §6.1 `update_rows_by_account_id` | Task 4 |
| §6.2 触发点（12 处，排除软删/恢复/永久删） | Task 8、Task 9 |
| §6.3 触发后行为（未配置静默跳过、后台线程、不写通道列） | Task 8、Task 9 |
| §6.4 手动全量刷新 | Task 8 |
| §7.1 有效归属判定 | Task 3 |
| §7.2 四条硬规则 | Task 2（规则 2）、Task 6（规则 1）、Task 7（规则 3②/4）、Task 8（规则 3①） |
| §7.3 归属名解析 + 歧义 | Task 6 |
| §7.4 空归属 | Task 6 |
| §7.5 TT reassign 缺口 | Task 9 |
| §8.1 sync 接口 | Task 7 |
| §8.2 归属门禁替换 | Task 7（表地址只从配置取） |
| §8.3 读回流程五类差异 | Task 6、Task 7 |
| §8.4 名称唯一命中才落库 | Task 6 |
| §9.1 设置页卡片 | Task 10 |
| §9.2 户归属字段 | Task 11 |
| §10 回归保障 | 每个任务自带测试 + Task 12 |

无遗漏。

**2. 占位符扫描**：无 TBD / TODO / 「类似 Task N」。每个改代码的步骤都给了完整代码。

**3. 类型一致性**：`cells_for_row` / `parse_row` / `effective_owner_name` / `is_dead` / `build_diff` / `apply_diff` / `owner_channel_cells` / `collect_rows_for_push` / `push_rows` / `load_config` / `save_config` / `get_platform_config` 的签名在定义任务与消费任务中逐字一致；`update_rows_by_account_id` 的参数与返回结构在 Task 4 定义、Task 7/8 消费，一致。

**4. 计划本身的已知风险（需在执行时留意）**

- Task 8 / Task 9 的 6 处触发点行号是**近似行号**，实现时必须按端点名定位，不能只认行号（本仓库有并行会话在改文件，行号会漂）。
- 已核对属实的既有事实（勿再怀疑）：`routes/decorators.py:5` 已导入 `HUGUAN_ROLE`（新增装饰器无需改 import）；`GoogleSheetsServiceError` 定义在 `google_sheets_service.py:15`；`mcc.parent_mcc_id` 存在；`main.py:7` 有模块级 `log`。
- **TT 行字典必须用 `account_id` 作键（Task 2 审查者指出的跨任务交接项）**：`cells_for_row` 一律读 `row["account_id"]`，而 TT 的数据库列名是 `advertiser_id`。Task 8 的 `_TT_ROW_SQL` 已经用 `a.advertiser_id AS account_id` 别名兜住了，**任何新增的 TT 行查询都必须照做** —— 否则 C 列（定位键）会被写成空串，而它正在写入区间 `A:J` 之内，会静默清掉表里的账户ID。
- **`_dead_flag` 假定 `death_date` 是 str**：`cells_for_row` 对它直接 `.strip()`（未走 `str(...)` 兜底）。SQLite 里该列是 TEXT 且 Task 8 的查询原样取出，故当前无风险；但若将来有调用方传入 `datetime.date`，会抛 `AttributeError`。Task 2 审查者标记为 Minor，未修。
- **命名遮蔽警告（Task 1 实现者与审查者共同确认）**：既有的 `update_cell_by_account_id` 内部有两个同名符号会遮蔽本计划新增的模块级函数 —— **`:581` 的形参 `col_index`**（遮蔽整个函数体）与 **`:602` 附近的局部变量 `col_letter`**。既有逻辑完全不受影响（该函数把它们当整数用，从不调用新函数），但**在那个函数体内调用新 `col_letter()` / `col_index()` 会静默拿到形参/局部值而非函数**。Task 4 新增的 `update_rows_by_account_id` 是独立函数、不在此列，无需处理；仅当后续需要在旧函数体内复用新工具时才要先改名。
- **Task 7 的 `confirmed` 结构校验已在计划内补齐（原为此处记录的风险，现已在端点层闭合）**：`confirmed` 载荷直接来自客户端，原写法 `data.get("confirmed") or {}` 只兜得住 `None`/`""`/`0`。已实测两条会炸成 500 的路径：① 外层是真值非 dict（`[1,2]` / `"abc"`）→ `apply_diff` 里 `conf.get` 抛 `AttributeError`；② 值不是数组（`{"create": 2}`）→ `item["row"] not in 2` 抛 `TypeError`。端点现已两层都判、非 dict 或非 list 一律 400，并配 `test_malformed_confirmed_is_400`。**`apply_diff` 内层 item 无需校验** —— 那些 item 由本模块 `build_diff` 产出、不经客户端，唯一的客户端输入就是行号。这条已并入 Global Constraints 的「容器型字段」口径。
- **警告数基线已从 618 漂到 630，不是新缺陷**：`conftest.py:28` 把 `JWT_SECRET_KEY` 固定成 15 字节的 `"test-secret-key"`，PyJWT 每次 encode/decode 都发 `InsecureKeyLengthWarning`。任何**首次**在测试文件里做 JWT 登录的任务都会抬高全量警告数（Task 5 +12）。已实测对照：未被触碰的 `test_huguan_role.py` 同样产出 289 条同类警告。**判据不是「警告数不变」而是「新增警告是否源自仓库代码」** —— 全部出自 site-packages 的 `jwt/api_jwt.py`，故不修。真正归属方是 conftest 共享 fixture（改成 ≥32 字节可一次清掉全仓），会牵动全套测试，不在本计划范围。
