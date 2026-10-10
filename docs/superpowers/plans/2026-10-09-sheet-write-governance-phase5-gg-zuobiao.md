# 写表失败统一治理（五期：GG 做表线接入）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 GG 做表线（「做表数据」页写 Google 表格）的 2 个写点接入统一治理（新增 `gg_zuobiao` 一个 target），使失败产生**持久**记录、可查、可逐条重试；顺带让两个既有缺陷**由构造消失**。

**Architecture:** 新建 `py/routes/gg_zuobiao_target.py` 注册 `gg_zuobiao` target（rebuild 从做表数据表重算，逻辑从现存重试端点搬进来）；两个写点改走 `sheet_write.run_write`；前端做表页换成统一的失败汇总区 + 逐条重试；两个专属端点退役；`sheets_sync_log` 停写但表与历史保留。

**Tech Stack:** Python 3.11 / Flask / SQLite(WAL) / pytest；前端 Vue 3 `<script setup>` + Element Plus。

**规格来源:** `docs/superpowers/specs/2026-10-09-sheet-write-governance-phase5-gg-zuobiao-design.md`（下称「规格」）

**执行顺序：Task 1 → 2 → 3 → 4 → 5。**
Task 4（退役端点）**必须在 Task 3（前端换源）之后** —— 先换调用方、再删被调用的东西，中间不留断裂状态（四期的执行顺序教训）。

## Global Constraints

- 写表**保持异步**；业务端点的响应不得因写表而阻塞或失败。
- 提示**只在最终结果产生时**发出 —— `pending` / `failed` 不得触发任何用户可见提示；终态（含 `synced`）可提示。
- 状态值固定 6 个，不得增删。**`gg_zuobiao` 不注册 `rollback`**（镜像类），最终失败落 `retry_failed`。
- `target` 用稳定英文 token：**`gg_zuobiao`**。
- **后台线程内禁止使用请求线程的 SQLite 连接**，一律 `database.get_db()` 新建。
- `run_write` / `run_write_many` / `register_target` 的签名与实现**一字不改**；**不要碰 `py/sheet_write.py`**。
- `err(msg, code)` 才是正确写法；**禁止** `return err(msg), code`（本文件用 `jsonify(...), code` 的既有写法时保持一致）。
- **登记必须发生在该端点自身写库的 `commit()` 之后** —— 已核实：
  `/api/google-sheets/update-zuobiao` 的两次 `db2.commit()` 在 `py/main.py:7502` / `:7558`，
  而现有的 `_sync_sheets_background(...)` 在 `:7634` ⇒ **commit 在前**，把登记放在原位置即可。
- **`sheets_sync_log` 表与历史数据保留不动**；本条线只是**不再写它**。
- 本仓库常有并行会话在改文件：**禁止 `git add -A`**，一律 `git add <显式路径>`。
- 不启动/重启任何**常驻服务进程**；`npm run build` 是一次性构建，允许。

### 测试红线（一~四期各踩过多次，本期必须避开）

1. **`time.sleep` 陷阱**：测试若 monkeypatch 全局 `time.sleep` 跳过 30s 重试，**必须**用模块顶部抓的真 sleep 轮询（`from time import sleep as _poll_sleep`）。在 test 体内、patch **之后**再 import 会绑到桩函数 ⇒ 主线程不让出 GIL、断言早于回调 ⇒ 恒失败。
2. **断言必须具判别力**：写完每条测试后问「被测代码坏了这条会不会红？」；**并动手做变异验证**（改坏 → 确认红 → 还原），把失败的断言原文写进报告。
   ⚠️ 四期的教训：**指定变异前先确认那条测试真的会经过被变异的代码路径** —— 只测上层成功态、不经过中间层，等于中间层零覆盖。
3. **换数据源必须重估依赖时序的常量**：四期在这里栽过一次（轮询预算 15s < 后端 30s 重试窗口 ⇒ 失败终态永不可观测）。本期末端有「保存后轮询」时，预算**必须**覆盖 30s 窗口。

---

## File Structure

| 文件 | 动作 | 职责 |
|---|---|---|
| `py/routes/gg_zuobiao_target.py` | **新建** | `gg_zuobiao` target：重建助手、直写、rebuild、注册 |
| `py/main.py` | 修改 | 顶层 import 注册 target；写点 ① 改走 `run_write`；退役两个端点 |
| `py/tests/test_gg_zuobiao_write.py` | **新建** | target + 写点的接线用例 |
| `py/tests/test_google_sheets*.py`（现场确认文件名） | 修改 | 判据迁到新路径（语义不降） |
| `frontend/src/views/ToolkitView.vue` | 修改 | 状态条 → 统一失败汇总区 + 逐条重试；轮询换源 |
| `frontend/src/api/google-sheets.js` | 修改 | 退役 `syncStatus` / `retrySync` 两个包装 |

---

### Task 1: `gg_zuobiao` target（注册 + rebuild）

**Files:**
- Create: `py/routes/gg_zuobiao_target.py`
- Modify: `py/main.py`（顶层 import 注册）
- Test: `py/tests/test_gg_zuobiao_write.py`（新建）

**Interfaces:**
- Consumes: `sheet_write.register_target(name, rebuild, rollback=None)`；`gs.build_service` / `gs.upsert_zuobiao`
- Produces（模块级，后续任务调用）:
  - `gg_zuobiao_key(product_name) -> str`
  - `gg_zuobiao_kwargs(db, user_id, product_name) -> tuple[dict | None, str | None]`
    —— 返回 `(upsert_zuobiao 的实参 dict, None)` 或 `(None, 失败原因)`
  - `gg_zuobiao_sync(user_id, product_name) -> None`
  - 模块导入即注册 target `gg_zuobiao`

- [ ] **Step 1: 写失败测试**

新建 `py/tests/test_gg_zuobiao_write.py`：

```python
"""GG 做表线写表点接入统一治理 —— 端到端测试。

守卫：(1) 写点登记正确的 target / business_key；
(2) 最终失败落 retry_failed（镜像类，**不得**出现 rolled_back）。

⚠️ 轮询必须用**模块顶层**捕获的真 sleep：测试里 monkeypatch 的是全局 `time.sleep`
（跳过 30s 重试），轮询循环自己也调 sleep —— 在 patch 之后再 import 会拿到桩函数、
主线程不让出 GIL、断言提前开火。
"""
from time import sleep as _poll_sleep

import database
import sheet_write


def _gg_user(client, username):
    """注册一个 GG 用户并返回 (headers, uid)。"""
    client.post("/api/auth/register", json={"username": username, "password": "test123"})
    db = database.get_db()
    uid = db.execute("SELECT id FROM users WHERE username=?", (username,)).fetchone()["id"]
    db.close()
    resp = client.post("/api/auth/login", json={"username": username, "password": "test123"})
    return {"Authorization": f"Bearer {resp.get_json().get('access_token', '')}"}, uid


def _row(db, uid, key):
    return db.execute("SELECT * FROM sheet_write_log WHERE user_id=? AND target='gg_zuobiao' "
                      "AND business_key=?", (uid, key)).fetchone()


def _settle(db, uid, key, tries=300):
    for _ in range(tries):
        r = _row(db, uid, key)
        if r is not None and r["status"] in sheet_write.TERMINAL:
            return r
        _poll_sleep(0.02)
    return _row(db, uid, key)


def test_gg_zuobiao_target_registered_without_rollback():
    """target 必须已注册（漏 import 就 KeyError ⇒ 500），且**不注册 rollback**。"""
    import routes.gg_zuobiao_target  # noqa: F401
    assert "gg_zuobiao" in sheet_write.TARGETS, "target 未注册"
    assert sheet_write.TARGETS["gg_zuobiao"]["rollback"] is None, \
        "镜像类不得注册 rollback（会让最终失败落 rolled_back 而非 retry_failed）"


def test_gg_zuobiao_kwargs_rebuilds_from_db(client):
    """重建必须给出 `upsert_zuobiao` 的实参（做表数据可从 DB 重算）。"""
    import routes.gg_zuobiao_target as tgt
    _, uid = _gg_user(client, "_zb_kw")
    db = database.get_db()
    _seed_zuobiao(db, uid, "产品甲")
    kwargs, why = tgt.gg_zuobiao_kwargs(db, uid, "产品甲")
    db.close()
    assert why is None, f"应能重建，实际 {why}"
    assert kwargs["product_name"] == "产品甲", kwargs
    assert kwargs["rows"], f"rows 不能为空：{kwargs}"


def test_gg_zuobiao_kwargs_reports_missing_data(client):
    """没有做表数据 ⇒ 回可读原因（不静默）。"""
    import routes.gg_zuobiao_target as tgt
    _, uid = _gg_user(client, "_zb_kw_none")
    db = database.get_db()
    kwargs, why = tgt.gg_zuobiao_kwargs(db, uid, "不存在的产品")
    db.close()
    assert kwargs is None and why, "找不到数据必须给出原因"
    assert "没找到" in why, f"原因应可读，实际 {why}"


def test_gg_zuobiao_final_failure_lands_retry_failed(client, monkeypatch):
    """最终失败落 retry_failed（**不是** rolled_back）—— 零回滚守卫。"""
    import google_sheets_service as gs
    import time as _time
    monkeypatch.setattr(_time, "sleep", lambda _s: None)
    monkeypatch.setattr(gs, "build_service", lambda _p: object())

    def _boom(*a, **k):
        raise RuntimeError("Sheets 配额超限")

    monkeypatch.setattr(gs, "upsert_zuobiao", _boom)

    _, uid = _gg_user(client, "_zb_fail")
    db = database.get_db()
    _seed_zuobiao(db, uid, "产品甲")
    key = __import__("routes.gg_zuobiao_target", fromlist=["x"]).gg_zuobiao_key("产品甲")
    payload = {"product_name": "产品甲"}
    sync_fn = sheet_write.build_sync("gg_zuobiao", uid, key, payload)
    sheet_write.run_write(db, user_id=uid, platform="gg", target="gg_zuobiao",
                          business_key=key, sync_fn=sync_fn, payload=payload)
    r = _settle(db, uid, key)
    db.close()

    assert r is not None, "必须登记日志行"
    assert r["status"] == "retry_failed", f"应落 retry_failed，实际 {r['status']}"
    assert r["status"] not in ("rolled_back", "rollback_abandoned"), "镜像类不得回滚"
```

> 本文件的本地 helper（**已在计划里给出**，照抄即可）：
>
> ```python
> def _seed_zuobiao(db, uid, product="产品甲", acc="acc_1", date="2026-10-01", region="US"):
>     """种一条做表数据。ad_reports 的 region / report_date 都是 NOT NULL（见 database.py 建表）。"""
>     db.execute(
>         "INSERT INTO ad_reports (user_id, product_name, region, report_date, account, "
>         "customer_id, campaign, cost) VALUES (?,?,?,?,?,?,?,?)",
>         (uid, product, region, date, acc, "c1", "camp", 1))
>     db.commit()
>
>
> def _setup_zuobiao_config(client, hdr):
>     """配好该用户的 Google 表格 —— 保存端点靠它（active_id → sheets 列表）解析 spreadsheet_id。"""
>     resp = client.post("/api/config/google-sheets", headers=hdr,
>                        json={"sheets": [{"id": "m1", "spreadsheet_id": "SHEET_ZB"}],
>                              "active_id": "m1"})
>     assert resp.status_code == 200, resp.get_data(as_text=True)[:200]
> ```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd py && python -m pytest tests/test_gg_zuobiao_write.py -v`
Expected: FAIL —— `ModuleNotFoundError: routes.gg_zuobiao_target`

- [ ] **Step 3: 新建 `py/routes/gg_zuobiao_target.py`**

**重建逻辑从现存重试端点搬进来**（`py/main.py` 的 `google_sheets_retry_sync`，
约 `:7697-7730`）：把那段「查做表数据 → 组装 rows → 取 products 的
`sales_person`/`agency_ratio` → 取用户 display_name → 组装 `upsert_zuobiao` 实参」
整段抽成 `gg_zuobiao_kwargs(db, user_id, product_name)`。

```python
"""GG 做表线的写表目标（五期）。

设计见 docs/superpowers/specs/2026-10-09-sheet-write-governance-phase5-gg-zuobiao-design.md

镜像类（表 = 系统状态的投影，`upsert_zuobiao` 幂等）⇒ **不注册 `rollback`**，
最终失败落 `retry_failed`。rebuild 一律**从 DB 重算**（不重放 `rows_json` 快照）。

线程约束：所有 service 与 DB 连接都在**函数/闭包内**新建 —— 这些代码会在后台线程里跑。
"""
import logging

import sheet_write

log = logging.getLogger("gg-server")


def gg_zuobiao_key(product_name):
    """业务键 = 产品名（该线的日志本就按 `(user_id, product_name)` 定位）。"""
    return product_name


def _zuobiao_spreadsheet_id(db, user_id, report_date):
    """解析该用户**该月**的做表表格 ID。

    做表表是**按月切的**：先按「**操作人名 + `YYYY.MM`**」在 `sheets[].spreadsheet_name`
    里找匹配，找不到退回 `active_config`，再退回 `sheets[0]`。
    **不要简化成「取 active」** —— 那会写到别的月份的表里。

    逻辑等价于 `py/main.py` 的 `google_sheets_update_zuobiao`（`:7471-7490`）里的解析；
    差别只是配置在这里重新取一份（重建在后台线程里跑，没有请求上下文）。
    """
    from main import _get_user_sheets_config

    sheets, active_config = _get_user_sheets_config(user_id)
    if not sheets:
        return ""
    user = db.execute("SELECT display_name, username FROM users WHERE id=?",
                      (user_id,)).fetchone()
    operator_name = (user["display_name"] or user["username"]) if user else ""
    expected = f"{operator_name}{(report_date or '')[:7].replace('-', '.')}"
    matched = next((s for s in sheets
                    if expected in (s.get("spreadsheet_name", "") or "")), None)
    if matched:
        return matched.get("spreadsheet_id", "") or ""
    if active_config:
        return active_config.get("spreadsheet_id", "") or ""
    return (sheets[0].get("spreadsheet_id", "") or "")


def gg_zuobiao_kwargs(db, user_id, product_name):
    """从 DB 重算 `upsert_zuobiao` 的实参。返回 `(kwargs, None)` 或 `(None, 失败原因)`。

    这段重建**逐行搬自退役前的 `/api/google-sheets/retry-sync`**（`py/main.py` 原
    `:7697-7745`）—— 它本来就是唯一真相源。**唯一改动**：`spreadsheet_id` 的来源从
    `log_row["spreadsheet_id"]` 换成 `_zuobiao_spreadsheet_id(db, user_id)`
    （新路径没有 `sheets_sync_log` 行可读）。
    """
    rows_raw = db.execute(
        "SELECT DISTINCT account, customer_id, campaign, cost, impressions, clicks, "
        "installs, in_app_actions, cost_per_in_app, report_date, region "
        "FROM ad_reports WHERE user_id=? AND product_name=? ORDER BY report_date DESC",
        (user_id, product_name)).fetchall()
    if not rows_raw:
        return None, "没有找到对应的做表数据"

    report_date = rows_raw[0]["report_date"] or ""
    region = rows_raw[0]["region"] or ""

    # ⚠️ 表格 ID 依赖 report_date（做表表按月切，保存端点按「操作人名 + YYYY.MM」匹配表名）
    spreadsheet_id = _zuobiao_spreadsheet_id(db, user_id, report_date)
    if not spreadsheet_id:
        return None, "表格 ID 为空"
    rows = [{
        "account": r["account"] or "",
        "customerId": str(r["customer_id"] or ""),
        "campaign": r["campaign"] or "",
        "cost": r["cost"] or 0,
    } for r in rows_raw]

    prod = db.execute(
        "SELECT COALESCE(sp.name, '') AS sales_person, agency_ratio FROM products p "
        "LEFT JOIN sales_persons sp ON p.sales_person_id = sp.id "
        "WHERE p.product_name=? AND (p.is_archived IS NULL OR p.is_archived=0) LIMIT 1",
        (product_name,)).fetchone()
    user = db.execute("SELECT display_name, username FROM users WHERE id=?",
                      (user_id,)).fetchone()

    return {
        "spreadsheet_id": spreadsheet_id,
        "rows": rows,
        "product_name": product_name,
        "region": region,
        "report_date": report_date,
        "sales_person": (prod["sales_person"] or "") if prod else "",
        "agency_ratio": prod["agency_ratio"] if prod else None,
        "operator_name": ((user["display_name"] or user["username"]) if user else ""),
    }, None


def gg_zuobiao_sync(user_id, product_name):
    """把该产品的做表数据写进 Google 表格。"""
    import database
    import google_sheets_service as gs
    from main import _GOOGLE_SHEETS_CONFIG

    db = database.get_db()
    try:
        kwargs, why = gg_zuobiao_kwargs(db, user_id, product_name)
        if kwargs is None:
            raise RuntimeError(why)
    finally:
        db.close()

    service = gs.build_service(_GOOGLE_SHEETS_CONFIG["credentials_path"])
    gs.upsert_zuobiao(service=service, **kwargs)


def _gg_zuobiao_rebuild(user_id, business_key, payload):
    product_name = (payload or {}).get("product_name") or business_key
    if not product_name:
        raise RuntimeError("payload 缺 product_name，无法重建做表数据")

    def _sync():
        gg_zuobiao_sync(user_id, product_name)

    return _sync


# ---------- 注册（模块导入即生效） ----------

sheet_write.register_target("gg_zuobiao", rebuild=_gg_zuobiao_rebuild)
```

- [ ] **Step 4: 顶层 import 注册**

`py/main.py` 的 target 注册区（`import routes.huguan_sheet_targets` / `import routes.fb_sheet_targets` 附近）加：

```python
import routes.gg_zuobiao_target  # noqa: F401  —— 注册 gg_zuobiao target
```

- [ ] **Step 5: 跑测试确认通过**

Run: `cd py && python -m pytest tests/test_gg_zuobiao_write.py -v`
Expected: 4 passed

- [ ] **Step 6: 变异验证（必做）**

把 `_gg_zuobiao_rebuild` 里的 `gg_zuobiao_sync(user_id, product_name)` 改成
`gg_zuobiao_sync(user_id, "写死的产品名")`，跑 `test_gg_zuobiao_kwargs_rebuilds_from_db`
（或终态那条），确认**红**；然后**还原**。把失败的断言原文写进报告。
> 若那条不被影响（payload 恰好等于写死值），**换一条真的经过 payload 的测试**再变异 ——
> 这正是四期栽过的「指定的变异不具判别力」；不许把「没红」当通过。

- [ ] **Step 7: 提交**

```bash
git add py/routes/gg_zuobiao_target.py py/main.py py/tests/test_gg_zuobiao_write.py
git commit -m "feat(gg): gg_zuobiao target（零回滚）

- 新增 routes/gg_zuobiao_target.py：key 构造 / 重建助手（从退役前的重试端点搬入，
  那段查询是唯一真相源）/ 直写 / rebuild / 注册
- main.py 顶层 import 注册（漏 import 的失败形态是调用点 KeyError ⇒ 500）

镜像类 ⇒ 不注册 rollback；rebuild 从 DB 重算，不重放 sheets_sync_log.rows_json 快照。"
```

---

### Task 2: 写点 ① `/api/google-sheets/update-zuobiao` 改走统一入口

**Files:**
- Modify: `py/main.py`（`google_sheets_update_zuobiao`，`:7428`；替换段落在 `:7594`–`:7634`）
- Test: `py/tests/test_gg_zuobiao_write.py`

**Interfaces:**
- Consumes: Task 1 的 `gg_zuobiao_key`；`sheet_write.run_write` / `build_sync`
- Produces: 端点响应形状**不变**（`{success, sheets_status: "syncing", db_saved}`）

- [ ] **Step 1: 写失败测试**

追加到 `py/tests/test_gg_zuobiao_write.py`：

```python
def test_update_zuobiao_registers_and_does_not_block(client, monkeypatch):
    """保存做表数据必须登记 gg_zuobiao，且**端点不阻塞在 Sheets 上**。"""
    import google_sheets_service as gs
    import time as _time
    # Sheets 层做成"很慢"：若端点同步直写，这条会超时；治理后它只是登记
    monkeypatch.setattr(gs, "build_service", lambda _p: object())
    monkeypatch.setattr(gs, "upsert_zuobiao", lambda **k: _time.sleep(2))

    hdr, uid = _gg_user(client, "_zb_save")
    _setup_zuobiao_config(client, hdr)      # 见下：配好表格 ID 等前置

    t0 = _time.time()
    resp = client.post("/api/google-sheets/update-zuobiao", headers=hdr, json={
        "product_name": "产品甲", "report_date": "2026-10-01", "rows": [
            {"account": "acc_1", "customerId": "c1", "cost": 1, "campaign": "x"},
        ],
    })
    elapsed = _time.time() - t0
    assert resp.status_code == 200, resp.get_data(as_text=True)[:300]
    assert resp.get_json()["sheets_status"] == "syncing", resp.get_json()
    assert elapsed < 1.0, f"端点不得阻塞在写表上，实际 {elapsed:.2f}s"

    db = database.get_db()
    r = _settle(db, uid, "产品甲")
    db.close()
    assert r is not None, "保存做表必须登记 gg_zuobiao"
    assert r["business_key"] == "产品甲", r["business_key"]
```

> `_setup_zuobiao_config` 与 `_seed_zuobiao` 都是本测试文件的本地 helper，**代码已在 Task 1
> 的 Step 1 里给出，直接复用**（同一个文件，不必重写）。若该端点还有别的前置导致它提前
> return，按现场补进 helper 并在报告里写明补了什么。

- [ ] **Step 2: 跑测试确认失败**

Run: `cd py && python -m pytest tests/test_gg_zuobiao_write.py -v -k update_zuobiao`
Expected: FAIL —— 查不到 `gg_zuobiao` 的日志行（现在走的是 `_sync_sheets_background`）

- [ ] **Step 3: 实现（替换 `:7594`–`:7634` 那一段）**

把 `def _do_sync(): ...` / `def _on_fail(...): ...` / `_sync_sheets_background(_do_sync, _on_fail)`
**整段**替换为：

```python
    # 接入统一写表治理（五期）：登记 + 后台写 + 失败可查可重试。
    # ⚠️ 位置必须在上面两次 db2.commit()（:7502 / :7558）**之后** —— 否则 run_write 会
    # 在持有未提交写事务的连接上 record_pending，另一条连接拿不到 SQLite 写锁 ⇒
    # 等满 timeout=30 抛 database is locked（三期在 tt_accounts_routes 修过同族缺陷）。
    #
    # 旧实现（自建回调 _on_fail）有两个缺陷，随本次改造消失：
    #  A 中间态 failed 就 INSERT 一条失败记录 ⇒ 30s 重试窗口内就报警
    #  B 终态失败只记进程内字典 _retry_failed_events 且消费端 pop 一次性 ⇒ 重启即丢
    import sheet_write
    import routes.gg_zuobiao_target as _zbt
    _payload = {"product_name": product_name}
    sheet_write.run_write(
        db2, user_id=user_id, platform="gg", target="gg_zuobiao",
        business_key=_zbt.gg_zuobiao_key(product_name),
        sync_fn=sheet_write.build_sync("gg_zuobiao", user_id,
                                       _zbt.gg_zuobiao_key(product_name), _payload),
        payload=_payload)
```

**同时删掉**（如果替换后不再被引用）：`_fmt_rows`、`_op_name` 及那批 `_spreadsheet_id`/`_region`/…
的闭包捕获变量、以及 `_retry_failed_events` 里**只服务于本写点**的那半（见 Task 4 的核实要求）。
响应的 `resp` 字典保持原样。

> ⚠️ `run_write` 的 `db` 形参在这里是 `db2` —— **实施时按现场确认该端点内用的是哪个连接变量**
> （`:7502`/`:7558` 的 `db2.commit()` 表明写表数据用的是 `db2`），别照抄变量名。

- [ ] **Step 4: 跑测试确认通过**

Run: `cd py && python -m pytest tests/test_gg_zuobiao_write.py -v`
Expected: 5 passed

- [ ] **Step 5: 提交**

```bash
git add py/main.py py/tests/test_gg_zuobiao_write.py
git commit -m "feat(gg): 做表保存改走统一治理（缺陷 A/B 由构造消失）

原来它自带一整套：自建回调 _on_fail + 自己的 sheets_sync_log 行 + 进程内
_retry_failed_events 事件。改为 run_write 登记后，失败落 sheet_write_log（持久、可重试）：
  A 中间态 failed 不再有任何落库点（/status 只回终态）⇒ 重试窗口内不再报警
  B 终态失败不再依赖进程内字典 + pop 一次性 ⇒ 重启不丢、也不会被漏轮询吞掉

登记点位于该端点两次 db2.commit() 之后（已核实 :7502/:7558 < :7634），
避免在持有未提交写事务的连接上 record_pending 撞 SQLite 单写者。"
```

---

### Task 3: 前端 —— 做表页换成统一失败汇总区 + 逐条重试

**Files:**
- Modify: `frontend/src/views/ToolkitView.vue`（状态条 `:34-45`；`syncStatus` 轮询 `:376`/`:543`；`zbRetrySheetsSync` `:580`）

**Interfaces:**
- Consumes: `sheetWriteApi.status({platform:'gg', target:'gg_zuobiao', businessKey})` / `sheetWriteApi.retry({platform:'gg', target:'gg_zuobiao', businessKey})`；`sheetWriteTone` / `sheetWriteHint` / `SHEET_WRITE_TOAST`（`@/utils/sheetWriteUi`）

- [ ] **Step 1: 替换状态条为失败汇总区**

把 `:34-45` 那段「表格同步状态提示条」（含 `🔄 重新同步` 按钮）整块换成**与 FB 数据管理页 /
户管看板卡片同款**的失败汇总区（视觉取值**逐字照抄** `frontend/src/views/fb/FbDataManage.vue`
里的那块 —— 3px 琥珀左脊柱 + warning 色调 + 三态语汇 + `sheetWriteUi` 文案源），只改三处：

- 标题量词同「项」；`fbSwFailures` → `zbSwFailures`
- 数据源 target：`{ platform: 'gg', target: 'gg_zuobiao' }`
- 逐条重试：`sheetWriteApi.retry({ platform: 'gg', target: 'gg_zuobiao', businessKey: f.business_key })`

**无失败时零渲染**（`v-if="zbSwFailures.length"`）。保留该页原有的产品选择等上下文。

- [ ] **Step 2: 轮询换源 + 预算必须覆盖 30s 重试窗口**

`syncStatus(zbSelectedProduct)` 的两处（产品切换 `:376`、保存后轮询 `:543`）改为按
**business_key = 产品名**查统一 status：

```js
// 轮询本次写表结果：pending/failed 静默续查（**不得提示中间态**）；
// 上限必须 > 后端 30s 重试窗口，否则终态 retry_failed 在 40s 前落不了库（四期栽过）。
const ZB_SW_POLL_MS = 3000
const ZB_SW_POLL_MAX = 15          // ~45s，覆盖 30s 重试窗口
```

保存后的提示保持「数据库已保存 N 条，表格后台同步中...」不变 ✓。

- [ ] **Step 3: 构建验证**

Run: `cd frontend && npm run build`
Expected: exit 0

- [ ] **Step 4: 提交**

```bash
git add frontend/src/views/ToolkitView.vue
git commit -m "feat(gg-ui): 做表页换成统一失败汇总区 + 逐条重试

原「表格同步状态提示条 + 重新同步按钮」只能表达一条状态；改为与 FB 数据管理页 /
户管看板卡片同款的汇总区（按产品列出失败项 + 逐条重试），全 app 一套失败语汇。
轮询换源到 /api/sheet-write/status（带 target 过滤），预算 45s 覆盖后端 30s 重试窗口。"
```

---

### Task 4: 退役两个端点 + 前端包装

**Files:**
- Modify: `py/main.py`（删 `google_sheets_sync_status` `:7646`、`google_sheets_retry_sync` `:7672`；清理只服务于它们的代码）
- Modify: `frontend/src/api/google-sheets.js`（删 `syncStatus` / `retrySync`）
- Test: 现场相关的 `py/tests/*`（清理引用）

> **执行顺序：本任务在 Task 3 之后做。**先换调用方，再删端点。

- [ ] **Step 1: 先 grep 核实无人再依赖**

Run:
```bash
grep -rn "sync-status\|retry-sync\|syncStatus\|retrySync" frontend/src py --include=*.vue --include=*.js --include=*.py | grep -v node_modules
grep -rn "sheets_sync_log" py --include=*.py | grep -v tests
grep -rn "_retry_failed_events" py --include=*.py
```
Expected：前端只剩 `api/google-sheets.js` 里的定义（本任务删）；后端 `sheets_sync_log`
只剩 `database.py` 的建表与**本文件即将删掉的那两处**；`_retry_failed_events` 只剩本文件内的定义与消费。

- [ ] **Step 2: 删除**

- 删 `google_sheets_sync_status`（`/api/google-sheets/sync-status`）与其装饰器
- 删 `google_sheets_retry_sync`（`/api/google-sheets/retry-sync`）与其装饰器
- 删只服务于它们的 `_retry_failed_events` 定义与消费点（`:7110` / `:7670`）
- `frontend/src/api/google-sheets.js` 删 `syncStatus` / `retrySync` 两行
- 清理测试里对这两个端点的引用（**判据迁到新路径，语义不降；不要整条删掉**）

- [ ] **Step 3: 零残留核实（把 grep 命令与输出贴进报告）**

Run: `grep -rn "google-sheets/sync-status\|google-sheets/retry-sync\|_retry_failed_events" py frontend/src --include=*.py --include=*.js --include=*.vue`
Expected: **零命中**

- [ ] **Step 4: 跑测试**

Run: `cd py && python -m pytest tests/ -q`
Expected: 全绿

- [ ] **Step 5: 提交**

```bash
git add py/main.py frontend/src/api/google-sheets.js py/tests
git commit -m "chore(gg): 退役做表线的两个专属端点 + 前端包装

/api/google-sheets/sync-status 与 /retry-sync 退役（逐条重试改用三期已上线的
/api/sheet-write/retry），_retry_failed_events 内存事件一并删除 ——
它正是缺陷 B 的载体。sheets_sync_log 表与历史保留不动。"
```

---

### Task 4.5: 养户行必须继续写进做表表（插队修复，用户 2026-10-10 已裁定「必须继续写」）

> 位置在 T4 之后、T5 之前。定性：**功能回退修复** —— T2 把写表实参改为从 `ad_reports` 重建，
> 而保存端点写库时只落非养户行（`db_rows = [r for r in raw_rows if not r.get("is_yanghu")]`）
> ⇒ `ad_reports` 里没有养户行 ⇒ 养户行不再被写进做表表。目标行为由缺陷本身决定（恢复既有意图）。

**方案：随 payload 携带养户行**（不采用「把养户行也落库」，那要动 schema 与既有数据语义）。

- **改动 1** `py/main.py` 登记块：`_payload` 补 `yanghu_rows`（请求 `rows` 里 `is_yanghu` 的行，
  保原顺序、绝不截断）+ `report_date` / `region`（纯养户行时兜底）。
- **改动 2** `py/routes/gg_zuobiao_target.py`：`gg_zuobiao_kwargs` / `gg_zuobiao_sync` /
  `_gg_zuobiao_rebuild` 加 `yanghu_rows` / `report_date` / `region` 参数；
  空数据判断改为 `if not rows_raw and not yanghu_rows:`；`rows = DB 非养户行 + list(yanghu_rows or [])`。
  老日志行无这些键 ⇒ `.get()` 缺省 ⇒ 行为与现状一致。
- **改动 3** 测试 `py/tests/test_gg_zuobiao_write.py` 追加 4 条：真入口带养户行 / 重试路径复现 /
  纯养户行不早退 / 无养户行不变；变异验证 3 条（去掉 payload 的 yanghu_rows、去掉 rows 追加、
  空判断改回 `if not rows_raw:`）。
- **改动 4** 文档：设计 §4.2 补「rebuild 一律从 DB 重算」的养户行例外；本计划补记本条。

### Task 5: 收尾回归

- [ ] **Step 1: 全量**

Run: `cd py && python -m pytest tests/ -q`
Expected: 全绿（预计 1803 + 本期新增约 6 条）

- [ ] **Step 2: 前端**

Run: `cd frontend && npm test && npm run build`
Expected: 20 passed；exit 0

- [ ] **Step 3: 变异验证（本项目连续四期栽在「测试没判别力」上，必做）**

1. 给 `gg_zuobiao` 注册一个 `rollback` ⇒ 「零回滚」守卫用例必须红；
2. 把登记挪到该端点 `commit()` **之前** ⇒ 必须红（或出现 `database is locked`）。
   两条都要贴出**红断言原文**并**还原**。

- [ ] **Step 4: 独立终审 + 交付**

派独立审查员（对抗性、逐条变异验证）；通过后提醒用户**重启 Flask**（后端有实质改动）
并跑人工清单；推 origin 需用户单独确认。

**人工清单（交用户执行）**：
1. 做表页选一个产品 → 保存数据 → 应弹「已保存 N 条，表格后台同步中...」；
   把表格配置改坏 → 保存 → **失败项应出现在汇总区**
2. 恢复配置 → 点失败项的「重试」→ 应转成功、汇总区消失
3. 无失败时汇总区**不应出现**
4. 一个用户有多个产品失败时，**每条都要显示**
