"""安全加固测试 — A/B/C/D 类缺陷收口。"""
import os
import shutil

import pytest

import database


def _create_user(client, username, role="user", platform="gg", created_by=None):
    """注册用户 → 直接改写 role/platform → 登录，返回 (headers, user_id)。"""
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


def _mk_account(db, owner_id, account_id, name="测试账户"):
    db.execute("INSERT INTO accounts(name, account_id, owner_id) VALUES(?,?,?)",
               (name, account_id, owner_id))
    db.commit()


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


def _data_root():
    """复刻 py/main.py 的 _DATA_ROOT（非 frozen：os.path.dirname(_current_dir)，_current_dir = py/）。

    即仓库根目录，故 _SCRAPE_DEFAULT_DIR = <root>/temp/scraped_images、_FONTS_DIR = <root>/fonts。
    main.py 不读 DATA_ROOT 环境变量，因此这里只用与生产一致的推导式。
    """
    return os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


ANON_GET_ENDPOINTS = [
    "/api/fonts/list",
    "/api/fonts/preview",
    "/api/fonts/file/simhei",
    "/api/google-sheets/status",
]

ANON_POST_ENDPOINTS = [
    ("/api/fonts/mark-used", {"font": "simhei"}),
    ("/api/fonts/import", {}),
    ("/api/fonts/upload", {}),
    ("/api/google-ads/accounts", {}),
    ("/api/google-ads/report", {}),
    ("/api/translate", {"text": "hello"}),
]


class TestAClassAnon:
    @pytest.mark.parametrize("path", ANON_GET_ENDPOINTS)
    def test_get_requires_login(self, client, path):
        resp = client.get(path)
        assert resp.status_code == 401

    @pytest.mark.parametrize("path,body", ANON_POST_ENDPOINTS)
    def test_post_requires_login(self, client, path, body):
        resp = client.post(path, json=body)
        assert resp.status_code == 401


# 登录态对照用的 GET 端点（与 ANON_GET_ENDPOINTS 同形状，去掉已单独覆盖的 /api/fonts/list）
LOGGED_IN_GET_ENDPOINTS = [
    "/api/fonts/preview",
    "/api/fonts/file/simhei",
    "/api/google-sheets/status",
]

# 登录态对照用的 POST 端点（与 ANON_POST_ENDPOINTS 同形状）
# 注意：/api/fonts/import 登录后触发阻塞式 tkinter 对话框，无法在测试里安全调用，
# 故豁免对照断言，其鉴权由匿名 401 用例钉住。
LOGGED_IN_POST_ENDPOINTS = [
    ("/api/fonts/mark-used", {"font": "simhei"}),
    ("/api/fonts/upload", {}),
    ("/api/google-ads/accounts", {}),
    ("/api/google-ads/report", {}),
]


class TestAClassLoggedIn:
    def test_fonts_list_ok_when_logged_in(self, client, auth_headers):
        resp = client.get("/api/fonts/list", headers=auth_headers)
        assert resp.status_code == 200
        assert resp.get_json()["success"] is True

    def test_translate_still_validates_when_logged_in(self, client, auth_headers):
        # 登录后空 text 仍返回 400（证明鉴权在前、业务校验在后，行为未变）
        resp = client.post("/api/translate", json={}, headers=auth_headers)
        assert resp.status_code == 400

    @pytest.mark.parametrize("path", LOGGED_IN_GET_ENDPOINTS)
    def test_get_not_blocked_when_logged_in(self, client, auth_headers, path):
        # 对照断言：合法用户绝不能被新补的鉴权误挡成 401
        # （200/400/404/500 均取决于入参与可选依赖，均可接受）
        resp = client.get(path, headers=auth_headers)
        assert resp.status_code != 401

    @pytest.mark.parametrize("path,body", LOGGED_IN_POST_ENDPOINTS)
    def test_post_not_blocked_when_logged_in(self, client, auth_headers, path, body):
        # 对照断言：合法用户绝不能被新补的鉴权误挡成 401
        resp = client.post(path, json=body, headers=auth_headers)
        assert resp.status_code != 401


class TestAClassFileWhitelist:
    def test_scrape_download_rejects_path_outside_scrape_dir(self, client, auth_headers):
        # 白名单外目录（系统目录）必须被拒，且不能被匿名打包
        resp = client.get("/api/scrape/download?path=C:\\Windows", headers=auth_headers)
        assert resp.status_code in (403, 404)

    def test_scrape_download_requires_existing_dir(self, client, auth_headers):
        resp = client.get("/api/scrape/download?path=C:\\nonexistent\\dir", headers=auth_headers)
        assert resp.status_code == 404

    def test_font_file_rejects_non_font_file(self, client, auth_headers):
        # 任意存在的文件（非字体扩展名）必须被拒
        import tempfile, os
        fd, fp = tempfile.mkstemp(suffix=".txt")
        try:
            os.write(fd, b"secret")
            os.close(fd)
            resp = client.get(f"/api/font-file?path={fp}", headers=auth_headers)
            assert resp.status_code in (403, 404)
        finally:
            os.unlink(fp)

    def test_serve_image_still_rejects_non_png(self, client):
        # serve_image 已有 _is_safe_path + .png 双闸门，匿名端点白名单行为钉住
        resp = client.get("/api/image?path=C:\\Windows\\win.ini")
        assert resp.status_code == 404

    def test_scrape_download_allows_dir_inside_scrape_root(self, client, auth_headers):
        # 对照组：_SCRAPE_DEFAULT_DIR 内的目录仍可下载（白名单不能误伤合法产出）
        target = os.path.join(_data_root(), "temp", "scraped_images", "pkg_probe")
        os.makedirs(target, exist_ok=True)
        try:
            resp = client.get(f"/api/scrape/download?path={target}", headers=auth_headers)
            assert resp.status_code == 200
        finally:
            shutil.rmtree(target, ignore_errors=True)

    def test_font_file_allows_font_in_fonts_dir(self, client, auth_headers):
        # 对照组：_FONTS_DIR 内的 .ttf 仍 200
        fonts_dir = os.path.join(_data_root(), "fonts")
        os.makedirs(fonts_dir, exist_ok=True)
        fp = os.path.join(fonts_dir, "probe.ttf")
        with open(fp, "wb") as f:
            f.write(b"\x00\x01\x00\x00")
        resp = None
        try:
            resp = client.get(f"/api/font-file?path={fp}", headers=auth_headers)
            assert resp.status_code == 200
        finally:
            # Windows 下 send_file 会持有文件句柄，必须先关响应再删，否则 WinError 32
            if resp is not None:
                resp.close()
            try:
                os.unlink(fp)
            except OSError:
                pass

    def test_font_file_rejects_font_outside_fonts_dir(self, client, auth_headers, tmp_path):
        # 覆盖目录闸门 403 分支：扩展名合法但目录在白名单外
        fp = tmp_path / "evil.ttf"
        fp.write_bytes(b"\x00\x01\x00\x00")
        resp = client.get(f"/api/font-file?path={fp}", headers=auth_headers)
        assert resp.status_code == 403


class TestScrapeSaveDirNarrowed:
    """save_dir 收窄（2026-09-24 裁决）：自定义保存路径必须落在 _SCRAPE_DEFAULT_DIR 内。"""

    def test_scrape_rejects_custom_save_dir_outside_root(self, client, auth_headers):
        resp = client.post("/api/scrape", json={
            "url": "https://play.google.com/store/apps/details?id=com.example",
            "save_dir": "C:\\Windows",
        }, headers=auth_headers)
        assert resp.status_code == 400

    def test_scrape_rejects_sibling_dir_escaping_root(self, client, auth_headers):
        # 前缀绕过防护：<root>/temp/scraped_images_evil 不能被 startswith 误放行
        evil = os.path.join(_data_root(), "temp", "scraped_images_evil")
        resp = client.post("/api/scrape", json={
            "url": "https://play.google.com/store/apps/details?id=com.example",
            "save_dir": evil,
        }, headers=auth_headers)
        assert resp.status_code == 400


class TestB1GgWriteOwnership:
    def _mk_owned_account(self, client, owner_uid, account_id):
        db = database.get_db()
        _mk_account(db, owner_uid, account_id, "账户")
        aid = db.execute("SELECT id FROM accounts WHERE account_id=?", (account_id,)).fetchone()["id"]
        db.close()
        return aid

    def test_user_cannot_update_others_account(self, client):
        _, owner_uid = _create_user(client, "_b1_owner", role="user")
        att, _ = _create_user(client, "_b1_att", role="user")
        aid = self._mk_owned_account(client, owner_uid, "GG-B1-1")
        resp = client.put(f"/api/accounts/{aid}", json={"name": "被篡改"}, headers=att)
        assert resp.status_code == 403
        db = database.get_db()
        name = db.execute("SELECT name FROM accounts WHERE id=?", (aid,)).fetchone()["name"]
        db.close()
        assert name == "账户"   # 数据未变

    def test_user_can_update_own_account(self, client):
        owner_hdr, owner_uid = _create_user(client, "_b1_owner2", role="user")
        aid = self._mk_owned_account(client, owner_uid, "GG-B1-2")
        resp = client.put(f"/api/accounts/{aid}", json={"name": "改名成功"}, headers=owner_hdr)
        assert resp.status_code == 200

    def test_developer_can_update_others_account(self, client):
        _, owner_uid = _create_user(client, "_b1_owner3", role="user")
        dev, _ = _create_user(client, "_b1_dev", role="developer")
        aid = self._mk_owned_account(client, owner_uid, "GG-B1-3")
        resp = client.put(f"/api/accounts/{aid}", json={"name": "代改"}, headers=dev)
        assert resp.status_code == 200

    def test_user_cannot_reassign_others_account(self, client):
        _, owner_uid = _create_user(client, "_b1_owner4", role="user")
        att, _ = _create_user(client, "_b1_att4", role="user")
        aid = self._mk_owned_account(client, owner_uid, "GG-B1-4")
        resp = client.put(f"/api/accounts/{aid}/reassign", json={}, headers=att)
        assert resp.status_code == 403

    def test_user_cannot_batch_update_others_account(self, client):
        _, owner_uid = _create_user(client, "_b1_owner5", role="user")
        att, _ = _create_user(client, "_b1_att5", role="user")
        aid = self._mk_owned_account(client, owner_uid, "GG-B1-5")
        resp = client.post("/api/accounts/batch-update", json={"ids": [aid], "field": "timezone", "value": "UTC+9"}, headers=att)
        assert resp.status_code == 403


class TestB2FbPixelsIsolation:
    def test_regular_fb_user_sees_only_own_pixels(self, client):
        hdr, u1 = _create_user(client, "_b2_u1", role="user", platform="fb")
        _, u2 = _create_user(client, "_b2_u2", role="user", platform="fb")
        db = database.get_db()
        pbm1 = _mk_fb_pixel_bm(db, u1, "PBM-B2-1", "U1的像素BM")
        pbm2 = _mk_fb_pixel_bm(db, u2, "PBM-B2-2", "U2的像素BM")
        _mk_fb_pixel(db, pbm1, "PX-B2-1", "U1的像素")
        _mk_fb_pixel(db, pbm2, "PX-B2-2", "U2的像素")
        db.close()
        resp = client.get("/api/fb/pixels/list?size=50", headers=hdr)
        ids = {p["pixel_id"] for p in resp.get_json()["items"]}
        assert ids == {"PX-B2-1"}      # 只含自己，不含 U2 的像素（对照行必需）

    def test_developer_still_sees_all_pixels(self, client):
        _, u1 = _create_user(client, "_b2_d_u1", role="user", platform="fb")
        _, u2 = _create_user(client, "_b2_d_u2", role="user", platform="fb")
        db = database.get_db()
        pbm1 = _mk_fb_pixel_bm(db, u1, "PBM-B2D-1", "D-U1的BM")
        pbm2 = _mk_fb_pixel_bm(db, u2, "PBM-B2D-2", "D-U2的BM")
        _mk_fb_pixel(db, pbm1, "PX-B2D-1", "D-U1像素")
        _mk_fb_pixel(db, pbm2, "PX-B2D-2", "D-U2像素")
        db.close()
        dev, _ = _create_user(client, "_b2_d_dev", role="developer", platform="fb")
        resp = client.get("/api/fb/pixels/list?size=50", headers=dev)
        ids = {p["pixel_id"] for p in resp.get_json()["items"]}
        assert ids == {"PX-B2D-1", "PX-B2D-2"}


class TestB4TtAgentOwnership:
    def _setup(self, client):
        _, owner = _create_user(client, "_b4_owner", role="user", platform="tt")
        db = database.get_db()
        db.execute("INSERT INTO agents(name, owner_id, platform) VALUES('TT代理A', ?, 'tt')", (owner,))
        db.commit()
        aid = db.execute("SELECT id FROM agents WHERE name='TT代理A'").fetchone()["id"]
        db.close()
        return owner, aid

    def test_tt_user_cannot_rename_others_agent(self, client):
        owner, aid = self._setup(client)
        hdr, _ = _create_user(client, "_b4_att", role="user", platform="tt")
        resp = client.put(f"/api/agents/{aid}?platform=tt", json={"name": "被改名"}, headers=hdr)
        assert resp.status_code == 404
        db = database.get_db()
        name = db.execute("SELECT name FROM agents WHERE id=?", (aid,)).fetchone()["name"]
        db.close()
        assert name == "TT代理A"

    def test_tt_user_cannot_delete_others_agent(self, client):
        owner, aid = self._setup(client)
        hdr, _ = _create_user(client, "_b4_att2", role="user", platform="tt")
        resp = client.delete(f"/api/agents/{aid}?platform=tt", headers=hdr)
        assert resp.status_code == 404
        db = database.get_db()
        row = db.execute("SELECT 1 FROM agents WHERE id=?", (aid,)).fetchone()
        db.close()
        assert row is not None

    def test_developer_can_rename_any_tt_agent(self, client):
        owner, aid = self._setup(client)
        dev, _ = _create_user(client, "_b4_dev", role="developer")
        resp = client.put(f"/api/agents/{aid}?platform=tt", json={"name": "代改名"}, headers=dev)
        assert resp.status_code == 200

    def test_developer_can_delete_any_tt_agent(self, client):
        owner, aid = self._setup(client)
        dev, _ = _create_user(client, "_b4_del_dev", role="developer")
        resp = client.delete(f"/api/agents/{aid}?platform=tt", headers=dev)
        assert resp.status_code == 200
        db = database.get_db()
        row = db.execute("SELECT 1 FROM agents WHERE id=?", (aid,)).fetchone()
        db.close()
        assert row is None


class TestC1ReassignInvalidOwner:
    def _setup(self, client):
        dev, dev_id = _create_user(client, "_c1_dev", role="developer")
        db = database.get_db()
        _mk_account(db, dev_id, "GG-C1-1", "C1账户")
        aid = db.execute("SELECT id FROM accounts WHERE account_id='GG-C1-1'").fetchone()["id"]
        db.close()
        return dev, aid

    def test_reassign_superscript_digit_returns_400(self, client):
        dev, aid = self._setup(client)
        resp = client.put(f"/api/accounts/{aid}/reassign", json={"owner_id": "²"}, headers=dev)
        assert resp.status_code == 400

    def test_reassign_nonexistent_user_returns_400(self, client):
        dev, aid = self._setup(client)
        resp = client.put(f"/api/accounts/{aid}/reassign", json={"owner_id": "99999999"}, headers=dev)
        assert resp.status_code == 400

    def test_reassign_valid_user_succeeds(self, client):
        dev, aid = self._setup(client)
        _, target = _create_user(client, "_c1_target", role="user")
        resp = client.put(f"/api/accounts/{aid}/reassign", json={"owner_id": target}, headers=dev)
        assert resp.status_code == 200
