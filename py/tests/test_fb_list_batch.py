"""FB 账户列表的 BM 批量查询 —— 消除每行一次查询的 N+1。"""
import os
import sys

_py_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _py_dir not in sys.path:
    sys.path.insert(0, _py_dir)


def _seed(db, uid, n_accounts, n_bms):
    bm_ids = []
    for i in range(n_bms):
        cur = db.execute(
            "INSERT INTO fb_bms(name, bm_id, owner_id, status) VALUES(?,?,?,'active')",
            (f"BM{i}", f"bm{i:06d}", uid),
        )
        bm_ids.append(cur.lastrowid)
    acc_ids = []
    for i in range(n_accounts):
        cur = db.execute(
            "INSERT INTO fb_accounts(name, account_id, owner_id) VALUES(?,?,?)",
            (f"fb{i}", f"fbacc{i:06d}", uid),
        )
        acc_ids.append(cur.lastrowid)
    # 每个账户挂到第 (i % n_bms) 个 BM 上
    for i, aid in enumerate(acc_ids):
        db.execute(
            "INSERT INTO fb_account_bm(account_id, bm_id, is_primary) VALUES(?,?,1)",
            (aid, bm_ids[i % n_bms]),
        )
    db.commit()
    return acc_ids, bm_ids


def test_fb_list_makes_one_bm_query_not_per_row(app, client, admin_fb_headers, monkeypatch):
    """**N+1 守卫**：本页的 BM 查询次数必须是 1，不随行数增长。

    这是唯一能在**改动前先失败**的判据。行为类断言在改动前后都通过
    （现状结果是对的，只是慢），只有查询次数会变：改前 50 行 = 50 次，
    改后 = 1 次。用 `sqlite3.Connection.set_trace_callback` 观测真实执行的 SQL，
    数其中含 `fb_account_bm` 的语句。

    ⚠️ 只断言「结果正确」的测试对 N+1 完全失明 —— 而那正是本任务要修的东西。
    """
    import database
    db = database.get_db()
    uid = db.execute("SELECT id FROM users WHERE username='adminfb'").fetchone()["id"]
    _seed(db, uid, 50, 5)
    db.close()

    import routes.helpers as helpers
    seen = []

    def counting_get_db():
        conn = helpers.get_db()
        # 每次 get_db() 都设一遍是刻意的：request 级连接在 g.db 里缓存，
        # 重复设置只是替换回调，不会叠加。
        conn.set_trace_callback(lambda sql: seen.append(sql))
        return conn

    monkeypatch.setattr("routes.fb_routes.get_db", counting_get_db)

    body = client.get("/api/fb/accounts/list?size=50", headers=admin_fb_headers).get_json()
    assert body["total"] == 50

    bm_queries = [s for s in seen if "fb_account_bm" in s]
    assert len(bm_queries) == 1, (
        f"BM 查询应为 1 次（批量），实际 {len(bm_queries)} 次 —— N+1 未消除"
    )


def test_fb_list_bms_are_grouped_correctly(app, client, admin_fb_headers):
    """正确性守卫：批查之后每行的 bms 仍必须是**它自己的**那个 BM。

    把批查写错（如 GROUP BY 分组键用错、或回填时用错下标）会让所有行
    拿到同一批 BM —— 这正是「不报错但数据全错」的形态。
    """
    import database
    db = database.get_db()
    uid = db.execute("SELECT id FROM users WHERE username='adminfb'").fetchone()["id"]
    _seed(db, uid, 12, 3)
    db.close()

    body = client.get("/api/fb/accounts/list?size=500", headers=admin_fb_headers).get_json()
    assert body["total"] == 12
    assert len(body["items"]) == 12
    for item in body["items"]:
        assert len(item["bms"]) == 1, f"账户 {item['account_id']} 应恰好挂 1 个 BM"
        # BM 名必须与该账户自身的挂载对应，不是别人那批
        expected_idx = int(item["account_id"].replace("fbacc", "")) % 3
        assert item["bms"][0]["name"] == f"BM{expected_idx}"
        # 列表侧必须**带** is_primary（前端靠它标「主 BM / 位置」列）。
        # 与 deleted 侧的「必须**不带**」构成一对，双向钉死形状漂移。
        assert "is_primary" in item["bms"][0]


def test_fb_list_primary_bm_name_is_populated(app, client, admin_fb_headers):
    import database
    db = database.get_db()
    uid = db.execute("SELECT id FROM users WHERE username='adminfb'").fetchone()["id"]
    _seed(db, uid, 6, 2)
    db.close()

    body = client.get("/api/fb/accounts/list?size=500", headers=admin_fb_headers).get_json()
    # 先断言条数：否则 items 为空时下面的循环空转 0 次，测试**假通过**。
    assert body["total"] == 6
    assert len(body["items"]) == 6
    for item in body["items"]:
        assert item["primary_bm_name"].startswith("BM")


def test_fb_list_account_without_bm_gets_empty_list(app, client, admin_fb_headers):
    """没挂 BM 的账户必须得到 `bms: []` 而不是缺字段或报错。"""
    import database
    db = database.get_db()
    uid = db.execute("SELECT id FROM users WHERE username='adminfb'").fetchone()["id"]
    db.execute("INSERT INTO fb_accounts(name, account_id, owner_id) VALUES('无BM','fbnone',?)", (uid,))
    db.commit()
    db.close()

    body = client.get("/api/fb/accounts/list?size=500", headers=admin_fb_headers).get_json()
    lonely = [i for i in body["items"] if i["account_id"] == "fbnone"]
    assert len(lonely) == 1
    assert lonely[0]["bms"] == []
    assert lonely[0]["primary_bm_name"] == ""


def test_fb_deleted_list_bms_are_grouped_correctly(app, client, admin_fb_headers):
    import database
    db = database.get_db()
    uid = db.execute("SELECT id FROM users WHERE username='adminfb'").fetchone()["id"]
    acc_ids, bm_ids = _seed(db, uid, 9, 3)
    for aid in acc_ids:
        db.execute("UPDATE fb_accounts SET deleted_at=datetime('now','localtime') WHERE id=?", (aid,))
    db.commit()
    db.close()

    body = client.get("/api/fb/accounts/deleted?size=500", headers=admin_fb_headers).get_json()
    assert body["total"] == 9
    # 先断言条数：否则 items 为空时下面的循环空转 0 次，测试**假通过**。
    assert len(body["items"]) == 9
    for item in body["items"]:
        assert len(item["bms"]) == 1
        # 已删除端点的响应必须与旧的「三键」（name/id/bm_id）**逐字节兼容**：
        # 不能多出 is_primary。这里把「不带」也钉成断言 —— 否则该要求
        # 只存在于源码注释里，改回去也没人拦。
        assert "is_primary" not in item["bms"][0]


def test_fb_deleted_list_makes_one_bm_query_not_per_row(app, client, admin_fb_headers, monkeypatch):
    """**N+1 守卫（已删除端点）**：BM 查询次数必须是 1，不随行数增长。

    与 `test_fb_list_makes_one_bm_query_not_per_row` 同机制：用
    `sqlite3.Connection.set_trace_callback` 观测真实执行的 SQL，数其中含
    `fb_account_bm` 的语句。

    相邻的 `test_fb_deleted_list_bms_are_grouped_correctly` 只断言了
    `total == 9` / `len(bms) == 1` —— 这两个判据**改前改后都成立**，
    把批查改回每行一次也照样通过。唯有查询次数能在改动前先失败：
    改前 50 行 = 50 次，改后 = 1 次。
    """
    import database
    db = database.get_db()
    uid = db.execute("SELECT id FROM users WHERE username='adminfb'").fetchone()["id"]
    acc_ids, _bm_ids = _seed(db, uid, 50, 5)
    for aid in acc_ids:
        db.execute("UPDATE fb_accounts SET deleted_at=datetime('now','localtime') WHERE id=?", (aid,))
    db.commit()
    db.close()

    import routes.helpers as helpers
    seen = []

    def counting_get_db():
        conn = helpers.get_db()
        # 每次 get_db() 都设一遍是刻意的：request 级连接在 g.db 里缓存，
        # 重复设置只是替换回调，不会叠加。
        conn.set_trace_callback(lambda sql: seen.append(sql))
        return conn

    monkeypatch.setattr("routes.fb_routes.get_db", counting_get_db)

    body = client.get("/api/fb/accounts/deleted?size=50", headers=admin_fb_headers).get_json()
    assert body["total"] == 50
    assert len(body["items"]) == 50

    bm_queries = [s for s in seen if "fb_account_bm" in s]
    assert len(bm_queries) == 1, (
        f"BM 查询应为 1 次（批量），实际 {len(bm_queries)} 次 —— N+1 未消除"
    )
