"""户管看板（Google Sheet 双向同步）测试。

设计见 docs/superpowers/specs/2026-09-23-huguan-sheet-design.md。
本文件不打真实 Google API：服务层调用一律用桩替换。
"""
import json

import database


# ---------- Task 1: 列工具 ----------

class TestColumnUtils:
    def test_col_index(self):
        from google_sheets_service import col_index
        assert col_index("A") == 0
        assert col_index("C") == 2
        assert col_index("N") == 13

    def test_col_letter(self):
        from google_sheets_service import col_letter
        assert col_letter(0) == "A"
        assert col_letter(2) == "C"
        assert col_letter(13) == "N"

    def test_merge_ranges_contiguous(self):
        from google_sheets_service import merge_ranges
        assert merge_ranges(["A", "B", "C", "D"]) == ["A:D"]

    def test_merge_ranges_with_gap(self):
        """非连续处必须断开：E 是唯一断口，故 A:D 与 F:K 分成两条。

        注意 F..K 本身是连续的（E 不在其中），所以只会断一次。
        """
        from google_sheets_service import merge_ranges
        cols = ["A", "B", "C", "D", "F", "G", "H", "I", "J", "K"]
        assert merge_ranges(cols) == ["A:D", "F:K"]

    def test_merge_ranges_single_and_empty(self):
        from google_sheets_service import merge_ranges
        assert merge_ranges(["D"]) == ["D:D"]
        assert merge_ranges([]) == []

    def test_merge_ranges_dedups_and_sorts(self):
        from google_sheets_service import merge_ranges
        assert merge_ranges(["B", "A", "B"]) == ["A:B"]


# ---------- Task 2: 列规格 + 系统→表 ----------

def _gg_row(**over):
    row = {
        "account_id": "1234567890",
        "acquired_date": "2026-09-01",
        "death_date": "",
        "timezone": "America/New_York",
        "mcc_name": "MCC-A",
        "agent_name": "渠道甲",
        "owner_name": "张三",
        "parent_mcc_name": "大MCC-A",
        "status_name": "存活",
    }
    row.update(over)
    return row


def _tt_row(**over):
    row = {
        "account_id": "7001234567890",
        "acquired_date": "2026-09-02",
        "death_date": "",
        "country": "US",
        "bc_name": "BC-1",
        "agent_name": "渠道乙",
        "owner_name": "李四",
        "timezone": "Asia/Shanghai",
        "status_name": "存活",
        "consumption": "120.5",
        "remark": "产品X",
    }
    row.update(over)
    return row


class TestColumnSpec:
    def test_gg_has_14_columns(self):
        from huguan_dashboard import COLUMN_SPEC
        assert len(COLUMN_SPEC["gg"]) == 14
        assert [c[0] for c in COLUMN_SPEC["gg"]] == list("ABCDEFGHIJKLMN")

    def test_tt_has_13_columns(self):
        from huguan_dashboard import COLUMN_SPEC
        assert len(COLUMN_SPEC["tt"]) == 13
        assert [c[0] for c in COLUMN_SPEC["tt"]] == list("ABCDEFGHIJKLM")

    def test_unmapped_columns_gg(self):
        """GG 的 E 国家 / L 位置 / M 消耗 / N 产品信息 系统不映射。"""
        from huguan_dashboard import COLUMN_SPEC
        unmapped = {c[0] for c in COLUMN_SPEC["gg"] if c[2] is None}
        assert unmapped == {"E", "L", "M", "N"}

    def test_unmapped_columns_tt(self):
        """TT 的 K 位置 系统不映射。"""
        from huguan_dashboard import COLUMN_SPEC
        unmapped = {c[0] for c in COLUMN_SPEC["tt"] if c[2] is None}
        assert unmapped == {"K"}

    def test_writable_cols_produce_expected_ranges(self):
        """COLUMN_SPEC 中标了 writable 的列 → A1 区间。

        H 列虽然 writable=True，但见下一条测试：它绝不出现在回写区间里。
        """
        from huguan_dashboard import COLUMN_SPEC
        from google_sheets_service import merge_ranges
        for platform in ("gg", "tt"):
            cols = [c[0] for c in COLUMN_SPEC[platform] if c[3]]
            if platform == "gg":
                # A..D 连续；E 跳过；F..K 连续 —— 只断一次
                assert merge_ranges(cols) == ["A:D", "F:K"]
            else:
                # A..J 连续；K 跳过；L、M 连续
                assert merge_ranges(cols) == ["A:J", "L:M"]

    def test_real_writeback_ranges_never_span_owner_channel(self):
        """★这是规则 2 的守门测试：自动回写合并出的区间不得覆盖 H 列。

        cells_for_row 不产出 H（§7.2 规则 2），而 merge_ranges 只合并 cells 里
        相邻的列，因此 H 必然落在 F:G 与 I:K 之间的断口上。若哪天有人给
        cells_for_row 加了 H，或改了 merge_ranges 的合并规则，这条会红。
        """
        from huguan_dashboard import cells_for_row
        from google_sheets_service import merge_ranges
        cells = cells_for_row(_gg_row(), "gg")
        assert "H" not in cells
        ranges = merge_ranges(list(cells.keys()))
        assert ranges == ["A:D", "F:G", "I:K"]
        # 逐列展开，确认 H 不在任何一个区间覆盖到的列里
        covered = set()
        for rng in ranges:
            first, last = rng.split(":")
            covered.update(chr(c) for c in range(ord(first), ord(last) + 1))
        assert "H" not in covered
        assert "E" not in covered

    def test_parent_mcc_is_writable_but_not_readable(self):
        """J 大MCC 是派生列：写回要用，读回必须忽略。"""
        from huguan_dashboard import COLUMN_SPEC
        spec = {c[0]: c for c in COLUMN_SPEC["gg"]}
        assert spec["J"][3] is True   # 可写
        assert spec["J"][4] is False  # 不可读


class TestCellsForRow:
    def test_gg_cells(self):
        from huguan_dashboard import cells_for_row
        cells = cells_for_row(_gg_row(), "gg")
        assert cells["A"] == "2026-09-01"
        assert cells["B"] == ""            # 未封户
        assert cells["D"] == "MCC-A"
        assert cells["F"] == "渠道甲"
        assert cells["G"] == "张三"
        assert cells["I"] == "America/New_York"
        assert cells["J"] == "大MCC-A"
        assert cells["K"] == "存活"
        # 未映射列一个都不能出现
        for col in ("E", "L", "M", "N"):
            assert col not in cells

    def test_gg_dead_flag(self):
        from huguan_dashboard import cells_for_row
        assert cells_for_row(_gg_row(death_date="2026-09-10"), "gg")["B"] == "是"

    def test_account_id_forced_to_text(self):
        """长数字账户ID 必须加 ' 前缀，否则 Sheets 会按数字处理丢精度。"""
        from huguan_dashboard import cells_for_row
        assert cells_for_row(_gg_row(), "gg")["C"] == "'1234567890"

    def test_never_emits_owner_channel(self):
        """规格 §7.2 规则 2：自动回写绝不产出 重新分配 / 换绑情况 列。"""
        from huguan_dashboard import cells_for_row
        assert "H" not in cells_for_row(_gg_row(), "gg")
        assert "L" not in cells_for_row(_tt_row(), "tt")

    def test_tt_cells(self):
        from huguan_dashboard import cells_for_row
        cells = cells_for_row(_tt_row(), "tt")
        assert cells["C"] == "'7001234567890"
        assert cells["D"] == "BC-1"
        assert cells["E"] == "US"
        assert cells["G"] == "李四"
        assert cells["H"] == "Asia/Shanghai"
        assert cells["J"] == "120.5"
        assert "K" not in cells   # 位置列不映射
        assert cells["M"] == "产品X"

    def test_missing_field_becomes_empty_string(self):
        from huguan_dashboard import cells_for_row
        cells = cells_for_row({"account_id": "1"}, "gg")
        assert cells["A"] == ""
        assert cells["K"] == ""


# ---------- Task 3: 表→系统 ----------

class TestParseRow:
    def test_parsed_key_name_is_normalized_to_account_id(self):
        """解析结果的统一键名恒为 `account_id`；DB 列名另由 ACCOUNT_KEY_FIELD 映射。

        这两个是**不同命名空间**：消费解析结果时用 `account_id`，
        拼 SQL / 写库时用 `ACCOUNT_KEY_FIELD[platform]`。
        谁把 parse_row 改成按平台输出 `advertiser_id`，这条就会红。
        """
        from huguan_dashboard import ACCOUNT_KEY_FIELD, parse_row
        assert ACCOUNT_KEY_FIELD == {"gg": "account_id", "tt": "advertiser_id"}
        p = parse_row(["", "", "'7001234567890"], "tt")
        assert p["account_id"] == "7001234567890"
        assert "advertiser_id" not in p

    def test_gg_parse_full_row(self):
        from huguan_dashboard import parse_row
        values = ["2026-09-01", "", "1234567890", "MCC-A", "美国", "渠道甲",
                  "张三", "", "America/New_York", "大MCC-A", "存活", "位置X", "", ""]
        p = parse_row(values, "gg")
        assert p["account_id"] == "1234567890"
        assert p["acquired_date"] == "2026-09-01"
        assert p["_dead_flag"] == ""
        assert p["mcc_name"] == "MCC-A"
        assert p["agent_name"] == "渠道甲"
        assert p["owner_name"] == "张三"
        assert p["_owner_channel"] == ""
        assert p["timezone"] == "America/New_York"
        assert p["status_name"] == "存活"

    def test_strips_leading_apostrophe_from_key(self):
        from huguan_dashboard import parse_row
        p = parse_row(["", "", "'1234567890"], "gg")
        assert p["account_id"] == "1234567890"

    def test_ignores_derived_and_unmapped_columns(self):
        """J 大MCC 是派生列、E/L/M/N 不映射 —— 解析结果里都不该有。"""
        from huguan_dashboard import parse_row
        p = parse_row(["", "", "1", "MCC-A", "美国", "", "", "", "", "大MCC-A",
                       "", "位置X", "999", "产品Y"], "gg")
        assert "parent_mcc_name" not in p
        assert set(p) == {"account_id", "acquired_date", "_dead_flag", "mcc_name",
                          "agent_name", "owner_name", "_owner_channel",
                          "timezone", "status_name"}

    def test_short_row_pads_empty(self):
        from huguan_dashboard import parse_row
        p = parse_row([], "tt")
        assert p["account_id"] == ""
        assert p["bc_name"] == ""
        assert p["remark"] == ""

    def test_tt_parse(self):
        from huguan_dashboard import parse_row
        values = ["2026-09-02", "是", "7001234567890", "BC-1", "US", "渠道乙",
                  "李四", "Asia/Shanghai", "死亡", "120.5", "位置Y", "王五", "产品X"]
        p = parse_row(values, "tt")
        assert p["account_id"] == "7001234567890"
        assert p["_dead_flag"] == "是"
        assert p["bc_name"] == "BC-1"
        assert p["country"] == "US"
        assert p["_owner_channel"] == "王五"   # L 换绑情况
        assert p["consumption"] == "120.5"
        assert p["remark"] == "产品X"

    def test_tt_parse_emits_exact_field_set(self):
        """TT 可读列的精确键集 —— 任一侧的读写 flag 被改都会红。"""
        from huguan_dashboard import parse_row
        p = parse_row(["", "", "'1"], "tt")
        assert set(p) == {"account_id", "acquired_date", "_dead_flag", "bc_name",
                          "country", "agent_name", "owner_name", "_owner_channel",
                          "timezone", "status_name", "consumption", "remark"}

    def test_whitespace_is_stripped(self):
        from huguan_dashboard import parse_row
        p = parse_row(["  2026-09-01  ", "", "  123  "], "gg")
        assert p["acquired_date"] == "2026-09-01"
        assert p["account_id"] == "123"


class TestEffectiveOwnerName:
    def test_channel_wins_when_present(self):
        """规格 §7.1：运营与重新分配不一致时以重新分配为准。"""
        from huguan_dashboard import effective_owner_name
        p = {"owner_name": "张三", "_owner_channel": "李四"}
        assert effective_owner_name(p) == "李四"

    def test_falls_back_to_owner_when_channel_empty(self):
        from huguan_dashboard import effective_owner_name
        assert effective_owner_name({"owner_name": "张三", "_owner_channel": ""}) == "张三"

    def test_whitespace_channel_falls_back_to_owner(self):
        """通道只有空白时不算「已填」，应回退到运营列。"""
        from huguan_dashboard import effective_owner_name
        assert effective_owner_name({"owner_name": "张三", "_owner_channel": "   "}) == "张三"

    def test_blank_when_both_empty(self):
        from huguan_dashboard import effective_owner_name
        assert effective_owner_name({"owner_name": "", "_owner_channel": "  "}) == ""


class TestIsDead:
    def test_status_alive_beats_dead_flag(self):
        """状态列有值时以它为准：状态=存活 时，是否封户=是 也不能判死。"""
        from huguan_dashboard import is_dead
        assert is_dead({"status_name": "存活", "_dead_flag": "是"}) is False

    def test_status_column_wins(self):
        """状态列更具体：状态=死亡 时，是否封户 不填也算死亡。"""
        from huguan_dashboard import is_dead
        assert is_dead({"status_name": "死亡", "_dead_flag": ""}) is True

    def test_dead_flag_fallback(self):
        from huguan_dashboard import is_dead
        assert is_dead({"status_name": "", "_dead_flag": "是"}) is True

    def test_alive(self):
        from huguan_dashboard import is_dead
        assert is_dead({"status_name": "存活", "_dead_flag": ""}) is False
        assert is_dead({"status_name": "", "_dead_flag": "否"}) is False


# ---------- Task 4: 批量行写入 ----------

class _FakeExec:
    def __init__(self, recorder, payload):
        self._recorder = recorder
        self._payload = payload

    def execute(self):
        self._recorder.append(self._payload)
        return self._payload


class _FakeValues:
    def __init__(self, recorder, grid):
        self._recorder = recorder
        self._grid = grid

    def get(self, spreadsheetId=None, range=None):
        self._recorder.append({"op": "get", "range": range})
        return _FakeExec(self._recorder, {"values": self._grid})

    def batchUpdate(self, spreadsheetId=None, body=None):
        return _FakeExec(self._recorder, {"op": "batchUpdate", "body": body})


class _FakeSheets:
    def __init__(self, recorder, grid):
        self._values = _FakeValues(recorder, grid)

    def values(self):
        return self._values


class _FakeService:
    def __init__(self, grid):
        self.recorder = []
        self._sheets = _FakeSheets(self.recorder, grid)

    def spreadsheets(self):
        return self._sheets


def _grid(rows):
    """rows: [account_id, ...] → C 列在 index 2 的最小网格。"""
    return [["", "", aid] for aid in rows]


class TestUpdateRowsByAccountId:
    def test_writes_only_listed_columns(self):
        from google_sheets_service import update_rows_by_account_id
        svc = _FakeService(_grid(["111", "222"]))
        res = update_rows_by_account_id(
            svc, "SS", "看板", [{"account_id": "222", "cells": {"A": "x", "G": "张三"}}]
        )
        assert res == {"updated": 1, "not_found": []}
        batch = [r for r in svc.recorder if r.get("op") == "batchUpdate"]
        assert len(batch) == 1
        data = batch[0]["body"]["data"]
        # A 与 G 不连续 → 两条区间，D~F 中间被跳过的列绝不落进区间
        assert [d["range"] for d in data] == ["'看板'!A2:A2", "'看板'!G2:G2"]
        assert data[0]["values"] == [["x"]]
        assert data[1]["values"] == [["张三"]]

    def test_contiguous_columns_merge_into_one_range(self):
        from google_sheets_service import update_rows_by_account_id
        svc = _FakeService(_grid(["111"]))
        update_rows_by_account_id(
            svc, "SS", "看板",
            [{"account_id": "111", "cells": {"A": "1", "B": "2", "C": "3", "D": "4"}}],
        )
        data = [r for r in svc.recorder if r.get("op") == "batchUpdate"][0]["body"]["data"]
        assert len(data) == 1
        assert data[0]["range"] == "'看板'!A1:D1"
        assert data[0]["values"] == [["1", "2", "3", "4"]]

    def test_gap_in_cells_splits_into_separate_ranges(self):
        """cells 里有空洞时区间会断开，而不是补空串。

        这正是「未出现在 cells 里的列一律不碰」的实现保证：merge_ranges 只会把
        在 cells 里**相邻**的列并成区间，所以 B、C 绝不会被顺带写进去。
        """
        from google_sheets_service import update_rows_by_account_id
        svc = _FakeService(_grid(["111"]))
        update_rows_by_account_id(
            svc, "SS", "看板", [{"account_id": "111", "cells": {"A": "1", "D": "4"}}]
        )
        data = [r for r in svc.recorder if r.get("op") == "batchUpdate"][0]["body"]["data"]
        assert [d["range"] for d in data] == ["'看板'!A1:A1", "'看板'!D1:D1"]
        assert data[0]["values"] == [["1"]]
        assert data[1]["values"] == [["4"]]

    def test_not_found_reported_not_raised(self):
        """表里没有这个账户是正常情况（户管的表不必包含所有账户），不能抛。"""
        from google_sheets_service import update_rows_by_account_id
        svc = _FakeService(_grid(["111"]))
        res = update_rows_by_account_id(
            svc, "SS", "看板",
            [{"account_id": "111", "cells": {"A": "1"}},
             {"account_id": "999", "cells": {"A": "2"}}],
        )
        assert res["updated"] == 1
        assert res["not_found"] == ["999"]

    def test_matches_apostrophe_prefixed_key(self):
        """定位时要剥掉 ' 前缀：表里存的可能是强制文本形式。"""
        from google_sheets_service import update_rows_by_account_id
        svc = _FakeService([["", "", "'111"]])
        res = update_rows_by_account_id(
            svc, "SS", "看板", [{"account_id": "111", "cells": {"A": "1"}}]
        )
        assert res == {"updated": 1, "not_found": []}

    def test_key_column_read_range_is_minimal(self):
        """只读 A:C 找键，不读整表。"""
        from google_sheets_service import update_rows_by_account_id
        svc = _FakeService(_grid(["111"]))
        update_rows_by_account_id(svc, "SS", "看板", [{"account_id": "111", "cells": {"A": "1"}}])
        gets = [r for r in svc.recorder if r.get("op") == "get"]
        assert gets[0]["range"] == "'看板'!A:C"

    def test_empty_rows_is_noop(self):
        from google_sheets_service import update_rows_by_account_id
        svc = _FakeService(_grid(["111"]))
        assert update_rows_by_account_id(svc, "SS", "看板", []) == {"updated": 0, "not_found": []}
        assert svc.recorder == []


# ---------- Task 5: 配置读写 + 权限 ----------

def _create_user(client, username, role="user", platform="gg"):
    """注册用户 → 改写 role/platform → 登录。返回 (headers, user_id)。"""
    client.post("/api/auth/register", json={"username": username, "password": "test123"})
    db = database.get_db()
    db.execute("UPDATE users SET role=?, platform=? WHERE username=?", (role, platform, username))
    db.commit()
    row = db.execute("SELECT id FROM users WHERE username=?", (username,)).fetchone()
    db.close()
    resp = client.post("/api/auth/login", json={"username": username, "password": "test123"})
    return {"Authorization": f"Bearer {resp.get_json()['access_token']}"}, row["id"]


class TestDashboardConfig:
    def test_save_then_get_roundtrip(self, client):
        hg, _ = _create_user(client, "_hg_cfg1", role="huguan")
        resp = client.post("/api/huguan/dashboard", headers=hg, json={
            "platform": "gg", "spreadsheet_id": "SS-GG", "sheet_name": "户管看板",
        })
        assert resp.status_code == 200
        got = client.get("/api/huguan/dashboard", headers=hg).get_json()["config"]
        assert got["gg"] == {"spreadsheet_id": "SS-GG", "sheet_name": "户管看板"}

    def test_platforms_are_isolated(self, client):
        """GG 与 TT 各配各的，互不覆盖（需求原文：这个sheet在gg和tt配置的是不一样的）。"""
        hg, _ = _create_user(client, "_hg_cfg2", role="huguan")
        client.post("/api/huguan/dashboard", headers=hg,
                    json={"platform": "gg", "spreadsheet_id": "SS-GG", "sheet_name": "G"})
        client.post("/api/huguan/dashboard", headers=hg,
                    json={"platform": "tt", "spreadsheet_id": "SS-TT", "sheet_name": "T"})
        got = client.get("/api/huguan/dashboard", headers=hg).get_json()["config"]
        assert got["gg"]["spreadsheet_id"] == "SS-GG"
        assert got["tt"]["spreadsheet_id"] == "SS-TT"

    def test_users_are_isolated(self, client):
        hg1, _ = _create_user(client, "_hg_cfg_a", role="huguan")
        hg2, _ = _create_user(client, "_hg_cfg_b", role="huguan")
        client.post("/api/huguan/dashboard", headers=hg1,
                    json={"platform": "gg", "spreadsheet_id": "SS-1", "sheet_name": "A"})
        got2 = client.get("/api/huguan/dashboard", headers=hg2).get_json()["config"]
        assert got2.get("gg", {}).get("spreadsheet_id", "") == ""

    def test_url_is_parsed_to_id(self, client):
        hg, _ = _create_user(client, "_hg_cfg3", role="huguan")
        client.post("/api/huguan/dashboard", headers=hg, json={
            "platform": "gg",
            "spreadsheet_id": "https://docs.google.com/spreadsheets/d/ABC-123_x/edit#gid=0",
            "sheet_name": "S",
        })
        got = client.get("/api/huguan/dashboard", headers=hg).get_json()["config"]
        assert got["gg"]["spreadsheet_id"] == "ABC-123_x"

    def test_invalid_platform_rejected(self, client):
        hg, _ = _create_user(client, "_hg_cfg4", role="huguan")
        resp = client.post("/api/huguan/dashboard", headers=hg,
                           json={"platform": "fb", "spreadsheet_id": "S", "sheet_name": "N"})
        assert resp.status_code == 400

    def test_non_huguan_gets_403(self, client):
        """规格：全部 /api/huguan/dashboard* 仅户管可达。"""
        for role in ("user", "viewer", "admin", "developer"):
            h, _ = _create_user(client, f"_nothg_{role}", role=role)
            assert client.get("/api/huguan/dashboard", headers=h).status_code == 403
            assert client.post("/api/huguan/dashboard", headers=h,
                               json={"platform": "gg", "spreadsheet_id": "S",
                                     "sheet_name": "N"}).status_code == 403

    def test_requires_jwt(self, client):
        assert client.get("/api/huguan/dashboard").status_code == 401

    def test_malformed_body_is_400_not_500(self, client):
        """畸形 body 必须 400 而不是 500 —— 非 dict body，以及 platform 非法。

        循环里三条 payload 只有 `{"platform": 5}` 以前会 `AttributeError` 炸成 500；
        `{"spreadsheet_id": 123}`（缺 platform 键，旧代码 `(None or "")` 已得 `""`）与
        `{"platform": "fb"}` 从来就是 400。断言都不变，只是别把注释读成「三条都曾 500」。
        另注意 `sheet_name` 给数字**不算**畸形：按全局约束与 spreadsheet_id 一致地
        `str()` 兜底（见下一条），所以这里只钉 body 结构与 platform 非法两条路径。
        """
        hg, _ = _create_user(client, "_hg_badbody", role="huguan")
        for payload in ({"platform": 5}, {"spreadsheet_id": 123}, {"platform": "fb"}):
            resp = client.post("/api/huguan/dashboard", headers=hg, json=payload)
            assert resp.status_code == 400, payload
        assert client.post("/api/huguan/dashboard", headers=hg,
                           json=[1, 2]).status_code == 400

    def test_numeric_fields_are_coerced_not_500(self, client):
        """数字型字段一律 `str()` 兜底后按字符串处理，既不 500 也不当畸形拒掉。

        与 spreadsheet_id 同一口径：户管粘进来的表格名/ID 是数字串很常见。
        """
        hg, _ = _create_user(client, "_hg_numeric", role="huguan")
        resp = client.post("/api/huguan/dashboard", headers=hg, json={
            "platform": "gg", "spreadsheet_id": 123456, "sheet_name": 5,
        })
        assert resp.status_code == 200
        got = client.get("/api/huguan/dashboard", headers=hg).get_json()["config"]
        assert got["gg"] == {"spreadsheet_id": "123456", "sheet_name": "5"}

    def test_non_dict_platform_entry_is_tolerated(self, client):
        """config 里平台条目是「真值非 dict」时不得抛异常（该表被别处共用）。"""
        from huguan_dashboard import get_platform_config
        _, uid = _create_user(client, "_hg_nondict", role="huguan")
        db = database.get_db()
        db.execute("INSERT OR REPLACE INTO config(key,value) VALUES(?,?)",
                   (f"huguan_dashboard_{uid}", '{"gg": "just-a-string", "tt": null}'))
        db.commit()
        empty = {"spreadsheet_id": "", "sheet_name": ""}
        assert get_platform_config(db, uid, "gg") == empty
        assert get_platform_config(db, uid, "tt") == empty
        db.close()

    def test_non_string_inner_values_are_tolerated(self, client):
        """平台条目**内层值**不是字符串时也不得抛异常。

        外层判了 dict 不代表里面存的是字符串：`config` 表全仓共用，值可能是数字或列表。
        `(v or "").strip()` 会 `AttributeError` → 500。
        """
        from huguan_dashboard import get_platform_config
        _, uid = _create_user(client, "_hg_inner", role="huguan")
        db = database.get_db()
        db.execute("INSERT OR REPLACE INTO config(key,value) VALUES(?,?)",
                   (f"huguan_dashboard_{uid}",
                    '{"gg": {"spreadsheet_id": 123, "sheet_name": ["x"]}}'))
        db.commit()
        got = get_platform_config(db, uid, "gg")
        assert got["spreadsheet_id"] == "123"
        assert isinstance(got["sheet_name"], str)   # 关键是不抛异常
        db.close()

    def test_save_config_tolerates_non_string_args(self, client):
        """save_config 直接收到数字/None 也不能炸（Task 7–9 会直接调它）。"""
        from huguan_dashboard import get_platform_config, save_config
        _, uid = _create_user(client, "_hg_savearg", role="huguan")
        db = database.get_db()
        save_config(db, uid, "gg", 123, None)
        assert get_platform_config(db, uid, "gg") == {"spreadsheet_id": "123",
                                                      "sheet_name": ""}
        db.close()

    def test_get_normalizes_non_dict_platform_entry(self, client):
        """`config` 里平台条目是「真值非 dict」时，GET 也要返回结构完整的对象。

        不归一化就会把字符串/数字原样透传，破坏 {"spreadsheet_id","sheet_name"} 契约。
        """
        hg, uid = _create_user(client, "_hg_getnorm", role="huguan")
        db = database.get_db()
        db.execute("INSERT OR REPLACE INTO config(key,value) VALUES(?,?)",
                   (f"huguan_dashboard_{uid}", '{"gg": "just-a-string"}'))
        db.commit()
        db.close()
        got = client.get("/api/huguan/dashboard", headers=hg).get_json()["config"]
        assert got["gg"] == {"spreadsheet_id": "", "sheet_name": ""}
        assert got["tt"] == {"spreadsheet_id": "", "sheet_name": ""}


# ---------- Task 6: 差异比对 ----------

def _seed(db, username, display_name, role="user", platform="gg"):
    db.execute("INSERT INTO users(username, password, role, display_name, platform) "
               "VALUES(?,?,?,?,?)", (username, "x", role, display_name, platform))
    db.commit()
    return db.execute("SELECT id FROM users WHERE username=?", (username,)).fetchone()["id"]


def _seed_account(db, account_id, owner_id, **over):
    cols = {"account_id": account_id, "name": account_id, "owner_id": owner_id,
            "timezone": "", "death_date": "", "deleted_at": None}
    cols.update(over)
    keys = ", ".join(cols)
    marks = ", ".join("?" for _ in cols)
    db.execute(f"INSERT INTO accounts({keys}) VALUES({marks})", tuple(cols.values()))
    db.commit()
    return db.execute("SELECT id FROM accounts WHERE account_id=?", (account_id,)).fetchone()["id"]


def _seed_tt_account(db, advertiser_id, owner_id, **over):
    """TT 侧夹具。定位键是 `advertiser_id`（Task 6/9 的 TT 路径都靠它）。"""
    cols = {"advertiser_id": advertiser_id, "name": advertiser_id, "owner_id": owner_id,
            "country": "", "timezone": "", "consumption": "", "remark": "",
            "death_date": "", "deleted_at": None, "acquired_date": ""}
    cols.update(over)
    keys = ", ".join(cols)
    marks = ", ".join("?" for _ in cols)
    db.execute(f"INSERT INTO tt_accounts({keys}) VALUES({marks})", tuple(cols.values()))
    db.commit()


class TestResolvers:
    def test_resolve_owner_by_display_name(self, client):
        from huguan_dashboard import resolve_owner_id
        db = database.get_db()
        uid = _seed(db, "_r1", "张三")
        assert resolve_owner_id(db, "张三") == uid
        db.close()

    def test_resolve_owner_falls_back_to_username(self, client):
        from huguan_dashboard import resolve_owner_id
        db = database.get_db()
        uid = _seed(db, "_r2", "")
        assert resolve_owner_id(db, "_r2") == uid
        db.close()

    def test_ambiguous_name_returns_none(self, client):
        """名称命中 ≥2 条 → None（规格 §8.4：该列不落库）。"""
        from huguan_dashboard import resolve_owner_id
        db = database.get_db()
        _seed(db, "_r3a", "重名")
        _seed(db, "_r3b", "重名")
        assert resolve_owner_id(db, "重名") is None
        db.close()

    def test_username_colliding_with_another_display_name_is_ambiguous(self, client):
        """甲的 display_name 撞上乙的 username ⇒ 必须判为歧义，不得猜中甲。

        拆成「先查 display_name，查不到再查 username」两条查询时，这里会静默返回
        `_r5a`（display_name 那条先命中），把账户挂到错误的人名下。写表方向
        （`COALESCE(NULLIF(display_name,''), username)`）产出的是一个合成名字空间，
        反向解析必须对称。对照行 `_r5b` 是**必须被算进去的第二个命中**。
        """
        from huguan_dashboard import resolve_owner_id
        db = database.get_db()
        _seed(db, "_r5a", "撞名")   # display_name = "撞名"
        _seed(db, "撞名", "")       # username     = "撞名"（display_name 空 → 回退后也叫"撞名"）
        assert resolve_owner_id(db, "撞名") is None
        db.close()

    def test_unknown_name_returns_none(self, client):
        from huguan_dashboard import resolve_owner_id
        db = database.get_db()
        assert resolve_owner_id(db, "查无此人") is None
        assert resolve_owner_id(db, "") is None
        db.close()

    def test_resolve_status_creates_under_owner(self, client):
        """按 owner + 平台双作用域：同名同 owner 但平台不同必须是两行。

        account_statuses.platform 默认 'gg'（database.py:153），不显式写平台
        会让 TT 的状态落进 gg 命名空间（状态下拉按平台过滤，main.py:6059）。
        """
        from huguan_dashboard import resolve_status_id
        db = database.get_db()
        uid = _seed(db, "_r4", "王五")
        sid = resolve_status_id(db, "待优化", uid, "gg")
        db.commit()
        row = db.execute("SELECT owner_id, platform FROM account_statuses WHERE id=?",
                         (sid,)).fetchone()
        assert row["owner_id"] == uid
        assert row["platform"] == "gg"
        # 再解析同名同平台，应复用同一行而不是重复新建
        assert resolve_status_id(db, "待优化", uid, "gg") == sid
        # 同名同 owner 换平台 → 另一行，且平台正确
        sid_tt = resolve_status_id(db, "待优化", uid, "tt")
        db.commit()
        assert sid_tt != sid
        assert db.execute("SELECT platform FROM account_statuses WHERE id=?",
                          (sid_tt,)).fetchone()["platform"] == "tt"
        assert resolve_status_id(db, "待优化", uid, "tt") == sid_tt
        db.close()

    def test_resolve_status_id_pins_name_then_platform_argument_order(self, client):
        """`resolve_status_id` 的第 1 / 第 4 个实参必须分别是 name / platform。

        name 与 platform 被调换时，查重会变成 `WHERE name='gg' AND platform='A'`
        —— 「A」(gg) 这个已存在的状态查不中，于是**静默新建一行**（或直接撞
        `UNIQUE(name, platform)`），把账户的状态挂到一个刚造出来的行上，平台命名空间
        也被污染（TT 的状态落进 gg 下拉）。两条状态的名字刻意取平台代号，让顺序错位
        必然查不中；`uid` 是 int 也顺带挡住 owner_id / platform 互换那种写法。
        """
        from huguan_dashboard import resolve_status_id
        db = database.get_db()
        uid = _seed(db, "_r6", "赵六")
        db.execute("INSERT INTO account_statuses(name, owner_id, platform) "
                   "VALUES('A', ?, 'gg')", (uid,))
        db.execute("INSERT INTO account_statuses(name, owner_id, platform) "
                   "VALUES('B', ?, 'tt')", (uid,))
        db.commit()
        id_a = db.execute("SELECT id FROM account_statuses WHERE name='A'").fetchone()["id"]
        id_b = db.execute("SELECT id FROM account_statuses WHERE name='B'").fetchone()["id"]
        assert resolve_status_id(db, "A", uid, "gg") == id_a
        assert resolve_status_id(db, "B", uid, "tt") == id_b
        # 两条都在且被复用：实参错位会多出一行（或直接 IntegrityError）
        assert db.execute("SELECT COUNT(*) AS n FROM account_statuses").fetchone()["n"] == 2
        db.close()


class TestBuildDiff:
    def _prepare(self, client):
        db = database.get_db()
        u1 = _seed(db, "_bd_zhang", "张三")
        u2 = _seed(db, "_bd_li", "李四")
        return db, u1, u2

    def test_new_account_goes_to_create(self, client):
        from huguan_dashboard import build_diff, parse_row
        db, u1, _ = self._prepare(client)
        parsed = [dict(parse_row(["", "", "NEW-1", "", "", "", "张三"], "gg"), row=2)]
        diff = build_diff(db, parsed, "gg")
        assert len(diff["to_create"]) == 1
        assert diff["to_create"][0]["account_id"] == "NEW-1"
        assert diff["to_create"][0]["owner_id"] == u1
        db.close()

    def test_new_account_without_owner_leaves_null(self, client):
        """规格 §7.4：运营列空着就空着，户管随时可以改。"""
        from huguan_dashboard import build_diff, parse_row
        db, _, _ = self._prepare(client)
        parsed = [dict(parse_row(["", "", "NEW-2"], "gg"), row=2)]
        diff = build_diff(db, parsed, "gg")
        assert diff["to_create"][0]["owner_id"] is None
        db.close()

    def test_existing_deleted_account_is_skipped(self, client):
        from huguan_dashboard import build_diff, parse_row
        db, u1, _ = self._prepare(client)
        _seed_account(db, "DEL-1", u1, deleted_at="2026-09-01 00:00:00")
        parsed = [dict(parse_row(["", "", "DEL-1"], "gg"), row=2)]
        diff = build_diff(db, parsed, "gg")
        assert len(diff["to_skip"]) == 1
        assert diff["to_create"] == []
        db.close()

    def test_owner_channel_overrides_current_owner(self, client):
        """规格 §7.1 + 规则 1：重新分配 压过 运营。"""
        from huguan_dashboard import build_diff, parse_row
        db, u1, u2 = self._prepare(client)
        _seed_account(db, "OWN-1", u1)
        # G=张三（当前）、H=李四（重新分配）
        parsed = [dict(parse_row(["", "", "OWN-1", "", "", "", "张三", "李四"], "gg"), row=2)]
        diff = build_diff(db, parsed, "gg")
        assert len(diff["owner_changes"]) == 1
        assert diff["owner_changes"][0]["to_owner_id"] == u2
        assert diff["owner_changes"][0]["from"] == "张三"
        assert diff["owner_changes"][0]["to"] == "李四"
        db.close()

    def test_matching_owner_produces_no_change(self, client):
        from huguan_dashboard import build_diff, parse_row
        db, u1, _ = self._prepare(client)
        _seed_account(db, "OWN-2", u1)
        parsed = [dict(parse_row(["", "", "OWN-2", "", "", "", "张三"], "gg"), row=2)]
        assert build_diff(db, parsed, "gg")["owner_changes"] == []
        db.close()

    def test_unknown_owner_is_warning_not_change(self, client):
        from huguan_dashboard import build_diff, parse_row
        db, u1, _ = self._prepare(client)
        _seed_account(db, "OWN-3", u1)
        parsed = [dict(parse_row(["", "", "OWN-3", "", "", "", "查无此人"], "gg"), row=2)]
        diff = build_diff(db, parsed, "gg")
        assert diff["owner_changes"] == []
        assert any("查无此人" in w["message"] for w in diff["warnings"])
        db.close()

    def test_blank_owner_keeps_existing_owner(self, client):
        """规格 §7.4：表里两列都空时，不得把系统里已有的归属清掉。"""
        from huguan_dashboard import build_diff, parse_row
        db, u1, _ = self._prepare(client)
        _seed_account(db, "OWN-4", u1)
        parsed = [dict(parse_row(["", "", "OWN-4"], "gg"), row=2)]
        assert build_diff(db, parsed, "gg")["owner_changes"] == []
        db.close()

    def test_missing_account_id_is_warning(self, client):
        from huguan_dashboard import build_diff, parse_row
        db, _, _ = self._prepare(client)
        parsed = [dict(parse_row(["", "", "   "], "gg"), row=7)]
        diff = build_diff(db, parsed, "gg")
        assert diff["to_create"] == []
        assert any(w["row"] == 7 for w in diff["warnings"])
        db.close()

    def test_ambiguous_mcc_name_is_warning(self, client):
        """重名 MCC 不落库，但同一行的其他列照常更新。

        ★ `to_update` 必须非空，否则下面那条断言是**空集上的恒真式**。
        所以这里让 I 列（时区）与库里不同，先制造出一条真实更新。
        """
        from huguan_dashboard import build_diff, parse_row
        db, u1, _ = self._prepare(client)
        # acquired_date 必须显式钉成 ""：`accounts.acquired_date` 的 DDL 默认值是
        # `date('now','localtime')`（database.py:236），不钉住它就与表里的空 A 列
        # 构成一条**真实差异**，`fields` 会多出 `acquired_date: ""` 而非只有 timezone。
        _seed_account(db, "MCCACC", u1, acquired_date="")
        db.execute("INSERT INTO mcc(name, mcc_id) VALUES('同名MCC','1')")
        db.execute("INSERT INTO mcc(name, mcc_id) VALUES('同名MCC','2')")
        db.commit()
        parsed = [dict(parse_row(["", "", "MCCACC", "同名MCC", "", "", "", "",
                                  "Asia/Shanghai"], "gg"), row=2)]
        diff = build_diff(db, parsed, "gg")
        assert len(diff["to_update"]) == 1          # 非空，下面的断言才有意义
        assert diff["to_update"][0]["fields"] == {"timezone": "Asia/Shanghai"}
        assert "mcc_id" not in diff["to_update"][0]["fields"]
        assert any("同名MCC" in w["message"] for w in diff["warnings"])
        db.close()

    def test_summary_counts(self, client):
        from huguan_dashboard import build_diff, parse_row
        db, u1, u2 = self._prepare(client)
        _seed_account(db, "S-1", u1)
        parsed = [
            dict(parse_row(["", "", "S-1", "", "", "", "张三", "李四"], "gg"), row=2),
            dict(parse_row(["", "", "S-NEW", "", "", "", "张三"], "gg"), row=3),
        ]
        s = build_diff(db, parsed, "gg")["summary"]
        assert s["total_in_sheet"] == 2
        assert s["owner_changes"] == 1
        assert s["new_accounts"] == 1
        db.close()

    def test_blank_text_column_clears_system_value(self, client):
        """表里文本列空着 = 把系统里该列清空（规格 §8.3「按表覆盖该列」）。

        这是**刻意的**不对称：名称类字段空值跳过（空串解析不出候选，属 §8.4 的
        「命中 0 条」），文本列空值照常落库。改成「空值一律跳过」会让户管永远
        无法从表里清掉一个值（B 列「是否封户」清空即撤销死亡）。
        对照行：库里 timezone='Asia/Shanghai' 而表里 I 列为空 ⇒ 必须出现空值差异。
        """
        from huguan_dashboard import build_diff, parse_row
        db, u1, _ = self._prepare(client)
        _seed_account(db, "BLANK-1", u1, acquired_date="", timezone="Asia/Shanghai")
        parsed = [dict(parse_row(["", "", "BLANK-1"], "gg"), row=2)]
        diff = build_diff(db, parsed, "gg")
        assert len(diff["to_update"]) == 1
        assert diff["to_update"][0]["fields"]["timezone"] == ""
        db.close()

    def test_soft_deleted_bc_is_not_matched(self, client):
        """软删的 BC 不得被「唯一命中」放行（否则账户挂到已删的 BC 上）。

        对照行：同名 BC 只有一条、且已软删 ⇒ 若 SQL 不带 `deleted_at IS NULL`，
        它会成为唯一命中并被写入 bc_id。仓库既有口径见 tt_routes.py:133/198/1054/1058。
        """
        from huguan_dashboard import build_diff, parse_row
        db, u1, _ = self._prepare(client)
        _seed_tt_account(db, "BCDEL-1", u1)
        db.execute("INSERT INTO tt_bcs(name, bc_id, owner_id, deleted_at) "
                   "VALUES('已删BC','1',?,datetime('now'))", (u1,))
        db.commit()
        row = ["", "", "BCDEL-1", "已删BC", "", "", "", "", "", "", "", "", ""]
        parsed = [dict(parse_row(row, "tt"), row=2)]
        diff = build_diff(db, parsed, "tt")
        assert diff["to_update"] == []
        assert any("已删BC" in w["message"] for w in diff["warnings"])
        db.close()

    def test_tt_diff_uses_advertiser_id_and_reports_pending_status(self, client):
        """TT 侧端到端：定位键走 `advertiser_id`、新状态名走 `pending_status`。

        本任务此前**零 TT 覆盖**（实现者只用一次性探针验过），而 Task 9 的触发点
        全在 TT 侧 —— 这条把 TT 路径钉进测试网。
        系统里还没有「待优化」(tt) ⇒ 该走 pending_status（名字原样），
        **且此刻不得建行**（dry_run 只读，规格 §8.3 步骤 7）。
        落库侧的平台命名空间断言在 Task 7 的 apply 测试里。
        """
        from huguan_dashboard import build_diff, parse_row
        db, u1, _ = self._prepare(client)
        _seed_tt_account(db, "TTD-1", u1)
        row = ["", "", "TTD-1", "", "", "", "", "", "待优化", "", "", "", ""]
        parsed = [dict(parse_row(row, "tt"), row=2)]
        diff = build_diff(db, parsed, "tt")
        assert len(diff["to_update"]) == 1
        assert diff["to_update"][0]["account_id"] == "TTD-1"
        assert diff["to_update"][0]["pending_status"] == "待优化"
        assert "status_id" not in diff["to_update"][0]["fields"]
        # 只读：状态行不能在这一步出现，否则 dry_run 承诺的「不改库」就是假的
        assert db.execute("SELECT COUNT(*) AS n FROM account_statuses").fetchone()["n"] == 0
        # 定位键必须真是 advertiser_id —— 写错列会 INSERT 出第二行而不是更新这一行
        assert db.execute("SELECT owner_id FROM tt_accounts WHERE advertiser_id='TTD-1'"
                          ).fetchone()["owner_id"] == u1
        assert db.execute("SELECT COUNT(*) AS n FROM tt_accounts").fetchone()["n"] == 1
        db.close()

    def test_two_owners_same_status_name_does_not_crash(self, client):
        """两个运营写同名状态 ⇒ 必须复用同一行，不得 IntegrityError。

        真实唯一约束是 `UNIQUE(name, platform)`，**不含 owner_id**（database.py:1225
        的迁移重建，PRAGMA 实测索引列为 ['name','platform']）。若查重键带上 owner_id，
        乙的账户写「待优化」时查不中而重复 INSERT → IntegrityError 从解析穿到
        build_diff，**整份差异报告全丢**（同一 sheet 其它行的结果也拿不到）。
        对照写法：main.py:6102。
        """
        from huguan_dashboard import build_diff, parse_row
        db, u1, u2 = self._prepare(client)
        _seed_account(db, "DUP-A", u1, acquired_date="")
        _seed_account(db, "DUP-B", u2, acquired_date="")
        rows = [
            # GG 状态是 K 列（index 10）；写成 index 8 会落进 I 列（时区）
            dict(parse_row(["", "", "DUP-A", "", "", "", "张三", "", "", "", "待优化"], "gg"),
                 row=2),
            dict(parse_row(["", "", "DUP-B", "", "", "", "李四", "", "", "", "待优化"], "gg"),
                 row=3),
        ]
        diff = build_diff(db, rows, "gg")           # 不得抛异常
        assert len(diff["to_update"]) == 2
        assert {i["pending_status"] for i in diff["to_update"]} == {"待优化"}
        # 从解析层再确认一次：两个人解析同名同平台，拿到的是同一行
        from huguan_dashboard import resolve_status_id
        sid_a = resolve_status_id(db, "待优化", u1, "gg")
        sid_b = resolve_status_id(db, "待优化", u2, "gg")
        assert sid_a == sid_b
        assert db.execute("SELECT COUNT(*) AS n FROM account_statuses").fetchone()["n"] == 1
        db.close()

    def test_diff_is_read_only_even_with_new_status_name(self, client):
        """dry_run 全程只读：连「需要新建的状态行」也不许在这一步落库。

        规格 §8.3 步骤 7 / §10.1 第 6 项「dry_run=true 不改库」。插入若挂在共享连接上，
        调用方随后任何一次 commit 都会把它真写进去，而报告里的 id 也只有在提交后才存在
        ——所以必须在解析层就拦住，不能靠「反正没 commit」。
        """
        from huguan_dashboard import build_diff, parse_row
        db, u1, _ = self._prepare(client)
        _seed_account(db, "RO-1", u1, acquired_date="")
        db.execute("INSERT INTO mcc(name, mcc_id) VALUES('RO-MCC','7')")
        db.commit()
        rows = [dict(parse_row(["", "", "RO-1", "RO-MCC", "", "", "张三", "", "", "", "全新状态"],
                               "gg"), row=2)]
        before = db.execute("SELECT COUNT(*) AS n FROM account_statuses").fetchone()["n"]
        diff = build_diff(db, rows, "gg")
        db.commit()          # 调用方正常收尾的提交：不该让任何东西冒出来
        assert db.execute("SELECT COUNT(*) AS n FROM account_statuses").fetchone()["n"] == before
        item = diff["to_update"][0]
        assert item["pending_status"] == "全新状态"
        # 其余列照常比对（只有状态那一列是 pending）
        assert item["fields"]["mcc_id"] == db.execute(
            "SELECT id FROM mcc WHERE name='RO-MCC'").fetchone()["id"]
        db.close()

    def test_dead_flag_reaches_the_diff(self, client):
        """`_is_dead` 必须真的进报告 —— 它恒为 False 时封户/撤销死亡永不落库。

        对照组三行：死亡状态、B 列「是否封户」= 是、都不是。只断言 True 的那种
        测试杀不掉「恒 False」的变异体，所以第三条断言 False 是必需的。
        """
        from huguan_dashboard import build_diff, parse_row
        db, u1, _ = self._prepare(client)
        _seed_account(db, "DEAD-1", u1, acquired_date="")
        _seed_account(db, "DEAD-2", u1, acquired_date="")
        _seed_account(db, "DEAD-3", u1, death_date="2026-01-01")
        rows = [
            # GG 状态是 K 列（index 10）
            dict(parse_row(["", "", "DEAD-1", "", "", "", "张三", "", "", "", "死亡"], "gg"),
                 row=2),
            # B 列「是否封户」= 是（B 是 index 1；写成 index 0 会落进 A 列日期）
            dict(parse_row(["", "是", "DEAD-2", "", "", "", "张三"], "gg"), row=3),
            dict(parse_row(["", "", "DEAD-3", "", "", "", "张三"], "gg"), row=4),
        ]
        diff = build_diff(db, rows, "gg")
        by_row = {i["row"]: i for i in diff["to_update"]}
        assert by_row[2]["fields"]["_is_dead"] is True      # K 列「死亡」
        assert by_row[3]["fields"]["_is_dead"] is True      # B 列「是否封户」= 是
        assert by_row[4]["fields"]["_is_dead"] is False     # 撤销死亡
        db.close()

    def test_to_create_carries_db_values_not_cells(self, client):
        """`to_create` 的键名叫 `db_values` 且真装着要写进库的值。

        两个变异体一起钉住：键名被改成 `cells`（与 Task 4 的「表列字母 → 单元格值」
        契约撞名，apply_diff 会当成列字母拼出非法 SQL），以及值被置空
        （新建出来的账户会丢掉表里所有列）。
        """
        from huguan_dashboard import build_diff, parse_row
        db, u1, _ = self._prepare(client)
        db.execute("INSERT INTO mcc(name, mcc_id) VALUES('NEW-MCC','9')")
        db.commit()
        mcc_id = db.execute("SELECT id FROM mcc WHERE name='NEW-MCC'").fetchone()["id"]
        rows = [dict(parse_row(["", "", "NEW-DB", "NEW-MCC", "", "", "张三", "",
                                "Asia/Shanghai"], "gg"), row=2)]
        item = build_diff(db, rows, "gg")["to_create"][0]
        assert "db_values" in item and "cells" not in item
        dv = item["db_values"]
        assert dv["mcc_id"] == mcc_id          # 值必须在
        assert dv["timezone"] == "Asia/Shanghai"
        assert dv["_is_dead"] is False
        db.close()

    def test_agent_namespace_is_platform_scoped(self, client):
        """代理解析必须按平台隔离：GG 的表不能挂到 TT 的代理上（反之亦然）。

        两边的查名 SQL 分别是 `_SQL_AGENT_GG` / `_SQL_AGENT_TT`，写反了不会报错
        —— 只会把账户静默挂到**另一个平台**的同名代理上。
        """
        from huguan_dashboard import build_diff, parse_row
        db, u1, _ = self._prepare(client)
        _seed_account(db, "AG-GG", u1, acquired_date="")
        _seed_tt_account(db, "AG-TT", u1)
        db.execute("INSERT INTO agents(name, platform) VALUES('张三代理','gg')")
        db.execute("INSERT INTO agents(name, platform) VALUES('TT代理','tt')")
        db.commit()
        gg_id = db.execute("SELECT id FROM agents WHERE platform='gg'").fetchone()["id"]
        tt_id = db.execute("SELECT id FROM agents WHERE platform='tt'").fetchone()["id"]
        # GG 的表里写了 TT 侧的代理名 ⇒ 查不到，记警告，不落库
        gg_diff = build_diff(db, [dict(parse_row(
            ["", "", "AG-GG", "", "", "TT代理", "张三"], "gg"), row=2)], "gg")
        assert gg_diff["to_update"] == []
        assert any("TT代理" in w["message"] for w in gg_diff["warnings"])
        # 反向：TT 的表里写 GG 侧代理名 ⇒ 同样不落库
        tt_row = ["", "", "AG-TT", "", "", "张三代理", "", "", "", "", "", "", ""]
        tt_diff = build_diff(db, [dict(parse_row(tt_row, "tt"), row=2)], "tt")
        assert tt_diff["to_update"] == []
        assert any("张三代理" in w["message"] for w in tt_diff["warnings"])
        # 各自命中的正例：GG 用 gg 代理、TT 用 tt 代理（不能用上面那两行，那两行
        # 刻意写的是对侧平台的代理名）
        gg_ok = build_diff(db, [dict(parse_row(
            ["", "", "AG-GG", "", "", "张三代理", "张三"], "gg"), row=2)], "gg")
        assert gg_ok["to_update"][0]["fields"]["agent_id"] == gg_id
        tt_row_ok = ["", "", "AG-TT", "", "", "TT代理", "", "", "", "", "", "", ""]
        tt_ok = build_diff(db, [dict(parse_row(tt_row_ok, "tt"), row=2)], "tt")
        assert tt_ok["to_update"][0]["fields"]["agent_id"] == tt_id
        db.close()

    def test_duplicate_account_id_rows_are_deduped(self, client):
        """同一账户ID 在表里出现两行 ⇒ 首行生效，后续行记警告。

        不去重的话两行都会进 `to_create`，落库阶段第二行撞唯一约束，整批报错。
        """
        from huguan_dashboard import build_diff, parse_row
        db, u1, _ = self._prepare(client)
        rows = [
            dict(parse_row(["", "", "DUP-ROW", "", "", "", "张三"], "gg"), row=2),
            dict(parse_row(["", "", "DUP-ROW", "", "", "", "张三"], "gg"), row=5),
        ]
        diff = build_diff(db, rows, "gg")
        assert len(diff["to_create"]) == 1
        assert diff["to_create"][0]["row"] == 2          # 首次出现的那行
        assert diff["summary"]["total_in_sheet"] == 2    # 表里确实有两行，不虚报
        assert any(w["row"] == 5 and "DUP-ROW" in w["message"] for w in diff["warnings"])
        db.close()

    def test_update_item_lists_columns_that_will_be_cleared(self, client):
        """新值为空的列必须进 `clears`，且 summary 汇总计数。

        清空不可逆：首次同步前户管要能一眼看到「将清空多少列」，而不是在几百行差异里
        自己发现 acquired_date 被清掉了。新建账户的空列**不算**清空（那是「不填」）。
        """
        from huguan_dashboard import build_diff, parse_row
        db, u1, _ = self._prepare(client)
        _seed_account(db, "CLR-1", u1, acquired_date="2026-01-01", timezone="Asia/Shanghai")
        diff = build_diff(db, [dict(parse_row(["", "", "CLR-1"], "gg"), row=2)], "gg")
        item = diff["to_update"][0]
        assert item["clears"] == ["acquired_date", "timezone"]   # sorted，两个都被清
        assert diff["summary"]["clears"] == 2
        # 新建账户的空列不产生 clears
        new_diff = build_diff(db, [dict(parse_row(["", "", "CLR-NEW"], "gg"), row=3)], "gg")
        assert new_diff["to_create"][0].get("clears") is None
        assert new_diff["summary"]["clears"] == 0
        db.close()

    def test_to_create_path_is_read_only_with_new_status_name(self, client):
        """新建账户 + 系统里没有的状态名 ⇒ dry_run 只读也必须守住这条路径。

        I1（dry_run 不改库）在 `build_diff` 里有两处 `_collect_updates(...,
        create_missing=False)`（`to_create` 一处、`to_update` 一处），但原先只有更新
        路径被钉住：删掉 `to_update` 那处的开关会红 3 条，删掉 `to_create` 这处的
        **81 条全绿** —— 那个 Critical 级修复只覆盖了一半。对照行：库里没有 `N1-NEW`，
        必然走 to_create 分支；K 列（GG 状态列，index 10）写的名字系统里不存在 ⇒
        该走 `pending_status`，且此刻（含调用方收尾 commit 之后）都不得建行。
        """
        from huguan_dashboard import build_diff, parse_row
        db, _, _ = self._prepare(client)
        rows = [dict(parse_row(["", "", "N1-NEW", "", "", "", "张三", "", "", "", "全新状态N1"],
                               "gg"), row=2)]
        assert db.execute("SELECT COUNT(*) AS n FROM account_statuses").fetchone()["n"] == 0
        diff = build_diff(db, rows, "gg")
        db.commit()      # 调用方正常收尾的提交：不该让任何东西冒出来
        assert db.execute("SELECT COUNT(*) AS n FROM account_statuses").fetchone()["n"] == 0
        assert len(diff["to_create"]) == 1
        assert diff["to_create"][0]["pending_status"] == "全新状态N1"
        db.close()

    def test_clears_ignores_columns_that_were_already_blank(self, client):
        """`clears` 必须取自 `changed`，不能取自 `fields`。

        表里空着、库里**也**空着的文本列：它在 `fields` 里（值为 `""`），但不构成任何
        真实变更、已被 `_same_as_existing` 过滤掉。取 `fields` 会把这些「本来就空」的列
        也算进「将清空」，让确认弹窗**虚报**清空规模（户管会以为自己要丢数据）。
        对照构造：库里 acquired_date / timezone 本来就是 `""`，表里 A / I 列也空 ⇒
        两列都不该进 clears。为让该行真的产出一条 to_update，K 列写一个系统里没有的
        状态名（pending 也算真实变更）。
        """
        from huguan_dashboard import build_diff, parse_row
        db, u1, _ = self._prepare(client)
        _seed_account(db, "SRC-1", u1, acquired_date="", timezone="")
        rows = [dict(parse_row(["", "", "SRC-1", "", "", "", "张三", "", "", "", "全新状态SRC"],
                               "gg"), row=2)]
        diff = build_diff(db, rows, "gg")
        assert len(diff["to_update"]) == 1          # 非空，下面的断言才有意义
        item = diff["to_update"][0]
        assert item["pending_status"] == "全新状态SRC"
        assert item["fields"] == {}                 # 两列都是空对空，无真实变更
        assert item["clears"] == []                 # 取 `fields` 会误报这两列
        assert diff["summary"]["clears"] == 0
        db.close()

    def test_tt_clears_are_sorted_not_in_field_order(self, client):
        """TT 的 `clears` 必须是字典序，不是 `_PLAIN_TEXT_FIELDS` 的插入序。

        GG 的 `_PLAIN_TEXT_FIELDS["gg"]` 恰好是 `("acquired_date", "timezone")`，
        插入序 = 字典序，所以把 `sorted()` 改成 `list()` 在 GG 上永远是绿的。TT 的插入序
        是 `(acquired_date, country, timezone, consumption, remark)`，与字典序不同 ——
        必须用 TT 造一条**多列同时被清空**的用例才钉得住。列下标以 COLUMN_SPEC 为准：
        A=0 acquired_date、E=4 country、H=7 timezone、J=9 consumption、M=12 remark。
        """
        from huguan_dashboard import build_diff, parse_row
        db, u1, _ = self._prepare(client)
        _seed_tt_account(db, "CLR-TT", u1, acquired_date="2026-01-01", country="US",
                         timezone="Asia/Shanghai", consumption="100", remark="备注")
        row = [""] * 13
        row[2] = "CLR-TT"                # C 列账户ID（定位键走 advertiser_id）
        diff = build_diff(db, [dict(parse_row(row, "tt"), row=2)], "tt")
        assert len(diff["to_update"]) == 1
        assert diff["to_update"][0]["clears"] == [
            "acquired_date", "consumption", "country", "remark", "timezone"]
        assert diff["summary"]["clears"] == 5
        db.close()

    def test_existing_status_lands_in_fields_with_no_pending(self, client):
        """系统里**已有**该状态名 ⇒ 落成 `fields["status_id"]`，`pending_status` 为 None。

        这是同步里最常见的档（状态名系统里已有），但此前经 `build_diff` 零覆盖：删掉
        `_collect_updates` 里的 `out["status_id"] = sid` 全绿 81 条，而该行被删掉后
        「已有状态」这一档就整条失效（field 丢失 → 无变更 → 该行不进 to_update）。
        """
        from huguan_dashboard import build_diff, parse_row
        db, u1, _ = self._prepare(client)
        _seed_account(db, "EX-1", u1, acquired_date="")
        db.execute("INSERT INTO account_statuses(name, owner_id, platform) "
                   "VALUES('已有状态', ?, 'gg')", (u1,))
        db.commit()
        sid = db.execute("SELECT id FROM account_statuses WHERE name='已有状态'"
                         ).fetchone()["id"]
        rows = [dict(parse_row(["", "", "EX-1", "", "", "", "张三", "", "", "", "已有状态"],
                               "gg"), row=2)]
        diff = build_diff(db, rows, "gg")
        assert len(diff["to_update"]) == 1
        item = diff["to_update"][0]
        assert item["fields"]["status_id"] == sid
        assert item["pending_status"] is None
        db.close()

    def test_blank_owner_row_produces_no_warning(self, client):
        """运营列与重新分配列**都空**的表行，不得产生任何警告（尤其归属相关的噪音）。

        `if want_owner_name:` 是空归属的短路；改成 `if True:` 时每个空白归属的行都会多出
        一条 `运营「」无法识别，已跳过归属变更` 的噪音警告（`resolve_owner_id("")` 返回
        None）。`test_blank_owner_keeps_existing_owner` 只断言 `owner_changes == []`，
        不看 warnings，钉不住这条不变量。该行其余列全空、账户已存在且未软删，所以
        正常情况下它是**干净**的：任何 warning 都属噪音。
        """
        from huguan_dashboard import build_diff, parse_row
        db, u1, _ = self._prepare(client)
        _seed_account(db, "OWN-5", u1)
        diff = build_diff(db, [dict(parse_row(["", "", "OWN-5"], "gg"), row=2)], "gg")
        assert diff["warnings"] == []
        db.close()
