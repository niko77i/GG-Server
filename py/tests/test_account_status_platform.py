"""GG 账户状态字典必须按 platform='gg' 取行 —— 回归钉 + 存量归位。

起因（2026-10-06）：GG 侧读写 account_statuses 的 6 处 SQL 都写
`WHERE name=? AND owner_id=?`，**缺 platform 条件**。account_statuses 是
`UNIQUE(name, platform)` 的共享字典（gg / fb / tt 各有一行「存活」），
该唯一索引按 (name, platform) 排序 —— 'fb' < 'gg' < 'tt'，故 EXPLAIN 走
`SEARCH ... USING INDEX sqlite_autoindex_account_statuses_1 (name=?)` 后
fetchone() 稳定拿到 **fb** 那一行。生产实测：43 个 GG 账户的状态被写成
fb 的字典 id（status_id=25「存活」25 条、status_id=26「死亡」8 条）。

`owner_id` 条件同样是错的：字典行 owner_id 记的是**创建者**（生产全是 1），
普通用户拿自己的 id 去查永远查不到。两个后果本文各钉一组：

- 读侧（accounts_list 的 status 筛选）：普通用户按状态筛选结果恒为空
- 写侧（create / batch-create / sync 两处）：回退 INSERT 不带 platform，
  撞 `UNIQUE(name, platform)` 直接 500
- 存量侧：迁移把挂在非 gg 行上的 GG 账户归位到 gg 的同名行

⚠️ 清单筛选里那句 `AND platform='gg'`（与写侧同口径）在迁移生效后**不可单独
证伪** —— 迁移会把账户挪到 gg 行，此时 `name=?` 与 `name=? AND platform='gg'`
命中的是同一批 id。它是「按构造正确」的防御，不是本文的红钉。
"""
import os
import sys

_py_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _py_dir not in sys.path:
    sys.path.insert(0, _py_dir)

import database  # noqa: E402


# ---------- 夹具工具 ----------

def _register(client, username):
    """注册并登录一个普通用户，返回 (请求头, 用户 id)。"""
    client.post("/api/auth/register", json={"username": username, "password": "test123"})
    resp = client.post("/api/auth/login", json={"username": username, "password": "test123"})
    token = resp.get_json()["access_token"]
    db = database.get_db()
    uid = db.execute("SELECT id FROM users WHERE username=?", (username,)).fetchone()["id"]
    db.close()
    return {"Authorization": f"Bearer {token}"}, uid


def _mk_status(db, name, platform, owner_id=1):
    """建一条字典行，返回其 id。"""
    db.execute(
        "INSERT INTO account_statuses(name, owner_id, platform) VALUES(?,?,?)",
        (name, owner_id, platform),
    )
    db.commit()
    return db.execute(
        "SELECT id FROM account_statuses WHERE name=? AND platform=?", (name, platform)
    ).fetchone()["id"]


def _mk_account(db, account_id, owner_id, status_id):
    """直接落一条账户（绕过 API，便于精确构造 status_id）。"""
    db.execute(
        "INSERT INTO accounts(name, account_id, owner_id, status_id) VALUES(?,?,?,?)",
        (account_id, account_id, owner_id, status_id),
    )
    db.commit()


# ---------- 读侧：状态筛选 ----------

class TestStatusFilterDoesNotScopeByOwner:
    """`accounts_list` 的 status 筛选曾被 `owner_id=?` 收窄到「字典行的创建者」。

    字典行 owner_id 恒为创建者（生产 = developer），与「账户归属人」毫无关系，
    于是普通用户按「存活」筛选恒返回空列表。
    """

    def test_normal_user_sees_own_account_filtered_by_status(self, client):
        h_creator, uid_creator = _register(client, "creatoruser")
        h_user, uid_user = _register(client, "plainuser")
        assert uid_user != uid_creator

        db = database.get_db()
        # 字典行的 owner 是**别人**（生产里是 developer）—— 这正是旧 SQL 失配之处
        sid = _mk_status(db, "存活", "gg", owner_id=uid_creator)
        _mk_account(db, "111-111-1111", uid_user, sid)
        db.close()

        resp = client.get("/api/accounts/list?status=存活", headers=h_user)
        assert resp.status_code == 200
        ids = {a["account_id"] for a in resp.get_json()["accounts"]}
        assert "111-111-1111" in ids, (
            "普通用户按状态筛选查不到自己的账户 —— status 子查询仍被 owner_id 收窄"
        )

        # 对照腿：别人（creator）不该看到这个账户
        resp = client.get("/api/accounts/list?status=存活", headers=h_creator)
        ids = {a["account_id"] for a in resp.get_json()["accounts"]}
        assert "111-111-1111" not in ids, "归属隔离不得被本次改动打破"


# ---------- 写侧：文本状态回退 ----------

class TestCreateAccountBindsStatusTextToGgRow:
    """按 `status` 文本建户时，回退 INSERT 必须带 platform='gg'。

    旧实现先按 `owner_id=当前用户` 查（查不到，因为字典行 owner 是创建者），
    再 INSERT 不带 platform 的同名行 → 撞 `UNIQUE(name, platform)` → 500。
    """

    def test_normal_user_can_create_account_with_status_text(self, client):
        h, uid = _register(client, "creatoruser")
        db = database.get_db()
        gg_sid = _mk_status(db, "存活", "gg", owner_id=uid)
        db.close()

        h2, uid2 = _register(client, "plainuser")
        assert uid2 != uid
        resp = client.post(
            "/api/accounts/create",
            headers=h2,
            json={"name": "账户A", "account_id": "444-444-4444", "status": "存活"},
        )
        assert resp.status_code == 200, (
            "建户失败。旧实现里回退 INSERT 撞 UNIQUE(name, platform)，异常被通用分支"
            f"误报成「账户 ID 已存在」409：{resp.get_json()}"
        )

        db = database.get_db()
        row = db.execute(
            "SELECT status_id FROM accounts WHERE account_id='444-444-4444'"
        ).fetchone()
        db.close()
        assert row["status_id"] == gg_sid, "状态必须绑到 gg 的字典行，而不是新建一行"


# ---------- 存量侧：迁移归位 ----------

class TestAccountStatusPlatformMigration:
    """把挂在非 gg 平台字典行上的 GG 账户归位。"""

    def test_moves_account_from_fb_row_to_gg_row(self, client):
        _, uid = _register(client, "miguser")
        db = database.get_db()
        gg_sid = _mk_status(db, "存活", "gg", owner_id=1)
        fb_sid = _mk_status(db, "存活", "fb", owner_id=1)
        _mk_account(db, "555-555-5555", uid, fb_sid)

        database._migrate_account_status_platform(db)

        row = db.execute(
            "SELECT a.status_id, s.platform FROM accounts a "
            "LEFT JOIN account_statuses s ON a.status_id=s.id "
            "WHERE a.account_id='555-555-5555'"
        ).fetchone()
        db.close()
        assert row["status_id"] == gg_sid
        assert row["platform"] == "gg"

    def test_creates_gg_row_when_name_absent_there(self, client):
        """gg 没有同名行时**建一行**，不得把 status_id 置 NULL。"""
        _, uid = _register(client, "miguser2")
        db = database.get_db()
        fb_sid = _mk_status(db, "fb独有状态", "fb", owner_id=1)
        _mk_account(db, "666-666-6666", uid, fb_sid)

        database._migrate_account_status_platform(db)

        row = db.execute(
            "SELECT a.status_id, s.name, s.platform FROM accounts a "
            "LEFT JOIN account_statuses s ON a.status_id=s.id "
            "WHERE a.account_id='666-666-6666'"
        ).fetchone()
        db.close()
        assert row["status_id"] is not None, "不得置 NULL"
        assert row["name"] == "fb独有状态"
        assert row["platform"] == "gg"

    def test_does_not_kill_get_db_when_owner_fk_dangles(self, client, app):
        """迁移的异常绝不能逃出去打死 get_db()（`_migrate_if_needed` 每个请求都跑）。

        构造：某条 fb 字典行的 owner_id 指向已不存在的用户（跨库拷 app.db / 旧备份
        导入造出的悬挂外键）。此时补建 gg 行的 INSERT 会抛 FOREIGN KEY ——
        **`INSERT OR IGNORE` 不吞外键错**（SQLite 的 ON CONFLICT 算法不适用于
        FOREIGN KEY 约束）。若不包 try，此后每次 get_db() 都重抛，全站 500。
        """
        import sqlite3

        _, uid = _register(client, "fkuser")
        db = database.get_db()
        fb_sid = _mk_status(db, "悬挂状态", "fb", owner_id=uid)
        _mk_account(db, "999-999-9999", uid, fb_sid)
        db.close()

        # 绕过 get_db（它开了 foreign_keys=ON）造一条悬挂外键
        raw = sqlite3.connect(database._db_path())
        raw.execute("PRAGMA foreign_keys=OFF")
        raw.execute("UPDATE account_statuses SET owner_id=999999 WHERE id=?", (fb_sid,))
        raw.commit()
        raw.close()

        conn = database.get_db()  # 迁移在此跑；不得抛异常
        row = conn.execute(
            "SELECT a.status_id, s.platform FROM accounts a "
            "LEFT JOIN account_statuses s ON a.status_id=s.id "
            "WHERE a.account_id='999-999-9999'"
        ).fetchone()
        conn.close()
        # 本轮没归位是允许的（宁可不动，也不能打死服务）；关键是没抛且状态未变 NULL
        assert row["status_id"] == fb_sid
        assert row["platform"] == "fb"

    def test_leaves_gg_and_null_rows_alone(self, client):
        """已是 gg 行的、以及 status_id 为 NULL 的，都不动（幂等）。"""
        _, uid = _register(client, "miguser3")
        db = database.get_db()
        gg_sid = _mk_status(db, "存活", "gg", owner_id=1)
        _mk_account(db, "777-777-7777", uid, gg_sid)
        _mk_account(db, "888-888-8888", uid, None)
        before = db.execute("SELECT COUNT(*) FROM account_statuses").fetchone()[0]

        database._migrate_account_status_platform(db)
        database._migrate_account_status_platform(db)

        after = db.execute("SELECT COUNT(*) FROM account_statuses").fetchone()[0]
        rows = {
            r["account_id"]: r["status_id"]
            for r in db.execute(
                "SELECT account_id, status_id FROM accounts "
                "WHERE account_id IN ('777-777-7777','888-888-8888')"
            )
        }
        db.close()
        assert after == before, "无错挂数据时不得新增字典行"
        assert rows["777-777-7777"] == gg_sid
        assert rows["888-888-8888"] is None


# ---------- 空状态（status_id IS NULL）的统计口径 ----------

class TestUnknownStatusBucket:
    """`status_id IS NULL` 的账户：表格显示「未知」，统计与筛选也必须都是「未知」。

    旧实现统计里写 `COALESCE(st.name, '存活')`，把 NULL 计进「存活」计数；
    而按「存活」筛选走的是 `name=?` 子查询，筛不出这批行 —— 于是
    `status_counts` 的 key 又被前端直接渲染成状态按钮（`availableStatuses`
    取的就是它的 key），按钮上的数字与点开后的列表对不上。

    修法是把 NULL 桶命名为「未知」（与表格渲染的兜底文案一致），并让筛选一并
    认这个字面量 —— 统计与筛选必须同口径：**出现过的 key，点开都有同样多的行**。
    """

    def _setup(self, client):
        h, uid = _register(client, "unkuser")
        db = database.get_db()
        sid = _mk_status(db, "存活", "gg", owner_id=1)
        _mk_account(db, "101-000-0001", uid, sid)
        _mk_account(db, "101-000-0002", uid, None)
        _mk_account(db, "101-000-0003", uid, None)
        db.close()
        return h

    def test_null_rows_counted_as_unknown_not_alive(self, client):
        h = self._setup(client)
        counts = client.get("/api/accounts/list", headers=h).get_json()["status_counts"]
        assert counts.get("未知") == 2, "status_id 为 NULL 的账户必须单列「未知」"
        assert counts.get("存活") == 1, "「存活」计数不得再把 NULL 行算进来"

    def test_filtering_unknown_returns_the_null_rows(self, client):
        h = self._setup(client)
        resp = client.get("/api/accounts/list", query_string={"status": "未知"}, headers=h)
        ids = {a["account_id"] for a in resp.get_json()["accounts"]}
        assert ids == {"101-000-0002", "101-000-0003"}, (
            "统计里「未知」有几条，点开就该有几条 —— 否则这个按钮是死链"
        )

    def test_every_counted_key_filters_to_the_same_total(self, client):
        """不变式：`status_counts` 里出现过的每个 key，筛选结果条数必须与它相等。"""
        h = self._setup(client)
        counts = client.get("/api/accounts/list", headers=h).get_json()["status_counts"]
        assert counts, "前置条件：本夹具应至少产出一个状态桶"
        for name, cnt in counts.items():
            resp = client.get("/api/accounts/list", query_string={"status": name}, headers=h)
            assert resp.get_json()["total"] == cnt, (
                f"「{name}」计数 {cnt}，按它筛选却得到 {resp.get_json()['total']} 条"
            )

    def test_real_dict_row_named_unknown_is_merged_not_lost(self, client):
        """真有一行叫「未知」的字典行时：统计合并两条来源，筛选也要同时给出两批。

        避免「名字撞车 ⇒ 其中一批行在按钮上计了数、却永远筛不出来」。
        """
        h, uid = _register(client, "unkuser2")
        db = database.get_db()
        real_sid = _mk_status(db, "未知", "gg", owner_id=1)
        _mk_account(db, "202-000-0001", uid, real_sid)   # 绑到真的「未知」字典行
        _mk_account(db, "202-000-0002", uid, None)       # status_id 为 NULL
        db.close()

        counts = client.get("/api/accounts/list", headers=h).get_json()["status_counts"]
        assert counts.get("未知") == 2, "两条来源应合并到同一个 key"

        resp = client.get("/api/accounts/list", query_string={"status": "未知"}, headers=h)
        ids = {a["account_id"] for a in resp.get_json()["accounts"]}
        assert ids == {"202-000-0001", "202-000-0002"}, (
            "合并计数了，筛选就必须把两批行都给出"
        )
