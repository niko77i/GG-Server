# 写表失败统一治理（四期：FB 报告写表域接入）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 FB 报告做表的 3 个写点接入一期确立的统一治理机制（新增 `fb_report` 一个 target），使失败产生带原因的持久记录、可查、可重试；**不做业务回滚**（`upsert` 幂等，全镜像类）。

**Architecture:** 新建 `py/routes/fb_sheet_targets.py` 注册 `fb_report` target（rebuild 复用 `_rebuild_fb_records`，「从 DB 重算」）；3 个写点改走 `sheet_write.run_write` / `run_write_many`；FB 停写 `sheets_sync_log`（表保留给 GG 做表线）；三个 FB 专属端点退役，前端改读三期的 `/api/sheet-write/status`。

**Tech Stack:** Python 3.11 / Flask / SQLite(WAL) / pytest；前端 Vue 3 `<script setup>` + Element Plus。

**规格来源:** `docs/superpowers/specs/2026-10-09-sheet-write-governance-phase4-fb-design.md`（下称「规格」）

**执行顺序：Task 1 → 2 → 3 → 5 → 6 → 4 → 7。**
Task 4（退役端点与 API 包装）**必须在前端换源（Task 5 / 6）之后**执行 ——
先把调用方换掉，再删被调用的东西，中间不留断裂状态。

## Global Constraints

- 写表**保持异步**；业务端点的响应不得因写表而阻塞或失败。**重试端点也异步化**（规格 §3.2）。
- 提示**只在最终结果产生时发出** —— `pending` / `failed` 不得触发任何用户可见提示；**终态（含 `synced`）可提示**。
  > **勘误（2026-10-09 终审）**：原文把 `synced` 也列入「不得提示」，与本计划 Task 5 的逐字代码
  > （`if (it.status === 'synced') return ElMessage.success('✅ 写表成功')`）和 Task 6 人工清单第 1 条
  > （「提取保存后 → 提取页应弹『✅ 写表成功』」）**直接矛盾**。`synced` 是终态，可提示；
  > 本页的成功确认是一次**显式用户动作的闭环**（用户点保存 → 轮询到 synced → 弹 ✅），不在禁止之列。
  > 同步更正规格 §3 第 3 条。
- 状态值固定 6 个，不得增删。**`fb_report` 不注册 `rollback`**（镜像类），最终失败落 `retry_failed`。
- `target` 用稳定英文 token：**`fb_report`**。
- **后台线程内禁止使用请求线程的 SQLite 连接**，一律 `database.get_db()` 新建。
- `run_write` / `run_write_many` / `register_target` 的签名与实现**一字不改**（一期已审）。
- `err(msg, code)` 才是正确写法；**禁止** `return err(msg), code`。
- 本仓库常有并行会话在改文件：**禁止 `git add -A`**，一律 `git add <显式路径>`。
- 不启动/重启任何**常驻服务进程**；`npm run build` 是一次性构建，允许。
- **`sheets_sync_log` 表与历史数据保留不动**（规格 §4.5，用户裁定）；FB 只是**不再写它**。
  `main.py` 里 GG 做表那条线继续读写它 —— 不得改动。

### 测试红线（一/二/三期各踩过多次，本期必须避开）

1. **`time.sleep` 陷阱**：测试若 monkeypatch 全局 `time.sleep` 跳过 30s 重试，**必须**用模块顶部抓的真 sleep 轮询（`from time import sleep as _poll_sleep`）。在 test 体内、patch **之后**再 import 会绑到桩函数 ⇒ 主线程不让出 GIL、断言早于回调 ⇒ 恒失败。
2. **断言必须具判别力**：写完每条测试后问「被测代码坏了这条会不会红？」；**对 §Task 6 点名的两条做变异验证**（改坏 → 确认红 → 还原），把失败的断言原文写进报告。
3. `run_write_many` 的 `sync_fn` **只执行一次** —— 传给它的工厂必须覆盖全部 N 键（用 `build_many_sync` 形态），拿单键工厂会让只有第一组被写而 N 行全落 `synced`。
4. **杀掉 `sheets_sync_log` 的读依赖前先确认没人再读** —— `main.py` 的 GG 做表线仍在读写它。

---

## File Structure

| 文件 | 动作 | 职责 |
|---|---|---|
| `py/routes/fb_sheet_targets.py` | **新建** | `fb_report` target：key 构造、直写、rebuild、注册 |
| `py/main.py` | 修改 | 顶层 import 注册 target（`:384` 附近） |
| `py/routes/fb_routes.py` | 修改 | `_rebuild_fb_records` 改签名；3 个写点改走统一入口；退役 3 个端点；FB 停写 `sheets_sync_log` |
| `py/tests/test_fb_sheet_write.py` | **新建** | `fb_report` target + 3 个写点的接线用例 |
| `py/tests/test_fb_sheets_retry.py` | 修改 | 判据迁到新路径（语义不降） |
| `py/tests/test_fb_platform.py` | 修改 | E11 系列里 FB 那几条迁到新路径 |
| `frontend/src/api/fb.js` | 修改 | 退役 3 个包装（含零调用的 `lastSyncStatus`） |
| `frontend/src/views/fb/FbDataExtract.vue` | 修改 | 轮询换源到统一 status |
| `frontend/src/views/fb/FbDataManage.vue` | 修改 | 新增失败汇总区 + 重试全部 |

---

### Task 1: `fb_report` target（注册 + rebuild）

**Files:**
- Create: `py/routes/fb_sheet_targets.py`
- Modify: `py/main.py`（`:384` 附近加 import）
- Modify: `py/routes/fb_routes.py`（`_rebuild_fb_records` 改签名）
- Test: `py/tests/test_fb_sheet_write.py`（新建）

**Interfaces:**
- Consumes: `sheet_write.register_target(name, rebuild, rollback=None)`；`_rebuild_fb_records`；`gs.upsert_fb_reports(db, user_id, product_name, line_name, report_date, records)`
- Produces（模块级，后续任务调用）:
  - `fb_report_key(product_name, line_name, report_date) -> str`
  - `fb_report_sync(user_id, product_name, line_name, report_date) -> None`
  - `fb_report_many_sync(user_id, groups) -> Callable[[], None]`（`groups = [(产品,线,日期), ...]`）
  - 模块导入即注册 target `fb_report`

- [ ] **Step 1: 写失败测试**

新建 `py/tests/test_fb_sheet_write.py`：

```python
"""FB 报告写表点接入统一治理 —— 端到端测试。

守卫两件事：(1) 三个写点都登记正确的 target 与 business_key；
(2) 最终失败落 retry_failed（镜像类，**不得**出现 rolled_back）。

⚠️ 轮询必须用**模块顶层**捕获的真 sleep（下）：测试里 monkeypatch 的是全局
`time.sleep`（跳过 30s 重试），轮询循环自己也调 sleep —— 在 patch 之后再
`from time import sleep` 会拿到桩函数、主线程不让出 GIL、断言提前开火。
"""
import json
from time import sleep as _poll_sleep

import database
import sheet_write


def _fb_user(client, username):
    """注册一个 fb 平台用户并返回 (headers, uid)。"""
    client.post("/api/auth/register", json={"username": username, "password": "test123"})
    db = database.get_db()
    db.execute("UPDATE users SET platform='fb' WHERE username=?", (username,))
    db.commit()
    uid = db.execute("SELECT id FROM users WHERE username=?", (username,)).fetchone()["id"]
    db.close()
    resp = client.post("/api/auth/login", json={"username": username, "password": "test123"})
    return {"Authorization": f"Bearer {resp.get_json().get('access_token', '')}"}, uid


def _seed_report(db, uid, product="产品甲", line="线A", date="2026-10-01", acc="acc_1"):
    db.execute(
        "INSERT INTO fb_ad_reports (user_id, product_name, line_name, report_date, "
        "account_name, account_id, cost, impressions, clicks, registrations, purchases, "
        "cost_per_purchase) VALUES (?,?,?,?,'名','"+acc+"',1,2,3,4,5,6)",
        (uid, product, line, date))
    db.commit()


def _row(db, uid, key):
    return db.execute("SELECT * FROM sheet_write_log WHERE user_id=? AND target='fb_report' "
                      "AND business_key=?", (uid, key)).fetchone()


def _settle(db, uid, key, tries=300):
    for _ in range(tries):
        r = _row(db, uid, key)
        if r is not None and r["status"] in sheet_write.TERMINAL:
            return r
        _poll_sleep(0.02)
    return _row(db, uid, key)


def test_fb_report_target_registered_without_rollback():
    """target 必须已注册（漏 import 就 KeyError ⇒ 500），且**不注册 rollback**。"""
    import routes.fb_sheet_targets  # noqa: F401
    assert "fb_report" in sheet_write.TARGETS, "target 未注册"
    assert sheet_write.TARGETS["fb_report"]["rollback"] is None, \
        "镜像类不得注册 rollback（会让最终失败落 rolled_back 而非 retry_failed）"


def test_fb_report_sync_rebuilds_from_db(client, monkeypatch):
    """rebuild 从 fb_ad_reports 重算，并把 (产品,线,日期) 原样交给 upsert。"""
    import google_sheets_service as gs
    import routes.fb_sheet_targets as tgt
    calls = []
    monkeypatch.setattr(gs, "upsert_fb_reports",
                        lambda db, uid, p, l, d, records: calls.append(
                            (p, l, d, sorted(r["account_id"] for r in records))))

    _, uid = _fb_user(client, "_fbsw_sync")
    db = database.get_db()
    _seed_report(db, uid, acc="acc_1")
    _seed_report(db, uid, acc="acc_2")
    db.close()

    tgt.fb_report_sync(uid, "产品甲", "线A", "2026-10-01")
    assert calls == [("产品甲", "线A", "2026-10-01", ["acc_1", "acc_2"])], f"实际 {calls}"


def test_fb_report_sync_raises_actionable_reason_when_no_rows(client):
    """找不到原始数据 ⇒ raise 带**可操作**原因（不是固定文案）。"""
    import routes.fb_sheet_targets as tgt
    _, uid = _fb_user(client, "_fbsw_norows")
    try:
        tgt.fb_report_sync(uid, "产品甲", "线A", "2099-01-01")
    except RuntimeError as e:
        assert "找不到对应的原始数据" in str(e), f"原因应可操作，实际 {e}"
    else:
        raise AssertionError("没有原始数据时必须抛错，不得静默成功")


def test_fb_report_final_failure_lands_retry_failed(client, monkeypatch):
    """最终失败落 retry_failed（**不是** rolled_back）—— 零回滚守卫。"""
    import google_sheets_service as gs
    import time as _time
    monkeypatch.setattr(_time, "sleep", lambda _s: None)
    monkeypatch.setattr(gs, "build_service", lambda _p: object())

    def _boom(*a, **k):
        raise RuntimeError("Sheets 配额超限")

    monkeypatch.setattr(gs, "upsert_fb_reports", _boom)

    _, uid = _fb_user(client, "_fbsw_fail")
    db = database.get_db()
    _seed_report(db, uid)
    key = __import__("routes.fb_sheet_targets", fromlist=["x"]).fb_report_key(
        "产品甲", "线A", "2026-10-01")
    sync_fn = sheet_write.build_sync("fb_report", uid, key,
                                     {"product_name": "产品甲", "line_name": "线A",
                                      "report_date": "2026-10-01"})
    sheet_write.run_write(db, user_id=uid, platform="fb", target="fb_report",
                          business_key=key, sync_fn=sync_fn,
                          payload={"product_name": "产品甲", "line_name": "线A",
                                   "report_date": "2026-10-01"})
    r = _settle(db, uid, key)
    db.close()

    assert r is not None, "必须登记日志行"
    assert r["status"] == "retry_failed", f"应落 retry_failed，实际 {r['status']}"
    assert r["status"] not in ("rolled_back", "rollback_abandoned"), "镜像类不得回滚"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd py && python -m pytest tests/test_fb_sheet_write.py -v`
Expected: FAIL —— `ModuleNotFoundError: routes.fb_sheet_targets`（或 `target 未注册: fb_report`）

- [ ] **Step 3: 改 `_rebuild_fb_records` 的签名**

`py/routes/fb_routes.py`：把 `def _rebuild_fb_records(db, user_id, log_row):` 改为收三元组，
函数体内不再读 `log_row`：

```python
def _rebuild_fb_records(db, user_id, product_name, line_name, report_date):
    """按 (产品名, 线名, 日期) 回查 fb_ad_reports，重建待写 records。

    返回 `(records, None)` 或 `(None, 失败原因)`。

    **刻意不读 `sheets_sync_log.rows_json`**：那个快照在写入时被 `[:10000]` 截断，
    每条 record 约 200 字符，超过约 50 条就从中间断开 ⇒ 重试照样是坏的。
    `fb_ad_reports` 存的是完整原始行，且按
    (user_id, product_name, line_name, account_id, report_date) 唯一，重建更可靠。
    """
    report_date = (report_date or '').strip()
    if not report_date:
        # 这两列是随 2026-10-06 那次修复才落库的，修复前写入的行没有它，无从定位
        return None, '这条同步记录缺少日期，无法重建待写数据，请重新保存一次数据'
    records = db.execute(
        "SELECT account_name, account_id, cost, impressions, clicks, "
        "registrations, purchases, cost_per_purchase FROM fb_ad_reports "
        "WHERE user_id=? AND product_name=? AND line_name=? AND report_date=?",
        (user_id, product_name, (line_name or '').strip(), report_date)
    ).fetchall()
    if not records:
        return None, '找不到对应的原始数据，无法重建待写数据，请重新保存一次数据'
    return [dict(r) for r in records], None
```

> 旧签名只有 Task 2 即将改造的那两条重试路径在用（`test_fb_sheets_retry.py` 里也是）。
> 改完在 Task 2 里同步更新调用点；本步先只改签名与实现。

- [ ] **Step 4: 新建 `py/routes/fb_sheet_targets.py`**

```python
"""FB 报告做表的写表目标（四期）。

设计见 docs/superpowers/specs/2026-10-09-sheet-write-governance-phase4-fb-design.md

镜像类（表 = 系统状态的投影，一次 `upsert_fb_reports` 覆盖该组全部记录）⇒
**不注册 `rollback`**，最终失败落 `retry_failed`。rebuild 一律**从 DB 重算**。

线程约束：所有 service 与 DB 连接都在**函数/闭包内**新建 —— 这些代码会在后台线程里跑。
"""
import logging

import sheet_write

log = logging.getLogger("gg-server")


def fb_report_key(product_name, line_name, report_date):
    """业务键 = `产品|线|日期`。**仅作前端展示**（汇总区要显示是哪一组失败）。

    重建**不**依赖拆它 —— 名字里若含 `|` 会拆错；权威来源是 payload（见下）。
    """
    return f"{product_name}|{line_name}|{report_date}"


def fb_report_sync(user_id, product_name, line_name, report_date):
    """把该 (产品,线,日期) 组的记录写进该用户的 FB 做表。"""
    import database
    import google_sheets_service as gs
    from routes.fb_routes import _rebuild_fb_records

    db = database.get_db()
    try:
        records, why = _rebuild_fb_records(db, user_id, product_name, line_name, report_date)
        if records is None:
            # 可操作的原因原样抛出 —— 它进 sheet_write_log.error_msg 前会被
            # 换成统一固定文案（防泄露），所以调用点用「登记前先重建」拦这类情况，
            # 不指望它到得了用户眼前（见 design §4.2）。
            raise RuntimeError(why)
        gs.upsert_fb_reports(db, user_id, product_name, line_name, report_date, records)
    finally:
        db.close()


def _payload_triple(payload, business_key):
    """从 payload 取 (产品,线,日期)。

    单条登记时 payload 是扁平三要素；批量登记（`run_write_many` 只有一个 payload）
    时是 `{"groups": {business_key: [产品,线,日期], …}}` 的映射。
    """
    p = payload or {}
    if "product_name" in p:
        return (p.get("product_name"), p.get("line_name"), p.get("report_date"))
    tri = (p.get("groups") or {}).get(business_key)
    if not tri:
        raise RuntimeError("payload 里找不到这组的 (产品,线,日期)，无法重建")
    return tuple(tri)


def _fb_report_rebuild(user_id, business_key, payload):
    product_name, line_name, report_date = _payload_triple(payload, business_key)

    def _sync():
        fb_report_sync(user_id, product_name, line_name, report_date)

    return _sync


def fb_report_many_sync(user_id, groups):
    """**批量首跑/批量重试**用：一次覆盖 N 组。

    `run_write_many` 的 `sync_fn` 只执行**一次**；拿单组工厂顶上会让只有第一组被写
    而 N 行全落 `synced`（静默漏写，二期踩过）。
    """
    groups = [tuple(g) for g in groups]

    def _sync():
        for product_name, line_name, report_date in groups:
            fb_report_sync(user_id, product_name, line_name, report_date)

    return _sync


# ---------- 注册（模块导入即生效） ----------

sheet_write.register_target("fb_report", rebuild=_fb_report_rebuild)
```

- [ ] **Step 5: 顶层 import 注册**

`py/main.py` 的 `:384`（`import routes.huguan_sheet_targets` 那行）之后加：

```python
import routes.fb_sheet_targets  # noqa: F401  —— 注册 fb_report target
```

- [ ] **Step 6: 跑测试确认通过**

Run: `cd py && python -m pytest tests/test_fb_sheet_write.py -v`
Expected: 4 passed

- [ ] **Step 7: 变异验证（必做）**

把 `_fb_report_rebuild` 里的 `_payload_triple(payload, business_key)` 改成
写死的 `("产品甲", "线A", "2026-10-01")`，跑
`test_fb_report_sync_raises_actionable_reason_when_no_rows`，确认**红**；然后**还原**。
把失败的断言原文写进报告。

- [ ] **Step 8: 提交**

```bash
git add py/routes/fb_sheet_targets.py py/main.py py/routes/fb_routes.py py/tests/test_fb_sheet_write.py
git commit -m "feat(fb): fb_report target（零回滚）

- 新增 routes/fb_sheet_targets.py：key 构造 / 直写 / rebuild（复用 _rebuild_fb_records
  「从 DB 重算」）/ 批量工厂 / 注册
- _rebuild_fb_records 签名从收 log_row 改成收 (产品,线,日期) 三元组 ——
  旧签名只有即将退役的两条重试路径在用
- main.py 顶层 import 注册（漏 import 的失败形态是调用点 KeyError ⇒ 500）

镜像类 ⇒ 不注册 rollback；rebuild 从 DB 重算，不重放 rows_json 快照
（那个快照本来就被 [:10000] 截断、不可靠）。"
```

---

### Task 2: 写点 ② ③（重试单条 / 批量）改走统一入口

**Files:**
- Modify: `py/routes/fb_routes.py`（`fb_retry_sheets_sync`，约 `:1948-2030`）
- Test: `py/tests/test_fb_sheet_write.py`、`py/tests/test_fb_sheets_retry.py`

**Interfaces:**
- Consumes: Task 1 的 `fb_report_key` / `fb_report_many_sync`；`sheet_write.run_write` / `run_write_many` / `build_sync`
- Produces: `fb_retry_sheets_sync` 改为「重建前置 → 登记 → 回已受理」；响应形状从 `{retried: N}` 改为 `{accepted: N, failed: [...]}`（`failed[]` 形状不变）

**关键约束（规格 §4.2）**：**登记前先重建一次**（纯 DB 读、不碰 Sheets）。重建失败 ⇒
**不登记**，把可操作原因原样回给用户（保住 `test_fb_sheets_retry.py` 守的判据）。

- [ ] **Step 1: 写失败测试**

追加到 `py/tests/test_fb_sheet_write.py`：

```python
def test_retry_single_registers_and_rebuild_failure_does_not(client, monkeypatch):
    """重试单条：可重建 ⇒ 登记 fb_report；不可重建 ⇒ 400 + 可操作原因、**零行登记**。"""
    import google_sheets_service as gs
    monkeypatch.setattr(gs, "upsert_fb_reports", lambda *a, **k: None)

    hdr, uid = _fb_user(client, "_fbsw_r1")
    db = database.get_db()
    _seed_report(db, uid, product="产品甲", line="线A", date="2026-10-01")
    db.close()

    body = {"groups": [["产品甲", "线A", "2026-10-01"]]}
    resp = client.post("/api/fb/reports/retry-sync", headers=hdr, json=body)
    assert resp.status_code == 200, resp.get_data(as_text=True)[:200]
    assert resp.get_json()["accepted"] == 1, resp.get_json()

    key = __import__("routes.fb_sheet_targets", fromlist=["x"]).fb_report_key(
        "产品甲", "线A", "2026-10-01")
    db = database.get_db()
    r = _settle(db, uid, key)
    db.close()
    assert r is not None, "重试必须登记 fb_report"
    assert r["status"] == "synced", f"实际 {r['status']}"

    # 不可重建（单组）：400 + 可操作原因，且没有任何行被登记
    resp = client.post("/api/fb/reports/retry-sync", headers=hdr,
                       json={"groups": [["产品乙", "线B", "2099-01-01"]]})
    assert resp.status_code == 400, resp.get_data(as_text=True)[:200]
    assert "找不到对应的原始数据" in resp.get_json()["error"], resp.get_json()
    db = database.get_db()
    n = db.execute("SELECT COUNT(*) FROM sheet_write_log WHERE target='fb_report' "
                   "AND business_key LIKE '产品乙%'").fetchone()[0]
    db.close()
    assert n == 0, f"重建失败不得登记，实际 {n} 行"


def test_retry_by_business_keys_reads_payload(client, monkeypatch):
    """汇总区重试：只回传 business_key 列表，端点从该行 payload_json 取三元组。

    这条挡住「客户端自己拆 `产品|线|日期`」那条路 —— 名字含 `|` 会拆错。
    """
    import google_sheets_service as gs
    written = []
    monkeypatch.setattr(gs, "upsert_fb_reports",
                        lambda db, uid, p, l, d, records: written.append((p, l, d)))

    hdr, uid = _fb_user(client, "_fbsw_bk")
    db = database.get_db()
    _seed_report(db, uid, product="甲|乙", line="L1", date="2026-10-01", acc="a1")
    key = __import__("routes.fb_sheet_targets", fromlist=["x"]).fb_report_key(
        "甲|乙", "L1", "2026-10-01")
    # 直接造一条失败的既有行（不起线程，确定且快）—— 端点要能从它的 payload_json 取三元组
    db.execute(
        "INSERT INTO sheet_write_log (user_id, platform, target, business_key, status, "
        "payload_json) VALUES (?, 'fb', 'fb_report', ?, 'retry_failed', ?)",
        (uid, key, json.dumps({"product_name": "甲|乙", "line_name": "L1",
                               "report_date": "2026-10-01"}, ensure_ascii=False)))
    db.commit()
    db.close()

    resp = client.post("/api/fb/reports/retry-sync", headers=hdr,
                       json={"business_keys": [key]})
    assert resp.status_code == 200, resp.get_data(as_text=True)[:200]
    assert resp.get_json()["accepted"] == 1, resp.get_json()
    for _ in range(300):
        if written:
            break
        _poll_sleep(0.02)
    assert written == [("甲|乙", "L1", "2026-10-01")], \
        f"名字含 `|` 也必须按 payload 取对三元组，实际 {written}"


def test_retry_by_business_keys_reads_mapped_payload(client, monkeypatch):
    """**批量登记**留下的行：payload 是 {business_key: [产品,线,日期]} 映射，也要认。

    自审时抓到的坑：只认扁平 payload ⇒ 批量失败的行永远重试不了。
    """
    import google_sheets_service as gs
    written = []
    monkeypatch.setattr(gs, "upsert_fb_reports",
                        lambda db, uid, p, l, d, records: written.append((p, l, d)))

    hdr, uid = _fb_user(client, "_fbsw_bkmap")
    db = database.get_db()
    _seed_report(db, uid, product="甲", line="L1", date="2026-10-01", acc="a1")
    key = __import__("routes.fb_sheet_targets", fromlist=["x"]).fb_report_key(
        "甲", "L1", "2026-10-01")
    db.execute(
        "INSERT INTO sheet_write_log (user_id, platform, target, business_key, status, "
        "payload_json) VALUES (?, 'fb', 'fb_report', ?, 'retry_failed', ?)",
        (uid, key, json.dumps({"groups": {key: ["甲", "L1", "2026-10-01"]}},
                              ensure_ascii=False)))
    db.commit()
    db.close()

    resp = client.post("/api/fb/reports/retry-sync", headers=hdr,
                       json={"business_keys": [key]})
    assert resp.status_code == 200, resp.get_data(as_text=True)[:200]
    assert resp.get_json()["accepted"] == 1, resp.get_json()
    for _ in range(300):
        if written:
            break
        _poll_sleep(0.02)
    assert written == [("甲", "L1", "2026-10-01")], f"映射形状的 payload 也要认，实际 {written}"


def test_retry_batch_covers_every_group(client, monkeypatch):
    """批量重试必须覆盖**每一组**（单组工厂会漏写，二期踩过）。"""
    import google_sheets_service as gs
    written = []
    monkeypatch.setattr(gs, "upsert_fb_reports",
                        lambda db, uid, p, l, d, records: written.append((p, l, d)))

    hdr, uid = _fb_user(client, "_fbsw_rb")
    db = database.get_db()
    _seed_report(db, uid, product="甲", line="L1", date="2026-10-01", acc="a1")
    _seed_report(db, uid, product="乙", line="L2", date="2026-10-02", acc="a2")
    _seed_report(db, uid, product="丙", line="L3", date="2026-10-03", acc="a3")
    db.close()

    resp = client.post("/api/fb/reports/retry-batch", headers=hdr,
                       json={"groups": [["甲", "L1", "2026-10-01"],
                                        ["乙", "L2", "2026-10-02"],
                                        ["丙", "L3", "2026-10-03"]]})
    assert resp.status_code == 200, resp.get_data(as_text=True)[:200]
    assert resp.get_json()["accepted"] == 3, resp.get_json()

    for _ in range(300):
        if len(written) >= 3:
            break
        _poll_sleep(0.02)
    assert sorted(written) == [("丙", "L3", "2026-10-03"), ("乙", "L2", "2026-10-02"),
                               ("甲", "L1", "2026-10-01")], f"三组都要写，实际 {written}"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd py && python -m pytest tests/test_fb_sheet_write.py -v -k "retry"`
Expected: FAIL —— 现有端点既不接受新入参形状、也不登记 `fb_report`

- [ ] **Step 3: 实现（替换 `fb_retry_sheets_sync` 整个函数体）**

```python
@fb_bp.route('/api/fb/reports/retry-sync', methods=['POST'])
@jwt_required()
@fb_required
def fb_retry_sheets_sync():
    """把该组（或多组）重新排一次写表。

    **登记前先重建一次**（纯 DB 读、不碰 Sheets）：重建失败就当场回**可操作**原因、
    **不登记** —— 因为 `sheet_write_log.error_msg` 会被统一换成固定文案（防泄露），
    可操作的原因到了那里就没了（design §4.2）。

    两种入参（**刻意不接受**客户端自己拆 `产品|线|日期` —— 名字含 `|` 会拆错）：
      单/多组：`{"groups": [[产品,线,日期], …]}`
      按既有失败行重试：`{"business_keys": [...]}` —— 三元组从该行的 `payload_json` 取
        （数据管理页汇总区的「重试全部失败的」走这条）
    """
    db = get_db()
    uid = get_uid()
    data = parse_body()

    triples = []
    if data.get("business_keys"):
        keys_in = list(data["business_keys"])
        marks = ",".join("?" for _ in keys_in)
        rows = db.execute(
            f"SELECT business_key, payload_json FROM sheet_write_log WHERE user_id=? "
            f"AND target='fb_report' AND business_key IN ({marks})",
            (uid, *keys_in)).fetchall()
        for r in rows:
            p = json.loads(r["payload_json"] or "{}")
            # ⚠️ 两种 payload 形状都要认：单组登记是扁平三要素；批量登记
            # （`run_write_many` 只收**一个** payload）是 {business_key: [产品,线,日期]} 映射。
            # 只认前者 ⇒ 批量失败的行永远重试不了（自审时抓到的坑）。
            tri = (p.get("groups") or {}).get(r["business_key"])
            if tri:
                triples.append(tuple(tri))
            elif p.get("product_name"):
                triples.append((p["product_name"], p.get("line_name"), p.get("report_date")))
    elif data.get("groups"):
        triples = [tuple(g) for g in data["groups"]]

    triples = [(p, l, d) for p, l, d in triples if p]
    if not triples:
        return err('缺少 groups 或 business_keys', 400)

    # 重建前置：不可重建的当场回原因，不进日志
    ok_groups, failed = [], []
    for p, l, d in triples:
        records, why = _rebuild_fb_records(db, uid, p, l, d)
        if records is None:
            failed.append({'product_name': p, 'line_name': l, 'report_date': d, 'error': why})
            continue
        ok_groups.append((p, l, d))

    if not ok_groups:
        # 单组形态沿用原来的「400 + 原因」，多组形态回 200 + failed[]（形状与改前一致）
        if len(triples) == 1:
            return err(failed[0]['error'], 400)
        return ok({'accepted': 0, 'failed': failed})

    import sheet_write
    import routes.fb_sheet_targets as _fbt

    keys = [_fbt.fb_report_key(p, l, d) for p, l, d in ok_groups]
    if len(ok_groups) == 1:
        p, l, d = ok_groups[0]
        payload = {"product_name": p, "line_name": l, "report_date": d}
        sheet_write.run_write(
            db, user_id=uid, platform="fb", target="fb_report", business_key=keys[0],
            sync_fn=sheet_write.build_sync("fb_report", uid, keys[0], payload),
            payload=payload)
    else:
        # `run_write_many` 只收**一个** payload ⇒ 三元组按 key 做成映射（design §Task 2）
        payload = {"groups": {_fbt.fb_report_key(p, l, d): [p, l, d]
                              for p, l, d in ok_groups}}
        sheet_write.run_write_many(
            db, user_id=uid, platform="fb", target="fb_report", business_keys=keys,
            sync_fn=_fbt.fb_report_many_sync(uid, ok_groups), payload=payload)

    return ok({'accepted': len(ok_groups), 'failed': failed})
```

同时：确认该路由的装饰器与路径**不变**（前端暂时仍打它，Task 4 才换）；删掉原来的
「同步直写 + 删行 + `error_msg`」逻辑（含 `retry_count` 自增那两段）。

- [ ] **Step 4: 跑测试确认通过**

Run: `cd py && python -m pytest tests/test_fb_sheet_write.py -v`
Expected: 6 passed

- [ ] **Step 5: 迁移 `test_fb_sheets_retry.py` 的判据（**语义不降**）**

该文件 5 条里：
- `test_retry_single_rebuilds_from_fb_ad_reports` → 改成打新入参（`product_name/line_name/report_date`），
  断言 `upsert_fb_reports` 收到正确的三元组与 records（**判据不变**）
- `test_retry_single_without_source_rows_returns_reason` → 断言 400 + 「找不到对应的原始数据」（**不变**）
- `test_retry_single_legacy_row_without_date_returns_reason` → 旧行没有日期 ⇒ 现在没有行可传日期，
  改为断言「传空 report_date ⇒ 400 + 缺少日期」（守住「缺日期必须给可操作原因」这条）
- `test_retry_batch_reports_unrebuildable_rows` → 改成 `{"groups": [...]}` 形态，
  断言 `failed[]` 里带 `error` 且含「缺少日期」
- `test_sheets_sync_log_has_retry_columns` → **保留原样**（表与列都还在）

Run: `cd py && python -m pytest tests/test_fb_sheets_retry.py -v`
Expected: 5 passed

- [ ] **Step 6: 提交**

```bash
git add py/routes/fb_routes.py py/tests/test_fb_sheet_write.py py/tests/test_fb_sheets_retry.py
git commit -m "feat(fb): 重试单条/批量改走统一治理（修请求线程直写阻塞）

原实现两支都在**请求线程里直接打 Google Sheets**：慢、超时、失败即 500 ——
违反「业务端点的响应不得因写表而阻塞或失败」。改为登记后立刻回「已受理」，
由后台线程写、失败落 retry_failed 可重试。

重建前置（design §4.2）：重建失败当场回**可操作**原因、不登记 ——
统一机制会把 error_msg 换成固定文案，可操作的原因到不了用户眼前。

批量走 run_write_many（一个线程 N 行日志）；它只收一个 payload，
故三元组做成 {business_key: [产品,线,日期]} 映射，避免拆 key 的歧义。"
```

---

### Task 3: 写点 ①（提取保存）改走统一入口 + FB 停写 `sheets_sync_log`

**Files:**
- Modify: `py/routes/fb_routes.py`（`_schedule_fb_sheets_write` + 其调用点 `:1751`）
- Test: `py/tests/test_fb_sheet_write.py`、`py/tests/test_fb_platform.py`

**Interfaces:**
- Consumes: Task 1 / 2 的 `fb_report_key`
- Produces: `_register_fb_report_write(uid, product_name, line_name, report_date)`；`/api/fb/extract/save` 响应从 `{saved, sync_log_id}` 改为 `{saved, business_key}`

- [ ] **Step 1: 写失败测试**

追加到 `py/tests/test_fb_sheet_write.py`：

```python
def test_extract_save_registers_fb_report_and_stops_writing_sync_log(client, monkeypatch):
    """提取保存：登记 fb_report，且**不再**写 sheets_sync_log（四期停写该表）。"""
    import google_sheets_service as gs
    monkeypatch.setattr(gs, "upsert_fb_reports", lambda *a, **k: None)

    hdr, uid = _fb_user(client, "_fbsw_ext")
    resp = client.post("/api/fb/extract/save", headers=hdr, json={
        "product_name": "产品甲", "line_name": "线A", "report_date": "2026-10-01",
        "records": [{"account_name": "名", "account_id": "acc_1", "cost": 1,
                     "impressions": 2, "clicks": 3, "registrations": 4,
                     "purchases": 5, "cost_per_purchase": 6}]})
    assert resp.status_code == 200, resp.get_data(as_text=True)[:300]
    key = resp.get_json()["business_key"]
    assert key == "产品甲|线A|2026-10-01", resp.get_json()

    db = database.get_db()
    r = _settle(db, uid, key)
    n_sync_log = db.execute("SELECT COUNT(*) FROM sheets_sync_log WHERE user_id=?",
                            (uid,)).fetchone()[0]
    db.close()
    assert r is not None, "提取保存必须登记 fb_report"
    assert r["status"] == "synced", f"实际 {r['status']}"
    assert n_sync_log == 0, f"FB 不得再写 sheets_sync_log，实际 {n_sync_log} 行"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd py && python -m pytest tests/test_fb_sheet_write.py -v -k extract`
Expected: FAIL —— 响应里没有 `business_key`，且 `sheets_sync_log` 有 1 行

- [ ] **Step 3: 实现**

把 `_schedule_fb_sheets_write`（整段，含自建 `threading.Thread`）替换为：

```python
def _register_fb_report_write(uid, product_name, line_name, report_date):
    """登记一次 FB 报告写表（四期：接入统一治理）。

    原先这里起一个自建 daemon 线程直写 Sheets，并把结果写进自己的
    `sheets_sync_log`；现在改为登记到 `sheet_write_log`，由统一机制写表、
    失败可查可重试。**FB 不再写 `sheets_sync_log`**（该表留给 GG 做表那条线）。

    `db` 用调用方（请求线程）的连接 —— 与三期的四个调用点同形：登记在请求线程
    完成，前端拿到响应就能查到这条记录。
    """
    import sheet_write
    import routes.fb_sheet_targets as _fbt

    key = _fbt.fb_report_key(product_name, line_name, report_date)
    payload = {"product_name": product_name, "line_name": line_name,
               "report_date": report_date}
    sheet_write.run_write(
        get_db(), user_id=uid, platform="fb", target="fb_report", business_key=key,
        sync_fn=sheet_write.build_sync("fb_report", uid, key, payload), payload=payload)
    return key
```

并把调用点（`:1751` 附近）改为：

```python
        business_key = _register_fb_report_write(uid, product_name, line_name, report_date)

        return ok({'saved': len(records), 'business_key': business_key})
```

**同时删掉**：那段「先插入一条 pending 同步日志并拿到 id」（`INSERT INTO sheets_sync_log …`
到 `log_id = …`）—— FB 不再写该表。注意 `db.commit()`（`fb_ad_reports` 的写入）必须保留，
且要在登记**之前**（登记会用同一个连接 `record_pending` → `commit`）。

> ⚠️ 常见坑：若把这个 `commit()` 删掉，`run_write` 会在**持有未提交写事务**的连接上
> 做 `record_pending`，另一条连接拿不到写锁 ⇒ 等满 `timeout=30` 抛 `database is locked`，
> 请求线程白冻 30 秒且日志行登记失败（三期在 `tt_accounts_routes` 修过两处同族缺陷）。

- [ ] **Step 4: 跑测试确认通过**

Run: `cd py && python -m pytest tests/test_fb_sheet_write.py -v`
Expected: 7 passed

- [ ] **Step 5: 迁移 `test_fb_platform.py` 的 E11 三条**

`TestE11FbSheets*` 那三条（约 `:655-725`）：
- `test_async_write_failure_sanitized` → 改为：mock `upsert_fb_reports` 抛错 →
  走 `/api/fb/extract/save` → 轮询 `/api/sheet-write/status?platform=fb&target=fb_report&business_key=…`
  断言 `status == 'retry_failed'`、`error_msg == sheet_write 的固定文案`（**不再**是
  `fb_routes._FB_SHEETS_FAILED_MSG` —— 统一文案变更，见 Commit 说明）、
  且 `"sheets.googleapis.com" in caplog.text`（**原文只进日志，这条判据必须保住**）
- 另外两条（单/批量重试的 sanitize）→ 同样改读统一 status
- `_FB_SHEETS_FAILED_MSG` 若已无引用则一并删除

Run: `cd py && python -m pytest tests/test_fb_platform.py -v -k "E11"`
Expected: 全绿

- [ ] **Step 6: 提交**

```bash
git add py/routes/fb_routes.py py/tests/test_fb_sheet_write.py py/tests/test_fb_platform.py
git commit -m "feat(fb): 提取保存改走统一治理；FB 停写 sheets_sync_log

- _schedule_fb_sheets_write（自建 daemon 线程）→ _register_fb_report_write（登记），
  唯一调用点与响应字段同步改：sync_log_id → business_key
- 不再插入 sheets_sync_log 的 pending 行（该表留给 GG 做表线，表与历史保留）
- 保留 fb_ad_reports 的 commit 且置于登记之前 —— 否则 run_write 会在持有未提交
  写事务的连接上 record_pending，撞 SQLite 单写者而冻满 30s（三期同族缺陷）

用户可见文案变化一处：写表失败的 error_msg 从 FB 自己的固定文案换成三期统一的
_WRITE_FAILED_MSG（防泄露的判据不变：原文只进日志）。"
```

---

### Task 4: 退役三个 FB 专属端点 + 前端 API 包装

> **执行顺序：本任务在 Task 5 / Task 6 之后做。**先换调用方，再删端点与包装。

**Files:**
- Modify: `py/routes/fb_routes.py`（删 `fb_last_sync` / `fb_sync_status_by_id` / `fb_sheets_sync_status`）
- Modify: `frontend/src/api/fb.js`（删三个包装）
- Test: `py/tests/test_fb_platform.py`（引用这三个端点的地方一并清理）

- [ ] **Step 1: 确认无人再依赖（先查再删）**

Run:
```bash
grep -rn "last-sync\|sync-status\|sheets-sync-status" frontend/src/ py/ --include=*.vue --include=*.js --include=*.py | grep -v node_modules
grep -rn "sheets_sync_log" py/ --include=*.py | grep -v tests
```
Expected：前端只剩 `FbDataExtract` 的 `getSyncStatus`（Task 5 换源）与 `FbDataManage` 的
`retrySheetsSync`（Task 6 换源）；后端 `sheets_sync_log` 只剩 `main.py`（GG 做表线）与 `database.py`。

- [ ] **Step 2: 删除三个端点与 `fb.js` 的三个包装**

删 `fb_last_sync` / `fb_sync_status_by_id` / `fb_sheets_sync_status` 三个函数及其 `@fb_bp.route` 装饰器；
`frontend/src/api/fb.js` 删 `retrySheetsSync` / `lastSyncStatus` / `getSyncStatus`。
（`getSyncStatus` / `retrySheetsSync` 的调用方在 Task 5/6 换源 —— **先做 Task 5/6 再删这两行**，
或删了立刻在同一提交里改前端调用方；本任务按「先换调用方、再删包装」的顺序执行。）

- [ ] **Step 3: 跑测试确认没有遗留引用**

Run: `cd py && python -m pytest tests/test_fb_platform.py tests/test_fb_sheets_retry.py -q`
Expected: 全绿（Task 2/3 已把判据迁到新路径）

- [ ] **Step 4: 提交**

```bash
git add py/routes/fb_routes.py frontend/src/api/fb.js
git commit -m "chore(fb): 退役三个 FB 专属同步端点 + 前端包装

/last-sync、/sync-status/<id>、/sheets-sync-status 全部退役；
fb.js 里对应三个包装（含零调用的 lastSyncStatus）一并删除。
前端改读三期的 /api/sheet-write/status（Task 5/6）。"
```

---

### Task 5: 前端 —— 提取页轮询换源

**Files:**
- Modify: `frontend/src/views/fb/FbDataExtract.vue`（`pollSyncStatus` 与保存后一段，约 `:245-270`）

**Interfaces:**
- Consumes: `sheetWriteApi.status({platform:'fb', target:'fb_report', businessKey})`；`sheetWriteHint` / `sheetWriteTone`（`@/utils/sheetWriteUi`）

- [ ] **Step 1: 换源**

把 `pollSyncStatus(syncLogId, attempt)` 改为按 **business_key** 轮询统一端点：

> **勘误（实现时改，2026-10-09）**：本段下面的 `MAX_ATTEMPTS = 15` **已改为 `40`**。
> 原因：换源后后端是「首次失败 → 中间态 `failed` → 睡 30s → 重试 → 终态」的状态机，
> **终态 `retry_failed` 最早 ~30s 才落库**；15s 会让「走了后端重试」的写表终态在本页
> **永不可观测**（旧代码 15s 够用，是因为旧后端把 `failed` 当**终态**当场弹）。
> 教训记于账本：**换掉一个「上游何时给终态」的数据源时，必须重估所有依赖该时序的常量**。
> 另同时**恢复**了被本段连带删掉的耗尽提示（「写表结果未返回，请稍后到「数据管理」页查看或重试」）。

```js
// 轮询本次写表结果：pending 则 1 秒后再查（**上限 40 次**，见上方勘误 —— 必须 > 后端 30s 重试窗口）。
// 四期起数据源换成统一的 /api/sheet-write/status（带 target 过滤，
// 防与同期其它 target 互相遮蔽）；终态文案复用全仓唯一文案源。
async function pollWriteStatus(businessKey, attempt = 0) {
  const MAX_ATTEMPTS = 40
  try {
    const r = await sheetWriteApi.status({
      platform: 'fb', target: 'fb_report', businessKey,
    })
    const it = r.item
    if (!it) return                       // 无记录 = 这条路径没触发写表
    if (it.target !== 'fb_report') return // 被遮蔽时误判成别的 target
    if (it.status === 'synced') return ElMessage.success('✅ 写表成功')
    if (it.status === 'pending' || it.status === 'failed') {
      if (attempt >= MAX_ATTEMPTS) return
      return setTimeout(() => pollWriteStatus(businessKey, attempt + 1), 1000)
    }
    // 需提示的终态：文案与汇总区/工具提示同源
    SHEET_WRITE_TOAST[sheetWriteTone(it.status)](sheetWriteHint(it))
  } catch { /* 查询失败不再打扰用户 */ }
}
```

保存后的调用改为：

```js
    if (res.business_key) pollWriteStatus(res.business_key)
```

imports 增补：`import { sheetWriteApi } from '../../api/sheetWrite'`、
`import { SHEET_WRITE_TOAST, sheetWriteTone, sheetWriteHint } from '@/utils/sheetWriteUi'`
（路径层数按该文件既有 import 风格对齐）。

- [ ] **Step 2: 构建验证**

Run: `cd frontend && npm run build`
Expected: exit 0

- [ ] **Step 3: 提交**

```bash
git add frontend/src/views/fb/FbDataExtract.vue
git commit -m "feat(fb-ui): 提取页写表轮询换源到统一状态接口

数据源从 getSyncStatus(sync_log_id) 换成 /api/sheet-write/status（按 business_key +
target 过滤）；终态文案复用 sheetWriteUi 的唯一文案源。"
```

---

### Task 6: 前端 —— 数据管理页失败汇总区 + 重试全部

**Files:**
- Modify: `frontend/src/views/fb/FbDataManage.vue`

**Interfaces:**
- Consumes: `sheetWriteApi.status({platform:'fb', target:'fb_report'})` / `.retry({platform:'fb', target:'fb_report', businessKey})`

- [ ] **Step 1: 照搬 T6 卡片已定稿的视觉方案**

模板（插在表格上方工具栏之后）：

```html
        <!-- 写表失败汇总（四期）。复用 T6 卡片已 /frontend-design 定稿的视觉语法：
             3px 琥珀左脊柱 + warning 色调（零回滚 ⇒ 只可能是 retry_failed，
             「表中未写入」不等于数据坏了）。有失败才渲染，无失败时连占位都没有。 -->
        <div v-if="fbSwFailures.length"
             style="background:var(--el-color-warning-light-9);border-left:3px solid var(--el-color-warning);border-radius:8px;padding:10px 12px;margin-bottom:12px;">
          <div style="font-weight:600;font-size:13px;color:#92400e;margin-bottom:6px;">
            ⚠️ {{ fbSwFailures.length }} 项没写进表
          </div>
          <div v-for="(f, i) in fbSwFailures" :key="f.business_key"
               :style="{ display:'flex', alignItems:'baseline', gap:'8px', padding:'5px 0',
                         borderTop: i ? '1px solid var(--el-color-warning-light-7)' : 'none' }">
            <el-tooltip placement="top" :content="sheetWriteHint(f)">
              <span style="font-family:monospace;font-size:12px;color:#374151;flex:none;max-width:45%;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">{{ f.business_key }}</span>
            </el-tooltip>
            <span style="font-size:12px;color:#6b7280;flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">{{ f.error_msg || '未知原因' }}</span>
            <el-button link size="small" :type="sheetWriteTone(f.status)"
                       @click="retryOne(f)">重试</el-button>
          </div>
          <div style="margin-top:8px;">
            <el-button size="small" @click="retryAll">重试全部失败的</el-button>
          </div>
        </div>
```

script（与该文件既有风格一致）：

```js
import { sheetWriteApi } from '../../api/sheetWrite'
import { sheetWriteTone, sheetWriteHint } from '@/utils/sheetWriteUi'

const FB_TARGET = 'fb_report'
const fbSwFailures = ref([])

async function loadFbSwFailures() {
  try {
    const res = await sheetWriteApi.status({ platform: 'fb', target: FB_TARGET })
    fbSwFailures.value = res.items || []
  } catch { /* 汇总拉不到不该打扰用户，保持上一次结果 */ }
}

async function retryOne(f) {
  try {
    await sheetWriteApi.retry({ platform: 'fb', target: FB_TARGET,
                                businessKey: f.business_key })
    ElMessage.success('已重新提交，请稍后查看结果')
    await loadFbSwFailures()
  } catch (e) { ElMessage.error(e.response?.data?.error || '重试失败') }
}

async function retryAll() {
  // 只回传 business_key 列表，**不拆 `产品|线|日期`**（名字含 `|` 会拆错）；
  // 三元组由端点从各行的 payload_json 取（Task 2 已支持）。
  try {
    const res = await fbApi.retrySheetsSync({
      business_keys: fbSwFailures.value.map(f => f.business_key),
    })
    ElMessage.success(`已重新提交 ${res.accepted || 0} 项，请稍后查看结果`)
    await loadFbSwFailures()
  } catch (e) { ElMessage.error(e.response?.data?.error || '重试失败') }
}

onMounted(() => { loadFbSwFailures() })
```

- [ ] **Step 2: `retrySheetsSync` 的入参改为可传 body**

`frontend/src/api/fb.js`：`retrySheetsSync(body = {}) { return client.post('/fb/reports/retry-sync', body) }`

- [ ] **Step 3: 构建验证**

Run: `cd frontend && npm run build`
Expected: exit 0

- [ ] **Step 4: 人工验证清单（写进报告，交用户执行）**

1. 提取保存后 → 提取页应弹「✅ 写表成功」
2. 把该用户的 Google 表格配置改坏 / mock 失败 → 再提取一次 → 数据管理页**应出现失败项**
3. 点失败项的「重试」→ 恢复配置后应转成功、汇总区消失
4. 无失败时汇总区**不应出现**
5. 「重试全部失败的」一次覆盖多组 → 各组都要写（不是只写第一组）

- [ ] **Step 5: 提交**

```bash
git add frontend/src/views/fb/FbDataManage.vue frontend/src/api/fb.js
git commit -m "feat(fb-ui): 数据管理页显示写表失败汇总 + 重试

复用 T6 卡片已定稿的视觉方案（3px 琥珀左脊柱 + warning 色调 + sheetWriteUi 文案源），
按 (产品,线,日期) 列出失败项、逐条重试、并支持「重试全部失败的」。"
```

---

### Task 7: 收尾回归

- [ ] **Step 1: 全量**

Run: `cd py && python -m pytest tests/ -q`
Expected: 全绿（预计 1776 + 本期新增约 8 条）

- [ ] **Step 2: 前端**

Run: `cd frontend && npm test && npm run build`
Expected: 20 passed；exit 0

- [ ] **Step 3: 变异验证（规格 §6 点名的两条）**

1. 把 `fb_report_many_sync` 里的 `for … in groups` 改成只写第一组 ⇒
   `test_retry_batch_covers_every_group` 必须红；贴出断言原文后**还原**
2. 去掉端点里的「重建前置」（不可重建的行照样登记）⇒
   `test_retry_single_registers_and_rebuild_failure_does_not` 必须红；贴出断言原文后**还原**

- [ ] **Step 4: 独立审查 + 交付**

派独立审查员（对抗性，逐条变异验证）；通过后提醒用户**重启 Flask**（后端有实质改动）
并跑 Task 6 Step 4 的人工清单；推 origin 需用户单独确认。
