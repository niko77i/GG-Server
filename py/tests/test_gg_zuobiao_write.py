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


def _seed_zuobiao(db, uid, product="产品甲", acc="acc_1", date="2026-10-01", region="US"):
    """种一条做表数据。ad_reports 的 region / report_date 都是 NOT NULL（见 database.py 建表）。"""
    db.execute(
        "INSERT INTO ad_reports (user_id, product_name, region, report_date, account, "
        "customer_id, campaign, cost) VALUES (?,?,?,?,?,?,?,?)",
        (uid, product, region, date, acc, "c1", "camp", 1))
    db.commit()


def _setup_zuobiao_config(client, hdr):
    """配好该用户的 Google 表格 —— 保存端点靠它（active_id → sheets 列表）解析 spreadsheet_id。"""
    resp = client.post("/api/config/google-sheets", headers=hdr,
                       json={"sheets": [{"id": "m1", "spreadsheet_id": "SHEET_ZB"}],
                             "active_id": "m1"})
    assert resp.status_code == 200, resp.get_data(as_text=True)[:200]


def test_gg_zuobiao_target_registered_without_rollback():
    """target 必须已注册（漏 import 就 KeyError ⇒ 500），且**不注册 rollback**。"""
    import routes.gg_zuobiao_target  # noqa: F401
    assert "gg_zuobiao" in sheet_write.TARGETS, "target 未注册"
    assert sheet_write.TARGETS["gg_zuobiao"]["rollback"] is None, \
        "镜像类不得注册 rollback（会让最终失败落 rolled_back 而非 retry_failed）"


def test_gg_zuobiao_kwargs_rebuilds_from_db(client):
    """重建必须给出 `upsert_zuobiao` 的实参（做表数据可从 DB 重算）。"""
    import routes.gg_zuobiao_target as tgt
    hdr, uid = _gg_user(client, "_zb_kw")
    _setup_zuobiao_config(client, hdr)      # 无表格配置 ⇒ 重建会以「表格 ID 为空」早退
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
    assert "没有找到" in why, f"原因应可读，实际 {why}"


def test_gg_zuobiao_final_failure_lands_retry_failed(client, monkeypatch):
    """最终失败落 retry_failed（**不是** rolled_back）—— 零回滚守卫。"""
    import google_sheets_service as gs
    import time as _time
    monkeypatch.setattr(_time, "sleep", lambda _s: None)
    monkeypatch.setattr(gs, "build_service", lambda _p: object())

    def _boom(*a, **k):
        raise RuntimeError("Sheets 配额超限")

    monkeypatch.setattr(gs, "upsert_zuobiao", _boom)

    hdr, uid = _gg_user(client, "_zb_fail")
    _setup_zuobiao_config(client, hdr)      # 让失败真的发生在 Sheets 调用上（而非配置早退）
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


def test_gg_zuobiao_rebuild_uses_payload_product_not_hardcoded(client, monkeypatch):
    """**真正走 rebuild 的用例**：写表用的产品名必须来自 payload，而非任何写死值。

    钉住简报 Step 6 那处变异：把 `_gg_zuobiao_rebuild` 里的
    `gg_zuobiao_sync(user_id, product_name)` 换成写死的
    `gg_zuobiao_sync(user_id, "写死的产品名")` ⇒ 本用例必红（payload 用的是「产品丙」）。

    为什么**不能**拿终态那条当变异判据：无论写死哪一组（该组无数据 / 表格 ID 为空），
    `gg_zuobiao_sync` 都会抛错 ⇒ 终态同样是 retry_failed ⇒ 那条**不具判别力**
    （四期栽过的「指定的变异不具判别力」）。
    """
    import google_sheets_service as gs
    import routes.gg_zuobiao_target as tgt
    written = []
    monkeypatch.setattr(gs, "build_service", lambda _p: object())
    monkeypatch.setattr(gs, "upsert_zuobiao",
                        lambda service, **k: written.append(k["product_name"]))

    hdr, uid = _gg_user(client, "_zb_rebuild")
    _setup_zuobiao_config(client, hdr)
    db = database.get_db()
    # payload 那一组（本用例期望被写出的）
    _seed_zuobiao(db, uid, "产品丙", acc="acc_payload")
    # 简报 Step 6 变异写死的那一组：实现若退化成写死值，写出的就是它，断言随即可见
    _seed_zuobiao(db, uid, "写死的产品名", acc="acc_hardcoded")
    db.close()

    key = tgt.gg_zuobiao_key("产品丙")
    payload = {"product_name": "产品丙"}
    sheet_write.build_sync("gg_zuobiao", uid, key, payload)()

    assert written == ["产品丙"], f"重建必须用 payload 里的产品名，实际 {written}"


# ---------------------------------------------------------------------------
# 按月匹配（三级回退的**第 1 级**）—— 本期最高风险分支的回归守卫
#
# 做表表按月切：`_zuobiao_spreadsheet_id` 要按「操作人名 + YYYY.MM」在
# `sheets[].spreadsheet_name` 里找当月那张；错了会**静默写到别的月份的表里**。
#
# 上面各用例发的 sheet 都**没有 `spreadsheet_name`** ⇒ `matched` 恒 None ⇒ 只走到
# 第 2 级（active_config）。第 1 级此前只被读代码核过、零回归守卫。下面两条补上，
# 并刻意让「第一张」与「active」指向**不同**的 spreadsheet_id，好把两个退化方向
# （写成 return active / return sheets[0]）分别钉死。
# ---------------------------------------------------------------------------

def _set_monthly_sheets(client, hdr):
    """给某用户配三张做表表：第一张 / active / 当月（指向各不相同的 spreadsheet_id）。

    当月那张的 `spreadsheet_name` 含 `_zb_month2026.10`（= 操作人名 + 该条
    `ad_reports` 的 `report_date` 月键），另两张是别的月份 ⇒ 只有「按月匹配」这一级
    才会选中 SHEET_MONTH。
    """
    resp = client.post("/api/config/google-sheets", headers=hdr, json={
        "sheets": [
            {"id": "m0", "spreadsheet_id": "SHEET_FIRST",
             "spreadsheet_name": "_zb_month2026.08"},
            {"id": "m1", "spreadsheet_id": "SHEET_ACTIVE",
             "spreadsheet_name": "_zb_month2026.09"},
            {"id": "m2", "spreadsheet_id": "SHEET_MONTH",
             "spreadsheet_name": "做表_zb_month2026.10"},
        ],
        "active_id": "m1",
    })
    assert resp.status_code == 200, resp.get_data(as_text=True)[:200]


def test_zuobiao_spreadsheet_id_matches_monthly_sheet(client):
    """第 1 级：命中「操作人名 + YYYY.MM」的那张 —— 不是 active，也不是第一张。

    判别力：把匹配那一支改坏（如 `return active_config["spreadsheet_id"]`）⇒ 本用例
    取到 SHEET_ACTIVE ⇒ 必红（漏掉按月匹配就会写到别的月份的表里）。
    """
    import routes.gg_zuobiao_target as tgt
    hdr, uid = _gg_user(client, "_zb_month")
    db = database.get_db()
    db.execute("UPDATE users SET display_name='_zb_month' WHERE id=?", (uid,))
    _seed_zuobiao(db, uid, "产品甲", date="2026-10-01")   # 月键 = 2026.10
    db.commit()
    db.close()
    _set_monthly_sheets(client, hdr)

    db = database.get_db()
    kwargs, why = tgt.gg_zuobiao_kwargs(db, uid, "产品甲")
    db.close()
    assert why is None, f"应能重建，实际 {why}"
    assert kwargs["spreadsheet_id"] == "SHEET_MONTH", \
        f"必须按月匹配（操作人名+YYYY.MM），实际 {kwargs['spreadsheet_id']}"
    assert kwargs["spreadsheet_id"] not in ("SHEET_ACTIVE", "SHEET_FIRST"), \
        f"不得退回 active/第一张，实际 {kwargs['spreadsheet_id']}"


def test_zuobiao_spreadsheet_id_falls_back_to_active_when_no_month_match(client):
    """第 1 级不命中 ⇒ 回退第 2 级 active_config（**不是** `sheets[0]`）。

    判别力：把回退顺序写反（先取 `sheets[0]`）⇒ 本用例取到 SHEET_FIRST ⇒ 必红。
    """
    import routes.gg_zuobiao_target as tgt
    hdr, uid = _gg_user(client, "_zb_nomatch")
    db = database.get_db()
    db.execute("UPDATE users SET display_name='_zb_nomatch' WHERE id=?", (uid,))
    _seed_zuobiao(db, uid, "产品甲", date="2026-10-01")   # 月键 = 2026.10
    db.commit()
    db.close()
    # 两张表的名字都**不含** _zb_nomatch2026.10 ⇒ 按月匹配落空
    resp = client.post("/api/config/google-sheets", headers=hdr, json={
        "sheets": [
            {"id": "m0", "spreadsheet_id": "SHEET_FIRST",
             "spreadsheet_name": "_zb_nomatch2026.08"},
            {"id": "m1", "spreadsheet_id": "SHEET_ACTIVE",
             "spreadsheet_name": "_zb_nomatch2026.09"},
        ],
        "active_id": "m1",
    })
    assert resp.status_code == 200, resp.get_data(as_text=True)[:200]

    db = database.get_db()
    kwargs, why = tgt.gg_zuobiao_kwargs(db, uid, "产品甲")
    db.close()
    assert why is None, f"应能重建，实际 {why}"
    assert kwargs["spreadsheet_id"] == "SHEET_ACTIVE", \
        f"按月不命中应回退 active_config，实际 {kwargs['spreadsheet_id']}"
