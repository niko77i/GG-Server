"""户管（huguan）角色权限测试。"""
import io
import json
import os

import database


def _create_user(client, username, role="user", platform="gg", created_by=None):
    """注册用户 → 直接改写 role/platform/created_by → 登录，返回 (headers, user_id)。"""
    client.post("/api/auth/register", json={"username": username, "password": "test123"})
    db = database.get_db()
    db.execute("UPDATE users SET role=?, platform=?, created_by=? WHERE username=?",
               (role, platform, created_by, username))
    db.commit()
    row = db.execute("SELECT id FROM users WHERE username=?", (username,)).fetchone()
    db.close()
    resp = client.post("/api/auth/login", json={"username": username, "password": "test123"})
    token = resp.get_json().get("access_token", "")
    return {"Authorization": f"Bearer {token}"}, row["id"]


def _huguan(client, username="_hg_main", platform="gg"):
    return _create_user(client, username, role="huguan", platform=platform)


class TestHuguanCrossPlatformAccess:
    def test_huguan_can_call_tt_endpoint(self, client):
        """户管的 users.platform 是 gg，但切到 TT 后调 TT 接口不应被 403。"""
        hg, _ = _huguan(client, "_hg_xplat")
        resp = client.get("/api/tt/users?platform=tt", headers=hg)
        assert resp.status_code == 200

    def test_huguan_effective_platform_follows_query_param(self, client):
        """户管的 _get_effective_platform 应跟随 ?platform=，而非固定用 users.platform。"""
        hg, _ = _huguan(client, "_hg_effplat")
        db = database.get_db()
        db.execute("INSERT INTO account_statuses(name, platform, owner_id) VALUES(?,?,?)",
                   ("TT专属状态", "tt", None))
        db.execute("INSERT INTO account_statuses(name, platform, owner_id) VALUES(?,?,?)",
                   ("GG专属状态", "gg", None))
        db.commit()
        db.close()
        resp = client.get("/api/statuses/list?platform=tt", headers=hg)
        names = [s["name"] for s in resp.get_json()["statuses"]]
        assert "TT专属状态" in names
        assert "GG专属状态" not in names

    def test_regular_user_still_blocked_on_other_platform(self, client):
        """回归：普通 GG 用户调 TT 接口仍然 403。"""
        u, _ = _create_user(client, "_hg_reg_gg", role="user", platform="gg")
        resp = client.get("/api/tt/users?platform=tt", headers=u)
        assert resp.status_code == 403


class TestPlatformSwitchRolesInvariant:
    """锁定「平台切换」不变量：**admin 不跨平台；developer / 户管 跨平台**。

    背景：Task 1 把两个平台切换闸门 —— `require_platform`（routes/decorators.py:59）
    与 `_get_effective_platform`（main.py:5782）—— 的放行判断从 `== "developer"`
    扩展为 `PLATFORM_SWITCH_ROLES = ("developer", HUGUAN_ROLE)`。
    选择该常量而非含 admin 的 `CROSS_USER_ROLES` 的**全部理由**，就是「admin 行为逐位不变」：
    admin 自 c4b3d56「用户管理按平台隔离」起已被有意移出跨平台判断
    （见 2026-09-22-user-role-platform-isolation-design.md）。

    本类是这条不变量的**回归网**：一旦有人把 admin 加进 `PLATFORM_SWITCH_ROLES`，
    `test_admin_gg_cannot_call_tt_endpoint` 立刻变红。没有它，那次编辑会静默地把
    admin 的跨平台越权改回来（并可经 /api/tt/accounts/list 看到全部用户的账户）。
    """

    def test_admin_gg_cannot_call_tt_endpoint(self, client):
        """GG 管理员调 TT 接口必须 403 —— 本类存在的首要原因。

        admin 的 users.platform='gg'。若此调用返回 200，说明 admin 已被放行跨平台，
        等于回退 c4b3d56 的平台隔离；配合 tt_accounts_routes.py:209 对
        role in CROSS_USER_ROLES 不加 owner 过滤，GG 管理员将看到全部用户的 TT 账户。
        """
        admin, _ = _create_user(client, "_inv_admin_gg", role="admin", platform="gg")
        resp = client.get("/api/tt/users?platform=tt", headers=admin)
        assert resp.status_code == 403, (
            "admin 不应跨平台：PLATFORM_SWITCH_ROLES 被改成了含 admin 的集合？"
        )

    def test_developer_gg_can_call_tt_endpoint(self, client):
        """GG developer 调 TT 接口仍 200 —— PLATFORM_SWITCH_ROLES 的另一半未被破坏。

        与上一条成对：证明 Task 1 的改动既没放过 admin，也没误伤 developer
        （require_platform 原来是 `== "developer"`，扩展后必须仍放行 developer）。
        """
        dev, _ = _create_user(client, "_inv_dev_gg", role="developer", platform="gg")
        resp = client.get("/api/tt/users?platform=tt", headers=dev)
        assert resp.status_code == 200

    def test_admin_tt_can_call_tt_endpoint(self, client):
        """TT 管理员调 TT 接口必须 200 —— 证明上条的 403 是「不跨平台」而非「admin 被禁用」。

        admin 走的是 require_platform 里原有的 `user.platform != platform` 分支
        （platform 都是 'tt'，故放行），其语义与 Task 1 之前完全一致。
        """
        admin, _ = _create_user(client, "_inv_admin_tt", role="admin", platform="tt")
        resp = client.get("/api/tt/users?platform=tt", headers=admin)
        assert resp.status_code == 200


class TestNoPlatformParamDefaultsToGG:
    """`_get_effective_platform` 的「不带 ?platform=」回退分支。

    与 `TestHuguanCrossPlatformAccess.test_huguan_effective_platform_follows_query_param`
    互补：那条覆盖「带 ?platform=tt」；本条覆盖「不带参数」时落到
    `request.args.get("platform", "gg")` 的**字面默认值 'gg'**。

    语义要点（已实测确认，见 task-1-report.md 修复报告）：
    平台切换角色（developer / 户管）的 `users.platform` **不参与**该解析 ——
    这正是设计文档 §7.3「户管的 users.platform 不参与权限判断」的落地结果。
    前端 client.js 对这类角色总会注入 ?platform=（设计 §3.2），
    因此「不带参数」是退化路径，其默认值就是 'gg'，**不是**该用户自己的 platform。
    """

    def test_huguan_without_platform_param_uses_gg_default(self, client):
        """户管 platform='tt'、不带 ?platform= 时取到默认 'gg' 命名空间，而非自己的 tt。"""
        hg, _ = _huguan(client, "_hg_fallback", platform="tt")
        db = database.get_db()
        db.execute("INSERT INTO account_statuses(name, platform, owner_id) VALUES(?,?,?)",
                   ("回退TT状态", "tt", None))
        db.execute("INSERT INTO account_statuses(name, platform, owner_id) VALUES(?,?,?)",
                   ("回退GG状态", "gg", None))
        db.commit()
        db.close()

        resp = client.get("/api/statuses/list", headers=hg)
        assert resp.status_code == 200
        names = [s["name"] for s in resp.get_json()["statuses"]]
        assert "回退GG状态" in names       # 缺省 'gg'
        assert "回退TT状态" not in names   # 不回退到 users.platform='tt'


class TestAuthRoleFixes:
    def test_toggle_huguan_hides_instead_of_demoting(self, client):
        """启停户管应进入 hidden；修复前因元组缺 huguan 会直接被降级成 user。"""
        import auth
        _, uid = _huguan(client, "_hg_toggle")
        assert auth.toggle_user_status(uid)["role"] == "hidden"

    def test_unhide_falls_back_to_user_for_all_roles(self, client):
        """前半锁定**本次新增**的户管隐藏行为（huguan → hidden，由 `py/auth.py:199` 元组修复带来）；
        后半锁定**既有**语义：取消隐藏一律回落 user —— 该语义对 admin / viewer 在改动前即成立。

        保护范围说明：循环第 0 腿是 huguan，其 `== "hidden"` 断言**依赖本次修复**，
        因此本用例在修复前是失败的，不是纯回归锁定。户管隐藏方向的独立覆盖见
        `test_toggle_huguan_hides_instead_of_demoting`。
        如需改成「取消隐藏恢复原角色」，那是独立的产品决策（需记忆字段），不在本需求范围。
        """
        import auth
        for idx, role in enumerate(("huguan", "admin", "viewer")):
            _, uid = _create_user(client, f"_hg_unhide_{idx}", role=role)
            assert auth.toggle_user_status(uid)["role"] == "hidden"
            assert auth.toggle_user_status(uid)["role"] == "user"

    def test_update_user_role_rejects_unknown_role(self, client):
        """角色白名单：非法角色值一律拒绝。"""
        import auth
        _, uid = _create_user(client, "_hg_badrole", role="user")
        assert auth.update_user_role(uid, "superuser") is False
        # 拒绝必须是「什么都没发生」：只断言返回值会把「先写入再返回 False」漏掉
        db = database.get_db()
        row = db.execute("SELECT role FROM users WHERE id = ?", (uid,)).fetchone()
        db.close()
        assert row["role"] == "user", "被拒绝的写入不得改动数据库中的角色"
        assert auth.update_user_role(uid, "huguan") is True

    def test_update_user_role_accepts_every_whitelisted_role(self, client):
        """白名单的接受侧：`py/auth.py:128` 元组里的每个角色都必须仍可写入。

        与 `test_update_user_role_rejects_unknown_role` 互补 —— 那条只覆盖拒绝侧，
        接受侧仅验证了 `huguan` 一个值。若有人日后从元组中删掉 `"viewer"`（例如误以为
        该角色已废弃），改角色功能会静默失效而原用例依旧全绿；本用例让这次删减立刻变红。
        """
        import auth
        for idx, role in enumerate(("user", "admin", "viewer", "hidden", "huguan")):
            _, uid = _create_user(client, f"_hg_wl_{idx}", role="user")
            assert auth.update_user_role(uid, role) is True, f"{role} 应在白名单内"
            db = database.get_db()
            row = db.execute("SELECT role FROM users WHERE id = ?", (uid,)).fetchone()
            db.close()
            assert row["role"] == role, f"{role} 应已写入数据库"

    def test_list_users_role_filter_default_unchanged(self, client):
        """不传 role_filter 时结果与改动前一致。

        注意 developer 视角下 list_users 不加任何角色过滤（filters = [""]），
        因此 developer 账号本身也会出现在结果里——这正是改动前的行为，必须保持。
        """
        import auth
        _, dev_id = _create_user(client, "_hg_lf_dev", role="developer")
        _create_user(client, "_hg_lf_admin", role="admin")
        _create_user(client, "_hg_lf_user", role="user")
        res = auth.list_users(current_user_id=dev_id)
        roles = {u["role"] for u in res["users"]}
        assert roles == {"developer", "admin", "user"}

    def test_list_users_role_filter_huguan_only(self, client):
        import auth
        _, dev_id = _create_user(client, "_hg_lf2_dev", role="developer")
        _create_user(client, "_hg_lf2_hg", role="huguan")
        _create_user(client, "_hg_lf2_user", role="user")
        res = auth.list_users(current_user_id=dev_id, role_filter="huguan")
        assert {u["role"] for u in res["users"]} == {"huguan"}

    def test_list_users_role_filter_combined_with_search(self, client):
        """`role_filter` 与 `search` 的组合：search 非空时 list_users 走的是**另一条**
        COUNT/SELECT 分支（`py/auth.py:97-110`），与空 search 分支（`:111-120`）分开拼 SQL，
        而既有 role_filter 用例（上面两条）都只覆盖了空 search 分支。

        构造：两个用户名都含特征子串 `zqx`（`_create_user` 不传 display_name，故这里靠
        username LIKE 命中），其中只有一个是户管；dev 账号特意不含该子串，以免混进搜索集。
        若 role_filter 在 search 分支中被丢弃或拼错位置，非户管的 `_hg_zqx_user` 会混进结果。
        """
        import auth
        _, dev_id = _create_user(client, "_hg_dev9", role="developer")
        _, hg_id = _create_user(client, "_hg_zqx_hg", role="huguan")
        _, user_id = _create_user(client, "_hg_zqx_user", role="user")

        # 前置校验：两个账号都该被 `zqx` 命中，否则下面的「排除」断言可能只是搜索没匹配上、
        # 而非 role_filter 生效。这里直接查库验证 LIKE 命中集，**不**调
        # `list_users(search=...)` 且不带 platform / role_filter —— 那条路径会撞上
        # `py/auth.py:99-101` 的既有缺陷（base_where 为空时仍拼 " AND (...)"，SQL 语法错误），
        # 与本次 role_filter 改动无关，见修复报告的「遗留发现」。
        db = database.get_db()
        matched = {r["id"] for r in db.execute(
            "SELECT id FROM users WHERE username LIKE ? OR display_name LIKE ?",
            ("%zqx%", "%zqx%")).fetchall()}
        db.close()
        assert matched == {hg_id, user_id}, "特征子串必须同时命中户管与非户管两个账号"

        res = auth.list_users(current_user_id=dev_id, search="zqx", role_filter="huguan")
        assert hg_id in {u["id"] for u in res["users"]}
        assert user_id not in {u["id"] for u in res["users"]}
        assert {u["role"] for u in res["users"]} == {"huguan"}
        # total 来自独立的 COUNT 查询（`py/auth.py:102`），是前端分页契约；
        # 若只筛 SELECT 而漏筛 COUNT，users 看着对、分页却会按未过滤的总数算页数。
        assert res["total"] == 1



class TestHuguanUserManagement:
    def test_create_ignores_requested_role(self, client):
        """户管创建用户时传 role=admin，落库仍为 huguan。"""
        hg, hg_id = _huguan(client, "_hgm_create")
        resp = client.post("/api/admin/users/create", json={
            "username": "_hgm_new1", "password": "test123", "role": "admin",
        }, headers=hg)
        assert resp.status_code == 200
        db = database.get_db()
        row = db.execute("SELECT role, platform, created_by FROM users WHERE username='_hgm_new1'").fetchone()
        db.close()
        assert row["role"] == "huguan"
        assert row["platform"] == "gg"
        assert row["created_by"] == hg_id

    def test_list_returns_only_huguan(self, client):
        hg, _ = _huguan(client, "_hgm_list")
        db = database.get_db()
        db.execute("INSERT INTO users(username, password, role, platform) VALUES('_hgm_u','x','user','gg')")
        db.commit()
        db.close()
        resp = client.get("/api/admin/users", headers=hg)
        assert resp.status_code == 200
        roles = {u["role"] for u in resp.get_json()["users"]}
        assert roles == {"huguan"}

    def test_huguan_cannot_promote_own_huguan(self, client):
        hg, _ = _huguan(client, "_hgm_promote")
        client.post("/api/admin/users/create", json={
            "username": "_hgm_sub1", "password": "test123"}, headers=hg)
        db = database.get_db()
        sub_id = db.execute("SELECT id FROM users WHERE username='_hgm_sub1'").fetchone()["id"]
        db.close()
        resp = client.post(f"/api/admin/users/{sub_id}/role", json={"role": "admin"}, headers=hg)
        assert resp.status_code == 400
        resp = client.post(f"/api/admin/users/{sub_id}/role", json={"role": "hidden"}, headers=hg)
        assert resp.status_code == 200

    def test_huguan_cannot_touch_others_huguan(self, client):
        hg_a, _ = _huguan(client, "_hgm_ownerA")
        hg_b, _ = _huguan(client, "_hgm_ownerB")
        client.post("/api/admin/users/create", json={
            "username": "_hgm_subB", "password": "test123"}, headers=hg_b)
        db = database.get_db()
        sub_b = db.execute("SELECT id FROM users WHERE username='_hgm_subB'").fetchone()["id"]
        db.close()
        resp = client.delete(f"/api/admin/users/{sub_b}", headers=hg_a)
        assert resp.status_code == 403
        assert resp.get_json()["error"] == "只能操作自己创建的户管"

    def test_huguan_cannot_touch_admin_or_user(self, client):
        hg, _ = _huguan(client, "_hgm_touch")
        _, user_id = _create_user(client, "_hgm_plain", role="user")
        _, admin_id = _create_user(client, "_hgm_admin", role="admin")
        for target in (user_id, admin_id):
            resp = client.post(f"/api/admin/users/{target}/toggle", headers=hg)
            assert resp.status_code == 403
            assert resp.get_json()["error"] == "户管只能操作户管账号"

    def test_huguan_cannot_toggle_self(self, client):
        hg, hg_id = _huguan(client, "_hgm_self")
        resp = client.post(f"/api/admin/users/{hg_id}/toggle", headers=hg)
        assert resp.status_code == 403
        assert resp.get_json()["error"] == "不能禁用自己"

    def test_admin_cannot_create_huguan(self, client):
        admin, _ = _create_user(client, "_hgm_admin2", role="admin")
        resp = client.post("/api/admin/users/create", json={
            "username": "_hgm_byadmin", "password": "test123", "role": "huguan",
        }, headers=admin)
        assert resp.status_code == 400
        assert resp.get_json()["error"] == "Invalid role"

    def test_developer_can_create_huguan(self, client):
        dev, _ = _create_user(client, "_hgm_dev", role="developer")
        resp = client.post("/api/admin/users/create", json={
            "username": "_hgm_bydev", "password": "test123", "role": "huguan",
        }, headers=dev)
        assert resp.status_code == 200

    def test_admin_platform_isolation_regression(self, client):
        """回归：平台隔离的错误文案与行为不变。"""
        _create_user(client, "_hgm_gg_user", role="user", platform="gg")
        tt_admin, _ = _create_user(client, "_hgm_tt_admin", role="admin", platform="tt")
        db = database.get_db()
        gg_uid = db.execute("SELECT id FROM users WHERE username='_hgm_gg_user'").fetchone()["id"]
        db.close()
        resp = client.post(f"/api/admin/users/{gg_uid}/role", json={"role": "viewer"}, headers=tt_admin)
        assert resp.status_code == 403
        assert resp.get_json()["error"] == "不能操作其他平台的用户"

    def test_huguan_cannot_trigger_scheduler(self, client):
        """户管不得获得定时任务权限（该接口只认 developer）。"""
        hg, _ = _huguan(client, "_hgm_sched")
        resp = client.post("/api/admin/trigger-weekly-cleanup", headers=hg)
        assert resp.status_code == 403

    def test_developer_and_admin_can_still_set_hidden(self, client):
        """回归：改角色接口对 developer / admin 仍能把用户设为 `hidden`。

        改动前 `py/main.py:7500` 的白名单是 `("user","admin","viewer","hidden")`，本任务把它
        换成「创建白名单 ∪ {hidden}」。若漏掉 `"hidden"` 的并集，developer / admin 会从 200 变 400 ——
        既违反纯增量原则，又因全仓无 `role.*hidden` 断言而不会被任何红灯拦下。本用例即为此设的守卫。
        """
        dev, _ = _create_user(client, "_hgm_dev_h", role="developer")
        admin, _ = _create_user(client, "_hgm_admin_h", role="admin")
        _, u1 = _create_user(client, "_hgm_h1", role="user")
        _, u2 = _create_user(client, "_hgm_h2", role="user")
        assert client.post(f"/api/admin/users/{u1}/role",
                           json={"role": "hidden"}, headers=dev).status_code == 200
        assert client.post(f"/api/admin/users/{u2}/role",
                           json={"role": "hidden"}, headers=admin).status_code == 200


class TestPlatformUsersEndpoint:
    def test_huguan_sees_only_current_platform(self, client):
        """户管切到 TT 时只应看到 TT + developer，不该看到 GG 行。

        注意这里用 `?platform=tt` 而**不是**调用者自身的 gg —— 否则即使
        `_get_effective_platform()` 完全忽略查询参数，本用例也会通过。

        两个夹具各配一个**本平台**账户：接口只列「名下有未删除账户」的人。
        若给 `_hgpu_gg` 不配账户（或配成 TT 账户），`_hgpu_gg not in names` 就会被
        账户过滤代为满足 —— 平台隔离一旦被破坏也不会红，那就成了空断言。
        """
        hg, _ = _huguan(client, "_hgpu_hg")  # users.platform == 'gg'
        db = database.get_db()
        db.execute("INSERT INTO users(username, password, role, platform) VALUES('_hgpu_gg','x','user','gg')")
        db.execute("INSERT INTO users(username, password, role, platform) VALUES('_hgpu_tt','x','user','tt')")
        gg_id = db.execute("SELECT id FROM users WHERE username='_hgpu_gg'").fetchone()["id"]
        tt_id = db.execute("SELECT id FROM users WHERE username='_hgpu_tt'").fetchone()["id"]
        db.execute("INSERT INTO accounts(name, account_id, owner_id) VALUES('GG夹具户','_hgpu_gg_acc',?)", (gg_id,))
        db.execute("INSERT INTO tt_accounts(name, advertiser_id, owner_id) VALUES('TT夹具户','_hgpu_tt_acc',?)", (tt_id,))
        db.commit()
        db.close()
        resp = client.get("/api/platform/users?platform=tt", headers=hg)
        assert resp.status_code == 200
        names = {u["username"] for u in resp.get_json()["users"]}
        assert "_hgpu_tt" in names
        assert "_hgpu_gg" not in names

    def test_includes_developer_excludes_hidden(self, client):
        """developer 行必须经 `OR role = 'developer'` 命中，hidden 行必须被排除。

        `_hgpu_dev` 故意插成 platform='tt'：调用者只查 platform='gg'，因此该行
        **只能**经 developer 分支出现。若把它插成 'gg'，它会被 `platform = ?`
        命中，删掉 `OR role = 'developer'` 断言也不会红 —— 那就成了空断言。

        两个夹具都配 **GG**（`accounts`）账户 —— 查的是 gg 面板，接口按有效平台选表，
        配错表或干脆不配，两条断言都会被账户过滤代为满足，同样失去守卫力。
        """
        hg, _ = _huguan(client, "_hgpu_hg2")
        db = database.get_db()
        db.execute("INSERT INTO users(username, password, role, platform) VALUES('_hgpu_dev','x','developer','tt')")
        db.execute("INSERT INTO users(username, password, role, platform) VALUES('_hgpu_hid','x','hidden','gg')")
        dev_id = db.execute("SELECT id FROM users WHERE username='_hgpu_dev'").fetchone()["id"]
        hid_id = db.execute("SELECT id FROM users WHERE username='_hgpu_hid'").fetchone()["id"]
        db.execute("INSERT INTO accounts(name, account_id, owner_id) VALUES('dev夹具户','_hgpu_dev_acc',?)", (dev_id,))
        db.execute("INSERT INTO accounts(name, account_id, owner_id) VALUES('hid夹具户','_hgpu_hid_acc',?)", (hid_id,))
        db.commit()
        db.close()
        resp = client.get("/api/platform/users?platform=gg", headers=hg)
        assert resp.status_code == 200
        names = {u["username"] for u in resp.get_json()["users"]}
        assert "_hgpu_dev" in names
        assert "_hgpu_hid" not in names

    def test_non_switch_role_cannot_pick_platform(self, client):
        """非切换角色传 ?platform= 必须被忽略，只能拿到自己平台的数据。

        本接口只挂 @jwt_required()，不像 /api/tt/users、/api/fb/users 那样挂平台
        装饰器，因此这条隔离属性只能靠本用例守护。

        两个夹具各配**本平台**账户（plain 配 GG、leak 配 TT）：接口只列「名下有未删除
        账户」的人，不配的话 `_hgpu_leak not in names` 会被账户过滤代为满足。
        """
        u, plain_id = _create_user(client, "_hgpu_plain", role="user", platform="gg")
        db = database.get_db()
        db.execute("INSERT INTO users(username, password, role, platform) VALUES('_hgpu_leak','x','user','tt')")
        leak_id = db.execute("SELECT id FROM users WHERE username='_hgpu_leak'").fetchone()["id"]
        db.execute("INSERT INTO accounts(name, account_id, owner_id) VALUES('plain夹具户','_hgpu_plain_acc',?)", (plain_id,))
        db.execute("INSERT INTO tt_accounts(name, advertiser_id, owner_id) VALUES('leak夹具户','_hgpu_leak_acc',?)", (leak_id,))
        db.commit()
        db.close()
        resp = client.get("/api/platform/users?platform=tt", headers=u)
        assert resp.status_code == 200
        names = {x["username"] for x in resp.get_json()["users"]}
        assert "_hgpu_leak" not in names
        # 正向断言：调用者自己（platform='gg'）必须在结果里。否则若接口返回空列表，
        # 上面那条负面断言也会通过 —— 那就成了空断言。
        assert "_hgpu_plain" in names


    def test_excludes_users_without_accounts(self, client):
        """新口径：非户管用户在该平台 0 户时，不出现在下拉里。"""
        hg, _ = _huguan(client, "_hgpu_hg3")
        _, with_acc = _create_user(client, "_hgpu_with", role="user", platform="gg")
        _, without_acc = _create_user(client, "_hgpu_without", role="user", platform="gg")
        db = database.get_db()
        db.execute("INSERT INTO accounts(name, account_id, owner_id) VALUES('有户','_hgpu_with_acc',?)", (with_acc,))
        db.commit()
        db.close()
        resp = client.get("/api/platform/users?platform=gg", headers=hg)
        assert resp.status_code == 200
        names = {u["username"] for u in resp.get_json()["users"]}
        assert "_hgpu_with" in names
        assert "_hgpu_without" not in names
        assert without_acc  # 夹具确实建出来了（避免上面那条负面断言因夹具不存在而恒真）

    def test_deleted_account_does_not_count(self, client):
        """新口径：「有账户」看的是**未删除**的户 —— 只剩软删除户的人同样被排除。

        守卫 `a.deleted_at IS NULL`：把它删掉，本用例必红。
        """
        hg, _ = _huguan(client, "_hgpu_hg4")
        _, uid = _create_user(client, "_hgpu_deleted", role="user", platform="gg")
        db = database.get_db()
        db.execute("INSERT INTO accounts(name, account_id, owner_id, deleted_at) "
                   "VALUES('已删除户','_hgpu_del_acc',?, datetime('now','localtime'))", (uid,))
        db.commit()
        db.close()
        resp = client.get("/api/platform/users?platform=gg", headers=hg)
        assert resp.status_code == 200
        names = {u["username"] for u in resp.get_json()["users"]}
        assert "_hgpu_deleted" not in names

    def test_huguan_exempt_even_without_accounts(self, client):
        """新口径：户管豁免 —— 自己在该平台 0 户也仍列出（户管管理所有户）。

        守卫 `u.role = 'huguan' OR ...`：把它删掉，本用例必红。
        """
        hg, _ = _huguan(client, "_hgpu_hg_exempt")
        resp = client.get("/api/platform/users?platform=gg", headers=hg)
        assert resp.status_code == 200
        names = {u["username"] for u in resp.get_json()["users"]}
        assert "_hgpu_hg_exempt" in names

    def test_account_table_follows_effective_platform(self, client):
        """新口径：账户表按**有效平台**选 —— 只持 GG 户的人不进 tt 面板下拉，反之亦然。

        两个夹具都用 **developer**：developer 经 `OR role = 'developer'` 必然通过基础
        平台过滤，因此「在不在结果里」**只由账户表的选择决定** —— 把任一方向的映射弄反，
        本用例都会红。

        切勿改用普通 user 做夹具：他们会先被 `platform = ?` 挡掉，断言退化成恒真
        （作者初版即犯此错，靠变异测试才发现）。
        """
        hg, _ = _huguan(client, "_hgpu_hg5")
        _, gg_only = _create_user(client, "_hgpu_ggonly", role="developer", platform="gg")
        _, tt_only = _create_user(client, "_hgpu_ttonly", role="developer", platform="gg")
        db = database.get_db()
        db.execute("INSERT INTO accounts(name, account_id, owner_id) VALUES('只GG户','_hgpu_ggonly_acc',?)", (gg_only,))
        db.execute("INSERT INTO tt_accounts(name, advertiser_id, owner_id) VALUES('只TT户','_hgpu_ttonly_acc',?)", (tt_only,))
        db.commit()
        db.close()
        gg = {u["username"] for u in client.get("/api/platform/users?platform=gg", headers=hg).get_json()["users"]}
        tt = {u["username"] for u in client.get("/api/platform/users?platform=tt", headers=hg).get_json()["users"]}
        assert "_hgpu_ggonly" in gg, "只持 GG 户的人必须出现在 gg 面板"
        assert "_hgpu_ggonly" not in tt, "只持 GG 户的人不该出现在 tt 面板（表选对了才会被排除）"
        assert "_hgpu_ttonly" in tt, "只持 TT 户的人必须出现在 tt 面板"
        assert "_hgpu_ttonly" not in gg, "只持 TT 户的人不该出现在 gg 面板（表选对了才会被排除）"


def _mk_account(db, owner_id, account_id, name="测试账户"):
    db.execute("INSERT INTO accounts(name, account_id, owner_id) VALUES(?,?,?)",
               (name, account_id, owner_id))
    db.commit()


class TestGgAccountListCrossUser:
    def _setup(self, client):
        hg, hg_id = _huguan(client, "_ggac_hg")
        _, u1 = _create_user(client, "_ggac_u1", role="user")
        _, u2 = _create_user(client, "_ggac_u2", role="user")
        db = database.get_db()
        _mk_account(db, u1, "GG-AC-1", "U1账户")
        _mk_account(db, u2, "GG-AC-2", "U2账户")
        db.close()
        return hg, hg_id, u1, u2

    def test_regular_user_sees_only_own(self, client):
        _, _, u1, _ = self._setup(client)
        hdr, _ = _create_user(client, "_ggac_u1b", role="user")
        resp = client.get("/api/accounts/list?size=50", headers=hdr)
        assert [a["account_id"] for a in resp.get_json()["accounts"]] == []

    def test_huguan_sees_all_users(self, client):
        hg, _, _, _ = self._setup(client)
        resp = client.get("/api/accounts/list?size=50", headers=hg)
        ids = {a["account_id"] for a in resp.get_json()["accounts"]}
        assert ids == {"GG-AC-1", "GG-AC-2"}

    def test_huguan_filters_by_owner_id(self, client):
        hg, _, u1, _ = self._setup(client)
        resp = client.get(f"/api/accounts/list?size=50&owner_id={u1}", headers=hg)
        ids = {a["account_id"] for a in resp.get_json()["accounts"]}
        assert ids == {"GG-AC-1"}

    def test_status_counts_follow_owner_filter(self, client):
        """状态计数必须与 owner_id 筛选同步，否则出现「列表1条、计数3条」。"""
        hg, _, u1, _ = self._setup(client)
        resp = client.get(f"/api/accounts/list?size=50&owner_id={u1}", headers=hg)
        assert resp.get_json()["status_counts"].get("存活", 0) == 1

    def test_regular_user_ignores_owner_id(self, client):
        """回归：普通用户传 owner_id 不能越权看到别人的账户。"""
        _, _, u1, _ = self._setup(client)
        hdr, _ = _create_user(client, "_ggac_u3", role="user")
        db = database.get_db()
        _mk_account(db, _create_user(client, "_ggac_u3b", role="user")[1], "GG-AC-3")
        db.close()
        resp = client.get(f"/api/accounts/list?size=50&owner_id={u1}", headers=hdr)
        assert [a["account_id"] for a in resp.get_json()["accounts"]] == []

    def test_huguan_agent_filter_not_scoped_to_self(self, client):
        """户管不带 owner_id 时按代理名筛选，必须匹配到别人账户上的代理。

        回归点：若 agent / status 四处子查询写成 `owner_filter or user_id`，无筛选时
        `"" or user_id` 退化为**户管自己的 id**，会把别人账户上的代理整片滤掉 ——
        与「跨用户可见」的目的直接矛盾。上面 5 条用例都没有设 agent，抓不到这个 bug，
        本用例即为此设的守卫。
        """
        hg, _, u1, _ = self._setup(client)
        db = database.get_db()
        db.execute("INSERT INTO agents(name, owner_id, platform) VALUES('代理甲', ?, 'gg')", (u1,))
        ag_id = db.execute("SELECT id FROM agents WHERE name='代理甲'").fetchone()["id"]
        db.execute("UPDATE accounts SET agent_id=? WHERE account_id='GG-AC-1'", (ag_id,))
        db.commit()
        db.close()
        resp = client.get("/api/accounts/list?size=50&agent=代理甲", headers=hg)
        ids = {a["account_id"] for a in resp.get_json()["accounts"]}
        assert ids == {"GG-AC-1"}

    def test_regular_user_agent_filter_still_scoped_to_self(self, client):
        """回归：普通用户按代理名筛选仍然是「只看自己的账户」，不得因本次改动放宽。"""
        _, _, u1, _ = self._setup(client)
        db = database.get_db()
        db.execute("INSERT INTO agents(name, owner_id, platform) VALUES('代理乙', ?, 'gg')", (u1,))
        ag_id = db.execute("SELECT id FROM agents WHERE name='代理乙'").fetchone()["id"]
        db.execute("UPDATE accounts SET agent_id=? WHERE account_id='GG-AC-1'", (ag_id,))
        db.commit()
        db.close()
        hdr, _ = _create_user(client, "_ggac_u4", role="user")
        resp = client.get("/api/accounts/list?size=50&agent=代理乙", headers=hdr)
        assert [a["account_id"] for a in resp.get_json()["accounts"]] == []


def _mk_mcc(db, owner_id, mcc_code, name="测试MCC"):
    db.execute("INSERT INTO mcc(name, mcc_id, owner_id) VALUES(?,?,?)", (name, mcc_code, owner_id))
    db.commit()


class TestGgMccListCrossUser:
    def _setup(self, client):
        hg, hg_id = _huguan(client, "_ggmcc_hg")
        _, u1 = _create_user(client, "_ggmcc_u1", role="user")
        _, u2 = _create_user(client, "_ggmcc_u2", role="user")
        db = database.get_db()
        _mk_mcc(db, u1, "MCC-1", "U1的MCC")
        _mk_mcc(db, u2, "MCC-2", "U2的MCC")
        db.close()
        return hg, hg_id, u1, u2

    def test_huguan_sees_all_mcc(self, client):
        hg, _, _, _ = self._setup(client)
        resp = client.get("/api/mcc/list?size=50", headers=hg)
        assert resp.status_code == 200
        codes = {m["mcc_id"] for m in resp.get_json()["mcc_list"]}
        assert codes == {"MCC-1", "MCC-2"}

    def test_huguan_filters_by_owner(self, client):
        hg, _, u1, _ = self._setup(client)
        resp = client.get(f"/api/mcc/list?size=50&owner_id={u1}", headers=hg)
        codes = {m["mcc_id"] for m in resp.get_json()["mcc_list"]}
        assert codes == {"MCC-1"}

    def test_regular_user_still_scoped(self, client):
        """回归：普通用户看不到别人的 MCC，且 owner_id 参数无效。"""
        _, _, u1, _ = self._setup(client)
        hdr, _ = _create_user(client, "_ggmcc_u3", role="user")
        resp = client.get(f"/api/mcc/list?size=50&owner_id={u1}", headers=hdr)
        assert resp.get_json()["mcc_list"] == []


class TestGgAccountListDropdownOwnerLeak:
    """守护 /api/accounts/list 下拉数据的归属收放（Task 5 引入的
    `if not cross_user: owner_filter = ""`）。

    Task 5 的 test_regular_user_ignores_owner_id 只断言 accounts 数组为空，而该数组由
    where 列表里恒为「自身 id」的归属分支兜底 —— 即使把那行守卫删掉，普通用户传
    owner_id 也仍然拿不到别人的 accounts，所以它抓不到下拉数据的越权。本用例专盯
    mcc_options / agents / timezone_options 三个下拉字段。
    """

    def test_regular_user_cannot_leak_dropdown_via_owner_id(self, client):
        # _app_cache 是进程级全局缓存，pytest 不重置它，且缓存键只含 user_id + scope、
        # 不含 agent 等筛选参数。若不清空，其它用例留下的同键空列表会让本用例变成空断言。
        from cache import cache as _app_cache
        _app_cache.clear()

        hdr_b, _ = _create_user(client, "_ggdd_b", role="user")  # 调用者 B：什么都不拥有
        _, a_id = _create_user(client, "_ggdd_a", role="user")   # 数据所有者 A
        db = database.get_db()
        _mk_account(db, a_id, "GG-DD-1", "A的账户")
        _mk_mcc(db, a_id, "MCC-DD", "A的MCC")
        db.execute("INSERT INTO agents(name, owner_id, platform) VALUES('代理DD', ?, 'gg')", (a_id,))
        ag_id = db.execute("SELECT id FROM agents WHERE name='代理DD'").fetchone()["id"]
        db.execute("UPDATE accounts SET agent_id=?, timezone='Asia/Shanghai' WHERE account_id='GG-DD-1'",
                   (ag_id,))
        db.commit()
        db.close()

        resp = client.get(f"/api/accounts/list?size=50&owner_id={a_id}&agent=代理DD", headers=hdr_b)
        assert resp.status_code == 200
        data = resp.get_json()
        # accounts 本就被 where 的归属分支挡掉，不是本用例的重点
        assert data["accounts"] == []
        # 三个下拉字段才是守卫真正保护的地方
        assert [m["name"] for m in data["mcc_options"]] == []
        assert data["agents"] == []
        assert data["timezone_options"] == []


class TestGgAgentsDropdownCacheInvalidation:
    """回归：改代理名后，账户面板「代理」下拉的缓存必须立刻失效。

    `py/main.py:3757` 把 agents 下拉缓存键从 `accounts:agents:{uid}` 改成带 owner 维度的
    `accounts:agents:{uid}:{scope}`，但两处写接口（PUT /api/agents/<aid> 改名、
    DELETE /api/agents/<aid>）仍在删**旧键**。`SimpleCache.delete` 是精确匹配的
    dict.pop（`py/cache.py:33-36`），旧键早已不存在 —— 两次删除退化为空操作，
    改名后下拉框在 120s TTL 内仍返回旧代理名，违反纯增量原则（对既有角色而言是行为倒退）。
    `test_rename_invalidates_agents_dropdown_cache` 是为这次回归设的守卫：
    改回 `delete` 即变红。

    缓存的清空只放在**开头**：第 1 步 GET 会立刻把该键重新写热，
    因此开头清缓存不会掩盖 bug —— 若第 3 步仍读到旧名字，说明写接口的失效调用确实没生效。
    放在开头是为了消除对**用例执行顺序**的依赖（`_app_cache` 是进程级全局缓存，
    pytest 不重置，且各用例的临时库会把用户 id 从 1 重新分配，他测遗留的
    `accounts:agents:1:1` 会与本用例的键撞车）。
    """

    def test_rename_invalidates_agents_dropdown_cache(self, client):
        from cache import cache as _app_cache
        _app_cache.clear()

        headers, uid = _create_user(client, "_gginv_u", role="user")
        db = database.get_db()
        _mk_account(db, uid, "GG-INV-1", "缓存账户")
        db.execute("INSERT INTO agents(name, owner_id, platform) VALUES(?,?,?)",
                   ("改名前代理", uid, "gg"))
        aid = db.execute("SELECT id FROM agents WHERE name='改名前代理'").fetchone()["id"]
        db.execute("UPDATE accounts SET agent_id=? WHERE account_id='GG-INV-1'", (aid,))
        db.commit()
        db.close()

        # 第 1 步：读到改名前的下拉值，同时把该键的缓存写热
        data = client.get("/api/accounts/list?size=50", headers=headers).get_json()
        assert "改名前代理" in data["agents"]

        # 第 2 步：改名
        resp = client.put(f"/api/agents/{aid}", json={"name": "改名后代理"}, headers=headers)
        assert resp.status_code == 200

        # 第 3 步：缓存必须已被失效 —— 否则这里仍是「改名前代理」
        data = client.get("/api/accounts/list?size=50", headers=headers).get_json()
        assert "改名后代理" in data["agents"]
        assert "改名前代理" not in data["agents"]

    def test_create_invalidates_agents_dropdown_cache(self, client):
        """回归：新增代理后，账户面板「代理」下拉的缓存必须立刻失效。

        与上面那条同类：`/api/agents/create` 此前从不失效 `accounts:agents:{uid}:{scope}`，
        故「面板已加载 → 新建代理 → 挂到账户上 → 面板重载」会在 120s TTL 内读到旧列表。

        注意下拉的取值是
        `SELECT DISTINCT ag.name FROM agents ag INNER JOIN accounts a ON a.agent_id = ag.id`
        —— 只列**被账户引用**的代理，所以第 3 步必须先把新代理挂到账户上，
        否则「新代理不在列表里」是正确行为，用例会变成假绿。

        同 `test_rename_invalidates_agents_dropdown_cache`：清缓存只放在开头，
        它不会掩盖 bug —— 若第 2 步的失效调用没生效，第 4 步会读到第 1 步的旧列表。
        """
        from cache import cache as _app_cache
        _app_cache.clear()

        headers, uid = _create_user(client, "_ggcrt_u", role="user")
        db = database.get_db()
        _mk_account(db, uid, "GG-CRT-1", "新建缓存账户")
        db.execute("INSERT INTO agents(name, owner_id, platform) VALUES(?,?,?)",
                   ("原有代理", uid, "gg"))
        aid = db.execute("SELECT id FROM agents WHERE name='原有代理'").fetchone()["id"]
        db.execute("UPDATE accounts SET agent_id=? WHERE account_id='GG-CRT-1'", (aid,))
        db.commit()
        db.close()

        # 第 1 步：加载面板 —— 同时把该键的缓存写热
        data = client.get("/api/accounts/list?size=50", headers=headers).get_json()
        assert "原有代理" in data["agents"]

        # 第 2 步：新增代理（此调用必须失效缓存）
        resp = client.post("/api/agents/create", json={"name": "新建代理"}, headers=headers)
        assert resp.status_code == 200

        # 第 3 步：把新代理挂到账户上（账户写入路径不失效该缓存，故第 4 步要靠第 2 步的失效）
        db = database.get_db()
        new_aid = db.execute("SELECT id FROM agents WHERE name='新建代理'").fetchone()["id"]
        db.execute("UPDATE accounts SET agent_id=? WHERE account_id='GG-CRT-1'", (new_aid,))
        db.commit()
        db.close()

        # 第 4 步：缓存必须已被第 2 步失效 —— 否则这里仍是第 1 步的旧列表
        data = client.get("/api/accounts/list?size=50", headers=headers).get_json()
        assert "新建代理" in data["agents"]


def _agents_dropdown_key(uid):
    """`/api/accounts/list` 为非跨用户角色写下的 agents 下拉缓存键。

    `py/main.py` 的 `scope = owner_filter or "all" if cross_user else str(user_id)`，
    普通角色恒走 `str(user_id)` 分支 ⇒ 键的 scope 段就是 uid 本身。
    """
    return f"accounts:agents:{uid}:{uid}"


class TestAnyAgentsInsertInvalidatesDropdownCache:
    """Task 21：把「任何写入 `agents` 表的路径都必须让代理名下拉缓存立即失效」
    这条不变量在全仓 9 处 `INSERT INTO agents` 上钉死。

    前一个提交 `710c0de` 只修了 `/api/agents/create` 的 TT/GG 两个分支；本次补齐
    其余 7 处（`main.py` 5 处 + `routes/tt_accounts_routes.py` 2 处）。
    失效形态统一为 `_app_cache.clear_prefix("accounts:agents:")`。

    测试口径分两类，**分类依据见 py/cache.py 与 `/api/accounts/list` 的查询**：

    * **行为断言**（A1 `accounts_create` / A2 `accounts_batch_create` /
      A3 `_execute_sync_create`）：这三条路径插入 agents 行后**立刻把新代理挂到
      账户上**，而 `accounts:agents:` 的唯一消费者 = `/api/accounts/list` 的
      `agents` 字段，其 SQL 带 `INNER JOIN accounts ON a.agent_id = ag.id`
      （只列被账户引用的代理）⇒ 新代理名真的会出现在下拉里，可做端到端断言。
    * **白盒不变量断言**（A4 `recharge_submit` / A5 `recharge_batch_submit` /
      B1 `_resolve_agent_id` / B2 `_ensure_agent`）：这四处**没有任何账户会引用**
      新插入的代理（充值与 TT 助手都是纯 agents 行写入；TT 账户又落在独立的
      `tt_accounts` 表、其下拉走无缓存的 `/api/agents/list?platform=tt`），
      行为断言在此**不可能成立** —— 「新代理不在下拉里」本来就是正确行为。
      故只能退化为白盒断言：调端点后直接断言该缓存键已从进程级缓存中消失。
      这仍是**真断言**：把对应的 `clear_prefix` 那行删掉必然变红。
    """

    # ---------- A 组可观测的 3 处：行为断言 ----------

    def test_accounts_create_invalidates_agents_dropdown_cache(self, client):
        """A1 `py/main.py` `accounts_create`：`POST /api/accounts/create` 的 agent 文本回退分支。"""
        from cache import cache as _app_cache
        _app_cache.clear()

        headers, _ = _create_user(client, "_t21_a1_u", role="user")

        # 第 1 步：加载面板 → 把 accounts:agents:{uid}:{uid} 写热（此时列表为空）
        data = client.get("/api/accounts/list?size=50", headers=headers).get_json()
        assert "T21代建代理" not in data["agents"]

        # 第 2 步：POST /api/accounts/create 传一个从未用过的代理名
        #         → 走 INSERT INTO agents，并立刻把新账户挂到该代理上
        resp = client.post("/api/accounts/create", json={
            "name": "T21代建账户", "account_id": "T21-A1-1", "agent": "T21代建代理",
        }, headers=headers)
        assert resp.status_code == 200

        # 第 3 步：不手动清缓存 —— 若第 2 步没失效，这里仍是第 1 步的旧列表
        data = client.get("/api/accounts/list?size=50", headers=headers).get_json()
        assert "T21代建代理" in data["agents"]

    def test_accounts_batch_create_invalidates_agents_dropdown_cache(self, client):
        """A2 `py/main.py` `accounts_batch_create`：逐账户 agent 文本回退分支。"""
        from cache import cache as _app_cache
        _app_cache.clear()

        headers, _ = _create_user(client, "_t21_a2_u", role="user")

        data = client.get("/api/accounts/list?size=50", headers=headers).get_json()
        assert "T21批量代理" not in data["agents"]

        resp = client.post("/api/accounts/batch-create", json={
            "account_ids": ["T21-A2-1"], "agent": "T21批量代理",
        }, headers=headers)
        assert resp.status_code == 200

        data = client.get("/api/accounts/list?size=50", headers=headers).get_json()
        assert "T21批量代理" in data["agents"]

    def test_sync_create_invalidates_agents_dropdown_cache(self, client, monkeypatch):
        """A3 `_execute_sync_create`：`POST /api/accounts/sync-from-sheet` 的
        `confirmed.create` 分支（真正的清缓存点在其调用方的 `db.commit()` 之后，
        因为该助手自身不 commit；本用例走完整端点，覆盖的正是那个调用方位置）。
        """
        import unittest.mock as mock

        import main
        from cache import cache as _app_cache
        _app_cache.clear()

        headers, uid = _create_user(client, "_t21_a3_u", role="user")
        db = database.get_db()
        # 门禁要求 A 列「运营」匹配当前登录用户的 display_name
        db.execute("UPDATE users SET display_name='_t21_a3_u' WHERE id=?", (uid,))
        # 同步入口的前置：表格 ID 未配置会 400 早退，到不了 confirmed.create 分支
        db.execute("INSERT OR REPLACE INTO tags(key,value) VALUES('recharge_sheet_id','sheet-t21')")
        db.commit()
        db.close()

        # 凭据路径只被 os.path.isfile 做存在性判断，指向本测试文件即可
        # （真正会发网络请求的 Sheets 调用全部被 mock 掉）
        monkeypatch.setitem(main._GOOGLE_SHEETS_CONFIG, "credentials_path", __file__)
        # 步骤 10c 的 Sheets 回写走后台线程；测试里替换成空实现，避免真实网络与线程竞态
        monkeypatch.setattr(main, "_sync_sheets_background", lambda *a, **k: None)

        # 第 1 步：把缓存写热
        data = client.get("/api/accounts/list?size=50", headers=headers).get_json()
        assert "T21同步代理" not in data["agents"]

        # 看板行格式（A:H）：A运营 B账户ID C代理 D- E时区 F备注 G是否封户 H解绑
        rows = [
            ["运营", "账户ID", "代理", "", "时区", "备注", "是否封户", "解绑"],
            ["_t21_a3_u", "T21-A3-1", "T21同步代理", "", "Asia/Shanghai", "", "可用", ""],
        ]

        # 第 2 步：dry_run=False 走 confirmed.create → _execute_sync_create 插入 agents + accounts
        with mock.patch("google_sheets_service.build_service", return_value=object()), \
             mock.patch("google_sheets_service.read_sheet_values", return_value=rows):
            resp = client.post("/api/accounts/sync-from-sheet", json={
                "dry_run": False,
                "confirmed": {"create": [{
                    "account_id": "T21-A3-1", "agent": "T21同步代理",
                    "timezone": "Asia/Shanghai",
                }]},
            }, headers=headers)
        assert resp.status_code == 200
        assert resp.get_json()["result"]["created"] == 1

        # 第 3 步：缓存必须已被调用方的清缓存行失效
        data = client.get("/api/accounts/list?size=50", headers=headers).get_json()
        assert "T21同步代理" in data["agents"]

    # ---------- A 组不可观测的 2 处 + B 组 2 处：白盒不变量断言 ----------

    def test_recharge_submit_invalidates_agents_dropdown_cache(self, client):
        """A4 `py/main.py` `recharge_submit`。

        白盒断言而非行为断言的原因见本类 docstring：充值只插入 agents 行，
        没有任何账户引用它 ⇒ 它**本就不该**出现在 `INNER JOIN accounts` 的下拉里，
        「下拉里没有它」恒为真，行为断言会退化成恒真式。
        """
        from cache import cache as _app_cache
        _app_cache.clear()

        headers, uid = _create_user(client, "_t21_a4_u", role="user")
        db = database.get_db()
        _mk_account(db, uid, "T21-A4-1", "T21充值账户")
        db.close()

        key = _agents_dropdown_key(uid)
        client.get("/api/accounts/list?size=50", headers=headers)
        assert _app_cache.get(key) is not None, "前置失败：下拉缓存没被写热"

        resp = client.post("/api/recharge/submit", json={
            "account_id": "T21-A4-1", "amount": "100", "agent": "T21充值新代理",
        }, headers=headers)
        assert resp.status_code == 200

        assert _app_cache.get(key) is None, "写入 agents 表后 accounts:agents: 缓存未失效"

    def test_recharge_batch_submit_invalidates_agents_dropdown_cache(self, client):
        """A5 `py/main.py` `recharge_batch_submit`（INSERT 在 for 循环体内）。"""
        from cache import cache as _app_cache
        _app_cache.clear()

        headers, uid = _create_user(client, "_t21_a5_u", role="user")
        db = database.get_db()
        _mk_account(db, uid, "T21-A5-1", "T21批量充值账户")
        db.close()

        key = _agents_dropdown_key(uid)
        client.get("/api/accounts/list?size=50", headers=headers)
        assert _app_cache.get(key) is not None, "前置失败：下拉缓存没被写热"

        resp = client.post("/api/recharge/batch-submit", json={
            "records": [{"account_id": "T21-A5-1", "amount": "100", "agent": "T21批量充值新代理"}],
        }, headers=headers)
        assert resp.status_code == 200

        assert _app_cache.get(key) is None, "写入 agents 表后 accounts:agents: 缓存未失效"

    def test_tt_create_account_invalidates_agents_dropdown_cache(self, client):
        """B1 `py/routes/tt_accounts_routes.py` `_resolve_agent_id`（模块级助手，自身不 commit）。

        白盒断言的原因：TT 代理落在独立命名空间，其下拉走**无缓存**的
        `/api/agents/list?platform=tt`；`accounts:agents:` 缓存只服务 GG 面板。
        """
        from cache import cache as _app_cache
        _app_cache.clear()

        headers, uid = _create_user(client, "_t21_b1_u", role="user", platform="tt")

        key = _agents_dropdown_key(uid)
        client.get("/api/accounts/list?size=50", headers=headers)
        assert _app_cache.get(key) is not None, "前置失败：下拉缓存没被写热"

        resp = client.post("/api/tt/accounts/create", json={
            "advertiser_id": "999000111222", "name": "T21TT账户", "agent": "T21TT新代理",
        }, headers=headers)
        assert resp.status_code == 200

        assert _app_cache.get(key) is None, "写入 agents 表后 accounts:agents: 缓存未失效"

    def test_tt_sync_from_sheet_invalidates_agents_dropdown_cache(self, client):
        """B2 `py/routes/tt_accounts_routes.py` `_ensure_agent`（看板同步确认模式）。

        白盒断言的原因同 B1。`_ensure_agent` 只从
        `POST /api/tt/accounts/sync-from-sheet`（非 dry_run）到达，
        故这里 mock 掉 Sheets 读接口把该流程走通。
        """
        import unittest.mock as mock

        from cache import cache as _app_cache
        _app_cache.clear()

        headers, uid = _create_user(client, "_t21_b2_u", role="user", platform="tt")
        db = database.get_db()
        # 门禁要求 A 列「运营」匹配当前登录用户的 display_name
        db.execute("UPDATE users SET display_name='_t21_b2_u' WHERE id=?", (uid,))
        db.execute("INSERT OR REPLACE INTO tags(key,value) VALUES('tt_sheet_id','sheet-t21-tt')")
        db.execute("INSERT OR REPLACE INTO tags(key,value) VALUES('tt_sheet_mappings', ?)",
                   ('{"my_dashboard": "我的看板"}',))
        db.commit()
        db.close()

        key = _agents_dropdown_key(uid)
        client.get("/api/accounts/list?size=50", headers=headers)
        assert _app_cache.get(key) is not None, "前置失败：下拉缓存没被写热"

        # 看板行格式（A:J）：A运营 B入库 C是否回收 D账户ID EBC F国家 G渠道 H时区 I消耗 J备注
        rows = [
            ["运营", "入库时间", "是否回收", "账户ID", "BC", "国家", "渠道", "时区", "消耗", "备注"],
            ["_t21_b2_u", "2026-09-20", "否", "999000333444", "BC-T21", "US",
             "T21TT同步代理", "+8", "", ""],
        ]

        with mock.patch("google_sheets_service.build_service", return_value=object()), \
             mock.patch("google_sheets_service.read_sheet_values", return_value=rows):
            resp = client.post("/api/tt/accounts/sync-from-sheet",
                               json={"dry_run": False}, headers=headers)
        assert resp.status_code == 200
        # 确认模式返回的是计数（dry_run 模式才返回明细列表）
        assert resp.get_json()["created"] == 1

        assert _app_cache.get(key) is None, "写入 agents 表后 accounts:agents: 缓存未失效"


class TestGgAccountOwnership:
    def test_huguan_creates_for_other_user(self, client):
        hg, hg_id = _huguan(client, "_ggown_hg")
        _, u1 = _create_user(client, "_ggown_u1", role="user")
        resp = client.post("/api/accounts/create", json={
            "name": "代建账户", "account_id": "GG-OWN-1",
            "owner_id": u1, "agent": "代建代理",
        }, headers=hg)
        assert resp.status_code == 200
        db = database.get_db()
        acc = db.execute("SELECT owner_id FROM accounts WHERE account_id='GG-OWN-1'").fetchone()
        ag = db.execute("SELECT owner_id FROM agents WHERE name='代建代理'").fetchone()
        db.close()
        assert acc["owner_id"] == u1
        assert ag["owner_id"] == u1

    def test_huguan_creates_without_owner_defaults_to_self(self, client):
        hg, hg_id = _huguan(client, "_ggown_hg2")
        resp = client.post("/api/accounts/create", json={
            "name": "自建账户", "account_id": "GG-OWN-2"}, headers=hg)
        assert resp.status_code == 200
        db = database.get_db()
        acc = db.execute("SELECT owner_id FROM accounts WHERE account_id='GG-OWN-2'").fetchone()
        db.close()
        assert acc["owner_id"] == hg_id

    def test_regular_user_owner_id_ignored_on_create(self, client):
        """回归：普通用户传 owner_id 不能把账户建到别人名下。"""
        _, u1 = _create_user(client, "_ggown_u2", role="user")
        hdr, me = _create_user(client, "_ggown_u3", role="user")
        resp = client.post("/api/accounts/create", json={
            "name": "越权账户", "account_id": "GG-OWN-3", "owner_id": u1}, headers=hdr)
        assert resp.status_code == 200
        db = database.get_db()
        acc = db.execute("SELECT owner_id FROM accounts WHERE account_id='GG-OWN-3'").fetchone()
        db.close()
        assert acc["owner_id"] == me

    def test_huguan_reassigns_to_target_user(self, client):
        hg, hg_id = _huguan(client, "_ggown_hg3")
        _, u1 = _create_user(client, "_ggown_u4", role="user")
        db = database.get_db()
        _mk_account(db, hg_id, "GG-OWN-4", "待转移")
        aid = db.execute("SELECT id FROM accounts WHERE account_id='GG-OWN-4'").fetchone()["id"]
        db.close()
        resp = client.put(f"/api/accounts/{aid}/reassign", json={"owner_id": u1}, headers=hg)
        assert resp.status_code == 200
        db = database.get_db()
        acc = db.execute("SELECT owner_id FROM accounts WHERE id=?", (aid,)).fetchone()
        db.close()
        assert acc["owner_id"] == u1

    def test_regular_user_owner_id_ignored_on_reassign(self, client):
        """回归：普通用户传 owner_id 不能把账户转给别人。

        reassign 的 `owner_id` 分支与 create 的**互相独立**（两处 `target_owner` 计算），
        只测 create 会让漏改这里的情况全绿。本用例即为此设的守卫：账户原属 u1，
        普通用户 caller 传 `owner_id=u1` 时应转给 caller 自己，而不是留在 u1 名下。
        """
        _, u1 = _create_user(client, "_ggown_u5", role="user")
        hdr, me = _create_user(client, "_ggown_u6", role="user")
        db = database.get_db()
        _mk_account(db, u1, "GG-OWN-5", "u1的账户")
        aid = db.execute("SELECT id FROM accounts WHERE account_id='GG-OWN-5'").fetchone()["id"]
        db.close()
        resp = client.put(f"/api/accounts/{aid}/reassign", json={"owner_id": u1}, headers=hdr)
        assert resp.status_code == 200
        db = database.get_db()
        owner = db.execute("SELECT owner_id FROM accounts WHERE id=?", (aid,)).fetchone()["owner_id"]
        db.close()
        assert owner == me


def _mk_tt_account(db, owner_id, adv_id, name="TT账户"):
    db.execute("INSERT INTO tt_accounts(name, advertiser_id, owner_id) VALUES(?,?,?)",
               (name, adv_id, owner_id))
    db.commit()


class TestTtCrossUser:
    def test_huguan_edits_other_users_tt_account(self, client):
        hg, _ = _huguan(client, "_tt_cs_hg")
        _, u1 = _create_user(client, "_tt_cs_u1", role="user", platform="tt")
        db = database.get_db()
        _mk_tt_account(db, u1, "TT-ADV-1")
        aid = db.execute("SELECT id FROM tt_accounts WHERE advertiser_id='TT-ADV-1'").fetchone()["id"]
        db.close()
        resp = client.put(f"/api/tt/accounts/{aid}", json={"name": "改名后"},
                          headers=hg)
        assert resp.status_code == 200
        db = database.get_db()
        row = db.execute("SELECT name FROM tt_accounts WHERE id=?", (aid,)).fetchone()
        db.close()
        assert row["name"] == "改名后"

    def test_regular_user_cannot_edit_other_users_tt_account(self, client):
        """回归：普通用户编辑他人 TT 账户仍 403。"""
        _, u1 = _create_user(client, "_tt_cs_u2", role="user", platform="tt")
        other, _ = _create_user(client, "_tt_cs_u3", role="user", platform="tt")
        db = database.get_db()
        _mk_tt_account(db, u1, "TT-ADV-2")
        aid = db.execute("SELECT id FROM tt_accounts WHERE advertiser_id='TT-ADV-2'").fetchone()["id"]
        db.close()
        resp = client.put(f"/api/tt/accounts/{aid}", json={"name": "越权改名"}, headers=other)
        assert resp.status_code == 403

    def test_huguan_edits_other_users_bc(self, client):
        hg, _ = _huguan(client, "_tt_bc_hg")
        _, u1 = _create_user(client, "_tt_bc_u1", role="user", platform="tt")
        db = database.get_db()
        db.execute("INSERT INTO tt_bcs(name, bc_id, owner_id) VALUES('BC1','BC-1',?)", (u1,))
        db.commit()
        bid = db.execute("SELECT id FROM tt_bcs WHERE bc_id='BC-1'").fetchone()["id"]
        db.close()
        resp = client.put(f"/api/tt/bcs/{bid}", json={"name": "BC改名"}, headers=hg)
        assert resp.status_code == 200
        db = database.get_db()
        row = db.execute("SELECT name FROM tt_bcs WHERE id=?", (bid,)).fetchone()
        db.close()
        assert row["name"] == "BC改名"

    def test_huguan_sees_other_users_bc_in_list(self, client):
        """BC 列表可见性：户管能改他人 BC（上一条）也必须能**看到**它。

        对应 `tt_routes.py:30`（`list_bcs`）。原计划表把这行标成「不改、无判断语义」是误标，
        缺了它户管就会「点得动但看不见」。
        """
        hg, _ = _huguan(client, "_tt_bcl_hg")
        _, u1 = _create_user(client, "_tt_bcl_u1", role="user", platform="tt")
        db = database.get_db()
        db.execute("INSERT INTO tt_bcs(name, bc_id, owner_id) VALUES('别人BC','BC-L1',?)", (u1,))
        db.commit()
        db.close()
        resp = client.get("/api/tt/bcs/list?size=50", headers=hg)
        assert resp.status_code == 200
        names = {b["name"] for b in resp.get_json()["items"]}
        assert "别人BC" in names

    def test_huguan_cannot_see_other_users_products(self, client):
        """回归守卫：产品域**不**放行。

        `tt_routes.py:158`（`list_products`）在原计划表里被误标为「要改」。若照原表替换，
        户管将跨用户看到全部产品，直接违反全局约束「huguan 不获得产品/视频的编辑权」。
        本用例是那条误标的路障：谁把 :158 换成 CROSS_USER_ROLES，这条立刻变红。
        """
        hg, _ = _huguan(client, "_tt_prd_hg")
        _, u1 = _create_user(client, "_tt_prd_u1", role="user", platform="tt")
        db = database.get_db()
        db.execute("INSERT INTO tt_products(product_name, owner_id) VALUES('别人的产品',?)", (u1,))
        db.commit()
        db.close()
        resp = client.get("/api/tt/products/list?size=50", headers=hg)
        assert resp.status_code == 200
        names = {p["product_name"] for p in resp.get_json()["items"]}
        assert "别人的产品" not in names

    def test_huguan_cannot_edit_other_users_product(self, client):
        """回归守卫：`_check_product_owner` / `_check_product_view` 一字不动。

        与上一条成对——上一条守列表可见性（`:158`），本条守写接口归属闸门（`:1157`/`:1169`）。
        """
        hg, _ = _huguan(client, "_tt_prde_hg")
        _, u1 = _create_user(client, "_tt_prde_u1", role="user", platform="tt")
        db = database.get_db()
        db.execute("INSERT INTO tt_products(product_name, owner_id) VALUES('只读产品',?)", (u1,))
        db.commit()
        pid = db.execute("SELECT id FROM tt_products WHERE product_name='只读产品'").fetchone()["id"]
        db.close()
        resp = client.put(f"/api/tt/products/{pid}", json={"product_name": "越权改名"}, headers=hg)
        assert resp.status_code == 403
        resp = client.get(f"/api/tt/products/{pid}/detail", headers=hg)
        assert resp.status_code == 403

    def test_huguan_cannot_see_other_users_delisted_packages(self, client):
        """回归守卫：产品域**不**放行（掉包检测）。

        `tt_routes.py:569`（`delist_status`）与原计划表误标为「要改」的 `:158`（`list_products`）
        同因同源。本用例是那条误标的路障：谁把 :569 换成 CROSS_USER_ROLES，第二条断言立刻变红。

        第一条断言是反向对照——户管自己的掉包记录**必须**可见，否则「看不到别人的」可以靠
        「整个接口对户管返回空」蒙混过关，这条守卫就成了假绿。
        """
        hg, hg_id = _huguan(client, "_tt_dl_hg")
        _, u1 = _create_user(client, "_tt_dl_u1", role="user", platform="tt")
        db = database.get_db()
        db.execute("INSERT INTO tt_products(product_name, owner_id) VALUES('户管的产品',?)", (hg_id,))
        mine = db.execute("SELECT id FROM tt_products WHERE product_name='户管的产品'").fetchone()["id"]
        db.execute("INSERT INTO tt_products(product_name, owner_id) VALUES('别人的产品',?)", (u1,))
        theirs = db.execute("SELECT id FROM tt_products WHERE product_name='别人的产品'").fetchone()["id"]
        for pid, pkg_name in ((mine, "户管的包"), (theirs, "别人的包")):
            db.execute("INSERT INTO tt_packages(product_id, package_name) VALUES(?,?)", (pid, pkg_name))
            pkid = db.execute("SELECT id FROM tt_packages WHERE package_name=?", (pkg_name,)).fetchone()["id"]
            db.execute("INSERT INTO tt_delist_checks(package_id, is_delisted) VALUES(?,1)", (pkid,))
        db.commit()
        db.close()
        resp = client.get("/api/tt/products/delist-status", headers=hg)
        assert resp.status_code == 200
        names = {p["product_name"] for p in resp.get_json()["delisted_packages"]}
        assert "户管的产品" in names       # 反向对照：接口对户管确实有效
        assert "别人的产品" not in names   # 产品域不放行


def _mk_fb_bm(db, owner_id, bm_code, name="测试BM"):
    db.execute("INSERT INTO fb_bms(name, bm_id, owner_id) VALUES(?,?,?)", (name, bm_code, owner_id))
    db.commit()


def _mk_fb_account(db, owner_id, account_id, name="FB账户"):
    db.execute("INSERT INTO fb_accounts(name, account_id, owner_id) VALUES(?,?,?)",
               (name, account_id, owner_id))
    db.commit()


class TestFbCrossUser:
    def _setup(self, client):
        hg, _ = _huguan(client, "_fb_cs_hg")
        _, u1 = _create_user(client, "_fb_cs_u1", role="user", platform="fb")
        _, u2 = _create_user(client, "_fb_cs_u2", role="user", platform="fb")
        db = database.get_db()
        _mk_fb_bm(db, u1, "BM-1", "U1的BM")
        _mk_fb_bm(db, u2, "BM-2", "U2的BM")
        _mk_fb_account(db, u1, "FB-AC-1")
        _mk_fb_account(db, u2, "FB-AC-2")
        db.close()
        return hg, u1, u2

    def _mk_pixel_bms(self, u1, u2):
        """给两个用户各造一条像素 BM（`_setup` 只造 `fb_bms`）。

        让 `/api/fb/bms/unified` 的 UNION **两半边**都有数据 —— 只覆盖 `fb_bms` 半边的话，
        第二半边漏加条件或参数错位都不会变红。
        """
        db = database.get_db()
        db.execute("INSERT INTO fb_pixel_bms(name, bm_id, owner_id) VALUES('U1的像素BM','PBM-U1',?)", (u1,))
        db.execute("INSERT INTO fb_pixel_bms(name, bm_id, owner_id) VALUES('U2的像素BM','PBM-U2',?)", (u2,))
        db.commit()
        db.close()

    def test_huguan_sees_all_bms(self, client):
        hg, _, _ = self._setup(client)
        resp = client.get("/api/fb/bms/list?size=50", headers=hg)
        assert resp.status_code == 200
        assert {b["bm_id"] for b in resp.get_json()["items"]} == {"BM-1", "BM-2"}

    def test_huguan_filters_bms_by_owner(self, client):
        hg, u1, _ = self._setup(client)
        resp = client.get(f"/api/fb/bms/list?size=50&owner_id={u1}", headers=hg)
        assert {b["bm_id"] for b in resp.get_json()["items"]} == {"BM-1"}

    def test_huguan_sees_other_users_pixel_bms(self, client):
        """`:771`（`/api/fb/pixel-bms/list`）—— 本任务五个改动站点中唯一此前全库零覆盖的一个。

        审查员变异证据：把该处的 `cross_user = role in CROSS_USER_ROLES` 改成 `cross_user = False`
        （户管静默退化为只看自己），83 条相关测试仍全绿。本用例即补那个豁口。
        """
        hg, _, u2 = self._setup(client)
        db = database.get_db()
        db.execute("INSERT INTO fb_pixel_bms(name, bm_id, owner_id) VALUES('U2的像素BM','PBM-2',?)", (u2,))
        db.commit()
        db.close()
        resp = client.get("/api/fb/pixel-bms/list?size=50", headers=hg)
        assert resp.status_code == 200
        assert {b["bm_id"] for b in resp.get_json()["items"]} == {"PBM-2"}

    def test_huguan_filters_pixel_bms_by_owner(self, client):
        """`:771` 的 `owner_id` 收窄分支 —— 与上一条互补（上一条只测「看全部」）。"""
        hg, u1, u2 = self._setup(client)
        db = database.get_db()
        db.execute("INSERT INTO fb_pixel_bms(name, bm_id, owner_id) VALUES('U1的像素BM','PBM-A',?)", (u1,))
        db.execute("INSERT INTO fb_pixel_bms(name, bm_id, owner_id) VALUES('U2的像素BM','PBM-B',?)", (u2,))
        db.commit()
        db.close()
        resp = client.get(f"/api/fb/pixel-bms/list?size=50&owner_id={u1}", headers=hg)
        assert resp.status_code == 200
        assert {b["bm_id"] for b in resp.get_json()["items"]} == {"PBM-A"}

    def test_huguan_sees_all_accounts(self, client):
        hg, _, _ = self._setup(client)
        resp = client.get("/api/fb/accounts/list?size=50", headers=hg)
        assert {a["account_id"] for a in resp.get_json()["items"]} == {"FB-AC-1", "FB-AC-2"}

    def test_huguan_filters_accounts_by_owner(self, client):
        hg, _, u2 = self._setup(client)
        resp = client.get(f"/api/fb/accounts/list?size=50&owner_id={u2}", headers=hg)
        assert {a["account_id"] for a in resp.get_json()["items"]} == {"FB-AC-2"}

    def test_regular_fb_user_ignores_owner_id(self, client):
        """回归：普通 FB 用户传 owner_id 不能越权。"""
        _, u1, _ = self._setup(client)
        other, _ = _create_user(client, "_fb_cs_u3", role="user", platform="fb")
        resp = client.get(f"/api/fb/accounts/list?size=50&owner_id={u1}", headers=other)
        assert resp.get_json()["items"] == []

    def test_huguan_sees_all_bms_unified_both_halves(self, client):
        """`:72`（`/api/fb/bms/unified`）是 UNION 两表，户管在**两半边**都必须放行。

        注意本用例**不带 `owner_id`**，故 `base_params` 为空，`base_params * 2` 退化为恒等操作 ——
        那一层耦合由下一条 `test_bms_unified_owner_filter_binds_both_halves` 负责，两条缺一不可。
        """
        hg, u1, u2 = self._setup(client)
        self._mk_pixel_bms(u1, u2)
        resp = client.get("/api/fb/bms/unified?size=50", headers=hg)
        assert resp.status_code == 200
        bm_ids = {b["bm_id"] for b in resp.get_json()["items"]}
        assert bm_ids == {"BM-1", "BM-2", "PBM-U1", "PBM-U2"}

    def test_bms_unified_owner_filter_binds_both_halves(self, client):
        """UNION 两半边的参数复制（`wrapped_params = base_params * 2`）。

        审查员变异证据：把 `py/routes/fb_routes.py:107` 的 `base_params * 2` 改成 `base_params`
        时套件全绿，而真实请求 `?owner_id=` 会抛 `sqlite3.ProgrammingError: Incorrect number of bindings`
        → HTTP 500。本用例通过传入 `owner_id` 让 `base_params` **非空**，从而锁住这个耦合：
        两半边各自拿到自己的那份参数，且各自收窄到该 owner。
        """
        hg, u1, u2 = self._setup(client)
        self._mk_pixel_bms(u1, u2)
        resp = client.get(f"/api/fb/bms/unified?size=50&owner_id={u1}", headers=hg)
        assert resp.status_code == 200
        assert {b["bm_id"] for b in resp.get_json()["items"]} == {"BM-1", "PBM-U1"}

    def test_huguan_sees_other_users_deleted_accounts(self, client):
        """`:387`（`/api/fb/accounts/deleted`）的账户回收站。

        断言用集合**相等**：既是「看得到别人回收站」的正向证明，也顺带守住
        「未删除的账户不得出现在回收站」这条既有语义（`_setup` 造的 FB-AC-1/2 都没删）。
        """
        hg, _, u2 = self._setup(client)
        db = database.get_db()
        db.execute("INSERT INTO fb_accounts(name, account_id, owner_id, deleted_at) "
                   "VALUES('U2的回收站账户','FB-DEL-2',?, datetime('now','localtime'))", (u2,))
        db.commit()
        db.close()
        resp = client.get("/api/fb/accounts/deleted?size=50", headers=hg)
        assert resp.status_code == 200
        assert {a["account_id"] for a in resp.get_json()["items"]} == {"FB-DEL-2"}

    def test_huguan_filters_deleted_accounts_by_owner(self, client):
        """`:411`（`/api/fb/accounts/deleted`）的 `owner_id` 收窄分支 —— 与上一条互补。"""
        hg, u1, u2 = self._setup(client)
        db = database.get_db()
        db.execute("INSERT INTO fb_accounts(name, account_id, owner_id, deleted_at) "
                   "VALUES('U1的回收站账户','FB-DEL-1',?, datetime('now','localtime'))", (u1,))
        db.execute("INSERT INTO fb_accounts(name, account_id, owner_id, deleted_at) "
                   "VALUES('U2的回收站账户','FB-DEL-2',?, datetime('now','localtime'))", (u2,))
        db.commit()
        db.close()
        resp = client.get(f"/api/fb/accounts/deleted?size=50&owner_id={u1}", headers=hg)
        assert resp.status_code == 200
        assert {a["account_id"] for a in resp.get_json()["items"]} == {"FB-DEL-1"}

    def test_huguan_cannot_see_other_users_fb_products(self, client):
        """回归守卫：产品域**不**放行（`fb_routes.py:471`）。

        `:471` 是 `elif role not in ('developer','admin')`，FB 产品列表按 **runner 归属**过滤
        （不是 owner）。全局约束「huguan 不获得产品/视频的编辑权」要求它保持原样 ——
        本用例是那条约束的路障：谁把 `:471` 换成 `CROSS_USER_ROLES`，断言立刻变红。
        与 Task 8 为 `:158`/`:569` 补守卫同因同源。
        """
        hg, _, u2 = self._setup(client)
        db = database.get_db()
        hg_id = db.execute("SELECT id FROM users WHERE username='_fb_cs_hg'").fetchone()["id"]
        # 正向对照：户管**在跑**的产品必须在结果里，否则「看不到别人的」可以靠
        # 「接口恒返回空」蒙混过关，这条守卫就成了假绿
        db.execute("INSERT INTO fb_products(product_name, owner_id) VALUES('户管在跑的产品',?)", (u2,))
        db.commit()
        mine = db.execute("SELECT id FROM fb_products WHERE product_name='户管在跑的产品'").fetchone()["id"]
        db.execute("INSERT INTO fb_product_runners(product_id, user_id) VALUES(?,?)", (mine, hg_id))
        # 负向目标：u2 拥有并在跑的产品不得出现
        db.execute("INSERT INTO fb_products(product_name, owner_id) VALUES('别人的FB产品',?)", (u2,))
        db.commit()
        pid = db.execute("SELECT id FROM fb_products WHERE product_name='别人的FB产品'").fetchone()["id"]
        db.execute("INSERT INTO fb_product_runners(product_id, user_id) VALUES(?,?)", (pid, u2))
        db.commit()
        db.close()
        resp = client.get("/api/fb/products/list?size=50", headers=hg)
        assert resp.status_code == 200
        names = {p["product_name"] for p in resp.get_json()["items"]}
        assert "户管在跑的产品" in names   # 正向对照：接口对户管确实有效
        assert "别人的FB产品" not in names  # 产品域不放行

    # ------------------------------------------------------------------
    # D1：`else` 分支（非跨用户角色只看自己）—— 四个此前无守卫的站点
    # ------------------------------------------------------------------

    def test_regular_fb_user_sees_only_own_bms(self, client):
        """`else` 分支（非跨用户角色只看自己）—— `/api/fb/bms/list`。

        审查员变异证据：把 `py/routes/fb_routes.py:37-39` 的 `else:` 分支改成 `pass`
        （普通用户于是能看到**全部** BM），全量 333 条测试仍全绿 —— 本用例即那个豁口。
        """
        self._setup(client)
        me, me_id = _create_user(client, "_fb_cs_ru1", role="user", platform="fb")
        db = database.get_db()
        db.execute("INSERT INTO fb_bms(name, bm_id, owner_id) VALUES('我的BM','BM-MINE',?)", (me_id,))
        db.commit()
        db.close()
        resp = client.get("/api/fb/bms/list?size=50", headers=me)
        assert resp.status_code == 200
        assert {b["bm_id"] for b in resp.get_json()["items"]} == {"BM-MINE"}

    def test_regular_fb_user_sees_only_own_bms_unified(self, client):
        """`else` 分支 —— `/api/fb/bms/unified`（UNION 两半边都要各自加 uid 条件）。"""
        self._setup(client)
        me, me_id = _create_user(client, "_fb_cs_ru2", role="user", platform="fb")
        db = database.get_db()
        db.execute("INSERT INTO fb_bms(name, bm_id, owner_id) VALUES('我的BM','BM-MINE',?)", (me_id,))
        db.execute("INSERT INTO fb_pixel_bms(name, bm_id, owner_id) VALUES('我的像素BM','PBM-MINE',?)", (me_id,))
        db.commit()
        db.close()
        resp = client.get("/api/fb/bms/unified?size=50", headers=me)
        assert resp.status_code == 200
        assert {b["bm_id"] for b in resp.get_json()["items"]} == {"BM-MINE", "PBM-MINE"}

    def test_regular_fb_user_sees_only_own_deleted_accounts(self, client):
        """`else` 分支 —— `/api/fb/accounts/deleted`（回收站）。

        **负向对照是必需的**：`_setup` 造的 FB-AC-1/2 都没删，若只插「我的一条」，
        则 `else:` 被改成 `pass`（丢掉 owner 条件）时结果依然是 `{FB-DEL-MINE}` ——
        断言集合相等却恒真。实测变异 3 原样通过即此故。故额外插入 u1 的一条**已删除**账户
        作为必须被挡住的对照行。
        """
        _, u1, _ = self._setup(client)
        me, me_id = _create_user(client, "_fb_cs_ru3", role="user", platform="fb")
        db = database.get_db()
        db.execute("INSERT INTO fb_accounts(name, account_id, owner_id, deleted_at) "
                   "VALUES('我的回收站账户','FB-DEL-MINE',?, datetime('now','localtime'))", (me_id,))
        # 负向对照：别人的回收站账户不得出现
        db.execute("INSERT INTO fb_accounts(name, account_id, owner_id, deleted_at) "
                   "VALUES('别人的回收站账户','FB-DEL-THEIRS',?, datetime('now','localtime'))", (u1,))
        db.commit()
        db.close()
        resp = client.get("/api/fb/accounts/deleted?size=50", headers=me)
        assert resp.status_code == 200
        assert {a["account_id"] for a in resp.get_json()["items"]} == {"FB-DEL-MINE"}

    def test_regular_fb_user_sees_only_own_pixel_bms(self, client):
        """`else` 分支 —— `/api/fb/pixel-bms/list`。

        **负向对照是必需的**：`_setup` 不造任何 `fb_pixel_bms`，若只插「我的一条」，
        则 `else:` 被改成 `pass` 时结果依然是 `{PBM-MINE}` —— 断言恒真（实测变异 4 原样通过）。
        故额外插入 u1 的一条像素 BM 作为必须被挡住的对照行。
        """
        _, u1, _ = self._setup(client)
        me, me_id = _create_user(client, "_fb_cs_ru4", role="user", platform="fb")
        db = database.get_db()
        db.execute("INSERT INTO fb_pixel_bms(name, bm_id, owner_id) VALUES('我的像素BM','PBM-MINE',?)", (me_id,))
        # 负向对照：别人的像素 BM 不得出现
        db.execute("INSERT INTO fb_pixel_bms(name, bm_id, owner_id) VALUES('别人的像素BM','PBM-THEIRS',?)", (u1,))
        db.commit()
        db.close()
        resp = client.get("/api/fb/pixel-bms/list?size=50", headers=me)
        assert resp.status_code == 200
        assert {b["bm_id"] for b in resp.get_json()["items"]} == {"PBM-MINE"}

    # ------------------------------------------------------------------
    # D2：developer / admin 在 `/api/fb/bms/list` 的语义（代表性站点）
    # ------------------------------------------------------------------

    def test_developer_sees_all_bms_without_owner_id(self, client):
        """纯增量守卫：developer 不传 owner_id 时看全部 —— 本任务改前改后都必须为真。

        对应 `py/routes/fb_routes.py:33` 新增的 `if cross_user:` 闸门。审查员变异证据：
        把该行改成 `if cross_user and role == "huguan":` 时全量 333 条测试仍全绿 ——
        即本任务新写的这段代码让 developer 静默退化为「只看自己」也没人报警。
        """
        self._setup(client)
        dev, _ = _create_user(client, "_fb_cs_dev", role="developer", platform="gg")
        resp = client.get("/api/fb/bms/list?size=50", headers=dev)
        assert resp.status_code == 200
        assert {b["bm_id"] for b in resp.get_json()["items"]} == {"BM-1", "BM-2"}

    def test_developer_narrows_when_owner_id_given(self, client):
        """developer 带 owner_id 时**收窄** —— 这是本任务有意引入的语义变化。

        改前 developer 不受 `owner_id` 影响（返回全部）；改后收窄到指定 owner。
        该变化已由设计文档放行（developer 获得跨用户账户可见性），本用例把新语义钉住，
        避免日后被当成回归误修回「忽略 owner_id」。
        """
        _, u1, _ = self._setup(client)
        dev, _ = _create_user(client, "_fb_cs_dev2", role="developer", platform="gg")
        resp = client.get(f"/api/fb/bms/list?size=50&owner_id={u1}", headers=dev)
        assert resp.status_code == 200
        assert {b["bm_id"] for b in resp.get_json()["items"]} == {"BM-1"}

    def test_admin_sees_all_bms_without_owner_id(self, client):
        """纯增量守卫：admin 不传 owner_id 时看全部。

        注意 admin **不跨平台**（`PLATFORM_SWITCH_ROLES` 不含 admin），故 platform 必须为 'fb'。
        与 `test_developer_sees_all_bms_without_owner_id` 成对：变异 `role == "huguan"` 会同时
        静默打挂两者，只测一侧则另一侧仍无网。
        """
        self._setup(client)
        adm, _ = _create_user(client, "_fb_cs_adm", role="admin", platform="fb")
        resp = client.get("/api/fb/bms/list?size=50", headers=adm)
        assert resp.status_code == 200
        assert {b["bm_id"] for b in resp.get_json()["items"]} == {"BM-1", "BM-2"}

    def test_admin_narrows_when_owner_id_given(self, client):
        """admin 带 owner_id 时收窄 —— 与 developer 侧同一语义变化。"""
        _, u1, _ = self._setup(client)
        adm, _ = _create_user(client, "_fb_cs_adm2", role="admin", platform="fb")
        resp = client.get(f"/api/fb/bms/list?size=50&owner_id={u1}", headers=adm)
        assert resp.status_code == 200
        assert {b["bm_id"] for b in resp.get_json()["items"]} == {"BM-1"}


class TestHuguanGlobalOptions:
    """户管可改名/删除平台级下拉选项（代理名 / 账户状态 / MCC 等级 / 商务人员）。

    本任务改 `py/main.py` 里 8 处 `is_dev` 的定义（4 类选项 × rename/delete），
    令其等于 `GLOBAL_OPTION_ROLES`。**四个 `*_create` 端点本来就没有角色闸门**
    （任何登录用户都能建，只是按 owner/platform 隔离），故不在本任务范围，
    也不要为它们写「户管能建」的用例 —— 那种断言改前改后都成立，是无法失败的假绿。
    """

    def test_huguan_renames_other_users_agent(self, client):
        """`:5777`（`agents_rename`）。原计划表把这组误写成 create，实为 rename。"""
        hg, _ = _huguan(client, "_opt_hg")
        _, u1 = _create_user(client, "_opt_u1", role="user", platform="gg")
        db = database.get_db()
        db.execute("INSERT INTO agents(name, owner_id) VALUES('u1的代理',?)", (u1,))
        db.commit()
        aid = db.execute("SELECT id FROM agents WHERE name='u1的代理'").fetchone()["id"]
        db.close()
        resp = client.put(f"/api/agents/{aid}?platform=gg", json={"name": "户管改名后"}, headers=hg)
        assert resp.status_code == 200
        db = database.get_db()
        row = db.execute("SELECT name FROM agents WHERE id=?", (aid,)).fetchone()
        db.close()
        assert row["name"] == "户管改名后"

    def test_huguan_deletes_other_users_agent(self, client):
        """`:5817`（`agents_delete`）。读回确认真的删了，而不是「返回 200 但没删」。"""
        hg, _ = _huguan(client, "_opt_hg")
        _, u1 = _create_user(client, "_opt_u1b", role="user", platform="gg")
        db = database.get_db()
        db.execute("INSERT INTO agents(name, owner_id) VALUES('u1的待删代理',?)", (u1,))
        db.commit()
        aid = db.execute("SELECT id FROM agents WHERE name='u1的待删代理'").fetchone()["id"]
        db.close()
        resp = client.delete(f"/api/agents/{aid}?platform=gg", headers=hg)
        assert resp.status_code == 200
        db = database.get_db()
        gone = db.execute("SELECT id FROM agents WHERE id=?", (aid,)).fetchone()
        db.close()
        assert gone is None

    def test_huguan_renames_other_users_status(self, client):
        """`:5935`（`statuses_rename`）。"""
        hg, _ = _huguan(client, "_opt_hg2")
        _, u1 = _create_user(client, "_opt_u2", role="user", platform="gg")
        db = database.get_db()
        db.execute("INSERT INTO account_statuses(name, platform, owner_id) "
                   "VALUES('u1的状态','gg',?)", (u1,))
        db.commit()
        sid = db.execute("SELECT id FROM account_statuses WHERE name='u1的状态'").fetchone()["id"]
        db.close()
        resp = client.put(f"/api/statuses/{sid}?platform=gg", json={"name": "户管改的状态"}, headers=hg)
        assert resp.status_code == 200
        db = database.get_db()
        row = db.execute("SELECT name FROM account_statuses WHERE id=?", (sid,)).fetchone()
        db.close()
        assert row["name"] == "户管改的状态"

    def test_huguan_deletes_other_users_status(self, client):
        """`:5964`（`statuses_delete`）。"""
        hg, _ = _huguan(client, "_opt_hg2b")
        _, u1 = _create_user(client, "_opt_u2b", role="user", platform="gg")
        db = database.get_db()
        db.execute("INSERT INTO account_statuses(name, platform, owner_id) "
                   "VALUES('u1的待删状态','gg',?)", (u1,))
        db.commit()
        sid = db.execute("SELECT id FROM account_statuses WHERE name='u1的待删状态'").fetchone()["id"]
        db.close()
        resp = client.delete(f"/api/statuses/{sid}?platform=gg", headers=hg)
        assert resp.status_code == 200
        db = database.get_db()
        gone = db.execute("SELECT id FROM account_statuses WHERE id=?", (sid,)).fetchone()
        db.close()
        assert gone is None

    def test_huguan_renames_other_users_mcc_level(self, client):
        """`:6036`（`mcc_levels_rename`）。"""
        hg, _ = _huguan(client, "_opt_hg3")
        _, u1 = _create_user(client, "_opt_u3", role="user", platform="gg")
        db = database.get_db()
        db.execute("INSERT INTO mcc_levels(name, owner_id) VALUES('u1的等级',?)", (u1,))
        db.commit()
        lid = db.execute("SELECT id FROM mcc_levels WHERE name='u1的等级'").fetchone()["id"]
        db.close()
        resp = client.put(f"/api/mcc-levels/{lid}?platform=gg", json={"name": "户管改的等级"}, headers=hg)
        assert resp.status_code == 200
        db = database.get_db()
        row = db.execute("SELECT name FROM mcc_levels WHERE id=?", (lid,)).fetchone()
        db.close()
        assert row["name"] == "户管改的等级"

    def test_huguan_deletes_other_users_mcc_level(self, client):
        """`:6063`（`mcc_levels_delete`）。"""
        hg, _ = _huguan(client, "_opt_hg3b")
        _, u1 = _create_user(client, "_opt_u3b", role="user", platform="gg")
        db = database.get_db()
        db.execute("INSERT INTO mcc_levels(name, owner_id) VALUES('u1的待删等级',?)", (u1,))
        db.commit()
        lid = db.execute("SELECT id FROM mcc_levels WHERE name='u1的待删等级'").fetchone()["id"]
        db.close()
        resp = client.delete(f"/api/mcc-levels/{lid}?platform=gg", headers=hg)
        assert resp.status_code == 200
        db = database.get_db()
        gone = db.execute("SELECT id FROM mcc_levels WHERE id=?", (lid,)).fetchone()
        db.close()
        assert gone is None

    def test_huguan_renames_other_users_sales_person(self, client):
        """`:6131`（`sales_persons_rename`）。

        这一处最容易漏：同函数的 `:6142` 还有一个 `is_dev` 的**引用**（重名检查的三元表达式），
        它与本处定义必须一起生效 —— 只改定义、不动 `:6142`。
        """
        hg, _ = _huguan(client, "_opt_hg4")
        _, u1 = _create_user(client, "_opt_u4", role="user", platform="gg")
        db = database.get_db()
        db.execute("INSERT INTO sales_persons(name, platform, owner_id) "
                   "VALUES('u1的商务','gg',?)", (u1,))
        db.commit()
        sid = db.execute("SELECT id FROM sales_persons WHERE name='u1的商务'").fetchone()["id"]
        db.close()
        resp = client.put(f"/api/sales-persons/{sid}?platform=gg", json={"name": "户管改的商务"}, headers=hg)
        assert resp.status_code == 200
        db = database.get_db()
        row = db.execute("SELECT name FROM sales_persons WHERE id=?", (sid,)).fetchone()
        db.close()
        assert row["name"] == "户管改的商务"

    def test_huguan_deletes_other_users_sales_person(self, client):
        """`:6161`（`sales_persons_delete`）。"""
        hg, _ = _huguan(client, "_opt_hg4b")
        _, u1 = _create_user(client, "_opt_u4b", role="user", platform="gg")
        db = database.get_db()
        db.execute("INSERT INTO sales_persons(name, platform, owner_id) "
                   "VALUES('u1的待删商务','gg',?)", (u1,))
        db.commit()
        sid = db.execute("SELECT id FROM sales_persons WHERE name='u1的待删商务'").fetchone()["id"]
        db.close()
        resp = client.delete(f"/api/sales-persons/{sid}?platform=gg", headers=hg)
        assert resp.status_code == 200
        db = database.get_db()
        gone = db.execute("SELECT id FROM sales_persons WHERE id=?", (sid,)).fetchone()
        db.close()
        assert gone is None

    def test_regular_user_cannot_rename_other_users_agent(self, client):
        """回归守卫：普通用户改不动他人代理名 —— 改前改后都必须为真（纯增量）。

        **含正向对照**：同一接口对 `me` *自己*的代理必须 200。没有这条对照，
        上面的 404 可能来自「接口恒 404」，断言就是假绿。
        """
        _, u1 = _create_user(client, "_opt_u5", role="user", platform="gg")
        me, me_id = _create_user(client, "_opt_u6", role="user", platform="gg")
        db = database.get_db()
        db.execute("INSERT INTO agents(name, owner_id) VALUES('u1的代理',?)", (u1,))
        db.execute("INSERT INTO agents(name, owner_id) VALUES('我自己的代理',?)", (me_id,))
        db.commit()
        theirs = db.execute("SELECT id FROM agents WHERE name='u1的代理'").fetchone()["id"]
        mine = db.execute("SELECT id FROM agents WHERE name='我自己的代理'").fetchone()["id"]
        db.close()
        assert client.put(f"/api/agents/{theirs}?platform=gg",
                          json={"name": "越权改名"}, headers=me).status_code == 404
        assert client.put(f"/api/agents/{mine}?platform=gg",
                          json={"name": "我改名"}, headers=me).status_code == 200

    def test_regular_user_cannot_delete_other_users_status(self, client):
        """回归守卫：普通用户删不掉他人的账户状态（`:5964`）。含正向对照。"""
        _, u1 = _create_user(client, "_opt_u7", role="user", platform="gg")
        me, me_id = _create_user(client, "_opt_u8", role="user", platform="gg")
        db = database.get_db()
        db.execute("INSERT INTO account_statuses(name, platform, owner_id) "
                   "VALUES('u1的状态','gg',?)", (u1,))
        db.execute("INSERT INTO account_statuses(name, platform, owner_id) "
                   "VALUES('我的状态','gg',?)", (me_id,))
        db.commit()
        theirs = db.execute("SELECT id FROM account_statuses WHERE name='u1的状态'").fetchone()["id"]
        mine = db.execute("SELECT id FROM account_statuses WHERE name='我的状态'").fetchone()["id"]
        db.close()
        assert client.delete(f"/api/statuses/{theirs}?platform=gg", headers=me).status_code == 404
        assert client.delete(f"/api/statuses/{mine}?platform=gg", headers=me).status_code == 200


class TestHuguanUserListCrossPlatform:
    """户管的用户列表跨平台（D9 修订）。

    缺口源：`py/auth.py:79-82` 对非 developer 调用者强制 `platform = 自己平台` 并忽略传入的
    `platform` 参数 ⇒ 户管在 FB 建出的户管，切到 GG 后看不见。本类既是修复的正向证明，
    也是「其余角色平台隔离不得被放宽」的路障（第 3/4/5 条）。
    """

    def _setup(self, client):
        """造出：户管自己(gg) + 其名下 gg/fb 两个户管 + 两个**必须被排除**的对照行。"""
        hg, hg_id = _create_user(client, "_ulc_hg", role="huguan", platform="gg")
        _create_user(client, "_ulc_h_gg", role="huguan", platform="gg", created_by=hg_id)
        _create_user(client, "_ulc_h_fb", role="huguan", platform="fb", created_by=hg_id)
        # 对照行 1：普通 user（role_filter=huguan 必须排除它）
        _create_user(client, "_ulc_plain_fb", role="user", platform="fb")
        # 对照行 2：developer（list_users 对非 developer 调用者的 role != 'developer' 必须排除它）
        _create_user(client, "_ulc_dev", role="developer", platform="gg")
        return hg, hg_id

    def test_huguan_sees_huguans_across_all_platforms(self, client):
        """集合**相等**：既证明看得到 fb 的户管，也证明两个对照行被排除。"""
        hg, _ = self._setup(client)
        resp = client.get("/api/admin/users?page_size=50", headers=hg)
        assert resp.status_code == 200
        names = {u["username"] for u in resp.get_json()["users"]}
        assert names == {"_ulc_hg", "_ulc_h_gg", "_ulc_h_fb"}

    def test_huguan_ignores_platform_param(self, client):
        """`?platform=` 对户管必须被忽略——否则前端注入的 `?platform=` 会把跨平台收窄回单平台。"""
        hg, _ = self._setup(client)
        resp = client.get("/api/admin/users?page_size=50&platform=fb", headers=hg)
        names = {u["username"] for u in resp.get_json()["users"]}
        assert names == {"_ulc_hg", "_ulc_h_gg", "_ulc_h_fb"}

    def test_admin_still_platform_isolated(self, client):
        """回归路障：admin 不得被 `is_huguan` 分支吞掉（`test_user_platform_isolation.py:43` 同因同源）。"""
        adm, _ = _create_user(client, "_ulc_adm", role="admin", platform="tt")
        _create_user(client, "_ulc_tt_user", role="user", platform="tt")
        _create_user(client, "_ulc_gg_user", role="user", platform="gg")
        resp = client.get("/api/admin/users?platform=gg", headers=adm)
        assert {u["platform"] for u in resp.get_json()["users"]} == {"tt"}

    def test_regular_user_still_platform_isolated(self, client):
        """回归路障：普通用户仍只看自己平台（直接调函数，因为 user 无权访问 /api/admin/users）。"""
        from auth import list_users
        _, ugg = _create_user(client, "_ulc_ru_gg", role="user", platform="gg")
        _create_user(client, "_ulc_ru_tt", role="user", platform="tt")
        res = list_users(current_user_id=ugg)
        assert {u["platform"] for u in res["users"]} == {"gg"}

    def test_developer_still_sees_all_platforms(self, client):
        """回归路障：developer 行为不变（本任务不得改动 `is_dev` 分支）。"""
        from auth import list_users
        _, dev = _create_user(client, "_ulc_dev2", role="developer", platform="gg")
        _create_user(client, "_ulc_d_gg", role="user", platform="gg")
        _create_user(client, "_ulc_d_tt", role="user", platform="tt")
        res = list_users(current_user_id=dev)
        assert {"gg", "tt"} <= {u["platform"] for u in res["users"]}


class TestHuguanBlockedFromProductDomain:
    """户管可跨平台，但不得写产品 / 包 / 素材（设计文档 §3.9）。"""

    def _fb_product_by_developer(self, client):
        """借开发者身份造一个 FB 产品，供户管越权尝试。"""
        dev, _ = _create_user(client, "_hg_pd_dev", role="developer", platform="fb")
        resp = client.post("/api/fb/products/create", json={"product_name": "户管越权靶子"},
                           headers=dev)
        assert resp.status_code == 200, resp.get_json()
        return dev, resp.get_json()["id"]

    def test_huguan_cannot_create_fb_product(self, client):
        hg, _ = _huguan(client, "_hg_pd_fb_create")
        resp = client.post("/api/fb/products/create", json={"product_name": "越权"},
                           headers=hg)
        assert resp.status_code == 403

    def test_huguan_cannot_update_fb_product(self, client):
        _, pid = self._fb_product_by_developer(client)
        hg, _ = _huguan(client, "_hg_pd_fb_update")
        resp = client.put(f"/api/fb/products/{pid}", json={"product_name": "被篡改"},
                          headers=hg)
        assert resp.status_code == 403

    def test_huguan_cannot_delete_fb_product(self, client):
        _, pid = self._fb_product_by_developer(client)
        hg, _ = _huguan(client, "_hg_pd_fb_delete")
        resp = client.delete(f"/api/fb/products/{pid}", headers=hg)
        assert resp.status_code == 403

    def test_huguan_cannot_create_tt_product(self, client):
        hg, _ = _huguan(client, "_hg_pd_tt_create")
        resp = client.post("/api/tt/products/create", json={"product_name": "越权"},
                           headers=hg)
        assert resp.status_code == 403

    def test_huguan_cannot_import_tt_products(self, client):
        """import-text 只挂 @tt_required，是易漏的写入面。"""
        hg, _ = _huguan(client, "_hg_pd_tt_import")
        resp = client.post("/api/tt/products/import-text", json={"text": "x"},
                           headers=hg)
        assert resp.status_code == 403

    def test_huguan_can_still_write_account_domain(self, client):
        """回归：收口不得误伤账户域——户管仍可建 BC。"""
        hg, _ = _huguan(client, "_hg_pd_bc", platform="tt")
        resp = client.post("/api/tt/bcs/create",
                           json={"name": "户管建的BC", "bc_id": "123456789"}, headers=hg)
        assert resp.status_code == 200

    def test_developer_can_still_write_products(self, client):
        """回归：developer 的产品写权限不受影响。"""
        dev, _ = _create_user(client, "_hg_pd_dev2", role="developer", platform="gg")
        resp = client.post("/api/tt/products/create", json={"product_name": "开发者的产品"},
                           headers=dev)
        assert resp.status_code == 200


def _import_payload(client, headers, payload):
    """以 multipart 上传导出的 JSON 载荷到 /api/tt/data/import（写法照抄 test_tt_routes）。"""
    file_bytes = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    return client.post("/api/tt/data/import", headers=headers,
                       data={"file": (io.BytesIO(file_bytes), "export.json")},
                       content_type="multipart/form-data")


class TestHuguanBlockedFromDataImport:
    """@tt_write_required 会放行户管，导入载荷里的 products / packages 是残留写入通道。"""

    PRODUCT_PAYLOAD = {"data": {"products": [{"id": 1, "product_name": "导入产品"}]}}

    def test_huguan_cannot_import_products(self, client):
        """户管导入含产品的载荷 → 403，且产品绝不能落库。"""
        hg, hg_id = _huguan(client, "_hg_imp_products")
        resp = _import_payload(client, hg, self.PRODUCT_PAYLOAD)
        assert resp.status_code == 403
        assert resp.get_json()["error"] == "户管无产品/素材权限"
        db = database.get_db()
        row = db.execute("SELECT COUNT(*) FROM tt_products WHERE owner_id=?", (hg_id,)).fetchone()
        db.close()
        assert row[0] == 0

    def test_huguan_can_still_import_bcs(self, client):
        """对照行：不得把户管整体拒绝——BC + 商务人员仍可导入并落库。"""
        hg, hg_id = _huguan(client, "_hg_imp_bcs")
        payload = {"data": {
            "bcs": [{"id": 1, "bc_id": "123456789", "name": "导入BC"}],
            "sales_persons": [{"id": 1, "name": "导入商务"}],
        }}
        resp = _import_payload(client, hg, payload)
        assert resp.status_code == 200
        db = database.get_db()
        bc = db.execute("SELECT owner_id FROM tt_bcs WHERE bc_id=?", ("123456789",)).fetchone()
        sp = db.execute("SELECT owner_id FROM sales_persons WHERE name=?", ("导入商务",)).fetchone()
        db.close()
        assert bc is not None and bc["owner_id"] == hg_id
        assert sp is not None and sp["owner_id"] == hg_id

    def test_developer_can_still_import_products(self, client):
        """对照行：闸门只针对户管，developer 导入产品不受影响。"""
        dev, dev_id = _create_user(client, "_hg_imp_dev", role="developer", platform="gg")
        resp = _import_payload(client, dev, self.PRODUCT_PAYLOAD)
        assert resp.status_code == 200
        assert resp.get_json()["report"]["products"] == 1
        db = database.get_db()
        row = db.execute("SELECT COUNT(*) FROM tt_products WHERE owner_id=?", (dev_id,)).fetchone()
        db.close()
        assert row[0] == 1

    def test_tt_user_can_still_import_products(self, client):
        """纯增量对照：普通 TT 用户导入产品保持原状。"""
        headers, uid = _create_user(client, "_hg_imp_ttuser", role="user", platform="tt")
        resp = _import_payload(client, headers, self.PRODUCT_PAYLOAD)
        assert resp.status_code == 200
        assert resp.get_json()["report"]["products"] == 1
        db = database.get_db()
        row = db.execute("SELECT COUNT(*) FROM tt_products WHERE owner_id=?", (uid,)).fetchone()
        db.close()
        assert row[0] == 1


def _mk_fb_pixel_bm(db, owner_id, bm_id, name="像素BM"):
    """建一条像素BM（像素的归属由其父表 `fb_pixel_bms.owner_id` 决定），返回其 id。"""
    db.execute("INSERT INTO fb_pixel_bms(name, bm_id, owner_id) VALUES(?,?,?)", (name, bm_id, owner_id))
    db.commit()
    return db.execute("SELECT id FROM fb_pixel_bms WHERE bm_id=?", (bm_id,)).fetchone()["id"]


def _mk_fb_pixel(db, pixel_bm_id, pixel_id, name="像素"):
    """在指定像素BM下建一条像素（`fb_pixels.pixel_bm_id` 外键非空）。"""
    db.execute("INSERT INTO fb_pixels(pixel_bm_id, pixel_name, pixel_id) VALUES(?,?,?)",
               (pixel_bm_id, name, pixel_id))
    db.commit()


def _mk_tt_bc(db, owner_id, bc_id, name="BC"):
    db.execute("INSERT INTO tt_bcs(name, bc_id, owner_id) VALUES(?,?,?)", (name, bc_id, owner_id))
    db.commit()


class TestListOwnerFilterCrossUser:
    """Task 16b：`/api/fb/pixels/list` 与 `/api/tt/bcs/list` 补齐 `owner_id` 收窄。

    这两个端点是 Task 16 的漏网点 —— 前端「全部用户」下拉会发出 `?owner_id=N`，
    但后端此前完全不读该参数（FB 像素连普通用户的归属过滤都没有，TT BC 则只对
    非跨用户角色写死 `owner_id=uid`）。本类同时钉住纯增量约束：非跨用户角色
    即使显式传参也必须被忽略，其 SQL 条件与结果逐字不变。

    注意 `fb_pixels` 表没有 `owner_id` 列，像素归属看父表 `fb_pixel_bms.owner_id`。
    """

    def _setup_fb(self, client):
        hg, _ = _huguan(client, "_fp_hg")
        u1_headers, u1 = _create_user(client, "_fp_u1", role="user", platform="fb")
        _, u2 = _create_user(client, "_fp_u2", role="user", platform="fb")
        db = database.get_db()
        pbm1 = _mk_fb_pixel_bm(db, u1, "PBM-FP-1", "U1的像素BM")
        pbm2 = _mk_fb_pixel_bm(db, u2, "PBM-FP-2", "U2的像素BM")
        _mk_fb_pixel(db, pbm1, "PX-FP-1", "U1的像素")
        _mk_fb_pixel(db, pbm2, "PX-FP-2", "U2的像素")
        db.close()
        return hg, u1_headers, u1, u2

    def _setup_tt(self, client):
        hg, _ = _huguan(client, "_bc_hg")
        u1_headers, u1 = _create_user(client, "_bc_u1", role="user", platform="tt")
        _, u2 = _create_user(client, "_bc_u2", role="user", platform="tt")
        db = database.get_db()
        _mk_tt_bc(db, u1, "BC-FP-1", "U1的BC")
        _mk_tt_bc(db, u2, "BC-FP-2", "U2的BC")
        db.close()
        return hg, u1_headers, u1, u2

    # ---------------- FB 像素 ----------------

    def test_huguan_filters_fb_pixels_by_owner(self, client):
        """户管带 `?owner_id=<B的uid>` → 只返回 B 名下的像素。"""
        hg, _, _, u2 = self._setup_fb(client)
        resp = client.get(f"/api/fb/pixels/list?size=50&owner_id={u2}", headers=hg)
        assert resp.status_code == 200
        pixel_ids = {p["pixel_id"] for p in resp.get_json()["items"]}
        assert pixel_ids == {"PX-FP-2"}   # 只含 U2 名下像素（集合相等，非子集）
        assert pixel_ids                  # 防「空列表也算通过」

    def test_huguan_fb_pixels_contrast_without_owner(self, client):
        """对照行：同一户管**不带**参数时必须看到多于 1 个 owner 的像素，
        证明上一条的收窄来自参数本身，而不是数据里本来就只有一个 owner。"""
        hg, _, _, _ = self._setup_fb(client)
        resp = client.get("/api/fb/pixels/list?size=50", headers=hg)
        assert resp.status_code == 200
        db = database.get_db()
        owner_of = {r["id"]: r["owner_id"]
                    for r in db.execute("SELECT id, owner_id FROM fb_pixel_bms").fetchall()}
        db.close()
        owners = {owner_of[p["pixel_bm_id"]] for p in resp.get_json()["items"]}
        assert len(owners) > 1

    def test_fb_user_sees_same_rows_with_or_without_owner_param(self, client):
        """纯增量对照（关键）：普通 `fb` 用户传**别人的 uid** 必须被完全忽略。

        两次返回的 `pixel_id` 集合相等 —— 若实现漏了角色判断而对该参数无差别生效，
        带参那次会退化成只有 U2 的行，本用例立即变红。
        """
        _, u1_headers, _, u2 = self._setup_fb(client)
        without = client.get("/api/fb/pixels/list?size=50", headers=u1_headers).get_json()["items"]
        with_param = client.get(f"/api/fb/pixels/list?size=50&owner_id={u2}",
                                headers=u1_headers).get_json()["items"]
        ids_without = {p["pixel_id"] for p in without}
        ids_with = {p["pixel_id"] for p in with_param}
        assert ids_with == ids_without
        assert "PX-FP-1" in ids_without   # 非空：自己的像素必须在，防「两边都空也算相等」

    # ---------------- TT BC ----------------

    def test_huguan_filters_tt_bcs_by_owner(self, client):
        """户管带 `?owner_id=<B的uid>` → 只返回 B 名下的 BC。"""
        hg, _, _, u2 = self._setup_tt(client)
        resp = client.get(f"/api/tt/bcs/list?size=50&owner_id={u2}", headers=hg)
        assert resp.status_code == 200
        bc_ids = {b["bc_id"] for b in resp.get_json()["items"]}
        assert bc_ids == {"BC-FP-2"}
        assert bc_ids                     # 防「空列表也算通过」

    def test_huguan_tt_bcs_contrast_without_owner(self, client):
        """对照行：不带参数时户管能看到多于 1 个 owner 的 BC。"""
        hg, _, _, _ = self._setup_tt(client)
        resp = client.get("/api/tt/bcs/list?size=50", headers=hg)
        assert resp.status_code == 200
        owners = {b["owner_id"] for b in resp.get_json()["items"]}
        assert len(owners) > 1

    def test_tt_user_sees_same_rows_with_or_without_owner_param(self, client):
        """纯增量对照：普通 `tt` 用户传**别人的 uid** 时两次集合完全相等，且只含自己的 BC。"""
        _, u1_headers, _, u2 = self._setup_tt(client)
        without = {b["bc_id"] for b in
                   client.get("/api/tt/bcs/list?size=50", headers=u1_headers).get_json()["items"]}
        with_param = {b["bc_id"] for b in
                      client.get(f"/api/tt/bcs/list?size=50&owner_id={u2}",
                                 headers=u1_headers).get_json()["items"]}
        assert with_param == without
        assert without == {"BC-FP-1"}     # 非空且只含自己的 BC


class TestGgWriteOpsCrossUser:
    """GG 侧「硬编码 owner_id == 自己」的 8 处写校验对跨用户角色放行（Task 18）。"""

    def _fixture(self, client):
        hg, hg_id = _huguan(client, "_ggw_hg")
        _, u1 = _create_user(client, "_ggw_u1", role="user")
        db = database.get_db()
        _mk_mcc(db, u1, "MCC-W1", "别人的MCC")
        _mk_account(db, u1, "GG-W-1", "别人的账户")
        mcc_id = db.execute("SELECT id FROM mcc WHERE mcc_id='MCC-W1'").fetchone()["id"]
        acc_id = db.execute("SELECT id FROM accounts WHERE account_id='GG-W-1'").fetchone()["id"]
        db.close()
        return hg, u1, mcc_id, acc_id

    def test_huguan_can_update_others_mcc(self, client):
        hg, _, mcc_id, _ = self._fixture(client)
        resp = client.put(f"/api/mcc/{mcc_id}", json={"name": "改过的名字"}, headers=hg)
        assert resp.status_code == 200
        db = database.get_db()
        name = db.execute("SELECT name FROM mcc WHERE id=?", (mcc_id,)).fetchone()["name"]
        db.close()
        assert name == "改过的名字"

    def test_huguan_can_delete_others_mcc(self, client):
        hg, _, mcc_id, _ = self._fixture(client)
        assert client.delete(f"/api/mcc/{mcc_id}", headers=hg).status_code == 200

    def test_huguan_can_soft_delete_and_restore_others_account(self, client):
        hg, _, _, acc_id = self._fixture(client)
        assert client.delete(f"/api/accounts/{acc_id}", headers=hg).status_code == 200
        assert client.post(f"/api/accounts/{acc_id}/restore", headers=hg).status_code == 200

    def test_huguan_can_delete_others_mcc_history(self, client):
        """跨用户角色的 MCC 历史删除白名单（该接口原本只认 developer / admin）。"""
        hg, _, _, acc_id = self._fixture(client)
        db = database.get_db()
        db.execute("INSERT INTO account_mcc_history(account_id, old_mcc_id, new_mcc_id) VALUES(?,?,?)",
                   (acc_id, 1, 2))
        db.commit()
        hid = db.execute("SELECT id FROM account_mcc_history WHERE account_id=?", (acc_id,)).fetchone()["id"]
        db.close()
        resp = client.delete(f"/api/accounts/{acc_id}/mcc-history/{hid}", headers=hg)
        assert resp.status_code == 200
        assert resp.get_json()["deleted"] == 1

    def test_regular_user_still_blocked_from_others_mcc(self, client):
        """回归：普通用户改别人 MCC 仍是 403，且文案逐字节不变。"""
        _, _, mcc_id, _ = self._fixture(client)
        hdr, _ = _create_user(client, "_ggw_u2", role="user")
        resp = client.put(f"/api/mcc/{mcc_id}", json={"name": "越权"}, headers=hdr)
        assert resp.status_code == 403
        assert resp.get_json()["error"] == "只有创建者才能编辑此 MCC"

    def test_regular_user_still_blocked_from_others_account(self, client):
        """回归：普通用户删别人账户仍是 404，且账户**真的没被**软删除。"""
        _, _, _, acc_id = self._fixture(client)
        hdr, _ = _create_user(client, "_ggw_u3", role="user")
        assert client.delete(f"/api/accounts/{acc_id}", headers=hdr).status_code == 404
        db = database.get_db()
        deleted = db.execute("SELECT deleted_at FROM accounts WHERE id=?", (acc_id,)).fetchone()["deleted_at"]
        db.close()
        assert deleted is None

    def test_regular_user_still_blocked_from_others_mcc_history(self, client):
        """回归：普通用户删别人的 MCC 历史仍是 403。"""
        hdr, _ = _create_user(client, "_ggw_u4", role="user")
        _, _, _, acc_id = self._fixture(client)
        assert client.delete(f"/api/accounts/{acc_id}/mcc-history/1", headers=hdr).status_code == 403


# ==================== Task 20: GG 产品/视频/文案/素材域对户管收口 ====================

def _count_rows(table):
    """返回某表的行数（表名为本文件内的字面量，非用户输入）。"""
    db = database.get_db()
    n = db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    db.close()
    return n


def _mk_product(product_name="已存在产品", owner_id=1):
    """直接插一条产品，返回 pid（用于产品读取/详情端点的对照与负面断言）。"""
    db = database.get_db()
    db.execute("INSERT INTO products(product_name, owner_id, runner_ids, created_at) VALUES(?,?,?,?)",
               (product_name, owner_id, "[]", "2026-01-01 00:00"))
    db.commit()
    pid = db.execute("SELECT last_insert_rowid()").fetchone()[0]
    db.close()
    return pid


class TestGgProductVideoDomainHuguanDenied:
    """Task 20（最终全分支审查 Critical C-1）：`py/main.py` 的 GG 产品域 / 文案域 /
    YouTube 素材域 / 产品审计域此前**完全没有** `@no_huguan`，实测户管调
    `POST /api/products/create` 返回 200（产品落库），违反设计文档 §3.9
    「产品域与视频素材域一律拒绝户管」。

    本类的每条用例都同时断三件事：谁被拒（状态码 + 文案）、谁没被拒（对照行）、
    DB 有没有真的变（负面事实断言）。只断状态码等于假绿。
    """

    HUGUAN_MSG = "户管无产品/素材权限"

    # ---------------- 1. 产品域写 ----------------

    def test_huguan_create_product_denied_and_db_unchanged(self, client):
        """户管建产品 → 403 + 原文案，且 products 表**没有**新增该产品。"""
        hg, _ = _huguan(client, "_t20_prod_create")
        before = _count_rows("products")
        resp = client.post("/api/products/create", json={"product_name": "户管偷建的产品"}, headers=hg)
        assert resp.status_code == 403
        assert resp.get_json()["error"] == self.HUGUAN_MSG
        db = database.get_db()
        n = db.execute("SELECT COUNT(*) FROM products WHERE product_name=?",
                       ("户管偷建的产品",)).fetchone()[0]
        db.close()
        assert n == 0, "守卫只挡了响应，产品仍落库了"
        assert _count_rows("products") == before

    # ---------------- 2. 产品域读 ----------------

    def test_huguan_list_products_denied(self, client):
        """户管读产品列表 → 403（读写全拒，D19）。"""
        hg, _ = _huguan(client, "_t20_prod_list")
        _mk_product(product_name="存在的产品")
        resp = client.get("/api/products/list", headers=hg)
        assert resp.status_code == 403
        assert resp.get_json()["error"] == self.HUGUAN_MSG

    def test_huguan_product_detail_denied(self, client):
        """户管读产品详情 → 403；该端点原本**无任何装饰器**，无 token 必须由 200 变 401。"""
        hg, _ = _huguan(client, "_t20_prod_detail")
        pid = _mk_product(product_name="详情产品")
        resp = client.get(f"/api/products/{pid}/detail", headers=hg)
        assert resp.status_code == 403
        assert resp.get_json()["error"] == self.HUGUAN_MSG
        # 补 @jwt_required() 的证据：不带 Authorization 头不再是 200
        anon = client.get(f"/api/products/{pid}/detail")
        assert anon.status_code == 401, "products_detail 仍可匿名访问（缺 @jwt_required）"

    # ---------------- 3. 文案域写 ----------------

    def test_huguan_copywriting_import_denied_and_db_unchanged(self, client):
        """户管导文案 → 403，且 copywritings 表未新增。"""
        hg, _ = _huguan(client, "_t20_cw_import")
        before = _count_rows("copywritings")
        resp = client.post("/api/copywriting/import",
                           json={"text": "户管偷导的文案", "region": "通用"}, headers=hg)
        assert resp.status_code == 403
        assert resp.get_json()["error"] == self.HUGUAN_MSG
        db = database.get_db()
        n = db.execute("SELECT COUNT(*) FROM copywritings WHERE content=?",
                       ("户管偷导的文案",)).fetchone()[0]
        db.close()
        assert n == 0, "守卫只挡了响应，文案仍落库了"
        assert _count_rows("copywritings") == before

    # ---------------- 4. YouTube 素材域 ----------------

    def test_huguan_youtube_list_denied(self, client):
        """户管读 YouTube 素材列表 → 403。"""
        hg, _ = _huguan(client, "_t20_yt_list")
        resp = client.get("/api/youtube/list", headers=hg)
        assert resp.status_code == 403
        assert resp.get_json()["error"] == self.HUGUAN_MSG

    def test_huguan_youtube_import_denied_and_db_unchanged(self, client):
        """户管导 YouTube 素材 → 403，且 videos 表未新增。"""
        hg, _ = _huguan(client, "_t20_yt_import")
        before = _count_rows("videos")
        resp = client.post("/api/youtube/import",
                           json={"urls": ["https://www.youtube.com/watch?v=t20nope"]}, headers=hg)
        assert resp.status_code == 403
        assert resp.get_json()["error"] == self.HUGUAN_MSG
        assert before == 0  # 防「两边都空也算相等」
        assert _count_rows("videos") == before

    # ---------------- 5. 产品审计域 ----------------

    def test_huguan_audit_log_restore_denied(self, client):
        """户管从审计日志恢复产品 → 403（原先拦它的是 developer 检查，文案不同）。"""
        hg, _ = _huguan(client, "_t20_audit")
        db = database.get_db()
        db.execute("INSERT INTO audit_log(user_id, action, target_type, target_id, target_name, detail) "
                   "VALUES(?,?,?,?,?,?)", (1, "delete_product", "product", 99999, "被删产品", "{}"))
        db.commit()
        log_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]
        db.close()
        resp = client.post(f"/api/audit-log/restore/{log_id}", headers=hg)
        assert resp.status_code == 403
        assert resp.get_json()["error"] == self.HUGUAN_MSG
        db = database.get_db()
        n = db.execute("SELECT COUNT(*) FROM products WHERE id=?", (99999,)).fetchone()[0]
        db.close()
        assert n == 0, "产品被恢复了 —— 守卫没生效"

    # ---------------- 6. 视频 / 音频替换域 ----------------

    def test_huguan_video_scan_dir_denied(self, client):
        """户管调视频域（scan-dir）→ 403。"""
        hg, _ = _huguan(client, "_t20_video_scan")
        resp = client.post("/api/video/scan-dir", json={"dir": "."}, headers=hg)
        assert resp.status_code == 403
        assert resp.get_json()["error"] == self.HUGUAN_MSG

    def test_huguan_audio_replace_denied(self, client):
        """户管调音频替换域 → 403（原先该域**完全无鉴权**）。"""
        hg, _ = _huguan(client, "_t20_audio_rep")
        resp = client.get("/api/audio-replace/history", headers=hg)
        assert resp.status_code == 403
        assert resp.get_json()["error"] == self.HUGUAN_MSG

    # ---------------- 7. 对照行：普通 user / developer 不得被堵死 ----------------

    def test_regular_user_not_blocked_on_product_and_video_domain(self, client):
        """对照行（关键）：普通 `user` 调同批端点**不得**是 403 / 户管文案。"""
        u, _ = _create_user(client, "_t20_ctrl_user", role="user", platform="gg")

        assert client.get("/api/products/list", headers=u).status_code != 403

        r_create = client.post("/api/products/create", json={"product_name": "普通用户的产品"}, headers=u)
        assert r_create.status_code == 200, r_create.get_json()
        assert r_create.get_json()["success"] is True
        db = database.get_db()
        n = db.execute("SELECT COUNT(*) FROM products WHERE product_name=?",
                       ("普通用户的产品",)).fetchone()[0]
        db.close()
        assert n == 1, "对照行的产品没落库 —— 说明守卫误伤了普通用户"

        assert client.get("/api/video/history/list", headers=u).status_code != 403

    def test_developer_not_blocked_on_product_and_video_domain(self, client):
        """对照行：`developer` 调同批端点**不得**是 403 / 户管文案。"""
        dev, _ = _create_user(client, "_t20_ctrl_dev", role="developer", platform="gg")

        assert client.get("/api/products/list", headers=dev).status_code != 403

        r_create = client.post("/api/products/create", json={"product_name": "开发者的产品"}, headers=dev)
        assert r_create.status_code == 200, r_create.get_json()
        db = database.get_db()
        n = db.execute("SELECT COUNT(*) FROM products WHERE product_name=?",
                       ("开发者的产品",)).fetchone()[0]
        db.close()
        assert n == 1

        assert client.get("/api/video/history/list", headers=dev).status_code != 403

    # ---------------- 8. 视频/音频域鉴权补口（D23） ----------------

    def test_video_domain_requires_login(self, client):
        """无 Authorization 头 → 401（不是 200）：原先这些端点完全裸奔。"""
        assert client.post("/api/video/scan-dir", json={"dir": "."}).status_code == 401
        assert client.get("/api/video/music-list").status_code == 401
        assert client.post("/api/video/history/save", json={"entry": {}}).status_code == 401
        assert client.get("/api/video/history/list").status_code == 401
        assert client.get("/api/video/progress?task_id=x").status_code == 401

    def test_video_domain_login_still_works_for_normal_user(self, client):
        """对照行：带正常 token 的 `user` 调同批端点不是 401。"""
        u, _ = _create_user(client, "_t20_auth_user", role="user", platform="gg")
        assert client.get("/api/video/music-list", headers=u).status_code == 200
        assert client.get("/api/video/history/list", headers=u).status_code == 200

    def test_audio_replace_domain_requires_login(self, client):
        """无 Authorization 头 → 401。"""
        assert client.get("/api/audio-replace/history").status_code == 401
        assert client.delete("/api/audio-replace/history").status_code == 401

    # ---------------- 9. 下载路径白名单（D24） ----------------

    def test_video_download_rejects_unlisted_path(self, client, tmp_path):
        """临时文件不在 video_tasks 里 → 404 原文案；插入记录后同一请求 → 200。"""
        from urllib.parse import quote
        f = tmp_path / "t20_wl.mp4"
        f.write_bytes(b"fake-video-bytes")
        url = "/api/video/download?path=" + quote(str(f))
        resp = client.get(url)
        assert resp.status_code == 404, "任意路径仍可读文件"
        assert resp.get_json()["error"] == "文件不存在"

        db = database.get_db()
        db.execute("INSERT INTO video_tasks(task_id, status, output_path) VALUES(?,?,?)",
                   ("t20-wl-task", "completed", str(f)))
        db.commit()
        db.close()
        ok = client.get(url)
        assert ok.status_code == 200
        assert ok.data == b"fake-video-bytes"

    def test_audio_replace_download_rejects_unlisted_path(self, client, tmp_path):
        """音频替换下载同法：不在 audio_replace_history 里 → 404，插入后 → 200。"""
        from urllib.parse import quote
        f = tmp_path / "t20_wl_audio.mp4"
        f.write_bytes(b"fake-replaced-bytes")
        url = "/api/audio-replace/download?path=" + quote(str(f))
        resp = client.get(url)
        assert resp.status_code == 404, "任意路径仍可读文件"
        assert resp.get_json()["error"] == "文件不存在"

        db = database.get_db()
        db.execute("INSERT INTO audio_replace_history(video_name, audio_name, output_name, output_path, size_mb) "
                   "VALUES(?,?,?,?,?)", ("v.mp4", "a.mp3", "out.mp4", str(f), 1.0))
        db.commit()
        db.close()
        ok = client.get(url)
        assert ok.status_code == 200
        assert ok.data == b"fake-replaced-bytes"

    def test_video_download_whitelist_is_exact_match(self, client, tmp_path):
        """白名单必须**精确相等**：同目录下未登记的同名/邻近文件仍 404。"""
        from urllib.parse import quote
        listed = tmp_path / "t20_exact.mp4"
        listed.write_bytes(b"listed")
        sibling = tmp_path / "t20_exact_extra.mp4"
        sibling.write_bytes(b"sibling")
        db = database.get_db()
        db.execute("INSERT INTO video_tasks(task_id, status, output_path) VALUES(?,?,?)",
                   ("t20-exact-task", "completed", str(listed)))
        db.commit()
        db.close()
        assert client.get("/api/video/download?path=" + quote(str(listed))).status_code == 200
        assert client.get("/api/video/download?path=" + quote(str(sibling))).status_code == 404

    def test_video_download_rejects_huguan_with_token(self, client, tmp_path):
        """户管带 token 调下载 → 403（前端 window.open 不带 Authorization 头，
        故这条只能验「带 token」这一路）。"""
        from urllib.parse import quote
        hg, _ = _huguan(client, "_t20_dl_hg")
        f = tmp_path / "t20_wl_hg.mp4"
        f.write_bytes(b"hg")
        db = database.get_db()
        db.execute("INSERT INTO video_tasks(task_id, status, output_path) VALUES(?,?,?)",
                   ("t20-wl-hg", "completed", str(f)))
        db.commit()
        db.close()
        resp = client.get("/api/video/download?path=" + quote(str(f)), headers=hg)
        assert resp.status_code == 403
        assert resp.get_json()["error"] == self.HUGUAN_MSG

    # ---------------- 10. Task 20 修复：/api/tasks 收口与 /api/audio 收紧 ----------------

    def test_tasks_rejects_huguan_and_keeps_user_list_intact(self, client):
        """修复 1：户管调 `/api/tasks` → 403 + 原文案。

        对照行（关键）：普通 `user` 仍 200，且能看到任务（不是空列表）——证明新增的
        `@no_huguan` 只挡户管，未改变其他角色拿到的内容。
        """
        hg, _ = _huguan(client, "_t20_tasks_hg")
        u, _ = _create_user(client, "_t20_tasks_user", role="user", platform="gg")
        db = database.get_db()
        db.execute("INSERT INTO video_tasks(task_id, status, output_path, created_at) VALUES(?,?,?,?)",
                   ("t20-tasks-visible", "pending", "/tmp/t20_visible.mp4", "2026-01-01 00:00"))
        db.commit()
        db.close()

        resp = client.get("/api/tasks", headers=hg)
        assert resp.status_code == 403
        assert resp.get_json()["error"] == self.HUGUAN_MSG

        ok = client.get("/api/tasks", headers=u)
        assert ok.status_code == 200, ok.get_json()
        body = ok.get_json()
        assert body["success"] is True
        ids = [t["task_id"] for t in body["tasks"]]
        assert "t20-tasks-visible" in ids, "对照行拿不到任务 —— 守卫误伤了普通用户"

    def test_audio_rejects_audio_replace_artifact_even_anonymous(self, client):
        """修复 2 的核心断言：`/api/audio` 不再能取到 `temp/audio_replace` 下的产物。

        D24 给 `/api/audio-replace/download` 加了精确匹配白名单，但 `/api/audio` 的
        全局静态目录白名单包含整个 `temp` 树，等于开了一道无鉴权的旁路。收紧到音乐目录后，
        带 token 与**不带 token** 都必须 403。
        """
        from urllib.parse import quote
        import main as _main
        art_dir = os.path.join(_main._DATA_ROOT, "temp", "audio_replace")
        os.makedirs(art_dir, exist_ok=True)
        f = os.path.join(art_dir, "t20_artifact_probe_new.mp4")
        with open(f, "wb") as fh:
            fh.write(b"t20-replaced-artifact")
        resp = anon = None
        try:
            url = "/api/audio?path=" + quote(f)
            u, _ = _create_user(client, "_t20_audio_user", role="user", platform="gg")
            resp = client.get(url, headers=u)
            assert resp.status_code == 403, "音频替换产物仍可读 —— 白名单旁路未被堵死"
            anon = client.get(url)
            assert anon.status_code == 403, "匿名仍可取到音频替换产物"
        finally:
            # 若守卫回归放行，流式响应会持有文件句柄（Windows 下挡住删除），先关响应
            for _r in (resp, anon):
                if _r is not None:
                    _r.close()
            try:
                os.remove(f)
            except OSError:
                pass

    def test_audio_serves_music_dir_file_anonymously(self, client):
        """修复 2 的回归面（D25）：**音乐目录内**的文件仍 200，且不带 token 仍 200。

        钉住既有的匿名播放行为，防止本次收紧误伤正常调用点。
        """
        from urllib.parse import quote
        import main as _main
        os.makedirs(_main._MUSIC_DIR, exist_ok=True)
        f = os.path.join(_main._MUSIC_DIR, "t20_music_probe.mp3")
        with open(f, "wb") as fh:
            fh.write(b"t20-music-bytes")
        anon = None
        try:
            url = "/api/audio?path=" + quote(f)
            anon = client.get(url)
            assert anon.status_code == 200, anon.status_code
            assert anon.data == b"t20-music-bytes"
        finally:
            # 流式响应持有文件句柄（Windows 下会挡住删除），先关响应再清理探针文件
            if anon is not None:
                anon.close()
            try:
                os.remove(f)
            except OSError:
                pass

    def test_video_download_whitelisted_path_allows_logged_in_user(self, client, tmp_path):
        """覆盖缺口：**已登录**的普通用户下载白名单内产物 → 200。

        此前只覆盖了匿名放行分支（`optional=True` 无 token），这里补上「带 token」分支，
        确保放行逻辑不是靠匿名路径意外成立的。
        """
        from urllib.parse import quote
        u, _ = _create_user(client, "_t20_dl_user", role="user", platform="gg")
        f = tmp_path / "t20_wl_loggedin.mp4"
        f.write_bytes(b"logged-in-bytes")
        db = database.get_db()
        db.execute("INSERT INTO video_tasks(task_id, status, output_path) VALUES(?,?,?)",
                   ("t20-wl-loggedin", "completed", str(f)))
        db.commit()
        db.close()
        resp = client.get("/api/video/download?path=" + quote(str(f)), headers=u)
        assert resp.status_code == 200, resp.status_code
        assert resp.data == b"logged-in-bytes"


# ==================== 代码审查修复：代理改名/删除的跨用户收口 ====================

class TestAgentsRenameCrossUserDuplicate:
    """修复 C：跨用户（含户管）改代理名时，重名检查必须按**被改代理的所有者**过滤。

    改动前 `agents_rename` 的重名检查用调用者 `user_id` 当 `owner_id`：
    户管把用户 A 的代理改成「A 名下已存在的名字」时查的是**户管自己**名下的重名，
    查不到 → UPDATE 撞 `UNIQUE(name, owner_id, platform)` → `sqlite3.IntegrityError`
    未被捕获 → 接口 500（且异常路径上 `db.close()` 不执行，连接泄漏）。

    纯增量约束：普通 `user`（被改代理的所有者就是自己）的重名语义必须逐字不变。
    """

    def test_huguan_rename_to_existing_name_of_owner_returns_409_and_db_unchanged(self, client):
        """户管把 A 的代理改成 A 名下已有的名字 → 409 + 原文案，且 DB 里该代理名未被改动。"""
        hg, _ = _huguan(client, "_arc_hg")
        _, u1 = _create_user(client, "_arc_u1", role="user", platform="gg")
        db = database.get_db()
        db.execute("INSERT INTO agents(name, owner_id, platform) VALUES('甲代理', ?, 'gg')", (u1,))
        db.execute("INSERT INTO agents(name, owner_id, platform) VALUES('乙代理', ?, 'gg')", (u1,))
        db.commit()
        a_id = db.execute("SELECT id FROM agents WHERE name='甲代理'").fetchone()["id"]
        db.close()

        resp = client.put(f"/api/agents/{a_id}?platform=gg", json={"name": "乙代理"}, headers=hg)
        assert resp.status_code == 409, resp.get_json()
        assert resp.get_json()["error"] == "代理「乙代理」已存在"

        # 负面事实：被改代理的名字不得变化，也不得凭空多出一条同名代理
        db = database.get_db()
        name = db.execute("SELECT name FROM agents WHERE id=?", (a_id,)).fetchone()["name"]
        n_dup = db.execute("SELECT COUNT(*) FROM agents WHERE name='乙代理' AND owner_id=?",
                           (u1,)).fetchone()[0]
        db.close()
        assert name == "甲代理", "重名请求把代理改名了 —— 重名检查未生效"
        assert n_dup == 1, "不得新增/复制出第二条同名代理"

    def test_regular_user_rename_to_own_duplicate_still_409(self, client):
        """纯增量：普通 `user` 改自己代理为自身重复名仍是 409（与改动前逐字一致）。"""
        me, me_id = _create_user(client, "_arc_u2", role="user", platform="gg")
        db = database.get_db()
        db.execute("INSERT INTO agents(name, owner_id, platform) VALUES('丙代理', ?, 'gg')", (me_id,))
        db.execute("INSERT INTO agents(name, owner_id, platform) VALUES('丁代理', ?, 'gg')", (me_id,))
        db.commit()
        c_id = db.execute("SELECT id FROM agents WHERE name='丙代理'").fetchone()["id"]
        db.close()

        resp = client.put(f"/api/agents/{c_id}?platform=gg", json={"name": "丁代理"}, headers=me)
        assert resp.status_code == 409, resp.get_json()
        assert resp.get_json()["error"] == "代理「丁代理」已存在"
        db = database.get_db()
        name = db.execute("SELECT name FROM agents WHERE id=?", (c_id,)).fetchone()["name"]
        db.close()
        assert name == "丙代理"

    def test_regular_user_rename_to_new_name_still_200_and_updated(self, client):
        """纯增量对照：普通 `user` 改成全新名字仍 200 且 DB 已更新。"""
        me, me_id = _create_user(client, "_arc_u3", role="user", platform="gg")
        db = database.get_db()
        db.execute("INSERT INTO agents(name, owner_id, platform) VALUES('戊代理', ?, 'gg')", (me_id,))
        db.commit()
        e_id = db.execute("SELECT id FROM agents WHERE name='戊代理'").fetchone()["id"]
        db.close()

        resp = client.put(f"/api/agents/{e_id}?platform=gg", json={"name": "全新代理名"}, headers=me)
        assert resp.status_code == 200, resp.get_json()
        db = database.get_db()
        name = db.execute("SELECT name FROM agents WHERE id=?", (e_id,)).fetchone()["name"]
        db.close()
        assert name == "全新代理名"

    def test_huguan_rename_to_new_name_still_200(self, client):
        """对照行：修复 C 不得误伤户管改他人代理的正常路径。"""
        hg, _ = _huguan(client, "_arc_hg2")
        _, u1 = _create_user(client, "_arc_u4", role="user", platform="gg")
        db = database.get_db()
        db.execute("INSERT INTO agents(name, owner_id, platform) VALUES('己代理', ?, 'gg')", (u1,))
        db.commit()
        f_id = db.execute("SELECT id FROM agents WHERE name='己代理'").fetchone()["id"]
        db.close()

        resp = client.put(f"/api/agents/{f_id}?platform=gg", json={"name": "户管改的新名"}, headers=hg)
        assert resp.status_code == 200, resp.get_json()
        db = database.get_db()
        name = db.execute("SELECT name FROM agents WHERE id=?", (f_id,)).fetchone()["name"]
        db.close()
        assert name == "户管改的新名"


class TestAgentsCacheInvalidationCrossUser:
    """修复 B：跨用户改/删代理时，代理名下拉缓存必须对**代理所有者**失效。

    缓存键 `accounts:agents:{请求者 id}:{scope}` 以请求者 id 打头，而缓存值是
    「按 `owner_filter or user_id` 查出的代理名」。改动前写接口只清 `{调用者}:` 前缀 ——
    户管改/删他人代理时，代理**所有者**的缓存最长 120 秒仍是旧名；用户在「代理」下拉里
    选中旧名后按名过滤匹配不到账号，列表为空。
    """

    def test_rename_by_huguan_invalidates_owner_dropdown_cache(self, client):
        """A 先读列表把缓存写热 → 户管改 A 的代理名 → A 再读必须看到**新名**。"""
        from cache import cache as _app_cache
        _app_cache.clear()   # 进程级全局缓存，pytest 不重置；见 TestGgAgentsDropdownCacheInvalidation

        hg, _ = _huguan(client, "_aci_hg")
        hdr_a, a_id = _create_user(client, "_aci_u1", role="user", platform="gg")
        db = database.get_db()
        _mk_account(db, a_id, "GG-ACI-1", "A的账户")
        db.execute("INSERT INTO agents(name, owner_id, platform) VALUES('改名前代理', ?, 'gg')", (a_id,))
        ag = db.execute("SELECT id FROM agents WHERE name='改名前代理'").fetchone()["id"]
        db.execute("UPDATE accounts SET agent_id=? WHERE account_id='GG-ACI-1'", (ag,))
        db.commit()
        db.close()

        # 第 1 步：A（所有者）读列表 → 把 `accounts:agents:{A}:{A}` 写热
        data = client.get("/api/accounts/list?size=50", headers=hdr_a).get_json()
        assert "改名前代理" in data["agents"]

        # 第 2 步：**户管**（非所有者）改名
        resp = client.put(f"/api/agents/{ag}?platform=gg", json={"name": "改名后代理"}, headers=hg)
        assert resp.status_code == 200, resp.get_json()

        # 第 3 步：A 再读 —— 缓存必须已失效，否则仍是旧名
        data = client.get("/api/accounts/list?size=50", headers=hdr_a).get_json()
        assert "改名后代理" in data["agents"]
        assert "改名前代理" not in data["agents"]

    def test_delete_by_huguan_invalidates_owner_dropdown_cache(self, client):
        """A 先读列表把缓存写热 → 户管删 A 的代理 → A 再读不得再有该旧名。

        构造要点：`agents_delete` 在有账户引用时会 409，因此第 1 步（把「待删代理」
        写进 A 的缓存）与第 2 步之间先把账户的 `agent_id` 置空解除引用 ——
        缓存里仍留着旧名，正是要钉住的「陈旧缓存」。
        """
        from cache import cache as _app_cache
        _app_cache.clear()

        hg, _ = _huguan(client, "_aci_hg2")
        hdr_a, a_id = _create_user(client, "_aci_u2", role="user", platform="gg")
        db = database.get_db()
        _mk_account(db, a_id, "GG-ACI-2", "A的账户")
        db.execute("INSERT INTO agents(name, owner_id, platform) VALUES('待删代理', ?, 'gg')", (a_id,))
        ag = db.execute("SELECT id FROM agents WHERE name='待删代理'").fetchone()["id"]
        db.execute("UPDATE accounts SET agent_id=? WHERE account_id='GG-ACI-2'", (ag,))
        db.commit()
        db.close()

        # 第 1 步：A 读列表 → 缓存写热，含「待删代理」
        data = client.get("/api/accounts/list?size=50", headers=hdr_a).get_json()
        assert "待删代理" in data["agents"]

        # 解除引用，使删除可通过账户引用检查
        db = database.get_db()
        db.execute("UPDATE accounts SET agent_id=NULL WHERE account_id='GG-ACI-2'")
        db.commit()
        db.close()

        # 第 2 步：户管删除该代理
        resp = client.delete(f"/api/agents/{ag}?platform=gg", headers=hg)
        assert resp.status_code == 200, resp.get_json()

        # 第 3 步：A 再读 —— 缓存必须已失效，旧名不得再出现
        data = client.get("/api/accounts/list?size=50", headers=hdr_a).get_json()
        assert "待删代理" not in data["agents"]


class TestGgAccountListDropdownScope:
    """回归：跨用户角色的三个筛选下拉必须与账户列表口径一致。

    缺陷（本需求自己引入）：`accounts_list` 在跨用户角色 + 不带 owner_id（「全部用户」）时
    列表跨用户，但 `mcc_options` / `agents` / `timezone_options` 仍用 `owner_filter or user_id`
    收窄到请求者自己 —— 户管名下通常没有账户，于是三个下拉全空，无法对全量列表筛选。
    设计文档 docs/superpowers/specs/2026-09-22-huguan-role-design.md:154 点名要求避免这种不一致。

    夹具刻意让**户管名下没有任何账户**，以复现「三个下拉全空」的真实场景；三个下拉的
    数据全部挂在 u1 / u2 名下，改动前一并会被 `user_id` 收窄掉。
    """

    def _setup(self, client):
        from cache import cache as _app_cache
        _app_cache.clear()   # 进程级全局缓存；缓存键含 user_id，须防跨用例串数据

        hg, hg_id = _huguan(client, "_ddsc_hg")            # 户管：名下无任何账户
        hdr_u1, u1 = _create_user(client, "_ddsc_u1", role="user")
        hdr_u2, u2 = _create_user(client, "_ddsc_u2", role="user")
        db = database.get_db()
        _mk_mcc(db, u1, "MCC-S1", "U1的MCC")
        _mk_mcc(db, u2, "MCC-S2", "U2的MCC")
        db.execute("INSERT INTO agents(name, owner_id, platform) VALUES('代理S1', ?, 'gg')", (u1,))
        db.execute("INSERT INTO agents(name, owner_id, platform) VALUES('代理S2', ?, 'gg')", (u2,))
        ag1 = db.execute("SELECT id FROM agents WHERE name='代理S1'").fetchone()["id"]
        ag2 = db.execute("SELECT id FROM agents WHERE name='代理S2'").fetchone()["id"]
        m1 = db.execute("SELECT id FROM mcc WHERE mcc_id='MCC-S1'").fetchone()["id"]
        m2 = db.execute("SELECT id FROM mcc WHERE mcc_id='MCC-S2'").fetchone()["id"]
        _mk_account(db, u1, "GG-SC-1", "U1账户")
        _mk_account(db, u2, "GG-SC-2", "U2账户")
        db.execute("UPDATE accounts SET agent_id=?, mcc_id=?, timezone='Asia/Shanghai' "
                   "WHERE account_id='GG-SC-1'", (ag1, m1))
        db.execute("UPDATE accounts SET agent_id=?, mcc_id=?, timezone='America/New_York' "
                   "WHERE account_id='GG-SC-2'", (ag2, m2))
        db.commit()
        db.close()
        return hg, hg_id, u1, u2, hdr_u1, hdr_u2

    def test_huguan_all_users_dropdowns_cover_other_users(self, client):
        """户管 + 不带 owner_id（「全部用户」）→ 他人名下的 MCC/代理/时区必须都出现在下拉里。

        本缺陷的直接回归测试：户管名下无账户，改动前三个下拉全空。
        """
        hg, _, _, _, _, _ = self._setup(client)
        resp = client.get("/api/accounts/list?size=50", headers=hg)
        assert resp.status_code == 200
        data = resp.get_json()
        # 列表本身跨用户（既有行为，非本次改动）
        assert {a["account_id"] for a in data["accounts"]} == {"GG-SC-1", "GG-SC-2"}
        # 三个下拉必须覆盖全量，与列表口径一致
        assert {"U1的MCC", "U2的MCC"} <= {m["name"] for m in data["mcc_options"]}
        assert {"代理S1", "代理S2"} <= set(data["agents"])
        assert {"Asia/Shanghai", "America/New_York"} <= set(data["timezone_options"])

    def test_huguan_owner_filter_narrows_dropdowns(self, client):
        """对照组：户管 + owner_id=u1 → 三个下拉只含 u1 的（改动前就该通过）。"""
        hg, _, u1, _, _, _ = self._setup(client)
        resp = client.get(f"/api/accounts/list?size=50&owner_id={u1}", headers=hg)
        data = resp.get_json()
        assert {m["name"] for m in data["mcc_options"]} == {"U1的MCC"}
        assert data["agents"] == ["代理S1"]
        assert data["timezone_options"] == ["Asia/Shanghai"]

    def test_regular_user_dropdowns_stay_scoped_to_self(self, client):
        """纯增量对照组：非跨用户 + 不带 owner_id → 只含自己的，不含他人的。"""
        _, _, _, _, hdr_u1, _ = self._setup(client)
        resp = client.get("/api/accounts/list?size=50", headers=hdr_u1)
        data = resp.get_json()
        assert {a["account_id"] for a in data["accounts"]} == {"GG-SC-1"}
        assert {m["name"] for m in data["mcc_options"]} == {"U1的MCC"}
        assert data["agents"] == ["代理S1"]
        assert data["timezone_options"] == ["Asia/Shanghai"]

    def test_regular_user_ignores_owner_id_on_dropdowns(self, client):
        """非跨用户 + owner_id=他人 → 参数被忽略，三个下拉仍只含自己的。"""
        _, _, _, u2, hdr_u1, _ = self._setup(client)
        resp = client.get(f"/api/accounts/list?size=50&owner_id={u2}", headers=hdr_u1)
        data = resp.get_json()
        assert {a["account_id"] for a in data["accounts"]} == {"GG-SC-1"}
        assert {m["name"] for m in data["mcc_options"]} == {"U1的MCC"}
        assert data["agents"] == ["代理S1"]
        assert data["timezone_options"] == ["Asia/Shanghai"]
