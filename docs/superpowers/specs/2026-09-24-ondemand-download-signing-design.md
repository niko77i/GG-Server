# 下载签名按需签发 + scrape 产物归属校验 设计文档

> 状态：**已实施（轻方案）** —— §三 描述的「新增 `/api/download-url` 端点 + 前端 7 处改异步」**已被否决**，
> 实际落地的是 §零 的轻方案。
> 前置：`2026-09-24-anonymous-surface-hardening-design.md`（匿名面收口，已上线）
> 关联裁决：本文件 §五 五条裁决，来自 2026-09-24 的对话

---

## 零、最终实施的方案（轻方案）—— 先读这一节

§三 的重方案（新增端点 + 前端 7 处下载入口改异步）**未实施**。理由：它要动 7 个前端调用点、
引入 `window.open` 用户手势陷阱、并把「归属」这一条纯后端约束和一次 UX 改造捆在一起交付 ——
收益与风险不成比例。用户 2026-09-24 裁决改走轻方案。

**轻方案实际做了三件事，全部在 `py/main.py` 内：**

| # | 改动 | 落点 |
|---|---|---|
| 1 | **TTL 锚定到应用 JWT 寿命**（`JWT_ACCESS_TOKEN_EXPIRES`，默认 86400s），不再写死 300s。新增 `_signed_download_url(endpoint, path)` 在**调用时**读配置取 TTL，替换全部 5 处 `_sign_query(...)` | `_signed_download_url` 定义于 `_get_ffmpeg_path()` 之后；5 处调用点：`/api/scrape`、video_progress 的 db_task 分支与 task.result 分支、audio_replace、audio_history |
| 2 | **堵侧门**：`POST /api/scrape` 的 `save_dir` 分支收窄 —— 必须是**自己**的目录，或调用者是 developer/admin（复用 `scrape_packages` 的既有判据） | `_is_within` / `_scrape_dn_for` / `_scrape_dir_for` 三个共享辅助函数，`scrape_packages` 一并改用它，从结构上消除两侧漂移 |
| 3 | **堵正门**：`GET /api/scrape/download` 在**有身份时**校验归属，且**置于存在性检查之前** | 由 `if get_jwt_identity() is not None:` 守护；管理员豁免同上 |

### 0.1 为什么侧门才是真正的关口（实施中发现，重方案没覆盖）

`/api/scrape/download` 是 `@jwt_required(optional=True)`：合法 JWT **或** 有效签名二者其一放行。
签名路径由浏览器原生请求消费（`window.open`），**不带 `Authorization`** ⇒ 校验方**拿不到身份**，
在该路径上根本无从判断归属。

⇒ 只堵正门等于做样子：攻击者不走那道门。**运行时实证**（2026-09-24）：

```
bob 传 save_dir = alice 的目录 → POST /api/scrape → 200
                                ↑ 响应里带着一个为 alice 的包签发的**合法签名**
bob 用该签名 GET /api/scrape/download（不带 token）→ 200，120 字节
```

⇒ 归属必须在**签发侧**（`save_dir`）堵死。正门那道校验的价值是「挡住直接带 token 的读取」，
不是本次收口的主力 —— 这一点重方案（只加新端点 + 正门）漏了。

### 0.2 TTL 取舍

| | 重方案（否决） | 轻方案（实施） |
|---|---|---|
| TTL | 维持 300s，靠「点击时现签」规避过期 | **锚定 JWT 寿命**（默认 86400s） |
| 「URL 被转发」窗口 | 300s | 24h（**比原来放宽了**） |

放宽是有意的：签名 URL 本就是 JWT 在**浏览器原生请求**场景下的替身，不应比它替代的东西活得更久，
但也不该**短得多** —— 前端没有重签路径，300s 会让「面板停留后点下载」必 401（缺口 A 的原始现象）。
恒等于 JWT 寿命是有原则的边界，代价是转发窗口从 5 分钟扩到 24 小时，记为已知风险（§九）。

### 0.3 验收结果（2026-09-24 实测）

- 全量套件 **684 passed, 0 failed**（新增 `py/tests/test_scrape_ownership.py` 15 例）
- 变异验证 5/5 全部实测转红后回滚：M1 侧门 `if False` → 2 红；M2 正门 `if False` → 3 红；
  M3 `_is_within` 退化为裸 `startswith` → 2 红；M4 角色集加入 `huguan` → 2 红；M5 `ttl=300` → 1 红
- 既有测试协调：`test_security_hardening.py::TestAClassFileWhitelist` 的两条（`requires_existing_dir`
  / `allows_dir_inside_scrape_root`）改用 `dev_headers` 穿过归属层，断言逐字不变 ——
  该类的职责是钉**白名单层**，归属层由新文件承重

### 0.4 未随本次交付的（明确记录）

- 前端**未做任何改动**，dist 无需为此重建（上一轮的 dist 重建已在裁决 1 中完成）
- video/audio 两条端点的跨用户读**维持现状**（无 `user_id` 列，按设计即全局共享）—— 见 §1.3
- `_find_font_path` 反斜杠穿越仍未处置（独立议题）

---

## 一、需求描述

### 1.1 背景

上一轮收口（提交 `ee3bd4b`）给三条产物下载端点加了**签名 URL**：匿名者拿不到签名因而被挡在门外，签名 URL 由受 JWT 保护的 axios 接口下发。

上线后运行时实测暴露出该设计的**两个缺口**，二者都源于「签名在**列表/请求起点**一次性签发、TTL 固定 300 秒」：

| 缺口 | 实测现象 | 根因 |
|---|---|---|
| **A. 签名过期即死** | 音频替换历史面板停留 >5 分钟后点「⬇ 下载」→ **401**；批量爬取串行 await 超 300s 时，靠前链接的下载按钮**到手即失效** | 签名在列表响应的那一刻签发，前端**没有任何重签路径**；`window.open` 是浏览器原生请求，不带 `Authorization`，签名是唯一凭证 |
| **B. 跨用户读保留** | bob 带自己的合法 token 下载 alice 的包目录 → **200**（131 字节 zip）；对照匿名同一目录 → 401 | `/api/scrape/download` 只校验「已登录」+「路径在 `_SCRAPE_DEFAULT_DIR` 内」，**不校验归属**。而该目录下的目录名即用户 `display_name`（[main.py:441](../../py/main.py#L441) 的 `os.path.join(_SCRAPE_DEFAULT_DIR, dn)`），归属信息**本就在手**，只是没校验 |

### 1.2 目标

1. 下载签名**在用户点击时现签**，TTL 维持 300 秒不变 —— 长生命周期界面不再撞过期。
2. `/api/scrape/download` 补上**归属校验**：登录用户只能下载**自己名下**的爬取包。
3. 兑现 §4.3 遗留的那句「归属校验留待裁决」——**只兑现 scrape 一条**，video/audio 两条按数据模型维持全局共享（见 §1.3）。

### 1.3 非目标（明确不做）

| 不做的事 | 理由 |
|---|---|
| 给 `video_tasks` / `audio_replace_history` 加 `user_id` 并回填 | 两表**无任何用户字段**（[database.py:173-184](../../py/database.py#L173-L184)、[:468-476](../../py/database.py#L468-L476)），它们在数据模型上**就是全局共享的产物库**。「A 能下 B 的产物」对它们不是缺陷。要隔离须改表 + 迁移，属独立新功能 |
| 延长签名 TTL | 裁决选的是「按需签发」，TTL 保持 300s —— 「URL 被转发」的有效窗口不被放宽 |
| 改动三条端点的**校验语义** | 仍是「合法 JWT **或** 有效签名」二选一放行，`_download_authorized` 的判据不变 |
| 触碰 `_find_font_path` 反斜杠穿越 | 独立的待裁定议题（见 MEMORY `windows-backslash-path-traversal`），本文件不涉及 |

---

## 二、事实基础（取证）

以下均为**运行时实测**，非读码推断。

### 2.1 缺口 A 的证据链

- `/api/video/progress`（[main.py:1012](../../py/main.py#L1012)、[:1042](../../py/main.py#L1042)）、`/api/audio-replace/history`（[:1302](../../py/main.py#L1302)）在**响应构造时**调用 `_sign_query(...)`，TTL 取默认 300s。
- 前端把这串 URL 存进 `ref` 或 store（`VideoView.vue:340/632/692`、`ToolkitView.vue:722`），点击时直接 `window.open` —— **全程没有任何重签动作**。
- 旁证：本仓库验证签名闭环时，用 `ttl=-1` 构造的过期签名打真实服务返回 **401**，与面板超时后的表现一致。

### 2.2 缺口 B 的证据链

用 Flask test client 造两个用户 + 一个受害者目录：

```
受害者目录: D:\...\temp\scraped_images\alice_victim\VictimPkg
bob 带 token 下载 alice 的包 -> 200 字节数: 131
匿名下载同一目录           -> 401
```

⇒ 匿名面确实堵死了（B-3 生效），但**认证用户之间无隔离**。

### 2.3 归属信息的可用性（决定方案可行性）

| 端点 | 归属可判定吗 | 依据 |
|---|---|---|
| `/api/scrape/download` | **可**，且无需改表 | 路径形如 `_SCRAPE_DEFAULT_DIR/<display_name>/<包名>`，[main.py:441](../../py/main.py#L441) 是构造方。对照：`/api/scrape/packages` 已经在按 `user_dn` 收窄 |
| `/api/video/download` | 不可 | `video_tasks` 无用户字段 |
| `/api/audio-replace/download` | 不可 | `audio_replace_history` 无用户字段 |

### 2.4 为什么「点击时现签」能同时解决 A 和 B

上一轮文档 §4.3 曾记下一个死结：

> 归属校验留待裁决——签名 URL 场景**无 token**，须在签名 payload 内携带 user_id 才可能校验

「点击时现签」**解开了这个死结**：签发请求走 axios，**带 `Authorization` 头**，服务端此刻**有完整身份**，可直接查归属，再把结果固化成签名。归属校验因此不必挤进签名 payload。

---

## 三、技术方案

> ⚠️ **本节整体未实施（已被否决）**。保留作为决策记录 —— 它记录了「为什么不走这条路」，
> 且其中的 §3.1「必须沿用 `scrape_packages` 既有模式」的教训在轻方案里**依然适用并已落实**。
> 实际方案见 §零。

### 3.1 新增端点：`POST /api/download-url`

```
POST /api/download-url
Headers: Authorization: Bearer <jwt>      # 必需，硬 @jwt_required()
Body:    { "path": "<绝对路径>" }
响应 200: { "success": true, "download_url": "/api/scrape/download?path=...&exp=...&sig=..." }
响应 400: { "success": false, "error": "..." }    # 路径缺失 / 不属于任何已知产物
响应 403: { "success": false, "error": "..." }    # 归属校验不通过
```

**路由归属校验表**（按「路径落在哪个产物的地盘」分派）：

| 路径形态 | 校验规则 | 失败码 |
|---|---|---|
| 落在 `_SCRAPE_DEFAULT_DIR` 下 | `realpath` 必须落在 `_SCRAPE_DEFAULT_DIR/<该用户有权访问的 dn>` 之下（dn 取法见下方「必须沿用既有模式」） | 403 |
| 命中 `video_tasks.output_path` | 该行存在即可（数据模型无归属，维持全局共享） | 400（无此产物） |
| 命中 `audio_replace_history.output_path` | 同上 | 400 |
| 都不落在 | 拒绝 | 400 |

#### ⚠️ 必须沿用 `scrape_packages` 的既有模式（否则「收口过头」）

[`scrape_packages`](../../py/main.py#L618-L628) 已经确立了本项目对「爬取包归属」的处理模式：

```python
is_admin = user and user["role"] in ("developer", "admin")
user_dn = request.args.get("user_dn", "").strip()
if user_dn and is_admin:
    dn = user_dn                                    # 管理员：可指定他人
else:
    dn = (user.get("display_name") or user.get("username") or f"user_{user_id}").strip()
```

⇒ **角色集合必须与 `scrape_packages` 完全一致**（`("developer", "admin")`，注意**不含** `huguan`——尽管 `routes/helpers.py:8` 的 `CROSS_USER_ROLES` 含它，本端点的既有判据不含，不得擅自扩大）。

**为什么这条是硬约束**：`POST /api/download-url` 是**下载侧**，`scrape_packages` 是**列表侧**。若两侧的权限集合不一致（例如列表侧放行管理员看他人包、下载侧却 403），管理员会在界面上**看得到、点不动**——这正是「禁止因新增功能导致已有功能失效」。因此归属规则的唯一正确来源是**与列表侧同源**。

**具体的 UI 复现路径**（管理员被打断的确切位置）：

1. `MediaView.vue:538` → `videoApi.packages(userDn || '')` → `video.js:19` 拼 `?user_dn=` → 后端 `scrape_packages:624` 的 `is_admin` 分支放行 → **界面列出 alice 的包**
2. 用户点该包的下载按钮 → `MediaView.vue:281` / `downloadImages()` → 若本设计漏掉 `is_admin` 豁免 → **403**

⇒ 只做「比对自己目录」不做管理员豁免，等于**把已能看到的包变成点不动**，正是必须避免的「新增功能导致已有功能失效」。

**关键实现约束**：

1. **归属比对必须先 `os.path.realpath` 归一化再比**，且用 `real == own_root or real.startswith(own_root + os.sep)` 的**边界安全**写法（不能裸 `startswith`，否则 `alice2` 会被 `alice` 前缀放行）。参照 [`_is_safe_music_path`](../../py/main.py#L773) 的既有写法。
2. **不得复用 `_is_safe_path`**（其白名单含整个 temp 树）。
3. 端点自身必须 `@jwt_required()`（硬），且**不加** `optional=True` —— 新端点不得进入匿名面。
4. 复用既有的 `sign_query`，不引入第二套签名实现。
5. **管理员路径的判据要与列表侧同源**：建议把 `scrape_packages` 里那段 dn 推导**提取为共享辅助函数**（如 `_resolve_scrape_dn(user, requested_dn)`），两处共用。否则两侧迟早漂移 —— 这是本仓库已记录过的「修复链漂移」教训。**提取属重构**：只搬运逻辑、不改判据，且需保持 `scrape_packages` 行为逐字不变（回归测试兜底）。

### 3.2 前端：7 处下载入口改为「先取签名、再打开」

**⚠️ 本方案唯一的技术陷阱：`window.open` 的用户手势**

`window.open()` 必须在**用户手势的同步调用栈内**执行。若写成：

```js
const { download_url } = await api.post('/download-url', { path })   // await 吃掉手势
window.open(download_url, '_blank')                                   // ← 被弹窗拦截器挡住
```

浏览器会判定为「非用户发起的弹窗」而拦截。**正确写法**是先同步开一个空白页，异步拿到 URL 后再改它的 `location`：

```js
async function openDownload(path) {
  const w = window.open('', '_blank')          // ← 同步，手势仍有效
  try {
    const { download_url } = await api.post('/download-url', { path })
    if (w) w.location = download_url
    else window.location.href = download_url   // 极端兜底：空白页都被拦
  } catch (e) {
    if (w) w.close()                           // 取签名失败 ⇒ 不留空白页
    ElMessage.error(e.response?.data?.error || '下载失败')
  }
}
```

改造清单（**共 7 处**，均为「把同步 `window.open(自拼URL)` 换成 `await openDownload(path)`」）：

| 文件 | 位置 | 当前形态 |
|---|---|---|
| `MediaView.vue` | `:281` 图片包 ⬇ | 已消费 `it.download_url` ⇒ 改为按需 |
| `MediaView.vue` | `downloadImages()` `:379` | 同上 |
| `MediaView.vue` | `downloadVideo()` `:855` | 同上 |
| `ScrapeView.vue` | `downloadImages()` `:89` | 同上 |
| `VideoView.vue` | `downloadVideo()` `:720` | 同上 |
| `ToolkitView.vue` | `audioDoDownload()` `:729` | 音频替换产物 ⬇ |
| `ToolkitView.vue` | `audioHistoryDownload()` `:757` | 音频替换历史 ⬇ |

### 3.3 后端列表响应里的 `download_url` 怎么处理

**保留**，不改。理由：

- 纯增量 —— 保留它意味着**现有前端逻辑不失效**，也给了 GET 路径一条退路。
- 按需签发是**叠加**在它之上的：前端点击时优先取新签名，取不到才退回列表里的旧 URL。
- 移除它会扩大改动面（3 处签发点 + 相关测试），与「纯增量」原则相悖。

### 3.4 回归测试（纯增量）

**新增** `py/tests/test_download_url.py`：

| 用例 | 断言 | 承重理由 |
|---|---|---|
| 自己目录 → 200 且 URL 可被对应端点放行 | 拿响应里的 URL 打端点 ⇒ **200** | 闭环：签发侧与校验侧约定一致 |
| 他人目录 → 403 | bob 请求 alice 的目录 | 本次核心交付 |
| **前缀同族陷阱**：`alice` 用户请求 `alice2` 的目录 → 403 | 专门钉住 `startswith` 缺 `+ os.sep` 的写法 | 裸 `startswith` 会在此放行 |
| **管理员读他人目录 → 200** | `developer`/`admin` 请求 alice 的目录 | **反向承重**：防「收口过头」把管理员既有工作流打断（对应 `scrape_packages` 的 `is_admin` 分支） |
| **`huguan` 读他人目录 → 403** | `huguan` 请求 alice 的目录 | 钉死角色集合**与列表侧一致**，不得擅自加入 `CROSS_USER_ROLES` 里的 `huguan` |
| 不在任何产物地盘的路径 → 400 | 如 `C:\Windows\` | 防变成「万能签名器」 |
| 匿名请求 → 401 | 无 `Authorization` | 防 `optional=True` 误加 |
| `video_tasks` / `audio_replace_history` 既有行 → 200 | 维持全局共享不被误伤 | 防收口过头 |

> 本项目定式：**无对照行的断言 = 假绿**。「他人 → 403」必须配一条「管理员 → 200」，否则把整条链路写成 `return 403` 也能全绿。

**变异验证（必做，贴原始输出）**：

- M1：把归属比对写成裸 `startswith(own_root)`（去掉 `+ os.sep`）⇒ 「前缀同族陷阱」用例**必须变红**
- M2：把 `_download_authorized` 的 `return _verify_query(...)` 临时改成 `return True` ⇒ 既有 B-3 的「匿名 401」「假签名 401」用例**必须变红**

### 3.5 部署

新端点属**后端改动**，需重启 5001；前端 `dist` 需 `npm run build`。二者都是本次交付的一部分 —— 上一轮正是因为**只改了源码没重建/重启**，导致收口在线上完全没有生效（dist 构建于 05:21、进程启动于 02:45，均早于 15:40–16:08 的提交）。

---

## 四、涉及的文件 / API

| 文件 | 改动 |
|---|---|
| `py/main.py` | **新增** `POST /api/download-url` 及其归属校验辅助函数；**重构**：把 `scrape_packages:620-628` 的 dn 推导提取为 `_resolve_scrape_dn(user, requested_dn)`，两处共用（只搬运、不改判据）；复用既有 `sign_query` |
| `py/tests/test_download_url.py` | **新增**（§3.4） |
| `frontend/src/api/client.js` | 可能新增一个 `fetchDownloadUrl(path)` 封装；`client.js` 已自动注入 `Authorization`，无需改动 |
| `frontend/src/views/MediaView.vue` | 3 处下载入口改异步 |
| `frontend/src/views/ScrapeView.vue` | 1 处 |
| `frontend/src/views/VideoView.vue` | 1 处 |
| `frontend/src/views/ToolkitView.vue` | 2 处 |
| `frontend/dist` | `npm run build` 重建 |

**不涉及**：`py/url_signing.py`（签名算法不变）、`py/database.py`（**无 schema 改动** —— 这正是「只修 scrape」的收益）。

---

## 五、裁决结果（2026-09-24 已定）

| # | 议题 | 裁决 |
|---|---|---|
| 1 | 线上是旧代码（dist 陈旧 + 进程陈旧），是否部署对齐？ | **是** —— 已执行：`npm run build` 重建 dist、重启 5001。运行时复测 A 组 8 条匿名 401、B-3 三条匿名 401、匿名白名单 7 条保留、签名闭环 6/6 |
| 2 | 跨用户读怎么处置？ | **只修 `/api/scrape/download`**。video/audio 两条因表无 `user_id` 且属全局共享产物库，维持现状并记为已知风险 |
| 3 | 签名 TTL 300s 撞长生命周期界面，怎么处置？ | **改为点击时按需签发**，TTL 维持 300s。该方案同时为归属校验提供天然落点 |
| 4 | 重方案（§三）太重，是否改走轻方案？ | **是，改走轻方案**（§零）。重方案整体否决，未实施 |
| 5 | 轻方案下 TTL 取多少？ | **锚定 `JWT_ACCESS_TOKEN_EXPIRES`**（默认 86400s），经 `_signed_download_url` 在调用时读配置。理由与代价见 §0.2 |

> 裁决 3 与裁决 5 的口径已被裁决 4 取代：裁决 3 的「TTL 维持 300s」**未执行**。

---

## 六、数据结构

**无改动。** 不新增表、不加列、不做迁移。

归属校验所需的 `display_name` 从 `users` 表现取（`auth.get_user_by_id(user_id)`，与 [main.py:439](../../py/main.py#L439) 同一取法），不落库、不缓存。

---

## 七、UI 改动

**无视觉改动**：不新增按钮、不改布局、不改交互形态，仅把 7 处下载按钮的**内部实现**由同步改为异步。

⚠️ 但**存在可感知的行为变化**，须在验收时覆盖：点击到文件开始下载之间会多一次网络往返（本地通常 <50ms，无感），失败时以 `ElMessage.error` 提示而不再是静默打开一个 401 页面。**这比现状更好** —— 现状是点开一个白页显示 `{"error":"未授权"}`。

⇒ 不触发 `/frontend-design`（无视觉设计工作）。

---

## 八、验收标准

1. §3.4 全部用例通过，且 M1/M2 两个变异验证**都实测转红**。
2. 运行时实测（真实 5001，非 test client）：
   - 自己目录取签名 → 下载成功
   - 他人目录取签名 → 403
   - 匿名取签名 → 401
3. 浏览器 DevTools 实测（**本设计新增的必做项**）：
   - 点击下载**不再触发弹窗拦截**（验证 §3.2 的空白页写法在真实浏览器有效）
   - 音频替换历史面板**停留 6 分钟以上**再点下载 → **成功**（这是缺口 A 的原始复现路径，必须由红转绿）
   - Network 面板确认 `/api/download-url` 带 `Authorization` 头，随后对 `/api/*/download` 的请求**不带** `Authorization` 但带 `exp`/`sig`
4. 全量测试不回归。

---

## 九、风险与边界

| 风险 | 评估 | 处置 |
|---|---|---|
| 空白页写法在个别浏览器仍被拦 | 低。`window.open('', '_blank')` 在同步栈内执行，是业界通行解法 | 兜底 `window.location.href`；验收第 3 条实测覆盖 |
| `/api/download-url` 沦为「万能签名器」 | **中，必须防**。若归属校验写错，任何登录用户可为**任意路径**取签名，等于绕过本次全部收口 | §3.4「不在任何产物地盘 → 400」用例 + M1 变异验证承重 |
| `startswith` 前缀同族越权（`alice` 读 `alice2`） | **中**。本仓库已有 `alice`/`alice2` 两个真实用户目录，恰好构成现成陷阱 | 强制 `real == root or real.startswith(root + os.sep)`；专门用例 |
| **收口过头打断管理员工作流** | **中，且已在设计阶段识别出一次**。初稿的归属规则漏了 `scrape_packages` 的 `is_admin` 分支，会让管理员「看得到包、点不动」 | §3.1「必须沿用既有模式」硬约束 + §3.4「管理员 → 200」反向承重用例；dn 推导提取为共享函数，从结构上消除两侧漂移 |
| 重构 `scrape_packages` 时改动其行为 | **中** | 只搬运 dn 推导、不改判据；提取后必须跑既有回归测试确认 `scrape_packages` 行为逐字不变 |
| **签名 URL 的转发窗口由 300s 放宽到 24h**（轻方案 §0.2） | **低–中**。签名 URL 一旦被转发（日志、截图、复制粘贴），在 24h 内对**该条路径**持续有效 | 接受。理由：签名路径本就只能校验「路径正确」而无法校验「来者是谁」（§0.1），窗口长短不改变这一性质；且窗口若不锚定 JWT 寿命，「面板停留后点下载」必 401 |
| video/audio 两条维持跨用户可读 | **低**，且是**既有**状态（上一轮之前它们是**匿名**可读，现在至少需要有效会话） | 记为已知风险，不在本文件范围内 |
| 前端 dist 再次忘记重建 | **中** —— 上一轮就是这么漏的 | §3.5 写入交付清单；验收第 3 条在浏览器里跑，天然要求 dist 是新的 |
