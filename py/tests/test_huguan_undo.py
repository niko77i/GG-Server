"""户管看板同步撤回（子项目 ③）测试。

设计见 docs/superpowers/specs/2026-10-06-huguan-sync-undo-design.md。
本文件不打真实 Google API。
"""
import pytest

import database
import huguan_dashboard as hd


@pytest.fixture
def fb_user(client):
    """一个 FB 平台的户管，返回其 id。"""
    db = database.get_db()
    db.execute("INSERT INTO users(username, password, role, platform) "
               "VALUES('u_undo', 'x', 'huguan', 'fb')")
    uid = db.execute("SELECT last_insert_rowid()").fetchone()[0]
    db.commit()
    db.close()
    return uid


class TestUndoPrimitives:
    def test_table_exists(self, client):
        db = database.get_db()
        cols = {r[1] for r in db.execute("PRAGMA table_info(huguan_sync_undo)").fetchall()}
        db.close()
        assert {"id", "user_id", "platform", "direction", "created_at", "payload"} <= cols

    def test_save_then_load(self, client, fb_user):
        db = database.get_db()
        hd.save_undo(db, fb_user, "fb", "push", {"cells": [{"account_id": "A1"}]})
        db.commit()
        got = hd.load_undo(db, fb_user, "fb", "push")
        db.close()
        assert got == {"cells": [{"account_id": "A1"}]}

    def test_load_missing_returns_none(self, client, fb_user):
        db = database.get_db()
        got = hd.load_undo(db, fb_user, "fb", "sync")
        db.close()
        assert got is None

    def test_save_is_idempotent_last_wins(self, client, fb_user):
        """UNIQUE(user_id, platform, direction) ⇒ 只留最近一条。"""
        db = database.get_db()
        hd.save_undo(db, fb_user, "fb", "push", {"v": 1})
        hd.save_undo(db, fb_user, "fb", "push", {"v": 2})
        db.commit()
        n = db.execute("SELECT COUNT(*) FROM huguan_sync_undo "
                       "WHERE user_id=? AND platform='fb' AND direction='push'",
                       (fb_user,)).fetchone()[0]
        got = hd.load_undo(db, fb_user, "fb", "push")
        db.close()
        assert n == 1
        assert got == {"v": 2}

    def test_platforms_and_directions_are_independent(self, client, fb_user):
        db = database.get_db()
        hd.save_undo(db, fb_user, "fb", "push", {"k": "fb-push"})
        hd.save_undo(db, fb_user, "fb", "sync", {"k": "fb-sync"})
        hd.save_undo(db, fb_user, "gg", "push", {"k": "gg-push"})
        db.commit()
        assert hd.load_undo(db, fb_user, "fb", "push") == {"k": "fb-push"}
        assert hd.load_undo(db, fb_user, "fb", "sync") == {"k": "fb-sync"}
        assert hd.load_undo(db, fb_user, "gg", "push") == {"k": "gg-push"}
        db.close()

    def test_delete(self, client, fb_user):
        db = database.get_db()
        hd.save_undo(db, fb_user, "fb", "push", {"v": 1})
        db.commit()
        hd.delete_undo(db, fb_user, "fb", "push")
        db.commit()
        assert hd.load_undo(db, fb_user, "fb", "push") is None
        db.close()

    def test_two_users_do_not_share(self, client, fb_user):
        db = database.get_db()
        db.execute("INSERT INTO users(username, password, role, platform) "
                   "VALUES('u_undo2', 'x', 'huguan', 'fb')")
        uid2 = db.execute("SELECT last_insert_rowid()").fetchone()[0]
        hd.save_undo(db, fb_user, "fb", "push", {"who": 1})
        db.commit()
        assert hd.load_undo(db, uid2, "fb", "push") is None
        db.close()

    def test_unknown_direction_rejected(self, client, fb_user):
        db = database.get_db()
        with pytest.raises(ValueError):
            hd.save_undo(db, fb_user, "fb", "redo", {"v": 1})
        db.close()

    # ---------- load_undo 的坏 payload 契约：坏数据 → None，绝不抛 ----------

    def test_load_invalid_json_returns_none(self, client, fb_user):
        """payload 不是合法 JSON ⇒ None（撤回入口据此禁用），不得抛异常。"""
        db = database.get_db()
        db.execute("INSERT INTO huguan_sync_undo(user_id, platform, direction, payload) "
                   "VALUES(?, 'fb', 'push', ?)", (fb_user, "{not json"))
        db.commit()
        assert hd.load_undo(db, fb_user, "fb", "push") is None
        db.close()

    @pytest.mark.parametrize("raw", ["[1,2]", "null", '"str"', "42"])
    def test_load_valid_json_not_dict_returns_none(self, client, fb_user, raw):
        """合法 JSON 但不是 dict ⇒ None（快照协议只认 dict）。"""
        db = database.get_db()
        db.execute("INSERT INTO huguan_sync_undo(user_id, platform, direction, payload) "
                   "VALUES(?, 'fb', 'push', ?)", (fb_user, raw))
        db.commit()
        assert hd.load_undo(db, fb_user, "fb", "push") is None
        db.close()

    def test_load_empty_payload_returns_none(self, client, fb_user):
        """payload 为空串 ⇒ None（与「无行」同一条短路分支）。"""
        db = database.get_db()
        db.execute("INSERT INTO huguan_sync_undo(user_id, platform, direction, payload) "
                   "VALUES(?, 'fb', 'push', '')", (fb_user,))
        db.commit()
        assert hd.load_undo(db, fb_user, "fb", "push") is None
        db.close()

    def test_save_delete_do_not_commit(self, client, fb_user):
        """原语与调用方共用事务：save_undo / delete_undo 都不得 commit。"""
        db = database.get_db()
        assert db.in_transaction is False, "前置：连接应处于无事务状态"
        hd.save_undo(db, fb_user, "fb", "push", {"v": 1})
        assert db.in_transaction is True, "save_undo 不得 commit"
        hd.delete_undo(db, fb_user, "fb", "push")
        assert db.in_transaction is True, "delete_undo 不得 commit"
        db.close()


class FakeService:
    """假 Sheets 服务：只记下写入了什么，不打网络。"""
    def __init__(self):
        self.writes = []


class TestPushSnapshot:
    def test_snapshot_only_covers_rows_present_in_sheet(self, client, fb_user, monkeypatch):
        """表里没有的账户本来就不会被写，不进快照。"""
        db = database.get_db()
        db.execute("INSERT INTO fb_accounts(name, account_id, owner_id) VALUES('户','U1',?)",
                   (fb_user,))
        db.execute("INSERT INTO fb_accounts(name, account_id, owner_id) VALUES('户2','U2',?)",
                   (fb_user,))
        db.commit()
        rows = hd.collect_rows_for_push(db, "fb")
        db.close()

        # 假表：只有 U1 在表里
        grid = [[""] * 17, [""] * 17]
        grid[1][hd.col_index("D")] = "U1"
        monkeypatch.setattr(hd, "read_sheet_values",
                            lambda svc, sid, name, rng: grid)

        payload = hd.snapshot_push_targets(
            FakeService(), {"spreadsheet_id": "S", "sheet_name": "N"}, "fb", rows)
        ids = [c["account_id"] for c in payload["cells"]]
        assert ids == ["U1"]

    def test_snapshot_records_only_columns_that_will_be_written(self, client, fb_user, monkeypatch):
        db = database.get_db()
        db.execute("INSERT INTO fb_accounts(name, account_id, owner_id) VALUES('户','U3',?)",
                   (fb_user,))
        db.commit()
        rows = hd.collect_rows_for_push(db, "fb")
        db.close()

        grid = [[""] * 17, [""] * 17]
        grid[1][hd.col_index("D")] = "U3"
        grid[1][hd.col_index("C")] = "表里的旧名"
        grid[1][hd.col_index("I")] = "不该被记"
        monkeypatch.setattr(hd, "read_sheet_values",
                            lambda svc, sid, name, rng: grid)

        payload = hd.snapshot_push_targets(
            FakeService(), {"spreadsheet_id": "S", "sheet_name": "N"}, "fb", rows)
        cells = payload["cells"][0]["cells"]
        # C 列会被批量写（writable=True）⇒ 必须记
        assert cells.get("C") == "表里的旧名"
        # I 列 writable=False ⇒ 批量根本不写它，不该进快照
        assert "I" not in cells

    def test_undo_cells_are_writable_input(self, client, fb_user, monkeypatch):
        payload = {"spreadsheet_id": "S", "sheet_name": "N",
                   "cells": [{"account_id": "U1", "cells": {"C": "旧", "G": "9"}}]}
        out = hd.push_undo_cells(payload)
        assert out[0]["account_id"] == "U1"
        assert out[0]["cells"] == {"C": "旧", "G": "9"}


# ---------- load_undo_meta：只给状态端点用的「payload + created_at」 ----------

class TestLoadUndoMeta:
    """`load_undo` 的契约是「返回 payload 本身」，不能改动；created_at 另走本函数。"""

    def test_meta_returns_payload_and_created_at(self, client, fb_user):
        db = database.get_db()
        hd.save_undo(db, fb_user, "fb", "push", {"cells": [{"account_id": "A"}]})
        db.commit()
        meta = hd.load_undo_meta(db, fb_user, "fb", "push")
        db.close()
        assert meta["payload"] == {"cells": [{"account_id": "A"}]}
        # 建表时 created_at 是 DEFAULT (datetime('now','localtime'))，落库后必须非空
        assert meta["created_at"]

    def test_meta_missing_returns_none(self, client, fb_user):
        db = database.get_db()
        assert hd.load_undo_meta(db, fb_user, "fb", "sync") is None
        db.close()

    def test_meta_bad_payload_returns_none(self, client, fb_user):
        """坏 payload 与「无快照」同形（都 None），与 load_undo 的短路口径一致。"""
        db = database.get_db()
        db.execute("INSERT INTO huguan_sync_undo(user_id, platform, direction, payload) "
                   "VALUES(?, 'fb', 'push', ?)", (fb_user, "{not json"))
        db.commit()
        assert hd.load_undo_meta(db, fb_user, "fb", "push") is None
        db.close()

    def test_meta_does_not_change_load_undo_contract(self, client, fb_user):
        """回归哨兵：load_undo 仍旧只返回 payload（Task 1 已交付的契约）。"""
        db = database.get_db()
        hd.save_undo(db, fb_user, "fb", "push", {"v": 1})
        db.commit()
        assert hd.load_undo(db, fb_user, "fb", "push") == {"v": 1}
        db.close()


class TestPushUndoRoute:
    """`undo_push` 的执行：写回快照里的格子 → 作废快照（规格 §6.1）。"""

    def test_undo_available_reflects_snapshot(self, client, fb_user):
        db = database.get_db()
        hd.save_undo(db, fb_user, "fb", "push", {"cells": [{"account_id": "A", "cells": {}}]})
        db.commit()
        db.close()
        # 直接调逻辑层（路由层需要 JWT，另测）
        db = database.get_db()
        got = hd.load_undo(db, fb_user, "fb", "push")
        db.close()
        assert got is not None

    def test_undo_only_touches_own_records(self, client, fb_user):
        db = database.get_db()
        db.execute("INSERT INTO users(username, password, role, platform) "
                   "VALUES('u_other', 'x', 'huguan', 'fb')")
        other = db.execute("SELECT last_insert_rowid()").fetchone()[0]
        hd.save_undo(db, fb_user, "fb", "push", {"v": 1})
        db.commit()
        assert hd.load_undo(db, other, "fb", "push") is None
        db.close()

    def test_undo_uses_writeback_helper(self, client, fb_user, monkeypatch):
        """撤回走 update_rows_by_account_id，且只带快照里的格子。"""
        calls = []
        db = database.get_db()
        hd.save_undo(db, fb_user, "fb", "push",
                     {"spreadsheet_id": "S", "sheet_name": "N",
                      "cells": [{"account_id": "U9", "cells": {"C": "旧名"}}]})
        db.commit()
        db.close()
        monkeypatch.setattr(hd, "_open_db", lambda: database.get_db())
        monkeypatch.setattr(hd, "get_platform_config",
                            lambda db_, uid, p: {"spreadsheet_id": "S", "sheet_name": "N"})
        import google_sheets_service as gs
        monkeypatch.setattr(gs, "build_service", lambda path: object())
        monkeypatch.setattr(gs, "update_rows_by_account_id",
                            lambda svc, sid, name, rows, key_col="C":
                            calls.append({"sid": sid, "name": name,
                                          "rows": rows, "key_col": key_col})
                            or {"updated": len(rows), "not_found": []})
        out = hd.undo_push(fb_user, "fb")
        assert calls and calls[0]["rows"][0]["account_id"] == "U9"
        assert calls[0]["rows"][0]["cells"] == {"C": "旧名"}
        # FB 的账户ID在 D 列：不显式传 key_col 就退回默认 "C"（账户名称）→ 整批静默写空
        assert calls[0]["key_col"] == "D"
        assert out["updated"] == 1

    def test_gg_undo_uses_key_col_C(self, client, monkeypatch):
        """对照：GG 的定位列是 "C"，显式传参必须仍是 "C"（挡「一律硬传 D」的变异体）。"""
        _hg, uid = _make_user(client, "_undo_gg_keycol", role="huguan", platform="gg")
        calls = []
        db = database.get_db()
        hd.save_undo(db, uid, "gg", "push",
                     {"spreadsheet_id": "S", "sheet_name": "N",
                      "cells": [{"account_id": "G1", "cells": {"C": "跨平台旧值"}}]})
        db.commit()
        db.close()
        monkeypatch.setattr(hd, "_open_db", lambda: database.get_db())
        monkeypatch.setattr(hd, "get_platform_config",
                            lambda db_, u, p: {"spreadsheet_id": "S", "sheet_name": "N"})
        import google_sheets_service as gs
        monkeypatch.setattr(gs, "build_service", lambda path: object())
        monkeypatch.setattr(gs, "update_rows_by_account_id",
                            lambda svc, sid, name, rows, key_col="C":
                            calls.append(key_col) or {"updated": len(rows), "not_found": []})
        hd.undo_push(uid, "gg")
        assert calls == ["C"]

    def test_undo_deletes_snapshot_after_write(self, client, fb_user, monkeypatch):
        """写回成功后快照必须作废 —— 否则能对同一次 push 反复撤回。"""
        db = database.get_db()
        hd.save_undo(db, fb_user, "fb", "push",
                     {"spreadsheet_id": "S", "sheet_name": "N",
                      "cells": [{"account_id": "U9", "cells": {"C": "旧"}}]})
        db.commit()
        db.close()
        monkeypatch.setattr(hd, "_open_db", lambda: database.get_db())
        monkeypatch.setattr(hd, "get_platform_config",
                            lambda db_, uid, p: {"spreadsheet_id": "S", "sheet_name": "N"})
        import google_sheets_service as gs
        monkeypatch.setattr(gs, "build_service", lambda path: object())
        monkeypatch.setattr(gs, "update_rows_by_account_id",
                            lambda *a, **k: {"updated": 1, "not_found": []})
        hd.undo_push(fb_user, "fb")
        db = database.get_db()
        assert hd.load_undo(db, fb_user, "fb", "push") is None
        db.close()

    def test_undo_without_snapshot_is_noop(self, client, fb_user, monkeypatch):
        """没有快照 ⇒ 全零，且绝不碰写入器（不能凭空写表）。"""
        calls = []
        monkeypatch.setattr(hd, "_open_db", lambda: database.get_db())
        monkeypatch.setattr(hd, "get_platform_config",
                            lambda db_, uid, p: {"spreadsheet_id": "S", "sheet_name": "N"})
        import google_sheets_service as gs
        monkeypatch.setattr(gs, "update_rows_by_account_id",
                            lambda *a, **k: calls.append(1) or {"updated": 0, "not_found": []})
        out = hd.undo_push(fb_user, "fb")
        assert out == {"updated": 0, "not_found": []}
        assert calls == []

    def test_undo_unconfigured_dashboard_returns_zero(self, client, fb_user, monkeypatch):
        """未配置看板 ⇒ 全零（与 push_rows 的静默跳过同口径），不碰写入器。"""
        calls = []
        monkeypatch.setattr(hd, "_open_db", lambda: database.get_db())
        monkeypatch.setattr(hd, "get_platform_config",
                            lambda db_, uid, p: {"spreadsheet_id": "", "sheet_name": ""})
        import google_sheets_service as gs
        monkeypatch.setattr(gs, "update_rows_by_account_id",
                            lambda *a, **k: calls.append(1) or {"updated": 0, "not_found": []})
        assert hd.undo_push(fb_user, "fb") == {"updated": 0, "not_found": []}
        assert calls == []

    def test_undo_empty_cells_clears_snapshot(self, client, fb_user, monkeypatch):
        """快照覆盖 0 行 ⇒ 没东西可退，但快照要作废（否则按钮永久可点）。"""
        db = database.get_db()
        hd.save_undo(db, fb_user, "fb", "push", {"spreadsheet_id": "S", "cells": []})
        db.commit()
        db.close()
        monkeypatch.setattr(hd, "_open_db", lambda: database.get_db())
        monkeypatch.setattr(hd, "get_platform_config",
                            lambda db_, uid, p: {"spreadsheet_id": "S", "sheet_name": "N"})
        import google_sheets_service as gs
        monkeypatch.setattr(gs, "update_rows_by_account_id",
                            lambda *a, **k: {"updated": 0, "not_found": []})
        assert hd.undo_push(fb_user, "fb") == {"updated": 0, "not_found": []}
        db = database.get_db()
        assert hd.load_undo(db, fb_user, "fb", "push") is None
        db.close()


def _make_user(client, username, role="huguan", platform="fb"):
    """注册用户 → 改写 role/platform → 登录。返回 (headers, uid)。"""
    client.post("/api/auth/register", json={"username": username, "password": "test123"})
    db = database.get_db()
    db.execute("UPDATE users SET role=?, platform=? WHERE username=?",
               (role, platform, username))
    db.commit()
    uid = db.execute("SELECT id FROM users WHERE username=?", (username,)).fetchone()["id"]
    db.close()
    resp = client.post("/api/auth/login",
                       json={"username": username, "password": "test123"})
    return {"Authorization": f"Bearer {resp.get_json()['access_token']}"}, uid


def _huguan_headers(client, username, platform="fb"):
    """注册一个户管角色用户并登录，返回 (headers, uid)。"""
    return _make_user(client, username, role="huguan", platform=platform)


class TestUndoStatusRoute:
    """GET /api/huguan/dashboard/undo：两方向各有无可撤快照 + 时间（spec §7 / §八）。"""

    def test_reports_both_directions_with_created_at(self, client):
        hg, uid = _huguan_headers(client, "_undo_status")
        db = database.get_db()
        hd.save_undo(db, uid, "fb", "push",
                     {"cells": [{"account_id": "A"}, {"account_id": "B"}]})
        # sync 的 count 口径 = updates 项数 + created 项数
        hd.save_undo(db, uid, "fb", "sync",
                     {"updates": [{"account_id": "A"}], "created": [{"account_id": "C"}]})
        db.commit()
        db.close()
        got = client.get("/api/huguan/dashboard/undo?platform=fb", headers=hg).get_json()
        assert got["success"] is True
        assert got["push"]["count"] == 2
        assert got["sync"]["count"] == 2
        # spec §八：按钮旁小字「上一次：10-06 14:32」需要 created_at
        assert got["push"]["created_at"]
        assert got["sync"]["created_at"]

    def test_null_when_no_snapshot(self, client):
        hg, _ = _huguan_headers(client, "_undo_status_none")
        got = client.get("/api/huguan/dashboard/undo?platform=fb", headers=hg).get_json()
        assert got["push"] is None
        assert got["sync"] is None

    def test_only_own_snapshots_are_reported(self, client):
        """记录按 JWT 里的 uid 取：别人的快照不得让我的按钮亮起来。"""
        hg, _uid = _huguan_headers(client, "_undo_status_mine")
        _other_hg, other = _huguan_headers(client, "_undo_status_other")
        db = database.get_db()
        hd.save_undo(db, other, "fb", "push", {"cells": [{"account_id": "X"}]})
        db.commit()
        db.close()
        got = client.get("/api/huguan/dashboard/undo?platform=fb", headers=hg).get_json()
        assert got["push"] is None

    def test_platform_isolation(self, client):
        hg, uid = _huguan_headers(client, "_undo_status_iso")
        db = database.get_db()
        hd.save_undo(db, uid, "gg", "push", {"cells": [{"account_id": "A"}]})
        db.commit()
        db.close()
        got = client.get("/api/huguan/dashboard/undo?platform=fb", headers=hg).get_json()
        assert got["push"] is None

    def test_bad_platform_400(self, client):
        hg, _ = _huguan_headers(client, "_undo_status_bad")
        assert client.get("/api/huguan/dashboard/undo?platform=xx",
                          headers=hg).status_code == 400

    def test_missing_platform_400(self, client):
        hg, _ = _huguan_headers(client, "_undo_status_missing")
        assert client.get("/api/huguan/dashboard/undo", headers=hg).status_code == 400

    def test_non_huguan_403(self, client):
        h, _ = _make_user(client, "_undo_status_user", role="user")
        assert client.get("/api/huguan/dashboard/undo?platform=gg",
                          headers=h).status_code == 403
