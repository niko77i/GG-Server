# 匿名可达端点收口 设计文档

**日期**：2026-09-24
**状态**：**已确认**（2026-09-24）—— 3 处裁决结果见 §5
**来源**：安全加固（`2026-09-23-security-hardening-design.md`）验收阶段发现的**未识别缺口**

---

## 一、需求描述

### 1.1 背景

安全加固的 10 个 Task 已全部完成并提交，验收结论为「**条件上线**」，三条门禁未过。本设计处理其中**优先级最高、且在安全加固的设计阶段完全未被识别**的一条：**匿名可达端点**。

该缺口是在 Task 10 交付「全站鉴权矩阵表」时，由一次**独立于原判据**的运行时普查发现的（`.superpowers/sdd/anon-surface-scan.md`）：

- 真实匿名可达端点 **20 条**，而矩阵表的 A 类方法只识别出 **3 条**，**漏 17 条**。
- 根因是**判据错位，不是漏扫**：A 类靠「装饰器栈里有没有 `jwt_required`」识别匿名面，而 `@jwt_required(optional=True)` **有**该装饰器（带 token 时有身份、不带 token 也放行），因此**必然**被判为「需登录」——这一类被定义在了判据的视野之外。
- 全仓 `optional=True` 端点共 **12 个**，A 类只识别出 **1 个**。

⇒ 结论：**该缺陷类别在原有方法论下不可能被发现**，不是执行疏漏。

### 1.2 目标

1. 把匿名可达面从 20 条收口到**一份显式白名单**——白名单之外的任何端点，零 token 必须 401。
2. 建立**常驻回归测试**，使「某端点悄悄变成匿名可达」从此**不可能再隐身**。
3. 收口过程中**不破坏任何现有前端功能**。

### 1.3 非目标

- 不处理安全加固已记录的其他缺口（I-2 的 28 组 `<int:...>`、O-1 的 79 处非 dict 体、O-2 的 traceback 回显等）。那些**另行裁决**，本设计不扩大范围。
- 不引入新的鉴权框架或角色模型。

---

## 二、事实基础（取证）

以下均为**实测/读码所得**，非推断。

### 2.1 `optional=True` 是误加，不是设计——三重独立证据

对 `/api/products/list` 与 `/api/products/create` 两个端点：

| 对照维度 | 事实 |
|---|---|
| **同族**（`/api/products/*` 共 18 个端点） | **16 个强制 `@jwt_required()`**，只有 `list`、`create` 这 2 个是 `optional=True` |
| **跨平台**（同功能的 TT / FB 实现） | `/api/tt/products/list`（[tt_routes.py:146-147](../../py/routes/tt_routes.py#L146-L147)）、`/api/fb/products/list`（[fb_routes.py:482-483](../../py/routes/fb_routes.py#L482-L483)）**均强制 `@jwt_required()`**；create 同理。**GG 是三个平台中唯一的例外** |
| **代码注释自证** | `products_create` 首行调用的 `reject_viewer()`（[decorators.py:53-62](../../py/routes/decorators.py#L53-L62)）在匿名分支上注释写着：<br>`except Exception:`<br>`    return None  # 未登录，由 @jwt_required() 处理`<br>作者**假定** `@jwt_required()` 会拦住未登录；`optional=True` 使该假定落空，这行从「交给装饰器处理」变成了「**匿名放行**」。`reject_huguan()`（[:65-73](../../py/routes/decorators.py#L65-L73)）是同一个注释、同一个塌陷 |

**同族的另 16 个端点**（runner-products、`<pid>` PUT/DELETE/restore、merge、runners、detail、packages 全族、check-delist、delist-status、import-text、assets 全族）**全部已是强制鉴权**——收口这两个是**向既有形态对齐**，不是发明新形态。

### 2.2 匿名读全库的机制（`products_list`）

[routes 2520-2529](../../py/main.py#L2520-L2529)：`runner` 默认 `"mine"`，该分支内 `user_id = int(get_jwt_identity())` 在匿名时抛异常 → `user_id = None` → `if user_id:` 为假 → **完全不加 runner 过滤条件** → 查询退化为「全库产品」。

⚠️ 但注意：`runner=all`（[:2530-2531](../../py/main.py#L2530-L2531)）**本来就对所有登录用户开放**。⇒ 加回强制鉴权**不改变任何登录用户的可见范围**，只挡住匿名。

### 2.3 前端调用方式（`.superpowers/sdd/frontend-call-survey.md`）

- axios 实例（`frontend/src/api/client.js`）**条件注入** `Authorization`：仅当 `localStorage.token` 存在时添加。
  ⇒ **「axios ⇒ 必然带 token」不成立**；正确判据是「axios **且** 调用时 localStorage 有 token」。
- `frontend/src/router/index.js:170-178` 的 `beforeEach` 对**非 `meta.guest`** 路由强制登录；`/login`、`/register` 是仅有的 guest 路由。
  ⇒ **除这两个页面外，所有调用点都在登录后可达的页面，token 必然存在。**
- 浏览器原生请求（`<img>` / `@font-face url()` / `<audio>` / `window.open`）**平台层面无法附加自定义请求头** ⇒ 加 `@jwt_required()` 必然打断。

### 2.4 无外部调用方

全仓路径扫描确认：命中这些 API 路径的只有 `frontend/src/`、`py/tests/`、`docs/`、`py/main.py`（定义处）、`py/routes/`（TT/FB 同族定义）。**不存在定时脚本、外部系统或桌面集成以非浏览器方式调用**。

---

## 三、匿名面清单与分组

20 条真实匿名面中，**静态资源类 5 条**（`/`、`/<path:filename>`、`/favicon.ico`、`/api/health`、`/api/image` 之外的框架级资源）属 Flask 默认或健康检查，**维持匿名**。以下处理**业务端点 15 条**。

### A 组：可直接加鉴权（8 条，**前端零改动**）

调用点全部为 axios 且位于登录后页面（§2.3），因此去掉 `optional=True` 即可。

| 端点 | 改法 |
|---|---|
| `GET /api/products/list` | `@jwt_required(optional=True)` → `@jwt_required()` |
| `POST /api/products/create` | 同上 |
| `GET /api/users/names` | 同上 |
| `GET /api/settings/account` | 同上 |
| `GET /api/auth/names` | 同上（**现役前端零调用点**，`8957fc7` 起已改用 `/api/fb/users`、`/api/tt/users`） |
| `POST /api/browse-file` | `optional=True` → 强制（`_can_browse()` 闸门行为不变） |
| `POST /api/browse-save` | 同上 |
| `POST /api/browse-folder` | 同上 |

**附带效果**：`/api/users/names` 加鉴权后，anon-scan §3.11 记录的「**匿名**可枚举含 developer 的用户名」缺陷自然消解。
⚠️ **但「登录用户仍可枚举 developer」这一独立缺陷并未被修复**——本设计不处理它，不得声称已修。

### B 组：浏览器原生消费，不能简单加鉴权（7 条）

加 `@jwt_required()` 会打断的具体功能（前端调查报告实测）：

| 端点 | 装饰器现状 | 打断什么 |
|---|---|---|
| `GET /api/image` | **无鉴权** | 媒体工具图片网格缩略图（`MediaView.vue:109`）+ 拖拽排序面板缩略图（`:98`）⇒ 全部破图 |
| `GET /api/font-file` | **无鉴权** | 「文案」字体选择器实时预览 ⇒ 401 后 `.catch` 静默回退默认字体、**无错误提示**（`:1045-1048`） |
| `GET /api/audio` | `optional=True` | 「背景音乐」下拉试听 ⇒ `audio.play()` reject 被空 catch 吞掉，**点选无反应**（`:674`）。限定：仅影响**非 localhost** 访问的用户（`:214` 的 v-if） |
| `GET /api/scrape/download` | `optional=True` | 图片爬取结果行的 📥 下载 zip（`window.open`） |
| `GET /api/video/download` | `optional=True` | 视频生成产物 📥 下载（`window.open`） |
| `GET /api/audio-replace/download` | `optional=True` | 「音频替换」产物下载（**两个入口同时失效**）；`POST /api/audio-replace` 本身是 axios 不受影响 ⇒ 呈现为「能跑完但下载不了」，**用户易误判为生成失败** |
| `POST /api/auth/register` | — | 注册页（guest 路由，前端确实在无 token 下调用）⇒ 见 §5 裁决点 3（**已裁决：保持现状，本轮不改**） |

**B 组按「是否需按用户区分」再分三类——这决定了修法完全不同**：

| 子类 | 端点 | path 约束现状 | 性质 | 建议修法 |
|---|---|---|---|---|
| **B-1 静态资源** | `/api/image`、`/api/font-file` | 白名单**过宽**（`font-file` 实测可取到 `C:\Windows\Fonts\arial.ttf`，1,036,584 字节） | 越界读本地文件 | **收窄路径白名单**，保持匿名 |
| **B-2 音频预览** | `/api/audio` | 读 `temp/music/` 任意文件 | 越界读 | 同上 |
| **B-3 产物下载** | `/api/scrape/download`、`/api/video/download`、`/api/audio-replace/download` | 三条**均有路径边界、均匿名可达**：<br>· `scrape`：目录白名单，限 `_SCRAPE_DEFAULT_DIR` 内（[:584-588](../../py/main.py#L584-L588)）；**有归属信息**（目录名 = `display_name`）但**未校验**<br>· `video`：path 须精确命中 `video_tasks.output_path`（[:1040](../../py/main.py#L1040)）；**无归属字段**<br>· `audio-replace`：path 须精确命中 `audio_replace_history.output_path`（[:1221](../../py/main.py#L1221)）；**无归属字段** | **匿名可达**（`scrape` 另有归属校验缺失；另两条无归属概念） | 见 §5 裁决点 2 |

> ⚠️ **勘误说明**：本表初稿曾将 `scrape/download` 记为「**无**在案校验 ⇒ 真 IDOR」，属**失实**。实测其[:584-588](../../py/main.py#L584-L588)存在目录白名单，IDOR 的成因是**缺用户隔离**而非缺路径边界。已于 2026-09-24 更正。

> **关键判断**：B-1 / B-2 **不需要身份**——它们要的是「不许越出目录」，而非「这是谁的」。因此修法是**收窄白名单**（后端单点改动，**前端零改动、页面功能不变**），而非前端调查报告建议的签名 URL。
> 只有 B-3 的「按用户区分」语义**必须引入身份**，才涉及签名 URL 或前端改造。

---

## 四、技术方案

### 4.1 A 组（8 条）

逐个把 `@jwt_required(optional=True)` 改为 `@jwt_required()`（`/api/browse-*` 三处同）。

**约束**：
- **纯增量**：只改装饰器这一行，不动函数体。
- 改后须复核 `reject_viewer()` / `reject_huguan()` 的行为**回归其原始设计意图**（§2.1 第三条证据）——即匿名请求在装饰器层就被挡下，不再走到 `return None`。
- `products_list` 的 `runner` 过滤逻辑**不动**（§2.2 已证明加鉴权后登录用户可见范围不变）。

### 4.2 B-1 / B-2（3 条，保持匿名）

**逐条复核后：实际只需改 1 条。**（初稿方案已勘误，见下）

| 端点 | 当前边界 | 结论 |
|---|---|---|
| `/api/audio` | `_is_safe_music_path()` **精确限定到 `_MUSIC_DIR`**（[:762-776](../../py/main.py#L762-L776)） | **无需改动**——已是最小化。该函数 docstring 明确说明**不复用** `_is_safe_path`，正是为避免放行 temp 树下的音频替换产物 |
| `/api/image` | `.png` 扩展名 + `_ALLOWED_STATIC_DIRS`（三个项目数据目录：`_SCRAPE_DEFAULT_DIR`、`_MUSIC_DIR`、`_DATA_ROOT/temp`，[:755-759](../../py/main.py#L755-L759)） | **无需改动**——边界已是项目数据目录，而非任意文件系统 |
| `/api/font-file` | 字体扩展名 + `_FONTS_DIR` + **整个系统字体目录** | **需改**——见下 |

#### ⚠️ 勘误：`/api/font-file` 的修法不能是「移除系统字体目录」

初稿写「仅允许项目 `fonts/` 目录；移除系统字体目录」——**该方案会打断现有功能，已废弃**。

实测 [`_scan_fonts_dir()`](../../py/main.py#L1440-L1462) 返回的字体列表**硬编码包含 4 个系统字体**：

```python
    sys_fonts = [
        ("simhei", "黑体",   os.path.join(sys_font_dir, "simhei.ttf")),
        ("msyh",   "微软雅黑", os.path.join(sys_font_dir, "msyh.ttc")),
        ("simsun", "宋体",   os.path.join(sys_font_dir, "simsun.ttc")),
        ("arial",  "Arial",  os.path.join(sys_font_dir, "arial.ttf")),
    ]
```

字体列表带 `"source": "system"` 标记，**前端选择器会列出这 4 个字体**；用户选中即请求 `/api/font-file?path=C:\Windows\Fonts\msyh.ttc`。移除系统字体目录 ⇒ 这 4 个字体预览全部失效。

⇒ **正确修法：按「前端实际需要什么」做白名单最小化** —— 把「整个系统字体目录」收窄为「`_scan_fonts_dir()` 列出的**那 4 个具名文件路径**」。

- **消除**：匿名可读系统字体目录下**任意**字体的暴露面
- **保留**：4 个系统字体 + 用户导入字体的预览**全部可用**（前端零影响）

**约束**：白名单收窄后，前端**现役调用点必须仍可访问**。⇒ 计划阶段须用**真实路径**逐条验证，不得仅凭代码推断。

### 4.3 B-3（3 条）——**签名 URL**（已裁决，见 §5 裁决点 2）

**可复用的既有模式**：`POST /api/audio-replace` 的响应**已经下发** `download_url`（[:1198](../../py/main.py#L1198)），前端取用后直接 `window.open`（`ToolkitView.vue:722` → `:729`）⇒ 本方案对该入口只需**给 URL 加签名**，前端零改动。同一模式推广至另两条。

**端点改造语义**：由「`optional=True` + 路径校验」改为「**要么**持有合法 JWT，**要么**持有未过期签名」二者其一放行（归属语义不变，理由见下方勘误）。签名 URL 由已有的 axios 接口下发——**下发通道本身受 JWT 保护**，这是本方案可信度的前提。

#### ⚠️ 勘误：产物「归属校验」本次不做（数据模型不支持）

设计文档初稿称 B-3 应改为「JWT 且**归属正确**」。实测**该目标不可达**：

- [`video_tasks`](../../py/database.py#L173-L184) **无任何用户字段**（仅 `task_id` / `package` / `status` / `output_path` / `settings` / 时间戳）
- [`audio_replace_history`](../../py/database.py#L468-L476) **同样无用户字段**

⇒ 这两张表的产物**在设计上就是全局共享的产物库**。「登录用户 A 能下载 B 的产物」对它们而言**不是缺陷，而是数据模型没有归属概念**。要做归属隔离必须**改表结构 + 数据迁移**，属新功能，**超出本次范围**。

| 端点 | 有无归属信息 | 本次修什么 |
|---|---|---|
| `/api/scrape/download` | **有**（目录名 = 用户 `display_name`，参照 `scrape_packages` 的推法） | 挡匿名。归属校验**留待裁决**——签名 URL 场景无 token，须在签名 payload 内携带 user_id 才可能校验 |
| `/api/video/download` | **无** | **仅挡匿名** |
| `/api/audio-replace/download` | **无** | **仅挡匿名** |

⇒ **本次 B-3 的实际交付目标收窄为：消除三条端点的匿名可达。** 产物归属隔离作为独立议题另行裁决。

> **后续（2026-09-24 已裁决，见 [`2026-09-24-ondemand-download-signing-design.md`](./2026-09-24-ondemand-download-signing-design.md)）**：
> `/api/scrape/download` 的归属校验**改为做**，video/audio 两条**维持全局共享**。
> 上表那句「签名 URL 场景无 token，须在签名 payload 内携带 user_id」的死结，由「**点击时按需签发**」
> 解开 —— 签发请求走 axios 带 `Authorization`，服务端此刻有完整身份，归属校验不必挤进签名 payload。
> 同轮还修掉了「签名在列表起点一次性签发、TTL 300s、前端无重签路径」导致长生命周期界面点下载必 401 的缺口。

**前端下载入口现状**（决定改动面；path 来源均为 axios 响应，故后端可在同一响应内附签名 URL）：

| 前端入口 | 用途 | path 来源 | 改动 |
|---|---|---|---|
| `ToolkitView.vue:729` | 音频替换产物 ⬇ | **后端已下发** `res.download_url` | **零改动** |
| `ToolkitView.vue:757` | 音频替换历史 ⬇ | 前端自拼（`item.output_path`） | 改为消费下发的 URL |
| `MediaView.vue:377` | 图片爬取结果 📥 | 前端自拼（`r.saved_path`） | 同上 |
| `MediaView.vue:853` | 视频生成产物 📥 | 前端自拼（调用方传入 path） | 同上 |

⇒ B-3 前端改动共 **3 处**，均为「把自拼 URL 换成后端下发的 URL」，**不涉及 UI 布局、交互形态或按钮位置**（故不触发 `/frontend-design`）。

### 4.4 回归测试（与上述并行，纯增量）

**交付物**：`py/tests/test_anon_surface.py`

**核心断言**：遍历 `app.url_map` 全部 GET 规则，用 Flask test client **零 token** 逐条请求；
**「非 401 集合」必须 == 显式白名单集合**（双向断言——既防新增匿名端点，也防白名单腐化）。

- 白名单**显式写出**在测试内，并注明「**这是待收口的债务，不是被认可的设计**」。
- 路径参数替换：`<int:x>` → `1`，`<path:x>` → `'x'`，其余 → `'x'`。
- **必做三个变异验证**（承重）：
  - A：给一个已强制登录的 GET 加 `optional=True` ⇒ 必须**变红**
  - B：从白名单删一条 ⇒ 必须**变红**
  - C：给白名单内端点补 `@jwt_required()` ⇒ 必须**变红**
- 变异在隔离 worktree 内做，**不污染主工作区**。

> 该测试是本次交付物的**方法论修复**：把匿名面从「靠人扫描」变为「机器常驻断言」，使 §1.1 的根因（判据错位）**结构上无法重演**。

---

## 五、裁决结果（2026-09-24 已定）

### 裁决点 1：A 组 8 条是否一次性收口？

**裁决：8 条一次性收口。**

**建议**：是。理由——§2.1 的三重证据表明这是**误加的装饰器**，修复是向既有形态对齐；§2.3/§2.4 表明前端零影响、无外部调用方。这是本设计中**风险最低、收益最直接**的部分。

**风险**：§1.1 的教训是「静态分析曾漏掉这一类」。⇒ 落地后**必须**用真实浏览器 DevTools Network 面板复核这 8 条的请求头确实带 `Authorization`（见 §7）。

### 裁决点 2：B-3 三条产物下载怎么修？

它们是**真/弱 IDOR**（可下载他人爬取图片、他人视频产物）。三条都需要「这是谁的」语义，**必须引入身份**。候选方案：

| 方案 | 做法 | 代价 |
|---|---|---|
| **① 签名 URL**（推荐） | 后端新增短时效 HMAC 签名，由已有 axios 接口下发完整 URL；前端继续 `window.open` | 后端加签名/验签；前端改各消费点改用下发 URL。**适合大文件**（视频） |
| **② 前端改 axios + blob** | 后端加 `@jwt_required()`；前端把 `window.open` 改成 axios 拉 blob + `createObjectURL` | 不引入签名机制（YAGNI）；但**大文件全量入内存**，视频场景有风险 |
| **③ 保留匿名，仅补归属** | — | **不可行**：无身份则无法判归属，此方案不成立 |

**裁决：采用方案 ①（签名 URL）。** 另注：`/api/scrape/download` 无论选哪个方案，都应**改为由 token identity 推目录**（对齐 `/api/scrape/packages` 的既有写法），不再接受调用方指定的任意 `path`。

### 裁决点 3：`POST /api/auth/register` 是否保留公网自助注册？

⚠️ **这不是加不加鉴权的问题**——它是**设计上就应匿名**的入口，前端也确实在无 token 下调用。加 `@jwt_required()` 只会让注册页**静默失效**，**不构成任何安全策略**。

若要禁止公网自助注册，正确做法是**新增配置开关或来源白名单**。**该项应单列裁决，不得并入 A 组批次。**

**裁决：保持现状。** `/api/auth/register` 本轮**不做任何改动**，仅作为已知项记录在案。

---

## 六、涉及文件

| 文件 | 改动 |
|---|---|
| `py/main.py` | A 组 8 处装饰器；B-1/B-2 的路径白名单；B-3 视裁决 |
| `py/routes/*.py` | 视 B-3 方案（若下发签名 URL） |
| `py/tests/test_anon_surface.py` | **新建**（回归测试） |
| `py/tests/test_security_hardening.py` | 追加 A 组收口的断言 |
| `frontend/src/**` | **A 组/B-1/B-2 零改动**；B-3 视裁决 |

---

## 七、数据结构

**无变化**。本设计不涉及任何表结构、字段或迁移。

---

## 八、UI 改动

**A 组 / B-1 / B-2：无 UI 改动**（受影响页面的可见行为不变）。
**B-3：已选签名 URL** ⇒ 前端改动下载触发逻辑（`window.open` 的目标改由后端下发的签名 URL 提供）。页面交互形态与按钮位置不变。

---

## 九、验收标准

1. A 组 8 条：零 token 请求返回 **401**；带任意有效 token 返回**与改动前完全一致**的响应体。
2. B-1/B-2：越界路径（如系统字体目录、目录穿越）被**拒绝**；前端现役调用点的真实路径**仍可访问**。
3. 回归测试 `test_anon_surface.py` 通过，且**三个变异验证全部如实变红**（须留存变异输出）。
4. 全量测试基线**不下降**（当前基线 606 passed）。
5. **浏览器实测**：DevTools Network 面板逐条复核 A 组请求头含 `Authorization`，B 组消费路径未被破坏。
   > 这是安全加固验收时**从未执行**的一步（其设计文档自称「最大风险」），本次**不得再跳过**。

---

## 十、风险与边界

- **最大风险**：B 组「加鉴权会打断前端」的判断**基于读码而非浏览器实测**。前端调查报告已自标两处最薄环节（`el-image` 底层请求未用 DevTools 实测；`dist/` 是否过期未核）。⇒ §9-5 的浏览器复核是**必需的**，不是可选项。
- **本设计的证据边界**：A 组的结论建立在**跨平台/同族形态对照**上（强证据，但有推断成分）；B 组的「不打断」结论建立在**前端调用方式静态分析**上。两者都**尚未**经运行时实测。
- 本次**不修复**、仅记录的其他缺口见 §1.3。
