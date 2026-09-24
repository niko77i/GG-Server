# 全站鉴权加固与既有缺陷收口 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 收口 13 条无鉴权路由、3 组登录后越权、2 处 500 入参、2 处死代码/谎报，并交付全站鉴权矩阵表。

**Architecture:** 纯增量收紧——A 类按「调用方式」分为「补 `@jwt_required()`」（10 条 axios/孤儿）与「路径白名单」（3 条 `<img>`/`window.open`/CSS）；B 类按 `_cross_user_actor`/`GLOBAL_OPTION_ROLES` 补归属与角色校验（仅 regions 收紧，statuses/agents/sales-persons 的 create 按裁决勘误不改）；C/D 类为入参校验与死代码清理。全部沿用 `py/routes/helpers.py` 的角色常量，不新增字面量元组。

**Tech Stack:** Flask + flask_jwt_extended 4.7.4、SQLite（临时库）、pytest + Flask test client、Vue 3 + Pinia（前端 regions 权限 gate）。

## Global Constraints

- **纯增量**：只收紧鉴权/校验，不改业务逻辑、不改既有响应形状、不改既有错误文案。
- **单一事实来源**：角色集合一律用 `py/routes/helpers.py` 的 `CROSS_USER_ROLES` / `GLOBAL_OPTION_ROLES` / `PLATFORM_SWITCH_ROLES` / `HUGUAN_ROLE`，禁止新增字面量元组。
- **装饰器顺序**：`@app.route` → `@jwt_required...` → 角色/平台装饰器 → `def`。
- **逐条实测**：每道闸门必须有「目标角色被拒 + 对照角色不被拒」的测试，禁止只写「装饰器已存在」的静态断言。
- **裁决锚点（2026-09-23）**：B 类仅 `regions_*` 收紧；`agents_create`/`statuses_create`/`sales_persons_create`/`mcc_levels_create` **勘误，不改代码**；B-3（sales-persons/create）**勘误，不改代码**。
- **行号仅作参考**：定位用「路由路径 + 函数名」，不要按行号找。
- **测试运行**：`cd py && python -m pytest tests/ -v`。
- **git**：本仓库常有并行会话在途改文件，**禁用 `git add -A`**；commit 只 `git add` 本任务涉及的文件。

## 文件结构总览

| 文件 | 改动 |
|---|---|
| `py/main.py` | A 类 13 条装饰器/白名单；B-1 三处归属校验；B-4 两处 TT 分支；B-5 regions 三处角色判定；C-1 入参校验；D-1 两处死 delete；D-2 rowcount |
| `py/auth.py` | C-2 搜索 SQL 拼接 |
| `py/routes/fb_routes.py` | B-2 `list_all_pixels` 租户隔离 |
| `py/tests/conftest.py` | 新增 `dev_headers` fixture（developer 用户） |
| `py/tests/test_security_hardening.py` | **新建**：A/B/C/D 类测试 + 复用 helper |
| `py/tests/test_regions.py` | regions 收紧后改期望值（普通 user 403 / developer 200） |
| `frontend/src/views/SettingsPanel.vue` | B-5 前端：地区 Tab 加角色 gate |
| `frontend/src/views/tt/TtSettingsPanel.vue` | B-5 前端：地区 Tab 加角色 gate |
| `frontend/src/views/fb/FbSettingsPanel.vue` | B-5 前端：地区卡加角色 gate（需引入 authStore） |
| `frontend/src/views/fb/FbProductPanel.vue` | B-5 前端：隐式新增地区前判角色 |
| `frontend/src/views/tt/TtProductPanel.vue` | B-5 前端：隐式新增地区前判角色 |
| `docs/superpowers/auth-matrix.md` | **新建**：全站鉴权矩阵表（交付物） |

**测试共享 helper**（`test_security_hardening.py` 顶部自带，从 `test_huguan_role.py` 复制）：

```python
import database


def _create_user(client, username, role="user", platform="gg", created_by=None):
    """注册用户 → 直接改写 role/platform → 登录，返回 (headers, user_id)。"""
    client.post("/api/auth/register", json={"username": username, "password": "test123"})
    db = database.get_db()
    db.execute("UPDATE users SET role=?, platform=?, created_by=? WHERE username=?",
               (role, platform, created_by, username))
    db.commit()
    row = db.execute("SELECT id FROM users WHERE username=?", (username,)).fetchone()
    db.close()
    resp = client.post("/api/auth/login", json={"username": username, "password": "test123"})
    token = resp.get_json().get("access_token", "")
    return {"Authorization": f"Bearer {token}"}, row["id"]


def _mk_account(db, owner_id, account_id, name="测试账户"):
    db.execute("INSERT INTO accounts(name, account_id, owner_id) VALUES(?,?,?)",
               (name, account_id, owner_id))
    db.commit()


def _mk_fb_pixel_bm(db, owner_id, bm_id, name="像素BM"):
    """建一条像素BM（像素归属由父表 fb_pixel_bms.owner_id 决定），返回其 id。"""
    db.execute("INSERT INTO fb_pixel_bms(name, bm_id, owner_id) VALUES(?,?,?)", (name, bm_id, owner_id))
    db.commit()
    return db.execute("SELECT id FROM fb_pixel_bms WHERE bm_id=?", (bm_id,)).fetchone()["id"]


def _mk_fb_pixel(db, pixel_bm_id, pixel_id, name="像素"):
    db.execute("INSERT INTO fb_pixels(pixel_bm_id, pixel_name, pixel_id) VALUES(?,?,?)",
               (pixel_bm_id, name, pixel_id))
    db.commit()
```

---

### Task 1: A 类 — 10 条路由补 `@jwt_required()`

**Files:**
- Modify: `py/main.py`（10 处装饰器）
- Test: `py/tests/test_security_hardening.py`（新建）

**Interfaces:**
- Consumes: 无（首个任务）。
- Produces: 10 条路由未登录访问返回 401；已登录 `user` 行为与改动前一致。

- [ ] **Step 1: 写失败测试**

在 `py/tests/test_security_hardening.py` 中写入：

```python
"""安全加固测试 — A/B/C/D 类缺陷收口。"""
import pytest


ANON_GET_ENDPOINTS = [
    "/api/fonts/list",
    "/api/fonts/preview",
    "/api/fonts/file/simhei",
    "/api/google-sheets/status",
]

ANON_POST_ENDPOINTS = [
    ("/api/fonts/mark-used", {"font": "simhei"}),
    ("/api/fonts/import", {}),
    ("/api/fonts/upload", {}),
    ("/api/google-ads/accounts", {}),
    ("/api/google-ads/report", {}),
    ("/api/translate", {"text": "hello"}),
]


class TestAClassAnon:
    @pytest.mark.parametrize("path", ANON_GET_ENDPOINTS)
    def test_get_requires_login(self, client, path):
        resp = client.get(path)
        assert resp.status_code == 401

    @pytest.mark.parametrize("path,body", ANON_POST_ENDPOINTS)
    def test_post_requires_login(self, client, path, body):
        resp = client.post(path, json=body)
        assert resp.status_code == 401


class TestAClassLoggedIn:
    def test_fonts_list_ok_when_logged_in(self, client, auth_headers):
        resp = client.get("/api/fonts/list", headers=auth_headers)
        assert resp.status_code == 200
        assert resp.get_json()["success"] is True

    def test_translate_still_validates_when_logged_in(self, client, auth_headers):
        # 登录后空 text 仍返回 400（证明鉴权在前、业务校验在后，行为未变）
        resp = client.post("/api/translate", json={}, headers=auth_headers)
        assert resp.status_code == 400
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd py && python -m pytest tests/test_security_hardening.py::TestAClassAnon -v`
Expected: FAIL — 未登录请求返回 200/400/404 而非 401。

- [ ] **Step 3: 实现 — 给 10 条路由补装饰器**

在 `py/main.py` 的 10 条路由上，紧贴 `@app.route(...)` 之下加 `@jwt_required()`。改动后装饰器栈如下（函数体**不动**）：

```python
@app.route("/api/fonts/list", methods=["GET"])
@jwt_required()
def fonts_list():
    ...

@app.route("/api/fonts/mark-used", methods=["POST"])
@jwt_required()
def fonts_mark_used():
    ...

@app.route("/api/fonts/preview", methods=["GET"])
@jwt_required()
def fonts_preview():
    ...

@app.route("/api/fonts/file/<font_id>", methods=["GET"])
@jwt_required()
def fonts_file(font_id):
    ...

@app.route("/api/fonts/import", methods=["POST"])
@jwt_required()
def fonts_import():
    ...

@app.route("/api/fonts/upload", methods=["POST"])
@jwt_required()
def fonts_upload():
    ...

@app.route("/api/google-ads/accounts", methods=["POST"])
@jwt_required()
def google_ads_accounts():
    ...

@app.route("/api/google-ads/report", methods=["POST"])
@jwt_required()
def google_ads_report():
    ...

@app.route("/api/google-sheets/status", methods=["GET"])
@jwt_required()
def google_sheets_status():
    ...

@app.route("/api/translate", methods=["POST"])
@jwt_required()
def translate_text():
    ...
```

> `@jwt_required` 已由 `py/main.py` 顶部 `from flask_jwt_extended import jwt_required` 导入，无需新增 import。

- [ ] **Step 4: 跑测试确认通过**

Run: `cd py && python -m pytest tests/test_security_hardening.py -v`
Expected: PASS（A 类匿名 401 + 登录后行为不变）。

- [ ] **Step 5: Commit**

```bash
git add py/main.py py/tests/test_security_hardening.py
git commit -m "fix: A 类 10 条无鉴权路由补 @jwt_required()"
```

---

### Task 2: A 类 — 3 条文件路由路径白名单

**Files:**
- Modify: `py/main.py`（`scrape_download`、`serve_font_file` 加白名单；`serve_image` 不改代码）
- Test: `py/tests/test_security_hardening.py`

**Interfaces:**
- Consumes: Task 1 已建的测试文件与 `client` fixture。
- Produces: `scrape_download` / `serve_font_file` 拒绝白名单外路径；`serve_image` 保持既有白名单行为并有测试钉住。

- [ ] **Step 1: 写失败测试**

在 `test_security_hardening.py` 追加：

```python
class TestAClassFileWhitelist:
    def test_scrape_download_rejects_path_outside_scrape_dir(self, client, auth_headers):
        # 白名单外目录（系统目录）必须被拒，且不能被匿名打包
        resp = client.get("/api/scrape/download?path=C:\\Windows", headers=auth_headers)
        assert resp.status_code in (403, 404)

    def test_scrape_download_requires_existing_dir(self, client, auth_headers):
        resp = client.get("/api/scrape/download?path=C:\\nonexistent\\dir", headers=auth_headers)
        assert resp.status_code == 404

    def test_font_file_rejects_non_font_file(self, client, auth_headers):
        # 任意存在的文件（非字体扩展名）必须被拒
        import tempfile, os
        fd, fp = tempfile.mkstemp(suffix=".txt")
        try:
            os.write(fd, b"secret")
            os.close(fd)
            resp = client.get(f"/api/font-file?path={fp}", headers=auth_headers)
            assert resp.status_code in (403, 404)
        finally:
            os.unlink(fp)

    def test_serve_image_still_rejects_non_png(self, client):
        # serve_image 已有 _is_safe_path + .png 双闸门，匿名端点白名单行为钉住
        resp = client.get("/api/image?path=C:\\Windows\\win.ini")
        assert resp.status_code == 404
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd py && python -m pytest tests/test_security_hardening.py::TestAClassFileWhitelist -v`
Expected: FAIL — `scrape_download` 返回 200（打包 Windows 目录）、`font-file` 返回 200（读任意文件）。

- [ ] **Step 3: 实现 — 两条路由加白名单**

**`scrape_download`**（`py/main.py:566`）：加 `@jwt_required(optional=True)` + `_SCRAPE_DEFAULT_DIR` 白名单：

```python
@app.route("/api/scrape/download", methods=["GET"])
@jwt_required(optional=True)
def scrape_download():
    """将爬取的图片目录打包为 zip 下载。"""
    path = request.args.get("path", "").strip()
    if not path or not os.path.isdir(path):
        return jsonify({"success": False, "error": "目录不存在"}), 404
    # 白名单：只允许 _SCRAPE_DEFAULT_DIR 内的目录打包（路径穿越防护）
    real = os.path.realpath(path)
    scrape_real = os.path.realpath(_SCRAPE_DEFAULT_DIR)
    if not (real == scrape_real or real.startswith(scrape_real + os.sep)):
        return jsonify({"success": False, "error": "目录不存在"}), 404
    pkg_name = os.path.basename(path)
    # ……（后续打包逻辑不变）
```

**`serve_font_file`**（`py/main.py:1658`）：加字体扩展名 + 目录双白名单：

```python
@app.route("/api/font-file", methods=["GET"])
def serve_font_file():
    """提供字体文件，供前端 CSS 预览加载。"""
    path = request.args.get("path", "").strip()
    if not path or not os.path.isfile(path):
        return "", 404
    # 扩展名白名单：只允许字体文件
    if not path.lower().endswith((".ttf", ".otf", ".ttc", ".woff", ".woff2")):
        return "", 404
    # 目录白名单：只允许 _FONTS_DIR 与系统字体目录（_scan_fonts_dir 返回的两类来源）
    real = os.path.realpath(path)
    allowed_dirs = [
        os.path.realpath(_FONTS_DIR),
        os.path.realpath(os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "Fonts")),
    ]
    if not any(real == d or real.startswith(d + os.sep) for d in allowed_dirs):
        return "", 403
    mt = "font/ttf" if path.lower().endswith('.ttf') else "font/otf"
    return send_file(path, mimetype=mt)
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd py && python -m pytest tests/test_security_hardening.py::TestAClassFileWhitelist -v`
Expected: PASS。

- [ ] **Step 5: Commit**

```bash
git add py/main.py py/tests/test_security_hardening.py
git commit -m "fix: scrape/download 与 font-file 加路径白名单，堵路径穿越/任意文件读取"
```

---

### Task 3: B-1 — GG 三个写端点归属校验

**Files:**
- Modify: `py/main.py`（`accounts_update`、`accounts_reassign`、`accounts_batch_update`）
- Test: `py/tests/test_security_hardening.py`

**Interfaces:**
- Consumes: `_cross_user_actor`（`py/main.py:3673`，已存在）、测试 helper `_create_user`/`_mk_account`。
- Produces: 普通 `user` 改/转移/批量改他人账户 → 403 且数据不变；改自己 → 200；跨用户角色 → 200。

- [ ] **Step 1: 写失败测试**

在 `test_security_hardening.py` 追加：

```python
class TestB1GgWriteOwnership:
    def _mk_owned_account(self, client, owner_uid, account_id):
        db = database.get_db()
        _mk_account(db, owner_uid, account_id, "账户")
        aid = db.execute("SELECT id FROM accounts WHERE account_id=?", (account_id,)).fetchone()["id"]
        db.close()
        return aid

    def test_user_cannot_update_others_account(self, client):
        _, owner_uid = _create_user(client, "_b1_owner", role="user")
        att, _ = _create_user(client, "_b1_att", role="user")
        aid = self._mk_owned_account(client, owner_uid, "GG-B1-1")
        resp = client.put(f"/api/accounts/{aid}", json={"name": "被篡改"}, headers=att)
        assert resp.status_code == 403
        db = database.get_db()
        name = db.execute("SELECT name FROM accounts WHERE id=?", (aid,)).fetchone()["name"]
        db.close()
        assert name == "账户"   # 数据未变

    def test_user_can_update_own_account(self, client):
        owner_hdr, owner_uid = _create_user(client, "_b1_owner2", role="user")
        aid = self._mk_owned_account(client, owner_uid, "GG-B1-2")
        resp = client.put(f"/api/accounts/{aid}", json={"name": "改名成功"}, headers=owner_hdr)
        assert resp.status_code == 200

    def test_developer_can_update_others_account(self, client):
        _, owner_uid = _create_user(client, "_b1_owner3", role="user")
        dev, _ = _create_user(client, "_b1_dev", role="developer")
        aid = self._mk_owned_account(client, owner_uid, "GG-B1-3")
        resp = client.put(f"/api/accounts/{aid}", json={"name": "代改"}, headers=dev)
        assert resp.status_code == 200

    def test_user_cannot_reassign_others_account(self, client):
        _, owner_uid = _create_user(client, "_b1_owner4", role="user")
        att, _ = _create_user(client, "_b1_att4", role="user")
        aid = self._mk_owned_account(client, owner_uid, "GG-B1-4")
        resp = client.put(f"/api/accounts/{aid}/reassign", json={}, headers=att)
        assert resp.status_code == 403

    def test_user_cannot_batch_update_others_account(self, client):
        _, owner_uid = _create_user(client, "_b1_owner5", role="user")
        att, _ = _create_user(client, "_b1_att5", role="user")
        aid = self._mk_owned_account(client, owner_uid, "GG-B1-5")
        resp = client.post("/api/accounts/batch-update", json={"ids": [aid], "field": "timezone", "value": "UTC+9"}, headers=att)
        assert resp.status_code == 403
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd py && python -m pytest tests/test_security_hardening.py::TestB1GgWriteOwnership -v`
Expected: FAIL — 越权写返回 200 而非 403。

- [ ] **Step 3: 实现 — 三处归属校验**

**`accounts_update`**（`py/main.py:4234`）在 `try` 块内、`user_id` 之后、`old_status` 查询之前插入：

```python
    db = _yt_db()
    try:
        user_id = int(get_jwt_identity())
        # 归属校验：非跨用户角色只能操作自己的账户
        ac = db.execute("SELECT owner_id FROM accounts WHERE id=?", (aid,)).fetchone()
        if not ac or (ac["owner_id"] != user_id and not _cross_user_actor(user_id)):
            return jsonify({"success": False, "error": "账户不存在或无权操作"}), 403
        old_status = db.execute(
```

**`accounts_reassign`**（`py/main.py:4386`）在 `if not existing` 之后插入：

```python
        if not existing:
            db.close()
            return jsonify({"success": False, "error": "账户不存在"}), 404
        # 归属校验：非跨用户角色不能转移他人账户
        if int(existing["owner_id"] or 0) != user_id and not _cross_user_actor(user_id):
            db.close()
            return jsonify({"success": False, "error": "无权转移该账户"}), 403
        if int(existing["owner_id"] or 0) == target_owner:
```

**`accounts_batch_update`**（`py/main.py:4601`）在 `user_id = int(get_jwt_identity())` 之后、`for aid in ids:` 之前插入：

```python
        user_id = int(get_jwt_identity())
        # 归属校验：非跨用户角色批量改时，ids 必须全部属于自己（任一越权即整体拒绝）
        if not _cross_user_actor(user_id) and ids:
            placeholders = ",".join("?" for _ in ids)
            owned = db.execute(
                f"SELECT COUNT(*) FROM accounts WHERE id IN ({placeholders}) AND owner_id=?",
                (*ids, user_id)
            ).fetchone()[0]
            if owned != len(ids):
                return jsonify({"success": False, "error": "包含无权操作的账户"}), 403
        new_clear_rows = []
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd py && python -m pytest tests/test_security_hardening.py::TestB1GgWriteOwnership -v`
Expected: PASS。

- [ ] **Step 5: Commit**

```bash
git add py/main.py py/tests/test_security_hardening.py
git commit -m "fix: GG 三个写端点补归属校验，堵越权改/转移/批量改"
```

---

### Task 4: B-2 — `fb_pixels` 租户隔离

**Files:**
- Modify: `py/routes/fb_routes.py`（`list_all_pixels`）
- Test: `py/tests/test_security_hardening.py`

**Interfaces:**
- Consumes: `CROSS_USER_ROLES`、`_get_role`、`get_uid`（`fb_routes.py` 内已有）；测试 helper `_mk_fb_pixel_bm`/`_mk_fb_pixel`。
- Produces: 普通 `fb` 用户列表只含自己的像素（有「必须被排除」的对照行）；跨用户角色仍看全库。

- [ ] **Step 1: 写失败测试**

在 `test_security_hardening.py` 追加：

```python
class TestB2FbPixelsIsolation:
    def test_regular_fb_user_sees_only_own_pixels(self, client):
        hdr, u1 = _create_user(client, "_b2_u1", role="user", platform="fb")
        _, u2 = _create_user(client, "_b2_u2", role="user", platform="fb")
        db = database.get_db()
        pbm1 = _mk_fb_pixel_bm(db, u1, "PBM-B2-1", "U1的像素BM")
        pbm2 = _mk_fb_pixel_bm(db, u2, "PBM-B2-2", "U2的像素BM")
        _mk_fb_pixel(db, pbm1, "PX-B2-1", "U1的像素")
        _mk_fb_pixel(db, pbm2, "PX-B2-2", "U2的像素")
        db.close()
        resp = client.get("/api/fb/pixels/list?size=50", headers=hdr)
        ids = {p["pixel_id"] for p in resp.get_json()["items"]}
        assert ids == {"PX-B2-1"}      # 只含自己，不含 U2 的像素（对照行必需）

    def test_developer_still_sees_all_pixels(self, client):
        _, u1 = _create_user(client, "_b2_d_u1", role="user", platform="fb")
        _, u2 = _create_user(client, "_b2_d_u2", role="user", platform="fb")
        db = database.get_db()
        pbm1 = _mk_fb_pixel_bm(db, u1, "PBM-B2D-1", "D-U1的BM")
        pbm2 = _mk_fb_pixel_bm(db, u2, "PBM-B2D-2", "D-U2的BM")
        _mk_fb_pixel(db, pbm1, "PX-B2D-1", "D-U1像素")
        _mk_fb_pixel(db, pbm2, "PX-B2D-2", "D-U2像素")
        db.close()
        dev, _ = _create_user(client, "_b2_d_dev", role="developer", platform="fb")
        resp = client.get("/api/fb/pixels/list?size=50", headers=dev)
        ids = {p["pixel_id"] for p in resp.get_json()["items"]}
        assert ids == {"PX-B2D-1", "PX-B2D-2"}
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd py && python -m pytest tests/test_security_hardening.py::TestB2FbPixelsIsolation -v`
Expected: FAIL — 普通 fb 用户列表含 U2 的像素（集合不等）。

- [ ] **Step 3: 实现 — `list_all_pixels` 非跨用户分支补归属过滤**

`py/routes/fb_routes.py` 的 `list_all_pixels`（约 933-945 行）改为：

```python
    where = []
    params = []
    uid = get_uid()
    role = _get_role(db, uid)
    cross_user = role in CROSS_USER_ROLES
    # 跨用户角色可用 owner_id 收窄；非跨用户角色强制只看自己的像素（像素归属由父表 fb_pixel_bms.owner_id 决定）
    owner_filter = (request.args.get('owner_id') or '').strip() if cross_user else ''
    if cross_user:
        if owner_filter:
            where.append("p.pixel_bm_id IN (SELECT id FROM fb_pixel_bms WHERE owner_id = ?)")
            params.append(owner_filter)
    else:
        where.append("p.pixel_bm_id IN (SELECT id FROM fb_pixel_bms WHERE owner_id = ?)")
        params.append(uid)
    if search:
        where.append("(p.pixel_name LIKE ? OR p.pixel_id LIKE ?)")
        params.extend([f"%{search}%", f"%{search}%"])
    where_clause = " AND ".join(where) if where else "1=1"
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd py && python -m pytest tests/test_security_hardening.py::TestB2FbPixelsIsolation tests/test_huguan_role.py::TestListOwnerFilterCrossUser -v`
Expected: PASS（新测试 + 既有户管纯增量对照均通过；既有 `test_fb_user_sees_same_rows_with_or_without_owner_param` 修复后仍绿）。

- [ ] **Step 5: Commit**

```bash
git add py/routes/fb_routes.py py/tests/test_security_hardening.py
git commit -m "fix: fb_pixels 列表对非跨用户角色做租户隔离"
```

---

### Task 5: B-4 — TT 代理改名/删除归属校验

**Files:**
- Modify: `py/main.py`（`agents_rename`、`agents_delete` 的 `platform == "tt"` 分支）
- Test: `py/tests/test_security_hardening.py`

**Interfaces:**
- Consumes: `GLOBAL_OPTION_ROLES`；测试 helper `_create_user`。
- Produces: 非跨用户角色只能改/删自己的 TT 代理；跨用户角色可操作任意 TT 代理。

- [ ] **Step 1: 写失败测试**

在 `test_security_hardening.py` 追加：

```python
class TestB4TtAgentOwnership:
    def _setup(self, client):
        _, owner = _create_user(client, "_b4_owner", role="user", platform="tt")
        db = database.get_db()
        db.execute("INSERT INTO agents(name, owner_id, platform) VALUES('TT代理A', ?, 'tt')", (owner,))
        aid = db.execute("SELECT id FROM agents WHERE name='TT代理A'").fetchone()["id"]
        db.close()
        return owner, aid

    def test_tt_user_cannot_rename_others_agent(self, client):
        owner, aid = self._setup(client)
        hdr, _ = _create_user(client, "_b4_att", role="user", platform="tt")
        resp = client.put(f"/api/agents/{aid}?platform=tt", json={"name": "被改名"}, headers=hdr)
        assert resp.status_code == 404
        db = database.get_db()
        name = db.execute("SELECT name FROM agents WHERE id=?", (aid,)).fetchone()["name"]
        db.close()
        assert name == "TT代理A"

    def test_tt_user_cannot_delete_others_agent(self, client):
        owner, aid = self._setup(client)
        hdr, _ = _create_user(client, "_b4_att2", role="user", platform="tt")
        resp = client.delete(f"/api/agents/{aid}?platform=tt", headers=hdr)
        assert resp.status_code == 404
        db = database.get_db()
        row = db.execute("SELECT 1 FROM agents WHERE id=?", (aid,)).fetchone()
        db.close()
        assert row is not None

    def test_developer_can_rename_any_tt_agent(self, client):
        owner, aid = self._setup(client)
        dev, _ = _create_user(client, "_b4_dev", role="developer")
        resp = client.put(f"/api/agents/{aid}?platform=tt", json={"name": "代改名"}, headers=dev)
        assert resp.status_code == 200
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd py && python -m pytest tests/test_security_hardening.py::TestB4TtAgentOwnership -v`
Expected: FAIL — 越权改名/删除返回 200 而非 404。

- [ ] **Step 3: 实现 — TT 分支补 owner 校验**

**`agents_rename`**（`py/main.py:5920`）`if platform == "tt":` 分支改为：

```python
    if platform == "tt":
        if is_dev:
            row = db.execute("SELECT id FROM agents WHERE id=? AND platform='tt'", (aid,)).fetchone()
        else:
            row = db.execute("SELECT id FROM agents WHERE id=? AND platform='tt' AND owner_id=?", (aid, user_id)).fetchone()
    elif is_dev:
        row = db.execute("SELECT id, owner_id FROM agents WHERE id=?", (aid,)).fetchone()
    else:
        row = db.execute("SELECT id FROM agents WHERE id=? AND owner_id=?", (aid, user_id)).fetchone()
```

**`agents_delete`**（`py/main.py:5967`）`if platform == "tt":` 分支改为：

```python
    if platform == "tt":
        if is_dev:
            row = db.execute("SELECT id FROM agents WHERE id=? AND platform='tt'", (aid,)).fetchone()
        else:
            row = db.execute("SELECT id FROM agents WHERE id=? AND platform='tt' AND owner_id=?", (aid, user_id)).fetchone()
    elif is_dev:
        row = db.execute("SELECT id FROM agents WHERE id=?", (aid,)).fetchone()
    else:
        row = db.execute("SELECT id FROM agents WHERE id=? AND owner_id=?", (aid, user_id)).fetchone()
```

> 注：`is_dev` 已在两函数内定义为 `user and user.get("role") in GLOBAL_OPTION_ROLES`，与 `_cross_user_actor` 语义一致（二者常量值相同），无需额外 import。

- [ ] **Step 4: 跑测试确认通过**

Run: `cd py && python -m pytest tests/test_security_hardening.py::TestB4TtAgentOwnership -v`
Expected: PASS。

- [ ] **Step 5: Commit**

```bash
git add py/main.py py/tests/test_security_hardening.py
git commit -m "fix: TT 代理改名/删除补归属校验"
```

---

### Task 6: B-5 — regions 收紧（后端 + 前端 + 测试）

**Files:**
- Modify: `py/main.py`（`regions_create_api`、`regions_update_api`、`regions_delete_api` 加角色判定）
- Modify: `py/tests/conftest.py`（新增 `dev_headers` fixture）
- Modify: `py/tests/test_regions.py`（收紧后期望值）
- Modify: `frontend/src/views/SettingsPanel.vue`、`frontend/src/views/tt/TtSettingsPanel.vue`、`frontend/src/views/fb/FbSettingsPanel.vue`、`frontend/src/views/fb/FbProductPanel.vue`、`frontend/src/views/tt/TtProductPanel.vue`

**Interfaces:**
- Consumes: `GLOBAL_OPTION_ROLES`（`py/main.py:39` 已导入）；前端 `useAuthStore` 的 `canManageAccounts` getter（`['developer','admin','huguan']`，与 `GLOBAL_OPTION_ROLES` 对齐）。
- Produces: 普通 `user` 对 regions create/update/delete 收 403；`developer`/`admin`/`huguan` 收 200；`list` 仍对所有登录用户开放。前端普通用户看不到「新增/删除地区」入口，保存产品时不再隐式创建地区。

- [ ] **Step 1: 加 `dev_headers` fixture + 写失败测试**

**conftest.py** 在 `tt_headers` 之后新增：

```python
@pytest.fixture
def dev_headers(client):
    """创建 developer 角色测试用户并返回带 JWT token 的请求头。"""
    client.post("/api/auth/register", json={
        "username": "devuser", "password": "test123",
    })
    db = database.get_db()
    db.execute("UPDATE users SET role='developer' WHERE username='devuser'")
    db.commit()
    db.close()
    resp = client.post("/api/auth/login", json={
        "username": "devuser", "password": "test123",
    })
    token = resp.get_json().get("access_token", "")
    return {"Authorization": f"Bearer {token}"}
```

**test_regions.py**：把 `TestRegionsUpdate.test_update_timezone`、`TestRegionsCreate.test_create_new_region`、`TestRegionsDelete.test_delete_region` 三个「成功操作」用例的 `auth_headers` 改为 `dev_headers`；并新增一个 403 测试类：

```python
class TestRegionsForbiddenForRegularUser:
    """B-5：regions 写操作收紧到 GLOBAL_OPTION_ROLES，普通 user 一律 403。"""

    def test_regular_user_cannot_create(self, client, auth_headers):
        resp = client.post("/api/regions/create",
                           json={"name": "越权地区", "timezone": "UTC"},
                           headers=auth_headers)
        assert resp.status_code == 403

    def test_regular_user_cannot_update(self, client, auth_headers):
        resp = client.get("/api/regions/list", headers=auth_headers)
        rid = resp.get_json()["regions"][0]["id"]
        resp = client.put(f"/api/regions/{rid}", json={"timezone": "UTC-0"}, headers=auth_headers)
        assert resp.status_code == 403

    def test_regular_user_cannot_delete(self, client, auth_headers):
        resp = client.get("/api/regions/list", headers=auth_headers)
        rid = resp.get_json()["regions"][0]["id"]
        resp = client.delete(f"/api/regions/{rid}", headers=auth_headers)
        assert resp.status_code == 403

    def test_regular_user_can_still_list(self, client, auth_headers):
        # list 对普通用户仍开放（产品表单需要读地区）
        resp = client.get("/api/regions/list", headers=auth_headers)
        assert resp.status_code == 200
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd py && python -m pytest tests/test_regions.py -v`
Expected: FAIL — `TestRegionsForbiddenForRegularUser` 三个用例返回 200 而非 403。

- [ ] **Step 3: 实现 — 后端三个 regions 写接口加角色判定**

`regions_update_api` / `regions_create_api` / `regions_delete_api`（`py/main.py:10191-10220`）各在函数体开头加：

```python
def regions_update_api(region_id):
    """更新地区时区。"""
    user = auth.get_user_by_id(int(get_jwt_identity()))
    if not user or user.get("role") not in GLOBAL_OPTION_ROLES:
        return jsonify({"success": False, "error": "权限不足"}), 403
    data = request.get_json(silent=True) or {}
    ...

def regions_create_api():
    """新增地区。"""
    user = auth.get_user_by_id(int(get_jwt_identity()))
    if not user or user.get("role") not in GLOBAL_OPTION_ROLES:
        return jsonify({"success": False, "error": "权限不足"}), 403
    platform = _get_effective_platform()
    ...

def regions_delete_api(region_id):
    """删除地区。"""
    user = auth.get_user_by_id(int(get_jwt_identity()))
    if not user or user.get("role") not in GLOBAL_OPTION_ROLES:
        return jsonify({"success": False, "error": "权限不足"}), 403
    database.regions_delete(region_id)
    return jsonify({"success": True})
```

> `regions_list_api` 不改（普通用户仍需读地区列表）。

- [ ] **Step 4: 实现 — 前端 5 组件权限 gate**

**（a）`SettingsPanel.vue`（GG）**：地区 Tab（约 108-163）的「新增地区」div（154-161）与删除按钮（138-147）加 `v-if="authStore.canManageAccounts"`。

```html
<!-- 新增地区入口：仅 developer/admin/huguan 可见 -->
<div v-if="authStore.canManageAccounts" style="display:flex;align-items:center;gap:12px;padding:10px 12px;background:#f9fafb;border-radius:6px;margin-top:8px;">
  <el-input v-model="newRegionName" placeholder="新地区名" size="small" style="flex:0 0 100px;" @keyup.enter="addRegion" />
  <el-select v-model="newRegionTz" placeholder="时区" size="small" style="flex:1;" filterable>
    <el-option v-for="tz in timezoneOptions" :key="tz" :label="tz" :value="tz" />
  </el-select>
  <el-button size="small" type="primary" @click="addRegion">新增</el-button>
</div>
```

删除按钮（138-147）加 `v-if="authStore.canManageAccounts"`。

**（b）`TtSettingsPanel.vue`**：地区 Tab（168-223）新增入口（214-221）与删除按钮加 `v-if="isAdmin || authStore.isHuguan"`（该组件已有 `isAdmin` computed）。

**（c）`FbSettingsPanel.vue`**：该组件**无 authStore**。在 `<script setup>` 加：

```js
import { useAuthStore } from '../../stores/auth'
const authStore = useAuthStore()
```

新增入口 div（18-22）与删除入口（27-31）加 `v-if="authStore.canManageAccounts"`。

**（d）`FbProductPanel.vue`** 隐式新增（346-350）改为：

```js
if (form.region && !regionOptions.value.some(r => (typeof r === 'string' ? r : r.name) === form.region)) {
    if (!auth.canManageAccounts) {
        ElMessage.error('无权限新增地区，请选择已有地区')
        return
    }
    await client.post('/regions/create', { name: form.region, timezone: '' })
    try { const r = await client.get('/regions/list'); regionOptions.value = (r.regions || []).map(r => typeof r === 'string' ? { name: r } : r) } catch(e) {}
}
```

（该组件已有 `const auth = useAuthStore()`；需确认已 `import { ElMessage }`，若无则补。）

**（e）`TtProductPanel.vue`** 隐式新增（181-184）改为：

```js
if (form.region && !regionOptions.value.some(r => r.name === form.region)) {
    if (!auth.canManageAccounts) {
        ElMessage.error('无权限新增地区，请选择已有地区')
        return
    }
    await client.post('/regions/create', { name: form.region, timezone: '' })
    try { const r = await client.get('/regions/list'); regionOptions.value = (r.regions || []).map(r => typeof r === 'string' ? { name: r } : r) } catch(e) {}
}
```

- [ ] **Step 5: 跑测试确认通过 + 浏览器抽查**

Run: `cd py && python -m pytest tests/test_regions.py -v`
Expected: PASS。

前端无单测，执行后需在浏览器以普通 `user` 登录，确认：设置面板「新增地区/删除」不可见；保存产品填新地区名时收到错误提示而非静默失败。以 `developer` 登录确认功能仍在。

- [ ] **Step 6: Commit**

```bash
git add py/main.py py/tests/conftest.py py/tests/test_regions.py frontend/src/views/SettingsPanel.vue frontend/src/views/tt/TtSettingsPanel.vue frontend/src/views/fb/FbSettingsPanel.vue frontend/src/views/fb/FbProductPanel.vue frontend/src/views/tt/TtProductPanel.vue
git commit -m "feat: regions 写操作收紧到 GLOBAL_OPTION_ROLES，前端隐藏普通用户入口"
```

---

### Task 7: C-1 — `accounts_reassign` 入参校验（非法 owner_id → 400）

**Files:**
- Modify: `py/main.py`（`accounts_reassign` 的 owner_id 解析段）
- Test: `py/tests/test_security_hardening.py`

**Interfaces:**
- Consumes: Task 3 已改的 `accounts_reassign`（已含归属校验）。
- Produces: 上标数字 `"²"`、非数字、不存在的目标用户 → 400（不是 500）。

- [ ] **Step 1: 写失败测试**

在 `test_security_hardening.py` 追加：

```python
class TestC1ReassignInvalidOwner:
    def _setup(self, client):
        dev, dev_id = _create_user(client, "_c1_dev", role="developer")
        db = database.get_db()
        _mk_account(db, dev_id, "GG-C1-1", "C1账户")
        aid = db.execute("SELECT id FROM accounts WHERE account_id='GG-C1-1'").fetchone()["id"]
        db.close()
        return dev, aid

    def test_reassign_superscript_digit_returns_400(self, client):
        dev, aid = self._setup(client)
        resp = client.put(f"/api/accounts/{aid}/reassign", json={"owner_id": "²"}, headers=dev)
        assert resp.status_code == 400

    def test_reassign_nonexistent_user_returns_400(self, client):
        dev, aid = self._setup(client)
        resp = client.put(f"/api/accounts/{aid}/reassign", json={"owner_id": "99999999"}, headers=dev)
        assert resp.status_code == 400

    def test_reassign_valid_user_succeeds(self, client):
        dev, aid = self._setup(client)
        _, target = _create_user(client, "_c1_target", role="user")
        resp = client.put(f"/api/accounts/{aid}/reassign", json={"owner_id": target}, headers=dev)
        assert resp.status_code == 200
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd py && python -m pytest tests/test_security_hardening.py::TestC1ReassignInvalidOwner -v`
Expected: FAIL — `"²"` 触发 500、不存在用户触发 500。

- [ ] **Step 3: 实现 — 严格 ASCII 校验 + 目标用户存在校验**

`accounts_reassign` 的 `owner_id` 解析段（`py/main.py:4374-4377`）改为：

```python
    if actor_role in CROSS_USER_ROLES:
        raw_owner = (data.get("owner_id") or "")
        raw_owner_str = str(raw_owner).strip()
        if raw_owner_str:
            if not (raw_owner_str.isascii() and raw_owner_str.isdigit()):
                return jsonify({"success": False, "error": "owner_id 必须是数字"}), 400
            try:
                target_owner = int(raw_owner_str)
            except (ValueError, OverflowError):
                return jsonify({"success": False, "error": "owner_id 必须是数字"}), 400
    db = _yt_db()
```

并在 `try` 块内、`if not existing` 之后、归属校验**之前**插入目标用户存在校验：

```python
        if not existing:
            db.close()
            return jsonify({"success": False, "error": "账户不存在"}), 404
        # 目标用户存在校验：转移给不存在的用户会触发 FK IntegrityError → 500，改为 400
        if target_owner != user_id:
            if not db.execute("SELECT 1 FROM users WHERE id=?", (target_owner,)).fetchone():
                db.close()
                return jsonify({"success": False, "error": "目标用户不存在"}), 400
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd py && python -m pytest tests/test_security_hardening.py::TestC1ReassignInvalidOwner tests/test_security_hardening.py::TestB1GgWriteOwnership -v`
Expected: PASS（C-1 新测试 + Task 3 的 B-1 归属校验回归均通过）。

- [ ] **Step 5: Commit**

```bash
git add py/main.py py/tests/test_security_hardening.py
git commit -m "fix: accounts_reassign 非法 owner_id 改为 400 并校验目标用户存在"
```

---

### Task 8: C-2 — 用户搜索 SQL 修复

**Files:**
- Modify: `py/auth.py`（`list_users` 的 `search_clause`）
- Test: `py/tests/test_security_hardening.py`

**Interfaces:**
- Consumes: 无（auth.py 的 `list_users` 直接可测）。
- Produces: developer 不带 `platform` 时搜索用户 → 200（不再 SQL 语法错误 500）。

- [ ] **Step 1: 写失败测试**

在 `test_security_hardening.py` 追加：

```python
class TestC2UserSearch:
    def test_developer_search_without_platform_returns_200(self, client):
        dev, _ = _create_user(client, "_c2_dev", role="developer")
        resp = client.get("/api/admin/users?search=foo", headers=dev)
        assert resp.status_code == 200

    def test_developer_search_returns_matching_users(self, client):
        dev, _ = _create_user(client, "_c2_dev2", role="developer")
        _create_user(client, "_c2_match", role="user")
        resp = client.get("/api/admin/users?search=_c2_match", headers=dev)
        assert resp.status_code == 200
        assert any(u["username"] == "_c2_match" for u in resp.get_json()["users"])
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd py && python -m pytest tests/test_security_hardening.py::TestC2UserSearch -v`
Expected: FAIL — developer 搜索触发 500（SQL 语法错误）。

- [ ] **Step 3: 实现 — 空 `where_clause` 时不拼 `AND`**

`py/auth.py` 的 `list_users` 中（约 106 行）：

```python
            search_clause = " AND (username LIKE ? OR display_name LIKE ?)"
```

改为：

```python
            search_clause = (" WHERE " if not where_clause else " AND ") + "(username LIKE ? OR display_name LIKE ?)"
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd py && python -m pytest tests/test_security_hardening.py::TestC2UserSearch -v`
Expected: PASS。

- [ ] **Step 5: Commit**

```bash
git add py/auth.py py/tests/test_security_hardening.py
git commit -m "fix: 用户搜索在空 where 子句时拼接 WHERE 而非 AND"
```

---

### Task 9: D-1/D-2 — 死 delete 清理 + 真实删除计数

**Files:**
- Modify: `py/main.py`（删两处 `_app_cache.delete`；`accounts_batch_delete` 用 rowcount）
- Test: `py/tests/test_security_hardening.py`

**Interfaces:**
- Consumes: 无。
- Produces: `statuses_rename`/`statuses_delete` 不再写死缓存键；`accounts_batch_delete` 返回真实删除条数。

- [ ] **Step 1: 写失败测试**

在 `test_security_hardening.py` 追加：

```python
class TestD2BatchDeleteCount:
    def test_batch_delete_reports_actual_count(self, client):
        dev, dev_id = _create_user(client, "_d2_dev", role="developer")
        db = database.get_db()
        _mk_account(db, dev_id, "GG-D2-1", "D2账户1")
        db.close()
        # 传两个不存在的 id：实际删除数应为 0
        resp = client.post("/api/accounts/batch-delete", json={"ids": [999999, 999998]}, headers=dev)
        assert resp.status_code == 200
        assert resp.get_json()["deleted"] == 0


class TestD1StatusesSmoke:
    """D-1 是纯删除死代码（缓存键从未被 set），无行为变化，用冒烟回归钉住改名/删除流程仍正常。"""

    def test_statuses_rename_delete_still_work(self, client):
        dev, dev_id = _create_user(client, "_d1_dev", role="developer")
        db = database.get_db()
        db.execute("INSERT INTO account_statuses(name, platform, owner_id) VALUES('状态甲','gg',?)", (dev_id,))
        sid = db.execute("SELECT id FROM account_statuses WHERE name='状态甲'").fetchone()["id"]
        db.close()
        resp = client.put(f"/api/statuses/{sid}", json={"name": "状态乙"}, headers=dev)
        assert resp.status_code == 200
        resp = client.delete(f"/api/statuses/{sid}", headers=dev)
        assert resp.status_code == 200
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd py && python -m pytest tests/test_security_hardening.py::TestD2BatchDeleteCount -v`
Expected: FAIL — 返回 `deleted: 2` 而非 0。

- [ ] **Step 3: 实现**

**D-1**：删 `py/main.py:6117` 与 `:6148` 两行 `_app_cache.delete(f"accounts:statuses:{user_id}")`（两函数删除该行后 `user_id` 仍被 `auth.get_user_by_id(user_id)` / `owner_id=?` 使用，无未使用变量）。

**D-2**：`accounts_batch_delete`（`py/main.py:4484-4492`）改为：

```python
        deleted = 0
        for aid in ids:
            cur = db.execute(
                "UPDATE accounts SET deleted_at=datetime('now','localtime'), "
                "updated_at=datetime('now','localtime') "
                f"WHERE id=?{owner_clause} AND deleted_at IS NULL",
                (aid,) if cross_user else (aid, user_id)
            )
            deleted += cur.rowcount
        db.commit()
        return jsonify({"success": True, "deleted": deleted})
```

- [ ] **Step 4: 跑测试确认通过 + 回归**

Run: `cd py && python -m pytest tests/test_security_hardening.py::TestD2BatchDeleteCount tests/test_security_hardening.py::TestD1StatusesSmoke tests/test_huguan_role.py -v`
Expected: PASS。

- [ ] **Step 5: Commit**

```bash
git add py/main.py py/tests/test_security_hardening.py
git commit -m "fix: 清理死缓存 delete，batch-delete 返回真实删除条数"
```

---

### Task 10: 交付物 — 全站鉴权矩阵表

**Files:**
- Create: `docs/superpowers/auth-matrix.md`
- （临时脚本：`py/tests/scan_routes_tmp.py`，跑完即删）

**Interfaces:**
- Consumes: 前 9 个 Task 的成果。
- Produces: 一张 markdown 表，逐端点写明「是否需登录 / 允许角色 / 有无归属校验 / 有无平台门禁 / 备注」。

- [ ] **Step 1: 写一次性扫描脚本**

创建 `py/tests/scan_routes_tmp.py`：

```python
"""一次性只读脚本：扫描所有路由的装饰器栈，生成鉴权矩阵 baseline。跑完即删。"""
import os, re, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import main  # noqa: F401  触发路由注册

rows = []
for rule in main.app.url_map.iter_rules():
    endpoint = rule.endpoint
    path = rule.rule
    methods = ",".join(sorted(m for m in rule.methods if m not in ("HEAD", "OPTIONS")))
    view = main.app.view_functions.get(endpoint)
    src = os.path.abspath(sys.modules[view.__module__].__file__)
    # 读源码，找装饰器栈中的 jwt_required / require_platform / *_required
    with open(src, encoding="utf-8") as f:
        lines = f.readlines()
    # 向上找 decorator 行
    import inspect
    try:
        _, start = inspect.getsourcelines(view)
    except Exception:
        continue
    decos = []
    i = start - 2
    while i >= 0 and (lines[i].lstrip().startswith("@") or not lines[i].strip()):
        s = lines[i].strip()
        if s.startswith("@"):
            decos.append(s)
        i -= 1
    has_jwt = any("jwt_required" in d for d in decos)
    rows.append((methods, path, has_jwt, "; ".join(decos)))

rows.sort(key=lambda r: r[1])
for methods, path, has_jwt, decos in rows:
    print(f"{methods}\t{path}\t{'YES' if has_jwt else 'NO'}\t{decos}")
```

- [ ] **Step 2: 运行扫描生成 baseline**

Run: `cd py && python tests/scan_routes_tmp.py > /tmp/routes_baseline.txt 2>&1`
Expected: 输出所有路由 + 是否 `jwt_required` + 装饰器栈。

- [ ] **Step 3: 人工核对成矩阵表**

把 baseline 结合前 9 个 Task 的结论，整理成 `docs/superpowers/auth-matrix.md`，表头：

| 端点（方法 + 路径） | 是否需登录 | 允许的角色 | 有无归属校验 | 有无平台门禁 | 备注 |

逐端点填写。**已收紧的端点**（A 类 13 条、B-1/B-2/B-4/B-5、C-1/C-2）务必反映修复后的口径。

- [ ] **Step 4: 删除临时脚本**

Run: `rm py/tests/scan_routes_tmp.py /tmp/routes_baseline.txt`
Expected: 删除成功（只读脚本不留存）。

- [ ] **Step 5: Commit**

```bash
git add docs/superpowers/auth-matrix.md
git commit -m "docs: 全站鉴权矩阵表（安全加固交付物）"
```

---

## 验收清单

- [ ] `cd py && python -m pytest tests/ -v` 全绿（含既有 `test_huguan_role.py`、`test_regions.py` 回归）。
- [ ] A 类 13 条：未登录 401 或被白名单拒绝；带 token `user` 行为不变。
- [ ] B-1：普通 `user` 改/转移/批量改他人 GG 账户 → 403 且数据不变；改自己/跨用户角色 → 200。
- [ ] B-2：普通 fb 用户列表只含自己的像素（含对照行）；developer 看全库。
- [ ] B-4：非跨用户角色改/删他人 TT 代理 → 404；跨用户角色 → 200。
- [ ] B-5：普通 `user` regions 写 → 403；`developer` → 200；`list` 仍开放；前端普通用户入口隐藏 + 隐式新增被拦。
- [ ] C-1：上标数字/非数字/不存在用户 → 400（非 500）。
- [ ] C-2：developer 无 platform 搜索 → 200。
- [ ] D-1/D-2：两处死 delete 已删；batch-delete 返回真实条数。
- [ ] 浏览器实测：以普通 `user` 和 `developer` 分别登录，点一遍「设置/产品/地区」相关页面，确认图片/字体/下载/地区功能无静默失效（4.2 最大风险点）。
