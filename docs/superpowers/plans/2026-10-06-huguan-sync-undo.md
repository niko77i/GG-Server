# 户管看板同步撤回 Implementation Plan（子项目 ③）

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 给户管看板的两个手动同步按钮各加一个「撤回上一次」，覆盖 gg / tt / fb 三个平台。

**Architecture:** 新建一张 `huguan_sync_undo` 表存快照（`UNIQUE(user_id, platform, direction)` ⇒ 每个户管每平台每方向只留最近一条）。系统→表方向存**整片将被写格子的原值**，撤回时无条件写回；表→系统方向存**增量改动**（列级旧值 + 新建对象），撤回时用 **compare-and-swap** 只回滚「没被别人动过」的部分，且**先回退表、再回退库**。

**Tech Stack:** Python 3 + Flask + sqlite3（原生 SQL）；Vue 3 + Element Plus；pytest + Flask test client。

## Global Constraints

- 设计依据：`docs/superpowers/specs/2026-10-06-huguan-sync-undo-design.md`。与本文冲突时以该 spec 为准。
- **本计划的示例代码与行号是编写时的快照。本仓库有并行会话持续改动这些文件，落笔前必须核对现行代码。发现计划与现行代码不符时，以现行代码为准，并在报告里记录偏差。**（② 的计划因此被实现者抓出 17 处「照抄就会失败」，这条是为此加的。）
- **纯增量**：GG / TT / FB 的既有行为**逐字节不变**。本计划只新增表、新增函数、新增路由、在既有函数里插入快照收集。
- **撤回只覆盖两个手动按钮**（`dashboard_push` / `dashboard_sync`），**不覆盖自动回写**（`writeback_rows` / `writeback_owner_channel` / `writeback_fb_acceptor`）。
- **快照只在「该次写入完整成功」后才有资格被撤回**：写入失败或抛异常 → 删除快照。
- **表→系统撤回的顺序铁律：先回退表，再回退库。** 反了会让下次同步把撤回又自动撤销掉（spec §6.2 有推演）。
- **表侧回退必须按平台分流**（spec §3.3）：GG 撤销运营列 + 清空通道列；TT 只撤运营列（**无通道列可清**）；FB 撤在用运营列 + 接户运营列。
- 新增表 `huguan_sync_undo` 必须**同时**加进 `admin_delete_user` 的关联清理清单（spec §5.4）。
- 提交时**只 `git add` 本任务明确列出的文件**，禁止 `git add -A`。
- 测试门禁：`cd py && python -m pytest tests/ -q`（基线 **1130 passed**，2026-10-06 实测），只增不减。前端门禁：`cd frontend && npm run build`。

---

## File Structure

| 文件 | 动作 | 职责 |
|---|---|---|
| `py/database.py` | 修改 | 建 `huguan_sync_undo` 表 |
| `py/huguan_dashboard.py` | 修改 | 快照读写、push/sync 两个方向的收集与回退逻辑（纯逻辑层，不 import flask） |
| `py/routes/huguan_dashboard_routes.py` | 修改 | `GET`/`POST /api/huguan/dashboard/undo`；在 push/sync 两个端点里接上快照 |
| `py/main.py` | 修改 | `admin_delete_user` 清理 `huguan_sync_undo` |
| `py/tests/test_huguan_undo.py` | 新建 | 本子项目的全部后端测试 |
| `frontend/src/api/huguan.js` | 修改 | `getUndo` / `doUndo` |
| `frontend/src/components/HuguanDashboardCard.vue` | 修改 | 两个「↩️ 撤回上次」按钮 + 结果报告 |

---

## Task 1: 快照表的读写原语

**Files:**
- Modify: `py/database.py`
- Modify: `py/huguan_dashboard.py`
- Test: `py/tests/test_huguan_undo.py`（新建）

**Interfaces:**
- Consumes: 无
- Produces: 模块级常量与三个函数
  - `UNDO_DIRECTIONS = ("push", "sync")`
  - `save_undo(db, user_id: int, platform: str, direction: str, payload: dict) -> None`（`INSERT OR REPLACE`）
  - `load_undo(db, user_id: int, platform: str, direction: str) -> dict | None`
  - `delete_undo(db, user_id: int, platform: str, direction: str) -> None`

- [ ] **Step 1: 写失败测试**

新建 `py/tests/test_huguan_undo.py`：

```python
"""户管看板同步撤回（子项目 ③）测试。

设计见 docs/superpowers/specs/2026-10-06-huguan-sync-undo-design.md。
本文件不打真实 Google API。
"""
import pytest

import database
import huguan_dashboard as hd


@pytest.fixture
def fb_user(client):
    """一个 FB 平台的户管，返回其 id。"""
    db = database.get_db()
    db.execute("INSERT INTO users(username, password, role, platform) "
               "VALUES('u_undo', 'x', 'huguan', 'fb')")
    uid = db.execute("SELECT last_insert_rowid()").fetchone()[0]
    db.commit()
    db.close()
    return uid


class TestUndoPrimitives:
    def test_table_exists(self, client):
        db = database.get_db()
        cols = {r[1] for r in db.execute("PRAGMA table_info(huguan_sync_undo)").fetchall()}
        db.close()
        assert {"id", "user_id", "platform", "direction", "created_at", "payload"} <= cols

    def test_save_then_load(self, client, fb_user):
        db = database.get_db()
        hd.save_undo(db, fb_user, "fb", "push", {"cells": [{"account_id": "A1"}]})
        db.commit()
        got = hd.load_undo(db, fb_user, "fb", "push")
        db.close()
        assert got == {"cells": [{"account_id": "A1"}]}

    def test_load_missing_returns_none(self, client, fb_user):
        db = database.get_db()
        got = hd.load_undo(db, fb_user, "fb", "sync")
        db.close()
        assert got is None

    def test_save_is_idempotent_last_wins(self, client, fb_user):
        """UNIQUE(user_id, platform, direction) ⇒ 只留最近一条。"""
        db = database.get_db()
        hd.save_undo(db, fb_user, "fb", "push", {"v": 1})
        hd.save_undo(db, fb_user, "fb", "push", {"v": 2})
        db.commit()
        n = db.execute("SELECT COUNT(*) FROM huguan_sync_undo "
                       "WHERE user_id=? AND platform='fb' AND direction='push'",
                       (fb_user,)).fetchone()[0]
        got = hd.load_undo(db, fb_user, "fb", "push")
        db.close()
        assert n == 1
        assert got == {"v": 2}

    def test_platforms_and_directions_are_independent(self, client, fb_user):
        db = database.get_db()
        hd.save_undo(db, fb_user, "fb", "push", {"k": "fb-push"})
        hd.save_undo(db, fb_user, "fb", "sync", {"k": "fb-sync"})
        hd.save_undo(db, fb_user, "gg", "push", {"k": "gg-push"})
        db.commit()
        assert hd.load_undo(db, fb_user, "fb", "push") == {"k": "fb-push"}
        assert hd.load_undo(db, fb_user, "fb", "sync") == {"k": "fb-sync"}
        assert hd.load_undo(db, fb_user, "gg", "push") == {"k": "gg-push"}
        db.close()

    def test_delete(self, client, fb_user):
        db = database.get_db()
        hd.save_undo(db, fb_user, "fb", "push", {"v": 1})
        db.commit()
        hd.delete_undo(db, fb_user, "fb", "push")
        db.commit()
        assert hd.load_undo(db, fb_user, "fb", "push") is None
        db.close()

    def test_two_users_do_not_share(self, client, fb_user):
        db = database.get_db()
        db.execute("INSERT INTO users(username, password, role, platform) "
                   "VALUES('u_undo2', 'x', 'huguan', 'fb')")
        uid2 = db.execute("SELECT last_insert_rowid()").fetchone()[0]
        hd.save_undo(db, fb_user, "fb", "push", {"who": 1})
        db.commit()
        assert hd.load_undo(db, uid2, "fb", "push") is None
        db.close()

    def test_unknown_direction_rejected(self, client, fb_user):
        db = database.get_db()
        with pytest.raises(ValueError):
            hd.save_undo(db, fb_user, "fb", "redo", {"v": 1})
        db.close()
```

- [ ] **Step 2: 跑测试确认失败**

```bash
cd py && python -m pytest tests/test_huguan_undo.py -q
```

Expected: FAIL —— `no such table: huguan_sync_undo` / `AttributeError: ... save_undo`。

- [ ] **Step 3: 建表**

在 `py/database.py` 的 `_ensure_schema` 里，`fb_asset_types` 那一段 `CREATE TABLE` **之后**插入：

```sql
        -- 户管看板同步撤回快照（子项目 ③）。
        -- UNIQUE(user_id, platform, direction) 实现「每个户管每平台每方向只留最近一条」，
        -- 写入用 INSERT OR REPLACE，不需要清理策略。
        -- ⚠️ user_id 无 ON DELETE，且连接开着 PRAGMA foreign_keys=ON ⇒
        -- admin_delete_user 必须一并删除本表的行，否则删任何用过看板的户管都会
        -- FOREIGN KEY constraint failed（见本计划 Task 6）。
        CREATE TABLE IF NOT EXISTS huguan_sync_undo (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id     INTEGER NOT NULL REFERENCES users(id),
            platform    TEXT    NOT NULL,
            direction   TEXT    NOT NULL,
            created_at  TEXT    DEFAULT (datetime('now','localtime')),
            payload     TEXT    NOT NULL DEFAULT '{}',
            UNIQUE(user_id, platform, direction)
        );
```

- [ ] **Step 4: 实现三个原语**

在 `py/huguan_dashboard.py` 的 `get_platform_config` / `save_config` 那一节**之后**插入：

```python
# ---------- 子项目 ③：同步撤回的快照原语 ----------

UNDO_DIRECTIONS = ("push", "sync")


def save_undo(db, user_id: int, platform: str, direction: str, payload: dict) -> None:
    """写入/覆盖某户管某平台某方向的撤回快照。

    `UNIQUE(user_id, platform, direction)` + `INSERT OR REPLACE` ⇒ 天然「只留最近一条」。
    **不 commit**：与调用方共用事务（快照必须与它描述的那次写入同生共死）。
    """
    if direction not in UNDO_DIRECTIONS:
        raise ValueError(f"不支持的撤回方向: {direction}")
    db.execute("INSERT OR REPLACE INTO huguan_sync_undo(user_id, platform, direction, payload) "
               "VALUES(?,?,?,?)",
               (user_id, platform, direction, json.dumps(payload, ensure_ascii=False)))


def load_undo(db, user_id: int, platform: str, direction: str) -> dict | None:
    """读某方向的快照；没有或 JSON 坏掉都返回 None（撤回入口据此禁用）。"""
    row = db.execute("SELECT payload FROM huguan_sync_undo "
                     "WHERE user_id=? AND platform=? AND direction=?",
                     (user_id, platform, direction)).fetchone()
    if not row or not row["payload"]:
        return None
    try:
        loaded = json.loads(row["payload"])
    except Exception:
        return None
    return loaded if isinstance(loaded, dict) else None


def delete_undo(db, user_id: int, platform: str, direction: str) -> None:
    """作废某方向的快照。**不 commit**。"""
    db.execute("DELETE FROM huguan_sync_undo "
               "WHERE user_id=? AND platform=? AND direction=?", (user_id, platform, direction))
```

> `json` 已在模块顶部 import（`save_config` 在用）；`log` 同。

- [ ] **Step 5: 跑测试确认通过**

```bash
cd py && python -m pytest tests/test_huguan_undo.py -q
```

Expected: PASS。

- [ ] **Step 6: 跑全量回归并提交**

```bash
cd py && python -m pytest tests/ -q
git add py/database.py py/huguan_dashboard.py py/tests/test_huguan_undo.py
git commit -m "feat(undo): huguan_sync_undo 表 + 快照读写原语

UNIQUE(user_id, platform, direction) 实现「只留最近一条」；
save/load/delete 三个原语，load 对坏 JSON 返回 None。"
```

---

## Task 2: push 方向的快照记录与撤回

**Files:**
- Modify: `py/huguan_dashboard.py`
- Modify: `py/routes/huguan_dashboard_routes.py`（`dashboard_push` 接上）
- Test: `py/tests/test_huguan_undo.py`（追加）

**Interfaces:**
- Consumes: Task 1 的 `save_undo` / `load_undo` / `delete_undo`
- Produces:
  - `snapshot_push_targets(service, conf, platform, rows) -> dict` —— 读整片表，返回 `{"spreadsheet_id":…, "sheet_name":…, "cells": [{account_id, cells:{列: 原值}}]}`，**只含真正会写到的行/格**
  - `push_undo_cells(payload) -> list` —— 把快照转成 `update_rows_by_account_id` 的入参形状

> **为什么 push 的撤回是「无条件写回」**：push 的语义是「整表对齐到系统」，撤回就是退回对齐之前。中间发生的自动回写会在下次 push 时重新对齐。不做 CAS（spec §6.1）。

- [ ] **Step 1: 写失败测试**

追加到 `py/tests/test_huguan_undo.py`：

```python
class FakeService:
    """假 Sheets 服务：只记下写入了什么，不打网络。"""
    def __init__(self):
        self.writes = []


class TestPushSnapshot:
    def test_snapshot_only_covers_rows_present_in_sheet(self, client, fb_user, monkeypatch):
        """表里没有的账户本来就不会被写，不进快照。"""
        db = database.get_db()
        db.execute("INSERT INTO fb_accounts(name, account_id, owner_id) VALUES('户','U1',?)",
                   (fb_user,))
        db.execute("INSERT INTO fb_accounts(name, account_id, owner_id) VALUES('户2','U2',?)",
                   (fb_user,))
        db.commit()
        rows = hd.collect_rows_for_push(db, "fb")
        db.close()

        # 假表：只有 U1 在表里
        grid = [[""] * 17, [""] * 17]
        grid[1][hd.col_index("D")] = "U1"
        monkeypatch.setattr(hd, "read_sheet_values",
                            lambda svc, sid, name, rng: grid)

        payload = hd.snapshot_push_targets(
            FakeService(), {"spreadsheet_id": "S", "sheet_name": "N"}, "fb", rows)
        ids = [c["account_id"] for c in payload["cells"]]
        assert ids == ["U1"]

    def test_snapshot_records_only_columns_that_will_be_written(self, client, fb_user, monkeypatch):
        db = database.get_db()
        db.execute("INSERT INTO fb_accounts(name, account_id, owner_id) VALUES('户','U3',?)",
                   (fb_user,))
        db.commit()
        rows = hd.collect_rows_for_push(db, "fb")
        db.close()

        grid = [[""] * 17, [""] * 17]
        grid[1][hd.col_index("D")] = "U3"
        grid[1][hd.col_index("C")] = "表里的旧名"
        grid[1][hd.col_index("I")] = "不该被记"
        monkeypatch.setattr(hd, "read_sheet_values",
                            lambda svc, sid, name, rng: grid)

        payload = hd.snapshot_push_targets(
            FakeService(), {"spreadsheet_id": "S", "sheet_name": "N"}, "fb", rows)
        cells = payload["cells"][0]["cells"]
        # C 列会被批量写（writable=True）⇒ 必须记
        assert cells.get("C") == "表里的旧名"
        # I 列 writable=False ⇒ 批量根本不写它，不该进快照
        assert "I" not in cells

    def test_undo_cells_are_writable_input(self, client, fb_user, monkeypatch):
        payload = {"spreadsheet_id": "S", "sheet_name": "N",
                   "cells": [{"account_id": "U1", "cells": {"C": "旧", "G": "9"}}]}
        out = hd.push_undo_cells(payload)
        assert out[0]["account_id"] == "U1"
        assert out[0]["cells"] == {"C": "旧", "G": "9"}
```

- [ ] **Step 2: 跑测试确认失败**

```bash
cd py && python -m pytest tests/test_huguan_undo.py -q -k PushSnapshot
```

Expected: FAIL —— `AttributeError: ... snapshot_push_targets`。

- [ ] **Step 3: 实现**

在 `py/huguan_dashboard.py` 的 `push_rows` **之前**插入：

```python
def snapshot_push_targets(service, conf: dict, platform: str, rows: list) -> dict:
    """读整片表，记下「本次刷新将会写到的每个格子」的当前值。

    只覆盖**真正会被写**的行与列：
      - 行：`rows` 里在表中命中定位键的那些（表里没有的账户 update_rows_by_account_id
        会进 not_found、一个字都不写）
      - 列：该行 `cells_for_row` 会产出的列（即 COLUMN_SPEC 里 writable=True 的）

    ⚠️ 必须在**写表之前**调用 —— 写完之后原值就没了。
    """
    sheet_name = conf["sheet_name"]
    grid = read_sheet_values(service, conf["spreadsheet_id"], sheet_name, READ_RANGE[platform])
    key_i = col_index(KEY_COL[platform])

    where = {}
    for i, values in enumerate(grid[1:], start=2):
        if len(values) <= key_i:
            continue
        raw = ("" if values[key_i] is None else str(values[key_i])).strip().lstrip("'").strip()
        if raw and raw not in where:
            where[raw] = values

    out = []
    for r in rows:
        aid = r["account_id"]
        values = where.get(aid)
        if values is None:
            continue
        cells = {}
        for col in r["cells"]:
            i = col_index(col)
            cells[col] = ("" if len(values) <= i or values[i] is None
                          else str(values[i])).strip()
        if cells:
            out.append({"account_id": aid, "cells": cells})
    return {"spreadsheet_id": conf["spreadsheet_id"],
            "sheet_name": sheet_name,
            "cells": out}


def push_undo_cells(payload: dict) -> list:
    """把 push 快照转成 `update_rows_by_account_id` 的入参形状。"""
    return [{"account_id": c["account_id"], "cells": dict(c["cells"])}
            for c in (payload or {}).get("cells", [])]
```

并在路由 `dashboard_push` 里、**写表之前**插入快照、**写表成功之后**提交快照：

```python
    snapshot = hd.snapshot_push_targets(service, conf, platform, rows)
    hd.save_undo(db_db, uid, platform, "push", snapshot)
    db_db.commit()
    res = gs.update_rows_by_account_id(...)     # 既有调用，保持不动
    if not res["updated"] and not res["not_found"]:
        # 一个字都没写 ⇒ 没有可撤回的东西，作废快照
        hd.delete_undo(db_db, uid, platform, "push")
        db_db.commit()
```

> **注意 `db_db`**：路由里 `db` 在 `finally: db.close()` 里已被关闭。**必须先读现行 `dashboard_push` 的代码**，确认连接的生命周期，再决定在哪里开连接做快照写读 —— 不要照抄上面的变量名。若既有实现已经关闭了连接，就在写表之前单独开一个连接完成「读整片表 + 存快照」。

- [ ] **Step 4: 跑测试确认通过**

```bash
cd py && python -m pytest tests/test_huguan_undo.py -q
```

- [ ] **Step 5: 跑全量回归并提交**

```bash
cd py && python -m pytest tests/ -q
git add py/huguan_dashboard.py py/routes/huguan_dashboard_routes.py py/tests/test_huguan_undo.py
git commit -m "feat(undo): push 方向记录快照（读整片表，只记将写的格）

写表前读原值存快照，一个字都没写则作废快照。"
```

---

## Task 3: push 撤回的执行与路由

**Files:**
- Modify: `py/huguan_dashboard.py`
- Modify: `py/routes/huguan_dashboard_routes.py`
- Test: `py/tests/test_huguan_undo.py`（追加）

**Interfaces:**
- Consumes: Task 1/2 的产物
- Produces:
  - `undo_push(user_id, platform) -> dict` —— 表写回 + 删快照；返回 `{"updated": n, "not_found": [...]}`
  - `GET /api/huguan/dashboard/undo?platform=X` → `{"success": true, "push": {...}|null, "sync": {...}|null}`
  - `POST /api/huguan/dashboard/undo` body `{"platform":…, "direction":…}`

- [ ] **Step 1: 写失败测试**

```python
class TestPushUndoRoute:
    def test_undo_available_reflects_snapshot(self, client, fb_user):
        db = database.get_db()
        hd.save_undo(db, fb_user, "fb", "push", {"cells": [{"account_id": "A", "cells": {}}]})
        db.commit()
        db.close()
        # 直接调逻辑层（路由层需要 JWT，另测）
        db = database.get_db()
        got = hd.load_undo(db, fb_user, "fb", "push")
        db.close()
        assert got is not None

    def test_undo_only_touches_own_records(self, client, fb_user):
        db = database.get_db()
        db.execute("INSERT INTO users(username, password, role, platform) "
                   "VALUES('u_other', 'x', 'huguan', 'fb')")
        other = db.execute("SELECT last_insert_rowid()").fetchone()[0]
        hd.save_undo(db, fb_user, "fb", "push", {"v": 1})
        db.commit()
        assert hd.load_undo(db, other, "fb", "push") is None
        db.close()

    def test_undo_uses_writeback_helper(self, client, fb_user, monkeypatch):
        """撤回走 update_rows_by_account_id，且只带快照里的格子。"""
        calls = []
        db = database.get_db()
        hd.save_undo(db, fb_user, "fb", "push",
                     {"spreadsheet_id": "S", "sheet_name": "N",
                      "cells": [{"account_id": "U9", "cells": {"C": "旧名"}}]})
        db.commit()
        db.close()
        monkeypatch.setattr(hd, "_open_db", lambda: database.get_db())
        monkeypatch.setattr(hd, "get_platform_config",
                            lambda db_, uid, p: {"spreadsheet_id": "S", "sheet_name": "N"})
        import google_sheets_service as gs
        monkeypatch.setattr(gs, "build_service", lambda path: object())
        monkeypatch.setattr(gs, "update_rows_by_account_id",
                            lambda svc, sid, name, rows: calls.append(rows) or
                            {"updated": len(rows), "not_found": []})
        monkeypatch.setattr(hd, "_sync_sheets_background", None, raising=False)
        out = hd.undo_push(fb_user, "fb")
        assert calls and calls[0][0]["account_id"] == "U9"
        assert calls[0][0]["cells"] == {"C": "旧名"}
        assert out["updated"] == 1
```

> 上面第三条用了 `_sync_sheets_background` —— **先读 `push_rows` 现行实现**，确认它实际走哪个后台函数（`from main import _sync_sheets_background`），并按现行形状 monkeypatch。若它是在函数内部 import 的，patch 点要相应调整。

- [ ] **Step 2: 跑测试确认失败**

```bash
cd py && python -m pytest tests/test_huguan_undo.py -q -k PushUndoRoute
```

- [ ] **Step 3: 实现 `undo_push` + 路由**

在 `py/huguan_dashboard.py` 的 `push_rows` **之后**插入：

```python
def undo_push(user_id: int, platform: str) -> dict:
    """撤回上一次「刷新到看板」：把快照里的格子写回原值，然后作废快照。

    **无条件写回**，不做 CAS（spec §6.1）。未配置看板或没有快照 → 返回全零。
    """
    db = _open_db()
    try:
        conf = get_platform_config(db, user_id, platform)
        if not conf["spreadsheet_id"] or not conf["sheet_name"]:
            return {"updated": 0, "not_found": []}
        payload = load_undo(db, user_id, platform, "push")
    finally:
        db.close()
    if not payload:
        return {"updated": 0, "not_found": []}

    rows = push_undo_cells(payload)
    if not rows:
        db = _open_db()
        try:
            delete_undo(db, user_id, platform, "push")
            db.commit()
        finally:
            db.close()
        return {"updated": 0, "not_found": []}

    import google_sheets_service as gs
    from main import _GOOGLE_SHEETS_CONFIG
    service = gs.build_service(_GOOGLE_SHEETS_CONFIG["credentials_path"])
    res = gs.update_rows_by_account_id(service, conf["spreadsheet_id"],
                                       conf["sheet_name"], rows)
    db = _open_db()
    try:
        delete_undo(db, user_id, platform, "push")
        db.commit()
    finally:
        db.close()
    return {"updated": res["updated"], "not_found": res["not_found"]}
```

在 `py/routes/huguan_dashboard_routes.py` 里，仿照 `dashboard_push` 的形状**只加 GET 状态端点**
（平台校验、JWT + `@huguan_required` 全部照抄现行写法）：

```python
@huguan_dashboard_bp.route("/api/huguan/dashboard/undo", methods=["GET"])
@jwt_required()
@huguan_required
def dashboard_undo_status():
    """两个方向各有没有可撤的快照。

    push 的 count 是「快照覆盖的行数」；sync 的 count 是
    「updates 项数 + created 项数」，与前端要显示的规模口径一致。
    """
    platform = str(request.args.get("platform") or "").strip()
    if platform not in hd.PLATFORMS:
        return err("platform 必须是 gg、tt 或 fb", 400)
    uid = get_uid()
    db = database.get_db()
    try:
        out = {}
        for direction in hd.UNDO_DIRECTIONS:
            payload = hd.load_undo(db, uid, platform, direction)
            if not payload:
                out[direction] = None
            elif direction == "push":
                out[direction] = {"count": len(payload.get("cells", []))}
            else:
                out[direction] = {"count": len(payload.get("updates", []))
                                           + len(payload.get("created", []))}
    finally:
        db.close()
    return ok({"undo": out})
```

> **POST 端点放 Task 5** —— 那时 `undo_sync` 才存在。本任务不引入任何「暂时不可用」的分支，
> 保证提交后全量测试是绿的。

- [ ] **Step 4: 跑测试确认通过**

```bash
cd py && python -m pytest tests/test_huguan_undo.py -q
```

- [ ] **Step 5: 跑全量回归并提交**

```bash
cd py && python -m pytest tests/ -q
git add py/huguan_dashboard.py py/routes/huguan_dashboard_routes.py py/tests/test_huguan_undo.py
git commit -m "feat(undo): push 撤回执行 + GET/POST 撤回端点"
```

---

## Task 4: sync 方向的快照记录

**Files:**
- Modify: `py/huguan_dashboard.py`（`apply_diff`）
- Test: `py/tests/test_huguan_undo.py`（追加）

**Interfaces:**
- Consumes: Task 1 的 `save_undo`
- Produces:
  - `apply_diff(db, diff, platform, confirmed, user_id, *, collect_undo=False) -> dict` —— 新增关键字参数；为真时额外返回 `"undo"` 键（快照 payload）
  - `build_diff` 的 `owner_changes` 项**多一个 `sheet_from` 键**（`{列字母: 表里的原值}`），供撤回时回退表侧
  - 模块级 `_OWNER_SHEET_COLS` / `_owner_sheet_from(parsed, platform)`

> **为什么放在 `apply_diff` 里而不是包一层**：旧值必须在 UPDATE **之前**读到（写完就读不到了），而这个位置只有 `apply_diff` 内部有。`collect_undo` 默认 `False` 保证既有调用与测试逐字节不变。

payload 形状：

```json
{
  "updates": [{"account_id":"…","cols":{"mcc_id":{"old":3},"owner_id":{"old":7}}}],
  "created": ["账户ID…"],
  "created_statuses": [{"name":"待优化","platform":"fb"}],
  "sheet_back": [{"account_id":"…","cells":{"G":"旧归属名","H":"旧通道值"}}]
}
```

- [ ] **Step 1: 写失败测试**

```python
class TestSyncSnapshot:
    def test_collect_undo_off_by_default(self, client, fb_user):
        """既有调用不带 collect_undo ⇒ 返回里没有 undo 键（纯增量）。"""
        db = database.get_db()
        diff = {"to_create": [], "to_update": [], "owner_changes": [],
                "to_skip": [], "warnings": [], "summary": {}}
        out = hd.apply_diff(db, diff, "fb", {}, fb_user)
        db.close()
        assert "undo" not in out

    def test_records_old_values_for_updates(self, client, fb_user):
        """列级旧值必须记下来。"""
        db = database.get_db()
        db.execute("INSERT INTO fb_accounts(name, account_id, owner_id, unit_price) "
                   "VALUES('户','SY1',?, '10')", (fb_user,))
        pk = db.execute("SELECT last_insert_rowid()").fetchone()[0]
        db.commit()
        diff = {"to_create": [], "to_skip": [], "warnings": [], "summary": {},
                "owner_changes": [],
                "to_update": [{"row": 2, "account_id": "SY1", "existing_id": pk,
                               "fields": {"unit_price": "99"}, "pending_status": None,
                               "scope_owner_id": fb_user, "clears": []}]}
        out = hd.apply_diff(db, diff, "fb", {"update": ["SY1"]}, fb_user, collect_undo=True)
        db.commit()
        db.close()
        ups = out["undo"]["updates"]
        assert ups == [{"account_id": "SY1", "cols": {"unit_price": {"old": "10"}}}]

    def test_records_created_ids(self, client, fb_user):
        db = database.get_db()
        diff = {"to_skip": [], "warnings": [], "summary": {}, "owner_changes": [], "to_update": [],
                "to_create": [{"row": 2, "account_id": "SY2", "owner_id": fb_user,
                               "owner_name": "", "db_values": {"_is_dead": False}, "pending_status": None}]}
        out = hd.apply_diff(db, diff, "fb", {"create": ["SY2"]}, fb_user, collect_undo=True)
        db.commit()
        db.close()
        assert out["undo"]["created"] == ["SY2"]
```

- [ ] **Step 2: 跑测试确认失败**

```bash
cd py && python -m pytest tests/test_huguan_undo.py -q -k SyncSnapshot
```

- [ ] **Step 3: 实现**

在 `apply_diff` 的签名上追加 `*, collect_undo: bool = False`，并在函数体开头建收集容器：

```python
    undo_updates, undo_created, undo_statuses, undo_sheet_back = [], [], [], []
```

在 `to_update` 分支里、**`db.execute(f"UPDATE {table} SET ...")` 之前**插入（旧值必须在写之前读）：

```python
            if collect_undo and fields:
                old_cols = {}
                for k in fields:
                    if k.startswith("_"):
                        continue
                    cur = db.execute(f"SELECT {k} AS v FROM {table} WHERE id=?",
                                     (item["existing_id"],)).fetchone()
                    old_cols[k] = cur["v"] if cur else None
                if old_cols:
                    undo_updates.append({"account_id": item["account_id"], "cols":
                                         {k: {"old": v} for k, v in old_cols.items()}})
```

在 `to_create` 分支里、INSERT **之后**（拿到 `new_id` 之后）插入：

```python
            if collect_undo:
                undo_created.append(item["account_id"])
```

在 `owner_changes` 分支的 `applied_owner_rows.append(...)` **之后**插入：

```python
            if collect_undo:
                undo_sheet_back.append({
                    "account_id": item["account_id"],
                    "cells": dict(item.get("sheet_from") or {}),
                })
```

**但 `sheet_from` 要先由 `build_diff` 造出来** —— 它是「归属变更会碰的那几列在**表里的原值**」，
必须在 `build_diff` 里从解析结果取（那时表还没被写过）：

**4a) 在 `build_diff` 里新增这个按平台分流的辅助函数（模块级）：**

```python
# 按平台给出「归属变更会写到表侧的那几列」，用于把原值记进快照。
# **必须按平台分流**（规格 §3.3）：
#   GG：运营列 + 通道列 H（同步后 H 被清空）
#   TT：只有接户运营列（L「换绑情况」只读回不回写，没有通道列）
#   FB：在用运营列 + 接户运营列 I（同步后 I 被写成「{旧}转{新}」）
_OWNER_SHEET_COLS = {"gg": ("G", "H"), "tt": ("G",), "fb": ("J", "I")}


def _owner_sheet_from(parsed: dict, platform: str) -> dict:
    """把该行「归属变更会碰的列」在表里的原值取出来。

    `parse_row` 已经把这几列解析成了字段（GG 的 `owner_name` / `_owner_channel`，
    TT 的 `owner_name`，FB 的 `owner_name` / `acceptor`），但快照要的是**列字母 → 单元格原值**，
    所以这里按列字母回读原始 values —— 用 `parse_row` 的结果拼容易漏掉「未映射但被写」的列。
    """
    field_by_col = {c[0]: c[2] for c in COLUMN_SPEC[platform]}
    out = {}
    for col in _OWNER_SHEET_COLS[platform]:
        field = field_by_col.get(col)
        if field:
            out[col] = ("" if parsed.get(field) is None else str(parsed.get(field)))
    return out
```

> ⚠️ **这里有一个你必须先核实的点**：上面的写法假设「`owner_changes` 里碰得到的列，
> 其值在 `parse_row` 的结果里都有对应字段可用」。**先读 `parse_row` 与 `COLUMN_SPEC` 确认**：
> GG 的 H 列字段名是 `_owner_channel`、G 列是 `owner_name`；TT 的 G 列是 `owner_name`；
> FB 的 J 列是 `owner_name`、I 列是 `acceptor`。若某个列在 `COLUMN_SPEC` 里标了**不可读**而拿不到值，
> 就改为直接在 `build_diff` 里按行号回读原始 `values`（`parsed["row"]` 是表里行号），
> 并在报告里说明你走了哪条路。

**4b) 在 `build_diff` 的 `owner_changes.append({...})` 里加一个键：**

```python
                "sheet_from": _owner_sheet_from(p, platform),
```

这次是**记录表里的真实原值**，不是「回退成旧归属名」—— 后者对 GG 的通道列是**错的**
（通道列同步前是户管填的**新**归属名，不是旧归属名）。记原值对三个平台一致正确。

在 `apply_diff` 的 return 里追加：

```python
    if collect_undo:
        result["undo"] = {"updates": undo_updates, "created": undo_created,
                          "created_statuses": undo_statuses, "sheet_back": undo_sheet_back}
    return result
```

> 别忘了 `created_statuses`：新建状态发生在 `resolve_status_id(...)` 里，它在 `to_create`/`to_update` 两个分支都有调用。**先读现行代码**，确认在哪里能知道「这次真的新建了状态」—— 可能需要给 `resolve_status_id` 加一个返回标记，或在调用前后查一次。不要靠猜。

- [ ] **Step 4: 跑测试确认通过**

```bash
cd py && python -m pytest tests/test_huguan_undo.py -q
```

- [ ] **Step 5: 跑全量回归并提交**

```bash
cd py && python -m pytest tests/ -q
git add py/huguan_dashboard.py py/tests/test_huguan_undo.py
git commit -m "feat(undo): apply_diff 收集 sync 方向的撤回快照

新增 collect_undo 关键字参数（默认 False，既有调用逐字节不变）。
旧值在 UPDATE 之前读取。"
```

---

## Task 5: sync 撤回的执行（表侧分流 + 库侧 CAS）

**Files:**
- Modify: `py/huguan_dashboard.py`
- Modify: `py/routes/huguan_dashboard_routes.py`
- Test: `py/tests/test_huguan_undo.py`（追加）

**Interfaces:**
- Consumes: Task 1–4 的产物
- Produces:
  - `undo_sync(user_id: int, platform: str) -> dict` —— 先表后库；返回 `{"reverted": n, "conflicts": [...], "kept": [...], "not_found": [...]}`
  - `POST /api/huguan/dashboard/undo`（两个方向都接上；Task 3 只加了 GET）

**顺序铁律（spec §6.2）**：**先回退表，再回退库。** 反了会让下次同步把撤回又自动撤销掉。

- [ ] **Step 1: 写失败测试**

```python
class TestSyncUndo:
    def test_cas_reverts_when_value_untouched(self, client, fb_user):
        """当前值 == 本次写入的新值 ⇒ 写回旧值。"""
        db = database.get_db()
        db.execute("INSERT INTO fb_accounts(name, account_id, owner_id, unit_price) "
                   "VALUES('户','C1',?, '99')", (fb_user,))
        pk = db.execute("SELECT last_insert_rowid()").fetchone()[0]
        hd.save_undo(db, fb_user, "fb", "sync",
                     {"updates": [{"account_id": "C1",
                                   "cols": {"unit_price": {"old": "10", "new": "99"}}}],
                      "created": [], "created_statuses": [], "sheet_back": []})
        db.commit()
        db.close()
        monkeypatch.setattr(hd, "_open_db", lambda: database.get_db())
        monkeypatch.setattr(hd, "get_platform_config",
                            lambda d, u, p: {"spreadsheet_id": "", "sheet_name": ""})
        out = hd.undo_sync(fb_user, "fb")
        db = database.get_db()
        got = db.execute("SELECT unit_price FROM fb_accounts WHERE id=?", (pk,)).fetchone()[0]
        db.close()
        assert got == "10"
        assert out["reverted"] == 1

    def test_cas_skips_when_value_changed(self, client, fb_user):
        """当前值 != 本次写入的新值 ⇒ 跳过并报冲突（别人改过了）。"""
        db = database.get_db()
        db.execute("INSERT INTO fb_accounts(name, account_id, owner_id, unit_price) "
                   "VALUES('户','C2',?, '77')", (fb_user,))
        pk = db.execute("SELECT last_insert_rowid()").fetchone()[0]
        hd.save_undo(db, fb_user, "fb", "sync",
                     {"updates": [{"account_id": "C2",
                                   "cols": {"unit_price": {"old": "10", "new": "99"}}}],
                      "created": [], "created_statuses": [], "sheet_back": []})
        db.commit()
        db.close()
        monkeypatch.setattr(hd, "_open_db", lambda: database.get_db())
        monkeypatch.setattr(hd, "get_platform_config",
                            lambda d, u, p: {"spreadsheet_id": "", "sheet_name": ""})
        out = hd.undo_sync(fb_user, "fb")
        db = database.get_db()
        got = db.execute("SELECT unit_price FROM fb_accounts WHERE id=?", (pk,)).fetchone()[0]
        db.close()
        assert got == "77"                      # 没被覆盖
        assert out["reverted"] == 0
        assert out["conflicts"][0]["account_id"] == "C2"

    def test_created_deleted_when_untouched(self, client, fb_user):
        db = database.get_db()
        db.execute("INSERT INTO fb_accounts(name, account_id, owner_id) VALUES('户','C3',?)",
                   (fb_user,))
        db.commit()
        db.close()
        db = database.get_db()
        hd.save_undo(db, fb_user, "fb", "sync",
                     {"updates": [], "created": ["C3"], "created_statuses": [], "sheet_back": []})
        db.commit()
        db.close()
        monkeypatch.setattr(hd, "_open_db", lambda: database.get_db())
        monkeypatch.setattr(hd, "get_platform_config",
                            lambda d, u, p: {"spreadsheet_id": "", "sheet_name": ""})
        out = hd.undo_sync(fb_user, "fb")
        db = database.get_db()
        n = db.execute("SELECT COUNT(*) FROM fb_accounts WHERE account_id='C3'").fetchone()[0]
        db.close()
        assert n == 0
        assert out["reverted"] >= 1
```

- [ ] **Step 2: 跑测试确认失败**

```bash
cd py && python -m pytest tests/test_huguan_undo.py -q -k SyncUndo
```

- [ ] **Step 3: 实现**

在 `py/huguan_dashboard.py` 里插入：

```python
def undo_sync(user_id: int, platform: str) -> dict:
    """撤回上一次「从表同步到系统」。

    **顺序：先回退表，再回退库**（spec §6.2 有「反了会怎样」的推演）。
    库部分用 CAS：只回滚「当前值仍等于本次写入的新值」的列。
    """
    db = _open_db()
    try:
        conf = get_platform_config(db, user_id, platform)
        payload = load_undo(db, user_id, platform, "sync")
    finally:
        db.close()
    if not payload:
        return {"reverted": 0, "conflicts": [], "not_found": [], "kept": []}

    table = _TABLE_FOR_PLATFORM[platform]
    key_field = ACCOUNT_KEY_FIELD[platform]

    # ---- 1. 先回退表 ----
    back = []
    for item in payload.get("sheet_back", []):
        if item.get("cells"):
            back.append({"account_id": item["account_id"], "cells": dict(item["cells"])})
    table_result = {"updated": 0, "not_found": []}
    if back and conf["spreadsheet_id"] and conf["sheet_name"]:
        import google_sheets_service as gs
        from main import _GOOGLE_SHEETS_CONFIG
        service = gs.build_service(_GOOGLE_SHEETS_CONFIG["credentials_path"])
        table_result = gs.update_rows_by_account_id(
            service, conf["spreadsheet_id"], conf["sheet_name"], back)

    # ---- 2. 再回退库 ----
    reverted, conflicts, kept = 0, [], []
    db = _open_db()
    try:
        for item in payload.get("updates", []):
            aid = item["account_id"]
            row = db.execute(f"SELECT * FROM {table} WHERE {key_field}=?", (aid,)).fetchone()
            if row is None:
                continue
            sets, vals, conflicted = [], [], False
            for col, pair in item["cols"].items():
                new_v = pair.get("new")
                cur = row[col] if col in row.keys() else None
                if str(cur if cur is not None else "") != str(new_v if new_v is not None else ""):
                    conflicted = True
                    continue
                sets.append(f"{col}=?")
                vals.append(pair.get("old"))
            if conflicted:
                conflicts.append({"account_id": aid, "reason": "同步后被改过"})
                continue
            if sets:
                db.execute(f"UPDATE {table} SET {', '.join(sets)} WHERE id=?",
                           tuple(vals) + (row["id"],))
                reverted += 1

        for aid in payload.get("created", []):
            row = db.execute(f"SELECT id, updated_at, created_at FROM {table} "
                             f"WHERE {key_field}=?", (aid,)).fetchone()
            if row is None:
                continue
            if str(row["updated_at"] or "") != str(row["created_at"] or ""):
                kept.append({"account_id": aid, "reason": "同步后被改过"})
                continue
            # fb_account_bm_history 没有 ON DELETE CASCADE，必须显式先删
            if platform == "fb":
                db.execute("DELETE FROM fb_account_bm_history WHERE account_id=?", (row["id"],))
            db.execute(f"DELETE FROM {table} WHERE id=?", (row["id"],))
            reverted += 1

        db.commit()
    finally:
        db.close()

    db = _open_db()
    try:
        delete_undo(db, user_id, platform, "sync")
        db.commit()
    finally:
        db.close()
    return {"reverted": reverted, "conflicts": conflicts, "kept": kept,
            "not_found": table_result.get("not_found", [])}
```

把路由 `dashboard_undo_apply` 里的 `undo_sync` 分支接上（Task 3 留的占位）。

- [ ] **Step 4: 跑测试确认通过**

```bash
cd py && python -m pytest tests/test_huguan_undo.py -q
```

- [ ] **Step 5: 跑全量回归并提交**

```bash
cd py && python -m pytest tests/ -q
git add py/huguan_dashboard.py py/routes/huguan_dashboard_routes.py py/tests/test_huguan_undo.py
git commit -m "feat(undo): sync 撤回执行（先表后库 + 库侧 CAS + 新建对象判定）

CAS：当前值 == 本次写入的新值才回滚。新建账户用 updated_at 判定。
FB 删账户前显式清 fb_account_bm_history（无 CASCADE）。"
```

---

## Task 6: 删用户清理 + 前端按钮

**Files:**
- Modify: `py/main.py`（`admin_delete_user`）
- Modify: `frontend/src/api/huguan.js`
- Modify: `frontend/src/components/HuguanDashboardCard.vue`
- Test: `py/tests/test_huguan_undo.py`（追加）

**Interfaces:**
- Consumes: Task 3 的两个端点
- Produces: 删用户时清理快照；卡片上两个撤回按钮

- [ ] **Step 1: 写失败测试**

```python
class TestDeleteUserCleanup:
    def test_deleting_user_via_endpoint_succeeds_with_undo_row_present(self, client, fb_user):
        """**驱动真实端点**：户管有快照时删他，不能以 FOREIGN KEY constraint failed 收场。

        ⚠️ 这条**不能**自己 DELETE 再断言行没了 —— 那是自证式空转，测不到 admin_delete_user。
        必须在删之前留下快照，然后走真实删用户路径，断言它成功且快照也没了。

        `developer` 身份发起（`admin_delete_user` 需要 admin/developer）。
        """
        db = database.get_db()
        hd.save_undo(db, fb_user, "fb", "push", {"v": 1})
        db.commit()
        # 目标用户不能是 developer/admin，否则会被同级保护拦掉
        db.execute("UPDATE users SET role='user' WHERE id=?", (fb_user,))
        db.commit()
        db.execute("INSERT INTO users(username, password, role, platform) "
                   "VALUES('del_dev', 'test123', 'developer', 'gg')")
        db.commit()
        db.close()

        token = client.post("/api/auth/login",
                            json={"username": "del_dev", "password": "test123"}
                            ).get_json()["access_token"]
        h = {"Authorization": f"Bearer {token}"}

        # 先读现行 main.py 确认删用户的实际路由与形状，再按它写；下面是常见形状
        r = client.delete(f"/api/admin/users/{fb_user}", headers=h)
        assert r.status_code == 200, r.get_json()

        db = database.get_db()
        n = db.execute("SELECT COUNT(*) FROM huguan_sync_undo WHERE user_id=?",
                       (fb_user,)).fetchone()[0]
        db.close()
        assert n == 0

    def test_undo_table_is_in_delete_user_cleanup_list(self):
        """静态守卫：admin_delete_user 的代码里必须出现 huguan_sync_undo。

        上面那条是端到端行为（更强），这条是**直指根因**的守卫 ——
        将来有人重构删用户逻辑、把清理行弄丢了，这条会立刻红并说清原因。
        """
        import inspect
        import main
        src = inspect.getsource(main.admin_delete_user)
        assert "huguan_sync_undo" in src, \
            "admin_delete_user 未清理 huguan_sync_undo —— 删任何用过看板的户管都会 FOREIGN KEY 500"
```

- [ ] **Step 2: 跑测试确认失败**

```bash
cd py && python -m pytest tests/test_huguan_undo.py -q -k DeleteUserCleanup
```

Expected: 第二条 FAIL —— `admin_delete_user` 源码里没有 `huguan_sync_undo`。

- [ ] **Step 3: 接进删用户清理**

**先读 `py/main.py` 的 `admin_delete_user`**，找到它既有的「删用户时的关联清理」那一段（`AGENTS.md` 记着这条口径），在其中按同一形状追加：

```python
        db.execute("DELETE FROM huguan_sync_undo WHERE user_id = ?", (uid,))
```

> 放在与它同类的「纯归属关系表直接删除」那组里。

- [ ] **Step 4: 前端**

`frontend/src/api/huguan.js` 补：

```js
  getUndo(platform) { return client.get('/huguan/dashboard/undo', { params: { platform } }) },
  doUndo(platform, direction) { return client.post('/huguan/dashboard/undo', { platform, direction }) },
```

`frontend/src/components/HuguanDashboardCard.vue`：
- `onMounted` 时并行拉一次 `getUndo(HD_PLATFORM)`，存进 `hdUndo` ref
- 在「🔄 刷新到看板」和「⬇️ 从表同步到系统」两个按钮**之后**各加一个 `↩️ 撤回上次`，`:disabled="!hdUndo.push"` / `!hdUndo.sync`
- 按钮旁小字：`上一次：{N 行/项}`（`hdUndo[direction].count`）
- 点击 → `ElMessageBox.confirm` 二次确认 → `doUndo` → 结果报告。**报告必须能显示冲突项**（账户ID + 原因）与表里找不到的行，与差异报告一个口径 —— 不能只报成功计数

- [ ] **Step 5: 跑测试 + 构建**

```bash
cd py && python -m pytest tests/test_huguan_undo.py -q
cd ../frontend && npm run build
```

- [ ] **Step 6: 跑全量回归并提交**

```bash
cd py && python -m pytest tests/ -q
git add py/main.py frontend/src/api/huguan.js frontend/src/components/HuguanDashboardCard.vue py/tests/test_huguan_undo.py
git commit -m "feat(undo): 删用户清理快照 + 前端撤回按钮与结果报告"
```

---

## 完成后

子项目 ③ 交付后，三步拆分全部完成：

| | 子项目 | 状态 |
|---|---|---|
| ① | FB 资产数据模型 | 已完成 |
| ② | FB 户管看板 | 已完成 |
| ③ | 双向撤回 | 本计划 |

**若 ③ 期间发现 ② 遗留的 Minor 需要顺带处理**（建号 BM 名解析失败静默 vs update 警告的不对称、`updated` 计数偏高、`_same_as_existing` 未带 `deleted_at IS NULL`），在 Task 4/5 碰到对应代码时一并修，并在报告里说明。
