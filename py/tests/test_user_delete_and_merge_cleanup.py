"""关联数据清理回归测试（2026-09-24）。

覆盖三处此前遗漏的清理 —— 它们都以 500（FOREIGN KEY constraint failed）
或遗留孤儿行的方式暴露：

1. `admin_delete_user` 未清理 TT / FB / 字典表中引用 users(id) 的列。
   这些列都是 `REFERENCES users(id)` 且**无 ON DELETE**，而连接开了
   `PRAGMA foreign_keys=ON`，旧代码删任何拥有 TT/FB 数据的用户都会 500。
2. TT `products_merge` 未清理 `tt_delist_checks` / `tt_delist_notifications`。
3. GG `products_merge` 未清理 `delist_notifications`（它按 package_id 挂载，
   不像 delist_checks 那样有 product_id）。

两处 merge 内部都先 `PRAGMA foreign_keys=OFF`，级联删除不会触发，
因此必须显式清理，且在删 packages 之前按包清理。
"""
import pytest

import database


# ---------- 直接操作库的辅助（测试内构造数据用，不走 API） ----------

def _uid(username):
    db = database.get_db()
    row = db.execute("SELECT id FROM users WHERE username=?", (username,)).fetchone()
    db.close()
    assert row, f"用户 {username} 不存在"
    return row[0]


def _ins(sql, params=()):
    """插入一行并返回 lastrowid。"""
    db = database.get_db()
    cur = db.execute(sql, params)
    db.commit()
    last = cur.lastrowid
    db.close()
    return last


def _scalar(sql, params=()):
    db = database.get_db()
    v = db.execute(sql, params).fetchone()[0]
    db.close()
    return v


def _count(table, where=""):
    return _scalar(f"SELECT COUNT(*) FROM {table} {where}".strip())


# ============================================================
# 1. 删用户：TT / FB / 字典表关联清理
# ============================================================

class TestDeleteUserCleanup:
    def test_tt_data_owner_can_be_deleted(self, client, dev_headers, tt_headers):
        """拥有 TT 数据的用户可被删除（修复前 500）。"""
        uid = _uid("ttuser")
        pid = _ins("INSERT INTO tt_products (product_name, owner_id, status) VALUES (?,?,'active')",
                   ("TT产品", uid))
        pkg = _ins("INSERT INTO tt_packages (product_id, type, package_name, url) "
                   "VALUES (?,'package','com.tt.a','https://play.google.com/store/apps/details?id=com.tt.a')",
                   (pid,))
        _ins("INSERT INTO tt_product_runners (product_id, user_id) VALUES (?,?)", (pid, uid))
        _ins("INSERT INTO tt_delist_checks (package_id, is_delisted) VALUES (?,1)", (pkg,))
        _ins("INSERT INTO tt_delist_notifications (package_id, user_id) VALUES (?,?)", (pkg, uid))

        resp = client.delete(f"/api/admin/users/{uid}", headers=dev_headers)

        assert resp.status_code == 200, resp.get_json()
        assert resp.get_json()["success"] is True
        assert _count("users", f"WHERE id={uid}") == 0
        # 在跑人员是纯归属关系 → 删除
        assert _count("tt_product_runners", f"WHERE user_id={uid}") == 0
        # owner_id 可空 → 置空，产品本身保留（TT 产品是共享数据）
        assert _scalar("SELECT owner_id FROM tt_products WHERE id=?", (pid,)) is None

    def test_fb_data_owner_can_be_deleted(self, client, dev_headers, auth_headers):
        """拥有 FB 数据的用户可被删除：做表数据 NULL 不出只能删，归属列置空。"""
        uid = _uid("testuser")
        fpid = _ins("INSERT INTO fb_products (product_name, owner_id) VALUES (?,?)", ("FB产品", uid))
        _ins("INSERT INTO fb_product_runners (product_id, user_id) VALUES (?,?)", (fpid, uid))
        _ins("INSERT INTO fb_ad_reports (user_id, product_name, report_date) VALUES (?,?,?)",
             (uid, "FB产品", "2026-09-01"))
        acc = _ins("INSERT INTO fb_accounts (name, account_id, owner_id) VALUES (?,?,?)",
                   ("FB账户", "act_1", uid))

        resp = client.delete(f"/api/admin/users/{uid}", headers=dev_headers)

        assert resp.status_code == 200, resp.get_json()
        assert resp.get_json()["success"] is True
        assert _count("fb_ad_reports", f"WHERE user_id={uid}") == 0
        assert _count("fb_product_runners", f"WHERE user_id={uid}") == 0
        assert _scalar("SELECT owner_id FROM fb_products WHERE id=?", (fpid,)) is None
        assert _scalar("SELECT owner_id FROM fb_accounts WHERE id=?", (acc,)) is None

    def test_dict_option_creator_can_be_deleted(self, client, dev_headers, auth_headers):
        """字典表（选项）的创建人被置空，选项本身保留。"""
        uid = _uid("testuser")
        rows = {}
        for tbl in ("agents", "account_statuses", "mcc_levels", "sales_persons"):
            rows[tbl] = _ins(f"INSERT INTO {tbl} (name, owner_id) VALUES (?,?)",
                            (f"测试项_{tbl}", uid))

        resp = client.delete(f"/api/admin/users/{uid}", headers=dev_headers)

        assert resp.status_code == 200, resp.get_json()
        for tbl, rid in rows.items():
            assert _count(tbl, f"WHERE id={rid}") == 1, f"{tbl} 的选项不该被删"
            assert _scalar(f"SELECT owner_id FROM {tbl} WHERE id=?", (rid,)) is None, \
                f"{tbl}.owner_id 应为 NULL"

    def test_gg_data_owner_can_be_deleted(self, client, dev_headers, auth_headers):
        """既有 GG 行为未被破坏（对照组）。"""
        uid = _uid("testuser")
        acc = _ins("INSERT INTO accounts (name, account_id, owner_id) VALUES (?,?,?)",
                   ("GG账户", "123-456-7890", uid))
        pid = _ins("INSERT INTO products (product_name, owner_id) VALUES (?,?)", ("GG产品", uid))

        resp = client.delete(f"/api/admin/users/{uid}", headers=dev_headers)

        assert resp.status_code == 200, resp.get_json()
        assert _scalar("SELECT owner_id FROM accounts WHERE id=?", (acc,)) is None
        assert _scalar("SELECT owner_id FROM products WHERE id=?", (pid,)) is None


# ============================================================
# 2 & 3. 合并产品：掉包检测/通知的孤儿行清理
# ============================================================

class TestMergeDelistCleanup:
    def test_tt_merge_removes_delist_rows_of_merged_packages(self, client, tt_headers):
        """TT 合并副产品时，其包的 tt_delist_checks / tt_delist_notifications 一并清理。"""
        uid = _uid("ttuser")
        master = _ins("INSERT INTO tt_products (product_name, owner_id) VALUES (?,?)", ("主产品", uid))
        sub = _ins("INSERT INTO tt_products (product_name, owner_id) VALUES (?,?)", ("副产品", uid))
        pkg = _ins("INSERT INTO tt_packages (product_id, type, package_name, url) "
                   "VALUES (?,'package','com.tt.sub','https://play.google.com/store/apps/details?id=com.tt.sub')",
                   (sub,))
        _ins("INSERT INTO tt_delist_checks (package_id, is_delisted) VALUES (?,1)", (pkg,))
        _ins("INSERT INTO tt_delist_notifications (package_id, user_id) VALUES (?,?)", (pkg, uid))

        resp = client.post("/api/tt/products/merge",
                           json={"master_id": master, "merge_ids": [sub]},
                           headers=tt_headers)

        assert resp.status_code == 200, resp.get_json()
        assert resp.get_json()["success"] is True
        assert _count("tt_products", f"WHERE id={sub}") == 0
        assert _count("tt_delist_checks", f"WHERE package_id={pkg}") == 0
        assert _count("tt_delist_notifications", f"WHERE package_id={pkg}") == 0

    def test_gg_merge_removes_delist_notifications_of_merged_packages(self, client, auth_headers):
        """GG 合并副产品时，其包的 delist_notifications 一并清理（按 package_id 挂载）。"""
        uid = _uid("testuser")
        master = _ins("INSERT INTO products (product_name, owner_id) VALUES (?,?)", ("主产品", uid))
        sub = _ins("INSERT INTO products (product_name, owner_id) VALUES (?,?)", ("副产品", uid))
        pkg = _ins("INSERT INTO packages (product_id, package_name, url) VALUES (?,?,?)",
                   (sub, "com.gg.sub", "https://play.google.com/store/apps/details?id=com.gg.sub"))
        _ins("INSERT INTO delist_notifications (package_id, user_id) VALUES (?,?)", (pkg, uid))

        resp = client.post("/api/products/merge",
                           json={"master_id": master, "merge_ids": [sub]},
                           headers=auth_headers)

        assert resp.status_code == 200, resp.get_json()
        assert resp.get_json()["success"] is True
        assert _count("products", f"WHERE id={sub}") == 0
        assert _count("delist_notifications", f"WHERE package_id={pkg}") == 0
