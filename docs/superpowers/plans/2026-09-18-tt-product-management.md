# TT 产品管理模块实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为 GG-Server 新增 TikTok（TT）平台的第一阶段「产品管理」大模块，功能对标 GG 产品管理完整度（产品 CRUD、投放对象「跑包/PWA」管理、在跑人员、BC 关联、合并、粘贴解析、掉包检测、素材关联），并让用户体系支持 TT 平台。

**Architecture:** 采用「独立复制」模式（与 FB 一致）：新建 `tt_*` 独立表 + `py/routes/tt_routes.py` 独立路由 + `frontend/src/views/tt/` 独立页面，对 GG 代码零侵入。共享层仅做「平台三值化」最小改动（`users.platform` 值域扩为 `gg|fb|tt`）。投放对象建模为单表 `tt_packages` + `type` 字段区分 `package`（跑包）与 `pwa`（PWA 链接）。

**Tech Stack:** Flask + SQLite（后端）、Vue 3 + Vite + Pinia + Element Plus（前端）、pytest（后端 TDD）。复用 `py/delist_checker.py` 掉包检测核心与共享视频库 `videos` 表。

## Global Constraints

- 平台值域三值化：`'gg' | 'fb' | 'tt'`（`users.platform` 默认 `'gg'`）。
- 纯增量原则：只新增 `tt_*` 表/文件，不修改任何 GG 或 FB 的现有业务逻辑；对共享层的改动仅限「平台值域放宽」与「新增 `tt_required` 装饰器」，不得改变 gg/fb 现有行为。
- 投放对象：`tt_packages.type` 为 `'package'`（跑包，对标 GG 包）或 `'pwa'`（PWA 链接，第一阶段仅手工 CRUD）。跑包才有掉包检测。
- 跑包 `series_name` 采用前缀/后缀拼接自定义（对标 GG）；PWA 的 `series_name` 直接填写、不拼接。
- BC 是产品级单选关联（`tt_products.bc_id`），对标 GG 的 `mcc_id`，不是 FB 的 `fb_product_bms` 多选。
- 在跑人员用独立关联表 `tt_product_runners`（对标 FB），不用 GG 的 `runner_ids` JSON 列。
- 后端所有 TT 路由挂 `/api/tt/*`，统一 `@jwt_required()` + `@tt_required`。
- 测试运行命令：`cd py && python -m pytest tests/ -v`（依赖 `py/tests/conftest.py` 的 `app`/`client`/`auth_headers` fixtures）。
- 提交信息风格沿用仓库现有 conventional commits（`feat:` / `fix:` / `chore:`）。

---

## 文件结构

### 新建文件

| 文件 | 职责 |
|------|------|
| `py/routes/tt_routes.py` | TT 产品管理全部 API 路由（BC/产品/投放对象/掉包检测/合并/粘贴解析/素材/用户） |
| `py/tests/test_tt_platform.py` | 表结构测试 + 平台三值化（装饰器/用户校验）测试 |
| `py/tests/test_tt_routes.py` | TT 路由集成测试（BC/产品/投放对象/掉包/合并/解析/素材/用户） |
| `frontend/src/api/tt.js` | TT API 调用模块 |
| `frontend/src/views/tt/TtBcPanel.vue` | BC 管理页（简单 CRUD） |
| `frontend/src/views/tt/TtProductPanel.vue` | 产品管理页（产品列表 + 弹窗含投放对象子表/在跑人员/BC） |

> 说明：设计文档第八节曾列出 `stores/tt.js`，但 FB 实际实现（`FbProductPanel.vue` 直接 `import fbApi`，无独立 store）未使用独立 store。本计划遵循现有模式，**不新建 `stores/tt.js`**，组件直接 `import ttApi`。

### 修改文件

| 文件 | 改动 |
|------|------|
| `py/database.py` | 新增 6 张 TT 表 + `_copy_gg_options_to_tt` 迁移 + `_migrate_if_needed` 调用 |
| `py/routes/decorators.py` | 新增 `tt_required` 装饰器 |
| `py/main.py` | 注册 `tt_bp`；`admin_create_user`/`admin_update_user` 校验加 `'tt'`；`_guard_gg_platform` 跳过 `/api/tt/` |
| `py/tests/conftest.py` | 新增 `tt_headers` fixture（TT 平台用户认证头） |
| `frontend/src/stores/auth.js` | 加 `isTtUser` getter；`effectivePlatform` 三值 |
| `frontend/src/router/index.js` | TT 路由 + 平台守卫三值 + 首页跳转三值 |
| `frontend/src/components/AppSidebar.vue` | 平台切换 `[GG][FB][TT]` + TT 菜单 |
| `frontend/src/views/UserManageView.vue` | 创建/编辑用户平台下拉加 TT 选项 |

---

## Task 1: TT 数据库建表 + 选项迁移

**Files:**
- Modify: `py/database.py:530-670`（在 FB 表块后追加 TT 表）、`py/database.py:1072-1120`（新增 `_copy_gg_options_to_tt`）、`py/database.py:1122-1128`（`_migrate_if_needed` 调用）
- Test: `py/tests/test_tt_platform.py`（新建）

**Interfaces:**
- Consumes: `database._ensure_schema(conn)`（现有建表函数，`conn.executescript` 内追加）、`database._migrate_if_needed(conn)`（现有迁移入口）
- Produces: 6 张表 `tt_bcs` / `tt_products` / `tt_product_runners` / `tt_packages` / `tt_delist_checks` / `tt_product_assets`；函数 `_copy_gg_options_to_tt(conn)`；选项数据 `regions`/`sales_persons`/`account_statuses` 中 `platform='tt'` 行

- [ ] **Step 1: 写失败的表结构测试**

新建 `py/tests/test_tt_platform.py`：

```python
"""TT 平台数据库表结构测试。"""
import os
import sys
import tempfile

_py_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _py_dir not in sys.path:
    sys.path.insert(0, _py_dir)

import database  # noqa: E402


def _fresh_conn():
    db_fd, db_path = tempfile.mkstemp(suffix=".db")
    conn = database.get_db()
    conn.close()
    # 用临时库重新建 schema
    os.close(db_fd)
    return db_path


def test_tt_tables_exist():
    fd, db_path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    import sqlite3
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    database._ensure_schema(conn)
    conn.commit()

    tables = {r["name"] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    for t in ["tt_bcs", "tt_products", "tt_product_runners",
              "tt_packages", "tt_delist_checks", "tt_product_assets"]:
        assert t in tables, f"缺少表 {t}"
    conn.close()
    os.unlink(db_path)


def test_tt_packages_has_type_column():
    fd, db_path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    import sqlite3
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    database._ensure_schema(conn)

    cols = {r[1] for r in conn.execute("PRAGMA table_info(tt_packages)")}
    for c in ["id", "product_id", "type", "series_name", "package_name",
              "url", "status", "created_at", "updated_at"]:
        assert c in cols, f"tt_packages 缺少列 {c}"
    conn.close()
    os.unlink(db_path)


def test_tt_products_has_bc_id_column():
    fd, db_path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    import sqlite3
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    database._ensure_schema(conn)

    cols = {r[1] for r in conn.execute("PRAGMA table_info(tt_products)")}
    for c in ["id", "product_name", "kpi", "region", "status", "bc_id",
              "sales_person_id", "agency_ratio", "customer", "owner_id",
              "is_archived", "created_at", "updated_at"]:
        assert c in cols, f"tt_products 缺少列 {c}"
    conn.close()
    os.unlink(db_path)


def test_copy_gg_options_to_tt():
    fd, db_path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    import sqlite3
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    database._ensure_schema(conn)

    # 预置一条 gg 地区，验证迁移复制出 tt 行
    conn.execute("INSERT OR IGNORE INTO regions(name, timezone, platform) VALUES('巴西','','gg')")
    conn.commit()
    database._copy_gg_options_to_tt(conn)

    rows = conn.execute("SELECT name FROM regions WHERE platform='tt'").fetchall()
    names = {r["name"] for r in rows}
    assert "巴西" in names, "TT 地区选项未从 GG 复制"
    conn.close()
    os.unlink(db_path)
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd py && python -m pytest tests/test_tt_platform.py -v`
Expected: FAIL — `test_tt_tables_exist` 报 `缺少表 tt_bcs`（表尚未创建），`test_copy_gg_options_to_tt` 报 `AttributeError: module 'database' has no attribute '_copy_gg_options_to_tt'`

- [ ] **Step 3: 追加 TT 建表**

编辑 `py/database.py`，在 FB 表块 `conn.executescript("""...""")`（第 531-670 行）之后、`# 列迁移已移至 _ensure_columns()` 之前，追加：

```python
    # ==================== TT 平台表 ====================
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS tt_bcs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            bc_id TEXT NOT NULL UNIQUE,
            note TEXT DEFAULT '',
            status TEXT DEFAULT 'normal',
            owner_id INTEGER REFERENCES users(id),
            deleted_at TEXT DEFAULT NULL,
            created_at TEXT DEFAULT (datetime('now','localtime')),
            updated_at TEXT DEFAULT (datetime('now','localtime'))
        );
        CREATE INDEX IF NOT EXISTS idx_tt_bcs_owner ON tt_bcs(owner_id);
        CREATE INDEX IF NOT EXISTS idx_tt_bcs_status ON tt_bcs(status);

        CREATE TABLE IF NOT EXISTS tt_products (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            product_name TEXT NOT NULL,
            kpi TEXT DEFAULT '',
            region TEXT DEFAULT '',
            status TEXT DEFAULT 'active',
            bc_id INTEGER REFERENCES tt_bcs(id),
            sales_person_id INTEGER REFERENCES sales_persons(id),
            agency_ratio REAL DEFAULT 0,
            customer TEXT DEFAULT '',
            owner_id INTEGER REFERENCES users(id),
            is_archived INTEGER DEFAULT 0,
            created_at TEXT DEFAULT (datetime('now','localtime')),
            updated_at TEXT DEFAULT (datetime('now','localtime'))
        );
        CREATE INDEX IF NOT EXISTS idx_tt_products_owner ON tt_products(owner_id);
        CREATE INDEX IF NOT EXISTS idx_tt_products_region ON tt_products(region);
        CREATE INDEX IF NOT EXISTS idx_tt_products_bc ON tt_products(bc_id);

        CREATE TABLE IF NOT EXISTS tt_product_runners (
            product_id INTEGER NOT NULL REFERENCES tt_products(id) ON DELETE CASCADE,
            user_id INTEGER NOT NULL REFERENCES users(id),
            PRIMARY KEY (product_id, user_id)
        );
        CREATE INDEX IF NOT EXISTS idx_tt_product_runners_user ON tt_product_runners(user_id);

        CREATE TABLE IF NOT EXISTS tt_packages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            product_id INTEGER NOT NULL REFERENCES tt_products(id) ON DELETE CASCADE,
            type TEXT DEFAULT 'package',
            series_name TEXT DEFAULT '',
            package_name TEXT DEFAULT '',
            url TEXT DEFAULT '',
            status TEXT DEFAULT '',
            created_at TEXT DEFAULT (datetime('now','localtime')),
            updated_at TEXT DEFAULT (datetime('now','localtime'))
        );
        CREATE INDEX IF NOT EXISTS idx_tt_packages_product ON tt_packages(product_id);
        CREATE INDEX IF NOT EXISTS idx_tt_packages_type ON tt_packages(type);

        CREATE TABLE IF NOT EXISTS tt_delist_checks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            package_id INTEGER NOT NULL REFERENCES tt_packages(id) ON DELETE CASCADE,
            is_delisted INTEGER DEFAULT 0,
            checked_at TEXT DEFAULT (datetime('now','localtime')),
            UNIQUE(package_id)
        );
        CREATE INDEX IF NOT EXISTS idx_tt_delist_checks_package ON tt_delist_checks(package_id);

        CREATE TABLE IF NOT EXISTS tt_product_assets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            product_id INTEGER NOT NULL REFERENCES tt_products(id),
            video_id TEXT NOT NULL,
            video_owner_id INTEGER NOT NULL DEFAULT 1,
            added_by INTEGER REFERENCES users(id),
            added_at TEXT DEFAULT (datetime('now','localtime')),
            UNIQUE(product_id, video_id)
        );
        CREATE INDEX IF NOT EXISTS idx_tt_product_assets_product ON tt_product_assets(product_id);
        CREATE INDEX IF NOT EXISTS idx_tt_product_assets_video ON tt_product_assets(video_id);
    """)
```

- [ ] **Step 4: 新增 `_copy_gg_options_to_tt` 并挂到迁移入口**

编辑 `py/database.py`，在 `_copy_gg_options_to_fb` 函数（第 1119 行）之后、`_migrate_if_needed` 之前插入：

```python
def _copy_gg_options_to_tt(conn: sqlite3.Connection):
    """一次性迁移：将 GG 平台的选项数据复制一份到 TT 平台。

    注意：选项表（regions/sales_persons/account_statuses）已含 platform 列，
    无需重建表，只需插入 platform='tt' 数据即可。
    """
    migrated = conn.execute(
        "SELECT value FROM config WHERE key='migrated_copy_options_to_tt'"
    ).fetchone()
    if migrated:
        return

    # 复制地区
    for r in conn.execute("SELECT name, timezone FROM regions WHERE platform='gg'").fetchall():
        conn.execute(
            "INSERT OR IGNORE INTO regions(name, timezone, platform) VALUES(?,?,'tt')",
            (r["name"], r["timezone"]))

    # 复制商务
    for s in conn.execute("SELECT DISTINCT name FROM sales_persons WHERE platform='gg'").fetchall():
        conn.execute(
            "INSERT OR IGNORE INTO sales_persons(name, owner_id, platform) VALUES(?,1,'tt')",
            (s["name"],))

    # 复制状态
    for s in conn.execute("SELECT DISTINCT name FROM account_statuses WHERE platform='gg'").fetchall():
        conn.execute(
            "INSERT OR IGNORE INTO account_statuses(name, owner_id, platform) VALUES(?,1,'tt')",
            (s["name"],))

    conn.execute("INSERT OR REPLACE INTO config(key,value) VALUES('migrated_copy_options_to_tt','1')")
    conn.commit()
```

编辑 `py/database.py` 的 `_migrate_if_needed`（第 1122-1127 行），在 `_copy_gg_options_to_fb(conn)` 之后追加一行：

```python
    # 复制 GG 选项到 FB
    _copy_gg_options_to_fb(conn)
    # 复制 GG 选项到 TT
    _copy_gg_options_to_tt(conn)
```

- [ ] **Step 5: 运行测试确认通过**

Run: `cd py && python -m pytest tests/test_tt_platform.py -v`
Expected: PASS（4 passed）

- [ ] **Step 6: 提交**

```bash
git add py/database.py py/tests/test_tt_platform.py
git commit -m "feat: TT 平台建表（6 张表）+ 选项数据迁移"
```

---

## Task 2: 平台三值化（装饰器 + 用户校验 + 平台守卫 + 测试夹具）

**Files:**
- Modify: `py/routes/decorators.py:86`（末尾追加 `tt_required`）
- Modify: `py/main.py:7370`（admin_create_user 校验）、`py/main.py:7528`（admin_update_user 校验）、`py/main.py:176-184`（`_guard_gg_platform` 跳过 `/api/tt/`）
- Modify: `py/tests/conftest.py:59`（追加 `tt_headers` fixture）
- Test: `py/tests/test_tt_platform.py`（追加测试）

**Interfaces:**
- Consumes: `routes.decorators.require_platform`（现有）、`routes.helpers.err`（现有）
- Produces: 装饰器 `tt_required`；`py/tests/conftest.py` 的 `tt_headers` fixture（后续 Task 3-7 复用）

- [ ] **Step 1: 写失败的测试**

在 `py/tests/test_tt_platform.py` 末尾追加：

```python
def test_tt_required_blocks_gg_user(client, auth_headers):
    from routes.decorators import require_platform
    # auth_headers 是 gg 用户，require_platform('tt') 应返回 403 响应
    resp = require_platform('tt')
    assert resp is not None
    assert resp[1] == 403


def test_tt_required_allows_tt_user(client, tt_headers):
    from flask_jwt_extended import get_jwt_identity
    # 通过 client 请求命中一个受 tt 保护的路由（尚未实现，这里直接验证 require_platform 放行）
    # 用 monkeypatch 替换 get_jwt_identity 返回 tt 用户 id 更直接，但此处用真实 token：
    # 由于 tt_required 依赖 get_jwt_identity()，需在请求上下文中调用，故用路由集成验证放行：
    resp = client.get("/api/tt/bcs/list", headers=tt_headers)
    # 路由未实现前返回 404（说明已通过平台守卫与鉴权，未返回 403）
    assert resp.status_code != 403
```

- [ ] **Step 2: 在 conftest.py 追加 `tt_headers` fixture**

编辑 `py/tests/conftest.py`，在 `auth_headers` fixture 之后追加：

```python
@pytest.fixture
def tt_headers(client):
    """创建 TT 平台测试用户并返回带 JWT token 的请求头。"""
    client.post("/api/auth/register", json={
        "username": "ttuser", "password": "test123",
    })
    # 直接把用户平台改为 tt（register 默认 gg）
    import database
    db = database.get_db()
    db.execute("UPDATE users SET platform='tt' WHERE username='ttuser'")
    db.commit()
    db.close()
    resp = client.post("/api/auth/login", json={
        "username": "ttuser", "password": "test123",
    })
    token = resp.get_json().get("access_token", "")
    return {"Authorization": f"Bearer {token}"}
```

- [ ] **Step 3: 运行测试确认失败**

Run: `cd py && python -m pytest tests/test_tt_platform.py -v`
Expected: FAIL — `test_tt_required_blocks_gg_user` 报 `ImportError: cannot import name 'require_platform'` 之前实际是 `AttributeError: module 'routes.decorators' has no attribute 'tt_required'`；`test_tt_required_allows_tt_user` 报 403（`tt_required` 尚未定义，路由未实现）

- [ ] **Step 4: 新增 `tt_required` 装饰器**

编辑 `py/routes/decorators.py`，在 `gg_required`（第 85 行）之后追加：

```python
def tt_required(fn):
    """要求 TT 平台用户（或 developer）。"""
    @wraps(fn)
    def wrapper(*args, **kwargs):
        err_resp = require_platform('tt')
        if err_resp:
            return err_resp
        return fn(*args, **kwargs)
    return wrapper
```

- [ ] **Step 5: 放宽用户创建/更新校验 + 平台守卫**

编辑 `py/main.py` 第 7370 行，把：

```python
    if platform not in ("gg", "fb"):
        return jsonify(success=False, error="Invalid platform"), 400
```

改为：

```python
    if platform not in ("gg", "fb", "tt"):
        return jsonify(success=False, error="Invalid platform"), 400
```

编辑 `py/main.py` 第 7528 行，把：

```python
    if platform is not None and platform not in ("gg", "fb"):
        return jsonify(success=False, error="无效的平台值"), 400
```

改为：

```python
    if platform is not None and platform not in ("gg", "fb", "tt"):
        return jsonify(success=False, error="无效的平台值"), 400
```

编辑 `py/main.py` 第 175-177 行的 `_guard_gg_platform`，把：

```python
    # 跳过 FB 专用路由（由 fb_routes 的 @fb_required 守卫）
    if request.path.startswith('/api/fb/'):
        return None
```

改为：

```python
    # 跳过 FB / TT 专用路由（由各自 blueprint 的 @fb_required/@tt_required 守卫）
    if request.path.startswith('/api/fb/') or request.path.startswith('/api/tt/'):
        return None
```

- [ ] **Step 6: 运行测试确认通过**

Run: `cd py && python -m pytest tests/test_tt_platform.py -v`
Expected: PASS — `test_tt_required_blocks_gg_user` 通过；`test_tt_required_allows_tt_user` 通过（`/api/tt/bcs/list` 未实现返回 404，而非 403）

- [ ] **Step 7: 提交**

```bash
git add py/routes/decorators.py py/main.py py/tests/conftest.py py/tests/test_tt_platform.py
git commit -m "feat: 平台三值化（tt_required 装饰器 + 用户创建/更新支持 tt + 平台守卫跳过 /api/tt）"
```

---

## Task 3: tt_routes.py 骨架 + BC 管理 + 注册 Blueprint

**Files:**
- Create: `py/routes/tt_routes.py`
- Modify: `py/main.py:354`（注册 `tt_bp`）
- Test: `py/tests/test_tt_routes.py`（新建）

**Interfaces:**
- Consumes: `routes.helpers.{ok, err, get_uid, get_db, parse_body}`（现有）、`routes.decorators.tt_required`（Task 2）
- Produces: Blueprint `tt_bp`；`_get_role(db, uid)`；BC 路由 `list/create/update/delete/options`

- [ ] **Step 1: 写失败的 BC CRUD 测试**

新建 `py/tests/test_tt_routes.py`：

```python
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

    # 选项
    resp = client.get("/api/tt/bcs/options", headers=tt_headers)
    assert resp.get_json()[0]["name"] == "改名BC"

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
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd py && python -m pytest tests/test_tt_routes.py -v`
Expected: FAIL — 404（路由未实现）

- [ ] **Step 3: 创建 tt_routes.py（骨架 + BC 路由）**

新建 `py/routes/tt_routes.py`：

```python
"""TikTok 平台 API 路由 — 产品管理 / BC管理 / 投放对象 / 掉包检测 / 素材关联"""
from flask import Blueprint, request
from flask_jwt_extended import jwt_required
from .helpers import ok, err, get_uid, get_db, parse_body
from .decorators import tt_required

tt_bp = Blueprint('tt', __name__)


# ==================== BC 管理 ====================

@tt_bp.route('/api/tt/bcs/list', methods=['GET'])
@jwt_required()
@tt_required
def list_bcs():
    db = get_db()
    page = request.args.get('page', 1, type=int)
    size = request.args.get('size', 50, type=int)
    status = request.args.get('status', '')
    offset = (page - 1) * size
    uid = get_uid()

    where = ["deleted_at IS NULL"]
    params = []
    role = _get_role(db, uid)
    if role not in ('developer', 'admin'):
        where.append("owner_id = ?")
        params.append(uid)
    if status:
        where.append("status = ?")
        params.append(status)
    where_clause = " AND ".join(where)

    total = db.execute(
        f"SELECT COUNT(*) FROM tt_bcs WHERE {where_clause}", params
    ).fetchone()[0]
    rows = db.execute(
        f"SELECT * FROM tt_bcs WHERE {where_clause} ORDER BY created_at DESC LIMIT ? OFFSET ?",
        params + [size, offset]
    ).fetchall()
    return ok({'items': [dict(r) for r in rows], 'total': total, 'page': page, 'size': size})


@tt_bp.route('/api/tt/bcs/create', methods=['POST'])
@jwt_required()
@tt_required
def create_bc():
    db = get_db()
    data = parse_body()
    name = data.get('name', '').strip()
    bc_id = data.get('bc_id', '').strip()
    note = data.get('note', '').strip()

    if not name or not bc_id:
        return err('BC名称和BCID不能为空'), 400
    if not bc_id.isdigit():
        return err('BCID必须是纯数字'), 400

    uid = get_uid()
    try:
        db.execute(
            "INSERT INTO tt_bcs (name, bc_id, note, owner_id) VALUES (?, ?, ?, ?)",
            (name, bc_id, note, uid))
        db.commit()
        return ok({'id': db.execute("SELECT last_insert_rowid()").fetchone()[0]})
    except Exception as e:
        return err(str(e))


@tt_bp.route('/api/tt/bcs/<int:bid>', methods=['PUT'])
@jwt_required()
@tt_required
def update_bc(bid):
    db = get_db()
    data = parse_body()
    name = data.get('name', '').strip()
    note = data.get('note', '').strip()
    status = data.get('status')
    if name:
        db.execute(
            "UPDATE tt_bcs SET name=?, note=?, updated_at=datetime('now','localtime') WHERE id=?",
            (name, note, bid))
    if status in ('normal', 'banned'):
        db.execute(
            "UPDATE tt_bcs SET status=?, updated_at=datetime('now','localtime') WHERE id=?",
            (status, bid))
    db.commit()
    return ok()


@tt_bp.route('/api/tt/bcs/<int:bid>', methods=['DELETE'])
@jwt_required()
@tt_required
def delete_bc(bid):
    db = get_db()
    db.execute("UPDATE tt_bcs SET deleted_at=datetime('now','localtime') WHERE id=?", (bid,))
    db.commit()
    return ok()


@tt_bp.route('/api/tt/bcs/options', methods=['GET'])
@jwt_required()
@tt_required
def bc_options():
    db = get_db()
    rows = db.execute(
        "SELECT id, name, bc_id FROM tt_bcs WHERE status='normal' AND deleted_at IS NULL ORDER BY name"
    ).fetchall()
    return ok([dict(r) for r in rows])


# ==================== 工具函数 ====================

def _get_role(db, uid):
    user = db.execute("SELECT role FROM users WHERE id=?", (uid,)).fetchone()
    return user['role'] if user else 'user'
```

- [ ] **Step 4: 注册 tt_bp**

编辑 `py/main.py`，在第 353-354 行 `from routes.fb_routes import fb_bp` / `app.register_blueprint(fb_bp)` 之后追加：

```python
from routes.tt_routes import tt_bp
app.register_blueprint(tt_bp)
```

- [ ] **Step 5: 运行测试确认通过**

Run: `cd py && python -m pytest tests/test_tt_routes.py -v`
Expected: PASS（2 passed）

- [ ] **Step 6: 提交**

```bash
git add py/routes/tt_routes.py py/main.py py/tests/test_tt_routes.py
git commit -m "feat: TT BC 管理路由（list/create/update/delete/options）+ 注册 tt_bp"
```

---

## Task 4: TT 产品 CRUD

**Files:**
- Modify: `py/routes/tt_routes.py`（追加产品路由）
- Test: `py/tests/test_tt_routes.py`（追加测试）

**Interfaces:**
- Consumes: `_get_role`（Task 3）、`ok/err/get_uid/get_db/parse_body`
- Produces: 路由 `list_products` / `runner_products` / `create_product` / `update_product` / `delete_product` / `restore_product` / `product_detail`

- [ ] **Step 1: 写失败的产品 CRUD 测试**

在 `py/tests/test_tt_routes.py` 末尾追加：

```python
def _create_bc(client, tt_headers, name="BC1", bc_id="1111111111"):
    return client.post("/api/tt/bcs/create", headers=tt_headers,
                       json={"name": name, "bc_id": bc_id}).get_json()["id"]


def test_product_crud(client, tt_headers):
    bc_id = _create_bc(client, tt_headers)

    # 创建（含投放对象 + 在跑人员）
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
    # 未在任何产品担任 runner 时返回空
    resp = client.get("/api/tt/products/runner-products", headers=tt_headers)
    assert resp.get_json() == []
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd py && python -m pytest tests/test_tt_routes.py -v`
Expected: FAIL — 404（产品路由未实现）

- [ ] **Step 3: 实现产品 CRUD 路由**

在 `py/routes/tt_routes.py` 的 `_get_role` 函数之前插入产品管理路由块：

```python
# ==================== 产品管理 ====================

@tt_bp.route('/api/tt/products/list', methods=['GET'])
@jwt_required()
@tt_required
def list_products():
    db = get_db()
    page = request.args.get('page', 1, type=int)
    size = request.args.get('size', 50, type=int)
    search = request.args.get('search', '')
    status = request.args.get('status', '')
    region = request.args.get('region', '')
    runner = request.args.get('runner', '', type=str)
    archived = request.args.get('archived', '0')
    uid = get_uid()
    offset = (page - 1) * size

    where = ["p.is_archived = 1" if archived == '1' else "p.is_archived = 0"]
    params = []
    role = _get_role(db, uid)
    if runner and runner.isdigit():
        where.append("p.id IN (SELECT product_id FROM tt_product_runners WHERE user_id=?)")
        params.append(int(runner))
    elif role not in ('developer', 'admin'):
        where.append("p.id IN (SELECT product_id FROM tt_product_runners WHERE user_id=?)")
        params.append(uid)
    if search:
        where.append("p.product_name LIKE ?")
        params.append(f"%{search}%")
    if status:
        where.append("p.status = ?")
        params.append(status)
    if region:
        where.append("p.region = ?")
        params.append(region)

    where_clause = " AND ".join(where)
    total = db.execute(f"SELECT COUNT(*) FROM tt_products p WHERE {where_clause}", params).fetchone()[0]
    rows = db.execute(
        f"SELECT p.* FROM tt_products p WHERE {where_clause} ORDER BY p.created_at DESC LIMIT ? OFFSET ?",
        params + [size, offset]
    ).fetchall()

    items = []
    for r in rows:
        item = dict(r)
        if r['sales_person_id']:
            sp = db.execute("SELECT name FROM sales_persons WHERE id=?", (r['sales_person_id'],)).fetchone()
            item['sales_person_name'] = sp['name'] if sp else ''
        if r['bc_id']:
            bc = db.execute("SELECT id, name, bc_id FROM tt_bcs WHERE id=?", (r['bc_id'],)).fetchone()
            item['bc'] = dict(bc) if bc else None
        item['runners'] = [dict(u) for u in db.execute(
            "SELECT u.id, u.username, u.display_name FROM users u "
            "JOIN tt_product_runners pr ON pr.user_id = u.id WHERE pr.product_id=?", (r['id'],)
        ).fetchall()]
        item['packages'] = [dict(pk) for pk in db.execute(
            "SELECT * FROM tt_packages WHERE product_id=? ORDER BY id", (r['id'],)
        ).fetchall()]
        items.append(item)

    return ok({'items': items, 'total': total, 'page': page, 'size': size})


@tt_bp.route('/api/tt/products/runner-products', methods=['GET'])
@jwt_required()
@tt_required
def runner_products():
    """获取当前用户的在跑产品（下拉框用）。"""
    db = get_db()
    uid = get_uid()
    rows = db.execute(
        "SELECT p.id, p.product_name FROM tt_products p "
        "JOIN tt_product_runners pr ON pr.product_id = p.id "
        "WHERE pr.user_id=? AND p.is_archived=0 ORDER BY p.product_name",
        (uid,)
    ).fetchall()
    return ok([dict(r) for r in rows])


@tt_bp.route('/api/tt/products/create', methods=['POST'])
@jwt_required()
@tt_required
def create_product():
    db = get_db()
    data = parse_body()
    product_name = data.get('product_name', '').strip()
    kpi = data.get('kpi', '')
    region = data.get('region', '')
    status = data.get('status', 'active')
    bc_id = data.get('bc_id', None)
    sales_person_id = data.get('sales_person_id', None)
    agency_ratio = data.get('agency_ratio', 0)
    customer = data.get('customer', '')
    runner_ids = data.get('runner_ids', [])
    packages = data.get('packages', [])  # [{type, series_name, package_name, url}]

    if not product_name:
        return err('产品名不能为空'), 400

    uid = get_uid()
    try:
        db.execute(
            "INSERT INTO tt_products (product_name, kpi, region, status, bc_id, "
            "sales_person_id, agency_ratio, customer, owner_id) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (product_name, kpi, region, status, bc_id, sales_person_id,
             agency_ratio, customer, uid))
        pid = db.execute("SELECT last_insert_rowid()").fetchone()[0]

        for ruid in runner_ids:
            db.execute("INSERT OR IGNORE INTO tt_product_runners (product_id, user_id) VALUES (?, ?)", (pid, ruid))
        for pkg in packages:
            db.execute(
                "INSERT INTO tt_packages (product_id, type, series_name, package_name, url, status) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (pid, pkg.get('type', 'package'), pkg.get('series_name', ''),
                 pkg.get('package_name', ''), pkg.get('url', ''), pkg.get('status', '')))

        db.commit()
        return ok({'id': pid})
    except Exception as e:
        return err(str(e))


@tt_bp.route('/api/tt/products/<int:pid>', methods=['PUT'])
@jwt_required()
@tt_required
def update_product(pid):
    db = get_db()
    data = parse_body()
    fields = {
        'product_name': data.get('product_name', '').strip(),
        'kpi': data.get('kpi', ''),
        'region': data.get('region', ''),
        'status': data.get('status', 'active'),
        'bc_id': data.get('bc_id', None),
        'sales_person_id': data.get('sales_person_id', None),
        'agency_ratio': data.get('agency_ratio', 0),
        'customer': data.get('customer', ''),
    }
    runner_ids = data.get('runner_ids', None)

    if fields['product_name']:
        db.execute(
            "UPDATE tt_products SET product_name=?, kpi=?, region=?, status=?, bc_id=?, "
            "sales_person_id=?, agency_ratio=?, customer=?, updated_at=datetime('now','localtime') WHERE id=?",
            (fields['product_name'], fields['kpi'], fields['region'], fields['status'],
             fields['bc_id'], fields['sales_person_id'], fields['agency_ratio'],
             fields['customer'], pid))

    if runner_ids is not None:
        db.execute("DELETE FROM tt_product_runners WHERE product_id=?", (pid,))
        for ruid in runner_ids:
            db.execute("INSERT OR IGNORE INTO tt_product_runners (product_id, user_id) VALUES (?, ?)", (pid, ruid))

    db.commit()
    return ok()


@tt_bp.route('/api/tt/products/<int:pid>', methods=['DELETE'])
@jwt_required()
@tt_required
def delete_product(pid):
    db = get_db()
    db.execute("UPDATE tt_products SET is_archived=1, updated_at=datetime('now','localtime') WHERE id=?", (pid,))
    db.commit()
    return ok()


@tt_bp.route('/api/tt/products/<int:pid>/restore', methods=['POST'])
@jwt_required()
@tt_required
def restore_product(pid):
    db = get_db()
    db.execute("UPDATE tt_products SET is_archived=0, updated_at=datetime('now','localtime') WHERE id=?", (pid,))
    db.commit()
    return ok()


@tt_bp.route('/api/tt/products/<int:pid>/detail', methods=['GET'])
@jwt_required()
@tt_required
def product_detail(pid):
    db = get_db()
    prod = db.execute("SELECT * FROM tt_products WHERE id=?", (pid,)).fetchone()
    if not prod:
        return err('产品不存在'), 404
    item = dict(prod)
    if prod['bc_id']:
        bc = db.execute("SELECT id, name, bc_id FROM tt_bcs WHERE id=?", (prod['bc_id'],)).fetchone()
        item['bc'] = dict(bc) if bc else None
    item['runners'] = [dict(u) for u in db.execute(
        "SELECT u.id, u.username, u.display_name FROM users u "
        "JOIN tt_product_runners pr ON pr.user_id = u.id WHERE pr.product_id=?", (pid,)
    ).fetchall()]
    item['packages'] = [dict(pk) for pk in db.execute(
        "SELECT * FROM tt_packages WHERE product_id=? ORDER BY id", (pid,)
    ).fetchall()]
    return ok(item)
```

- [ ] **Step 4: 运行测试确认通过**

Run: `cd py && python -m pytest tests/test_tt_routes.py -v`
Expected: PASS（4 passed）

- [ ] **Step 5: 提交**

```bash
git add py/routes/tt_routes.py py/tests/test_tt_routes.py
git commit -m "feat: TT 产品 CRUD 路由（list/create/update/delete/restore/detail/runner-products）"
```

---

## Task 5: TT 投放对象（跑包/PWA）增删改 + 批量删除

**Files:**
- Modify: `py/routes/tt_routes.py`（追加投放对象路由）
- Test: `py/tests/test_tt_routes.py`（追加测试）

**Interfaces:**
- Consumes: `ok/err/get_db/parse_body`、`tt_required`
- Produces: 路由 `add_package` / `update_package` / `delete_package` / `batch_delete_packages`

- [ ] **Step 1: 写失败的投放对象测试**

在 `py/tests/test_tt_routes.py` 末尾追加：

```python
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
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd py && python -m pytest tests/test_tt_routes.py::test_package_crud_and_batch_delete -v`
Expected: FAIL — 404

- [ ] **Step 3: 实现投放对象路由**

在 `py/routes/tt_routes.py` 的 `_get_role` 之前插入：

```python
# ==================== 投放对象（跑包 / PWA，单表） ====================

@tt_bp.route('/api/tt/products/<int:pid>/packages', methods=['POST'])
@jwt_required()
@tt_required
def add_package(pid):
    db = get_db()
    data = parse_body()
    pkg_type = data.get('type', 'package')
    series_name = data.get('series_name', '').strip()
    package_name = data.get('package_name', '').strip()
    url = data.get('url', '').strip()
    status = data.get('status', '')

    if pkg_type not in ('package', 'pwa'):
        return err('无效的投放对象类型'), 400
    if pkg_type == 'package' and not package_name:
        return err('跑包必须填写包名'), 400

    try:
        db.execute(
            "INSERT INTO tt_packages (product_id, type, series_name, package_name, url, status) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (pid, pkg_type, series_name, package_name, url, status))
        db.commit()
        return ok({'id': db.execute("SELECT last_insert_rowid()").fetchone()[0]})
    except Exception as e:
        return err(str(e))


@tt_bp.route('/api/tt/packages/<int:pkg_id>', methods=['PUT'])
@jwt_required()
@tt_required
def update_package(pkg_id):
    db = get_db()
    data = parse_body()
    fields = {
        'series_name': data.get('series_name', '').strip(),
        'package_name': data.get('package_name', '').strip(),
        'url': data.get('url', '').strip(),
        'status': data.get('status', ''),
    }
    db.execute(
        "UPDATE tt_packages SET series_name=?, package_name=?, url=?, status=?, "
        "updated_at=datetime('now','localtime') WHERE id=?",
        (fields['series_name'], fields['package_name'], fields['url'],
         fields['status'], pkg_id))
    db.commit()
    return ok()


@tt_bp.route('/api/tt/packages/<int:pkg_id>', methods=['DELETE'])
@jwt_required()
@tt_required
def delete_package(pkg_id):
    db = get_db()
    db.execute("DELETE FROM tt_delist_checks WHERE package_id=?", (pkg_id,))
    db.execute("DELETE FROM tt_packages WHERE id=?", (pkg_id,))
    db.commit()
    return ok()


@tt_bp.route('/api/tt/packages/batch-delete', methods=['POST'])
@jwt_required()
@tt_required
def batch_delete_packages():
    db = get_db()
    data = parse_body()
    ids = data.get('ids') or []
    if not ids:
        return err('请选择要删除的投放对象'), 400
    placeholders = ",".join(["?"] * len(ids))
    db.execute(f"DELETE FROM tt_delist_checks WHERE package_id IN ({placeholders})", ids)
    db.execute(f"DELETE FROM tt_packages WHERE id IN ({placeholders})", ids)
    db.commit()
    return ok({'deleted': len(ids)})
```

- [ ] **Step 4: 运行测试确认通过**

Run: `cd py && python -m pytest tests/test_tt_routes.py::test_package_crud_and_batch_delete -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add py/routes/tt_routes.py py/tests/test_tt_routes.py
git commit -m "feat: TT 投放对象路由（跑包/PWA 增删改 + 批量删除）"
```

---

## Task 6: TT 掉包检测（复用 delist_checker）

**Files:**
- Modify: `py/routes/tt_routes.py`（追加掉包检测路由）
- Test: `py/tests/test_tt_routes.py`（追加测试，mock 网络）

**Interfaces:**
- Consumes: `delist_checker.check_product_packages(product_id, packages, proxy_pool=None)`（现有，返回 `[{package_id, product_id, is_delisted, error}]`）
- Produces: 路由 `check_delist` / `delist_status`

- [ ] **Step 1: 写失败的掉包检测测试**

在 `py/tests/test_tt_routes.py` 末尾追加：

```python
import unittest.mock as mock


def test_check_delist(client, tt_headers):
    pid = client.post("/api/tt/products/create", headers=tt_headers, json={
        "product_name": "掉包产品",
        "packages": [{"type": "package", "series_name": "S", "package_name": "com.a.b", "url": "https://play.google.com/store/apps/details?id=com.a.b"}],
    }).get_json()["id"]

    fake = [{"package_id": 1, "product_id": pid, "is_delisted": True, "error": ""}]
    with mock.patch("delist_checker.check_product_packages", return_value=fake):
        resp = client.post(f"/api/tt/products/{pid}/check-delist", headers=tt_headers)
    assert resp.status_code == 200
    assert resp.get_json()["results"][0]["is_delisted"] is True

    # 掉包状态查询
    resp = client.get("/api/tt/products/delist-status", headers=tt_headers)
    assert len(resp.get_json()["delisted_packages"]) == 1
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd py && python -m pytest tests/test_tt_routes.py::test_check_delist -v`
Expected: FAIL — 404

- [ ] **Step 3: 实现掉包检测路由**

在 `py/routes/tt_routes.py` 追加：

```python
# ==================== 掉包检测（仅跑包 type='package'） ====================

@tt_bp.route('/api/tt/products/<int:pid>/check-delist', methods=['POST'])
@jwt_required()
@tt_required
def check_delist(pid):
    import delist_checker
    db = get_db()

    pkgs = db.execute(
        "SELECT id, package_name, series_name, url FROM tt_packages "
        "WHERE product_id=? AND type='package' AND url != ''",
        (pid,)
    ).fetchall()
    if not pkgs:
        return ok({'results': [], 'message': '没有需要检测的跑包'})

    pkg_list = [dict(p) for p in pkgs]
    results = delist_checker.check_product_packages(pid, pkg_list, None)

    import datetime
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    for r in results:
        db.execute(
            "INSERT OR REPLACE INTO tt_delist_checks(package_id, is_delisted, checked_at) "
            "VALUES(?, ?, ?)",
            (r["package_id"], 1 if r["is_delisted"] else 0, now))
    db.commit()
    return ok({'results': results})


@tt_bp.route('/api/tt/products/delist-status', methods=['GET'])
@jwt_required()
@tt_required
def delist_status():
    """获取当前用户关联产品的掉包检测状态。"""
    db = get_db()
    uid = get_uid()
    rows = db.execute(
        "SELECT dc.package_id, dc.is_delisted, dc.checked_at, "
        "pkg.series_name, pkg.package_name, pkg.url, pkg.status AS pkg_status, "
        "prod.product_name "
        "FROM tt_delist_checks dc "
        "JOIN tt_packages pkg ON dc.package_id = pkg.id "
        "JOIN tt_products prod ON pkg.product_id = prod.id "
        "WHERE dc.is_delisted = 1 AND prod.is_archived = 0 "
        "AND pkg.product_id IN (SELECT product_id FROM tt_product_runners WHERE user_id=?) "
        "ORDER BY dc.checked_at DESC",
        (uid,)
    ).fetchall()
    delisted = [dict(r) for r in rows]
    return ok({'delisted_packages': delisted})
```

- [ ] **Step 4: 运行测试确认通过**

Run: `cd py && python -m pytest tests/test_tt_routes.py::test_check_delist -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add py/routes/tt_routes.py py/tests/test_tt_routes.py
git commit -m "feat: TT 掉包检测路由（check-delist / delist-status，复用 delist_checker）"
```

---

## Task 7: TT 高级功能（合并 + 粘贴解析 + 素材关联 + 用户查询）

**Files:**
- Modify: `py/routes/tt_routes.py`（追加高级功能路由 + 解析辅助函数）
- Test: `py/tests/test_tt_routes.py`（追加测试）

**Interfaces:**
- Consumes: `ok/err/get_db/parse_body/get_uid`、`tt_required`、`re`（标准库）
- Produces: 路由 `products_merge` / `import_text` / `list_assets` / `add_assets` / `delete_asset` / `list_tt_users`；辅助函数 `_extract_pkg_from_url` / `_guess_series`

> 范围说明：素材关联第一阶段采用「从共享视频库选择已有视频建立关联」（`add_assets` 接收 `video_ids` 数组），不做「导入新视频」。导入式素材后续阶段补。这与设计文档「素材关联复用共享视频库」一致。

- [ ] **Step 1: 写失败的高级功能测试**

在 `py/tests/test_tt_routes.py` 末尾追加：

```python
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
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd py && python -m pytest tests/test_tt_routes.py::test_import_text_parse tests/test_tt_routes.py::test_merge_products tests/test_tt_routes.py::test_list_tt_users -v`
Expected: FAIL — 404

- [ ] **Step 3: 实现高级功能路由 + 解析辅助函数**

在 `py/routes/tt_routes.py` 的 `_get_role` 之前插入：

```python
# ==================== 合并 / 粘贴解析 / 素材 / 用户 ====================

@tt_bp.route('/api/tt/products/merge', methods=['POST'])
@jwt_required()
@tt_required
def products_merge():
    """合并多个产品到主产品（迁移投放对象 + 在跑人员，删除副产品）。"""
    db = get_db()
    data = parse_body()
    master_id = data.get("master_id")
    merge_ids = data.get("merge_ids") or []

    if not master_id or not merge_ids:
        return err('请指定主产品和被合并产品'), 400
    if master_id in merge_ids:
        return err('主产品不能在被合并列表中'), 400

    master = db.execute("SELECT id FROM tt_products WHERE id=?", (master_id,)).fetchone()
    if not master:
        return err('主产品不存在'), 404

    db.execute("PRAGMA foreign_keys=OFF")
    merged_packages = 0
    for mid in merge_ids:
        sub = db.execute("SELECT * FROM tt_products WHERE id=?", (mid,)).fetchone()
        if not sub:
            continue

        # 迁移投放对象
        for p in db.execute("SELECT * FROM tt_packages WHERE product_id=?", (mid,)).fetchall():
            existing = db.execute(
                "SELECT id FROM tt_packages WHERE product_id=? AND package_name=? AND url=?",
                (master_id, p["package_name"], p["url"])
            ).fetchone()
            if not existing:
                db.execute(
                    "INSERT INTO tt_packages (product_id, type, series_name, package_name, url, status) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (master_id, p["type"], p["series_name"], p["package_name"], p["url"], p["status"]))
                merged_packages += 1

        # 迁移在跑人员
        for pr in db.execute("SELECT user_id FROM tt_product_runners WHERE product_id=?", (mid,)).fetchall():
            db.execute("INSERT OR IGNORE INTO tt_product_runners (product_id, user_id) VALUES (?, ?)",
                       (master_id, pr["user_id"]))

        # 清理并删除副产品
        db.execute("DELETE FROM tt_product_assets WHERE product_id=?", (mid,))
        db.execute("DELETE FROM tt_packages WHERE product_id=?", (mid,))
        db.execute("DELETE FROM tt_product_runners WHERE product_id=?", (mid,))
        db.execute("DELETE FROM tt_products WHERE id=?", (mid,))

    db.execute("PRAGMA foreign_keys=ON")
    db.commit()
    return ok({'merged_packages': merged_packages, 'merged_products': len(merge_ids)})


@tt_bp.route('/api/tt/products/import-text', methods=['POST'])
@jwt_required()
@tt_required
def import_text():
    """粘贴文本解析成投放对象列表（第一阶段仅跑包 Google Play 链接）。"""
    data = parse_body()
    text = (data.get("text") or "").strip()
    prefix = (data.get("prefix") or "").strip()
    suffix = (data.get("suffix") or "").strip()
    if not text:
        return err('未提供文本内容'), 400

    links = re.findall(r'https?://play\.google\.com/store/apps/details\?id=[\w.&=/\-?%]+', text)
    results = []
    for link in links:
        pkg = _extract_pkg_from_url(link)
        series = _guess_series(text, link)
        if prefix:
            if not series.startswith(prefix):
                prefix_base = prefix.split("-")[0]
                series_base = series.split("-")[0] if "-" in series else series
                if prefix_base == series_base:
                    rest = series[len(series_base):].lstrip("-")
                    sep = "" if prefix.endswith("-") else "-"
                    series = prefix + sep + rest if rest else prefix
                else:
                    sep = "" if prefix.endswith("-") else "-"
                    series = prefix + sep + series
        if suffix:
            if not series.endswith("-" + suffix) and series != suffix:
                series = series + "-" + suffix
        results.append({"type": "package", "series_name": series, "package_name": pkg, "url": link})
    return ok({'parsed': results})


def _extract_pkg_from_url(url):
    m = re.search(r'[?&]id=([\w.]+)', url)
    return m.group(1) if m else ""


def _guess_series(text, link):
    """从文本猜测链接对应的系列名（与 GG 逻辑一致）。"""
    lines = text.split("\n")
    link_idx = -1
    for i, line in enumerate(lines):
        if link in line:
            link_idx = i
            break
    if link_idx < 0:
        return _extract_pkg_from_url(link)
    for j in range(max(0, link_idx - 8), link_idx):
        l = lines[j].strip()
        if "神包上线" in l:
            name = l.split("神包上线：")[-1].split("神包上线")[-1].strip()
            if name:
                return name
    for j in range(max(0, link_idx - 2), min(len(lines), link_idx + 5)):
        l = lines[j].strip()
        for prefix in ["广告命名：", "广告命名:", "渠道命名：", "渠道命名:"]:
            if prefix in l:
                name = l.split(prefix)[-1].strip()
                if name:
                    return name
    for j in range(link_idx, max(-1, link_idx - 10), -1):
        l = lines[j].strip()
        if "神包上线" in l:
            continue
        if ("APK" in l or ("包" in l and re.search(r'包\d+', l))) and "-" in l:
            for token in l.split():
                token = re.sub(r'^[^\w]*', '', token)
                if '-' in token and len(token) > 2:
                    return token
    for j in range(link_idx + 1, min(len(lines), link_idx + 6)):
        l = lines[j].strip()
        if "应用名：" in l or "应用名:" in l:
            name = l.split("应用名：")[-1].split("应用名:")[-1].strip()
            if name:
                return name
    for j in range(max(0, link_idx - 3), min(len(lines), link_idx)):
        l = lines[j].strip()
        if "名称：" in l or "名称:" in l:
            name = l.split("名称：")[-1].split("名称:")[-1].strip()
            if name:
                return name
    for j in range(link_idx, max(-1, link_idx - 3), -1):
        l = lines[j].strip()
        tokens = l.split()
        if tokens:
            first = re.sub(r'^[^\w]*', '', tokens[0])
            if '-' in first and len(first) > 2:
                return first
    return _extract_pkg_from_url(link)


# ==================== 素材关联（共享视频库） ====================

@tt_bp.route('/api/tt/products/<int:pid>/assets', methods=['GET'])
@jwt_required()
@tt_required
def list_assets(pid):
    db = get_db()
    rows = db.execute("""
        SELECT v.*, pa.added_by, pa.added_at, u.display_name AS added_by_name
        FROM tt_product_assets pa
        JOIN videos v ON pa.video_id = v.id AND pa.video_owner_id = v.owner_id
        LEFT JOIN users u ON pa.added_by = u.id
        WHERE pa.product_id = ?
        ORDER BY pa.added_at DESC
    """, (pid,)).fetchall()
    return ok({'assets': [dict(r) for r in rows]})


@tt_bp.route('/api/tt/products/<int:pid>/assets', methods=['POST'])
@jwt_required()
@tt_required
def add_assets(pid):
    """从共享视频库选择已有视频建立关联。body: { video_ids: [...] }。"""
    db = get_db()
    data = parse_body()
    video_ids = data.get('video_ids') or []
    if not video_ids:
        return err('请选择至少一个视频'), 400
    uid = get_uid()

    prod = db.execute("SELECT id FROM tt_products WHERE id=?", (pid,)).fetchone()
    if not prod:
        return err('产品不存在'), 404

    added = 0
    for vid in video_ids:
        existing = db.execute(
            "SELECT id FROM tt_product_assets WHERE product_id=? AND video_id=?", (pid, vid)
        ).fetchone()
        if not existing:
            db.execute(
                "INSERT INTO tt_product_assets(product_id, video_id, video_owner_id, added_by) "
                "VALUES(?,?,?,?)", (pid, vid, uid, uid))
            added += 1
    db.commit()
    return ok({'added': added})


@tt_bp.route('/api/tt/products/<int:pid>/assets/<video_id>', methods=['DELETE'])
@jwt_required()
@tt_required
def delete_asset(pid, video_id):
    db = get_db()
    db.execute("DELETE FROM tt_product_assets WHERE product_id=? AND video_id=?", (pid, video_id))
    db.commit()
    return ok()


# ==================== 用户查询（TT 平台） ====================

@tt_bp.route('/api/tt/users', methods=['GET'])
@jwt_required()
@tt_required
def list_tt_users():
    """返回 TT 平台用户列表（供「在跑人员」选择器使用）。"""
    db = get_db()
    rows = db.execute(
        "SELECT id, username, display_name, platform FROM users "
        "WHERE (platform = 'tt' OR role = 'developer') AND role != 'hidden' "
        "ORDER BY display_name, username"
    ).fetchall()
    return ok({"users": [dict(r) for r in rows]})
```

同时在文件顶部 `import re`。编辑 `py/routes/tt_routes.py` 顶部导入区，把：

```python
from flask import Blueprint, request
from flask_jwt_extended import jwt_required
from .helpers import ok, err, get_uid, get_db, parse_body
from .decorators import tt_required
```

改为：

```python
import re

from flask import Blueprint, request
from flask_jwt_extended import jwt_required
from .helpers import ok, err, get_uid, get_db, parse_body
from .decorators import tt_required
```

- [ ] **Step 4: 运行测试确认通过**

Run: `cd py && python -m pytest tests/test_tt_routes.py -v`
Expected: PASS（全部通过）

- [ ] **Step 5: 提交**

```bash
git add py/routes/tt_routes.py py/tests/test_tt_routes.py
git commit -m "feat: TT 高级功能（合并/粘贴解析/素材关联/用户查询）"
```

---

## Task 8: 前端平台三值化 + API 模块 + 路由

**Files:**
- Create: `frontend/src/api/tt.js`
- Modify: `frontend/src/stores/auth.js:16-21`、`frontend/src/router/index.js:16-23,85-126,144-145`、`frontend/src/components/AppSidebar.vue:4,12-15,60-70,83-101,154`、`frontend/src/views/UserManageView.vue:8-12,37-41,98-126`

**Interfaces:**
- Consumes: `client`（现有 axios 实例，baseURL `/api`）
- Produces: `ttApi` 对象；`auth.isTtUser` getter；`/tt/products` `/tt/bcs` 路由；侧边栏 TT 菜单与平台切换；用户管理 TT 选项

**验证方式：** 前端无测试框架，用 `npm run build` 校验编译通过 + 手动浏览器验证。

- [ ] **Step 1: 创建 `frontend/src/api/tt.js`**

```js
/** TT 平台 API 调用模块 */
import client from './client'

export const ttApi = {
  // BC 管理
  listBcs(params = {}) { return client.get('/tt/bcs/list', { params }) },
  createBc(data) { return client.post('/tt/bcs/create', data) },
  updateBc(id, data) { return client.put(`/tt/bcs/${id}`, data) },
  deleteBc(id) { return client.delete(`/tt/bcs/${id}`) },
  bcOptions() { return client.get('/tt/bcs/options') },

  // 产品管理
  listProducts(params = {}) { return client.get('/tt/products/list', { params }) },
  runnerProducts() { return client.get('/tt/products/runner-products') },
  createProduct(data) { return client.post('/tt/products/create', data) },
  updateProduct(id, data) { return client.put(`/tt/products/${id}`, data) },
  deleteProduct(id) { return client.delete(`/tt/products/${id}`) },
  restoreProduct(id) { return client.post(`/tt/products/${id}/restore`) },
  productDetail(id) { return client.get(`/tt/products/${id}/detail`) },
  mergeProducts(data) { return client.post('/tt/products/merge', data) },

  // 投放对象
  addPackage(productId, data) { return client.post(`/tt/products/${productId}/packages`, data) },
  updatePackage(id, data) { return client.put(`/tt/packages/${id}`, data) },
  deletePackage(id) { return client.delete(`/tt/packages/${id}`) },
  batchDeletePackages(ids) { return client.post('/tt/packages/batch-delete', { ids }) },

  // 掉包检测
  checkDelist(productId) { return client.post(`/tt/products/${productId}/check-delist`) },
  delistStatus() { return client.get('/tt/products/delist-status') },

  // 粘贴解析
  importText(data) { return client.post('/tt/products/import-text', data) },

  // 素材
  listAssets(productId) { return client.get(`/tt/products/${productId}/assets`) },
  addAssets(productId, data) { return client.post(`/tt/products/${productId}/assets`, data) },
  deleteAsset(productId, videoId) { return client.delete(`/tt/products/${productId}/assets/${videoId}`) },

  // 用户
  listTtUsers() { return client.get('/tt/users') },
}
```

- [ ] **Step 2: 修改 `stores/auth.js`**

把 getter（第 16-18 行）：

```js
    isFbUser: (state) => state.currentPlatform === 'fb',
    isGgUser: (state) => state.currentPlatform === 'gg',
```

改为：

```js
    isFbUser: (state) => state.currentPlatform === 'fb',
    isGgUser: (state) => state.currentPlatform === 'gg',
    isTtUser: (state) => state.currentPlatform === 'tt',
```

- [ ] **Step 3: 修改 `router/index.js`**

首页重定向（第 21 行），把：

```js
      return user.platform === 'fb' ? '/fb/products' : '/accounts/products'
```

改为：

```js
      if (user.platform === 'fb') return '/fb/products'
      if (user.platform === 'tt') return '/tt/products'
      return '/accounts/products'
```

在 FB 路由块之后（第 125 行 `]` 之前）追加 TT 路由：

```js
  // ==================== TT 平台路由 ====================
  {
    path: '/tt',
    redirect: '/tt/products',
    meta: { platform: 'tt' }
  },
  {
    path: '/tt/products',
    component: () => import('../views/tt/TtProductPanel.vue'),
    meta: { platform: 'tt', title: 'TT产品管理' }
  },
  {
    path: '/tt/bcs',
    component: () => import('../views/tt/TtBcPanel.vue'),
    meta: { platform: 'tt', title: 'BC管理' }
  },
```

平台守卫的首页跳转（第 144-145 行），把：

```js
  const userPlatform = auth.user?.platform || 'gg'
  const platformHome = userPlatform === 'fb' ? '/fb/products' : '/accounts/products'
```

改为：

```js
  const userPlatform = auth.user?.platform || 'gg'
  const platformHome = userPlatform === 'fb' ? '/fb/products'
    : userPlatform === 'tt' ? '/tt/products'
    : '/accounts/products'
```

- [ ] **Step 4: 修改 `AppSidebar.vue`**

品牌按钮首页跳转（第 4 行），把：

```html
        <div class="rail-brand" @click="selectTab(auth.effectivePlatform === 'fb' ? '/fb/products' : '/accounts')" title="首页">
```

改为：

```html
        <div class="rail-brand" @click="selectTab(auth.effectivePlatform === 'fb' ? '/fb/products' : auth.effectivePlatform === 'tt' ? '/tt/products' : '/accounts')" title="首页">
```

平台切换按钮（第 12-15 行），在 FB 按钮后追加 TT 按钮：

```html
      <div v-if="auth.isDeveloper" class="platform-switch">
        <button class="plat-btn" :class="{ active: auth.currentPlatform === 'gg' }" @click="switchPlatform('gg')">GG</button>
        <button class="plat-btn" :class="{ active: auth.currentPlatform === 'fb' }" @click="switchPlatform('fb')">FB</button>
        <button class="plat-btn" :class="{ active: auth.currentPlatform === 'tt' }" @click="switchPlatform('tt')">TT</button>
      </div>
```

`switchPlatform` 函数（第 60-70 行），把：

```js
function switchPlatform(platform) {
  auth.setPlatform(platform)
  // 跳转到该平台的默认页面
  if (platform === 'fb') {
    router.push('/fb/products')
    activeSection.value = 'fb-accounts'
  } else {
    router.push('/accounts/products')
    activeSection.value = 'accounts'
  }
}
```

改为：

```js
function switchPlatform(platform) {
  auth.setPlatform(platform)
  // 跳转到该平台的默认页面
  if (platform === 'fb') {
    router.push('/fb/products')
    activeSection.value = 'fb-accounts'
  } else if (platform === 'tt') {
    router.push('/tt/products')
    activeSection.value = 'tt-accounts'
  } else {
    router.push('/accounts/products')
    activeSection.value = 'accounts'
  }
}
```

在 `fbNavItems` 之后追加 `ttNavItems`（第 99 行 `]` 之后）：

```js
const ttNavItems = [
  { key: 'tt-accounts', icon: '🏢', label: '产品管理', sections: [
    { title: '产品', items: [
      { icon:'📦',label:'产品管理',path:'/tt/products'},
      { icon:'🏢',label:'BC管理',path:'/tt/bcs'},
    ]},
  ]},
  { key: 'analysis', icon: '📈', label: '数据分析', sections: [{ title: '分析', items: [{ icon:'📊',label:'数据看板',path:'/analysis'}]}]},
  { key: 'admin', icon: '🏴', label: '管理', admin: true, sections: [{ title: '管理', items: [{ icon:'👥',label:'用户管理',path:'/admin/users'},{ icon:'⏰',label:'定时任务',path:'/admin/scheduler',developer:true }] }]},
]
```

`currentNavItems`（第 101 行），把：

```js
const currentNavItems = computed(() => auth.effectivePlatform === 'fb' ? fbNavItems : ggNavItems)
```

改为：

```js
const currentNavItems = computed(() =>
  auth.effectivePlatform === 'fb' ? fbNavItems
  : auth.effectivePlatform === 'tt' ? ttNavItems
  : ggNavItems)
```

`visibleNavItems`（第 103-107 行）的账户键判断，把 `n.key === 'accounts' || n.key === 'fb-accounts'` 改为同时覆盖 `tt-accounts`：

```js
const visibleNavItems = computed(() => currentNavItems.value.filter(n => {
  if (n.key === 'accounts' || n.key === 'fb-accounts' || n.key === 'tt-accounts') return auth.canAccessProducts
  if (n.admin) return auth.isAdmin
  return true
}))
```

路由监听（第 154 行），把：

```js
  if (p.startsWith('/accounts/settings') || p.startsWith('/fb/settings')) activeSection.value = 'settings'
```

改为：

```js
  if (p.startsWith('/accounts/settings') || p.startsWith('/fb/settings') || p.startsWith('/tt/settings')) activeSection.value = 'settings'
```

- [ ] **Step 5: 修改 `UserManageView.vue`**

平台 Tab（第 11-12 行），追加 TT：

```html
      <el-tab-pane label="GG" name="gg" />
      <el-tab-pane label="FB" name="fb" />
      <el-tab-pane label="TT" name="tt" />
```

平台标签渲染（第 39-41 行），把：

```html
            <el-tag :type="row.platform === 'fb' ? 'primary' : 'success'" size="small">
              {{ row.platform === 'fb' ? 'FB' : 'GG' }}
            </el-tag>
```

改为：

```html
            <el-tag :type="row.platform === 'fb' ? 'primary' : row.platform === 'tt' ? 'warning' : 'success'" size="small">
              {{ row.platform === 'fb' ? 'FB' : row.platform === 'tt' ? 'TT' : 'GG' }}
            </el-tag>
```

创建表单平台下拉（第 99-102 行），追加 TT 选项：

```html
          <el-select v-model="createForm.platform" style="width:100%">
            <el-option label="GG (Google Ads)" value="gg" />
            <el-option label="FB (Facebook)" value="fb" />
            <el-option label="TT (TikTok)" value="tt" />
          </el-select>
```

编辑表单平台下拉（第 123-127 行），追加 TT 选项：

```html
          <el-select v-model="editForm.platform" style="width:100%">
            <el-option label="GG (Google Ads)" value="gg" />
            <el-option label="FB (Facebook)" value="fb" />
            <el-option label="TT (TikTok)" value="tt" />
          </el-select>
```

- [ ] **Step 6: 校验编译**

Run: `cd frontend && npm run build`
Expected: 编译成功（无报错）。路由懒加载的 `../views/tt/TtProductPanel.vue` / `../views/tt/TtBcPanel.vue` 此时尚未创建，构建会失败——因此**此步骤在 Task 9/10 完成后统一执行**。本步骤先提交 API/路由/平台三值化改动，构建校验推迟到 Task 10 末尾。

- [ ] **Step 7: 提交**

```bash
git add frontend/src/api/tt.js frontend/src/stores/auth.js frontend/src/router/index.js frontend/src/components/AppSidebar.vue frontend/src/views/UserManageView.vue
git commit -m "feat: 前端平台三值化（TT 路由/侧边栏/用户管理）+ tt API 模块"
```

---

## Task 9: TtBcPanel.vue（BC 管理页）

**Files:**
- Create: `frontend/src/views/tt/TtBcPanel.vue`

**Interfaces:**
- Consumes: `ttApi`（Task 8）、`useAuthStore`、`client`（选项加载）
- Produces: BC 管理页（列表 + 新增/编辑/删除弹窗）

**验证方式：** `npm run build` + 手动浏览器验证。

- [ ] **Step 1: 创建 `frontend/src/views/tt/TtBcPanel.vue`**

```vue
<template>
  <div class="page-wrapper">
    <div class="page-header">
      <h1 class="page-title">BC 管理</h1>
      <el-button type="primary" @click="openCreate">新增 BC</el-button>
    </div>

    <div class="filter-card">
      <el-input v-model="search" placeholder="搜索 BC 名称或 BCID..." @input="onSearch" clearable size="small" style="width:220px" />
      <el-select v-model="filterStatus" placeholder="全部状态" clearable size="small" style="width:140px" @change="loadData">
        <el-option label="正常" value="normal" />
        <el-option label="封禁" value="banned" />
      </el-select>
      <span class="total-badge">共 {{ total }} 个</span>
    </div>

    <el-table :data="items" border size="small" v-loading="loading" :header-cell-style="{ background:'#f8f9fa', color:'#374151', fontWeight:600 }">
      <el-table-column prop="name" label="名称" min-width="160" />
      <el-table-column prop="bc_id" label="BCID" min-width="140" />
      <el-table-column prop="note" label="备注" min-width="180">
        <template #default="{ row }">{{ row.note || '-' }}</template>
      </el-table-column>
      <el-table-column label="状态" width="90">
        <template #default="{ row }">
          <el-tag :type="row.status === 'banned' ? 'danger' : 'success'" size="small">
            {{ row.status === 'banned' ? '封禁' : '正常' }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column label="操作" width="180" align="center">
        <template #default="{ row }">
          <el-button size="small" @click="openEdit(row)">编辑</el-button>
          <el-button v-if="row.status !== 'banned'" size="small" type="warning" @click="toggleBan(row)">封禁</el-button>
          <el-popconfirm title="确定删除？" @confirm="handleDelete(row.id)">
            <template #reference><el-button size="small" type="danger">删除</el-button></template>
          </el-popconfirm>
        </template>
      </el-table-column>
    </el-table>

    <div v-if="total>size" class="pagination-row">
      <el-pagination v-model:current-page="page" :page-size="size" :total="total" background
        layout="prev,pager,next" size="small" :pager-count="7" @current-change="loadData" />
    </div>

    <el-dialog v-model="dialogVisible" :title="editingId?'编辑 BC':'新增 BC'" width="480px">
      <el-form :model="form" label-width="80px">
        <el-form-item label="名称" required><el-input v-model="form.name" /></el-form-item>
        <el-form-item label="BCID" required><el-input v-model="form.bc_id" /></el-form-item>
        <el-form-item label="备注"><el-input v-model="form.note" type="textarea" :rows="2" /></el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible=false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="handleSave">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, reactive, onMounted } from 'vue'
import { ttApi } from '../../api/tt'
import { ElMessage } from 'element-plus'

const items = ref([]); const loading = ref(false)
const page = ref(1); const size = ref(20); const total = ref(0)
const search = ref(''); const filterStatus = ref('')
const dialogVisible = ref(false); const editingId = ref(null); const saving = ref(false)
const form = reactive({ name: '', bc_id: '', note: '' })

let searchTimer = null
function onSearch() { clearTimeout(searchTimer); searchTimer = setTimeout(loadData, 300) }

async function loadData() {
  loading.value = true
  try {
    const p = { page: page.value, size: size.value }
    if (search.value) p.search = search.value
    if (filterStatus.value) p.status = filterStatus.value
    const res = await ttApi.listBcs(p)
    items.value = res.items || []; total.value = res.total || 0
  } finally { loading.value = false }
}

function openCreate() {
  editingId.value = null
  Object.assign(form, { name: '', bc_id: '', note: '' })
  dialogVisible.value = true
}
function openEdit(row) {
  editingId.value = row.id
  Object.assign(form, { name: row.name, bc_id: row.bc_id, note: row.note || '' })
  dialogVisible.value = true
}

async function handleSave() {
  if (!form.name) return ElMessage.warning('请输入名称')
  if (!form.bc_id) return ElMessage.warning('请输入 BCID')
  saving.value = true
  try {
    editingId.value ? await ttApi.updateBc(editingId.value, { name: form.name, note: form.note })
      : await ttApi.createBc({ name: form.name, bc_id: form.bc_id, note: form.note })
    ElMessage.success(editingId.value ? '已更新' : '已创建')
    dialogVisible.value = false; loadData()
  } catch (e) { ElMessage.error(e.response?.data?.error || '保存失败') }
  finally { saving.value = false }
}

async function toggleBan(row) {
  await ttApi.updateBc(row.id, { status: 'banned' })
  ElMessage.success('已封禁'); loadData()
}
function handleDelete(id) { ttApi.deleteBc(id).then(() => { ElMessage.success('已删除'); loadData() }) }

onMounted(loadData)
</script>

<style scoped>
.page-wrapper { background:#f5f6f8;padding:24px;min-height:100%;display:flex;flex-direction:column;gap:16px; }
.page-header { display:flex;justify-content:space-between;align-items:center; }
.page-title { margin:0;font-size:20px;font-weight:700;color:#1f2937; }
.filter-card { background:#f8f9fa;border-radius:12px;padding:14px 16px;display:flex;align-items:center;gap:12px;flex-wrap:wrap;border:1px solid #e5e7eb; }
.total-badge { font-size:13px;color:#6b7280;font-weight:500;white-space:nowrap;padding:4px 10px;background:#fff;border-radius:6px;border:1px solid #e5e7eb; }
.pagination-row { display:flex;justify-content:center;gap:8px;margin-top:16px; }
</style>
```

- [ ] **Step 2: 提交**

```bash
git add frontend/src/views/tt/TtBcPanel.vue
git commit -m "feat: TT BC 管理页（TtBcPanel.vue）"
```

---

## Task 10: TtProductPanel.vue（产品管理页）

**Files:**
- Create: `frontend/src/views/tt/TtProductPanel.vue`

**Interfaces:**
- Consumes: `ttApi`（Task 8）、`useAuthStore`、`copyToClipboard`、`client`（选项加载）
- Produces: 产品管理页（产品列表 + 弹窗含投放对象子表/在跑人员/BC + 掉包检测）

**验证方式：** `npm run build` + 手动浏览器验证。

- [ ] **Step 1: 创建 `frontend/src/views/tt/TtProductPanel.vue`**

```vue
<template>
  <div class="page-wrapper">
    <div class="page-header">
      <h1 class="page-title">TT 产品管理</h1>
      <el-button type="primary" @click="openCreate">新增产品</el-button>
    </div>

    <div class="filter-card">
      <el-input v-model="search" placeholder="搜索产品..." @input="onSearch" clearable size="small" style="flex:1;min-width:160px" />
      <el-select v-model="filterRegion" placeholder="全部地区" clearable size="small" style="width:120px" @change="loadData">
        <el-option v-for="r in regionOptions" :key="r.name" :label="r.name" :value="r.name" />
      </el-select>
      <el-select v-model="filterRunner" placeholder="筛选在跑人" clearable filterable size="small" style="width:160px" @change="loadData">
        <el-option v-for="u in ttUsers" :key="u.id" :label="(u.display_name||u.username)+' ('+u.username+')'" :value="u.id" />
      </el-select>
      <el-radio-group v-model="filterStatus" size="small" @change="loadData">
        <el-radio-button value="">正常</el-radio-button>
        <el-radio-button value="paused">已暂停</el-radio-button>
      </el-radio-group>
      <el-radio-group v-model="filterArchived" size="small" @change="loadData">
        <el-radio-button value="">在用</el-radio-button>
        <el-radio-button value="1">已归档</el-radio-button>
      </el-radio-group>
      <span class="total-badge">共 {{ total }} 个</span>
    </div>

    <div class="product-list">
      <el-card v-for="item in items" :key="item.id" class="product-card"
        :class="{ 'is-paused': item.status === 'paused' }" :body-style="{ padding: 0 }">
        <div class="product-card-inner">
          <div class="product-card-header" @click="toggleExpand(item.id)">
            <div class="product-card-info">
              <div class="product-card-tags">
                <span class="status-dot" :class="item.status === 'paused' ? 'dot-paused' : 'dot-active'"></span>
                <strong class="product-name">{{ item.product_name }}</strong>
                <el-tag v-if="item.sales_person_name" size="small" class="tag-sales">{{ item.sales_person_name }}</el-tag>
                <el-tag v-if="item.kpi" size="small" class="tag-kpi">{{ item.kpi }}</el-tag>
                <el-tag v-if="item.region" size="small" class="tag-region">{{ item.region }}</el-tag>
                <el-tag v-if="item.customer" size="small" class="tag-customer">{{ item.customer }}</el-tag>
              </div>
              <div v-if="item.bc" class="product-card-bc">
                <el-tag size="small" type="info">BC: {{ item.bc.name }}</el-tag>
              </div>
              <div v-if="item.runners && item.runners.length" class="product-card-runners">
                在跑: {{ item.runners.map(r => r.display_name||r.username).join('、') }}
              </div>
              <div class="product-card-lines">
                投放对象: {{ (item.packages||[]).length }} 个
                <span class="expand-hint">展开</span>
              </div>
            </div>
            <div class="product-card-actions" @click.stop>
              <template v-if="filterArchived==='1'">
                <el-popconfirm title="确定恢复？" @confirm="handleRestore(item.id)">
                  <template #reference><el-button size="small" type="success">恢复</el-button></template>
                </el-popconfirm>
              </template>
              <template v-else>
                <el-button size="small" @click="openEdit(item)">编辑</el-button>
                <el-button size="small" @click="handleCheckDelist(item)" :loading="checkingId===item.id">掉包检测</el-button>
                <el-popconfirm title="确定删除？" @confirm="handleDelete(item.id)">
                  <template #reference><el-button size="small" type="danger">删除</el-button></template>
                </el-popconfirm>
              </template>
            </div>
          </div>

          <div v-if="expanded[item.id]" class="product-card-expand" @click.stop>
            <el-table v-if="(item.packages||[]).length" :data="item.packages" border size="small" class="pkg-table"
              :header-cell-style="{ background:'#f8f9fa', color:'#374151', fontWeight:600 }">
              <el-table-column label="类型" width="80">
                <template #default="{ row: pk }">
                  <el-tag :type="pk.type === 'pwa' ? 'warning' : 'primary'" size="small">{{ pk.type === 'pwa' ? 'PWA' : '跑包' }}</el-tag>
                </template>
              </el-table-column>
              <el-table-column prop="series_name" label="系列名" min-width="120" />
              <el-table-column label="包名" min-width="140">
                <template #default="{ row: pk }"><span class="copy-link" @click="copy(pk.package_name)">{{ pk.package_name || '-' }}</span></template>
              </el-table-column>
              <el-table-column label="链接" min-width="220">
                <template #default="{ row: pk }"><span v-if="pk.url" class="copy-link" @click="copy(pk.url)">{{ pk.url }}</span><span v-else class="no-data">-</span></template>
              </el-table-column>
              <el-table-column prop="status" label="状态" width="90">
                <template #default="{ row: pk }">{{ pk.status || '-' }}</template>
              </el-table-column>
            </el-table>
            <div v-else class="no-lines">无投放对象</div>
          </div>
        </div>
      </el-card>

      <el-empty v-if="!items.length" description="暂无产品" />

      <div v-if="total>size" class="pagination-row">
        <el-pagination v-model:current-page="page" :page-size="size" :total="total" background
          layout="prev,pager,next" size="small" :pager-count="7" @current-change="loadData" />
      </div>
    </div>

    <el-dialog v-model="dialogVisible" :title="editingId?'编辑产品':'新增产品'" width="760px" top="3vh">
      <el-form :model="form" label-width="80px">
        <el-row :gutter="16">
          <el-col :span="12"><el-form-item label="产品名" required><el-input v-model="form.product_name" /></el-form-item></el-col>
          <el-col :span="12"><el-form-item label="KPI"><el-input v-model="form.kpi" /></el-form-item></el-col>
        </el-row>
        <el-row :gutter="16">
          <el-col :span="12">
            <el-form-item label="地区">
              <el-select v-model="form.region" clearable filterable allow-create style="width:100%">
                <el-option v-for="r in regionOptions" :key="r.name" :label="r.name" :value="r.name" />
              </el-select>
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="商务">
              <el-select v-model="form.sales_person_id" clearable filterable allow-create style="width:100%">
                <el-option v-for="s in salesOptions" :key="s.id" :label="s.name" :value="s.id" />
              </el-select>
            </el-form-item>
          </el-col>
        </el-row>
        <el-row :gutter="16">
          <el-col :span="12">
            <el-form-item label="BC">
              <el-select v-model="form.bc_id" clearable filterable style="width:100%">
                <el-option v-for="b in bcOptions" :key="b.id" :label="b.name+' ('+b.bc_id+')'" :value="b.id" />
              </el-select>
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="代投比例"><el-input-number v-model="form.agency_ratio" :min="0" :max="100" style="width:100%" /></el-form-item>
          </el-col>
        </el-row>
        <el-row :gutter="16">
          <el-col :span="12"><el-form-item label="客户"><el-input v-model="form.customer" /></el-form-item></el-col>
          <el-col :span="12">
            <el-form-item label="状态">
              <el-select v-model="form.status" style="width:100%">
                <el-option label="正常" value="active" /><el-option label="暂停" value="paused" />
              </el-select>
            </el-form-item>
          </el-col>
        </el-row>
        <el-form-item label="在跑人员">
          <el-select v-model="form.runner_ids" multiple filterable style="width:100%">
            <el-option v-for="u in ttUsers" :key="u.id" :label="(u.display_name||u.username)+' ('+u.username+')'" :value="u.id" />
          </el-select>
        </el-form-item>

        <el-divider content-position="left">投放对象</el-divider>
        <el-button size="small" type="success" @click="addPkgRow('package')" class="add-btn">+ 跑包</el-button>
        <el-button size="small" type="warning" @click="addPkgRow('pwa')" class="add-btn">+ PWA</el-button>
        <el-button size="small" @click="openImportText" class="add-btn">粘贴解析</el-button>
        <el-table :data="formPackages" border size="small" class="dialog-pkg-table"
          :header-cell-style="{ background:'#f8f9fa', color:'#374151', fontWeight:600 }">
          <el-table-column label="类型" width="80">
            <template #default="{ row }"><el-tag :type="row.type === 'pwa' ? 'warning' : 'primary'" size="small">{{ row.type === 'pwa' ? 'PWA' : '跑包' }}</el-tag></template>
          </el-table-column>
          <el-table-column label="系列名" min-width="130">
            <template #default="{row,$index}"><el-input v-model="formPackages[$index].series_name" size="small" /></template>
          </el-table-column>
          <el-table-column label="包名（仅跑包）" min-width="140">
            <template #default="{row,$index}"><el-input v-model="formPackages[$index].package_name" size="small" :disabled="row.type==='pwa'" /></template>
          </el-table-column>
          <el-table-column label="链接" min-width="180">
            <template #default="{row,$index}"><el-input v-model="formPackages[$index].url" size="small" /></template>
          </el-table-column>
          <el-table-column label="状态" width="100">
            <template #default="{row,$index}"><el-input v-model="formPackages[$index].status" size="small" /></template>
          </el-table-column>
          <el-table-column label="操作" width="70" align="center">
            <template #default="{ $index }"><el-button size="small" type="danger" @click="formPackages.splice($index,1)">删除</el-button></template>
          </el-table-column>
        </el-table>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible=false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="handleSave">保存</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="importVisible" title="粘贴解析投放对象" width="560px">
      <el-input v-model="importTextRaw" type="textarea" :rows="6" placeholder="粘贴 Google Play 链接文本（跑包）..." />
      <div style="margin-top:8px;display:flex;gap:8px;">
        <el-input v-model="importPrefix" placeholder="前缀（可选）" size="small" style="width:140px" />
        <el-input v-model="importSuffix" placeholder="后缀（可选）" size="small" style="width:140px" />
      </div>
      <template #footer>
        <el-button @click="importVisible=false">取消</el-button>
        <el-button type="primary" @click="handleImportText">解析并加入</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, reactive, onMounted } from 'vue'
import { useAuthStore } from '../../stores/auth'
import { ttApi } from '../../api/tt'
import { ElMessage } from 'element-plus'
import { copyToClipboard } from '../../utils/clipboard'
import client from '../../api/client'

const auth = useAuthStore()
const items = ref([]); const loading = ref(false)
const page = ref(1); const size = ref(5); const total = ref(0)
const search = ref(''); const filterStatus = ref(''); const filterRegion = ref('')
const filterArchived = ref(''); const filterRunner = ref(null)
const dialogVisible = ref(false); const editingId = ref(null); const saving = ref(false)
const checkingId = ref(null)
const bcOptions = ref([]); const ttUsers = ref([]); const salesOptions = ref([]); const regionOptions = ref([])
const form = reactive({ product_name:'', kpi:'', region:'', status:'active', bc_id:null, sales_person_id:null, agency_ratio:0, customer:'', runner_ids:[] })
const formPackages = ref([])
const expanded = ref({})
const importVisible = ref(false); const importTextRaw = ref(''); const importPrefix = ref(''); const importSuffix = ref('')

function toggleExpand(id) { expanded.value[id] = !expanded.value[id] }
async function copy(val) { if (!val) return; await copyToClipboard(val); ElMessage.success('已复制 ✓') }

let searchTimer = null
function onSearch() { clearTimeout(searchTimer); searchTimer = setTimeout(loadData, 300) }
function addPkgRow(type) { formPackages.value.push({ type, series_name:'', package_name:'', url:'', status:'' }) }

async function loadData() {
  loading.value = true
  try {
    const p = { page: page.value, size: size.value }
    if (search.value) p.search = search.value
    if (filterStatus.value) p.status = filterStatus.value
    if (filterRegion.value) p.region = filterRegion.value
    if (filterRunner.value) p.runner = filterRunner.value
    if (filterArchived.value) p.archived = filterArchived.value
    const res = await ttApi.listProducts(p)
    items.value = res.items || []; total.value = res.total || 0
  } finally { loading.value = false }
}

async function loadOptions() {
  try { const r = await ttApi.bcOptions(); bcOptions.value = r.data || [] } catch(e) {}
  try { const r = await ttApi.listTtUsers(); ttUsers.value = r.users || [] } catch(e) {}
  try { const r = await client.get('/sales-persons/list'); salesOptions.value = r.sales_persons || [] } catch(e) {}
  try { const r = await client.get('/regions/list'); regionOptions.value = (r.regions || []).map(r => typeof r === 'string' ? { name: r } : r) } catch(e) {}
}

async function refreshOptions() {
  try { const r = await ttApi.bcOptions(); bcOptions.value = r.data || [] } catch(e) {}
  try { const r = await client.get('/sales-persons/list'); salesOptions.value = r.sales_persons || [] } catch(e) {}
  try { const r = await client.get('/regions/list'); regionOptions.value = (r.regions || []).map(r => typeof r === 'string' ? { name: r } : r) } catch(e) {}
}

async function openCreate() {
  editingId.value = null
  Object.assign(form, { product_name:'', kpi:'', region:'', status:'active', bc_id:null, sales_person_id:null, agency_ratio:0, customer:'', runner_ids:[] })
  formPackages.value = []
  await refreshOptions()
  dialogVisible.value = true
}

async function openEdit(row) {
  editingId.value = row.id
  Object.assign(form, {
    product_name: row.product_name, kpi: row.kpi, region: row.region, status: row.status || 'active',
    bc_id: row.bc ? row.bc.id : row.bc_id, sales_person_id: row.sales_person_id,
    agency_ratio: row.agency_ratio, customer: row.customer || '', runner_ids: (row.runners||[]).map(r => r.id),
  })
  formPackages.value = (row.packages||[]).map(p => ({ type: p.type, series_name: p.series_name, package_name: p.package_name, url: p.url, status: p.status }))
  await refreshOptions()
  dialogVisible.value = true
}

async function handleSave() {
  if (!form.product_name) return ElMessage.warning('请输入产品名')
  if (!editingId.value && auth.user && !form.runner_ids.includes(auth.user.id)) form.runner_ids.push(auth.user.id)
  saving.value = true
  try {
    if (form.region && !regionOptions.value.some(r => r.name === form.region)) {
      await client.post('/regions/create', { name: form.region, timezone: '' })
      try { const r = await client.get('/regions/list'); regionOptions.value = (r.regions || []).map(r => typeof r === 'string' ? { name: r } : r) } catch(e) {}
    }
    if (typeof form.sales_person_id === 'string' && form.sales_person_id) {
      const res = await client.post('/sales-persons/create', { name: form.sales_person_id })
      form.sales_person_id = res.id
    }
    const data = { ...form, packages: formPackages.value }
    editingId.value ? await ttApi.updateProduct(editingId.value, data) : await ttApi.createProduct(data)
    ElMessage.success(editingId.value ? '已更新' : '已创建')
    dialogVisible.value = false; loadData()
  } catch(e) { ElMessage.error(e.response?.data?.error || '保存失败') }
  finally { saving.value = false }
}

async function handleCheckDelist(item) {
  checkingId.value = item.id
  try {
    const res = await ttApi.checkDelist(item.id)
    const results = res.results || []
    const delisted = results.filter(r => r.is_delisted).length
    ElMessage.success(`检测完成：${results.length} 个跑包，${delisted} 个掉包`)
    loadData()
  } catch(e) { ElMessage.error(e.response?.data?.error || '检测失败') }
  finally { checkingId.value = null }
}

function openImportText() { importTextRaw.value = ''; importPrefix.value = ''; importSuffix.value = ''; importVisible.value = true }

async function handleImportText() {
  if (!importTextRaw.value.trim()) return ElMessage.warning('请粘贴文本')
  try {
    const res = await ttApi.importText({ text: importTextRaw.value, prefix: importPrefix.value, suffix: importSuffix.value })
    const parsed = res.parsed || []
    if (!parsed.length) return ElMessage.warning('未解析到 Google Play 链接')
    for (const p of parsed) formPackages.value.push(p)
    importVisible.value = false
    ElMessage.success(`已解析 ${parsed.length} 个跑包`)
  } catch(e) { ElMessage.error(e.response?.data?.error || '解析失败') }
}

function handleDelete(id) { ttApi.deleteProduct(id).then(() => { ElMessage.success('已删除'); loadData() }) }
function handleRestore(id) { ttApi.restoreProduct(id).then(() => { ElMessage.success('已恢复'); loadData() }) }

onMounted(() => { loadOptions(); loadData() })
</script>

<style scoped>
.page-wrapper { background:#f5f6f8;padding:24px;min-height:100%;display:flex;flex-direction:column;gap:16px; }
.page-header { display:flex;justify-content:space-between;align-items:center; }
.page-title { margin:0;font-size:20px;font-weight:700;color:#1f2937; }
.filter-card { background:#f8f9fa;border-radius:12px;padding:14px 16px;display:flex;align-items:center;gap:12px;flex-wrap:wrap;border:1px solid #e5e7eb; }
.total-badge { font-size:13px;color:#6b7280;font-weight:500;white-space:nowrap;padding:4px 10px;background:#fff;border-radius:6px;border:1px solid #e5e7eb; }
.product-list { flex:1;min-height:0;overflow-y:auto; }
.product-card { margin-bottom:12px;border-radius:12px;border:1px solid #e5e7eb;overflow:hidden; }
.product-card.is-paused { opacity:0.7; }
.product-card-inner { padding:16px; }
.product-card-header { display:flex;justify-content:space-between;align-items:flex-start;cursor:pointer;gap:16px; }
.product-card-info { flex:1;min-width:0; }
.product-card-tags { display:flex;align-items:center;gap:8px;margin-bottom:6px;flex-wrap:wrap; }
.status-dot { width:8px;height:8px;border-radius:50%;display:inline-block;flex-shrink:0; }
.dot-active { background:#059669; }
.dot-paused { background:#dc2626; }
.product-name { font-size:15px;color:#1f2937; }
.tag-sales { background:#ecfdf5 !important;color:#059669 !important;border-color:#a7f3d0 !important; }
.tag-kpi { background:#fffbeb !important;color:#d97706 !important;border-color:#fde68a !important; }
.tag-region { background:#eff6ff !important;color:#2563eb !important;border-color:#bfdbfe !important; }
.tag-customer { background:#fdf4ff !important;color:#c026d3 !important;border-color:#f5d0fe !important; }
.product-card-bc { margin-bottom:4px; }
.product-card-runners { font-size:12px;color:#9ca3af;margin-bottom:2px; }
.product-card-lines { font-size:12px;color:#9ca3af; }
.expand-hint { display:inline-block;margin-left:8px;color:#0891b2;font-size:11px;cursor:pointer; }
.product-card-actions { display:flex;gap:4px;flex-shrink:0; }
.product-card-expand { margin-top:14px;padding-top:14px;border-top:1px solid #f3f4f6; }
.pkg-table, .dialog-pkg-table { border-radius:8px;overflow:hidden; }
.copy-link { cursor:pointer;color:#0891b2;font-size:13px; }
.copy-link:hover { color:#06b6d4;text-decoration:underline; }
.no-data { color:#9ca3af;font-size:12px; }
.no-lines { color:#9ca3af;font-size:13px;padding:8px 0;text-align:center; }
.pagination-row { display:flex;justify-content:center;gap:8px;margin-top:16px;padding-bottom:4px; }
.add-btn { margin-bottom:10px; }
</style>
```

- [ ] **Step 2: 校验前端编译**

Run: `cd frontend && npm run build`
Expected: 编译成功（无报错，TT 路由引用的两个 `.vue` 文件均已创建）

- [ ] **Step 3: 提交**

```bash
git add frontend/src/views/tt/TtProductPanel.vue
git commit -m "feat: TT 产品管理页（TtProductPanel.vue，含投放对象子表/掉包检测/粘贴解析）"
```

---

## Task 11: 端到端验证 + 收尾

**Files:** 无新文件（回归验证）

- [ ] **Step 1: 运行全部后端测试**

Run: `cd py && python -m pytest tests/ -v`
Expected: 全绿（既有 GG/FB 测试 + 新增 TT 测试均通过，确认无回归）

- [ ] **Step 2: 前端完整构建**

Run: `cd frontend && npm run build`
Expected: 编译成功

- [ ] **Step 3: 手动冒烟验证（后端起服务 + 浏览器）**

1. 启动后端：`cd py && python main.py`
2. 启动前端：`cd frontend && npm run dev`
3. 用 developer 账号登录 → 侧边栏出现 `[GG][FB][TT]` 切换
4. 切到 TT → 进入 `/tt/products` → 新增产品（含跑包/PWA 投放对象、BC、在跑人员）→ 保存 → 列表展开查看投放对象 type 标签
5. 对含跑包的产品点「掉包检测」→ 返回结果
6. 进 `/tt/bcs` → 新增/编辑/删除 BC
7. 进 `/admin/users` → 创建平台为 TT 的用户 → 用该 TT 用户登录 → 自动跳到 `/tt/products`

- [ ] **Step 4: 收尾提交（如有遗漏的格式化改动）**

```bash
git status
git add -A
git commit -m "chore: TT 产品管理模块收尾（端到端验证通过）"
```

---

## 自审记录

**1. 规格覆盖**：设计文档各节均有对应任务——第二节技术方案（Task 1/2/3）、第三节数据库（Task 1）、第四节 API 路由（Task 3-7）、第五节前端（Task 8-10）、第六节用户管理 TT（Task 2/8）、第七节掉包检测（Task 6）、第八节文件清单（贯穿全部 Task）。设计文档第九节「后续阶段」（TT 账户管理/数据提取/做表/PWA 完善）明确不在本轮，已排除。

**2. 与设计文档的两处有意偏离（均已在上文注明）**：
- `stores/tt.js` 不新建（遵循 FB 实际模式，组件直接 import `ttApi`）。
- 素材关联 `add_assets` 第一阶段采用「选择已有视频建立关联」，不做「导入新视频」（导入逻辑 `_batch_import_videos` 位于 `main.py`，复制会引入循环依赖；且设计文档第四节素材语义未细化）。

**3. 类型/命名一致性**：`tt_bp`、`tt_required`、`ttApi`、`_get_role`、`tt_headers`、`tt_packages.type`（`'package'`/`'pwa'`）在前后端与测试中命名一致；后端返回 `items/total/page/size` 或 `data/[...]`（`ok()` 自动包装 list），前端 `ttApi` 方法返回值与之一致。
