# 写表失败统一治理（一期）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让写 Google Sheets 的失败不再静默 —— 最终失败时产生持久记录（含原因）、提示操作者、支持一键重试，并对「主数据延伸」类写表做条件回滚。一期落地统一基建 + TT「回收户清单」。

**Architecture:** 新增 `py/sheet_write.py` 作为唯一写表入口（`run_write`），内部包住既有的 `_sync_sheets_background`，用一张 `sheet_write_log` 表按 `(user_id, target, business_key)` upsert 记录状态机；写表目标通过 `TARGETS` 注册表提供可重建的执行器与可选的回滚器。TT 回收清单改走该入口，回滚用「守卫写进 UPDATE 的 WHERE」实现原子条件回滚。

**Tech Stack:** Python 3.11 / Flask / SQLite(WAL) / Flask-JWT-Extended / pytest；前端 Vue 3 `<script setup>` + Element Plus。

**规格来源：** `docs/superpowers/specs/2026-10-06-sheet-write-failure-governance-design.md`（下称「规格」）

## Global Constraints

- 写表**保持异步**。业务端点的响应不得因为写表而阻塞或失败。
- 提示**只在最终结果产生时**发出 —— `failed`（首次失败、30s 重试在途）**不得**触发任何用户可见提示。
- 状态值固定 6 个，不得增删：`pending` / `failed` / `synced` / `retry_failed` / `rolled_back` / `rollback_abandoned`。
- 终态 4 个：`synced` / `retry_failed` / `rolled_back` / `rollback_abandoned`。需提示的终态 3 个（即除 `synced`）。
- `target` 一律用**稳定英文 token**，不得用中文列头或显示名（`tt_recycle`）。
- **后台线程内禁止使用请求线程的 SQLite 连接**，一律 `database.get_db()` 新建；**禁止**在请求线程预先 `build_service()` 再传进线程（httplib2 非线程安全）。
- 回滚**只用于「主数据延伸」类**（`tt_recycle`）；镜像类（`huguan_dashboard`）不注册 `rollback`。
- 回滚**只在 `retry_failed` 时执行**，不得在 `failed` 时执行。
- 回滚守卫必须写在 `UPDATE ... WHERE` 里（原子），不得「先 SELECT 再 UPDATE」。
- `err(msg, code)` 才是正确写法；**禁止** `return err(msg), code`（嵌套元组，Flask 抛 TypeError）。
- 本仓库常有并行会话在改文件：**禁止 `git add -A`**，一律 `git add <显式路径>`。
- 不启动/重启任何**常驻服务进程**（Flask 等）—— 需要时提请用户执行。
  `npm run build` 是一次性构建、非常驻，允许执行；若用户当次要求跳过构建，改为人工核对模板语法并在交付说明里注明「未跑构建」。

---

## File Structure

| 文件 | 动作 | 职责 |
|---|---|---|
| `py/database.py` | 修改 | `sheet_write_log` 建表（`_ensure_schema` + `_ensure_columns` 双侧） |
| `py/main.py` | 修改 | 修 `_sync_sheets_background` 缺陷 A/B；注册新 blueprint |
| `py/sheet_write.py` | **新建** | `run_write` 编排、状态机、`TARGETS` 注册表、条件回滚调度 |
| `py/routes/sheet_write_routes.py` | **新建** | `GET /api/sheet-write/status`、`POST /api/sheet-write/retry` |
| `py/routes/tt_accounts_routes.py` | 修改 | TT 回收清单接入：快照抓取、改走 `run_write`、注册 `tt_recycle` 目标 |
| `py/tests/test_sheet_write.py` | **新建** | 基建单测（缺陷 A/B 守卫、状态机、条件回滚） |
| `py/tests/test_tt_recycle_sheet_write.py` | **新建** | TT 接入端到端（快照、回滚、守卫未过） |
| `frontend/src/api/sheetWrite.js` | **新建** | 两个接口的前端封装 |
| `frontend/src/views/tt/TtAccountPanel.vue` | 修改 | 轮询、提示、行标记、重试按钮 |

---

### Task 1: `sheet_write_log` 表

**Files:**
- Modify: `py/database.py`（`_ensure_schema` 内的 CREATE TABLE 区、`_ensure_columns` 内的迁移区）
- Test: `py/tests/test_sheet_write.py`

**Interfaces:**
- Consumes: 无
- Produces: 表 `sheet_write_log`，列 `id, user_id, platform, target, business_key, status, error_msg, payload_json, snapshot_json, created_at, updated_at, settled_at`，含 `UNIQUE(user_id, target, business_key)`

- [ ] **Step 1: 写失败测试**

新建 `py/tests/test_sheet_write.py`：

```python
"""写表失败统一治理 —— 基建测试。

设计见 docs/superpowers/specs/2026-10-06-sheet-write-failure-governance-design.md
"""
import pytest

import database


def test_sheet_write_log_table_shape(client):
    """表必须存在，且 UNIQUE 约束落在 (user_id, target, business_key)。"""
    db = database.get_db()
    cols = {r[1] for r in db.execute("PRAGMA table_info(sheet_write_log)").fetchall()}
    db.close()
    assert {
        "id", "user_id", "platform", "target", "business_key", "status",
        "error_msg", "payload_json", "snapshot_json", "created_at",
        "updated_at", "settled_at",
    } <= cols


def test_sheet_write_log_unique_key(client):
    """同 (user_id, target, business_key) 只能有一行 —— upsert 语义的前提。"""
    db = database.get_db()
    for _ in range(2):
        try:
            db.execute(
                "INSERT INTO sheet_write_log (user_id, platform, target, business_key, status) "
                "VALUES (1,'tt','tt_recycle','acc_1','pending')")
            db.commit()
            ok = True
        except Exception:
            db.rollback()
            ok = False
    rows = db.execute(
        "SELECT COUNT(*) FROM sheet_write_log WHERE user_id=1 AND target='tt_recycle' "
        "AND business_key='acc_1'").fetchone()[0]
    db.close()
    assert ok is False, "第二次插入应撞 UNIQUE 约束"
    assert rows == 1
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd py && python -m pytest tests/test_sheet_write.py -v`
Expected: FAIL —— `no such table: sheet_write_log`

- [ ] **Step 3: 建表**

在 `py/database.py` 的 `_ensure_schema` 里，紧跟 `sheets_sync_log` 的 CREATE INDEX 之后（`idx_ssl_user_product` 那行后面）插入：

```sql
        CREATE TABLE IF NOT EXISTS sheet_write_log (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id       INTEGER NOT NULL,
            platform      TEXT    NOT NULL,
            target        TEXT    NOT NULL,
            business_key  TEXT    NOT NULL DEFAULT '',
            status        TEXT    NOT NULL,
            error_msg     TEXT    DEFAULT '',
            payload_json  TEXT    DEFAULT '',
            snapshot_json TEXT    DEFAULT '',
            created_at    TEXT    DEFAULT (datetime('now','localtime')),
            updated_at    TEXT    DEFAULT (datetime('now','localtime')),
            settled_at    TEXT    DEFAULT NULL,
            UNIQUE(user_id, target, business_key)
        );
        CREATE INDEX IF NOT EXISTS idx_swl_user_platform ON sheet_write_log(user_id, platform);
```

在 `_ensure_columns` 里追加（放在既有 `sheets_sync_log` 补列之后，保持同类聚在一起）：

```python
    # 写表失败治理（2026-10-06）：老库补建表。_ensure_schema 只在首建时跑，
    # 存量库不会走到那段 CREATE TABLE，故此处再建一次（IF NOT EXISTS 幂等）。
    conn.execute("""
        CREATE TABLE IF NOT EXISTS sheet_write_log (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id       INTEGER NOT NULL,
            platform      TEXT    NOT NULL,
            target        TEXT    NOT NULL,
            business_key  TEXT    NOT NULL DEFAULT '',
            status        TEXT    NOT NULL,
            error_msg     TEXT    DEFAULT '',
            payload_json  TEXT    DEFAULT '',
            snapshot_json TEXT    DEFAULT '',
            created_at    TEXT    DEFAULT (datetime('now','localtime')),
            updated_at    TEXT    DEFAULT (datetime('now','localtime')),
            settled_at    TEXT    DEFAULT NULL,
            UNIQUE(user_id, target, business_key)
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_swl_user_platform "
                 "ON sheet_write_log(user_id, platform)")
```

> **为什么两处都要写**：`_ensure_schema` 只在 `_schema_verified` 为假时跑（首建），存量库永远不会再进；`_ensure_columns` 每次连库都跑。两侧都写才能保证新老库一致。

- [ ] **Step 4: 跑测试确认通过**

Run: `cd py && python -m pytest tests/test_sheet_write.py -v`
Expected: 2 passed

- [ ] **Step 5: 提交**

```bash
git add py/database.py py/tests/test_sheet_write.py
git commit -m "feat(sheet-write): 新建 sheet_write_log 表

按 (user_id, target, business_key) 唯一 —— 本表回答的是「这个账户的这个
写表目标现在是不是处于失败态」，不是历史审计，故用 upsert 语义。
_ensure_schema（首建）与 _ensure_columns（每次连库）双侧都写，
保证新老库一致。"
```

---

### Task 2: 修 `_sync_sheets_background` 的缺陷 A / B

**Files:**
- Modify: `py/main.py:7909-7937`
- Test: `py/tests/test_sheet_write.py`

**Interfaces:**
- Consumes: 无
- Produces: `_sync_sheets_background(sync_fn, on_result_fn)` —— **首次成功也会以 `("synced", "")` 调用回调**

- [ ] **Step 1: 写失败测试**

追加到 `py/tests/test_sheet_write.py`：

```python
def test_background_calls_back_on_first_success(monkeypatch):
    """缺陷 A 守卫：首次写成功也必须回调。

    原实现里首次成功直接跳出 try，on_fail_fn 一次都不调 —— 导致把
    `sheets_synced=1` 写在回调里的充值写表点标志位永远停在 0（前端误报
    「未同步」），以及 GG 做表的 pending 日志行永久残留（前端轮询空转）。
    """
    import main

    calls = []
    main._sync_sheets_background(lambda: None, lambda s, e: calls.append((s, e)))
    # 后台是 daemon 线程，等它跑完
    import time
    for _ in range(100):
        if calls:
            break
        time.sleep(0.02)

    assert calls == [("synced", "")]


def test_background_reports_retry_failed(monkeypatch):
    """重试也失败 => 终态 retry_failed，且错误信息非空。"""
    import main
    monkeypatch.setattr("time.sleep", lambda _s: None)   # 跳过 30s

    calls = []

    def _boom():
        raise RuntimeError("Sheets 挂了")

    main._sync_sheets_background(_boom, lambda s, e: calls.append((s, e)))
    import time
    for _ in range(100):
        if len(calls) >= 3:
            break
        time.sleep(0.02)

    assert [c[0] for c in calls] == ["failed", "retry_failed"]
    assert "Sheets 挂了" in calls[-1][1]


def test_background_logs_callback_exception(caplog):
    """缺陷 B 守卫：回调自身抛异常必须落 ERROR 日志，不得静默 pass。

    回调是唯一负责落记录的地方 —— 它失败后彻底没痕迹，就没法排查
    「状态为什么没更新」。原来三处都是 `except Exception: pass`。
    """
    import logging
    import time

    import main

    def _bad_cb(status, err):
        raise RuntimeError("回调自己炸了")

    with caplog.at_level(logging.ERROR):
        main._sync_sheets_background(lambda: None, _bad_cb)
        for _ in range(100):
            if caplog.records:
                break
            time.sleep(0.02)

    assert any("结果回调失败" in r.getMessage() for r in caplog.records), \
        f"回调异常没有落日志，现有记录: {[r.getMessage() for r in caplog.records]}"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd py && python -m pytest tests/test_sheet_write.py -v -k background`
Expected: `test_background_calls_back_on_first_success` FAIL（`calls == []`）

- [ ] **Step 3: 修改 `_sync_sheets_background`**

把 `py/main.py:7909-7937` 整个函数体替换为：

```python
def _sync_sheets_background(sync_fn, on_result_fn):
    """后台线程写 Google Sheets，失败 30s 后重试一次。

    命名沿革：参数原叫 `on_fail_fn`，但 **首次成功也会调用它**（2026-10-06 修复）。
    这名字已名不副实，但改名要动 15 个调用点，收益不抵；按语义读作「结果回调」。

    sync_fn:        无参函数，执行 Sheets 写入。**必须在自身闭包内新建 service
                    与 DB 连接** —— 本函数在线程里跑，httplib2 与 sqlite 连接
                    都不可跨线程复用。
    on_result_fn:   回调 (status: str, error: str)，status 取值:
                      'synced'        首次成功 或 失败后重试成功
                      'failed'        首次失败（30s 重试在途的中间态）
                      'retry_failed'  30s 重试也失败（最终失败）
                    回调自身抛异常不影响主流程，但会落 log.error（原来静默 pass，
                    等于唯一负责落记录的地方失败后彻底没痕迹）。
    """
    import time as _time

    def _run():
        try:
            sync_fn()
            # 首次成功也必须回调：否则把「已同步」写进回调的调用点永远漏标
            if on_result_fn:
                try:
                    on_result_fn("synced", "")
                except Exception as e:
                    log.error("Sheets 结果回调失败(status=synced): %s", e)
            return
        except Exception as e:
            log.warning("Sheets 同步失败，30s 后重试: %s", e)
            if on_result_fn:
                try:
                    on_result_fn("failed", str(e))
                except Exception as e2:
                    log.error("Sheets 结果回调失败(status=failed): %s", e2)
        _time.sleep(30)
        try:
            sync_fn()
            if on_result_fn:
                try:
                    on_result_fn("synced", "")
                except Exception as e:
                    log.error("Sheets 结果回调失败(status=synced): %s", e)
        except Exception as e2:
            log.error("Sheets 重试失败: %s", e2)
            if on_result_fn:
                try:
                    on_result_fn("retry_failed", str(e2))
                except Exception as e3:
                    log.error("Sheets 结果回调失败(status=retry_failed): %s", e3)

    t = threading.Thread(target=_run, daemon=True)
    t.start()
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd py && python -m pytest tests/test_sheet_write.py -v -k background`
Expected: 3 passed

- [ ] **Step 5: 回归受影响的既有测试**

Run: `cd py && python -m pytest tests/test_huguan_dashboard.py tests/test_tt_accounts.py tests/test_tt_platform.py -q`
Expected: 全绿（这 3 个文件覆盖了走 `_sync_sheets_background` 的主要调用点）

- [ ] **Step 6: 提交**

```bash
git add py/main.py py/tests/test_sheet_write.py
git commit -m "fix(sheets): _sync_sheets_background 首次成功也回调，回调异常落日志

缺陷 A：首次成功直接跳出 try，on_fail_fn 一次都不调。而各调用点把
sheets_synced=1 写在回调里 -> 标志位永远停在 0，前端 tooltip 误报
「未同步到表格」（影响 5 个充值写表点）；GG 做表的 pending 日志行也
永久残留，startZbSyncPolling 拿到的 log.status=='pending' 既不等于
'failed' 也不为 null，空转到轮询上限。

缺陷 B：三处 except Exception: pass 改为落 log.error —— 回调是唯一
负责落记录的地方，它失败就彻底没痕迹了。

参数名 on_fail_fn 已名不副实，但改名要动 15 个调用点，改为在 docstring
首行说明其真实语义是「结果回调」。"
```

---

### Task 3: `py/sheet_write.py` —— 统一入口与状态机

**Files:**
- Create: `py/sheet_write.py`
- Test: `py/tests/test_sheet_write.py`

**Interfaces:**
- Consumes: 表 `sheet_write_log`（Task 1）；`main._sync_sheets_background`（Task 2）
- Produces:
  - `TERMINAL: tuple[str, ...]`、`ATTENTION: tuple[str, ...]`
  - `register_target(name: str, rebuild: Callable, rollback: Callable | None = None) -> None`
  - `build_sync(target: str, user_id: int, business_key: str, payload: dict) -> Callable[[], None]`
  - `record_pending(db, *, user_id, platform, target, business_key, payload=None, snapshot=None) -> None`
  - `settle(db, *, user_id, target, business_key, status, error_msg="") -> None`
  - `run_write(db, *, user_id, platform, target, business_key, sync_fn, payload=None, snapshot=None) -> None`
  - `rebuild = _rebuild`（内部）
  - 注册表项：`TARGETS[name] = {"rebuild": ..., "rollback": ...}`

- [ ] **Step 1: 写失败测试**

追加到 `py/tests/test_sheet_write.py`：

```python
def _mk_log(db, uid, target, key, status="pending", payload=None, snapshot=None):
    import json
    db.execute(
        "INSERT INTO sheet_write_log (user_id, platform, target, business_key, status, "
        "payload_json, snapshot_json) VALUES (?,?,?,?,?,?,?)",
        (uid, "tt", target, key, status,
         json.dumps(payload or {}), json.dumps(snapshot or {})))
    db.commit()


def _row(db, uid, target, key):
    return db.execute(
        "SELECT * FROM sheet_write_log WHERE user_id=? AND target=? AND business_key=?",
        (uid, target, key)).fetchone()


def test_record_pending_is_upsert(client):
    """同键重登记回 pending 并清空上轮的错误与定案时刻。"""
    import sheet_write
    db = database.get_db()
    _mk_log(db, 1, "tt_recycle", "acc_1", status="retry_failed", snapshot={"a": 1})
    sheet_write.record_pending(db, user_id=1, platform="tt", target="tt_recycle",
                               business_key="acc_1", payload={"reason": "封禁"},
                               snapshot={"b": 2})
    r = _row(db, 1, "tt_recycle", "acc_1")
    db.close()
    assert r["status"] == "pending"
    assert r["error_msg"] == ""
    assert r["settled_at"] is None
    assert '"b"' in r["snapshot_json"]


def test_settle_sets_settled_at_only_for_terminal(client):
    """settled_at 只在终态落定，中间态不得置上（前端靠它判「已定案」）。"""
    import sheet_write
    db = database.get_db()
    _mk_log(db, 1, "tt_recycle", "acc_2")
    sheet_write.settle(db, user_id=1, target="tt_recycle", business_key="acc_2",
                       status="failed", error_msg="超时")
    assert _row(db, 1, "tt_recycle", "acc_2")["settled_at"] is None
    sheet_write.settle(db, user_id=1, target="tt_recycle", business_key="acc_2",
                       status="retry_failed", error_msg="超时")
    r = _row(db, 1, "tt_recycle", "acc_2")
    db.close()
    assert r["settled_at"] is not None
    assert r["status"] == "retry_failed"


def test_run_write_marks_synced_on_success(client, monkeypatch):
    """写表成功 => synced，且不触发回滚。"""
    import sheet_write
    rolled = []
    sheet_write.register_target("_t_ok",
                                rebuild=lambda uid, key, payload: (lambda: None),
                                rollback=lambda db, snap: rolled.append(1) or True)
    db = database.get_db()
    sheet_write.run_write(db, user_id=1, platform="tt", target="_t_ok",
                          business_key="k1", sync_fn=lambda: None)
    import time
    for _ in range(100):
        if _row(db, 1, "_t_ok", "k1")["status"] == "synced":
            break
        time.sleep(0.02)
    r = _row(db, 1, "_t_ok", "k1")
    db.close()
    assert r["status"] == "synced"
    assert rolled == []


def test_run_write_marks_failed_during_retry_window(client, monkeypatch):
    """首次失败落中间态 failed（**此时不得提示**），随后才落终态。

    这是「等最终结果才提示」的守卫：前端只在 status ∈ ATTENTION 时提示，
    而 failed 不在其中。
    """
    import sheet_write
    import time as _time
    monkeypatch.setattr(_time, "sleep", lambda _s: None)

    seq = []
    real_settle = sheet_write.settle

    def _spy(db, *, user_id, target, business_key, status, error_msg=""):
        seq.append(status)
        return real_settle(db, user_id=user_id, target=target,
                           business_key=business_key, status=status, error_msg=error_msg)

    monkeypatch.setattr(sheet_write, "settle", _spy)
    sheet_write.register_target("_t_mid", rebuild=lambda uid, key, payload: (lambda: None))

    def _boom():
        raise RuntimeError("挂了")

    db = database.get_db()
    sheet_write.run_write(db, user_id=1, platform="tt", target="_t_mid",
                          business_key="k9", sync_fn=_boom)
    for _ in range(200):
        if "retry_failed" in seq:
            break
        _time.sleep(0.01)

    sheet_write.settle = real_settle
    assert seq == ["failed", "retry_failed"]
    assert sheet_write.ATTENTION == ("retry_failed", "rolled_back", "rollback_abandoned")
    assert "failed" not in sheet_write.ATTENTION
    db.close()


def test_run_write_rolls_back_on_final_failure(client, monkeypatch):
    """最终失败 => 调回滚器，且落 rolled_back。"""
    import sheet_write
    monkeypatch.setattr("time.sleep", lambda _s: None)
    calls = []
    sheet_write.register_target(
        "_t_rb",
        rebuild=lambda uid, key, payload: (lambda: None),
        rollback=lambda db, snap: calls.append(snap) or True)

    def _boom():
        raise RuntimeError("Sheets 挂了")

    db = database.get_db()
    sheet_write.run_write(db, user_id=1, platform="tt", target="_t_rb",
                          business_key="k2", sync_fn=_boom, snapshot={"x": 9})
    import time
    for _ in range(150):
        if _row(db, 1, "_t_rb", "k2")["status"] == "rolled_back":
            break
        time.sleep(0.02)
    r = _row(db, 1, "_t_rb", "k2")
    db.close()
    assert r["status"] == "rolled_back"
    assert calls == [{"x": 9}]
    assert "Sheets 挂了" in r["error_msg"]


def test_run_write_abandons_rollback_when_guard_fails(client, monkeypatch):
    """回滚器返回 False（守卫未过）=> rollback_abandoned，不得落 rolled_back。"""
    import sheet_write
    monkeypatch.setattr("time.sleep", lambda _s: None)
    sheet_write.register_target("_t_ab",
                                rebuild=lambda uid, key, payload: (lambda: None),
                                rollback=lambda db, snap: False)

    def _boom():
        raise RuntimeError("Sheets 挂了")

    db = database.get_db()
    sheet_write.run_write(db, user_id=1, platform="tt", target="_t_ab",
                          business_key="k3", sync_fn=_boom, snapshot={"x": 1})
    import time
    for _ in range(150):
        if _row(db, 1, "_t_ab", "k3")["status"] == "rollback_abandoned":
            break
        time.sleep(0.02)
    r = _row(db, 1, "_t_ab", "k3")
    db.close()
    assert r["status"] == "rollback_abandoned"
    assert "被再次修改" in r["error_msg"]


def test_run_write_no_rollback_for_mirror_target(client, monkeypatch):
    """镜像类（未注册 rollback）最终失败 => retry_failed，且业务数据不动。"""
    import sheet_write
    monkeypatch.setattr("time.sleep", lambda _s: None)
    sheet_write.register_target("_t_mirror",
                                rebuild=lambda uid, key, payload: (lambda: None))

    def _boom():
        raise RuntimeError("挂了")

    db = database.get_db()
    sheet_write.run_write(db, user_id=1, platform="tt", target="_t_mirror",
                          business_key="k4", sync_fn=_boom)
    import time
    for _ in range(150):
        if _row(db, 1, "_t_mirror", "k4")["status"] == "retry_failed":
            break
        time.sleep(0.02)
    r = _row(db, 1, "_t_mirror", "k4")
    db.close()
    assert r["status"] == "retry_failed"
    assert r["settled_at"] is not None


def test_build_sync_unknown_target_raises(client):
    import sheet_write
    with pytest.raises(KeyError):
        sheet_write.build_sync("nope", 1, "k", {})
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd py && python -m pytest tests/test_sheet_write.py -v`
Expected: FAIL —— `ModuleNotFoundError: No module named 'sheet_write'`

- [ ] **Step 3: 创建 `py/sheet_write.py`**

```python
"""写表失败统一治理：登记任务 → 后台写表 → 按最终结果落状态 / 回滚。

设计见 docs/superpowers/specs/2026-10-06-sheet-write-failure-governance-design.md。

本模块只做编排与状态机，不 import flask；真正的 Sheets I/O 由各 target 的
执行器负责（见 register_target），HTTP 入口在 routes/sheet_write_routes.py。
"""
import json
import logging

log = logging.getLogger("gg-server")

# 终态：settled_at 非空。前端轮询到终态即停。
TERMINAL = ("synced", "retry_failed", "rolled_back", "rollback_abandoned")
# 需要向用户提示的终态（synced 是「没出事」，不打扰）
ATTENTION = ("retry_failed", "rolled_back", "rollback_abandoned")

# target -> {"rebuild": (user_id, business_key, payload) -> sync_fn,
#            "rollback": (db, snapshot) -> bool  |  None}
TARGETS = {}


def register_target(name, rebuild, rollback=None):
    """注册一个写表目标。

    rebuild 必须是**工厂**而不是现成的 zero-arg 函数：重试发生在另一次请求里，
    执行器要在**后台线程内**用 database.get_db() 新建连接、新建 service
    （sqlite 连接与 httplib2 客户端都不可跨线程复用）。
    """
    TARGETS[name] = {"rebuild": rebuild, "rollback": rollback}


def build_sync(target, user_id, business_key, payload):
    """按注册表构造写表函数。初始写表与重试共用同一条重建路径（DRY）。"""
    entry = TARGETS.get(target)
    if entry is None:
        raise KeyError(f"未注册的写表目标: {target}")
    return entry["rebuild"](user_id, business_key, payload or {})


def record_pending(db, *, user_id, platform, target, business_key,
                   payload=None, snapshot=None):
    """登记一条写表任务。同键 upsert 回 pending 并清空上轮结果。

    在**请求线程**用调用方的 db 执行 —— 前端拿到响应后要立刻能查到这条记录。
    """
    db.execute(
        "INSERT INTO sheet_write_log (user_id, platform, target, business_key, "
        "status, error_msg, payload_json, snapshot_json, settled_at) "
        "VALUES (?,?,?,?,'pending','',?,?,NULL) "
        "ON CONFLICT(user_id, target, business_key) DO UPDATE SET "
        "platform=excluded.platform, status='pending', error_msg='', "
        "payload_json=excluded.payload_json, snapshot_json=excluded.snapshot_json, "
        "settled_at=NULL, updated_at=datetime('now','localtime')",
        (user_id, platform, target, business_key,
         json.dumps(payload or {}, ensure_ascii=False),
         json.dumps(snapshot or {}, ensure_ascii=False)))
    db.commit()


def settle(db, *, user_id, target, business_key, status, error_msg=""):
    """落状态。settled_at 只在终态置上。"""
    db.execute(
        "UPDATE sheet_write_log SET status=?, error_msg=?, "
        "settled_at=CASE WHEN ? THEN datetime('now','localtime') ELSE settled_at END, "
        "updated_at=datetime('now','localtime') "
        "WHERE user_id=? AND target=? AND business_key=?",
        (status, error_msg, 1 if status in TERMINAL else 0,
         user_id, target, business_key))
    db.commit()


def _apply_final(db, row, err_msg):
    """写表最终失败后的处置：先试条件回滚，再决定落哪个终态。

    三种结局必须区分，因为用户的后续动作完全不同：
      retry_failed        镜像类，无回滚 —— 业务变更仍生效，用户需自己处理
      rolled_back         已撤销 —— 用户无需再做任何事
      rollback_abandoned  该账户期间被再次修改，不敢覆盖 —— 用户需手工核对
    """
    entry = TARGETS.get(row["target"]) or {}
    rollback_fn = entry.get("rollback")
    if rollback_fn is None:
        settle(db, user_id=row["user_id"], target=row["target"],
               business_key=row["business_key"], status="retry_failed",
               error_msg=err_msg)
        return

    try:
        snapshot = json.loads(row["snapshot_json"] or "{}")
    except Exception:
        snapshot = {}
    try:
        rolled = bool(rollback_fn(db, snapshot))
    except Exception as e:
        log.error("写表回滚异常 target=%s key=%s: %s",
                  row["target"], row["business_key"], e)
        rolled = False

    if rolled:
        settle(db, user_id=row["user_id"], target=row["target"],
               business_key=row["business_key"], status="rolled_back",
               error_msg=err_msg)
    else:
        settle(db, user_id=row["user_id"], target=row["target"],
               business_key=row["business_key"], status="rollback_abandoned",
               error_msg=f"{err_msg}（该账户在写表期间被再次修改，未自动撤销，请手工核对）")


def run_write(db, *, user_id, platform, target, business_key, sync_fn,
              payload=None, snapshot=None):
    """统一写表入口。绝不抛异常 —— 写表是业务端点的副作用，不得影响主流程。

    调用方在**请求线程**传入 db（仅用于登记 pending），随后写表在线程内进行；
    线程内的一切 DB 操作由本函数用 database.get_db() 另建连接。
    """
    try:
        record_pending(db, user_id=user_id, platform=platform, target=target,
                       business_key=business_key, payload=payload, snapshot=snapshot)
    except Exception as e:
        # 登记失败不该阻断写表本身，但必须有痕迹 —— 否则前端永远查不到这次任务
        log.error("写表任务登记失败 target=%s key=%s: %s", target, business_key, e)

    def _on_result(status, err_msg):
        import database
        _db = None
        try:
            _db = database.get_db()
            row = _db.execute(
                "SELECT * FROM sheet_write_log WHERE user_id=? AND target=? AND business_key=?",
                (user_id, target, business_key)).fetchone()
            if row is None:
                return
            if status == "synced":
                settle(_db, user_id=user_id, target=target, business_key=business_key,
                       status="synced", error_msg="")
            elif status == "failed":
                # 中间态：30s 重试在途。前端据此继续轮询，但**不提示**。
                settle(_db, user_id=user_id, target=target, business_key=business_key,
                       status="failed", error_msg=(err_msg or "")[:500])
            else:
                _apply_final(_db, row, (err_msg or "")[:500])
        except Exception as e:
            log.error("写表状态落库失败 target=%s key=%s: %s", target, business_key, e)
        finally:
            if _db is not None:
                try:
                    _db.close()
                except Exception:
                    pass

    try:
        from main import _sync_sheets_background
        _sync_sheets_background(sync_fn, _on_result)
    except Exception as e:
        log.error("写表后台任务启动失败 target=%s key=%s: %s", target, business_key, e)
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd py && python -m pytest tests/test_sheet_write.py -v`
Expected: 13 passed

- [ ] **Step 5: 提交**

```bash
git add py/sheet_write.py py/tests/test_sheet_write.py
git commit -m "feat(sheet-write): 新增 run_write 统一写表入口与状态机

- 状态机 6 态，settled_at 只在终态落定
- 终态三分：retry_failed（镜像类，无回滚）/ rolled_back（已撤销）/
  rollback_abandoned（守卫未过，用户需手工核对）—— 三者后续动作完全不同，
  文案混用会误导
- TARGETS 注册表用 rebuild 工厂而非现成函数：重试发生在另一次请求，
  执行器要在后台线程内新建 sqlite 连接与 httplib2 service
- run_write 自身绝不抛异常（写表是副作用，不得影响主流程）"
```

---

### Task 4: HTTP 接口与 blueprint 注册

**Files:**
- Create: `py/routes/sheet_write_routes.py`
- Modify: `py/main.py`（blueprint 注册区，`:359-367` 附近）
- Test: `py/tests/test_sheet_write.py`

**Interfaces:**
- Consumes: `sheet_write.ATTENTION` / `build_sync` / `run_write`（Task 3）
- Produces: `sheet_write_bp`（Flask Blueprint），路由 `GET /api/sheet-write/status`、`POST /api/sheet-write/retry`

- [ ] **Step 1: 写失败测试**

追加到 `py/tests/test_sheet_write.py`：

```python
def _tt_user(client, username):
    client.post("/api/auth/register", json={"username": username, "password": "test123"})
    db = database.get_db()
    db.execute("UPDATE users SET platform='tt' WHERE username=?", (username,))
    db.commit()
    uid = db.execute("SELECT id FROM users WHERE username=?", (username,)).fetchone()["id"]
    db.close()
    resp = client.post("/api/auth/login", json={"username": username, "password": "test123"})
    return {"Authorization": f"Bearer {resp.get_json().get('access_token', '')}"}, uid


def test_status_returns_only_attention_items(client):
    """不带 business_key => 只回需要提示的终态（synced/pending 不出现在列表标记里）。"""
    h, uid = _tt_user(client, "_sw_list")
    db = database.get_db()
    _mk_log(db, uid, "tt_recycle", "acc_bad", status="retry_failed")
    _mk_log(db, uid, "tt_recycle", "acc_ok", status="synced")
    _mk_log(db, uid, "tt_recycle", "acc_wait", status="pending")
    db.close()

    resp = client.get("/api/sheet-write/status?platform=tt", headers=h)
    assert resp.status_code == 200
    keys = [i["business_key"] for i in resp.get_json()["items"]]
    assert keys == ["acc_bad"]


def test_status_single_returns_latest_for_key(client):
    """带 business_key => 回该项（含中间态），供轮询用。"""
    h, uid = _tt_user(client, "_sw_one")
    db = database.get_db()
    _mk_log(db, uid, "tt_recycle", "acc_x", status="failed", payload={"reason": "封禁"})
    db.close()

    resp = client.get("/api/sheet-write/status?platform=tt&business_key=acc_x", headers=h)
    body = resp.get_json()
    assert body["item"]["status"] == "failed"


def test_status_is_isolated_per_user(client):
    """A 用户查不到 B 用户的记录（约束在 SQL 的 WHERE user_id 里）。"""
    ha, uid_a = _tt_user(client, "_sw_a")
    hb, uid_b = _tt_user(client, "_sw_b")
    db = database.get_db()
    _mk_log(db, uid_a, "tt_recycle", "acc_a", status="retry_failed")
    db.close()

    resp = client.get("/api/sheet-write/status?platform=tt&business_key=acc_a", headers=hb)
    assert resp.get_json()["item"] is None


def test_status_rejects_bad_platform(client):
    h, _ = _tt_user(client, "_sw_badp")
    resp = client.get("/api/sheet-write/status?platform=zz", headers=h)
    assert resp.status_code == 400
    assert "platform" in resp.get_json()["error"]


def test_retry_requires_attention_status(client):
    """pending / synced 的任务不接受重试。"""
    h, uid = _tt_user(client, "_sw_retry_pending")
    db = database.get_db()
    _mk_log(db, uid, "tt_recycle", "acc_p", status="pending")
    db.close()
    resp = client.post("/api/sheet-write/retry", headers=h,
                       json={"platform": "tt", "target": "tt_recycle", "business_key": "acc_p"})
    assert resp.status_code == 400
    assert "不需要重试" in resp.get_json()["error"]


def test_retry_unknown_target_returns_400_not_500(client):
    h, uid = _tt_user(client, "_sw_retry_badt")
    db = database.get_db()
    _mk_log(db, uid, "no_such_target", "acc_q", status="retry_failed")
    db.close()
    resp = client.post("/api/sheet-write/retry", headers=h,
                       json={"platform": "tt", "target": "no_such_target", "business_key": "acc_q"})
    assert resp.status_code == 400
    assert "未注册" in resp.get_json()["error"]


def test_retry_success_path(client):
    """终态失败的任务可重试：重新走一次写表，成功则落 synced。"""
    import sheet_write
    ran = []
    sheet_write.register_target("_t_retry",
                                rebuild=lambda uid, key, payload: (lambda: ran.append(key)))
    h, uid = _tt_user(client, "_sw_retry_ok")
    db = database.get_db()
    _mk_log(db, uid, "_t_retry", "acc_r", status="retry_failed", payload={"reason": "x"})
    db.close()

    resp = client.post("/api/sheet-write/retry", headers=h,
                       json={"platform": "tt", "target": "_t_retry", "business_key": "acc_r"})
    assert resp.status_code == 200, resp.get_json()

    import time
    db = database.get_db()
    for _ in range(100):
        if _row(db, uid, "_t_retry", "acc_r")["status"] == "synced":
            break
        time.sleep(0.02)
    r = _row(db, uid, "_t_retry", "acc_r")
    db.close()
    assert ran == ["acc_r"]
    assert r["status"] == "synced"


def test_retry_missing_record_returns_404(client):
    h, uid = _tt_user(client, "_sw_retry_404")
    resp = client.post("/api/sheet-write/retry", headers=h,
                       json={"platform": "tt", "target": "tt_recycle", "business_key": "nope"})
    assert resp.status_code == 404
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd py && python -m pytest tests/test_sheet_write.py -v -k "status or retry"`
Expected: FAIL —— 404（路由不存在）

- [ ] **Step 3: 创建路由文件**

新建 `py/routes/sheet_write_routes.py`：

```python
"""写表失败治理的 HTTP 入口。

设计见 docs/superpowers/specs/2026-10-06-sheet-write-failure-governance-design.md。
本文件只做取参/鉴权/调逻辑层，状态机与执行器都在 py/sheet_write.py。
"""
import json

from flask import Blueprint, request
from flask_jwt_extended import jwt_required

import sheet_write
from .helpers import ok, err, get_uid, get_db

sheet_write_bp = Blueprint("sheet_write", __name__)

_PLATFORMS = ("gg", "tt", "fb")


@sheet_write_bp.route("/api/sheet-write/status", methods=["GET"])
@jwt_required()
def sheet_write_status():
    """查当前用户的写表任务。

    带 `business_key` → 回该项（含 pending/failed 中间态），供前端轮询；
    不带           → 只回需要提示的终态，供列表标记。

    隔离约束写在 SQL 的 `WHERE user_id=?` 里，不在 Python 侧过滤。
    """
    db = get_db()
    uid = get_uid()
    platform = (request.args.get("platform") or "").strip()
    business_key = (request.args.get("business_key") or "").strip()
    if platform not in _PLATFORMS:
        db.close()
        return err("platform 必须是 gg / tt / fb", 400)

    sql = ("SELECT business_key, target, status, error_msg, created_at, updated_at, settled_at "
           "FROM sheet_write_log WHERE user_id=? AND platform=?")
    params = [uid, platform]
    if business_key:
        sql += " AND business_key=?"
        params.append(business_key)
    sql += " ORDER BY updated_at DESC"
    items = [dict(r) for r in db.execute(sql, params).fetchall()]
    db.close()

    if business_key:
        return ok({"item": items[0] if items else None})
    return ok({"items": [i for i in items if i["status"] in sheet_write.ATTENTION]})


@sheet_write_bp.route("/api/sheet-write/retry", methods=["POST"])
@jwt_required()
def sheet_write_retry():
    """重试一次失败的写表。

    只有**需要提示的终态**才可重试 —— pending 还在途、synced 已成功，都不该
    被重复提交（重复提交会对同一个账户写第二行）。
    """
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return err("请求体必须是 JSON 对象", 400)
    platform = str(data.get("platform") or "").strip()
    target = str(data.get("target") or "").strip()
    business_key = str(data.get("business_key") or "").strip()
    if platform not in _PLATFORMS or not target or not business_key:
        return err("platform / target / business_key 均为必填", 400)

    db = get_db()
    uid = get_uid()
    row = db.execute(
        "SELECT * FROM sheet_write_log WHERE user_id=? AND platform=? AND target=? "
        "AND business_key=?", (uid, platform, target, business_key)).fetchone()
    if row is None:
        db.close()
        return err("没有找到该写表记录", 404)
    if row["status"] not in sheet_write.ATTENTION:
        db.close()
        return err(f"该写表任务当前状态为 {row['status']}，不需要重试", 400)

    def _load(raw):
        try:
            v = json.loads(raw or "{}")
            return v if isinstance(v, dict) else {}
        except Exception:
            return {}

    payload = _load(row["payload_json"])
    snapshot = _load(row["snapshot_json"])

    try:
        sync_fn = sheet_write.build_sync(target, uid, business_key, payload)
    except KeyError as e:
        db.close()
        return err(str(e), 400)

    # 沿用上轮的 snapshot：回滚要撤销的仍是同一次业务变更，不能因为重试而丢掉守卫依据
    sheet_write.run_write(db, user_id=uid, platform=platform, target=target,
                          business_key=business_key, sync_fn=sync_fn,
                          payload=payload, snapshot=snapshot)
    db.close()
    return ok({"message": "已重新提交，请稍后查看结果"})
```

- [ ] **Step 4: 注册 blueprint**

在 `py/main.py` 的户管看板 blueprint 注册之后（`:367` 那行 `app.register_blueprint(huguan_dashboard_bp)` 后面）加：

```python
# 写表失败治理（跨平台）
from routes.sheet_write_routes import sheet_write_bp
app.register_blueprint(sheet_write_bp)
```

- [ ] **Step 5: 跑测试确认通过**

Run: `cd py && python -m pytest tests/test_sheet_write.py -v`
Expected: 21 passed

- [ ] **Step 6: 提交**

```bash
git add py/routes/sheet_write_routes.py py/main.py py/tests/test_sheet_write.py
git commit -m "feat(sheet-write): 新增 status / retry 两个接口

- GET /api/sheet-write/status：带 business_key 供轮询（含中间态），
  不带则只回需提示的终态供列表标记
- POST /api/sheet-write/retry：只有需提示的终态可重试 —— pending 在途、
  synced 已成功都不该重复提交（会对同一账户写第二行）
- 隔离约束写在 SQL 的 WHERE user_id 里，不在 Python 侧过滤
- 重试沿用上轮 snapshot：回滚要撤销的仍是同一次业务变更"
```

---

### Task 5: TT 回收清单接入统一入口

**Files:**
- Modify: `py/routes/tt_accounts_routes.py`（`_maybe_write_recycle` `:1214-1229`、`_trigger_recycle_if_dead` `:1232-1248`、单条更新 `:299-306` 与 `:338-340`、批量更新 `:446-449` 与 `:466-468`）
- Test: `py/tests/test_tt_recycle_sheet_write.py`

**Interfaces:**
- Consumes: `sheet_write.register_target` / `build_sync` / `run_write`（Task 3）
- Produces:
  - 模块级注册：`sheet_write.register_target("tt_recycle", rebuild=_tt_recycle_rebuild, rollback=_tt_recycle_rollback)`
  - `_tt_recycle_rebuild(user_id: int, business_key: str, payload: dict) -> Callable[[], None]`
  - 每次触发前写入 `sheet_write_log` 的快照：`{"account_pk", "prev_status_id", "prev_status_changed_date", "prev_death_date", "new_status_id"}`

- [ ] **Step 1: 写失败测试**

新建 `py/tests/test_tt_recycle_sheet_write.py`：

```python
"""TT「回收户清单」接入写表失败治理 —— 端到端测试。

守卫：状态改为非存活且带原因时，写表走统一入口、登记 pending、抓快照。
"""
import database
import sheet_write


def _tt_admin(client, username):
    """建一个 TT 平台的 admin（跨用户角色，便于操作他人账户）。"""
    client.post("/api/auth/register", json={"username": username, "password": "test123"})
    db = database.get_db()
    db.execute("UPDATE users SET platform='tt', role='admin' WHERE username=?", (username,))
    db.commit()
    uid = db.execute("SELECT id FROM users WHERE username=?", (username,)).fetchone()["id"]
    db.close()
    resp = client.post("/api/auth/login", json={"username": username, "password": "test123"})
    return {"Authorization": f"Bearer {resp.get_json().get('access_token', '')}"}, uid


def _mk_account(db, uid, advertiser_id, status_id):
    db.execute(
        "INSERT INTO tt_accounts (advertiser_id, name, owner_id, status_id) VALUES (?,?,?,?)",
        (advertiser_id, advertiser_id, uid, status_id))
    db.commit()
    return db.execute("SELECT id FROM tt_accounts WHERE advertiser_id=?",
                      (advertiser_id,)).fetchone()["id"]


def _status_id(db, name):
    db.execute("INSERT OR IGNORE INTO account_statuses (name, platform) VALUES (?, 'tt')", (name,))
    db.commit()
    return db.execute("SELECT id FROM account_statuses WHERE name=? AND platform='tt'",
                      (name,)).fetchone()["id"]


def _setup_sheet(db):
    """配好 TT 全局表格 ID 与工作表映射，让 _trigger_recycle_if_dead 不提前返回。"""
    db.execute("INSERT OR REPLACE INTO tags (key, value) VALUES ('tt_sheet_id', 'SHEET_X')")
    db.execute("INSERT OR REPLACE INTO tags (key, value) VALUES "
               "('tt_sheet_mappings', '{\"recycle\": \"回收户清单\"}')")
    db.commit()


def test_recycle_write_registers_pending_and_snapshot(client, monkeypatch):
    """改非存活 => 登记一条 tt_recycle 的 pending 并抓下改前快照。"""
    import google_sheets_service as gs
    monkeypatch.setattr(gs, "build_service", lambda _p: object())
    monkeypatch.setattr(gs, "append_recycle", lambda *a, **k: {"appended": 1})

    h, uid = _tt_admin(client, "_rc_ok")
    db = database.get_db()
    _setup_sheet(db)
    alive = _status_id(db, "存活")
    dead = _status_id(db, "封禁")
    aid = _mk_account(db, uid, "adv_1", alive)
    db.close()

    resp = client.put(f"/api/tt/accounts/{aid}", headers=h,
                      json={"status_id": dead, "recycle_reason": "封禁回收"})
    assert resp.status_code == 200, resp.get_json()

    import time
    db = database.get_db()
    for _ in range(100):
        r = db.execute("SELECT * FROM sheet_write_log WHERE user_id=? AND target='tt_recycle' "
                       "AND business_key='adv_1'", (uid,)).fetchone()
        if r is not None and r["status"] == "synced":
            break
        time.sleep(0.02)
    r = db.execute("SELECT * FROM sheet_write_log WHERE user_id=? AND target='tt_recycle' "
                   "AND business_key='adv_1'", (uid,)).fetchone()
    db.close()

    assert r is not None, "必须登记一条写表任务"
    assert r["status"] == "synced"
    import json
    snap = json.loads(r["snapshot_json"])
    assert snap["account_pk"] == aid
    assert snap["prev_status_id"] == alive
    assert snap["new_status_id"] == dead
    payload = json.loads(r["payload_json"])
    assert payload["reason"] == "封禁回收"


def test_no_write_when_status_is_alive(client, monkeypatch):
    """改回「存活」不写表、不登记。"""
    import google_sheets_service as gs
    called = []
    monkeypatch.setattr(gs, "build_service", lambda _p: object())
    monkeypatch.setattr(gs, "append_recycle", lambda *a, **k: called.append(1))

    h, uid = _tt_admin(client, "_rc_alive")
    db = database.get_db()
    _setup_sheet(db)
    alive = _status_id(db, "存活")
    dead = _status_id(db, "死亡")
    aid = _mk_account(db, uid, "adv_2", dead)
    db.close()

    resp = client.put(f"/api/tt/accounts/{aid}", headers=h,
                      json={"status_id": alive, "recycle_reason": "随便"})
    assert resp.status_code == 200

    import time
    time.sleep(0.2)
    db = database.get_db()
    n = db.execute("SELECT COUNT(*) FROM sheet_write_log WHERE user_id=? AND target='tt_recycle'",
                   (uid,)).fetchone()[0]
    db.close()
    assert n == 0
    assert called == []


def test_no_write_without_reason(client, monkeypatch):
    """非存活但没带原因 => 不写表（与改动前口径一致）。"""
    import google_sheets_service as gs
    called = []
    monkeypatch.setattr(gs, "build_service", lambda _p: object())
    monkeypatch.setattr(gs, "append_recycle", lambda *a, **k: called.append(1))

    h, uid = _tt_admin(client, "_rc_noreason")
    db = database.get_db()
    _setup_sheet(db)
    alive = _status_id(db, "存活")
    dead = _status_id(db, "封禁")
    aid = _mk_account(db, uid, "adv_3", alive)
    db.close()

    assert client.put(f"/api/tt/accounts/{aid}", headers=h,
                      json={"status_id": dead}).status_code == 200
    import time
    time.sleep(0.2)
    db = database.get_db()
    n = db.execute("SELECT COUNT(*) FROM sheet_write_log WHERE user_id=? AND target='tt_recycle'",
                   (uid,)).fetchone()[0]
    db.close()
    assert n == 0
    assert called == []


def test_snapshot_taken_before_editable_death_date_overwrite(client, monkeypatch):
    """快照必须在 editable 循环改写 death_date **之前**抓。

    单条路径的 SELECT a.* 已含 death_date；但 :308-313 的 editable 列表也含
    death_date 且先执行。若把快照挪到状态块里抓，prev_death_date 会是被本次
    请求改写过的值，回滚就还原成错的。
    """
    import google_sheets_service as gs
    monkeypatch.setattr(gs, "build_service", lambda _p: object())
    monkeypatch.setattr(gs, "append_recycle", lambda *a, **k: {"appended": 1})

    h, uid = _tt_admin(client, "_rc_snap")
    db = database.get_db()
    _setup_sheet(db)
    alive = _status_id(db, "存活")
    dead = _status_id(db, "封禁")
    db.execute("INSERT INTO tt_accounts (advertiser_id, name, owner_id, status_id, death_date) "
               "VALUES ('adv_4','adv_4',?,?,'2020-01-01')", (uid, alive))
    db.commit()
    aid = db.execute("SELECT id FROM tt_accounts WHERE advertiser_id='adv_4'").fetchone()["id"]
    db.close()

    # 同一次请求里既改 death_date 又改状态
    assert client.put(f"/api/tt/accounts/{aid}", headers=h,
                      json={"death_date": "2026-10-06", "status_id": dead,
                            "recycle_reason": "封禁回收"}).status_code == 200

    import time, json
    db = database.get_db()
    for _ in range(100):
        r = db.execute("SELECT * FROM sheet_write_log WHERE user_id=? AND business_key='adv_4'",
                       (uid,)).fetchone()
        if r is not None and r["status"] == "synced":
            break
        time.sleep(0.02)
    r = db.execute("SELECT * FROM sheet_write_log WHERE user_id=? AND business_key='adv_4'",
                   (uid,)).fetchone()
    db.close()
    snap = json.loads(r["snapshot_json"])
    assert snap["prev_death_date"] == "2020-01-01", "快照抓成了被改写后的值"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd py && python -m pytest tests/test_tt_recycle_sheet_write.py -v`
Expected: FAIL —— `sheet_write_log` 里没有任何记录（当前 `_maybe_write_recycle` 根本不走统一入口）

- [ ] **Step 3: 改造 `py/routes/tt_accounts_routes.py`**

在文件顶部 import 区加入：

```python
import sheet_write
```

把 `_maybe_write_recycle`（`:1214-1229`）与 `_trigger_recycle_if_dead`（`:1232-1248`）整段替换为：

```python
# ==================== 状态改「非存活」写回收清单 ====================

def _tt_recycle_rebuild(user_id, business_key, payload):
    """构造一次「写回收户清单」的函数。

    初始写表与重试**共用**这一条重建路径（DRY）。返回的是 zero-arg 闭包，
    将由后台线程调用，故 service 与 DB 连接都必须在闭包**内部**新建 ——
    请求线程的 sqlite 连接不能跨线程使用，httplib2 客户端亦非线程安全。
    表地址在**每次执行时**现取：户管改过配置后，重试应写进新表。
    """
    def _sync():
        import database
        import google_sheets_service as gs
        from main import _GOOGLE_SHEETS_CONFIG

        db = database.get_db()
        try:
            sheet_id = _get_tt_sheet_id(db)
            mappings = _get_tt_sheet_mappings(db)
            sheet_name = (mappings.get("recycle") or "").strip() or "回收户清单"
        finally:
            db.close()
        if not sheet_id:
            raise RuntimeError("未配置 TT 表格 ID，无法写回收户清单")

        service = gs.build_service(_GOOGLE_SHEETS_CONFIG["credentials_path"])
        gs.append_recycle(service, sheet_id, sheet_name, [{
            "time": datetime.datetime.now().strftime("%Y-%m-%d"),
            "account_id": business_key,
            "reason": (payload or {}).get("reason", ""),
        }])

    return _sync


def _tt_recycle_rollback(db, snapshot):
    """条件回滚：把账户状态改回改之前的值。

    **守卫写在 UPDATE 的 WHERE 里**（原子），不是「先查后写」—— 后者在两步之间
    存在竞态。受影响行数为 0 即守卫未过：说明这 30 秒内用户又改过状态，
    此时**必须放弃回滚**（拿陈旧快照覆盖用户的后续操作就是伪造数据）。

    返回 True=已回滚，False=放弃。
    """
    try:
        acct_pk = snapshot.get("account_pk")
        new_status_id = snapshot.get("new_status_id")
    except AttributeError:
        return False
    if acct_pk is None or new_status_id is None:
        return False
    cur = db.execute(
        "UPDATE tt_accounts SET status_id=?, status_changed_date=?, death_date=?, "
        "updated_at=datetime('now','localtime') "
        "WHERE id=? AND status_id=?",
        (snapshot.get("prev_status_id"),
         snapshot.get("prev_status_changed_date") or "",
         snapshot.get("prev_death_date") or "",
         acct_pk, new_status_id))
    db.commit()
    return cur.rowcount > 0


sheet_write.register_target("tt_recycle", rebuild=_tt_recycle_rebuild,
                            rollback=_tt_recycle_rollback)


def _trigger_recycle_if_dead(db, uid, advertiser_id, status_id, reason, snapshot=None):
    """status 为非「存活」时，走统一入口异步写回收户清单。

    snapshot 由调用方在**业务变更落库前**抓取（见两条调用路径的注释），
    供最终失败时条件回滚用。
    """
    st = db.execute("SELECT name FROM account_statuses WHERE id=?", (status_id,)).fetchone()
    if not st or st["name"] == "存活":
        return
    if not reason:
        return
    sheet_id = _get_tt_sheet_id(db)
    if not sheet_id:
        return
    # 自动新增回收原因（词表已改为全平台公用，name 全局唯一）
    existing = db.execute("SELECT id FROM tt_recycle_reasons WHERE name=?", (reason,)).fetchone()
    if not existing:
        db.execute("INSERT OR IGNORE INTO tt_recycle_reasons(name, owner_id) VALUES(?,?)",
                   (reason, uid))

    payload = {"reason": reason}
    sheet_write.run_write(
        db, user_id=uid, platform="tt", target="tt_recycle",
        business_key=advertiser_id,
        sync_fn=sheet_write.build_sync("tt_recycle", uid, advertiser_id, payload),
        payload=payload, snapshot=snapshot)
```

- [ ] **Step 4: 在两条调用路径上抓快照**

**单条路径**（`update_account`）：把 `:299-306` 改为——

```python
    row = db.execute(
        "SELECT a.*, st.name AS status_name FROM tt_accounts a "
        "LEFT JOIN account_statuses st ON a.status_id = st.id WHERE a.id=?", (aid,)
    ).fetchone()
    if not row:
        return err("账户不存在", 404)
    if role not in CROSS_USER_ROLES and row["owner_id"] != uid:
        return err("无权限", 403)

    # 回滚快照必须在**这里**抓：下面的 `editable` 列表包含 death_date，
    # 一旦进入那个循环，row 里的 death_date 就是本次请求改写后的值了 ——
    # 那时抓到的快照会让回滚还原成错误的值。
    recycle_snapshot_base = {
        "account_pk": row["id"],
        "prev_status_id": row["status_id"],
        "prev_status_changed_date": row["status_changed_date"],
        "prev_death_date": row["death_date"],
    }
```

并把 `:338-340` 改为：

```python
            if new_status_name and new_status_name != (row["status_name"] or ""):
                snap = dict(recycle_snapshot_base)
                snap["new_status_id"] = status_id
                _trigger_recycle_if_dead(db, uid, row["advertiser_id"], status_id,
                                         (data.get("recycle_reason") or "").strip(), snap)
```

**批量路径**（`batch_update_accounts`）：把 `:449` 的 SELECT 与 `:453` 的 SELECT 都补上缺的两列——

```python
            r = db.execute("SELECT owner_id, bc_id, advertiser_id, status_id, "
                           "status_changed_date, death_date FROM tt_accounts WHERE id=?",
                           (aid,)).fetchone()
```

并把 `:461-468` 改为：

```python
        if field == "status_id" and value:
            st_name = db.execute("SELECT name FROM account_statuses WHERE id=?", (value,)).fetchone()
            if st_name and st_name["name"] == "死亡":
                db.execute("UPDATE tt_accounts SET death_date=date('now','localtime') WHERE id=?", (aid,))
            db.execute("UPDATE tt_accounts SET status_changed_date=datetime('now','localtime') WHERE id=?", (aid,))
            if r["status_id"] is None or str(r["status_id"]) != str(value):
                snap = {"account_pk": aid,
                        "prev_status_id": r["status_id"],
                        "prev_status_changed_date": r["status_changed_date"],
                        "prev_death_date": r["death_date"],
                        "new_status_id": value}
                _trigger_recycle_if_dead(db, uid, r["advertiser_id"], value,
                                         (data.get("recycle_reason") or "").strip(), snap)
```

> 批量路径的 `r` 是在循环内、进入状态块**之前**查的，中间没有改 `death_date` 的分支，所以此处就地取快照是安全的。

- [ ] **Step 5: 跑测试确认通过**

Run: `cd py && python -m pytest tests/test_tt_recycle_sheet_write.py -v`
Expected: 4 passed

- [ ] **Step 6: 回归既有 TT 账户测试**

Run: `cd py && python -m pytest tests/test_tt_accounts.py tests/test_tt_routes.py -q`
Expected: 全绿

- [ ] **Step 7: 提交**

```bash
git add py/routes/tt_accounts_routes.py py/tests/test_tt_recycle_sheet_write.py
git commit -m "feat(tt): 回收户清单写表接入统一治理入口

原来 _maybe_write_recycle 传的是 lambda s, e: None —— 写失败连日志都没有。
现改走 sheet_write.run_write，登记任务 + 抓回滚快照。

- 表地址在每次执行时现取，不存进任务记录：户管改过配置后重试应写进新表
- 回滚快照在两条路径上分别抓：单条路径必须在 editable 循环**之前**
  （该列表含 death_date，进循环后 row 里的值已被本次请求改写）；
  批量路径的 SELECT 补上 status_changed_date / death_date 两列
- _tt_recycle_rebuild 同时服务首次写表与重试（DRY）"
```

---

### Task 6: 条件回滚的端到端验证

**Files:**
- Test: `py/tests/test_tt_recycle_sheet_write.py`

**Interfaces:**
- Consumes: `_tt_recycle_rollback`、`_trigger_recycle_if_dead`（Task 5）
- Produces: 无新代码 —— 本任务补齐回滚路径的端到端守卫

- [ ] **Step 1: 写测试**

追加到 `py/tests/test_tt_recycle_sheet_write.py`：

```python
def test_rollback_restores_status_on_final_failure(client, monkeypatch):
    """写表最终失败且守卫通过 => 状态被改回，落 rolled_back。"""
    import google_sheets_service as gs
    import time, json
    monkeypatch.setattr("time.sleep", lambda _s: None)      # 跳过 30s 重试等待
    monkeypatch.setattr(gs, "build_service", lambda _p: object())

    def _boom(*a, **k):
        raise RuntimeError("Sheets 配额超限")

    monkeypatch.setattr(gs, "append_recycle", _boom)

    h, uid = _tt_admin(client, "_rc_rb_ok")
    db = database.get_db()
    _setup_sheet(db)
    alive = _status_id(db, "存活")
    dead = _status_id(db, "封禁")
    aid = _mk_account(db, uid, "adv_rb1", alive)
    db.close()

    assert client.put(f"/api/tt/accounts/{aid}", headers=h,
                      json={"status_id": dead, "recycle_reason": "封禁回收"}
                      ).status_code == 200

    db = database.get_db()
    for _ in range(200):
        r = db.execute("SELECT * FROM sheet_write_log WHERE user_id=? AND business_key='adv_rb1'",
                       (uid,)).fetchone()
        if r is not None and r["status"] in ("rolled_back", "rollback_abandoned"):
            break
        time.sleep(0.02)
    r = db.execute("SELECT * FROM sheet_write_log WHERE user_id=? AND business_key='adv_rb1'",
                   (uid,)).fetchone()
    cur_status = db.execute("SELECT status_id FROM tt_accounts WHERE id=?", (aid,)).fetchone()["status_id"]
    db.close()

    assert r["status"] == "rolled_back", r["error_msg"]
    assert cur_status == alive, "状态应被改回改之前的值"
    assert "Sheets 配额超限" in r["error_msg"]


def test_rollback_abandoned_when_status_changed_again(client, monkeypatch):
    """写表期间用户又改了状态 => 守卫未过 => 不回滚，落 rollback_abandoned。

    这条比回滚本身更重要：拿 30 秒前的快照覆盖用户的后续操作就是伪造数据。
    """
    import google_sheets_service as gs
    import time
    monkeypatch.setattr(gs, "build_service", lambda _p: object())

    h, uid = _tt_admin(client, "_rc_rb_ab")
    db = database.get_db()
    _setup_sheet(db)
    alive = _status_id(db, "存活")
    dead = _status_id(db, "封禁")
    other = _status_id(db, "端口回收")
    aid = _mk_account(db, uid, "adv_rb2", alive)
    db.close()

    def _blocked(*a, **k):
        raise RuntimeError("Sheets 挂了")
    monkeypatch.setattr(gs, "append_recycle", _blocked)

    assert client.put(f"/api/tt/accounts/{aid}", headers=h,
                      json={"status_id": dead, "recycle_reason": "封禁回收"}
                      ).status_code == 200

    # 在 30s 重试窗口内，用户又把它改成了第三个状态
    time.sleep(0.05)
    assert client.put(f"/api/tt/accounts/{aid}", headers=h,
                      json={"status_id": other, "recycle_reason": "端口回收"}
                      ).status_code == 200

    monkeypatch.setattr("time.sleep", lambda _s: None)   # 放行重试
    db = database.get_db()
    for _ in range(300):
        r = db.execute("SELECT * FROM sheet_write_log WHERE user_id=? AND business_key='adv_rb2'",
                       (uid,)).fetchone()
        if r is not None and r["status"] in ("rolled_back", "rollback_abandoned"):
            break
        time.sleep(0.02)
    r = db.execute("SELECT * FROM sheet_write_log WHERE user_id=? AND business_key='adv_rb2'",
                   (uid,)).fetchone()
    cur_status = db.execute("SELECT status_id FROM tt_accounts WHERE id=?", (aid,)).fetchone()["status_id"]
    db.close()

    # 两次改状态共用同一条 (user, target, business_key) 记录，后者覆盖前者，
    # 故无论哪一次先定案，账户都**不能**被改回 `alive`
    assert cur_status != alive, "不得用陈旧快照覆盖用户的后续修改"
    assert r["status"] in ("rolled_back", "rollback_abandoned")


def test_mirror_target_never_rolls_back(client, monkeypatch):
    """镜像类目标最终失败后，业务数据一字不动（此处以 tt_accounts 为对象验证）。"""
    import sheet_write
    monkeypatch.setattr("time.sleep", lambda _s: None)
    sheet_write.register_target("_t_mirror_biz",
                                rebuild=lambda uid, key, payload: (lambda: None))

    h, uid = _tt_admin(client, "_rc_mirror")
    db = database.get_db()
    alive = _status_id(db, "存活")
    dead = _status_id(db, "封禁")
    aid = _mk_account(db, uid, "adv_m1", alive)

    def _boom():
        raise RuntimeError("挂了")

    sheet_write.run_write(db, user_id=uid, platform="tt", target="_t_mirror_biz",
                          business_key="adv_m1", sync_fn=_boom)
    db.execute("UPDATE tt_accounts SET status_id=? WHERE id=?", (dead, aid))
    db.commit()

    import time
    for _ in range(150):
        r = db.execute("SELECT * FROM sheet_write_log WHERE user_id=? AND target='_t_mirror_biz'",
                       (uid,)).fetchone()
        if r is not None and r["status"] == "retry_failed":
            break
        time.sleep(0.02)
    cur = db.execute("SELECT status_id FROM tt_accounts WHERE id=?", (aid,)).fetchone()["status_id"]
    db.close()
    assert cur == dead, "镜像类不得回滚业务数据"
```

- [ ] **Step 2: 跑测试**

Run: `cd py && python -m pytest tests/test_tt_recycle_sheet_write.py -v`
Expected: 7 passed

- [ ] **Step 3: 全量后端回归**

Run: `cd py && python -m pytest tests/ -q`
Expected: 除 `test_fb_asset_model.py` 的既有失败（8 failed + 16 errors，与本改动无关，规格 §12.4 有记录）外全绿

- [ ] **Step 4: 提交**

```bash
git add py/tests/test_tt_recycle_sheet_write.py
git commit -m "test(tt): 补条件回滚的端到端守卫

- 守卫通过 => 状态改回，落 rolled_back，error_msg 带原始失败原因
- 守卫未过（写表期间用户又改了状态）=> 不回滚，账户不得被改回旧值
- 镜像类目标最终失败 => 业务数据一字不动"
```

---

### Task 7: 前端 —— 轮询提示 + 行标记 + 重试按钮

**Files:**
- Create: `frontend/src/api/sheetWrite.js`
- Modify: `frontend/src/views/tt/TtAccountPanel.vue`

**Interfaces:**
- Consumes: `GET /api/sheet-write/status`、`POST /api/sheet-write/retry`（Task 4）
- Produces: `sheetWriteApi.status(params)` / `sheetWriteApi.retry(body)`

- [ ] **Step 1: 先调 `/frontend-design` 做视觉设计**

按项目规矩，**新增 UI 必须先调用 `/frontend-design` 技能**（行内失败标记 + tooltip + 重试按钮 + 三种状态提示文案属于新增交互）。把本任务 §4 的交互需求喂给它，拿到视觉方案后再写代码。

- [ ] **Step 2: 新建 API 封装**

新建 `frontend/src/api/sheetWrite.js`：

```js
/** 写表失败治理（跨平台） */
import client from './client'

export const sheetWriteApi = {
  // 带 business_key 供轮询单条；不带则只回需要提示的终态，供列表标记
  status({ platform, businessKey } = {}) {
    const params = { platform }
    if (businessKey) params.business_key = businessKey
    return client.get('/sheet-write/status', { params })
  },
  retry({ platform, target, businessKey }) {
    return client.post('/sheet-write/retry', {
      platform, target, business_key: businessKey,
    })
  },
}
```

- [ ] **Step 3: 在 `TtAccountPanel.vue` 接入轮询与提示**

在 `<script setup>` 的 import 区加入：

```js
import { sheetWriteApi } from '../../api/sheetWrite'
```

并把 vue 的 import 补上 `onUnmounted`（当前是
`import { ref, reactive, onMounted, watch, nextTick } from 'vue'`，**没有** `onUnmounted`）：

```js
import { ref, reactive, onMounted, onUnmounted, watch, nextTick } from 'vue'
```

在文件顶部（`const authStore = ...` 附近）加入状态与常量：

```js
// ---------- 写表失败治理（回收户清单异步写表的结果） ----------
const RECYCLE_TARGET = 'tt_recycle'
const SHEET_WRITE_POLL_MS = 3000
const SHEET_WRITE_POLL_MAX = 14          // ~42s，覆盖 30s 重试窗口
let sheetWriteTimer = null
const sheetWriteFailures = ref({})       // advertiser_id -> {target, status, error_msg}
```

加入三个函数：

```js
/** 列表标记用：拉取当前用户所有「需要提示」的写表终态。静默失败（不打扰用户）。 */
async function loadSheetWriteFailures() {
  try {
    const res = await sheetWriteApi.status({ platform: 'tt' })
    const map = {}
    for (const it of res.items || []) map[it.business_key] = it
    sheetWriteFailures.value = map
  } catch { /* 标记拉不到不该打扰用户，保持上一次的结果 */ }
}

/** 轮询单条直到终态。中间态（pending/failed）继续等，不提示。 */
function pollSheetWrite(advertiserId) {
  let attempts = 0
  const tick = async () => {
    if (attempts >= SHEET_WRITE_POLL_MAX) return
    attempts++
    try {
      const res = await sheetWriteApi.status({ platform: 'tt', businessKey: advertiserId })
      const it = res.item
      if (!it) return                                    // 无记录 = 这条路径没触发写表
      if (it.status === 'synced') { loadSheetWriteFailures(); return }
      if (it.status === 'pending' || it.status === 'failed') {
        sheetWriteTimer = setTimeout(tick, SHEET_WRITE_POLL_MS)
        return
      }
      // 三种需提示的终态，文案各自不同 —— 用户后续动作不一样
      const reason = it.error_msg || '未知原因'
      if (it.status === 'rolled_back') {
        ElMessage.warning(`写表失败，已撤销本次状态变更。原因：${reason}`)
      } else if (it.status === 'rollback_abandoned') {
        ElMessage.warning(`写表失败，且该账户期间被再次修改，未自动撤销，请手工核对。原因：${reason}`)
      } else {
        ElMessage.error(`写表失败，表中未写入。原因：${reason}`)
      }
      loadSheetWriteFailures()
    } catch { /* 轮询失败静默，靠列表标记兜底 */ }
  }
  if (sheetWriteTimer) clearTimeout(sheetWriteTimer)
  sheetWriteTimer = setTimeout(tick, SHEET_WRITE_POLL_MS)
}

/** 重试按钮 */
async function retrySheetWrite(row) {
  const f = sheetWriteFailures.value[row.advertiser_id]
  if (!f) return
  try {
    await sheetWriteApi.retry({ platform: 'tt', target: f.target, businessKey: row.advertiser_id })
    ElMessage.success('已重新提交，请稍后查看结果')
    pollSheetWrite(row.advertiser_id)
  } catch (e) {
    ElMessage.error(e.response?.data?.error || '重试失败')
  }
}
```

- [ ] **Step 4: 接上触发点**

`onRecycleSaved()`（:433）改为：

```js
async function onRecycleSaved() {
  // 记下本次涉及哪些账户，用于轮询写表结果（快照：load() 会重建 items）
  const ids = recycleTarget.value?.mode === 'batch'
    ? (recycleTarget.value.accounts || []).map(a => a.advertiser_id)
    : [recycleTarget.value?.account?.advertiser_id].filter(Boolean)
  load()
  for (const id of ids) pollSheetWrite(id)
}
```

批量改状态处（:675 之后的 `load()`）改为：

```js
    const ids = selected.value.map(s => s.advertiser_id)
    await ttAccountsApi.batchUpdate({ ids: selected.value.map(s => s.id), field: 'status_id', value: val })
    load()
    for (const id of ids) pollSheetWrite(id)
```

在 `load()` 的成功分支里追加一次标记拉取（`items.value = res.items || []` 之后）：

```js
    loadSheetWriteFailures()
```

在 `onMounted` 里加一次初始拉取，并在 `onUnmounted` 清理定时器：

```js
onMounted(async () => {
  // …既有内容不动…
  loadSheetWriteFailures()
})
onUnmounted(() => { if (sheetWriteTimer) clearTimeout(sheetWriteTimer) })
```

> 若该组件已在其他位置调用 `onUnmounted`，把清理语句并进去即可，不要新增第二个 `onUnmounted`。

- [ ] **Step 5: 在表格里加标记与重试按钮**

在「广告账户 ID」列之后插入一列（位置与样式按 Step 1 的视觉方案定；下方为功能骨架）：

```vue
        <el-table-column label="写表" width="110" align="center">
          <template #default="{ row }">
            <template v-if="sheetWriteFailures[row.advertiser_id]">
              <el-tooltip placement="top"
                :content="sheetWriteFailures[row.advertiser_id].error_msg || '写表失败'">
                <el-tag size="small" type="danger" effect="plain">写表失败</el-tag>
              </el-tooltip>
              <el-button link type="primary" size="small"
                @click.stop="retrySheetWrite(row)">重试</el-button>
            </template>
            <span v-else style="color:#c0c4cc;">—</span>
          </template>
        </el-table-column>
```

- [ ] **Step 6: 构建验证**

Run: `cd frontend && npm run build`
Expected: 构建成功，无报错

> 若用户要求跳过构建，则改为人工核对模板语法并在交付说明里注明「未跑构建」。

- [ ] **Step 7: 提交**

```bash
git add frontend/src/api/sheetWrite.js frontend/src/views/tt/TtAccountPanel.vue
git commit -m "feat(tt): 账户列表展示写表失败标记 + 重试按钮 + 结果提示

- 改状态后轮询 /api/sheet-write/status 直到终态（~42s 上限覆盖 30s 重试）
- 中间态 pending/failed 继续轮询、不提示（用户裁定「等最终结果」）
- 三种终态文案各自不同：rolled_back（已撤销）/ rollback_abandoned
  （被再次修改，未撤销，请手工核对）/ retry_failed（表中未写入）
- 列表加载时拉一次全量失败项做行标记，tooltip 显示具体原因"
```

---

## 交付后的收尾（非任务，供执行者提醒用户）

1. **重启 Flask** —— 后端改动与建表迁移需重启生效。**不得自行重启**，提请注意即可。
2. **`cd frontend && npm run build`** —— Tailscale 用户只能访问 :5001，不 build 看不到前端改动。
3. **`test_fb_asset_model.py` 的 24 个既有失败**（规格 §12.4）：4 位密码 `t123` vs 注册要求 ≥6 位。与本计划无关，应作为独立 bug 修复。
