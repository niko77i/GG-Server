"""安全加固测试 — A/B/C/D 类缺陷收口。"""
import json
import logging
import os
import shutil

import pytest

import database

# 与 test_fb_platform.py 同因同解：conftest 的 15 字节 JWT 密钥会让 PyJWT 每次编解码
# 都抛 InsecureKeyLengthWarning，属夹具既有产物。按类精确静音，保持测试输出干净。
pytestmark = pytest.mark.filterwarnings("ignore::jwt.warnings.InsecureKeyLengthWarning")


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
    def test_scrape_download_rejects_path_outside_scrape_dir(self, client, dev_headers):
        # 白名单外目录（系统目录）必须被拒。
        # 用 developer 穿过归属层，且断言收紧为 **恰为 404**：归属层拒人是 403，
        # 若这里仍写 `in (403, 404)`，归属层就能满足断言 ⇒ 白名单层失去保护（整段
        # 删掉仍全绿）。C:\Windows 确实存在，故 404 只可能来自白名单这一层。
        resp = client.get("/api/scrape/download?path=C:\\Windows", headers=dev_headers)
        assert resp.status_code == 404, (
            f"白名单层未生效：得到 {resp.status_code}（403 来自归属层，不构成本层证据）"
        )

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


# ---------------------------------------------------------------------------
# E 组：信息泄露（CWE-209）收口
#   E-1 全局 500 处理器不再回显异常原文 / traceback（治本）
#   E-2 status_id / agent_id / mcc_id × 三个端点补 int64 上界与类型闸门
# ---------------------------------------------------------------------------

# 客户端响应里绝不允许出现的「内部细节」标记（第一层的直接守门断言）
LEAK_MARKERS = ("Traceback", "main.py", "SQLite", "sqlite3", "OverflowError",
                "IntegrityError", "FOREIGN KEY")


def _assert_no_internal_leak(resp):
    """响应体（含 JSON 与 header 之外的全部文本）不得含异常类型/消息/源码路径/行号。"""
    raw = resp.get_data(as_text=True)
    for marker in LEAK_MARKERS:
        assert marker not in raw, f"响应体泄露内部细节 {marker!r}: {raw[:200]!r}"


class TestE1Global500HandlerHidesInternals:
    """第一层：任意**未预期**异常 ⇒ 固定文案 + 500；详情只落服务端日志。

    改前该处理器藏在 `if __name__ == "__main__":` 块内 ⇒ 以导入方式拉起应用时
    压根不注册，响应退化成 Flask 默认 HTML，且原实现把 `str(e)` 与 `tb[-2000:]`
    （含 `py/main.py` 源码路径与行号）一并回给客户端。去掉本层修复，
    `body["success"]` 这行即红（响应不再是 JSON）。
    """

    def test_unexpected_exception_response_hides_internals(self, client, app, monkeypatch, caplog):
        import main as main_mod

        def _boom():
            raise RuntimeError("内部炸了 D:\\server\\cc\\GG-Server\\py\\main.py:42")

        # 让工厂默认的「测试期异常上抛」让位于本用例要钉的兜底路径
        monkeypatch.setitem(app.config, "PROPAGATE_EXCEPTIONS", False)
        monkeypatch.setattr(main_mod, "_scan_fonts_dir", _boom)

        with caplog.at_level(logging.ERROR, logger="gg-server"):
            resp = client.get("/api/fonts/list", headers=_login(client, "e1user"))

        assert resp.status_code == 500
        body = resp.get_json()
        assert body is not None, "500 不再是 JSON —— 兜底处理器未注册"
        assert body["success"] is False
        assert body["error"] == "服务器内部错误，请查看控制台日志"
        assert "trace" not in body, "响应体重新带上了 traceback 字段"
        _assert_no_internal_leak(resp)
        assert "内部炸了" not in resp.get_data(as_text=True)
        # 异常详情不得丢：仍在日志里（排查能力不因脱敏而降级）
        assert "内部炸了" in caplog.text


def _login(client, username, role="user"):
    """注册 + 登录，返回认证头（E 组用例专用的小工具）。"""
    return _create_user(client, username, role=role)[0]


class TestE2PkFieldGate:
    """第二层：三个端点的 status_id / agent_id / mcc_id 补上界与类型闸门 ⇒ 400。

    合法范围 = 能安全绑进 sqlite3 的整数主键：[0, 2**63-1]。闸门口径与
    `accounts_reassign` 既有的 owner_id 闸门一致（ASCII 数字串 → int → 上界）。
    """

    PK_FIELDS = ("status_id", "agent_id", "mcc_id")
    # 数值超 int64（int 与「数字串」两种外形都覆盖：后者 TEXT 绑定会绕过 OverflowError，
    # 转而在 `PRAGMA foreign_keys=ON` 下撞外键约束）
    OVERSIZE = (2 ** 63, 10 ** 30, "9223372036854775808", "9" * 19, "9" * 30)

    def _own_account(self, client, username, account_id):
        """建一个普通用户 + 归其名下的账户，返回 (认证头, 账户主键 aid)。"""
        hdr, uid = _create_user(client, username, role="user")
        db = database.get_db()
        _mk_account(db, uid, account_id)
        aid = db.execute("SELECT id FROM accounts WHERE account_id=?", (account_id,)).fetchone()["id"]
        db.close()
        return hdr, aid

    # ---- PUT /api/accounts/<aid> -------------------------------------------

    @pytest.mark.parametrize("field", PK_FIELDS)
    def test_update_rejects_oversized_pk(self, client, field):
        hdr, aid = self._own_account(client, f"_e2_upd_{field}", "GG-E2-UPD")
        for bad in self.OVERSIZE:
            resp = client.put(f"/api/accounts/{aid}", json={field: bad}, headers=hdr)
            assert resp.status_code == 400, (
                f"update {field}={bad!r} 应 400，实得 {resp.status_code}（{resp.get_data(as_text=True)[:120]}）"
            )
            assert resp.get_json()["error"] == f"{field} 不合法"
            _assert_no_internal_leak(resp)

    @pytest.mark.parametrize("field", PK_FIELDS)
    def test_update_rejects_wrong_type_and_bool(self, client, field):
        """类型闸门：非数字串、负数、Unicode 数字、bool 一律 400（bool 是 int 子类，
        但 `str(True)=='True'` 不是数字串 ⇒ 被同一口径挡下，不会静默绑成 1）。"""
        hdr, aid = self._own_account(client, f"_e2_uty_{field}", "GG-E2-UTY")
        for bad in ("abc", "-1", "1.5", "²", "١", True, [1], {"a": 1}):
            resp = client.put(f"/api/accounts/{aid}", json={field: bad}, headers=hdr)
            assert resp.status_code == 400, (
                f"update {field}={bad!r} 应 400，实得 {resp.status_code}"
            )
            assert resp.get_json()["error"] == f"{field} 不合法"

    def test_mcc_id_empty_values_still_clear(self, client):
        """对照：mcc_id 的既有「空值/0 ⇒ 清空 MCC」语义不得被新闸门误伤。

        （`False == 0` 在 Python 为真，故 mcc_id=False 走的也是这条既有归一化路径，
        属预期的「清空」而非闸门漏放 —— 它不会绑出任何伪造主键。）
        """
        hdr, aid = self._own_account(client, "_e2_clr", "GG-E2-CLR")
        for ok in (None, 0, "0", "", False):
            resp = client.put(f"/api/accounts/{aid}", json={"mcc_id": ok}, headers=hdr)
            assert resp.status_code == 200, (
                f"mcc_id={ok!r} 应沿用『清空 MCC』走 200，实得 {resp.status_code}"
            )
            db = database.get_db()
            mcc = db.execute("SELECT mcc_id FROM accounts WHERE id=?", (aid,)).fetchone()["mcc_id"]
            db.close()
            assert mcc is None

    # ---- POST /api/accounts/batch-update ----------------------------------

    @pytest.mark.parametrize("field", PK_FIELDS)
    def test_batch_update_rejects_oversized_pk(self, client, field):
        hdr, aid = self._own_account(client, f"_e2_batch_{field}", "GG-E2-BATCH")
        for bad in self.OVERSIZE:
            resp = client.post("/api/accounts/batch-update",
                               json={"ids": [aid], "field": field, "value": bad}, headers=hdr)
            assert resp.status_code == 400, (
                f"batch-update {field}={bad!r} 应 400，实得 {resp.status_code}"
            )
            assert resp.get_json()["error"] == f"{field} 不合法"
            _assert_no_internal_leak(resp)

    # ---- PUT /api/accounts/<aid>/reassign ---------------------------------

    @pytest.mark.parametrize("field", PK_FIELDS)
    def test_reassign_rejects_oversized_pk(self, client, field):
        """reassign 的字段向量需跨用户角色、且转移到**他人**名下才走得到字段更新那段循环。"""
        dev, dev_id = _create_user(client, f"_e2_re_{field}", role="developer")
        _, target = _create_user(client, f"_e2_re_t_{field}", role="user")
        db = database.get_db()
        _mk_account(db, dev_id, "GG-E2-RE")
        aid = db.execute("SELECT id FROM accounts WHERE account_id='GG-E2-RE'").fetchone()["id"]
        db.close()
        for bad in self.OVERSIZE:
            resp = client.put(f"/api/accounts/{aid}/reassign",
                              json={"owner_id": target, field: bad}, headers=dev)
            assert resp.status_code == 400, (
                f"reassign {field}={bad!r} 应 400，实得 {resp.status_code}"
            )
            assert resp.get_json()["error"] == f"{field} 不合法"
            _assert_no_internal_leak(resp)

    # ---- 边界对照：合法上界值不得被新闸门误拦 ------------------------------

    def test_max_valid_int64_still_reaches_business_path(self, client):
        """`2**63-1` 是**合法** int64 上界 ⇒ 必须穿过闸门、落到既有业务路径。

        改前该值在 accounts_update 会绑进 sqlite 并撞外键 ⇒ 409「所属 MCC 不存在…」；
        若闸门把上界误写成 `>= 2**63 - 1`，本用例会改成 400 + `xxx 不合法` ⇒ 红。
        """
        hdr, aid = self._own_account(client, "_e2_max", "GG-E2-MAX")
        m = 2 ** 63 - 1
        for field in self.PK_FIELDS:
            resp = client.put(f"/api/accounts/{aid}", json={field: m}, headers=hdr)
            assert resp.status_code != 400, (
                f"{field}={m}（合法上界）被闸门误拦成 400"
            )
            assert resp.get_json()["error"] != f"{field} 不合法", (
                f"{field}={m}（合法上界）被格式/上界闸门拒掉"
            )
            # 走到既有业务路径：外键不存在 ⇒ 既有 409（中文），而非新的格式 400
            assert resp.status_code == 409

    def test_max_valid_int64_reassign_not_rejected_by_gate(self, client):
        """reassign 侧的同一对照：上界值不得被新闸门拦成 400「不合法」。"""
        dev, dev_id = _create_user(client, "_e2_max_re", role="developer")
        _, target = _create_user(client, "_e2_max_re_t", role="user")
        db = database.get_db()
        _mk_account(db, dev_id, "GG-E2-MAX-RE")
        aid = db.execute("SELECT id FROM accounts WHERE account_id='GG-E2-MAX-RE'").fetchone()["id"]
        db.close()
        m = 2 ** 63 - 1
        for field in self.PK_FIELDS:
            resp = client.put(f"/api/accounts/{aid}/reassign",
                              json={"owner_id": target, field: m}, headers=dev)
            assert resp.status_code != 400, f"reassign {field}={m}（合法上界）被闸门误拦"
            assert resp.get_json()["error"] != f"{field} 不合法"


class TestE3CreateOwnerParseGate:
    """追加站点 1：`POST /api/accounts/create` 的 owner 解析改用同口径闸门。

    改前是裸 `.isdigit()` —— Unicode 数字（"²"/"①"/"٣" 等）为真，但 `int()` 对它们抛
    ValueError，且该 `int()` 在 try 之外 ⇒ 500（本端点无泛 `except Exception`，异常逸出）。
    超 int64 的纯数字串则会在 sqlite 绑定处抛 OverflowError ⇒ 同样 500。

    该端点**既有语义**是「owner_id 不合规就忽略、建到自己名下」，故修复后仍应落回自己
    名下（而不是新增一种拒绝行为，也不是把账户建到伪造的 id 上）。
    """

    @pytest.mark.parametrize("bad", ["²", "①", "٣", "9" * 30, 10 ** 30, 2 ** 63])
    def test_create_with_unparsable_owner_falls_back_to_self(self, client, bad):
        """先刻意建够用户，使 id=3 真实存在：阿拉伯-印度数字 "٣" 经裸 `int()` 会解析成 3
        （Python 的 int() 接受 Unicode 十进制数字）⇒ 改前账户会被**静默建到 id=3 的用户名下**。
        断言 `owner_id == hg_id` 让这条构造同时钉住「不 500」与「不越权代建」。
        """
        hg, hg_id = _create_user(client, "_e3_hg", role="huguan")
        _create_user(client, "_e3_f2", role="user")
        _, u3 = _create_user(client, "_e3_f3", role="user")
        if bad == "٣":
            assert u3 == 3 and int(bad) == 3, "前置失败：三号用户 id 非 3，越权构造失效"
        resp = client.post("/api/accounts/create",
                           json={"name": "E3账户", "account_id": "GG-E3-1", "owner_id": bad},
                           headers=hg)
        assert resp.status_code == 200, (
            f"owner_id={bad!r} 应回落到自己名下（200），实得 {resp.status_code}"
        )
        db = database.get_db()
        own = db.execute("SELECT owner_id FROM accounts WHERE account_id='GG-E3-1'").fetchone()
        db.close()
        assert own is not None and own["owner_id"] == hg_id

    def test_create_with_valid_owner_still_honoured(self, client):
        """对照：合法 owner_id 仍必须真的建到目标用户名下（闸门不得收过头）。"""
        hg, _ = _create_user(client, "_e3_hg_ok", role="huguan")
        _, target = _create_user(client, "_e3_target", role="user")
        resp = client.post("/api/accounts/create",
                           json={"name": "E3代建", "account_id": "GG-E3-2",
                                 "owner_id": str(target)},
                           headers=hg)
        assert resp.status_code == 200
        db = database.get_db()
        own = db.execute("SELECT owner_id FROM accounts WHERE account_id='GG-E3-2'").fetchone()
        db.close()
        assert own["owner_id"] == target

    def test_max_valid_int64_owner_not_rejected_by_gate(self, client):
        """边界对照：2**63-1 是**合法** int64 ⇒ 必须穿过闸门、落到 DB 绑定上。

        判据取 409 而不是「非 500」：`accounts.owner_id` 是 `REFERENCES users(id)`，
        连接开着 `PRAGMA foreign_keys=ON` ⇒ 该值会真的走到 INSERT 并撞外键，被既有
        IntegrityError 分支接成 409。若上界误写成 `>= 2**63 - 1`，值会被静默忽略、
        target_owner 落回自己 ⇒ 建库成功 200 ⇒ 本用例红。
        """
        hg, _ = _create_user(client, "_e3_hg_max", role="huguan")
        resp = client.post("/api/accounts/create",
                           json={"name": "E3上界", "account_id": "GG-E3-3",
                                 "owner_id": str(2 ** 63 - 1)},
                           headers=hg)
        assert resp.status_code == 409, (
            f"合法上界 owner_id 未穿过闸门（实得 {resp.status_code}）—— 上界被写成 `>=`？"
        )


# TT 侧全部带 `<int:...>` 路径参数的端点：超 int64 的 id 不可能命中任何行。
# 期望 404 而非 400/500 —— 与 GG main.py 的 aid 守卫同口径（该守卫明确定调
# 「超 int64 的 id 不可能匹配任何行 ⇒ 按『账户不存在』返回 404」）。
TT_INT64_ROUTES = [
    ("put",    "/api/tt/accounts/{i}",                     None),
    ("put",    "/api/tt/accounts/{i}/reassign",            {}),
    ("delete", "/api/tt/accounts/{i}",                     None),
    ("post",   "/api/tt/accounts/{i}/restore",             None),
    ("delete", "/api/tt/accounts/{i}/permanent",           None),
    ("get",    "/api/tt/accounts/{i}/bc-history",          None),
    ("delete", "/api/tt/accounts/{i}/bc-history/{i}",      None),
    ("get",    "/api/tt/accounts/{i}/recharge-records",    None),
    ("put",    "/api/tt/recharge/{i}",                     {}),
    ("delete", "/api/tt/recharge/{i}",                     None),
    ("post",   "/api/tt/recharge/{i}/retry-sheets",        None),
    ("put",    "/api/tt/recycle-reasons/{i}",              {"name": "E4原因"}),
    ("delete", "/api/tt/recycle-reasons/{i}",              None),
]


class TestE4TtIntPathParamBounds:
    """追加站点 2：TT 侧所有 `<int:...>` 路径参数补 int64 上界。

    Werkzeug 的 IntegerConverter 只保证「能解析成 int」，不限 int64 ⇒ 超界 id 会在
    sqlite3 参数绑定处抛 OverflowError（异常逸出视图 ⇒ 500 + traceback）。把 GG 侧
    `if aid > 2**63 - 1` 的守卫补到 TT 全部 13 条带 `<int:>` 的路由上。
    """

    @pytest.mark.parametrize("method,path,body", TT_INT64_ROUTES)
    @pytest.mark.parametrize("bad", [2 ** 63, 10 ** 30, "9" * 30])
    def test_oversized_int_path_param_is_not_500(self, client, method, path, body, bad):
        hdr, _ = _create_user(client, "_e4_tt", role="user", platform="tt")
        url = path.format(i=bad)
        fn = getattr(client, method)
        resp = (fn(url, json=body, headers=hdr) if body is not None
                else fn(url, headers=hdr))
        assert resp.status_code == 404, (
            f"{method.upper()} {path} id={bad!r} 应 404，实得 {resp.status_code}"
            f"（{resp.get_data(as_text=True)[:120]}）"
        )
        _assert_no_internal_leak(resp)

    def test_max_valid_int64_tt_aid_not_rejected_by_guard(self, client):
        """边界对照：2**63-1 是**合法** int64 ⇒ 必须穿过闸门、落到既有业务路径。

        TT 各端点对不存在的账户本就回 404（与超界守卫**同码**）⇒ 单看状态码无法区分，
        故改挑 `delete_bc_history`：该端点**没有**存在性校验，穿过闸门后会真的执行
        DELETE 并回 200；而超界守卫命中时是 404「记录不存在」。用 developer 身份穿过
        它前面的「非跨用户角色 403」那层。
        """
        dev, _ = _create_user(client, "_e4_tt_max", role="developer")
        m = 2 ** 63 - 1
        resp = client.delete(f"/api/tt/accounts/{m}/bc-history/{m}", headers=dev)
        assert resp.status_code == 200, (
            f"合法上界 id 被闸门误拦（实得 {resp.status_code}）—— 上界被写成 `>=`？"
        )


# ---------------------------------------------------------------------------
# E 组（续）：上一轮登记、未闭的同族泄露路径收口
#   E-5 `accounts_reassign` 自己的终末 `except` 不再回显 `str(e)`
#       （它**绕过**全局 500 兜底 —— 端点自己吞了异常）
#   E-6 GG 侧 `<int:aid>` 路径参数补 int64 上界（与 TT 侧同口径 404）
#   E-7 `batch-update` / `batch-delete` 的 `ids` **数组元素**过闸门
#   E-8 `accounts_create` 的 status_id / agent_id / mcc_id 过闸门
# ---------------------------------------------------------------------------

# 固定脱敏文案 —— 与全局 500 兜底（main.py 的 `internal_error`）**逐字节一致**，
# 沿用仓库既有措辞，不自创。
SANITIZED_500 = "服务器内部错误，请查看控制台日志"


class TestE5SelfSwallowedExceptIsSanitized:
    """端点自带终末 `except` 时，第一层全局兜底**管不到**它 ⇒ 必须自己脱敏。

    `accounts_reassign` 尾部是 `except Exception as e: ... jsonify(error=str(e)), 500`。
    走 `{owner_id: <他人>, status_id: 999999}`：999999 是**合法 int64**（过第二层闸门），
    但库里没有该行 ⇒ UPDATE 撞 `PRAGMA foreign_keys=ON` ⇒ IntegrityError ⇒ 被本端点
    自己的 except 吞下并回 `str(e)`（"FOREIGN KEY constraint failed"）。
    改前该文案直出客户端（CWE-209）；改后为固定中文，且详情仍进日志。
    """

    def _dev_with_account(self, client, tag):
        dev, dev_id = _create_user(client, f"_e5_dev_{tag}", role="developer")
        _, target = _create_user(client, f"_e5_tgt_{tag}", role="user")
        db = database.get_db()
        _mk_account(db, dev_id, f"GG-E5-{tag}")
        aid = db.execute("SELECT id FROM accounts WHERE account_id=?", (f"GG-E5-{tag}",)).fetchone()["id"]
        db.close()
        return dev, dev_id, target, aid

    def test_fk_violation_returns_fixed_chinese_message(self, client, caplog):
        dev, _dev_id, target, aid = self._dev_with_account(client, "fk")
        with caplog.at_level(logging.ERROR, logger="gg-server"):
            resp = client.put(f"/api/accounts/{aid}/reassign",
                              json={"owner_id": target, "status_id": 999999},
                              headers=dev)
        assert resp.status_code == 500, (
            f"reassign 撞外键应仍回既有 500（状态码不在本任务范围），实得 {resp.status_code}"
        )
        body = resp.get_json()
        assert body is not None, "响应不再是 JSON"
        assert body["error"] == SANITIZED_500, (
            f"终末 except 仍回显英文异常原文：{body['error']!r}"
        )
        _assert_no_internal_leak(resp)
        assert "FOREIGN KEY" not in resp.get_data(as_text=True)
        # 异常详情不得被一起砍掉：仍须进 gg-server 日志（用 caplog 钉住）
        assert "FOREIGN KEY constraint failed" in caplog.text, (
            "异常详情没进日志 —— 排查线索被脱敏一并砍掉了"
        )

    def test_sibling_terminal_except_accounts_update_also_sanitized(self, client, monkeypatch, caplog):
        """同一模式的其他站点（`accounts_update` 终末 except）也必须脱敏 —— 断点式验证。

        `accounts_update` 里 `_record_mcc_change` 抛非 IntegrityError 的异常时会落到它
        自己的 `except Exception as e: str(e)`（绕过全局兜底）。把它 patch 成炸掉，
        钉住响应文案 + 日志仍留详情。
        """
        import main as main_mod

        hdr, uid = _create_user(client, "_e5_upd", role="user")
        db = database.get_db()
        _mk_account(db, uid, "GG-E5-UPD")
        aid = db.execute("SELECT id FROM accounts WHERE account_id='GG-E5-UPD'").fetchone()["id"]
        db.close()

        def _boom(*_a, **_k):
            raise RuntimeError("内部炸了 D:\\server\\cc\\GG-Server\\py\\main.py:42")

        monkeypatch.setattr(main_mod, "_record_mcc_change", _boom)
        with caplog.at_level(logging.ERROR, logger="gg-server"):
            resp = client.put(f"/api/accounts/{aid}", json={"mcc_id": 1}, headers=hdr)

        assert resp.status_code == 500
        assert resp.get_json()["error"] == SANITIZED_500, (
            f"accounts_update 终末 except 仍回显原文：{resp.get_json()['error']!r}"
        )
        _assert_no_internal_leak(resp)
        assert "内部炸了" not in resp.get_data(as_text=True)
        assert "内部炸了" in caplog.text, "异常详情没进日志"


# GG 侧带 `<int:aid>` 的全部路由（Werkzeug IntegerConverter 无上界）。超 int64 的 id
# 不可能命中任何行 ⇒ 与 TT 侧/既有 reassign aid 守卫同口径：404「账户不存在」。
GG_INT_AID_ROUTES = [
    ("put",    "/api/accounts/{i}",                   {}),
    ("delete", "/api/accounts/{i}",                   None),
    ("post",   "/api/accounts/{i}/restore",           None),
    ("delete", "/api/accounts/{i}/permanent",         None),
    ("get",    "/api/accounts/{i}/recharge-records",  None),
    ("get",    "/api/accounts/{i}/mcc-history",       None),
    ("delete", "/api/accounts/{i}/mcc-history/{i}",   None),
    # `/api/agents/<int:aid>` 的参数名同样是 `aid`、同样直接进 sqlite 绑定 ⇒ 同族。
    ("put",    "/api/agents/{i}",                     {"name": "E6代理"}),
    ("delete", "/api/agents/{i}",                     None),
]


class TestE6GgIntAidPathParamBounds:
    """GG 侧 `<int:aid>` 补 int64 上界（上一轮只补了 TT 侧）。

    改前：`PUT/DELETE /api/accounts/<10**30>` 等会在 sqlite3 绑定处抛 OverflowError
    （无 try 的直接逸出视图 ⇒ 500 + traceback；有 try 的回 `str(e)` 英文原文）。
    """

    @pytest.mark.parametrize("method,path,body", GG_INT_AID_ROUTES)
    @pytest.mark.parametrize("bad", [2 ** 63, 10 ** 30, "9" * 30])
    def test_oversized_aid_is_404_not_500(self, client, method, path, body, bad):
        hdr, _ = _create_user(client, "_e6_gg", role="developer")
        url = path.format(i=bad)
        fn = getattr(client, method)
        resp = (fn(url, json=body, headers=hdr) if body is not None
                else fn(url, headers=hdr))
        assert resp.status_code == 404, (
            f"{method.upper()} {path} aid={bad!r} 应 404，实得 {resp.status_code}"
            f"（{resp.get_data(as_text=True)[:120]}）"
        )
        _assert_no_internal_leak(resp)

    def test_max_valid_int64_aid_passes_guard(self, client):
        """边界对照：2**63-1 是**合法** int64 ⇒ 必须穿过守卫、落到既有业务路径。

        取 `DELETE /api/accounts/<m>`：守卫命中回 404「账户不存在」，而该值能正常绑定、
        查无此行时回**既有** 404「账户不存在或已删除」—— 文案不同即可区分是否穿过守卫。
        若上界被误写成 `>= 2**63 - 1`，文案会变成「账户不存在」⇒ 本用例红。
        """
        hdr, _ = _create_user(client, "_e6_max", role="developer")
        m = 2 ** 63 - 1
        resp = client.delete(f"/api/accounts/{m}", headers=hdr)
        assert resp.status_code == 404
        assert resp.get_json()["error"] == "账户不存在或已删除", (
            f"合法上界 aid 被守卫误拦（文案 {resp.get_json()['error']!r}）"
        )


class TestE7BatchIdsArrayGate:
    """`ids` 数组**元素**是独立向量：归属过滤的 `IN (?)` 与逐条 UPDATE/DELETE 都会绑定它。

    改前 `ids=[10**30]` ⇒ OverflowError（无 try 的逸出视图 ⇒ 500 + traceback）。
    """

    OVERSIZE = (2 ** 63, 10 ** 30, "9" * 30)

    def _body(self, endpoint, ids):
        if endpoint == "batch-update":
            return {"ids": ids, "field": "status_id", "value": 1}
        return {"ids": ids}

    @pytest.mark.parametrize("endpoint", ["batch-update", "batch-delete"])
    @pytest.mark.parametrize("bad", OVERSIZE)
    def test_oversized_id_element_is_400(self, client, endpoint, bad):
        hdr, _ = _create_user(client, f"_e7_{endpoint}", role="user")
        resp = client.post(f"/api/accounts/{endpoint}", json=self._body(endpoint, [bad]), headers=hdr)
        assert resp.status_code == 400, (
            f"{endpoint} ids=[{bad!r}] 应 400，实得 {resp.status_code}"
            f"（{resp.get_data(as_text=True)[:120]}）"
        )
        assert resp.get_json()["error"] == "ids 不合法"
        _assert_no_internal_leak(resp)

    @pytest.mark.parametrize("endpoint", ["batch-update", "batch-delete"])
    def test_oversized_id_mixed_with_valid_element_still_400(self, client, endpoint):
        """混入一个合法元素也必须整体拒绝 —— 逐个元素都过闸门，不是只看第一个。"""
        hdr, uid = _create_user(client, f"_e7_mix_{endpoint}", role="user")
        db = database.get_db()
        _mk_account(db, uid, f"GG-E7-{endpoint}")
        aid = db.execute("SELECT id FROM accounts WHERE account_id=?", (f"GG-E7-{endpoint}",)).fetchone()["id"]
        db.close()
        resp = client.post(f"/api/accounts/{endpoint}", json=self._body(endpoint, [aid, 10 ** 30]), headers=hdr)
        assert resp.status_code == 400, (
            f"{endpoint} ids=[valid, 10**30] 应 400，实得 {resp.status_code}"
        )

    @pytest.mark.parametrize("endpoint", ["batch-update", "batch-delete"])
    def test_max_valid_int64_id_element_passes_gate(self, client, endpoint):
        """边界对照：2**63-1 合法 ⇒ 穿过闸门，落到既有业务路径（而非新的 400）。

        - batch-delete：无归属预检，逐条 UPDATE 命中 0 行 ⇒ 既有 `200 + deleted=0`；
        - batch-update：归属预检 COUNT=0 ≠ len(ids) ⇒ 既有 `403 包含无权操作的账户`。
        """
        hdr, _ = _create_user(client, f"_e7_max_{endpoint}", role="user")
        m = 2 ** 63 - 1
        resp = client.post(f"/api/accounts/{endpoint}", json=self._body(endpoint, [m]), headers=hdr)
        assert resp.status_code != 400, f"{endpoint} ids=[2**63-1] 被闸门误拦成 400"
        assert resp.get_json().get("error") != "ids 不合法"
        if endpoint == "batch-delete":
            assert resp.status_code == 200 and resp.get_json()["deleted"] == 0
        else:
            assert resp.status_code == 403


class TestE8CreatePkFieldGate:
    """`accounts_create` 的 status_id / agent_id / mcc_id 仍是裸绑定（上一轮只修了 owner 解析）。

    改前：超 int64 ⇒ sqlite3 绑定处 OverflowError（本端点只 catch IntegrityError ⇒
    异常逸出视图 ⇒ 500 + traceback）。
    """

    PK_FIELDS = ("status_id", "agent_id", "mcc_id")
    OVERSIZE = (2 ** 63, 10 ** 30, "9" * 30)

    @pytest.mark.parametrize("field", PK_FIELDS)
    def test_create_rejects_oversized_pk(self, client, field):
        hdr, _ = _create_user(client, f"_e8_{field}", role="user")
        for n, bad in enumerate(self.OVERSIZE):
            resp = client.post("/api/accounts/create",
                               json={"name": "E8账户", "account_id": f"GG-E8-{field}-{n}", field: bad},
                               headers=hdr)
            assert resp.status_code == 400, (
                f"create {field}={bad!r} 应 400，实得 {resp.status_code}"
                f"（{resp.get_data(as_text=True)[:120]}）"
            )
            assert resp.get_json()["error"] == f"{field} 不合法"
            _assert_no_internal_leak(resp)

    @pytest.mark.parametrize("field", PK_FIELDS)
    def test_create_rejects_wrong_type(self, client, field):
        hdr, _ = _create_user(client, f"_e8_ty_{field}", role="user")
        for bad in ("abc", "-1", "²", "١", True, [1]):
            resp = client.post("/api/accounts/create",
                               json={"name": "E8账户", "account_id": f"GG-E8-TY-{field}", field: bad},
                               headers=hdr)
            assert resp.status_code == 400, (
                f"create {field}={bad!r} 应 400，实得 {resp.status_code}"
            )
            assert resp.get_json()["error"] == f"{field} 不合法"

    def test_create_max_valid_int64_status_id_reaches_business_path(self, client):
        """边界对照：2**63-1 合法 ⇒ 穿过闸门、真的走到 INSERT 并撞外键 ⇒ 既有 409。

        若上界被误写成 `>=`，值会被闸门拦成 400「status_id 不合法」⇒ 本用例红。
        """
        hdr, _ = _create_user(client, "_e8_max", role="user")
        resp = client.post("/api/accounts/create",
                           json={"name": "E8上界", "account_id": "GG-E8-MAX",
                                 "status_id": 2 ** 63 - 1},
                           headers=hdr)
        assert resp.status_code == 409, (
            f"合法上界 status_id 未穿过闸门（实得 {resp.status_code}）—— 上界被写成 `>=`？"
        )

    def test_create_mcc_id_empty_still_clears(self, client):
        """对照：mcc_id 的既有「空值/0 ⇒ 清空」语义不得被新闸门误伤。

        注：本端点把 mcc_id 写进 INSERT 用的是 `data.get("mcc_id") or None`，故
        `None` / `0` / `""` 三个**假值**都会被归一成 NULL；而字符串 `"0"` 是**真值**、
        既有的 create 路径本就不清空它（会走到 FK 校验）—— 该不对称是既有行为，
        不在本任务范围，故此处不构造 `"0"`。
        """
        hdr, _ = _create_user(client, "_e8_clr", role="user")
        for n, ok in enumerate((None, 0, "")):
            resp = client.post("/api/accounts/create",
                               json={"name": "E8清空", "account_id": f"GG-E8-CLR-{n}", "mcc_id": ok},
                               headers=hdr)
            assert resp.status_code == 200, (
                f"mcc_id={ok!r} 应沿用既有『清空』走 200，实得 {resp.status_code}"
            )


# ---------------------------------------------------------------------------
# E 组续：直接内插异常原文的 f-string 站点（上一轮 grep `str(e)` 漏掉的形态）
#   `f"…: {e}"` —— 异常原文经 f-string 直接拼进响应体
# ---------------------------------------------------------------------------
# 固定脱敏文案（与前面 SANITIZED_500 同族措辞：原文换成固定中文，详情进日志）
SANITIZED_INTEGRITY = "数据完整性错误，详情见服务端日志"
SANITIZED_CREATE_DIR = "无法创建目录，详情见服务端日志"
SANITIZED_OUT_DIR = "无法创建输出目录，详情见服务端日志"
SANITIZED_READ_SHEET = "无法读取表格，详情见服务端日志"
SANITIZED_UNKNOWN = "未知错误，详情见服务端日志"
SANITIZED_ACCESS_SHEET = "无法访问表格，详情见服务端日志"
SANITIZED_TT_IMPORT = "导入失败，请查看服务端日志"

# 这些站点泄露的「内部细节」形态：schema/列名、文件系统路径、英文库异常。
# 比 LEAK_MARKERS 更贴本组（列名与 constraint 原文不在 LEAK_MARKERS 里）。
SCHEMA_LEAK_MARKERS = ("constraint failed", "NOT NULL", "UNIQUE", "accounts.",
                       "account_statuses", "Permission denied", "Errno", "has no attribute")


def _assert_no_schema_leak(resp):
    raw = resp.get_data(as_text=True)
    for marker in SCHEMA_LEAK_MARKERS:
        assert marker not in raw, f"响应体泄露内部细节 {marker!r}: {raw[:200]!r}"


class TestE9InterpolatedExceptionIsSanitized:
    """`f"…: {e}"` 直接内插异常原文的响应站点全部换固定文案，详情进日志。

    上一轮的 grep 串是 `str(e)`，看不见这种内插形态。每处都用一个**真实的异常**
    （真 sqlite3.IntegrityError / 真 OSError / 真实抛出的通用异常）驱动对应分支：
    去掉本批修复，响应体即回显 schema 列名 / 绝对路径 / 英文库异常 ⇒ 断言转红。
    """

    # ---- :4518 accounts_create 的通用 IntegrityError 分支（非 FK / 非 UNIQUE）----
    def test_accounts_create_generic_integrity_error_is_sanitized(self, client, monkeypatch, caplog):
        import sqlite3
        import main as main_mod

        def _boom(*_a, **_k):
            # 真 sqlite3.IntegrityError，文案取 SQLite 对 NOT NULL 违规的**真实措辞**
            raise sqlite3.IntegrityError(
                "NOT NULL constraint failed: account_statuses.owner_id")

        monkeypatch.setattr(main_mod, "_gg_status_id", _boom)
        hdr, _ = _create_user(client, "_e9_crt", role="user")
        with caplog.at_level(logging.ERROR, logger="gg-server"):
            resp = client.post("/api/accounts/create",
                               json={"name": "E9建", "account_id": "GG-E9-CRT", "status": "存活"},
                               headers=hdr)
        assert resp.status_code == 409
        body = resp.get_json()
        assert body["error"] == SANITIZED_INTEGRITY, (
            f"create 的通用分支仍回显异常原文：{body['error']!r}")
        _assert_no_schema_leak(resp)
        _assert_no_internal_leak(resp)
        assert "NOT NULL constraint failed: account_statuses.owner_id" in caplog.text, (
            "异常详情没进日志 —— 排查线索被脱敏一并砍掉了")

    # ---- :4798 accounts_update 的通用 IntegrityError 分支（真实 HTTP 可达）----
    def test_accounts_update_notnull_violation_is_sanitized(self, client, caplog):
        """真实路径：PUT /api/accounts/{id} body `{"name": null}`。

        `name` 列是 NOT NULL，且 `name` 不在 update 的 pk 闸门白名单里 ⇒ 原样
        绑进 UPDATE ⇒ SQLite 抛 IntegrityError("NOT NULL constraint failed:
        accounts.name")，且不含 foreign key ⇒ 落到 :4798 的通用分支。
        """
        hdr, uid = _create_user(client, "_e9_upd", role="user")
        db = database.get_db()
        _mk_account(db, uid, "GG-E9-UPD")
        aid = db.execute("SELECT id FROM accounts WHERE account_id='GG-E9-UPD'").fetchone()["id"]
        db.close()

        with caplog.at_level(logging.ERROR, logger="gg-server"):
            resp = client.put(f"/api/accounts/{aid}", json={"name": None}, headers=hdr)
        assert resp.status_code == 409, (
            f"NOT NULL 违规应落 IntegrityError 分支回 409，实得 {resp.status_code}")
        body = resp.get_json()
        assert body["error"] == SANITIZED_INTEGRITY, (
            f"update 的通用分支仍回显 schema 列名：{body['error']!r}")
        _assert_no_schema_leak(resp)
        _assert_no_internal_leak(resp)
        assert "NOT NULL constraint failed: accounts.name" in caplog.text, (
            "异常详情没进日志")

    # ---- :689 scrape 建目录失败 ----
    def test_scrape_makedirs_failure_is_sanitized(self, client, monkeypatch, caplog):
        import os as _os
        import main as main_mod

        _real_makedirs = _os.makedirs

        def _boom(path, *a, **k):
            if str(path).endswith("com.e9.app"):
                raise OSError(13, "Permission denied", str(path))
            return _real_makedirs(path, *a, **k)

        monkeypatch.setattr(main_mod.os, "makedirs", _boom)
        hdr, _ = _create_user(client, "_e9_scr", role="user")
        with caplog.at_level(logging.ERROR, logger="gg-server"):
            resp = client.post(
                "/api/scrape",
                json={"url": "https://play.google.com/store/apps/details?id=com.e9.app"},
                headers=hdr)
        assert resp.status_code == 500
        assert resp.get_json()["error"] == SANITIZED_CREATE_DIR, (
            f"scrape 建目录失败仍回显路径：{resp.get_json()['error']!r}")
        assert "Permission denied" not in resp.get_data(as_text=True)
        assert "com.e9.app" not in resp.get_data(as_text=True), "响应体泄露了服务端绝对路径"
        assert "Permission denied" in caplog.text, "OSError 详情没进日志"

    # ---- :1064 video_generate 建输出目录失败 ----
    def test_video_generate_makedirs_failure_is_sanitized(self, client, monkeypatch, caplog):
        import os as _os
        import main as main_mod

        _real_makedirs = _os.makedirs

        def _boom(path, *a, **k):
            if str(path).replace("/", "\\").rstrip("\\").endswith("e9out"):
                raise OSError(13, "Permission denied", str(path))
            return _real_makedirs(path, *a, **k)

        monkeypatch.setattr(main_mod.os, "makedirs", _boom)
        hdr, _ = _create_user(client, "_e9_vid", role="user")
        with caplog.at_level(logging.ERROR, logger="gg-server"):
            resp = client.post("/api/video/generate",
                               json={"images": ["a.png"],
                                     "settings": {"output_path": r"D:\e9out\v.mp4"}},
                               headers=hdr)
        assert resp.status_code == 400
        assert resp.get_json()["error"] == SANITIZED_OUT_DIR, (
            f"video 建输出目录失败仍回显路径：{resp.get_json()['error']!r}")
        assert "Permission denied" not in resp.get_data(as_text=True)
        assert "e9out" not in resp.get_data(as_text=True), "响应体泄露了落盘绝对路径"
        assert "Permission denied" in caplog.text, "OSError 详情没进日志"

    # ---- :5302 sync-from-sheet 读表失败 ----
    def test_sync_from_sheet_generic_error_is_sanitized(self, client, monkeypatch, caplog, tmp_path):
        import main as main_mod
        import google_sheets_service as gs

        creds = tmp_path / "creds.json"
        creds.write_text("{}")
        monkeypatch.setattr(main_mod, "_GOOGLE_SHEETS_CONFIG",
                            {"credentials_path": str(creds)})
        monkeypatch.setattr(main_mod, "_get_sync_spreadsheet_id", lambda db: "FAKE_SHEET")
        monkeypatch.setattr(main_mod, "_get_my_dashboard_name", lambda db, uid: "看板")

        def _boom(*_a, **_k):
            raise ValueError("内部炸了 D:\\server\\cc\\GG-Server\\py\\x.py:1")

        monkeypatch.setattr(gs, "build_service", _boom)
        hdr, _ = _create_user(client, "_e9_sync", role="user")
        with caplog.at_level(logging.ERROR, logger="gg-server"):
            resp = client.post("/api/accounts/sync-from-sheet", json={}, headers=hdr)
        assert resp.status_code == 400
        assert resp.get_json()["error"] == SANITIZED_READ_SHEET, (
            f"读表失败仍回显原文：{resp.get_json()['error']!r}")
        assert "内部炸了" not in resp.get_data(as_text=True)
        _assert_no_internal_leak(resp)
        assert "内部炸了" in caplog.text, "异常详情没进日志"

    # ---- :8022 google-ads 账户列表未知错误 ----
    def test_google_ads_accounts_unknown_error_is_sanitized(self, client, monkeypatch, caplog):
        import google_ads_service as gas
        hdr, _ = _create_user(client, "_e9_ads1", role="user")

        def _boom(*_a, **_k):
            raise ValueError("内部炸了 D:\\server\\cc\\GG-Server\\py\\x.py:2")

        monkeypatch.setattr(gas, "list_accounts", _boom)
        with caplog.at_level(logging.ERROR, logger="gg-server"):
            resp = client.post("/api/google-ads/accounts", json={}, headers=hdr)
        assert resp.status_code == 500
        assert resp.get_json()["error"] == SANITIZED_UNKNOWN, (
            f"google-ads/accounts 仍回显原文：{resp.get_json()['error']!r}")
        assert "内部炸了" not in resp.get_data(as_text=True)
        _assert_no_internal_leak(resp)
        assert "内部炸了" in caplog.text, "异常详情没进日志"

    # ---- :8052 google-ads 报告未知错误 ----
    def test_google_ads_report_unknown_error_is_sanitized(self, client, monkeypatch, caplog):
        import google_ads_service as gas
        hdr, _ = _create_user(client, "_e9_ads2", role="user")

        def _boom(*_a, **_k):
            raise ValueError("内部炸了 D:\\server\\cc\\GG-Server\\py\\x.py:3")

        monkeypatch.setattr(gas, "fetch_campaign_report", _boom)
        with caplog.at_level(logging.ERROR, logger="gg-server"):
            resp = client.post("/api/google-ads/report",
                               json={"account_id": "1", "start_date": "2026-01-01",
                                     "end_date": "2026-01-31"}, headers=hdr)
        assert resp.status_code == 500
        assert resp.get_json()["error"] == SANITIZED_UNKNOWN, (
            f"google-ads/report 仍回显原文：{resp.get_json()['error']!r}")
        assert "内部炸了" not in resp.get_data(as_text=True)
        assert "内部炸了" in caplog.text, "异常详情没进日志"

    # ---- :8168 google-sheets 列表读取失败（同形态站点，任务表未列）----
    def test_google_sheets_list_sheets_unknown_error_is_sanitized(self, client, monkeypatch, caplog, tmp_path):
        import main as main_mod
        import google_sheets_service as gs

        creds = tmp_path / "creds.json"
        creds.write_text("{}")
        monkeypatch.setattr(main_mod, "_GOOGLE_SHEETS_CONFIG",
                            {"credentials_path": str(creds)})

        def _boom(*_a, **_k):
            raise ValueError("内部炸了 D:\\server\\cc\\GG-Server\\py\\x.py:4")

        monkeypatch.setattr(gs, "build_service", _boom)
        hdr, _ = _create_user(client, "_e9_sht", role="user")
        with caplog.at_level(logging.ERROR, logger="gg-server"):
            resp = client.get("/api/google-sheets/sheets?spreadsheet_id=abc", headers=hdr)
        assert resp.status_code == 400
        assert resp.get_json()["error"] == SANITIZED_ACCESS_SHEET, (
            f"sheets 列表仍回显原文：{resp.get_json()['error']!r}")
        assert "内部炸了" not in resp.get_data(as_text=True)
        assert "内部炸了" in caplog.text, "异常详情没进日志"

    # ---- routes/tt_routes.py TT 数据导入失败（同形态，单引号 f-string）----
    def test_tt_data_import_error_is_sanitized(self, client, caplog):
        import io
        import json as _json

        hdr, _ = _create_user(client, "_e9_tt", role="user", platform="tt")
        # 结构合法但类型畸形：bc_id 是 list ⇒ (bc.get('bc_id') or '').strip() 抛
        # AttributeError（英文库异常），被迫落到本端点的通用 except。
        payload = {"data": {"bcs": [{"id": 1, "bc_id": ["not-a-string"]}]}}
        with caplog.at_level(logging.ERROR, logger="gg-server"):
            resp = client.post(
                "/api/tt/data/import",
                data={"file": (io.BytesIO(_json.dumps(payload).encode()), "x.json")},
                content_type="multipart/form-data", headers=hdr)
        body = resp.get_json()
        assert body.get("success") is False, f"导入畸形载荷应回业务失败：{body!r}"
        assert body.get("error") == SANITIZED_TT_IMPORT, (
            f"TT 导入失败仍回显异常原文：{body.get('error')!r}")
        assert "has no attribute" not in resp.get_data(as_text=True)
        assert "has no attribute" in caplog.text, "异常详情没进日志"


# ---------------------------------------------------------------------------
# E-11：异常文本「落库 / 落任务状态 → 读取端点回出」的数据流收口
#
# 前三轮失败的原因是每轮只 grep 一个字符串字面量（`str(e)` → `{e}` → 单引号变体），
# 只能修到上一轮那个 grep 串命中的站点。本组改按**数据流**收口：
#     异常 → 落 DB 列 / 任务 message → 读取端点回进响应体
# 逐站点点名，每个站点都用**真实异常**驱动，去掉修复即红。
# ---------------------------------------------------------------------------

# 本组泄露的「内部细节」形态：英文库异常名、上游 URL、服务端绝对路径、schema 约束。
E11_LEAK_MARKERS = (
    "HttpError", "googleapis.com", "HTTPSConnectionPool", "Max retries exceeded",
    "Expecting value", "Permission denied", "Errno", "constraint failed",
    "UNIQUE", "Traceback", "No such file", "english boom",
)


def _assert_no_e11_leak(target):
    raw = target if isinstance(target, str) else target.get_data(as_text=True)
    for marker in E11_LEAK_MARKERS:
        assert marker not in raw, f"响应体泄露内部细节 {marker!r}: {raw[:300]!r}"


class _InlineThread:
    """把 `threading.Thread(target=...).start()` 就地同步跑完。

    后台写表线程在测试里同步执行 ⇒ 断言不必靠轮询撞时序（`_sync_sheets_background`
    起的就是这种 daemon 线程）。`daemon` / 其余 kwargs 一律忽略。
    """

    def __init__(self, target=None, daemon=None, args=(), kwargs=None):
        self._target = target
        self._args = args
        self._kwargs = kwargs or {}

    def start(self):
        self._target(*self._args, **self._kwargs)

    def join(self, timeout=None):
        pass


@pytest.fixture
def inline_bg(monkeypatch):
    """让 main 的后台 Sheets 线程同步执行，并跳过 30s 重试睡眠。"""
    import main as main_mod
    monkeypatch.setattr(main_mod.threading, "Thread", _InlineThread)
    monkeypatch.setattr("time.sleep", lambda _s: None)


def _gg_account(client, username, account_id):
    """建一个普通 GG 用户 + 归其名下的账户，返回 (认证头, 账户主键 aid, 账户ID)。"""
    hdr, uid = _create_user(client, username, role="user")
    db = database.get_db()
    _mk_account(db, uid, account_id)
    aid = db.execute("SELECT id FROM accounts WHERE account_id=?", (account_id,)).fetchone()["id"]
    db.close()
    return hdr, aid, account_id


def _boom_sheets(*_a, **_k):
    """模拟 Google Sheets 上游失败：异常原文含上游 URL（英文库异常）。"""
    import google_sheets_service as gs
    raise gs.GoogleSheetsServiceError(
        "读取工作表失败: <HttpError 404 returned \"Not Found\". Details: "
        "\"Requested entity was not found.\"> https://sheets.googleapis.com/v4/spreadsheets/SHEET-E11")


class TestE11RechargeSheetsErrorSink:
    """item-3：`recharge_records.sheets_error` 由后台回调写入、被 GET recharge-records 回出。

    两个写入点都点名：
      - `recharge_retry_sheets`（同步 try/except，直写该列）；
      - 充值提交 / 批量提交的后台 `_on_fail` 回调。
    """

    def test_retry_sheets_writes_fixed_text_not_raw_exception(self, client, monkeypatch, caplog, inline_bg):
        """item-3 在新架构下的等价守卫。

        二期把 `POST /api/recharge/<rid>/retry-sheets` 改成**转调统一写表入口**
        （设计 §5.3：同步重放 → 提交后立即返回，是有意的语义变更）；
        失败不再写 `recharge_records.sheets_error`，改由 `sheet_write_log` 承担。
        安全属性不变：**异常原文不得经任何回给客户端的字段外泄**。
        """
        import main as main_mod
        import sheet_write
        import google_sheets_service as gs

        hdr, aid, acc = _gg_account(client, "_e11_retry", "GG-E11-RETRY")
        db = database.get_db()
        db.execute("INSERT INTO recharge_records (account_id, amount, operator, created_by) "
                   "VALUES (?, '100', 'x', 1)", (acc,))
        rid = db.execute("SELECT last_insert_rowid()").fetchone()[0]
        db.commit(); db.close()

        monkeypatch.setattr(main_mod, "_get_sync_spreadsheet_id", lambda db: "SHEET-E11")
        monkeypatch.setattr(main_mod, "_get_recharge_sheet_name", lambda db: "充值表")
        monkeypatch.setattr(gs, "build_service", lambda path: object())
        monkeypatch.setattr(gs, "append_recharge", _boom_sheets)

        with caplog.at_level(logging.ERROR, logger="gg-server"):
            resp = client.post(f"/api/recharge/{rid}/retry-sheets", headers=hdr)
        # 新语义：提交后立即返回，不再同步重放、不再 500
        assert resp.status_code == 200, resp.get_data(as_text=True)[:200]
        _assert_no_e11_leak(resp)

        # 安全属性①：已退场的列不得被写入任何东西（更不得含异常原文）
        recs = client.get(f"/api/accounts/{aid}/recharge-records", headers=hdr).get_json()["records"]
        row = next(r for r in recs if r["id"] == rid)
        _assert_no_e11_leak(json.dumps(recs, ensure_ascii=False))
        assert row["sheets_error"] in ("", None), (
            f"sheets_error 已退场、不得被写：{row['sheets_error']!r}")

        # 安全属性②：失败改由统一机制承担，且落库的是固定文案
        db = database.get_db()
        log_row = db.execute("SELECT * FROM sheet_write_log WHERE target='gg_recharge' "
                             "AND business_key=?", (str(rid),)).fetchone()
        db.close()
        assert log_row is not None, "重试必须登记进统一写表机制"
        assert log_row["status"] == "retry_failed"
        assert log_row["error_msg"] == sheet_write._WRITE_FAILED_MSG, (
            f"落库文案应为固定文案，实际 {log_row['error_msg']!r}")
        _assert_no_e11_leak(log_row["error_msg"] or "")
        # 异常详情不得被一并砍掉
        assert "sheets.googleapis.com" in caplog.text, "异常详情没进日志"

    def test_submit_background_on_fail_writes_fixed_text(self, client, monkeypatch, caplog, inline_bg):
        """充值提交的后台失败在新架构下的等价守卫（同上：原文不外泄）。"""
        import main as main_mod
        import sheet_write
        import google_sheets_service as gs

        hdr, aid, acc = _gg_account(client, "_e11_submit", "GG-E11-SUBMIT")
        monkeypatch.setattr(main_mod, "_get_sync_spreadsheet_id", lambda db: "SHEET-E11")
        monkeypatch.setattr(main_mod, "_get_recharge_sheet_name", lambda db: "充值表")
        monkeypatch.setattr(gs, "build_service", lambda path: object())
        monkeypatch.setattr(gs, "append_recharge", _boom_sheets)

        with caplog.at_level(logging.ERROR, logger="gg-server"):
            resp = client.post("/api/recharge/submit",
                               json={"account_id": acc, "amount": "100"}, headers=hdr)
        assert resp.status_code == 200, resp.get_data(as_text=True)[:200]

        # 安全属性①：退场的列不得被写
        recs = client.get(f"/api/accounts/{aid}/recharge-records", headers=hdr).get_json()["records"]
        assert recs, "充值记录应出现在列表里"
        _assert_no_e11_leak(json.dumps(recs, ensure_ascii=False))
        assert recs[0]["sheets_error"] in ("", None), (
            f"sheets_error 已退场、不得被写：{[r['sheets_error'] for r in recs]!r}")

        # 安全属性②：失败落统一机制，文案固定
        rid = recs[0]["id"]
        db = database.get_db()
        log_row = db.execute("SELECT * FROM sheet_write_log WHERE target='gg_recharge' "
                             "AND business_key=?", (str(rid),)).fetchone()
        db.close()
        assert log_row is not None, "后台写表失败必须登记"
        assert log_row["status"] == "retry_failed"
        assert log_row["error_msg"] == sheet_write._WRITE_FAILED_MSG, (
            f"落库文案应为固定文案，实际 {log_row['error_msg']!r}")
        _assert_no_e11_leak(log_row["error_msg"] or "")
        assert "sheets.googleapis.com" in caplog.text, "异常详情没进日志"


class TestE11TtRechargeSheetsErrorSink:
    """同族站点（结论文件未列）：TT 侧 `tt_recharge_records.sheets_error` 同形状同链路。

    写点 `routes/tt_accounts_routes.py` 的 `_on_fail`，读点
    `GET /api/tt/accounts/<aid>/recharge-records`（`SELECT r.*` + `dict(r)`）。
    """

    def test_tt_background_on_fail_writes_fixed_text(self, client, monkeypatch, caplog, inline_bg):
        import main as main_mod
        import google_sheets_service as gs
        from routes import tt_accounts_routes as ttr

        hdr, uid = _create_user(client, "_e11_tt", role="user", platform="tt")
        db = database.get_db()
        db.execute("INSERT INTO tt_accounts (advertiser_id, owner_id, name) VALUES (?,?,?)",
                   ("TT-E11-ACC", uid, "TT账户"))
        aid = db.execute("SELECT id FROM tt_accounts WHERE advertiser_id='TT-E11-ACC'").fetchone()["id"]
        db.execute("INSERT INTO tt_recharge_records (account_id, amount, operator, created_by) "
                   "VALUES ('TT-E11-ACC', '100', 'x', ?)", (uid,))
        rid = db.execute("SELECT last_insert_rowid()").fetchone()[0]
        db.commit(); db.close()

        monkeypatch.setattr(gs, "build_service", lambda path: object())
        monkeypatch.setattr(gs, "append_recharge_tt", _boom_sheets)

        with caplog.at_level(logging.ERROR, logger="gg-server"):
            ttr._append_recharge_background(db=None, uid=uid, sheet_id="SHEET-E11",
                                            sheet_name="TT充值表", rows=[{"a": 1}], rids=[rid])

        resp = client.get(f"/api/tt/accounts/{aid}/recharge-records", headers=hdr)
        assert resp.status_code == 200, resp.get_data(as_text=True)[:200]
        items = resp.get_json()["items"]
        row = next(r for r in items if r["id"] == rid)
        _assert_no_e11_leak(resp)
        assert row["sheets_error"] == main_mod._SHEETS_SYNC_FAILED_MSG, (
            f"TT sheets_error 落进了异常原文：{row['sheets_error']!r}")
        assert "sheets.googleapis.com" in caplog.text, "异常详情没进日志"


class TestE11ZuobiaoSheetsErrorSink:
    """item-4：做表写表失败文案的落点 —— 五期起由 `sheets_sync_log` 换成 `sheet_write_log`。

    旧形态：做表线的两个专属端点（写 `sheets_sync_log.error_msg` + 读回，已随五期
    退役）把异常原文落库并原样回给客户端。新形态：写点并入统一写表治理，落
    `sheet_write_log.error_msg`、由 `GET /api/sheet-write/status` 回出。
    **安全属性不变**：异常原文不得经任何回给客户端的字段外泄 —— 落库的必须是固定
    文案，详情只进服务端日志。
    """

    def test_update_zuobiao_failure_sanitizes_sheet_write_log(self, client, monkeypatch, caplog, inline_bg):
        import sheet_write
        import google_sheets_service as gs

        hdr, uid = _create_user(client, "_e11_zb", role="user")
        # 配好该用户的 Google 表格 —— 保存端点靠它解析 spreadsheet_id（否则端点早退、不登记）
        resp = client.post("/api/config/google-sheets", headers=hdr, json={
            "sheets": [{"id": "m1", "spreadsheet_id": "SHEET-E11"}], "active_id": "m1"})
        assert resp.status_code == 200, resp.get_data(as_text=True)[:200]

        monkeypatch.setattr(gs, "build_service", lambda path: object())
        monkeypatch.setattr(gs, "upsert_zuobiao", _boom_sheets)

        with caplog.at_level(logging.ERROR, logger="gg-server"):
            resp = client.post("/api/google-sheets/update-zuobiao", headers=hdr, json={
                "product_name": "P-E11", "region": "US", "report_date": "2026-01-01",
                "rows": [{"account": "acc", "customerId": "1", "cost": 1, "campaign": "c"}],
            })
        # 新语义：保存提交后立即返回（后台写表），不再同步 500
        assert resp.status_code == 200, resp.get_data(as_text=True)[:200]
        _assert_no_e11_leak(resp)

        # 安全属性①：失败落统一机制，且**落库的是固定文案**（异常原文不外泄）
        db = database.get_db()
        log_row = db.execute(
            "SELECT * FROM sheet_write_log WHERE user_id=? AND target='gg_zuobiao' "
            "AND business_key='P-E11'", (uid,)).fetchone()
        db.close()
        assert log_row is not None, "做表写表失败必须登记进统一写表机制"
        assert log_row["status"] == "retry_failed", log_row["status"]
        assert log_row["error_msg"] == sheet_write._WRITE_FAILED_MSG, (
            f"落库文案应为固定文案，实际 {log_row['error_msg']!r}")
        _assert_no_e11_leak(log_row["error_msg"] or "")

        # 安全属性②：该文案**回给客户端**时同样不得夹带原文（旧 sync-status 的回出腿）
        st = client.get("/api/sheet-write/status?platform=gg&target=gg_zuobiao"
                        "&business_key=P-E11", headers=hdr)
        _assert_no_e11_leak(st)
        item = st.get_json()["item"]
        assert item["error_msg"] == sheet_write._WRITE_FAILED_MSG, (
            f"回出的 error_msg 应为固定文案，实际 {item['error_msg']!r}")

        # 异常详情不得被一并砍掉
        assert "sheets.googleapis.com" in caplog.text, "异常详情没进日志"


class TestE11FfmpegStderrHidden:
    """item-7：`/api/audio-replace` 的 FFmpeg stderr 会回显**服务端绝对路径**。"""

    def test_audio_replace_ffmpeg_failure_hides_stderr(self, client, monkeypatch, caplog):
        import io
        import main as main_mod

        class _Result:
            returncode = 1
            stderr = (r"D:\server\cc\GG-Server\temp\audio_replace\_upload_video_1.mp4: "
                      "No such file or directory")

        monkeypatch.setattr(main_mod.subprocess, "run", lambda *a, **k: _Result())
        hdr, _ = _create_user(client, "_e11_ffm", role="user")

        with caplog.at_level(logging.ERROR, logger="gg-server"):
            resp = client.post(
                "/api/audio-replace",
                data={"video": (io.BytesIO(b"v"), "v.mp4"), "audio": (io.BytesIO(b"a"), "a.mp3")},
                content_type="multipart/form-data", headers=hdr)

        assert resp.status_code == 500, resp.get_data(as_text=True)[:200]
        assert resp.get_json()["error"] == "FFmpeg 执行失败，详情见服务端日志", (
            f"FFmpeg stderr 仍直出：{resp.get_json()['error']!r}")
        _assert_no_e11_leak(resp)
        assert "audio_replace" not in resp.get_data(as_text=True), "响应体泄露了服务端落盘路径"
        assert "No such file" in caplog.text, "stderr 详情没进日志"


class TestE11VideoProgressHidden:
    """同族站点（结论文件未列）：`VideoTask.message` 经 /api/video/progress 回出。

    `video_processor.VideoTask.run` 把 FFmpeg 命令串（含服务端绝对路径）与 stderr
    拼进 message；`/api/video/progress` 的 `message` 与 `error` 两个字段都原样回给前端。
    """

    def _run_task(self, client, monkeypatch, caplog, tmp_path, patch_target):
        import main as main_mod
        import video_processor as vp

        monkeypatch.setattr(main_mod.threading, "Thread", _InlineThread)
        monkeypatch.setattr("time.sleep", lambda _s: None)
        patch_target(monkeypatch, vp)

        hdr, _ = _create_user(client, "_e11_vid", role="user")
        with caplog.at_level(logging.ERROR, logger="gg-server"):
            resp = client.post("/api/video/generate",
                               json={"images": [str(tmp_path / "a.png")],
                                     "settings": {"output_path": str(tmp_path / "v.mp4")}},
                               headers=hdr)
        assert resp.status_code == 202, resp.get_data(as_text=True)[:200]
        tid = resp.get_json()["task_id"]
        return client.get(f"/api/video/progress?task_id={tid}", headers=hdr)

    def test_generic_exception_message_hides_path(self, client, monkeypatch, caplog, tmp_path):
        def _patch(monkeypatch, vp):
            def _boom(self):
                raise OSError(13, "Permission denied",
                              r"D:\server\cc\GG-Server\temp\ai_videos\x.mp4")
            monkeypatch.setattr(vp.VideoTask, "build_command", _boom)

        pr = self._run_task(client, monkeypatch, caplog, tmp_path, _patch)
        body = pr.get_json()
        assert body["error"] == "视频生成异常，详情见服务端日志", (
            f"视频任务失败文案仍回显路径：{body['error']!r}")
        _assert_no_e11_leak(pr)
        assert "Permission denied" in caplog.text, "异常详情没进日志"

    def test_ffmpeg_returncode_message_hides_cmd_and_stderr(self, client, monkeypatch, caplog, tmp_path):
        def _patch(monkeypatch, vp):
            class _Proc:
                returncode = 1
                stderr = [r"D:\server\cc\GG-Server\temp\ai_videos\x.mp4: No such file or directory"]

                def wait(self):
                    return 1

            monkeypatch.setattr(vp.VideoTask, "build_command", lambda self: ["ffmpeg"])
            monkeypatch.setattr(vp.subprocess, "Popen", lambda *a, **k: _Proc())

        pr = self._run_task(client, monkeypatch, caplog, tmp_path, _patch)
        body = pr.get_json()
        assert "FFmpeg 返回错误码 1" in body["error"]
        assert "详情见服务端日志" in body["error"], (
            f"FFmpeg 命令串 / stderr 仍直出：{body['error']!r}")
        _assert_no_e11_leak(pr)
        assert "No such file" in caplog.text, "stderr 详情没进日志"


class TestE11SheetsServiceSourceSanitized:
    """item-6：`google_sheets_service` 的 `{e}` 内插把上游库原文带进面向用户的异常文案。"""

    def test_invalid_credentials_json_not_leaked(self, client, tmp_path, monkeypatch):
        """/api/google-sheets/status 会把这句 message 原样回给客户端（真实路径，不打桩）。"""
        import main as main_mod

        creds = tmp_path / "bad.json"
        creds.write_text("{ this is not valid json")
        monkeypatch.setattr(main_mod, "_GOOGLE_SHEETS_CONFIG", {"credentials_path": str(creds)})
        hdr, _ = _create_user(client, "_e11_creds", role="user")

        resp = client.get("/api/google-sheets/status", headers=hdr)
        body = resp.get_data(as_text=True)
        msg = resp.get_json()["message"]
        assert "Expecting" not in body, f"凭据文件解析错误原文回给客户端：{body[:300]!r}"
        assert str(creds) not in body, "响应体泄露了服务端密钥文件绝对路径"
        assert msg == "凭据文件格式无效，请确认为服务账号 JSON 密钥文件", (
            f"可操作的中文说明被一并砍掉了：{msg!r}")

    def test_read_sheet_values_message_hides_upstream_error(self, caplog):
        """`read_sheet_values` 的 `{e}` 内插：上游 HttpError/URL 不得出现在异常文案里。"""
        import google_sheets_service as gs

        class _Exec:
            def execute(self):
                raise RuntimeError(
                    "<HttpError 404> https://sheets.googleapis.com/v4/spreadsheets/SID")

        class _Values:
            def get(self, **_kw):
                return _Exec()

        class _Sheets:
            def values(self):
                return _Values()

        class _Svc:
            def spreadsheets(self):
                return _Sheets()

        with caplog.at_level(logging.ERROR, logger="gg-server"):
            with pytest.raises(gs.GoogleSheetsServiceError) as ei:
                gs.read_sheet_values(_Svc(), "SID", "看板", "A:H")

        assert "读取工作表失败" in str(ei.value)
        assert "sheets.googleapis.com" not in str(ei.value)
        assert "HttpError" not in str(ei.value)
        assert "sheets.googleapis.com" in caplog.text, "异常详情没进日志"

    def test_update_rows_message_keeps_actionable_ids_but_drops_library_text(self, caplog):
        """批量失败文案：account_id 与「已写入 0 行」是用户可操作信息 ⇒ 保留；
        `{e}` 上游原文 ⇒ 换成固定尾句。"""
        import google_sheets_service as gs

        class _Exec:
            def __init__(self, result=None, boom=False):
                self._result = result
                self._boom = boom

            def execute(self):
                if self._boom:
                    raise RuntimeError("quota exceeded https://sheets.googleapis.com/v4/spreadsheets")
                return self._result

        class _Values:
            def get(self, **_kw):
                # 首次读取（定位 account_id 行）必须成功返回网格，才走得到 batchUpdate
                return _Exec({"values": [["", "", "A1"], ["", "", "A2"]]})

            def batchUpdate(self, **_kw):
                return _Exec(boom=True)

        class _Sheets:
            def values(self):
                return _Values()

        class _Svc:
            def spreadsheets(self):
                return _Sheets()

        rows = [{"account_id": "A1", "cells": {"A": "1"}},
                {"account_id": "A2", "cells": {"A": "2"}}]
        with caplog.at_level(logging.ERROR, logger="gg-server"):
            with pytest.raises(gs.GoogleSheetsServiceError) as ei:
                gs.update_rows_by_account_id(_Svc(), "SID", "看板", rows)

        msg = str(ei.value)
        assert "A1" in msg and "A2" in msg, "用户可定位的 account_id 被误杀"
        assert "本次已写入 0 行" in msg
        assert "quota exceeded" not in msg
        assert "sheets.googleapis.com" not in msg
        assert "quota exceeded" in caplog.text, "异常详情没进日志"


class TestE11AdsServiceSourceSanitized:
    """item-6（Ads 侧）：`e.error.message` 内插把上游 API 英文原文带给客户端。"""

    def test_list_accounts_message_hides_upstream_text(self, monkeypatch, caplog):
        import google_ads_service as gas

        class _Err:
            message = ("RequestError.INVALID_ARGUMENT https://googleads.googleapis.com/"
                       "v24/customers/123")

        class _Exc(Exception):
            error = _Err()

            def __str__(self):
                return self.error.message

        class _Svc:
            def list_accessible_customers(self):
                raise _Exc()

        class _Client:
            def get_service(self, _name):
                return _Svc()

        monkeypatch.setattr(gas, "GoogleAdsException", _Exc)
        monkeypatch.setattr(gas, "_build_client", lambda *a, **k: _Client())

        with caplog.at_level(logging.ERROR, logger="gg-server"):
            with pytest.raises(gas.GoogleAdsServiceError) as ei:
                gas.list_accounts("a", "b", "c", "d", "e")

        assert "获取账户列表失败" in str(ei.value)
        assert "googleads.googleapis.com" not in str(ei.value)
        assert "googleads.googleapis.com" in caplog.text, "异常详情没进日志"

    def test_endpoint_response_hides_upstream_text(self, client, monkeypatch, caplog):
        import google_ads_service as gas

        class _Err:
            message = "RequestError.PERMISSION_DENIED https://googleads.googleapis.com/v24"

        class _Exc(Exception):
            error = _Err()

            def __str__(self):
                return self.error.message

        class _Svc:
            def list_accessible_customers(self):
                raise _Exc()

        class _Client:
            def get_service(self, _name):
                return _Svc()

        monkeypatch.setattr(gas, "GoogleAdsException", _Exc)
        monkeypatch.setattr(gas, "_build_client", lambda *a, **k: _Client())
        hdr, _ = _create_user(client, "_e11_ads", role="user")

        with caplog.at_level(logging.ERROR, logger="gg-server"):
            resp = client.post("/api/google-ads/accounts", json={}, headers=hdr)
        assert resp.status_code == 500
        assert resp.get_json()["error"] == "获取账户列表失败，请检查 Google Ads 凭据与权限"
        _assert_no_e11_leak(resp)
        assert "googleads.googleapis.com" in caplog.text, "异常详情没进日志"


class TestE11ScraperDelistSourceSanitized:
    """同族站点（结论文件未列）：`scraper` / `delist_checker` 把库异常原文拼进文案。

    两者的文案都经响应体回给客户端（/api/scrape 的 500 与 /api/products/delist-status）。
    """

    def test_scrape_error_hides_requests_library_text(self, monkeypatch, caplog):
        import requests
        import scraper

        def _boom(*_a, **_k):
            raise requests.ConnectionError(
                "HTTPSConnectionPool(host='play.google.com', port=443): "
                "Max retries exceeded with url: /store/apps/details?id=a.b")

        monkeypatch.setattr(scraper.requests, "get", _boom)
        with caplog.at_level(logging.WARNING, logger="gg-server"):
            with pytest.raises(scraper.ScrapeError) as ei:
                scraper.scrape_images("https://play.google.com/store/apps/details?id=a.b")

        assert "无法访问页面" in str(ei.value)
        assert "HTTPSConnectionPool" not in str(ei.value)
        assert "Max retries" not in str(ei.value)
        assert "HTTPSConnectionPool" in caplog.text, "异常详情没进日志"

    def test_direct_request_exception_text_not_returned(self, monkeypatch, caplog):
        import delist_checker as dc

        def _boom(*_a, **_k):
            raise ValueError("english boom from some library")

        monkeypatch.setattr(dc.requests, "get", _boom)
        with caplog.at_level(logging.WARNING, logger="gg-server"):
            is_delisted, err = dc.check_url_delisted(
                "https://play.google.com/store/apps/details?id=a.b")
        assert is_delisted is None
        assert "无法判定" in err
        assert "english boom" not in err
        assert "english boom" in caplog.text, "异常详情没进日志"

    def test_proxy_exception_text_not_returned(self, monkeypatch, caplog):
        import delist_checker as dc

        class _Pool:
            count = 1
            max_retries = 1

            def next(self, exclude=None):
                return {"ip": "1.2.3.4", "port": 8080}

            def to_requests(self, _proxy):
                return {"http": "http://1.2.3.4:8080"}

        def _boom(*_a, **_k):
            raise RuntimeError("english boom from proxy stack")

        monkeypatch.setattr(dc.requests, "get", _boom)
        with caplog.at_level(logging.WARNING, logger="gg-server"):
            is_delisted, err = dc.check_url_delisted(
                "https://play.google.com/store/apps/details?id=a.b", _Pool())
        assert is_delisted is None
        assert "无法判定" in err
        assert "english boom" not in err
        assert "english boom" in caplog.text, "异常详情没进日志"


class TestE11AiUpstreamBodySanitized:
    """上游 AI provider 的响应体（`resp.text`）是外部数据，不得回进客户端。

    `/api/ad-reports/multi-ai-chat` 与 `/api/ad-reports/analyze` 的非 200 分支一度把
    `resp.text[:300]` 拼进 `answer` 直出 —— 那是**上游 provider 的响应体**（多为英文
    错误 JSON），不是本地异常变量，所以前几轮 grep `str(e)` / `{e}` 一律命中不了。
    修复后：客户端只收固定中文文案（保留 HTTP 状态码），原文落 `log.warning`。
    """

    _SENTINEL = "UPSTREAM-PROVIDER-RAW-BODY-9x7"

    @staticmethod
    def _enable_ai(client, uid):
        db = database.get_db()
        db.execute(
            "INSERT OR REPLACE INTO config(key, value) VALUES (?, ?)",
            (f"ai_analysis_{uid}", json.dumps({
                "enabled": True, "provider": "volcano", "model": "m",
                "api_key": "k", "endpoint": "https://provider.invalid/v1/chat",
            })))
        db.commit()
        db.close()

    @pytest.mark.parametrize("path,uname", [
        ("/api/ad-reports/multi-ai-chat", "ai_body_mac"),
        ("/api/ad-reports/analyze", "ai_body_ana"),
    ])
    def test_upstream_error_body_not_echoed_but_logged(self, client, caplog, monkeypatch, path, uname):
        import main
        hdr, uid = _create_user(client, uname)
        self._enable_ai(client, uid)

        # （2026-10-07）此处原有 `monkeypatch.setattr(main, "_yt_db", database.get_db)` 的绕行：
        # 当时 `analyze` 会提前 `close()` 请求级共享连接，那是**另一个独立缺陷**，
        # 为隔离它才把 `_yt_db` 换成每次新开连接。那句 `close()` 现已修
        # （回归守卫见 `test_ad_reports.TestAdReportsAnalyze
        # ::test_analyze_enabled_does_not_500_on_closed_db`），故**撤除绕行** ——
        # 留着它，本用例就不再覆盖真实的共享连接路径了。

        class _FakeResp:
            status_code = 503
            text = ('{"error":{"type":"upstream_failure","message":"'
                    + TestE11AiUpstreamBodySanitized._SENTINEL + '"}}')

        def _fake_post(url, *a, **k):
            return _FakeResp()

        monkeypatch.setattr(main.requests, "post", _fake_post)

        with caplog.at_level(logging.WARNING, logger="gg-server"):
            resp = client.post(path, json={"question": "花费如何？"}, headers=hdr)

        assert resp.status_code == 200, resp.get_data(as_text=True)[:200]
        body = resp.get_json()
        assert body.get("answer"), "应仍给出 answer"
        raw = resp.get_data(as_text=True)
        assert self._SENTINEL not in raw, f"上游响应体被回显：{raw[:300]!r}"
        assert "503" in body["answer"], "对用户有用的 HTTP 状态码应保留"
        assert self._SENTINEL in caplog.text, "上游原文没进日志"

