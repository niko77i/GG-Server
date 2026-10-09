"""GG 看板同步：认领他人账户 + 已存在账户不再误当新增（Task 1）。

根因回归：`accounts.account_id` 是**全局 UNIQUE**，但同步查「系统里有没有」时带了
`AND a.owner_id = ?`（只看自己的）⇒ 别人的账户被当成「系统没有」、归入 `to_create`，
确认后 `INSERT` 撞唯一约束抛异常。本文件守卫：**已存在的 account_id（不论归属、
是否软删）绝不进 `to_create`**，而是进 `to_claim`。

Google Sheets 一律打桩（`build_service` / `read_sheet_values`），认领触发的两次
户管看板回写也拍成桩，既不落网也可断言。
"""
import database
import huguan_dashboard as hd


# ---------- 夹具 ----------

def _user(client, username, role="user"):
    """注册 → 改 role/platform/display_name → 登录。返回 (headers, user_id)。

    display_name 必须设：sync 的门禁（A 列运营）要拿它跟表里 operator 比对。
    """
    client.post("/api/auth/register", json={"username": username, "password": "test123"})
    db = database.get_db()
    db.execute("UPDATE users SET role=?, platform='gg', display_name=? WHERE username=?",
               (role, username, username))
    db.commit()
    uid = db.execute("SELECT id FROM users WHERE username=?", (username,)).fetchone()["id"]
    db.close()
    resp = client.post("/api/auth/login", json={"username": username, "password": "test123"})
    return {"Authorization": f"Bearer {resp.get_json()['access_token']}"}, uid


def _seed_user(db, username, display_name):
    """造一个「他人」用户（归属人）。"""
    db.execute("INSERT INTO users(username, password, role, display_name, platform) "
               "VALUES(?,?,?,?, 'gg')", (username, "x", "user", display_name))
    db.commit()
    return db.execute("SELECT id FROM users WHERE username=?", (username,)).fetchone()["id"]


def _seed_account(db, account_id, owner_id, **over):
    cols = {"account_id": account_id, "name": account_id, "owner_id": owner_id,
            "timezone": "", "death_date": "", "deleted_at": None}
    cols.update(over)
    keys = ", ".join(cols)
    marks = ", ".join("?" for _ in cols)
    db.execute(f"INSERT INTO accounts({keys}) VALUES({marks})", tuple(cols.values()))
    db.commit()
    return db.execute("SELECT id FROM accounts WHERE account_id=?", (account_id,)).fetchone()["id"]


def _setup_sheet(db):
    """配好表格 ID 与看板 sheet 名，让三道闸门都不提前 return。"""
    db.execute("INSERT OR REPLACE INTO tags(key,value) VALUES('recharge_sheet_id','SHEET_X')")
    db.execute("INSERT OR REPLACE INTO tags(key,value) VALUES"
               "('sheet_mappings', '{\"my_dashboard\": \"我的看板\"}')")
    db.commit()


_HEADER = ["运营", "账户ID", "所属渠道", "国家", "时区", "备注", "是否封户", "是否解绑"]


def _row(operator, account_id, blocked=""):
    # A运营 B账户ID C渠道 D国家 E时区 F备注 G是否封户 H是否解绑
    return [operator, account_id, "", "", "", "", blocked, ""]


def _stub_sheets(monkeypatch, rows):
    import google_sheets_service as gs
    import main as m
    monkeypatch.setattr(m, "_GOOGLE_SHEETS_CONFIG", {"credentials_path": __file__})
    monkeypatch.setattr(gs, "build_service", lambda path: object())
    monkeypatch.setattr(gs, "read_sheet_values", lambda *a, **k: rows)


def _stub_writeback(monkeypatch):
    """拦住户管看板回写（不落网、可断言）。返回捕获容器。"""
    calls = {"rows": [], "channel": []}
    monkeypatch.setattr(
        hd, "writeback_rows",
        lambda uid, platform, ids=None: calls["rows"].append((platform, list(ids or []))))
    monkeypatch.setattr(
        hd, "writeback_owner_channel",
        lambda uid, platform, acct, new_owner, text=None:
        calls["channel"].append((platform, acct, new_owner)))
    return calls


def _post_sync(client, headers, **body):
    return client.post("/api/accounts/sync-from-sheet", headers=headers, json=body)


# ---------- 用例 ----------

def test_other_users_account_goes_to_claim_not_create(client, monkeypatch):
    """他人账户不进 to_create、进 to_claim，且带归属人显示名。"""
    h, uid = _user(client, "_cl_other")
    db = database.get_db()
    _setup_sheet(db)
    other = _seed_user(db, "_cl_other_owner", "拉菲")
    aid = _seed_account(db, "403-400-6011", other)
    db.close()
    _stub_sheets(monkeypatch, [_HEADER, _row("_cl_other", "403-400-6011")])

    resp = _post_sync(client, h, dry_run=True)
    assert resp.status_code == 200, resp.get_json()
    body = resp.get_json()
    diff = body["diff"]

    assert "403-400-6011" not in {a["account_id"] for a in diff["to_create"]}
    claim = {a["account_id"]: a for a in diff["to_claim"]}
    assert "403-400-6011" in claim
    assert claim["403-400-6011"]["owner_name"] == "拉菲"
    assert claim["403-400-6011"]["existing_id"] == aid
    assert claim["403-400-6011"]["owner_id"] == other
    assert claim["403-400-6011"]["deleted"] is False
    assert body["summary"]["claimable"] == 1


def test_soft_deleted_other_account_goes_to_claim(client, monkeypatch):
    """软删的他人账户：同样进 to_claim 且 deleted 为真，绝不进 to_create。

    这是防「第二个同样的坑」：软删的他人账户既不在 existing_map（owner 不符），
    若 to_claim 也不收，它就两边不沾、掉进 to_create 撞全局唯一约束。
    """
    h, uid = _user(client, "_cl_soft")
    db = database.get_db()
    _setup_sheet(db)
    other = _seed_user(db, "_cl_soft_owner", "拉菲")
    aid = _seed_account(db, "SD-400-6011", other, deleted_at="2026-01-01 00:00:00")
    db.close()
    _stub_sheets(monkeypatch, [_HEADER, _row("_cl_soft", "SD-400-6011")])

    resp = _post_sync(client, h, dry_run=True)
    assert resp.status_code == 200, resp.get_json()
    diff = resp.get_json()["diff"]

    assert "SD-400-6011" not in {a["account_id"] for a in diff["to_create"]}
    claim = {a["account_id"]: a for a in diff["to_claim"]}
    assert "SD-400-6011" in claim
    assert claim["SD-400-6011"]["deleted"] is True
    assert claim["SD-400-6011"]["existing_id"] == aid


def test_own_account_unaffected(client, monkeypatch):
    """自己的账户仍走原逻辑（状态变更→to_update、无变化→unchanged），不在 to_claim。"""
    h, uid = _user(client, "_cl_own")
    db = database.get_db()
    _setup_sheet(db)
    _seed_account(db, "OWN-UPD", uid)
    _seed_account(db, "OWN-OK", uid)
    db.close()
    _stub_sheets(monkeypatch, [
        _HEADER,
        _row("_cl_own", "OWN-UPD", "是"),   # 封户=是、当前存活 → 需变更状态
        _row("_cl_own", "OWN-OK", "否"),    # 封户=否、当前存活 → 无变化
    ])

    resp = _post_sync(client, h, dry_run=True)
    assert resp.status_code == 200, resp.get_json()
    diff = resp.get_json()["diff"]

    assert {a["account_id"] for a in diff["to_update"]} == {"OWN-UPD"}
    assert diff["unchanged"] == 1
    assert diff["to_claim"] == []
    assert {a["account_id"] for a in diff["to_create"]} == set()


def test_claim_executes_reassign(client, monkeypatch):
    """dry_run=false + confirmed.claim → 账户 owner_id 变为调用者；两次回写被触发。"""
    h, uid = _user(client, "_cl_exec", role="huguan")
    db = database.get_db()
    _setup_sheet(db)
    other = _seed_user(db, "_cl_exec_owner", "拉菲")
    aid = _seed_account(db, "CLAIM-1", other)
    _seed_account(db, "OWN-2", uid)          # 陪跑：让一般回写的 id 列表与认领腿区分
    db.close()
    _stub_sheets(monkeypatch, [
        _HEADER,
        _row("_cl_exec", "CLAIM-1"),
        _row("_cl_exec", "OWN-2", "否"),
    ])
    calls = _stub_writeback(monkeypatch)

    resp = _post_sync(client, h, dry_run=False, confirmed={"claim": ["CLAIM-1"]})
    assert resp.status_code == 200, resp.get_json()
    assert resp.get_json()["result"]["claimed"] == 1

    db = database.get_db()
    owner = db.execute("SELECT owner_id FROM accounts WHERE id=?", (aid,)).fetchone()["owner_id"]
    db.close()
    assert owner == uid

    # 认领腿只回写被认领的账户；一般同步腿回写整片 sheet_ids（含陪跑）
    assert calls["rows"][0] == ("gg", ["CLAIM-1"])
    # 归属变更通道列（H「重新分配」）只由认领腿写，值为新归属
    assert calls["channel"] == [("gg", "CLAIM-1", uid)]


def test_claim_denied_for_non_cross_user_role(client, monkeypatch):
    """非跨用户角色发认领 → owner_id 不变，且该条有错误（不静默丢弃）。"""
    h, uid = _user(client, "_cl_deny", role="user")
    db = database.get_db()
    _setup_sheet(db)
    other = _seed_user(db, "_cl_deny_owner", "拉菲")
    aid = _seed_account(db, "DENY-1", other)
    db.close()
    _stub_sheets(monkeypatch, [_HEADER, _row("_cl_deny", "DENY-1")])
    _stub_writeback(monkeypatch)

    resp = _post_sync(client, h, dry_run=False, confirmed={"claim": ["DENY-1"]})
    assert resp.status_code == 200, resp.get_json()
    result = resp.get_json()["result"]
    assert result["claimed"] == 0
    assert any(e["account_id"] == "DENY-1" for e in result["errors"])

    db = database.get_db()
    owner = db.execute("SELECT owner_id FROM accounts WHERE id=?", (aid,)).fetchone()["owner_id"]
    db.close()
    assert owner == other
