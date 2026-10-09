"""GG 平台写表点接入统一治理 —— 端到端测试。

守卫两件事：(1) 每次触发都登记 pending 并抓对 business_key；
(2) 最终失败落 retry_failed（GG 侧全是镜像类，**不得**出现 rolled_back）。

⚠️ 轮询必须用**模块顶层**捕获的真 sleep（下）。测试里 monkeypatch 的是
**全局** `time.sleep`（`_sync_sheets_background` 的 30s 重试也靠它跳过），
而轮询循环自己也调 sleep —— 若在 patch 之后再 `from time import sleep`，
拿到的是被 patch 的桩函数，主线程不让出 GIL、后台守护线程永远跑不到，
断言就会在任务真正落终态之前提前开火。
"""
import json
from time import sleep as _poll_sleep

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


def _poll(db, uid, key, tries=300):
    """轮询直到该行落终态（用模块顶层捕获的真 sleep，见文件头注释）。"""
    for _ in range(tries):
        r = _row(db, uid, "gg_my_dashboard", key)
        if r is not None and r["status"] in sheet_write.TERMINAL:
            return r
        _poll_sleep(0.02)
    return _row(db, uid, "gg_my_dashboard", key)


def _wait_until(pred, msg, tries=300):
    """轮询直到 pred() 为真；超时则以 msg 断言失败。

    用模块顶层捕获的真 sleep 让出 GIL，后台守护线程才跑得到（见文件头注释）。
    """
    for _ in range(tries):
        if pred():
            return
        _poll_sleep(0.02)
    raise AssertionError(msg)


def _record_cell_writes(monkeypatch):
    """把看板批量写换成记录器，返回 ([(account_id, value, col_index)], [key_col])。

    实现已从「逐账户 2 次 update_cell_by_account_id」改成「一次
    update_rows_by_account_id 覆盖整批」：一次调用里每户的 cells 同时含
    F 与 H。这里把每户的 cells 展平成逐格三元组 —— 既守住「一次调用覆盖全部
    账户」，也保住既有「F 列=5、H 列=7」的断言口径。

    同时记下每次调用的 key_col：本看板的账户ID在 **B 列**，而
    update_rows_by_account_id 的默认值是 "C"（户管看板的列）—— 漏传会按 C 列
    定位 ⇒ 整批写空且不抛异常（静默写错）。用 key_col 断言把这条风险钉死。

    参数序与 google_sheets_service.update_rows_by_account_id 逐位对齐：
    (service, spreadsheet_id, sheet_name, rows, key_col="C")。
    """
    import google_sheets_service as gs
    writes = []
    key_cols = []
    monkeypatch.setattr(gs, "build_service", lambda _p: object())

    def _rec(svc, sid, name, rows, key_col="C"):
        key_cols.append(key_col)
        for r in rows:
            for col, val in r["cells"].items():
                writes.append((r["account_id"], val, {"F": 5, "H": 7}[col]))

    monkeypatch.setattr(gs, "update_rows_by_account_id", _rec)
    return writes, key_cols



def test_status_change_registers_dashboard_write(client, monkeypatch):
    """改状态 ⇒ 登记 gg_my_dashboard 的一条记录，business_key 是 account_id。"""
    import google_sheets_service as gs
    monkeypatch.setattr(gs, "build_service", lambda _p: object())
    monkeypatch.setattr(gs, "update_rows_by_account_id", lambda *a, **k: None)

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

    db = database.get_db()
    r = _poll(db, uid, acct_key)
    db.close()
    assert r is not None, "改状态必须登记一条 gg_my_dashboard"
    assert r["status"] == "synced"
    assert r["status"] not in ("rolled_back", "rollback_abandoned"), "GG 侧不得回滚"


def test_status_change_without_sheets_config_registers_nothing(client, monkeypatch):
    """未配置表格（无 recharge_sheet_id）⇒ 改状态必须**零** sheet_write_log 行。

    这是回归守卫：配置闸门（原实现为 `if sheet_id and dashboard_name:`）必须在
    **登记 pending 之前**短路，未配置实例上写表点须静默 no-op。若闸门失效（例如
    误用「构造闭包永不失败」的 build_sync 当闸门），这里会凭空多出一条日志行 ——
    后台写表随即失败 ⇒ retry_failed + ⚠️ 标记，正是用户可见回归。
    """
    h, uid = _gg_user(client, "_gg_noconfig")
    db = database.get_db()
    # 刻意**不**调 _setup_sheets：tags 里没有 recharge_sheet_id，闸门应关闭
    alive = _status_id(db, "存活")
    dead = _status_id(db, "死亡")
    aid = _mk_account(db, uid, "gg_adv_nc", alive)
    db.close()

    resp = client.put(f"/api/accounts/{aid}", headers=h, json={"status_id": dead})
    assert resp.status_code == 200, resp.get_json()

    db = database.get_db()
    n = db.execute("SELECT COUNT(*) FROM sheet_write_log").fetchone()[0]
    db.close()
    assert n == 0, f"未配置表格时不得登记任何写表任务，实际 {n} 行"


def test_delete_and_restore_register_dashboard_write(client, monkeypatch):
    """删户与恢复**各自**触发一次写表 —— 两入口独立可观测。

    为什么不能只断言「存在一行」：两处 upsert 的是**同一行**
    （UNIQUE(user_id, target, business_key)，business_key 同为 account_id），
    只看到一行分不清是哪个点位写的（弱守卫：删户点位单干也能让此断言通过）。
    故用写表实参区分：删户写 H 列「解绑」，恢复清空 H 列 —— 两者先后各自出现，
    才证明两个点位都真的触发过。轮询各自的可观测副作用，不依赖墙钟先后。
    """
    writes, _key_cols = _record_cell_writes(monkeypatch)

    h, uid = _gg_user(client, "_gg_del")
    db = database.get_db()
    _setup_sheets(db)
    aid = _mk_account(db, uid, "gg_adv_2", _status_id(db, "存活"))
    db.close()

    assert client.delete(f"/api/accounts/{aid}", headers=h).status_code == 200
    # 删户点位：H 列写「解绑」（col_index=7）
    _wait_until(lambda: ("gg_adv_2", "解绑", 7) in writes,
                f"删户必须触发写表，实际 {writes}")

    assert client.post(f"/api/accounts/{aid}/restore", headers=h).status_code == 200
    # 恢复点位：H 列清空（col_index=7、值为空串）—— 与删户的「解绑」是不同的可观测值
    _wait_until(lambda: ("gg_adv_2", "", 7) in writes,
                f"恢复必须触发写表（清空 H 列），实际 {writes}")

    db = database.get_db()
    r = _poll(db, uid, "gg_adv_2")
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

    monkeypatch.setattr(gs, "update_rows_by_account_id", _boom)

    h, uid = _gg_user(client, "_gg_fail")
    db = database.get_db()
    _setup_sheets(db)
    alive = _status_id(db, "存活")
    dead = _status_id(db, "死亡")
    aid = _mk_account(db, uid, "gg_adv_3", alive)
    db.close()

    assert client.put(f"/api/accounts/{aid}", headers=h,
                      json={"status_id": dead}).status_code == 200

    db = database.get_db()
    r = _poll(db, uid, "gg_adv_3")
    cur = db.execute("SELECT status_id FROM accounts WHERE id=?", (aid,)).fetchone()["status_id"]
    db.close()

    assert r is not None, "改状态必须登记一条 gg_my_dashboard"
    assert r["status"] == "retry_failed", f"应落 retry_failed，实际 {r['status']}"
    # 落库文案是**固定文案**（安全修复：error_msg 会经 /status 原样回客户端），
    # 异常原文只进日志 —— 不再是 "Sheets 配额超限"。
    assert r["error_msg"] == sheet_write._WRITE_FAILED_MSG, \
        f"落库文案应为固定文案，实际 {r['error_msg']!r}"
    assert cur == dead, "GG 侧是镜像类，**不得**回滚业务数据"


def test_batch_status_change_writes_every_account(client, monkeypatch):
    """批量改状态：N 行日志 **且每一户都被写表**。

    守卫的点：`run_write_many` 只执行 sync_fn **一次**（一个后台线程，Task 1 已用
    「sync_fn 只应执行一次」钉住）。故首跑的 sync_fn 必须覆盖全部 N 户 —— 若照
    单户工厂 `build_sync(..., business_keys[0], ...)` 构造，则只有第一户被写进表，
    而 N 行日志全落 synced（静默漏写，比原实现更糟：原来是一个线程串行写 N 户）。
    """
    writes, key_cols = _record_cell_writes(monkeypatch)

    h, uid = _gg_user(client, "_gg_batch")
    db = database.get_db()
    _setup_sheets(db)
    alive = _status_id(db, "存活")
    dead = _status_id(db, "死亡")
    a1 = _mk_account(db, uid, "gg_adv_5", alive)
    a2 = _mk_account(db, uid, "gg_adv_6", alive)
    db.close()

    resp = client.post("/api/accounts/batch-update", headers=h,
                       json={"ids": [a1, a2], "field": "status_id", "value": dead})
    assert resp.status_code == 200, resp.get_json()

    db = database.get_db()
    r1 = _poll(db, uid, "gg_adv_5")
    r2 = _poll(db, uid, "gg_adv_6")
    db.close()

    assert r1 is not None and r2 is not None, "批量改状态必须每户各登记一行"
    assert (r1["status"], r2["status"]) == ("synced", "synced")
    written = {a for a, _v, _c in writes}
    assert written == {"gg_adv_5", "gg_adv_6"}, f"两户都必须被写表，实际只写了 {writes}"
    # 一次调用覆盖整批（不再逐账户 2 次），且必须按 B 列（账户ID）定位 ——
    # 默认值是 "C"（户管看板列）会整批写空且不抛异常。
    assert key_cols == ["B"], (
        f"须一次调用且按 B 列定位（默认 C 列会静默写空），实际 key_col={key_cols}")


def test_dashboard_write_rebuilds_from_accounts(client, monkeypatch):
    """重建从 accounts 重算 F/H —— 删户态写「解绑」，非删户态写空。"""
    writes, _key_cols = _record_cell_writes(monkeypatch)

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


def test_dashboard_write_f_col_writes_status_name(client, monkeypatch):
    """F 列必须写该账户的**状态名**（status_name or "存活"）—— 与改前逐字相同。

    批量改造后 F 列从未被任何用例断言（上面各条只断言 H），于是实现若把 F 写死成
    "存活"、或误填账户ID / H 的值，全套照样绿。这里锚两条分支：

    (1) 有状态名时 F = 该名 —— 刻意用**非** "存活" 的名字「死亡」，以区别于回落值；
        写死 "存活" 或写成 H 的值都会在此处变红。
    (2) status_id 为 NULL（LEFT JOIN 出 NULL status_name）时回落 "存活"。
    """
    writes, _key_cols = _record_cell_writes(monkeypatch)

    h, uid = _gg_user(client, "_gg_fcol")
    db = database.get_db()
    _setup_sheets(db)
    dead = _status_id(db, "死亡")
    a_named = _mk_account(db, uid, "gg_fcol_named", dead)    # 状态名「死亡」
    a_null = _mk_account(db, uid, "gg_fcol_null", None)      # status_id NULL ⇒ 回落
    db.close()

    # 删户点位触发看板写（写 F=状态名、H="解绑"），不改状态值
    assert client.delete(f"/api/accounts/{a_named}", headers=h).status_code == 200
    assert client.delete(f"/api/accounts/{a_null}", headers=h).status_code == 200

    _wait_until(lambda: ("gg_fcol_named", "解绑", 7) in writes
                and ("gg_fcol_null", "解绑", 7) in writes,
                f"两户删户都必须触发看板写，实际 {writes}")

    assert ("gg_fcol_named", "死亡", 5) in writes, \
        f"F 列(col 5) 必须写该账户的状态名「死亡」（写死 '存活' 会在此变红），实际 {writes}"
    assert ("gg_fcol_null", "存活", 5) in writes, \
        f"status_name 为 NULL 时 F 列(col 5) 应回落 '存活'，实际 {writes}"


# ---------------------------------------------------------------------------
# 身份维度：五个点位各自「写谁的看板」
#
# 上面六条用例里 owner 恒等于操作者，而无私有配置时 _get_my_dashboard_name 一律
# 回落内置「我的看板」—— 于是把删户/恢复的 ac["owner_id"] 改成 user_id（或反向）
# 后六条全绿。该维度此前**零覆盖**。
#
# 它失败时是静默的：跨用户操作（管理员删他人账户）会写错看板名，
# update_rows_by_account_id 在该表里查不到对应行，只把它记进返回值的
# not_found 列表、**不抛异常** ⇒ 日志照样落 synced，正是本功能要消灭的
# 「写丢了还不知道」。
#
# 故下面每条都造 owner ≠ 操作者、两人各配**不同的私有看板名**，直接断言传入
# update_rows_by_account_id 的看板名是哪一份，并反向断言不是另一份。
# ---------------------------------------------------------------------------


def _record_sheet_writes(monkeypatch):
    """把看板写表换成记录器，返回 [(dashboard_name, account_id)]。

    参数序与 google_sheets_service.update_rows_by_account_id 逐位对齐：
    (service, spreadsheet_id, sheet_name, rows, key_col="C")。批量写入一次覆盖
    本批全部账户，故把 rows 里每户展平成一条 (sheet_name, account_id)。
    """
    import google_sheets_service as gs
    calls = []
    monkeypatch.setattr(gs, "build_service", lambda _p: object())
    monkeypatch.setattr(
        gs, "update_rows_by_account_id",
        lambda svc, sid, name, rows, key_col="C":
        calls.extend((name, r["account_id"]) for r in rows))
    return calls


def _set_private_dashboard(db, uid, name):
    """给某用户盖一层**私有**看板名（config 表 key=sheet_mappings_<uid>）。

    私有层优先级最高（_get_my_dashboard_name：私有 config > 全局 tags > 内置默认，
    见 main.py），故两人各配不同名后，「写谁的看板」在写表实参里直接可读。
    """
    db.execute("INSERT OR REPLACE INTO config (key, value) VALUES (?, ?)",
               (f"sheet_mappings_{uid}", json.dumps({"my_dashboard": name}, ensure_ascii=False)))
    db.commit()


def _ident_setup(client):
    """建 owner（账户归属者）与 operator（操作者），各配不同的私有看板名。

    返回 (op_headers, owner_uid, op_uid)。

    operator 用 role='admin'：删户 / 恢复 / 改状态 / 批量改状态四个端点都只在
    `_cross_user_actor(user_id)` 为真时才放行「动别人的账户」，而
    CROSS_USER_ROLES = ("developer", "admin", "huguan")。取 admin 而非 developer，
    是因为 developer 同在 PLATFORM_SWITCH_ROLES（可切平台）里，admin 语义更贴近
    「管理员代管他人账户」这一被测场景。
    """
    _h_owner, owner_uid = _gg_user(client, "_gg_ident_owner")
    h_op, op_uid = _gg_user(client, "_gg_ident_op", role="admin")
    db = database.get_db()
    _setup_sheets(db)
    _set_private_dashboard(db, owner_uid, "看板_OWNER")
    _set_private_dashboard(db, op_uid, "看板_OPERATOR")
    db.close()
    return h_op, owner_uid, op_uid


def test_delete_writes_owner_dashboard_not_operator(client, monkeypatch):
    """删户点位写的是**账户归属者**的看板名，不是操作者的。"""
    calls = _record_sheet_writes(monkeypatch)
    h_op, owner_uid, _op_uid = _ident_setup(client)
    db = database.get_db()
    aid = _mk_account(db, owner_uid, "gg_ident_del", _status_id(db, "存活"))
    db.close()

    assert client.delete(f"/api/accounts/{aid}", headers=h_op).status_code == 200
    _wait_until(lambda: any(a == "gg_ident_del" for _n, a in calls),
                f"删户必须触发写表，实际 {calls}")

    names = {n for n, a in calls if a == "gg_ident_del"}
    assert "看板_OWNER" in names, f"删户须写账户 owner 的看板，实际 {names}"
    assert "看板_OPERATOR" not in names, f"删户不得写操作者的看板，实际 {names}"


def test_restore_writes_owner_dashboard_not_operator(client, monkeypatch):
    """恢复点位写的也是**账户归属者**的看板名，不是操作者的。"""
    calls = _record_sheet_writes(monkeypatch)
    h_op, owner_uid, _op_uid = _ident_setup(client)
    db = database.get_db()
    aid = _mk_account(db, owner_uid, "gg_ident_res", _status_id(db, "存活"))
    db.execute("UPDATE accounts SET deleted_at=datetime('now','localtime') WHERE id=?", (aid,))
    db.commit()
    db.close()

    assert client.post(f"/api/accounts/{aid}/restore", headers=h_op).status_code == 200
    _wait_until(lambda: any(a == "gg_ident_res" for _n, a in calls),
                f"恢复必须触发写表，实际 {calls}")

    names = {n for n, a in calls if a == "gg_ident_res"}
    assert "看板_OWNER" in names, f"恢复须写账户 owner 的看板，实际 {names}"
    assert "看板_OPERATOR" not in names, f"恢复不得写操作者的看板，实际 {names}"


def test_status_change_writes_operator_dashboard_not_owner(client, monkeypatch):
    """单户改状态点位写的是**操作者**的看板名（与删户/恢复刻意不一致）。"""
    calls = _record_sheet_writes(monkeypatch)
    h_op, owner_uid, _op_uid = _ident_setup(client)
    db = database.get_db()
    aid = _mk_account(db, owner_uid, "gg_ident_st", _status_id(db, "存活"))
    dead = _status_id(db, "死亡")
    db.close()

    resp = client.put(f"/api/accounts/{aid}", headers=h_op, json={"status_id": dead})
    assert resp.status_code == 200, resp.get_json()
    _wait_until(lambda: any(a == "gg_ident_st" for _n, a in calls),
                f"改状态必须触发写表，实际 {calls}")

    names = {n for n, a in calls if a == "gg_ident_st"}
    assert "看板_OPERATOR" in names, f"改状态须写操作者的看板，实际 {names}"
    assert "看板_OWNER" not in names, f"改状态不得写账户 owner 的看板，实际 {names}"


def test_batch_status_change_writes_operator_dashboard_not_owner(client, monkeypatch):
    """批量改状态点位（run_write_many 路径）写的也是**操作者**的看板名。"""
    calls = _record_sheet_writes(monkeypatch)
    h_op, owner_uid, _op_uid = _ident_setup(client)
    db = database.get_db()
    alive = _status_id(db, "存活")
    dead = _status_id(db, "死亡")
    a1 = _mk_account(db, owner_uid, "gg_ident_b1", alive)
    a2 = _mk_account(db, owner_uid, "gg_ident_b2", alive)
    db.close()

    resp = client.post("/api/accounts/batch-update", headers=h_op,
                       json={"ids": [a1, a2], "field": "status_id", "value": dead})
    assert resp.status_code == 200, resp.get_json()
    _wait_until(lambda: {a for _n, a in calls} >= {"gg_ident_b1", "gg_ident_b2"},
                f"批量改状态必须写全两户，实际 {calls}")

    names = {n for n, a in calls if a in ("gg_ident_b1", "gg_ident_b2")}
    assert "看板_OPERATOR" in names, f"批量改状态须写操作者的看板，实际 {names}"
    assert "看板_OWNER" not in names, f"批量改状态不得写账户 owner 的看板，实际 {names}"


# ---------------------------------------------------------------------------
# GG 充值表（target=gg_recharge）四个写表点
#
# ⚠️ 与上面几条不同：下面几条**不**在测试体内重新 `from time import sleep`
# —— 本文件顶部已捕获真 sleep。其中一条会 monkeypatch 全局 `time.sleep`，若在
# patch 之后再 import 一次，轮询拿到的就是被 patch 的桩，轮询自己会去填 `seen`
# （断言恒真）且不让出 GIL（断言跑在后台线程之前）。
# ---------------------------------------------------------------------------


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


def test_recharge_retry_sheets_submits_to_unified_entry(client, monkeypatch):
    """旧 `POST /api/recharge/<rid>/retry-sheets` 改为**薄转调**统一入口。

    语义已变：200 只代表「已提交到后台」。本用例钉住「提交确实发生」——
    旧形态是同步重放、根本不登记 sheet_write_log，于是查不到日志行 ⇒ 红。
    同时守住既有的 404（记录不存在）不被转调改写掉。
    """
    import google_sheets_service as gs
    written = []
    monkeypatch.setattr(gs, "build_service", lambda _p: object())
    monkeypatch.setattr(gs, "append_recharge",
                        lambda svc, sid, name, rows: written.extend(rows))

    h, uid = _gg_user(client, "_gg_retry")
    db = database.get_db()
    _setup_sheets(db)
    _mk_account(db, uid, "gg_adv_rt", _status_id(db, "存活"))
    # 直接造一条充值记录：本用例测的是重试入口，不必先走 submit
    db.execute("INSERT INTO recharge_records (account_id, amount, operator, created_by, "
               "sheets_synced) VALUES ('gg_adv_rt', '77', '运营', ?, 0)", (uid,))
    db.commit()
    rid = db.execute("SELECT last_insert_rowid()").fetchone()[0]
    db.close()

    assert client.post("/api/recharge/999999999/retry-sheets",
                       headers=h).status_code == 404, "不存在的记录必须 404"

    resp = client.post(f"/api/recharge/{rid}/retry-sheets", headers=h)
    assert resp.status_code == 200, resp.get_json()

    db = database.get_db()
    for _ in range(200):
        r = _row(db, uid, "gg_recharge", str(rid))
        if r is not None and r["status"] in sheet_write.TERMINAL:
            break
        _poll_sleep(0.02)
    r = _row(db, uid, "gg_recharge", str(rid))
    db.close()

    assert r is not None, "旧端点必须登记 gg_recharge（转调统一入口）"
    assert r["status"] == "synced", r["error_msg"] if r else None
    assert any(w["account_id"] == "gg_adv_rt" for w in written), \
        f"重试必须真的把该行写进表，实际 {written}"


def test_status_clear_off_registers_recharge_write(client, monkeypatch):
    """清账追加的「清」记录必须登记 gg_recharge —— 单户（点位 A）与批量（点位 C）。

    本用例是**批量清账点位**唯一的守卫：若点位 C 照单键工厂
    `build_sync("gg_recharge", user_id, _keys[0], ...)` 构造，`run_write_many` 只执行
    sync_fn 一次 ⇒ 只有第一条「清」被写进表，而两行日志全落 synced（静默漏写）。
    断言「三户都被写表」即红 —— 正是 Task 2 在「我的看板」发现的同一类缺陷。
    """
    import google_sheets_service as gs
    written = []
    monkeypatch.setattr(gs, "build_service", lambda _p: object())
    monkeypatch.setattr(gs, "append_recharge",
                        lambda svc, sid, name, rows: written.extend(rows))
    monkeypatch.setattr(gs, "update_rows_by_account_id", lambda *a, **k: None)

    h, uid = _gg_user(client, "_gg_clear")
    db = database.get_db()
    _setup_sheets(db)
    alive = _status_id(db, "存活")
    dead = _status_id(db, "死亡")
    ids = [_mk_account(db, uid, f"gg_adv_c{i}", alive) for i in (1, 2, 3)]
    for aid in ids:
        acc = db.execute("SELECT account_id FROM accounts WHERE id=?", (aid,)).fetchone()["account_id"]
        db.execute("INSERT INTO recharge_records (account_id, amount, operator, created_by) "
                   "VALUES (?, '500', '运营', ?)", (acc, uid))
    db.commit()
    db.close()

    # 点位 A：单户改状态 ⇒ 清账一条
    assert client.put(f"/api/accounts/{ids[0]}", headers=h,
                      json={"status_id": dead}).status_code == 200
    # 点位 C：批量改状态 ⇒ 清账两条
    assert client.post("/api/accounts/batch-update", headers=h,
                       json={"ids": ids[1:], "field": "status_id", "value": dead}
                       ).status_code == 200

    db = database.get_db()
    rids = [c["id"] for c in db.execute(
        "SELECT id FROM recharge_records WHERE amount='清' ORDER BY id").fetchall()]
    assert len(rids) == 3, f"三个账户都应追加清账记录，实际 {rids}"
    for _ in range(300):
        rows = [_row(db, uid, "gg_recharge", str(r)) for r in rids]
        if all(x is not None and x["status"] in sheet_write.TERMINAL for x in rows):
            break
        _poll_sleep(0.02)
    rows = [_row(db, uid, "gg_recharge", str(r)) for r in rids]
    db.close()

    assert all(x is not None for x in rows), f"每条清账都必须登记 gg_recharge，实际 {rows}"
    assert [x["status"] for x in rows] == ["synced"] * 3, [x["error_msg"] for x in rows]
    cleared = {w["account_id"] for w in written if w.get("amount") == "清"}
    assert cleared == {"gg_adv_c1", "gg_adv_c2", "gg_adv_c3"}, \
        f"三户都必须被写进充值表，实际 {written}"


# ==================== Task 4：接口回传「轮询所需的 key」 ====================
# 前端在每次触发写表的操作之后要主动轮询，才能给出「即时提示」；而轮询需要知道
# 本次产生了哪些 business_key。这四个接口过去不回传，故这几条用例钉住它们。


def test_accounts_update_returns_clear_recharge_id(client, monkeypatch):
    """改状态触发自动清账时，响应必须带上该 recharge_records.id。"""
    import google_sheets_service as gs
    monkeypatch.setattr(gs, "build_service", lambda _p: object())
    monkeypatch.setattr(gs, "append_recharge", lambda *a, **k: None)
    monkeypatch.setattr(gs, "update_rows_by_account_id", lambda *a, **k: None)

    h, uid = _gg_user(client, "_gg_key1")
    db = database.get_db()
    _setup_sheets(db)
    alive = _status_id(db, "存活")
    dead = _status_id(db, "死亡")
    aid = _mk_account(db, uid, "gg_adv_k1", alive)
    # 清账只在「该户有未清充值」时触发
    db.execute("INSERT INTO recharge_records (account_id, amount, operator, created_by) "
               "VALUES ('gg_adv_k1', '100', '运营', ?)", (uid,))
    db.commit()
    db.close()

    resp = client.put(f"/api/accounts/{aid}", headers=h, json={"status_id": dead})
    assert resp.status_code == 200, resp.get_json()
    body = resp.get_json()
    assert body.get("clear_recharge_id"), \
        f"响应缺 clear_recharge_id（前端无从对 gg_recharge 轮询）：{body}"

    db = database.get_db()
    cleared = db.execute("SELECT id FROM recharge_records WHERE account_id='gg_adv_k1' "
                         "AND amount='清'").fetchone()
    db.close()
    assert cleared is not None, "应已追加清账记录"
    assert body["clear_recharge_id"] == cleared["id"], \
        "回传的 id 必须是本次清账记录的主键"


def test_accounts_update_without_clear_returns_null_key(client, monkeypatch):
    """未触发清账时仍须有该 key（值为 None）—— 前端按键取值，缺 key 会 undefined。"""
    import google_sheets_service as gs
    monkeypatch.setattr(gs, "build_service", lambda _p: object())
    monkeypatch.setattr(gs, "update_rows_by_account_id", lambda *a, **k: None)

    h, uid = _gg_user(client, "_gg_key0")
    db = database.get_db()
    _setup_sheets(db)
    alive = _status_id(db, "存活")
    dead = _status_id(db, "死亡")
    aid = _mk_account(db, uid, "gg_adv_k0", alive)   # 无任何充值记录 ⇒ 不触发清账
    db.close()

    resp = client.put(f"/api/accounts/{aid}", headers=h, json={"status_id": dead})
    assert resp.status_code == 200, resp.get_json()
    body = resp.get_json()
    assert "clear_recharge_id" in body, f"key 必须存在（可为 None）：{body}"
    assert body["clear_recharge_id"] is None


def test_batch_update_returns_clear_recharge_ids(client, monkeypatch):
    """批量改状态的响应必须带上本批全部清账记录 id。"""
    import google_sheets_service as gs
    monkeypatch.setattr(gs, "build_service", lambda _p: object())
    monkeypatch.setattr(gs, "append_recharge", lambda *a, **k: None)
    monkeypatch.setattr(gs, "update_rows_by_account_id", lambda *a, **k: None)

    h, uid = _gg_user(client, "_gg_key2")
    db = database.get_db()
    _setup_sheets(db)
    alive = _status_id(db, "存活")
    dead = _status_id(db, "死亡")
    ids = [_mk_account(db, uid, f"gg_adv_b{i}", alive) for i in (1, 2)]
    for aid in ids:
        acc = db.execute("SELECT account_id FROM accounts WHERE id=?", (aid,)).fetchone()["account_id"]
        db.execute("INSERT INTO recharge_records (account_id, amount, operator, created_by) "
                   "VALUES (?, '100', '运营', ?)", (acc, uid))
    db.commit()
    db.close()

    resp = client.post("/api/accounts/batch-update", headers=h,
                       json={"ids": ids, "field": "status_id", "value": dead})
    assert resp.status_code == 200, resp.get_json()
    body = resp.get_json()
    assert isinstance(body.get("clear_recharge_ids"), list), f"缺 clear_recharge_ids：{body}"
    assert len(body["clear_recharge_ids"]) == 2, f"两户都清账、应回传两个 id：{body}"


def test_recharge_batch_submit_returns_ids(client, monkeypatch):
    """批量充值必须回传本次产生的全部 id。"""
    import google_sheets_service as gs
    monkeypatch.setattr(gs, "build_service", lambda _p: object())
    monkeypatch.setattr(gs, "append_recharge", lambda *a, **k: None)

    h, uid = _gg_user(client, "_gg_key3")
    db = database.get_db()
    _setup_sheets(db)
    _mk_account(db, uid, "gg_adv_k3", _status_id(db, "存活"))
    db.close()

    resp = client.post("/api/recharge/batch-submit", headers=h, json={"records": [
        {"account_id": "gg_adv_k3", "amount": 10, "agent": "A"},
        {"account_id": "gg_adv_k3", "amount": 20, "agent": "A"},
    ]})
    assert resp.status_code == 200, resp.get_json()
    body = resp.get_json()
    assert isinstance(body.get("recharge_ids"), list), f"缺 recharge_ids：{body}"
    assert len(body["recharge_ids"]) == 2, f"两条充值、应回传两个 id：{body}"

    db = database.get_db()
    real = [r["id"] for r in db.execute(
        "SELECT id FROM recharge_records WHERE account_id='gg_adv_k3' ORDER BY id").fetchall()]
    db.close()
    assert body["recharge_ids"] == real, "回传的必须是真实落库的主键"


def test_sync_from_sheet_returns_affected_account_ids(client, monkeypatch):
    """从表同步的回写腿涉及哪些账户，必须回传（前端靠它轮询看板写表）。

    假表格的列布局按现场解析器写死：row[0]=运营（须匹配当前用户 display_name）、
    row[1]=账户ID、row[7]=是否解绑。表头行被跳过。
    """
    import google_sheets_service as gs
    monkeypatch.setattr(gs, "build_service", lambda _p: object())
    monkeypatch.setattr(gs, "update_rows_by_account_id", lambda *a, **k: None)
    # 端点前置校验 credentials_path 必须是真实存在的文件（main.py:5246），
    # 否则在读到表格之前就 400 —— 与既有一期用例同样用 __file__ 顶上。
    import main
    monkeypatch.setitem(main._GOOGLE_SHEETS_CONFIG, "credentials_path", __file__)
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
        f"回写腿涉及的账户应被回传（不能是空表）：{body}"
