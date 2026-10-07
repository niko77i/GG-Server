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
