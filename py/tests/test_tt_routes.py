"""TT 路由集成测试。"""
import os
import sys

_py_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _py_dir not in sys.path:
    sys.path.insert(0, _py_dir)


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
