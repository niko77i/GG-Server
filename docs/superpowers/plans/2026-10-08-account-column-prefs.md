# 账户看板自定义列（按用户保存）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让三张主账户表（GG 广告账户 / TT 广告账户 / FB 账户）的每个用户能自己勾选显示哪些列、拖拽排列顺序，配置存服务端并绑定账号。

**Architecture:** 配置以 JSON 存在既有 `config` 表的 `dashboard_columns_{uid}` key 下，每个面板存 `order`（全部列的有序表）+ `hidden`（其中被隐藏的子集）两个字段。前端用 Pinia store 在 App 启动时拉一次，三张表共享；纯排序/过滤逻辑抽成无依赖的 `columnPrefsLogic.mjs`（可用 Node 内置测试运行器测）；各面板的 `<el-table-column>` 逐字保留，只外包一层 `<template v-for>` + `v-if` 分派，列序由数组驱动。

**Tech Stack:** Flask + SQLite（后端）、Vue 3 `<script setup>` + Pinia + Element Plus 2.9（前端）、pytest（后端测试）、`node --test`（前端纯逻辑测试，Node 18 内置，零新依赖）。

**设计文档:** `docs/superpowers/specs/2026-10-08-account-column-prefs-design.md`

## Global Constraints

- **不改单元格业务逻辑。** 三个面板的 `<el-table-column>` 内部 markup **逐字保留**，只允许「外包一层 `<template v-for>` + 加一条 `v-if`」和缩进变化。任何单元格内的表达式、事件、类名都不许改。
- **不引入任何新的前端 npm 依赖。** 拖拽用 HTML5 原生 `draggable`；前端测试用 Node 18 内置的 `node --test`。
- **uid 只从 JWT 取**（`routes/helpers.py` 的 `get_uid()`），**绝不从请求体读 uid**。
- **不做后端语义白名单。** 校验只查形状（`panel` 白名单、`order`/`hidden` 是字符串数组且 ≤64 项、每项 ≤64 字符）。不校验「key 是不是真实列名」。
- **`config` 表全仓共用。** 读出来的值可能是数字、字符串、嵌套 list 或坏 JSON。读取路径必须逐层判类型并降级，**任何畸形值都不许打成 500**。
- **锁定列**：`selection` 勾选框与「操作」列不进 `order`/`hidden`、不进候选列表、不可拖动。
- **零配置时视觉与改造前逐像素一致**：每个列的 `min-width` / `width` 必须逐字沿用现有模板里写死的值。
- **提交规范**：仓库有多会话共享工作区，**禁用 `git add -A`**，每次只 `git add` 本任务明确列出的文件。
- **不推送到 origin**（用户按「一批改完才推」的节拍）。

---

## 文件结构

**新建（后端）**
| 文件 | 职责 |
|---|---|
| `py/column_prefs.py` | 逻辑层：`PANELS` 常量、形状校验、宽容读取、读-改-写保存 |
| `py/routes/column_prefs_routes.py` | HTTP 层：取参 / 鉴权 / 调逻辑层，不做业务判断 |
| `py/tests/test_column_prefs.py` | 逻辑层 + 路由的 pytest |

**新建（前端）**
| 文件 | 职责 |
|---|---|
| `frontend/src/utils/columnPrefsLogic.mjs` | 纯函数：解析顺序、过滤可见、toggle、move。无 Vue/Pinia/axios 依赖 |
| `frontend/tests/columnPrefsLogic.test.mjs` | 上述纯函数的 `node --test` 用例 |
| `frontend/src/api/columnPrefs.js` | GET/PUT `/api/user/column-prefs` |
| `frontend/src/stores/columnPrefs.js` | Pinia：持有 prefs、App 启动预拉、debounce 保存、失败回滚 |
| `frontend/src/constants/accountColumns.js` | 三个面板的列注册表（列清单唯一真相源）+ `indexByKey` |
| `frontend/src/components/ColumnSettings.vue` | 设置弹层：勾选显隐 + 拖拽调序 + 恢复默认 |
| `frontend/src/components/cells/SheetWriteCell.vue` | 写表单元格（从 GG/TT 两份逐字复制品抽出） |
| `frontend/src/components/cells/OwnerCell.vue` | 户归属单元格（同上） |

**修改**
| 文件 | 改动 |
|---|---|
| `py/main.py:377` 附近 | 注册 `column_prefs_bp` |
| `frontend/package.json` | 加 `"test": "node --test tests/"` script |
| `frontend/src/App.vue` | 启动时 `columnPrefs.ensureLoaded()` |
| `frontend/src/views/AdsAccountPanel.vue` | 抽出两列 → 接入 ColumnSettings → v-for 改造 |
| `frontend/src/views/tt/TtAccountPanel.vue` | 同上 |
| `frontend/src/views/fb/FbAccountPanel.vue` | 接入 ColumnSettings → v-for 改造（无共享单元格） |

**任务依赖链**

```
1 (py 逻辑层) ──→ 2 (py 路由) ───────────────────────┐
3 (纯逻辑) ──→ 4 (store+api+App) ──→ 5 (ColumnSettings) │
                          │                             │
                          └──→ 6 (抽两个单元格组件) ──→ 7 (注册表 + GG) ──→ 8 (TT) ──→ 9 (FB)
                                                                                        │
1..9 ──────────────────────────────────────────────────────────────────────────→ 10 (端到端验收)
```

任务 3、4 与任务 1、2 之间没有依赖，可以并行。**任务 6 必须在 7 之前**（GG 面板要用抽出的组件），
且它本身也改 GG/TT 面板，所以排在面板改造之前。

---

## Task 1: 后端逻辑层 `py/column_prefs.py`

**Files:**
- Create: `py/column_prefs.py`
- Test: `py/tests/test_column_prefs.py`

**Interfaces:**
- Consumes: 无
- Produces:
  - `PANELS: tuple[str, ...]` = `("gg_ads", "tt_ads", "fb_ads")`
  - `CONFIG_KEY: str` = `"dashboard_columns_{uid}"`
  - `validate_key_list(raw) -> list[str] | None` —— 请求体严格校验，不合格返回 `None`
  - `load_prefs(db, user_id: int) -> dict` —— 宽容读取，永不抛异常
  - `save_panel_prefs(db, user_id: int, panel: str, order: list, hidden: list) -> dict` —— 读-改-写，返回保存后的完整 prefs

- [ ] **Step 1: 写失败测试**

创建 `py/tests/test_column_prefs.py`：

```python
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
    '{"gg_ads": {"order": ["a"], "hidden": 5}}',  # hidden 不是 list
])
def test_load_prefs_degrades_on_garbage(app, raw):
    """任何畸形存量值都必须降级，不许抛异常。"""
    _put_raw(9999, raw)
    db = database.get_db()
    try:
        prefs = cp.load_prefs(db, 9999)
    finally:
        db.close()
    assert prefs == {}, f"畸形值 {raw!r} 未被降级：{prefs}"


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
```

- [ ] **Step 2: 跑测试确认失败**

```bash
cd py && python -m pytest tests/test_column_prefs.py -v
```

预期：`ModuleNotFoundError: No module named 'column_prefs'`

- [ ] **Step 3: 实现 `py/column_prefs.py`**

```python
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
    except (ValueError, TypeError):
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
```

- [ ] **Step 4: 跑测试确认通过**

```bash
cd py && python -m pytest tests/test_column_prefs.py -v
```

预期：全部 PASS（13 个用例，其中参数化会展开成多条）

- [ ] **Step 5: 提交**

```bash
cd "D:/server/cc/GG-Server" && git add py/column_prefs.py py/tests/test_column_prefs.py && git commit -m "feat(column-prefs): 逻辑层 — 用户级列配置的校验与持久化

每面板存 order + hidden 两个字段。只存可见数组会让用户主动隐藏的列
被新列策略自动弹回，故必须分开存。

读取路径逐层判类型并降级，畸形存量值不 500；请求体路径严格校验回 400。
校验只做形状不做语义白名单，避免前后端两份列清单漂移。"
```

---

## Task 2: 后端路由 `py/routes/column_prefs_routes.py` + 注册

**Files:**
- Create: `py/routes/column_prefs_routes.py`
- Modify: `py/main.py`（在 `sheet_write_bp` 注册之后，约 377 行）
- Test: `py/tests/test_column_prefs.py`（追加路由用例）

**Interfaces:**
- Consumes: Task 1 的 `column_prefs.PANELS` / `validate_key_list` / `load_prefs` / `save_panel_prefs`
- Produces: 蓝图 `column_prefs_bp`，暴露
  - `GET /api/user/column-prefs` → `{"success": true, "prefs": {...}}`
  - `PUT /api/user/column-prefs`，body `{"panel": str, "order": [...], "hidden": [...]}` → `{"success": true, "prefs": {...}}`

- [ ] **Step 1: 写失败测试**

在 `py/tests/test_column_prefs.py` 末尾追加：

```python
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
```

- [ ] **Step 2: 跑测试确认失败**

```bash
cd py && python -m pytest tests/test_column_prefs.py -v -k "roundtrip or isolated or requires_auth"
```

预期：全部 FAIL（404，路由还不存在）

- [ ] **Step 3: 实现 `py/routes/column_prefs_routes.py`**

```python
"""账户看板自定义列配置的 HTTP 入口。

设计见 docs/superpowers/specs/2026-10-08-account-column-prefs-design.md。
本文件只做取参 / 鉴权 / 调逻辑层，校验与存储都在 column_prefs.py。
"""
from flask import Blueprint
from flask_jwt_extended import jwt_required

import column_prefs as cp
import database

from .helpers import ok, err, parse_body, get_uid

column_prefs_bp = Blueprint("column_prefs", __name__)


@column_prefs_bp.route("/api/user/column-prefs", methods=["GET"])
@jwt_required()
def column_prefs_get():
    """返回当前登录用户的全部面板列配置。无配置时 prefs 为 {}。"""
    uid = get_uid()
    if uid is None:
        return err("无法识别当前用户", 401)
    db = database.get_db()
    try:
        prefs = cp.load_prefs(db, uid)
    finally:
        db.close()
    return ok({"prefs": prefs})


@column_prefs_bp.route("/api/user/column-prefs", methods=["PUT"])
@jwt_required()
def column_prefs_put():
    """整体替换某个面板的列配置（order 与 hidden 一起提交）。

    uid 只从 JWT 取，**绝不从请求体读** —— config 的 key 内含 uid，
    接受请求体里的 uid 就等于允许任意用户改写他人的界面配置。
    """
    uid = get_uid()
    if uid is None:
        return err("无法识别当前用户", 401)

    body = parse_body()
    panel = body.get("panel")
    if panel not in cp.PANELS:
        return err(f"不支持的面板: {panel!r}")

    order = cp.validate_key_list(body.get("order"))
    if order is None:
        return err("order 必须是字符串数组，去重后不超过 64 项、每项不超过 64 字符")

    hidden = cp.validate_key_list(body.get("hidden", []))
    if hidden is None:
        return err("hidden 必须是字符串数组，不超过 64 项、每项不超过 64 字符")

    db = database.get_db()
    try:
        prefs = cp.save_panel_prefs(db, uid, panel, order, hidden)
    finally:
        db.close()
    return ok({"prefs": prefs})
```

- [ ] **Step 4: 注册蓝图**

在 `py/main.py` 找到这一处（约 377 行）：

```python
# 写表失败治理（跨平台）
from routes.sheet_write_routes import sheet_write_bp
app.register_blueprint(sheet_write_bp)
```

**在其后**插入：

```python
# 用户级界面偏好（账户看板自定义列）
from routes.column_prefs_routes import column_prefs_bp
app.register_blueprint(column_prefs_bp)
```

- [ ] **Step 5: 跑全部测试确认通过**

```bash
cd py && python -m pytest tests/test_column_prefs.py -v
```

预期：全部 PASS

- [ ] **Step 6: 跑一遍全量后端测试，确认没碰坏别的**

```bash
cd py && python -m pytest tests/ -q
```

预期：无新增失败（与改动前对比；若有既有失败，记录基线）

- [ ] **Step 7: 提交**

```bash
cd "D:/server/cc/GG-Server" && git add py/routes/column_prefs_routes.py py/main.py py/tests/test_column_prefs.py && git commit -m "feat(column-prefs): 路由 — GET/PUT /api/user/column-prefs

uid 只从 JWT 取，请求体里的 uid 被忽略（有专门用例覆盖）。
含 uid 隔离用例：两个真实用户互相读不到对方配置。"
```

---

## Task 3: 前端纯逻辑 `frontend/src/utils/columnPrefsLogic.mjs`

**Files:**
- Create: `frontend/src/utils/columnPrefsLogic.mjs`
- Test: `frontend/tests/columnPrefsLogic.test.mjs`
- Modify: `frontend/package.json`（加 test script）

> **为什么是 `.mjs` 而不是 `.js`**：`frontend/package.json` 没有 `"type": "module"`，
> 所以 Node 会把 `.js` 当 CommonJS 解析。Vite 不在乎（它自己转译），但 `node --test`
> 会直接在 `import` 上抛 `SyntaxError`。已实测：源文件用 `.js` 时报
> `Named export 'f' not found. The requested module is a CommonJS module`；
> 两边都用 `.mjs` 则正常，且 `node --test tests/` 能自动发现 `*.test.mjs`。
> 不选「给 package.json 加 `"type": "module"`」是因为那会改变 `frontend/` 下**所有**
> `.js` 的解析方式，波及面超出本功能需要。

**Interfaces:**
- Consumes: 无（纯函数，不 import 任何东西）
- Produces（后续 store 与组件依赖这些确切签名）：
  - `registryKeys(registry) -> string[]` —— 注册表数组 → key 数组（即默认顺序）
  - `indexByKey(registry) -> Record<string, object>` —— key → 列属性（**已剔除 `key` 与 `available`**，可直接 `v-bind`）
  - `resolveOrder(panelPref, registry, isAvailable) -> string[]` —— 完整顺序（含隐藏列，已剔陈旧、已追加新列）
  - `resolveVisible(panelPref, registry, isAvailable) -> string[]` —— 渲染顺序
  - `applyToggle(panelPref, registry, key, checked) -> {order, hidden}` —— 只改 `hidden`，不动 `order`
  - `applyMove(panelPref, registry, fromIndex, toIndex) -> {order, hidden}`
  - `isOnlyVisible(panelPref, registry, isAvailable, key) -> boolean` —— 取消勾选 key 是否会导致一个可见列都不剩

  `registry` 是数组，每项 `{key, label, ...列属性, available?}`；`available` 是 `(auth) => boolean`，缺省视为恒真。`panelPref` 是 `{order, hidden}` 或 `null`/`undefined`（无配置）。

  **参数约定**：`isAvailable` 恒为第 3 参，类型是 `(col) => boolean`（接收注册表里的一项，判断该列对当前角色是否可见）。它是谓词，**不是** auth store 对象。

- [ ] **Step 1: 写失败测试**

创建 `frontend/tests/columnPrefsLogic.test.mjs`：

```js
// 纯逻辑用例。运行：cd frontend && npm test
// 用 Node 18 内置的 node --test，不引入任何依赖。
// 扩展名必须是 .mjs —— package.json 没有 "type": "module"，.js 会被当 CJS 解析。
import { test } from 'node:test'
import assert from 'node:assert/strict'

import {
  registryKeys, indexByKey, resolveOrder, resolveVisible,
  applyToggle, applyMove, isOnlyVisible,
} from '../src/utils/columnPrefsLogic.mjs'

// 三列注册表：b 带角色闸门
const REG = [
  { key: 'a', label: 'A', minWidth: 100 },
  { key: 'b', label: 'B', width: 54, align: 'center', available: (auth) => auth.isHuguan },
  { key: 'c', label: 'C', minWidth: 120 },
]
// isAvailable 是谓词 (col) => boolean，接收注册表里的一项。三种口径：
const ALL = () => true                              // 谁都能看
const noGate = (col) => !col.available              // 只看不带闸门的列（模拟非户管的普通用户）
const gateOnly = (col) => Boolean(col.available)    // 只看带闸门的列（反向构造用）

test('registryKeys 返回数组声明顺序', () => {
  assert.deepEqual(registryKeys(REG), ['a', 'b', 'c'])
})

test('indexByKey 剔除 key 与 available，只留可 v-bind 的属性', () => {
  assert.deepEqual(indexByKey(REG), {
    a: { label: 'A', minWidth: 100 },
    b: { label: 'B', width: 54, align: 'center' },
    c: { label: 'C', minWidth: 120 },
  })
})

test('resolveOrder: 无配置时用注册表默认顺序', () => {
  assert.deepEqual(resolveOrder(null, REG, ALL), ['a', 'b', 'c'])
})

test('resolveOrder: 保留用户顺序（含隐藏列）', () => {
  const pref = { order: ['c', 'a', 'b'], hidden: ['a'] }
  assert.deepEqual(resolveOrder(pref, REG, ALL), ['c', 'a', 'b'])
})

test('resolveOrder: 剔除陈旧 key（列已从代码删除）', () => {
  const pref = { order: ['c', 'ghost', 'a', 'b'], hidden: [] }
  assert.deepEqual(resolveOrder(pref, REG, ALL), ['c', 'a', 'b'])
})

test('resolveOrder: 新列追加到末尾（这是「新列默认显示」策略的落点）', () => {
  const pref = { order: ['a', 'c'], hidden: [] }   // 用户配置里没有 b
  assert.deepEqual(resolveOrder(pref, REG, ALL), ['a', 'c', 'b'])
})

test('resolveOrder: 角色闸门过滤掉不可见的列', () => {
  const pref = { order: ['c', 'b', 'a'], hidden: [] }
  assert.deepEqual(resolveOrder(pref, REG, noGate), ['c', 'a'])
})

test('resolveVisible: 减去 hidden', () => {
  const pref = { order: ['c', 'a', 'b'], hidden: ['a'] }
  assert.deepEqual(resolveVisible(pref, REG, ALL), ['c', 'b'])
})

test('resolveVisible: 隐藏的列不会被新列策略弹回来（本设计自审抓出的缺陷）', () => {
  // 用户把 c 藏了。下次加载时 c 既在 order 里也在 hidden 里 —— 必须保持隐藏。
  const pref = { order: ['a', 'c'], hidden: ['c'] }
  assert.deepEqual(resolveVisible(pref, REG, ALL), ['a', 'b'])
})

test('applyToggle 隐藏：只往 hidden 加，order 原样不动', () => {
  const pref = { order: ['c', 'a', 'b'], hidden: [] }
  assert.deepEqual(applyToggle(pref, REG, ALL, 'a', false), {
    order: ['c', 'a', 'b'], hidden: ['a'],
  })
})

test('applyToggle 显示：从 hidden 移除，回到原位（不是末尾）', () => {
  const pref = { order: ['c', 'a', 'b'], hidden: ['a'] }
  assert.deepEqual(applyToggle(pref, REG, ALL, 'a', true), {
    order: ['c', 'a', 'b'], hidden: [],
  })
})

test('applyToggle 在无配置时也能工作', () => {
  assert.deepEqual(applyToggle(null, REG, ALL, 'b', false), {
    order: ['a', 'b', 'c'], hidden: ['b'],
  })
})

test('applyMove 把第 0 项移到第 2 位', () => {
  const pref = { order: ['a', 'b', 'c'], hidden: [] }
  assert.deepEqual(applyMove(pref, REG, ALL, 0, 2).order, ['b', 'c', 'a'])
})

test('applyMove 把第 2 项移到第 0 位', () => {
  const pref = { order: ['a', 'b', 'c'], hidden: [] }
  assert.deepEqual(applyMove(pref, REG, ALL, 2, 0).order, ['c', 'a', 'b'])
})

test('applyMove 不动 hidden', () => {
  const pref = { order: ['a', 'b', 'c'], hidden: ['b'] }
  assert.deepEqual(applyMove(pref, REG, ALL, 0, 2).hidden, ['b'])
})

test('applyMove 在无配置时以默认顺序为基准', () => {
  assert.deepEqual(applyMove(null, REG, ALL, 0, 1).order, ['b', 'a', 'c'])
})

test('applyMove 下标越界时原样返回，不抛异常', () => {
  const pref = { order: ['a', 'b', 'c'], hidden: [] }
  assert.deepEqual(applyMove(pref, REG, ALL, 0, 9).order, ['a', 'b', 'c'])
  assert.deepEqual(applyMove(pref, REG, ALL, -1, 0).order, ['a', 'b', 'c'])
})

test('isOnlyVisible: 还有别的可见列时返回 false', () => {
  const pref = { order: ['a', 'c'], hidden: ['c'] }   // 可见的是 a，加上新列的 b 共两列
  assert.equal(isOnlyVisible(pref, REG, ALL, 'a'), false)
})

test('isOnlyVisible: 只剩一列可见时返回 true', () => {
  // 非户管看不到带闸门的 b；c 被用户藏了 —— 可见的只剩 a
  const pref = { order: ['a', 'c'], hidden: ['c'] }
  assert.equal(isOnlyVisible(pref, REG, noGate, 'a'), true)
})

test('isOnlyVisible: 被角色闸门挡掉的列不算「可见」', () => {
  // 反向构造：只有带闸门的 b 可见，a 被挡掉且被用户藏了 —— 可见的只剩 b
  const pref = { order: ['a', 'b'], hidden: ['a'] }
  assert.equal(isOnlyVisible(pref, REG, gateOnly, 'b'), true)
})
```

- [ ] **Step 2: 跑测试确认失败**

```bash
cd frontend && node --test tests/
```

预期：FAIL —— `Cannot find module '../src/utils/columnPrefsLogic.mjs'`

- [ ] **Step 3: 实现 `frontend/src/utils/columnPrefsLogic.mjs`**

```js
/**
 * 账户看板自定义列 —— 纯逻辑层。
 *
 * **扩展名是 .mjs 而非 .js，是刻意的**：package.json 没有 "type": "module"，
 * Node 会把 .js 当 CommonJS 解析，node --test 跑这个文件时会直接
 * SyntaxError（Vite 不在乎，但测试在乎）。改扩展名比给整个 frontend/
 * 加 "type": "module" 的波及面小得多。
 *
 * 设计见 docs/superpowers/specs/2026-10-08-account-column-prefs-design.md。
 * 这里刻意不 import Vue / Pinia / axios：顺序解析与显隐计算是本功能最容易出错
 * 的部分（新列策略、陈旧 key、角色闸门三方交织），抽成纯函数才能用 Node 内置的
 * 测试运行器覆盖。Pinia store 只是这些函数的一层薄封装。
 *
 * 术语
 *   registry  列注册表（数组），每项 { key, label, ...可 v-bind 的列属性, available? }
 *             available 是 (auth) => boolean，缺省视为恒真
 *   panelPref 服务端存的单面板配置 { order: string[], hidden: string[] }，可缺省
 *   order     该面板「全部列」的有序表，可见的与隐藏的都在里面
 *   hidden    order 中被用户隐藏的 key 子集
 */

/** 注册表数组 → key 数组。数组声明顺序即默认显示顺序。 */
export function registryKeys(registry) {
  return registry.map((col) => col.key)
}

/** key → 列属性。剔除 key 与 available，产物可直接 v-bind 到 el-table-column。 */
export function indexByKey(registry) {
  const out = {}
  for (const col of registry) {
    const { key, available, ...attrs } = col
    out[key] = attrs
  }
  return out
}

function available(col, isAvailable) {
  return !col.available || isAvailable(col)
}

/**
 * 解析出该面板的完整顺序表（含隐藏列）。顺序：
 *   1. 用户存过的 order；没有则用注册表默认顺序
 *   2. 剔除陈旧 key（代码里已不存在的列）与角色不可见的列
 *   3. 注册表里存在、但用户 order 里没有的**新列追加到末尾**
 *
 * 第 3 步就是「新列默认显示、追加到末尾」策略的落点。
 */
export function resolveOrder(panelPref, registry, isAvailable) {
  const cols = registry.filter((col) => available(col, isAvailable))
  const known = new Set(cols.map((col) => col.key))
  const base = Array.isArray(panelPref?.order) && panelPref.order.length
    ? panelPref.order
    : registryKeys(registry)

  const kept = base.filter((key) => known.has(key))
  const seen = new Set(kept)
  const appended = cols.map((col) => col.key).filter((key) => !seen.has(key))
  return [...kept, ...appended]
}

/** 实际渲染顺序 = 完整顺序减去 hidden。 */
export function resolveVisible(panelPref, registry, isAvailable) {
  const hidden = new Set(panelPref?.hidden ?? [])
  return resolveOrder(panelPref, registry, isAvailable).filter((key) => !hidden.has(key))
}

/** 净化为 { order, hidden }，hidden 按 order 排序并裁剪到 order 之内。 */
function normalize(panelPref, registry, isAvailable) {
  const order = resolveOrder(panelPref, registry, isAvailable)
  const hiddenSet = new Set(panelPref?.hidden ?? [])
  return { order, hidden: order.filter((key) => hiddenSet.has(key)) }
}

/** 勾选/取消勾选：只改 hidden，**不动 order**，所以再勾回来会回到原位而非末尾。 */
export function applyToggle(panelPref, registry, isAvailable, key, checked) {
  const { order, hidden } = normalize(panelPref, registry, isAvailable)
  const set = new Set(hidden)
  if (checked) set.delete(key)
  else set.add(key)
  return { order, hidden: order.filter((k) => set.has(k)) }
}

/** 拖拽调序：fromIndex / toIndex 是完整顺序表里的下标。越界则原样返回。 */
export function applyMove(panelPref, registry, isAvailable, fromIndex, toIndex) {
  const { order, hidden } = normalize(panelPref, registry, isAvailable)
  if (fromIndex === toIndex || fromIndex < 0 || toIndex < 0 ||
      fromIndex >= order.length || toIndex >= order.length) {
    return { order, hidden }
  }
  const next = [...order]
  const [moved] = next.splice(fromIndex, 1)
  next.splice(toIndex, 0, moved)
  return { order: next, hidden }
}

/**
 * 取消勾选 key 是否会导致一个可见列都不剩。
 * 会的话 UI 应该拦下 —— 只剩选择框和「操作」列的表格看着像坏了。
 */
export function isOnlyVisible(panelPref, registry, isAvailable, key) {
  const visible = resolveVisible(panelPref, registry, isAvailable)
  return visible.length === 1 && visible[0] === key
}
```

- [ ] **Step 4: 跑测试确认通过**

```bash
cd frontend && node --test tests/
```

预期：全部 PASS（19 个用例）

- [ ] **Step 5: 加 npm script**

`frontend/package.json` 的 `"scripts"` 里加一行（放在 `"dev"` 之前）：

```json
    "test": "node --test tests/",
```

- [ ] **Step 6: 用 npm 跑一次，确认 script 生效**

```bash
cd frontend && npm test
```

预期：与 Step 4 同样全部 PASS

- [ ] **Step 7: 提交**

```bash
cd "D:/server/cc/GG-Server" && git add frontend/src/utils/columnPrefsLogic.mjs frontend/tests/columnPrefsLogic.test.mjs frontend/package.json && git commit -m "feat(column-prefs): 前端纯逻辑 — 顺序解析与显隐计算

顺序解析是三件事交织的地方（新列追加策略、陈旧 key 剔除、角色闸门），
抽成不依赖 Vue/Pinia 的纯函数，用 Node 内置 node --test 覆盖，零新依赖。

用隐藏/恢复用例锁死本设计自审时抓出的缺陷：只存可见数组会让用户
主动隐藏的列被新列策略弹回来。"
```

---

## Task 4: Pinia store + API 模块 + App 启动预拉

**Files:**
- Create: `frontend/src/api/columnPrefs.js`
- Create: `frontend/src/stores/columnPrefs.js`
- Modify: `frontend/src/App.vue`（约 38-41 行的启动流程）

**Interfaces:**
- Consumes: Task 3 的全部纯函数；Task 2 的两个接口
- Produces: `useColumnPrefsStore()`，暴露
  - `ready: boolean` —— 首次拉取是否已**落定**（成功或失败都置 true）
  - `visibleOrder(panelKey, registry) -> string[]`
  - `settingsList(panelKey, registry) -> Array<{key, label, hidden}>`
  - `toggle(panelKey, registry, key, checked)`
  - `move(panelKey, registry, fromIndex, toIndex)`
  - `reset(panelKey, registry)`
  - `ensureLoaded() -> Promise<void>`

- [ ] **Step 1: 创建 API 模块**

`frontend/src/api/columnPrefs.js`：

```js
import client from './client'

export const columnPrefsApi = {
  // 拿当前登录用户的全部面板列配置
  get() {
    return client.get('/user/column-prefs')
  },
  // 整体替换某个面板的配置
  save(panel, order, hidden) {
    return client.put('/user/column-prefs', { panel, order, hidden })
  },
}
```

> `frontend/src/api/client.js:3` 是 `axios.create({ baseURL: '/api', ... })`，所以这里写 `/user/column-prefs` 即请求 `/api/user/column-prefs`。`client.js` 的请求拦截器会自动带上 `Authorization` 头，无需手动处理。

- [ ] **Step 2: 创建 store**

`frontend/src/stores/columnPrefs.js`：

```js
import { defineStore } from 'pinia'
import { ref } from 'vue'
import { ElMessage } from 'element-plus'

import { columnPrefsApi } from '@/api/columnPrefs'
import {
  registryKeys, resolveOrder, resolveVisible, applyToggle, applyMove, isOnlyVisible,
} from '@/utils/columnPrefsLogic.mjs'
import { useAuthStore } from '@/stores/auth'

// 保存去抖窗口。拖一次会连发十几个变更，不防抖就是一串请求。
const SAVE_DEBOUNCE_MS = 400

export const useColumnPrefsStore = defineStore('columnPrefs', () => {
  const prefs = ref({})           // 服务端原始 JSON：{panel: {order, hidden}}
  const ready = ref(false)        // 首次拉取是否已落定（成功或失败都置 true）

  let loadPromise = null          // 启动预拉的单例，避免多个面板各拉一次
  const saveTimers = {}           // panelKey -> timer

  // 没有配置的面板用空 pref，纯函数会走注册表默认顺序
  function prefOf(panelKey) {
    return prefs.value?.[panelKey] ?? null
  }

  function isAvailable() {
    const auth = useAuthStore()
    return (col) => !col.available || col.available(auth)
  }

  function visibleOrder(panelKey, registry) {
    return resolveVisible(prefOf(panelKey), registry, isAvailable())
  }

  /** 设置弹层用：完整顺序（含隐藏列），每项带上 label 与 hidden 标记。 */
  function settingsList(panelKey, registry) {
    const order = resolveOrder(prefOf(panelKey), registry, isAvailable())
    const hidden = new Set(prefOf(panelKey)?.hidden ?? [])
    const byKey = Object.fromEntries(registry.map((c) => [c.key, c]))
    return order.map((key) => ({
      key,
      label: byKey[key]?.label ?? key,
      hidden: hidden.has(key),
    }))
  }

  // 服务端已确认的状态，回滚用
  let lastConfirmed = {}

  async function ensureLoaded() {
    if (ready.value) return
    if (loadPromise) return loadPromise
    loadPromise = (async () => {
      try {
        const resp = await columnPrefsApi.get()
        prefs.value = resp.data?.prefs ?? {}
        lastConfirmed = JSON.parse(JSON.stringify(prefs.value))
      } catch (e) {
        // 拉不到就退回默认列。**绝不能让 ready 停在 false** —— 面板的表格
        // 等 ready 才挂载，卡住就是整张表永远不显示，比列序不对严重得多。
        ElMessage.error('列配置加载失败，已使用默认列')
      } finally {
        ready.value = true
      }
    })()
    return loadPromise
  }

  function scheduleSave(panelKey, registry) {
    clearTimeout(saveTimers[panelKey])
    saveTimers[panelKey] = setTimeout(() => {
      const pref = prefOf(panelKey) ?? { order: registryKeys(registry), hidden: [] }
      columnPrefsApi.save(panelKey, pref.order, pref.hidden).then((resp) => {
        // 以服务端回写的完整 prefs 为准，并更新「已确认」快照 —— 不回写的话
        // 「连续改两次、第二次失败」会回滚到很久以前的陈旧状态。
        prefs.value = resp.data?.prefs ?? prefs.value
        lastConfirmed = JSON.parse(JSON.stringify(prefs.value))
      }).catch(() => {
        // 失败回滚到上次服务端确认的状态，不留「界面显示已保存、其实没存上」的假象
        ElMessage.error('列配置保存失败，已还原')
        prefs.value = JSON.parse(JSON.stringify(lastConfirmed))
      })
    }, SAVE_DEBOUNCE_MS)
  }

  function commit(panelKey, registry, next) {
    prefs.value = { ...prefs.value, [panelKey]: next }
    scheduleSave(panelKey, registry)
  }

  function toggle(panelKey, registry, key, checked) {
    commit(panelKey, registry, applyToggle(prefOf(panelKey), registry, isAvailable(), key, checked))
  }

  function move(panelKey, registry, fromIndex, toIndex) {
    commit(panelKey, registry, applyMove(prefOf(panelKey), registry, isAvailable(), fromIndex, toIndex))
  }

  function reset(panelKey, registry) {
    commit(panelKey, registry, { order: registryKeys(registry), hidden: [] })
  }

  /** 取消勾选这一列会不会让表格一列数据都不剩（UI 据此禁用勾选框）。 */
  function onlyVisible(panelKey, registry, key) {
    return isOnlyVisible(prefOf(panelKey), registry, isAvailable(), key)
  }

  return {
    prefs, ready,
    visibleOrder, settingsList, onlyVisible,
    toggle, move, reset,
    ensureLoaded,
  }
})
```

- [ ] **Step 3: App 启动时预拉**

`frontend/src/App.vue` 找到（约 38-41 行）：

```js
auth.initFromStorage()
auth.fetchMe()
```

在同一处补上：

```js
columnPrefs.ensureLoaded()
```

并在 `<script setup>` 的 import 区加：

```js
import { useColumnPrefsStore } from '@/stores/columnPrefs'
```

以及实例化（跟在 `const auth = useAuthStore()` 一类语句之后）：

```js
const columnPrefs = useColumnPrefsStore()
```

- [ ] **Step 4: 起前端确认不报错**

```bash
cd frontend && npm run dev
```

打开任意页面，浏览器控制台**不应有**关于 `columnPrefs` 的报错；Network 里应看到一次 `GET /api/user/column-prefs` 返回 200。

> 后端需要同时在跑（5001）。若不便启动后端，可先跳过网络断言，只确认无 import / 语法错误，并在 Task 10 补验。

- [ ] **Step 5: 提交**

```bash
cd "D:/server/cc/GG-Server" && git add frontend/src/api/columnPrefs.js frontend/src/stores/columnPrefs.js frontend/src/App.vue && git commit -m "feat(column-prefs): Pinia store + 启动预拉

三个面板共享同一份配置、App 启动时只拉一次。
防抖 400ms 保存；失败回滚到上次服务端确认的状态。

拉取失败时 ready 也置 true —— 面板的表格等 ready 才挂载，
卡在 false 就是整张表永远不显示。"
```

---

## Task 5: `/frontend-design` 视觉设计 + `ColumnSettings.vue`

**Files:**
- Create: `frontend/src/components/ColumnSettings.vue`
- Modify: Task 7-9 各面板的筛选栏（本任务只建组件，不接入）

**Interfaces:**
- Consumes: `useColumnPrefsStore()`（Task 4）
- Produces: `<ColumnSettings :panel-key="string" :registry="Array" />`，自包含（自己去 store 拿数据，面板只需给两个 prop）

- [ ] **Step 1: 调用 `/frontend-design`**

本项目规范要求：新增 UI（新组件 + 新交互）必须先做视觉设计。执行：

```
/frontend-design
```

**给设计的输入（务必带上）：**
1. 组件是一个 `el-popover` 弹层，形态参考现有 `frontend/src/views/DataManageView.vue:30-43` 的「📊 列显示」弹层，触发按钮放在各面板的筛选栏里。
2. 内容是一个 20 项以内的列表：拖拽手柄 + 列名 + 勾选框。**列表顺序 = 显示顺序**，所以视觉上要让「拖动」这件事显而易见。
3. 底部有「恢复默认」。
4. 三种状态要区分：可拖（默认）、正在拖（被拖项与落点）、以及「不能再取消了」（只剩一列可见时，勾选框禁用 + 提示文案）。
5. 已知无障碍缺口、需要在视觉上补偿：拖拽是鼠标手势，键盘用户无法调序。设计需给出视觉上的替代线索；若设计认为应加 ↑↓ 按钮，作为本任务范围内的补充实现。
6. 依赖 Element Plus 现有组件与既有配色，不引入新依赖。

**把设计产出的关键决策（间距 / 手柄样式 / 拖拽态表现 / 禁用态文案）记录到设计文档附录**，然后在 Step 2 落地。

- [ ] **Step 2: 实现组件**

`frontend/src/components/ColumnSettings.vue`（结构与交互骨架如下；视觉细节按 Step 1 的设计产出调整）：

```vue
<template>
  <el-popover placement="bottom-start" :width="260" trigger="click">
    <template #reference>
      <el-button>📊 列显示</el-button>
    </template>
    <div class="column-settings">
      <div class="column-settings__title">拖动调整顺序，取消勾选隐藏</div>
      <ul class="column-settings__list">
        <li
          v-for="(col, i) in list" :key="col.key"
          class="column-settings__item"
          :class="{
            'is-dragging': dragIndex === i,
            'is-over': overIndex === i && dragIndex !== i,
          }"
          draggable="true"
          @dragstart="onDragStart(i)"
          @dragover.prevent="onDragOver(i)"
          @drop.prevent="onDrop(i)"
          @dragend="onDragEnd"
        >
          <span class="column-settings__handle" aria-hidden="true">⠿</span>
          <el-checkbox
            :model-value="!col.hidden"
            :disabled="isLockedKey(col.key)"
            @change="(v) => onToggle(col.key, v)"
          >{{ col.label }}</el-checkbox>
        </li>
      </ul>
      <div class="column-settings__footer">
        <el-button link size="small" @click="onReset">恢复默认</el-button>
      </div>
    </div>
  </el-popover>
</template>

<script setup>
import { computed, ref } from 'vue'
import { ElMessage } from 'element-plus'

import { useColumnPrefsStore } from '@/stores/columnPrefs'

const props = defineProps({
  panelKey: { type: String, required: true },
  registry: { type: Array, required: true },
})

const store = useColumnPrefsStore()

const list = computed(() => store.settingsList(props.panelKey, props.registry))

// 只剩这一列可见时不许再取消，否则表格只剩选择框和「操作」列，用户会以为坏了
function isLockedKey(key) {
  return store.onlyVisible(props.panelKey, props.registry, key)
}

function onToggle(key, checked) {
  store.toggle(props.panelKey, props.registry, key, checked)
}

function onReset() {
  store.reset(props.panelKey, props.registry)
  ElMessage.success('已恢复默认列')
}

// --- 原生 HTML5 拖拽（不引入 sortablejs） ---
const dragIndex = ref(-1)
const overIndex = ref(-1)

function onDragStart(i) { dragIndex.value = i }
function onDragOver(i) { overIndex.value = i }

function onDrop(i) {
  if (dragIndex.value > -1 && dragIndex.value !== i) {
    store.move(props.panelKey, props.registry, dragIndex.value, i)
  }
  onDragEnd()
}

function onDragEnd() {
  dragIndex.value = -1
  overIndex.value = -1
}
</script>
```

- [ ] **Step 3: 起前端做一次人工检查**

```bash
cd frontend && npm run dev
```

把 `<ColumnSettings>` 临时挂到 GG 面板的筛选栏里，（Task 7 会正式接入），确认：
1. 弹层能打开，列出全部数据列
2. 勾选/取消勾选立即影响表格
3. 拖动列表项能改列序
4. 「恢复默认」生效
5. 只剩一列可见时该项的勾选框被禁用

> 若第 3 条**不生效**，立刻停下来 —— 这正是设计 §8.1 标记的风险。按设计给的兜底方案处理：给 `<el-table>` 绑 `:key="orderKey"`，顺序变更时 bump。**不要**改成「刷新后才生效」就交付。

- [ ] **Step 4: 提交**

```bash
cd "D:/server/cc/GG-Server" && git add frontend/src/components/ColumnSettings.vue docs/superpowers/specs/2026-10-08-account-column-prefs-design.md && git commit -m "feat(column-prefs): ColumnSettings 设置弹层

勾选显隐 + HTML5 原生拖拽调序 + 恢复默认。
只剩一列可见时禁用该项勾选框，避免表格看着像坏了。
拖拽用原生 draggable，不引入 sortablejs。"
```

---

## Task 6: 抽出 `SheetWriteCell.vue` / `OwnerCell.vue`（行为保持不变）

**Files:**
- Create: `frontend/src/components/cells/SheetWriteCell.vue`
- Create: `frontend/src/components/cells/OwnerCell.vue`
- Modify: `frontend/src/views/AdsAccountPanel.vue:63-78`（写表列）、`:163-212`（户归属单元格）
- Modify: `frontend/src/views/tt/TtAccountPanel.vue:59-71`（写表列）、`:198-247`（户归属单元格）

**Interfaces:**
- Consumes: 无（纯展示组件）
- Produces:
  - `<SheetWriteCell :row="object" :failure="object|undefined" @retry="fn" />`
  - `<OwnerCell :row="object" :account-key="string" :loaded="bool" :failed="bool" :options="Array" :option-map="object" :pending="Set" @change="fn" />`

**这是一次纯粹的行为保持重构 —— 不改任何单元格逻辑。** 抽完后 GG / TT 的写表与户归属两列必须与抽取前逐字一致。

- [ ] **Step 1: 记录抽取前的基线**

把要搬的两块 markup 原样记下来（后面要逐字比对）：

```bash
cd "D:/server/cc/GG-Server/frontend/src/views" && sed -n '63,78p' AdsAccountPanel.vue && echo "=====" && sed -n '156,213p' AdsAccountPanel.vue
```

- [ ] **Step 2: 创建 `SheetWriteCell.vue`**

markup 从 `TtAccountPanel.vue:59-71` 逐字搬入（与 GG 版同构，只差 `row.account_id` / `row.advertiser_id` 这个取值字段）：

```vue
<template>
  <template v-if="failure">
    <el-tooltip placement="top" :content="hint(failure)">
      <el-button link size="small" :type="tone(failure.status)"
        @click.stop="$emit('retry')">{{ mark(failure.status) }}</el-button>
    </el-tooltip>
  </template>
  <span v-else style="color:#16a34a;font-size:14px;">✅</span>
</template>

<script setup>
// 「写表」列单元格。GG 与 TT 原本各有一份逐字复制的 markup（注释自述
// 「语汇 / 位置 / 宽度逐字沿用」），这里合并为一份，改一处两平台同时生效。
import { sheetWriteMark as mark, sheetWriteTone as tone, sheetWriteHint as hint } from '@/utils/sheetWriteUi'

defineProps({
  row: { type: Object, required: true },
  failure: { type: Object, default: null },
})
defineEmits(['retry'])
</script>
```

> `row` 目前未被模板直接使用，但保留它是因为：① 调用方语义清晰（这是某一行的单元格）；② 将来要在单元格里显示行相关信息的改动不必再改接口。若担心 lint 报未使用，可在模板里不加 `row` 引用并接受 prop 仅作为契约。

- [ ] **Step 3: 创建 `OwnerCell.vue`**

markup 从 `AdsAccountPanel.vue:163-212` 逐字搬入，把 6 处外部依赖改成 props / emit：

| 面板内原名 | 组件内改为 |
|---|---|
| `ownerOptionsLoaded` | `props.loaded` |
| `ownerOptionsFailed` | `props.failed` |
| `ownerOptionMap` | `props.optionMap` |
| `ownerOptions` | `props.options` |
| `ownerPending` | `props.pending` |
| `row.account_id`（GG）/ `row.advertiser_id`（TT） | `row[props.accountKey]` |
| `changeOwner(row, v)` | `$emit('change', v)` |

```vue
<template>
  <div class="owner-cell">
    <!-- ① 加载中：不用裸 el-select，否则会退化成显示裸 owner_id 数字（§5.4） -->
    <el-skeleton v-if="!loaded" :rows="1" animated />
    <!-- ⑤ 失败态：列表没回来，写操作不能静默（§5.6） -->
    <el-select v-else-if="failed" :model-value="null" size="small" disabled
      style="width:100%;" placeholder="暂时无法加载用户列表"
      :aria-label="`账户 ${row[accountKey]} 的户归属`" />
    <!-- ③ 未知归属：不在列表里（账号可能已停用），禁用并说明，不让户管以为能保持现状（§5.4） -->
    <el-tooltip v-else-if="row.owner_id && !optionMap[row.owner_id]"
      content="这个归属人不在用户列表里（账号可能已停用）。请重新选择。">
      <el-select :model-value="row.owner_id" size="small" filterable disabled
        style="width:100%;" placeholder="未知用户"
        :aria-label="`账户 ${row[accountKey]} 的户归属`">
        <el-option :key="row.owner_id" :label="`用户 #${row.owner_id}`" :value="row.owner_id" />
      </el-select>
    </el-tooltip>
    <!-- ④ 未分配 -->
    <el-tooltip v-else-if="!row.owner_id"
      content="这个账户还没有归属人，普通用户看不到它，只有户管和管理员可见。">
      <el-select :model-value="row.owner_id" size="small" filterable
        placeholder="未分配" style="width:100%;"
        :disabled="pending.has(row.id)"
        :aria-label="`账户 ${row[accountKey]} 的户归属`"
        @change="(v) => $emit('change', v)">
        <el-option v-for="u in options" :key="u.id"
          :label="u.display_name || u.username" :value="u.id" />
        <template #empty>
          <div style="padding:8px 12px;font-size:12px;color:#6b7280;line-height:1.6;">
            没有匹配的用户。<br />停用的账号不会出现在这里。
          </div>
        </template>
      </el-select>
    </el-tooltip>
    <!-- ② 正常 -->
    <el-select v-else :model-value="row.owner_id" size="small" filterable
      placeholder="未分配" style="width:100%;"
      :disabled="pending.has(row.id)"
      :aria-label="`账户 ${row[accountKey]} 的户归属`"
      @change="(v) => $emit('change', v)">
      <el-option v-for="u in options" :key="u.id"
        :label="u.display_name || u.username" :value="u.id" />
      <template #empty>
        <div style="padding:8px 12px;font-size:12px;color:#6b7280;line-height:1.6;">
          没有匹配的用户。<br />停用的账号不会出现在这里。
        </div>
      </template>
    </el-select>
  </div>
</template>

<script setup>
// 「户归属」列单元格。GG 与 TT 原本各有一份逐字复制的 markup（注释自述
// 「GG 与 TT 逐字同构，只差 reassign 实现」）——逻辑早已抽到 useOwnerPicker，
// 只剩 markup 是两份。这里合并。
//
// 唯一差异：aria-label 里用的账户标识字段，GG 是 account_id、TT 是 advertiser_id，
// 故做成 accountKey prop。**漏掉这一项会让 TT 的无障碍标签变成 undefined**，
// 是本次抽取最容易出错的地方。
defineProps({
  row: { type: Object, required: true },
  accountKey: { type: String, required: true },
  loaded: { type: Boolean, default: false },
  failed: { type: Boolean, default: false },
  options: { type: Array, default: () => [] },
  optionMap: { type: Object, default: () => ({}) },
  pending: { type: Set, default: () => new Set() },
})
defineEmits(['change'])
</script>
```

- [ ] **Step 4: 改 GG 面板两处调用点**

`AdsAccountPanel.vue`，在 `<script setup>` 的 import 区加：

```js
import SheetWriteCell from '@/components/cells/SheetWriteCell.vue'
import OwnerCell from '@/components/cells/OwnerCell.vue'
```

把写表列的 `<template #default>` 内容（原 67-77 行）替换为：

```html
          <template #default="{ row }">
            <SheetWriteCell :row="row" :failure="sheetWriteFailures[row.account_id]"
              @retry="retrySheetWrite(row)" />
          </template>
```

把户归属列的 `<template #default>` 内容（原 163-212 行）替换为：

```html
          <template #default="{ row }">
            <OwnerCell :row="row" account-key="account_id"
              :loaded="ownerOptionsLoaded" :failed="ownerOptionsFailed"
              :options="ownerOptions" :option-map="ownerOptionMap"
              :pending="ownerPending"
              @change="(v) => changeOwner(row, v)" />
          </template>
```

**`<template #header>` 保持原样不动**（那是静态 markup，只有 5 行，且不随行变化）。

- [ ] **Step 5: 改 TT 面板两处调用点**

`TtAccountPanel.vue`，同样先加两个 import，然后：

写表列 `<template #default>` →

```html
          <template #default="{ row }">
            <SheetWriteCell :row="row" :failure="sheetWriteFailures[row.advertiser_id]"
              @retry="retrySheetWrite(row)" />
          </template>
```

户归属列 `<template #default>` →

```html
          <template #default="{ row }">
            <OwnerCell :row="row" account-key="advertiser_id"
              :loaded="ownerOptionsLoaded" :failed="ownerOptionsFailed"
              :options="ownerOptions" :option-map="ownerOptionMap"
              :pending="ownerPending"
              @change="(v) => changeOwner(row, v)" />
          </template>
```

- [ ] **Step 6: 起前端逐项人工验收（两个平台各一遍）**

```bash
cd frontend && npm run dev
```

**GG 页（`/accounts/ads`）**：以户管账号登录，逐项确认
1. 写表列：无失败的行显示 ✅；构造一个失败态（或看日志里已有的失败行），确认 ⚠️ 的悬浮提示文案与点击重试与改前一致
2. 户归属列：加载中显示骨架；正常行显示下拉；改一个归属，确认保存成功
3. 未分配行显示「未分配」placeholder
4. **用浏览器 DevTools 检查某个户归属下拉的 `aria-label`，必须是 `账户 <真实 account_id> 的户归属`** —— 不能出现 `undefined`

**TT 页（`/tt/accounts`）**：同样 4 项。**第 4 项尤其重要**，这里必须是 `advertiser_id`，这是抽取里唯一的真实差异点。

- [ ] **Step 7: 提交**

```bash
cd "D:/server/cc/GG-Server" && git add frontend/src/components/cells/SheetWriteCell.vue frontend/src/components/cells/OwnerCell.vue frontend/src/views/AdsAccountPanel.vue frontend/src/views/tt/TtAccountPanel.vue && git commit -m "refactor(cells): 抽出写入与户归属两个单元格组件

「写表」列 GG/TT 各有一份逐字复制的 markup；「户归属」列的逻辑早已
抽到 useOwnerPicker，但 markup 仍是两份（各约 57 行）。合并为共享组件。

唯一差异是 aria-label 里的账户标识字段（GG account_id / TT advertiser_id），
做成 accountKey prop。行为保持不变，未改任何单元格逻辑。"
```

---

## Task 7: `constants/accountColumns.js` + GG 面板 v-for 改造

**Files:**
- Create: `frontend/src/constants/accountColumns.js`
- Modify: `frontend/src/views/AdsAccountPanel.vue:47-222`（`<el-table>` 区块）
- Modify: `frontend/src/views/AdsAccountPanel.vue` 筛选栏（接入 `<ColumnSettings>`）

**Interfaces:**
- Consumes: Task 3 的 `indexByKey`；Task 4 的 `useColumnPrefsStore`；Task 5 的 `ColumnSettings`
- Produces: `PANEL_KEYS`、`GG_ADS_COLUMNS`、`TT_ADS_COLUMNS`、`FB_ADS_COLUMNS`（后两个在 Task 8/9 用到，本任务一并定义好，避免三次改同一个文件）

- [ ] **Step 1: 创建列注册表**

`frontend/src/constants/accountColumns.js`：

```js
/**
 * 账户看板三张表的列注册表 —— 列清单的唯一真相源。
 *
 * 设计见 docs/superpowers/specs/2026-10-08-account-column-prefs-design.md。
 * - 数组声明顺序 = 默认显示顺序（不依赖对象 key 顺序语义）
 * - 每项的宽度属性逐字沿用各面板改造前模板里写死的值，
 *   保证零配置时视觉与改造前逐像素一致
 * - available 承接原有的角色闸门（原先散落在模板里的 v-if="authStore.isHuguan"）
 *
 * panel key 必须与 py/column_prefs.py 的 PANELS 逐字一致。
 */

export const PANEL_KEYS = {
  GG_ADS: 'gg_ads',
  TT_ADS: 'tt_ads',
  FB_ADS: 'fb_ads',
}

export const GG_ADS_COLUMNS = [
  { key: 'name', label: '账号名称', minWidth: 140 },
  { key: 'account_id', prop: 'account_id', label: '账号 ID', minWidth: 140, showOverflowTooltip: true },
  { key: 'sheet_write', label: '写表', width: 54, align: 'center' },
  { key: 'mcc', label: '所属 MCC', minWidth: 140 },
  { key: 'timezone', label: '时区', minWidth: 120 },
  { key: 'agent', label: '代理', minWidth: 140 },
  { key: 'status', label: '状态', minWidth: 120 },
  { key: 'acquired_date', prop: 'acquired_date', label: '到手时间', minWidth: 100, showOverflowTooltip: true },
  { key: 'status_changed', label: '状态变更时间', minWidth: 110, showOverflowTooltip: true },
  { key: 'owner', label: '户归属', width: 160, align: 'center', available: (auth) => auth.isHuguan },
]

export const TT_ADS_COLUMNS = [
  { key: 'advertiser_id', prop: 'advertiser_id', label: '广告账户 ID', minWidth: 150, showOverflowTooltip: true },
  { key: 'sheet_write', label: '写表', width: 54, align: 'center' },
  { key: 'bc', label: '所属 BC', minWidth: 160 },
  { key: 'timezone', label: '时区', minWidth: 120 },
  { key: 'agent', label: '代理', minWidth: 140 },
  { key: 'status', label: '状态', minWidth: 120 },
  { key: 'country', label: '国家', minWidth: 110 },
  { key: 'consumption', label: '消耗情况', minWidth: 120 },
  { key: 'remark', label: '备注', minWidth: 160 },
  { key: 'acquired_date', prop: 'acquired_date', label: '到手时间', minWidth: 100, showOverflowTooltip: true },
  { key: 'status_changed', label: '状态变更时间', minWidth: 110, showOverflowTooltip: true },
  { key: 'owner', label: '户归属', width: 160, align: 'center', available: (auth) => auth.isHuguan },
  { key: 'owner_change_note', prop: 'owner_change_note', label: '换绑情况', minWidth: 160, showOverflowTooltip: true, available: (auth) => auth.isHuguan },
]

export const FB_ADS_COLUMNS = [
  { key: 'name', prop: 'name', label: '账户名', minWidth: 120 },
  { key: 'account_id', prop: 'account_id', label: '账户ID', width: 160 },
  { key: 'bms', label: '所属BM', minWidth: 140 },
  { key: 'location', label: '位置', minWidth: 120 },
  { key: 'channel', label: '所属渠道', width: 110 },
  { key: 'asset_type', label: '资产类型', width: 110 },
  { key: 'status', label: '状态', width: 100 },
  { key: 'operator', prop: 'operator', label: '操作人', width: 100 },
  { key: 'timezone', prop: 'timezone', label: '时区', width: 100 },
  { key: 'acquired_date', prop: 'acquired_date', label: '到手时间', width: 110 },
]
```

- [ ] **Step 2: 改造 GG 面板的 `<el-table>` 区块**

在 `<script setup>` 加：

```js
import { PANEL_KEYS, GG_ADS_COLUMNS, indexByKey } from '@/constants/accountColumns'
import ColumnSettings from '@/components/ColumnSettings.vue'
import { useColumnPrefsStore } from '@/stores/columnPrefs'
```

以及：

```js
const columnPrefs = useColumnPrefsStore()
const COL_ATTRS = indexByKey(GG_ADS_COLUMNS)
const visibleOrder = computed(() => columnPrefs.visibleOrder(PANEL_KEYS.GG_ADS, GG_ADS_COLUMNS))
```

把 `<el-table> … </el-table>`（原 47-222 行）改成下面这个结构。**每个 `<el-table-column>` 的内部 markup 逐字不动**，只是被搬进 `v-if` 分支并增加 2 格缩进；`v-if="key === '...'"` 里的 key 与注册表一致。

```html
      <el-table v-if="columnPrefs.ready" :data="store.accounts" @selection-change="val => selected = val" :row-class-name="mccRowClass">
        <el-table-column type="selection" width="45" />
        <template v-for="key in visibleOrder" :key="key">
          <el-table-column v-if="key === 'name'" v-bind="COL_ATTRS.name">
            <template #default="{ row }">
              <!-- 原 50-60 行的 markup 逐字不动 -->
            </template>
          </el-table-column>
          <el-table-column v-else-if="key === 'sheet_write'" v-bind="COL_ATTRS.sheet_write">
            <template #default="{ row }">
              <SheetWriteCell :row="row" :failure="sheetWriteFailures[row.account_id]"
                @retry="retrySheetWrite(row)" />
            </template>
          </el-table-column>
          <el-table-column v-else-if="key === 'mcc'" v-bind="COL_ATTRS.mcc">
            <template #default="{ row }">
              <!-- 原 80-98 行的 markup 逐字不动 -->
            </template>
          </el-table-column>
          <el-table-column v-else-if="key === 'timezone'" v-bind="COL_ATTRS.timezone">
            <template #default="{ row }">
              <!-- 原 101-114 行的 markup 逐字不动 -->
            </template>
          </el-table-column>
          <el-table-column v-else-if="key === 'agent'" v-bind="COL_ATTRS.agent">
            <template #default="{ row }">
              <!-- 原 117-130 行的 markup 逐字不动 -->
            </template>
          </el-table-column>
          <el-table-column v-else-if="key === 'status'" v-bind="COL_ATTRS.status">
            <template #default="{ row }">
              <!-- 原 133-146 行的 markup 逐字不动 -->
            </template>
          </el-table-column>
          <el-table-column v-else-if="key === 'status_changed'" v-bind="COL_ATTRS.status_changed">
            <template #default="{ row }">
              <!-- 原 150-153 行的 markup 逐字不动 -->
            </template>
          </el-table-column>
          <el-table-column v-else-if="key === 'owner'" v-bind="COL_ATTRS.owner">
            <template #header>
              <!-- 原 157-162 行的 markup 逐字不动 -->
            </template>
            <template #default="{ row }">
              <OwnerCell :row="row" account-key="account_id"
                :loaded="ownerOptionsLoaded" :failed="ownerOptionsFailed"
                :options="ownerOptions" :option-map="ownerOptionMap"
                :pending="ownerPending"
                @change="(v) => changeOwner(row, v)" />
            </template>
          </el-table-column>
          <!-- 纯 prop 列兜底：account_id / acquired_date 走这里 -->
          <el-table-column v-else v-bind="COL_ATTRS[key]" />
        </template>
        <el-table-column label="操作" width="200">
          <!-- 原 215-220 行的 markup 逐字不动 -->
        </el-table-column>
      </el-table>
```

`v-if="columnPrefs.ready"` 是**必须的**：列序是按 DOM 顺序在 `onMounted` 时注册的，若表格先在默认顺序下挂载、配置随后才到，列序可能不会跟随更新（设计 §8.1）。

- [ ] **Step 3: 在筛选栏接入 `<ColumnSettings>`**

在 GG 面板筛选栏（`<OwnerFilterSelect ... />` 那一行之后，约 41 行）加：

```html
        <ColumnSettings :panel-key="PANEL_KEYS.GG_ADS" :registry="GG_ADS_COLUMNS" />
```

- [ ] **Step 4: 手动验收（GG 页）**

```bash
cd frontend && npm run dev
```

打开 `/accounts/ads`，逐项确认：
1. **零配置时列与顺序与改造前完全一致**（拿改造前的截图对照；这是回归的主判据）
2. 藏一列 → 刷新 → 仍是隐藏
3. 拖动调序 → 立即生效 → 刷新 → 顺序保持
4. 「恢复默认」把顺序与显隐都还原
5. 内联改名（✏️）／MCC 下拉／时区／代理／状态 四类内联编辑仍能正常打开与保存
6. 户归属下拉仍能改派（户管账号）
7. 写表列的 ⚠️ / ✅ 显示与点击重试正常
8. 批量勾选（selection）仍工作，批量按钮计数跟着变
9. 「操作」列四个按钮（✏️ 📋 💰 🗑）都能用
10. 用**普通用户**账号登录，确认候选列表里没有「户归属」

- [ ] **Step 5: 跑前端逻辑测试确认没碰到纯逻辑**

```bash
cd frontend && npm test
```

预期：全部 PASS

- [ ] **Step 6: 提交**

```bash
cd "D:/server/cc/GG-Server" && git add frontend/src/constants/accountColumns.js frontend/src/views/AdsAccountPanel.vue && git commit -m "feat(column-prefs): GG 账户表接入自定义列

列注册表集中到 constants/accountColumns.js（列清单唯一真相源），
表头宽度逐字沿用原模板值，零配置时视觉与改造前一致。

表格外包 <template v-for> + v-if 分派，单元格 markup 逐字不动，
只增加包裹与缩进。v-if=columnPrefs.ready 是必须的：列序按 DOM 顺序
在 onMounted 注册，先挂载后到配置可能不生效。"
```

---

## Task 8: TT 面板接入

**Files:**
- Modify: `frontend/src/views/tt/TtAccountPanel.vue:52-258`（`<el-table>` 区块）
- Modify: `frontend/src/views/tt/TtAccountPanel.vue` 筛选栏

**Interfaces:**
- Consumes: Task 7 的 `TT_ADS_COLUMNS` / `PANEL_KEYS` / `indexByKey`；Task 4 的 store；Task 5 的 `ColumnSettings`；Task 6 的两个单元格组件

- [ ] **Step 1: 加 import 与常量**

`<script setup>` 的 import 区追加：

```js
import { PANEL_KEYS, TT_ADS_COLUMNS, indexByKey } from '@/constants/accountColumns'
import ColumnSettings from '@/components/ColumnSettings.vue'
import { useColumnPrefsStore } from '@/stores/columnPrefs'
```

（`SheetWriteCell` / `OwnerCell` 在 Task 6 已加）

并加：

```js
const columnPrefs = useColumnPrefsStore()
const COL_ATTRS = indexByKey(TT_ADS_COLUMNS)
const visibleOrder = computed(() => columnPrefs.visibleOrder(PANEL_KEYS.TT_ADS, TT_ADS_COLUMNS))
```

- [ ] **Step 2: 改造 `<el-table>` 区块**

结构与 GG 完全同构。TT 的 13 个数据列 key 与默认顺序：

`advertiser_id` → `sheet_write` → `bc` → `timezone` → `agent` → `status` → `country` → `consumption` → `remark` → `acquired_date` → `status_changed` → `owner` → `owner_change_note`

```html
      <el-table v-if="columnPrefs.ready" ...>
        <el-table-column type="selection" width="45" />
        <template v-for="key in visibleOrder" :key="key">
          <el-table-column v-if="key === 'sheet_write'" v-bind="COL_ATTRS.sheet_write">
            <template #default="{ row }">
              <SheetWriteCell :row="row" :failure="sheetWriteFailures[row.advertiser_id]"
                @retry="retrySheetWrite(row)" />
            </template>
          </el-table-column>
          <el-table-column v-else-if="key === 'bc'" v-bind="COL_ATTRS.bc">
            <template #default="{ row }"><!-- 原 74-94 行 markup 逐字不动 --></template>
          </el-table-column>
          <el-table-column v-else-if="key === 'timezone'" v-bind="COL_ATTRS.timezone">
            <template #default="{ row }"><!-- 原 97-110 行 markup 逐字不动 --></template>
          </el-table-column>
          <el-table-column v-else-if="key === 'agent'" v-bind="COL_ATTRS.agent">
            <template #default="{ row }"><!-- 原 113-126 行 markup 逐字不动 --></template>
          </el-table-column>
          <el-table-column v-else-if="key === 'status'" v-bind="COL_ATTRS.status">
            <template #default="{ row }"><!-- 原 129-142 行 markup 逐字不动 --></template>
          </el-table-column>
          <el-table-column v-else-if="key === 'country'" v-bind="COL_ATTRS.country">
            <template #default="{ row }"><!-- 原 145-155 行 markup 逐字不动 --></template>
          </el-table-column>
          <el-table-column v-else-if="key === 'consumption'" v-bind="COL_ATTRS.consumption">
            <template #default="{ row }"><!-- 原 158-168 行 markup 逐字不动 --></template>
          </el-table-column>
          <el-table-column v-else-if="key === 'remark'" v-bind="COL_ATTRS.remark">
            <template #default="{ row }"><!-- 原 171-181 行 markup 逐字不动 --></template>
          </el-table-column>
          <el-table-column v-else-if="key === 'status_changed'" v-bind="COL_ATTRS.status_changed">
            <template #default="{ row }"><!-- 原 185-188 行 markup 逐字不动 --></template>
          </el-table-column>
          <el-table-column v-else-if="key === 'owner'" v-bind="COL_ATTRS.owner">
            <template #header><!-- 原 192-197 行 markup 逐字不动 --></template>
            <template #default="{ row }">
              <OwnerCell :row="row" account-key="advertiser_id"
                :loaded="ownerOptionsLoaded" :failed="ownerOptionsFailed"
                :options="ownerOptions" :option-map="ownerOptionMap"
                :pending="ownerPending"
                @change="(v) => changeOwner(row, v)" />
            </template>
          </el-table-column>
          <!-- 纯 prop 列兜底：advertiser_id / owner_change_note / acquired_date -->
          <el-table-column v-else v-bind="COL_ATTRS[key]" />
        </template>
        <el-table-column label="操作" width="200">
          <!-- 原 251-257 行 markup 逐字不动 -->
        </el-table-column>
      </el-table>
```

**注意**：「换绑情况」列原先带 `v-if="authStore.isHuguan"`（原 249 行），现在角色闸门已搬进注册表的 `available`，模板里**不再需要**那个 `v-if`，走兜底分支即可。

- [ ] **Step 3: 筛选栏接入**

```html
        <ColumnSettings :panel-key="PANEL_KEYS.TT_ADS" :registry="TT_ADS_COLUMNS" />
```

- [ ] **Step 4: 手动验收（TT 页）**

打开 `/tt/accounts`，重复 Task 7 Step 4 的 10 项。额外确认：
11. **用户管账号，「换绑情况」列在候选列表里且能显隐**（这列的角色闸门刚搬家，是最容易出问题的一处）
12. **用普通用户账号，「户归属」与「换绑情况」都不在候选列表里**

- [ ] **Step 5: 提交**

```bash
cd "D:/server/cc/GG-Server" && git add frontend/src/views/tt/TtAccountPanel.vue && git commit -m "feat(column-prefs): TT 账户表接入自定义列

13 个数据列接入；「户归属」「换绑情况」的角色闸门从模板 v-if 搬进
列注册表的 available，模板里不再重复判断。"
```

---

## Task 9: FB 面板接入

**Files:**
- Modify: `frontend/src/views/fb/FbAccountPanel.vue:51-83`（`<el-table>` 区块）
- Modify: `frontend/src/views/fb/FbAccountPanel.vue` 筛选栏

**Interfaces:**
- Consumes: Task 7 的 `FB_ADS_COLUMNS` / `PANEL_KEYS` / `indexByKey`；Task 4 的 store；Task 5 的 `ColumnSettings`

FB 没有共享单元格，10 个数据列里有 6 个是简单内联表达式，改造最轻。

- [ ] **Step 1: 加 import 与常量**

```js
import { PANEL_KEYS, FB_ADS_COLUMNS, indexByKey } from '@/constants/accountColumns'
import ColumnSettings from '@/components/ColumnSettings.vue'
import { useColumnPrefsStore } from '@/stores/columnPrefs'
```

```js
const columnPrefs = useColumnPrefsStore()
const COL_ATTRS = indexByKey(FB_ADS_COLUMNS)
const visibleOrder = computed(() => columnPrefs.visibleOrder(PANEL_KEYS.FB_ADS, FB_ADS_COLUMNS))
```

（若 `<script setup>` 里没 import `computed`，一并加上）

- [ ] **Step 2: 改造 `<el-table>` 区块**

```html
      <el-table v-if="columnPrefs.ready" :data="items" stripe border v-loading="loading" @selection-change="onSelect">
        <el-table-column type="selection" width="45" />
        <template v-for="key in visibleOrder" :key="key">
          <el-table-column v-if="key === 'bms'" v-bind="COL_ATTRS.bms">
            <template #default="{ row }">{{ row.bms?.map(b=>b.name).join(', ') }}</template>
          </el-table-column>
          <el-table-column v-else-if="key === 'location'" v-bind="COL_ATTRS.location">
            <template #default="{ row }">
              <span v-if="row.primary_bm_name">{{ row.primary_bm_name }}</span>
              <span v-else style="color:#c0c4cc;">—</span>
            </template>
          </el-table-column>
          <el-table-column v-else-if="key === 'channel'" v-bind="COL_ATTRS.channel">
            <template #default="{ row }">{{ optName(channelOptions, row.channel_id) }}</template>
          </el-table-column>
          <el-table-column v-else-if="key === 'asset_type'" v-bind="COL_ATTRS.asset_type">
            <template #default="{ row }">{{ optName(assetTypeOptions, row.asset_type_id) }}</template>
          </el-table-column>
          <el-table-column v-else-if="key === 'status'" v-bind="COL_ATTRS.status">
            <template #default="{ row }">{{ optName(statusOptions, row.status_id) }}</template>
          </el-table-column>
          <!-- 纯 prop 列兜底：name / account_id / operator / timezone / acquired_date -->
          <el-table-column v-else v-bind="COL_ATTRS[key]" />
        </template>
        <el-table-column label="操作" width="140" fixed="right">
          <template #default="{ row }">
            <el-button size="small" type="primary" link @click="openEdit(row)">编辑</el-button>
            <el-popconfirm title="确定删除？" @confirm="handleDelete(row.id)">
              <template #reference><el-button size="small" type="danger" link>删除</el-button></template>
            </el-popconfirm>
          </template>
        </el-table-column>
      </el-table>
```

- [ ] **Step 3: 筛选栏接入**

```html
        <ColumnSettings :panel-key="PANEL_KEYS.FB_ADS" :registry="FB_ADS_COLUMNS" />
```

- [ ] **Step 4: 手动验收（FB 页）**

打开 `/fb/accounts`，重复 Task 7 Step 4 的 1-4、8、9、10 项（FB 没有内联编辑与写表列，5-7 项不适用）。额外确认：**「操作」列的 `fixed="right"` 在列序变化后仍然贴右**。

- [ ] **Step 5: 提交**

```bash
cd "D:/server/cc/GG-Server" && git add frontend/src/views/fb/FbAccountPanel.vue && git commit -m "feat(column-prefs): FB 账户表接入自定义列

10 个数据列接入，无共享单元格。操作列保持 fixed=\"right\"。"
```

---

## Task 10: 端到端验收 + 代码审查

**Files:** 无新增；可能按审查意见回头修改

- [ ] **Step 1: 逐条跑设计文档 §7.2 的前端验收清单**

后端与前端都要在跑。**用一个全新的浏览器 profile**（确保没有历史 localStorage），逐条执行并**记录实际观察结果**：

| # | 操作 | 期望 |
|---|---|---|
| 1 | GG/TT/FB 各做一次「藏列 → 拖序 → 刷新」 | 配置回读正确 |
| 2 | **隐藏一列后刷新** | 该列仍是隐藏 |
| 3 | 换浏览器 profile 重登同一账号 | 配置跟着账号走 |
| 4 | 清空 localStorage 后刷新 | 配置仍在 |
| 5 | 普通用户登录 TT 页 | 候选列表里没有「户归属」「换绑情况」 |
| 6 | 藏到只剩一列可见数据列 | 再取消勾选被拦下并提示 |
| 7 | 取消勾选某列再勾回来 | 回到列表原位置，不是末尾 |
| 8 | 把后端杀掉，刷新页面 | 表格仍能显示（默认列），不白屏 |
| 9 | 把后端杀掉，改一次列配置 | 报错提示 + 界面回滚到保存前状态 |

**第 8、9 条是对 Task 4 里「拉取失败 ready 也要置 true」和「失败回滚」两处实现的实测**，不能用「代码看起来对」代替。

- [ ] **Step 2: 跨用户隔离实测**

用两个真实账号（A 与 B）在**同一浏览器**分别登录，确认 A 改的列不影响 B，且互相看不到对方配置。

- [ ] **Step 3: 跑全部自动化测试**

```bash
cd py && python -m pytest tests/ -q
cd ../frontend && npm test
```

预期：全绿。**若有失败，先修再往下走。**

- [ ] **Step 4: 调用 `/code-review`**

本次改动触及**鉴权**（JWT uid 边界、用户级数据隔离），按项目规范必须走 code-review：

```
/code-review
```

重点请审查者关注：
- `py/routes/column_prefs_routes.py` 的 uid 取值路径，有无任何从请求体读 uid 的旁路
- `py/column_prefs.py` 的读取路径是否真的做到「任何畸形值都不 500」
- `frontend/src/stores/columnPrefs.js` 的失败回滚是否会留下「界面已保存其实没存上」的窗口
- 三个面板改造里是否有**任何一个**原本的单元格逻辑被意外改变（逐块 diff）

- [ ] **Step 5: 修复审查发现的问题，重跑 Step 1-3**

修完必须**重跑实测**，不能只跑单测就宣布通过。

- [ ] **Step 6: 更新设计文档的状态**

把 `docs/superpowers/specs/2026-10-08-account-column-prefs-design.md` 开头的「状态：待实现」改为「状态：已实现（2026-XX-XX）」，并把 §8.1 拖拽列序风险的**实际结论**（是否需要 `:key` 兜底）补写进去——那份文档现在把这条列成未决风险，落地后应当有结论。

- [ ] **Step 7: 提交**

```bash
cd "D:/server/cc/GG-Server" && git add docs/superpowers/specs/2026-10-08-account-column-prefs-design.md && git commit -m "docs(column-prefs): 补实现结论，关闭拖拽列序未决风险"
```

**不要推送到 origin** —— 汇报完成，等用户决定推送时机。

---

## 附：验收判据汇总（给实施者自查）

交付前逐条打勾，任何一条没实测过就不算完成：

- [ ] `py/tests/test_column_prefs.py` 全绿，且**实际执行过**
- [ ] `cd frontend && npm test` 全绿，且**实际执行过**
- [ ] 三张表零配置时列与顺序与改造前一致（有对照截图或逐列核对记录）
- [ ] 「隐藏列刷新后仍隐藏」实测通过（这是设计自审抓出的缺陷的回归判据）
- [ ] 「拖拽调序立即生效」实测通过（设计 §8.1 的风险点，必须给出结论）
- [ ] 跨用户隔离实测通过（两个真实账号）
- [ ] 后端不可用时表格不白屏、保存失败有提示且回滚
- [ ] `/code-review` 已执行，发现的问题已修复并重跑实测
