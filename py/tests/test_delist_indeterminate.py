"""「判定未知」不得覆盖既有掉包记录 —— GG 侧消费方测试。

设计文档：docs/superpowers/specs/2026-09-24-tt-appstore-package-design.md
"""
import os
import sys
import datetime
from unittest.mock import patch

_py_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _py_dir not in sys.path:
    sys.path.insert(0, _py_dir)

import database  # noqa: E402

APPLE_DELISTED = "https://apps.apple.com/vn/app/id6813542964"


def _mk_gg_product_and_package():
    """建一个 GG 产品 + 一个正常状态的包，返回 (pid, pkg_id)。"""
    db = database.get_db()
    db.execute("INSERT INTO products(product_name, status) VALUES('未知态GG产品','')")
    db.commit()
    pid = db.execute("SELECT last_insert_rowid() AS id").fetchone()["id"]
    db.execute(
        "INSERT INTO packages(product_id, series_name, package_name, url, status) "
        "VALUES(?,?,?,?,?)",
        (pid, "GG系列", "com.a.b", APPLE_DELISTED, ""))
    db.commit()
    pkg_id = db.execute("SELECT last_insert_rowid() AS id").fetchone()["id"]
    db.close()
    return pid, pkg_id


def _seed_delisted_row(pkg_id, pid):
    """埋一条「上一轮已掉包」的记录。"""
    db = database.get_db()
    db.execute(
        "INSERT OR REPLACE INTO delist_checks(package_id, product_id, is_delisted, checked_at, error_msg) "
        "VALUES(?,?,?,?,?)",
        (pkg_id, pid, 1, datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"), ""))
    db.commit()
    db.close()


def _read_delist_row(pkg_id):
    db = database.get_db()
    row = db.execute("SELECT is_delisted, error_msg FROM delist_checks WHERE package_id=?",
                     (pkg_id,)).fetchone()
    db.close()
    return dict(row) if row else None


class TestGGManualCheckIndeterminate:
    """GG 手动检测：未知态不覆盖既有判定，但把原因记进 error_msg。"""

    def test_manual_check_keeps_prior_delisted_state(self, client, auth_headers):
        pid, pkg_id = _mk_gg_product_and_package()
        _seed_delisted_row(pkg_id, pid)

        with patch("delist_checker.check_product_packages",
                   return_value=[{"package_id": pkg_id, "product_id": pid,
                                  "is_delisted": None, "error": "HTTP 429 限流，判定未知"}]):
            resp = client.post(f"/api/products/{pid}/check-delist", headers=auth_headers)

        assert resp.status_code == 200
        assert resp.get_json()["results"][0]["is_delisted"] is None

        row = _read_delist_row(pkg_id)
        assert row["is_delisted"] == 1              # 未被覆盖成 0
        assert "429" in row["error_msg"]            # 原因留痕


class TestGGSchedulerIndeterminate:
    """GG 定时检测：未知态不覆盖既有判定。"""

    def test_scheduler_keeps_prior_delisted_state(self, client, auth_headers, monkeypatch):
        import main

        pid, pkg_id = _mk_gg_product_and_package()
        _seed_delisted_row(pkg_id, pid)

        monkeypatch.setattr("delist_checker.check_url_delisted",
                            lambda url, pool=None: (None, "HTTP 429 限流，判定未知"))
        monkeypatch.setattr(main, "_build_delist_proxy_pool", lambda: None)
        monkeypatch.setattr(main, "_send_telegram_notifications",
                            lambda db_, pkgs: None)

        main._run_delist_check_once()

        row = _read_delist_row(pkg_id)
        assert row["is_delisted"] == 1
        assert "429" in row["error_msg"]


class TestGGManualCheckEmptyUrl:
    """空 url 包（GG 可创建）同样不得把既有掉包记录抹成正常。"""

    def test_manual_check_empty_url_keeps_prior_delisted_state(self, client, auth_headers):
        db = database.get_db()
        db.execute("INSERT INTO products(product_name, status) VALUES('空url产品','')")
        db.commit()
        pid = db.execute("SELECT last_insert_rowid() AS id").fetchone()["id"]
        # GG 加包端点不校验 url，所以这种行真实存在
        db.execute(
            "INSERT INTO packages(product_id, series_name, package_name, url, status) "
            "VALUES(?,?,?,?,?)",
            (pid, "GG系列", "com.a.b", "", ""))
        db.commit()
        pkg_id = db.execute("SELECT last_insert_rowid() AS id").fetchone()["id"]
        db.close()

        _seed_delisted_row(pkg_id, pid)

        resp = client.post(f"/api/products/{pid}/check-delist", headers=auth_headers)

        assert resp.status_code == 200
        row = _read_delist_row(pkg_id)
        assert row["is_delisted"] == 1              # 未被覆盖成 0
        assert "无法判定" in row["error_msg"]


class TestEmptyUrlJudgedIndeterminate:
    """delist_checker 层：空 url 一律判「未知」，不再判「正常」。"""

    def test_check_url_delisted_empty_url_returns_none(self):
        from delist_checker import check_url_delisted

        is_delisted, error = check_url_delisted("")

        assert is_delisted is None
        assert "无法判定" in error

    def test_check_product_packages_empty_url_returns_none(self):
        from unittest.mock import patch
        from delist_checker import check_product_packages

        with patch("delist_checker.requests.get") as mock_get:
            results = check_product_packages(1, [{"id": 1, "url": "", "package_name": "test.a"}])

        mock_get.assert_not_called()                # 空 url 仍不发请求
        assert results[0]["is_delisted"] is None
        assert "无法判定" in results[0]["error"]
