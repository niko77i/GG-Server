# 按表导入 / 按表回写（TT 多表）实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让 TT 户管能**只对某一张账户表**发起「导入到系统」或「刷新回表里」，不必每次把所有表跑一遍；按表时**不跨表去重**、快照只含该表；顺带加计时日志定位「慢」。

**Architecture:** **不改** `build_diff` / `apply_diff` / 写回链路 —— 按表靠「路由只喂那一张表的数据」实现，既有跨表去重/快照/撤回/`_account_type` 注入全部原样复用，不产生第二套路径。两个端点各加一个**可选** `sheet_name`（缺省＝全部表，与改动前逐字节一致）。

**Tech Stack:** Python 3.11 / Flask / SQLite / pytest（后端）；Vue 3 + Element Plus / `node --test`（前端）。

设计依据：`docs/superpowers/specs/2026-10-10-per-sheet-sync-design.md`（下称"设计 §X"）。

## Global Constraints

- **`sheet_name` 缺省 ⇒ 行为与改动前逐字节一致**（全部表、跨表去重、整批定位键校验）。前端可分批上线。
- **按表操作的归属门禁**：`sheet_name` 必须是**该用户自己配置里**的某张表，否则 400；**不得**据此读任意工作表。
- **gg/fb 传 `sheet_name` ⇒ 400**（用户裁定：静默等同全量会让前端 bug 变哑巴）。
- **禁止并发**：按表或平台级操作进行中，**所有**相关按钮禁用（用户裁定）。
- 按表时**不跨表去重**（A1）；跨表重复用**只查库**的提示补偿（设计 §3.3），**不得**为此读其它表。
- **撤回快照**：按表操作生成的快照**只含该表**；「撤回上次」＝撤回上一次那次操作（B）。
- **计时日志只加日志、不改行为**（设计 §3.4）；级别 `log.info`。
- **不做 C**（读范围收窄）——除非计时日志显示读取是大头。
- **提交纪律**：只 `git add` 本任务列出的文件。**禁止 `git add -A`/`.`/`git checkout`/`restore`/`stash`/`push`**（工作区有并行会话，正在另一个 feature 上提交）。提交一律显式 pathspec。
- 测试命令：后端 `cd py && python -m pytest tests/<file> -q`（`client`/`app` 夹具，不得裸用 `temp/app.db`；Sheets 一律 monkeypatch）；前端 `cd frontend && npm test`。
- **不启动任何进程/服务。**

---

## Task 1: `sync` 支持按表（+ 归属校验 + 计时日志）

**Files:**
- Modify: `py/routes/huguan_dashboard_routes.py`（`dashboard_sync`）
- Test: `py/tests/test_huguan_dashboard.py`

**Interfaces:**
- Produces: `POST /api/huguan/dashboard/sync` 接受可选 `sheet_name`（str）；给了就只处理该表

- [ ] **Step 1: 写失败测试**

追加到 `py/tests/test_huguan_dashboard.py`（新类）：

```python
class TestPerTableSync:
    """按表导入（设计 §3.1）：给了 sheet_name 就只读那一张表。"""

    def _conf(self, client, username, tables):
        hg, _ = _create_user(client, username, role="huguan")
        db = database.get_db()
        db.execute("INSERT OR REPLACE INTO config(key,value) VALUES(?,?)",
                   (f"huguan_dashboard_{_uid_of(username)}", json.dumps(
                       {"tt": {"spreadsheet_id": "SS", "tables": tables}})))
        db.commit(); db.close()
        return hg

    def test_only_reads_the_named_table(self, client, monkeypatch):
        import google_sheets_service as gs
        hg = self._conf(client, "_ps1", [
            {"name": "企业户", "sheet_name": "企业户"},
            {"name": "加白户", "sheet_name": "加白户"}])
        reads = []

        def _fake_read(svc, sid, sheet, rng):
            reads.append(sheet)
            if sheet == "企业户":
                return [["账户ID", "备注二"], ["7001", ""]]
            return [["入库时间", "是否回收", "账户ID", "BC", "国家", "所属渠道",
                     "接户运营", "时区", "状态", "消耗", "位置", "换绑情况", "产品信息"],
                    ["2026-10-01", "否", "9001", "", "", "", "", "", "", "", "", "", ""]]

        monkeypatch.setattr(gs, "read_sheet_values", _fake_read)
        monkeypatch.setattr(gs, "build_service", lambda p: object())
        diff = client.post("/api/huguan/dashboard/sync", headers=hg, json={
            "platform": "tt", "sheet_name": "企业户", "dry_run": True}).get_json()["diff"]
        assert reads == ["企业户"], f"只该读一张表，实际读了 {reads}"
        assert [x["account_id"] for x in diff["to_create"]] == ["7001"]

    def test_foreign_sheet_name_rejected_without_reading(self, client, monkeypatch):
        import google_sheets_service as gs
        hg = self._conf(client, "_ps2", [{"name": "企业户", "sheet_name": "企业户"}])
        reads = []
        monkeypatch.setattr(gs, "read_sheet_values", lambda *a, **k: reads.append(a) or [[]])
        monkeypatch.setattr(gs, "build_service", lambda p: object())
        resp = client.post("/api/huguan/dashboard/sync", headers=hg, json={
            "platform": "tt", "sheet_name": "别人的表", "dry_run": True})
        assert resp.status_code == 400 and "别人的表" in resp.get_json()["error"]
        assert reads == [], "外来表名不该真的去读"

    def test_gg_rejects_sheet_name(self, client):
        hg, _ = _create_user(client, "_ps3", role="huguan")
        resp = client.post("/api/huguan/dashboard/sync", headers=hg, json={
            "platform": "gg", "sheet_name": "企业户", "dry_run": True})
        assert resp.status_code == 400

    def test_without_sheet_name_reads_every_table(self, client, monkeypatch):
        """缺省必须与改动前一致：所有表都读、行合并。"""
        import google_sheets_service as gs
        hg = self._conf(client, "_ps4", [
            {"name": "企业户", "sheet_name": "企业户"},
            {"name": "加白户", "sheet_name": "加白户"}])
        reads = []
        monkeypatch.setattr(gs, "read_sheet_values",
                            lambda svc, sid, sheet, rng: reads.append(sheet) or
                            [["账户ID"], ["7001" if sheet == "企业户" else "9001"]])
        monkeypatch.setattr(gs, "build_service", lambda p: object())
        client.post("/api/huguan/dashboard/sync", headers=hg,
                    json={"platform": "tt", "dry_run": True})
        assert reads == ["企业户", "加白户"]
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd py && python -m pytest tests/test_huguan_dashboard.py -q -k TestPerTableSync`
Expected: FAIL —— 前三条红（忽略 `sheet_name` ⇒ 读了全部表／不 400）；第四条应已通过

- [ ] **Step 3: 实现**

`dashboard_sync` 里，platform 校验之后加：

```python
    # 按表操作（设计 §3.1）：`sheet_name` 可选。给了就只处理那一张表；缺省＝全部表
    # （与改动前逐字节一致）。gg/fb 只有一张表，按表无意义 ⇒ 直接拒，避免「静默等同全量」
    # 让前端 bug 变成哑巴。
    only_sheet = str(data.get("sheet_name") or "").strip()
    if only_sheet and platform != "tt":
        return err("只有 TT 支持按表操作", 400)
```

`tables = [t for t in tables if t["sheet_name"]]` 之后加：

```python
        # 归属门禁：只能按自己配置里的表操作（与读表头端点同款）；不在里面就 400，
        # 绝不据此去读任意工作表。
        if only_sheet:
            tables = [t for t in tables if t["sheet_name"] == only_sheet]
            if not tables:
                return err(f"工作表「{only_sheet}」不在你的看板配置里", 400)
```

同时加计时（设计 §3.4）——在文件顶部 `import` 区补 `import time`，并加一个模块级小工具：

```python
def _tick(label: str, t0: float) -> float:
    """计时日志（设计 §3.4）：只为定位「慢」，不改任何行为。返回新的起点。"""
    log.info("户管看板 %s 阶段耗时 %.2fs", label, time.perf_counter() - t0)
    return time.perf_counter()
```

在 `dashboard_sync` 的**读取循环前后**、`build_diff` 前后、`apply_diff` 前后各插一次
（`t0 = _tick("读取完成", t0)` 形式），标签分别用「读取完成」「build_diff 完成」「落库完成」。
`log` 已在该模块可用（没有就补 `log = logging.getLogger("gg-server")`）。

- [ ] **Step 4: 跑测试确认通过 + 全文件回归**

Run: `cd py && python -m pytest tests/test_huguan_dashboard.py -q`
Expected: 全绿（既有同步用例走「无 sheet_name」路径，必须一条不红）

- [ ] **Step 5: 提交**

```bash
git commit -m "feat(tt): 同步支持按表（可选 sheet_name + 归属门禁 + 阶段计时）" -- py/routes/huguan_dashboard_routes.py py/tests/test_huguan_dashboard.py
```

---

## Task 2: `push` 支持按表（+ **行过滤**到目标户类型）

**Files:**
- Modify: `py/routes/huguan_dashboard_routes.py`（`dashboard_push`）
- Test: `py/tests/test_huguan_dashboard.py`

**Interfaces:**
- Consumes: Task 1 的 `only_sheet` 解析与 `_tick`
- Produces: `POST /api/huguan/dashboard/push` 接受可选 `sheet_name`

> ⚠️ **最容易做错的地方**：`group_rows_by_sheet`（`py/huguan_dashboard.py:705-731`）**内部重新读配置取全部表**
> —— 所以「只过滤 `tables`」**不管用**，写回照样会覆盖每一张表。必须**过滤「行」**：
> 只保留 `account_type == 目标表 name` 的行，且 `col_maps_by_type` **只解析目标表**
> （顺带省掉其它表的表头读 = 提速）。

> ⚠️ 写测试时注意：push 在写表**前**还会为撤回快照读一次表（`read_sheet_values`），
> 你的 `read_sheet_values` 桩要能同时满足「表头读」与「快照读」两种 range；否则测试会因
> 快照那步红，看不出你要验的东西。若快照读的桩难以兼顾，就在断言里放宽对读取次数的要求，
> 但**必须**保留「只有目标表的 worksheet 被写」这条断言。

- [ ] **Step 1: 写失败测试**

```python
class TestPerTablePush:
    def _conf(self, client, username, tables):
        return TestPerTableSync()._conf(client, username, tables)

    def test_only_the_named_table_is_written(self, client, monkeypatch):
        import google_sheets_service as gs
        hg = self._conf(client, "_pp1", [
            {"name": "企业户", "sheet_name": "企业户"},
            {"name": "加白户", "sheet_name": "加白户"}])
        db = database.get_db()
        db.execute("INSERT INTO tt_accounts(advertiser_id, name, account_type, "
                   "deleted_at) VALUES('8001','甲','企业户','')")
        db.execute("INSERT INTO tt_accounts(advertiser_id, name, account_type, "
                   "deleted_at) VALUES('8002','乙','加白户','')")
        db.commit(); db.close()
        headers_read, written = [], []

        def _fake_read(svc, sid, sheet, rng):
            headers_read.append(sheet)
            return [["账户ID"]]

        monkeypatch.setattr(gs, "read_sheet_values", _fake_read)
        monkeypatch.setattr(gs, "build_service", lambda p: object())
        monkeypatch.setattr(gs, "update_rows_by_account_id",
                            lambda svc, sid, sheet, rows, key_col="C":
                            written.append((sheet, [r["account_id"] for r in rows]))
                            or {"updated": len(rows), "not_found": []})
        resp = client.post("/api/huguan/dashboard/push", headers=hg,
                           json={"platform": "tt", "sheet_name": "企业户"})
        assert resp.status_code == 200, resp.get_json()
        assert headers_read == ["企业户"], f"只该解析目标表的表头，实际 {headers_read}"
        assert written and all(s == "企业户" for s, _ in written), f"实际写了 {written}"
        assert all(ids == ["8001"] for _s, ids in written), f"只该写企业户的账户，实际 {written}"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd py && python -m pytest tests/test_huguan_dashboard.py -q -k TestPerTablePush`
Expected: FAIL —— 两个表都被解析/写入

- [ ] **Step 3: 实现**

`dashboard_push` 里，`tables = hd.get_platform_tables(...)` 之后加：

```python
        # 按表刷新（设计 §3.1/§3.2）：`sheet_name` 可选。
        only_sheet = str(data.get("sheet_name") or "").strip()
        if only_sheet and platform != "tt":
            return err("只有 TT 支持按表操作", 400)
        target_type = None
        if only_sheet:
            target = next((t for t in tables if t["sheet_name"] == only_sheet), None)
            if target is None:
                return err(f"工作表「{only_sheet}」不在你的看板配置里", 400)
            # ⚠️ 只过滤 tables 不够：group_rows_by_sheet 会**重新读配置取全部表** ⇒
            # 必须记住目标户类型，稍后把「行」过滤到它，否则照样写每张表。
            target_type = target["name"]
```

`col_maps_by_sheet` 的推导改为（按表时只解析目标表 ⇒ 省掉其它表的表头读）：

```python
        col_maps_by_sheet = {
            t["sheet_name"]: hd.resolve_table_col_map(
                service, c["spreadsheet_id"], t["sheet_name"], platform,
                t.get("columns") or {})
            for t in (tables if target_type is None
                      else [t for t in tables if t["name"] == target_type])
        }
```

`rows = hd.collect_rows_for_push(...)` 之后加：

```python
        if target_type is not None:
            # 只留目标户类型的账户：写回的是**这张表**，别的表一个格都不碰。
            rows = [r for r in rows if (r.get("account_type") or "") == target_type]
```

同样按 Task 1 的 `_tick` 在「收集完成」「写表完成」处加计时。

- [ ] **Step 4: 跑测试确认通过 + 全文件回归**

Run: `cd py && python -m pytest tests/test_huguan_dashboard.py tests/test_huguan_sheet_write.py tests/test_huguan_undo.py -q`
Expected: 全绿（既有 push 用例走「无 sheet_name」路径）

- [ ] **Step 5: 提交**

```bash
git commit -m "feat(tt): 刷新支持按表（行过滤到目标户类型 + 只解析该表表头）" -- py/routes/huguan_dashboard_routes.py py/tests/test_huguan_dashboard.py
```

---

## Task 3: 跨表归属提示（**只查库**）

**Files:**
- Modify: `py/huguan_dashboard.py`（新增纯函数）
- Modify: `py/routes/huguan_dashboard_routes.py`（两个端点接入）
- Test: `py/tests/test_huguan_dashboard.py`

**Interfaces:**
- Produces: `cross_sheet_notes(db, platform: str, account_ids: list, sheet_name: str, cap: int = 50) -> dict`
  返回 `{"count": int, "notes": [{"account_id": str, "current_type": str, "this_sheet": str}]}`
  —— `count` 是**命中总数**，`notes` 最多 `cap` 条

- [ ] **Step 1: 写失败测试**

```python
class TestCrossSheetNotes:
    """按表操作时，提示「这些账户当前归属另一张表」（A1 的补偿，只查库）。"""

    def test_notes_accounts_belonging_to_another_type(self, client):
        import database
        db = database.get_db()
        db.execute("INSERT INTO tt_accounts(advertiser_id, name, account_type, "
                   "deleted_at) VALUES('7001','甲','加白户','')")
        db.commit()
        got = hd.cross_sheet_notes(db, "tt", ["7001", "7002"], "企业户")
        db.close()
        assert got["count"] == 1
        assert got["notes"] == [{"account_id": "7001", "current_type": "加白户",
                                 "this_sheet": "企业户"}]

    def test_same_type_or_unknown_accounts_are_not_noted(self, client):
        import database
        db = database.get_db()
        db.execute("INSERT INTO tt_accounts(advertiser_id, name, account_type, "
                   "deleted_at) VALUES('7001','甲','企业户','')")
        db.commit()
        got = hd.cross_sheet_notes(db, "tt", ["7001", "7099"], "企业户")
        db.close()
        assert got == {"count": 0, "notes": []}

    def test_cap_keeps_total_count(self, client):
        import database
        db = database.get_db()
        for i in range(5):
            db.execute("INSERT INTO tt_accounts(advertiser_id, name, account_type, "
                       f"deleted_at) VALUES('71{i:02d}','x','加白户','')")
        db.commit()
        got = hd.cross_sheet_notes(db, "tt", [f"71{i:02d}" for i in range(5)],
                                   "企业户", cap=2)
        db.close()
        assert got["count"] == 5 and len(got["notes"]) == 2
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd py && python -m pytest tests/test_huguan_dashboard.py -q -k TestCrossSheetNotes`
Expected: FAIL —— `AttributeError: ... 'cross_sheet_notes'`

- [ ] **Step 3: 实现（`py/huguan_dashboard.py`）**

```python
def cross_sheet_notes(db, platform: str, account_ids: list, sheet_name: str,
                      cap: int = 50) -> dict:
    """按表操作时的「跨表重复」提示（设计 §3.3）：这些账户**当前归属另一张表**。

    为什么只查库：读其它表会抵消按表操作带来的提速（与「只在该表内去重」的初衷冲突）。
    库里的 `account_type` 就是「上一次同步时它来自哪张表」的记账，够用。

    判据：本次同步里出现的账户，其库里 `account_type` 非空且与本次表名不同。
    `count` 给总数（前端能说「共 N 个」），`notes` 最多 `cap` 条（防空表刷爆报告）。
    """
    ids = [a for a in (account_ids or []) if a]
    if not ids:
        return {"count": 0, "notes": []}
    table = _TABLE_FOR_PLATFORM[platform]
    hits = []
    for part in chunk(ids):
        marks = ",".join("?" for _ in part)
        for r in db.execute(
                f"SELECT {ACCOUNT_KEY_FIELD[platform]} AS aid, account_type "
                f"FROM {table} WHERE {ACCOUNT_KEY_FIELD[platform]} IN ({marks}) "
                "AND deleted_at IS NULL", tuple(part)).fetchall():
            cur = _conf_text(r["account_type"])
            if cur and cur != sheet_name:
                hits.append({"account_id": _conf_text(r["aid"]),
                             "current_type": cur, "this_sheet": sheet_name})
    return {"count": len(hits), "notes": hits[:cap]}
```

- [ ] **Step 4: 接进两个端点（只在按表时）**

`dashboard_sync`：算出 diff 后（`apply_diff` 之前，`parsed_rows` 还在作用域里）加

```python
        if only_sheet:
            diff["cross_sheet_notes"] = hd.cross_sheet_notes(
                db, platform, [p.get("account_id") for p in parsed_rows], only_sheet)
```

`dashboard_push`：`rows` 过滤之后加同样的键到返回值（`result` 里加
`result["cross_sheet_notes"] = hd.cross_sheet_notes(db, platform, [r["account_id"] for r in rows], only_sheet)`；
注意 push 的 `db` 在 `finally` 里已关 —— 用**该函数内仍活着的那个连接**，或在收集阶段就把账号列表存下来、
在 `db.close()` 之前算好）。

- [ ] **Step 5: 跑测试确认通过 + 全量后端回归**

Run: `cd py && python -m pytest tests/ -q`
Expected: 全绿

- [ ] **Step 6: 提交**

```bash
git commit -m "feat(tt): 按表同步/刷新时提示「这些账户当前属于别的表」（只查库）" -- py/huguan_dashboard.py py/routes/huguan_dashboard_routes.py py/tests/test_huguan_dashboard.py
```

---

## Task 4: 视觉确认（`/frontend-design`，小范围）

**Files:**
- 产出：追加到本计划的「## 视觉规格（Task 4 产出）」小节

- [ ] **Step 1: 调技能**

对「每张 TT 表那一行的两个小按钮（导入这张表 / 刷新回这张表）+ 平台级按钮改名 + 单表差异弹窗标题」
调用 `/frontend-design`。**不引入新的视觉语言**（沿用既有卡片与 Element Plus），只定：
按钮的**主次**（哪个 primary）、**图标**（⬇️/⬆️ 与既有平台级一致）、**间距**（与表名/工作表名同行还是换行）、
**进行中的禁用态**、以及**单表弹窗标题**的写法。

- [ ] **Step 2: 写进本计划「视觉规格」小节**（Task 5 要照它做，不得让它去猜）。

- [ ] **Step 3: 提交**

```bash
git commit -m "docs(per-sheet-sync): 按表按钮与单表弹窗的视觉规格" -- docs/superpowers/plans/2026-10-10-per-sheet-sync.md
```

---

## Task 5: 前端接线（每表两按钮 + 单表弹窗 + 并发禁用）

**Files:**
- Modify: `frontend/src/components/HuguanDashboardCard.vue`
- Modify: `frontend/src/api/huguan.js`（`sync`/`push` 透传 `sheet_name`）

- [ ] **Step 1: API 透传**

`huguanApi.sync(body)` 已经是透传整包，`push(platform)` 目前只收 platform ⇒ 改为
`push: (platform, sheetName) => api.post('/huguan/dashboard/push', sheetName ? { platform, sheet_name: sheetName } : { platform })`
（缺省不发该键 ⇒ 与现状逐字节一致）。

- [ ] **Step 2: 每表两个按钮**

在 tt 多表循环里、每个表项（户类型名 + 工作表名）那一行加两个 `size="small"` 按钮：
「导入这张表」（调既有单表同步流程，body 带 `sheet_name`）、「刷新回这张表」（同上，走 push）。
**平台级两个按钮**在 tt 下改名「全部导入」「全部刷新」（gg/fb 不改）。

- [ ] **Step 3: 单表差异弹窗**

复用现有差异弹窗：单表时标题带表名（如「企业户 · 差异报告」）、**隐藏「表」列**、
并在有 `cross_sheet_notes` 时多显示一节（文案照视觉规格）：说明这几个账户当前属于别的表、
本次按这张表同步可能覆盖它们的字段。

- [ ] **Step 4: 并发禁用**

任一按表/平台级操作进行中 ⇒ **禁用全部**（按表与平台级）按钮（用户裁定：禁止并发）。

- [ ] **Step 5: 自查 + 构建**

Run: `cd frontend && npm test && npx vite build`
Expected: 测试绿、构建通过（`dist/` 已 gitignore）

- [ ] **Step 6: 提交**

```bash
git commit -m "feat(tt-ui): 每张表各自的「导入这张表 / 刷新回这张表」+ 单表弹窗与跨表提示" -- frontend/src/components/HuguanDashboardCard.vue frontend/src/api/huguan.js
```

---

## Task 6: 收尾（全量回归 + 验收清单补项）

**Files:**
- Modify: `docs/superpowers/plans/2026-10-10-per-sheet-sync.md`（验收清单）

- [x] **Step 1: 两套全量** —— 2026-10-10 于 `5d87f81` 实跑

Run: `cd py && python -m pytest tests/ -q`
Result: **1905 passed, 0 failed**（555.25s，1631 warnings）

Run: `cd frontend && npm test`
Result: **36 passed, 0 failed**（`node --test`，36 条纯逻辑用例；`tests 36 / pass 36 / fail 0`）

- [x] **Step 2: 写验收清单进本计划**

逐条写清「怎么点、看什么、期望什么」，交给用户在自己的服务上执行（本计划**不启动任何进程**）。

#### 验收清单（用户手工执行 · 整体验收）

> **这是一次「整体验收」：本轮的按表导入/回写 + 上一轮 TT 表头映射两批，合成一次跑完。**
> 上一轮（列映射面板 / 未采集列 / 同名列）的清单在
> `docs/superpowers/plans/2026-10-10-tt-header-mapping-frontend.md` 文末的
> 「### 验收清单（用户手工执行 · 两批合一）」（其「记录表」在文末）。**本清单不重复它的条目**，
> 只在其记录表上勾。
>
> ⚠️ **上一轮那批条目本轮仍要全部重跑**（A1–A8 / B1–B3 / C4 / D1–D5 的勾都还空着），原因有二：
> 1. 本轮改动落在**同一张卡片的同一段交互**上 —— 每张表那一行（列映射折叠标题与按表按钮同行）；
> 2. Task 5 把**按表刷新改成走既有确认弹窗**（`pushDlg`），而平台级刷新弹窗是**同一处渲染**，
>    也就是本轮动过上一轮验收赖以成立的那段代码路径。
>
> ⇒ **先**照上一轮清单跑完（尤其 A1/A2/B1/B2/B3），**再**跑本清单。

##### 0 · 前置（一次性）

- 浏览器打开 TT 设置页 → 「户管看板」卡片；确认「户类型」里至少有 **企业户** 与 **加白户** 两张表，
  且各自的工作表名已保存（点过「💾 保存配置」）。
- 建议在**测试用表格**上做（下面几步要往表里加/改名一列、清空工作表名）。
- 每张要验的表里**必须有一列表头叫「账户ID」**（定位键，否则同步会被拒）。
- 打开 **F12 → Network** 面板 —— 本清单里「到底有没有真的发请求」要靠它判定。

##### 一 · 按表导入（P1 · P2 · P9）

**P1 · 按表导入只出该表差异**
- 怎么点：在 TT 卡片里，找到「企业户」那一行，点右侧的「**⬇️ 导入这张表**」。
- 看什么 / 期望：
  - 弹出差异弹窗，标题是「**企业户 · 差异报告**」（**带表名**，与平台级光秃秃的「差异报告」区分）；
  - 弹窗里**没有「表」这一列**（只有一张表，表列恒为同值）；
  - 列表里**只有企业户行的差异** —— 加白户那张表的账户（例如 9001）**一行都不出现**。
- 看完关掉弹窗（本步只预演，先**别**点确认落库）。

**P2 · 归属门禁：非配置内的表名 ⇒ 400，且**不**发起读取**
- 怎么点：在「企业户」那一行的「工作表」输入框里，把名字改成配置里**没有**的名字（例如「瞎写的表」），
  **先别保存**；然后点这一行的「⬇️ 导入这张表」。
- 期望：
  - 右上角弹错误提示，文案含这个假表名，形如「工作表「瞎写的表」不在你的看板配置里」（HTTP **400**）；
  - F12 → Network 里**只看到一次** `/api/huguan/dashboard/sync` 请求且**立即 400 返回**，
    **没有**后续的读表请求（**不发起读取**）—— 这条是本设计的硬约束。
- 验完把名字**改回去**。

**P9 · 跨表提示节**
- 前置：制造「账户当前归属 ≠ 本次同步的表」。例如企业户表里有一个账户 7001，把系统里 7001 的**户类型
  改成「加白户」**（或反向：让原属加白户的 9001 在库里落成「企业户」）。
- 怎么点：回到 7001 **原本**那张表（例：企业户），点「⬇️ 导入这张表」。
- 期望：差异弹窗里多出一节 ——
  - 标题「**这些账户当前属于别的表**」；
  - 区顶一行灰字「本次按「企业户」同步可能覆盖它们的字段。」（**表名随你点的那张表变**）；
  - 每条一行：`账户ID` + 当前户类型（灰底小标签，`el-tag type="info"`）；
  - 命中**超过 50 条**时，末尾多一行「**等共 N 个**」（N 是**命中总数**，不是显示条数）。
- 注意：这一节**只在按表导入时**出现；平台级「全部导入」**不出现**（见 P4）。

##### 二 · 按表刷新（P3）

**P3 · 按表刷新必须先出确认弹窗；取消 ⇒ 一个格都不写**
- 怎么点（**先验取消**）：在「企业户」那一行点「**⬆️ 刷新回这张表**」。
  - 期望：**先弹出一个确认弹窗**（**不是**点一下就写表）；弹窗体里有一行范围说明
    「**范围：仅「企业户」**」（放在既有说明行旁边，**不是**塞进那两张列表格里）。
  - 点「**取消**」→ 弹窗关闭，**表格一个格都没动**（刷新表格页确认，或看 Network 里**没有**写表请求）。
- 再验确认写表：再点一次「⬆️ 刷新回这张表」→ 这次点「**确认刷新**」。
  - 期望：**只有企业户那张 worksheet 被写**；加白户那张 worksheet **一个格不动**
    （前后 diff 那张表应为零变化）。
  - F12 → Network 里的 `/api/huguan/dashboard/push` 请求体**带着 `sheet_name`**
    （形如 `{"platform":"tt","sheet_name":"企业户"}`）。

##### 三 · 平台级（P4 · P10）—— 含一处**有意的**规格订正

**P4 · 平台级两点行为与改动前一致（弹窗多一行「范围：全部表」＝有意订正，不是回归）**
- 怎么点：点卡片底部平台的「**⬇️ 全部导入**」→ 与改动前一致：弹差异弹窗、**含「表」列**、
  **不出现**跨表提示节。再点「**⬆️ 全部刷新**」→ 先弹确认弹窗，点「确认刷新」后才写**每一张**表。
- ⚠️ **唯一可见差异**：这个刷新确认弹窗里**多了一行「范围：全部表」**。这是本轮**有意**的规格订正
  （按表刷新改走同一个 `pushDlg`，弹窗体里必须标范围）——**请按「预期如此」验收，不要当成回归。**

**P10 · gg/fb 无按表按钮、平台级文案不变**
- 怎么点：切到 **GG** 卡片、**FB** 卡片（各自的户管看板卡片）。
- 期望：
  - **没有**「导入这张表 / 刷新回这张表」两个按表按钮（结构上只存在于 tt 分支）；
  - 平台级按钮文案与改动前**逐字相同**（「全部导入 / 全部刷新」只对 tt 改名）；
  - F12 → Network 里 gg/fb 的 sync/push 请求体**不含 `sheet_name` 键**（载荷逐字节不变）；
  - 唯一例外仍是 P4 那行「范围：全部表」（gg/fb 的刷新确认弹窗里也会有）。

##### 四 · 撤回（P5）

**P5 · 按表同步 → 撤回只回退该表那一次；全部导入 → 撤回回退那一次**
- 怎么点，按顺序：
  1. 企业户点「⬇️ 导入这张表」→ 点确认**落库**（确保这次确实改了企业户的某些字段）。
  2. 点卡片上的**撤回**（「撤回上一次」）。
  - 期望：**只回退企业户这次的变化**；**加白户那张表完全没被这次撤回碰到**。
  3. 再做一次**平台级**「⬇️ 全部导入」→ 确认落库 → 点撤回。
  - 期望：回退的是**那一次全部同步**的变化（撤回语义仍是「撤上一次操作」，本轮未改）。
- 关键点：按表**落库**那一步也带 `sheet_name`（后端 `applySync` 在 `dry_run:false` 时会重新读表）——
  所以第 1 步在 Network 里，`/sync` 的 **dry_run:false** 请求体里**也应看到 `sheet_name`**。

##### 五 · 交互细节（P6 · P7 · P8）

**P6 · 空表名 ⇒ 该行两按钮禁用**
- 怎么点：清空「企业户」那一行的「工作表」输入框（把名字删掉，**先别保存**）。
- 期望：该行两个按钮（导入这张表 / 刷新回这张表）**都变灰不可点**；鼠标悬停给出提示
  「**先在左边填这张表的工作表名**」。
- 把名字填回去，按钮恢复可点。

**P7 · 并发禁用 + loading + 该行灰字**
- 怎么点：触发一次要花点时间的操作（按表导入即可），在它**进行中**观察整张卡片。
- 期望：
  - 卡片上**所有**相关按钮（按表两按钮 + 平台级两按钮）**全部 disabled**（用户裁定：禁止并发）；
  - 只有**被点的那一个**在转圈（loading）；
  - 该行下方出现一行 12px 灰字（`#6b7280`）「**正在处理「企业户」，请稍候…**」；
  - 操作结束后，按钮恢复、灰字消失。

**P8 · 展开「列映射」后两按钮仍在标题那一行**
- 怎么点：点「企业户」那一行的「**列映射 ▸**」展开。
- 期望：展开 / 收起**都不影响**两个按表按钮的位置 —— 它们**始终在「列映射」这一行**
  （`hd-sheet-actions` 高度固定 48px），**不会**被挤到下一行、也不会掉进折叠区里。

**P8b · tooltip 不叠加（tt 配置完好 vs 未配置）**
- 怎么点：鼠标悬停卡片底部的平台级按钮。
  - 配置完好时：提示「**所有表：企业户、加白户**」（列出所有表名）；
  - 把「表格地址」(`spreadsheet_id`) 清空（**先别保存**）后再悬停：只显示「**请先填写表格地址…**」。
- 期望：两种提示**不叠加** —— 未配置时**只**出现后一条，不会同时出现表名列表。

##### 六 · 服务端观测（P11 · P12）

**P11 · 缺省＝全部表不变（后端侧）**
- 不做任何按表操作，直接点平台级「⬇️ 全部导入」。
- 期望：差异与改动前一致（所有表都读、跨表去重、整批定位键校验都在）——
  即「**不带 `sheet_name`**」的路径行为**逐字节不变**。

**P12 · 计时日志能在服务日志里看到各阶段耗时**
- 怎么点：跑一次平台级（或按表）同步 / 刷新，然后看**服务端日志输出**（运行 Flask 的那个控制台窗口）。
- 期望：能看到形如
  `户管看板 读取完成 阶段耗时 X.XXs` / `户管看板 build_diff 完成 阶段耗时 X.XXs` /
  `户管看板 落库完成 阶段耗时 X.XXs`（push 侧为「收集完成 / 写表完成」）的 `INFO` 行。
- 用途：据此判断「读取」是否是大头，决定要不要做 read-scope 收窄（本轮**不做**，只观测）。

##### 记录表（验完把结果填这里）

| 组 | 项 | 结果 |
|---|---|---|
| P1 | 按表导入：只出该表差异 + 标题带表名 + 无「表」列 | ☐ |
| P2 | 归属门禁：非配置表名 ⇒ 400 且**不发起读取** | ☐ |
| P3 | 按表刷新：先出确认弹窗（含「范围：仅「<表名>」」），取消 ⇒ 一个格不写 | ☐ |
| P3 | 按表刷新：确认后只写该 worksheet（别的表零变化） | ☐ |
| P4 | 平台级两点行为与改动前一致（弹窗多一行「范围：全部表」＝有意订正） | ☐ |
| P5 | 撤回：按表那次只回退该表；全部那次回退那一次 | ☐ |
| P6 | 空表名 ⇒ 该行两按钮禁用 + tooltip | ☐ |
| P7 | 并发：全禁 + 被点者转圈 + 该行灰字 | ☐ |
| P8 | 展开「列映射」后两按钮仍在标题行 | ☐ |
| P8b | tooltip 不叠加（所有表：… / 请先填写表格地址…） | ☐ |
| P9 | 跨表提示出现；超 50 条有「等共 N 个」 | ☐ |
| P10 | gg/fb 无按表按钮、平台级文案不变（含「范围：全部表」例外） | ☐ |
| P11 | 缺省＝全部表不变 | ☐ |
| P12 | 计时日志可见各阶段耗时 | ☐ |
| — | 上一轮 TT 表头映射两批（A1–A8 / B1–B3 / C4 / D1–D5） | ☐ 见另一计划文末 |

- [ ] **Step 3: 提交**

```bash
git commit -m "docs(per-sheet-sync): 验收清单" -- docs/superpowers/plans/2026-10-10-per-sheet-sync.md
```

---

## 视觉规格（Task 4 产出）

### 定位

这是**既有卡片里每张表那一行**的局部增强，**不引入新视觉语言**（沿用 Element Plus + 卡片既有的
`#e6a23c` 警告橙 / `#6b7280` 次要灰 / `el-tag` 灰底标签 / 12–14px 字号）。可支配的「大胆」只有一处：
**让「我操作的是哪一张表」一眼可见** —— 每表两个按钮存在的全部意义就是消除这个歧义。

### 版式（表项那一行）

```
┌──────────────────────────────────────────────────────────────┐
│ 户类型 [企业户        ]  工作表 [企业户        ]      ⊖ 删除  │
│ 列映射 ▸              [⬇ 导入这张表] [⬆ 刷新回这张表]         │
└──────────────────────────────────────────────────────────────┘
```

- 两个按钮放在**该表项自己的行内右端**（与「删除」同一层级），`size="small"`。
- **两个都不做 `primary`**（都用 `plain`）：平台级那两个才是主行动，两层都抢主色会让层级失效。
  这是刻意的克制 —— 一个界面里只留一处最响。
- 图标沿用既有语言：**⬇️** 导入（表 → 系统）／**⬆️** 刷新（系统 → 表），与平台级按钮同款。
- 间距：两按钮之间 `8px`；与左侧「列映射」折叠标题之间至少 `24px`，避免被误读成折叠区的一部分。
- 文案用「**这张表**」而不是「该表/此表」——与用户自己的说法一致（「对应的 sheet 就点对应的导入」）。

### 平台级按钮（卡片底部那排）

- **tt 下改文案**：「⬇️ 全部导入」「⬆️ 全部刷新」，并给 tooltip「所有表：<表名1>、<表名2>…」。
- **gg/fb 不改**（只有一张表，按表无意义，文案与行为逐字节不变）。

### 状态

| 状态 | 表现 |
|---|---|
| 空闲 | 两个按钮常态可点 |
| 进行中 | **所有**相关按钮 `disabled`（用户裁定禁止并发）+ 被点的那个显示 `loading` |
| 禁用说明 | 禁用期间该行下方一行灰字（12px `#6b7280`）：「正在处理「企业户」，请稍候…」——否则用户会以为界面坏了 |
| 单表差异弹窗 | 标题「**企业户 · 差异报告**」（与平台级「差异报告」区分）；弹窗内**隐藏「表」列**（恒为同一张表） |
| 跨表提示节 | 仅单表同步且命中时出现。标题「**这些账户当前属于别的表**」；区顶一行说明「本次按「企业户」同步可能覆盖它们的字段。」；每条 `账户ID` + 当前户类型（灰底 `el-tag`）；条数超上限时末尾一行「等共 N 个」 |

### 不做

- 不加新图标、不加动效、不加编号。
- 不在每张表那行重复平台级的「全部」按钮。

### ⚠️ 订正（2026-10-10 实现时对照代码发现，原文写错了）

原文写「**不给按表按钮加确认弹窗**（刷新是既有行为，只是范围变小）」—— **错**：
平台级刷新**本来就是两段式**（「🔄 刷新到看板」先开 `pushDlg` 解释「会被写成/不会改动的列」，再点「确认刷新」
才写表，`HuguanDashboardCard.vue:286-307`）。按表刷新若点一下就写表，既与既有不一致，又是**更危险**的那个
（范围小 ≠ 误点无害）。

⇒ **按表刷新走同一个 `pushDlg`**：弹窗加一个范围（`pushDlg.sheet`），体里标一行
「范围：仅「企业户」」/「范围：全部表」（放既有说明行旁边，别塞进列表格 —— 那两张表格讲的是**列**，与范围无关）；
`doPushHd` 把范围透传下去（`null` 时不发该键 ⇒ 平台级载荷逐字节不变）。

### 另一处计划漏项（实现时发现）

**确认落库那一步（`applySync`）也必须带 `sheet_name`**：后端 `dashboard_sync` 在 `dry_run: false` 时会
**重新读表**，不带该键则①别的表缺「账户ID」会**误拒**这次按表落库，②撤回快照会覆盖**全部表**、破坏裁定 B
（验收第 7 条）。交互流程不变，只是多一个请求键。
