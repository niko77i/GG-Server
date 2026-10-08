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


def test_huguan_targets_register_no_rollback():
    """零回滚是本期的**设计裁定**，不是实现细节 —— 四个 target 一律不得注册 rollback。

    看板表是系统状态的投影（全镜像类），写表失败时回滚业务数据没有意义。
    而 `_apply_final` 的分支完全由 `rollback` 是否为 None 决定：

        rollback is None            → retry_failed        （镜像类：业务变更仍生效，用户自己处理）
        rollback 返回 True          → rolled_back
        rollback 返回 False / 抛异常 → rollback_abandoned

    也就是说，一旦给任一 target 注册了 rollback，该 target 的最终失败**就不再落
    retry_failed** —— 用户看到的文案（`sheetWriteHint` 按 status 分三套）、是否可重试、
    以及 T6 卡片「N 项没写进表 + 用 warning 色调」的前提全部随之失效。

    上面那条只断言了成员**存在**；这条钉住注册时的**取值**。
    去掉 register_target 的 rollback=None 默认、或给任一 target 传了 rollback ⇒ 本用例红。
    """
    import routes.huguan_sheet_targets  # noqa: F401
    for t in ("huguan_dashboard", "huguan_owner_channel",
              "operator_dashboard_remark", "huguan_fb_acceptor"):
        assert sheet_write.TARGETS[t]["rollback"] is None, (
            f"{t} 是全镜像类，不得注册 rollback —— 注册后最终失败会落 "
            f"rolled_back / rollback_abandoned 而非 retry_failed"
        )


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

    # 走**批量首跑**那条路径（`many_sync` 返回的闭包 = `run_write_many` 的 sync_fn）。
    # 直接调 `huguan_dashboard_sync` 无法判别「many_sync 只覆盖第一键」那类静默漏写
    # —— 那正是本用例要守的形态（设计 §4.3 / 计划 §12）。
    tgt.huguan_dashboard_many_sync(uid, "tt", ["hg_adv_1", "hg_adv_2", "hg_adv_3"])()
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


def test_write_background_routes_fb_acceptor_column_to_its_target(client, monkeypatch):
    """点位 #5 的 :171（FB 旧转新 → I 列）必须走 huguan_fb_acceptor。

    FB 的 I 列在 `COLUMN_SPEC` 里 `writable=False`、`OWNER_CHANNEL_COL` 又没有 fb 键
    —— 若按「其余走 huguan_dashboard（整行重建）」处理，整行刷新**碰不到** I 列，
    换绑记录会被**静默丢弃**（三期回归修复点；计划书曾误称该分支已被整行刷新覆盖）。
    """
    import google_sheets_service as gs
    import routes.huguan_dashboard_routes as hr
    monkeypatch.setattr(gs, "build_service", lambda _p: object())
    monkeypatch.setattr(gs, "update_rows_by_account_id", lambda *a, **k: None)

    h, uid = _tt_huguan(client, "_hg_p5fb")
    db = database.get_db()
    _mk_huguan_conf(db, uid, platform="fb")
    db.execute("INSERT INTO fb_accounts (name, account_id, acceptor, owner_id) "
               "VALUES ('fb_p5','hg_p5fb_a','张三转李四',?)", (uid,))
    db.commit()
    conf = __import__("huguan_dashboard").get_platform_config(db, uid, "fb")
    db.close()

    rows = [{"account_id": "hg_p5fb_a", "cells": {"I": "张三转李四"}}]
    hr._write_background(conf, rows, "fb", uid)

    db = database.get_db()
    r = _settle(db, uid, "huguan_fb_acceptor", "hg_p5fb_a")
    db.close()
    assert r is not None, "FB I 列（换绑记录）必须登记 huguan_fb_acceptor"
    assert r["status"] == "synced"


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


def test_batch_create_conflict_last_still_registers_sheet_write_log(client, monkeypatch):
    """批量建户里**最后一条**撞唯一约束时，也必须登记 sheet_write_log。

    根因（2026-10-08，与 test_remark_push_registers_log_row 同批发现）：
    `batch_create_accounts` 的 `except sqlite3.IntegrityError` 分支**没有 db.rollback()**。
    sqlite3 会为那次 INSERT 开一个隐式事务，而约束冲突**不会**自动结束它；
    若失败的正是**最后一条**，循环里再没有后续 commit 来清理 ⇒ 本请求连接一直
    握着写锁，紧接着的 `hd.writeback_rows(...)` 经 run_write 在**另一条连接**上
    record_pending ⇒ 等满 `timeout=30` 抛 "database is locked"，被 run_write 的
    except 吞掉：请求线程白冻 30 秒，且 sheet_write_log **一行都不落**
    （这次失败从此看不见、也无法重试）。

    触发条件正是「冲突在最后一条」—— 冲突在中间时，后面那条成功后的 commit
    会顺手把悬着的事务清掉，所以这个 bug 只在特定顺序下出现（易漏测）。
    去掉 `:496` 的 `db.rollback()` ⇒ 本用例红（实测 32.25s 且查不到行，
    调换顺序 `[DUP, NEW]` 或只传 `[NEW]` 则 0.03s 通过 —— 对照见 fix-deadlock-review.md）。
    """
    import google_sheets_service as gs
    monkeypatch.setattr(gs, "build_service", lambda _p: object())
    monkeypatch.setattr(gs, "update_rows_by_account_id", lambda *a, **k: None)

    h, uid = _tt_huguan(client, "_hg_bc")
    db = database.get_db()
    _mk_huguan_conf(db, uid)
    NEW, DUP = "770001", "770002"
    db.execute("DELETE FROM tt_accounts WHERE advertiser_id IN (?,?)", (NEW, DUP))
    # 让**最后一条**撞唯一约束：DUP 先入库，请求里放在 NEW 之后
    db.execute("INSERT INTO tt_accounts (advertiser_id, name, owner_id) VALUES (?,?,?)",
               (DUP, DUP, uid))
    db.commit()
    db.close()

    resp = client.post("/api/tt/accounts/batch-create", headers=h,
                       json={"account_ids": [NEW, DUP]})
    assert resp.status_code == 200, resp.get_data(as_text=True)[:200]
    body = resp.get_json()
    assert NEW in (body["created_ids"] or []), f"应先建成 NEW：{body}"
    assert DUP in [s["advertiser_id"] for s in (body["skipped"] or [])], f"末条应被跳过：{body}"

    db = database.get_db()
    r = _settle(db, uid, "huguan_dashboard", NEW)
    db.close()
    assert r is not None, (
        "批量建户成功后必须登记 huguan_dashboard —— 查不到就说明最后一条撞唯一约束"
        "留下的未提交写事务把 record_pending 挡到 database is locked 并被吞掉了"
    )
    assert r["status"] == "synced", f"应同步成功，实际 {r['status']}"
