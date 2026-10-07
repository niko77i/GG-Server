"""已删除账户列表分页 —— GG 与 TT 两个端点。

这两个端点在 1912 户规模下会一次性把全部已删账户吐给浏览器，
前端再全量渲染成 DOM，上万行直接卡死。
"""
import os
import sys

_py_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _py_dir not in sys.path:
    sys.path.insert(0, _py_dir)


def _seed_deleted_gg(db, owner_id, n):
    """给 owner_id 播种 n 户「已删除」的 GG 账户。

    account_id 带上 owner_id 前缀：accounts.account_id 是**全局 UNIQUE**，
    而归属隔离用例要给两个 owner 各播一批。用一个不带 owner 的全局计数器
    会在第二批撞 UNIQUE 约束。带上 owner 前缀既避开撞车，也更贴近生产数据
    （真实 account_id 本就跨 owner 全局唯一，从不复用）。
    """
    for i in range(n):
        db.execute(
            "INSERT INTO accounts(name, account_id, owner_id, deleted_at) "
            "VALUES(?,?,?,datetime('now','localtime'))",
            (f"已删{i}", f"ggdel{owner_id}-{i:06d}", owner_id),
        )
    db.commit()


def _gg_uid(db):
    return db.execute("SELECT id FROM users WHERE username='testuser'").fetchone()["id"]


def test_gg_deleted_returns_total_and_page_meta(app, client, auth_headers):
    import database
    db = database.get_db()
    _seed_deleted_gg(db, _gg_uid(db), 120)
    db.close()

    body = client.get("/api/accounts/deleted", headers=auth_headers).get_json()
    assert body["success"] is True
    assert body["total"] == 120
    assert body["page"] == 1
    assert body["size"] == 20
    assert len(body["accounts"]) == 20


def test_gg_deleted_second_page_is_disjoint(app, client, auth_headers):
    """翻页必须真的换了一批数据 —— 只断言 total 的测试测不出 OFFSET 写错。"""
    import database
    db = database.get_db()
    _seed_deleted_gg(db, _gg_uid(db), 120)
    db.close()

    p1 = client.get("/api/accounts/deleted?page=1&size=50", headers=auth_headers).get_json()
    p2 = client.get("/api/accounts/deleted?page=2&size=50", headers=auth_headers).get_json()
    ids1 = {a["account_id"] for a in p1["accounts"]}
    ids2 = {a["account_id"] for a in p2["accounts"]}
    assert len(ids1) == 50 and len(ids2) == 50
    assert not (ids1 & ids2)


def test_gg_deleted_search_filters_server_side(app, client, auth_headers):
    """分页后搜索必须走后端 —— 前端只能看到当前页，过滤会漏结果。"""
    import database
    db = database.get_db()
    _seed_deleted_gg(db, _gg_uid(db), 120)
    db.execute(
        "INSERT INTO accounts(name, account_id, owner_id, deleted_at) "
        "VALUES('独一无二', 'FINDME', ?, datetime('now','localtime'))",
        (_gg_uid(db),),
    )
    db.commit()
    db.close()

    body = client.get("/api/accounts/deleted?search=FINDME", headers=auth_headers).get_json()
    assert body["total"] == 1
    assert body["accounts"][0]["account_id"] == "FINDME"


def test_gg_deleted_excludes_live_accounts(app, client, auth_headers):
    """回归守卫：未删除的账户不得出现在已删除列表里。"""
    import database
    db = database.get_db()
    uid = _gg_uid(db)
    _seed_deleted_gg(db, uid, 3)
    db.execute("INSERT INTO accounts(name, account_id, owner_id) VALUES('活的','LIVE001',?)", (uid,))
    db.commit()
    db.close()

    body = client.get("/api/accounts/deleted", headers=auth_headers).get_json()
    assert body["total"] == 3
    assert all(a["account_id"] != "LIVE001" for a in body["accounts"])


def test_gg_deleted_only_returns_own_accounts(app, client, auth_headers):
    """数据归属隔离守卫：别人的已删账户不得出现。"""
    import database
    db = database.get_db()
    db.execute("INSERT OR IGNORE INTO users(id, username, password, role) VALUES(999,'other','x','user')")
    _seed_deleted_gg(db, 999, 5)
    _seed_deleted_gg(db, _gg_uid(db), 2)
    db.commit()
    db.close()

    body = client.get("/api/accounts/deleted?size=500", headers=auth_headers).get_json()
    assert body["total"] == 2


def test_gg_deleted_clamps_oversized_size(app, client, auth_headers):
    """本端点的 size 闸门。

    判据与 Task 2 的列表闸门相同，但**必须落在本任务**：Task 2 时点这个端点
    还没有 size 参数，传 size=999999 会返回全部行，用例在那个时点必然失败。
    """
    import database
    db = database.get_db()
    _seed_deleted_gg(db, _gg_uid(db), 600)
    db.close()

    body = client.get("/api/accounts/deleted?size=999999", headers=auth_headers).get_json()
    assert len(body["accounts"]) <= 500


def test_gg_deleted_non_numeric_size_does_not_500(app, client, auth_headers):
    """现状的裸 int() 会 ValueError ⇒ 500；闸门必须回落默认值。"""
    resp = client.get("/api/accounts/deleted?size=abc", headers=auth_headers)
    assert resp.status_code == 200


def test_gg_deleted_huge_page_does_not_500(app, client, auth_headers):
    """page 没有上界时，(page-1)*size 绑进 OFFSET 超过 2^63-1，
    SQLite 抛 OverflowError ⇒ 500。page 闸门必须钳住它。"""
    resp = client.get("/api/accounts/deleted?page=1000000000000000000", headers=auth_headers)
    assert resp.status_code == 200
