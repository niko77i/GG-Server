# TT 表头映射（第一批：后端机制）实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让 TT 的每张账户表**按表头名**认列（自动别名识别 + 手工覆盖），账户ID 列认不出就拒同步，其余未识别列在差异报告里逐条上报。

**Architecture:** 引入「字段目录」（字段key ↔ 中文名 ↔ 别名 ↔ 方向）与 `resolve_column_map(headers, overrides)`，产出一份**表级** `{字段key: 列字母}`。读/写两端共 4 个函数改为接收 `col_map`；gg/fb 由既有 `COLUMN_SPEC` **合成**一份等价 map 走同一个签名，从而逐字节不变。

**Tech Stack:** Python 3.11 / Flask / SQLite / pytest / Google Sheets API（测试一律打桩）

设计依据：`docs/superpowers/specs/2026-10-09-tt-header-mapping-design.md`（下称"设计 §X"）。**本计划只做第一批（后端机制）**；前端列映射 UI 是第二批。

## Global Constraints

- **GG / FB 必须逐字节不变**：它们的取/写列由 `COLUMN_SPEC[platform]` 合成，结果与改动前完全相同；`COLUMN_SPEC` / `KEY_COL` / `OWNER_COL` / `OWNER_CHANNEL_COL` **全部保留**。
- **表头恒在第 1 行**（沿用现状，不新增配置）。
- **账户ID 列认不出 ⇒ 整次同步拒绝**（`err(...)`，文案含工作表名）；其他未识别列**不阻断**，但必须进 `unmatched_columns` 上报。
- **未采集的列一个字不碰**（读不取、写不写）。
- **手工覆盖 > 别名自动匹配 > 不采集**。
- **`landing_url` 库里为空 ⇒ 回写跳过该格**（不清表里那格）；其余字段保持"照库里值写（含空串）"。
- **提交纪律**：只 `git add` 本任务列出的文件。**禁止 `git add -A` / `git add .`**（本工作区有并行会话）。**禁止 `git push`**。
- 测试命令：`cd py && python -m pytest tests/<file> -q`。测试里必须用 `client`/`app` 夹具（把 `_db_path` 指向临时库），**不得**裸用真实 `temp/app.db`；Google Sheets 一律 monkeypatch 打桩。

---

## 文件结构

| 文件 | 职责 | 本次改动 |
|---|---|---|
| `py/huguan_dashboard.py` | 户管看板双向同步的**纯逻辑层** | 新增字段目录 + `resolve_column_map` + `spec_column_map` / `field_spec`；`parse_row` / `cells_for_row` / `_owner_sheet_from` / `owner_channel_cells` 接 `col_map`；`snapshot_push_targets` 按 `col_map` |
| `py/database.py` | 建表 + 列迁移 | `tt_accounts` 加 `subject_name` / `landing_url` |
| `py/routes/huguan_dashboard_routes.py` | 户管看板 HTTP 入口 | 逐表解析 `col_map`、读范围 `A:ZZ`、定位键校验、`unmatched_columns` 上报 |
| `py/routes/huguan_sheet_targets.py` | 三期写表目标 | 两处 `key_col` 改为按该表 `col_map` |
| `py/tests/test_huguan_dashboard.py` 等 | 测试 | 扩充 |

---

## Task 1: 字段目录 + `resolve_column_map`

**Files:**
- Modify: `py/huguan_dashboard.py`（在 `COLUMN_SPEC` 之后新增）
- Test: `py/tests/test_huguan_dashboard.py`（追加）

**Interfaces:**
- Produces:
  - `TT_FIELD_CATALOG: list[tuple]` —— 每项 `(字段key, 中文名, 别名元组, 方向"rw"|"r", 是否定位键, 空值是否跳过回写)`
  - `resolve_column_map(headers: list, overrides: dict) -> tuple[dict, list]` —— 返回 `({字段key: 列字母}, [未采集的表头名])`
  - `field_spec(platform: str) -> dict` —— `{字段key: {"writable": bool, "readable": bool, "key": bool, "skip_empty_write": bool}}`（tt 来自目录，gg/fb 由 `COLUMN_SPEC` 推导）
  - `spec_column_map(platform: str) -> dict` —— `COLUMN_SPEC` 合成的 `{字段key: 列字母}`，**只用于 gg/fb**

- [ ] **Step 1: 写失败测试**

追加到 `py/tests/test_huguan_dashboard.py`（该文件顶部已 `import huguan_dashboard as hd`；没有就补）：

```python
class TestResolveColumnMap:
    # 实测的企业户表表头（设计 §一）
    ENTERPRISE = ["日期", "是否回收", "账户ID", "主体名称", "账户名称", "BC",
                  "国家", "所属渠道", "接户运营", "时区", "下户链接"]
    # 加白户表表头 = 既有 COLUMN_SPEC["tt"] 的中文名
    JIABAI = ["入库时间", "是否回收", "账户ID", "BC", "国家", "所属渠道",
              "接户运营", "时区", "状态", "消耗", "位置", "换绑情况", "产品信息"]

    def test_enterprise_header_resolves_fully_by_alias(self):
        """企业户表零配置可认全：别名「日期」→ 入库时间，含两个新字段。"""
        m, unmatched = hd.resolve_column_map(self.ENTERPRISE, {})
        assert unmatched == [], f"应零未采集，实际={unmatched}"
        assert m["advertiser_id"] == "C"
        assert m["acquired_date"] == "A"          # ← 靠别名
        assert m["subject_name"] == "D"
        assert m["name"] == "E"
        assert m["bc_name"] == "F"
        assert m["landing_url"] == "K"

    def test_jiabai_header_resolves_identically_to_legacy_spec(self):
        """加白户表：解析结果必须与既有 COLUMN_SPEC 逐字段相同（回归锚）。"""
        m, unmatched = hd.resolve_column_map(self.JIABAI, {})
        assert unmatched == []
        legacy = {f: c for c, _h, f, _w, _r in hd.COLUMN_SPEC["tt"] if f}
        # 定位键两套命名并存（设计 §4.1/§4.4）：m 用目录名 advertiser_id，legacy 用
        # 表列名 account_id，故两侧各自剔除**自己**的键名后再逐字段比。
        # （规格里 K「位置」field=None 不采集；本走 B 后「位置」由目录的忽略条目吞掉，
        #  既不进 m、也不进未采集。）
        assert {k: v for k, v in m.items() if k != "advertiser_id"} == \
               {k: v for k, v in legacy.items() if k != "account_id"}

    def test_unknown_header_is_reported_not_silently_dropped(self):
        m, unmatched = hd.resolve_column_map(["账户ID", "备注二"], {})
        assert unmatched == ["备注二"]
        assert "remark" not in m          # 没认出来就不许映射到任何字段

    def test_override_beats_alias(self):
        """手工覆盖优先：把别名表里没有的叫法指到任意字段。"""
        m, unmatched = hd.resolve_column_map(["账户ID", "负责人"], {"负责人": "owner_name"})
        assert m["owner_name"] == "B" and unmatched == []

    def test_override_wins_over_alias(self):
        m, _u = hd.resolve_column_map(["账户ID", "日期"], {"日期": "remark"})
        assert m["remark"] == "B" and "acquired_date" not in m

    def test_duplicate_field_takes_leftmost_and_reports(self):
        """两列都叫「日期」→ 取最左，另一个记未采集（不静默）。"""
        m, unmatched = hd.resolve_column_map(["账户ID", "日期", "日期"], {})
        assert m["acquired_date"] == "B"
        assert unmatched == ["日期"]

    def test_recognized_but_ignored_header_is_not_reported(self):
        """「位置」是**认识但刻意不采集**的列：既不映射、也不进未采集列表。
        （这一条最初漏了 —— 没有它，加白户表每次同步都会报「1 列未采集 —— 位置」。）"""
        m, unmatched = hd.resolve_column_map(["账户ID", "位置"], {})
        assert unmatched == []
        assert "B" not in m.values(), "「位置」不该被映射到任何字段"

    def test_blank_header_ignored(self):
        m, unmatched = hd.resolve_column_map(["账户ID", "", "  "], {})
        assert unmatched == [] and "B" not in m.values()

    def test_key_field_flag(self):
        assert hd.field_spec("tt")["advertiser_id"]["key"] is True
        assert hd.field_spec("tt")["landing_url"]["skip_empty_write"] is True
        assert hd.field_spec("tt")["remark"]["skip_empty_write"] is False

    def test_spec_column_map_reproduces_legacy_for_gg_fb(self):
        """gg/fb 合成的 map 必须与 COLUMN_SPEC 逐字节一致（GG/FB 不变的锚）。"""
        for p in ("gg", "fb"):
            legacy = {f: c for c, _h, f, _w, _r in hd.COLUMN_SPEC[p] if f}
            assert hd.spec_column_map(p) == legacy
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd py && python -m pytest tests/test_huguan_dashboard.py -q -k TestResolveColumnMap`
Expected: FAIL —— `AttributeError: module 'huguan_dashboard' has no attribute 'resolve_column_map'`

- [ ] **Step 3: 实现**

在 `py/huguan_dashboard.py` 的 `COLUMN_SPEC` 定义之后追加：

```python
# ---------- TT 表头映射（2026-10-09 设计 §4.1）----------
#
# 每项：(字段key, 中文名, 别名元组, 方向, 是否定位键, 空值是否跳过回写)
#   - 别名是「自动识别」的**全部**依据。目前只放**有实测依据**的叫法（`日期` 来自企业户表）；
#     以后遇到新叫法加一行即可 —— 因为配置里只存"手工覆盖"，别名表一改、所有表自动受益。
#   - 方向 "r" = 只读回（表→系统），永不回写。
#   - 空值跳过回写：见设计 §4.7，目前只有 landing_url（非必填的户管自有链接，不能被系统清掉）。
#   - 未列在这里的字段（如 fb 的 operator / asset_type_name）不参与 tt 的表头映射。
TT_FIELD_CATALOG = [
    ("acquired_date",     "入库时间", ("入库时间", "日期"), "rw", False, False),
    ("_dead_flag",        "是否回收", ("是否回收",),        "rw", False, False),
    ("advertiser_id",     "账户ID",   ("账户ID",),          "rw", True,  False),
    ("subject_name",      "主体名称", ("主体名称",),        "rw", False, False),
    ("name",              "账户名称", ("账户名称",),        "rw", False, False),
    ("bc_name",           "BC",       ("BC",),              "rw", False, False),
    ("country",           "国家",     ("国家",),            "rw", False, False),
    ("agent_name",        "所属渠道", ("所属渠道",),        "rw", False, False),
    ("owner_name",        "接户运营", ("接户运营",),        "rw", False, False),
    ("timezone",          "时区",     ("时区",),            "rw", False, False),
    ("landing_url",       "下户链接", ("下户链接",),        "rw", False, True),
    ("status_name",       "状态",     ("状态",),            "rw", False, False),
    ("consumption",       "消耗",     ("消耗",),            "rw", False, False),
    ("remark",            "产品信息", ("产品信息",),        "rw", False, False),
    ("owner_change_note", "换绑情况", ("换绑情况",),        "r",  False, False),
    # 空串字段key = **认识这个表头、但刻意不采集**（legacy `COLUMN_SPEC["tt"]` 的 K「位置」
    # 就是 field=None 的同一语义）。它既不入映射、也不进 unmatched —— 否则加白户表每次
    # 同步都会报「1 列未采集 —— 位置」，把「未采集」这个信号淹成噪音。
    ("",                  "位置",     ("位置",),            "ignore", False, False),
]

# tt 的解析结果里，定位键的字段名恒为 "account_id"（与 COLUMN_SPEC 的既有约定一致：
# 解析结果用 account_id，拼 SQL / 写库用 ACCOUNT_KEY_FIELD[platform]，两个命名空间勿混）。
TT_KEY_FIELD = "account_id"

# 别名 → 字段key（同名字段只取最先出现的那个别名条目）
_TT_ALIAS_TO_FIELD = {}
for _f, _label, _aliases, _dir, _key, _skip in TT_FIELD_CATALOG:
    for _a in _aliases:
        _TT_ALIAS_TO_FIELD.setdefault(_a, _f)


def resolve_column_map(headers: list, overrides: dict) -> tuple:
    """表头行 + 手工覆盖 → ({字段key: 列字母}, [未采集的表头名])。

    优先级：**手工覆盖 > 别名自动匹配 > 不采集**（设计 §4.2）。

    - 表头文本 strip() 后匹配；空表头跳过。
    - 多列命中同一字段 ⇒ 取**最左**那列，其余记入未采集（不静默）。
    - 覆盖指向的字段key 非法 ⇒ 忽略该条并记入未采集（校验已在 HTTP 层拦，这里是纵深防御）。
    返回的未采集列表保留表头原文（strip 后），供前端逐条显示与指派。
    """
    # 只把**真正的字段**当合法覆盖目标：空串字段key 是「认识但刻意不采集」的哨兵
    # （见 TT_FIELD_CATALOG），不是字段，故不能作为手工覆盖的落点。
    catalog_fields = {f for f, _l, _a, _d, _k, _s in TT_FIELD_CATALOG if f}
    out, unmatched, taken = {}, [], set()

    def _claim(field, col_letter):
        if field in out:
            return False
        out[field] = col_letter
        taken.add(col_letter)
        return True

    # 第一轮：手工覆盖
    for i, raw in enumerate(headers):
        name = ("" if raw is None else str(raw)).strip()
        if not name or name not in (overrides or {}):
            continue
        field = (overrides or {})[name]
        if field not in catalog_fields or not _claim(field, _col_letter(i)):
            unmatched.append(name)

    # 第二轮：别名自动匹配（跳过已被覆盖占用的列）
    for i, raw in enumerate(headers):
        name = ("" if raw is None else str(raw)).strip()
        if not name or _col_letter(i) in taken:
            continue
        field = _TT_ALIAS_TO_FIELD.get(name)
        if field is None:
            # 完全不认识 ⇒ 报出来（设计 §4.3）
            if name not in (overrides or {}):
                if name not in unmatched:
                    unmatched.append(name)
            continue
        if field == "":
            # 认识、但刻意不采集（如「位置」）：既不映射也不上报
            taken.add(_col_letter(i))
            continue
        if not _claim(field, _col_letter(i)):
            unmatched.append(name)
    return out, unmatched


def _col_letter(i: int) -> str:
    """0 → "A"。只支持到 ZZ（表头映射够用；超过 702 列的表不在本次范围）。"""
    if i < 0 or i > 701:
        raise ValueError(f"列索引超出 A:ZZ 范围: {i}")
    if i < 26:
        return chr(ord("A") + i)
    return chr(ord("A") + i // 26 - 1) + chr(ord("A") + i % 26)


def field_spec(platform: str) -> dict:
    """字段key → {writable, readable, key, skip_empty_write}。

    tt 来自 TT_FIELD_CATALOG；gg/fb 由既有 COLUMN_SPEC 推导（保证行为逐字不变）。
    `key` 对 gg/fb 恒为 `ACCOUNT_KEY_FIELD` 那个字段名。
    """
    spec = {}
    if platform == "tt":
        for f, _l, _a, d, is_key, skip in TT_FIELD_CATALOG:
            if not f:
                continue          # 「认识但刻意不采集」的条目不是字段
            spec[f] = {"writable": d == "rw", "readable": True,
                       "key": is_key, "skip_empty_write": skip}
        return spec
    key_field = ACCOUNT_KEY_FIELD[platform]
    for _col, _header, field, writable, readable in COLUMN_SPEC[platform]:
        if field is None:
            continue
        spec[field] = {"writable": writable, "readable": readable,
                       "key": field == key_field, "skip_empty_write": False}
    return spec


def spec_column_map(platform: str) -> dict:
    """由既有 COLUMN_SPEC 合成的 {字段key: 列字母}。**只用于 gg / fb** ——
    它们继续走固定列规格，结果与改动前逐字节相同（设计 §4.4 的等价性承诺）。"""
    return {field: col for col, _h, field, _w, _r in COLUMN_SPEC[platform] if field}
```

`ACCOUNT_KEY_FIELD` 定义在文件更上方（`:91` 附近），`COLUMN_SPEC` 在 `:28` —— 新增代码放在它们**之后**即可。

- [ ] **Step 4: 跑测试确认通过**

Run: `cd py && python -m pytest tests/test_huguan_dashboard.py -q -k TestResolveColumnMap`
Expected: PASS（9 个用例）

- [ ] **Step 5: 提交**

```bash
git add py/huguan_dashboard.py py/tests/test_huguan_dashboard.py
git commit -m "feat(huguan): tt 表头映射——字段目录 + resolve_column_map"
```

---

## Task 2: `tt_accounts` 新增两个字段

**Files:**
- Modify: `py/database.py`（`tt_accounts` 建表语句 + `_ensure_columns` 迁移区）
- Test: `py/tests/test_tt_platform.py`

**Interfaces:**
- Produces: `tt_accounts.subject_name TEXT DEFAULT ''`、`tt_accounts.landing_url TEXT DEFAULT ''`

- [ ] **Step 1: 写失败测试**

追加到 `py/tests/test_tt_platform.py`（该文件有 `_fresh_schema_conn()`，返回 `(conn, db_path)` 元组，照文件既有用法解包）：

```python
def test_tt_accounts_has_subject_name_and_landing_url():
    conn, db_path = _fresh_schema_conn()
    try:
        cols = {r[1] for r in conn.execute("PRAGMA table_info(tt_accounts)").fetchall()}
        assert "subject_name" in cols, f"缺 subject_name。现有列: {sorted(cols)}"
        assert "landing_url" in cols, f"缺 landing_url。现有列: {sorted(cols)}"
    finally:
        conn.close()
        os.unlink(db_path)
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd py && python -m pytest tests/test_tt_platform.py -q -k subject_name`
Expected: FAIL

- [ ] **Step 3: 实现**

在 `py/database.py` 的 `tt_accounts` **建表语句**里（`account_type` 那一行旁边）加两列，并在 `_ensure_columns` 的 tt 迁移区（`account_type` 那条附近）加：

```python
    # TT 表头映射新增字段（2026-10-09 设计 §4.6）：
    #   主体名称 —— 企业户表有这一列；下户链接 —— 非必填的 URL。
    # 与 account_type 一样，建表语句与迁移区**两处都要有**。
    _add_column_if_missing(conn, "tt_accounts", "subject_name",
                           "subject_name TEXT DEFAULT ''")
    _add_column_if_missing(conn, "tt_accounts", "landing_url",
                           "landing_url TEXT DEFAULT ''")
```

- [ ] **Step 4: 跑测试确认通过 + 同族回归**

Run: `cd py && python -m pytest tests/test_tt_platform.py tests/test_tt_accounts.py -q`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add py/database.py py/tests/test_tt_platform.py
git commit -m "feat(tt): tt_accounts 加 subject_name / landing_url 两列"
```

---

## Task 3: `parse_row` / `cells_for_row` 接收 `col_map`

**Files:**
- Modify: `py/huguan_dashboard.py:125-165`（`cells_for_row` / `parse_row`）
- Test: `py/tests/test_huguan_dashboard.py`

**Interfaces:**
- Consumes: Task 1 的 `field_spec` / `spec_column_map`
- Produces:
  - `cells_for_row(row: dict, platform: str, col_map: dict | None = None) -> dict`
  - `parse_row(values: list, platform: str, col_map: dict | None = None) -> dict`
  - `col_map=None` ⇒ **自动取 `spec_column_map(platform)`**（gg/fb 与既有调用点零改动）

- [ ] **Step 1: 写失败测试**

```python
class TestColMapReadWrite:
    ENTERPRISE = ["日期", "是否回收", "账户ID", "主体名称", "账户名称", "BC",
                  "国家", "所属渠道", "接户运营", "时区", "下户链接"]

    def _row(self):
        return ["2026-10-01", "否", "7001234567890123456", "主体A", "账户甲",
                "BC-1", "US", "渠道X", "张三", "UTC+8", "https://x/y"]

    def test_parse_row_uses_col_map(self):
        cm, _u = hd.resolve_column_map(self.ENTERPRISE, {})
        p = hd.parse_row(self._row(), "tt", cm)
        assert p["account_id"] == "7001234567890123456"
        assert p["acquired_date"] == "2026-10-01"
        assert p["subject_name"] == "主体A"
        assert p["name"] == "账户甲"
        assert p["bc_name"] == "BC-1"          # ← 改前会读成「主体名称」
        assert p["agent_name"] == "渠道X"
        assert p["owner_name"] == "张三"
        assert p["landing_url"] == "https://x/y"
        assert p["_dead_flag"] == "否"

    def test_parse_row_omits_unmapped_columns(self):
        cm, _u = hd.resolve_column_map(["账户ID", "备注二"], {})
        p = hd.parse_row(["7001", "x"], "tt", cm)
        # 未采集列不得出现在任何字段里 —— 「位置」「消耗」等也应缺席
        assert "consumption" not in p and "status_name" not in p
        assert p["account_id"] == "7001"

    def test_cells_for_row_uses_col_map_letters(self):
        cm, _u = hd.resolve_column_map(self.ENTERPRISE, {})
        cells = hd.cells_for_row({"account_id": "7001", "bc_name": "BC-9", "name": "甲"},
                                 "tt", cm)
        assert cells["F"] == "BC-9"            # BC 在 F 列（企业户表）
        assert cells["E"] == "甲"              # 账户名称在 E 列
        # 语义（Global Constraints「其余字段保持照库里值写（含空串）」）：row 里没给值的
        # **可写**列照旧产出空串（等于清掉表里那格）；只有 skip_empty_write 的字段才跳过。
        assert cells["A"] == ""                # acquired_date：映射到 A，未给值 ⇒ 写空串
        assert cm["landing_url"] not in cells  # landing_url：空值跳过回写（见下一条测试）

    def test_cells_for_row_skips_unmapped_columns_entirely(self):
        """未采集的列**一个字不碰** —— 产出里不得含它的列字母。"""
        cm, _u = hd.resolve_column_map(["账户ID", "备注二"], {"备注二": "remark"})
        # 只有 account_id + remark 被采集；其余字段（bc_name 等）不在 map 里
        cells = hd.cells_for_row({"account_id": "7001", "bc_name": "BC-9", "remark": "R"},
                                 "tt", cm)
        assert set(cells) == {cm["advertiser_id"], cm["remark"]}
        assert cells[cm["remark"]] == "R"

    def test_cells_for_row_skips_empty_landing_url(self):
        """设计 §4.7：landing_url 库里为空 ⇒ 跳过该格，不清表。"""
        cm, _u = hd.resolve_column_map(self.ENTERPRISE, {})
        cells = hd.cells_for_row({"account_id": "7001", "landing_url": ""}, "tt", cm)
        assert cm["landing_url"] not in cells
        cells2 = hd.cells_for_row({"account_id": "7001", "landing_url": "https://a"},
                                  "tt", cm)
        assert cells2[cm["landing_url"]] == "https://a"

    def test_default_col_map_keeps_gg_fb_identical(self):
        """col_map=None ⇒ 走 spec_column_map；**钉死字面产出**。

        （原写作 `cells_for_row(row, p) == cells_for_row(row, p, spec_column_map(p))` ——
        两边都经 `cm = spec_column_map(p) if col_map is None else col_map` 求出、自比恒真，
        防不住 None 分支被接错图。2026-10-10 任务审查发现后改为字面期望。）
        字面期望由 `COLUMN_SPEC[platform]`（writable=True、非 _owner_channel、非 field=None）
        与该 row 的取值推出：gg 可写列 = A,B,C,D,F,G,I,J,K；fb 可写列 = A..Q 去掉只读的 I。
        键列的账户ID 非纯数字（"GG-1"/"FB-1"），`_text` 不加 ' 前缀，故为裸串。
        """
        for p, values, row, expected_cols, key_letter, key_value in (
            ("gg", ["2026-10-01", "否", "GG-1", "MCC", "US", "渠道", "张三",
                    "重新分配", "UTC+8", "大MCC", "存活", "位置", "消耗", "产品"],
             {"account_id": "GG-1", "mcc_name": "MCC", "owner_name": "张三"},
             "ABCDFGIJK", "C", "GG-1"),
            ("fb", ["2026-10-01", "op", "名称", "FB-1", "渠道", "类型", "10", "1",
                    "接户", "在用", "2026-10-02", "2", "UTC+8", "消耗", "存活", "BM", "产品"],
             {"account_id": "FB-1", "name": "名称", "owner_name": "在用"},
             "ABCDEFGHJKLMNOPQ", "D", "FB-1"),
        ):
            parsed = hd.parse_row(values, p)
            assert parsed["account_id"] == row["account_id"]
            cells = hd.cells_for_row(row, p)
            assert set(cells) == set(expected_cols)   # 恰好这些列，不多不少
            assert cells[key_letter] == key_value     # 键格字面值（非纯数字不带 ' 前缀）
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd py && python -m pytest tests/test_huguan_dashboard.py -q -k TestColMapReadWrite`
Expected: FAIL —— `TypeError: parse_row() takes 2 positional arguments but 3 were given`

- [ ] **Step 3: 实现**

替换 `cells_for_row` 与 `parse_row`：

```python
def cells_for_row(row: dict, platform: str, col_map: dict | None = None) -> dict:
    """系统 → 表：把一行账户数据转成 {列字母: 待写值}。

    `col_map` 是**这张表**的 {字段key: 列字母}；`None` ⇒ 用既有固定规格合成的
    （gg/fb 与既有调用点零改动，逐字节等价）。

    只产出「col_map 里映射到可写字段」的列，且**绝不产出归属变更通道列**
    （规格 §7.2 规则 2）—— 自动回写若顺手把户管刚填的重新分配清掉，那个变更就被静默吞了。
    **未采集的列一个字不碰**：它不在 col_map 里，自然不会出现在产出里（设计 §4.5）。
    """
    cm = spec_column_map(platform) if col_map is None else col_map
    spec = field_spec(platform)
    cells = {}
    for field, col in cm.items():
        s = spec.get(field)
        if not s or not s["writable"] or field == "_owner_channel":
            continue
        if field == "_dead_flag":
            value = "是" if (row.get("death_date") or "").strip() else ""
        elif field == "account_id":
            value = _text(row.get("account_id", ""))
        else:
            value = "" if row.get(field) is None else str(row.get(field)).strip()
        # 空值跳过回写（设计 §4.7）：非必填、由户管维护的字段，系统没填不代表要清掉表里那格。
        if not value and s["skip_empty_write"]:
            continue
        cells[col] = value
    return cells


def parse_row(values: list, platform: str, col_map: dict | None = None) -> dict:
    """表 → 系统：把一行原始单元格值转成 {字段名: 字符串值}。

    `col_map` 是**这张表**的 {字段key: 列字母}；`None` ⇒ 用既有固定规格合成的。

    不可读列（未映射列、派生列）一律不出现在结果里；`_owner_channel` 与 `_dead_flag`
    是合成字段，供上层判归属与生死。**未采集的列不产出任何字段**（设计 §4.4）。
    """
    cm = spec_column_map(platform) if col_map is None else col_map
    spec = field_spec(platform)
    out = {}
    for field, col in cm.items():
        s = spec.get(field)
        if not s or not s["readable"] or field == "account_id":
            continue
        i = col_index(col)
        raw = values[i] if len(values) > i else ""
        out[field] = ("" if raw is None else str(raw)).strip()
    # 定位键单独取。统一键名恒为 "account_id"（GG 与 TT 一致），
    # 与 ACCOUNT_KEY_FIELD 里的 DB 列名是两个命名空间：消费解析结果用
    # account_id，拼 SQL / 写库用 ACCOUNT_KEY_FIELD[platform]，勿混用。
    # lstrip("'") 假定该值只带 _text() 加的那一个前缀。
    key_col = cm.get(TT_KEY_FIELD) or cm.get(ACCOUNT_KEY_FIELD[platform]) \
        or KEY_COL[platform]
    key_i = col_index(key_col)
    raw_key = values[key_i] if len(values) > key_i else ""
    out["account_id"] = ("" if raw_key is None else str(raw_key)).strip().lstrip("'").strip()
    return out
```

> ⚠️ 注意 `tt` 的目录里字段 key 是 `advertiser_id`，而 `COLUMN_SPEC["tt"]` 里写的是
> `"account_id"`（那是**表列**语义）。`spec_column_map("tt")` 会给出 `{"account_id": "C", ...}`，
> 与目录的 `advertiser_id` 不一致 —— 所以 `resolve_column_map` 产出的 tt map 用
> **`advertiser_id`**，而 `TT_KEY_FIELD = "account_id"` 是**解析结果**的键名。
> 上面那行 `cm.get(TT_KEY_FIELD) or cm.get(ACCOUNT_KEY_FIELD[platform])` 同时兜住两种命名。

- [ ] **Step 4: 跑测试确认通过 + 全族回归**

Run: `cd py && python -m pytest tests/test_huguan_dashboard.py -q`
Expected: PASS（含所有既有用例 —— 它们走 `col_map=None`，行为必须不变）

- [ ] **Step 5: 提交**

```bash
git add py/huguan_dashboard.py py/tests/test_huguan_dashboard.py
git commit -m "feat(huguan): parse_row / cells_for_row 支持表级 col_map（gg/fb 走合成 map）"
```

---

## Task 4: `_owner_sheet_from` / `owner_channel_cells` 接收 `col_map`

**Files:**
- Modify: `py/huguan_dashboard.py:581`（`_owner_sheet_from`）、`:878`（`owner_channel_cells`）
- Test: `py/tests/test_huguan_dashboard.py`

**Interfaces:**
- Produces: 两个函数新增可选末参 `col_map=None`（`None` ⇒ `spec_column_map(platform)`）

- [ ] **Step 1: 写失败测试**

```python
class TestColMapOwnerColumns:
    def test_owner_sheet_from_uses_col_map(self):
        """撤回快照的表侧原值，列字母必须来自这张表的映射。"""
        cm, _u = hd.resolve_column_map(["账户ID", "接户运营"], {})
        parsed = {"account_id": "7001", "owner_name": "张三", "_owner_channel": ""}
        got = hd._owner_sheet_from(parsed, "tt", cm)
        assert got == {"B": "张三"}          # 接户运营在 B 列（这张表里）

    def test_owner_channel_cells_uses_col_map(self):
        cm, _u = hd.resolve_column_map(["账户ID", "换绑情况"], {})
        got = hd.owner_channel_cells([{"account_id": "7001"}], "tt", "张三", cm)
        assert got == [{"account_id": "7001", "cells": {"B": "张三"}}]

    def test_defaults_unchanged(self):
        assert hd.owner_channel_cells([{"account_id": "7001"}], "tt", "张三") == \
               hd.owner_channel_cells([{"account_id": "7001"}], "tt", "张三",
                                      hd.spec_column_map("tt"))
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd py && python -m pytest tests/test_huguan_dashboard.py -q -k TestColMapOwnerColumns`
Expected: FAIL

- [ ] **Step 3: 实现**

给两个函数各加一个可选末参 `col_map=None`，函数体内把原来取列字母的地方从
「`COLUMN_SPEC[platform]` 里找 field==X」改成 `cm[field]`（`cm = spec_column_map(platform) if col_map is None else col_map`）。
**没找到该字段就跳过该列**（未采集 ⇒ 不写不读）。

- [ ] **Step 4: 跑测试确认通过**

Run: `cd py && python -m pytest tests/test_huguan_dashboard.py tests/test_huguan_undo.py tests/test_fb_huguan_dashboard.py -q`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add py/huguan_dashboard.py py/tests/test_huguan_dashboard.py
git commit -m "feat(huguan): 归属/通道列也走表级 col_map"
```

---

## Task 5: 同步路由——逐表解析 col_map、定位键校验、未采集列上报

**Files:**
- Modify: `py/routes/huguan_dashboard_routes.py:139-167`（逐表读循环）
- Test: `py/tests/test_huguan_dashboard.py`

**Interfaces:**
- Consumes: Task 1 `resolve_column_map`、Task 3 `parse_row(values, platform, col_map)`
- Produces: 差异报告新增 `unmatched_columns: [{"sheet": str, "headers": [str]}]`

- [ ] **Step 1: 写失败测试**

```python
class TestHeaderMappingSync:
    # 注意：三个用例各自内联建 config（不共用一个 setUp helper）—— 每个用例的表配置
    # 不同（企业户 / 怪表 / 企业户），共用一个 helper 反而要传参绕。

    def test_enterprise_header_reads_correctly(self, client, monkeypatch):
        """企业户表头 → 按表头名读，不再串列（BC 不该读成「主体名称」的值）。"""
        hg, _ = _create_user(client, "_hm1", role="huguan")
        db = database.get_db()
        db.execute("INSERT OR REPLACE INTO config(key,value) VALUES(?,?)",
                   (f"huguan_dashboard_{_uid_of('_hm1')}", json.dumps({"tt": {
                       "spreadsheet_id": "SS",
                       "tables": [{"name": "企业户", "sheet_name": "企业户"}]}})))
        db.commit(); db.close()
        import google_sheets_service as gs
        monkeypatch.setattr(gs, "read_sheet_values", lambda *a, **k: [
            ["日期", "是否回收", "账户ID", "主体名称", "账户名称", "BC",
             "国家", "所属渠道", "接户运营", "时区", "下户链接"],
            ["2026-10-01", "否", "7009", "主体A", "账户甲", "BC-9",
             "US", "渠道X", "张三", "UTC+8", "https://x/y"],
        ])
        monkeypatch.setattr(gs, "build_service", lambda p: object())
        diff = client.post("/api/huguan/dashboard/sync", headers=hg,
                           json={"platform": "tt", "dry_run": True}).get_json()["diff"]
        create = diff["to_create"][0]
        assert create["account_id"] == "7009"
        assert diff.get("unmatched_columns") == []
        # 本用例只钉路由层两件事：表头解析全中（无未采集）+ 账户ID 读对。
        # 「BC 不再读成主体名称的值」由 Task 3 的 parse_row 用例钉（那里能直接断言
        # bc_name == "BC-1"）；这里钉不了 —— BC 名要经 bc 表解析成 bc_id，而临时库里
        # 没有这个 BC，_collect_updates 只会记一条「无法唯一匹配」的 warning。

    def test_missing_key_column_rejects_the_whole_sync(self, client, monkeypatch):
        """账户ID 认不出 ⇒ 拒同步（设计 §4.3 第 2 条）。"""
        hg, _ = _create_user(client, "_hm2", role="huguan")
        db = database.get_db()
        db.execute("INSERT OR REPLACE INTO config(key,value) VALUES(?,?)",
                   (f"huguan_dashboard_{_uid_of('_hm2')}", json.dumps({"tt": {
                       "spreadsheet_id": "SS",
                       "tables": [{"name": "怪表", "sheet_name": "怪表"}]}})))
        db.commit(); db.close()
        import google_sheets_service as gs
        monkeypatch.setattr(gs, "read_sheet_values",
                            lambda *a, **k: [["日期", "备注"], ["2026-10-01", "x"]])
        monkeypatch.setattr(gs, "build_service", lambda p: object())
        resp = client.post("/api/huguan/dashboard/sync", headers=hg,
                           json={"platform": "tt", "dry_run": True})
        assert resp.status_code == 400
        assert "账户ID" in resp.get_json()["error"]
        assert "怪表" in resp.get_json()["error"]

    def test_unmatched_columns_are_reported(self, client, monkeypatch):
        hg, _ = _create_user(client, "_hm3", role="huguan")
        db = database.get_db()
        db.execute("INSERT OR REPLACE INTO config(key,value) VALUES(?,?)",
                   (f"huguan_dashboard_{_uid_of('_hm3')}", json.dumps({"tt": {
                       "spreadsheet_id": "SS",
                       "tables": [{"name": "企业户", "sheet_name": "企业户"}]}})))
        db.commit(); db.close()
        import google_sheets_service as gs
        monkeypatch.setattr(gs, "read_sheet_values", lambda *a, **k: [
            ["账户ID", "备注二"], ["7009", "x"]])
        monkeypatch.setattr(gs, "build_service", lambda p: object())
        diff = client.post("/api/huguan/dashboard/sync", headers=hg,
                           json={"platform": "tt", "dry_run": True}).get_json()["diff"]
        assert diff["unmatched_columns"] == [{"sheet": "企业户", "headers": ["备注二"]}]
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd py && python -m pytest tests/test_huguan_dashboard.py -q -k TestHeaderMappingSync`
Expected: FAIL

- [ ] **Step 3: 实现**

在 `dashboard_sync` 的逐表循环里：

```python
        parsed_rows, unmatched_columns = [], []
        for t in tables:
            grid = gs.read_sheet_values(service, spreadsheet_id,
                                        t["sheet_name"], hd.HEADER_READ_RANGE["tt"]
                                        if platform == "tt" else hd.READ_RANGE[platform])
```

- tt 用新的 `HEADER_READ_RANGE = {"tt": "A:ZZ"}`（`py/huguan_dashboard.py`，并在 §4.4 把 `READ_RANGE["tt"]` 改成 `"A:ZZ"` —— **两个常量合并成一个更简单：直接把 `READ_RANGE["tt"]` 改成 `"A:ZZ"`，gg/fb 两项不动**）。
- 表头行 = `grid[0]`；`col_map, unmatched = hd.resolve_column_map(grid[0], (t.get("columns") or {}))`。
- **定位键校验**：
  ```python
            if not (col_map.get("advertiser_id") or col_map.get("account_id")):
                return err(f"工作表「{t['sheet_name']}」里找不到「账户ID」列，无法同步")
  ```
- 未采集非空则记录：`unmatched_columns.append({"sheet": t["sheet_name"], "headers": unmatched})`
- 逐行 `hd.parse_row(values, platform, col_map)`。
- **gg/fb 走原路径**（`col_map=None` ⇒ 合成 map，`READ_RANGE` 原值不变）。
- `diff` 里带上：`diff["unmatched_columns"] = unmatched_columns`（**空列表也要带**，前端据此判断）。

- [ ] **Step 4: 跑测试确认通过 + 全族回归**

Run: `cd py && python -m pytest tests/test_huguan_dashboard.py tests/test_huguan_sheet_write.py tests/test_fb_huguan_dashboard.py tests/test_gg_sheet_write.py -q`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add py/huguan_dashboard.py py/routes/huguan_dashboard_routes.py py/tests/test_huguan_dashboard.py
git commit -m "feat(tt): 同步按表头映射读列，定位键缺失拒同步，未采集列上报"
```

---

## Task 6: 写侧按 `col_map` 定位行

**Files:**
- Modify: `py/routes/huguan_sheet_targets.py:90`、`:159`
- Modify: `py/routes/huguan_dashboard_routes.py:343`（撤回写入）
- Modify: `py/huguan_dashboard.py`（`snapshot_push_targets` 按 col_map 记列）
- Test: `py/tests/test_huguan_sheet_write.py`

**Interfaces:**
- Consumes: Task 1 `resolve_column_map`、Task 3/4 的 col_map 版函数
- Produces: 写表前先读**表头行**解析 `col_map`，`key_col` 取 `col_map[定位键]`

- [ ] **Step 1: 写失败测试**

在 `py/tests/test_huguan_sheet_write.py` 追加（**自包含**，不依赖该文件的既有 helper，只 monkeypatch 两个 Sheets 入口）：

```python
def test_tt_write_uses_header_key_column(client, monkeypatch):
    """TT 表的账户ID不在 C 列时，写表必须按表头映射定位 —— 否则整批静默写空。"""
    import json
    import database
    import google_sheets_service as gs
    import huguan_dashboard as hd

    # 账户ID 在 **A 列** 的表（既有实现会按 KEY_COL["tt"]=="C" 定位 → 找不到行）
    HEADER = ["账户ID", "产品信息"]

    captured = []

    def _fake_update(svc, spreadsheet_id, sheet_name, rows, key_col="C"):
        captured.append({"sheet_name": sheet_name, "key_col": key_col, "rows": rows})
        return {"updated": len(rows), "not_found": []}

    def _fake_read(svc, spreadsheet_id, sheet_name, range_str):
        if range_str == "A1:ZZ1":          # ← 表头行读取（Task 6 新引入）
            return [HEADER]
        return [HEADER, ["7001", "备注甲"]]

    monkeypatch.setattr(gs, "update_rows_by_account_id", _fake_update)
    monkeypatch.setattr(gs, "read_sheet_values", _fake_read)
    monkeypatch.setattr(gs, "build_service", lambda p: object())
    monkeypatch.setattr("main._GOOGLE_SHEETS_CONFIG", {"credentials_path": "x"})

    # 直接调共享 helper，断言它解析出的定位列
    cm = hd.resolve_table_col_map(object(), "SS", "企业户", "tt")
    assert cm["advertiser_id"] == "A", f"应按表头定为 A 列，实际={cm}"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd py && python -m pytest tests/test_huguan_sheet_write.py -q -k header_key_column`
Expected: FAIL

- [ ] **Step 3: 实现**

抽一个共享 helper（放 `py/huguan_dashboard.py`，供路由与 targets 共用）：

```python
def resolve_table_col_map(service, spreadsheet_id: str, sheet_name: str,
                          platform: str, overrides: dict | None = None) -> dict:
    """写表前解析这张表的 col_map（读表头行）。

    gg/fb 直接返回 spec_column_map（零额外读，行为逐字节不变）；
    tt 读一次表头行（A1:ZZ1）再 resolve。找不到定位键时**抛错** ——
    绝不退回任何默认列（那会让整批静默写空）。
    """
```

然后把 `huguan_sheet_targets.py:90` / `:159` 的

```python
gs.update_rows_by_account_id(service, spreadsheet_id, sheet_name, sheet_rows,
                             key_col=hd.KEY_COL[platform])
```

改为先 `cm = hd.resolve_table_col_map(service, spreadsheet_id, sheet_name, platform)`，
再 `key_col=cm[定位键]`；`sheet_rows` 的 `cells` 也要由 col_map 版 `cells_for_row` 产出。
`huguan_dashboard_routes.py:343`（撤回）同样处理。`:296` 是 **FB 专用**，不受影响、保持原样。

- [ ] **Step 4: 跑测试确认通过 + 全族回归**

Run: `cd py && python -m pytest tests/test_huguan_sheet_write.py tests/test_huguan_dashboard.py tests/test_huguan_undo.py tests/test_gg_sheet_write.py tests/test_fb_huguan_dashboard.py tests/test_sheet_concurrent_probe.py -q`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add py/huguan_dashboard.py py/routes/huguan_sheet_targets.py py/routes/huguan_dashboard_routes.py py/tests/test_huguan_sheet_write.py
git commit -m "feat(tt): 写表按表头映射定位行（key_col 来自该表 col_map）"
```

---

## Task 7: 新字段落库 + 账户名称 + 空值跳过回写

**Files:**
- Modify: `py/huguan_dashboard.py`（`_PLAIN_TEXT_FIELDS["tt"]`、`apply_diff` 的 `src["name"]`）
- Test: `py/tests/test_huguan_dashboard.py`

**Interfaces:**
- Produces: `subject_name` / `landing_url` 能从表同步进库；`name` 优先取表里的「账户名称」

- [ ] **Step 1: 写失败测试**

```python
class TestNewFieldsSync:
    """造 config + 打桩读表 + 走 /sync 真落库（dry_run=false + confirmed.create）。"""

    def test_subject_name_and_landing_url_land_in_db(self, client, monkeypatch):
        import json
        import database
        import google_sheets_service as gs
        hg, _ = _create_user(client, "_nf1", role="huguan")
        db = database.get_db()
        db.execute("INSERT OR REPLACE INTO config(key,value) VALUES(?,?)",
                   (f"huguan_dashboard_{_uid_of('_nf1')}", json.dumps({"tt": {
                       "spreadsheet_id": "SS",
                       "tables": [{"name": "企业户", "sheet_name": "企业户"}]}})))
        db.commit(); db.close()
        header = ["日期", "是否回收", "账户ID", "主体名称", "账户名称", "BC",
                  "国家", "所属渠道", "接户运营", "时区", "下户链接"]
        row = ["2026-10-01", "否", "7101", "主体甲", "账户甲", "BC-1",
               "US", "渠道X", "张三", "UTC+8", "https://x/y"]
        monkeypatch.setattr(gs, "read_sheet_values", lambda *a, **k: [header, row])
        monkeypatch.setattr(gs, "build_service", lambda p: object())
        resp = client.post("/api/huguan/dashboard/sync", headers=hg,
                           json={"platform": "tt", "dry_run": False,
                                 "confirmed": {"create": ["7101"]}})
        assert resp.status_code == 200
        db = database.get_db()
        r = db.execute("SELECT name, subject_name, landing_url FROM tt_accounts "
                       "WHERE advertiser_id='7101'").fetchone()
        db.close()
        assert r is not None, "账户没落库"
        assert r["subject_name"] == "主体甲"
        assert r["landing_url"] == "https://x/y"

    def test_name_uses_sheet_account_name_when_mapped(self, client, monkeypatch):
        """表里有「账户名称」→ 用它当 name（不再拿账户ID）。"""
        import json
        import database
        import google_sheets_service as gs
        hg, _ = _create_user(client, "_nf2", role="huguan")
        db = database.get_db()
        db.execute("INSERT OR REPLACE INTO config(key,value) VALUES(?,?)",
                   (f"huguan_dashboard_{_uid_of('_nf2')}", json.dumps({"tt": {
                       "spreadsheet_id": "SS",
                       "tables": [{"name": "企业户", "sheet_name": "企业户"}]}})))
        db.commit(); db.close()
        header = ["账户ID", "账户名称"]
        monkeypatch.setattr(gs, "read_sheet_values",
                            lambda *a, **k: [header, ["7102", "账户乙"]])
        monkeypatch.setattr(gs, "build_service", lambda p: object())
        assert client.post("/api/huguan/dashboard/sync", headers=hg, json={
            "platform": "tt", "dry_run": False,
            "confirmed": {"create": ["7102"]}}).status_code == 200
        db = database.get_db()
        got = db.execute("SELECT name FROM tt_accounts WHERE advertiser_id='7102'"
                         ).fetchone()["name"]
        db.close()
        assert got == "账户乙", f"应用表里的账户名称，实际={got!r}"

    def test_name_falls_back_to_account_id_when_not_mapped(self, client, monkeypatch):
        """加白户表没有「账户名称」列 → name 仍回落账户ID（行为不变）。"""
        import json
        import database
        import google_sheets_service as gs
        hg, _ = _create_user(client, "_nf3", role="huguan")
        db = database.get_db()
        db.execute("INSERT OR REPLACE INTO config(key,value) VALUES(?,?)",
                   (f"huguan_dashboard_{_uid_of('_nf3')}", json.dumps({"tt": {
                       "spreadsheet_id": "SS",
                       "tables": [{"name": "加白户", "sheet_name": "加白户"}]}})))
        db.commit(); db.close()
        header = ["入库时间", "是否回收", "账户ID", "BC", "国家", "所属渠道",
                  "接户运营", "时区", "状态", "消耗", "位置", "换绑情况", "产品信息"]
        row = ["2026-10-01", "否", "7103", "BC-1", "US", "渠道X", "张三",
               "UTC+8", "存活", "", "", "", ""]
        monkeypatch.setattr(gs, "read_sheet_values",
                            lambda *a, **k: [header, row])
        monkeypatch.setattr(gs, "build_service", lambda p: object())
        assert client.post("/api/huguan/dashboard/sync", headers=hg, json={
            "platform": "tt", "dry_run": False,
            "confirmed": {"create": ["7103"]}}).status_code == 200
        db = database.get_db()
        got = db.execute("SELECT name FROM tt_accounts WHERE advertiser_id='7103'"
                         ).fetchone()["name"]
        db.close()
        assert got == "7103", f"无「账户名称」列时应回落账户ID，实际={got!r}"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd py && python -m pytest tests/test_huguan_dashboard.py -q -k TestNewFieldsSync`
Expected: FAIL

- [ ] **Step 3: 实现**

- 把 `subject_name` / `landing_url` 加进 `_PLAIN_TEXT_FIELDS["tt"]`（`py/huguan_dashboard.py:545` 附近）——
  它是"文本列空着 = 清空系统该列"的口径所依据的集合；这两个字段确实该按表覆盖。
- `apply_diff` 的 create 分支：`src["name"] = item["account_id"]` 改为
  ```python
            # 设计 §4.6：表里有「账户名称」列就用它；没有（如加白户表）仍回落账户 ID。
            src["name"] = (src.pop("_sheet_name", None) or "").strip() or item["account_id"]
  ```
  并在 `_collect_updates` 里把映射到的 `name` 值搬成合成键 `_sheet_name`（照 `_is_dead` 的惯例）。

- [ ] **Step 4: 跑测试确认通过 + 全量回归**

Run: `cd py && python -m pytest tests/ -q`
Expected: 全绿（这是本批的收尾，跑全量）

- [ ] **Step 5: 提交**

```bash
git add py/huguan_dashboard.py py/tests/test_huguan_dashboard.py
git commit -m "feat(tt): 主体名称/下户链接落库，账户名称优先取表里的值"
```

---

## Task 8: 配置——`tables[i].columns` 的读取与校验

**Files:**
- Modify: `py/routes/huguan_dashboard_routes.py`（POST 校验 `:71-96`）
- Modify: `py/huguan_dashboard.py`（`get_platform_tables` 带出 `columns`）
- Test: `py/tests/test_huguan_dashboard.py`

**Interfaces:**
- Produces: `get_platform_tables` 每项多一个 `columns`（dict，可为空 `{}`）；POST 校验 `columns` 合法性

- [ ] **Step 1: 写失败测试**

```python
class TestColumnsConfig:
    def test_post_rejects_unknown_field_key(self, client):
        hg, _ = _create_user(client, "_cc1", role="huguan")
        resp = client.post("/api/huguan/dashboard", headers=hg, json={
            "platform": "tt", "spreadsheet_id": "T1",
            "tables": [{"name": "企业户", "sheet_name": "企业户",
                        "columns": {"负责人": "不存在的字段"}}]})
        assert resp.status_code == 400
        assert "不存在的字段" in resp.get_json()["error"]

    def test_post_rejects_duplicate_field_key(self, client):
        hg, _ = _create_user(client, "_cc2", role="huguan")
        resp = client.post("/api/huguan/dashboard", headers=hg, json={
            "platform": "tt", "spreadsheet_id": "T1",
            "tables": [{"name": "企业户", "sheet_name": "企业户",
                        "columns": {"负责人": "owner_name", "运营": "owner_name"}}]})
        assert resp.status_code == 400
        assert "owner_name" in resp.get_json()["error"]

    def test_post_rejects_non_object_columns(self, client):
        hg, _ = _create_user(client, "_cc3", role="huguan")
        resp = client.post("/api/huguan/dashboard", headers=hg, json={
            "platform": "tt", "spreadsheet_id": "T1",
            "tables": [{"name": "企业户", "sheet_name": "企业户",
                        "columns": ["负责人"]}]})
        assert resp.status_code == 400

    def test_columns_saved_and_read_back(self, client):
        hg, _ = _create_user(client, "_cc4", role="huguan")
        assert client.post("/api/huguan/dashboard", headers=hg, json={
            "platform": "tt", "spreadsheet_id": "T1",
            "tables": [{"name": "企业户", "sheet_name": "企业户",
                        "columns": {"负责人": "owner_name"}}]}).status_code == 200
        tt = client.get("/api/huguan/dashboard", headers=hg).get_json()["config"]["tt"]
        assert tt["tables"][0]["columns"] == {"负责人": "owner_name"}

    def test_columns_default_empty(self, client):
        """没配 columns 的表也要带出空 dict（前端据此渲染，不用判 None）。"""
        hg, _ = _create_user(client, "_cc5", role="huguan")
        client.post("/api/huguan/dashboard", headers=hg, json={
            "platform": "tt", "spreadsheet_id": "T1",
            "tables": [{"name": "加白户", "sheet_name": "加白户"}]})
        tt = client.get("/api/huguan/dashboard", headers=hg).get_json()["config"]["tt"]
        assert tt["tables"][0]["columns"] == {}
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd py && python -m pytest tests/test_huguan_dashboard.py -q -k TestColumnsConfig`

- [ ] **Step 3: 实现**

- `get_platform_tables`：tt 的每项加 `"columns": {...}`（原样透出配置里的覆盖，缺省 `{}`）。
- POST 校验追加：
  ```python
            cols = t.get("columns")
            if cols is not None:
                if not isinstance(cols, dict):
                    return err(f"户类型「{name}」的 columns 必须是对象", 400)
                seen_fields = set()
                for header, field in cols.items():
                    if field not in _TT_CATALOG_FIELDS:
                        return err(f"列「{header}」指向了未知字段「{field}」", 400)
                    if field in seen_fields:
                        return err(f"字段「{field}」被两列同时指定", 400)
                    seen_fields.add(field)
  ```
  （`_TT_CATALOG_FIELDS` = `{f for f, *_ in hd.TT_FIELD_CATALOG}`，从 `huguan_dashboard` 导出。）

- [ ] **Step 4: 跑测试确认通过**

Run: `cd py && python -m pytest tests/test_huguan_dashboard.py tests/test_tt_routes.py -q`

- [ ] **Step 5: 提交**

```bash
git add py/huguan_dashboard.py py/routes/huguan_dashboard_routes.py py/tests/test_huguan_dashboard.py
git commit -m "feat(tt): 配置支持 tables[].columns 手工覆盖（含校验）"
```

---

## 收尾（人工验证，用户自测）

1. **企业户表零配置**：不配 `columns`，点「从表同步到系统」→ BC 栏落的是真实 BC 值（不再是「主体名称」的值）。
2. **未采集列上报**：某表加一列「备注二」→ 差异报告里出现「企业户：1 列未采集 —— 备注二」。
3. **定位键缺失**：把「账户ID」列改名 → 同步被拒，错误文案含工作表名。
4. **加白户表回归**：A:M 那张表同步结果与改动前**完全一样**。
5. **GG/FB 回归**：两边同步行为不变。
