"""FB 户管看板（子项目 ②）测试。

设计见 docs/superpowers/specs/2026-10-06-fb-huguan-dashboard-design.md。
本文件不打真实 Google API。
"""
import pytest

import database
import huguan_dashboard as hd


class TestPlatformSkeleton:
    def test_platforms_includes_fb(self):
        assert hd.PLATFORMS == ("gg", "tt", "fb")

    def test_table_for_platform_has_all_three(self):
        assert hd._TABLE_FOR_PLATFORM["gg"] == "accounts"
        assert hd._TABLE_FOR_PLATFORM["tt"] == "tt_accounts"
        assert hd._TABLE_FOR_PLATFORM["fb"] == "fb_accounts"

    def test_table_lookup_raises_on_unknown_platform(self):
        """缺键必须 KeyError —— 不能像二元 else 那样静默回落 GG 表。"""
        with pytest.raises(KeyError):
            hd._TABLE_FOR_PLATFORM["fbx"]

    def test_row_sql_has_all_three(self):
        for p in hd.PLATFORMS:
            assert p in hd._ROW_SQL, p

    def test_fb_row_sql_selects_from_fb_accounts(self):
        assert "FROM fb_accounts" in hd._FB_ROW_SQL

    def test_fb_row_sql_joins_primary_bm_only(self):
        """主 BM 的 join 必须带 is_primary=1，否则多 BM 账户会让行数翻倍。"""
        assert "ab.is_primary = 1" in hd._FB_ROW_SQL


class TestFbColumnSpec:
    def test_seventeen_columns(self):
        assert len(hd.COLUMN_SPEC["fb"]) == 17
        letters = [c[0] for c in hd.COLUMN_SPEC["fb"]]
        assert letters == [chr(ord("A") + i) for i in range(17)]

    def test_writable_readable_flags(self):
        flags = {c[0]: (c[3], c[4]) for c in hd.COLUMN_SPEC["fb"]}
        # B 操作人与 D 资产UID：写但不读
        assert flags["B"] == (True, False)
        assert flags["D"] == (True, False)
        # I 接户运营：只读回 + 定向写，不参与批量回写
        assert flags["I"] == (False, True)
        # 其余全部双向
        for col in "ACEFGHJKLMNOPQ":
            assert flags[col] == (True, True), col

    def test_key_and_owner_cols(self):
        assert hd.KEY_COL["fb"] == "D"
        assert hd.OWNER_COL["fb"] == "J"
        assert hd.READ_RANGE["fb"] == "A:Q"
        assert hd.ACCOUNT_KEY_FIELD["fb"] == "account_id"

    def test_owner_channel_col_has_no_fb_key(self):
        """FB 刻意不登记 —— 见 spec §6.5。"""
        assert "fb" not in hd.OWNER_CHANNEL_COL

    def test_cells_for_row_excludes_column_i(self):
        """cells_for_row 产出 = A:Q 除去 I。

        订正：brief/plan 原文写的是 set("ACDEFGHJKLMNOPQ")（15 个字母，漏了 B），
        但 B 操作人 writable=True（见 test_writable_readable_flags），cells 必然含 B；
        设计文档 §131 亦写明「产出 = writable=True 的列，即 A:Q 除去 I」（16 列）。
        原串是笔误，此处补回 B 以还原用例自身声明的意图。
        """
        row = {c[2]: "x" for c in hd.COLUMN_SPEC["fb"] if c[2]}
        row["account_id"] = "123"
        cells = hd.cells_for_row(row, "fb")
        assert "I" not in cells
        assert set(cells) == set("ABCDEFGHJKLMNOPQ")
