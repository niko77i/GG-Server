"""TT 路由集成测试。"""
import os
import sys

_py_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _py_dir not in sys.path:
    sys.path.insert(0, _py_dir)

import database  # noqa: E402


def _make_tt_headers(client, username):
    """创建第二个 TT 平台用户并返回带 JWT token 的请求头（与 conftest.tt_headers 相同方式）。"""
    client.post("/api/auth/register", json={
        "username": username, "password": "test123",
    })
    db = database.get_db()
    db.execute("UPDATE users SET platform='tt' WHERE username=?", (username,))
    db.commit()
    db.close()
    resp = client.post("/api/auth/login", json={
        "username": username, "password": "test123",
    })
    token = resp.get_json().get("access_token", "")
    return {"Authorization": f"Bearer {token}"}


def test_bc_crud(client, tt_headers):
    # 创建
    resp = client.post("/api/tt/bcs/create", headers=tt_headers, json={
        "name": "测试BC", "bc_id": "1234567890", "note": "备注",
    })
    assert resp.status_code == 200
    bid = resp.get_json()["id"]
    assert bid > 0

    # 列表
    resp = client.get("/api/tt/bcs/list", headers=tt_headers)
    items = resp.get_json()["items"]
    assert len(items) == 1
    assert items[0]["name"] == "测试BC"

    # 更新
    resp = client.put(f"/api/tt/bcs/{bid}", headers=tt_headers, json={"name": "改名BC"})
    assert resp.status_code == 200

    # 选项（ok(list) 包装为 {"success": True, "data": [...]}）
    resp = client.get("/api/tt/bcs/options", headers=tt_headers)
    assert resp.get_json()["data"][0]["name"] == "改名BC"

    # 软删除
    resp = client.delete(f"/api/tt/bcs/{bid}", headers=tt_headers)
    assert resp.status_code == 200
    resp = client.get("/api/tt/bcs/list", headers=tt_headers)
    assert resp.get_json()["items"] == []


def test_bc_create_validates_digit(client, tt_headers):
    resp = client.post("/api/tt/bcs/create", headers=tt_headers, json={
        "name": "坏BC", "bc_id": "abc",
    })
    assert resp.status_code == 400


def test_bc_list_blocks_gg_user(client, auth_headers):
    """gg 平台用户访问 TT 路由应被 tt_required 拦截返回 403。"""
    resp = client.get("/api/tt/bcs/list", headers=auth_headers)
    assert resp.status_code == 403


def test_bc_update_delete_requires_owner(client, tt_headers):
    """IDOR 修复：第二个 TT 用户不能更新/删除他人的 BC（403），所有者仍可（200）。"""
    # 第一个 TT 用户（ttuser）创建 BC
    resp = client.post("/api/tt/bcs/create", headers=tt_headers, json={
        "name": "所有者BC", "bc_id": "9876543210", "note": "",
    })
    assert resp.status_code == 200
    bid = resp.get_json()["id"]

    # 第二个 TT 用户（同为 tt 平台、普通 user 角色）
    other_headers = _make_tt_headers(client, "ttuser2")

    # 越权更新 / 删除 → 403
    resp = client.put(f"/api/tt/bcs/{bid}", headers=other_headers, json={"name": "越权改名"})
    assert resp.status_code == 403
    resp = client.delete(f"/api/tt/bcs/{bid}", headers=other_headers)
    assert resp.status_code == 403

    # 所有者仍可更新 / 删除 → 200
    resp = client.put(f"/api/tt/bcs/{bid}", headers=tt_headers, json={"name": "改名成功"})
    assert resp.status_code == 200
    resp = client.delete(f"/api/tt/bcs/{bid}", headers=tt_headers)
    assert resp.status_code == 200
