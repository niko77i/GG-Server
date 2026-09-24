"""TT 掉包通知测试 — pending/dismiss 接口 + 定时检测 + Telegram 参数化。

设计文档：docs/superpowers/specs/2026-09-24-tt-delist-notification-design.md
"""
import os
import sys
import datetime

_py_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _py_dir not in sys.path:
    sys.path.insert(0, _py_dir)

import database  # noqa: E402
import delist_checker  # noqa: E402
import telegram_sender  # noqa: E402
from routes import tt_routes  # noqa: E402


# ==================== 辅助 ====================

def _make_tt_user(client, username):
    """创建 TT 平台用户并返回 (headers, user_id)。"""
    client.post("/api/auth/register", json={"username": username, "password": "test123"})
    db = database.get_db()
    db.execute("UPDATE users SET platform='tt' WHERE username=?", (username,))
    db.commit()
    uid = db.execute("SELECT id FROM users WHERE username=?", (username,)).fetchone()["id"]
    db.close()
    resp = client.post("/api/auth/login", json={"username": username, "password": "test123"})
    token = resp.get_json().get("access_token", "")
    return {"Authorization": f"Bearer {token}"}, uid


def _mk_product(db, owner_id, name="TT产品", status="active"):
    db.execute(
        "INSERT INTO tt_products(product_name, status, owner_id) VALUES(?,?,?)",
        (name, status, owner_id))
    db.commit()
    return db.execute("SELECT last_insert_rowid() AS id").fetchone()["id"]


def _mk_package(db, product_id, series="系列A", status="", pkg_type="package"):
    db.execute(
        "INSERT INTO tt_packages(product_id, type, series_name, package_name, url, status) "
        "VALUES(?,?,?,?,?,?)",
        (product_id, pkg_type, series, "com.example." + series, "https://play.google.com/store/apps/details?id=com.example", status))
    db.commit()
    return db.execute("SELECT last_insert_rowid() AS id").fetchone()["id"]


def _mark_delisted(db, package_id, is_delisted=1):
    db.execute(
        "INSERT OR REPLACE INTO tt_delist_checks(package_id, is_delisted, checked_at) "
        "VALUES(?,?,datetime('now','localtime'))",
        (package_id, is_delisted))
    db.commit()


# ==================== pending 接口 ====================

class TestTtDelistPending:
    def test_owner_sees_own_delisted_notification(self, client, tt_headers):
        db = database.get_db()
        uid = db.execute("SELECT id FROM users WHERE username='ttuser'").fetchone()["id"]
        pid = _mk_product(db, uid)
        pkg = _mk_package(db, pid, "系列甲")
        _mark_delisted(db, pkg)
        db.close()

        resp = client.get("/api/tt/delist/pending", headers=tt_headers)
        assert resp.status_code == 200
        notifs = resp.get_json()["notifications"]
        assert len(notifs) == 1
        assert notifs[0]["product_id"] == pid
        assert notifs[0]["type"] == "first"
        assert notifs[0]["series_names"] == ["系列甲"]
        assert notifs[0]["package_ids"] == [pkg]
        assert notifs[0]["platform"] == "tt"

    def test_user_does_not_see_others_notification(self, client, tt_headers):
        # B 用户不拥有、也不在跑 A 的产品 → 看不到
        other_hdr, other_uid = _make_tt_user(client, "ttuser_b")
        db = database.get_db()
        uid = db.execute("SELECT id FROM users WHERE username='ttuser'").fetchone()["id"]
        pid = _mk_product(db, uid)
        _mark_delisted(db, _mk_package(db, pid))
        db.close()

        resp = client.get("/api/tt/delist/pending", headers=other_hdr)
        assert resp.status_code == 200
        assert resp.get_json()["notifications"] == []

    def test_runner_sees_notification(self, client, tt_headers):
        # B 是 A 产品的在跑人员 → 能看到
        other_hdr, other_uid = _make_tt_user(client, "ttuser_runner")
        db = database.get_db()
        uid = db.execute("SELECT id FROM users WHERE username='ttuser'").fetchone()["id"]
        pid = _mk_product(db, uid)
        db.execute("INSERT INTO tt_product_runners(product_id, user_id) VALUES(?,?)", (pid, other_uid))
        _mark_delisted(db, _mk_package(db, pid))
        db.commit()
        db.close()

        resp = client.get("/api/tt/delist/pending", headers=other_hdr)
        notifs = resp.get_json()["notifications"]
        assert len(notifs) == 1
        assert notifs[0]["product_id"] == pid

    def test_developer_sees_all(self, client, dev_headers):
        _, uid = _make_tt_user(client, "ttuser_dev")
        db = database.get_db()
        pid = _mk_product(db, uid)
        _mark_delisted(db, _mk_package(db, pid))
        db.close()

        resp = client.get("/api/tt/delist/pending", headers=dev_headers)
        assert resp.status_code == 200
        assert len(resp.get_json()["notifications"]) == 1

    def test_dropped_package_excluded(self, client, tt_headers):
        # 包状态已设为「掉包」→ 不再通知
        db = database.get_db()
        uid = db.execute("SELECT id FROM users WHERE username='ttuser'").fetchone()["id"]
        pid = _mk_product(db, uid)
        _mark_delisted(db, _mk_package(db, pid, "系列乙", status="dropped"))
        db.close()

        resp = client.get("/api/tt/delist/pending", headers=tt_headers)
        assert resp.get_json()["notifications"] == []

    def test_paused_product_excluded(self, client, tt_headers):
        db = database.get_db()
        uid = db.execute("SELECT id FROM users WHERE username='ttuser'").fetchone()["id"]
        pid = _mk_product(db, uid, status="paused")
        _mark_delisted(db, _mk_package(db, pid))
        db.close()

        resp = client.get("/api/tt/delist/pending", headers=tt_headers)
        assert resp.get_json()["notifications"] == []

    def test_pwa_package_excluded_from_pending(self, client, tt_headers):
        """PWA 包不弹通知 —— 与两处检测口径统一（掉包只针对 type='package'）。"""
        db = database.get_db()
        uid = db.execute("SELECT id FROM users WHERE username='ttuser'").fetchone()["id"]
        pid = _mk_product(db, uid)
        _mark_delisted(db, _mk_package(db, pid, "PWA系列", pkg_type="pwa"))
        db.close()

        resp = client.get("/api/tt/delist/pending", headers=tt_headers)
        assert resp.get_json()["notifications"] == []

    def test_non_tt_platform_admin_sees_nothing(self, client, tt_headers):
        """非 TT 平台的 admin 不得越平台看到 TT 掉包数据（与 delist-status 的 @tt_required 同边界）。"""
        db = database.get_db()
        uid = db.execute("SELECT id FROM users WHERE username='ttuser'").fetchone()["id"]
        pid = _mk_product(db, uid)
        _mark_delisted(db, _mk_package(db, pid))
        db.close()

        # GG 平台的 admin：role=admin，platform 保持默认 'gg'
        client.post("/api/auth/register", json={"username": "ggadmin", "password": "test123"})
        db = database.get_db()
        db.execute("UPDATE users SET role='admin' WHERE username='ggadmin'")
        db.commit()
        db.close()
        token = client.post("/api/auth/login",
                            json={"username": "ggadmin", "password": "test123"}).get_json()["access_token"]
        hdr = {"Authorization": f"Bearer {token}"}

        # 对照：同边界下 delist-status 直接 403
        assert client.get("/api/tt/products/delist-status", headers=hdr).status_code == 403
        # pending 静默返回空：既不泄露全部 TT 数据，也不产生 30s 一次的 403 噪声
        resp = client.get("/api/tt/delist/pending", headers=hdr)
        assert resp.status_code == 200
        assert resp.get_json()["notifications"] == []

    def test_multi_package_grouped_into_one_notification(self, client, tt_headers):
        """同一产品多包掉包 → 聚合成一条通知，series_names / package_ids 去重收集。"""
        db = database.get_db()
        uid = db.execute("SELECT id FROM users WHERE username='ttuser'").fetchone()["id"]
        pid = _mk_product(db, uid)
        p1 = _mk_package(db, pid, "系列A")
        p2 = _mk_package(db, pid, "系列B")
        _mark_delisted(db, p1)
        _mark_delisted(db, p2)
        db.close()

        notifs = client.get("/api/tt/delist/pending", headers=tt_headers).get_json()["notifications"]
        assert len(notifs) == 1
        assert set(notifs[0]["series_names"]) == {"系列A", "系列B"}
        assert set(notifs[0]["package_ids"]) == {p1, p2}
        assert notifs[0]["type"] == "first"

    def test_first_takes_priority_over_reminder_in_group(self, client, tt_headers):
        """组内既有 first 又有 reminder 时，整组按 first 处理（避免新包被旧包的提醒掩盖）。"""
        db = database.get_db()
        uid = db.execute("SELECT id FROM users WHERE username='ttuser'").fetchone()["id"]
        pid = _mk_product(db, uid)
        p1 = _mk_package(db, pid, "系列A")
        p2 = _mk_package(db, pid, "系列B")
        _mark_delisted(db, p1)
        _mark_delisted(db, p2)
        db.close()

        # p1 关闭通知并回拨 4 分钟 → 变成 reminder；p2 从未通知 → 仍是 first
        assert client.post("/api/tt/delist/dismiss", headers=tt_headers,
                           json={"package_ids": [p1]}).status_code == 200
        old = (datetime.datetime.now(datetime.timezone.utc)
               - datetime.timedelta(seconds=240)).isoformat()
        db = database.get_db()
        db.execute("UPDATE tt_delist_notifications SET dismissed_at=? "
                   "WHERE package_id=? AND user_id=?", (old, p1, uid))
        db.commit()
        db.close()

        notifs = client.get("/api/tt/delist/pending", headers=tt_headers).get_json()["notifications"]
        assert len(notifs) == 1
        assert notifs[0]["type"] == "first"

    def test_dismiss_then_reminder_after_3min(self, client, tt_headers):
        db = database.get_db()
        uid = db.execute("SELECT id FROM users WHERE username='ttuser'").fetchone()["id"]
        pid = _mk_product(db, uid)
        pkg = _mk_package(db, pid, "系列丙")
        _mark_delisted(db, pkg)
        db.close()

        # 首次：type=first
        resp = client.get("/api/tt/delist/pending", headers=tt_headers)
        assert resp.get_json()["notifications"][0]["type"] == "first"

        # 关闭 → 3 分钟内不再提醒
        assert client.post("/api/tt/delist/dismiss", headers=tt_headers,
                           json={"package_ids": [pkg]}).status_code == 200
        resp = client.get("/api/tt/delist/pending", headers=tt_headers)
        assert resp.get_json()["notifications"] == []

        # 把 dismissed_at 改到 4 分钟前 → 转为 reminder
        old = (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(seconds=240)).isoformat()
        db = database.get_db()
        db.execute("UPDATE tt_delist_notifications SET dismissed_at=? WHERE package_id=? AND user_id=?",
                   (old, pkg, uid))
        db.commit()
        db.close()

        resp = client.get("/api/tt/delist/pending", headers=tt_headers)
        notifs = resp.get_json()["notifications"]
        assert len(notifs) == 1
        assert notifs[0]["type"] == "reminder"
        # 口径与 GG 一致：首次 dismiss 插入 reminder_count=0，其后每次 dismiss 递增
        assert notifs[0]["reminder_count"] == 0


# ==================== dismiss 接口 ====================

class TestTtDelistDismiss:
    def test_dismiss_writes_notification_row(self, client, tt_headers):
        db = database.get_db()
        uid = db.execute("SELECT id FROM users WHERE username='ttuser'").fetchone()["id"]
        pid = _mk_product(db, uid)
        pkg = _mk_package(db, pid)
        db.close()

        resp = client.post("/api/tt/delist/dismiss", headers=tt_headers,
                           json={"package_ids": [pkg]})
        assert resp.status_code == 200
        assert resp.get_json()["success"] is True

        db = database.get_db()
        row = db.execute("SELECT * FROM tt_delist_notifications WHERE package_id=? AND user_id=?",
                         (pkg, uid)).fetchone()
        db.close()
        assert row is not None
        assert row["first_notified"] == 1
        assert row["dismissed_at"]

    def test_dismiss_missing_ids_returns_400(self, client, tt_headers):
        resp = client.post("/api/tt/delist/dismiss", headers=tt_headers, json={})
        assert resp.status_code == 400

    def test_batch_dismiss_multiple_package_ids(self, client, tt_headers):
        db = database.get_db()
        uid = db.execute("SELECT id FROM users WHERE username='ttuser'").fetchone()["id"]
        pid = _mk_product(db, uid)
        p1 = _mk_package(db, pid, "系列A")
        p2 = _mk_package(db, pid, "系列B")
        db.close()

        resp = client.post("/api/tt/delist/dismiss", headers=tt_headers,
                           json={"package_ids": [p1, p2]})
        assert resp.status_code == 200

        db = database.get_db()
        cnt = db.execute("SELECT COUNT(*) AS c FROM tt_delist_notifications "
                         "WHERE user_id=? AND package_id IN (?,?)", (uid, p1, p2)).fetchone()["c"]
        db.close()
        assert cnt == 2

    def test_dismiss_accepts_single_package_id_field(self, client, tt_headers):
        """兼容单数字段 package_id（GG 老口径）。"""
        db = database.get_db()
        uid = db.execute("SELECT id FROM users WHERE username='ttuser'").fetchone()["id"]
        pid = _mk_product(db, uid)
        pkg = _mk_package(db, pid)
        db.close()

        resp = client.post("/api/tt/delist/dismiss", headers=tt_headers,
                           json={"package_id": pkg})
        assert resp.status_code == 200
        db = database.get_db()
        row = db.execute("SELECT id FROM tt_delist_notifications "
                         "WHERE package_id=? AND user_id=?", (pkg, uid)).fetchone()
        db.close()
        assert row is not None

    def test_repeated_dismiss_increments_reminder_count(self, client, tt_headers):
        db = database.get_db()
        uid = db.execute("SELECT id FROM users WHERE username='ttuser'").fetchone()["id"]
        pid = _mk_product(db, uid)
        pkg = _mk_package(db, pid)
        db.close()

        for _ in range(2):
            client.post("/api/tt/delist/dismiss", headers=tt_headers, json={"package_ids": [pkg]})

        db = database.get_db()
        row = db.execute("SELECT reminder_count FROM tt_delist_notifications "
                         "WHERE package_id=? AND user_id=?", (pkg, uid)).fetchone()
        db.close()
        # 口径与 GG 一致：首次 insert(0) + 第二次 update(+1) = 1
        assert row["reminder_count"] == 1


# ==================== 通知状态表清理（对齐 GG 的既有不变量） ====================

class TestTtDelistNotificationCleanup:
    def test_deleting_package_removes_notification_rows(self, client, tt_headers):
        """删除跑包 → 同步清理通知状态行（对齐 GG「包删除 → 清理 delist_notifications」）。"""
        db = database.get_db()
        uid = db.execute("SELECT id FROM users WHERE username='ttuser'").fetchone()["id"]
        pid = _mk_product(db, uid)
        pkg = _mk_package(db, pid)
        db.close()

        assert client.post("/api/tt/delist/dismiss", headers=tt_headers,
                           json={"package_ids": [pkg]}).status_code == 200
        assert client.delete(f"/api/tt/packages/{pkg}", headers=tt_headers).status_code == 200

        db = database.get_db()
        cnt = db.execute("SELECT COUNT(*) AS c FROM tt_delist_notifications "
                         "WHERE package_id=?", (pkg,)).fetchone()["c"]
        db.close()
        assert cnt == 0

    def test_batch_deleting_packages_removes_notification_rows(self, client, tt_headers):
        db = database.get_db()
        uid = db.execute("SELECT id FROM users WHERE username='ttuser'").fetchone()["id"]
        pid = _mk_product(db, uid)
        p1 = _mk_package(db, pid, "系列A")
        p2 = _mk_package(db, pid, "系列B")
        db.close()

        assert client.post("/api/tt/delist/dismiss", headers=tt_headers,
                           json={"package_ids": [p1, p2]}).status_code == 200
        assert client.post("/api/tt/packages/batch-delete", headers=tt_headers,
                           json={"ids": [p1, p2]}).status_code == 200

        db = database.get_db()
        cnt = db.execute("SELECT COUNT(*) AS c FROM tt_delist_notifications "
                         "WHERE package_id IN (?,?)", (p1, p2)).fetchone()["c"]
        db.close()
        assert cnt == 0


# ==================== Telegram 发送（TT 独立机器人） ====================

class TestTtTelegramSender:
    def test_skips_when_unconfigured(self, client, monkeypatch):
        monkeypatch.setattr(tt_routes, "_load_tt_telegram_config", lambda: {})
        db = database.get_db()
        sent = tt_routes.send_tt_delist_notifications(
            db, [{"product_id": 1, "product_name": "P", "series_name": "S"}])
        db.close()
        assert sent == 0

    def test_grouped_by_product_with_runner_usernames(self, client, tt_headers, monkeypatch):
        db = database.get_db()
        uid = db.execute("SELECT id FROM users WHERE username='ttuser'").fetchone()["id"]
        pid = _mk_product(db, uid, "产品X")
        db.execute("INSERT INTO tt_product_runners(product_id, user_id) VALUES(?,?)", (pid, uid))
        db.execute("UPDATE users SET telegram_username='carl_test' WHERE id=?", (uid,))
        db.commit()

        monkeypatch.setattr(tt_routes, "_load_tt_telegram_config",
                            lambda: {"bot_token": "T", "chat_id": "C"})
        calls = []

        def _fake_send(config, product_name, series_names, usernames, title="GG-Server"):
            calls.append({
                "product_name": product_name, "series_names": series_names,
                "usernames": usernames, "title": title,
            })
            return True

        monkeypatch.setattr(telegram_sender, "send_product_delist_notification", _fake_send)

        # 同一产品两个包 → 聚合成一条通知，系列名去重
        pkgs = [
            {"product_id": pid, "product_name": "产品X", "series_name": "系列1"},
            {"product_id": pid, "product_name": "产品X", "series_name": "系列2"},
        ]
        sent = tt_routes.send_tt_delist_notifications(db, pkgs)
        db.close()

        assert sent == 1
        assert len(calls) == 1
        assert calls[0]["title"] == "TT-Server"          # 独立机器人标题
        assert calls[0]["product_name"] == "产品X"
        assert calls[0]["series_names"] == ["系列1", "系列2"]
        assert calls[0]["usernames"] == ["carl_test"]    # 来自 tt_product_runners


class TestTelegramSenderTitleParam:
    def test_gg_default_title(self):
        msg = telegram_sender._build_product_message("产品", ["系列"], [])
        assert "GG-Server 掉包通知" in msg

    def test_tt_title(self):
        msg = telegram_sender._build_product_message("产品", ["系列"], [], title="TT-Server")
        assert "TT-Server 掉包通知" in msg
        assert "GG-Server" not in msg


# ==================== 手动检测补通知 ====================

class TestTtManualCheckNotify:
    def test_manual_check_sends_notification_when_delisted(self, client, tt_headers, monkeypatch):
        db = database.get_db()
        uid = db.execute("SELECT id FROM users WHERE username='ttuser'").fetchone()["id"]
        pid = _mk_product(db, uid, "产品Y")
        _mk_package(db, pid, "系列M")
        db.close()

        monkeypatch.setattr(delist_checker, "check_product_packages",
                            lambda pid_, pkgs, pool: [
                                {"package_id": p["id"], "product_id": pid_,
                                 "is_delisted": True, "error": ""} for p in pkgs])
        sent = []
        monkeypatch.setattr(tt_routes, "send_tt_delist_notifications",
                            lambda db_, pkgs, title="TT-Server": sent.append(pkgs) or 1)

        resp = client.post(f"/api/tt/products/{pid}/check-delist", headers=tt_headers)
        assert resp.status_code == 200
        assert len(sent) == 1
        assert sent[0][0]["product_name"] == "产品Y"

    def test_manual_check_no_notification_when_all_normal(self, client, tt_headers, monkeypatch):
        db = database.get_db()
        uid = db.execute("SELECT id FROM users WHERE username='ttuser'").fetchone()["id"]
        pid = _mk_product(db, uid)
        _mk_package(db, pid)
        db.close()

        monkeypatch.setattr(delist_checker, "check_product_packages",
                            lambda pid_, pkgs, pool: [
                                {"package_id": p["id"], "product_id": pid_,
                                 "is_delisted": False, "error": ""} for p in pkgs])
        sent = []
        monkeypatch.setattr(tt_routes, "send_tt_delist_notifications",
                            lambda db_, pkgs, title="TT-Server": sent.append(pkgs) or 1)

        resp = client.post(f"/api/tt/products/{pid}/check-delist", headers=tt_headers)
        assert resp.status_code == 200
        assert sent == []

    def test_manual_check_skips_non_normal_packages(self, client, tt_headers, monkeypatch):
        """非正常状态（暂停/已掉包/拒登/没事件）的包不检测、不通知 —— 口径同 GG 手动检测。"""
        db = database.get_db()
        uid = db.execute("SELECT id FROM users WHERE username='ttuser'").fetchone()["id"]
        pid = _mk_product(db, uid, "全非正常产品")
        for st in ("paused", "dropped", "rejected", "no_events"):
            _mk_package(db, pid, "系列-" + st, status=st)
        db.close()

        checked = []

        def _fake_check_product(pid_, pkgs, pool):
            checked.append(list(pkgs))
            return []

        monkeypatch.setattr(delist_checker, "check_product_packages", _fake_check_product)
        sent = []
        monkeypatch.setattr(tt_routes, "send_tt_delist_notifications",
                            lambda db_, pkgs, title="TT-Server": sent.append(pkgs) or 1)

        resp = client.post(f"/api/tt/products/{pid}/check-delist", headers=tt_headers)
        assert resp.status_code == 200
        assert resp.get_json()["results"] == []
        assert checked == []  # 未发起任何 HTTP 检测
        assert sent == []


# ==================== 定时检测 ====================

class TestTtDelistScheduler:
    def test_only_packages_type_checked_and_new_delist_notified_once(self, client, tt_headers, monkeypatch):
        import main

        db = database.get_db()
        uid = db.execute("SELECT id FROM users WHERE username='ttuser'").fetchone()["id"]
        pid = _mk_product(db, uid, "定时产品")
        pkg_run = _mk_package(db, pid, "跑包", pkg_type="package")
        pkg_pwa = _mk_package(db, pid, "PWA包", pkg_type="pwa")
        pkg_dropped = _mk_package(db, pid, "已掉包包", status="dropped")
        db.commit()
        db.close()

        checked_urls = []

        def _fake_check(url, pool=None):
            checked_urls.append(url)
            return True, ""

        monkeypatch.setattr(delist_checker, "check_url_delisted", _fake_check)
        monkeypatch.setattr(main, "_build_delist_proxy_pool", lambda: None)
        notified = []
        monkeypatch.setattr(tt_routes, "send_tt_delist_notifications",
                            lambda db_, pkgs, title="TT-Server": notified.append(pkgs) or len(pkgs))

        result = main._run_tt_delist_check_once()

        # 只有 type='package' 且状态正常的包被检测
        assert result["total"] == 1
        assert len(checked_urls) == 1

        # 首次检测到掉包 → 发一次通知
        assert len(notified) == 1

        # 第二次检测：仍是掉包但非「新掉包」→ 不再发
        notified.clear()
        main._run_tt_delist_check_once()
        assert notified == []

    def test_scheduler_skips_non_normal_packages(self, client, tt_headers, monkeypatch):
        """定时检测只跑「正常」状态的包，暂停/已掉包/拒登/没事件一律跳过。"""
        import main

        db = database.get_db()
        uid = db.execute("SELECT id FROM users WHERE username='ttuser'").fetchone()["id"]
        pid = _mk_product(db, uid, "定时非正常产品")
        _mk_package(db, pid, "正常包", status="")
        for st in ("paused", "dropped", "rejected", "no_events"):
            _mk_package(db, pid, "包-" + st, status=st)
        db.close()

        checked_urls = []

        def _fake_check(url, pool=None):
            checked_urls.append(url)
            return True, ""

        monkeypatch.setattr(delist_checker, "check_url_delisted", _fake_check)
        monkeypatch.setattr(main, "_build_delist_proxy_pool", lambda: None)
        notified = []
        monkeypatch.setattr(tt_routes, "send_tt_delist_notifications",
                            lambda db_, pkgs, title="TT-Server": notified.append(pkgs) or len(pkgs))

        result = main._run_tt_delist_check_once()

        assert result["total"] == 1
        assert len(checked_urls) == 1
        assert len(notified) == 1

    def test_no_packages_returns_zero(self, client, monkeypatch):
        import main
        monkeypatch.setattr(main, "_build_delist_proxy_pool", lambda: None)
        result = main._run_tt_delist_check_once()
        assert result["total"] == 0
        assert result["delisted"] == 0
