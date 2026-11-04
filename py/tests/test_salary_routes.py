"""薪资路由测试：配置缺失 / 归属校验 / 参数校验 / 明细返回。"""

import salary_service

AGG = {
    "rows_total": 3,
    "rows_counted": 2,
    "rows_skipped_empty_k": 1,
    "rows_invalid_k": 0,
    "rows_missing_f": 0,
    "rows_m_missing": 0,
    "agency_fee": 15000.0,
    "net_value": 10000.0,
    "spend": 300000.0,
    "core": 25000.0,
    "sheet_n_sum": 25000.0,
    "latest_date": "2026-11-03",
    "by_date": [],
    "warnings": [],
    "sheet_name": "Sheet1",
    "spreadsheet_title": "卡尔2026.11",
}


def _configure_sheet(client, headers, sid="SID1", name="11月做表"):
    resp = client.post("/api/config/google-sheets", headers=headers, json={
        "sheets": [{"id": "m1", "spreadsheet_id": sid, "spreadsheet_name": name}],
        "active_id": "m1",
    })
    assert resp.status_code == 200


class TestOverview:
    def test_no_sheet_configured(self, client, auth_headers):
        resp = client.get("/api/salary/overview", headers=auth_headers)
        assert resp.status_code == 400
        assert "个人中心" in resp.get_json()["error"]

    def test_rejects_spreadsheet_outside_config(self, client, auth_headers):
        _configure_sheet(client, auth_headers)
        resp = client.get("/api/salary/overview?spreadsheet_id=OTHER",
                          headers=auth_headers)
        assert resp.status_code == 403
        assert "不在你的配置里" in resp.get_json()["error"]

    def test_success_returns_aggregates_and_default_salary(self, client, auth_headers, monkeypatch):
        _configure_sheet(client, auth_headers)
        monkeypatch.setattr(salary_service, "read_and_aggregate", lambda sid: dict(AGG))

        resp = client.get("/api/salary/overview?spreadsheet_id=SID1", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["success"] is True
        assert data["aggregates"]["latest_date"] == "2026-11-03"
        assert data["salary"]["core"] == 25000
        assert data["salary"]["base_salary"] == 6000
        # overview 的默认参数是「成本 0 / 汇率 6.6」⇒ 利润 25000、提成 2500
        assert data["salary"]["total"] == 6000 + (900 + 2500) * 6.6
        assert data["defaults"]["usdt_rate"] == 6.6
        assert data["defaults"]["base_salary"] == 6000
        assert data["defaults"]["base_salary_options"] == [4000, 6000, 8000, 10000]

    def test_default_base_salary_is_6000_even_in_low_tier(self, client, auth_headers, monkeypatch):
        """下拉默认固定 6000（用户 2026-11-04 指定），不随基数自动变；自动档只作提示。"""
        _configure_sheet(client, auth_headers)
        low = dict(AGG, agency_fee=830.0, net_value=1276.0, spend=12950.0,
                   core=2106.0, sheet_n_sum=2106.0)
        monkeypatch.setattr(salary_service, "read_and_aggregate", lambda sid: low)

        resp = client.get("/api/salary/overview?spreadsheet_id=SID1", headers=auth_headers)
        data = resp.get_json()
        assert data["defaults"]["base_salary"] == 6000
        assert data["salary"]["base_salary"] == 6000
        assert data["salary"]["base_salary_auto"] == 4000  # 提示仍按基数
        assert data["salary"]["base_salary_auto_band"] == "0-1万"

    def test_uses_active_sheet_when_id_omitted(self, client, auth_headers, monkeypatch):
        _configure_sheet(client, auth_headers)
        seen = {}

        def _fake(sid):
            seen["sid"] = sid
            return dict(AGG)

        monkeypatch.setattr(salary_service, "read_and_aggregate", _fake)
        resp = client.get("/api/salary/overview", headers=auth_headers)
        assert resp.status_code == 200
        assert seen["sid"] == "SID1"


class TestCompute:
    def test_matches_documented_example(self, client, auth_headers):
        resp = client.post("/api/salary/compute", headers=auth_headers, json={
            "agency_fee": 15000, "net_value": 10000, "spend": 300000,
            "cost": 2000, "base_salary": 6000, "usdt_rate": 6.6,
        })
        assert resp.status_code == 200
        s = resp.get_json()["salary"]
        assert s["total"] == 27120
        assert s["spend_bonus"] == 900
        assert s["profit_bonus"] == 2300

    def test_base_salary_omitted_auto_tiers(self, client, auth_headers):
        resp = client.post("/api/salary/compute", headers=auth_headers, json={
            "agency_fee": 40000, "net_value": 0, "spend": 0,
        })
        s = resp.get_json()["salary"]
        assert s["base_salary"] == 10000  # 基数 4 万 → 新档 10000

    def test_negative_net_value_allowed(self, client, auth_headers):
        resp = client.post("/api/salary/compute", headers=auth_headers, json={
            "agency_fee": 20000, "net_value": -5000, "spend": 0,
        })
        assert resp.status_code == 200
        assert resp.get_json()["salary"]["profit_rate"] == 0.01

    def test_rejects_base_salary_outside_options(self, client, auth_headers):
        resp = client.post("/api/salary/compute", headers=auth_headers, json={
            "agency_fee": 1, "net_value": 1, "spend": 1, "base_salary": 5000,
        })
        assert resp.status_code == 400
        assert "底薪只能" in resp.get_json()["error"]

    def test_allows_negative_spend_from_sheet(self, client, auth_headers):
        """聚合值可能为负（表里负 K / 冲正），不能因此 400 把页面卡在旧数字上。"""
        resp = client.post("/api/salary/compute", headers=auth_headers, json={
            "agency_fee": 1, "net_value": 1, "spend": -1,
        })
        assert resp.status_code == 200
        assert resp.get_json()["salary"]["spend"] == -1

    def test_rejects_non_object_body(self, client, auth_headers):
        """非 dict 请求体（列表/字符串）不能直接 500。"""
        resp = client.post("/api/salary/compute", headers=auth_headers, json=[1, 2])
        assert resp.status_code == 400
        assert "JSON 对象" in resp.get_json()["error"]

    def test_error_uses_chinese_label(self, client, auth_headers):
        resp = client.post("/api/salary/compute", headers=auth_headers, json={
            "agency_fee": "abc", "net_value": 1, "spend": 1,
        })
        assert resp.status_code == 400
        assert "代投费" in resp.get_json()["error"]

    def test_rejects_non_positive_rate(self, client, auth_headers):
        resp = client.post("/api/salary/compute", headers=auth_headers, json={
            "agency_fee": 1, "net_value": 1, "spend": 1, "usdt_rate": 0,
        })
        assert resp.status_code == 400
        assert "汇率" in resp.get_json()["error"]

    def test_requires_auth(self, client):
        resp = client.post("/api/salary/compute", json={"agency_fee": 1})
        assert resp.status_code == 401
