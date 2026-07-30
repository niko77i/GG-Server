# Facebook 平台支持 — 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 GG-Server 中新增 Facebook (FB) 广告平台支持，包括用户平台划分、6 个新页面、8 张新表、~35 个新 API 端点，GG 代码仅做权限相关的最小改动。

**Architecture:** 混合模式 — FB 使用独立的新表/路由/页面，GG 代码仅在 users 表、auth 模块、路由守卫、侧边栏中做必要扩展。后端新增 `py/routes/fb_routes.py`，前端新增 `frontend/src/views/fb/` 目录。

**Tech Stack:** Python Flask + SQLite + Vue 3 + Element Plus + Pinia

**Spec:** [2026-07-30-fb-platform-design.md](../specs/2026-07-30-fb-platform-design.md)

## Global Constraints

- TDD 铁律：先写测试→看它失败→写最小实现→看它通过→重构
- GG 源代码只做权限相关改动，FB 功能全部新文件
- 前端改动后需 `npm run build`，后端改动后需重启 Flask
- 每次完成 bug 修复或功能需求后提醒提交 git
- 遵循现有代码风格（Flask Blueprint 模式、Vue Composition API）

---

## 文件结构

### 新建文件

| 文件 | 职责 |
|------|------|
| `py/routes/fb_routes.py` | 所有 FB API 路由（~35 个端点） |
| `py/tests/test_fb_routes.py` | FB API 测试 |
| `frontend/src/views/fb/FbProductPanel.vue` | FB 产品管理页面 |
| `frontend/src/views/fb/FbAccountPanel.vue` | FB 账户管理页面 |
| `frontend/src/views/fb/FbBmPanel.vue` | 账户BM管理页面 |
| `frontend/src/views/fb/FbPixelBmPanel.vue` | 像素BM管理页面 |
| `frontend/src/views/fb/FbDataExtract.vue` | FB 数据提取页面 |
| `frontend/src/views/fb/FbDataManage.vue` | FB 数据管理页面 |
| `frontend/src/api/fb.js` | FB API 调用模块 |
| `frontend/src/stores/fb.js` | FB Pinia 状态管理 |

### 修改文件

| 文件 | 改动 |
|------|------|
| `py/database.py` | 新增 8 张 FB 表的建表语句 |
| `py/auth.py` | 用户 CRUD 函数加 `platform` 字段 |
| `py/main.py` | 注册 fb_routes Blueprint |
| `py/routes/helpers.py` | 新增 `require_platform()` 权限检查 |
| `py/routes/decorators.py` | 新增 `@fb_required` / `@gg_required` 装饰器 |
| `frontend/src/router/index.js` | 新增 6 条 FB 路由 + platform 守卫 |
| `frontend/src/components/AppSidebar.vue` | platform 菜单切换 |
| `frontend/src/stores/auth.js` | 新增 platform getter + 切换状态 |
| `frontend/src/views/UserManageView.vue` | 创建用户时选 GG/FB 平台 |

---

### Task 1: 数据库 — users 表加 platform 字段

**Files:**
- Modify: `py/database.py` (users 表定义处)
- Test: `py/tests/test_fb_platform.py` (新建)

**Interfaces:**
- Consumes: 现有 users 表结构
- Produces: `users.platform TEXT DEFAULT 'gg'`，值 'gg' | 'fb'，developer 可为 NULL

- [ ] **Step 1: 写失败测试**

```python
# py/tests/test_fb_platform.py
import pytest
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database import get_db, _ensure_schema


def test_users_table_has_platform_column():
    """验证 users 表包含 platform 字段"""
    db = get_db()
    _ensure_schema(db)
    cursor = db.execute("PRAGMA table_info(users)")
    columns = {row[1]: row[2] for row in cursor.fetchall()}
    assert 'platform' in columns
    assert columns['platform'] == 'TEXT'


def test_platform_default_value():
    """验证 platform 字段默认值为 'gg'"""
    db = get_db()
    _ensure_schema(db)
    from auth import create_user, delete_user
    import uuid
    test_username = f'test_platform_{uuid.uuid4().hex[:8]}'
    create_user(db, test_username, 'test', 'user', 'Test', None)
    user = db.execute("SELECT platform FROM users WHERE username = ?", (test_username,)).fetchone()
    assert user['platform'] == 'gg'
    # cleanup
    db.execute("DELETE FROM users WHERE username = ?", (test_username,))
    db.commit()


def test_developer_platform_null():
    """验证 developer 的 platform 可为 NULL（表示双平台）"""
    db = get_db()
    _ensure_schema(db)
    db.execute("UPDATE users SET platform = NULL WHERE role = 'developer' AND username = 'carl567'")
    db.commit()
    user = db.execute("SELECT platform FROM users WHERE username = 'carl567'").fetchone()
    assert user['platform'] is None
    # restore
    db.execute("UPDATE users SET platform = 'gg' WHERE username = 'carl567'")
    db.commit()
```

- [ ] **Step 2: 运行测试验证失败**

```bash
cd py && python -m pytest tests/test_fb_platform.py -v
```
预期：`test_users_table_has_platform_column` FAIL（platform 列不存在）

- [ ] **Step 3: 修改 database.py 加 platform 字段**

在 `py/database.py` 的 `_ensure_schema()` 函数中，找到 users 表建表语句（约第 369 行），在 `custom_name TEXT DEFAULT ''` 后追加：

```python
platform TEXT DEFAULT 'gg',
```

同时在 `_ensure_schema()` 末尾或自动迁移逻辑中加 ALTER TABLE（如果 users 表已存在）：

```python
# 迁移：为已有 users 表添加 platform 字段
try:
    db.execute("ALTER TABLE users ADD COLUMN platform TEXT DEFAULT 'gg'")
except:
    pass  # 字段已存在
```

- [ ] **Step 4: 运行测试验证通过**

```bash
cd py && python -m pytest tests/test_fb_platform.py -v
```
预期：3 tests PASS

- [ ] **Step 5: Commit**

```bash
git add py/database.py py/tests/test_fb_platform.py
git commit -m "feat: users 表新增 platform 字段"
```

---

### Task 2: 数据库 — 新建 FB 8 张表

**Files:**
- Modify: `py/database.py` (追加建表语句)
- Test: `py/tests/test_fb_platform.py` (追加测试)

**Interfaces:**
- Consumes: SQLite WAL 模式
- Produces: fb_bms, fb_accounts, fb_account_bm, fb_account_bm_history, fb_products, fb_product_runners, fb_product_bms, fb_lines, fb_pixel_bms, fb_pixels, fb_ad_reports 共 11 张表

- [ ] **Step 1: 写失败测试**

在 `py/tests/test_fb_platform.py` 追加：

```python
def test_fb_tables_exist():
    """验证所有 FB 表均已创建"""
    db = get_db()
    _ensure_schema(db)
    expected_tables = [
        'fb_bms', 'fb_accounts', 'fb_account_bm', 'fb_account_bm_history',
        'fb_products', 'fb_product_runners', 'fb_product_bms',
        'fb_lines', 'fb_pixel_bms', 'fb_pixels', 'fb_ad_reports'
    ]
    tables = db.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    table_names = {t['name'] for t in tables}
    for tbl in expected_tables:
        assert tbl in table_names, f"Table {tbl} not found"


def test_fb_bms_unique_bm_id():
    """验证 fb_bms.bm_id 唯一约束"""
    db = get_db()
    _ensure_schema(db)
    db.execute("INSERT INTO fb_bms (name, bm_id, owner_id) VALUES ('test1', '123456', 1)")
    db.commit()
    import sqlite3
    with pytest.raises(sqlite3.IntegrityError):
        db.execute("INSERT INTO fb_bms (name, bm_id, owner_id) VALUES ('test2', '123456', 1)")
        db.commit()
    # cleanup
    db.execute("DELETE FROM fb_bms WHERE bm_id = '123456'")
    db.commit()


def test_fb_account_bm_many_to_many():
    """验证 fb_account_bm 多对多关系"""
    db = get_db()
    _ensure_schema(db)
    # 创建测试数据
    db.execute("INSERT INTO fb_bms (name, bm_id, owner_id) VALUES ('bm1', '111', 1)")
    db.execute("INSERT INTO fb_bms (name, bm_id, owner_id) VALUES ('bm2', '222', 1)")
    db.execute("INSERT INTO fb_accounts (name, account_id, owner_id) VALUES ('acc1', '999999999999999', 1)")
    db.commit()
    bm1_id = db.execute("SELECT id FROM fb_bms WHERE bm_id='111'").fetchone()['id']
    bm2_id = db.execute("SELECT id FROM fb_bms WHERE bm_id='222'").fetchone()['id']
    acc_id = db.execute("SELECT id FROM fb_accounts WHERE account_id='999999999999999'").fetchone()['id']
    # 关联到两个BM
    db.execute("INSERT INTO fb_account_bm (account_id, bm_id) VALUES (?, ?)", (acc_id, bm1_id))
    db.execute("INSERT INTO fb_account_bm (account_id, bm_id) VALUES (?, ?)", (acc_id, bm2_id))
    db.commit()
    # 验证
    bms = db.execute("SELECT bm_id FROM fb_account_bm WHERE account_id = ?", (acc_id,)).fetchall()
    assert len(bms) == 2
    # cleanup
    db.execute("DELETE FROM fb_account_bm WHERE account_id = ?", (acc_id,))
    db.execute("DELETE FROM fb_accounts WHERE account_id = '999999999999999'")
    db.execute("DELETE FROM fb_bms WHERE bm_id IN ('111','222')")
    db.commit()


def test_fb_lines_unique_product_line():
    """验证 fb_lines 同一产品下不能重名"""
    db = get_db()
    _ensure_schema(db)
    db.execute("INSERT INTO fb_products (product_name, owner_id) VALUES ('test_product', 1)")
    db.commit()
    pid = db.execute("SELECT id FROM fb_products WHERE product_name='test_product'").fetchone()['id']
    db.execute("INSERT INTO fb_lines (product_id, line_name) VALUES (?, 'line1')", (pid,))
    db.commit()
    import sqlite3
    with pytest.raises(sqlite3.IntegrityError):
        db.execute("INSERT INTO fb_lines (product_id, line_name) VALUES (?, 'line1')", (pid,))
        db.commit()
    # cleanup
    db.execute("DELETE FROM fb_lines WHERE product_id = ?", (pid,))
    db.execute("DELETE FROM fb_products WHERE id = ?", (pid,))
    db.commit()


def test_fb_ad_reports_dedup_index():
    """验证 fb_ad_reports 去重索引"""
    db = get_db()
    _ensure_schema(db)
    indexes = db.execute("SELECT name FROM sqlite_master WHERE type='index' AND name LIKE 'idx_fb_ad_reports_upsert%'").fetchall()
    assert len(indexes) > 0, "Missing unique index on fb_ad_reports"
```

- [ ] **Step 2: 运行测试验证失败**

```bash
cd py && python -m pytest tests/test_fb_platform.py::test_fb_tables_exist -v
```
预期：FAIL（FB 表不存在）

- [ ] **Step 3: 在 database.py 加建表语句**

在 `py/database.py` 的 `_ensure_schema()` 函数末尾（其他建表语句之后），追加设计文档中所有 11 张 FB 表的 `CREATE TABLE IF NOT EXISTS` 语句。完整 SQL 见设计文档第 3.2 节。

- [ ] **Step 4: 运行测试验证通过**

```bash
cd py && python -m pytest tests/test_fb_platform.py -v
```
预期：7 tests PASS

- [ ] **Step 5: Commit**

```bash
git add py/database.py py/tests/test_fb_platform.py
git commit -m "feat: 新建 FB 11 张数据库表"
```

---

### Task 3: auth.py — 用户 CRUD 支持 platform 字段

**Files:**
- Modify: `py/auth.py`
- Test: `py/tests/test_fb_platform.py` (追加测试)

**Interfaces:**
- Consumes: `database.get_db()`
- Produces: `create_user(db, username, password, role, display_name, created_by, platform='gg')`, `get_user_by_id()` 返回含 platform，`list_users()` 返回含 platform 且支持 platform 筛选

- [ ] **Step 1: 写失败测试**

在 `py/tests/test_fb_platform.py` 追加：

```python
def test_create_user_with_platform():
    """验证 create_user 接受 platform 参数"""
    db = get_db()
    _ensure_schema(db)
    import uuid
    from auth import create_user
    test_username = f'test_fb_user_{uuid.uuid4().hex[:8]}'
    user_id = create_user(db, test_username, 'test', 'user', 'Test FB', None, platform='fb')
    user = db.execute("SELECT platform FROM users WHERE id = ?", (user_id,)).fetchone()
    assert user['platform'] == 'fb'
    # cleanup
    db.execute("DELETE FROM users WHERE id = ?", (user_id,))
    db.commit()


def test_get_user_by_id_returns_platform():
    """验证 get_user_by_id 返回 platform 字段"""
    db = get_db()
    _ensure_schema(db)
    from auth import get_user_by_id
    user = get_user_by_id(db, 1)  # developer
    assert 'platform' in user


def test_list_users_supports_platform_filter():
    """验证 list_users 支持按 platform 筛选"""
    db = get_db()
    _ensure_schema(db)
    from auth import list_users, create_user
    import uuid
    # 创建一个 fb 用户
    test_username = f'test_list_fb_{uuid.uuid4().hex[:8]}'
    uid = create_user(db, test_username, 'test', 'user', 'List FB', None, platform='fb')
    # 按 platform=fb 筛选
    result = list_users(db, platform='fb')
    usernames = [u['username'] for u in result['users']]
    assert test_username in usernames
    # 按 platform=gg 筛选（应不包含该fb用户）
    result_gg = list_users(db, platform='gg')
    usernames_gg = [u['username'] for u in result_gg['users']]
    assert test_username not in usernames_gg
    # cleanup
    db.execute("DELETE FROM users WHERE id = ?", (uid,))
    db.commit()


def test_login_returns_platform():
    """验证登录响应返回 platform 字段"""
    db = get_db()
    _ensure_schema(db)
    from auth import authenticate
    result = authenticate(db, 'carl567', '1976xiaobai')
    assert result is not None
    assert 'platform' in result
```

- [ ] **Step 2: 运行测试验证失败**

```bash
cd py && python -m pytest tests/test_fb_platform.py::test_create_user_with_platform -v
```
预期：FAIL（create_user 不接受 platform 参数）

- [ ] **Step 3: 修改 auth.py**

改动点：
1. `create_user()` 签名加 `platform='gg'` 参数，INSERT 中包含 platform
2. `get_user_by_id()` SELECT 中加 `platform`
3. `list_users()` SELECT 中加 `platform`，支持 `platform` 参数筛选
4. `authenticate()` 返回字典加 `'platform': user['platform']`
5. 登录端点 `/api/auth/me` 返回 `platform`

- [ ] **Step 4: 运行测试验证通过**

```bash
cd py && python -m pytest tests/test_fb_platform.py -v -k "platform"
```
预期：相关测试 PASS

- [ ] **Step 5: Commit**

```bash
git add py/auth.py py/tests/test_fb_platform.py
git commit -m "feat: auth 模块支持 platform 字段"
```

---

### Task 4: 权限装饰器 — require_platform 和 fb_required

**Files:**
- Modify: `py/routes/decorators.py`
- Modify: `py/routes/helpers.py`
- Test: `py/tests/test_fb_platform.py` (追加测试)

**Interfaces:**
- Consumes: `get_jwt_identity()`
- Produces: `require_platform(platform)` 函数，`@fb_required` / `@gg_required` 装饰器

- [ ] **Step 1: 写失败测试**

```python
def test_require_platform_rejects_wrong_platform():
    """验证 require_platform 拒绝错误平台的用户"""
    # 此测试需要 Flask test client，先创建测试 app
    from database import get_db
    db = get_db()
    _ensure_schema(db)
    # 创建一个 fb 用户
    from auth import create_user
    import uuid
    test_username = f'test_perm_{uuid.uuid4().hex[:8]}'
    uid = create_user(db, test_username, 'test', 'user', 'Test', None, platform='fb')
    
    # 用 fb 用户 token 访问 gg 路由应该被拒绝
    from main import app
    with app.test_client() as client:
        # 登录获取 token
        resp = client.post('/api/auth/login', json={'username': test_username, 'password': 'test'})
        token = resp.get_json()['access_token']
        # 访问 gg 路由
        resp = client.get('/api/ad-reports/dashboard', 
                         headers={'Authorization': f'Bearer {token}'})
        assert resp.status_code == 403
    
    # cleanup
    db.execute("DELETE FROM users WHERE id = ?", (uid,))
    db.commit()
```

- [ ] **Step 2: 运行测试验证失败**

```bash
cd py && python -m pytest tests/test_fb_platform.py::test_require_platform_rejects_wrong_platform -v
```
预期：FAIL（GG 路由未拒绝 FB 用户）

- [ ] **Step 3: 实现权限检查**

在 `py/routes/helpers.py` 加：

```python
def require_platform(required_platform):
    """检查当前用户是否属于指定平台。developer 直接放行。"""
    from flask_jwt_extended import get_jwt_identity
    uid = get_jwt_identity()
    db = get_db()
    user = db.execute("SELECT role, platform FROM users WHERE id=?", (uid,)).fetchone()
    if not user:
        abort(401)
    if user['role'] == 'developer':
        return
    if user['platform'] != required_platform:
        abort(403)
```

在 `py/routes/decorators.py` 加：

```python
from functools import wraps
from flask import abort
from flask_jwt_extended import get_jwt_identity

def fb_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        require_platform('fb')
        return f(*args, **kwargs)
    return decorated

def gg_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        require_platform('gg')
        return f(*args, **kwargs)
    return decorated
```

- [ ] **Step 4: 在 main.py 中给 GG 路由加 @gg_required**

对 `/api/ad-reports/*`、`/api/accounts/*`、`/api/mcc/*`、`/api/products/*`、`/api/scrape/*`、`/api/video/*`、`/api/youtube/*` 相关路由加 `@gg_required`。

- [ ] **Step 5: 运行测试验证通过**

```bash
cd py && python -m pytest tests/test_fb_platform.py -v -k "require_platform"
```

- [ ] **Step 6: Commit**

```bash
git add py/routes/helpers.py py/routes/decorators.py py/main.py py/tests/test_fb_platform.py
git commit -m "feat: 新增 platform 权限装饰器 @fb_required / @gg_required"
```

---

### Task 5: FB API — BM 管理路由

**Files:**
- Create: `py/routes/fb_routes.py`
- Modify: `py/main.py` (注册 Blueprint)
- Test: `py/tests/test_fb_routes.py` (新建)

**Interfaces:**
- Consumes: `database.get_db()`, `@jwt_required()`, `@fb_required`
- Produces: `/api/fb/bms/*` 全部端点

- [ ] **Step 1: 写失败测试**

```python
# py/tests/test_fb_routes.py
import pytest
import json
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database import get_db, _ensure_schema
from main import app


@pytest.fixture
def client():
    app.config['TESTING'] = True
    with app.test_client() as c:
        db = get_db()
        _ensure_schema(db)
        yield c


@pytest.fixture
def dev_token(client):
    resp = client.post('/api/auth/login', json={'username': 'carl567', 'password': '1976xiaobai'})
    return resp.get_json()['access_token']


def test_create_bm(dev_token, client):
    """测试创建账户BM"""
    resp = client.post('/api/fb/bms/create',
        json={'name': '测试BM', 'bm_id': '987654321', 'note': '测试用'},
        headers={'Authorization': f'Bearer {dev_token}'})
    assert resp.status_code == 200
    data = resp.get_json()
    assert data['success'] is True
    # verify in db
    db = get_db()
    bm = db.execute("SELECT * FROM fb_bms WHERE bm_id='987654321'").fetchone()
    assert bm is not None
    assert bm['name'] == '测试BM'
    # cleanup
    db.execute("DELETE FROM fb_bms WHERE bm_id='987654321'")
    db.commit()


def test_list_bms(dev_token, client):
    """测试BM列表"""
    db = get_db()
    db.execute("INSERT INTO fb_bms (name, bm_id, owner_id) VALUES ('list_test', '111222', 1)")
    db.commit()
    resp = client.get('/api/fb/bms/list',
        headers={'Authorization': f'Bearer {dev_token}'})
    assert resp.status_code == 200
    data = resp.get_json()
    assert data['success'] is True
    assert len(data['data']) >= 1
    # cleanup
    db.execute("DELETE FROM fb_bms WHERE bm_id='111222'")
    db.commit()


def test_bm_id_pure_number_validation(dev_token, client):
    """测试BM ID纯数字校验"""
    resp = client.post('/api/fb/bms/create',
        json={'name': '非法BM', 'bm_id': 'abc123'},
        headers={'Authorization': f'Bearer {dev_token}'})
    assert resp.status_code == 400  # 应拒绝非纯数字


def test_delete_bm_soft(dev_token, client):
    """测试BM软删除"""
    db = get_db()
    db.execute("INSERT INTO fb_bms (name, bm_id, owner_id) VALUES ('del_test', '333444', 1)")
    db.commit()
    bm = db.execute("SELECT id FROM fb_bms WHERE bm_id='333444'").fetchone()
    resp = client.delete(f"/api/fb/bms/{bm['id']}",
        headers={'Authorization': f'Bearer {dev_token}'})
    assert resp.status_code == 200
    # 验证软删除
    deleted = db.execute("SELECT deleted_at FROM fb_bms WHERE bm_id='333444'").fetchone()
    assert deleted['deleted_at'] is not None
    # cleanup
    db.execute("DELETE FROM fb_bms WHERE bm_id='333444'")
    db.commit()
```

- [ ] **Step 2: 运行测试验证失败**

```bash
cd py && python -m pytest tests/test_fb_routes.py -v
```
预期：404（fb_routes 未注册）

- [ ] **Step 3: 创建 fb_routes.py 并实现 BM API**

```python
# py/routes/fb_routes.py
from flask import Blueprint, request, jsonify, g
from flask_jwt_extended import jwt_required
from .decorators import fb_required
from .helpers import ok, err, get_uid, get_db, parse_body

fb_bp = Blueprint('fb', __name__)


@fb_bp.route('/api/fb/bms/create', methods=['POST'])
@jwt_required()
@fb_required
def create_bm():
    db = get_db()
    data = parse_body()
    name = data.get('name', '').strip()
    bm_id = data.get('bm_id', '').strip()
    note = data.get('note', '').strip()

    if not name or not bm_id:
        return err('BM名称和BMID不能为空')
    if not bm_id.isdigit():
        return err('BMID必须是纯数字'), 400

    uid = get_uid()
    try:
        db.execute(
            "INSERT INTO fb_bms (name, bm_id, note, owner_id) VALUES (?, ?, ?, ?)",
            (name, bm_id, note, uid))
        db.commit()
        return ok({'id': db.execute("SELECT last_insert_rowid()").fetchone()[0]})
    except Exception as e:
        return err(str(e))


@fb_bp.route('/api/fb/bms/list', methods=['GET'])
@jwt_required()
@fb_required
def list_bms():
    db = get_db()
    page = request.args.get('page', 1, type=int)
    size = request.args.get('size', 50, type=int)
    status = request.args.get('status', '')
    offset = (page - 1) * size

    where = ["deleted_at IS NULL"]
    params = []
    if status:
        where.append("status = ?")
        params.append(status)

    where_clause = " AND ".join(where)
    total = db.execute(f"SELECT COUNT(*) FROM fb_bms WHERE {where_clause}", params).fetchone()[0]
    rows = db.execute(
        f"SELECT b.*, (SELECT COUNT(*) FROM fb_account_bm WHERE bm_id=b.id) as account_count "
        f"FROM fb_bms b WHERE {where_clause} ORDER BY b.created_at DESC LIMIT ? OFFSET ?",
        params + [size, offset]).fetchall()

    return ok({
        'items': [dict(r) for r in rows],
        'total': total,
        'page': page,
        'size': size
    })


@fb_bp.route('/api/fb/bms/<int:bid>', methods=['PUT'])
@jwt_required()
@fb_required
def update_bm(bid):
    db = get_db()
    data = parse_body()
    name = data.get('name', '').strip()
    note = data.get('note', '').strip()

    if name:
        db.execute("UPDATE fb_bms SET name=?, note=?, updated_at=datetime('now','localtime') WHERE id=?",
                   (name, note, bid))
        db.commit()
    return ok()


@fb_bp.route('/api/fb/bms/<int:bid>', methods=['DELETE'])
@jwt_required()
@fb_required
def delete_bm(bid):
    db = get_db()
    db.execute("UPDATE fb_bms SET deleted_at=datetime('now','localtime') WHERE id=?", (bid,))
    db.commit()
    return ok()


@fb_bp.route('/api/fb/bms/options', methods=['GET'])
@jwt_required()
@fb_required
def bm_options():
    db = get_db()
    rows = db.execute(
        "SELECT id, name, bm_id FROM fb_bms WHERE status='normal' AND deleted_at IS NULL ORDER BY name"
    ).fetchall()
    return ok([dict(r) for r in rows])
```

- [ ] **Step 4: 在 main.py 注册 Blueprint**

```python
from routes.fb_routes import fb_bp
app.register_blueprint(fb_bp)
```

- [ ] **Step 5: 运行测试验证通过**

```bash
cd py && python -m pytest tests/test_fb_routes.py -v
```

- [ ] **Step 6: Commit**

```bash
git add py/routes/fb_routes.py py/main.py py/tests/test_fb_routes.py
git commit -m "feat: FB BM 管理 API（创建/列表/更新/软删除/选项）"
```

---

### Task 6: FB API — 账户管理路由

**Files:**
- Modify: `py/routes/fb_routes.py` (追加)
- Test: `py/tests/test_fb_routes.py` (追加)

- [ ] **Step 1: 写测试**

```python
def test_create_fb_account(dev_token, client):
    """测试创建FB账户并关联BM"""
    db = get_db()
    db.execute("INSERT INTO fb_bms (name, bm_id, owner_id) VALUES ('acctest', '555666', 1)")
    db.commit()
    bm = db.execute("SELECT id FROM fb_bms WHERE bm_id='555666'").fetchone()

    resp = client.post('/api/fb/accounts/create',
        json={'name': '测试账户', 'account_id': '1520401159586810', 'bm_ids': [bm['id']]},
        headers={'Authorization': f'Bearer {dev_token}'})
    assert resp.status_code == 200
    data = resp.get_json()
    assert data['success'] is True

    # cleanup
    db.execute("DELETE FROM fb_account_bm WHERE account_id IN (SELECT id FROM fb_accounts WHERE account_id='1520401159586810')")
    db.execute("DELETE FROM fb_accounts WHERE account_id='1520401159586810'")
    db.execute("DELETE FROM fb_bms WHERE bm_id='555666'")
    db.commit()


def test_account_id_pure_number_validation(dev_token, client):
    """测试账户ID纯数字校验"""
    resp = client.post('/api/fb/accounts/create',
        json={'name': '非法', 'account_id': 'abc-def', 'bm_ids': []},
        headers={'Authorization': f'Bearer {dev_token}'})
    assert resp.status_code == 400


def test_soft_delete_and_restore_account(dev_token, client):
    """测试软删除和恢复"""
    db = get_db()
    db.execute("INSERT INTO fb_accounts (name, account_id, owner_id) VALUES ('softdel', '111111111111111', 1)")
    db.commit()
    acc = db.execute("SELECT id FROM fb_accounts WHERE account_id='111111111111111'").fetchone()

    # 软删除
    resp = client.delete(f"/api/fb/accounts/{acc['id']}",
        headers={'Authorization': f'Bearer {dev_token}'})
    assert resp.status_code == 200

    deleted = db.execute("SELECT deleted_at FROM fb_accounts WHERE id=?", (acc['id'],)).fetchone()
    assert deleted['deleted_at'] is not None

    # 恢复
    resp = client.post(f"/api/fb/accounts/{acc['id']}/restore",
        headers={'Authorization': f'Bearer {dev_token}'})
    assert resp.status_code == 200

    restored = db.execute("SELECT deleted_at FROM fb_accounts WHERE id=?", (acc['id'],)).fetchone()
    assert restored['deleted_at'] is None

    # cleanup
    db.execute("DELETE FROM fb_accounts WHERE id=?", (acc['id'],))
    db.commit()
```

- [ ] **Step 2-5: 实现+测试+通过+提交** (流程同上)

---

### Task 7: FB API — 产品管理路由

**Files:**
- Modify: `py/routes/fb_routes.py` (追加)
- Test: `py/tests/test_fb_routes.py` (追加)

实现端点：`/api/fb/products/*` + `/api/fb/lines/*`

---

### Task 8: FB API — 像素BM 和像素管理路由

**Files:**
- Modify: `py/routes/fb_routes.py` (追加)
- Test: `py/tests/test_fb_routes.py` (追加)

实现端点：`/api/fb/pixel-bms/*` + `/api/fb/pixels/*`

---

### Task 9: FB API — 数据提取路由

**Files:**
- Modify: `py/routes/fb_routes.py` (追加)
- Test: `py/tests/test_fb_routes.py` (追加)

实现端点：`/api/fb/extract/parse` + `/api/fb/extract/save`

核心逻辑：数据透视表动态分组 + $最大金额提取 + [数字]脏数据过滤

- [ ] **Step 1: 写解析器测试**

```python
def test_parse_fb_data_sort_mode(dev_token, client):
    """测试排序模式解析FB粘贴数据"""
    sample = """数据透视表
100M$-308
1520401159586810
250090
$3,066.48
228
[2]
2404
265
[2]
100M$-310
1351916086831194
314349
$2,709.90
232
[2]
2633
265
[2]
总成效"""

    resp = client.post('/api/fb/extract/parse',
        json={'text': sample, 'sorted': True},
        headers={'Authorization': f'Bearer {dev_token}'})
    assert resp.status_code == 200
    data = resp.get_json()
    assert data['success'] is True
    assert len(data['data']) == 2
    # 第一组
    assert data['data'][0]['account_name'] == '100M$-308'
    assert data['data'][0]['account_id'] == '1520401159586810'
    assert data['data'][0]['cost'] == 3066.48
    assert data['data'][0]['impressions'] == 250090
    assert data['data'][0]['clicks'] == 228


def test_parse_fb_data_no_sort(dev_token, client):
    """测试非排序模式解析（仅提取三项）"""
    resp = client.post('/api/fb/extract/parse',
        json={'text': sample, 'sorted': False},
        headers={'Authorization': f'Bearer {dev_token}'})
    data = resp.get_json()
    assert data['data'][0]['account_name'] == '100M$-308'
    assert data['data'][0]['account_id'] == '1520401159586810'
    assert data['data'][0]['cost'] == 3066.48
    # 非排序模式不应有展示/点击等字段
    assert data['data'][0].get('impressions', 0) == 0


def test_parse_fb_missing_header(dev_token, client):
    """测试缺少数据透视表标记"""
    resp = client.post('/api/fb/extract/parse',
        json={'text': 'random text without header', 'sorted': False},
        headers={'Authorization': f'Bearer {dev_token}'})
    assert resp.status_code == 400
```

---

### Task 10: FB API — 数据管理路由 + ban-and-migrate

**Files:**
- Modify: `py/routes/fb_routes.py` (追加)
- Test: `py/tests/test_fb_routes.py` (追加)

实现端点：`/api/fb/reports/*` + `POST /api/fb/bms/:bid/ban-and-migrate`

---

### Task 11: 前端 — auth store + 路由守卫 + 侧边栏

**Files:**
- Modify: `frontend/src/stores/auth.js`
- Modify: `frontend/src/router/index.js`
- Modify: `frontend/src/components/AppSidebar.vue`
- Modify: `frontend/src/views/UserManageView.vue`

改动：
1. auth store 加 `currentPlatform` 状态 + `isFbUser`/`isGgUser` getter
2. 路由增 6 条 FB 路由 + `meta.platform` 守卫
3. 侧边栏根据 platform 渲染菜单 + developer 切换开关
4. 用户管理创建用户时选择平台

---

### Task 12: 前端 — FB API 模块 + Store

**Files:**
- Create: `frontend/src/api/fb.js`
- Create: `frontend/src/stores/fb.js`

---

### Task 13: 前端 — FbBmPanel（账户BM管理页面）

**Files:**
- Create: `frontend/src/views/fb/FbBmPanel.vue`

---

### Task 14: 前端 — FbPixelBmPanel（像素BM管理页面）

**Files:**
- Create: `frontend/src/views/fb/FbPixelBmPanel.vue`

---

### Task 15: 前端 — FbAccountPanel（FB账户管理页面）

**Files:**
- Create: `frontend/src/views/fb/FbAccountPanel.vue`

---

### Task 16: 前端 — FbProductPanel（FB产品管理页面）

**Files:**
- Create: `frontend/src/views/fb/FbProductPanel.vue`

---

### Task 17: 前端 — FbDataExtract（FB数据提取页面）

**Files:**
- Create: `frontend/src/views/fb/FbDataExtract.vue`

---

### Task 18: 前端 — FbDataManage（FB数据管理页面）

**Files:**
- Create: `frontend/src/views/fb/FbDataManage.vue`

---

### Task 19: 集成测试 + 端到端验证

**Files:**
- Test: `py/tests/test_fb_integration.py` (新建)

完整流程测试：创建BM → 创建账户 → 创建产品+线名 → 粘贴数据 → 保存 → 查看数据管理 → 统计累加

---

## 实现顺序

```
Task 1  (DB: users platform)     ──┐
Task 2  (DB: FB 11张表)          ──┤ 基础设施
Task 3  (auth platform)          ──┤
Task 4  (权限装饰器)              ──┘
                                    │
Task 5  (API: BM)                ──┐
Task 6  (API: 账户)              ──┤
Task 7  (API: 产品)              ──┤
Task 8  (API: 像素BM)            ──┤ 后端（可并行 5-7）
Task 9  (API: 数据提取)          ──┤
Task 10 (API: 数据管理 + 迁移)   ──┘
                                    │
Task 11 (前端: auth/路由/侧边栏)  ──┐
Task 12 (前端: API+Store)        ──┤
Task 13 (前端: FbBmPanel)        ──┤ 前端（串行，逐个页面）
Task 14 (前端: FbPixelBmPanel)   ──┤
Task 15 (前端: FbAccountPanel)   ──┤
Task 16 (前端: FbProductPanel)   ──┤
Task 17 (前端: FbDataExtract)    ──┤
Task 18 (前端: FbDataManage)     ──┘
                                    │
Task 19 (集成测试)                ── 收尾
```

**重启提醒**：后端 Task 3-10 完成后需重启 Flask；前端 Task 11-18 完成后需 `npm run build`。
