"""FB 资产数据模型（子项目 ①）测试。

设计见 docs/superpowers/specs/2026-10-06-fb-asset-data-model-design.md。
"""
import sqlite3

import pytest

import database


def _cols(conn, table):
    """PRAGMA table_info → {列名: 类型}。"""
    return {r[1]: r[2] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()}


@pytest.fixture
def two_users(client):
    """两个 FB 平台用户，用于验证「词表唯一性按 (name, platform)，不按 owner」。"""
    db = database.get_db()
    for name in ("u_alpha", "u_beta"):
        db.execute("INSERT INTO users(username, password, role, platform) "
                   "VALUES(?, 'x', 'user', 'fb')", (name,))
    db.commit()
    ids = [r[0] for r in db.execute(
        "SELECT id FROM users WHERE username IN ('u_alpha','u_beta') "
        "ORDER BY username").fetchall()]
    db.close()
    return ids


def _seed_bm_pair_and_account(db, owner_id):
    """建两个 BM 与一个 FB 账户，返回 (bm1, bm2, account_pk)。"""
    db.execute("INSERT INTO fb_bms(name, bm_id, owner_id) VALUES('BM甲','bm1',?)", (owner_id,))
    bm1 = db.execute("SELECT last_insert_rowid()").fetchone()[0]
    db.execute("INSERT INTO fb_bms(name, bm_id, owner_id) VALUES('BM乙','bm2',?)", (owner_id,))
    bm2 = db.execute("SELECT last_insert_rowid()").fetchone()[0]
    db.execute("INSERT INTO fb_accounts(name, account_id, owner_id) VALUES('户甲','1001',?)",
               (owner_id,))
    acc = db.execute("SELECT last_insert_rowid()").fetchone()[0]
    return bm1, bm2, acc


class TestFbAccountColumns:
    def test_ten_new_columns_exist(self, client):
        db = database.get_db()
        cols = _cols(db, "fb_accounts")
        db.close()
        expected = {
            "operator": "TEXT",
            "channel_id": "INTEGER",
            "asset_type_id": "INTEGER",
            "unit_price": "TEXT",
            "inbound_qty": "TEXT",
            "acceptor_id": "INTEGER",
            "outbound_date": "TEXT",
            "outbound_qty": "TEXT",
            "consumption": "TEXT",
            "remark": "TEXT",
        }
        for col, affinity in expected.items():
            assert col in cols, f"fb_accounts 缺列 {col}"
            assert cols[col] == affinity, f"{col} 期望 {affinity}，实际 {cols[col]}"

    def test_new_columns_default_empty_for_existing_rows(self, client, two_users):
        """存量行取默认值：空串 / NULL，行为与改动前一致。"""
        db = database.get_db()
        _, _, acc = _seed_bm_pair_and_account(db, two_users[0])
        db.commit()
        row = db.execute("SELECT * FROM fb_accounts WHERE id=?", (acc,)).fetchone()
        db.close()
        assert row["operator"] == ""
        assert row["remark"] == ""
        assert row["unit_price"] == ""
        assert row["channel_id"] is None

    def test_migration_is_idempotent(self, client):
        """_ensure_columns 每次连库都跑，连两次不得报错。"""
        db1 = database.get_db()
        db1.close()
        db2 = database.get_db()
        cols = _cols(db2, "fb_accounts")
        db2.close()
        assert "remark" in cols


class TestSharedOptionTables:
    def test_tables_exist_with_expected_columns(self, client):
        db = database.get_db()
        for t in ("fb_channels", "fb_asset_types"):
            cols = _cols(db, t)
            assert "name" in cols, t
            assert "owner_id" in cols, t
            assert "platform" in cols, t
            assert "created_at" in cols, t
        db.close()

    def test_name_unique_per_platform_not_per_owner(self, client, two_users):
        """唯一性是 (name, platform) —— 甲、乙建同名渠道只能落一行。

        这正是设计不复用 `agents` 的理由：agents 的 UNIQUE 含 owner_id，
        同名会落两行，而「唯一命中才落库」的口径下那一列会永远同步不上。
        """
        db = database.get_db()
        db.execute("INSERT INTO fb_channels(name, owner_id, platform) VALUES('渠道A', ?, 'fb')",
                   (two_users[0],))
        db.commit()
        with pytest.raises(sqlite3.IntegrityError):
            db.execute("INSERT INTO fb_channels(name, owner_id, platform) VALUES('渠道A', ?, 'fb')",
                       (two_users[1],))
        db.rollback()
        n = db.execute("SELECT COUNT(*) FROM fb_channels WHERE name='渠道A'").fetchone()[0]
        db.close()
        assert n == 1

    def test_same_name_allowed_on_other_platform(self, client, two_users):
        """platform 是唯一性的一部分：gg 上可以有同名。"""
        db = database.get_db()
        db.execute("INSERT INTO fb_channels(name, owner_id, platform) VALUES('渠道A', ?, 'fb')",
                   (two_users[0],))
        db.execute("INSERT INTO fb_channels(name, owner_id, platform) VALUES('渠道A', ?, 'gg')",
                   (two_users[0],))
        db.commit()
        n = db.execute("SELECT COUNT(*) FROM fb_channels WHERE name='渠道A'").fetchone()[0]
        db.close()
        assert n == 2


class TestPrimaryBm:
    def test_switching_primary_bm_succeeds(self, client, two_users):
        """换 BM 必须成功：同一事务内先清后设。"""
        db = database.get_db()
        bm1, bm2, acc = _seed_bm_pair_and_account(db, two_users[0])
        db.execute("INSERT INTO fb_account_bm(account_id, bm_id, is_primary) VALUES(?,?,1)",
                   (acc, bm1))
        # bm2 必须**已与该账户关联**（is_primary=0），否则下面的 SET is_primary=1
        # 影响 0 行、什么也没换。换 BM 的前提是这条关联已经存在。
        db.execute("INSERT INTO fb_account_bm(account_id, bm_id, is_primary) VALUES(?,?,0)",
                   (acc, bm2))
        db.commit()
        db.execute("UPDATE fb_account_bm SET is_primary=0 WHERE account_id=?", (acc,))
        db.execute("UPDATE fb_account_bm SET is_primary=1 WHERE account_id=? AND bm_id=?",
                   (acc, bm2))
        db.commit()
        row = db.execute("SELECT bm_id FROM fb_account_bm WHERE account_id=? AND is_primary=1",
                         (acc,)).fetchone()
        db.close()
        assert row is not None and row["bm_id"] == bm2

    def test_two_primaries_rejected(self, client, two_users):
        """同一账户至多一个主 BM。"""
        db = database.get_db()
        bm1, bm2, acc = _seed_bm_pair_and_account(db, two_users[0])
        db.execute("INSERT INTO fb_account_bm(account_id, bm_id, is_primary) VALUES(?,?,1)",
                   (acc, bm1))
        db.commit()
        with pytest.raises(sqlite3.IntegrityError):
            db.execute("INSERT INTO fb_account_bm(account_id, bm_id, is_primary) VALUES(?,?,1)",
                       (acc, bm2))
        db.rollback()
        db.close()

    def test_setting_new_primary_before_clearing_fails(self, client, two_users):
        """先设后清会撞部分唯一索引 —— 把「顺序不是风格问题」钉成回归测试。

        SQLite 的唯一索引是**逐语句**检查的，不是事务提交时统一检查。
        """
        db = database.get_db()
        bm1, bm2, acc = _seed_bm_pair_and_account(db, two_users[0])
        db.execute("INSERT INTO fb_account_bm(account_id, bm_id, is_primary) VALUES(?,?,1)",
                   (acc, bm1))
        # 同上：bm2 得先关联，否则这条 UPDATE 影响 0 行、根本不会撞唯一索引 ——
        # 那样这个用例就成了「什么都没发生却断言抛异常」的假绿。
        db.execute("INSERT INTO fb_account_bm(account_id, bm_id, is_primary) VALUES(?,?,0)",
                   (acc, bm2))
        db.commit()
        with pytest.raises(sqlite3.IntegrityError):
            # 先设新的（此刻 bm1 仍是 1）
            db.execute("UPDATE fb_account_bm SET is_primary=1 WHERE account_id=? AND bm_id=?",
                       (acc, bm2))
        db.rollback()
        db.close()

    def test_multiple_non_primary_bms_allowed(self, client, two_users):
        """非主 BM 不受限：一个账户可挂多个 BM。"""
        db = database.get_db()
        bm1, bm2, acc = _seed_bm_pair_and_account(db, two_users[0])
        db.execute("INSERT INTO fb_account_bm(account_id, bm_id, is_primary) VALUES(?,?,0)",
                   (acc, bm1))
        db.execute("INSERT INTO fb_account_bm(account_id, bm_id, is_primary) VALUES(?,?,0)",
                   (acc, bm2))
        db.commit()
        n = db.execute("SELECT COUNT(*) FROM fb_account_bm WHERE account_id=?", (acc,)).fetchone()[0]
        db.close()
        assert n == 2


class TestSharedOptionApi:
    """两组词表端点的契约。门禁口径：list 任意已登录；create/rename/delete 需
    GLOBAL_OPTION_ROLES（与 /api/regions/* 同族）。"""

    @pytest.fixture
    def fb_admin(self, client):
        """一个 FB 平台的 admin —— GLOBAL_OPTION_ROLES 成员。"""
        client.post("/api/auth/register", json={"username": "fb_admin", "password": "test123"})
        db = database.get_db()
        db.execute("UPDATE users SET role='admin', platform='fb' WHERE username='fb_admin'")
        db.commit()
        db.close()
        token = client.post("/api/auth/login",
                            json={"username": "fb_admin", "password": "test123"}
                            ).get_json()["access_token"]
        return {"Authorization": f"Bearer {token}"}

    @pytest.fixture
    def fb_plain(self, client):
        """一个 FB 平台的普通 user —— 不在 GLOBAL_OPTION_ROLES。"""
        client.post("/api/auth/register", json={"username": "fb_plain", "password": "test123"})
        db = database.get_db()
        db.execute("UPDATE users SET platform='fb' WHERE username='fb_plain'")
        db.commit()
        db.close()
        token = client.post("/api/auth/login",
                            json={"username": "fb_plain", "password": "test123"}
                            ).get_json()["access_token"]
        return {"Authorization": f"Bearer {token}"}

    @pytest.mark.parametrize("base", ["/api/fb-channels", "/api/fb-asset-types"])
    def test_create_list_rename_delete_roundtrip(self, client, fb_admin, base):
        r = client.post(f"{base}/create", json={"name": "甲"}, headers=fb_admin)
        assert r.status_code == 200 and r.get_json()["success"] is True
        new_id = r.get_json()["id"]

        r = client.get(f"{base}/list", headers=fb_admin)
        names = [i["name"] for i in r.get_json()["items"]]
        assert "甲" in names

        r = client.put(f"{base}/{new_id}", json={"name": "乙"}, headers=fb_admin)
        assert r.status_code == 200

        r = client.delete(f"{base}/{new_id}", headers=fb_admin)
        assert r.status_code == 200

    @pytest.mark.parametrize("base", ["/api/fb-channels", "/api/fb-asset-types"])
    def test_duplicate_name_rejected(self, client, fb_admin, base):
        client.post(f"{base}/create", json={"name": "重复"}, headers=fb_admin)
        r = client.post(f"{base}/create", json={"name": "重复"}, headers=fb_admin)
        assert r.status_code == 409

    @pytest.mark.parametrize("base", ["/api/fb-channels", "/api/fb-asset-types"])
    def test_empty_name_rejected(self, client, fb_admin, base):
        r = client.post(f"{base}/create", json={"name": "   "}, headers=fb_admin)
        assert r.status_code == 400

    @pytest.mark.parametrize("base", ["/api/fb-channels", "/api/fb-asset-types"])
    def test_write_requires_option_role(self, client, fb_plain, base):
        r = client.post(f"{base}/create", json={"name": "无权"}, headers=fb_plain)
        assert r.status_code == 403

    def test_delete_blocked_while_referenced_by_live_account(self, client, fb_admin, two_users):
        r = client.post("/api/fb-channels/create", json={"name": "在用渠道"}, headers=fb_admin)
        cid = r.get_json()["id"]
        db = database.get_db()
        db.execute("INSERT INTO fb_accounts(name, account_id, owner_id, channel_id) "
                   "VALUES('户','2001',?,?)", (two_users[0], cid))
        db.commit()
        db.close()
        r = client.delete(f"/api/fb-channels/{cid}", headers=fb_admin)
        assert r.status_code == 409

    def test_delete_clears_reference_on_soft_deleted_account(self, client, fb_admin, two_users):
        """软删账户不挡删除，但引用必须被解除 —— 否则 FK 约束会让 DELETE 变 500。"""
        r = client.post("/api/fb-channels/create", json={"name": "仅软删引用"}, headers=fb_admin)
        cid = r.get_json()["id"]
        db = database.get_db()
        db.execute("INSERT INTO fb_accounts(name, account_id, owner_id, channel_id, deleted_at) "
                   "VALUES('户','2002',?,?,datetime('now','localtime'))", (two_users[0], cid))
        db.commit()
        db.close()
        r = client.delete(f"/api/fb-channels/{cid}", headers=fb_admin)
        assert r.status_code == 200
        db = database.get_db()
        left = db.execute("SELECT channel_id FROM fb_accounts WHERE account_id='2002'").fetchone()[0]
        gone = db.execute("SELECT COUNT(*) FROM fb_channels WHERE id=?", (cid,)).fetchone()[0]
        db.close()
        assert left is None and gone == 0


class TestFbAccountApi:
    @pytest.fixture
    def fb_user(self, client):
        client.post("/api/auth/register", json={"username": "fb_owner", "password": "test123"})
        db = database.get_db()
        db.execute("UPDATE users SET platform='fb', display_name='张三' "
                   "WHERE username='fb_owner'")
        db.commit()
        db.close()
        token = client.post("/api/auth/login",
                            json={"username": "fb_owner", "password": "test123"}
                            ).get_json()["access_token"]
        return {"Authorization": f"Bearer {token}"}

    def test_create_writes_new_fields(self, client, fb_user):
        r = client.post("/api/fb/accounts/create", headers=fb_user, json={
            "name": "户一", "account_id": "9001", "timezone": "Asia/Shanghai",
            "unit_price": "12.5", "inbound_qty": "3", "outbound_qty": "1",
            "outbound_date": "2026-10-01", "consumption": "88", "remark": "备注A",
        })
        assert r.status_code == 200
        aid = r.get_json()["id"]
        db = database.get_db()
        row = db.execute("SELECT * FROM fb_accounts WHERE id=?", (aid,)).fetchone()
        db.close()
        assert row["unit_price"] == "12.5"
        assert row["inbound_qty"] == "3"
        assert row["outbound_qty"] == "1"
        assert row["outbound_date"] == "2026-10-01"
        assert row["consumption"] == "88"
        assert row["remark"] == "备注A"

    def test_operator_is_frozen_to_creator_and_ignores_request_body(self, client, fb_user):
        """operator 由服务端填；请求体里的同名字段必须被忽略。"""
        r = client.post("/api/fb/accounts/create", headers=fb_user, json={
            "name": "户二", "account_id": "9002", "operator": "伪造的操作人",
        })
        aid = r.get_json()["id"]
        db = database.get_db()
        row = db.execute("SELECT operator FROM fb_accounts WHERE id=?", (aid,)).fetchone()
        db.close()
        assert row["operator"] == "张三"

    def test_operator_cannot_be_changed_by_update(self, client, fb_user):
        """PUT 里根本没有 operator 这一列的写入路径。"""
        r = client.post("/api/fb/accounts/create", headers=fb_user,
                        json={"name": "户三", "account_id": "9003"})
        aid = r.get_json()["id"]
        client.put(f"/api/fb/accounts/{aid}", headers=fb_user, json={
            "name": "户三改", "operator": "改过的操作人",
        })
        db = database.get_db()
        row = db.execute("SELECT name, operator FROM fb_accounts WHERE id=?", (aid,)).fetchone()
        db.close()
        assert row["name"] == "户三改"
        assert row["operator"] == "张三"

    def test_update_writes_new_fields(self, client, fb_user):
        r = client.post("/api/fb/accounts/create", headers=fb_user,
                        json={"name": "户四", "account_id": "9004"})
        aid = r.get_json()["id"]
        client.put(f"/api/fb/accounts/{aid}", headers=fb_user, json={
            "name": "户四", "unit_price": "99", "remark": "改后备注",
        })
        db = database.get_db()
        row = db.execute("SELECT unit_price, remark FROM fb_accounts WHERE id=?",
                         (aid,)).fetchone()
        db.close()
        assert row["unit_price"] == "99"
        assert row["remark"] == "改后备注"

    def test_primary_bm_visible_in_list(self, client, fb_user):
        db = database.get_db()
        uid = db.execute("SELECT id FROM users WHERE username='fb_owner'").fetchone()[0]
        db.execute("INSERT INTO fb_bms(name, bm_id, owner_id) VALUES('BM主','bmz',?)", (uid,))
        bm = db.execute("SELECT last_insert_rowid()").fetchone()[0]
        db.commit()
        db.close()
        r = client.post("/api/fb/accounts/create", headers=fb_user, json={
            "name": "户五", "account_id": "9005", "bm_ids": [bm], "primary_bm_id": bm,
        })
        assert r.status_code == 200
        r = client.get("/api/fb/accounts/list", headers=fb_user,
                       query_string={"search": "9005"})
        item = r.get_json()["items"][0]
        assert item["primary_bm_name"] == "BM主"

    def test_switching_primary_bm_via_update(self, client, fb_user):
        """换 BM 走接口也必须成功（先清后设）。"""
        db = database.get_db()
        uid = db.execute("SELECT id FROM users WHERE username='fb_owner'").fetchone()[0]
        for nm, bid in (("BM一", "bx1"), ("BM二", "bx2")):
            db.execute("INSERT INTO fb_bms(name, bm_id, owner_id) VALUES(?,?,?)", (nm, bid, uid))
        bms = [r[0] for r in db.execute("SELECT id FROM fb_bms ORDER BY id").fetchall()]
        db.commit()
        db.close()
        r = client.post("/api/fb/accounts/create", headers=fb_user, json={
            "name": "户六", "account_id": "9006", "bm_ids": bms, "primary_bm_id": bms[0],
        })
        aid = r.get_json()["id"]
        r = client.put(f"/api/fb/accounts/{aid}", headers=fb_user, json={
            "name": "户六", "bm_ids": bms, "primary_bm_id": bms[1],
        })
        assert r.status_code == 200
        db = database.get_db()
        row = db.execute("SELECT bm_id FROM fb_account_bm WHERE account_id=? AND is_primary=1",
                         (aid,)).fetchone()
        db.close()
        assert row is not None and row["bm_id"] == bms[1]


class TestFbReassign:
    @pytest.fixture
    def fb_user_headers_factory(self, client):
        """注册两个 FB 用户并返回 (headers_dict, uid) 的工厂。"""
        def _make(username):
            client.post("/api/auth/register", json={"username": username, "password": "test123"})
            db = database.get_db()
            db.execute("UPDATE users SET platform='fb' WHERE username=?", (username,))
            db.commit()
            uid = db.execute("SELECT id FROM users WHERE username=?", (username,)).fetchone()[0]
            db.close()
            token = client.post("/api/auth/login",
                                json={"username": username, "password": "test123"}
                                ).get_json()["access_token"]
            return {"Authorization": f"Bearer {token}"}, uid
        return _make

    def _make_account(self, client, headers, account_id):
        r = client.post("/api/fb/accounts/create", headers=headers,
                        json={"name": f"户{account_id}", "account_id": account_id})
        return r.get_json()["id"]

    def test_developer_can_transfer_to_another_user(self, client, fb_user_headers_factory):
        dev_h, _ = fb_user_headers_factory("fb_dev")
        db = database.get_db()
        db.execute("UPDATE users SET role='developer', platform='fb' WHERE username='fb_dev'")
        db.commit()
        db.close()
        # 重新登录拿带新角色的 token
        token = client.post("/api/auth/login",
                            json={"username": "fb_dev", "password": "test123"}
                            ).get_json()["access_token"]
        dev_h = {"Authorization": f"Bearer {token}"}
        _, target_uid = fb_user_headers_factory("fb_target")

        aid = self._make_account(client, dev_h, "7001")
        r = client.put(f"/api/fb/accounts/{aid}/reassign", headers=dev_h,
                       json={"owner_id": target_uid})
        assert r.status_code == 200
        db = database.get_db()
        owner = db.execute("SELECT owner_id FROM fb_accounts WHERE id=?", (aid,)).fetchone()[0]
        db.close()
        assert owner == target_uid

    def test_plain_user_without_owner_id_claims_for_self(self, client, fb_user_headers_factory):
        h, uid = fb_user_headers_factory("fb_solo")
        aid = self._make_account(client, h, "7002")
        r = client.put(f"/api/fb/accounts/{aid}/reassign", headers=h, json={})
        # 已经属于自己 → 409（与 TT 同口径）
        assert r.status_code == 409

    def test_plain_user_cannot_steal_another_users_account(self, client, fb_user_headers_factory):
        """非跨用户角色按 id 改别人名下的户 → 403。"""
        h1, _ = fb_user_headers_factory("fb_a")
        h2, _ = fb_user_headers_factory("fb_b")
        aid = self._make_account(client, h1, "7003")
        r = client.put(f"/api/fb/accounts/{aid}/reassign", headers=h2, json={})
        assert r.status_code == 403

    def test_nonexistent_target_user_returns_400_not_500(self, client, fb_user_headers_factory):
        """目标用户不存在必须在写库前挡成 400 —— 否则 FK IntegrityError → 500。"""
        dev_h, _ = fb_user_headers_factory("fb_dev2")
        db = database.get_db()
        db.execute("UPDATE users SET role='developer' WHERE username='fb_dev2'")
        db.commit()
        db.close()
        token = client.post("/api/auth/login",
                            json={"username": "fb_dev2", "password": "test123"}
                            ).get_json()["access_token"]
        dev_h = {"Authorization": f"Bearer {token}"}
        aid = self._make_account(client, dev_h, "7004")
        r = client.put(f"/api/fb/accounts/{aid}/reassign", headers=dev_h,
                       json={"owner_id": 999999})
        assert r.status_code == 400

    def test_non_numeric_owner_id_returns_400(self, client, fb_user_headers_factory):
        """非法 owner_id 只对**跨用户角色**才有意义。

        端点只在 `if role in CROSS_USER_ROLES:` 分支里解析 owner_id —— 普通 user
        传的 owner_id 被**完全忽略**（默认路径恒为「转给自己」，与 TT 同口径）。
        用普通 user 发这个请求会走到「已属于当前用户」的 409，拿不到 400。
        所以本用例必须用跨用户角色发起。
        """
        fb_user_headers_factory("fb_dev3")
        db = database.get_db()
        db.execute("UPDATE users SET role='developer' WHERE username='fb_dev3'")
        db.commit()
        db.close()
        token = client.post("/api/auth/login",
                            json={"username": "fb_dev3", "password": "test123"}
                            ).get_json()["access_token"]
        h = {"Authorization": f"Bearer {token}"}
        aid = self._make_account(client, h, "7005")
        r = client.put(f"/api/fb/accounts/{aid}/reassign", headers=h,
                       json={"owner_id": "abc"})
        assert r.status_code == 400

    def test_missing_account_returns_404(self, client, fb_user_headers_factory):
        h, _ = fb_user_headers_factory("fb_solo3")
        r = client.put("/api/fb/accounts/999999/reassign", headers=h, json={})
        assert r.status_code == 404
