# 全站鉴权矩阵表（安全加固计划交付物 · Task 10）

- 生成日期：2026-09-24
- 覆盖范围：`main.app.url_map` 全部 **298** 条规则 = **297** 条应用路由 + Flask 内置 `static` 静态路由
- 路由分布：`main.py` 178 / `fb_routes.py` 49 / `tt_routes.py` 28 / `tt_accounts_routes.py` 26 / `auth_routes.py` 12 / `huguan_dashboard_routes.py` 4 / Flask `static` 1
- 基线来源：一次性只读扫描脚本（`py/tests/scan_routes_tmp.py`，**已删除**），方法 A（`inspect.getsourcelines` 修正版）与方法 B（独立 AST 解析）双向比对，297/298 一致（唯一例外是 Flask 内置 `static`，非应用端点）
- 本文件**不是**合规声明，是一份**带来源分级**的现状清单。使用前请先读 §1.2 与 §4。

> ⚠️ **一句话使用前提**：「归属校验」列标 `未核` 的行，**不得**默认其存在归属校验。本表中「无归属校验」是**读过函数体或实测**得出的结论，「未核」是**没读、不下断言** —— 两者的区别正是这份文档的价值所在。

## 1. 表头说明

### 1.1 各列口径

| 列 | 口径 |
|---|---|
| 端点（方法 + 路径） | 取自 `url_map.iter_rules()`，即 Flask 实际注册的规则；路径参数按注册原文（如 `<int:aid>`） |
| 是否需登录 | `需` = 有 `@jwt_required()`；`可选` = `@jwt_required(optional=True)`（**不带 token 也能进**）；`否` = 无任何 JWT 装饰器 |
| 允许的角色 | 能**通过装饰器层**到达函数体的角色集合的**上界**。函数体内若另有判定只会更严（更严只会缩小集合）⇒ 本列回答的是「谁可能到得了」，不是「谁最终成功」 |
| 有无归属校验 | 函数体内是否按 `owner_id` / `CROSS_USER_ROLES` / `can_modify` 等把操作对象限定到本人的行。`有` = 有；`无` = 读过函数体或实测确认没有；`未核` = **没读过，不做任何断言** |
| 有无平台门禁 | 是否限制请求者的 `platform`（fb/gg/tt）。全站唯一一个 GG 平台守卫 `_guard_gg_platform` 经实测**已失效**（见 §3.1），故 GG 业务路由本列一律为「无」 |
| 备注 | 前序 Task 的修复状态、已知缺口标记（`**§3.x**`）、以及该单元格结论的补充说明 |

### 1.2 来源等级（**本表的核心质量属性**）

| 标记 | 含义 |
|---|---|
| `[已核]` | 我**逐行读过**该端点的函数体，或对其做过运行时探测；该单元格的结论有代码/实测依据 |
| `[推断]` | **未读函数体**；结论由装饰器栈语义、或函数体符号的**机械扫描**（关键词命中，不区分「校验」还是「SELECT 列名」）推出 |
| `[未核]` | 无法判断，不下断言 |

- 标记**逐单元格**标注，不逐行 —— 同一行的不同单元格可以等级不同。
- **读一行时请只看它最弱的那个单元格**。若「归属校验」为 `未核`，该行整体就不能被当作「已验证有校验」。
- `[推断]` 级结论所依据的装饰器语义来自 `py/routes/decorators.py`（我已通读全文）：
  - `@jwt_required()` → 任意已登录用户
  - `@admin_required` → 仅 `developer` / `admin`
  - `@huguan_required` → 仅 `huguan`
  - `@no_huguan` → 拒 `huguan`，其余已登录用户放行
  - `@fb_required` / `@tt_required` → 该平台用户，或 `PLATFORM_SWITCH_ROLES = ("developer", "huguan")`（**`admin` 不是平台切换角色**，这点常被误判）
  - `@tt_write_required` → 同 `@tt_required`，再拒 `viewer`
  - 另需注意 `require_platform(platform)` **不是装饰器**，而是被上面几个平台装饰器在内部调用的**辅助函数**（返回错误响应或 `None`）

### 1.3 为什么「允许的角色」不能从路径名猜（勘误 (2) 的落地）

本表 `roles` 列：`[已核]` 行一律来自函数体；`[推断]` 行来自装饰器语义或体内符号机械扫描；**没有任何一行是从路径名猜的**。本项目真实的反例：

- 同为 `/api/admin/` 前缀：`/api/admin/data/export|import` 用 `@admin_required`（仅 developer/admin），而 `/api/admin/users*` 是在函数体内判 `role not in ("developer","admin","huguan")` —— **对 huguan 放行**。⇒ `/api/admin/` 这个路径名**推不出**角色，这正是勘误 (2) 的靶心。**本表在核查途中正是因为第一版机械扫描的关键词表里没有 `'huguan'` 而误判过这 8 行，靠逐条读函数体才发现并改正** —— 请对 `[推断]` 行保持同样的怀疑。
- `/api/platform/users`、`/api/statuses/list`、`/api/regions/list`、`/api/sales-persons/list` 只是 `@jwt_required()`，**任意登录用户**可读（含跨户枚举）。
- `/api/mcc/<int:mid>/detail` 路径上看像「按归属过滤的详情」，实际**没有任何归属过滤**（§3.5）。
- `/api/mcc-levels/*`、`/api/agents/*` 的 `PUT/DELETE` 体内是 `GLOBAL_OPTION_ROLES`（含 huguan），并非路径暗示的 admin 专属。

### 1.4 来源等级分布（本表的可读性摘要）


| 维度 | 计数 |
|---|---|
| 路由总数（行数） | 298 |
| 「允许的角色」= `[已核]`（读过函数体） | 62 |
| 「允许的角色」= `[推断]`（装饰器/机械扫描） | 236 |
| 「归属校验」= 有（读函数体/实测） | 58 |
| 「归属校验」= **无**（读函数体/实测，即缺口） | 29 |
| 「归属校验」= 未核 | 211 |
| 行级（「允许的角色」+「归属校验」两列的较弱者）`[已核]` | 61 |
| 行级（「允许的角色」+「归属校验」两列的较弱者）`[推断]` | 65 |
| 行级（「允许的角色」+「归属校验」两列的较弱者）`[未核]` | 172 |

## 2. 主表（逐端点，共 298 行 / 298 条规则）

### 2.1 无鉴权 / 静态资源 / 健康检查（10 条）

全站无需登录即可调用的端点（含 A 类 13 条的收口状态）

| 端点（方法 + 路径） | 是否需登录 | 允许的角色 | 有无归属校验 | 有无平台门禁 | 备注 |
|---|---|---|---|---|---|
| `GET /` | 否 | 匿名 [已核] | 不适用 | 不适用 | SPA 首页：send_from_directory(_FRONTEND_DIR, 'index.html') |
| `GET /<path:filename>` | 否 | 匿名 [已核] | 不适用 | 不适用 | Flask 内置静态路由（static_folder=frontend/dist、static_url_path=''）；非 API，路径约束由 Flask safe_join 提供 |
| `GET /api/audio` | 可选 | 匿名可用；带 token 时作用域=本人 [推断] | 未核 | 无（GG 专用守卫实际失效）[已核] | 同上；调用方是 <audio src>，不携带 token |
| `GET /api/audio-replace/download` | 可选 | 匿名可用；带 token 时作用域=本人 [推断] | 未核 | 无（GG 专用守卫实际失效）[已核] | 同上；audio_replace_history.output_path 白名单 |
| `GET /api/font-file` | 否 | 匿名（字体扩展名白名单）[已核] | 不适用 | 不适用 | A 类 13 条之一；Task 1 判定为「有意保留匿名」，控制 = 扩展名白名单 + realpath 目录包含 |
| `GET /api/health` | 否 | 匿名 [已核] | 不适用 | 不适用 | 固定返回 {"status":"ok"}，无信息量 |
| `GET /api/image` | 否 | 匿名（图片扩展名白名单）[已核] | 不适用 | 不适用 | A 类 13 条之一；同上，serve_image |
| `GET /api/scrape/download` | 可选 | 匿名可用；带 token 时作用域=本人 [推断] | 未核 | 无（GG 专用守卫实际失效）[已核] | A 类 13 条之一，Task 1 补的 optional；Task 20 同族结论：文件类端点按字面加 @jwt_required() 会让前端下载 401 |
| `GET /api/video/download` | 可选 | 匿名可用；带 token 时作用域=本人 [推断] | 未核 | 无（GG 专用守卫实际失效）[已核] | Task 20 有意保留 optional（调用方 window.open 不带 Authorization 头）；控制依赖 video_tasks.output_path 精确白名单 |
| `GET /favicon.ico` | 否 | 匿名 [已核] | 不适用 | 不适用 | 恒返回 ('', 204)，无 body |

### 2.2 认证域 /api/auth/*（13 条）

登录、注册、本人资料读写

| 端点（方法 + 路径） | 是否需登录 | 允许的角色 | 有无归属校验 | 有无平台门禁 | 备注 |
|---|---|---|---|---|---|
| `GET /api/auth/custom-name` | 需 | 本人 [已核] | 不适用 | 不适用 | 按 identity 读 users.custom_name |
| `PUT /api/auth/custom-name` | 需 | 本人 [已核] | 不适用 | 不适用 | 按 identity 写 users.custom_name |
| `GET /api/auth/email` | 需 | 本人 [已核] | 不适用 | 不适用 | 按 identity 读 users.email |
| `PUT /api/auth/email` | 需 | 本人 [已核] | 不适用 | 不适用 | 按 identity 写 users.email |
| `POST /api/auth/login` | 否 | 匿名 [已核] | 不适用 | 不适用 | 登录入口；auth.login_user(username, password) |
| `GET /api/auth/me` | 需 | 本人（identity 为唯一键，无入参）[已核] | 不适用 | 不适用 | auth.get_user_by_id(identity) |
| `GET /api/auth/names` | 可选 | 匿名可读；非 developer 看不到 developer 角色用户 [已核] | 不适用 | 不适用 | 返回「在 products 表有 owner/runner 数据」的用户 id/username/display_name ⇒ 匿名即可枚举用户名；前端 runner 选择器有意如此 |
| `PUT /api/auth/password` | 需 | 本人（且必须先校验旧密码）[已核] | 不适用 | 不适用 | auth.update_password(identity, new)；旧密码错误 → 400 |
| `PUT /api/auth/profile` | 需 | 本人 [已核] | 不适用 | 不适用 | 只允许改自己的 display_name（username 传 None） |
| `POST /api/auth/refresh` | 需 | 持 refresh token 的用户本人 [已核] | 不适用 | 不适用 | create_access_token(identity=同一 subject)，无法代他人换取 |
| `POST /api/auth/register` | 否 | 匿名 [已核] | 不适用 | 不适用 | 自助注册入口（用户名 4-20、密码 ≥6）；是否应开放给公网属产品决策 |
| `PUT /api/auth/telegram-username` | 需 | 本人 [已核] | 不适用 | 不适用 | 按 identity 写 users.telegram_username |
| `GET /api/users/names` | 可选 | 匿名可读（optional）；**无 developer 过滤**（与 /api/auth/names 不同）[已核] | 不适用 | 无 [已核] | **已核观察（§3.8）**：匿名即可枚举「有产品的用户」的 id/username/display_name 且**含 developer**；与带过滤的 /api/auth/names 口径不一致 |

### 2.3 GG 账号域 /api/accounts/*（17 条）

GG 账户主表；B-1 三处写端点的归属校验在此

| 端点（方法 + 路径） | 是否需登录 | 允许的角色 | 有无归属校验 | 有无平台门禁 | 备注 |
|---|---|---|---|---|---|
| `DELETE /api/accounts/<int:aid>` | 需 | 同上 [已核] | 有 [已核] | 无（GG 专用守卫实际失效）[已核] | Task 9 D-1/D-2：清理死缓存 delete、batch-delete 返回真实删除条数 |
| `PUT /api/accounts/<int:aid>` | 需 | 任意已登录；跨用户需 role ∈ CROSS_USER_ROLES(developer/admin/huguan)，否则仅 owner_id=本人 [已核] | 有 [已核] | 无（GG 专用守卫实际失效）[已核] | B-1 项，Task 7 已修（含修复轮 2 补的 int64 上界与同族 aid 向量） |
| `GET /api/accounts/<int:aid>/mcc-history` | 需 | 任意已登录用户 [推断] | 未核 | 无（GG 专用守卫实际失效）[已核] | I-2 路径参数（见 §3.2） |
| `DELETE /api/accounts/<int:aid>/mcc-history/<int:hid>` | 需 | 体内出现 CROSS_USER_ROLES/role（机械扫描）[推断] | 未核 | 无（GG 专用守卫实际失效）[已核] | 两个路径参数，I-2 覆盖（见 §3.2） |
| `DELETE /api/accounts/<int:aid>/permanent` | 需 | 任意已登录用户 [推断] | 未核 | 无（GG 专用守卫实际失效）[已核] | 体内出现 owner_id/_cross_user_actor（机械扫描，未逐行核）；I-2 超大整数路径参数（见 §3.2） |
| `PUT /api/accounts/<int:aid>/reassign` | 需 | 任意已登录（跨用户转移由入参 owner_id 决定；写前校验目标用户存在）[已核] | 有 [已核] | 无（GG 专用守卫实际失效）[已核] | **本任务对照验证的基准端点**：@app.route + @jwt_required()，无其它守卫；Task 7 修复轮 2 补 int64 上界 + ASCII 契约守护 |
| `GET /api/accounts/<int:aid>/recharge-records` | 需 | 任意已登录用户 [推断] | 未核 | 无（GG 专用守卫实际失效）[已核] | I-2 路径参数（见 §3.2） |
| `POST /api/accounts/<int:aid>/restore` | 需 | 任意已登录用户 [推断] | 未核 | 无（GG 专用守卫实际失效）[已核] | 同 permanent；I-2 路径参数（见 §3.2） |
| `POST /api/accounts/batch-create` | 需 | 任意已登录用户 [推断] | 未核 | 无（GG 专用守卫实际失效）[已核] |  |
| `POST /api/accounts/batch-delete` | 需 | 任意已登录；跨用户放行条件同 CROSS_USER_ROLES [已核] | 有 [已核] | 无（GG 专用守卫实际失效）[已核] | B-1 同族；判定提到循环外；D-2 谎报计数已修 |
| `POST /api/accounts/batch-lookup` | 需 | 任意已登录用户 [推断] | **无 [已核]** | 无（GG 专用守卫实际失效）[已核] | **新发现跨户读（§3.5）**：`WHERE a.account_id IN (...)` 无 owner 条件，单次可批量探明多户归属 |
| `POST /api/accounts/batch-update` | 需 | 同上 [已核] | 有 [已核] | 无（GG 专用守卫实际失效）[已核] | B-1 项，Task 7 已修 |
| `POST /api/accounts/create` | 需 | 任意已登录；体内出现 CROSS_USER_ROLES（机械扫描）[推断] | 未核 | 无（GG 专用守卫实际失效）[已核] | C-1b 已核结论：非法 owner_id 走 409（或静默错归属），**不会** 500 |
| `GET /api/accounts/deleted` | 需 | 任意已登录用户 [推断] | 未核 | 无（GG 专用守卫实际失效）[已核] |  |
| `GET /api/accounts/list` | 需 | 任意已登录；CROSS_USER_ROLES 可跨用户可见，否则仅本人 [推断] | 未核 | 无（GG 专用守卫实际失效）[已核] | 体内出现 CROSS_USER_ROLES/owner_id（机械扫描，未逐行核） |
| `GET /api/accounts/lookup` | 需 | 任意已登录用户 [推断] | **无 [已核]** | 无（GG 专用守卫实际失效）[已核] | **新发现跨户读（§3.5）**：`WHERE a.account_id=? AND a.deleted_at IS NULL`，无 owner 条件，回传 name/account_id/timezone/MCC/**owner_id/owner_name**/状态 ⇒ 任意登录用户可按 account_id 探明他人账户归属 |
| `POST /api/accounts/sync-from-sheet` | 需 | 任意已登录用户 [推断] | 未核 | 无（GG 专用守卫实际失效）[已核] | 从表格同步账户；**是否限定本人范围未核** |

### 2.4 GG MCC 与字典选项域（29 条）

MCC、MCC 层级、地区、状态、商务人员、代理、平台用户

| 端点（方法 + 路径） | 是否需登录 | 允许的角色 | 有无归属校验 | 有无平台门禁 | 备注 |
|---|---|---|---|---|---|
| `DELETE /api/agents/<int:aid>` | 需 | developer / admin / huguan（GLOBAL_OPTION_ROLES）[推断] | 未核 | 无（GG 专用守卫实际失效）[已核] | B-4 项，Task 5 已修 |
| `PUT /api/agents/<int:aid>` | 需 | developer / admin / huguan（GLOBAL_OPTION_ROLES，体内常量）[推断] | 未核 | 无（GG 专用守卫实际失效）[已核] | B-4 项：Task 5 已修 TT 分支完全不校验 owner_id 的绕过 |
| `POST /api/agents/create` | 需 | 任意已登录 [已核] | 不适用 [已核] | 无（GG 专用守卫实际失效）[已核] | platform=tt 分支插入全平台共享名（唯一性也按平台），非 tt 分支 owner_id=本人 |
| `GET /api/agents/list` | 需 | 任意已登录 [已核] | 有（platform!=tt 按 owner_id；platform=tt 全平台共享）[已核] | 无（GG 专用守卫实际失效）[已核] | platform=tt 分支无 owner 过滤（B-4 同族，但列表本身无写风险） |
| `DELETE /api/mcc-levels/<int:lid>` | 需 | 同上 [推断] | 未核 | 无（GG 专用守卫实际失效）[已核] | I-2 路径参数（见 §3.2） |
| `PUT /api/mcc-levels/<int:lid>` | 需 | developer/admin/huguan（GLOBAL_OPTION_ROLES，机械扫描）[推断] | 未核 | 无（GG 专用守卫实际失效）[已核] | I-2 路径参数（见 §3.2） |
| `POST /api/mcc-levels/create` | 需 | 任意已登录用户 [推断] | 不适用（owner_id=本人）[已核] | 无（GG 专用守卫实际失效）[已核] | 唯一性按 (name, owner_id) |
| `GET /api/mcc-levels/list` | 需 | 任意已登录，只返回本人 [已核] | 有 [已核] | 无（GG 专用守卫实际失效）[已核] | SQL owner_id=? |
| `DELETE /api/mcc/<int:mid>` | 需 | 同上 [已核] | 有 [已核] | 无（GG 专用守卫实际失效）[已核] | 同族 mid 上界校验（Task 7） |
| `PUT /api/mcc/<int:mid>` | 需 | 任意已登录；跨用户需 _cross_user_actor [已核] | 有 [已核] | 无（GG 专用守卫实际失效）[已核] | Task 7 已核（同族 mid/aid 上界校验） |
| `GET /api/mcc/<int:mid>/detail` | 需 | 任意已登录用户 [推断] | **无 [已核]** | 无（GG 专用守卫实际失效）[已核] | **新发现同族缺口（§3.5）**：只校验 MCC 存在，随后返回该 MCC 完整树（直属+子 MCC、账户名/account_id/状态、关联产品），无 owner/shared 过滤 |
| `POST /api/mcc/<int:mid>/link` | 需 | 任意已登录用户 [推断] | **无 [已核]** | 无（GG 专用守卫实际失效）[已核] | **新发现同族缺口（§3.5）**：只校验 MCC 存在，随即 _link_mcc_chain_to_user(db, mid, uid) —— 任意登录用户可把他人的 MCC（含上级链）关联到自己名下 |
| `POST /api/mcc/batch-delete` | 需 | 任意已登录；跨用户需 _cross_user_actor 非空 [已核] | 有 [已核] | 无（GG 专用守卫实际失效）[已核] | 循环内逐条 owner_id 判定，非本人只跳过并记 skipped |
| `POST /api/mcc/create` | 需 | 任意已登录用户 [推断] | 不适用（新建，owner_id=本人）[已核] | 无（GG 专用守卫实际失效）[已核] | **已核观察（§3.8）**：mcc_id 已属他人时响应带 owner_name（users.display_name/username）⇒ 可探测任意 mcc_id 的归属人 |
| `GET /api/mcc/list` | 需 | 任意已登录；CROSS_USER_ROLES 可跨用户 [推断] | 未核 | 无（GG 专用守卫实际失效）[已核] | 体内出现 CROSS_USER_ROLES/owner_id（机械扫描） |
| `GET /api/mcc/options` | 需 | 任意已登录，但只返回本人 owner 或被 shared 的 MCC [已核] | 有 [已核] | 无（GG 专用守卫实际失效）[已核] | SQL 条件：owner_id=? OR shared_user_ids=? OR shared_user_ids LIKE ... |
| `GET /api/platform/users` | 需 | 任意已登录 [已核] | 不适用（列表接口，按平台过滤）[已核] | 无（GG 专用守卫实际失效）[已核] | 返回「在该平台有未删除账户」的用户的 id/username/display_name ⇒ 跨户枚举用户名（有意设计，供归属人筛选下拉） |
| `DELETE /api/regions/<int:region_id>` | 需 | developer/admin/huguan [已核] | 不适用 [已核] | 无（GG 专用守卫实际失效）[已核] | B-5 项，Task 6 已收紧 |
| `PUT /api/regions/<int:region_id>` | 需 | developer/admin/huguan [已核] | 不适用 [已核] | 无（GG 专用守卫实际失效）[已核] | B-5 项，Task 6 已收紧 |
| `POST /api/regions/create` | 需 | developer/admin/huguan（GLOBAL_OPTION_ROLES）[已核] | 不适用 [已核] | 无（GG 专用守卫实际失效）[已核] | B-5 项，Task 6 已收紧；前端同步隐藏普通用户新增入口 |
| `GET /api/regions/list` | 需 | 任意已登录；按 platform 全量 [已核] | 不适用（regions 是全局表，无 owner_id 列）[已核] | 无（GG 专用守卫实际失效）[已核] |  |
| `DELETE /api/sales-persons/<int:sid>` | 需 | developer/admin/huguan [推断] | 未核 | 无（GG 专用守卫实际失效）[已核] | 同上；I-2 路径参数 |
| `PUT /api/sales-persons/<int:sid>` | 需 | developer/admin/huguan [推断] | 未核 | 无（GG 专用守卫实际失效）[已核] | 与 B-5 同批收紧到 GLOBAL_OPTION_ROLES；I-2 路径参数 |
| `POST /api/sales-persons/create` | 需 | 任意已登录用户 [推断] | 不适用（owner_id=本人）[推断] | 无（GG 专用守卫实际失效）[已核] | **B-3 已裁决（2026-09-23）：属产品功能，有意保留，不是缺口** |
| `GET /api/sales-persons/list` | 需 | 任意已登录；按 platform 全量（**不按 owner**）[已核] | 不适用 [已核] | 无（GG 专用守卫实际失效）[已核] | 同平台任意用户可见全部商务人员姓名（跨户可见，低危） |
| `DELETE /api/statuses/<int:sid>` | 需 | developer/admin/huguan [推断] | 未核 | 无（GG 专用守卫实际失效）[已核] | I-2 路径参数（见 §3.2） |
| `PUT /api/statuses/<int:sid>` | 需 | developer/admin/huguan [推断] | 未核 | 无（GG 专用守卫实际失效）[已核] | I-2 路径参数（见 §3.2） |
| `POST /api/statuses/create` | 需 | 任意已登录用户 [推断] | 不适用 [推断] | 无（GG 专用守卫实际失效）[已核] |  |
| `GET /api/statuses/list` | 需 | 任意已登录；按 platform 全量 [已核] | 不适用（全局字典表，按平台）[已核] | 无（GG 专用守卫实际失效）[已核] |  |

### 2.5 GG 管理 / 配置 / 运维域（36 条）

/api/admin/*、数据导入导出、AI 配置、设置、审计日志、字体、文件浏览

| 端点（方法 + 路径） | 是否需登录 | 允许的角色 | 有无归属校验 | 有无平台门禁 | 备注 |
|---|---|---|---|---|---|
| `GET /api/admin/data/export/<int:uid>` | 需（由 @admin_required 自校验 JWT，未挂 @jwt_required）[已核] | 仅 developer/admin [已核] | 有（_can_access_user_data(actor, target) → 403）[已核] | 不适用 | 越权目标数据导出被 403 挡住 |
| `POST /api/admin/data/import` | 需（同上）[已核] | 仅 developer/admin [已核] | 有（_can_access_user_data）[已核] | 不适用 | 越权目标数据导入被 403 挡住 |
| `POST /api/admin/trigger-delist-check` | 需 | 体内仅出现 "developer"（机械扫描）⇒ 推断仅 developer [推断] | 未核 | 不适用 |  |
| `POST /api/admin/trigger-weekly-cleanup` | 需 | 仅 developer [推断] | 未核 | 不适用 |  |
| `GET /api/admin/users` | 需 | developer / admin / **huguan**（体内白名单 `role not in ('developer','admin','huguan')`）[已核] | 有（huguan 被 role_filter 限定为只看 huguan；[已核]） | 不适用 | **勘误 (2) 的靶心**：路径是 /api/admin/ 但**对 huguan 放行**；机械扫描若不把 'huguan' 列入关键词就会漏判 |
| `DELETE /api/admin/users/<int:uid>` | 需 | developer / admin / huguan [已核] | 有（_check_modify_user；uid==self 阻断）[已核] | 不适用 | I-2 路径参数 |
| `PUT /api/admin/users/<int:uid>` | 需 | developer / admin / huguan [已核] | 有（_check_modify_user + developer 目标保护）[已核] | 不适用 | I-2 路径参数 |
| `PUT /api/admin/users/<int:uid>/password` | 需 | developer / admin / huguan [已核] | 有（_check_modify_user + developer 目标保护）[已核] | 不适用 | 重置他人密码；I-2 路径参数 |
| `POST /api/admin/users/<int:uid>/role` | 需 | developer / admin / huguan [已核] | 有（_check_modify_user；uid==self 阻断）[已核] | 不适用 | 改角色；I-2 路径参数 |
| `PUT /api/admin/users/<int:uid>/telegram-username` | 需 | developer / admin / huguan [已核] | 有（_check_modify_user）[已核] | 不适用 | I-2 路径参数 |
| `POST /api/admin/users/<int:uid>/toggle` | 需 | developer / admin / huguan [已核] | 有（_check_modify_user；uid==self 阻断）[已核] | 不适用 | 启停用户；I-2 路径参数 |
| `POST /api/admin/users/create` | 需 | developer / admin / huguan [已核] | 不适用（新建；huguan 创建时 role 被 _huguan_allowed_roles 强制）[已核] | 不适用 | 同上；huguan 建号时请求体的 role 被强制改写 |
| `GET /api/audit-log/list` | 需 | 任意已登录（非 huguan）[已核] | 未核 | 无 [已核] | 可见范围未核（是否按 actor 过滤） |
| `POST /api/audit-log/restore/<int:log_id>` | 需 | 仅 developer（体内 `role != "developer"` 字面量）[推断] | 未核 | 无 [已核] | 回滚操作；I-2 路径参数 |
| `POST /api/browse-file` | 可选 | 匿名可用；带 token 时作用域=本人 [推断] | 未核 | 无 [已核] | **待核**：optional ⇒ 不带 token 也能调；文件浏览类接口的控制逻辑未读 |
| `POST /api/browse-folder` | 可选 | 匿名可用；带 token 时作用域=本人 [推断] | 未核 | 无 [已核] | 同上 |
| `POST /api/browse-save` | 可选 | 匿名可用；带 token 时作用域=本人 [推断] | 未核 | 无 [已核] | 同上；**写**本地文件系统 |
| `GET /api/config/ai` | 需 | 任意已登录，仅本人 ai_analysis_{uid} [已核] | 有（按 identity 分键）[已核] | 无 [已核] |  |
| `POST /api/config/ai` | 需 | 任意已登录用户 [推断] | 未核 | 无 [已核] |  |
| `GET /api/config/google-sheets` | 需 | 任意已登录用户 [推断] | 未核 | 无 [已核] |  |
| `POST /api/config/google-sheets` | 需 | 任意已登录用户 [推断] | 未核 | 无 [已核] |  |
| `GET /api/data/export` | 需 | 体内出现 get_user_by_id（机械扫描）[推断] | 未核 | 无 [已核] | 数据导出；与 /api/admin/data/export 是否同口径未核 |
| `POST /api/data/import` | 需 | 任意已登录用户 [推断] | 未核 | 无 [已核] |  |
| `GET /api/data/import-history` | 需 | 任意已登录用户 [推断] | 未核 | 无 [已核] |  |
| `POST /api/delist/dismiss` | 需 | 任意已登录用户 [推断] | 未核 | 无 [已核] |  |
| `GET /api/delist/pending` | 需 | 任意已登录用户 [推断] | 未核 | 无 [已核] |  |
| `GET /api/fonts/file/<font_id>` | 需 | 任意已登录用户 [推断] | 未核 | 无 [已核] | A 类 13 条之一，Task 1 已补（字符串路径参数，不属 I-2 的 <int:> 族） |
| `POST /api/fonts/import` | 需 | 任意已登录用户 [推断] | 未核 | 无 [已核] | A 类 13 条之一，Task 1 已补 |
| `GET /api/fonts/list` | 需 | 任意已登录用户 [推断] | 未核 | 无 [已核] | A 类 13 条之一，Task 1 已补 @jwt_required() |
| `POST /api/fonts/mark-used` | 需 | 任意已登录用户 [推断] | 未核 | 无 [已核] | A 类 13 条之一，Task 1 已补 |
| `GET /api/fonts/preview` | 需 | 任意已登录用户 [推断] | 未核 | 无 [已核] | A 类 13 条之一，Task 1 已补 |
| `POST /api/fonts/upload` | 需 | 任意已登录用户 [推断] | 未核 | 无 [已核] | A 类 13 条之一，Task 1 已补 |
| `GET /api/settings/account` | 可选 | 匿名可读（装饰器为 optional）；读到的内容范围未核 [推断] | 未核 | 无 [已核] | **待核**：optional 意味着不带 token 也能调，而该接口读的是全局 tags（充值表 ID / 表格映射） |
| `POST /api/settings/account` | 需 | 任意已登录；只有 sheet_mappings 的全局写入被体内 is_admin(developer/admin) 挡，recharge_sheet_id 的全局写入**无角色门禁** [已核] | 不适用 [已核] | 无 [已核] | **已核观察（§3.8）**：recharge_sheet_id 落入全局 tags，任意登录用户可改 |
| `GET /api/tasks` | 需 | 非 huguan [推断] | 未核 | 无 [已核] |  |
| `POST /api/translate` | 需 | 任意已登录用户 [推断] | 未核 | 无 [已核] | A 类 13 条之一，Task 1 已补 @jwt_required() |

### 2.6 GG 广告报告与外部同步域（24 条）

做表数据、Google Sheets / Google Ads 同步

| 端点（方法 + 路径） | 是否需登录 | 允许的角色 | 有无归属校验 | 有无平台门禁 | 备注 |
|---|---|---|---|---|---|
| `DELETE /api/ad-reports/<int:report_id>` | 需 | 任意已登录，但只作用于本人的行 [已核] | 有 [已核] | 无（GG 专用守卫实际失效）[已核] | `DELETE ... WHERE id=? AND user_id=?`；I-2 路径参数 |
| `PUT /api/ad-reports/<int:report_id>` | 需 | 任意已登录，但只作用于本人的行 [已核] | 有 [已核] | 无（GG 专用守卫实际失效）[已核] | 先 `SELECT id FROM ad_reports WHERE id=? AND user_id=?`，不匹配 → 404『记录不存在或无权操作』 |
| `POST /api/ad-reports/analyze` | 需 | 体内出现 role（机械扫描）[推断] | 未核 | 无（GG 专用守卫实际失效）[已核] |  |
| `POST /api/ad-reports/batch-delete` | 需 | 任意已登录，但只删除本人的行 [已核] | 有 [已核] | 无（GG 专用守卫实际失效）[已核] | `DELETE ... WHERE id IN (...) AND user_id=?`，返回真实 rowcount |
| `POST /api/ad-reports/check-duplicates` | 需 | 任意已登录用户 [推断] | 未核 | 无（GG 专用守卫实际失效）[已核] |  |
| `GET /api/ad-reports/compare` | 需 | 任意已登录用户 [推断] | 未核 | 无（GG 专用守卫实际失效）[已核] |  |
| `GET /api/ad-reports/cross-user` | 需 | 任意已登录用户 [推断] | 未核 | 无（GG 专用守卫实际失效）[已核] | **待核**：名字暗示跨用户聚合，作用域条件未读 |
| `GET /api/ad-reports/dashboard` | 需 | 任意已登录用户 [推断] | 未核 | 无（GG 专用守卫实际失效）[已核] |  |
| `GET /api/ad-reports/dates` | 需 | 任意已登录用户 [推断] | 未核 | 无（GG 专用守卫实际失效）[已核] | 设计文档 §3.1 已明确：已挂 @jwt_required 且按用户隔离，**不属于** A 类 |
| `GET /api/ad-reports/export` | 需 | 任意已登录用户 [推断] | 未核 | 无（GG 专用守卫实际失效）[已核] |  |
| `GET /api/ad-reports/list` | 需 | 任意已登录用户 [推断] | 未核 | 无（GG 专用守卫实际失效）[已核] |  |
| `POST /api/ad-reports/multi-ai-chat` | 需 | 体内出现 role（机械扫描）[推断] | 未核 | 无（GG 专用守卫实际失效）[已核] |  |
| `GET /api/ad-reports/multi-analysis` | 需 | 任意已登录用户 [推断] | 未核 | 无（GG 专用守卫实际失效）[已核] |  |
| `POST /api/ad-reports/multi-analysis` | 需 | 任意已登录用户 [推断] | 未核 | 无（GG 专用守卫实际失效）[已核] |  |
| `GET /api/ad-reports/products` | 需 | 任意已登录用户 [推断] | 未核 | 无（GG 专用守卫实际失效）[已核] |  |
| `POST /api/ad-reports/save` | 需 | 任意已登录用户 [推断] | 未核 | 无（GG 专用守卫实际失效）[已核] | **I-3 旁路写入口**：经 _auto_link_mcc_and_accounts → `INSERT OR IGNORE INTO regions(name, timezone)`（py/main.py:8738）绕过 regions 的 GLOBAL_OPTION_ROLES 门禁 |
| `GET /api/ad-reports/trends` | 需 | 任意已登录用户 [推断] | 未核 | 无（GG 专用守卫实际失效）[已核] |  |
| `POST /api/google-ads/accounts` | 需 | 任意已登录用户 [推断] | 未核 | 无 [已核] | A 类 13 条之一（设计文档列为「最高」严重度），Task 1 已补 @jwt_required() |
| `POST /api/google-ads/report` | 需 | 任意已登录用户 [推断] | 未核 | 无 [已核] | A 类 13 条之一（最高严重度），Task 1 已补 |
| `POST /api/google-sheets/retry-sync` | 需 | 任意已登录用户 [推断] | 未核 | 无 [已核] |  |
| `GET /api/google-sheets/sheets` | 需 | 任意已登录用户 [推断] | 未核 | 无 [已核] |  |
| `GET /api/google-sheets/status` | 需 | 任意已登录用户 [推断] | 未核 | 无 [已核] | A 类 13 条之一，Task 1 已补 @jwt_required() |
| `GET /api/google-sheets/sync-status` | 需 | 任意已登录用户 [推断] | 未核 | 无 [已核] |  |
| `POST /api/google-sheets/update-zuobiao` | 需 | 任意已登录用户 [推断] | 未核 | 无（GG 专用守卫实际失效）[已核] | **I-3 旁路写入口**：同上，调用点 py/main.py:6837 |

### 2.7 GG 产品 / 素材 / 视频域（62 条）

产品、YouTube、文案、视频、音频、充值、爬取

| 端点（方法 + 路径） | 是否需登录 | 允许的角色 | 有无归属校验 | 有无平台门禁 | 备注 |
|---|---|---|---|---|---|
| `POST /api/audio-replace` | 需 | 非 huguan [推断] | 未核 | 无（GG 专用守卫实际失效）[已核] | Task 20 已收口；未读函数体 |
| `DELETE /api/audio-replace/history` | 需 | 非 huguan [推断] | 未核 | 无（GG 专用守卫实际失效）[已核] | 未读函数体 |
| `GET /api/audio-replace/history` | 需 | 非 huguan [推断] | 未核 | 无（GG 专用守卫实际失效）[已核] | 未读函数体 |
| `DELETE /api/audio-replace/history/<int:hid>` | 需 | 非 huguan [推断] | 未核 | 无（GG 专用守卫实际失效）[已核] | 未读函数体 |
| `POST /api/copywriting/batch-edit` | 需 | 非 huguan；体内出现 'developer'/'admin' 分支（机械扫描）[推断] | 未核 | 无 [已核] | 未读函数体 |
| `POST /api/copywriting/delete` | 需 | 非 huguan；体内出现 'developer'/'admin' 分支（机械扫描）[推断] | 未核 | 无 [已核] | 未读函数体 |
| `POST /api/copywriting/edit` | 需 | 非 huguan；体内 can_modify [已核] | 有（can_modify）[已核] | 无（GG 专用守卫实际失效）[已核] |  |
| `POST /api/copywriting/import` | 需 | 非 huguan；体内出现 owner_id/is_public（机械扫描）[推断] | 未核 | 无 [已核] | 未读函数体 |
| `GET /api/copywriting/list` | 需 | 非 huguan；体内 scope_where [推断] | 未核 | 无（GG 专用守卫实际失效）[已核] |  |
| `DELETE /api/products/<int:pid>` | 需 | 同上 [已核] | **无 [已核]** | 无（GG 专用守卫实际失效）[已核] | **待裁决疑点（§3.9）**：同 PUT；I-2 路径参数 |
| `PUT /api/products/<int:pid>` | 需 | 任意已登录（非 huguan；viewer 被 _reject_viewer 拒）[已核] | **无 [已核]** | 无（GG 专用守卫实际失效）[已核] | **待裁决疑点（§3.9）**：只有 _reject_viewer，无 owner/runner 判定。GG 产品是否为团队共享资源未定 ⇒ 不列为确认缺口，I-2 路径参数 |
| `GET /api/products/<int:pid>/assets` | 需 | 非 huguan [推断] | 未核 | 无（GG 专用守卫实际失效）[已核] |  |
| `POST /api/products/<int:pid>/assets` | 需 | 非 huguan；viewer 被拒 [推断] | 未核 | 无（GG 专用守卫实际失效）[已核] |  |
| `DELETE /api/products/<int:pid>/assets/<video_id>` | 需 | 非 huguan；viewer 被拒 [推断] | 未核 | 无（GG 专用守卫实际失效）[已核] |  |
| `POST /api/products/<int:pid>/check-delist` | 需 | 非 huguan；viewer 被拒 [推断] | 未核 | 无（GG 专用守卫实际失效）[已核] |  |
| `GET /api/products/<int:pid>/detail` | 需 | 任意已登录（非 huguan）[已核] | **无 [已核]** | 无（GG 专用守卫实际失效）[已核] | **待裁决疑点（§3.9）**：Task 20 已补 @jwt_required()，但体内无 owner/runner 条件 —— 与 `/api/products/list`（按 product_runners 作用域）**读侧口径不一致** |
| `POST /api/products/<int:pid>/packages` | 需 | 非 huguan；viewer 被拒 [推断] | 未核 | 无（GG 专用守卫实际失效）[已核] |  |
| `POST /api/products/<int:pid>/restore` | 需 | 非 huguan；viewer 被拒 [推断] | 未核 | 无（GG 专用守卫实际失效）[已核] |  |
| `PUT /api/products/<int:pid>/runners` | 需 | 非 huguan；viewer 被拒 [推断] | 未核 | 无（GG 专用守卫实际失效）[已核] | **待核**：改 runner 列表即改可见范围 |
| `POST /api/products/create` | 可选 | 匿名可建（optional）+ 非 huguan；viewer 被拒 [推断] | 未核 | 无（GG 专用守卫实际失效）[已核] | 体内出现 owner_id/reject_viewer（机械扫描） |
| `GET /api/products/delist-status` | 需 | 非 huguan [推断] | 未核 | 无（GG 专用守卫实际失效）[已核] |  |
| `POST /api/products/import-text` | 需 | 非 huguan；viewer 被拒 [推断] | 未核 | 无（GG 专用守卫实际失效）[已核] |  |
| `GET /api/products/list` | 可选 | 匿名可读（optional）；体内按 runner 作用域，viewer 被强制 runner=all [已核] | 有（product_runners 作用域）[已核] | 无（GG 专用守卫实际失效）[已核] | **待裁决疑点（§3.9）**：runner=all 可越过本人作用域 |
| `POST /api/products/merge` | 需 | 非 huguan；viewer 被拒 [推断] | 未核 | 无（GG 专用守卫实际失效）[已核] |  |
| `DELETE /api/products/packages/<int:pkg_id>` | 需 | 非 huguan；viewer 被拒 [推断] | 未核 | 无（GG 专用守卫实际失效）[已核] |  |
| `PUT /api/products/packages/<int:pkg_id>` | 需 | 非 huguan；viewer 被拒 [推断] | 未核 | 无（GG 专用守卫实际失效）[已核] |  |
| `POST /api/products/packages/batch-delete` | 需 | 非 huguan；viewer 被拒 [推断] | 未核 | 无（GG 专用守卫实际失效）[已核] |  |
| `GET /api/products/runner-products` | 需 | 非 huguan [推断] | 未核 | 无（GG 专用守卫实际失效）[已核] |  |
| `DELETE /api/recharge/<int:rid>` | 需 | 任意已登录；体内出现 owner_id（机械扫描）[推断] | 未核 | 无 [已核] | 未读函数体；I-2 路径参数 |
| `PUT /api/recharge/<int:rid>` | 需 | 任意已登录；体内出现 owner_id（机械扫描）[推断] | 未核 | 无 [已核] | 未读函数体；I-2 路径参数 |
| `POST /api/recharge/<int:rid>/retry-sheets` | 需 | 任意已登录用户 [推断] | 未核 | 无 [已核] | 未读函数体；I-2 路径参数 |
| `POST /api/recharge/batch-submit` | 需 | 任意已登录；体内出现 owner_id（机械扫描）[推断] | 未核 | 无 [已核] | 未读函数体 |
| `POST /api/recharge/submit` | 需 | 任意已登录；体内出现 owner_id（机械扫描）[推断] | 未核 | 无 [已核] | 未读函数体 |
| `POST /api/scrape` | 需 | 任意已登录用户 [推断] | 未核 | 无（GG 专用守卫实际失效）[已核] | 未读函数体；**注意**：此处是 `data = request.get_json(silent=True)` 后直接 `data.get(...)`，非 dict 请求体同样触发 O-1（§3.3） |
| `GET /api/scrape/packages` | 需 | 体内出现 'developer'/'admin'（机械扫描）[推断] | 未核 | 无（GG 专用守卫实际失效）[已核] | 未读函数体 |
| `POST /api/scrape/upload-images` | 需 | 任意已登录用户 [推断] | 未核 | 无（GG 专用守卫实际失效）[已核] | 未读函数体（体内出现 get_user_by_id） |
| `GET /api/scrape/users` | 需 | 任意已登录用户 [推断] | 未核 | 无（GG 专用守卫实际失效）[已核] | 未读函数体；**实测**：FB 平台用户访问该端点返回 200（§3.1） |
| `POST /api/video/generate` | 需 | 非 huguan [推断] | 未核 | 无（GG 专用守卫实际失效）[已核] | Task 20 已对户管 403 收口；未读函数体 |
| `POST /api/video/history/delete` | 需 | 非 huguan [推断] | 未核 | 无（GG 专用守卫实际失效）[已核] | 未读函数体 |
| `GET /api/video/history/list` | 需 | 非 huguan [推断] | 未核 | 无（GG 专用守卫实际失效）[已核] | 未读函数体 |
| `POST /api/video/history/save` | 需 | 非 huguan [推断] | 未核 | 无（GG 专用守卫实际失效）[已核] | 未读函数体 |
| `GET /api/video/music-list` | 需 | 非 huguan [推断] | 未核 | 无（GG 专用守卫实际失效）[已核] | 未读函数体 |
| `POST /api/video/next-filename` | 需 | 非 huguan [推断] | 未核 | 无（GG 专用守卫实际失效）[已核] | 未读函数体 |
| `GET /api/video/progress` | 需 | 非 huguan [推断] | 未核 | 无（GG 专用守卫实际失效）[已核] | 未读函数体 |
| `POST /api/video/scan-dir` | 需 | 非 huguan [推断] | 未核 | 无（GG 专用守卫实际失效）[已核] | 扫描本地目录（读文件系统）；未读函数体 |
| `POST /api/video/upload-music` | 需 | 非 huguan [推断] | 未核 | 无（GG 专用守卫实际失效）[已核] | 写本地文件系统；未读函数体 |
| `GET /api/youtube/<vid>/consumption` | 需 | 非 huguan；体内出现 owner_id/is_public（机械扫描）[推断] | 未核 | 无（GG 专用守卫实际失效）[已核] | 未读函数体 |
| `POST /api/youtube/<vid>/consumption` | 需 | 非 huguan；体内出现 owner_id（机械扫描）[推断] | 未核 | 无（GG 专用守卫实际失效）[已核] | 未读函数体 |
| `DELETE /api/youtube/<vid>/consumption/<int:cid>` | 需 | 非 huguan [推断] | 未核 | 无（GG 专用守卫实际失效）[已核] | 未读函数体 |
| `PUT /api/youtube/<vid>/consumption/<int:cid>` | 需 | 非 huguan [推断] | 未核 | 无（GG 专用守卫实际失效）[已核] | 未读函数体 |
| `GET /api/youtube/asset-products` | 需 | 非 huguan [推断] | 未核 | 无（GG 专用守卫实际失效）[已核] | 未读函数体 |
| `POST /api/youtube/backfill-channels` | 需 | 非 huguan [推断] | 未核 | 无（GG 专用守卫实际失效）[已核] | 未读函数体 |
| `POST /api/youtube/batch-edit` | 需 | 非 huguan；体内出现 'developer'/'admin' 分支（机械扫描）[推断] | 未核 | 无（GG 专用守卫实际失效）[已核] | 未读函数体 |
| `GET /api/youtube/consumption/dates` | 需 | 非 huguan；体内出现 owner_id/scope_where（机械扫描）[推断] | 未核 | 无（GG 专用守卫实际失效）[已核] | 未读函数体 |
| `GET /api/youtube/dates` | 需 | 非 huguan；体内出现 owner_id/scope_where（机械扫描）[推断] | 未核 | 无（GG 专用守卫实际失效）[已核] | 未读函数体 |
| `POST /api/youtube/delete` | 需 | 非 huguan；体内 owner_id/is_public/developer/admin（机械扫描）[推断] | 未核 | 无（GG 专用守卫实际失效）[已核] |  |
| `POST /api/youtube/edit` | 需 | 非 huguan；体内 can_modify [已核] | 有（can_modify）[已核] | 无（GG 专用守卫实际失效）[已核] |  |
| `POST /api/youtube/import` | 需 | 非 huguan；体内出现 is_public（机械扫描）[推断] | 未核 | 无（GG 专用守卫实际失效）[已核] | 未读函数体 |
| `GET /api/youtube/list` | 需 | 非 huguan；体内 scope_where [推断] | 未核 | 无（GG 专用守卫实际失效）[已核] |  |
| `GET /api/youtube/product-assets` | 需 | 非 huguan [推断] | 未核 | 无（GG 专用守卫实际失效）[已核] | 未读函数体 |
| `GET /api/youtube/tags` | 需 | 非 huguan [推断] | 未核 | 无（GG 专用守卫实际失效）[已核] | 未读函数体 |
| `POST /api/youtube/tags` | 需 | 非 huguan [推断] | 未核 | 无（GG 专用守卫实际失效）[已核] | 未读函数体 |

### 2.8 FB 平台域 /api/fb/*（49 条）

B-2 / B-6 / B-7 与本次新发现的同族缺口集中在此

| 端点（方法 + 路径） | 是否需登录 | 允许的角色 | 有无归属校验 | 有无平台门禁 | 备注 |
|---|---|---|---|---|---|
| `DELETE /api/fb/accounts/<int:aid>` | 需 | FB 平台用户 或 developer/huguan [推断] | **无 [已核]** | 有（@fb_required → require_platform('fb')）[推断] | **同族缺口（§3.5）** |
| `PUT /api/fb/accounts/<int:aid>` | 需 | FB 平台用户 或 developer/huguan [推断] | **无 [已核]** | 有（@fb_required → require_platform('fb')）[推断] | **同族缺口（§3.5）**：UPDATE fb_accounts ... WHERE id=?；**实测** U2 改 U1 的户 → 200 且改名生效 |
| `GET /api/fb/accounts/<int:aid>/bm-history` | 需 | FB 平台用户 或 developer/huguan [推断] | **无 [已核]** | 有（@fb_required → require_platform('fb')）[推断] | **同族缺口（§3.5）**：**实测** U2 读 U1 的户 BM 历史 → 200 |
| `DELETE /api/fb/accounts/<int:aid>/permanent` | 需 | FB 平台用户 或 developer/huguan [推断] | 未核 | 有（@fb_required → require_platform('fb')）[推断] | 永久删除；未读函数体 |
| `POST /api/fb/accounts/<int:aid>/restore` | 需 | FB 平台用户 或 developer/huguan [推断] | 未核 | 有（@fb_required → require_platform('fb')）[推断] |  |
| `POST /api/fb/accounts/create` | 需 | FB 平台用户 或 developer/huguan [推断] | 不适用（owner_id=本人）[已核] | 有（@fb_required → require_platform('fb')）[推断] | **已核观察（§3.8）**：参数缺失分支 `return err(...), 400` 产生嵌套 tuple ⇒ 该路径抛 TypeError（预先存在，非本任务范围） |
| `GET /api/fb/accounts/deleted` | 需 | FB 平台用户 或 developer/huguan [推断] | 有 [推断] | 有（@fb_required → require_platform('fb')）[推断] | 体内出现 CROSS_USER_ROLES/owner_id（机械扫描） |
| `GET /api/fb/accounts/list` | 需 | FB 平台用户 或 developer/huguan [推断] | 有 [已核] | 有（@fb_required → require_platform('fb')）[推断] |  |
| `DELETE /api/fb/bms/<int:bid>` | 需 | FB 平台用户 或 developer/huguan [推断] | **无 [已核]** | 有（@fb_required → require_platform('fb')）[推断] | **同族缺口（§3.5）**；I-2 路径参数 |
| `PUT /api/fb/bms/<int:bid>` | 需 | FB 平台用户 或 developer/huguan [推断] | **无 [已核]** | 有（@fb_required → require_platform('fb')）[推断] | **B-6/B-7 同族缺口（§3.5）**：UPDATE fb_bms SET name=?,note=? WHERE id=?；**运行时实测**：U2 改 U1 的 BM → 200 且改名生效 |
| `POST /api/fb/bms/<int:bid>/ban-and-migrate` | 需 | FB 平台用户 或 developer/huguan [推断] | **无 [已核]** | 有（@fb_required → require_platform('fb')）[推断] | 封禁+迁移，写操作；**同族缺口（§3.5）** |
| `POST /api/fb/bms/create` | 需 | FB 平台用户 或 developer/huguan [推断] | 不适用（owner_id=本人）[已核] | 有（@fb_required → require_platform('fb')）[推断] |  |
| `GET /api/fb/bms/list` | 需 | FB 平台用户 或 developer/huguan [推断] | 有（本人或共享作用域）[已核] | 有（@fb_required → require_platform('fb')）[推断] |  |
| `GET /api/fb/bms/options` | 需 | FB 平台用户 或 developer/huguan [推断] | **无 [已核]** | 有（@fb_required → require_platform('fb')）[推断] | 返回**全库** BM 选项（跨租户可见，低危） |
| `GET /api/fb/bms/unified` | 需 | FB 平台用户 或 developer/huguan [推断] | 有 [已核] | 有（@fb_required → require_platform('fb')）[推断] |  |
| `POST /api/fb/extract/check-duplicates` | 需 | FB 平台用户 或 developer/huguan [推断] | 未核 | 有（@fb_required → require_platform('fb')）[推断] | **待核**：去重检查是否跨租户比对 |
| `POST /api/fb/extract/parse` | 需 | FB 平台用户 或 developer/huguan [推断] | 未核 | 有（@fb_required → require_platform('fb')）[推断] |  |
| `POST /api/fb/extract/save` | 需 | FB 平台用户 或 developer/huguan [推断] | 不适用（user_id=本人）[已核] | 有（@fb_required → require_platform('fb')）[推断] |  |
| `DELETE /api/fb/lines/<int:lid>` | 需 | FB 平台用户 或 developer/huguan（且拒 huguan）[推断] | **无 [已核]** | 有（@fb_required → require_platform('fb')）[推断] | **同族缺口（§3.5）**：delete_line 无归属校验 |
| `PUT /api/fb/lines/<int:lid>` | 需 | FB 平台用户 或 developer/huguan（且拒 huguan）[推断] | **无 [已核]** | 有（@fb_required → require_platform('fb')）[推断] | **同族缺口（§3.5）**：update_line 无归属校验 |
| `DELETE /api/fb/pixel-bms/<int:bid>` | 需 | FB 平台用户 或 developer/huguan [推断] | **无 [已核]** | 有（@fb_required → require_platform('fb')）[推断] | **B-7 已知缺口（§3.5）** |
| `PUT /api/fb/pixel-bms/<int:bid>` | 需 | FB 平台用户 或 developer/huguan [推断] | **无 [已核]** | 有（@fb_required → require_platform('fb')）[推断] | **B-7 已知缺口（§3.5）**；**实测** U2 改 U1 的 pixel-bm → 200 |
| `GET /api/fb/pixel-bms/<int:bid>/pixels` | 需 | FB 平台用户 或 developer/huguan [推断] | **无 [已核]** | 有（@fb_required → require_platform('fb')）[推断] | **B-6 已知缺口（§3.5）**：list_pixels 仅 WHERE pixel_bm_id=?，无 owner 过滤 |
| `POST /api/fb/pixel-bms/<int:bid>/pixels` | 需 | FB 平台用户 或 developer/huguan [推断] | **无 [已核]** | 有（@fb_required → require_platform('fb')）[推断] | **B-6 已知缺口（§3.5）**：create_pixel 无归属校验 |
| `POST /api/fb/pixel-bms/create` | 需 | FB 平台用户 或 developer/huguan [推断] | 不适用（owner_id=本人）[已核] | 有（@fb_required → require_platform('fb')）[推断] |  |
| `GET /api/fb/pixel-bms/list` | 需 | FB 平台用户 或 developer/huguan [推断] | 有（本人作用域）[已核] | 有（@fb_required → require_platform('fb')）[推断] |  |
| `GET /api/fb/pixel-bms/options` | 需 | FB 平台用户 或 developer/huguan [推断] | **无 [已核]** | 有（@fb_required → require_platform('fb')）[推断] | 返回**全库** pixel-bm 选项（跨租户可见，低危） |
| `DELETE /api/fb/pixels/<int:pxid>` | 需 | FB 平台用户 或 developer/huguan [推断] | **无 [已核]** | 有（@fb_required → require_platform('fb')）[推断] | **B-6 已知缺口（§3.5）** |
| `PUT /api/fb/pixels/<int:pxid>` | 需 | FB 平台用户 或 developer/huguan [推断] | **无 [已核]** | 有（@fb_required → require_platform('fb')）[推断] | **B-6 已知缺口（§3.5）** |
| `GET /api/fb/pixels/list` | 需 | FB 平台用户 或 developer/huguan [推断] | 有（B-2 已修：非跨用户分支强制本人 owner_id）[已核] | 有（@fb_required → require_platform('fb')）[推断] | B-2 项，Task 4 已修；测试含「必须被排除」的对照行 |
| `DELETE /api/fb/products/<int:pid>` | 需 | FB 平台用户 或 developer/huguan [推断] | **无 [已核]** | 有（@fb_required → require_platform('fb')）[推断] | **同族缺口（§3.5）**：**实测** U2 归档 U1 的产品 → 200 |
| `PUT /api/fb/products/<int:pid>` | 需 | FB 平台用户 或 developer/huguan [推断] | **无 [已核]** | 有（@fb_required → require_platform('fb')）[推断] | **同族缺口（§3.5）**：**实测** U2 改 U1 的产品 → 200，product_name 落库为 HACKED |
| `GET /api/fb/products/<int:pid>/detail` | 需 | FB 平台用户 或 developer/huguan [推断] | **无 [已核]** | 有（@fb_required → require_platform('fb')）[推断] | **同族缺口（§3.5）**：**实测** U2 全量读 U1 的产品详情 → 200（跨租户读） |
| `POST /api/fb/products/<int:pid>/lines` | 需 | FB 平台用户 或 developer/huguan（且拒 huguan）[推断] | 未核 | 有（@fb_required → require_platform('fb')）[推断] |  |
| `POST /api/fb/products/<int:pid>/restore` | 需 | FB 平台用户 或 developer/huguan（且拒 huguan）[推断] | 未核 | 有（@fb_required → require_platform('fb')）[推断] |  |
| `POST /api/fb/products/create` | 需 | FB 平台用户 或 developer/huguan [推断] | 不适用（owner_id=本人）[推断] | 有（@fb_required → require_platform('fb')）[推断] |  |
| `GET /api/fb/products/list` | 需 | FB 平台用户 或 developer/huguan [推断] | 有（fb_product_runners 作用域；**实测** U2 列表为空）[已核] | 有（@fb_required → require_platform('fb')）[推断] | 读侧已隔离，与写侧（PUT/DELETE/detail）不隔离形成对照 |
| `GET /api/fb/products/runner-products` | 需 | FB 平台用户 或 developer/huguan [推断] | 未核 | 有（@fb_required → require_platform('fb')）[推断] |  |
| `DELETE /api/fb/reports/<int:rid>` | 需 | FB 平台用户 或 developer/huguan [推断] | **无 [已核]** | 有（@fb_required → require_platform('fb')）[推断] | **同族缺口（§3.5）**：**实测** U2 删 U1 的报告 → 200（数据被真删） |
| `PUT /api/fb/reports/<int:rid>` | 需 | FB 平台用户 或 developer/huguan [推断] | **无 [已核]** | 有（@fb_required → require_platform('fb')）[推断] | **同族缺口（§3.5）**：**实测** U2 改 U1 报告的成本 → 200 |
| `POST /api/fb/reports/batch-delete` | 需 | FB 平台用户 或 developer/huguan [推断] | **无 [已核]** | 有（@fb_required → require_platform('fb')）[推断] | **同族缺口（§3.5）**：batch_delete_reports 无归属校验 |
| `GET /api/fb/reports/export` | 需 | FB 平台用户 或 developer/huguan [推断] | 有（作用域）[已核] | 有（@fb_required → require_platform('fb')）[推断] |  |
| `GET /api/fb/reports/last-sync` | 需 | FB 平台用户 或 developer/huguan [推断] | 未核 | 有（@fb_required → require_platform('fb')）[推断] |  |
| `GET /api/fb/reports/list` | 需 | FB 平台用户 或 developer/huguan [推断] | 有（user_id=? 作用域）[已核] | 有（@fb_required → require_platform('fb')）[推断] |  |
| `POST /api/fb/reports/retry-sync` | 需 | FB 平台用户 或 developer/huguan [推断] | 未核 | 有（@fb_required → require_platform('fb')）[推断] |  |
| `GET /api/fb/reports/stats` | 需 | FB 平台用户 或 developer/huguan [推断] | 未核 | 有（@fb_required → require_platform('fb')）[推断] |  |
| `GET /api/fb/reports/sync-status` | 需 | FB 平台用户 或 developer/huguan [推断] | 未核 | 有（@fb_required → require_platform('fb')）[推断] |  |
| `GET /api/fb/reports/sync-status/<int:log_id>` | 需 | FB 平台用户 或 developer/huguan [推断] | 未核 | 有（@fb_required → require_platform('fb')）[推断] |  |
| `GET /api/fb/users` | 需 | FB 平台用户 或 developer/huguan [推断] | 不适用（平台级用户列表）[已核] | 有（@fb_required → require_platform('fb')）[推断] | 体内出现 role（机械扫描）；平台级而非租户级列表 |

### 2.9 户管看板域 /api/huguan/*（4 条）

@huguan_required 独占

| 端点（方法 + 路径） | 是否需登录 | 允许的角色 | 有无归属校验 | 有无平台门禁 | 备注 |
|---|---|---|---|---|---|
| `GET /api/huguan/dashboard` | 需 | 仅 huguan [推断] | 未核 | 不适用 | @huguan_required ⇒ role == 'huguan'；看板数据是全户范围（产品定位如此） |
| `POST /api/huguan/dashboard` | 需 | 仅 huguan [推断] | 未核 | 不适用 | 同上 |
| `POST /api/huguan/dashboard/push` | 需 | 仅 huguan [推断] | 未核 | 不适用 | 同上 |
| `POST /api/huguan/dashboard/sync` | 需 | 仅 huguan [推断] | 未核 | 不适用 | 同上 |

### 2.10 TT 平台域 /api/tt/*（54 条）

TT 账户、充值、产品、包、回收原因

| 端点（方法 + 路径） | 是否需登录 | 允许的角色 | 有无归属校验 | 有无平台门禁 | 备注 |
|---|---|---|---|---|---|
| `DELETE /api/tt/accounts/<int:aid>` | 需 | TT 平台用户（非 viewer）或 developer/huguan [已核] | 有 [已核] | 有（@tt_required / @tt_write_required）[推断] | 同上；I-2 路径参数 |
| `PUT /api/tt/accounts/<int:aid>` | 需 | TT 平台用户（非 viewer）或 developer/huguan [已核] | 有 [已核] | 有（@tt_required / @tt_write_required）[推断] | 体内：role not in CROSS_USER_ROLES and row['owner_id'] != uid → 403 |
| `GET /api/tt/accounts/<int:aid>/bc-history` | 需 | TT 平台用户 或 developer/huguan [推断] | 有 [推断] | 有（@tt_required / @tt_write_required）[推断] |  |
| `DELETE /api/tt/accounts/<int:aid>/bc-history/<int:hid>` | 需 | TT 平台用户（非 viewer）或 developer/huguan [推断] | 有 [推断] | 有（@tt_required / @tt_write_required）[推断] |  |
| `DELETE /api/tt/accounts/<int:aid>/permanent` | 需 | TT 平台用户（非 viewer）或 developer/huguan [推断] | 有 [推断] | 有（@tt_required / @tt_write_required）[推断] |  |
| `PUT /api/tt/accounts/<int:aid>/reassign` | 需 | TT 平台用户 或 developer/huguan [推断] | 未核 | 有（@tt_required / @tt_write_required）[推断] | I-2 路径参数 |
| `GET /api/tt/accounts/<int:aid>/recharge-records` | 需 | TT 平台用户 或 developer/huguan [推断] | 有 [推断] | 有（@tt_required / @tt_write_required）[推断] |  |
| `POST /api/tt/accounts/<int:aid>/restore` | 需 | TT 平台用户（非 viewer）或 developer/huguan [推断] | 有 [推断] | 有（@tt_required / @tt_write_required）[推断] |  |
| `POST /api/tt/accounts/batch-create` | 需 | TT 平台用户（非 viewer）或 developer/huguan [推断] | 未核 | 有（@tt_required / @tt_write_required）[推断] |  |
| `POST /api/tt/accounts/batch-delete` | 需 | 同上 [推断] | 有 [推断] | 有（@tt_required / @tt_write_required）[推断] | 体内出现 CROSS_USER_ROLES/owner_id |
| `POST /api/tt/accounts/batch-lookup` | 需 | TT 平台用户 或 developer/huguan [推断] | 未核 | 有（@tt_required / @tt_write_required）[推断] | **待核**：同上 |
| `POST /api/tt/accounts/batch-update` | 需 | 同上 [推断] | 有 [推断] | 有（@tt_required / @tt_write_required）[推断] | 体内出现 CROSS_USER_ROLES/owner_id |
| `POST /api/tt/accounts/create` | 需 | TT 平台用户（非 viewer）或 developer/huguan [推断] | 未核 | 有（@tt_required / @tt_write_required）[推断] |  |
| `GET /api/tt/accounts/deleted` | 需 | TT 平台用户 或 developer/huguan [推断] | 有 [推断] | 有（@tt_required / @tt_write_required）[推断] | 体内出现 CROSS_USER_ROLES/owner_id |
| `GET /api/tt/accounts/list` | 需 | TT 平台用户 或 developer/huguan [推断] | 有（体内 CROSS_USER_ROLES/owner_id，机械扫描）[推断] | 有（@tt_required / @tt_write_required）[推断] |  |
| `GET /api/tt/accounts/lookup` | 需 | TT 平台用户 或 developer/huguan [推断] | 未核 | 有（@tt_required / @tt_write_required）[推断] | **待核**：是否按 owner 过滤 |
| `POST /api/tt/accounts/sync-from-sheet` | 需 | 同上 [推断] | 有 [推断] | 有（@tt_required / @tt_write_required）[推断] | 体内出现 CROSS_USER_ROLES/owner_id |
| `DELETE /api/tt/bcs/<int:bid>` | 需 | 同上 [推断] | 未核 | 有（@tt_required / @tt_write_required）[推断] |  |
| `PUT /api/tt/bcs/<int:bid>` | 需 | 同上 [推断] | 未核 | 有（@tt_required / @tt_write_required）[推断] |  |
| `POST /api/tt/bcs/create` | 需 | TT 平台用户（非 viewer）或 developer/huguan [推断] | 未核 | 有（@tt_required / @tt_write_required）[推断] |  |
| `GET /api/tt/bcs/list` | 需 | TT 平台用户 或 developer/huguan [推断] | 有 [推断] | 有（@tt_required / @tt_write_required）[推断] |  |
| `GET /api/tt/bcs/options` | 需 | TT 平台用户 或 developer/huguan [推断] | 有 [推断] | 有（@tt_required / @tt_write_required）[推断] |  |
| `GET /api/tt/data/export` | 需 | TT 平台用户 或 developer/huguan [推断] | 未核 | 有（@tt_required / @tt_write_required）[推断] |  |
| `POST /api/tt/data/import` | 需 | TT 平台用户（非 viewer）或 developer/huguan [推断] | 未核 | 有（@tt_required / @tt_write_required）[推断] |  |
| `DELETE /api/tt/packages/<int:pkg_id>` | 需 | 同上 [推断] | 未核 | 有（@tt_required / @tt_write_required）[推断] |  |
| `PUT /api/tt/packages/<int:pkg_id>` | 需 | TT 平台用户（非 viewer）或 developer/huguan（拒 huguan）[推断] | 未核 | 有（@tt_required / @tt_write_required）[推断] |  |
| `POST /api/tt/packages/batch-delete` | 需 | 同上 [推断] | 未核 | 有（@tt_required / @tt_write_required）[推断] |  |
| `DELETE /api/tt/products/<int:pid>` | 需 | 同上 [推断] | 未核 | 有（@tt_required / @tt_write_required）[推断] | **未核**：同上 |
| `PUT /api/tt/products/<int:pid>` | 需 | TT 平台用户（非 viewer）或 developer/huguan（拒 huguan）[推断] | 未核 | 有（@tt_required / @tt_write_required）[推断] | **未核**：未读函数体，不排除与 GG products 同形 |
| `GET /api/tt/products/<int:pid>/assets` | 需 | TT 平台用户 或 developer/huguan [推断] | 未核 | 有（@tt_required / @tt_write_required）[推断] |  |
| `POST /api/tt/products/<int:pid>/assets` | 需 | TT 平台用户（非 viewer）或 developer/huguan（拒 huguan）[推断] | 未核 | 有（@tt_required / @tt_write_required）[推断] |  |
| `DELETE /api/tt/products/<int:pid>/assets/<video_id>` | 需 | 同上 [推断] | 未核 | 有（@tt_required / @tt_write_required）[推断] |  |
| `POST /api/tt/products/<int:pid>/check-delist` | 需 | 同上 [推断] | 未核 | 有（@tt_required / @tt_write_required）[推断] |  |
| `GET /api/tt/products/<int:pid>/detail` | 需 | TT 平台用户 或 developer/huguan [推断] | 未核 | 有（@tt_required / @tt_write_required）[推断] |  |
| `POST /api/tt/products/<int:pid>/packages` | 需 | 同上 [推断] | 未核 | 有（@tt_required / @tt_write_required）[推断] |  |
| `POST /api/tt/products/<int:pid>/restore` | 需 | 同上 [推断] | 未核 | 有（@tt_required / @tt_write_required）[推断] |  |
| `POST /api/tt/products/create` | 需 | TT 平台用户（非 viewer）或 developer/huguan（拒 huguan）[推断] | 未核 | 有（@tt_required / @tt_write_required）[推断] |  |
| `GET /api/tt/products/delist-status` | 需 | TT 平台用户 或 developer/huguan [推断] | 未核 | 有（@tt_required / @tt_write_required）[推断] |  |
| `POST /api/tt/products/import-text` | 需 | TT 平台用户 或 developer/huguan（拒 huguan）[推断] | 未核 | 有（@tt_required / @tt_write_required）[推断] |  |
| `GET /api/tt/products/list` | 需 | TT 平台用户 或 developer/huguan [推断] | 未核 | 有（@tt_required / @tt_write_required）[推断] |  |
| `POST /api/tt/products/merge` | 需 | TT 平台用户（非 viewer）或 developer/huguan（拒 huguan）[推断] | 未核 | 有（@tt_required / @tt_write_required）[推断] |  |
| `GET /api/tt/products/runner-products` | 需 | TT 平台用户 或 developer/huguan [推断] | 未核 | 有（@tt_required / @tt_write_required）[推断] |  |
| `DELETE /api/tt/recharge/<int:rid>` | 需 | 同上 [推断] | 有 [推断] | 有（@tt_required / @tt_write_required）[推断] |  |
| `PUT /api/tt/recharge/<int:rid>` | 需 | TT 平台用户（非 viewer）或 developer/huguan [推断] | 有 [推断] | 有（@tt_required / @tt_write_required）[推断] | 体内出现 CROSS_USER_ROLES/role |
| `POST /api/tt/recharge/<int:rid>/retry-sheets` | 需 | 同上 [推断] | 有 [推断] | 有（@tt_required / @tt_write_required）[推断] |  |
| `POST /api/tt/recharge/batch-submit` | 需 | 同上 [推断] | 有 [推断] | 有（@tt_required / @tt_write_required）[推断] | 同上 |
| `POST /api/tt/recharge/submit` | 需 | 同上 [推断] | 有 [推断] | 有（@tt_required / @tt_write_required）[推断] | 体内出现 CROSS_USER_ROLES/owner_id |
| `DELETE /api/tt/recycle-reasons/<int:rid>` | 需 | 同上 [推断] | 有 [推断] | 有（@tt_required / @tt_write_required）[推断] |  |
| `PUT /api/tt/recycle-reasons/<int:rid>` | 需 | 同上 [推断] | 有 [推断] | 有（@tt_required / @tt_write_required）[推断] |  |
| `POST /api/tt/recycle-reasons/create` | 需 | TT 平台用户（非 viewer）或 developer/huguan [推断] | 未核 | 有（@tt_required / @tt_write_required）[推断] |  |
| `GET /api/tt/recycle-reasons/list` | 需 | TT 平台用户 或 developer/huguan [推断] | 有 [推断] | 有（@tt_required / @tt_write_required）[推断] |  |
| `GET /api/tt/settings` | 需 | TT 平台用户 或 developer/huguan [推断] | 未核 | 有（@tt_required / @tt_write_required）[推断] |  |
| `POST /api/tt/settings` | 需 | TT 平台用户 或 developer/huguan；体内出现 role [推断] | 未核 | 有（@tt_required / @tt_write_required）[推断] |  |
| `GET /api/tt/users` | 需 | TT 平台用户 或 developer/huguan；体内出现 role [推断] | 未核 | 有（@tt_required / @tt_write_required）[推断] |  |


## 3. 已知缺口 / 待用户裁决

> 本节全部是**未修**项。已修项见 §3.10。

### 3.1 GG 业务路由**没有有效的平台隔离**（新证据，运行时实测）★

`py/main.py:168-200` 的 `_guard_gg_platform`（`@app.before_request`）是**唯一**打算给 GG 业务路由做平台隔离的地方，但它在**任何情况下都不会拦住请求**：`get_jwt_identity()` 在未经过 `@jwt_required()` 的视图外调用会抛 `RuntimeError`，被它自己的 `except Exception: return None` 吞掉 ⇒ 守卫恒返回 `None`。

**实测（Flask test client，只读探测）**：一个 FB 平台用户的 token 访问 GG 业务路由，全部 **200**：
`/api/accounts/list`、`/api/mcc/list`、`/api/products/list`、`/api/youtube/list`、`/api/ad-reports/dates`、`/api/scrape/users`。

⇒ 结论：**GG 业务域当前没有任何平台级隔离**；FB/TT 用户可读写 GG 数据（能否越权取决于各端点的归属校验，而归属校验只在部分端点存在）。设计文档 §九-3 已记「当前没有任何平台级隔离」，本表把它从「设计判断」升级为**实测**。
另注：`_GG_ONLY_PREFIXES` 之外的大量 GG 域（`/api/copywriting`、`/api/recharge`、`/api/config` 等）本就被该守卫**显式跳过**，即使守卫生效也不覆盖。

### 3.2 I-2：`<int:...>` 路由对超大整数路径参数无防护（未修，待裁决）

全仓 **28 组** `<int:...>` 路由组对超大整数路径参数无防护；其中 **5 组**会返回 500 + **英文异常原文**（`/api/accounts/<int:aid>/reassign` 已由 Task 7 修复轮 2 闭合，其余仍在），**23 组**异常逸出视图（由全局 500 handler 兜住，见 §3.4）。本表中凡备注写「I-2 路径参数」的行即属该族。**待用户裁决是否集中收口。**

### 3.3 O-1：非 dict 请求体触发 `AttributeError → 500`（未修，待裁决）

`request.get_json(silent=True) or {}` 模式在请求体是 `[1,2]` / `"x"` 这类非 dict 时，`.get(...)` 抛 `AttributeError`；部分调用点该语句位于 `try` 之外（例如 `fb_routes` 的写接口在 `db = _yt_db()` 之后），异常直接逸出为 500。全仓该模式约 **79 处**。

### 3.4 O-2：全局 500 handler 回显 traceback（未修，信息泄露）

`py/main.py` 约 `:10327`（注册在 `if __name__ == "__main__":` 内，`waitress.serve` 下同样生效）的 `_internal_error` 会把 **最多 2000 字符的 traceback**（含绝对路径与源码行）通过 JSON 的 `trace` 字段回给客户端。⇒ 上面 §3.2 那些逸出的异常在生产下**不是通用 500 页，而是带源码路径的回显**。这一条把 I-2 的优先级从「健壮性」抬到「信息泄露」。

### 3.5 B-6 / B-7 及其**同族扩展**：按 id 的单行读写缺归属校验（未修）

设计文档已知的 **B-6（`pixels` 族）/ B-7（`pixel-bms` 族）**：整族无归属校验。本次核查**实测确认了这一缺口比原记录更宽**，FB 域的单行写接口普遍如此：

| 端点族 | 结论 | 证据等级 |
|---|---|---|
| `/api/fb/bms/<bid>` PUT/DELETE、`/api/fb/bms/options`、`/api/fb/bms/<bid>/ban-and-migrate` | 无归属校验（`UPDATE fb_bms ... WHERE id=?`） | 读函数体 [已核] + PUT 实测 200 |
| `/api/fb/accounts/<aid>` PUT/DELETE、`/api/fb/accounts/<aid>/bm-history` | 无归属校验 | 读函数体 [已核] + 实测 200 |
| `/api/fb/products/<pid>` PUT/DELETE、`/api/fb/products/<pid>/detail` | 无归属校验 | 读函数体 [已核] + 实测 200（改名校验、跨租户读） |
| `/api/fb/lines/<lid>` PUT/DELETE、`/api/fb/reports/<rid>` PUT/DELETE、`/api/fb/reports/batch-delete` | 无归属校验 | 读函数体 [已核] + 报告实测 200 |
| `/api/fb/pixel-bms/<bid>` PUT/DELETE、`/api/fb/pixel-bms/<bid>/pixels` GET/POST、`/api/fb/pixels/<pxid>` PUT/DELETE、`/api/fb/pixel-bms/options` | 无归属校验（B-6/B-7 原记录） | 读函数体 [已核] + 实测 200 |
| **`/api/mcc/<int:mid>/detail` GET**（GG 域，本次新发现） | **无归属校验**：只校验 MCC 存在，随后返回该 MCC 完整树（直属+子 MCC、账户名/account_id/状态、关联产品） | 读函数体 [已核]（**未做运行时探测**） |
| **`/api/mcc/<int:mid>/link` POST**（GG 域，本次新发现） | **无归属校验**：任意登录用户可把他人的 MCC（含上级链）关联到自己名下 | 读函数体 [已核]（**未做运行时探测**） |

**读侧与写侧的对照（实测）**：U1 有产品、`fb_product_runners` 里只有 U1；U2 调 `/api/fb/products/list` 得到 `[]`（**读侧已隔离**），但 U2 调 `/api/fb/products/<U1的pid>` PUT 返回 **200** 且 `product_name` 落库为 `HACKED`（**写侧未隔离**）。这类「读侧已收、写侧未收」的错配是本次核查最值得注意的形状。

**同族的「读侧缺隔离」（本次新发现，读函数体 [已核]，未做运行时探测）**：

| 端点 | 现状 |
|---|---|
| `GET /api/accounts/lookup` | `WHERE a.account_id=? AND a.deleted_at IS NULL` —— **无 owner 条件**；回传 `name`/`account_id`/`timezone`/MCC 名与码/**`owner_id`/`owner_name`**/状态 ⇒ 任意登录用户按 `account_id` 即可探明他人账户的归属与明细 |
| `POST /api/accounts/batch-lookup` | `WHERE a.account_id IN (...)` —— **无 owner 条件**，一次批量探明多户 |
| `GET /api/mcc/<int:mid>/detail` | 见上表 |
| `POST /api/mcc/<int:mid>/link` | 见上表 |

**建议**：按 B-2 的修法（照抄同文件已有 `owner_filter` 写法）对整族统一收口，而不是逐条打补丁 —— 否则修完 PUT 仍会漏 DELETE / detail / batch-*。

### 3.6 I-3：regions 的旁路写入口（未修，待裁决）

`/api/ad-reports/save`（调用点 `py/main.py:8810`）与 `/api/google-sheets/update-zuobiao`（调用点 `py/main.py:6837`）都会走到 `_auto_link_mcc_and_accounts`（`def` 在 `py/main.py:8718`），其中 `py/main.py:8738` 执行 `INSERT OR IGNORE INTO regions(name, timezone) VALUES(?,?)` —— 于是**任意登录用户**都能通过保存广告报告来给全局 `regions` 表补建地区，绕过 Task 6 刚给 `/api/regions/create` 加的 `GLOBAL_OPTION_ROLES` 门禁。
已复核：其余所有 `INSERT INTO regions` 站点均非路由可达（`database.py:1239/1274` 建库、`:1900` `_init_regions` 种子、`:1928` `regions_create` 本身）。

### 3.7 `accounts:statuses` 死键（未清，有守护测试）

`py/routes/huguan_dashboard_routes.py:127` 仍有一处同族死 `_app_cache.delete(f"accounts:statuses:{...}")`（全库无任何该键的写入）。Task 9 勘误 (3) 判定：**有守护测试**，清理会动测试，故未清。

### 3.8 其他已核但未处理的观察（低危，供参考）

1. `/api/settings/account` POST：`sheet_mappings` 的全局写入被体内 `is_admin`（developer/admin）挡住，但 **`recharge_sheet_id` 的全局写入没有任何角色门禁** —— 任意登录用户可改全局充值表 ID（影响所有用户）。
2. `/api/mcc/create`：当传入的 `mcc_id` 已属他人时，响应里带 `owner_name`（`users.display_name`/`username`）⇒ 可用于探测任意 `mcc_id` 的归属人。
3. `/api/sales-persons/list`、`/api/fb/users`、`/api/platform/users`：平台级全量列表，含跨户用户名/展示名（有意设计，但属可枚举面）。
4. `/api/fb/accounts/create`：参数缺失分支写作 `return err('...'), 400`，产生**嵌套 tuple** ⇒ 该路径抛 `TypeError` 而非返回 400（预先存在，与本次鉴权主题无关，仅记录）。
5. `/api/browse-file`、`/api/browse-folder`、`/api/browse-save` 是 `@jwt_required(optional=True)` ⇒ **不带 token 也能调**，且 `browse-save` 会**写本地文件系统**；其路径控制逻辑本次未读（表中标 `未核`）。
6. `/api/settings/account` GET 同为 `optional`，读的是全局配置（充值表 ID / 表格映射）—— 是否匿名可读**待核**。
7. `/api/users/names`（`py/main.py:7741`）是 `@jwt_required(optional=True)` 且**体内无 developer 过滤** ⇒ **匿名**即可枚举「有产品的用户」的 `id`/`username`/`display_name`，**且含 developer 账号**。对照 `/api/auth/names`（同为可选登录，但非 developer 调用者会加 `AND u.role != 'developer'`）—— 两个同名族接口的可见口径**不一致**，`/api/users/names` 是更宽的那个。

### 3.9 疑点（**未确定为缺口**，请勿据此直接改代码）

- **GG 产品写接口是否有意共享？** `/api/products/<int:pid>` 的 PUT/DELETE 只有 `_reject_viewer()`，**无** owner/runner 判定；而 `/api/products/list` 是按 `product_runners` 作用域的（`runner=all` 时可越过本人范围，viewer 被强制 `all`）。「GG 产品是团队共享资源」与「漏了校验」两种解释都能解释现状 ⇒ **待用户裁决**，本次**不列为确认缺口**。
- **⚠️ 反例（不要凭「看起来可疑」下结论）：`/api/ad-reports/<int:report_id>` PUT/DELETE 与 `/api/ad-reports/batch-delete`。**
  机械扫描在这三条的函数体里**一个归属符号都没扫到**，我在核查途中据此一度把它们写成了「疑似无归属校验」。**读到函数体才发现是机械扫描的假阴性**：三条都写着
  `... WHERE id=? AND user_id=?`（batch 版是 `WHERE id IN (...) AND user_id=?` 并对 `rowcount` 计数），**归属校验确实存在**。⇒ 本表把它们标为 `[已核] 有`，并把它当作本任务「**不要臆测出一个看起来合理的结论**」的正面样本：机械扫描为空**不等于**没有校验。
- **`/api/tt/products/*`、`/api/tt/packages/*`、`/api/tt/bcs/*`**：TT 平台，归属校验**未核**；不排除与 GG/FB 同形。
- **`/api/tt/accounts/lookup`**：TT 平台的按名称/ID 查询单户，是否按 owner 过滤**未核**（GG 版的同名端点`/api/accounts/lookup` 已读函数体，确认**无** owner 条件，见 §3.5 —— TT 版**不能**因此推定，故仍列 `未核`）。

### 3.10 已收紧项的现状（勘误 (4) 要求的对照）

| 项 | 内容 | 状态 |
|---|---|---|
| A 类 13 条 | `scrape/download`、`image`、`fonts/*`(7)、`font-file`、`google-ads/*`(2)、`google-sheets/status`、`translate` | **11 条已补 `@jwt_required()`**；`/api/image`、`/api/font-file` 为**有意保留匿名**（扩展名白名单 + realpath 目录包含）。另有 Task 20 的 3 条（`video/download`、`audio-replace/download`、`audio`）仍是 **optional**（前端不带头，见 §3.1 注） |
| B-1 | GG 三处写端点归属校验（`accounts_update`/`accounts_reassign`/`accounts_batch_update`） | **已修**（Task 7，含修复轮 2 的 int64 上界与同族 `aid` 向量） |
| B-2 | `fb_pixels` 跨租户 | **已修**（Task 4，测试含「必须被排除」对照行） |
| B-3 | `sales-persons/create` 无角色白名单 | **已裁决：不改代码**（属产品功能） |
| B-4 | TT 分支 `agents` rename/delete 绕过 owner 校验 | **已修**（Task 5） |
| B-5 | `regions_*` 全组收紧到 `GLOBAL_OPTION_ROLES` | **已修**（Task 6；但 §3.6 的旁路仍在） |
| B-6 / B-7 | `pixels` / `pixel-bms` 无归属校验 | **未修**（见 §3.5，且实际范围更大） |
| C-1 | `accounts_reassign` 非法 `owner_id` → 500 | **已修**（Task 7；`accounts_create` 经复核**不成立**，见 C-1b） |
| C-2 | `py/auth.py` 空 `base_where` 拼 `AND` → 500 | **已修**（Task 8） |
| D-1 | `accounts:statuses` 死 `delete` | **部分**：`py/main.py` 内已清（Task 9）；`huguan_dashboard_routes.py:127` 那处**有守护测试，未清**（§3.7） |
| D-2 | `accounts_batch_delete` 谎报条数 | **已修**（Task 9，返回真实删除条数） |
| D-3 | —— | 复核后**不成立，已划掉** |

## 4. 本次交付物的证据边界

### 4.1 逐条核过的（`[已核]` 的依据）

- **读过函数体**：`py/routes/decorators.py`、`py/routes/helpers.py`、`py/routes/auth_routes.py` 全文；`py/main.py` 中本表标 `[已核]` 的约 60 个端点（含 `before_request` 守卫、500 handler、`accounts`/`mcc`/`regions`/字典组、`settings/account`、`ad-reports/save`、`google-sheets/update-zuobiao`、`products` 写接口、`youtube/edit`、`copywriting/edit`、`audit-log/list`、`delist/pending`、`config/ai`、`admin/data/*`）；`py/routes/fb_routes.py` 中约 33 个端点；`py/routes/tt_accounts_routes.py` 的 `update_account`/`delete_account`。
- **运行时实测（Flask test client，只读探测，不落任何持久产物，探测脚本与基线输出都在仓库外且已清）**：
  1. FB 用户的 token 访问 GG 业务路由 → 全部 200（§3.1）。
  2. 跨租户 FB 写/读：`bms` PUT、`accounts` PUT、`accounts/<aid>/bm-history` GET、`reports` PUT/DELETE、`products` PUT/DELETE/detail、`pixel-bms` PUT → 全部 200 且写操作**真实生效**（§3.5）。
  3. `products` 读侧 vs 写侧的对照实验（U1/U2 + `fb_product_runners` 成员关系）。
- **角色字面量的机械化普查（辅助手段，用于**定位**要读哪个函数体，不用于下结论）**：对全部 297 条应用路由，逐个提取函数体（AST `FunctionDef.lineno`→`end_lineno`），统计体内是否出现 `"huguan"` / `HUGUAN_ROLE` / `"developer"` / `"admin"` / `"viewer"` / `CROSS_USER_ROLES` / `GLOBAL_OPTION_ROLES` / `PLATFORM_SWITCH_ROLES` / `_check_modify_user` / `_can_access_user_data` 等符号。**这次普查正是 §1.3 那条勘误靶心的发现途径**：它把 `/api/admin/users*` 与 `/api/platform/users` 共 9 条点名出来（体内出现 `"huguan"`），我据此逐条读函数体，才确认它们**对 huguan 放行**。
- **⚠️ 该普查的第一版有缺陷，必须记下**：第一版关键词表里**漏了 `'huguan'` 与 `HUGUAN_ROLE`**，因此对这 9 条**什么都没扫到**，我据此把它们误写成「仅 developer/admin」并在表里写了「**不含 huguan**」。**这是本任务最危险的一次接近事故** —— 一条错误的 `[已核]`，正是勘误 (3) 警告的那种文档。补上关键词并逐条读函数体后才更正。⇒ 凡「机械扫描为空」的结论，本表一律不下断言（同类反例见 §3.9 首条）。
- **对照验证（勘误 (1) 强制）**：见 §4.4。

### 4.2 只按装饰器栈推断的（`[推断]` 的依据）

- 「是否需登录」列对 `[推断]` 行来自扫描脚本（该脚本已通过对照验证，§4.4）。
- 「允许的角色」列对 `[推断]` 行来自 §1.2 列出的装饰器语义，**或**函数体内关键词的机械扫描（`owner_id`、`CROSS_USER_ROLES`、`GLOBAL_OPTION_ROLES`、`role`、`can_modify`、`scope_where`、`reject_viewer` 等）。
- **机械扫描的局限必须知道**：它只说明「该符号出现在函数体内」，**不区分**「用作归属校验」还是「用作 SELECT 列名/返回值字段」。因此本表**从不**用机械扫描去断言「有归属校验」—— 标 `有` 的行都是读过函数体的；机械扫描只用来写「体内出现 X（机械扫描）」并配合 `未核`。

### 4.3 **没有**验证什么（结论边界）

1. **298 行中有 211 行的「归属校验」列是 `未核`（约 71%）**（含 1 行 Flask 内置 `static`，非应用端点）。这些行本表**不为它们背书**，既不背书「有校验」也不背书「无校验」。另有 236 行的「允许的角色」列是 `[推断]`（约 79%），同样只是**装饰器层的上界**，不是最终准入结论。
2. **未跑浏览器、未做端到端 UI 验证**；运行时探测只覆盖了 §4.1 列出的少数端点，其余 `[已核]` 结论来自**静态阅读**。
3. **未做持久化影响评估**：实测中的写操作（改 FB 的 BM/户/产品/报告名）发生在**探测用的临时数据库/测试客户端**环境，未评估生产数据的历史污染。
4. **前端未核**：本表只覆盖后端路由，**未**核对前端是否会绕过（例如某些页面直链可达、某些入口对普通用户可见）。设计文档 §3.1 已指出 `/toolkit/zuobiao`、`/toolkit/translate` 可直链打开。
5. **未核 I-2 的 28 组清单明细**：本表只在备注里标出「I-2 路径参数」，未逐一枚举该 28 组的分组口径。
6. **O-1 的 79 处未逐一枚举**：只核了 `fb_routes` 的写接口那一类触发形态。
7. **`/api/huguan/*` 的数据范围未核**：`@huguan_required` 只保证调用者是 huguan，**看板数据本身是全户范围**（产品定位如此），是否应分片未评估。
8. **生产部署差异未核**：`_internal_error`（§3.4）注册在 `if __name__ == "__main__":` 内，本表按 `waitress.serve` 下生效来陈述；不同启动方式下是否仍注册未逐一验证。

### 4.4 扫描脚本的对照验证结果（勘误 (1) 强制项）

- **结论：计划原稿给的扫描脚本是错的，我修了脚本后才用它。**
- **症状**：原稿从 `inspect.getsourcelines(view)` 返回的行号 `start` **向上**扫 `start-2` 起的连续 `@` 行。而 `co_firstlineno` 对**带装饰器的函数**指向的是**第一个装饰器所在行**，不是 `def` 行 ⇒ 向上扫等于从装饰器栈**外侧**往外找，**恒得到空栈**。实测症状：`PUT /api/accounts/<int:aid>/reassign` 被报成「无装饰器」，全仓 `require_platform`/`tt_write_required`/`no_huguan` 命中数为 0。
- **修法**：改为从 `start` **向下**扫，收集 `@` 行，遇到 `def` 行停止（并容忍多行装饰器，按括号深度累计）。另新增**方法 B（独立 AST 解析）**作为第二来源：直接 `ast.parse` 各源文件、取 `FunctionDef.decorator_list`、`ast.unparse` 后与本方法归一化比对。
- **修后结果**：**297/298 一致**，唯一不一致的是 Flask 内置 `static` 路由（`inspect` 解析到 `flask/app.py`，AST 侧无同名函数），属预期，非应用端点。
- **三项人工对照**（勘误 (1) 要求）：
  1. `PUT /api/accounts/<int:aid>/reassign` → `@app.route(...)` + `@jwt_required()`，**无**其它守卫 —— 与已知事实**完全一致**。
  2. 「任一带 `@require_platform(...)` 的端点」→ **该验证项在事实上不成立**：本仓库里 `require_platform` **不是装饰器**，而是被 `@fb_required`/`@gg_required`/`@tt_required`/`@tt_write_required` 在内部调用的辅助函数，所以不存在「带 `@require_platform(...)` 的端点」。我以其等价物替代核对：`@fb_required` 49 处、`@tt_required` 20 处、`@tt_write_required` 34 处，均符合预期。
  3. 带 `@tt_write_required` / `@no_huguan` 的端点 → `@tt_write_required` 34 处、`@no_huguan` 79 处，均符合预期。
- 全量装饰器计数（基线）：`@jwt_required*` 288、`@app.route` 178、`@no_huguan` 79、`@fb_required` 49、`@tt_write_required` 34、`@tt_required` 20、`@huguan_required` 4、`@admin_required` 2、`@gg_required` **0 处（零使用）**。
- 无 `@jwt_required()` 的 10 条：`/`、`/<path:filename>`（静态）、`/favicon.ico`、`/api/health`、`/api/font-file`、`/api/image`、`/api/auth/login`、`/api/auth/register`、`/api/admin/data/export/<int:uid>`、`/api/admin/data/import`（**后两条虽无 `@jwt_required()`，但由 `@admin_required` 自行校验 JWT** —— 只看装饰器清单会误判为「匿名」，这是本表把它单列的原因）。

