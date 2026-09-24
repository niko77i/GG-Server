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
