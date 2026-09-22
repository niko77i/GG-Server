"""户管（huguan）角色权限测试。"""
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
        role in ('developer','admin') 不加 owner 过滤，GG 管理员将看到全部用户的 TT 账户。
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
