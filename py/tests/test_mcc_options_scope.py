"""MCC 候选口径（2026-11-11 用户定稿）：**全部 MCC 对全部投手开放**。

历史：
- 最初按 owner ∪ shared_user_ids 收窄 → 新投手（名下 0 个 MCC）看不到顶级 MCC，
  账户页下拉为空（「选不到 MCC」）；
- 2026-11-06 试过「自己创建 ∪ 自己产品用到」，仍不够 —— 用户 2026-11-11 明确：
  「顶级的 mcc 应该是每个投手都有的，改为全部投手都有权限，广告账户那边也是」；
- 现口径：列表 / 详情 / 两个 MCC 下拉一律全量；**改、删、关联（写）仍按 owner 或
  跨用户角色**，见 `_mcc_visible` 与 `test_lookup_ownership.py`。
"""

import json

import database


def _mk_mcc(db, name, mcc_id, owner_id, shared=None):
    db.execute(
        "INSERT INTO mcc(name, mcc_id, owner_id, shared_user_ids) VALUES(?,?,?,?)",
        (name, mcc_id, owner_id, json.dumps(shared or [])),
    )
    return db.execute("SELECT last_insert_rowid()").fetchone()[0]


def _register(client, username, role="user", platform="gg"):
    client.post("/api/auth/register", json={"username": username, "password": "test123"})
    db = database.get_db()
    db.execute("UPDATE users SET role=?, platform=? WHERE username=?", (role, platform, username))
    db.commit()
    uid = db.execute("SELECT id FROM users WHERE username=?", (username,)).fetchone()["id"]
    db.close()
    return uid


def _option_names(client, headers):
    res = client.get("/api/mcc/options", headers=headers)
    assert res.status_code == 200
    return [o["name"] for o in res.get_json()["options"]]


class TestMccOptionsScope:
    def test_regular_user_sees_others_mcc(self, client, auth_headers):
        """普通投手（非 owner、无产品、没被共享）也能选到顶级 MCC。"""
        other_id = _register(client, "mccother10")
        db = database.get_db()
        _mk_mcc(db, "别人的顶级MCC", "901-000-0001", other_id)
        db.commit()
        db.close()

        assert "别人的顶级MCC" in _option_names(client, auth_headers)

    def test_account_list_options_are_global(self, client, auth_headers):
        """账户页下拉（/api/accounts/list 的 mcc_options）同样是全量，且不受归属人筛选影响。"""
        other_id = _register(client, "mccother11")
        me = database.get_db()
        my_id = me.execute("SELECT id FROM users WHERE username='testuser'").fetchone()["id"]
        db = database.get_db()
        _mk_mcc(db, "别人的MCC-列表", "902-000-0001", other_id)
        _mk_mcc(db, "我的MCC-列表", "902-000-0002", my_id)
        db.commit()
        db.close()
        me.close()

        res = client.get(f"/api/accounts/list?owner_id={my_id}&size=10", headers=auth_headers)
        assert res.status_code == 200
        names = [o["name"] for o in res.get_json()["mcc_options"]]
        assert "别人的MCC-列表" in names
        assert "我的MCC-列表" in names

    def test_mcc_list_is_global_for_regular_user(self, client, auth_headers):
        """/api/mcc/list 也必须全量 —— 否则「MCC 页看得见、账户页看不见」会打架。"""
        other_id = _register(client, "mccother12")
        db = database.get_db()
        _mk_mcc(db, "MCC-列表全局", "903-000-0001", other_id)
        db.commit()
        db.close()

        res = client.get("/api/mcc/list?size=200", headers=auth_headers)
        assert res.status_code == 200
        assert "MCC-列表全局" in {m["name"] for m in res.get_json()["mcc_list"]}
