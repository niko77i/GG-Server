"""薪资计算纯函数测试（档位边界 / 成本 / 汇率 / 负增值）。"""

import salary_calc as sc


class TestBaseSalary:
    """底薪：左闭右开，4 万以上 10000（2026-11-04 更正）。"""

    def test_tiers(self):
        cases = [
            (0, 4000, "0-1万"),
            (9999.99, 4000, "0-1万"),
            (10000, 6000, "1-3万"),
            (29999.99, 6000, "1-3万"),
            (30000, 8000, "3-4万"),
            (39999.99, 8000, "3-4万"),
            (40000, 10000, "4万以上"),
            (100000, 10000, "4万以上"),
        ]
        for core, want, band in cases:
            got, got_band = sc.base_salary_for(core)
            assert (got, got_band) == (want, band), f"基数 {core} 应落 {want}"


class TestSpendRate:
    """消耗：全额按档位，恰好 20 万走 0.003。"""

    def test_tiers(self):
        assert sc.spend_rate_for(0) == 0.002
        assert sc.spend_rate_for(199999.99) == 0.002
        assert sc.spend_rate_for(200000) == 0.003
        assert sc.spend_rate_for(1000000) == 0.003


class TestProfitRate:
    """利润提成费率看纯增值；负增值单独 0.01。"""

    def test_tiers(self):
        cases = [
            (-1, 0.01, "负增值"),
            (-100000, 0.01, "负增值"),
            (0, 0.10, "0-2万"),
            (19999.99, 0.10, "0-2万"),
            (20000, 0.12, "2-3万"),
            (29999.99, 0.12, "2-3万"),
            (30000, 0.15, "3-4万"),
            (40000, 0.18, "4万以上"),
        ]
        for net, want, band in cases:
            got, got_band = sc.profit_rate_for(net)
            assert (got, got_band) == (want, band), f"纯增值 {net} 应用 {want}"


class TestComputeSalary:
    """整份明细：算式与文档算例对齐。"""

    def test_documented_example(self):
        """代投 15000 + 纯增值 10000，成本 2000，消耗 30 万，汇率 6.6 → 27120 元。"""
        s = sc.compute_salary(agency_fee=15000, net_value=10000, spend=300000,
                              cost=2000, usdt_rate=6.6)
        assert s["core"] == 25000
        assert s["base_salary"] == 6000
        assert s["spend_rate"] == 0.003
        assert s["spend_bonus"] == 900
        assert s["profit"] == 23000
        assert s["profit_rate"] == 0.10
        assert s["profit_bonus"] == 2300
        assert s["usdt_total"] == 3200
        assert s["usdt_rmb"] == 21120
        assert s["total"] == 27120

    def test_negative_profit_bonus_is_zero_but_not_deducted(self):
        """成本高到利润为负：提成按 0，底薪照给。"""
        s = sc.compute_salary(agency_fee=10000, net_value=2000, spend=0,
                              cost=50000, usdt_rate=6.6)
        assert s["profit"] == -38000
        assert s["profit_base"] == 0
        assert s["profit_bonus"] == 0
        assert s["base_salary"] == 6000  # 基数 12000 → 1-3万档
        assert s["total"] == 6000

    def test_negative_net_value_uses_one_percent(self):
        s = sc.compute_salary(agency_fee=20000, net_value=-5000, spend=0, usdt_rate=6.6)
        assert s["core"] == 15000
        assert s["profit_rate"] == 0.01
        assert s["profit_bonus"] == 150.0
        assert s["base_salary"] == 6000

    def test_manual_base_salary_override(self):
        s = sc.compute_salary(agency_fee=15000, net_value=10000, spend=300000,
                              base_salary=10000, usdt_rate=6.6)
        assert s["base_salary"] == 10000
        assert s["manual_base_salary"] is True
        assert s["base_salary_auto"] == 6000  # 仍带出「按基数应落哪档」
        # 成本缺省 0 ⇒ 利润 25000 → 利润提成 2500；消耗提成 900
        assert s["usdt_total"] == 3400
        assert s["total"] == 10000 + 3400 * 6.6

    def test_zero_everything(self):
        s = sc.compute_salary(0, 0, 0)
        assert s["core"] == 0
        assert s["base_salary"] == 4000
        assert s["spend_bonus"] == 0
        assert s["profit_bonus"] == 0
        assert s["total"] == 4000
