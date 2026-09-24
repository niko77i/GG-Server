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

    def test_scrape_download_requires_existing_dir(self, client, dev_headers):
        # 本类钉的是**白名单/存在性层**。归属校验（普通用户对他人目录恒 403）已于
        # 2026-09-24 插在此层之前，故这里用 developer 身份穿过归属层，让断言仍落在
        # 本层语义上；普通用户在归属层的 403 由 test_scrape_ownership.py 承重。
        resp = client.get("/api/scrape/download?path=C:\\nonexistent\\dir", headers=dev_headers)
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

    def test_scrape_download_allows_dir_inside_scrape_root(self, client, dev_headers):
        # 对照组：_SCRAPE_DEFAULT_DIR 内的目录仍可下载（白名单不能误伤合法产出）
        # 用 developer 穿过归属层的原因同上：本类钉白名单，不钉归属。
        target = os.path.join(_data_root(), "temp", "scraped_images", "pkg_probe")
        os.makedirs(target, exist_ok=True)
        try:
            resp = client.get(f"/api/scrape/download?path={target}", headers=dev_headers)
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

    def test_reassign_oversized_digit_returns_400(self, client):
        """超 SQLite 64 位的有符号整数上界（2^63-1）⇒ 400 而非 500。

        `int("9"*30)` 在 Python 侧**成功**（任意精度），溢出发生在 sqlite3 参数绑定处，
        抛出的 OverflowError 不在 `int()` 的 except 作用域内 ⇒ 改前会漏成 500 并吐英文原文。
        """
        dev, aid = self._setup(client)
        for raw in ("9223372036854775808", "9" * 19, "9" * 30, "9" * 4096):
            resp = client.put(f"/api/accounts/{aid}/reassign",
                              json={"owner_id": raw}, headers=dev)
            assert resp.status_code == 400, f"{raw[:20]} 应 400，实得 {resp.status_code}"

    def test_reassign_max_valid_int64_still_goes_to_existence_check(self, client):
        """边界对照：2^63-1（合法 int64 上界）必须仍走**存在性预检**而非格式闸门。

        若上界误写成 `>= 2**63 - 1`，合法边界值 2^63-1 会被格式闸门拒掉、返回
        「owner_id 不合法」而非「目标用户不存在」，这条即变红 —— 它钉住「上界不误伤合法边界值」。
        """
        dev, aid = self._setup(client)
        resp = client.put(f"/api/accounts/{aid}/reassign",
                          json={"owner_id": "9223372036854775807"}, headers=dev)
        assert resp.status_code == 400
        assert resp.get_json()["error"] == "目标用户不存在"

    def test_reassign_non_ascii_digit_cannot_impersonate_user_id(self, client):
        """ASCII 契约：Unicode 数字必须被格式闸门拒掉，不得被 int() 当作等价数字放行。

        承重设计：`int("١") == 1`、`int("٢") == 2` …（阿拉伯-印度数字）。本用例**刻意先建一个
        id 恰好等于 `int(该 Unicode 数字)` 的真实用户**，于是：
        - 闸门完好 ⇒ 400「owner_id 不合法」，账户归属**不变**；
        - 若 `isascii()` 被摘掉 ⇒ `int()` 解析成合法用户 id、存在性预检通过 ⇒ **转移成功** ⇒ 本用例红。
        （刻意选「Unicode 数字映射到已存在的用户」这一构造，而非「映射到不存在的 id」：
        后者在摘掉 isascii 后仍会落到存在性预检返回 400，只断状态码会出现假绿；
        本构造使越权真实发生（200 + 归属被改写），状态码与归属断言双重设防。）
        """
        _, owner = _create_user(client, "_c1a_o", role="user")
        _, target = _create_user(client, "_c1a_t", role="user")
        dev, _ = _create_user(client, "_c1a_d", role="developer")
        db = database.get_db()
        _mk_account(db, owner, "GG-C1-A", "C1非ASCII")
        aid = db.execute("SELECT id FROM accounts WHERE account_id='GG-C1-A'").fetchone()["id"]
        db.close()
        assert 1 <= target <= 9, f"本用例依赖 target id ≤ 9 以构造阿拉伯-印度数字，实得 {target}"
        fake = chr(0x0660 + target)
        assert int(fake) == target, "前置失败：构造的 Unicode 数字未映射到 target id"

        resp = client.put(f"/api/accounts/{aid}/reassign",
                          json={"owner_id": fake}, headers=dev)
        assert resp.status_code == 400
        assert resp.get_json()["error"] == "owner_id 不合法"
        # 承重：归属必须未变（若 isascii 闸门失守，账户会被静默转给 target）
        db = database.get_db()
        ow = db.execute("SELECT owner_id FROM accounts WHERE id=?", (aid,)).fetchone()["owner_id"]
        db.close()
        assert ow == owner, "Unicode 数字绕过了 ASCII 闸门并改变了账户归属"

    def test_reassign_oversized_account_id_returns_404(self, client):
        """同族向量：路径参数 aid 也走任意精度解析（Werkzeug IntegerConverter 无上界），
        超 int64 的 id 会在 sqlite3 参数绑定处抛 OverflowError ⇒ 改前 500 + 英文原文。

        与 owner_id 向量同根因、同表现，但触发门槛更低：**普通 user 角色即可打到**。
        超界 id 不可能存在任何行 ⇒ 语义上应是 404「账户不存在」，与既有 404 路径合流。
        """
        user, _ = _create_user(client, "_c1b_u", role="user")
        for raw in ("9223372036854775808", "9" * 19, "9" * 30):
            resp = client.put(f"/api/accounts/{raw}/reassign", json={}, headers=user)
            assert resp.status_code == 404, f"aid={raw[:20]} 应 404，实得 {resp.status_code}"
            assert resp.get_json()["error"] == "账户不存在"


class TestC2UserSearch:
    """C-2：developer 不带 platform 时搜索用户，`list_users` 曾把 `AND (...)` 直接拼在
    `FROM users` 之后（空 `where_clause`）⇒ SQL 语法错误 ⇒ 500。

    - `test_developer_search_without_platform_returns_200`：只断言 200（弱断言，防不住
      「把搜索结果恒置空」的绕过实现），仅作状态码锚点；
    - `test_developer_search_returns_matching_users`：**承重**正向对照，必须真的返回匹配行；
    - `test_developer_search_with_platform_still_works`：纯增量对照（带 platform 的路径
      改前就能拼对，修好后必须仍 200 且返回匹配行）。
    """

    def test_developer_search_without_platform_returns_200(self, client):
        dev, _ = _create_user(client, "_c2_dev", role="developer")
        resp = client.get("/api/admin/users?search=foo", headers=dev)
        assert resp.status_code == 200

    def test_developer_search_returns_matching_users(self, client):
        dev, _ = _create_user(client, "_c2_dev2", role="developer")
        _create_user(client, "_c2_match", role="user")
        resp = client.get("/api/admin/users?search=_c2_match", headers=dev)
        assert resp.status_code == 200
        assert any(u["username"] == "_c2_match" for u in resp.get_json()["users"])

    def test_developer_search_with_platform_still_works(self, client):
        dev, _ = _create_user(client, "_c2_dev3", role="developer")
        _create_user(client, "_c2_match2", role="user")
        resp = client.get("/api/admin/users?search=_c2_match2&platform=gg", headers=dev)
        assert resp.status_code == 200
        assert any(u["username"] == "_c2_match2" for u in resp.get_json()["users"])


class TestD2BatchDeleteCount:
    def test_batch_delete_reports_actual_count(self, client):
        """承重对照：混入一个**存在**的 id ⇒ deleted 必须是 1 而非 len(ids)=2、也非恒 0。"""
        dev, dev_id = _create_user(client, "_d2_dev", role="developer")
        db = database.get_db()
        _mk_account(db, dev_id, "GG-D2-1", "D2账户1")
        aid = db.execute("SELECT id FROM accounts WHERE account_id='GG-D2-1'").fetchone()["id"]
        db.close()
        # 1 个存在 + 1 个不存在 ⇒ 真实删除数 1
        resp = client.post("/api/accounts/batch-delete", json={"ids": [aid, 999998]}, headers=dev)
        assert resp.status_code == 200
        assert resp.get_json()["deleted"] == 1
        # 同一 id 再删一次（已软删，deleted_at IS NULL 不匹配）⇒ 0
        resp = client.post("/api/accounts/batch-delete", json={"ids": [aid]}, headers=dev)
        assert resp.status_code == 200
        assert resp.get_json()["deleted"] == 0

    def test_batch_delete_all_nonexistent_reports_zero(self, client):
        dev, _ = _create_user(client, "_d2_dev2", role="developer")
        resp = client.post("/api/accounts/batch-delete", json={"ids": [999999, 999998]}, headers=dev)
        assert resp.status_code == 200
        assert resp.get_json()["deleted"] == 0


class TestD1StatusesSmoke:
    """D-1 是纯删除死代码（缓存键从未被 set），无行为变化，用冒烟回归钉住改名/删除流程仍正常。

    这是回归钉，不是失败测试 —— 改前改后都应通过。
    """

    def test_statuses_rename_delete_still_work(self, client):
        dev, dev_id = _create_user(client, "_d1_dev", role="developer")
        db = database.get_db()
        db.execute("INSERT INTO account_statuses(name, platform, owner_id) VALUES('状态甲','gg',?)", (dev_id,))
        sid = db.execute("SELECT id FROM account_statuses WHERE name='状态甲'").fetchone()["id"]
        db.commit()
        db.close()
        resp = client.put(f"/api/statuses/{sid}", json={"name": "状态乙"}, headers=dev)
        assert resp.status_code == 200
        resp = client.delete(f"/api/statuses/{sid}", headers=dev)
        assert resp.status_code == 200


class TestA2AnonymousRejected:
    """A 组 8 条：零 token 必须 401。

    收口前本组第 1 条会失败 —— 那正是要钉的行为。
    """

    ANON_CASES = [
        ("get",  "/api/products/list",    None),
        ("post", "/api/products/create",  {"product_name": "anon-probe"}),
        ("get",  "/api/users/names",      None),
        ("get",  "/api/settings/account", None),
        ("get",  "/api/auth/names",       None),
        ("post", "/api/browse-file",      {"path": "x"}),
        ("post", "/api/browse-save",      {"path": "x"}),
        ("post", "/api/browse-folder",    {"path": "x"}),
    ]

    @pytest.mark.parametrize("method,path,payload", ANON_CASES)
    def test_anonymous_is_rejected(self, client, method, path, payload):
        fn = getattr(client, method)
        resp = fn(path, json=payload) if payload is not None else fn(path)
        assert resp.status_code == 401, (
            f"{method.upper()} {path} 对匿名请求返回 {resp.status_code}，应为 401"
        )

    @pytest.mark.parametrize("method,path,payload", ANON_CASES)
    def test_logged_in_is_not_rejected(self, client, dev_headers, method, path, payload):
        """承重对照：带 token 时**不得**是 401（证明只挡匿名，没挡已登录）。

        没有这条，「把 8 个端点改成恒 401」也能让上一条全绿 —— 这正是本项目
        「无对照行的断言 = 假绿」定式。
        """
        fn = getattr(client, method)
        resp = (fn(path, json=payload, headers=dev_headers) if payload is not None
                else fn(path, headers=dev_headers))
        assert resp.status_code != 401, (
            f"{method.upper()} {path} 带 token 仍返回 401 —— 收口过头了"
        )


class TestFontFileWhitelistMinimized:
    """`/api/font-file` 只应放行 _scan_fonts_dir() 列出的那 4 个具名系统字体。

    承重对照：**同一目录内**的具名字体必须 200、非具名字体必须 403。
    只测其中一条无法区分「白名单最小化」与「整个系统字体目录被误封」。
    """

    FOUR_NAMED = ("simhei.ttf", "msyh.ttc", "simsun.ttc", "arial.ttf")

    @staticmethod
    def _sys_font_dir():
        return os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "Fonts")

    def test_named_system_font_still_served(self, client):
        """对照行 A：4 个具名字体必须仍可访问（证明没有误封）。"""
        p = os.path.join(self._sys_font_dir(), "arial.ttf")
        if not os.path.isfile(p):
            pytest.skip("本机无 arial.ttf，无法验证对照行 A")
        resp = client.get("/api/font-file", query_string={"path": p})
        assert resp.status_code == 200, (
            f"具名系统字体 arial.ttf 被拒绝（{resp.status_code}）—— 白名单收得过紧，"
            "会打断前端字体预览"
        )

    def test_other_system_font_is_rejected(self, client):
        """对照行 B：同目录内的非具名字体必须 403。"""
        d = self._sys_font_dir()
        if not os.path.isdir(d):
            pytest.skip("本机无系统字体目录，无法验证对照行 B")
        named = {n.lower() for n in self.FOUR_NAMED}
        others = [f for f in os.listdir(d)
                  if f.lower().endswith((".ttf", ".otf", ".ttc"))
                  and f.lower() not in named]
        if not others:
            pytest.skip("系统字体目录内无其它字体可供对照")
        p = os.path.join(d, others[0])
        resp = client.get("/api/font-file", query_string={"path": p})
        assert resp.status_code == 403, (
            f"非具名系统字体 {others[0]} 返回 {resp.status_code}，应为 403 —— "
            "整个系统字体目录仍然匿名可读"
        )

    def test_synthetic_fonts_dir_both_arms(self, client, tmp_path, monkeypatch):
        """承重腿：合成一个 Fonts 目录，**同一目录内**具名字体 200、非具名字体 403。

        为什么必须有这条：上面两条依赖**真实系统字体目录**，环境不满足时双双 skip
        ⇒ 无声通过。而「整个系统字体目录被封」与「白名单最小化」这两种实现，
        在真实环境里未必能同屏对照。这条用 tmp_path 造出受控对照，**永不 skip**。

        依据：`_named_system_fonts()` 在**调用时**读 `SystemRoot`（不是模块导入时缓存），
        所以 monkeypatch.setenv 能生效。
        """
        fake_root = tmp_path
        fake_fonts = fake_root / "Fonts"
        fake_fonts.mkdir()
        named_file = fake_fonts / "arial.ttf"
        other_file = fake_fonts / "unlisted_font.ttf"
        named_file.write_bytes(b"FAKE-NAMED")
        other_file.write_bytes(b"FAKE-OTHER")
        monkeypatch.setenv("SystemRoot", str(fake_root))

        # 对照行 A：具名字体（在 _named_system_fonts() 清单里）⇒ 200
        resp_named = client.get("/api/font-file", query_string={"path": str(named_file)})
        assert resp_named.status_code == 200, (
            f"合成具名字体 arial.ttf 返回 {resp_named.status_code}，应为 200 —— "
            "白名单收得过紧，会打断前端字体预览"
        )

        # 对照行 B：同目录内的非具名字体 ⇒ 403
        resp_other = client.get("/api/font-file", query_string={"path": str(other_file)})
        assert resp_other.status_code == 403, (
            f"合成非具名字体 unlisted_font.ttf 返回 {resp_other.status_code}，应为 403 —— "
            "白名单没有真正最小化，同目录下任意字体仍可读"
        )


class TestB3DownloadsRequireAuthOrSignature:
    """B-3 三条：匿名（无 token、无签名）必须 401；带 token 必须非 401。"""

    CASES = [
        ("/api/scrape/download",       {"path": "whatever"}),
        ("/api/video/download",        {"path": "whatever"}),
        ("/api/audio-replace/download", {"path": "whatever"}),
    ]

    @pytest.mark.parametrize("path,args", CASES)
    def test_anonymous_without_signature_rejected(self, client, path, args):
        resp = client.get(path, query_string=args)
        assert resp.status_code == 401, (
            f"{path} 匿名且无签名返回 {resp.status_code}，应为 401"
        )

    @pytest.mark.parametrize("path,args", CASES)
    def test_garbage_signature_rejected(self, client, path, args):
        """伪造签名必须被拒（承重：证明验签真的在跑）。"""
        resp = client.get(path, query_string={**args, "exp": "9999999999", "sig": "deadbeef"})
        assert resp.status_code == 401, (
            f"{path} 伪造签名返回 {resp.status_code}，应为 401"
        )

    @pytest.mark.parametrize("path,args", CASES)
    def test_logged_in_is_not_401(self, client, dev_headers, path, args):
        """承重对照：带 token **不得** 401（证明只挡匿名，没挡已登录）。

        注意断言是「非 401」而非「200」—— path 不存在时应为 404，
        那也是合法结果（鉴权已通过，业务层说文件不存在）。
        """
        resp = client.get(path, query_string=args, headers=dev_headers)
        assert resp.status_code != 401, (
            f"{path} 带 token 仍返回 401 —— 收口过头了"
        )

    @pytest.mark.parametrize("path,_args", CASES)
    def test_issued_signature_is_accepted(self, client, app, path, _args):
        """闭环承重：`sign_query` 签发的 URL 必须能被同一端点放行。

        为什么必须有这条：上面三条只钉住了「无签名 ⇒ 401」「假签名 ⇒ 401」
        「带 token ⇒ 非 401」，**唯独没有一条证明「合法签名 ⇒ 放行」**。
        于是只要签发侧与校验侧的约定不一致（参数名 `exp` 对不上 `expires`、
        端点串写错、编码方式不同），**签名 URL 会全线 401 而上面三条依然全绿**
        —— 这是典型的假绿：功能完全不可用，测试却零信号。

        断言**精确等于 404**（而非「非 401」）：`whatever` 路径不存在，三个端点
        过闸后都确定性走到 `not os.path.isfile(path)` 分支回 404。写成「非 401」
        会漏掉两类假绿——验签抛异常变 500、以及意外返回 200——两者都会被放过。
        """
        from url_signing import sign_query

        qs = sign_query(path, "whatever", app.config["JWT_SECRET_KEY"])
        resp = client.get(path + "?" + qs)
        assert resp.status_code == 404, (
            f"{path} 对合法签名的响应是 {resp.status_code}，期望 404（闸门放行后"
            f"撞不存在的文件）—— 401/403 说明签发侧与校验侧约定不一致；"
            f"500 说明验签抛了异常；200 说明放行了不该放行的请求。query={qs}"
        )

    def test_signature_is_bound_to_its_endpoint_at_route_level(self, client, app):
        """一个端点的签名不能挪用到另一个端点 —— 在**路由层**验证绑定生效。

        `test_url_signing.py::test_cross_endpoint_reuse_rejected` 只证明
        `verify_query` 本身会拒绝跨端点复用；它管不到**端点有没有把正确的
        endpoint 串传给 `_download_authorized`**。若某条端点写错了串
        （例如 scrape/download 传了 "/api/video/download"），单测全绿而这条必红。
        """
        from url_signing import sign_query

        qs = sign_query("/api/video/download", "whatever", app.config["JWT_SECRET_KEY"])
        resp = client.get("/api/scrape/download?" + qs)
        assert resp.status_code == 401, (
            f"video/download 的签名挪用到 scrape/download 后被放行"
            f"（{resp.status_code}）—— 端点的 endpoint 串绑定失效"
        )
