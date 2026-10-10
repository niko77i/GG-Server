"""数据管理页的跨用户权限（GG + FB）。

设计见 docs/superpowers/specs/2026-10-11-report-data-permission-design.md。
运行：cd py && python -m pytest tests/test_report_data_permission.py -v

本文件由 Task 3（FB）先建，含两任务共用的 `_mk_user`；Task 2（GG）随后**追加**
自己的部分，不重建本文件。
"""
import pytest

import database

# ---------- 夹具（GG / FB 共用） ----------


def _mk_user(client, username, role, platform="gg"):
    client.post("/api/auth/register", json={"username": username, "password": "test123"})
    db = database.get_db()
    db.execute("UPDATE users SET role=?, platform=? WHERE username=?", (role, platform, username))
    db.commit()
    uid = db.execute("SELECT id FROM users WHERE username=?", (username,)).fetchone()["id"]
    db.close()
    resp = client.post("/api/auth/login", json={"username": username, "password": "test123"})
    assert resp.status_code == 200, resp.get_json()
    tok = resp.get_json().get("access_token", "")
    assert tok, "登录未返回 token"
    return {"Authorization": f"Bearer {tok}"}, uid


# ---------- FB ----------

def _mk_fb_user(client, username, role):
    return _mk_user(client, username, role, platform="fb")


def _mk_fb_report(uid, product="P1", line="L1", date="2026-10-01", cost=10.0, aid="accX"):
    db = database.get_db()
    db.execute(
        "INSERT INTO fb_ad_reports (user_id, product_name, line_name, report_date, "
        "account_name, account_id, cost) VALUES (?,?,?,?,?,?,?)",
        (uid, product, line, date, "n-" + aid, aid, cost))
    db.commit()
    rid = db.execute("SELECT id FROM fb_ad_reports ORDER BY id DESC LIMIT 1").fetchone()["id"]
    db.close()
    return rid


@pytest.fixture
def fb_three(client):
    u_h, u_uid = _mk_fb_user(client, "fperm_user", "user")
    g_h, g_uid = _mk_fb_user(client, "fperm_hug", "huguan")
    a_h, a_uid = _mk_fb_user(client, "fperm_adm", "admin")
    return {
        "user": (u_h, u_uid, _mk_fb_report(u_uid, aid="u1", cost=11.0)),
        "huguan": (g_h, g_uid, _mk_fb_report(g_uid, aid="g1", cost=22.0)),
        "admin": (a_h, a_uid, _mk_fb_report(a_uid, aid="a1", cost=33.0)),
    }


def _fb_items(client, headers, **params):
    r = client.get("/api/fb/reports/list", headers=headers, query_string=params)
    assert r.status_code == 200, r.get_data(as_text=True)[:300]
    return r.get_json()


def test_fb_plain_user_still_sees_only_self(client, fb_three):
    h, _, _ = fb_three["user"]
    body = _fb_items(client, h)
    rows = body.get("data") or body.get("items") or body.get("reports")
    assert rows is not None, f"list 返回结构变了：{list(body)}"
    assert len(rows) == 1


@pytest.mark.parametrize("who", ["huguan", "admin"])
def test_fb_cross_user_sees_all(client, fb_three, who):
    h, _, _ = fb_three[who]
    body = _fb_items(client, h)
    rows = body.get("data") or body.get("items") or body.get("reports")
    assert len(rows) == 3, f"{who} 应看到全部"


def test_fb_owner_filter_cannot_widen_plain_user(client, fb_three):
    h, _, _ = fb_three["user"]
    _, hug_uid, _ = fb_three["huguan"]
    body = _fb_items(client, h, user_id=hug_uid)
    rows = body.get("data") or body.get("items") or body.get("reports")
    assert len(rows) == 1, "owner 筛选不得让普通用户看到别人的行"


def test_fb_huguan_can_edit_cost(client, fb_three):
    h, _, _ = fb_three["huguan"]
    _, _, u_rid = fb_three["user"]
    r = client.put(f"/api/fb/reports/{u_rid}", json={"cost": 77.0}, headers=h)
    assert r.status_code == 200, r.get_data(as_text=True)[:300]


def test_fb_huguan_cannot_edit_other_fields(client, fb_three):
    """**现存行为被收窄**：户管此前能改整行，现在只剩 cost。"""
    h, _, _ = fb_three["huguan"]
    _, _, u_rid = fb_three["user"]
    for payload in ({"line_name": "L9"}, {"cost": 1.0, "line_name": "L9"}):
        assert client.put(f"/api/fb/reports/{u_rid}", json=payload, headers=h).status_code == 403


def test_fb_admin_readonly(client, fb_three):
    """**现存行为被收紧**：FB 的写接口此前对 admin 开放。"""
    h, _, own = fb_three["admin"]
    _, _, u_rid = fb_three["user"]
    assert client.put(f"/api/fb/reports/{u_rid}", json={"cost": 1.0}, headers=h).status_code == 403
    assert client.delete(f"/api/fb/reports/{own}", headers=h).status_code == 403
    assert client.post("/api/fb/reports/batch-delete", json={"ids": [own]}, headers=h).status_code == 403
    assert client.post("/api/fb/reports/retry-sync",
                       json={"groups": [["P1", "L1", "2026-10-01"]]}, headers=h).status_code == 403


def test_fb_huguan_cannot_delete(client, fb_three):
    h, _, own = fb_three["huguan"]
    assert client.delete(f"/api/fb/reports/{own}", headers=h).status_code == 403
    assert client.post("/api/fb/reports/batch-delete", json={"ids": [own]}, headers=h).status_code == 403


def test_fb_export_allowed_for_cross_user(client, fb_three):
    for who in ("admin", "huguan"):
        h, _, _ = fb_three[who]
        assert client.get("/api/fb/reports/export", headers=h).status_code == 200, who


# ---------- FB：审查收口（2026-10-11，Task 3 审查 🔴 / 🟡） ----------

_EXTRACT_PAYLOAD = {
    "product_name": "P1", "line_name": "L1", "report_date": "2026-10-01",
    "records": [{"account_name": "n", "account_id": "x1", "cost": 1}],
}


def _fb_report_count():
    db = database.get_db()
    n = db.execute("SELECT COUNT(*) FROM fb_ad_reports").fetchone()[0]
    db.close()
    return n


@pytest.mark.parametrize("who", ["huguan", "admin"])
def test_fb_extract_save_rejects_readonly_roles(client, fb_three, who):
    """**审查 🔴**：`/api/fb/extract/save` 是 FB 侧**另一条**写 `fb_ad_reports` 的路径
    （「数据提取」页的新增 / 回填）。它的装饰器只过平台门禁、不判角色 ——
    户管与 FB 管理员曾能直接 200 新增行并写全字段（实测复现）。
    它与数据管理页同属「写 FB 报表数据」，同受设计 §3 矩阵约束 ⇒ 只读角色 403。
    """
    h, _, _ = fb_three[who]
    before = _fb_report_count()
    r = client.post("/api/fb/extract/save", json=_EXTRACT_PAYLOAD, headers=h)
    assert r.status_code == 403, r.get_data(as_text=True)[:300]
    assert _fb_report_count() == before, "被拒的请求不得落库（守卫须在 INSERT 之前）"


def test_fb_extract_save_still_allows_plain_user(client, fb_three, monkeypatch):
    """回归：普通 user 用数据提取页保存**自己名下**的数据不受影响（收窄不得误伤）。"""
    import google_sheets_service as gs
    monkeypatch.setattr(gs, "upsert_fb_reports", lambda *a, **k: None)
    h, _, _ = fb_three["user"]
    r = client.post("/api/fb/extract/save", json=_EXTRACT_PAYLOAD, headers=h)
    assert r.status_code == 200, r.get_data(as_text=True)[:300]


def test_fb_stats_owner_filter_cannot_widen_plain_user(client, fb_three):
    """**审查 🟡**：stats 也钉住「普通 user 传他人 `user_id` 仍只见自己」。

    三条夹具的 (产品, 线, 日期) 完全相同 ⇒ 越权成功的话会聚成一行、total_cost=66.0；
    被正确收窄则只有自己那行、total_cost=11.0。两者可判别。
    """
    h, _, _ = fb_three["user"]
    _, hug_uid, _ = fb_three["huguan"]
    r = client.get("/api/fb/reports/stats", headers=h, query_string={"user_id": hug_uid})
    assert r.status_code == 200, r.get_data(as_text=True)[:300]
    rows = r.get_json()["data"]
    assert len(rows) == 1, f"只该看到自己那一行，实际 {rows}"
    assert rows[0]["total_cost"] == 11.0, f"聚合值不得含他人行：{rows}"


def test_fb_export_owner_filter_cannot_widen_plain_user(client, fb_three):
    """**审查 🟡**：export 也钉住同一条硬约束（CSV 正文不得出现他人那行）。"""
    h, _, _ = fb_three["user"]
    _, hug_uid, _ = fb_three["huguan"]
    r = client.get("/api/fb/reports/export", headers=h, query_string={"user_id": hug_uid})
    assert r.status_code == 200, r.get_data(as_text=True)[:300]
    body = r.get_data(as_text=True)
    assert "u1" in body, "自己那行（account_id=u1）必须在导出里"
    assert "g1" not in body, "他人那行（account_id=g1）不得出现"


# ---------- GG ----------

def _mk_report(uid, product="P1", date="2026-10-01", cost=10.0, campaign="C1"):
    db = database.get_db()
    db.execute(
        "INSERT INTO ad_reports (user_id, product_name, region, report_date, customer_id, "
        "campaign, cost) VALUES (?,?,?,?,?,?,?)",
        (uid, product, "R", date, "cust1", campaign, cost))
    db.commit()
    rid = db.execute("SELECT id FROM ad_reports ORDER BY id DESC LIMIT 1").fetchone()["id"]
    db.close()
    return rid


@pytest.fixture
def three(client):
    """三个账号：普通 user / 户管 / 管理员，各造一条自己的 GG 报表。"""
    user_h, user_uid = _mk_user(client, "perm_user", "user")
    hug_h, hug_uid = _mk_user(client, "perm_hug", "huguan")
    adm_h, adm_uid = _mk_user(client, "perm_adm", "admin")
    user_rid = _mk_report(user_uid, cost=11.0)
    hug_rid = _mk_report(hug_uid, cost=22.0)
    adm_rid = _mk_report(adm_uid, cost=33.0)
    return {
        "user": (user_h, user_uid, user_rid),
        "huguan": (hug_h, hug_uid, hug_rid),
        "admin": (adm_h, adm_uid, adm_rid),
    }


def _items(client, headers, **params):
    r = client.get("/api/ad-reports/list", headers=headers, query_string=params)
    assert r.status_code == 200, r.get_data(as_text=True)[:300]
    # ⚠️ GG 的 list 返回键是 `reports`（不是 `data`）。
    return r.get_json()["reports"]


# ---------- GG：可见范围 ----------

def test_gg_plain_user_still_sees_only_self(client, three):
    """**回归硬判据**：普通用户的行为与改动前逐字一致。"""
    h, uid, _ = three["user"]
    got = _items(client, h)
    assert len(got) == 1
    assert got[0]["cost"] == 11.0


def test_gg_huguan_sees_all(client, three):
    h, _, _ = three["huguan"]
    assert len(_items(client, h)) == 3, "户管应看到全部用户的数据"


def test_gg_admin_sees_all(client, three):
    h, _, _ = three["admin"]
    assert len(_items(client, h)) == 3, "管理员应看到全部用户的数据"


def test_gg_owner_filter_narrows_for_cross_user(client, three):
    """「保存人」筛选：跨用户角色传 user_id 只拿到该人的行。"""
    h, _, _ = three["huguan"]
    _, user_uid, _ = three["user"]
    got = _items(client, h, user_id=user_uid)
    assert len(got) == 1 and got[0]["cost"] == 11.0


def test_gg_owner_filter_cannot_widen_plain_user(client, three):
    """**越权硬判据**：普通用户传别人的 user_id 也只看自己。"""
    h, _, _ = three["user"]
    _, hug_uid, _ = three["huguan"]
    got = _items(client, h, user_id=hug_uid)
    assert len(got) == 1 and got[0]["cost"] == 11.0, "owner 筛选不得让普通用户看到别人的行"


# ---------- GG：写权限 ----------

def test_gg_huguan_can_edit_cost_of_others_row(client, three):
    h, _, _ = three["huguan"]
    _, user_uid, user_rid = three["user"]
    r = client.put(f"/api/ad-reports/{user_rid}", json={"cost": 99.5}, headers=h)
    assert r.status_code == 200, r.get_data(as_text=True)[:300]
    db = database.get_db()
    got = db.execute("SELECT cost FROM ad_reports WHERE id=?", (user_rid,)).fetchone()["cost"]
    db.close()
    assert got == 99.5


def test_gg_huguan_cannot_edit_other_fields(client, three):
    """**白名单外字段 → 403**（不是静默忽略）。"""
    h, _, _ = three["huguan"]
    _, _, user_rid = three["user"]
    for payload in ({"campaign": "改过的"}, {"cost": 1.0, "campaign": "改过的"},
                    {"region": "XX"}, {"report_date": "2030-01-01"}):
        r = client.put(f"/api/ad-reports/{user_rid}", json=payload, headers=h)
        assert r.status_code == 403, f"{payload} 应被拒，实际 {r.status_code}"


def test_gg_admin_cannot_edit_anything(client, three):
    h, _, _ = three["admin"]
    _, _, user_rid = three["user"]
    for payload in ({"cost": 1.0}, {"campaign": "x"}):
        assert client.put(f"/api/ad-reports/{user_rid}", json=payload, headers=h).status_code == 403


def test_gg_admin_and_huguan_cannot_delete(client, three):
    for who in ("admin", "huguan"):
        h, _, own_rid = three[who]
        assert client.delete(f"/api/ad-reports/{own_rid}", headers=h).status_code == 403, who
        r = client.post("/api/ad-reports/batch-delete", json={"ids": [own_rid]}, headers=h)
        assert r.status_code == 403, who


def test_gg_admin_and_huguan_cannot_create(client, three):
    payload = {"product_name": "P1", "report_date": "2026-10-01", "region": "R",
               "records": [{"campaign": "C9", "cost": 1}]}
    for who in ("admin", "huguan"):
        h, _, _ = three[who]
        assert client.post("/api/ad-reports/save", json=payload, headers=h).status_code == 403, who


def test_gg_export_allowed_for_admin_and_huguan(client, three):
    for who in ("admin", "huguan"):
        h, _, _ = three[who]
        assert client.get("/api/ad-reports/export", headers=h).status_code == 200, who


def test_gg_export_owner_filter_cannot_widen_plain_user(client, three):
    """**审查补强**：export 也钉住「普通 user 传他人 user_id 仍只导出自己的行」。

    三条夹具的 (产品,地区,日期,客户ID,广告系列) 完全相同，唯一可判别的是 cost：
    自己 11.0，他人 22.0 / 33.0。越权成功的话 CSV 正文会同时出现他人行的 cost。
    """
    h, _, _ = three["user"]
    _, hug_uid, _ = three["huguan"]
    r = client.get("/api/ad-reports/export", headers=h, query_string={"user_id": hug_uid})
    assert r.status_code == 200, r.get_data(as_text=True)[:300]
    body = r.get_data(as_text=True)
    assert "11.0" in body, "自己那行（cost=11.0）必须在导出里"
    assert "22.0" not in body, "他人那行（cost=22.0）不得出现"
    assert "33.0" not in body, "他人那行（cost=33.0）不得出现"


def test_gg_plain_user_write_paths_unchanged(client, three):
    """普通用户对自己行的增删改仍是 200（回归）。"""
    h, _, own_rid = three["user"]
    assert client.put(f"/api/ad-reports/{own_rid}", json={"cost": 5.0}, headers=h).status_code == 200
    assert client.delete(f"/api/ad-reports/{own_rid}", headers=h).status_code == 200
