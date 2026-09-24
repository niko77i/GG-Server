"""匿名可达面（GET）常驻回归测试 —— 钉死 `@jwt_required(optional=True)` 隐身类别。

## 为什么需要这个测试

安全加固计划（2026-09）用「装饰器里有没有 `jwt_required`」来识别「不需要登录即可调用」
的端点（设计文档里的「A 类」）。但 `@jwt_required(optional=True)` 在装饰器层**算「有」**，
于是这类端点**天然隐身**：真实匿名面 20 条，「A 类」只覆盖 3 条。

根因不是「漏扫」，是**判据本身把类别定义在了扫描器视野之外** —— 漏多少条都不会有人发现。
本测试把判据从「装饰器字面」换成「**零 token 实测**」，让这个类别再也无法隐身：

    匿名 GET 全量扫描得到的「非 401」端点集合  ==  显式白名单集合

任何新增的 `optional=True` / 不带 `@jwt_required` 的 GET 端点都会立刻让本测试变红；
任何给白名单端点补上鉴权的改动也会变红（白名单过期）。

## 口径

- 遍历 `app.url_map` 的全部规则，**只取 GET**（`HEAD`/`OPTIONS` 不算，它们是隐式方法）。
- 路径参数替换：`<int:x>` → `1`，`<path:x>` → `1`，其它 `<x>` → `1`。
- **零 token**：不传任何 `Authorization` 头。
- 判定只看「**是不是 401**」。400/404/500 都算「匿名可达」—— 因为鉴权根本不是拦它的原因。
- 只发 GET；本仓库现有匿名 GET 端点均为只读（探针实测零外呼、零写库），故无跳过项。
  扫描期间**封锁非回环网络出口**：本测试会自动发现未来的新端点并请求它们，若不设这道
  闸门，一个「匿名可达 + 会外呼」的新端点就会在跑测试时真的打出去。

## ⚠️ 白名单的性质

下面这张白名单是**当前已知的匿名可达面，是待收口的债务，不是被认可的设计**。
它存在的唯一目的是：**把「现状」冻结成一条对照行**，使得任何对匿名面的增删都必须显式改这张表 ——
从而暴露在 code review 里。**往这张表里加条目，等于宣布一个新的匿名缺口被接受**，
需要用户裁定，而不是实现者的自由裁量。

## ⚠️ 本测试的覆盖边界

- **只覆盖 GET**。`POST /api/browse-file`、`POST /api/browse-save`、`POST /api/browse-folder`、
  `POST /api/products/create`、`POST /api/auth/register` 都是 `optional=True`/无鉴权的**写**端点，
  匿名可达性**尚未被本测试覆盖**（见 `.superpowers/sdd/anon-surface-scan.md`）。
- 本测试只回答「**是否 401**」，不回答「这个端点匿名可达时能读到/写到什么」。
  一个端点被业务闸门二次拦截（如 `_can_browse()`）仍是「非 401」，仍算匿名可达。
- 非 GET 方法的匿名面、带**无效/过期 token** 的行为，都不在本测试范围内。
"""
import collections
import socket as _socket
import warnings

import pytest

# ---------------------------------------------------------------------------
# 白名单：当前已知的匿名可达 GET 端点（规则字符串，含路径参数占位符）
#
# ★ 这是**待收口的债务**，不是被认可的设计。增删此表需在 code review 中显式说明理由。
# ---------------------------------------------------------------------------
ANON_GET_WHITELIST = frozenset({
    # --- 非 API：前端外壳与静态资源 ---
    "/",                        # SPA 首页（main.py:401）
    "/<path:filename>",         # Flask 内置 static（static_url_path=""）⇒ 整个前端 bundle
    "/favicon.ico",             # main.py:73，返回 204 空体
    # --- 无 @jwt_required 的 API ---
    "/api/health",              # main.py:422
    "/api/image",               # main.py:796，扩展名+目录白名单内任意 .png
    "/api/font-file",           # main.py:1681，项目 fonts/ 与系统字体目录内任意字体
    # --- @jwt_required(optional=True)：装饰器层「有鉴权」但匿名放行 ---
    # 2026-09-24：A 组 4 条（products/list、users/names、auth/names、settings/account GET）
    # 已收口为强制鉴权，本表不再列出。
    "/api/audio",               # main.py:1106，temp/music/ 下任意文件
    "/api/scrape/download",     # main.py:576，打包 temp/scraped_images/ 下调用方指定的目录
    "/api/video/download",      # main.py:1031
    "/api/audio-replace/download",  # main.py:1212
})

# 扫描需要覆盖的 GET 规则数量的下界。若 url_map 遍历/过滤被改坏，本测试会大声失败，
# 而不是「扫到 0 条 ⇒ 空集 == 非空白名单？」侥幸通过。
_MIN_EXPECTED_GET_RULES = 100


def _materialize(rule):
    """把 url_map 规则里的路径参数替换成具体值，得到可直接请求的路径。

    `<int:x>` → `1`，`<path:x>` → `1`，其它 `<x>` → `1`。
    统一替换成 `1` 是有意的：对 `<path:x>` 而言它仍是一个合法路径段，
    且足够让那些「有参数才走到业务逻辑」的端点暴露在鉴权层之后。
    """
    path = str(rule)
    for arg in rule.arguments:
        for converter in ("int", "path", "string", "float", "uuid", "any"):
            path = path.replace("<%s:%s>" % (converter, arg), "1")
        path = path.replace("<%s>" % arg, "1")
    return path


class _EgressBlocked(RuntimeError):
    pass


def _sweep(client):
    """零 token 遍历全部 GET 规则，返回 {rule_str: (path, status)}。

    非回环 connect 一律抛错并记录 —— 防止自动发现的「新」端点真的打外部网络。
    """
    real_connect = _socket.socket.connect
    blocked = []

    def guarded_connect(self, address):
        host = address[0] if isinstance(address, tuple) else str(address)
        if isinstance(host, str) and host not in ("127.0.0.1", "::1", "localhost", ""):
            blocked.append(host)
            raise _EgressBlocked("非回环出口被测试封锁: %r" % (address,))
        return real_connect(self, address)

    results = collections.OrderedDict()
    _socket.socket.connect = guarded_connect
    try:
        for rule in sorted(client.application.url_map.iter_rules(), key=lambda r: str(r)):
            if "GET" not in rule.methods:
                continue  # 只扫 GET；HEAD/OPTIONS 是隐式方法，不算
            path = _materialize(rule)
            try:
                resp = client.get(path)  # 零 token：不带 Authorization 头
                status = resp.status_code
            except Exception as exc:  # noqa: BLE001
                # 连异常都算「非 401」：鉴权没能拦住它
                status = "EXC:%s" % type(exc).__name__
            results[str(rule)] = (path, status)
    finally:
        _socket.socket.connect = real_connect

    return results, blocked


def _describe(rule, path, status):
    return "  %-40s (请求 %-40s) → %s" % (rule, path, status)


def test_anonymous_get_surface_matches_whitelist(client):
    """承重断言：匿名 GET 全量扫描的「非 401」集合 == 显式白名单集合。"""
    results, blocked = _sweep(client)

    assert len(results) >= _MIN_EXPECTED_GET_RULES, (
        "GET 规则只扫到 %d 条（下界 %d）—— 遍历或过滤逻辑已被改坏，"
        "本测试的结果不可信，先修扫描本身。" % (len(results), _MIN_EXPECTED_GET_RULES)
    )

    anon_actual = {rule for rule, (_p, st) in results.items() if st != 401}

    # 5xx 是独立信号：不是 401 就意味着鉴权没拦，但 5xx 通常还意味着崩溃。
    server_errors = ["%s %s → %s" % (rule, path, st)
                     for rule, (path, st) in results.items()
                     if isinstance(st, int) and 500 <= st < 600]
    if server_errors:
        warnings.warn(
            "匿名 GET 扫描中发现 %d 条 5xx（非 401 ⇒ 匿名可达，且可能是崩溃）：\n  %s"
            % (len(server_errors), "\n  ".join(server_errors)),
            stacklevel=2,
        )
    if blocked:
        warnings.warn(
            "匿名 GET 扫描中端点尝试了外部网络出口（已被测试封锁）：%s" % (blocked,),
            stacklevel=2,
        )

    newly_anon = sorted(anon_actual - ANON_GET_WHITELIST)
    whitelist_stale = sorted(ANON_GET_WHITELIST - anon_actual)

    if newly_anon or whitelist_stale:
        lines = []
        if newly_anon:
            lines.append(
                "★ 新的匿名可达 GET 端点（零 token 返回非 401，但不在白名单）："
            )
            lines.extend(_describe(r, *results[r]) for r in newly_anon)
            lines.append(
                "  ⇒ 这可能是新加的 @jwt_required(optional=True)，或忘了加 @jwt_required。\n"
                "    若非有意，请补 @jwt_required()；若确为有意，需用户裁定后才能加进白名单。"
            )
        if whitelist_stale:
            lines.append(
                "★ 白名单已过期（白名单里的端点现在返回 401，说明有人给它加了鉴权）："
            )
            for r in whitelist_stale:
                lines.append(_describe(r, *results[r]) if r in results
                             else "  %-40s → 规则已不存在（被删除或改名）" % r)
            lines.append(
                "  ⇒ 匿名面已收口是好事，请把该条从 ANON_GET_WHITELIST 里删掉。"
            )
        pytest.fail(
            "匿名可达面与白名单不一致（这是承重断言，不允许忽略）：\n" + "\n".join(lines)
        )


def test_whitelist_entries_all_resolve_to_real_get_rules(client):
    """元断言：白名单里不能有「拼错/已删除/不是 GET」的幽灵条目。

    没有这条，白名单可能悄悄腐烂成一张与实际规则名对不上的表，
    而承重断言仍可能因为双向抵消而「看起来对」。
    """
    get_rules = {str(r) for r in client.application.url_map.iter_rules()
                 if "GET" in r.methods}
    ghosts = sorted(ANON_GET_WHITELIST - get_rules)
    assert not ghosts, (
        "白名单里这些条目不对应任何已注册的 GET 规则（拼写错误？规则被改名/删除？）：\n  %s"
        % "\n  ".join(ghosts)
    )
