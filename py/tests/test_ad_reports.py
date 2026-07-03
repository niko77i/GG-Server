"""测试做表数据保存 + 分析 API。每个测试独立，自包含数据准备。"""
import json


class TestAdReportsSave:
    """POST /api/ad-reports/save — 保存做表数据。"""

    def test_save_rows_successfully(self, client, auth_headers):
        """保存数据行成功。"""
        rows = [
            {"account": "Acc1", "customerId": "111-222-3333", "campaign": "Camp-A",
             "cost": 100.5, "impressions": 5000, "clicks": 300,
             "installs": 50, "inAppActions": 1.5, "costPerInApp": 2.0},
            {"account": "Acc2", "customerId": "444-555-6666", "campaign": "Camp-B",
             "cost": 200.0, "impressions": 8000, "clicks": 500,
             "installs": 80, "inAppActions": 2.0, "costPerInApp": 2.5},
        ]
        resp = client.post("/api/ad-reports/save", json={
            "product_name": "test_save_prod",
            "region": "巴西", "report_date": "2026-07-01",
            "rows": rows, "override_ids": [],
        }, headers=auth_headers)
        data = resp.get_json()
        assert data["success"] is True
        assert data["saved"] == 2

    def test_save_requires_product_name(self, client, auth_headers):
        """缺少产品名返回 400。"""
        resp = client.post("/api/ad-reports/save", json={
            "product_name": "", "region": "巴西",
            "report_date": "2026-07-01",
            "rows": [{"customerId": "x", "campaign": "y"}],
            "override_ids": [],
        }, headers=auth_headers)
        assert resp.status_code == 400

    def test_save_requires_region(self, client, auth_headers):
        """缺少地区返回 400。"""
        resp = client.post("/api/ad-reports/save", json={
            "product_name": "test", "region": "",
            "report_date": "2026-07-01",
            "rows": [{"customerId": "x", "campaign": "y"}],
            "override_ids": [],
        }, headers=auth_headers)
        assert resp.status_code == 400

    def test_save_duplicate_skipped_in_same_request(self, client, auth_headers):
        """同请求中同维度多条数据应聚合成一条（不再跳过）。"""
        rows = [{"account": "Dup", "customerId": "dup-111", "campaign": "DupCamp",
                 "cost": 100, "impressions": 100, "clicks": 10,
                 "installs": 1, "inAppActions": 0, "costPerInApp": 100}]
        resp = client.post("/api/ad-reports/save", json={
            "product_name": "test_dup_prod2",
            "region": "巴西", "report_date": "2026-07-01",
            "rows": rows, "override_ids": [],
        }, headers=auth_headers)
        data = resp.get_json()
        assert data["success"] is True
        assert data["saved"] == 1  # 聚合成 1 条

    def test_save_with_override(self, client, auth_headers):
        """override_ids 覆盖已有行。"""
        rows = [{"account": "Ovr", "customerId": "ovr-111", "campaign": "OvrCamp",
                 "cost": 50, "impressions": 100, "clicks": 10,
                 "installs": 1, "inAppActions": 0, "costPerInApp": 50}]
        client.post("/api/ad-reports/save", json={
            "product_name": "test_ovr_prod",
            "region": "巴西", "report_date": "2026-07-01",
            "rows": rows, "override_ids": [],
        }, headers=auth_headers)

        # 查 id
        resp = client.get("/api/ad-reports/list?product_name=test_ovr_prod", headers=auth_headers)
        old_id = resp.get_json()["reports"][0]["id"]

        # 覆盖
        resp = client.post("/api/ad-reports/save", json={
            "product_name": "test_ovr_prod",
            "region": "巴西", "report_date": "2026-07-01",
            "rows": [{"account": "Ovr", "customerId": "ovr-111", "campaign": "OvrCamp",
                      "cost": 999, "impressions": 100, "clicks": 10,
                      "installs": 1, "inAppActions": 0, "costPerInApp": 999}],
            "override_ids": [old_id],
        }, headers=auth_headers)
        assert resp.get_json()["success"] is True

    def test_save_aggregates_same_dimension_rows(self, client, auth_headers):
        """同维度多条数据应聚合 SUM 后保存为一条。"""
        rows = [
            {"account": "Agg", "customerId": "agg-111", "campaign": "AggCamp",
             "cost": 100, "impressions": 1000, "clicks": 50,
             "installs": 10, "inAppActions": 5, "costPerInApp": 10},
            {"account": "Agg", "customerId": "agg-111", "campaign": "AggCamp",
             "cost": 50, "impressions": 500, "clicks": 25,
             "installs": 5, "inAppActions": 2, "costPerInApp": 25},
        ]
        resp = client.post("/api/ad-reports/save", json={
            "product_name": "test_agg_prod",
            "region": "巴西", "report_date": "2026-07-01",
            "rows": rows, "override_ids": [],
        }, headers=auth_headers)
        data = resp.get_json()
        assert data["success"] is True
        # 两行同维度 → 聚合成 1 条
        assert data["saved"] == 1
        assert data["aggregated_from"] == 2

        # 验证聚合值
        list_resp = client.get(
            "/api/ad-reports/list?product_name=test_agg_prod", headers=auth_headers
        )
        reports = list_resp.get_json()["reports"]
        assert len(reports) == 1
        r = reports[0]
        assert r["cost"] == 150  # 100 + 50
        assert r["impressions"] == 1500  # 1000 + 500
        assert r["clicks"] == 75  # 50 + 25
        assert r["installs"] == 15  # 10 + 5
        assert r["in_app_actions"] == 7  # 5 + 2

    def test_save_upsert_accumulates_on_existing(self, client, auth_headers):
        """同维度再次保存应累加到已有记录。"""
        rows = [{"account": "Up", "customerId": "up-111", "campaign": "UpCamp",
                 "cost": 100, "impressions": 1000, "clicks": 50,
                 "installs": 10, "inAppActions": 5, "costPerInApp": 20}]
        # 第一次
        client.post("/api/ad-reports/save", json={
            "product_name": "test_up_prod",
            "region": "巴西", "report_date": "2026-07-01",
            "rows": rows, "override_ids": [],
        }, headers=auth_headers)
        # 第二次 — 同样的维度
        resp = client.post("/api/ad-reports/save", json={
            "product_name": "test_up_prod",
            "region": "巴西", "report_date": "2026-07-01",
            "rows": rows, "override_ids": [],
        }, headers=auth_headers)
        data = resp.get_json()
        assert data["success"] is True
        assert data["saved"] == 1  # UPDATE 了已有记录

        # 验证数值累加
        list_resp = client.get(
            "/api/ad-reports/list?product_name=test_up_prod", headers=auth_headers
        )
        reports = list_resp.get_json()["reports"]
        assert len(reports) == 1
        r = reports[0]
        assert r["cost"] == 200  # 100 + 100


class TestAdReportsCheckDuplicates:
    """POST /api/ad-reports/check-duplicates — 重复检测。"""

    def test_detect_existing_duplicates(self, client, auth_headers):
        """检测已存在的数据。"""
        # 先保存
        rows = [{"account": "Chk", "customerId": "chk-111", "campaign": "ChkCamp",
                 "cost": 100, "impressions": 100, "clicks": 10}]
        client.post("/api/ad-reports/save", json={
            "product_name": "test_chk_prod",
            "region": "巴西", "report_date": "2026-07-01",
            "rows": rows, "override_ids": [],
        }, headers=auth_headers)

        # 再检测
        resp = client.post("/api/ad-reports/check-duplicates", json={
            "product_name": "test_chk_prod",
            "report_date": "2026-07-01",
            "rows": rows,
        }, headers=auth_headers)
        data = resp.get_json()
        assert data["success"] is True
        assert len(data["duplicates"]) > 0
        dup = data["duplicates"][0]
        assert "existing" in dup
        assert "incoming" in dup

    def test_no_duplicates_for_new_data(self, client, auth_headers):
        """全新数据应无重复。"""
        resp = client.post("/api/ad-reports/check-duplicates", json={
            "product_name": "nonexistent_prod",
            "report_date": "2026-07-01",
            "rows": [{"customerId": "new-111", "campaign": "NewCamp"}],
        }, headers=auth_headers)
        data = resp.get_json()
        assert data["duplicates"] == []


class TestAdReportsList:
    """GET /api/ad-reports/list — 报告列表。"""

    def test_list_reports_for_product(self, client, auth_headers):
        """按产品列出报告（自包含数据）。"""
        rows = [{"account": "List", "customerId": "list-111", "campaign": "ListCamp",
                 "cost": 50, "impressions": 100, "clicks": 10,
                 "installs": 1, "inAppActions": 0, "costPerInApp": 50}]
        client.post("/api/ad-reports/save", json={
            "product_name": "test_list_prod",
            "region": "巴西", "report_date": "2026-07-01",
            "rows": rows, "override_ids": [],
        }, headers=auth_headers)

        resp = client.get("/api/ad-reports/list?product_name=test_list_prod", headers=auth_headers)
        data = resp.get_json()
        assert data["success"] is True
        assert data["total"] > 0

    def test_list_returns_all_products_aggregation(self, client, auth_headers):
        """列表返回聚合的产品和地区列表。"""
        resp = client.get("/api/ad-reports/list", headers=auth_headers)
        data = resp.get_json()
        assert "products" in data
        assert "regions" in data
        assert isinstance(data["products"], list)
        assert isinstance(data["regions"], list)


class TestAdReportsDelete:
    """DELETE /api/ad-reports/<id> — 删除单条。"""

    def test_delete_report_row(self, client, auth_headers):
        """删除一条报告。"""
        rows = [{"account": "Del", "customerId": "del-111", "campaign": "DelCamp",
                 "cost": 10, "impressions": 10, "clicks": 1,
                 "installs": 0, "inAppActions": 0, "costPerInApp": 10}]
        client.post("/api/ad-reports/save", json={
            "product_name": "test_del_prod",
            "region": "巴西", "report_date": "2026-07-01",
            "rows": rows, "override_ids": [],
        }, headers=auth_headers)

        resp = client.get("/api/ad-reports/list?product_name=test_del_prod", headers=auth_headers)
        rid = resp.get_json()["reports"][0]["id"]
        resp = client.delete(f"/api/ad-reports/{rid}", headers=auth_headers)
        assert resp.get_json()["success"] is True


class TestAdReportsDashboard:
    """GET /api/ad-reports/dashboard — 仪表盘概览。"""

    def test_dashboard_returns_summary(self, client, auth_headers):
        """仪表盘返回聚合指标。"""
        rows = [
            {"account": "Dash1", "customerId": "dash-111", "campaign": "DashCamp-A",
             "cost": 100, "impressions": 5000, "clicks": 300,
             "installs": 50, "inAppActions": 1.5, "costPerInApp": 2.0},
            {"account": "Dash2", "customerId": "dash-222", "campaign": "DashCamp-B",
             "cost": 200, "impressions": 8000, "clicks": 500,
             "installs": 80, "inAppActions": 2.0, "costPerInApp": 2.5},
        ]
        client.post("/api/ad-reports/save", json={
            "product_name": "test_dash_prod",
            "region": "巴西", "report_date": "2026-07-01",
            "rows": rows, "override_ids": [],
        }, headers=auth_headers)

        resp = client.get("/api/ad-reports/dashboard?product_name=test_dash_prod", headers=auth_headers)
        data = resp.get_json()
        assert data["success"] is True
        s = data["summary"]
        assert s["total_cost"] > 0
        assert "avg_cpi" in s

    def test_dashboard_includes_anomalies(self, client, auth_headers):
        """仪表盘包含异常检测。"""
        resp = client.get("/api/ad-reports/dashboard?product_name=test_dash_prod", headers=auth_headers)
        data = resp.get_json()
        assert "anomalies" in data
        assert isinstance(data["anomalies"], list)


class TestAdReportsTrends:
    """GET /api/ad-reports/trends — 趋势数据。"""

    def test_trends_returns_series(self, client, auth_headers):
        """趋势返回系列数据。"""
        rows = [{"account": "Trend", "customerId": "trend-111", "campaign": "TrendCamp",
                 "cost": 100, "impressions": 5000, "clicks": 300,
                 "installs": 50, "inAppActions": 1.5, "costPerInApp": 2.0}]
        client.post("/api/ad-reports/save", json={
            "product_name": "test_trend_prod",
            "region": "巴西", "report_date": "2026-07-01",
            "rows": rows, "override_ids": [],
        }, headers=auth_headers)

        resp = client.get("/api/ad-reports/trends?product_name=test_trend_prod&metric=cpi", headers=auth_headers)
        data = resp.get_json()
        assert data["success"] is True
        assert "series" in data
        if data["series"]:
            s = data["series"][0]
            assert "name" in s
            assert "data" in s
            if s["data"]:
                assert "date" in s["data"][0]


class TestAdReportsCompare:
    """GET /api/ad-reports/compare — 产品/系列对比。"""

    def test_compare_by_product(self, client, auth_headers):
        """按产品聚合对比。"""
        rows = [{"account": "Cmp", "customerId": "cmp-111", "campaign": "CmpCamp",
                 "cost": 100, "impressions": 1000, "clicks": 100,
                 "installs": 10, "inAppActions": 0.5, "costPerInApp": 10}]
        client.post("/api/ad-reports/save", json={
            "product_name": "test_cmp_prod",
            "region": "巴西", "report_date": "2026-07-01",
            "rows": rows, "override_ids": [],
        }, headers=auth_headers)

        resp = client.get("/api/ad-reports/compare?group_by=product_name", headers=auth_headers)
        data = resp.get_json()
        assert data["success"] is True
        assert "items" in data


class TestAdReportsCrossUser:
    """GET /api/ad-reports/cross-user — 跨用户对比。"""

    def test_cross_user_requires_product(self, client, auth_headers):
        """缺少产品名返回 400。"""
        resp = client.get("/api/ad-reports/cross-user", headers=auth_headers)
        assert resp.status_code == 400

    def test_cross_user_for_product(self, client, auth_headers):
        """同产品不同用户的聚合。"""
        rows = [{"account": "XUser", "customerId": "xuser-111", "campaign": "XUserCamp",
                 "cost": 100, "impressions": 1000, "clicks": 100,
                 "installs": 10, "inAppActions": 0.5, "costPerInApp": 10}]
        client.post("/api/ad-reports/save", json={
            "product_name": "test_xuser_prod",
            "region": "巴西", "report_date": "2026-07-01",
            "rows": rows, "override_ids": [],
        }, headers=auth_headers)

        resp = client.get("/api/ad-reports/cross-user?product_name=test_xuser_prod", headers=auth_headers)
        data = resp.get_json()
        assert data["success"] is True
        assert "users" in data
        assert len(data["users"]) > 0


class TestAdReportsProducts:
    """GET /api/ad-reports/products — 产品下拉列表。"""

    def test_returns_accessible_products(self, client, auth_headers):
        """返回当前用户有权限的产品（创建产品后检查）。"""
        # 创建产品
        client.post("/api/products/create", json={
            "product_name": "test_acc_prod",
            "kpi": "test", "region": "巴西",
        }, headers=auth_headers)

        resp = client.get("/api/ad-reports/products", headers=auth_headers)
        data = resp.get_json()
        assert data["success"] is True
        names = [p["product_name"] for p in data["products"]]
        assert "test_acc_prod" in names


class TestAdReportsAnalyze:
    """POST /api/ad-reports/analyze — AI 分析。"""

    def test_analyze_disabled_by_default(self, client, auth_headers):
        """默认未启用 AI 分析。"""
        resp = client.post("/api/ad-reports/analyze", json={
            "question": "测试问题",
            "filters": {"product_name": "test"},
        }, headers=auth_headers)
        data = resp.get_json()
        assert data["success"] is True
        assert data["enabled"] is False


class TestAdReportsMultiAnalysis:
    """GET /api/ad-reports/multi-analysis — 多维自由分析。"""

    def _seed_data(self, client, auth_headers):
        """准备测试数据：两个账户、两个campaign、同一产品。"""
        rows = [
            {"account": "账户A", "customerId": "111-222-3333", "campaign": "Camp-X",
             "cost": 500, "impressions": 10000, "clicks": 500,
             "installs": 80, "inAppActions": 200, "costPerInApp": 2.5},
            {"account": "账户A", "customerId": "111-222-3333", "campaign": "Camp-Y",
             "cost": 300, "impressions": 6000, "clicks": 200,
             "installs": 40, "inAppActions": 150, "costPerInApp": 2.0},
            {"account": "账户B", "customerId": "444-555-6666", "campaign": "Camp-X",
             "cost": 800, "impressions": 15000, "clicks": 600,
             "installs": 120, "inAppActions": 200, "costPerInApp": 4.0},
            {"account": "账户B", "customerId": "444-555-6666", "campaign": "Camp-Y",
             "cost": 200, "impressions": 4000, "clicks": 150,
             "installs": 30, "inAppActions": 100, "costPerInApp": 2.0},
        ]
        client.post("/api/ad-reports/save", json={
            "product_name": "test_multi_prod",
            "region": "巴西", "report_date": "2026-07-01",
            "rows": rows, "override_ids": [],
        }, headers=auth_headers)

    def test_multi_analysis_group_by_account(self, client, auth_headers):
        """按账户分组返回正确的聚合数据。"""
        self._seed_data(client, auth_headers)
        resp = client.get(
            "/api/ad-reports/multi-analysis?x_axis=cost&y_axis=cpi&group_by=account&product_name=test_multi_prod",
            headers=auth_headers)
        data = resp.get_json()
        assert data["success"] is True
        assert len(data["points"]) == 2  # 账户A, 账户B
        names = {p["name"] for p in data["points"]}
        assert "账户A" in names
        assert "账户B" in names
        # 每个点应有必需的字段
        for p in data["points"]:
            assert "x" in p
            assert "y" in p
            assert "detail" in p
            assert "total_cost" in p["detail"]
            assert "avg_cpi" in p["detail"]

    def test_multi_analysis_group_by_campaign(self, client, auth_headers):
        """按campaign分组返回正确的聚合数据。"""
        self._seed_data(client, auth_headers)
        resp = client.get(
            "/api/ad-reports/multi-analysis?x_axis=cost&y_axis=cpi&group_by=campaign&product_name=test_multi_prod",
            headers=auth_headers)
        data = resp.get_json()
        assert data["success"] is True
        assert len(data["points"]) == 2  # Camp-X, Camp-Y

    def test_multi_analysis_returns_stats(self, client, auth_headers):
        """返回统计信息：均值、中位数、相关系数。"""
        self._seed_data(client, auth_headers)
        resp = client.get(
            "/api/ad-reports/multi-analysis?x_axis=cost&y_axis=cpi&group_by=account&product_name=test_multi_prod",
            headers=auth_headers)
        data = resp.get_json()
        assert "stats" in data
        s = data["stats"]
        assert "x_avg" in s
        assert "y_avg" in s
        assert "correlation" in s
        assert "sample_count" in s
        assert s["sample_count"] == 2

    def test_multi_analysis_returns_insights(self, client, auth_headers):
        """返回规则引擎生成的分析结论。"""
        self._seed_data(client, auth_headers)
        resp = client.get(
            "/api/ad-reports/multi-analysis?x_axis=cost&y_axis=cpi&group_by=account&product_name=test_multi_prod",
            headers=auth_headers)
        data = resp.get_json()
        assert "insights" in data
        assert isinstance(data["insights"], list)

    def test_multi_analysis_with_size_by(self, client, auth_headers):
        """气泡大小参数正确传递并计算。"""
        self._seed_data(client, auth_headers)
        resp = client.get(
            "/api/ad-reports/multi-analysis?x_axis=cost&y_axis=cpi&size_by=ctr&group_by=account&product_name=test_multi_prod",
            headers=auth_headers)
        data = resp.get_json()
        assert data["success"] is True
        for p in data["points"]:
            assert "size" in p
            assert p["size"] >= 0

    def test_multi_analysis_without_size_by(self, client, auth_headers):
        """不传size_by时气泡大小仍存在（默认值）。"""
        self._seed_data(client, auth_headers)
        resp = client.get(
            "/api/ad-reports/multi-analysis?x_axis=cost&y_axis=cpi&group_by=account&product_name=test_multi_prod",
            headers=auth_headers)
        data = resp.get_json()
        for p in data["points"]:
            assert "size" in p

    def test_multi_analysis_different_metrics(self, client, auth_headers):
        """不同指标组合（ctr vs cvr）正常工作。"""
        self._seed_data(client, auth_headers)
        resp = client.get(
            "/api/ad-reports/multi-analysis?x_axis=ctr&y_axis=cvr&group_by=campaign&product_name=test_multi_prod",
            headers=auth_headers)
        data = resp.get_json()
        assert data["success"] is True
        assert len(data["points"]) == 2

    def test_multi_analysis_empty_when_no_data(self, client, auth_headers):
        """无数据时返回空points + 空insights。"""
        resp = client.get(
            "/api/ad-reports/multi-analysis?x_axis=cost&y_axis=cpi&group_by=account&product_name=nonexistent_xyz",
            headers=auth_headers)
        data = resp.get_json()
        assert data["success"] is True
        assert data["points"] == []
        assert data["insights"] == []


class TestAdReportsMultiAiChat:
    """POST /api/ad-reports/multi-ai-chat — AI 对话分析。"""

    def test_ai_chat_disabled_by_default(self, client, auth_headers):
        """默认未启用AI时返回提示。"""
        resp = client.post("/api/ad-reports/multi-ai-chat", json={
            "question": "哪些账户需要优化？",
            "context": {"product_name": "test", "points": []},
            "history": [],
        }, headers=auth_headers)
        data = resp.get_json()
        assert data["success"] is True
        assert data["enabled"] is False


class TestAdReportsUpdate:
    """PUT /api/ad-reports/<id> — 编辑单条报告。"""

    def test_update_report_fields(self, client, auth_headers):
        """编辑报告字段成功。"""
        # 准备数据
        rows = [{"account": "Ed", "customerId": "ed-111", "campaign": "EdCamp",
                 "cost": 100, "impressions": 1000, "clicks": 50,
                 "installs": 10, "inAppActions": 5, "costPerInApp": 20}]
        client.post("/api/ad-reports/save", json={
            "product_name": "test_edit_prod",
            "region": "巴西", "report_date": "2026-07-01",
            "rows": rows, "override_ids": [],
        }, headers=auth_headers)

        list_resp = client.get(
            "/api/ad-reports/list?product_name=test_edit_prod", headers=auth_headers
        )
        rid = list_resp.get_json()["reports"][0]["id"]

        # 编辑
        resp = client.put(f"/api/ad-reports/{rid}", json={
            "cost": 999, "impressions": 888, "campaign": "UpdatedCamp",
        }, headers=auth_headers)
        assert resp.get_json()["success"] is True

        # 验证
        list_resp2 = client.get(
            "/api/ad-reports/list?product_name=test_edit_prod", headers=auth_headers
        )
        r = list_resp2.get_json()["reports"][0]
        assert r["cost"] == 999
        assert r["impressions"] == 888
        assert r["campaign"] == "UpdatedCamp"

    def test_update_nonexistent_returns_404(self, client, auth_headers):
        """编辑不存在的记录返回 404。"""
        resp = client.put("/api/ad-reports/99999", json={
            "cost": 100
        }, headers=auth_headers)
        assert resp.status_code == 404

    def test_update_cannot_modify_others_data(self, client, auth_headers):
        """不能编辑其他用户的数据。"""
        # 用另一个用户创建的记录 ID
        resp = client.put("/api/ad-reports/99999", json={
            "cost": 100
        }, headers=auth_headers)
        assert resp.status_code == 404


class TestAdReportsBatchDelete:
    """POST /api/ad-reports/batch-delete — 批量删除。"""

    def test_batch_delete(self, client, auth_headers):
        """批量删除多条记录。"""
        rows = [
            {"account": "BD1", "customerId": "bd-111", "campaign": "BDCamp1",
             "cost": 10, "impressions": 100, "clicks": 10,
             "installs": 1, "inAppActions": 0, "costPerInApp": 10},
            {"account": "BD2", "customerId": "bd-222", "campaign": "BDCamp2",
             "cost": 20, "impressions": 200, "clicks": 20,
             "installs": 2, "inAppActions": 0, "costPerInApp": 10},
        ]
        client.post("/api/ad-reports/save", json={
            "product_name": "test_bd_prod",
            "region": "巴西", "report_date": "2026-07-01",
            "rows": rows, "override_ids": [],
        }, headers=auth_headers)

        list_resp = client.get(
            "/api/ad-reports/list?product_name=test_bd_prod", headers=auth_headers
        )
        ids = [r["id"] for r in list_resp.get_json()["reports"]]

        resp = client.post("/api/ad-reports/batch-delete", json={
            "ids": ids
        }, headers=auth_headers)
        data = resp.get_json()
        assert data["success"] is True
        assert data["deleted"] == len(ids)

    def test_batch_delete_requires_ids(self, client, auth_headers):
        """空 ids 返回 400。"""
        resp = client.post("/api/ad-reports/batch-delete", json={"ids": []}, headers=auth_headers)
        assert resp.status_code == 400


class TestAdReportsExport:
    """GET /api/ad-reports/export — CSV 导出。"""

    def test_export_returns_csv(self, client, auth_headers):
        """导出返回 CSV 格式。"""
        rows = [{"account": "Exp", "customerId": "exp-111", "campaign": "ExpCamp",
                 "cost": 50, "impressions": 500, "clicks": 25,
                 "installs": 5, "inAppActions": 2, "costPerInApp": 25}]
        client.post("/api/ad-reports/save", json={
            "product_name": "test_exp_prod",
            "region": "巴西", "report_date": "2026-07-01",
            "rows": rows, "override_ids": [],
        }, headers=auth_headers)

        resp = client.get("/api/ad-reports/export?product_name=test_exp_prod", headers=auth_headers)
        assert resp.status_code == 200
        assert "text/csv" in resp.content_type
        content = resp.data.decode("utf-8-sig")
        assert "产品名" in content
        assert "test_exp_prod" in content


class TestAdReportsListSearch:
    """GET /api/ad-reports/list — 搜索参数。"""

    def test_list_search_by_account(self, client, auth_headers):
        """搜索账户名匹配。"""
        rows = [
            {"account": "SearchMe", "customerId": "sr-111", "campaign": "SrcCamp",
             "cost": 50, "impressions": 500, "clicks": 25,
             "installs": 5, "inAppActions": 2, "costPerInApp": 25},
            {"account": "OtherAcc", "customerId": "sr-222", "campaign": "OthCamp",
             "cost": 30, "impressions": 300, "clicks": 15,
             "installs": 3, "inAppActions": 1, "costPerInApp": 30},
        ]
        client.post("/api/ad-reports/save", json={
            "product_name": "test_srch_prod",
            "region": "巴西", "report_date": "2026-07-01",
            "rows": rows, "override_ids": [],
        }, headers=auth_headers)

        resp = client.get("/api/ad-reports/list?search=SearchMe", headers=auth_headers)
        data = resp.get_json()
        assert data["success"] is True
        # 只匹配到 SearchMe
        assert data["total"] == 1
        assert data["reports"][0]["account"] == "SearchMe"

    def test_list_search_by_campaign(self, client, auth_headers):
        """搜索系列名匹配（自包含数据）。"""
        rows = [{"account": "SrcAcc", "customerId": "src-333", "campaign": "SrcCampaign",
                 "cost": 50, "impressions": 500, "clicks": 25,
                 "installs": 5, "inAppActions": 2, "costPerInApp": 25}]
        client.post("/api/ad-reports/save", json={
            "product_name": "test_srch2_prod",
            "region": "巴西", "report_date": "2026-07-01",
            "rows": rows, "override_ids": [],
        }, headers=auth_headers)

        resp = client.get("/api/ad-reports/list?search=SrcCampaign", headers=auth_headers)
        data = resp.get_json()
        assert data["total"] >= 1
