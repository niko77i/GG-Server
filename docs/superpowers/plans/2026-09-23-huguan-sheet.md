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
- **状态解析必须带平台（Task 6 起）**：`resolve_status_id(db, name, owner_id, platform, *, create_missing=True)`。`account_statuses.platform` 默认 `'gg'`、唯一约束是 `(name, platform)`、下拉按平台过滤（`main.py:6059`）—— 漏平台会让 TT 的状态落进 gg 命名空间。
- **状态查重键是 `(name, platform)`，不含 `owner_id`**（规格 §8.4）—— 真实唯一约束就是这两个列（`database.py:1225` 的迁移重建，PRAGMA 实测），带上 `owner_id` 会让两个运营写同名状态时重复 `INSERT` 撞约束，`IntegrityError` 穿到 `build_diff` 把整份报告带崩。既有正确对照：`main.py:6102`、`routes/tt_accounts_routes.py:65`。
- **`dry_run=true` 全程只读**（规格 §8.3 步骤 7 / §10.1 第 6 项）：`build_diff` 一律 `create_missing=False`；系统里没有的状态名以 `pending_status` 原样进报告（不是 id、不是 warning），`INSERT` 只发生在 `apply_diff`。
- **请求体读字段的统一口径（所有 `/api/huguan/*` 端点）**：`data = request.get_json(silent=True)` 后先判 `isinstance(data, dict)`，否则 400；字段一律 `str(... or "")` 兜底再 `.strip()`。**禁止**写 `(data.get(x) or "").strip()` —— 客户端给个数字或 `null` 就会 `AttributeError` 炸成 500（Task 5 审查实测 `{"platform": 5}` / `{"spreadsheet_id": 123}` / `[1,2]` 三种 body 全中）。
- **同一口径适用于「容器型字段」**：`confirmed` 这类期望 dict 的字段，`data.get(x) or {}` 只能兜住 `None`/`""`/`0`，兜不住真值非 dict（`[1,2]`、`"abc"`）—— 那样会把 `AttributeError` 带到逻辑层炸成 500。必须显式判类型，非 dict 一律 400。判据与上一条相同：**客户端能构造出的畸形 body，只能是 4xx，不能是 5xx**。
- **「畸形」的边界（避免两种口径打架）**：畸形 = ①body 不是 JSON 对象；②容器型字段的类型不符。**标量字段给数字/`None` 不算畸形** —— 按 `str(... or "")` 兜底后照常走后续校验，该 200 就 200（`sheet_name: 5` → `"5"` 存下来），该 400 才 400（`platform: 5` → `"5"` 不在 `PLATFORMS` 里）。**不要**为了「数字也该拒绝」而对标量字段加 `isinstance(x, str)` 检查，那会与 `test_numeric_fields_are_coerced_not_500` 直接冲突（Task 5 修复时计划里真出现过这对互斥断言，一站一立才收敛）。
- **测试门禁**：`cd py && PYTHONDONTWRITEBYTECODE=1 python -m pytest tests/ -q`。
  **不写死基线数字**——以 `.superpowers/sdd/progress.md` 里各任务的**实测值**为准。本仓库有并行会话在同时加测试，数字只会涨，写死的数字必然过期（此处原写「基线 424 passed」，早已被 693 超越）。
  **`PYTHONDONTWRITEBYTECODE=1` 不能省**：同秒内生成的同字节数变异体不会让 `.pyc` 失效，会得到假 GREEN（Task 9 实测教训）。每次提交后不得低于该任务当次的实测基线。
- **各任务的计数是「累计预期」，为下界而非精确值**：以 `.superpowers/sdd/progress.md` 里记的**上一任务实测值**为准。若实际条数与预期不符，**先核实是计划写错还是实现漏做**：计划写错就改计划（并顺移后续累计值），实现漏做就补实现 —— 不要为了对上数字而删测试或改断言（Task 2 就因计划漏数而多出 1 条）。
- **前端门禁**：`cd frontend && npm run build` 必须通过。
- **前端 UI 前置**：Task 10 / Task 11 的视觉设计**已产出**：`docs/superpowers/specs/2026-09-24-huguan-frontend-visual-design.md`（2026-09-24）。两个任务动手前**先读它**，**不要**重跑 `/frontend-design` 另做一版——那只会得到一份与计划、与后端接口都对不上的第二版。设计与本计划的文字冲突时**以设计文档为准**（CLAUDE.md 该条的意图是「先有视觉设计再写 UI」，该前提已满足）；发现设计与接口对不上，回报，不要自行改设计。
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

> **⚠️ v1.31 修订 —— 上面这段代码已被实现推翻，照抄会重新引入缺陷。**
> 落地版（`py/google_sheets_service.py:685-723`）把**所有行**的写入区间收集进一个 `data`，
> 在循环**外**发**一次** `values().batchUpdate`；`data` 为空则一次都不调用。
> 上面这版在循环**内**每行发一次请求、且异常在循环内 `raise` —— 后果是
> **前面的行已落表**（半写、无回滚，错误文案还会把责任缩到单个 `account_id`）。
> 单次 `values.batchUpdate` 是原子的，所以「整批单次」不只是性能优化，它是
> 「失败即 0 行」这一契约的前提。**按落地版实现，不要照抄本块。**
> 细节见 `docs/superpowers/specs/2026-09-23-huguan-sheet-design.md` §6.1 / §6.4 / §12.5 的 v1.31 修订。

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
  - `resolve_status_id(db, name: str, owner_id, platform: str, *, create_missing: bool = True) -> int | None` — 查重键 `(name, platform)`（**不含 owner_id**）；查不到且 `create_missing=False` 时返回 `None`（不建行），`owner_id` 只用于给新建行记「谁先建的」
  - `build_diff(db, parsed_rows: list, platform: str) -> dict` — 返回 `{"to_create": [...], "to_update": [...], "owner_changes": [...], "to_skip": [...], "warnings": [...], "summary": {...}}`
  - 每个 diff 项都带 `"row"`（表里 1-indexed 行号，供报错定位与前端展示）与 `"account_id"`（供前端回传确认，按账户ID 绑定而非行号）
  - 每个 diff 项还带 `"pending_status": str | None` — 该行状态名在系统里尚不存在时的名字。**`build_diff` 绝不建行**（`dry_run` 只读），`INSERT` 推迟到 Task 7 的 `apply_diff`。文本列的新值为空串时，该列名进 `to_update[i]["clears"]`（前端必须显式标注「将清空」）
  - `summary` 额外带 `"clears": int` — 本次将被清空的列总数（首次同步前用它量化影响面）

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


def _seed_tt_account(db, advertiser_id, owner_id, **over):
    """TT 侧夹具。定位键是 `advertiser_id`（Task 6/9 的 TT 路径都靠它）。"""
    cols = {"advertiser_id": advertiser_id, "name": advertiser_id, "owner_id": owner_id,
            "country": "", "timezone": "", "consumption": "", "remark": "",
            "death_date": "", "deleted_at": None, "acquired_date": ""}
    cols.update(over)
    keys = ", ".join(cols)
    marks = ", ".join("?" for _ in cols)
    db.execute(f"INSERT INTO tt_accounts({keys}) VALUES({marks})", tuple(cols.values()))
    db.commit()


class TestResolvers:
    def test_resolve_owner_by_display_name(self, client):
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

    def test_username_colliding_with_another_display_name_is_ambiguous(self, client):
        """甲的 display_name 撞上乙的 username ⇒ 必须判为歧义，不得猜中甲。

        拆成「先查 display_name，查不到再查 username」两条查询时，这里会静默返回
        `_r5a`（display_name 那条先命中），把账户挂到错误的人名下。写表方向
        （`COALESCE(NULLIF(display_name,''), username)`）产出的是一个合成名字空间，
        反向解析必须对称。对照行 `_r5b` 是**必须被算进去的第二个命中**。
        """
        from huguan_dashboard import resolve_owner_id
        db = database.get_db()
        _seed(db, "_r5a", "撞名")   # display_name = "撞名"
        _seed(db, "撞名", "")       # username     = "撞名"（display_name 空 → 回退后也叫"撞名"）
        assert resolve_owner_id(db, "撞名") is None
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
        # acquired_date 必须显式钉成 ""：`accounts.acquired_date` 的 DDL 默认值是
        # `date('now','localtime')`（database.py:236），不钉住它就与表里的空 A 列
        # 构成一条**真实差异**，`fields` 会多出 `acquired_date: ""` 而非只有 timezone。
        _seed_account(db, "MCCACC", u1, acquired_date="")
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

    def test_blank_text_column_clears_system_value(self, client):
        """表里文本列空着 = 把系统里该列清空（规格 §8.3「按表覆盖该列」）。

        这是**刻意的**不对称：名称类字段空值跳过（空串解析不出候选，属 §8.4 的
        「命中 0 条」），文本列空值照常落库。改成「空值一律跳过」会让户管永远
        无法从表里清掉一个值（B 列「是否封户」清空即撤销死亡）。
        对照行：库里 timezone='Asia/Shanghai' 而表里 I 列为空 ⇒ 必须出现空值差异。
        """
        from huguan_dashboard import build_diff, parse_row
        db, u1, _ = self._prepare(client)
        _seed_account(db, "BLANK-1", u1, acquired_date="", timezone="Asia/Shanghai")
        parsed = [dict(parse_row(["", "", "BLANK-1"], "gg"), row=2)]
        diff = build_diff(db, parsed, "gg")
        assert len(diff["to_update"]) == 1
        assert diff["to_update"][0]["fields"]["timezone"] == ""
        db.close()

    def test_soft_deleted_bc_is_not_matched(self, client):
        """软删的 BC 不得被「唯一命中」放行（否则账户挂到已删的 BC 上）。

        对照行：同名 BC 只有一条、且已软删 ⇒ 若 SQL 不带 `deleted_at IS NULL`，
        它会成为唯一命中并被写入 bc_id。仓库既有口径见 tt_routes.py:133/198/1054/1058。
        """
        from huguan_dashboard import build_diff, parse_row
        db, u1, _ = self._prepare(client)
        _seed_tt_account(db, "BCDEL-1", u1)
        db.execute("INSERT INTO tt_bcs(name, bc_id, owner_id, deleted_at) "
                   "VALUES('已删BC','1',?,datetime('now'))", (u1,))
        db.commit()
        row = ["", "", "BCDEL-1", "已删BC", "", "", "", "", "", "", "", "", ""]
        parsed = [dict(parse_row(row, "tt"), row=2)]
        diff = build_diff(db, parsed, "tt")
        assert diff["to_update"] == []
        assert any("已删BC" in w["message"] for w in diff["warnings"])
        db.close()

    def test_tt_diff_uses_advertiser_id_and_reports_pending_status(self, client):
        """TT 侧端到端：定位键走 `advertiser_id`、新状态名走 `pending_status`。

        本任务此前**零 TT 覆盖**（实现者只用一次性探针验过），而 Task 9 的触发点
        全在 TT 侧 —— 这条把 TT 路径钉进测试网。
        系统里还没有「待优化」(tt) ⇒ 该走 pending_status（名字原样），
        **且此刻不得建行**（dry_run 只读，规格 §8.3 步骤 7）。
        落库侧的平台命名空间断言在 Task 7 的 apply 测试里。
        """
        from huguan_dashboard import build_diff, parse_row
        db, u1, _ = self._prepare(client)
        _seed_tt_account(db, "TTD-1", u1)
        row = ["", "", "TTD-1", "", "", "", "", "", "待优化", "", "", "", ""]
        parsed = [dict(parse_row(row, "tt"), row=2)]
        diff = build_diff(db, parsed, "tt")
        assert len(diff["to_update"]) == 1
        assert diff["to_update"][0]["account_id"] == "TTD-1"
        assert diff["to_update"][0]["pending_status"] == "待优化"
        assert "status_id" not in diff["to_update"][0]["fields"]
        # 只读：状态行不能在这一步出现，否则 dry_run 承诺的「不改库」就是假的
        assert db.execute("SELECT COUNT(*) AS n FROM account_statuses").fetchone()["n"] == 0
        # 定位键必须真是 advertiser_id —— 写错列会 INSERT 出第二行而不是更新这一行
        assert db.execute("SELECT owner_id FROM tt_accounts WHERE advertiser_id='TTD-1'"
                          ).fetchone()["owner_id"] == u1
        assert db.execute("SELECT COUNT(*) AS n FROM tt_accounts").fetchone()["n"] == 1
        db.close()

    def test_two_owners_same_status_name_does_not_crash(self, client):
        """两个运营写同名状态 ⇒ 必须复用同一行，不得 IntegrityError。

        真实唯一约束是 `UNIQUE(name, platform)`，**不含 owner_id**（database.py:1225
        的迁移重建，PRAGMA 实测索引列为 ['name','platform']）。若查重键带上 owner_id，
        乙的账户写「待优化」时查不中而重复 INSERT → IntegrityError 从解析穿到
        build_diff，**整份差异报告全丢**（同一 sheet 其它行的结果也拿不到）。
        对照写法：main.py:6102。
        """
        from huguan_dashboard import build_diff, parse_row
        db, u1, u2 = self._prepare(client)
        _seed_account(db, "DUP-A", u1, acquired_date="")
        _seed_account(db, "DUP-B", u2, acquired_date="")
        rows = [
            # GG 状态是 K 列（index 10）；写成 index 8 会落进 I 列（时区）
            dict(parse_row(["", "", "DUP-A", "", "", "", "张三", "", "", "", "待优化"], "gg"),
                 row=2),
            dict(parse_row(["", "", "DUP-B", "", "", "", "李四", "", "", "", "待优化"], "gg"),
                 row=3),
        ]
        diff = build_diff(db, rows, "gg")           # 不得抛异常
        assert len(diff["to_update"]) == 2
        assert {i["pending_status"] for i in diff["to_update"]} == {"待优化"}
        # 从解析层再确认一次：两个人解析同名同平台，拿到的是同一行
        from huguan_dashboard import resolve_status_id
        sid_a = resolve_status_id(db, "待优化", u1, "gg")
        sid_b = resolve_status_id(db, "待优化", u2, "gg")
        assert sid_a == sid_b
        assert db.execute("SELECT COUNT(*) AS n FROM account_statuses").fetchone()["n"] == 1
        db.close()

    def test_diff_is_read_only_even_with_new_status_name(self, client):
        """dry_run 全程只读：连「需要新建的状态行」也不许在这一步落库。

        规格 §8.3 步骤 7 / §10.1 第 6 项「dry_run=true 不改库」。插入若挂在共享连接上，
        调用方随后任何一次 commit 都会把它真写进去，而报告里的 id 也只有在提交后才存在
        ——所以必须在解析层就拦住，不能靠「反正没 commit」。
        """
        from huguan_dashboard import build_diff, parse_row
        db, u1, _ = self._prepare(client)
        _seed_account(db, "RO-1", u1, acquired_date="")
        db.execute("INSERT INTO mcc(name, mcc_id) VALUES('RO-MCC','7')")
        db.commit()
        rows = [dict(parse_row(["", "", "RO-1", "RO-MCC", "", "", "张三", "", "", "", "全新状态"],
                               "gg"), row=2)]
        before = db.execute("SELECT COUNT(*) AS n FROM account_statuses").fetchone()["n"]
        diff = build_diff(db, rows, "gg")
        db.commit()          # 调用方正常收尾的提交：不该让任何东西冒出来
        assert db.execute("SELECT COUNT(*) AS n FROM account_statuses").fetchone()["n"] == before
        item = diff["to_update"][0]
        assert item["pending_status"] == "全新状态"
        # 其余列照常比对（只有状态那一列是 pending）
        assert item["fields"]["mcc_id"] == db.execute(
            "SELECT id FROM mcc WHERE name='RO-MCC'").fetchone()["id"]
        db.close()

    def test_dead_flag_reaches_the_diff(self, client):
        """`_is_dead` 必须真的进报告 —— 它恒为 False 时封户/撤销死亡永不落库。

        对照组三行：死亡状态、B 列「是否封户」= 是、都不是。只断言 True 的那种
        测试杀不掉「恒 False」的变异体，所以第三条断言 False 是必需的。
        """
        from huguan_dashboard import build_diff, parse_row
        db, u1, _ = self._prepare(client)
        _seed_account(db, "DEAD-1", u1, acquired_date="")
        _seed_account(db, "DEAD-2", u1, acquired_date="")
        _seed_account(db, "DEAD-3", u1, death_date="2026-01-01")
        rows = [
            # GG 状态是 K 列（index 10）
            dict(parse_row(["", "", "DEAD-1", "", "", "", "张三", "", "", "", "死亡"], "gg"),
                 row=2),
            # B 列「是否封户」是 index 1 —— index 0 是 A 列日期，写错位置会变成
            # 「日期=是」，`_is_dead` 仍是 False 而被 `_same_as_existing` 过滤掉，
            # 断言直接 KeyError。
            dict(parse_row(["", "是", "DEAD-2", "", "", "", "张三"], "gg"), row=3),
            dict(parse_row(["", "", "DEAD-3", "", "", "", "张三"], "gg"), row=4),
        ]
        diff = build_diff(db, rows, "gg")
        by_row = {i["row"]: i for i in diff["to_update"]}
        assert by_row[2]["fields"]["_is_dead"] is True      # K 列「死亡」
        assert by_row[3]["fields"]["_is_dead"] is True      # B 列「是否封户」= 是
        assert by_row[4]["fields"]["_is_dead"] is False     # 撤销死亡
        db.close()

    def test_to_create_carries_db_values_not_cells(self, client):
        """`to_create` 的键名叫 `db_values` 且真装着要写进库的值。

        两个变异体一起钉住：键名被改成 `cells`（与 Task 4 的「表列字母 → 单元格值」
        契约撞名，apply_diff 会当成列字母拼出非法 SQL），以及值被置空
        （新建出来的账户会丢掉表里所有列）。
        """
        from huguan_dashboard import build_diff, parse_row
        db, u1, _ = self._prepare(client)
        db.execute("INSERT INTO mcc(name, mcc_id) VALUES('NEW-MCC','9')")
        db.commit()
        mcc_id = db.execute("SELECT id FROM mcc WHERE name='NEW-MCC'").fetchone()["id"]
        rows = [dict(parse_row(["", "", "NEW-DB", "NEW-MCC", "", "", "张三", "",
                                "Asia/Shanghai"], "gg"), row=2)]
        item = build_diff(db, rows, "gg")["to_create"][0]
        assert "db_values" in item and "cells" not in item
        dv = item["db_values"]
        assert dv["mcc_id"] == mcc_id          # 值必须在
        assert dv["timezone"] == "Asia/Shanghai"
        assert dv["_is_dead"] is False
        db.close()

    def test_agent_namespace_is_platform_scoped(self, client):
        """代理解析必须按平台隔离：GG 的表不能挂到 TT 的代理上（反之亦然）。

        两边的查名 SQL 分别是 `_SQL_AGENT_GG` / `_SQL_AGENT_TT`，写反了不会报错
        —— 只会把账户静默挂到**另一个平台**的同名代理上。
        """
        from huguan_dashboard import build_diff, parse_row
        db, u1, _ = self._prepare(client)
        _seed_account(db, "AG-GG", u1, acquired_date="")
        _seed_tt_account(db, "AG-TT", u1)
        db.execute("INSERT INTO agents(name, platform) VALUES('张三代理','gg')")
        db.execute("INSERT INTO agents(name, platform) VALUES('TT代理','tt')")
        db.commit()
        gg_id = db.execute("SELECT id FROM agents WHERE platform='gg'").fetchone()["id"]
        tt_id = db.execute("SELECT id FROM agents WHERE platform='tt'").fetchone()["id"]
        # GG 的表里写了 TT 侧的代理名 ⇒ 查不到，记警告，不落库
        gg_diff = build_diff(db, [dict(parse_row(
            ["", "", "AG-GG", "", "", "TT代理", "张三"], "gg"), row=2)], "gg")
        assert gg_diff["to_update"] == []
        assert any("TT代理" in w["message"] for w in gg_diff["warnings"])
        # 反向：TT 的表里写 GG 侧代理名 ⇒ 同样不落库
        tt_row = ["", "", "AG-TT", "", "", "张三代理", "", "", "", "", "", "", ""]
        tt_diff = build_diff(db, [dict(parse_row(tt_row, "tt"), row=2)], "tt")
        assert tt_diff["to_update"] == []
        assert any("张三代理" in w["message"] for w in tt_diff["warnings"])
        # 各自命中的正例：GG 用 gg 代理、TT 用 tt 代理（不能用上面那两行，那两行
        # 刻意写的是对侧平台的代理名）
        gg_ok = build_diff(db, [dict(parse_row(
            ["", "", "AG-GG", "", "", "张三代理", "张三"], "gg"), row=2)], "gg")
        assert gg_ok["to_update"][0]["fields"]["agent_id"] == gg_id
        tt_row_ok = ["", "", "AG-TT", "", "", "TT代理", "", "", "", "", "", "", ""]
        tt_ok = build_diff(db, [dict(parse_row(tt_row_ok, "tt"), row=2)], "tt")
        assert tt_ok["to_update"][0]["fields"]["agent_id"] == tt_id
        db.close()

    def test_duplicate_account_id_rows_are_deduped(self, client):
        """同一账户ID 在表里出现两行 ⇒ 首行生效，后续行记警告。

        不去重的话两行都会进 `to_create`，落库阶段第二行撞唯一约束，整批报错。
        """
        from huguan_dashboard import build_diff, parse_row
        db, u1, _ = self._prepare(client)
        rows = [
            dict(parse_row(["", "", "DUP-ROW", "", "", "", "张三"], "gg"), row=2),
            dict(parse_row(["", "", "DUP-ROW", "", "", "", "张三"], "gg"), row=5),
        ]
        diff = build_diff(db, rows, "gg")
        assert len(diff["to_create"]) == 1
        assert diff["to_create"][0]["row"] == 2          # 首次出现的那行
        assert diff["summary"]["total_in_sheet"] == 2    # 表里确实有两行，不虚报
        assert any(w["row"] == 5 and "DUP-ROW" in w["message"] for w in diff["warnings"])
        db.close()

    def test_update_item_lists_columns_that_will_be_cleared(self, client):
        """新值为空的列必须进 `clears`，且 summary 汇总计数。

        清空不可逆：首次同步前户管要能一眼看到「将清空多少列」，而不是在几百行差异里
        自己发现 acquired_date 被清掉了。新建账户的空列**不算**清空（那是「不填」）。
        """
        from huguan_dashboard import build_diff, parse_row
        db, u1, _ = self._prepare(client)
        _seed_account(db, "CLR-1", u1, acquired_date="2026-01-01", timezone="Asia/Shanghai")
        diff = build_diff(db, [dict(parse_row(["", "", "CLR-1"], "gg"), row=2)], "gg")
        item = diff["to_update"][0]
        assert item["clears"] == ["acquired_date", "timezone"]   # sorted，两个都被清
        assert diff["summary"]["clears"] == 2
        # 新建账户的空列不产生 clears
        new_diff = build_diff(db, [dict(parse_row(["", "", "CLR-NEW"], "gg"), row=3)], "gg")
        assert new_diff["to_create"][0].get("clears") is None
        assert new_diff["summary"]["clears"] == 0
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
    """归属名 → users.id。空 display_name 回退 username，唯一命中才返回。

    必须用**单条** COALESCE(NULLIF(display_name,''), username) 查询，不能拆成
    「先查 display_name，查不到再查 username」两条：后者会在
    「甲的 display_name 与乙的 username 同名」时静默返回甲 —— 而写表方向
    （`_GG_ROW_SQL` / `_TT_ROW_SQL`）产出的正是这一个合成名字空间，两边不对称
    就会把账户挂到错误的人名下。规格 §8.4 的统一口径是「唯一命中才落库」，
    跨命名空间撞名属 ≥2 条命中，应出警告而不是猜。
    """
    name = (name or "").strip()
    if not name:
        return None
    return resolve_named_id(
        db,
        "SELECT id FROM users WHERE COALESCE(NULLIF(display_name, ''), username) = ?",
        (name,))


def resolve_status_id(db, name: str, owner_id, platform: str, *, create_missing: bool = True):
    """状态名 → account_statuses.id。

    **查重键是 (name, platform)，不含 owner_id。** 真实唯一约束就是这两个列
    （database.py:1225 的迁移重建；database.py:505 的原始建表 UNIQUE(name, owner_id)
    已被覆盖，PRAGMA 实测 sqlite_autoindex_account_statuses_1 = ['name','platform']）。
    带上 owner_id 查重会让「甲已有『待优化』(gg)、乙的账户也写『待优化』」查不中而
    重复 INSERT，直接 sqlite3.IntegrityError —— 该异常从 _resolve_field 穿到
    build_diff，**把整份差异报告带崩**（同 sheet 其它行的结果也拿不到）。
    owner_id 只是「谁先建的」这个记账，不参与查重。
    既有正确对照：main.py:6102（/api/statuses/list 的创建）、routes/tt_accounts_routes.py:65。

    **必须带 platform**：account_statuses.platform 默认 'gg'（database.py:153），
    而状态下拉按平台过滤（main.py:6059 `/api/statuses/list`）。不写平台会让 TT 同步
    新建的状态落进 gg 命名空间 —— TT 下拉里看不见，反而出现在 GG 下拉里。
    既有代码的两种写法可对照：GG 侧靠默认值吃 'gg'（main.py:4042/4184/4944/5068），
    TT 侧显式写 'tt'（main.py:6085、tt_accounts_routes.py:69）。

    因为唯一约束成立，(name, platform) **至多命中 1 行**，所以状态解析没有
    规格 §8.4 的「命中 ≥2 条」歧义档 —— 只有 id / None 两种结果。

    create_missing=False 时只查不建（规格 §8.3 步骤 7：dry_run 不改库），
    查不到返回 None，由调用方按 pending 处理（不是 warning）。
    """
    name = (name or "").strip()
    if not name:
        return None
    row = db.execute("SELECT id FROM account_statuses WHERE name=? AND platform=?",
                     (name, platform)).fetchone()
    if row:
        return row["id"]
    if not create_missing:
        return None
    db.execute("INSERT INTO account_statuses(name, owner_id, platform) VALUES(?,?,?)",
               (name, owner_id, platform))
    return db.execute("SELECT last_insert_rowid() AS id").fetchone()["id"]


# 各可读列 → (解析器种类, 查名 SQL 模板)
_SQL_MCC = "SELECT id FROM mcc WHERE name=?"
_SQL_AGENT_GG = "SELECT id FROM agents WHERE name=? AND (platform='gg' OR platform IS NULL)"
_SQL_AGENT_TT = "SELECT id FROM agents WHERE name=? AND platform='tt'"
# tt_bcs 有 deleted_at（database.py），必须过滤软删：否则一个已删的 BC 若恰好是
# 唯一同名行，会被「唯一命中才落库」放行，把账户挂到已删的 BC 上。仓库既有口径一致
# （tt_routes.py:133/198/1054/1058 全部带 deleted_at IS NULL）。
# mcc / agents 无 deleted_at，不加；users 也无。
_SQL_BC = "SELECT id FROM tt_bcs WHERE name=? AND deleted_at IS NULL"


def _resolve_field(db, platform: str, field: str, value: str):
    """把表里的一个名称解析成系统主键；不认识的字段返回 (True, None) 表示无需解析。

    返回 (ok, resolved)：ok=False 表示该列要记 warning 且不落库。

    **status_name 刻意不在这里。** 状态有三档而其它名称只有两档：其它名称是
    「唯一命中 / 歧义（0 或 ≥2 条）」，状态是「已有 id / 系统里还没有（pending）」
    —— 因为唯一约束 (name, platform) 让状态至多命中 1 行，不存在歧义档。
    混进本函数会让「查不到」被误判成歧义而记 warning、把该列丢弃，正是规格
    §8.3 步骤 7 要避免的。状态的解析在 `_collect_updates` 里单独走。
    """
    if field == "mcc_name":
        return True, resolve_named_id(db, _SQL_MCC, (value,))
    if field == "agent_name":
        sql = _SQL_AGENT_TT if platform == "tt" else _SQL_AGENT_GG
        return True, resolve_named_id(db, sql, (value,))
    if field == "bc_name":
        return True, resolve_named_id(db, _SQL_BC, (value,))
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
    sheet_rows = len(parsed_rows)   # 表里数据行总数（**去重前**），供 summary 用

    # 产出列表必须**先于**去重循环初始化：去重本身会往 `warnings` 里塞一条，
    # 放到循环之后会 UnboundLocalError（`compile()` 查不出这种运行期绑定错误）。
    to_create, to_update, owner_changes, to_skip = [], [], [], []
    warnings = []

    # 按账户ID 去重：同一 ID 在表里出现两行时，若两行都进 to_create，落库阶段第二行
    # 会撞唯一约束。取**首次出现**的那行生效，后续行记 warning（户管要能看到并去改表）。
    # 账户ID 为空的行不在这里拦 —— 它们要按原有路径记「账户ID为空，跳过」。
    seen_rows, deduped = {}, []
    for p in parsed_rows:
        aid = (p.get("account_id") or "").strip()
        if not aid:
            deduped.append(p)
            continue
        if aid in seen_rows:
            warnings.append({"row": p.get("row"),
                             "message": f"账户ID「{aid}」已在第 {seen_rows[aid]} 行出现，本行跳过"})
            continue
        seen_rows[aid] = p.get("row")
        deduped.append(p)
    parsed_rows = deduped

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
            db_values = _collect_updates(db, platform, p, want_owner_id, row_no, warnings,
                                         create_missing=False)
            # 先摘掉合成键再入报告：db_values 会被 apply_diff 直接拼 INSERT 列名，
            # 带上下划线开头的键会变成非法 SQL。
            pending = db_values.pop("_pending_status", None)
            to_create.append({
                "row": row_no,
                "account_id": aid,
                "owner_id": want_owner_id,
                "owner_name": want_owner_name,
                # 键名刻意不叫 "cells"：本模块里 "cells" 一律指「表列字母 → 单元格值」
                # （Task 4 的 update_rows_by_account_id 契约），这里装的是
                # 「数据库列名 → 值」，供 apply_diff 拼 INSERT。两者同名会被误用。
                "db_values": db_values,
                # 系统里还没有的状态名；apply_diff 落库前才 INSERT（build_diff 只读）
                "pending_status": pending,
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
        fields = _collect_updates(db, platform, p, scope_owner, row_no, warnings,
                                  create_missing=False)
        pending = fields.pop("_pending_status", None)
        changed = {k: v for k, v in fields.items()
                   if not _same_as_existing(db, platform, existing, k, v)}
        # pending 也算真实变更：系统里没这个状态名，建出来必然与现状不同。
        # 只比 `changed` 会让「这一行只改了状态」被整行漏掉。
        if changed or pending:
            to_update.append({"row": row_no, "account_id": aid,
                              "existing_id": existing["id"], "fields": changed,
                              "pending_status": pending,
                              # apply_diff 建缺失状态行时用它记 owner（谁先建的）
                              "scope_owner_id": scope_owner,
                              # 新值为空串的文本列：清空是不可逆的，必须让前端显式标注
                              "clears": _blank_columns(platform, changed)})

    return {
        "to_create": to_create,
        "to_update": to_update,
        "owner_changes": owner_changes,
        "to_skip": to_skip,
        "warnings": warnings,
        "summary": {
            "total_in_sheet": sheet_rows,
            "new_accounts": len(to_create),
            "updates": len(to_update),
            "owner_changes": len(owner_changes),
            "skipped": len(to_skip),
            "warnings": len(warnings),
            # 只统计 to_update：新建账户的空列是「不填」，不是「清空已有值」。
            # 首次正式同步前先跑 dry_run 看这个数，是这次「空值=清空」口径的
            # 唯一量化手段（规格 §8.3）。
            "clears": sum(len(i.get("clears") or []) for i in to_update),
        },
    }


def _collect_updates(db, platform, p, owner_id, row_no, warnings, *, create_missing=True) -> dict:
    """把一行解析结果里「要写进系统」的字段收集成 {字段名: 值}。

    名称类字段先解析成主键，解析不唯一则记 warning 并丢弃该字段。

    **文本列的空值照常落库，不得写成 `if not value: continue`。** 规格 §8.3 对
    `to_update` 的口径是「**按表覆盖该列**」——表里空着就是把系统里该列清空，
    否则户管永远无法从表里清掉一个值（B 列「是否封户」清空即撤销死亡，同理）。
    §7.4「不因表里空着就把 owner_id 清空」是**归属专属例外**，不能推广到文本列。
    与下方名称类字段的 `if not value: continue` 不对称是**刻意的**：空串在名称
    命名空间里根本没有可解析的候选，属规格 §8.4 的「命中 0 条」。

    产出里可能带两个**下划线开头的合成键**（不是数据库列，调用方必须先摘掉）：
    `_is_dead` 死亡标记、`_pending_status` 系统里还没有的状态名。

    create_missing 由 build_diff 传 False（dry_run 只读），落库阶段才用默认 True。
    """
    out = {}
    for f in _PLAIN_TEXT_FIELDS[platform]:
        # `_conf_text` 兜底是因为 p 未必全是 str（同 `_conf_text` 的既有理由）
        out[f] = _conf_text(p.get(f))
    for f in _parseable_fields(platform):
        value = (p.get(f) or "").strip()
        if not value:
            continue
        if f == "status_name":
            # 状态单独走：它没有「歧义」档（唯一约束 (name, platform) 至多命中 1 行），
            # 所以查不到**不是**警告，而是「系统里还没有」——create_missing=False 时
            # 记成 pending，落库阶段再 INSERT。走下面的通用分支会被误判成歧义而丢弃。
            sid = resolve_status_id(db, value, owner_id, platform,
                                    create_missing=create_missing)
            if sid is None:
                out["_pending_status"] = value
            else:
                out["status_id"] = sid
            continue
        _known, resolved = _resolve_field(db, platform, f, value)
        if not _known:
            continue
        if resolved is None:
            warnings.append({"row": row_no,
                             "message": f"{f}「{value}」无法唯一匹配，已跳过该列"})
            continue
        out[_target_column(platform, f)] = resolved
    out["_is_dead"] = is_dead(p)
    return out


def _blank_columns(platform: str, fields: dict) -> list:
    """fields 里新值为空串的文本列（下划线开头的合成键不算）。

    规格 §8.3：文本列空着 = 清空系统里该列。这是不可逆的批量动作，所以单独列出来
    让前端显式标注「将清空」——不能让「几百行的 acquired_date 被悄悄清掉」藏在差异
    报告里。只认文本列：`_is_dead`（合成键）与主键列（`mcc_id` 等）不在此列。
    """
    return sorted(k for k, v in fields.items()
                  if k in _PLAIN_TEXT_FIELDS[platform] and v == "")


def _target_column(platform: str, field: str) -> str:
    """解析后的字段名 → 真实数据库列名。

    `status_name` 这条**不**经 `_collect_updates` 的通用分支（状态走 pending 档），
    但 apply_diff 落库时要靠它把 pending 状态名映射到 `status_id` 列，所以保留。
    """
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
Expected: PASS（聚焦 **≥ 81 passed / 0 failed**。实测口径：Task 5 末 55 条 + 本任务原始
16 条 + 事后补的 3 条（空文本列清空 / 软删 BC 不命中 / TT 端到端）= 74，再加本轮审查修复
净新增 7 条（同名状态不崩 / dry_run 只读 / `_is_dead` 三态 / `db_values` 契约 / 代理平台
隔离 / 重复账户ID 去重 / `clears` 标注；TT 那条是**改写**旧测试，净增 0）= 81。
**判据是 `0 failed`**，`≥` 是下限。）

**变异体覆盖的诚实口径**：审查点名的 6 个变异体，本轮被杀掉 5 个。第 6 个
——「状态作用域取错 owner（`scope_owner`）」——在 Task 6 里**杀不掉**，而且这不是
漏写测试：C1 修复后 `owner_id` 既不参与查重、也不影响 `build_diff` 的任何输出
（`build_diff` 已不再建状态行），它唯一的去向是 `to_update[i]["scope_owner_id"]`，
要等落库才看得出差别。**它的杀测试在 Task 7**（`TestApplyDiff` 的
`test_pending_status_row_records_scoped_owner`：落库后断言新建 `account_statuses`
行的 `owner_id == scope_owner_id`）。在 Task 7 落地前，不要说「6 个变异体都能被杀」。

- [ ] **Step 5: 跑全量测试确认无回归**

Run: `cd py && python -m pytest tests/ -q`
Expected: PASS（全量 ≥ 521 passed。**注意：本仓库有并行会话在途改 `py/main.py`**，
全量数字会随其提交浮动 —— 判据是 `0 failed`，不是精确等于某个数。）

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
  - `apply_diff(db, diff: dict, platform: str, confirmed: dict, user_id: int) -> dict` — `confirmed` 形如 `{"create": ["C-1","C-2"], "update": ["A1"], "owner": ["A2"]}`（值为**账户ID**，不是行号——行号会随表重排漂移）。返回 `{"created": n, "updated": n, "owner_changed": n, "applied_owner_rows": [...], "not_applied": [...], "errors": [...]}`
  - `owner_channel_cells(rows: list, platform: str, value: str) -> list` — 构造只写归属变更通道列的 rows
  - HTTP：`POST /api/huguan/dashboard/sync`

- [ ] **Step 1: 写失败的测试**

> 契约说明：`apply_diff` 的 `confirmed` 按**账户ID** 绑定（`{"create": ["C-1"], ...}`），不是行号。下方测试示例里的 `{"create": [2]}` 之类应读作「账户ID 为该测试 fixture 里的账户」（`C-1` / `OC-1` / `ST-1` …），行号只在 `parse_row(..., row=N)` 的 `row` 字段里出现、供报错定位。实现时以本节 Interfaces 的 `apply_diff` 签名为准。

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

    def test_apply_creates_pending_status_in_tt_namespace(self, client):
        """系统里没有的状态名，到 apply_diff 才建行，且平台必须是 'tt'。

        `build_diff` 只读（pending_status 只是个名字），所以状态行的创建**只**发生
        在这里。漏传 platform 会让 TT 的状态落进 gg 命名空间：TT 下拉里看不见、
        反而出现在 GG 下拉里（规格 §8.4）。
        """
        from huguan_dashboard import build_diff, parse_row, apply_diff
        db, u1, _ = self._setup(client)
        _seed_tt_account(db, "APS-1", u1)
        row = ["", "", "APS-1", "", "", "", "", "", "新状态", "", "", "", ""]
        parsed = [dict(parse_row(row, "tt"), row=2)]
        diff = build_diff(db, parsed, "tt")
        assert diff["to_update"][0]["pending_status"] == "新状态"
        assert db.execute("SELECT COUNT(*) AS n FROM account_statuses").fetchone()["n"] == 0
        apply_diff(db, diff, "tt", {"update": [2]}, user_id=u1)
        rows = db.execute("SELECT id, name, platform FROM account_statuses").fetchall()
        assert len(rows) == 1                      # 只建一行
        assert rows[0]["name"] == "新状态"
        assert rows[0]["platform"] == "tt"         # 不写平台会落进 gg
        assert db.execute("SELECT status_id FROM tt_accounts WHERE advertiser_id='APS-1'"
                          ).fetchone()["status_id"] == rows[0]["id"]
        db.close()

    def test_pending_status_row_records_scoped_owner(self, client):
        """新建状态行的 owner_id 取**该行的作用域归属**（换了归属就用新归属）。

        `scope_owner` 写错的后果不是报错，而是状态被记到旧运营名下 —— 静默错人。
        对照行：G 列把归属从张三改成李四，K 列写一个不存在的状态名。
        """
        from huguan_dashboard import build_diff, parse_row, apply_diff
        db, u1, u2 = self._setup(client)
        _seed_account(db, "APS-2", u1, acquired_date="")
        row = ["", "", "APS-2", "", "", "", "李四", "", "", "", "新状态X"]
        parsed = [dict(parse_row(row, "gg"), row=2)]
        diff = build_diff(db, parsed, "gg")
        assert diff["to_update"][0]["scope_owner_id"] == u2      # 新归属，不是 u1
        apply_diff(db, diff, "gg", {"owner": [2], "update": [2]}, user_id=u1)
        r = db.execute("SELECT owner_id FROM account_statuses WHERE name='新状态X'").fetchone()
        assert r["owner_id"] == u2
        db.close()

    def test_two_accounts_same_new_status_name_create_one_row(self, client):
        """两个账户写同一个新状态名 ⇒ 只建一行，第二行复用它（不得 IntegrityError）。

        真实唯一约束是 UNIQUE(name, platform)，不含 owner_id。逐个 apply 时第二行
        查重必须命中第一行建的那条；带 owner_id 查重会在这里炸。
        """
        from huguan_dashboard import build_diff, parse_row, apply_diff
        db, u1, u2 = self._setup(client)
        _seed_account(db, "AS-1", u1, acquired_date="")
        _seed_account(db, "AS-2", u2, acquired_date="")
        rows = [
            dict(parse_row(["", "", "AS-1", "", "", "", "张三", "", "", "", "共享状态"], "gg"),
                 row=2),
            dict(parse_row(["", "", "AS-2", "", "", "", "李四", "", "", "", "共享状态"], "gg"),
                 row=3),
        ]
        diff = build_diff(db, rows, "gg")
        res = apply_diff(db, diff, "gg", {"update": [2, 3]}, user_id=u1)
        assert res["errors"] == []
        assert res["updated"] == 2
        assert db.execute("SELECT COUNT(*) AS n FROM account_statuses").fetchone()["n"] == 1
        ids = {r["status_id"] for r in db.execute(
            "SELECT status_id FROM accounts WHERE account_id IN ('AS-1','AS-2')").fetchall()}
        assert len(ids) == 1                       # 两个账户指向同一行状态
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

    confirmed: {"create": [账户ID...], "update": [账户ID...], "owner": [账户ID...]}
               缺哪个键就完全不执行该类别。按账户ID 匹配，不是行号——行号会随表
               重排漂移，落库时重新拉表重算 diff 后行位移会静默作用到另一个账户。
    """
    conf = confirmed or {}
    created = updated = owner_changed = 0
    errors = []
    applied_owner_rows = []
    matched = {"create": set(), "update": set(), "owner": set()}

    table = "tt_accounts" if platform == "tt" else "accounts"
    key_field = ACCOUNT_KEY_FIELD[platform]

    for item in diff.get("to_create", []):
        if item["account_id"] not in conf.get("create", []):
            continue
        matched["create"].add(item["account_id"])
        try:
            # db_values 装的是「数据库列名 → 值」（见 build_diff 的 to_create），
            # 与表列字母的 cells 不是一回事，切勿混用。
            src = dict(item.get("db_values") or {})
            # _is_dead 是合成标记，不是数据库列，必须先摘掉再拼 INSERT
            want_dead = bool(src.pop("_is_dead", False))
            # 系统里还没有的状态名，到这一步才建行（build_diff 全程只读）
            pending = item.get("pending_status")
            if pending:
                src[_target_column(platform, "status_name")] = resolve_status_id(
                    db, pending, item.get("owner_id"), platform)
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
        if item["account_id"] not in conf.get("update", []):
            continue
        matched["update"].add(item["account_id"])
        try:
            fields = dict(item.get("fields") or {})
            is_dead_val = fields.pop("_is_dead", None)
            # 系统里还没有的状态名，到这一步才建行（build_diff 全程只读，规格 §8.3
            # 步骤 7/8）。owner 取该行作用域归属，只记「谁先建的」——不参与查重。
            pending = item.get("pending_status")
            if pending:
                fields[_target_column(platform, "status_name")] = resolve_status_id(
                    db, pending, item.get("scope_owner_id"), platform)
            if fields:
                sets = ", ".join(f"{k}=?" for k in fields)
                # 状态真变了才刷新 status_changed_date（前端「状态变更时间」据此显示）
                status_refresh = ", status_changed_date=datetime('now','localtime')" \
                    if "status_id" in fields else ""
                db.execute(f"UPDATE {table} SET {sets}{status_refresh}, "
                           "updated_at=datetime('now','localtime') WHERE id=?",
                           tuple(fields.values()) + (item["existing_id"],))
            if is_dead_val is not None:
                _apply_death(db, platform, item["existing_id"], bool(is_dead_val))
            updated += 1
        except Exception as e:
            errors.append({"row": item["row"], "error": str(e)})

    for item in diff.get("owner_changes", []):
        if item["account_id"] not in conf.get("owner", []):
            continue
        matched["owner"].add(item["account_id"])
        try:
            db.execute(f"UPDATE {table} SET owner_id=?, "
                       "updated_at=datetime('now','localtime') WHERE id=?",
                       (item["to_owner_id"], item["existing_id"]))
            owner_changed += 1
            applied_owner_rows.append({"account_id": item["account_id"],
                                       "to": item["to"]})
        except Exception as e:
            errors.append({"row": item["row"], "error": str(e)})

    db.commit()
    # 勾了但当前 diff 里没有的账户ID，别静默丢弃——明确回报，让前端知道没生效
    not_applied = [
        {"account_id": aid, "category": cat}
        for cat in ("create", "update", "owner")
        for aid in conf.get(cat, [])
        if aid not in matched[cat]
    ]
    return {"created": created, "updated": updated, "owner_changed": owner_changed,
            "applied_owner_rows": applied_owner_rows, "not_applied": not_applied,
            "errors": errors}


def _apply_death(db, platform: str, account_pk: int, want_dead: bool) -> None:
    """按死亡标记同步 death_date（对照 main.py:4638 的既有语义）。"""
    table = "tt_accounts" if platform == "tt" else "accounts"
    if want_dead:
        db.execute(f"UPDATE {table} SET death_date=date('now','localtime'), "
                   "status_changed_date=datetime('now','localtime') WHERE id=?", (account_pk,))
    else:
        db.execute(f"UPDATE {table} SET death_date='', "
                   "status_changed_date=datetime('now','localtime') WHERE id=?", (account_pk,))
```

- [ ] **Step 4: 实现 sync 端点**

追加到 `py/routes/huguan_dashboard_routes.py`。文件顶部补一行导入（照抄 `py/routes/tt_accounts_routes.py:10`）：`from cache import cache as _app_cache`（清缓存用，见下方 `clear_prefix` / `delete`）。

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

        # fail-safe：只有显式布尔 False 才落库；缺省/null/"false"(字符串)/0 一律只读
        if data.get("dry_run") is not False:
            return ok({"diff": diff})

        # confirmed 期望 {"create": [账户ID], "update": [账户ID], "owner": [账户ID]}。
        # `or {}` 兜不住真值非 dict（[1,2] / "abc"）→ apply_diff 里 conf.get 炸 500；
        # 值不是数组同样炸。两层都在这里挡住。
        confirmed = data.get("confirmed")
        if not isinstance(confirmed, dict):
            return err("confirmed 必须是对象", 400)
        for k in ("create", "update", "owner"):
            v = confirmed.get(k)
            if v is not None and not isinstance(v, list):
                return err(f"confirmed.{k} 必须是账户ID数组", 400)

        result = hd.apply_diff(db, diff, platform, confirmed, user_id=uid)

        # 规格 §8.3 步骤 8：清缓存（账户写入 → 下拉/列表失效；新建状态 → 状态下拉失效）
        _app_cache.clear_prefix("accounts:agents:")
        if any(item.get("pending_status") for item in
               diff.get("to_create", []) + diff.get("to_update", [])):
            _app_cache.delete(f"accounts:statuses:{uid}")

        # 规格 §7.2 规则 3② + 规则 4：应用了归属变更的行，回写运营列并清空变更通道列
        applied = result.pop("applied_owner_rows", [])
        if applied:
            rows = []
            for item in applied:
                rows.append({"account_id": item["account_id"],
                             "cells": {hd.OWNER_COL[platform]: item["to"]}})
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
Expected: PASS（聚焦 ≥ 91 passed。口径：Task 6 审查修复后 83 条 + 本任务原 5 条 +
本轮为 pending 状态落库补的 3 条。**判据是 `0 failed`**，`≥` 是下限。）

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
        db.execute("INSERT INTO tt_bcs(name, bc_id) VALUES('BC-P','BC-P')")
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
        不存在的用户 0。空 body（`{}`）走的是同一条 `or ""` 路径，故认领流程不受影响。
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

    def test_unknown_target_user_is_400_not_500(self, client):
        """目标用户不存在必须在写库前挡成 400 —— 否则 FK IntegrityError → 500。

        `tt_accounts.owner_id REFERENCES users(id)` 且连接开了 `PRAGMA foreign_keys=ON`。
        """
        hg, _ = _create_user(client, "_tt_rg_ghost", role="huguan", platform="tt")
        db = database.get_db()
        aid = _seed_tt(db, "TTR-5", _seed(db, "_tt_rg_gother", "吴十"))
        db.close()
        resp = client.put(f"/api/tt/accounts/{aid}/reassign", headers=hg,
                          json={"owner_id": 99999999})
        assert resp.status_code == 400
        db = database.get_db()
        assert db.execute("SELECT owner_id FROM tt_accounts WHERE id=?",
                          (aid,)).fetchone()["owner_id"] != 99999999
        db.close()

    def test_non_ascii_digit_owner_id_is_400(self, client):
        """非 ASCII 数字一律拒 —— `"١٢٣".isdigit()` 为真，不挡会静默变成 123。"""
        hg, _ = _create_user(client, "_tt_rg_bad", role="huguan", platform="tt")
        db = database.get_db()
        aid = _seed_tt(db, "TTR-6", _seed(db, "_tt_rg_badother", "郑一"))
        db.close()
        for bad in ["abc", "١٢٣", "1.5"]:
            assert client.put(f"/api/tt/accounts/{aid}/reassign", headers=hg,
                              json={"owner_id": bad}).status_code == 400, bad

    def test_oversized_owner_id_is_400(self, client):
        """超 int64 的值在 sqlite3 参数绑定处抛 OverflowError → 500，须提前挡掉。"""
        hg, _ = _create_user(client, "_tt_rg_big", role="huguan", platform="tt")
        db = database.get_db()
        aid = _seed_tt(db, "TTR-7", _seed(db, "_tt_rg_bigother", "冯二"))
        db.close()
        assert client.put(f"/api/tt/accounts/{aid}/reassign", headers=hg,
                          json={"owner_id": "9" * 25}).status_code == 400


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

修改 `py/routes/tt_accounts_routes.py` 的 `reassign_account`（按**函数名**定位，行号会漂）。**只加这几段，其余逐字节不动**：

在 `data = parse_body()` 之后（该函数前几行依次是 `db = get_db()` / `uid = get_uid()` / `data = parse_body()`）插入目标归属的计算。
**注意必须排在 `data = parse_body()` 之后**——下面这段读 `data.get("owner_id")`，插在它前面会直接 `NameError`：

```python
    # 目标归属：跨用户角色（developer/admin/户管）可用 owner_id 转给指定用户，
    # 其余角色恒为调用者自己（默认路径与改动前逐字节一致）。
    # `or ""` 不能省：owner_id 给 0 时 `"0".isdigit()` 为真，会被当成合法目标。
    target_owner = uid
    if _get_role(db, uid) in CROSS_USER_ROLES:
        raw_owner = (data.get("owner_id") or "")
        raw_owner_str = str(raw_owner).strip()
        if raw_owner_str:
            if not (raw_owner_str.isascii() and raw_owner_str.isdigit()):
                return err("owner_id 不合法", 400)
            target_owner = int(raw_owner_str)
            if target_owner > 2**63 - 1:
                return err("owner_id 不合法", 400)
```

**`isascii()` 不能省**：`"١٢٣".isdigit()`（阿拉伯-印度数字）为真，会静默转成 123。

**目标用户存在性校验**，插在 `existing` 的 404 检查之后、409 检查之前：

```python
    if target_owner != uid:
        if not db.execute("SELECT 1 FROM users WHERE id=?", (target_owner,)).fetchone():
            return err("目标用户不存在", 400)
```

**这一条是必需的、不是加固**：`tt_accounts.owner_id` 是 `INTEGER REFERENCES users(id)`（`database.py:766`），
而每次连接都 `PRAGMA foreign_keys=ON`（`database.py:42`）⇒ 指向不存在的用户会在 UPDATE 处抛
`IntegrityError` → **500**。这是本任务引入的新输入路径，照原样发出去就是新功能自带一条崩溃路径。
（GG 侧同族写法见 `main.py` 的 `accounts_reassign`，其注释同样记「改为 400」。）

然后把该函数中两处 `uid` 的归属用途替换为 `target_owner`：

- `if int(existing["owner_id"] or 0) == uid:` → `if int(existing["owner_id"] or 0) == target_owner:`
- `db.execute("UPDATE tt_accounts SET owner_id=?, ...", (uid, aid))` → `(target_owner, aid)`
- 该处的 409 文案：`target_owner == uid` 时保持「已属于当前用户」，否则用「已属于目标用户」

**不加「归属权限 403」校验（用户已裁定，勿擅自补）**：TT 的批量导入弹窗有「⚠ 他人账户 — 勾选认领」
这条**已上线**能力（`batch-lookup` 不过滤归属 ⇒ 普通用户看得见也点得动，
`TtAccountBatchImportModal.vue:520-526` 用空 body 调本端点认领）。补 403 会让它对普通用户整体失效。
TT 与 GG 在权限维度的这处差异**留给最终整分支审查裁定**，本任务不动。

并把返回文案改为区分两种情况：

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

6 处插入点（**行号与端点名均已实测**，`grep -n "@tt_accounts_bp.route"` 可复核）：

| 行号 | 端点 | 插入的调用 |
|---|---|---|
| `:86` | `POST /api/tt/accounts/create` | `_huguan_push(uid, [advertiser_id])` |
| `:355` | `POST /api/tt/accounts/batch-create` | `_huguan_push(uid, created_ids)` |
| `:287` | `PUT /api/tt/accounts/<int:aid>` | `_huguan_push(uid, [existing["advertiser_id"]])` |
| `:466` | `PUT /api/tt/accounts/<int:aid>/reassign` | `_huguan_push(uid, [existing["advertiser_id"]])` + `_huguan_owner_channel(uid, existing["advertiser_id"], target_owner)` |
| `:419` | `POST /api/tt/accounts/batch-update` | `_huguan_push(uid, affected_advertiser_ids)` |
| `:995` | `POST /api/tt/accounts/sync-from-sheet` | `_huguan_push(uid, [对应 advertiser_id])` |

**插入点的局部变量名以实际代码为准**（例如 `_huguan_push(uid, [advertiser_id])` 里的 `advertiser_id`
在 create 端点可能是别的名字，TT 表的主键字段是 `advertiser_id`）；行号仍可能随编辑漂移，
**一律以 `@tt_accounts_bp.route(...)` 里的端点字符串为锚**。

**不接入**：`:499` 软删、`:536` 恢复、`:553` 永久删 —— 只改 `deleted_at`，不动任何可映射列。

- [ ] **Step 5: 跑测试确认通过**

Run: `cd py && PYTHONDONTWRITEBYTECODE=1 python -m pytest tests/test_huguan_dashboard.py -q`
Expected: PASS（聚焦 ≥ 135 passed —— 上一任务实测 126，本任务新增 9 条：7 条 reassign + 2 条触发点。
**报告里必须写明实测数字**，低于 135 说明有用例没跑起来）

- [ ] **Step 6: 跑全量测试确认无回归**

Run: `cd py && PYTHONDONTWRITEBYTECODE=1 python -m pytest tests/ -q`
Expected: PASS（全量 ≥ 602 passed —— 上一任务实测 593 + 本任务 9 条，不得低于上一任务实测值）

**`PYTHONDONTWRITEBYTECODE=1` 不能省**：同秒内生成的两个同字节数变异体不会让 `.pyc` 失效，
会得到假 GREEN（本项目已踩过）。

- [ ] **Step 7: 提交**

```bash
git add py/routes/tt_accounts_routes.py py/tests/test_huguan_dashboard.py
git commit -m "feat: 户管看板 TT 回写接入与 TT 跨用户归属转移"
```

---

## Task 10: 前端 —— 设置页看板配置卡片

> **视觉设计已产出**：`docs/superpowers/specs/2026-09-24-huguan-frontend-visual-design.md`（1017 行，2026-09-24）。
> 本任务下方代码块里**只有**这些是有效基线：文件清单、API 路径与函数名、数据字段的取法、构建与提交步骤。
> **一切视觉细节以那份设计文档为准**，它明确取代下方代码块的 UI 部分——差异确认从 `ElMessageBox`
> 的文本行改为自绘 `el-dialog` + `el-table` 分组呈现（归属变更区五列）、「工作表名」独占一行、
> 用手写 label 而非 `el-form`。设计文档 §9 的 11 项裁定记录见 `.superpowers/sdd/progress.md`。
> 若你读设计文档时发现它**与本任务的数据字段/接口对不上**，停下来回报，不要自行改设计。

**Files:**
- Create: `frontend/src/api/huguan.js`
- Modify: `frontend/src/views/SettingsPanel.vue`（GG）
- Modify: `frontend/src/views/tt/TtSettingsPanel.vue`（TT）
- Test: `cd frontend && npm run build`（无单测框架，构建即门禁）

**Interfaces:**
- Consumes: `GET/POST /api/huguan/dashboard`、`POST /api/huguan/dashboard/push`、`POST /api/huguan/dashboard/sync`、`GET /api/google-sheets/sheets`（既有，户管已可达）
- Produces: 户管可见的配置卡片；`frontend/src/api/huguan.js` 的 `huguanApi`（Task 11 要用）

**本任务要消费的两个后端事实**（设计：`docs/superpowers/specs/2026-09-24-huguan-owner-source-and-picker-design.md`，已实现于 `py/huguan_dashboard.py` 与 `py/routes/huguan_dashboard_routes.py`）：

1. `diff.owner_changes[i]` 现在多一个 `via` 键，取值只有两个：`"owner_channel"` / `"owner_name"`。
   「归属变更」区必须显示**来源**列，且**不得直接渲染 token**——按平台映射：

   | `via` | GG 显示 | TT 显示 |
   |---|---|---|
   | `owner_channel` | 重新分配 | 换绑情况 |
   | `owner_name` | 运营 | 接户运营 |

   四个中文名与 `py/huguan_dashboard.py:24-56` 的 `COLUMN_SPEC` 表头逐字一致。**兜底**：未知 token
   渲染 `—` 而不是裸 token，避免将来加 token 时把内部标识泄到界面。（设计文档 §1.4）

2. `frontend/src/api/huguan.js` 除四个既有方法外，还要加一个 `ownerOptions()`，打到
   `GET /api/huguan/dashboard/owner-options`。Task 11 的「户归属」下拉用它，**不是** `/platform/users`。

- [ ] **Step 1: 读视觉设计文档**

Read: `docs/superpowers/specs/2026-09-24-huguan-frontend-visual-design.md`

本任务需要的四件事都在里面：卡片的视觉层级（与既有的「充值表配置」/「Google 表格配置」卡片并列时的主次关系）、六个控件的排布、差异确认对话框的信息层级（五类差异如何分组呈现、`owner_changes` 要最醒目）、以及「归属变更」区那五列的列定义。

设计已产出并裁定，**不要重跑 `/frontend-design` 另做一版**——那只会得到一份与计划、与后端接口都对不上的第二版。有缺口就回报。

- [ ] **Step 2: 新建 API 封装**

创建 `frontend/src/api/huguan.js`：

```js
import api from './client'

export const huguanApi = {
  getConfig: () => api.get('/huguan/dashboard'),
  saveConfig: (body) => api.post('/huguan/dashboard', body),
  push: (platform) => api.post('/huguan/dashboard/push', { platform }),
  sync: (body) => api.post('/huguan/dashboard/sync', body),
  // 「户归属」下拉的数据源（编辑用途，全量用户）。**不要**换回 /platform/users：
  // 那个端点是给「归属人」筛选器用的，只列该平台有未删除账户的人；拿它当改归属的
  // 选项源，户管就没法把 GG 的户转给一个只在 TT 有户的合法用户（实测缺口）。
  // 见 docs/superpowers/specs/2026-09-24-huguan-owner-source-and-picker-design.md §2。
  ownerOptions: () => api.get('/huguan/dashboard/owner-options'),
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
      <el-button :loading="hdPushing" @click="pushHd">🔄 刷新到看板</el-button>
      <el-button :loading="hdSyncing" @click="syncHd">⬇️ 从表同步到系统</el-button>
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
    ElMessage.error(e?.response?.data?.error || '刷新到看板失败')
  } finally { hdPushing.value = false }
}

async function syncHd() {
  hdSyncing.value = true
  try {
    const res = await huguanApi.sync({ platform: 'gg', dry_run: true })
    const d = res.diff
    const s = d.summary
    // ⚠ 下面这段「用 ElMessageBox 拼文本行」的**呈现方式已被视觉设计取代**：
    //   docs/superpowers/specs/2026-09-24-huguan-frontend-visual-design.md 改成自绘
    //   el-dialog + el-table 分组呈现，「归属变更」区五列（日期/账户ID/由/改为/来源）。
    //   保留这段只是为了钉住**数据侧**的决定：取哪些字段、按什么顺序、每个列表封顶多少行。
    //   照抄它的呈现方式 = 与设计文档冲突。
    const lines = [
      `表里共 ${s.total_in_sheet} 行`,
      `新增账户 ${s.new_accounts} 个`,
      `字段更新 ${s.updates} 处`,
      `归属变更 ${s.owner_changes} 个`,
      `跳过 ${s.skipped} 个`,
      `警告 ${s.warnings} 条`,
    ]
    // 清空是不可逆的：必须在确认弹窗里显式摆出来，不能藏在几百行差异里。
    // 逐个列出行号，但封顶 20 行，避免首次同步时弹窗被刷屏。
    if (s.clears) {
      lines.push(`⚠ 将清空 ${s.clears} 个字段（表里留空 = 清空系统该列）`)
    }
    if (d.owner_changes.length) {
      lines.push('', '【归属变更】')
      d.owner_changes.forEach(c => lines.push(`  第 ${c.row} 行 ${c.account_id}：${c.from || '（空）'} → ${c.to}`))
    }
    const clearing = d.to_update.filter(x => (x.clears || []).length)
    if (clearing.length) {
      lines.push('', '【将清空以下字段】（表里留空即清空，不可撤销）')
      clearing.slice(0, 20).forEach(x => lines.push(
        `  第 ${x.row} 行 ${x.account_id}：${x.clears.join('、')}`))
      if (clearing.length > 20) lines.push(`  …另有 ${clearing.length - 20} 行`)
    }
    // 系统里还没有的状态名：确认后才会新建，所以弹窗里给的是名字而不是 id
    const pendingStatus = [...d.to_create, ...d.to_update]
      .map(x => x.pending_status).filter(Boolean)
    if (pendingStatus.length) {
      const names = [...new Set(pendingStatus)]
      lines.push('', `【将新建状态】${names.join('、')}（系统里还没有）`)
    }
    if (!s.new_accounts && !s.updates && !s.owner_changes) {
      hdHint.value = '看板与系统已一致，无需同步'
      return
    }
    await ElMessageBox.confirm(lines.join('\n'), '确认从表同步到系统', {
      confirmButtonText: '确认同步',
      cancelButtonText: '取消',
      customStyle: { whiteSpace: 'pre-line' },
    })
    const applied = await huguanApi.sync({
      platform: 'gg',
      dry_run: false,
      confirmed: {
        create: d.to_create.map(x => x.account_id),
        update: d.to_update.map(x => x.account_id),
        owner: d.owner_changes.map(x => x.account_id),
      },
    })
    const r = applied.result
    ElMessage.success(`已应用：新增 ${r.created}，更新 ${r.updated}，归属变更 ${r.owner_changed}`)
    // 勾了却没落库的行（表已变化、当前 diff 里找不到该账户）：不能只看计数就报成功
    if (r.not_applied?.length) {
      const names = r.not_applied.slice(0, 20)
        .map(x => `${x.account_id}（${x.category}）`).join('、')
      const more = r.not_applied.length > 20 ? ` 等 ${r.not_applied.length} 条` : ''
      ElMessage.warning(`以下 ${r.not_applied.length} 行未落库（确认后表已变化）：${names}${more}`)
    }
    hdHint.value = ''
  } catch (e) {
    if (e !== 'cancel') ElMessage.error(e?.response?.data?.error || '从表同步到系统失败')
  } finally { hdSyncing.value = false }
}

onMounted(loadHdConfig)
```

若该文件的 `<script setup>` 里没有 `ref` / `onMounted` 的 import，补上。

- [ ] **Step 4: TT 设置页加同样的卡片**

> **⚠ 本步已于 2026-09-24 被用户裁定取代——不要按下面原文复制两份。**
>
> 原文让 TT 页「追加同样的卡片，改动三点」，即把约 753 行逐字节复制一份。Task 10 实现完成后的代码审查
> 把这条列为 Important：这个项目已经**被同一类失败咬过一次**——设计文档 §3.4 的 TT 列清单就是照 GG 结构
> 改写而来，结果三处事实错误，其中一处（称 `M 列 · 产品信息` 不会被覆盖、实际会被静默覆盖）会直接导致
> 户管数据丢失。753 行重复里任何后续修正漏改一侧，都会复现同一类漂移。
>
> **用户裁定：抽共享组件。** 实际做法见 Step 4'。

- [x] **Step 4'（取代 Step 4）：抽共享组件**

新建 `frontend/src/components/HuguanDashboardCard.vue`，`defineProps({ platform })`（`'gg' | 'tt'`）；
平台相关的一切从 `props.platform` 派生——`res.config[platform]`、`huguanApi.push(platform)` /
`sync({ platform, ... })`、`VIA_LABELS[platform]`、`PUSH_COVER[platform]`、`PUSH_SAFE[platform]`，
以及按平台切词的文案（附加说明行、幸免补充句、按钮平台词）。`FIELD_LABELS` / `WARN_TOKENS` 跨平台共用，保持不分区。

两个设置页各自删掉整块、只留 import + 一行标签，**位置不变**：
- `SettingsPanel.vue`：`</template>`（`:104`，管理员专属包层）之后、`</el-tab-pane>` 之前 ⇒ `<HuguanDashboardCard platform="gg" />`
  ——**不要放进那个 `isAdmin || isDeveloper` 的 template 里**，户管既非 admin 也非 developer，放进去就整块不渲染。
- `tt/TtSettingsPanel.vue`：`</el-card>`（`:164`）之后、`</el-tab-pane>`（`:165`）之前 ⇒ `platform="tt"`。
- 同时清掉两页里因此变成死代码的 import（`nextTick` / `huguanApi` 等）与只服务该块的局部状态、常量，
  以及那个多余的 `onMounted(loadHdConfig)`（组件自带）。**只删本块专用的**，pre-existing 代码在用的 import 不许动。

**严格等价搬运**：所有用户可见文案、`setTimeout` 时长、tooltip、默认勾选、错误分支逐字不变。本次搬运**不**顺手修
审查留下的四条 Minor（`setTimeout(...,100)` 打点、n=0 时的绿字成功态、无差异早退、`WARN_TOKENS` 含 `status_name`）。

- [ ] **Step 5: 构建验证**

Run: `cd frontend && npm run build`
Expected: 构建成功，无编译错误

**构建证不了「等价搬运」**，故必须另证字符串保全：在 `frontend/dist/assets/SettingsPanel-*.js` 与
`TtSettingsPanel-*.js` 里 grep 那批特征文案（`户管看板配置`、`重新分配`、`接户运营`、`换绑情况`、
`这个表格里没有可读的工作表`、`归属变更默认不勾选`、`确认同步`、两个对话框标题）。
注意这些文案现在应落在**共享组件的 chunk** 里（被两页共同 import），而不是每页一份 ⇒ 命中位置会变，不是回归。

- [ ] **Step 6: 提交**

```bash
git add frontend/src/components/HuguanDashboardCard.vue \
        frontend/src/api/huguan.js \
        frontend/src/views/SettingsPanel.vue \
        frontend/src/views/tt/TtSettingsPanel.vue
git commit -m "refactor(huguan): 抽 HuguanDashboardCard 共享组件（用户裁定，取代两份逐字复制）"
```

---

## Task 11: 前端 —— 账户面板「户归属」字段

> **视觉设计已产出**：`docs/superpowers/specs/2026-09-24-huguan-frontend-visual-design.md` §5（「户归属」列专章）。
> 本任务下方代码块里**只有**这些是有效基线：文件清单、标识符与数据源、`store`/`ttAccountsApi` 的调用路径、构建与提交步骤。
> **一切视觉细节以设计文档 §5 为准**，它明确取代下方代码块的 UI 部分（列宽、表头 tooltip、静息态去边框、`aria-label`、失败态）。
> 设计与本任务的接口对不上时停下来回报，不要自行改设计。

**Files:**
- Modify: `frontend/src/views/AdsAccountPanel.vue`（GG）
- Modify: `frontend/src/views/tt/TtAccountPanel.vue`（TT）
- Test: `cd frontend && npm run build`

**Interfaces:**
- Consumes: `PUT /api/accounts/<aid>/reassign`（GG，既有）、`PUT /api/tt/accounts/<aid>/reassign`（TT，Task 9 扩展后）、`huguanApi.ownerOptions()`（「户归属」列下拉的数据源，Task 10 建的封装）、`GET /api/platform/users`（**仅**「归属人」筛选器的数据源，本任务不碰）
- 注意：**这两个端点用途不同，不要合并**。`/platform/users` 只列该平台有未删除账户的用户（筛选场景的有意取舍，见 `docs/superpowers/specs/2026-09-23-owner-filter-hide-empty-users-design.md`）；`owner-options` 是全量用户（编辑场景必需）。详见 `docs/superpowers/specs/2026-09-24-huguan-owner-source-and-picker-design.md` §2。
- Produces: 仅户管可见可编辑的「户归属」列

**动手前先对齐既有标识符**（本计划的初稿在这里写错过三处，**以本表为准**）：

| 初稿里写的 | 该文件的实际情况（已核实） | 应当怎么写 |
|---|---|---|
| `accountsApi.reassign(...)` | `AdsAccountPanel.vue` 既不导入 `accountsApi` 也不导入裸 `api`；它持有 `const store = useAccountStore()`（`:172` / `:185`），而 store **已有** `reassignAccount(id, body)`（`frontend/src/stores/accounts.js:38`） | `await store.reassignAccount(row.id, { owner_id: newOwnerId })`，**零新增 import** |
| `authStore.isHuguan` | 两个面板**都没有** `authStore`，文件里没有任何 auth store 的导入 | 新增 `import { useAuthStore } from '@/stores/auth'` + `const authStore = useAuthStore()`（getter 定义在 `stores/auth.js:15`） |
| 下拉数据源 | 需要一个户管专用端点 | 新增 `import { huguanApi } from '@/api/huguan'`（Task 10 建的封装） |

TT 侧不同：`TtAccountPanel.vue:206` **已经**导入 `ttAccountsApi`，且 TT 没有 store —— TT 直接
`await ttAccountsApi.reassign(row.id, { owner_id: newOwnerId })`（`frontend/src/api/tt.js:71`），
只需再加 `huguanApi` 与 `useAuthStore` 两个 import。

- [ ] **Step 1: 读视觉设计文档**

Read: `docs/superpowers/specs/2026-09-24-huguan-frontend-visual-design.md` §5

设计已裁定以下四点，照它做，**不要重跑 `/frontend-design`**：「户归属」列在表格里的呈现（结论：常显下拉 + 静息态去边框）、与既有「归属人」筛选下拉的区分（表格外=筛选 / 表格内=编辑，靠表格边界区隔，不新增控件）、编辑后的反馈文案、以及列名为什么是「户归属」而不是「归属人」（用户原话，见设计文档 §5.1）。有缺口就回报。

- [ ] **Step 2: GG 面板加列**

在 `frontend/src/views/AdsAccountPanel.vue` 的账户表格里加一列，并用 `v-if="authStore.isHuguan"` 控制**可见性**。

> **视觉细节以设计文档 §5 为准**（`:738` 起给了成品标记）：列宽 `160`、表头带 `el-tooltip` 解释
> 「改这里会把新归属写进看板的「重新分配」列（TT 是「换绑情况」列），等你在看板同步时生效」、
> 每格 `el-select` 带 `aria-label`、静息态用 `:deep()` 去边框（手法见 `:915`）。
> **失败态是行为要求，不是装饰**（设计文档 §5.6）：用户列表加载失败时该列所有 `el-select` 一律
> `disabled` + placeholder `暂时无法加载用户列表`，并在表格顶部出一次
> `ElMessage.warning('用户列表加载失败，暂时无法修改户归属。')` —— **不要沿用
> `OwnerFilterSelect.vue:56` 的静默失败口径**：这一列是**写**操作，静默失败会让户管以为改成功了。
> 另：**不要**把「户归属」加进 `AccountModal.vue`（设计文档 §5.1 第 4 条：那里已有「认领/转移给我」
> 通路，同一动作两个入口、两种副作用才是真正的困惑源）。
> 下面这段是**最小功能基线**（无 tooltip / 无失败态 / 无 aria），不要照抄它的呈现方式。

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

在 `<script setup>` 顶部 import 区追加（本文件的既有风格是 `@/` 别名，见 `:171-183`）：

```js
import { huguanApi } from '@/api/huguan'
```

再在 `<script setup>` 中追加：

```js
const ownerOptions = ref([])   // 「户归属」列下拉：全量用户，**编辑**用途

// 数据源必须是户管专用的 owner-options，**不是** /platform/users。
// `/platform/users` 是给上方「归属人」筛选器用的：它只列**该平台有未删除账户**的用户
// （那是筛选场景的有意设计，见 docs/superpowers/specs/2026-09-23-owner-filter-hide-empty-users-design.md）。
// 拿它当改归属的选项源，户管就没法把 GG 的户转给一个只在 TT 有户的合法用户（实测缺口）。
// 两个端点各服务一个场景，勿合并回一个。
// 依据：docs/superpowers/specs/2026-09-24-huguan-owner-source-and-picker-design.md §2.4
async function loadOwnerPickerOptions() {
  if (!authStore.isHuguan) return
  try {
    const res = await huguanApi.ownerOptions()
    ownerOptions.value = res.users || []
  } catch { /* 下拉加载失败不阻塞主流程 */ }
}

async function changeOwner(row, newOwnerId) {
  const prev = row.owner_id
  row.owner_id = newOwnerId                       // 乐观更新，失败回滚
  try {
    await store.reassignAccount(row.id, { owner_id: newOwnerId })
    // 不能写「系统已把新归属写进看板的「重新分配」列」——规格 §6.3：未配置看板时
    // 那次回写是**静默跳过**的，这句在未配置时是假话。本端点不返回「是否回写」，
    // 所以只能用条件句兜底（彻底修法＝返回体带布尔，但那是 main.py 的改动，不在本任务）。
    const t = ownerOptions.value.find((u) => u.id === newOwnerId)
    const who = (t && (t.display_name || t.username)) || `用户 #${newOwnerId}`
    ElMessage.success(
      `归属已变更为「${who}」。如果配置了户管看板，新归属会写进「重新分配」列，等你在看板同步时生效`
    )
  } catch (e) {
    row.owner_id = prev
    ElMessage.error(e?.response?.data?.error || '归属变更失败')
  }
}

onMounted(loadOwnerPickerOptions)
```

- [ ] **Step 3: TT 面板加同样的列**

在 `frontend/src/views/tt/TtAccountPanel.vue` 里加同样的列，改动两点：
- `store.reassignAccount` 改为 `ttAccountsApi.reassign`（`frontend/src/api/tt.js:71`；`ttAccountsApi` 在 `:206` **已导入**，TT 面板没有 store）
- `useAuthStore` 与 `huguanApi` 两个 import 同样要加（TT 面板同样没有 `authStore`）
- 成功文案里的「重新分配」改为「换绑情况」（TT 侧户管通道列名，见规格 §3.4；Task 9 的 `_huguan_owner_channel` 写的就是这一列），条件句部分与 GG 逐字一致

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
Expected: PASS，全量 **684 passed**（`7e278e3` 实测；本计划各任务的实测基线依次为 593 → 602 → 684）。
**不得低于本任务当次的实测基线** —— 本仓库有并行会话在同时加测试，数字只会涨，掉下来就是有回归或被删用例。
（原计划此处写「≥ 509」，是计划编写时按「基线 424 + 新增 ≈ 85」估的，早已过期，勿再引用。）

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
- **Task 7 的 `confirmed` 结构校验已在计划内补齐（原为此处记录的风险，现已在端点层闭合）**：`confirmed` 载荷直接来自客户端，原写法 `data.get("confirmed") or {}` 只兜得住 `None`/`""`/`0`。已实测两条会炸成 500 的路径：① 外层是真值非 dict（`[1,2]` / `"abc"`）→ `apply_diff` 里 `conf.get` 抛 `AttributeError`；② 值不是数组（`{"create": 2}`）→ `item["account_id"] not in 2` 抛 `TypeError`。端点现已两层都判、非 dict 或非 list 一律 400，并配 `test_malformed_confirmed_is_400`。**`apply_diff` 内层 item 无需校验** —— 那些 item 由本模块 `build_diff` 产出、不经客户端，唯一的客户端输入就是账户ID（confirmed 已改按账户ID 绑定，见 Task 7 的 apply_diff 契约）。这条已并入 Global Constraints 的「容器型字段」口径。
- **警告数基线已从 618 漂到 630，不是新缺陷**：`conftest.py:28` 把 `JWT_SECRET_KEY` 固定成 15 字节的 `"test-secret-key"`，PyJWT 每次 encode/decode 都发 `InsecureKeyLengthWarning`。任何**首次**在测试文件里做 JWT 登录的任务都会抬高全量警告数（Task 5 +12）。已实测对照：未被触碰的 `test_huguan_role.py` 同样产出 289 条同类警告。**判据不是「警告数不变」而是「新增警告是否源自仓库代码」** —— 全部出自 site-packages 的 `jwt/api_jwt.py`，故不修。真正归属方是 conftest 共享 fixture（改成 ≥32 字节可一次清掉全仓），会牵动全套测试，不在本计划范围。
