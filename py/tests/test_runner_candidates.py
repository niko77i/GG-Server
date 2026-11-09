"""在跑人员候选列表（/api/users/names）：新用户必须能被选到。

回归背景（2026-11-05）：该端点原先 `JOIN products`（内连接），只返回「已拥有产品 /
已在某产品当在跑人员」的用户 ⇒ 新建用户（名下有 0 个产品）永远进不了候选列表，
而他又正因为进不了列表才没法被指派，形成死循环。实例：admin「黑子」在产品管理里查不到。
"""

import database


def _register(client, username, platform="gg", role="user", display_name=""):
    """注册 + 改平台/角色/昵称，返回 uid。"""
    client.post("/api/auth/register", json={"username": username, "password": "test123"})
    db = database.get_db()
    db.execute("UPDATE users SET platform=?, role=?, display_name=? WHERE username=?",
               (platform, role, display_name, username))
    db.commit()
    row = db.execute("SELECT id FROM users WHERE username=?", (username,)).fetchone()
    db.close()
    return row["id"]


def _names(client, headers):
    res = client.get("/api/users/names", headers=headers)
    assert res.status_code == 200
    return [u["id"] for u in res.get_json()["users"]]


class TestRunnerCandidateList:
    def test_new_user_without_any_product_is_listed(self, client, auth_headers):
        uid = _register(client, "heizi01", role="admin", display_name="黑子")
        assert uid in _names(client, auth_headers)

    def test_hidden_user_is_excluded(self, client, auth_headers):
        uid = _register(client, "hiduser", role="hidden")
        assert uid not in _names(client, auth_headers)

    def test_other_platform_user_excluded_until_they_participate(self, client, auth_headers):
        fb_uid = _register(client, "fbuser01", platform="fb")
        tt_uid = _register(client, "ttuser01", platform="tt")
        db = database.get_db()
        db.execute("INSERT INTO products(product_name, owner_id, runner_ids) VALUES('P', ?, '[]')",
                   (tt_uid,))
        db.commit()
        db.close()

        ids = _names(client, auth_headers)
        assert fb_uid not in ids, "没参与过 GG 产品的 FB 用户不该混进 GG 候选"
        assert tt_uid in ids, "参与过产品的用户保持原口径（不论平台）"

    def test_existing_participants_keep_appearing(self, client, auth_headers):
        owner_uid = _register(client, "owner01", display_name="在跑A")
        db = database.get_db()
        db.execute("INSERT INTO products(product_name, owner_id, runner_ids) VALUES('P2', ?, '[]')",
                   (owner_uid,))
        db.commit()
        db.close()
        assert owner_uid in _names(client, auth_headers)


class TestAuthNamesSameRule:
    """/api/auth/names 与 /api/users/names 必须同口径（否则两个下拉会对不上）。"""

    def test_auth_names_includes_new_user(self, client, auth_headers):
        uid = _register(client, "heizi02", role="admin", display_name="黑子2")
        res = client.get("/api/auth/names", headers=auth_headers)
        assert res.status_code == 200
        assert uid in [u["id"] for u in res.get_json()["users"]]

    def test_auth_names_hides_developer_from_non_developer(self, client, auth_headers):
        dev_uid = _register(client, "devuser9", role="developer")
        ids = [u["id"] for u in client.get("/api/auth/names", headers=auth_headers).get_json()["users"]]
        assert dev_uid not in ids, "非 developer 不应看到 developer"
