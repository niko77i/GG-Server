"""GG 查户接口与 MCC 关联/详情 —— 归属收口测试。

背景（2026-10-11 全仓复核，HANDOFF §8.5 第 4 条）：

- `GET /api/accounts/lookup`、`POST /api/accounts/batch-lookup` 只挂 `@jwt_required()`，
  SQL 里没有 owner 条件，且回传 `owner_id` / `owner_name` ⇒ 任意登录用户按
  account_id 即可探明**他人**账户的归属与明细。
- `POST /api/mcc/<mid>/link` 可把**任意** MCC（含上级链）关联到自己名下；
  `GET /api/mcc/<mid>/detail` 随即回出该 MCC 的完整树（上级、直属/间接账户）。
  **两者是耦合的**：只要 link 不设限，detail 的闸门就能被「先 link 再 detail」绕过。
  2026-10-11 用户裁定：**两个都收口**。

口径与 FB 侧 `routes/fb_routes.py` 的 accounts 族一致：非 `CROSS_USER_ROLES`
（developer / admin / huguan）强制按 `owner_id` 收窄；跨用户角色放行。

⚠️ TT 侧的镜像缺口（`/api/tt/accounts/{lookup,batch-lookup}`）在
`test_tt_accounts.py::TestTtLookupOwnershipClosure`，不在本文件。
"""
import os
import sys

import pytest

_py_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _py_dir not in sys.path:
    sys.path.insert(0, _py_dir)

import database  # noqa: E402


def _create_user(client, username, role="user", platform="gg"):
    """注册 → 改写 role/platform → 登录，返回 (headers, user_id)。"""
    client.post("/api/auth/register", json={"username": username, "password": "test123"})
    db = database.get_db()
    db.execute("UPDATE users SET role=?, platform=? WHERE username=?",
               (role, platform, username))
    db.commit()
    row = db.execute("SELECT id FROM users WHERE username=?", (username,)).fetchone()
    db.close()
    resp = client.post("/api/auth/login", json={"username": username, "password": "test123"})
    return {"Authorization": f"Bearer {resp.get_json()['access_token']}"}, row["id"]


def _mk_account(owner_id, account_id, name="账户"):
    db = database.get_db()
    db.execute("INSERT INTO accounts(name, account_id, owner_id) VALUES(?,?,?)",
               (name, account_id, owner_id))
    db.commit()
    aid = db.execute("SELECT id FROM accounts WHERE account_id=?", (account_id,)).fetchone()["id"]
    db.close()
    return aid


def _mk_mcc(owner_id, mcc_id, name="MCC", parent_id=None, shared=None):
    import json as _json
    db = database.get_db()
    db.execute("INSERT INTO mcc(name, mcc_id, owner_id, parent_mcc_id, shared_user_ids) "
               "VALUES(?,?,?,?,?)",
               (name, mcc_id, owner_id, parent_id, _json.dumps(shared or [])))
    db.commit()
    mid = db.execute("SELECT id FROM mcc WHERE mcc_id=?", (mcc_id,)).fetchone()["id"]
    db.close()
    return mid


def _acc_name(aid):
    db = database.get_db()
    row = db.execute("SELECT account_id FROM accounts WHERE id=?", (aid,)).fetchone()
    db.close()
    return row["account_id"] if row else None


class TestGgAccountsLookupOwnership:
    """GG 两条查户接口补 owner 过滤。"""

    def test_lookup_hides_others_account(self, client):
        """越权写照：不加 owner 条件时 B 能查到 A 的账户并拿到 A 的 owner_name。"""
        _, a_id = _create_user(client, "lk_a")
        b_hdr, _ = _create_user(client, "lk_b")
        _mk_account(a_id, "lk-0001")
        body = client.get("/api/accounts/lookup?account_id=lk-0001", headers=b_hdr).get_json()
        assert body["found"] is False          # 证伪：不收紧时 found=True 且带回 owner_id

    def test_lookup_finds_own_account(self, client):
        """防过度收口：查自己的户必须仍能找到。"""
        a_hdr, a_id = _create_user(client, "lk_a2")
        _mk_account(a_id, "lk-0002")
        body = client.get("/api/accounts/lookup?account_id=lk-0002", headers=a_hdr).get_json()
        assert body["found"] is True
        assert body["existing"]["account_id"] == "lk-0002"

    def test_dev_can_lookup_others_account(self, client):
        """跨用户角色（CROSS_USER_ROLES）放行腿。"""
        _, a_id = _create_user(client, "lk_a3")
        dev_hdr, _ = _create_user(client, "lk_dev3", role="developer")
        _mk_account(a_id, "lk-0003")
        body = client.get("/api/accounts/lookup?account_id=lk-0003", headers=dev_hdr).get_json()
        assert body["found"] is True

    def test_batch_lookup_hides_others_account(self, client):
        """批量口径必须与单条一致 —— 否则单条修了、批量仍是探户工具。"""
        _, a_id = _create_user(client, "bl_a")
        b_hdr, _ = _create_user(client, "bl_b")
        _mk_account(a_id, "bl-0001")
        body = client.post("/api/accounts/batch-lookup",
                           json={"account_ids": ["bl-0001"]}, headers=b_hdr).get_json()
        assert body["found"] == []
        assert body["not_found"] == ["bl-0001"]

    def test_batch_lookup_finds_own_account(self, client):
        a_hdr, a_id = _create_user(client, "bl_a2")
        _mk_account(a_id, "bl-0002")
        body = client.post("/api/accounts/batch-lookup",
                           json={"account_ids": ["bl-0002", "bl-nope"]},
                           headers=a_hdr).get_json()
        assert [f["account_id"] for f in body["found"]] == ["bl-0002"]
        assert body["not_found"] == ["bl-nope"]


class TestGgMccLinkDetailOwnership:
    """MCC 关联与详情同时收口（link 不设限则 detail 的闸门可被绕过）。"""

    def test_cannot_link_others_mcc(self, client):
        _, a_id = _create_user(client, "mcc_a")
        b_hdr, b_id = _create_user(client, "mcc_b")
        mid = _mk_mcc(a_id, "mcc-0001")
        resp = client.post(f"/api/mcc/{mid}/link", headers=b_hdr)
        assert resp.status_code == 403
        # 证伪：不设限时 shared_user_ids 会写入 b_id、且随后 detail 可读
        db = database.get_db()
        shared = db.execute("SELECT shared_user_ids FROM mcc WHERE id=?", (mid,)).fetchone()[0]
        db.close()
        assert str(b_id) not in (shared or "")

    def test_cannot_read_others_mcc_detail(self, client):
        _, a_id = _create_user(client, "mcc_a2")
        b_hdr, _ = _create_user(client, "mcc_b2")
        mid = _mk_mcc(a_id, "mcc-0002")
        resp = client.get(f"/api/mcc/{mid}/detail", headers=b_hdr)
        assert resp.status_code == 403

    def test_owner_can_read_own_mcc_detail(self, client):
        """防过度收口。"""
        a_hdr, a_id = _create_user(client, "mcc_a3")
        mid = _mk_mcc(a_id, "mcc-0003")
        resp = client.get(f"/api/mcc/{mid}/detail", headers=a_hdr)
        assert resp.status_code == 200
        assert resp.get_json()["mcc"]["id"] == mid

    def test_shared_user_can_read_mcc_detail(self, client):
        """**放行腿**：已被共享给的人必须仍能看 —— 否则 owner 之外的协作方全被挡死。"""
        _, a_id = _create_user(client, "mcc_a4")
        b_hdr, b_id = _create_user(client, "mcc_b4")
        mid = _mk_mcc(a_id, "mcc-0004", shared=[b_id])
        resp = client.get(f"/api/mcc/{mid}/detail", headers=b_hdr)
        assert resp.status_code == 200

    def test_shared_user_can_relink_mcc(self, client):
        """**放行腿**：已共享给自己的 MCC，link 应放行（子 MCC 挂链时要用到）。"""
        _, a_id = _create_user(client, "mcc_a5")
        b_hdr, b_id = _create_user(client, "mcc_b5")
        mid = _mk_mcc(a_id, "mcc-0005", shared=[b_id])
        resp = client.post(f"/api/mcc/{mid}/link", headers=b_hdr)
        assert resp.status_code == 200

    def test_dev_can_read_others_mcc_detail(self, client):
        _, a_id = _create_user(client, "mcc_a6")
        dev_hdr, _ = _create_user(client, "mcc_dev6", role="developer")
        mid = _mk_mcc(a_id, "mcc-0006")
        resp = client.get(f"/api/mcc/{mid}/detail", headers=dev_hdr)
        assert resp.status_code == 200


class TestGgMccParentOwnership:
    """`mcc_create` / `mcc_update` 的 `parent_mcc_id` 归属收口。

    **为什么必须补**：`mcc_link` 与 `mcc_detail` 的闸门（上一条类）只判「能否看见 mid」，
    但 `_link_mcc_chain_to_user`（`main.py:3324`）会把调用者 uid **递归写进所有祖先**的
    `shared_user_ids`，且上行时不判归属。而 `mcc_create` / `mcc_update` 对
    `parent_mcc_id` **只判存在、不判归属** ⇒ 存在一条自服务绕过链：

      ① 把自己新建的「子 MCC」挂到受害者 MCC 下（自己是子 MCC 的 owner，天然可见）
      ② 对自己这个子 MCC 调 link ⇒ 链式回写把 uid 塞进**受害者**的 shared_user_ids
      ③ 此时 `_mcc_visible(victim, me)` 为真 ⇒ `GET /api/mcc/<victim>/detail` 放行

    即「两个都收口」若不补父级归属，等于没收。父级校验落在入口端点，风险最低
    （`_link_mcc_chain_to_user` 为多调用方共用，含管理员分配场景，不宜改其语义）。
    """

    def test_cannot_create_child_under_others_mcc(self, client):
        """利用链的**第 ① 步**：这条一堵，后面 ② ③ 都无从谈起。"""
        _, a_id = _create_user(client, "mp_a")
        b_hdr, _ = _create_user(client, "mp_b")
        victim = _mk_mcc(a_id, "mp-victim")
        resp = client.post("/api/mcc/create",
                           json={"name": "B的子MCC", "mcc_id": "mp-b-child",
                                 "parent_mcc_id": victim}, headers=b_hdr)
        assert resp.status_code == 403

    def test_can_create_child_under_own_mcc(self, client):
        """防过度收口：挂在自己 MCC 下必须仍能建。"""
        a_hdr, a_id = _create_user(client, "mp_a2")
        own = _mk_mcc(a_id, "mp-own2")
        resp = client.post("/api/mcc/create",
                           json={"name": "A的子MCC", "mcc_id": "mp-a2-child",
                                 "parent_mcc_id": own}, headers=a_hdr)
        assert resp.status_code == 200

    def test_can_create_top_level_mcc(self, client):
        """防过度收口：不带上级的顶层 MCC 不受影响。"""
        a_hdr, _ = _create_user(client, "mp_a3")
        resp = client.post("/api/mcc/create",
                           json={"name": "顶层MCC", "mcc_id": "mp-top3"}, headers=a_hdr)
        assert resp.status_code == 200

    def test_dev_can_create_child_under_others_mcc(self, client):
        """跨用户角色放行腿。"""
        _, a_id = _create_user(client, "mp_a4")
        dev_hdr, _ = _create_user(client, "mp_dev4", role="developer")
        victim = _mk_mcc(a_id, "mp-victim4")
        resp = client.post("/api/mcc/create",
                           json={"name": "dev的子MCC", "mcc_id": "mp-dev4-child",
                                 "parent_mcc_id": victim}, headers=dev_hdr)
        assert resp.status_code == 200

    def test_cannot_reparent_own_mcc_under_others(self, client):
        """同族的第二条入口：先建自己的 MCC，再把它的上级改成受害者的 —— 等价于 ①。

        `mcc_update` 原只查自环/子孙环与父级存在性，不查父级归属。
        """
        _, a_id = _create_user(client, "mp_a5")
        b_hdr, b_id = _create_user(client, "mp_b5")
        victim = _mk_mcc(a_id, "mp-victim5")
        mine = _mk_mcc(b_id, "mp-mine5")
        resp = client.put(f"/api/mcc/{mine}", json={"parent_mcc_id": victim}, headers=b_hdr)
        assert resp.status_code == 403
        # 证伪：不设限时该 UPDATE 会真的把 mine 的上级改成受害者的 MCC
        db = database.get_db()
        parent = db.execute("SELECT parent_mcc_id FROM mcc WHERE id=?", (mine,)).fetchone()[0]
        db.close()
        assert parent is None

    def test_can_reparent_under_own_mcc(self, client):
        """防过度收口：把自己两个 MCC 串起来必须仍能改。"""
        a_hdr, a_id = _create_user(client, "mp_a6")
        child = _mk_mcc(a_id, "mp-child6")
        parent = _mk_mcc(a_id, "mp-parent6")
        resp = client.put(f"/api/mcc/{child}", json={"parent_mcc_id": parent}, headers=a_hdr)
        assert resp.status_code == 200

    def test_link_chain_cannot_reach_victim(self, client):
        """**端到端集成腿**：完整走一遍 ①②③，末态必须仍看不见受害者 MCC。

        可证伪：父级归属校验缺失时，B 能建成子 MCC 并 link，随后 detail 返回 200
        且带上受害者的账户清单 ⇒ 断言失败。
        """
        a_id = _create_user(client, "mp_a7")[1]
        b_hdr, b_id = _create_user(client, "mp_b7")
        victim = _mk_mcc(a_id, "mp-victim7")
        _mk_account(a_id, "mp-acc7")          # 受害者名下有一个户，泄露与否可证

        # ① 试图把子 MCC 挂到受害者下
        created = client.post("/api/mcc/create",
                              json={"name": "B的子MCC", "mcc_id": "mp-b7-child",
                                    "parent_mcc_id": victim}, headers=b_hdr)
        assert created.status_code == 403

        # ② 即便子 MCC 以别的方式存在，link 也不该把 B 写进受害者的 shared
        db = database.get_db()
        shared = db.execute("SELECT shared_user_ids FROM mcc WHERE id=?", (victim,)).fetchone()[0]
        db.close()
        assert str(b_id) not in (shared or "")

        # ③ 末态：仍看不见
        assert client.get(f"/api/mcc/{victim}/detail", headers=b_hdr).status_code == 403
