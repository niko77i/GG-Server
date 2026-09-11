# 掉包检测走代理 IP — 设计文档

## 1. 需求描述

当前「谷歌掉包检测」定时任务直接使用服务端自身的出口 IP 访问 Google Play 链接来判断包是否掉包（`py/delist_checker.py` 的 `check_url_delisted` 使用裸 `requests.get`）。

需求：**改为通过代理 IP 访问**，避免使用服务端 IP 被 Google 风控/限制，同时支持多出口 IP 轮换以降低单 IP 被限流的风险。

### 现状小结（已核实代码）

- 核心检测函数：[py/delist_checker.py:25](py/delist_checker.py#L25) `check_url_delisted(url)`，裸 `requests.get`，无 `proxies`。
- 定时任务：[py/main.py:7939](py/main.py#L7939) `_start_delist_scheduler`，每小时执行一次（`time.sleep(3600)`）。
- 单次检测：[py/main.py:7796](py/main.py#L7796) `_run_delist_check_once`，`ThreadPoolExecutor(max_workers=min(len(pkgs), 10))` 并发调用 `check_url_delisted`。
- 手动检测：`check_product_packages`（[py/delist_checker.py:66](py/delist_checker.py#L66)）顺序遍历，最终也走 `check_url_delisted`。
- 配置加载：[py/main.py:315](py/main.py#L315) 从 `config/config.json` 读入 `APP_CONFIG`（含 `smtp`、`telegram` 等段）。

### 代理清单（用户提供）

| 出口 IP | 端口 | 用户名 | 密码 |
|---|---|---|---|
| 107.151.249.31 | 2615 | `<redacted>` | `<redacted>` |
| 107.151.249.31 | 2203 | `<redacted>` | `<redacted>` |
| 107.151.249.31 | 2019 | `<redacted>` | `<redacted>` |
| 107.151.249.31 | 800 | `<redacted>` | `<redacted>` |
| 107.151.249.31 | 623 | `<redacted>` | `<redacted>` |
| 200.160.208.55 | 443 | `<redacted>` | `<redacted>` |

实际只有 **2 个不同出口 IP**：`107.151.249.31`（5 个端口实例）和 `200.160.208.55`。

## 2. 技术方案

### 2.1 配置（config/config.json）

新增 `delist_proxy` 段，采用结构化格式（便于去重、轮换和扩展）：

```json
"delist_proxy": {
    "enabled": true,
    "max_retries": 3,
    "proxies": [
        {"ip": "107.151.249.31", "port": 2615, "username": "<redacted>", "password": "<redacted>"},
        {"ip": "107.151.249.31", "port": 2203, "username": "<redacted>", "password": "<redacted>"},
        {"ip": "107.151.249.31", "port": 2019, "username": "<redacted>", "password": "<redacted>"},
        {"ip": "107.151.249.31", "port": 800,  "username": "<redacted>", "password": "<redacted>"},
        {"ip": "107.151.249.31", "port": 623,  "username": "<redacted>", "password": "<redacted>"},
        {"ip": "200.160.208.55", "port": 443,  "username": "<redacted>", "password": "<redacted>"}
    ]
}
```

- `enabled=false` 时完全回退到当前直连逻辑（向后兼容，出问题可一键关闭）。
- `max_retries`：单个 URL 最多尝试几个不同代理后才判为「检测失败」。

### 2.2 新增代理池模块（`py/proxy_pool.py`）

职责单一，不侵入检测逻辑：

```python
class ProxyPool:
    def __init__(self, proxies_config): ...   # 解析配置，按 (ip, port) 去重
    def next(self) -> dict | None: ...        # 轮询/随机取一个代理，线程安全
    @staticmethod
    def to_requests(proxy: dict) -> dict:     # 转成 requests 的 proxies 参数
        # {"http": "http://user:pass@ip:port", "https": "http://user:pass@ip:port"}
```

- `to_requests` 默认按 **HTTP 代理**（`http://` 前缀）生成；若后续引入 SOCKS5，加 `scheme` 字段即可（`socks5://`）。
- `next()` 用线程安全的循环取用（`itertools.cycle` + 锁，或 `random.choice`），10 并发下每线程各取一个。

### 2.3 检测函数改造（`py/delist_checker.py`）

**纯增量**，`check_url_delisted` 增加一个可选参数，缺省时行为与现在完全一致：

```python
def check_url_delisted(url: str, proxy_pool=None) -> tuple[bool, str]:
    # proxy_pool 为 None → 走原直连逻辑（零改动）
    # proxy_pool 提供 → 遍历代理重试，失败换下一个
```

重试流程（仅当 `proxy_pool` 提供时启用）：

1. 从池里取代理 → 转成 `proxies` 参数 → 发请求。
2. 成功拿到响应 → 按原逻辑判 404 / 关键词，返回结果。
3. 代理连接失败 / 超时（`ConnectionError` / `Timeout`）→ 换下一个代理，最多 `max_retries` 次。
4. 所有代理都失败 → 返回 `(False, "代理全部失败: ...")`，**不判为掉包**。

**关键：区分「代理挂了」和「真掉包」**。代理失败只返回带 error 的 `is_delisted=False`，绝不误判成掉包；同时 error 文案带上「代理」字样，便于日志排查。

### 2.4 调用处接入（`py/main.py`）

- 定时任务 `_run_delist_check_once` 内：读取 `APP_CONFIG["delist_proxy"]`，若 `enabled` 则构造 `ProxyPool`，在 `_check_one` 中传给 `check_url_delisted(url, proxy_pool)`。
- 手动检测 `check_product_packages`：同样支持传入 `proxy_pool`（或在其内部读取配置），保证手动检测也走代理。
- 代理池在单次检测任务内构造一次、复用，避免每个 URL 重复解析配置。

## 3. 涉及的文件

| 文件 | 变更类型 | 说明 |
|------|---------|------|
| `config/config.json` | 修改 | 新增 `delist_proxy` 段 |
| `py/proxy_pool.py` | **新建** | 代理池管理（解析、去重、轮换、转 requests 格式） |
| `py/delist_checker.py` | 修改 | `check_url_delisted` 增加可选 `proxy_pool` 参数 + 失败重试 |
| `py/main.py` | 修改 | 定时任务与手动检测接入代理池 |

## 4. 数据结构

- 配置结构：见 2.1，`delist_proxy.proxies` 为字典列表，字段 `ip/port/username/password`（后续可加 `scheme`）。
- 运行时不新增数据库表、不改现有表结构。掉包判定结果仍写 `delist_checks`（`is_delisted` / `error_msg`），仅 `error_msg` 文案在代理失败时包含「代理」标识。

## 5. UI 改动

**无**。代理属于服务端基础设施配置，直接写 `config.json`，不暴露给前端用户。

## 6. 已确认的决策

1. **代理协议**：实现时先实测确定（HTTP 或 SOCKS5），以实测结果决定 `scheme`。默认先按 HTTP 代理编写，实测若为 SOCKS5 则切换并引入 `PySocks` 依赖。
2. **轮换策略**：随机取代理 + 失败自动换下一个（最多 `max_retries` 次）。
3. **`enabled` 开关**：加开关，`enabled=false` 时完全回退到当前直连逻辑。
4. **手动检测也走代理**：是，定时与手动检测行为一致，统一走 `delist_proxy` 配置。

---

设计已确认，下一步在 `docs/superpowers/plans/` 编写实现计划并开始编码。
