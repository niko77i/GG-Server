"""TT 路由集成测试。"""
import io
import json
import os
import sys

_py_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _py_dir not in sys.path:
    sys.path.insert(0, _py_dir)

import database  # noqa: E402
import unittest.mock as mock  # noqa: E402


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


def test_bc_list_search(client, tt_headers):
    """BC 列表 search 参数：按名称或 BCID 模糊匹配。"""
    client.post("/api/tt/bcs/create", headers=tt_headers, json={
        "name": "Alpha", "bc_id": "111",
    })
    client.post("/api/tt/bcs/create", headers=tt_headers, json={
        "name": "Beta", "bc_id": "222",
    })

    # 按名称模糊匹配
    resp = client.get("/api/tt/bcs/list?search=Alp", headers=tt_headers)
    items = resp.get_json()["items"]
    assert [it["name"] for it in items] == ["Alpha"]

    # 按 bc_id 模糊匹配
    resp = client.get("/api/tt/bcs/list?search=222", headers=tt_headers)
    items = resp.get_json()["items"]
    assert [it["name"] for it in items] == ["Beta"]


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


def _create_bc(client, tt_headers, name="BC1", bc_id="1111111111"):
    return client.post("/api/tt/bcs/create", headers=tt_headers,
                       json={"name": name, "bc_id": bc_id}).get_json()["id"]


def test_product_crud(client, tt_headers):
    bc_id = _create_bc(client, tt_headers)

    # 创建（含投放对象）
    resp = client.post("/api/tt/products/create", headers=tt_headers, json={
        "product_name": "产品A", "kpi": "KPI-A", "region": "巴西",
        "bc_id": bc_id, "customer": "客户X",
        "runner_ids": [], "packages": [
            {"type": "package", "series_name": "系列1", "package_name": "com.a.b", "url": "https://play.google.com/store/apps/details?id=com.a.b"},
            {"type": "pwa", "series_name": "PWA系列", "url": "https://example.com/pwa"},
        ],
    })
    assert resp.status_code == 200
    pid = resp.get_json()["id"]

    # 列表
    resp = client.get("/api/tt/products/list", headers=tt_headers)
    items = resp.get_json()["items"]
    assert len(items) == 1
    assert items[0]["product_name"] == "产品A"
    assert len(items[0]["packages"]) == 2

    # 详情
    resp = client.get(f"/api/tt/products/{pid}/detail", headers=tt_headers)
    assert resp.get_json()["customer"] == "客户X"
    assert len(resp.get_json()["packages"]) == 2

    # 更新
    resp = client.put(f"/api/tt/products/{pid}", headers=tt_headers, json={
        "product_name": "产品A改", "kpi": "KPI-B",
    })
    assert resp.status_code == 200
    resp = client.get(f"/api/tt/products/{pid}/detail", headers=tt_headers)
    assert resp.get_json()["product_name"] == "产品A改"

    # 软删除 + 恢复
    client.delete(f"/api/tt/products/{pid}", headers=tt_headers)
    resp = client.get("/api/tt/products/list", headers=tt_headers)
    assert resp.get_json()["items"] == []
    client.post(f"/api/tt/products/{pid}/restore", headers=tt_headers)
    resp = client.get("/api/tt/products/list", headers=tt_headers)
    assert len(resp.get_json()["items"]) == 1


def test_runner_products(client, tt_headers):
    # 未在任何产品担任 runner 时返回空（ok(list) 包装为 {"data": []}）
    resp = client.get("/api/tt/products/runner-products", headers=tt_headers)
    assert resp.get_json()["data"] == []


def test_product_update_writes_packages(client, tt_headers):
    """update_product 传入 packages 时覆盖写入；不传 packages 时保持原 packages 不变。"""
    bc_id = _create_bc(client, tt_headers)
    pid = client.post("/api/tt/products/create", headers=tt_headers, json={
        "product_name": "带包产品", "bc_id": bc_id,
        "packages": [
            {"type": "package", "series_name": "系列1", "package_name": "com.a.b", "url": "https://a"},
            {"type": "pwa", "series_name": "PWA系列", "url": "https://b"},
        ],
    }).get_json()["id"]

    detail = client.get(f"/api/tt/products/{pid}/detail", headers=tt_headers).get_json()
    assert len(detail["packages"]) == 2

    # 更新 packages → 数量与内容变化
    resp = client.put(f"/api/tt/products/{pid}", headers=tt_headers, json={
        "packages": [
            {"type": "package", "series_name": "新系列", "package_name": "com.c.d", "url": "https://c"},
        ],
    })
    assert resp.status_code == 200
    detail = client.get(f"/api/tt/products/{pid}/detail", headers=tt_headers).get_json()
    assert len(detail["packages"]) == 1
    assert detail["packages"][0]["package_name"] == "com.c.d"

    # 不传 packages 的更新 → packages 保持不变
    resp = client.put(f"/api/tt/products/{pid}", headers=tt_headers, json={
        "product_name": "改名不带包",
    })
    assert resp.status_code == 200
    detail = client.get(f"/api/tt/products/{pid}/detail", headers=tt_headers).get_json()
    assert len(detail["packages"]) == 1
    assert detail["packages"][0]["package_name"] == "com.c.d"


def test_list_products_runner_param_no_idor(client, tt_headers):
    """横向越权修复：普通用户带 runner=他人uid 过滤时，仍只能看到自己的产品。"""
    # 第一个 TT 用户创建自己的产品
    bc_id = _create_bc(client, tt_headers)
    pid_own = client.post("/api/tt/products/create", headers=tt_headers, json={
        "product_name": "我的产品", "bc_id": bc_id,
    }).get_json()["id"]

    # 第二个 TT 用户创建产品
    other_headers = _make_tt_headers(client, "ttuser2")
    bc2_id = _create_bc(client, other_headers, name="BC2", bc_id="2222222222")
    pid_other = client.post("/api/tt/products/create", headers=other_headers, json={
        "product_name": "他人产品", "bc_id": bc2_id,
    }).get_json()["id"]

    # 查 ttuser2 的 uid
    db = database.get_db()
    row = db.execute("SELECT id FROM users WHERE username='ttuser2'").fetchone()
    db.close()
    other_uid = row["id"]

    # 第一个用户带 runner=<ttuser2_id> 过滤，只能看到自己的产品，看不到他人产品
    resp = client.get(f"/api/tt/products/list?runner={other_uid}", headers=tt_headers)
    ids = [it["id"] for it in resp.get_json()["items"]]
    assert pid_own in ids
    assert pid_other not in ids


def test_product_update_delete_requires_owner(client, tt_headers):
    """IDOR 修复：第二个 TT 用户不能更新/删除/查看他人产品（403），所有者仍可（200）。"""
    bc_id = _create_bc(client, tt_headers)
    pid = client.post("/api/tt/products/create", headers=tt_headers, json={
        "product_name": "所有者产品", "bc_id": bc_id,
    }).get_json()["id"]

    other_headers = _make_tt_headers(client, "ttuser2")

    # 越权更新 / 删除 / 详情 → 403
    assert client.put(f"/api/tt/products/{pid}", headers=other_headers,
                      json={"product_name": "越权改名"}).status_code == 403
    assert client.delete(f"/api/tt/products/{pid}", headers=other_headers).status_code == 403
    assert client.get(f"/api/tt/products/{pid}/detail", headers=other_headers).status_code == 403

    # 所有者仍可更新 / 删除 → 200
    assert client.put(f"/api/tt/products/{pid}", headers=tt_headers,
                      json={"product_name": "改名成功"}).status_code == 200
    assert client.delete(f"/api/tt/products/{pid}", headers=tt_headers).status_code == 200


def test_package_crud_and_batch_delete(client, tt_headers):
    pid = client.post("/api/tt/products/create", headers=tt_headers, json={
        "product_name": "包产品",
    }).get_json()["id"]

    # 添加跑包
    resp = client.post(f"/api/tt/products/{pid}/packages", headers=tt_headers, json={
        "type": "package", "series_name": "S1", "package_name": "com.x.y", "url": "https://play.google.com/store/apps/details?id=com.x.y",
    })
    assert resp.status_code == 200
    pkg_id = resp.get_json()["id"]

    # 添加 PWA
    resp = client.post(f"/api/tt/products/{pid}/packages", headers=tt_headers, json={
        "type": "pwa", "series_name": "PWA-1", "url": "https://pwa.example.com",
    })
    pwa_id = resp.get_json()["id"]

    # 校验 type 字段
    resp = client.get(f"/api/tt/products/{pid}/detail", headers=tt_headers)
    pkgs = resp.get_json()["packages"]
    types = {p["id"]: p["type"] for p in pkgs}
    assert types[pkg_id] == "package"
    assert types[pwa_id] == "pwa"
    assert {p["package_name"] for p in pkgs} == {"com.x.y", ""}

    # 更新
    resp = client.put(f"/api/tt/packages/{pkg_id}", headers=tt_headers, json={"status": "dropped"})
    assert resp.status_code == 200

    # 单个删除
    resp = client.delete(f"/api/tt/packages/{pkg_id}", headers=tt_headers)
    assert resp.status_code == 200

    # 批量删除
    resp = client.post("/api/tt/packages/batch-delete", headers=tt_headers, json={"ids": [pwa_id]})
    assert resp.status_code == 200
    resp = client.get(f"/api/tt/products/{pid}/detail", headers=tt_headers)
    assert resp.get_json()["packages"] == []


def test_package_update_status_only_preserves_fields(client, tt_headers):
    """部分更新：只传 status 时，series_name/package_name/url 等未传字段必须保留原值。"""
    pid = client.post("/api/tt/products/create", headers=tt_headers, json={
        "product_name": "字段幸存产品",
    }).get_json()["id"]
    pkg_id = client.post(f"/api/tt/products/{pid}/packages", headers=tt_headers, json={
        "type": "package", "series_name": "系列X", "package_name": "com.survive.pkg",
        "url": "https://play.google.com/store/apps/details?id=com.survive.pkg",
    }).get_json()["id"]

    resp = client.put(f"/api/tt/packages/{pkg_id}", headers=tt_headers,
                      json={"status": "dropped"})
    assert resp.status_code == 200

    pkgs = client.get(f"/api/tt/products/{pid}/detail", headers=tt_headers).get_json()["packages"]
    pkg = next(p for p in pkgs if p["id"] == pkg_id)
    assert pkg["status"] == "dropped"
    assert pkg["series_name"] == "系列X"
    assert pkg["package_name"] == "com.survive.pkg"
    assert pkg["url"] == "https://play.google.com/store/apps/details?id=com.survive.pkg"


def test_package_update_requires_package_name_for_package_type(client, tt_headers):
    """type=package 的投放对象，PUT 传空 package_name → 400。"""
    pid = client.post("/api/tt/products/create", headers=tt_headers, json={
        "product_name": "空包名产品",
    }).get_json()["id"]
    pkg_id = client.post(f"/api/tt/products/{pid}/packages", headers=tt_headers, json={
        "type": "package", "series_name": "系列Y", "package_name": "com.existing.pkg",
    }).get_json()["id"]

    resp = client.put(f"/api/tt/packages/{pkg_id}", headers=tt_headers,
                      json={"package_name": ""})
    assert resp.status_code == 400


def test_package_update_delete_batch_requires_owner(client, tt_headers):
    """IDOR 修复：第二个 TT 用户不能更新/删除/批量删除他人的投放对象（403），所有者仍可（200）。"""
    pid = client.post("/api/tt/products/create", headers=tt_headers, json={
        "product_name": "所有者包产品",
    }).get_json()["id"]
    pkg_id = client.post(f"/api/tt/products/{pid}/packages", headers=tt_headers, json={
        "type": "package", "series_name": "S1", "package_name": "com.owner.pkg",
    }).get_json()["id"]
    pwa_id = client.post(f"/api/tt/products/{pid}/packages", headers=tt_headers, json={
        "type": "pwa", "series_name": "PWA-1", "url": "https://owner.example.com",
    }).get_json()["id"]

    other_headers = _make_tt_headers(client, "ttuser2")

    # 越权更新 / 删除 → 403
    assert client.put(f"/api/tt/packages/{pkg_id}", headers=other_headers,
                      json={"status": "dropped"}).status_code == 403
    assert client.delete(f"/api/tt/packages/{pkg_id}", headers=other_headers).status_code == 403

    # 越权批量删除（任一非 owner 即整体拒绝，不部分删除）→ 403
    assert client.post("/api/tt/packages/batch-delete", headers=other_headers,
                       json={"ids": [pwa_id]}).status_code == 403

    # 所有者仍可更新 / 删除 / 批量删除 → 200
    assert client.put(f"/api/tt/packages/{pkg_id}", headers=tt_headers,
                      json={"status": "dropped"}).status_code == 200
    assert client.delete(f"/api/tt/packages/{pkg_id}", headers=tt_headers).status_code == 200
    assert client.post("/api/tt/packages/batch-delete", headers=tt_headers,
                       json={"ids": [pwa_id]}).status_code == 200
    assert client.get(f"/api/tt/products/{pid}/detail", headers=tt_headers).get_json()["packages"] == []


def test_check_delist(client, tt_headers):
    pid = client.post("/api/tt/products/create", headers=tt_headers, json={
        "product_name": "掉包产品",
        "packages": [{"type": "package", "series_name": "S", "package_name": "com.a.b", "url": "https://play.google.com/store/apps/details?id=com.a.b"}],
    }).get_json()["id"]

    # 从真实数据取 package id，避免硬编码 id=1 依赖「全新临时 DB 首个插入」这一事实
    detail = client.get(f"/api/tt/products/{pid}/detail", headers=tt_headers).get_json()
    pkg_id = detail["packages"][0]["id"]

    fake = [{"package_id": pkg_id, "product_id": pid, "is_delisted": True, "error": ""}]
    with mock.patch("delist_checker.check_product_packages", return_value=fake):
        resp = client.post(f"/api/tt/products/{pid}/check-delist", headers=tt_headers)
    assert resp.status_code == 200
    assert resp.get_json()["results"][0]["is_delisted"] is True

    # 检测掉包后，list_products 通过 LEFT JOIN 返回 is_delisted，用于卡片红边持久标记
    items = client.get("/api/tt/products/list", headers=tt_headers).get_json()["items"]
    assert items[0]["packages"][0]["is_delisted"] == 1

    # 掉包状态查询
    resp = client.get("/api/tt/products/delist-status", headers=tt_headers)
    assert len(resp.get_json()["delisted_packages"]) == 1


def test_check_delist_requires_owner(client, tt_headers):
    """IDOR 修复：第二个 TT 用户不能对他人产品触发掉包检测（403）。"""
    pid = client.post("/api/tt/products/create", headers=tt_headers, json={
        "product_name": "他人掉包产品",
        "packages": [{"type": "package", "series_name": "S", "package_name": "com.owner.delist", "url": "https://play.google.com/store/apps/details?id=com.owner.delist"}],
    }).get_json()["id"]

    other_headers = _make_tt_headers(client, "ttuser2")
    resp = client.post(f"/api/tt/products/{pid}/check-delist", headers=other_headers)
    assert resp.status_code == 403


def test_delist_status_scope(client, tt_headers):
    """横向越权修复：非 owner/runner 用户看不到他人产品的掉包记录；owner 能看到自己的。"""
    pid = client.post("/api/tt/products/create", headers=tt_headers, json={
        "product_name": "我的掉包产品",
        "packages": [{"type": "package", "series_name": "S", "package_name": "com.mine.delist", "url": "https://play.google.com/store/apps/details?id=com.mine.delist"}],
    }).get_json()["id"]
    detail = client.get(f"/api/tt/products/{pid}/detail", headers=tt_headers).get_json()
    pkg_id = detail["packages"][0]["id"]

    fake = [{"package_id": pkg_id, "product_id": pid, "is_delisted": True, "error": ""}]
    with mock.patch("delist_checker.check_product_packages", return_value=fake):
        resp = client.post(f"/api/tt/products/{pid}/check-delist", headers=tt_headers)
    assert resp.status_code == 200

    # owner 能看到自己产品的掉包记录
    resp = client.get("/api/tt/products/delist-status", headers=tt_headers)
    assert len(resp.get_json()["delisted_packages"]) == 1

    # 非 owner/runner 用户看不到他人产品的掉包记录
    other_headers = _make_tt_headers(client, "ttuser2")
    resp = client.get("/api/tt/products/delist-status", headers=other_headers)
    assert resp.get_json()["delisted_packages"] == []


def test_import_text_parse(client, tt_headers):
    text = "神包上线：战神系列\nhttps://play.google.com/store/apps/details?id=com.hero.war"
    resp = client.post("/api/tt/products/import-text", headers=tt_headers, json={
        "text": text, "prefix": "P9", "suffix": "B",
    })
    assert resp.status_code == 200
    parsed = resp.get_json()["parsed"]
    assert len(parsed) == 1
    assert parsed[0]["package_name"] == "com.hero.war"


def test_merge_products(client, tt_headers):
    p1 = client.post("/api/tt/products/create", headers=tt_headers, json={
        "product_name": "主产品",
        "packages": [{"type": "package", "series_name": "A", "package_name": "com.a", "url": "https://play.google.com/store/apps/details?id=com.a"}],
    }).get_json()["id"]
    p2 = client.post("/api/tt/products/create", headers=tt_headers, json={
        "product_name": "副产品",
        "packages": [{"type": "package", "series_name": "B", "package_name": "com.b", "url": "https://play.google.com/store/apps/details?id=com.b"}],
    }).get_json()["id"]

    resp = client.post("/api/tt/products/merge", headers=tt_headers, json={
        "master_id": p1, "merge_ids": [p2],
    })
    assert resp.status_code == 200
    assert resp.get_json()["merged_packages"] == 1

    # 副产品被删除，主产品含 2 个投放对象
    resp = client.get(f"/api/tt/products/{p1}/detail", headers=tt_headers)
    assert len(resp.get_json()["packages"]) == 2


def test_list_tt_users(client, tt_headers):
    resp = client.get("/api/tt/users", headers=tt_headers)
    users = resp.get_json()["users"]
    assert any(u["username"] == "ttuser" for u in users)


def test_assets_add_list_delete(client, tt_headers):
    """素材关联：从共享视频库选择已有视频建立关联，video_owner_id 存视频真实 owner。"""
    pid = client.post("/api/tt/products/create", headers=tt_headers, json={
        "product_name": "素材产品",
    }).get_json()["id"]

    # 第二个用户拥有一个共享视频（owner 与当前用户不同，验证 video_owner_id 修复）
    _make_tt_headers(client, "ttuser2")
    db = database.get_db()
    other_uid = db.execute("SELECT id FROM users WHERE username='ttuser2'").fetchone()["id"]
    db.execute(
        "INSERT INTO videos (id, owner_id, url, title) VALUES (?, ?, ?, ?)",
        ("vid-abc", other_uid, "https://example.com/v.mp4", "测试视频"))
    db.commit()
    db.close()

    # ttuser 将他人拥有的共享视频关联到自己产品
    resp = client.post(f"/api/tt/products/{pid}/assets", headers=tt_headers,
                       json={"video_ids": ["vid-abc"]})
    assert resp.status_code == 200
    assert resp.get_json()["added"] == 1

    # 列表应能 JOIN 出该视频
    resp = client.get(f"/api/tt/products/{pid}/assets", headers=tt_headers)
    assert resp.status_code == 200
    assets = resp.get_json()["assets"]
    assert len(assets) == 1
    assert assets[0]["id"] == "vid-abc"
    assert assets[0]["title"] == "测试视频"

    # 删除关联
    resp = client.delete(f"/api/tt/products/{pid}/assets/vid-abc", headers=tt_headers)
    assert resp.status_code == 200
    resp = client.get(f"/api/tt/products/{pid}/assets", headers=tt_headers)
    assert resp.get_json()["assets"] == []


def test_merge_requires_owner(client, tt_headers):
    """IDOR 修复：非 owner 不能合并他人产品（403），任一被合并产品非本人即整体拒绝。"""
    p1 = client.post("/api/tt/products/create", headers=tt_headers, json={
        "product_name": "主产品",
    }).get_json()["id"]
    p2 = client.post("/api/tt/products/create", headers=tt_headers, json={
        "product_name": "副产品",
    }).get_json()["id"]

    other_headers = _make_tt_headers(client, "ttuser2")
    p3 = client.post("/api/tt/products/create", headers=other_headers, json={
        "product_name": "他人自己的产品",
    }).get_json()["id"]

    # master 是他人产品 → 403
    assert client.post("/api/tt/products/merge", headers=other_headers,
                       json={"master_id": p1, "merge_ids": [p3]}).status_code == 403
    # merge_ids 含他人产品 → 403（整体拒绝）
    assert client.post("/api/tt/products/merge", headers=other_headers,
                       json={"master_id": p3, "merge_ids": [p1]}).status_code == 403

    # 副产品 p2 未被删除（整体拒绝，不做部分合并）
    resp = client.get(f"/api/tt/products/{p1}/detail", headers=tt_headers)
    assert resp.status_code == 200


def test_assets_require_owner_or_view(client, tt_headers):
    """IDOR 修复：非 owner/runner 不能增/删/查他人产品的素材（403）。"""
    pid = client.post("/api/tt/products/create", headers=tt_headers, json={
        "product_name": "他人素材产品",
    }).get_json()["id"]

    other_headers = _make_tt_headers(client, "ttuser2")

    # 越权 add / delete / list → 403
    assert client.post(f"/api/tt/products/{pid}/assets", headers=other_headers,
                       json={"video_ids": ["vid-x"]}).status_code == 403
    assert client.delete(f"/api/tt/products/{pid}/assets/vid-x",
                         headers=other_headers).status_code == 403
    assert client.get(f"/api/tt/products/{pid}/assets",
                      headers=other_headers).status_code == 403


def test_create_product_rejects_package_without_name(client, tt_headers):
    resp = client.post("/api/tt/products/create", headers=tt_headers, json={
        "product_name": "空包名产品",
        "packages": [{"type": "package", "series_name": "S", "package_name": ""}],
    })
    assert resp.status_code == 400


def test_create_product_rejects_invalid_type(client, tt_headers):
    resp = client.post("/api/tt/products/create", headers=tt_headers, json={
        "product_name": "坏类型产品",
        "packages": [{"type": "bad", "series_name": "S", "package_name": "com.x"}],
    })
    assert resp.status_code == 400


def test_update_product_partial_does_not_clear_fields(client, tt_headers):
    pid = client.post("/api/tt/products/create", headers=tt_headers, json={
        "product_name": "部分更新产品", "kpi": "K1", "region": "巴西",
        "customer": "客户X", "status": "active",
    }).get_json()["id"]

    # 只改 status，其余字段应保留
    resp = client.put(f"/api/tt/products/{pid}", headers=tt_headers, json={"status": "paused"})
    assert resp.status_code == 200
    detail = client.get(f"/api/tt/products/{pid}/detail", headers=tt_headers).get_json()
    assert detail["status"] == "paused"
    assert detail["kpi"] == "K1"
    assert detail["region"] == "巴西"
    assert detail["customer"] == "客户X"

    # 空 product_name 应 400
    resp = client.put(f"/api/tt/products/{pid}", headers=tt_headers, json={"product_name": ""})
    assert resp.status_code == 400


def test_update_product_rejects_package_without_name(client, tt_headers):
    pid = client.post("/api/tt/products/create", headers=tt_headers, json={
        "product_name": "改包产品",
    }).get_json()["id"]
    resp = client.put(f"/api/tt/products/{pid}", headers=tt_headers, json={
        "packages": [{"type": "package", "series_name": "S", "package_name": ""}],
    })
    assert resp.status_code == 400


# ==================== 设置（Google 表格配置） ====================

def test_settings_get_default(client, tt_headers):
    resp = client.get("/api/tt/settings", headers=tt_headers)
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["success"] is True
    assert data["settings"]["sheet_mappings"]["accounts"] == "账户明细"


def test_settings_save_requires_admin(client, tt_headers):
    """普通 TT 用户保存配置 → 403。"""
    resp = client.post("/api/tt/settings", headers=tt_headers, json={
        "sheet_id": "abc", "sheet_mappings": {"accounts": "账户"},
    })
    assert resp.status_code == 403


def test_settings_save_and_readback(client, tt_headers):
    """admin 保存后读回。"""
    db = database.get_db()
    db.execute("UPDATE users SET role='admin' WHERE username='ttuser'")
    db.commit()
    db.close()

    resp = client.post("/api/tt/settings", headers=tt_headers, json={
        "sheet_id": "abc123", "sheet_mappings": {"accounts": "账户明细表"},
    })
    assert resp.status_code == 200

    resp = client.get("/api/tt/settings", headers=tt_headers)
    data = resp.get_json()
    assert data["settings"]["sheet_id"] == "abc123"
    assert data["settings"]["sheet_mappings"]["accounts"] == "账户明细表"


# ==================== 数据导出 / 导入 ====================

def test_data_export_import_roundtrip(client, tt_headers):
    """导出当前用户数据 → 导入到第二个用户 → 第二个用户可见。"""
    sp_id = client.post("/api/sales-persons/create", headers=tt_headers,
                        json={"name": "商务A"}).get_json()["id"]
    bc_id = _create_bc(client, tt_headers)
    pid = client.post("/api/tt/products/create", headers=tt_headers, json={
        "product_name": "导出产品", "bc_id": bc_id, "sales_person_id": sp_id,
        "packages": [{"type": "package", "series_name": "S",
                      "package_name": "com.exp.pkg",
                      "url": "https://play.google.com/store/apps/details?id=com.exp.pkg"}],
    }).get_json()["id"]

    # 导出
    resp = client.get("/api/tt/data/export", headers=tt_headers)
    assert resp.status_code == 200
    assert "attachment" in (resp.headers.get("Content-Disposition") or "")
    payload = resp.get_json()
    assert payload["source"] == "tt-server"
    data = payload["data"]
    assert len(data["bcs"]) == 1
    assert len(data["products"]) == 1
    assert len(data["packages"]) == 1
    assert len(data["sales_persons"]) == 1

    # 导入到第二个用户
    other_headers = _make_tt_headers(client, "ttuser2")
    file_bytes = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    resp = client.post("/api/tt/data/import", headers=other_headers,
                       data={"file": (io.BytesIO(file_bytes), "export.json")},
                       content_type="multipart/form-data")
    assert resp.status_code == 200
    report = resp.get_json()["report"]
    assert report["bcs"] == 1
    assert report["products"] == 1
    assert report["packages"] == 1

    # 第二个用户现在能看到导入的产品
    resp = client.get("/api/tt/products/list", headers=other_headers)
    assert len(resp.get_json()["items"]) == 1


def test_data_import_rejects_non_json(client, tt_headers):
    """仅支持 .json 文件。"""
    resp = client.post("/api/tt/data/import", headers=tt_headers,
                       data={"file": (io.BytesIO(b"not-json"), "export.txt")},
                       content_type="multipart/form-data")
    assert resp.status_code == 400


def test_data_import_tolerates_malformed_elements(client, tt_headers):
    """数据块里混入非 dict 元素不应 500，而是被跳过。"""
    payload = {"data": {"bcs": ["x", {"id": 1, "bc_id": "123", "name": "BC"}]}}
    file_bytes = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    resp = client.post("/api/tt/data/import", headers=tt_headers,
                       data={"file": (io.BytesIO(file_bytes), "export.json")},
                       content_type="multipart/form-data")
    assert resp.status_code == 200
    assert resp.get_json()["report"]["bcs"] == 1


# ==================== 商务人员删除的 TT 引用检查 ====================

def test_sales_persons_delete_blocks_tt_product_ref(client, tt_headers):
    """被 TT 在跑产品引用的商务人员删除 → 409。"""
    sp_id = client.post("/api/sales-persons/create", headers=tt_headers,
                        json={"name": "被引用商务"}).get_json()["id"]
    bc_id = _create_bc(client, tt_headers)
    client.post("/api/tt/products/create", headers=tt_headers, json={
        "product_name": "引用产品", "bc_id": bc_id, "sales_person_id": sp_id,
    })
    resp = client.delete(f"/api/sales-persons/{sp_id}", headers=tt_headers)
    assert resp.status_code == 409
    assert "在跑产品" in resp.get_json()["error"]


def test_sales_persons_delete_clears_archived_tt_ref(client, tt_headers):
    """被已归档 TT 产品引用的商务人员可删除，且解除引用。"""
    sp_id = client.post("/api/sales-persons/create", headers=tt_headers,
                        json={"name": "归档引用商务"}).get_json()["id"]
    bc_id = _create_bc(client, tt_headers)
    pid = client.post("/api/tt/products/create", headers=tt_headers, json={
        "product_name": "归档产品", "bc_id": bc_id, "sales_person_id": sp_id,
    }).get_json()["id"]
    # 归档产品
    client.delete(f"/api/tt/products/{pid}", headers=tt_headers)

    resp = client.delete(f"/api/sales-persons/{sp_id}", headers=tt_headers)
    assert resp.status_code == 200

    # 归档产品的 sales_person_id 已解除
    db = database.get_db()
    row = db.execute("SELECT sales_person_id FROM tt_products WHERE id=?", (pid,)).fetchone()
    db.close()
    assert row["sales_person_id"] is None


# ==================== 修复验证（#3/#4/#11/#17/#18） ====================

def _make_viewer_headers(client, username="ttviewer"):
    """创建 TT 平台 viewer（只读）用户并返回其 JWT 请求头。"""
    client.post("/api/auth/register", json={"username": username, "password": "test123"})
    db = database.get_db()
    db.execute("UPDATE users SET platform='tt', role='viewer' WHERE username=?", (username,))
    db.commit()
    db.close()
    resp = client.post("/api/auth/login", json={"username": username, "password": "test123"})
    token = resp.get_json().get("access_token", "")
    return {"Authorization": f"Bearer {token}"}


def test_viewer_cannot_write_products(client):
    """#3 viewer 角色不能写产品/BC（创建 BC/产品均 403）。"""
    viewer = _make_viewer_headers(client)
    assert client.post("/api/tt/bcs/create", headers=viewer,
                       json={"name": "BC", "bc_id": "123"}).status_code == 403
    assert client.post("/api/tt/products/create", headers=viewer,
                       json={"product_name": "产品"}).status_code == 403


def test_bc_options_owner_isolation(client, tt_headers):
    """#4 bc_options 不应泄露他人 BC（普通用户只能看到自己的 BC）。"""
    client.post("/api/tt/bcs/create", headers=tt_headers,
                json={"name": "我的BC", "bc_id": "1111111111"})
    other_headers = _make_tt_headers(client, "ttuser2")
    client.post("/api/tt/bcs/create", headers=other_headers,
                json={"name": "他人BC", "bc_id": "2222222222"})

    resp = client.get("/api/tt/bcs/options", headers=tt_headers)
    names = [it["name"] for it in resp.get_json()["data"]]
    assert "我的BC" in names
    assert "他人BC" not in names


def test_create_bc_duplicate_friendly_error(client, tt_headers):
    """#11 BCID 重复应返回友好错误而非原始 SQLite 报错。"""
    client.post("/api/tt/bcs/create", headers=tt_headers,
                json={"name": "BC1", "bc_id": "1234567890"})
    resp = client.post("/api/tt/bcs/create", headers=tt_headers,
                       json={"name": "BC2", "bc_id": "1234567890"})
    assert resp.status_code == 409
    assert "UNIQUE" not in resp.get_json()["error"]


def test_soft_deleted_bc_hidden_in_product_list(client, tt_headers):
    """#17 软删后的 BC 名称不应显示在产品列表里。"""
    bc_id = _create_bc(client, tt_headers, name="将删BC", bc_id="3333333333")
    pid = client.post("/api/tt/products/create", headers=tt_headers, json={
        "product_name": "挂BC产品", "bc_id": bc_id,
    }).get_json()["id"]
    # 软删 BC
    client.delete(f"/api/tt/bcs/{bc_id}", headers=tt_headers)

    items = client.get("/api/tt/products/list", headers=tt_headers).get_json()["items"]
    product = next(it for it in items if it["id"] == pid)
    assert product.get("bc") is None


def test_import_runner_count_accurate(client, tt_headers):
    """#18 导入时 runner 计数应反映实际入库数（INSERT OR IGNORE 折叠后不虚高）。"""
    # 导出含 1 个产品、1 个在跑人员
    _create_bc(client, tt_headers)
    pid = client.post("/api/tt/products/create", headers=tt_headers, json={
        "product_name": "导入计数产品",
    }).get_json()["id"]
    payload = {
        "data": {
            "products": [{"id": 100, "product_name": "导入计数产品"}],
            "product_runners": [
                {"id": 200, "product_id": 100},
                {"id": 201, "product_id": 100},  # 同一产品重复 runner → 折叠为一条
            ],
        },
    }
    file_bytes = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    resp = client.post("/api/tt/data/import", headers=tt_headers,
                       data={"file": (io.BytesIO(file_bytes), "export.json")},
                       content_type="multipart/form-data")
    assert resp.status_code == 200
    assert resp.get_json()["report"]["runners"] == 1
