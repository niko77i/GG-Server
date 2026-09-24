"""爬取产物归属校验测试 —— B-3 的两个越权入口（侧门 + 正门）。

## 为什么必须两条门一起测

`/api/scrape/download` 是 `@jwt_required(optional=True)`：合法 JWT **或** 有效签名
二者其一放行。签名路径由浏览器原生请求消费（`window.open`），**不带 Authorization**，
因此**校验方拿不到身份**，无法在此判断归属。

于是归属只能在**签发侧**（`POST /api/scrape` 的 `save_dir`）堵死。只测正门不测侧门，
就等于用一套「攻击者根本不用走那条门」的断言冒充安全 —— 这是本文件存在的理由。
"""
import os
import shutil
import sqlite3
import subprocess
import sys
import threading
import time

import pytest

import auth
import database
from main import _SCRAPE_DEFAULT_DIR, _scrape_dir_for, _scrape_dn_for


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


@pytest.fixture
def scrape_dirs():
    """记录测试造出的爬取目录，结束后清理（避免污染真实的 scraped_images/）。"""
    made = []

    def _make(username, pkg):
        d = os.path.join(_SCRAPE_DEFAULT_DIR, username, pkg)
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, "a.png"), "wb") as f:
            f.write(b"\x89PNG\r\n\x1a\n" + b"P" * 32)
        made.append(os.path.join(_SCRAPE_DEFAULT_DIR, username))
        return d

    yield _make
    for d in made:
        shutil.rmtree(d, ignore_errors=True)


def _play_url(pkg):
    """包名从 `?id=` 提取 —— 目录名必须与它一致才能命中缓存分支。"""
    return f"https://play.google.com/store/apps/details?id={pkg}"


def _save_dir_of(username):
    return os.path.join(_SCRAPE_DEFAULT_DIR, username)


def _is_inside_root(path):
    """path 是否落在爬取根之内（含等于）。两边先 realpath 归一化再比。"""
    r, p = os.path.realpath(_SCRAPE_DEFAULT_DIR), os.path.realpath(path)
    return p == r or p.startswith(r + os.sep)


def _uid_of(username):
    db = database.get_db()
    try:
        row = db.execute("SELECT id FROM users WHERE username=?", (username,)).fetchone()
    finally:
        db.close()
    return row["id"] if row else None


# ===========================================================================
# 侧门：POST /api/scrape 的 save_dir —— 归属的**唯一**关口
# ===========================================================================
class TestSideDoorSaveDir:
    def test_cross_user_save_dir_denied(self, client, scrape_dirs):
        """承重：bob 传 alice 的 save_dir ⇒ 403。

        这是 B-3 的真入口。放行的后果不是「多读一个目录」，而是 bob 拿到一个
        **为 alice 的包签发的合法签名**，而签名路径上没有身份可校验 ——
        正门加多少归属校验都形同虚设（攻击者不走那道门）。
        """
        _create_user(client, "_own_alice")
        bob, _ = _create_user(client, "_own_bob")
        scrape_dirs("_own_alice", "SidePkg")

        r = client.post("/api/scrape",
                        json={"url": _play_url("SidePkg"), "save_dir": _save_dir_of("_own_alice")},
                        headers=bob)
        assert r.status_code == 403, (
            f"bob 用 alice 的 save_dir 拿到 {r.status_code} —— 侧门未堵，"
            f"响应={r.get_json()}"
        )
        # 关键：不得在响应里漏出签名
        assert "download_url" not in (r.get_json() or {}), (
            "被拒的请求仍下发了 download_url —— 归属校验形同虚设"
        )

    def test_own_save_dir_allowed(self, client, scrape_dirs):
        """对照行：自己的 save_dir 必须放行（否则上一条把功能整体禁掉也能全绿）。"""
        bob, _ = _create_user(client, "_own_bob2")
        scrape_dirs("_own_bob2", "SidePkg")
        r = client.post("/api/scrape",
                        json={"url": _play_url("SidePkg"), "save_dir": _save_dir_of("_own_bob2")},
                        headers=bob)
        assert r.status_code == 200, f"自己的目录被拒：{r.status_code} {r.get_json()}"

    def test_omitted_save_dir_allowed(self, client, scrape_dirs):
        """不传 save_dir（前端现状）⇒ 落到自己目录，必须放行。"""
        bob, _ = _create_user(client, "_own_bob3")
        scrape_dirs("_own_bob3", "SidePkg")
        r = client.post("/api/scrape", json={"url": _play_url("SidePkg")}, headers=bob)
        assert r.status_code == 200, f"省略 save_dir 被拒：{r.status_code} {r.get_json()}"

    def test_admin_cross_user_save_dir_allowed(self, client, scrape_dirs):
        """反向承重：developer/admin 传他人 save_dir ⇒ 200。

        没有这条，「他人 ⇒ 403」只要把整条链路写成 `return 403` 就能全绿。
        管理员豁免的判据与 scrape_packages 同源（scrape_packages 允许管理员传
        user_dn 列他人的包）—— 若此处 403，管理员会在界面「看得到包、点不动」。
        """
        _create_user(client, "_own_alice3")
        dev, _ = _create_user(client, "_own_dev", role="developer")
        scrape_dirs("_own_alice3", "SidePkg")
        r = client.post("/api/scrape",
                        json={"url": _play_url("SidePkg"),
                              "save_dir": _save_dir_of("_own_alice3")},
                        headers=dev)
        assert r.status_code == 200, (
            f"管理员被拒（{r.status_code}）—— 与 scrape_packages 的 is_admin 判据分叉，"
            f"会造成「列表看得到、下载点不动」"
        )

    def test_huguan_is_not_cross_user(self, client, scrape_dirs):
        """huguan **不**享有跨用户访问。

        钉死角色集与 scrape_packages 一致（developer/admin）。routes/helpers.py 的
        CROSS_USER_ROLES 含 huguan，但爬取产物的既有判据不含 —— 不得擅自扩大。
        """
        _create_user(client, "_own_alice4")
        hg, _ = _create_user(client, "_own_hg", role="huguan")
        scrape_dirs("_own_alice4", "SidePkg")
        r = client.post("/api/scrape",
                        json={"url": _play_url("SidePkg"),
                              "save_dir": _save_dir_of("_own_alice4")},
                        headers=hg)
        assert r.status_code == 403, (
            f"huguan 拿到了 {r.status_code} —— 角色集被擅自扩大（应仅 developer/admin）"
        )

    def test_prefix_sibling_save_dir_denied(self, client, scrape_dirs):
        """承重：`_sd_alice` 不得因前缀而把 `_sd_alice2` 的目录当自己的。

        侧门同样走 `_is_within`，故前缀陷阱在这里也存在 —— 与正门那条是**两条**
        独立的覆盖，因为两道门是两处调用点。
        """
        alice, _ = _create_user(client, "_sd_alice")
        _create_user(client, "_sd_alice2")
        scrape_dirs("_sd_alice2", "TrapPkg")
        r = client.post("/api/scrape",
                        json={"url": _play_url("TrapPkg"),
                              "save_dir": _save_dir_of("_sd_alice2")},
                        headers=alice)
        assert r.status_code == 403, (
            f"`_sd_alice` 把 `_sd_alice2` 的目录当成了自己的（{r.status_code}）—— "
            f"侧门的前缀同族越权"
        )


# ===========================================================================
# 正门：GET /api/scrape/download —— 有身份时的归属校验
# ===========================================================================
class TestFrontDoorDownload:
    def test_other_user_dir_with_token_denied(self, client, scrape_dirs):
        """承重：bob 带自己的合法 token 直接下载 alice 的包 ⇒ 403。"""
        _create_user(client, "_fd_alice")
        bob, _ = _create_user(client, "_fd_bob")
        d = scrape_dirs("_fd_alice", "FrontPkg")
        r = client.get("/api/scrape/download?path=" + d, headers=bob)
        assert r.status_code == 403, f"bob 下载 alice 的包得到 {r.status_code}（应 403）"

    def test_own_dir_with_token_allowed(self, client, scrape_dirs):
        """对照行：自己的包必须能下。"""
        bob, _ = _create_user(client, "_fd_bob2")
        d = scrape_dirs("_fd_bob2", "FrontPkg")
        r = client.get("/api/scrape/download?path=" + d, headers=bob)
        assert r.status_code == 200, f"自己的包下不了：{r.status_code}"
        assert len(r.data) > 0

    def test_admin_other_user_dir_allowed(self, client, scrape_dirs):
        """反向承重：admin 下他人的包 ⇒ 200（与列表侧同源）。"""
        _create_user(client, "_fd_alice2")
        dev, _ = _create_user(client, "_fd_dev", role="developer")
        d = scrape_dirs("_fd_alice2", "FrontPkg")
        r = client.get("/api/scrape/download?path=" + d, headers=dev)
        assert r.status_code == 200, f"管理员下他人的包被拒：{r.status_code}"

    def test_prefix_sibling_trap(self, client, scrape_dirs):
        """承重：`_pfx_alice` 不得因前缀而读到 `_pfx_alice2` 的包。

        钉死 `_is_within` 必须带 `+ os.sep`。裸 startswith 会在这里放行 ——
        本仓库确实同时存在 alice / alice2 两个真实用户目录，该陷阱是现成的。
        """
        alice, _ = _create_user(client, "_pfx_alice")
        _create_user(client, "_pfx_alice2")
        d = scrape_dirs("_pfx_alice2", "TrapPkg")
        r = client.get("/api/scrape/download?path=" + d, headers=alice)
        assert r.status_code == 403, (
            f"`_pfx_alice` 读到了 `_pfx_alice2` 的包（{r.status_code}）—— "
            f"归属比对缺 `+ os.sep`，前缀同族越权"
        )

    def test_anonymous_denied(self, client, scrape_dirs):
        """匿名（无 token、无签名）⇒ 401，不得是 403/200。"""
        d = scrape_dirs("_fd_anon", "FrontPkg")
        r = client.get("/api/scrape/download?path=" + d)
        assert r.status_code == 401, f"匿名得到 {r.status_code}（应 401）"

    def test_huguan_denied(self, client, scrape_dirs):
        """huguan 下他人的包 ⇒ 403。

        与侧门那条是**两处独立调用点**：正门直接查 `_SCRAPE_CROSS_USER_ROLES`，
        侧门经由 `_scrape_dn_for`。若正门哪天被改成写死一份角色名单，这条会红。
        """
        _create_user(client, "_fd_alice3")
        hg, _ = _create_user(client, "_fd_hg", role="huguan")
        d = scrape_dirs("_fd_alice3", "FrontPkg")
        r = client.get("/api/scrape/download?path=" + d, headers=hg)
        assert r.status_code == 403, (
            f"huguan 下到了他人的包（{r.status_code}）—— 正门的角色判据与侧门分叉"
        )

    def test_nonexistent_other_user_dir_is_403_not_404(self, client):
        """非属主对**不存在**的目录也应是 403，不能靠 404/403 差异探测存在性。"""
        bob, _ = _create_user(client, "_fd_bob3")
        ghost = os.path.join(_SCRAPE_DEFAULT_DIR, "_fd_nobody", "GhostPkg")
        r = client.get("/api/scrape/download?path=" + ghost, headers=bob)
        assert r.status_code == 403, (
            f"不存在的他人目录返回 {r.status_code} —— 403/404 差异构成存在性探测器"
        )


# ===========================================================================
# 包名本身也是越权通道：归属收窄只看得见 save_dir，而签发的是 pkg_dir
# ===========================================================================
class TestPackageNameIsNotATraversalVector:
    """`pkg_name` 来自 `?id=`，`extract_package_name`（utils.py:4）原样返回捕获组，
    **未经清洗**。而 `/api/scrape` 签发的 URL 指向 `pkg_dir = join(save_dir, pkg_name)`
    —— 归属收窄只校验 `save_dir` ⇒ 包名可穿则归属校验整条失效。

    这不是推演，是 2026-09-24 的运行时实测（修复前，真实 5001）：
    bob 传 `?id=../_rv_alice/TravPkg` → **200**，拿到为 alice 的包签发的合法签名，
    匿名 GET 之 → **200 / 121 字节**；`?id=D:/.../AbsPkg` 还在 `_SCRAPE_DEFAULT_DIR`
    之外真的建出了目录。⇒ 本类是该越权面的承重测试。
    """

    @pytest.fixture(autouse=True)
    def _clean_pn_residue(self):
        """本类必须自清。

        这些用例**刻意**把「有问题的包名」喂进端点。闸门正常时它们全部 400、什么都不建；
        但一旦闸门被人拆掉（例如变异验证 M6），分支就会走到底并**真的建出目录** ——
        2026-09-24 实测：M6 那一轮在真实 `scraped_images/` 里留下了 `_pn_bob/sub/dir`
        和 `_pn_bob/a/b`。测试污染生产数据目录比测试不绿更糟，故进出各扫一次。
        """
        def _sweep():
            if os.path.isdir(_SCRAPE_DEFAULT_DIR):
                for name in os.listdir(_SCRAPE_DEFAULT_DIR):
                    if name.startswith("_pn_"):
                        shutil.rmtree(os.path.join(_SCRAPE_DEFAULT_DIR, name), ignore_errors=True)
            shutil.rmtree(os.path.join(_SCRAPE_DEFAULT_DIR, "..", "_pn_outside"),
                          ignore_errors=True)

        _sweep()
        yield
        _sweep()

    @pytest.mark.parametrize("bad", [
        "../_pn_alice/TravPkg",       # 正斜杠上跳
        "..\\_pn_alice\\TravPkg",     # 反斜杠上跳（本仓库历史上只防 / 不防 \）
        "..",                         # 上跳到 save_dir 本身
        ".",                          # join 后退化为 save_dir，等于签了父目录
        "C:/Windows",                 # 盘符绝对路径，join 会整条丢弃 save_dir
        "sub/dir",                    # 普通子路径也不该当包名
        "a\\b",                       # 单个反斜杠
    ])
    def test_traversal_package_name_rejected(self, client, bad):
        bob, _ = _create_user(client, "_pn_bob")
        r = client.post("/api/scrape",
                        json={"url": f"https://play.google.com/store/apps/details?id={bad}"},
                        headers=bob)
        assert r.status_code == 400, (
            f"包名 {bad!r} 得到 {r.status_code} —— 越权通道未堵，响应={r.get_json()}"
        )
        assert "download_url" not in (r.get_json() or {}), (
            f"包名 {bad!r} 被拒后仍下发了 download_url"
        )

    def test_legit_package_name_still_works(self, client, scrape_dirs):
        """对照行：正常包名必须放行 —— 否则上一条把功能整体禁掉也能全绿。"""
        bob, _ = _create_user(client, "_pn_bob2")
        scrape_dirs("_pn_bob2", "com.example.legit")
        r = client.post("/api/scrape",
                        json={"url": _play_url("com.example.legit")}, headers=bob)
        assert r.status_code == 200, f"正常包名被误伤：{r.status_code} {r.get_json()}"

    def test_absolute_escape_creates_no_directory(self, client):
        """承重：绝对路径包名**不得**在 _SCRAPE_DEFAULT_DIR 之外建出任何目录。

        修复前这里会真的 `makedirs` 成功（实测），故不能只断言状态码 —— 必须断言
        文件系统结果，否则「返回 400 但目录已建」仍会绿。
        """
        bob, _ = _create_user(client, "_pn_bob3")
        parent = os.path.join(_SCRAPE_DEFAULT_DIR, "..", "_pn_outside")
        target = os.path.join(parent, "AbsPkg")
        try:
            r = client.post("/api/scrape",
                            json={"url": _play_url(target.replace("\\", "/"))},
                            headers=bob)
            assert r.status_code == 400, f"绝对路径包名得到 {r.status_code}"
            assert not os.path.isdir(target), (
                f"目录被建到了白名单之外：{target}"
            )
        finally:
            shutil.rmtree(parent, ignore_errors=True)


# ===========================================================================
# 签名路径仍然可用（不得因收口把功能打死）
# ===========================================================================
class TestSignedPathUnaffected:
    def test_issued_signature_downloads(self, client, scrape_dirs):
        """闭环：为**自己**的包签发的 URL，不带 token 也必须能下载。"""
        bob, _ = _create_user(client, "_sp_bob")
        scrape_dirs("_sp_bob", "SignedPkg")
        r = client.post("/api/scrape",
                        json={"url": _play_url("SignedPkg"), "save_dir": _save_dir_of("_sp_bob")},
                        headers=bob)
        assert r.status_code == 200
        url = r.get_json().get("download_url")
        assert url, f"响应未含 download_url：{r.get_json()}"

        rd = client.get(url)  # 刻意不带 Authorization
        assert rd.status_code == 200, f"自己包的签名被拒：{rd.status_code} url={url}"
        assert len(rd.data) > 0

    def test_signature_ttl_matches_jwt_lifetime(self, client, app, scrape_dirs):
        """TTL 必须与应用自身 JWT 有效期一致（默认 86400s）。

        为什么钉死这一点：TTL 太短会让「面板停留后点下载」必 401（前端无重签路径），
        太长则无谓放大转发窗口。锚定到 JWT 寿命是有原则的边界 —— 签名 URL 本就是
        JWT 在浏览器原生请求场景下的替身，不应比它替代的东西活得更久。
        """
        bob, _ = _create_user(client, "_sp_bob2")
        scrape_dirs("_sp_bob2", "TtlPkg")
        r = client.post("/api/scrape",
                        json={"url": _play_url("TtlPkg"), "save_dir": _save_dir_of("_sp_bob2")},
                        headers=bob)
        url = r.get_json()["download_url"]
        exp = int([p for p in url.split("?")[1].split("&") if p.startswith("exp=")][0][4:])

        jwt_ttl = int(app.config["JWT_ACCESS_TOKEN_EXPIRES"])
        delta = exp - time.time()
        assert jwt_ttl - 60 <= delta <= jwt_ttl + 60, (
            f"签名剩余有效期 {delta:.0f}s 与 JWT 寿命 {jwt_ttl}s 不符"
        )
        assert delta > 3600, (
            f"签名有效期仅 {delta:.0f}s —— 短于 1 小时会让「面板停留后点下载」必 401"
        )


# ===========================================================================
# 目录名的**两个入口**：username 与 display_name
#
# `_scrape_dn_for` 是 `display_name or username` —— 这条通道有两个入口。
# 2026-09-24 实测：只锁 display_name 之后，用 username = `..\..\_un_e\pwn`
# （15 字符，通过「4-20 字符」长度闸门）注册 → `_scrape_dir_for` 推导出的路径
# 规范化后仍在 _SCRAPE_DEFAULT_DIR 之外。**锁一个等于没锁。**
# 危害不止写入侧：scrape_packages 会直接 listdir 推导出的目录 = 信息泄露。
# ===========================================================================
class TestDirectoryNameHasTwoEntries:
    def test_scrape_dn_for_bounds_username(self):
        """承重：越界的 username 不得被当作目录名交出去。

        直接调推导函数（绕开 HTTP 闸门）—— 这是「结构上防住」与
        「碰巧被别的检查挡住」的分界。
        """
        dn = _scrape_dn_for({"username": "..\\..\\_dn_e\\pwn", "display_name": "", "role": "user"}, 99)
        assert dn == "user_99", f"越界 username 被原样用作目录名：{dn!r}"
        d = _scrape_dir_for({"username": "..\\..\\_dn_e\\pwn", "display_name": "", "role": "user"}, 99)
        assert _is_inside_root(d), f"推导出的路径越出爬取根：{d}"

    def test_scrape_dn_for_bounds_display_name(self):
        """承重：display_name 是同一通道的另一个入口，同样要被兜住。"""
        d = _scrape_dir_for({"username": "ok_user", "display_name": "..\\..\\_dn_e\\pwn", "role": "user"}, 98)
        assert _is_inside_root(d), f"display_name 注入后路径越出爬取根：{d}"

    def test_scrape_dn_for_keeps_normal_names(self):
        """对照行：正常名字必须原样保留。

        没有这条，「一律退化成 user_<id>」也能让上面两条全绿 ——
        而那会让所有人的爬取产物挤进同一个目录（数据串号）。
        """
        assert _scrape_dn_for({"username": "zhang.san", "display_name": "", "role": "user"}, 1) == "zhang.san"
        assert _scrape_dn_for({"username": "x", "display_name": "张三", "role": "user"}, 1) == "张三"

    @pytest.mark.parametrize("bad", [
        "..\\..\\_dn_e\\pwn",   # 反斜杠上跳（长度 15，长度闸门放行）
        "../_dn_e/pwn",         # 正斜杠上跳
        "a:b_c",                # 冒号（Windows 盘符/ADS）
    ])
    def test_register_rejects_bad_username(self, client, bad):
        """承重：这些 username 必须在建号关口就被拒。

        ⚠️ 断言的是**状态码 400**，不是「被拒」这个感觉 —— 长度闸门也返回 400，
        所以下面必须配一条长度合法性的对照（见 test_register_accepts_normal_username
        与 length 断言）。本用例的 bad 值刻意全部落在 4-20 字符内。
        """
        assert 4 <= len(bad) <= 20, f"用例自身失效：{bad!r} 长度 {len(bad)} 会被长度闸门拦下，测不到字符闸门"
        r = client.post("/api/auth/register", json={"username": bad, "password": "dn123456"})
        assert r.status_code == 400, f"username={bad!r} 得到 {r.status_code}：{r.get_json()}"
        assert auth.get_user_by_username(bad) is None, f"username={bad!r} 竟然建号成功"

    def test_register_accepts_normal_username(self, client):
        """对照行：正常 username 必须能注册。

        ⚠️ 这条同时钉住一个**曾被我自己写坏**的回归：不给 display_name 时
        （前端现状，绝大多数用户如此）走的是空值分支。我第一版让空值落进了
        下面的「目录占用」判据 —— join(root, "") == root，而爬取根目录必然非空
        （真实环境里有 ai/alice/alice2），于是空 display_name 被判成
        「该显示名对应的爬取目录里已有数据」，**把不带显示名的注册整体打死**。
        """
        r = client.post("/api/auth/register",
                        json={"username": "zhang.san", "password": "dn123456"})
        assert r.status_code == 200, f"正常 username 被误伤：{r.status_code} {r.get_json()}"

    def test_empty_display_name_is_legal(self, client):
        """承重：空 display_name 是**合法输入**（语义 = 回退到 username）。

        上面那条也能挡住这个回归，但那只是因为 zhang.san 恰好没传 display_name；
        这条直接把「空值」当被测对象，并断言它不参与目录占用判定。
        """
        assert auth.directory_name_error(None, "empty_dn_user", "") is None, "空 display_name 被判为非法"
        assert auth.directory_name_error(None, "empty_dn_user", "   ".strip()) is None
        r = client.post("/api/auth/register", json={
            "username": "empty_dn_user", "password": "dn123456", "display_name": ""})
        assert r.status_code == 200, f"空 display_name 被误伤：{r.status_code} {r.get_json()}"

    def test_profile_rejects_traversal_display_name(self, client, scrape_dirs):
        """承重：PUT /api/auth/profile 改 display_name 为越界串 ⇒ 400。"""
        h, _ = _create_user(client, "_dn_prof")
        r = client.put("/api/auth/profile", json={"display_name": "..\\..\\_dn_e\\pwn"}, headers=h)
        assert r.status_code == 400, f"越界 display_name 被接受：{r.status_code} {r.get_json()}"
        assert auth.get_user_by_id(_uid_of("_dn_prof"))["display_name"] != "..\\..\\_dn_e\\pwn"

    def test_profile_accepts_normal_display_name(self, client):
        """对照行：正常 display_name 必须改得动（否则上一条把改名整体禁掉也能全绿）。"""
        h, _ = _create_user(client, "_dn_prof2")
        r = client.put("/api/auth/profile", json={"display_name": "_dn_prof2_new"}, headers=h)
        assert r.status_code == 200, f"正常 display_name 被拒：{r.status_code} {r.get_json()}"
        assert auth.get_user_by_id(_uid_of("_dn_prof2"))["display_name"] == "_dn_prof2_new"

    def test_profile_rejects_duplicate_effective_directory_name(self, client):
        """承重：判重必须比**解析后的目录名**，不能只比 display_name 这一列。

        本用例就是那条会漏掉的情形：`_dn_dup_a` 注册时 display_name 是**空的**，
        它的目录名来自 **username**。于是 bob 把 display_name 设成
        `_dn_dup_a` 时，两人在 display_name 列上并不重名（a 那列是空的），
        目录名却都是 `_dn_dup_a` —— 两条目录名判据里，
        「只比列」的版本会放行，bob 就白拿了 a 的目录（= 本轮最初那个 HIGH 越权）。

        ⚠️ 这条不是因为「display_name 重名」而红，是因为「解析后的目录名重名」。
        """
        _create_user(client, "_dn_dup_a")
        hb, _ = _create_user(client, "_dn_dup_b")
        r = client.put("/api/auth/profile", json={"display_name": "_dn_dup_a"}, headers=hb)
        assert r.status_code == 400, (
            f"bob 拿到了 a 的目录名（判重只比了 display_name 列）：{r.status_code} {r.get_json()}"
        )

    def test_profile_rejects_occupied_directory(self, client):
        """承重：目标目录里已有**别人的产物** ⇒ 400。

        这条是「只做字符 + 唯一性」挡不住的那类：无主目录的冒名接管 ——
        用户被删了但 temp/scraped_images/<名字>/ 还在，新用户取同一个名字，
        就白拿了别人残留的产物。
        """
        occupied = os.path.join(_SCRAPE_DEFAULT_DIR, "_dn_occupied")
        os.makedirs(occupied, exist_ok=True)
        with open(os.path.join(occupied, "stale.png"), "wb") as f:
            f.write(b"\x89PNG\r\n\x1a\n" + b"S" * 16)
        try:
            h, _ = _create_user(client, "_dn_taker")
            r = client.put("/api/auth/profile", json={"display_name": "_dn_occupied"}, headers=h)
            assert r.status_code == 400, f"占用他人残留目录被放行：{r.status_code} {r.get_json()}"
        finally:
            shutil.rmtree(occupied, ignore_errors=True)

    def test_trailing_dot_display_name_rejected(self, client):
        """承重：**尾部点**必须单独挡住 —— 它是唯一挡得住这条的规则。

        Windows 上目录名的尾部点会被静默剥掉（前提由下面
        TestWindowsPathNormalisation 单独钉住）。于是 display_name = `alice.`
        会把 bob 的产物写进 **alice 的目录**，而：
          · 字符串判重看不出（`"alice." != "alice"`）——判的是字符串；
          · `_is_within(realpath(root/"alice."), root)` 也是 True
            （realpath 归一化后就在根内，**不算逃逸**）；
          · 目录占用判据只在目标**已有内容**时才拦得住 —— alice 还没爬过就拦不住。
        ⚠️ 这不是路径穿越：`alice.` 里没有一个 `..`，全是合法字符。

        ⚠️ 本用例刻意**不预建 alice 的目录**：一旦建了，「目录占用」判据就会
        先把它拦下，用例就变成在测占用判据、测不到点规则（实测踩过这个坑）。
        不建目录时，唯一能拦下它的就是点规则本身。

        变异验证：拆掉 `_fs_name_error` 的「首尾点」规则，本条**唯一**转红。
        """
        _create_user(client, "_dtd_alice")
        hb, _ = _create_user(client, "_dtd_bob")
        r = client.put("/api/auth/profile", json={"display_name": "_dtd_alice."}, headers=hb)
        assert r.status_code == 400, (
            f"`_dtd_alice.` 被接受 —— 尾部点在 Windows 上等价于 `_dtd_alice`，"
            f"bob 会写进 alice 的目录：{r.status_code} {r.get_json()}"
        )

    def test_inner_dot_display_name_still_works(self, client):
        """对照行：**中间**的点是正常字符，必须放行。

        没有这条，上面那条可以被「凡含点就拒」蒙过去 —— 而 ``zhang.san`` 这类
        名字在本仓库是真实存在的用户名形态。
        """
        h, _ = _create_user(client, "_dot_name")
        r = client.put("/api/auth/profile", json={"display_name": "zhang.san"}, headers=h)
        assert r.status_code == 200, f"中间带点的名字被误伤：{r.status_code} {r.get_json()}"

    def test_keeping_own_display_name_is_allowed(self, client, scrape_dirs):
        """对照行：改回**自己当前**的名字必须放行（目录非空但就是自己的）。

        没有这条，上一条可以被「只要目录非空就拒」蒙过去 —— 而那会让
        「保存资料时原样回传 display_name」这种常规操作直接报错。
        """
        h, _ = _create_user(client, "_dn_owner")
        client.put("/api/auth/profile", json={"display_name": "_dn_owner"}, headers=h)
        d = scrape_dirs("_dn_owner", "OwnPkg")
        assert os.listdir(d), "夹具没造出内容，用例前提不成立"
        r = client.put("/api/auth/profile", json={"display_name": "_dn_owner"}, headers=h)
        assert r.status_code == 200, f"改回自己的 display_name 被拒：{r.status_code} {r.get_json()}"


class TestJunctionEscape:
    """`_is_within(pkg_dir, save_dir)` 真正拦得住的场景。

    字符闸门对 join 逃逸已经完备（`C:` / `\\` / `/` 都含被拦字符），所以
    「包名里塞分隔符」那组用例**区分不出**这一层。这一层拦的是字符闸门
    **看不见**的逃逸：save_dir 下有个指向外部的 junction / symlink 目录时，
    pkg_name = `LinkPkg` 字符全合法、join 也毫无异常，只有 realpath 后
    才看得出已在 save_dir 之外。

    Windows 上 `mklink /J` 普通用户免提权，这就是它是真实场景而非理论推演的理由。
    不支持时（非 NTFS / 无权限 / 非 Windows）skip —— 宁可显式 skip，也不要
    写一条在 CI 上悄悄变成空断言的用例。
    """

    @pytest.fixture
    def junction(self):
        """造 junction 的工具。返回 (username, user_dir, outside, link)。

        ⚠️ 顺序有讲究：**必须先注册、后建目录**。目录名判据里有一条「目标目录
        已有内容 ⇒ 拒绝」，若先建目录再注册，注册本身就会被拦下，测不到 junction
        那一层（本类会变成在测别的东西）。
        """
        if not sys.platform.startswith("win"):
            pytest.skip("junction 是 Windows 专有（POSIX 上对应 symlink）")
        made = []

        def _build(client, username):
            bob, uid = _create_user(client, username)      # 先注册 —— 此时目录还不存在
            user_dir = os.path.join(_SCRAPE_DEFAULT_DIR, username)
            outside = os.path.join(_SCRAPE_DEFAULT_DIR, "..", "_jx_outside")
            link = os.path.join(user_dir, "LinkPkg")
            os.makedirs(user_dir, exist_ok=True)
            os.makedirs(outside, exist_ok=True)
            r = subprocess.run(["cmd", "/c", "mklink", "/J", link, os.path.abspath(outside)],
                               capture_output=True, text=True)
            if r.returncode != 0:
                pytest.skip(f"mklink /J 不可用：{r.stdout.strip()} {r.stderr.strip()}")
            made.append((user_dir, outside, link))
            return bob, user_dir, outside, link

        yield _build
        for user_dir, outside, link in made:
            # ⚠️ 必须用 rmdir 拆 junction —— rmtree 会**跟着链接进到目标目录**，
            # 把根外的东西一起删掉（这正是 junction 本身的危害，别在清理时重演）。
            if os.path.isdir(link):
                try:
                    os.rmdir(link)
                except OSError:
                    subprocess.run(["cmd", "/c", "rmdir", link], capture_output=True)
            shutil.rmtree(user_dir, ignore_errors=True)
            shutil.rmtree(outside, ignore_errors=True)

    def test_junction_package_dir_is_rejected(self, client, junction):
        """承重：pkg_name 指向根外 junction 时不得被放行。

        变异验证：把 `_is_within(pkg_dir, save_dir)` 那一行短路掉，本条（连同
        下面那条）会转红 —— 这就是「那一层是不是白写的」的答案。
        """
        bob, user_dir, outside, link = junction(client, "_jx_user")
        assert _is_inside_root(link) is False, "junction 没造到根外，用例前提不成立"

        r = client.post("/api/scrape",
                        json={"url": _play_url("LinkPkg"), "save_dir": user_dir}, headers=bob)
        assert r.status_code == 400, (
            f"pkg_name 经 junction 逃到根外却被放行：{r.status_code} {r.get_json()}"
        )
        assert "download_url" not in (r.get_json() or {}), "被拒的请求仍下发了 download_url"

    def test_junction_target_stays_empty(self, client, junction):
        """承重：断言**文件系统结果**，不只是状态码。

        只断言 400 的话，「返回 400 但已经把东西写进根外」仍会绿。
        """
        bob, user_dir, outside, link = junction(client, "_jx_user2")
        client.post("/api/scrape",
                    json={"url": _play_url("LinkPkg"), "save_dir": user_dir}, headers=bob)
        assert os.listdir(outside) == [], f"根外目录被写入了：{os.listdir(outside)}"

    def test_plain_package_in_same_dir_still_works(self, client, scrape_dirs):
        """对照行：同一个用户目录下，**非 junction** 的正常包名必须照常放行。

        没有这条，上面两条可以被「凡 save_dir 有子目录就 400」蒙过去。
        """
        bob, _ = _create_user(client, "_jx_user3")
        scrape_dirs("_jx_user3", "PlainPkg")
        r = client.post("/api/scrape",
                        json={"url": _play_url("PlainPkg"),
                              "save_dir": _save_dir_of("_jx_user3")}, headers=bob)
        assert r.status_code == 200, f"正常包名被误伤：{r.status_code} {r.get_json()}"


class TestWindowsPathNormalisation:
    """钉住「尾部点被静默剥掉」这个**文件系统事实**。

    单独成类而不是塞进上面那条策略用例里，原因：这个前提需要目录**已经存在**
    才能用 realpath 演示；而策略用例一旦预建目录，占用判据就会先拦下 ——
    两者互相干扰（实测踩过）。分开后，这里的断言若哪天失效，
    会明确告诉我们「点规则的立论过期了」，而不是让策略用例变成假绿。
    """

    def test_trailing_dot_and_space_collapse(self, tmp_path):
        if not sys.platform.startswith("win"):
            pytest.skip("尾部点折叠是 Windows 行为（POSIX 上 `alice.` 是另一个目录）")
        real = tmp_path / "alice"
        real.mkdir()
        (real / "existing.png").write_bytes(b"x")

        for variant in ("alice.", "alice "):
            probe = tmp_path / variant
            assert os.path.realpath(probe) == os.path.realpath(real), (
                f"{variant!r} 不再折叠到 'alice' —— 尾部点/空格规则的立论需要重新评估"
            )
        # 往 "alice." 里写文件，必须真的落在 alice/ 里
        (tmp_path / "alice." / "bob.png").write_bytes(b"y")
        assert "bob.png" in os.listdir(real), "写入 `alice./` 没落到 `alice/`"


class TestScrapeRootIsSingleSourceOfTruth:
    def test_auth_root_matches_main_default(self):
        """钉死 auth._scrape_root() 与 main._SCRAPE_DEFAULT_DIR 是同一个目录。

        auth 侧独立推导一次路径（与 database.py 的 _db_path() 同一惯例），
        这是**必要**的 —— 但两份独立推导会漂移，所以必须有一条断言钉住。
        一旦哪天 _SCRAPE_DEFAULT_DIR 换了位置而 auth 没跟上，
        display_name 的「目录占用」判据就会看着一个空目录，静默失效。
        """
        assert os.path.realpath(auth._scrape_root()) == os.path.realpath(_SCRAPE_DEFAULT_DIR), (
            f"auth._scrape_root()={auth._scrape_root()!r} 与 "
            f"main._SCRAPE_DEFAULT_DIR={_SCRAPE_DEFAULT_DIR!r} 不是同一个目录"
        )


class TestEffectiveDnMatchesScrapeDnFor:
    """`auth._effective_dn` 与 `main._scrape_dn_for` 的解析规则必须一致。

    第三个同源点是 `database.py` 里 `users.scrape_dn` 生成列的表达式（DB 唯一
    约束按它建索引）。三者任一漂移，都会让「DB 唯一约束挡住的」与「应用层判定
    的」不再是同一件事 —— 要么 DB 放行而应用层当成别人的目录，要么反过来。

    ⚠️ `auth._effective_dn` 的 docstring 与 `database.py` 的注释此前都声称
    「由 test_scrape_ownership.py 的 TestEffectiveDnMatchesScrapeDnFor 钉住」，
    而**该类当时并不存在**（code-review 第 3 轮指出：注释在撒谎）。
    本类就是补上的那条断言。

    两函数**刻意**有一处不同：`_effective_dn` 不含 `user_<id>` 兜底（它要回答
    「解析出的名字是什么」），`_scrape_dn_for` 在解析为空时退化为 `user_<id>`
    （它要回答「用哪个目录」）。所以断言分两支写，而不是简单相等。
    """

    CASES = [
        # (username, display_name, _effective_dn 的期望值)
        ("alice", "Alice 显示名", "Alice 显示名"),    # display_name 优先
        ("alice", "", "alice"),                      # 空 display_name → 回退 username
        ("alice", None, "alice"),
        ("alice", "   ", ""),                        # 纯空白 → 解析为空（不是回退 username！
                                                     # 这正是本轮踩过的坑：以为会回退）
        ("  padded  ", "  trimmed  ", "trimmed"),    # 两侧都 strip
        ("alice", "zhang.san", "zhang.san"),         # 中间的点是正常字符
    ]

    @pytest.mark.parametrize("username,display_name,expected", CASES)
    def test_effective_dn(self, username, display_name, expected):
        assert auth._effective_dn(username, display_name) == expected

    @pytest.mark.parametrize("username,display_name,expected", CASES)
    def test_scrape_dn_for_only_adds_fallback_when_empty(self, username, display_name, expected):
        """非空时必须逐字相同；为空时必须落进 `user_<id>` 兜底。"""
        user = {"display_name": display_name, "username": username, "role": "user"}
        got = _scrape_dn_for(user, 7)
        if expected:
            assert got == expected, f"_scrape_dn_for 与 _effective_dn 漂移：{got!r} != {expected!r}"
        else:
            assert got == "user_7", f"空解析结果必须退化为 user_<id>，实际 {got!r}"


class TestDirectoryNameCaseInsensitiveCollision:
    """H1（code-review 第 3 轮）：`alice` 与 `ALICE` 在 NTFS 上是**同一个目录**。

    加固前，「他人目录名」是直接做**字符串比较**的，于是 bob 认领 `ALICE` 被判为
    不重名 —— 而 `os.path.realpath` 只在目标**已存在**时才把大小写折到磁盘真值，
    「目录不存在」这一档因此漏检。

    那一档不是边角情况：每周清理会 rmtree 整个爬取根再重建，那一瞬间**全库**都
    落进「目录不存在」，窗口每周重开。这就是最高危的那条腿。

    实测（加固前基线）：`os.path.samefile(root/"ALICE", root/"alice")` 为 True，
    透过大写路径读得到 alice 的 secret.png，写入也落进 alice 目录。
    """

    def _fs_folds_case(self, root):
        """前提：本文件系统确实认为 `ALICE` 与 `alice` 是同一目录。"""
        real = os.path.join(root, "_ci_probe_a")
        os.makedirs(real, exist_ok=True)
        try:
            return os.path.realpath(os.path.join(root, "_CI_PROBE_A")) == os.path.realpath(real)
        finally:
            shutil.rmtree(real, ignore_errors=True)

    def test_dir_missing_window_is_closed(self, client, scrape_dirs):
        """目录**不存在**那一档 —— 加固前正是它漏检。

        `_ci_alice` 的目录刻意**不预建**：realpath 折叠不了不存在的路径，
        所以这一档只能靠大小写归一拦住，靠「目录占用」是拦不住的。
        """
        if not self._fs_folds_case(_SCRAPE_DEFAULT_DIR):
            pytest.skip("本文件系统区分大小写，H1 的立论不适用")
        _create_user(client, "_ci_alice")
        hb, _ = _create_user(client, "_ci_bob")
        r = client.put("/api/auth/profile", json={"display_name": "_CI_ALICE"}, headers=hb)
        assert r.status_code == 400, (
            f"`_CI_ALICE` 与 alice 的目录 `_ci_alice` 在 NTFS 上是同一个 —— "
            f"bob 白拿了 alice 的目录：{r.status_code} {r.get_json()}"
        )

    def test_dir_exists_but_empty_window_is_closed(self, client):
        """目录存在但**为空**那一档。

        空目录同样要拒：否则攻击者可以「先占名、等对方产出再共享」。
        """
        if not self._fs_folds_case(_SCRAPE_DEFAULT_DIR):
            pytest.skip("本文件系统区分大小写")
        d = os.path.join(_SCRAPE_DEFAULT_DIR, "_ci_empty")
        os.makedirs(d, exist_ok=True)          # 刻意不写任何文件
        try:
            hb, _ = _create_user(client, "_ci_taker")
            r = client.put("/api/auth/profile", json={"display_name": "_CI_EMPTY"}, headers=hb)
            assert r.status_code == 400, (
                f"空目录档漏检：{r.status_code} {r.get_json()}"
            )
        finally:
            shutil.rmtree(d, ignore_errors=True)

    def test_unowned_leftover_dir_case_variant_is_rejected(self, client):
        """无主残留目录（用户已删、目录还在）的大小写变体。

        与 `test_profile_rejects_occupied_directory` 是同一类，但换成大小写变体
        —— 后者测的是「字符串完全相同」，覆盖不到 H1 这条腿。
        """
        if not self._fs_folds_case(_SCRAPE_DEFAULT_DIR):
            pytest.skip("本文件系统区分大小写")
        d = os.path.join(_SCRAPE_DEFAULT_DIR, "_ci_leftover")
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, "stale.png"), "wb") as f:
            f.write(b"\x89PNG\r\n\x1a\n" + b"S" * 16)
        try:
            hb, _ = _create_user(client, "_ci_newcomer")
            r = client.put("/api/auth/profile", json={"display_name": "_CI_LEFTOVER"}, headers=hb)
            assert r.status_code == 400, f"接管无主目录的大小写变体被放行：{r.status_code}"
        finally:
            shutil.rmtree(d, ignore_errors=True)

    def test_case_insensitive_self_rename_is_allowed(self, client):
        """对照行：把自己 display_name 只改大小写，必须放行。

        没有这条，上面三条可以被「凡大小写不同就拒」蒙过去 —— 而那只改大小写的
        改名是常规操作，且 b 自己就是该目录的主人。
        """
        _create_user(client, "_ci_self")
        h, _ = _create_user(client, "_ci_self2")
        # 先设成小写，再只改大小写
        assert client.put("/api/auth/profile", json={"display_name": "_ci_self3"},
                          headers=h).status_code == 200
        r = client.put("/api/auth/profile", json={"display_name": "_CI_SELF3"}, headers=h)
        assert r.status_code == 200, f"只改自己名字的大小写被误伤：{r.status_code} {r.get_json()}"


class TestConcurrentDuplicateDirectoryName:
    """H2（code-review 第 3 轮）：`directory_name_error` 是 check-then-act，非原子。

    它是「读快照 → 判断 → INSERT」三步，Python 里**天生**无法原子。8 个线程都在
    彼此 INSERT 之前读完快照，于是全部放行 —— 加固前实测 8/8 全部落库同名，
    而目录名相同 = 8 个人共用一个爬取目录（= H1 那个越权，换个入口）。

    应用层修不动这一点（加锁只护得住单进程，而这是多线程/多进程服务），
    所以原子性交给 DB：`users.scrape_dn` 上有唯一索引。本类钉住那个兜底。
    """

    N = 8

    def test_only_one_of_n_concurrent_registrations_succeeds(self, client):
        """走 `auth.create_user` 这条**真实写路径**，不是直接 INSERT。

        直接 INSERT 会绕过应用层闸门，就测不出「闸门全放行、DB 兜住」这个组合
        —— 而那个组合正是这条缺陷的形态。
        """
        # 先在**主线程**把库预热到**稳态**，再放线程。
        #
        # 为什么需要两次：`_ensure_columns`（第 53 行起）**每次连库都跑**，其中的
        # `_add_column_if_missing` 是**无锁**的「PRAGMA 查列 → ALTER ADD」；
        # 而 `_cleanup_old_option_columns` 会把 `products.sales_person` **DROP** 掉。
        # 于是新库上的调用序列是「加列 → 被删 → 下次连库再加回来」：
        #   · 第 1 次 get_db()：建表 → 加 sales_person → cleanup 删掉它并置标记
        #   · 恰好停在这里就放线程，8 个线程会**同时**去 ALTER ADD 这个已不存在的列
        #     → 1 个成功、7 个 `duplicate column name: sales_person`（实测踩到）
        #   · 第 2 次 get_db()：cleanup 已置标记不再删，列被加回并**留下**
        #     → 后续所有连接只做 PRAGMA 读、不 ALTER → 无竞态
        # 稳态这一点与真实库一致（实测 temp/app.db 里 products.sales_person 存在）。
        #
        # ⚠️ 那个迁移竞态是一个**独立的、先于本轮存在的**缺陷（`_ensure_schema` 有
        # `_schema_lock` 双检锁，`_ensure_columns` 没有），不在本用例射程内，
        # 已单独记录待裁定。此处只是把它隔离出去，**不是掩盖** —— 下面的断言
        # 会把「预热是否真的到了稳态」显式钉住，前提一旦失效本用例会直接报出来。
        database.get_db().close()
        database.get_db().close()
        _db = database.get_db()
        try:
            _cols = [r[1] for r in _db.execute("PRAGMA table_info(products)")]
        finally:
            _db.close()
        assert "sales_person" in _cols, (
            "预热没到稳态：products.sales_person 仍缺席，_ensure_columns 会在"
            "并发连接里 ALTER，把本用例的观测污染成「线程被迁移异常打死」"
        )

        outcomes = {"created": 0, "rejected": 0, "error": []}
        lock = threading.Lock()

        def _reg(i):
            try:
                r = auth.create_user(username=f"_conc_{i}", password="test123",
                                     role="user", display_name="_conc_same")
            except Exception as e:                       # noqa: BLE001 - 见下
                # 刻意宽捕获：本用例要断言的是"没有一个线程死于意外异常"。
                # 只 catch IntegrityError 的话，其它异常会让线程静默死掉、
                # 计数对不上，测试反而可能变绿（假绿）。
                with lock:
                    outcomes["error"].append(f"{type(e).__name__}: {e}")
                return
            with lock:
                outcomes["created" if r else "rejected"] += 1

        threads = [threading.Thread(target=_reg, args=(i,)) for i in range(self.N)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert outcomes["error"] == [], f"线程死于意外异常：{outcomes['error']}"
        assert outcomes["created"] + outcomes["rejected"] == self.N, (
            f"分档计数对不上：{outcomes}"
        )
        assert outcomes["created"] == 1, (
            f"并发注册同名 display_name 应只成功 1 个，实际 {outcomes['created']} 个"
        )
        assert outcomes["rejected"] == self.N - 1, (
            f"应恰好 {self.N - 1} 个被挡回，实际 {outcomes['rejected']} 个"
        )
        # 落库侧核对：唯一索引在，且库里确实只有一行占着这个名字
        db = database.get_db()
        try:
            n = db.execute("SELECT COUNT(*) FROM users WHERE scrape_dn = ?",
                           ("_conc_same",)).fetchone()[0]
        finally:
            db.close()
        assert n == 1, f"DB 里同目录名的行数为 {n}，唯一约束没生效"

    def test_sequential_duplicate_is_rejected_by_gate(self, client):
        """对照行：**顺序**重复必须由应用层闸门拒（返回 None），而非靠 DB 抛异常。

        没有这条，上一条可以被「唯一索引在，但应用层闸门整个坏了」蒙过去 ——
        那时用户拿到的是一个 500 而不是干净的「名字重复」提示。

        ⚠️ 只断言 `create_user(...) is None` 本身是**假绿**：闸门整个坏掉时
        返回值**一模一样** —— 闸门放行 → INSERT 撞唯一索引 → IntegrityError
        被 create_user 吞掉 → 同样 return None。两条路径在返回值上无从区分
        （code-review 第 3 轮指出，且本类正是为此而设）。故拆成两腿：先直接
        问闸门要**具体文案**（钉「闸门拦住」这一腿），再走整体写路径。
        """
        assert auth.create_user(username="_seq_a", password="test123",
                                role="user", display_name="_seq_same") is not None
        # 腿一：闸门必须给出**判据 2 的原文案**。DB 唯一索引抛的是
        # IntegrityError、给不出这句话 —— 故这条能把两条路径真正区分开。
        assert auth.directory_name_error(
            None, "_seq_b", "_seq_same"
        ) == "该名字会与其他用户的爬取目录重名，请换一个"
        # 腿二：整体写路径仍然干净地返回 None（结果侧不变，但已非唯一证据）
        assert auth.create_user(username="_seq_b", password="test123",
                                role="user", display_name="_seq_same") is None


def _seed_raw_user(username, display_name, role="user", platform="gg"):
    """直接 INSERT 一行 users，返回 id。

    刻意**绕过** auth.create_user：本类要测的是「库里已经存在某个 display_name
    取值时，Python 侧与 DB 生成列解析出的键是否相同」，走关口会被 strip 掉，
    就测不到原始取值了。
    """
    db = database.get_db()
    try:
        cur = db.execute(
            "INSERT INTO users (username, password, role, display_name, platform) "
            "VALUES (?,?,?,?,?)",
            (username, "x", role, display_name, platform),
        )
        db.commit()
        return cur.lastrowid
    finally:
        db.close()


class TestDbGeneratedColumnMatchesPython:
    """钉住 `users.scrape_dn`（DB 生成列）与 Python 侧目录名解析**同键**。

    ⚠️ `database.py` 的注释声称「解析规则一致性由 test_scrape_ownership.py 的
    `TestEffectiveDnMatchesScrapeDnFor` 钉住」—— 但那个类只比了
    `auth._effective_dn` 与 `main._scrape_dn_for` 两个 **Python** 函数，
    **完全没碰 DB 生成列**。注释在撒谎（第三次同类问题）。
    本类才是钉 DB 那一腿的。

    为什么必须同键：H2 把并发的原子性交给了 DB 唯一索引，而索引建在 `scrape_dn`
    上、应用层闸门判的是 `_scrape_dn_for`。两者若不同键，「DB 兜底」保护的就是
    另一个键 —— H2 的核心保证会**静默失效**。
    """

    @pytest.mark.parametrize("username,display_name", [
        ("dbe_a", "有名字"),
        ("dbe_b", ""),
        ("dbe_c", None),
        ("dbe_d", "zhang.san"),
        ("dbe_e", " 首尾有空白 "),      # 会被 strip 掉首尾
    ])
    def test_same_key(self, client, username, display_name):
        uid = _seed_raw_user(username, display_name)
        db = database.get_db()
        try:
            got_db = db.execute("SELECT scrape_dn FROM users WHERE id=?", (uid,)).fetchone()[0]
        finally:
            db.close()
        user = {"display_name": display_name, "username": username, "role": "user"}
        got_py = _scrape_dn_for(user, uid)
        assert got_py == got_db, (
            f"Python 与 DB 的目录名解析已漂移：_scrape_dn_for={got_py!r} "
            f"vs scrape_dn={got_db!r}（display_name={display_name!r}）"
        )

    def test_whitespace_only_display_name_is_a_known_divergence(self, client):
        """⚠️ **已知差异**（本轮发现，未修）：`display_name` 为纯空白非空串时两边不同键。

        · Python `_scrape_dn_for`：`(display_name or username or "").strip()` ——
          `"   "` 是 **truthy**，故**不回退 username**；strip 后成空串 ⇒ 落进 `user_<id>`
        · DB 生成列：`NULLIF(TRIM(display_name), '')` ⇒ TRIM 后为空 ⇒ **回退 username**

        即 Python 是「先判 falsy 再 strip」，DB 是「先 TRIM 再判空」，**求值顺序不同**。

        影响：这一档下应用层闸门与 DB 唯一索引判的**不是同一个键**。
        方向是安全的（fail-closed）—— 攻击者取 `display_name` = 某人的 `username`
        时，应用层**放行**（它以为那个人的目录是 `user_<id>`），但 DB 生成列会撞上
        ⇒ `IntegrityError` ⇒ 拒绝。只会**误拒**，不会漏越权。

        当前**不可触发**：`create_user` / `update_user` 都已 strip，新数据产生不了
        `"   "`；真实库 33 行逐行核对也无此值（实测 0 不一致）。

        本条只把差异**记录**下来，防止哪天变成静默的洞；顺带钉住
        「一边的语义被改了」这件事。修法未做 —— 改 Python 侧会改变既有目录名语义
        （`"   "` 的用户目录会从 `user_<id>` 变成 username），有产物「搬家」风险，
        且属改既有功能逻辑，需用户裁定。
        """
        uid = _seed_raw_user("_ws_only", "   ")
        db = database.get_db()
        try:
            got_db = db.execute("SELECT scrape_dn FROM users WHERE id=?", (uid,)).fetchone()[0]
        finally:
            db.close()
        user = {"display_name": "   ", "username": "_ws_only", "role": "user"}
        got_py = _scrape_dn_for(user, uid)

        assert got_py == f"user_{uid}", f"Python 侧语义变了：{got_py!r}"
        assert got_db == "_ws_only", f"DB 侧语义变了：{got_db!r}"
        assert got_py != got_db, (
            "两边居然一致了 —— 该已知差异已消失，请删掉本条用例与 database.py 里的相关注释"
        )
