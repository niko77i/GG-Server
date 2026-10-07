"""FB 户管看板（子项目 ②）测试。

设计见 docs/superpowers/specs/2026-10-06-fb-huguan-dashboard-design.md。
本文件不打真实 Google API。
"""
import json

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


def _fb_row_with_acceptor(account_id: str, acceptor: str) -> list:
    """构造一行 FB 表原始单元格值，只填 D 资产UID 与 I 接户运营。"""
    values = _fb_row(account_id)
    values[hd.col_index("I")] = acceptor
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


def _fb_bare_account(db, account_id: str, owner_id: int) -> int:
    """建一条「文本列全空」的 FB 账户，返回行主键。

    `acquired_date` 必须显式写空 —— 建表默认值是当天日期，不写就会与表里空着的 A 列
    判成「变了」，让 `updated` 计数用例失去分辨力（`changed` 里混进无关列 ⇒ 走进
    `sets` 分支 ⇒ 那行本来就该计数）。其余文本列建表默认值都是空串。
    """
    db.execute("INSERT INTO fb_accounts(name, account_id, owner_id, acquired_date) "
               "VALUES('', ?, ?, '')", (account_id, owner_id))
    return db.execute("SELECT last_insert_rowid() AS id").fetchone()["id"]


class TestLeftoverMinorsFromSubproject2:
    """子项目 ② 遗留的三条 Minor（③ 的计划第 1109 行点名「在 Task 4/5 碰到对应代码时一并修」）。

    三条都在 `apply_diff` / `_same_as_existing` 里 —— Task 4/5 大幅改写了这两处却一处
    都没修：建号分支 BM 名解析失败静默、`updated` 计数偏高、`_same_as_existing` 查主 BM
    未过滤软删。全部走真实路径（parse_row → build_diff → apply_diff），不打 stub。
    """

    @pytest.fixture
    def fb_user(self, client):
        """一个 FB 平台的户管，返回其 id。"""
        db = database.get_db()
        db.execute("INSERT INTO users(username, password, role, platform) "
                   "VALUES('fb_a2', 'x', 'huguan', 'fb')")
        uid = db.execute("SELECT last_insert_rowid()").fetchone()[0]
        db.commit()
        db.close()
        return uid

    # ---------- 遗留 1：建号分支的 BM 名解析失败静默 ----------

    def test_create_with_unknown_position_warns_like_update(self, client, fb_user):
        """建号分支位置名解析不到 ⇒ 同口径 warning，且账户仍建成功。

        改前这里无声跳过：户管看到的是「账户建好了、位置列空着」而没有任何提示，
        同一个函数里的 update 分支却是会说的。文案必须与 update 分支逐字一致
        （前端渲染无需为两处写分支）。
        """
        db = database.get_db()
        parsed = hd.parse_row(_fb_row("A2-C1", "不存在的BM"), "fb")
        parsed["row"] = 2
        diff = hd.build_diff(db, [parsed], "fb")

        res = hd.apply_diff(db, diff, "fb", {"create": ["A2-C1"]}, fb_user)

        row = db.execute("SELECT id FROM fb_accounts WHERE account_id='A2-C1'").fetchone()
        db.close()
        assert res["errors"] == [], res["errors"]
        assert res["created"] == 1, "位置解析失败不得让整条建号失败"
        assert row is not None, "账户必须真的落库"
        assert res["warnings"] == [
            {"row": 2, "message": "位置「不存在的BM」无法唯一匹配，已跳过"}]

    # ---------- 遗留 2：updated 计数偏高 ----------

    def test_no_write_is_not_counted_when_position_unresolvable(self, client, fb_user):
        """位置名解析不到 ⇒ 整行只剩一条 warning、一个字节都没写 ⇒ 不计入 updated。"""
        db = database.get_db()
        acc = _fb_bare_account(db, "A2-N1", fb_user)
        db.commit()
        parsed = hd.parse_row(_fb_row("A2-N1", "不存在的BM"), "fb")
        parsed["row"] = 2
        diff = hd.build_diff(db, [parsed], "fb")
        # 先钉住「这一行确实只剩位置一项进差异」：多一项就会走 sets 分支、
        # 变成「有写入」的场景，本用例就失去分辨力了。
        upd = [i for i in diff["to_update"] if i["account_id"] == "A2-N1"]
        assert upd and set(upd[0]["fields"]) == {"_primary_bm_name"}, diff["to_update"]
        # updated_at 换成哨兵值：真写了库它必然被刷新成当前时刻
        db.execute("UPDATE fb_accounts SET updated_at='2000-01-01 00:00:00' WHERE id=?", (acc,))
        db.commit()

        res = hd.apply_diff(db, diff, "fb", {"update": ["A2-N1"]}, fb_user)

        row = db.execute("SELECT updated_at FROM fb_accounts WHERE id=?", (acc,)).fetchone()
        db.close()
        assert res["errors"] == []
        assert any("无法唯一匹配" in w["message"] for w in res["warnings"]), res["warnings"]
        assert res["updated"] == 0
        assert row["updated_at"] == "2000-01-01 00:00:00", "这一行根本没写库"

    def test_no_write_is_not_counted_for_already_dead_fb_account(self, client, fb_user):
        """FB 账户已是「死亡」且表里状态列仍写「死亡」⇒ 什么都没写，不该计入 updated。

        FB 的生死由状态列承载（`_apply_death` 对 fb 直接返回），所以这一行的
        status_id 与库里相等、不进 `changed`；而 `_is_dead` 因为在 fb_accounts 上
        查不到 death_date（`_same_as_existing` 的 `cur_dead` 恒为 False）被判成「变了」，
        于是整行**只剩它一项** —— 落库阶段 sets 为空、`_apply_death` 又是空操作，
        一个字节都没写。这正是「计数偏高」最容易被漏掉的一档。
        """
        db = database.get_db()
        acc = _fb_bare_account(db, "A2-D1", fb_user)
        db.execute("INSERT INTO account_statuses(name, owner_id, platform) "
                   "VALUES('死亡', ?, 'fb')", (fb_user,))
        sid = db.execute("SELECT last_insert_rowid()").fetchone()[0]
        db.execute("UPDATE fb_accounts SET status_id=? WHERE id=?", (sid, acc))
        db.commit()
        values = _fb_row("A2-D1")
        values[hd.col_index("O")] = "死亡"
        parsed = hd.parse_row(values, "fb")
        parsed["row"] = 2
        diff = hd.build_diff(db, [parsed], "fb")
        upd = [i for i in diff["to_update"] if i["account_id"] == "A2-D1"]
        assert upd and upd[0]["fields"] == {"_is_dead": True}, diff["to_update"]

        res = hd.apply_diff(db, diff, "fb", {"update": ["A2-D1"]}, fb_user)

        db.close()
        assert res["errors"] == []
        assert res["updated"] == 0

    def test_primary_bm_only_write_is_still_counted(self, client, fb_user):
        """只改主 BM 的行**仍要**计入 updated —— 防「矫枉过正」。

        简化成 `if sets:` 计数会漏掉这一行：它的业务列一个都没变，写的是中间表
        fb_account_bm 与历史表，于是制造出一个新的「计数偏低」。
        """
        db = database.get_db()
        acc = _fb_bare_account(db, "A2-P1", fb_user)
        db.execute("INSERT INTO fb_bms(name, bm_id, owner_id) VALUES('位置甲', 'a2-p1', ?)",
                   (fb_user,))
        bm = db.execute("SELECT last_insert_rowid()").fetchone()[0]
        db.commit()
        parsed = hd.parse_row(_fb_row("A2-P1", "位置甲"), "fb")
        parsed["row"] = 2
        diff = hd.build_diff(db, [parsed], "fb")
        upd = [i for i in diff["to_update"] if i["account_id"] == "A2-P1"]
        assert upd and set(upd[0]["fields"]) == {"_primary_bm_name"}, diff["to_update"]

        res = hd.apply_diff(db, diff, "fb", {"update": ["A2-P1"]}, fb_user)

        prim = db.execute("SELECT bm_id FROM fb_account_bm WHERE account_id=? AND is_primary=1",
                          (acc,)).fetchone()
        hist = db.execute("SELECT COUNT(*) AS n FROM fb_account_bm_history WHERE account_id=?",
                          (acc,)).fetchone()["n"]
        db.close()
        assert res["errors"] == []
        assert res["updated"] == 1, "只改主 BM 的行同样写了库，必须计入"
        assert prim is not None and prim["bm_id"] == bm
        assert hist == 1

    # ---------- 遗留 3：软删的同名 BM 被当成「当前主 BM 名」 ----------

    def test_soft_deleted_same_name_bm_does_not_hide_position_change(self, client, fb_user):
        """软删的同名 BM 不得让「表里把位置改成这个名字」被判成「没变」。

        改前 `_same_as_existing` 的 JOIN 没带 `b.deleted_at IS NULL`：那条已软删的
        「位置甲」仍被读成当前主 BM 名 ⇒ 表里的这次修改进不了 to_update，永远写不进去、
        且没有任何提示。带上过滤后它照常进差异，落库阶段由 `resolve_named_id` 拒绝
        并出「无法唯一匹配」warning —— 户管看到的是显式拒绝，而不是静默丢弃。
        """
        db = database.get_db()
        acc = _fb_bare_account(db, "A2-S1", fb_user)
        db.execute("INSERT INTO fb_bms(name, bm_id, owner_id, deleted_at) "
                   "VALUES('位置甲', 'a2-s1', ?, datetime('now','localtime'))", (fb_user,))
        bm = db.execute("SELECT last_insert_rowid()").fetchone()[0]
        db.execute("INSERT INTO fb_account_bm(account_id, bm_id, is_primary) VALUES(?,?,1)",
                   (acc, bm))
        db.commit()
        parsed = hd.parse_row(_fb_row("A2-S1", "位置甲"), "fb")
        parsed["row"] = 2
        diff = hd.build_diff(db, [parsed], "fb")
        db.close()
        upd = [i for i in diff["to_update"] if i["account_id"] == "A2-S1"]
        assert len(upd) == 1, "软删同名 BM 不得把这次改位置判成「没变」而滤掉"
        assert upd[0]["fields"] == {"_primary_bm_name": "位置甲"}


class TestFbAcceptor:
    def test_column_exists_and_defaults_empty(self, client):
        db = database.get_db()
        cols = {r[1]: r[2] for r in db.execute("PRAGMA table_info(fb_accounts)").fetchall()}
        db.close()
        assert "acceptor" in cols
        assert cols["acceptor"] == "TEXT"

    def test_owner_transition_format(self):
        assert hd._fb_owner_transition("张三", "李四") == "张三转李四"

    def test_owner_transition_handles_empty_old(self):
        """首任（没有旧归属）不该拼出「转李四」。"""
        assert hd._fb_owner_transition("", "李四") == "李四"

    def test_owner_transition_handles_empty_new(self):
        """新归属为空（目标用户查不到 / 缺 to）不该拼出「张三转」。"""
        assert hd._fb_owner_transition("张三", "") == "张三"
        assert hd._fb_owner_transition("", "") == ""

    def test_acceptor_cells_only_contains_column_i(self):
        rows = [{"account_id": "A1"}, {"account_id": "A2"}]
        cells = hd._fb_acceptor_cells(rows, "张三转李四")
        assert cells == [{"account_id": "A1", "cells": {"I": "张三转李四"}},
                         {"account_id": "A2", "cells": {"I": "张三转李四"}}]

    def test_acceptor_is_read_back_verbatim(self, client):
        """接户运营双向：表里的串原样落进 acceptor，不做名称解析、不出警告。"""
        db = database.get_db()
        db.execute("INSERT INTO users(username, password, role, platform) "
                   "VALUES('fb_acc', 'x', 'user', 'fb')")
        db.commit()
        db.close()
        values = [""] * 17
        values[hd.col_index("D")] = "AC-1"
        values[hd.col_index("I")] = "张三转李四"
        parsed = hd.parse_row(values, "fb")
        assert parsed["acceptor"] == "张三转李四"
        assert "_owner_channel" not in parsed


class TestFbAcceptorReadback:
    """接户运营列（I）双向：户管在表里改它，build_diff + apply_diff 要落进 acceptor。

    设计 §3.1：「接户运营列 可读可写。读回时**原样存进 `acceptor`（TEXT）**，
    不做名称解析、不参与归属判定」。本类走真实路径
    （parse_row → build_diff → apply_diff）钉住这条链路。

    上面 `TestFbAcceptor.test_acceptor_is_read_back_verbatim` 只钉住 `parse_row`
    产出了 acceptor —— 但产出**没人消费**就等于被静默丢弃。改动前
    `_PLAIN_TEXT_FIELDS["fb"]` 不含 acceptor，`_collect_updates` 不会把它放进
    fields，`to_update` 里根本没有这一列，下面两条断言都会红。
    """

    @pytest.fixture
    def fb_acceptor_seed(self, client):
        """一个 FB 用户 + 一条已存账户（acceptor 初始为空）。"""
        db = database.get_db()
        db.execute("INSERT INTO users(username, password, role, platform) "
                   "VALUES('fb_rb', 'x', 'user', 'fb')")
        uid = db.execute("SELECT last_insert_rowid()").fetchone()[0]
        db.execute("INSERT INTO fb_accounts(name, account_id, owner_id) VALUES('户', 'RB-1', ?)",
                   (uid,))
        acc = db.execute("SELECT last_insert_rowid()").fetchone()[0]
        db.commit()
        db.close()
        return {"uid": uid, "acc": acc}

    def test_sheet_edit_lands_in_acceptor(self, client, fb_acceptor_seed):
        """户管在表 I 列填串 → 落进 fb_accounts.acceptor（原样，不解析）。"""
        s = fb_acceptor_seed
        db = database.get_db()
        parsed = hd.parse_row(_fb_row_with_acceptor("RB-1", "张三转李四"), "fb")
        parsed["row"] = 2
        diff = hd.build_diff(db, [parsed], "fb")
        # 先钉住「这一列确实进了差异」：改动前 _collect_updates 不看 acceptor，
        # to_update 里压根没有这一列，下面 len==1 会直接红。
        upd = [i for i in diff["to_update"] if i["account_id"] == "RB-1"]
        assert len(upd) == 1, diff
        assert upd[0]["fields"].get("acceptor") == "张三转李四"

        res = hd.apply_diff(db, diff, "fb", {"update": ["RB-1"]}, s["uid"])

        stored = db.execute("SELECT acceptor FROM fb_accounts WHERE id=?",
                            (s["acc"],)).fetchone()["acceptor"]
        db.close()
        assert res["errors"] == [], res["errors"]
        assert res["updated"] == 1
        assert stored == "张三转李四", stored

    def test_blank_sheet_cell_clears_acceptor(self, client, fb_acceptor_seed):
        """表 I 列清空 → 库里 acceptor 被清空（文本列「空着=清空」口径）。"""
        s = fb_acceptor_seed
        db = database.get_db()
        db.execute("UPDATE fb_accounts SET acceptor='张三转李四' WHERE id=?", (s["acc"],))
        db.commit()

        parsed = hd.parse_row(_fb_row_with_acceptor("RB-1", ""), "fb")
        parsed["row"] = 2
        diff = hd.build_diff(db, [parsed], "fb")
        upd = [i for i in diff["to_update"] if i["account_id"] == "RB-1"]
        assert len(upd) == 1, diff
        assert upd[0]["fields"]["acceptor"] == ""
        # 清空是不可逆动作，必须列进「将清空」提示（前端据此显式标注）。
        assert "acceptor" in upd[0]["clears"], upd[0]["clears"]

        res = hd.apply_diff(db, diff, "fb", {"update": ["RB-1"]}, s["uid"])

        stored = db.execute("SELECT acceptor FROM fb_accounts WHERE id=?",
                            (s["acc"],)).fetchone()["acceptor"]
        db.close()
        assert res["errors"] == [], res["errors"]
        assert stored == "", stored

    def test_cells_for_row_still_excludes_column_i(self):
        """回归守卫：读回口径打开后，批量回写仍不得碰 I 列。

        `_PLAIN_TEXT_FIELDS`（表→系统）与 `COLUMN_SPEC[...][3]`（系统→表）是
        两个正交旋钮 —— 本次只动前者。若顺手把 FB 的 I 列改成 writable=True，
        `cells_for_row` 会产出 "I" 覆盖户管手填的串，本断言必红。
        """
        row = {c[2]: "x" for c in hd.COLUMN_SPEC["fb"] if c[2]}
        row["account_id"] = "123"
        row["acceptor"] = "张三转李四"   # 即便行里有值也不得被推送
        cells = hd.cells_for_row(row, "fb")
        assert "I" not in cells


def _fb_loginable_user(client, username, role="huguan", platform="fb"):
    """建一个可登录的 FB 用户并返回 (headers, uid)。

    ⚠️ 偏离 brief：brief 的测试直接 `INSERT INTO users ... password='test123'`，
    但 `login_user` 走 `check_password_hash`，明文密码必然 401（`KeyError:
    'access_token'`）。这里改用仓内既定写法（register 落哈希 + UPDATE 改角色/平台，
    见 test_huguan_dashboard.py::_create_user 与 conftest.tt_headers）。断言与意图不变。
    """
    client.post("/api/auth/register", json={"username": username, "password": "test123"})
    db = database.get_db()
    db.execute("UPDATE users SET role=?, platform=? WHERE username=?", (role, platform, username))
    db.commit()
    row = db.execute("SELECT id FROM users WHERE username=?", (username,)).fetchone()
    db.close()
    token = client.post("/api/auth/login",
                        json={"username": username, "password": "test123"}
                        ).get_json()["access_token"]
    return {"Authorization": f"Bearer {token}"}, row["id"]


class TestFbAcceptorWritebackKeyCol:
    """修复轮 3 · 同族：定向写 I 列的定位列必须按平台取（FB 是 D，不是默认的 C）。

    `writeback_fb_acceptor` 此前调 `gs.update_rows_by_account_id(...)` 不传 key_col，
    于是按 C 列（账户名称）找资产UID → 整批落进 not_found、I 列静默写空。
    """

    def test_fb_acceptor_writeback_passes_key_col_D(self, client, monkeypatch):
        """走到真实 `writeback_fb_acceptor`（不桩它），只桩 Sheets I/O 与后台线程。

        判别力：去掉函数里的 `key_col=KEY_COL[platform]`，本用例立刻变红（实得 "C"）。
        """
        from huguan_dashboard import KEY_COL
        assert KEY_COL["fb"] == "D", "前提：FB 的资产UID在 D 列；列规格变了本用例要重写"

        _h, uid = _fb_loginable_user(client, "fb_kc", role="huguan", platform="fb")
        db = database.get_db()
        db.execute("INSERT OR REPLACE INTO config(key,value) VALUES(?,?)",
                   (f"huguan_dashboard_{uid}",
                    json.dumps({"fb": {"spreadsheet_id": "SS", "sheet_name": "S"}})))
        db.commit()
        db.close()

        import google_sheets_service as gs
        import main as m
        captured = []

        def _fake(service, spreadsheet_id, sheet_name, rows, key_col="C"):
            captured.append({"rows": rows, "key_col": key_col})
            return {"updated": len(rows), "not_found": []}

        monkeypatch.setattr(gs, "update_rows_by_account_id", _fake)
        monkeypatch.setattr(gs, "build_service", lambda path: object())
        # 回写经 main._sync_sheets_background 起后台线程；换成同步执行，断言不抢时间。
        monkeypatch.setattr(m, "_sync_sheets_background", lambda fn, on_fail: fn())

        hd.writeback_fb_acceptor(uid, "fb", "A1", "张三转李四")

        assert captured, "对照：写入器必须被调用过，否则下面断言是空集上的恒真式"
        assert captured[0]["key_col"] == "D"
        # 顺带钉住写的确实是 I 列（本函数存在的唯一理由）
        assert captured[0]["rows"] == [{"account_id": "A1", "cells": {"I": "张三转李四"}}]


class TestFbWritebackTriggers:
    """FB 端点必须触发户管看板回写；软删 / 恢复 / 永久删不触发。"""

    def test_create_triggers_writeback(self, client, monkeypatch):
        calls = []
        monkeypatch.setattr(hd, "writeback_rows",
                            lambda uid, plat, ids=None: calls.append((plat, ids)))
        # 用真实端点建一个账户
        # ⚠️ 偏离 brief：account_id 用纯数字 —— `create_account` 有
        # `if not account_id.isdigit(): return 400`，brief 原文的 "WB-1" 会被 400 拒。
        h, _ = _fb_loginable_user(client, "fb_wb")
        r = client.post("/api/fb/accounts/create", headers=h,
                        json={"name": "户wb", "account_id": "100001"})
        assert r.status_code == 200
        assert any(plat == "fb" for plat, _ in calls)

    def test_soft_delete_does_not_trigger(self, client, monkeypatch):
        calls = []
        monkeypatch.setattr(hd, "writeback_rows",
                            lambda uid, plat, ids=None: calls.append((plat, ids)))
        h, uid = _fb_loginable_user(client, "fb_wb2")
        db = database.get_db()
        db.execute("INSERT INTO fb_accounts(name, account_id, owner_id) VALUES('户','WB-2',?)",
                   (uid,))
        aid = db.execute("SELECT last_insert_rowid()").fetchone()[0]
        db.commit()
        db.close()
        client.delete(f"/api/fb/accounts/{aid}", headers=h)
        assert calls == []

    def test_reassign_to_self_triggers_writeback(self, client, monkeypatch):
        """跨用户角色把**别人名下**的户不带 owner_id 转给自己：归属真变了，两个回写都要调。

        单用户分支（target_owner == uid）不是「归属没变」的死路：非跨用户角色走不到
        这里（403 / 409），但跨用户角色对**别人的**户不传 owner_id 时，`existing["owner_id"]
        != uid` 让「已属于目标」的 409 不触发，UPDATE 确实把归属改成调用者自己。
        这条能区分「补了」与「没补」：去掉单用户分支的回写它必红。
        """
        rows_calls, acc_calls = [], []
        monkeypatch.setattr(hd, "writeback_rows",
                            lambda uid, plat, ids=None: rows_calls.append((plat, ids)))
        monkeypatch.setattr(hd, "writeback_fb_acceptor",
                            lambda uid, plat, aid, note: acc_calls.append((plat, aid, note)))
        h, dev = _fb_loginable_user(client, "fb_wb3", role="developer")
        # 户先挂在**别人**名下
        db = database.get_db()
        db.execute("INSERT INTO users(username, password, role, platform, display_name) "
                   "VALUES('fb_wb3_old', 'x', 'user', 'fb', '旧主')")
        old_uid = db.execute("SELECT last_insert_rowid()").fetchone()[0]
        db.execute("INSERT INTO fb_accounts(name, account_id, owner_id) VALUES('户','WB-3',?)",
                   (old_uid,))
        aid = db.execute("SELECT last_insert_rowid()").fetchone()[0]
        db.commit()
        db.close()

        r = client.put(f"/api/fb/accounts/{aid}/reassign", headers=h, json={})

        assert r.status_code == 200, r.get_json()
        db = database.get_db()
        owner = db.execute("SELECT owner_id FROM fb_accounts WHERE id=?",
                           (aid,)).fetchone()["owner_id"]
        db.close()
        assert owner == dev, "归属应改成调用者自己"
        assert rows_calls == [("fb", ["WB-3"])], rows_calls
        assert len(acc_calls) == 1 and acc_calls[0][0] == "fb", acc_calls
        assert acc_calls[0][2] == "旧主转fb_wb3", acc_calls

    def test_plain_user_cannot_trigger_writeback(self, client, monkeypatch):
        """非跨用户角色改**别人**的户 → 403，且不触发任何回写（归属不可能变）。"""
        rows_calls, acc_calls = [], []
        monkeypatch.setattr(hd, "writeback_rows",
                            lambda uid, plat, ids=None: rows_calls.append((plat, ids)))
        monkeypatch.setattr(hd, "writeback_fb_acceptor",
                            lambda uid, plat, aid, note: acc_calls.append((plat, aid, note)))
        h, _ = _fb_loginable_user(client, "fb_wb4", role="user")
        db = database.get_db()
        db.execute("INSERT INTO users(username, password, role, platform) "
                   "VALUES('fb_wb4_own', 'x', 'user', 'fb')")
        other = db.execute("SELECT last_insert_rowid()").fetchone()[0]
        db.execute("INSERT INTO fb_accounts(name, account_id, owner_id) VALUES('户','WB-4',?)",
                   (other,))
        aid = db.execute("SELECT last_insert_rowid()").fetchone()[0]
        db.commit()
        db.close()

        r = client.put(f"/api/fb/accounts/{aid}/reassign", headers=h, json={})

        assert r.status_code == 403, r.get_json()
        assert rows_calls == [] and acc_calls == []

    def test_create_with_acceptor_directed_writes_column_i(self, client, monkeypatch):
        """建号时填了接户人 → 必须定向补写 I 列（列值原样透传）。

        「接户运营」不在批量回写范围（`cells_for_row` 跳过 I 列），只靠 writeback_rows
        的话表里那一格永远是空的 —— 去掉这条定向调用本用例必红。
        """
        rows_calls, acc_calls = [], []
        monkeypatch.setattr(hd, "writeback_rows",
                            lambda uid, plat, ids=None: rows_calls.append((plat, ids)))
        monkeypatch.setattr(hd, "writeback_fb_acceptor",
                            lambda uid, plat, aid, note: acc_calls.append((plat, aid, note)))
        h, _ = _fb_loginable_user(client, "fb_wb5")

        r = client.post("/api/fb/accounts/create", headers=h,
                        json={"name": "户wb5", "account_id": "100005", "acceptor": "张三"})

        assert r.status_code == 200, r.get_json()
        assert rows_calls == [("fb", ["100005"])], rows_calls
        assert acc_calls == [("fb", "100005", "张三")], acc_calls
        db = database.get_db()
        stored = db.execute("SELECT acceptor FROM fb_accounts WHERE account_id='100005'"
                            ).fetchone()["acceptor"]
        db.close()
        assert stored == "张三"

    def test_create_without_acceptor_skips_directed_write(self, client, monkeypatch):
        """接户人为空 → 不调定向写（不得凭空往 I 列写串）。"""
        rows_calls, acc_calls = [], []
        monkeypatch.setattr(hd, "writeback_rows",
                            lambda uid, plat, ids=None: rows_calls.append((plat, ids)))
        monkeypatch.setattr(hd, "writeback_fb_acceptor",
                            lambda uid, plat, aid, note: acc_calls.append((plat, aid, note)))
        h, _ = _fb_loginable_user(client, "fb_wb6")

        r = client.post("/api/fb/accounts/create", headers=h,
                        json={"name": "户wb6", "account_id": "100006"})

        assert r.status_code == 200, r.get_json()
        assert rows_calls == [("fb", ["100006"])], rows_calls
        assert acc_calls == [], acc_calls

    def test_update_with_acceptor_directed_writes_column_i(self, client, monkeypatch):
        """编辑时提交了接户人 → 同样定向补写 I 列。"""
        rows_calls, acc_calls = [], []
        monkeypatch.setattr(hd, "writeback_rows",
                            lambda uid, plat, ids=None: rows_calls.append((plat, ids)))
        monkeypatch.setattr(hd, "writeback_fb_acceptor",
                            lambda uid, plat, aid, note: acc_calls.append((plat, aid, note)))
        h, uid = _fb_loginable_user(client, "fb_wb7")
        db = database.get_db()
        db.execute("INSERT INTO fb_accounts(name, account_id, owner_id) VALUES('户','WB-7',?)",
                   (uid,))
        aid = db.execute("SELECT last_insert_rowid()").fetchone()[0]
        db.commit()
        db.close()

        r = client.put(f"/api/fb/accounts/{aid}", headers=h,
                       json={"name": "户改", "account_id": "WB-7", "acceptor": "李四"})

        assert r.status_code == 200, r.get_json()
        assert rows_calls == [("fb", ["WB-7"])], rows_calls
        assert acc_calls == [("fb", "WB-7", "李四")], acc_calls

    def test_update_without_acceptor_skips_directed_write(self, client, monkeypatch):
        """编辑时不传接户人 → 不调定向写（helper 对空串也早退，这里显式钉住不调）。"""
        rows_calls, acc_calls = [], []
        monkeypatch.setattr(hd, "writeback_rows",
                            lambda uid, plat, ids=None: rows_calls.append((plat, ids)))
        monkeypatch.setattr(hd, "writeback_fb_acceptor",
                            lambda uid, plat, aid, note: acc_calls.append((plat, aid, note)))
        h, uid = _fb_loginable_user(client, "fb_wb8")
        db = database.get_db()
        db.execute("INSERT INTO fb_accounts(name, account_id, owner_id) VALUES('户','WB-8',?)",
                   (uid,))
        aid = db.execute("SELECT last_insert_rowid()").fetchone()[0]
        db.commit()
        db.close()

        r = client.put(f"/api/fb/accounts/{aid}", headers=h,
                       json={"name": "户改", "account_id": "WB-8", "acceptor": ""})

        assert r.status_code == 200, r.get_json()
        assert rows_calls == [("fb", ["WB-8"])], rows_calls
        assert acc_calls == [], acc_calls

    def test_reassign_syncs_db_acceptor_with_sheet(self, client, monkeypatch):
        """reassign 必须**库表同串**：acceptor 列与 I 列写的是同一个换绑串。

        单用户分支（developer 对别人名下的户、不带 owner_id 转给自己）。
        改前库里的 acceptor 恒为改前值（NULL），本用例必红。
        """
        rows_calls, acc_calls = [], []
        monkeypatch.setattr(hd, "writeback_rows",
                            lambda uid, plat, ids=None: rows_calls.append((plat, ids)))
        monkeypatch.setattr(hd, "writeback_fb_acceptor",
                            lambda uid, plat, aid, note: acc_calls.append((plat, aid, note)))
        h, _dev = _fb_loginable_user(client, "fb_wb9", role="developer")
        db = database.get_db()
        db.execute("INSERT INTO users(username, password, role, platform, display_name) "
                   "VALUES('fb_wb9_old', 'x', 'user', 'fb', '旧主')")
        old_uid = db.execute("SELECT last_insert_rowid()").fetchone()[0]
        db.execute("INSERT INTO fb_accounts(name, account_id, owner_id) VALUES('户','WB-9',?)",
                   (old_uid,))
        aid = db.execute("SELECT last_insert_rowid()").fetchone()[0]
        db.commit()
        db.close()

        r = client.put(f"/api/fb/accounts/{aid}/reassign", headers=h, json={})

        assert r.status_code == 200, r.get_json()
        db = database.get_db()
        stored = db.execute("SELECT acceptor FROM fb_accounts WHERE id=?",
                            (aid,)).fetchone()["acceptor"]
        db.close()
        assert stored == "旧主转fb_wb9", stored
        assert acc_calls == [("fb", "WB-9", "旧主转fb_wb9")], acc_calls
        # 库表同串：库里的值就是传给回写帮助函数的那一串
        assert stored == acc_calls[0][2]

    def test_reassign_cross_user_syncs_db_acceptor_with_sheet(self, client, monkeypatch):
        """跨用户分支（带 owner_id）同样库表同串 —— 两条分支共用同一个 note。"""
        rows_calls, acc_calls = [], []
        monkeypatch.setattr(hd, "writeback_rows",
                            lambda uid, plat, ids=None: rows_calls.append((plat, ids)))
        monkeypatch.setattr(hd, "writeback_fb_acceptor",
                            lambda uid, plat, aid, note: acc_calls.append((plat, aid, note)))
        h, _dev = _fb_loginable_user(client, "fb_wb10", role="developer")
        db = database.get_db()
        db.execute("INSERT INTO users(username, password, role, platform, display_name) "
                   "VALUES('fb_wb10_old', 'x', 'user', 'fb', '旧主十')")
        old_uid = db.execute("SELECT last_insert_rowid()").fetchone()[0]
        db.execute("INSERT INTO users(username, password, role, platform, display_name) "
                   "VALUES('fb_wb10_new', 'x', 'user', 'fb', '新主十')")
        new_uid = db.execute("SELECT last_insert_rowid()").fetchone()[0]
        db.execute("INSERT INTO fb_accounts(name, account_id, owner_id) VALUES('户','WB-10',?)",
                   (old_uid,))
        aid = db.execute("SELECT last_insert_rowid()").fetchone()[0]
        db.commit()
        db.close()

        r = client.put(f"/api/fb/accounts/{aid}/reassign", headers=h,
                       json={"owner_id": new_uid})

        assert r.status_code == 200, r.get_json()
        db = database.get_db()
        stored = db.execute("SELECT acceptor FROM fb_accounts WHERE id=?",
                            (aid,)).fetchone()["acceptor"]
        owner = db.execute("SELECT owner_id FROM fb_accounts WHERE id=?",
                           (aid,)).fetchone()["owner_id"]
        db.close()
        assert owner == new_uid
        assert stored == "旧主十转新主十", stored
        assert acc_calls == [("fb", "WB-10", "旧主十转新主十")], acc_calls
