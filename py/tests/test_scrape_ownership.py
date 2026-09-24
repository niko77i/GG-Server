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
import time

import pytest

import database
from main import _SCRAPE_DEFAULT_DIR


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
