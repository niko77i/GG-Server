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

        这三条以前会 AttributeError 炸成 500。
        注意 `sheet_name` 给数字**不算**畸形：按全局约束与 spreadsheet_id 一致地
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
