# TT「换绑情况」列改造 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让 TT 的账户归属只认「接户运营」列，并把「换绑情况」列改造成由系统自动生成的换绑记录字段（`旧转新月.日`）。

**Architecture:** 按平台分叉 —— TT 走新语义，GG 的「重新分配」逐字节不变。新增 `tt_accounts.owner_change_note` 列承载 L 列的值；L 列在 `COLUMN_SPEC` 里由合成字段 `_owner_channel` 改为普通文本字段且 `writable=False`（不参与任何全量回写）；系统只在 reassign 端点写它。

**Tech Stack:** Python 3.11 / Flask / SQLite(WAL) / pytest；前端 Vue 3 + Element Plus。

**Spec:** `docs/superpowers/specs/2026-10-06-tt-owner-change-note-design.md`

## Global Constraints

- **仅 TT**。GG 的「重新分配」（H 列）行为、文案、写入内容、列定义**逐字节不得变化**。
- **纯增量原则**：不改动既有功能的代码逻辑；新逻辑按平台分叉接入。
- **注释用中文**，与文件既有风格一致（说明「为什么」而非「是什么」）。
- **`py/database.py` 有并行会话在修改**（`git status` 显示 `M`）。所有改动按**符号名**定位，不要只按行号；`git add` 只加本任务明确列出的文件，**禁用 `git add -A`**。
- 测试运行方式固定：`cd py && python -m pytest tests/<file>::<Class>::<test> -v`
- 月日格式**不得**用 `strftime("%-m")` —— Windows 不支持该格式符，用 `f"{now.month}.{now.day}"`。

---

## File Structure

| 文件 | 职责 | 本计划改动 |
|------|------|-----------|
| `py/database.py` | 建表 + 列迁移 | 新增 `tt_accounts.owner_change_note`（建表语句 + `_add_column_if_missing`） |
| `py/huguan_dashboard.py` | 户管看板双向同步的纯逻辑层 | 列定义、归属判定分叉、读回字段、写表函数加 `text` 参数 |
| `py/routes/huguan_dashboard_routes.py` | 户管看板 HTTP 层 | 同步后的清空动作改 GG-only |
| `py/routes/tt_accounts_routes.py` | TT 账户 HTTP 层 | reassign 生成并落库换绑记录文本 |
| `frontend/src/views/tt/TtAccountPanel.vue` | TT 账户面板 | 加只读「换绑情况」列 |
| `py/tests/test_huguan_dashboard.py` | 同步逻辑测试 | 新增用例 + 6 处既有断言随语义更新 |

---

## Task 1: 新增 `tt_accounts.owner_change_note` 列

**Files:**
- Modify: `py/database.py`（`tt_accounts` 建表语句内 `remark` 之后；`_ensure_columns()` 内）
- Test: `py/tests/test_huguan_dashboard.py`

**Interfaces:**
- Consumes: 无
- Produces: 数据库列 `tt_accounts.owner_change_note TEXT DEFAULT ''`，供 Task 4/6 读写

- [ ] **Step 1: 写失败测试**

追加到 `py/tests/test_huguan_dashboard.py` 末尾：

```python
class TestOwnerChangeNoteColumn:
    def test_tt_accounts_has_owner_change_note_column(self, client):
        """新列必须存在，且默认空串（不能是 NULL —— 读回按表覆盖时 NULL 与 '' 要同义）。"""
        db = database.get_db()
        cols = {r[1]: r for r in db.execute("PRAGMA table_info(tt_accounts)").fetchall()}
        assert "owner_change_note" in cols, "tt_accounts 缺 owner_change_note 列"
        assert cols["owner_change_note"][4] == "''"   # dflt_value
        db.close()

    def test_owner_change_note_defaults_to_empty(self, client):
        db = database.get_db()
        db.execute("INSERT INTO tt_accounts(advertiser_id, name) VALUES('OCN-1','OCN-1')")
        db.commit()
        row = db.execute(
            "SELECT owner_change_note FROM tt_accounts WHERE advertiser_id='OCN-1'").fetchone()
        assert row["owner_change_note"] == ""
        db.close()
```

- [ ] **Step 2: 跑测试确认失败**

```bash
cd py && python -m pytest tests/test_huguan_dashboard.py::TestOwnerChangeNoteColumn -v
```

预期：两条都 FAIL。第一条 `AssertionError: tt_accounts 缺 owner_change_note 列`；
第二条 `sqlite3.OperationalError: no such column: owner_change_note`。

- [ ] **Step 3: 改建表语句**

在 `py/database.py` 的 `tt_accounts` 建表语句里，`remark TEXT DEFAULT '',` 之后加一行：

```sql
            owner_change_note TEXT DEFAULT '',
```

- [ ] **Step 4: 加列迁移（存量库）**

在 `py/database.py` 的 `_ensure_columns()` 内，紧挨其它 `_add_column_if_missing` 调用处加入
（参照 `fb_accounts` 的 `remark` 先例）：

```python
    # TT 换绑记录（2026-10-06 规格）：由 reassign 生成「旧转新月.日」，读回时按表覆盖。
    # 建表语句服务全新库，这一条服务存量库 —— 两处都要有。
    _add_column_if_missing(conn, "tt_accounts", "owner_change_note",
                           "owner_change_note TEXT DEFAULT ''")
```

- [ ] **Step 5: 跑测试确认通过**

```bash
cd py && python -m pytest tests/test_huguan_dashboard.py::TestOwnerChangeNoteColumn -v
```

预期：2 passed。

- [ ] **Step 6: 跑相关回归**

```bash
cd py && python -m pytest tests/test_huguan_dashboard.py tests/test_tt_accounts.py -q
```

预期：全部通过（新列是纯增量，不应打破任何既有用例）。

- [ ] **Step 7: 提交**

```bash
git add py/database.py py/tests/test_huguan_dashboard.py
git commit -m "feat(tt): tt_accounts 新增 owner_change_note 列（换绑记录）"
```

---

## Task 2: `COLUMN_SPEC["tt"]` 的 L 列改为普通文本字段

**Files:**
- Modify: `py/huguan_dashboard.py`（`COLUMN_SPEC["tt"]` 的 L 条目）
- Test: `py/tests/test_huguan_dashboard.py`

**Interfaces:**
- Consumes: Task 1 的列名 `owner_change_note`
- Produces: L 列成为 `readable=True` 的普通字段，`parse_row()` 输出键由 `_owner_channel`
  变为 `owner_change_note`；L 列 `writable=False`（不进 `cells_for_row`）

- [ ] **Step 1: 改既有测试（先让它们表达新契约）**

改 `TestParseRow::test_tt_parse` 中的一行断言：

```python
        assert p["owner_change_note"] == "王五"   # L 换绑情况（2026-10-06 起为普通文本字段）
```

改 `TestParseRow::test_tt_parse_emits_exact_field_set` 的键集：

```python
        assert set(p) == {"account_id", "acquired_date", "_dead_flag", "bc_name",
                          "country", "agent_name", "owner_name", "owner_change_note",
                          "timezone", "status_name", "consumption", "remark"}
```

改 `TestColumnSpec::test_writable_cols_produce_expected_ranges` 的 TT 分支：

```python
            else:
                # A..J 连续；K 跳过；L 不可写（换绑记录，只由 reassign 单点写）；M 单独一段
                assert merge_ranges(cols) == ["A:J", "M:M"]
```

- [ ] **Step 2: 跑测试确认失败**

```bash
cd py && python -m pytest tests/test_huguan_dashboard.py::TestParseRow tests/test_huguan_dashboard.py::TestColumnSpec -v
```

预期：`test_tt_parse` KeyError `owner_change_note`；`test_tt_parse_emits_exact_field_set`
键集不等；`test_writable_cols_produce_expected_ranges` 得到 `['A:J', 'L:M']` 而非 `['A:J', 'M:M']`。

- [ ] **Step 3: 改列定义**

`py/huguan_dashboard.py` 的 `COLUMN_SPEC["tt"]` 中：

```python
        ("L", "换绑情况",  "owner_change_note", False, True),
```

`writable=False` 的理由：这一列是**系统生成的换绑记录**，只由 reassign 端点单点写入，
不参与任何全量/单行回写。这也让原「规则 2（自动回写不得碰这一列）」继续成立。

**GG 的 H 列条目（`("H", "重新分配", "_owner_channel", True, True)`）不要动。**

- [ ] **Step 4: 跑测试确认通过**

```bash
cd py && python -m pytest tests/test_huguan_dashboard.py::TestParseRow tests/test_huguan_dashboard.py::TestColumnSpec -v
```

预期：全部 passed。

- [ ] **Step 5: 提交**

```bash
git add py/huguan_dashboard.py py/tests/test_huguan_dashboard.py
git commit -m "feat(tt): 换绑情况列改为普通文本字段 owner_change_note（只读回、不回写）"
```

---

## Task 3: 归属判定按平台分叉

**Files:**
- Modify: `py/huguan_dashboard.py`（`effective_owner_name()` 及其唯一调用点）
- Test: `py/tests/test_huguan_dashboard.py`（`TestEffectiveOwnerName`）

**Interfaces:**
- Consumes: 无
- Produces: `effective_owner_name(parsed: dict, platform: str) -> str` —— **`platform` 为必填位置参数**，
  刻意不给默认值（默认值会让漏传的 TT 调用方静默拿到 GG 语义）

- [ ] **Step 1: 改既有测试并新增 TT 用例**

把 `TestEffectiveOwnerName` 整个类替换为：

```python
class TestEffectiveOwnerName:
    # ---- GG：维持 §7.1，变更通道非空时压过运营列 ----

    def test_gg_channel_wins_when_present(self):
        from huguan_dashboard import effective_owner_name
        p = {"owner_name": "张三", "_owner_channel": "李四"}
        assert effective_owner_name(p, "gg") == "李四"

    def test_gg_falls_back_to_owner_when_channel_empty(self):
        from huguan_dashboard import effective_owner_name
        assert effective_owner_name(
            {"owner_name": "张三", "_owner_channel": ""}, "gg") == "张三"

    def test_gg_whitespace_channel_falls_back_to_owner(self):
        """通道只有空白时不算「已填」，应回退到运营列。"""
        from huguan_dashboard import effective_owner_name
        assert effective_owner_name(
            {"owner_name": "张三", "_owner_channel": "   "}, "gg") == "张三"

    def test_gg_blank_when_both_empty(self):
        from huguan_dashboard import effective_owner_name
        assert effective_owner_name({"owner_name": "", "_owner_channel": "  "}, "gg") == ""

    # ---- TT：2026-10-06 起只认「接户运营」列 ----

    def test_tt_ignores_legacy_channel_key(self):
        """TT 归属恒取接户运营列 —— 即使 parsed 里仍带着 _owner_channel 也不看它。"""
        from huguan_dashboard import effective_owner_name
        p = {"owner_name": "张三", "_owner_channel": "李四"}
        assert effective_owner_name(p, "tt") == "张三"

    def test_tt_uses_owner_change_note_as_plain_text_not_owner(self):
        """换绑情况现在是普通文本字段，绝不参与归属判定。"""
        from huguan_dashboard import effective_owner_name
        p = {"owner_name": "张三", "owner_change_note": "阿豪转李四10.6"}
        assert effective_owner_name(p, "tt") == "张三"

    def test_tt_blank_owner(self):
        from huguan_dashboard import effective_owner_name
        assert effective_owner_name(
            {"owner_name": "", "owner_change_note": "阿豪转李四10.6"}, "tt") == ""
```

- [ ] **Step 2: 跑测试确认失败**

```bash
cd py && python -m pytest tests/test_huguan_dashboard.py::TestEffectiveOwnerName -v
```

预期：GG 四条 FAIL（`TypeError: effective_owner_name() takes 1 positional argument but 2 were given`）；
TT 三条同样 FAIL。

- [ ] **Step 3: 改函数**

`py/huguan_dashboard.py` 的 `effective_owner_name()` 整体替换为：

```python
def effective_owner_name(parsed: dict, platform: str) -> str:
    """有效归属判定，按平台分叉。

    TT（2026-10-06 规格）：归属**恒取**「接户运营」列。原「换绑情况」列的变更通道语义已取消，
    该列改作换绑记录文本（`owner_change_note`），不参与归属判定。

    GG：维持 2026-09-23 规格 §7.1 —— 「重新分配」列非空时压过「运营」列。
    「表里运营列和重新分配列不一致，就以表里的重新分配为准」（用户原话）。

    platform 是**必填位置参数**，刻意不给默认值：漏传的 TT 调用方会静默拿到 GG 语义，
    那正是本次要消除的 bug。
    """
    if platform == "tt":
        return (parsed.get("owner_name") or "").strip()
    channel = (parsed.get("_owner_channel") or "").strip()
    if channel:
        return channel
    return (parsed.get("owner_name") or "").strip()
```

- [ ] **Step 4: 改唯一调用点**

`py/huguan_dashboard.py` 的 `build_diff()` 内：

```python
        want_owner_name = effective_owner_name(p, platform)
```

- [ ] **Step 5: 跑测试确认通过**

```bash
cd py && python -m pytest tests/test_huguan_dashboard.py::TestEffectiveOwnerName -v
```

预期：7 passed。

- [ ] **Step 6: 提交**

```bash
git add py/huguan_dashboard.py py/tests/test_huguan_dashboard.py
git commit -m "feat(tt): 归属判定按平台分叉，TT 只认接户运营列"
```

---

## Task 4: L 列的值读回存进 `owner_change_note`

**Files:**
- Modify: `py/huguan_dashboard.py`（`_PLAIN_TEXT_FIELDS["tt"]`）
- Test: `py/tests/test_huguan_dashboard.py`

**Interfaces:**
- Consumes: Task 1 的列名、Task 2 的 `parse_row` 输出键
- Produces: `to_create` / `to_update` 的 `db_values` / `fields` 中出现键 `owner_change_note`

- [ ] **Step 1: 写失败测试**

追加：

```python
class TestOwnerChangeNoteReadBack:
    """L 列的值按表覆盖存进 owner_change_note（其他文本列同口径）。"""

    def _prepare(self, client):
        db = database.get_db()
        u1 = _seed(db, "_ocn_a", "张三")
        return db, u1

    def test_new_account_carries_note(self, client):
        from huguan_dashboard import build_diff, parse_row
        db, u1 = self._prepare(client)
        row = [""] * 13
        row[2], row[6], row[11] = "OCN-NEW", "张三", "阿豪转张三10.6"
        diff = build_diff(db, [dict(parse_row(row, "tt"), row=2)], "tt")
        item = diff["to_create"][0]
        assert item["db_values"]["owner_change_note"] == "阿豪转张三10.6"
        db.close()

    def test_existing_account_note_is_overwritten(self, client):
        from huguan_dashboard import build_diff, parse_row
        db, u1 = self._prepare(client)
        _seed_tt_account(db, "OCN-EX", u1, name="张三")
        db.execute("UPDATE tt_accounts SET owner_change_note='旧记录' WHERE advertiser_id='OCN-EX'")
        db.commit()
        row = [""] * 13
        row[2], row[6], row[11] = "OCN-EX", "张三", "新记录A转B10.7"
        diff = build_diff(db, [dict(parse_row(row, "tt"), row=2)], "tt")
        item = diff["to_update"][0]
        assert item["fields"]["owner_change_note"] == "新记录A转B10.7"
        db.close()

    def test_clearing_note_is_reported_in_clears(self, client):
        """表里清空 → 系统清空，且必须出现在 clears 里让户管看见（不可逆动作）。"""
        from huguan_dashboard import build_diff, parse_row
        db, u1 = self._prepare(client)
        _seed_tt_account(db, "OCN-CLR", u1, name="张三")
        db.execute("UPDATE tt_accounts SET owner_change_note='要没了' WHERE advertiser_id='OCN-CLR'")
        db.commit()
        row = [""] * 13
        row[2], row[6] = "OCN-CLR", "张三"   # L 列留空
        diff = build_diff(db, [dict(parse_row(row, "tt"), row=2)], "tt")
        item = diff["to_update"][0]
        assert item["fields"]["owner_change_note"] == ""
        assert "owner_change_note" in item["clears"]
        db.close()
```

- [ ] **Step 2: 跑测试确认失败**

```bash
cd py && python -m pytest tests/test_huguan_dashboard.py::TestOwnerChangeNoteReadBack -v
```

预期：三条都 FAIL，`KeyError: 'owner_change_note'`（键根本没被收集）。

- [ ] **Step 3: 加进文本列清单**

`py/huguan_dashboard.py` 的 `_PLAIN_TEXT_FIELDS`：

```python
_PLAIN_TEXT_FIELDS = {
    "gg": ("acquired_date", "timezone"),
    "tt": ("acquired_date", "country", "timezone", "consumption", "remark",
           "owner_change_note"),
}
```

- [ ] **Step 4: 跑测试确认通过**

```bash
cd py && python -m pytest tests/test_huguan_dashboard.py::TestOwnerChangeNoteReadBack -v
```

预期：3 passed。

- [ ] **Step 5: 提交**

```bash
git add py/huguan_dashboard.py py/tests/test_huguan_dashboard.py
git commit -m "feat(tt): 换绑情况列值读回存进 owner_change_note（按表覆盖）"
```

---

## Task 5: 取消 TT 同步后的「清空 L 列」

**Files:**
- Modify: `py/routes/huguan_dashboard_routes.py`（`dashboard_sync()` 内 规则 3② 那一步）
- Test: `py/tests/test_huguan_dashboard.py`

**Interfaces:**
- Consumes: 无
- Produces: TT 同步应用归属变更后**不再**产生 L 列写回；GG 仍产生 H 列清空写回

**为什么必须改**：L 列现在是换绑记录。若这条清空对 TT 生效，每次同步都会抹掉记录；
又因 Task 4 的读回是按表覆盖（空串会落库），记录会被**双重抹除**。

- [ ] **Step 1: 写失败测试（TT 不回写 + GG 回归护栏）**

追加：

```python
class TestSyncChannelClearPlatformSplit:
    """规则 3② 的清空动作按平台分叉：TT 不清（L 是换绑记录），GG 照清。"""

    def _wire(self, client, platform):
        hg, uid = _create_user(client, f"_clr_{platform}", role="huguan", platform=platform)
        db = database.get_db()
        target = _seed(db, f"_clr_t_{platform}", "李四", platform=platform)
        db.execute("INSERT OR REPLACE INTO config(key,value) VALUES(?,?)",
                   (f"huguan_dashboard_{uid}",
                    json.dumps({platform: {"spreadsheet_id": "SS", "sheet_name": "S"}})))
        db.commit()
        db.close()
        return hg, uid, target

    def test_tt_sync_does_not_clear_change_note(self, client, monkeypatch):
        hg, uid, target = self._wire(client, "tt")
        db = database.get_db()
        _seed_tt_account(db, "CLR-TT", uid)   # 归属起手是户管自己，表里 G 列写「李四」→ 触发变更
        db.commit()
        db.close()
        import google_sheets_service as gs
        monkeypatch.setattr(gs, "read_sheet_values", lambda *a, **k: [
            ["入库时间", "是否回收", "账户ID", "BC", "国家", "所属渠道",
             "接户运营", "时区", "状态", "消耗", "位置", "换绑情况", "产品信息"],
            [""] * 2 + ["CLR-TT"] + [""] * 3 + ["李四"] + [""] * 6,
        ])
        captured = []
        _stub_sheets(monkeypatch, captured)
        resp = client.post("/api/huguan/dashboard/sync", headers=hg,
                           json={"platform": "tt", "dry_run": False,
                                 "confirmed": {"owner": ["CLR-TT"]}})
        assert resp.status_code == 200
        all_cells = [c for cap in captured for c in cap["rows"]]
        assert not any("L" in c["cells"] for c in all_cells), \
            "TT 同步不得写 L 列（换绑记录会被抹掉）"

    def test_gg_sync_still_clears_channel_column(self, client, monkeypatch):
        """回归护栏：GG 的清空行为一个字都不能变。"""
        hg, uid, target = self._wire(client, "gg")
        db = database.get_db()
        db.execute("INSERT INTO accounts(account_id, name, owner_id) VALUES('CLR-GG','CLR-GG',?)",
                   (uid,))
        db.commit()
        db.close()
        import google_sheets_service as gs
        monkeypatch.setattr(gs, "read_sheet_values", lambda *a, **k: [
            ["日期", "是否封户", "账户ID", "MCC", "国家", "所属渠道", "运营", "重新分配"],
            ["", "", "CLR-GG", "", "", "", "户管本人", "李四"],
        ])
        captured = []
        _stub_sheets(monkeypatch, captured)
        resp = client.post("/api/huguan/dashboard/sync", headers=hg,
                           json={"platform": "gg", "dry_run": False,
                                 "confirmed": {"owner": ["CLR-GG"]}})
        assert resp.status_code == 200
        all_cells = [c for cap in captured for c in cap["rows"]]
        assert any(c["cells"].get("H") == "" for c in all_cells), \
            "GG 同步仍应清空 H 列"
```

- [ ] **Step 2: 跑测试确认失败**

```bash
cd py && python -m pytest tests/test_huguan_dashboard.py::TestSyncChannelClearPlatformSplit -v
```

预期：`test_tt_sync_does_not_clear_change_note` FAIL（当前 TT 也清 L）；
`test_gg_sync_still_clears_channel_column` PASS（GG 现状就是对的，这条是护栏）。

- [ ] **Step 3: 改为 GG-only**

`py/routes/huguan_dashboard_routes.py` 的 `dashboard_sync()` 中，把：

```python
            _write_background(conf, hd.owner_channel_cells(applied, platform, ""))
```

改为：

```python
            # 规则 3② 只对 GG 生效（2026-10-06 规格）：TT 的 L 列已是换绑记录，
            # 同步时清空会抹掉记录，且因读回按表覆盖会连带清掉系统里的值。
            if platform != "tt":
                _write_background(conf, hd.owner_channel_cells(applied, platform, ""))
```

同段上一行的规则 4 回写（写 `OWNER_COL`）**保持不动**。

- [ ] **Step 4: 跑测试确认通过**

```bash
cd py && python -m pytest tests/test_huguan_dashboard.py::TestSyncChannelClearPlatformSplit -v
```

预期：2 passed。

- [ ] **Step 5: 提交**

```bash
git add py/routes/huguan_dashboard_routes.py py/tests/test_huguan_dashboard.py
git commit -m "fix(tt): 同步后不再清空换绑情况列（规则 3② 改 GG-only）"
```

---

## Task 6: `writeback_owner_channel` 支持传入完整文本

**Files:**
- Modify: `py/huguan_dashboard.py`（`writeback_owner_channel()`）
- Test: `py/tests/test_huguan_dashboard.py`

**Interfaces:**
- Consumes: 无
- Produces: `writeback_owner_channel(user_id, platform, account_id, new_owner_id, text=None)`
  —— `text` 为 `None` 时行为与改动前**逐字节一致**（GG 调用方不传）

- [ ] **Step 1: 写测试**

追加：

```python
class TestWritebackOwnerChannelText:
    def test_text_param_overrides_resolved_name(self, client, monkeypatch):
        """传了 text 就写 text，不再写解析出的新归属名。"""
        hg, uid = _create_user(client, "_wb_text", role="huguan", platform="tt")
        db = database.get_db()
        target = _seed(db, "_wb_text_t", "黎明", platform="tt")
        db.execute("INSERT OR REPLACE INTO config(key,value) VALUES(?,?)",
                   (f"huguan_dashboard_{uid}",
                    json.dumps({"tt": {"spreadsheet_id": "SS", "sheet_name": "S"}})))
        db.commit()
        db.close()
        captured = []
        _stub_sheets(monkeypatch, captured)
        import huguan_dashboard as hd
        hd.writeback_owner_channel(uid, "tt", "WB-TEXT", target, text="阿轩转黎明10.7")
        cells = [r["cells"] for c in captured for r in c["rows"] if "L" in r["cells"]]
        assert cells == [{"L": "阿轩转黎明10.7"}]

    def test_omitting_text_keeps_legacy_behavior(self, client, monkeypatch):
        """回归护栏：不传 text 时写解析出的新归属名（GG 走这条路）。"""
        hg, uid = _create_user(client, "_wb_legacy", role="huguan", platform="gg")
        db = database.get_db()
        target = _seed(db, "_wb_legacy_t", "李四")
        db.execute("INSERT OR REPLACE INTO config(key,value) VALUES(?,?)",
                   (f"huguan_dashboard_{uid}",
                    json.dumps({"gg": {"spreadsheet_id": "SS", "sheet_name": "S"}})))
        db.commit()
        db.close()
        captured = []
        _stub_sheets(monkeypatch, captured)
        import huguan_dashboard as hd
        hd.writeback_owner_channel(uid, "gg", "WB-LEGACY", target)
        cells = [r["cells"] for c in captured for r in c["rows"] if "H" in r["cells"]]
        assert cells == [{"H": "李四"}]
```

- [ ] **Step 2: 跑测试确认失败**

```bash
cd py && python -m pytest tests/test_huguan_dashboard.py::TestWritebackOwnerChannelText -v
```

预期：`test_text_param_overrides_resolved_name` FAIL（`TypeError: writeback_owner_channel()
got an unexpected keyword argument 'text'`）；`test_omitting_text_keeps_legacy_behavior` PASS
（现状即如此，是护栏）。

- [ ] **Step 3: 改签名与取值**

`py/huguan_dashboard.py` 的 `writeback_owner_channel()`：

签名改为：

```python
def writeback_owner_channel(user_id, platform, account_id, new_owner_id, text=None):
```

把原来的：

```python
        rows = owner_channel_cells([{"account_id": account_id}], platform, name)
```

改为：

```python
        # text 为 None 时写解析出的新归属名 —— GG 走这条路，行为与改动前逐字节一致。
        # TT 由调用方传入完整的换绑记录文本（「旧转新月.日」）：文本里含「变更前归属人」，
        # 那是 reassign 端点才知道的信息，在本函数里重新推断会引入第二次查询与不一致风险。
        value = text if text is not None else name
        rows = owner_channel_cells([{"account_id": account_id}], platform, value)
```

- [ ] **Step 4: 跑测试确认通过**

```bash
cd py && python -m pytest tests/test_huguan_dashboard.py::TestWritebackOwnerChannelText -v
```

预期：2 passed。

- [ ] **Step 5: 提交**

```bash
git add py/huguan_dashboard.py py/tests/test_huguan_dashboard.py
git commit -m "feat(tt): writeback_owner_channel 支持传入完整换绑文本"
```

**审查裁定（2026-10-06）**：早退由 `if not name: return` 改为
`if not name and text is None: return`，使 `text` 的写入与「归属人名能否解析」解耦；
另补 `text=""` 用例钉死 `is not None` 与 truthiness 的区别。GG 路径不受影响
（不传 `text` 时两式等价）。

---

## Task 7: reassign 生成并落库换绑记录

**Files:**
- Modify: `py/routes/tt_accounts_routes.py`（`reassign_account()`）
- Test: `py/tests/test_huguan_dashboard.py`（`TestTtReassignChannelWrite`）

**Interfaces:**
- Consumes: Task 1 的列、Task 6 的 `text` 参数
- Produces: reassign 后 `tt_accounts.owner_change_note == 写表的 L 值 == f"{旧}转{新}{M}.{D}"`

- [ ] **Step 1: 改既有测试并新增用例**

`TestTtReassignChannelWrite` 类内，把 `test_tt_reassign_writes_channel_column` 的末两行断言改为：

```python
        chan = [r for c in captured for r in c["rows"] if "L" in r["cells"]]
        assert chan, "reassign 应写换绑情况列 L"
        note = {r["account_id"]: r["cells"]["L"] for r in chan}["TTTRIG-CHAN"]
        assert note.startswith("旧归属转新归属"), f"格式应为「旧转新月.日」，实得 {note!r}"
        assert re.fullmatch(r"旧归属转新归属\d{1,2}\.\d{1,2}", note), note
        db = database.get_db()
        stored = db.execute(
            "SELECT owner_change_note FROM tt_accounts WHERE advertiser_id='TTTRIG-CHAN'"
        ).fetchone()["owner_change_note"]
        assert stored == note, "落库值与写表值必须是同一份文本"
        db.close()
```

在该类内新增：

```python
    def test_tt_reassign_with_null_old_owner_uses_placeholder(self, client, monkeypatch):
        """旧归属为空时文本以「未分配转」开头。"""
        hg, uid = _create_user(client, "_tt_ocn_null", role="huguan", platform="tt")
        db = database.get_db()
        db.execute("INSERT OR REPLACE INTO config(key,value) VALUES(?,?)",
                   (f"huguan_dashboard_{uid}",
                    json.dumps({"tt": {"spreadsheet_id": "SS", "sheet_name": "S"}})))
        target = _seed(db, "_tt_ocn_null_t", "黎明", platform="tt")
        aid = _seed_tt(db, "OCN-NULL", None)   # owner_id 为 NULL
        db.commit()
        db.close()
        captured = []
        _stub_sheets(monkeypatch, captured)
        resp = client.put(f"/api/tt/accounts/{aid}/reassign", headers=hg,
                          json={"owner_id": target})
        assert resp.status_code == 200
        chan = [r for c in captured for r in c["rows"] if "L" in r["cells"]]
        assert chan[0]["cells"]["L"].startswith("未分配转黎明")

    def test_tt_reassign_note_is_pure_ascii_month_day_no_padding(self, client, monkeypatch):
        """月日不补零、不用 strftime('%-m')（Windows 不支持该格式符）。"""
        hg, uid = _create_user(client, "_tt_ocn_fmt", role="huguan", platform="tt")
        db = database.get_db()
        db.execute("INSERT OR REPLACE INTO config(key,value) VALUES(?,?)",
                   (f"huguan_dashboard_{uid}",
                    json.dumps({"tt": {"spreadsheet_id": "SS", "sheet_name": "S"}})))
        old = _seed(db, "_tt_ocn_fmt_o", "阿轩", platform="tt")
        target = _seed(db, "_tt_ocn_fmt_t", "黎明", platform="tt")
        aid = _seed_tt(db, "OCN-FMT", old)
        db.commit()
        db.close()
        captured = []
        _stub_sheets(monkeypatch, captured)
        client.put(f"/api/tt/accounts/{aid}/reassign", headers=hg,
                   json={"owner_id": target})
        chan = [r for c in captured for r in c["rows"] if "L" in r["cells"]]
        note = chan[0]["cells"]["L"]
        import datetime as _dt
        now = _dt.datetime.now()
        assert note == f"阿轩转黎明{now.month}.{now.day}"
```

（`re` 已在文件顶部导入，无需补。）

- [ ] **Step 2: 跑测试确认失败**

```bash
cd py && python -m pytest tests/test_huguan_dashboard.py::TestTtReassignChannelWrite -v
```

预期：改造后的第 1 条 FAIL（当前写的是裸名字 `新归属`，且 DB 无该列值 → 断言落空）；
新增 2 条 FAIL（当前根本不写 `owner_change_note`）。

- [ ] **Step 3: 改写 reassign**

`py/routes/tt_accounts_routes.py` 的 `reassign_account()`：

在 `db.execute("UPDATE tt_accounts SET owner_id=?, updated_at=datetime('now','localtime') WHERE id=?", (target_owner, aid))`
之后、`db.commit()` **之前**插入：

```python
    # 换绑记录（2026-10-06 规格）：文本与稍后写表的 L 列值必须同源，故在此构造一次。
    # 月日不用 strftime("%-m") —— Windows 不支持该格式符。
    _old_label = (existing["display_name"] or existing["username"] or "未分配").strip()
    _new_label_row = db.execute(
        "SELECT COALESCE(NULLIF(display_name,''), username, '') AS n FROM users WHERE id=?",
        (target_owner,)).fetchone()
    _new_label = ((_new_label_row["n"] if _new_label_row else "") or str(target_owner)).strip()
    _now = datetime.datetime.now()
    owner_change_note = f"{_old_label}转{_new_label}{_now.month}.{_now.day}"
    db.execute("UPDATE tt_accounts SET owner_change_note=? WHERE id=?",
               (owner_change_note, aid))
```

把原来的：

```python
    hd.writeback_owner_channel(uid, "tt", existing["advertiser_id"], target_owner)
```

改为：

```python
    hd.writeback_owner_channel(uid, "tt", existing["advertiser_id"], target_owner,
                               text=owner_change_note)
```

**注意**：末尾返回文案用的 `old_owner` / `label` 变量保持原样不动（那是给用户看的消息，
与换绑记录文本是两回事，不得合并 —— 文案里没有格式要求，改动它会破坏既有接口契约）。

- [ ] **Step 4: 跑测试确认通过**

```bash
cd py && python -m pytest tests/test_huguan_dashboard.py::TestTtReassignChannelWrite -v
```

预期：3 passed。

- [ ] **Step 5: 跑 TT 路由回归**

```bash
cd py && python -m pytest tests/test_huguan_dashboard.py tests/test_tt_accounts.py tests/test_tt_routes.py -q
```

预期：全部通过。若 `TestTtReassignCrossUser` 有断言涉及 L 列内容，按新格式更新它。

- [ ] **Step 6: 提交**

```bash
git add py/routes/tt_accounts_routes.py py/tests/test_huguan_dashboard.py
git commit -m "feat(tt): reassign 自动写换绑记录（旧转新月.日）"
```

---

## Task 8: `TestOwnerChangeVia` 的 TT 断言随语义更新

> **已提前执行（2026-10-06，用户裁定）**：本任务的用例改写已前移到 Task 2 之后立即执行。
> 原因：Task 2 把 L 列改为 `owner_change_note` 后该用例即变红，而它并非依赖 Task 3 的分叉
> （TT 侧 `_owner_channel` 在 Task 2 之后已自然消失）。留到 Task 8 会让 Task 3–7 期间持续
> 红灯，掩盖真回归。本任务剩余内容仅为记录，不再重复执行。

**Files:**
- Test: `py/tests/test_huguan_dashboard.py`（`TestOwnerChangeVia::test_tt_uses_the_same_tokens_as_gg`）

**Interfaces:**
- Consumes: Task 3 的分叉（TT 不看 L 列）
- Produces: 无（纯测试更新）

- [ ] **Step 1: 改测试**

该用例原本断言「TT 的 L 列触发归属变更且 token 为 `owner_channel`」—— 新语义下 TT 不再有
`owner_channel` 这个触发来源。把 TT 部分改为：

```python
    def test_tt_only_owner_name_token_since_2026_10_06(self, client):
        """TT 归属只认「接户运营」列 ⇒ 只可能产出 `owner_name` token。

        L 列（换绑情况）自 2026-10-06 起是换绑记录文本，不参与归属判定，
        因此 TT 侧**不再存在** `owner_channel` 这个触发来源。
        GG 的 `owner_channel` token 仍由 test_gg_channel_column_gives_owner_channel_token 覆盖。
        """
        from huguan_dashboard import build_diff, parse_row
        db, u1, u2 = self._prepare(client)
        _seed_tt_account(db, "VIA-TT-1", u1)
        _seed_tt_account(db, "VIA-TT-2", u1)
        row_name = [""] * 13
        row_name[2], row_name[6] = "VIA-TT-1", "李四"          # 只填接户运营
        row_chan = [""] * 13
        row_chan[2], row_chan[6], row_chan[11] = "VIA-TT-2", "张三", "李四"
        diff = build_diff(db, [
            dict(parse_row(row_name, "tt"), row=2),
            dict(parse_row(row_chan, "tt"), row=3),
        ], "tt")
        by_aid = {i["account_id"]: i for i in diff["owner_changes"]}
        # VIA-TT-1：G=李四 ≠ 库内张三 → 变更，via=owner_name
        assert by_aid["VIA-TT-1"]["to_owner_id"] == u2
        assert by_aid["VIA-TT-1"]["via"] == "owner_name"
        # VIA-TT-2：G=张三 与库内一致，L 列不再参与 ⇒ 无归属变更
        assert "VIA-TT-2" not in by_aid
        db.close()
```

- [ ] **Step 2: 跑测试确认通过**

```bash
cd py && python -m pytest tests/test_huguan_dashboard.py::TestOwnerChangeVia -v
```

预期：3 passed（GG 两条 + TT 一条）。

- [ ] **Step 3: 全量跑户管看板测试**

```bash
cd py && python -m pytest tests/test_huguan_dashboard.py -q
```

预期：全部通过。任何 FAIL 都指向本次改动遗漏的分叉点，逐个修。

- [ ] **Step 4: 提交**

```bash
git add py/tests/test_huguan_dashboard.py
git commit -m "test(tt): via token 用例随 TT 新归属语义更新"
```

---

## Task 9: 前端加只读「换绑情况」列

**Files:**
- Modify: `frontend/src/views/tt/TtAccountPanel.vue`

**Interfaces:**
- Consumes: `GET /api/tt/accounts/list` 返回体里的 `owner_change_note`（`SELECT a.*` 自动带出）
- Produces: 户管可见的只读列

**前置**：这是只读展示列、无新交互，**不需要** `/frontend-design`。

- [ ] **Step 1: 加列**

在 `frontend/src/views/tt/TtAccountPanel.vue` 中，找到既有的「户归属」列
（`<el-table-column v-if="authStore.isHuguan" label="户归属" width="160" align="center">`），
在它**之后**插入：

```vue
        <el-table-column v-if="authStore.isHuguan" prop="owner_change_note"
                         label="换绑情况" min-width="160" show-overflow-tooltip />
```

- [ ] **Step 2: 构建验证**

```bash
cd frontend && npm run build
```

预期：构建成功，无 Vue 模板编译错误。

- [ ] **Step 3: 人工验收**

以户管账号登录，打开 TT 账户面板。预期：
- 表头出现「换绑情况」列，紧挨「户归属」
- 值形如 `阿轩转黎明10.7`；未发生过换绑的账户该格为空
- 以非户管账号（投手）登录时，三列（户归属 / 换绑情况）都不显示

- [ ] **Step 4: 提交**

```bash
git add frontend/src/views/tt/TtAccountPanel.vue
git commit -m "feat(tt): 账户面板新增只读「换绑情况」列（仅户管可见）"
```

---

## 完成后的收尾

- [ ] **提醒用户 `npm run build`**（前端改动后其他人才能看到；本计划 Task 9 已含此步）
- [ ] **提醒用户重启 Flask 服务**（后端 `py/*.py` 已改，需重启生效）
- [ ] **提醒用户提交 git**
- [ ] **按项目规矩调用 `/code-review`**：本次触及归属判定与按平台分叉的鉴权相邻逻辑，建议跑一轮

---

## Self-Review 记录

**Spec 覆盖检查**（对照 `2026-10-06-tt-owner-change-note-design.md`）：

| Spec 章节 | 对应任务 |
|-----------|----------|
| §3.1 新增数据库列 | Task 1 |
| §3.2 归属判定按平台分叉 | Task 3 |
| §3.3 列定义改为普通文本字段 | Task 2 |
| §3.4 读回按表覆盖 | Task 4 |
| §3.5 系统 UI 改归属时写 L | Task 6（函数支持）+ Task 7（调用方） |
| §3.6 取消 TT 同步后清空 L | Task 5 |
| §3.7 前端展示 | Task 9 |
| §6 测试要点 #1-#3 | Task 3 |
| §6 测试要点 #4-#6 | Task 4 |
| §6 测试要点 #7 | Task 5 |
| §6 测试要点 #8 | Task 5（GG 护栏） |
| §6 测试要点 #9-#10 | Task 7 |
| §6 测试要点 #11 | Task 2（`writable=False` 使 L 不进 cells） |
| §6 测试要点 #12 | Task 7（月日格式） |

**类型一致性**：`effective_owner_name(parsed, platform)` 在 Task 3 定义并改调用点；
`writeback_owner_channel(..., text=None)` 在 Task 6 定义、Task 7 消费；
`owner_change_note` 在 Task 1 建列、Task 2 定义键名、Task 4/6/7 读写。三处命名一致。

**已知未覆盖**：spec §5 的三条已知后果属产品决策记录，无需测试。
