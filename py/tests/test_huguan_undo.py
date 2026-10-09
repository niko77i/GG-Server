"""户管看板同步撤回（子项目 ③）测试。

设计见 docs/superpowers/specs/2026-10-06-huguan-sync-undo-design.md。
本文件不打真实 Google API。
"""
import json
import logging
import sqlite3

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
            FakeService(), {"spreadsheet_id": "S"}, "fb", [("N", rows)])
        ids = [c["account_id"] for c in payload["sheets"][0]["cells"]]
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
            FakeService(), {"spreadsheet_id": "S"}, "fb", [("N", rows)])
        cells = payload["sheets"][0]["cells"][0]["cells"]
        # C 列会被批量写（writable=True）⇒ 必须记
        assert cells.get("C") == "表里的旧名"
        # I 列 writable=False ⇒ 批量根本不写它，不该进快照
        assert "I" not in cells

    def test_undo_cells_are_writable_input(self, client, fb_user, monkeypatch):
        """旧形状快照仍要能转出写表入参（按表分组：`{"sheet_name", "rows"}`）。"""
        payload = {"spreadsheet_id": "S", "sheet_name": "N",
                   "cells": [{"account_id": "U1", "cells": {"C": "旧", "G": "9"}}]}
        out = hd.push_undo_cells(payload)
        assert out[0]["sheet_name"] == "N"
        assert out[0]["rows"][0]["account_id"] == "U1"
        assert out[0]["rows"][0]["cells"] == {"C": "旧", "G": "9"}


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

    def test_undo_half_configured_dashboard_returns_zero(self, client, fb_user, monkeypatch):
        """gg/fb 的「有表格ID、工作表名为空」半截配置 ⇒ 全零、不碰写入器。

        等价性哨兵：多表改造把前置判据从 `conf["sheet_name"]` 换成 `tables` 之后，
        gg/fb 的 `tables` 恒为单元素列表（工作表名可以为空）⇒ 少了
        `platform != "tt"` 那一支，这里会拿空表名去写表（改动前是直接返回全零）。
        """
        calls = []
        db = database.get_db()
        hd.save_undo(db, fb_user, "fb", "push",
                     {"spreadsheet_id": "S", "sheet_name": "N",
                      "cells": [{"account_id": "U9", "cells": {"C": "旧名"}}]})
        db.commit()
        db.close()
        monkeypatch.setattr(hd, "_open_db", lambda: database.get_db())
        monkeypatch.setattr(hd, "get_platform_config",
                            lambda db_, uid, p: {"spreadsheet_id": "S", "sheet_name": ""})
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


# ---------- Task 4: sync 方向（表 → 系统）的快照记录 ----------

_PAYLOAD_KEYS = {"updates", "owner_changes", "created", "created_statuses", "sheet_back"}


def _seed_user(db, username, display_name, platform="gg", role="huguan"):
    """造一个可被归属解析命中的用户（resolve_owner_id 认 display_name，回退 username）。"""
    db.execute("INSERT INTO users(username, password, role, display_name, platform) "
               "VALUES(?, 'x', ?, ?, ?)", (username, role, display_name, platform))
    return db.execute("SELECT last_insert_rowid() AS id").fetchone()["id"]


def _seed_gg_account(db, account_id, owner_id):
    db.execute("INSERT INTO accounts(account_id, name, owner_id, death_date) "
               "VALUES(?, ?, ?, '')", (account_id, account_id, owner_id))
    return db.execute("SELECT last_insert_rowid() AS id").fetchone()["id"]


def _seed_fb_account(db, account_id, owner_id, **over):
    cols = {"name": account_id, "account_id": account_id, "owner_id": owner_id}
    cols.update(over)
    keys = ", ".join(cols)
    marks = ", ".join("?" for _ in cols)
    db.execute(f"INSERT INTO fb_accounts({keys}) VALUES({marks})", tuple(cols.values()))
    return db.execute("SELECT last_insert_rowid() AS id").fetchone()["id"]


def _gg_row(account_id, owner_name="", owner_channel=""):
    """GG 一行原始值（A:N）。C=账户ID(2)、G=运营(6)、H=重新分配(7)。"""
    row = [""] * 14
    row[2], row[6], row[7] = account_id, owner_name, owner_channel
    return row


def _tt_row(account_id, owner_name=""):
    """TT 一行原始值（A:M）。C=账户ID(2)、G=接户运营(6)、L=换绑情况(11)。"""
    row = [""] * 13
    row[2], row[6] = account_id, owner_name
    return row


def _fb_row(account_id, acceptor="", owner_name=""):
    """FB 一行原始值（A:Q）。D=资产UID(3)、I=接户运营(8)、J=在用运营(9)。"""
    row = [""] * 17
    row[3], row[8], row[9] = account_id, acceptor, owner_name
    return row


def _sheet_from(parsed, platform):
    """路由（Task 5 的接线）要做的同一件事：按账户ID 把表侧原值映射好传给 apply_diff。

    表侧原值只有 `parse_row` 的结果里才有，而 `build_diff` 的返回值是干跑响应体
    （前端契约）—— 不许为了新功能给它加键。故由调用方算好、按 `account_id` 传入。
    """
    return {parsed["account_id"]: hd._owner_sheet_from(parsed, platform)}


class _ReadSpy(dict):
    """记账 dict：`.get` 每被调用一次就 +1（用来钉「默认档根本没读它」）。

    必须非空 —— 空 dict 在 `(sheet_from or {})` 里会被 `or` 短路成字面量 `{}`，
    那样即使代码真的读了也读不到本对象，探针就恒为 0（测不出东西）。
    """

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.gets = 0

    def get(self, *a, **kw):
        self.gets += 1
        return super().get(*a, **kw)


class TestSyncSnapshot:
    """`apply_diff(collect_undo=True)` 收集 sync 方向撤回快照（spec §5.2）。

    Task 5 的 `undo_sync` **逐键**消费这份 payload，故键集与每项的形状都是接口契约：
      {"updates":          [{"account_id", "cols": {列名: {"old", "new"}}}],
       "owner_changes":    [同 updates 项的形状 —— Task 5 用同一个 CAS 循环处理两者],
       "created":          [账户ID],
       "created_statuses": [{"name", "platform"}],
       "sheet_back":       [{"account_id", "cells": {列字母: 表里原值}}]}
    """

    def test_collect_undo_off_by_default(self, client, fb_user):
        """既有调用不带 collect_undo ⇒ 返回里没有 undo 键（纯增量）。"""
        db = database.get_db()
        diff = {"to_create": [], "to_update": [], "owner_changes": [],
                "to_skip": [], "warnings": [], "summary": {}}
        out = hd.apply_diff(db, diff, "fb", {}, fb_user)
        db.close()
        assert "undo" not in out

    def test_payload_has_all_five_keys(self, client, fb_user):
        """键集必须齐 —— Task 5 逐键消费，缺一个就静默漏掉一整类撤回。"""
        db = database.get_db()
        diff = {"to_create": [], "to_update": [], "owner_changes": [],
                "to_skip": [], "warnings": [], "summary": {}}
        out = hd.apply_diff(db, diff, "fb", {}, fb_user, collect_undo=True)
        db.close()
        assert set(out["undo"]) == _PAYLOAD_KEYS

    def test_unconfirmed_rows_are_not_recorded(self, client, fb_user):
        """没被 confirm 的行一个字都没写 ⇒ 不得进快照（否则撤回会去回滚没发生过的写）。"""
        db = database.get_db()
        pk = _seed_fb_account(db, "SY-NC", fb_user, unit_price="10")
        db.commit()
        diff = {"to_create": [], "to_skip": [], "warnings": [], "summary": {},
                "owner_changes": [],
                "to_update": [{"row": 2, "account_id": "SY-NC", "existing_id": pk,
                               "fields": {"unit_price": "99"}, "pending_status": None,
                               "scope_owner_id": fb_user, "clears": []}]}
        out = hd.apply_diff(db, diff, "fb", {}, fb_user, collect_undo=True)
        db.close()
        assert out["undo"]["updates"] == []

    # ---------- updates：列级旧值 + 新值 ----------

    def test_records_old_and_new_values_for_updates(self, client, fb_user):
        """列级旧值必须记下来，且要带上「本次写入的新值」（Task 5 的 CAS 靠它比对）。

        旧值读错时机（UPDATE 之后才读）会得到 "99" —— 断言会红，故本测试能证伪。
        """
        db = database.get_db()
        pk = _seed_fb_account(db, "SY1", fb_user, unit_price="10")
        db.commit()
        diff = {"to_create": [], "to_skip": [], "warnings": [], "summary": {},
                "owner_changes": [],
                "to_update": [{"row": 2, "account_id": "SY1", "existing_id": pk,
                               "fields": {"unit_price": "99"}, "pending_status": None,
                               "scope_owner_id": fb_user, "clears": []}]}
        out = hd.apply_diff(db, diff, "fb", {"update": ["SY1"]}, fb_user, collect_undo=True)
        db.commit()
        db.close()
        ups = out["undo"]["updates"]
        assert ups == [{"account_id": "SY1",
                        "cols": {"unit_price": {"old": "10", "new": "99"}}}]

    def test_records_every_changed_column(self, client, fb_user):
        """一行的多列变更都要进同一条 updates 项（不能只记第一列）。"""
        db = database.get_db()
        pk = _seed_fb_account(db, "SY2", fb_user, unit_price="10", remark="旧备注")
        db.commit()
        diff = {"to_create": [], "to_skip": [], "warnings": [], "summary": {},
                "owner_changes": [],
                "to_update": [{"row": 2, "account_id": "SY2", "existing_id": pk,
                               "fields": {"unit_price": "99", "remark": "新备注"},
                               "pending_status": None, "scope_owner_id": fb_user,
                               "clears": []}]}
        out = hd.apply_diff(db, diff, "fb", {"update": ["SY2"]}, fb_user, collect_undo=True)
        db.commit()
        db.close()
        cols = out["undo"]["updates"][0]["cols"]
        assert cols == {"unit_price": {"old": "10", "new": "99"},
                        "remark": {"old": "旧备注", "new": "新备注"}}

    # ---------- created ----------

    def test_records_created_ids(self, client, fb_user):
        db = database.get_db()
        diff = {"to_skip": [], "warnings": [], "summary": {}, "owner_changes": [],
                "to_update": [],
                "to_create": [{"row": 2, "account_id": "SY3", "owner_id": fb_user,
                               "owner_name": "", "db_values": {"_is_dead": False},
                               "pending_status": None}]}
        out = hd.apply_diff(db, diff, "fb", {"create": ["SY3"]}, fb_user, collect_undo=True)
        db.commit()
        db.close()
        assert out["undo"]["created"] == ["SY3"]

    # ---------- created_statuses：本次**真正新建**的状态行 ----------

    def test_created_status_recorded_via_to_create_branch(self, client, fb_user):
        db = database.get_db()
        diff = {"to_skip": [], "warnings": [], "summary": {}, "owner_changes": [],
                "to_update": [],
                "to_create": [{"row": 2, "account_id": "SY4", "owner_id": fb_user,
                               "owner_name": "", "db_values": {"_is_dead": False},
                               "pending_status": "待优化"}]}
        out = hd.apply_diff(db, diff, "fb", {"create": ["SY4"]}, fb_user, collect_undo=True)
        # 先确认真建了行（否则下面断言的是「记了一个并不存在的状态」）
        n = db.execute("SELECT COUNT(*) FROM account_statuses "
                       "WHERE name='待优化' AND platform='fb'").fetchone()[0]
        db.commit()
        db.close()
        assert n == 1
        assert out["undo"]["created_statuses"] == [{"name": "待优化", "platform": "fb"}]

    def test_created_status_recorded_via_to_update_branch(self, client, fb_user):
        """to_update 分支同样会建状态行 —— 两处调用点都要接上收集。"""
        db = database.get_db()
        pk = _seed_fb_account(db, "SY5", fb_user)
        db.commit()
        diff = {"to_create": [], "to_skip": [], "warnings": [], "summary": {},
                "owner_changes": [],
                "to_update": [{"row": 2, "account_id": "SY5", "existing_id": pk,
                               "fields": {}, "pending_status": "待优化",
                               "scope_owner_id": fb_user, "clears": []}]}
        out = hd.apply_diff(db, diff, "fb", {"update": ["SY5"]}, fb_user, collect_undo=True)
        db.commit()
        db.close()
        assert out["undo"]["created_statuses"] == [{"name": "待优化", "platform": "fb"}]

    def test_already_existing_status_is_not_recorded(self, client, fb_user):
        """系统里已有的状态**不是**本次新建 ⇒ 不进快照。

        否则 Task 5 会把它当成「本次新建」删掉 —— 而它可能有别的账户在用。
        （去掉 `existed is None` 判定，本测试即红。）
        """
        db = database.get_db()
        db.execute("INSERT INTO account_statuses(name, owner_id, platform) "
                   "VALUES('待优化', ?, 'fb')", (fb_user,))
        pk = _seed_fb_account(db, "SY6", fb_user)
        db.commit()
        diff = {"to_create": [], "to_skip": [], "warnings": [], "summary": {},
                "owner_changes": [],
                "to_update": [{"row": 2, "account_id": "SY6", "existing_id": pk,
                               "fields": {}, "pending_status": "待优化",
                               "scope_owner_id": fb_user, "clears": []}]}
        out = hd.apply_diff(db, diff, "fb", {"update": ["SY6"]}, fb_user, collect_undo=True)
        db.commit()
        db.close()
        assert out["undo"]["created_statuses"] == []

    # ---------- owner_changes：库侧归属旧值（走的是 owner_changes 分支，不是 to_update） ----------

    def test_owner_change_records_db_side_old_and_new(self, client, fb_user):
        """归属变更的库侧旧值必须在 owner_changes 分支里记 —— 否则撤回时库里的归属纹丝不动。

        `_collect_updates` 不产出 owner_id ⇒ 归属变更完全不经过 to_update。
        """
        db = database.get_db()
        new_owner = _seed_user(db, "u_sy_li", "李四", platform="fb")
        pk = _seed_fb_account(db, "SY7", fb_user, acceptor="旧接户记录")
        db.commit()
        parsed = dict(hd.parse_row(_fb_row("SY7", owner_name="李四"), "fb"), row=2)
        diff = hd.build_diff(db, [parsed], "fb")
        out = hd.apply_diff(db, diff, "fb", {"owner": ["SY7"]}, fb_user, collect_undo=True,
                            sheet_from=_sheet_from(parsed, "fb"))
        row = db.execute("SELECT owner_id, acceptor FROM fb_accounts WHERE id=?",
                         (pk,)).fetchone()
        db.commit()
        db.close()
        assert row["owner_id"] == new_owner            # 落库真的生效了
        assert out["undo"]["owner_changes"] == [{
            "account_id": "SY7",
            "cols": {"owner_id": {"old": fb_user, "new": new_owner},
                     # FB 独有的库侧写点：acceptor 被写成「{旧}转{新}」
                     "acceptor": {"old": "旧接户记录", "new": "u_undo转李四"}}}]

    def test_owner_change_on_non_fb_has_no_acceptor_key(self, client):
        """acceptor 只对 fb 记：别的平台的表没这一列，记了 Task 5 会拼出非法 UPDATE。"""
        db = database.get_db()
        u_zhang = _seed_user(db, "u_sy_zhang", "张三")
        u_li = _seed_user(db, "u_sy_li2", "李四")
        _seed_gg_account(db, "SY8", u_zhang)
        db.commit()
        parsed = dict(hd.parse_row(_gg_row("SY8", "张三", "李四"), "gg"), row=2)
        diff = hd.build_diff(db, [parsed], "gg")
        out = hd.apply_diff(db, diff, "gg", {"owner": ["SY8"]}, u_zhang, collect_undo=True,
                            sheet_from=_sheet_from(parsed, "gg"))
        db.commit()
        db.close()
        item = out["undo"]["owner_changes"][0]
        assert item["account_id"] == "SY8"
        assert set(item["cols"]) == {"owner_id"}
        assert item["cols"]["owner_id"] == {"old": u_zhang, "new": u_li}

    # ---------- sheet_back：落库后回写表的那几列的**原值** ----------

    def test_owner_sheet_from_covers_exactly_the_platform_columns(self, client):
        """表侧记哪几列**按平台分流**（规格 §3.3）：TT 没有通道列，FB 是 J + I。"""
        assert hd._owner_sheet_from(hd.parse_row(_gg_row("A", "张三", "李四"), "gg"),
                                    "gg") == {"G": "张三", "H": "李四"}
        assert hd._owner_sheet_from(hd.parse_row(_tt_row("A", "王五"), "tt"),
                                    "tt") == {"G": "王五"}
        assert hd._owner_sheet_from(hd.parse_row(_fb_row("A", "接户旧", "赵六"), "fb"),
                                    "fb") == {"J": "赵六", "I": "接户旧"}

    def test_sheet_back_records_sheet_original_values(self, client):
        """GG 侧：运营列 + 通道列两列的原值都要记（通道列同步后会被清空）。

        记的是**表里的真实原值**，不是「回退成旧归属名」—— 后者对通道列是错的。
        """
        db = database.get_db()
        u_zhang = _seed_user(db, "u_sb_zhang", "张三")
        u_li = _seed_user(db, "u_sb_li", "李四")
        _seed_gg_account(db, "SB-GG", u_zhang)
        db.commit()
        parsed = dict(hd.parse_row(_gg_row("SB-GG", "张三", "李四"), "gg"), row=2)
        diff = hd.build_diff(db, [parsed], "gg")
        out = hd.apply_diff(db, diff, "gg", {"owner": ["SB-GG"]}, u_zhang,
                            collect_undo=True, sheet_from=_sheet_from(parsed, "gg"))
        db.commit()
        db.close()
        assert out["undo"]["sheet_back"] == [
            {"account_id": "SB-GG", "cells": {"G": "张三", "H": "李四"}}]

    def test_sheet_back_on_fb_covers_in_use_and_acceptor_columns(self, client, fb_user):
        """FB 侧：J（在用运营）+ I（接户运营）两列的原值。"""
        db = database.get_db()
        _seed_user(db, "u_sb_li3", "李四", platform="fb")
        _seed_fb_account(db, "SB-FB", fb_user, acceptor="旧接户记录")
        db.commit()
        parsed = dict(hd.parse_row(_fb_row("SB-FB", "旧接户记录", "李四"), "fb"), row=2)
        diff = hd.build_diff(db, [parsed], "fb")
        out = hd.apply_diff(db, diff, "fb", {"owner": ["SB-FB"]}, fb_user,
                            collect_undo=True, sheet_from=_sheet_from(parsed, "fb"))
        db.commit()
        db.close()
        assert out["undo"]["sheet_back"] == [
            {"account_id": "SB-FB", "cells": {"J": "李四", "I": "旧接户记录"}}]

    def test_sheet_from_is_not_read_when_not_collecting(self, client, fb_user):
        """`collect_undo=False` 时新入参完全不被读取（纯增量：默认档一次都不碰它）。"""
        db = database.get_db()
        pk = _seed_fb_account(db, "SY9", fb_user)
        db.commit()
        spy = _ReadSpy({"SY9": {"J": "旧在用"}})
        diff = {"to_create": [], "to_update": [], "to_skip": [], "warnings": [],
                "summary": {},
                "owner_changes": [{"row": 2, "account_id": "SY9", "existing_id": pk,
                                   "from": "u_undo", "to": "u_undo",
                                   "to_owner_id": fb_user, "via": "owner_name"}]}
        out = hd.apply_diff(db, diff, "fb", {"owner": ["SY9"]}, fb_user, sheet_from=spy)
        db.close()
        assert "undo" not in out
        assert spy.gets == 0, "collect_undo=False 时不得读取 sheet_from"


class TestUndoStatusRoute:
    """GET /api/huguan/dashboard/undo：两方向各有无可撤快照 + 时间（spec §7 / §八）。"""

    def test_reports_both_directions_with_created_at(self, client):
        hg, uid = _huguan_headers(client, "_undo_status")
        db = database.get_db()
        hd.save_undo(db, uid, "fb", "push",
                     {"cells": [{"account_id": "A"}, {"account_id": "B"}]})
        # sync 的 count 口径 = 五类里「要撤的项」之和
        # （updates + owner_changes + created + created_statuses；sheet_back 是表侧原值、不算）
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

    def test_sync_count_includes_owner_changes(self, client):
        """只改归属的同步（updates/created 皆空）⇒ count 不能是 0。

        快照 payload 有五类内容；只数 updates+created 会让「纯归属变更」的同步
        按钮亮着却显示「影响 0 项」，与 `undo_sync` 的 `reverted` 口径对不上。
        去掉 owner_changes 的计数，本测试即红。
        """
        hg, uid = _huguan_headers(client, "_undo_status_oc")
        db = database.get_db()
        hd.save_undo(db, uid, "fb", "sync",
                     {"updates": [], "owner_changes": [{"account_id": "OC", "cols": {}}],
                      "created": [], "created_statuses": [], "sheet_back": []})
        db.commit()
        db.close()
        got = client.get("/api/huguan/dashboard/undo?platform=fb", headers=hg).get_json()
        assert got["sync"]["count"] == 1

    def test_sync_count_includes_created_statuses(self, client):
        """同理：本次新建的状态也是要撤的项，必须计入 count。"""
        hg, uid = _huguan_headers(client, "_undo_status_cs")
        db = database.get_db()
        hd.save_undo(db, uid, "fb", "sync",
                     {"updates": [], "owner_changes": [], "created": [],
                      "created_statuses": [{"name": "待优化", "platform": "fb"}],
                      "sheet_back": []})
        db.commit()
        db.close()
        got = client.get("/api/huguan/dashboard/undo?platform=fb", headers=hg).get_json()
        assert got["sync"]["count"] == 1

    def test_sync_count_excludes_sheet_back(self, client):
        """`sheet_back` 是表侧原值（要盖回去的旧值），不是「要撤的项」，不计入 count。"""
        hg, uid = _huguan_headers(client, "_undo_status_sb")
        db = database.get_db()
        hd.save_undo(db, uid, "fb", "sync",
                     {"updates": [], "owner_changes": [], "created": [],
                      "created_statuses": [],
                      "sheet_back": [{"account_id": "SB1", "cells": {"J": "旧"}}]})
        db.commit()
        db.close()
        got = client.get("/api/huguan/dashboard/undo?platform=fb", headers=hg).get_json()
        assert got["sync"]["count"] == 0

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


# ========== Task 5: sync 撤回的执行（先表后库 + 库侧 CAS + 新建对象判定） ==========

def _empty_sync_payload(**over):
    """一份「什么都没改」的 sync 快照，按需覆盖某几键（键集固定为契约的五键）。"""
    p = {"updates": [], "owner_changes": [], "created": [], "created_statuses": [],
         "sheet_back": []}
    p.update(over)
    return p


def _sync_env(monkeypatch, conf=None, calls=None, result=None):
    """undo_sync 的通用打桩。

    - `_open_db` 走到真库：`undo_sync` 会开三条连接（读快照 / 库事务 / 删快照），
      每次必须拿到**新**连接（`database.get_db()` 每次新建，不复用）
    - `conf` 缺省 = 未配置看板 ⇒ 表侧那步不做，专测库侧
    - 表侧写入换成记账 writer，返回的 calls 用来断言写了几列、定位列是哪个
    """
    monkeypatch.setattr(hd, "_open_db", lambda: database.get_db())
    monkeypatch.setattr(hd, "get_platform_config",
                        lambda db_, uid, p: conf or {"spreadsheet_id": "", "sheet_name": ""})
    calls = [] if calls is None else calls
    import google_sheets_service as gs
    monkeypatch.setattr(gs, "build_service", lambda path: object())
    monkeypatch.setattr(gs, "update_rows_by_account_id",
                        lambda svc, sid, name, rows, key_col="C":
                        calls.append({"sid": sid, "name": name, "rows": rows,
                                      "key_col": key_col})
                        or (result or {"updated": len(rows), "not_found": []}))
    return calls


class TestSyncUndoExec:
    """`undo_sync`：先表后库；库侧 CAS（updates + owner_changes）；新建对象判定。"""

    def test_cas_reverts_when_value_untouched(self, client, fb_user, monkeypatch):
        """当前值 == 本次写入的新值 ⇒ 写回旧值（spec §6.2 CAS 正例）。"""
        _sync_env(monkeypatch)
        db = database.get_db()
        pk = _seed_fb_account(db, "C1", fb_user, unit_price="99")
        hd.save_undo(db, fb_user, "fb", "sync", _empty_sync_payload(
            updates=[{"account_id": "C1",
                      "cols": {"unit_price": {"old": "10", "new": "99"}}}]))
        db.commit()
        db.close()
        out = hd.undo_sync(fb_user, "fb")
        db = database.get_db()
        got = db.execute("SELECT unit_price FROM fb_accounts WHERE id=?", (pk,)).fetchone()[0]
        db.close()
        assert got == "10"
        assert out["reverted"] == 1
        assert out["conflicts"] == []

    def test_cas_skips_when_value_changed(self, client, fb_user, monkeypatch):
        """当前值 != 本次写入的新值 ⇒ 跳过并报冲突（别人改过了），绝不覆盖。"""
        _sync_env(monkeypatch)
        db = database.get_db()
        pk = _seed_fb_account(db, "C2", fb_user, unit_price="77")
        hd.save_undo(db, fb_user, "fb", "sync", _empty_sync_payload(
            updates=[{"account_id": "C2",
                      "cols": {"unit_price": {"old": "10", "new": "99"}}}]))
        db.commit()
        db.close()
        out = hd.undo_sync(fb_user, "fb")
        db = database.get_db()
        got = db.execute("SELECT unit_price FROM fb_accounts WHERE id=?", (pk,)).fetchone()[0]
        db.close()
        assert got == "77"                       # 没被覆盖
        assert out["reverted"] == 0
        # 冲突要能定位到具体账户与原因（只断言计数会让「静默跳过」也变绿）
        assert out["conflicts"] == [{"account_id": "C2", "kind": "update",
                                     "reason": "同步后被改过"}]

    def test_created_deleted_when_untouched(self, client, fb_user, monkeypatch):
        """新建账户没人动过（updated_at == created_at）⇒ 删掉。"""
        _sync_env(monkeypatch)
        db = database.get_db()
        _seed_fb_account(db, "C3", fb_user)
        hd.save_undo(db, fb_user, "fb", "sync", _empty_sync_payload(created=["C3"]))
        db.commit()
        db.close()
        out = hd.undo_sync(fb_user, "fb")
        db = database.get_db()
        n = db.execute("SELECT COUNT(*) FROM fb_accounts WHERE account_id='C3'").fetchone()[0]
        db.close()
        assert n == 0
        assert out["reverted"] >= 1

    # ---------- 补齐 1：owner_changes 必须走同一段 CAS ----------

    def test_owner_change_cas_reverts_db_side(self, client, fb_user, monkeypatch):
        """归属变更的库侧回滚（含 FB 的 acceptor 写点）。

        计划示例只遍历 `payload["updates"]` ⇒ 归属变更纹丝不动，本测试即红。
        """
        _sync_env(monkeypatch)
        db = database.get_db()
        new_owner = _seed_user(db, "u_oc_li", "李四", platform="fb")
        pk = _seed_fb_account(db, "OC1", new_owner, acceptor="u_undo转李四")
        hd.save_undo(db, fb_user, "fb", "sync", _empty_sync_payload(
            owner_changes=[{"account_id": "OC1",
                            "cols": {"owner_id": {"old": fb_user, "new": new_owner},
                                     "acceptor": {"old": "旧接户记录",
                                                  "new": "u_undo转李四"}}}]))
        db.commit()
        db.close()
        out = hd.undo_sync(fb_user, "fb")
        db = database.get_db()
        row = db.execute("SELECT owner_id, acceptor FROM fb_accounts WHERE id=?",
                         (pk,)).fetchone()
        db.close()
        assert row["owner_id"] == fb_user
        assert row["acceptor"] == "旧接户记录"
        assert out["reverted"] == 1
        assert out["conflicts"] == []

    def test_owner_change_conflict_reports_owner_kind(self, client, fb_user, monkeypatch):
        """归属被同步之后又改过 ⇒ 保留现值 + 冲突（kind=owner，与字段冲突可区分）。"""
        _sync_env(monkeypatch)
        db = database.get_db()
        new_owner = _seed_user(db, "u_oc2_new", "李四", platform="fb")
        other = _seed_user(db, "u_oc2_other", "王五", platform="fb")
        pk = _seed_fb_account(db, "OC2", other)
        hd.save_undo(db, fb_user, "fb", "sync", _empty_sync_payload(
            owner_changes=[{"account_id": "OC2",
                            "cols": {"owner_id": {"old": fb_user, "new": new_owner}}}]))
        db.commit()
        db.close()
        out = hd.undo_sync(fb_user, "fb")
        db = database.get_db()
        got = db.execute("SELECT owner_id FROM fb_accounts WHERE id=?", (pk,)).fetchone()[0]
        db.close()
        assert got == other                       # 别人后来的改动没被覆盖
        assert out["reverted"] == 0
        assert out["conflicts"] == [{"account_id": "OC2", "kind": "owner",
                                     "reason": "同步后被改过"}]

    def test_same_account_reverts_field_and_owner_independently(self, client, fb_user,
                                                                monkeypatch):
        """同一账户同时有字段变更与归属变更 ⇒ 两条各自 CAS、各自回滚（不合并成一条）。"""
        _sync_env(monkeypatch)
        db = database.get_db()
        new_owner = _seed_user(db, "u_both_li", "李四", platform="fb")
        pk = _seed_fb_account(db, "BO1", new_owner, unit_price="99")
        hd.save_undo(db, fb_user, "fb", "sync", _empty_sync_payload(
            updates=[{"account_id": "BO1",
                      "cols": {"unit_price": {"old": "10", "new": "99"}}}],
            owner_changes=[{"account_id": "BO1",
                            "cols": {"owner_id": {"old": fb_user, "new": new_owner}}}]))
        db.commit()
        db.close()
        out = hd.undo_sync(fb_user, "fb")
        db = database.get_db()
        row = db.execute("SELECT owner_id, unit_price FROM fb_accounts WHERE id=?",
                         (pk,)).fetchone()
        db.close()
        assert (row["owner_id"], row["unit_price"]) == (fb_user, "10")
        assert out["reverted"] == 2

    # ---------- 第十条第 4 条：新建对象（三小项） ----------

    def test_created_modified_after_sync_is_kept(self, client, fb_user, monkeypatch):
        """建号后被别人改过（updated_at != created_at）⇒ 保留并报冲突，绝不删。"""
        _sync_env(monkeypatch)
        db = database.get_db()
        pk = _seed_fb_account(db, "CK1", fb_user)
        db.execute("UPDATE fb_accounts SET updated_at='2099-01-01 00:00:00' WHERE id=?",
                   (pk,))
        hd.save_undo(db, fb_user, "fb", "sync", _empty_sync_payload(created=["CK1"]))
        db.commit()
        db.close()
        out = hd.undo_sync(fb_user, "fb")
        db = database.get_db()
        n = db.execute("SELECT COUNT(*) FROM fb_accounts WHERE id=?", (pk,)).fetchone()[0]
        db.close()
        assert n == 1
        assert out["reverted"] == 0
        assert out["kept"] == [{"account_id": "CK1", "reason": "同步后被改过"}]

    def test_deleting_created_account_drops_history_rows(self, client, monkeypatch):
        """GG：新建账户被删时 account_mcc_history 随 CASCADE 一并消失（第十条第 4 条）。"""
        _sync_env(monkeypatch)
        _hg, uid = _huguan_headers(client, "_undo_delhist", platform="gg")
        db = database.get_db()
        pk = _seed_gg_account(db, "CD1", uid)
        db.execute("INSERT INTO account_mcc_history(account_id, changed_by) VALUES(?,?)",
                   (pk, uid))
        hd.save_undo(db, uid, "gg", "sync", _empty_sync_payload(created=["CD1"]))
        db.commit()
        db.close()
        out = hd.undo_sync(uid, "gg")
        db = database.get_db()
        acc_n = db.execute("SELECT COUNT(*) FROM accounts WHERE id=?", (pk,)).fetchone()[0]
        hist_n = db.execute("SELECT COUNT(*) FROM account_mcc_history WHERE account_id=?",
                            (pk,)).fetchone()[0]
        db.close()
        assert (acc_n, hist_n) == (0, 0)
        assert out["reverted"] == 1

    def test_deleting_created_fb_account_clears_bm_history_first(self, client, fb_user,
                                                                 monkeypatch):
        """FB 特有（第十条第 8 条）：`fb_account_bm_history` 没有 ON DELETE CASCADE ⇒
        必须先显式清掉，否则 foreign_keys=ON 用外键把删除挡下来（本测试会报错）。
        """
        _sync_env(monkeypatch)
        db = database.get_db()
        pk = _seed_fb_account(db, "BF1", fb_user)
        db.execute("INSERT INTO fb_account_bm_history(account_id, changed_by) VALUES(?,?)",
                   (pk, fb_user))
        hd.save_undo(db, fb_user, "fb", "sync", _empty_sync_payload(created=["BF1"]))
        db.commit()
        db.close()
        out = hd.undo_sync(fb_user, "fb")
        db = database.get_db()
        acc_n = db.execute("SELECT COUNT(*) FROM fb_accounts WHERE id=?", (pk,)).fetchone()[0]
        hist_n = db.execute("SELECT COUNT(*) FROM fb_account_bm_history WHERE account_id=?",
                            (pk,)).fetchone()[0]
        db.close()
        assert (acc_n, hist_n) == (0, 0)
        assert out["reverted"] == 1

    # ---------- 补齐 2：created_statuses 的回滚 ----------

    def test_created_status_deleted_when_unreferenced(self, client, fb_user, monkeypatch):
        _sync_env(monkeypatch)
        db = database.get_db()
        db.execute("INSERT INTO account_statuses(name, owner_id, platform) "
                   "VALUES('待优化', ?, 'fb')", (fb_user,))
        sid = db.execute("SELECT last_insert_rowid()").fetchone()[0]
        hd.save_undo(db, fb_user, "fb", "sync", _empty_sync_payload(
            created_statuses=[{"name": "待优化", "platform": "fb"}]))
        db.commit()
        db.close()
        out = hd.undo_sync(fb_user, "fb")
        db = database.get_db()
        n = db.execute("SELECT COUNT(*) FROM account_statuses WHERE id=?", (sid,)).fetchone()[0]
        db.close()
        assert n == 0
        assert out["reverted"] == 1
        assert out["conflicts"] == []

    def test_created_status_kept_when_referenced(self, client, fb_user, monkeypatch):
        """有引用 ⇒ 保留并报冲突。去掉引用检查（无条件删）本测试即红。"""
        _sync_env(monkeypatch)
        db = database.get_db()
        db.execute("INSERT INTO account_statuses(name, owner_id, platform) "
                   "VALUES('待优化', ?, 'fb')", (fb_user,))
        sid = db.execute("SELECT last_insert_rowid()").fetchone()[0]
        pk = _seed_fb_account(db, "ST1", fb_user)
        db.execute("UPDATE fb_accounts SET status_id=? WHERE id=?", (sid, pk))
        hd.save_undo(db, fb_user, "fb", "sync", _empty_sync_payload(
            created_statuses=[{"name": "待优化", "platform": "fb"}]))
        db.commit()
        db.close()
        out = hd.undo_sync(fb_user, "fb")
        db = database.get_db()
        n = db.execute("SELECT COUNT(*) FROM account_statuses WHERE id=?", (sid,)).fetchone()[0]
        db.close()
        assert n == 1
        assert out["reverted"] == 0
        assert out["conflicts"] == [{"name": "待优化", "platform": "fb", "kind": "status",
                                     "reason": "状态仍被 1 个账户引用"}]

    def test_status_reference_check_covers_all_three_tables(self, client, fb_user, monkeypatch):
        """引用检查必须扫**三张表**：`tt_accounts` 引用了本次新建的 fb 状态，同样不许删。

        只查快照那个 platform 对应的表（fb_accounts）就会漏判，删出一条悬空 status_id。

        探针刻意用 `tt_accounts` 而不是 `accounts`：`_migrate_account_status_platform`
        （database.py:1390，**每次 get_db() 都跑**）会把「GG 账户挂在非 gg 状态行上」
        的引用挪回 gg 同名行，中途就把 `accounts` 里的探针引走，测不出东西。
        `tt_accounts` / `fb_accounts` 不受那条迁移影响。
        """
        _sync_env(monkeypatch)
        db = database.get_db()
        db.execute("INSERT INTO account_statuses(name, owner_id, platform) "
                   "VALUES('跨平台', ?, 'fb')", (fb_user,))
        sid = db.execute("SELECT last_insert_rowid()").fetchone()[0]
        # 引用来自 **tt_accounts** —— 不是快照 platform 对应的 fb_accounts
        db.execute("INSERT INTO tt_accounts(advertiser_id, name, owner_id, status_id) "
                   "VALUES('TTREF', 'TTREF', ?, ?)", (fb_user, sid))
        hd.save_undo(db, fb_user, "fb", "sync", _empty_sync_payload(
            created_statuses=[{"name": "跨平台", "platform": "fb"}]))
        db.commit()
        db.close()
        out = hd.undo_sync(fb_user, "fb")
        db = database.get_db()
        n = db.execute("SELECT COUNT(*) FROM account_statuses WHERE id=?", (sid,)).fetchone()[0]
        db.close()
        assert n == 1
        assert out["conflicts"] == [{"name": "跨平台", "platform": "fb", "kind": "status",
                                     "reason": "状态仍被 1 个账户引用"}]

    # ---------- 表侧回退：按平台分流列 + 显式传定位列（第十条第 7 条） ----------

    @pytest.mark.parametrize("platform,key_col,cells", [
        ("gg", "C", {"G": "张三", "H": "李四"}),      # 运营列 + 通道列
        ("tt", "C", {"G": "王五"}),                   # 只有接户运营列，无通道列
        ("fb", "D", {"J": "赵六", "I": "接户旧"}),    # 在用运营列 + 接户运营列
    ])
    def test_sheet_back_uses_platform_columns_and_key_col(
            self, client, fb_user, monkeypatch, platform, key_col, cells):
        """三平台分流 + **显式传该平台的定位列**。

        不传 key_col ⇒ FB（账户ID 在 D 列）按默认 "C"（账户名称）定位，整批静默写空。
        """
        calls = _sync_env(monkeypatch, conf={"spreadsheet_id": "SID", "sheet_name": "N"})
        db = database.get_db()
        hd.save_undo(db, fb_user, platform, "sync", _empty_sync_payload(
            sheet_back=[{"account_id": "SB1", "cells": cells}]))
        db.commit()
        db.close()
        hd.undo_sync(fb_user, platform)
        assert calls[0]["sid"] == "SID"
        assert calls[0]["key_col"] == key_col
        assert calls[0]["rows"] == [{"account_id": "SB1", "cells": cells}]

    def test_sheet_back_empty_cells_skips_table_write(self, client, fb_user, monkeypatch):
        """没有可回退的表侧内容（cells 空）⇒ 一个字都不写表。"""
        calls = _sync_env(monkeypatch, conf={"spreadsheet_id": "SID", "sheet_name": "N"})
        db = database.get_db()
        hd.save_undo(db, fb_user, "fb", "sync", _empty_sync_payload(
            sheet_back=[{"account_id": "SB0", "cells": {}}]))
        db.commit()
        db.close()
        hd.undo_sync(fb_user, "fb")
        assert calls == []

    def test_table_not_found_is_reported(self, client, fb_user, monkeypatch):
        """表里找不到的行进 not_found 报告，不算错误（spec §6.1 同口径）。"""
        _sync_env(monkeypatch, conf={"spreadsheet_id": "SID", "sheet_name": "N"},
                  result={"updated": 0, "not_found": ["NF1"]})
        db = database.get_db()
        hd.save_undo(db, fb_user, "fb", "sync", _empty_sync_payload(
            sheet_back=[{"account_id": "NF1", "cells": {"J": "x"}}]))
        db.commit()
        db.close()
        out = hd.undo_sync(fb_user, "fb")
        assert out["not_found"] == ["NF1"]

    # ---------- 顺序铁律（第十条第 5 条）与快照生命周期 ----------

    def test_db_step_failure_keeps_table_reverted_and_snapshot(self, client, fb_user,
                                                               monkeypatch):
        """库那步失败时：表**已经**回退（顺序对），库事务整体回滚，快照留着可重试。

        库那步的失败用「old 指向不存在的用户」造出来：CAS 通过后 UPDATE 撞
        `owner_id REFERENCES users(id)`。
        """
        calls = _sync_env(monkeypatch, conf={"spreadsheet_id": "SID", "sheet_name": "N"})
        db = database.get_db()
        pk = _seed_fb_account(db, "OR1", fb_user)
        hd.save_undo(db, fb_user, "fb", "sync", _empty_sync_payload(
            owner_changes=[{"account_id": "OR1",
                            "cols": {"owner_id": {"old": 999999, "new": fb_user}}}],
            sheet_back=[{"account_id": "OR1", "cells": {"J": "三", "I": "旧"}}]))
        db.commit()
        db.close()
        with pytest.raises(sqlite3.IntegrityError):
            hd.undo_sync(fb_user, "fb")
        assert calls and calls[0]["rows"][0]["cells"] == {"J": "三", "I": "旧"}
        db = database.get_db()
        got = db.execute("SELECT owner_id FROM fb_accounts WHERE id=?", (pk,)).fetchone()[0]
        payload = hd.load_undo(db, fb_user, "fb", "sync")
        db.close()
        assert got == fb_user, "库那步失败 ⇒ 事务回滚，归属没被改"
        assert payload is not None, "库那步失败 ⇒ 快照不能被删（要能重试）"

    def test_table_step_failure_leaves_db_untouched(self, client, monkeypatch):
        """顺序铁律的语义侧面：表那步失败 ⇒ 库一个字没动、快照还在。

        反了（先库后表）就会在表失败后留下「库里已回旧归属、表里还是新归属」，
        下次同步立刻判定出归属变更、把撤回重做一遍（spec §6.2 的推演）。
        """
        monkeypatch.setattr(hd, "_open_db", lambda: database.get_db())
        monkeypatch.setattr(hd, "get_platform_config",
                            lambda db_, uid, p: {"spreadsheet_id": "SID",
                                                 "sheet_name": "N"})
        import google_sheets_service as gs
        monkeypatch.setattr(gs, "build_service", lambda path: object())
        wrote = []

        def _boom(svc, sid, name, rows, key_col="C"):
            wrote.append(rows)
            raise RuntimeError("表炸了")

        monkeypatch.setattr(gs, "update_rows_by_account_id", _boom)

        _hg, uid = _huguan_headers(client, "_undo_tfail", platform="gg")
        db = database.get_db()
        u_zhang = _seed_user(db, "u_tf_zhang", "张三")
        u_li = _seed_user(db, "u_tf_li", "李四")
        pk = _seed_gg_account(db, "TF1", u_li)          # 同步已把归属改成李四
        hd.save_undo(db, uid, "gg", "sync", _empty_sync_payload(
            owner_changes=[{"account_id": "TF1",
                            "cols": {"owner_id": {"old": u_zhang, "new": u_li}}}],
            sheet_back=[{"account_id": "TF1", "cells": {"G": "张三", "H": "李四"}}]))
        db.commit()
        db.close()

        with pytest.raises(RuntimeError):
            hd.undo_sync(uid, "gg")
        assert wrote, "表那步必须先被调用"

        db = database.get_db()
        got = db.execute("SELECT owner_id FROM accounts WHERE id=?", (pk,)).fetchone()[0]
        payload = hd.load_undo(db, uid, "gg", "sync")
        # 下次同步：表还是同步之后的样子（G=李四、通道列已清空），库也是李四
        parsed = dict(hd.parse_row(_gg_row("TF1", "李四", ""), "gg"), row=2)
        diff = hd.build_diff(db, [parsed], "gg")
        db.close()
        assert got == u_li, "表那步失败时库绝不能已经回退"
        assert payload is not None, "表那步失败时快照必须留着可重试"
        assert [o for o in diff["owner_changes"] if o["account_id"] == "TF1"] == [], \
            "回退失败后不得让下次同步重做那次归属变更"

    def test_snapshot_column_missing_from_schema_reports_conflict(self, client, fb_user,
                                                                 monkeypatch):
        """快照里的列在当前 schema 已不存在 ⇒ 报冲突，**不是**把整次撤回炸掉。

        去掉那个 `col not in keys` 守卫，`row[col]` 会 IndexError 把整批撤回带崩。
        """
        _sync_env(monkeypatch)
        db = database.get_db()
        _seed_fb_account(db, "MC1", fb_user)
        hd.save_undo(db, fb_user, "fb", "sync", _empty_sync_payload(
            updates=[{"account_id": "MC1",
                      "cols": {"no_such_col": {"old": "a", "new": "b"}}}]))
        db.commit()
        db.close()
        out = hd.undo_sync(fb_user, "fb")
        assert out["reverted"] == 0
        assert out["conflicts"] == [{"account_id": "MC1", "kind": "update",
                                     "reason": "库中无列 no_such_col，未撤回"}]

    def test_snapshot_deleted_after_successful_undo(self, client, fb_user, monkeypatch):
        _sync_env(monkeypatch)
        db = database.get_db()
        hd.save_undo(db, fb_user, "fb", "sync", _empty_sync_payload())
        db.commit()
        db.close()
        hd.undo_sync(fb_user, "fb")
        db = database.get_db()
        assert hd.load_undo(db, fb_user, "fb", "sync") is None
        db.close()

    def test_no_snapshot_returns_full_key_set(self, client, fb_user, monkeypatch):
        """没有快照 ⇒ 全零，键集与成功路径一致，且一个字都不写表。"""
        calls = _sync_env(monkeypatch, conf={"spreadsheet_id": "SID", "sheet_name": "N"})
        out = hd.undo_sync(fb_user, "fb")
        assert out == {"reverted": 0, "conflicts": [], "kept": [], "not_found": []}
        assert calls == []

    def test_does_not_touch_other_users_snapshot(self, client, fb_user, monkeypatch):
        """只撤自己的：另一个户管的快照取不到、也删不掉。"""
        _sync_env(monkeypatch)
        other_payload = _empty_sync_payload(created=["X1"])
        db = database.get_db()
        db.execute("INSERT INTO users(username, password, role, platform) "
                   "VALUES('u_undo_other_sync', 'x', 'huguan', 'fb')")
        other = db.execute("SELECT last_insert_rowid()").fetchone()[0]
        hd.save_undo(db, other, "fb", "sync", other_payload)
        db.commit()
        db.close()
        out = hd.undo_sync(fb_user, "fb")
        db = database.get_db()
        still = hd.load_undo(db, other, "fb", "sync")
        db.close()
        assert out["reverted"] == 0
        assert still == other_payload

    def test_writeback_rows_does_not_write_undo_snapshot(self, client, fb_user, monkeypatch):
        """第十条第 9 条：自动回写（writeback_rows → push_rows）绝不碰 huguan_sync_undo。

        自动回写是「编辑某个账户」的副作用，单独撤它只会让表和库当场不一致（spec §二.4）。
        """
        import main
        import google_sheets_service as gs
        db = database.get_db()
        hd.save_config(db, fb_user, "fb", "SID", "Sheet1")
        hd.save_undo(db, fb_user, "fb", "push",
                     {"cells": [{"account_id": "KEEP", "cells": {}}]})
        db.commit()
        db.close()
        monkeypatch.setattr(gs, "build_service", lambda p: object())
        monkeypatch.setattr(gs, "update_rows_by_account_id",
                            lambda *a, **k: {"updated": 0, "not_found": []})
        monkeypatch.setattr(main, "_sync_sheets_background", lambda fn, cb: fn())
        hd.writeback_rows(fb_user, "fb")
        db = database.get_db()
        push_payload = hd.load_undo(db, fb_user, "fb", "push")
        sync_payload = hd.load_undo(db, fb_user, "fb", "sync")
        db.close()
        assert push_payload == {"cells": [{"account_id": "KEEP", "cells": {}}]}
        assert sync_payload is None


class TestUndoApplyRoute:
    """`POST /api/huguan/dashboard/undo`：两个方向都接上，uid 只从 JWT 取（spec §7）。"""

    def test_push_direction_calls_undo_push(self, client, monkeypatch):
        hg, uid = _huguan_headers(client, "_undo_post_push")
        called = []
        monkeypatch.setattr(hd, "undo_push",
                            lambda u, p: called.append(("push", u, p))
                            or {"updated": 3, "not_found": []})
        monkeypatch.setattr(hd, "undo_sync",
                            lambda u, p: called.append(("sync", u, p)) or {})
        resp = client.post("/api/huguan/dashboard/undo",
                           json={"platform": "fb", "direction": "push"}, headers=hg)
        assert resp.status_code == 200
        assert called == [("push", uid, "fb")]
        assert resp.get_json()["updated"] == 3

    def test_sync_direction_calls_undo_sync(self, client, monkeypatch):
        hg, uid = _huguan_headers(client, "_undo_post_sync")
        called = []
        monkeypatch.setattr(hd, "undo_sync",
                            lambda u, p: called.append((u, p))
                            or {"reverted": 1, "conflicts": [], "kept": [],
                                "not_found": []})
        resp = client.post("/api/huguan/dashboard/undo",
                           json={"platform": "fb", "direction": "sync"}, headers=hg)
        assert resp.status_code == 200
        assert called == [(uid, "fb")]
        assert resp.get_json()["reverted"] == 1

    def test_body_uid_is_ignored(self, client, monkeypatch):
        """请求体带 uid 也不接受：一律按 JWT 里的 uid 撤（spec §7）。"""
        hg, uid = _huguan_headers(client, "_undo_post_uid")
        seen = []
        monkeypatch.setattr(hd, "undo_push",
                            lambda u, p: seen.append(u)
                            or {"updated": 0, "not_found": []})
        resp = client.post("/api/huguan/dashboard/undo",
                           json={"platform": "fb", "direction": "push", "uid": 999999},
                           headers=hg)
        assert resp.status_code == 200
        assert seen == [uid]

    def test_bad_platform_400(self, client):
        hg, _ = _huguan_headers(client, "_undo_post_badp")
        assert client.post("/api/huguan/dashboard/undo",
                           json={"platform": "xx", "direction": "push"},
                           headers=hg).status_code == 400

    def test_bad_direction_400(self, client):
        hg, _ = _huguan_headers(client, "_undo_post_badd")
        assert client.post("/api/huguan/dashboard/undo",
                           json={"platform": "fb", "direction": "redo"},
                           headers=hg).status_code == 400

    def test_missing_direction_400(self, client):
        hg, _ = _huguan_headers(client, "_undo_post_nodir")
        assert client.post("/api/huguan/dashboard/undo",
                           json={"platform": "fb"}, headers=hg).status_code == 400

    def test_non_json_body_400(self, client):
        hg, _ = _huguan_headers(client, "_undo_post_badbody")
        assert client.post("/api/huguan/dashboard/undo", data="not json",
                           headers=hg).status_code == 400

    def test_non_huguan_403(self, client):
        h, _ = _make_user(client, "_undo_post_user", role="user")
        assert client.post("/api/huguan/dashboard/undo",
                           json={"platform": "gg", "direction": "push"},
                           headers=h).status_code == 403

    def test_requires_jwt(self, client):
        assert client.post("/api/huguan/dashboard/undo",
                           json={"platform": "gg", "direction": "push"}
                           ).status_code in (401, 422)

    def test_execution_failure_returns_500_with_message(self, client, monkeypatch, caplog):
        """执行侧有意不吞异常 ⇒ 路由层转成 500 + **固定**中文文案（不许静默吞掉）。

        响应体绝不内插原始异常文本：可能含文件路径 / SQL 片段等内部信息。异常详情
        只落日志 —— 这里用 caplog 钉住「排查线索仍在日志里」。把 `e` 内插回响应即红。
        """
        hg, _ = _huguan_headers(client, "_undo_post_500")

        def _boom(u, p):
            raise RuntimeError("表炸了")

        monkeypatch.setattr(hd, "undo_push", _boom)
        with caplog.at_level(logging.ERROR, logger="gg-server"):
            resp = client.post("/api/huguan/dashboard/undo",
                               json={"platform": "fb", "direction": "push"}, headers=hg)
        assert resp.status_code == 500
        body = resp.get_json()
        assert body["success"] is False
        assert body["error"] == "撤回失败，请重试"
        assert "表炸了" not in body["error"]
        # 异常详情不得丢：仍在日志里（排查能力不因脱敏而降级）
        assert "表炸了" in caplog.text


class TestSyncRouteSnapshotWiring:
    """`dashboard_sync` 路由：apply_diff 带 collect_undo + sheet_from，快照按成败落库/作废。

    这是 Task 4 明确留给本任务的接线（spec §5.3）。
    """

    def _wire_sync(self, client, monkeypatch, username, grid):
        """把 sync 路由的 Sheets I/O 全打桩（读表返回 grid、后台回写不跑）。"""
        import main
        import google_sheets_service as gs
        monkeypatch.setattr(gs, "build_service", lambda p: object())
        monkeypatch.setattr(gs, "read_sheet_values", lambda svc, sid, name, rng: grid)
        monkeypatch.setattr(main, "_sync_sheets_background", lambda fn, cb: None)
        hg, uid = _huguan_headers(client, username, platform="gg")
        db = database.get_db()
        hd.save_config(db, uid, "gg", "SID", "Sheet1")
        db.commit()
        db.close()
        return hg, uid

    def test_route_stores_snapshot_with_sheet_back(self, client, monkeypatch):
        """`sheet_from` 必须真的传进去：不传 ⇒ sheet_back 全空、表侧撤回静默失效。"""
        hg, uid = self._wire_sync(client, monkeypatch, "_undo_wire_ok",
                                  [[""] * 14, _gg_row("WR1", "张三", "李四")])
        db = database.get_db()
        _seed_user(db, "u_wire_zhang", "张三")
        _seed_user(db, "u_wire_li", "李四")
        _seed_gg_account(db, "WR1", db.execute(
            "SELECT id FROM users WHERE display_name='张三'").fetchone()["id"])
        db.commit()
        db.close()
        resp = client.post("/api/huguan/dashboard/sync",
                           json={"platform": "gg", "dry_run": False,
                                 "confirmed": {"owner": ["WR1"]}},
                           headers=hg)
        assert resp.status_code == 200
        db = database.get_db()
        payload = hd.load_undo(db, uid, "gg", "sync")
        db.close()
        assert payload["sheet_back"] == [{"account_id": "WR1",
                                          "cells": {"G": "张三", "H": "李四"}}]
        assert payload["owner_changes"][0]["account_id"] == "WR1"
        # 快照是内部凭据，不随响应体发给前端
        assert "undo" not in resp.get_json()["result"]

    def test_route_discards_snapshot_when_apply_diff_raises(self, client, monkeypatch):
        """apply_diff 抛异常 ⇒ 作废快照（部分落库的库状态无法用残缺快照安全反向）。"""
        hg, uid = self._wire_sync(client, monkeypatch, "_undo_wire_fail",
                                  [[""] * 14, _gg_row("WR2", "张三", "")])
        db = database.get_db()
        hd.save_undo(db, uid, "gg", "sync",
                     _empty_sync_payload(updates=[{"account_id": "OLD"}]))
        db.commit()
        db.close()

        def _boom(*a, **k):
            raise RuntimeError("库炸了")

        monkeypatch.setattr(hd, "apply_diff", _boom)
        with pytest.raises(RuntimeError):
            client.post("/api/huguan/dashboard/sync",
                        json={"platform": "gg", "dry_run": False,
                              "confirmed": {"create": ["WR2"]}}, headers=hg)
        db = database.get_db()
        assert hd.load_undo(db, uid, "gg", "sync") is None
        db.close()


# ---------- Task 6: 删用户时的快照清理 ----------


class TestDeleteUserCleanup:
    """`huguan_sync_undo.user_id REFERENCES users(id)` 且无 ON DELETE，连接又开着
    `PRAGMA foreign_keys=ON` ⇒ 不清理的话，**删任何用过看板的户管都会
    `FOREIGN KEY constraint failed`（500）**。spec §八 / 计划 Task 6。
    """

    def test_deleting_user_via_endpoint_succeeds_with_undo_row_present(self, client, fb_user):
        """**驱动真实删用户端点**：户管有快照时删他，不能以 FOREIGN KEY constraint
        failed 收场。

        ⚠️ 这条**不能**自己 DELETE 再断言行没了 —— 那是自证式空转，测不到
        `admin_delete_user`。必须在删之前留下快照，然后走真实删用户路径，断言它
        成功且快照也没了。

        `developer` 身份发起（删用户需要 admin/developer；developer 不受
        `_check_modify_user` 的同级保护拦截）。目标户管的 role 先改成 'user'：
        `admin_delete_user` 对 developer 目标直接 400，用 'user' 让本测试只测
        「快照清理」这一件事。
        """
        db = database.get_db()
        hd.save_undo(db, fb_user, "fb", "push", {"v": 1})
        db.commit()
        # 目标用户不能是 developer/admin，否则会被同级保护 / 400 拦掉
        db.execute("UPDATE users SET role='user' WHERE id=?", (fb_user,))
        db.commit()
        db.close()

        # ⚠️ 偏离 brief：brief 用 `INSERT INTO users(...password='test123')` 造 developer，
        # 但 `login_user` 走 `check_password_hash`，明文密码必然 401（KeyError:
        # 'access_token'）。改用仓内既定写法 `_make_user`（register 落哈希 + UPDATE
        # 改角色），断言与意图不变。
        dev_headers, _dev_id = _make_user(client, "_undo_del_dev", role="developer")

        r = client.delete(f"/api/admin/users/{fb_user}", headers=dev_headers)
        assert r.status_code == 200, r.get_json()

        db = database.get_db()
        n = db.execute("SELECT COUNT(*) FROM huguan_sync_undo WHERE user_id=?",
                       (fb_user,)).fetchone()[0]
        db.close()
        assert n == 0

    def test_undo_table_is_in_delete_user_cleanup_list(self):
        """静态守卫：`admin_delete_user` 的代码里必须出现 `huguan_sync_undo`。

        上面那条是端到端行为（更强），这条是**直指根因**的守卫 —— 将来有人重构删
        用户逻辑、把清理行弄丢了，这条会立刻红并说清原因。
        """
        import inspect
        import main
        src = inspect.getsource(main.admin_delete_user)
        assert "huguan_sync_undo" in src, \
            "admin_delete_user 未清理 huguan_sync_undo —— 删任何用过看板的户管都会 FOREIGN KEY 500"


# ========== 规格 §十「回归保障」补齐：push 快照的作废与 not_found 透传 ==========
#
# 规格 §十 第 1 条「表写下失败则不留快照」与第 2 条「表里已删的行进 not_found」
# 此前无测试覆盖（生产代码已实现，只是没被测试打过 —— 这正是最危险的形态）。
# 三条都**驱动真实入口**：前两条走真实端点 `POST /api/huguan/dashboard/push`，
# 第三条调真实 `hd.undo_push`。


def _push_env(client, monkeypatch, username, platform="gg", account_id="WF1", write=None):
    """把一个户管的 `/push` 端点环境整好，返回 (headers, uid)。

    - 已配好看板 + 一个会进 `collect_rows_for_push` 的账户；
    - `read_sheet_values`（快照读表）返回一张能命中该账户的表 ⇒ 本次 push 会先写下
      一份**非空**快照（这样「被作废」与「本来就没有」不再同形，见各用例）；
    - `update_rows_by_account_id` 换成 `write`（不传则不打桩，由用例自己打）。
    """
    import google_sheets_service as gs
    hg, uid = _huguan_headers(client, username, platform=platform)
    db = database.get_db()
    hd.save_config(db, uid, platform, "SS", "Sheet1")
    if platform == "fb":
        _seed_fb_account(db, account_id, uid)
        grid = [[""] * 17, _fb_row(account_id, owner_name="运营")]
    else:
        _seed_gg_account(db, account_id, uid)
        grid = [[""] * 14, _gg_row(account_id, "运营", "")]
    db.commit()
    db.close()

    monkeypatch.setattr(hd, "read_sheet_values", lambda *a, **k: grid)
    monkeypatch.setattr(gs, "build_service", lambda path: object())
    if write is not None:
        monkeypatch.setattr(gs, "update_rows_by_account_id", write)
    return hg, uid


def _seed_stale_push_snapshot(uid, platform="gg"):
    """预置一份「上一次成功同步」留下的快照（哨兵值）。"""
    db = database.get_db()
    hd.save_undo(db, uid, platform, "push",
                 {"spreadsheet_id": "SS", "sheet_name": "Sheet1",
                  "cells": [{"account_id": "STALE", "cells": {"C": "上次的原值"}}]})
    db.commit()
    db.close()


class TestPushRouteSnapshotLifecycle:
    """规格 §5.3 / §十 第 1 条：`/push` 写表失败或空写 ⇒ 快照必须被作废。

    驱动真实端点 —— 不作废时 `load_undo` 会读到本次 push 写下的新快照，故断言
    「读不到快照了」对两条路径都有判别力（不是「本来就没有」）。
    """

    def test_write_failure_discards_snapshot(self, client, monkeypatch):
        """写表**抛异常**（不是读表）⇒ 端点失败，且快照被作废。

        判别力：注释掉 `dashboard_push` except 分支里的 `_discard_push_undo(...)`，
        快照留存（`load_undo` 读到新一份快照），本用例即红。

        异常如何露出：conftest 以 TESTING=True 起 app，未捕获异常**直接抛给
        `client.post` 调用者**（与既有 `TestPushSnapshotReadFailure` 同口径），
        生产环境里则是 Flask 的泛化 500。
        """
        def _boom(svc, sid, name, rows, key_col="C"):
            raise RuntimeError("写表炸了")

        hg, uid = _push_env(client, monkeypatch, "_push_wfail", write=_boom)
        _seed_stale_push_snapshot(uid)

        with pytest.raises(RuntimeError, match="写表炸了"):
            client.post("/api/huguan/dashboard/push", headers=hg, json={"platform": "gg"})

        db = database.get_db()
        got = hd.load_undo(db, uid, "gg", "push")
        db.close()
        assert got is None, "写表失败 ⇒ 快照必须被作废（表没变，撤回没有意义）"

    def test_empty_write_discards_snapshot(self, client, monkeypatch):
        """一个字都没写（`updated==0` 且 `not_found` 为空）⇒ 快照作废。

        判别力：注释掉 `dashboard_push` 里
        `if not res["updated"] and not res["not_found"]:` 那段作废，本用例即红。
        """
        wrote = []

        def _empty(svc, sid, name, rows, key_col="C"):
            wrote.append(rows)
            return {"updated": 0, "not_found": []}

        hg, uid = _push_env(client, monkeypatch, "_push_empty", write=_empty)
        _seed_stale_push_snapshot(uid)

        resp = client.post("/api/huguan/dashboard/push", headers=hg, json={"platform": "gg"})
        assert resp.status_code == 200
        assert wrote, "对照：写入器必须被调用过，否则下面的断言是空集上的恒真式"
        result = resp.get_json()["result"]
        assert result["updated"] == 0
        assert result["not_found"] == []

        db = database.get_db()
        got = hd.load_undo(db, uid, "gg", "push")
        db.close()
        assert got is None, "空写 ⇒ 没有可撤回的东西，快照必须被作废"

    def test_partial_write_failure_keeps_snapshot(self, client, monkeypatch):
        """多表下「表 1 写成功、表 2 抛异常」⇒ 快照必须**保留**（审查修复轮 1 · Finding 2）。

        判别力：改前 `except` 分支无条件 `_discard_push_undo(...)` ⇒ 表 1 已被改、它的
        撤回入口却被**永久丢掉**（按钮消失，户管再也退不回去）。本用例会红。
        单表下「一个字都没写」时仍作废（spec §十 第 1 条，见上面两条用例）—— 此处
        表 1 已写成功，故不在「都没写」之列。
        """
        import google_sheets_service as gs
        hg, uid = _huguan_headers(client, "_push_partial", platform="tt")
        db = database.get_db()
        db.execute("INSERT OR REPLACE INTO config(key,value) VALUES(?,?)",
                   (f"huguan_dashboard_{uid}", json.dumps({"tt": {
                       "spreadsheet_id": "SS", "tables": [
                           {"name": "加白户", "sheet_name": "总户-加白"},
                           {"name": "企业户", "sheet_name": "总户-企业"}]}})))
        _seed_tt_account(db, "8001", uid, account_type="加白户")
        _seed_tt_account(db, "8002", uid, account_type="企业户")
        db.commit()
        db.close()

        # 快照读表：两张表各命中自己的账户 ⇒ 快照非空，「保留」与「本来就没有」不再同形
        grids = {"总户-加白": [["", "", ""], ["", "", "8001"]],
                 "总户-企业": [["", "", ""], ["", "", "8002"]]}
        monkeypatch.setattr(hd, "read_sheet_values", lambda *a, **k: grids[a[2]])
        monkeypatch.setattr(gs, "build_service", lambda path: object())

        wrote = []

        def _partial(svc, sid, name, rows, key_col="C"):
            wrote.append(name)
            if name == "总户-企业":
                raise RuntimeError("表 2 炸了")
            return {"updated": len(rows), "not_found": []}

        monkeypatch.setattr(gs, "update_rows_by_account_id", _partial)

        with pytest.raises(RuntimeError, match="表 2 炸了"):
            client.post("/api/huguan/dashboard/push", headers=hg, json={"platform": "tt"})
        assert wrote and wrote[0] == "总户-加白", \
            "表 1 必须先写成功，否则本用例测不到「部分写」"

        db = database.get_db()
        got = hd.load_undo(db, uid, "tt", "push")
        db.close()
        assert got is not None, "部分写成功 ⇒ 快照必须保留（表 1 的撤回入口不能丢）"


class TestPushUndoNotFoundPassthrough:
    """规格 §6.1 / §十 第 2 条：push 撤回时写入器报告的「表里找不到的行」原样透传。"""

    def test_undo_push_passes_not_found_through(self, client, fb_user, monkeypatch):
        """表里已删的行进 `not_found` 报告，不报错、也不许被吞成空列表。"""
        db = database.get_db()
        hd.save_undo(db, fb_user, "fb", "push",
                     {"spreadsheet_id": "S", "sheet_name": "N",
                      "cells": [{"account_id": "GONE", "cells": {"C": "旧名"}}]})
        db.commit()
        db.close()
        monkeypatch.setattr(hd, "_open_db", lambda: database.get_db())
        monkeypatch.setattr(hd, "get_platform_config",
                            lambda db_, uid, p: {"spreadsheet_id": "S", "sheet_name": "N"})
        import google_sheets_service as gs
        monkeypatch.setattr(gs, "build_service", lambda path: object())
        monkeypatch.setattr(gs, "update_rows_by_account_id",
                            lambda *a, **k: {"updated": 0, "not_found": ["X1"]})

        out = hd.undo_push(fb_user, "fb")
        assert out["not_found"] == ["X1"]
        assert out["updated"] == 0


# ========== Task 7: 撤回快照支持多表（每张表一份 + 旧单表快照兼容） ==========


def test_snapshot_and_undo_across_two_sheets(monkeypatch):
    """快照逐表分份，`push_undo_cells` 按表还原。

    ⚠️ 偏离 brief（一处，必要）：brief 给的 grid 把账户ID 放在**第 0 行**，而
    `snapshot_push_targets` 跳过表头（`grid[1:]`）⇒ 那个 grid 一个账户都命不中，
    `cells` 恒为空、断言必红（且是「空集上的恒真/恒假」式的红，测不到东西）。
    此处只把 ID 行挪到数据行（第 1 行），其余逐字照抄：断言的值与形状都不变。
    """
    import huguan_dashboard as hd
    import google_sheets_service as gs  # noqa: F401  （brief 原样保留）

    grids = {
        "总户-加白": [["", "", ""], ["", "", "8001"]],
        "总户-企业": [["", "", ""], ["", "", "8002"]],
    }

    def _read(svc, sid, name, rng):
        return grids[name]

    monkeypatch.setattr(hd, "read_sheet_values", _read)

    groups = [("总户-加白", [{"account_id": "8001", "cells": {"A": "x"}}]),
              ("总户-企业", [{"account_id": "8002", "cells": {"A": "y"}}])]
    snap = hd.snapshot_push_targets(object(), {"spreadsheet_id": "SS"}, "tt", groups)
    assert [s["sheet_name"] for s in snap["sheets"]] == ["总户-加白", "总户-企业"]
    assert (push_undo_calls := hd.push_undo_cells(snap))
    assert [(c["sheet_name"], [r["account_id"] for r in c["rows"]]) for c in push_undo_calls] == \
        [("总户-加白", ["8001"]), ("总户-企业", ["8002"])]


def _seed_tt_account(db, advertiser_id, owner_id, **over):
    """TT 侧夹具（本文件专用；定位键是 `advertiser_id`）。"""
    cols = {"advertiser_id": advertiser_id, "name": advertiser_id, "owner_id": owner_id,
            "country": "", "timezone": "", "consumption": "", "remark": "",
            "death_date": "", "deleted_at": None, "acquired_date": ""}
    cols.update(over)
    keys = ", ".join(cols)
    marks = ", ".join("?" for _ in cols)
    db.execute(f"INSERT INTO tt_accounts({keys}) VALUES({marks})", tuple(cols.values()))
    return db.execute("SELECT last_insert_rowid() AS id").fetchone()["id"]


class TestCrossTableDuplicateSheetBack:
    """跨表重复 + 归属变更 + 撤回（此前完全没有覆盖的组合）。

    Task 5 让「同一账户同时出现在两张 worksheet」成为可能。此时：
      - `build_diff` 的去重是**首次出现生效**（靠前的表胜出，后表记 warning）
      - 路由构造 `sheet_from` 曾经是**字典推导 = 后出现覆盖**
    两者方向相反 ⇒ 快照里的表侧原值取自**后**那张表，而系统里生效的是**前**那张表。
    撤回时就会把后表的运营名写进前表（串表），且没有任何测试能发现。
    """

    def test_first_table_wins_and_undo_restores_that_value(self, client, monkeypatch):
        import main
        import google_sheets_service as gs

        hg, uid = _huguan_headers(client, "_undo_xtab", platform="gg")
        db = database.get_db()
        db.execute("INSERT OR REPLACE INTO config(key,value) VALUES(?,?)",
                   (f"huguan_dashboard_{uid}", json.dumps({"tt": {
                       "spreadsheet_id": "SS", "tables": [
                           {"name": "加白户", "sheet_name": "总户-加白"},
                           {"name": "企业户", "sheet_name": "总户-企业"}]}})))
        li = _seed_user(db, "u_xtab_li", "李四")        # 库里 8003 的当前归属
        zhang = _seed_user(db, "u_xtab_zhang", "张三")   # 表里（前表）要改成的人
        _seed_tt_account(db, "8003", li, account_type="加白户")
        db.commit()
        db.close()

        # 表头映射后 tt 按**表头名**取列：`_tt_row` 的运营值落在 G（index 6），
        # 故表头第 7 格必须是「接户运营」（第 4~6 格空着，被 resolve_column_map 跳过）。
        hdr = ["入库时间", "是否回收", "账户ID", "", "", "", "接户运营"]
        # 同一账户 8003 在两张表里，且「接户运营」不同：前表=张三（胜出）、后表=李四
        tabs = {"总户-加白": [hdr, _tt_row("8003", "张三")],
                "总户-企业": [hdr, _tt_row("8003", "李四")]}
        monkeypatch.setattr(gs, "read_sheet_values", lambda svc, sid, name, rng: tabs[name])
        monkeypatch.setattr(gs, "build_service", lambda p: object())
        writes = []

        def _write(svc, sid, name, rows, key_col="C"):
            writes.append((name, rows, key_col))
            return {"updated": len(rows), "not_found": []}

        monkeypatch.setattr(gs, "update_rows_by_account_id", _write)
        monkeypatch.setattr(main, "_sync_sheets_background", lambda fn, cb: fn())

        resp = client.post("/api/huguan/dashboard/sync", headers=hg,
                           json={"platform": "tt", "dry_run": False,
                                 "confirmed": {"owner": ["8003"]}})
        assert resp.status_code == 200, resp.get_json()

        db = database.get_db()
        payload = hd.load_undo(db, uid, "tt", "sync")
        db.close()

        # ① 系统里生效的是**前表**：归属 李四 → 张三
        assert payload["owner_changes"][0]["account_id"] == "8003"
        assert payload["owner_changes"][0]["cols"]["owner_id"] == {"old": li, "new": zhang}
        # ② 表侧原值必须取自**同一张**（前）表 —— 后表是李四，写回前表就是串表
        assert payload["sheet_back"] == [{"account_id": "8003",
                                          "cells": {"G": "张三"}}]
        # ③ 同步收尾的定向回写也确实落在前表（按账户类型分组；行里多带 account_type）
        assert writes[0][0] == "总户-加白"
        assert [(r["account_id"], r["cells"]) for r in writes[0][1]] == [("8003", {"G": "张三"})]
        assert writes[0][2] == "C"

        # ④ 撤回：库侧回退 + 表侧盖回**前表**的原值。
        #    **不再把 conf 打桩成单表形状**（审查修复轮 1 · Finding 1）：表名从快照的
        #    `sheet_back_sheets` 来，真实的 tt 多表配置（无顶层 sheet_name）即可跑通 ——
        #    这正是「表侧回退在 tt 多表下不再静默失效」的钉子。
        #
        #    判别力（审查修复轮 1 · Finding 3）：同步自己的定向回写（writes[0]）与撤回的
        #    表侧回退（writes[-1]）在「前表 + G=张三」上**逐字相同** ⇒ 只断言 writes[-1] 的
        #    话，撤回表侧那步被短路（一个字都不写）时断言照样过。故先钉「撤回阶段真的新写了
        #    一次表」—— 短路时 writes 不增长，这里必红。
        n_before_undo = len(writes)
        out = hd.undo_sync(uid, "tt")
        assert out["reverted"] == 1
        db = database.get_db()
        owner = db.execute("SELECT owner_id FROM tt_accounts "
                           "WHERE advertiser_id='8003'").fetchone()[0]
        assert owner == li, "撤回后归属必须回到李四"
        assert hd.load_undo(db, uid, "tt", "sync") is None
        db.close()
        assert len(writes) == n_before_undo + 1, \
            "撤回必须真的写一次表（表侧那步被短路时这里会红）"
        assert writes[-1][0] == "总户-加白"
        assert [(r["account_id"], r["cells"]) for r in writes[-1][1]] == [("8003", {"G": "张三"})]
        assert writes[-1][2] == "C"


class TestPushUndoAcrossTwoSheets:
    """`undo_push` 在多表配置下逐表还原（tt 多表 conf 里没有 sheet_name）。"""

    def test_undo_push_writes_each_sheet(self, client, monkeypatch):
        """tt 多表：两个 worksheet 各写一次，且都按 `KEY_COL["tt"]`（C 列）定位。

        判别力：`undo_push` 改前用 `conf["spreadsheet_id"] / conf["sheet_name"]` 做前置
        校验与写表目标，而 tt 多表配置的 `sheet_name` 恒为空串 ⇒ 直接短路返回全零、
        一个字都不写（撤回按钮还亮着）。本用例会红。
        """
        import google_sheets_service as gs

        hg, uid = _huguan_headers(client, "_undo_multi", platform="gg")
        db = database.get_db()
        db.execute("INSERT OR REPLACE INTO config(key,value) VALUES(?,?)",
                   (f"huguan_dashboard_{uid}", json.dumps({"tt": {
                       "spreadsheet_id": "SS", "tables": [
                           {"name": "加白户", "sheet_name": "总户-加白"},
                           {"name": "企业户", "sheet_name": "总户-企业"}]}})))
        hd.save_undo(db, uid, "tt", "push",
                     {"spreadsheet_id": "SS", "sheets": [
                         {"sheet_name": "总户-加白",
                          "cells": [{"account_id": "8001", "cells": {"D": "旧BC"}}]},
                         {"sheet_name": "总户-企业",
                          "cells": [{"account_id": "8002", "cells": {"D": "旧BC2"}}]}]})
        db.commit()
        db.close()

        calls = []
        monkeypatch.setattr(gs, "build_service", lambda p: object())
        monkeypatch.setattr(gs, "update_rows_by_account_id",
                            lambda svc, sid, name, rows, key_col="C":
                            calls.append((sid, name, rows, key_col))
                            or {"updated": len(rows), "not_found": []})

        out = hd.undo_push(uid, "tt")
        assert [(c[1], [r["account_id"] for r in c[2]]) for c in calls] == \
            [("总户-加白", ["8001"]), ("总户-企业", ["8002"])]
        assert {c[3] for c in calls} == {"C"}, "tt 的定位列是 C（账户ID）"
        assert out == {"updated": 2, "not_found": []}
        db = database.get_db()
        assert hd.load_undo(db, uid, "tt", "push") is None
        db.close()


class TestUndoStatusCountAcrossShapes:
    def test_push_count_sums_sheets_of_new_shape(self, client):
        """新形状是多表快照 ⇒ 「影响 N 行」必须把各表行数加起来。

        改前只数 payload 顶层的 `cells`，新形状没有这个键 ⇒ 按钮亮着却显示
        「影响 0 行」。
        """
        hg, uid = _huguan_headers(client, "_undo_cnt_new", platform="fb")
        db = database.get_db()
        hd.save_undo(db, uid, "fb", "push",
                     {"spreadsheet_id": "S", "sheets": [
                         {"sheet_name": "A", "cells": [{"account_id": "1"}]},
                         {"sheet_name": "B", "cells": [{"account_id": "2"},
                                                       {"account_id": "3"}]}]})
        db.commit()
        db.close()
        got = client.get("/api/huguan/dashboard/undo?platform=fb", headers=hg).get_json()
        assert got["push"]["count"] == 3

