# 匿名可达端点收口 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**设计文档**：`docs/superpowers/specs/2026-09-24-anonymous-surface-hardening-design.md`（2026-09-24 已确认）

**Goal:** 把匿名可达 GET 端点从 **14 条**收口到 **7 条**显式白名单；消除 3 条产物下载端点的**匿名可达**。

**Architecture:** 按「是否需按用户区分」分三组：A 组 8 条（装饰器误加 `optional=True`）直接改回强制鉴权；B-1/B-2 经复核**只需改 1 条**（`font-file` 白名单最小化），其余保持匿名；B-3 三条产物下载改为「合法 JWT **或** 未过期签名」二者其一放行，签名 URL 由已有 axios 接口下发。

**Tech Stack:** Flask + flask_jwt_extended 4.7.4、SQLite、Vue 3 + axios（改动仅限下载 URL 来源）

## Global Constraints

以下约束适用于**每一个** Task：

- **纯增量**：只加鉴权/白名单，**不改动既有业务逻辑**。
  - `products_list` 的 runner 过滤逻辑（设计文档 §2.2）**一字不动**
  - `browse-*` 的 `_can_browse()` 闸门**不动**
  - B-3 三条的**路径校验**（目录白名单 / 精确命中 `output_path`）**全部保留**
  - **归属语义不变**：`video_tasks`、`audio_replace_history` 无用户字段，「登录用户可下他人产物」是数据模型如此，**本次不引入归属校验**（设计文档 §4.3 勘误）
- **禁止 `git add -A`**：本仓库常有并行会话在途改文件（`py/huguan_dashboard.py`、`py/tests/test_huguan_dashboard.py` 等）。commit **只 add 本任务文件**，逐个列出路径。
- **行号一律以路由字符串/函数名定位**，不要照抄本计划的 `:NNNN`（并行会话在途改文件，行号随时漂移）。
- **全量测试基线：612 passed**。每个 Task 结束跑全量，**数字以实测为准**，不得照抄估算值。若出现新的失败，如实报告，**不要**把并行会话的红算成本任务引入的回归。
- **前端改动仅限下载 URL 来源**（`window.open` 的参数），不涉及 UI 布局、交互形态或按钮位置 ⇒ **不触发 `/frontend-design`**。
- 每个 Task 完成后必须跑**变异验证**并把**原始输出**贴进报告 —— 本项目已有多次「假绿」教训，**声称变红不算**。

## 前置状态（已就位，勿重复实现）

- **匿名面回归测试已建立**：`py/tests/test_anon_surface.py`，commit `efdd9d8`，2 条测试，当前 **2 passed**。
  白名单 `ANON_GET_WHITELIST` 现有 **14 条** GET。
  ⚠️ 该测试是**双向断言**：收口一个端点后，**必须从白名单删除对应条目**，否则测试会因「白名单已过期」变红。这不是测试在碍事，**这正是它的设计意图**。
- 本计划中每个 Task 的「白名单」变更，**都指** `py/tests/test_anon_surface.py` 里的 `ANON_GET_WHITELIST`。

**白名单收敛路径**：14 →（Task 1）**10** →（Task 4）**7**

**最终保留的 7 条**（即收口完成后仍应匿名可达的）：
`/`、`/<path:filename>`、`/favicon.ico`、`/api/health`、`/api/image`、`/api/font-file`、`/api/audio`

---

### Task 1: A 组 8 条装饰器收口

**Files:**
- Modify: `py/main.py`（7 处装饰器）
- Modify: `py/routes/auth_routes.py`（1 处装饰器）
- Modify: `py/tests/test_anon_surface.py`（白名单删 4 条）
- Test: `py/tests/test_security_hardening.py`（追加测试）

**Interfaces:**
- Consumes: `conftest.py` 既有 fixture `client`、`dev_headers`
- Produces: 无新接口（仅装饰器变更）

**背景**：设计文档 §2.1 的三重证据（同族 16:2、跨平台 TT/FB 均为强制、`reject_viewer` 注释自证作者假定会被拦截）表明这 8 处的 `optional=True` 是**误加**。

- [ ] **Step 1: 写失败测试**

在 `py/tests/test_security_hardening.py` **末尾追加**（文件顶部若无 `import pytest` 需补上）：

```python
class TestA2AnonymousRejected:
    """A 组 8 条：零 token 必须 401。

    收口前本组第 1 条会失败 —— 那正是要钉的行为。
    """

    ANON_CASES = [
        ("get",  "/api/products/list",    None),
        ("post", "/api/products/create",  {"product_name": "anon-probe"}),
        ("get",  "/api/users/names",      None),
        ("get",  "/api/settings/account", None),
        ("get",  "/api/auth/names",       None),
        ("post", "/api/browse-file",      {"path": "x"}),
        ("post", "/api/browse-save",      {"path": "x"}),
        ("post", "/api/browse-folder",    {"path": "x"}),
    ]

    @pytest.mark.parametrize("method,path,payload", ANON_CASES)
    def test_anonymous_is_rejected(self, client, method, path, payload):
        fn = getattr(client, method)
        resp = fn(path, json=payload) if payload is not None else fn(path)
        assert resp.status_code == 401, (
            f"{method.upper()} {path} 对匿名请求返回 {resp.status_code}，应为 401"
        )

    @pytest.mark.parametrize("method,path,payload", ANON_CASES)
    def test_logged_in_is_not_rejected(self, client, dev_headers, method, path, payload):
        """承重对照：带 token 时**不得**是 401（证明只挡匿名，没挡已登录）。

        没有这条，「把 8 个端点改成恒 401」也能让上一条全绿 —— 这正是本项目
        「无对照行的断言 = 假绿」定式。
        """
        fn = getattr(client, method)
        resp = (fn(path, json=payload, headers=dev_headers) if payload is not None
                else fn(path, headers=dev_headers))
        assert resp.status_code != 401, (
            f"{method.upper()} {path} 带 token 仍返回 401 —— 收口过头了"
        )
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd py && python -m pytest tests/test_security_hardening.py::TestA2AnonymousRejected -v`

Expected:
- `test_anonymous_is_rejected` 的 8 条 **FAIL**（返回 200/403/400 而非 401）
- `test_logged_in_is_not_rejected` 的 8 条 **PASS**（回归钉 —— 改前就应通过）

把**原始输出**贴进报告。

- [ ] **Step 3: 改 8 处装饰器**

一律把 `@jwt_required(optional=True)` 改为 `@jwt_required()`，**只改这一行**：

| # | 文件 | 定位锚点（`@app.route` / `@auth_bp.route` 行） | 函数 |
|---|---|---|---|
| 1 | `py/main.py` | `@app.route("/api/products/list", methods=["GET"])` | `products_list` |
| 2 | `py/main.py` | `@app.route("/api/products/create", methods=["POST"])` | `products_create` |
| 3 | `py/main.py` | `@app.route("/api/users/names", methods=["GET"])` | `users_names` |
| 4 | `py/main.py` | `@app.route("/api/settings/account", methods=["GET"])` | `account_settings_get` |
| 5 | `py/main.py` | `@app.route("/api/browse-file", methods=["POST"])` | `browse_file` |
| 6 | `py/main.py` | `@app.route("/api/browse-save", methods=["POST"])` | `browse_save` |
| 7 | `py/main.py` | `@app.route("/api/browse-folder", methods=["POST"])` | `browse_folder` |
| 8 | `py/routes/auth_routes.py` | `@auth_bp.route("/names", methods=["GET"], endpoint="users_names")` | `users_names` |

⚠️ **陷阱**：
- `/api/settings/account` 的 **POST**（`account_settings_save`）**已经是** `@jwt_required()`，**不要动它**。只改 GET 那个（`account_settings_get`）。
- `py/routes/auth_routes.py` 用 `url_prefix="/api/auth"` 拼接，路由字符串是 `"/names"` 不是 `"/api/auth/names"` —— 按 `endpoint="users_names"` 定位。
- **函数体一字不动**。特别是 `products_list` 的 runner 过滤（设计文档 §2.2）。

- [ ] **Step 4: 从白名单删除已收口的 4 条**

在 `py/tests/test_anon_surface.py` 的 `ANON_GET_WHITELIST` 中**删除**这 4 行（连同其行尾注释）：

```
    "/api/products/list",       # main.py:2495，runner=mine 匿名时不过滤 owner ⇒ 读全库产品
    "/api/users/names",         # main.py:7738，无 developer 过滤（与 /api/auth/names 口径不一致）
    "/api/auth/names",          # routes/auth_routes.py:177
    "/api/settings/account",    # main.py:6524，匿名读全局配置 + 全局选项字典
```

并在 `@jwt_required(optional=True)` 那一节的**分组注释**下补一行说明，例如：

```python
    # --- @jwt_required(optional=True)：装饰器层「有鉴权」但匿名放行 ---
    # 2026-09-24：A 组 4 条（products/list、users/names、auth/names、settings/account GET）
    # 已收口为强制鉴权，本表不再列出。
```

⚠️ 这些白名单条目**恰好和 Step 1 的端点是同一批**：`browse-file|save|folder` 是 **POST**，不在 GET 白名单里（白名单只含 GET），所以**只删 4 条不是 8 条**。

- [ ] **Step 5: 跑测试确认通过 + 回归**

Run: `cd py && python -m pytest tests/test_security_hardening.py::TestA2AnonymousRejected tests/test_anon_surface.py -v`

Expected: **全 PASS**。

Run: `cd py && python -m pytest tests/ -q`

Expected: 全绿。**实测数字**应为 `612 + 16 = 628 passed`（本 Task 新增 16 条参数化用例）—— 以**实测**为准，若并行会话另有增减，如实记录差异。

**变异验证（必做，贴原始输出）**：把 `products_list` 的装饰器**临时改回** `@jwt_required(optional=True)`，重跑 `TestA2AnonymousRejected::test_anonymous_is_rejected` ⇒ 对应那条**必须变红**。实测后**立即还原**，并确认：

```bash
md5sum py/main.py     # 还原后应与变异前逐位一致
git status --short py/main.py   # 应为空
```

- [ ] **Step 6: Commit**

```bash
git add py/main.py py/routes/auth_routes.py py/tests/test_security_hardening.py py/tests/test_anon_surface.py
git commit -m "fix(security): 收口 A 组 8 条匿名可达端点（optional=True 误加）"
```

**报告须包含**：8 处改动逐一列出、白名单 14→10、Step 2 与 Step 5 的原始输出、变异验证的原始输出与还原自证（md5）。

---

### Task 2: `/api/font-file` 路径白名单最小化

**Files:**
- Modify: `py/main.py`（`serve_font_file`）
- Test: `py/tests/test_security_hardening.py`（追加测试）

**Interfaces:**
- Consumes: 无
- Produces: 无（仅收紧既有白名单）

**背景**：当前白名单含**整个系统字体目录**（`C:\Windows\Fonts`）⇒ 匿名可读该目录下**任意**字体。而前端实际只需要 `_scan_fonts_dir()` 列出的 **4 个具名文件**。本 Task 把这 4 个文件之外的系统字体挡掉。

⚠️ **不要**移除系统字体目录（会让这 4 个字体预览失效）—— 见设计文档 §4.2 勘误。

- [ ] **Step 1: 写失败测试**

在 `py/tests/test_security_hardening.py` **末尾追加**：

```python
class TestFontFileWhitelistMinimized:
    """`/api/font-file` 只应放行 _scan_fonts_dir() 列出的那 4 个具名系统字体。

    承重对照：**同一目录内**的具名字体必须 200、非具名字体必须 403。
    只测其中一条无法区分「白名单最小化」与「整个系统字体目录被误封」。
    """

    FOUR_NAMED = ("simhei.ttf", "msyh.ttc", "simsun.ttc", "arial.ttf")

    @staticmethod
    def _sys_font_dir():
        return os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "Fonts")

    def test_named_system_font_still_served(self, client):
        """对照行 A：4 个具名字体必须仍可访问（证明没有误封）。"""
        p = os.path.join(self._sys_font_dir(), "arial.ttf")
        if not os.path.isfile(p):
            pytest.skip("本机无 arial.ttf，无法验证对照行 A")
        resp = client.get("/api/font-file", query_string={"path": p})
        assert resp.status_code == 200, (
            f"具名系统字体 arial.ttf 被拒绝（{resp.status_code}）—— 白名单收得过紧，"
            "会打断前端字体预览"
        )

    def test_other_system_font_is_rejected(self, client):
        """对照行 B：同目录内的非具名字体必须 403。"""
        d = self._sys_font_dir()
        if not os.path.isdir(d):
            pytest.skip("本机无系统字体目录，无法验证对照行 B")
        named = {n.lower() for n in self.FOUR_NAMED}
        others = [f for f in os.listdir(d)
                  if f.lower().endswith((".ttf", ".otf", ".ttc"))
                  and f.lower() not in named]
        if not others:
            pytest.skip("系统字体目录内无其它字体可供对照")
        p = os.path.join(d, others[0])
        resp = client.get("/api/font-file", query_string={"path": p})
        assert resp.status_code == 403, (
            f"非具名系统字体 {others[0]} 返回 {resp.status_code}，应为 403 —— "
            "整个系统字体目录仍然匿名可读"
        )

    def test_synthetic_fonts_dir_both_arms(self, client, tmp_path, monkeypatch):
        """承重腿：合成一个 Fonts 目录，**同一目录内**具名字体 200、非具名字体 403。

        为什么必须有这条：上面两条依赖**真实系统字体目录**，环境不满足时双双 skip
        ⇒ 无声通过。而「整个系统字体目录被封」与「白名单最小化」这两种实现，
        在真实环境里未必能同屏对照。这条用 tmp_path 造出受控对照，**永不 skip**。

        依据：`_named_system_fonts()` 在**调用时**读 `SystemRoot`（不是模块导入时缓存），
        所以 monkeypatch.setenv 能生效。
        """
        fake_root = tmp_path
        fake_fonts = fake_root / "Fonts"
        fake_fonts.mkdir()
        named_file = fake_fonts / "arial.ttf"
        other_file = fake_fonts / "unlisted_font.ttf"
        named_file.write_bytes(b"FAKE-NAMED")
        other_file.write_bytes(b"FAKE-OTHER")
        monkeypatch.setenv("SystemRoot", str(fake_root))

        # 对照行 A：具名字体（在 _named_system_fonts() 清单里）⇒ 200
        resp_named = client.get("/api/font-file", query_string={"path": str(named_file)})
        assert resp_named.status_code == 200, (
            f"合成具名字体 arial.ttf 返回 {resp_named.status_code}，应为 200 —— "
            "白名单收得过紧，会打断前端字体预览"
        )

        # 对照行 B：同目录内的非具名字体 ⇒ 403
        resp_other = client.get("/api/font-file", query_string={"path": str(other_file)})
        assert resp_other.status_code == 403, (
            f"合成非具名字体 unlisted_font.ttf 返回 {resp_other.status_code}，应为 403 —— "
            "白名单没有真正最小化，同目录下任意字体仍可读"
        )
```

⚠️ **三条测试互相承重**：只做 B 会把「整个目录被封」误判为成功；只做 A 会把「什么都没改」误判为成功；前两条可能因环境 skip 而无声通过，**第三条（合成目录）是永不 skip 的承重腿**。报告里若出现 skip，必须说明是哪条。

⚠️ **测试用的字体必须是 `.ttf`/`.otf`/`.ttc`**：`serve_font_file` 的**扩展名白名单在目录白名单之前**，用 `.woff` 会得到 404 而非 403，把测试写歪。

- [ ] **Step 2: 跑测试确认失败**

Run: `cd py && python -m pytest tests/test_security_hardening.py::TestFontFileWhitelistMinimized -v`

Expected:
- `test_named_system_font_still_served` **PASS**（改前就通过，回归钉）
- `test_other_system_font_is_rejected` **FAIL**（返回 200）

把**原始输出**贴进报告。若出现 skip，说明本机环境不满足，**如实标注**（并说明是哪一条）。

- [ ] **Step 3: 实现**

分**三小步**做，顺序不可颠倒（先抽公共函数，再让两处共用，最后收紧白名单）。

**3a. 先抽出模块级辅助函数。** 定位 `py/main.py` 的 `def _scan_fonts_dir()`，在**它前面**插入：

```python
def _named_system_fonts():
    """系统字体的 (id, 中文名, 绝对路径) 列表。

    同时供字体列表（_scan_fonts_dir）与 /api/font-file 白名单使用 —— 两处必须同源，
    否则「列表里能看到、但下载被拒」或反之。
    """
    sys_font_dir = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "Fonts")
    return [
        ("simhei", "黑体",   os.path.join(sys_font_dir, "simhei.ttf")),
        ("msyh",   "微软雅黑", os.path.join(sys_font_dir, "msyh.ttc")),
        ("simsun", "宋体",   os.path.join(sys_font_dir, "simsun.ttc")),
        ("arial",  "Arial",  os.path.join(sys_font_dir, "arial.ttf")),
    ]
```

**3b. 让 `_scan_fonts_dir()` 改用它。** 把该函数内联的 `sys_fonts = [ ... ]`（当前硬编码那 4 条）**整块替换**为：

```python
    sys_fonts = _named_system_fonts()
```

⚠️ **纯增量硬要求**：`_scan_fonts_dir()` 的**返回行为必须逐字段不变**（同样的 id/name/path 与顺序，`source` 仍为 `"system"`）。这是**结构改动、零行为变化**。做完先跑一遍既有字体相关测试确认，再往下走。

**3c. 收紧 `serve_font_file` 的白名单。** 定位 `@app.route("/api/font-file", methods=["GET"])`，把当前的目录白名单：

```python
    allowed_dirs = [
        os.path.realpath(_FONTS_DIR),
        os.path.realpath(os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "Fonts")),
    ]
    if not any(real == d or real.startswith(d + os.sep) for d in allowed_dirs):
        return "", 403
```

（变量名/写法可能略有出入，以实际读到的为准）整块替换为：

```python
    # 路径白名单：项目字体目录内的任意字体，或系统字体目录中的**具名**字体。
    # 不再放行整个系统字体目录 —— 前端只需要 _scan_fonts_dir() 列出的那几个文件，
    # 白名单按「实际需要什么」最小化（见 2026-09-24 匿名面收口设计文档 §4.2）。
    real = os.path.realpath(path)
    fonts_real = os.path.realpath(_FONTS_DIR)
    in_project_dir = (real == fonts_real or real.startswith(fonts_real + os.sep))
    if not in_project_dir:
        named_real = {os.path.realpath(p) for _fid, _name, p in _named_system_fonts()}
        if real not in named_real:
            return "", 403
```

⚠️ **保持单一出口**：函数末尾原有的 `mt = ...` 与 `return send_file(path, mimetype=mt)` **一律不动**。本次只替换白名单判定这一段。

- [ ] **Step 4: 跑测试确认通过**

Run: `cd py && python -m pytest tests/test_security_hardening.py::TestFontFileWhitelistMinimized tests/test_anon_surface.py -v`

Expected: **全 PASS**（`/api/font-file` 仍在白名单里，**不要**删它）。

再跑字体相关既有测试（若存在）与全量：

Run: `cd py && python -m pytest tests/ -q`

Expected: 全绿。**实测数字**（本 Task 新增 2 条）以实测为准。

**变异验证（必做，贴原始输出）**：把 `serve_font_file` 的白名单判定**临时改回**原来的 `allowed_dirs`（含整个系统字体目录），重跑 ⇒ `test_other_system_font_is_rejected` **必须变红**。实测后立即还原，用 `md5sum py/main.py` + `git status --short py/main.py` 自证。

- [ ] **Step 5: Commit**

```bash
git add py/main.py py/tests/test_security_hardening.py
git commit -m "fix(security): /api/font-file 白名单最小化到具名系统字体"
```

**报告须包含**：改动前后白名单对比、两条对照测试的原始输出（含 skip 情况）、变异验证原始输出、`_scan_fonts_dir()` 行为未变的证据（既有测试全绿）。

---

### Task 3: 签名 URL 签发/验签工具

**Files:**
- Create: `py/url_signing.py`
- Test: `py/tests/test_url_signing.py`

**Interfaces:**
- Consumes: 无（纯函数，密钥由调用方传入）
- Produces:
  - `sign_query(endpoint: str, path: str, secret: str, ttl: int = 300, now: float | None = None) -> str` —— 返回 `path=...&exp=...&sig=...` 形式的 query 串（已 URL 编码）
  - `verify_query(endpoint: str, path: str, exp: str, sig: str, secret: str, now: float | None = None) -> bool`

**背景**：`<img>` / `<audio>` / `window.open` 这类**浏览器原生请求无法附加 `Authorization` 头**，因此无法走 JWT。签名 URL 由**受 JWT 保护的 axios 接口下发**，把下载权限绑定到「持有有效会话」。全仓**无**现成 HMAC/`itsdangerous` 基建，需新建。

`endpoint` 参与签名，用于防止**签名跨端点复用**（一个下载 URL 不能拿去调另一个端点）。

- [ ] **Step 1: 写失败的测试**

创建 `py/tests/test_url_signing.py`：

```python
"""签名 URL 工具的单测。

全部为纯函数测试，不依赖 Flask app / 数据库。
"""
import time

from url_signing import sign_query, verify_query

SECRET = "unit-test-secret"
EP = "/api/video/download"
PATH = r"D:\data\temp\video\out.mp4"


def _parse(qs):
    """把 sign_query 的输出解析成 dict。"""
    out = {}
    for part in qs.split("&"):
        k, _, v = part.partition("=")
        out[k] = v
    return out


class TestSignVerify:
    def test_valid_signature_verifies(self):
        qs = sign_query(EP, PATH, SECRET)
        p = _parse(qs)
        assert verify_query(EP, PATH, p["exp"], p["sig"], SECRET) is True

    def test_tampered_path_rejected(self):
        """承重：改 path 必须失效（否则签名形同虚设，可下任意文件）。"""
        qs = sign_query(EP, PATH, SECRET)
        p = _parse(qs)
        assert verify_query(EP, r"D:\data\temp\video\OTHER.mp4",
                            p["exp"], p["sig"], SECRET) is False

    def test_tampered_exp_rejected(self):
        """承重：改 exp 必须失效（否则可把过期时间改到 2099 年）。"""
        qs = sign_query(EP, PATH, SECRET)
        p = _parse(qs)
        assert verify_query(EP, PATH, str(int(p["exp"]) + 999999), p["sig"], SECRET) is False

    def test_cross_endpoint_reuse_rejected(self):
        """承重：一个端点的签名不能挪用到另一个端点。"""
        qs = sign_query(EP, PATH, SECRET)
        p = _parse(qs)
        assert verify_query("/api/scrape/download", PATH, p["exp"], p["sig"], SECRET) is False

    def test_wrong_secret_rejected(self):
        qs = sign_query(EP, PATH, SECRET)
        p = _parse(qs)
        assert verify_query(EP, PATH, p["exp"], p["sig"], "other-secret") is False

    def test_expired_rejected(self):
        """过期必须失效。用注入的 now 做确定性测试，不 sleep。"""
        now = 1_000_000.0
        qs = sign_query(EP, PATH, SECRET, ttl=300, now=now)
        p = _parse(qs)
        assert verify_query(EP, PATH, p["exp"], p["sig"], SECRET, now=now + 301) is False
        assert verify_query(EP, PATH, p["exp"], p["sig"], SECRET, now=now + 299) is True

    def test_exp_boundary_is_exclusive(self):
        """钉死 exp 语义：**exp 那一刻本身即失效**（与 JWT 一致）。

        为什么必须有这条：上面 `test_expired_rejected` 用 now±1 对称地绕开了
        等号，因此**无法区分 `<` 与 `<=`** —— 改松改严都全绿、零信号。
        （本计划早先内嵌的就是错的 `exp_i <`，正是这条把它抓住的。）
        """
        now = 1_000_000.0
        qs = sign_query(EP, PATH, SECRET, ttl=300, now=now)
        p = _parse(qs)
        exp = int(p["exp"])  # = 1_000_300

        assert verify_query(EP, PATH, p["exp"], p["sig"], SECRET, now=exp) is False, (
            "now == exp 时签名仍被接受 —— exp 这一刻应已失效"
        )
        assert verify_query(EP, PATH, p["exp"], p["sig"], SECRET, now=exp - 1) is True, (
            "now == exp-1 时签名被拒 —— 有效期右端点被收得过紧"
        )

    def test_missing_fields_rejected(self):
        """缺任一字段 ⇒ False（不得因「空签名匹配空签名」而放行）。"""
        assert verify_query(EP, PATH, "", "", SECRET) is False
        assert verify_query(EP, PATH, "abc", "", SECRET) is False
        assert verify_query(EP, PATH, "", "abc", SECRET) is False

    def test_non_numeric_exp_rejected(self):
        """exp 非数字 ⇒ False，不得抛异常（异常逸出会变成 500）。"""
        qs = sign_query(EP, PATH, SECRET)
        p = _parse(qs)
        assert verify_query(EP, PATH, "not-a-number", p["sig"], SECRET) is False


class TestPathEncoding:
    def test_windows_path_roundtrip(self):
        """Windows 反斜杠路径经 URL 编码后必须能原样还原（本项目路径全为 Windows 形式）。"""
        from urllib.parse import unquote, parse_qs
        qs = sign_query(EP, PATH, SECRET)
        got = parse_qs(qs)["path"][0]
        assert got == PATH
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd py && python -m pytest tests/test_url_signing.py -v`

Expected: **全部 FAIL**，`ModuleNotFoundError: No module named 'url_signing'`。

- [ ] **Step 3: 实现**

创建 `py/url_signing.py`：

```python
"""短时效签名 URL 工具。

## 为什么需要

`<img src>` / CSS `@font-face url()` / `<audio src>` / `window.open()` 这类**浏览器原生请求**，
由渲染引擎发起，**无法附加 `Authorization` 头**，因此走不了 JWT 鉴权。

签名 URL 解决这个问题：由**受 JWT 保护的 axios 接口**下发一个带 HMAC 签名的完整 URL，
前端把它交给浏览器原生请求消费。下载权限因而绑定到「持有有效会话」。

## 安全性质

- `endpoint` 参与签名 ⇒ 一个下载 URL **不能**挪用到另一个端点。
- `path` 参与签名 ⇒ 改路径即失效。
- `exp` 参与签名 ⇒ 不能把过期时间改大。
- 比对用 `hmac.compare_digest` ⇒ 恒定时间，避免时序侧信道。
- 任何字段缺失 / 非数字 / 过期 ⇒ **一律 False**（fail-closed）。
- 默认 TTL 300 秒 —— 短到足以把「URL 被转发」的窗口压到最小。
"""
import hashlib
import hmac
import time
from urllib.parse import quote

DEFAULT_TTL = 300  # 秒


def _digest(endpoint: str, path: str, exp: int, secret: str) -> str:
    payload = f"{endpoint}\n{path}\n{exp}".encode("utf-8")
    return hmac.new(secret.encode("utf-8"), payload, hashlib.sha256).hexdigest()


def sign_query(endpoint: str, path: str, secret: str,
               ttl: int = DEFAULT_TTL, now: float | None = None) -> str:
    """生成签名 query 串：`path=...&exp=...&sig=...`（path 已 URL 编码）。"""
    exp = int((now if now is not None else time.time()) + ttl)
    sig = _digest(endpoint, path, exp, secret)
    return f"path={quote(path)}&exp={exp}&sig={sig}"


def verify_query(endpoint: str, path: str, exp: str, sig: str, secret: str,
                 now: float | None = None) -> bool:
    """校验签名。任何异常情况均返回 False（调用方据此返回 401）。

    ## exp 语义

    `exp` 是**排他**上界，与 JWT 一致：`now >= exp` 即视为已过期。
    有效窗口是 `[签发时刻, exp)` —— `exp` 那一刻**已经失效**。

    刻意与 JWT 对齐：本工具就是 JWT 在「浏览器原生请求」场景下的替代品，
    两处语义若有分歧，后续读代码的人必然错判。
    （2026-09-24 由 4053894 钉死；此处早先写的 `exp_i <` 是错的，已改。）
    """
    if not path or not exp or not sig:
        return False
    try:
        exp_i = int(exp)
    except (TypeError, ValueError):
        return False
    # 用 <= 而非 <：exp 那一刻本身即失效（见 docstring「exp 语义」）。
    if exp_i <= int(now if now is not None else time.time()):
        return False
    return hmac.compare_digest(_digest(endpoint, path, exp_i, secret), sig)
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd py && python -m pytest tests/test_url_signing.py -v`

Expected: **全 PASS**（12 条）。

**变异验证（必做，贴原始输出）**：把 `_digest` 的 payload 去掉 `endpoint`（改成 `f"{path}\n{exp}"`），重跑 ⇒ `test_cross_endpoint_reuse_rejected` **必须变红**。实测后立即还原。

- [ ] **Step 5: Commit**

```bash
git add py/url_signing.py py/tests/test_url_signing.py
git commit -m "feat(security): 新增短时效签名 URL 工具（浏览器原生请求鉴权）"
```

---

### Task 4: B-3 三条端点接入签名 + 三处下发点 + 前端消费点

**Files:**
- Modify: `py/main.py`（3 个 download 端点 + 3 个下发点）
- Modify: `frontend/src/views/MediaView.vue`（2 处）
- Modify: `frontend/src/views/ToolkitView.vue`（1 处）
- Modify: `frontend/src/views/VideoView.vue`（1 处，**孤儿文件**）
- Modify: `frontend/src/views/ScrapeView.vue`（1 处，**孤儿文件**）
- Modify: `py/tests/test_anon_surface.py`（白名单删 3 条）
- Test: `py/tests/test_security_hardening.py`（追加测试）

**Interfaces:**
- Consumes: Task 3 的 `sign_query` / `verify_query`
- Produces: 各下发点响应体新增 `download_url` 字段

**背景**：三条端点当前 `@jwt_required(optional=True)` ⇒ 匿名可达。改为「合法 JWT **或** 未过期签名」二者其一放行。**路径校验保留**，**归属语义不变**（设计文档 §4.3 勘误：两张产物表无用户字段）。

- [ ] **Step 1: 写失败测试**

在 `py/tests/test_security_hardening.py` **末尾追加**：

```python
class TestB3DownloadsRequireAuthOrSignature:
    """B-3 三条：匿名（无 token、无签名）必须 401；带 token 必须非 401。"""

    CASES = [
        ("/api/scrape/download",       {"path": "whatever"}),
        ("/api/video/download",        {"path": "whatever"}),
        ("/api/audio-replace/download", {"path": "whatever"}),
    ]

    @pytest.mark.parametrize("path,args", CASES)
    def test_anonymous_without_signature_rejected(self, client, path, args):
        resp = client.get(path, query_string=args)
        assert resp.status_code == 401, (
            f"{path} 匿名且无签名返回 {resp.status_code}，应为 401"
        )

    @pytest.mark.parametrize("path,args", CASES)
    def test_garbage_signature_rejected(self, client, path, args):
        """伪造签名必须被拒（承重：证明验签真的在跑）。"""
        resp = client.get(path, query_string={**args, "exp": "9999999999", "sig": "deadbeef"})
        assert resp.status_code == 401, (
            f"{path} 伪造签名返回 {resp.status_code}，应为 401"
        )

    @pytest.mark.parametrize("path,args", CASES)
    def test_logged_in_is_not_401(self, client, dev_headers, path, args):
        """承重对照：带 token **不得** 401（证明只挡匿名，没挡已登录）。

        注意断言是「非 401」而非「200」—— path 不存在时应为 404，
        那也是合法结果（鉴权已通过，业务层说文件不存在）。
        """
        resp = client.get(path, query_string=args, headers=dev_headers)
        assert resp.status_code != 401, (
            f"{path} 带 token 仍返回 401 —— 收口过头了"
        )
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd py && python -m pytest tests/test_security_hardening.py::TestB3DownloadsRequireAuthOrSignature -v`

Expected:
- `test_anonymous_without_signature_rejected` 3 条 **FAIL**（返回 404）
- `test_garbage_signature_rejected` 3 条 **FAIL**（返回 404）
- `test_logged_in_is_not_401` 3 条 **PASS**（回归钉）

- [ ] **Step 3: 在 `py/main.py` 顶部导入并加一个统一鉴权辅助**

在 `py/main.py` 既有 import 区（`from routes.decorators import ...` 附近）加入：

```python
from url_signing import sign_query as _sign_query, verify_query as _verify_query
```

在 `_is_safe_music_path` 附近（模块级）新增：

```python
def _download_authorized(endpoint: str, path: str) -> bool:
    """产物下载端点的统一鉴权：合法 JWT **或** 未过期签名，二者其一即可。

    - 有合法 JWT ⇒ 放行（保持既有「登录即可下载」语义，本次不改归属模型）
    - 无 JWT ⇒ 必须有有效签名，否则 False（调用方返回 401）

    注意：本函数**不判定归属**。`video_tasks` / `audio_replace_history`
    无用户字段，产物在设计上是全局共享的（见 2026-09-24 设计文档 §4.3 勘误）。
    """
    # ⚠️ 必须判返回值，**不能**靠 try/except：
    # 本端点是 @jwt_required(optional=True)，无 token 时 get_jwt_identity() 返回 None
    # 而**不抛异常** —— 写成 try: get_jwt_identity(); return True 会变成匿名全放行。
    if get_jwt_identity() is not None:
        return True
    return _verify_query(
        endpoint,
        path,
        request.args.get("exp", ""),
        request.args.get("sig", ""),
        app.config["JWT_SECRET_KEY"],
    )
```

⚠️ **上面的 `is not None` 是本 Task 最容易写错的一行**。同族的 `reject_viewer()`（`py/routes/decorators.py`）能靠 `try: int(get_jwt_identity())` 工作，是因为 `int(None)` **会**抛 `TypeError`；少了 `int()` 这层，异常就不存在了。**不要**照抄 `reject_viewer` 的 `try/except` 形状。

（承重测试：Step 1 的 `test_anonymous_without_signature_rejected` 正是钉这一行 —— 如果误写成 `try/except`，它必红。）

- [ ] **Step 4: 改造 3 个下载端点**

对下列每个函数，在 `path` 取到之后、业务校验之前插入鉴权闸门：

| 函数 | 路由 | 插入点 |
|---|---|---|
| `video_download` | `@app.route("/api/video/download", methods=["GET"])` | `if not path:` 之后 |
| `audio_replace_download` | `@app.route("/api/audio-replace/download", methods=["GET"])` | `if not path:` 之后 |
| `scrape_download` | `@app.route("/api/scrape/download", methods=["GET"])` | `if not path or not os.path.isdir(path):` 之后 |

插入代码（以 `video_download` 为例，另两条把端点字符串换成各自的）：

```python
    if not _download_authorized("/api/video/download", path):
        return jsonify({"success": False, "error": "未授权：需要登录或有效的下载签名"}), 401
```

⚠️ **保留**原有的路径校验（`scrape` 的目录白名单、另两条的「精确命中 `output_path`」）**与错误文案不变**。**保留** `@jwt_required(optional=True)` —— 它现在的作用是「有 token 时解析身份」，鉴权由闸门负责。

- [ ] **Step 5: 在三处下发点附上签名 URL**

**5a. `POST /api/scrape`（函数 `scrape`）** —— `saved_path` 有**两个出口**，都要带上 `download_url`：

- 缓存分支（形如 `"saved_path": pkg_dir` 的字典字面量）
- 正常路径（`response` 字典的 `"saved_path": pkg_dir`，末尾 `return jsonify(response)`）

在 `pkg_dir` 定义之后加一个局部变量，两个出口共用：

```python
    _scrape_dl = ("/api/scrape/download?"
                  + _sign_query("/api/scrape/download", pkg_dir, app.config["JWT_SECRET_KEY"]))
```

然后在两处 `"saved_path": pkg_dir,` 旁边各加一行：

```python
            "download_url": _scrape_dl,
```

**5b. `GET /api/video/progress`（函数 `video_progress`）** —— 两个出口：

- 完成分支：`resp["output"] = task.result()`
- SQLite 兜底：`_out = {"path": db_task["output_path"]}`

⚠️ **`task.result()` 返回的是内部 `_result` 的引用**（`video_processor.py` 的 `self._result`）。**不可原地修改**，否则会污染后续轮询。改为：

```python
        if task.status == "completed":
            _res = dict(task.result())
            _p = _res.get("path", "")
            if _p:
                _res["download_url"] = ("/api/video/download?"
                                        + _sign_query("/api/video/download", _p, app.config["JWT_SECRET_KEY"]))
            resp["output"] = _res
```

对 SQLite 兜底分支同理：

```python
            _out = {"path": db_task["output_path"]}
            if db_task["output_path"]:
                _out["download_url"] = ("/api/video/download?"
                                        + _sign_query("/api/video/download", db_task["output_path"],
                                                      app.config["JWT_SECRET_KEY"]))
```

**5c. `GET /api/audio-replace/history`（函数 `audio_replace_history_list`）** —— 在 item 字典里新增：

```python
            "download_url": ("/api/audio-replace/download?"
                             + _sign_query("/api/audio-replace/download", r["output_path"],
                                           app.config["JWT_SECRET_KEY"])),
```

**5d. `POST /api/audio-replace`（函数 `audio_replace`）** —— 把既有的下发行

```python
            "download_url": f"/api/audio-replace/download?path={quote(output_path)}",
```

改为

```python
            "download_url": ("/api/audio-replace/download?"
                             + _sign_query("/api/audio-replace/download", output_path,
                                           app.config["JWT_SECRET_KEY"])),
```

- [ ] **Step 6: 改前端 5 个消费点**

一律**只改 URL 来源**，不改模板结构、不改按钮、不改交互。

已核实的现状（**按这些行号定位，不要照抄数字**）：

| 文件 | 现状 | 为什么需要连带改动 |
|---|---|---|
| `MediaView.vue` | `:376` `downloadImages(r)` 自拼 URL | `r` 是 `:361`/`:364` **显式构造**的对象，需补 `download_url` 字段 |
| `MediaView.vue` | `:852` `downloadVideo(path)` 自拼 URL；`:618` `generatedPaths` 是**纯路径字符串数组** | 3 处 push（`:650`/`:775`/`:826`）拿到的正是 progress 响应 ⇒ `download_url` 就在手边，但**得存下来** |
| `VideoView.vue`（孤儿） | `:716` `downloadVideo()` 无参，读 `generatedPath` 单值 ref | 3 处赋值（`:338`/`:629`/`:688`）同样来自 progress 响应 |
| `ToolkitView.vue` | `:756` `audioHistoryDownload(item)` 自拼 URL | 历史列表接口本 Task 才新增 `download_url` |
| `ToolkitView.vue` | `:722`/`:729` `audioDownloadUrl = res.download_url` → `window.open` | **零改动** —— 后端换签名后自然生效 |
| `ScrapeView.vue`（孤儿） | `:86` `downloadImages(r)` 自拼 URL | `r` 是 `:70`/`:73` 显式构造的对象 |

**6a. `MediaView.vue` — 爬取结果带上下载 URL**

`:361` 改为（加 `download_url`）：

```javascript
      scrapeResults.value[i] = { url: links[i], package_name: res.package_name, image_count: res.image_count, error: '', saved_path: res.saved_path, from_cache: res.from_cache, download_url: res.download_url }
```

`:364` 改为：

```javascript
      scrapeResults.value[i] = { url: links[i], package_name: '', image_count: 0, error: e.message, saved_path: '', download_url: '' }
```

`:376` 改为：

```javascript
function downloadImages(r) {
  const target = r.download_url || ('/api/scrape/download?path=' + encodeURIComponent(r.saved_path))
  window.open(target, '_blank')
}
```

**6b. `MediaView.vue` — 视频产物列表带上下载 URL**

`generatedPaths` 由**字符串数组**改为**对象数组**（`{path, download_url}`）。三处 push 统一改为：

- `:650` → `if (latest.result?.output?.path) generatedPaths.value.push({ path: latest.result.output.path, download_url: latest.result.output.download_url || '' })`
- `:775` → `if (p.output?.path) generatedPaths.value.push({ path: p.output.path, download_url: p.output.download_url || '' })`
- `:826` → 同 `:775`

模板 `:281` 改为：

```html
          <el-button v-for="(it, i) in generatedPaths" :key="i" link size="small" type="primary" @click="downloadVideo(it.path, it.download_url)" style="font-size:11px;">📥 {{ pathBasename(it.path) }}</el-button>
```

`:852` 改为：

```javascript
function downloadVideo(path, url) {
  const target = url || (path ? '/api/video/download?path=' + encodeURIComponent(path) : '')
  if (target) window.open(target, '_blank')
}
```

`:282` 的「清空列表」是 `generatedPaths = []` 直接赋值，**不受影响**。

**6c. `ScrapeView.vue`（孤儿文件）**

`:70` 加 `download_url: res.download_url`，`:73` 加 `download_url: ''`，`:86` 与 6a 的 `downloadImages` **写法完全相同**。

**6d. `VideoView.vue`（孤儿文件）**

保留 `generatedPath` ref 不动，**新增**一个 ref：

```javascript
const generatedDownloadUrl = ref('')
```

在 `:338`、`:629`、`:688` 三处紧跟着补一行：

```javascript
      generatedDownloadUrl.value = latest.result?.output?.download_url || ''
```

（`:629`/`:688` 用 `p.output?.download_url || ''`。）

`:716` 的 `downloadVideo()` 改为：

```javascript
function downloadVideo() {
  const p = generatedPath.value
  if (!p) return
  window.open(generatedDownloadUrl.value || ('/api/video/download?path=' + encodeURIComponent(p)), '_blank')
}
```

`:199` 的模板 `@click="downloadVideo"` **不变**（仍无参）。

**6e. `ToolkitView.vue`**

`:756` 改为：

```javascript
function audioHistoryDownload(item) {
  window.open(item.download_url || `/api/audio-replace/download?path=${encodeURIComponent(item.output_path)}`, '_blank')
}
```

⚠️ **关于 `||` 兜底分支**：五处都保留了自拼 URL 的退路，作用是**防前端崩**（`download_url` 缺失时不至于 `window.open('undefined')`）。**但它不是可用路径** —— 服务端收口后自拼 URL 必然 401。因此：
- 若浏览器实测（Task 5 Step 3）时**看到 401**，说明对应下发点（Step 5）没生效，**回去修 Step 5，不要靠兜底绕过**。
- 报告里必须写明这一点。

- [ ] **Step 7: 从白名单删除已收口的 3 条**

在 `py/tests/test_anon_surface.py` 的 `ANON_GET_WHITELIST` 中**删除**：

```
    "/api/scrape/download",     # main.py:576，打包 temp/scraped_images/ 下调用方指定的目录
    "/api/video/download",      # main.py:1031
    "/api/audio-replace/download",  # main.py:1212
```

**保留** `/api/image`、`/api/font-file`、`/api/audio`（它们本就该匿名，见设计文档 §4.2）。

- [ ] **Step 8: 跑测试确认通过 + 回归**

Run: `cd py && python -m pytest tests/test_security_hardening.py::TestB3DownloadsRequireAuthOrSignature tests/test_anon_surface.py tests/test_url_signing.py -v`

Expected: **全 PASS**，且 `test_anon_surface.py` 的白名单已收敛到 **7 条**。

Run: `cd py && python -m pytest tests/ -q`

Expected: 全绿。**实测数字**以实测为准（本 Task 新增 9 条 + Task 3 的 12 条）。

⚠️ `py/tests/test_huguan_role.py` 有 6 处直接调用这些下载端点 —— **重点确认它们仍然通过**；若变红，检查是否有测试在**不带 token** 的情况下断言下载成功（那正是被本次收口挡掉的行为，需要把该测试改为带 token）。

**变异验证（必做，贴原始输出）**：把 `_download_authorized` 的 `return _verify_query(...)` **临时改为** `return True`（模拟「验签形同虚设」），重跑 ⇒ `test_anonymous_without_signature_rejected` 与 `test_garbage_signature_rejected` **必须变红**。实测后立即还原并自证。

- [ ] **Step 9: Commit**

```bash
git add py/main.py py/tests/test_security_hardening.py py/tests/test_anon_surface.py \
        frontend/src/views/MediaView.vue frontend/src/views/ToolkitView.vue \
        frontend/src/views/VideoView.vue frontend/src/views/ScrapeView.vue
git commit -m "fix(security): B-3 三条产物下载收口匿名可达（签名 URL）"
```

**报告须包含**：3 个端点 + 4 个下发点的逐处改动、白名单 10→7、5 个前端消费点改动、`test_huguan_role.py` 的复核结论、变异验证原始输出。

---

### Task 5: 浏览器实测复核（人工，不可自动化）

**Files:** 无（纯验证任务，**不产生代码改动**）

**背景**：安全加固验收时**从未执行**浏览器实测（其设计文档自称「最大风险」）。本 Task 把它补上。下面每一步的结论都必须来自 **DevTools Network 面板的实测**，**不得**由读码推断。

- [ ] **Step 1: 启动服务并登录**

Run: `cd py && python main.py`

在浏览器打开服务地址，用 **developer 或 admin** 账号登录。

- [ ] **Step 2: 复核 A 组 8 条（应带 `Authorization`）**

在 DevTools Network 面板逐条触发并检查请求头**确实含 `Authorization: Bearer ...`**：

| 触发动作 | 端点 |
|---|---|
| 打开产品管理页 | `GET /api/products/list` |
| 在产品弹窗提交一个测试产品 | `POST /api/products/create` |
| 打开含 runner 选择器的弹窗 | `GET /api/users/names` |
| 打开账户管理 / MCC 页 | `GET /api/settings/account` |
| 媒体工具中点「浏览文件」 | `POST /api/browse-file` |

**判定**：任一请求**未带**该头且仍返回 200 ⇒ **本计划的前提被推翻**，立即停止并报告（说明是哪一条、什么场景）。

- [ ] **Step 3: 复核 B 组 3 条（应能正常消费签名 URL）**

| 触发动作 | 期望 |
|---|---|
| 媒体工具 > 图片爬取，跑一次并点结果行 📥 | 下载到 zip，**不是** 401 页面 |
| 媒体工具 > 视频生成，点产物 📥 | 下载到 mp4 |
| 工具集 > 音频替换，跑一次并点产物 ⬇ **和历史记录 ⬇** | **两个入口都要试** —— 下载到文件 |

**判定**：任一处新开标签页显示 401 JSON ⇒ 该下发点没生效，回到 Task 4 Step 5 检查。

- [ ] **Step 4: 复核 B-1/B-2 三条未受影响**

| 触发动作 | 期望 |
|---|---|
| 媒体工具图片网格 + 拖拽排序面板 | 缩略图**全部正常**显示（无破图） |
| 媒体工具 >「文案」字体选择器 | 逐个试**黑体/微软雅黑/宋体/Arial** 与任一导入字体 ⇒ 预览字体**都正确变化** |
| 媒体工具 >「背景音乐」选歌试听 | 能播放（**注意**：该下拉仅在**非 localhost 访问**时渲染，须用局域网 IP 访问验证） |

- [ ] **Step 5: 把结论写进报告**

对每一条记录：**触发的动作 → Network 面板看到的实际请求 URL 与状态码 → 结论**。
若有任何一条**未能验证**（例如没有合适的测试数据），**明确标注「未验证」并说明原因**，**不得**推断为通过。

---

## 完成标准

1. `py/tests/test_anon_surface.py` 白名单为 **7 条**，测试通过。
2. A 组 8 条、B-3 三条**零 token 全部 401**；带 token 行为与改动前一致。
3. `/api/font-file` 对非具名系统字体返回 **403**，对 4 个具名字体返回 **200**。
4. 全量测试**实测**全绿，数字如实记录。
5. 每个 Task 的**变异验证原始输出**均已留存，且工作区已还原（`md5sum` 自证）。
6. Task 5 的浏览器实测结论逐条落盘；**未验证项**明确标注。
7. 全部完成后调用 **`/code-review`**（CLAUDE.md 硬性要求），修复发现的问题再交付。

## 已知的未解决项（不在本计划范围）

- **产物归属隔离**：`video_tasks` / `audio_replace_history` 无用户字段，「登录用户可下他人产物」需改表结构 + 数据迁移 ⇒ 独立议题。
- **`/api/scrape/download` 的归属校验**：有归属信息（目录名 = `display_name`）但未校验；签名 URL 场景无 token，须在签名 payload 内携带 user_id 才能校验 ⇒ 独立议题。
- **`POST /api/auth/register`**：设计上应匿名，已裁决**保持现状**。
- 安全加固验收记录的其他缺口（I-2 的 28 组 `<int:...>`、O-1 的 79 处非 dict 体、O-2 的 traceback 回显、B-6/B-7 等）⇒ 另行裁决。
