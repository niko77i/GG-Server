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


# ---------------------------------------------------------------------------
# 写点 ①：/api/google-sheets/update-zuobiao 改走统一入口
# ---------------------------------------------------------------------------

def test_update_zuobiao_registers_and_does_not_block(client, monkeypatch):
    """保存做表数据必须登记 gg_zuobiao，且**端点不阻塞在 Sheets 上**。"""
    import google_sheets_service as gs
    import time as _time
    # Sheets 层做成"很慢"：若端点同步直写，这条会超时；治理后它只是登记
    monkeypatch.setattr(gs, "build_service", lambda _p: object())
    monkeypatch.setattr(gs, "upsert_zuobiao", lambda **k: _time.sleep(2))

    hdr, uid = _gg_user(client, "_zb_save")
    _setup_zuobiao_config(client, hdr)      # 配好表格 ID 等前置

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


def test_update_zuobiao_registers_when_write_block_runs(client, monkeypatch):
    """带 region/report_date ⇒ 端点自身写库分支真的执行时，也必须登记成功。

    这条钉住现场陷阱：写库分支末尾的 `db2.close()` 关掉的正是请求级 g 共享连接
    （`_yt_db()` 的 `db` 与 `db2` **是同一个对象**）。若 run_write 复用 `db`/`db2`，
    登记会在**已关闭的连接**上抛 ProgrammingError，而 run_write 会吞掉异常只记日志
    ⇒ 日志行根本不存在 ⇒ 本用例必红（上一条用例走的是 `region` 为空、写库分支被跳过
    的分支，那时 g 连接还开着，**测不出**这个陷阱）。
    """
    import google_sheets_service as gs
    monkeypatch.setattr(gs, "build_service", lambda _p: object())
    monkeypatch.setattr(gs, "upsert_zuobiao", lambda **k: None)

    hdr, uid = _gg_user(client, "_zb_save_r")
    _setup_zuobiao_config(client, hdr)

    resp = client.post("/api/google-sheets/update-zuobiao", headers=hdr, json={
        "product_name": "产品甲", "region": "US", "report_date": "2026-10-01",
        "rows": [{"account": "acc_1", "customerId": "c1", "cost": 1, "campaign": "x"}],
    })
    assert resp.status_code == 200, resp.get_data(as_text=True)[:300]
    assert resp.get_json()["db_saved"] == 1, resp.get_json()

    db = database.get_db()
    r = _settle(db, uid, "产品甲")
    db.close()
    assert r is not None, \
        "写库分支执行过后仍必须登记（不得在 db2.close() 关掉的共享连接上登记）"
    assert r["status"] == "synced", r["status"]


def test_update_zuobiao_rolls_back_when_write_block_raises(client, monkeypatch):
    """写库块中途抛异常时必须**收事务**，否则请求线程被 SQLite 写锁冻 ~30 秒 + 漏登记。

    现场陷阱：第 1 行正常落库（开启未提交写事务），第 2 行触发异常 —— 恰好落在
    「首次 DML 之后、第二次 commit() 之前」。若 except 只 `log.warning` 而不
    rollback/close，则 `db2`（= flask.g 共享连接）**持着写锁不撒手**；紧随其后的
    record_pending 走**新连接** ⇒ 等满 `timeout=30` 抛 `database is locked`（被
    run_write 吞掉）⇒ 响应冻结 ~30s 且 `sheet_write_log` 一行都没有。

    构造：第 2 行的 `impressions` 用超出 SQLite INTEGER 范围的整数（JSON 里合法），
    在第二循环 bind 参数时抛 `OverflowError`（`int(10**30)` 本身不报错，故异常点
    确实在**已有一条 DML 之后**）。
    判别力：去掉 except 里的 `db2.rollback()` ⇒ 本用例必红（零行 + elapsed≈30s）。
    """
    import google_sheets_service as gs
    import time as _time
    monkeypatch.setattr(_time, "sleep", lambda _s: None)   # 别让后台 30s 重试拖慢用例
    monkeypatch.setattr(gs, "build_service", lambda _p: object())
    monkeypatch.setattr(gs, "upsert_zuobiao", lambda **k: None)

    hdr, uid = _gg_user(client, "_zb_rb")
    _setup_zuobiao_config(client, hdr)

    t0 = _time.time()
    resp = client.post("/api/google-sheets/update-zuobiao", headers=hdr, json={
        "product_name": "产品甲", "region": "US", "report_date": "2026-10-01",
        "rows": [
            {"account": "acc_1", "customerId": "c1", "cost": 1,
             "campaign": "x", "impressions": 1},
            {"account": "acc_2", "customerId": "c2", "cost": 1,
             "campaign": "y", "impressions": 10 ** 30},
        ],
    })
    elapsed = _time.time() - t0
    assert resp.status_code == 200, resp.get_data(as_text=True)[:300]
    assert elapsed < 5.0, f"异常路径不得冻结在 SQLite 写锁上，实际 {elapsed:.2f}s"

    db = database.get_db()
    r = _row(db, uid, "产品甲")
    # 排干后台写表线程再收尾：写库块抛异常后登记仍在进行，而做表现在经 zb_rows 路径
    # 会真调 upsert_zuobiao（不再因回库重算无数据而早退）⇒ 不排干会与下一条用例的
    # monkeypatch 竞态（残留线程把数据塞进下一条的 captured）。
    _settle(db, uid, "产品甲")
    db.close()
    assert r is not None, "写库块抛异常后仍必须登记（异常路径必须收事务，不得留写锁）"


# ---------------------------------------------------------------------------
# 养户行必须继续写进做表表（T4.5 必做修复）
#
# 养户行是请求侧数据、不落库（写库块只落非养户行）⇒ DB 重建不出来。T2 改造后
# 养户行被静默丢掉（功能回退）。修法：随 payload 携带，重建时追加在 rows 末尾。
# 下面四条各钉一处：真入口携带 / 重试路径复现 / 纯养户行不早退 / 无养户行不变。
# ---------------------------------------------------------------------------

def _yanghu_row(campaign="养户广告", acc="acc_yh", cid="cyh"):
    """造一条养户行，形状与 `upsert_zuobiao` 吃的一致（ToolkitView 送来的 rows 形状）。"""
    return {"account": acc, "customerId": cid, "cost": 0, "campaign": campaign,
            "is_yanghu": True}


def test_update_zuobiao_writes_yanghu_row(client, monkeypatch):
    """真入口：请求 rows 含 1 养户行 + 1 普通行 ⇒ 写给 `upsert_zuobiao` 的 rows 含那条养户行。

    判别力：把 `_payload` 里的 `"yanghu_rows"` 去掉 ⇒ 重建出来的 rows 只有 DB 非养户行
    ⇒ 本用例红（养户行丢失，正是要修的回退）。
    """
    import google_sheets_service as gs
    import time as _time
    monkeypatch.setattr(_time, "sleep", lambda _s: None)   # 别让 30s 重试拖慢（成功路径不触发）
    captured = []
    monkeypatch.setattr(gs, "build_service", lambda _p: object())
    monkeypatch.setattr(gs, "upsert_zuobiao", lambda service, **k: captured.append(k["rows"]))

    hdr, uid = _gg_user(client, "_zb_yh")
    _setup_zuobiao_config(client, hdr)

    resp = client.post("/api/google-sheets/update-zuobiao", headers=hdr, json={
        "product_name": "产品甲", "region": "US", "report_date": "2026-10-01",
        "rows": [
            {"account": "acc_1", "customerId": "c1", "cost": 1, "campaign": "x"},
            _yanghu_row(),
        ],
    })
    assert resp.status_code == 200, resp.get_data(as_text=True)[:300]

    db = database.get_db()
    _settle(db, uid, "产品甲")
    db.close()

    assert captured, "必须真的调用 upsert_zuobiao（而非配置早退）"
    rows = captured[0]
    yh = [r for r in rows if r.get("is_yanghu")]
    assert len(yh) == 1, f"养户行必须恰好 1 条（不许重复/漏），实际 {yh}"
    assert yh[0]["campaign"] == "养户广告", yh[0]
    assert yh[0]["is_yanghu"] is True, yh[0]


def test_gg_zuobiao_retry_keeps_yanghu_rows(client, monkeypatch):
    """重试路径（重启后）：从登记行读回 payload_json 再 build_sync ⇒ 仍带养户行。

    判别力：把 `gg_zuobiao_kwargs` 里的 `+ list(yanghu_rows or [])` 去掉 ⇒ 重试重建
    出来的 rows 只剩 DB 非养户行 ⇒ 本用例红。
    """
    import json
    import google_sheets_service as gs
    import routes.gg_zuobiao_target as tgt
    captured = []
    monkeypatch.setattr(gs, "build_service", lambda _p: object())
    monkeypatch.setattr(gs, "upsert_zuobiao", lambda service, **k: captured.append(k["rows"]))

    hdr, uid = _gg_user(client, "_zb_retry")
    _setup_zuobiao_config(client, hdr)
    db = database.get_db()
    _seed_zuobiao(db, uid, "产品甲")
    key = tgt.gg_zuobiao_key("产品甲")
    payload = {"product_name": "产品甲", "yanghu_rows": [_yanghu_row()],
               "report_date": "2026-10-01", "region": "US"}
    # 只登记、不真写（sync_fn 用 no-op）：这里验证的是 payload_json 的持久化与重试复现
    sheet_write.run_write(db, user_id=uid, platform="gg", target="gg_zuobiao",
                          business_key=key, sync_fn=lambda: None, payload=payload)
    row = _row(db, uid, key)
    db.close()
    assert row is not None and row["payload_json"], "登记必须持久化 payload"

    # 模拟重试端点：读回 payload_json 再交给 build_sync
    payload2 = json.loads(row["payload_json"])
    sheet_write.build_sync("gg_zuobiao", uid, key, payload2)()

    assert captured, "重试必须真的调用 upsert_zuobiao"
    yh = [r for r in captured[0] if r.get("is_yanghu")]
    assert len(yh) == 1, f"重试重建必须仍带养户行，实际 {yh}"
    assert yh[0]["campaign"] == "养户广告", yh[0]


def test_zuobiao_writes_pure_yanghu_rows(client, monkeypatch):
    """纯养户行：ad_reports 无该产品行、请求 rows 全是养户行 ⇒ 仍写出（不得早退）。

    判别力：把 `if not rows_raw and not yanghu_rows:` 改回 `if not rows_raw:` ⇒ 本用例
    在「没有找到对应的做表数据」处早退 ⇒ upsert 从不被调用、终态 retry_failed ⇒ 红。
    """
    import google_sheets_service as gs
    import time as _time
    monkeypatch.setattr(_time, "sleep", lambda _s: None)
    captured = []
    monkeypatch.setattr(gs, "build_service", lambda _p: object())
    monkeypatch.setattr(gs, "upsert_zuobiao", lambda service, **k: captured.append(k["rows"]))

    hdr, uid = _gg_user(client, "_zb_pure_yh")
    _setup_zuobiao_config(client, hdr)

    resp = client.post("/api/google-sheets/update-zuobiao", headers=hdr, json={
        "product_name": "产品甲", "region": "US", "report_date": "2026-10-01",
        "rows": [_yanghu_row("养户1"), _yanghu_row("养户2", acc="acc_yh2", cid="cyh2")],
    })
    assert resp.status_code == 200, resp.get_data(as_text=True)[:300]

    db = database.get_db()
    r = _settle(db, uid, "产品甲")
    db.close()
    assert r is not None and r["status"] == "synced", \
        f"纯养户行也必须写出（不得早退成「没有找到」），实际 {r and r['status']}"
    assert captured, "纯养户行必须真的调用 upsert_zuobiao"
    rows = captured[0]
    assert len(rows) == 2, f"两条养户行都应写出，实际 {rows}"
    assert all(r.get("is_yanghu") for r in rows), f"应全是养户行，实际 {rows}"


def test_zuobiao_no_yanghu_unchanged(client, monkeypatch):
    """无养户行：请求 rows 无 is_yanghu ⇒ 行为与现状一致（不报错、写出的行无养户行）。

    判别力：若空 `yanghu_rows` 的处理把非养户行误标/追加出错 ⇒ 本用例在「写出无养户行」
    或「终态 synced」上红。
    """
    import google_sheets_service as gs
    import time as _time
    monkeypatch.setattr(_time, "sleep", lambda _s: None)
    captured = []
    monkeypatch.setattr(gs, "build_service", lambda _p: object())
    monkeypatch.setattr(gs, "upsert_zuobiao", lambda service, **k: captured.append(k["rows"]))

    hdr, uid = _gg_user(client, "_zb_no_yh")
    _setup_zuobiao_config(client, hdr)

    resp = client.post("/api/google-sheets/update-zuobiao", headers=hdr, json={
        "product_name": "产品甲", "region": "US", "report_date": "2026-10-01",
        "rows": [{"account": "acc_1", "customerId": "c1", "cost": 1, "campaign": "x"}],
    })
    assert resp.status_code == 200, resp.get_data(as_text=True)[:300]

    db = database.get_db()
    r = _settle(db, uid, "产品甲")
    db.close()
    assert r is not None and r["status"] == "synced", \
        f"无养户行也应正常写出，实际 {r and r['status']}"
    assert captured, "无养户行也必须调用 upsert_zuobiao"
    rows = captured[0]
    assert rows and all(not r.get("is_yanghu") for r in rows), \
        f"无养户行时写出的行不得有养户行，实际 {rows}"


# ---------------------------------------------------------------------------
# 重建只取**当月**行（I1：多月份串月会静默污染当月表）
#
# ad_reports 对同一产品累积多个月份的行、且本仓没有任何按月清理逻辑 ⇒ 重建若不按
# `report_date` 过滤，会把旧月行以当月日期写进当月表（表键含 date，旧月行查不到 ⇒
# 被 append 成当月日期的重复行）。三条各钉一处：真入口 / 重试路径 / 无日期兼容。
# ---------------------------------------------------------------------------

def test_update_zuobiao_rebuild_takes_only_current_month(client, monkeypatch):
    """真入口：多月份不串月。预种 9 月行，再经 POST 保存 10 月行 ⇒ 重建只取 10 月。

    判别力：去掉 `gg_zuobiao_kwargs` 里的 `if report_date: where += " AND report_date=?"`
    过滤（恢复成全月份查询）⇒ 9 月行（acc_sep）也被写进 10 月表 ⇒ 本用例必红。
    """
    import google_sheets_service as gs
    import time as _time
    monkeypatch.setattr(_time, "sleep", lambda _s: None)   # 成功路径不触发 30s 重试，防御性打桩
    captured = []
    monkeypatch.setattr(gs, "build_service", lambda _p: object())
    monkeypatch.setattr(gs, "upsert_zuobiao", lambda service, **k: captured.append(k))

    hdr, uid = _gg_user(client, "_zb_monthonly")
    _setup_zuobiao_config(client, hdr)
    # 预种一条 9 月的行 —— 若重建不加月份过滤，它会被以 10 月日期写进 10 月表
    db = database.get_db()
    _seed_zuobiao(db, uid, "产品甲", acc="acc_sep", date="2026-09-01")
    db.close()

    resp = client.post("/api/google-sheets/update-zuobiao", headers=hdr, json={
        "product_name": "产品甲", "region": "US", "report_date": "2026-10-01",
        "rows": [{"account": "acc_oct", "customerId": "c2", "cost": 1, "campaign": "x"}],
    })
    assert resp.status_code == 200, resp.get_data(as_text=True)[:300]

    db = database.get_db()
    _settle(db, uid, "产品甲")
    db.close()

    assert captured, "必须真的调用 upsert_zuobiao（而非配置早退）"
    k = captured[0]
    accounts = [r["account"] for r in k["rows"]]
    assert "acc_oct" in accounts, f"当月行必须写出，实际 {accounts}"
    assert "acc_sep" not in accounts, f"旧月行不得串进当月表，实际 {accounts}"
    assert k["report_date"] == "2026-10-01", f"report_date 应为当月，实际 {k['report_date']}"


def test_gg_zuobiao_retry_takes_only_current_month(client, monkeypatch):
    """重试路径（build_sync）同样只取当月：payload 带 report_date ⇒ 过滤掉旧月行。

    判别力：与真入口同 —— 去掉月份过滤后，9 月行（acc_sep）也会被写出 ⇒ 必红。
    """
    import google_sheets_service as gs
    import routes.gg_zuobiao_target as tgt
    captured = []
    monkeypatch.setattr(gs, "build_service", lambda _p: object())
    monkeypatch.setattr(gs, "upsert_zuobiao", lambda service, **k: captured.append(k))

    hdr, uid = _gg_user(client, "_zb_retry_month")
    _setup_zuobiao_config(client, hdr)
    db = database.get_db()
    _seed_zuobiao(db, uid, "产品甲", acc="acc_sep", date="2026-09-01")
    _seed_zuobiao(db, uid, "产品甲", acc="acc_oct", date="2026-10-01")
    db.close()

    key = tgt.gg_zuobiao_key("产品甲")
    payload = {"product_name": "产品甲", "report_date": "2026-10-01", "region": "US"}
    sheet_write.build_sync("gg_zuobiao", uid, key, payload)()

    assert captured, "重试必须真的调用 upsert_zuobiao"
    k = captured[0]
    accounts = [r["account"] for r in k["rows"]]
    assert "acc_oct" in accounts, f"当月行必须写出，实际 {accounts}"
    assert "acc_sep" not in accounts, f"旧月行不得串进当月表，实际 {accounts}"
    assert k["report_date"] == "2026-10-01", f"report_date 应为当月，实际 {k['report_date']}"


def test_gg_zuobiao_kwargs_without_date_no_filter(client):
    """无 report_date ⇒ 不加月份过滤（兼容「payload 里没有日期」的场合）。

    预种两个月 ⇒ 不带日期时**两个月的行都应重建出来**（证明没被过滤），且不报错。
    """
    import routes.gg_zuobiao_target as tgt
    hdr, uid = _gg_user(client, "_zb_nodate")
    _setup_zuobiao_config(client, hdr)
    db = database.get_db()
    _seed_zuobiao(db, uid, "产品甲", acc="acc_sep", date="2026-09-01")
    _seed_zuobiao(db, uid, "产品甲", acc="acc_oct", date="2026-10-01")
    db.close()

    db = database.get_db()
    kwargs, why = tgt.gg_zuobiao_kwargs(db, uid, "产品甲")
    db.close()
    assert why is None, f"应能重建，实际 {why}"
    accounts = {r["account"] for r in kwargs["rows"]}
    assert accounts == {"acc_sep", "acc_oct"}, \
        f"不带日期时不得过滤月份，实际 {accounts}"


def test_update_zuobiao_backfill_prior_month_uses_input_month(client, monkeypatch):
    """补录旧月（入参月 ≠ DB 最新月）也必须按**入参**月过滤 —— 钉死「按 DB 最新月过滤」退化。

    现有 a/b 用例的测试数据里入参月恰好 = DB 最新月（都是 2026-10）、c 不传日期 ⇒
    分不清「按入参月过滤」与「按 DB 最新月过滤」两种实现。但 report_date 完全由客户端
    决定（保存端点无「≥ 最新月」校验）、ad_reports 又无按月清理 ⇒ 客户端可在 10 月已
    存在后补录 9 月。此时入参月（9 月）≠ DB 最新月（10 月），若实现退化成
    「按 MAX(report_date) 过滤」，补录的 9 月行被静默丢弃、反而重写 10 月行 —— 与 I1
    同族的静默数据错误。

    判别力：把 `gg_zuobiao_kwargs` 的过滤值从入参 `report_date` 换成「先查该产品
    MAX(report_date) 再拿它过滤」⇒ 本用例必红（10 月行漏进来 + report_date 变成 10 月）。
    """
    import google_sheets_service as gs
    import time as _time
    monkeypatch.setattr(_time, "sleep", lambda _s: None)   # 成功路径不触发 30s 重试，防御性打桩
    captured = []
    monkeypatch.setattr(gs, "build_service", lambda _p: object())
    monkeypatch.setattr(gs, "upsert_zuobiao", lambda service, **k: captured.append(k))

    hdr, uid = _gg_user(client, "_zb_backfill")
    _setup_zuobiao_config(client, hdr)
    # 预种：该产品已有 10 月行（DB 最新月 = 10 月）
    db = database.get_db()
    _seed_zuobiao(db, uid, "产品甲", acc="acc_oct", date="2026-10-01")
    db.close()

    # 经真实 POST 补录 9 月行：入参月（9 月）≠ DB 最新月（10 月）
    resp = client.post("/api/google-sheets/update-zuobiao", headers=hdr, json={
        "product_name": "产品甲", "region": "US", "report_date": "2026-09-01",
        "rows": [{"account": "acc_sep", "customerId": "c2", "cost": 1, "campaign": "x"}],
    })
    assert resp.status_code == 200, resp.get_data(as_text=True)[:300]

    db = database.get_db()
    _settle(db, uid, "产品甲")
    db.close()

    assert captured, "必须真的调用 upsert_zuobiao（而非配置早退）"
    k = captured[0]
    accounts = [r["account"] for r in k["rows"]]
    assert "acc_sep" in accounts, f"补录的 9 月行必须写出，实际 {accounts}"
    assert "acc_oct" not in accounts, f"10 月行不得被误写进 9 月表，实际 {accounts}"
    assert k["report_date"] == "2026-09-01", \
        f"report_date 应为入参月 9 月，实际 {k['report_date']}"


# ---------------------------------------------------------------------------
# 做表数据「预览里有的行/金额，写到 Google 表上对不上、漏了很多」—— 三处口径统一
# ---------------------------------------------------------------------------

def test_update_zuobiao_accumulates_same_key_rows(client, monkeypatch):
    """入库同键（日期+产品+账户+客户ID+系列）的多行必须**求和**，不得后写覆盖前写。

    判别力：两行同 account/customerId/campaign、不同 cost/impressions 等 ⇒ 若仍是
    覆盖，库里 cost 只剩后一行 5 ⇒ 本用例断言 15 / 150 / 7 / 4 / 4 / 3.75 必红。
    """
    import google_sheets_service as gs
    monkeypatch.setattr(gs, "build_service", lambda _p: object())
    monkeypatch.setattr(gs, "upsert_zuobiao", lambda **k: None)

    hdr, uid = _gg_user(client, "_zb_accum")
    _setup_zuobiao_config(client, hdr)

    resp = client.post("/api/google-sheets/update-zuobiao", headers=hdr, json={
        "product_name": "产品甲", "region": "US", "report_date": "2026-10-01",
        "rows": [
            {"account": "acc_1", "customerId": "c1", "campaign": "x", "cost": 10,
             "impressions": 100, "clicks": 5, "installs": 3, "inAppActions": 1,
             "costPerInApp": 2},
            {"account": "acc_1", "customerId": "c1", "campaign": "x", "cost": 5,
             "impressions": 50, "clicks": 2, "installs": 1, "inAppActions": 3,
             "costPerInApp": 4},
        ],
    })
    assert resp.status_code == 200, resp.get_data(as_text=True)[:300]
    assert resp.get_json()["db_saved"] == 1, resp.get_json()

    db = database.get_db()
    row = db.execute(
        "SELECT cost, impressions, clicks, installs, in_app_actions, cost_per_in_app "
        "FROM ad_reports WHERE user_id=? AND product_name=? AND report_date=?",
        (uid, "产品甲", "2026-10-01")).fetchone()
    db.close()
    assert row is not None, "同键两行应累加成一行"
    assert row["cost"] == 15, f"cost 应累加为 15，实际 {row['cost']}"
    assert row["impressions"] == 150, row["impressions"]
    assert row["clicks"] == 7, row["clicks"]
    assert row["installs"] == 4, row["installs"]
    assert row["in_app_actions"] == 4, row["in_app_actions"]
    assert abs(row["cost_per_in_app"] - 3.75) < 1e-9, \
        f"cost_per_in_app 应重算为 15/4=3.75，实际 {row['cost_per_in_app']}"


def test_update_zuobiao_sheet_uses_preview_rows_not_db(client, monkeypatch):
    """做表必须用本次解析的预览 rows（含养户），不回库重算 raw_rows 的细粒度行。

    判别力：raw_rows 两行（同 客户ID+系列、不同账户）入库成 2 行；rows 是聚合后的
    1 行预览。若写表仍回库重算 ⇒ 写出 2 行（细粒度）⇒ 本用例断言 1 行 ⇒ 必红。
    """
    import google_sheets_service as gs
    import time as _time
    monkeypatch.setattr(_time, "sleep", lambda _s: None)
    captured = []
    monkeypatch.setattr(gs, "build_service", lambda _p: object())
    monkeypatch.setattr(gs, "upsert_zuobiao", lambda service, **k: captured.append(k["rows"]))

    hdr, uid = _gg_user(client, "_zb_preview")
    _setup_zuobiao_config(client, hdr)

    resp = client.post("/api/google-sheets/update-zuobiao", headers=hdr, json={
        "product_name": "产品甲", "region": "US", "report_date": "2026-10-01",
        "rows": [{"account": "", "customerId": "c1", "cost": 10, "campaign": "x"}],
        "raw_rows": [
            {"account": "acc_1", "customerId": "c1", "cost": 6, "campaign": "x"},
            {"account": "acc_2", "customerId": "c1", "cost": 4, "campaign": "x"},
        ],
    })
    assert resp.status_code == 200, resp.get_data(as_text=True)[:300]

    db = database.get_db()
    _settle(db, uid, "产品甲")
    db.close()

    assert captured, "必须真的调用 upsert_zuobiao"
    rows = captured[0]
    assert len(rows) == 1, f"做表必须用预览 1 行，实际 {len(rows)} 行：{rows}"
    assert float(rows[0]["cost"]) == 10, rows


def test_gg_zuobiao_kwargs_uses_zb_rows_when_present(client):
    """payload 带 zb_rows ⇒ `gg_zuobiao_kwargs` 直接用它做 rows，不回库重算、不追加养户行。"""
    import routes.gg_zuobiao_target as tgt
    hdr, uid = _gg_user(client, "_zb_zbrows")
    _setup_zuobiao_config(client, hdr)
    db = database.get_db()
    # 库里种一条无关的非养户行：若实现回库重算，它会混进 rows ⇒ 本用例必红
    _seed_zuobiao(db, uid, "产品甲", acc="acc_from_db")

    zb_rows = [{"account": "acc_zb", "customerId": "c1", "campaign": "x", "cost": 1,
                "is_yanghu": False},
               {"account": "acc_yh", "customerId": "cyh", "campaign": "养户",
                "cost": 0, "is_yanghu": True}]
    kwargs, why = tgt.gg_zuobiao_kwargs(db, uid, "产品甲", zb_rows=zb_rows,
                                        report_date="2026-10-01", region="US")
    db.close()
    assert why is None, f"应能重建，实际 {why}"
    assert kwargs["rows"] == zb_rows, \
        f"必须直接用 zb_rows（不得回库重算/追加养户行），实际 {kwargs['rows']}"


class _FakeExec:
    def __init__(self, data):
        self._data = data

    def execute(self):
        return self._data


class _FakeSheetsService:
    """挡掉真实 Google API 的假 service，记录 values().update / batchUpdate 的 body。"""

    def __init__(self, existing_values):
        self.existing_values = existing_values
        self.value_batch = []     # values().batchUpdate（更新既有行）
        self.value_update = []    # values().update（追加新行）
        self.format_batch = []    # spreadsheets().batchUpdate（格式化）

    def spreadsheets(self):
        return _FakeSpreadsheets(self)


class _FakeSpreadsheets:
    def __init__(self, svc):
        self._svc = svc

    def get(self, spreadsheetId):
        return _FakeExec({
            "properties": {"title": "op202610"},
            "sheets": [{"properties": {"title": "Sheet1", "sheetId": 0,
                                       "gridProperties": {"rowCount": 1000}}}],
        })

    def values(self):
        return _FakeValues(self._svc)

    def batchUpdate(self, spreadsheetId, body):
        self._svc.format_batch.append(body)
        return _FakeExec({})


class _FakeValues:
    def __init__(self, svc):
        self._svc = svc

    def get(self, spreadsheetId, range):
        return _FakeExec({"values": self._svc.existing_values})

    def batchUpdate(self, spreadsheetId, body):
        self._svc.value_batch.append(body)
        return _FakeExec({})

    def update(self, spreadsheetId, range, valueInputOption, body):
        self._svc.value_update.append(body)
        return _FakeExec({})


def test_upsert_zuobiao_key_includes_product():
    """写表行键必须含产品列（G 列）：同（日期,客户ID,系列）但产品不同（普通 vs 养户）
    不得互相覆盖 —— 一更新一追加，而不是两行都挤到同一行。

    判别力：键漏掉产品 ⇒ 普通行与养户行都命中同一已有行、双双 UPDATE ⇒
    updated=2 / inserted=0 ⇒ 本用例断言 updated=1 / inserted=1 必红。
    """
    import google_sheets_service as gs
    # A日期 B操作人 C账户 D客户ID E消耗 F空 G产品 H商务 I区域 J系列 K空 L代投 M N
    existing = [["2026-10-01", "op", "acc", "c1", "5", "", "产品甲", "商务", "US",
                 "x", "", "0%", "", ""]]
    svc = _FakeSheetsService(existing)

    rows = [
        {"account": "acc", "customerId": "c1", "cost": 10, "campaign": "x"},
        {"account": "acc_yh", "customerId": "c1", "cost": 7, "campaign": "x",
         "is_yanghu": True},
    ]
    result = gs.upsert_zuobiao(
        service=svc, spreadsheet_id="S", rows=rows, product_name="产品甲",
        region="US", report_date="2026-10-01", sales_person="商务",
        agency_ratio=10, operator_name="op")
    assert result == {"updated": 1, "inserted": 1}, result


# ---------------------------------------------------------------------------
# 2026-10-17：产品名带首尾空格导致商务(H)/代投比例(L) 静默写空
# ---------------------------------------------------------------------------

def test_gg_zuobiao_kwargs_finds_product_with_padded_name(client):
    """产品名在库里带首尾空格时，写表实参仍必须取到商务与代投比例。

    回归：products id=302「YN3059—GG谷歌包代投 7+1 +8户 」（尾部空格）。
    写表路径传进 `gg_zuobiao_kwargs` 的是 `.strip()` 后的名字，精确匹配
    `p.product_name=?` 匹配不到 ⇒ `sales_person` / `agency_ratio` 静默为空
    ⇒ 表上 H 列（商务）与 L 列（代投比例/服务费）空白。

    修法：查询用 `TRIM(p.product_name)=?`。本用例钉住该行为。
    """
    from routes.gg_zuobiao_target import gg_zuobiao_kwargs

    hdr, uid = _gg_user(client, "_zb_padded")
    _setup_zuobiao_config(client, hdr)

    db = database.get_db()
    sp_id = db.execute("INSERT INTO sales_persons (name) VALUES (?)", ("蓝桉",)).lastrowid
    db.execute(
        "INSERT INTO products (product_name, region, agency_ratio, sales_person_id) "
        "VALUES (?,?,?,?)", ("产品乙 ", "US", 8.0, sp_id))
    _seed_zuobiao(db, uid, product="产品乙", date="2026-10-01")
    db.commit()

    kwargs, why = gg_zuobiao_kwargs(db, uid, "产品乙", report_date="2026-10-01")
    db.close()

    assert kwargs is not None, why
    assert kwargs["sales_person"] == "蓝桉", f"H 列商务取空：{kwargs}"
    assert kwargs["agency_ratio"] == 8.0, f"L 列代投比例取空：{kwargs}"
