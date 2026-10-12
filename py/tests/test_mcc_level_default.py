"""MCC 等级留空必须落到 id=1 —— 「建不了 MCC」的红钉。

起因（2026-10-12）：用户放开普通用户账户区后实测，点「➕ 新增 MCC」保存得到
`POST /api/mcc/create → 409`，看似权限被拒，实为一条对所有角色都成立的 bug：

1. `MccModal.vue` 的 `form.level_id` 初值是**空字符串 `''`**（不是 null），未选等级就原样提交；
2. `mcc.level_id` 是 `level_id INTEGER REFERENCES mcc_levels(id)`（`database.py:348` 迁移列），
   空串插进去 → `FOREIGN KEY constraint failed`；
3. 该 IntegrityError 被 `except _sqlite3.IntegrityError` 兜住，**统一误报**成
   「MCC ID 'xxx' 已存在」409 —— 排查方向被彻底带偏。

且这跟角色无关：本机 `mcc_levels` 表**一行都没有**（全新库），等级下拉对 admin /
developer / user 都是空的，谁点谁 409。

用户 2026-10-12 裁定口径：**空就默认为 1，id=1 不存在就补建 id=1**。

本文件钉住：
- 空值（`''` / `None` / 指向已删等级）一律落到 id=1，且不 409/500；
- id=1 不存在时被补建；
- **对照腿**：指向真实存在的等级时原样使用（不许被无脑改成 1）；
- 真重复的 MCC ID 仍是 409，且文案准确。
"""
import os
import sys

_py_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _py_dir not in sys.path:
    sys.path.insert(0, _py_dir)

import database  # noqa: E402


def _mk_level(db, level_id, name, owner_id):
    db.execute("INSERT INTO mcc_levels(id, name, owner_id) VALUES(?,?,?)", (level_id, name, owner_id))
    db.commit()


def _uid(db, username="testuser"):
    return db.execute("SELECT id FROM users WHERE username=?", (username,)).fetchone()["id"]


# ---------- 红钉：空值必须能建出 MCC ----------

def test_empty_string_level_id_builds_mcc_and_lands_on_one(client, auth_headers):
    """前端未选等级时提交的就是空串 —— 这条以前必然 409。"""
    r = client.post("/api/mcc/create",
                    json={"name": "甲 MCC", "mcc_id": "111-222-3333", "level_id": ""},
                    headers=auth_headers)
    assert r.status_code == 200, r.get_json()
    assert r.get_json()["success"] is True

    db = database.get_db()
    row = db.execute("SELECT level_id FROM mcc WHERE mcc_id='111-222-3333'").fetchone()
    assert row["level_id"] == 1, "空等级应落到 id=1"
    assert db.execute("SELECT 1 FROM mcc_levels WHERE id=1").fetchone() is not None, "id=1 应被补建"
    db.close()


def test_missing_level_id_also_lands_on_one(client, auth_headers):
    """完全不传 level_id（None）与传空串同口径。"""
    r = client.post("/api/mcc/create",
                    json={"name": "乙 MCC", "mcc_id": "222-333-4444"},
                    headers=auth_headers)
    assert r.status_code == 200, r.get_json()

    db = database.get_db()
    assert db.execute("SELECT level_id FROM mcc WHERE mcc_id='222-333-4444'").fetchone()["level_id"] == 1
    db.close()


def test_dangling_level_id_lands_on_one_instead_of_409(client, auth_headers):
    """指向已被删除的等级 id —— 同样不许 409，落回 id=1。"""
    r = client.post("/api/mcc/create",
                    json={"name": "丙 MCC", "mcc_id": "333-444-5555", "level_id": 99999},
                    headers=auth_headers)
    assert r.status_code == 200, r.get_json()

    db = database.get_db()
    assert db.execute("SELECT level_id FROM mcc WHERE mcc_id='333-444-5555'").fetchone()["level_id"] == 1
    db.close()


def test_default_level_is_created_once(client, auth_headers):
    """补建 id=1 必须幂等 —— 连建两个 MCC 不能多出几行，也不能撞 UNIQUE(name, owner_id)。"""
    for i, mid in enumerate(["444-555-6666", "555-666-7777"]):
        r = client.post("/api/mcc/create",
                        json={"name": f"MCC{i}", "mcc_id": mid, "level_id": ""},
                        headers=auth_headers)
        assert r.status_code == 200, r.get_json()

    db = database.get_db()
    n = db.execute("SELECT COUNT(*) FROM mcc_levels WHERE id=1").fetchone()[0]
    assert n == 1, "id=1 只应有一行"
    db.close()


def test_default_level_created_when_name_already_taken(client, auth_headers):
    """本人名下已有名为「一级」的等级（但 id≠1）时，补建 id=1 不得撞 UNIQUE(name, owner_id)。"""
    db = database.get_db()
    uid = _uid(db)
    _mk_level(db, 7, "一级", uid)          # 同名、非 1 号
    db.close()

    r = client.post("/api/mcc/create",
                    json={"name": "丁 MCC", "mcc_id": "666-777-8888", "level_id": ""},
                    headers=auth_headers)
    assert r.status_code == 200, r.get_json()

    db = database.get_db()
    assert db.execute("SELECT level_id FROM mcc WHERE mcc_id='666-777-8888'").fetchone()["level_id"] == 1
    assert db.execute("SELECT COUNT(*) FROM mcc_levels WHERE id=1").fetchone()[0] == 1
    db.close()


# ---------- 对照腿：不许把「有效等级」也改成 1 ----------

def test_valid_level_id_is_kept(client, auth_headers):
    """对照腿：选了真实存在的等级就用它。没有这条，把 level_id 一律写死 1 也能骗过上面全部用例。"""
    db = database.get_db()
    uid = _uid(db)
    _mk_level(db, 42, "三级", uid)
    db.close()

    r = client.post("/api/mcc/create",
                    json={"name": "戊 MCC", "mcc_id": "777-888-9999", "level_id": 42},
                    headers=auth_headers)
    assert r.status_code == 200, r.get_json()

    db = database.get_db()
    assert db.execute("SELECT level_id FROM mcc WHERE mcc_id='777-888-9999'").fetchone()["level_id"] == 42
    db.close()


def test_level_id_as_numeric_string_is_kept(client, auth_headers):
    """前端 el-select 的 value 可能是字符串形式的数字 —— 也要认。"""
    db = database.get_db()
    uid = _uid(db)
    _mk_level(db, 43, "四级", uid)
    db.close()

    r = client.post("/api/mcc/create",
                    json={"name": "己 MCC", "mcc_id": "888-999-0000", "level_id": "43"},
                    headers=auth_headers)
    assert r.status_code == 200, r.get_json()

    db = database.get_db()
    assert db.execute("SELECT level_id FROM mcc WHERE mcc_id='888-999-0000'").fetchone()["level_id"] == 43
    db.close()


# ---------- 编辑路径同样归一（旧实现会 500） ----------

def test_update_with_empty_level_id_is_normalized(client, auth_headers):
    """编辑 MCC 时清空等级 ⇒ 同样落到 id=1，不是 500。"""
    r = client.post("/api/mcc/create",
                    json={"name": "庚 MCC", "mcc_id": "999-000-1111", "level_id": ""},
                    headers=auth_headers)
    assert r.status_code == 200, r.get_json()
    mid = r.get_json()["id"]

    r = client.put(f"/api/mcc/{mid}",
                   json={"name": "庚 MCC 改名", "level_id": "", "parent_mcc_id": None},
                   headers=auth_headers)
    assert r.status_code == 200, r.get_json()

    db = database.get_db()
    assert db.execute("SELECT level_id FROM mcc WHERE id=?", (mid,)).fetchone()["level_id"] == 1
    db.close()


# ---------- 真重复仍是 409 ----------

def test_duplicate_mcc_id_still_conflicts(client, auth_headers):
    """对照腿：真的重复 MCC ID 仍是 409（归一等级不许把重复检查一并放过）。"""
    payload = {"name": "辛 MCC", "mcc_id": "123-456-7890", "level_id": ""}
    assert client.post("/api/mcc/create", json=payload, headers=auth_headers).status_code == 200

    r = client.post("/api/mcc/create", json=payload, headers=auth_headers)
    assert r.status_code == 409
    assert "已" in r.get_json()["error"]
