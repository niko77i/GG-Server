"""TT 苹果（App Store）包链接录入测试。

设计文档：docs/superpowers/specs/2026-09-24-tt-appstore-package-design.md
"""
import os
import sys

import pytest

_py_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _py_dir not in sys.path:
    sys.path.insert(0, _py_dir)

from routes import tt_routes  # noqa: E402

APPLE_LIVE = "https://apps.apple.com/vn/app/id6804355336"
APPLE_SLUG = "https://apps.apple.com/vn/app/densia/id6804355336"
PLAY = "https://play.google.com/store/apps/details?id=com.a.b"


class TestIsAppstoreUrl:
    """域名判定：按解析出的 host 全等比较，禁止子串匹配。"""

    def test_apps_apple_com_is_appstore(self):
        assert tt_routes._is_appstore_url(APPLE_LIVE) is True

    def test_itunes_apple_com_is_appstore(self):
        assert tt_routes._is_appstore_url("https://itunes.apple.com/us/app/id123") is True

    def test_slug_form_is_appstore(self):
        assert tt_routes._is_appstore_url(APPLE_SLUG) is True

    def test_play_is_not_appstore(self):
        assert tt_routes._is_appstore_url(PLAY) is False

    def test_host_in_query_is_not_appstore(self):
        """域名出现在参数里 → 不是苹果（子串匹配会误判）。"""
        assert tt_routes._is_appstore_url("https://evil.com/?u=apps.apple.com") is False

    def test_suffix_domain_is_not_appstore(self):
        """apps.apple.com.evil.com 不是苹果。"""
        assert tt_routes._is_appstore_url("https://apps.apple.com.evil.com/vn/app/id1") is False

    def test_empty_and_none_are_not_appstore(self):
        assert tt_routes._is_appstore_url("") is False
        assert tt_routes._is_appstore_url(None) is False

    def test_backslash_userinfo_is_not_appstore(self):
        r"""反斜杠 host 绕过必须 fail-closed。

        `urlsplit('https://evil.com\@apps.apple.com/vn/app/id123').hostname`
        在 Python 眼里反斜杠只是 userinfo 里的普通字符，host 取最后一个 @ 之后 → `apps.apple.com`；
        而浏览器 / 前端 `new URL()`（WHATWG 把 `\` 归一成 `/`）算出的是 `evil.com`。
        后端据此放行会落库成「空包名 + 非苹果链接」，绕过「跑包必须填写包名」守卫。
        苹果链接不含反斜杠，一律判否。
        """
        assert tt_routes._is_appstore_url(
            "https://evil.com\\@apps.apple.com/vn/app/id123") is False


class TestValidatePackage:
    """校验四象限：只有「苹果链接 + 空包名」是新放行的组合。"""

    @pytest.fixture(autouse=True)
    def _flask_app_ctx(self, app):
        """拒绝分支走 err() → jsonify()，需要 Flask 应用上下文（仓库既有约定）。"""
        with app.app_context():
            yield

    def _call(self, **pkg):
        return tt_routes._validate_package(pkg)

    def test_play_empty_name_rejected(self):
        resp = self._call(type="package", package_name="", url=PLAY)
        assert resp is not None

    def test_play_with_name_ok(self):
        assert self._call(type="package", package_name="com.a.b", url=PLAY) is None

    def test_appstore_empty_name_ok(self):
        assert self._call(type="package", package_name="", url=APPLE_LIVE) is None

    def test_appstore_with_name_ok(self):
        assert self._call(type="package", package_name="myapp", url=APPLE_LIVE) is None

    def test_pwa_needs_no_name(self):
        assert self._call(type="pwa", package_name="", url="") is None

    def test_invalid_type_rejected(self):
        assert self._call(type="ios", package_name="x", url=APPLE_LIVE) is not None

    def test_play_empty_name_and_empty_url_rejected(self):
        """URL 缺失时不得因为「可能以后填苹果链接」而放行。"""
        assert self._call(type="package", package_name="", url="") is not None


class TestAddPackageViaApi:
    """走 HTTP 接口验证放行真的生效（不只是函数级）。"""

    def test_add_appstore_package_without_name(self, client, tt_headers):
        pid = client.post("/api/tt/products/create", headers=tt_headers, json={
            "product_name": "苹果包产品",
        }).get_json()["id"]

        resp = client.post(f"/api/tt/products/{pid}/packages", headers=tt_headers, json={
            "type": "package", "series_name": "S1", "package_name": "", "url": APPLE_LIVE,
        })
        assert resp.status_code == 200

        detail = client.get(f"/api/tt/products/{pid}/detail", headers=tt_headers).get_json()
        pkg = detail["packages"][0]
        assert pkg["package_name"] == ""
        assert pkg["url"] == APPLE_LIVE

    def test_add_play_package_without_name_still_rejected(self, client, tt_headers):
        pid = client.post("/api/tt/products/create", headers=tt_headers, json={
            "product_name": "安卓包产品",
        }).get_json()["id"]

        resp = client.post(f"/api/tt/products/{pid}/packages", headers=tt_headers, json={
            "type": "package", "series_name": "S1", "package_name": "", "url": PLAY,
        })
        assert resp.status_code == 400
        assert "包名" in resp.get_json()["error"]

    def test_create_product_with_appstore_package(self, client, tt_headers):
        """建产品时带包这条路径（第三个调用点）也要放行。"""
        resp = client.post("/api/tt/products/create", headers=tt_headers, json={
            "product_name": "带苹果包的产品",
            "packages": [{"type": "package", "series_name": "S1",
                          "package_name": "", "url": APPLE_LIVE}],
        })
        assert resp.status_code == 200

    def test_update_package_clearing_name_allowed_for_appstore(self, client, tt_headers):
        """更新时清空包名：苹果链接允许，安卓链接拒绝。"""
        pid = client.post("/api/tt/products/create", headers=tt_headers, json={
            "product_name": "更新测试产品",
        }).get_json()["id"]

        apple_id = client.post(f"/api/tt/products/{pid}/packages", headers=tt_headers, json={
            "type": "package", "series_name": "S1", "package_name": "x", "url": APPLE_LIVE,
        }).get_json()["id"]
        resp = client.put(f"/api/tt/packages/{apple_id}", headers=tt_headers,
                          json={"package_name": ""})
        assert resp.status_code == 200

        play_id = client.post(f"/api/tt/products/{pid}/packages", headers=tt_headers, json={
            "type": "package", "series_name": "S2", "package_name": "com.a.b", "url": PLAY,
        }).get_json()["id"]
        resp = client.put(f"/api/tt/packages/{play_id}", headers=tt_headers,
                          json={"package_name": ""})
        assert resp.status_code == 400

    def test_put_url_only_cannot_turn_appstore_row_into_play_row(self, client, tt_headers):
        """只传 url（不带 package_name 键）也不能把存量苹果行改成「Play 链接 + 空包名」。

        守卫若带 `'package_name' in updates` 条件，本请求会绕过整段规则落库，
        使苹果豁免在 add_package 与 update_package 两条路径上口径分裂。
        """
        pid = client.post("/api/tt/products/create", headers=tt_headers, json={
            "product_name": "只传url产品",
        }).get_json()["id"]
        pkg_id = client.post(f"/api/tt/products/{pid}/packages", headers=tt_headers, json={
            "type": "package", "series_name": "S1", "package_name": "", "url": APPLE_LIVE,
        }).get_json()["id"]

        resp = client.put(f"/api/tt/packages/{pkg_id}", headers=tt_headers,
                          json={"url": PLAY})

        assert resp.status_code == 400
        assert "包名" in resp.get_json()["error"]

    def test_put_url_only_still_allowed_for_appstore_to_appstore(self, client, tt_headers):
        """苹果行只换 url（苹果 → 苹果）仍放行，且包名保持空。"""
        pid = client.post("/api/tt/products/create", headers=tt_headers, json={
            "product_name": "苹果换苹果产品",
        }).get_json()["id"]
        pkg_id = client.post(f"/api/tt/products/{pid}/packages", headers=tt_headers, json={
            "type": "package", "series_name": "S1", "package_name": "", "url": APPLE_LIVE,
        }).get_json()["id"]

        resp = client.put(f"/api/tt/packages/{pkg_id}", headers=tt_headers,
                          json={"url": APPLE_SLUG})
        assert resp.status_code == 200

        detail = client.get(f"/api/tt/products/{pid}/detail", headers=tt_headers).get_json()
        pkg = detail["packages"][0]
        assert pkg["url"] == APPLE_SLUG
        assert pkg["package_name"] == ""

    def test_put_url_only_unchanged_for_play_row_with_name(self, client, tt_headers):
        """正向对照：安卓行（有包名）只换 Play url 不受影响，仍是 200。"""
        pid = client.post("/api/tt/products/create", headers=tt_headers, json={
            "product_name": "安卓换url产品",
        }).get_json()["id"]
        pkg_id = client.post(f"/api/tt/products/{pid}/packages", headers=tt_headers, json={
            "type": "package", "series_name": "S1", "package_name": "com.a.b", "url": PLAY,
        }).get_json()["id"]

        resp = client.put(f"/api/tt/packages/{pkg_id}", headers=tt_headers,
                          json={"url": "https://play.google.com/store/apps/details?id=com.c.d"})
        assert resp.status_code == 200


class TestImportTextAppstore:
    """脏数据解析：苹果链接要能捞出来，且顺序与原文一致。"""

    def test_parse_appstore_link(self, client, tt_headers):
        resp = client.post("/api/tt/products/import-text", headers=tt_headers,
                           json={"text": f"神包上线：苹果系列\n{APPLE_LIVE}"})
        parsed = resp.get_json()["parsed"]
        assert len(parsed) == 1
        assert parsed[0]["url"] == APPLE_LIVE
        assert parsed[0]["package_name"] == ""
        assert parsed[0]["type"] == "package"
        assert parsed[0]["series_name"] == "苹果系列"

    def test_parse_slug_form(self, client, tt_headers):
        resp = client.post("/api/tt/products/import-text", headers=tt_headers,
                           json={"text": f"神包上线：Densia\n{APPLE_SLUG}"})
        parsed = resp.get_json()["parsed"]
        assert len(parsed) == 1
        assert parsed[0]["url"] == APPLE_SLUG

    def test_appstore_query_params_stripped(self, client, tt_headers):
        """苹果链接尾随查询参数被有意截掉（地区在路径里，不影响判定；便于去重）。"""
        resp = client.post("/api/tt/products/import-text", headers=tt_headers,
                           json={"text": "神包上线：带参\nhttps://apps.apple.com/vn/app/id6804355336?pt=123&ct=abc"})
        parsed = resp.get_json()["parsed"]
        assert len(parsed) == 1
        assert parsed[0]["url"] == "https://apps.apple.com/vn/app/id6804355336"
        assert parsed[0]["series_name"] == "带参"

    def test_order_follows_source_text_not_pattern(self, client, tt_headers):
        """Play 与苹果交错时，输出顺序必须按原文出现顺序，不能先排完 Play 再排苹果。"""
        text = (
            "神包上线：甲\n" + PLAY + "\n"
            "神包上线：乙\n" + APPLE_LIVE + "\n"
            "神包上线：丙\nhttps://play.google.com/store/apps/details?id=com.c.d"
        )
        resp = client.post("/api/tt/products/import-text", headers=tt_headers, json={"text": text})
        parsed = resp.get_json()["parsed"]
        assert [p["url"] for p in parsed] == [
            PLAY,
            APPLE_LIVE,
            "https://play.google.com/store/apps/details?id=com.c.d",
        ]

    def test_mixed_keeps_play_package_names(self, client, tt_headers):
        """苹果条目包名为空，Play 条目包名照旧提取。"""
        text = "神包上线：甲\n" + PLAY + "\n神包上线：乙\n" + APPLE_LIVE
        resp = client.post("/api/tt/products/import-text", headers=tt_headers, json={"text": text})
        parsed = resp.get_json()["parsed"]
        assert parsed[0]["package_name"] == "com.a.b"
        assert parsed[1]["package_name"] == ""

    def test_non_appstore_apple_path_not_matched(self, client, tt_headers):
        """苹果官网其他路径（非 /app/idNNN）不该被当成包链接。"""
        resp = client.post("/api/tt/products/import-text", headers=tt_headers,
                           json={"text": "看看 https://apps.apple.com/vn/charts/paid-apps"})
        assert resp.get_json()["parsed"] == []

    def test_parse_dotted_slug_form(self, client, tt_headers):
        """含点 slug 要能捞出来 —— 原 slug 字符集 [\\w\\-]+ 不含 `.`。

        后果：同一 URL 手填能落库、粘贴导入被静默丢弃（`parsed` 里没有它，
        不报错不提示），两条录入通道口径分裂。
        """
        url = "https://apps.apple.com/us/app/foo.bar/id123"
        resp = client.post("/api/tt/products/import-text", headers=tt_headers,
                           json={"text": f"神包上线：带点\n{url}"})
        parsed = resp.get_json()["parsed"]
        assert len(parsed) == 1
        assert parsed[0]["url"] == url

    def test_parse_percent_encoded_slug_form(self, client, tt_headers):
        """含百分号编码的 slug（中文应用名）同样要能捞出来。"""
        url = "https://apps.apple.com/cn/app/%E5%BE%AE%E4%BF%A1/id414478124"
        resp = client.post("/api/tt/products/import-text", headers=tt_headers,
                           json={"text": f"神包上线：微信\n{url}"})
        parsed = resp.get_json()["parsed"]
        assert len(parsed) == 1
        assert parsed[0]["url"] == url

    def test_widened_slug_does_not_loosen_boundaries(self):
        """反向边界：放宽 slug 段不得把非包链接吞进来。

        `/app/` 后没有 `id<数字>`、以及非苹果 host 的同类路径，都不得被 `_LINK_RE` 命中。
        """
        assert tt_routes._LINK_RE.findall("https://apps.apple.com/vn/app/") == []
        assert tt_routes._LINK_RE.findall("https://evil.com/vn/app/id123") == []


class TestUpdatePackageTypeValidation:
    """PUT /api/tt/packages/<id> 的 type 必须与 _validate_package 同口径（只允许 package/pwa）。

    落库一个既非 package 也非 pwa 的行，该行此后不再被手动/定时掉包检测取到
    （两处 SQL 都按 type='package' 过滤），等于悄悄退出巡检范围。
    """

    def _make_pkg(self, client, tt_headers):
        pid = client.post("/api/tt/products/create", headers=tt_headers, json={
            "product_name": "type 校验产品",
        }).get_json()["id"]
        pkg_id = client.post(f"/api/tt/products/{pid}/packages", headers=tt_headers, json={
            "type": "package", "series_name": "S1", "package_name": "com.a.b", "url": PLAY,
        }).get_json()["id"]
        return pid, pkg_id

    def test_invalid_type_rejected(self, client, tt_headers):
        _, pkg_id = self._make_pkg(client, tt_headers)

        resp = client.put(f"/api/tt/packages/{pkg_id}", headers=tt_headers, json={"type": "ios"})

        assert resp.status_code == 400
        assert "无效的投放对象类型" in resp.get_json()["error"]

    def test_empty_type_rejected(self, client, tt_headers):
        """空字符串同属非法取值，不得落库。"""
        _, pkg_id = self._make_pkg(client, tt_headers)

        resp = client.put(f"/api/tt/packages/{pkg_id}", headers=tt_headers, json={"type": ""})

        assert resp.status_code == 400
        assert "无效的投放对象类型" in resp.get_json()["error"]

    def test_pwa_type_allowed(self, client, tt_headers):
        """合法取值不得误伤。"""
        _, pkg_id = self._make_pkg(client, tt_headers)

        resp = client.put(f"/api/tt/packages/{pkg_id}", headers=tt_headers, json={"type": "pwa"})

        assert resp.status_code == 200

    def test_package_type_allowed_on_compliant_row(self, client, tt_headers):
        """已合规行显式传 package 仍放行。"""
        _, pkg_id = self._make_pkg(client, tt_headers)

        resp = client.put(f"/api/tt/packages/{pkg_id}", headers=tt_headers, json={"type": "package"})

        assert resp.status_code == 200


class TestUpdatePackageExplicitEmptyUrl:
    """显式传空 url 时不得回落库里 url 而放行（否则落库成包名与 url 皆空）。"""

    def _make_apple_pkg(self, client, tt_headers):
        pid = client.post("/api/tt/products/create", headers=tt_headers, json={
            "product_name": "空url收口产品",
        }).get_json()["id"]
        pkg_id = client.post(f"/api/tt/products/{pid}/packages", headers=tt_headers, json={
            "type": "package", "series_name": "S1", "package_name": "", "url": APPLE_LIVE,
        }).get_json()["id"]
        return pid, pkg_id

    def test_explicit_empty_url_rejected(self, client, tt_headers):
        _, pkg_id = self._make_apple_pkg(client, tt_headers)

        resp = client.put(f"/api/tt/packages/{pkg_id}", headers=tt_headers,
                          json={"package_name": "", "url": ""})

        assert resp.status_code == 400
        assert "包名" in resp.get_json()["error"]

    def test_omitting_url_still_allowed(self, client, tt_headers):
        """没传 url（本次只清包名）仍按库里的苹果 url 放行 —— 既有能力不被削弱。"""
        _, pkg_id = self._make_apple_pkg(client, tt_headers)

        resp = client.put(f"/api/tt/packages/{pkg_id}", headers=tt_headers,
                          json={"package_name": ""})

        assert resp.status_code == 200
