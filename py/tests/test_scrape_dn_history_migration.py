"""`users.prev_scrape_dns`（JSON）→ `scrape_dn_history` 表的一次性迁移测试。

## 为什么必须单独测这一段

迁移的「搬数据 + DROP COLUMN」路径**只在真实库上跑一次**，而所有其它测试用的都是
**全新**临时库 —— 新库里根本没有 `prev_scrape_dns` 这个列，迁移只会走「列不存在 ⇒
直接打标记返回」那一支。也就是说：**不写本文件，迁移的核心分支一行都没被执行过**，
而它跑在唯一一份真实数据上（迁移失败或搬错，用户的曾用名记录就永久丢了，且删掉的
列没有任何回退路径）。

## 夹具怎么造出「迁移前的库」

不手抄一份旧 schema（手抄必然与真实 schema 漂移，就测不出真东西了）。改为：
  1. `get_db()` 建立**当前**完整 schema；
  2. 把 `prev_scrape_dns` 列**加回来**并填上 JSON（即迁移前的样子）；
  3. 清掉迁移标记；
  4. 直接调 `_migrate_scrape_dn_history`。
这样走的是生产代码的**同一条路径**，且不依赖任何手抄的 DDL。
"""
import os
import shutil
import time

import pytest

import auth
import database


@pytest.fixture
def db(client):
    """client 只为触发 app 夹具（把 database._db_path 指向临时库）。"""
    conn = database.get_db()
    yield conn
    conn.close()


def _pre_migration(conn):
    """把库倒回「迁移前」：列加回来、标记清掉。返回 (uid_p, uid_q)。"""
    conn.execute("ALTER TABLE users ADD COLUMN prev_scrape_dns TEXT DEFAULT ''")
    conn.execute("DELETE FROM config WHERE key='migrated_scrape_dn_history'")
    uid_p = conn.execute(
        "INSERT INTO users(username, password, display_name, prev_scrape_dns) "
        "VALUES('_mg_p', 'x', '_mg_p', ?)", ('["_mg_old1", "_mg_old2"]',)).lastrowid
    uid_q = conn.execute(
        "INSERT INTO users(username, password, display_name, prev_scrape_dns) "
        "VALUES('_mg_q', 'x', '_mg_q', ?)", ('["_mg_x"]',)).lastrowid
    # 坏值行：非 JSON —— 必须被跳过，且不得中断其余用户的搬运
    uid_bad = conn.execute(
        "INSERT INTO users(username, password, display_name, prev_scrape_dns) "
        "VALUES('_mg_bad', 'x', '_mg_bad', ?)", ('not json at all',)).lastrowid
    conn.commit()
    return uid_p, uid_q, uid_bad


def _hist(conn, uid):
    return [r[0] for r in conn.execute(
        "SELECT dn FROM scrape_dn_history WHERE user_id = ? ORDER BY id", (uid,)).fetchall()]


def test_migration_moves_history_in_release_order_and_drops_column(db):
    conn = db
    uid_p, uid_q, uid_bad = _pre_migration(conn)
    assert "_mg_old1" not in _hist(conn, uid_p), "夹具前提不成立：迁移前不该已有新表数据"

    database._migrate_scrape_dn_history(conn)

    # 1) 顺序必须与 JSON 数组顺序一致（数组顺序 = 释放先后，认领判据靠它）
    assert _hist(conn, uid_p) == ["_mg_old1", "_mg_old2"], (
        f"搬运顺序/内容不对：{_hist(conn, uid_p)!r}"
    )
    assert _hist(conn, uid_q) == ["_mg_x"]
    # 2) 坏值被跳过，且**不**影响其它行（整段不因它中断）
    assert _hist(conn, uid_bad) == []
    # 3) 旧列必须真的删掉 —— 否则新写入方（auth.update_user）只写表不写列，
    #    该列会永远停在迁移那一刻的旧值上，成为一颗定时炸弹
    cols = [r[1] for r in conn.execute("PRAGMA table_info(users)").fetchall()]
    assert "prev_scrape_dns" not in cols, f"旧列没删掉：{cols}"
    # 4) 生成列与唯一索引不受 DROP COLUMN 影响（DROP 会重建表，最易在这里出事）
    assert "scrape_dn" in [r[1] for r in conn.execute("PRAGMA table_xinfo(users)")], (
        "DROP COLUMN 把 scrape_dn 生成列一起弄丢了 —— 目录名唯一约束会随之失效"
    )


def test_migrated_rows_drive_last_writer_wins_in_order(db):
    """只被**一个**人提到过的名字没有歧义 ⇒ 判给他（否则旧数据取不回自己的产物）。"""
    conn = db
    uid_p, uid_q, _uid_bad = _pre_migration(conn)
    database._migrate_scrape_dn_history(conn)
    # 另加一个 P 独有的名字（模拟真实历史上「改名离开」）
    conn.execute("INSERT INTO scrape_dn_history(user_id, dn) VALUES(?, ?)", (uid_p, "_mg_only_p"))
    conn.commit()

    keys_p = auth._dn_released_keys(conn, uid_p)
    assert "_mg_only_p" in keys_p, "只有某人释放过的名字应判给他"
    # 无歧义的迁移行同理（_mg_old1/_mg_old2 只出现在 P 的历史里）
    assert {"_mg_old1", "_mg_old2"} <= keys_p, f"P 独有名字未判给 P：{keys_p}"
    assert "_mg_x" not in keys_p
    assert "_mg_x" in auth._dn_released_keys(conn, uid_q)


def test_ambiguous_name_from_old_format_is_given_to_nobody(db):
    """承重：**被 ≥2 人的历史同时提到**的名字，迁移后必须谁也不给（fail-closed）。

    为什么不能按 users.id 顺序「猜」一个先后：JSON 里没有时间戳，真实先后无法还原，
    猜反的方向是**误放** —— 先释放的人反倒成了「最后持有者」，于是他能认领那个目录、
    读到别人留在里面的产物（正是 Important #2 那一档读路径）。故插 user_id=0 的哨兵，
    使每个真实用户对这一档都退回修复前的「拒」。

    没有这条，删掉哨兵那段代码不会有任何用例转红 —— 而它挡的是**读到别人产物**。
    """
    conn = db
    uid_p, uid_q, _uid_bad = _pre_migration(conn)
    # P 与 Q 的历史里都有同一个名字 `_mg_amb`（真实形态：P 用过后离开、Q 接手）。
    # Q 的历史里**保留** `_mg_x` —— 它是「无歧义」的对照行。
    conn.execute("UPDATE users SET prev_scrape_dns = ? WHERE id = ?",
                 ('["_mg_amb"]', uid_p))
    conn.execute("UPDATE users SET prev_scrape_dns = ? WHERE id = ?",
                 ('["_mg_x", "_mg_amb"]', uid_q))
    conn.commit()

    database._migrate_scrape_dn_history(conn)

    assert "_mg_amb" not in auth._dn_released_keys(conn, uid_p), (
        "跨用户先后无法还原却把名字判给了 P —— 判反就会认领到别人的产物目录"
    )
    assert "_mg_amb" not in auth._dn_released_keys(conn, uid_q), (
        "跨用户先后无法还原却把名字判给了 Q"
    )
    # 对照：同一次迁移里**无歧义**的名字仍照常判给本人（哨兵没有一刀切全冻住）
    assert {"_mg_x"} <= auth._dn_released_keys(conn, uid_q)
def test_migration_sentinel_blocks_the_dir_it_judged(db):
    """承重（**效果级**）+ 钉住**亚秒**：迁移时**已存在**的歧义名目录，必须被迁移写下的哨兵拦住。

    为什么单列一条（2026-09-25，code-review 第 7 轮 Important #1）：迁移那两处 INSERT 原先
    都吃表的默认值 `datetime('now')`（**秒级、向下截断**）。同一截断方向在**释放行**上是
    fail-closed（`ts > ctime` 更难成立 ⇒ 更严），在**哨兵**上却是 **fail-open** ——
    哨兵判据是 `ts >= ctime`，时刻被截小就拦不住它当年所判的那个化身，于是
    「同一秒内先建目录、后跑迁移」会把这条歧义名悄悄放开。

    构型就是那一档：目录先建好，迁移随后写哨兵（两者几乎必然落在同一秒）。
    两条断言各钉一头：
      · `ts > int(ts)` —— 迁移写下的哨兵行**必须带亚秒**（与时钟无关，确定性强）；
      · `_sentinel_row_blocks_dir(name, ts) is True` —— 效果：它拦得住那个化身。
        这条只在「目录与迁移同秒」时对秒级截断敏感（跨秒时退化为恒真，**不会假红**）。
    """
    conn = db
    name = "_mg_amb_dir"
    path = os.path.join(auth._scrape_root(), name)
    shutil.rmtree(path, ignore_errors=True)
    uid_p, uid_q, _uid_bad = _pre_migration(conn)
    # ⚠️ 为什么不能「紧挨着建目录就调迁移」（首版正是这么写，假红）：
    # SQLite 的 `now` 与文件系统时钟之间有**毫秒级抖动**（自测 300 次采样：-0.2ms ~ +0.8ms，
    # 跨零），于是「目录 ctime 反而晚于哨兵时刻」是**合法**情形，`ts >= ctime` 并不必然成立。
    # 改为确定性构造：先把当前这一秒「用掉」，再建目录、睡 50ms —— 于是
    #   ① 目录与迁移**必在同一秒**（除非 sleep 超 1s，不可能）；
    #   ② 抖动（≤1ms）远小于 50ms ⇒ 修复后 `ts > ctime` 必成立。
    # 两个方向都确定，不靠机器快慢。
    now = time.time()
    time.sleep(1.0 - (now - int(now)) + 0.02)
    os.makedirs(path)
    time.sleep(0.05)
    try:
        conn.execute("UPDATE users SET prev_scrape_dns = ? WHERE id = ?",
                     ('["%s"]' % name, uid_p))
        conn.execute("UPDATE users SET prev_scrape_dns = ? WHERE id = ?",
                     ('["%s"]' % name, uid_q))
        conn.commit()

        database._migrate_scrape_dn_history(conn)

        row = conn.execute(
            "SELECT created_at FROM scrape_dn_history WHERE user_id = ? AND dn = ?",
            (auth._DN_SENTINEL_UID, name)).fetchone()
        assert row is not None, "夹具前提：歧义名应当被补一行哨兵"
        ts = auth._parse_utc_ts(row[0])
        assert ts is not None, f"哨兵行时刻解析不出：{row[0]!r}"
        assert ts > float(int(ts)), (
            f"迁移写下的哨兵行没有亚秒（{row[0]!r}）—— 秒级截断对哨兵是 **fail-open** 方向，"
            "会把「同一秒内先建目录、后跑迁移」的歧义名悄悄放开"
        )
        assert auth._dir_ctime(name) is not None, "夹具前提：目录应当存在"
        assert auth._sentinel_row_blocks_dir(name, ts) is True, (
            f"迁移写下的哨兵（{row[0]!r}）拦不住它当年所判的那个目录"
        )
    finally:
        shutil.rmtree(path, ignore_errors=True)


def test_migration_is_idempotent(db):
    """标记置上后再跑一次不得重复搬运 —— 重复会让同一个名字凭空多出几行、
    序号被推高，从而把「谁最后释放」的判据弄反。"""
    conn = db
    uid_p, _uid_q, _uid_bad = _pre_migration(conn)
    database._migrate_scrape_dn_history(conn)
    before = conn.execute("SELECT COUNT(*) FROM scrape_dn_history").fetchone()[0]

    # 契约一：标记必须真的写上了。少了这条断言，本用例是**假绿** —— 即便删掉写标记
    # 那行，第二次调用也会走「列已不存在 ⇒ 直接返回」那一支而不再搬运，行数照样不变。
    mark = conn.execute("SELECT value FROM config "
                        "WHERE key='migrated_scrape_dn_history'").fetchone()
    assert mark is not None and mark[0] == "1", f"迁移标记没写上：{mark}"

    database._migrate_scrape_dn_history(conn)
    after = conn.execute("SELECT COUNT(*) FROM scrape_dn_history").fetchone()[0]

    assert before == after, f"迁移不幂等：行数 {before} → {after}"
    assert _hist(conn, uid_p) == ["_mg_old1", "_mg_old2"]


def _sentinel_rows(conn, dn):
    """该名字上的**哨兵**行数（必须限定 user_id：表里同时装着真实用户的释放行）。"""
    return conn.execute(
        "SELECT COUNT(*) FROM scrape_dn_history WHERE user_id = ? AND dn = ?",
        (auth._DN_SENTINEL_UID, dn)).fetchone()[0]


class TestScanRetirementAndSentinelIncarnations:
    """无主目录扫盘**退役** + 哨兵改为「按化身处境」判（2026-09-25，设计文档 §0.13）。

    用户裁定「换判据：加时间维度」后，`database._tombstone_orphan_scrape_dirs`
    ——「扫一次盘、给不属于任何存活用户的目录名补哨兵墓碑」—— **整段删除**。

    它当年之所以把这一档一刀切封死，是因为认领判据**没有时间维度**：「被删用户留下的
    目录」与「我自己的旧目录」在数据上完全同形（§0.12 收口 1），只能取严；而它写下的
    永久硬闸把「目录被清理后重建、本人想改回原名」这条路一并封了。判据升级为
    「我的最后释放时刻 > 该目录创建时刻」之后，这一档由**判据本身**接住；
    它当年写下的哨兵行留在表里，新判据只让它们对**当年所判的那个化身**生效。

    ⚠️ 本类必须同时钉住三件事，缺一就是把「换判据」做成了「拆保护」：
      ① 无主目录**仍然**认领不到（改由判据 3 接住）—— 它正是产物越权读的入口；
      ② 迁移入口**不再**补哨兵（否则扫盘换个写法又活过来）；
      ③ 当年补下的哨兵行仍对它当年所判的化身生效（live 的 `alice` / `alice2` 靠它）。

    ⚠️ `_scrape_root()` 指向**真实**的 `temp/scraped_images`（测试没有把它隔离到 tmp），
    故本类**只**对自己造的、名字唯一可控的目录做断言；对真实残留目录（如仓库里
    遗留的 `alice`/`alice2`）不置一词 —— 断言别的东西会被环境污染成假绿/假红。
    """

    NAME = "_orph_r8"

    @pytest.fixture
    def orphan(self):
        """真实爬取根 + 一个用完就删的临时子目录。"""
        r = auth._scrape_root()
        path = os.path.join(r, self.NAME)
        shutil.rmtree(path, ignore_errors=True)
        yield r, self.NAME, path
        shutil.rmtree(path, ignore_errors=True)

    @staticmethod
    def _row(conn, uid, dn, offset=None):
        """插一行释放 / 哨兵记录。

        `offset=None` ⇒ **当前**时刻且带**亚秒**（与生产写入方
        `auth.note_scrape_dn_release` 同款）；否则用 SQLite 时间修饰符（如
        `-60 seconds`）把行时刻推到过去，用来构造「行早于目录创建」的形态。
        """
        if offset is None:
            conn.execute("INSERT INTO scrape_dn_history(user_id, dn, created_at) "
                         "VALUES(?, ?, strftime('%Y-%m-%d %H:%M:%f','now'))", (uid, dn))
        else:
            conn.execute("INSERT INTO scrape_dn_history(user_id, dn, created_at) "
                         "VALUES(?, ?, datetime('now', ?))", (uid, dn, offset))

    @staticmethod
    def _new_user(conn, username):
        return conn.execute("INSERT INTO users(username, password) VALUES(?, 'x')",
                            (username,)).lastrowid

    def test_migration_no_longer_tombstones_orphan_dirs(self, db, orphan):
        """接线腿（效果级）：跑一遍迁移入口，无主目录**不得**再被补哨兵。

        写成「效果」而不是「代码里没有那行调用」：函数已整段删除，任何形式的复活
        （重新实现、换个名字重挂）都会让本用例转红。
        """
        conn = db
        _r, name, path = orphan
        os.makedirs(path, exist_ok=True)
        # 一次性标记清掉 —— 若扫描还在，这一轮**就会**跑起来并补上哨兵
        conn.execute("DELETE FROM config WHERE key='tombstoned_orphan_scrape_dirs'")
        conn.commit()
        assert _sentinel_rows(conn, name) == 0, "夹具前提：此刻不该有哨兵行"

        database._migrate_if_needed(conn)

        assert _sentinel_rows(conn, name) == 0, (
            "迁移入口又给无主目录补了哨兵 —— 扫盘复活了（§0.13 已把它退役）"
        )

    def test_orphan_dir_is_still_not_claimable(self, db, orphan):
        """承重（退役后保护仍在）：无主目录 + 我**没有**该名字的覆盖行 ⇒ 仍拒。

        少了这条，「扫盘退役」就可能是「把这一档放开」—— 而这一档正是被删用户产物的
        读路径（越权读）。正确性就在这里：无主目录由**判据 3**（目录存在，且既不在
        `own_keys` 也不在 `hist_keys` 里）自己接住，不需要哨兵。
        """
        conn = db
        _r, name, path = orphan
        os.makedirs(path, exist_ok=True)
        uid = self._new_user(conn, "_orph_r8_x")
        conn.commit()

        assert auth.directory_name_error(uid, None, name) == (
            "该名字对应的爬取目录已被占用，请换一个"
        ), "无主目录在扫盘退役后变成可认领了 —— 越权读路径原样复活"

    def test_old_sentinel_still_blocks_on_the_incarnation_it_judged(self, db, orphan):
        """承重（兼容 live 的 `alice` / `alice2`）：哨兵行晚于目录创建 ⇒ 照旧硬闸。

        与下一条**成对**：单看任何一条，「哨兵一律失效」与「哨兵一律有效」都能蒙过去，
        而两者之一必然是错的。
        """
        conn = db
        _r, name, path = orphan
        os.makedirs(path, exist_ok=True)
        uid = self._new_user(conn, "_orph_r8_y")
        # 用**显式未来时刻**构造「行晚于目录创建」：`strftime('%f')` 只到毫秒且是
        # 截断，同一毫秒内建目录 + 插行会被判成「行更早」（生产路径不会同毫秒，
        # 见 §0.13 残余风险 4）。显式时刻让本用例只测判据、不测时钟。
        self._row(conn, uid, name, "+60 seconds")
        conn.commit()
        # 夹具前提：此刻该名**确实**判给我 —— 否则下面的「拒」可能来自别的原因（假绿）
        assert auth.directory_name_error(uid, None, name) is None, (
            "夹具前提不成立：我的覆盖行没有让该名判给我，后面测不到哨兵"
        )

        self._row(conn, auth._DN_SENTINEL_UID, name, "+60 seconds")   # 当年扫盘补的哨兵
        conn.commit()

        assert auth.directory_name_error(uid, None, name) == (
            "该名字对应的爬取目录已被占用，请换一个"
        ), "哨兵对它当年所判的化身失效了 —— live 的 alice/alice2 保护被拆掉"

    def test_old_sentinel_does_not_block_a_rebuilt_incarnation(self, db, orphan):
        """承重（本轮修复的正题）：目录在哨兵**之后**重建 ⇒ 旧哨兵不再拦。

        目录被清掉重建后 `ctime` 更新，哨兵那一刻早于当前化身 ⇒ 它对当前化身没有说话
        权，该名交由释放行的覆盖判据裁决。少了这条，「哨兵永久硬闸」会把「目录被清理后
        重建、本人想改回原名」这条路封死 —— 正是 §0.12 收口 1 记下的代价。
        """
        conn = db
        _r, name, path = orphan
        uid = self._new_user(conn, "_orph_r8_z")
        # 哨兵行写在**前**（老化身：当时目录还不存在），目录在后
        self._row(conn, auth._DN_SENTINEL_UID, name, "-60 seconds")
        conn.commit()
        os.makedirs(path, exist_ok=True)
        self._row(conn, uid, name, "+60 seconds")       # 覆盖行晚于新化身
        conn.commit()

        assert name in auth._dn_released_keys(conn, uid), (
            "目录已在其后重建，旧哨兵却仍在硬闸 —— 名字被永久封死"
        )
        assert auth.directory_name_error(uid, None, name) is None, (
            "判据内部放行了，但闸门仍拒 —— 本人的认领路没有真正恢复"
        )

    def test_sentinel_dirty_row_still_blocks(self, db, orphan):
        """承重（纯函数）：时刻**解析不出**的哨兵行照拦（fail-closed）。

        与释放行的同一档相反（那边取「不覆盖」），两侧一起才是 fail-closed。少这条，
        把 `_sentinel_row_blocks_dir` 的 `ts is None → True` 翻成 `False`
        （脏行当成「没说过话」）不会有任何用例转红。
        """
        _r, name, path = orphan
        os.makedirs(path, exist_ok=True)
        assert auth._dir_ctime(name) is not None, "夹具前提：目录应当存在"
        assert auth._sentinel_row_blocks_dir(name, None) is True, (
            "时刻解析不出的哨兵行被放行了 —— 脏行必须落在拦的一侧"
        )

    def test_sentinel_tie_takes_the_blocking_side(self, db, orphan):
        """承重（纯函数、不碰时钟）：哨兵的 tie（`ts == ctime`）取**拦**。

        两侧的 tie 都朝 fail-closed 倒：释放行的 tie 取「不覆盖」（不放开认领），
        哨兵的 tie 取「拦」（不放行）。少了这条，把哨兵的 `>=` 写成 `>` 不会有任何用例
        转红 —— 而 tie 正是「目录与哨兵在同一刻、说不清谁先」的形态。
        """
        _r, name, path = orphan
        os.makedirs(path, exist_ok=True)
        ctime = auth._dir_ctime(name)
        assert ctime is not None, "夹具前提：目录应当存在"
        assert auth._sentinel_row_blocks_dir(name, ctime) is True, (
            "哨兵与目录同一时刻却被判成不拦 —— tie 必须落在拦的一侧"
        )
        assert auth._sentinel_row_blocks_dir(name, ctime - 0.001) is False, (
            "早 1ms 的哨兵也被判成拦 —— 目录重建后旧哨兵永远失效不了"
        )
