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

    def test_rename_collision_returns_none_without_half_write(self, client, monkeypatch):
        """Important #4（code-review 第 5 轮）：并发**改名**撞唯一索引时逃逸为 500。

        形态：`auth.update_user` 的 `try/except sqlite3.IntegrityError` 原本**只包住
        `commit()`**，而 SQLite 在 **UPDATE 语句处**就抛（已独立复现）⇒ 该 except 是
        **死代码**，异常从 UPDATE 直接冒到 Flask ⇒ 500；路由对 `None` 的 400 处理本来
        就在，只是永远走不到。收口：把 try 上提到覆盖两条会动 `scrape_dn` 的 UPDATE。

        确定性复现（**不赌线程调度**）：把前置闸门换成「一律放行」，以模拟「闸门读到
        的是过期快照」这一竞态前提 —— `directory_name_error` 本就是 check-then-act、
        天生非原子。再让两个用户的目录名收敛到同一个值 ⇒ 第二条 UPDATE 撞
        `idx_users_scrape_dn`。修复前异常从这里冒出，本用例在 assert 处就报
        IntegrityError；修复后返回 None（路由 400）。
        """
        _h1, uid1 = _create_user(client, "_cr_a")
        _h2, uid2 = _create_user(client, "_cr_b")
        monkeypatch.setattr(auth, "directory_name_error", lambda *a, **k: None)

        assert auth.update_user(uid1, display_name="_cr_same") is not None, (
            "第一条不该失败（此时无人占用 _cr_same）"
        )
        # 第二条：闸门被绕过，只剩 DB 唯一索引这道兜底 —— 必须**返回 None**，不得抛出
        assert auth.update_user(uid2, display_name="_cr_same") is None

        # 回滚必须干净：失败的那次不能留下半写状态（username/display_name 都没变）
        assert auth.get_user_by_id(uid1)["display_name"] == "_cr_same"
        assert auth.get_user_by_id(uid2)["display_name"] == "", (
            f"失败的改名留下了半写状态：{auth.get_user_by_id(uid2)['display_name']!r}"
        )

    def test_concurrent_renames_to_same_name_never_500(self, app, monkeypatch):
        """同一竞态的**端到端**腿：走真实路由（`PUT /api/auth/profile`）并发改名，
        断言「恰好 1 个 200、其余 400、**没有任何 5xx**」。

        ⚠️ 闸门在此**刻意**换成一律放行：否则线程可能被前置闸门逐个挡住（那也不会有
        IntegrityError），断言「没有 5xx」就成了**空气** —— 修复前后一样绿。
        放开闸门才能保证每个线程都真的走到 UPDATE 那一行。
        """
        n = 6
        heads = [_create_user(app.test_client(), f"_crn_{i}")[0] for i in range(n)]
        monkeypatch.setattr(auth, "directory_name_error", lambda *a, **k: None)

        codes = []
        lock = threading.Lock()

        def _rename(h):
            c = app.test_client()
            r = c.put("/api/auth/profile", json={"display_name": "_crn_same"}, headers=h)
            with lock:
                codes.append(r.status_code)

        threads = [threading.Thread(target=_rename, args=(h,)) for h in heads]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(codes) == n, f"有线程没跑完：{codes}"
        assert not [c for c in codes if c >= 500], (
            f"并发改名有请求逃逸为 5xx（唯一索引冲突没被接住）：{sorted(codes)}"
        )
        assert codes.count(200) == 1, (
            f"应恰好 1 个成功（DB 唯一索引兜底），实际 {sorted(codes)}"
        )
        assert codes.count(400) == n - 1, (
            f"其余应干净地 400，实际 {sorted(codes)}"
        )


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


def _token_for(uid):
    """直接为该 uid 签一个 access_token。

    刻意不走 `/api/auth/login`：本文件下文的存量用户是**闸门上线前**的形态
    （`username` 非法），注册接口根本造不出来，只能用 `_seed_raw_user` 直接
    INSERT，而它的 password 是占位串、登录不了。
    """
    from flask_jwt_extended import create_access_token
    from main import app as _app
    with _app.app_context():
        return {"Authorization": f"Bearer {create_access_token(identity=str(uid))}"}


class TestFormerDirectoryNameIsReclaimable:
    """MEDIUM-1（code-review 第 3 轮）：改回**自己的曾用显示名**被自己的旧目录锁死。

    形态（`_probe_hist_dn.py` 曾独立复现，本类把它收编为正式用例）：
      1. 显示名设为 `老王`，爬取产物落在 `temp/scraped_images/老王/`
      2. 改名 `老李` ⇒ 目录名变成 `老李`，`老王` 目录**原封不动留在磁盘上**
      3. 想改回 `老王` ⇒ 判据 3 看到磁盘上存在 `老王`，而它不在 own_keys 里
         ⇒ 400「该名字对应的爬取目录已被占用，请换一个」

    即用户在 `老王` 目录里的全部产物**永远访问不到**了，且没有恢复路径。
    修法：`users.prev_scrape_dns` 记录曾用目录名，判据 3 把它算作「我的」。

    本类必须**成对**存在 —— 只测「能改回去」而不同时钉住「别人仍然抢不走」，
    就等于用「放宽」冒充修复，把判据 3 的无主目录保护一起丢掉。
    """

    def test_rename_back_to_own_former_name_succeeds(self, client, scrape_dirs):
        h, uid = _create_user(client, "_hist_a")
        root = _SCRAPE_DEFAULT_DIR

        # 1) 显示名 = 曾用名，并在该目录下造出产物
        r1 = client.put("/api/auth/profile", json={"display_name": "_hist_old_a"}, headers=h)
        assert r1.status_code == 200, f"设定显示名失败：{r1.status_code} {r1.get_json()}"
        scrape_dirs("_hist_old_a", "com.pkg.old")
        assert os.path.isdir(os.path.join(root, "_hist_old_a"))

        # 2) 改名 —— 旧目录**刻意不动**（这正是缺陷场景：产物留在旧目录里）
        r2 = client.put("/api/auth/profile", json={"display_name": "_hist_new_a"}, headers=h)
        assert r2.status_code == 200, f"改名失败：{r2.status_code} {r2.get_json()}"
        assert os.path.isdir(os.path.join(root, "_hist_old_a")), "旧目录应原封不动留着"

        # 3) 改回曾用名 —— 修复前这里是 400
        r3 = client.put("/api/auth/profile", json={"display_name": "_hist_old_a"}, headers=h)
        assert r3.status_code == 200, (
            f"改回自己的曾用显示名被拒：{r3.status_code} {r3.get_json()}"
        )

        # 用户可见结果：产物必须**真的又列得出来**了。
        # 只断言 200 属「断言过弱」—— 200 只说明闸门放行，而本缺陷的用户可见后果
        # 是「产物在盘上却列不出来」。少了这条，若哪天 dn 推导漂移导致 listdir 指向
        # 别处（闸门放行、列表仍空），本用例照样绿。
        pkgs = client.get("/api/scrape/packages", headers=h).get_json()["packages"]
        assert "com.pkg.old" in [p["name"] for p in pkgs], (
            f"改回曾用名后旧产物仍不可见，等于没修：{pkgs}"
        )

        # 落库侧核对：靠的确实是曾用名记录，而不是判据 3 整体失效。
        db = database.get_db()
        try:
            hist = [r[0] for r in db.execute(
                "SELECT dn FROM scrape_dn_history WHERE user_id = ?", (uid,)).fetchall()]
        finally:
            db.close()
        assert "_hist_old_a" in hist, (
            f"曾用名没落库，改回成功另有原因：scrape_dn_history={hist!r}"
        )

    def test_same_former_name_is_still_blocked_for_others(self, client, scrape_dirs):
        """对照行：曾用名只对**本人**开闸，别人抢同一目录仍被拒。

        没有这条，上一条可以被「判据 3 整个被拆掉」蒙过去 —— 那等于把「无主目录
        保护」一起丢了，而那正是判据 3 存在的理由（用户被删、目录还在）。
        """
        h_a, uid_a = _create_user(client, "_hist_b")
        h_b, uid_b = _create_user(client, "_hist_c")

        # A 用 _hist_mid 当显示名 → 造出产物 → 改名腾空这个名字
        assert client.put("/api/auth/profile", json={"display_name": "_hist_mid"},
                          headers=h_a).status_code == 200
        scrape_dirs("_hist_mid", "com.pkg.mid")
        assert client.put("/api/auth/profile", json={"display_name": "_hist_after"},
                          headers=h_a).status_code == 200

        # B 想取 A 的曾用名 —— 必须仍被拒
        r = client.put("/api/auth/profile", json={"display_name": "_hist_mid"}, headers=h_b)
        assert r.status_code == 400, (
            f"曾用名豁免漏给了别人：B 取 A 的曾用目录名返回 {r.status_code}"
        )
        # 闸门侧要**判据 3 的原文案**：钉住拒的原因是「目录占用」而不是别的判据
        # ——若只断言 400，判据 2 或字符闸门误伤也能蒙过去。
        assert auth.directory_name_error(uid_b, None, "_hist_mid") == (
            "该名字对应的爬取目录已被占用，请换一个"
        )

    def test_former_name_that_someone_else_also_used_is_not_reclaimable(self, client, scrape_dirs):
        """**曾用名豁免必须收窄**：这个名字若**别人也用过**，就不能凭「我曾用过」认领。

        反例（本次修复自己引入的形态，本用例先红后绿）：A 用过 `_lk_X` 后改名离开；
        B 随后也取 `_lk_X` 并在其下爬出产物，再改名离开 —— 此时目录 `_lk_X` 里装的是
        **B 的产物**，而 A 仅凭 `_lk_X` 在自己的曾用名列表里就能认领进来读到它。
        这等于把判据 3 的「目录占用」保护整条绕开，正是本轮要防的那类越权。

        判据：只有「除我之外**没有任何人**用过」的曾用名才算我的（目录里只可能有我的
        产物）。别人用过的名字一律退回**修复前**的行为（拒），fail-closed。
        """
        h_a, uid_a = _create_user(client, "_lk_a")
        h_b, uid_b = _create_user(client, "_lk_b")

        # 1) A 先占用 _lk_X（此时该目录还不存在，故判据 3 无目录可撞），再改名离开
        assert client.put("/api/auth/profile", json={"display_name": "_lk_X"},
                          headers=h_a).status_code == 200
        assert client.put("/api/auth/profile", json={"display_name": "_lk_Y"},
                          headers=h_a).status_code == 200

        # 2) B 也取 _lk_X，并在其下爬出产物 —— 目录里从此装的是 B 的东西
        assert client.put("/api/auth/profile", json={"display_name": "_lk_X"},
                          headers=h_b).status_code == 200
        scrape_dirs("_lk_X", "com.pkg.leak")

        # 3) B 再改名离开 —— 目录 _lk_X 连产物一起留在磁盘上
        assert client.put("/api/auth/profile", json={"display_name": "_lk_Z"},
                          headers=h_b).status_code == 200

        # 4) A 拿自己的曾用名 _lk_X 回来 —— 放行就等于让 A 读到 B 的产物
        r = client.put("/api/auth/profile", json={"display_name": "_lk_X"}, headers=h_a)
        assert r.status_code == 400, (
            f"曾用名豁免漏给了「别人也用过的名字」：A 认领 _lk_X 返回 {r.status_code}，"
            f"而该目录里装的是 B 的产物（该目录归 B 用过）"
        )
        assert auth.directory_name_error(uid_a, None, "_lk_X") == (
            "该名字对应的爬取目录已被占用，请换一个"
        )

    def test_comma_in_former_name_is_not_split(self, client, scrape_dirs):
        """承重：曾用名里的逗号**不得**被当成分隔符，拆出的子名不能变成我的曾用名。

        为什么需要这条：`_fs_name_error` 只挡路径分隔符/冒号/空字符与首尾的点、空白
        —— **名字中间允许逗号和换行**。若曾用名被拼进**任何**分隔符串（逗号、换行、
        JSON 之外的紧凑格式），曾用名 `_j_a,b` 会被读成 `["_j_a", "b"]`，`_j_a` 就平白
        成了「我的曾用名」。此时只要磁盘上存在一个 `_j_a` 目录（**别人的**残留，例如
        用户被删而目录还在），判据 3 的「目录占用」保护就会被绕开，我能读到它。

        ⚠️ 存储已在 2026-09-24 从 `users.prev_scrape_dns`（JSON 文本）换成
        `scrape_dn_history` 表（**一名字一行**），本用例的原始动因（JSON 序列化）随之
        消失；保留它是为了钉住「名字被当**不透明整串**处理」这一性质 —— 若哪天有人
        为了省事又把它拼回一个分隔符列，本用例会立刻转红。

        两条腿都必须踩在判据 3 上，各由相反方向承重：
          · 取回**完整**的 `_j_a,b` → 200：目录存在，只有「曾用名被原样保留为**一个**
            条目」能解释（退化成逗号拼接时，`_j_a,b` 根本不在拆出来的列表里）；
          · 取**拆出来**的 `_j_a`  → 400：证明它没有被拆成两条。
        """
        h, uid = _create_user(client, "_j_x")
        _create_user(client, "_j_y")          # 让 others 非空，不靠判据 2 空转兜底
        root = _SCRAPE_DEFAULT_DIR

        # 1) 显示名带逗号（合法值），随后两个目录都造出来 —— 两条腿都要撞判据 3
        assert client.put("/api/auth/profile", json={"display_name": "_j_a,b"},
                          headers=h).status_code == 200, "带逗号的显示名应是合法值"
        scrape_dirs("_j_a,b", "com.pkg.comma")
        scrape_dirs("_j_a", "com.pkg.orphan")

        # 2) 改名离开 —— 旧名进曾用名列表，目录原地不动
        assert client.put("/api/auth/profile", json={"display_name": "_j_away"},
                          headers=h).status_code == 200

        # 3) 腿一：完整的曾用名应能取回
        r_full = client.put("/api/auth/profile", json={"display_name": "_j_a,b"}, headers=h)
        assert r_full.status_code == 200, (
            f"带逗号的曾用名取不回，说明它没被原样保留："
            f"{r_full.status_code} {r_full.get_json()}"
        )

        # 4) 腿二：逗号不得当分隔符 —— 拆出的 `_j_a` 不是我的曾用名，必须仍被拒
        r_split = client.put("/api/auth/profile", json={"display_name": "_j_a"}, headers=h)
        assert r_split.status_code == 400, (
            f"曾用名里的逗号被当成分隔符拆开了：取 `_j_a` 返回 {r_split.status_code}，"
            f"而磁盘上的 `_j_a` 是别人的残留目录"
        )
        assert auth.directory_name_error(uid, None, "_j_a") == (
            "该名字对应的爬取目录已被占用，请换一个"
        )

class TestFormerNameBelongsToLastHolder:
    """Important #1（code-review 第 5 轮）：一个名字被 ≥2 人先后用过时，**最后持有者**
    也取不回自己的产物。

    形态（`temp/_probe_r5_verify.py` 独立复现）：
      1. P 占空闲名 N（目录还不存在 ⇒ 判据 3 无目录可撞），随即改名离开 —— N 进 P 的曾用名
      2. Q 合法接手 N（**这一放行本身就证明目录里没有 P 的产物**），产出后改名离开
      3. Q 想取回 N ⇒ 修复前被拒，而目录 `N` 里**只有 Q 自己的产物**

    用户可见后果与原缺陷（MEDIUM-1）完全一致：产物在盘上、应用内无恢复路径。
    修法：曾用名升级为**带全局序号的条目**（`scrape_dn_history.id`，跨用户单调），
    认领条件从「无他人用过」改为「我的释放序 > 所有他人的释放序」（last-writer-wins），
    同值一律拒 ⇒ 仍 fail-closed。最后持有者本就能读该目录（认领前它就在自己名下），
    故不新增任何暴露面。

    本类必须**成对**：只测「最后持有者能取回」而不钉住「先前持有者仍抢不走」，
    就等于用「谁用过谁就能认领」冒充修复，把「名字被多人用过 ⇒ 目录里可能是别人的
    产物」整条保护丢掉。
    """

    @staticmethod
    def _p_occupies_then_q_takes_over(client, scrape_dirs):
        """公共夹具：P 先用 N 后离开、Q 接手 N 并产出后离开；返回 h_p/uid_p/h_q/uid_q。

        ⚠️ 中间的每一步 status 都必须断言 —— 少了它，夹具可以因「某步悄悄失败」
        而把两条腿都测成空气（例如 Q 根本没接手成功，磁盘上就没有 Q 的产物）。
        """
        N = "_lw_N"
        h_p, uid_p = _create_user(client, "_lw_p")
        h_q, uid_q = _create_user(client, "_lw_q")

        # 1) P 先占 N（目录不存在）再改名离开 —— N 进 P 的曾用名，盘上无 P 的产物
        r = client.put("/api/auth/profile", json={"display_name": N}, headers=h_p)
        assert r.status_code == 200, f"P 占用空闲名失败：{r.status_code} {r.get_json()}"
        r = client.put("/api/auth/profile", json={"display_name": "_lw_Pout"}, headers=h_p)
        assert r.status_code == 200, f"P 改名离开失败：{r.status_code} {r.get_json()}"

        # 2) Q 合法接手 N（若目录里有 P 的产物，判据 3 会在这里就拒掉），产出后离开
        r = client.put("/api/auth/profile", json={"display_name": N}, headers=h_q)
        assert r.status_code == 200, (
            f"Q 接手空闲名失败（夹具前提不成立：目录里已有别人的东西）："
            f"{r.status_code} {r.get_json()}"
        )
        scrape_dirs(N, "com.pkg.lw")
        r = client.put("/api/auth/profile", json={"display_name": "_lw_Qout"}, headers=h_q)
        assert r.status_code == 200, f"Q 改名离开失败：{r.status_code} {r.get_json()}"
        return h_p, uid_p, h_q, uid_q

    def test_last_holder_reclaims_own_former_name(self, client, scrape_dirs):
        h_p, _uid_p, h_q, _uid_q = self._p_occupies_then_q_takes_over(client, scrape_dirs)

        # Q 取回 N —— 目录里**只有 Q 自己的产物**，修复前这里是 400
        r = client.put("/api/auth/profile", json={"display_name": "_lw_N"}, headers=h_q)
        assert r.status_code == 200, (
            f"最后持有者取不回自己的产物目录：Q 认领 _lw_N 返回 {r.status_code} "
            f"{r.get_json()}"
        )

        # 用户可见结果：产物必须**真的又列得出来**了（200 只说明闸门放行）
        pkgs = client.get("/api/scrape/packages", headers=h_q).get_json()["packages"]
        assert "com.pkg.lw" in [p["name"] for p in pkgs], (
            f"取回曾用名后产物仍不可见，等于没修：{pkgs}"
        )
        # ⚠️ 此处**不**再断言「P 也被拒」：Q 取回成功后它自己就占着 `_lw_N`，
        # P 的检查会先撞判据 2（与他人**当前**目录名重名）而不是判据 3，断言会
        # 测到另一条路径上。反方向由下一条测试在「Q 已离开」的夹具下发声。

    def test_earlier_holder_still_cannot_reclaim(self, client, scrape_dirs):
        """对照行：名字的最后持有者不是**先**用过的那个人 ⇒ 先前持有者仍被拒。

        与上一条共用同一夹具，只把「谁来认领」换成人，两条腿放行/拒绝相反。
        没有这条，实现退化成「谁用过谁就能认领」时上一条照样绿。
        """
        h_p, uid_p, _h_q, _uid_q = self._p_occupies_then_q_takes_over(client, scrape_dirs)

        # P（先前持有者）取回 N —— 目录里是 **Q 的产物**，必须拒
        r = client.put("/api/auth/profile", json={"display_name": "_lw_N"}, headers=h_p)
        assert r.status_code == 400, (
            f"先前持有者抢到了后来者的产物目录：P 认领 _lw_N 返回 {r.status_code}，"
            f"而该目录里装的是 Q 的产物"
        )
        assert auth.directory_name_error(uid_p, None, "_lw_N") == (
            "该名字对应的爬取目录已被占用，请换一个"
        )


class TestDeletedUserDirectoryIsTombstoned:
    """Important #2（code-review 第 5 轮）：被删用户的爬取目录可被「曾用名含该名」的人认领。

    **这一档是我这次改动引入的回归**（`temp/_probe_r5_verify.py` 独立复现）：
    修复前根本没有曾用名豁免，判据 3 见到盘上存在 `_tb_D` 而它不在 own_keys 里就拒；
    加了「我历史上用过就算我的」之后，被删的用户连行都没有了 ⇒ 他的名字在
    `others_keys` 里凭空消失 ⇒ 曾用名含该名的人被放行，读到**被删用户**的产物。
    按纯增量原则（不得让新增功能使既有保护失效）必须收口。

    形态：
      1. M 用过 `_tb_D` 后改名离开 ⇒ `_tb_D` 进 M 的曾用名
      2. V 合法接手 `_tb_D` 并在其下产出
      3. 删掉 V —— `admin_delete_user` **不删爬取目录**，产物仍在盘上
      4. M 拿曾用名 `_tb_D` 回来 ⇒ 判据 2 已看不见 V ⇒ **放行**，M 读到 V 的产物

    修法（用户裁定）：删用户时把其**当前目录名**记入 `scrape_dn_history` 作墓碑 ——
    该表刻意**无外键**，行随用户删除而存活；在 last-writer-wins 规则里它就是
    「最后释放该名的人」⇒ M 的释放序更小 ⇒ 拒。非破坏性：不动任何人的数据、
    不删任何目录，只把这一档退回「拒」。

    ⚠️ 代价（已知、刻意接受）：被删用户名下的名字对**其他人**永久关闭认领，即使
    那个目录里其实什么都没有。方向 fail-closed，且可由 admin 手工删墓碑行解除。
    """

    def test_directory_of_deleted_user_is_not_reclaimable(self, client, scrape_dirs):
        h_admin, _ = _create_user(client, "_tb_admin", role="admin")
        h_m, _uid_m = _create_user(client, "_tb_m")
        h_v, uid_v = _create_user(client, "_tb_v")

        # 1) M 用过 _tb_D 后改名离开 ⇒ _tb_D 进 M 的曾用名
        assert client.put("/api/auth/profile", json={"display_name": "_tb_D"},
                          headers=h_m).status_code == 200
        assert client.put("/api/auth/profile", json={"display_name": "_tb_Mout"},
                          headers=h_m).status_code == 200

        # 2) V 合法接手 _tb_D 并在其下产出
        assert client.put("/api/auth/profile", json={"display_name": "_tb_D"},
                          headers=h_v).status_code == 200, "V 接手失败，夹具前提不成立"
        scrape_dirs("_tb_D", "com.pkg.tomb")

        # 3) 删掉 V —— 目录连产物一起留在盘上（admin_delete_user 不删爬取目录）
        r = client.delete(f"/api/admin/users/{uid_v}", headers=h_admin)
        assert r.status_code == 200, f"删用户失败：{r.status_code} {r.get_json()}"
        # 前置断言：夹具必须保持「无主目录」形态，否则本用例测的是别的东西
        assert os.path.isdir(os.path.join(_SCRAPE_DEFAULT_DIR, "_tb_D")), (
            "夹具前提不成立：删用户竟把爬取目录一并删了，那就轮不到墓碑表出场"
        )

        # 4) M 拿曾用名回来 —— 必须退回「拒」，而不是因 V 的行没了就放行
        r = client.put("/api/auth/profile", json={"display_name": "_tb_D"}, headers=h_m)
        assert r.status_code == 400, (
            f"被删用户的目录被曾用名持有者认领走了：M 认领 _tb_D 返回 {r.status_code}，"
            f"而该目录里装的是已删除用户 V 的产物"
        )
        assert auth.directory_name_error(_uid_m, None, "_tb_D") == (
            "该名字对应的爬取目录已被占用，请换一个"
        )

    def test_unrelated_deletion_does_not_freeze_others_former_names(self, client, scrape_dirs):
        """对照行：删用户**只**影响他自己占过的名字，不能把所有人的曾用名认领一起冻住。

        没有这条，上一条的 400 可以由**任何**让 hist_keys 恒空的原因产生（墓碑插入时
        user_id 串了、或实现改成「有墓碑就全体放弃认领」），主用例照样绿 —— 而 M 自己
        的产物又回到「盘上有、取不回」的老症状上，等于把 #1 的修复反手打掉。
        """
        h_admin, _ = _create_user(client, "_fz_admin", role="admin")
        h_m, _uid_m = _create_user(client, "_fz_m")
        _h_w, uid_w = _create_user(client, "_fz_w")

        # M 用过 _fz_F、产出、改名离开 —— 与 _fz_w 的名字毫不相干
        assert client.put("/api/auth/profile", json={"display_name": "_fz_F"},
                          headers=h_m).status_code == 200
        scrape_dirs("_fz_F", "com.pkg.fz")
        assert client.put("/api/auth/profile", json={"display_name": "_fz_Mout"},
                          headers=h_m).status_code == 200

        # 另有一个不相干的用户被删（会在墓碑表里多出一行）
        assert client.delete(f"/api/admin/users/{uid_w}", headers=h_admin).status_code == 200

        # M 取回 _fz_F —— 目录存在，但除 M 外没人用过这个名字 ⇒ 必须放行
        r = client.put("/api/auth/profile", json={"display_name": "_fz_F"}, headers=h_m)
        assert r.status_code == 200, (
            f"删掉一个不相干的用户竟冻住了别人的曾用名认领：M 认领 _fz_F 返回 "
            f"{r.status_code} {r.get_json()}"
        )


class TestLegacyIllegalNameIsNotSelfLocked:
    """L-7（code-review 第 3 轮，潜伏）：闸门上线**之前**入库的非法值把用户锁死。

    形态：某个存量用户的 `username` 含路径分隔符（闸门上线前可自由填）。此后他
    只想改显示名，两处调用（路由前置校验 + `auth.update_user` 这个唯一关口）都会
    把他**没动过**的 username 一并拿出来校验 ⇒ 恒判非法 ⇒ 任何一次资料更新都 400；
    而 profile 端点根本不允许改 username ⇒ **没有任何修正通道**。

    live 库实测 0 行（24 用户），属潜伏而非在线。修法：对「与库里现值完全相同」的
    字段跳过**字符**判据 —— 该值此刻已经在生效，重验一遍挡不住任何事，只会锁死用户。

    ⚠️ 这里早先写着「安全性由 main._scrape_dn_for 的结构兜底接住」，那是**错的**
    （code-review 第 5 轮指出，实测已复现）：兜底只挡「推导结果越出爬取根」，而
    `alice/pkg` 这类**含分隔符但留在根内**的值**不退化**。接受本豁免的依据只有一条
    事实 —— 这类值只可能来自闸门上线前的存量数据，且 live 为 0 行。

    本类同样必须成对：只钉「旧值豁免」而不同时钉「改成新非法值照旧拦」，就等于把
    字符闸门整个拆掉 —— 那才是真正的越权入口。
    """

    ILLEGAL = "_l7_a/b"

    def test_unchanged_illegal_value_no_longer_freezes_update(self, client):
        uid = _seed_raw_user(self.ILLEGAL, "")
        # 前置断言：夹具确实造出了「闸门判非法」的值。少了这条，本用例可以因
        # 「那个值其实合法」而假绿 —— 那时它测的是空气。
        assert auth._fs_name_error(self.ILLEGAL, "用户名"), "夹具没造出非法 username"

        r = client.put("/api/auth/profile", json={"display_name": "_l7_ok"},
                       headers=_token_for(uid))
        assert r.status_code == 200, (
            f"存量非法 username 把用户锁死了：{r.status_code} {r.get_json()}"
        )

    def test_changing_to_another_illegal_value_is_still_rejected(self, client):
        """对照行：豁免只覆盖「没动它」，把 username **改**成非法值仍须被拒。"""
        uid = _seed_raw_user("_l7_b", "")

        # 1) 改成一个**新的**非法值 —— 必须拒
        assert auth.directory_name_error(uid, "_l7_c/d", None), (
            "改成另一个非法 username 居然放行了 —— 字符闸门被豁免逻辑拆掉了"
        )
        # 2) 整体写路径也确认一次（不只问闸门函数）
        assert auth.update_user(uid, username="_l7_c/d") is None
        # 3) 新建路径没有「旧值」可豁免，必须照旧拒
        assert auth.directory_name_error(None, "_l7_e/f", None), (
            "新建用户路径被豁免逻辑误伤了 —— 新值必须照旧过关"
        )

    def test_unchanged_illegal_display_name_no_longer_freezes_update(self, client):
        """对称腿：`_keep_d`（display_name 入口）与 `_keep_u` 各需一条对照行。

        豁免挂在**两个**独立条件上（`_keep_u` / `_keep_d`）。只测 username 那一侧，
        等于放任 display 那一侧被「恒 False」蒙过去 —— 那种形态的症状正是「存量非法
        display_name 的用户仍被锁死」，与缺陷原形一模一样。
        """
        ILLEGAL_DN = "_l7_g/h"
        uid = _seed_raw_user("_l7_f", ILLEGAL_DN)
        assert auth._fs_name_error(ILLEGAL_DN, "显示名"), "夹具没造出非法 display_name"

        r = client.put("/api/auth/profile", json={"display_name": ILLEGAL_DN},
                       headers=_token_for(uid))
        assert r.status_code == 200, (
            f"存量非法 display_name 把用户锁死了：{r.status_code} {r.get_json()}"
        )

        # 对照：把 display_name **改成**另一个非法值仍须被拒（豁免只管「没动它」）
        r2 = client.put("/api/auth/profile", json={"display_name": "_l7_i/j"},
                        headers=_token_for(uid))
        assert r2.status_code == 400, (
            f"改成另一个非法显示名居然放行了：{r2.status_code} {r2.get_json()}"
        )


class TestSentinelIsAHardGate:
    """哨兵（`scrape_dn_history.user_id = auth._DN_SENTINEL_UID`）必须是**硬闸**，
    而不是「一个很大的序号」。

    为什么（2026-09-24，code-review 第 6 轮第 1 条，用户裁定「改判据」）：
    哨兵的两个用途都是「这个名字的归属**事后无法判定** ⇒ 一律拒」——
    ① 迁移时跨用户先后不可还原的歧义名；② 迁移时磁盘上不属于任何存活用户的目录名
    （升级**之前**就已删掉的用户留下的，既无 users 行也来不及写墓碑）。
    若哨兵只按序号参与比较（`seq > others[k]`），它在迁移那一刻拿到的是当时的最大 id，
    此后任何真实用户再释放一次同名（新 id 更大）就**赢过它** ⇒ 阻断静默失效。
    """

    def test_sentinel_blocks_even_after_a_later_release(self, app, client):
        """承重：哨兵行在前（序号小）、我的释放行在后（序号大）⇒ 仍必须拒。

        反向的写法（哨兵在后）测不出问题：那时按序号比较也恰好是拒，
        与「硬闸」在行为上不可区分 —— 会得到一条永远绿的假腿。
        """
        N = "_sg_n"
        db = database.get_db()
        try:
            uid = db.execute(
                "INSERT INTO users(username, password) VALUES('_sg_u','x')").lastrowid
            # 哨兵**先**插 ⇒ 它的 id 比后面那条小
            db.execute("INSERT INTO scrape_dn_history(user_id, dn) VALUES(?, ?)",
                       (auth._DN_SENTINEL_UID, N))
            # 对照腿的前置：此刻我没有释放行，本来就不该给我
            assert N not in auth._dn_released_keys(db, uid)

            db.execute("INSERT INTO scrape_dn_history(user_id, dn) VALUES(?, ?)", (uid, N))
            # 对照行：同一批写入里一个**没有**哨兵的名字
            db.execute("INSERT INTO scrape_dn_history(user_id, dn) VALUES(?, ?)",
                       (uid, "_sg_ok"))
            db.commit()

            keys = auth._dn_released_keys(db, uid)
            assert N not in keys, (
                f"哨兵被后来的更大序号顶掉了 —— 硬闸失效，{N!r} 又变成可认领"
            )
            assert "_sg_ok" in keys, (
                f"整条函数被一刀切冻住了（连没有哨兵的名字也不给）：{keys!r}"
            )
        finally:
            db.close()


class TestOutOfRootLegacyNameMatchesReadPath:
    """越界的**存量** `display_name` 上，`auth._dir_name_of` 必须与读路径
    `main._scrape_dn_for` 求值一致（2026-09-24，code-review 第 6 轮第 2 条）。

    不一致时的症状：真实目录是 `user_<id>`（读路径退化的结果），而改名时记下的
    「释放名」是原样的越界串 ⇒ 该用户改名离开后，真实目录**永不进**
    own_keys/hist_keys ⇒ 判据 3 永久拒其认领（产物在盘上、应用内无恢复路径）。

    写入关闸（`_fs_name_error`）只挡新数据，库里的历史值仍可能是越界的 ——
    故必须有一条**用过 L-7 豁免的真实形态**的用例，而不是只比对两个纯函数。
    `_seed_raw_user` 直接 INSERT，绕过关口，正是为了造出这种值。
    """

    UID_FOR_PURE = 98

    def test_dir_name_of_degenerates_like_scrape_dn_for(self):
        """纯函数腿：两者对同一个越界值必须给出同一个名字。"""
        for bad in ("..\\..\\_or_e\\pwn", "../_or_e/pwn", "D:/abs/_or_e/pwn"):
            user = {"username": bad, "display_name": "", "role": "user"}
            assert auth._dir_name_of(self.UID_FOR_PURE, bad, "") == \
                _scrape_dn_for(user, self.UID_FOR_PURE), (
                f"{bad!r} 上两个求值函数不一致："
                f"auth={auth._dir_name_of(self.UID_FOR_PURE, bad, '')!r} "
                f"main={_scrape_dn_for(user, self.UID_FOR_PURE)!r}"
            )
            assert auth._dir_name_of(self.UID_FOR_PURE, bad, "") == \
                f"user_{self.UID_FOR_PURE}"

    def test_legacy_out_of_root_name_release_records_real_directory(self, client):
        """承重腿（真实形态）：越界存量名用户改名离开时，记下的必须是**真实目录名**。

        这是「产物在盘上但应用内无恢复路径」那条用户可见后果的收口点：
        记错名字 ⇒ 当事人永远取不回自己的目录。
        """
        uid = _seed_raw_user("_or_u", "..\\..\\_or_esc\\pwn")
        real_dn = f"user_{uid}"
        # 前置：夹具确实造出了越界值（否则本用例在测空气）
        assert auth._dir_name_of(uid, "_or_u", "..\\..\\_or_esc\\pwn") == real_dn, (
            "夹具前提不成立：种子值没有越界（或退化没生效）"
        )

        r = client.put("/api/auth/profile", json={"display_name": "_or_out"},
                       headers=_token_for(uid))
        assert r.status_code == 200, f"越界存量名用户改名被拒：{r.status_code} {r.get_json()}"

        db = database.get_db()
        try:
            released = [row[0] for row in db.execute(
                "SELECT dn FROM scrape_dn_history WHERE user_id = ?", (uid,)).fetchall()]
        finally:
            db.close()
        assert real_dn in released, (
            f"释放名记的不是真实目录名 ⇒ 当事人取不回自己的产物。"
            f"记下的={released!r}，真实目录={real_dn!r}"
        )
        assert "..\\..\\_or_esc\\pwn" not in released, (
            f"越界串被原样记进了释放名（永远匹配不到任何真实目录）：{released!r}"
        )
