# 掉包检测走代理 IP — 实现计划

## 实现顺序（TDD）

### 阶段 0：实测代理协议（前置）
1. 用 curl / 临时脚本实测 6 个代理的协议（HTTP 还是 SOCKS5），确定 `scheme`。
2. 实测能否访问 `https://play.google.com`，确认代理可用。

### 阶段 1：代理池模块 + 测试
3. 创建 `py/tests/test_proxy_pool.py` — 测解析、按 (ip,port) 去重、随机取用、`to_requests` 转换。
4. 创建 `py/proxy_pool.py` — 实现 `ProxyPool` 类。
5. 运行测试确认通过。

### 阶段 2：检测函数改造 + 测试
6. 更新 `py/tests/test_delist_checker.py` — 新增「代理失败换下一个重试」「全失败返回代理错误」「无代理池走原逻辑」测试。
7. 修改 `py/delist_checker.py` — `check_url_delisted` 增加可选 `proxy_pool` 参数 + 失败重试（保持原测试通过）。
8. 运行测试确认通过。

### 阶段 3：接入调用处 + 配置
9. 修改 `py/main.py` — `_run_delist_check_once` 读取 `delist_proxy` 配置、构造 `ProxyPool` 并传入 `check_url_delisted`；手动检测同样接入。
10. 更新 `config/config.json` — 新增 `delist_proxy` 段（`enabled` + `max_retries` + 6 个代理）。
11. 运行测试确认通过。

### 阶段 4：验证
12. 手动触发掉包检测（或调用 `POST /api/admin/trigger-delist-check`）验证走代理、日志含代理信息。
13. 验证 `enabled=false` 回退直连。

## 涉及文件清单

| 文件 | 操作 |
|------|------|
| `py/tests/test_proxy_pool.py` | **新建** |
| `py/proxy_pool.py` | **新建** |
| `py/tests/test_delist_checker.py` | 修改（新增代理重试用例） |
| `py/delist_checker.py` | 修改（加 `proxy_pool` 可选参数 + 重试） |
| `py/main.py` | 修改（定时 + 手动检测接入代理池） |
| `config/config.json` | 修改（新增 `delist_proxy` 段） |

## 关键约束（纯增量）

- `check_url_delisted(url)` 不传 `proxy_pool` 时行为与当前完全一致，现有测试必须继续通过。
- 代理失败（连接失败/超时）绝不判为掉包，只返回带「代理」标识的 error。
- 掉包判定逻辑（404 + 关键词）不改动。
