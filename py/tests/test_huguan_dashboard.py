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
