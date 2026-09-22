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


class TestPlatformUsersEndpoint:
    def test_huguan_sees_only_current_platform(self, client):
        """户管切到 TT 时只应看到 TT + developer，不该看到 GG 行。

        注意这里用 `?platform=tt` 而**不是**调用者自身的 gg —— 否则即使
        `_get_effective_platform()` 完全忽略查询参数，本用例也会通过。
        """
        hg, _ = _huguan(client, "_hgpu_hg")  # users.platform == 'gg'
        db = database.get_db()
        db.execute("INSERT INTO users(username, password, role, platform) VALUES('_hgpu_gg','x','user','gg')")
        db.execute("INSERT INTO users(username, password, role, platform) VALUES('_hgpu_tt','x','user','tt')")
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
        """
        hg, _ = _huguan(client, "_hgpu_hg2")
        db = database.get_db()
        db.execute("INSERT INTO users(username, password, role, platform) VALUES('_hgpu_dev','x','developer','tt')")
        db.execute("INSERT INTO users(username, password, role, platform) VALUES('_hgpu_hid','x','hidden','gg')")
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
        """
        u, _ = _create_user(client, "_hgpu_plain", role="user", platform="gg")
        db = database.get_db()
        db.execute("INSERT INTO users(username, password, role, platform) VALUES('_hgpu_leak','x','user','tt')")
        db.commit()
        db.close()
        resp = client.get("/api/platform/users?platform=tt", headers=u)
        assert resp.status_code == 200
        names = {x["username"] for x in resp.get_json()["users"]}
        assert "_hgpu_leak" not in names
        # 正向断言：调用者自己（platform='gg'）必须在结果里。否则若接口返回空列表，
        # 上面那条负面断言也会通过 —— 那就成了空断言。
        assert "_hgpu_plain" in names


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
