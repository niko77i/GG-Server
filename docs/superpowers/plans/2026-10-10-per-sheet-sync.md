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

- [ ] **Step 1: 两套全量**

Run: `cd py && python -m pytest tests/ -q`；`cd frontend && npm test`
Expected: 全绿（记录真实数字）

- [ ] **Step 2: 写验收清单**（用户手动执行），至少覆盖：

1. **按表导入**：TT 卡片上某张表点「导入这张表」⇒ 只出该表的差异；另一张表的行**不得**出现。
2. **按表刷新**：点「刷新回这张表」⇒ 只有那张 worksheet 被写（别的表一个格不动）。
3. **缺省不变**：平台级「全部导入 / 全部刷新」行为与改动前一致。
4. **归属门禁**：改工作表名成配置里没有的名字再点按表按钮 ⇒ 400 提示，且**没有**发起读取。
5. **跨表提示**：把某账户的类型改成另一张表 ⇒ 在另一张表里点「导入这张表」⇒ 报告里出现该提示。
6. **并发禁用**：一次按表操作进行中，其它按钮为禁用态。
7. **撤回仍是「撤上一次操作」**：按表同步 → 撤回 ⇒ 只回退那张表这次的变化；再做一次**全部**同步 → 撤回 ⇒ 回退那一次。
8. **计时日志**：跑一次同步/刷新，在服务日志里应能看到各阶段耗时（据此决定是否要做读范围收窄）。

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
- 不给按表按钮加确认弹窗（导入本来就有差异弹窗这道闸；刷新是既有行为，只是范围变小）。
- 不在每张表那行重复平台级的「全部」按钮。
