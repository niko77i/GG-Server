"""FB 分析端点 —— 聚合口径与平台数据隔离。

设计见 docs/superpowers/specs/2026-10-11-analysis-platform-isolation-design.md。
运行：cd py && python -m pytest tests/test_fb_analysis.py -v
"""
import pytest

import database

DASH = "/api/fb/analysis/dashboard"
TREND = "/api/fb/analysis/trends"


def _login(client, username):
    client.post("/api/auth/register", json={"username": username, "password": "test123"})
    db = database.get_db()
    db.execute("UPDATE users SET platform='fb', role='user' WHERE username=?", (username,))
    db.commit()
    db.close()
    resp = client.post("/api/auth/login", json={"username": username, "password": "test123"})
    assert resp.status_code == 200, resp.get_json()
    tok = resp.get_json().get("access_token", "")
    assert tok, "登录未返回 token"
    return {"Authorization": f"Bearer {tok}"}, resp.get_json()["user"]["id"]


@pytest.fixture
def fb_user(client):
    return _login(client, "fbanalysis")


def _seed(uid, rows):
    """rows: (product, line, date, account_id, cost, impressions, clicks)"""
    db = database.get_db()
    for p, l, d, aid, cost, imp, clk in rows:
        db.execute(
            "INSERT INTO fb_ad_reports (user_id, product_name, line_name, report_date, "
            "account_name, account_id, cost, impressions, clicks) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            (uid, p, l, d, f"acc-{aid}", aid, cost, imp, clk))
    db.commit()
    db.close()


def test_dashboard_aggregates_by_line(client, fb_user):
    headers, uid = fb_user
    _seed(uid, [
        ("P1", "L1", "2026-10-01", "a1", 10.0, 100, 5),
        ("P1", "L1", "2026-10-02", "a2", 20.0, 200, 6),
        ("P1", "L2", "2026-10-01", "a3", 5.0, 50, 1),
    ])
    body = client.get(DASH, headers=headers).get_json()
    assert body["summary"]["total_cost"] == 35.0
    assert body["summary"]["total_impressions"] == 350
    assert body["summary"]["total_clicks"] == 12
    assert body["summary"]["record_count"] == 3
    assert body["summary"]["account_count"] == 3
    lines = {r["line_name"]: r for r in body["by_line"]}
    assert lines["L1"]["total_cost"] == 30.0
    assert lines["L2"]["total_cost"] == 5.0


def test_dashboard_filters_by_multi_product(client, fb_user):
    """product_name 逗号分隔多值 → IN 查询（照 ad_reports_dashboard 的口径）。"""
    headers, uid = fb_user
    _seed(uid, [
        ("P1", "L1", "2026-10-01", "a1", 10.0, 0, 0),
        ("P2", "L1", "2026-10-01", "a2", 20.0, 0, 0),
        ("P3", "L1", "2026-10-01", "a3", 40.0, 0, 0),
    ])
    body = client.get(DASH, headers=headers, query_string={"product_name": "P1,P2"}).get_json()
    assert body["summary"]["total_cost"] == 30.0
    assert body["summary"]["record_count"] == 2


def test_dashboard_filters_by_date_range(client, fb_user):
    headers, uid = fb_user
    _seed(uid, [
        ("P1", "L1", "2026-10-01", "a1", 10.0, 0, 0),
        ("P1", "L1", "2026-10-10", "a2", 20.0, 0, 0),
        ("P1", "L1", "2026-10-20", "a3", 40.0, 0, 0),
    ])
    body = client.get(DASH, headers=headers,
                      query_string={"from_date": "2026-10-05", "to_date": "2026-10-15"}).get_json()
    assert body["summary"]["total_cost"] == 20.0


def test_dashboard_empty_is_zero_not_error(client, fb_user):
    headers, _ = fb_user
    body = client.get(DASH, headers=headers).get_json()
    assert body["success"] is True
    assert body["summary"]["total_cost"] == 0
    assert body["summary"]["record_count"] == 0
    assert body["by_line"] == []


def test_trends_groups_by_date_ascending(client, fb_user):
    headers, uid = fb_user
    _seed(uid, [
        ("P1", "L1", "2026-10-02", "a1", 20.0, 200, 2),
        ("P1", "L1", "2026-10-01", "a2", 10.0, 100, 1),
        ("P1", "L1", "2026-10-01", "a3", 5.0, 50, 1),
    ])
    body = client.get(TREND, headers=headers).get_json()
    pts = body["points"]
    assert [p["report_date"] for p in pts] == ["2026-10-01", "2026-10-02"], "必须按日期升序"
    assert pts[0]["total_cost"] == 15.0
    assert pts[1]["total_cost"] == 20.0


def test_endpoints_require_auth(client):
    assert client.get(DASH).status_code == 401
    assert client.get(TREND).status_code == 401


def test_only_reads_fb_table_not_gg(client, fb_user):
    """**数据隔离的核心判据**：往 GG 的 ad_reports 塞同名产品/线，
    FB 分析端点绝不能把它们算进来。"""
    headers, uid = fb_user
    _seed(uid, [("P1", "L1", "2026-10-01", "a1", 10.0, 0, 0)])   # fb_ad_reports
    db = database.get_db()
    db.execute(
        "INSERT INTO ad_reports (user_id, product_name, region, report_date, customer_id, "
        "campaign, cost) VALUES (?,?,?,?,?,?,?)",
        (uid, "P1", "R", "2026-10-01", "c1", "L1", 9999.0))      # ad_reports（GG）
    db.commit()
    db.close()
    body = client.get(DASH, headers=headers).get_json()
    assert body["summary"]["total_cost"] == 10.0, "不能把 GG 的 9999 算进来"
