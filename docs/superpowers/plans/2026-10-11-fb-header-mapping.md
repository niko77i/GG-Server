# FB 户管看板：按表头映射字段（子项目 A）实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 FB 户管看板从「按列字母读写」改成「按表头名读写」，并给它一块与 TT 同款的「列映射」面板——表头改名/换序/插列时不再静默串列。

**Architecture:** 引入一份按平台的 `FIELD_CATALOG`：TT 手写、**FB 从 `COLUMN_SPEC["fb"]` 推导**（分配只有一份真相）。既有的表头解析器（`resolve_column_map` / `describe_header_columns` / `field_spec`）全部接 `platform` 参数，gg 继续走 `spec_column_map` 合成路径（逐字节不变）。FB 的配置多一个可选的 `columns`（手工覆盖），前端把扁平的 `sheet_name + columns` 包成一条 `tables` 复用 TT 的模板。

**Tech Stack:** Python 3.11 / Flask / SQLite / pytest；Vue 3 + Element Plus；纯逻辑测试用 `node --test`（`.mjs`）。

**Spec:** `docs/superpowers/specs/2026-10-11-fb-header-mapping-design.md`

## Global Constraints

- **不启动任何进程**：前端 dev server 与后端 5001 都由用户控制。改完只需跑测试，不要起服务。
- **禁止 `git add -A` / `git pull` / `git push`**。提交一律显式列出该任务改动的文件（`git add <file>` 后再 `git commit -- <file>`）。
- **这个仓库有并行会话共用工作区**：不要 `git checkout` / `git stash` / 切分支；sdd 草稿放自己的子目录 `.superpowers/sdd/fb-header-mapping/`。
- **GG 的行为逐字节不变**：`COLUMN_SPEC["gg"]`、`READ_RANGE["gg"]="A:N"`、`col_map=None` 路径、gg 的配置载荷形状（**不含 `columns`、不含 `*_field_catalog`**）都不许动。
- **TT 的行为逐字节不变**：只有函数签名/改名的机械改动；每个任务结束时 TT 的既有测试必须全绿。
- **`temp/` 只看不写**，尤其不碰 `.db`。
- 测试命令：后端 `cd py && python -m pytest tests/<file> -q`；前端 `cd frontend && npm test`。
- 提交信息格式：`<type>(fb-header-mapping): <中文说明>`。

### 三个必须遵守的接口约定（后面每个任务都依赖）

1. **方向字典 `_DIRECTION = {"rw": (True, True), "w": (True, False), "r": (False, True)}`** —— 键是「可写, 可读」，`"w"` 是本次新引入的只写档。哨兵条目的 `"ignore"` **不在**这张表里。
2. **`resolve_column_map(headers, overrides, platform)`** —— 第三个参数**无默认值**，漏传要当场 `TypeError`。
3. **命名空间**：col_map 的键用 `COLUMN_SPEC` 的第 3 项（fb 是 `channel_name`/`status_name`/`owner_name`/`primary_bm_name`/`account_id`）；解析结果与 DB 列名是另外两个命名空间，勿混。

---

## 文件结构

| 文件 | 职责 | 本次改动 |
|---|---|---|
| `py/huguan_dashboard.py` | 户管看板纯逻辑层（列规格、目录、读写映射、diff） | 目录归一 + 读写路径平台化 |
| `py/routes/huguan_dashboard_routes.py` | HTTP 入口（配置、同步、刷新、读表头、撤回） | 放行 fb + 错误文案按平台 |
| `py/routes/huguan_sheet_targets.py` | 写表目标的按账户重建 | 角色列/定位键列按 col_map |
| `frontend/src/components/HuguanDashboardCard.vue` | 户管看板卡片（含列映射 UI） | fb 复用 tt 模板 |
| `py/tests/test_huguan_dashboard.py` | 主回归 | 加参数 + 新增 FB 用例 |
| `py/tests/test_fb_huguan_dashboard.py` | FB 看板回归 | 更新 `READ_RANGE` 断言 + 新增用例 |
| `py/tests/test_huguan_sheet_write.py` / `test_huguan_undo.py` | 写表/撤回回归 | 加参数 |

---

## Task 1: 字段目录按平台归一（`FIELD_CATALOG` + `field_spec` 走目录）

**Files:**
- Modify: `py/huguan_dashboard.py`（`:86-127` 目录区、`:390-398` 列常量区、`:297-317` `field_spec`）
- Test: `py/tests/test_huguan_dashboard.py`（文件末尾追加一个测试类）

**Interfaces:**
- Consumes: 无（第一个任务）
- Produces: `FIELD_CATALOG: dict[str, list]`（键 `"tt"`/`"fb"`，值为 6 元组列表 `(字段key, 中文名, 别名元组, 方向, 是否定位键, 空值跳过)`）；`_DIRECTION: dict[str, tuple[bool, bool]]`；`_derive_catalog(platform) -> list`

- [ ] **Step 1: 写失败的测试**

在 `py/tests/test_huguan_dashboard.py` 末尾追加：

```python
class TestFieldCatalogPerPlatform:
    """FB 的字段目录从 COLUMN_SPEC["fb"] 推导（设计 §4.1）。分配只有一份真相。"""

    def test_derived_catalog_matches_column_spec_item_by_item(self):
        from huguan_dashboard import COLUMN_SPEC, FIELD_CATALOG, ACCOUNT_KEY_FIELD
        derived = FIELD_CATALOG["fb"]
        assert len(derived) == len(COLUMN_SPEC["fb"]) == 17
        dirs = {"r": (False, True), "w": (True, False), "rw": (True, True)}
        for (col, header, field, writable, readable), entry in zip(COLUMN_SPEC["fb"], derived):
            key, label, aliases, d, is_key, skip = entry
            assert key == field, f"{col} 列的字段key 推导错了"
            assert label == header, f"{col} 列的中文名必须是表头原文"
            assert aliases == (header,), f"{col} 列的别名就是表头原文"
            assert dirs[d] == (writable, readable), f"{col} 列的方向推导错了"
            assert is_key == (field == ACCOUNT_KEY_FIELD["fb"]), f"{col} 列的定位键标志错了"
            assert skip is False

    def test_field_spec_fb_equivalent_to_column_spec(self):
        """fb 改走目录后，field_spec("fb") 必须与从 COLUMN_SPEC 推导的逐字段相同。"""
        from huguan_dashboard import COLUMN_SPEC, ACCOUNT_KEY_FIELD, field_spec
        key_field = ACCOUNT_KEY_FIELD["fb"]
        legacy = {}
        for _col, _h, field, writable, readable in COLUMN_SPEC["fb"]:
            if field is None:
                continue
            legacy[field] = {"writable": writable, "readable": readable,
                             "key": field == key_field, "skip_empty_write": False}
        assert field_spec("fb") == legacy

    def test_field_spec_fb_three_directions(self):
        """三个方向都要推对：只写 / 只读回 / 读写。"""
        from huguan_dashboard import field_spec
        s = field_spec("fb")
        assert s["operator"] == {"writable": True, "readable": False,
                                 "key": False, "skip_empty_write": False}
        assert s["account_id"] == {"writable": True, "readable": False,
                                   "key": True, "skip_empty_write": False}
        assert s["acceptor"] == {"writable": False, "readable": True,
                                 "key": False, "skip_empty_write": False}
        assert s["timezone"] == {"writable": True, "readable": True,
                                 "key": False, "skip_empty_write": False}

    def test_field_spec_gg_still_from_column_spec(self):
        """gg 不走目录，仍由 COLUMN_SPEC 推导 —— 逐字段不变。"""
        from huguan_dashboard import COLUMN_SPEC, ACCOUNT_KEY_FIELD, FIELD_CATALOG, field_spec
        assert "gg" not in FIELD_CATALOG
        key_field = ACCOUNT_KEY_FIELD["gg"]
        legacy = {}
        for _col, _h, field, writable, readable in COLUMN_SPEC["gg"]:
            if field is None:
                continue
            legacy[field] = {"writable": writable, "readable": readable,
                             "key": field == key_field, "skip_empty_write": False}
        assert field_spec("gg") == legacy

    def test_field_spec_tt_unchanged(self):
        """TT 走目录前后逐字段相同（含 landing_url 的「空值跳过回写」）。"""
        from huguan_dashboard import field_spec
        s = field_spec("tt")
        assert s["landing_url"]["skip_empty_write"] is True
        assert s["owner_change_note"] == {"writable": False, "readable": True,
                                         "key": False, "skip_empty_write": False}
        assert s["advertiser_id"]["key"] is True
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd py && python -m pytest tests/test_huguan_dashboard.py -q -k TestFieldCatalogPerPlatform`

Expected: FAIL —— `ImportError: cannot import name 'FIELD_CATALOG'`

- [ ] **Step 3a: 把列常量区上移（纯移动，无行为改动）**

`py/huguan_dashboard.py` 现在是「`COLUMN_SPEC`（:29-84）→ `TT_FIELD_CATALOG`（:94）→ … → 列常量（:390-398）」。因为目录推导要用 `ACCOUNT_KEY_FIELD`，把 `:390-398` 那一整块**整段剪切**到 `COLUMN_SPEC` 之后（即 `# ---------- TT 表头映射（2026-10-09 设计 §4.1）----------` 那行之前）：

```python
KEY_COL = {"gg": "C", "tt": "C", "fb": "D"}
OWNER_COL = {"gg": "G", "tt": "G", "fb": "J"}
OWNER_CHANNEL_COL = {"gg": "H", "tt": "L"}      # 刻意不含 fb，见 spec §6.5
# tt / fb 读 A:ZZ：表头映射后列数不定（户管每加一张表表头都不同，且「认识但刻意不采集」
# 的列也占位），固定范围会读漏右侧列。gg 仍走固定 A:N（逐字节不变）。
READ_RANGE = {"gg": "A:N", "tt": "A:ZZ", "fb": "A:ZZ"}   # ← fb 的改动在 Task 4
# 系统里「账户ID」列在两张表下的实际字段名
ACCOUNT_KEY_FIELD = {"gg": "account_id", "tt": "advertiser_id", "fb": "account_id"}
```

> ⚠️ 本步**只搬位置**，`READ_RANGE["fb"]` 仍须是 `"A:Q"` —— 改成 `"A:ZZ"` 是 Task 4 的事。
> 注释里那句 fb 说明也留到 Task 4 再写。搬完立刻跑一次全量确认没搬坏。

Run: `cd py && python -m pytest tests/ -q`
Expected: PASS（与改动前同样的通过数）

- [ ] **Step 3b: 加 `_DIRECTION` / `_derive_catalog` / `FIELD_CATALOG`**

在 `TT_FIELD_CATALOG` 定义之后（`_TT_ALIAS_TO_FIELD` 之前）插入：

```python
# 方向 → (可写, 可读)。"w" = 只写不读回（FB 的「操作人」是冻结字段、「资产UID」是定位键）；
# "r" = 只读回（FB 的「接户运营」）。哨兵条目用的 "ignore" **不在这张表里** —— 它不是字段。
_DIRECTION = {"rw": (True, True), "w": (True, False), "r": (False, True)}


def _derive_catalog(platform: str) -> list:
    """由既有 `COLUMN_SPEC[platform]` 推导字段目录（设计 §4.1）。

    **只用于 fb。** tt 的目录是手写的 `TT_FIELD_CATALOG` —— 它需要多别名
    （`日期` 也是 `入库时间`）与「认识但刻意不采集」的哨兵，`COLUMN_SPEC` 表达不了。
    fb 这 17 列既没有第二别名、也没有哨兵，于是从 `COLUMN_SPEC` 推导即可：
    这样「表头名 ↔ 字段」的分配**只有一份真相**，改 `COLUMN_SPEC` 别名跟着改，不会两份漂。

    推导规则（逐位对应，见设计 §4.1 的表）：
      第2项 表头       → label（下拉显示）+ 别名元组 (表头,)
      第3项 字段名     → 字段key
      第4/5项 可写可读 → 方向（`_DIRECTION` 反查）
      字段名 == ACCOUNT_KEY_FIELD[platform] → 是否定位键
      空值跳过回写恒 False（COLUMN_SPEC 没有这个语义）
    """
    key_field = ACCOUNT_KEY_FIELD[platform]
    out = []
    for _col, header, field, writable, readable in COLUMN_SPEC[platform]:
        if field is None:
            continue
        d = next(k for k, v in _DIRECTION.items()
                 if v == (bool(writable), bool(readable)))
        out.append((field, header, (header,), d, field == key_field, False))
    return out


# 字段目录：按平台一份。tt 手写、fb 从 COLUMN_SPEC 推导（设计 §4.1）。
FIELD_CATALOG = {"tt": TT_FIELD_CATALOG, "fb": _derive_catalog("fb")}
```

> 若 `COLUMN_SPEC` 里出现 `(False, False)` 的非空字段，`next(...)` 会 `StopIteration` ——
> 这是**故意的**：那种列既不可写也不可读，本来就不该进目录，应当当场炸而不是静默漏掉。

- [ ] **Step 3c: 改 `field_spec`**

把 `field_spec`（`py/huguan_dashboard.py`）整个换成：

```python
def field_spec(platform: str) -> dict:
    """字段key → {writable, readable, key, skip_empty_write}。

    tt / fb 来自 `FIELD_CATALOG`（tt 手写、fb 由 `COLUMN_SPEC` 推导）；
    gg 由既有 `COLUMN_SPEC` 推导（保证行为逐字不变）。
    `key` 对 gg 恒为 `ACCOUNT_KEY_FIELD` 那个字段名。
    """
    catalog = FIELD_CATALOG.get(platform)
    if catalog is not None:
        spec = {}
        for f, _l, _a, d, is_key, skip in catalog:
            # 「认识但刻意不采集」的哨兵（空串字段key，如 tt 的「位置」）不是字段。
            # **必须在查 _DIRECTION 之前跳过** —— 它的方向是 "ignore"，不在那张表里。
            if not f:
                continue
            writable, readable = _DIRECTION[d]
            spec[f] = {"writable": writable, "readable": readable,
                       "key": is_key, "skip_empty_write": skip}
        return spec
    key_field = ACCOUNT_KEY_FIELD[platform]
    for _col, _header, field, writable, readable in COLUMN_SPEC[platform]:
        if field is None:
            continue
        spec[field] = {"writable": writable, "readable": readable,
                       "key": field == key_field, "skip_empty_write": False}
    return spec
```

> 注意 `spec = {}` 现在必须**在 if 分支里**初始化（原来是函数开头统一初始化后 `return spec`）。

- [ ] **Step 4: 跑测试确认通过**

Run: `cd py && python -m pytest tests/test_huguan_dashboard.py -q -k TestFieldCatalogPerPlatform`
Expected: PASS（5 passed）

- [ ] **Step 5: 全量回归**

Run: `cd py && python -m pytest tests/ -q`
Expected: PASS。**这是「TT 与 GG 行为未变」的第一道证据** —— 目录改道后既有测试一条都不许变红。

- [ ] **Step 6: 提交**

```bash
git add py/huguan_dashboard.py py/tests/test_huguan_dashboard.py
git commit -m "feat(fb-header-mapping): 字段目录按平台归一，FB 目录从 COLUMN_SPEC 推导" -- py/huguan_dashboard.py py/tests/test_huguan_dashboard.py
```

---

## Task 2: `resolve_column_map` / `describe_header_columns` 接 `platform`

**Files:**
- Modify: `py/huguan_dashboard.py`（`_TT_ALIAS_TO_FIELD`、`resolve_column_map`、`describe_header_columns`、`resolve_table_col_map` 的调用）
- Modify: `py/routes/huguan_dashboard_routes.py`（两处调用）
- Modify: `py/tests/test_huguan_dashboard.py`（约 31 处）、`py/tests/test_huguan_sheet_write.py`（1 处）、`py/tests/test_huguan_undo.py`（1 处）

**Interfaces:**
- Consumes: `FIELD_CATALOG`（Task 1）
- Produces: `resolve_column_map(headers, overrides, platform) -> (dict, list)`；`describe_header_columns(headers, overrides, col_map, unmatched, platform) -> list`；`_ALIAS_TO_FIELD: dict[str, dict[str, str]]`

- [ ] **Step 1: 写失败的测试（等价性锚）**

在 `py/tests/test_huguan_dashboard.py` 的 `TestFieldCatalogPerPlatform` 类之后追加：

```python
class TestFbHeaderMappingAnchor:
    """FB 表头映射的等价性锚（设计 §六 锚 1）。

    FB 表头正常时，按表头名解析的结果必须与老的「按列字母」合成结果**逐字节相同**。
    这条锚是「改造没有改变正常表的行为」的唯一证据。
    """

    FB_STD_HEADER = [c[1] for c in hd.COLUMN_SPEC["fb"]]   # 17 个中文表头，顺序即 A..Q

    def test_fb_standard_header_reproduces_legacy_column_map(self):
        col_map, unmatched = hd.resolve_column_map(self.FB_STD_HEADER, {}, "fb")
        assert col_map == hd.spec_column_map("fb")
        assert unmatched == []

    def test_fb_standard_header_maps_every_column_in_order(self):
        """逐列钉字面值：列字母必须与原固定规格一模一样。"""
        col_map, _u = hd.resolve_column_map(self.FB_STD_HEADER, {}, "fb")
        assert [col_map.get(f) for f in
                ("acquired_date", "operator", "name", "account_id", "channel_name",
                 "asset_type_name", "unit_price", "inbound_qty", "acceptor",
                 "owner_name", "outbound_date", "outbound_qty", "timezone",
                 "consumption", "status_name", "primary_bm_name", "remark")] \
            == list("ABCDEFGHIJKLMNOPQ")

    def test_fb_reordered_header_follows_names(self):
        """换序：映射跟着表头走（老实现按列字母读会静默串列）。"""
        headers = list(reversed(self.FB_STD_HEADER))
        col_map, unmatched = hd.resolve_column_map(headers, {}, "fb")
        assert unmatched == []
        assert col_map["acquired_date"] == "Q"
        assert col_map["remark"] == "A"
        assert col_map["account_id"] == "N"

    def test_fb_unknown_header_is_reported_not_mapped(self):
        """插一列不认识的：它进未采集，其余列不受影响。"""
        headers = self.FB_STD_HEADER[:5] + ["临时备注"] + self.FB_STD_HEADER[5:]
        col_map, unmatched = hd.resolve_column_map(headers, {}, "fb")
        assert unmatched == ["临时备注"]
        assert col_map["asset_type_name"] == "G"     # 原 F 列被挤到 G
        assert set(col_map) == {f for f in hd.spec_column_map("fb")}

    def test_fb_override_wins_over_alias(self):
        col_map, unmatched = hd.resolve_column_map(
            self.FB_STD_HEADER, {"时区": "consumption"}, "fb")
        assert col_map["consumption"] == "M"          # 时区列（M）被改指派给消耗
        assert "timezone" not in col_map              # 消耗列（N）落选
        assert unmatched == ["消耗"]

    def test_fb_override_empty_string_means_deliberately_skipped(self):
        col_map, unmatched = hd.resolve_column_map(self.FB_STD_HEADER, {"时区": ""}, "fb")
        assert "timezone" not in col_map
        assert unmatched == []

    def test_resolve_column_map_requires_platform(self):
        """platform 无默认值：漏传必须当场 TypeError，不许静默按 TT 处理。"""
        import pytest
        with pytest.raises(TypeError):
            hd.resolve_column_map(self.FB_STD_HEADER, {})

    def test_tt_standard_header_unchanged(self):
        """TT 的表头行仍解析成同一份 col_map（走同一函数、不同目录）。"""
        tt_header = [c[1] for c in hd.COLUMN_SPEC["tt"]]
        col_map, unmatched = hd.resolve_column_map(tt_header, {}, "tt")
        assert unmatched == []
        assert col_map["advertiser_id"] == "C"
        assert col_map["remark"] == "M"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd py && python -m pytest tests/test_huguan_dashboard.py -q -k TestFbHeaderMappingAnchor`
Expected: FAIL —— `TypeError: resolve_column_map() takes 2 positional arguments but 3 were given`

- [ ] **Step 3a: 别名表按平台**

把 `py/huguan_dashboard.py` 里的

```python
# 别名 → 字段key（同名字段只取最先出现的那个别名条目）
_TT_ALIAS_TO_FIELD = {}
for _f, _label, _aliases, _dir, _key, _skip in TT_FIELD_CATALOG:
    for _a in _aliases:
        _TT_ALIAS_TO_FIELD.setdefault(_a, _f)
```

整段**删除**，改放到 `FIELD_CATALOG` 定义之后：

```python
# 别名 → 字段key，按平台一份（同名字段只取最先出现的那个别名条目）。
# 放在这里而不是目录定义旁边，是因为它按 FIELD_CATALOG 逐平台展开。
_ALIAS_TO_FIELD = {}
for _p, _catalog in FIELD_CATALOG.items():
    _alias = {}
    for _f, _label, _aliases, _dir, _key, _skip in _catalog:
        for _a in _aliases:
            _alias.setdefault(_a, _f)
    _ALIAS_TO_FIELD[_p] = _alias
```

- [ ] **Step 3b: `resolve_column_map` 接 platform**

签名与开头两行改动（其余逐字不动）：

```python
def resolve_column_map(headers: list, overrides: dict, platform: str) -> tuple:
    """表头行 + 手工覆盖 → ({字段key: 列字母}, [未采集的表头名])。

    优先级：**手工覆盖 > 别名自动匹配 > 不采集**（设计 §4.2）。
    字段目录与别名表按 `platform` 取（tt 手写 / fb 由 COLUMN_SPEC 推导，见 FIELD_CATALOG）。
    **`platform` 刻意没有默认值** —— 漏传要当场 TypeError，绝不静默按 tt 处理。

    其余口径见下（与 TT 单平台时逐字相同）：
    - 表头文本 strip() 后匹配；空表头跳过。
    - 多列命中同一字段 ⇒ 取**最左**那列。……
    """
    catalog = FIELD_CATALOG[platform]
    alias_map = _ALIAS_TO_FIELD[platform]
    # 只把**真正的字段**当合法覆盖目标：空串字段key 是「认识但刻意不采集」的哨兵
    catalog_fields = {f for f, _l, _a, _d, _k, _s in catalog if f}
```

然后把函数体里唯一一处 `_TT_ALIAS_TO_FIELD.get(name)` 改成 `alias_map.get(name)`。

- [ ] **Step 3c: `describe_header_columns` 接 platform**

```python
def describe_header_columns(headers: list, overrides: dict,
                            col_map: dict, unmatched: list, platform: str) -> list:
```

函数体内那行 `alias_map, alias_unmatched = resolve_column_map(headers, {})`
改成 `resolve_column_map(headers, {}, platform)`。
（docstring 里补一句：`platform` 只是转交给 `resolve_column_map`。）

- [ ] **Step 3d: 改生产调用点**

- `py/huguan_dashboard.py` 的 `resolve_table_col_map` 内：
  `col_map, _unmatched = resolve_column_map(headers, overrides or {})`
  → `resolve_column_map(headers, overrides or {}, platform)`
- `py/routes/huguan_dashboard_routes.py` 的 `dashboard_sync`：
  `hd.resolve_column_map(headers, t.get("columns") or {})`
  → 末尾补 `, platform`
- `py/routes/huguan_dashboard_routes.py` 的 `dashboard_sheet_headers`：
  `hd.resolve_column_map(headers, overrides)` → 补 `, platform`
  `hd.describe_header_columns(headers, overrides, col_map, unmatched)` → 补 `, platform`

- [ ] **Step 3e: 改测试调用点（机械）**

Run: `grep -rn "resolve_column_map(\|describe_header_columns(" py/tests/`

对**每一个**命中：`resolve_column_map(X, Y)` → `resolve_column_map(X, Y, "tt")`；
`describe_header_columns(...)` 末位补 `"tt"`。
（这些测试全部是 TT 的；加 `"tt"` 表示「按 TT 解析」，断言一个字都不改。）

同一个 grep 里出现 `hd.resolve_column_map` 的位置也要一并处理。

- [ ] **Step 4: 跑测试确认通过**

Run: `cd py && python -m pytest tests/test_huguan_dashboard.py -q -k TestFbHeaderMappingAnchor`
Expected: PASS（8 passed）

- [ ] **Step 5: 全量回归**

Run: `cd py && python -m pytest tests/ -q`
Expected: PASS。**第二道证据**：签名改完、调用点全改完，TT/GG 既有测试仍全绿。

- [ ] **Step 6: 提交**

```bash
git add py/huguan_dashboard.py py/routes/huguan_dashboard_routes.py py/tests/test_huguan_dashboard.py py/tests/test_huguan_sheet_write.py py/tests/test_huguan_undo.py
git commit -m "feat(fb-header-mapping): 表头解析器接 platform，FB 表头映射跑通（含等价性锚）" -- py/huguan_dashboard.py py/routes/huguan_dashboard_routes.py py/tests/test_huguan_dashboard.py py/tests/test_huguan_sheet_write.py py/tests/test_huguan_undo.py
```

---

## Task 3: 字段目录暴露改名 —— `field_catalog(platform)` / `_catalog_fields(platform)`

**Files:**
- Modify: `py/huguan_dashboard.py`（`tt_field_catalog`、`_TT_CATALOG_FIELDS`）
- Modify: `py/routes/huguan_dashboard_routes.py`（2 处）
- Modify: `py/tests/test_huguan_dashboard.py`（6 处）

**Interfaces:**
- Consumes: `FIELD_CATALOG`、`field_spec`（Task 1）
- Produces: `field_catalog(platform) -> list[dict]`（每项含 `key` / `label` / `direction` / `writable` / `readable` / `key_col`）；`_catalog_fields(platform) -> set[str]`

- [ ] **Step 1: 写失败的测试**

追加到 `py/tests/test_huguan_dashboard.py`：

```python
class TestFieldCatalogExposure:
    """目录暴露按平台（设计 §4.7）。"""

    def test_fb_catalog_has_17_real_fields(self):
        cat = hd.field_catalog("fb")
        assert len(cat) == 17
        by_key = {c["key"]: c for c in cat}
        assert by_key["operator"]["direction"] == "w"
        assert by_key["operator"]["writable"] is True
        assert by_key["operator"]["readable"] is False
        assert by_key["acceptor"]["direction"] == "r"
        assert by_key["account_id"]["key_col"] is True
        assert by_key["remark"]["label"] == "产品信息"
        assert by_key["channel_name"]["label"] == "所属渠道"

    def test_tt_catalog_unchanged(self):
        """TT 的目录（含哨兵剔除）逐项不变。"""
        cat = hd.field_catalog("tt")
        keys = [c["key"] for c in cat]
        assert "位置" not in keys and "" not in keys
        assert {c["key"]: c["label"] for c in cat}["advertiser_id"] == "账户ID"

    def test_catalog_fields_are_the_post_whitelist(self):
        """白名单与目录同源：能选的必能存。"""
        for p in ("tt", "fb"):
            assert hd._catalog_fields(p) == {c["key"] for c in hd.field_catalog(p)}
        assert "" not in hd._catalog_fields("tt")
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd py && python -m pytest tests/test_huguan_dashboard.py -q -k TestFieldCatalogExposure`
Expected: FAIL —— `AttributeError: module 'huguan_dashboard' has no attribute 'field_catalog'`

- [ ] **Step 3a: 改 `py/huguan_dashboard.py`**

`tt_field_catalog` 整个函数替换为：

```python
def field_catalog(platform: str) -> list:
    """字段目录（供前端「列映射」下拉）：只含**真正的字段**，排除空串哨兵。

    与 POST 校验**同源**（都出自 `FIELD_CATALOG` / `field_spec(platform)`）—— 否则会出现
    「下拉里能选、保存时被 400 拒」这种漂移。`key_col` 给前端把定位键标成必选；
    `direction == "r"` 的标「只读回」、`"w"` 的标「只写」（fb 的「操作人」）。
    """
    spec = field_spec(platform)
    return [{"key": f, "label": label, "direction": d,
             "writable": spec[f]["writable"], "readable": spec[f]["readable"],
             "key_col": spec[f]["key"]}
            for f, label, _aliases, d, _key, _skip in FIELD_CATALOG[platform] if f]
```

把 `_TT_CATALOG_FIELDS = set(field_spec("tt"))` 那段（含上方注释）替换为：

```python
# 合法的**可手工覆盖字段**集合，供 POST 层校验 `tables[].columns`（设计 §4.2）。
# 必须与 `resolve_column_map` 认定的可覆盖目标**同一口径** —— 后者用
# `{f for f, ... in FIELD_CATALOG[platform] if f}`（剔掉空串哨兵）。若直接取整个目录，
# 就会把「认识但刻意不采集」的空串哨兵（tt 的中文名「位置」）**当成一个字段**混进来：
# 用户把某列覆盖成这个字段会被放行，而 `resolve_column_map` 里根本没有这个字段可认
# —— 两边对「什么是字段」打架。故取 `field_spec(platform)` 这个**终裁字段集**。
def _catalog_fields(platform: str) -> set:
    return set(field_spec(platform))
```

- [ ] **Step 3b: 改调用点**

Run: `grep -rn "tt_field_catalog\|_TT_CATALOG_FIELDS" py frontend/src frontend/tests`

- `py/routes/huguan_dashboard_routes.py`：`hd.tt_field_catalog()` → `hd.field_catalog(platform)`（Task 8 会再改这里的平台取法，本步先保持一致）
- `py/routes/huguan_dashboard_routes.py`：`hd._TT_CATALOG_FIELDS` → `hd._catalog_fields(platform)`
- `py/tests/test_huguan_dashboard.py`：6 处 `hd.tt_field_catalog()` → `hd.field_catalog("tt")`
- `frontend/src/components/HuguanDashboardCard.vue` 里有两处注释提到 `tt_field_catalog`（`:1209`），**改成 `tt_field_catalog / fb_field_catalog`**（真正的取值改法在 Task 9）；`frontend/tests/columnMappingLogic.test.mjs` 若只是注释则同样只改注释。

- [ ] **Step 4: 跑测试确认通过**

Run: `cd py && python -m pytest tests/test_huguan_dashboard.py -q -k TestFieldCatalogExposure`
Expected: PASS（3 passed）

- [ ] **Step 5: 全量回归**

Run: `cd py && python -m pytest tests/ -q`
Expected: PASS

- [ ] **Step 6: 提交**

```bash
git add py/huguan_dashboard.py py/routes/huguan_dashboard_routes.py py/tests/test_huguan_dashboard.py frontend/src/components/HuguanDashboardCard.vue
git commit -m "refactor(fb-header-mapping): 字段目录暴露按平台（field_catalog / _catalog_fields）" -- py/huguan_dashboard.py py/routes/huguan_dashboard_routes.py py/tests/test_huguan_dashboard.py frontend/src/components/HuguanDashboardCard.vue
```

---

## Task 4: 读路径 —— FB 读 `A:ZZ`、同步放行 fb、错误文案按平台

**Files:**
- Modify: `py/huguan_dashboard.py`（`READ_RANGE`、`KEY_COL_LABEL`、`resolve_table_col_map` 的错误文案）
- Modify: `py/routes/huguan_dashboard_routes.py`（`dashboard_sync` 的表头解析分支 + 错误文案）
- Test: `py/tests/test_huguan_dashboard.py`、`py/tests/test_fb_huguan_dashboard.py`

**Interfaces:**
- Consumes: `resolve_column_map(..., platform)`（Task 2）
- Produces: `READ_RANGE["fb"] == "A:ZZ"`；`KEY_COL_LABEL: dict[str, str]`

- [ ] **Step 1: 写失败的测试**

在 `py/tests/test_huguan_dashboard.py` 追加：

```python
class TestFbSyncReadPath:
    """FB 读路径（设计 §4.4）。"""

    def test_fb_read_range_is_wide(self):
        assert hd.READ_RANGE["fb"] == "A:ZZ", "表头映射后列数不定，固定 A:Q 会读漏右侧列"
        assert hd.READ_RANGE["gg"] == "A:N", "gg 逐字节不变"

    def test_key_col_label_speaks_the_users_language(self):
        """错误文案里的列名必须与户管表里的表头一致 —— 他拿这句去找列。"""
        assert hd.KEY_COL_LABEL["fb"] == "资产UID"
        assert hd.KEY_COL_LABEL["tt"] == "账户ID"
        assert hd.KEY_COL_LABEL["gg"] == "账户ID"

    def test_missing_key_column_message_names_asset_uid(self, monkeypatch):
        """FB 表里没有「资产UID」⇒ 拒绝写表，且文案说「资产UID」不是「账户ID」。

        打桩 `read_sheet_values`（它就在 `huguan_dashboard` 模块里，直接 patch 模块属性），
        免得 `service=object()` 去碰真实网络。"""
        import pytest
        headers = [c[1] for c in hd.COLUMN_SPEC["fb"] if c[2] != "account_id"]
        monkeypatch.setattr(hd, "read_sheet_values", lambda *a, **k: [headers])
        with pytest.raises(ValueError) as ei:
            hd.resolve_table_col_map(object(), "SS", "账户管理分配", "fb", {})
        assert "资产UID" in str(ei.value)
        assert "账户ID" not in str(ei.value)
```

在 `py/tests/test_fb_huguan_dashboard.py` 里找到 `assert hd.READ_RANGE["fb"] == "A:Q"`（约 `:60`）改成：

```python
        assert hd.READ_RANGE["fb"] == "A:ZZ"   # 表头映射后列数不定（2026-10-11 设计 §4.4）
```

同一文件 `:58`/`:59` 的 `KEY_COL["fb"] == "D"` / `OWNER_COL["fb"] == "J"` **保持不变**
（它们是写表器的兜底常量，仍存在）。

- [ ] **Step 2: 跑测试确认失败**

Run: `cd py && python -m pytest tests/test_huguan_dashboard.py -q -k TestFbSyncReadPath`
Expected: FAIL —— `AttributeError: module 'huguan_dashboard' has no attribute 'KEY_COL_LABEL'`

- [ ] **Step 3a: `py/huguan_dashboard.py`**

`READ_RANGE` 改成 `{"gg": "A:N", "tt": "A:ZZ", "fb": "A:ZZ"}`，注释改成：

```python
# tt / fb 读 A:ZZ：表头映射后列数不定（户管每加一张表表头都不同，且「认识但刻意不采集」
# 的列也占位），固定范围会读漏右侧列。gg 仍走固定 A:N（逐字节不变）。
READ_RANGE = {"gg": "A:N", "tt": "A:ZZ", "fb": "A:ZZ"}
# 「账户ID」列在各平台表里的**表头名** —— 只用于错误文案。户管是拿这句话去自己的表里
# 找那一列的，说错名字他就找不到（FB 那张表的表头是「资产UID」，不是「账户ID」）。
KEY_COL_LABEL = {"gg": "账户ID", "tt": "账户ID", "fb": "资产UID"}
```

`resolve_table_col_map` 里 `raise ValueError(f"工作表「{sheet_name}」里找不到「账户ID」列，无法写表")`
改成 `f"工作表「{sheet_name}」里找不到「{KEY_COL_LABEL[platform]}」列，无法写表"`。
（该函数此时仍只服务 tt —— 放行 fb 是 Task 5 的事；先统一文案口径。）

- [ ] **Step 3b: `py/routes/huguan_dashboard_routes.py` 的 `dashboard_sync`**

把 `:234-248` 那段的平台判断与文案改成：

```python
            # tt / fb 改按**表头名**解析列（户管每加一张表表头都不同，固定列字母会静默串列）；
            # gg 仍走合成 map（`col_map=None` ⇒ `COLUMN_SPEC` 固定列，逐字节不变）。
            col_map = None
            if platform in ("tt", "fb"):
                headers = grid[0] if grid else []
                col_map, unmatched = hd.resolve_column_map(
                    headers, t.get("columns") or {}, platform)
                # 定位键认不出 ⇒ 整批拒同步（设计 §4.3 第 2 条）：没有定位键列，
                # 读出来的每一行都无法与系统里的账户对应，继续跑只会产出垃圾差异。
                if not (col_map.get("advertiser_id") or col_map.get("account_id")):
                    return err(f"工作表「{t['sheet_name']}」里找不到"
                               f"「{hd.KEY_COL_LABEL[platform]}」列，无法同步")
                if unmatched:
                    unmatched_columns.append({"sheet": t["sheet_name"],
                                              "headers": unmatched})
                sheet_col_maps.setdefault(t["sheet_name"], col_map)
            table_grids.append((t, grid, col_map))
```

同一文件的 phase 2（`:254-266`）里 `if platform == "tt": parsed["_account_type"] = t["name"]`
**不动**（FB 本轮没有户类型）。

- [ ] **Step 4: 跑测试确认通过**

Run: `cd py && python -m pytest tests/test_huguan_dashboard.py tests/test_fb_huguan_dashboard.py -q`
Expected: PASS

- [ ] **Step 5: 全量回归**

Run: `cd py && python -m pytest tests/ -q`
Expected: PASS

- [ ] **Step 6: 提交**

```bash
git add py/huguan_dashboard.py py/routes/huguan_dashboard_routes.py py/tests/test_huguan_dashboard.py py/tests/test_fb_huguan_dashboard.py
git commit -m "feat(fb-header-mapping): FB 读路径改按表头解析（A:ZZ + 定位键校验 + 文案按平台）" -- py/huguan_dashboard.py py/routes/huguan_dashboard_routes.py py/tests/test_huguan_dashboard.py py/tests/test_fb_huguan_dashboard.py
```

---

## Task 5: 写路径（一）—— `resolve_table_col_map` 放行 fb + `parse_row` 去掉列字母兜底

**Files:**
- Modify: `py/huguan_dashboard.py`（`resolve_table_col_map`、`parse_row`）
- Test: `py/tests/test_huguan_dashboard.py`、`py/tests/test_huguan_sheet_write.py`

**Interfaces:**
- Consumes: `key_col_of_col_map(col_map, platform)`（既有）、`KEY_COL_LABEL`（Task 4）
- Produces: `resolve_table_col_map` 对 fb 也读表头；`parse_row` 在 col_map 缺定位键时抛 `ValueError`

- [ ] **Step 1: 写失败的测试**

在 `py/tests/test_huguan_dashboard.py` 追加：

```python
class TestFbWritePathColMap:
    """FB 写路径按表解析 col_map（设计 §4.5）。"""

    def test_resolve_table_col_map_reads_header_for_fb(self, monkeypatch):
        """fb 不再返回固定合成 map，而是读表头行后解析。"""
        headers = list(reversed([c[1] for c in hd.COLUMN_SPEC["fb"]]))
        monkeypatch.setattr(hd, "read_sheet_values", lambda *a, **k: [headers])
        cm = hd.resolve_table_col_map(object(), "SS", "账户管理分配", "fb", {})
        assert cm["account_id"] == "N"          # 表头反排 ⇒ 资产UID 落到 N
        assert cm["acquired_date"] == "Q"

    def test_resolve_table_col_map_gg_untouched(self):
        """gg 仍是零额外读的合成 map（逐字节不变）。"""
        assert hd.resolve_table_col_map(object(), "SS", "看板", "gg", {}) \
            == hd.spec_column_map("gg")

    def test_parse_row_never_falls_back_to_fixed_key_column(self, monkeypatch):
        """col_map 里没有定位键 ⇒ 抛错，**绝不**静默用 KEY_COL["fb"]（D 列）。"""
        import pytest
        cm = {f: c for f, c in hd.spec_column_map("fb").items() if f != "account_id"}
        with pytest.raises(ValueError):
            hd.parse_row(["x"] * 17, "fb", cm)

    def test_parse_row_follows_reordered_header(self):
        """换序后 parse_row 读到的字段值跟着列走。"""
        headers = list(reversed([c[1] for c in hd.COLUMN_SPEC["fb"]]))
        cm, _u = hd.resolve_column_map(headers, {}, "fb")
        values = [""] * 17
        values[hd.col_index(cm["timezone"])] = "UTC+8"
        values[hd.col_index(cm["account_id"])] = "1234567890"
        row = hd.parse_row(values, "fb", cm)
        assert row["timezone"] == "UTC+8"
        assert row["account_id"] == "1234567890"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd py && python -m pytest tests/test_huguan_dashboard.py -q -k TestFbWritePathColMap`
Expected: FAIL —— `test_resolve_table_col_map_reads_header_for_fb` 拿到的是合成 map（`account_id == "D"`），`test_parse_row_never_falls_back...` 不抛错。

- [ ] **Step 3a: `resolve_table_col_map` 放行 fb**

```python
def resolve_table_col_map(service, spreadsheet_id: str, sheet_name: str,
                          platform: str, overrides: dict | None = None) -> dict:
    """写表前解析**这张表**的 col_map（tt / fb 读一次表头行）。

    - gg：直接返回 `spec_column_map("gg")`，**零额外读**，行为与改动前逐字节相同。
    - tt / fb：读一次表头行（`A1:ZZ1`）再 `resolve_column_map`。表头顺序与固定列规格不同
      （户管每加一张表表头都不同）⇒ 固定列字母会静默串列，必须按表头定位。
    - 定位键解析不到时**抛错** —— 绝不退回任何默认列：那会让整批静默写到错行
      （读路径同样拒同步，两侧口径一致）。

    `overrides` 是该表的手工覆盖 `{表头名: 字段key}`，必须与读路径
    （`dashboard_sync` 的 `t.get("columns")`）**同源** —— 否则同一次同步里读与写
    对「哪一列是定位键」的认识不一致，写就会落到错行。
    """
    if platform == "gg":
        return spec_column_map(platform)
    grid = read_sheet_values(service, spreadsheet_id, sheet_name, "A1:ZZ1")
    headers = grid[0] if grid else []
    col_map, _unmatched = resolve_column_map(headers, overrides or {}, platform)
    if not (col_map.get(ACCOUNT_KEY_FIELD[platform]) or col_map.get(TT_KEY_FIELD)):
        raise ValueError(
            f"工作表「{sheet_name}」里找不到「{KEY_COL_LABEL[platform]}」列，无法写表")
    return col_map
```

- [ ] **Step 3b: `parse_row` 去掉列字母兜底**

把 `parse_row` 末尾那三行

```python
    key_col = cm.get(TT_KEY_FIELD) or cm.get(ACCOUNT_KEY_FIELD[platform]) \
        or KEY_COL[platform]
    key_i = col_index(key_col)
```

改成

```python
    # **不再有列字母兜底**（设计 §4.8）：col_map 里没有定位键 ⇒ 抛错，绝不静默落到
    # KEY_COL[platform]（fb 是 D 列）—— 那正是「表头一挪就写错行」的入口。
    # 路由的前置校验已先拦一道，这里是纵深防御（gg 走 spec_column_map 恒有定位键，抛不出来）。
    # 顺带复用 key_col_of_col_map：定位键在 tt 有两个命名空间（advertiser_id / account_id），
    # 自己再写一遍 `or` 迟早漏一个。
    key_col = key_col_of_col_map(cm, platform)
    key_i = col_index(key_col)
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd py && python -m pytest tests/test_huguan_dashboard.py tests/test_huguan_sheet_write.py -q`
Expected: PASS

- [ ] **Step 5: 全量回归**

Run: `cd py && python -m pytest tests/ -q`
Expected: PASS

- [ ] **Step 6: 提交**

```bash
git add py/huguan_dashboard.py py/tests/test_huguan_dashboard.py py/tests/test_huguan_sheet_write.py
git commit -m "feat(fb-header-mapping): 写路径按表解析 col_map，定位键不再有列字母兜底" -- py/huguan_dashboard.py py/tests/test_huguan_dashboard.py py/tests/test_huguan_sheet_write.py
```

---

## Task 6: 写路径（二）—— 五处硬编码列字母改按 col_map

**Files:**
- Modify: `py/huguan_dashboard.py`（`_fb_acceptor_cells`）
- Modify: `py/routes/huguan_sheet_targets.py`（`:183` 角色列、`:298-326` fb acceptor target）
- Modify: `py/routes/huguan_dashboard_routes.py`（`:405-408` 的 `{"I": ...}`）
- Test: `py/tests/test_fb_huguan_dashboard.py`、`py/tests/test_huguan_sheet_write.py`

**Interfaces:**
- Consumes: `resolve_table_col_map`、`owner_role_col(platform, role, col_map)`、`key_col_of_col_map`
- Produces: `_fb_acceptor_cells(rows, value, col)` —— **第三个参数是必填的列字母**（旧的二元调用会 TypeError）

- [ ] **Step 1: 写失败的测试**

在 `py/tests/test_fb_huguan_dashboard.py` 追加（该文件已有 FB 的 app/client 夹具可直接用）：

```python
class TestFbAcceptorColumnFollowsHeader:
    """「接户运营」列挪位后，写表器必须写到**挪过去的那一列**（设计 §4.5）。"""

    def test_fb_acceptor_cells_takes_explicit_column(self):
        rows = hd._fb_acceptor_cells([{"account_id": "7"}], "张三转李四", "X")
        assert rows == [{"account_id": "7", "cells": {"X": "张三转李四"}}]

    def test_fb_acceptor_cells_requires_column(self):
        import pytest
        with pytest.raises(TypeError):
            hd._fb_acceptor_cells([{"account_id": "7"}], "张三转李四")
```

在 `py/tests/test_huguan_sheet_write.py` 追加（同文件已有 `resolve_table_col_map` 的桩写法可参考）：

```python
class TestFbOwnerColumnFollowsHeader:
    """「在用运营」列挪位后，归属回写仍落到正确的列。"""

    def test_owner_role_col_resolves_from_col_map_for_fb(self):
        cm = {f: c for f, c in hd.spec_column_map("fb").items()}
        cm["owner_name"] = "Z"                     # 模拟表头变了 ⇒ 运营列在 Z
        assert hd.owner_role_col("fb", "owner", cm) == "Z"

    def test_owner_role_col_returns_none_when_column_not_collected(self):
        cm = {f: c for f, c in hd.spec_column_map("fb").items()}
        del cm["owner_name"]
        assert hd.owner_role_col("fb", "owner", cm) is None   # 一个字不碰
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd py && python -m pytest tests/test_fb_huguan_dashboard.py -q -k TestFbAcceptorColumnFollowsHeader`
Expected: FAIL —— `TypeError: _fb_acceptor_cells() takes 2 positional arguments but 3 were given`

- [ ] **Step 3a: `_fb_acceptor_cells` 加列参数**

```python
def _fb_acceptor_cells(rows: list, value: str, col: str) -> list:
    """构造只写「接户运营」列的 rows（列字母由调用方按该表 col_map 传入）。

    **`col` 必填、无默认值** —— 表头映射后这一列不在固定位置，给个默认 "I" 就是
    留一个「表头一挪就写错列」的入口。

    刻意只含这一列 —— 与 `owner_channel_cells` 同一理由：收尾写入若顺手带上别的列，
    就会把户管在表里的其他手工改动一起冲掉。
    """
    return [{"account_id": r["account_id"], "cells": {col: value}} for r in rows]
```

- [ ] **Step 3b: `huguan_sheet_targets.py` 的 fb acceptor target 按表解析**

`huguan_fb_acceptor_sync` 里 `db` 块与写表块改成：

```python
    db = database.get_db()
    try:
        spreadsheet_id = hd.get_platform_config(db, user_id, platform)["spreadsheet_id"]
        if not spreadsheet_id:
            raise RuntimeError("该看板未配置表格 ID")
        table = _resolve_account_table(db, user_id, platform, account_id)
        if not table or not table["sheet_name"]:
            raise RuntimeError("查不到该看板的工作表")
        sheet_name = table["sheet_name"]
        columns = table.get("columns") or {}
    finally:
        db.close()

    service = gs.build_service(_GOOGLE_SHEETS_CONFIG["credentials_path"])
    # 写表前按**该表**表头解析 col_map（与 `huguan_owner_channel_sync` 同法）。表头映射后
    # 「接户运营」列不在固定位置，定位键列同理 —— 写死 I / D 就是把换绑记录和整行写错位。
    cm = hd.resolve_table_col_map(service, spreadsheet_id, sheet_name, platform, columns)
    col = cm.get("acceptor")
    if col is None:
        # 该表没有「接户运营」列（未采集）⇒ 一个字不碰（与 owner_role_col 同口径）
        return
    rows = hd._fb_acceptor_cells([{"account_id": account_id}], note, col)
    gs.update_rows_by_account_id(service, spreadsheet_id, sheet_name, rows,
                                 key_col=hd.key_col_of_col_map(cm, platform))
```

把函数 docstring 里「走 `_resolve_sheet_name` 会命中那个唯一的空名条目」那段删掉，改成说明它现在也解析 col_map。

- [ ] **Step 3c: `huguan_sheet_targets.py:183` 的角色列**

```python
    # 角色列必须与写表器用**同一份** col_map 定位（tt / fb 的表头顺序都可能与固定规格不同）。
    # gg 仍传 None 走既有固定字母路径（含它的既有抛错口径，逐字节不变）。
    col = hd.owner_role_col(platform, role, cm if platform in ("tt", "fb") else None)
```

- [ ] **Step 3d: `huguan_dashboard_routes.py:401-408` 的 `{"I": ...}`**

```python
            if platform == "fb":
                # FB 没有通道列可清；改为把换绑记录定向写进「接户运营」列。
                # 列字母按**该账户那张表**的 col_map 取（表头映射后不在固定 I 列）；
                # 每行的串不同，所以不能用 _fb_acceptor_cells（它写同一个串）。
                rows = []
                for r in applied:
                    cm = col_map_by_account.get(r["account_id"])
                    col = (cm or {}).get("acceptor")
                    if col is None:
                        continue                   # 未采集 ⇒ 一个字不碰
                    rows.append({"account_id": r["account_id"],
                                 "cells": {col: hd._fb_owner_transition(
                                     r.get("from", ""), r["to"])}})
                if rows:
                    _write_background_tables(db, uid, platform, rows, col_map_by_account)
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd py && python -m pytest tests/test_fb_huguan_dashboard.py tests/test_huguan_sheet_write.py tests/test_huguan_undo.py -q`
Expected: PASS

- [ ] **Step 5: 全量回归**

Run: `cd py && python -m pytest tests/ -q`
Expected: PASS

- [ ] **Step 6: 提交**

```bash
git add py/huguan_dashboard.py py/routes/huguan_sheet_targets.py py/routes/huguan_dashboard_routes.py py/tests/test_fb_huguan_dashboard.py py/tests/test_huguan_sheet_write.py
git commit -m "feat(fb-header-mapping): 写表目标的角色列/定位键列按 col_map，去掉五处硬编码字母" -- py/huguan_dashboard.py py/routes/huguan_sheet_targets.py py/routes/huguan_dashboard_routes.py py/tests/test_fb_huguan_dashboard.py py/tests/test_huguan_sheet_write.py
```

---

## Task 7: 配置形态 —— FB 带 `columns`（读 + 写 + 校验）

**Files:**
- Modify: `py/huguan_dashboard.py`（`get_platform_tables`、`save_config`）
- Modify: `py/routes/huguan_dashboard_routes.py`（POST 的 `columns` 校验放行 fb）
- Test: `py/tests/test_huguan_dashboard.py`、`py/tests/test_fb_huguan_dashboard.py`

**Interfaces:**
- Consumes: `_catalog_fields(platform)`（Task 3）
- Produces: `get_platform_tables(db, uid, "fb") -> [{"name": "", "sheet_name": str, "columns": dict}]`；`save_config(db, uid, platform, spreadsheet_id, sheet_name, *, tables=None, columns=None)`

- [ ] **Step 1: 写失败的测试**

在 `py/tests/test_huguan_dashboard.py` 的 **`class TestPlatformTables` 里追加**这四个方法
（该类已有 `_db()` 与 `client` 夹具，uid 用 9，与同文件其它用例一致）：

```python
    # ---- 2026-10-11（子项目 A）：FB 的列映射覆盖随配置存取 ----

    def test_fb_carries_columns_and_gg_does_not(self, client):
        """fb 带 columns（缺省 {}，与 tt 同口径）；**gg 不带** —— 载荷形状逐字节不变。"""
        db = self._db()
        hd.save_config(db, 9, "fb", "SS1", "账户管理分配",
                       columns={"时区": "consumption"})
        hd.save_config(db, 9, "gg", "SS2", "看板G")
        assert hd.get_platform_tables(db, 9, "fb") == [
            {"name": "", "sheet_name": "账户管理分配",
             "columns": {"时区": "consumption"}}]
        assert hd.get_platform_tables(db, 9, "gg") == [
            {"name": "", "sheet_name": "看板G"}]
        db.close()

    def test_fb_columns_default_to_empty_dict(self, client):
        db = self._db()
        hd.save_config(db, 9, "fb", "SS1", "账户管理分配")
        assert hd.get_platform_tables(db, 9, "fb")[0]["columns"] == {}
        db.close()

    def test_fb_empty_columns_do_not_touch_the_stored_text(self, client):
        """传空 dict ⇒ 落盘的配置文本与改动前一致（多一个键都不行）。"""
        db = self._db()
        hd.save_config(db, 9, "fb", "SS1", "账户管理分配", columns={})
        raw = db.execute("SELECT value FROM config WHERE key='huguan_dashboard_9'").fetchone()[0]
        assert json.loads(raw)["fb"] == {"spreadsheet_id": "SS1", "sheet_name": "账户管理分配"}
        db.close()

    def test_fb_columns_survive_a_round_trip(self, client):
        """存了再读回来一模一样 —— 否则改一次配置就把已有覆盖**静默清掉**。"""
        db = self._db()
        hd.save_config(db, 9, "fb", "SS1", "账户管理分配", columns={"时区": "consumption"})
        got = hd.get_platform_tables(db, 9, "fb")[0]["columns"]
        hd.save_config(db, 9, "fb", "SS1", "账户管理分配", columns=got)
        assert hd.get_platform_tables(db, 9, "fb")[0]["columns"] == {"时区": "consumption"}
        db.close()
```

再在**同文件末尾**追加（用该文件既有的 `_create_user` 助手；端点路径是
`POST /api/huguan/dashboard`，**不是** `.../config`）：

```python
class TestFbColumnsPostValidation:
    """POST 层放行 fb 的顶层 columns，白名单按平台取（设计 §4.7）。"""

    def _save(self, client, username, cols):
        hg, _uid = _create_user(client, username, role="huguan")
        body = {"platform": "fb", "spreadsheet_id": "SS", "sheet_name": "账户管理分配"}
        if cols is not None:
            body["columns"] = cols
        return client.post("/api/huguan/dashboard", json=body, headers=hg)

    def test_fb_accepts_a_known_field(self, client):
        assert self._save(client, "_fbcols1", {"备注二": "consumption"}).status_code == 200

    def test_fb_rejects_an_unknown_field(self, client):
        assert self._save(client, "_fbcols2", {"某列": "不存在的字段"}).status_code == 400

    def test_fb_rejects_a_tt_only_field_name(self, client):
        """白名单按**该平台**的目录取：tt 的定位键名 fb 目录里没有。"""
        assert self._save(client, "_fbcols3", {"某列": "advertiser_id"}).status_code == 400

    def test_fb_rejects_two_columns_on_one_field(self, client):
        assert self._save(client, "_fbcols4",
                          {"甲": "consumption", "乙": "consumption"}).status_code == 400

    def test_fb_empty_string_is_allowed_and_repeatable(self, client):
        """空串 = 刻意不采集：合法，且允许多列同指（与 tt 同口径）。"""
        assert self._save(client, "_fbcols5", {"甲": "", "乙": ""}).status_code == 200

    def test_fb_columns_must_be_an_object(self, client):
        assert self._save(client, "_fbcols6", ["consumption"]).status_code == 400
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd py && python -m pytest tests/test_fb_huguan_dashboard.py -q -k TestFbColumnsConfig`
Expected: FAIL —— `get_platform_tables` 返回的项里没有 `columns` 键

- [ ] **Step 3a: `get_platform_tables`**

`py/huguan_dashboard.py` 里 `get_platform_tables` 末尾三行

```python
    return [{"name": "", "sheet_name": _conf_text(entry.get("sheet_name"))}]
```

改成

```python
    if platform == "fb":
        # fb 有了表头映射 ⇒ 与 tt 一样带 `columns`（手工覆盖）。**gg 不带** ——
        # gg 没有表头映射，载荷形状必须逐字节不变（前端也据此分流）。
        cols = entry.get("columns")
        return [{"name": "", "sheet_name": _conf_text(entry.get("sheet_name")),
                 "columns": cols if isinstance(cols, dict) else {}}]
    return [{"name": "", "sheet_name": _conf_text(entry.get("sheet_name"))}]
```

docstring 里「gg / fb → 单元素列表，`name` 为空串，**不带 `columns`**」改成
「gg → 单元素列表、不带 `columns`；fb → 单元素列表、**带 `columns`**」。

- [ ] **Step 3b: `save_config` 收 `columns`**

签名加一个关键字参数：

```python
def save_config(db, user_id: int, platform: str, spreadsheet_id: str, sheet_name: str,
                *, tables=None, columns=None) -> None:
```

`tables=None` 分支：

```python
    if tables is None:
        conf[platform] = {
            "spreadsheet_id": _conf_text(spreadsheet_id),
            "sheet_name": _conf_text(sheet_name),
        }
        # 列映射覆盖（仅 fb；`{表头名: 字段key}`）。空 dict / None 都**不落盘** ——
        # 保持「没配 columns」时的配置文本与改动前逐字节一致（gg 永远走这一支）。
        if platform == "fb" and isinstance(columns, dict) and columns:
            conf[platform]["columns"] = dict(columns)
```

docstring 补一句：「`columns` 只对 fb 生效（tt 的覆盖挂在 `tables[]` 每一项上）。」

- [ ] **Step 3c: POST 路由放行 fb 的 columns**

`py/routes/huguan_dashboard_routes.py` 的 `dashboard_config`（POST）里，
`:130-146` 那段 `columns` 校验所在的循环现在只处理 `tables`（tt 专用）。新增一段
**平行**的 fb 顶层 `columns` 校验（与 tt 那段的规则逐字同款，只是换成顶层字段）：

```python
    # fb 的列映射覆盖在**顶层** `columns`（fb 仍是单表，没有 tables[]）。规则与 tt 的
    # `tables[].columns` 逐字同款：空串合法（刻意不采集，允许多列同指）、非字符串一律 400、
    # 同一字段被两列指定 ⇒ 400、白名单按**该平台**的目录取（fb 目录里没有 tt 的
    # advertiser_id，反之亦然 —— 用错平台的字段名必须当场拒）。
    fb_cols = data.get("columns")
    if platform == "fb" and fb_cols is not None:
        if not isinstance(fb_cols, dict):
            return err("columns 必须是对象", 400)
        allowed = hd._catalog_fields(platform)
        seen_fields = set()
        for header, field in fb_cols.items():
            if isinstance(field, str) and field == "":
                continue
            if not isinstance(field, str) or field not in allowed:
                return err(f"列「{header}」指向了未知字段「{field}」", 400)
            if field in seen_fields:
                return err(f"字段「{field}」被两列同时指定", 400)
            seen_fields.add(field)

    db = database.get_db()
```

并把 `save_config` 调用改成把 `fb_cols` 传下去：

```python
        hd.save_config(db, get_uid(), platform, ss_id, sheet_name, tables=tables,
                       columns=fb_cols if isinstance(fb_cols, dict) else None)
```

> **gg 必须仍拒绝**：`platform == "fb"` 的条件保证了这一点 —— gg 传 `columns` 会被忽略（不落盘），
> 与今天的行为一致。若你希望 gg 传 columns 直接 400，**不要**在本任务加，另开一笔说明。

- [ ] **Step 4: 跑测试确认通过**

Run: `cd py && python -m pytest tests/test_fb_huguan_dashboard.py tests/test_huguan_dashboard.py -q`
Expected: PASS

- [ ] **Step 5: 全量回归**

Run: `cd py && python -m pytest tests/ -q`
Expected: PASS

- [ ] **Step 6: 提交**

```bash
git add py/huguan_dashboard.py py/routes/huguan_dashboard_routes.py py/tests/test_fb_huguan_dashboard.py py/tests/test_huguan_dashboard.py
git commit -m "feat(fb-header-mapping): FB 配置带列映射覆盖（读/写/校验三处放行）" -- py/huguan_dashboard.py py/routes/huguan_dashboard_routes.py py/tests/test_fb_huguan_dashboard.py py/tests/test_huguan_dashboard.py
```

---

## Task 8: `/sheet-headers` 放行 fb + 配置 GET 出 `fb_field_catalog`

**Files:**
- Modify: `py/routes/huguan_dashboard_routes.py`（`dashboard_sheet_headers`、`dashboard_config` GET）
- Test: `py/tests/test_huguan_dashboard.py`

**Interfaces:**
- Consumes: `field_catalog(platform)`（Task 3）
- Produces: `GET /api/huguan/dashboard/sheet-headers?platform=fb&sheet_name=…` 可用；`GET /api/huguan/dashboard/config` 的 fb 载荷带 `fb_field_catalog`

- [ ] **Step 1: 写失败的测试**

照着 `py/tests/test_huguan_dashboard.py` 里 `class TestSheetHeadersEndpoint`（`:6190`）
的既有桩法写。**新增到那个类里**（它有 `_conf()` 助手，只是写死了 tt —— 给它加一个
`platform` 参数，默认 `"tt"`，既有三个用例不受影响）：

```python
    def _conf(self, client, username, tables=None, platform="tt", entry=None):
        """建一个户管用户并把某个平台的看板配置塞进 config 表。

        `entry` 给了就用它当该平台的配置整体（fb 是扁平形）；否则按 `tables` 包成 tt 多表形。
        默认参数保证既有三个用例（tt 多表形）逐字不变。
        """
        hg, _ = _create_user(client, username, role="huguan")
        if entry is None:
            entry = {"spreadsheet_id": "SS", "tables": tables}
        db = database.get_db()
        db.execute("INSERT OR REPLACE INTO config(key,value) VALUES(?,?)",
                   (f"huguan_dashboard_{_uid_of(username)}",
                    json.dumps({platform: entry})))
        db.commit(); db.close()
        return hg

    def test_accepts_fb_and_maps_by_header_name(self, client, monkeypatch):
        """fb 放行：扁平配置 + 按表头解析；门禁仍是「这张表必须在用户自己的配置里」。"""
        import google_sheets_service as gs
        hg = self._conf(client, "_sh4", platform="fb", entry={
            "spreadsheet_id": "SS", "sheet_name": "账户管理分配"})
        headers = [c[1] for c in hd.COLUMN_SPEC["fb"]]
        monkeypatch.setattr(gs, "read_sheet_values", lambda *a, **k: [headers])
        monkeypatch.setattr(gs, "build_service", lambda p: object())
        res = client.get("/api/huguan/dashboard/sheet-headers", headers=hg,
                         query_string={"platform": "fb",
                                       "sheet_name": "账户管理分配"}).get_json()
        assert res["unmatched"] == []
        by_header = {c["header"]: c for c in res["columns"]}
        assert by_header["资产UID"] == {"header": "资产UID", "field": "account_id",
                                        "via": "alias", "alias_field": "account_id"}
        assert by_header["操作人"] == {"header": "操作人", "field": "operator",
                                       "via": "alias", "alias_field": "operator"}
        assert by_header["接户运营"] == {"header": "接户运营", "field": "acceptor",
                                         "via": "alias", "alias_field": "acceptor"}

    def test_config_payload_carries_field_catalog_per_platform(self, client):
        """tt 键名不变；fb 多出 fb_field_catalog；gg 两个键都没有。"""
        hg, _ = _create_user(client, "_sh5", role="huguan")
        conf = client.get("/api/huguan/dashboard", headers=hg).get_json()["config"]
        assert isinstance(conf["tt"]["tt_field_catalog"], list)
        assert isinstance(conf["fb"]["fb_field_catalog"], list)
        assert "tt_field_catalog" not in conf["fb"]
        assert "fb_field_catalog" not in conf["gg"]
        assert "gg_field_catalog" not in conf["gg"]
```

> ⚠️ 改 `_conf` 的签名时**不要动既有三个用例的调用**（它们用位置参数传 `tables`，
> 新签名 `(client, username, tables=None, platform="tt", entry=None)` 完全兼容）。
> 这是本任务唯一需要改既有测试的地方，改完立刻跑一遍 `-k TestSheetHeadersEndpoint` 确认三个老用例仍绿。

- [ ] **Step 2: 跑测试确认失败**

Run: `cd py && python -m pytest tests/test_huguan_dashboard.py -q -k TestFbSheetHeadersAndConfig`
Expected: FAIL —— fb 的请求返回 400「只有 TT 支持表头映射」

- [ ] **Step 3a: `/sheet-headers` 放行 fb**

```python
    platform = str(request.args.get("platform") or "").strip()
    if platform not in ("tt", "fb"):
        return err("只有 TT / FB 支持表头映射", 400)
```

docstring 第一句「读某张 tt 表的第 1 行」改成「读某张规格表（tt / fb）的第 1 行」。

- [ ] **Step 3b: 配置 GET 按平台出目录**

把

```python
                entry["tt_field_catalog"] = hd.tt_field_catalog()
```

改成

```python
                # 列映射 UI 的下拉数据源（设计 §3.2）：**按平台**给，键名 `{platform}_field_catalog`。
                # tt 的键名逐字不变（老前端零破坏）；gg 不给这个键（载荷形状不变）。
                entry[f"{p}_field_catalog"] = hd.field_catalog(p)
```

> `p` 是上面那个循环变量；该分支外面已有 `if p in ("tt", "fb")` 之类的门（读一遍上下文确认，
> 没有就加 `if p in ("tt", "fb"):`）。**gg 绝不能出现这个键。**

- [ ] **Step 4: 跑测试确认通过**

Run: `cd py && python -m pytest tests/test_huguan_dashboard.py -q -k TestFbSheetHeadersAndConfig`
Expected: PASS

- [ ] **Step 5: 全量回归**

Run: `cd py && python -m pytest tests/ -q`
Expected: PASS

- [ ] **Step 6: 提交**

```bash
git add py/routes/huguan_dashboard_routes.py py/tests/test_huguan_dashboard.py
git commit -m "feat(fb-header-mapping): 读表头端点与字段目录对 FB 开放" -- py/routes/huguan_dashboard_routes.py py/tests/test_huguan_dashboard.py
```

---

## Task 9: 前端（一）—— FB 配置摊成一条 tables + 目录键按平台

**Files:**
- Modify: `frontend/src/components/HuguanDashboardCard.vue`

**Interfaces:**
- Consumes: 后端 `GET /api/huguan/dashboard/config` 的 `fb_field_catalog` 与顶层 `columns`（Task 7/8）
- Produces: `hdSeedTables(conf)`；`hdReadHeaders` 用 `HD_PLATFORM` 取平台

- [ ] **Step 1: 写失败的测试（纯逻辑）**

新建 `frontend/tests/fbConfigSeed.test.mjs`：

```js
// FB 配置 → 渲染用 tables 的摊平/折回（设计 §4.9）。
// 运行：cd frontend && npm test
import { test } from 'node:test'
import assert from 'node:assert/strict'
```

> ⚠️ `hdSeedTables` 现在住在 `.vue` 里，`node --test` 拿不到它。**先把它抽到
> `frontend/src/utils/columnMapping.mjs`**（该文件已是「列映射的纯换算」模块，职责相符），
> 参数化平台，然后 `.vue` import 它 —— 这样才有可测的接缝。抽的时候**两个函数都抽**：
> `seedTables(conf, platform)` 与 `flattenColumns(platform, tables)`。

于是 `frontend/tests/fbConfigSeed.test.mjs` 写成：

```js
// FB 配置 → 渲染用 tables 的摊平/折回（设计 §4.9）。
// 运行：cd frontend && npm test
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { seedTables, flattenColumns } from '../src/utils/columnMapping.mjs'

test('fb：扁平配置摊成一条 table', () => {
  const rows = seedTables(
    { spreadsheet_id: 'SS', sheet_name: '账户管理分配', columns: { 时区: 'consumption' } }, 'fb')
  assert.deepEqual(rows, [{ name: '', sheet_name: '账户管理分配',
                            columns: { 时区: 'consumption' } }])
})

test('fb：没配过也给一条空行（用户得有地方填工作表名）', () => {
  assert.deepEqual(seedTables({}, 'fb'), [{ name: '', sheet_name: '', columns: {} }])
})

test('fb：columns 形状不对时兜成空对象', () => {
  assert.deepEqual(seedTables({ sheet_name: 'S', columns: 'garbage' }, 'fb'),
    [{ name: '', sheet_name: 'S', columns: {} }])
})

test('tt：认后端给的 tables，并复制 columns', () => {
  const src = [{ name: '加白户', sheet_name: 'S1', columns: { 日期: 'acquired_date' } }]
  const rows = seedTables({ tables: src }, 'tt')
  assert.deepEqual(rows, [{ name: '加白户', sheet_name: 'S1',
                            columns: { 日期: 'acquired_date' } }])
  assert.notEqual(rows[0].columns, src[0].columns)   // 必须是副本，不能共享引用
})

test('tt：后端没给 tables ⇒ 空列表', () => {
  assert.deepEqual(seedTables({}, 'tt'), [])
})

test('gg：既没有 tables 也不摊平（该分支不渲染表格列表）', () => {
  assert.deepEqual(seedTables({ sheet_name: 'X' }, 'gg'), [])
})

test('fb：折回时只带 sheet_name 与非空 columns', () => {
  assert.deepEqual(
    flattenColumns('fb', [{ name: '', sheet_name: ' 账户管理分配 ', columns: { 时区: 'consumption' } }]),
    { sheet_name: '账户管理分配', columns: { 时区: 'consumption' } })
  assert.deepEqual(
    flattenColumns('fb', [{ name: '', sheet_name: 'S', columns: {} }]),
    { sheet_name: 'S' })                              // 空 columns 不上送（配置文本逐字节不变）
})
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd frontend && npm test`
Expected: FAIL —— `seedTables is not a function`

- [ ] **Step 3a: 在 `frontend/src/utils/columnMapping.mjs` 加两个纯函数**

```js
/** 后端配置 → 渲染用的 tables 列表（设计 §4.9）。
 *  - tt：后端给 tables（存量单表配置后端已兜成单条）⇒ 逐项复制
 *  - fb：后端给**扁平**的 sheet_name + columns（fb 仍是单表）⇒ 包成一条；
 *        没配过也给一条空行 —— 用户得有地方填工作表名
 *  - gg：没有列映射，返回 []（该分支不渲染表格列表）
 *  columns 一律复制成新对象：它是「未保存」标记的基线，共享引用会让基线跟着改。 */
export function seedTables(conf, platform) {
  const c = conf || {}
  if (Array.isArray(c.tables)) {
    return c.tables.map(t => ({
      name: t.name || '',
      sheet_name: t.sheet_name || '',
      columns: (t.columns && typeof t.columns === 'object') ? { ...t.columns } : {},
    }))
  }
  if (platform === 'fb') {
    return [{
      name: '',
      sheet_name: c.sheet_name || '',
      columns: (c.columns && typeof c.columns === 'object') ? { ...c.columns } : {},
    }]
  }
  return []
}

/** 渲染用的 tables → 后端的扁平配置（fb 专用，设计 §4.6）。
 *  空 columns **不上送** —— 保持「没配覆盖」时的配置文本与改动前一致。 */
export function flattenColumns(platform, tables) {
  const t = (tables || [])[0] || {}
  const out = { sheet_name: (t.sheet_name || '').trim() }
  const cols = t.columns
  if (cols && typeof cols === 'object' && Object.keys(cols).length) out.columns = { ...cols }
  return out
}
```

- [ ] **Step 3b: `.vue` 里接上**

- import：`import { rowsFromColumns, columnsFromRows, pickColumn, seedTables, flattenColumns } from '@/utils/columnMapping.mjs'`
- `loadHdConfig`：

```js
    const conf = (res.config && res.config[HD_PLATFORM]) || {}
    // 字段目录按平台取（tt 的键名 `tt_field_catalog` 逐字不变；gg 没有这个键 ⇒ 兜成 []）
    const catalogKey = `${HD_PLATFORM}_field_catalog`
    hdFieldCatalog.value = Array.isArray(conf[catalogKey]) ? conf[catalogKey] : []
    hdForm.value = {
      spreadsheet_id: conf.spreadsheet_id || '',
      sheet_name: conf.sheet_name || '',
      tables: seedTables(conf, HD_PLATFORM),
    }
```

- `saveHdConfig` 的分支：

```js
    if (HD_PLATFORM === 'tt') {
      /* …既有那段原样不动… */
    } else if (HD_PLATFORM === 'fb') {
      // fb 仍是单表：摊平的 sheet_name + columns 在顶层（设计 §4.6）
      Object.assign(body, flattenColumns('fb', hdForm.value.tables))
    } else {
      body.sheet_name = hdForm.value.sheet_name
    }
```

- `hdConfigured`：

```js
const hdConfigured = computed(() => {
  if (!hdForm.value.spreadsheet_id) return false
  if (HD_PLATFORM === 'tt') {
    return hdForm.value.tables.some(t => (t.name || '').trim() && (t.sheet_name || '').trim())
  }
  if (HD_PLATFORM === 'fb') {
    // fb 没有户类型名，只看工作表名
    return hdForm.value.tables.some(t => (t.sheet_name || '').trim())
  }
  return !!hdForm.value.sheet_name
})
```

- `hdReadHeaders` 里 `huguanApi.getSheetHeaders('tt', name)` → `huguanApi.getSheetHeaders(HD_PLATFORM, name)`

- [ ] **Step 4: 跑测试确认通过**

Run: `cd frontend && npm test`
Expected: PASS

- [ ] **Step 5: 前端构建自检（不启动服务）**

Run: `cd frontend && npx vite build`
Expected: 构建成功（无报错）。**不要**起 dev server。

- [ ] **Step 6: 提交**

```bash
git add frontend/src/utils/columnMapping.mjs frontend/src/components/HuguanDashboardCard.vue frontend/tests/fbConfigSeed.test.mjs
git commit -m "feat(fb-header-mapping): FB 配置摊成一条表 + 目录键按平台（前端）" -- frontend/src/utils/columnMapping.mjs frontend/src/components/HuguanDashboardCard.vue frontend/tests/fbConfigSeed.test.mjs
```

---

## Task 10: 前端（二）—— 模板放开 fb（四处隐藏）+ 未采集区 + 下拉「只写」

**Files:**
- Modify: `frontend/src/components/HuguanDashboardCard.vue`

**Interfaces:**
- Consumes: `seedTables` / `flattenColumns`（Task 9）、后端目录的 `direction === "w"`（Task 3）
- Produces: FB 卡片出现「工作表名 + 列映射」；gg 模板与 tt 模板的可见元素**不变**

- [ ] **Step 1: 逐处改模板（无独立测试，靠 Step 3 的构建 + 人工验收）**

按下面五处改 `HuguanDashboardCard.vue`：

1. **单表分支只留给 gg**（`:34`）
   `v-if="HD_PLATFORM !== 'tt'"` → `v-if="HD_PLATFORM === 'gg'"`
   （`:48` 的 `v-else` 保持 —— 它现在接住 tt 与 fb）

2. **表格列表的说明文案分平台**（`:49-55`）
   把现有的「账户表（户类型 → 工作表）」标题与两行说明包进
   `<template v-if="HD_PLATFORM === 'tt'">`，紧随其后加 fb 的一段：

```html
        <div v-else style="font-weight:500;font-size:13px;color:#374151;margin-bottom:6px;">
          账户表
        </div>
        <div v-else style="font-size:12px;color:#6b7280;margin-bottom:8px;line-height:1.6;">
          这张表就是 FB 的账户管理表。右边选它在 Google 表格里对应的工作表，
          下面的「列映射」可以把每一列指派到系统字段。
        </div>
```

3. **每行的户类型名输入与删除按钮只给 tt**（`:58-64`）
   - `<el-input v-model="t.name" …>` 上加 `v-if="HD_PLATFORM === 'tt'"`
   - `<el-button … @click="removeHdTable(i)">删除</el-button>` 上加 `v-if="HD_PLATFORM === 'tt'"`

4. **该行的两个按表按钮只给 tt**（`:168-183`）
   整个 `<el-tooltip …><span class="hd-sheet-actions">…</span></el-tooltip>` 外层加
   `v-if="HD_PLATFORM === 'tt'"`（**保留**它内部的按钮不动）。
   同段里「正在处理…」那行灰字（`:186-189`）不动。

5. **「＋ 新增户类型」与空态提示只给 tt**（`:191-194`）
   - `<el-button size="small" :disabled="hdBusy" @click="addHdTable">＋ 新增户类型</el-button>`
     加 `v-if="HD_PLATFORM === 'tt'"`
   - `<div v-if="!hdForm.tables.length" …>` 改成 `v-if="HD_PLATFORM === 'tt' && !hdForm.tables.length"`

6. **「未采集列」区块放行 fb**（`:581`）
   `v-if="HD_PLATFORM === 'tt' && hdUnmatchedColumns.length"`
   → `v-if="(HD_PLATFORM === 'tt' || HD_PLATFORM === 'fb') && hdUnmatchedColumns.length"`

7. **下拉加「只写」标记**（`hdColumnOptions`，`:1437-1444`）

```js
const hdColumnOptions = computed(() => (hdFieldCatalog.value || [])
  .filter(c => c && c.key)
  .map(c => ({
    value: c.key,
    label: c.label || c.key,
    // 三档标记与后端 direction 一一对应：定位键 > 只读回 > 只写。
    // 「只写」是 fb 的「操作人」这类系统写、绝不读回的列（设计 §4.1）。
    mark: c.key_col ? '定位键'
      : (c.direction === 'r' ? '只读回' : (c.direction === 'w' ? '只写' : '')),
    keyCol: !!c.key_col,
  })))
```

- [ ] **Step 2: 确认 gg 与 tt 的模板未被误伤**

Run: `grep -n "HD_PLATFORM === 'gg'\|HD_PLATFORM === 'tt'\|HD_PLATFORM === 'fb'\|HD_PLATFORM !== 'tt'" frontend/src/components/HuguanDashboardCard.vue`

逐行确认：gg 原有的三处单表元素仍在 `gg` 分支下；tt 的四处隐藏项都还在（只是加了 `v-if`）。
**特别确认 `:34` 那一支对 gg 的行为与改动前逐字相同。**

- [ ] **Step 3: 构建自检**

Run: `cd frontend && npx vite build`
Expected: 构建成功

- [ ] **Step 4: 前端测试**

Run: `cd frontend && npm test`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add frontend/src/components/HuguanDashboardCard.vue
git commit -m "feat(fb-header-mapping): FB 卡片复用 TT 模板（隐藏户类型名/删除/按表按钮/新增）" -- frontend/src/components/HuguanDashboardCard.vue
```

---

## Task 11: 收尾 —— 全量回归 + 验收清单

**Files:**
- Modify: 无（只跑回归）
- Create: 无

- [ ] **Step 1: 后端全量**

Run: `cd py && python -m pytest tests/ -q`
Expected: 全绿。把通过数与**改动前**的基线比较（基线：本次开工前跑一次记下来）。
**任何一条从绿变红都必须先查清原因，不许改测试来让它变绿。**

- [ ] **Step 2: 前端全量 + 构建**

Run: `cd frontend && npm test && npx vite build`
Expected: 全绿 + 构建成功

- [ ] **Step 3: 三条锚的最终证据**

Run: `cd py && python -m pytest tests/test_huguan_dashboard.py -q -k "TestFieldCatalogPerPlatform or TestFbHeaderMappingAnchor or TestFbWritePathColMap or TestFbSyncReadPath"`
Expected: PASS。这三组就是「FB 表头正常时逐字节等价」「TT/GG 行为未变」的证据。

- [ ] **Step 4: 写验收清单（追加到本文件末尾）**

把下面的清单补进本计划「## 人工验收清单」一节（Task 12 的产物），并在提交信息里带上。

- [ ] **Step 5: 提交（如有收尾改动）**

```bash
git add docs/superpowers/plans/2026-10-11-fb-header-mapping.md
git commit -m "docs(fb-header-mapping): 收尾 —— 全量回归结果与人工验收清单" -- docs/superpowers/plans/2026-10-11-fb-header-mapping.md
```

---

## 人工验收清单（全部由用户在浏览器里点，我不启动任何进程）

**前置**：`cd frontend && npm run build` 之后重启 Flask。两步都由用户执行。

### A. FB 正常路径（表头未动过）
- [ ] A1 FB 设置页的户管看板卡片里出现「工作表名」下拉 + 「列映射」折叠区；**没有**「户类型名」「删除」「导入这张表/刷新回这张表」「＋ 新增户类型」
- [ ] A2 选好「账户管理分配」→ 保存配置 → 刷新页面，配置还在
- [ ] A3 点「读取表头」→ 17 行逐列显示，每行都是「别名」标记、**没有一个红条「未采集」**
- [ ] A4 「操作人」行标「只写」、「资产UID」标「定位键」、「接户运营」标「只读回」
- [ ] A5 「从表同步到系统」跑一次 → 报告与改造前一致（同样的新增/更新条数）

### B. FB 表头被改动（这是本次要修的核心）
- [ ] B1 把表里的「时区」和「消耗」两列**对调**（整列连表头一起搬）→ 点「读取表头」→ 两行跟着换了位置，标记仍是「别名」
- [ ] B2 同步一次 → 报告里**没有**「未采集列」提示；系统里的时区/消耗值不串
- [ ] B3 在中间插一列「临时备注」→ 读取表头 → 该行红条「未采集」；同步一次 → 报告出现「1 列未采集 —— 临时备注」与「去指派」入口
- [ ] B4 点「去指派」→ 面板自动展开并滚到可见 → 在「临时备注」那行选「（不采集）」→ 保存 → 再同步，未采集提示消失
- [ ] B5 把「资产UID」表头改坏（如加个下划线）→ 同步 → **被拒绝**，提示里写的是「**资产UID**」不是「账户ID」

### C. 手工指派
- [ ] C1 把「时区」那列改指派成「消耗」→ 该行标「手工」+「未保存」→ 保存后标记熄灭；「消耗」那行变成红条「未采集」
- [ ] C2 刷新页面 → 刚才的指派还在
- [ ] C3 把指派改回「时区」→ 保存 → 再读表头，该行回到「别名」

### D. 回写与撤回
- [ ] D1 把「在用运营」列挪到别的位置（连表头一起）→ 在系统里改一个账户的归属 → 回表看：新归属名写在**挪过去的那一列**，不是原来的 J 列
- [ ] D2 撤回上一次同步 → 表里那列恢复原值

### E. GG 与 TT 没被误伤
- [ ] E1 GG 的户管看板卡片**完全没变**（还是单个「工作表名」下拉，没有列映射区）
- [ ] E2 TT 的卡片**完全没变**（多表 + 三处入口 + 列映射区都在）
- [ ] E3 GG 与 TT 各跑一次同步/刷新，报告正常

---

## Self-Review 记录

**Spec 覆盖**：§4.1→Task 1；§4.2→Task 2；§4.3→Task 2（口径未动，靠既有 TT 测试作证）；§4.4→Task 4；§4.5→Task 5+6；§4.6→Task 7；§4.7→Task 3+7+8；§4.8→Task 5；§4.9→Task 9+10；§六的三条锚→Task 1/2/11；§七影响面→各任务的 Files 段。

**已知的取舍**（供审查者核对）：
- Task 9 把 `seedTables` / `flattenColumns` 抽进 `columnMapping.mjs`：这是为**可测**付出的结构改动，
  不是重构 —— 两个函数是该模块既有职责（列映射的纯换算）的自然延伸。
- Task 8 要给既有 `TestSheetHeadersEndpoint._conf` **加默认参数**（`platform` / `entry`）。
  默认值保证既有三个用例逐字不变，但这是本计划里唯一改到既有测试**结构**（而非只加参数）的地方，
  审查时要单独确认那三个老用例仍绿。
- Task 6 的 `huguan_fb_acceptor_sync` 从「零额外读」变成「读一次表头行」—— 这是表头映射的必然代价，
  与兄弟函数 `huguan_owner_channel_sync` 口径一致（它早就这么做了）。

**自审修正记录**（写完后重读 spec 与代码时抓到的）：
1. 配置端点路径是 `POST /api/huguan/dashboard`（`:84`），**不是** `/api/huguan/dashboard/config` —— 初稿写错了。
2. 测试夹具名不能编：已按 `py/tests/test_huguan_dashboard.py` 真实的
   `_create_user(client, username, role=…)` / `_uid_of(username)` / `TestPlatformTables._db()` 写实。
3. Task 4 初稿写了「先写错误版本再纠正」的两段测试 —— 已删掉错的那段。
4. 写死 `"I"` 的是**两处**（`_fb_acceptor_cells` 与路由 `:407`），初稿当成了一处。
