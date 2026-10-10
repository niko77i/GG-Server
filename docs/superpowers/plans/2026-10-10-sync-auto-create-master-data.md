# 同步自动补建字典项（BC / 渠道 / 国家时区）实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 户管看板同步（表 → 系统）遇到系统字典里**没有**的 BC / 所属渠道 / 国家时区时**自动补建**，
而不是跳过该列并报警告；补建**只在落库时发生**，且**在差异报告里逐条可见**。

**Architecture:** 把既有的「确保主数据存在」规则（`_ensure_bc`/`_ensure_agent`/`_strip_utc_prefix`）
提取到共享模块，两条链路共用一份；同步侧照 `_pending_status` 的成熟做法产出 `_pending_master`
合成键（dry_run 只产不写、落库才建），并把它摊成 `diff.pending_master` 供前端展示。

**Tech Stack:** Python 3.11 / Flask / SQLite / pytest（后端）；Vue 3 + Element Plus（前端）。

设计依据：`docs/superpowers/specs/2026-10-10-sync-auto-create-bc-design.md`（下称"设计 §X"）。
**实证前提**（设计 §一，已只读查过库）：该系统的 BC `name == bc_id`（都是 19 位数字）、无脏空格、无重名。

## Global Constraints

- **dry_run 绝不写库**；补建**只在落库路径**发生，且必须在 `diff.pending_master` 里可见。
- **同理不同建**：`tt_bcs`/`agents` 同名 **≥2 条**时**仍警告跳过**（歧义 ≠ 没有）；`regions` 里**已存在的国家绝不覆盖**。
- **国家或时区缺一不建**（避免建出「有国家没时区」的残项，它会被当成已有、再也补不上）。
- **BC 建项**：`name = bc_id = 表里那一格`；**owner_id = 发起同步的户管**；**软删同名直接复活**、不新建。
- **建成后清缓存**（渠道照先例 `accounts:agents:`；BC 需 grep 确认有无对应前缀）。
- **合成键纪律**：`_pending_master` 必须在 `_same_as_existing` / `sets=[f"{k}=?"]` **之前**摘掉 ——
  否则它会穿过 `UPDATE tt_accounts SET _pending_master=?` 直接报错（`_sheet_name` 踩过同款，见 `:1104-1107` 的注释）。
- **gg/fb 与「刷新回表」不动**；不自动建用户（运营）。
- **提交纪律**：只 `git add` 本任务列出的文件。禁止 `git add -A`/`.`/`checkout`/`restore`/`stash`/`push`
  （工作区有并行会话）。提交一律显式 pathspec。
- 测试：`cd py && python -m pytest tests/<file> -q`（`client`/`app` 夹具，不得裸用 `temp/app.db`；Sheets 一律 monkeypatch）；前端 `cd frontend && npm test`。**不启动任何进程。**

---

## Task 1: 共享模块 `py/tt_master_data.py`（纯搬运）

**Files:**
- Create: `py/tt_master_data.py`
- Modify: `py/routes/tt_accounts_routes.py`（删掉三个本地 def，改为 import）
- Test: `py/tests/test_tt_master_data.py`（新）

**Interfaces:**
- Produces: `ensure_bc(db, name, uid) -> int | None`、`ensure_agent(db, name, uid) -> int | None`、
  `strip_utc_prefix(value) -> str`（三者签名与语义与今日**逐字一致**）

- [ ] **Step 1: 先摸清调用点（不许漏）**

Run: `grep -rn "_ensure_bc\|_ensure_agent\|_strip_utc_prefix" py/ --include=*.py`
把这四处都记进报告：`tt_accounts_routes.py:1265`（def）、`:1284`（def）、`:1305`（def）、
`:1376-1377`（调用）、`:1300/:1302`（`_region_timezone` 内调用）、
`py/tests/test_tt_accounts.py:764`（**测试从路由模块 import `_region_timezone`** —— 该名称必须继续存在于路由模块）。

- [ ] **Step 2: 写失败测试**

新建 `py/tests/test_tt_master_data.py`：

```python
"""ensure_bc / ensure_agent / strip_utc_prefix —— 从 tt_accounts_routes 提取到共享模块后的行为锚。"""
import os
import pytest


def test_strip_utc_prefix():
    from tt_master_data import strip_utc_prefix
    assert strip_utc_prefix("UTC+8") == "+8"
    assert strip_utc_prefix("+8") == "+8"
    assert strip_utc_prefix("") == ""
    assert strip_utc_prefix(None) == ""


def test_ensure_bc_creates_with_name_as_bc_id_and_revives_soft_deleted():
    from tt_master_data import ensure_bc
    import database
    conn, db_path = _fresh_schema_conn_of(database)
    try:
        new_id = ensure_bc(conn, "7677926795186094081", 1)
        row = conn.execute("SELECT name, bc_id, owner_id, deleted_at FROM tt_bcs WHERE id=?",
                           (new_id,)).fetchone()
        assert row["name"] == "7677926795186094081"
        assert row["bc_id"] == "7677926795186094081"      # 与实证数据一致
        assert row["owner_id"] == 1
        # 软删复活：把刚建的软删，再 ensure 同名 ⇒ 同一个 id、deleted_at 清空
        conn.execute("UPDATE tt_bcs SET deleted_at='2026-01-01' WHERE id=?", (new_id,))
        again = ensure_bc(conn, "7677926795186094081", 1)
        assert again == new_id
        assert conn.execute("SELECT deleted_at FROM tt_bcs WHERE id=?",
                            (new_id,)).fetchone()["deleted_at"] is None
    finally:
        conn.close()
        os.unlink(db_path)


def test_ensure_agent_creates_and_clears_cache(monkeypatch):
    import cache
    cleared = []
    monkeypatch.setattr(cache.cache, "clear_prefix", lambda p: cleared.append(p))
    from tt_master_data import ensure_agent
    import database
    conn, db_path = _fresh_schema_conn_of(database)
    try:
        aid = ensure_agent(conn, "渠道Z", 1)
        row = conn.execute("SELECT name, platform, owner_id FROM agents WHERE id=?",
                           (aid,)).fetchone()
        assert (row["name"], row["platform"], row["owner_id"]) == ("渠道Z", "tt", 1)
        assert "accounts:agents:" in cleared, "新建渠道后必须清缓存，否则下拉看不到"
    finally:
        conn.close()
        os.unlink(db_path)
```

`_fresh_schema_conn_of` 不存在 —— **照 `py/tests/test_tt_platform.py` 里 `_fresh_schema_conn()` 的既有写法**
（它返回 `(conn, db_path)`）复制一个小 helper 到本文件顶部，别去改那个文件。

- [ ] **Step 3: 跑测试确认失败**

Run: `cd py && python -m pytest tests/test_tt_master_data.py -q`
Expected: FAIL —— `ModuleNotFoundError: No module named 'tt_master_data'`

- [ ] **Step 4: 实现（纯搬运）**

新建 `py/tt_master_data.py`，把三个函数**逐字**搬过来（`ensure_bc` 见 `tt_accounts_routes.py:1265-1281`、
`ensure_agent` 见 `:1284-1293`、`strip_utc_prefix` 见 `:1305-1307`），并把 `_ensure_agent` 里的
`_app_cache.clear_prefix("accounts:agents:")` 照搬（模块顶部 `from cache import cache as _app_cache`）。
**函数体一个字符都不要改**（只改名字前缀：`_ensure_bc` → `ensure_bc` 等）。

然后 `py/routes/tt_accounts_routes.py`：删掉三个本地 def，
改为 `from tt_master_data import ensure_bc, ensure_agent, strip_utc_prefix`，
并把 `:1376-1377` 与 `:1300/:1302` 的调用点改成新名字。
**`_region_timezone` 必须继续留在路由模块里**（`test_tt_accounts.py:764` 从那里 import 它）。

- [ ] **Step 5: 跑测试确认通过 + 该链路回归**

Run: `cd py && python -m pytest tests/test_tt_master_data.py tests/test_tt_accounts.py tests/test_tt_platform.py -q`
Expected: 全绿（`test_tt_accounts.py` 覆盖 `sync_from_sheet` 与 `_region_timezone` ⇒ 搬运未改行为）

- [ ] **Step 6: 提交**

```bash
git commit -m "refactor(tt): 主数据 ensure 规则提取到 tt_master_data（BC/渠道/时区归一化）" -- py/tt_master_data.py py/routes/tt_accounts_routes.py py/tests/test_tt_master_data.py
```

---

## Task 2: 同步侧产出 `_pending_master`（dry_run 只产不写）

**Files:**
- Modify: `py/huguan_dashboard.py`（`_collect_updates`，必要时加一个小查询 helper）
- Test: `py/tests/test_huguan_dashboard.py`

**Interfaces:**
- Produces: `_collect_updates` 的产出里多一个合成键
  `_pending_master: [{"kind": "bc"|"agent"|"region", "name": str, "timezone": str|None}]`
  （**每行一份**；`timezone` 只有 `kind == "region"` 才有；`kind` 与 `name` 是聚合键）

- [ ] **Step 1: 写失败测试**

追加到 `py/tests/test_huguan_dashboard.py`（新类）：

```python
class TestPendingMasterData:
    """同步时把「系统字典里没有的项」产成 _pending_master（dry_run 只产不写）。"""

    def _setup(self, client, username, bc=True, agent=True, region=True):
        hg, uid = _create_user(client, username, role="huguan")
        db = database.get_db()
        if bc:
            db.execute("INSERT INTO tt_bcs(name, bc_id) VALUES('BC-有','7000000000000000001')")
        if agent:
            db.execute("INSERT INTO agents(name, platform) VALUES('渠道有','tt')")
        if region:
            db.execute("INSERT INTO regions(name, timezone, platform) VALUES('美国','+8','tt')")
        db.commit(); db.close()
        return hg, uid

    def test_missing_bc_agent_region_are_reported_as_pending(self, client):
        hg, _uid = self._setup(client, "_pm1")
        db = database.get_db()
        from huguan_dashboard import _collect_updates, parse_row
        p = parse_row(["入库时间", "是否回收", "账户ID", "BC", "国家", "所属渠道",
                       "接户运营", "时区", "状态", "消耗", "位置", "换绑情况", "产品信息"],
                      "tt", __import__("huguan_dashboard").resolve_column_map(
                          ["入库时间", "是否回收", "账户ID", "BC", "国家", "所属渠道",
                           "接户运营", "时区", "状态", "消耗", "位置", "换绑情况", "产品信息"], {})[0])
        p.update({"日期": None})
        row = dict(p, **{"账户ID": "9001", "BC": "BC-没有", "国家": "巴西", "所属渠道": "渠道没有",
                         "时区": "UTC+8"})
        row["account_id"] = "9001"
        out = _collect_updates(db, "tt", row, None, 2, [], create_missing=False)
        db.close()
        got = {(x["kind"], x["name"], x.get("timezone")) for x in out["_pending_master"]}
        assert ("bc", "BC-没有", None) in got, got
        assert ("agent", "渠道没有", None) in got, got
        assert ("region", "巴西", "+8") in got, got        # 归一化去掉 UTC 前缀

    def test_existing_entries_do_not_appear(self, client):
        hg, _uid = self._setup(client, "_pm2")
        db = database.get_db()
        from huguan_dashboard import _collect_updates
        out = _collect_updates(db, "tt", {"account_id": "9002", "bc_name": "BC-有",
                                          "agent_name": "渠道有", "country": "美国",
                                          "timezone": "+8"}, None, 2, [], create_missing=False)
        db.close()
        assert out.get("_pending_master", []) == []

    def test_ambiguous_name_is_still_a_warning_not_a_create(self, client):
        """同名 ≥2 条 = 歧义 ≠ 没有 ⇒ 仍警告跳过，绝不补建第三条。"""
        hg, _uid = self._setup(client, "_pm3", bc=False)
        db = database.get_db()
        db.execute("INSERT INTO tt_bcs(name, bc_id) VALUES('BC-歧义','7000000000000000002')")
        db.execute("INSERT INTO tt_bcs(name, bc_id) VALUES('BC-歧义','7000000000000000003')")
        db.commit()
        from huguan_dashboard import _collect_updates
        warns = []
        out = _collect_updates(db, "tt", {"account_id": "9003", "bc_name": "BC-歧义"},
                               None, 2, warns, create_missing=False)
        db.close()
        assert "bc_id" not in out
        assert [_ for _ in out.get("_pending_master", []) if _["kind"] == "bc"] == []
        assert any("无法唯一匹配" in w["message"] for w in warns), warns

    def test_country_without_timezone_is_not_pending(self, client):
        hg, _uid = self._setup(client, "_pm4")
        db = database.get_db()
        from huguan_dashboard import _collect_updates
        out = _collect_updates(db, "tt", {"account_id": "9004", "country": "秘鲁", "timezone": ""},
                               None, 2, [], create_missing=False)
        db.close()
        assert [x for x in out.get("_pending_master", []) if x["kind"] == "region"] == []
```

> 注：上面第一条用例里 `parse_row` 的构造略显笨拙是为了**不依赖**夹具里已有的表头常量；
> 若 `test_huguan_dashboard.py` 里已有现成的 `_row(...)`/表头 helper，**优先用现成的**，别照抄这段。

- [ ] **Step 2: 跑测试确认失败**

Run: `cd py && python -m pytest tests/test_huguan_dashboard.py -q -k TestPendingMasterData`
Expected: FAIL —— 没有 `_pending_master` 键

- [ ] **Step 3: 实现**

在 `py/huguan_dashboard.py` 的 `_collect_updates` 里改造名称类字段分支（现有代码在 `:1216-1225`）：

```python
        _known, resolved = _resolve_field(db, platform, f, value)
        if not _known:
            continue
        if resolved is None:
            # 「查不到」与「重名多条」在 resolve_named_id 里都返回 None（0 或 ≥2 ⇒ 不猜）。
            # 但两者处理**相反**：0 条 = 系统里没有 ⇒ dry_run 产 pending、落库补建；
            # ≥2 条 = 歧义 ⇒ 仍然只警告跳过（多建一条只会更乱）。
            hits = _named_hits(db, platform, f, value)
            if hits == 0 and f in ("bc_name", "agent_name"):
                pending_master.append({"kind": "bc" if f == "bc_name" else "agent",
                                       "name": value, "timezone": None})
                continue
            warnings.append({"row": row_no, "sheet": _conf_text(p.get("_sheet")),
                             "message": f"{f}「{value}」无法唯一匹配，已跳过该列"})
            continue
        out[_target_column(platform, f)] = resolved
```

并在函数开头（`out = {}` 附近）加 `pending_master = []`，末尾（`return out` 之前）加：

```python
    # 国家 → 时区：表里两列都有、而 regions 里没有这个国家 ⇒ 记 pending（**只查库、不写**）。
    # 国家或时区缺一不建：建出「有国家没时区」的残项会被当成已有、再也补不上。
    country = _conf_text(p.get("country"))
    tz = _conf_text(p.get("timezone"))
    if platform == "tt" and country and tz and not _region_exists(db, country):
        pending_master.append({"kind": "region", "name": country,
                               "timezone": strip_utc_prefix(tz)})
    if pending_master:
        out["_pending_master"] = pending_master
```

新增两个小 helper（同文件，紧邻 `resolve_named_id`）：

```python
def _named_hits(db, platform: str, field: str, value: str) -> int:
    """该名称命中了**几条**（0 / 1 / ≥2）。只为区分「没有」与「歧义」，不参与取值。"""
    if field == "bc_name":
        sql = _SQL_BC
    elif field == "agent_name":
        sql = _AGENT_SQL[platform]
        if sql is None:
            return 0
    else:
        return 0
    return len(db.execute(sql, (value,)).fetchall())


def _region_exists(db, country: str) -> bool:
    return db.execute("SELECT 1 FROM regions WHERE name=? AND platform='tt'",
                      (country,)).fetchone() is not None
```

文件顶部补 `from tt_master_data import strip_utc_prefix`（T1 的产物）。

- [ ] **Step 4: 跑测试确认通过 + 全文件回归**

Run: `cd py && python -m pytest tests/test_huguan_dashboard.py -q`
Expected: 全绿（既有用例不受影响：`_pending_master` 只在有缺项时出现）

- [ ] **Step 5: 提交**

```bash
git commit -m "feat(tt): 同步把「缺的字典项」产成 _pending_master（BC/渠道/国家时区，dry_run 只产不写）" -- py/huguan_dashboard.py py/tests/test_huguan_dashboard.py
```

---

## Task 3: 落库补建 + `diff.pending_master`（**含合成键纪律**）

**Files:**
- Modify: `py/huguan_dashboard.py`（`build_diff` 摘键/聚合、`apply_diff` 两分支消费）
- Modify: `py/routes/huguan_dashboard_routes.py`（`diff` 带出该键）
- Test: `py/tests/test_huguan_dashboard.py`

**Interfaces:**
- Consumes: T2 的 `_pending_master`；T1 的 `ensure_bc` / `ensure_agent`
- Produces: `diff.pending_master: [{"kind","name","timezone"|None,"rows": int}]`（**按 (kind,name) 聚合、`rows` 计数**；
  时区取**首次出现**的值 —— 与既有「首次出现生效」惯例一致）

- [ ] **Step 1: 写失败测试**

```python
class TestPendingMasterApply:
    def test_dry_run_reports_but_creates_nothing(self, client, monkeypatch):
        import google_sheets_service as gs
        hg, _ = _create_user(client, "_pma1", role="huguan")
        db = database.get_db()
        db.execute("INSERT OR REPLACE INTO config(key,value) VALUES(?,?)",
                   (f"huguan_dashboard_{_uid_of('_pma1')}", json.dumps({"tt": {
                       "spreadsheet_id": "SS",
                       "tables": [{"name": "企业户", "sheet_name": "企业户"}]}})))
        db.commit(); db.close()
        hdr = ["入库时间", "是否回收", "账户ID", "BC", "主体名称", "账户名称",
               "国家", "所属渠道", "接户运营", "时区", "下户链接"]
        row = ["2026-10-01", "否", "9101", "BC-新", "主体X", "甲",
               "巴西", "渠道新", "张三", "UTC+8", ""]
        monkeypatch.setattr(gs, "read_sheet_values", lambda *a, **k: [hdr, row])
        monkeypatch.setattr(gs, "build_service", lambda p: object())
        diff = client.post("/api/huguan/dashboard/sync", headers=hg,
                           json={"platform": "tt", "dry_run": True}).get_json()["diff"]
        kinds = {(x["kind"], x["name"]) for x in diff["pending_master"]}
        assert ("bc", "BC-新") in kinds and ("agent", "渠道新") in kinds
        assert ("region", "巴西") in kinds
        db = database.get_db()
        assert db.execute("SELECT COUNT(*) c FROM tt_bcs WHERE name='BC-新'").fetchone()["c"] == 0, \
            "dry_run 绝不写库"
        db.close()

    def test_apply_creates_and_links(self, client, monkeypatch):
        import google_sheets_service as gs
        hg, _ = _create_user(client, "_pma2", role="huguan")
        db = database.get_db()
        db.execute("INSERT OR REPLACE INTO config(key,value) VALUES(?,?)",
                   (f"huguan_dashboard_{_uid_of('_pma2')}", json.dumps({"tt": {
                       "spreadsheet_id": "SS",
                       "tables": [{"name": "企业户", "sheet_name": "企业户"}]}})))
        db.commit(); db.close()
        hdr = ["入库时间", "是否回收", "账户ID", "BC", "主体名称", "账户名称",
               "国家", "所属渠道", "接户运营", "时区", "下户链接"]
        row = ["2026-10-01", "否", "9102", "BC-新2", "主体X", "甲",
               "巴西", "渠道新2", "张三", "UTC+8", ""]
        monkeypatch.setattr(gs, "read_sheet_values", lambda *a, **k: [hdr, row])
        monkeypatch.setattr(gs, "build_service", lambda p: object())
        resp = client.post("/api/huguan/dashboard/sync", headers=hg,
                           json={"platform": "tt", "dry_run": False,
                                 "confirmed": {"create": ["9102"]}})
        assert resp.status_code == 200, resp.get_json()
        db = database.get_db()
        bc = db.execute("SELECT id, bc_id FROM tt_bcs WHERE name='BC-新2'").fetchone()
        ag = db.execute("SELECT id FROM agents WHERE name='渠道新2' AND platform='tt'").fetchone()
        rg = db.execute("SELECT timezone FROM regions WHERE name='巴西' AND platform='tt'").fetchone()
        acc = db.execute("SELECT bc_id, agent_id FROM tt_accounts WHERE advertiser_id='9102'").fetchone()
        db.close()
        assert bc and bc["bc_id"] == "BC-新2", "BC 应被补建且 bc_id = name"
        assert ag, "渠道应被补建"
        assert rg and rg["timezone"] == "+8", "时区应归一化去 UTC 前缀"
        assert acc["bc_id"] == bc["id"] and acc["agent_id"] == ag["id"], "账户必须挂到新建的项上"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd py && python -m pytest tests/test_huguan_dashboard.py -q -k TestPendingMasterApply`
Expected: FAIL —— `KeyError: 'pending_master'` / 库里没有补建

- [ ] **Step 3: 实现**

**（a）`build_diff`**：两个分支各自摘掉合成键（**紧挨既有的 `_pending_status` 那句**），
挂到该 item 上；最后在**返回的字典字面量**里加聚合键（`build_diff` 的返回是 `return { "to_create": ..., ... }` 字面量，
**不是**名为 `diff` 的变量 —— 别写成 `diff[...] = ...`）：

```python
        # create 分支（紧挨 `pending = db_values.pop("_pending_status", None)`）：
        pending_master_row = db_values.pop("_pending_master", None)
        to_create.append({..., "pending_status": pending,
                          "pending_master": pending_master_row})   # 加这一行

        # update 分支（紧挨 `pending = fields.pop("_pending_status", None)`，**且必须在
        # `changed = {...}` 推导之前** —— 否则它会穿过 `sets=[f"{k}=?"]` 报错）：
        pending_master_row = fields.pop("_pending_master", None)
        to_update.append({..., "pending_status": pending,
                          "pending_master": pending_master_row})   # 加这一行
```

```python
    # 返回前聚合「将新增的字典项」（设计 §4.3）：按 (kind, name) 去重、rows 计数、
    # 时区取**首次出现**（与既有「首次出现生效」惯例一致）。
    agg, order = {}, []
    for item in to_create + to_update:
        for x in item.get("pending_master") or []:
            k = (x["kind"], x["name"])
            if k not in agg:
                agg[k] = {"kind": x["kind"], "name": x["name"],
                          "timezone": x.get("timezone"), "rows": 0}
                order.append(k)
            agg[k]["rows"] += 1

    return {
        "to_create": to_create,
        "to_update": to_update,
        "owner_changes": owner_changes,
        "to_skip": to_skip,
        "warnings": warnings,
        "pending_master": [agg[k] for k in order],      # ← 加这一行
        "summary": {...},
    }
```

**（b）`apply_diff`**：照 `pending_status` 的样板（create 在 `:1536`、update 在 `:1617`），
**紧接其后**补建并把新 id 挂到这一行：

```python
            # create 分支（`src` 是要 INSERT 的行字典；owner 用 item.get("owner_id")）：
            for x in item.get("pending_master") or []:
                if x["kind"] == "bc":
                    src["bc_id"] = ensure_bc(db, x["name"], item.get("owner_id"))
                elif x["kind"] == "agent":
                    src["agent_id"] = ensure_agent(db, x["name"], item.get("owner_id"))
                else:                                  # region：纯 INSERT，无 id 要挂
                    _ensure_region(db, x["name"], x["timezone"])
```

```python
            # update 分支（`fields` 就是 item["fields"]；owner 用 item.get("scope_owner_id")
            # —— 与上面 pending_status 的取法逐字一致。**必须在 `sets = [...]` 与
            # 历史留痕之前**：这样 bc_id/agent_id 进 SET，$MCC/BC 变更留痕也能记上。）
            for x in item.get("pending_master") or []:
                if x["kind"] == "bc":
                    fields["bc_id"] = ensure_bc(db, x["name"], item.get("scope_owner_id"))
                elif x["kind"] == "agent":
                    fields["agent_id"] = ensure_agent(db, x["name"], item.get("scope_owner_id"))
                else:
                    _ensure_region(db, x["name"], x["timezone"])
```

`_ensure_region(db, name, timezone)` 新增在 `huguan_dashboard.py`：

```python
def _ensure_region(db, name: str, timezone: str) -> None:
    """国家 → 时区：缺则补建（**已存在绝不覆盖** —— 字典是别的功能在用的权威值）。"""
    if not name or not timezone:
        return
    if _region_exists(db, name):
        return
    db.execute("INSERT INTO regions(name, timezone, platform) VALUES(?,?,'tt')",
               (name, timezone))
```

**（c）路由**：`diff` 就是 `build_diff` 的返回值 ⇒ 路由**无需改动**（`diff["pending_master"]` 自动带出）。
先 grep 确认没有第二处重建 `diff` 键集合的地方，并在报告里说明。

- [ ] **Step 4: 跑测试确认通过 + 全量后端回归**

Run: `cd py && python -m pytest tests/ -q`
Expected: 全绿（含既有 `_pending_status` 用例 —— 合成键纪律没被破坏）

- [ ] **Step 5: 提交**

```bash
git commit -m "feat(tt): 落库补建缺的字典项并挂到账户上；diff 带出 pending_master" -- py/huguan_dashboard.py py/tests/test_huguan_dashboard.py
```

---

## Task 4: 前端差异弹窗加「将新增的字典项」一节

**Files:**
- Modify: `frontend/src/components/HuguanDashboardCard.vue`

**视觉规格（照此做，勿自创）**：
- 位置：差异弹窗里，**紧挨**既有的「未采集列」节（同一层级的区块）。
- 标题：「**将新增的字典项**」14px/600 `#374151`，与既有分区标题同款；左竖条 **3px `#e6a23c`**（warning 橙 —— 它是"将写入"而非"出错了"）。
- 区顶一行说明（12px `#6b7280`）：「这些是系统里还没有的 BC / 渠道 / 国家时区，**确认同步后会自动创建**。」
- 逐条一行：`类型标签（灰底 el-tag：BC / 渠道 / 国家时区）` + `名称`（`font-family` 沿用；纯数字用 `font-variant-numeric: tabular-nums`）+ **`N 行`**（12px `#6b7280`，`el-tag` 无底） + （国家时区那类额外显示 `→ +8`）。
- 只在 `diff.pending_master` **存在且非空**时渲染；`dry_run` 与结果页都显示（确认后它就不再变化——建成即"已有"）。
- 不做：不加动效、不加编号、不给它单独的确认按钮（它跟随整个差异报告的确认）。

- [ ] **Step 1: 接线**（`hdPendingMaster = computed(() => syncDiff.value?.pending_master || [])`）
- [ ] **Step 2: 渲染**（照视觉规格）
- [ ] **Step 3: 验证**：`cd frontend && npm test && npx vite build`（`dist/` 已 gitignore，可当 `.vue` 编译检查）
- [ ] **Step 4: 提交**

```bash
git commit -m "feat(tt-ui): 差异弹窗显示「将新增的字典项」" -- frontend/src/components/HuguanDashboardCard.vue
```

---

## Task 5: 收尾（两套全量 + 验收清单补项）

**Files:**
- Modify: `docs/superpowers/plans/2026-10-10-sync-auto-create-master-data.md`（补验收清单）

- [x] **Step 1: 两套全量** —— 2026-10-10 于 `4d0eb89` 实跑

Run: `cd py && python -m pytest tests/ -q`
Result: **1924 passed, 0 failed**（526.31s；1651 warnings）

Run: `cd frontend && npm test`
Result: **36 passed, 0 failed**（`node --test`，`tests 36 / pass 36 / fail 0`；约 71ms）

- [x] **Step 2: 写验收清单进本计划**

### 验收清单（用户手工执行 · 本批并入「整体验收」）

> **本批是「整体验收」的第三批，用户要的是一次跑完前两批 + 本批。** 所以本清单**不重复**前两批的条目，只指路 + 补本批条目：
>
> - **第一批**（列映射面板 / 未采集列 / 同名列）：`docs/superpowers/plans/2026-10-10-tt-header-mapping-frontend.md` 文末「### 验收清单（用户手工执行 · 两批合一）」的 **A1–A8 / B1–B3 / C4 / D1–D5**。
> - **第二批**（按表导入 / 按表刷新 / 撤回对称）：`docs/superpowers/plans/2026-10-10-per-sheet-sync.md` 文末「#### 验收清单（用户手工执行 · 整体验收）」的 **P1–P12 + P5bis**。
> - **这三批目前全部未跑**（前两批记录表的勾都还空着）。⇒ **建议顺序：第一批 → 第二批 → 本批**。理由：本批只往**同一张差异弹窗**里加了一个区块，但它落在第一批「未采集列」区**正下方**、并复用第二批改过的模式开关（`syncDlg.mode`），前两批的弹窗版式是本批验收的前提。
> - 全程**只点浏览器，不重启任何服务**。

#### 0 · 前置（一次性）

- 浏览器打开 TT 设置页 → 「户管看板」卡片；确认至少有 **企业户** 与 **加白户** 两张表且工作表名已保存。
- 用一张**测试用表格**做（下面要往表里加行、加系统里没有的 BC / 渠道 / 国家）。
- 每张要验的表里**必须有一列表头叫「账户ID」**。
- 备好两个观测点：① **账户详情**（看账户挂没挂上 BC / 渠道）；② **下拉出现的地方**（看新建的 BC / 渠道是否立刻可选）。

#### 一 · 预演（dry_run）—— 只产不写

**S1 · 「将新增的字典项」区出现、位置与逐条款式**（吸收 Task 4 审查手工项 1 / 3 / 6）
- 怎么点：在企业户测试表里加一行：`账户ID`=一个新号；`BC` 填一个系统里没有的 19 位数字；`所属渠道` 填「渠道X」（系统没有）；`国家` 填一个系统没有的新国家、`时区` 填 `UTC+8`。保存表 → 点「⬇️ 导入这张表」（或平台级「⬇️ 全部导入」；本步只**预演**，先别确认）。
- 看什么 / 期望（**颜色与对齐必须在真实浏览器里看** —— `npm test` 不覆盖 `.vue` 渲染）：
  - 弹窗里出现区块「**将新增的字典项**」，位置在「**未采集列**」区**正下方**；
  - 区块左侧一条 **3px 橙色竖条**（`#e6a23c`）；标题 14px / 600 / `#374151`（与相邻分区标题同款）；
  - 区顶一行 **12px 灰字**（`#6b7280`）：「这些是系统里还没有的 BC / 渠道 / 国家时区，确认同步后会自动创建。」；
  - 逐条一行，**三档都要对**：
    - **BC** 行 = 灰底 `el-tag`「BC」+ 那串 **19 位数字名** + 灰字「N 行」；数字**等宽对齐**（`tabular-nums`）；
    - **渠道**行 = 灰底 `el-tag`「渠道」+ 名称 + 「N 行」；
    - **国家时区**行 = 灰底 `el-tag`「国家时区」+ 国家名 + 「N 行」+ 灰色「**→ +8**」。
  - ⚠️ 只有**国家时区**那一档出现「→ 时区」；**BC / 渠道行绝不能出现「→ …」**（它们没有时区）。

**S2 · 预演不写库**（brief 1）
- 接着 S1，**先别点确认**：去「字典/下拉」处与账户详情里查 —— 那个 BC、那个渠道、那个新国家在系统里**查不到**，表里那一行的账户也**没建**。
- 期望：dry_run **绝不写库**。

**S3 · 列表为空时整块不渲染**（吸收 Task 4 审查手工项 2；含 gg/fb）
- 怎么点：① 用一张**所有字段都已存在**的表（或把 S1 那行的新项删掉）跑一次预演；② 切到 GG / FB 卡片各跑一次。
- 期望：**整块不出现** —— 没有标题、没有空表、没有残留（该 div 带 `margin:16px 0`，为空时整个 div 不在）。

#### 二 · 确认落库（apply）

**S4 · 确认后建出字典项并挂到账户上**（brief 2）
- 怎么点：回到 S1 的预演，点**确认落库**（新增/更新默认全勾）。
- 期望：
  - BC 被建出（`name = 那串数字`），账户详情里该账户**挂上了这个 BC**；
  - 渠道被建出，账户**挂上了这个渠道**；
  - 新国家进了 `regions`，且时区是 `+8`（**已去 `UTC` 前缀**，不是 `UTC+8`）。

**S5 · 结果页口径改为「已补建」、整页再无「将新增」**（吸收 Task 4 审查手工项 4）
- 接着 S4 停在结果页。
- 期望：区块标题变「**已补建的字典项**」；区顶说明变「这些是本次同步自动写入系统字典的 BC / 渠道 / 国家时区。」；**通读整个结果页，任何位置都不得再有「将新增」三个字**。

**S6 · 孤儿行：`orphan_linked` 计数出现 / 不出现**（吸收 Task 4 审查手工项 5）
- 怎么点：制造一个「**已存在账户、唯一变化是系统没有的字典名**」—— 系统里已有一个账户（其余字段固定），把表里该行的 `BC`（或 `所属渠道`）改成系统**没有**的名字、**其余列与库里逐字相同**；保存表 → 同步 → 确认落库。
- 期望：
  - 结果页 alert 在「归属变更 N 个」之后**多出一句**「**，另有 N 个已有账户补上了字典关联**」；
  - 当本次 `created` / `updated` / `owner_changed` **全为 0**、`orphan_linked > 0` 时这句话**仍要出现**（一次「只挂链」的同步不能被读成没发生）；
  - 反之，没有任何孤儿的一次同步里，这句**不出现**。
- 备注：若该账户除字典名外的列也变了，它会被判成普通更新（`orphan_linked` 不计）、句子不出现属正常 —— 请确保「其余列逐字相同」。

**S7 · 同名重复的 BC 仍警告、且不建第三条**（brief 3）
- 怎么点：在系统里造**两条同名** BC（同名、不同 `bc_id`）；表里填这个名字。
- 期望：同步**仍然报**「…**无法唯一匹配**…已跳过该列」这类警告，**不补建第三条**（歧义 ≠ 没有）。

**S8 · 已存在的国家不被覆盖**（brief 4）
- 怎么点：手动把系统里某国（如「美国」）的时区改成别的值（如 `+9`）；再同步一张**含该国、时区列写着 `UTC+8`** 的表并确认落库。
- 期望：该国的时区**仍是 `+9`**（字典是别的功能在用的权威值，**已存在绝不覆盖**）。

**S9 · 新建的渠道 / BC 立刻出现在下拉里**（brief 5，缓存已清）
- 怎么点：S4 落库后**不刷新页面**，去看用到渠道与 BC 的两处。
- 期望：
  - TT 账户面板的「**渠道**」下拉（`GET /api/agents/list?platform=tt`，直读库、无缓存）—— 立刻可见；
  - 「**BC**」下拉（`GET /api/tt/bcs/options`，直读库、无缓存）—— 立刻可见；
  - 账户列表里渠道的**显示 / 筛选**（`GET /api/accounts/list`，缓存键 `accounts:agents:`）—— 也**不刷新页面**就更新（这一处才是 brief 说的「缓存已清」：`ensure_agent` 会 `clear_prefix("accounts:agents:")`）。

#### 三 · 回归与版式

**S10 · gg/fb 与「刷新回表」行为不变**（brief 6）
- 怎么点：切到 GG / FB 卡片各同步一次；再回 TT 做一次「⬆️ 刷新回这张表」。
- 期望：gg/fb 的同步与弹窗与改动前**逐字节不变**（`pending_master` 对 gg/fb 恒为空，整块不出现）；「刷新回表」流程与改动前一致。

**S11 · 新区块未破坏滚动容器内既有版式**（吸收 Task 4 审查手工项 7）
- 怎么点：在一次**差异项很多**（弹窗出现纵向滚动条）的预演里，滚动到「未采集列」与「将新增的字典项」两区交界处。
- 期望：新区块**落在 70vh 滚动容器内部**、随滚动条正常滚动，**没有**溢出容器、没有压住 / 错位既有区块。

#### 四 ·「已补建」绝对断言的过度声称（Task 4 审查**未决**项）

**S12 · 让一次同步「报告列了、实际没建」—— 核对结果页会不会过度声称**
- 背景：结果页的标题**写死**「已补建的字典项」，不区分本次是否真的建成。若本次同步有出错的行（`errors`）、有勾了却没落库的项（`not_applied`）、或干脆**没勾**某行，这个标题对那条未建成的项就是**过度声称**。
- 怎么点（**可确定性触发，不需要改库、不需要与表赛跑**）：
  1. 在表里放**两行新增**（两个系统都没有的账户）：A 行的 `BC` 用系统没有的「BC-A」，B 行的 `BC` 用系统没有的「BC-B」。
  2. 跑预演 —— 「将新增的字典项」里**同时列出 BC-A 与 BC-B**。
  3. 在确认弹窗的「新增」表里，把 **B 那一行前面的勾去掉**（只留 A 勾着），点确认落库。
  4. **期望看到过度声称**：结果页提示「已同步：新增 1 …」，而下方「**已补建的字典项**」区**仍列出 BC-A 与 BC-B 两条**；去下拉 / 字典处查 —— **BC-B 根本查不到**（对应账户没落库，BC-B 也没被建）。⇒ 标题对 BC-B 不成立。
  - 同类对照（顺带看一眼）：若某次同步弹出红 alert「有 N 行出错，没有写入」或黄 alert「有 N 项没有落库（确认之后表又变了）」，请一并去下拉核对：这一区列出的项**是不是都真建了**。
- 判据 / 待裁定：这是**设计层面的已知边界**（spec 让结果页读成「已完成」），**不是本轮实现缺陷**。请用户拍板：是否需要在**有 `errors` / `not_applied` / 未勾选**时，把该区标题换成更保守的措辞（例如「本次补建的字典项」）或按实际结果逐条标注。**此条不阻塞交付**，记录为观察项。

#### 记录表（验完把结果填这里）

| 组 | 项 | 结果 |
|---|---|---|
| 本批 | S1 预演区出现 / 位置 / 逐条款式（「→ +8」仅国家档） | ☐ |
| 本批 | S2 预演不写库 | ☐ |
| 本批 | S3 空列表整块不渲染（含 gg/fb） | ☐ |
| 本批 | S4 确认落库：建出 + 挂链 + 时区去 UTC | ☐ |
| 本批 | S5 结果页改「已补建」、全页无「将新增」 | ☐ |
| 本批 | S6 孤儿行 orphan_linked 出现 / 不出现 | ☐ |
| 本批 | S7 同名 BC 仍警告、不建第三条 | ☐ |
| 本批 | S8 已存在国家不被覆盖 | ☐ |
| 本批 | S9 新建渠道/BC 立刻进下拉（缓存已清） | ☐ |
| 本批 | S10 gg/fb 与刷新回表行为不变 | ☐ |
| 本批 | S11 未破坏 70vh 滚动容器版式 | ☐ |
| 本批 | S12 「已补建」过度声称（未勾选行仍列出）—— 待用户裁定 | ☐ |
| — | 第一批 A1–A8 / B1–B3 / C4 / D1–D5 | ☐ 见 `2026-10-10-tt-header-mapping-frontend.md` |
| — | 第二批 P1–P12 + P5bis | ☐ 见 `2026-10-10-per-sheet-sync.md` |

- [x] **Step 3: 提交**

```bash
git commit -m "docs(sync-auto-create): 验收清单（整体验收第三批）" -- docs/superpowers/plans/2026-10-10-sync-auto-create-master-data.md
```
