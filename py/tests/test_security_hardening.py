"""安全加固测试 — A/B/C/D 类缺陷收口。"""
import pytest


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
