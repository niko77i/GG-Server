"""读表聚合测试：K 空行跳过、最新日期、数字/日期解析、口径告警。"""

import salary_service as ss


def _row(date="", f="", k="", l="", m="", n=""):
    """按做表 A–N 布局造一行（只填关心的列，其余留空）。"""
    row = [""] * 14
    row[0] = date
    row[5] = f
    row[10] = k
    row[11] = l
    row[12] = m
    row[13] = n
    return row


class TestParseNumber:
    def test_common_shapes(self):
        assert ss.parse_number("1,234.56") == 1234.56
        assert ss.parse_number(" 88 ") == 88.0
        assert ss.parse_number("6%") == 0.06
        assert ss.parse_number(12) == 12.0
        assert ss.parse_number("") is None
        assert ss.parse_number(None) is None
        assert ss.parse_number("#VALUE!") is None
        assert ss.parse_number("#DIV/0!") is None

    def test_bool_is_not_number(self):
        assert ss.parse_number(True) is None


class TestParseDateCell:
    def test_iso_and_slash(self):
        assert ss.parse_date_cell("2026-11-03") == "2026-11-03"
        assert ss.parse_date_cell("2026/11/3") == "2026-11-03"
        assert ss.parse_date_cell("2026.11.03") == "2026-11-03"

    def test_excel_serial(self):
        # UNFORMATTED_VALUE 下日期是序列号：45658 = 2025-01-01
        assert ss.parse_date_cell(45658) == "2025-01-01"
        assert ss.parse_date_cell(46000) != ""

    def test_serial_as_text(self):
        # 表格里存成文本的序列号也要转，否则前端显示 45658
        assert ss.parse_date_cell("45658") == "2025-01-01"

    def test_small_number_is_not_a_date(self):
        # 旧实现把任意 1..90000 的数字都当序列号：100 → 1900-04-09，比原样显示更误导
        assert ss.parse_date_cell(100) == "100"

    def test_empty(self):
        assert ss.parse_date_cell("") == ""
        assert ss.parse_date_cell(None) == ""


class TestPercentRatio:
    def test_shapes(self):
        assert ss._percent_ratio("6%") == 0.06
        assert ss._percent_ratio(0.06) == 0.06
        assert ss._percent_ratio(6) == 0.06

    def test_one_means_one_percent(self):
        """`L=1`：数字即百分数的口径下是 1%（旧实现当成 100%，1000×1=1000）。"""
        assert ss._percent_ratio(1) == 0.01


class TestAggregateRows:
    def test_skips_rows_without_k_and_tracks_latest_date(self):
        rows = [
            _row("2026-11-01", f=1000, k=800, l="10%", m=100, n=300),
            _row("2026-11-02", f=2000, k="", l="10%", m=200, n=""),   # K 未填 → 跳过
            _row("2026-11-03", f=3000, k=2500, l="10%", m=300, n=800),
        ]
        agg = ss.aggregate_rows(rows)
        assert agg["rows_counted"] == 2
        assert agg["rows_skipped_empty_k"] == 1
        assert agg["agency_fee"] == 400          # 100 + 300
        assert agg["net_value"] == 700           # (1000-800) + (3000-2500)
        assert agg["spend"] == 3300              # 800 + 2500
        assert agg["core"] == 1100               # 400 + 700
        assert agg["latest_date"] == "2026-11-03"
        assert agg["warnings"] == []

    def test_latest_date_ignores_rows_without_k(self):
        rows = [
            _row("2026-11-01", f=1000, k=800, m=100, n=300),
            _row("2026-11-09", f=2000, k="", m=200, n=""),
        ]
        agg = ss.aggregate_rows(rows)
        assert agg["latest_date"] == "2026-11-01"

    def test_by_date_groups(self):
        rows = [
            _row("2026-11-01", f=1000, k=800, m=100, n=300),
            _row("2026-11-01", f=500, k=400, m=50, n=150),
            _row("2026-11-02", f=2000, k=1500, m=200, n=700),
        ]
        agg = ss.aggregate_rows(rows)
        assert [g["date"] for g in agg["by_date"]] == ["2026-11-01", "2026-11-02"]
        assert agg["by_date"][0]["rows"] == 2
        assert agg["by_date"][0]["spend"] == 1200

    def test_missing_m_falls_back_to_f_times_l(self):
        rows = [_row("2026-11-01", f=1000, k=800, l="5%", m="", n="")]
        agg = ss.aggregate_rows(rows)
        assert agg["agency_fee"] == 50  # 1000 × 5%
        assert agg["rows_m_missing"] == 1
        assert any("M 列无值" in w for w in agg["warnings"])

    def test_n_mismatch_warns(self):
        # N 手工改成 999，与 F−K+M=300 不符
        rows = [_row("2026-11-01", f=1000, k=800, m=100, n=999)]
        agg = ss.aggregate_rows(rows)
        assert any("N 列合计" in w for w in agg["warnings"])

    def test_invalid_k_is_skipped_and_warned(self):
        rows = [_row("2026-11-01", f=1000, k="abc", m=100, n=300)]
        agg = ss.aggregate_rows(rows)
        assert agg["rows_counted"] == 0
        assert agg["rows_invalid_k"] == 1
        assert any("不是数字" in w for w in agg["warnings"])

    def test_header_row_in_k_does_not_warn(self):
        """表头行（K='平台实际'）不应给每次计算都挂一条「K 不是数字」告警。"""
        rows = [_row("日期", f="报给客户", k="平台实际", m="代投费", n="利润"),
                _row("2026-11-01", f=1000, k=800, m=100, n=300)]
        agg = ss.aggregate_rows(rows)
        assert agg["rows_counted"] == 1
        assert agg["rows_header_k"] == 1
        assert agg["rows_invalid_k"] == 0
        assert agg["warnings"] == []

    def test_missing_f_counts_as_zero(self):
        rows = [_row("2026-11-01", f="", k=800, m=100, n="")]
        agg = ss.aggregate_rows(rows)
        assert agg["net_value"] == -800
        assert agg["rows_missing_f"] == 1
        assert any("F 为空" in w for w in agg["warnings"])

    def test_empty_sheet(self):
        agg = ss.aggregate_rows([])
        assert agg["rows_counted"] == 0
        assert agg["latest_date"] == ""
        assert agg["core"] == 0

    def test_zero_k_is_counted(self):
        """K=0 是「有值」，不能当未填跳过（真机表尾就有这种行）。"""
        agg = ss.aggregate_rows([_row("2026-11-01", f=0, k=0, m=0, n=0)])
        assert agg["rows_counted"] == 1
        assert agg["rows_skipped_empty_k"] == 0

    def test_negative_k_counts(self):
        """表里出现负 K（冲正/退款）时照实计入，不吞行。"""
        agg = ss.aggregate_rows([_row("2026-11-01", f=1000, k=-200, m=100, n=1300)])
        assert agg["rows_counted"] == 1
        assert agg["spend"] == -200
        assert agg["net_value"] == 1200


class TestReadAndAggregate:
    """读表这道闸：必须用第一个工作表 + UNFORMATTED_VALUE。"""

    def test_reads_first_sheet_with_unformatted_values(self, monkeypatch):
        import google_sheets_service as gs
        import main

        captured = {}

        monkeypatch.setattr(gs, "build_service", lambda path: object())
        monkeypatch.setattr(gs, "get_spreadsheet_info", lambda svc, sid: {
            "title": "卡尔2026.11",
            "sheets": [{"name": "工作表1"}, {"name": "其他"}],
        })

        def _read(svc, sid, name, rng, value_render_option=None):
            captured.update(sid=sid, name=name, rng=rng, opt=value_render_option)
            return [_row("2026-11-01", f=1000, k=800, m=100, n=300)]

        monkeypatch.setattr(gs, "read_sheet_values", _read)
        monkeypatch.setitem(main._GOOGLE_SHEETS_CONFIG, "credentials_path", "dummy.json")

        agg = ss.read_and_aggregate("SID1")

        # 漏传 UNFORMATTED_VALUE 会让千分位/日期字符串混进来 ⇒ 金额全错但测试照样绿
        assert captured["opt"] == "UNFORMATTED_VALUE"
        assert captured["name"] == "工作表1"
        assert captured["rng"] == "A:N"
        assert agg["sheet_name"] == "工作表1"
        assert agg["latest_date"] == "2026-11-01"
        assert agg["core"] == 300
