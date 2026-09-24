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


class TestOrphanScrapeDirsAreTombstoned:
    """磁盘上「不属于任何存活用户」的爬取目录，迁移时必须补哨兵墓碑。

    挡的是哪一档（2026-09-24，code-review 第 6 轮第 1 条，用户裁定「改判据」）：
    `scrape_dn_history` 上线**之前**就已删掉的用户，既没有 users 行、也没来得及写
    墓碑行 —— 他的目录留在盘上却**完全无主**，`_dn_released_keys` 看不见它，于是
    「曾用名含该目录名」的人可以认领并读到产物。补一行哨兵即可让该名字永久不可认领。

    ⚠️ `_scrape_root()` 指向**真实**的 `temp/scraped_images`（测试没有把它隔离到 tmp），
    故本类**只**对自己造的、名字唯一可控的目录做断言；对真实残留目录（如仓库里
    遗留的 `alice`/`alice2`）不置一词 —— 断言别的东西会被环境污染成假绿/假红。
    """

    @pytest.fixture
    def root(self):
        """真实爬取根 + 一个用完就删的临时子目录名。"""
        r = auth._scrape_root()
        name = "_orph_tb_probe"
        path = os.path.join(r, name)
        shutil.rmtree(path, ignore_errors=True)
        yield r, name, path
        shutil.rmtree(path, ignore_errors=True)

    def _rerun(self, conn):
        """把「一次性」标记清掉，好让本用例能重复触发扫描。"""
        conn.execute("DELETE FROM config WHERE key='tombstoned_orphan_scrape_dirs'")
        conn.commit()

    def test_orphan_dir_gets_sentinel_and_cannot_be_claimed(self, db, root):
        """承重：无主目录 ⇒ 补哨兵 ⇒ 曾用名含它的人认领不到（而这是产物读路径）。

        ⚠️ **本条同时钉住一个被接受的代价**（code-review 第 6 轮收口第 1 条，详见
        设计文档 §0.12「两裁定的相互作用」）：V 在这里的形态 = 「**存活**用户，曾释放过
        该名，目录还在盘上」—— 即「我自己的旧目录」。哨兵把它一并封掉，于是 V 改不回
        原名、旧目录里的产物在盘上却取不回（MEDIUM-1 的症状）。

        为什么**必须**接受：本用例的 V 与「攻击者」在数据上**完全同形** —— 攻击者要拿到
        该名，前提正是他**也**有一行同名释放记录（否则判据 3「目录已占用」直接拒，除
         `own_keys`/`hist_keys` 两条豁免外无路可走，见 `auth.directory_name_error:355`）。
        于是任何「把 `scrape_dn_history` 里出现过的名字排除在扫描之外」的写法，都会**恰好
        放过每一条可被利用的名字** ⇒ 扫描退化成空操作、缺口原样复活。
        两档不可区分（被删用户升级前没有行，与「只有我一行」在表上长得一样），
        按本项目一贯的 fail-closed（误放 > 误拒）取「封」。

        代价的实际规模：扫描**只跑一次**，故只影响「本次上线**之前**就已改名、且想改回去」
        的用户；live 库扫描时 `scrape_dn_history` 为 **0 行**（实测），即当前 **0 人**受影响。
        """
        conn = db
        r, name, path = root
        os.makedirs(path, exist_ok=True)
        # 造一个「曾用名含该目录名」的存活用户：没有哨兵时他会认领到该目录
        uid_v = conn.execute(
            "INSERT INTO users(username, password) VALUES('_orph_v', 'x')").lastrowid
        conn.execute("INSERT INTO scrape_dn_history(user_id, dn) VALUES(?, ?)", (uid_v, name))
        conn.commit()
        # 夹具前提：此刻还没有哨兵，且该名**确实**判给了 V —— 否则下面的「拒」
        # 可能来自别的原因（比如名字压根没进判据），断言就成了假绿。
        assert _sentinel_rows(conn, name) == 0
        assert name in auth._dn_released_keys(conn, uid_v), (
            "夹具前提不成立：扫描前该名字没判给 V，本用例测不到「哨兵把它挡下来」"
        )

        self._rerun(conn)
        database._tombstone_orphan_scrape_dirs(conn)

        assert _sentinel_rows(conn, name) == 1, "无主目录没被补哨兵墓碑"
        assert name not in auth._dn_released_keys(conn, uid_v), (
            "补了哨兵却仍能被认领 —— 哨兵没有真正硬闸（产物读路径仍然敞开）"
        )

    def test_missing_scrape_root_does_not_consume_the_one_shot(self, db, tmp_path,
                                                              monkeypatch):
        """承重：爬取根**不存在**时不得写一次性标记。

        否则升级时「先起服务、后拷爬取目录」（或全新部署首次 get_db() 早于建目录）
        会把唯一的一次机会空转掉，此后补上的目录再也补不上哨兵 —— 缺口原样复活。
        这与函数自称的「不打标记，下次重试」是同一个契约（code-review 第 6 轮收口第 2 条）。
        """
        conn = db
        monkeypatch.setattr(auth, "_scrape_root",
                            lambda: str(tmp_path / "_no_such_scrape_root"))
        conn.execute("DELETE FROM config WHERE key='tombstoned_orphan_scrape_dirs'")
        conn.commit()

        database._tombstone_orphan_scrape_dirs(conn)

        mark = conn.execute("SELECT value FROM config "
                            "WHERE key='tombstoned_orphan_scrape_dirs'").fetchone()
        assert mark is None, (
            "爬取根不存在却把一次性标记用掉了 —— 之后目录补上也不会再扫，墓碑永远缺席"
        )

    def test_live_users_directory_is_not_tombstoned(self, db, root):
        """对照腿：**有主**的目录一个哨兵都不补（否则会误伤活人自己的产物）。

        少了这条，把扫描写成「根下每个目录都补哨兵」也会让上面那条绿 ——
        而那样做会让所有用户都取不回自己的产物。
        """
        conn = db
        r, name, path = root
        os.makedirs(path, exist_ok=True)
        # 让**存活用户**的真实目录名恰好等于这个名字
        uid_live = conn.execute(
            "INSERT INTO users(username, password, display_name) VALUES(?, 'x', ?)",
            ("_orph_live", name)).lastrowid
        conn.commit()
        assert auth._dir_name_of(uid_live, "_orph_live", name) == name, (
            "夹具前提不成立：存活用户的实际目录名与磁盘上的目录不一致"
        )

        self._rerun(conn)
        database._tombstone_orphan_scrape_dirs(conn)

        assert _sentinel_rows(conn, name) == 0, (
            "把活人自己的目录也补了哨兵 —— 该用户从此取不回自己的产物"
        )

    def test_scan_is_one_shot(self, db, root):
        """标记必须在，否则每次进程启动都全量扫一遍根目录并重复插哨兵。"""
        conn = db
        r, name, path = root
        os.makedirs(path, exist_ok=True)
        conn.execute("DELETE FROM config WHERE key='tombstoned_orphan_scrape_dirs'")
        conn.commit()

        database._tombstone_orphan_scrape_dirs(conn)
        assert _sentinel_rows(conn, name) == 1
        mark = conn.execute("SELECT value FROM config "
                            "WHERE key='tombstoned_orphan_scrape_dirs'").fetchone()
        assert mark is not None and mark[0] == "1", f"标记没写上：{mark}"

        database._tombstone_orphan_scrape_dirs(conn)
        assert _sentinel_rows(conn, name) == 1, "扫描不幂等：同一个目录被补了多次哨兵"

    def test_scan_is_wired_into_migration(self, db, root):
        """接线腿：扫描必须真的挂在迁移入口上。

        上面三条都是**直调函数** —— 把 `_migrate_if_needed` 里那一行调用删掉，
        它们照样全绿，而线上再也不会补墓碑、整个保护静默消失。
        """
        conn = db
        _r, name, path = root
        os.makedirs(path, exist_ok=True)
        conn.execute("DELETE FROM config WHERE key='tombstoned_orphan_scrape_dirs'")
        conn.commit()

        database._migrate_if_needed(conn)

        assert _sentinel_rows(conn, name) == 1, (
            "迁移入口没有再调用无主目录扫描 —— 接线断了，墓碑永远不会补"
        )
