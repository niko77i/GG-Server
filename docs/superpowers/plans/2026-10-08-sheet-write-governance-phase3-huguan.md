# 写表失败统一治理（三期：户管看板域接入）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把户管看板域最后 5 个「只写日志」写表点接入一期的统一治理机制（合并为 4 个 target），使其最终失败产生带原因的持久记录、可提示、可重试；**不做业务回滚**（全镜像类）。

**Architecture:** 新增 `py/routes/huguan_sheet_targets.py` 注册 4 个 target（rebuild 一律从 DB 重算）；5 个点位改走 `sheet_write.run_write` / `run_write_many`；`/api/sheet-write/status` 加 `target` 参数（**本期必需**，防同一 account_id 跨 target 互相遮蔽）；前端三处落点复用二期已确认的视觉方案。

**Tech Stack:** Python 3.11 / Flask / SQLite(WAL) / pytest；前端 Vue 3 `<script setup>` + Element Plus。

**规格来源:** `docs/superpowers/specs/2026-10-08-sheet-write-governance-phase3-huguan-design.md`（下称「规格」）

## Global Constraints

- 写表**保持异步**；业务端点的响应不得因写表而阻塞或失败。
- 提示**只在最终结果产生时**发出 —— `pending` / `failed` / `synced` 不得触发任何用户可见提示或标记；只有 `retry_failed` / `rolled_back` / `rollback_abandoned` 三个终态才显示。
- 状态值固定 6 个，不得增删。**本期所有 target 一律不注册 `rollback`**（全镜像类），最终失败落 `retry_failed`。
- `target` 一律用**稳定英文 token**：`huguan_dashboard` / `huguan_owner_channel` / `operator_dashboard_remark` / `huguan_fb_acceptor`。
- **`sheet_write_log.user_id` = 表主人**（不是操作者）—— 本期与二期的一处**有意差异**（规格 §3.5）。除 `operator_dashboard_remark` 外，其余 3 个 target 的表主人 == 触发者。
- **后台线程内禁止使用请求线程的 SQLite 连接**，一律 `database.get_db()` 新建；**禁止**在请求线程预先 `build_service()` 再传进线程。
- `run_write` / `run_write_many` 的签名与实现**一字不改**（一期已审）。
- `err(msg, code)` 才是正确写法；**禁止** `return err(msg), code`。
- 本仓库常有并行会话在改文件：**禁止 `git add -A`**，一律 `git add <显式路径>`。
- 不启动/重启任何**常驻服务进程**；`npm run build` 是一次性构建，允许。

### 测试红线（一、二期各踩过多次的坑，本期必须避开）

1. **`time.sleep` 陷阱**：测试若 monkeypatch 全局 `time.sleep` 跳过 30s 重试，**必须**用模块顶部抓的真 sleep 轮询（`from time import sleep as _poll_sleep`）。在 test 体内、patch **之后**再 import 会绑到桩函数 ⇒ 主线程不让出 GIL、断言早于回调 ⇒ 恒失败（一期三次、二期两次都栽在这）。
2. **断言必须具判别力**：写完每条测试后，问「被测代码坏了这条会不会红？」；**实施时对最重要的两条做一次变异验证**（改坏 → 确认红 → 还原），把失败的断言原文写进报告。
3. `run_write_many` 的 `sync_fn` **只执行一次** —— 传给它的工厂必须覆盖全部 N 键（用 `build_many_sync` 形态），拿单键工厂会让只有第一户被写而 N 行全落 `synced`（二期踩过）。

---

## File Structure

| 文件 | 动作 | 职责 |
|---|---|---|
| `py/routes/sheet_write_routes.py` | 修改 | `/status` 加 `target` 查询参数（向后兼容） |
| `frontend/src/api/sheetWrite.js` | 修改 | `status()` 增加 `target` 透传 |
| `py/routes/huguan_sheet_targets.py` | **新建** | 4 个 target 的直写函数 + rebuild + 注册 |
| `py/main.py` | 修改 | 点位 #1 改走统一入口；顶层 import 注册 target |
| `py/huguan_dashboard.py` | 修改 | 点位 #2 / #3 / #4 改走统一入口 |
| `py/routes/huguan_dashboard_routes.py` | 修改 | 点位 #5 改走统一入口；`_write_background` 增加 `user_id` 形参 |
| `py/tests/test_huguan_sheet_write.py` | **新建** | 4 个 target + 5 个点位的接线用例 |
| `frontend/src/views/fb/FbAccountPanel.vue` | 修改 | 新增「写表」列（照搬二期 TT 方案） |
| `frontend/src/components/HuguanDashboardCard.vue` | 修改 | 失败汇总 + 重试（**新增 UI**） |

---

### Task 1: `/api/sheet-write/status` 加 `target` 参数

**Files:**
- Modify: `py/routes/sheet_write_routes.py`（`sheet_write_status`，约 :26-60）
- Modify: `frontend/src/api/sheetWrite.js`
- Test: `py/tests/test_sheet_write.py`

**Interfaces:**
- Produces: `GET /api/sheet-write/status?platform=&target=&business_key=` —— `target` 可选；**不传时行为与现在完全一致**（向后兼容，不打断一期 TT / 二期 GG 的前端）

- [ ] **Step 1: 写失败测试**

追加到 `py/tests/test_sheet_write.py`：

```python
def test_status_target_param_disambiguates_same_business_key(client):
    """同一 business_key 跨 target 时必须能各取各的 —— 不给 target 就只回最新一行。

    这是三期**必需**的改动：4 个 target 的 business_key 都是 account_id，
    同一账户同时有 huguan_dashboard 与 operator_dashboard_remark 两条是正常的。
    不过滤 ⇒ 一个 target 的行遮住另一个 ⇒ **静默漏报**。
    去掉 `if target:` 过滤 ⇒ 本用例红。
    """
    client.post("/api/auth/register", json={"username": "_swtgt", "password": "test123"})
    db = database.get_db()
    db.execute("UPDATE users SET platform='tt' WHERE username='_swtgt'")
    db.commit()
    uid = db.execute("SELECT id FROM users WHERE username='_swtgt'").fetchone()["id"]
    for tgt in ("huguan_dashboard", "operator_dashboard_remark"):
        db.execute(
            "INSERT INTO sheet_write_log (user_id, platform, target, business_key, status) "
            "VALUES (?, 'tt', ?, 'acc_same', 'retry_failed')", (uid, tgt))
    db.commit()
    db.close()
    hdr = {"Authorization": "Bearer " + client.post(
        "/api/auth/login", json={"username": "_swtgt", "password": "test123"}
    ).get_json()["access_token"]}

    # 不带 target：只回最新一行（列表标记用）
    r0 = client.get("/api/sheet-write/status?platform=tt&business_key=acc_same", headers=hdr)
    assert r0.get_json()["item"]["target"] in ("huguan_dashboard", "operator_dashboard_remark")

    # 带 target：精确取该 target 的行（被遮蔽即红）
    for tgt in ("huguan_dashboard", "operator_dashboard_remark"):
        r = client.get(f"/api/sheet-write/status?platform=tt&target={tgt}"
                       "&business_key=acc_same", headers=hdr)
        assert r.status_code == 200, r.get_data(as_text=True)[:200]
        item = r.get_json()["item"]
        assert item is not None, f"带 target={tgt} 应能取到该行（被遮蔽即红）"
        assert item["target"] == tgt, f"取到了别的 target 的行：{item}"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd py && python -m pytest tests/test_sheet_write.py::test_status_target_param_disambiguates_same_business_key -v`
Expected: FAIL —— 带 target 时取到的仍是「最新一行」而非指定那条（或 item 为 None）

- [ ] **Step 3: 实现**

在 `py/routes/sheet_write_routes.py` 的 `sheet_write_status` 取参处加：

```python
    # 三期新增：按 target 过滤。4 个 target 的 business_key 都是 account_id，
    # 同一账户同时有两条（如 huguan_dashboard + operator_dashboard_remark）正常；
    # 不过滤会让一个 target 的行遮住另一个 ⇒ 静默漏报。
    # **不传时行为与改动前完全一致**（向后兼容一期 TT / 二期 GG 的前端）。
    target = (request.args.get("target") or "").strip()
```

并在拼 SQL 处、`business_key` 判断**之前**插入：

```python
    if target:
        sql += " AND target=?"
        params.append(target)
```

- [ ] **Step 4: 前端 api 透传**

`frontend/src/api/sheetWrite.js` 的 `status` 改为：

```js
  status({ platform, target, businessKey } = {}) {
    const params = { platform }
    if (target) params.target = target
    if (businessKey) params.business_key = businessKey
    return client.get('/sheet-write/status', { params })
  },
```

- [ ] **Step 5: 跑测试确认通过**

Run: `cd py && python -m pytest tests/test_sheet_write.py -q`
Expected: 全部通过（含既有用例 —— 它们不传 target，行为必须不变）

- [ ] **Step 6: 提交**

```bash
git add py/routes/sheet_write_routes.py py/tests/test_sheet_write.py frontend/src/api/sheetWrite.js
git commit -m "feat(sheet-write): /status 增加 target 参数，防同一 account_id 跨 target 互相遮蔽

三期 4 个 target 的 business_key 全是 account_id，同一账户同时有
huguan_dashboard 与 operator_dashboard_remark 两条是正常的。该端点只回最新一行
⇒ 一个 target 的行会遮住另一个，静默漏报（二期记为「今日不可达」是因为当时
键格式不相交，三期不再成立）。

不传 target 时行为与改动前完全一致，不打断一期 TT / 二期 GG 的前端。"
```

---

### Task 2: 4 个 target 的注册与 rebuild

**Files:**
- Create: `py/routes/huguan_sheet_targets.py`
- Modify: `py/main.py`（顶层 import 以注册 target）
- Test: `py/tests/test_huguan_sheet_write.py`

**Interfaces:**
- Consumes: `sheet_write.register_target(name, rebuild, rollback=None)`；`huguan_dashboard` 的 `get_platform_config` / `collect_rows_for_push` / `owner_channel_cells` / `KEY_COL`
- Produces（模块级函数，后续任务调用）:
  - `huguan_dashboard_sync(user_id, platform, account_ids) -> None`
  - `huguan_dashboard_many_sync(user_id, platform, business_keys) -> Callable[[], None]`
  - `huguan_owner_channel_sync(user_id, platform, account_id, value) -> None`
  - `huguan_fb_acceptor_sync(user_id, platform, account_id, note) -> None`
  - `operator_dashboard_remark_sync(owner_id, account_id, value) -> None`
  - 模块导入即注册 4 个 target

- [ ] **Step 1: 写失败测试**

新建 `py/tests/test_huguan_sheet_write.py`：

```python
"""户管看板域写表点接入统一治理 —— 端到端测试。

守卫两件事：(1) 每次触发都登记正确的 target 与 business_key；
(2) 最终失败落 retry_failed（全镜像类，**不得**出现 rolled_back）。

⚠️ 轮询必须用**模块顶层**捕获的真 sleep（下）：测试里 monkeypatch 的是全局
`time.sleep`（跳过 30s 重试），轮询循环自己也调 sleep —— 在 patch 之后再
`from time import sleep` 会拿到桩函数，主线程不让出 GIL、断言提前开火。
"""
import json
from time import sleep as _poll_sleep

import database
import sheet_write


def _tt_huguan(client, username):
    client.post("/api/auth/register", json={"username": username, "password": "test123"})
    db = database.get_db()
    db.execute("UPDATE users SET platform='tt', role='huguan' WHERE username=?", (username,))
    db.commit()
    uid = db.execute("SELECT id FROM users WHERE username=?", (username,)).fetchone()["id"]
    db.close()
    resp = client.post("/api/auth/login", json={"username": username, "password": "test123"})
    return {"Authorization": f"Bearer {resp.get_json().get('access_token', '')}"}, uid


def _mk_huguan_conf(db, uid, platform="tt"):
    """给该户管配好看板表格，使各点位不提前 return。"""
    db.execute("INSERT OR REPLACE INTO config (key, value) VALUES (?, ?)",
               (f"huguan_dashboard_{uid}",
                json.dumps({platform: {"spreadsheet_id": "SHEET_X", "sheet_name": "看板"}})))
    db.commit()


def _row(db, uid, target, key):
    return db.execute("SELECT * FROM sheet_write_log WHERE user_id=? AND target=? "
                      "AND business_key=?", (uid, target, key)).fetchone()


def _settle(db, uid, target, key, tries=300):
    for _ in range(tries):
        r = _row(db, uid, target, key)
        if r is not None and r["status"] in sheet_write.TERMINAL:
            return r
        _poll_sleep(0.02)
    return _row(db, uid, target, key)


def test_all_four_targets_registered():
    """4 个 target 必须都已注册（模块导入即注册；漏 import 就全 500）。"""
    import routes.huguan_sheet_targets  # noqa: F401
    for t in ("huguan_dashboard", "huguan_owner_channel",
              "operator_dashboard_remark", "huguan_fb_acceptor"):
        assert t in sheet_write.TARGETS, f"target 未注册: {t}"


def test_huguan_dashboard_sync_writes_all_n(client, monkeypatch):
    """整行刷新：N 户都要被写进表（守卫「只写第一户」那类静默漏写）。"""
    import google_sheets_service as gs
    import routes.huguan_sheet_targets as tgt
    written = []
    monkeypatch.setattr(gs, "build_service", lambda _p: object())
    monkeypatch.setattr(gs, "update_rows_by_account_id",
                        lambda svc, sid, name, rows, key_col=None: written.extend(rows))

    h, uid = _tt_huguan(client, "_hg_many")
    db = database.get_db()
    _mk_huguan_conf(db, uid)
    for i in (1, 2, 3):
        db.execute("INSERT INTO tt_accounts (advertiser_id, name, owner_id) VALUES (?,?,?)",
                   (f"hg_adv_{i}", f"hg_adv_{i}", uid))
    db.commit()
    db.close()

    tgt.huguan_dashboard_sync(uid, "tt", ["hg_adv_1", "hg_adv_2", "hg_adv_3"])
    assert {w["account_id"] for w in written} == {"hg_adv_1", "hg_adv_2", "hg_adv_3"}, \
        f"三户都必须被写进表，实际 {written}"


def test_huguan_dashboard_final_failure_lands_retry_failed(client, monkeypatch):
    """最终失败落 retry_failed（**不是** rolled_back）—— 零回滚守卫。"""
    import google_sheets_service as gs
    import time as _time
    monkeypatch.setattr(_time, "sleep", lambda _s: None)
    monkeypatch.setattr(gs, "build_service", lambda _p: object())

    def _boom(*a, **k):
        raise RuntimeError("Sheets 配额超限")

    monkeypatch.setattr(gs, "update_rows_by_account_id", _boom)

    h, uid = _tt_huguan(client, "_hg_fail")
    db = database.get_db()
    _mk_huguan_conf(db, uid)
    db.execute("INSERT INTO tt_accounts (advertiser_id, name, owner_id) "
               "VALUES ('hg_f1','hg_f1',?)", (uid,))
    db.commit()

    sync_fn = sheet_write.build_sync("huguan_dashboard", uid, "hg_f1", {"platform": "tt"})
    sheet_write.run_write(db, user_id=uid, platform="tt", target="huguan_dashboard",
                          business_key="hg_f1", sync_fn=sync_fn, payload={"platform": "tt"})
    r = _settle(db, uid, "huguan_dashboard", "hg_f1")
    db.close()

    assert r is not None, "必须登记日志行"
    assert r["status"] == "retry_failed", f"应落 retry_failed，实际 {r['status']}"
    assert r["status"] not in ("rolled_back", "rollback_abandoned"), "镜像类不得回滚"


def test_operator_remark_log_row_belongs_to_table_owner(client, monkeypatch):
    """#2 是唯一真正的第三方：日志行必须记在**表主人（投手）**名下，不是操作者。

    这是本期与二期的一处**有意差异**（规格 §3.5）——去掉「传 owner_id 作 user_id」
    就会记到操作者名下 ⇒ 表主人永远看不到自己的表没同步上。
    """
    import google_sheets_service as gs
    monkeypatch.setattr(gs, "build_service", lambda _p: object())
    monkeypatch.setattr(gs, "update_rows_by_account_id", lambda *a, **k: None)

    h_op, op_uid = _tt_huguan(client, "_hg_rm_op")
    db = database.get_db()
    client.post("/api/auth/register", json={"username": "_hg_rm_owner", "password": "test123"})
    owner_uid = db.execute("SELECT id FROM users WHERE username='_hg_rm_owner'").fetchone()["id"]
    db.execute("UPDATE users SET platform='tt' WHERE id=?", (owner_uid,))
    db.execute("INSERT INTO tt_accounts (advertiser_id, name, owner_id, remark) "
               "VALUES ('hg_r1','hg_r1',?, '备注X')", (owner_uid,))
    db.commit()

    sync_fn = sheet_write.build_sync("operator_dashboard_remark", owner_uid, "hg_r1", {})
    sheet_write.run_write(db, user_id=owner_uid, platform="tt",
                          target="operator_dashboard_remark",
                          business_key="hg_r1", sync_fn=sync_fn)
    r = _settle(db, owner_uid, "operator_dashboard_remark", "hg_r1")
    # 反证：不该记在操作者名下
    wrong = _row(db, op_uid, "operator_dashboard_remark", "hg_r1")
    db.close()

    assert r is not None, "日志行必须记在**表主人**名下"
    assert wrong is None, "不得记在操作者名下（那就没人能看见/重试了）"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd py && python -m pytest tests/test_huguan_sheet_write.py -v`
Expected: FAIL —— `target 未注册: huguan_dashboard`（或 `ModuleNotFoundError: routes.huguan_sheet_targets`）

- [ ] **Step 3: 创建 `py/routes/huguan_sheet_targets.py`**

```python
"""户管看板域的写表目标（三期）。

设计见 docs/superpowers/specs/2026-10-08-sheet-write-governance-phase3-huguan-design.md

全部是**镜像类**（表 = 系统状态的投影）⇒ 一律不注册 `rollback`，最终失败落 `retry_failed`。
rebuild 一律**从 DB 重算**，不重放快照。

⚠️ `sheet_write_log.user_id` 记的是**表主人**（规格 §3.5）：除
`operator_dashboard_remark` 外，其余三个 target 的表主人 == 触发者（这些操作只有户管会做）。

线程约束：所有 service 与 DB 连接都在**函数/闭包内**新建 —— 这些代码会在后台线程里跑，
sqlite 连接与 httplib2 客户端都不可跨线程复用。
"""
import sheet_write


# ---------- target: huguan_dashboard（整行刷新；覆盖点位 #1 与 #5 的 :159/:171/:180） ----------

def huguan_dashboard_sync(user_id, platform, account_ids):
    """把这些账户的**整行**刷新到该户管的看板。

    重建走 `collect_rows_for_push` —— 与既有 `push_rows` 同一条路径。
    `cells_for_row` 只产出系统拥有的可写列，**刻意不含**归属变更通道列（规格 §7.2 规则 2），
    故不会碰到户管用公式维护的列。
    """
    import database
    import google_sheets_service as gs
    import huguan_dashboard as hd
    from main import _GOOGLE_SHEETS_CONFIG

    db = database.get_db()
    try:
        conf = hd.get_platform_config(db, user_id, platform)
        if not conf["spreadsheet_id"] or not conf["sheet_name"]:
            raise RuntimeError("该看板未配置表格 ID 或工作表名")
        rows = hd.collect_rows_for_push(db, platform, list(account_ids))
    finally:
        db.close()
    if not rows:
        raise RuntimeError("找不到对应账户，无法重建看板行")

    service = gs.build_service(_GOOGLE_SHEETS_CONFIG["credentials_path"])
    gs.update_rows_by_account_id(service, conf["spreadsheet_id"],
                                 conf["sheet_name"], rows, key_col=hd.KEY_COL[platform])


def huguan_dashboard_many_sync(user_id, platform, business_keys):
    """**首跑**用：一次覆盖 N 户。

    `run_write_many` 的 `sync_fn` 只执行**一次**；拿单户工厂顶上会让只有第一户被写进表
    而 N 行全落 synced（静默漏写，二期踩过）。
    """
    keys = list(business_keys)

    def _sync():
        huguan_dashboard_sync(user_id, platform, keys)

    return _sync


def _huguan_dashboard_rebuild(user_id, business_key, payload):
    platform = (payload or {}).get("platform")
    if not platform:
        raise RuntimeError("payload 缺 platform，无法重建看板行")

    def _sync():
        huguan_dashboard_sync(user_id, platform, [business_key])

    return _sync


# ---------- target: huguan_owner_channel（通道列；覆盖点位 #3 与 #5 的 :165） ----------

def huguan_owner_channel_sync(user_id, platform, account_id, value):
    """写归属变更通道列（GG=H / TT=L）。`value` 为空串即清空该格。"""
    import database
    import google_sheets_service as gs
    import huguan_dashboard as hd
    from main import _GOOGLE_SHEETS_CONFIG

    db = database.get_db()
    try:
        conf = hd.get_platform_config(db, user_id, platform)
        if not conf["spreadsheet_id"] or not conf["sheet_name"]:
            raise RuntimeError("该看板未配置表格 ID 或工作表名")
        rows = hd.owner_channel_cells([{"account_id": account_id}], platform, value)
    finally:
        db.close()
    if not rows:
        raise RuntimeError("无法构造通道列待写行")

    service = gs.build_service(_GOOGLE_SHEETS_CONFIG["credentials_path"])
    gs.update_rows_by_account_id(service, conf["spreadsheet_id"], conf["sheet_name"], rows)


def _huguan_owner_channel_rebuild(user_id, business_key, payload):
    """`payload` 需带 `platform` 与 `mode`：

      * mode="clear" → 清空该格（点位 #5 的 :165）
      * mode="owner" → 从 DB 读回该账户的归属留痕（点位 #3）
          - gg：`accounts.owner_id` → `users` 的名字（**可重算**）
          - tt：`tt_accounts.owner_change_note`（**读回**——旧归属名与「月.日」无法从
            当前 DB 重算，但该串在写表前已落库；注意它是**单值列**，会被后续换绑覆盖）
    """
    p = payload or {}
    platform = p.get("platform")
    mode = p.get("mode")
    if not platform or mode not in ("clear", "owner"):
        raise RuntimeError("payload 需带 platform 与 mode(clear|owner)")

    def _sync():
        if mode == "clear":
            huguan_owner_channel_sync(user_id, platform, business_key, "")
            return
        import database
        db = database.get_db()
        try:
            if platform == "tt":
                r = db.execute(
                    "SELECT owner_change_note FROM tt_accounts WHERE advertiser_id=?",
                    (business_key,)).fetchone()
                value = (r["owner_change_note"] if r else "") or ""
            else:
                r = db.execute(
                    "SELECT COALESCE(NULLIF(u.display_name, ''), u.username, '') AS n "
                    "FROM accounts a LEFT JOIN users u ON a.owner_id = u.id "
                    "WHERE a.account_id = ?", (business_key,)).fetchone()
                value = (r["n"] if r else "") or ""
        finally:
            db.close()
        huguan_owner_channel_sync(user_id, platform, business_key, value)

    return _sync


# ---------- target: operator_dashboard_remark（点位 #2；唯一真正的第三方） ----------

def operator_dashboard_remark_sync(owner_id, account_id, value):
    """写**投手看板**的 J 列（备注）。表主人 = `owner_id`（账户 owner）。"""
    import database
    import google_sheets_service as gs
    import huguan_dashboard as hd
    from main import _GOOGLE_SHEETS_CONFIG

    db = database.get_db()
    try:
        row = db.execute("SELECT value FROM tags WHERE key='tt_sheet_id'").fetchone()
        sheet_id = (row["value"] if row else "") or ""
        if not sheet_id:
            raise RuntimeError("未配置 TT 表格 ID，无法写投手看板")
        sheet_name = hd._operator_dashboard_name(db, owner_id)
    finally:
        db.close()

    service = gs.build_service(_GOOGLE_SHEETS_CONFIG["credentials_path"])
    gs.update_rows_by_account_id(service, sheet_id, sheet_name,
                                 [{"account_id": account_id, "cells": {"J": value}}],
                                 key_col="D")


def _operator_dashboard_remark_rebuild(user_id, business_key, payload):
    """重建：J 列内容 = `tt_accounts.remark`（两条调用路径都在写表前落库）。"""
    def _sync():
        import database
        db = database.get_db()
        try:
            r = db.execute("SELECT remark FROM tt_accounts WHERE advertiser_id=?",
                           (business_key,)).fetchone()
            value = (r["remark"] if r else "") or ""
        finally:
            db.close()
        operator_dashboard_remark_sync(user_id, business_key, value)

    return _sync


# ---------- target: huguan_fb_acceptor（点位 #4） ----------

def huguan_fb_acceptor_sync(user_id, platform, account_id, note):
    """写 FB 接户运营列（I 列）。"""
    import database
    import google_sheets_service as gs
    import huguan_dashboard as hd
    from main import _GOOGLE_SHEETS_CONFIG

    db = database.get_db()
    try:
        conf = hd.get_platform_config(db, user_id, platform)
        if not conf["spreadsheet_id"] or not conf["sheet_name"]:
            raise RuntimeError("该看板未配置表格 ID 或工作表名")
        rows = hd._fb_acceptor_cells([{"account_id": account_id}], note)
    finally:
        db.close()
    if not rows:
        raise RuntimeError("无法构造 FB 接户运营待写行")

    service = gs.build_service(_GOOGLE_SHEETS_CONFIG["credentials_path"])
    gs.update_rows_by_account_id(service, conf["spreadsheet_id"], conf["sheet_name"], rows,
                                 key_col=hd.KEY_COL[platform])


def _huguan_fb_acceptor_rebuild(user_id, business_key, payload):
    """重建：I 列内容 = `fb_accounts.acceptor`（三条路径都在写表前落库）。"""
    def _sync():
        import database
        db = database.get_db()
        try:
            r = db.execute("SELECT acceptor FROM fb_accounts WHERE account_id=?",
                           (business_key,)).fetchone()
            note = (r["acceptor"] if r else "") or ""
        finally:
            db.close()
        if not note:
            return          # 与原实现一致：note 为空时早退（不写）
        huguan_fb_acceptor_sync(user_id, "fb", business_key, note)

    return _sync


# ---------- 注册（模块导入即生效） ----------

sheet_write.register_target("huguan_dashboard", rebuild=_huguan_dashboard_rebuild)
sheet_write.register_target("huguan_owner_channel", rebuild=_huguan_owner_channel_rebuild)
sheet_write.register_target("operator_dashboard_remark",
                            rebuild=_operator_dashboard_remark_rebuild)
sheet_write.register_target("huguan_fb_acceptor", rebuild=_huguan_fb_acceptor_rebuild)
```

> ⚠️ **实现前必须先读现场核对的四处**（不要照抄了事）：
> 1. `hd._operator_dashboard_name` / `hd._fb_acceptor_cells` 的**实际名字与签名**（带下划线的是内部函数 —— 确认名字、参数顺序，必要时与现场一致地调用）。
> 2. `hd.owner_channel_cells` 的**实参顺序**（是 `(rows, platform, value)` 还是别的）。
> 3. `hd.collect_rows_for_push` 是否已支持 `platform="fb"`（一期只支持 gg/tt；二期或并行会话可能已扩）。**若不支持 fb**，则 #4/#5 的 fb 分支需另行处理，**停下来报告**而不是自己发明。
> 4. `tt_accounts.owner_change_note` 列确实存在（二期并行会话加的）。
> **任何一处与本文不符 → 按现场改，并在报告里写明改了什么、为什么。**

- [ ] **Step 4: 顶层 import 注册**

在 `py/main.py` 中二期加的 `import routes.gg_recharge_sheet` 附近，同样加一行：

```python
import routes.huguan_sheet_targets  # noqa: F401  —— 注册户管看板域的 4 个写表目标
```

> **不 import 就不注册**，失败形态是调用点 `build_sync` 抛 `KeyError` ⇒ HTTP 500（二期为此专门核过一次）。

- [ ] **Step 5: 跑测试确认通过**

Run: `cd py && python -m pytest tests/test_huguan_sheet_write.py -v`
Expected: 4 passed

- [ ] **Step 6: 变异验证（必做）**

把 `huguan_dashboard_many_sync` 里的 `keys = list(business_keys)` 改成 `keys = list(business_keys)[:1]`，
跑 `test_huguan_dashboard_sync_writes_all_n`，确认**红**；然后**还原**。
把失败的断言原文写进报告。

- [ ] **Step 7: 提交**

```bash
git add py/routes/huguan_sheet_targets.py py/main.py py/tests/test_huguan_sheet_write.py
git commit -m "feat(huguan): 户管看板域 4 个写表 target（零回滚）

- huguan_dashboard：整行刷新（合并点位 #1 push_rows 与 #5 的 :159/:171/:180
  —— 勘察发现二者写的是同一张表的同一批列）
- huguan_owner_channel：通道列（点位 #3 + #5 的 :165；该列被 cells_for_row
  刻意排除，故必须单列 target）
- operator_dashboard_remark：投手看板 J 列（点位 #2，唯一真正的第三方）
- huguan_fb_acceptor：FB 接户运营 I 列（点位 #4）

全部镜像类 ⇒ 不注册 rollback；rebuild 一律从 DB 重算。
user_id 记**表主人**（规格 §3.5，本期与二期的一处有意差异）。"
```

---

### Task 3: 点位 #1 / #5 接入（`huguan_dashboard` target）

**Files:**
- Modify: `py/huguan_dashboard.py`（`push_rows` 内，约 :1513-1526）
- Modify: `py/routes/huguan_dashboard_routes.py`（`_write_background` :425-452 及其 4 个调用点 :159/:165/:171/:180）
- Test: `py/tests/test_huguan_sheet_write.py`

**Interfaces:**
- Consumes: `routes.huguan_sheet_targets.huguan_dashboard_sync` / `huguan_dashboard_many_sync`
- Produces: `_write_background(conf, rows, platform, user_id)` —— **签名新增 `user_id`**（表主人），4 个调用点都要传

**关键约束**

- 点位 #1 是 `writeback_rows` → `push_rows` 的链路（**15 个调用点**都经 `writeback_rows`）。
  改 `push_rows` 一处即可覆盖全部。
- 点位 #5 的 `_write_background` **签名里没有 `uid`** —— 必须新增形参，否则记不到表主人。
- **#5 的 :165（清空通道列）走 `huguan_owner_channel` target，不是 `huguan_dashboard`**
  （通道列被 `cells_for_row` 排除，全行刷新碰不到它）。

- [ ] **Step 1: 写失败测试**

追加到 `py/tests/test_huguan_sheet_write.py`：

```python
def test_writeback_rows_registers_huguan_dashboard(client, monkeypatch):
    """点位 #1：`writeback_rows` 必须登记 huguan_dashboard（原实现只写日志）。"""
    import google_sheets_service as gs
    import huguan_dashboard as hd
    monkeypatch.setattr(gs, "build_service", lambda _p: object())
    monkeypatch.setattr(gs, "update_rows_by_account_id", lambda *a, **k: None)

    h, uid = _tt_huguan(client, "_hg_p1")
    db = database.get_db()
    _mk_huguan_conf(db, uid)
    db.execute("INSERT INTO tt_accounts (advertiser_id, name, owner_id) "
               "VALUES ('hg_p1_a','hg_p1_a',?)", (uid,))
    db.commit()
    db.close()

    hd.writeback_rows(uid, "tt", ["hg_p1_a"])

    db = database.get_db()
    r = _settle(db, uid, "huguan_dashboard", "hg_p1_a")
    db.close()
    assert r is not None, "writeback_rows 必须登记 huguan_dashboard"
    assert r["status"] == "synced"


def test_write_background_clears_channel_via_owner_channel_target(client, monkeypatch):
    """点位 #5 的 :165（清空通道列）必须走 huguan_owner_channel，不是全行刷新
    —— 通道列被 cells_for_row 排除，走错 target 就永远清不掉。"""
    import google_sheets_service as gs
    import routes.huguan_dashboard_routes as hr
    calls = []
    monkeypatch.setattr(gs, "build_service", lambda _p: object())
    monkeypatch.setattr(gs, "update_rows_by_account_id",
                        lambda svc, sid, name, rows, key_col=None:
                        calls.append([c for r in rows for c in (r.get("cells") or {})]))

    h, uid = _tt_huguan(client, "_hg_p5")
    db = database.get_db()
    _mk_huguan_conf(db, uid)
    db.execute("INSERT INTO tt_accounts (advertiser_id, name, owner_id) "
               "VALUES ('hg_p5_a','hg_p5_a',?)", (uid,))
    db.commit()
    conf = __import__("huguan_dashboard").get_platform_config(db, uid, "tt")
    db.close()

    # 直接调新签名的 _write_background（第 4 个参数是表主人）
    rows = [{"account_id": "hg_p5_a", "cells": {"L": ""}}]
    hr._write_background(conf, rows, "tt", uid)

    db = database.get_db()
    r = _settle(db, uid, "huguan_owner_channel", "hg_p5_a")
    db.close()
    assert r is not None, "清空通道列必须登记 huguan_owner_channel"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd py && python -m pytest tests/test_huguan_sheet_write.py -v -k "p1 or p5 or channel"`
Expected: FAIL —— 查不到 `huguan_dashboard` / `huguan_owner_channel` 的日志行；`_write_background` 参数个数不匹配

- [ ] **Step 3: 改 `push_rows`（点位 #1）**

把 `py/huguan_dashboard.py` 里 `push_rows` 的 `_do` 与 `_sync_sheets_background` 那一段
（`def _do(): ... _sync_sheets_background(_do, lambda s, e: ...)`）整段替换为：

```python
    # 接入统一写表治理（三期）：登记 + 后台写 + 失败可查可重试。
    # business_key 逐账户一行；一次 N 户走 run_write_many（一个线程、N 行日志）。
    import sheet_write
    import routes.huguan_sheet_targets as _hst
    _keys = [r["account_id"] for r in rows]
    if not _keys:
        return
    _payload = {"platform": platform}
    _db = _open_db()
    try:
        if len(_keys) == 1:
            sheet_write.run_write(
                _db, user_id=user_id, platform=platform, target="huguan_dashboard",
                business_key=_keys[0],
                sync_fn=sheet_write.build_sync("huguan_dashboard", user_id, _keys[0], _payload),
                payload=_payload)
        else:
            sheet_write.run_write_many(
                _db, user_id=user_id, platform=platform, target="huguan_dashboard",
                business_keys=_keys,
                sync_fn=_hst.huguan_dashboard_many_sync(user_id, platform, _keys),
                payload=_payload)
    finally:
        _db.close()
```

> `_open_db()` 是本模块已有的惰性取库 helper（约 :1784）。**注意**：`run_write` 的 `db` 只用于
> 在**请求线程**登记 pending；真正的写表在后台线程里、用它自己的连接（由 `huguan_dashboard_sync`
> 内部新建）—— 符合全局约束。

- [ ] **Step 4: 改 `_write_background`（点位 #5）**

`py/routes/huguan_dashboard_routes.py` 的 `_write_background` 改为**新增 `user_id` 形参**并接入统一入口：

```python
def _write_background(conf, rows, platform, user_id):
    """后台写表，接入统一治理（三期）。

    `user_id` 是**表主人**（户管自己）—— 原签名只有 `conf`，记不到表主人，
    故本次新增该形参。四个调用点都要传。

    这里保留「按列集合逐次提交」的语义：调用方各自构造不同的 rows
    （新归属名 / 通道列清空 / FB 旧转新 / TT M 列备注），故逐行按目标分派：
    通道列（OWNER_CHANNEL_COL）走 huguan_owner_channel，其余走 huguan_dashboard。
    """
    import sheet_write
    import routes.huguan_sheet_targets as _hst

    channel_col = hd.OWNER_CHANNEL_COL.get(platform)
    # 按**身份**划分，不要用 `r not in channel_rows` —— dict 的 in 是**按值比较**，
    # 两行内容相同的行会被一起划进/划出（勘误：初稿写的就是这个写法）。
    channel_rows, other_rows = [], []
    for r in rows:
        (channel_rows if (channel_col and channel_col in (r.get("cells") or {}))
         else other_rows).append(r)

    db = database.get_db()
    try:
        if other_rows:
            keys = [r["account_id"] for r in other_rows]
            _payload = {"platform": platform}
            sheet_write.run_write_many(
                db, user_id=user_id, platform=platform, target="huguan_dashboard",
                business_keys=keys,
                sync_fn=_hst.huguan_dashboard_many_sync(user_id, platform, keys),
                payload=_payload)
        if channel_rows:
            # 通道列：走自己的 target（该列被 cells_for_row 排除）
            for r in channel_rows:
                value = (r["cells"] or {}).get(channel_col, "")
                _payload = {"platform": platform, "mode": "clear" if value == "" else "owner"}
                sheet_write.run_write(
                    db, user_id=user_id, platform=platform, target="huguan_owner_channel",
                    business_key=r["account_id"],
                    sync_fn=sheet_write.build_sync("huguan_owner_channel", user_id,
                                                   r["account_id"], _payload),
                    payload=_payload)
    finally:
        db.close()
```

并把 **4 个调用点**（约 :159 / :165 / :171 / :180）都加上 `uid` 实参：

```python
        _write_background(conf, <原 rows 表达式>, platform, uid)
```

> `uid` 在 `dashboard_sync` 里已存在（`uid = get_uid()`）；若无，用现场等价变量。

- [ ] **Step 5: 跑测试确认通过**

Run: `cd py && python -m pytest tests/test_huguan_sheet_write.py -v`
Expected: 6 passed

- [ ] **Step 6: 回归（本任务改的是 huguan 看板主路径）**

Run: `cd py && python -m pytest tests/test_huguan_dashboard.py tests/test_huguan_role.py tests/test_fb_huguan_dashboard.py -q`
Expected: 全绿。**失败要当真** —— 这三个文件覆盖本任务改动的全部路径。

- [ ] **Step 7: 提交**

```bash
git add py/huguan_dashboard.py py/routes/huguan_dashboard_routes.py py/tests/test_huguan_sheet_write.py
git commit -m "feat(huguan): 点位 #1/#5 接入统一治理（huguan_dashboard target）

- #1 push_rows：15 个调用点都经 writeback_rows，改这一处即全覆盖；
  N>1 走 run_write_many（一个线程、N 行日志）
- #5 _write_background：签名新增 user_id（表主人）—— 原签名只有 conf，
  记不到表主人；4 个调用点都已传
- #5 的通道列清空走 huguan_owner_channel（该列被 cells_for_row 刻意排除，
  走全行刷新永远清不掉）"
```

---

### Task 4: 点位 #2 / #3 / #4 接入

**Files:**
- Modify: `py/huguan_dashboard.py`（`push_remark_to_operator_dashboard` :1770-1779 / `writeback_owner_channel` :1827-1836 / `writeback_fb_acceptor` :1862-1874）
- Test: `py/tests/test_huguan_sheet_write.py`

**Interfaces:**
- Consumes: `routes.huguan_sheet_targets.operator_dashboard_remark_sync` / `huguan_owner_channel_sync` / `huguan_fb_acceptor_sync`
- Produces: 三个点位改走统一入口；调用点按现场核对是否需补 `payload`

**关键约束**

- **#2 的 `user_id` 必须是 `owner_id`（表主人），不是操作者** —— 这是本期与二期的有意差异。
- **#3 的 TT 路径**：`payload` 需带 `{"platform": "tt", "mode": "owner"}`；重建读回
  `tt_accounts.owner_change_note`（该串在写表前已落库）。**GG 路径**同理但 mode 也是
  `"owner"`（重建从 `users` 重算名字）。

- [ ] **Step 1: 写失败测试**

追加到 `py/tests/test_huguan_sheet_write.py`：

```python
def test_writeback_owner_channel_registers_and_rebuilds(client, monkeypatch):
    """点位 #3：必须登记 huguan_owner_channel，且重试能把通道列写回去。"""
    import google_sheets_service as gs
    import huguan_dashboard as hd
    written = []
    monkeypatch.setattr(gs, "build_service", lambda _p: object())
    monkeypatch.setattr(gs, "update_rows_by_account_id",
                        lambda svc, sid, name, rows, key_col=None: written.extend(rows))

    h, uid = _tt_huguan(client, "_hg_p3")
    db = database.get_db()
    _mk_huguan_conf(db, uid)
    db.execute("INSERT INTO tt_accounts (advertiser_id, name, owner_id) "
               "VALUES ('hg_p3_a','hg_p3_a',?)", (uid,))
    db.commit()
    db.close()

    hd.writeback_owner_channel(uid, "tt", "hg_p3_a", uid, text="旧转新10.8")

    db = database.get_db()
    r = _settle(db, uid, "huguan_owner_channel", "hg_p3_a")
    db.close()
    assert r is not None, "必须登记 huguan_owner_channel"
    assert r["status"] == "synced"
    assert any("L" in (x.get("cells") or {}) for x in written), f"应写 TT 通道列 L：{written}"


def test_writeback_fb_acceptor_registers(client, monkeypatch):
    """点位 #4：必须登记 huguan_fb_acceptor。"""
    import google_sheets_service as gs
    import huguan_dashboard as hd
    monkeypatch.setattr(gs, "build_service", lambda _p: object())
    monkeypatch.setattr(gs, "update_rows_by_account_id", lambda *a, **k: None)

    h, uid = _tt_huguan(client, "_hg_p4")
    db = database.get_db()
    _mk_huguan_conf(db, uid, "fb")
    db.execute("INSERT INTO fb_accounts (name, account_id, owner_id, acceptor) "
               "VALUES ('fb_a','fb_a',?, '张三转李四10.8')", (uid,))
    db.commit()
    db.close()

    hd.writeback_fb_acceptor(uid, "fb", "fb_a", "张三转李四10.8")

    db = database.get_db()
    r = _settle(db, uid, "huguan_fb_acceptor", "fb_a")
    db.close()
    assert r is not None, "必须登记 huguan_fb_acceptor"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd py && python -m pytest tests/test_huguan_sheet_write.py -v -k "p3 or p4"`
Expected: FAIL —— 查不到对应 target 的日志行

- [ ] **Step 3: 三处替换**

**#2 `push_remark_to_operator_dashboard`** —— 把 `_do` + `_sync_sheets_background` 那段替换为：

```python
    import sheet_write
    _payload = {"kind": "remark"}
    _db = _open_db()
    try:
        sheet_write.run_write(
            # ⚠️ user_id 传 **owner_id**（表主人），不是操作者 —— 本期唯一真正的第三方，
            # 规格 §3.5。日志行记在表主人名下，他才能看到并重试。
            _db, user_id=owner_id, platform="tt", target="operator_dashboard_remark",
            business_key=account_id,
            sync_fn=sheet_write.build_sync("operator_dashboard_remark", owner_id,
                                           account_id, _payload),
            payload=_payload)
    finally:
        _db.close()
```

**#3 `writeback_owner_channel`** —— 替换为：

```python
    import sheet_write
    _payload = {"platform": platform, "mode": "owner"}
    _db = _open_db()
    try:
        sheet_write.run_write(
            _db, user_id=user_id, platform=platform, target="huguan_owner_channel",
            business_key=account_id,
            sync_fn=sheet_write.build_sync("huguan_owner_channel", user_id,
                                           account_id, _payload),
            payload=_payload)
    finally:
        _db.close()
```

**#4 `writeback_fb_acceptor`** —— 替换为（保留原有的「note 为空则早退」）：

```python
    if not note:
        return
    import sheet_write
    _payload = {"platform": platform}
    _db = _open_db()
    try:
        sheet_write.run_write(
            _db, user_id=user_id, platform=platform, target="huguan_fb_acceptor",
            business_key=account_id,
            sync_fn=sheet_write.build_sync("huguan_fb_acceptor", user_id,
                                           account_id, _payload),
            payload=_payload)
    finally:
        _db.close()
```

> 三处都**保留原有的「配置未就绪就早退」判断**（原本是 `if not conf[...]: return`）—— 若不保留，
> 未配置看板的实例上每次操作都会凭空产生一条 `retry_failed` 行（**二期踩过这个坑，修复轮 1**）。
> **实现时逐处检查现场是否已有该早退分支，有则原样保留。**

- [ ] **Step 4: 跑测试确认通过**

Run: `cd py && python -m pytest tests/test_huguan_sheet_write.py -v`
Expected: 8 passed

- [ ] **Step 5: 回归**

Run: `cd py && python -m pytest tests/test_huguan_dashboard.py tests/test_tt_accounts.py tests/test_fb_platform.py -q`
Expected: 全绿（这三个文件覆盖 #2/#3/#4 的调用路径）

- [ ] **Step 6: 提交**

```bash
git add py/huguan_dashboard.py py/tests/test_huguan_sheet_write.py
git commit -m "feat(huguan): 点位 #2/#3/#4 接入统一治理

- #2 push_remark_to_operator_dashboard：**user_id 传 owner_id（表主人）**，
  不是操作者 —— 本期唯一真正的第三方，日志行记在投手名下他才能看到/重试（规格 §3.5）
- #3 writeback_owner_channel：huguan_owner_channel target，payload 带
  platform+mode=owner；TT 路径重建读回 tt_accounts.owner_change_note
- #4 writeback_fb_acceptor：huguan_fb_acceptor target，保留「note 为空早退」

三处均保留原有的「配置未就绪早退」—— 不保留会让未配置的实例凭空产生失败行
（二期修复轮 1 的同一类坑）。"
```

---

### Task 5: 前端 —— TT 面板补 target 过滤 + FB 账户表加「写表」列

**Files:**
- Modify: `frontend/src/views/tt/TtAccountPanel.vue`（**只加 target 过滤**）
- Modify: `frontend/src/views/fb/FbAccountPanel.vue`

**Interfaces:**
- Consumes: `sheetWriteApi`（`frontend/src/api/sheetWrite.js`）、`sheetWriteMark/Tone/Hint` / `SHEET_WRITE_TOAST`（`frontend/src/utils/sheetWriteUi.js`）

**⚠️ 本任务含一处三期**引入**的回归修复（自审发现）**

三期新增了两个 **tt 平台**的 target：`huguan_dashboard`（platform=tt）与
`operator_dashboard_remark`（platform=tt）。而**二期上线的 TT 账户表面板拉取状态时不带
target 过滤** —— 它会把这两类失败当成 `tt_recycle` 的失败标在账户行上（**标错**）。

这正是三期要修的「同一 business_key 跨 target 相互遮蔽」的镜像面：三期新增 target
⇒ 所有**不带 target 过滤**的消费方都会开始错标。全仓盘一遍：

| 消费方 | 是否过滤 target | 结论 |
|---|---|---|
| `views/tt/TtAccountPanel.vue` | ❌ 只传 `platform: 'tt'` | **本期必须补** |
| `views/AdsAccountPanel.vue`（二期 GG） | ✅ `DASH_TARGET = 'gg_my_dashboard'` | 无需改 |
| `components/AccountDetailModal.vue`（二期充值） | ✅ `RECHARGE_TARGET = 'gg_recharge'` | 无需改（平台 gg，三期不动 gg） |

- [ ] **Step 1: 无 `node_modules` 时先装**

Run: `cd frontend && npm ci`
（worktree 不复制 node_modules；**不要**碰主目录的 `node_modules`。）

- [ ] **Step 2: 给 TT 面板补 target 过滤（回归修复）**

`frontend/src/views/tt/TtAccountPanel.vue`：

1. 加常量（与该文件既有的 `SHEET_WRITE_POLL_MS` 等放在一起）：

```js
const RECYCLE_TARGET = 'tt_recycle'   // TT 账户行上的标记只反映回收户清单写表
```

2. `loadSheetWriteFailures()` 的循环里加过滤：

```js
    for (const it of res.items || []) {
      // 三期新增了 tt 平台的两个 target（huguan_dashboard / operator_dashboard_remark）；
      // 不过滤会把它们的失败当成回收清单的失败标在账户行上（标错）。
      if (it.target !== RECYCLE_TARGET) continue
      map[it.business_key] = it
    }
```

3. `pollSheetWrite(advertiserId)` 里：
   - 取状态时传 `target: RECYCLE_TARGET`（`sheetWriteApi.status({ platform: 'tt', target: RECYCLE_TARGET, businessKey: advertiserId })`）
   - 拿到 `it` 后加 `if (it.target !== RECYCLE_TARGET) return`（防被遮蔽时误判）

> **判据**：TT 面板现在 `target` 过滤后应**只**显示 `tt_recycle` 的失败。若某账户行出现
> 「写表失败」但该账户并**没有**回收清单写表记录，即过滤失效。

- [ ] **Step 3: 照搬二期 TT 的方案**

对照 `frontend/src/views/tt/TtAccountPanel.vue`（二期已确认并上线的实现），在
`frontend/src/views/fb/FbAccountPanel.vue` 做同样三件事：

1. **表格插一列** —— `el-table` 里、紧跟「账户ID」列（`prop="account_id"`）之后：

```html
        <!-- 写表状态。沿用二期 TT 账户表已确认的方案（同一位置、同一宽度、同一三态语汇），
             两张表并列出现时跨平台一致。 -->
        <el-table-column label="写表" width="54" align="center">
          <template #default="{ row }">
            <template v-if="sheetWriteFailures[row.account_id]">
              <el-tooltip placement="top"
                :content="sheetWriteHint(sheetWriteFailures[row.account_id])">
                <el-button link size="small"
                  :type="sheetWriteTone(sheetWriteFailures[row.account_id].status)"
                  @click.stop="retrySheetWrite(row)">{{ sheetWriteMark(sheetWriteFailures[row.account_id].status) }}</el-button>
              </el-tooltip>
            </template>
            <span v-else style="color:#16a34a;font-size:14px;">✅</span>
          </template>
        </el-table-column>
```

2. **script 加**（import + 状态 + 三个函数）—— **逐字照搬 TT 面板的对应实现**，仅两处不同：
   - `platform` 传 `'fb'`
   - **加上 target 过滤**：`const DASH_TARGET = 'huguan_dashboard'`，`loadSheetWriteFailures`
     里 `if (it.target !== DASH_TARGET) continue`，`pollSheetWrite` 里同判
     （三期新加 `target` 参数就是为了这个 —— 同一 `account_id` 可能同时有
     `huguan_dashboard` 与 `huguan_fb_acceptor` 两条，不过滤会标错）

3. **`onUnmounted` 清 Map**（TT 面板同形）。

- [ ] **Step 4: 接**「写表结果」**的轮询触发点**

FB 账户表的动作里，**哪些会触发户管看板域的写表**：#4 的三条路径（建号 / 编辑 / 换绑）。
在对应的 `save*` / `reassign` 成功分支后调 `pollSheetWrite(row.account_id)`。

> **实现时先读现场**：这三条路径在 `FbAccountPanel.vue` 里对应的函数名可能与 TT 不同；
> 逐个核对，别照抄 TT 的函数名。

- [ ] **Step 5: 构建验证**

Run: `cd frontend && npm run build`
Expected: 构建成功（exit 0）

- [ ] **Step 6: 提交**

```bash
git add frontend/src/views/tt/TtAccountPanel.vue frontend/src/views/fb/FbAccountPanel.vue
git commit -m "feat(fb): 账户表新增「写表」列；TT 面板补 target 过滤

FB 列逐字复用二期 TT 账户表已确认的方案（位置/宽度/三态/文案单源），并加
target 过滤（三期新加的 /status target 参数）—— 同一 account_id 可能同时有
huguan_dashboard 与 huguan_fb_acceptor 两条，不过滤会标错。

TT 面板的过滤是**三期引入的回归修复**：三期新增了两个 tt 平台的 target，
而二期上线的 TT 面板拉取时不带 target 过滤 ⇒ 会把它们当成回收清单的失败
标在账户行上。"
```

---

### Task 6: 前端 —— 户管看板配置卡片的失败汇总

**Files:**
- Modify: `frontend/src/components/HuguanDashboardCard.vue`

**Interfaces:**
- Consumes: `sheetWriteApi.status({ platform, target: 'huguan_dashboard' })` / `.status({ platform, target: 'huguan_owner_channel' })` / `.retry(...)`

- [ ] **Step 1: 先调 `/frontend-design`**

**本任务是本期唯一的新增 UI**（在既有卡片里加一个「同步失败」汇总区 + 重试）—— 按项目规矩
**必须先调 `/frontend-design`** 拿视觉方案，再写代码。喂给它的需求：

- 位置：`HuguanDashboardCard.vue` 的配置卡内、「看板同步」分组之后、「上一次：」提示之前
- 内容：本看板（按 `HD_PLATFORM`）下 `huguan_dashboard` + `huguan_owner_channel` 两个 target
  的失败项汇总（条数 + 逐条：账户ID + 原因 + 重试按钮）
- 无失败时不显示任何东西（不能常驻占位）
- 复用 `sheetWriteUi.js` 的三态语汇与文案

- [ ] **Step 2: 按视觉方案实现**

数据来源：`sheetWriteApi.status({ platform: HD_PLATFORM, target: 'huguan_dashboard' })`
与 `... target: 'huguan_owner_channel'`（两次调用，各自过滤；**不要**不带 target 地拉全部，
那会把别的 target 的行也算进来）。

重试：`sheetWriteApi.retry({ platform: HD_PLATFORM, target: f.target, businessKey: f.business_key })`。

加载时机：`onMounted`（与既有 `loadHdConfig` 并列）+ 每次 `push`/`sync` 成功后刷新。

- [ ] **Step 3: 构建验证**

Run: `cd frontend && npm run build`
Expected: 构建成功

- [ ] **Step 4: 人工验证清单（写进报告，交用户执行）**

`npm run build` 只证明能编译。报告里列出这份清单：

1. 配好看板后，随便改一个账户的状态 → 户管看板应刷到；**把表格 ID 故意改错**再改状态 → 卡片内应出现失败项
2. 点失败项的「重试」→ 恢复正确表格 ID 后应转成功、汇总区消失
3. 无失败时汇总区**不应出现**
4. 同一账户同时有 `huguan_dashboard` 与 `huguan_owner_channel` 两条失败时，**两条都要显示**（target 过滤的检出口）

- [ ] **Step 5: 提交**

```bash
git add frontend/src/components/HuguanDashboardCard.vue
git commit -m "feat(huguan): 看板配置卡片显示同步失败汇总 + 重试

户管是这 4 个 target 里 3 个的表主人（规格 §3.5）；原先写表失败只落服务端日志，
户管在自己的卡片里看不到、也无法重试。

按 target 分别拉取（三期新加的 /status target 参数），避免别的 target 的行混入。"
```

---

## 交付后的收尾（非任务，供执行者提醒用户）

1. **合并回 master 前跑全量**：`cd py && python -m pytest tests/ -q`
2. **合并** → 主目录 `npm run build` → **提醒用户重启 Flask**
3. **提醒用户跑 Task 6 Step 4 的人工清单**（前端运行时行为无自动化覆盖）
4. 合并时**特别当心**（二期的教训）：并行会话可能在你合并期间提交 master；自动合并成功但你又改过的文件必须重新 `git add`，否则「工作区绿、提交树旧」的错位不会被任何测试发现
