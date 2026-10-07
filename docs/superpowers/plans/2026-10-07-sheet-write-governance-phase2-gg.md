# 写表失败统一治理（二期：GG 平台接入）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 GG 平台的 9 个写表点（5 个「我的看板」静默点 + 4 个充值点）接入一期的统一治理机制，使其最终失败产生带原因的持久记录、可提示、可重试；**不做业务回滚**（GG 侧全是镜像类）。

**Architecture:** 给 `py/sheet_write.py` 加一个**加法式**的 `run_write_many`（一次后台写表、登记 N 行日志），用它和既有的 `run_write` 把 GG 的 9 个点从「各写各的 `_on_fail`」收敛到统一入口；新增 `gg_my_dashboard` / `gg_recharge` 两个 target（均从 DB 重建、均不注册 `rollback`）；前端复用一期 TT 的标记与轮询实现。

**Tech Stack:** Python 3.11 / Flask / SQLite(WAL) / waitress / pytest；前端 Vue 3 `<script setup>` + Element Plus。

**规格来源：** `docs/superpowers/specs/2026-10-07-sheet-write-governance-phase2-gg-design.md`（下称「规格」）
**一期（已完成、已在 master）：** `docs/superpowers/specs/2026-10-06-sheet-write-failure-governance-design.md`

## Global Constraints

- 写表**保持异步**；业务端点的响应不得因写表而阻塞或失败。
- 提示**只在最终结果产生时**发出 —— `failed`（首次失败、30s 重试在途）**不得**触发任何用户可见提示或列表标记。
- 状态值固定 6 个，不得增删：`pending` / `failed` / `synced` / `retry_failed` / `rolled_back` / `rollback_abandoned`。**本期不会产生后两个**（无回滚）。
- **本期所有 target 一律不注册 `rollback`** —— GG 侧 10 个点全是「主数据镜像」（规格 §2.2），最终失败落 `retry_failed`。
- `target` 一律用**稳定英文 token**：`gg_my_dashboard` / `gg_recharge`。
- **后台线程内禁止使用请求线程的 SQLite 连接**，一律 `database.get_db()` 新建；**禁止**在请求线程预先 `build_service()` 再传进线程（httplib2 非线程安全）。
- `run_write` 的签名与实现**一字不改**（一期已审）——`run_write_many` 是纯增量。
- `recharge_records.sheets_synced` / `sheets_error` 两列**保留不删、不再写入**；不重建表。
- `err(msg, code)` 才是正确写法；**禁止** `return err(msg), code`（`err()` 返回 `(Response, code)` 元组）。
- 本仓库常有并行会话在改文件：**禁止 `git add -A`**，一律 `git add <显式路径>`。
- 不启动/重启任何**常驻服务进程**；`npm run build` 是一次性构建，允许。

### 测试红线（一期踩过三次的坑，本期必须避开）

1. **`time.sleep` 陷阱**：测试若用 `monkeypatch.setattr("time.sleep", ...)` 跳过 30s 重试，**打的是全局 `time.sleep`**，会连测试自己的轮询 sleep 一起打成空转 —— 主线程不再 yield GIL，后台线程拿不到执行机会，断言早于回调落地，测试**恒定失败**。正确写法：模块顶部 `from time import sleep as _poll_sleep`（早于任何 patch 抓取），轮询一律用 `_poll_sleep(...)`。
2. **断言必须具判别力**：写完每个测试后，问自己「如果被测代码坏了，这条断言会不会失败？」—— 不会就是无效守卫。一期因此改掉了两条恒真断言。**实施时请务必临时破坏被测代码验证一次，并报告观察到的失败断言。**
3. **别把期望值写错**：Step 里的 `Expected: N passed` 是累计值，跑出来不一致要查清楚再报告。

---

## File Structure

| 文件 | 动作 | 职责 |
|---|---|---|
| `py/sheet_write.py` | 修改 | 新增 `run_write_many`（加法，`run_write` 不动） |
| `py/routes/gg_dashboard_sheet.py` | **新建** | `gg_my_dashboard` target：直写函数 + rebuild + 注册 |
| `py/routes/gg_recharge_sheet.py` | **新建** | `gg_recharge` target：直写函数 + rebuild + 注册 |
| `py/main.py` | 修改 | 9 个点位改走统一入口；3 个接口补轮询所需的 key |
| `py/tests/test_sheet_write.py` | 修改 | `run_write_many` 用例 |
| `py/tests/test_gg_sheet_write.py` | **新建** | 两个 target 的用例 + 9 个点位的接线用例 |
| `frontend/src/views/AdsAccountPanel.vue` | 修改 | 写表列 + 6 个轮询触发点 |
| `frontend/src/components/AccountDetailModal.vue` | 修改 | 充值 tooltip 改读新接口 |

> **为什么两个 target 各建一个文件**：`main.py` 已近 11400 行，且本仓库正在「逐步拆 Blueprint」；把 target 的直写函数与 rebuild 放进独立文件，既避免继续膨胀 `main.py`，也让「重建逻辑」有单一归属。两个文件都只依赖 `database` / `google_sheets_service` / `sheet_write`，不 import `main`（`_GOOGLE_SHEETS_CONFIG` 在函数内延迟 import，与一期 `tt_accounts_routes.py` 的写法一致）。

---

### Task 1: `run_write_many` —— 一次写表、N 行日志

**Files:**
- Modify: `py/sheet_write.py`（在 `run_write` 之后追加）
- Test: `py/tests/test_sheet_write.py`

**Interfaces:**
- Consumes: `record_pending` / `settle` / `_apply_final` / `_inflight` / `TERMINAL`（均已存在）
- Produces: `run_write_many(db, *, user_id, platform, target, business_keys, sync_fn, payload=None, snapshot=None) -> None`

- [ ] **Step 1: 写失败测试**

追加到 `py/tests/test_sheet_write.py`：

```python
def test_run_write_many_registers_one_row_per_key(client):
    """N 个 business_key ⇒ N 行日志，且都从 pending 起。（此时还没起线程，故仍为 pending）"""
    import sheet_write
    db = database.get_db()
    sheet_write.run_write_many(
        db, user_id=1, platform="gg", target="_t_many",
        business_keys=["a1", "a2", "a3"], sync_fn=lambda: None)
    # 立即读：登记是同步的，线程结果尚未落
    rows = db.execute(
        "SELECT business_key, status FROM sheet_write_log "
        "WHERE user_id=1 AND target='_t_many' ORDER BY business_key").fetchall()
    db.close()
    assert [r["business_key"] for r in rows] == ["a1", "a2", "a3"]
    assert all(r["status"] in ("pending", "synced") for r in rows), \
        "登记后应至少是 pending（线程可能已抢先落 synced，但绝不该是别的）"


def test_run_write_many_settles_all_keys_on_success(client):
    """一次后台写表成功后，N 行**全部**落 synced。"""
    import sheet_write
    from time import sleep as _poll_sleep
    calls = []
    sheet_write.run_write_many(
        database.get_db(), user_id=2, platform="gg", target="_t_many_ok",
        business_keys=["b1", "b2"], sync_fn=lambda: calls.append(1))

    db = database.get_db()
    for _ in range(200):
        rows = db.execute(
            "SELECT status FROM sheet_write_log WHERE user_id=2 AND target='_t_many_ok'").fetchall()
        if len(rows) == 2 and all(r["status"] == "synced" for r in rows):
            break
        _poll_sleep(0.02)
    db.close()
    assert len(calls) == 1, "sync_fn 只应执行一次（一个后台线程），不是每 key 一次"
    assert [r["status"] for r in rows] == ["synced", "synced"]


def test_run_write_many_settles_all_keys_on_final_failure(client, monkeypatch):
    """最终失败时 N 行全部落 retry_failed，且都带原因。"""
    import sheet_write
    import time as _time
    monkeypatch.setattr(_time, "sleep", lambda _s: None)      # 跳过 30s
    from time import sleep as _poll_sleep                      # 真 sleep 轮询

    def _boom():
        raise RuntimeError("Sheets 挂了")

    sheet_write.run_write_many(
        database.get_db(), user_id=3, platform="gg", target="_t_many_fail",
        business_keys=["c1", "c2", "c3"], sync_fn=_boom)

    db = database.get_db()
    for _ in range(300):
        rows = db.execute(
            "SELECT status, error_msg FROM sheet_write_log "
            "WHERE user_id=3 AND target='_t_many_fail'").fetchall()
        if len(rows) == 3 and all(r["status"] == "retry_failed" for r in rows):
            break
        _poll_sleep(0.02)
    db.close()
    assert len(rows) == 3
    assert {r["status"] for r in rows} == {"retry_failed"}, \
        f"应全部终态失败，实际 {[r['status'] for r in rows]}"
    assert all("Sheets 挂了" in (r["error_msg"] or "") for r in rows)


def test_run_write_many_marks_all_keys_inflight(client, monkeypatch):
    """N 个 key 都要进 _inflight —— 否则 sweep_stale 会把在途的行误收敛，
    重试闸门放行后起第二个写手（一期修复轮 2 的教训）。"""
    import sheet_write
    import time as _time
    seen = {}

    def _capture(_s):
        with sheet_write._inflight_lock:
            seen["keys"] = set(sheet_write._inflight)

    monkeypatch.setattr(_time, "sleep", _capture)   # 30s 重试前会被调用
    from time import sleep as _poll_sleep

    def _boom():
        raise RuntimeError("挂")

    sheet_write.run_write_many(
        database.get_db(), user_id=4, platform="gg", target="_t_many_inflight",
        business_keys=["d1", "d2"], sync_fn=_boom)

    for _ in range(200):
        if seen:
            break
        _poll_sleep(0.01)
    assert seen.get("keys", set()) >= {(4, "_t_many_inflight", "d1"),
                                       (4, "_t_many_inflight", "d2")}


def test_run_write_many_empty_keys_is_noop(client):
    """空列表不登记、不起线程。"""
    import sheet_write
    calls = []
    sheet_write.run_write_many(
        database.get_db(), user_id=5, platform="gg", target="_t_many_empty",
        business_keys=[], sync_fn=lambda: calls.append(1))
    db = database.get_db()
    n = db.execute("SELECT COUNT(*) FROM sheet_write_log WHERE user_id=5").fetchone()[0]
    db.close()
    assert n == 0
    assert calls == []
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd py && python -m pytest tests/test_sheet_write.py -v -k many`
Expected: FAIL —— `AttributeError: module 'sheet_write' has no attribute 'run_write_many'`

- [ ] **Step 3: 实现 `run_write_many`**

在 `py/sheet_write.py` 的 `run_write` 之后追加（**`run_write` 本身一字不改**）：

```python
def run_write_many(db, *, user_id, platform, target, business_keys,
                   sync_fn, payload=None, snapshot=None):
    """一次后台写表，登记 N 行日志（每个 business_key 一行），结果统一落。

    用于「一次操作影响 N 个账户」的场景（批量改状态、sync-from-sheet 回写）。

    为什么不是逐键调用 run_write：那会变成 **N 个后台线程 + N 次并行 Sheets API
    突发**（原实现是一个线程串行 N 次调用），被取消的还要各自睡 30s 重试。
    为什么不是只登记一行：行内标记就失去按账户定位的能力 —— 那正是本设计的意义。

    除「N 行日志 / N 个业务键」外，语义与 run_write 完全一致。绝不抛异常。
    """
    keys = list(business_keys)
    if not keys:
        return

    for bk in keys:
        try:
            record_pending(db, user_id=user_id, platform=platform, target=target,
                           business_key=bk, payload=payload, snapshot=snapshot)
        except Exception as e:
            # 登记失败不该阻断写表本身，但必须有痕迹
            log.error("写表任务登记失败 target=%s key=%s: %s", target, bk, e)

    inflight_keys = [(user_id, target, bk) for bk in keys]

    def _on_result(status, err_msg):
        import database
        _db = None
        try:
            _db = database.get_db()
            for bk in keys:
                row = _db.execute(
                    "SELECT * FROM sheet_write_log "
                    "WHERE user_id=? AND target=? AND business_key=?",
                    (user_id, target, bk)).fetchone()
                if row is None:
                    continue
                if status == "synced":
                    settle(_db, user_id=user_id, target=target, business_key=bk,
                           status="synced", error_msg="")
                elif status == "failed":
                    settle(_db, user_id=user_id, target=target, business_key=bk,
                           status="failed", error_msg=(err_msg or "")[:500])
                else:
                    _apply_final(_db, row, (err_msg or "")[:500])
        except Exception as e:
            log.error("写表状态落库失败 target=%s: %s", target, e)
        finally:
            if _db is not None:
                try:
                    _db.close()
                except Exception:
                    pass
            # 同 run_write：只在**终态**摘除在途登记（中间态 "failed" 时同一线程
            # 还会再试一次，摘了会让重试窗口失去保护）。
            if status in TERMINAL:
                with _inflight_lock:
                    for k in inflight_keys:
                        _inflight.discard(k)

    with _inflight_lock:
        for k in inflight_keys:
            _inflight.add(k)
    try:
        from main import _sync_sheets_background
        _sync_sheets_background(sync_fn, _on_result)
    except Exception as e:
        with _inflight_lock:
            for k in inflight_keys:
                _inflight.discard(k)
        log.error("写表后台任务启动失败 target=%s: %s", target, e)
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd py && python -m pytest tests/test_sheet_write.py -v`
Expected: 35 passed（一期收尾时是 30，本任务 +5）

- [ ] **Step 5: 验证断言具判别力（必做）**

临时把 `run_write_many` 的 `for bk in keys:` 循环改成只处理 `keys[0]`，跑 `-k many`，确认
`test_run_write_many_settles_all_keys_on_success` **失败**；然后改回。
把失败断言原文写进报告。

- [ ] **Step 6: 提交**

```bash
git add py/sheet_write.py py/tests/test_sheet_write.py
git commit -m "feat(sheet-write): 新增 run_write_many（一次写表、N 行日志）

批量点位（_sync_batch_dashboard / _sync_back_to_dashboard）是「一个后台任务
写 N 个账户」，而 run_write 是「一个任务一个 business_key」。逐键调用会变成
N 个线程 + N 次并行 API 突发；只登记一行又会让行标记失去按账户定位的能力。

故新增 run_write_many：登记 N 行、起**一个**后台线程、结果统一落到 N 行。
run_write 签名与实现一字不改（纯增量），一期已审代码零改动。"
```

---

### Task 2: `gg_my_dashboard` target 与 5 个「我的看板」点位接入

**Files:**
- Create: `py/routes/gg_dashboard_sheet.py`
- Modify: `py/main.py`（4762 附近 `_sync_dashboard`、4951 `_sync_unbind`、5023 `_sync_unbind_clear`、5243 `_sync_batch_dashboard`、5516 `_sync_back_to_dashboard`）
- Test: `py/tests/test_gg_sheet_write.py`

**Interfaces:**
- Consumes: `sheet_write.register_target` / `build_sync` / `run_write` / `run_write_many`（前三个一期已有，`run_write_many` 来自 Task 1）
- Produces:
  - 模块级注册：`sheet_write.register_target("gg_my_dashboard", rebuild=_gg_dashboard_rebuild)`
  - `_gg_dashboard_write(dash_uid, account_ids) -> None`（直写：读账户 → F 列写状态、H 列写解绑/空）
  - `_gg_dashboard_rebuild(user_id, business_key, payload) -> Callable[[], None]`

**关键约束 —— 保住既有行为（易错点）**

既有代码解析「写谁的看板」时**不一致**，`payload` 必须把该身份带过去，rebuild 才能复现：

| 现点位 | 解析方式 |
|---|---|
| 4766 `_sync_dashboard`（改状态） | `_get_my_dashboard_name(db, user_id)` —— **操作者** |
| 5236 `_sync_batch_dashboard`（批量） | `_get_my_dashboard_name(db, user_id)` —— **操作者** |
| 4946 `_sync_unbind`（删户） | `_get_my_dashboard_name(db, ac["owner_id"])` —— **账户 owner** |
| 5018 `_sync_unbind_clear`（恢复） | `_get_my_dashboard_name(db, ac["owner_id"])` —— **账户 owner** |
| 5516 `_sync_back_to_dashboard`（从表同步） | 沿用上方已解析的 `dashboard_name`（**实现时以现场代码为准**，见 Step 3） |

⇒ 本 task **不改变**这个既有差异（那是独立话题），只把它编码进 `payload={"dash_uid": <同现场解析出的 id>}`，让 rebuild 复现。

- [ ] **Step 1: 写失败测试**

新建 `py/tests/test_gg_sheet_write.py`：

```python
"""GG 平台写表点接入统一治理 —— 端到端测试。

守卫两件事：(1) 每次触发都登记 pending 并抓对 business_key；
(2) 最终失败落 retry_failed（GG 侧全是镜像类，**不得**出现 rolled_back）。
"""
import database
import sheet_write


def _gg_user(client, username, role="user"):
    client.post("/api/auth/register", json={"username": username, "password": "test123"})
    db = database.get_db()
    db.execute("UPDATE users SET role=?, platform='gg' WHERE username=?", (role, username))
    db.commit()
    uid = db.execute("SELECT id FROM users WHERE username=?", (username,)).fetchone()["id"]
    db.close()
    resp = client.post("/api/auth/login", json={"username": username, "password": "test123"})
    return {"Authorization": f"Bearer {resp.get_json().get('access_token', '')}"}, uid


def _setup_sheets(db):
    """配好全局表格 ID 与充值/看板 sheet 名，让各点位不提前 return。"""
    db.execute("INSERT OR REPLACE INTO tags (key, value) VALUES ('recharge_sheet_id', 'SHEET_X')")
    db.execute("INSERT OR REPLACE INTO tags (key, value) VALUES "
               "('sheet_mappings', '{\"my_dashboard\": \"我的看板\", \"recharge\": \"充值表\"}')")
    db.commit()


def _mk_account(db, uid, account_id, status_id=None):
    db.execute("INSERT INTO accounts (name, account_id, owner_id, status_id) VALUES (?,?,?,?)",
               (account_id, account_id, uid, status_id))
    db.commit()
    return db.execute("SELECT id FROM accounts WHERE account_id=?", (account_id,)).fetchone()["id"]


def _status_id(db, name):
    db.execute("INSERT OR IGNORE INTO account_statuses (name, platform) VALUES (?, 'gg')", (name,))
    db.commit()
    return db.execute("SELECT id FROM account_statuses WHERE name=? AND platform='gg'",
                      (name,)).fetchone()["id"]


def _row(db, uid, target, key):
    return db.execute("SELECT * FROM sheet_write_log WHERE user_id=? AND target=? "
                      "AND business_key=?", (uid, target, key)).fetchone()


def test_status_change_registers_dashboard_write(client, monkeypatch):
    """改状态 ⇒ 登记 gg_my_dashboard 的一条记录，business_key 是 account_id。"""
    import google_sheets_service as gs
    monkeypatch.setattr(gs, "build_service", lambda _p: object())
    monkeypatch.setattr(gs, "update_cell_by_account_id", lambda *a, **k: None)

    h, uid = _gg_user(client, "_gg_status")
    db = database.get_db()
    _setup_sheets(db)
    alive = _status_id(db, "存活")
    dead = _status_id(db, "死亡")
    aid = _mk_account(db, uid, "gg_adv_1", alive)
    acct_key = db.execute("SELECT account_id FROM accounts WHERE id=?", (aid,)).fetchone()["account_id"]
    db.close()

    resp = client.put(f"/api/accounts/{aid}", headers=h, json={"status_id": dead})
    assert resp.status_code == 200, resp.get_json()

    from time import sleep as _poll_sleep
    db = database.get_db()
    for _ in range(200):
        r = _row(db, uid, "gg_my_dashboard", acct_key)
        if r is not None and r["status"] in sheet_write.TERMINAL:
            break
        _poll_sleep(0.02)
    r = _row(db, uid, "gg_my_dashboard", acct_key)
    db.close()
    assert r is not None, "改状态必须登记一条 gg_my_dashboard"
    assert r["status"] == "synced"
    assert r["status"] not in ("rolled_back", "rollback_abandoned"), "GG 侧不得回滚"


def test_delete_and_restore_register_dashboard_write(client, monkeypatch):
    """删户与恢复各登记一条（H 列写「解绑」/ 清空）—— 这两个入口最容易漏接轮询。"""
    import google_sheets_service as gs
    monkeypatch.setattr(gs, "build_service", lambda _p: object())
    monkeypatch.setattr(gs, "update_cell_by_account_id", lambda *a, **k: None)

    h, uid = _gg_user(client, "_gg_del")
    db = database.get_db()
    _setup_sheets(db)
    aid = _mk_account(db, uid, "gg_adv_2", _status_id(db, "存活"))
    db.close()

    assert client.delete(f"/api/accounts/{aid}", headers=h).status_code == 200
    assert client.post(f"/api/accounts/{aid}/restore", headers=h).status_code == 200

    from time import sleep as _poll_sleep
    db = database.get_db()
    for _ in range(300):
        r = _row(db, uid, "gg_my_dashboard", "gg_adv_2")
        if r is not None and r["status"] in sheet_write.TERMINAL:
            break
        _poll_sleep(0.02)
    r = _row(db, uid, "gg_my_dashboard", "gg_adv_2")
    db.close()
    assert r is not None, "删户/恢复必须登记 gg_my_dashboard"


def test_dashboard_final_failure_lands_retry_failed_not_rolled_back(client, monkeypatch):
    """写表最终失败 ⇒ retry_failed（**不是** rolled_back）—— GG 侧零回滚的守卫。"""
    import google_sheets_service as gs
    import time as _time
    monkeypatch.setattr(_time, "sleep", lambda _s: None)
    monkeypatch.setattr(gs, "build_service", lambda _p: object())

    def _boom(*a, **k):
        raise RuntimeError("Sheets 配额超限")

    monkeypatch.setattr(gs, "update_cell_by_account_id", _boom)

    h, uid = _gg_user(client, "_gg_fail")
    db = database.get_db()
    _setup_sheets(db)
    alive = _status_id(db, "存活")
    dead = _status_id(db, "死亡")
    aid = _mk_account(db, uid, "gg_adv_3", alive)
    db.close()

    assert client.put(f"/api/accounts/{aid}", headers=h,
                      json={"status_id": dead}).status_code == 200

    from time import sleep as _poll_sleep
    db = database.get_db()
    for _ in range(300):
        r = _row(db, uid, "gg_my_dashboard", "gg_adv_3")
        if r is not None and r["status"] in sheet_write.TERMINAL:
            break
        _poll_sleep(0.02)
    r = _row(db, uid, "gg_my_dashboard", "gg_adv_3")
    cur = db.execute("SELECT status_id FROM accounts WHERE id=?", (aid,)).fetchone()["status_id"]
    db.close()

    assert r["status"] == "retry_failed", f"应落 retry_failed，实际 {r['status']}"
    assert "Sheets 配额超限" in r["error_msg"]
    assert cur == dead, "GG 侧是镜像类，**不得**回滚业务数据"


def test_dashboard_write_rebuilds_from_accounts(client, monkeypatch):
    """重建从 accounts 重算 F/H —— 删户态写「解绑」，非删户态写空。"""
    import google_sheets_service as gs
    writes = []
    monkeypatch.setattr(gs, "build_service", lambda _p: object())
    monkeypatch.setattr(gs, "update_cell_by_account_id",
                        lambda svc, sid, name, aid, val, col_index=5:
                        writes.append((aid, val, col_index)))

    h, uid = _gg_user(client, "_gg_rebuild")
    db = database.get_db()
    _setup_sheets(db)
    aid = _mk_account(db, uid, "gg_adv_4", _status_id(db, "存活"))
    db.execute("UPDATE accounts SET deleted_at=datetime('now','localtime') WHERE id=?", (aid,))
    db.commit()
    db.close()

    import sheet_write as sw
    sync_fn = sw.build_sync("gg_my_dashboard", uid, "gg_adv_4", {"dash_uid": uid})
    sync_fn()          # 直接执行（不在后台线程里，测试内联跑）

    assert ("gg_adv_4", "解绑", 7) in writes, f"H 列应写「解绑」，实际 {writes}"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd py && python -m pytest tests/test_gg_sheet_write.py -v`
Expected: FAIL —— `sheet_write_log` 里查不到 `gg_my_dashboard` 的记录（点位未接入）

- [ ] **Step 3: 创建 `py/routes/gg_dashboard_sheet.py`**

```python
"""GG「我的看板」写表目标。

设计见 docs/superpowers/specs/2026-10-07-sheet-write-governance-phase2-gg-design.md。

GG 侧全是「主数据镜像」：看板那一行是 accounts 行的投影，故**不注册 rollback**
（把系统回滚了镜像反而失真）。重建一律从 accounts 重算，与既有
`_sync_back_to_dashboard`（main.py:5516）的写法定全一致。
"""
import sheet_write

TARGET = "gg_my_dashboard"


def _gg_dashboard_write(dash_uid, account_ids):
    """直写：对每个 account_id，F 列写状态名、H 列写「解绑」/空。

    **在后台线程内执行** —— service 必须在这里 build（httplib2 非线程安全），
    DB 连接也必须现开（sqlite 连接不可跨线程）。
    """
    import database
    import google_sheets_service as gs
    # 延迟 import：这两个 helper 定义在 main.py，而 main 会 import 本模块（注册 target），
    # 顶层 import 会成环。GOOGLE_SHEETS_CONFIG 同理。
    from main import _GOOGLE_SHEETS_CONFIG, _get_sync_spreadsheet_id, _get_my_dashboard_name

    db = database.get_db()
    try:
        sheet_id = _get_sync_spreadsheet_id(db)
        dashboard_name = _get_my_dashboard_name(db, dash_uid)
        if not sheet_id or not dashboard_name:
            raise RuntimeError("未配置看板表格 ID 或工作表名，无法写我的看板")
        rows = db.execute(
            "SELECT a.account_id, a.deleted_at, st.name AS status_name "
            "FROM accounts a LEFT JOIN account_statuses st ON a.status_id = st.id "
            f"WHERE a.id IN ({','.join('?' for _ in account_ids)})",
            tuple(account_ids)).fetchall()
        payload = [(r["account_id"], r["status_name"] or "存活", r["deleted_at"] or "")
                   for r in rows]
    finally:
        db.close()

    if not payload:
        raise RuntimeError("找不到对应账户，无法重建看板行")

    service = gs.build_service(_GOOGLE_SHEETS_CONFIG["credentials_path"])
    for account_id, st, deleted in payload:
        # 备注列（F 列）：写状态；是否解绑（H 列）：已删除写「解绑」，未删除清空
        gs.update_cell_by_account_id(service, sheet_id, dashboard_name, account_id, st)
        gs.update_cell_by_account_id(service, sheet_id, dashboard_name, account_id,
                                     "解绑" if deleted else "", col_index=7)


def _gg_dashboard_rebuild(user_id, business_key, payload):
    """重试时重建同步函数。business_key = account_id；dash_uid 由 payload 带。

    dash_uid 必须在 payload 里：既有代码解析「写谁的看板」并不一致
    （改状态/批量用操作者，删户/恢复用账户 owner），本 target 不改变该差异，
    只把它编码进 payload 以便重建复现。
    """
    dash_uid = (payload or {}).get("dash_uid") or user_id

    def _sync():
        import database
        db = database.get_db()
        try:
            row = db.execute("SELECT id FROM accounts WHERE account_id=?",
                             (business_key,)).fetchone()
        finally:
            db.close()
        if row is None:
            raise RuntimeError(f"账户 {business_key} 不存在，无法重建看板行")
        _gg_dashboard_write(dash_uid, [row["id"]])

    return _sync


sheet_write.register_target(TARGET, rebuild=_gg_dashboard_rebuild)
```

> `_get_sync_spreadsheet_id` / `_get_my_dashboard_name` 定义在 `main.py`，而 `main` 会 import
> 本模块（注册 target）—— 故上面用**函数内延迟 import**，顶层 import 会成环。
> `_gg_dashboard_rebuild` 里的 `import database` 同理放在闭包内。

- [ ] **Step 4: 改 `py/main.py` 的 5 个点位**

每个点位做同一件事：**删掉原有的 `def _sync_xxx()` 与 `_on_fail`（或 lambda），改调统一入口**，并把 `payload` 按 Step 3 的表格带上 `dash_uid`。

**点位 1 — 改状态（约 4764-4784）**，把整段 `if new_status and old_status and ...:` 块替换为：

```python
        # 状态变更时写「我的看板」（独立于清账逻辑，所有状态变更都触发）
        if new_status and old_status and new_status != old_status["status_name"]:
            _acct_id = old_status["account_id"]
            _payload = {"dash_uid": user_id}
            if sheet_write.build_sync_safe("gg_my_dashboard", user_id, _acct_id, _payload):
                sheet_write.run_write(
                    db, user_id=user_id, platform="gg", target="gg_my_dashboard",
                    business_key=_acct_id,
                    sync_fn=sheet_write.build_sync("gg_my_dashboard", user_id, _acct_id, _payload),
                    payload=_payload)
```

> **`business_key` 用 `account_id`（文本），不是主键 `aid`** —— 重建时用它反查主键。
> `build_sync_safe` 返回 `None` 表示配置未就绪（表格 ID 或看板名缺失），此时整段跳过，
> 与既有 `if sheet_id and dashboard_name:` 的行为等价。

**点位 2 — 删户（约 4944-4955）**、**点位 3 — 恢复（约 5016-5027）**：

```python
        # 后台写「我的看板」H 列（解绑 / 清空）
        _acct_id = ac["account_id"]
        _payload = {"dash_uid": ac["owner_id"]}
        if sheet_write.build_sync_safe("gg_my_dashboard", user_id, _acct_id, _payload):
            sheet_write.run_write(
                db, user_id=user_id, platform="gg", target="gg_my_dashboard",
                business_key=_acct_id,
                sync_fn=sheet_write.build_sync("gg_my_dashboard", user_id, _acct_id, _payload),
                payload=_payload)
```

**点位 4 — 批量改状态（约 5235-5257）**、**点位 5 — 从表同步回写（约 5516-5532）**：

```python
            if _sync_back_rows:
                _keys = [r[0] for r in _sync_back_rows]
                _payload = {"dash_uid": user_id}
                if sheet_write.build_sync_safe("gg_my_dashboard", user_id, _keys[0], _payload):
                    sheet_write.run_write_many(
                        db, user_id=user_id, platform="gg", target="gg_my_dashboard",
                        business_keys=_keys,
                        sync_fn=sheet_write.build_sync("gg_my_dashboard", user_id, _keys[0], _payload),
                        payload=_payload)
```

> `_sync_back_rows` 的元素是 `(account_id, status_name, deleted_at)`；批量点位同理，各自用现成的 account_id 列表。**`dash_uid` 以现场代码解析出的身份为准**（点位 5 需先读现场确认）。

为了让调用点不必先判定「配置齐不齐」，在 `py/sheet_write.py` 追加一个小助手：

```python
def build_sync_safe(target, user_id, business_key, payload):
    """配置未就绪时返回 None 而不抛 —— 调用点用它短路（与既有 `if sheet_id and dashboard_name:` 等价）。

    与 build_sync 的区别：build_sync 对**未注册**的 target 抛 KeyError（契约的一部分，
    重试端点据此返回 400）；本函数只吞掉 rebuild 工厂内部的**配置缺失**异常。
    """
    try:
        return build_sync(target, user_id, business_key, payload)
    except KeyError:
        raise                      # 未注册是契约错误，不能吞
    except Exception as e:
        log.warning("写表目标重建失败 target=%s: %s", target, e)
        return None
```

- [ ] **Step 5: 在 `py/main.py` 顶部 import**

```python
import sheet_write
import routes.gg_dashboard_sheet  # noqa: F401  —— 注册 gg_my_dashboard target
```

（若 `main.py` 已有 `import routes.xxx` 的成组写法，并入该组。）

- [ ] **Step 6: 跑测试确认通过**

Run: `cd py && python -m pytest tests/test_gg_sheet_write.py -v`
Expected: 4 passed

- [ ] **Step 7: 回归**

Run: `cd py && python -m pytest tests/test_ad_reports.py tests/test_security_hardening.py tests/test_huguan_dashboard.py -q`
Expected: 全绿。**失败要当真** —— 这 3 个文件覆盖 GG 账户路径。

- [ ] **Step 8: 提交**

```bash
git add py/routes/gg_dashboard_sheet.py py/main.py py/sheet_write.py py/tests/test_gg_sheet_write.py
git commit -m "feat(gg): 5 个「我的看板」写表点接入统一治理（零回滚）

原实现全是 log.warning —— 写失败只有日志，用户看不到也重试不了。
现改走 sheet_write.run_write / run_write_many。

- 新增 gg_my_dashboard target：重建从 accounts 重算 F（状态）+ H（解绑），
  与既有 _sync_back_to_dashboard 的写法定全一致
- **不注册 rollback** —— GG 侧全是镜像类（看板行是 accounts 行的投影，
  回滚业务数据会让镜像失真）
- payload 带 dash_uid：既有代码解析「写谁的看板」不一致（改状态/批量用操作者，
  删户/恢复用账户 owner），本 task 不改变该差异，只编码进 payload 让重建复现
- 批量两点用 run_write_many：一个后台线程、N 行日志"
```

---

### Task 3: `gg_recharge` target 与 4 个充值点位接入

**Files:**
- Create: `py/routes/gg_recharge_sheet.py`
- Modify: `py/main.py`（4749-4762 清账、5218-5233 批量清账、5677-5697 单笔充值、5779-5796 批量充值）
- Test: `py/tests/test_gg_sheet_write.py`

**Interfaces:**
- Consumes: `sheet_write.register_target` / `run_write` / `run_write_many`
- Produces: `sheet_write.register_target("gg_recharge", rebuild=_gg_recharge_rebuild)`；`_gg_recharge_write(rids) -> None`

- [ ] **Step 1: 写失败测试**

追加到 `py/tests/test_gg_sheet_write.py`：

```python
def test_recharge_submit_registers_and_settles(client, monkeypatch):
    """单笔充值 ⇒ 登记 gg_recharge，business_key 是 recharge_records.id。"""
    import google_sheets_service as gs
    monkeypatch.setattr(gs, "build_service", lambda _p: object())
    monkeypatch.setattr(gs, "append_recharge", lambda *a, **k: None)

    h, uid = _gg_user(client, "_gg_recharge")
    db = database.get_db()
    _setup_sheets(db)
    _mk_account(db, uid, "gg_adv_r1", _status_id(db, "存活"))
    db.close()

    resp = client.post("/api/recharge/submit", headers=h,
                       json={"account_id": "gg_adv_r1", "amount": 100, "agent": "代理A"})
    assert resp.status_code == 200, resp.get_json()
    rid = resp.get_json()["id"]

    from time import sleep as _poll_sleep
    db = database.get_db()
    for _ in range(200):
        r = _row(db, uid, "gg_recharge", str(rid))
        if r is not None and r["status"] in sheet_write.TERMINAL:
            break
        _poll_sleep(0.02)
    r = _row(db, uid, "gg_recharge", str(rid))
    db.close()
    assert r is not None, "充值必须登记 gg_recharge"
    assert r["status"] == "synced"


def test_recharge_first_failure_is_intermediate_not_alerting(client, monkeypatch):
    """首次失败 ⇒ status='failed'（中间态），**不在 ATTENTION 里** ——
    修掉现值「首次失败就写 sheets_error 让前端立刻报警」与用户裁定的冲突。"""
    import google_sheets_service as gs
    import time as _time
    seen = {}

    def _capture(_s):
        db = database.get_db()
        rows = db.execute("SELECT status FROM sheet_write_log WHERE target='gg_recharge'").fetchall()
        seen["statuses"] = [r["status"] for r in rows]
        db.close()

    monkeypatch.setattr(_time, "sleep", _capture)
    monkeypatch.setattr(gs, "build_service", lambda _p: object())

    def _boom(*a, **k):
        raise RuntimeError("Sheets 挂了")

    monkeypatch.setattr(gs, "append_recharge", _boom)
    from time import sleep as _poll_sleep

    h, uid = _gg_user(client, "_gg_firstfail")
    db = database.get_db()
    _setup_sheets(db)
    _mk_account(db, uid, "gg_adv_r2", _status_id(db, "存活"))
    db.close()

    assert client.post("/api/recharge/submit", headers=h,
                       json={"account_id": "gg_adv_r2", "amount": 50, "agent": "A"}
                       ).status_code == 200

    for _ in range(200):
        if seen:
            break
        _poll_sleep(0.01)
    assert seen.get("statuses") == ["failed"], \
        f"首次失败应是中间态 failed，实际 {seen.get('statuses')}"
    assert "failed" not in sheet_write.ATTENTION, "中间态不得触发提示"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd py && python -m pytest tests/test_gg_sheet_write.py -v -k recharge`
Expected: FAIL —— 查不到 `gg_recharge` 记录

- [ ] **Step 3: 创建 `py/routes/gg_recharge_sheet.py`**

```python
"""GG「充值表」写表目标。

镜像类：写表前 recharge_records 行已落库，表只是副本，故**不注册 rollback**。
重建一律从 recharge_records 重算（与一期做表数据的 retry-sync 同思路）。
"""
import sheet_write

TARGET = "gg_recharge"


def _gg_recharge_write(rids):
    """直写：按 rids 从 recharge_records 重建追加行并写表。后台线程内执行。"""
    import database
    import google_sheets_service as gs
    from main import _GOOGLE_SHEETS_CONFIG, _get_sync_spreadsheet_id, _get_recharge_sheet_name

    db = database.get_db()
    try:
        sheet_id = _get_sync_spreadsheet_id(db)
        sheet_name = _get_recharge_sheet_name(db)
        if not sheet_id:
            raise RuntimeError("未配置充值表格 ID，无法写充值表")
        rows = db.execute(
            "SELECT r.account_id, r.amount, r.agent, r.operator, r.status, "
            "a.account_id AS acct_id FROM recharge_records r "
            "LEFT JOIN accounts a ON a.account_id = r.account_id "
            f"WHERE r.id IN ({','.join('?' for _ in rids)})",
            tuple(rids)).fetchall()
        payload = [{"account_id": r["account_id"], "amount": r["amount"],
                    "agent": r["agent"] or "", "operator": r["operator"] or "",
                    **({"status": r["status"]} if r["status"] else {})}
                   for r in rows]
    finally:
        db.close()

    if not payload:
        raise RuntimeError("找不到对应充值记录，无法重建待写行")

    service = gs.build_service(_GOOGLE_SHEETS_CONFIG["credentials_path"])
    gs.append_recharge(service, sheet_id, sheet_name, payload)


def _gg_recharge_rebuild(user_id, business_key, payload):
    """business_key = recharge_records.id（字符串）。"""
    def _sync():
        try:
            rid = int(business_key)
        except (TypeError, ValueError):
            raise RuntimeError(f"非法的充值记录 id: {business_key}")
        _gg_recharge_write([rid])

    return _sync


sheet_write.register_target(TARGET, rebuild=_gg_recharge_rebuild)
```

> `recharge_records` 的列名以现场代码为准（既有 `_on_fail` 用的是 `sheets_synced`/`sheets_error`，而插入语句用 `agent_id`）。**实现前先读一遍 `recharge_records` 的建表语句**（`py/database.py`），确认 `agent` / `operator` / `status` 三列的确切名字与类型，必要时调整上面 SELECT。

- [ ] **Step 4: 改 `py/main.py` 的 4 个充值点位**

**点位 A — 单笔清账（4749-4762）、点位 B — 单笔充值（5677-5697）** 各处替换为：

```python
                if sheet_id:
                    _payload = {"kind": "single"}
                    sheet_write.run_write(
                        db, user_id=user_id, platform="gg", target="gg_recharge",
                        business_key=str(clear_record_id),   # 单笔充值处用 str(record_id)
                        sync_fn=sheet_write.build_sync(
                            "gg_recharge", user_id, str(clear_record_id), _payload),
                        payload=_payload)
```

**点位 C — 批量清账（5218-5233）、点位 D — 批量充值（5779-5796）** 替换为：

```python
                if sheet_id:
                    _keys = [str(rid) for rid in _rids]   # 批量充值处用 _ids
                    _payload = {"kind": "batch"}
                    sheet_write.run_write_many(
                        db, user_id=user_id, platform="gg", target="gg_recharge",
                        business_keys=_keys,
                        sync_fn=sheet_write.build_sync(
                            "gg_recharge", user_id, _keys[0], _payload),
                        payload=_payload)
```

**四个 `_on_fail` 全部删除** —— 状态由统一机制落 `sheet_write_log`。
`recharge_records.sheets_synced` / `sheets_error` 两列**保留但不再写入**。

- [ ] **Step 5: 跑测试确认通过**

Run: `cd py && python -m pytest tests/test_gg_sheet_write.py -v`
Expected: 6 passed

- [ ] **Step 6: 回归（含既有充值重试用例）**

Run: `cd py && python -m pytest tests/test_tt_accounts.py tests/test_security_hardening.py -q`
Expected: 全绿

- [ ] **Step 7: 旧 `retry-sheets` 改为转调统一入口（规格 §5.3）**

`POST /api/recharge/<int:rid>/retry-sheets`（约 `main.py:5883`）现在是**同步**在请求线程里重放。
改造后重试统一走 `POST /api/sheet-write/retry`（异步），该端点改为**薄转调**：

```python
@app.route("/api/recharge/<int:rid>/retry-sheets", methods=["POST"])
@jwt_required()
def recharge_retry_sheets(rid):
    """旧入口，改为转调统一写表重试（规格 §5.3）。

    **语义已变**：返回 200 只代表「已提交到后台」，不再代表写入成功 ——
    旧语义（同步等 Sheets）正是会阻塞请求的那种形态。
    保留本端点而非删除：它有既有的权限守卫用例
    `test_recharge_retry_sheets_owner_guard`（py/tests/test_tt_accounts.py:617），
    删除会连带废掉该守卫；且能让未刷新的旧前端页面继续可用。
    """
    db = get_db()
    user_id = int(get_jwt_identity())
    # 权限守卫照旧：只有记录创建者或跨用户角色可重试
    row = db.execute("SELECT created_by FROM recharge_records WHERE id=?", (rid,)).fetchone()
    if not row:
        db.close()
        return jsonify({"success": False, "error": "充值记录不存在"}), 404
    user = db.execute("SELECT role FROM users WHERE id=?", (user_id,)).fetchone()
    if row["created_by"] != user_id and (not user or user["role"] not in CROSS_USER_ROLES):
        db.close()
        return jsonify({"success": False, "error": "无权限"}), 403

    _payload = {"kind": "retry"}
    sheet_write.run_write(
        db, user_id=user_id, platform="gg", target="gg_recharge",
        business_key=str(rid),
        sync_fn=sheet_write.build_sync("gg_recharge", user_id, str(rid), _payload),
        payload=_payload)
    db.close()
    return jsonify({"success": True, "message": "已重新提交，请稍后查看结果"})
```

> 权限守卫的实现以现场代码为准 —— **不要放宽它**。本步只把「同步重放」换成「提交到统一入口」，
> 守卫逻辑逐字保留。既有用例 `test_recharge_retry_sheets_owner_guard` 必须仍然通过
> （它断言的是 403，与新实现无关，但**跑一遍确认**）。

- [ ] **Step 8: 提交**

```bash
git add py/routes/gg_recharge_sheet.py py/main.py py/tests/test_gg_sheet_write.py
git commit -m "feat(gg): 4 个充值写表点接入统一治理，退场 sheets_synced/sheets_error

原 _on_fail 只有两分支：failed（首败、30s 重试在途）与 retry_failed 落进同一个
else ⇒ 首次失败就写 sheets_error，前端立刻报 ⚠️ —— 与用户「只在最终结果提示」
的裁定冲突。接统一机制后自然修正。

- 新增 gg_recharge target：重建从 recharge_records 重算
- 不注册 rollback（镜像类：写表前记录已落库）
- recharge_records.sheets_synced / sheets_error 保留不删、不再写入（可回退读）"
```

---

### Task 4: 三个接口补「轮询所需的 key」

**Files:**
- Modify: `py/main.py`（`accounts_update` 的响应、`accounts_batch_update` 的响应、`recharge_batch_submit` 的响应、`accounts_sync_from_sheet` 的响应）
- Test: `py/tests/test_gg_sheet_write.py`

**Interfaces:**
- Produces: 四个接口的响应体新增字段 —— `clear_recharge_id`（单）/ `clear_recharge_ids`（批量）/ `recharge_ids` / `affected_account_ids`。字段名固定，前端按此读取。

**为什么必须做**（规格 §6.4）：前端拿不到这些 key 就无法对 `gg_recharge` / `gg_my_dashboard` 轮询 ⇒ 那条写表失败只有持久标记、没有即时提示 —— 半个需求落不了地。

- [ ] **Step 1: 写失败测试**

追加到 `py/tests/test_gg_sheet_write.py`：

```python
def test_accounts_update_returns_clear_recharge_id(client, monkeypatch):
    """改状态触发自动清账时，响应必须带上该 recharge_records.id —— 前端靠它轮询。"""
    import google_sheets_service as gs
    monkeypatch.setattr(gs, "build_service", lambda _p: object())
    monkeypatch.setattr(gs, "append_recharge", lambda *a, **k: None)
    monkeypatch.setattr(gs, "update_cell_by_account_id", lambda *a, **k: None)

    h, uid = _gg_user(client, "_gg_key1")
    db = database.get_db()
    _setup_sheets(db)
    alive = _status_id(db, "存活")
    dead = _status_id(db, "死亡")
    aid = _mk_account(db, uid, "gg_adv_k1", alive)
    # 清账只在「该户有未清充值」时触发
    db.execute("INSERT INTO recharge_records (account_id, amount, created_by) "
               "VALUES ('gg_adv_k1', 10, ?)", (uid,))
    db.commit()
    db.close()

    resp = client.put(f"/api/accounts/{aid}", headers=h, json={"status_id": dead})
    assert resp.status_code == 200
    body = resp.get_json()
    assert "clear_recharge_id" in body, \
        f"响应缺 clear_recharge_id（前端无从对 gg_recharge 轮询）：{body}"


def test_recharge_batch_submit_returns_ids(client, monkeypatch):
    """批量充值必须回传本次产生的全部 id。"""
    import google_sheets_service as gs
    monkeypatch.setattr(gs, "build_service", lambda _p: object())
    monkeypatch.setattr(gs, "append_recharge", lambda *a, **k: None)

    h, uid = _gg_user(client, "_gg_key2")
    db = database.get_db()
    _setup_sheets(db)
    _mk_account(db, uid, "gg_adv_k2", _status_id(db, "存活"))
    db.close()

    resp = client.post("/api/recharge/batch-submit", headers=h, json={"rows": [
        {"account_id": "gg_adv_k2", "amount": 10, "agent": "A"},
        {"account_id": "gg_adv_k2", "amount": 20, "agent": "A"},
    ]})
    assert resp.status_code == 200, resp.get_json()
    body = resp.get_json()
    assert isinstance(body.get("recharge_ids"), list) and len(body["recharge_ids"]) == 2, \
        f"响应缺 recharge_ids 或数量不对：{body}"


def test_sync_from_sheet_returns_affected_account_ids(client, monkeypatch):
    """从表同步的回写腿涉及哪些账户，必须回传（前端靠它轮询看板写表）。

    构造：把 `gs.read_sheet_values` 替成一份最小表格 —— 表头行 + 一行
    「运营列 = 当前用户 display_name」（门禁要求运营列匹配当前用户）。
    这样写入腿会匹配到该账户，account_id 应出现在 affected_account_ids 里。
    """
    import google_sheets_service as gs
    monkeypatch.setattr(gs, "build_service", lambda _p: object())
    monkeypatch.setattr(gs, "update_cell_by_account_id", lambda *a, **k: None)
    monkeypatch.setattr(gs, "read_sheet_values", lambda svc, sid, name, rng: [
        ["运营", "账户ID", "所属渠道", "国家", "时区", "备注", "是否封户", "是否解绑"],
        ["_gg_sync", "gg_adv_s1", "", "", "", "", "", ""],
    ])

    h, uid = _gg_user(client, "_gg_sync")
    db = database.get_db()
    _setup_sheets(db)
    db.execute("UPDATE users SET display_name='_gg_sync' WHERE id=?", (uid,))
    _mk_account(db, uid, "gg_adv_s1", _status_id(db, "存活"))
    db.commit()
    db.close()

    resp = client.post("/api/accounts/sync-from-sheet", headers=h, json={"dry_run": False})
    assert resp.status_code == 200, resp.get_json()
    body = resp.get_json()
    assert "affected_account_ids" in body, f"响应缺 affected_account_ids：{body}"
    assert "gg_adv_s1" in body["affected_account_ids"], \
        f"回写腿涉及的账户应被回传：{body}"
```

> **上面这份表格构造是按「GG 我的看板」的既有列布局（A=运营、B=账户ID…）推的**。
> 实现时**先读一遍 `accounts_sync_from_sheet` 的解析代码**核对列下标与门禁条件，
> 不符则以现场为准调整构造 —— 但**必须覆盖非空分支**（断言 `affected_account_ids`
> 里真的含有那个 account_id），不许退化成「只断言键存在」那种不具判别力的写法。

- [ ] **Step 2: 跑测试确认失败**

Run: `cd py && python -m pytest tests/test_gg_sheet_write.py -v -k key or ids`
Expected: FAIL —— 响应里没有这些字段

- [ ] **Step 3: 改四个接口的响应体**

`accounts_update`（响应构造在 `main.py:4790` 附近）—— 把清账时已知的 `clear_record_id` 带出去：

```python
        resp = {"success": True}
        if recharge_note:
            resp["recharge_note"] = recharge_note
        # 清账记录的 id：前端靠它对 gg_recharge 轮询（否则写表失败只有标记、没有即时提示）
        if clear_record_id:
            resp["clear_recharge_id"] = clear_record_id
        return jsonify(resp)
```

> `clear_record_id` 需在外层作用域初始化为 `None`（该分支可能不执行），实现时确认。

`accounts_batch_update`（`:5258`）→ `{"success": True, "updated": len(ids), "clear_recharge_ids": _rids or []}`（`_rids` 在清账分支内定义，需提到外层并初始化 `[]`）。

`recharge_batch_submit`（`:5798`）→ 增加 `"recharge_ids": list(inserted_ids)`。

`accounts_sync_from_sheet`（`:5536` 附近的成功响应）→ 增加 `"affected_account_ids": [...]`（本次回写腿涉及的 account_id 列表）。

- [ ] **Step 4: 跑测试确认通过**

Run: `cd py && python -m pytest tests/test_gg_sheet_write.py -v`
Expected: 8–9 passed（视 sync-from-sheet 那条的实现方式）

- [ ] **Step 5: 提交**

```bash
git add py/main.py py/tests/test_gg_sheet_write.py
git commit -m "feat(gg): 四个接口回传轮询所需的 key

前端拿不到这些 key 就无法对 gg_recharge / gg_my_dashboard 轮询 —— 那条写表
失败就只有持久标记、没有即时提示，半个需求落不了地。

- PUT /api/accounts/<aid>      新增 clear_recharge_id
- POST /api/accounts/batch-update 新增 clear_recharge_ids
- POST /api/recharge/batch-submit 新增 recharge_ids
- POST /api/accounts/sync-from-sheet 新增 affected_account_ids"
```

---

### Task 5: 前端 —— 充值记录改用统一接口

**Files:**
- Modify: `frontend/src/components/AccountDetailModal.vue`
- Create: `frontend/src/api/sheetWrite.js`（若一期已在主目录有该文件，本分支基于旧基点则需新建；实现时先确认）

**Interfaces:**
- Consumes: `GET /api/sheet-write/status?platform=gg`、`POST /api/sheet-write/retry`
- Produces: `sheetWriteApi.status({platform, businessKey})` / `sheetWriteApi.retry({platform, target, businessKey})`

- [ ] **Step 1: 先调 `/frontend-design`**

本任务**不新增视觉元素**（沿用既有 ⚠️/✅ 与 tooltip，只换数据来源），但**触达了用户可见交互**。按项目规矩：**若确认只是换数据源、视觉一字不变，可在报告里说明并跳过**；若发现需要新的视觉表达（例如「已自动撤销」态在这个弹窗里也要出现），则必须先调 `/frontend-design`。

- [ ] **Step 2: 抽出共用的三态语汇模块**

新建 `frontend/src/utils/sheetWriteUi.js`，把一期 `TtAccountPanel.vue` 里的三态语汇与文案
**原样搬过来**（`SHEET_WRITE_UI` / `SHEET_WRITE_TOAST` / `sheetWriteMark` / `sheetWriteTone` /
`sheetWriteHint`），并让 `TtAccountPanel.vue` 改为从该模块 import（**全仓只能有一份文案源**）。

> 这是本次唯一的「搬动既有代码」动作。必要性：Task 5 与 Task 6 都要用这套语汇，
> 各写一份必然漂移 —— 而「三种终态文案各自不同」是本功能的需求之一。
> 搬迁后 `TtAccountPanel.vue` 的行为必须**逐字不变**，靠它既有的用例回归。

- [ ] **Step 3: 新建/确认 API 封装**

`frontend/src/api/sheetWrite.js`（与一期 TT 那份同形）：

```js
/** 写表失败治理（跨平台） */
import client from './client'

export const sheetWriteApi = {
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

- [ ] **Step 4: 改 `AccountDetailModal.vue`**

现状（`:50-57`）：`row.sheets_synced === 0` → ⚠️（tooltip = `row.sheets_error || '未同步到表格'`）+ 点击 `retryRechargeSheets(row)`。

改为：

- 挂载/刷新时拉一次 `sheetWriteApi.status({ platform: 'gg' })`，按 `String(row.id)` 索引成 `sheetWriteFailures`
- 单元格改为：`sheetWriteFailures[String(row.id)]` 存在 → 复用一期的三态语汇（`sheetWriteMark/Tone/Hint`）；否则 ✅
- 点击 → `sheetWriteApi.retry({ platform: 'gg', target: f.target, businessKey: String(row.id) })`
- **删除对 `sheets_synced` / `sheets_error` 的读取**（这两列不再写入）

> 三态与文案从一期 `TtAccountPanel.vue` 抄同一份实现（`SHEET_WRITE_UI` / `SHEET_WRITE_TOAST` / `sheetWriteHint`）——**不要各写一份**；若嫌重复可抽到 `frontend/src/utils/sheetWriteUi.js`，两条路都行，但**全仓只能有一份文案源**。

- [ ] **Step 5: 构建验证**

Run: `cd frontend && npm run build`
Expected: 构建成功

- [ ] **Step 6: 提交**

```bash
git add frontend/src/api/sheetWrite.js frontend/src/components/AccountDetailModal.vue frontend/src/utils/sheetWriteUi.js frontend/src/views/tt/TtAccountPanel.vue
git commit -m "feat(gg): 充值记录写表状态改读统一接口

原读 recharge_records.sheets_synced/sheets_error —— 那两列只有两分支，
首次失败（30s 重试在途）就置位，前端立刻报 ⚠️，与「只在最终结果提示」
的裁定冲突。改读 /api/sheet-write/status，只有终态才显示标记。

三态语汇与文案从一期 TtAccountPanel 抽出共用，全仓一份文案源。"
```

---

### Task 6: 前端 —— GG 账户表写表列 + 6 个轮询触发点

**Files:**
- Modify: `frontend/src/views/AdsAccountPanel.vue`
- Test: 无自动化测试（前端）；靠 `npm run build` + 人工验证

**Interfaces:**
- Consumes: `sheetWriteApi`（Task 5 建立）、四个接口的新字段（Task 4）

- [ ] **Step 1: 加「写表」列**

**逐字复用一期 TT 账户表那套**（`TtAccountPanel.vue` 里已确认的视觉方案）：

- 位置：**紧跟「账户 ID」列**
- `width="54"`、`align="center"`
- 三态语汇：`retry_failed` ⚠️ warning / `rolled_back` ↩️ info / `rollback_abandoned` ⛔ danger
- tooltip = `sheetWriteHint(item)`；点击 = 重试；无记录渲染 ✅（`#16a34a`）
- 行 key 是**账户的 `account_id`**（不是主键 id）
- 按钮必须 `@click.stop`

> 本表也有按分组交替的行底色 —— 与 TT 一样，四个标记都不依赖底色，**不要为底色做任何补偿**，也**不要改行级样式**。

- [ ] **Step 2: 接 6 个轮询触发点（本 task 的承重部分）**

用户要的是「**即时提示 + 持久标记**」。持久标记由列表加载拉一次 `/api/sheet-write/status?platform=gg` 得到；**即时提示必须在每次触发写表的操作之后主动轮询**。漏一个入口，该入口就退化成「只有标记」。

| 触发动作 | 轮询的 business_key | key 来源 |
|---|---|---|
| 改状态 | 该 `account_id` + 响应里的 `clear_recharge_id` | 行数据 + Task 4 的新字段 |
| **删户** | 该 `account_id` | 行数据 |
| **恢复** | 该 `account_id` | 行数据 |
| 批量改状态 | 本批全部 `account_id` + 响应里的 `clear_recharge_ids` | 选中行 + Task 4 |
| **从表同步** | 响应里的 `affected_account_ids` | Task 4 |
| 单笔/批量充值 | 响应里的 `id` / `recharge_ids` | Task 4 |

**实现要求**（照抄一期 `TtAccountPanel.vue` 的 `pollSheetWrite`）：

1. 轮询函数从一期 TT 那份**照搬**，含它**按 business_key 独立计时**的 `Map` —— 一期修复轮 1 已证明共用单个 timer 会让批量场景只有最后一个账户保留轮询。
2. `target` 取自 `/status` 返回的 `item.target`（不要在前端硬编码）。
3. 轮询上限用一期的 `SHEET_WRITE_POLL_MAX`（~42s，覆盖 30s 重试窗口）。
4. 轮询失败/超限**静默退出**，靠持久标记兜底。
5. `onUnmounted` 清空整个 Map。

- [ ] **Step 3: 构建验证**

Run: `cd frontend && npm run build`
Expected: 构建成功

- [ ] **Step 4: 人工验证清单（写进报告，交给用户执行）**

`npm run build` 只证明能编译，**证明不了运行时行为**。报告里必须列出下面这份清单，请用户在真实页面逐条走：

1. 改一个账户的状态 → 应看到终态提示（或标记）
2. **删一个账户** → 应有轮询提示
3. **恢复一个账户** → 应有轮询提示
4. **批量改 3 个以上账户** → **每个**都要有提示（这是单计时器缺陷的唯一真实检出口）
5. 从表同步 → 应有提示
6. 单笔充值 / 批量充值 → 各有提示

- [ ] **Step 5: 提交**

```bash
git add frontend/src/views/AdsAccountPanel.vue
git commit -m "feat(gg): 账户表写表列 + 6 个轮询触发点

列与语汇逐字复用一期 TT 方案（同一位置、同一宽度、同一三态），
两张表并列出现时跨平台一致。

轮询触发点逐个接全（改状态/删户/恢复/批量/从表同步/充值）——
漏一个那个入口就只有持久标记、没有即时提示，而用户要的是两者都要。
按 business_key 独立计时，照搬一期修复轮 1 的 Map 写法。"
```

---

## 交付后的收尾（非任务，供执行者提醒用户）

1. **合并回 master 前先跑全量**：`cd py && python -m pytest tests/ -q`
2. **合并后**：在主目录 `git merge feat/sheet-write-gg` → `cd frontend && npm run build` → **提醒用户重启 Flask**
3. **人工验证 Task 6 Step 4 的 6 条清单** —— 前端运行时契约 `npm run build` 证明不了
