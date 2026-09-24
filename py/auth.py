import json
import os
import sqlite3

from werkzeug.security import generate_password_hash, check_password_hash
from flask_jwt_extended import create_access_token, create_refresh_token

import database

# ---------------------------------------------------------------------------
# 用户可控字符串会变成**文件系统标识**
# ---------------------------------------------------------------------------
# main.py 的 _scrape_dn_for 是 `display_name or username` —— 直接把用户数据当
# 爬取产物目录名，而爬取产物的归属校验就建立在这个目录名上。
# 于是「用户名/显示名可自由填、可重名」等于「可以冒名占住别人的目录」。
#
# 2026-09-24 实测（code-review 第 2 轮 HIGH，安全加固返工），**两次**：
#   ① display_name：bob 改成 alice 的目录名 → 不传 save_dir 的 POST /api/scrape
#      → 200，拿到**为 alice 的包签发的合法签名** → 匿名 GET → 200/121 字节。
#      **全程不需要任何路径穿越** —— 只因目录名=display_name。
#      display_name = `..\..\x` 还能让端点在 _SCRAPE_DEFAULT_DIR 之外建出目录。
#   ② username：只锁 ① 之后，用 username = `..\..\_un_e\pwn`（15 字符，长度
#      闸门放行）注册 → _scrape_dir_for 推导出的路径仍在爬取根之外。
#      ⇒ 这条通道有**两个入口**，锁一个等于没锁。
#
# ⇒ 校验必须堵在**唯一写入关口**（create_user / update_user），不能靠各路由自觉。
#   本文件独立推导一次路径，与 database.py 的 _db_path() 同一惯例；
#   两边一致由 test_scrape_ownership.py 的一条断言钉住，防路径漂移。
def _scrape_root() -> str:
    """爬取产物根目录（须与 main.py 的 _SCRAPE_DEFAULT_DIR 一致，有测试钉住）。"""
    current = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(os.path.dirname(current), "temp", "scraped_images")


def _fs_name_error(name: str, what: str):
    r"""**文件系统标识**的字符闸门 —— username 与 display_name 共用。

    两者都会经 main._scrape_dn_for 变成爬取产物目录名（该函数就是
    `display_name or username`），也就是说这条通道有**两个入口**。
    只锁其中一个 = 没锁 —— 2026-09-24 实测：仅锁 display_name 之后，用
    username = `..\..\_un_e\pwn`（15 字符，长度闸门放行）注册，得到的
    `_scrape_dir_for` 路径规范化后在 _SCRAPE_DEFAULT_DIR 之外。

    故字符约束必须写在**一处**、两个入口共用，而不是各写一份字符表 ——
    本文件此前正是因为「归属只堵在一处」才被绕过两次。
    """
    if not name:
        return None                      # 空 = 该入口不提供目录名，交给另一个入口
    if name in (".", ".."):
        return f"{what}不能是 . 或 .."
    if any(c in name for c in "/\\:\x00"):
        return f"{what}不能包含路径分隔符、冒号或空字符"
    if name.startswith(".") or name.endswith("."):
        return f"{what}不能以点开头或结尾"
    if name != name.strip():
        return f"{what}首尾不能有空白"
    return None


def _effective_dn(username, display_name) -> str:
    """(username, display_name) 解析出的**爬取目录名**（不含 `user_<id>` 兜底）。

    必须与 main._scrape_dn_for 的解析一致（都是 `display_name or username`，
    再 strip）。两边一致由 test_scrape_ownership.py 的
    `TestEffectiveDnMatchesScrapeDnFor` 钉住，防解析漂移 ——
    本注释此前声称"有断言钉住"，而那条断言**并不存在**（code-review 第 3 轮
    指出：被钉住的只有路径，解析规则无人管）。现已补上，注释不再撒谎。
    """
    return (display_name or username or "").strip()


def _dir_name_of(uid, username, display_name) -> str:
    """某一行的**实际爬取目录名** —— 即 _scrape_dn_for 真正会用的那一个。

    与 _effective_dn 的差别只有一处：两者都空时退化成 `user_<id>`。
    判重必须用本函数而不是 _effective_dn —— 否则 `user_<id>` 这个兜底
    命名空间**整个不在比较空间里**（code-review 第 3 轮 M3，实测：
    注册 `username = "user_2"` 或把 display_name 设成 `user_2`，都能与
    2 号用户的兜底目录撞名而判重放行）。
    """
    return _effective_dn(username, display_name) or f"user_{uid}"


def _dn_key(name: str) -> str:
    """判重/占用比较用的**文件系统键** —— 大小写归一。

    Windows/NTFS 大小写不敏感：`alice` / `Alice` / `ALICE` 是**同一个目录**
    （本机实测 os.path.samefile 为 True，且透过大写路径能读到另一方的文件、
    写入也落进同一目录）。裸字符串比较看不见这件事，于是两个用户可以共用
    一个目录 —— 与「首尾点」是同一类机制，只是落在判重轴上。

    os.path.normcase 在 POSIX 上恒等，在 Windows 上折叠大小写；比它更宽松的
    折叠（数据库侧 NOCASE 只折 ASCII）由 DB 唯一索引兜住，应用层更严即 fail-closed。
    """
    return os.path.normcase(name)


def _dn_history(raw) -> list:
    r"""解析 `users.prev_scrape_dns`（JSON 数组文本）为字符串列表；坏值一律当空。

    为什么用 JSON 而不是逗号/换行分隔：`_fs_name_error` 只挡了路径分隔符、冒号、
    空字符与首尾的点/空白，**名字中间允许逗号和换行** —— 用分隔符拼接会在这里
    串味（`a,b` 一个名字会被拆成两个）。

    ⚠️ 「坏值当空」的方向**取决于是谁的**，两边**相反**，不可一概而论：
      · 读 `me` 的历史（决定「哪些名字我能不能认领」）→ 当空**是 fail-closed**：
        读不出来只是我不再去认领，不会把别人的名字误判成自己的。
      · 读**别人**的历史（决定「哪些名字已经被别人用过」）→ 当空**是 fail-open**：
        漏看他用过的名字，就可能让我认领到一个装着**他的**产物的目录。
    本函数自身**无法区分「本来就是空」与「坏了」**（两者都返回 `[]`），所以「当空
    还是当满」由**调用方按用途**决定：`directory_name_error` 读**别人**的历史时，
    对「非空但解析失败」的行**整体放弃认领**（保守当满），不依赖本函数的返回值分辨。
    当前该情形**不可达**：本列只由 `_dn_history_append` 写入，写进去的永远是合法
    JSON（`json.loads(json.dumps(x))` 恒成立）。但上面那道保守处理**不依赖**这个
    假设 —— 哪天外部改库或人工编辑造出坏值，认领也只是退回修复前的「拒」。
    """
    if not raw:
        return []
    try:
        val = json.loads(raw)
    except (ValueError, TypeError):
        return []
    if not isinstance(val, list):
        return []
    return [x for x in val if isinstance(x, str) and x]


def _dn_history_append(raw, name) -> str:
    """把 name 追加进曾用名（按 `_dn_key` 归一判重）；无需追加时**原样返回** raw。

    原样返回（而不是回写一份规范化后的 JSON）是为了让调用方能靠 `==` 判断
    「没变化」，从而不产生无意义的 UPDATE。
    """
    names = _dn_history(raw)
    if not name:
        return raw
    key = _dn_key(name)
    if any(_dn_key(n) == key for n in names):
        return raw
    names.append(name)
    return json.dumps(names, ensure_ascii=False)


def directory_name_error(uid, username=None, display_name=None):
    """校验这组取值解析出的**爬取目录名**是否可用。返回错误串；None 表示可用。

    uid=None 表示**新建**用户；uid 给定而 username / display_name 传 None，
    表示「沿用该用户当前的值」（只改其中一个字段的常见情形）。

    三条判据缺一不可：
      1. 字符 —— username 与 display_name 是同一通道的两个入口，都要过闸门
      2. 唯一 —— ⚠️ 比对的是**解析后的目录名**、且必须**含 user_<id> 兜底**、
         且必须**大小写归一**。三个维度各由一次实测换来：
           · 只比列 → 漏掉「bob 把 display_name 设成 alice 的 username」
             （alice 没有 display_name，列上不同名，目录却是同一个）
           · 不比兜底 → 漏掉 `user_<id>` 命名空间的冒名
           · 不比大小写 → 漏掉「bob 认领 ALICE」，而 NTFS 认为它与 alice 同目录
         任一条漏检都等价于最初的 HIGH 越权原样复活。
      3. 目录占用 —— 与爬取根下**已存在的任何目录**做大小写归一碰撞检测，
         **空目录同样拒**。空目录必须拒：否则攻击者先占名、等对方产出再共享
         —— 实测「目录不存在」与「目录存在但为空」两档在原实现下都能通过，
         而每周清理会把整个爬取根 rmtree 重建，那一瞬间**全库**都落在
         「目录不存在」这一档，窗口每周重开。
         仅做 1+2 也挡不住「无主目录」（用户被删而 temp/scraped_images/<名字>/
         还在），第 3 条才是。
    """
    conn = database.get_db()
    try:
        me = conn.execute(
            "SELECT id, username, display_name, prev_scrape_dns FROM users WHERE id = ?",
            (uid,)).fetchone() if uid is not None else None
        others = conn.execute(
            "SELECT id, username, display_name, prev_scrape_dns FROM users "
            "WHERE id IS NOT ?", (uid,)
        ).fetchall()
    finally:
        conn.close()

    if me:
        if username is None:
            username = me["username"]
        if display_name is None:
            display_name = me["display_name"]

    # L-7：对「与库里现值**完全相同**」的字段跳过**字符**判据。
    #
    # 为什么：闸门上线**之前**入库的非法值（例如 username 里带路径分隔符）会把
    # 用户自己锁死 —— 他只想改显示名，本函数却把他**没动过**的 username 一并
    # 拿出来验，恒判非法 ⇒ 该用户任何一次资料更新都 400；而 profile 端点根本
    # 不允许改 username ⇒ 没有任何修正通道（live 库实测 0 行，属潜伏；已独立复现）。
    # 这个值此刻**已经在生效**，重验一遍挡不住任何事，只会锁死用户。
    #
    # 真实的边界：本豁免只对「与库中现值**严格相等**」的值生效 ⇒ 相等即无变更，
    # 它**不可能**把一个新的非法值放进来，凡改动过的值一律仍在闸门外。
    #
    # ⚠️ 这里早先写着「安全性由 main._scrape_dn_for 的结构兜底接住」，那是**错的**
    # （code-review 第 5 轮指出，已独立复现）：兜底条件只是「推导结果不得越出爬取
    # 根」，而 `nest_user/pkg`、`alice/pkg` 这类**含分隔符但留在根内**的值规范化后
    # 仍在根内 ⇒ **不退化**，实测目录名原样就是 `nest_user/pkg`。它的后果不是读到
    # 根外，而是往一个真实用户（如 `alice`）的目录里凭空多出一个 `pkg` 子目录，
    # 被 scrape_packages 当成**她自己的包**列出、可经正门下载 —— 等于她能读到那个
    # 存量用户的产物。
    # 于是接受本豁免的依据**只剩一条事实**：这类值只可能来自闸门上线**之前**的
    # 存量数据，而 live 库实测 0 行。它**没有被结构兜底覆盖**，需要按存量数据治理
    # （见设计文档 §0.10「仍未做」）。且**只豁免字符判据** —— 判据 2/3 比的是别人
    # 与磁盘，与旧值本身是否合法无关，照旧执行。
    _keep_u = me is not None and username == me["username"]
    _keep_d = me is not None and display_name == me["display_name"]
    err = None
    if not _keep_u:
        err = _fs_name_error(username, "用户名")
    if not err and not _keep_d:
        err = _fs_name_error(display_name, "显示名")
    if err:
        return err

    eff = _effective_dn(username, display_name)
    if not eff:
        # 两个都空 ⇒ _scrape_dn_for 退化成 user_<id>，不占任何共享名字；
        # others 里同样解析为空的行各自退化成**自己的** user_<id>，互不相同。
        return None

    key = _dn_key(eff)

    # 判据 2：与所有其他用户的**实际目录名**比（含兜底 + 大小写归一）
    for r in others:
        if _dn_key(_dir_name_of(r["id"], r["username"], r["display_name"])) == key:
            return "该名字会与其他用户的爬取目录重名，请换一个"

    # 自己的名字空间 = 当前目录名 + username 派生目录名。
    # 后者是为了不误伤「清空 display_name」这个正常操作 —— 清空后目录名回落
    # 到 username，而那个目录按命名规则本来就是自己的。
    own_keys = set()
    if me:
        own_keys.add(_dn_key(_dir_name_of(me["id"], me["username"], me["display_name"])))
        own_keys.add(_dn_key(_dir_name_of(me["id"], me["username"], "")))

    # 曾用目录名（MEDIUM-1）：改名之后旧目录仍留在磁盘上，但它既不在上面两行里、
    # 也不属于任何**其他**现存用户的**当前**目录名（判据 2 只看这一维），于是判据 3
    # 会把「改回我的曾用名」一并拒掉 —— 用户此前的产物永远回不去。
    # 判据 3 的正当目的是挡「无主目录」（用户被删而目录还在）被**他人**认领。
    #
    # ⚠️ 但这个豁免必须**收窄**：只有「除我之外没有任何人用过」的名字才算我的。
    # 若别人也用过同一个名字，他可能在该目录下爬出过产物，凭「我曾用过」放行就等于
    # 让我读到**他的**产物 —— 把判据 3 整条绕开。已运行时复现，见
    # TestFormerDirectoryNameIsReclaimable::
    #   test_former_name_that_someone_else_also_used_is_not_reclaimable（先红后绿）。
    # 「用过」必须**含曾用名**：别人改名离开后，他的产物仍留在那个目录里。
    # 别人用过的名字一律退回**修复前**的行为（拒），fail-closed。
    #
    # ⚠️ 已知边界一（误拒，code-review 第 5 轮 Important #1，已独立复现）：本收窄比
    # 「目录里的数据是否干净」**更保守** —— 一个名字被 ≥2 人先后用过时，**最后持有者**
    # 也被拒。复现：P 占空闲名 N（从未产出）→ 改名离开；Q 合法接手 N（能放行这件事
    # 本身就证明目录里没有 P 的产物）→ 产出后离开；此时 Q 想取回 N 被拒，而目录里
    # **只有 Q 自己的产物**。用户可见后果与原缺陷一致（产物在盘上、应用内无恢复
    # 路径）。这是「只看名字、不看目录内容」这一路线的固有上限；要修全需改存储格式
    # 记「谁最后释放了该名」（last-writer-wins），属需裁定的目标行为。
    #
    # ⚠️ 已知边界二（误放，Important #2，已独立复现）：`others` 只能看到**还存在的**
    # 行。用户被删后（admin_delete_user 不删爬取目录），他的目录名连同历史一起消失，
    # 于是任何 `prev_scrape_dns` 含该名的人都能认领它、读到**被删用户**的产物。
    # 复现：M 的曾用名含 D → V 合法接手 D 并产出 → M 认领被拒（判据 2）→ 删掉 V →
    # M 认领 D 放行，目录里是 V 的产物。**这条边界正是判据 3 声称要挡的「无主目录」
    # 那一档** —— 现有唯一收口点是「删用户时同步处理其爬取目录」或建墓碑表，属需
    # 裁定的目标行为（删目录是破坏性操作）。
    #
    # ⚠️ 本列**只增不减** ⇒ 一个名字一旦被谁用过，就**永久**对其他人关闭认领。
    # 它不是白名单，别当白名单用。且本修复是**单向**的：只对**上线后**发生的改名
    # 生效 —— 此前改过名、旧目录还在的用户 `prev_scrape_dns` 仍是空串，同症状仍在，
    # 且**无法自动回填**（无主目录的归属无法事后判定）。
    #
    # 刻意**不**把曾用名加进判据 2 的比较空间：那会让任何名字一旦被谁用过就全局
    # 永久保留（prev_scrape_dns 只增不减），而「空目录被抢」没有数据可失 ——
    # 真正的数据保护来自判据 3「目录是否存在」，产物存在 ⇔ 目录存在。
    hist_keys = set()
    if me:
        others_keys = set()
        _others_hist_unreadable = False
        for r in others:
            others_keys.add(_dn_key(_dir_name_of(r["id"], r["username"], r["display_name"])))
            _oh_list = _dn_history(r["prev_scrape_dns"])
            if r["prev_scrape_dns"] and not _oh_list:
                _others_hist_unreadable = True
            for _oh in _oh_list:
                others_keys.add(_dn_key(_oh))
        # 别人的历史「非空但解析失败」⇒ 不知道他用过哪些名字 ⇒ **整体放弃认领**，
        # 退回修复前的行为（拒）。方向必须与读**我自己**历史时相反：那边坏值当空是
        # fail-closed（只是我不再认领），这边当空是 fail-open（漏看别人用过的名字，
        # 就可能认领到装着他产物的目录）。见 _dn_history 的 docstring。
        if not _others_hist_unreadable:
            for _h in _dn_history(me["prev_scrape_dns"]):
                _k = _dn_key(_h)
                if _k not in others_keys:
                    hist_keys.add(_k)

    # 判据 3：目录占用 —— 与爬取根下已存在的任何目录碰撞即拒。
    # 此处**枚举真实目录名**而不是 realpath(join(root, eff))：realpath 只在
    # 目标**已存在**时才把大小写折叠到磁盘上的真实值，恰恰漏掉「目录还不存在」
    # 这一档 —— 那正是缺口所在。
    try:
        existing = os.listdir(_scrape_root())
    except OSError:
        existing = []
    for d in existing:
        dk = _dn_key(d)
        if dk == key and dk not in own_keys and dk not in hist_keys:
            return "该名字对应的爬取目录已被占用，请换一个"
    return None


def hash_password(password: str) -> str:
    return generate_password_hash(password)


def verify_password(password: str, hashed: str) -> bool:
    return check_password_hash(hashed, password)


def create_user(username: str, password: str, role: str = "user",
                display_name: str = "", created_by: int = None,
                platform: str = "gg") -> dict:
    conn = database.get_db()
    try:
        # 与 update_user 对齐：两边都在关口处 strip，否则同一输入在两条写路径上
        # 判定相反（建号被拒、改名被归一化）—— 口径不一本身就是缺陷。
        if display_name is not None:
            display_name = display_name.strip()

        cur = conn.execute(
            "SELECT id FROM users WHERE username = ?", (username,)
        )
        if cur.fetchone():
            return None

        # username 与 display_name 都会成为爬取产物目录名（main._scrape_dn_for），
        # 故必须在**唯一写入关口**校验，各路由无法绕过。见 directory_name_error。
        if directory_name_error(None, username, display_name):
            return None

        hashed = hash_password(password)
        try:
            cur = conn.execute(
                "INSERT INTO users (username, password, role, display_name, created_by, platform) VALUES (?, ?, ?, ?, ?, ?)",
                (username, hashed, role, display_name, created_by, platform)
            )
            conn.commit()
        except sqlite3.IntegrityError:
            # users.scrape_dn 唯一索引弹回：并发的另一次注册在
            # directory_name_error 的读快照与本次 INSERT 之间插入了同名目录名。
            # 口径是 check-then-act 在 Python 里非原子 —— 原子性只能交给 DB。
            # 实测（code-review 第 3 轮 H2）8 线程并发注册同名 display_name 时
            # 应用层闸门 8/8 全放行，正是这条索引把结果收敛为"只成功一个"。
            return None
        return get_user_by_id(cur.lastrowid)
    finally:
        conn.close()


def get_user_by_id(user_id: int) -> dict | None:
    conn = database.get_db()
    try:
        cur = conn.execute(
            "SELECT id, username, role, display_name, created_at, last_login, created_by, config, email, telegram_username, platform FROM users WHERE id = ?",
            (user_id,)
        )
        row = cur.fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def get_user_by_username(username: str) -> dict | None:
    conn = database.get_db()
    try:
        cur = conn.execute("SELECT * FROM users WHERE username = ?", (username,))
        row = cur.fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def list_users(search: str = "", page: int = 1, page_size: int = 20, current_user_id: int = None, platform: str = None, role_filter: str = None) -> dict:
    """列出用户。非 developer 只看自己平台且看不到 developer；developer 看全部（可选按 platform 筛）。
    platform: 可选筛选 ('gg' | 'fb' | 'tt')，仅 developer 生效，None 表示不过滤。
    role_filter: 可选角色筛选，None 表示不过滤（默认行为与历史一致）。
    """
    conn = database.get_db()
    try:
        # 判断当前用户是否是 developer / 户管
        is_dev = False
        is_huguan = False
        my_platform = None
        if current_user_id:
            cur_user = conn.execute("SELECT role, platform FROM users WHERE id = ?", (current_user_id,)).fetchone()
            is_dev = cur_user and cur_user["role"] == "developer"
            is_huguan = cur_user and cur_user["role"] == "huguan"
            my_platform = (cur_user["platform"] if cur_user else None) or "gg"

        # 非 developer 用户看不到 developer 角色，且只能看自己平台（户管例外，见下）
        filters = [""] if is_dev else ["role != 'developer'"]
        params = []

        if is_huguan:
            # 户管跨平台：既不按自己平台过滤，也忽略传入的 platform 参数
            pass
        elif not is_dev and current_user_id:
            # 非 developer 且有登录上下文：强制只看自己平台，忽略传入的筛选参数
            filters.append("platform = ?")
            params.append(my_platform)
        elif platform:
            # developer 或无登录上下文（内部调用）：按传入参数筛选
            filters.append("platform = ?")
            params.append(platform)

        if role_filter:
            filters.append("role = ?")
            params.append(role_filter)

        base_where = " AND ".join(f for f in filters if f)
        where_clause = f" WHERE {base_where}" if base_where else ""

        SELECT_COLS = "id, username, role, display_name, created_at, last_login, created_by, telegram_username, platform"

        if search:
            like = f"%{search}%"
            search_clause = (" WHERE " if not where_clause else " AND ") + "(username LIKE ? OR display_name LIKE ?)"
            total = conn.execute(
                f"SELECT COUNT(*) as total FROM users{where_clause}{search_clause}",
                params + [like, like]
            ).fetchone()["total"]
            offset = (page - 1) * page_size
            rows = conn.execute(
                f"SELECT {SELECT_COLS} FROM users{where_clause}{search_clause} ORDER BY id DESC LIMIT ? OFFSET ?",
                params + [like, like, page_size, offset]
            ).fetchall()
        else:
            total = conn.execute(
                f"SELECT COUNT(*) as total FROM users{where_clause}",
                params
            ).fetchone()["total"]
            offset = (page - 1) * page_size
            rows = conn.execute(
                f"SELECT {SELECT_COLS} FROM users{where_clause} ORDER BY id DESC LIMIT ? OFFSET ?",
                params + [page_size, offset]
            ).fetchall()
        return {"users": [dict(r) for r in rows], "total": total}
    finally:
        conn.close()


def update_user_role(user_id: int, new_role: str) -> bool:
    # 纵深防御：即使调用方漏校验，也不允许写入未知角色
    if new_role not in ("user", "admin", "viewer", "hidden", "huguan"):
        return False
    conn = database.get_db()
    try:
        cur = conn.execute("SELECT role FROM users WHERE id = ?", (user_id,))
        row = cur.fetchone()
        if not row or row["role"] == "developer":
            return False
        conn.execute("UPDATE users SET role = ? WHERE id = ?", (new_role, user_id))
        conn.commit()
        return True
    finally:
        conn.close()


def update_user(uid: int, username: str = None, display_name: str = None, platform: str = None) -> dict | None:
    """编辑用户信息（用户名、显示名、平台）。返回更新后的用户 dict，失败返回 None。"""
    conn = database.get_db()
    try:
        existing = conn.execute("SELECT * FROM users WHERE id = ?", (uid,)).fetchone()
        if not existing:
            return None
        # 改名前解析出的目录名 —— 改名成功后要记进 prev_scrape_dns（见下方的追加块）。
        old_dn = _dir_name_of(existing["id"], existing["username"], existing["display_name"])

        if display_name is not None:
            display_name = display_name.strip()
        # username 同理必须**先归一、再过关口**。本行原本在下方
        # `if username is not None:` 分支内（位置在关口**之后**），上一轮被误删后
        # 只剩路由层归一，直调 update_user 的路径会漂。归位并上提的原因：
        # 留在关口之后时，建号路径（路由层 strip）传 "bob" 得 200，改名路径传
        # "bob " 会被 _fs_name_error「首尾不能有空白」拒成 400 —— 同一输入两条
        # 写路径判定相反（code-review 第 3 轮指出）。
        if username is not None:
            username = username.strip()

        # 目录名关口：**任一**字段改动都会改变爬取目录名（_scrape_dn_for 是
        # `display_name or username`），故在此一次性判定，而不是各分支各判一次
        # —— 分两处判会漏掉「两个一起改」的组合。见 directory_name_error。
        if username is not None or display_name is not None:
            if directory_name_error(uid, username, display_name):
                return None

        if username is not None:
            if len(username) < 4 or len(username) > 20:
                return None
            # 检查用户名是否被其他用户占用
            dup = conn.execute(
                "SELECT id FROM users WHERE username = ? AND id != ?", (username, uid)
            ).fetchone()
            if dup:
                return None
            conn.execute("UPDATE users SET username = ? WHERE id = ?", (username, uid))

        if display_name is not None:
            conn.execute("UPDATE users SET display_name = ? WHERE id = ?", (display_name, uid))

        if platform is not None:
            conn.execute("UPDATE users SET platform = ? WHERE id = ?", (platform, uid))

        # 曾用目录名落库（MEDIUM-1）：目录名**变了**就把旧名字记下来。
        # 必须在 commit 之前、与改名同属一个事务 —— 否则「改名成功而历史没落库」
        # 会留下一个永久死角：旧目录还在磁盘上，判据 3 却因为它不在 own_keys 里
        # 而把改回曾用名这条路封死，且再没有任何别的恢复路径。
        _hist_row = conn.execute(
            "SELECT username, display_name, prev_scrape_dns FROM users WHERE id = ?",
            (uid,)).fetchone()
        if _hist_row is not None:
            _new_dn = _dir_name_of(uid, _hist_row["username"], _hist_row["display_name"])
            if _dn_key(_new_dn) != _dn_key(old_dn):
                _hist = _dn_history_append(_hist_row["prev_scrape_dns"], old_dn)
                if _hist != _hist_row["prev_scrape_dns"]:
                    conn.execute("UPDATE users SET prev_scrape_dns = ? WHERE id = ?",
                                 (_hist, uid))

        try:
            conn.commit()
        except sqlite3.IntegrityError:
            # 同 create_user：并发改名撞上 users.scrape_dn 唯一索引。
            return None
        return get_user_by_id(uid)
    finally:
        conn.close()


def update_password(uid: int, new_password: str) -> bool:
    """修改用户密码。"""
    if not new_password or len(new_password) < 6:
        return False
    conn = database.get_db()
    try:
        existing = conn.execute("SELECT id FROM users WHERE id = ?", (uid,)).fetchone()
        if not existing:
            return False
        hashed = hash_password(new_password)
        conn.execute("UPDATE users SET password = ? WHERE id = ?", (hashed, uid))
        conn.commit()
        return True
    finally:
        conn.close()


def toggle_user_status(user_id: int) -> dict | None:
    conn = database.get_db()
    try:
        cur = conn.execute("SELECT id, role FROM users WHERE id = ?", (user_id,))
        row = cur.fetchone()
        if not row or row["role"] == "developer":
            return None
        new_role = "hidden" if row["role"] in ("user", "admin", "viewer", "huguan") else "user"
        conn.execute("UPDATE users SET role = ? WHERE id = ?", (new_role, user_id))
        conn.commit()
        return get_user_by_id(user_id)
    finally:
        conn.close()


def update_last_login(user_id: int):
    conn = database.get_db()
    try:
        conn.execute("UPDATE users SET last_login = datetime('now') WHERE id = ?", (user_id,))
        conn.commit()
    finally:
        conn.close()


def login_user(username: str, password: str) -> dict | None:
    user = get_user_by_username(username)
    if not user or user["role"] == "hidden":
        return None
    if not verify_password(password, user["password"]):
        return None
    update_last_login(user["id"])
    access_token = create_access_token(identity=str(user["id"]))
    refresh_token = create_refresh_token(identity=str(user["id"]))
    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "user": {"id": user["id"], "username": user["username"], "role": user["role"], "display_name": user.get("display_name", ""), "platform": user.get("platform", "gg")}
    }


def register_user(username: str, password: str, display_name: str = "") -> dict | None:
    return create_user(username=username, password=password, role="user", display_name=display_name, created_by=None)


def init_developer(config: dict):
    dev_config = config.get("developer", {})
    username = dev_config.get("username", "admin")
    password = dev_config.get("password", "admin123")
    existing = get_user_by_username(username)
    if existing:
        return
    if create_user(username=username, password=password, role="developer",
                   display_name="Developer"):
        print(f"[Auth] Developer account created: {username}")
        return
    # display_name 可能因与既有爬取目录冲突被拒（例如库被清空但
    # temp/scraped_images/ 还在）。退化为**不带显示名** —— 此时目录名回落到
    # username，即 _scrape_root()/<username>。
    if create_user(username=username, password=password, role="developer", display_name=""):
        print(f"[Auth] Developer account created: {username} (无显示名)")
        return
    # ⚠️ 两次都失败：兜底只绕开了 display_name 侧，绕不开 username 侧 ——
    # 退化后目录名就是 username，若 temp/scraped_images/<username>/ 同样被占用，
    # 第二次依旧被拒。developer 账号建不出来 = 整个系统谁也进不去，
    # 所以这里**必须显式告警**。（原实现在此无条件 print "created"，
    # 会把"系统已经不可登录"报成成功 —— code-review 第 3 轮指出。）
    print(f"[Auth] !! 无法创建 developer 账号 `{username}`："
          f"爬取目录 `{os.path.join(_scrape_root(), username)}` 已被占用或该名字非法。"
          f"请清理该目录（或改用配置里的 developer 用户名）后重启。")
