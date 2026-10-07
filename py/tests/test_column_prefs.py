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
