# TT 备注（`remark`）跨看板同步优先级 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让 `tt_accounts.remark` 在「户管看板」与投手「我的看板」之间不再互相静默覆盖 —— 首次入库时投手看板优先，此后投手权威永久，并补上「系统 → 投手看板」这条原本不存在的推送通路。

**Architecture:** 方案 A（在现有同步链路上打补丁）。**不新增表、不新增数据库列**。权威判定天然映射到 `build_diff` 的 `to_create`（首次入库）/ `to_update`（此后）两个分支；新建一个面向**投手看板**的推送函数（既有 `push_rows` 只面向户管看板）。

**Tech Stack:** Python 3.11 / Flask / SQLite(WAL) / pytest；前端 Vue 3 + Element Plus。

**Spec:** `docs/superpowers/specs/2026-10-06-tt-remark-sync-precedence-design.md`

## Global Constraints

- **仅 TT**。GG / FB 的行为、文案、列定义**逐字节不得变化**。
- **纯增量原则**：不改动既有功能的代码逻辑；新逻辑按平台分叉接入。
- **注释用中文**，与文件既有风格一致（说明「为什么」而非「是什么」）。
- ⚠️ **本仓库有另一个并行会话在改 `py/` 并往 master 提交。**
  `git add` 只加本任务明确列出的文件，**绝对禁止 `git add -A` / `git add .`**。
  提交前跑 `git status --short` 确认暂存区干净。
- 测试运行方式固定：`cd py && python -m pytest tests/<file>::<Class>::<test> -v`
- ⚠️ **`_PLAIN_TEXT_FIELDS["tt"]` 同时服务 `to_create` 与 `to_update`（共用 `_collect_updates`）。
  本次刻意【不改】它** —— 见 Task 1 的理由。改它会连带破坏「首次入库读户管 M 列」那一支。

## ⚠️ 相对 spec 的一处勘误（实现前必读）

spec §3.2 写「sheet 名取 `tags.tt_sheet_mappings` 里 `{owner_id}.my_dashboard`」—— **这是错的**。
实测（2026-10-06）：

| 存放位置 | 内容 |
|----------|------|
| `tags.tt_sheet_id` | 全局表 ID（`1bQWVqCMtdEyxasNiMvtzKrnp0NVeeBnzEpF6-iPj74w`） |
| `tags.tt_sheet_mappings` | `{"recycle":…, "recharge":…, "accounts":…}` —— **不含 `my_dashboard`** |
| `config.tt_sheet_mappings_{uid}` | 每投手私有：`{"my_dashboard": "黎明账户看板", …}` |

正确的解析顺序（**必须镜像 `py/routes/tt_accounts_routes.py` 的 `sync_from_sheet()`**）：

```
sheet_id  = tags.tt_sheet_id
sheet_name = tags.tt_sheet_mappings.my_dashboard  或  "我的看板"   # 全局兜底
若 config.tt_sheet_mappings_{owner_id}.my_dashboard 非空 → 用它覆盖   # 投手私有
```

现存配置：uid 23/25/28/30/31 有 `my_dashboard`；**29/32/33 没有** —— 他们走全局兜底，
若兜底 sheet 在该表里不存在，读表会返回空 → 按「户管赢」降级（spec §5 已知后果 3）。

**Task 2 完成后，请把本节内容回写进 spec §3.2**（标为勘误）。

---

## File Structure

| 文件 | 职责 | 本计划改动 |
|------|------|-----------|
| `py/huguan_dashboard.py` | 户管看板双向同步的纯逻辑层 | `to_update` 剔除 remark、新增读投手表与推投手表两个函数、`apply_diff` 集成 |
| `py/routes/huguan_dashboard_routes.py` | 户管看板 HTTP 层 | `dashboard_sync()` 消费两个新返回键 |
| `py/routes/tt_accounts_routes.py` | TT 账户 HTTP 层 | `update_account()` 改备注后补两个推送 |
| `frontend/src/views/tt/TtAccountPanel.vue` | TT 账户面板 | 加可内联编辑的「备注」列 |
| `py/tests/test_huguan_dashboard.py` | 同步逻辑测试 | 新增用例 |

---

## Task 1: 已存在账户：`to_update` 剔除 `remark`

**Files:**
- Modify: `py/huguan_dashboard.py`（`build_diff()` 内 `changed` 的过滤处）
- Test: `py/tests/test_huguan_dashboard.py`

**Interfaces:**
- Consumes: 无
- Produces: 已存在账户的 `to_update[].fields` / `clears` 中**永不出现** `remark`

- [ ] **Step 1: 写失败测试**

追加到 `py/tests/test_huguan_dashboard.py` 末尾：

```python
class TestRemarkNotPulledForExistingAccounts:
    """户管看板 M 列的改动不再进系统（2026-10-06 规格：投手权威永久）。"""

    def _prepare(self, client):
        db = database.get_db()
        u1 = _seed(db, "_rmk_a", "张三")
        return db, u1

    def _tt_row_with_remark(self, aid, remark):
        row = [""] * 13
        row[2], row[6], row[12] = aid, "张三", remark   # C 账户ID / G 接户运营 / M 产品信息
        return row

    def test_existing_account_remark_change_is_ignored(self, client):
        from huguan_dashboard import build_diff, parse_row
        db, u1 = self._prepare(client)
        _seed_tt_account(db, "RMK-EX", u1)
        db.execute("UPDATE tt_accounts SET remark='投手写的' WHERE advertiser_id='RMK-EX'")
        db.commit()
        row = self._tt_row_with_remark("RMK-EX", "户管改的")
        diff = build_diff(db, [dict(parse_row(row, "tt"), row=2)], "tt")
        # 该行可能因别的字段进 to_update，但 remark 必须不在其中
        for item in diff["to_update"]:
            assert "remark" not in item["fields"], "已存在账户不得从表里更新 remark"
        db.close()

    def test_existing_account_blank_remark_does_not_clear_nor_report(self, client):
        """表里把 M 列清空，既不清系统里的值，也不进 clears（旧隐患已根治）。"""
        from huguan_dashboard import build_diff, parse_row
        db, u1 = self._prepare(client)
        _seed_tt_account(db, "RMK-CLR", u1)
        db.execute("UPDATE tt_accounts SET remark='投手的备注' WHERE advertiser_id='RMK-CLR'")
        db.commit()
        row = self._tt_row_with_remark("RMK-CLR", "")      # M 列留空
        diff = build_diff(db, [dict(parse_row(row, "tt"), row=2)], "tt")
        for item in diff["to_update"]:
            assert "remark" not in item["fields"]
            assert "remark" not in item["clears"]
        stored = db.execute(
            "SELECT remark FROM tt_accounts WHERE advertiser_id='RMK-CLR'").fetchone()["remark"]
        assert stored == "投手的备注", "表里空值不得清掉系统里的备注"
        db.close()

    def test_new_account_still_carries_remark(self, client):
        """回归护栏：to_create 分支必须仍能收到户管 M 列的值（Task 3 要用）。"""
        from huguan_dashboard import build_diff, parse_row
        db, u1 = self._prepare(client)
        row = self._tt_row_with_remark("RMK-NEW", "户管填的")
        diff = build_diff(db, [dict(parse_row(row, "tt"), row=2)], "tt")
        item = diff["to_create"][0]
        assert item["db_values"]["remark"] == "户管填的"
        db.close()
```

- [ ] **Step 2: 跑测试确认失败**

```bash
cd py && python -m pytest tests/test_huguan_dashboard.py::TestRemarkNotPulledForExistingAccounts -v
```

预期：前两条 FAIL（当前 `remark` 会进 `to_update` 的 `fields`）；第三条 PASS（现状即此，是护栏）。

- [ ] **Step 3: 加剔除条件**

`py/huguan_dashboard.py` 的 `build_diff()` 内：

```python
        changed = {k: v for k, v in fields.items()
                   if not _same_as_existing(db, platform, existing, k, v)}
```

改为：

```python
        # TT 的 remark 不走「按表覆盖」（2026-10-06 规格）：投手权威永久，
        # 户管看板 M 列的改动不再进系统。空值也因此不会进 clears，
        # 根治了原先「户管 M 列空着就清掉投手备注」的隐患。
        # 注意：只剔 to_update —— to_create（首次入库）仍要用户管 M 列的值。
        changed = {k: v for k, v in fields.items()
                   if not _same_as_existing(db, platform, existing, k, v)
                   and not (platform == "tt" and k == "remark")}
```

**不要**改 `_PLAIN_TEXT_FIELDS` —— 它与 `to_create` 共用，改掉会让 `test_new_account_still_carries_remark` 变红。

- [ ] **Step 4: 跑测试确认通过**

```bash
cd py && python -m pytest tests/test_huguan_dashboard.py::TestRemarkNotPulledForExistingAccounts -v
cd py && python -m pytest tests/test_huguan_dashboard.py -q
```

预期：3 passed；全文件全绿（基线 197 passed / 0 failed）。

- [ ] **Step 5: 提交**

```bash
git add py/huguan_dashboard.py py/tests/test_huguan_dashboard.py
git commit -m "feat(tt): 已存在账户不再从户管看板同步 remark（投手权威永久）"
```

---

## Task 2: 读投手看板的备注映射

**Files:**
- Modify: `py/huguan_dashboard.py`（新增只读函数）
- Test: `py/tests/test_huguan_dashboard.py`

**Interfaces:**
- Consumes: 无
- Produces: `read_operator_remark_map(db, owner_id: int) -> dict[str, str]`
  —— 返回 `{广告账户ID: J 列备注}`；配置缺失 / 读表失败一律返回 `{}`

- [ ] **Step 1: 写失败测试**

追加：

```python
class TestReadOperatorRemarkMap:
    """读投手「我的看板」的 账户ID → J 列备注 映射。"""

    def _setup(self, client, uid_suffix, dashboard_name, sheet_id="SS-TT"):
        db = database.get_db()
        u = _seed(db, f"_orm_{uid_suffix}", f"投手{uid_suffix}", platform="tt")
        db.execute("INSERT OR REPLACE INTO tags(key,value) VALUES('tt_sheet_id',?)", (sheet_id,))
        if dashboard_name:
            db.execute("INSERT OR REPLACE INTO config(key,value) VALUES(?,?)",
                       (f"tt_sheet_mappings_{u}", json.dumps({"my_dashboard": dashboard_name})))
        db.commit()
        db.close()
        return u

    def test_builds_map_from_d_column_keyed_rows(self, client, monkeypatch):
        import google_sheets_service as gs
        u = self._setup(client, "a", "黎明账户看板")
        monkeypatch.setattr(gs, "build_service", lambda path: object())
        monkeypatch.setattr(gs, "read_sheet_values", lambda *a, **k: [
            ["运营", "入库时间", "是否回收", "账户ID", "BC", "国家", "接户运营",
             "时区", "状态", "备注"],                       # 表头，应被跳过
            ["黎明", "", "", "AID-1", "", "", "", "", "", "投手备注1"],
            ["黎明", "", "", "AID-2", "", "", "", "", "", ""],
        ])
        import huguan_dashboard as hd
        db = database.get_db()
        got = hd.read_operator_remark_map(db, u)
        db.close()
        assert got == {"AID-1": "投手备注1", "AID-2": ""}

    def test_missing_sheet_id_returns_empty(self, client, monkeypatch):
        u = self._setup(client, "b", "看板B", sheet_id="")
        import huguan_dashboard as hd
        db = database.get_db()
        assert hd.read_operator_remark_map(db, u) == {}
        db.close()

    def test_read_failure_returns_empty_not_raise(self, client, monkeypatch):
        """读不到投手看板不得阻断户管同步 —— 绝不抛异常。"""
        import google_sheets_service as gs
        u = self._setup(client, "c", "看板C")

        def _boom(*a, **k):
            raise RuntimeError("网络炸了")

        monkeypatch.setattr(gs, "build_service", lambda path: object())
        monkeypatch.setattr(gs, "read_sheet_values", _boom)
        import huguan_dashboard as hd
        db = database.get_db()
        assert hd.read_operator_remark_map(db, u) == {}
        db.close()

    def test_operator_without_private_config_falls_back_to_global(self, client, monkeypatch):
        """投手没配私有 my_dashboard 时用全局 tags 兜底，而不是直接放弃。"""
        import google_sheets_service as gs
        db = database.get_db()
        u = _seed(db, "_orm_d", "投手d", platform="tt")
        db.execute("INSERT OR REPLACE INTO tags(key,value) VALUES('tt_sheet_id','SS-TT')")
        db.execute("INSERT OR REPLACE INTO tags(key,value) VALUES('tt_sheet_mappings',?)",
                   (json.dumps({"my_dashboard": "全局看板"}),))
        db.commit()
        db.close()
        seen = {}

        def _capture(service, spreadsheet_id, sheet_name, rng):
            seen["sheet_name"] = sheet_name
            return []

        monkeypatch.setattr(gs, "build_service", lambda path: object())
        monkeypatch.setattr(gs, "read_sheet_values", _capture)
        import huguan_dashboard as hd
        db = database.get_db()
        hd.read_operator_remark_map(db, u)
        db.close()
        assert seen["sheet_name"] == "全局看板"
```

- [ ] **Step 2: 跑测试确认失败**

```bash
cd py && python -m pytest tests/test_huguan_dashboard.py::TestReadOperatorRemarkMap -v
```

预期：四条全 FAIL（`AttributeError: module 'huguan_dashboard' has no attribute 'read_operator_remark_map'`）。

- [ ] **Step 3: 实现**

在 `py/huguan_dashboard.py` 中，紧挨 `push_rows()` 之前（或之后）新增：

```python
def _operator_dashboard_name(db, owner_id: int) -> str:
    """解析某投手「我的看板」的 sheet 名。

    与 tt_accounts_routes.sync_from_sheet() 同源：先取全局 tags 兜底，
    再被 config 表里的投手私有配置覆盖。两处必须保持一致，否则读与写会对着
    不同的 tab 操作。
    """
    name = ""
    row = db.execute("SELECT value FROM tags WHERE key='tt_sheet_mappings'").fetchone()
    if row and row["value"]:
        try:
            loaded = json.loads(row["value"])
            if isinstance(loaded, dict):
                name = (loaded.get("my_dashboard") or "").strip()
        except Exception:
            pass
    if not name:
        name = "我的看板"
    priv = db.execute("SELECT value FROM config WHERE key=?",
                      (f"tt_sheet_mappings_{owner_id}",)).fetchone()
    if priv and priv["value"]:
        try:
            loaded_priv = json.loads(priv["value"])
            if isinstance(loaded_priv, dict) and (loaded_priv.get("my_dashboard") or "").strip():
                name = loaded_priv["my_dashboard"].strip()
        except Exception:
            pass
    return name


def read_operator_remark_map(db, owner_id: int) -> dict:
    """读该投手「我的看板」的 广告账户ID → J 列备注 映射。

    投手未配看板、全局未配 tt_sheet_id、或读表失败 —— 一律返回空 dict，
    由调用方按「户管赢」降级。读不到投手看板不应阻断户管同步，故本函数**绝不抛异常**。
    """
    import logging
    log = logging.getLogger("gg-server")
    try:
        row = db.execute("SELECT value FROM tags WHERE key='tt_sheet_id'").fetchone()
        sheet_id = (row["value"] if row and row["value"] else "").strip()
        if not sheet_id:
            return {}
        sheet_name = _operator_dashboard_name(db, owner_id)

        import google_sheets_service as gs
        from main import _GOOGLE_SHEETS_CONFIG
        service = gs.build_service(_GOOGLE_SHEETS_CONFIG["credentials_path"])
        rows = gs.read_sheet_values(service, sheet_id, sheet_name, "A:J")
        if not rows:
            return {}
        rows = rows[1:]   # 跳过表头
        out = {}
        for r in rows:
            # D 列（下标 3）是账户ID，J 列（下标 9）是备注
            aid = (r[3] if len(r) > 3 else "").strip().lstrip("'").strip()
            if not aid or aid in out:
                continue
            out[aid] = (r[9] if len(r) > 9 else "").strip()
        return out
    except Exception as e:
        log.warning("读投手看板备注失败（按户管赢降级）: %s", e)
        return {}
```

**注意**：`json` 与 `main` 的导入位置 —— `py/huguan_dashboard.py` 顶部已有 `import json`；
`main` 用函数内导入（与 `push_rows` 同法，避免模块级循环依赖）。

- [ ] **Step 4: 跑测试确认通过**

```bash
cd py && python -m pytest tests/test_huguan_dashboard.py::TestReadOperatorRemarkMap -v
```

预期：4 passed。

- [ ] **Step 5: 把勘误回写进 spec**

在 `docs/superpowers/specs/2026-10-06-tt-remark-sync-precedence-design.md` 的 §3.2 里，
把「sheet 名取 `tags.tt_sheet_mappings` 里 `{owner_id}.my_dashboard`」那一句改为本文档
开头「相对 spec 的一处勘误」表格所述的正确来源（`config.tt_sheet_mappings_{uid}.my_dashboard`
优先，`tags.tt_sheet_mappings.my_dashboard` 兜底）。

- [ ] **Step 6: 提交**

```bash
git add py/huguan_dashboard.py py/tests/test_huguan_dashboard.py docs/superpowers/specs/2026-10-06-tt-remark-sync-precedence-design.md
git commit -m "feat(tt): 新增读投手看板备注映射（含配置解析勘误回写 spec）"
```

---

## Task 3: `apply_diff` 首次入库时应用投手优先

**Files:**
- Modify: `py/huguan_dashboard.py`（`apply_diff()` 的 `to_create` 循环 + 返回值）
- Test: `py/tests/test_huguan_dashboard.py`

**Interfaces:**
- Consumes: Task 2 的 `read_operator_remark_map(db, owner_id)`
- Produces: `apply_diff` 返回 dict 新增两个键
  - `remark_m_writeback`: `[{"account_id": str, "value": str}]`（投手赢 → 回写户管看板 M 列）
  - `remark_operator_push`: `[{"owner_id": int, "account_id": str, "value": str}]`（户管赢 → 推投手看板 J 列）
  - `platform != "tt"` 时两者恒为空列表

- [ ] **Step 1: 写失败测试**

追加：

```python
class TestApplyDiffRemarkPrecedence:
    """首次入库时投手看板 J 列优先（2026-10-06 规格）。"""

    def _prepare(self, client):
        db = database.get_db()
        u_op = _seed(db, "_adrp_op", "黎明", platform="tt")
        db.execute("INSERT OR REPLACE INTO tags(key,value) VALUES('tt_sheet_id','SS-TT')")
        db.execute("INSERT OR REPLACE INTO config(key,value) VALUES(?,?)",
                   (f"tt_sheet_mappings_{u_op}", json.dumps({"my_dashboard": "黎明账户看板"})))
        db.commit()
        return db, u_op

    def _arm_read(self, monkeypatch, mapping):
        import google_sheets_service as gs
        monkeypatch.setattr(gs, "build_service", lambda path: object())
        monkeypatch.setattr(gs, "read_sheet_values",
                            lambda *a, **k: [["运营", "", "", "账户ID"],
                                             *[["黎明", "", "", aid, "", "", "", "", "", v]
                                               for aid, v in mapping.items()]])

    def _diff_one(self, db, aid, owner_name, remark):
        from huguan_dashboard import build_diff, parse_row
        row = [""] * 13
        row[2], row[6], row[12] = aid, owner_name, remark
        return build_diff(db, [dict(parse_row(row, "tt"), row=2)], "tt")

    def test_operator_value_wins_on_first_ingest(self, client, monkeypatch):
        db, u_op = self._prepare(client)
        self._arm_read(monkeypatch, {"ADRP-1": "投手填的"})
        diff = self._diff_one(db, "ADRP-1", "黎明", "户管填的")
        res = apply_diff(db, diff, "tt", {"create": ["ADRP-1"]}, user_id=1)
        stored = db.execute(
            "SELECT remark FROM tt_accounts WHERE advertiser_id='ADRP-1'").fetchone()["remark"]
        assert stored == "投手填的", "投手看板有值时投手赢"
        assert res["remark_m_writeback"] == [{"account_id": "ADRP-1", "value": "投手填的"}]
        assert res["remark_operator_push"] == []
        db.close()

    def test_supervisor_value_wins_when_operator_blank(self, client, monkeypatch):
        db, u_op = self._prepare(client)
        self._arm_read(monkeypatch, {"ADRP-2": ""})
        diff = self._diff_one(db, "ADRP-2", "黎明", "户管填的")
        res = apply_diff(db, diff, "tt", {"create": ["ADRP-2"]}, user_id=1)
        stored = db.execute(
            "SELECT remark FROM tt_accounts WHERE advertiser_id='ADRP-2'").fetchone()["remark"]
        assert stored == "户管填的"
        assert res["remark_m_writeback"] == []
        assert res["remark_operator_push"] == [
            {"owner_id": u_op, "account_id": "ADRP-2", "value": "户管填的"}]
        db.close()

    def test_operator_sheet_read_once_per_owner(self, client, monkeypatch):
        """同一投手的多个新建账户只读一次表。"""
        import google_sheets_service as gs
        db, u_op = self._prepare(client)
        calls = []

        def _count(service, spreadsheet_id, sheet_name, rng):
            calls.append(sheet_name)
            return [["运营", "", "", "账户ID"],
                    ["黎明", "", "", "ADRP-3", "", "", "", "", "", "投手3"],
                    ["黎明", "", "", "ADRP-4", "", "", "", "", "", "投手4"]]

        monkeypatch.setattr(gs, "build_service", lambda path: object())
        monkeypatch.setattr(gs, "read_sheet_values", _count)
        d3 = self._diff_one(db, "ADRP-3", "黎明", "户管3")
        d4 = self._diff_one(db, "ADRP-4", "黎明", "户管4")
        # 两个账户必须在**同一次** apply_diff 调用里创建，才能共享缓存
        diff = {"to_create": d3["to_create"] + d4["to_create"], "to_update": [],
                "owner_changes": [], "to_skip": [], "warnings": [], "summary": {}}
        apply_diff(db, diff, "tt", {"create": ["ADRP-3", "ADRP-4"]}, user_id=1)
        assert len(calls) == 1, f"应在一次 apply_diff 内只读一次投手表，实读 {len(calls)} 次"
        db.close()

    def test_gg_produces_no_remark_keys(self, client, monkeypatch):
        """回归护栏：GG 不得产生这两个键的内容。"""
        db = database.get_db()
        u1 = _seed(db, "_adrp_gg", "张三")
        row = ["", "", "ADRP-GG", "MCC-A", "", "", "张三", ""]
        from huguan_dashboard import build_diff, parse_row
        diff = build_diff(db, [dict(parse_row(row, "gg"), row=2)], "gg")
        res = apply_diff(db, diff, "gg", {"create": ["ADRP-GG"]}, user_id=1)
        assert res["remark_m_writeback"] == []
        assert res["remark_operator_push"] == []
        db.close()
```

在文件顶部的 import 区确认已 `from huguan_dashboard import ... apply_diff`（若测试类未导入，
在各方法内按上面写法局部导入亦可）。

- [ ] **Step 2: 跑测试确认失败**

```bash
cd py && python -m pytest tests/test_huguan_dashboard.py::TestApplyDiffRemarkPrecedence -v
```

预期：前三条 FAIL（返回 dict 里没有 `remark_m_writeback` → KeyError）；第四条 FAIL 同理。

- [ ] **Step 3: 实现**

`py/huguan_dashboard.py` 的 `apply_diff()`：

**(a) 初始化**（紧挨 `applied_owner_rows = []` 之后）：

```python
    # TT 备注首次对齐的产物（2026-10-06 规格）：由路由层 pop 后消费。
    remark_m_writeback = []
    remark_operator_push = []
    # 本次调用内的投手看板备注缓存 {owner_id: {aid: remark}}。
    # 局部而非模块级 —— 表内容随时可变，跨请求缓存会让户管看到过期值。
    _operator_remark_cache = {}
```

**(b) `to_create` 循环内**，在 `src = dict(item.get("db_values") or {})` 之后、
拼 `INSERT` 之前插入：

```python
            if platform == "tt" and "remark" in src:
                _op_id = item.get("owner_id")
                if _op_id is not None and _op_id not in _operator_remark_cache:
                    _operator_remark_cache[_op_id] = read_operator_remark_map(db, _op_id)
                _op_value = (_operator_remark_cache.get(_op_id) or {}).get(
                    item["account_id"], "").strip() if _op_id is not None else ""
                if _op_value:
                    src["remark"] = _op_value            # 投手赢
                    remark_m_writeback.append({"account_id": item["account_id"],
                                               "value": _op_value})
                else:
                    remark_operator_push.append({"owner_id": _op_id,
                                                 "account_id": item["account_id"],
                                                 "value": (src.get("remark") or "").strip()})
```

**(c) 返回值**加上两个键：

```python
    return {"created": created, "updated": updated, "owner_changed": owner_changed,
            "applied_owner_rows": applied_owner_rows, "not_applied": not_applied,
            "remark_m_writeback": remark_m_writeback,
            "remark_operator_push": remark_operator_push,
            "errors": errors}
```

- [ ] **Step 4: 跑测试确认通过**

```bash
cd py && python -m pytest tests/test_huguan_dashboard.py::TestApplyDiffRemarkPrecedence -v
cd py && python -m pytest tests/test_huguan_dashboard.py -q
```

预期：4 passed；全文件全绿。

- [ ] **Step 5: 提交**

```bash
git add py/huguan_dashboard.py py/tests/test_huguan_dashboard.py
git commit -m "feat(tt): 首次入库按投手看板优先对齐 remark"
```

---

## Task 4: 推送通路 + 路由层消费

**Files:**
- Modify: `py/huguan_dashboard.py`（新增推送函数）
- Modify: `py/routes/huguan_dashboard_routes.py`（`dashboard_sync()` 消费两个键）
- Test: `py/tests/test_huguan_dashboard.py`

**Interfaces:**
- Consumes: Task 3 的两个返回键
- Produces: `push_remark_to_operator_dashboard(owner_id, account_id, value) -> None`
  —— 面向**投手看板** J 列（`key_col="D"`），绝不抛异常

- [ ] **Step 1: 写失败测试**

追加：

```python
class TestRemarkPushPath:
    """系统 → 投手看板 J 列的推送通路（本次新建）。"""

    def test_push_writes_j_column_keyed_by_d(self, client, monkeypatch):
        import google_sheets_service as gs
        db = database.get_db()
        u_op = _seed(db, "_rpp_op", "黎明", platform="tt")
        db.execute("INSERT OR REPLACE INTO tags(key,value) VALUES('tt_sheet_id','SS-TT')")
        db.execute("INSERT OR REPLACE INTO config(key,value) VALUES(?,?)",
                   (f"tt_sheet_mappings_{u_op}", json.dumps({"my_dashboard": "黎明账户看板"})))
        db.commit()
        db.close()
        captured = []

        def _fake(service, spreadsheet_id, sheet_name, rows, key_col="C"):
            captured.append({"sheet_name": sheet_name, "key_col": key_col, "rows": rows})
            return {"updated": len(rows), "not_found": []}

        monkeypatch.setattr(gs, "build_service", lambda path: object())
        monkeypatch.setattr(gs, "update_rows_by_account_id", _fake)
        import main as m
        monkeypatch.setattr(m, "_sync_sheets_background", lambda fn, on_fail: fn())
        import huguan_dashboard as hd
        hd.push_remark_to_operator_dashboard(u_op, "RPP-1", "投手备注")
        assert len(captured) == 1
        assert captured[0]["sheet_name"] == "黎明账户看板"
        assert captured[0]["key_col"] == "D", "投手看板账户ID在 D 列"
        assert captured[0]["rows"] == [{"account_id": "RPP-1", "cells": {"J": "投手备注"}}]

    def test_push_without_sheet_id_is_silent_noop(self, client, monkeypatch):
        import google_sheets_service as gs
        db = database.get_db()
        u_op = _seed(db, "_rpp_no", "黎明2", platform="tt")
        db.execute("INSERT OR REPLACE INTO tags(key,value) VALUES('tt_sheet_id','')")
        db.commit()
        db.close()
        called = []
        monkeypatch.setattr(gs, "update_rows_by_account_id",
                            lambda *a, **k: called.append(1))
        import huguan_dashboard as hd
        hd.push_remark_to_operator_dashboard(u_op, "RPP-2", "x")
        assert called == []
```

- [ ] **Step 2: 跑测试确认失败**

```bash
cd py && python -m pytest tests/test_huguan_dashboard.py::TestRemarkPushPath -v
```

预期：两条 FAIL（函数不存在）。

- [ ] **Step 3: 实现推送函数**

在 `py/huguan_dashboard.py` 的 `push_rows()` 之后新增：

```python
def push_remark_to_operator_dashboard(owner_id: int, account_id: str, value: str) -> None:
    """把备注写进该投手「我的看板」的 J 列（按 D 列定位行）。

    与 push_rows 的区别：push_rows 面向**户管看板**（配置来自 huguan_dashboard_{uid}），
    本函数面向**投手看板**（配置来自 tags.tt_sheet_id + tt_sheet_mappings）。

    投手未配看板 / 全局未配 tt_sheet_id → 静默返回。
    绝不抛异常（与 writeback_rows 同契约：回写失败不得影响主流程）。
    """
    try:
        db = _open_db()
        try:
            row = db.execute("SELECT value FROM tags WHERE key='tt_sheet_id'").fetchone()
            sheet_id = (row["value"] if row and row["value"] else "").strip()
            if not sheet_id:
                return
            sheet_name = _operator_dashboard_name(db, owner_id)
        finally:
            db.close()

        rows = [{"account_id": account_id, "cells": {"J": value}}]

        def _do():
            import google_sheets_service as gs
            from main import _GOOGLE_SHEETS_CONFIG
            service = gs.build_service(_GOOGLE_SHEETS_CONFIG["credentials_path"])
            # 投手看板的账户ID在 D 列（户管看板在 C 列），故必须显式传 key_col。
            gs.update_rows_by_account_id(service, sheet_id, sheet_name, rows, key_col="D")

        from main import _sync_sheets_background
        _sync_sheets_background(
            _do, lambda s, e: log.warning("投手看板备注回写失败: %s", e) if e else None)
    except Exception as e:
        log.warning("投手看板备注回写触发失败: %s", e)
```

（`log` 与 `_open_db` 是本模块既有名字，直接用。）

- [ ] **Step 4: 路由层消费**

`py/routes/huguan_dashboard_routes.py` 的 `dashboard_sync()` 中，
在既有 `applied = result.pop("applied_owner_rows", [])` **之后**加：

```python
        # TT 备注首次对齐的两个写回（2026-10-06 规格）。与 applied_owner_rows 同法：
        # 先从 result 摘掉，再发起后台写回 —— 只写单列，绝不整行推送。
        m_writeback = result.pop("remark_m_writeback", [])
        if m_writeback:
            _write_background(conf, [{"account_id": r["account_id"],
                                      "cells": {"M": r["value"]}} for r in m_writeback])
        for r in result.pop("remark_operator_push", []):
            hd.push_remark_to_operator_dashboard(r["owner_id"], r["account_id"], r["value"])
```

- [ ] **Step 5: 跑测试确认通过**

```bash
cd py && python -m pytest tests/test_huguan_dashboard.py::TestRemarkPushPath -v
cd py && python -m pytest tests/test_huguan_dashboard.py -q
```

预期：2 passed；全文件全绿。

- [ ] **Step 6: 加一条端到端用例**

追加到 `TestRemarkPushPath` 类里，锁死「同步接口真的把两个写回发出去了」：

```python
    def test_sync_endpoint_emits_remark_writebacks(self, client, monkeypatch):
        """走真实同步端点：投手赢 → 只回写户管 M；户管赢 → 只推投手 J。"""
        import google_sheets_service as gs
        hg, uid = _create_user(client, "_rpp_e2e", role="huguan", platform="tt")
        db = database.get_db()
        op = _seed(db, "_rpp_e2e_op", "黎明", platform="tt")
        db.execute("INSERT OR REPLACE INTO config(key,value) VALUES(?,?)",
                   (f"huguan_dashboard_{uid}",
                    json.dumps({"tt": {"spreadsheet_id": "HG-SS", "sheet_name": "S"}})))
        db.execute("INSERT OR REPLACE INTO tags(key,value) VALUES('tt_sheet_id','OP-SS')")
        db.execute("INSERT OR REPLACE INTO config(key,value) VALUES(?,?)",
                   (f"tt_sheet_mappings_{op}", json.dumps({"my_dashboard": "黎明账户看板"})))
        db.commit()
        db.close()

        def _read(service, spreadsheet_id, sheet_name, rng):
            if sheet_name == "黎明账户看板":
                return [["运营", "", "", "账户ID"],
                        ["黎明", "", "", "E2E-1", "", "", "", "", "", "投手填的"]]
            return [["入库时间", "是否回收", "账户ID", "BC", "国家", "所属渠道",
                     "接户运营", "时区", "状态", "消耗", "位置", "换绑情况", "产品信息"],
                    [""] * 2 + ["E2E-1"] + [""] * 3 + ["黎明"] + [""] * 5 + ["户管填的"]]

        captured = []
        monkeypatch.setattr(gs, "build_service", lambda path: object())
        monkeypatch.setattr(gs, "read_sheet_values", _read)
        _stub_sheets(monkeypatch, captured)
        resp = client.post("/api/huguan/dashboard/sync", headers=hg,
                           json={"platform": "tt", "dry_run": False,
                                 "confirmed": {"create": ["E2E-1"]}})
        assert resp.status_code == 200
        rows = [r for c in captured for r in c["rows"]]
        assert {"account_id": "E2E-1", "cells": {"M": "投手填的"}} in rows, \
            "投手赢 → 回写户管看板 M 列"
        assert not any("J" in r["cells"] for r in rows), "投手赢时不应推投手看板"
```

⚠️ 该用例的户管看板数据行必须**恰好 13 列**且 C 列（下标 2）是账户ID、G 列（下标 6）是接户运营、
M 列（下标 12）是产品信息 —— 少了账户ID 会让 `parse_row` 跳过整行，测试静默空跑
（本项目已踩过这个坑）。

- [ ] **Step 7: 跑测试确认通过并提交**

```bash
cd py && python -m pytest tests/test_huguan_dashboard.py::TestRemarkPushPath -v
cd py && python -m pytest tests/test_huguan_dashboard.py -q
git add py/huguan_dashboard.py py/routes/huguan_dashboard_routes.py py/tests/test_huguan_dashboard.py
git commit -m "feat(tt): 新建系统→投手看板推送通路，同步端点消费备注对齐结果"
```

---

## Task 5: 投手在系统内联改备注时推两张表

**Files:**
- Modify: `py/routes/tt_accounts_routes.py`（`update_account()`）
- Test: `py/tests/test_huguan_dashboard.py`

**Interfaces:**
- Consumes: Task 4 的 `push_remark_to_operator_dashboard(owner_id, account_id, value)`
- Produces: `PUT /api/tt/accounts/<aid>` 带 `remark` 时同时推户管看板 M 与投手看板 J

- [ ] **Step 1: 写失败测试**

追加：

```python
class TestUpdateAccountPushesRemark:
    """投手在系统内联改备注 → 推两张表（2026-10-06 规格）。"""

    def test_updating_remark_pushes_to_both_boards(self, client, monkeypatch):
        import google_sheets_service as gs
        op, op_uid = _create_user(client, "_uapr_op", role="user", platform="tt")
        db = database.get_db()
        db.execute("INSERT OR REPLACE INTO config(key,value) VALUES(?,?)",
                   (f"huguan_dashboard_{op_uid}",   # 让 writeback_rows 有配置可写
                    json.dumps({"tt": {"spreadsheet_id": "HG-SS", "sheet_name": "S"}})))
        db.execute("INSERT OR REPLACE INTO tags(key,value) VALUES('tt_sheet_id','OP-SS')")
        db.execute("INSERT OR REPLACE INTO config(key,value) VALUES(?,?)",
                   (f"tt_sheet_mappings_{op_uid}", json.dumps({"my_dashboard": "投手看板"})))
        aid = _seed_tt(db, "UAPR-1", op_uid)
        db.commit()
        db.close()

        captured = []

        def _fake(service, spreadsheet_id, sheet_name, rows, key_col="C"):
            captured.append({"sheet_name": sheet_name, "key_col": key_col, "rows": rows})
            return {"updated": len(rows), "not_found": []}

        monkeypatch.setattr(gs, "build_service", lambda path: object())
        monkeypatch.setattr(gs, "update_rows_by_account_id", _fake)
        import main as m
        monkeypatch.setattr(m, "_sync_sheets_background", lambda fn, on_fail: fn())

        resp = client.put(f"/api/tt/accounts/{aid}", headers=op, json={"remark": "新备注"})
        assert resp.status_code == 200
        cells = [c for cap in captured for c in cap["rows"]]
        assert any(r["cells"].get("M") == "新备注" for r in cells), "应推户管看板 M 列"
        assert any(r["cells"].get("J") == "新备注" for r in cells), "应推投手看板 J 列"

    def test_updating_other_fields_does_not_push_remark(self, client, monkeypatch):
        """回归护栏：不带 remark 的更新不得触发备注推送。"""
        import google_sheets_service as gs
        op, op_uid = _create_user(client, "_uapr_op2", role="user", platform="tt")
        db = database.get_db()
        aid = _seed_tt(db, "UAPR-2", op_uid)
        db.commit()
        db.close()
        called = []
        monkeypatch.setattr(gs, "build_service", lambda path: object())
        monkeypatch.setattr(gs, "update_rows_by_account_id",
                            lambda *a, **k: called.append(1) or {"updated": 0, "not_found": []})
        import main as m
        monkeypatch.setattr(m, "_sync_sheets_background", lambda fn, on_fail: fn())
        client.put(f"/api/tt/accounts/{aid}", headers=op, json={"country": "US"})
        assert called == []
```

- [ ] **Step 2: 跑测试确认失败**

```bash
cd py && python -m pytest tests/test_huguan_dashboard.py::TestUpdateAccountPushesRemark -v
```

预期：第一条 FAIL（只写库、无任何推送）；第二条 PASS（护栏，现状即如此）。

- [ ] **Step 3: 实现**

`py/routes/tt_accounts_routes.py` 的 `update_account()`：

现有 `editable` 循环（`for f in editable: if f in data ...`）不变。在其**之后**、
`# agent/status 文本回退` **之前**插入：

```python
    # 备注改动要推到两张表（2026-10-06 规格）。在 editable 循环之后取一次值：
    # 循环里可能已 strip 过，或本次并未带 remark，故以「data 里是否给了 remark」为准。
    if "remark" in data and data["remark"] is not None:
        _remark_value = str(data["remark"]).strip()
        _adv = row["advertiser_id"]
        _owner_for_push = row["owner_id"]
        # 户管看板：writeback_rows 用的是调用者 uid 的 huguan_dashboard_{uid} 配置。
        # 投手调用时查不到配置会静默空转 —— 这是既有行为，见规格 §5 已知后果 2。
        hd.writeback_rows(uid, "tt", [_adv])
        # 投手看板：推给**账户的归属人**，不是调用者 —— 户管可能代改别人名下的户。
        if _owner_for_push is not None:
            hd.push_remark_to_operator_dashboard(_owner_for_push, _adv, _remark_value)
```

确认文件顶部已 `import huguan_dashboard as hd`（该文件已在用 `hd.writeback_rows`，应已导入）。

- [ ] **Step 4: 跑测试确认通过**

```bash
cd py && python -m pytest tests/test_huguan_dashboard.py::TestUpdateAccountPushesRemark -v
cd py && python -m pytest tests/test_huguan_dashboard.py tests/test_tt_accounts.py tests/test_tt_routes.py -q
```

预期：2 passed；回归全绿。

- [ ] **Step 5: 提交**

```bash
git add py/routes/tt_accounts_routes.py py/tests/test_huguan_dashboard.py
git commit -m "feat(tt): 系统内联改备注后同时推送户管看板与投手看板"
```

---

## Task 6: 前端可内联编辑的备注列

**Files:**
- Modify: `frontend/src/views/tt/TtAccountPanel.vue`

**Interfaces:**
- Consumes: `PUT /api/tt/accounts/<id>` 已支持 `remark`（Task 5 补了推送）
- Produces: 列表面板上可内联编辑的「备注」列

**前置**：⚠️ **这一列是新增 UI 交互**（内联编辑）。按项目规矩，**必须先调用
`/frontend-design` 技能完成视觉设计**，再按设计实现。控制器会在派发本任务前先跑该技能，
并把结论一并交给实现者。

- [x] **Step 1: 先过 `/frontend-design`（控制器执行）**

**结论：不发明新视觉，逐字对齐本文件既有的内联编辑模式。**

理由与依据：

1. **brief 把方向钉死了** —— 「与既有 Element Plus 表格列风格一致」。设计自由度为零的轴
   不投入；自由度仅存在于**行为**（何时进编辑态、怎么取消、怎么反馈）而非外观。
2. **本文件已有六列内联可编辑**：BC / 时区 / 代理 / 状态 / 国家 / **消耗情况**
   （`TtAccountPanel.vue:58,82,98,114,130,143`），共用一套已成型的结构：
   `v-if="editingXxxId === row.id"` 切 `<el-input>` / 只读态 `{{ row.xxx || '—' }}` +
   `✏️` 按钮；类名 `.inline-edit-cell` / `.inline-cell-text` / `.inline-name-input` /
   `.inline-edit-btn` 已在 `<style scoped>` 里定义好（`:740` 起）。
3. **`消耗情况` 是最贴切的类比** —— 同为纯文本列，交互与 remark 完全同构。
4. **在 20 列的运营数据表里给单列发明独特视觉身份，是对抗既有设计系统、损害可用性。**
   这里的「克制」不是保守，是正确的设计判断。

**计划初稿的三处偏离（本次修正）**：

| 初稿写法 | 既有惯例 | 为什么改 |
|---|---|---|
| 点文字进编辑态（隐式热区） | `✏️` 按钮显式进入 | 隐式热区在密集表格里不可发现，且与六个邻居不一致 |
| 无取消键 | `@keyup.escape` → `cancelXxxEdit` | 缺了它，用户误触后只能靠失焦提交，无法放弃 |
| 只弹失败提示 | 成功/失败都弹（六个邻居一致） | 只报错不报成，用户无法确认改动已生效 |

自造类名 `.remark-cell` 也一并去掉 —— 复用 `.inline-*`。

- [ ] **Step 2: 按设计实现**

在 `frontend/src/views/tt/TtAccountPanel.vue` 的「消耗情况」列（`:141`）**之后**插入：

```vue
        <el-table-column label="备注" min-width="160">
          <template #default="{ row }">
            <div class="inline-edit-cell" v-if="editingRemarkId === row.id">
              <el-input v-model="editRemarkValue" size="small" class="inline-name-input"
                :ref="el => { if (el) remarkInputRef = el }"
                @blur="saveRemark(row)" @keyup.enter="saveRemark(row)" @keyup.escape="cancelRemarkEdit" />
            </div>
            <div class="inline-edit-cell" v-else>
              <span class="inline-cell-text">{{ row.remark || '—' }}</span>
              <el-button link size="small" class="inline-edit-btn" @click.stop="startEditRemark(row)">✏️</el-button>
            </div>
          </template>
        </el-table-column>
```

`<script setup>` 内，紧挨 `编辑消耗情况` 那一组（`:315,321,323,636-657`）之后补：

```js
const editingRemarkId = ref(null)
const editRemarkValue = ref('')
let remarkInputRef = null

function startEditRemark(row) {
  editingRemarkId.value = row.id
  editRemarkValue.value = row.remark || ''
  nextTick(() => { remarkInputRef?.focus?.() })
}
function cancelRemarkEdit() {
  editingRemarkId.value = null
  editRemarkValue.value = ''
  remarkInputRef = null
}
async function saveRemark(row) {
  const v = editRemarkValue.value.trim()
  if (v === (row.remark || '')) { cancelRemarkEdit(); return }
  try {
    await ttAccountsApi.update(row.id, { remark: v })
    row.remark = v
    ElMessage.success('备注已更新')
  } catch (e) {
    ElMessage.error('更新备注失败')
  }
  cancelRemarkEdit()
}
```

**注意**：失败时**不要**回写 `row.remark` —— 保持原值即天然回滚，与六个邻居同款。
`ttAccountsApi` / `ElMessage` / `ref` / `nextTick` 该文件**均已导入**
（`TtAccountPanel.vue:256,270,255`），无需新增 import。

- [ ] **Step 3: 构建验证**

```bash
cd frontend && npm run build
```

预期：构建成功，无模板编译错误。

- [ ] **Step 4: 人工验收（留给用户）**

在报告里逐条列出验收要点：点击单元格进入编辑态 / 回车或失焦提交 / 提交后文案即时更新 /
失败有提示且不改变原值 / 非本人账户不可编辑。

- [ ] **Step 5: 提交**

```bash
git add frontend/src/views/tt/TtAccountPanel.vue
git commit -m "feat(tt): 账户面板备注列支持内联编辑"
```

---

## 完成后的收尾

- [ ] 提醒用户 `npm run build`（前端改动后其他人才能看到）
- [ ] 提醒用户**重启 Flask 服务**（后端 `py/*.py` 已改）
- [ ] 提醒用户提交 git
- [ ] 按项目规矩跑 `/code-review`

## 已知后果（来自 spec §5，实现后仍成立，勿当缺陷）

1. `dry_run` 预览看不到投手看板的影响（读取在落库阶段）。
2. 投手改备注时户管看板不会即时刷新（`writeback_rows` 用调用者 uid）——靠全量刷新对齐。
3. 投手读不到时静默降级为「户管赢」并记日志。
4. 投手看板里没有该账户行时，`update_rows_by_account_id` 返回 `not_found`、**不建行**（既有契约）。
