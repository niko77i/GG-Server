"""账户看板自定义列配置 — 逻辑层与接口。

设计见 docs/superpowers/specs/2026-10-08-account-column-prefs-design.md。
运行：cd py && python -m pytest tests/test_column_prefs.py -v
"""
import json

import pytest

import column_prefs as cp
import database

URL = "/api/user/column-prefs"


# ---------- 逻辑层：形状校验 ----------

def test_validate_key_list_accepts_strings():
    assert cp.validate_key_list(["a", "b"]) == ["a", "b"]


def test_validate_key_list_strips_and_dedupes():
    assert cp.validate_key_list(["  a  ", "a", "b"]) == ["a", "b"]


@pytest.mark.parametrize("bad", [
    None, "a", 1, {"a": 1}, ["a", 1], [None], [""], ["a" * 65],
    [f"k{i}" for i in range(65)],   # 超过 64 项即拒（数量卡在净化之前）
])
def test_validate_key_list_rejects_malformed(bad):
    """形状不合格一律返回 None（调用方回 400）。"""
    assert cp.validate_key_list(bad) is None


def test_panels_constant():
    assert cp.PANELS == ("gg_ads", "tt_ads", "fb_ads")


# ---------- 逻辑层：宽容读取 ----------

def _put_raw(uid, value):
    """直接往 config 表塞任意值，模拟被别的功能写脏 / 历史数据。"""
    db = database.get_db()
    db.execute("INSERT OR REPLACE INTO config(key,value) VALUES(?,?)",
               (cp.CONFIG_KEY.format(uid=uid), value))
    db.commit()
    db.close()


@pytest.mark.parametrize("raw", [
    "not json at all",          # 坏 JSON
    "123",                      # 顶层是数字
    '"a string"',               # 顶层是字符串
    "[]",                       # 顶层是 list
    '{"gg_ads": "nope"}',       # 面板值是字符串
    '{"gg_ads": ["a","b"]}',    # 面板值是 list 而不是 dict（旧格式）
    '{"gg_ads": {"order": "x"}}',   # order 不是 list
])
def test_load_prefs_degrades_on_garbage(app, raw):
    """任何畸形存量值都必须降级，不许抛异常。

    **注意 `hidden` 坏掉的情形不在这组里**：按设计 §4.4「`order`/`hidden`
    不是 list → **该字段降级**」，hidden 坏掉只丢该字段、保留完好的 order，
    不是整面板降级。见下方 test_load_prefs_hidden_garbage_degrades_field_only。
    """
    _put_raw(9999, raw)
    db = database.get_db()
    try:
        prefs = cp.load_prefs(db, 9999)
    finally:
        db.close()
    assert prefs == {}, f"畸形值 {raw!r} 未被降级：{prefs}"


@pytest.mark.parametrize("bad_hidden", [5, "x", None, {"a": 1}])
def test_load_prefs_hidden_garbage_degrades_field_only(app, bad_hidden):
    """hidden 坏掉只降级该字段，order 原样保留（设计 §4.4「该字段降级」）。

    order 是完好的合法数据，不该因为 hidden 坏掉就连坐回默认 —— 那会让
    用户白丢自己排好的列顺序。hidden 键**缺失**时同样视为空表。
    """
    _put_raw(9996, json.dumps({"gg_ads": {"order": ["a", "b"], "hidden": bad_hidden}}))
    db = database.get_db()
    try:
        prefs = cp.load_prefs(db, 9996)
    finally:
        db.close()
    assert prefs == {"gg_ads": {"order": ["a", "b"], "hidden": []}}


def test_load_prefs_missing_hidden_is_empty(app):
    """只有 order 的面板仍然可用（hidden 键缺失 = 没有隐藏列）。"""
    _put_raw(9995, json.dumps({"gg_ads": {"order": ["a", "b"]}}))
    db = database.get_db()
    try:
        prefs = cp.load_prefs(db, 9995)
    finally:
        db.close()
    assert prefs == {"gg_ads": {"order": ["a", "b"], "hidden": []}}


def test_load_prefs_keeps_valid_and_drops_unknown_panel(app):
    _put_raw(9998, json.dumps({
        "gg_ads": {"order": ["a", "b"], "hidden": ["b"]},
        "nope": {"order": ["x"], "hidden": []},
    }))
    db = database.get_db()
    try:
        prefs = cp.load_prefs(db, 9998)
    finally:
        db.close()
    assert prefs == {"gg_ads": {"order": ["a", "b"], "hidden": ["b"]}}


def test_load_prefs_drops_hidden_keys_not_in_order(app):
    """hidden 里出现 order 里没有的 key 是冗余信息，剔除即可，不该报错。"""
    _put_raw(9997, json.dumps({
        "gg_ads": {"order": ["a"], "hidden": ["a", "ghost"]},
    }))
    db = database.get_db()
    try:
        prefs = cp.load_prefs(db, 9997)
    finally:
        db.close()
    assert prefs["gg_ads"]["hidden"] == ["a"]


def test_load_prefs_empty_when_no_row(app):
    db = database.get_db()
    try:
        assert cp.load_prefs(db, 12345) == {}
    finally:
        db.close()


# ---------- 逻辑层：保存语义 ----------

def test_save_panel_prefs_keeps_other_panels(app):
    """保存一个面板不能清掉另一个面板的配置。"""
    db = database.get_db()
    try:
        cp.save_panel_prefs(db, 7001, "gg_ads", ["a"], [])
        cp.save_panel_prefs(db, 7001, "tt_ads", ["b"], ["b"])
        prefs = cp.load_prefs(db, 7001)
    finally:
        db.close()
    assert prefs["gg_ads"] == {"order": ["a"], "hidden": []}
    assert prefs["tt_ads"] == {"order": ["b"], "hidden": ["b"]}


def test_save_panel_prefs_rejects_unknown_panel(app):
    db = database.get_db()
    try:
        with pytest.raises(ValueError):
            cp.save_panel_prefs(db, 7002, "mcc", ["a"], [])
    finally:
        db.close()


def test_save_panel_prefs_prunes_hidden_not_in_order(app):
    db = database.get_db()
    try:
        prefs = cp.save_panel_prefs(db, 7003, "gg_ads", ["a"], ["ghost", "a"])
    finally:
        db.close()
    assert prefs["gg_ads"]["hidden"] == ["a"]


# ---------- 路由层 ----------

def _login(client, username, password="test123"):
    """注册并登录，返回 (headers, uid)。

    必须断言登录成功：空 token 会让「隔离」用例退化成两个 401 相互空转，
    看着是绿的其实什么都没验证。
    """
    client.post("/api/auth/register", json={"username": username, "password": password})
    resp = client.post("/api/auth/login", json={"username": username, "password": password})
    assert resp.status_code == 200, resp.get_json()
    data = resp.get_json()
    token = data.get("access_token", "")
    assert token, f"登录未返回 token：{data}"
    return {"Authorization": f"Bearer {token}"}, data["user"]["id"]


@pytest.fixture
def alice(client):
    return _login(client, "alice01")


@pytest.fixture
def bob(client):
    return _login(client, "bob0001")


def test_get_returns_empty_prefs_when_unset(client, alice):
    headers, _ = alice
    resp = client.get(URL, headers=headers)
    assert resp.status_code == 200
    assert resp.get_json()["prefs"] == {}


def test_put_then_get_roundtrip(client, alice):
    headers, _ = alice
    body = {"panel": "gg_ads", "order": ["a", "b", "c"], "hidden": ["c"]}
    resp = client.put(URL, json=body, headers=headers)
    assert resp.status_code == 200
    assert resp.get_json()["prefs"]["gg_ads"] == {"order": ["a", "b", "c"], "hidden": ["c"]}

    resp = client.get(URL, headers=headers)
    assert resp.get_json()["prefs"]["gg_ads"] == {"order": ["a", "b", "c"], "hidden": ["c"]}


def test_put_one_panel_keeps_the_other(client, alice):
    headers, _ = alice
    client.put(URL, json={"panel": "gg_ads", "order": ["a"], "hidden": []}, headers=headers)
    client.put(URL, json={"panel": "tt_ads", "order": ["b"], "hidden": []}, headers=headers)
    prefs = client.get(URL, headers=headers).get_json()["prefs"]
    assert set(prefs) == {"gg_ads", "tt_ads"}
    assert prefs["gg_ads"]["order"] == ["a"]


def test_prefs_are_isolated_per_user(client, alice, bob):
    """A 保存后，B 读不到 A 的配置 —— 本功能的权限边界。"""
    a_headers, _ = alice
    b_headers, _ = bob
    client.put(URL, json={"panel": "gg_ads", "order": ["secret"], "hidden": []}, headers=a_headers)

    assert client.get(URL, headers=b_headers).get_json()["prefs"] == {}
    # 反向再确认一次：B 写入不影响 A
    client.put(URL, json={"panel": "gg_ads", "order": ["bonly"], "hidden": []}, headers=b_headers)
    assert client.get(URL, headers=a_headers).get_json()["prefs"]["gg_ads"]["order"] == ["secret"]


def test_put_ignores_uid_in_body(client, alice, bob):
    """请求体里塞别人的 uid 不生效 —— uid 只认 JWT。"""
    a_headers, a_uid = alice
    b_headers, b_uid = bob
    client.put(URL, json={"panel": "gg_ads", "order": ["a"], "hidden": [], "uid": b_uid},
               headers=a_headers)
    assert client.get(URL, headers=b_headers).get_json()["prefs"] == {}


@pytest.mark.parametrize("body", [
    {},
    {"panel": "mcc", "order": ["a"], "hidden": []},
    {"panel": "gg_ads"},
    {"panel": "gg_ads", "order": "a", "hidden": []},
    {"panel": "gg_ads", "order": ["a", 1], "hidden": []},
    {"panel": "gg_ads", "order": [""], "hidden": []},
    {"panel": "gg_ads", "order": ["a" * 65], "hidden": []},
    {"panel": "gg_ads", "order": [f"k{i}" for i in range(65)], "hidden": []},   # 超 64 项
    {"panel": "gg_ads", "order": ["a"], "hidden": "x"},
    {"panel": "gg_ads", "order": ["a"], "hidden": [1]},
])
def test_put_rejects_malformed_body(client, alice, body):
    headers, _ = alice
    resp = client.put(URL, json=body, headers=headers)
    assert resp.status_code == 400, resp.get_json()


def test_endpoints_require_auth(client):
    assert client.get(URL).status_code == 401
    assert client.put(URL, json={"panel": "gg_ads", "order": [], "hidden": []}).status_code == 401


def test_get_does_not_500_on_garbage_stored_value(client, alice):
    """存量值被写脏时接口降级为 {}，而不是 500。"""
    headers, uid = alice
    _put_raw(uid, '{"gg_ads": "not a dict"}')
    resp = client.get(URL, headers=headers)
    assert resp.status_code == 200
    assert resp.get_json()["prefs"] == {}
