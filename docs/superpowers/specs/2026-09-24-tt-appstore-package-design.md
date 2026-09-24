# TT 支持苹果（App Store）包链接 + 掉包判定加固

> 日期：2026-09-24
> 范围：TT 平台（`tt_packages` 录入链路）+ `delist_checker.py` 判定加固
> 状态：待确认

## 1. 需求描述

TT 的投放对象目前只支持 Google Play 跑包。实际投放中存在 **iOS 苹果包**，需要：

1. 能把 App Store 链接录入为投放对象
2. 录入的苹果包能被掉包检测扫到、判得准、该报的能报出来

用户提供的样本：

| 类型 | 链接 | 地区 |
|------|------|------|
| 正常 | `https://apps.apple.com/vn/app/id6804355336` | 越南 |
| 掉包 | `https://apps.apple.com/vn/app/id6813542964` | 越南 |

## 2. 现状与根因

### 2.1 为什么现在导入苹果链接会报「未找到有效的 Google Play 链接」

不是「链接失效」，是**录入链路三处硬编码了 Google Play**：

| # | 位置 | 现状 | 后果 |
|---|------|------|------|
| 1 | `routes/tt_routes.py:943` `import_text` | 正则只匹配 `play.google.com/store/apps/details?id=` | 苹果链接一条都捞不到 → 返回 `parsed: []` → 前端弹警告 |
| 2 | `routes/tt_routes.py:1423` `_validate_package` | `type='package'` 必须有包名 | 苹果包没有安卓包名，空包名直接 400 |
| 3 | `frontend/src/components/TtProductCard.vue:85-88` | 包名位置直接渲染 `pkg.package_name` | 苹果包包名为空 → 出现两个相邻的 `│` 分隔符 |

前端提示语 `未找到有效的 Google Play 链接`（`TtAddPackageModal.vue:86`）是写死的 Play 口径，
字面意思是「没有一条是 Play 链接」，而不是「链接无效」。

### 2.2 掉包判定：苹果链接天然被现有规则覆盖（已实测）

用 `delist_checker.py` 里**完全相同的 User-Agent**（Android Chrome）实测：

| 链接 | 直连 | 经代理 |
|------|------|--------|
| 正常 `id6804355336` | 200 → 跳转 `/app/densia/id6804355336`，497344 字节 | 200，497344 字节（一致） |
| 掉包 `id6813542964` | **404**，2383 字节 | **404**，2383 字节（一致） |

结论：**「404 即掉包」这条规则天然覆盖 App Store，`delist_checker.py` 的判定逻辑不需要为苹果改。**

### 2.3 但实测撞出一个既有缺陷：429 静默漏报（影响 GG + TT）

同一条代理连续 5 次请求掉包链接：

| 次数 | 状态码 | 响应体长度 | 现有规则判定 |
|------|--------|-----------|--------------|
| #1 #2 #3 | 404 | 2383 | 掉包 ✅ |
| **#4** | **429** | **2383** | **未掉包 ❌** |
| #5 | 404 | 2383 | 掉包 ✅ |

关键点：**429 的响应体与 404 的响应体长度完全相同（2383 字节）**——苹果对限流返回的是同一个错误页，
两者**只能靠状态码区分**。而 `delist_checker.py:41` 只认 404：

```python
if resp.status_code == 404:
    return True, ""
```

429 因此掉进「正常」一侧。更严重的是消费方是**无条件覆盖写**：

```python
db.execute("INSERT OR REPLACE INTO tt_delist_checks(package_id, is_delisted, checked_at) "
           "VALUES(?, ?, ?)", (pkg["package_id"], 1 if is_delisted else 0, now))
```

所以一次 429 不只是「这一轮漏报」，它会**把上一次正确的掉包记录覆盖成 0，前端红标直接消失**，
且 `error` 字段不落库（只存在于手动检测的返回体里），整条链路完全静默。

429 的诱因是**代理出口 IP 是共享的**（他人也在用同一 IP 打苹果），不是本系统请求过密。

> 未验证项：Google Play 是否也会在限流时返回非 404 状态码，**未实测**（难以稳定触发）。
> 但判定逻辑是两条线共用的，加固后 GG 同样受益，属于推测而非实测结论。

## 3. 设计决策

| 决策点 | 结论 | 理由 |
|--------|------|------|
| 数据模型 | **不改表结构**，苹果包 = `type='package'` + URL 是 App Store 域名 | 掉包检测 SQL 的白名单是 `type='package'`，复用即自动覆盖，改动面最小 |
| 包名字段 | 苹果包 `package_name` 允许为**空串**，且**不自动填**数字 id | 用户明确要求不自动填；空串语义诚实 |
| 放行范围 | **只有苹果链接**才允许空包名，安卓包维持「必须填包名」原校验 | 纯增量，不放松既有校验 |
| 域名识别 | 按**解析出的 host 精确匹配** `apps.apple.com` / `itunes.apple.com` | `url.includes()` 会被 `https://evil.com/?u=apps.apple.com` 绕过 |
| 卡片展示 | 标签保持「跑包」，包名位置显示灰色小字 `iOS`，分隔符保留 | 一眼可辨平台，且不新增第三种标签文案 |
| 429 处置 | 视为**判定未知**：换代理重试，耗尽后**不写库**、既不判掉包也不判正常 | 覆盖写会抹掉正确的掉包记录，必须避免 |

## 4. 技术方案

### 4.1 域名识别（收敛成一个判定）

新增 `_is_appstore_url(url)`，用 `urlparse` 取 host，小写后与白名单**全等**比较：

```
apps.apple.com             → 苹果
itunes.apple.com           → 苹果（老域名，会跳转）
evil.com/?u=apps.apple.com → 不是
apps.apple.com.evil.com    → 不是
```

后端落在 `routes/tt_routes.py` 工具函数区（与 `_extract_pkg_from_url` 同处）；
前端在 `TtProductCard.vue` 内联同口径的小函数（前端只是渲染，不承担校验职责）。

### 4.2 录入链路改动

| # | 位置 | 改动 |
|---|------|------|
| 1 | `tt_routes.py` 工具函数区 | 新增 `_is_appstore_url(url)` |
| 2 | `tt_routes.py:1423` `_validate_package` | 包名为空时，URL 是苹果链接则放行，否则维持原 400 |
| 3 | `tt_routes.py:470-473` `update_package` 内联校验 | 同上；URL 取 `updates.get('url') or existing['url']` |
| 4 | `tt_routes.py:943` `import_text` | 正则扩成 Play + App Store 双 pattern，**按在原文中出现的先后顺序合并输出**；苹果条目 `package_name` 留空 |
| 5 | `TtAddPackageModal.vue:93` | 手动添加的包名必填校验加苹果豁免 |
| 6 | `TtAddPackageModal.vue:86` / `:9` | 提示语与 placeholder 改为「Google Play / App Store」 |
| 7 | `TtProductCard.vue:85-88` | 包名为空且是苹果链接时显示灰色 `iOS` 占位（不可复制、无点击行为） |

`_validate_package` 一改即覆盖三个调用点（建产品带包 `:255`、改产品重建包 `:318`、加包 `:427`），
因为三处传入的 dict 都带 `url`。

苹果链接的两种真实形状都要匹配：

```
https://apps.apple.com/vn/app/id6804355336          （无 slug）
https://apps.apple.com/vn/app/densia/id6804355336   （有 slug）
```

`_extract_pkg_from_url` 的 `[?&]id=` 对苹果链接的真实形状不会误匹配——苹果的 id 在路径段
（`/app/id6804355336`），而它带的查询参数键是 `l`、`pt`、`ct` 之类，都不是 `id`。
因此该函数无需改动，它返回空串正是苹果包期望的结果。

### 4.3 掉包判定加固（429 → 判定未知）

**契约变更**：`check_url_delisted` / `check_product_packages` 的 `is_delisted` 由 `bool`
变为 **`bool | None`**（`None` = 判定未知）。`error` 携带状态码。

`delist_checker.py`：

```python
class DelistIndeterminate(Exception):
    """响应状态既非 404 也非正常页面（429/5xx），无法判定。"""

_RETRYABLE_STATUS = {429, 500, 502, 503, 504}

def _request_and_judge(url, proxies):
    resp = requests.get(...)
    if resp.status_code == 404:
        return True, ""
    if resp.status_code in _RETRYABLE_STATUS:
        raise DelistIndeterminate(f"HTTP {resp.status_code}")
    # 关键词检查（不变）
    ...
    return False, ""
```

`check_url_delisted`：

- 直连分支：捕获 `DelistIndeterminate` → 返回 `(None, "HTTP 429 限流，判定未知")`
- 代理分支：捕获 `DelistIndeterminate` → 记入 `last_error` 并**换下一个代理重试**；
  重试耗尽 → `(None, "代理均返回异常状态: ...")`

「代理失败绝不判掉包」的既有不变量不变。

**消费方改动**（共 5 处，`check_product_packages` 只是透传）：

| 位置 | 改动 |
|------|------|
| `main.py:8668`（GG 定时） | `is_delisted is None` → **跳过数据库写入**，保留上一轮判定结果 |
| `main.py:8834`（TT 定时） | 同上 |
| `main.py:3632`（GG 手动） | 同上；`results[].is_delisted` 为 `null` + `error` 说明原因 |
| `tt_routes.py:644`（TT 手动） | 同上 |
| `delist_checker.check_product_packages` | 原样透传 `None` |

注意 `if is_delisted:` 这类判断对 `None` 天然安全（falsy），所以**不会误发通知**；
唯一必须显式改的是那个无条件 `INSERT OR REPLACE`。

## 5. 边界与不变量

改动后必须仍然成立：

1. **安卓包仍必须填包名** —— 三处 `_validate_package` + 一处内联校验，无一放松
2. **代理失败绝不判掉包** —— 既有逻辑不变
3. **合并去重键不变** —— `(product_id, package_name, url)`；两个不同苹果 app 包名都空但 url 不同 → 不判重；
   同一个 app 粘两次 → 包名空且 url 相同 → 判重
4. **苹果包能被定时检测扫到** —— 检测 SQL 白名单是 `pkg.type='package' AND pkg.url != ''`，
   不含 URL 形状判断，复用类型即自动覆盖
5. **「判定未知」不改变既有状态** —— 不写库，不抹掉上一轮的正确判定

### 已知业务边界（非缺陷）

App Store 链接带地区段（`/vn/`、`/us/`…），**同一个 app 可能越南区已下架、美国区仍在架**。
系统按录入的那条链接请求、按那个地区判定。用户已确认知悉。

## 6. 涉及文件与 API

**后端**

- `py/delist_checker.py` —— 新增 `DelistIndeterminate`、`_RETRYABLE_STATUS`；`_request_and_judge` 加状态码分支；`check_url_delisted` 处理未知态
- `py/routes/tt_routes.py` —— 新增 `_is_appstore_url`；改 `_validate_package`、`update_package` 内联校验、`import_text`
- `py/main.py` —— GG/TT 两处定时检测 + GG 手动检测的写库分支

**前端**

- `frontend/src/components/TtAddPackageModal.vue` —— 校验豁免 + 文案
- `frontend/src/components/TtProductCard.vue` —— iOS 占位渲染

**API**：无新增、无路径变更。`POST /api/tt/products/import-text` 的返回体
`parsed[]` 中苹果条目的 `package_name` 为 `""`；掉包相关接口的
`results[].is_delisted` 可能为 `null`。

**数据库**：无表结构变更、无迁移。

## 7. UI 改动

苹果包在 TT 产品卡片中的渲染（`TtProductCard.vue`）：

```
改前： 跑包 │ 系列名 │      │ https://apps.apple.com/... 🔗
改后： 跑包 │ 系列名 │ iOS  │ https://apps.apple.com/... 🔗
                      ↑ 灰色小字占位
```

`iOS` 占位符不可复制、不绑点击事件（避免复制出无意义的字符串）。

`TtAddPackageModal` 的解析预览表格与手动添加区域逻辑不变，苹果条目在「包名」列显示为空，
用户可自行填或不填。

## 8. 测试方案

按 `/test-driven-development` 执行。网络相关一律用 monkeypatch 替换 `requests.get`，
不起真实网络、不依赖代理可用性。

**`delist_checker`**

- `_request_and_judge`：404 → `(True, "")`；429 → 抛 `DelistIndeterminate`；503 → 抛；200 + 关键词 → `(True, "")`；200 正常页 → `(False, "")`
- `check_url_delisted` 直连：429 → `(None, ...)`；404 → `(True, "")`；200 → `(False, "")`
- `check_url_delisted` 代理：第一个代理 429、第二个 200 → `(False, "")`；全部 429 → `(None, ...)`
- 不变量：代理抛 `ConnectionError` → `(False, 错误信息)`，**绝不返回 True**

**`tt_routes`**

- `_is_appstore_url` 正反例：`apps.apple.com/vn/app/id123` ✓、`itunes.apple.com/...` ✓、
  `evil.com/?u=apps.apple.com` ✗、`apps.apple.com.evil.com` ✗、空串 ✗
- `_validate_package` 四象限：安卓+空包名 → 400；安卓+有包名 → 通过；苹果+空包名 → 通过；苹果+有包名 → 通过
- `import_text`：Play 与苹果链接**交错**的文本 → 数量与顺序都对，苹果条目 `package_name` 为空

**消费方**

- 模拟 `is_delisted=None` 走一遍写库逻辑 → 断言 `tt_delist_checks` 中该包的旧记录**未被覆盖**

**回归**

- 跑 `py/tests/` 现有全部测试，确认安卓包名校验、合并去重、掉包通知未被破坏

## 9. 风险与未验证项

| 项 | 说明 |
|----|------|
| 代理可用性 | 已实测：清理后 2 条代理（`200.160.208.55`、`207.145.250.227`）访问苹果与 Play 均正常，返回字节与直连一致。代理会过期失效，需人工更换 |
| 429 的 Play 侧表现 | **未实测**，属推测。加固后 GG 同样受益 |
| 429 触发频率 | 实测 5 次中 1 次（共享代理 IP，他人也在使用）。换更干净的代理可降低频率，但加固后即使触发也不再抹掉判定记录 |
| TT 手动检测走直连 | `tt_routes.py:644` 传 `proxy_pool=None`（直连），与 `AGENTS.md` 中「手动检测走代理池」的描述不符。**本次不擅自改**，作为疑问提出，待用户裁定 |

## 10. 明确不做的事

- 不新增 `type='ios'`，不改 `tt_packages` 表结构
- 不改 GG / FB 平台的录入链路（`AddPackageModal.vue`、`CopyImportModal.vue` 保持 Play 口径）
- 不为苹果链接配独立代理池
- 不改 `_guess_series` 的猜名逻辑；苹果链接猜不到时的兜底是**空串**（不塞数字 id，与「不自动填」同口径）
- 不动 `tt_data_import` 的 JSON 重建逻辑（直接搬运行数据，不校验）

## 11. 文档同步

- 本文档需登记到 `AGENTS.md` 的「设计文档索引」
- TT 掉包通知与产品管理的描述需补充「支持 App Store 链接」
- `delist_checker.py` 的判定口径变化（新增「判定未知」态）需在 AGENTS.md 的「包掉包自动检测与通知」处说明

## 12. 追补：同族缺陷收口（2026-09-24 用户裁定）

实现期间在审查环节又发现两处与 §2.3「无法判定被写成正常、抹掉正确记录」**同一缺陷家族**的缺陷，
经用户裁定**一并收口**，纳入原 Task 3 范围：

### 12.1 空 url 也归为「未知」

`check_product_packages`（`delist_checker.py:152-158`）对空 url 返回 `is_delisted=False`（=「正常」），
经消费方无条件写库后同样会抹掉上一轮正确的掉包记录。

**可达性已证实（仅 GG）**：

| 路径 | `url != ''` 过滤 | 是否可达 |
|------|-----------------|---------|
| GG 手动检测取包 SQL（`main.py:3619-3622`） | **无** | **可达** |
| GG 定时（`main.py:8645`）、TT 定时（`main.py:8811`）、TT 手动（`tt_routes.py:635`） | 有 | 不可达 |

且 GG 加包端点（`main.py:3401-3414`）**只要求包名、不要求 url**，故空 url 包可被创建；
`products_update_package` 还可把既有包的 url 清空，使既有掉包记录随后被抹。

**处置**：`check_url_delisted("")` 与 `check_product_packages` 的空 url 分支
统一由 `False` 改判 `None`（模块契约统一为「无法判定 → `None`」），消费方据此不写库。
两个钉住旧行为的既有测试（`test_empty_url_returns_false`、`test_skips_packages_without_url`）
**改断言并注明语义变更，不删除**。

### 12.2 `update_package` 的 url 语义收口

`tt_routes.py:484-489` 的 `updates.get('url') or existing['url']` 把「本次没传 url」
与「本次显式传空串」混同：对存量苹果包 `PUT {"package_name":"","url":""}` 会回落用库里的苹果 url
而放行，最终落库成「包名与 url 皆空」—— 正是这条校验要拦的形态。

**处置**：先判 key 存在性（`'url' in updates`）再决定用本次值还是库里值。
「本次没传 url → 回落库里 url」这一既有能力保持不变。

### 12.3 「拿不到判定」的四类残余全部归为「未知」

Task 3 审查环节发现 §2.3 的同族缺陷**还有第三个实例**，且同样可达。实现后实测：

```
check_url_delisted('play.google.com/store/apps/details?id=x')   # 漏写 http://
  → (False, "Invalid URL '...': No scheme supplied. ...")
```

`requests.MissingSchema` 不是 `ConnectionError` 子类，落进 `delist_checker.py` 的兜底
`except Exception → False`，于是**畸形 url 被判成「正常」**，照样经消费方写成 `is_delisted=0`
抹掉既有掉包记录。同族还有三处：

| # | 分支 | 位置 | 现状 |
|---|------|------|------|
| ① | 畸形 url（`MissingSchema` 等解析异常） | 直连兜底 `except Exception` | `False` |
| ② | 直连超时 | `except requests.Timeout` | `False` |
| ③ | 直连连接失败 | `except requests.ConnectionError` | `False` |
| ④ | 代理池为空 | `proxy_pool.count == 0` | `False` |
| ⑤ | 代理全部失败（重试耗尽） | 末尾返回 | `False` |

**可达性已实测**：GG 加包端点只校验包名不校验 url；`products_update_package` 可写入任意
url 或把 url 清空；定时取包 SQL 只过滤 `url != ''`，故畸形/失效 url 真能进到检测环节。

> 这五处保持 `False` 原是 Task 1 的**显式决定**（计划明文要求三条测试继续断言 `is False`，
> 理由是「不让未知态扩大化」）。2026-09-24 用户裁定：**与 429 后果同型，一并收口**，
> 五处统一改判 `None`。

**处置**：五处全部由 `False` 改判 `None`，模块契约彻底统一为「拿不到判定 → `None`」。
「代理失败绝不判掉包」不变量不受影响 —— `None` 既非 `True` 也非 `False`，且消费方对
`None` 一律不写库。`test_delist_checker.py` 中钉住旧行为的四条既有测试
（`test_returns_false_with_error_on_timeout` / `..._on_connection_error` /
`..._on_general_exception`、`test_all_proxies_fail_returns_proxy_error` /
`test_empty_pool_returns_proxy_error`，以及 Task 1 新增的
`test_timeout_still_false_not_none`）**改断言 + 改名 + 注明语义变更，不删除**。

反面必须保持不变：**200 正常页面仍判 `False`**（`test_returns_false_when_app_page_normal`、
`test_200_normal_still_false`、`test_retries_next_proxy_after_failure`、
`test_proxy_retries_to_next_after_429`、`test_no_pool_keeps_direct_connection` 五条断言不得改动）。
「未知」只吸收「拿不到判定」，不得吸收「拿到了判定且判为正常」。

顺带修正 `check_product_packages` 的 docstring —— 它写「函数只做透传」，但该函数自身在
空 url 分支返回 `None`，措辞自相矛盾（Task 1 遗留）。

### 12.4 前端「本轮全部未知」时的误报提示

`ProductCard.vue:196`、`TtProductCard.vue:308` 在 `delisted.length === 0` 时**无条件**
弹 `ElMessage.success('所有包均正常 ✓')`。整批 429 限流（或全为空 url 包）时本轮结果全是
`None`，该提示会说谎，让人以为检测正常完成。

数据本身不受影响（列表仍按持久化的 `is_delisted=1` 标红），仅提示语失真。
Task 1 起即可达，Task 3 扩大了可达面。

**处置**：折进 Task 4 一并修正（Task 4 本就要改 `TtProductCard.vue`），提示语需区分
「全部正常」与「本轮有 N 个未能判定」。用户 2026-09-24 裁定。

### 12.5 5xx 只认了 500/502/503/504，其余 5xx 会漏成「正常」

§2.3 同族缺陷的**第四个实例**。`delist_checker.py:27`：

```python
_RETRYABLE_STATUS = frozenset({429, 500, 502, 503, 504})
```

命中该集合的状态码抛 `DelistIndeterminate` → `None`（未知）；**不在集合里的 5xx**
（501 Not Implemented、505 HTTP Version Not Supported、506/508/510/511 等）
则继续往下走：既然不是 404，就落到关键词扫描 —— 拿一个「服务器错误页」去匹配
`_DELISTED_PATTERNS`，几乎必然不命中 → `return False, ""` → 判为「正常」，
再经消费方 `INSERT OR REPLACE` 抹掉上一轮正确的掉包记录。后果与 429 完全同型。

可达性弱于前三例：需要上游（商店 / 中间代理 / CDN）真的返回这些冷门状态码，
实测样本中未出现。但「503 判未知、501 判正常」这个不对称没有任何依据，
且修复成本是一行。`_RETRYABLE_STATUS` 实测**仅被本模块三处引用**
（`:27` 定义、`:47` docstring、`:62` 使用），**没有任何测试导入或断言它**，改写安全。

**处置**：判定从「枚举集合」改为「429 或任意 5xx」：

```python
def _is_indeterminate_status(status_code: int) -> bool:
    """429 或任意 5xx 均视为「拿不到判定」，应换代理重试。"""
    return status_code == 429 or 500 <= status_code < 600
```

删除 `_RETRYABLE_STATUS`，`:62` 改为 `if _is_indeterminate_status(resp.status_code):`，
`:47` docstring 与 `DelistIndeterminate` 类 docstring 同步措辞。
**反面必须保持不变**：404 → `True`（掉包），200 正常页 → `False`（正常）；
新增一条 200 对照用例，防止「把判定拓宽成未知」。

**已知边界（本任务不动，另议）**：404 之外的 4xx 当前同样落到 `False`。
其中 **403 在数据中心 IP 上是现实存在的**（商店返回反爬页），与本族缺陷同型；
但改判它等于把「只认 404 为掉包」的口径整体拓宽，超出本次裁定范围 ——
记为已知风险，不夹带进本任务。

### 12.6 TT 手动检测实际走直连，与文档及另外三处调用不一致

AGENTS.md 写「TT 手动检测 `POST /api/tt/products/:pid/check-delist`，同样走代理池」，
但 `tt_routes.py:665` 传的是 `None`：

```python
results = delist_checker.check_product_packages(pid, pkg_list, None)   # ← 直连
```

四处同族调用的实际状态：

| 调用点 | 代理池 |
|--------|--------|
| GG 手动 `main.py:3632` | ✅ `_build_delist_proxy_pool()` |
| GG 定时 `main.py:8676` | ✅ |
| TT 定时 `main.py:8857` | ✅ |
| **TT 手动 `tt_routes.py:665`** | ❌ `None`（直连） |

后果：TT 手动检测是唯一绕过代理池的路径，而它恰是最容易被限流的使用方式
（用户手动连点）。429 实测频率约 1/5，直连等于把限流概率拉到最高 ——
而限流一旦发生，正是本设计要收口的「未知态」源头。

**处置**：改为 `_build_delist_proxy_pool()`，与其余三处对齐。
`tt_routes.py` **不在模块层导入 `main`**（`main.py` 导入并注册本 Blueprint，
模块级互导会成环），因此**在函数内部局部导入** —— 仓库既有先例：
`routes/tt_accounts_routes.py:717/1050/1216`、`routes/huguan_dashboard_routes.py:52/88/168/219/224`。

```python
    from main import _build_delist_proxy_pool
    results = delist_checker.check_product_packages(pid, pkg_list, _build_delist_proxy_pool())
```

既有 TT 手动检测的用例全部 monkeypatch 了 `delist_checker.check_product_packages`
（`tests/test_tt_delist_notification.py:444/464/491`），第三个参数被忽略，结论不受影响；
新增一条用例断言代理池被**透传**（monkeypatch `main._build_delist_proxy_pool`
返回哨兵对象，断言 `check_product_packages` 收到的第三个参数正是该哨兵）。
