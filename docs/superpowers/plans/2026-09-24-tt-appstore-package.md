# TT 苹果（App Store）包链接支持 + 掉包判定加固 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让 TT 的投放对象能录入 App Store 链接并正确参与掉包检测；顺带修掉「429 限流被当成正常、覆盖掉正确掉包记录」这一既有缺陷。

**Architecture:** 复用 `tt_packages.type='package'`，苹果包表现为「URL 是 App Store 域名的跑包 + 包名为空」。域名判定收敛成一个按 host 全等比较的函数（后端 `_is_appstore_url`、前端内联同口径小函数）。掉包判定引入第三态「未知」：`check_url_delisted` 的 `is_delisted` 由 `bool` 变为 `bool | None`，`None` 表示限流/服务端异常导致本次无法判定，四个消费方遇到 `None` 时不写库，保留上一轮判定结果。

**Tech Stack:** Python 3.11 / Flask / SQLite(WAL) / pytest + unittest.mock；Vue 3 `<script setup>` + Element Plus + Vite（前端无测试框架，靠 `npm run build` + 人工验证）。

## Global Constraints

- **语言**：面向用户的说明、注释、提交信息一律中文。
- **纯增量原则**：只做增量，不修改原有功能逻辑；禁止因新增功能导致已有功能出错或失效。
- **安卓包名校验不得放松**：只有 URL 是 App Store 域名时，`type='package'` 的包名才允许留空。其余情况维持原 400。
- **代理失败绝不判掉包**：`check_url_delisted` 在超时/连接失败时仍返回 `(False, 错误信息)`，不变。
- **不改表结构**：无 DDL、无迁移。
- **不改 GG/FB 的录入链路**：`AddPackageModal.vue`、`CopyImportModal.vue`、`utils.py:extract_package_name` 保持 Play 口径。
- **域名判定禁止用子串匹配**：必须解析 host 后全等比较，`https://evil.com/?u=apps.apple.com` 必须判为「不是苹果」。
- **苹果链接只认这两个 host**：`apps.apple.com`、`itunes.apple.com`（均含任意地区段如 `/vn/`、`/us/`）。
- **测试不得外发真实通知**：任何新测试若走到 `/check-delist` 或调度器，必须 monkeypatch 掉 `send_tt_delist_notifications` / 邮件发送。
- **执行环境**：所有 pytest 命令在 `py/` 目录下执行（`conftest.py` 依赖该目录在 `sys.path`）。后端改动后需重启 Flask（用户自行重启），前端改动后需 `npm run build`。
- **不得使用 `git add -A`**：本仓库常有并行会话在途改文件，只暂存本任务涉及的文件。

---

## 文件结构

| 文件 | 职责 | 本计划中的动作 |
|------|------|----------------|
| `py/delist_checker.py` | 掉包判定核心（GG/TT 共用） | 新增第三态「未知」：`DelistIndeterminate` + `_RETRYABLE_STATUS`；`_request_and_judge` 加状态码分支；`check_url_delisted` 返回 `bool \| None` |
| `py/routes/tt_routes.py` | TT 平台路由 | 新增 `_is_appstore_url`；`_validate_package` / `update_package` 放行苹果空包名；`import_text` 支持苹果链接（按原文顺序） |
| `py/main.py` | GG 定时/手动检测、TT 定时检测 | 三处消费方：`is_delisted is None` 时不覆盖既有判定 |
| `py/routes/tt_routes.py`（同文件） | TT 手动检测 | 第四处消费方，同上 |
| `frontend/src/components/TtAddPackageModal.vue` | 添加包弹窗 | 手动添加的包名必填校验加苹果豁免；提示语与 placeholder 文案 |
| `frontend/src/components/TtProductCard.vue` | TT 产品卡片（唯一渲染包名处） | 苹果空包名显示灰色 `iOS` 占位 |
| `py/tests/test_delist_checker.py` | 判定单元测试（已存在） | 新增 `TestIndeterminateStatus` |
| `py/tests/test_tt_appstore_package.py` | 录入链路测试 | **新建** |
| `py/tests/test_delist_indeterminate.py` | 消费方不覆盖既有判定的测试 | **新建** |
| `py/tests/test_tt_delist_notification.py` | TT 调度器测试（已存在） | 在 `TestTtDelistScheduler` 里补一条 |

---

## Task 1: 掉包判定引入「未知」态

**Files:**
- Modify: `py/delist_checker.py`
- Test: `py/tests/test_delist_checker.py`（在文件末尾追加新类）

**Interfaces:**
- Consumes: 无（本任务是链条起点）
- Produces:
  - `delist_checker.DelistIndeterminate` —— 异常类，`__init__` 接收一个字符串消息
  - `delist_checker._RETRYABLE_STATUS: frozenset[int]` —— `{429, 500, 502, 503, 504}`
  - `delist_checker.check_url_delisted(url: str, proxy_pool=None) -> tuple[bool | None, str]` —— `True` 掉包 / `False` 正常 / `None` 判定未知
  - `delist_checker.check_product_packages(product_id, packages, proxy_pool=None) -> list[dict]` —— 每个 dict 的 `is_delisted` 可能为 `None`

- [ ] **Step 1: 写失败的测试**

在 `py/tests/test_delist_checker.py` **末尾追加**：

```python
# ============================================================
# 测试限流 / 服务端异常 → 判定未知（429/5xx）
# ============================================================

class TestIndeterminateStatus:
    """429/5xx 既不是 404（掉包）也不是正常页面，必须判为「未知」。

    实测依据：App Store 对掉包链接返回 404，被限流时返回 429，
    两者响应体同为 2383 字节，只能靠状态码区分。旧逻辑只认 404，
    会把 429 当成「正常」，从而抹掉上一轮正确的掉包记录。
    """

    def _resp(self, status, text=""):
        m = MagicMock()
        m.status_code = status
        m.text = text
        return m

    def test_429_direct_returns_none(self):
        """直连遇 429 → is_delisted 为 None，error 带状态码。"""
        from delist_checker import check_url_delisted

        with patch("delist_checker.requests.get", return_value=self._resp(429, "Too Many Requests")):
            is_delisted, error = check_url_delisted("https://apps.apple.com/vn/app/id6813542964")

        assert is_delisted is None
        assert "429" in error

    def test_503_direct_returns_none(self):
        """直连遇 503 → 同样判为未知。"""
        from delist_checker import check_url_delisted

        with patch("delist_checker.requests.get", return_value=self._resp(503)):
            is_delisted, error = check_url_delisted("https://play.google.com/store/apps/details?id=com.a.b")

        assert is_delisted is None
        assert "503" in error

    def test_404_still_true(self):
        """404 不受影响，仍判掉包。"""
        from delist_checker import check_url_delisted

        with patch("delist_checker.requests.get", return_value=self._resp(404)):
            is_delisted, error = check_url_delisted("https://apps.apple.com/vn/app/id6813542964")

        assert is_delisted is True
        assert error == ""

    def test_200_normal_still_false(self):
        """正常页面不受影响，仍判未掉包。"""
        from delist_checker import check_url_delisted

        with patch("delist_checker.requests.get", return_value=self._resp(200, "App page")):
            is_delisted, error = check_url_delisted("https://apps.apple.com/vn/app/id6804355336")

        assert is_delisted is False
        assert error == ""

    def test_timeout_still_false_not_none(self):
        """超时仍返回 False（既有不变量：代理/网络失败绝不判掉包，也不改判未知）。"""
        from delist_checker import check_url_delisted

        with patch("delist_checker.requests.get", side_effect=requests.Timeout("timed out")):
            is_delisted, error = check_url_delisted("https://play.google.com/store/apps/details?id=com.a.b")

        assert is_delisted is False
        assert error != ""

    def test_proxy_retries_to_next_after_429(self):
        """第一个代理 429，第二个代理 200 → 最终判正常，且请求了两次。"""
        from delist_checker import check_url_delisted
        from proxy_pool import ProxyPool

        pool = ProxyPool([
            {"ip": "1.2.3.1", "port": 801, "username": "u", "password": "p"},
            {"ip": "1.2.3.2", "port": 802, "username": "u", "password": "p"},
        ], max_retries=2)

        with patch("delist_checker.requests.get",
                   side_effect=[self._resp(429), self._resp(200, "App page")]) as mock_get:
            is_delisted, error = check_url_delisted("https://apps.apple.com/vn/app/id6804355336", pool)

        assert is_delisted is False
        assert error == ""
        assert mock_get.call_count == 2

    def test_all_proxies_429_returns_none(self):
        """所有代理都 429 → 判为未知，不判掉包也不判正常。"""
        from delist_checker import check_url_delisted
        from proxy_pool import ProxyPool

        pool = ProxyPool([
            {"ip": "1.2.3.1", "port": 801, "username": "u", "password": "p"},
            {"ip": "1.2.3.2", "port": 802, "username": "u", "password": "p"},
        ], max_retries=2)

        with patch("delist_checker.requests.get", return_value=self._resp(429)):
            is_delisted, error = check_url_delisted("https://apps.apple.com/vn/app/id6813542964", pool)

        assert is_delisted is None
        assert "429" in error

    def test_request_and_judge_raises_on_429(self):
        """_request_and_judge 遇 429 抛 DelistIndeterminate。"""
        from delist_checker import _request_and_judge, DelistIndeterminate

        with patch("delist_checker.requests.get", return_value=self._resp(429)):
            with pytest.raises(DelistIndeterminate):
                _request_and_judge("https://apps.apple.com/vn/app/id6813542964", None)

    def test_check_product_packages_passes_none_through(self):
        """批量检测把未知态原样透传。"""
        from delist_checker import check_product_packages

        with patch("delist_checker.check_url_delisted", return_value=(None, "HTTP 429 限流，判定未知")):
            results = check_product_packages(1, [
                {"id": 7, "url": "https://apps.apple.com/vn/app/id6813542964", "package_name": ""},
            ])

        assert results[0]["is_delisted"] is None
        assert "429" in results[0]["error"]
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd py && python -m pytest tests/test_delist_checker.py::TestIndeterminateStatus -v`

Expected: 多条 FAIL —— `test_429_direct_returns_none` 报 `assert False is None`（当前把 429 判成正常）；`test_request_and_judge_raises_on_429` 报 `ImportError: cannot import name 'DelistIndeterminate'`。

- [ ] **Step 3: 实现**

把 `py/delist_checker.py` 的**模块头部**改成：

```python
"""Google Play / App Store 掉包检测模块。

通过 HTTP 请求应用商店链接，判断应用是否已被下架。
"""

import requests

# 移动端 User-Agent（Google Play 与 App Store 通用）
_USER_AGENT = (
    "Mozilla/5.0 (Linux; Android 13; Pixel 7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Mobile Safari/537.36"
)

# 掉包判定关键词
_DELISTED_PATTERNS = [
    "not found on this server",
    "找不到请求的网址",
    "We're sorry, the requested URL was not found",
]

# 可重试的异常状态码：既不是 404（掉包），也不是正常页面（限流 / 服务端异常），
# 命中时本次无法判定，交由调用方换代理重试。
# 实测依据：App Store 对掉包链接返回 404，被限流时返回 429，两者响应体同为
# 2383 字节，只能靠状态码区分；旧逻辑只认 404，会把 429 当成「正常」，
# 进而用 INSERT OR REPLACE 抹掉上一轮正确的掉包记录。
_RETRYABLE_STATUS = frozenset({429, 500, 502, 503, 504})

_TIMEOUT = 15  # 请求超时秒数


class DelistIndeterminate(Exception):
    """响应状态既非 404 也非正常页面（429/5xx），本次判定结果未知。

    调用方应保留上一轮判定结果，不得当作「正常」写入。
    """
```

把 `_request_and_judge` 改成：

```python
def _request_and_judge(url: str, proxies: dict | None) -> tuple[bool, str]:
    """发请求并判掉包；网络异常直接抛出，由调用方处理。

    Args:
        url: 应用商店链接（Google Play 或 App Store）
        proxies: requests 的 proxies 参数，None 表示直连

    Raises:
        DelistIndeterminate: 状态码属于 _RETRYABLE_STATUS，本次无法判定
    """
    resp = requests.get(
        url,
        headers={"User-Agent": _USER_AGENT},
        timeout=_TIMEOUT,
        allow_redirects=True,
        proxies=proxies,
    )

    # 1. HTTP 404
    if resp.status_code == 404:
        return True, ""

    # 2. 限流 / 服务端异常：结果未知，抛出让调用方换代理重试
    if resp.status_code in _RETRYABLE_STATUS:
        raise DelistIndeterminate(f"HTTP {resp.status_code}")

    # 3. 检查页面内容关键词
    text_lower = resp.text.lower()
    for pattern in _DELISTED_PATTERNS:
        if pattern.lower() in text_lower:
            return True, ""

    return False, ""
```

把 `check_url_delisted` 整个替换成：

```python
def check_url_delisted(url: str, proxy_pool=None) -> tuple[bool | None, str]:
    """检测单个应用链接是否已掉包。

    Args:
        url: 应用商店链接（Google Play 或 App Store）
        proxy_pool: ProxyPool 实例；None 时走原直连逻辑

    Returns:
        (is_delisted, error)：
          True  → 已掉包
          False → 正常（含网络/代理失败：既有不变量「失败绝不判掉包」）
          None  → 判定未知（限流或服务端异常且重试耗尽），调用方应保留上一次判定结果
    """
    if not url or not url.strip():
        return False, ""

    # 无代理池：直连，行为与历史版本一致（新增：限流/服务端异常返回「未知」）
    if proxy_pool is None:
        try:
            return _request_and_judge(url, None)
        except DelistIndeterminate as e:
            return None, f"{e} 限流或服务端异常，判定未知"
        except requests.Timeout:
            return False, "请求超时"
        except requests.ConnectionError:
            return False, "网络连接失败"
        except Exception as e:
            return False, str(e)

    # 有代理池：失败换下一个代理重试，绝不因代理失败误判为掉包
    if proxy_pool.count == 0:
        return False, "代理池为空"

    tried = set()
    last_error = ""
    last_indeterminate = ""
    for _ in range(proxy_pool.max_retries):
        proxy = proxy_pool.next(exclude=tried)
        if proxy is None:
            break
        tried.add((proxy["ip"], proxy["port"]))
        try:
            return _request_and_judge(url, proxy_pool.to_requests(proxy))
        except DelistIndeterminate as e:
            last_indeterminate = f"{e} @ {proxy['ip']}:{proxy['port']}"
        except requests.Timeout:
            last_error = f"代理超时 {proxy['ip']}:{proxy['port']}"
        except requests.ConnectionError:
            last_error = f"代理连接失败 {proxy['ip']}:{proxy['port']}"
        except Exception as e:
            last_error = f"代理异常 {proxy['ip']}:{proxy['port']}: {e}"

    # 出现过限流/服务端异常 → 整体判为未知（保守：既不算掉包也不算正常）
    if last_indeterminate:
        return None, f"代理响应异常（限流/服务端）: {last_indeterminate}"
    return False, f"代理全部失败: {last_error}"
```

把 `check_product_packages` 的 docstring 里 `is_delisted` 的说明补成：

```python
    Returns:
        检测结果列表，每个元素包含 package_id, is_delisted, error。
        is_delisted 为 True/False/None（None 表示判定未知）。函数只做透传。
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd py && python -m pytest tests/test_delist_checker.py -v`

Expected: 全绿（既有 16 个 + 新增 9 个）。特别确认既有的 `test_returns_false_with_error_on_timeout`、`test_all_proxies_fail_returns_proxy_error`、`test_empty_pool_returns_proxy_error` 仍通过 —— 它们断言 `is_delisted is False`，证明「未知态」没有扩大化。

- [ ] **Step 5: 提交**

```bash
git add py/delist_checker.py py/tests/test_delist_checker.py
git commit -m "fix(delist): 429/5xx 判为「判定未知」而非正常，避免覆盖正确掉包记录"
```

---

## Task 2: TT 苹果链接识别与录入放行

**Files:**
- Modify: `py/routes/tt_routes.py`（模块导入区、`_validate_package`、`update_package`、`import_text`、工具函数区）
- Test: `py/tests/test_tt_appstore_package.py`（**新建**）

**Interfaces:**
- Consumes: Task 1 无依赖（本任务不碰判定逻辑）
- Produces:
  - `tt_routes._is_appstore_url(url) -> bool`
  - `tt_routes._validate_package(pkg: dict) -> None | flask.Response`
  - `tt_routes.import_text`：`POST /api/tt/products/import-text` 返回的 `parsed[]` 中，苹果条目 `package_name` 为 `""`

- [ ] **Step 1: 写失败的测试**

新建 `py/tests/test_tt_appstore_package.py`：

```python
"""TT 苹果（App Store）包链接录入测试。

设计文档：docs/superpowers/specs/2026-09-24-tt-appstore-package-design.md
"""
import os
import sys

_py_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _py_dir not in sys.path:
    sys.path.insert(0, _py_dir)

from routes import tt_routes  # noqa: E402

APPLE_LIVE = "https://apps.apple.com/vn/app/id6804355336"
APPLE_SLUG = "https://apps.apple.com/vn/app/densia/id6804355336"
PLAY = "https://play.google.com/store/apps/details?id=com.a.b"


class TestIsAppstoreUrl:
    """域名判定：按解析出的 host 全等比较，禁止子串匹配。"""

    def test_apps_apple_com_is_appstore(self):
        assert tt_routes._is_appstore_url(APPLE_LIVE) is True

    def test_itunes_apple_com_is_appstore(self):
        assert tt_routes._is_appstore_url("https://itunes.apple.com/us/app/id123") is True

    def test_slug_form_is_appstore(self):
        assert tt_routes._is_appstore_url(APPLE_SLUG) is True

    def test_play_is_not_appstore(self):
        assert tt_routes._is_appstore_url(PLAY) is False

    def test_host_in_query_is_not_appstore(self):
        """域名出现在参数里 → 不是苹果（子串匹配会误判）。"""
        assert tt_routes._is_appstore_url("https://evil.com/?u=apps.apple.com") is False

    def test_suffix_domain_is_not_appstore(self):
        """apps.apple.com.evil.com 不是苹果。"""
        assert tt_routes._is_appstore_url("https://apps.apple.com.evil.com/vn/app/id1") is False

    def test_empty_and_none_are_not_appstore(self):
        assert tt_routes._is_appstore_url("") is False
        assert tt_routes._is_appstore_url(None) is False


class TestValidatePackage:
    """校验四象限：只有「苹果链接 + 空包名」是新放行的组合。"""

    def _call(self, **pkg):
        return tt_routes._validate_package(pkg)

    def test_play_empty_name_rejected(self):
        resp = self._call(type="package", package_name="", url=PLAY)
        assert resp is not None

    def test_play_with_name_ok(self):
        assert self._call(type="package", package_name="com.a.b", url=PLAY) is None

    def test_appstore_empty_name_ok(self):
        assert self._call(type="package", package_name="", url=APPLE_LIVE) is None

    def test_appstore_with_name_ok(self):
        assert self._call(type="package", package_name="myapp", url=APPLE_LIVE) is None

    def test_pwa_needs_no_name(self):
        assert self._call(type="pwa", package_name="", url="") is None

    def test_invalid_type_rejected(self):
        assert self._call(type="ios", package_name="x", url=APPLE_LIVE) is not None

    def test_play_empty_name_and_empty_url_rejected(self):
        """URL 缺失时不得因为「可能以后填苹果链接」而放行。"""
        assert self._call(type="package", package_name="", url="") is not None


class TestAddPackageViaApi:
    """走 HTTP 接口验证放行真的生效（不只是函数级）。"""

    def test_add_appstore_package_without_name(self, client, tt_headers):
        pid = client.post("/api/tt/products/create", headers=tt_headers, json={
            "product_name": "苹果包产品",
        }).get_json()["id"]

        resp = client.post(f"/api/tt/products/{pid}/packages", headers=tt_headers, json={
            "type": "package", "series_name": "S1", "package_name": "", "url": APPLE_LIVE,
        })
        assert resp.status_code == 200

        detail = client.get(f"/api/tt/products/{pid}/detail", headers=tt_headers).get_json()
        pkg = detail["packages"][0]
        assert pkg["package_name"] == ""
        assert pkg["url"] == APPLE_LIVE

    def test_add_play_package_without_name_still_rejected(self, client, tt_headers):
        pid = client.post("/api/tt/products/create", headers=tt_headers, json={
            "product_name": "安卓包产品",
        }).get_json()["id"]

        resp = client.post(f"/api/tt/products/{pid}/packages", headers=tt_headers, json={
            "type": "package", "series_name": "S1", "package_name": "", "url": PLAY,
        })
        assert resp.status_code == 400
        assert "包名" in resp.get_json()["error"]

    def test_create_product_with_appstore_package(self, client, tt_headers):
        """建产品时带包这条路径（第三个调用点）也要放行。"""
        resp = client.post("/api/tt/products/create", headers=tt_headers, json={
            "product_name": "带苹果包的产品",
            "packages": [{"type": "package", "series_name": "S1",
                          "package_name": "", "url": APPLE_LIVE}],
        })
        assert resp.status_code == 200

    def test_update_package_clearing_name_allowed_for_appstore(self, client, tt_headers):
        """更新时清空包名：苹果链接允许，安卓链接拒绝。"""
        pid = client.post("/api/tt/products/create", headers=tt_headers, json={
            "product_name": "更新测试产品",
        }).get_json()["id"]

        apple_id = client.post(f"/api/tt/products/{pid}/packages", headers=tt_headers, json={
            "type": "package", "series_name": "S1", "package_name": "x", "url": APPLE_LIVE,
        }).get_json()["id"]
        resp = client.put(f"/api/tt/packages/{apple_id}", headers=tt_headers,
                          json={"package_name": ""})
        assert resp.status_code == 200

        play_id = client.post(f"/api/tt/products/{pid}/packages", headers=tt_headers, json={
            "type": "package", "series_name": "S2", "package_name": "com.a.b", "url": PLAY,
        }).get_json()["id"]
        resp = client.put(f"/api/tt/packages/{play_id}", headers=tt_headers,
                          json={"package_name": ""})
        assert resp.status_code == 400


class TestImportTextAppstore:
    """脏数据解析：苹果链接要能捞出来，且顺序与原文一致。"""

    def test_parse_appstore_link(self, client, tt_headers):
        resp = client.post("/api/tt/products/import-text", headers=tt_headers,
                           json={"text": f"神包上线：苹果系列\n{APPLE_LIVE}"})
        parsed = resp.get_json()["parsed"]
        assert len(parsed) == 1
        assert parsed[0]["url"] == APPLE_LIVE
        assert parsed[0]["package_name"] == ""
        assert parsed[0]["type"] == "package"

    def test_parse_slug_form(self, client, tt_headers):
        resp = client.post("/api/tt/products/import-text", headers=tt_headers,
                           json={"text": f"神包上线：Densia\n{APPLE_SLUG}"})
        parsed = resp.get_json()["parsed"]
        assert len(parsed) == 1
        assert parsed[0]["url"] == APPLE_SLUG

    def test_order_follows_source_text_not_pattern(self, client, tt_headers):
        """Play 与苹果交错时，输出顺序必须按原文出现顺序，不能先排完 Play 再排苹果。"""
        text = (
            "神包上线：甲\n" + PLAY + "\n"
            "神包上线：乙\n" + APPLE_LIVE + "\n"
            "神包上线：丙\nhttps://play.google.com/store/apps/details?id=com.c.d"
        )
        resp = client.post("/api/tt/products/import-text", headers=tt_headers, json={"text": text})
        parsed = resp.get_json()["parsed"]
        assert [p["url"] for p in parsed] == [
            PLAY,
            APPLE_LIVE,
            "https://play.google.com/store/apps/details?id=com.c.d",
        ]

    def test_mixed_keeps_play_package_names(self, client, tt_headers):
        """苹果条目包名为空，Play 条目包名照旧提取。"""
        text = "神包上线：甲\n" + PLAY + "\n神包上线：乙\n" + APPLE_LIVE
        resp = client.post("/api/tt/products/import-text", headers=tt_headers, json={"text": text})
        parsed = resp.get_json()["parsed"]
        assert parsed[0]["package_name"] == "com.a.b"
        assert parsed[1]["package_name"] == ""

    def test_non_appstore_apple_path_not_matched(self, client, tt_headers):
        """苹果官网其他路径（非 /app/idNNN）不该被当成包链接。"""
        resp = client.post("/api/tt/products/import-text", headers=tt_headers,
                           json={"text": "看看 https://apps.apple.com/vn/charts/paid-apps"})
        assert resp.get_json()["parsed"] == []
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd py && python -m pytest tests/test_tt_appstore_package.py -v`

Expected: `TestIsAppstoreUrl` 全部 FAIL（`AttributeError: module 'routes.tt_routes' has no attribute '_is_appstore_url'`）；`TestImportTextAppstore::test_parse_appstore_link` FAIL（`parsed` 为空列表）。

- [ ] **Step 3: 实现**

**3a. 模块导入区**（`py/routes/tt_routes.py` 第 1-10 行）加 `import urllib.parse`：

```python
"""TikTok 平台 API 路由 — 产品管理 / BC管理 / 投放对象 / 掉包检测 / 素材关联"""
import json
import os
import re
import urllib.parse

from flask import Blueprint, request
```

**3b. 工具函数区**，在 `_extract_pkg_from_url` 上方插入：

```python
# App Store 的两个合法 host（老域名 itunes.apple.com 会跳转到 apps.apple.com）
_APPSTORE_HOSTS = frozenset({"apps.apple.com", "itunes.apple.com"})


def _is_appstore_url(url):
    """URL 的 host 是否属于 App Store。

    必须解析出 host 后**全等**比较：用子串匹配会让
    `https://evil.com/?u=apps.apple.com` 这类 URL 误判为苹果链接。
    """
    if not url:
        return False
    try:
        host = urllib.parse.urlsplit(str(url).strip()).hostname or ""
    except ValueError:
        return False
    return host.lower() in _APPSTORE_HOSTS
```

**3c. `_validate_package`**（约 1423 行）整体替换：

```python
def _validate_package(pkg):
    """校验投放对象：type 必须 package/pwa；跑包必须填写包名。

    例外：App Store 的投放对象没有安卓包名，URL 是苹果链接时包名允许留空。
    返回 None 或 err 响应。
    """
    pkg_type = pkg.get('type', 'package')
    if pkg_type not in ('package', 'pwa'):
        return err('无效的投放对象类型', 400)
    if pkg_type == 'package' and not (pkg.get('package_name') or '').strip():
        if not _is_appstore_url(pkg.get('url')):
            return err('跑包必须填写包名', 400)
    return None
```

**3d. `update_package` 的内联校验**（约 470-473 行）替换成：

```python
    # re-enforce type 规则：package 必须填写包名（App Store 链接除外，与 add_package 语义一致）
    pkg_type = updates.get('type', existing['type'])
    if pkg_type == 'package' and 'package_name' in updates and not updates['package_name']:
        # 本次没传 url 时，用库里既有的 url 判断是不是苹果链接
        if not _is_appstore_url(updates.get('url') or existing['url']):
            return err('跑包必须填写包名', 400)
```

**3e. `import_text` 的链接提取**（约 943 行）。在文件**顶部（`tt_bp = Blueprint(...)` 之前）**加两个常量：

```python
# 脏数据解析用的链接正则。两个 pattern 合成一个 alternation，
# 这样 re.finditer 能按**原文出现顺序**输出，而不是「先排完 Play 再排苹果」，
# 否则 _guess_series 会拿错行去猜系列名。
# 苹果链接的查询参数（?pt= / ?ct= / ?l=）是分享/联盟参数，与掉包判定无关，
# 故意不捕获 —— 去掉后同一个 app 的重复粘贴能被合并去重键识别。
_PLAY_LINK_RE = r'https?://play\.google\.com/store/apps/details\?id=[\w.&=/\-?%]+'
# 苹果链接两种真实形状都要匹配：
#   https://apps.apple.com/vn/app/id6804355336         （无 slug）
#   https://apps.apple.com/vn/app/densia/id6804355336  （有 slug —— 实测中 200 会跳转到这个形状）
# slug 必须作为独立路径段可选：写成 `[\w\-]*id\d+` 会跨不过 slug 后的 `/`，导致 slug 形式漏匹配。
_APPSTORE_LINK_RE = r'https?://(?:apps|itunes)\.apple\.com/(?:[\w\-]+/)?app/(?:[\w\-]+/)?id\d+'
_LINK_RE = re.compile(f'(?:{_PLAY_LINK_RE})|(?:{_APPSTORE_LINK_RE})')
```

把 `import_text` 里这一行：

```python
    links = re.findall(r'https?://play\.google\.com/store/apps/details\?id=[\w.&=/\-?%]+', text)
```

替换成：

```python
    links = [m.group(0) for m in _LINK_RE.finditer(text)]
```

并把紧随其后的 for 循环里这行：

```python
        pkg = _extract_pkg_from_url(link)
```

替换成：

```python
        # 苹果链接没有安卓包名，也不自动填数字 id（用户裁定：包名留空）
        pkg = "" if _is_appstore_url(link) else _extract_pkg_from_url(link)
```

同时把该函数的 docstring 首行改为：

```python
    """粘贴文本解析成投放对象列表（支持 Google Play 与 App Store 链接）。"""
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd py && python -m pytest tests/test_tt_appstore_package.py -v`

Expected: 全绿。

再跑既有 TT 回归，确认安卓校验没被放松：

Run: `cd py && python -m pytest tests/test_tt_routes.py tests/test_tt_platform.py tests/test_tt_delist_notification.py tests/test_tt_accounts.py -v`

Expected: 全绿。

- [ ] **Step 5: 提交**

```bash
git add py/routes/tt_routes.py py/tests/test_tt_appstore_package.py
git commit -m "feat(tt): 投放对象支持 App Store 链接，苹果包允许包名为空"
```

---

## Task 3: 判定未知时不覆盖既有结果

**Files:**
- Modify: `py/main.py`（TT 定时循环约 8843-8872、GG 定时循环约 8680-8709、GG 手动循环约 3644-3651）
- Modify: `py/routes/tt_routes.py`（TT 手动循环约 648-653、`update_package` 内联校验约 484-489）
- Modify: `py/delist_checker.py`（空 url 两处判定，见 3e）
- Modify: `py/tests/test_delist_checker.py`（更新两个钉住旧行为的既有测试，见 3e）
- Test: `py/tests/test_delist_indeterminate.py`（**新建**）、`py/tests/test_tt_delist_notification.py`（补一条）、`py/tests/test_tt_appstore_package.py`（追加一个类，见 1c）

**Interfaces:**
- Consumes: Task 1 的 `check_url_delisted` 返回 `bool | None`
- Produces: 四处消费方语义一致 —— `is_delisted is None` 时**不覆盖** `delist_checks` / `tt_delist_checks` 里的既有行；GG 侧额外把原因写进 `error_msg`

**本任务额外包含两项用户裁定的同族收口**（2026-09-24）：
- **3e** 空 url 也从「正常」改判「未知」（与 429 同一缺陷家族，且 GG 侧可达）
- **3f** `update_package` 的 url 语义收口（显式传空 url 不再回落库里 url 而放行）

改这两个既有测试是本任务**唯一**允许修改既有测试的地方；改动方式是**改断言 + 注明语义变更**，
**不得删除用例**。

- [ ] **Step 1: 写失败的测试**

**1a.** 在 `py/tests/test_tt_delist_notification.py` 的 `class TestTtDelistScheduler`（约 505 行）**内部末尾**追加：

```python
    def test_indeterminate_does_not_overwrite_existing_delisted(self, client, tt_headers, monkeypatch):
        """429 等未知态不得把上一轮「已掉包」覆盖成正常。"""
        import main

        db = database.get_db()
        uid = db.execute("SELECT id FROM users WHERE username='ttuser'").fetchone()["id"]
        pid = _mk_product(db, uid, "未知态产品")
        pkg_id = _mk_package(db, pid, "未知包")
        _mark_delisted(db, pkg_id, is_delisted=1)   # 上一轮已判定掉包
        db.close()

        # 本轮检测返回「未知」
        monkeypatch.setattr(delist_checker, "check_url_delisted", lambda url, pool=None: (None, "HTTP 429 限流，判定未知"))
        monkeypatch.setattr(main, "_build_delist_proxy_pool", lambda: None)
        notified = []
        monkeypatch.setattr(tt_routes, "send_tt_delist_notifications",
                            lambda db_, pkgs, title="TT-Server": notified.append(pkgs) or len(pkgs))

        result = main._run_tt_delist_check_once()

        db = database.get_db()
        row = db.execute("SELECT is_delisted FROM tt_delist_checks WHERE package_id=?",
                         (pkg_id,)).fetchone()
        db.close()

        assert row["is_delisted"] == 1          # 既有判定被保留
        assert notified == []                   # 未知态不触发通知
        assert result["delisted"] == 0
        assert result["results"][0]["is_delisted"] is None
        assert "429" in result["results"][0]["error"]
```

**1b.** 新建 `py/tests/test_delist_indeterminate.py`，覆盖 GG 侧两个消费方：

```python
"""「判定未知」不得覆盖既有掉包记录 —— GG 侧消费方测试。

设计文档：docs/superpowers/specs/2026-09-24-tt-appstore-package-design.md
"""
import os
import sys
import datetime
from unittest.mock import patch

_py_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _py_dir not in sys.path:
    sys.path.insert(0, _py_dir)

import database  # noqa: E402

APPLE_DELISTED = "https://apps.apple.com/vn/app/id6813542964"


def _mk_gg_product_and_package():
    """建一个 GG 产品 + 一个正常状态的包，返回 (pid, pkg_id)。"""
    db = database.get_db()
    db.execute("INSERT INTO products(product_name, status) VALUES('未知态GG产品','')")
    db.commit()
    pid = db.execute("SELECT last_insert_rowid() AS id").fetchone()["id"]
    db.execute(
        "INSERT INTO packages(product_id, series_name, package_name, url, status) "
        "VALUES(?,?,?,?,?)",
        (pid, "GG系列", "com.a.b", APPLE_DELISTED, ""))
    db.commit()
    pkg_id = db.execute("SELECT last_insert_rowid() AS id").fetchone()["id"]
    db.close()
    return pid, pkg_id


def _seed_delisted_row(pkg_id, pid):
    """埋一条「上一轮已掉包」的记录。"""
    db = database.get_db()
    db.execute(
        "INSERT OR REPLACE INTO delist_checks(package_id, product_id, is_delisted, checked_at, error_msg) "
        "VALUES(?,?,?,?,?)",
        (pkg_id, pid, 1, datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"), ""))
    db.commit()
    db.close()


def _read_delist_row(pkg_id):
    db = database.get_db()
    row = db.execute("SELECT is_delisted, error_msg FROM delist_checks WHERE package_id=?",
                     (pkg_id,)).fetchone()
    db.close()
    return dict(row) if row else None


class TestGGManualCheckIndeterminate:
    """GG 手动检测：未知态不覆盖既有判定，但把原因记进 error_msg。"""

    def test_manual_check_keeps_prior_delisted_state(self, client, auth_headers):
        pid, pkg_id = _mk_gg_product_and_package()
        _seed_delisted_row(pkg_id, pid)

        with patch("delist_checker.check_product_packages",
                   return_value=[{"package_id": pkg_id, "product_id": pid,
                                  "is_delisted": None, "error": "HTTP 429 限流，判定未知"}]):
            resp = client.post(f"/api/products/{pid}/check-delist", headers=auth_headers)

        assert resp.status_code == 200
        assert resp.get_json()["results"][0]["is_delisted"] is None

        row = _read_delist_row(pkg_id)
        assert row["is_delisted"] == 1              # 未被覆盖成 0
        assert "429" in row["error_msg"]            # 原因留痕


class TestGGSchedulerIndeterminate:
    """GG 定时检测：未知态不覆盖既有判定。"""

    def test_scheduler_keeps_prior_delisted_state(self, client, auth_headers, monkeypatch):
        import main

        pid, pkg_id = _mk_gg_product_and_package()
        _seed_delisted_row(pkg_id, pid)

        monkeypatch.setattr("delist_checker.check_url_delisted",
                            lambda url, pool=None: (None, "HTTP 429 限流，判定未知"))
        monkeypatch.setattr(main, "_build_delist_proxy_pool", lambda: None)
        monkeypatch.setattr(main, "_send_telegram_notifications",
                            lambda db_, pkgs: None)

        main._run_delist_check_once()

        row = _read_delist_row(pkg_id)
        assert row["is_delisted"] == 1
        assert "429" in row["error_msg"]


class TestGGManualCheckEmptyUrl:
    """空 url 包（GG 可创建）同样不得把既有掉包记录抹成正常。"""

    def test_manual_check_empty_url_keeps_prior_delisted_state(self, client, auth_headers):
        db = database.get_db()
        db.execute("INSERT INTO products(product_name, status) VALUES('空url产品','')")
        db.commit()
        pid = db.execute("SELECT last_insert_rowid() AS id").fetchone()["id"]
        # GG 加包端点不校验 url，所以这种行真实存在
        db.execute(
            "INSERT INTO packages(product_id, series_name, package_name, url, status) "
            "VALUES(?,?,?,?,?)",
            (pid, "GG系列", "com.a.b", "", ""))
        db.commit()
        pkg_id = db.execute("SELECT last_insert_rowid() AS id").fetchone()["id"]
        db.close()

        _seed_delisted_row(pkg_id, pid)

        resp = client.post(f"/api/products/{pid}/check-delist", headers=auth_headers)

        assert resp.status_code == 200
        row = _read_delist_row(pkg_id)
        assert row["is_delisted"] == 1              # 未被覆盖成 0
        assert "无法判定" in row["error_msg"]


class TestEmptyUrlJudgedIndeterminate:
    """delist_checker 层：空 url 一律判「未知」，不再判「正常」。"""

    def test_check_url_delisted_empty_url_returns_none(self):
        from delist_checker import check_url_delisted

        is_delisted, error = check_url_delisted("")

        assert is_delisted is None
        assert "无法判定" in error

    def test_check_product_packages_empty_url_returns_none(self):
        from unittest.mock import patch
        from delist_checker import check_product_packages

        with patch("delist_checker.requests.get") as mock_get:
            results = check_product_packages(1, [{"id": 1, "url": "", "package_name": "test.a"}])

        mock_get.assert_not_called()                # 空 url 仍不发请求
        assert results[0]["is_delisted"] is None
        assert "无法判定" in results[0]["error"]
```

**1c.** 追加到 `py/tests/test_tt_appstore_package.py` 末尾（`update_package` 收口的测试）：

```python
class TestUpdatePackageExplicitEmptyUrl:
    """显式传空 url 时不得回落库里 url 而放行（否则落库成包名与 url 皆空）。"""

    def _make_apple_pkg(self, client, tt_headers):
        pid = client.post("/api/tt/products/create", headers=tt_headers, json={
            "product_name": "空url收口产品",
        }).get_json()["id"]
        pkg_id = client.post(f"/api/tt/products/{pid}/packages", headers=tt_headers, json={
            "type": "package", "series_name": "S1", "package_name": "", "url": APPLE_LIVE,
        }).get_json()["id"]
        return pid, pkg_id

    def test_explicit_empty_url_rejected(self, client, tt_headers):
        _, pkg_id = self._make_apple_pkg(client, tt_headers)

        resp = client.put(f"/api/tt/packages/{pkg_id}", headers=tt_headers,
                          json={"package_name": "", "url": ""})

        assert resp.status_code == 400
        assert "包名" in resp.get_json()["error"]

    def test_omitting_url_still_allowed(self, client, tt_headers):
        """没传 url（本次只清包名）仍按库里的苹果 url 放行 —— 既有能力不被削弱。"""
        _, pkg_id = self._make_apple_pkg(client, tt_headers)

        resp = client.put(f"/api/tt/packages/{pkg_id}", headers=tt_headers,
                          json={"package_name": ""})

        assert resp.status_code == 200
```


- [ ] **Step 2: 跑测试确认失败**

Run: `cd py && python -m pytest tests/test_delist_indeterminate.py tests/test_tt_appstore_package.py "tests/test_tt_delist_notification.py::TestTtDelistScheduler::test_indeterminate_does_not_overwrite_existing_delisted" -v`

Expected: FAIL ——
- `assert 0 == 1`（既有掉包记录被 `1 if None else 0` 覆盖成 0）
- `TestGGManualCheckEmptyUrl` FAIL（空 url 仍被判「正常」→ 覆盖成 0）
- `TestEmptyUrlJudgedIndeterminate` 两条 FAIL（现在返回 `False` 而非 `None`）
- `TestUpdatePackageExplicitEmptyUrl::test_explicit_empty_url_rejected` FAIL（现在返回 200 而非 400）

> GG 侧通知只需 mock 一个函数：`main._send_telegram_notifications(db, pkgs)`（`main.py:8570`）。
> 邮件没有独立函数，是调度器内联发的，且被 `if delisted_list:` 闸门挡住 ——
> 判定未知时 `delisted_list` 为空，邮件路径根本不会进入，无需 mock。
>
> **注意**：`tests/test_delist_checker.py` 的两个既有测试在这一步**仍应通过**（它们钉的是旧行为），
> 要到 Step 3 的 3e 才连同实现一起改断言。若你在 Step 2 就把它们改了，那是超前改动。

- [ ] **Step 3: 实现**

**3a. TT 定时循环**（`py/main.py` 约 8846-8872，`for pkg, is_delisted, error in checked:` 整段替换）：

```python
        for pkg, is_delisted, error in checked:
            # 判定未知（限流/服务端异常）：不写库，保留上一轮判定结果。
            # 旧逻辑用 `1 if is_delisted else 0` 无条件覆盖，429 会把正确的掉包记录抹成 0。
            # tt_delist_checks 无 error_msg 列，原因只通过下面的 results 返回体暴露。
            if is_delisted is None:
                results.append({
                    "package_id": pkg["package_id"],
                    "product_id": pkg["product_id"],
                    "package_name": pkg.get("package_name", ""),
                    "is_delisted": None,
                    "error": error,
                })
                continue

            was_delisted = False
            if is_delisted:
                prev = db.execute(
                    "SELECT is_delisted FROM tt_delist_checks WHERE package_id=?",
                    (pkg["package_id"],)
                ).fetchone()
                was_delisted = prev is not None and prev["is_delisted"] == 1

            db.execute(
                "INSERT OR REPLACE INTO tt_delist_checks(package_id, is_delisted, checked_at) "
                "VALUES(?, ?, ?)",
                (pkg["package_id"], 1 if is_delisted else 0, now)
            )
            results.append({
                "package_id": pkg["package_id"],
                "product_id": pkg["product_id"],
                "package_name": pkg.get("package_name", ""),
                "is_delisted": is_delisted,
                "error": error,
            })
            if is_delisted:
                delisted_list.append(pkg)
                if not was_delisted:
                    newly_delisted_list.append(pkg)
```

**3b. GG 定时循环**（`py/main.py` 约 8680-8709，同一形状整段替换）：

```python
        for pkg, is_delisted, error in checked:
            # 判定未知（限流/服务端异常）：不覆盖既有判定，只把原因写进 error_msg。
            # 不能走 INSERT OR REPLACE —— 那会把上一轮正确的 is_delisted=1 抹成 0。
            if is_delisted is None:
                db.execute(
                    "UPDATE delist_checks SET error_msg=? WHERE package_id=?",
                    (error, pkg["package_id"]))
                results.append({
                    "package_id": pkg["package_id"],
                    "product_id": pkg["product_id"],
                    "package_name": pkg.get("package_name", ""),
                    "is_delisted": None,
                    "error": error,
                })
                continue

            # 检查是否此前已标记为掉包（用于 Telegram 去重）
            was_delisted = False
            if is_delisted:
                prev = db.execute(
                    "SELECT is_delisted FROM delist_checks WHERE package_id=?",
                    (pkg["package_id"],)
                ).fetchone()
                was_delisted = prev is not None and prev["is_delisted"] == 1

            # 写 DB
            db.execute(
                "INSERT OR REPLACE INTO delist_checks(package_id, product_id, is_delisted, checked_at, error_msg) "
                "VALUES(?, ?, ?, ?, ?)",
                (pkg["package_id"], pkg["product_id"], 1 if is_delisted else 0, now, error)
            )
            results.append({
                "package_id": pkg["package_id"],
                "product_id": pkg["product_id"],
                "package_name": pkg.get("package_name", ""),
                "is_delisted": is_delisted,
                "error": error,
            })
            if is_delisted:
                delisted_list.append(pkg)
                if not was_delisted:
                    newly_delisted_list.append(pkg)
```

> 「未知」只 `UPDATE` 而不 insert：若该包从无检测记录，受影响行数为 0，不产生新行 —— 这正是期望行为（没有判定，就不该有记录）。

**3c. GG 手动循环**（`py/main.py`，`for r in results:` 处）：

```python
    for r in results:
        # 判定未知：不覆盖既有判定，只记录原因
        if r["is_delisted"] is None:
            db.execute("UPDATE delist_checks SET error_msg=? WHERE package_id=?",
                       (r.get("error", ""), r["package_id"]))
            continue

        db.execute(
            "INSERT OR REPLACE INTO delist_checks(package_id, product_id, is_delisted, checked_at, error_msg) "
            "VALUES(?, ?, ?, ?, ?)",
            (r["package_id"], pid, 1 if r["is_delisted"] else 0, now, r.get("error", ""))
        )
        if r["is_delisted"]:
            newly_delisted.append(r)
```

**3d. TT 手动循环**（`py/routes/tt_routes.py`，`for r in results:` 处）：

```python
    for r in results:
        # 判定未知（限流/服务端异常）：不写库，保留上一轮判定结果
        if r["is_delisted"] is None:
            continue
        db.execute(
            "INSERT OR REPLACE INTO tt_delist_checks(package_id, is_delisted, checked_at) "
            "VALUES(?, ?, ?)",
            (r["package_id"], 1 if r["is_delisted"] else 0, now))
```

（该处 `if any(r["is_delisted"] for r in results):` 不变 —— `None` 是 falsy，不会误触发通知。）

**3e. 空 url 也归为「未知」**（同族缺陷收口，用户 2026-09-24 裁定「一并收口」）

理由：`check_product_packages` 现在对空 url 返回 `is_delisted=False`（=「正常」），
经消费方无条件写库后**同样会抹掉上一轮正确的掉包记录** —— 与 429 是同一个缺陷家族。
且可达性已证实：GG 手动检测取包 SQL（`main.py:3619-3622`）没有 `url != ''` 过滤，
而 GG 加包端点（`main.py:3401-3414`）**只要求包名、不要求 url**，所以空 url 包能被创建。

改 `py/delist_checker.py` 两处（模块契约统一为「无法判定 → `None`」）：

```python
    if not url or not url.strip():
        return None, "URL 为空，无法判定"
```

（原为 `return False, ""`，在 `check_url_delisted` 开头。）

```python
        if not url:
            results.append({
                "package_id": pkg_id,
                "product_id": product_id,
                "is_delisted": None,
                "error": "URL 为空，无法判定",
            })
            continue
```

（原为 `"is_delisted": False, "error": ""`，在 `check_product_packages` 循环内。）

**同步更新两个钉住旧行为的既有测试** —— 是**改断言并注明语义变更，不是删除**：

- `tests/test_delist_checker.py` 的 `test_empty_url_returns_false` 改名为
  `test_empty_url_returns_none`，断言改为 `is_delisted is None` 且 `"无法判定" in error`，
  docstring 改为「空 URL 无法判定 → 返回 None（调用方不得据此写「正常」）」。
- `tests/test_delist_checker.py` 的 `test_skips_packages_without_url` 的
  `assert all(r["is_delisted"] is False for r in results)` 改为 `is None`，
  保留 `mock_get.assert_not_called()`（空 url 仍不发请求）。

**3f. `update_package` 收口 url 语义**（用户 2026-09-24 裁定「顺手收口」）

`py/routes/tt_routes.py` 的 `update_package` 内联校验里，
`updates.get('url') or existing['url']` 把「本次没传 url」与「本次显式传空串」混同，
于是对存量苹果包 `PUT {"package_name": "", "url": ""}` 会回落用库里的苹果 url 而放行，
最终落库成「包名与 url 皆空」—— 正是这条校验要拦的形态。改成先判 key 存在性：

```python
    # re-enforce type 规则：package 必须填写包名（App Store 链接除外，与 add_package 语义一致）
    pkg_type = updates.get('type', existing['type'])
    if pkg_type == 'package' and 'package_name' in updates and not updates['package_name']:
        # 本次显式传了 url 就用本次的（空串即「清空」→ 不放行）；
        # 本次没传 url 才回落库里的 url 判断是不是苹果链接。
        if 'url' in updates:
            effective_url = updates['url']
        else:
            effective_url = existing['url']
        if not _is_appstore_url(effective_url):
            return err('跑包必须填写包名', 400)
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd py && python -m pytest tests/test_delist_indeterminate.py tests/test_delist_checker.py tests/test_tt_appstore_package.py "tests/test_tt_delist_notification.py::TestTtDelistScheduler" -v`

Expected: 全绿（含 3e 改过断言的两个既有测试）。

Run: `cd py && python -m pytest tests/ -q`

Expected: 全绿（`test_delist_api.py` 整文件是注释状态、`test_tt_routes.py` 的两个测试按现行决定注释，均不参与收集）。

- [ ] **Step 5: 提交**

```bash
git add py/main.py py/routes/tt_routes.py py/delist_checker.py py/tests/test_delist_checker.py py/tests/test_delist_indeterminate.py py/tests/test_tt_delist_notification.py py/tests/test_tt_appstore_package.py
git commit -m "fix(delist): 判定未知时不覆盖既有掉包记录，空 url 一并归为未知（GG/TT 共四处消费方）"
```

---

## Task 3b: 「拿不到判定」的五类残余全部归为「未知」

> 用户 2026-09-24 裁定：与 429 后果同型，一并收口（spec §12.3）。
> 本任务**推翻 Task 1 的一处显式决定** —— Task 1 曾明文要求超时/连接失败/代理失败保持
> `False`（理由是「不让未知态扩大化」）。裁定后该理由作废，模块契约统一为
> 「拿不到判定 → `None`」。

**Files:**
- Modify: `py/delist_checker.py`（`check_url_delisted` 的 5 个失败分支 + 两处 docstring/注释）
- Modify: `py/tests/test_delist_checker.py`（5 条既有测试改断言/改名，注明语义变更）

**Interfaces:**
- Consumes: Task 3 已落地的消费方 `is None` 守卫（本任务只改生产侧，消费方无需再动）
- Produces: `check_url_delisted` 只在**拿到了判定**时才返回 `False`；其余一律 `None`

**关键分界（不得越界）**：`None` 只吸收「拿不到判定」，**不得**吸收「拿到了判定且判为正常」。
200 正常页面、404 掉包页面的判定一个字都不许动。

- [ ] **Step 1: 改 5 个失败分支（错误文案保留原文并追加「，无法判定」）**

`check_url_delisted` 直连分支（`if proxy_pool is None:` 内的 try/except）改成：

```python
    # 无代理池：直连；拿不到判定（限流/服务端异常/超时/连接失败/解析失败）一律返回「未知」
    if proxy_pool is None:
        try:
            return _request_and_judge(url, None)
        except DelistIndeterminate as e:
            return None, f"{e} 限流或服务端异常，判定未知"
        except requests.Timeout:
            return None, "请求超时，无法判定"
        except requests.ConnectionError:
            return None, "网络连接失败，无法判定"
        except Exception as e:
            return None, f"{e}，无法判定"
```

代理分支两处返回值改成：

```python
    # 有代理池：失败换下一个代理重试，绝不因代理失败误判为掉包
    if proxy_pool.count == 0:
        return None, "代理池为空，无法判定"
```

```python
    if last_indeterminate:
        return None, f"代理响应异常（限流/服务端）: {last_indeterminate}"
    return None, f"代理全部失败: {last_error}，无法判定"
```

> 代理分支**循环内**的逐代理 `except` 全部保持原样（继续换下一个代理重试），
> 只改「重试耗尽后」的最终返回。`_request_and_judge` 一字不动。

- [ ] **Step 2: 修正两处失真的文档措辞**

`check_url_delisted` 的 docstring Returns 段：

```python
    Returns:
        (is_delisted, error)：
          True  → 已掉包
          False → 正常（拿到了判定，且判为在架）
          None  → 判定未知（限流/服务端异常/超时/连接失败/解析失败/空 url），
                  调用方应保留上一次判定结果，不得覆盖
```

`check_product_packages` 的 docstring 末句「函数只做透传」自相矛盾（该函数自身在空 url
分支返回 `None`），改成：

```python
        is_delisted 为 True/False/None（None 表示判定未知）。
        空 url 由本函数直接判为 None（无法判定），其余原样透传 check_url_delisted 的结果。
```

- [ ] **Step 3: 改 5 条既有测试的断言（只改断言/改名，不删除）**

`TestCheckUrlDelisted` 三条 —— 断言 `is False` 改 `is None`，名字由
`test_returns_false_*` 改为 `test_returns_none_*`，docstring 说明「拿不到判定 → 未知」。
**`error` 的既有断言原样保留**（文案保留原文，故 `"超时" in error`、`error != ""` 仍成立）：

```python
    def test_returns_none_on_timeout(self):
        """请求超时 → 判定未知（拿不到判定，不得当作「正常」覆盖既有记录）。"""
        from delist_checker import check_url_delisted

        with patch("delist_checker.requests.get", side_effect=requests.Timeout("timed out")):
            is_delisted, error = check_url_delisted("https://play.google.com/store/apps/details?id=com.example.app")

        assert is_delisted is None
        assert "超时" in error
```

`test_returns_none_on_connection_error` / `test_returns_none_on_general_exception`
同法（断言 `is None`，保留 `assert error != ""`）。

`TestCheckUrlDelistedWithProxies` 两条：

```python
        assert is_delisted is None          # 原 assert is_delisted is False
        assert "代理" in error              # 保留
        assert mock_get.call_count == 2     # 保留
```

```python
        assert is_delisted is None                  # 原 assert is_delisted is False
        assert "代理池为空" in error                # 原 error == "代理池为空"（文案已追加「，无法判定」）
        mock_get.assert_not_called()                # 保留
```

`TestIndeterminateStatus.test_timeout_still_false_not_none` 的整个前提已被裁定推翻，
**改名并反转断言 + 注明语义变更**（这是 Task 1 新增的用例，同样只改不删）：

```python
    def test_timeout_is_none_not_false(self):
        """超时改判未知（2026-09-24 裁定：与 429 同型，拿不到判定不得覆盖既有记录）。

        本用例的前身 test_timeout_still_false_not_none 钉的是「不让未知态扩大化」，
        该理由已被裁定作废。「失败绝不判掉包」不变量不受影响 —— None 既非 True 也非 False。
        """
        from delist_checker import check_url_delisted

        with patch("delist_checker.requests.get", side_effect=requests.Timeout("timed out")):
            is_delisted, error = check_url_delisted("https://play.google.com/store/apps/details?id=com.a.b")

        assert is_delisted is None
        assert error != ""
```

- [ ] **Step 4: 新增两条用例，钉住「拿到了判定仍是 False」的边界**

在 `TestIndeterminateStatus` 内追加：

```python
    def test_malformed_url_returns_none(self):
        """畸形 url（漏写 scheme）→ 判定未知，而非「正常」。

        requests.MissingSchema 不是 ConnectionError 子类，原兜底 except 会吞成 False，
        经消费方写库后抹掉既有掉包记录。实测确认过的事实。
        """
        from delist_checker import check_url_delisted

        is_delisted, error = check_url_delisted("play.google.com/store/apps/details?id=com.x.y")

        assert is_delisted is None
        assert error != ""

    def test_200_normal_still_false_after_unknown_widening(self):
        """边界：200 且无关键词仍是 False —— 「未知」不得吸收「判为正常」。"""
        from delist_checker import check_url_delisted

        resp = MagicMock(status_code=200, text="<html>welcome to the app page</html>")
        with patch("delist_checker.requests.get", return_value=resp):
            is_delisted, error = check_url_delisted("https://play.google.com/store/apps/details?id=com.a.b")

        assert is_delisted is False
        assert error == ""
```

> `MagicMock` 若文件顶部未导入，在 Step 4 一并补 `from unittest.mock import MagicMock, patch`
> （该文件已导入 `patch`，按实际导入行调整，不要重复导入）。

- [ ] **Step 5: 跑测试**

Run: `cd py && python -m pytest tests/test_delist_checker.py tests/test_delist_indeterminate.py tests/test_tt_appstore_package.py "tests/test_tt_delist_notification.py::TestTtDelistScheduler" -v`

Expected: 全绿（含 Step 3 改过断言的 5 条 + Step 4 新增的 2 条）。

Run: `cd py && python -m pytest tests/ -q`

Expected: 全绿。

> 若出现 `TestGGManualCheckEmptyUrl` 之类依赖 `is False` 的失败，**不要**改那些用例的
> 期望值去迁就，先看它钉的是不是「拿到判定判为正常」的边界 —— 那类边界必须保持语义。

- [ ] **Step 6: 提交**

逐文件 add（**禁止 `git add -A`**），提交前 `git status` 核对暂存区无并行会话的改动：

```bash
git add py/delist_checker.py py/tests/test_delist_checker.py
git commit -m "fix(delist): 超时/连接失败/解析失败/代理失败统一改判「未知」，不再覆盖既有判定"
```

---

## Task 4: 前端录入放行与 iOS 标识

**Files:**
- Modify: `frontend/src/components/TtAddPackageModal.vue`（第 9、86、93 行）
- Modify: `frontend/src/components/TtProductCard.vue`（第 85-88 行 + `<script setup>` 加判定函数 + `checkDelist`）
- Modify: `frontend/src/components/ProductCard.vue`（`checkDelist`）

**Interfaces:**
- Consumes: 后端 Task 2 已放行苹果空包名；Task 1/3/3b 的 `is_delisted` 可能为 `null`（判定未知）
- Produces: 前端不再拦截苹果包；卡片上苹果包显示灰色 `iOS` 占位；检测提示语不再把「本轮全部未知」说成「所有包均正常」

> 本任务**没有自动化测试** —— 该仓库前端无测试框架（`frontend/package.json` 只有 `dev`/`build`/`preview` 三个脚本，devDependencies 里没有 vitest/jest）。验证方式为 `npm run build` 通过 + 下面的浏览器人工核对清单。

- [ ] **Step 1: 改 TtAddPackageModal 的校验与文案**

第 9 行 placeholder：

```html
        <el-input v-model="form.text" type="textarea" :rows="6" placeholder="粘贴包含 Google Play / App Store 链接的文本..." />
```

第 86 行提示语：

```javascript
    if (!parsed.value.length) ElMessage.warning('未找到有效的 Google Play / App Store 链接')
```

第 93 行手动添加校验 —— 在文件顶部 `<script setup>` 的 import 之后加判定函数，然后改校验。先在 `import { ElMessage } from 'element-plus'` 下面插入：

```javascript
// App Store 的两个合法 host（与后端 _is_appstore_url 同口径）
const APPSTORE_HOSTS = ['apps.apple.com', 'itunes.apple.com']
function isAppstoreUrl(url) {
  try {
    return APPSTORE_HOSTS.includes(new URL(String(url || '').trim()).hostname.toLowerCase())
  } catch {
    return false
  }
}
```

再把第 93 行替换成：

```javascript
  if (manual.type === 'package' && !manual.package_name.trim() && !isAppstoreUrl(manual.url)) {
    return ElMessage.warning('跑包必须填写包名（App Store 链接可留空）')
  }
```

- [ ] **Step 2: 改 TtProductCard 的 iOS 占位**

在 `frontend/src/components/TtProductCard.vue` 的 `<script setup>` 里（与 `TtAddPackageModal` 同口径），加：

```javascript
// 苹果包：URL 是 App Store 且包名为空 → 列表里显示灰色 iOS 占位
const APPSTORE_HOSTS = ['apps.apple.com', 'itunes.apple.com']
function isIosPkg(pkg) {
  if (pkg.type === 'pwa') return false
  if ((pkg.package_name || '').trim()) return false
  try {
    return APPSTORE_HOSTS.includes(new URL(String(pkg.url || '').trim()).hostname.toLowerCase())
  } catch {
    return false
  }
}
```

把第 86 行那个渲染包名的 `<span>` 替换成两个分支（保留它前后的两个 `│` 分隔符不动）：

```html
          <span v-if="isIosPkg(pkg)" style="font-size:11px;color:#999;flex-shrink:0;">iOS</span>
          <span v-else-if="pkg.type !== 'pwa'" style="font-family:monospace;cursor:pointer;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;" @click.stop="copy(pkg.package_name)">{{ pkg.package_name }}</span>
```

`iOS` 占位符**不绑点击事件、不可复制**（避免复制出无意义的字符串）。

- [ ] **Step 3: 修正「本轮全部未知」时的误报提示（用户 2026-09-24 裁定，spec §12.4）**

`TtProductCard.vue` 的 `checkDelist` 与 `ProductCard.vue` 的 `checkDelist` 目前都在
无掉包时无条件弹「所有包均正常 ✓」。整批 429 限流时本轮结果全是 `null`，该提示会说谎。
两处改成同样口径（下面是 `TtProductCard.vue` 的形态，`ProductCard.vue` 按自己的
`res.success` 包裹结构套用同一段判断）：

```javascript
    const results = res.results || []
    const delisted = results.filter(r => r.is_delisted)
    // 判定未知（限流/网络异常/空 url）：is_delisted 为 null 或缺失
    const unknown = results.filter(r => r.is_delisted == null)
    if (delisted.length) {
      ElMessage.warning(`检测到 ${delisted.length} 个包已掉包！`)
    } else if (unknown.length) {
      ElMessage.warning(`${unknown.length} 个包本轮未能判定（限流或网络异常），已保留上次判定结果`)
    } else {
      ElMessage.success('所有包均正常 ✓')
    }
```

**严格增量**：`unknown.length === 0` 时行为与改前逐字一致（含 `results` 为空仍走
「所有包均正常」这一原有行为）。只有「存在未知」这一新增情形改变文案。
`emit('refresh')` 的调用位置按各自文件原有位置保持不动。

- [ ] **Step 4: 构建验证**

Run: `cd frontend && npm run build`

Expected: 构建成功，无 Vue 编译错误（`v-else-if` 紧跟 `v-if`，不报 "v-else-if has no adjacent v-if"）。

- [ ] **Step 5: 浏览器人工核对**

前置：后端已重启（用户执行），前端已 `npm run build`。

1. 打开 TT 产品管理 → 某产品 → 「➕ 添加包」
2. 「粘贴内容」里粘 `神包上线：测试苹果\nhttps://apps.apple.com/vn/app/id6804355336` → 点「预览解析」
   - 期望：提示「识别 1 个包」，表格里包名列为**空**、链接列是苹果链接、类型是「跑包」；**不再**出现「未找到有效的 Google Play / App Store 链接」
3. 点「💾 添加」→ 期望提示「已添加 1 个包」
4. 回到产品卡片 → 期望该行显示 `跑包 │ 测试苹果 │ iOS │ https://apps.apple.com/... 🔗`，**没有两个相邻的 `│`**
5. 手动添加区：类型「跑包」+ 链接填苹果链接 + **包名留空** → 点「添加」→ 期望成功
6. 手动添加区：类型「跑包」+ 链接填 `https://play.google.com/store/apps/details?id=com.a.b` + 包名留空 → 期望仍被拦截，提示「跑包必须填写包名（App Store 链接可留空）」
7. 对该产品点「是否掉包」手动检测 → 期望苹果包出现在检测结果里（说明掉包检测覆盖到了苹果包）
8. 提示语核对：构造一个「本轮未能判定」的场景（例如给某产品加一个空 url 的 GG 包，或在 GG 产品卡片上检测一个 url 为空的包），点「是否掉包」
   - 期望：提示「N 个包本轮未能判定（限流或网络异常），已保留上次判定结果」，**不再**出现「所有包均正常 ✓」
   - 反例核对：一个所有包 url 都正常的 GG 产品，点检测 → 期望仍是「所有包均正常 ✓」

- [ ] **Step 6: 提交**

逐文件 add（**禁止 `git add -A`**），提交前 `git status` 核对暂存区无并行会话的改动：

```bash
git add frontend/src/components/TtAddPackageModal.vue frontend/src/components/TtProductCard.vue frontend/src/components/ProductCard.vue
git commit -m "feat(tt): 前端放行 App Store 链接，苹果包以灰色 iOS 占位展示"
```

---

## Task 5: 文档同步

**Files:**
- Modify: `AGENTS.md`

**Interfaces:**
- Consumes: Task 1-4 的最终行为
- Produces: 文档与实现一致

- [ ] **Step 1: 更新 AGENTS.md 的 TT 描述**

在 `## 新增功能模块` 的 `### TT（TikTok）平台` 一节里，`- **数据提取**` 那条之后补一条：

```markdown
- **投放对象支持 App Store 链接**：苹果包复用 `type='package'`，URL 是
  `apps.apple.com` / `itunes.apple.com` 时**包名允许留空**（不自动填数字 id），
  卡片上以灰色 `iOS` 占位展示；安卓包仍强制填写包名。域名判定按解析出的 host
  全等比较（防 `evil.com/?u=apps.apple.com` 误判）
```

- [ ] **Step 2: 更新 AGENTS.md 的掉包检测描述**

在 `### 掉包检测与通知` 一节的**核心逻辑**列表里，`- **检测方式**` 那条之后补一条：

```markdown
- **判定第三态（未知）**：`is_delisted` 由 `bool` 扩为 **`bool | None`**，`None` = 判定未知。
  「拿不到判定」的七类一律归为 `None`：HTTP 429/5xx、请求超时、网络连接失败、
  链接解析失败（畸形 url）、代理池为空、代理全部失败、url 为空。
  消费方（GG 定时 / GG 手动 / TT 定时 / TT 手动四处）遇 `None` **一律不写库**，
  保留上一轮判定结果，也不触发掉包通知。
  反面边界：404 → 掉包、200 正常页 → 正常，**「拿到了判定」的结果不得改判 `None`**。
  起因：App Store 对掉包链接返回 404，被限流时返回 429，两者响应体同为
  2383 字节，只能靠状态码区分；旧逻辑只认 404 且无条件 `INSERT OR REPLACE`，
  会把 429（以及超时/代理失败等）当成正常，抹掉正确的掉包记录。
  GG 侧同时把原因写入 `delist_checks.error_msg`
```

- [ ] **Step 3: 登记设计文档索引**（spec §11 要求；项目规则「每次新的文档都要建立索引」）

在 `## 设计文档索引` → `### GG-Server 独立设计文档` 一节的**末尾**追加：

```markdown
- [TT 支持苹果包链接（App Store）+ 掉包判定加固](docs/superpowers/specs/2026-09-24-tt-appstore-package-design.md)
```

- [ ] **Step 4: 提交**

逐文件 add（**禁止 `git add -A`**），提交前 `git status` 核对暂存区无并行会话的改动：

```bash
git add AGENTS.md
git commit -m "docs: AGENTS.md 补充 TT 支持 App Store 链接与掉包判定第三态"
```

---

## 收尾（不属于任何 Task，交付前逐条确认）

- [ ] `cd py && python -m pytest tests/ -q` 全绿
- [ ] `cd frontend && npm run build` 成功
- [ ] **提醒用户重启 Flask 服务**（后端改动生效的前提；不得自行重启）
- [ ] **提醒用户前端已构建**（Tailscale 上其他人只能访问 5001，不 build 看不到改动）
- [ ] 调用 `/code-review` 审查本次改动（涉及校验放行规则，属鉴权相邻改动）
- [ ] 提交 git 并提醒用户

## 明确不做的事（防止实现时漂移）

- 不新增 `type='ios'`，不改 `tt_packages` 表结构
- 不改 GG / FB 的录入链路（`AddPackageModal.vue`、`CopyImportModal.vue`、`utils.py:extract_package_name`）
- 不改 `_guess_series` 的猜名逻辑；苹果链接猜不到时兜底返回空串（与「不自动填」同口径）
- ~~不把「超时/连接失败」改判为未知态~~ —— **此项已被 Task 3b 推翻**（用户 2026-09-24 裁定
  五类「拿不到判定」一并收口）。最终口径：**拿不到判定 → `None`**，涵盖 429/5xx、超时、
  连接失败、解析失败（畸形 url）、代理池为空、代理全部失败、空 url 共七类。
  反面仍然成立：**200 正常页面 / 404 掉包页面这类「拿到了判定」的结果一律不得改判 `None`**。
- 不动 `tt_data_import` 的 JSON 重建逻辑
- 不修 `tt_routes.py:644` 手动检测走直连（`proxy_pool=None`）这一现状 —— 与 `AGENTS.md` 描述不符，已作为疑问提出，待用户裁定
