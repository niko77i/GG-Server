# 共享账号网关（广大大 / 有米云）

> 状态：**设计已确认，P0 骨架已实现（2026-11-06）**；P1 真实登录联调待用户配合
> 位置：GG-Server → 共享账号（`/share`），网关独立端口
> 前身：`D:\server\cc\shared Acount` 的「登录态共享器」浏览器扩展 v0.6.0
> 实施计划：[2026-11-06-shared-account-gateway-plan.md](../plans/2026-11-06-shared-account-gateway-plan.md)

## 1. 背景：扩展「能用但不方便」

扩展已经验证了核心事实：**同一个会员账号的登录态可以给多人复用**（服务机登录一次，同事导入快照即可用）。
但它的工作方式决定了每次都要人肉搬运：

| # | 痛点 | 具体表现 |
|---|---|---|
| 1 | 每人要装扩展 | 打开开发者模式、加载已解压扩展，新人接入成本高 |
| 2 | 每次续期都要全量重发 | `jwt` 只有 12 小时、`user-token` 3 天、`ZFSESSID` 30 天；快照一过期，所有人重新导入 |
| 3 | 采集质量靠人判断 | 只采到 3 条 cookie、没有 `ZFSESSID` 时，别人注入后登不上（已踩过两次） |
| 4 | 采集绑死一台机器 | 必须在「采集者那台浏览器」登录后再采，换机器就重来 |
| 5 | 无法审计 | 谁在用、什么时候用，平台侧和本侧都看不到 |

**目标**：把「登录态」从**文件**变成**服务**——服务端登录一次并持有会话，同事在 GG-Server 点「打开」就能用原站；
令牌轮换、cookie 续期由网关自动跟随，人只在**会话真失效**时重新登录一次（管理员一人操作）。

## 2. 方案选择

| | A. 反向代理网关 | B. 服务端远程浏览器 | C. 快照中心 |
|---|---|---|---|
| 原理 | 服务端持有会话，同事浏览器经网关访问原站 | 服务端跑已登录的 Chrome，同事看画面 | 快照存 GG-Server，扩展一键拉取注入 |
| 同事成本 | **打开网页即可，零安装** | 打开网页即可 | 仍要装扩展 |
| 续期 | 自动跟随 `Set-Cookie`；仅会话锚点失效时重登 | 同 A（在远程浏览器里重登） | 每次过期都要重新采集分发 |
| 代价 | 需要代理改写与排错 | 每用户一个 Chrome，内存/带宽重、会卡 | 改动最小但痛点 1/2 原样保留 |

**选 A**（用户 2026-11-06 确认）。B 作为兜底：若平台对代理出的页面做了强指纹校验、A 调不通，再评估远程浏览器。

## 3. 已探测的技术事实（2026-11-06，只读探测）

| 结论 | 依据 | 对设计的影响 |
|---|---|---|
| 前端是 CRA 单页应用 | `/modules/creative/display-ads` 返回 1.7KB 壳 + `main.62ead425.js`（12.4MB） | 页面/API 都由 JS 发起 |
| **API 与页面同源，但在 apex** | `www.guangdada.net` 对 `/napi/*` 与根路径都 301 → `guangdada.net`；bundle 里两处 `axios.create({baseURL:""})` | 上游主站取 **apex `guangdada.net`**，`www` 列为附加主机；同站跨主机跳转在服务端内部跟随 |
| 接口前缀是 `/napi/v1/*` | 依赖里出现 `/napi/v1/user/jwt`、`/napi/v1/user/login`、`/napi/v1/creative/list` 等 509 条路径 | 登录/取令牌都走这条前缀，无需另配 API 域名 |
| **没有 WebSocket、没有 Service Worker** | bundle 中 `wss://`/`WebSocket`/`serviceWorker` 均为 0 | 省掉两条最难代理的通路 |
| 静态资源跨域且可直连 | bundle/CSS 在 `nbs-bj-global.zingfront.com`、`static-global.zingfront.com` | 由同事浏览器直连，不过服务器，省带宽 |
| **CDN 开了 Referer 防盗链** | 实测同一 URL：无 Referer / `https://guangdada.net/` → 200；`http://100.80.178.20:8901/...` 或 `127.0.0.1:8901` → **403**（返回 HTML，浏览器随后 `ERR_BLOCKED_BY_ORB` 丢掉 main.js → **白屏**） | 网关必须在 HTML 里注入 `<meta name="referrer" content="no-referrer">` + `Referrer-Policy: no-referrer`，让跨域静态资源不带 Referer |
| 认证由 cookie + localStorage 共同承担 | 请求头 `x-nbs-user-token` 读 cookie `user-token` 或 localStorage；`Authorization` 取 localStorage 里的 jwt | 网关必须把 `user-token` 这类非 httpOnly cookie 下发到浏览器 |
| **`user-token` 是 SPA 用 `document.cookie` 写的，不在上游 Set-Cookie 里** | bundle 的请求拦截器：`x-nbs-user-token = readCookie("user-token") \|\| localStorage.getItem("user-token")`；取不到就 `Promise.reject("Token null")` / 不发 jwt 请求 | 网关必须**从浏览器请求里学习** `user-token` 存进会话罐，并在页面响应里下发；否则换主机/端口打开时 SPA 认为未登录 |
| 会话锚点是 `ZFSESSID`（httpOnly，约 30 天） | 扩展实测：有它才能续出 jwt；只有 3 条 cookie 的快照必失败 | 网关把它留在服务端，浏览器侧不需要 |
| 登录有阿里云滑块验证码 | 壳页加载 `o.alicdn.com/.../AliyunCaptcha.js` | 登录必须在**真人浏览器**里完成，不能无人值守重登 |
| 存在额外跨域服务 | `agent.guangdada.net`（Copilot）、`global.guangdada.net`（iframeHost）、`ecom-saas.zingfront.com` | 第一期只保证核心素材浏览；这些模块另做映射 |
| `cryptography 49` 已安装 | `python -c "import cryptography"` | 会话罐可 AES-GCM 加密落库 |
| 8899 已被旧项目占用 | `shared Acount/tools/proxy.js` 默认端口 | 网关改用 **8901**（有米云预留 8902） |

## 4. 架构

```
                        ┌──────────────────────────────────────────┐
同事浏览器 ──5001──────► │ GG-Server（Flask/waitress，现有）          │
  （登录、点「打开」）    │  · /share 页面                            │
                        │  · POST /api/share/sites/<id>/enter       │
                        │      → 一次性票据 URL                     │
                        └───────────────┬──────────────────────────┘
                                        │ 302/新标签
                        ┌───────────────▼──────────────────────────┐
同事浏览器 ──8901──────► │ 共享账号网关（第二个 waitress，独立线程）  │
  （直接操作原站）        │  · 校验票据 → 种网关会话 cookie           │
                        │  · 原站根路径 1:1 映射                    │
                        │  · 会话罐：注入 Cookie / 吸收 Set-Cookie  │
                        │  · 响应重写：绝对域名 → 当前网关 origin    │
                        └───────────────┬──────────────────────────┘
                                        │ HTTPS
                                        ▼
                              https://www.guangdada.net
```

**为什么是独立端口，而不是 `/share/gdd/` 路径前缀**（关键取舍）：

1. SPA 的接口是**根绝对路径**（`/api/...`），挂在路径前缀下会被浏览器解析到 GG-Server 根上，直接打到自己的 API；
2. 前端路由（`/modules/...`）读 `location.pathname`，前缀会污染深链接；
3. `<base>` 只能救相对路径，救不了根绝对路径；靠 shim 改写 `fetch`/`XHR`/`history` 很脆，且 12MB bundle 里还有绝对地址。

独立端口让原站**原样**跑在根路径上，代价只是多一个监听端口。

## 5. 关键设计

### 5.1 站点配置

配置在 `config/config.json`（真实密钥/账号走 `config.local.json`）：

```json
"share_gateway": {
  "enabled": true,
  "sites": [
    { "id": "guangdada", "name": "广大大", "upstream": "https://www.guangdada.net", "port": 80, "enabled": true }
  ]
}
```

站点表同步落库（便于 UI 展示状态与日志），启动时以配置为准做 upsert。

### 5.2 会话罐（服务端 cookie jar）

- 每个站点一个 jar：`name → {value, domain, path, expires, secure, http_only}`。
- 请求上游时：按 domain/path/未过期筛出 cookie，拼 `Cookie` 头。
- 响应 `Set-Cookie`：**先更新 jar（原子、落库）**，再决定是否下发浏览器。
  - `HttpOnly`（`ZFSESSID` 等）：**只留在服务端**，不下发。
  - 非 `HttpOnly`（`user-token`、`x-token` 等）：下发，但 `Domain` 去掉、`Secure` 去掉、`SameSite` 非 `None` 才保留。
- 并发：进程内 `threading.Lock` 保护；落库用整串覆盖写（不做逐条 read-modify-write）。
- 加密：`AES-256-GCM`，密钥由 `secret_key + site_id` 经 HKDF 派生；`nonce` 随机，密文 base64 存 `share_sessions.cookies_enc`。
- 采集/清空：管理员在网关页面登录即自动写入；「清空会话」= 删 jar，强制重登。

### 5.3 代理细则

**请求**（浏览器 → 网关 → 上游）：

| 处理 | 规则 |
|---|---|
| URL | `upstream + RAW_PATH + '?' + QUERY`（保留原始百分号编码） |
| Cookie | 用 jar 重建，**忽略浏览器带来的 Cookie** |
| 逐跳头 | 丢弃 `Connection/Keep-Alive/Transfer-Encoding/TE/Trailer/Upgrade/Proxy-*` |
| Host | 改为上游 host |
| Origin / Referer | 若指向网关，改写为上游 origin（防 CSRF 校验误杀） |
| Authorization / x-nbs-user-token | 原样透传（前端自己带） |
| Accept-Encoding | 只保留 `gzip, deflate`，网关解压后判断是否需重写 |

**响应**（上游 → 网关 → 浏览器）：

| 处理 | 规则 |
|---|---|
| 状态码 | 全透传（302 也是） |
| `Location` | 指向上游的绝对地址 → 改写为网关 origin |
| `Set-Cookie` | 见 5.2 |
| `Content-Encoding` | 解压（gzip/deflate）；解不了的原样透传 |
| 文本（html/css/js/json/text） | 把 `https://www.guangdada.net`、`//www.guangdada.net`、`https://guangdada.net` 换成**当前请求的网关 origin**（按 `Host` 头算，LAN/Tailscale 各自可用）；改完重算 `Content-Length` |
| HTML 额外注入 | `<meta name="referrer" content="no-referrer">` + `Referrer-Policy: no-referrer` —— CDN 防盗链会 403 掉网关 Referer 下的 main.js（见 §3） |
| 二进制/大响应 | 流式透传，不缓冲；单次响应 > 8MB 的文本放弃重写 |
| 超时 | 连接 10s、读取 60s；上游 5xx/超时返回网关错误页（带重试按钮） |
| 压缩 | 网关不压缩文本响应（LAN 带宽足够，避免二次处理） |

**不代理**：跨域 CDN 图片/视频（同事浏览器直连原 CDN）、阿里云验证码。风险见第 9 节。

### 5.4 登录与重新登录

1. 管理员在 GG-Server「共享账号」页点「打开」→ 拿到一次性票据 → 打开网关。
2. 网关入口 302 到 `share_gateway.sites[].landing_path`（广大大默认 `/modules/creative/display-ads` 工作台；原站 `/` 是营销首页，登录了也看不出状态）。
3. 没登录时显示原站登录页（阿里云滑块**在管理员自己的浏览器里**跑，服务端看不到密码）。
4. 登录成功：
   - 上游 `Set-Cookie` 被 jar 吸收（含 `ZFSESSID`）；
   - **SPA 用 `document.cookie` 写的 `user-token` 不会出现在 Set-Cookie 里**，由网关从后续请求的 `Cookie` 头里学习进 jar（白名单 `user-token` / `x-token`），再在 HTML 响应里下发给所有浏览器。会话罐里按 **72 小时**记它的到期时间（与 SPA `setCookie(..., 72)` 一致），过期后状态变「需重新登录」。
5. 同事打开时：拿到 `__sgw_<site>` + 服务端下发的 `user-token`，SPA 用 `x-nbs-user-token` 调 `/napi/v1/user/jwt` 换 jwt，直接进入已登录状态。
6. 会话失效（心跳判定）→ 卡片变黄「需重新登录」→ 管理员重复 1~4 步。**密码不落库、不经过网关日志。**

> 为什么不能「服务端自动重登」：登录要过阿里云滑块，且服务端保存密码等于把账号交出去；不做。
> 为什么必须同步 `user-token`：它只存在于「登录时那个 origin」的浏览器里；网关换端口/主机后是新 origin，没有它 SPA 会判断成未登录（表现为「登录过但打开还是登录页」）。

### 5.5 访问控制

- 只有**已登录 GG-Server** 的用户能拿到票据：`POST /api/share/sites/<id>/enter` 走 `@jwt_required()`。
- 票据：`base64url({site,uid,name,exp,nonce}) + "." + HMAC-SHA256(secret)`，TTL 60s、一次性（进程内 nonce 集合，5 分钟清理）。
- 网关入口 `/__sgw/enter?t=...` 校验票据 → 种 `__sgw_<site>` cookie（HttpOnly、SameSite=Lax、12h）→ 302 到 `/`。
  ⚠️ **cookie 名按站点区分**：浏览器 cookie 不区分端口，8901 与 8902 共享命名空间；同名会让第二个站点拿到第一个站点的 cookie 去验签（site 不匹配 → 401）。
- **网关 URL 的主机名**：沿用浏览器访问 GG-Server 时的 Host；若 Host 是 `127.0.0.1`/`localhost`（管理员在服务器本机打开），回退到 `share_gateway.public_host` 配置，未配置则自动探测本机对外 IP（优先 Tailscale `100.64.0.0/10`，其次 192.168/10/172）。
  否则复制出去的链接会让同事连到**他自己机器**（`ERR_CONNECTION_REFUSED`）。
- **票据是一次性且绑定签发人的**：`复制链接` 只适合「同一个人在本机换浏览器打开」，**不能当同事邀请链接**发给别人——
  别人打开时要么票据已被用掉（401），要么 cookie 绑的是签发人身份。同事应各自登录 GG-Server 后在本页点「打开」。
- 其余所有请求校验对应站点的 `__sgw_<site>`；无效返回最小 401 页（「请从 GG-Server → 共享账号 打开」），不渲染原站。
- 站点配置/清空会话/访问日志：仅 `developer`（与现有敏感配置同级）。

### 5.6 失效检测

- 后台线程每 5 分钟按**会话罐的 cookie 有效期**判断：罐子为空 → `unknown`（未登录）；`ZFSESSID`/`user-token` 未过期 → `ok`；全部过期 → `expired`。
- 为什么不在服务端请求登录接口判定：所有 `/napi/*` 都要求 `x-nbs-user-token`/`x-product-id` 等业务头，未带时统一返回 `403 ILLEGAL REQUEST`，无法区分「没登录」与「缺头」；P1 联调拿到真实响应后再校准。
- 结果写 `share_sessions.status`（`ok` / `expired` / `unknown`）与 `last_error`；前端卡片据此上色。
- 网关端口未监听时，接口直接报 `down`，与「会话过期」分开显示。

### 5.7 审计

- `share_access_log`：谁、什么时候、从哪个 IP 进了哪个站点（进入时记一条）。管理页可看最近 200 条。
- 不记录浏览内容、不记录 URL 路径（量大且无必要）。

### 5.8 安全加固（2026-11-06 独立审查后）

| 问题 | 处置 |
|---|---|
| 任何登录用户都能把共享 `user-token` 换成自己的 | 罐里有**未过期**令牌时一律不覆盖（不论 uid）；想更新只能等上游 401 把旧令牌标过期，或管理员清空会话 |
| 令牌在服务端已失效、本地却仍显示「可用」；重新登录的新 token 又被「不覆盖」挡住 | 代理看到 `/napi/*` 返回 **401** 时调 `mark_auth_invalid()`：把学到的令牌标成过期 + 状态改「需重新登录」，下一次登录的新 token 自然学进来 |
| 登录请求本身带着**旧** `Authorization`，把刚清掉的旧令牌又学回罐里，导致重新登录永远生效不了 | 任何含 `login` / `logon` / `signin` 的路径都**不学习**、并清掉旧令牌（Insightrackr 的登录接口是 `/cas/api/logon/login`，不在 `login_path` 里） |
| 浏览器缓存了旧版 HTML（没有 no-referrer），别人都好了他还白屏 | 网关返回的 HTML 与进入 302 一律 `Cache-Control: no-store` |
| 同事在登录页自己登录原站，把共享会话顶掉（原站提示「您已在其他设备登录」） | 只有 `manage_uids`（默认 `[1]`，即 developer）能访问登录页/登录接口；其他人返回 403「请联系管理员重新登录」。管理员登录前先 `mark_auth_invalid()`，新令牌才能学进来 |
| Chrome / Edge 用同一个共享 token，被平台当成两台设备踢下线 | 转发上游时**统一 User-Agent** 并去掉 `sec-ch-ua*` 客户端提示头 |
| 「停用站点」只改显示、不拦请求；清空会话后旧 `__sgw` cookie 仍有效 12h | ① `enter` 与代理两侧都检查 `share_sites.enabled`（代理侧 5 秒缓存）；② cookie 里带会话代次 `ver`（`share_sessions.ver`），清空/停用时 +1，旧 cookie 立即 401 |
| 文本响应无上限缓冲（chunked 无 Content-Length）可能 OOM 主进程 | 文本响应一律**有界读取**（`read(8MB+1)`）后重写；超过上限时把「已读前缀 + 剩余流」一起透传。⚠️ **不能因为 chunked 就跳过重写** —— 原站 SPA 壳正是 chunked，跳过会漏掉 no-referrer，CDN 403 → 白屏（2026-11-06 二次踩坑） |
| 内部跟随跨主机 301 时丢掉中间响应的 Set-Cookie | 跟随前先 `absorb` 进会话罐 |
| 无绝对到期时间的会话 cookie 被当成永不过期 | 入罐记 `first_seen`；状态自检按 `ZFSESSID 30 天 / user-token 72 小时` 估算到期 |
| 非 ASCII 票据/网关 cookie 抛异常 → 500 | 解析前做 ASCII 校验并包 try/except，统一 401；`__call__` 外层兜底不吐堆栈 |

**非 cookie 型站点（2026-11-06 新增 Insightrackr）**

Insightrackr（`data.insightrackr.com`）不用 cookie：登录把 token 写进 `localStorage.token`，每个接口带
`Authorization: <token>`（无 Bearer 前缀）。网关按站点配置走另一套：

| 配置 | 作用 |
|---|---|
| `auth_header: "Authorization"` | 从浏览器请求头学习令牌，存加密罐的伪条目 `__auth_header`；转发上游时回注该头 |
| `local_storage_token_key: "token"` | 在每个 HTML 响应里注入 `localStorage.setItem("token", <共享值>)`，让新浏览器被 SPA 当成已登录 |
| `login_path: "/login"` | 该路径的 401 不当作「会话失效」（避免登录失败误清令牌） |

其余防护同 cookie 型：已有未过期令牌不覆盖；上游 401 → `mark_auth_invalid()` 后重新登录的令牌才学进来。

## 6. 数据模型

```sql
CREATE TABLE IF NOT EXISTS share_sites (
    id          TEXT PRIMARY KEY,          -- 'guangdada'
    name        TEXT NOT NULL,
    upstream    TEXT NOT NULL,
    port        INTEGER NOT NULL,
    enabled     INTEGER NOT NULL DEFAULT 1,
    created_at  TEXT
);

CREATE TABLE IF NOT EXISTS share_sessions (
    site_id     TEXT PRIMARY KEY REFERENCES share_sites(id) ON DELETE CASCADE,
    cookies_enc TEXT,                      -- AES-256-GCM 密文（base64）
    updated_at  TEXT,
    status      TEXT DEFAULT 'unknown',    -- ok | expired | unknown
    last_ok_at  TEXT,
    last_error  TEXT,
    fail_streak INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS share_access_log (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    site_id    TEXT NOT NULL,
    user_id    INTEGER,
    username   TEXT,
    ip         TEXT,
    created_at TEXT NOT NULL
);
```

## 7. 接口

| 方法 | 路径 | 权限 | 说明 |
|---|---|---|---|
| GET | `/api/share/sites` | 登录用户 | 站点列表 + 状态 + 会话剩余时间 + 今日使用人数 |
| POST | `/api/share/sites/<id>/enter` | 登录用户 | 发一次性票据，返回网关 URL |
| GET | `/api/share/sites/<id>/logs` | developer | 最近 200 条访问记录 |
| POST | `/api/share/sites/<id>/reset` | developer | 清空会话罐（强制重登） |
| POST | `/api/share/sites/<id>/check` | developer | 立即探测上游与登录状态 |
| PUT | `/api/share/sites/<id>` | developer | 改名称/端口/启用 |

## 8. 前端方案（UI 先确认）

新增一级菜单「🔗 共享账号」（三平台都显示，因为这是公司级工具），页面 `/share`：

```
共享账号
同事点「打开」直接在浏览器里用原站，不需要安装任何扩展。
会话失效时，由管理员在网关页面里重新登录一次即可，其他人无需操作。

┌───────────────────────────────────────────────────────────────┐
│  广大大 · guangdada.net                          ● 可用         │
│  会话已就绪 · 最近核对 2 分钟前                                 │
│  今日 3 人使用 · 上次使用 10:24（张三）                         │
│                                                                │
│  [ 打开共享页面 ]   [ 复制链接 ]        ⋯ 管理                  │
└───────────────────────────────────────────────────────────────┘

┌───────────────────────────────────────────────────────────────┐
│  有米云 · appgrowing.cn                          ○ 未启用       │
│  管理员启用后可用                                               │
└───────────────────────────────────────────────────────────────┘
```

状态与交互：

| 状态 | 徽标 | 主按钮 | 副文案 |
|---|---|---|---|
| 可用 | 绿 `● 可用` | 打开（新标签） | 最近核对 X 前 |
| 需重新登录 | 黄 `● 需重新登录` | 打开（新标签） | 「管理员打开后在页面里登录一次」 |
| 网关不可达 | 红 `● 网关未启动` | 打开（禁用） | 提示检查端口/防火墙 |
| 未启用 | 灰 `○ 未启用` | 禁用 | 「管理员启用后可用」 |

「⋯ 管理」（developer）：清空会话、立即探测、访问日志（抽屉表格）、启用/停用。
空态：无站点 → 「联系管理员在 config.json 配置共享站点」。
错误态：接口失败 → 顶部 amber 提示条 + 重试按钮；不阻塞页面。

侧边栏：新增 `{ key:'share', icon:'🔗', label:'共享账号' }`，GG/FB/TT 三套菜单都加；户管菜单不显示。

## 9. 风险与边界

| 风险 | 影响 | 应对 |
|---|---|---|
| 平台条款 | 共享会员账号大概率违反 ToS，极端情况封号 | 只对内网、限人数、不对外提供入口；用户已知情（见 TEST-PLAN 第 11 节） |
| 浏览器「不安全」提示 | 网关是 http，Chrome 可能提示 | 内网地址默认不提示；后续可选自签证书 |
| 跨域 CDN 的 Referer / 签名 | 图片/视频 403 | 先实测；若被拦，再加 `/__cdn/` 代理（走服务器带宽） |
| 额外跨域服务（Copilot / Ecom iframe） | 这些模块登录态缺失 | 一期不保证；二期加 host 映射 `https://agent.guangdada.net` → `/__up/agent/...` |
| cookie 不区分端口 | 网关 `user-token` 也会发给 5001 | 名字不冲突即无害；网关只下发非 httpOnly 且不加 Domain |
| 6 人同 IP 同会话 | 平台风控降级 | 与扩展方案风险相同，不新增；先 2 人试，观察 1 天 |
| 网关线程挂掉 | 共享页 502 | 线程内 try/except + 重启循环；主服务不受影响 |
| 主进程重启 | 网关随之重启，jar 落库不丢 | jar 每次 Set-Cookie 即落库 |

## 10. 分期与验收

| 阶段 | 内容 | 验收 | 状态 |
|---|---|---|---|
| P0 | 骨架：`share_gateway/`（jar / 加密 / 票据 / 代理 / 重写）+ 假上游单测 + 接口 + 前端页面 | `pytest py/tests/test_share_gateway.py` 全绿；不接真实站点 | ✅ 2026-11-06（23 条用例） |
| P1 | 广大大真实联调：登录 → 素材浏览 → 6 人并发 30 分钟 | 6 人无跳登录、无 401；管理员登录一次后同事直接可用 | ✅ 2026-11-06 核心链路已验证：全新 origin（`172.30.3.237:8901`，无任何 cookie/localStorage）打开直接进「工作台」，`/napi/v1/creative/list`、`/creative/count` 均 200；多机并发待同事实测 |
| P2 | 失效检测校准、访问日志、管理操作、UI 完整态 | 清空会话后卡片变黄；重登后变绿；日志有记录 | 部分随 P0 落地 |
| P3 | 有米云接入（8902） | 同上 | 待定 |

P1 需要用户配合：**由管理员在网关页面里输入账号密码 + 过验证码**（我不接触密码）。

**P1 验证记录（2026-11-06）**
- 空白页根因：CDN 对网关 Referer 返回 403 → `ERR_BLOCKED_BY_ORB` → main.js 不加载；注入 no-referrer 后修复（临时实例先验证出登录页，再在生产验证出工作台）。
- 会话罐实测只学到 `user-token`（32 字符），**没有 `ZFSESSID`**；仅凭它在全新 origin 上就能把 `/napi/v1/creative/list` 拉到 200 并渲染广告列表 —— 说明这个站的接口鉴权主要靠 `x-nbs-user-token`，`ZFSESSID` 不是必需。
- 已知不覆盖：`agent.guangdada.net`（Copilot/知识库问答）是跨域服务，浏览器直连带 Origin 校验，被 CORS 拦；要在网关里用 Copilot，得再做 host 映射。

## 11. 涉及文件

```
新增：
py/share_gateway/__init__.py
py/share_gateway/jar.py          # cookie jar + AES-GCM
py/share_gateway/ticket.py       # 票据签发/校验 + 每站 cookie 名
py/share_gateway/proxy.py        # 代理与重写 + 网关鉴权/进入页（核心）
py/share_gateway/runtime.py      # 每站点会话罐运行时 + 状态自检
py/share_gateway/store.py        # 站点/会话/日志 SQL
py/share_gateway/runner.py       # 独立 waitress 线程 + 心跳线程
py/routes/share_routes.py        # /api/share/*
py/tests/test_share_gateway.py   # jar/ticket/重写/端到端/接口 单测
frontend/src/views/ShareView.vue
frontend/src/api/share.js

改动（极小）：
py/main.py                       # 注册 blueprint；__main__ 里启动网关
py/database.py                   # 3 张表
frontend/src/router/index.js     # /share 路由
frontend/src/components/AppSidebar.vue  # 三平台菜单项
config/config.json               # share_gateway 节点
docs/superpowers/specs/...       # 本文档
AGENTS.md                        # 设计文档索引 + 模块说明
```

## 12. 已确认的四项（2026-11-06 用户选择）

1. **入口**：一级菜单「🔗 共享账号」，GG/FB/TT 三平台可见（户管菜单不显示）。
2. **权限**：所有登录用户可打开；仅 developer 可管理（清空会话 / 日志 / 启用停用 / 检测）。
3. **端口**：**80（广大大，2026-11-06 由 8901 改过来：个别客户端只放行 80/5001）**、8903（Insightrackr）、8902（有米云），需在服务器防火墙放行。
4. **重登方式**：会话失效时由管理员在网关页面里手动登录（密码不落库、不经过网关日志）。
