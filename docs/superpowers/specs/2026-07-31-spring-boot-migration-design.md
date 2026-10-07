# GG-Server Spring Boot 迁移设计文档

> **文档版本**: v1.35  
> **日期**: 2026-07-31（v1.35 更新于 2026-10-07）  
> **目的**: 将现有 Python Flask 后端完整迁移至 Java Spring Boot + MySQL  
> **新项目名称**: **LM-Server**（`D:\server\cc\LM-Server`，包名 `com.lmserver`）  
> **前置条件**: 前端 Vite/Vue3 不变，仅替换后端 API 层  
> **v1.35 变更**: **定时任务：权限下放到管理员 + 周期可配置**（对应 `py/routes/decorators.py`、`py/main.py`、`frontend/src/{views/SchedulerView.vue,components/AppSidebar.vue,router/index.js,api/admin.js}`，详见**附录 K**）——四件事：① **补文档缺口**：本文档接口表漏了 `POST /api/admin/trigger-tt-delist-check`；② **定时界面权限从「仅 developer」下放到各平台 admin**（新增 `scheduler_required(platform)` 装饰器，⚠️ **刻意不复用 `require_platform`** —— 它的 `PLATFORM_SWITCH_ROLES` 含 `HUGUAN_ROLE`，会把户管无条件放行）；③ **按平台隔离**：GG admin 见「掉包检测 + 每周清理」、TT admin 见「TT 掉包检测」、**FB admin 无任务（页面空态，`tasks: []` ≠ 403）**、户管/普通用户一律 403；④ **新增「手动修改定时周期」的接口与界面**（管理员可改，改完 **30 秒内生效、无需重启**）。⚠️ **本版把 §8.5 的 Java 骨架实质推翻**：原骨架用 `@Scheduled(cron=...)` **固定 cron**，表达不了「运行时可配置的周期」—— 正解是**每 30 秒醒一次的 tick 循环 + 每 tick 重读配置**（见 §8.5 与附录 K）。⚠️ 新增两个 `config` key：`scheduler_config`（管理员意图）与 **`scheduler_last_run_{task_key}`（一个任务一个 key，运行事实）**，两者分开是为了避开读改写竞争
> **v1.34 变更**: **TT 备注（`remark`）跨看板同步优先级**（对应 `py/huguan_dashboard.py`、`py/routes/huguan_dashboard_routes.py`、`py/routes/tt_accounts_routes.py`、`frontend/src/views/tt/TtAccountPanel.vue`，详见**附录 J**）——`tt_accounts.remark` 被**两张 Google 表同时读写**（投手「我的看板」`J` 列 / 户管看板 `M` 列），两边都 `writable=True`+`readable=True`，谁后同步谁赢；叠加「文本列空值照常落库」的口径 ⇒ **户管 `M` 列空着就会把投手填的备注清掉**。本次定下优先级：**首次入库**（户管触发）时投手 `J` 列**有值则投手赢**（覆盖系统 + 回写户管 `M`）、空则户管赢（推给投手 `J`）；**此后投手权威永久**，户管改 `M` 列**不再进系统**；投手在系统内联编辑备注则推**两张表**。实现上**零新增状态**——权威判定天然映射到 `build_diff` 的 `to_create`/`to_update` 两个分支，只需给 `to_update` 的字段过滤追加 `and not (platform == "tt" and k == "remark")`；⚠️ **不得**把 `remark` 从 `_PLAIN_TEXT_FIELDS["tt"]` 删掉（该清单被 `to_create` 与 `to_update` **共用**，删掉会让「首次入库读户管 `M` 列」失效）。**附带发现并补建了一条此前根本不存在的通路**：所有推送都走 `push_rows(user_id,...)`（取 `huguan_dashboard_{uid}` 配置），而投手没有该键 ⇒ `sync_from_sheet` 结尾的 `hd.writeback_rows(uid,...)` **对投手一直是静默空转**；本次新建 `push_remark_to_operator_dashboard(owner_id, account_id, value)` 面向投手看板，⚠️ **投手看板的账户ID在 `D` 列**（户管在 `C` 列），调 `update_rows_by_account_id` **必须显式传 `key_col="D"`**，漏传会默认 `"C"` 并**静默定位到错误的行**。**只改 `remark` 一个字段；仅 TT；不新增表、不新增数据库列**。前端在「消耗情况」列后加**可内联编辑**的「备注」列（复用既有 `.inline-*` 惯例，失败不回写 `row.remark` 即天然回滚）。⚠️ **本版一并补录了 TT「我的看板」（10 列）的完整列模型与同步契约**（此前只在 6.3 一句带过，且极易与 GG 的同名 8 列表混同）—— 见 **§8.1「我的看板是两张不同的表」**
> **v1.33 变更**: **TT「换绑情况」列改造：归属变更通道 → 换绑记录字段**（对应 `py/database.py`、`py/huguan_dashboard.py`、`py/routes/huguan_dashboard_routes.py`、`py/routes/tt_accounts_routes.py`、`frontend/src/views/tt/TtAccountPanel.vue`，详见**附录 I**）——**这是改需求、不是 bug 修复**：v1.31 定下的「变更通道列（TT「换绑情况」）非空则压过运营列」（用户当时的原话，见 `2026-09-23-huguan-sheet-design.md:35`）**被用户 2026-10-06 裁定取消**。新语义：① TT 归属**恒取**「接户运营」`G` 列，`effective_owner_name(parsed, platform)` 按平台分叉，⚠️ **`platform` 必须是必填位置参数、不得给默认值**（默认值会让漏传的 TT 调用方静默拿到 GG 语义）；② `L` 列由合成字段 `_owner_channel` 改为**真实列** `owner_change_note`（普通文本、`writable=False`/`readable=True`），**DDL 新增一列**（已在 §5.2 同步，**无数据迁移动作**）；⚠️ `tt_accounts` 此前**没有任何** `_add_column_if_missing` 迁移记录，而生产库已存在 ⇒ `CREATE TABLE IF NOT EXISTS` **不生效**，**建表语句与迁移条目两处都要加**；③ 系统 UI 改归属时写 `旧归属人转新归属人+月.日`（如 `阿轩转黎明10.7`，**月日不补零**、旧归属解析不到写 `未分配`，⚠️ **不得**用 `strftime("%-m")`——Windows 不支持；⚠️ `display_name` 仅含空白时是 truthy 会顶掉 `or` 兜底 ⇒ 必须**先 strip 再 or**），且**同时落库** `owner_change_note`，两处同一份文本；④ **同步后的「清空变更通道列」（§7.9 规则 3②）改为 GG-only** —— 对 TT 执行会抹掉记录，且因读回按表覆盖会**连带清掉系统值**（双重抹除）；⑤ 前端加**只读**「换绑情况」列（仅户管可见）。**仅 TT**：GG 的「重新分配」（`H` 列）与 §7.9 的四条规则**逐字不变**（§7.9 已就地标注 TT 侧的作废范围）
> **v1.32 变更**: **TT 广告账户列表不再展示「账户名称」列**（纯前端 `frontend/src/views/tt/TtAccountPanel.vue`，后端与数据库**零改动**，详见附录 H）——该列此前是 TT 账户名**唯一的内联编辑入口**（hover ✏️ → `<el-input>` → `ttAccountsApi.update(row.id, { name })`）。用户 2026-10-06 裁定 TT 列表无需展示账户名，本次删除该列，并同步清掉**专为该列存在**的状态与函数（`editingNameId` / `editNameValue` / `nameInputRef` 与 `startEditName` / `cancelNameEdit` / `saveName`，已核零残留引用；`nextTick`、`.inline-name-input`、`.inline-edit-btn` 仍被国家/消耗等其他内联编辑使用，**未删**）。**改名能力未丢失**：行尾 ✏️ 打开的 `TtAccountModal` 中「账户名称」仍是必填字段（新增与编辑共用该弹窗）。**仅 TT 改动**：GG（`AdsAccountPanel.vue`，见附录 E.1）与 FB（`FbAccountPanel.vue` 的「账户名」列）**保持原样**。**搜索框存在一处刻意的不一致，交接/迁移时勿「顺手修正」**：placeholder 由「🔍 搜索名称/广告账户 ID...」改为「🔍 搜索广告账户 ID...」，但后端 `GET /api/tt/accounts/list` 内**两处** search 条件 `(a.name LIKE ? OR a.advertiser_id LIKE ?)`（主列表 `tt_accounts_routes.py:224`、各状态计数 `:269`）**一律未改**——账户名只是不在列表里显示，按名搜索的通道仍然保留（用户明确选择「只改 placeholder 文案」）。`tt_accounts.name` 字段、DDL、接口契约均未动，**不存在数据迁移动作**。**Spring 侧无需任何改动**（本文档前提是前端不变、仅替换后端 API 层）
> **v1.31 变更**: **户管角色（户管线）整体补录**——新增 `huguan` 角色、用户权限按角色收窄、以及「户管看板」Google Sheet 双向同步。权威设计见 `2026-09-22-huguan-role-design.md`（角色与权限）、`2026-09-23-huguan-sheet-design.md`（看板双向同步）、`2026-09-24-huguan-owner-source-and-picker-design.md`（归属变更「来源」标注）、`2026-09-24-huguan-frontend-visual-design.md`（前端视觉）；Java 侧重建要点见 §7.9，Controller 见 6.3，Sheets 方法见 8.1。**① 角色与三个角色集合常量**：`py/routes/helpers.py` 集中定义 `CROSS_USER_ROLES = ("developer","admin","huguan")`（可跨用户看数据）、`GLOBAL_OPTION_ROLES = ("developer","admin","huguan")`（可改全局选项/字典表，两者当前同值但**语义不同、不得合并**）、`PLATFORM_SWITCH_ROLES = ("developer","huguan")`（可切平台命名空间，**admin 刻意不在其中**——管理员自 v1.28 起按平台隔离，见 7.7）；`py/routes/decorators.py` 新增 `@huguan_required`，语义是**严格** `role == "huguan"`（admin/developer 一律 403 `权限不足，仅户管可操作`），因为户管看板是户管的**个人**配置，不是管理功能。**② 本版更正 §7.7.4 的衔接点预测**：v1.28 当时写「`_get_effective_platform` 的 `role == 'developer'` 计划改为 `CROSS_USER_ROLES`」，实际落地用的是 **`PLATFORM_SWITCH_ROLES`**（`main.py:6364`）——若真按 CROSS_USER_ROLES 改，admin 会被重新放回「跨平台取 `request.args['platform']`」分支，v1.28 刚修掉的「FB 管理员看到 GG 选项」缺陷当场复发。**这两个集合不可互换**，7.7.2 的 `isCrossPlatform()` 已据此拆成两个谓词。**③ 用户管理按户管收窄**（不改 administrator 既有行为）：`main.py:_check_modify_user` 在 developer 短路之后、角色层级与平台判断**之前**插入户管分支——目标角色必须是 `huguan`（否则 `户管只能操作户管账号`）**且** `target.created_by == actor.id`（否则 `只能操作自己创建的户管`）；户管**不受平台维度约束**（户管本身跨平台）。配套：`ALLOWED_CREATE_ROLES = {developer:(user,admin,viewer,huguan), admin:(user,admin,viewer), huguan:(huguan,)}`，创建用户时户管**忽略请求体 role 并强制写成 `huguan`**，改角色白名单收为 `("huguan","hidden")`；用户列表的角色过滤**不在 `auth.list_users` 内部**，而在路由层（`role_filter = "huguan" if user["role"] == "huguan" else None`），`list_users` 内部只负责「户管跳过平台过滤」。**迁移时两处都要照搬**，只改一处会漏掉一种越权。**④ 户管看板双向同步**：配置存 `config` 表键 `huguan_dashboard_{uid}`，**按平台各一份**（`PLATFORMS = ("gg","tt")`；**FB 不支持**）；GG 14 列 / TT 13 列，系统只写其中一部分（GG 实际自动写 `A:D`+`F:G`+`I:K`、TT 实际自动写 `A:J`+`M:M`），**其余列由户管自己用公式维护**，靠 `update_rows_by_account_id` 的**区间合并**（只有相邻列并成区间、空洞处断开）保证「没出现在 `cells` 里的列绝不被写到」——这是公式列保命的唯一机制，**不得**用「整行覆盖」实现。归属字段**不新增数据库列**，直接复用 `accounts.owner_id` / `tt_accounts.owner_id`（可空）。**⑤ 归属变更协议四条硬规则**（⚠️ **v1.33 起规则 1 与规则 3 的 TT 部分已作废 —— 见附录 I；GG 部分逐字不变**）：变更通道列（GG「重新分配」/ TT「换绑情况」）的值**优先于**运营列（**仅 GG**）；**自动回写永不碰变更通道列**；变更通道列只有**两个**写入点（户管在系统 UI 改归属 ⇒ 写新名字；「从表同步到系统」成功 ⇒ 清空为 `""`）；应用归属变更后必须**回写运营列**为新归属人名，让两列重新一致。名字→`owner_id` 走「`display_name` 精确匹配、回落 `username`，命中 0 或 ≥2 均只告警、不写归属」（唯一命中才写）。**⑥ 表→系统同步的差异契约**：`POST /api/huguan/dashboard/sync` 返回五类差异（`to_create`/`to_update`/`owner_changes`/`to_skip`/`warnings`），表内**空值即清空**系统列（`to_update` 每条带 `clears`，`summary` 带 `clears` 计数），确认绑定**按 account_id 而非行号**，`not_applied` 防静默丢弃；`dry_run` 为**fail-safe**——**只有显式布尔 `false` 才落库**（缺省 / `true` / `null` / 字符串 `"false"` / `0` 全部只读），漏掉这个 `is not False` 会让「传个空值就把库改了」；表地址**只从该户管自己的配置取，请求体不接受表地址**（归属门禁不复用，因为复用等于给了「对着别人的表发起同步」这条路）。**⑦ 本轮终审修复**：`update_rows_by_account_id` 由「每行一次 `values().batchUpdate`」改为**整批一次调用**——Google 的单次 `batchUpdate` 请求是**原子**的，「配额撞车导致前几行已落表」的半写与「几百行 = 几百次请求」的请求数爆炸一并解掉，失败文案随之从「表已部分写入、无回滚」改为**「本次已写入 0 行」**，前端用户可见文案同步为**「刷新到看板失败。本次没有写入任何数据，直接重试是安全的。」**（`HuguanDashboardCard.vue:687` 与 `2026-09-24-huguan-frontend-visual-design.md` §195/§1005），后端异常消息里带本次涉及的 `account_id` 便于定位。**迁移红线**：区间合并语义、`dry_run` 的 fail-safe、归属回写顺序、`@huguan_required` 的严格性，四项均须原样重建；**不要**把户管并入 `admin`（两者权限模型不同），**不要**把 `CROSS_USER_ROLES` 与 `PLATFORM_SWITCH_ROLES` 合并成一个集合
> **v1.30 变更**: **爬取产物归属校验：目录名认领判据加时间维度**（对应 `py/auth.py` 的 `directory_name_error` / `_dn_released_keys` / `_dir_ctime` / `_release_row_covers_dir` / `_sentinel_row_blocks_dir` 与 `py/database.py` 的 `_migrate_scrape_dn_history`）——这套判据来自 2026-09-23「全站鉴权加固」与 2026-09-24「下载签名按需签发 + scrape 产物归属校验」，**此前未录入本文档**，v1.30 随本轮换判据一并补录（权威说明见 `2026-09-24-ondemand-download-signing-design.md` §0.9–§0.13，Java 侧重建要点见 §7.8、缺表 DDL 见 §5.2）。背景：`temp/scraped_images/<目录名>` 下是各用户的爬取产物，目录名由用户名派生、磁盘上**没有 owner 记录**，归属只能靠「目录名判据」+ 一张墓碑表 `scrape_dn_history`（无外键、刻意不进删用户清理）反推。原判据只答「谁曾用过这个名字」（last-writer-wins），挡不住「行过期、但序号最大」的形态（迁移搬来的行、admin 用 `requested_dn` 代管建出的目录、记录缺失类故障）。本轮换成**带时间维度**的判据：① **释放行须晚于目录创建时刻**才参与比较（`created_at > 目录 ctime`），自己与他人**两侧一起**过滤——于是「上线前已改名者的旧目录认领路」恢复（他的旧行晚于旧目录，仍算数），而「每周清理后旧释放行认领新目录」被挡住；② **拿不到化身**（目录不存在 / 越界 / `stat` 失败）或**时刻解析不出**（脏行）时，释放行**不过滤**、哨兵**照拦**（两侧都取严侧，fail-closed）；③ **哨兵改按「化身」生效**：`user_id = 0` 的哨兵行只拦它写下时**已存在**的那个目录（`ts >= ctime`），目录在其后**重建**则旧哨兵失效（否则本人的认领路会被永久封死）；哨兵不参与 LWW 序号比较（独立 `blocked` 集合）。同时**退役**「无主目录扫盘补墓碑」整段（`database._tombstone_orphan_scrape_dirs` 删除）——它是上一轮的兜底，换判据后不再需要，无主目录仍由「判据 3：目录占用」接住。④ **亚秒不变式（本轮修的真实缺陷）**：`scrape_dn_history.created_at` 的表默认值 `datetime('now')` **只到秒**，同一个截断方向对**释放行**是 fail-closed（`ts > ctime` 更难成立）、对**哨兵**却是 **fail-open**（`ts >= ctime` 更难成立 ⇒ 拦不住它当年所判的化身），「同一秒内先建目录、后跑迁移」会把歧义名悄悄放开。故**任何**写该表的代码都必须显式带亚秒（`strftime('%Y-%m-%d %H:%M:%f','now')`）；迁移的哨兵写入口曾漏此条，已修并补效果级用例（code-review 第 7 轮 Important #1）。⑤ 时刻列是 **UTC**，解析须用 `calendar.timegm` 而非本地解析（用 `mktime` 会整体偏一个时区）；SQLite `now` 与文件系统时钟之间存在毫秒级抖动且**跨零**，故两侧判据都不能省掉亚秒精度。**迁移红线**：Spring 侧必须在**服务层**原样重建这套判据与墓碑表，**不得**改成按 `users` 外键推导归属；`scrape_dn_history` **不得**建 `UNIQUE(dn)`、**不得**加外键、**不得**在删用户时清理；时间列精度至少毫秒且按 UTC 存
> **v1.29 变更**: **回收原因改为全平台公用词表**（对应 `py/routes/tt_accounts_routes.py` 的四个 `recycle-reasons` 接口、`py/database.py` 的 `_ensure_columns`、前端 `frontend/src/views/tt/TtSettingsPanel.vue`）——此前 `GET /api/tt/recycle-reasons/list` **无角色拦截**（仅 `@jwt_required() @tt_required`）却按 `owner_id` 做数据隔离：`role in CROSS_USER_ROLES`（developer/admin/huguan）看全量，其余**仅本人**。但该词表在前端是「TT设置 → ♻️回收原因选项」卡片集中维护的**共享词表**，设计意图与实现不一致 → admin 建的原因普通用户下拉框恒为空（实测：库中 3 条原因 `owner_id` 全为 admin uid=23，以普通用户 uid 查询返回 `[]`），且状态变更弹窗在用户手输时会自动 `create` 一条**归自己的同名记录**，产生跨 owner 重名脏数据。同一功能本已有两条**作用域互相矛盾**的写入路径：API 路径按 `(name, owner_id)` 去重，而 `_trigger_recycle_if_dead` 走 `WHERE name=?` **全局**去重 + `INSERT OR IGNORE`。本次统一为公用语义：① `list` 删掉角色分支，所有 TT 用户（含 viewer）读全表；② `create` 去重条件 `(name, owner_id)` → 全局 `name`，`owner_id` 仅记录创建者、**不再参与鉴权**，并加 `sqlite3.IntegrityError` 兜底返回 409（防并发撞唯一索引变 500）；③ `rename`/`delete` 删掉 owner 检查，`rename` 新增全局重名检查（改到已存在名称返回 409、原值不变，前端已消费 `error` 字段）；④ `py/database.py` 的 `_ensure_columns` 新增 `CREATE UNIQUE INDEX IF NOT EXISTS idx_tt_recycle_reasons_name ON tt_recycle_reasons(name)`，**带重名防御**：存量若有重名则跳过建索引，避免唯一索引创建失败导致每次连库都抛异常；⑤ 前端把「♻️ 回收原因选项」卡片移出管理员专属 `<template v-if>`，改用 `visibleOptionCards` 计算属性按角色过滤——回收原因对所有 TT 用户可见可改，「代理名选项」「账户状态选项」仍管理员专属（管理员渲染结果逐位不变）。**权限边界**：viewer 保持只读，`@tt_write_required` 未改（可读、不可增改删）。**迁移要点**：Spring 侧回收原因不得再按 owner 过滤，`name` 唯一约束必须是**全局唯一**而非 `UNIQUE(name, owner_id)`，详见 6.3
> **v1.28 变更**: **用户管理的平台隔离**——此前 `admin` 是**全局角色**：任何管理员都能看到并操作全部平台的用户，创建用户时非 developer 一律被强制写成 `platform='gg'`（把 TT/FB 管理员建的用户错误塞进 GG）。本次把 `admin` 从全局改为**按平台隔离**，`developer` 短路豁免。涉及：① `auth.list_users` 非 developer 强制 `platform = 自己的平台` 且不返回 developer 行（**忽略传入的 `platform` 参数**；无 `current_user_id` 的内部调用保持原行为不变）；② `admin_create_user` 非 developer 的 `platform` 锁定为创建者自己的平台（非法存量值兜底 `gg`），前端平台下拉框仅 developer 可见；③ 新增 `_check_modify_user(actor, target)` 返回**拒绝原因字符串**（`不能操作同级管理员` / `不能操作其他平台的用户`），替换原布尔 `_can_modify_user`，被 `role`/`toggle`/`delete`/`update`/`password`/`telegram` **六个**用户操作接口复用；④ 新增 `_can_access_user_data(actor, target)` 约束数据导入/导出（不限制目标角色，仅平台）；⑤ **`_get_effective_platform()` 语义修正**：原判断 `role in ('developer','admin')` 时取 `request.args.get('platform','gg')`，实际只有 developer 会被前端注入 platform，导致**非 developer 管理员落到 GG 命名空间**（TT 页面因显式传参侥幸正确，FB 页面不传参 → FB 管理员看到 GG 的商务人员/账户状态选项），现改为仅 `role == 'developer'` 跨平台；⑥ 前端 `UserManageView.vue` 平台 Tab 按身份条件渲染 + 创建弹窗平台字段仅 developer 可见 + 身份时序修正（见 7.7）。**迁移要点**：`@AdminRequired` 不再等价于跨平台权限，Spring 侧必须补平台维度的校验，详见 7.7
> **v1.27 变更**: TT 设置「Google Sheets」区块权限展示修复（纯前端 `frontend/src/views/tt/TtSettingsPanel.vue`，后端无改动）——此前「Google Sheets URL 输入框 + 📋读取工作表 按钮」整块用 `v-if="isAdmin"` 包裹，投手（普通角色）看不到「读取工作表」按钮、无法加载 sheet 列表给「我的看板」选表。现改为：①「📋读取工作表」按钮对**所有登录用户**开放（投手可点，读的是管理员已配置的全局 `tt_sheet_id`，接口 `GET /api/google-sheets/sheets` 仅 `@jwt_required`、无角色限制）；② `sheet_id` 输入框内容**仅管理员可改**（投手侧 `:disabled` 只读显示管理员已配置的 ID，并加「仅管理员可改」标签）；③ 投手点「保存」提交的 `sheet_id` 被后端 `tt_settings_save` 忽略（`is_admin` 判断），仅写私有 `my_dashboard` 到 config 表 `tt_sheet_mappings_<uid>`。迁移到 Spring Boot 时前端需保持「读取开放、sheet_id 写仅管理员」的展示与后端权限边界一致
> **v1.26 变更**: TT 账户「回收户清单」写表（对应 `py/google_sheets_service.py` 的 `append_recycle` 与 `py/routes/tt_accounts_routes.py` 的 `_trigger_recycle_if_dead`/`_maybe_write_recycle`）——账户状态更新为「非存活」（`!= 存活`，即 验证/封禁/死亡 等）且携带 `recycle_reason` 时，后台异步写「回收户清单」Sheet。该表 12 列表头（时间/账户ID/渠道/运营/国家/时区/有无消耗/回收原因/是否提交/清零金额/备注/是否二次提交），系统**只写 A(时间)/B(账户ID)/H(回收原因) 三列**，其余 C~L 列（渠道/运营/国家/时区/有无消耗/是否提交/清零金额/备注/是否二次提交）在表格里已有公式、**不得覆盖**。写入规则：① A 列时间自动写当天日期、格式「年-月-日」（如 `2026-09-22`），带前导 `'` 标记为文本；② B 列账户ID 带前导 `'` 标记为文本（防 13 位纯数字变科学计数）；③ H 列写回收原因；④ **判断最后一行（换行）只看 B 列「账户ID」有无数据**，时间列（A）有残留但账户ID为空的行忽略（与充值表 `append_recharge_tt` 一致）。回收原因由前端弹窗可搜索下拉选择（`recycle_reason` 字段），后端 `_trigger_recycle_if_dead` 若该原因不在 `tt_recycle_reasons` 表则自动 INSERT（owner_id=当前用户）；配套回收原因 CRUD 接口 `GET/POST/PUT/DELETE /api/tt/recycle-reasons/*`（**v1.29 起改为全平台公用词表，此处「owner 隔离，admin/developer 看全量」的描述已作废**，见下方 v1.29 变更）。迁移到 Spring Boot 时 `GoogleSheetsService` 需提供回收写表方法：只写 A/B/H、保留 C~L 公式、以「账户ID」列判断追加行号、时间「年-月-日」+前导 `'`、账户ID 前导 `'`
> **v1.25 变更**: TT 账户充值写表适配（对应 `py/google_sheets_service.py` 的 `append_recharge_tt` 与 `py/routes/tt_accounts_routes.py` 的 `_append_recharge_background`）——TT 充值表表头为 9 列（时间/账户ID/金额/代理/运营/是否充值/账户ID/金额锁定/是否处理），系统**只写前 3 列**（时间/账户ID/金额），D~I 列（代理/运营/是否充值/账户ID/金额锁定/是否处理）在表格里已有公式、**不得覆盖**。写入规则：① A 列时间自动写当前日期、格式「月/日」（如 `9/22`），带前导 `'` 标记为文本（防止被解析为日期）；② B 列账户ID 带前导 `'` 标记为文本（防止 13 位纯数字变科学计数）；③ C 列金额写 `float` 数字（供 D~I 列公式计算）；④ **判断最后一行（换行）只看 B 列「账户ID」有无数据**，时间/金额列有残留但账户ID为空的行忽略。GG 的 `append_recharge` 保持不动（纯增量），TT 路由 `_append_recharge_background._do_sync` 改调 `append_recharge_tt`（submit/batch-submit/retry-sheets 三处共用）。迁移到 Spring Boot 时 `GoogleSheetsService`（或 `TtAccountService`）需提供 TT 专用充值写表方法：只写 A~C、保留 D~I 公式、以「账户ID」列判断追加行号
> **v1.24 变更**: TT 账户「我的看板」同步新增「是否回收」列驱动账户状态（对应 `py/routes/tt_accounts_routes.py` 的 `sync_from_sheet`）——① C 列「是否回收」推导状态：「是」→「死亡」、「可用」/空 →「存活」；② 新户直接导入并写 `status_id`（死亡户同时写 `death_date`）；③ 已存在账户做状态比对（C 列推导 vs 系统 `status_name`，NULL 视为「存活」），不一致时返回 `status_conflicts`（`{advertiser_id, sheet_status, system_status}`）由前端提示用户确认、不自动改；④ 确认模式新增 `status_resolutions`（`{advertiser_id: "存活"|"死亡"}`），更新 `status_id`/`status_changed_date`/`death_date`（死亡置当天、存活清空，与手动改状态一致）；⑤ 越权保护：`status_resolutions`/`resolutions` 仅允许改当前用户看板行内（A 列「运营」匹配 display_name）的 `advertiser_id`，非 admin/developer 带 `owner_id` 条件；⑥ 状态同步**不触发** `_trigger_recycle_if_dead`（回收户清单是上游，同步只反映状态、不写清单）。本次一并修复：看板同步跳过表头第一行（避免「运营」表头误触发门禁）+ 按列 `len(r)>N` 安全取值（Google Sheets 截断尾部空列，避免 IndexError）。迁移到 Spring Boot 时 TtAccountService.syncFromSheet 需保持上述状态比对/冲突确认契约与越权保护，且状态变更路径不得触发回收清单写入
> **v1.23 变更**: TT 设置界面最终实现细化（对应 `py/routes/tt_routes.py` 的 `/api/tt/settings`、`/api/tt/data/export`、`/api/tt/data/import` 与 `main.py` 的 `sales_persons_delete`）——① TT 数据导出按 owner_id 隔离（`tt_bcs`/`tt_products` 过滤 owner，packages/runners/delist_checks 由所属产品/包推导，`sales_persons` 导出 `platform='tt'` 全量供导入映射）；② TT 数据导入按外键依赖顺序重建（sales_persons→bcs→products→packages→runners→delist_checks）并建 old_id→new_id 映射，`owner_id`/`runners.user_id` 全部重映射为当前导入用户，BC 优先复用本人否则按全局唯一 `bc_id` 复用，商务按 name 匹配/新建；③ 导入加 JSON 结构强校验（非 dict 元素/缺 id 跳过）+ 事务 rollback（失败返回 400 不落半截数据）+ 20MB 上传上限；④ 前端商务/地区复用端点显式传 `platform=tt`，修复 admin（非 developer）平台回退 gg 的问题
> **v1.22 变更**: 补充 TT（TikTok Ads）平台完整迁移设计——此前文档仅覆盖 GG+FB。新增 6 张 TT 表 MySQL DDL（`tt_bcs`/`tt_products`/`tt_product_runners`/`tt_packages`/`tt_delist_checks`/`tt_product_assets`，详见 5.2）与 `TtController`（28 个接口，详见 6.3），并新增 TT 设置界面（`/api/tt/settings` GET/POST，存全局 tags `tt_sheet_id`/`tt_sheet_mappings`，供后续 TT 账户管理读取 Google 表格）与 TT 数据导出/导入（`/api/tt/data/export`/`/api/tt/data/import`）。另在 `sales_persons_delete` 补 `tt_products` 引用检查（原只查 GG `products` 与 FB `fb_products`，删除被 TT 产品引用的商务人员会悬空引用）
> **v1.21 变更**: 做表数据与 MCC 管理三处前端修复/增强（均纯前端，后端无改动）——① 做表数据「包含广告系列ID」与「7列数据」两个勾选项此前互斥（`zbIncludeCampaignId` 被 `:disabled="zbSevenCols"` 禁用），现改为可同时勾选，`adsParser.js` 增加「7列 + 含广告系列ID = 8列」组合（step=8、指标列整体后移1位、第5列广告系列ID自动剔除）；② MCC 新增/编辑弹窗「等级」下拉框此前依赖设置页 `loadMccLevels()` 才填充、直接进 MCC 面板为空，改为 `MccModal.vue` `init()` 懒加载（`if (!store.options.mccLevels.length) await store.loadMccLevels()`），并将「上级 MCC」下拉框加 `filterable` 支持搜索；③ 做表数据日期 `zbSelectedDate` 此前仅在组件初始化时算一次「昨天」、跨天后不更新导致覆盖到错误日期，新增 `scheduleZbMidnightRefresh()` 定时器在 0 点后自动更新为新「昨天」并递归调度到下一 0 点
> **v1.20 变更**: 做表数据「养户」与「7列」判定解耦——前端 `ToolkitView.vue` 做表数据 Tab 的 `is_yanghu` 此前由 `zbYanghu（勾选7列）|| 命中养户关键词` 决定，导致勾选「7列（无安装/应用指标）」时所有行被误判为养户（G列写「养户」、H列写「止戈」、L列写「0%」，且不入库）。现改为**仅按系列名（campaign）命中养户关键词判定**：变量 `zbYanghu`→`zbSevenCols`（表示7列数据格式）、`adsParser.js` 参数 `isYanghu`→`isSevenCols`、勾选项文案改为「7列数据（无安装/应用指标）」。副作用：7 列非养户行现在会入库 `ad_reports`，因 7 列解析不含 `installs/in_app_actions/cost_per_in_app` 三字段，入库时按 0 写入（覆盖旧值）。后端接口契约不变（`is_yanghu` 仍由前端传入，详见 6.2 说明）
> **v1.19 变更**: 掉包检测改为走代理 IP 访问 Google Play 链接（不再用服务端自身 IP，避免被风控/限流）。新增 `py/proxy_pool.py` 代理池模块（随机取用 + 失败自动切换下一个代理 + `enabled` 开关 + `max_retries` 重试）；`config/config.json` 新增 `delist_proxy` 段；`check_url_delisted` / `check_product_packages` 增加可选 `proxy_pool` 参数（缺省直连，向后兼容）；定时任务与手动检测均接入。迁移到 Spring Boot 时 DelistChecker 需支持代理池访问（详见 6.3、8.5 说明）
> **v1.18 变更**: 修复静态资源请求 500 导致前端路由跳转不过去（两层根因叠加）——① `_attach_db`（`before_request`）此前对每个请求无条件调用 `database.get_db()` 打开数据库连接并执行迁移，静态资源请求（`/assets/*.js`）也被波及；当数据库被占用（掉包检测定时任务写库）时，静态资源请求抛 `sqlite3.OperationalError: database is locked` → 500。② `_add_static_cache`（`after_request`）未判断响应状态码，给 500 错误响应也加了 `Cache-Control: max-age=31536000`，浏览器把一次性 500 缓存 1 年——即使服务端已恢复该浏览器仍持续加载失败（表现为换浏览器就好、本机正常）。修复：`_attach_db` 对非 `/api/` 请求直接跳过、不打开数据库；`_add_static_cache` 对 `status_code >= 400` 的错误响应直接跳过、不缓存。迁移到 Spring Boot 时：①请求入口的数据库连接绑定/上下文初始化（Filter、Interceptor、`@RequestScope` 等）应只对 API 请求生效，静态资源与页面请求不得触发任何数据库访问；②静态资源缓存策略（`Cache-Control` / `CacheWebFilter` 等）必须对错误响应禁用缓存
> **v1.17 变更**: 修复手动执行掉包检测时 500 报错（sqlite3.OperationalError: database is locked）。根因是两处 SQLite 并发写锁叠加——① `_migrate_if_needed` 的两个迁移 claim 标记（`migrated_videos_composite_pk` / `migrated_fk_rebuild_after_composite_pk`）用无条件 `INSERT OR IGNORE`，导致每个请求（含前端高频轮询 `/api/delist/pending`）都要抢写锁；② `_run_delist_check_once` 在并行 HTTP 检测循环内边检测边 `INSERT OR REPLACE` 写 `delist_checks`、直到整个网络检测结束才 commit，写锁被占用数分钟。修复：掉包检测改为先收集全部结果、循环结束后统一写库（写锁只占用纯 DB 循环的极短时间）；两个 claim 标记改为先 SELECT 判断、仅首次（标记缺失）才写。迁移到 Spring Boot 时 DelistService 检测任务同样应「先聚合结果、后批量写」，避免在长网络调用期间持有事务/行锁（详见 6.3 说明）
> **v1.16 变更**: 产品管理列表吸顶交互——展开产品后「产品头部」滚动到列表区顶部即吸顶（`position: sticky`），包滚完才释放、往回滚自动重新钉住；「包筛选工具栏」移入产品头部 header 内、随头部一起吸顶固定。纯 CSS + DOM 移动，无后端改动（详见附录 G）
> **v1.15 变更**: 产品包列表多选后新增「取消选择」按钮——工具栏「已选 N 个」旁新增「✕ 取消选择」按钮（选中任意包后显示），点击一键清空已选并重置 Shift 锚点，补齐「部分选择时无清空入口」的缺口（纯前端，详见附录 F）
> **v1.13 变更**: 修复「暂停/删除产品仍弹掉包通知」——`delist/pending` 与 `products/delist-status` 两个查询此前只过滤 `pkg.status`（包状态）、漏过滤 `prod.status`（产品状态），导致产品暂停/删除后前端仍反复弹掉包通知（首次 + 3 分钟提醒循环）。两处查询补 `AND (prod.status IS NULL OR prod.status='' OR prod.status='0')`，与定时检测 `_run_delist_check_once` 保持一致。迁移到 Spring Boot 时，DelistService 查询通知/掉包状态的 SQL 必须同时过滤包状态与产品状态（详见 6.3 说明）
> **v1.14 变更**: FB 数据提取动态分组补充「短纯数字作为组起点」判断——账户名可能是短纯数字（如 `100M$` 被识别为文本、但某些账户名是 <10 位纯数字），此前分组条件只认「文本行 + 下一行 ≥10 位账户 ID」，会漏掉以短数字开头的账户。现分组起点改为 `(is_text_header OR is_short_number) AND next_is_account_id`，其中 `is_short_number = 纯数字且去逗号后 <10 位`。详见 8.2 节 `parseExtract` 动态分组实现
> **v1.12 变更**: 修复产品包列表勾选框视觉不同步 bug 并补充 Shift 范围取消——checkbox 由 `@click.stop.prevent` 改为 `@mousedown`（记录 Shift）+ `@change`（处理切换），解决「状态已更新但勾选框视觉不同步、再次点击取消不了」的问题；Shift 范围选择由「只追加勾选」改为按目标状态统一设置（支持选中/取消）。详见附录 F
> **v1.11 变更**: 修复 Python SQLite 端全新数据库建库崩溃的两个 bug——① `_ensure_schema` 中 `idx_products_archived` 索引先于 `is_archived` 列创建（该列由 `_ensure_columns` 补），删除该冗余索引；② `_migrate_options_tables` 的 guard 用「agent_id 非 NULL 记录数」判断迁移状态，空表时失效导致重复迁移报 `no such column: agent`，改为迁移前先检查旧 `agent` 列是否存在。迁移到 MySQL 时注意：DDL 索引不得先于列定义；数据迁移 guard 应用明确的迁移标记（config/版本表）而非记录数判断
> **v1.10 变更**: 掉包通知按产品聚合——`delist/pending` 返回产品聚合结构、`delist/dismiss` 接受 `package_ids[]`、Telegram 通知改为产品级（产品名 + 多系列名，不展示包名/链接）；前端弹窗按产品统一为一条（详见 6.3 说明）
> **v1.9 变更**: 补充 `GoogleSheetsController` 的 `update-zuobiao` 接口产品/包名校验——包系列名与数据广告系列取交集，不匹配且无养户行时报错，有养户行时放行并返回 warning（此前该逻辑在迁移文档中完全缺失）
> **v1.8 变更**: 产品包列表前端交互增强——默认只展示「正常」状态包、状态筛选与排序按钮置于包列表工具栏、Shift 首尾范围选择勾选、按系列名（series_name）排序（降序/升序）+ 恢复默认排序按钮（纯前端，后端无改动，详见附录 F）  
> **v1.7 变更**: 产品创建冲突检测——同名已删除/已暂停产品返回 409 提示恢复（普通用户可恢复，无需管理员确认）；新增 `/api/products/{pid}/restore` 接口；修复 `products_create` 中 sales_person 兼容处理在 db/user_id 初始化前引用的隐患  
> **v1.6 变更**: 账户表格内联编辑扩展（时区/代理/状态）、表格UI整体优化、YouTube标签配置页空白修复  
> **v1.5 变更**: 同步 GG 账户管理最新实现——双向同步（含H列解绑）、软删除/恢复/物理删除、已删除列表  
> **v1.4 变更**: 清账逻辑兜底——改为直接查未清充值记录，不依赖 status_changed_date  
> **v1.3 变更**: FB 数据提取增加回流数据过滤 + $ 金额去重（行数与正常数据一致，仅消耗全为 $0.00）  
> **v1.2 变更**: 确定项目名 LM-Server、包名更新为 com.lmserver  
> **v1.1 变更**: 修正路由计数(226→236)、修正响应格式(items vs data)、修正DDL JSON默认值、新增密码迁移策略、新增前端兼容性矩阵、补充 helpers.py 迁移方案
---

## 目录

1. [项目概述](#1-项目概述)
2. [系统架构对比](#2-系统架构对比)
3. [项目结构设计](#3-项目结构设计)
4. [技术栈与依赖](#4-技术栈与依赖)
5. [数据库设计 — 46 张表 MySQL DDL](#5-数据库设计)
6. [API Controller 设计 — 273 个接口](#6-api-controller-设计)
7. [认证与安全](#7-认证与安全)
8. [业务服务层设计](#8-业务服务层设计)
9. [外部集成](#9-外部集成)
10. [配置管理](#10-配置管理)
11. [部署方案](#11-部署方案)
12. [迁移策略](#12-迁移策略)

---

## 1. 项目概述

### 1.1 现有系统规模

| 维度 | 数量 |
|------|------|
| 后端代码行数 | ~20,000 行 Python |
| API 路由 | **273 个**（v1.31 计入户管看板 5 个；本行按本文档自身清单累加，掉包/TT 苹果包等其他线未并入） |
| 数据库表 | **46 张** |
| 前端页面 | 30 个 Vue 组件 |
| 外部集成 | 10 个（Google Sheets/Ads/AI/FFmpeg/邮件/Telegram 等） |
| 用户角色 | 6 级（developer / admin / huguan / user / viewer / hidden），户管见 7.9 |
| 平台隔离 | 3 个（GG Google Ads / FB Facebook Ads / TT TikTok Ads） |

### 1.2 功能模块清单

| 模块 | 路由数 | 说明 |
|------|--------|------|
| 认证系统 | 12 | 登录、注册、JWT、个人信息、改密 |
| GG 产品管理 | 17 | 产品 CRUD、包管理、在跑人员、掉包检测 |
| GG 账户管理 | 21 | 广告账户 CRUD、MCC 关联、批量操作、Sheet 双向同步、软删除/恢复/物理删除 |
| GG MCC 管理 | 8 | MCC CRUD、关联、详情 |
| GG 充值管理 | 5 | 单个/批量充值、Sheet 写入 |
| GG 广告报告 | 17 | 报告 CRUD、去重、分析、AI 对话、导出 |
| GG YouTube | 16 | 视频导入/列表/编辑/消费追踪、标签管理 |
| GG 文案管理 | 5 | 文案导入/列表/编辑/删除/批量 |
| FB BM 管理 | 7 | BM CRUD、封禁迁移 |
| FB 账户管理 | 8 | 账户 CRUD、BM 关联、软删除/恢复 |
| FB 产品管理 | 10 | 产品 CRUD、线名、在跑人员、BM 关联 |
| FB Pixel BM | 5 | Pixel BM CRUD |
| FB Pixel | 5 | Pixel CRUD、关联 |
| FB 数据提取 | 3 | 解析、去重、保存（异步写 Sheet） |
| FB 报告 | 9 | 报告 CRUD、统计、导出、Sheet 同步/重试 |
| TT BC 管理 | 5 | BC CRUD、选项 |
| TT 产品管理 | 18 | 产品 CRUD、包管理、在跑人员、掉包检测、合并、文本导入、素材 |
| TT 设置 | 4 | Google 表格配置、数据导出/导入（商务/地区复用共享端点） |
| TT 用户 | 1 | TT 平台用户列表（在跑人员下拉） |
| 视频/音频 | 16 | AI 视频生成、FFmpeg 合成、音频替换、历史 |
| 图片抓取 | 5 | Google Play 截图抓取、上传 |
| 字体管理 | 7 | 字体导入/预览/上传 |
| 数据导入导出 | 3 | 用户级导入导出、历史 |
| 管理员 | 11 | 用户管理、数据导入、**定时任务触发（v1.35 起按平台隔离，见附录 K）** |
| 系统配置 | 9 | AI 配置、Sheets 配置、账户设置 |
| 选项数据 | 20 | 代理/状态/MCC等级/商务/地区 CRUD |
| 审计/掉包 | 4 | 审计日志、掉包通知 |
| 工具类 | 5 | 文件浏览、翻译、用户查询 |
| 系统/静态 | 3 | 首页、健康检查 |

---

## 2. 系统架构对比

### 2.1 当前架构 (Python)

```
┌──────────────┐     ┌─────────────────────────────────┐
│  Vue 3 前端   │────▶│  Flask (单文件 main.py 9652行)    │
│  Vite 开发服  │     │  + auth_routes.py (205行)        │
│  Hash Router  │     │  + fb_routes.py (1455行)         │
└──────────────┘     │  + 15个业务模块                    │
                      │  + SQLite (WAL模式)               │
                      │  + Google Sheets/Ads API         │
                      │  + FFmpeg 子进程                  │
                      │  + SMTP / Telegram Bot           │
                      └─────────────────────────────────┘
```

### 2.2 目标架构 (Spring Boot)

```
┌──────────────┐     ┌─────────────────────────────────────────┐
│  Vue 3 前端   │────▶│  Spring Boot 3.x (JDK 17+)              │
│  (不变)       │     │                                         │
│  Vite        │     │  ┌─ Controller 层 (按模块分包)          │
│  baseURL: /api│     │  │  AuthController, FbController,      │
│              │     │  │  AccountController, ProductController │
│              │     │  │  ... (20+ Controller)                │
│              │     │  ├─ Service 层                           │
│              │     │  │  AuthService, SheetsService,          │
│              │     │  │  AdsService, AiService,              │
│              │     │  │  VideoService, EmailService ...      │
│              │     │  ├─ Repository 层 (JPA/MyBatis)         │
│              │     │  ├─ Security (Spring Security + JWT)    │
│              │     │  └─ Config (application.yml)            │
│              │     │                                         │
│              │     │  ┌─ MySQL 8.0                           │
│              │     │  │  连接池: HikariCP (默认)             │
│              │     │  └─ Redis (可选, 缓存/Session)          │
│              │     │                                         │
│              │     │  外部集成:                               │
│              │     │  Google Sheets API (Java SDK)            │
│              │     │  Google Ads API (Java SDK)               │
│              │     │  FFmpeg (ProcessBuilder)                │
│              │     │  SMTP (Spring Mail)                     │
│              │     │  Telegram Bot API (RestTemplate)        │
│              │     │  AI API (RestTemplate)                  │
│              │     └─────────────────────────────────────────┘
└──────────────┘
```

### 2.3 关键差异

| 维度 | Python Flask | Spring Boot |
|------|-------------|-------------|
| 并发模型 | Waitress 40线程 + GIL | 内嵌 Tomcat NIO，真正多线程 |
| 代码组织 | main.py 单文件近万行 | Controller → Service → Repository 三层分离 |
| 数据库 | SQLite (WAL) | MySQL 8.0 (HikariCP 连接池) |
| 认证 | flask-jwt-extended | Spring Security + jjwt |
| 异步 | threading.Thread | @Async + CompletableFuture |
| 定时任务 | daemon Thread + 每 30 秒 tick 重算目标 | `@Scheduled(fixedDelay=30s)` 驱动 tick，**不用 cron**（v1.35） |
| 缓存 | 内存 dict + TTL | Caffeine / Redis |
| 类型安全 | 动态类型 | 编译期检查 |
| 部署 | pyinstaller EXE | java -jar fat JAR |

---

## 3. 项目结构设计

### 3.1 Maven/Gradle 项目结构

```
lm-server/
├── pom.xml (Maven)
├── src/
│   ├── main/
│   │   ├── java/com/lmserver/
│   │   │   ├── LmServerApplication.java          # 启动类
│   │   │   │
│   │   │   ├── config/                            # 配置类
│   │   │   │   ├── SecurityConfig.java            # Spring Security
│   │   │   │   ├── JwtConfig.java                 # JWT 配置
│   │   │   │   ├── WebConfig.java                 # CORS
│   │   │   │   ├── AsyncConfig.java               # 异步线程池
│   │   │   │   ├── CacheConfig.java               # Caffeine 缓存
│   │   │   │   ├── GoogleSheetsConfig.java        # Sheets SDK
│   │   │   │   ├── GoogleAdsConfig.java           # Ads SDK
│   │   │   │   └── MailConfig.java                # 邮件配置
│   │   │   │
│   │   │   ├── security/                          # 安全组件
│   │   │   │   ├── JwtTokenProvider.java          # Token 生成/验证
│   │   │   │   ├── JwtAuthenticationFilter.java   # JWT 过滤器
│   │   │   │   ├── PlatformGuardFilter.java       # GG/FB 平台守卫
│   │   │   │   └── UserPrincipal.java             # 用户主体
│   │   │   │
│   │   │   ├── controller/                        # 控制器 (按模块分包)
│   │   │   │   ├── auth/
│   │   │   │   │   └── AuthController.java        # /api/auth/*
│   │   │   │   ├── fb/
│   │   │   │   │   ├── FbBmController.java        # /api/fb/bms/*
│   │   │   │   │   ├── FbAccountController.java   # /api/fb/accounts/*
│   │   │   │   │   ├── FbProductController.java   # /api/fb/products/*
│   │   │   │   │   ├── FbPixelBmController.java   # /api/fb/pixel-bms/*
│   │   │   │   │   ├── FbPixelController.java     # /api/fb/pixels/*
│   │   │   │   │   ├── FbExtractController.java   # /api/fb/extract/*
│   │   │   │   │   └── FbReportController.java    # /api/fb/reports/*
│   │   │   │   ├── gg/
│   │   │   │   │   ├── ProductController.java     # /api/products/*
│   │   │   │   │   ├── AccountController.java     # /api/accounts/*
│   │   │   │   │   ├── MccController.java         # /api/mcc/*
│   │   │   │   │   ├── RechargeController.java    # /api/recharge/*
│   │   │   │   │   ├── AdReportController.java    # /api/ad-reports/*
│   │   │   │   │   ├── YoutubeController.java     # /api/youtube/*
│   │   │   │   │   └── CopywritingController.java # /api/copywriting/*
│   │   │   │   ├── admin/
│   │   │   │   │   ├── AdminUserController.java   # /api/admin/users/*
│   │   │   │   │   └── AdminDataController.java   # /api/admin/data/*
│   │   │   │   ├── ScrapeController.java          # /api/scrape/*
│   │   │   │   ├── VideoController.java           # /api/video/*
│   │   │   │   ├── FontController.java            # /api/fonts/*
│   │   │   │   ├── ConfigController.java          # /api/config/*
│   │   │   │   ├── SettingsController.java        # /api/settings/*
│   │   │   │   ├── OptionController.java          # /api/agents|statuses|.../*
│   │   │   │   ├── DataController.java            # /api/data/*
│   │   │   │   └── UtilityController.java         # /api/browse|translate/*
│   │   │   │
│   │   │   ├── service/                           # 业务服务层
│   │   │   │   ├── AuthService.java
│   │   │   │   ├── FbService.java                 # FB 平台核心业务
│   │   │   │   ├── AccountService.java            # GG 账户业务
│   │   │   │   ├── ProductService.java            # GG 产品业务
│   │   │   │   ├── MccService.java
│   │   │   │   ├── RechargeService.java
│   │   │   │   ├── AdReportService.java
│   │   │   │   ├── YoutubeService.java
│   │   │   │   ├── CopywritingService.java
│   │   │   │   ├── ScrapeService.java
│   │   │   │   ├── VideoService.java
│   │   │   │   ├── DataImportExportService.java
│   │   │   │   ├── AuditService.java
│   │   │   │   ├── DelistService.java
│   │   │   │   ├── OptionService.java
│   │   │   │   ├── sheets/
│   │   │   │   │   ├── GoogleSheetsService.java   # Sheets 核心读写
│   │   │   │   │   ├── GgSheetsWriter.java        # GG 做表数据写入
│   │   │   │   │   └── FbSheetsWriter.java        # FB 做表数据写入
│   │   │   │   ├── ads/
│   │   │   │   │   └── GoogleAdsService.java      # Google Ads API
│   │   │   │   ├── ai/
│   │   │   │   │   ├── AiVideoService.java        # AI 视频策略接口
│   │   │   │   │   └── impl/                      # 5个Provider实现
│   │   │   │   │       ├── SeedanceProvider.java
│   │   │   │   │       ├── DoubaoProvider.java
│   │   │   │   │       ├── DoubaoFastProvider.java
│   │   │   │   │       ├── VeoProvider.java
│   │   │   │   │       └── AtlasProvider.java
│   │   │   │   ├── notification/
│   │   │   │   │   ├── NotificationService.java   # 接口
│   │   │   │   │   ├── EmailSender.java
│   │   │   │   │   └── TelegramSender.java
│   │   │   │   └── delist/
│   │   │   │       └── DelistChecker.java
│   │   │   │
│   │   │   ├── repository/                        # 数据访问层 (JPA)
│   │   │   │   ├── UserRepository.java
│   │   │   │   ├── AccountRepository.java
│   │   │   │   ├── FbAccountRepository.java
│   │   │   │   ├── FbBmRepository.java
│   │   │   │   ├── FbProductRepository.java
│   │   │   │   ├── FbPixelRepository.java
│   │   │   │   ├── ProductRepository.java
│   │   │   │   ├── MccRepository.java
│   │   │   │   ├── RechargeRecordRepository.java
│   │   │   │   ├── AdReportRepository.java
│   │   │   │   ├── FbAdReportRepository.java
│   │   │   │   ├── VideoRepository.java
│   │   │   │   ├── CopywritingRepository.java
│   │   │   │   ├── AuditLogRepository.java
│   │   │   │   ├── ConfigRepository.java
│   │   │   │   └── ... (46个Repository)
│   │   │   │
│   │   │   ├── entity/                            # JPA 实体 (46个)
│   │   │   │   ├── User.java
│   │   │   │   ├── Account.java
│   │   │   │   ├── FbAccount.java
│   │   │   │   ├── FbBm.java
│   │   │   │   ├── ... (46个Entity)
│   │   │   │
│   │   │   ├── dto/                               # 数据传输对象
│   │   │   │   ├── request/                       # 请求 DTO
│   │   │   │   │   ├── LoginRequest.java
│   │   │   │   │   ├── CreateAccountRequest.java
│   │   │   │   │   ├── SaveExtractRequest.java
│   │   │   │   │   └── ... (按模块分类)
│   │   │   │   └── response/                      # 响应 DTO
│   │   │   │       ├── ApiResponse.java           # 统一响应 {success, data, error}
│   │   │   │       ├── PagedResponse.java         # 分页响应
│   │   │   │       └── ...
│   │   │   │
│   │   │   ├── enums/                             # 枚举
│   │   │   │   ├── UserRole.java                  # developer/admin/viewer/user/hidden
│   │   │   │   ├── Platform.java                  # gg/fb
│   │   │   │   └── AccountStatus.java             # 存活/死亡/验证/限额
│   │   │   │
│   │   │   ├── exception/                         # 异常处理
│   │   │   │   ├── GlobalExceptionHandler.java    # @ControllerAdvice
│   │   │   │   ├── BusinessException.java
│   │   │   │   ├── UnauthorizedException.java
│   │   │   │   └── PlatformForbiddenException.java
│   │   │   │
│   │   │   └── util/                              # 工具类
│   │   │       ├── JwtUtil.java
│   │   │       ├── PasswordUtil.java              # BCrypt
│   │   │       ├── DateUtil.java
│   │   │       └── FfmpegUtil.java
│   │   │
│   │   └── resources/
│   │       ├── application.yml                    # 主配置
│   │       ├── application-dev.yml                # 开发环境
│   │       ├── application-prod.yml               # 生产环境
│   │       └── service-account.json               # Google SA 密钥
│   │
│   └── test/
│       └── java/com/ggserver/
│           ├── controller/                        # Controller 测试
│           ├── service/                           # Service 测试
│           └── repository/                        # Repository 测试
```

### 3.2 包命名规范

```
基础包: com.lmserver
Controller: com.lmserver.controller.{模块}
Service:    com.lmserver.service.{模块}
Repository: com.lmserver.repository
Entity:     com.lmserver.entity
DTO:        com.lmserver.dto.{request|response}
Config:     com.lmserver.config
Security:   com.lmserver.security
```

---

## 4. 技术栈与依赖

### 4.1 Maven pom.xml 核心依赖

```xml
<parent>
    <groupId>org.springframework.boot</groupId>
    <artifactId>spring-boot-starter-parent</artifactId>
    <version>3.3.0</version>
</parent>

<properties>
    <java.version>17</java.version>
    <jjwt.version>0.12.5</jjwt.version>
</properties>

<dependencies>
    <!-- Web -->
    <dependency>
        <groupId>org.springframework.boot</groupId>
        <artifactId>spring-boot-starter-web</artifactId>
    </dependency>

    <!-- Security + JWT -->
    <dependency>
        <groupId>org.springframework.boot</groupId>
        <artifactId>spring-boot-starter-security</artifactId>
    </dependency>
    <dependency>
        <groupId>io.jsonwebtoken</groupId>
        <artifactId>jjwt-api</artifactId>
        <version>${jjwt.version}</version>
    </dependency>
    <dependency>
        <groupId>io.jsonwebtoken</groupId>
        <artifactId>jjwt-impl</artifactId>
        <version>${jjwt.version}</version>
        <scope>runtime</scope>
    </dependency>
    <dependency>
        <groupId>io.jsonwebtoken</groupId>
        <artifactId>jjwt-jackson</artifactId>
        <version>${jjwt.version}</version>
        <scope>runtime</scope>
    </dependency>

    <!-- Database -->
    <dependency>
        <groupId>org.springframework.boot</groupId>
        <artifactId>spring-boot-starter-data-jpa</artifactId>
    </dependency>
    <dependency>
        <groupId>com.mysql</groupId>
        <artifactId>mysql-connector-j</artifactId>
        <scope>runtime</scope>
    </dependency>
    <!-- H2 for testing -->
    <dependency>
        <groupId>com.h2database</groupId>
        <artifactId>h2</artifactId>
        <scope>test</scope>
    </dependency>

    <!-- Validation -->
    <dependency>
        <groupId>org.springframework.boot</groupId>
        <artifactId>spring-boot-starter-validation</artifactId>
    </dependency>

    <!-- Mail -->
    <dependency>
        <groupId>org.springframework.boot</groupId>
        <artifactId>spring-boot-starter-mail</artifactId>
    </dependency>

    <!-- Async -->
    <dependency>
        <groupId>org.springframework.boot</groupId>
        <artifactId>spring-boot-starter</artifactId>
    </dependency>

    <!-- Cache -->
    <dependency>
        <groupId>org.springframework.boot</groupId>
        <artifactId>spring-boot-starter-cache</artifactId>
    </dependency>
    <dependency>
        <groupId>com.github.ben-manes.caffeine</groupId>
        <artifactId>caffeine</artifactId>
    </dependency>

    <!-- Google APIs -->
    <dependency>
        <groupId>com.google.api-client</groupId>
        <artifactId>google-api-client</artifactId>
        <version>2.4.0</version>
    </dependency>
    <dependency>
        <groupId>com.google.apis</groupId>
        <artifactId>google-api-services-sheets</artifactId>
        <version>v4-rev612-1.25.0</version>
    </dependency>
    <dependency>
        <groupId>com.google.auth</groupId>
        <artifactId>google-auth-library-oauth2-http</artifactId>
        <version>1.23.0</version>
    </dependency>
    <dependency>
        <groupId>com.google.api-ads</groupId>
        <artifactId>google-ads</artifactId>
        <version>34.0.0</version>
    </dependency>

    <!-- HTML Parsing (替代 BeautifulSoup) -->
    <dependency>
        <groupId>org.jsoup</groupId>
        <artifactId>jsoup</artifactId>
        <version>1.17.2</version>
    </dependency>

    <!-- Image Processing (替代 Pillow) -->
    <dependency>
        <groupId>net.coobird</groupId>
        <artifactId>thumbnailator</artifactId>
        <version>0.4.20</version>
    </dependency>

    <!-- JSON -->
    <dependency>
        <groupId>com.fasterxml.jackson.core</groupId>
        <artifactId>jackson-databind</artifactId>
    </dependency>

    <!-- Lombok -->
    <dependency>
        <groupId>org.projectlombok</groupId>
        <artifactId>lombok</artifactId>
        <optional>true</optional>
    </dependency>

    <!-- API 文档 (Swagger) -->
    <dependency>
        <groupId>org.springdoc</groupId>
        <artifactId>springdoc-openapi-starter-webmvc-ui</artifactId>
        <version>2.6.0</version>
    </dependency>

    <!-- Entity↔DTO 自动转换 -->
    <dependency>
        <groupId>org.mapstruct</groupId>
        <artifactId>mapstruct</artifactId>
        <version>1.5.5.Final</version>
    </dependency>
    <dependency>
        <groupId>org.mapstruct</groupId>
        <artifactId>mapstruct-processor</artifactId>
        <version>1.5.5.Final</version>
        <scope>provided</scope>
    </dependency>

    <!-- 熔断器（保护外部 API 调用） -->
    <dependency>
        <groupId>io.github.resilience4j</groupId>
        <artifactId>resilience4j-spring-boot3</artifactId>
        <version>2.2.0</version>
    </dependency>

    <!-- 速率限制 -->
    <dependency>
        <groupId>com.bucket4j</groupId>
        <artifactId>bucket4j-core</artifactId>
        <version>8.7.0</version>
    </dependency>

    <!-- Test -->
    <dependency>
        <groupId>org.springframework.boot</groupId>
        <artifactId>spring-boot-starter-test</artifactId>
        <scope>test</scope>
    </dependency>
    <dependency>
        <groupId>org.springframework.security</groupId>
        <artifactId>spring-security-test</artifactId>
        <scope>test</scope>
    </dependency>
</dependencies>
```

---

## 5. 数据库设计

> **数据库版本要求**: MySQL 8.0.13+（`DEFAULT (CURRENT_DATE)` 括号表达式需要此版本）

### 5.1 从 SQLite 到 MySQL 的变更

| SQLite 特性 | MySQL 替代 |
|-------------|-----------|
| `INTEGER PRIMARY KEY AUTOINCREMENT` | `BIGINT AUTO_INCREMENT PRIMARY KEY` |
| `TEXT` | `VARCHAR(n)` 或 `TEXT` |
| `TEXT DEFAULT (datetime('now','localtime'))` | `DATETIME DEFAULT CURRENT_TIMESTAMP` |
| `TEXT DEFAULT '[]'` (JSON) | `JSON` 类型 |
| `UNIQUE(name, owner_id)` | 同名 |
| 外键 `ON DELETE CASCADE` | 同名 |
| WAL 模式 | InnoDB（默认） |
| 无连接池 | HikariCP（默认） |

### 5.2 完整 MySQL DDL

> **说明**: 以下为全部 52 张表的 MySQL 8.0 DDL。执行顺序应按分类依次执行。
>
> **v1.29 补入册**: `tt_recycle_reasons`、`tt_accounts`、`tt_account_bc_history`、`tt_recharge_records` 四张 TT 表此前缺失于本文档。经与现网 `temp/app.db` 逐表比对（文档表名集合 vs `sqlite_master`），现已补齐。
>
> **v1.30 补入册**: `scrape_dn_history`、`tt_delist_notifications` 两张表此前缺失于本文档（同一比对口径：文档表名集合 vs `sqlite_master`）。现已补齐，**两侧数量一致（各 52 张）**。前者是爬取产物归属校验的**墓碑表**（见 §7.8），后者的 GG 同构体 `delist_notifications` 在 §5.2「27.」已收录（TT 掉包通知走独立机器人，表结构与 GG 一致）。

```sql
-- ============================================================
-- GG-Server MySQL 8.0 完整建库脚本
-- 字符集: utf8mb4, 排序: utf8mb4_unicode_ci
-- 引擎: InnoDB
-- ============================================================

CREATE DATABASE IF NOT EXISTS ggserver
  CHARACTER SET utf8mb4
  COLLATE utf8mb4_unicode_ci;

USE ggserver;

-- ============================================================
-- 一、用户和认证相关 (2 张表)
-- ============================================================

-- 1. users — 用户表
CREATE TABLE users (
    id               BIGINT AUTO_INCREMENT PRIMARY KEY,
    username         VARCHAR(20)  NOT NULL UNIQUE COMMENT '用户名（唯一）',
    password         VARCHAR(255) NOT NULL          COMMENT '密码（BCrypt 哈希）',
    role             VARCHAR(20)  NOT NULL DEFAULT 'user'
                     COMMENT '角色: developer/admin/viewer/user/hidden',
    display_name     VARCHAR(100) DEFAULT ''        COMMENT '显示名称',
    custom_name      VARCHAR(100) DEFAULT ''        COMMENT '自定义名称',
    email            VARCHAR(255) DEFAULT ''        COMMENT '邮箱',
    telegram_username VARCHAR(100) DEFAULT ''       COMMENT 'Telegram 用户名（不带@）',
    platform         VARCHAR(10)  DEFAULT 'gg'     COMMENT '所属平台: gg/fb',
    config           JSON         DEFAULT NULL      COMMENT '用户配置JSON（偏好设置等）',
    token_version    INT          DEFAULT 0         COMMENT 'JWT Token版本号（改密/禁用时递增）',
    created_at       DATETIME     DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
    last_login       DATETIME     NULL              COMMENT '最后登录时间',
    created_by       BIGINT       NULL              COMMENT '创建者用户ID（自引用）',
    INDEX idx_users_role (role),
    INDEX idx_users_platform (platform),
    CONSTRAINT fk_users_created_by FOREIGN KEY (created_by) REFERENCES users(id)
) ENGINE=InnoDB COMMENT='用户表';

-- 2. config — 系统配置键值表
CREATE TABLE config (
    `key`  VARCHAR(255) PRIMARY KEY COMMENT '配置键',
    `value` TEXT         NULL     COMMENT '配置值（JSON字符串）'
) ENGINE=InnoDB COMMENT='系统配置键值表';

-- ============================================================
-- 二、GG (Google) 选项表 (5 张)
-- ============================================================

-- 3. agents — 代理/渠道选项表
CREATE TABLE agents (
    id         BIGINT AUTO_INCREMENT PRIMARY KEY,
    name       VARCHAR(100) NOT NULL COMMENT '代理名称',
    owner_id   BIGINT       NULL     COMMENT '归属用户ID',
    created_at DATETIME     DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uk_agents_name_owner (name, owner_id),
    CONSTRAINT fk_agents_owner FOREIGN KEY (owner_id) REFERENCES users(id)
) ENGINE=InnoDB COMMENT='代理选项表';

-- 4. account_statuses — 账户状态选项表
CREATE TABLE account_statuses (
    id         BIGINT AUTO_INCREMENT PRIMARY KEY,
    name       VARCHAR(50)  NOT NULL COMMENT '状态名称（存活/死亡/验证/限额）',
    owner_id   BIGINT       NULL     COMMENT '归属用户ID',
    platform   VARCHAR(10)  DEFAULT 'gg' COMMENT '平台隔离: gg/fb',
    created_at DATETIME     DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uk_statuses_name_owner (name, owner_id),
    CONSTRAINT fk_statuses_owner FOREIGN KEY (owner_id) REFERENCES users(id)
) ENGINE=InnoDB COMMENT='账户状态选项表';

-- 5. mcc_levels — MCC 等级选项表
CREATE TABLE mcc_levels (
    id         BIGINT AUTO_INCREMENT PRIMARY KEY,
    name       VARCHAR(100) NOT NULL COMMENT '等级名称',
    owner_id   BIGINT       NULL     COMMENT '归属用户ID',
    created_at DATETIME     DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uk_mcc_levels_name_owner (name, owner_id),
    CONSTRAINT fk_mcc_levels_owner FOREIGN KEY (owner_id) REFERENCES users(id)
) ENGINE=InnoDB COMMENT='MCC等级选项表';

-- 6. sales_persons — 商务/销售人员选项表
CREATE TABLE sales_persons (
    id         BIGINT AUTO_INCREMENT PRIMARY KEY,
    name       VARCHAR(100) NOT NULL COMMENT '商务名称',
    owner_id   BIGINT       NULL     COMMENT '归属用户ID',
    platform   VARCHAR(10)  DEFAULT 'gg' COMMENT '平台隔离: gg/fb',
    created_at DATETIME     DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uk_sp_name_owner (name, owner_id),
    CONSTRAINT fk_sp_owner FOREIGN KEY (owner_id) REFERENCES users(id)
) ENGINE=InnoDB COMMENT='商务选项表';

-- 7. regions — 地区与时区管理
CREATE TABLE regions (
    id         BIGINT AUTO_INCREMENT PRIMARY KEY,
    name       VARCHAR(100) NOT NULL COMMENT '地区名称',
    timezone   VARCHAR(50)  NOT NULL DEFAULT '' COMMENT '时区',
    platform   VARCHAR(10)  DEFAULT 'gg' COMMENT '平台隔离: gg/fb',
    created_at DATETIME     DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uk_regions_name_platform (name, platform)
) ENGINE=InnoDB COMMENT='地区与时区表';

-- ============================================================
-- 三、GG MCC 与账户 (5 张)
-- ============================================================

-- 8. mcc — MCC 管理表
CREATE TABLE mcc (
    id              BIGINT AUTO_INCREMENT PRIMARY KEY,
    name            VARCHAR(255) NOT NULL COMMENT 'MCC 名称',
    mcc_id          VARCHAR(50)  NOT NULL UNIQUE COMMENT 'Google MCC ID',
    level_id        BIGINT       NULL     COMMENT 'MCC 等级外键',
    parent_mcc_id   BIGINT       NULL     COMMENT '父MCC ID（自引用）',
    owner_id        BIGINT       NULL     COMMENT '归属用户ID',
    shared_user_ids JSON         DEFAULT ('[]') COMMENT '共享用户ID列表',
    -- ↓ Spring Boot新增字段（Python版无），用于MCC凭证管理 ↓
    login_email     VARCHAR(255) DEFAULT '' COMMENT '【新增】登录邮箱',
    login_password  VARCHAR(255) DEFAULT '' COMMENT '【新增】登录密码',
    backup_email    VARCHAR(255) DEFAULT '' COMMENT '【新增】备用邮箱',
    backup_phone    VARCHAR(50)  DEFAULT '' COMMENT '【新增】备用手机号',
    created_at      DATETIME     DEFAULT CURRENT_TIMESTAMP,
    updated_at      DATETIME     DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_mcc_level (level_id),
    INDEX idx_mcc_parent (parent_mcc_id),
    INDEX idx_mcc_owner (owner_id),
    CONSTRAINT fk_mcc_level FOREIGN KEY (level_id) REFERENCES mcc_levels(id),
    CONSTRAINT fk_mcc_parent FOREIGN KEY (parent_mcc_id) REFERENCES mcc(id),
    CONSTRAINT fk_mcc_owner FOREIGN KEY (owner_id) REFERENCES users(id)
) ENGINE=InnoDB COMMENT='MCC管理表';

-- 9. accounts — GG 广告账户表
CREATE TABLE accounts (
    id                  BIGINT AUTO_INCREMENT PRIMARY KEY,
    name                VARCHAR(255) NOT NULL COMMENT '账户名称',
    account_id          VARCHAR(50)  NOT NULL UNIQUE COMMENT 'Google 广告账户ID',
    timezone            VARCHAR(50)  DEFAULT '' COMMENT '时区',
    agent_id            BIGINT       NULL     COMMENT '代理外键',
    status_id           BIGINT       NULL     COMMENT '状态外键',
    mcc_id              BIGINT       NULL     COMMENT '所属MCC外键',
    acquired_date       DATE         DEFAULT (CURRENT_DATE) COMMENT '获取日期',
    death_date          DATE         NULL     COMMENT '死亡日期',
    status_changed_date DATE         NULL     COMMENT '状态变更日期',
    owner_id            BIGINT       NULL     COMMENT '归属用户ID',
    deleted_at          DATETIME     NULL     COMMENT '软删除时间',
    created_at          DATETIME     DEFAULT CURRENT_TIMESTAMP,
    updated_at          DATETIME     DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_accounts_mcc (mcc_id),
    INDEX idx_accounts_owner (owner_id),
    INDEX idx_accounts_status (status_id),
    INDEX idx_accounts_agent (agent_id),
    INDEX idx_accounts_list (owner_id, status_id, deleted_at),
    INDEX idx_accounts_created (created_at),
    CONSTRAINT fk_accounts_agent FOREIGN KEY (agent_id) REFERENCES agents(id),
    CONSTRAINT fk_accounts_status FOREIGN KEY (status_id) REFERENCES account_statuses(id),
    CONSTRAINT fk_accounts_mcc FOREIGN KEY (mcc_id) REFERENCES mcc(id),
    CONSTRAINT fk_accounts_owner FOREIGN KEY (owner_id) REFERENCES users(id)
) ENGINE=InnoDB COMMENT='GG广告账户表';

-- 10. account_mcc_history — 账户 MCC 变更历史
CREATE TABLE account_mcc_history (
    id           BIGINT AUTO_INCREMENT PRIMARY KEY,
    account_id   BIGINT       NOT NULL COMMENT '账户ID',
    old_mcc_id   BIGINT       NULL     COMMENT '旧MCC ID',
    new_mcc_id   BIGINT       NULL     COMMENT '新MCC ID',
    changed_by   BIGINT       NULL     COMMENT '操作人ID',
    change_type  VARCHAR(20)  NOT NULL DEFAULT 'manual' COMMENT '变更类型: manual/auto',
    created_at   DATETIME     DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_acmh_account (account_id),
    INDEX idx_acmh_changed_by (changed_by),
    CONSTRAINT fk_acmh_account FOREIGN KEY (account_id) REFERENCES accounts(id) ON DELETE CASCADE,
    CONSTRAINT fk_acmh_changed_by FOREIGN KEY (changed_by) REFERENCES users(id)
) ENGINE=InnoDB COMMENT='账户MCC变更历史';

-- 11. recharge_records — 充值记录表
CREATE TABLE recharge_records (
    id             BIGINT AUTO_INCREMENT PRIMARY KEY,
    account_id     VARCHAR(50)  NOT NULL COMMENT '关联账户ID（引用 accounts.account_id）',
    amount         VARCHAR(50)  NOT NULL COMMENT '充值金额',
    agent_id       BIGINT       NULL     COMMENT '代理外键',
    operator       VARCHAR(100) DEFAULT '' COMMENT '操作员',
    status         VARCHAR(50)  DEFAULT '' COMMENT '充值状态',
    sheets_synced  TINYINT      DEFAULT 0 COMMENT 'Google Sheets 同步标记',
    sheets_error   TEXT         NULL     COMMENT 'Sheets 同步错误信息',
    created_by     BIGINT       NULL     COMMENT '创建者ID',
    created_at     DATETIME     DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_recharge_account (account_id),
    INDEX idx_recharge_created_by (created_by),
    CONSTRAINT fk_recharge_agent FOREIGN KEY (agent_id) REFERENCES agents(id),
    CONSTRAINT fk_recharge_created_by FOREIGN KEY (created_by) REFERENCES users(id)
) ENGINE=InnoDB COMMENT='充值记录表';

-- 12. sheets_sync_log — Google Sheets 同步日志
CREATE TABLE sheets_sync_log (
    id             BIGINT AUTO_INCREMENT PRIMARY KEY,
    user_id        BIGINT       NOT NULL COMMENT '用户ID',
    product_name   VARCHAR(255) NOT NULL DEFAULT '' COMMENT '产品名称',
    spreadsheet_id VARCHAR(255) NOT NULL DEFAULT '' COMMENT 'Google Sheets 表ID',
    sheet_gid      VARCHAR(100) NOT NULL DEFAULT '' COMMENT 'Sheet GID',
    status         VARCHAR(50)  NOT NULL DEFAULT 'failed' COMMENT '同步状态',
    error_msg      TEXT         NULL     COMMENT '错误信息',
    rows_json      JSON         NULL     COMMENT '待同步行数据',
    retry_count    INT          DEFAULT 0 COMMENT '重试次数',
    created_at     DATETIME     DEFAULT CURRENT_TIMESTAMP,
    updated_at     DATETIME     DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_ssl_user_product (user_id, product_name),
    CONSTRAINT fk_ssl_user FOREIGN KEY (user_id) REFERENCES users(id)
) ENGINE=InnoDB COMMENT='Sheets同步日志';

-- ============================================================
-- 四、GG 产品与包 (7 张)
-- ============================================================

-- 13. products — GG 产品表
CREATE TABLE products (
    id              BIGINT AUTO_INCREMENT PRIMARY KEY,
    product_name    VARCHAR(255) NULL     COMMENT '产品名称',
    kpi             VARCHAR(255) NULL     COMMENT 'KPI指标',
    region          VARCHAR(100) NULL     COMMENT '地区',
    status          VARCHAR(50)  DEFAULT '' COMMENT '状态',
    customer        VARCHAR(255) DEFAULT '' COMMENT '客户名称',
    sales_person_id BIGINT       NULL     COMMENT '商务外键',
    mcc_id          BIGINT       NULL     COMMENT '所属MCC外键',
    agency_ratio    DOUBLE       NULL     COMMENT '代理比例',
    owner_id        BIGINT       NULL     COMMENT '归属用户ID',
    runner_ids      JSON         DEFAULT ('[]') COMMENT '在跑人员ID列表',
    is_archived     TINYINT      DEFAULT 0 COMMENT '是否归档',
    deleted_at      DATETIME     NULL     COMMENT '软删除时间',
    created_at      DATETIME     DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_products_name (product_name),
    INDEX idx_products_region (region),
    INDEX idx_products_mcc (mcc_id),
    INDEX idx_products_owner (owner_id),
    INDEX idx_products_sp (sales_person_id),
    INDEX idx_products_created (created_at),
    CONSTRAINT fk_products_sp FOREIGN KEY (sales_person_id) REFERENCES sales_persons(id),
    CONSTRAINT fk_products_mcc FOREIGN KEY (mcc_id) REFERENCES mcc(id),
    CONSTRAINT fk_products_owner FOREIGN KEY (owner_id) REFERENCES users(id)
) ENGINE=InnoDB COMMENT='GG产品表';

-- 14. product_runners — 产品在跑人员关联表
CREATE TABLE product_runners (
    product_id BIGINT NOT NULL COMMENT '产品ID',
    user_id    BIGINT NOT NULL COMMENT '用户ID',
    PRIMARY KEY (product_id, user_id),
    INDEX idx_pr_user (user_id),
    CONSTRAINT fk_pr_product FOREIGN KEY (product_id) REFERENCES products(id),
    CONSTRAINT fk_pr_user FOREIGN KEY (user_id) REFERENCES users(id)
) ENGINE=InnoDB COMMENT='产品在跑人员关联';

-- 15. packages — 产品包/素材系列表
CREATE TABLE packages (
    id            BIGINT AUTO_INCREMENT PRIMARY KEY,
    product_id    BIGINT       NULL     COMMENT '所属产品ID',
    series_name   VARCHAR(255) NULL     COMMENT '系列名称',
    package_name  VARCHAR(255) NULL     COMMENT '包名称',
    url           TEXT         NULL     COMMENT '素材URL/地址',
    status        VARCHAR(50)  DEFAULT '' COMMENT '状态',
    created_at    DATETIME     DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_packages_product (product_id),
    CONSTRAINT fk_packages_product FOREIGN KEY (product_id) REFERENCES products(id)
) ENGINE=InnoDB COMMENT='产品包表';

-- 16. copywritings — 文案管理表
CREATE TABLE copywritings (
    id            BIGINT AUTO_INCREMENT PRIMARY KEY,
    region        VARCHAR(100) NOT NULL DEFAULT '通用' COMMENT '所属地区',
    content       TEXT         NOT NULL COMMENT '文案内容',
    owner_id      BIGINT       NULL     COMMENT '归属用户ID',
    effectiveness VARCHAR(50)  DEFAULT '' COMMENT '成效标记',
    is_public     TINYINT      DEFAULT 0 COMMENT '是否公开',
    created_at    DATETIME     DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_copywritings_region (region),
    INDEX idx_copywritings_owner (owner_id),
    CONSTRAINT fk_copywritings_owner FOREIGN KEY (owner_id) REFERENCES users(id)
) ENGINE=InnoDB COMMENT='文案管理表';

-- 17. product_assets — 产品成效素材关联
CREATE TABLE product_assets (
    id              BIGINT AUTO_INCREMENT PRIMARY KEY,
    product_id      BIGINT       NOT NULL COMMENT '产品ID',
    video_id        VARCHAR(50)  NOT NULL COMMENT '视频ID',
    video_owner_id  BIGINT       NOT NULL DEFAULT 1 COMMENT '视频归属用户ID',
    added_by        BIGINT       NULL     COMMENT '添加者ID',
    added_at        DATETIME     DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uk_assets_product_video (product_id, video_id),
    INDEX idx_pa_video_owner (video_id, video_owner_id),
    CONSTRAINT fk_pa_product FOREIGN KEY (product_id) REFERENCES products(id),
    CONSTRAINT fk_pa_added_by FOREIGN KEY (added_by) REFERENCES users(id),
    CONSTRAINT fk_pa_video_ref FOREIGN KEY (video_id, video_owner_id) REFERENCES videos(id, owner_id)
) ENGINE=InnoDB COMMENT='产品素材关联';

-- 17. scrape_cache — 爬取缓存表
CREATE TABLE scrape_cache (
    package_name VARCHAR(255) PRIMARY KEY COMMENT '包名称（主键）',
    image_count  INT          DEFAULT 0 COMMENT '图片数量',
    saved_path   TEXT         NULL     COMMENT '保存路径',
    logo_path    TEXT         NULL     COMMENT 'Logo路径',
    last_scraped DATETIME     DEFAULT CURRENT_TIMESTAMP COMMENT '最后爬取时间',
    scraped_by   BIGINT       NULL     COMMENT '爬取操作人ID',
    CONSTRAINT fk_sc_cache_user FOREIGN KEY (scraped_by) REFERENCES users(id)
) ENGINE=InnoDB COMMENT='爬取缓存表';

-- scrape_dn_history — 爬取目录名历史 + 墓碑 + 哨兵硬闸（v1.30 补入册）
-- ⚠️ 刻意**不建外键**、删用户时**也不清理本表**：它是「墓碑表」——删用户时先写入该用户
-- 当前的爬取目录名（`auth.note_scrape_dn_release`），那行必须**活过**本次删除，否则本该
-- 无主的爬取目录会被「曾用名含该名」的人认领、读到被删用户的产物。
-- ⚠️ **不得**建 `UNIQUE(dn)`：同一目录名允许多行（last-writer-wins 靠 id 序比较）。
-- `user_id = 0` 是**哨兵**（硬闸，非真实用户），不参与序号比较，只拦它写下时已存在的化身。
-- ⚠️ 写入必须带**亚秒**（SQLite 侧用 strftime('%Y-%m-%d %H:%M:%f','now')）：本表的默认值
-- 若只到秒，对「释放行」是 fail-closed、对「哨兵」却是 **fail-open**（见 §7.8 不变式 4）。
-- 列语义与精度详见 §7.8。
CREATE TABLE scrape_dn_history (
    id         BIGINT AUTO_INCREMENT PRIMARY KEY,
    user_id    BIGINT       NOT NULL COMMENT '用户ID；0 = 哨兵（硬闸，不参与 LWW 比较）',
    dn         VARCHAR(255) NOT NULL COMMENT '爬取目录名（应用层按 normcase 归一后比较）',
    created_at DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '释放/标记时刻（UTC，毫秒精度）',
    INDEX idx_scrape_dn_history_dn (dn),
    INDEX idx_scrape_dn_history_user (user_id)
) ENGINE=InnoDB COMMENT='爬取目录名历史（墓碑 + 哨兵硬闸）';

-- 18. import_history — 导入历史记录
CREATE TABLE import_history (
    id                 BIGINT AUTO_INCREMENT PRIMARY KEY,
    user_id            BIGINT       NULL     COMMENT '操作人ID',
    file_name          VARCHAR(255) NULL     COMMENT '文件名',
    file_type          VARCHAR(20)  NULL     COMMENT '文件类型: db/json',
    products_count     INT DEFAULT 0,
    packages_count     INT DEFAULT 0,
    accounts_count     INT DEFAULT 0,
    mcc_count          INT DEFAULT 0,
    videos_count       INT DEFAULT 0,
    copywritings_count INT DEFAULT 0,
    tags_count         INT DEFAULT 0,
    skipped_count      INT DEFAULT 0,
    status             VARCHAR(20)  DEFAULT 'success' COMMENT '状态',
    error_msg          TEXT         NULL     COMMENT '错误信息',
    created_at         DATETIME     DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_ih_user FOREIGN KEY (user_id) REFERENCES users(id)
) ENGINE=InnoDB COMMENT='导入历史';

-- ============================================================
-- 五、YouTube / 视频 (9 张)
-- ============================================================

-- 19. videos — YouTube 视频表
CREATE TABLE videos (
    id            VARCHAR(50)  NOT NULL COMMENT '视频YouTube ID',
    owner_id      BIGINT       NOT NULL DEFAULT 1 COMMENT '归属用户ID',
    url           TEXT         NULL     COMMENT '视频URL',
    title         VARCHAR(500) NULL     COMMENT '视频标题',
    region        VARCHAR(100) DEFAULT '通用' COMMENT '地区',
    frame_type    VARCHAR(50)  DEFAULT '非融帧' COMMENT '融帧类型',
    effectiveness VARCHAR(50)  DEFAULT '' COMMENT '成效评估',
    product_name  VARCHAR(255) DEFAULT '' COMMENT '关联产品名称',
    review_status VARCHAR(50)  DEFAULT '能过审' COMMENT '审核状态',
    is_public     TINYINT      DEFAULT 0 COMMENT '是否公开',
    channel_name  VARCHAR(255) DEFAULT '' COMMENT '频道名称',
    imported_at   DATETIME     NULL     COMMENT '导入时间',
    PRIMARY KEY (id, owner_id),
    INDEX idx_videos_owner (owner_id),
    INDEX idx_videos_region (region),
    INDEX idx_videos_imported (imported_at),
    CONSTRAINT fk_videos_owner FOREIGN KEY (owner_id) REFERENCES users(id)
) ENGINE=InnoDB COMMENT='YouTube视频表';

-- 20. tags — 通用标签键值表
CREATE TABLE tags (
    `key`  VARCHAR(100) PRIMARY KEY COMMENT '标签键',
    `value` JSON         NULL     COMMENT '标签值（JSON数组）'
) ENGINE=InnoDB COMMENT='通用标签表';

-- 21. video_history — 视频生成历史
CREATE TABLE video_history (
    id         BIGINT AUTO_INCREMENT PRIMARY KEY,
    package    VARCHAR(255) NOT NULL COMMENT '所属包名',
    name       VARCHAR(255) DEFAULT '' COMMENT '历史记录名称',
    settings   JSON         NOT NULL COMMENT '设置JSON',
    created_at DATETIME     DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME     DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_history_pkg (package)
) ENGINE=InnoDB COMMENT='视频生成历史';

-- 22. video_tasks — 视频任务记录
CREATE TABLE video_tasks (
    id          BIGINT AUTO_INCREMENT PRIMARY KEY,
    task_id     VARCHAR(100) NOT NULL UNIQUE COMMENT '任务唯一标识',
    package     VARCHAR(255) DEFAULT '' COMMENT '所属包名',
    status      VARCHAR(20)  DEFAULT 'pending' COMMENT '状态',
    progress    DOUBLE       DEFAULT 0 COMMENT '进度（0~1）',
    message     TEXT         NULL     COMMENT '状态信息',
    output_path VARCHAR(500) DEFAULT '' COMMENT '输出路径',
    settings    JSON         NULL     COMMENT '任务设置',
    created_at  DATETIME     DEFAULT CURRENT_TIMESTAMP,
    finished_at DATETIME     NULL     COMMENT '完成时间',
    INDEX idx_tasks_status (status)
) ENGINE=InnoDB COMMENT='视频任务记录';

-- 23. audio_replace_history — 音频替换历史
CREATE TABLE audio_replace_history (
    id          BIGINT AUTO_INCREMENT PRIMARY KEY,
    video_name  VARCHAR(255) NOT NULL COMMENT '视频文件名',
    audio_name  VARCHAR(255) NOT NULL COMMENT '替换音频文件名',
    output_name VARCHAR(255) NOT NULL COMMENT '输出文件名',
    output_path VARCHAR(500) NOT NULL COMMENT '输出路径',
    size_mb     DOUBLE       NOT NULL COMMENT '文件大小（MB）',
    created_at  DATETIME     DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB COMMENT='音频替换历史';

-- 24. ad_reports — GG 广告投放报告
CREATE TABLE ad_reports (
    id              BIGINT AUTO_INCREMENT PRIMARY KEY,
    user_id         BIGINT       NOT NULL COMMENT '上传用户ID',
    product_name    VARCHAR(255) NOT NULL COMMENT '产品名称',
    region          VARCHAR(100) NOT NULL COMMENT '地区',
    report_date     DATE         NOT NULL COMMENT '报告日期',
    account         VARCHAR(255) NOT NULL DEFAULT '' COMMENT '账户名称',
    customer_id     VARCHAR(100) NOT NULL DEFAULT '' COMMENT '客户ID',
    campaign        VARCHAR(255) NOT NULL DEFAULT '' COMMENT '广告系列',
    cost            DOUBLE       DEFAULT 0 COMMENT '消耗',
    impressions     INT          DEFAULT 0 COMMENT '展示次数',
    clicks          INT          DEFAULT 0 COMMENT '点击次数',
    installs        DOUBLE       DEFAULT 0 COMMENT '安装数',
    in_app_actions  DOUBLE       DEFAULT 0 COMMENT '应用内操作',
    cost_per_in_app DOUBLE       DEFAULT 0 COMMENT '单次应用内操作成本',
    saved_at        DATETIME     DEFAULT CURRENT_TIMESTAMP COMMENT '保存时间',
    INDEX idx_ar_user_product_date (user_id, product_name, report_date),
    INDEX idx_ar_date (report_date),
    INDEX idx_ar_dedup (user_id, product_name, customer_id, campaign, report_date),
    CONSTRAINT fk_ar_user FOREIGN KEY (user_id) REFERENCES users(id)
) ENGINE=InnoDB COMMENT='GG广告投放报告';

-- 25. video_consumption — 视频消耗追踪
CREATE TABLE video_consumption (
    id             BIGINT AUTO_INCREMENT PRIMARY KEY,
    video_id       VARCHAR(50)  NOT NULL COMMENT '视频ID',
    video_owner_id BIGINT       NOT NULL DEFAULT 1 COMMENT '视频归属用户ID',
    user_id        BIGINT       NOT NULL COMMENT '录入用户ID',
    product_id     BIGINT       NULL     COMMENT '关联产品ID',
    amount         DOUBLE       NOT NULL DEFAULT 0 COMMENT '消耗金额',
    consume_date   DATE         NOT NULL DEFAULT (CURRENT_DATE) COMMENT '消耗日期',
    created_at     DATETIME     DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_vc_video (video_id, video_owner_id),
    INDEX idx_vc_user (user_id),
    INDEX idx_vc_product (product_id),
    INDEX idx_vc_date (consume_date),
    CONSTRAINT fk_vc_user FOREIGN KEY (user_id) REFERENCES users(id),
    CONSTRAINT fk_vc_product FOREIGN KEY (product_id) REFERENCES products(id),
    CONSTRAINT fk_vc_video_ref FOREIGN KEY (video_id, video_owner_id) REFERENCES videos(id, owner_id)
) ENGINE=InnoDB COMMENT='视频消耗追踪';

-- ============================================================
-- 六、掉包检测与审计 (4 张)
-- ============================================================

-- 26. delist_checks — 掉包检测结果
CREATE TABLE delist_checks (
    id          BIGINT AUTO_INCREMENT PRIMARY KEY,
    package_id  BIGINT       NOT NULL UNIQUE COMMENT '包ID（唯一）',
    product_id  BIGINT       NOT NULL COMMENT '产品ID',
    is_delisted TINYINT      DEFAULT 0 COMMENT '是否掉包',
    checked_at  DATETIME     NULL     COMMENT '检测时间',
    error_msg   TEXT         NULL     COMMENT '错误信息',
    INDEX idx_dc_product (product_id),
    CONSTRAINT fk_dc_package FOREIGN KEY (package_id) REFERENCES packages(id),
    CONSTRAINT fk_dc_product FOREIGN KEY (product_id) REFERENCES products(id)
) ENGINE=InnoDB COMMENT='掉包检测结果';

-- 27. delist_notifications — 掉包通知状态
CREATE TABLE delist_notifications (
    id              BIGINT AUTO_INCREMENT PRIMARY KEY,
    package_id      BIGINT   NOT NULL COMMENT '包ID',
    user_id         BIGINT   NOT NULL COMMENT '用户ID',
    first_notified  TINYINT  DEFAULT 0 COMMENT '是否已首次通知',
    dismissed_at    DATETIME NULL     COMMENT '关闭时间',
    reminder_count  INT      DEFAULT 0 COMMENT '提醒次数',
    UNIQUE KEY uk_dn_package_user (package_id, user_id),
    INDEX idx_dn_user (user_id),
    CONSTRAINT fk_dn_package FOREIGN KEY (package_id) REFERENCES packages(id),
    CONSTRAINT fk_dn_user FOREIGN KEY (user_id) REFERENCES users(id)
) ENGINE=InnoDB COMMENT='掉包通知状态';

-- 28. audit_log — 审计日志
CREATE TABLE audit_log (
    id          BIGINT AUTO_INCREMENT PRIMARY KEY,
    user_id     BIGINT       NOT NULL COMMENT '操作人ID',
    action      VARCHAR(50)  NOT NULL COMMENT '操作类型（如: delete_product）',
    target_type VARCHAR(50)  NOT NULL COMMENT '目标类型（如: product）',
    target_id   BIGINT       NOT NULL COMMENT '目标ID',
    target_name VARCHAR(255) DEFAULT '' COMMENT '目标名称',
    detail      JSON         NULL     COMMENT '详情',
    created_at  DATETIME     DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_audit_action (action),
    INDEX idx_audit_created (created_at),
    INDEX idx_audit_user (user_id),
    CONSTRAINT fk_audit_user FOREIGN KEY (user_id) REFERENCES users(id)
) ENGINE=InnoDB COMMENT='审计日志';

-- ============================================================
-- 七、FB 平台 (11 张)
-- ============================================================

-- 29. fb_bms — FB 商务管理平台表
CREATE TABLE fb_bms (
    id         BIGINT AUTO_INCREMENT PRIMARY KEY,
    name       VARCHAR(255) NOT NULL COMMENT 'BM 名称',
    bm_id      VARCHAR(50)  NOT NULL UNIQUE COMMENT 'Facebook BM ID',
    note       TEXT         NULL     COMMENT '备注',
    status     VARCHAR(20)  DEFAULT 'normal' COMMENT '状态: normal/deleted',
    owner_id   BIGINT       NULL     COMMENT '归属用户ID',
    deleted_at DATETIME     NULL     COMMENT '软删除时间',
    created_at DATETIME     DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME     DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_fb_bms_owner (owner_id),
    INDEX idx_fb_bms_status (status),
    INDEX idx_fb_bms_list (owner_id, status, deleted_at),
    CONSTRAINT fk_fb_bms_owner FOREIGN KEY (owner_id) REFERENCES users(id)
) ENGINE=InnoDB COMMENT='FB BM表';

-- 30. fb_accounts — FB 广告账户表
CREATE TABLE fb_accounts (
    id                  BIGINT AUTO_INCREMENT PRIMARY KEY,
    name                VARCHAR(255) NOT NULL COMMENT '账户名称',
    account_id          VARCHAR(50)  NOT NULL UNIQUE COMMENT 'FB 账户ID',
    timezone            VARCHAR(50)  DEFAULT '' COMMENT '时区',
    status_id           BIGINT       NULL     COMMENT '状态外键',
    acquired_date       DATE         DEFAULT (CURRENT_DATE) COMMENT '获取日期',
    status_changed_date DATE         NULL     COMMENT '状态变更日期',
    owner_id            BIGINT       NULL     COMMENT '归属用户ID',
    deleted_at          DATETIME     NULL     COMMENT '软删除时间',
    created_at          DATETIME     DEFAULT CURRENT_TIMESTAMP,
    updated_at          DATETIME     DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_fb_accounts_owner (owner_id),
    INDEX idx_fb_accounts_list (owner_id, status_id, deleted_at),
    INDEX idx_fb_accounts_created (created_at),
    CONSTRAINT fk_fb_accounts_status FOREIGN KEY (status_id) REFERENCES account_statuses(id),
    CONSTRAINT fk_fb_accounts_owner FOREIGN KEY (owner_id) REFERENCES users(id)
) ENGINE=InnoDB COMMENT='FB广告账户表';

-- 31. fb_account_bm — FB 账户-BM 关联表
CREATE TABLE fb_account_bm (
    id         BIGINT AUTO_INCREMENT PRIMARY KEY,
    account_id BIGINT   NOT NULL COMMENT '账户ID',
    bm_id      BIGINT   NOT NULL COMMENT 'BM ID',
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uk_fab_account_bm (account_id, bm_id),
    INDEX idx_fab_bm (bm_id),
    CONSTRAINT fk_fab_account FOREIGN KEY (account_id) REFERENCES fb_accounts(id) ON DELETE CASCADE,
    CONSTRAINT fk_fab_bm FOREIGN KEY (bm_id) REFERENCES fb_bms(id) ON DELETE CASCADE
) ENGINE=InnoDB COMMENT='FB账户-BM关联';

-- 32. fb_account_bm_history — FB 账户-BM 变更历史
CREATE TABLE fb_account_bm_history (
    id          BIGINT AUTO_INCREMENT PRIMARY KEY,
    account_id  BIGINT       NOT NULL COMMENT '账户ID',
    old_bm_id   BIGINT       NULL     COMMENT '旧BM ID',
    new_bm_id   BIGINT       NULL     COMMENT '新BM ID',
    changed_by  BIGINT       NULL     COMMENT '操作人ID',
    change_type VARCHAR(20)  NOT NULL DEFAULT 'manual' COMMENT '变更类型',
    created_at  DATETIME     DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_fabmh_account (account_id),
    CONSTRAINT fk_fabmh_account FOREIGN KEY (account_id) REFERENCES fb_accounts(id),
    CONSTRAINT fk_fabmh_old_bm FOREIGN KEY (old_bm_id) REFERENCES fb_bms(id),
    CONSTRAINT fk_fabmh_new_bm FOREIGN KEY (new_bm_id) REFERENCES fb_bms(id),
    CONSTRAINT fk_fabmh_user FOREIGN KEY (changed_by) REFERENCES users(id)
) ENGINE=InnoDB COMMENT='FB账户BM变更历史';

-- 33. fb_products — FB 产品表
CREATE TABLE fb_products (
    id              BIGINT AUTO_INCREMENT PRIMARY KEY,
    product_name    VARCHAR(255) NOT NULL COMMENT '产品名称',
    kpi             VARCHAR(255) DEFAULT '' COMMENT 'KPI指标',
    region          VARCHAR(100) DEFAULT '' COMMENT '地区',
    status          VARCHAR(50)  DEFAULT 'active' COMMENT '状态',
    sales_person_id BIGINT       NULL     COMMENT '商务外键',
    agency_ratio    DOUBLE       DEFAULT 0 COMMENT '代理比例',
    owner_id        BIGINT       NULL     COMMENT '归属用户ID',
    is_archived     TINYINT      DEFAULT 0 COMMENT '是否归档',
    created_at      DATETIME     DEFAULT CURRENT_TIMESTAMP,
    updated_at      DATETIME     DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_fb_products_owner (owner_id),
    INDEX idx_fb_products_sp (sales_person_id),
    CONSTRAINT fk_fb_products_sp FOREIGN KEY (sales_person_id) REFERENCES sales_persons(id),
    CONSTRAINT fk_fb_products_owner FOREIGN KEY (owner_id) REFERENCES users(id)
) ENGINE=InnoDB COMMENT='FB产品表';

-- 34. fb_product_runners — FB 产品在跑人员关联
CREATE TABLE fb_product_runners (
    product_id BIGINT NOT NULL COMMENT '产品ID',
    user_id    BIGINT NOT NULL COMMENT '用户ID',
    PRIMARY KEY (product_id, user_id),
    INDEX idx_fpr_user (user_id),
    CONSTRAINT fk_fpr_product FOREIGN KEY (product_id) REFERENCES fb_products(id) ON DELETE CASCADE,
    CONSTRAINT fk_fpr_user FOREIGN KEY (user_id) REFERENCES users(id)
) ENGINE=InnoDB COMMENT='FB产品在跑人员关联';

-- 35. fb_product_bms — FB 产品-BM 关联表
CREATE TABLE fb_product_bms (
    id         BIGINT AUTO_INCREMENT PRIMARY KEY,
    product_id BIGINT NOT NULL COMMENT '产品ID',
    bm_id      BIGINT NOT NULL COMMENT 'BM ID',
    UNIQUE KEY uk_fpb_product_bm (product_id, bm_id),
    INDEX idx_fpb_bm (bm_id),
    CONSTRAINT fk_fpb_product FOREIGN KEY (product_id) REFERENCES fb_products(id) ON DELETE CASCADE,
    CONSTRAINT fk_fpb_bm FOREIGN KEY (bm_id) REFERENCES fb_bms(id) ON DELETE CASCADE
) ENGINE=InnoDB COMMENT='FB产品-BM关联';

-- 36. fb_pixel_bms — FB Pixel BM 管理
CREATE TABLE fb_pixel_bms (
    id         BIGINT AUTO_INCREMENT PRIMARY KEY,
    name       VARCHAR(255) NOT NULL COMMENT '名称',
    bm_id      VARCHAR(50)  NOT NULL UNIQUE COMMENT 'FB BM ID',
    note       TEXT         NULL     COMMENT '备注',
    status     VARCHAR(20)  DEFAULT 'normal' COMMENT '状态',
    owner_id   BIGINT       NULL     COMMENT '归属用户ID',
    deleted_at DATETIME     NULL     COMMENT '软删除时间',
    created_at DATETIME     DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME     DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_fpbms_owner (owner_id),
    INDEX idx_fpbms_list (owner_id, status, deleted_at),
    CONSTRAINT fk_fpbms_owner FOREIGN KEY (owner_id) REFERENCES users(id)
) ENGINE=InnoDB COMMENT='FB Pixel BM表';

-- 37. fb_pixels — FB Pixel 表
CREATE TABLE fb_pixels (
    id          BIGINT AUTO_INCREMENT PRIMARY KEY,
    pixel_bm_id BIGINT       NOT NULL COMMENT '所属 Pixel BM',
    pixel_name  VARCHAR(255) NOT NULL COMMENT 'Pixel 名称',
    pixel_id    VARCHAR(50)  NOT NULL UNIQUE COMMENT 'Pixel ID',
    created_at  DATETIME     DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_fp_bm (pixel_bm_id),
    CONSTRAINT fk_fp_bm FOREIGN KEY (pixel_bm_id) REFERENCES fb_pixel_bms(id) ON DELETE CASCADE
) ENGINE=InnoDB COMMENT='FB Pixel表';

-- 38. fb_lines — FB 广告线/落地页
CREATE TABLE fb_lines (
    id         BIGINT AUTO_INCREMENT PRIMARY KEY,
    product_id BIGINT       NOT NULL COMMENT '产品ID',
    line_name  VARCHAR(255) NOT NULL COMMENT '线路名称',
    link       TEXT         NULL     COMMENT '链接地址',
    pixel_id   BIGINT       NULL     COMMENT '关联Pixel',
    created_at DATETIME     DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uk_fl_product_line (product_id, line_name),
    INDEX idx_fl_product (product_id),
    INDEX idx_fl_pixel (pixel_id),
    CONSTRAINT fk_fl_product FOREIGN KEY (product_id) REFERENCES fb_products(id) ON DELETE CASCADE,
    CONSTRAINT fk_fl_pixel FOREIGN KEY (pixel_id) REFERENCES fb_pixels(id) ON DELETE SET NULL
) ENGINE=InnoDB COMMENT='FB广告线';

-- 39. fb_ad_reports — FB 广告投放报告
CREATE TABLE fb_ad_reports (
    id                BIGINT AUTO_INCREMENT PRIMARY KEY,
    user_id           BIGINT       NOT NULL COMMENT '上传用户ID',
    product_name      VARCHAR(255) NOT NULL COMMENT '产品名称',
    line_name         VARCHAR(255) DEFAULT '' COMMENT '线路名称',
    report_date       DATE         NOT NULL COMMENT '报告日期',
    account_name      VARCHAR(255) DEFAULT '' COMMENT '账户名称',
    account_id        VARCHAR(50)  DEFAULT '' COMMENT '账户ID',
    cost              DOUBLE       DEFAULT 0 COMMENT '消耗',
    impressions       INT          DEFAULT 0 COMMENT '展示次数',
    clicks            INT          DEFAULT 0 COMMENT '点击次数',
    registrations     INT          DEFAULT 0 COMMENT '注册数',
    purchases         INT          DEFAULT 0 COMMENT '购买数',
    cost_per_purchase DOUBLE       DEFAULT 0 COMMENT '单次购买成本',
    updated_at        DATETIME     NULL     COMMENT '更新时间',
    saved_at          DATETIME     DEFAULT CURRENT_TIMESTAMP COMMENT '保存时间',
    -- 去重唯一索引：(用户, 产品, 线名, 账户ID, 日期)
    UNIQUE KEY uk_far_upsert (user_id, product_name, line_name, account_id, report_date),
    INDEX idx_far_user_date (user_id, report_date),
    INDEX idx_far_product_date (product_name, report_date),
    CONSTRAINT fk_far_user FOREIGN KEY (user_id) REFERENCES users(id)
) ENGINE=InnoDB COMMENT='FB广告投放报告';

-- ============================================================
-- 八、TT (TikTok) 平台 (10 张表)
-- ============================================================

-- tt_recycle_reasons — TT 回收原因选项表（v1.29 新增入册；全平台公用词表）
-- 注意：name 为【全局唯一】，不是 SQLite 旧表上的 UNIQUE(name, owner_id)
CREATE TABLE tt_recycle_reasons (
    id         BIGINT AUTO_INCREMENT PRIMARY KEY,
    name       VARCHAR(100) NOT NULL COMMENT '回收原因名称',
    owner_id   BIGINT       NULL     COMMENT '创建者ID（仅留痕，不参与鉴权）',
    created_at DATETIME     DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
    UNIQUE KEY uk_tt_recycle_reasons_name (name),
    CONSTRAINT fk_tt_recycle_reasons_owner FOREIGN KEY (owner_id) REFERENCES users(id)
) ENGINE=InnoDB COMMENT='TT 回收原因选项表';

-- tt_bcs — TT BC 表
CREATE TABLE tt_bcs (
    id          BIGINT AUTO_INCREMENT PRIMARY KEY,
    name        VARCHAR(255) NOT NULL COMMENT 'BC 名称',
    bc_id       VARCHAR(255) NOT NULL UNIQUE COMMENT 'BC ID（唯一）',
    note        TEXT         DEFAULT '' COMMENT '备注',
    status      VARCHAR(20)  DEFAULT 'normal' COMMENT '状态: normal/banned',
    owner_id    BIGINT       NULL COMMENT '所属用户ID',
    deleted_at  DATETIME     NULL COMMENT '软删除时间',
    created_at  DATETIME     DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
    updated_at  DATETIME     DEFAULT CURRENT_TIMESTAMP COMMENT '更新时间',
    INDEX idx_tt_bcs_owner (owner_id),
    INDEX idx_tt_bcs_status (status),
    CONSTRAINT fk_tt_bcs_owner FOREIGN KEY (owner_id) REFERENCES users(id)
) ENGINE=InnoDB COMMENT='TT BC 表';

-- tt_accounts — TT 广告账户表（主表，v1.29 补入册）
-- 日期列在 SQLite 里是 `TEXT DEFAULT ''`（空串），MySQL 侧统一收敛为 DATE NULL——
-- 存量迁移时需把 '' 转成 NULL，否则严格模式下写入报错。
CREATE TABLE tt_accounts (
    id                  BIGINT AUTO_INCREMENT PRIMARY KEY,
    name                VARCHAR(255) DEFAULT '' COMMENT '账户名称',
    advertiser_id       VARCHAR(255) NOT NULL COMMENT 'TikTok 广告账户ID（全局唯一）',
    bc_id               BIGINT       NULL     COMMENT '所属 BC',
    country             VARCHAR(100) DEFAULT '' COMMENT '国家',
    agent_id            BIGINT       NULL     COMMENT '代理外键',
    timezone            VARCHAR(50)  DEFAULT '' COMMENT '时区',
    consumption         VARCHAR(50)  DEFAULT '' COMMENT '有无消耗',
    status_id           BIGINT       NULL     COMMENT '状态外键（存活/死亡/验证…）',
    acquired_date       DATE         DEFAULT (CURRENT_DATE) COMMENT '获取日期',
    death_date          DATE         NULL     COMMENT '死亡日期（SQLite 旧值为空串）',
    status_changed_date DATE         NULL     COMMENT '状态变更日期（SQLite 旧值为空串）',
    remark              TEXT         DEFAULT '' COMMENT '备注',
    owner_change_note   TEXT         DEFAULT '' COMMENT '换绑记录（旧归属人转新归属人+月.日，v1.33）',
    owner_id            BIGINT       NULL     COMMENT '归属用户ID',
    deleted_at          DATETIME     NULL     COMMENT '软删除时间',
    created_at          DATETIME     DEFAULT CURRENT_TIMESTAMP,
    updated_at          DATETIME     DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uk_tt_accounts_advertiser (advertiser_id),
    INDEX idx_tt_accounts_bc (bc_id),
    INDEX idx_tt_accounts_owner (owner_id),
    INDEX idx_tt_accounts_status (status_id),
    INDEX idx_tt_accounts_agent (agent_id),
    INDEX idx_tt_accounts_list (owner_id, status_id, deleted_at),
    CONSTRAINT fk_tt_accounts_bc FOREIGN KEY (bc_id) REFERENCES tt_bcs(id),
    CONSTRAINT fk_tt_accounts_agent FOREIGN KEY (agent_id) REFERENCES agents(id),
    CONSTRAINT fk_tt_accounts_status FOREIGN KEY (status_id) REFERENCES account_statuses(id),
    CONSTRAINT fk_tt_accounts_owner FOREIGN KEY (owner_id) REFERENCES users(id)
) ENGINE=InnoDB COMMENT='TT广告账户表';

-- tt_account_bc_history — TT 账户 BC 变更历史（对齐 GG 的 account_mcc_history）
CREATE TABLE tt_account_bc_history (
    id           BIGINT AUTO_INCREMENT PRIMARY KEY,
    account_id   BIGINT       NOT NULL COMMENT '账户ID',
    old_bc_id    BIGINT       NULL     COMMENT '旧BC ID（不设外键：BC 可被硬删）',
    new_bc_id    BIGINT       NULL     COMMENT '新BC ID（不设外键：BC 可被硬删）',
    changed_by   BIGINT       NULL     COMMENT '操作人ID',
    change_type  VARCHAR(20)  NOT NULL DEFAULT 'manual' COMMENT '变更类型: manual/auto',
    created_at   DATETIME     DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_tt_acbh_account (account_id),
    INDEX idx_tt_acbh_changed_by (changed_by),
    CONSTRAINT fk_tt_acbh_account FOREIGN KEY (account_id) REFERENCES tt_accounts(id) ON DELETE CASCADE,
    CONSTRAINT fk_tt_acbh_changed_by FOREIGN KEY (changed_by) REFERENCES users(id)
) ENGINE=InnoDB COMMENT='TT账户BC变更历史';

-- tt_recharge_records — TT 充值记录表（对齐 GG 的 recharge_records）
-- account_id 为【文本】advertiser_id，非 tt_accounts.id，源表即无外键（多账户删除后仍留痕）
CREATE TABLE tt_recharge_records (
    id             BIGINT AUTO_INCREMENT PRIMARY KEY,
    account_id     VARCHAR(255) NOT NULL COMMENT '账户ID（引用 tt_accounts.advertiser_id）',
    amount         VARCHAR(50)  NOT NULL COMMENT '充值金额',
    agent_id       BIGINT       NULL     COMMENT '代理外键',
    operator       VARCHAR(100) DEFAULT '' COMMENT '操作员',
    status         VARCHAR(50)  DEFAULT '' COMMENT '充值状态',
    created_by     BIGINT       NULL     COMMENT '创建者ID',
    sheets_synced  TINYINT      DEFAULT 0 COMMENT 'Google Sheets 同步标记',
    sheets_error   TEXT         NULL     COMMENT 'Sheets 同步错误信息',
    created_at     DATETIME     DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_tt_recharge_account (account_id),
    INDEX idx_tt_recharge_created_by (created_by),
    CONSTRAINT fk_tt_recharge_agent FOREIGN KEY (agent_id) REFERENCES agents(id),
    CONSTRAINT fk_tt_recharge_created_by FOREIGN KEY (created_by) REFERENCES users(id)
) ENGINE=InnoDB COMMENT='TT充值记录表';

-- tt_products — TT 产品表
CREATE TABLE tt_products (
    id              BIGINT AUTO_INCREMENT PRIMARY KEY,
    product_name    VARCHAR(255) NOT NULL COMMENT '产品/群名',
    kpi             VARCHAR(255) DEFAULT '' COMMENT 'KPI',
    region          VARCHAR(100) DEFAULT '' COMMENT '地区',
    status          VARCHAR(20)  DEFAULT 'active' COMMENT '状态: active/paused',
    bc_id           BIGINT       NULL COMMENT '所属 BC',
    sales_person_id BIGINT       NULL COMMENT '商务人员',
    agency_ratio    DOUBLE       DEFAULT 0 COMMENT '代投比例',
    customer        VARCHAR(255) DEFAULT '' COMMENT '客户',
    owner_id        BIGINT       NULL COMMENT '所属用户ID',
    is_archived     TINYINT      DEFAULT 0 COMMENT '是否归档',
    created_at      DATETIME     DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
    updated_at      DATETIME     DEFAULT CURRENT_TIMESTAMP COMMENT '更新时间',
    INDEX idx_tt_products_owner (owner_id),
    INDEX idx_tt_products_region (region),
    INDEX idx_tt_products_bc (bc_id),
    CONSTRAINT fk_tt_products_bc FOREIGN KEY (bc_id) REFERENCES tt_bcs(id),
    CONSTRAINT fk_tt_products_sales FOREIGN KEY (sales_person_id) REFERENCES sales_persons(id),
    CONSTRAINT fk_tt_products_owner FOREIGN KEY (owner_id) REFERENCES users(id)
) ENGINE=InnoDB COMMENT='TT 产品表';

-- tt_product_runners — TT 产品在跑人员关联表
CREATE TABLE tt_product_runners (
    product_id BIGINT NOT NULL COMMENT '产品ID',
    user_id    BIGINT NOT NULL COMMENT '在跑人员用户ID',
    PRIMARY KEY (product_id, user_id),
    INDEX idx_tt_product_runners_user (user_id),
    CONSTRAINT fk_tt_runners_product FOREIGN KEY (product_id) REFERENCES tt_products(id) ON DELETE CASCADE,
    CONSTRAINT fk_tt_runners_user FOREIGN KEY (user_id) REFERENCES users(id)
) ENGINE=InnoDB COMMENT='TT 产品在跑人员关联表';

-- tt_packages — TT 产品包表
CREATE TABLE tt_packages (
    id           BIGINT AUTO_INCREMENT PRIMARY KEY,
    product_id   BIGINT NOT NULL COMMENT '所属产品',
    type         VARCHAR(20)  DEFAULT 'package' COMMENT '类型: package/pwa',
    series_name  VARCHAR(255) DEFAULT '' COMMENT '系列名',
    package_name VARCHAR(255) DEFAULT '' COMMENT '包名',
    url          VARCHAR(500) DEFAULT '' COMMENT '链接',
    status       VARCHAR(20)  DEFAULT '' COMMENT '状态: normal/no_events/paused/dropped/rejected',
    created_at   DATETIME     DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
    updated_at   DATETIME     DEFAULT CURRENT_TIMESTAMP COMMENT '更新时间',
    INDEX idx_tt_packages_product (product_id),
    INDEX idx_tt_packages_type (type),
    CONSTRAINT fk_tt_packages_product FOREIGN KEY (product_id) REFERENCES tt_products(id) ON DELETE CASCADE
) ENGINE=InnoDB COMMENT='TT 产品包表';

-- tt_delist_checks — TT 掉包检测结果表
CREATE TABLE tt_delist_checks (
    id          BIGINT AUTO_INCREMENT PRIMARY KEY,
    package_id  BIGINT NOT NULL COMMENT '包ID',
    is_delisted TINYINT DEFAULT 0 COMMENT '是否掉包',
    checked_at  DATETIME DEFAULT CURRENT_TIMESTAMP COMMENT '检测时间',
    UNIQUE KEY uk_tt_delist_package (package_id),
    CONSTRAINT fk_tt_delist_package FOREIGN KEY (package_id) REFERENCES tt_packages(id) ON DELETE CASCADE
) ENGINE=InnoDB COMMENT='TT 掉包检测结果表';

-- tt_delist_notifications — TT 掉包通知状态表（v1.30 补入册）
-- 与 GG 的 delist_notifications（见上「27.」）同构，仅平台不同；TT 掉包通知走独立的
-- tt_telegram 机器人。`UNIQUE(package_id, user_id)` 是「每包每用户一条」的幂等键。
-- 删包 / 批量删包时 Python 侧会同步清理本表行，故此处用 ON DELETE CASCADE 兜底。
CREATE TABLE tt_delist_notifications (
    id              BIGINT AUTO_INCREMENT PRIMARY KEY,
    package_id      BIGINT  NOT NULL COMMENT '包ID',
    user_id         BIGINT  NOT NULL COMMENT '用户ID',
    first_notified  TINYINT DEFAULT 0 COMMENT '是否已首次通知',
    dismissed_at    DATETIME NULL     COMMENT '关闭时间',
    reminder_count  INT     DEFAULT 0 COMMENT '提醒次数',
    UNIQUE KEY uk_tt_dn_package_user (package_id, user_id),
    INDEX idx_tt_dn_user (user_id),
    CONSTRAINT fk_tt_dn_package FOREIGN KEY (package_id) REFERENCES tt_packages(id) ON DELETE CASCADE,
    CONSTRAINT fk_tt_dn_user FOREIGN KEY (user_id) REFERENCES users(id)
) ENGINE=InnoDB COMMENT='TT 掉包通知状态表';

-- tt_product_assets — TT 产品素材表
CREATE TABLE tt_product_assets (
    id              BIGINT AUTO_INCREMENT PRIMARY KEY,
    product_id      BIGINT NOT NULL COMMENT '所属产品',
    video_id        VARCHAR(255) NOT NULL COMMENT '素材视频ID',
    video_owner_id  BIGINT NOT NULL DEFAULT 1 COMMENT '素材所属用户ID',
    added_by        BIGINT NULL COMMENT '添加人用户ID',
    added_at        DATETIME DEFAULT CURRENT_TIMESTAMP COMMENT '添加时间',
    UNIQUE KEY uk_tt_asset (product_id, video_id),
    INDEX idx_tt_assets_product (product_id),
    INDEX idx_tt_assets_video (video_id),
    CONSTRAINT fk_tt_assets_product FOREIGN KEY (product_id) REFERENCES tt_products(id),
    CONSTRAINT fk_tt_assets_added_by FOREIGN KEY (added_by) REFERENCES users(id)
) ENGINE=InnoDB COMMENT='TT 产品素材表';

-- ============================================================
-- 九、初始化数据
-- ============================================================

-- 默认 developer 账户（密码: admin123，BCrypt 编码）
INSERT INTO users (username, password, role, display_name, platform)
VALUES ('admin', '$2a$10$...', 'developer', '系统管理员', 'gg');

-- 默认标签数据
INSERT INTO tags (`key`, `value`) VALUES
('regions', '["巴西","菲律宾","孟加拉","印尼","东南亚通用","通用"]'),
('frame_types', '["融帧","非融帧"]'),
('effectiveness', '["","成效","一般"]'),
('review_statuses', '["能过审","不能过审"]'),
('product_names', '["p222","93ok"]');

-- 默认账户状态
INSERT INTO account_statuses (name, owner_id, platform) VALUES
('存活', NULL, 'gg'),
('死亡', NULL, 'gg'),
('验证', NULL, 'gg'),
('限额', NULL, 'gg');

-- FB 平台账户状态（与 GG 独立）
INSERT INTO account_statuses (name, owner_id, platform) VALUES
('存活', NULL, 'fb'),
('死亡', NULL, 'fb'),
('验证', NULL, 'fb'),
('限额', NULL, 'fb');

-- TT 回收原因（全平台公用词表，v1.29；取自现网 temp/app.db 存量）
-- owner_id 置 NULL 表示系统预置，任何非 viewer 的 TT 用户均可改名/删除
INSERT INTO tt_recycle_reasons (name, owner_id) VALUES
('封禁回收', NULL),
('拒审回收', NULL),
('端口回收', NULL);
```

---

## 6. API Controller 设计

### 6.1 统一响应格式

保持与现有前端完全兼容。**关键兼容性说明**：Python `helpers.py` 的 `ok()` 函数对 `dict` 参数做展平处理，
导致分页列表使用 `items` 字段名而非 `data`。前端代码统一读取 `response.items`，Java 端必须保持一致。

```json
// 单对象成功响应（Python: ok(non_dict) → {"success": true, "data": ...}）
{
    "success": true,
    "data": { ... }
}

// 分页列表响应（Python: ok({'items':..., 'total':...}) → 展平到顶层）
{
    "success": true,
    "items": [...],            // 注意：字段名是 items，不是 data
    "total": 100,
    "page": 1,
    "size": 20
}

// 纯列表响应（无分页，Python: ok([...]) → {"success": true, "data": [...]}）
{
    "success": true,
    "data": [...]
}

// 错误响应
{
    "success": false,
    "error": "错误描述"
}
```

```java
// 统一响应 DTO
@Data
@AllArgsConstructor
@NoArgsConstructor
public class ApiResponse<T> {
    private boolean success;
    @JsonInclude(JsonInclude.Include.NON_NULL)
    private T data;
    @JsonInclude(JsonInclude.Include.NON_NULL)
    private String error;

    public static <T> ApiResponse<T> ok(T data) {
        return new ApiResponse<>(true, data, null);
    }

    public static <T> ApiResponse<T> ok() {
        return new ApiResponse<>(true, null, null);
    }

    public static <T> ApiResponse<T> fail(String error) {
        return new ApiResponse<>(false, null, error);
    }
}

// 分页响应（独立类 — 字段名必须与 Python 对齐：items 而非 data）
@Data
public class PagedResponse<T> {
    private boolean success = true;
    private List<T> items;      // 关键：使用 items，不是 data
    private long total;
    private int page;
    private int size;

    public static <T> PagedResponse<T> of(List<T> items, long total, int page, int size) {
        PagedResponse<T> resp = new PagedResponse<>();
        resp.setItems(items);
        resp.setTotal(total);
        resp.setPage(page);
        resp.setSize(size);
        return resp;
    }
}
```

### 6.2 Controller 示例

以下选取代表性的 Controller 展示设计思路，完整 20+ Controller 按相同模式实现。

#### AuthController

```java
@RestController
@RequestMapping("/api/auth")
@RequiredArgsConstructor
public class AuthController {

    private final AuthService authService;
    private final JwtTokenProvider jwtTokenProvider;

    // POST /api/auth/login
    @PostMapping("/login")
    public ApiResponse<LoginResponse> login(@Valid @RequestBody LoginRequest req) {
        LoginResult result = authService.login(req.getUsername(), req.getPassword());
        if (result == null) {
            return ApiResponse.fail("Invalid credentials or account disabled");
        }
        return ApiResponse.ok(LoginResponse.builder()
            .accessToken(result.getAccessToken())
            .refreshToken(result.getRefreshToken())
            .user(result.getUser())
            .build());
    }

    // POST /api/auth/register
    @PostMapping("/register")
    public ApiResponse<UserDto> register(@Valid @RequestBody RegisterRequest req) {
        UserDto user = authService.register(
            req.getUsername(), req.getPassword(), req.getDisplayName());
        if (user == null) return ApiResponse.fail("Registration failed");
        return ApiResponse.ok(user);
    }

    // GET /api/auth/me
    @GetMapping("/me")
    public ApiResponse<UserDto> me(@AuthenticationPrincipal UserPrincipal principal) {
        UserDto user = authService.getUserById(principal.getUserId());
        if (user == null) return ApiResponse.fail("User not found");
        return ApiResponse.ok(user);
    }

    // PUT /api/auth/password
    @PutMapping("/password")
    public ApiResponse<Void> changePassword(
            @AuthenticationPrincipal UserPrincipal principal,
            @Valid @RequestBody ChangePasswordRequest req) {
        authService.changePassword(principal.getUserId(),
            req.getOldPassword(), req.getNewPassword());
        return ApiResponse.ok();
    }

    // PUT /api/auth/profile
    @PutMapping("/profile")
    public ApiResponse<UserDto> updateProfile(
            @AuthenticationPrincipal UserPrincipal principal,
            @Valid @RequestBody UpdateProfileRequest req) {
        UserDto updated = authService.updateProfile(principal.getUserId(),
            req.getDisplayName());
        return ApiResponse.ok(updated);
    }

    // GET /api/auth/names
    @GetMapping("/names")
    public ApiResponse<List<UserNameDto>> userNames(
            @AuthenticationPrincipal UserPrincipal principal) {
        return ApiResponse.ok(authService.getUserNames(principal));
    }

    // ... 其余 auth 路由 (custom-name, email, telegram-username)
}
```

#### FbBmController

```java
@RestController
@RequestMapping("/api/fb/bms")
@RequiredArgsConstructor
@FbPlatformRequired  // 自定义注解：需要 JWT + FB 平台
public class FbBmController {

    private final FbService fbService;

    // GET /api/fb/bms/list
    @GetMapping("/list")
    public PagedResponse<FbBmDto> list(
            @AuthenticationPrincipal UserPrincipal principal,
            @RequestParam(defaultValue = "1") int page,
            @RequestParam(defaultValue = "20") int size,
            @RequestParam(required = false) String status) {
        return fbService.listBms(principal.getUserId(), page, size, status);
    }

    // GET /api/fb/bms/unified — 统一列表（含 Pixel BM）
    @GetMapping("/unified")
    public PagedResponse<FbBmDto> listUnified(
            @AuthenticationPrincipal UserPrincipal principal,
            @RequestParam(defaultValue = "1") int page,
            @RequestParam(defaultValue = "20") int size,
            @RequestParam(required = false) String search,
            @RequestParam(required = false) String status,
            @RequestParam(required = false) String bmType) {
        return fbService.listUnifiedBms(principal.getUserId(), page, size,
            search, status, bmType);
    }

    // POST /api/fb/bms/create
    @PostMapping("/create")
    public ApiResponse<Long> create(
            @AuthenticationPrincipal UserPrincipal principal,
            @Valid @RequestBody CreateFbBmRequest req) {
        Long id = fbService.createBm(principal.getUserId(),
            req.getName(), req.getBmId(), req.getNote());
        return ApiResponse.ok(id);
    }

    // PUT /api/fb/bms/{bid}
    @PutMapping("/{bid}")
    public ApiResponse<Void> update(
            @AuthenticationPrincipal UserPrincipal principal,
            @PathVariable Long bid,
            @Valid @RequestBody UpdateFbBmRequest req) {
        fbService.updateBm(principal.getUserId(), bid,
            req.getName(), req.getNote());
        return ApiResponse.ok();
    }

    // DELETE /api/fb/bms/{bid}
    @DeleteMapping("/{bid}")
    public ApiResponse<Void> delete(
            @AuthenticationPrincipal UserPrincipal principal,
            @PathVariable Long bid) {
        fbService.softDeleteBm(principal.getUserId(), bid);
        return ApiResponse.ok();
    }

    // POST /api/fb/bms/{bid}/ban-and-migrate
    @PostMapping("/{bid}/ban-and-migrate")
    public ApiResponse<BanMigrateResult> banAndMigrate(
            @AuthenticationPrincipal UserPrincipal principal,
            @PathVariable Long bid,
            @Valid @RequestBody BanMigrateRequest req) {
        return ApiResponse.ok(fbService.banAndMigrate(bid,
            req.getTargetBmId(), req.getTargetBmName()));
    }

    // GET /api/fb/bms/options
    @GetMapping("/options")
    public ApiResponse<List<OptionDto>> options() {
        return ApiResponse.ok(fbService.getBmOptions());
    }
}
```

#### AccountController (GG)

```java
@RestController
@RequestMapping("/api/accounts")
@RequiredArgsConstructor
public class AccountController {

    private final AccountService accountService;

    // GET /api/accounts/list
    @GetMapping("/list")
    public PagedResponse<AccountDto> list(
            @AuthenticationPrincipal UserPrincipal principal,
            @RequestParam(defaultValue = "1") int page,
            @RequestParam(defaultValue = "20") int size,
            @RequestParam(required = false) String search,
            @RequestParam(required = false) Long statusId,
            @RequestParam(required = false) Long mccId,
            @RequestParam(required = false) Long agentId,
            @RequestParam(required = false) String sort,
            @RequestParam(required = false) String order) {
        return accountService.listAccounts(principal.getUserId(),
            AccountQuery.builder()
                .page(page).size(size)
                .search(search).statusId(statusId)
                .mccId(mccId).agentId(agentId)
                .sort(sort).order(order)
                .build());
    }

    // POST /api/accounts/create
    @PostMapping("/create")
    public ApiResponse<Long> create(
            @AuthenticationPrincipal UserPrincipal principal,
            @Valid @RequestBody CreateAccountRequest req) {
        return ApiResponse.ok(accountService.createAccount(
            principal.getUserId(), req));
    }

    // PUT /api/accounts/{aid}
    @PutMapping("/{aid}")
    public ApiResponse<Void> update(
            @AuthenticationPrincipal UserPrincipal principal,
            @PathVariable Long aid,
            @Valid @RequestBody UpdateAccountRequest req) {
        accountService.updateAccount(principal.getUserId(), aid, req);
        return ApiResponse.ok();
    }

    // POST /api/accounts/batch-update
    @PostMapping("/batch-update")
    public ApiResponse<Long> batchUpdate(
            @AuthenticationPrincipal UserPrincipal principal,
            @Valid @RequestBody BatchUpdateRequest req) {
        return ApiResponse.ok(accountService.batchUpdate(principal.getUserId(), req));
    }

    // POST /api/accounts/sync-from-sheet（双向同步）
    //   dry_run=true: 返回 diff（to_create / to_update / unchanged）
    //   dry_run=false: 执行创建+状态更新 → db.commit() → 系统→Sheet 同步 F列(备注)+H列(是否解绑)
    //   跳过 H列="解绑" 的账户，跳过系统已逻辑删除的账户
    @PostMapping("/sync-from-sheet")
    public ApiResponse<SyncResult> syncFromSheet(
            @AuthenticationPrincipal UserPrincipal principal,
            @Valid @RequestBody SyncRequest req) {
        return ApiResponse.ok(accountService.syncFromSheet(
            principal.getUserId(), req));
    }

    // DELETE /api/accounts/{aid} — 软删除（设 deleted_at，后台写 Sheet H列"解绑"）
    // POST /api/accounts/{aid}/restore — 恢复（清 deleted_at，后台清 Sheet H列）
    // DELETE /api/accounts/{aid}/permanent — 物理删除（不可恢复，清充值记录+MCC历史）
    // GET /api/accounts/deleted — 已删除账户列表
    // ... 其余路由 (batch-delete, batch-lookup, lookup, recharge-records, mcc-history, ...)
}
```

#### ProductController (GG)

```java
@RestController
@RequestMapping("/api/products")
@RequiredArgsConstructor
public class ProductController {

    private final ProductService productService;

    // POST /api/products/create — 创建产品（含同名冲突检测）
    //   前置：校验 product_name → 初始化上下文（db/user_id）→ sales_person 兼容处理
    //   sales_person 兼容：仅传 sales_person（字符串）时，查/建 sales_persons 表得到 sales_person_id
    //     （Python 原实现曾把该处理放在 db/user_id 初始化之前，存在 UnboundLocalError 隐患，迁移时注意顺序）
    //   逻辑：先按 product_name 查同名产品（不过滤 is_archived/deleted_at/status）
    //     · 同名产品已删除 (is_archived=1 或 deleted_at 非空) → 返回 409 + {conflict:"deleted", product_id, product_name}
    //     · 同名产品已暂停 (status="paused")               → 返回 409 + {conflict:"paused", product_id, product_name}
    //     · 同名产品正常                                     → 追加包/更新字段 + 加入 runner
    //     · 无同名产品                                       → 新建
    //   前端收到 409 后弹窗询问"该产品已删除/已暂停，是否恢复？"
    @PostMapping("/create")
    public ApiResponse<Long> create(
            @AuthenticationPrincipal UserPrincipal principal,
            @Valid @RequestBody CreateProductRequest req) {
        return productService.createProduct(principal.getUserId(), req);
    }

    // POST /api/products/{pid}/restore — 恢复已删除或已暂停的产品
    //   普通用户可操作（无需 developer/admin 确认）
    //   · 已删除产品：is_archived=0, deleted_at=null，并从 audit_log 快照恢复关联包
    //   · 已暂停产品：status=""（恢复正常）
    @PostMapping("/{pid}/restore")
    public ApiResponse<RestoreResult> restore(
            @AuthenticationPrincipal UserPrincipal principal,
            @PathVariable Long pid) {
        return ApiResponse.ok(productService.restoreProduct(pid));
    }
}
```

> **说明（v1.7 新增）**：原 Python `products_create` 的 existing 查询未过滤 `is_archived`/`deleted_at`，
> 导致创建与已删除产品同名的产品时静默更新旧记录（返回 200 但产品不可见）。
> 迁移时改为：创建接口先做冲突检测返回 409，新增独立 restore 接口统一处理"已删除/已暂停"两类恢复，
> 且恢复不再要求 developer 权限。

#### GoogleSheetsController

```java
@RestController
@RequestMapping("/api/google-sheets")
@RequiredArgsConstructor
public class GoogleSheetsController {

    private final GoogleSheetsService sheetsService;

    // POST /api/google-sheets/update-zuobiao — 做表数据写入（产品校验 + 入库 + 后台同步 Sheet）
    //   前置校验：
    //     1. product_name 必填（空 → 400 "产品名不能为空"）
    //     2. rows 必填（空 → 400 "做表数据不能为空"）
    //   产品/包名校验（核心，迁移易漏，详见下方 validateProductMatches）：
    //     查该 product_name 下正常状态包的 series_name，与 rows 的 campaign 求交集
    //       · 有交集                          → 放行
    //       · 无交集 且 无养户行(is_yanghu)    → 400 "产品选择有误！..."
    //       · 无交集 但有养户行                → 放行，响应附 warning 字段（前端弹警告）
    //   通过后：非养户行入库 ad_reports（同键覆盖）→ 后台线程写 Sheets
    @PostMapping("/update-zuobiao")
    public ApiResponse<UpdateZuobiaoResponse> updateZuobiao(
            @AuthenticationPrincipal UserPrincipal principal,
            @Valid @RequestBody UpdateZuobiaoRequest req) {
        return ApiResponse.ok(sheetsService.updateZuobiao(principal.getUserId(), req));
    }

    // GET /api/google-sheets/sync-status — 查询指定产品 Sheets 同步失败记录（含行数据）
    // POST /api/google-sheets/retry-sync — 手动重试做表数据 Sheets 同步
    // GET /api/google-sheets/status — Google Sheets API 配置状态
    // GET /api/google-sheets/sheets — 读取 spreadsheet 所有 sheet 列表
}
```

产品/包名校验逻辑（Service 层）：

```java
/**
 * 校验产品包系列与数据广告系列是否匹配。
 * @return 匹配/无包返回 null；不匹配但有养户行时返回 warning 文案；不匹配且无养户行时抛 BusinessException。
 */
private String validateProductMatches(String productName, List<ZuobiaoRow> rows) {
    // 1. 查该产品下正常状态的包系列名
    Set<String> pkgNames = packageRepository
        .findSeriesNamesByProductName(productName).stream()
        .map(s -> s == null ? "" : s.trim())
        .filter(s -> !s.isEmpty())
        .collect(Collectors.toSet());
    if (pkgNames.isEmpty()) {
        return null;  // 产品无包，跳过校验
    }
    // 2. 取数据中的广告系列名，求交集
    Set<String> campaigns = rows.stream()
        .map(r -> r.getCampaign() == null ? "" : r.getCampaign().trim())
        .filter(s -> !s.isEmpty())
        .collect(Collectors.toSet());
    Set<String> matched = new HashSet<>(pkgNames);
    matched.retainAll(campaigns);
    if (!matched.isEmpty()) {
        return null;  // 有交集，放行
    }
    // 3. 无交集 → 看是否含养户行
    boolean hasYanghu = rows.stream().anyMatch(ZuobiaoRow::isYanghu);
    if (!hasYanghu) {
        throw new BusinessException(
            "产品选择有误！「" + productName + "」的包系列与数据中的广告系列不匹配，请重新选择产品。");
    }
    // 4. 有养户行但非养户行不匹配 → 放行并返回警告
    return "⚠️ 产品「" + productName + "」的包系列与数据中的非养户广告系列不匹配，请确认产品选择是否正确。";
}
```

> **说明（v1.9 新增）**：此校验在 Python 位于 `main.py` 的 `google_sheets_update_zuobiao` 接口层
> （不在 `google_sheets_service.upsert_zuobiao` 服务函数内），迁移文档此前未记录，极易遗漏。
> 三种场景行为对照：
>
> | 场景 | 行为 |
> |------|------|
> | 非养户行与包系列有交集 | 正常放行 |
> | 无交集 + 无养户行 | 阻断，400 "产品选择有误！..." |
> | 无交集 + 有养户行 | 放行 + 响应 `warning` 字段（前端 8 秒警告弹窗，可关闭） |
>
> 前端 `ToolkitView.vue` 收到 `warning` 后调用 `ElMessage.warning({ duration: 8000, showClose: true })`。
>
> **说明（v1.20 新增）**：前端 `is_yanghu` 的判定来源已变更——原实现为 `zbYanghu(勾选7列) || 命中养户关键词`，v1.20 起改为**仅按系列名（campaign）命中养户关键词**（`zbYanghuKeywords`，默认 `['养户','Website traffic-Search','Campaign #1']`，可在输入框增删）。原因：Google 报告现调不出「安装/应用」指标，7 列数据也是真实投放数据而非养户，是否养户应只看系列名。前端变量语义化：`zbYanghu`→`zbSevenCols`（7列格式）、`parseAdsData` 参数 `isYanghu`→`isSevenCols`。**后端契约不变**：`is_yanghu` 仍由前端逐行传入，`ZuobiaoRow.isYanghu` 字段与 `validateProductMatches` 逻辑均无需改动；非养户的 7 列行会入库 `ad_reports`，`installs/in_app_actions/cost_per_in_app` 按 0 写（覆盖旧值，7 列解析本无这三列）。

### 6.3 完整 Controller 清单

| Controller | 路由前缀 | 接口数 | 认证 |
|---|---|---|---|
| `AuthController` | `/api/auth/*` | 12 | 混合 |
| `FbBmController` | `/api/fb/bms/*` | 7 | JWT + FB |
| `FbAccountController` | `/api/fb/accounts/*` | 8 | JWT + FB |
| `FbProductController` | `/api/fb/products/*` | 8 | JWT + FB |
| `FbLineController` | `/api/fb/lines/*` | 3 | JWT + FB |
| `FbPixelBmController` | `/api/fb/pixel-bms/*` | 5 | JWT + FB |
| `FbPixelController` | `/api/fb/pixels/*` | 5 | JWT + FB |
| `FbExtractController` | `/api/fb/extract/*` | 3 | JWT + FB |
| `FbReportController` | `/api/fb/reports/*` | 9 | JWT + FB |
| `FbUserController` | `/api/fb/users` | 1 | JWT + FB |
| `ProductController` | `/api/products/*` | 18 | JWT + 混合 |
| `AccountController` | `/api/accounts/*` | 21 | JWT |
| `MccController` | `/api/mcc/*` | 8 | JWT |
| `RechargeController` | `/api/recharge/*` | 5 | JWT |
| `AdReportController` | `/api/ad-reports/*` | 17 | JWT |
| `YoutubeController` | `/api/youtube/*` | 16 | JWT |
| `ScrapeController` | `/api/scrape/*` | 5 | JWT |
| `VideoController` | `/api/video/*`, `/api/audio*` | 16 | 混合 |
| `FontController` | `/api/fonts/*` | 7 | 无 |
| `CopywritingController` | `/api/copywriting/*` | 5 | JWT |
| `AdminUserController` | `/api/admin/users/*` | 8 | JWT + Admin |
| `AdminDataController` | `/api/admin/data/*` | 2 | Admin |
| `AdminTriggerController` | `/api/admin/trigger-*` | **3**（v1.35 更正：此前漏记 `trigger-tt-delist-check`） | **按平台 admin / developer（v1.35）** |
| `AdminSchedulerController` | `GET/PUT /api/admin/scheduler/config` | 2（v1.35 新增） | **按平台 admin / developer（v1.35）** |
| `ConfigController` | `/api/config/*` | 6 | JWT |
| `SettingsController` | `/api/settings/*` | 2 | JWT |
| `OptionController` | `/api/{agents\|statuses\|mcc-levels\|sales-persons\|regions}/*` | 20 | JWT |
| `DataController` | `/api/data/*` | 3 | JWT |
| `AuditController` | `/api/audit-log/*` | 2 | JWT |
| `DelistController` | `/api/delist/*` | 2 | JWT |
| `UtilityController` | `/api/browse-*`, `/api/translate` | 5 | 混合 |
| `GoogleSheetsController` | `/api/google-sheets/*` | 4 | JWT |
| `GoogleAdsController` | `/api/google-ads/*` | 2 | 无 |
| `TtController` | `/api/tt/*` | 28 | JWT |
| `HuguanDashboardController` | `/api/huguan/dashboard*` | 5 | JWT + 户管 |
| **合计** | | **273** | |

> **说明（v1.10 新增）**：`DelistController` 的 `delist/pending` 返回**产品聚合**结构
> （`{ product_id, product_name, series_names[], package_ids[], type, reminder_count }`），
> `delist/dismiss` 入参为 `package_ids[]`（批量）。对应 Python 端 `delist_pending` / `delist_dismiss`
> 已同步改造为按产品聚合/批量关闭；前端 `App.vue` 按产品统一弹窗、`ProductPanel.vue` 支持多包跳转高亮。
>
> **说明（v1.13 新增）**：掉包通知查询必须**同时过滤包状态与产品状态**，否则暂停/删除的产品仍会弹通知：
> - `GET /api/products/delist-status` 与 `GET /api/delist/pending` 的 WHERE 除过滤 `pkg.status`（`IS NULL/''/'0'`，排除 dropped/paused 包）外，还必须过滤 `prod.status`（`IS NULL/''/'0'`，排除 paused/dropped 产品）。
> - 漏掉 `prod.status` 的后果：产品暂停后，只要掉包的包未手动标成 `dropped`，前端 `App.vue` 每 30 秒轮询 `delist/pending` 仍命中，反复弹「首次通知」+ 关闭 3 分钟后的「提醒通知」。
> - Python 端定时检测 `_run_delist_check_once` 一直含 `prod.status` 过滤；`delist-status`/`delist/pending` 曾缺失，已于 v1.13 补齐。迁移到 Spring Boot 的 DelistService 时务必保留此过滤。
>
> **说明（v1.17 新增）**：掉包检测与数据库迁移存在 SQLite 写锁并发问题，迁移到 Spring Boot 时注意：
> - `_run_delist_check_once` 不得在慢网络请求期间持有写事务——先并行完成所有 URL 检测、收集结果，循环结束后再一次性写入 `delist_checks` 并提交。
> - 迁移标记（`config` 表的 claim key）应「先查后写」，已迁移后每个请求只读不写，避免每个请求都抢写锁。
> - MySQL/InnoDB 下虽为行锁而非库级写锁，但同样应避免长事务跨越外部网络调用（会长时间占用连接与锁）。
>
> **说明（v1.18 新增）**：请求入口的数据库连接绑定必须跳过静态资源与页面请求。Python 端 `_attach_db`（`before_request`）此前对每个请求无条件 `database.get_db()`，导致 `/assets/*.js` 等静态资源在数据库被占用时抛 `database is locked` → 500，前端动态 import 的 chunk 加载失败、页面跳不过去。修复为仅对 `/api/` 请求打开数据库连接。另注意：静态资源缓存（`_add_static_cache`）必须跳过错误响应，否则 500 会被 `Cache-Control: max-age` 缓存 1 年造成缓存污染（表现为换浏览器才好）。迁移到 Spring Boot 时：不要在全局 Filter / Interceptor / `@RequestScope` 初始化里对所有请求做数据库访问，应排除静态资源与 SPA 页面（Spring Security `permitAll` + 静态资源 handler 通常已覆盖，但仍需注意自定义 Filter 不得无条件查库）；静态资源缓存策略（`CacheControl` / `CacheWebFilter`）同样必须对错误响应禁用缓存。
>
> **说明（v1.19 新增）**：掉包检测改为走代理 IP，迁移到 Spring Boot 的 DelistChecker 时注意：
> - 新增 `delist_proxy` 配置段（`enabled` / `max_retries` / `proxies[]`，每个代理含 `ip`/`port`/`username`/`password`/`scheme`）。`enabled=false` 或 `proxies` 为空时**完全回退直连**（与历史行为一致，出问题可一键关闭）。
> - 代理池按 `(ip, port)` 去重，随机取一个；请求失败（连接失败/超时）时换下一个代理重试，最多 `max_retries` 次。
> - **关键：区分「代理挂了」和「真掉包」**。代理全部失败时返回 `is_delisted=false` + 带「代理」标识的 error（如 `代理全部失败: ...`），**绝不误判为掉包**；仅当通过代理拿到明确 404 / 关键词时才判 `is_delisted=true`。
> - Java 侧映射：`py/proxy_pool.py` → `delist/DelistProxyPool.java`（解析配置、去重、随机取用、生成代理参数）；`check_url_delisted(url, proxy_pool)` → `DelistChecker.checkUrlDelisted(url, proxyPool)`。**注意 `RestTemplate` 默认不支持按请求动态切换代理**（`SimpleClientHttpRequestFactory.setProxy()` 为全局单一代理），需用 Apache HttpClient（每请求 `RequestConfig`/`HttpClientContext` 指定 proxy）或 OkHttp（每请求 `newBuilder().proxy(...)`）实现逐请求换代理。
>
> **说明（v1.22 新增）**：TT 平台（`TtController`）共 28 个接口，端点分组如下：
> - **BC**（5）：`GET/POST /api/tt/bcs/list|create`、`PUT/DELETE /api/tt/bcs/{id}`、`GET /api/tt/bcs/options`
> - **产品**（9）：`GET /api/tt/products/list`、`GET /api/tt/products/runner-products`、`POST /api/tt/products/create`、`PUT/DELETE /api/tt/products/{id}`、`POST /api/tt/products/{id}/restore`、`GET /api/tt/products/{id}/detail`、`POST /api/tt/products/merge`、`POST /api/tt/products/import-text`
> - **包**（4）：`POST /api/tt/products/{id}/packages`、`PUT/DELETE /api/tt/packages/{id}`、`POST /api/tt/packages/batch-delete`
> - **掉包**（2）：`POST /api/tt/products/{id}/check-delist`、`GET /api/tt/products/delist-status`
> - **素材**（3）：`GET/POST /api/tt/products/{id}/assets`、`DELETE /api/tt/products/{id}/assets/{videoId}`
> - **用户**（1）：`GET /api/tt/users`
> - **设置**（2，v1.22 新增，权限于 v1.27 修订）：`GET/POST /api/tt/settings`（`sheet_id` 与 `accounts/recharge/recycle` 三个内置映射存全局 tags，仅 admin/developer 可写；`my_dashboard` 为投手私有，各用户写各自 config 表 `tt_sheet_mappings_<uid>`）
> - **数据**（2，v1.22 新增）：`GET /api/tt/data/export`、`POST /api/tt/data/import`
> - 商务人员/地区复用 `OptionController`（`/api/sales-persons/*`、`/api/regions/*`），通过 `platform=tt` 隔离；`sales_persons_delete` 需补 `tt_products` 引用检查与解除引用（原只查 GG `products`/FB `fb_products`），否则删除被 TT 产品引用的商务人员会悬空
>
> **TT 数据导出/导入迁移要点（v1.23 补充）**：
> - **导出**（`GET /api/tt/data/export`）：`tt_bcs`（`owner_id=? AND deleted_at IS NULL`）与 `tt_products`（`owner_id=? AND is_archived=0`）按当前用户 owner 隔离；`tt_packages`/`tt_product_runners`/`tt_delist_checks` 由上述产品/包 id 推导（不跨 owner）；`sales_persons` 导出 `platform='tt'` 全量（商务人员为平台级共享选项，供导入映射）。返回 `{version, exported_at, source:"tt-server", data:{bcs,products,packages,product_runners,delist_checks,sales_persons}}` 附件下载。
> - **导入**（`POST /api/tt/data/import`，multipart `.json`）：按外键依赖顺序重建并建 `old_id→new_id` 映射——① sales_persons 按 name 匹配/新建（platform='tt'）；② tt_bcs 优先复用本人（`bc_id=? AND owner_id=?`），否则按全局唯一 `bc_id` 复用（bc_id 全局 UNIQUE，无法重复建）；③ tt_products `owner_id=当前用户`、映射 bc_id/sales_person_id；④ tt_packages 映射 product_id；⑤ tt_product_runners 映射 product_id、`user_id=当前用户`；⑥ tt_delist_checks 映射 package_id。**owner_id 全部重映射为当前导入用户**，杜绝横向越权。
> - **健壮性**：JSON 结构强校验（各数据块强制为 dict 列表，非 dict 元素/缺 id 跳过）；事务失败 `rollback`（返回 400，不落半截数据）；上传限 20MB。SQLite 用 `PRAGMA foreign_keys=OFF/ON`，MySQL 侧对应 `SET foreign_key_checks=0/1`（建议在 `@Transactional` 内完成、异常自动回滚）。
> - **范围取舍**：`tt_product_assets`（素材，关联 videos）不导出/导入；仅支持 `.json`（不支持 GG 的 `.db` 旧库导入）。
>
> **TT 账户同步状态驱动迁移要点（v1.24 补充）**：
> - `TtAccountController` 新增 `POST /api/tt/accounts/sync-from-sheet`（对应 `py/routes/tt_accounts_routes.py` 的 `sync_from_sheet`）：读「我的看板」Sheet A:J 列，跳过表头第一行，按 D 列账户ID过滤，A 列「运营」匹配当前用户 display_name 门禁（不匹配则拒绝同步）。⚠️ **这是 TT 自己的「我的看板」（10 列），与 GG 的 8 列同名不同表 —— 完整列模型、配置三层来源、冲突裁决契约与迁移红线见 §8.1 的「我的看板是两张不同的表」子节**。
> - **状态推导**：C 列「是否回收」`是` → 死亡、`可用`/空 → 存活。dry_run 返回 `{dry_run, total, created[], updated[], conflicts[], status_conflicts[]}`，其中 `created` 条目含 `status`，`status_conflicts` 条目为 `{advertiser_id, sheet_status, system_status}`。
> - **冲突确认契约**：confirm 请求 `{dry_run:false, resolutions:{}, status_resolutions:{advertiser_id:"存活"|"死亡"}}`；`status_resolutions` 只含用户选「以 Sheet 为准」的项，value 为目标状态名。
> - **越权保护**：`status_resolutions`/`resolutions` 仅允许改当前用户看板行内的 `advertiser_id`（`valid_ids`），非 admin/developer 角色带 `owner_id` 条件。
> - **death_date 维护**：改为「死亡」置当天、改为「存活」清空，与手动改状态（`updateAccount`）保持一致；新户为死亡时 INSERT 同步写 death_date。
> - **不写回收清单**：状态同步路径不触发 `_trigger_recycle_if_dead`（回收户清单是上游数据源，同步只反映状态，Java 侧对应回收清单写入逻辑不得被调用）。
>
> **TT 充值写表迁移要点（v1.25 补充）**：
> - TT 充值表（Google Sheets）为 9 列表头：`时间 | 账户ID | 金额 | 代理 | 运营 | 是否充值 | 账户ID | 金额锁定 | 是否处理`。系统**只写前 3 列**（时间/账户ID/金额），第 4~9 列（代理/运营/是否充值/账户ID/金额锁定/是否处理）在表格里已有公式、写入时**不得覆盖**。
> - 列映射（`append_recharge_tt` → Java `GoogleSheetsService.appendRechargeTt`）：A 列时间 = 当前日期「月/日」（如 `9/22`），前导 `'` 标记为文本（防止被解析为日期）；B 列账户ID = 文本（前导 `'`，防止 13 位纯数字变科学计数）；C 列金额 = `float` 数字（供 D~I 列公式数值计算）；写入范围 `A{start}:C{end}`、`valueInputOption=USER_ENTERED`。
> - **判断最后一行（换行）只看「账户ID」列（B 列）有无数据**：从末行向上扫描，仅当 B 列非空才视为「已有数据行」，时间/金额列有残留但账户ID为空的行忽略。Java 侧读 `A:C` 后取 index 1 判断；注意 Google Sheets 会截断行尾空单元格，需 `len(row) > 1` 保护（`row[1]` 存在且非空）。
> - GG 的 `append_recharge`（7 列映射）保持不动（纯增量）；TT 路由 `_append_recharge_background._do_sync` 改调 `append_recharge_tt`，submit / batch-submit / retry-sheets 三处共用同一后台同步逻辑。
>
> **TT 回收户清单写表迁移要点（v1.26 补充）**：
> - TT 回收户清单（Google Sheets）为 12 列表头：`时间 | 账户ID | 渠道 | 运营 | 国家 | 时区 | 有无消耗 | 回收原因 | 是否提交 | 清零金额 | 备注 | 是否二次提交`。系统**只写 A(时间)/B(账户ID)/H(回收原因) 三列**，C~L 列（渠道/运营/国家/时区/有无消耗/是否提交/清零金额/备注/是否二次提交）在表格里已有公式、写入时**不得覆盖**。
> - 列映射（`append_recycle` → Java `GoogleSheetsService.appendRecycle`）：A 列时间 = 当天日期「年-月-日」（如 `2026-09-22`），前导 `'` 标记为文本（防日期解析）；B 列账户ID = 文本（前导 `'`，防 13 位纯数字变科学计数）；H 列回收原因 = 文本。用 `values().batchUpdate` 一次写 A/B/H 三个非连续 range（`A{start}:A{end}`、`B{start}:B{end}`、`H{start}:H{end}`），`valueInputOption=USER_ENTERED`。
> - **判断最后一行（换行）只看「账户ID」列（B 列）有无数据**：从末行向上扫描，仅当 B 列非空才视为「已有数据行」，时间列（A）有残留但账户ID为空的行忽略。Java 侧读 `A:B` 后取 index 1 判断；注意 Google Sheets 会截断行尾空单元格，需 `len(row) > 1` 保护。
> - **触发契约**：`updateAccount`（`PUT /api/tt/accounts/{id}`）与批量状态更新，当状态**真正变更**（新状态名 ≠ 旧状态名）且新状态为**非「存活」**（即 验证/封禁/死亡 等）且请求携带 `recycle_reason` 非空时，才触发写回收清单；状态同步（`sync-from-sheet`）路径**不得**触发（回收户清单是上游，同步只反映状态，见 v1.24）。写表在后台异步线程执行，失败不阻塞状态变更。
> - ⚠️ **v1.34 起 `updateAccount` 还多一条推送契约**：请求体带 `remark` 时（`"remark" in data and data["remark"] is not None`，**显式传 `""` 也算**，语义是清空备注），除落库外向**两张表**各推一次 —— 户管看板 `M` 列 + 投手看板 `J` 列。`owner_id` 取**该账户当前的 `owner_id`**（不是调用者 uid：户管可能代改别人名下的户）。⚠️ **户管看板那次回写不要自己在 `commit()` 之前加**：函数尾部**本来就有**一条 post-commit 的全量单行回写，而 `cells_for_row` 已含 `M` 列 —— 再加一条只会在 commit 前用**新连接读到未提交的旧值**，并与尾调用的后台线程**并发写同一行**（乱序时旧值可能后落盘覆盖新值）。详见附录 J。
> - **回收原因自动入库**：`recycle_reason` 若不在 `tt_recycle_reasons` 表则自动 INSERT（`owner_id` 记为当前用户，仅作创建者留痕）。
> - **回收原因为全平台公用词表（v1.29 修订，取代 v1.26 的 owner 隔离描述）**：
>   - `GET /api/tt/recycle-reasons/list` 返回**全表**，不做任何 owner / 角色过滤（viewer 亦可读）。
>   - `POST /create` 按 `name` **全局**去重（不是 `(name, owner_id)`），重名返回 409；`PUT /{id}` 改名需做全局重名检查（撞已有名称 → 409，原值不变）；`DELETE /{id}` 仅校验存在性。
>   - 写接口统一挂 `@tt_write_required`（放行所有非 viewer），**不做 owner 归属校验**：任何非 viewer 的 TT 用户可增/改/删任意一条。
>   - MySQL DDL 需为 `name` 建**全局唯一约束**（`UNIQUE KEY uk_tt_recycle_reasons_name (name)`），**不要**沿用 SQLite 表上的 `UNIQUE(name, owner_id)`——后者允许跨 owner 重名，已不满足契约。列：`id`/`name`/`owner_id`（仅留痕，无外键语义依赖）/`created_at`。
>   - 前端权限边界：回收原因卡片对**所有 TT 用户**可见可改；代理名/状态选项卡片仍管理员专属。`TtSettingsPanel.vue` 用 `visibleOptionCards`（`optionCards.filter(c => !c.adminOnly || isAdmin||isDeveloper||isHuguan)`）实现，单一 el-row 不再用 `<template v-if>` 包裹。
>
> **户管看板迁移要点（v1.31 新增）**：`HuguanDashboardController`（`py/routes/huguan_dashboard_routes.py`）5 个接口，**全部** `@jwt_required() + @huguan_required`（严格 `role == "huguan"`，admin/developer 亦 403）：
> - `GET /api/huguan/dashboard` → `{config: {gg:{spreadsheet_id,sheet_name}, tt:{...}}}`。两份都要**归一化**后再返回：`config` 表全仓共用，平台条目可能是「真值非 dict」（字符串/数字），直接透传会破坏响应契约。
> - `POST /api/huguan/dashboard` → 保存某平台配置。`platform` 必须 ∈ `("gg","tt")`（否则 400 `platform 必须是 gg 或 tt`，**不含 fb**）；`spreadsheet_id` 过 `_parse_sheet_id` 接受裸 ID 或完整 URL；字段一律先 `str()` 兜底（给数字/null 不该炸 500）。
> - `POST /api/huguan/dashboard/sync` → **表 → 系统**。未配置时 400 `请先在设置页配置户管看板的表格 ID 与工作表名`。跳表头第 1 行、**不跳任何数据行**（户管看板没有「是否解绑」列可用作跳过标记）；`read_range` 按平台取（GG `A:N` / TT `A:M`），读回**忽略**定位键列（C）与户管自维护列；⚠️ **v1.33 起 TT 的 `L` 列虽仍读回，但不再参与归属判定**（降为普通文本 `owner_change_note`，见附录 I）。`dry_run is not False` 即只读返回 `{diff}`；落库后（`confirmed` 必须是对象、三个 key 各自的值为数组或 null，否则 400）清缓存 `accounts:agents:` 前缀、必要时清 `accounts:statuses:<uid>`，并**回写运营列**、以及 ⚠️ **仅 GG 清空归属通道列**（TT 的 `L` 已是换绑记录，清它会抹掉记录 —— 见附录 I）。⚠️ **v1.34 起落库阶段还会读投手「我的看板」并对新建账户额外发起写回**（回写户管 `M` 列 / 推投手 `J` 列，见附录 J）；这两次写回在路由层被 `pop` 掉，**响应形状 `{result, diff}` 不变**。
> - `POST /api/huguan/dashboard/push` → **系统 → 表**全量刷新，**同步执行**。响应形状是 **`{success, result:{rows, updated, not_found}}`**（注意 `result` 这层包裹，不是平铺的 `{rows,updated,not_found}`）。`rows` = 候选行数，`updated` = 真正写进该户管表里的行数（⊆ rows），**表里找不到该账户不算错误**（户管的表不必包含所有账户）而进 `not_found`。
> - `GET /api/huguan/dashboard/owner-options` → 「户归属」下拉数据源：**全部非 `viewer`/`hidden` 用户**。与 `GET /api/platform/users`（只列该平台有未删除账户的人）**分工不同、都保留**：前者服务**编辑**（不要求名下已有账户），后者服务**筛选**（名下无户的选项筛不出东西）。
>
>   ⚠️ **2026-09-28 修订（迁移实现须照此写）**：本行原写「不按平台过滤」，已作废。现行口径是
>   `platform = ?platform`（缺省 `gg`，白名单 `hd.PLATFORMS` 之外回落 `gg`）**OR `role IN ('developer','huguan')`** ——
>   跨平台角色必须无条件保留，否则他们在 TT 看板建的户（`owner_id` 自动设为自己、
>   `require_platform` 对其放行）会退化成禁用的「用户 #N」且无 UI 可修。
>   见 [2026-09-28-huguan-owner-options-platform-isolation-design.md](2026-09-28-huguan-owner-options-platform-isolation-design.md)。
> - **归属门禁不复用**：同步/刷新的表地址**只从该户管自己的 `huguan_dashboard_{uid}` 配置取**，请求体不接受表地址 —— 若复用 `/api/accounts` 那套归属校验，等于同时给出「对着别人的表发起同步」这条路。
> - **后台回写**（`_write_background`）：`service` 必须**在线程内的闭包里 build**，不可由调用方传入 —— 该函数经 `_sync_sheets_background` 起后台线程且失败 30s 后重试，而 `dashboard_sync` 会**背靠背调两次**，两个线程并发复用同一个 httplib2 客户端（**非线程安全**）。仓库既有写法统一是这个形状，照抄即可。

---

## 7. 认证与安全

### 7.1 整体架构

```
                    ┌─────────────────────┐
                    │   SecurityFilterChain │
                    └──────────┬──────────┘
                               │
              ┌────────────────┼────────────────┐
              │                │                │
     ┌────────▼────────┐ ┌────▼─────┐ ┌───────▼───────┐
     │ JwtAuthFilter    │ │ CORS     │ │ PlatformGuard │
     │ (解析JWT,设置    │ │ Filter   │ │ Filter        │
     │  SecurityContext) │ │          │ │ (GG-only前缀  │
     └────────┬────────┘ └──────────┘ │  拦截FB用户)  │
              │                       └───────────────┘
     ┌────────▼────────┐
     │ Controller       │
     │ @Authentication  │
     │ Principal +      │
     │ @FbPlatformReq   │
     │ @AdminRequired   │
     └─────────────────┘
```

### 7.2 Spring Security 配置

```java
@Configuration
@EnableWebSecurity
@EnableMethodSecurity
@RequiredArgsConstructor
public class SecurityConfig {

    private final JwtTokenProvider jwtTokenProvider;

    @Bean
    public SecurityFilterChain filterChain(HttpSecurity http) throws Exception {
        http
            .csrf(CsrfConfigurer::disable)
            .cors(Customizer.withDefaults())
            .sessionManagement(sm ->
                sm.sessionCreationPolicy(SessionCreationPolicy.STATELESS))
            .authorizeHttpRequests(auth -> auth
                // 公开路由
                .requestMatchers(
                    "/api/auth/login",
                    "/api/auth/register",
                    "/api/auth/refresh"
                ).permitAll()
                .requestMatchers(HttpMethod.GET,
                    "/api/products/{pid}/detail",
                    "/api/image",
                    "/api/video/download",
                    "/api/video/progress",
                    "/api/fonts/**",
                    "/api/font-file",
                    "/api/health"
                ).permitAll()
                // 其余全部需要认证
                .anyRequest().authenticated()
            )
            .addFilterBefore(
                new JwtAuthenticationFilter(jwtTokenProvider),
                UsernamePasswordAuthenticationFilter.class)
            .addFilterAfter(
                new PlatformGuardFilter(),
                JwtAuthenticationFilter.class);

        return http.build();
    }

    @Bean
    public PasswordEncoder passwordEncoder() {
        return new BCryptPasswordEncoder();
    }

    @Value("${cors.allowed-origins:http://localhost:5173,http://127.0.0.1:5173}")
    private List<String> allowedOrigins;

    @Bean
    public CorsConfigurationSource corsConfigurationSource() {
        CorsConfiguration config = new CorsConfiguration();
        config.setAllowedOriginPatterns(allowedOrigins);  // 生产环境白名单
        config.setAllowedMethods(List.of("GET","POST","PUT","DELETE","OPTIONS"));
        config.setAllowedHeaders(List.of(
            "Authorization", "Content-Type", "Accept", "X-Requested-With"));
        config.setExposedHeaders(List.of("x-new-access-token"));
        config.setAllowCredentials(true);
        config.setMaxAge(3600L);

        UrlBasedCorsConfigurationSource source = new UrlBasedCorsConfigurationSource();
        source.registerCorsConfiguration("/**", config);
        return source;
    }
}
```

### 7.3 JWT Token 提供者

```java
@Component
public class JwtTokenProvider {

    @Value("${jwt.secret}")
    private String secret;

    @Value("${jwt.access-token-expiration:3600000}") // 1小时
    private long accessTokenExpiration;

    @Value("${jwt.refresh-token-expiration:2592000000}") // 30天
    private long refreshTokenExpiration;

    // 启动时强制校验：禁止使用默认弱密钥
    @PostConstruct
    public void validateSecret() {
        if (secret == null || secret.isBlank() || secret.length() < 32
                || secret.startsWith("your-256-bit-secret")) {
            throw new IllegalStateException(
                "【安全错误】JWT_SECRET 不能使用默认值！请设置环境变量 JWT_SECRET。\n"
                + "生成命令: openssl rand -base64 64");
        }
    }

    private SecretKey getSigningKey() {
        return Keys.hmacShaKeyFor(Decoders.BASE64.decode(secret));
    }

    // 生成 Access Token（含 tokenVersion 支持强制失效）
    public String createAccessToken(Long userId, String role, String platform, int tokenVersion) {
        return Jwts.builder()
            .subject(String.valueOf(userId))
            .claim("role", role)
            .claim("platform", platform)
            .claim("tokenVersion", tokenVersion)
            .issuedAt(new Date())
            .expiration(new Date(System.currentTimeMillis() + accessTokenExpiration))
            .signWith(getSigningKey())
            .compact();
    }

    // 验证 Token（含 tokenVersion 校验）
    public boolean validateToken(String token, int currentTokenVersion) {
        try {
            Claims claims = Jwts.parser().verifyWith(getSigningKey()).build()
                .parseSignedClaims(token).getPayload();
            int tv = claims.get("tokenVersion", Integer.class);
            return tv == currentTokenVersion;
        } catch (JwtException | IllegalArgumentException e) {
            return false;
        }
    }

    public Date getExpiration(String token) {
        return Jwts.parser().verifyWith(getSigningKey()).build()
            .parseSignedClaims(token).getPayload().getExpiration();
    }

    public long getAccessTokenExpiration() { return accessTokenExpiration; }

    // 提取字段
    private Claims getClaims(String token) {
        return Jwts.parser().verifyWith(getSigningKey()).build()
            .parseSignedClaims(token).getPayload();
    }

    public Long getUserId(String token) {
        return Long.parseLong(getClaims(token).getSubject());
    }

    public String getRole(String token) {
        return getClaims(token).get("role", String.class);
    }

    public String getPlatform(String token) {
        return getClaims(token).get("platform", String.class);
    }

    public int getTokenVersion(String token) {
        return getClaims(token).get("tokenVersion", Integer.class);
    }
}
```

### 7.4 JWT 认证过滤器

```java
@RequiredArgsConstructor
public class JwtAuthenticationFilter extends OncePerRequestFilter {

    private final JwtTokenProvider jwtTokenProvider;

    @Override
    protected void doFilterInternal(HttpServletRequest request,
            HttpServletResponse response, FilterChain chain)
            throws ServletException, IOException {

        String token = resolveToken(request);

        if (token != null && jwtTokenProvider.validateToken(token)) {
            Long userId = jwtTokenProvider.getUserId(token);
            String role = jwtTokenProvider.getRole(token);
            String platform = jwtTokenProvider.getPlatform(token);

            UserPrincipal principal = new UserPrincipal(userId, role, platform);
            UsernamePasswordAuthenticationToken auth =
                new UsernamePasswordAuthenticationToken(
                    principal, null, getAuthorities(role));

            SecurityContextHolder.getContext().setAuthentication(auth);

            // 滑动过期：仅剩余有效期 < 30% 时才签发新 token
            Date expiration = jwtTokenProvider.getExpiration(token);
            long remaining = expiration.getTime() - System.currentTimeMillis();
            if (remaining < jwtTokenProvider.getAccessTokenExpiration() * 0.3) {
                String newToken = jwtTokenProvider.createAccessToken(
                    userId, role, platform, jwtTokenProvider.getTokenVersion(token));
                response.setHeader("x-new-access-token", newToken);
            }
        }

        chain.doFilter(request, response);
    }

    private String resolveToken(HttpServletRequest request) {
        String bearer = request.getHeader("Authorization");
        if (bearer != null && bearer.startsWith("Bearer ")) {
            return bearer.substring(7);
        }
        return null;
    }

    private Collection<? extends GrantedAuthority> getAuthorities(String role) {
        return List.of(new SimpleGrantedAuthority("ROLE_" + role.toUpperCase()));
    }
}
```

### 7.5 自定义注解

```java
// @FbPlatformRequired — FB 平台 + JWT 认证
@Target({ElementType.TYPE, ElementType.METHOD})
@Retention(RetentionPolicy.RUNTIME)
public @interface FbPlatformRequired {}

// @AdminRequired — 管理员权限
@Target({ElementType.TYPE, ElementType.METHOD})
@Retention(RetentionPolicy.RUNTIME)
public @interface AdminRequired {}

// @DeveloperRequired — 开发者权限
@Target({ElementType.TYPE, ElementType.METHOD})
@Retention(RetentionPolicy.RUNTIME)
public @interface DeveloperRequired {}

// @RejectViewer — 拒绝 observer 角色
@Target({ElementType.TYPE, ElementType.METHOD})
@Retention(RetentionPolicy.RUNTIME)
public @interface RejectViewer {}
```

对应 AOP 切面示例：

```java
@Aspect
@Component
@RequiredArgsConstructor
public class PlatformGuardAspect {

    @Around("@within(fbPlatformRequired) || @annotation(fbPlatformRequired)")
    public Object checkFbPlatform(ProceedingJoinPoint pjp,
            FbPlatformRequired fbPlatformRequired) throws Throwable {
        Authentication auth = SecurityContextHolder.getContext().getAuthentication();
        UserPrincipal principal = (UserPrincipal) auth.getPrincipal();

        if (!principal.isDeveloper() && !"fb".equals(principal.getPlatform())) {
            throw new PlatformForbiddenException("FB platform required");
        }
        return pjp.proceed();
    }
}
```

### 7.6 平台守卫过滤器

```java
public class PlatformGuardFilter extends OncePerRequestFilter {

    // GG 专属路由（FB 用户不能访问）—— AntPathMatcher 防路径绕过
    private static final Set<String> GG_ONLY_PATTERNS = Set.of(
        "/api/ad-reports/**", "/api/accounts/**", "/api/mcc/**",
        "/api/products/**", "/api/scrape/**", "/api/video/**",
        "/api/youtube/**", "/api/settings/**", "/api/google-sheets/**"
    );
    private final AntPathMatcher pathMatcher = new AntPathMatcher();

    @Override
    protected void doFilterInternal(HttpServletRequest request,
            HttpServletResponse response, FilterChain chain)
            throws ServletException, IOException {

        String path = request.getRequestURI();

        // 用 AntPathMatcher 而非 startsWith 防路径遍历绕过
        boolean isGgOnly = GG_ONLY_PATTERNS.stream()
            .anyMatch(p -> pathMatcher.match(p, path));
        if (!isGgOnly) {
            chain.doFilter(request, response);
            return;
        }

        Authentication auth = SecurityContextHolder.getContext().getAuthentication();
        if (auth != null && auth.getPrincipal() instanceof UserPrincipal principal) {
            if (!principal.isDeveloper() && "fb".equals(principal.getPlatform())) {
                response.setStatus(403);
                response.setContentType("application/json;charset=UTF-8");
                response.getWriter().write(
                    "{\"success\":false,\"error\":\"Platform access denied\"}");
                return;
            }
        }

        chain.doFilter(request, response);
    }
}
```

### 7.7 用户管理的平台隔离（v1.28）

**核心语义变更**：`admin` 由**全局角色**降为**平台内角色**。GG 管理员只看/只管 GG 用户，TT 管理员只看/只管 TT 用户；只有 `developer` 跨平台无限制。这与 7.6 的 `PlatformGuardFilter`（按路由前缀拦截 FB 用户访问 GG 专属接口）是**两条不同的链路**：7.6 管的是「FB 用户能不能调 GG 的业务接口」，本节管的是「管理员能看见/操作哪些**用户账号**」。二者都要保留。

对应 Python 实现：`py/auth.py:list_users`、`py/main.py:admin_create_user`、`py/main.py:_check_modify_user`、`py/main.py:_can_access_user_data`、`py/main.py:_get_effective_platform`。

#### 7.7.1 四条约束规则

| 链路 | 规则 | developer |
|------|------|-----------|
| 用户列表 `GET /api/admin/users` | 非 developer 强制 `WHERE platform = 自己的 platform`，且 `WHERE role != 'developer'`（看不到开发者）；**忽略请求传入的 `platform` 参数** | 不过滤，可按 `platform` 参数筛，缺省返回全部 |
| 创建用户 `POST /api/admin/users/create` | 非 developer 的 `platform` **锁定为创建者自己的平台**（请求体传什么都无效）；创建者 platform 为非法存量值时兜底 `gg` | 请求体 `platform` 生效 |
| 用户操作（6 个接口） | 非 developer：目标角色必须是 `user`/`viewer`/`hidden`（不能动同级管理员）**且** `platform` 必须与自己相同 | 全部放行 |
| 数据导入/导出 | 非 developer 仅限**自己平台**的用户（不限目标角色——搬运数据不改账号权限） | 全部放行 |

「6 个接口」指 `POST /api/admin/users/<uid>/{role,toggle,delete,update,password,telegram}`，在 Python 侧共用一个 `_check_modify_user`，一处改动全局生效。

#### 7.7.2 空值归一

所有平台比较一律用 `(x.platform or 'gg')` 归一后再比，禁止直接字符串比较——存量数据存在 `platform` 为 `NULL` 或 `''` 的行，直接比较会让这类用户对任何管理员都不可见（或可被跨平台操作）。

Java 侧建议在 `UserPrincipal` / `UserEntity` 上提供：

```java
/** 归一后的平台：NULL/空串一律视为 gg。所有平台比较必须走这里。 */
public String effectivePlatform() {
    return (platform == null || platform.isBlank()) ? "gg" : platform;
}

/** 跨用户角色：可见/可操作他人数据（developer / admin / 户管）。 */
private static final Set<String> CROSS_USER_ROLES = Set.of("developer", "admin", "huguan");

/** 跨平台角色：可切换平台命名空间（developer / 户管）。**admin 刻意不在其中**，见 7.7.4。 */
private static final Set<String> PLATFORM_SWITCH_ROLES = Set.of("developer", "huguan");

public boolean isCrossPlatform() {
    return PLATFORM_SWITCH_ROLES.contains(role);
}

public boolean isCrossUser() {
    return CROSS_USER_ROLES.contains(role);
}
```

> **v1.31 修订（户管角色落地后）**：上段原为一个 `isCrossPlatform()`，注释里写「户管角色落地后扩展为角色集合」。落地时发现**必须拆成两个谓词**：户管既要跨用户看数据、又要切平台，但 **admin 只跨用户、不跨平台**（v1.28 的隔离结论）。原计划的「扩展为角色集合」若做成一个集合，`_get_effective_platform` 会把 admin 重新拉进跨平台分支，v1.28 修掉的缺陷立即复发。`py/routes/helpers.py` 的对应实现是 `CROSS_USER_ROLES` 与 `PLATFORM_SWITCH_ROLES` 两个常量（+ 语义不同的 `GLOBAL_OPTION_ROLES`），**三者不得合并**。

#### 7.7.3 拒绝原因要可区分

Python 侧 `_check_modify_user` 返回的是**拒绝原因字符串**而非布尔值，接口据此返回不同的错误消息（`不能操作同级管理员` / `不能操作其他平台的用户`，均 HTTP 403）。这是刻意设计：前端与排障时需要区分「角色层级不够」和「跨平台越权」，布尔值会把两类拒绝混成同一个 403。

Java 侧对应抛两个不同的异常/错误码，不要合并：

```java
public enum UserModifyDenyReason {
    SAME_LEVEL_ADMIN("不能操作同级管理员"),
    CROSS_PLATFORM("不能操作其他平台的用户");

    private final String message;
    UserModifyDenyReason(String message) { this.message = message; }
    public String message() { return message; }
}

/** 返回 null 表示可操作；否则返回具体拒绝原因。 */
public UserModifyDenyReason checkModifyUser(UserEntity actor, UserEntity target) {
    if (actor.isCrossPlatform()) return null;
    if (!Set.of("user", "viewer", "hidden").contains(target.getRole())) {
        return UserModifyDenyReason.SAME_LEVEL_ADMIN;
    }
    if (!actor.effectivePlatform().equals(target.effectivePlatform())) {
        return UserModifyDenyReason.CROSS_PLATFORM;
    }
    return null;
}
```

**注意规则顺序**：先判角色层级、再判平台。反过来会让「跨平台的同级管理员」返回平台原因，与既有测试（`test_tt_admin_cannot_modify_same_platform_admin` 断言「不能操作同级管理员」）不符。同平台的两个 admin 之间依然不能互相操作——本次**没有**放开这一点。

> **v1.31 追加（户管分支）**：`huguan` 落地后 `_check_modify_user` 在 **developer 短路之后、角色层级/平台判断之前**多了一段户管分支，返回两个**新的**拒绝原因字符串（`户管只能操作户管账号` / `只能操作自己创建的户管`）。户管**不走**平台的 `effectivePlatform()` 比较——户管本身跨平台。完整判定与 Java 骨架见 **7.9.3**；枚举相应扩为四个值，别只加平台那两支。

#### 7.7.4 `_get_effective_platform` 修正（易漏）

Python 的 `_get_effective_platform()` 供「取平台相关选项」的接口使用（账户状态、商务人员、地区等列表）。原实现是：

```python
if user and user.get("role") in ("developer", "admin"):   # ← 错误
    return request.args.get("platform", "gg")
```

问题在于：前端 `client.js` **只对 developer 注入 `platform` 参数**（按路由 hash 前缀推断），管理员拿不到注入。于是非 developer 管理员会被 `request.args.get` 的缺省值带进 **GG 命名空间**。表现为：TT 页面因前端显式传了 `platform=tt` 而侥幸正确，**FB 页面不传参 → FB 管理员看到的是 GG 的商务人员/账户状态选项**（静默错数据，不报错）。现改为仅 `role == 'developer'` 才跨平台，其他角色一律取自己的 `platform`：

```python
if user and user.get("role") == "developer":
    return request.args.get("platform", "gg")
return (user or {}).get("platform", "gg")
```

**迁移到 Spring Boot 时必须保持这个语义**：平台相关选项解析只认 developer 短路，不要想当然地把 admin 也算进去。

**与户管角色的衔接点（v1.31 已落地，且与原预测不同 —— 以本段为准）**：这里原写「计划改为 `CROSS_USER_ROLES`（含 developer 与户管角色）」。**实际落地用的是 `PLATFORM_SWITCH_ROLES = ("developer", "huguan")`**（`py/main.py:6364`），即 **admin 依旧不跨平台**。

这不是措辞差异，是「改了会复发 v1.28 那个缺陷」的实质差异：`CROSS_USER_ROLES` 含 admin，若按原预测改，admin 会被重新放进「取 `request.args['platform']`」分支 → FB 管理员又看到 GG 的商务人员/账户状态选项（静默错数据）。两个常量的分工是：

| 常量 | 值 | 用途 | 谁能拿它当跨平台用 |
|------|----|------|-------------------|
| `CROSS_USER_ROLES` | developer / admin / huguan | 跨**用户**看/改数据（账户归属、通知） | **不能**用于平台切换判断 |
| `PLATFORM_SWITCH_ROLES` | developer / huguan | 跨**平台**命名空间（`_get_effective_platform`、`@require_platform`） | 只能用它 |
| `GLOBAL_OPTION_ROLES` | developer / admin / huguan | 改**全局**选项/字典表 | 与上两者语义均不同 |

**合并三者为任意一个集合都会引入越权或错数据**。迁移时 7.7.2 的两个谓词 + 本节的短路判断要**同时**照搬；`"developer".equals(role)` 这类散写一律用常量替换。

#### 7.7.5 前端配套

| 位置 | 改动 | 迁移注意 |
|------|------|----------|
| `frontend/src/views/UserManageView.vue` | 平台 Tab（全部/GG/FB/TT）按身份条件渲染：非 developer 只显示自己平台那一个 | 纯前端体验优化，**权限边界不在前端**——后端必须独立强制（可绕过前端直调接口） |
| 同上，创建用户弹窗 | 「平台」字段 `v-if="authStore.isDeveloper"`，非 developer 看不到也传不出 | 后端仍要锁死（双保险） |
| 同上，Tab 默认值 | **必须用 `watch(() => authStore.user?.id, ..., { immediate: true })`**，不可在 `ref` 初始值里读身份 | 见下方说明 |
| `frontend/src/api/client.js` | developer 的 `platform` 自动注入需**排除 `/admin/users` 路径** | 见下方说明 |

**前端两处坑（迁移重构前端时勿重犯）**：

1. **身份时序**：`App.vue` 的 `initFromStorage()` / `fetchMe()` 在**父组件 `onMounted`** 才执行，而子组件的 `onMounted` 早于父组件、`setup` 更早。因此在 `UserManageView` 的 `setup` 阶段 `authStore.user` **必为 `null`**。若把身份算进 `ref` 初始值（只求值一次），Tab 选中态与筛选值会永久错位（被误判成「非开发者 / gg」）。必须改为 `watch` 身份变化后再定值并拉数据。

2. **自动注入误伤**：`client.js` 对 developer 按 `window.location.hash` 前缀推断平台（`/tt`→tt、`/fb`→fb、其余→gg）。用户管理页路由是 `/admin/users`，不以 `/tt`、`/fb` 开头 → 被推断成 `gg` 注入，导致 developer 的「全部」Tab 实际只返回 GG。须对该路径排除自动注入，平台交由页面内 Tab 显式控制。

### 7.8 爬取产物归属校验：目录名认领判据（v1.30 补充）

> 权威说明：`docs/superpowers/specs/2026-09-24-ondemand-download-signing-design.md` §0.9–§0.13（含各轮 code-review 的裁定与变异验证）。本节只收 **Java 侧必须原样重建的判据**；同一防线里「下载签名按需签发」那半条线（§0.9–§0.11）本版未收录。

**为什么不能靠外键推导归属**：爬取产物落在 `temp/scraped_images/<目录名>/`，目录名由用户「显示名」派生，**磁盘上没有 owner 记录**；`scrape_cache` 只记包名与保存路径、不记目录归属。因此归属判定 = 「这个名字此刻是不是你的」+「你曾用过这个名字，且你**最后一次释放**晚于这个目录的**创建时刻**」。

**三条判据**（`AuthService.directoryNameError(uid, username, displayName)`，任一条不过即拒）：

| # | 判据 | 规则 | 迁移注意 |
|---|------|------|---------|
| 1 | 字符闸门 | 禁 `/`、`\`、`:`、`\x00`，禁首尾点、禁首尾空白 | 必须在**应用层**做；别用 `Paths.get(..).normalize()` 代替（Windows 上 `\` 与盘符语义不同，且 normalize 不拦首尾空白） |
| 2 | 唯一 | 与本人**当前**目录名 + **曾用名**（`scrape_dn_history` 中 `user_id = 我` 的行）比较，先按 `normcase` 归一 | 别靠 MySQL 排序规则代劳：`utf8mb4_general_ci` 的大小写不敏感与 `normcase` 不等价（后者只处理 ASCII），且该表**刻意无唯一约束** |
| 3 | 目录占用 | `scrape_root` 下**任意**同名条目（**文件也算**）即拒 | 别改成 `isDirectory()`（占用判据要更严）；本条是「无主目录」现在**唯一**的兜底（扫盘补墓碑已于 v1.30 退役） |

**last-writer-wins + 时间维度**（`_dn_released_keys`）：把 `scrape_dn_history` 按 `dn` 归一分组，以 `id` 作**跨用户单调序号**，只有「我的序号 > 他人的序号」才算我说了算（**同值取拒**）。v1.30 起，每组先按**化身**过滤再比序号：

| 情形 | 释放行（`user_id != 0`） | 哨兵行（`user_id = 0`） |
|------|------------------------|------------------------|
| 目录存在，且 `ts` 晚于 `ctime` | 参与 LWW（`ts > ctime`） | **拦**（`ts >= ctime`） |
| 目录存在，但 `ts` 不晚于 `ctime` | **整条剔除**（不参与） | 不拦（该化身已被重建，旧哨兵失效） |
| 目录存在，但 `ts` 解析不出（脏行） | 剔除（不算「说得出来」） | **照拦** |
| 拿不到化身（不存在 / 越界 / `stat` 失败） | **不剔除**（照常参与） | **照拦** |

两个方向的取舍都要照抄：**释放行**抖向「不覆盖」= 误拒（fail-closed，可接受）；**哨兵**抖向「不拦」= 放开（fail-open，不可接受）——所以哨兵这侧必须带亚秒（见不变式 4）。tie（`ts == ctime`）在**两侧都取严**：释放行判「不覆盖」、哨兵判「拦」。

**方法骨架**（Python 侧纯函数，逐字对应）：

```java
/** 判据：该目录名此刻能否判给 uid（三条判据全过才放行）。 */
boolean directoryNameError(long uid, String username, String displayName);

/** 化身：目录创建时刻（epoch ms，UTC）；null = 目录不存在 / 越界 / stat 失败。 */
Long dirCtime(String dn);

/** 释放行是否覆盖该化身：ts == null → false（脏行不算覆盖）；化身 == null → true（不过滤）；否则 ts > ctime。 */
boolean releaseRowCoversDir(String dn, Long ts);

/** 哨兵行是否拦该化身：ts == null → true（照拦）；化身 == null → true（照拦）；否则 ts >= ctime。 */
boolean sentinelRowBlocksDir(String dn, Long ts);
```

`dirCtime` 的**越界判定**要与读路径**复用同一个函数**（Python 侧为 `auth._dir_name_of`，做 realpath + `os.sep` 前缀判断）：口径不一致会把**自己人**的目录误判成无主，永久封掉他的名字（Python 侧变异 m21 恰好 1 红）。

**四条不变式（迁错任何一条都会静默削弱或静默放大权限）**：

1. **墓碑必须活过删用户**：`DELETE /api/admin/users/{id}` 需先写该用户当前目录名的释放行，且**该表不进删用户清理清单**（其余引用 `users(id)` 的表都要清）。少了这步，被删用户的目录会立刻变成无主、可被「曾用名含该名」的人认领并读到其产物（Python 侧回归：`test_scrape_ownership.py::TestDeletedUserDirectoryIsTombstoned`，变异实测**恰好 1 红**）。
2. **哨兵是独立集合**：`user_id = 0` 的名字在「已释放」查询里用独立 `blocked` 集合剔除，**不参与序号比较**。若改成「参与比较」，后来者更大的 id 会把它顶掉，硬闸静默失效（变异 m17 恰好 1 红）。
3. **迁移歧义名要种哨兵**：一次性数据迁移时，若同一目录名在多个用户间**先后无法还原**，必须写入哨兵行（`database._migrate_scrape_dn_history`）——这是哨兵**唯一**的写入点（另一个写入点「无主目录扫盘补墓碑」已于 v1.30 退役）。
4. **写入必须带亚秒**：表默认值只到秒时，「同一秒内先建目录、后跑迁移」会让哨兵时刻被截小 ⇒ `ts >= ctime` 不成立 ⇒ 歧义名被放开。**任何**写该表的代码路径都要显式带毫秒（SQLite：`strftime('%Y-%m-%d %H:%M:%f','now')`；MySQL：`CURRENT_TIMESTAMP(3)` + `DATETIME(3)`）。解析时轴必须按 **UTC**（Python 侧 `calendar.timegm`；用本地解析会整批偏一个时区，变异 m31）。

> **回归锚点（迁移后用等价用例覆盖）**：`py/tests/test_scrape_ownership.py`（认领放行/拒绝、他人过期行不挡我、时间维度惰性分支、亚秒格式、秒级 tie、时轴定值、删号墓碑、哨兵硬闸）与 `py/tests/test_scrape_dn_history_migration.py`（迁移幂等、扫盘退役后无主目录仍不可认领、哨兵按化身生效、脏行照拦）。**别只测「拿得到产物」**——这几条判据的价值全在**反例**上。

### 7.9 户管角色与户管看板（v1.31 补录）

权威设计见 `2026-09-22-huguan-role-design.md`（角色）、`2026-09-23-huguan-sheet-design.md`（看板双向同步）、`2026-09-24-huguan-owner-source-and-picker-design.md`（归属来源标注）、`2026-09-24-huguan-frontend-visual-design.md`（前端视觉，含 11 项已裁定决策）。本节只收 **Java 侧必须原样重建的语义**。

#### 7.9.1 角色与三个角色集合

户管（`huguan`）是**业务角色**，不是「小号管理员」：它跨平台、跨用户看数据，但被**排除在产品/素材域之外**。

```java
public static final String HUGUAN_ROLE = "huguan";

/** 跨用户角色：可见/可操作他人数据。 */
public static final Set<String> CROSS_USER_ROLES = Set.of("developer", "admin", HUGUAN_ROLE);
/** 跨平台角色：可切换平台命名空间。admin 刻意不在其中（见 7.7.4）。 */
public static final Set<String> PLATFORM_SWITCH_ROLES = Set.of("developer", HUGUAN_ROLE);
/** 可增删改全局选项/字典表。与上两者语义不同，不得合并。 */
public static final Set<String> GLOBAL_OPTION_ROLES = Set.of("developer", "admin", HUGUAN_ROLE);
```

**四个装饰器**（`py/routes/decorators.py`），语义各不相同，别按名字想当然：

| 装饰器 / 函数 | 语义 | 户管 |
|---------------|------|------|
| `@huguan_required` | **严格** `role == "huguan"` | 放行（admin/developer 是 **403** `权限不足，仅户管可操作`） |
| `@admin_required` | `role in ("developer","admin")` | **拒绝** |
| `reject_huguan()` / `@no_huguan` | 产品/包/素材域专用，户管一律拒绝 | **403** `户管无产品/素材权限` |
| `require_platform(p)` | 按平台拦截；`PLATFORM_SWITCH_ROLES` 直接放行 | 放行 |

> `@huguan_required` 的**严格性**是有意的：户管看板是户管的**个人**配置（存各自 `config`），不是管理功能，把 developer 顺带放行会让「谁的看板」这一层归属失去意义。

**本版无 DDL 变更**：户管线**不新增表、不新增列**。`users.role` 在 §5 的 DDL 里是 `VARCHAR(20) NOT NULL DEFAULT 'user'`（**不是** `ENUM`、无 `CHECK` 约束），`'huguan'` 6 字符直接可存 —— 迁移时**不要**把这个列实现成 MySQL `ENUM('developer','admin','user','viewer','hidden')`，那会把新角色挡在库外。归属复用现有的 `accounts.owner_id` / `tt_accounts.owner_id`。

#### 7.9.2 户管看板：列模型与写入边界

**配置**存 `config` 表键 `huguan_dashboard_{uid}`，**按平台各一份**（`PLATFORMS = ("gg","tt")`；**FB 不支持**，因为 FB 无归属字段语义）。响应契约是归一化后的 `{gg:{spreadsheet_id,sheet_name}, tt:{...}}` —— `config` 表全仓共用，平台条目可能是「真值非 dict」，**归一化不能省**。

列模型是 `COLUMN_SPEC`（`py/huguan_dashboard.py`），每项 `(列字母, 表头, 系统字段名, 可写, 可读)`：

| | GG（14 列，`READ_RANGE=A:N`） | TT（13 列，`READ_RANGE=A:M`） |
|---|---|---|
| 定位键 | `C` 账户ID（**可写、不可读**） | `C` 账户ID（同上，取自 `advertiser_id`） |
| 归属通道列 | `H` 重新分配 | **无**（`L` 换绑情况自 **v1.33** 起改为普通文本「换绑记录」列，不再参与归属判定 —— 见附录 I） |
| 运营列 | `G` 运营 | `G` 接户运营 |
| 系统**不映射**列（户管自维护，读写都不碰） | `E` 国家、`L` 位置、`M` 消耗、`N` 产品信息 | `K` 位置 |
| 可写**不可读**（读回会与别的列打架） | `C`、`J` 大MCC（派生列） | `C` |

三个合成字段**不对应数据库列**：`_dead_flag`（`death_date` 是否非空 → 写 `是`/空）、`_owner_channel`（归属变更通道，**v1.33 起仅 GG 使用**）、以及派生列 `parent_mcc_name`。**归属不新增数据库列**，直接用 `accounts.owner_id` / `tt_accounts.owner_id`（可空）。系统**实际自动写**的列比「可写」更窄：GG 是 `A:D`+`F:G`+`I:K`，TT 是 `A:J`+`M:M` —— 中间的缺口（GG 的 `H`、TT 的 `L`）就是不参与自动回写的列。GG 的 `H` 靠 `field == "_owner_channel"` 守卫排除，TT 的 `L` 自 **v1.33** 起靠 `writable=False` 排除 —— **机制不同、效果相同**，两者都不得改成可写。

**写表方法 `update_rows_by_account_id(service, spreadsheet_id, sheet_name, rows, key_col="C")`**（§8.1）：

- `rows: [{"account_id": "123", "cells": {"A": "...", "G": "张三"}}]`，`cells` 键为列字母；
- **只有相邻列会并成区间，空洞处断开** —— 因此没出现在 `cells` 里的列**绝不会被写到**。这是户管公式列保命的**唯一**机制，**不得**用「读整行 → 改几格 → 整行写回」实现（那会清空公式）；
- 账户ID 定位时取出的值要 `.strip().lstrip("'").strip()`（表里写的是带前导 `'` 的文本），**首次出现优先**（`if v not in row_of`）；
- **整批一次 `values().batchUpdate`**（`valueInputOption=USER_ENTERED`）。单次请求**原子**：要么全成、要么全不成。不要退回「每行一次调用」——那会同时带来「配额撞车导致前几行已落表」的半写与「几百行 = 几百次请求」的请求数爆炸；
- **表里找不到该账户不算错误**，进 `not_found` —— 户管的表不必包含所有账户；
- 返回 `{"updated": n, "not_found": [...]}`。失败时抛 `GoogleSheetsServiceError`，文案写**「本次已写入 0 行」**（原子性的直接推论），不要写「表已部分写入、无回滚」。

#### 7.9.3 用户管理按户管收窄

户管能进用户管理页，但只能管**自己创建的户管账号**。`_check_modify_user` 的**判定顺序不可调换**（developer → 户管 → 角色层级 → 平台）：

```java
public enum UserModifyDenyReason {
    SAME_LEVEL_ADMIN("不能操作同级管理员"),
    CROSS_PLATFORM("不能操作其他平台的用户"),
    HUGUAN_TARGET_NOT_HUGUAN("户管只能操作户管账号"),      // v1.31
    HUGUAN_NOT_OWNER("只能操作自己创建的户管");            // v1.31

    private final String message;
    UserModifyDenyReason(String message) { this.message = message; }
    public String message() { return this.message; }
}

/** 返回 null 表示可操作；否则返回具体拒绝原因。 */
public UserModifyDenyReason checkModifyUser(UserEntity actor, UserEntity target) {
    if ("developer".equals(actor.getRole())) return null;          // ① 短路
    if (HUGUAN_ROLE.equals(actor.getRole())) {                     // ② 户管分支
        if (!HUGUAN_ROLE.equals(target.getRole())) {
            return UserModifyDenyReason.HUGUAN_TARGET_NOT_HUGUAN;
        }
        if (!Objects.equals(target.getCreatedBy(), actor.getId())) {
            return UserModifyDenyReason.HUGUAN_NOT_OWNER;
        }
        return null;   // 户管不受平台维度约束（户管本身跨平台）
    }
    if (!Set.of("user", "viewer", "hidden").contains(target.getRole())) {  // ③
        return UserModifyDenyReason.SAME_LEVEL_ADMIN;
    }
    if (!actor.effectivePlatform().equals(target.effectivePlatform())) {   // ④
        return UserModifyDenyReason.CROSS_PLATFORM;
    }
    return null;
}
```

**户管分支必须早于 ③④**：户管的目标可能是**其他平台**的户管，若先走平台比较，合法操作会被 `CROSS_PLATFORM` 误拒。

配套三处（缺一即越权）：

| 位置 | 规则 |
|------|------|
| 创建用户 `POST /api/admin/users/create` | `ALLOWED_CREATE_ROLES = {developer:(user,admin,viewer,huguan), admin:(user,admin,viewer), huguan:(huguan,)}`；户管**忽略请求体 `role`，强制写 `huguan`** |
| 改角色 `POST .../role` | 白名单 = `ALLOWED_CREATE_ROLES[actor] + ("hidden",)`；户管**再收窄**为 `("huguan","hidden")`（不能把自己的人提成 admin） |
| 用户列表 `GET /api/admin/users` | 角色过滤**在路由层**：`role_filter = "huguan" if user.role == "huguan" else None`；`list_users` 内部只负责「户管跳过平台过滤」。**两处都要照搬** |

`update_user_role` 另有一层纵深防御：写入前再校验一次 `new_role ∈ {user, admin, viewer, hidden, huguan}`，即使调用方漏校验也不会落库未知角色。

#### 7.9.4 归属变更协议（四条硬规则）

1. **变更通道列的值优先于运营列** —— 两列同时有值时以通道列为准（户管是显式在表里写下「重新分配」/「换绑情况」的）。
2. **自动回写永不碰变更通道列** —— 系统自动同步（账户状态/字段变更触发的后台回写）只写运营列，通道列只有户管能写。
3. **变更通道列只有两个写入点**：① 户管在系统 UI 改归属 ⇒ 写新归属人名；② 「从表同步到系统」成功应用归属后 ⇒ **清空为 `""`**。除此之外任何路径都不得写它。
4. **应用归属变更后必须回写运营列**为新归属人名，让两列重新一致（否则下一轮同步会读到旧运营名，把归属再改回去）。

> ⚠️ **v1.33 起，规则 1 与规则 3 的 TT 部分已作废**（GG 部分逐字不变）：
>
> | 规则 | GG（不变） | TT（v1.33 起） |
> |------|-----------|----------------|
> | 1 通道优先 | 保留 | **作废** —— 归属恒取「接户运营」，`L` 列值不参与判定 |
> | 2 回写不碰通道列 | 保留 | **保留**（改由 `writable=False` 保证，不再靠 `_owner_channel` 守卫） |
> | 3① 系统 UI 改归属写 L | 写新归属人名 | **保留但内容变更**：写 `旧归属人转新归属人+月.日`（如 `阿轩转黎明10.7`），且**同时落库** `tt_accounts.owner_change_note` |
> | 3② 同步后清空 L | 保留 | **作废** —— 对 TT 执行会抹掉换绑记录（读回是按表覆盖，会连带清掉系统值） |
> | 4 回写运营列 | 保留 | **保留**（TT 的 `G` 列现在是唯一归属列） |
>
> TT 侧实现的全部细节（含「为什么必须这样」）见**附录 I**。**迁移红线**：GG 的四条规则
> **逐字重建**；TT 走附录 I 的新语义。把 TT 也按规则 1 实现，会让归属被 `L` 列的记录文本劫持。

**名字 → `owner_id`**：先按 `users.display_name` **精确匹配**，无命中回落 `users.username`；命中 **0 个或 ≥2 个都不写归属**（只进 `warnings`），但**该行其他列照常处理**。

**空归属**：已存在的账户 ⇒ **维持原值不变**；新建账户 ⇒ `owner_id = NULL`（普通用户看不见，户管/admin/developer 可见）。

**TT 侧 `reassign_account` 已扩展**（GG 侧 `/api/accounts/{id}/reassign` 原有此能力）：`actor_role ∈ CROSS_USER_ROLES` 且请求体给了合法 `owner_id` 时才允许转给**指定用户**，否则恒为「转给自己」（默认路径与改动前逐字节一致）。四道校验缺一即 500 或越权：

```java
String raw = (data instanceof Map) ? String.valueOf(((Map<?,?>) data).getOrDefault("owner_id", "")) : "";
// ① 非跨用户角色：忽略 owner_id，target 恒为自己
// ② "abc" / "1.5" / "" 等 → 400 owner_id 不合法（判据是 isascii && isdigit，
//    不能只判 isDigit —— 全角数字 "１" 会通过 isDigit 却在 Integer.parseInt 炸 500）
// ③ > 2^63-1 → 400（防 SQLite 绑定溢出）
// ④ target != 自己时，必须查 users 存在性 → 否则 FOREIGN KEY 违约变 500
```

`target == 自己` 与 `target == 他人` 的 409 文案**刻意不同**（`该账户已属于当前用户，无需转移` / `该账户已属于目标用户，无需转移`），前端直接展示后端文案，**不要**在 Java 侧统一成一句。

⚠️ **v1.33 起，TT 的 reassign 还多做一件事**：落库 `owner_id` 的同时，生成**换绑记录**并**写两处** ——
① `UPDATE tt_accounts SET owner_change_note=?`（`旧归属人转新归属人+月.日`）；
② 调 `writeback_owner_channel(..., text=同一个字符串)` 写进户管看板的 `L` 列。
**两处必须同源**（在端点内构造一次），且写入点必须在 `db.commit()` **之前**、与 `owner_id` 同一次事务。
⚠️ **返回文案里的 `old_owner` / `label` 保持原样不动** —— 那是给用户看的消息，与换绑记录是两套契约
（文案没有月日格式要求）。全部细节与红线见**附录 I**。

#### 7.9.5 表 → 系统同步的差异契约

`POST /api/huguan/dashboard/sync`，请求体 `{platform, dry_run, confirmed}`。差异分**五类**：

| 类别 | 含义 |
|------|------|
| `to_create` | 系统里没有、表里有的账户 |
| `to_update` | 系统里有、表里字段值不同的账户。**表内空值 = 清空系统对应列**（每条带 `clears` 字段，`summary` 带 `clears` 计数）。⚠️ **v1.34 起有一个 TT 专属例外**：`remark` **不再进 `to_update`**（投手权威永久，见附录 J）——表里改/清空户管 `M` 列对**已存在**账户一律不生效，`remark` 也因此**不再出现在 `clears` 里**。⚠️ **该例外只能加在 `to_update` 的字段过滤上，不得把 `remark` 从 `_PLAIN_TEXT_FIELDS["tt"]` 删掉**（该清单被 `to_create` 与 `to_update` 共用，删掉会让「首次入库读户管 `M` 列」失效） |
| `owner_changes` | 归属变更，每条带 `{account_id, from, to, via}` |
| `to_skip` | 软删除（`deleted_at` 非空）的账户 |
| `warnings` | 名字解析歧义（0 或 ≥2 命中）等不阻断项 |

四条**不可简化**的约束：

1. **`dry_run` 是 fail-safe**：**只有显式布尔 `false` 才落库**。判据写 `data.get("dry_run") is not False`，**不能**写 `if not dry_run` —— 后者会让 `null` 因假值而落库，等于「传了个空值就把库改了」。
2. **确认按 `account_id` 绑定，不按行号**：`confirmed = {create:[账户ID...], update:[...], owner:[...]}`；三个 key 的值必须是数组或 `null`，否则 400（`2 not in 2` 会 `TypeError` → 500）。行号在重新拉表后可能位移到别人身上，用行号 = 把变更应用到错误的账户。
3. **`not_applied` 防静默丢弃**：确认里给了但本次未应用到的项要显式回传，不允许悄悄忽略。
4. **表地址只从配置取**：`spreadsheet_id` / `sheet_name` **只来自该户管自己的 `huguan_dashboard_{uid}`**，请求体不接受表地址。**归属门禁刻意不复用** —— 复用 `/api/accounts` 那套校验等于同时引出「对着别人的表发起同步」这条路。

落库后要清缓存 `accounts:agents:` 前缀（账户/代理下拉立即刷新），本次可能新建状态行时再清 `accounts:statuses:{uid}`。

#### 7.9.6 两个「归属人下拉」分工（易合并错）

| 端点 | 数据源 | 服务于 |
|------|--------|--------|
| `GET /api/platform/users` | 该平台**有未删除账户**的人 | **筛选**（「归属人」筛选器）——选中一个名下无户的人必然得到空表，没有筛选价值 |
| `GET /api/huguan/dashboard/owner-options` | 排除 `role in ('viewer','hidden')`，且 `platform = ?platform`（缺省 gg，白名单外回落 gg）**OR `role in ('developer','huguan')`** ⚠️ 2026-09-28 起按平台隔离，见上一节修订 | **编辑**（改归属）——不要求名下已有账户，否则户管没法把户转给刚建号、还没分到户的新人 |

**两者都保留，不要互相替代**（曾计划合并，实测发现缺口）。

#### 7.9.7 前端边界

| 位置 | 取值 |
|------|------|
| `stores/auth.js` | `isHuguan: (s) => s.user?.role === 'huguan'`；`canSwitchPlatform: ['developer','huguan'].includes(...)`；`canManageAccounts: ['developer','admin','huguan'].includes(...)` |
| 侧边栏 `AppSidebar.vue` | 户管有**三套**精简导航（`huguanNavItems` / `huguanFbNavItems` / `huguanTtNavItems`），按 `effectivePlatform` 取用：**FB 也可进入**，但只有「账户管理（广告账户/BM管理/像素管理）+ FB设置 + 管理」三项；GG/TT 侧为「账户管理（广告账户/MCC或BC/设置）+ 管理」。三套都**不含产品、素材、YouTube、媒体、做表**等域 |
| 设置页「📊 户管看板配置」 | **同一个组件**（`HuguanDashboardCard.vue`）在 GG 设置页与 TT 设置页**各挂一次**，平台由 `platform` 属性驱动（`platform="gg"` / `platform="tt"`）——不是两份组件，也不是一份卡片。组件内部自带 `v-if="authStore.isHuguan"` 守卫，两个设置页都**无条件挂载**它；同页另一张 sheet 卡片与户管互斥（GG 侧是管理员专属 `template`，TT 侧是 `v-if="!isHuguan"`），所以不存在主次并列 |
| 归属变更「来源」列 | 按平台映射**中文**：`owner_channel` → GG「重新分配」/ ~~TT「换绑情况」~~；`owner_name` → GG「运营」/ TT「接户运营」。**未知 token 渲染 `—`**，**不得**只渲染 GG 的两种叫法。⚠️ **v1.33 起 TT 侧不再产出 `owner_channel`**（`L` 列不参与归属判定，故 `via` 恒为 `owner_name`）；映射表**保留** TT 那一项不删，纯属历史数据的容错 —— 但**不要**为 TT 再造出 `owner_channel` |
| 路由守卫 `router/index.js` | 户管对 `meta.admin` 路由走**白名单**：`/accounts/ads`、`/accounts/mcc`、`/accounts/settings`、`/fb/accounts`、`/fb/bms`、`/fb/pixels`、`/fb/settings`、`/tt/accounts`、`/tt/bcs`、`/tt/settings`、`/admin/users`（`p === r \|\| p.startsWith(r + '/')`）。另有一串**逐条重定向**：产品页（GG/FB/TT 三处）、FB / TT 数据提取与数据管理、`/youtube`、`/media`、`/toolkit/audio` 一律弹回本平台账户页——对应的后端接口域（产品/包/素材、`/api/youtube/*`、`/api/video/*`、`/api/audio*`）已用 `@no_huguan` 覆盖（全仓 **79** 处：`main.py` 59、`fb_routes.py` 7、`tt_routes.py` 13）。**`/toolkit/zuobiao` 按裁定放行**，不要顺手也拒掉 |
| `AccountModal.vue` 409 转户入口 | 非 `canManageAccounts` 角色（普通用户/viewer）**不渲染**「转移给我」按钮，改为明确告知「该账户属于他人，需由户管或管理员转移」——那个入口点了必然 403 |

**权限边界不在前端**：以上全部只是体验优化，后端必须独立强制（可绕过前端直调接口）。

---

## 8. 业务服务层设计

### 8.1 Google Sheets 服务

这是最核心的业务服务，需要完整保留 Python 版本的 upsert 逻辑。

```java
@Service
@Slf4j
public class GoogleSheetsService {

    @Value("${google.sheets.credentials-path}")
    private String credentialsPath;

    private static final String APPLICATION_NAME = "GG-Server";
    private static final List<String> SCOPES =
        List.of("https://www.googleapis.com/auth/spreadsheets");

    private Sheets sheetsService;

    @PostConstruct
    public void init() throws Exception {
        GoogleCredentials credentials = GoogleCredentials
            .fromStream(new FileInputStream(credentialsPath))
            .createScoped(SCOPES);
        // 使用服务账号时不需要 refresh token

        this.sheetsService = new Sheets.Builder(
            GoogleNetHttpTransport.newTrustedTransport(),
            JacksonFactory.getDefaultInstance(),
            new HttpCredentialsAdapter(credentials))
            .setApplicationName(APPLICATION_NAME)
            .build();
    }

    /**
     * GG 做表数据 upsert（对应 Python upsert_zuobiao）
     * 列映射 A-N（14列）：日期|运营|客户名称|商务|投放国家|渠道号|
     *   系列名|包名|账户ID|素材图|落地页|账号消耗(¥)|广告系列
     * M = F*L (利润), N = F-K+M (客户实际消耗)
     */
    public UpsertResult upsertZuobiao(String spreadsheetId, List<ZuobiaoRow> rows,
            String productName, String region, String reportDate,
            String salesPerson, Double agencyRatio, String operatorName) {
        try {
            // 1. 获取表格信息
            Spreadsheet spreadsheet = sheetsService.spreadsheets()
                .get(spreadsheetId).execute();

            String sheetName = spreadsheet.getSheets().get(0)
                .getProperties().getTitle();

            // 2. 读取现有数据 A-N
            ValueRange existingData = sheetsService.spreadsheets().values()
                .get(spreadsheetId, "'" + sheetName + "'!A:N").execute();
            List<List<Object>> existing = existingData.getValues();
            if (existing == null) existing = new ArrayList<>();

            // 3. 找最后一行（只看 A 列日期，不看其他列）
            int lastRow = 0;
            String lastDate = "";
            for (int i = existing.size() - 1; i >= 0; i--) {
                List<Object> row = existing.get(i);
                if (!row.isEmpty() && row.get(0) != null
                        && !row.get(0).toString().isBlank()) {
                    lastRow = i + 1;
                    lastDate = row.get(0).toString().trim();
                    break;
                }
            }

            // 4. 新日期空一行
            if (reportDate != null && !reportDate.isEmpty()
                    && !lastDate.isEmpty() && !lastDate.equals(reportDate)) {
                lastRow++;
            }

            // 5. 构建去重索引: (A=日期, C=客户名称, I=账户ID, M=广告系列)
            Map<String, Integer> existingMap = new HashMap<>();
            for (int i = 0; i < existing.size(); i++) {
                List<Object> row = existing.get(i);
                if (row.size() > 8 && row.get(0) != null && row.get(8) != null) {
                    String key = row.get(0).toString().trim() + "|"
                        + (row.size() > 8 ? row.get(8).toString().trim() : "");
                    existingMap.put(key, i);
                }
            }

            // 6. 自动扩容
            int maxRows = spreadsheet.getSheets().get(0)
                .getProperties().getGridProperties().getRowCount();
            int needed = lastRow + rows.size() + 1;
            if (needed > maxRows) {
                // batchUpdate appendDimension
                Request request = new Request()
                    .setAppendDimension(new AppendDimensionRequest()
                        .setSheetId(spreadsheet.getSheets().get(0)
                            .getProperties().getSheetId())
                        .setDimension("ROWS")
                        .setLength(needed - maxRows + 100));
                sheetsService.spreadsheets().batchUpdate(spreadsheetId,
                    new BatchUpdateSpreadsheetRequest()
                        .setRequests(List.of(request))).execute();
            }

            // 7. 构建批量更新
            List<Request> updateRequests = new ArrayList<>();
            List<List<Object>> newRowUpdates = new ArrayList<>();
            int updated = 0, appended = 0;

            for (ZuobiaoRow zuobiaoRow : rows) {
                List<Object> rowData = zuobiaoRow.toSheetRow(); // 14列
                String dedupKey = reportDate + "|" + zuobiaoRow.getAccountId();

                if (existingMap.containsKey(dedupKey)) {
                    int rowIdx = existingMap.get(dedupKey);
                    // 更新已有行
                    updateRequests.add(buildUpdateRequest(sheetName, rowIdx + 1, rowData));
                    updated++;
                } else {
                    lastRow++;
                    updateRequests.add(buildUpdateRequest(sheetName, lastRow, rowData));
                    appended++;
                }
            }

            // 8. 批量执行更新
            if (!updateRequests.isEmpty()) {
                sheetsService.spreadsheets().values().batchUpdate(spreadsheetId,
                    new BatchUpdateValuesRequest()
                        .setValueInputOption("USER_ENTERED")
                        .setData(updateRequests.stream()
                            .map(r -> new ValueRange()
                                .setRange(r.getRange())
                                .setValues(List.of(r.getValues())))
                            .toList()))
                    .execute();
            }

            return UpsertResult.builder()
                .updated(updated).appended(appended)
                .sheetName(sheetName).build();
        } catch (Exception e) {
            log.error("Sheets upsert failed", e);
            throw new BusinessException("Google Sheets 写入失败: " + e.getMessage());
        }
    }

    /**
     * FB 做表数据写入（对应 Python upsert_fb_reports）
     * 列映射 A-L（12列）：日期|运营|账户名称|广告账户ID|账号消耗|
     *   报给客户|客户名称|商务|投放国家|渠道号|平台实际|代投比例
     */
    public UpsertResult upsertFbReports(Long userId, String productName,
            String lineName, String reportDate, List<FbReportRow> records) {
        // 逻辑同上，区别：
        //   1. 读取用户 Sheets 配置（按 platform 选 key）
        //   2. 按 用户名+月份 匹配表格
        //   3. 去重键：(日期, 账户ID, 产品名, 线名)
        //   4. 12列输出
        //   详略（代码结构与 upsertZuobiao 类似）
    }
    /**
     * 「我的看板」Sheet 双向同步（对应 Python accounts_sync_from_sheet + update_cell_by_account_id）
     *
     * 我的看板列结构（A-H，8列）：
     *   A=运营, B=账户ID, C=所属渠道, D=国家, E=时区, F=备注, G=是否封户, H=是否解绑
     *
     * Sheet→系统 (dry_run):
     *   1. 读取 A:H 列
     *   2. 门禁校验：A列运营 == 当前用户 display_name
     *   3. 跳过 H列="解绑" 的账户
     *   4. 按 B列 account_id 匹配系统账户（含软删除）
     *   5. 系统没有 → to_create；系统有+未删除 → 根据 G列封户值建议状态；
     *      系统有+已删除 → 跳过
     *
     * Sheet→系统 (execute):
     *   1. 创建新账户（name/MCC留空，状态默认"存活"，代理自动创建）
     *   2. 执行确认后的状态变更（不触发清账逻辑，同步 death_date）
     *
     * 系统→Sheet (execute后自动):
     *   1. 重新查询所有匹配账户最新状态（含 deleted_at）
     *   2. F列(备注) ← 系统状态
     *   3. H列(是否解绑) ← 已删除写"解绑"，未删除清空
     *
     * 系统→Sheet (状态变更时自动):
     *   accounts_update / batch_update 状态变更时，后台线程更新 F列(备注)
     *   accounts_delete 时后台写 H列"解绑"
     *   accounts_restore 时后台清 H列
     */
    public SyncResult syncFromSheet(Long userId, SyncRequest req) {
        // dry_run: 比对返回 diff
        // execute: 执行 + commit + 系统→Sheet 同步
    }

    /** 按 account_id 更新 Sheet 指定列 */
    public void updateCellByAccountId(String spreadsheetId, String sheetName,
            String accountId, String value, int colIndex) {
        // colIndex: 5=F列(备注), 7=H列(是否解绑)
    }

    /**
     * 按「账户ID 列」定位行，一次写多列；未出现在 cells 里的列一律不碰。（v1.31，户管看板专用）
     *
     * rows: [{"account_id": "123", "cells": {"A": "2026-09-23", "G": "张三"}}]
     *   cells 键为列字母——只有相邻列并成区间，空洞处断开，
     *   因此没出现在 cells 里的列绝不会被写到（户管的公式列靠这个保命）。
     * keyCol: 账户ID 所在列字母。**户管看板两侧都是 "C"；投手「我的看板」是 "D"**
     *   （自 v1.34 起本方法也服务投手看板，见附录 J）。调用方**必须显式传**：
     *   默认值 "C" 只覆盖户管看板，用它去写投手看板会**静默定位到错误的行**。
     *
     * 返回 {"updated": n, "not_found": [accountId...]}：表里找不到该账户不算错误
     * （户管的表不必包含所有账户）。整批合并进**一次** values().batchUpdate——
     * 单请求原子，避免「配额撞车导致前几行已落表」的半写与请求数爆炸。
     */
    public UpdateRowsResult updateRowsByAccountId(String spreadsheetId, String sheetName,
            List<RowPatch> rows, String keyCol) {
        if (rows == null || rows.isEmpty()) return new UpdateRowsResult(0, List.of());

        int keyIdx = colIndex(keyCol);
        List<List<Object>> grid = readSheetValues(spreadsheetId, sheetName, "A:" + keyCol);

        Map<String, Integer> rowOf = new LinkedHashMap<>();   // 账户ID → 1-indexed 行号
        for (int i = 0; i < grid.size(); i++) {
            List<Object> r = grid.get(i);
            if (r.size() > keyIdx) {
                // 表里写的是带前导 ' 的文本，去引号+去白后比较；首次出现优先
                String v = String.valueOf(r.get(keyIdx)).strip().replaceAll("^'+", "").strip();
                if (!v.isEmpty()) rowOf.putIfAbsent(v, i + 1);
            }
        }

        List<ValueRange> data = new ArrayList<>();
        List<String> pending = new ArrayList<>();   // 已定位到的 account_id，供失败定位
        List<String> notFound = new ArrayList<>();
        for (RowPatch item : rows) {
            Integer rowNum = rowOf.get(item.accountId().strip());
            if (rowNum == null) { notFound.add(item.accountId()); continue; }
            for (String rng : mergeRanges(new ArrayList<>(item.cells().keySet()))) {
                String[] se = rng.split(":");
                int start = colIndex(se[0]), end = colIndex(se[1]);
                List<Object> values = new ArrayList<>();
                for (int c = start; c <= end; c++) {
                    values.add(item.cells().getOrDefault(colLetter(c), ""));
                }
                data.add(new ValueRange().setRange(
                    a1Sheet(sheetName) + se[0] + rowNum + ":" + se[1] + rowNum).setValues(List.of(values)));
            }
            pending.add(item.accountId());
        }

        if (!data.isEmpty()) {
            try {
                sheetsService.spreadsheets().values()
                    .batchUpdate(spreadsheetId,
                        new BatchUpdateValuesRequest()
                            .setValueInputOption("USER_ENTERED").setData(data))
                    .execute();
            } catch (IOException e) {
                // 单请求原子：失败即整批未写入，「本次已写入 0 行」是如实表述，
                // 不要写成「表已部分写入、无回滚」
                throw new GoogleSheetsServiceException(
                    "批量更新行失败（本次已写入 0 行，涉及 account_id=" + String.join(",", pending) + "）", e);
            }
        }
        return new UpdateRowsResult(pending.size(), notFound);   // updated 按「已定位到的行数」计
    }

    /** 通用读取 Sheet 指定范围 */
    public List<List<Object>> readSheetValues(String spreadsheetId,
            String sheetName, String range) {
        // 返回二维列表
    }
}
```

#### 「我的看板」是**两张不同的表**（v1.34 补录）

> 本小节补的是上面 Java 方法注释里**只写了一半**的事实：那张「A-H 8 列」的表是 **GG** 的
> 「我的看板」；**TT 有一张自己的「我的看板」，列布局完全不同（A-J 10 列）**，
> 两者由**不同的端点**驱动。此前本文档只在 6.3 的 `sync-from-sheet` 条目里一句带过
> （「读 A:J 列」），极易被当成同一张表而套错列映射。

| | GG 我的看板 | TT 我的看板 |
|---|---|---|
| 端点 | `accounts_sync_from_sheet`（`main.py`） | `POST /api/tt/accounts/sync-from-sheet`（`py/routes/tt_accounts_routes.py`） |
| 列数 / 读范围 | **8 列**，`A:H` | **10 列**，`A:J` |
| 定位键 | `B` 账户ID | **`D` 账户ID** |
| 门禁列 | `A` 运营 == 当前用户 `display_name` | `A` 运营 == 当前用户 `display_name`（为空回落 `username`） |
| 跳过标记 | `H` 是否解绑 | **无**（TT 没有可用作跳过标记的列，故**不跳任何数据行**） |
| 双向？ | 是（`F` 备注、`H` 是否解绑由系统回写） | **仅备注一列**（v1.34 起，见附录 J）；其余列只读不写 |
| Java 侧对应 | `GoogleSheetsService.syncFromSheet`（方法注释见上） | 见下表 —— **不要**复用 GG 的 8 列映射 |

**TT 我的看板列模型（`A:J`，逐列）**：

| 列 | 表头 | 系统字段 | 方向 | 说明 |
|----|------|---------|------|------|
| `A` | 运营 | （门禁）| 只读 | 必须逐行等于当前用户 `display_name`（为空回落 `username`），否则整批 400 `看板「运营」列与当前账号不匹配，仅可同步自己的账户`。同时决定新建账户的 `owner_id` |
| `B` | 入库时间 | `acquired_date` | 只读 | |
| `C` | 是否回收 | （推导状态）| 只读 | `是` → 死亡；`可用`/空 → 存活。**与系统状态不一致时进 `status_conflicts`，不自动改**（见下） |
| `D` | 账户ID | `advertiser_id` | 只读（**定位键**）| 为空的行整行跳过；**必须 `isdigit()`**，非纯数字跳过 |
| `E` | BC | `bc_id` | 只读 | 系统里不存在时**自动新建**到 `tt_bcs` |
| `F` | 国家 | `country` | 只读 | |
| `G` | 所属渠道 | `agent_id` | 只读 | 系统里不存在时**自动新建**到 `agents` |
| `H` | 时区 | `timezone` | 只读 | 直接存文本（格式 `+8` / `-3`，**非** UTC）。**为空时**用 TT 设置页「地区时区」（`regions` 表）补 |
| `I` | 一周内消耗情况 | `consumption` | **双向** | 与系统值不一致时进 `conflicts` 弹窗，由用户选「以表为准 / 以系统为准」（见下） |
| `J` | 备注 | `remark` | **双向**（v1.34 起）| 见附录 J：首次入库时投手值优先、此后投手权威永久；系统→表的推送走 `key_col="D"` |

**配置来源（三层，缺一不可）**：

```
表 ID     : tags.tt_sheet_id                       （全局，所有投手共用同一张 spreadsheet，各占一个 tab）
sheet 名  : tags.tt_sheet_mappings.my_dashboard    （全局兜底）或 "我的看板"
            ↓ 被覆盖
            config.tt_sheet_mappings_{uid}.my_dashboard   （投手私有，原样取值、不 strip）
```

⚠️ 实测：`tags.tt_sheet_mappings` 只含 `{recycle, recharge, accounts}`，**不含 `my_dashboard`**；
私有配置现存于 uid 23/25/28/30/31，**29/32/33 未配**（走全局兜底）。以 `TT 设置 → Google Sheets`
区块维护（`TtSettingsPanel.vue`，见 v1.27 变更）。

**同步流程（表 → 系统）**：

1. 读 `A:J` → **跳过表头第 1 行**（否则「运营」表头会误触发门禁）→ 过滤 `D` 列为空的行。
2. **门禁**：`A` 列逐行校验（见上表）。**这是整批校验，不是逐行跳过** —— 有一行不匹配即整批拒绝。
3. 逐行生成 `{created, updated, conflicts, status_conflicts}`；`dry_run` 只比对不落库。
4. **确认模式**（`dry_run=false`）额外接受：
   - `resolutions: {advertiser_id: value}` —— 消耗冲突的裁决（「以表为准」时传表值）；
   - `status_resolutions: {advertiser_id: "存活"|"死亡"}` —— 状态冲突的裁决。
   ⚠️ 两者都**只允许改当前用户看板行内**（`A` 列门禁已保证）的 `advertiser_id`，非跨用户角色再加 `owner_id` 条件 —— 少了这层，用户可借 `advertiser_id` 改**任意账户**的消耗/状态。
   ⚠️ 状态裁决的取值**只接受 `"存活"` / `"死亡"`**（与表里 `C` 列二值一致），其他值忽略。
5. **新建账户**：`name` = `advertiser_id`；死亡户同时写 `death_date`；已软删的同 `advertiser_id` 记录**恢复复用**（`deleted_at=NULL`）而非新建，避免撞唯一约束。
6. **状态同步路径不得触发回收户清单写入**（`_trigger_recycle_if_dead`）—— 回收户清单是上游，同步只反映状态（见 v1.24 与 6.3）。
7. 结尾 `hd.writeback_rows(uid, "tt", touched_ids)` —— ⚠️ **对投手是一句静默空转**：该函数取的是
   调用者自己的 `huguan_dashboard_{uid}` 配置，投手没有这个键。**这是既有行为、不是缺陷**
   （见附录 J §已知后果 2）。投手看板的回写由 6.3 的 `updateAccount` 与户管同步两条路径承担。

**迁移红线**：

1. **TT 的 10 列映射不得套用 GG 的 8 列** —— 两张表列布局、定位键（`D` vs `B`）、跳过标记都不同。
2. **门禁是整批的**，不是逐行跳过；且 `A` 列值为空时回落 `username`（不是直接判不匹配）。
3. **`resolutions` / `status_resolutions` 的越权保护必须原样重建**（见上）。
4. **换行（追加新账户）不要实现**：本端点是「表里有、系统没有就建」，定位靠 `D` 列账户ID；
   不存在「追加到表尾」的语义（那是充值表/回收户清单的模式，别混）。
5. **投手看板的账户ID在 `D` 列** —— 任何面向它的 `updateRowsByAccountId` 调用都必须显式传
   `key_col="D"`（§8.1 的方法默认值是 `"C"`，那是户管看板）。

### 8.2 FB 数据提取服务

```java
@Service
@RequiredArgsConstructor
@Slf4j
public class FbExtractService {

    private final FbAdReportRepository fbAdReportRepository;
    private final GoogleSheetsService sheetsService;
    private final JdbcTemplate jdbc;

    /**
     * 解析提取文本 → 结构化数据（含尾部校验）
     * 对应 Python: POST /api/fb/extract/parse
     *
     * 解析流程：
     * 1. 找到"数据透视表"~"总成效"范围，动态分组提取每行账户数据
     * 2. "总成效"之后不再丢弃，改为提取校验数据：
     *    - 正则 "已显示\d+/(\d+)行" 提取声明总行数
     *    - 收集 $ 金额取最大值，验证其后紧跟"总花费"作为声明总消耗
     * 3. 返回 ParseResult{data, warnings, groupSize, validation}
     */
    public ParseResult parseExtract(String text, boolean sorted) {
        List<String> lines = List.of(text.split("\\n"));

        // 找到"数据透视表"~"总成效"范围
        int startIdx = -1, endIdx = -1;
        for (int i = 0; i < lines.size(); i++) {
            String line = lines.get(i).trim();
            if (line.contains("数据透视表") && startIdx < 0) startIdx = i + 1;
            if (line.contains("总成效") && endIdx < 0) endIdx = i;
        }
        if (startIdx < 0) throw new BusinessException("未找到\"数据透视表\"标记");
        if (endIdx < 0) endIdx = lines.size();

        // 解析尾部校验数据（"总成效"之后的内容）
        List<String> tailLines = lines.subList(endIdx, lines.size());
        int declaredRows = 0;
        double declaredSpend = 0.0;

        Pattern rowCountPattern = Pattern.compile("已显示\\d+/(\\d+)行");
        for (int i = 0; i < tailLines.size(); i++) {
            String line = tailLines.get(i).trim();
            Matcher m = rowCountPattern.matcher(line);
            if (m.find()) declaredRows = Integer.parseInt(m.group(1));

            if (line.startsWith("$")) {
                double amt = Double.parseDouble(line.replace("$", "").replace(",", ""));
                // 检查该行或后两行是否包含"总花费"
                String nearby = line + " " + String.join(" ",
                    tailLines.subList(Math.min(i + 1, tailLines.size()),
                                      Math.min(i + 3, tailLines.size())));
                if (nearby.contains("总花费")) {
                    declaredSpend = Math.max(declaredSpend, amt);
                }
            }
        }

        // === 动态分组（v1.14：支持短纯数字作为组起点） ===
        // 规则：当前行是「文本头」或「短纯数字(<10位，可能是账户名)」且下一行是 ≥10 位账户 ID → 新组开始
        List<String> dataLines = lines.subList(startIdx, endIdx);
        List<List<String>> groups = new ArrayList<>();
        List<String> currentGroup = new ArrayList<>();
        Pattern pureDigit = Pattern.compile("^[\\d,]+$");

        for (int i = 0; i < dataLines.size(); i++) {
            String line = dataLines.get(i);
            boolean isPureDigit = pureDigit.matcher(line).matches();
            int digitLen = isPureDigit ? line.replace(",", "").length() : 0;
            boolean isAccountId = digitLen >= 10;
            boolean isTextHeader = !isPureDigit
                && !line.startsWith("$") && !line.startsWith("[");
            boolean isShortNumber = isPureDigit && digitLen < 10;  // 短纯数字可能是账户名

            boolean nextIsAccountId = i + 1 < dataLines.size()
                && pureDigit.matcher(dataLines.get(i + 1)).matches()
                && dataLines.get(i + 1).replace(",", "").length() >= 10;

            if ((isTextHeader || isShortNumber) && nextIsAccountId) {
                if (!currentGroup.isEmpty()) groups.add(currentGroup);
                currentGroup = new ArrayList<>(List.of(line));
            } else {
                currentGroup.add(line);
            }
        }
        if (!currentGroup.isEmpty()) groups.add(currentGroup);

        // 逐组提取：group[0]=账户名, group[1]=账户ID(去逗号), group[2:]=$金额/纯数字

        // === 每组提取后的过滤逻辑（2026-08-01 新增） ===
        // 1. 去重：收集到的 $ 金额用 distinct 去重，相同值视为重复数据只保留一个
        // 2. 回流过滤：去重后若所有 $ 金额均为 0，跳过该行（回流数据：有账号名+ID但无实际消耗）
        // 3. 警告：去重后才判断 len > 2，避免重复 $ 金额导致误报警告

        List<FbReportRow> data = new ArrayList<>();
        List<String> warnings = new ArrayList<>();
        // ... 构建 data 和 warnings

        // 构建校验对象
        double extractedSpend = data.stream().mapToDouble(FbReportRow::getCost).sum();
        ValidationResult validation = ValidationResult.builder()
            .declaredRows(declaredRows)
            .extractedRows(data.size())
            .declaredSpend(Math.round(declaredSpend * 100.0) / 100.0)
            .extractedSpend(Math.round(extractedSpend * 100.0) / 100.0)
            .build();

        return ParseResult.builder()
            .data(data).warnings(warnings).groupSize(groups.get(0).size())
            .validation(validation)
            .build();
    }

    /**
     * 检查重复
     * 对应 Python: POST /api/fb/extract/check-duplicates
     */
    public DuplicateResult checkDuplicates(String productName, String lineName,
            String reportDate, List<FbReportRow> records) {
        // 按 (user_id, product_name, line_name, account_id, report_date)
        // 查询已有记录，返回重复项
    }

    /**
     * 保存提取数据（含异步写 Sheets）
     * 对应 Python: POST /api/fb/extract/save
     */
    @Transactional
    public int saveExtract(Long userId, String productName, String lineName,
            String reportDate, List<FbReportRow> records) {
        // 1. 写入 MySQL（fb_ad_reports 表 upsert）
        int saved = 0;
        for (FbReportRow rec : records) {
            int updated = jdbc.update("""
                INSERT INTO fb_ad_reports
                  (user_id, product_name, line_name, report_date,
                   account_name, account_id, cost, impressions, clicks,
                   registrations, purchases, cost_per_purchase)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
                ON DUPLICATE KEY UPDATE
                  account_name=VALUES(account_name), cost=VALUES(cost),
                  impressions=VALUES(impressions), clicks=VALUES(clicks),
                  registrations=VALUES(registrations),
                  purchases=VALUES(purchases),
                  cost_per_purchase=VALUES(cost_per_purchase),
                  updated_at=CURRENT_TIMESTAMP
                """,
                userId, productName, lineName, reportDate,
                rec.getAccountName(), rec.getAccountId(), rec.getCost(),
                rec.getImpressions(), rec.getClicks(),
                rec.getRegistrations(), rec.getPurchases(),
                rec.getCostPerPurchase());
            saved += updated;
        }

        // 2. 先持久化 Sheets 同步日志
        SheetsSyncLog syncLog = sheetsSyncLogRepository.save(
            SheetsSyncLog.builder()
                .userId(userId).productName(productName)
                .status("pending").rowsJson(toJson(records)).build());

        // 3. 异步写 Sheets（用 Spring 管理的业务线程池，不用 CompletableFuture）
        taskExecutor.execute(() -> {
            try {
                sheetsService.upsertFbReports(userId, productName,
                    lineName, reportDate, records);
                syncLog.setStatus("synced");
                sheetsSyncLogRepository.save(syncLog);
            } catch (Exception e) {
                log.error("[FB-Sheets] 写入失败: {}", e.getMessage());
                syncLog.setStatus("failed");
                syncLog.setErrorMsg(e.getMessage().substring(0, 500));
                syncLog.setRetryCount(syncLog.getRetryCount() + 1);
                sheetsSyncLogRepository.save(syncLog);
            }
        });

        return saved;
    }
}
```

### 8.3 其他核心服务设计概要

| 服务 | 关键功能 | Spring 技术 |
|------|---------|------------|
| **AccountService** | GG 账户 CRUD、批量操作、Sheet 同步 | JPA + @Transactional |
| **ProductService** | GG 产品 CRUD、包管理、在跑人员 | JPA |
| **MccService** | MCC CRUD、层级管理 | JPA |
| **RechargeService** | 充值提交、批量充值、Sheet 写入 | JPA + @Async |
| **AdReportService** | 报告 CRUD、去重、分析、AI 对话、CSV 导出 | JPA + RestTemplate |
| **YoutubeService** | 视频导入/列表/编辑、消费追踪 | JPA |
| **ScrapeService** | Google Play 截图抓取 | Jsoup |
| **VideoService** | AI 视频生成、FFmpeg 合成 | ProcessBuilder + @Async |
| **AuthService** | 登录/注册、JWT 签发、角色管理 | BCrypt + jjwt |
| **DataImportExportService** | 数据导入导出、备份恢复 | Jackson |
| **DelistService** | 掉包检测、通知 | @Scheduled + RestTemplate（代理池访问） |
| **NotificationService** | 邮件 + Telegram 通知 | JavaMailSender + RestTemplate |
| **FbService** | FB 全平台业务（BM/账户/产品/Pixel） | JPA + @Transactional |
| **OptionService** | 选项表 CRUD | JPA |
| **HuguanDashboardService** | 户管看板：列模型、表↔系统差异与归属变更协议（v1.31，见 7.9） | JPA + Sheets（`updateRowsByAccountId`）+ @Async 回写 |

### 8.4 账户状态变更清账（v1.4 加固）

**需求**: GG 账户从"存活"变更为非存活状态（如"死亡"）时，自动在 `recharge_records` 表中插入一条 `amount='清'` 的清算记录，并同步到 Google Sheets 充值表。

**现存问题**: 原逻辑依赖 `status_changed_date` 字段判断是否有"存活期间"的充值 → 该字段在账户创建时未设置，且可能因各种路径（Sheet 同步、直接改库等）不准确，导致清账被跳过。

**兜底方案**: 改为**直接查数据状态**，不依赖任何外部字段：

```sql
SELECT COUNT(*) FROM recharge_records r1
WHERE r1.account_id = ? AND r1.amount != '清'
AND NOT EXISTS (
    SELECT 1 FROM recharge_records r2
    WHERE r2.account_id = r1.account_id
      AND r2.amount = '清'
      AND r2.created_at > r1.created_at
)
```

逻辑：
1. 找到该账户下所有非"清"的充值记录
2. 检查每条充值之后是否存在"清"记录（`amount='清' AND created_at > 充值时间`）
3. 如果有未清的充值 → `need_clear = true` → 插入清账记录
4. **防重复**: `NOT EXISTS` 子查询天然阻止——已有"清"记录的充值不会被重复计算

**涉及位置**（Python → Java 迁移对照）:

| Python | Java | 说明 |
|--------|------|------|
| `accounts_update()` (单账户更新) | `AccountController.update()` → `AccountService` | 相同兜底 SQL |
| `accounts_batch_update()` (批量更新) | `AccountController.batchUpdate()` → `AccountService` | 相同兜底 SQL |

**与旧逻辑对比**:

| | 旧逻辑 | 新逻辑 |
|---|---|---|
| 判断依据 | `status_changed_date` | 充值表实际数据 |
| 依赖字段 | 必须正确维护 | 无外部依赖 |
| 重复清账 | 依赖时间比较 | NOT EXISTS 子查询天然防重复 |
| Sheet 同步路径 | 明确跳过 | 同样跳过（该路径不改状态） |

### 8.5 定时任务

> ⚠️ **v1.35 起，本节的 Java 骨架已被实质推翻。** 原骨架用 `@Scheduled(cron = "...")` **固定 cron** ——
> 它**表达不了**「周期由管理员在页面上配置、改完 30 秒内生效、无需重启」这个要求
> （cron 是启动期固定的，改它得改 yml 再重启）。
> **正解是「每 30 秒醒一次的 tick 循环 + 每 tick 重读配置」**，见下方新骨架与**附录 K**。
> 原骨架的 `scheduler.weekly-cleanup` / `scheduler.delist-check` 两个 yml cron **已作废**（见 §10.1 的 `scheduler` 段）。

**三个任务与其平台归属**（v1.35）：

| task key | 名称 | 平台 | 可配置项 | 默认值 |
|---|---|---|---|---|
| `gg_delist` | 掉包检测 | gg | 间隔（分钟） | **60** |
| `tt_delist` | TT 掉包检测 | tt | 间隔（分钟） | **30** |
| `cleanup` | 每周清理 | gg | 星期几 + 小时 | **周日(6) + 0 点** |

**周期下限 10 分钟、上限 1440 分钟**（用户裁定）。下限是**硬闸**：下方 10 分钟的理由是
`delist_checker._TIMEOUT = 5` + 代理池只有 2 个代理，更短的周期 Google Play 与代理池承受不住 ——
**读侧与写侧都要校验**（Java 侧同样：读配置时非法值回落默认、写接口越界返回 400）。

```java
@Component
@Slf4j
public class SchedulerTicker {

    /** 配置变更的生效粒度：每 30 秒醒一次，醒来时重算目标。 */
    private static final long TICK_SECONDS = 30;

    /** 每任务已累积的秒数（进程内状态；重启后归零 ⇒ 首次执行仍在启动后一整个周期）。
     *  ⚠️ 「启动时立即执行一次」的语义 Python 侧本就不存在（那段代码是注释掉的），此处不要新增。 */
    private final Map<String, Long> elapsed = new ConcurrentHashMap<>();

    /** 单一 tick 驱动三个任务 —— 不要用 cron，也不要每任务各起一个 Timer。 */
    @Scheduled(fixedDelay = TICK_SECONDS * 1000)
    public void tick() {
        for (TaskSpec t : TaskSpec.ALL) {                    // 见上表
            long prev = elapsed.merge(t.key(), TICK_SECONDS, Long::sum) - TICK_SECONDS;
            long target = schedulerConfig.intervalMinutes(t) * 60L;   // 每 tick 重读配置
            if (prev + TICK_SECONDS >= target) {             // 命中 ⇒ 执行并把累积清零
                elapsed.put(t.key(), 0L);
                runOne(t);                                   // GG/TT 掉包 或 每周清理
            }
        }
    }
}
```

**必须原样重建的语义**（细节与「为什么」见**附录 K**）：

1. **每 tick 重读配置** —— 这是「免重启生效」的**实现依据**，别把它「优化」成启动时读一次。
2. **只改「什么时候调」**：三个任务本体（`_run_delist_check_once` / `_run_tt_delist_check_once` /
   `_run_weekly_cleanup_once` 对应物）**逻辑一行不动**。
3. **每周清理不能退化成「同一天重复触发」**：原语义是「今天是周日但 00:00 已过 ⇒ 顺延一周」
   （`if target <= now: target += 7 days`）。⚠️ 原 Python 实现的 `_run_weekly_cleanup_once()` 是**裸调无 try/except**
   —— 异常会杀死该线程、**每周清理从此永久静默失效且无人知晓**；v1.35 补了保护，这是**唯一的行为变更**。
   周期改成「星期几 + 小时」后，它是**日历语义**，与两个间隔型任务不同。
4. **每次执行都要记账**（成功与失败都记）：写 `scheduler_last_run_{task_key}`，`ok` 记本轮成败。
   ⚠️ **一个任务一个 key** —— 单一 key 存整个 map 会让 6 个写者（3 个调度 + 3 个触发接口）
   互相覆盖，那是本版刻意根除的读改写竞态。
5. **权限**：三个 `POST /api/admin/trigger-*` 用 `scheduler_required(platform)`（**不是** `require_platform`）。

### 8.5.1 掉包检测代理池（v1.19）

**需求**: 掉包检测不再用服务端自身 IP，改走代理 IP 访问 Google Play，多出口轮换降低单 IP 被限流风险。

**结构**（对应 Python `py/proxy_pool.py` + `py/delist_checker.py`）：

```java
// delist/DelistProxyPool.java
@Component
public class DelistProxyPool {
    private final List<ProxyConfig> proxies;   // 启动时解析 delist-proxy.proxies[]，按 (ip,port) 去重
    private final boolean enabled;
    private final int maxRetries;

    /** 随机取一个代理，排除 exclude 中已尝试的 (ip,port)。无可用返回 null。 */
    public ProxyConfig next(Set<String> exclude) { ... }

    public boolean isEnabled() { ... }
    public boolean isEmpty() { return proxies.isEmpty(); }
    public int maxRetries() { ... }
}

// delist/DelistChecker.java
public DelistResult checkUrlDelisted(String url, DelistProxyPool proxyPool) {
    if (proxyPool == null || !proxyPool.isEnabled()) {
        return directCheck(url);   // 直连，行为与历史一致
    }
    if (proxyPool.isEmpty()) return DelistResult.notDelisted("代理池为空");
    Set<String> tried = new HashSet<>();
    String lastError = "";
    for (int i = 0; i < proxyPool.maxRetries(); i++) {
        ProxyConfig p = proxyPool.next(tried);
        if (p == null) break;
        tried.add(p.ip() + ":" + p.port());
        try {
            return requestAndJudge(url, p);   // 逐请求设置代理发请求，判 404/关键词
        } catch (TimeoutException | ConnectException e) {
            lastError = "代理失败 " + p.ip() + ":" + p.port();
        }
    }
    return DelistResult.notDelisted("代理全部失败: " + lastError);  // 绝不误判为掉包
}
```

**关键点**:
- `RestTemplate` 默认不支持按请求动态切换代理（`SimpleClientHttpRequestFactory.setProxy()` 是全局单一代理）。用 **Apache HttpClient**（每请求 `RequestConfig`/`HttpClientContext` 指定 proxy）或 **OkHttp**（每请求 `newBuilder().proxy(...)` 构造临时 client）实现逐请求换代理。
- 代理失败只返回 `is_delisted=false` + 带「代理」标识的 error；仅当拿到明确 404 / 关键词才判 `is_delisted=true`。切勿把代理异常当成掉包。
- `enabled=false` 或 `proxies` 为空时完全回退直连，与历史行为一致（向后兼容，出问题可一键关闭）。
- 代理池在单次检测任务内构造一次、复用，避免每 URL 重复解析配置。

### 8.6 异步配置

```java
@Configuration
@EnableAsync
public class AsyncConfig implements AsyncConfigurer {

    @Bean("ggAsyncExecutor")
    public Executor taskExecutor() {
        ThreadPoolTaskExecutor executor = new ThreadPoolTaskExecutor();
        executor.setCorePoolSize(5);
        executor.setMaxPoolSize(20);
        executor.setQueueCapacity(100);
        executor.setThreadNamePrefix("gg-async-");
        executor.setRejectedExecutionHandler(
            new ThreadPoolExecutor.CallerRunsPolicy());
        executor.initialize();
        return executor;
    }

    @Override
    public Executor getAsyncExecutor() {
        return taskExecutor();
    }

    @Override
    public AsyncUncaughtExceptionHandler getAsyncUncaughtExceptionHandler() {
        return (ex, method, params) ->
            log.error("Async method {} failed", method.getName(), ex);
    }
}
```

> **使用规范**: `@Async` 必须指定线程池名 `@Async("ggAsyncExecutor")`，禁止无参 `@Async` 或 `CompletableFuture.runAsync()`。

---

## 9. 外部集成

### 9.1 Google Sheets API

```yaml
# application.yml
google:
  sheets:
    credentials-path: ${GOOGLE_SHEETS_CREDENTIALS_PATH:config/service-account.json}
    application-name: GG-Server
```

实现类：`GoogleSheetsService`（详见 8.1 节）

### 9.2 Google Ads API

```java
@Service
@Slf4j
public class GoogleAdsService {

    /**
     * 列出经理账户下所有子账户
     */
    public List<String> listAccounts(GoogleAdsCredentials creds) {
        GoogleAdsClient client = buildClient(creds);
        // 使用 CustomerServiceClient 列出账户
        // ...
    }

    /**
     * 拉取广告系列报告
     */
    public List<CampaignReportRow> fetchCampaignReport(
            GoogleAdsCredentials creds, String accountId,
            String startDate, String endDate) {
        GoogleAdsClient client = buildClient(creds);
        String query = """
            SELECT campaign.name, metrics.cost_micros,
                   metrics.impressions, metrics.clicks,
                   metrics.ctr, metrics.conversions, metrics.cost_per_conversion
            FROM campaign
            WHERE segments.date BETWEEN '%s' AND '%s'
            """.formatted(startDate, endDate);
        // 执行 GAQL 查询
        // ...
    }

    private GoogleAdsClient buildClient(GoogleAdsCredentials creds) {
        return GoogleAdsClient.newBuilder()
            .setClientId(creds.getClientId())
            .setClientSecret(creds.getClientSecret())
            .setRefreshToken(creds.getRefreshToken())
            .setDeveloperToken(creds.getDeveloperToken())
            .setLoginCustomerId(Long.parseLong(creds.getManagerId()))
            .build();
    }
}
```

### 9.3 AI 视频生成

使用 **策略模式** 支持 5 个 Provider：

```java
// 接口
public interface AiVideoProvider {
    String generateVideo(String imagePath, int duration, String apiKey);
    String getProviderName();
}

// 豆包实现
@Component
public class DoubaoProvider implements AiVideoProvider {
    private final RestTemplate restTemplate = new RestTemplate();

    @Value("${ai.doubao.endpoint:https://ark.cn-beijing.volces.com/api/v3}")
    private String endpoint;

    @Override
    public String generateVideo(String imagePath, int duration, String apiKey) {
        // 1. 图片编码 base64
        // 2. POST 提交任务
        // 3. 轮询直到完成
        // 4. 下载 MP4
    }
}

// 工厂
@Component
@RequiredArgsConstructor
public class AiVideoProviderFactory {
    private final List<AiVideoProvider> providers;

    public AiVideoProvider getProvider(String name) {
        return providers.stream()
            .filter(p -> p.getProviderName().equalsIgnoreCase(name))
            .findFirst()
            .orElseThrow(() -> new BusinessException("Unknown provider: " + name));
    }
}
```

### 9.4 FFmpeg 视频处理

```java
@Component
@Slf4j
public class FfmpegService {

    @Value("${ffmpeg.path:ffmpeg}")
    private String ffmpegPath;

    @Value("${ffprobe.path:ffprobe}")
    private String ffprobePath;

    public String generateVideo(VideoTaskParams params) throws Exception {
        List<String> command = buildFfmpegCommand(params);

        ProcessBuilder pb = new ProcessBuilder(command);
        pb.redirectErrorStream(true);

        Process process = pb.start();

        // 有界输出读取（防 OOM）
        ByteArrayOutputStream out = new ByteArrayOutputStream();
        byte[] buf = new byte[8192];
        int total = 0, maxBytes = 10 * 1024 * 1024;
        try (InputStream is = process.getInputStream()) {
            int n;
            while ((n = is.read(buf)) != -1) {
                total += n;
                if (total > maxBytes) { process.destroyForcibly(); throw new BusinessException("FFmpeg输出超限"); }
                out.write(buf, 0, n);
            }
        }

        // 5 分钟超时
        if (!process.waitFor(300, TimeUnit.SECONDS)) {
            process.destroyForcibly();
            throw new BusinessException("FFmpeg 超时（5分钟）");
        }

        if (process.exitValue() != 0)
            throw new BusinessException("FFmpeg 失败: " + out.toString("UTF-8"));

        return params.getOutputPath();
    }

    // 并发限制：最多 2 个 FFmpeg 进程
    private final Semaphore ffmpegSemaphore = new Semaphore(2);

    public String generateVideoWithLimit(VideoTaskParams params) throws Exception {
        if (!ffmpegSemaphore.tryAcquire(5, TimeUnit.MINUTES))
            throw new BusinessException("FFmpeg 队列已满");
        try { return generateVideo(params); }
        finally { ffmpegSemaphore.release(); }
    }

    private List<String> buildFfmpegCommand(VideoTaskParams params) {
        // 构建完整 FFmpeg 滤镜链命令
        // 背景层 + 图片 xfade + Logo overlay + 文案 drawtext + 音频
        // ...
    }
}
```

### 9.5 邮件发送

```java
@Service
@RequiredArgsConstructor
public class EmailSender {

    private final JavaMailSender mailSender;

    @Value("${spring.mail.username}")
    private String fromAddress;

    @Async
    public void sendDelistNotification(List<String> recipients,
            PackageInfo pkgInfo) {
        try {
            MimeMessage message = mailSender.createMimeMessage();
            MimeMessageHelper helper = new MimeMessageHelper(message, "UTF-8");

            helper.setFrom(fromAddress, "GG-Server");
            helper.setSubject("[GG-Server] 检测到包掉包 - " + pkgInfo.getPackageName());
            helper.setText(buildDelistEmailBody(pkgInfo), false);
            helper.setTo(recipients.toArray(new String[0]));

            mailSender.send(message);
            log.info("掉包邮件已发送: {} → {}", pkgInfo.getPackageName(), recipients);
        } catch (Exception e) {
            log.error("发送邮件失败", e);
        }
    }
}
```

### 9.6 Telegram 通知

```java
@Service
@Slf4j
public class TelegramSender {

    private final RestTemplate restTemplate = new RestTemplate();

    @Value("${notification.telegram.bot-token}")
    private String botToken;

    @Value("${notification.telegram.chat-id}")
    private String chatId;

    // 产品级掉包通知：一个产品一条消息，展示产品名 + 多个系列名（不展示包名/链接）
    @Async
    public void sendProductDelistNotification(String productName,
            List<String> seriesNames, List<String> usernames) {
        String text = buildProductHtmlMessage(productName, seriesNames, usernames);
        String url = "https://api.telegram.org/bot" + botToken + "/sendMessage";

        Map<String, Object> body = Map.of(
            "chat_id", chatId,
            "text", text,
            "parse_mode", "HTML",
            "disable_web_page_preview", true
        );

        try {
            restTemplate.postForEntity(url, body, String.class);
            log.info("Telegram 产品级掉包通知已发送: {}", productName);
        } catch (Exception e) {
            log.error("Telegram 发送失败", e);
        }
    }

    private String buildProductHtmlMessage(String productName, List<String> seriesNames,
            List<String> usernames) {
        StringBuilder sb = new StringBuilder("<b>【GG-Server 掉包通知】</b>\n");
        if (!usernames.isEmpty()) {
            sb.append("\n").append(usernames.stream()
                .map(u -> "@" + u).collect(Collectors.joining(" ")));
        }
        sb.append("\n<b>产品：</b>").append(escapeHtml(productName)).append("\n");
        sb.append("<b>掉包系列：</b>\n");
        for (String sn : seriesNames) {
            sb.append("· ").append(escapeHtml(sn)).append("\n");
        }
        sb.append("\n该产品的多个包已被下架，请尽快将包状态设置为\"掉包\"。");
        return sb.toString();
    }
}
```

> **说明（v1.10 新增）**：对应 Python `telegram_sender.py` 的 `send_product_delist_notification`，消息不再包含包名与链接。

### 9.7 Google Play 抓取 (Jsoup)

```java
@Service
public class ScrapeService {

    public ScrapeResult scrapeImages(String url) throws IOException {
        Document doc = Jsoup.connect(url)
            .userAgent("Mozilla/5.0 (Windows NT 10.0; Win64; x64) " +
                "AppleWebKit/537.36 Chrome/120.0.0.0")
            .timeout(30000)
            .get();

        // 提取 <c-wiz jsrenderer='UZStuc'> 下所有 <img>
        Element cWiz = doc.selectFirst("c-wiz[jsrenderer=UZStuc]");
        List<String> imageUrls = new ArrayList<>();
        if (cWiz != null) {
            for (Element img : cWiz.select("img")) {
                String src = img.attr("src");
                if (src.contains("=w")) {
                    src = src.replaceAll("=w\\d+-h\\d+", "=w1200-h1200");
                }
                imageUrls.add(src);
            }
        }

        return new ScrapeResult(imageUrls.stream().distinct().toList());
    }

    public String scrapeLogo(String url) throws IOException {
        Document doc = Jsoup.connect(url)
            .userAgent("...").timeout(30000).get();

        Element logoDiv = doc.selectFirst("div.Mqg6jb.Mhrnjf");
        if (logoDiv != null) {
            Element img = logoDiv.selectFirst("img");
            if (img != null) return img.attr("src");
        }
        return null;
    }
}
```

---

## 10. 配置管理

### 10.1 application.yml 主配置

```yaml
server:
  port: ${SERVER_PORT:5001}

spring:
  application:
    name: lm-server

  # 数据库
  datasource:
    url: jdbc:mysql://${DB_HOST:localhost}:${DB_PORT:3306}/ggserver
          ?useUnicode=true&characterEncoding=utf8mb4
          &serverTimezone=Asia/Shanghai&useSSL=false
    username: ${DB_USERNAME:root}
    password: ${DB_PASSWORD:}
    driver-class-name: com.mysql.cj.jdbc.Driver
    hikari:
      maximum-pool-size: 30        # 30+ 用户 + 异步任务
      minimum-idle: 10
      connection-timeout: 30000
      idle-timeout: 600000
      max-lifetime: 1800000        # 30 min，低于 MySQL wait_timeout
      leak-detection-threshold: 10000

  # JPA
  jpa:
    hibernate:
      ddl-auto: validate  # 生产环境用 validate, 开发用 update
    show-sql: false
    properties:
      hibernate:
        dialect: org.hibernate.dialect.MySQLDialect
        format_sql: true

  # 邮件
  mail:
    host: ${SMTP_HOST:}
    port: ${SMTP_PORT:465}
    username: ${SMTP_USERNAME:}
    password: ${SMTP_PASSWORD:}
    properties:
      mail:
        smtp:
          ssl:
            enable: true
          auth: true

  # 文件上传
  servlet:
    multipart:
      max-file-size: 500MB
      max-request-size: 500MB

  # 缓存
  cache:
    type: caffeine
    caffeine:
      spec: expireAfterWrite=60s

# JWT
jwt:
  secret: ${JWT_SECRET:your-256-bit-secret-key-here-minimum-32-characters}
  access-token-expiration: 3600000       # 1 小时
  refresh-token-expiration: 2592000000   # 30 天

# Google
google:
  sheets:
    credentials-path: ${GOOGLE_SHEETS_CREDENTIALS_PATH:config/service-account.json}

# AI
ai:
  doubao:
    endpoint: https://ark.cn-beijing.volces.com/api/v3
  seedance:
    endpoint: https://api.atlascloud.ai/v1

# FFmpeg
ffmpeg:
  path: ${FFMPEG_PATH:ffmpeg}
  ffprobe-path: ${FFPROBE_PATH:ffprobe}

# 通知
notification:
  telegram:
    bot-token: ${TELEGRAM_BOT_TOKEN:}
    chat-id: ${TELEGRAM_CHAT_ID:}

# 定时任务（⚠️ v1.35 起：周期不再来自 yml，而是 admin 在页面上配置、存 config 表的
#            scheduler_config key。此处只留 tick 粒度与校验区间，cron 已作废）
scheduler:
  tick-seconds: 30              # 配置变更生效粒度
  min-minutes: 10               # 周期下限（硬闸，读写两侧都要校验）
  max-minutes: 1440             # 周期上限

# 掉包检测代理（v1.19，enabled=false 时直连）
delist-proxy:
  enabled: ${DELIST_PROXY_ENABLED:false}
  max-retries: ${DELIST_PROXY_MAX_RETRIES:3}
  proxies:
    - ip: ${DELIST_PROXY_1_IP:}
      port: ${DELIST_PROXY_1_PORT:0}
      username: ${DELIST_PROXY_1_USERNAME:}
      password: ${DELIST_PROXY_1_PASSWORD:}
      scheme: http        # http / socks5
    # ... 更多代理（按 (ip,port) 去重）

# 日志
logging:
  level:
    com.lmserver: INFO
    org.springframework.security: WARN
  file:
    path: ./logs
```

### 10.2 环境变量对照表

| 环境变量 | 说明 | 默认值 |
|---------|------|--------|
| `SERVER_PORT` | 服务端口 | 5001 |
| `DB_HOST` | MySQL 主机 | localhost |
| `DB_PORT` | MySQL 端口 | 3306 |
| `DB_USERNAME` | 数据库用户名 | root |
| `DB_PASSWORD` | 数据库密码 | (空) |
| `JWT_SECRET` | JWT 签名密钥 | (需设置) |
| `GOOGLE_SHEETS_CREDENTIALS_PATH` | Sheets SA 密钥路径 | config/service-account.json |
| `SMTP_HOST/USERNAME/PASSWORD` | SMTP 配置 | (空) |
| `TELEGRAM_BOT_TOKEN/CHAT_ID` | Telegram 配置 | (空) |
| `FFMPEG_PATH` | FFmpeg 可执行文件路径 | ffmpeg |
| `DELIST_PROXY_ENABLED` | 掉包检测代理开关（false=直连） | false |
| `DELIST_PROXY_MAX_RETRIES` | 单 URL 最多尝试代理数 | 3 |
| `DELIST_PROXY_N_IP/PORT/USERNAME/PASSWORD` | 第 N 个代理配置 | (空) |

---

## 11. 部署方案

### 11.1 开发环境

```bash
# 启动 MySQL（Docker）
docker run -d --name ggserver-mysql \
  -e MYSQL_ROOT_PASSWORD=root123 \
  -e MYSQL_DATABASE=ggserver \
  -p 3306:3306 \
  mysql:8.0

# 启动 Spring Boot
mvn spring-boot:run -Dspring-boot.run.profiles=dev

# 前端（不变）
cd frontend && npm run dev
```

### 11.2 生产环境

```bash
# 编译
mvn clean package -DskipTests

# 运行
java -jar target/lm-server-0.1.0-SNAPSHOT.jar \
  --server.port=5001 \
  --spring.datasource.url=jdbc:mysql://localhost:3306/ggserver \
  --spring.datasource.username=gguser \
  --spring.datasource.password=xxx \
  --jwt.secret=<your-secret-key> \
  --google.sheets.credentials-path=/opt/ggserver/config/service-account.json
```

### 11.3 前端代理配置

前端 `vite.config.js` 中的代理目标改为 Spring Boot 端口：

```javascript
// frontend/vite.config.js
server: {
  proxy: {
    '/api': {
      target: 'http://127.0.0.1:5001',  // Spring Boot 端口（不变）
      changeOrigin: true
    }
  }
}
```

### 11.4 Tailscale 部署架构

```
                    Tailscale 网络
    ┌──────────────────┼──────────────────┐
    │                  │                  │
┌───▼───┐       ┌─────▼─────┐      ┌────▼────┐
│ 用户A  │       │  服务器     │      │  用户B   │
│ 浏览器 │──────▶│ SpringBoot │◀─────│ 浏览器   │
│        │       │ :5001      │      │         │
└───────┘       │ MySQL :3306│      └─────────┘
                │ (Docker)   │
                └────────────┘
```

---

## 12. 迁移策略

### 12.1 数据迁移脚本

从 SQLite 导出到 MySQL：

```sql
-- 方案1: 使用工具
-- sqlite3 temp/app.db .dump | python sqlite_to_mysql.py

-- 方案2: 手动导出 CSV 后导入 MySQL
-- 每个表执行：.mode csv, .output table.csv, SELECT * FROM table;
```

关键转换：

| SQLite 值 | MySQL 转换 |
|-----------|-----------|
| `datetime('now','localtime')` | `CURRENT_TIMESTAMP` 由 MySQL 自动处理 |
| `'[]'` (JSON 字符串) | `JSON_ARRAY()` 或 `'[]'`（MySQL JSON 列） |
| `"role != 'developer'"` (SQL拼接) | JPA 参数化查询 |
| 自增 ID 从 1 开始 | 保持原值 (`SET foreign_key_checks=0; INSERT; SET foreign_key_checks=1;`) |

### 12.2 渐进式迁移建议

```
第一阶段（1-2周）：搭架子
├── Spring Boot 项目初始化
├── MySQL 建库建表
├── 数据迁移
├── 认证模块（JWT + Spring Security）
└── 前端代理指向新后端

第二阶段（2-3周）：GG 核心业务
├── 产品管理 → 账户管理 → MCC → 充值
├── 广告报告 → YouTube → 文案
└── 选项管理 → 设置 → 数据导入导出

第三阶段（2-3周）：FB 核心业务
├── BM 管理 → 账户管理 → 产品管理
├── Pixel → 数据提取 → 报告
└── Sheets 写表

第四阶段（1-2周）：辅助功能
├── 视频/AI/FFmpeg
├── 邮件/Telegram
├── 抓取/掉包检测
└── 管理员功能

第五阶段（1周）：测试与上线
├── 接口测试（与前端联调）
├── 性能测试
├── 文档完善
└── 正式切换
```

### 12.3 向后兼容检查清单

- [ ] 所有 268 个 API 路径不变
- [ ] JWT Token 格式保持 `Authorization: Bearer xxx`
- [ ] 响应格式保持 `{success, data/error}`（去掉 Python 的 `success` 外层包裹? → 保留，前端依赖）
- [ ] 分页格式保持 `{items, total, page, size}`
- [ ] 滑动过期 header `x-new-access-token` 保持
- [ ] CORS 配置允许前端跨域
- [ ] Hash Router 兼容（`window.location.hash` 平台检测）
- [ ] 文件上传 multipart/form-data 兼容
- [ ] CSV 导出响应头一致

### 12.4 密码哈希迁移

**问题**：Python 使用 `werkzeug.security.generate_password_hash()`（默认 `pbkdf2:sha256`），
Spring Boot 使用 BCrypt。两种哈希算法不兼容，迁移后现有用户密码无法直接验证。

**方案：兼容登录 + 自动升级**

```java
@Service
public class AuthService {

    // 新密码使用 BCrypt
    public String encodePassword(String rawPassword) {
        return passwordEncoder.encode(rawPassword);
    }

    // 验证密码 — 兼容两种哈希
    public boolean verifyPassword(String rawPassword, User user) {
        String storedHash = user.getPassword();

        // 1. BCrypt 哈希（新格式，$2a$ 开头）
        if (storedHash.startsWith("$2a$") || storedHash.startsWith("$2b$")) {
            boolean match = passwordEncoder.matches(rawPassword, storedHash);
            return match;
        }

        // 2. 旧 pbkdf2:sha256 哈希（werkzeug 格式）
        if (storedHash.startsWith("pbkdf2:sha256:")) {
            boolean match = verifyPbkdf2(rawPassword, storedHash);
            if (match) {
                // 自动升级为 BCrypt
                user.setPassword(passwordEncoder.encode(rawPassword));
                userRepository.save(user);
                log.info("用户 {} 密码已自动升级为 BCrypt", user.getUsername());
            }
            return match;
        }

        return false;
    }

    private boolean verifyPbkdf2(String rawPassword, String hash) {
        // 解析 werkzeug 格式: pbkdf2:sha256:iterations$salt$hash
        // 使用 Java PBKDF2WithHmacSHA256 验证
        String[] parts = hash.split("\\$");
        String[] methodParts = parts[0].split(":");
        int iterations = Integer.parseInt(methodParts[2]);
        String salt = parts[1];
        String expectedHash = parts[2];

        try {
            SecretKeyFactory factory = SecretKeyFactory.getInstance("PBKDF2WithHmacSHA256");
            KeySpec spec = new PBEKeySpec(rawPassword.toCharArray(),
                salt.getBytes(StandardCharsets.UTF_8), iterations, 256);
            byte[] derived = factory.generateSecret(spec).getEncoded();
            // werkzeug 使用 hex 编码
            String derivedHex = HexFormat.of().formatHex(derived);
            return derivedHex.equals(expectedHash);
        } catch (Exception e) {
            log.error("PBKDF2 verification error", e);
            return false;
        }
    }
}
```

**迁移步骤**：
1. 数据迁移时保持 `users.password` 字段原值不变
2. 用户首次登录时自动完成密码升级（透明的，无需用户操作）
3. 经过一段过渡期（如 3 个月）后，可移除旧哈希兼容逻辑

### 12.5 前端兼容性验证矩阵

迁移时必须逐接口验证响应格式，重点检查以下差异点：

| 检查项 | Python 行为 | Java 目标 | 前端读取 |
|--------|------------|----------|---------|
| 分页列表字段名 | `response.items` | `response.items` | `res.data.items` |
| 单对象字段名 | `response.data` | `response.data` | `res.data.data` |
| 纯列表字段名 | `response.data` | `response.data` | `res.data.data` |
| 分页元数据 | `response.total/page/size` | `response.total/page/size` | 顶层读取 |
| 错误字段名 | `response.error` | `response.error` | `res.data.error` |
| JWT 响应头 | `x-new-access-token` | `x-new-access-token` | axios 拦截器 |

> **验证方法**：迁移一个模块后，先用 Postman/Bruno 对比 Python 和 Java 的响应 JSON，
> 确认结构一致后再进行前端联调。

---

## 附录 A: 文件对照表

| Python 文件 | Java 替代 |
|------------|----------|
| `py/main.py` (9652行) | 拆分为 20+ Controller + 15+ Service |
| `py/auth.py` | `security/` + `AuthService` + `UserRepository` |
| `py/database.py` | JPA Entities + 46个 Repository + `schema.sql` |
| `py/routes/auth_routes.py` | `AuthController` |
| `py/routes/fb_routes.py` | 9个 FB Controller |
| `py/routes/tt_routes.py` | `TtController`（28 接口） |
| `py/routes/decorators.py` | `@FbPlatformRequired`, `@AdminRequired` AOP |
| `py/routes/helpers.py` | `ApiResponse` / `PagedResponse` + `SecurityUtil` + `RepositoryUtil` |
| `py/utils.py` | `util/` 包（`UrlUtil`, `NaturalSortUtil`, `ImageFormatUtil`） |
| `py/google_sheets_service.py` | `GoogleSheetsService` |
| `py/google_ads_service.py` | `GoogleAdsService` |
| `py/ai_service.py` | `AiVideoProvider` 接口 + 5实现 |
| `py/video_processor.py` | `FfmpegService` |
| `py/email_sender.py` | `EmailSender` |
| `py/telegram_sender.py` | `TelegramSender` |
| `py/scraper.py` | `ScrapeService` |
| `py/delist_checker.py` | `DelistChecker` |
| `py/proxy_pool.py` | `delist/DelistProxyPool` |
| `py/cache.py` | Caffeine `@Cacheable` |
| `py/resizer.py` | `ImageService` (Thumbnailator) |
| `py/data_service.py` | `DataImportExportService` |
| `py/manage.py` | Spring Shell 或 `CommandLineRunner` |

## 附录 B: 关键技术决策

| 决策点 | 选择 | 理由 |
|--------|------|------|
| ORM | Spring Data JPA | 46 张表，JPA 自动生成 CRUD |
| 数据库 | MySQL 8.0 | 用户要求，功能完整 |
| JSON 列 | MySQL JSON 类型 | runner_ids, settings 等字段原生 JSON 支持 |
| 缓存 | Caffeine | 单机部署，无需 Redis |
| 异步 | @Async + CompletableFuture | Sheets/邮件/Telegram 不阻塞 |
| 认证 | Spring Security + jjwt | 业界标准 |
| 定时任务 | `@Scheduled(fixedDelay)` + 每 tick 重读配置 | **不能用 cron**：周期须**运行时**可配（v1.35，见附录 K） |
| FFmpeg | ProcessBuilder | 保持子进程调用方式 |
| HTML 解析 | Jsoup | 完美替代 BeautifulSoup |
| 图片处理 | Thumbnailator | 替代 Pillow 基础操作 |
| 构建工具 | Maven | 更广泛的社区支持 |
| JDK 版本 | 17 (LTS) | 长期支持版本 |

---

> **文档结束** — 本文档涵盖从 Flask+SQLite 到 Spring Boot+MySQL 的全部迁移设计，包含 268 个 API、46 张表、15 个业务服务的完整设计方案。前端不变，仅替换后端。

---

## 附录 C: 后端架构审查与优化

> **审查日期**: 2026-07-31 | **审查员**: 后端架构师 Agent  
> **整体评分**: B（方向正确，安全/可靠性/代码复用待加强）

### C.1 严重问题（已修正）

| # | 问题 | 修正 |
|---|------|------|
| C1 | JWT 每次请求都签发新 token | 仅剩余有效期 < 30% 时续签 |
| C2 | `CompletableFuture.runAsync()` 绕过业务线程池 | 改为 `taskExecutor.execute()` + 持久化 sync_log |
| C3 | `@Transactional` 内异步导致事务不一致 | DB 写入和 Sheets 写入拆为独立方法 |
| C4 | FFmpeg ProcessBuilder 无超时 | 5min 超时 + Semaphore(2) 并发限制 + 有界输出读取 |
| C5 | CORS `*` + `allowCredentials(true)` | 改用白名单 + 明确 headers |
| C6 | JWT Secret 弱默认值 | 启动时 `@PostConstruct` 校验，拒绝默认值 |

### C.2 中等问题（已修正）

| # | 问题 | 修正 |
|---|------|------|
| M1 | FbService 将成上帝类 | 设计文档已拆分 GG/FB Service |
| M2 | 40 个 Repository 平铺 | 建议按 gg/fb/common 分包 |
| M3 | API 无版本控制 | 建议使用 `/api/v1/` 前缀 |
| M4 | Sheets 并发写入无锁 | 建议 `ConcurrentHashMap<String, ReentrantLock>` 按表格加锁 |
| M5 | 缺少速率限制 | pom.xml 已加 Bucket4j 依赖 |
| M6 | JWT 无法主动踢出用户 | `token_version` 字段支持改密/禁用时强制失效 |
| M7 | 缺少结构化错误码 | 建议 `ApiError{code, message, field}` |
| M8 | Refresh Token 无轮换 | 建议每次 refresh 换发新 token |
| M9 | 平台守卫 startsWith 绕过 | 改为 `AntPathMatcher` 通配符匹配 |
| M10 | Google Ads Client 未复用 | 建议 `ConcurrentHashMap` 缓存客户端 |

### C.3 增强建议

| # | 建议 | 状态 |
|---|------|------|
| S1 | GG/FB 平台提取公共基类 | 建议引入 `BaseAccount`、`BaseProduct` |
| S2 | MapStruct 自动 Entity↔DTO 转换 | pom.xml 已加依赖 |
| S3 | Caffeine 缓存分级 | 建议 options 5min / users 10min / sheets-credentials 长期 |
| S4 | Spring Actuator + Prometheus 监控 | 建议添加 |
| S5 | Resilience4j 熔断器保护外部 API | pom.xml 已加依赖 |
| S6 | HikariCP 连池增至 30 | 已修正 |
| S7 | `ad_reports`/`fb_ad_reports` 日期索引 | 已添加 |
| S8 | SpringDoc OpenAPI (Swagger) | pom.xml 已加依赖 |
| S9 | `@Async` 显式指定线程池 | 已添加使用规范 |

---

## 附录 D: 数据库设计审查与修正

> **审查日期**: 2026-07-31 | **审查员**: 数据库优化师 Agent  
> **交叉验证基准**: `py/database.py`、`py/auth.py`  
> **整体评分**: B+（结构完整，3 个阻塞问题已修复）

### D.1 阻塞级修正

| # | 表 | 问题 | 修正 |
|---|-----|------|------|
| D1 | `users` | 缺少 `config` 列（`auth.py` 直接查询） | 已添加 `config JSON` |
| D2 | `product_assets` / `video_consumption` | 缺少对 `videos(id, owner_id)` 的复合外键 | 已添加 `fk_pa_video_ref` / `fk_vc_video_ref` |
| D3 | `video_consumption` | `user_id` 应为 `NOT NULL` | 已修正 |

### D.2 其他修正

| # | 修正内容 |
|---|---------|
| D4 | `mcc` 表 4 个新增列标注 `【新增】` |
| D5 | 补充 FB 平台 `account_statuses` 种子数据 |
| D6 | 补充 `product_names` 标签种子 |
| D7 | 添加 `idx_vc_product`、`idx_accounts_created`、`idx_products_created`、`idx_fb_accounts_created`、`idx_videos_imported` 索引 |
| D8 | `users` 加 `token_version` 支持 JWT 主动失效 |
| D9 | MySQL 版本要求标注：8.0.13+ |

### D.3 数据迁移备忘

- SQLite → MySQL 时用 `SET foreign_key_checks=0` 临时关闭外键检查
- `deleted_at` 字段统一使用 `DATETIME NULL`
- `JSON` 列迁移前用 `JSON_VALID()` 校验
- `videos` 复合主键 `(id, owner_id)` 确保所有引用表 FK 一致

---

## 附录 E: v1.6 前端优化 + YouTube 标签修复

> **日期**: 2026-08-03

### E.1 账户表格内联编辑扩展

**文件**: `frontend/src/views/AdsAccountPanel.vue`

原有账户表格只有"账户名称"和"所属 MCC"两列支持内联编辑。本次扩展到**全部 5 个可编辑字段**：

| 列 | 编辑组件 | API 字段 | 说明 |
|---|---|---|---|
| 账户名称 | `<el-input>` | `{ name }` | 已有，不变 |
| 所属 MCC | `<el-select>` filterable | `{ mcc_id }` | 已有，不变 |
| **时区** | `<el-select>` filterable + allow-create | `{ timezone }` | **新增**，支持输入新区值 |
| **代理** | `<el-select>` filterable + clearable | `{ agent_id }` | **新增**，可清空 |
| **状态** | `<el-select>` filterable | `{ status_id }` | **新增**，后端自动处理状态变更时间+清账 |

交互模式统一：hover 显示 ✏️ 按钮 → 点击切换为编辑组件 → 选择/输入后自动保存 → blur 取消。

### E.2 表格 UI 整体优化

**列宽协调**（全部 10 列重新分配）：

| 列 | 宽度 | 说明 |
|---|---|---|
| 选择框 | width=45 | 不变 |
| 账号名称 | min-width=140 | 中文名需要空间 |
| 账号 ID | min-width=140 | 长数字 ID |
| 所属 MCC | min-width=140 | 两行显示（名/ID） |
| 时区 | min-width=120 | "Asia/Shanghai" |
| 代理 | min-width=140 | 中文代理名 |
| 状态 | min-width=120 | 标签+编辑按钮 |
| 到手时间 | min-width=100 | YYYY-MM-DD |
| 状态变更时间 | min-width=110 | YYYY-MM-DD |
| 操作 | width=200 | 4 个按钮 |

**文本截断统一**：所有 inline-edit-cell 中的 `.inline-cell-text` 统一应用：
```css
white-space: nowrap; overflow: hidden; text-overflow: ellipsis; flex: 1 1 auto;
```

**MCC 列改为上下行**：原来单行 `名字 · ID` 改为两行堆叠显示——上行名字、下行 ID，编辑按钮右侧垂直居中。

### E.3 YouTube 标签配置页空白修复

**问题**: 标签配置页（TagsConfig）textarea 全部显示为空，即使用户之前配置过标签。

**根因**:
1. **后端** `GET /api/youtube/tags`：数据库 `tags` 表无记录时返回 `{}`，前端 `store.tags = {}` 导致所有字段 `undefined`
2. **前端** TagsConfig 用 `v-show` 渲染，在父组件 `onMounted` 中 `store.loadTags()` 异步完成前就已挂载

**修复**:
1. **后端** [main.py](py/main.py) — `youtube_tags_get()` 加默认结构兜底：
   ```python
   tags = {
       "regions": [], "frame_types": [], "effectiveness": [],
       "product_names": [], "review_statuses": [],
   }
   ```
2. **前端** [TagsConfig.vue](frontend/src/components/youtube/TagsConfig.vue) — 新增 watch 监听：
   ```javascript
   watch(() => store.tags, () => loadCfgFromStore(), { deep: true })
   ```

### E.4 数据恢复说明

标签数据在 GitHub 的默认种子数据为（设计文档第 1194-1199 行）：
```sql
INSERT INTO tags (`key`, `value`) VALUES
('regions', '["巴西","菲律宾","孟加拉","印尼","东南亚通用","通用"]'),
('frame_types', '["融帧","非融帧"]'),
('effectiveness', '["","成效","一般"]'),
('review_statuses', '["能过审","不能过审"]'),
('product_names', '["p222","93ok"]');
```

迁移到 Spring Boot 后通过 MySQL 种子脚本自动初始化，无需手动配置。

---

## 附录 F: v1.8 产品包列表前端交互增强

> **日期**: 2026-08-13  
> **性质**: 纯前端改动，后端无变更  
> **文件**: `frontend/src/components/ProductCard.vue`

### F.1 需求背景

一个产品可能包含大量包。原实现将产品下所有包一次性展示、仅按「状态分组 → 导入时间」排序，且勾选只能逐个点击。本次增强三点：**状态过滤（默认只看正常包）**、**Shift 首尾范围选择**、**按系列名（series_name）排序**。

### F.2 状态过滤

- `filterStatus` 默认值由 `'all'` 改为 `'normal'`：产品展开后**默认只显示「正常」状态的包**。
- 状态筛选标签（全部/正常/没事件/暂停/掉包/拒登）放在**包列表顶部工具栏左侧**，不放产品栏 header。
- 最前面的 **「全部 N」** 标签（N=总包数）用于回到展示所有包的视图；各状态标签点击显示对应状态的包。
- 当前激活的状态标签以 `effect="dark"` 高亮，非激活为 `light`。

### F.3 Shift 首尾范围选择

- 新增锚点 `anchorId`：记录最近一次点击的包。
- 普通点击包 checkbox：正常勾选/取消该包，并更新锚点。
- **按住 Shift 点击包 checkbox**：按当前展示顺序，把「锚点包 ↔ 当前包」之间的连续所有包统一设为当前包的目标状态（选中或取消）。
- checkbox 由 `v-model` 改为 `:checked` 绑定 + `@change` 处理切换，并用 `@mousedown` 记录 Shift 状态（`change` 事件不携带 `shiftKey`）。视觉状态完全由 `checkedIds` 驱动；不再使用 `@click.prevent`（其会取消浏览器原生切换、导致勾选框视觉与状态不同步）。
- 工具栏「已选 N 个」旁新增 **「✕ 取消选择」** 按钮（`checkedIds.length > 0` 时显示），点击清空 `checkedIds` 并重置 `anchorId`，提供「部分选择时一键清空」的入口（v1.15 新增）。

### F.4 名字排序

- 排序按钮放在**包列表顶部工具栏左侧**（紧跟状态筛选标签），不放产品栏、不放工具栏右侧。
- 排序键为 **`series_name`（系列名）**，用 `localeCompare(..., undefined, { numeric: true })` 字典序比较（数字感知，`GG-9` 排在 `GG-10` 前）。
- 排序主按钮在 **「降序(Z→A) ↔ 升序(A→Z)」** 之间切换（首次点击进入降序），不在降序/升序/默认三态间循环。
- 进入排序状态后，旁边出现 **「恢复默认排序」** 按钮，点击恢复默认（状态分组 → 导入时间）。
- 排序生效范围（用户确认的规则）：
  - **展示所有包**（`filter='all'`，多状态混合）：只对「正常」包按系列名排序，其它状态包保持底部原有顺序不动；
  - **筛选单一状态**：对当前展示的所有包整体按系列名排序。

### F.5 后端影响

**无**。过滤、排序、勾选均在 `ProductCard.vue` 前端完成（`props.product.packages` 已随产品列表一次性返回）。

迁移到 Spring Boot 后，`GET /api/products/*` 接口只需按当前 Python 实现原样返回 `packages` 数组（原始顺序），**不做**按状态或名字的排序/过滤——这些逻辑由前端负责，迁移时不要在 Service 层重复实现。

---

## 附录 G: v1.16 产品头部与包筛选工具栏吸顶

> **日期**: 2026-08-14  
> **性质**: 纯前端改动，后端无变更  
> **文件**: `frontend/src/components/ProductCard.vue`

### G.1 需求背景

一个产品可能包含大量包。展开产品后往下滚包列表时，产品头部（产品名/KPI/地区那一栏）会滚出视野，用户既看不到「当前在看哪个产品」，也够不着包筛选工具栏。本次增强两点：**产品头部吸顶**、**包筛选工具栏随头部一起吸顶**。

### G.2 产品头部吸顶（position: sticky）

- 产品卡片根 `el-card` 增加类名 `product-card`。
- **关键坑**：Element Plus `.el-card` 默认 `overflow: hidden`，会把 `position: sticky` 的滚动容器锁定为卡片自身（卡片内部并不滚动），导致头部无法相对外层列表区（ProductPanel 的 `overflow-y:auto`）吸顶。必须先覆盖 `.product-card { overflow: visible }`。
- `.product-card :deep(.el-card__header)` 设 `position: sticky; top: 0; z-index: 10; overflow: hidden;`，并加不透明背景 `var(--el-card-bg-color)` 挡住从下方滚上来的包。
- sticky 天然满足「释放 / 重新钉住」语义：header 约束范围是 `.el-card`（整个产品卡片），滚到 `top:0` 后钉住，卡片底部（最后一个包）触到头部时被「推」着滚走释放，往回滚自动重新钉住，无需 JS。
- 圆角裁剪下放：覆盖 `overflow:visible` 后卡片原本靠 `overflow:hidden` 做的圆角裁剪失效，改为 header 加顶部圆角、`.el-card__body` 加 `overflow:hidden` + 底部圆角。

### G.3 包筛选工具栏吸顶（移入 header）

- 原「包筛选工具栏」（状态筛选标签 / 名字排序 / 全选 / 批量操作，原在 `.el-card__body` 内）整体移入 `<template #header>` 插槽、产品头部 div 之后，并加 `v-show="expanded"`（原来靠外层 `v-show` 控制）。
- 这样它随 `.el-card__header`（已 sticky）一起吸顶，**无需动态计算 `top`**（产品头部 flex-wrap 换行、高度不固定，单独 sticky 会因 `top` 值无法确定而错位）。
- 去掉工具栏自身 `border-bottom`（避免与 header 自带 border 双线），加 `margin-bottom: -10px` 抵消 header 默认 18px 底部 padding，使工具栏上下间距对称。
- 工具栏移出产品头部 div 后成为其兄弟节点，点击工具栏不再触发展开/收起（原来也不触发）；内部 `@click.stop` 保留，行为不变。

### G.4 后端影响

**无**。吸顶为纯 CSS（`position: sticky`）+ DOM 位置移动，不涉及任何接口、数据或 Service 逻辑。迁移到 Spring Boot 时无需在 Controller/Service 层做任何处理。

---

## 附录 H: v1.32 TT 账户列表移除「账户名称」列

> **日期**: 2026-10-06  
> **性质**: 纯前端改动，后端无变更  
> **文件**: `frontend/src/views/tt/TtAccountPanel.vue`

### H.1 需求背景

TT 广告账户列表（`/tt/accounts`）第 2 列是「账户名称」。用户裁定 TT 侧不需要在列表里展示账户名（**仅 TT**，GG / FB 保持原样）。

### H.2 改动内容

改动前该列是 TT 账户名**唯一的**内联编辑入口：hover 出现 ✏️ → 切换成 `<el-input>` → `ttAccountsApi.update(row.id, { name })` 保存。

1. **删除表格列**「账户名称」（原 `min-width=140`，含其内联编辑模板）。
   移除后列顺序为：选择框 → 广告账户 ID → 所属 BC → 时区 → 代理 → 国家 → 消耗 → 到手时间 → 状态变更时间 → 户归属（仅户管）→ 操作。
2. **清理专为该列存在的状态与函数**：`editingNameId` / `editNameValue` / `nameInputRef`，以及 `startEditName` / `cancelNameEdit` / `saveName`（已核零残留引用）。
   **未删**：`nextTick`、CSS 类 `.inline-name-input` 与 `.inline-edit-btn` —— 它们仍被「国家」「消耗」等其他内联编辑使用。
3. **搜索框 placeholder** 由「🔍 搜索名称/广告账户 ID...」改为「🔍 搜索广告账户 ID...」。

### H.3 刻意保留的不一致（交接/迁移时勿「顺手修正」）

**搜索框提示词不再提「名称」，但后端仍按 `name` 匹配。** 用户明确选择「只改 placeholder 文案、不动后端 SQL」。

`GET /api/tt/accounts/list`（`py/routes/tt_accounts_routes.py:197`）的 `list_accounts()` 内**两处** search 条件均**保持原样**：

| 位置 | 用途 | 条件 |
|---|---|---|
| `tt_accounts_routes.py:224` | 主列表查询 | `(a.name LIKE ? OR a.advertiser_id LIKE ?)` |
| `tt_accounts_routes.py:269` | 各状态计数（`sc_where2`，不含 status 筛选） | 同上 |

即：**账户名只是不在列表里显示，按名搜索的通道仍然保留**。改成「只按 advertiser_id 搜」是另一次独立决策，不要顺带做。

### H.4 改名入口与后端影响

- **改名能力未丢失**：行尾 ✏️ 打开 `TtAccountModal`，其中「账户名称」仍是**必填**字段（新增与编辑共用该弹窗）。本次未动该弹窗。
- **其余展示点未动**（用户选择「只去账户列表那一列」）：`TtAccountDetailModal.vue`（详情弹窗「账户名称：xxx」）、`TtAccountDeletedModal.vue`（已删除账户列表的「账户名称」列）**均保持原样**。
- **GG / FB 未动**：GG 侧见附录 E.1（`AdsAccountPanel.vue` 的账户名内联编辑，本次不动）；FB 侧 `FbAccountPanel.vue` 的「账户名」列**保持原样**。
- **后端影响：无**。`tt_accounts.name` 字段、DDL、接口契约一律未动，**不存在数据迁移动作**。迁移到 Spring Boot 时无需在 Controller / Service 层做任何处理。

---

## 附录 I: v1.33 TT「换绑情况」列改造

> **日期**: 2026-10-06
> **性质**: **改需求**（非 bug 修复）—— 推翻 v1.31 制定的归属协议中**仅 TT 的部分**
> **权威设计**: `2026-10-06-tt-owner-change-note-design.md`
> **取代范围**: `2026-09-23-huguan-sheet-design.md` 的 §7.1、§7.2 规则 1、规则 3② 中**仅 TT 的部分**
> **影响文件**: `py/database.py`、`py/huguan_dashboard.py`、`py/routes/huguan_dashboard_routes.py`、`py/routes/tt_accounts_routes.py`、`frontend/src/views/tt/TtAccountPanel.vue`

### I.1 需求背景与定性

v1.31 定下「变更通道列的值优先于运营列」：TT 的 `L` 列「换绑情况」非空时压过 `G` 列「接户运营」
（设计文档 `2026-09-23-huguan-sheet-design.md:35` 留有用户原话）。用户 2026-10-06 裁定**取消该规则**，
把 `L` 列改作**换绑记录字段**。

**这是改需求，不是 bug 修复** —— v1.31 的实现是按当时要求做的，本次是要求变了。
因此 §7.9 与首部变更摘要是**有据地更正**，不是「实现偏离了设计」。

**仅 TT**。GG 的「重新分配」（`H` 列）承载的是另一套已上线流程，**逐字节不变**。

### I.2 变更内容

| 项 | v1.31（旧） | v1.33（新） |
|----|-----------|-----------|
| TT 归属判定 | `_owner_channel`（`L` 列）非空则压过 `owner_name`（`G` 列） | **恒取** `G` 列「接户运营」；`effective_owner_name(parsed, platform)` 按平台分叉 |
| `L` 列语义 | 合成字段 `_owner_channel`（归属变更通道） | 真实数据库列 `owner_change_note`，**普通文本**、`writable=False` / `readable=True` |
| `L` 列写入 | 户管在系统 UI 改归属 ⇒ 写**新归属人名** | 同一时机 ⇒ 写 `旧归属人转新归属人+月.日`（如 `阿轩转黎明10.7`），**同时落库** `owner_change_note`，两处同一份文本 |
| 同步后清空 `L` | 规则 3②：应用归属变更后清空为 `""` | **对 TT 不再执行**（改 GG-only）。对 TT 执行会抹掉记录，且因读回按表覆盖会**连带清掉系统值**（双重抹除） |
| `L` 列读回 | 驱动归属 | 读回**原样存进** `owner_change_note`，**不影响归属**；空值按表覆盖（表里清空 → 系统也清空），并进 `clears` 让户管看见 |
| 前端 | 无「换绑情况」列 | `TtAccountPanel.vue` 加**只读**「换绑情况」列（`v-if="authStore.isHuguan"`，紧挨「户归属」） |

**DDL 变更（1 列，已在 §5.2 同步）**：

```sql
owner_change_note TEXT DEFAULT '' COMMENT '换绑记录（旧归属人转新归属人+月.日，v1.33）'
```

**无数据迁移动作**：老库里该列全为空串。`tt_accounts` 此前**没有任何** `_add_column_if_missing`
迁移记录，故实现时**建表语句与迁移条目两处都要加** —— 生产库 `temp/app.db` 已存在，
`CREATE TABLE IF NOT EXISTS` 对其**不生效**，只有 `_ensure_columns()` 里的
`_add_column_if_missing` 能把列补上。Java 侧对应「建表 DDL + 启动时幂等的 schema 补丁」。

**月日格式**：`f"{now.month}.{now.day}"`，**不补零**（10 月 7 日 → `10.7`；10 月 10 日 → `10.10`）。
**不得**用 `strftime("%-m")` —— Windows 平台不支持该格式符。旧归属人解析不到时写 `未分配`。
文本与落库值必须**同源**（在 reassign 端点内构造一次），不要两处各构造一遍。
**注意**：`display_name` 仅含空白时它是 truthy、会顶掉 `or` 兜底，`.strip()` 后得到空串
→ 记录退化成 `转10.7`。必须**先 strip 再 or**。

### I.3 与 §7.9 的对应关系

| §7.9 条款 | 处理 |
|-----------|------|
| 规则 1（变更通道优先） | TT **作废**；GG 保留 |
| 规则 2（自动回写不碰通道列） | TT **效果保留**（改由 `writable=False` 实现）；GG 保留原实现 |
| 规则 3①（系统 UI 改归属写 L） | TT **保留但内容变更**（见 I.2） |
| 规则 3②（同步后清空通道列） | TT **作废**；GG 保留 |
| 规则 4（落库后回写运营列） | TT / GG **均保留**（TT 的 `G` 列现在是唯一归属列，更需要它） |
| 「归属不新增数据库列」 | **仅对 `owner_id` 成立**；归属判定本身仍不新增列，但换绑记录新增了 `owner_change_note` |

### I.4 迁移红线

1. **`effective_owner_name` 的 `platform` 参数必须是必填位置参数，不得给默认值** ——
   默认值会让漏传的 TT 调用方**静默拿到 GG 语义**，正是本次要消除的缺陷。
2. **GG 的四条规则逐字重建**；TT 走 I.2 的新语义。把 TT 也按规则 1 实现，会让归属被 `L` 列的
   记录文本劫持（例如 `阿轩转黎明10.7` 会被当成一个叫这个名字的运营去找用户）。
3. **`L` 列不得改成可写**。它靠 `writable=False` 排除出 `cells_for_row` —— 这是「自动回写永不碰
   换绑记录」的**唯一**保障，机制与 GG 的 `H` 列（靠 `field == "_owner_channel"` 守卫）不同、效果相同。
4. **`L` 列的读回按表覆盖**是刻意的（与其他文本列同口径）—— **不得**加 `if not value: continue`
   之类的空值跳过，否则户管永远无法从表里清掉一条记录。
5. **同步后的清空动作必须分平台**：TT 不清 `L`。漏掉这个分叉，每次同步都会抹掉换绑记录。

---

## 附录 J: v1.34 TT 备注（`remark`）跨看板同步优先级

> **日期**: 2026-10-06
> **性质**: 新增同步优先级规则 + **新建一条此前不存在的推送通路**
> **权威设计**: `2026-10-06-tt-remark-sync-precedence-design.md`
> **影响文件**: `py/huguan_dashboard.py`、`py/routes/huguan_dashboard_routes.py`、`py/routes/tt_accounts_routes.py`、`frontend/src/views/tt/TtAccountPanel.vue`

### J.1 需求背景

`tt_accounts.remark` 被**两张 Google 表同时读写**：投手「我的看板」`J` 列「备注」、
户管看板 `M` 列「产品信息」。两边都是 `writable=True` + `readable=True`，谁后同步谁赢。
更严重的是「文本列空值照常落库」的口径 ⇒ **户管看板 `M` 列空着，同步一次就会把投手填的备注清掉**。

**附带发现**：**「系统 → 投手看板」的推送链路此前根本不存在**。所有推送都走
`push_rows(user_id, ...)`，它取的是 `user_id` 自己的 `huguan_dashboard_{uid}` 配置 ——
而投手没有这个键，所以 `sync_from_sheet` 结尾那句 `hd.writeback_rows(uid, ...)` 对投手是
**一句静默空转**。

### J.2 规则（用户逐条确认）

| 场景 | 结果 |
|------|------|
| 首次入库（户管触发），投手看板 `J` 列**有值** | **投手赢**：覆盖系统 + 回写户管看板 `M` 列 |
| 首次入库（户管触发），投手 `J` 列**空** | **户管赢**：系统用户管 `M` 列值 + 推给投手看板 `J` 列 |
| 首次入库（投手触发） | 直接用投手 `J` 列的值，**不额外读户管看板**（分触发方处理） |
| 账户已存在，户管改 `M` 列 | **不生效** —— 投手权威永久 |
| 投手在系统内联编辑备注 | 推**两张表** |
| 投手同步（`J` 列） | 不生效（维持现状，只处理消耗/状态冲突） |

**只改 `remark` 一个字段**；**仅 TT**；**不新增表、不新增数据库列**。

### J.3 实现要点（Java 侧必须重建的语义）

1. **权威判定天然映射到 `build_diff` 的 `to_create` / `to_update` 两个分支**，故**零新增状态**。
   实现方式是给 `to_update` 的字段过滤**追加一个剔除条件**：
   `and not (platform == "tt" and k == "remark")`。
   ⚠️ **不得**把 `remark` 从 `_PLAIN_TEXT_FIELDS["tt"]` 里删掉 —— 该清单被 `to_create` 与
   `to_update` **共用**，删掉会让「首次入库读户管 `M` 列」那一支失效。
   **附带收益**：`_blank_columns` 不再为已存在账户把 `remark` 报进 `clears`，
   「户管空值清空投手备注」从此不可能发生。
2. **读投手看板发生在 `apply_diff`（落库阶段）而非 `build_diff`（`dry_run`）** ——
   后者承诺只读且会被空跑调用，在其中发起网络读取会让预览变慢并引入失败面。
   代价：`dry_run` 预览**看不到**投手看板的影响（见 J.4）。
   **缓存必须是单次 `apply_diff` 调用内的局部字典**（按 owner 惰性读取），
   **不得**做成模块级缓存 —— 表内容随时可变，跨请求缓存会让户管看到过期值。
3. **`apply_diff` 返回两个新键**（由路由层 `pop` 后消费）：
   `remark_m_writeback: [{account_id, value}]`（投手赢 → 回写户管 `M`）、
   `remark_operator_push: [{owner_id, account_id, value}]`（户管赢 → 推投手 `J`）。
   在 `platform != "tt"` 时**恒为空列表**。
   ⚠️ **`owner_id` 为 `None` 的行不产生 `remark_operator_push` 记录**（归属解析不到的 TT 行
   确实会进 `to_create`，但它没有投手看板可推）。该键的元素类型声明是 `owner_id: int`，
   **不得吐 `None`**。
4. **新建推送函数 `push_remark_to_operator_dashboard(owner_id, account_id, value)`** ——
   面向投手看板，配置取自 `tags.tt_sheet_id` + 每投手的 `my_dashboard`；
   与 `push_rows`（面向户管看板、配置取自 `huguan_dashboard_{uid}`）**不是一回事**。
   ⚠️ **投手看板的账户ID在 `D` 列**（户管看板在 `C` 列）—— 调 `update_rows_by_account_id`
   **必须显式传 `key_col="D"`**，漏传会默认 `"C"` 并**静默定位到错误的行**。
   只写 `{"J": value}` **单列**，绝不整行推送；走后台线程；**绝不抛异常**。
5. **投手看板 sheet 名的解析顺序**（**必须与 `sync_from_sheet()` 逐字一致**，否则读与写会
   对着不同的 tab 操作）：

   ```
   sheet_name = tags.tt_sheet_mappings.my_dashboard  或  "我的看板"      # 全局兜底
   若 config.tt_sheet_mappings_{owner_id}.my_dashboard 非空 → 用它覆盖     # 投手私有（原值，不 strip）
   ```

   ⚠️ 私有值**原样透传、不得 strip** —— 既有写入路径用的是原值，一致才安全。
   实测：`tags.tt_sheet_mappings` 只含 `{recycle, recharge, accounts}`，**不含 `my_dashboard`**；
   私有配置在 `config.tt_sheet_mappings_{uid}`（现存 uid 23/25/28/30/31，29/32/33 未配）。
6. **`PUT /api/tt/accounts/{id}` 带 `remark` 时推两张表**：户管看板 `M` 列 + 投手看板 `J` 列。
   `owner_id` 取**该账户当前的 `owner_id`**（不是调用者 uid）—— 户管可能代改别人名下的户。
   ⚠️ **户管看板那次回写不要自己在 commit 之前加**：`update_account()` 尾部**本来就有**一条
   post-commit 的全量单行回写，而 `cells_for_row` 已含 `M` 列 —— 再加一条只会在
   `db.commit()` 之前用**新连接读到未提交的旧值**，并与尾调用的后台线程**并发写同一行**。
7. **前端**：`TtAccountPanel.vue` 在「消耗情况」列后加**可内联编辑**的「备注」列。
   该文件已有六列内联可编辑，**必须复用既有的 `.inline-*` 类与「✏️ 按钮进入 + Esc 取消 +
   成功/失败都提示」惯例**，不要发明新交互；失败时**不要**回写 `row.remark`（保持原值即天然回滚）。

### J.4 已知后果（实现后仍成立，勿当缺陷修）

1. `dry_run` 预览看不到投手看板的影响（读取在落库阶段）。
2. 投手改备注时户管看板**不会即时刷新** —— `writeback_rows` 用的是调用者 uid 的
   `huguan_dashboard_{uid}` 配置，投手没有它 → 该步**静默空转**（既有行为）。户管看板靠
   `dashboard_push` 全量刷新对齐。
3. 投手看板读不到时**静默降级为「户管赢」**并记日志 —— 读不到投手看板不得阻断户管同步。
4. 投手看板里**没有该账户行**时，`update_rows_by_account_id` 返回 `not_found` 且**不建行**
   （既有契约：系统只改单元格、不建行）。

---

## 附录 K: v1.35 定时任务权限下放 + 周期可配置

> **日期**: 2026-10-07
> **性质**: 新增权限模型 + 新增配置接口与界面 + **实质推翻 §8.5 原 Java 骨架**
> **权威设计**: `2026-10-07-scheduler-admin-access-and-interval-config-design.md`（设计）、
> `2026-10-07-scheduler-frontend-visual-design.md`（视觉）、`2026-10-07-scheduler-open-findings.md`（审查发现结项记录）
> **影响文件**: `py/routes/decorators.py`、`py/main.py`、`frontend/src/{views/SchedulerView.vue, components/AppSidebar.vue, router/index.js, api/admin.js}`

### K.1 用户口述的四件事

1. **补文档缺口**：本文档接口表漏了 `POST /api/admin/trigger-tt-delist-check`（已在 §6.3 更正为 3 个）。
2. **定时界面权限下放到所有管理员**（不再仅 developer）。
3. **管理员按平台看到对应任务**，后端也按平台限制调用。
4. **新增「手动修改定时周期」的接口与界面**。

| 用户裁定 | 结论 |
|---|---|
| FB 管理员（平台无任务）看到什么 | **显示空态提示**，保留菜单入口（`tasks: []`，**不是** 403） |
| 每周清理怎么配 | **星期几 + 时刻**（保留日历语义），默认仍周日 00:00 |
| 掉包周期下限 | **10 分钟** |
| 间隔上限 | **1440 分钟（24 小时）** |
| 是否显示「上次执行时间」 | **要显示** |

### K.2 权限模型

**新增装饰器** `scheduler_required(platform)`（`py/routes/decorators.py`）：
developer **跨平台放行**；admin 须 `user.platform == platform`；其余（含**户管**）一律 **403**。

> ⚠️ **绝不复用 `require_platform()`** —— 它的 `PLATFORM_SWITCH_ROLES = ("developer", HUGUAN_ROLE)`
> **含户管**，会把户管无条件放行，等于给户管开定时任务的后门。这是本版最容易踩的坑，
> `py/tests/test_scheduler_config.py::TestSchedulerRequired::test_huguan_rejected` 就是它的对照腿。

| 角色 | 可见 | 可「立即执行」 | 可改周期 |
|---|---|---|---|
| developer | 全部三项 | 全部 | 全部 |
| admin (platform=gg) | `gg_delist` + `cleanup` | 同左 | 同左 |
| admin (platform=tt) | `tt_delist` | 同左 | 同左 |
| admin (platform=fb) | **无 → 空态** | — | — |
| huguan / user / viewer | 无（入口不可见） | 403 | 403 |

**前端隔离是三重自洽的**（不需要新标记）：
侧边栏三份 nav（gg/fb/tt）里定时任务项的父级本是 `admin: true`；户管用**独立的**三份 nav
（`huguanNavItems` / `huguanFbNavItems` / `huguanTtNavItems`）**本就没有定时任务项**；
路由 `meta.developer` → `meta.admin`，而户管白名单 `HUGUAN_ROUTES` **不含** `/admin/scheduler`。

### K.3 周期配置的数据结构（两个 key）

```
config.scheduler_config           ← 管理员意图（只有管理员 PUT 时写）
  {"gg_delist_minutes": 60, "tt_delist_minutes": 30,
   "cleanup_weekday": 6, "cleanup_hour": 0}

config.scheduler_last_run_{task_key}   ← 运行事实（只有调度/触发路径写），如
config.scheduler_last_run_gg_delist = {"ts": "2026-10-07 12:00:03", "ok": true}
```

**为什么是两个 key 而不是一个**：

1. **写侧不同** —— config 只有管理员 PUT 时写；last_run 只有任务跑完时写。混在一起，
   两个写侧就变成 read-modify-write 竞争：管理员保存周期的同时任务跑完，后写的一方抹掉另一方。
2. **权限不同** —— config 是「有权限才能改」，last_run 是「人人可读」的运行时状态。

**为什么 `last_run` 还要再拆到每任务一个 key**（v1.35 审查后追加）：

`last_run` 自己就有 **6 个写者**（3 个调度 + 3 个触发接口）。单 key 存整个 map 时，
「读整个 dict → 改子键 → 写回整个 dict」两个写者交错会**丢更新**，把另一任务的时间戳退回旧值。
拆到每任务一个 key 后，写入是**单条 `INSERT OR REPLACE`**，天然原子 ——
**共享状态根本不存在，因此不需要锁**。（初版曾用一把 `threading.Lock` 兜住；拆 key 后已删掉锁。）

> **迁移红线**：Java 侧**不要**把两者并进同一个 key，也**不要**把 last_run 收回单 key 再靠锁兜 ——
> 拆开是刻意的，注释在 `py/main.py` 的 `_mark_task_run` 上方。

**校验规则**（写侧违反一律 400；**读侧非法值一律回落默认，不得抛异常** ——
`_get_scheduler_config` 被调度线程每 30 秒调一次，它崩了等于定时任务全停）：

| 字段 | 规则 |
|---|---|
| `gg_delist_minutes` / `tt_delist_minutes` | 整数，**10 ≤ v ≤ 1440** |
| `cleanup_weekday` | 整数 0–6（**0=周一 … 6=周日**，Python 约定） |
| `cleanup_hour` | 整数 0–23 |

> ⚠️ **布尔是 Python 的陷阱**：`True == 1`，故 `isinstance(v, int)` 会放行 `true`。
> 对 `cleanup_weekday` / `cleanup_hour`（区间含 1）必须额外 `not isinstance(v, bool)`，
> 否则 `{"cleanup_weekday": true}` 会**静默变成「周一」**。
> （`gg_delist_minutes` 靠下限 10 就拦住了 `true`，不需要这条 —— 但也无妨。）

### K.4 调度改造：tick 循环取代固定睡眠

原实现是「睡死一整个周期再执行」（`while True: sleep(3600)`），周期写死、改一次要改代码重启。
v1.35 改为**每 `_TICK_SECONDS = 30` 秒醒一次、醒来时重算目标**，故配置改动最多 30 秒生效。

**行为边界**（Java 侧必须保住）：

| 情形 | 行为 |
|---|---|
| 首次执行 | 仍在**启动后一整个周期**（Python 侧「启动时立即执行一次」的代码**本就是注释掉的**，不要新增该语义） |
| 周期改**小** | `elapsed` 可能已超新目标 ⇒ **下一 tick 即触发**（用户想要更快，符合预期） |
| 周期改**大** | `elapsed` 保留 ⇒ 按新周期等，**不会因为改大就立刻跑** |
| 正在跑的那一轮 | **不被打断**：本轮跑完才按新周期算下一轮 |
| 出错 | 保留既有语义：**sleep 60 秒重试一次**，再失败才记 `ok=false` |

**每周清理**是**日历语义**（星期几 + 小时），与两个间隔型任务不同：

```
target = 本周的（weekday, hour:00）；若 target <= now ⇒ +7 天
```
等价于原实现 `days_until_sunday or 7`（「今天是周日但 00:00 已过 ⇒ 顺延一周」）。
**不得退化成同一天重复触发，也不得跳过一周。**

> ⚠️ **本版唯一的行为变更（有意为之，勿当回归）**：原 `_start_weekly_cleanup` 里
> `_run_weekly_cleanup_once()` 是**裸调、无 try/except** —— 一旦抛异常，这个 daemon 线程直接死掉，
> **每周清理从此永久失效且无人知晓**（另两个调度循环都有保护，唯独它没有）。
> 本版补上 try/except + `ok=false` 记账：失败不再杀线程，且界面上能看到失败。
> **除此之外清理逻辑一行不动。**

**每次执行都要记账**（成功与失败都记 —— 用户要看的是「上次跑没跑、成没成」，
不是「上次成功是什么时候」）。三个触发接口同样记。

### K.5 两个新接口

```
GET /api/admin/scheduler/config
→ { "success": true, "tasks": [
     {"key":"gg_delist", "name":"掉包检测", "platform":"gg", "kind":"interval",
      "value":60, "min":10, "max":1440, "last_run":{"ts":"...","ok":true}},
     {"key":"tt_delist", ..., "kind":"interval", "value":30, ...},
     {"key":"cleanup", "name":"每周清理", "platform":"gg", "kind":"weekly",
      "weekday":6, "hour":0, "last_run":null} ] }

PUT /api/admin/scheduler/config
body: {"gg_delist_minutes": 120}   或   {"cleanup_weekday": 3, "cleanup_hour": 8}
→ { "success": true, "config": {...更新后的全量...} }
```

**GET 的三条硬约束**：

- **只返回该用户有权管理的任务** —— **必须在后端过滤**，不能只靠前端，否则 F12 就能看到越权任务。
- `last_run` 为 `null` 表示**从未执行**，与「执行失败」（`ok === false`）是**两回事**，前端要能区分。
- ⚠️ **GET 刻意不用 `scheduler_required(platform)`**（只用「developer 或 admin」判定）——
  这样 **FB 管理员拿到 `200 + []` 空列表**（→ 前端渲染空态），而不是 403。
  **空数组 ≠ 无权限**：空态是「本平台没有任务」，403 才是「你没权限」。这条设计意图别读成漏洞。

**PUT 的两条硬约束**：

- **越权字段 → 403，不做「静默忽略」**（TT 管理员传 `gg_delist_minutes` 必须被明确拒绝）。
- 未知字段 → 400（防「字段名拼错却提示保存成功」）；校验失败 → 400 且 error **指明字段与合法区间**。
- 返回**全量配置**（前端直接回填）。

### K.6 前端（`SchedulerView.vue`）

- **由接口 `tasks` 驱动渲染**（不再硬编码三张卡），按 `kind` 分派频率控件：
  `interval` → 数字输入 + 「分钟」；`weekly` → 星期几下拉 + 小时下拉。
  `min`/`max` **取自接口返回值，不得写死**。
- **「保存」按钮仅在有改动时可点**（这本身就是「有未保存改动」的提示）。
- **「上次执行」五态**：今天 / 昨天 / `MM-DD` / 失败（括号内带时刻）/ 从未执行。
  ⚠️ **「尚未执行」与「执行失败」必须分开** —— 合成一句会让用户分不清是没跑过还是跑挂了。
- **FB 管理员空态** + **加载失败的错误态**（两者**不是**一回事：空态是 `tasks.length === 0`，
  错误态是接口失败；错误态要有「重试」入口，别让页面除标题外空白）。
- 视觉上**沿用本页既有卡片语言**（`el-card shadow="never"`、48×48 emoji 块、既有灰阶、
  唯一强调色 `#0891b2` 只用于「运行中」光环）；周期与「上次执行」放在卡片内一条
  **浅分隔线（`1px solid #f3f4f6`）之下**的「调度条」里（左周期右上次执行）。
  **不引入新字体、不换主色、不加装饰性动效**；数字用 `tabular-nums`。

### K.7 迁移红线（逐条）

1. **不要复用 `require_platform`** 做定时任务权限 —— 它会放行户管。
2. **不要用 `@Scheduled(cron=...)`** —— 周期须运行时可配，cron 是启动期固定的。
   用 `@Scheduled(fixedDelay=30s)` 驱动 tick，tick 内重读配置。
3. **`scheduler_config` 与 `scheduler_last_run_{task_key}` 必须分开存**，且后者**一任务一 key**。
4. **读配置永不抛异常**（非法值回落默认）；**写接口越界 400**。10 分钟下限是硬闸，两侧都要校验。
5. **布尔陷阱**：`cleanup_weekday` / `cleanup_hour` 必须显式排除 `bool`。
6. **GET 对 FB 管理员返回空列表而非 403**；**PUT 越权字段 403 而非静默忽略**。
7. **每周清理**：日历语义不得退化为同天重复触发；且**必须补 try/except**（原实现裸调会永久静默失效 —— 这是本版唯一的行为变更）。
8. **`last_run === null`（从未执行）与 `ok === false`（失败）在前端必须可区分**。
9. 三个 `_run_*_once` **本体逻辑一行不改** —— 只改「什么时候调它」。
