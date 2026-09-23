# 全站鉴权加固与既有缺陷收口 设计文档

> **状态：待确认，尚未排期。** 用户已表示「另开一个任务去完成」。
> **与户管需求完全独立**：本文件里的每一项**都不是**户管需求（`2026-09-22-huguan-role-design.md`）的一部分，户管需求本身不包含它们。
> **来源**：户管需求验收阶段（最终全分支审查 `b1eb46a..ccf6430` + 控制者自查）在建立「角色 × 平台 × 资源 × 读写」矩阵时**顺带照出来的既有缺口**。它们在本分支之前就已存在。
> **编写日期**：2026-09-23。

## 一、背景

户管角色的验收需要判断「户管能不能碰 X」，因此第一次把三个平台每个端点的鉴权口径逐条过了一遍。这次系统性排查照出了三类既有问题：

1. **一批端点完全不需要登录**（`py/main.py` 里没有 `@jwt_required()`），而服务监听 `0.0.0.0:5001`（`py/main.py:10065-10066`）——任何能连到该端口的人都能调用。
2. **一批端点登录后可越权**：要么没有归属（`owner_id`）校验，要么对普通用户不做租户隔离。
3. **一批端点用 500 响应非法入参**，而不是 400。

这三类都不是本次户管改动引入的，也不影响户管需求本身的正确性。**数据损坏类的问题一条都没有**——全部是「谁能看 / 谁能改」的边界问题与健壮性问题。

## 二、需求描述（本任务要完成什么）

| # | 目标 | 范围 |
|---|---|---|
| 1 | 收口 A 类：**无需登录即可调用**的端点 | 13 条（见 3.1） |
| 2 | 收口 B 类：**登录后越权 / 跨租户可见** | 3 组（见 3.2） |
| 3 | 修 C 类：**入参导致 500** | 2 处（见 3.3） |
| 4 | 清理 D 类：既有死代码 / 谎报 | 3 处（见 3.4，低优先级） |
| 5 | **交付物**：全站鉴权矩阵表 | 逐端点写明「是否需登录 / 需要什么角色 / 有无归属校验 / 有无平台门禁」（见 4.5） |

**不属于本任务**：户管需求本身（子项目 A）与户管 sheet 配置（子项目 B）。**已由户管需求的 Task 20 覆盖**的项见 3.5，不要重复做。

## 三、现状与证据

**证据等级标注**（每项都已标注，实施前请按标注复核）：
- ★ = 控制者**本人实测**（读代码 / 跑脚本 / 发请求）
- ☆ = 子代理报告，**控制者未独立复核**，实施前必须实测确认
- 账本 = `.superpowers/sdd/progress.md` 的记录（该目录被 gitignore，属草稿）

> ⚠️ **行号一律只作参考**：本文件的行号取自 HEAD `0cc21d0`（户管 Task 20 合并**之后**的快照），与更早的分析报告中出现的行号**不一致**（例如 `/api/google-ads/accounts` 曾位于 7193、`/api/translate` 曾位于 7479）。
> **实施时请用「路由路径 + 函数名」作锚点定位，不要按行号找。**

### 3.1 A 类：完全不需要登录即可调用（最高优先级）★

**判定依据**（★实测）：`py/main.py` 的 `_guard_gg_platform`（`@app.before_request`）对未登录请求**直接放行**，其注释原文是「未登录，交给路由自身的 @jwt_required 处理」；而下列路由**没有**那个装饰器，`_guard_gg_platform` 也不覆盖它们（`/api/fonts`、`/api/translate` 等不在 `_GG_ONLY_PREFIXES` 内，`/api/scrape` 在但同样被放行）。

| 路由路径 | 函数名 | 现有装饰器 |
|---|---|---|
| `/api/scrape/download` | `scrape_download` | 无 |
| `/api/image` | `serve_image` | 无 |
| `/api/fonts/list` | `fonts_list` | 无 |
| `/api/fonts/mark-used` | `fonts_mark_used` | 无 |
| `/api/fonts/preview` | `fonts_preview` | 无 |
| `/api/fonts/file/<font_id>` | `fonts_file` | 无 |
| `/api/fonts/import` | `fonts_import` | 无 |
| `/api/fonts/upload` | `fonts_upload` | 无 |
| `/api/font-file` | `serve_font_file` | 无 |
| `/api/google-ads/accounts` | `google_ads_accounts` | 无 |
| `/api/google-ads/report` | `google_ads_report` | 无 |
| `/api/google-sheets/status` | `google_sheets_status` | 无 |
| `/api/translate` | `translate_text` | 无 |

**严重度差异**（实施时按此排优先级）：
- **最高**：`/api/google-ads/accounts`、`/api/google-ads/report` —— 未登录可拉取 Google Ads 账户与报表数据。
- **高**：`/api/scrape/download`、`/api/fonts/file/<font_id>`、`/api/font-file`、`/api/image` —— 文件读取类，需确认是否有路径穿越（`/api/video/download` 的同类问题已由户管 Task 20 处理，可参照其做法）。
- **中**：`/api/fonts/import`、`/api/fonts/upload`、`/api/fonts/mark-used` —— 未登录可写。
- **低**：`/api/translate`、`/api/fonts/list`、`/api/fonts/preview`、`/api/google-sheets/status` —— 只读/计算类。

**可达性补充（说明为什么这些不是纸面问题）**：上表里 `/api/scrape/download` 与 `/api/translate` 分别被前端页面 `/toolkit/zuobiao`（做表数据）与 `/toolkit/translate`（翻译工具）调用，而这两个页面**在浏览器地址栏直接输入即可打开**（不在任何路由守卫的拦截范围内，侧边栏虽无入口但直链可达）。也就是说这些匿名端点不是「没有界面的孤儿接口」，攻击面是真实可触达的。

**不属于本项的一条（避免误列）**：`/analysis`（数据分析）与 `/data-manage`（数据管理）两个页面背后的接口 —— `/api/config/ai`（GET/POST）与 `/api/ad-reports/dates` —— **都已挂 `@jwt_required()` 且按用户隔离**，不属于 A 类。户管能否进这两个页面是**权限范围**问题，不是鉴权缺口。

### 3.2 B 类：登录后越权 / 跨租户可见

| # | 项 | 证据 | 说明 |
|---|---|---|---|
| B-1 | **GG 三个写端点完全不经归属校验**：`accounts_update` / `accounts_reassign` / `accounts_batch_update` | ☆（户管 Task 18 审查者机械核实：这三处无 `owner_id` 判定，且该任务明确被禁止顺手加） | 任何登录用户可修改 / 转移 / 批量修改**别人的** GG 账户。设计文档 `2026-09-22-huguan-role-design.md` §2.5 已把它记为「既有缺口，本设计不修复」 |
| B-2 | **`fb_pixels` 列表对非跨用户角色不做租户隔离** | ★（`py/routes/fb_routes.py` 的 `list_all_pixels`：`where = []`，只有 `search` 条件；`owner_id` 收窄仅在 `role in CROSS_USER_ROLES` 时生效） | 普通 `fb` 用户能看到**全库**像素。户管 Task 16b 明确按用户裁决「最小增量」保留此项未修 |
| B-3 | **`/api/sales-persons/create` 无角色白名单** | ★（实测只有 `@jwt_required()`，无 `GLOBAL_OPTION_ROLES` 判定；插入时用 `_get_effective_platform()` 限定平台） | 设计文档 §3.5 声称这类「设置下拉选项」接口原本有 `is_dev = role in ('developer','admin')` 判断并要改为 `GLOBAL_OPTION_ROLES`，但 `create` 实读**没有**该判断。**待实测确认**：普通 `user` 是否真能创建商务人员；若确实能，属权限缺口；若不能，则属 §3.5 的文档描述不准（该文档需要勘误） |
| B-4 | **TT 代理（`agents` 表 `platform='tt'`）可被任意登录用户改名 / 删除**：`agents_rename`（PUT `/api/agents/<aid>`）与 `agents_delete`（DELETE 同路径）的存在性检查在 `platform == "tt"` 分支上写作 `SELECT id FROM agents WHERE id=? AND platform='tt'` —— **完全不校验 `owner_id`**，且该分支在 `is_dev` 判断**之前**，所以任何登录用户（连 `viewer` 在内）都能改 / 删他人名下的 TT 代理 | ★（实测代码；并已核对 `git show b1eb46a:py/main.py` —— **分支起点时就是这个形态**，属既有缺口，本分支只是把 `is_dev` 从 `('developer','admin')` 扩到含户管，未改变该分支的行为） | 期望：TT 分支同样做归属校验，非跨用户角色只能操作自己的 TT 代理。**注意**：`platform` 来自查询参数 `request.args.get("platform","")`，所以「传不传 `platform=tt`」决定走哪条分支，核实时要覆盖两种调用形态 |

**B 类需要一并核对的同类项**（实施时逐条扫）：`agents_*` / `statuses_*` / `mcc-levels` / `regions_*` / `sales-persons_*` 这几组「设置下拉选项」接口的角色判定是否都已统一到 `GLOBAL_OPTION_ROLES`。设计文档 §3.5 已注明 `regions_*` 四个接口**当前没有任何角色判断**（任意登录用户可调用），并明确按纯增量原则不在户管需求内收紧——**在本任务内应当收紧**。

### 3.3 C 类：非法入参导致 500（健壮性）

| # | 项 | 证据 | 说明 |
|---|---|---|---|
| C-1 | `accounts_create` / `accounts_reassign` 收到 `owner_id` 为**阿拉伯-印度数字**（如 `"٣"`）或**不存在的用户**时 → `int()` / 后续查询抛错 → **500** | ☆（最终全分支审查报告，`isdigit()` 对这类字符返回 `True` 但 `int()` 可解析为 `3`，或用户不存在导致后续失败） | 期望：**400** + 明确文案。**实施前先实测复现**，确认具体失败点与文案 |
| C-2 | `py/auth.py` 的搜索 SQL 缺陷：developer 在「全部」Tab 下搜索时 `base_where` 为空仍拼出 `" AND (...)"` → SQL 语法错误 → **500** | ☆（账本 D1 条目，已上报未答复） | 期望：空 `base_where` 时不拼 `AND`。**实施前先实测复现** |

### 3.4 D 类：既有死代码 / 谎报（低优先级）

| # | 项 | 证据 |
|---|---|---|
| D-1 | `_app_cache.delete(f"accounts:statuses:{user_id}")` 是**死代码**（缓存键实际带 platform/scope 段，删不掉任何东西） | 账本（户管 Task 6 记） |
| D-2 | `accounts_batch_delete` 返回 `deleted: len(ids)`，**不校验实际更新行数**，会谎报条数 | 账本（户管 Task 6 / Task 18 brief 明确「有意不改」） |
| D-3 | `accounts_list` 的早退路径不关闭请求级数据库连接 | 账本（户管 Task 5 记，属既有结构问题） |

### 3.5 **已由户管 Task 20 覆盖，不要重复做**

户管 Task 20（提交 `0cc21d0`，用户裁决 D23 / D24）已处理：`/api/video/*` 与 `/api/audio-replace/*` 共 16 条无鉴权端点的补口、`video_download` 与 `audio_replace_download` 的路径白名单、`/api/products/<int:pid>/detail` 的补口、58 个产品/视频/文案素材域端点对户管的 403 收口。**本任务不要重复处理。**

**但请注意 Task 20 的收口程度并非全封闭**（实现者自报、待最终裁定）：
- `/api/video/download`、`/api/audio-replace/download`、`/api/audio` 三条用的是 `@jwt_required(optional=True)` 而非 `@jwt_required()`。原因是调用方是 `window.open(...)` 与 `<audio src>`，**不携带 `Authorization` 头**（token 只存 localStorage，JWT 未配置 cookie 位置）；按字面加 `@jwt_required()` 会让所有角色的下载由 200 变 401。因此这三条**仍是「不带 token 也能调」**，其安全控制依赖路径白名单（精确匹配 `video_tasks.output_path` / `audio_replace_history.output_path`，未登记路径 404）与「带 token 的户管被 403」。
- **这条经验正是 4.2 的前车之鉴**：它证明了「直接补 `@jwt_required()`」对文件服务类端点不可行，本任务的 A 类实施必须采用 4.2 的第 3 条分支。

实施前先确认 Task 20 已合并（`git log --oneline` 查 `0cc21d0`）。

## 四、技术方案

### 4.1 总原则

1. **纯增量**：只收紧鉴权/校验，不改业务逻辑、不改既有响应形状、不改错误文案（`py/routes/decorators.py` 的既有文案保持原样）。
2. **单一事实来源**：角色集合一律用 `py/routes/helpers.py` 的 `CROSS_USER_ROLES` / `GLOBAL_OPTION_ROLES` / `PLATFORM_SWITCH_ROLES` / `HUGUAN_ROLE`，**不要新增字面量元组**。
3. **装饰器顺序**沿用仓库既有习惯：`@app.route` → `@jwt_required...` → 角色/平台装饰器 → `def`。
4. **逐条实测**：每加一道闸门，都要有测试**实测**目标角色被拒、对照角色不被拒（禁止只写「装饰器已存在」的静态断言）。

### 4.2 A 类做法：补 `@jwt_required()`——**但先解决一个真实的设计冲突**

**陷阱（必须先处理，否则会打断现有功能）**：下列调用方式**不会携带 `Authorization` 头**——浏览器的 `<img src>`、`<a href>`、`window.open()`、CSS `url()`、`<iframe>`。若这些端点的调用方是上述方式，直接补 `@jwt_required()` 会把它们**全部打成 401**：

- `/api/image`（`serve_image`）、`/api/fonts/file/<font_id>`、`/api/font-file`、`/api/fonts/preview` 很可能被 `<img>` / CSS 引用（字体文件尤其）；
- `/api/scrape/download`、`/api/video/download`（已由 Task 20 处理，可参考其结论）很可能被 `window.open` / `<a>` 触发（`frontend/src/views/VideoView.vue` 与 `MediaView.vue` 用的正是 `window.open('/api/video/download?path=...')`——**这正是 Task 20 必须同时做路径白名单的原因**）。

**因此 4.2 的实施步骤必须是**：
1. **先 grep 每个端点的全部调用点**（前端 + 后端内部 + 可能的外部调用），确认调用方式是否带 token；
2. 带 token 的（axios 等）→ 直接补 `@jwt_required()`；
3. 不带 token 的 → 二选一，**在实施计划里明确选定并说明理由**：
   - (a) 改造前端用带 token 的取回方式（`fetch` + `blob` 或 `Authorization` 头），再补 `@jwt_required()`；
   - (b) 保留端点匿名但对**入参做严格白名单**（例如文件类端点只允许命中数据库记录在案的路径——与 Task 20 对 `video_download` 采用的口径一致），并在文档里明确「这是有意保留的匿名端点」；
4. 每条都要有测试钉住「未登录 → 401」或「未登录 → 白名单外路径被拒」。

**`/api/translate`、`/api/google-sheets/status`、`/api/fonts/list`、`/api/fonts/preview`** 这几个是前端 axios 调用的可能性大，逐个确认即可。

### 4.3 B 类做法

- **B-1（GG 三个写端点）**：加 `owner_id` 归属校验，口径与户管 Task 18 的 `_cross_user_actor`（`py/main.py`，语义 = `role in CROSS_USER_ROLES`）**保持一致**——跨用户角色放行，其余角色只能操作自己的。注意 `accounts_batch_delete` 那类循环场景**把判定提到循环外**（`auth.get_user_by_id` 每次会新开数据库连接）。
- **B-2（`fb_pixels` 跨租户）**：把 `list_all_pixels` 的非跨用户分支改成与同文件其他列表一致的形状 —— **先读 `py/routes/fb_routes.py` 里 `list_bms` 等已有五处 `owner_filter` 的既有写法，照抄**，并把「必须有一条『必须被排除』的对照行」写进测试（只断言集合相等是假绿）。
- **B-3（`sales-persons/create`）**：先实测确认是否真能被普通 `user` 调用；是则按 §3.5 的口径把这一组接口统一到 `GLOBAL_OPTION_ROLES`；否则给设计文档 §3.5 写勘误。

### 4.4 C 类做法

统一「先校验、后使用」：入参为数字时用**严格 ASCII 数字**判定（例如 `str.isascii() and str.isdigit()`，或 `try: int(v) except` 后返回 400），并校验目标用户存在；非法入参一律 **400 + 明确中文文案**，不落 500。

### 4.5 交付物：全站鉴权矩阵表

产出一张 markdown 表（建议落在 `docs/superpowers/` 下），逐端点列出：

| 端点（方法 + 路径） | 是否需登录 | 允许的角色 | 有无归属校验 | 有无平台门禁 | 备注 |

**生成方式建议**：写一次性脚本扫描 `py/main.py` + `py/routes/*.py` 的 `@app.route` / `@bp.route` 及其装饰器栈（**只读、跑完即删**），人工核对成一版 baseline，避免靠记忆漏项——本次照出缺口靠的就是这种机械扫描。矩阵表本身也是本任务的主要验收物。

## 五、涉及的文件 / API

| 文件 | 改动 |
|---|---|
| `py/main.py` | A 类 13 条路由的装饰器；B-1 三处写校验；B-3 `sales-persons` 组；C-1 入参校验 |
| `py/routes/fb_routes.py` | B-2 `list_all_pixels` 的租户隔离 |
| `py/auth.py` | C-2 搜索 SQL |
| `py/routes/decorators.py` | 可能新增平台/角色装饰器（若沿用既有 `reject_huguan` / `require_platform` 模式即可，则**不改**） |
| 前端（可能） | 仅当 4.2 选择「改造调用方式」时才改对应组件；否则**不改前端** |
| `docs/superpowers/` | 鉴权矩阵表 + 设计文档 §3.5 勘误（若 B-3 判定为文档不准） |

## 六、数据结构

**无变更**：不新增表、不新增列、不改迁移。本任务只收紧既有端点的鉴权与入参校验。

## 七、UI 改动

**预计无**。唯一可能：若 4.2 选择改造前端取文件方式，则涉及对应组件（`<img>` → 带 token 的 fetch + blob URL）。这属实现细节，不是新 UI 设计。

## 八、测试要点

- **A 类**：每个端点各一条「未登录 → 401 或被白名单拒绝」+ 一条「带正常 token 的 `user` → 行为与改动前一致」的对照行。
- **B-1**：普通 `user` 改/转移/批量改**别人的** GG 账户 → 403 且**数据未变**（负面事实断言）；`user` 改自己的 → 仍成功。
- **B-2**：普通 `fb` 用户列表**不含**他人的像素（**必须有「必须被排除」的对照行**，只断集合相等是假绿）；developer 仍能跨用户。
- **B-3**：按实测结论定。
- **C 类**：非法 `owner_id`（Unicode 数字、不存在的用户、空串）→ **400**（不是 500）；developer 无 `platform` 时搜索 → 200。
- **回归（最高优先级）**：`developer` / `admin` / `user` / `viewer` 的**既有正常流程**不得因本次收紧而失效——尤其是 4.2 里那些「原本匿名可用」的端点，改造后必须逐个确认前端仍能正常取到资源。

## 九、风险与边界

1. **最大风险是 4.2**：把「原本任何人可调」改成「需要登录」，若漏改某个 `<img>` / `window.open` 调用点，表现为**图片/字体/下载静默失效**（浏览器控制台 401），而且后端测试全绿也发现不了。**必须在浏览器里逐个点一遍**。
2. **不做**：不重构、不统一命名、不动表结构、不改既有错误文案、不引入测试框架。
3. **`_guard_gg_platform` 本身是否有效**需在本任务中一并验证（★实测：它对未登录请求放行；但**它在 `before_request` 阶段调用 `get_jwt_identity()`，而 JWT 上下文是由路由上的 `@jwt_required()` 建立的**——这个时序是否让该钩子对已登录用户也不生效，**必须用一个真实的跨平台请求实测**，不能只靠读代码。若实测发现该钩子是死代码，那么「GG 专用路由对 FB 用户的平台隔离」是靠别处实现的，需一并查明并补测试）。
4. **服务监听 `0.0.0.0`**：若部署环境可从不可信网络访问，本任务的 A 类应视为**紧急**。这一条需要你来判断部署现实。

## 十、建议分批（每批独立可交付、独立可回滚）

| 批次 | 内容 | 理由 |
|---|---|---|
| 1 | A 类里「不带 token 也能被利用」的：`/api/google-ads/*`、文件读取类（含路径白名单） | 唯一不需要账号就能打的 |
| 2 | A 类其余（含 4.2 的调用方式改造） | 需要前端配合，风险集中在浏览器验证 |
| 3 | B 类（越权/跨租户） | 需要登录才能触发 |
| 4 | C 类 + D 类 + 鉴权矩阵表收尾 | 健壮性与清理 |

---

## 附：本分支任务审查累积的 Minor（**不属于本文件范围**）

户管需求各任务审查累积的低优先级条目（约 60 条，含回归网缺口、命名、文档措辞等）记在 `.superpowers/sdd/progress.md` 的「待办 Minor（final review triage，不阻塞）」小节。它们属**户管分支自身的代码质量**，与本文件的「既有缺口」不是一回事，**不要合并处理**；需要时另开一轮清理。

## 附：证据复核清单（实施第一步就该做）

- [ ] `git log --oneline` 确认户管 Task 20 已合并，3.5 的项不要重复做
- [ ] 用脚本重新扫描一遍无 `@jwt_required()` 的路由，与 3.1 的表逐条对齐（行号会漂移，按路径 + 函数名比对）
- [ ] 逐条实测 3.2 的 B-1 / B-3、3.3 的 C-1 / C-2，把「☆」升级为「★」或推翻
- [ ] 实测 3.4 的 D-1 / D-2 / D-3 是否仍然存在
- [ ] 实测 `_guard_gg_platform` 是否真的生效（见九-3）
