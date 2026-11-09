"""账户页 / 账户弹窗的 MCC 候选口径（2026-11-06 用户定稿）。

规则：**自己创建的 MCC** ∪ **自己产品用到的 MCC**。
不是「共享给我的」（shared_user_ids 列表），也不是「全部 MCC」—— 这两条都试过并被否掉。

历史背景：
- 黑子（admin，名下 0 个 MCC）原本下拉为空 → 「账户管理里选不到 MCC」；
- 先修成「跨用户角色给全部 109 个」→ 用户否掉：「不是共享所有 MCC」；
- 最终口径：按创建人 + 产品关联，产品用到但自己没创建的也要给。
"""

import json

import database


def _mk_mcc(db, name, mcc_id, owner_id, shared=None):
    db.execute(
        "INSERT INTO mcc(name, mcc_id, owner_id, shared_user_ids) VALUES(?,?,?,?)",
        (name, mcc_id, owner_id, json.dumps(shared or [])),
    )
    return db.execute("SELECT last_insert_rowid()").fetchone()[0]


def _mk_product(db, name, owner_id, mcc_row_id, runners=None):
    db.execute(
        "INSERT INTO products(product_name, owner_id, runner_ids, mcc_id) VALUES(?,?,?,?)",
        (name, owner_id, json.dumps(runners or []), mcc_row_id),
    )


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
    def test_own_mcc_and_product_mcc_are_listed(self, client, admin_gg_headers):
        """自己创建的 + 自己产品在用的（即使 MCC 是别人创建的）。"""
        db = database.get_db()
        admin_id = db.execute("SELECT id FROM users WHERE username='admingg'").fetchone()["id"]
        other_id = _register(client, "mccother2")
        own = _mk_mcc(db, "我创建的MCC", "101-000-0001", admin_id)
        prod_mcc = _mk_mcc(db, "产品在用的别人的MCC", "101-000-0002", other_id)
        _mk_product(db, "我的产品", admin_id, prod_mcc)
        db.commit()
        db.close()

        names = _option_names(client, admin_gg_headers)
        assert "我创建的MCC" in names
        assert "产品在用的别人的MCC" in names
        assert own  # 仅用于说明

    def test_unrelated_and_merely_shared_mccs_are_not_listed(self, client, admin_gg_headers):
        """既不是我创建的、也和我的产品无关的 MCC 不该出现（含「只是共享给我」的）。"""
        db = database.get_db()
        admin_id = db.execute("SELECT id FROM users WHERE username='admingg'").fetchone()["id"]
        other_id = _register(client, "mccother3")
        _mk_mcc(db, "别人的无关MCC", "202-000-0001", other_id)
        _mk_mcc(db, "只是共享给我的MCC", "202-000-0002", other_id, shared=[admin_id])
        db.commit()
        db.close()

        names = _option_names(client, admin_gg_headers)
        assert "别人的无关MCC" not in names
        assert "只是共享给我的MCC" not in names, "旧口径（按 shared 列表）已被用户否掉"

    def test_runner_product_mcc_is_listed(self, client, auth_headers):
        """产品在跑人员也算「我的产品」：黑子就是靠这条拿到他产品的 MCC。"""
        db = database.get_db()
        me = db.execute("SELECT id FROM users WHERE username='testuser'").fetchone()["id"]
        owner_id = _register(client, "mccowner3")
        mcc_row = _mk_mcc(db, "我跑的产品的MCC", "303-000-0001", owner_id)
        _mk_product(db, "我当在跑的产品", owner_id, mcc_row, runners=[me])
        db.commit()
        db.close()

        assert "我跑的产品的MCC" in _option_names(client, auth_headers)

    def test_account_list_options_not_narrowed_by_owner_filter(self, client, admin_gg_headers):
        """账户页下拉读的是 /api/accounts/list 的 mcc_options，不能跟「归属人」筛选收窄。"""
        db = database.get_db()
        admin_id = db.execute("SELECT id FROM users WHERE username='admingg'").fetchone()["id"]
        other_id = _register(client, "mccowner4")
        mcc_row = _mk_mcc(db, "产品绑定的MCC", "404-000-0001", other_id)
        _mk_product(db, "我的另一个产品", admin_id, mcc_row)
        db.commit()
        db.close()

        res = client.get(f"/api/accounts/list?owner_id={admin_id}&size=10",
                         headers=admin_gg_headers)
        assert res.status_code == 200
        names = [o["name"] for o in res.get_json()["mcc_options"]]
        assert "产品绑定的MCC" in names
