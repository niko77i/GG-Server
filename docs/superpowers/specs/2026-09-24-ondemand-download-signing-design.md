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

⇒ 归属必须在**签发侧**堵死。正门那道校验的价值是「挡住直接带 token 的读取」，
不是本次收口的主力 —— 这一点重方案（只加新端点 + 正门）漏了。

**但收窄 `save_dir` 一条并不足够 —— 见 §0.4，那是本次交付的一次返工。**

### 0.2 TTL 取舍

| | 重方案（否决） | 轻方案（实施） |
|---|---|---|
| TTL | 维持 300s，靠「点击时现签」规避过期 | **锚定 JWT 寿命**（默认 86400s） |
| 「URL 被转发」窗口 | 300s | 24h（**比原来放宽了**） |

放宽是有意的：签名 URL 本就是 JWT 在**浏览器原生请求**场景下的替身，不应比它替代的东西活得更久，
但也不该**短得多** —— 前端没有重签路径，300s 会让「面板停留后点下载」必 401（缺口 A 的原始现象）。
恒等于 JWT 寿命是有原则的边界，代价是转发窗口从 5 分钟扩到 24 小时，记为已知风险（§九）。

### 0.3 验收结果（2026-09-24 实测）

> ⚠️ 本节数字是**首次提交（`8f824db`）当时**的，之后因 §0.4 的返工已刷新 ——
> 最新为 **693 passed, 0 failed**（`test_scrape_ownership.py` 由 15 例增至 24 例）。

- 全量套件 **684 passed, 0 failed**（新增 `py/tests/test_scrape_ownership.py` 15 例）
- 变异验证 5/5 全部实测转红后回滚：M1 侧门 `if False` → 2 红；M2 正门 `if False` → 3 红；
  M3 `_is_within` 退化为裸 `startswith` → 2 红；M4 角色集加入 `huguan` → 2 红；M5 `ttl=300` → 1 红
- 既有测试协调：`test_security_hardening.py::TestAClassFileWhitelist` 的两条（`requires_existing_dir`
  / `allows_dir_inside_scrape_root`）改用 `dev_headers` 穿过归属层，断言逐字不变 ——
  该类的职责是钉**白名单层**，归属层由新文件承重

**运行时实测（真实 5001，非 test client）**：修复前一轮 10/10 PASS（正门匿名 401、普通用户读他人
403、前缀陷阱 403、自己的包 200、developer 跨用户 200、侧门 403 且不漏签名、签名闭环 200、
TTL 实测 86399s）；§0.4 返工后又跑了一轮 10/10 PASS。

### 0.4 返工：`save_dir` 收窄被 `pkg_name` 整条绕过（2026-09-24 同日发现并修复）

**这是一次真实的返工，不是补充说明。** 上面 0.1 的论证在 `pkg_name` 这条路径上不成立，
而我是先提交（`8f824db`）、后来经 `/code-review` 才发现 —— 当时的设计文档已把
「归属在签发侧堵死」当作既成事实写下，属于把未验证的推论写成了结论。

**缺陷**：`/api/scrape` 里真正被签名的不是 `save_dir`，而是

```python
pkg_dir = os.path.join(save_dir, pkg_name)      # main.py:544
_scrape_dl = _signed_download_url("/api/scrape/download", pkg_dir)
```

而 `pkg_name` 来自 `extract_package_name(url)`（`utils.py:4`），实现是
`re.search(r"[?&]id=([^&#]+)")` 的捕获组 **原样返回、未经任何清洗** ——
`/`、`\`、`:`、`..` 全部放行。收窄二只看 `save_dir`，于是 pkg_name 成了侧门的正门。

**运行时实证（修复前，真实 5001，由本会话独立复现 5/5）**：

| 请求 | 结果 |
|---|---|
| bob（普通用户）省略 `save_dir`，`?id=../_rv_alice/TravPkg` | **200**，响应含 `download_url`，其 `path=...\_rv_bob\../_rv_alice/TravPkg` |
| 匿名 GET 上面这个签名（不带 token） | **200 / 121 字节** —— alice 的包被完整取走 |
| `?id=D:/.../temp/_rv_abs_escape/AbsPkg` | 在 `_SCRAPE_DEFAULT_DIR` **之外**真的建出了目录（收窄一也一并绕过） |

**修复**（`py/main.py`，纯增量 +24/−0）：在签发之前加两道闸门 ——

1. **字符闸门**：`pkg_name` 不得为空、不得是 `.` / `..`、不得含 `/`、`\`、`:`、NUL ⇒ 400
2. **落地复核**：`_is_within(pkg_dir, save_dir)` ⇒ 400

**修复后实测**（同一探针，真实 5001）：上跳包名 / 反斜杠变体 / 绝对路径 → 全 400，
白名单外不再建目录；对照行（正常包名 200、签名闭环匿名 200、正门 bob 读 alice 403）全部保留。**10/10 PASS**。

#### 关于第 2 道闸门：**订正** —— 它确实承重（2026-09-24 同日推翻了自己的结论）

> ⚠️ 这一节原本写的是「当前没有测试能区分它，保留只为抗未来重构」。**那个结论是错的**，
> 已经改掉，原文与本节的差异刻意保留在此，作为「把推论写成结论」的实例。

当时的推理：变异验证把第 2 行改为 `if False and ...` 后本类 9 条用例**仍全绿**（M7），
于是断定第 1 道字符闸门对「阻止 `os.path.join` 逃逸」已是完备的。**这个推理本身没错**
（Windows 上 `join` 视作绝对路径的三种形态 `C:` / `\` / `/` 都含被拦字符，POSIX 上只有 `/`），
错的是**从它外推到「这层没有用」** —— 我只检查了 `join` 逃逸这一种逃逸方式。

它真正拦的是**字符闸门看不见的逃逸**：`save_dir` 下若有一个指向外部的
**junction / symlink** 目录，则

```bat
mklink /J temp\scraped_images\bob\LinkPkg  <根外目录>   :: 普通用户免提权
```

`pkg_name = "LinkPkg"` 字符全部合法、`join` 也毫无异常，但 `realpath` 之后已在 `save_dir` 之外。
`TestJunctionEscape` 三条用例把这一点坐实：把第 2 行短路掉，**该类的用例真的转红**（M6）。

⇒ 代码注释已同步订正（`main.py` 里那一段），并指明对应用例。

### 0.5 测试污染教训（同日）

`TestPackageNameIsNotATraversalVector` 会**刻意**把有问题的包名喂进端点。闸门正常时全部 400、
什么都不建；但**闸门被拆掉的那一轮（M6 变异验证），分支会走到底并真的建出目录** ——
2026-09-24 实测在真实 `temp/scraped_images/` 里留下了 `_pn_bob/sub/dir`、`_pn_bob/a/b`。

⇒ 该类已加 autouse fixture，进出各扫一次 `_pn_*`。
**测试污染生产数据目录比测试不绿更糟**，负向用例必须自清。

### 0.6 未随本次交付的（明确记录）

- 前端**未做任何改动**，dist 无需为此重建（上一轮的 dist 重建已在裁决 1 中完成）
- video/audio 两条端点的跨用户读**维持现状**（无 `user_id` 列，按设计即全局共享）—— 见 §1.3
- `_find_font_path` 反斜杠穿越仍未处置（独立议题）

### 0.7 第二轮返工：目录名是「用户可控串」（2026-09-24 同日）

> 用户裁定：**「短期止血：锁 display_name + 校验默认路径」**。

§0.4 堵住了 `pkg_name`，但归属的**键**还没审：`_scrape_dn_for` 是
`display_name or username` —— 直接把用户可控字符串当目录名，而归属校验正建立在这个目录名上。
于是「能冒名占住别人的目录」= 不需要任何路径穿越就能拿到别人的产物。

三次递进，每次都是**上一次的收口不够**，而每次都由**对照行**抓出（不是靠推演）：

| 轮 | 攻击 | 为什么上一轮挡不住 | 收口位置 |
|---|---|---|---|
| ① | bob 改 `display_name` = alice 的目录名 → 不传 `save_dir` 爬取 → 200 + 为 alice 的包签发的合法签名 → 匿名 GET 200/121 字节 | `save_dir` 收窄只管显式传参的分支 | `auth._fs_name_error`（字符闸门） |
| ② | 只锁 display_name 之后，用 `username = ..\..\_un_e\pwn`（15 字符，通过「4-20 字符」长度闸门）注册 | **同一条通道有两个入口**（`display_name or username`），锁一个等于没锁 | 字符闸门收口成 `_fs_name_error` **一处**，两个入口共用 |
| ③ | bob 把 `display_name` 设成 alice 的 **username** | 判重只比 `display_name` **这一列**；alice 那列是空的 ⇒ 列上不重名，目录名却相同 | 判重改为比**解析后的目录名**（`_effective_dn`） |

另有一条**不是穿越**的越权：`display_name = "alice."`。
Windows 目录名尾部点会被**静默剥掉**，实测 `realpath(root/"alice.") == realpath(root/"alice")`、
往 `alice./` 写文件真的落进 `alice/`。而字符串判重看不出（`"alice." != "alice"`）、
`_is_within` 也是 True（realpath 归一化后就在根内，**不算逃逸**）——
**「首尾点」这条规则是唯一挡住它的东西**（`test_trailing_dot_display_name_rejected`）。

**最终收口点**（都写在**唯一**关口，不靠各调用点自觉）：

- `auth._fs_name_error` —— 字符闸门，`username` / `display_name` 共用
- `auth.directory_name_error` —— 解析后目录名的**唯一性** + **目录占用**；
  挂在 `create_user` / `update_user` 两个唯一写入关口
- `main._scrape_dn_for` —— 对 `own` 的越界兜底（原来只校验管理员的 `requested_dn`，漏了 `own`）。
  这一处的价值在于 `_scrape_dir_for` 有**三个**调用点：写入、下载、列表。
  只在写入侧补一道，另两处仍靠自觉；而 `scrape_packages` 会直接 `listdir` 推导出的目录
  —— 越界即**信息泄露**
- 四处置信路由前置 `directory_name_error` —— 只为给出清楚的错误文案，真正的约束在上面两处

**为什么不需要第二道冗余闸门**：`/api/scrape` 的「省略 `save_dir` 时也校验推导结果」
（`/code-review` finding #3 的落点建议）**没有采用** —— 该路径由 `_scrape_dn_for` 推导，
在那里收口即可覆盖全部三个调用点。加第二道冗余闸门会让两道互相掩盖，
变异验证时谁也测不出，反而降低可信度。

**一处我自己写坏、被对照行抓出的回归**：`display_name_error` 里空值落进了「目录占用」判据
—— `join(root, "") == root`，而爬取根目录**必然非空**（真实环境有 `ai`/`alice`/`alice2`），
于是空 `display_name` 被判成「该目录里已有数据」，**把不带显示名的注册整体打死**。
空值是合法输入（语义 = 回退到 username），必须短路。

**验收**：全量 `717 passed / 0 failed`（改前 693）；
变异验证 **6/6 承重** —— M1 字符闸门（username 入口）、M2 首尾点、M3 判重退回比列、
M4 目录占用、M5 `_scrape_dn_for` 的 `own` 兜底、M6 第 2 道闸门（junction），
每条都把对应用例实测转红。

**已知行为变更**（修复的副作用，需运维知悉）：

1. `username` 新增字符校验 —— 含 `/ \ : NUL`、首尾点/空白的用户名会被拒
2. **目录已被占用的名字会被拒**：用户被删但 `temp/scraped_images/<名字>/` 还在时，
   用同名重建账号会被拦（需先清目录或改名）。这是**刻意**的 —— 那正是「无主目录冒名接管」
3. `display_name` 判重改为比解析后的目录名 ⇒ 设成他人 `username` 也会被拒

---

#### `/code-review` 的遗留发现（用户 2026-09-24 裁定「本轮不做」）

只修了 HIGH 那条（§0.4）。以下 6 条已报告，**均不在本文件的原始范围内**，留待另行裁定。其中第 2 条已被 §0.4 修复、第 7 条已被 §0.8 修复（表内已标注），其余维持「本轮不做」：

| # | 级别 | 问题 |
|---|---|---|
| 2 | MEDIUM | `test_scrape_download_rejects_path_outside_scrape_dir` 的 `in (403, 404)` 曾被归属层的 403 满足 ⇒ 白名单层失去保护。**已在本轮修复**（改 `dev_headers` + 收紧为 `== 404`） |
| 3 | MEDIUM | `/api/video/download`、`/api/audio-replace/download` 仍无归属校验。审查者指出本文件「全局共享产物库」的前提与产物实际落点（`scraped_images/<dn>/<pkg>/ai/*.mp4`）不符，实测 bob 能下 alice 的视频 ⇒ **§1.3 的非目标理由需要重新评估** |
| 4 | LOW | TTL 统一 24h，而服务端请求日志会落盘含 `sig` 的完整 query ⇒ 叠加第 3 条等于「日志泄漏 → 24h 匿名能力」 |
| 5 | LOW | `_scrape_dn_for` 的 `requested_dn` 校验漏 Windows 盘符相对名：`user_dn=C:` 也通过，`_scrape_dir_for` 返回 `"C:"`（实测 `isdir` 为真），developer/admin 可列出 `_SCRAPE_DEFAULT_DIR` 之外的目录 |
| 6 | LOW | `int(app.config.get("JWT_ACCESS_TOKEN_EXPIRES", 86400))` 与该键的 int/秒形态强耦合：键缺失时回退值不等于 JWT-Extended 的真实缺省（15min），「锚定 JWT 寿命」落空；若被设为 `timedelta` 则抛 TypeError ⇒ 全部下载 URL 下发 500 |
| 7 | LOW | `scrape_upload_images` 仍手抄 dn 推导，与 §0「dn 推导唯一来源」的承诺不符（当前靠巧合一致，改一处即「写得到、下不了」）。**已在 §0.8 修复**（改用 `_scrape_dn_for`，同时补上了越界兜底） |

---

### 0.8 第三轮返工：H1 大小写折叠 + H2 并发窗口 + 3 个上传端点（2026-09-24 同日）

> 用户裁定：H1+H2 修法 = **「H1 归一变比较 + H2 加 DB 唯一约束」**；
> 3 个同族越界端点 = **「本轮一并修」**。

§0.7 收口后仍留了两条 HIGH，由**两位独立审查者**分别从不同入口发现并互相印证 ——
这符合本项目对「判据独立」的要求（同一判据的两种实现不算交叉验证）：

| # | 级别 | 缺陷 | 谁发现 | 为什么 §0.7 的收口没盖住 |
|---|---|---|---|---|
| H1 | HIGH | 判重比的是**字符串**，而 NTFS 上 `alice` 与 `ALICE` 是**同一个目录** | 安全审查者（字符串比较 vs realpath 比较）＋ 代码质量审查者（判据 2 与判据 3 标准不一致） | `os.path.realpath` 只在目标**已存在**时才把大小写折到磁盘真值 —— 「目录不存在」这一档因此漏检 |
| H2 | HIGH | 开放注册的 check-then-act 在并发下能插出多个**同名目录**的用户 | 代码质量审查者 | `directory_name_error` 是「读快照 → 判断 → INSERT」，Python 里天生非原子 |

#### H1 的运行时取证（我自己独立复验，不走审查者的 Flask 客户端路径）

- **文件系统事实层**：`os.path.samefile(root/"ALICE", root/"alice") == True`；
  透过大写路径**读到**了 alice 的 `secret.png`；写入也落进 alice 目录
- **闸门层**：把窗口边界钉成三档实测 —— 目录**不存在** → 放行（漏检）、
  目录**为空** → 放行（漏检）、目录**非空** → 拦下

「目录不存在」档不是边角情况：`_run_weekly_cleanup_once` 会 rmtree **整个**爬取根
再重建，那一瞬间**全库**都落进这一档 —— **窗口每周重开一次**。这也是把「空目录」
一并拒掉的理由：否则可以先占名、等对方产出再共享。

#### 修法

| 处 | 改动 |
|---|---|
| `auth._dn_key` | `os.path.normcase` 归一 —— POSIX 恒等，Windows 折大小写 |
| `auth.directory_name_error` 判据 2 | 从「比字符串」改为比 `_dn_key(_dir_name_of(...))`，**含 `user_<id>` 兜底**，排除自己当前的两种写法 |
| `auth.directory_name_error` 判据 3 | 目录占用同样按 `_dn_key` 归一再比，并排除自己拥有的目录 |
| `database.py` | 新增 `users.scrape_dn` **生成列** + `CREATE UNIQUE INDEX ... ON users(scrape_dn COLLATE NOCASE)` |
| `auth.create_user` / `update_user` | `sqlite3.IntegrityError` → `return None`（并发撞索引时给干净的「名字重复」而不是 500） |
| `auth.create_user` | `display_name.strip()`，与 `update_user` 对齐 |
| `auth.init_developer` | 两次创建分别判定，**两次都失败时打印明确告警** —— 原实现无条件 print `"created"`，会把「系统已经不可登录」报成成功 |

**为什么 H2 必须落到 DB**：应用层的「读快照 → 判断 → INSERT」在多线程/多进程下
无法原子（加锁只护得住单进程，而这是常开的多线程服务）。原子性只能交给 DB。
`COLLATE NOCASE` 只折 ASCII，比 Python 的 `normcase` **窄** ⇒ 应用层更严 =
fail-closed（两者不一致时先被应用层拒掉），方向是安全的。

#### ⚠️ 订正：H2 的「应用层更严 = fail-closed」只覆盖大小写一维

§0.8 正文写了「`COLLATE NOCASE` 比 `normcase` 窄 ⇒ 应用层更严 = fail-closed」。
复核时发现这句话**只在一维上成立**，另有一处反向的不一致：

| | `display_name` = `"   "`（纯空白**非空串**）时的解析 |
|---|---|
| Python `_scrape_dn_for` | `(display_name or username or "").strip()` —— `"   "` 是 **truthy**，故不回退 username；strip 后成空串 ⇒ `user_<id>` |
| DB `scrape_dn` 生成列 | `NULLIF(TRIM(display_name),'')` ⇒ TRIM 后为空 ⇒ **回退 username** |

即 Python 是「先判 falsy 再 strip」，DB 是「先 TRIM 再判空」，**求值顺序不同**。
这一档下应用层闸门与 DB 唯一索引判的**不是同一个键** —— 而 H2 的原子性正是交给
那个索引的。

**方向仍是 fail-closed**：攻击者取 `display_name` = 某人的 `username` 时，应用层
**放行**（它以为那个人的目录是 `user_<id>`），但 DB 生成列会撞上 ⇒ `IntegrityError`
⇒ 拒绝。**只会误拒，不会漏越权**。

**当前不可触发**：`create_user` / `update_user` 都已 strip，新数据产生不了 `"   "`；
真实 `temp/app.db` 逐行核对（**2026-09-24 快照：24 行**）—— **0 不一致**，也无「TRIM 后为空但原值非空」的行。（此处原写「33 行」：该数字随库变化而失准，故改为带日期的快照表述。）

**未修**：统一求值顺序要改 Python 侧的目录名语义（`"   "` 的用户目录会从
`user_<id>` 变成 username），有产物「搬家」风险，且属改既有功能逻辑，需裁定。
已由 `TestDbGeneratedColumnMatchesPython` 的两条用例**如实记录**（一条钉「除该档外
必须同键」，一条钉「该档的差异仍然存在」）—— 差异消失时后一条会转红，提示删除注释。


**为什么 `scrape_dn` 用 `PRAGMA table_xinfo` 判存在性而不是复用
`_add_column_if_missing`**：该 helper 查的是 `PRAGMA table_info`，而该 PRAGMA
**不列出生成列**（生成列在 `table_xinfo` 里）—— 于是它每次都判「列不存在」→ 重复
ALTER → `duplicate column name: scrape_dn`，而 `_ensure_columns` **每次连库都跑**
⇒ 整个应用当场打死（实测：全量套件从 `717 passed` 掉到 `304 failed`）。
遵守纯增量原则，把生成列判存在性的局限关在新代码块内，不动共享 helper。

#### 3 个上传端点的路径穿越（用户批准本轮一并修）

`FileStorage.filename` 原样携带客户端字符串，3 处直接 join 进路径。加固前用
Flask test client **运行时实测**的基线（3/3 确认）：

| 端点 | 基线 | 修复后 |
|---|---|---|
| `/api/fonts/upload` | 200，落盘 `temp/_travprobe/x.ttf`（`fonts/` 之外） | 拦住，且中文名对照行仍正常落盘 |
| `/api/video/upload-music` | 200，落盘 `temp/_travprobe/x.mp3`（`music/` 之外） | 拦住 |
| `/api/audio-replace` | ffmpeg argv 的输出路径归一化后为 `temp/_travprobe/x_new.mp4` | 留在 `temp/audio_replace/` 内 |

`audio-replace` 的影响面比另两个大：该路径不只进 ffmpeg 的 argv，还进
`audio_replace_history` 表与**签名下载 URL**。

统一收口在新增的 `main._safe_upload_name`。**刻意不用 werkzeug 的
`secure_filename`**：它会把中文名整段滤掉（`背景音乐.mp3` → `mp3`），砸掉本项目的
正常上传 —— 那是把可用功能改坏。故只做「剥目录成分」一件事，字符白名单仍交给各
端点既有的扩展名校验。三个端点各配**中文名对照行**，专门防这个误修。

#### 其余随本轮一并修

- `admin_update_user` 的 `display_name` 补 `.strip()`，与建号路径对齐。不 strip 会让
  **同一输入在两条写路径上判定相反**：建号 `"张三 "` 归一出 `"张三"` 成功，改名
  `"张三 "` 则被 `_fs_name_error` 的「首尾不能有空白」拒成 400
- `scrape_upload_images` 改用 `_scrape_dn_for`（原为手抄 dn 推导，缺越界兜底）
  —— 即 §0.7 遗留清单的第 7 条

#### 测试

- `test_scrape_ownership.py` 新增 3 个类：
  - `TestEffectiveDnMatchesScrapeDnFor` —— 钉住 `auth._effective_dn` ≡
    `main._scrape_dn_for`。⚠️ `_effective_dn` 与 `database.py` 的两处注释此前都声称
    「由该类钉住」，而**该类当时并不存在**（code-review 第 3 轮指出：注释在撒谎）。
    断言分两支写：非空时逐字相同，为空时 `_scrape_dn_for` 必须落进 `user_<id>` 兜底
  - `TestDirectoryNameCaseInsensitiveCollision` —— H1 的三档窗口各一条 + 对照行
    （只改**自己**名字的大小写必须放行）
  - `TestConcurrentDuplicateDirectoryName` —— 8 线程并发注册同名，**分档计数**：
    断言 `1 created / 7 rejected / 0 error`。宽捕获刻意留着 —— 只 catch
    `IntegrityError` 的话，其它异常会让线程静默死掉、计数对不上，测试反而可能变绿
  - `TestDbGeneratedColumnMatchesPython` —— 钉住 **DB 生成列**与 Python 解析
    **同键**（`test_same_key` 5 档参数化）+ **已知差异**一条（见上面的订正）。
    ⚠️ 此前 `database.py` 的注释声称一致性「由 `TestEffectiveDnMatchesScrapeDnFor`
    钉住」，而那个类只比 Python 两个函数之间、**没碰 DB 生成列** —— 该注释
    已一并订正（注释不得撒谎是本项目 code-review 的固定检查项）
- `test_huguan_dashboard.py` 的两条用例**前提已被 DB 唯一约束消掉**（它们靠
  `_seed` 造两个同名 `display_name` 的用户来测 `resolve_owner_id` 的「≥2 → None」）。
  改写为断言「歧义已不可能构造」+ 唯一命中仍必须命中的对照行。
  「≥2 → None」的契约**未丢覆盖** —— 仍由 `test_ambiguous_mcc_name_is_warning`
  实测覆盖（那条确实往 `mcc` 表插了两行同名）
- 新增 `test_upload_filename_traversal.py` —— 3 端点各一条越界 + 一条对照行，
  外加 `_safe_upload_name` 自身的边界（`.` / `..` / 空 / 纯目录 → `""`）。
  穿越用例内置**非空转守卫**：`os.path.relpath` 若不含 `..` 就直接失败，
  防「目标目录就在自己内部」的用例静默变绿

#### 验收

- **全量 `779 passed / 0 failed`**（本轮改动前 746）
  - `test_scrape_ownership.py` 68 passed（新增 4 个类 27 条）
  - `test_huguan_dashboard.py` 145 passed
  - `test_upload_filename_traversal.py` 7 passed（新文件）
  - H2 并发用例连续 **5 次**运行稳定（迁移竞态已隔离，见下）
- 3 个上传端点：修复前基线 3/3 越界 → 修复后 3/3 拦住，中文名对照行全过

#### 已知行为变更（运维知悉）

1. **`display_name` 现在是全局唯一**（不区分大小写，且含 `user_<id>` 兜底命名空间）。
   若存量库已存在重名，建索引会被**跳过**（防御式：否则唯一索引创建失败会让**每次
   连库**都抛异常、把应用打死）。此时需人工改名后再重启，索引才会建立
2. 带**首尾空白**的 `display_name` 在**改名**路径上由 400 变为自动 strip 后成功
   （建号路径本来就是 strip 后成功，此前两条路径口径相反）
3. `admin_update_user` 与 `auth.create_user` 在并发撞名时返回 400「用户名重复或
   更新失败」，而不是 500
4. 上传文件名中的目录成分被剥掉：`a/b.png` → `b.png`（此前会写到 `a/` 子目录）

#### 本轮**未**处理的（明确记录）

- §0.7 遗留清单里除第 7 条外的其余低危项（#3/#4/#5/#6）维持「用户已裁定本轮不做」
- `_fs_name_error` 仍只防 `/` 不防 `\` 的**其他**出口（`_find_font_path` 那条独立议题，
  见 memory 记录）

#### ⚠️ 另一个已知限制（本轮实测发现，未修）

判据 2 只比**他人当前的目录名**，而判据 3 的 `own_keys` 却把自己**两种**写法都排除了
（当前目录名 + username 派生目录名）—— 两处**不对称**。缺的那一块是：
**他人 `username` 派生的名字没被预留**，而它在对方清空 `display_name` 时会变成对方的目录名。

实测（`temp/_probe_username_namespace.py`）：

```
B 取 A 的 username 作 display_name  → 200 放行
随后 A 清空 display_name            → 400「该名字会与其他用户的爬取目录重名，请换一个」
```

即 **B 可以抢注 A 的 username，从而永久锁死 A 清空 `display_name` 的能力**
（A 只能改成别的名字）。而错误文案是误导性的 —— A 看到的「甲名」与「sym_a」
两个名字毫不相干，它无从知道问题出在自己**未改**的 username 上。

**不是越权**：A、B 不会共用目录（B 占了 `sym_a`，A 清空时被应用层判据 2 拦下，
DB 根本没参与）。安全方向 fail-closed，属**可用性 + 文案**问题。

**修法方向（未做，待裁定）**：让判据 2 也把「他人 username 派生的名字」纳入预留，
与 `own_keys` 的处理对称。代价是**变严**：任何人的 `username` 都不再能被别人取作
`display_name`。这**是**正确行为（那个名字迟早会变成对方的目录名），但属改既有
功能逻辑 + 会拒掉当前能通过的名字，按本项目规则需先裁定。

**未固化为测试**：本条记录的是一个**待裁定**的行为，把它写成断言等于单方面把现状
钉成期望行为。故只留探针脚本作证据，不写进 `tests/`。


#### ⚠️ 本轮**新发现**的独立缺陷（先于本轮存在，待裁定，未修）

并发场景下 `database.get_db()` 的迁移逻辑存在**非原子 check-then-act**。实测
（`temp/_probe_migration_race.py`，**3/3 轮全部复现**）：8 线程同时首次连库时
**6–7 个线程失败**：

```
duplicate column name: channel_name / sales_person   ← _ensure_columns 的无锁 ALTER
no such column: "level" / "status"                   ← _cleanup_old_option_columns 的 DROP 竞态
database is locked                                    ← 写锁竞争（被前两者放大）
```

**根因已定位（在文件内就能对照）**：

- `_ensure_schema`（`get_db()` 第 45-50 行）**有** `_schema_lock` 双检锁 —— 模式是
  现成的、正确的
- `_ensure_columns`（第 53 行）**每次连库都跑**，其中的 `_add_column_if_missing`
  是「`PRAGMA table_info` 查列 → `ALTER TABLE ADD COLUMN`」，**无锁**
- 更麻烦的是 `_ensure_columns` 与 `_cleanup_old_option_columns` **互相增删同一列**：
  后者会把 `products.sales_person` **DROP** 掉（标记置 1 后不再删），前者下次连库
  又把它加回来 ⇒ 新库上的序列是「加 → 删 → 再加回」
- **实测真实 `temp/app.db`**：`products.sales_person` **存在**（cleanup 标记已是 `'1'`
  却仍被加回），`accounts.agent`/`accounts.status`/`mcc.level` 已删 —— 所以**稳态下
  不触发**，生产当前是**潜在**而非**live**

**触发窗口**：「全新库首次多人同时访问」或「升级带新列后的第一次启动 + 并发请求」。
稳态下（列都已存在）只做 PRAGMA 读、不 ALTER，故平时不炸；但每次全新部署都可能让
一部分请求拿到 500。**不是目录名归属问题**，与 H2 只是同族（都是非原子的读-判-写）。

**后果（本轮实测踩到）**：新加的 H2 并发用例被它污染成 flaky —— 第一次跑红
（7 个线程 `duplicate column name: sales_person`）。已把该用例的预热改为
**预热到稳态并显式断言该前提**（`products.sales_person` 必须已在），把迁移竞态
隔离出去；连续 5 次运行 68 passed 稳定。**隔离 ≠ 掩盖** —— 前提一旦失效，用例会
直接报出来。

<details>
<summary>为什么「只多调一次 get_db()」不够（踩过的坑）</summary>

第一次的缓解是「主线程连一次库再放线程」。这**反而更糟**：单次调用恰好停在
「`sales_person` 刚被 cleanup DROP、标记已置」那一档，于是 8 个线程**同时**去
ALTER ADD 这个已不存在的列 —— 必然 7 个失败。正确做法是**两次**：第二次连库时
cleanup 已置标记不再删，列被加回并留下 ⇒ 后续连接只读不 ALTER。
</details>

**未修**：位于 DB 迁移层、与目录名归属无关，**链条已漂离本轮需求**，故不在本轮
擅自修复 —— 待用户裁定。（修法方向明确且与文件内既有模式一致：把 `_ensure_columns`
也用 `_schema_lock` 护住；但那要单独设计「加/删互斗」那部分，不是加个锁就完。）

### 0.9 第四轮：code-review 第 3 轮的逐条处置（2026-09-24 同日）

审查对象是本轮加固**本身**（H1/H2/3 个上传端点）。下列每条都**先独立复现、再决定**
—— 审查员是模型，其结论本身不构成证据。

#### 已修（4 条）

| # | 缺陷 | 复现方式 | 修法 |
|---|---|---|---|
| HIGH-1 | `database.py` 的重复检测用 **BINARY**、唯一索引用 **NOCASE**，且建索引无 `try/except` | **运行时复现**：库里存在 `alice` / `Alice` 两条 `scrape_dn` 时，BINARY 检测得 `0`（以为无重复）→ `CREATE UNIQUE INDEX ... COLLATE NOCASE` 抛 `IntegrityError: UNIQUE constraint failed: users.scrape_dn`。该异常从 `get_db()` 冒出，而 `get_db()` 在 `_before_request` **每个请求都调**、启动预初始化也调 ⇒ **服务起不来 / 每个请求 500** | ① 检测改 `GROUP BY scrape_dn COLLATE NOCASE`，与索引同 collation；② 建索引包 `try/except sqlite3.IntegrityError` 兜底；③ 跳过分支改为 `print("[Migrate] ...")` 显式告警（不再静默丢弃原子性保障） |
| MEDIUM-2 | `/api/admin/users/create` 本轮新加的目录名闸门排在**既有**的 409「用户名已存在」之前 ⇒ 重名用户名被顶成 400 | `git diff` 确认该闸门是本轮新增行，且 409 分支原在其后 | 把 `existing = auth.get_user_by_username(username)` + 409 **上提**到闸门之前，恢复原对外契约 |
| L-6 | **纯增量违规**：上一轮在 `auth.update_user` 里删掉了既有的 `username = username.strip()`（`git diff` 的 `-` 行），且其原位置在闸门**之后** ⇒ 同一输入建号得 200、改名得 400 | `git diff -- py/auth.py` | 还原该 strip 并**上提**到目录名关口之前（同时消除建号/改名口径相反） |
| L-4 | `/api/audio-replace` 里 `_safe_upload_name` 返回空时未按错误处理 ⇒ `base_name` 为空、输出静默变成 `_new.mp4`，两人同用非法名会互相覆盖；同族另两个端点都是「空 → 400」 | 读代码 + 与另两端点对照 | 在建临时文件**之前**加空名 400（免得 400 时留垃圾） |

#### 测试质量（2 条，已修）

- **L-1 —— 本轮唯一真正的假绿点**：`test_sequential_duplicate_is_rejected_by_gate`
  只断言 `create_user(...) is None`。闸门**整个坏掉**时返回值一模一样（闸门放行 →
  INSERT 撞唯一索引 → `IntegrityError` 被 `create_user` 吞 → 同样 `None`），两条路径
  无从区分，而 docstring 却声称在测 gate。已补一腿直接问闸门要**判据 2 的原文案**
  —— DB 唯一索引给不出这句话，故这条断言能真正区分。
- **L-2**：`test_huguan_dashboard.py` 的对照行 `resolve_owner_id(db, "重名") is not None`
  太弱（换个用户命中也能蒙过），改为 `== uid_a` 钉到**具体那一行**；函数名同步改为
  `test_ambiguous_name_is_unconstructable_and_unique_still_resolves`（原名与断言语义已不符）。

#### 明确不改（3 条，附理由）

- **L-3**（`video_ext` / `audio_ext` 取自未过筛的原始文件名）：**探针未能复现 500** ——
  `.mp4:evil` 这类含 `:` 的后缀在 Windows 上被当作 NTFS **备用数据流**，写入**成功**，
  既不抛 `OSError` 也不越界；审查员自己也标了「未实测出 500」。按诊断优先原则，
  无实测证据不动手。
- **MEDIUM-3**（并发用例的 `except Exception` 过宽）：**不采纳「收窄 + 重试」**。该宽捕获
  **不是掩盖** —— 它把异常记进 `outcomes["error"]`（含 `type(e).__name__`）并断言
  `== []`，命中即报红。若收窄成只 catch `sqlite3.IntegrityError`，用例反而会在
  **迁移竞态**（见上、**尚未裁定**的独立缺陷）命中时直接崩，把本用例与那个待裁定
  缺陷耦合起来。
  另：审查员称「§0.8 验收数字『62 passed』与现状 68 不符」—— 实测全文**没有**
  「62 passed」，§0.8 一直写的是 **68**，此条**不成立**（审查员读的是旧副本）。
- **L-5**（`ALTER TABLE ... GENERATED ... VIRTUAL` 硬依赖 SQLite ≥ 3.31，
  `requirements.txt` 未记该下限）：属依赖声明问题，且部署机版本未确证，单独处理。

#### 待用户裁定（2 条行为问题，本轮**未**改）

- **MEDIUM-1 · 改回曾用显示名会被自己的旧目录拦住**：用户显示名曾为 `老王`（目录
  `temp/scraped_images/老王/` 内已有产物），改名 `老李` 后想改回 `老王` → 判据 3 命中
  **自己的旧目录** → 400。`own_keys` 只放**当前**目录名与 username 派生名，不含曾用名
  ⇒ 用户**自己此前的产物永远访问不到，且 UI/admin 都没有恢复路径**。
  修法（把历史目录名纳入 `own_keys`，或对「目录内文件全属本人」放行）会**放宽**判定
  = 改既有功能逻辑，按本项目规则需先裁定。
  **独立复现（我自己跑的，非转述审查员）**：`py/tests/_probe_hist_dn.py`（跑完即留档、
  不被默认收集）。两腿证据 ——
  ```
  [3b] 对照：目录「老李」存在时把显示名**再设一次 老李** -> 200   ← 判据 3 非无差别拒绝
  [4]  改回曾用名「老王」（自己的旧目录）              -> 400
       {'error': '该显示名对应的爬取目录已被占用，请换一个'}
  ```
- **L-7（潜伏）**：闸门新增**之前**入库的非法名用户（含 `/:\`、首尾点、首尾空白）会被
  自己的旧值卡死 —— `directory_name_error` 对自己旧名也不放行、`update_user` 同样拦，
  **没有任何端点能修正**。live 库实测 **0 行**（24 用户），故仅潜伏。修法方向：对自己
  当前旧值豁免，或给 admin 一条修正通道。

### 0.10 第五轮：MEDIUM-1 / L-7 的裁定与修复（2026-09-24 同日）

§0.9 里挂起的 2 条行为问题，用户裁定**一并修**，且 MEDIUM-1 的修法方向由用户在
「记录曾用目录名」与「改名时迁移目录」之间选定 —— 选前者。

#### MEDIUM-1 · 曾用显示名被自己的旧目录锁死（已修）

**为什么选「记录曾用名」而不是「改名时 `os.rename` 迁移目录」**：前者**不动文件系统**
（无耗时 / Windows 文件锁 / 请求内文件操作失败语义 / 并发风险），语义也最小 ——
只放宽「我的」名字空间。「迁移目录」虽然语义更强（产物随用户走），但要在 DB 事务里
做文件操作，属高风险改动，需先写设计文档，本轮不做。

| 项 | 内容 |
|---|---|
| 数据结构 | `users.prev_scrape_dns TEXT DEFAULT ''`，JSON 数组文本，记录**曾用爬取目录名** |
| 迁移 | `_add_column_if_missing`（**普通列**用 `table_info` 即可；只有**生成列** `scrape_dn` 才必须用 `table_xinfo` —— 两者不可混用） |
| 写入 | `auth.update_user` 在目录名**发生变化**时追加旧名字，语句与改名**同一事务**（在 `commit()` 之前） |
| 读取 | `auth._dn_history`（坏值一律当空 = fail-closed：读不出来只是自己的曾用名不被认领，不会把别人的名字误判成自己的）；`_dn_history_append`（按 `_dn_key` 归一判重，无需追加时**原样返回** raw，便于调用方靠 `==` 判断「无变化」从而不产生空 UPDATE） |
| 生效点 | `directory_name_error` 的 `own_keys` 纳入曾用名 ⇒ 判据 3 不再拦「改回自己的旧目录」 |

**为什么用 JSON 而不是逗号/换行分隔**：`_fs_name_error` 只挡路径分隔符、冒号、空字符
与首尾的点/空白 —— **名字中间允许逗号和换行**，分隔符拼接会在这里串味（`a,b` 这一个
名字会被拆成两个）。

**为什么刻意*不*把曾用名加进判据 2**：那会让任何名字一旦被谁用过就**全局永久保留**
（`prev_scrape_dns` 只增不减），而「空目录被别人抢走」**没有数据可失** ——
产物存在 ⇔ 目录存在，真正的数据保护来自判据 3「目录是否存在」。故这个不对称是
**刻意的取舍**，不是遗漏（代码注释里同样写明了理由）。

#### ⚠️ 收窄：曾用名豁免**自己引入的越权**，已修（同日，先红后绿）

上面那版豁免（「凡是我的曾用名都算我的」）**过宽，自己开了一个跨用户读取的口子**。
由我在写完后推演发现，**先写成用例跑红确证**（不是靠推理下结论）：

```
A: display_name = _lk_X（目录还不存在）→ 改名 _lk_Y 离开      # A 的曾用名里有 _lk_X
B: display_name = _lk_X（判据 3 无目录可撞，放行）→ 在其下爬出产物 → 改名 _lk_Z 离开
   ⇒ 目录 _lk_X 连**B 的产物**一起留在磁盘上
A: display_name = _lk_X
   修复前实测 → 200   ← A 仅凭「我曾用过」就认领成功，读到的是 B 的产物
```

即：**只要一个名字被两个人先后用过，先走的那个人就能回来拿走后者留下的产物** ——
判据 3 的「目录占用」保护被整条绕开，正是本轮要防的那类越权。

**修法**：豁免收窄为「**除我之外没有任何人用过**这个名字」—— 此时目录里只可能有我的
产物。「用过」**必须含曾用名**（别人改名离开后，他的产物仍留在那个目录里）。
别人用过的名字一律退回**修复前**的行为（拒），fail-closed。

实现上把 `own_keys`（当前目录名 + username 派生名，**无条件**豁免，维持原语义）与
`hist_keys`（曾用名，**有条件**豁免）分开；`hist_keys = 我的曾用名 − 所有人的「用过」集合`。

**已知残留（明确记录，接受）**：若用过该名字的那个人**已被删除**，其行不再存在，
「别人用过」集合里就没有他 ⇒ 本人可凭曾用名认领到一个可能装着**已删除用户**产物的目录。
窗口有界：`_cleanup` 每周把整个爬取根 rmtree 重建，孤儿目录至多存活一周；且需要
「两个人先后用过同一名字 + 其中一人被删」两个条件同时成立。按上述「产物存在 ⇔ 目录存在」
的取舍一并接受，不为它加严。

**修完仍未覆盖的一档（明确记录）**：若某个曾用名**从未** materialize 成目录（那个名字
下从没爬过），判据 3 无目录可撞 ⇒ 别人可以取走这个名字，此时本人回不去。**无数据可失**
（该目录下本来就没有他的产物），故按上述理由**接受**，不为它加严。

#### L-7 · 存量非法名用户被自己的旧值锁死（已修）

**修法**：对「与库里现值**完全相同**」的字段跳过**字符**判据（`_keep_u` / `_keep_d`）。
该值此刻**已经在生效**，重验一遍挡不住任何事，只会把用户锁死；而 profile 端点根本
不允许改 username ⇒ 原本**没有任何修正通道**。安全性由 `main._scrape_dn_for` 的结构
兜底接住（推导结果越界即退化为 `user_<uid>`，见 py/main.py:477-478），不靠这里。

**只豁免字符判据** —— 判据 2/3 比的是「别人与磁盘」，与旧值本身是否合法无关，照旧执行。

#### 测试

新增 5 条（`test_scrape_ownership.py` 68 → **73**），并把上一轮的探针
`py/tests/_probe_hist_dn.py` **收编为正式用例后删除** —— 那个探针断言的是**缺陷形态**
（400），修复后必红，留着就是在撒谎。
（第 5 轮审查后又补 3 条 → **76**，见下节。）

| 用例 | 作用 |
|---|---|
| `TestFormerDirectoryNameIsReclaimable::test_rename_back_to_own_former_name_succeeds` | 三腿：设定曾用名 + 造产物 → 改名（旧目录**刻意不删**，这才是缺陷场景）→ 改回，断言 200；再核对 `prev_scrape_dns` 里确实有旧名字（证明靠的是**曾用名**，不是判据 3 整体失效） |
| `…::test_same_former_name_is_still_blocked_for_others` | **对照行**：另一个用户取同一名字仍 400，且要**判据 3 的原文案**（只断言 400 的话，判据 2 或字符闸门误伤也能蒙过） |
| `…::test_former_name_that_someone_else_also_used_is_not_reclaimable` | **收窄的对照行**（见上节）：先红后绿，钉住「别人也用过的名字不能凭曾用名认领」 |
| `TestLegacyIllegalNameIsNotSelfLocked::test_unchanged_illegal_value_no_longer_freezes_update` | 含前置断言「夹具确实造出了闸门判非法的值」—— 否则本用例可能在**测空气** |
| `…::test_changing_to_another_illegal_value_is_still_rejected` | **对照行**：改成另一个非法 username 仍拒（闸门函数 + 整体写路径两条腿）、新建路径无旧值可豁免故仍拒 |

**变异验证（三证，跑完均已还原，`grep -c MUTATION` = 0）**：

| 变异 | 结果 |
|---|---|
| 拆掉 `hist_keys` 的曾用名认领 | **恰好 1 红**：`test_rename_back_to_own_former_name_succeeds`（400 + 判据 3 原文案）；**其余 4 条全绿** |
| 拆掉 L-7 的 `_keep_u` / `_keep_d`（恒 `False`） | **恰好 1 红**：`test_unchanged_illegal_value_no_longer_freezes_update`（400 + 字符闸门文案）；**其余 4 条全绿** |
| 拆掉「别人用过」收窄（`hist_keys` 直接吃下全部曾用名） | **恰好 1 红**：`test_former_name_that_someone_else_also_used_is_not_reclaimable`；**其余 4 条全绿** |

#### 第 5 轮审查（code-review）的处置

审查者另跑了一组只读探针。三条 Important **我逐条独立复现后全部成立**
（自己的探针 `temp/_probe_r5_verify.py`，临时 DB + 临时爬取根，不复用它的判据）：

| 编号 | 结论 | 处置 |
|---|---|---|
| #3 | 本文件与 `auth.py` 里「安全性由 `_scrape_dn_for` 结构兜底接住」是**错的**：兜底只挡「越出爬取根」，而 `nest_user/pkg`、`alice/pkg` 这类**留在根内**的嵌套分隔符值**不退化**（实测目录名原样就是 `nest_user/pkg`）。后果不是读根外，而是往真实用户目录里凭空多出子目录，被当成**她自己的包**列出 | **已修（注释订正）**：改为事实表述，并写明接受本豁免只剩「只可能来自存量、live 实测 0 行」这一条依据；存量治理列入「仍未做」 |
| #6 | 读**别人**的 `prev_scrape_dns` 时「坏值当空」是 **fail-open**（漏看他用过的名字 ⇒ 可能认领到装着他产物的目录），与读**我自己**历史时方向相反 | **已修**：他人历史「非空但解析失败」⇒ 整体放弃认领（保守当满），退回修复前的「拒」。该分支不依赖「不可达」假设 |
| #1 | 收窄比「目录数据是否干净」**更保守** —— 名字被 ≥2 人先后用过时，**最后持有者**也被拒（复现：目录里只有他自己的产物） | **未改，待裁定**（需改存储格式记「谁最后释放该名」，属目标行为） |
| #2 | `others` 只能看到**还存在的**行 ⇒ 用户被删后其目录名连同历史一起消失，任何曾用名含该名的人都能认领并读到**被删用户**的产物。**这正是判据 3 声称要挡的「无主目录」那一档**，且是本轮改动**新引入**的读取路径 | **未改，待裁定**（收口点只有「删用户时同步处理其爬取目录」或建墓碑表） |
| #4 | `update_user` 的 `try/except sqlite3.IntegrityError` 只包住 `commit()`，而唯一索引在 **UPDATE 语句**处即抛 ⇒ 并发改名时逃逸为 500（非本轮引入） | 记录待裁定（既有缺陷，改动会让 500→400 属行为变更） |

#1 / #2 已用 ⚠️ 注释逐条写进 `auth.py`（含复现步骤），避免后人把当前收窄读成「已完备」。

**补的 3 条承重用例 + 对应变异（跑完均已还原，`grep -c MUTATION` = 0）**：

| 用例 | 钉住什么 |
|---|---|
| `…::test_comma_in_former_name_is_not_split` | 「用 JSON 而非分隔符」这个实现选择。两腿都踩判据 3：取回完整的 `_j_a,b` 须 200、取拆出的 `_j_a` 须 400 |
| `…::test_unreadable_other_history_fails_closed` | #6 的保守当满分支（含前置断言「夹具确实造出了坏值」，否则在测空气） |
| `TestLegacyIllegalNameIsNotSelfLocked::test_unchanged_illegal_display_name_no_longer_freezes_update` | `_keep_d`（display_name 入口）的对称腿 + 改成新非法值仍拒的对照 |

| 变异 | 结果 |
|---|---|
| 把存储换成**逗号拼接**（读+写两侧一起换） | **3 红**：目标那条 `test_comma_in_former_name_is_not_split`；另两条是各自 `json.loads(hist)` 的**格式敏感断言**被格式变更打到（`test_rename_back_to_own_former_name_succeeds`、`test_unreadable_other_history_fails_closed`）—— 即审查者所说「退化成逗号拼接时原 5 条全绿」的空档已被补上 |
| 拆掉 `_keep_d`（恒 `False`） | **恰好 1 红**：`test_unchanged_illegal_display_name_no_longer_freezes_update`；其余 7 条全绿 |
| 拆掉 #6 的保守当满（`if not _others_hist_unreadable` → `if True`） | **恰好 1 红**：`test_unreadable_other_history_fails_closed`；其余 7 条全绿 |

#### 验收

- `py/tests/test_scrape_ownership.py`：**76 passed**（原 68；本轮 5 条 + 第 5 轮审查后 3 条）
- 全量：**803 passed / 0 failed**
  —— 785（上一轮基线）+ 8（本轮）+ 12（**并行会话**的户管看板回写用例）
  − 2（**并行会话**在 `5abd134` 里主动停用的两条真实外发通知用例，非本任务）
- `git diff` 口径：本轮只动 `py/auth.py`、`py/database.py`、`py/tests/test_scrape_ownership.py`，
  并删除 `py/tests/_probe_hist_dn.py`

#### 仍未做（不在本轮射程）

- **迁移竞态**：`_ensure_columns` 每次连库都跑却**无锁**，且与 `_cleanup_old_option_columns`
  互相增删 `products.sales_person`；探针 3/3 轮复现 6–7 线程失败，真实库稳态不触发。
  **先于本轮存在**、与目录名归属无关的独立缺陷，仍需单独设计「加/删互斗」的修法。
- **测试隔离到 tmp**：`scrape_dirs` fixture 与相关用例仍直接写**真实** `temp/scraped_images/`
  （DB 已由 `conftest.py` 的 `app` fixture 重指临时文件，**只有爬取目录没隔离**）。
  重指 `_SCRAPE_DEFAULT_DIR` / `auth._scrape_root` 会与 `TestScrapeRootIsSingleSourceOfTruth`
  冲突，属高风险改动，需先裁定。
- **存量非法名治理**（第 5 轮 #3 的后果）：`username` / `display_name` 里含分隔符但
  **留在爬取根内**的存量值不受 `_scrape_dn_for` 兜底保护，会让产物落进别名目录、
  被真实用户当成自己的包列出。live 实测 **0 行**，但需一次性迁移（命中
  `/ \ : \x00` 的值改写成 `user_<id>` 之类）才算收口。
- **删用户不清其爬取目录**（第 5 轮 #2 的根因）：`admin_delete_user` 不删爬取目录，
  既是磁盘无界增长，也是 #2 那条新读路径的来源。修法（删目录 / 建墓碑表）属需裁定的
  目标行为。
- **并发改名逃逸为 500**（第 5 轮 #4）：`update_user` 的 `except sqlite3.IntegrityError`
  只包住 `commit()`，而唯一索引在 UPDATE 语句处即抛。**先于本轮存在**，实测回滚干净
  （无半写状态），修法是上提 `try` 覆盖写序列 —— 但那会把 500 变成 400，属行为变更。

#### 待用户裁定（第 5 轮的三条 Important 中未改的两条）

- **#1 最后持有者被误拒**：名字被 ≥2 人先后用过时，**最后持有者**（数据唯一所在的
  那个人）也被拒，用户可见后果与原缺陷一致（产物在盘上、应用内无恢复路径）。
  修法需把 `prev_scrape_dns` 升级为**带序号的条目**并改用 last-writer-wins
  （认领条件：我的释放序 > 所有其他人的释放序，同值一律拒，故仍 fail-closed）。
  **时机最好**：该列 live 行数为 0，现在改存储格式零成本。
- **#2 被删用户的目录可被认领**：见上表。修法二选一 —— 删用户时同步处理其爬取目录
  （破坏性），或建墓碑表并在 `others_keys` 里纳入被删用户的目录名。

---

### 0.11 第六轮：上述三条裁定的落地（2026-09-24 同日）

上一节列的三条「待裁定」已由用户裁定，全部实现。**判据（判据 1/2/3）本身一个字未动** ——
本轮改的是「曾用名集合从哪来」和「撞唯一索引时怎么收场」。

#### 裁定与实现

| # | 裁定 | 实现 |
|---|---|---|
| #1 | **升级为 last-writer-wins** | 曾用名从 `users.prev_scrape_dns`（JSON 文本）迁到新表 `scrape_dn_history`，一行一个名字、`id` 作**跨用户单调序号**。认领条件改为「我的释放序 > 所有他人的释放序」，同值一律拒（仍 fail-closed） |
| #2 | **建墓碑表** | 同一张 `scrape_dn_history` 兼作墓碑：`admin_delete_user` 先写入该用户**当前**的爬取目录名，再删用户。该表**刻意无外键**、`admin_delete_user` **刻意不清理它**，故墓碑行随用户删除而存活。⚠️ **只覆盖升级之后的删除** —— 见下方「覆盖面边界」 |
| #4 | **顺手修** | `update_user` 的 `try` 上提到覆盖两条会动 `scrape_dn` 的 UPDATE ⇒ 并发改名撞唯一索引时按代码原意返回 `None` → 路由 400，不再逃逸成 500 |

**#1 为什么必须换存储**：JSON 文本只记录「谁用过这个名字」，**没有先后顺序**，
于是认领判据只能做成「除我之外没人用过」⇒ 名字被 ≥2 人先后用过时**最后持有者也取不回
自己的产物**。表存储给每行一个自增 `id`，先后可判。
顺带消灭「分隔符串味」整类缺陷 —— 名字存在**行**里，逗号/换行只是普通字符。

**#1 的迁移是单向的**：`prev_scrape_dns` 里的 JSON 没有时间戳，**跨用户先后无法还原**。
按 `users.id` 顺序「猜」的风险方向是**误放**（先释放的人反倒成了「最后持有者」⇒
认领到别人的产物目录，正是 #2 那一档读路径），远比误拒严重。故对「被 ≥2 人的历史
同时提到」的名字插一行 `user_id=0` 的**哨兵** ⇒ 谁也赢不了 ⇒ 退回「拒」。
代价：存量的 LWW 提升只对升级**之后**发生的改名生效。

**#2 的墓碑为什么不能进 `admin_delete_user` 的清理清单**：那行必须**活过**本次删除，
否则墓碑失效、保护静默消失。已在 `database.py` 建表处、`main.py` 写入处、
`auth.note_scrape_dn_release` 三处写明（措辞统一为「若顺手把本表加进清理清单，
这条保护会静默失效」）。已用变异 m16 实测：加一行 `DELETE FROM scrape_dn_history
WHERE user_id = ?` 会让 #2 主腿**恰好 1 红**（对照腿保持绿）—— 即「静默失效」不成立，
测试抓得住。

#### ⚠️ #2 的覆盖面边界（写文档时漏了，第六轮 code-review 第 1 条指出）

上述墓碑只在**删除发生的当下**写入。**升级之前就已经被删掉**的用户，既无 `users` 行
（无从取 `_scrape_dn_for`），也永远不会有墓碑行 —— 他们留在磁盘上的目录名，在认领判据里
等同于「**无人用过**」。于是任何曾用名恰好等于该目录名的人，按 LWW 就能认领并读到
**升级前已删用户**的产物。第六轮审查者用实测复现了这一条：
`PUT /api/auth/profile {"display_name": "<该目录名>"}` → 200，
`GET /api/scrape/packages` → 能列出该目录下的包。

**这是既有缺口，不是本轮引入的**：改动前的判据（`others_keys` 也只看现存用户）同样
放行。但本轮文档先前写成「#2 已修」而**没写这个边界**，属不实陈述，已改正。

**为什么不能顺手用迁移补上**：迁移时扫描爬取根、把「不属于任何存活用户的目录名」
插成墓碑 —— 但 LWW 判据是「我的释放序 > 所有他人的释放序」，墓碑行在迁移那一刻拿到
当时的**最大** id，此后任何真实用户再释放一次同名就**赢过它**（新 id 更大）⇒ 墓碑被
顶掉，缺口重新出现。要让「升级前已删用户的目录」**永久**不可认领，必须改判据
（例如 `user_id = 0` 的哨兵行**无条件**阻断，而不是参与 seq 比较）—— 那属于**改判据**，
需先裁定。已列入「仍未做」。

#### 迁移

`database._migrate_scrape_dn_history(conn)`：config 键 `migrated_scrape_dn_history` 守卫 →
列不存在则打标记返回 → 否则两趟搬运（先收集，再按用户顺序 INSERT，再插哨兵）→
`ALTER TABLE users DROP COLUMN prev_scrape_dns` → 打标记 → commit。
整体 `try/except` 打印并 rollback，**不打标记**（下次重试）。

两个 DDL 风险已用独立探针先证实，再动生产代码：
`DROP COLUMN` 在「VIRTUAL 生成列 + `COLLATE NOCASE` 唯一索引 + `foreign_keys=ON`
且有子表（`accounts` 等）引用 `users(id)`」的组合下**均可行**，`PRAGMA foreign_key_check` 为空。
（另记：`PRAGMA foreign_keys` 在事务内是空操作，故迁移函数里刻意不写它 —— 写了只是
「看着像防护」，docstring 里说明了理由与实测依据。）

#### 测试

| 文件 | 结果 |
|---|---|
| `py/tests/test_scrape_ownership.py` | **81 passed**（76 − 1 过时 + 6 新增） |
| `py/tests/test_scrape_dn_history_migration.py` | **4 passed**（新建） |

**新增用例（每条主腿都配对照腿）**：

| 用例 | 钉住什么 |
|---|---|
| `TestFormerNameBelongsToLastHolder::test_last_holder_reclaims_own_former_name` | #1：最后持有者须 200，且 `/api/scrape/packages` 里**确实能看到**那个包（不只看状态码） |
| `…::test_earlier_holder_still_cannot_reclaim` | **对照腿**：先前持有者仍须 400（判据 3 文案）—— 防「一刀切全放行」 |
| `TestDeletedUserDirectoryIsTombstoned::test_directory_of_deleted_user_is_not_reclaimable` | #2：删用户后其目录不可被曾用名持有者认领（前置断言「目录仍在盘上」） |
| `…::test_unrelated_deletion_does_not_freeze_others_former_names` | **对照腿**：删无关用户后，我的名字仍能取回 —— 防「一刀切全冻住」 |
| `TestConcurrentDuplicateDirectoryName::test_rename_collision_returns_none_without_half_write` | #4：返回 `None` 且**无半写状态**（第二人 `display_name` 仍为空串） |
| `…::test_concurrent_renames_to_same_name_never_500` | #4：6 线程并发改名 ⇒ 无 5xx、恰好 1 个 200、恰 `n−1` 个 400 |
| `test_scrape_dn_history_migration.py` 全 4 条 | 迁移顺序/坏值跳过/旧列真删/生成列存活；LWW 按序生效；**歧义名谁也不给**（fail-closed）+ 无歧义名对照；幂等（**含「标记必须真的写上」**） |

**`test_unreadable_other_history_fails_closed` 已删除**：它钉的是「读**别人**的
`prev_scrape_dns` 坏值时保守当满」（第五轮 #6）。存储换表后该分支不存在了
（`scrape_dn_history.dn` 是 `NOT NULL` 列，没有「非空但解析失败」这一档），
故用例失去动因。对应变异 m6 一并作废。

**变异验证（m7–m16，10 条，跑完均已还原，`grep -c MUTATION py/{database,auth,main}.py` 均为 0）**：

| 变异 | 结果 |
|---|---|
| m7 `except IntegrityError: raise`（≡ 修复前） | **2 红**：两条 #4 用例，无额外 |
| m8 删掉墓碑写入 | **恰好 1 红**：#2 主腿；**对照腿保持绿** ⇒ 两条用例职责不重叠 |
| m9 丢掉序号（退回旧判据） | **恰好 1 红**：#1 主腿 |
| m10 全算别人（`mine` 恒空） | **4 红**（含控制腿）⇒ 能抓住「一刀切全冻住」 |
| m11 全算我的（谁有过行谁就能认领） | **4 红**（全部保护腿）⇒ 能抓住「一刀切全放行」 |
| m12 不删旧列 | **1 红** |
| m13 不写迁移标记 | **1 红**（见下） |
| m14 不插歧义哨兵 | **1 红** |
| m15 搬运动序倒 | **2 红** |
| m16 把墓碑表加进 `admin_delete_user` 的清理清单 | **恰好 1 红**：#2 主腿；**对照腿保持绿** |

#### 自查中抓出的两处「假绿」

1. **「幂等」用例一开始是假绿**：即便删掉写标记那行，第二次调用也会走「列已不存在 ⇒
   直接返回」而不再搬运，行数照样不变。补上「标记必须真的写上」的断言后，m13 才如期转红。
2. **迁移的跨用户顺序不可还原**（误放风险，见上）—— 自查时发现原方案按 `users.id`
   顺序「猜」先后，猜反方向是**误放**。改为插哨兵 + 新增专门用例，m14 钉住。

3. **文档里的一句「断言」也是断言**：我原先在 `AGENTS.md` 写「若有人把墓碑表加进清理清单，
   这条保护会静默失效、**且无任何测试会转红**」—— 没验证就写下了。m16 实测后是**错的**：
   测试确实抓得住（恰好 1 红）。已改正。**文档里对代码行为的断言同样受「无对照行的断言
   不能写」约束**，尤其是否定式断言（「没有测试覆盖」）最容易被想当然。

三条都印证同一条硬规矩：**「无对照行的断言不能写」**（前两条是测试断言=假绿，
第三条是文档断言=想当然）。

#### 验收

- `py/tests/test_scrape_ownership.py`：**81 passed**（76 − 1 过时 + 6 新增）
- `py/tests/test_scrape_dn_history_migration.py`：**4 passed**（新建）
- 全量：**864 passed / 0 failed**（256s）
  —— ⚠️ 该数是**工作区合并态**，含**并行会话**在途新增/修改的用例
  （`test_delist_indeterminate.py`、`test_huguan_dashboard.py`、`test_tt_*`、
  `test_delist_checker.py` 等，非本任务），故不能当成本任务的增量。
  本任务自身的增量就是上面两行（81 + 4）。
- `git diff` 口径：本轮只动 `py/auth.py`、`py/database.py`、`py/main.py`（**仅
  `admin_delete_user` 一处墓碑写入的 hunk** —— 该文件另有并行会话在途的掉包「判定未知」
  改动，提交时用过滤补丁只暂存本任务的 hunk，见提交说明）、
  `py/tests/test_scrape_ownership.py`，并新增 `py/tests/test_scrape_dn_history_migration.py`
- 文档：本文件 §0.11、`AGENTS.md`（索引行 + 表总览 51→52 张 / GG 29→30 张 +
  「删用户关联清理」下新增墓碑表例外警示）

#### 仍未做（本轮**未**纳入，与上一节同一清单的更新）

- ~~**#1 最后持有者被误拒**~~ —— **已修**（本轮）
- ~~**#2 被删用户的目录可被认领**~~ —— **已修，但只对升级之后的删除生效**（本轮，墓碑表）；
  升级前已删的那一档仍在，见下方专条
- ~~**并发改名逃逸为 500**~~ —— **已修**（本轮 #4）
- **删用户不清其爬取目录**（#2 的根因之一）：墓碑表只挡住了「被认领读到」，
  **磁盘无界增长**这个缺口仍在，`admin_delete_user` 仍不删目录。
- **迁移竞态**：`_ensure_columns` 每次连库都跑却**无锁**，且与 `_cleanup_old_option_columns`
  互相增删 `products.sales_person`；探针 3/3 轮复现 6–7 线程失败，真实库稳态不触发。
  **先于本轮存在**、与目录名归属无关的独立缺陷，仍需单独设计「加/删互斗」的修法。
- **测试隔离到 tmp**：`scrape_dirs` fixture 与相关用例仍直接写**真实** `temp/scraped_images/`
  （DB 已由 `conftest.py` 的 `app` fixture 重指临时文件，**只有爬取目录没隔离**）。
  重指 `_SCRAPE_DEFAULT_DIR` / `auth._scrape_root` 会与 `TestScrapeRootIsSingleSourceOfTruth`
  冲突，属高风险改动，需先裁定。
- **存量非法名治理**（第 5 轮 #3 的后果）：`username` / `display_name` 里含分隔符但
  **留在爬取根内**的存量值不受 `_scrape_dn_for` 兜底保护，会让产物落进别名目录、
  被真实用户当成自己的包列出。live 实测 **0 行**，但需一次性迁移（命中
  `/ \ : \x00` 的值改写成 `user_<id>` 之类）才算收口。
- **升级前已删用户的目录仍可被认领**（#2 的覆盖面边界，第六轮 code-review 第 1 条）：
  见上方「#2 的覆盖面边界」。修法需**改判据**（`user_id = 0` 哨兵无条件阻断），
  不是补一处写入点 —— 需先裁定。
- **记「释放」用的求值函数与读路径不一致**（第六轮 code-review 第 2 条）：
  `auth._dir_name_of`（`py/auth.py:72`）= `display_name or username`（空则 `user_<id>`）；
  `main._scrape_dn_for`（`py/main.py:453`）**多一步**「推导结果越出爬取根 ⇒ 退化为
  `user_<id>`」。对**越界**的存量 `display_name`（如 `..\..\_x`，写入关口加固前落库的值），
  两者给出**不同**的名字：真实目录是 `user_<id>`，而改名时记下的释放名是 `..\..\_x`。
  后果：该用户改名离开后，其真实目录 `user_<id>` **永不进** `own_keys`/`hist_keys`
  ⇒ 判据 3 永久拒其认领 ⇒ 产物在盘上、应用内无恢复路径。
  附带：同一个越界存量用户与「名字恰好是 `user_<id>`」的新用户，在**真实磁盘上共用
  同一目录**，而 `directory_name_error` 的判重看不见（它用 `_dir_name_of`），漏判重。
  **先于本轮存在**（改动前的 JSON 存储同样用 `_dir_name_of`）。修法：把 `_scrape_dn_for`
  的越界退化**同步进** `_dir_name_of`（auth 已有 `_scrape_root()`，可本地实现）——
  但那会改动**存量值的判重口径**，属行为变更，需先裁定。
- **`temp/` 清理与 `temp/_.*` gitignore**：探针脚本、变异脚本、`.bak` 库文件长期裸奔在
  `temp/` 下（仓库既有惯例是留着一批 `temp/_*.py`），未定型。

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
