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


class TestEffectivePlatformFallback:
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
