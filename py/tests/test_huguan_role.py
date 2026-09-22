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
        """锁定既有单向行为：取消隐藏一律回落 user，对任何角色都一样。

        这不是本需求引入的缺陷，也不是户管独有 —— `toggle_user_status` 只在「隐藏」
        方向查元组，因此 `hidden` 落到 else 分支的 `"user"`，admin / viewer 同样如此。
        本用例存在的意义是把这个既有语义写下来，避免后人误以为「取消隐藏会恢复原角色」。
        如需改成恢复隐藏前的角色，那是独立的产品决策（需记忆字段），不在本需求范围。
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
        assert auth.update_user_role(uid, "huguan") is True

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
