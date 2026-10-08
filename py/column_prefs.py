"""账户看板自定义列配置 — 用户级列显隐与顺序的持久化与校验。

设计见 docs/superpowers/specs/2026-10-08-account-column-prefs-design.md。
存储沿用 config 表（key 含 uid），形状与 huguan_dashboard_{uid} 一致：
每个面板存 {"order": [...], "hidden": [...]}。

为什么必须存两个字段：只存「可见列的有序数组」的话，「用户主动隐藏了 A 列」
与「A 列是代码里新加的」在数据上完全同形（都是「不在数组里」）。而新列策略要求
「不在配置里 → 追加到末尾并可见」，于是用户每隐藏一列，下次刷新就会被自动弹回来。
"""
import json

# 支持自定义列的面板。前端 constants/accountColumns.js 的 PANEL_KEYS
# 必须与这里逐字一致。
PANELS = ("gg_ads", "tt_ads", "fb_ads")

CONFIG_KEY = "dashboard_columns_{uid}"

# 形状上限。纯防御：正常配置撑死二十几列，64 是给未来留的余量。
MAX_KEYS = 64
MAX_KEY_LEN = 64


def _text(value) -> str:
    """配置值一律转字符串。

    不能写 `(value or "").strip()` —— config 表全仓共用，里面存的可能是数字
    或列表（真值非 str），`.strip()` 会直接 AttributeError 炸成 500。
    同类兜底先例见 huguan_dashboard._conf_text。
    """
    return "" if value is None else str(value)


def validate_key_list(raw):
    """请求体的**严格**校验：必须是字符串列表，去重后 ≤64 项、每项 ≤64 字符。

    合格返回净化后的列表；不合格返回 None（调用方回 400）。

    刻意**不校验**「key 是不是真实存在的列名」——语义白名单意味着列清单在
    Python 与 Vue 各存一份，将来加列时忘改一边就是线上静默失效。渲染端会与
    列注册表求交集，未知 key 根本不渲染，所以形状校验足够（设计 §4.3）。
    """
    if not isinstance(raw, list):
        return None
    # 先卡数量再逐项净化：否则一个百万项的请求体会被完整遍历一遍。
    # 净化只会让列表变短，所以这里卡住之后 out 必然不会超限。
    if len(raw) > MAX_KEYS:
        return None
    out = []
    for item in raw:
        if not isinstance(item, str):
            return None
        key = item.strip()
        if not key or len(key) > MAX_KEY_LEN:
            return None
        if key not in out:
            out.append(key)
    return out


def _lenient_key_list(raw):
    """存量值的**宽容**读取：能救就救，救不了返回 None。

    与 validate_key_list 的区别是刻意为之：请求体不合格要 400 打回，而
    存量脏数据只能降级——用户不该因为一个陈年脏值就再也打不开看板。
    """
    if not isinstance(raw, list):
        return None
    out = []
    for item in raw:
        key = _text(item).strip()
        if key and len(key) <= MAX_KEY_LEN and key not in out:
            out.append(key)
    return out[:MAX_KEYS]


def load_prefs(db, user_id: int) -> dict:
    """读取该用户的列配置：{panel: {"order": [...], "hidden": [...]}}。

    逐层判类型、能降级就降级，**绝不抛异常**。config 表是全仓共用的，
    读出来的可能是任何 JSON（数字、字符串、嵌套 list）。
    """
    row = db.execute("SELECT value FROM config WHERE key=?",
                     (CONFIG_KEY.format(uid=user_id),)).fetchone()
    if not row or not row["value"]:
        return {}
    try:
        loaded = json.loads(row["value"])
    except (ValueError, TypeError, RecursionError):
        # RecursionError 必须单列：它是 RuntimeError 的子类，**不属于**
        # ValueError/TypeError 族，光靠这两个接不住。超深嵌套 JSON（约 >1000 层）
        # 会让解析器爆栈，这是「任何畸形存量值都不许打成 500」这条不变量唯一
        # 没盖住的口子。触发需往共享 config 表写入病态深度，无合法路径可达
        # （写入端只落 ≤64 项扁平常量），纯防御。
        return {}
    if not isinstance(loaded, dict):
        return {}

    prefs = {}
    for panel in PANELS:
        entry = loaded.get(panel)
        if not isinstance(entry, dict):
            continue                        # 面板值不是 dict：跳过，前端走默认
        order = _lenient_key_list(entry.get("order"))
        if order is None:
            continue                        # order 坏掉：整面板降级为默认
        # hidden 是**字段级**降级（设计 §4.4「该字段降级」）：hidden 坏掉只丢
        # 该字段、完好的 order 原样保留，整面板不连坐 —— 否则用户会白丢自己排好
        # 的列顺序。键缺失 / null / 非 list（数字、字符串、dict）都归一到空表。
        # 与 order 的处理刻意不对称：order 是面板的主结构，坏掉就无从渲染，故整
        # 面板降级（见上）。
        hidden = _lenient_key_list(entry.get("hidden")) or []
        prefs[panel] = {"order": order, "hidden": [k for k in hidden if k in order]}
    return prefs


def save_panel_prefs(db, user_id: int, panel: str, order, hidden) -> dict:
    """整体替换某面板的配置；其它面板保持不变（读-改-写）。

    传入的 order / hidden 必须已经过 validate_key_list。
    """
    if panel not in PANELS:
        raise ValueError(f"不支持的面板: {panel}")
    prefs = load_prefs(db, user_id)
    prefs[panel] = {
        "order": list(order),
        "hidden": [k for k in hidden if k in order],
    }
    db.execute("INSERT OR REPLACE INTO config(key,value) VALUES(?,?)",
               (CONFIG_KEY.format(uid=user_id), json.dumps(prefs, ensure_ascii=False)))
    db.commit()
    return prefs
