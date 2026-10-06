"""FB 资产数据模型（子项目 ①）测试。

设计见 docs/superpowers/specs/2026-10-06-fb-asset-data-model-design.md。
"""
import sqlite3

import pytest

import database


def _cols(conn, table):
    """PRAGMA table_info → {列名: 类型}。"""
    return {r[1]: r[2] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()}


@pytest.fixture
def two_users(client):
    """两个 FB 平台用户，用于验证「词表唯一性按 (name, platform)，不按 owner」。"""
    db = database.get_db()
    for name in ("u_alpha", "u_beta"):
        db.execute("INSERT INTO users(username, password, role, platform) "
                   "VALUES(?, 'x', 'user', 'fb')", (name,))
    db.commit()
    ids = [r[0] for r in db.execute(
        "SELECT id FROM users WHERE username IN ('u_alpha','u_beta') "
        "ORDER BY username").fetchall()]
    db.close()
    return ids


def _seed_bm_pair_and_account(db, owner_id):
    """建两个 BM 与一个 FB 账户，返回 (bm1, bm2, account_pk)。"""
    db.execute("INSERT INTO fb_bms(name, bm_id, owner_id) VALUES('BM甲','bm1',?)", (owner_id,))
    bm1 = db.execute("SELECT last_insert_rowid()").fetchone()[0]
    db.execute("INSERT INTO fb_bms(name, bm_id, owner_id) VALUES('BM乙','bm2',?)", (owner_id,))
    bm2 = db.execute("SELECT last_insert_rowid()").fetchone()[0]
    db.execute("INSERT INTO fb_accounts(name, account_id, owner_id) VALUES('户甲','1001',?)",
               (owner_id,))
    acc = db.execute("SELECT last_insert_rowid()").fetchone()[0]
    return bm1, bm2, acc


class TestFbAccountColumns:
    def test_ten_new_columns_exist(self, client):
        db = database.get_db()
        cols = _cols(db, "fb_accounts")
        db.close()
        expected = {
            "operator": "TEXT",
            "channel_id": "INTEGER",
            "asset_type_id": "INTEGER",
            "unit_price": "TEXT",
            "inbound_qty": "TEXT",
            "acceptor_id": "INTEGER",
            "outbound_date": "TEXT",
            "outbound_qty": "TEXT",
            "consumption": "TEXT",
            "remark": "TEXT",
        }
        for col, affinity in expected.items():
            assert col in cols, f"fb_accounts 缺列 {col}"
            assert cols[col] == affinity, f"{col} 期望 {affinity}，实际 {cols[col]}"

    def test_new_columns_default_empty_for_existing_rows(self, client, two_users):
        """存量行取默认值：空串 / NULL，行为与改动前一致。"""
        db = database.get_db()
        _, _, acc = _seed_bm_pair_and_account(db, two_users[0])
        db.commit()
        row = db.execute("SELECT * FROM fb_accounts WHERE id=?", (acc,)).fetchone()
        db.close()
        assert row["operator"] == ""
        assert row["remark"] == ""
        assert row["unit_price"] == ""
        assert row["channel_id"] is None

    def test_migration_is_idempotent(self, client):
        """_ensure_columns 每次连库都跑，连两次不得报错。"""
        db1 = database.get_db()
        db1.close()
        db2 = database.get_db()
        cols = _cols(db2, "fb_accounts")
        db2.close()
        assert "remark" in cols


class TestSharedOptionTables:
    def test_tables_exist_with_expected_columns(self, client):
        db = database.get_db()
        for t in ("fb_channels", "fb_asset_types"):
            cols = _cols(db, t)
            assert "name" in cols, t
            assert "owner_id" in cols, t
            assert "platform" in cols, t
            assert "created_at" in cols, t
        db.close()

    def test_name_unique_per_platform_not_per_owner(self, client, two_users):
        """唯一性是 (name, platform) —— 甲、乙建同名渠道只能落一行。

        这正是设计不复用 `agents` 的理由：agents 的 UNIQUE 含 owner_id，
        同名会落两行，而「唯一命中才落库」的口径下那一列会永远同步不上。
        """
        db = database.get_db()
        db.execute("INSERT INTO fb_channels(name, owner_id, platform) VALUES('渠道A', ?, 'fb')",
                   (two_users[0],))
        db.commit()
        with pytest.raises(sqlite3.IntegrityError):
            db.execute("INSERT INTO fb_channels(name, owner_id, platform) VALUES('渠道A', ?, 'fb')",
                       (two_users[1],))
        db.rollback()
        n = db.execute("SELECT COUNT(*) FROM fb_channels WHERE name='渠道A'").fetchone()[0]
        db.close()
        assert n == 1

    def test_same_name_allowed_on_other_platform(self, client, two_users):
        """platform 是唯一性的一部分：gg 上可以有同名。"""
        db = database.get_db()
        db.execute("INSERT INTO fb_channels(name, owner_id, platform) VALUES('渠道A', ?, 'fb')",
                   (two_users[0],))
        db.execute("INSERT INTO fb_channels(name, owner_id, platform) VALUES('渠道A', ?, 'gg')",
                   (two_users[0],))
        db.commit()
        n = db.execute("SELECT COUNT(*) FROM fb_channels WHERE name='渠道A'").fetchone()[0]
        db.close()
        assert n == 2


class TestPrimaryBm:
    def test_switching_primary_bm_succeeds(self, client, two_users):
        """换 BM 必须成功：同一事务内先清后设。"""
        db = database.get_db()
        bm1, bm2, acc = _seed_bm_pair_and_account(db, two_users[0])
        db.execute("INSERT INTO fb_account_bm(account_id, bm_id, is_primary) VALUES(?,?,1)",
                   (acc, bm1))
        db.commit()
        db.execute("UPDATE fb_account_bm SET is_primary=0 WHERE account_id=?", (acc,))
        db.execute("UPDATE fb_account_bm SET is_primary=1 WHERE account_id=? AND bm_id=?",
                   (acc, bm2))
        db.commit()
        row = db.execute("SELECT bm_id FROM fb_account_bm WHERE account_id=? AND is_primary=1",
                         (acc,)).fetchone()
        db.close()
        assert row is not None and row["bm_id"] == bm2

    def test_two_primaries_rejected(self, client, two_users):
        """同一账户至多一个主 BM。"""
        db = database.get_db()
        bm1, bm2, acc = _seed_bm_pair_and_account(db, two_users[0])
        db.execute("INSERT INTO fb_account_bm(account_id, bm_id, is_primary) VALUES(?,?,1)",
                   (acc, bm1))
        db.commit()
        with pytest.raises(sqlite3.IntegrityError):
            db.execute("INSERT INTO fb_account_bm(account_id, bm_id, is_primary) VALUES(?,?,1)",
                       (acc, bm2))
        db.rollback()
        db.close()

    def test_setting_new_primary_before_clearing_fails(self, client, two_users):
        """先设后清会撞部分唯一索引 —— 把「顺序不是风格问题」钉成回归测试。

        SQLite 的唯一索引是**逐语句**检查的，不是事务提交时统一检查。
        """
        db = database.get_db()
        bm1, bm2, acc = _seed_bm_pair_and_account(db, two_users[0])
        db.execute("INSERT INTO fb_account_bm(account_id, bm_id, is_primary) VALUES(?,?,1)",
                   (acc, bm1))
        db.commit()
        with pytest.raises(sqlite3.IntegrityError):
            # 先设新的（此刻 bm1 仍是 1）
            db.execute("UPDATE fb_account_bm SET is_primary=1 WHERE account_id=? AND bm_id=?",
                       (acc, bm2))
        db.rollback()
        db.close()

    def test_multiple_non_primary_bms_allowed(self, client, two_users):
        """非主 BM 不受限：一个账户可挂多个 BM。"""
        db = database.get_db()
        bm1, bm2, acc = _seed_bm_pair_and_account(db, two_users[0])
        db.execute("INSERT INTO fb_account_bm(account_id, bm_id, is_primary) VALUES(?,?,0)",
                   (acc, bm1))
        db.execute("INSERT INTO fb_account_bm(account_id, bm_id, is_primary) VALUES(?,?,0)",
                   (acc, bm2))
        db.commit()
        n = db.execute("SELECT COUNT(*) FROM fb_account_bm WHERE account_id=?", (acc,)).fetchone()[0]
        db.close()
        assert n == 2
