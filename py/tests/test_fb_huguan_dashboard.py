"""FB 户管看板（子项目 ②）测试。

设计见 docs/superpowers/specs/2026-10-06-fb-huguan-dashboard-design.md。
本文件不打真实 Google API。
"""
import pytest

import database
import huguan_dashboard as hd


class TestPlatformSkeleton:
    def test_platforms_includes_fb(self):
        assert hd.PLATFORMS == ("gg", "tt", "fb")

    def test_table_for_platform_has_all_three(self):
        assert hd._TABLE_FOR_PLATFORM["gg"] == "accounts"
        assert hd._TABLE_FOR_PLATFORM["tt"] == "tt_accounts"
        assert hd._TABLE_FOR_PLATFORM["fb"] == "fb_accounts"

    def test_table_lookup_raises_on_unknown_platform(self):
        """缺键必须 KeyError —— 不能像二元 else 那样静默回落 GG 表。"""
        with pytest.raises(KeyError):
            hd._TABLE_FOR_PLATFORM["fbx"]

    def test_row_sql_has_all_three(self):
        for p in hd.PLATFORMS:
            assert p in hd._ROW_SQL, p

    def test_fb_row_sql_selects_from_fb_accounts(self):
        assert "FROM fb_accounts" in hd._FB_ROW_SQL

    def test_fb_row_sql_joins_primary_bm_only(self):
        """主 BM 的 join 必须带 is_primary=1，否则多 BM 账户会让行数翻倍。"""
        assert "ab.is_primary = 1" in hd._FB_ROW_SQL


class TestFbColumnSpec:
    def test_seventeen_columns(self):
        assert len(hd.COLUMN_SPEC["fb"]) == 17
        letters = [c[0] for c in hd.COLUMN_SPEC["fb"]]
        assert letters == [chr(ord("A") + i) for i in range(17)]

    def test_writable_readable_flags(self):
        flags = {c[0]: (c[3], c[4]) for c in hd.COLUMN_SPEC["fb"]}
        # B 操作人与 D 资产UID：写但不读
        assert flags["B"] == (True, False)
        assert flags["D"] == (True, False)
        # I 接户运营：只读回 + 定向写，不参与批量回写
        assert flags["I"] == (False, True)
        # 其余全部双向
        for col in "ACEFGHJKLMNOPQ":
            assert flags[col] == (True, True), col

    def test_key_and_owner_cols(self):
        assert hd.KEY_COL["fb"] == "D"
        assert hd.OWNER_COL["fb"] == "J"
        assert hd.READ_RANGE["fb"] == "A:Q"
        assert hd.ACCOUNT_KEY_FIELD["fb"] == "account_id"

    def test_owner_channel_col_has_no_fb_key(self):
        """FB 刻意不登记 —— 见 spec §6.5。"""
        assert "fb" not in hd.OWNER_CHANNEL_COL

    def test_cells_for_row_excludes_column_i(self):
        """cells_for_row 产出 = A:Q 除去 I。

        订正：brief/plan 原文写的是 set("ACDEFGHJKLMNOPQ")（15 个字母，漏了 B），
        但 B 操作人 writable=True（见 test_writable_readable_flags），cells 必然含 B；
        设计文档 §131 亦写明「产出 = writable=True 的列，即 A:Q 除去 I」（16 列）。
        原串是笔误，此处补回 B 以还原用例自身声明的意图。
        """
        row = {c[2]: "x" for c in hd.COLUMN_SPEC["fb"] if c[2]}
        row["account_id"] = "123"
        cells = hd.cells_for_row(row, "fb")
        assert "I" not in cells
        assert set(cells) == set("ABCDEFGHJKLMNOPQ")


class TestFbNameResolution:
    @pytest.fixture
    def fb_seed(self, client):
        """一个 FB 用户 + 一条渠道 + 一条资产类型。"""
        db = database.get_db()
        db.execute("INSERT INTO users(username, password, role, platform) "
                   "VALUES('fb_res', 'x', 'user', 'fb')")
        uid = db.execute("SELECT last_insert_rowid()").fetchone()[0]
        db.execute("INSERT INTO fb_channels(name, owner_id, platform) VALUES('渠道甲', ?, 'fb')",
                   (uid,))
        ch = db.execute("SELECT last_insert_rowid()").fetchone()[0]
        db.execute("INSERT INTO fb_asset_types(name, owner_id, platform) VALUES('类型乙', ?, 'fb')",
                   (uid,))
        at = db.execute("SELECT last_insert_rowid()").fetchone()[0]
        db.commit()
        db.close()
        return {"uid": uid, "channel_id": ch, "asset_type_id": at}

    def test_resolves_channel_name(self, client, fb_seed):
        db = database.get_db()
        known, resolved = hd._resolve_field(db, "fb", "channel_name", "渠道甲")
        db.close()
        assert known is True
        assert resolved == fb_seed["channel_id"]

    def test_resolves_asset_type_name(self, client, fb_seed):
        db = database.get_db()
        known, resolved = hd._resolve_field(db, "fb", "asset_type_name", "类型乙")
        db.close()
        assert known is True
        assert resolved == fb_seed["asset_type_id"]

    def test_unknown_channel_gives_none_not_warning_lookup(self, client, fb_seed):
        """查不到 → resolved is None（调用方记 warning），不是歧义档。"""
        db = database.get_db()
        known, resolved = hd._resolve_field(db, "fb", "channel_name", "不存在的渠道")
        db.close()
        assert known is True and resolved is None

    def test_target_column_mapping(self):
        assert hd._target_column("fb", "channel_name") == "channel_id"
        assert hd._target_column("fb", "asset_type_name") == "asset_type_id"

    def test_parseable_fields_fb(self):
        assert hd._parseable_fields("fb") == ("channel_name", "asset_type_name", "status_name")

    def test_parseable_fields_gg_tt_unchanged(self):
        """回归点：GG / TT 的可解析字段集不得变化。"""
        assert hd._parseable_fields("gg") == ("mcc_name", "agent_name", "bc_name", "status_name")
        assert hd._parseable_fields("tt") == ("mcc_name", "agent_name", "bc_name", "status_name")


class TestFbApplyDeathIsNoop:
    def test_death_does_not_touch_fb_accounts(self, client):
        """fb_accounts 没有 death_date 列 —— 走到这里会 OperationalError。

        这条是防回归的关键断言：FB 分支忘记 return 会让整批同步逐行报错，
        而不是静默出错，所以必须有一个用例钉住「调用不抛异常且不改任何列」。
        """
        db = database.get_db()
        db.execute("INSERT INTO users(username, password, role, platform) "
                   "VALUES('fb_d', 'x', 'user', 'fb')")
        uid = db.execute("SELECT last_insert_rowid()").fetchone()[0]
        db.execute("INSERT INTO fb_accounts(name, account_id, owner_id) VALUES('户', 'DE-1', ?)",
                   (uid,))
        pk = db.execute("SELECT last_insert_rowid()").fetchone()[0]
        db.commit()
        before = dict(db.execute("SELECT * FROM fb_accounts WHERE id=?", (pk,)).fetchone())
        # 两个方向都不能抛异常（走到 UPDATE death_date 就会 OperationalError）
        hd._apply_death(db, "fb", pk, True)
        hd._apply_death(db, "fb", pk, False)
        db.commit()
        after = dict(db.execute("SELECT * FROM fb_accounts WHERE id=?", (pk,)).fetchone())
        db.close()
        # 真的什么都没改 —— 不只是「没崩」
        assert after == before

    def test_gg_apply_death_still_works(self, client):
        """回归点：GG / TT 的死亡标记行为不变。"""
        db = database.get_db()
        db.execute("INSERT INTO users(username, password, role, platform) "
                   "VALUES('gg_d', 'x', 'user', 'gg')")
        uid = db.execute("SELECT last_insert_rowid()").fetchone()[0]
        db.execute("INSERT INTO accounts(name, account_id, owner_id) VALUES('户', 'GD-1', ?)",
                   (uid,))
        pk = db.execute("SELECT last_insert_rowid()").fetchone()[0]
        db.commit()
        hd._apply_death(db, "gg", pk, True)
        db.commit()
        row = db.execute("SELECT death_date, status_changed_date FROM accounts WHERE id=?",
                         (pk,)).fetchone()
        db.close()
        assert row["death_date"] != ""
        assert row["status_changed_date"] != ""


class TestFbPrimaryBmSync:
    @pytest.fixture
    def fb_bm_seed(self, client):
        db = database.get_db()
        db.execute("INSERT INTO users(username, password, role, platform) "
                   "VALUES('fb_bm', 'x', 'user', 'fb')")
        uid = db.execute("SELECT last_insert_rowid()").fetchone()[0]
        ids = []
        for nm, bid in (("BM一", "b1"), ("BM二", "b2")):
            db.execute("INSERT INTO fb_bms(name, bm_id, owner_id) VALUES(?,?,?)", (nm, bid, uid))
            ids.append(db.execute("SELECT last_insert_rowid()").fetchone()[0])
        db.execute("INSERT INTO fb_accounts(name, account_id, owner_id) VALUES('户', 'BM-1', ?)",
                   (uid,))
        acc = db.execute("SELECT last_insert_rowid()").fetchone()[0]
        db.commit()
        db.close()
        return {"uid": uid, "bm1": ids[0], "bm2": ids[1], "acc": acc}

    def test_set_primary_bm_switches(self, client, fb_bm_seed):
        s = fb_bm_seed
        db = database.get_db()
        hd._set_primary_bm(db, s["acc"], s["bm1"])
        db.commit()
        hd._set_primary_bm(db, s["acc"], s["bm2"])   # 换 BM
        db.commit()
        row = db.execute("SELECT bm_id FROM fb_account_bm WHERE account_id=? AND is_primary=1",
                         (s["acc"],)).fetchone()
        db.close()
        assert row["bm_id"] == s["bm2"]

    def test_record_bm_change_writes_history(self, client, fb_bm_seed):
        s = fb_bm_seed
        db = database.get_db()
        hd._record_bm_change(db, s["acc"], None, s["bm1"], s["uid"])
        db.commit()
        row = db.execute("SELECT old_bm_id, new_bm_id, changed_by FROM fb_account_bm_history "
                         "WHERE account_id=?", (s["acc"],)).fetchone()
        db.close()
        assert row["old_bm_id"] is None and row["new_bm_id"] == s["bm1"]

    def test_record_bm_change_skips_when_unchanged(self, client, fb_bm_seed):
        """值没变不写历史 —— 否则历史面板会被 A→A 刷屏。"""
        s = fb_bm_seed
        db = database.get_db()
        hd._record_bm_change(db, s["acc"], s["bm1"], s["bm1"], s["uid"])
        db.commit()
        n = db.execute("SELECT COUNT(*) FROM fb_account_bm_history WHERE account_id=?",
                       (s["acc"],)).fetchone()[0]
        db.close()
        assert n == 0

    def test_record_bm_change_skips_without_changed_by(self, client, fb_bm_seed):
        """changed_by REFERENCES users(id)，写 None 会撞 FK —— 宁可漏记。"""
        s = fb_bm_seed
        db = database.get_db()
        hd._record_bm_change(db, s["acc"], None, s["bm1"], 0)
        db.commit()
        n = db.execute("SELECT COUNT(*) FROM fb_account_bm_history WHERE account_id=?",
                       (s["acc"],)).fetchone()[0]
        db.close()
        assert n == 0


def _fb_row(account_id: str, bm_name: str = "") -> list:
    """构造一行 FB 表原始单元格值（A:Q 共 17 列，只填 D 资产UID 与 P 位置）。"""
    values = [""] * 17
    values[hd.col_index("D")] = account_id
    values[hd.col_index("P")] = bm_name
    return values


class TestFbBuildApplyIntegration:
    """端到端驱动 build_diff / apply_diff 的 FB 分支（子项目 ② Task 4）。

    上面 TestFbPrimaryBmSync 只直接调 `_set_primary_bm` / `_record_bm_change` 两个
    助手；本类走真实路径：parse_row → build_diff → apply_diff，钉住 6 处 FB 安全
    修补里「清位置 / 换位置 / 建号不写 death_date / 坏 BM 名」这几条集成行为 ——
    它们正是后续重构最容易静默改坏、而单测助手函数看不见的部分。
    """

    @pytest.fixture
    def fb_seed(self, client):
        """一个 FB 用户 + 两个 BM + 一个已存账户（BM一 为主 BM，BM二 为非主）。"""
        db = database.get_db()
        db.execute("INSERT INTO users(username, password, role, platform) "
                   "VALUES('fb_int', 'x', 'user', 'fb')")
        uid = db.execute("SELECT last_insert_rowid()").fetchone()[0]
        ids = []
        for nm, bid in (("BM一", "b1"), ("BM二", "b2")):
            db.execute("INSERT INTO fb_bms(name, bm_id, owner_id) VALUES(?,?,?)", (nm, bid, uid))
            ids.append(db.execute("SELECT last_insert_rowid()").fetchone()[0])
        db.execute("INSERT INTO fb_accounts(name, account_id, owner_id) VALUES('户', 'BM-1', ?)",
                   (uid,))
        acc = db.execute("SELECT last_insert_rowid()").fetchone()[0]
        db.execute("INSERT INTO fb_account_bm(account_id, bm_id, is_primary) VALUES(?,?,1)",
                   (acc, ids[0]))
        db.execute("INSERT INTO fb_account_bm(account_id, bm_id, is_primary) VALUES(?,?,0)",
                   (acc, ids[1]))
        db.commit()
        db.close()
        return {"uid": uid, "bm1": ids[0], "bm2": ids[1], "acc": acc}

    def test_blank_position_clears_primary_without_deleting_links(self, client, fb_seed):
        """位置空着 → 清主 BM 标记，但关联行一行都不能删。"""
        s = fb_seed
        db = database.get_db()
        parsed = hd.parse_row(_fb_row("BM-1", ""), "fb")
        parsed["row"] = 2
        diff = hd.build_diff(db, [parsed], "fb")
        # 先钉住「空位置确实进了差异」：build_diff 若看不见当前主 BM 会把它滤掉。
        upd = [i for i in diff["to_update"] if i["account_id"] == "BM-1"]
        assert len(upd) == 1
        assert "_primary_bm_name" in upd[0]["fields"]
        before = db.execute("SELECT COUNT(*) FROM fb_account_bm WHERE account_id=?",
                            (s["acc"],)).fetchone()[0]

        res = hd.apply_diff(db, diff, "fb", {"update": ["BM-1"]}, s["uid"])

        prim = db.execute("SELECT COUNT(*) FROM fb_account_bm WHERE account_id=? AND is_primary=1",
                          (s["acc"],)).fetchone()[0]
        after = db.execute("SELECT COUNT(*) FROM fb_account_bm WHERE account_id=?",
                           (s["acc"],)).fetchone()[0]
        db.close()
        assert res["errors"] == []
        assert res["updated"] == 1
        assert prim == 0, "主 BM 标记应被清掉"
        assert before == 2
        assert after == 2, "清标记不得删掉任何 fb_account_bm 关联行"

    def test_position_filled_switches_primary_and_writes_history(self, client, fb_seed):
        """位置填 BM 名 → 换主 BM（旧的不再是主），并写一行历史。"""
        s = fb_seed
        db = database.get_db()
        parsed = hd.parse_row(_fb_row("BM-1", "BM二"), "fb")
        parsed["row"] = 2
        diff = hd.build_diff(db, [parsed], "fb")

        res = hd.apply_diff(db, diff, "fb", {"update": ["BM-1"]}, s["uid"])

        prim = db.execute("SELECT bm_id FROM fb_account_bm WHERE account_id=? AND is_primary=1",
                          (s["acc"],)).fetchone()
        old_primary = db.execute(
            "SELECT is_primary FROM fb_account_bm WHERE account_id=? AND bm_id=?",
            (s["acc"], s["bm1"])).fetchone()
        hist = db.execute("SELECT old_bm_id, new_bm_id, changed_by FROM fb_account_bm_history "
                          "WHERE account_id=?", (s["acc"],)).fetchall()
        db.close()
        assert res["errors"] == []
        assert res["updated"] == 1
        assert prim is not None and prim["bm_id"] == s["bm2"], "新 BM 应成为主 BM"
        assert old_primary["is_primary"] == 0, "旧 BM 不应再是主 BM"
        assert len(hist) == 1
        assert hist[0]["old_bm_id"] == s["bm1"]
        assert hist[0]["new_bm_id"] == s["bm2"]
        assert hist[0]["changed_by"] == s["uid"]

    def test_fb_create_does_not_write_death_date(self, client, fb_seed):
        """FB 建号不得写 death_date —— 否则 fb_accounts 无此列，整条建号失败。

        回归守卫：曾有无条件 `src["death_date"] = ""`，让每个 FB 新建账户
        都 `no column named death_date` 落进 errors，created 恒为 0。
        """
        s = fb_seed
        db = database.get_db()
        parsed = hd.parse_row(_fb_row("BM-NEW", ""), "fb")
        parsed["row"] = 3
        diff = hd.build_diff(db, [parsed], "fb")
        assert any(i["account_id"] == "BM-NEW" for i in diff["to_create"])

        res = hd.apply_diff(db, diff, "fb", {"create": ["BM-NEW"]}, s["uid"])

        row = db.execute("SELECT id FROM fb_accounts WHERE account_id='BM-NEW'").fetchone()
        db.close()
        assert res["errors"] == [], res["errors"]
        assert res["created"] == 1
        assert row is not None, "FB 新建账户应真的落库"

    def test_position_unknown_bm_warns_and_writes_nothing(self, client, fb_seed):
        """位置填不存在的 BM 名 → 出警告，且不换主 BM、不写历史。"""
        s = fb_seed
        db = database.get_db()
        parsed = hd.parse_row(_fb_row("BM-1", "不存在的BM"), "fb")
        parsed["row"] = 2
        diff = hd.build_diff(db, [parsed], "fb")

        res = hd.apply_diff(db, diff, "fb", {"update": ["BM-1"]}, s["uid"])

        prim = db.execute("SELECT bm_id FROM fb_account_bm WHERE account_id=? AND is_primary=1",
                          (s["acc"],)).fetchone()
        n_hist = db.execute("SELECT COUNT(*) FROM fb_account_bm_history WHERE account_id=?",
                            (s["acc"],)).fetchone()[0]
        db.close()
        assert res["errors"] == []
        assert any("无法唯一匹配" in w["message"] for w in res["warnings"]), res["warnings"]
        assert prim is not None and prim["bm_id"] == s["bm1"], "坏 BM 名不得改动主 BM"
        assert n_hist == 0, "坏 BM 名不得写历史"
