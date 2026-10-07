# 上万户规模治理 · 第 ③ 部分：分页与列表 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让所有列表端点在数据量到上万级时既不卡浏览器也不被绕过分页 —— 修掉两个无分页的「已删除账户」端点，给全部 15 处 `size` 参数加服务端上限，并消除 FB 列表的 N+1 查询。

**Architecture:** 全部是**服务端闸门 + 既有形状对齐**，不引入新表、新线程或新状态。分页尺寸闸门收敛到既有的 `routes/helpers.parse_pagination`（现状是零调用点的死代码），把它的上限从 100 提到 500 并加安全整数解析；`IN (...)` 分块收敛到新的 `utils.chunk`。两个无分页端点照抄 FB 已有的 `{items, total, page, size}` 响应形状，前端改分页渲染 + 搜索走后端。

**Tech Stack:** Python 3.11 / Flask / SQLite 3.45.1 / pytest / Vue 3 + Element Plus + Pinia

**上位规格:** `docs/superpowers/specs/2026-10-07-sheet-sync-scale-design.md`（§6 分页与列表、§2.2 配额）

---

## Global Constraints

以下为**项目级硬性要求**，每个任务都隐含包含：

- **纯增量原则**：只做增量，不修改原有功能的代码逻辑。禁止因本计划导致已有功能逻辑出错或失效。
  - 具体到本计划：所有分页改动**只加字段不加参数**——`/accounts/deleted` 与 `/tt/accounts/deleted` 的响应在原有 `accounts` / `items` 字段之外**追加** `total` / `page` / `size`，前端旧的读取路径 `res.accounts` / `res.items` 必须继续可用。
- **`size` 上限 = `500`**（前端最大页尺寸是 200，留 2.5 倍余量）。**越界钳制，不报错**。
- **`chunk` 分块大小 = `900`**（SQLite 3.45.1 的 `SQLITE_LIMIT_VARIABLE_NUMBER` 是 32766，900 留足余量）。
- **禁止 `git add -A`**：本仓库有并行会话共用工作区，只 `git add` 本计划涉及的具体文件。
- **提交信息用中文**，格式 `type(scope): 描述`，与仓库既有提交一致。
- **测试命令**：`cd py && python -m pytest tests/ -q`；前端 `cd frontend && npm run build`。
- **不要动**：`py/main.py` 的 `/api/accounts/list`（4074 那处是列表主端点，只加闸门不改行为）、`fb_routes.py` 的已删除列表（它已经有分页，只加闸门）。

---

## 文件结构

| 文件 | 动作 | 职责 |
|---|---|---|
| `py/utils.py` | 修改 | 新增 `chunk`（无依赖模块，`main.py:29` 已在用） |
| `py/routes/helpers.py` | 修改 | `parse_pagination` 加上限与安全整数解析（现状零调用点） |
| `py/tests/test_utils.py` | **新建** | `chunk` 的纯函数测试 |
| `py/tests/test_helpers.py` | 修改 | 追加 `parse_pagination` 测试 |
| `py/main.py` | 修改 | `/api/accounts/deleted` 分页；6 处 `size` 加闸门；5 处 `IN` 接入 `chunk` |
| `py/routes/tt_accounts_routes.py` | 修改 | `/api/tt/accounts/deleted` 分页；1 处 `size` 加闸门；2 处 `IN` 接入 `chunk` |
| `py/routes/fb_routes.py` | 修改 | 8 处 `size` 加闸门；2 处列表 N+1 改批查 |
| `frontend/src/api/accounts.js` | 修改 | `listDeleted` 接收分页/搜索参数 |
| `frontend/src/api/tt.js` | 修改 | `listDeleted` 接收分页/搜索参数 |
| `frontend/src/stores/accounts.js` | 修改 | `loadDeletedAccounts` 透传参数 |
| `frontend/src/components/AccountDeletedModal.vue` | 修改 | 分页渲染 + 搜索走后端 |
| `frontend/src/components/tt/TtAccountDeletedModal.vue` | 修改 | 同上 |

---

## Task 1: `utils.chunk` + `helpers.parse_pagination` 闸门

**Files:**
- Modify: `py/utils.py`（在文件末尾追加）
- Modify: `py/routes/helpers.py:74-78`（替换 `parse_pagination`）
- Create: `py/tests/test_utils.py`
- Modify: `py/tests/test_helpers.py`（文件末尾追加）

**Interfaces:**
- Consumes: 无
- Produces:
  - `utils.chunk(seq, size=None) -> list[list]` — 把序列切成多段。`size=None` 时用模块常量 `utils.CHUNK_SIZE`（值 `900`）
  - `routes.helpers.parse_pagination(default: int = 20, maximum: int = 500, name: str = "size") -> tuple[int, int]` — 返回 `(page, size)`，`page >= 1`，`1 <= size <= maximum`
  - `routes.helpers._safe_int(raw, default) -> int`

- [ ] **Step 1: 写失败的测试**

新建 `py/tests/test_utils.py`：

```python
"""测试 utils.py 公共函数 — chunk 分块。"""
import os
import sys

_py_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _py_dir not in sys.path:
    sys.path.insert(0, _py_dir)

from utils import chunk, CHUNK_SIZE  # noqa: E402


class TestChunk:
    def test_empty_returns_empty_list(self):
        assert chunk([]) == []

    def test_single_small_sequence_is_one_part(self):
        assert chunk([1, 2, 3]) == [[1, 2, 3]]

    def test_exact_multiple_has_no_trailing_empty_part(self):
        """900 个元素应恰好切成 1 段，不能多出空段。"""
        assert chunk(list(range(900)), size=900) == [list(range(900))]

    def test_boundary_901_splits_into_two(self):
        parts = chunk(list(range(901)), size=900)
        assert [len(p) for p in parts] == [900, 1]

    def test_multiple_parts_preserve_order(self):
        parts = chunk(list(range(1800)), size=900)
        assert [len(p) for p in parts] == [900, 900]
        assert parts[0][0] == 0
        assert parts[1][0] == 900

    def test_default_size_uses_module_constant(self):
        assert CHUNK_SIZE == 900
        assert chunk(list(range(901)))[0] == list(range(900))

    def test_accepts_tuple_and_generator(self):
        assert chunk((1, 2, 3)) == [[1, 2, 3]]
        assert chunk(x for x in range(3)) == [[0, 1, 2]]

    def test_monkeypatchable_size_for_guard_tests(self, monkeypatch):
        """其它任务的守卫测试靠改 CHUNK_SIZE 来证明调用点真的走了 chunk。"""
        import utils
        monkeypatch.setattr(utils, "CHUNK_SIZE", 3)
        assert utils.chunk(list(range(7))) == [[0, 1, 2], [3, 4, 5], [6]]
```

在 `py/tests/test_helpers.py` 末尾追加：

```python
class TestParsePagination:
    """parse_pagination(default, maximum, name) 函数。

    需要 Flask 请求上下文（读 request.args），故用 app 夹具的 test_request_context。
    """

    def _call(self, app, query, **kwargs):
        from routes.helpers import parse_pagination
        with app.test_request_context("/?" + query):
            return parse_pagination(**kwargs)

    def test_defaults_when_no_params(self, app):
        assert self._call(app, "") == (1, 20)

    def test_explicit_values(self, app):
        assert self._call(app, "page=3&size=50") == (3, 50)

    def test_size_above_maximum_is_clamped_not_rejected(self, app):
        """上万级数据下这是「冲烂浏览器」的总闸门，必须钳制。"""
        assert self._call(app, "size=999999") == (1, 500)

    def test_size_exactly_maximum_passes(self, app):
        assert self._call(app, "size=500") == (1, 500)

    def test_size_just_above_maximum_clamps(self, app):
        assert self._call(app, "size=501") == (1, 500)

    def test_non_numeric_size_falls_back_to_default(self, app):
        """现状的裸 int() 会 ValueError ⇒ 500；本函数必须回落而不是抛。"""
        assert self._call(app, "size=abc") == (1, 20)

    def test_zero_and_negative_size_fall_back_to_one(self, app):
        assert self._call(app, "size=0") == (1, 1)
        assert self._call(app, "size=-5") == (1, 1)

    def test_negative_page_falls_back_to_one(self, app):
        """负数页在现状里会变成 OFFSET -N（SQLite 等价 0），是静默错值。"""
        assert self._call(app, "page=-3") == (1, 20)

    def test_non_numeric_page_falls_back_to_one(self, app):
        assert self._call(app, "page=abc") == (1, 20)

    def test_custom_default_preserves_caller_behavior(self, app):
        """TT/FB 的默认页尺寸是 50，迁移时不得把它变成 20。"""
        assert self._call(app, "", default=50) == (1, 50)

    def test_custom_maximum(self, app):
        assert self._call(app, "size=999", maximum=100) == (1, 100)

    def test_custom_param_name(self, app):
        """main.py:8423 用的是 page_size，不是 size。"""
        assert self._call(app, "page_size=30", name="page_size") == (1, 30)
```

- [ ] **Step 2: 运行测试确认失败**

```bash
cd py && python -m pytest tests/test_utils.py tests/test_helpers.py -q
```

Expected: FAIL —— `ImportError: cannot import name 'chunk' from 'utils'`（`test_utils.py` 整体收集失败），`test_helpers.py` 的 `TestParsePagination` 因 `parse_pagination() got an unexpected keyword argument 'maximum'` 失败。

- [ ] **Step 3: 实现 `chunk`**

在 `py/utils.py` **末尾追加**（不要动文件里已有的三个函数）：

```python
# `IN (?,?,…)` 的单次绑定数量上限。SQLite 3.45.1 实测
# `SQLITE_LIMIT_VARIABLE_NUMBER` = 32766；取 900 是为了留足余量，
# 同时让每段拼接出的 SQL 文本不至于过长。
CHUNK_SIZE = 900


def chunk(seq, size=None):
    """把序列切成多段，供 `IN (?,?,…)` 分批绑定。

    账户数上万后，一次 `IN` 会绑定上万个变量：1 万户尚能跑，
    **超过 32766 户必然抛 `too many SQL variables`**。调用方一律写成
    `for part in chunk(ids): ... IN ({",".join("?" * len(part))}) ...`。

    Args:
        seq: 任意可迭代对象（list / tuple / generator 均可）
        size: 每段长度；None 时取模块常量 CHUNK_SIZE（**在调用时读取**，
              这样守卫测试可以 monkeypatch 它来证明调用点确实走了分块）

    Returns:
        list[list]。空输入返回 `[]`（**不是** `[[]]` —— 后者会让调用方
        拼出一个 `IN ()` 的非法 SQL）。
    """
    step = CHUNK_SIZE if size is None else size
    items = list(seq)
    return [items[i:i + step] for i in range(0, len(items), step)]
```

- [ ] **Step 4: 实现 `parse_pagination`**

把 `py/routes/helpers.py:74-78` 的整个函数替换为：

```python
def _safe_int(raw, default: int) -> int:
    """安全整数解析：非数字一律回落默认值，不抛异常。

    现状的裸 `int(request.args.get("size", 20) or 20)` 遇到 `size=abc`
    会 ValueError ⇒ 500。分页参数是用户可以随便拼的，不该把接口打成 500。
    """
    try:
        return int(raw)
    except (TypeError, ValueError):
        return default


def parse_pagination(default: int = 20, maximum: int = 500,
                     name: str = "size") -> tuple[int, int]:
    """解析分页参数，返回 (page, size)。**越界一律钳制，不报错**。

    这是「不要全量返回、冲烂浏览器」的服务端总闸门：调用方前端的默认页尺寸
    都很小，但服务端此前没有任何上限，任何客户端传 `size=999999` 就能把整张
    表拉回去。

    Args:
        default: 缺省页尺寸。**各调用点保持自己的原值**（GG 是 20，TT/FB 是 50），
                 迁移时不得统一成 20 —— 那会改变既有端点的行为。
        maximum: 页尺寸上限，默认 500（前端最大页尺寸是 200，留 2.5 倍余量）。
        name: 页尺寸的查询参数名，默认 "size"。`main.py:8423` 用的是 `page_size`。

    Returns:
        (page, size)，满足 `page >= 1` 且 `1 <= size <= maximum`。
    """
    page = max(1, _safe_int(request.args.get("page"), 1))
    size = max(1, min(maximum, _safe_int(request.args.get(name), default)))
    return page, size
```

- [ ] **Step 5: 运行测试确认通过**

```bash
cd py && python -m pytest tests/test_utils.py tests/test_helpers.py -q
```

Expected: PASS（`test_utils.py` 8 passed，`test_helpers.py` 13 + 12 = 25 passed）

- [ ] **Step 6: 确认没有打破既有测试**

```bash
cd py && python -m pytest tests/ -q
```

Expected: 与执行本任务前的基线**逐条一致**（本任务只新增函数、只改了一个零调用点的死函数，不应影响任何既有测试）。

- [ ] **Step 7: 提交**

```bash
git add py/utils.py py/routes/helpers.py py/tests/test_utils.py py/tests/test_helpers.py
git commit -m "feat(helpers): chunk 分块 + parse_pagination 服务端尺寸闸门"
```

---

## Task 2: 15 处 `size` 调用点迁移到 `parse_pagination`

**Files:**
- Modify: `py/main.py:2775`、`py/main.py:3513`、`py/main.py:4074`、`py/main.py:6005`、`py/main.py:8423`、`py/main.py:9987`
- Modify: `py/routes/tt_accounts_routes.py:211`
- Modify: `py/routes/fb_routes.py:21`、`63`、`270`、`464`、`638`、`921`、`1146`、`1653`
- Modify: `py/main.py:46`（导入行）
- Modify: `py/routes/tt_accounts_routes.py:13`（导入行）
- Test: `py/tests/test_pagination_guard.py`（**新建**）

**Interfaces:**
- Consumes: Task 1 的 `routes.helpers.parse_pagination(default, maximum, name)`
- Produces: 无新接口；所有列表端点获得服务端尺寸上限

**⚠️ 每处都必须保留它原本的默认值**，否则违反纯增量原则：

| 位置 | 原写法 | 原默认 | 改成 |
|---|---|---|---|
| `main.py:2775` | `int(request.args.get("size", 20) or 20)` | 20 | `parse_pagination()` |
| `main.py:3513` | `request.args.get("size", 20, type=int)` | 20 | `parse_pagination()` |
| `main.py:4074` | `int(request.args.get("size", 20) or 20)` | 20 | `parse_pagination()` |
| `main.py:6005` | `int(request.args.get("size", 20) or 20)` | 20 | `parse_pagination()` |
| `main.py:8423` | `int(request.args.get("page_size", 20))` | 20 | `parse_pagination(name="page_size")` |
| `main.py:9987` | `int(request.args.get("size", 50))` | **50** | `parse_pagination(default=50)` |
| `tt_accounts_routes.py:211` | `request.args.get('size', 50, type=int)` | **50** | `parse_pagination(default=50)` |
| `fb_routes.py:21/63/270/464/638/921/1146/1653` | `request.args.get('size', 50, type=int)` | **50** | `parse_pagination(default=50)` |

**注意**：每处的 `page` 解析也一并交给 `parse_pagination`（它同时返回 page）。若原处写的是
`page = int(request.args.get("page", 1) or 1)`，把那一行和 `size` 那一行**一起**替换成
`page, size = parse_pagination(...)`。

- [ ] **Step 1: 写失败的测试**

新建 `py/tests/test_pagination_guard.py`：

```python
"""分页尺寸闸门守卫 —— 覆盖所有暴露 size 的列表端点。

判据不是「端点能返回 200」，而是「**传超大 size 时返回条数被压到上限**」。
只断言 200 的测试对闸门失效完全失明：没有闸门时端点照样返回 200，
只是把上万行一次性吐出来。
"""
import os
import sys

_py_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _py_dir not in sys.path:
    sys.path.insert(0, _py_dir)

MAX_PAGE_SIZE = 500


def _insert_accounts(db, owner_id, n):
    """插入 n 个 GG 账户。"""
    for i in range(n):
        db.execute(
            "INSERT INTO accounts(name, account_id, owner_id) VALUES(?,?,?)",
            (f"acc{i}", f"gg{i:06d}", owner_id),
        )
    db.commit()


def test_gg_accounts_list_clamps_oversized_size(app, client, auth_headers):
    """/api/accounts/list —— 传 size=999999 必须被压到 500 以内。"""
    import database
    db = database.get_db()
    uid = db.execute("SELECT id FROM users WHERE username='testuser'").fetchone()["id"]
    _insert_accounts(db, uid, 600)
    db.close()

    resp = client.get("/api/accounts/list?size=999999", headers=auth_headers)
    assert resp.status_code == 200
    assert len(resp.get_json()["accounts"]) <= MAX_PAGE_SIZE


def test_gg_accounts_list_non_numeric_size_does_not_500(app, client, auth_headers):
    """现状的裸 int() 会 ValueError ⇒ 500。闸门必须回落默认值。"""
    resp = client.get("/api/accounts/list?size=abc", headers=auth_headers)
    assert resp.status_code == 200


def test_gg_deleted_list_clamps_oversized_size(app, client, auth_headers):
    import database
    db = database.get_db()
    uid = db.execute("SELECT id FROM users WHERE username='testuser'").fetchone()["id"]
    for i in range(600):
        db.execute(
            "INSERT INTO accounts(name, account_id, owner_id, deleted_at) "
            "VALUES(?,?,?,datetime('now','localtime'))",
            (f"del{i}", f"gdel{i:06d}", uid),
        )
    db.commit()
    db.close()

    resp = client.get("/api/accounts/deleted?size=999999", headers=auth_headers)
    assert resp.status_code == 200
    assert len(resp.get_json()["accounts"]) <= MAX_PAGE_SIZE


def test_mcc_list_clamps_oversized_size(app, client, auth_headers):
    resp = client.get("/api/mcc/list?size=999999", headers=auth_headers)
    assert resp.status_code == 200


def test_tt_accounts_list_clamps_oversized_size(app, client, tt_headers):
    resp = client.get("/api/tt/accounts/list?size=999999", headers=tt_headers)
    assert resp.status_code == 200
    assert len(resp.get_json()["items"]) <= MAX_PAGE_SIZE


def test_tt_deleted_list_clamps_oversized_size(app, client, tt_headers):
    resp = client.get("/api/tt/accounts/deleted?size=999999", headers=tt_headers)
    assert resp.status_code == 200
    assert len(resp.get_json()["items"]) <= MAX_PAGE_SIZE


def test_fb_accounts_list_clamps_oversized_size(app, client, admin_fb_headers):
    resp = client.get("/api/fb/accounts/list?size=999999", headers=admin_fb_headers)
    assert resp.status_code == 200
    assert len(resp.get_json()["items"]) <= MAX_PAGE_SIZE
```

- [ ] **Step 2: 运行测试确认失败**

```bash
cd py && python -m pytest tests/test_pagination_guard.py -q
```

Expected: `test_gg_accounts_list_clamps_oversized_size` FAIL（`assert 600 <= 500`），`test_gg_accounts_list_non_numeric_size_does_not_500` FAIL（`assert 500 == 200`）。其余可能已经通过（这些端点本来没有数据返回）。

- [ ] **Step 3: 加导入**

`py/main.py:46` 那一行改为：

```python
from routes.helpers import PLATFORM_SWITCH_ROLES, CROSS_USER_ROLES, GLOBAL_OPTION_ROLES, parse_pagination
```

`py/routes/tt_accounts_routes.py:13` 那一行改为：

```python
from .helpers import ok, err, get_uid, get_db, parse_body, CROSS_USER_ROLES, parse_pagination
```

`py/routes/fb_routes.py` 的导入处（`from .helpers import ...`）追加 `parse_pagination`。

- [ ] **Step 4: 逐个替换 15 处**

对表中每一处，把 `page` 与 `size` 两行合并成一行。示例（`main.py:6004-6005`）：

替换前：
```python
    page = int(request.args.get("page", 1) or 1)
    size = int(request.args.get("size", 20) or 20)
```

替换后：
```python
    page, size = parse_pagination()
```

`main.py:8423`：
```python
    page, page_size = parse_pagination(name="page_size")
```
（若该处的变量名是 `page_size`，**保持变量名不变**，只换解析方式；如后续代码用 `page_size` 拼 SQL，不要改名。）

`main.py:9987`、`tt_accounts_routes.py:211`、`fb_routes.py` 八处：
```python
    page, size = parse_pagination(default=50)
```

- [ ] **Step 5: 运行测试确认通过**

```bash
cd py && python -m pytest tests/test_pagination_guard.py -q
```

Expected: PASS（7 passed）

- [ ] **Step 6: 全量回归**

```bash
cd py && python -m pytest tests/ -q
```

Expected: 与基线一致。**逐条核对**既有列表测试（`test_tt_accounts.py`、`test_fb_platform.py`、
`test_huguan_dashboard.py`），确认默认页尺寸没被改坏 —— 这是本任务最大的回归风险。

- [ ] **Step 7: 提交**

```bash
git add py/main.py py/routes/tt_accounts_routes.py py/routes/fb_routes.py py/tests/test_pagination_guard.py
git commit -m "fix(pagination): 15 处 size 参数加服务端上限，超限钳制不报错"
```

---

## Task 3: GG `/api/accounts/deleted` 补分页 + 服务端搜索

**Files:**
- Modify: `py/main.py:5020-5045`（`accounts_deleted_list`）
- Test: `py/tests/test_deleted_pagination.py`（**新建**）

**Interfaces:**
- Consumes: Task 1 的 `parse_pagination`、Task 2 已加好的导入
- Produces: `GET /api/accounts/deleted` 响应追加 `total` / `page` / `size` 三个字段；
  新增可选查询参数 `search`（匹配 `account_id` / `name` / 代理名）。
  **原有的 `accounts` 字段与形状不变。**

- [ ] **Step 1: 写失败的测试**

新建 `py/tests/test_deleted_pagination.py`：

```python
"""已删除账户列表分页 —— GG 与 TT 两个端点。

这两个端点在 1912 户规模下会一次性把全部已删账户吐给浏览器，
前端再全量渲染成 DOM，上万行直接卡死。
"""
import os
import sys

_py_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _py_dir not in sys.path:
    sys.path.insert(0, _py_dir)


def _seed_deleted_gg(db, owner_id, n):
    for i in range(n):
        db.execute(
            "INSERT INTO accounts(name, account_id, owner_id, deleted_at) "
            "VALUES(?,?,?,datetime('now','localtime'))",
            (f"已删{i}", f"ggdel{i:06d}", owner_id),
        )
    db.commit()


def _gg_uid(db):
    return db.execute("SELECT id FROM users WHERE username='testuser'").fetchone()["id"]


def test_gg_deleted_returns_total_and_page_meta(app, client, auth_headers):
    import database
    db = database.get_db()
    _seed_deleted_gg(db, _gg_uid(db), 120)
    db.close()

    body = client.get("/api/accounts/deleted", headers=auth_headers).get_json()
    assert body["success"] is True
    assert body["total"] == 120
    assert body["page"] == 1
    assert body["size"] == 20
    assert len(body["accounts"]) == 20


def test_gg_deleted_second_page_is_disjoint(app, client, auth_headers):
    """翻页必须真的换了一批数据 —— 只断言 total 的测试测不出 OFFSET 写错。"""
    import database
    db = database.get_db()
    _seed_deleted_gg(db, _gg_uid(db), 120)
    db.close()

    p1 = client.get("/api/accounts/deleted?page=1&size=50", headers=auth_headers).get_json()
    p2 = client.get("/api/accounts/deleted?page=2&size=50", headers=auth_headers).get_json()
    ids1 = {a["account_id"] for a in p1["accounts"]}
    ids2 = {a["account_id"] for a in p2["accounts"]}
    assert len(ids1) == 50 and len(ids2) == 50
    assert not (ids1 & ids2)


def test_gg_deleted_search_filters_server_side(app, client, auth_headers):
    """分页后搜索必须走后端 —— 前端只能看到当前页，过滤会漏结果。"""
    import database
    db = database.get_db()
    _seed_deleted_gg(db, _gg_uid(db), 120)
    db.execute(
        "INSERT INTO accounts(name, account_id, owner_id, deleted_at) "
        "VALUES('独一无二', 'FINDME', ?, datetime('now','localtime'))",
        (_gg_uid(db),),
    )
    db.commit()
    db.close()

    body = client.get("/api/accounts/deleted?search=FINDME", headers=auth_headers).get_json()
    assert body["total"] == 1
    assert body["accounts"][0]["account_id"] == "FINDME"


def test_gg_deleted_excludes_live_accounts(app, client, auth_headers):
    """回归守卫：未删除的账户不得出现在已删除列表里。"""
    import database
    db = database.get_db()
    uid = _gg_uid(db)
    _seed_deleted_gg(db, uid, 3)
    db.execute("INSERT INTO accounts(name, account_id, owner_id) VALUES('活的','LIVE001',?)", (uid,))
    db.commit()
    db.close()

    body = client.get("/api/accounts/deleted", headers=auth_headers).get_json()
    assert body["total"] == 3
    assert all(a["account_id"] != "LIVE001" for a in body["accounts"])


def test_gg_deleted_only_returns_own_accounts(app, client, auth_headers):
    """数据归属隔离守卫：别人的已删账户不得出现。"""
    import database
    db = database.get_db()
    db.execute("INSERT OR IGNORE INTO users(id, username, password, role) VALUES(999,'other','x','user')")
    _seed_deleted_gg(db, 999, 5)
    _seed_deleted_gg(db, _gg_uid(db), 2)
    db.commit()
    db.close()

    body = client.get("/api/accounts/deleted?size=500", headers=auth_headers).get_json()
    assert body["total"] == 2
```

- [ ] **Step 2: 运行测试确认失败**

```bash
cd py && python -m pytest tests/test_deleted_pagination.py -q
```

Expected: FAIL —— `KeyError: 'total'`（现状只返回 `accounts`），`len(body["accounts"]) == 20` 断言失败（现状返回全部 120 条）。

- [ ] **Step 3: 改写端点**

把 `py/main.py:5020-5045` 的 `accounts_deleted_list` 整个函数替换为：

```python
@app.route("/api/accounts/deleted", methods=["GET"])
@jwt_required()
def accounts_deleted_list():
    """返回当前用户已删除的账户列表（**分页** + 服务端搜索）。

    分页是必须的：上万户规模下全量返回会让前端一次性渲染上万行 DOM 而卡死
    （2026-10-07 用户原话「不要全量返回 冲烂浏览器」）。

    响应在原有的 `accounts` 之外**追加** `total` / `page` / `size` —— 纯增量，
    前端旧读取路径 `res.accounts` 不受影响。

    搜索必须走服务端：分页之后前端手里只有当前页，「当前页内过滤」会漏掉
    其余页的匹配结果，表现为「搜得到但显示不全」。
    """
    user_id = int(get_jwt_identity())
    page, size = parse_pagination()
    search = request.args.get("search", "").strip()

    where = ["a.owner_id=?", "a.deleted_at IS NOT NULL"]
    params = [user_id]
    if search:
        # 与前端原来的客户端过滤口径对齐：账户ID / 名称 / 代理名三个字段。
        where.append("(a.account_id LIKE ? OR a.name LIKE ? OR ag.name LIKE ?)")
        like = f"%{search}%"
        params += [like, like, like]
    where_sql = " AND ".join(where)

    db = _yt_db()
    try:
        # total 与列表用**同一套** where/params：分两套条件会让总数与实际
        # 可翻页数不一致，前端算出空页。
        total = db.execute(
            f"SELECT COUNT(*) FROM accounts a LEFT JOIN agents ag ON a.agent_id = ag.id "
            f"WHERE {where_sql}",
            params
        ).fetchone()[0]
        rows = db.execute(
            f"""SELECT a.id, a.name, a.account_id, a.timezone, a.deleted_at,
                       ag.name AS agent_name, st.name AS status_name
                FROM accounts a
                LEFT JOIN agents ag ON a.agent_id = ag.id
                LEFT JOIN account_statuses st ON a.status_id = st.id
                WHERE {where_sql}
                ORDER BY a.deleted_at DESC LIMIT ? OFFSET ?""",
            params + [size, (page - 1) * size]
        ).fetchall()
    finally:
        db.close()

    accounts = []
    for r in rows:
        d = dict(r)
        if d.get("agent_name"):
            d["agent"] = d["agent_name"]
        if d.get("status_name"):
            d["status"] = d["status_name"]
        accounts.append(d)
    return jsonify({"success": True, "accounts": accounts,
                    "total": total, "page": page, "size": size})
```

- [ ] **Step 4: 运行测试确认通过**

```bash
cd py && python -m pytest tests/test_deleted_pagination.py -q
```

Expected: PASS（5 passed）

- [ ] **Step 5: 全量回归**

```bash
cd py && python -m pytest tests/ -q
```

Expected: 与基线一致。

- [ ] **Step 6: 提交**

```bash
git add py/main.py py/tests/test_deleted_pagination.py
git commit -m "feat(accounts): /accounts/deleted 补分页与服务端搜索"
```

---

## Task 4: TT `/api/tt/accounts/deleted` 补分页 + 服务端搜索

**Files:**
- Modify: `py/routes/tt_accounts_routes.py:700-727`（`deleted_accounts_list`）
- Test: `py/tests/test_deleted_pagination.py`（追加）

**Interfaces:**
- Consumes: Task 1 的 `parse_pagination`、Task 2 已加好的导入
- Produces: `GET /api/tt/accounts/deleted` 响应追加 `total` / `page` / `size`；
  新增可选查询参数 `search`。**原有的 `items` 字段与形状不变。**

- [ ] **Step 1: 写失败的测试**

在 `py/tests/test_deleted_pagination.py` **末尾追加**：

```python
def _seed_deleted_tt(db, owner_id, n):
    for i in range(n):
        db.execute(
            "INSERT INTO tt_accounts(advertiser_id, owner_id, deleted_at) "
            "VALUES(?,?,datetime('now','localtime'))",
            (f"ttdel{i:06d}", owner_id),
        )
    db.commit()


def _tt_uid(db):
    return db.execute("SELECT id FROM users WHERE username='ttuser'").fetchone()["id"]


def test_tt_deleted_returns_total_and_page_meta(app, client, tt_headers):
    import database
    db = database.get_db()
    _seed_deleted_tt(db, _tt_uid(db), 120)
    db.close()

    body = client.get("/api/tt/accounts/deleted", headers=tt_headers).get_json()
    assert body["success"] is True
    assert body["total"] == 120
    assert body["page"] == 1
    assert body["size"] == 50
    assert len(body["items"]) == 50


def test_tt_deleted_second_page_is_disjoint(app, client, tt_headers):
    import database
    db = database.get_db()
    _seed_deleted_tt(db, _tt_uid(db), 120)
    db.close()

    p1 = client.get("/api/tt/accounts/deleted?page=1&size=50", headers=tt_headers).get_json()
    p2 = client.get("/api/tt/accounts/deleted?page=2&size=50", headers=tt_headers).get_json()
    ids1 = {a["advertiser_id"] for a in p1["items"]}
    ids2 = {a["advertiser_id"] for a in p2["items"]}
    assert len(ids1) == 50 and len(ids2) == 50
    assert not (ids1 & ids2)


def test_tt_deleted_search_by_advertiser_id(app, client, tt_headers):
    import database
    db = database.get_db()
    uid = _tt_uid(db)
    _seed_deleted_tt(db, uid, 120)
    db.execute(
        "INSERT INTO tt_accounts(advertiser_id, owner_id, deleted_at) "
        "VALUES('FINDME_TT', ?, datetime('now','localtime'))", (uid,)
    )
    db.commit()
    db.close()

    body = client.get("/api/tt/accounts/deleted?search=FINDME_TT", headers=tt_headers).get_json()
    assert body["total"] == 1
    assert body["items"][0]["advertiser_id"] == "FINDME_TT"


def test_tt_deleted_search_by_name(app, client, tt_headers):
    import database
    db = database.get_db()
    uid = _tt_uid(db)
    db.execute(
        "INSERT INTO tt_accounts(advertiser_id, name, owner_id, deleted_at) "
        "VALUES('ttname001', '独特名称', ?, datetime('now','localtime'))", (uid,)
    )
    db.commit()
    db.close()

    body = client.get("/api/tt/accounts/deleted?search=独特名称", headers=tt_headers).get_json()
    assert body["total"] == 1


def test_tt_deleted_excludes_live_accounts(app, client, tt_headers):
    import database
    db = database.get_db()
    uid = _tt_uid(db)
    _seed_deleted_tt(db, uid, 3)
    db.execute("INSERT INTO tt_accounts(advertiser_id, owner_id) VALUES('TTLIVE001',?)", (uid,))
    db.commit()
    db.close()

    body = client.get("/api/tt/accounts/deleted", headers=tt_headers).get_json()
    assert body["total"] == 3
    assert all(a["advertiser_id"] != "TTLIVE001" for a in body["items"])


def test_tt_deleted_only_returns_own_accounts(app, client, tt_headers):
    import database
    db = database.get_db()
    db.execute("INSERT OR IGNORE INTO users(id, username, password, role) VALUES(998,'ttother','x','user')")
    _seed_deleted_tt(db, 998, 5)
    _seed_deleted_tt(db, _tt_uid(db), 2)
    db.commit()
    db.close()

    body = client.get("/api/tt/accounts/deleted?size=500", headers=tt_headers).get_json()
    assert body["total"] == 2


def test_tt_deleted_cross_user_role_sees_all(app, client, admin_tt_headers):
    """跨用户角色（admin/huguan/developer）仍应看到全部 —— 回归守卫。"""
    import database
    db = database.get_db()
    db.execute("INSERT OR IGNORE INTO users(id, username, password, role) VALUES(997,'ttu2','x','user')")
    _seed_deleted_tt(db, 997, 4)
    db.commit()
    db.close()

    body = client.get("/api/tt/accounts/deleted?size=500", headers=admin_tt_headers).get_json()
    assert body["total"] >= 4
```

- [ ] **Step 2: 运行测试确认失败**

```bash
cd py && python -m pytest tests/test_deleted_pagination.py -q
```

Expected: TT 的 7 条 FAIL —— `KeyError: 'total'`。

- [ ] **Step 3: 改写端点**

把 `py/routes/tt_accounts_routes.py:700-727` 的 `deleted_accounts_list` 整个函数替换为：

```python
@tt_accounts_bp.route('/api/tt/accounts/deleted', methods=['GET'])
@jwt_required()
@tt_required
def deleted_accounts_list():
    """已删除账户列表（**分页** + 服务端搜索）。

    分页理由与 GG 的 `/api/accounts/deleted` 相同（见 main.py 该端点的 docstring）。
    响应在原有 `items` 之外**追加** `total` / `page` / `size` —— 纯增量。
    """
    db = get_db()
    uid = get_uid()
    role = _get_role(db, uid)
    page, size = parse_pagination(default=50)
    cross_user = role in CROSS_USER_ROLES
    owner_filter = request.args.get('owner_id', '').strip()
    if not cross_user:
        owner_filter = ''
    search = request.args.get('search', '').strip()

    where = ["a.deleted_at IS NOT NULL"]
    params = []
    if cross_user:
        if owner_filter:
            where.append("a.owner_id = ?")
            params.append(owner_filter)
    else:
        where.append("a.owner_id = ?")
        params.append(uid)
    if search:
        # 与前端原来的客户端过滤口径对齐：账户ID / 名称 / 代理名。
        where.append("(a.advertiser_id LIKE ? OR a.name LIKE ? OR ag.name LIKE ?)")
        like = f"%{search}%"
        params += [like, like, like]
    where_sql = " AND ".join(where)

    total = db.execute(
        f"SELECT COUNT(*) FROM tt_accounts a LEFT JOIN agents ag ON a.agent_id = ag.id "
        f"WHERE {where_sql}",
        params
    ).fetchone()[0]
    rows = db.execute(
        f"""SELECT a.id, a.name, a.advertiser_id, a.deleted_at,
                   ag.name AS agent_name, st.name AS status_name
            FROM tt_accounts a
            LEFT JOIN agents ag ON a.agent_id = ag.id
            LEFT JOIN account_statuses st ON a.status_id = st.id
            WHERE {where_sql}
            ORDER BY a.deleted_at DESC LIMIT ? OFFSET ?""",
        params + [size, (page - 1) * size]
    ).fetchall()

    items = []
    for r in rows:
        d = dict(r)
        d["agent"] = d.get("agent_name") or ""
        d["status"] = d.get("status_name") or ""
        items.append(d)
    return ok({"items": items, "total": total, "page": page, "size": size})
```

- [ ] **Step 4: 运行测试确认通过**

```bash
cd py && python -m pytest tests/test_deleted_pagination.py -q
```

Expected: PASS（12 passed）

- [ ] **Step 5: 全量回归**

```bash
cd py && python -m pytest tests/ -q
```

Expected: 与基线一致。

- [ ] **Step 6: 提交**

```bash
git add py/routes/tt_accounts_routes.py py/tests/test_deleted_pagination.py
git commit -m "feat(tt): /tt/accounts/deleted 补分页与服务端搜索"
```

---

## Task 5: FB 列表 N+1 改批查

**Files:**
- Modify: `py/routes/fb_routes.py:311-318`（`list_accounts` 的 BM 循环）
- Modify: `py/routes/fb_routes.py:488-494`（`list_deleted_accounts` 的 BM 循环）
- Test: `py/tests/test_fb_list_batch.py`（**新建**）

**Interfaces:**
- Consumes: 无（只用 `IN (...)` 直查）
- Produces: 无接口变化 —— `/api/fb/accounts/list` 与 `/api/fb/accounts/deleted`
  的每行 `bms` 字段内容不变（元素仍是 `{name, id, bm_id}`，已删除列表另有 `is_primary`）

**当前病灶**：每行单独查一次 BM。一页 50 行 = 50 次查询；页尺寸上限提到 500 后是 500 次。

- [ ] **Step 1: 写失败的测试**

新建 `py/tests/test_fb_list_batch.py`：

```python
"""FB 账户列表的 BM 批量查询 —— 消除每行一次查询的 N+1。"""
import os
import sys

_py_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _py_dir not in sys.path:
    sys.path.insert(0, _py_dir)


def _seed(db, uid, n_accounts, n_bms):
    bm_ids = []
    for i in range(n_bms):
        cur = db.execute(
            "INSERT INTO fb_bms(name, bm_id, owner_id, status) VALUES(?,?,?,'active')",
            (f"BM{i}", f"bm{i:06d}", uid),
        )
        bm_ids.append(cur.lastrowid)
    acc_ids = []
    for i in range(n_accounts):
        cur = db.execute(
            "INSERT INTO fb_accounts(name, account_id, owner_id) VALUES(?,?,?)",
            (f"fb{i}", f"fbacc{i:06d}", uid),
        )
        acc_ids.append(cur.lastrowid)
    # 每个账户挂到第 (i % n_bms) 个 BM 上
    for i, aid in enumerate(acc_ids):
        db.execute(
            "INSERT INTO fb_account_bm(account_id, bm_id, is_primary) VALUES(?,?,1)",
            (aid, bm_ids[i % n_bms]),
        )
    db.commit()
    return acc_ids, bm_ids


def test_fb_list_bms_are_grouped_correctly(app, client, admin_fb_headers):
    """正确性守卫：批查之后每行的 bms 仍必须是**它自己的**那个 BM。

    把批查写错（如 GROUP BY 分组键用错、或回填时用错下标）会让所有行
    拿到同一批 BM —— 这正是「不报错但数据全错」的形态。
    """
    import database
    db = database.get_db()
    uid = db.execute("SELECT id FROM users WHERE username='adminfb'").fetchone()["id"]
    _seed(db, uid, 12, 3)
    db.close()

    body = client.get("/api/fb/accounts/list?size=500", headers=admin_fb_headers).get_json()
    assert body["total"] == 12
    assert len(body["items"]) == 12
    for item in body["items"]:
        assert len(item["bms"]) == 1, f"账户 {item['account_id']} 应恰好挂 1 个 BM"
        # BM 名必须与该账户自身的挂载对应，不是别人那批
        expected_idx = int(item["account_id"].replace("fbacc", "")) % 3
        assert item["bms"][0]["name"] == f"BM{expected_idx}"


def test_fb_list_primary_bm_name_is_populated(app, client, admin_fb_headers):
    import database
    db = database.get_db()
    uid = db.execute("SELECT id FROM users WHERE username='adminfb'").fetchone()["id"]
    _seed(db, uid, 6, 2)
    db.close()

    body = client.get("/api/fb/accounts/list?size=500", headers=admin_fb_headers).get_json()
    for item in body["items"]:
        assert item["primary_bm_name"].startswith("BM")


def test_fb_list_account_without_bm_gets_empty_list(app, client, admin_fb_headers):
    """没挂 BM 的账户必须得到 `bms: []` 而不是缺字段或报错。"""
    import database
    db = database.get_db()
    uid = db.execute("SELECT id FROM users WHERE username='adminfb'").fetchone()["id"]
    db.execute("INSERT INTO fb_accounts(name, account_id, owner_id) VALUES('无BM','fbnone',?)", (uid,))
    db.commit()
    db.close()

    body = client.get("/api/fb/accounts/list?size=500", headers=admin_fb_headers).get_json()
    lonely = [i for i in body["items"] if i["account_id"] == "fbnone"]
    assert len(lonely) == 1
    assert lonely[0]["bms"] == []
    assert lonely[0]["primary_bm_name"] == ""


def test_fb_deleted_list_bms_are_grouped_correctly(app, client, admin_fb_headers):
    import database
    db = database.get_db()
    uid = db.execute("SELECT id FROM users WHERE username='adminfb'").fetchone()["id"]
    acc_ids, bm_ids = _seed(db, uid, 9, 3)
    for aid in acc_ids:
        db.execute("UPDATE fb_accounts SET deleted_at=datetime('now','localtime') WHERE id=?", (aid,))
    db.commit()
    db.close()

    body = client.get("/api/fb/accounts/deleted?size=500", headers=admin_fb_headers).get_json()
    assert body["total"] == 9
    for item in body["items"]:
        assert len(item["bms"]) == 1
```

- [ ] **Step 2: 运行测试确认失败**

```bash
cd py && python -m pytest tests/test_fb_list_batch.py -q
```

Expected: 前三条**可能已经通过**（现状的 N+1 逻辑是正确的，只是慢）—— 本任务的测试是**正确性守卫**，
用来证明改成批查之后行为没变。若它们已通过，把 `test_fb_deleted_list_bms_are_grouped_correctly`
作为主判据；**Step 4 之后四条必须仍全绿**。

> 说明：N+1 的「快」无法用单测直接断言（查询次数不进响应）。改成批查是否真的生效，
> 由 Step 4 的代码审查确认「循环里不再有 `db.execute`」。测试负责锁住**行为不变**。

- [ ] **Step 3: 改写 `list_accounts` 的 BM 循环**

把 `py/routes/fb_routes.py:311-318` 的这段：

```python
    result_items = []
    for r in rows:
        item = dict(r)
        bms = db.execute(
            "SELECT b.name, b.id, b.bm_id, ab.is_primary FROM fb_bms b "
            "JOIN fb_account_bm ab ON ab.bm_id = b.id "
            "WHERE ab.account_id = ?", (r['id'],)
        ).fetchall()
        item['bms'] = [dict(b) for b in bms]
        item['primary_bm_name'] = next((b['name'] for b in item['bms'] if b['is_primary']), '')
        result_items.append(item)
```

替换为：

```python
    # 一次查回本页所有账户的 BM，再在内存里按 account_id 分组。
    # 原来是**每行一次查询**（N+1）：页尺寸上限提到 500 后最坏 500 次往返。
    bms_by_account = {}
    row_ids = [r['id'] for r in rows]
    if row_ids:
        marks = ",".join("?" for _ in row_ids)
        for b in db.execute(
            f"SELECT ab.account_id, b.name, b.id, b.bm_id, ab.is_primary "
            f"FROM fb_bms b JOIN fb_account_bm ab ON ab.bm_id = b.id "
            f"WHERE ab.account_id IN ({marks})", row_ids
        ).fetchall():
            bms_by_account.setdefault(b['account_id'], []).append(
                {'name': b['name'], 'id': b['id'], 'bm_id': b['bm_id'],
                 'is_primary': b['is_primary']})

    result_items = []
    for r in rows:
        item = dict(r)
        item['bms'] = bms_by_account.get(r['id'], [])
        item['primary_bm_name'] = next((b['name'] for b in item['bms'] if b['is_primary']), '')
        result_items.append(item)
```

- [ ] **Step 4: 改写 `list_deleted_accounts` 的 BM 循环**

把 `py/routes/fb_routes.py:488-494` 的同形循环替换为（注意此处的查询**多一列 `is_primary`**，
但响应里原来就不含 `is_primary`，**保持不含**以维持逐字节兼容）：

```python
    bms_by_account = {}
    row_ids = [r['id'] for r in rows]
    if row_ids:
        marks = ",".join("?" for _ in row_ids)
        for b in db.execute(
            f"SELECT ab.account_id, b.name, b.id, b.bm_id "
            f"FROM fb_bms b JOIN fb_account_bm ab ON ab.bm_id = b.id "
            f"WHERE ab.account_id IN ({marks})", row_ids
        ).fetchall():
            bms_by_account.setdefault(b['account_id'], []).append(
                {'name': b['name'], 'id': b['id'], 'bm_id': b['bm_id']})

    result_items = []
    for r in rows:
        item = dict(r)
        item['bms'] = bms_by_account.get(r['id'], [])
        result_items.append(item)
```

- [ ] **Step 5: 运行测试确认通过**

```bash
cd py && python -m pytest tests/test_fb_list_batch.py -q
```

Expected: PASS（4 passed）

- [ ] **Step 6: 代码审查确认循环里没有 `db.execute`**

人工检查改写后的两段：`for r in rows:` 循环体内**不得**出现 `db.execute`。
这是本任务唯一真正证明「N+1 已消除」的判据。

- [ ] **Step 7: 全量回归**

```bash
cd py && python -m pytest tests/ -q
```

Expected: 与基线一致，尤其 `test_fb_platform.py`、`test_fb_asset_model.py`。

- [ ] **Step 8: 提交**

```bash
git add py/routes/fb_routes.py py/tests/test_fb_list_batch.py
git commit -m "perf(fb): 列表 BM 改批量查询，消除每行一次的 N+1"
```

---

## Task 6: 既有 `IN (...)` 接入 `chunk`

**Files:**
- Modify: `py/main.py`（`batch-lookup` 约 4337、`batch-delete` 计数约 5070、`batch-update` 反查约 5155、GG sync 约 5307）
- Modify: `py/routes/tt_accounts_routes.py`（约 186、244）
- Modify: `py/huguan_dashboard.py`（约 500、1331）

> ⚠️ 规格 §6.4 把 `huguan_dashboard.py` 列了三处（500/956/1331），其中 **956 不是 `IN` 子句** ——
> 它是 `INSERT INTO {table}({cols}) VALUES({marks})` 的列绑定，`src` 只有十几个字段，无变量上限问题。
> **只改 500 与 1331 两处**，不要动 956。
- Test: `py/tests/test_chunk_callers.py`（**新建**）

**Interfaces:**
- Consumes: Task 1 的 `utils.chunk`
- Produces: 无接口变化

**手法**：`chunk` 在调用时读取模块常量 `utils.CHUNK_SIZE`，所以守卫测试把 `CHUNK_SIZE`
monkeypatch 成 `3`，再用 10 个 id 调端点 —— **如果调用点没真的走 `chunk`，行为不会有任何变化，
测试就抓不到；一旦走了，分块路径就被真实执行**。

- [ ] **Step 1: 写失败的测试**

新建 `py/tests/test_chunk_callers.py`：

```python
"""验证既有 `IN (...)` 调用点真的走了 utils.chunk。

手法：把**消费模块**里的 `chunk` 名字换成一个「强制每段 3 个元素」的记录器，
再用 10 个 id 调端点。10 个 id 在真实 CHUNK_SIZE=900 下只会产生 1 段，
所以**必须**让 spy 强行切成 4 段 —— 否则「调用点压根没分块」和「分块了但只有
一段」这两种情况在断言上无法区分，测试会对真正的失效完全失明。
"""
import os
import sys

_py_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _py_dir not in sys.path:
    sys.path.insert(0, _py_dir)

# 消费 `chunk` 的模块名。必须打**这些模块**的名字，不能打 `utils.chunk` ——
# main.py 用的是 `from utils import chunk`，那是模块级的独立名字绑定，
# 改 utils 里那个对 main.chunk 没有任何影响（这正是本测试要防的
# 「以为分块了其实没有」）。
_CHUNK_CONSUMERS = ("main", "huguan_dashboard", "routes.tt_accounts_routes")


class _ChunkSpy:
    """记录 chunk 调用，并把每段强制压到 3 个元素。"""

    def __init__(self, monkeypatch):
        self.calls = []
        patched = []

        def spy(seq, size=None):
            items = list(seq)
            self.calls.append(len(items))
            return [items[i:i + 3] for i in range(0, len(items), 3)]

        for name in _CHUNK_CONSUMERS:
            mod = sys.modules.get(name)
            if mod is not None and hasattr(mod, "chunk"):
                monkeypatch.setattr(mod, "chunk", spy, raising=True)
                patched.append(name)
        assert patched, "没有任何消费模块被装上 spy —— 说明导入还没加"

    @property
    def was_used(self):
        """至少有一次分块调用，且输入长度超过了 spy 的段长 3。"""
        return any(n > 3 for n in self.calls)


def test_batch_lookup_uses_chunk(app, client, auth_headers, monkeypatch):
    import database
    db = database.get_db()
    uid = db.execute("SELECT id FROM users WHERE username='testuser'").fetchone()["id"]
    ids = [f"look{i:04d}" for i in range(10)]
    for aid in ids:
        db.execute("INSERT INTO accounts(name, account_id, owner_id) VALUES(?,?,?)",
                   (aid, aid, uid))
    db.commit()
    db.close()

    spy = _ChunkSpy(monkeypatch)
    resp = client.post("/api/accounts/batch-lookup",
                       json={"account_ids": ids}, headers=auth_headers)
    assert resp.status_code == 200
    # 分块后必须把 4 段结果**合并**，不能只返回最后一段 —— 这是改写时最易犯的错。
    assert len(resp.get_json()["found"]) == 10
    assert spy.was_used, "batch-lookup 没有走 chunk"


def test_batch_lookup_chunk_results_are_merged(app, client, auth_headers, monkeypatch):
    """分块后结果必须合并：断言总数，能抓住「只返回最后一段」的写法。"""
    import database
    db = database.get_db()
    uid = db.execute("SELECT id FROM users WHERE username='testuser'").fetchone()["id"]
    ids = [f"m{i:04d}" for i in range(10)]
    for aid in ids:
        db.execute("INSERT INTO accounts(name, account_id, owner_id) VALUES(?,?,?)",
                   (aid, aid, uid))
    db.commit()
    db.close()

    _ChunkSpy(monkeypatch)
    body = client.post("/api/accounts/batch-lookup",
                       json={"account_ids": ids}, headers=auth_headers).get_json()
    assert len(body["found"]) == 10
    assert body["not_found"] == []


def test_huguan_collect_rows_uses_chunk(app, monkeypatch):
    """collect_rows_for_push 的 IN（huguan_dashboard.py 约 1331）。"""
    import database
    import huguan_dashboard as hd
    db = database.get_db()
    db.execute("INSERT OR IGNORE INTO users(id, username, password, role) VALUES(1,'dev','x','developer')")
    for i in range(10):
        db.execute("INSERT INTO accounts(name, account_id, owner_id) VALUES(?,?,1)",
                   (f"acc{i}", f"hd{i:04d}"))
    db.commit()

    spy = _ChunkSpy(monkeypatch)
    rows = hd.collect_rows_for_push(db, "gg", [f"hd{i:04d}" for i in range(10)])
    db.close()

    # 必须回全部 10 行，不是最后一段的 1 行。
    assert len(rows) == 10
    assert spy.was_used, "collect_rows_for_push 没有走 chunk"


def test_huguan_apply_diff_lookup_uses_chunk(app, monkeypatch):
    """apply_diff 查现有账户的那条 IN（huguan_dashboard.py 约 500）。"""
    import huguan_dashboard as hd
    assert hasattr(hd, "chunk"), "huguan_dashboard 还没有导入 chunk"
```

> 最后一条只断言导入存在：`apply_diff` 的入参形状复杂（要造出完整的
> `parsed_rows` 结构），端到端造起来不划算。它真正的行为守卫由
> `test_huguan_dashboard.py` 既有的 apply_diff 全套用例承担 —— 本任务
> 改完后那套用例必须全绿，即证明改写没破坏行为。

- [ ] **Step 2: 运行测试确认失败**

```bash
cd py && python -m pytest tests/test_chunk_callers.py -q
```

Expected: FAIL —— `AssertionError: 没有任何消费模块被装上 spy —— 说明导入还没加`
（Step 3 加导入前，`main` / `huguan_dashboard` / `routes.tt_accounts_routes` 三个模块都还没有
`chunk` 这个名字）。

- [ ] **Step 3: 给三个模块加导入**

`py/main.py` 第 29 行改为：

```python
from utils import extract_package_name, natural_sort_key, chunk
```

`py/routes/tt_accounts_routes.py` 的模块导入区追加：

```python
from utils import chunk
```

`py/huguan_dashboard.py` 在顶层导入区追加（该模块有意不在 import 期依赖 `database`，
但 `utils` 无依赖，可以直接顶层导入）：

```python
from utils import chunk
```

- [ ] **Step 4: 逐个改写 `IN (...)` 调用点**

统一形状（以 `batch-lookup` 为例，`main.py` 约 4337）：

替换前：
```python
    db = _yt_db()
    placeholders = ",".join(["?"] * len(clean_ids))
    rows = db.execute(
        f"SELECT a.*, m.name AS mcc_name, ... "
        f"WHERE a.account_id IN ({placeholders})",
        clean_ids
    ).fetchall()
```

替换后：
```python
    db = _yt_db()
    # 分块绑定：SQLite 3.45.1 的变量上限是 32766，上万 id 一次绑定会抛
    # `too many SQL variables`。用 chunk 分批，结果合并。
    rows = []
    for part in chunk(clean_ids):
        marks = ",".join("?" for _ in part)
        rows.extend(db.execute(
            f"SELECT a.*, m.name AS mcc_name, ... "
            f"WHERE a.account_id IN ({marks})",
            part
        ).fetchall())
```

对**计数**类查询（`main.py` 约 5070 `SELECT COUNT(*) ... IN (...)`），把各段结果**累加**：

```python
    total_found = 0
    for part in chunk(ids):
        marks = ",".join("?" for _ in part)
        total_found += db.execute(
            f"SELECT COUNT(*) FROM accounts WHERE id IN ({marks}) AND owner_id=?",
            tuple(part) + (user_id,)
        ).fetchone()[0]
```

对 **GG sync 的现有账户查询**（`main.py` 约 5307），把 `placeholders` 换成逐段查询后
合并进同一个 `existing_map`：

```python
    existing_map = {}
    for part in chunk(sheet_ids):
        marks = ",".join("?" for _ in part)
        for r in db.execute(
            f"""SELECT a.id, a.account_id, a.timezone, a.agent_id, a.status_id,
                       a.deleted_at,
                       ag.name AS agent_name, st.name AS status_name
                FROM accounts a
                LEFT JOIN agents ag ON a.agent_id = ag.id
                LEFT JOIN account_statuses st ON a.status_id = st.id
                WHERE a.account_id IN ({marks}) AND a.owner_id = ?""",
            tuple(part) + (user_id,)
        ).fetchall():
            existing_map[r["account_id"]] = dict(r)
```

对 `huguan_dashboard.py` 的**两处**（**不要动 956，它不是 IN 子句**）：

**其一：`apply_diff` 查现有账户（约 496-508）**

替换前：
```python
    existing_map = {}
    if ids:
        marks = ",".join("?" for _ in ids)
        table = _TABLE_FOR_PLATFORM[platform]
        rows = db.execute(
            f"""SELECT a.*, u.display_name AS owner_display, u.username AS owner_username
                FROM {table} a LEFT JOIN users u ON a.owner_id = u.id
                WHERE a.{key_field} IN ({marks})""",
            ids,
        ).fetchall()
        for r in rows:
            existing_map[r[key_field]] = dict(r)
```

替换后（逐段查询、**合并进同一个 map**）：
```python
    existing_map = {}
    if ids:
        table = _TABLE_FOR_PLATFORM[platform]
        # 分块绑定：上万账户时一次 IN 会超 SQLite 的 32766 变量上限。
        for part in chunk(ids):
            marks = ",".join("?" for _ in part)
            for r in db.execute(
                f"""SELECT a.*, u.display_name AS owner_display, u.username AS owner_username
                    FROM {table} a LEFT JOIN users u ON a.owner_id = u.id
                    WHERE a.{key_field} IN ({marks})""",
                tuple(part),
            ).fetchall():
                existing_map[r[key_field]] = dict(r)
```

**其二：`collect_rows_for_push`（约 1325-1340）**

替换前：
```python
    conds = ["a.deleted_at IS NULL"]
    if account_ids is not None:
        if not account_ids:
            return []
        marks = ",".join("?" for _ in account_ids)
        conds.append(f"a.{ACCOUNT_KEY_FIELD[platform]} IN ({marks})")
        params = tuple(account_ids)
    sql += " WHERE " + " AND ".join(conds)

    out = []
    for r in db.execute(sql, params).fetchall():
        row = dict(r)
        out.append({"account_id": str(row.get("account_id") or "").strip(),
                    "cells": cells_for_row(row, platform)})
    return [o for o in out if o["account_id"]]
```

替换后（先把「要执行的查询列表」拼出来，再统一跑 —— 保持原有的「条件先累积成 list
再统一拼」写法，不引入「先拼 WHERE 再找地方插 AND」）：
```python
    conds = ["a.deleted_at IS NULL"]
    # 每项是 (sql, params)。account_ids 给定时用 chunk 切成多段查询；
    # None 表示全部，单条查询即可。
    queries = []
    if account_ids is None:
        queries.append((sql + " WHERE " + " AND ".join(conds), ()))
    else:
        if not account_ids:
            return []
        for part in chunk(account_ids):
            marks = ",".join("?" for _ in part)
            part_conds = conds + [f"a.{ACCOUNT_KEY_FIELD[platform]} IN ({marks})"]
            queries.append((sql + " WHERE " + " AND ".join(part_conds), tuple(part)))

    out = []
    for q_sql, q_params in queries:
        for r in db.execute(q_sql, q_params).fetchall():
            row = dict(r)
            out.append({"account_id": str(row.get("account_id") or "").strip(),
                        "cells": cells_for_row(row, platform)})
    return [o for o in out if o["account_id"]]
```

- [ ] **Step 5: 运行测试确认通过**

```bash
cd py && python -m pytest tests/test_chunk_callers.py -q
```

Expected: PASS（4 passed）

- [ ] **Step 6: 全量回归**

```bash
cd py && python -m pytest tests/ -q
```

Expected: 与基线一致。重点看 `test_huguan_dashboard.py`（改动最多，尤其
`collect_rows_for_push` 与 `apply_diff` 的全套用例）与 `test_tt_accounts.py`。

- [ ] **Step 7: 提交**

```bash
git add py/main.py py/routes/tt_accounts_routes.py py/huguan_dashboard.py py/tests/test_chunk_callers.py
git commit -m "fix(sql): 既有 IN (...) 调用点接入 chunk，防超 32766 变量上限"
```

---

## Task 7: 前端 —— GG 已删除弹窗改分页

**Files:**
- Modify: `frontend/src/api/accounts.js:20`
- Modify: `frontend/src/stores/accounts.js:86-89`
- Modify: `frontend/src/components/AccountDeletedModal.vue`

**Interfaces:**
- Consumes: Task 3 的 `/api/accounts/deleted?page=&size=&search=` → `{accounts, total, page, size}`
- Produces: `store.loadDeletedAccounts(params) -> {accounts, total, page, size}`
  （**注意：返回值从「数组」变成「对象」**，调用方必须同步改）

- [ ] **Step 1: 改 API 层**

`frontend/src/api/accounts.js:20`：

```javascript
  listDeleted: (params) => api.get('/accounts/deleted', { params }),
```

- [ ] **Step 2: 改 store**

`frontend/src/stores/accounts.js:86-89`，替换 `loadDeletedAccounts`：

```javascript
    async loadDeletedAccounts(params = {}) {
      // 返回形状从「数组」改为后端的分页对象 {accounts, total, page, size}。
      // 上万行时前端只拿一页，不再全量拉取渲染。
      return accountsApi.listDeleted(params)
    },
```

- [ ] **Step 3: 改组件**

`frontend/src/components/AccountDeletedModal.vue` 的 `<script setup>` 整段替换为：

```javascript
import { ref, watch } from 'vue'
import { useAccountStore } from '@/stores/accounts'
import { ElMessage, ElMessageBox } from 'element-plus'

const props = defineProps({ visible: Boolean })
const emit = defineEmits(['update:visible', 'restored'])

const store = useAccountStore()
const rows = ref([])
const total = ref(0)
const page = ref(1)
const size = ref(20)
const searchText = ref('')
const restoring = ref(null)
const deleting = ref(null)

let searchTimer = null

async function load() {
  try {
    const res = await store.loadDeletedAccounts({
      page: page.value, size: size.value, search: searchText.value,
    })
    rows.value = res.accounts || []
    total.value = res.total || 0
  } catch (e) {
    ElMessage.error(e.response?.data?.error || '加载失败')
  }
}

function onSearchInput() {
  // 搜索改走服务端（分页后前端只有当前页，本地过滤会漏结果）。
  // 300ms 防抖避免每敲一个字打一次后端。
  clearTimeout(searchTimer)
  searchTimer = setTimeout(() => { page.value = 1; load() }, 300)
}

function onPageChange(p) { page.value = p; load() }
function onSizeChange(s) { size.value = s; page.value = 1; load() }

// 每次打开都从第一页、清空搜索重来 —— 与改动前 @open="load" 的行为一致。
watch(() => props.visible, (v) => {
  if (v) { page.value = 1; searchText.value = ''; load() }
})
```

`<template>` 整段替换为：

```html
<el-dialog :model-value="visible" @update:model-value="$emit('update:visible', $event)"
  title="🗑 已删除账户" width="750px">
  <div style="display:flex;gap:8px;margin-bottom:12px;align-items:center;">
    <el-input v-model="searchText" @input="onSearchInput"
      placeholder="🔍 搜索账户ID / 名称 / 代理..." clearable style="flex:1;" />
    <span style="color:#888;font-size:12px;white-space:nowrap;">共 {{ total }} 条</span>
  </div>
  <el-table :data="rows" size="small" border stripe v-if="rows.length">
    <el-table-column prop="account_id" label="账户ID" min-width="130" show-overflow-tooltip />
    <el-table-column prop="name" label="账户名称" min-width="100">
      <template #default="{ row }">
        <span v-if="row.name">{{ row.name }}</span>
        <span v-else style="color:#ccc;">—</span>
      </template>
    </el-table-column>
    <el-table-column prop="agent" label="代理" width="80" />
    <el-table-column prop="timezone" label="时区" width="80" />
    <el-table-column label="状态" width="80">
      <template #default="{ row }">
        <el-tag size="small" type="info">{{ row.status || '未知' }}</el-tag>
      </template>
    </el-table-column>
    <el-table-column prop="deleted_at" label="删除时间" min-width="120" />
    <el-table-column label="操作" width="130">
      <template #default="{ row }">
        <el-button link type="success" size="small" @click="doRestore(row)" :loading="restoring === row.id">恢复</el-button>
        <el-button link type="danger" size="small" @click="doPermanentDelete(row)" :loading="deleting === row.id">删除</el-button>
      </template>
    </el-table-column>
  </el-table>
  <el-empty v-else :description="searchText ? '无匹配结果' : '暂无已删除账户'" :image-size="50" />

  <div v-if="total > size" style="display:flex;justify-content:flex-end;margin-top:12px;">
    <el-pagination v-model:current-page="page" :page-size="size" :total="total"
      :page-sizes="[20, 50, 100, 200]" layout="sizes, prev, pager, next"
      background small
      @current-change="onPageChange" @size-change="onSizeChange" />
  </div>

  <template #footer>
    <el-button @click="$emit('update:visible', false)">关闭</el-button>
  </template>
</el-dialog>
```

- [ ] **Step 4: 恢复/删除成功后刷新当前页**

`doRestore` 与 `doPermanentDelete` 里原来的

```javascript
    allAccounts.value = allAccounts.value.filter(a => a.id !== row.id)
```

两处都替换为：

```javascript
    await load()
```

（分页后不能只在前端数组里删一行 —— 那会让本页少一条却不补上下一页的第一条，
且 `total` 与实际不符。重新拉当前页最省事也最正确。）

- [ ] **Step 5: 构建验证**

```bash
cd frontend && npm run build
```

Expected: 构建成功，无 `allAccounts is not defined` 之类的编译错误。

- [ ] **Step 6: 提交**

```bash
git add frontend/src/api/accounts.js frontend/src/stores/accounts.js frontend/src/components/AccountDeletedModal.vue
git commit -m "feat(frontend): GG 已删除账户弹窗改分页渲染 + 服务端搜索"
```

---

## Task 8: 前端 —— TT 已删除弹窗改分页

**Files:**
- Modify: `frontend/src/api/tt.js:82`
- Modify: `frontend/src/components/tt/TtAccountDeletedModal.vue`

**Interfaces:**
- Consumes: Task 4 的 `/api/tt/accounts/deleted?page=&size=&search=` → `{items, total, page, size}`
- Produces: 无（组件内部状态）

- [ ] **Step 1: 改 API 层**

`frontend/src/api/tt.js:82`：

```javascript
  listDeleted: (params) => client.get('/tt/accounts/deleted', { params }),
```

- [ ] **Step 2: 改组件 script**

`frontend/src/components/tt/TtAccountDeletedModal.vue` 的 `<script setup>` 整段替换为：

```javascript
import { ref, watch } from 'vue'
import { ttAccountsApi } from '@/api/tt'
import { ElMessage, ElMessageBox } from 'element-plus'

const props = defineProps({ visible: Boolean })
const emit = defineEmits(['update:visible', 'restored'])

const rows = ref([])
const total = ref(0)
const page = ref(1)
const size = ref(20)
const searchText = ref('')
const restoring = ref(null)
const deleting = ref(null)

let searchTimer = null

async function load() {
  try {
    const res = await ttAccountsApi.listDeleted({
      page: page.value, size: size.value, search: searchText.value,
    })
    rows.value = res.items || []
    total.value = res.total || 0
  } catch (e) {
    ElMessage.error(e.response?.data?.error || '加载失败')
  }
}

function onSearchInput() {
  // 搜索走服务端：分页后前端只有当前页，本地过滤会漏掉其余页的匹配项。
  clearTimeout(searchTimer)
  searchTimer = setTimeout(() => { page.value = 1; load() }, 300)
}

function onPageChange(p) { page.value = p; load() }
function onSizeChange(s) { size.value = s; page.value = 1; load() }

watch(() => props.visible, (v) => {
  if (v) { page.value = 1; searchText.value = ''; load() }
})
```

- [ ] **Step 3: 改组件 template**

`<template>` 整段替换为（列定义与原来逐字一致，只换数据源与加分页）：

```html
<el-dialog :model-value="visible" @update:model-value="$emit('update:visible', $event)"
  title="🗑 已删除账户" width="750px">
  <div style="display:flex;gap:8px;margin-bottom:12px;align-items:center;">
    <el-input v-model="searchText" @input="onSearchInput"
      placeholder="🔍 搜索广告账户 ID / 名称 / 代理..." clearable style="flex:1;" />
    <span style="color:#888;font-size:12px;white-space:nowrap;">共 {{ total }} 条</span>
  </div>
  <el-table :data="rows" size="small" border stripe v-if="rows.length">
    <el-table-column prop="advertiser_id" label="广告账户 ID" min-width="150" show-overflow-tooltip />
    <el-table-column prop="name" label="账户名称" min-width="120">
      <template #default="{ row }">
        <span v-if="row.name">{{ row.name }}</span>
        <span v-else style="color:#ccc;">—</span>
      </template>
    </el-table-column>
    <el-table-column prop="agent" label="代理" width="90">
      <template #default="{ row }">
        <span v-if="row.agent">{{ row.agent }}</span>
        <span v-else style="color:#ccc;">—</span>
      </template>
    </el-table-column>
    <el-table-column label="状态" width="80">
      <template #default="{ row }">
        <el-tag size="small" type="info">{{ row.status || '未知' }}</el-tag>
      </template>
    </el-table-column>
    <el-table-column prop="deleted_at" label="删除时间" min-width="120" />
    <el-table-column label="操作" width="130">
      <template #default="{ row }">
        <el-button link type="success" size="small" @click="doRestore(row)" :loading="restoring === row.id">恢复</el-button>
        <el-button link type="danger" size="small" @click="doPermanentDelete(row)" :loading="deleting === row.id">删除</el-button>
      </template>
    </el-table-column>
  </el-table>
  <el-empty v-else :description="searchText ? '无匹配结果' : '暂无已删除账户'" :image-size="50" />

  <div v-if="total > size" style="display:flex;justify-content:flex-end;margin-top:12px;">
    <el-pagination v-model:current-page="page" :page-size="size" :total="total"
      :page-sizes="[20, 50, 100, 200]" layout="sizes, prev, pager, next"
      background small
      @current-change="onPageChange" @size-change="onSizeChange" />
  </div>

  <template #footer>
    <el-button @click="$emit('update:visible', false)">关闭</el-button>
  </template>
</el-dialog>
```

- [ ] **Step 4: 恢复/删除成功后刷新当前页**

`doRestore` 与 `doPermanentDelete` 里的

```javascript
    allAccounts.value = allAccounts.value.filter(a => a.id !== row.id)
```

两处都替换为：

```javascript
    await load()
```

- [ ] **Step 5: 构建验证**

```bash
cd frontend && npm run build
```

Expected: 构建成功。

- [ ] **Step 6: 提交**

```bash
git add frontend/src/api/tt.js frontend/src/components/tt/TtAccountDeletedModal.vue
git commit -m "feat(frontend): TT 已删除账户弹窗改分页渲染 + 服务端搜索"
```

---

## Task 9: 端到端验收与门禁

**Files:**
- 无代码改动；只跑门禁与人工验收

**Interfaces:**
- Consumes: Task 1–8 的全部产出
- Produces: 无

- [ ] **Step 1: 后端全量回归**

```bash
cd py && python -m pytest tests/ -q
```

Expected: 与基线一致 —— **基线实测 1443 passed, 0 failed**（2026-10-07 在
`.claude/worktrees/sheet-sync-pagination` 上跑出，耗时约 8.5 分钟）。

> 早先本计划与规格 §9.3 都记着「`test_fb_asset_model.py` 的 24 条是红的」——**该记录已过时**，
> 实测该文件现在 32 passed / 0 failed（4 位密码那条既有缺陷已被其它会话修掉）。
> 也就是说**全量回归必须是全绿**，不存在任何可以豁免的既有红测试。
> 如果改完出现红测试，**一律是本计划引入的**，必须查到底，不得当作既有问题跳过。

- [ ] **Step 2: 前端构建**

```bash
cd frontend && npm run build
```

Expected: 成功。

- [ ] **Step 3: 人工验收清单（必须逐条实测，不得只看代码）**

启动服务前**先征得用户同意**（本仓库约定：不得自动启动进程）。

| # | 操作 | 预期 |
|---|---|---|
| 1 | 造 1000 个已删账户，打开 GG 已删除弹窗 | 只渲染 20 行，出现分页条，浏览器不卡 |
| 2 | 点第 2 页 | 内容变化，与第 1 页无重复 |
| 3 | 搜索框输入某账户ID片段 | 300ms 后出结果，且 **`共 N 条` 显示的是全库匹配数**，不是当前页数 |
| 4 | 切页尺寸到 200 | 返回 200 行，仍不卡 |
| 5 | 在弹窗里恢复一个账户 | 列表刷新，`共 N 条` 减 1 |
| 6 | TT 已删除弹窗重复 1–5 | 同上 |
| 7 | 浏览器直接访问 `/api/accounts/deleted?size=999999` | 返回 ≤500 条，不 500 |
| 8 | 浏览器直接访问 `/api/accounts/list?size=abc` | 返回 200，走默认页尺寸（**改动前这里是 500**） |
| 9 | 打开 FB 账户列表（一页 50 行） | 每行的 BM 列显示正确，没有串行/串户 |

第 8 条是**行为变更**，必须实测确认它确实变好了（原来 500 → 现在 200）。

- [ ] **Step 4: 调用 `/code-review`**

本计划触及 SQL 拼接（`IN` 分块、动态 `WHERE`）与数据归属（`owner_id` 隔离条件），
按项目规矩**必须**在交付前调 `/code-review`，修完发现的问题再交付。

- [ ] **Step 5: 终态提交（若有 review 修复）**

```bash
git add <review 修复涉及的具体文件>
git commit -m "fix(pagination): 处理 code review 发现的问题"
```

---

## 自审记录

**规格覆盖核对**（对照 `2026-10-07-sheet-sync-scale-design.md` §6）：

| 规格条目 | 对应任务 |
|---|---|
| §6.1 GG `/api/accounts/deleted` 补分页 | Task 3 |
| §6.1 TT `/tt/accounts/deleted` 补分页 | Task 4 |
| §6.1 前端两个弹窗改分页渲染 | Task 7、Task 8 |
| §6.2 `size` 上限 500、钳制不报错、复用 `parse_pagination` | Task 1、Task 2 |
| §6.3 FB 列表 N+1 改批查 | Task 5 |
| §6.4 既有 `IN (...)` 接入 `chunk(900)` | Task 1、Task 6 |
| §6.4 规格把 `huguan_dashboard.py:956` 误列为 `IN` 子句 | **已剔除**（见 Task 6 顶部警示，它是 `INSERT ... VALUES` 的列绑定） |
| §9.1 分页闸门测试、已删除列表分页测试 | Task 2、Task 3、Task 4 |
| §9.1 `IN` 分块测试 | Task 6 |
| §9.1 FB N+1 消除测试 | Task 5 |
| §9.4 交付前 `/code-review` | Task 9 |

**规格中不在本计划范围的**（留给第 ① ② 部分的计划）：§4 写表通道、§5 从表同步批量化、
§7 配额预算（依赖 ① 的冲刷器）。

**已知偏离规格之处**：规格 §8 把 `chunk` 放在 `py/routes/helpers.py`；本计划改放
`py/utils.py`。理由：`chunk` 是无依赖纯函数，而 `routes/helpers.py` 会 import `database` 与
`auth`，让 `huguan_dashboard.py`（§6.4 需要 `chunk`）去 import 它有循环导入风险。
`utils.py` 已被 `main.py:29` 与 `resizer.py` 使用，是既有惯例。
