"""分页尺寸闸门守卫 —— 覆盖所有暴露 size 的列表端点。

判据不是「端点能返回 200」，而是「**传超大 size 时返回条数被压到上限**」。
只断言 200 的测试对闸门失效完全失明：没有闸门时端点照样返回 200，
只是把上万行一次性吐出来。
"""
import os
import sys

_py_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _py_dir not in sys.path:
    sys.path.insert(0, _py_dir)

MAX_PAGE_SIZE = 500


def _insert_accounts(db, owner_id, n):
    """插入 n 个 GG 账户。"""
    for i in range(n):
        db.execute(
            "INSERT INTO accounts(name, account_id, owner_id) VALUES(?,?,?)",
            (f"acc{i}", f"gg{i:06d}", owner_id),
        )
    db.commit()


def test_gg_accounts_list_clamps_oversized_size(app, client, auth_headers):
    """/api/accounts/list —— 传 size=999999 必须被压到 500 以内。"""
    import database
    db = database.get_db()
    uid = db.execute("SELECT id FROM users WHERE username='testuser'").fetchone()["id"]
    _insert_accounts(db, uid, 600)
    db.close()

    resp = client.get("/api/accounts/list?size=999999", headers=auth_headers)
    assert resp.status_code == 200
    assert len(resp.get_json()["accounts"]) <= MAX_PAGE_SIZE


def test_gg_accounts_list_non_numeric_size_does_not_500(app, client, auth_headers):
    """现状的裸 int() 会 ValueError ⇒ 500。闸门必须回落默认值。"""
    resp = client.get("/api/accounts/list?size=abc", headers=auth_headers)
    assert resp.status_code == 200


def test_mcc_list_clamps_oversized_size(app, client, auth_headers):
    resp = client.get("/api/mcc/list?size=999999", headers=auth_headers)
    assert resp.status_code == 200


def test_tt_accounts_list_clamps_oversized_size(app, client, tt_headers):
    resp = client.get("/api/tt/accounts/list?size=999999", headers=tt_headers)
    assert resp.status_code == 200
    assert len(resp.get_json()["items"]) <= MAX_PAGE_SIZE


def test_fb_accounts_list_clamps_oversized_size(app, client, admin_fb_headers):
    resp = client.get("/api/fb/accounts/list?size=999999", headers=admin_fb_headers)
    assert resp.status_code == 200
    assert len(resp.get_json()["items"]) <= MAX_PAGE_SIZE
