"""选项表导入的查重键必须是各表**真实的 UNIQUE 约束**。

起因（2026-10-06）：`data_service._import_option_table` 对四张选项表一律按
`(name, owner_id)` 查重，而 `account_statuses` / `sales_persons` 的真实唯一键是
`(name, platform)`（`mcc_levels` 是 `(name, owner_id)`、`agents` 是
`(name, owner_id, platform)`）。生产里字典行的 `owner_id` 全是创建者 developer=1，
于是**任何非 developer 的导入**都会走到「查不到 → INSERT → 撞
UNIQUE(name, platform)」，异常穿出 `_import_option_table` 把整次导入打崩
（`/api/data/import` 的 `except Exception` 直接 500，业务表一条都进不去）。
"""
import json
import os
import sys

_py_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _py_dir not in sys.path:
    sys.path.insert(0, _py_dir)

import data_service  # noqa: E402
import database  # noqa: E402


def _register(client, username):
    client.post("/api/auth/register", json={"username": username, "password": "test123"})
    db = database.get_db()
    uid = db.execute("SELECT id FROM users WHERE username=?", (username,)).fetchone()["id"]
    db.close()
    return uid


def _write_export(tmp_path, tables):
    payload = {"data": tables}
    path = os.path.join(tmp_path, "export.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False)
    return path


class TestOptionTableImportDedup:
    def test_status_row_owned_by_someone_else_is_deduped_not_duplicated(
        self, client, tmp_path
    ):
        """字典行属于别人（生产 = developer）时，导入必须**跳过**而不是撞 UNIQUE。"""
        creator = _register(client, "imp_creator")
        target = _register(client, "imp_target")
        assert creator != target

        db = database.get_db()
        db.execute(
            "INSERT INTO account_statuses(name, owner_id, platform) VALUES('存活',?,'gg')",
            (creator,))
        db.commit()
        before = db.execute("SELECT COUNT(*) FROM account_statuses").fetchone()[0]
        db.close()

        path = _write_export(tmp_path, {
            "account_statuses": [
                {"id": 1, "name": "存活", "owner_id": creator, "platform": "gg"},
            ],
        })
        report = data_service.execute_import(path, "json", target)  # 不得抛异常

        db = database.get_db()
        after = db.execute("SELECT COUNT(*) FROM account_statuses").fetchone()[0]
        db.close()
        assert after == before, "同名同平台的字典行不得重复插入"
        assert report["report"]["account_statuses"]["skipped"] == 1

    def test_sales_person_same_name_other_owner_is_deduped(self, client, tmp_path):
        """sales_persons 同为 UNIQUE(name, platform)，同样不得重复插入。"""
        creator = _register(client, "imp_creator2")
        target = _register(client, "imp_target2")

        db = database.get_db()
        db.execute(
            "INSERT INTO sales_persons(name, owner_id, platform) VALUES('老王',?,'gg')",
            (creator,))
        db.commit()
        before = db.execute("SELECT COUNT(*) FROM sales_persons").fetchone()[0]
        db.close()

        path = _write_export(tmp_path, {
            "sales_persons": [
                {"id": 1, "name": "老王", "owner_id": creator, "platform": "gg"},
            ],
        })
        report = data_service.execute_import(path, "json", target)

        db = database.get_db()
        after = db.execute("SELECT COUNT(*) FROM sales_persons").fetchone()[0]
        db.close()
        assert after == before
        assert report["report"]["sales_persons"]["skipped"] == 1

    def test_absent_platform_defaults_to_gg_for_dedup(self, client, tmp_path):
        """旧导出没有 platform 列 → 按建表默认值 'gg' 查重，不能因 NULL 失配而重复插入。"""
        creator = _register(client, "imp_creator3")
        target = _register(client, "imp_target3")

        db = database.get_db()
        db.execute(
            "INSERT INTO account_statuses(name, owner_id, platform) VALUES('验证',?,'gg')",
            (creator,))
        db.commit()
        before = db.execute("SELECT COUNT(*) FROM account_statuses").fetchone()[0]
        db.close()

        path = _write_export(tmp_path, {
            "account_statuses": [{"id": 1, "name": "验证", "owner_id": creator}],
        })
        report = data_service.execute_import(path, "json", target)

        db = database.get_db()
        after = db.execute("SELECT COUNT(*) FROM account_statuses").fetchone()[0]
        db.close()
        assert after == before
        assert report["report"]["account_statuses"]["skipped"] == 1

    def test_mcc_level_still_deduped_by_owner(self, client, tmp_path):
        """对照腿：mcc_levels 的唯一键确实含 owner_id，别人的同名行**不**算重复。

        若不按表区分查重键（一律 (name, platform)），这条会误判为重复而漏导入。
        """
        creator = _register(client, "imp_creator4")
        target = _register(client, "imp_target4")

        db = database.get_db()
        db.execute("INSERT INTO mcc_levels(name, owner_id) VALUES('一级',?)", (creator,))
        db.commit()
        db.close()

        path = _write_export(tmp_path, {
            "mcc_levels": [{"id": 1, "name": "一级", "owner_id": creator}],
        })
        report = data_service.execute_import(path, "json", target)

        assert report["report"]["mcc_levels"]["imported"] == 1
        db = database.get_db()
        owners = {
            r["owner_id"]
            for r in db.execute("SELECT owner_id FROM mcc_levels WHERE name='一级'")
        }
        db.close()
        assert owners == {creator, target}
