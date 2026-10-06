# FB 资产数据模型 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 FB 户管看板需要的 10 个字段与两张公用词表落进数据库，并补上 FB 缺失的归属变更端点。

**Architecture:** 纯增量。数据库层走既有的幂等迁移口子（`_ensure_schema` 建表 + `_ensure_columns` 补列），不新造迁移机制；接口层比照同族既有端点（`/api/statuses/*`、`/api/tt/accounts/<aid>/reassign`）逐条对齐；前端沿用 GG/TT 既有组件样式，不做独立视觉设计。

**Tech Stack:** Python 3 + Flask + sqlite3（原生 SQL，无 ORM）；Vue 3 + Element Plus + Pinia；pytest + Flask test client。

## Global Constraints

- 设计依据：`docs/superpowers/specs/2026-10-06-fb-asset-data-model-design.md`。与本文冲突时以该 spec 为准。
- **纯增量**：不得修改 `fb_accounts` / `fb_account_bm` 建表语句里的既有列，只做 `ADD COLUMN` 与新建表。
- **UI 不走 `/frontend-design`**（spec 决策 9，用户 2026-10-06 明确豁免）：沿用 GG/TT 既有样式。
- `fb_accounts` 新增的 10 列一律**可空**（`TEXT DEFAULT ''` 或 `NULL`），存量行取默认值，行为与改动前一致。
  （`fb_account_bm.is_primary` 是另一张表上的 `INTEGER NOT NULL DEFAULT 0` —— 它是新列，
  存量行一律取 0，同样不改变既有行为；不适用「可空」这条。）
- SQL 里插值的表名 / 列名**必须是代码内常量**（`fb_channels`、`channel_id` 等），绝不来自请求体。参数一律走 `?` 占位符。
- 测试门禁：`cd py && python -m pytest tests/ -q`，只增不减。
- 前端门禁：`cd frontend && npm run build` 通过。
- 提交时**只 `git add` 本任务明确列出的文件**，禁止 `git add -A`（本仓库常有并行会话在途改文件）。

---

## File Structure

| 文件 | 动作 | 职责 |
|---|---|---|
| `py/database.py` | 修改 | `_ensure_schema` 建两张公用词表；`_ensure_columns` 补 10 列 + `is_primary` + 部分唯一索引 |
| `py/main.py` | 修改 | 新增 `/api/fb-channels/*`、`/api/fb-asset-types/*` 两组 CRUD |
| `py/routes/fb_routes.py` | 修改 | 账户 create/update/list 承载新字段；`operator` 冻结；新增 `reassign`；`_set_primary_bm` 辅助 |
| `py/tests/test_fb_asset_model.py` | 新建 | 本子项目的全部后端测试 |
| `frontend/src/api/fb.js` | 修改 | 补 `reassign` 与两组词表的 API 封装 |
| `frontend/src/views/fb/FbAccountPanel.vue` | 修改 | 表格列 + 编辑表单扩充 |
| `frontend/src/views/fb/FbSettingsPanel.vue` | 修改 | 新增两张词表卡片 |

---

## Task 1: 数据库迁移

**Files:**
- Modify: `py/database.py`（`_ensure_schema` 内 `fb_account_bm_history` 建表之后；`_ensure_columns` 内 `_add_column_if_missing(conn, "copywritings", "is_public", ...)` 那一行之后）
- Test: `py/tests/test_fb_asset_model.py`（新建）

**Interfaces:**
- Consumes: 无
- Produces: `fb_accounts` 的 10 个新列（`operator` / `channel_id` / `asset_type_id` / `unit_price` / `inbound_qty` / `acceptor_id` / `outbound_date` / `outbound_qty` / `consumption` / `remark`）；表 `fb_channels` 与 `fb_asset_types`（列：`id, name, owner_id, platform, created_at`，约束 `UNIQUE(name, platform)`）；`fb_account_bm.is_primary` 列；索引 `idx_fb_account_bm_primary`

- [ ] **Step 1: 写失败测试**

新建 `py/tests/test_fb_asset_model.py`：

```python
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
```

- [ ] **Step 2: 跑测试确认失败**

```bash
cd py && python -m pytest tests/test_fb_asset_model.py -q
```

Expected: FAIL —— `fb_accounts 缺列 operator`，以及 `no such table: fb_channels`。

- [ ] **Step 3: 建两张公用词表**

在 `py/database.py` 的 `_ensure_schema` 内，`CREATE TABLE IF NOT EXISTS fb_account_bm_history (...)` 那一块**之后**插入：

```sql
        -- FB 资产公用词表（子项目 ①，2026-10-06）：所属渠道 / 资产类型。
        -- 形状照 account_statuses 的 UNIQUE(name, platform)——「公用」指名字全平台唯一，
        -- owner_id 只记「谁先建的」，不参与查重。**刻意不复用 agents**：agents 的
        -- UNIQUE 是 (name, owner_id, platform)，同名会落两行，而看板同步的
        -- 「唯一命中才落库」口径会让那一列永远同步不上。
        CREATE TABLE IF NOT EXISTS fb_channels (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            name       TEXT NOT NULL,
            owner_id   INTEGER REFERENCES users(id),
            platform   TEXT DEFAULT 'fb',
            created_at TEXT DEFAULT (datetime('now','localtime')),
            UNIQUE(name, platform)
        );

        CREATE TABLE IF NOT EXISTS fb_asset_types (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            name       TEXT NOT NULL,
            owner_id   INTEGER REFERENCES users(id),
            platform   TEXT DEFAULT 'fb',
            created_at TEXT DEFAULT (datetime('now','localtime')),
            UNIQUE(name, platform)
        );
```

- [ ] **Step 4: 补 10 个新列 + 主 BM 标记与索引**

在 `py/database.py` 的 `_ensure_columns` 内，`_add_column_if_missing(conn, "copywritings", "is_public", "is_public INTEGER DEFAULT 0")` 那一行**之后**插入：

```python
    # FB 资产数据模型（子项目 ①，2026-10-06）：10 个新列。
    # 全部可空 —— 存量行取默认值，列表 / 编辑 / 删除行为与改动前一致。
    # ⚠️ channel_id / asset_type_id 的 REFERENCES 指向上面 _ensure_schema 建的
    # fb_channels / fb_asset_types。get_db 的调用顺序是 _ensure_schema → _ensure_columns，
    # 同一次连接内表必定已存在。
    _add_column_if_missing(conn, "fb_accounts", "operator", "operator TEXT DEFAULT ''")
    _add_column_if_missing(conn, "fb_accounts", "channel_id",
                           "channel_id INTEGER REFERENCES fb_channels(id)")
    _add_column_if_missing(conn, "fb_accounts", "asset_type_id",
                           "asset_type_id INTEGER REFERENCES fb_asset_types(id)")
    _add_column_if_missing(conn, "fb_accounts", "unit_price", "unit_price TEXT DEFAULT ''")
    _add_column_if_missing(conn, "fb_accounts", "inbound_qty", "inbound_qty TEXT DEFAULT ''")
    _add_column_if_missing(conn, "fb_accounts", "acceptor_id",
                           "acceptor_id INTEGER REFERENCES users(id)")
    _add_column_if_missing(conn, "fb_accounts", "outbound_date", "outbound_date TEXT DEFAULT ''")
    _add_column_if_missing(conn, "fb_accounts", "outbound_qty", "outbound_qty TEXT DEFAULT ''")
    _add_column_if_missing(conn, "fb_accounts", "consumption", "consumption TEXT DEFAULT ''")
    _add_column_if_missing(conn, "fb_accounts", "remark", "remark TEXT DEFAULT ''")
    # 主 BM 标记（「位置」列的存储，规格 4.3）。部分唯一索引保证
    # 「同一账户至多一个主 BM」——**不阻止换 BM**，换法是同一事务内先清后设。
    _add_column_if_missing(conn, "fb_account_bm", "is_primary",
                           "is_primary INTEGER NOT NULL DEFAULT 0")
    if _table_exists(conn, "fb_account_bm"):
        conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_fb_account_bm_primary "
                     "ON fb_account_bm(account_id) WHERE is_primary = 1")
```

- [ ] **Step 5: 跑测试确认通过**

```bash
cd py && python -m pytest tests/test_fb_asset_model.py -q
```

Expected: PASS（全部用例）。

- [ ] **Step 6: 跑全量回归**

```bash
cd py && python -m pytest tests/ -q
```

Expected: 全绿，且总数 ≥ 改动前基线（只增不减）。

- [ ] **Step 7: 提交**

```bash
git add py/database.py py/tests/test_fb_asset_model.py
git commit -m "feat(fb): fb_accounts 补 10 列 + 两张公用词表 + 主 BM 标记

- _ensure_schema 新增 fb_channels / fb_asset_types，UNIQUE(name, platform)
- _ensure_columns 新增 operator/channel_id/asset_type_id/unit_price/inbound_qty/
  acceptor_id/outbound_date/outbound_qty/consumption/remark
- fb_account_bm.is_primary + 部分唯一索引（至多一个主 BM；换 BM 先清后设）"
```

---

## Task 2: 两张公用词表的 CRUD 接口

**Files:**
- Modify: `py/main.py`（在 `statuses_delete` 之后、`# ========== MCC Levels 选项 API ==========` 之前插入）
- Test: `py/tests/test_fb_asset_model.py`（追加）

**Interfaces:**
- Consumes: Task 1 的 `fb_channels` / `fb_asset_types` 表
- Produces: 路由 `/api/fb-channels/list|create|<id>(PUT/DELETE)` 与 `/api/fb-asset-types/list|create|<id>(PUT/DELETE)`。响应契约：
  - `GET .../list` → `{"success": true, "items": [{"id": int, "name": str}, ...]}`
  - `POST .../create` body `{"name": str}` → `{"success": true, "id": int}` / 400 空名 / 409 重名
  - `PUT .../<id>` body `{"name": str}` → `{"success": true}` / 400 / 403 / 404 / 409
  - `DELETE .../<id>` → `{"success": true}` / 403 / 404 / 409（被在用账户引用）

- [ ] **Step 1: 写失败测试**

追加到 `py/tests/test_fb_asset_model.py`：

```python
class TestSharedOptionApi:
    """两组词表端点的契约。门禁口径：list 任意已登录；create/rename/delete 需
    GLOBAL_OPTION_ROLES（与 /api/regions/* 同族）。"""

    @pytest.fixture
    def fb_admin(self, client):
        """一个 FB 平台的 admin —— GLOBAL_OPTION_ROLES 成员。"""
        client.post("/api/auth/register", json={"username": "fb_admin", "password": "t123"})
        db = database.get_db()
        db.execute("UPDATE users SET role='admin', platform='fb' WHERE username='fb_admin'")
        db.commit()
        db.close()
        token = client.post("/api/auth/login",
                            json={"username": "fb_admin", "password": "t123"}
                            ).get_json()["access_token"]
        return {"Authorization": f"Bearer {token}"}

    @pytest.fixture
    def fb_plain(self, client):
        """一个 FB 平台的普通 user —— 不在 GLOBAL_OPTION_ROLES。"""
        client.post("/api/auth/register", json={"username": "fb_plain", "password": "t123"})
        db = database.get_db()
        db.execute("UPDATE users SET platform='fb' WHERE username='fb_plain'")
        db.commit()
        db.close()
        token = client.post("/api/auth/login",
                            json={"username": "fb_plain", "password": "t123"}
                            ).get_json()["access_token"]
        return {"Authorization": f"Bearer {token}"}

    @pytest.mark.parametrize("base", ["/api/fb-channels", "/api/fb-asset-types"])
    def test_create_list_rename_delete_roundtrip(self, client, fb_admin, base):
        r = client.post(f"{base}/create", json={"name": "甲"}, headers=fb_admin)
        assert r.status_code == 200 and r.get_json()["success"] is True
        new_id = r.get_json()["id"]

        r = client.get(f"{base}/list", headers=fb_admin)
        names = [i["name"] for i in r.get_json()["items"]]
        assert "甲" in names

        r = client.put(f"{base}/{new_id}", json={"name": "乙"}, headers=fb_admin)
        assert r.status_code == 200

        r = client.delete(f"{base}/{new_id}", headers=fb_admin)
        assert r.status_code == 200

    @pytest.mark.parametrize("base", ["/api/fb-channels", "/api/fb-asset-types"])
    def test_duplicate_name_rejected(self, client, fb_admin, base):
        client.post(f"{base}/create", json={"name": "重复"}, headers=fb_admin)
        r = client.post(f"{base}/create", json={"name": "重复"}, headers=fb_admin)
        assert r.status_code == 409

    @pytest.mark.parametrize("base", ["/api/fb-channels", "/api/fb-asset-types"])
    def test_empty_name_rejected(self, client, fb_admin, base):
        r = client.post(f"{base}/create", json={"name": "   "}, headers=fb_admin)
        assert r.status_code == 400

    @pytest.mark.parametrize("base", ["/api/fb-channels", "/api/fb-asset-types"])
    def test_write_requires_option_role(self, client, fb_plain, base):
        r = client.post(f"{base}/create", json={"name": "无权"}, headers=fb_plain)
        assert r.status_code == 403

    def test_delete_blocked_while_referenced_by_live_account(self, client, fb_admin, two_users):
        r = client.post("/api/fb-channels/create", json={"name": "在用渠道"}, headers=fb_admin)
        cid = r.get_json()["id"]
        db = database.get_db()
        db.execute("INSERT INTO fb_accounts(name, account_id, owner_id, channel_id) "
                   "VALUES('户','2001',?,?)", (two_users[0], cid))
        db.commit()
        db.close()
        r = client.delete(f"/api/fb-channels/{cid}", headers=fb_admin)
        assert r.status_code == 409

    def test_delete_clears_reference_on_soft_deleted_account(self, client, fb_admin, two_users):
        """软删账户不挡删除，但引用必须被解除 —— 否则 FK 约束会让 DELETE 变 500。"""
        r = client.post("/api/fb-channels/create", json={"name": "仅软删引用"}, headers=fb_admin)
        cid = r.get_json()["id"]
        db = database.get_db()
        db.execute("INSERT INTO fb_accounts(name, account_id, owner_id, channel_id, deleted_at) "
                   "VALUES('户','2002',?,?,datetime('now','localtime'))", (two_users[0], cid))
        db.commit()
        db.close()
        r = client.delete(f"/api/fb-channels/{cid}", headers=fb_admin)
        assert r.status_code == 200
        db = database.get_db()
        left = db.execute("SELECT channel_id FROM fb_accounts WHERE account_id='2002'").fetchone()[0]
        gone = db.execute("SELECT COUNT(*) FROM fb_channels WHERE id=?", (cid,)).fetchone()[0]
        db.close()
        assert left is None and gone == 0
```

- [ ] **Step 2: 跑测试确认失败**

```bash
cd py && python -m pytest tests/test_fb_asset_model.py -q -k SharedOptionApi
```

Expected: FAIL —— 404（路由不存在）。

- [ ] **Step 3: 实现端点**

在 `py/main.py` 的 `statuses_delete` 函数之后、`# ========== MCC Levels 选项 API ==========` 之前插入：

```python
# ========== FB 公用词表 API（子项目 ①，2026-10-06）==========
#
# 「所属渠道」「资产类型」两组平台级公用词表。形状照 /api/statuses/*（本文件上方）：
# platform 取自 _get_effective_platform()，名称唯一性是 (name, platform)，
# owner_id 只记「谁先建的」、不参与查重。
#
# ⚠️ 下面 SQL 里插值的 table / ref_col 是**代码内常量**（调用点的字面量），
# 绝不来自请求体；所有值一律走 ? 占位符。

def _option_role_denied():
    """非 GLOBAL_OPTION_ROLES 返回 403 响应；放行返回 None。"""
    user = auth.get_user_by_id(int(get_jwt_identity()))
    if not user or user.get("role") not in GLOBAL_OPTION_ROLES:
        return jsonify({"success": False, "error": "权限不足，仅管理员可操作"}), 403
    return None


def _register_shared_option_api(table: str, url_base: str, ref_col: str, label: str):
    """注册一组「全平台公用词表」的 list/create/rename/delete 四个端点。

    table    —— 物理表名（fb_channels / fb_asset_types），代码内常量
    url_base —— 路由前缀
    ref_col  —— fb_accounts 上引用该表的列名，删除时用它统计 / 解除引用
    label    —— 错误文案里的中文名
    """

    @app.route(f"{url_base}/list", methods=["GET"], endpoint=f"{table}_list")
    @jwt_required()
    def _list():
        db = _yt_db()
        try:
            rows = db.execute(
                f"SELECT id, name FROM {table} WHERE platform=? ORDER BY id",
                (_get_effective_platform(),)).fetchall()
            return jsonify({"success": True, "items": [dict(r) for r in rows]})
        finally:
            db.close()

    @app.route(f"{url_base}/create", methods=["POST"], endpoint=f"{table}_create")
    @jwt_required()
    def _create():
        denied = _option_role_denied()
        if denied:
            return denied
        data = request.get_json(silent=True) or {}
        name = (data.get("name") or "").strip()
        if not name:
            return jsonify({"success": False, "error": "名称不能为空"}), 400
        platform = _get_effective_platform()
        db = _yt_db()
        try:
            if db.execute(f"SELECT id FROM {table} WHERE name=? AND platform=?",
                          (name, platform)).fetchone():
                return jsonify({"success": False, "error": f"{label}「{name}」已存在"}), 409
            user_id = int(get_jwt_identity())
            db.execute(f"INSERT INTO {table}(name, owner_id, platform) VALUES(?,?,?)",
                       (name, user_id, platform))
            db.commit()
            new_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]
            return jsonify({"success": True, "id": new_id})
        finally:
            db.close()

    @app.route(f"{url_base}/<int:oid>", methods=["PUT"], endpoint=f"{table}_rename")
    @jwt_required()
    def _rename(oid):
        denied = _option_role_denied()
        if denied:
            return denied
        data = request.get_json(silent=True) or {}
        name = (data.get("name") or "").strip()
        if not name:
            return jsonify({"success": False, "error": "名称不能为空"}), 400
        platform = _get_effective_platform()
        db = _yt_db()
        try:
            if not db.execute(f"SELECT id FROM {table} WHERE id=?", (oid,)).fetchone():
                return jsonify({"success": False, "error": f"{label}不存在"}), 404
            if db.execute(f"SELECT id FROM {table} WHERE name=? AND platform=? AND id!=?",
                          (name, platform, oid)).fetchone():
                return jsonify({"success": False, "error": f"{label}「{name}」已存在"}), 409
            db.execute(f"UPDATE {table} SET name=? WHERE id=?", (name, oid))
            db.commit()
            return jsonify({"success": True})
        finally:
            db.close()

    @app.route(f"{url_base}/<int:oid>", methods=["DELETE"], endpoint=f"{table}_delete")
    @jwt_required()
    def _delete(oid):
        denied = _option_role_denied()
        if denied:
            return denied
        db = _yt_db()
        try:
            if not db.execute(f"SELECT id FROM {table} WHERE id=?", (oid,)).fetchone():
                return jsonify({"success": False, "error": f"{label}不存在"}), 404
            live = db.execute(
                f"SELECT COUNT(*) FROM fb_accounts WHERE {ref_col}=? AND deleted_at IS NULL",
                (oid,)).fetchone()[0]
            if live > 0:
                return jsonify({"success": False,
                                "error": f"无法删除：被 {live} 个账户引用，请先解除关联"}), 409
            # 软删账户不挡删除，但引用必须显式解除：fb_accounts.<ref_col> 是
            # REFERENCES，连接开着 PRAGMA foreign_keys=ON，留着悬挂引用会让
            # DELETE 抛 FOREIGN KEY constraint failed 变成 500。
            db.execute(f"UPDATE fb_accounts SET {ref_col}=NULL WHERE {ref_col}=?", (oid,))
            db.execute(f"DELETE FROM {table} WHERE id=?", (oid,))
            db.commit()
            return jsonify({"success": True})
        finally:
            db.close()


_register_shared_option_api("fb_channels", "/api/fb-channels", "channel_id", "渠道")
_register_shared_option_api("fb_asset_types", "/api/fb-asset-types", "asset_type_id", "资产类型")
```

> **放在 `main.py` 而非 `fb_routes.py` 的理由**：这两个路径属于 `/api/statuses/*`、`/api/sales-persons/*`、`/api/mcc-levels/*` 那一族全局选项 API，同族同处，便于一起找到。路径沿用 spec 里已批准的 `/api/fb-channels/*`。
>
> **`_yt_db()` / `_get_effective_platform()` / `_option_role_denied` 均在 `main.py` 内已存在或上面已定义。** `GLOBAL_OPTION_ROLES` 与 `auth` 在 `main.py` 已导入（`statuses_rename` 就在用）。

- [ ] **Step 4: 跑测试确认通过**

```bash
cd py && python -m pytest tests/test_fb_asset_model.py -q -k SharedOptionApi
```

Expected: PASS。

- [ ] **Step 5: 跑全量回归并提交**

```bash
cd py && python -m pytest tests/ -q
git add py/main.py py/tests/test_fb_asset_model.py
git commit -m "feat(fb): 新增所属渠道 / 资产类型两组公用词表 API

形状照 /api/statuses/*：platform 取自 _get_effective_platform()，
唯一性 (name, platform)，owner_id 只记谁先建的。
删除时统计在用账户引用，并显式解除软删账户的引用（避免 FK 500）。"
```

---

## Task 3: FB 账户接口承载新字段

**Files:**
- Modify: `py/routes/fb_routes.py`（`list_accounts` 的 BM 批量查询段；`create_account`；`update_account`；文件顶部辅助区新增 `_display_name` / `_set_primary_bm`）
- Test: `py/tests/test_fb_asset_model.py`（追加）

**Interfaces:**
- Consumes: Task 1 的列与表
- Produces:
  - `_display_name(db, uid) -> str` —— 名字快照，`display_name` 优先、回退 `username`
  - `_set_primary_bm(db, acc_pk, bm_id) -> None` —— 换主 BM（先清后设，不 commit）
  - `GET /api/fb/accounts/list` 的每个 item 多出 `primary_bm_name: str`，且 `bms[]` 多出 `is_primary: int`
  - `POST /api/fb/accounts/create` / `PUT /api/fb/accounts/<aid>` 接受 `channel_id / asset_type_id / unit_price / inbound_qty / acceptor_id / outbound_date / outbound_qty / consumption / remark / primary_bm_id`

- [ ] **Step 1: 写失败测试**

追加到 `py/tests/test_fb_asset_model.py`：

```python
class TestFbAccountApi:
    @pytest.fixture
    def fb_user(self, client):
        client.post("/api/auth/register", json={"username": "fb_owner", "password": "t123"})
        db = database.get_db()
        db.execute("UPDATE users SET platform='fb', display_name='张三' "
                   "WHERE username='fb_owner'")
        db.commit()
        db.close()
        token = client.post("/api/auth/login",
                            json={"username": "fb_owner", "password": "t123"}
                            ).get_json()["access_token"]
        return {"Authorization": f"Bearer {token}"}

    def test_create_writes_new_fields(self, client, fb_user):
        r = client.post("/api/fb/accounts/create", headers=fb_user, json={
            "name": "户一", "account_id": "9001", "timezone": "Asia/Shanghai",
            "unit_price": "12.5", "inbound_qty": "3", "outbound_qty": "1",
            "outbound_date": "2026-10-01", "consumption": "88", "remark": "备注A",
        })
        assert r.status_code == 200
        aid = r.get_json()["id"]
        db = database.get_db()
        row = db.execute("SELECT * FROM fb_accounts WHERE id=?", (aid,)).fetchone()
        db.close()
        assert row["unit_price"] == "12.5"
        assert row["inbound_qty"] == "3"
        assert row["outbound_qty"] == "1"
        assert row["outbound_date"] == "2026-10-01"
        assert row["consumption"] == "88"
        assert row["remark"] == "备注A"

    def test_operator_is_frozen_to_creator_and_ignores_request_body(self, client, fb_user):
        """operator 由服务端填；请求体里的同名字段必须被忽略。"""
        r = client.post("/api/fb/accounts/create", headers=fb_user, json={
            "name": "户二", "account_id": "9002", "operator": "伪造的操作人",
        })
        aid = r.get_json()["id"]
        db = database.get_db()
        row = db.execute("SELECT operator FROM fb_accounts WHERE id=?", (aid,)).fetchone()
        db.close()
        assert row["operator"] == "张三"

    def test_operator_cannot_be_changed_by_update(self, client, fb_user):
        """PUT 里根本没有 operator 这一列的写入路径。"""
        r = client.post("/api/fb/accounts/create", headers=fb_user,
                        json={"name": "户三", "account_id": "9003"})
        aid = r.get_json()["id"]
        client.put(f"/api/fb/accounts/{aid}", headers=fb_user, json={
            "name": "户三改", "operator": "改过的操作人",
        })
        db = database.get_db()
        row = db.execute("SELECT name, operator FROM fb_accounts WHERE id=?", (aid,)).fetchone()
        db.close()
        assert row["name"] == "户三改"
        assert row["operator"] == "张三"

    def test_update_writes_new_fields(self, client, fb_user):
        r = client.post("/api/fb/accounts/create", headers=fb_user,
                        json={"name": "户四", "account_id": "9004"})
        aid = r.get_json()["id"]
        client.put(f"/api/fb/accounts/{aid}", headers=fb_user, json={
            "name": "户四", "unit_price": "99", "remark": "改后备注",
        })
        db = database.get_db()
        row = db.execute("SELECT unit_price, remark FROM fb_accounts WHERE id=?",
                         (aid,)).fetchone()
        db.close()
        assert row["unit_price"] == "99"
        assert row["remark"] == "改后备注"

    def test_primary_bm_visible_in_list(self, client, fb_user):
        db = database.get_db()
        uid = db.execute("SELECT id FROM users WHERE username='fb_owner'").fetchone()[0]
        db.execute("INSERT INTO fb_bms(name, bm_id, owner_id) VALUES('BM主','bmz',?)", (uid,))
        bm = db.execute("SELECT last_insert_rowid()").fetchone()[0]
        db.commit()   # 不 commit 就 close 会回滚，BM 行丢失，后面的 create 会撞 FK
        db.close()
        r = client.post("/api/fb/accounts/create", headers=fb_user, json={
            "name": "户五", "account_id": "9005", "bm_ids": [bm], "primary_bm_id": bm,
        })
        assert r.status_code == 200
        r = client.get("/api/fb/accounts/list", headers=fb_user, query_string={"search": "9005"})
        item = r.get_json()["items"][0]
        assert item["primary_bm_name"] == "BM主"

    def test_switching_primary_bm_via_update(self, client, fb_user):
        """换 BM 走接口也必须成功（先清后设）。"""
        db = database.get_db()
        uid = db.execute("SELECT id FROM users WHERE username='fb_owner'").fetchone()[0]
        for nm, bid in (("BM一", "bx1"), ("BM二", "bx2")):
            db.execute("INSERT INTO fb_bms(name, bm_id, owner_id) VALUES(?,?,?)", (nm, bid, uid))
        bms = [r[0] for r in db.execute("SELECT id FROM fb_bms ORDER BY id").fetchall()]
        db.commit()   # 同上：不 commit 就 close 会回滚
        db.close()
        r = client.post("/api/fb/accounts/create", headers=fb_user, json={
            "name": "户六", "account_id": "9006", "bm_ids": bms, "primary_bm_id": bms[0],
        })
        aid = r.get_json()["id"]
        r = client.put(f"/api/fb/accounts/{aid}", headers=fb_user, json={
            "name": "户六", "bm_ids": bms, "primary_bm_id": bms[1],
        })
        assert r.status_code == 200
        db = database.get_db()
        row = db.execute("SELECT bm_id FROM fb_account_bm WHERE account_id=? AND is_primary=1",
                         (aid,)).fetchone()
        db.close()
        assert row is not None and row["bm_id"] == bms[1]
```

- [ ] **Step 2: 跑测试确认失败**

```bash
cd py && python -m pytest tests/test_fb_asset_model.py -q -k FbAccountApi
```

Expected: FAIL —— `unit_price` 读回为空串（create 没写这些列）、`primary_bm_name` KeyError。

- [ ] **Step 3: 加两个辅助函数**

在 `py/routes/fb_routes.py` 的 `def _get_role(db, uid):` 附近（文件末尾的辅助区）追加：

```python
def _display_name(db, uid):
    """用户显示名快照：display_name 优先，空则回退 username。

    与 `resolve_owner_id` 用的同一个 COALESCE(NULLIF(...)) 口径。
    用于 `fb_accounts.operator` —— 那一列存的是**名字快照**不是外键（规格 6.1）。
    """
    r = db.execute("SELECT COALESCE(NULLIF(display_name, ''), username, '') AS n "
                   "FROM users WHERE id=?", (uid,)).fetchone()
    return r['n'] if r else ''


def _set_primary_bm(db, acc_pk, bm_id):
    """把某账户的主 BM 换成 bm_id。**不 commit**，事务边界由调用方负责。

    ⚠️ **必须先清后设，顺序不能反。** `idx_fb_account_bm_primary` 是
    `WHERE is_primary = 1` 的部分唯一索引，保证同一账户至多一行主 BM。
    SQLite 的唯一索引是**逐语句**检查的，不是事务提交时统一检查 ——
    先设新的（此刻旧的主 BM 还是 1）会立刻 UNIQUE constraint failed。
    这是正确性问题，不是代码风格问题。
    """
    db.execute("UPDATE fb_account_bm SET is_primary=0 WHERE account_id=?", (acc_pk,))
    cur = db.execute("UPDATE fb_account_bm SET is_primary=1 WHERE account_id=? AND bm_id=?",
                     (acc_pk, bm_id))
    if cur.rowcount == 0:
        # 该 BM 尚未与该账户关联
        db.execute("INSERT INTO fb_account_bm(account_id, bm_id, is_primary) VALUES(?,?,1)",
                   (acc_pk, bm_id))
```

- [ ] **Step 4: 改 `create_account`**

把 `py/routes/fb_routes.py` 的 `create_account` 函数体替换为：

```python
@fb_bp.route('/api/fb/accounts/create', methods=['POST'])
@jwt_required()
@fb_required
def create_account():
    db = get_db()
    data = parse_body()
    name = data.get('name', '').strip()
    account_id = data.get('account_id', '').strip()
    bm_ids = data.get('bm_ids', [])
    timezone = data.get('timezone', '')
    status_id = data.get('status_id', None)
    acquired_date = data.get('acquired_date', '')
    # 子项目 ① 新增字段（规格 4.1）
    channel_id = data.get('channel_id') or None
    asset_type_id = data.get('asset_type_id') or None
    unit_price = data.get('unit_price', '')
    inbound_qty = data.get('inbound_qty', '')
    acceptor_id = data.get('acceptor_id') or None
    outbound_date = data.get('outbound_date', '')
    outbound_qty = data.get('outbound_qty', '')
    consumption = data.get('consumption', '')
    remark = data.get('remark', '')
    primary_bm_id = data.get('primary_bm_id') or None

    if not name or not account_id:
        return err('账户名称和账户ID不能为空'), 400
    if not account_id.isdigit():
        return err('账户ID必须是纯数字'), 400

    uid = get_uid()
    # operator 是**冻结字段**（规格 6.1）：服务端填创建者的名字快照，
    # 请求体里的同名字段一律忽略。
    operator = _display_name(db, uid)
    try:
        db.execute(
            "INSERT INTO fb_accounts (name, account_id, timezone, status_id, acquired_date, "
            "owner_id, operator, channel_id, asset_type_id, unit_price, inbound_qty, "
            "acceptor_id, outbound_date, outbound_qty, consumption, remark) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (name, account_id, timezone, status_id, acquired_date, uid, operator,
             channel_id, asset_type_id, unit_price, inbound_qty,
             acceptor_id, outbound_date, outbound_qty, consumption, remark))
        acc_pk = db.execute("SELECT last_insert_rowid()").fetchone()[0]
        for bm_id in bm_ids:
            db.execute("INSERT OR IGNORE INTO fb_account_bm (account_id, bm_id) VALUES (?, ?)",
                       (acc_pk, bm_id))
        if primary_bm_id:
            _set_primary_bm(db, acc_pk, primary_bm_id)
        db.commit()
        return ok({'id': acc_pk})
    except Exception as e:
        return err(str(e))
```

- [ ] **Step 5: 改 `update_account`**

把 `update_account` 函数体替换为：

```python
@fb_bp.route('/api/fb/accounts/<int:aid>', methods=['PUT'])
@jwt_required()
@fb_required
def update_account(aid):
    db = get_db()
    data = parse_body()
    name = data.get('name', '').strip()
    timezone = data.get('timezone', '')
    status_id = data.get('status_id', None)
    acquired_date = data.get('acquired_date', '')
    bm_ids = data.get('bm_ids', None)
    # 子项目 ① 新增字段。
    # ⚠️ **operator 刻意不在此列，也不出现在下面的 UPDATE 语句里** ——
    # 冻结口径是「让它没有写入路径」，而不是「在接口层过滤请求体」（规格 6.1）。
    # 想加这一列的请先读规格：它记录的是接户那一刻的户管名，事后不应变化。
    channel_id = data.get('channel_id') or None
    asset_type_id = data.get('asset_type_id') or None
    unit_price = data.get('unit_price', '')
    inbound_qty = data.get('inbound_qty', '')
    acceptor_id = data.get('acceptor_id') or None
    outbound_date = data.get('outbound_date', '')
    outbound_qty = data.get('outbound_qty', '')
    consumption = data.get('consumption', '')
    remark = data.get('remark', '')
    primary_bm_id = data.get('primary_bm_id') or None

    if name:
        db.execute(
            "UPDATE fb_accounts SET name=?, timezone=?, status_id=?, acquired_date=?, "
            "channel_id=?, asset_type_id=?, unit_price=?, inbound_qty=?, acceptor_id=?, "
            "outbound_date=?, outbound_qty=?, consumption=?, remark=?, "
            "updated_at=datetime('now','localtime') WHERE id=?",
            (name, timezone, status_id, acquired_date,
             channel_id, asset_type_id, unit_price, inbound_qty, acceptor_id,
             outbound_date, outbound_qty, consumption, remark, aid))

    if bm_ids is not None:
        # 全量替换关联（既有行为）。这一步会把所有 is_primary 一并清掉 ——
        # 因此下面必须按 primary_bm_id 重建主 BM；前端应始终同时提交两个字段。
        db.execute("DELETE FROM fb_account_bm WHERE account_id=?", (aid,))
        for bm_id in bm_ids:
            db.execute("INSERT OR IGNORE INTO fb_account_bm (account_id, bm_id) VALUES (?, ?)",
                       (aid, bm_id))
    if primary_bm_id:
        _set_primary_bm(db, aid, primary_bm_id)

    db.commit()
    return ok()
```

- [ ] **Step 6: 改 `list_accounts` 的 BM 查询段**

把 `list_accounts` 里的：

```python
    # 批量获取关联的 BM 名称
    result_items = []
    for r in rows:
        item = dict(r)
        bms = db.execute(
            "SELECT b.name, b.id, b.bm_id FROM fb_bms b "
            "JOIN fb_account_bm ab ON ab.bm_id = b.id "
            "WHERE ab.account_id = ?", (r['id'],)
        ).fetchall()
        item['bms'] = [dict(b) for b in bms]
        result_items.append(item)
```

替换为：

```python
    # 批量获取关联的 BM 名称，并标出主 BM（即看板「位置」列，规格 4.3）
    result_items = []
    for r in rows:
        item = dict(r)
        bms = db.execute(
            "SELECT b.name, b.id, b.bm_id, ab.is_primary FROM fb_bms b "
            "JOIN fb_account_bm ab ON ab.bm_id = b.id "
            "WHERE ab.account_id = ?", (r['id'],)
        ).fetchall()
        item['bms'] = [dict(b) for b in bms]
        item['primary_bm_name'] = next((b['name'] for b in item['bms'] if b['is_primary']), '')
        result_items.append(item)
```

- [ ] **Step 7: 跑测试确认通过**

```bash
cd py && python -m pytest tests/test_fb_asset_model.py -q -k FbAccountApi
```

Expected: PASS。

- [ ] **Step 8: 跑全量回归并提交**

```bash
cd py && python -m pytest tests/ -q
git add py/routes/fb_routes.py py/tests/test_fb_asset_model.py
git commit -m "feat(fb): 账户接口承载新增 10 字段，operator 冻结、主 BM 可换

- create/update 接受新字段；operator 由服务端填、UPDATE 语句里不出现该列
- 新增 _set_primary_bm（先清后设，附理由注释）与 _display_name
- list 返回 primary_bm_name 与 bms[].is_primary"
```

---

## Task 4: FB 归属变更端点

**Files:**
- Modify: `py/routes/fb_routes.py`（在 `restore_account` 之前插入 `reassign_account`）
- Test: `py/tests/test_fb_asset_model.py`（追加）

**Interfaces:**
- Consumes: `CROSS_USER_ROLES`（已导入）、`_get_role`、`get_uid`、`get_db`、`parse_body`、`ok`、`err`
- Produces: `PUT /api/fb/accounts/<int:aid>/reassign`，body 可选 `{"owner_id": <int>}`。200 → `{"success": true, "data": {"message": str}}`；403 无权限；404 账户不存在；400 目标用户不存在 / owner_id 非法；409 已属于目标

- [ ] **Step 1: 写失败测试**

追加到 `py/tests/test_fb_asset_model.py`：

```python
class TestFbReassign:
    @pytest.fixture
    def fb_user_headers_factory(self, client):
        """注册两个 FB 用户并返回 (headers_dict, uid) 的工厂。"""
        def _make(username):
            client.post("/api/auth/register", json={"username": username, "password": "t123"})
            db = database.get_db()
            db.execute("UPDATE users SET platform='fb' WHERE username=?", (username,))
            db.commit()
            uid = db.execute("SELECT id FROM users WHERE username=?", (username,)).fetchone()[0]
            db.close()
            token = client.post("/api/auth/login",
                                json={"username": username, "password": "t123"}
                                ).get_json()["access_token"]
            return {"Authorization": f"Bearer {token}"}, uid
        return _make

    def _make_account(self, client, headers, account_id):
        r = client.post("/api/fb/accounts/create", headers=headers,
                        json={"name": f"户{account_id}", "account_id": account_id})
        return r.get_json()["id"]

    def test_developer_can_transfer_to_another_user(self, client, fb_user_headers_factory):
        dev_h, _ = fb_user_headers_factory("fb_dev")
        db = database.get_db()
        db.execute("UPDATE users SET role='developer', platform='fb' WHERE username='fb_dev'")
        db.commit()
        db.close()
        # 重新登录拿带新角色的 token
        token = client.post("/api/auth/login",
                            json={"username": "fb_dev", "password": "t123"}
                            ).get_json()["access_token"]
        dev_h = {"Authorization": f"Bearer {token}"}
        _, target_uid = fb_user_headers_factory("fb_target")

        aid = self._make_account(client, dev_h, "7001")
        r = client.put(f"/api/fb/accounts/{aid}/reassign", headers=dev_h,
                       json={"owner_id": target_uid})
        assert r.status_code == 200
        db = database.get_db()
        owner = db.execute("SELECT owner_id FROM fb_accounts WHERE id=?", (aid,)).fetchone()[0]
        db.close()
        assert owner == target_uid

    def test_plain_user_without_owner_id_claims_for_self(self, client, fb_user_headers_factory):
        h, uid = fb_user_headers_factory("fb_solo")
        aid = self._make_account(client, h, "7002")
        r = client.put(f"/api/fb/accounts/{aid}/reassign", headers=h, json={})
        # 已经属于自己 → 409（与 TT 同口径）
        assert r.status_code == 409

    def test_plain_user_cannot_steal_another_users_account(self, client, fb_user_headers_factory):
        """非跨用户角色按 id 改别人名下的户 → 403。"""
        h1, _ = fb_user_headers_factory("fb_a")
        h2, _ = fb_user_headers_factory("fb_b")
        aid = self._make_account(client, h1, "7003")
        r = client.put(f"/api/fb/accounts/{aid}/reassign", headers=h2, json={})
        assert r.status_code == 403

    def test_nonexistent_target_user_returns_400_not_500(self, client, fb_user_headers_factory):
        """目标用户不存在必须在写库前挡成 400 —— 否则 FK IntegrityError → 500。"""
        dev_h, _ = fb_user_headers_factory("fb_dev2")
        db = database.get_db()
        db.execute("UPDATE users SET role='developer' WHERE username='fb_dev2'")
        db.commit()
        db.close()
        token = client.post("/api/auth/login",
                            json={"username": "fb_dev2", "password": "t123"}
                            ).get_json()["access_token"]
        dev_h = {"Authorization": f"Bearer {token}"}
        aid = self._make_account(client, dev_h, "7004")
        r = client.put(f"/api/fb/accounts/{aid}/reassign", headers=dev_h,
                       json={"owner_id": 999999})
        assert r.status_code == 400

    def test_non_numeric_owner_id_returns_400(self, client, fb_user_headers_factory):
        """非法 owner_id 只对**跨用户角色**才有意义。

        端点只在 `if role in CROSS_USER_ROLES:` 分支里解析 owner_id —— 普通 user
        传的 owner_id 被**完全忽略**（默认路径恒为「转给自己」，与 TT 同口径）。
        用普通 user 发这个请求会走到「已属于当前用户」的 409，拿不到 400。
        所以本用例必须用跨用户角色发起。
        """
        fb_user_headers_factory("fb_dev3")
        db = database.get_db()
        db.execute("UPDATE users SET role='developer' WHERE username='fb_dev3'")
        db.commit()
        db.close()
        token = client.post("/api/auth/login",
                            json={"username": "fb_dev3", "password": "t123"}
                            ).get_json()["access_token"]
        h = {"Authorization": f"Bearer {token}"}
        aid = self._make_account(client, h, "7005")
        r = client.put(f"/api/fb/accounts/{aid}/reassign", headers=h,
                       json={"owner_id": "abc"})
        assert r.status_code == 400

    def test_missing_account_returns_404(self, client, fb_user_headers_factory):
        h, _ = fb_user_headers_factory("fb_solo3")
        r = client.put("/api/fb/accounts/999999/reassign", headers=h, json={})
        assert r.status_code == 404
```

- [ ] **Step 2: 跑测试确认失败**

```bash
cd py && python -m pytest tests/test_fb_asset_model.py -q -k FbReassign
```

Expected: FAIL —— 404（路由不存在）。

- [ ] **Step 3: 实现端点**

在 `py/routes/fb_routes.py` 的 `restore_account` 函数**之前**插入：

```python
@fb_bp.route('/api/fb/accounts/<int:aid>/reassign', methods=['PUT'])
@jwt_required()
@fb_required
def reassign_account(aid):
    """改 FB 账户的归属（「在用运营」= owner_id）。

    形状照 TT 的 `reassign_account`（routes/tt_accounts_routes.py:466）：
    - 默认路径（不带 owner_id，或调用者非 CROSS_USER_ROLES）→ 转给调用者自己
    - 跨用户路径：CROSS_USER_ROLES + 合法 owner_id → 转给该用户

    注：本端点由子项目 ① 新增。TT / GG 版本在这里还会调 `hd.writeback_*`
    回写户管看板 —— FB 的看板回写属于子项目 ②，**此处刻意不调**，
    等 ② 落地时再补，不要提前接上。
    """
    db = get_db()
    uid = get_uid()
    role = _get_role(db, uid)
    data = parse_body()

    # 目标归属：跨用户角色可用 owner_id 转给指定用户，其余角色恒为调用者自己。
    # `or ""` 不能省：owner_id 给 0 时 `"0".isdigit()` 为真，会被当成合法目标。
    target_owner = uid
    if role in CROSS_USER_ROLES:
        # parse_body() 对「真值非 dict」的 body（如 JSON 数组）原样返回，
        # 不判类型直接 .get 会 AttributeError → 500。
        raw_owner = (data.get("owner_id") or "") if isinstance(data, dict) else ""
        raw_owner_str = str(raw_owner).strip()
        if raw_owner_str:
            if not (raw_owner_str.isascii() and raw_owner_str.isdigit()):
                return err("owner_id 不合法", 400)
            target_owner = int(raw_owner_str)
            if target_owner > 2**63 - 1:
                return err("owner_id 不合法", 400)

    existing = db.execute(
        "SELECT a.*, u.username, u.display_name FROM fb_accounts a "
        "LEFT JOIN users u ON a.owner_id = u.id WHERE a.id = ?", (aid,)
    ).fetchone()
    if not existing:
        return err("账户不存在", 404)

    # 归属校验（与同文件 delete_account 同口径）：非跨用户角色只能操作自己的账户。
    # 少了这道闸，普通 user / viewer 按 id 就能把**别人名下**的账户改成自己的。
    if role not in CROSS_USER_ROLES and existing["owner_id"] != uid:
        return err("无权限", 403)

    # 目标用户存在性校验是**必需**的：fb_accounts.owner_id 是
    # INTEGER REFERENCES users(id)，连接开着 PRAGMA foreign_keys=ON
    # ⇒ 指向不存在的用户会在 UPDATE 处抛 IntegrityError 变成 500。
    if target_owner != uid:
        if not db.execute("SELECT 1 FROM users WHERE id=?", (target_owner,)).fetchone():
            return err("目标用户不存在", 400)

    if int(existing["owner_id"] or 0) == target_owner:
        return err("该账户已属于当前用户，无需转移" if target_owner == uid
                   else "该账户已属于目标用户，无需转移", 409)

    db.execute("UPDATE fb_accounts SET owner_id=?, updated_at=datetime('now','localtime') "
               "WHERE id=?", (target_owner, aid))
    db.commit()

    if target_owner == uid:
        return ok({"message": f"账户「{existing['name'] or existing['account_id']}」"
                              f"已转移至当前用户"})
    old_owner = existing["display_name"] or existing["username"] or "未知"
    t = db.execute("SELECT display_name, username FROM users WHERE id=?",
                   (target_owner,)).fetchone()
    new_owner = (t["display_name"] or t["username"] or "") if t else ""
    # 文案与 TT 侧的分支结构对称：只有跨用户分支补「已从 A」。
    return ok({"message": f"账户「{existing['name'] or existing['account_id']}」"
                          f"已从 {old_owner} 转移至 {new_owner}"})
```

- [ ] **Step 4: 跑测试确认通过**

```bash
cd py && python -m pytest tests/test_fb_asset_model.py -q -k FbReassign
```

Expected: PASS。

- [ ] **Step 5: 跑全量回归并提交**

```bash
cd py && python -m pytest tests/ -q
git add py/routes/fb_routes.py py/tests/test_fb_asset_model.py
git commit -m "feat(fb): 补 FB 归属变更端点 reassign（此前无归属通路）

形状照 TT：CROSS_USER_ROLES + 合法 owner_id 转给他人，否则转给自己。
含归属校验（防普通用户按 id 抢别人的户）与目标用户存在性校验（防 FK 500）。
户管看板回写属子项目 ②，此处刻意不调。"
```

---

## Task 5: 前端 —— API 封装与账户面板

**Files:**
- Modify: `frontend/src/api/fb.js`
- Modify: `frontend/src/views/fb/FbAccountPanel.vue`
- Test: `cd frontend && npm run build`（无测试框架，构建即门禁）

**Interfaces:**
- Consumes: Task 2 / 3 / 4 的端点
- Produces: `fbApi.reassignAccount(id, data)`、`fbApi.listChannels()`、`fbApi.createChannel(name)`、`fbApi.deleteChannel(id)`、`fbApi.listAssetTypes()`、`fbApi.createAssetType(name)`、`fbApi.deleteAssetType(id)`

- [ ] **Step 1: 补 API 封装**

在 `frontend/src/api/fb.js` 的 `accountBmHistory` 那一行之后插入：

```js
  reassignAccount(id, data) { return client.put(`/fb/accounts/${id}/reassign`, data) },
```

在 `// 用户查询` 之前插入：

```js
  // 公用词表（所属渠道 / 资产类型）
  listChannels() { return client.get('/fb-channels/list') },
  createChannel(name) { return client.post('/fb-channels/create', { name }) },
  deleteChannel(id) { return client.delete(`/fb-channels/${id}`) },
  listAssetTypes() { return client.get('/fb-asset-types/list') },
  createAssetType(name) { return client.post('/fb-asset-types/create', { name }) },
  deleteAssetType(id) { return client.delete(`/fb-asset-types/${id}`) },
```

- [ ] **Step 2: 表格加「位置」列**

在 `frontend/src/views/fb/FbAccountPanel.vue` 的 `<el-table-column label="所属BM" ...>` 那一块**之后**插入：

```vue
        <el-table-column label="位置" min-width="120">
          <template #default="{ row }">
            <span v-if="row.primary_bm_name">{{ row.primary_bm_name }}</span>
            <span v-else style="color:#c0c4cc;">—</span>
          </template>
        </el-table-column>
        <el-table-column label="所属渠道" width="110">
          <template #default="{ row }">{{ optName(channelOptions, row.channel_id) }}</template>
        </el-table-column>
        <el-table-column label="资产类型" width="110">
          <template #default="{ row }">{{ optName(assetTypeOptions, row.asset_type_id) }}</template>
        </el-table-column>
        <el-table-column label="状态" width="100">
          <template #default="{ row }">{{ optName(statusOptions, row.status_id) }}</template>
        </el-table-column>
        <el-table-column prop="operator" label="操作人" width="100" />
```

> **为什么不直接 `prop="channel_name"`**：后端 `list_accounts` 是 `SELECT a.*`，只返回
> `channel_id` / `asset_type_id` / `status_id` 这些 **id**，不返回名字 —— 写成 `prop="channel_name"`
> 会渲染成空白列。这里用本页已经加载好的选项表做 id → 名 映射，不必改后端查询。
> `optName` 加在 `<script setup>` 里（见 Step 3 的尾部）。

- [ ] **Step 3: 表单扩充**

把 `form` 的 `reactive` 初始化（当前是 `const form = reactive({ name:'', account_id:'', bm_ids:[], timezone:'', acquired_date:'', status_id:null })`）替换为：

```js
const form = reactive({
  name:'', account_id:'', bm_ids:[], primary_bm_id:null, timezone:'', acquired_date:'',
  status_id:null, channel_id:null, asset_type_id:null, unit_price:'', inbound_qty:'',
  acceptor_id:null, outbound_date:'', outbound_qty:'', consumption:'', remark:'',
})
```

把 `openCreate` 替换为：

```js
function openCreate() {
  editingId.value = null
  Object.assign(form, {
    name:'', account_id:'', bm_ids:[], primary_bm_id:null, timezone:'', acquired_date:'',
    status_id:null, channel_id:null, asset_type_id:null, unit_price:'', inbound_qty:'',
    acceptor_id:null, outbound_date:'', outbound_qty:'', consumption:'', remark:'',
  })
  dialogVisible.value = true
}
```

把 `openEdit` 替换为：

```js
function openEdit(row) {
  editingId.value = row.id
  Object.assign(form, {
    name: row.name, account_id: row.account_id,
    bm_ids: (row.bms||[]).map(b=>b.id),
    primary_bm_id: (row.bms||[]).find(b=>b.is_primary)?.id || null,
    timezone: row.timezone, acquired_date: row.acquired_date, status_id: row.status_id,
    channel_id: row.channel_id, asset_type_id: row.asset_type_id,
    unit_price: row.unit_price, inbound_qty: row.inbound_qty,
    acceptor_id: row.acceptor_id, outbound_date: row.outbound_date,
    outbound_qty: row.outbound_qty, consumption: row.consumption, remark: row.remark,
  })
  dialogVisible.value = true
}
```

在 `<el-form-item label="状态">` 那一块**之后**插入：

```vue
        <el-form-item label="主BM（位置）">
          <el-select v-model="form.primary_bm_id" clearable placeholder="从已关联的BM中选择" style="width:100%">
            <el-option v-for="b in form.bm_ids" :key="b"
                       :label="(bmOptions.find(x=>x.id===b)||{}).name || ('BM#'+b)" :value="b" />
          </el-select>
        </el-form-item>
        <el-form-item label="所属渠道">
          <el-select v-model="form.channel_id" clearable placeholder="请选择渠道" style="width:100%">
            <el-option v-for="c in channelOptions" :key="c.id" :label="c.name" :value="c.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="资产类型">
          <el-select v-model="form.asset_type_id" clearable placeholder="请选择资产类型" style="width:100%">
            <el-option v-for="t in assetTypeOptions" :key="t.id" :label="t.name" :value="t.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="接户运营">
          <el-select v-model="form.acceptor_id" clearable filterable placeholder="选择接户运营" style="width:100%">
            <el-option v-for="u in fbUsers" :key="u.id"
                       :label="u.display_name || u.username" :value="u.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="单价">
          <el-input v-model="form.unit_price" placeholder="数字" />
        </el-form-item>
        <el-form-item label="入库">
          <el-input v-model="form.inbound_qty" placeholder="数量" />
        </el-form-item>
        <el-form-item label="出库时间">
          <el-input v-model="form.outbound_date" placeholder="YYYY-MM-DD" />
        </el-form-item>
        <el-form-item label="出库">
          <el-input v-model="form.outbound_qty" placeholder="数量" />
        </el-form-item>
        <el-form-item label="消耗">
          <el-input v-model="form.consumption" />
        </el-form-item>
        <el-form-item label="产品信息">
          <el-input v-model="form.remark" type="textarea" :rows="2" />
        </el-form-item>
```

在 `loadOptions` 里追加三组数据源：

```js
async function loadOptions() {
  try { const r = await fbApi.bmOptions(); bmOptions.value = r.data || [] } catch(e) { console.warn('loadOptions bm', e) }
  try { const r = await client.get('/statuses/list'); statusOptions.value = r.statuses || r.data || [] } catch(e) { console.warn('loadOptions statuses', e) }
  try { const r = await fbApi.listChannels(); channelOptions.value = r.items || [] } catch(e) { console.warn('loadOptions channels', e) }
  try { const r = await fbApi.listAssetTypes(); assetTypeOptions.value = r.items || [] } catch(e) { console.warn('loadOptions assetTypes', e) }
  try { const r = await fbApi.listFbUsers(); fbUsers.value = r.users || [] } catch(e) { console.warn('loadOptions users', e) }
}
```

并在 `bmOptions` 那一行的声明旁边补三个 ref 与一个映射函数：

```js
const channelOptions = ref([]); const assetTypeOptions = ref([]); const fbUsers = ref([])

// 选项 id → 名字。后端 list_accounts 只返回 *_id，不返回名字（见 Step 2 的说明），
// 用本页已加载的选项表映射，避免为此改后端查询。
//
// ⚠️ 形参 list 收的是**普通数组**不是 ref：本函数只在模板里调用，而 `<script setup>`
// 的顶层 ref 在模板中会自动解包，传进来的是 `channelOptions.value` 那个数组。
// 写成 `list.value.find(...)` 会 TypeError。
function optName(list, id) {
  if (id === null || id === undefined || id === '') return ''
  const o = (list || []).find(x => x.id === id)
  return o ? o.name : ''
}
```

- [ ] **Step 4: 构建**

```bash
cd frontend && npm run build
```

Expected: 构建成功，无报错。

- [ ] **Step 5: 提交**

```bash
git add frontend/src/api/fb.js frontend/src/views/fb/FbAccountPanel.vue
git commit -m "feat(fb): 账户面板承载新增字段与主 BM

表格补 位置/所属渠道/资产类型/状态/操作人 五列；
编辑表单从 6 个字段扩到 16 个；补词表与 FB 用户的数据源。"
```

---

## Task 6: 前端 —— 设置页两张词表卡片

**Files:**
- Modify: `frontend/src/views/fb/FbSettingsPanel.vue`
- Test: `cd frontend && npm run build`

**Interfaces:**
- Consumes: Task 5 的 `fbApi.listChannels/createChannel/deleteChannel/listAssetTypes/createAssetType/deleteAssetType`
- Produces: 设置页新增「🏷 所属渠道」「📦 资产类型」两张卡

- [ ] **Step 1: 加两张卡片**

在 `frontend/src/views/fb/FbSettingsPanel.vue` 的第三张卡（账户状态管理）那个 `</el-col>` **之后**插入：

```vue
      <!-- 第四栏：所属渠道 -->
      <el-col :xs="24" :md="12" :lg="8">
        <el-card class="setting-card" shadow="never">
          <template #header>
            <span class="card-title">🏷 所属渠道</span>
          </template>

          <div v-if="authStore.canManageAccounts" class="add-form">
            <el-input v-model="newChannelName" placeholder="新建渠道名称" size="small"
                      @keyup.enter="createChannel" />
            <el-button type="primary" size="small" @click="createChannel">添加</el-button>
          </div>

          <div v-if="channels.length" class="tag-list">
            <div v-for="item in channels" :key="item.id" class="tag-row">
              <el-tag size="default">{{ item.name }}</el-tag>
              <el-popconfirm v-if="authStore.canManageAccounts" title="确定删除？" @confirm="deleteChannel(item.id)">
                <template #reference>
                  <el-button class="tag-delete-btn" size="small" type="danger" link>删除</el-button>
                </template>
              </el-popconfirm>
            </div>
          </div>
          <el-empty v-else description="暂无渠道" :image-size="60" />
        </el-card>
      </el-col>

      <!-- 第五栏：资产类型 -->
      <el-col :xs="24" :md="12" :lg="8">
        <el-card class="setting-card" shadow="never">
          <template #header>
            <span class="card-title">📦 资产类型</span>
          </template>

          <div v-if="authStore.canManageAccounts" class="add-form">
            <el-input v-model="newAssetTypeName" placeholder="新建资产类型名称" size="small"
                      @keyup.enter="createAssetType" />
            <el-button type="primary" size="small" @click="createAssetType">添加</el-button>
          </div>

          <div v-if="assetTypes.length" class="tag-list">
            <div v-for="item in assetTypes" :key="item.id" class="tag-row">
              <el-tag size="default">{{ item.name }}</el-tag>
              <el-popconfirm v-if="authStore.canManageAccounts" title="确定删除？" @confirm="deleteAssetType(item.id)">
                <template #reference>
                  <el-button class="tag-delete-btn" size="small" type="danger" link>删除</el-button>
                </template>
              </el-popconfirm>
            </div>
          </div>
          <el-empty v-else description="暂无资产类型" :image-size="60" />
        </el-card>
      </el-col>
```

- [ ] **Step 2: 加状态与动作**

在 `const statuses = ref([]); const newStatusName = ref('')` 那一行之后插入：

```js
const channels = ref([]); const newChannelName = ref('')
const assetTypes = ref([]); const newAssetTypeName = ref('')
```

在 `loadData` 末尾追加：

```js
  try { const r = await fbApi.listChannels(); channels.value = r.items || [] } catch(e) { console.warn(e) }
  try { const r = await fbApi.listAssetTypes(); assetTypes.value = r.items || [] } catch(e) { console.warn(e) }
```

在 `deleteStatus` 那一行之后插入：

```js
// 渠道
async function createChannel() {
  if (!newChannelName.value.trim()) return
  try {
    await fbApi.createChannel(newChannelName.value.trim())
    ElMessage.success('已添加'); newChannelName.value = ''; loadData()
  } catch(e) { ElMessage.error(e.response?.data?.error || '添加失败') }
}
async function deleteChannel(id) {
  try { await fbApi.deleteChannel(id); ElMessage.success('已删除'); loadData() }
  catch(e) { ElMessage.error(e.response?.data?.error || '删除失败') }
}

// 资产类型
async function createAssetType() {
  if (!newAssetTypeName.value.trim()) return
  try {
    await fbApi.createAssetType(newAssetTypeName.value.trim())
    ElMessage.success('已添加'); newAssetTypeName.value = ''; loadData()
  } catch(e) { ElMessage.error(e.response?.data?.error || '添加失败') }
}
async function deleteAssetType(id) {
  try { await fbApi.deleteAssetType(id); ElMessage.success('已删除'); loadData() }
  catch(e) { ElMessage.error(e.response?.data?.error || '删除失败') }
}
```

并把顶部 import 补上 `fbApi`：

```js
import { fbApi } from '../../api/fb'
```

- [ ] **Step 3: 构建**

```bash
cd frontend && npm run build
```

Expected: 构建成功。

- [ ] **Step 4: 提交**

```bash
git add frontend/src/views/fb/FbSettingsPanel.vue
git commit -m "feat(fb): 设置页新增所属渠道 / 资产类型两张词表卡片

样式照同页既有的地区 / 商务人员 / 状态三张卡。"
```

---

## 完成后

子项目 ① 交付后，FB 的账户模型已能承载看板的 17 列。接下来是 **子项目 ②（FB 户管看板：17 列映射 + 双向同步）**，它需要：

- `hd.PLATFORMS` 从 `("gg", "tt")` 扩到含 `"fb"`
- 修掉 `build_diff` / `apply_diff` 里 `"tt_accounts" if platform == "tt" else "accounts"` 这处**二元判断**（加 fb 后会静默落到 GG 表）
- FB 的 `COLUMN_SPEC`（17 列）与 `_FB_ROW_SQL`
- FB 侧的 `hd.writeback_rows` / `hd.writeback_owner_channel` 接入点（本计划 Task 4 刻意留空）
- `fb_account_bm_history` 没有 `ON DELETE CASCADE` —— 撤回删新建 FB 账户时要显式先删历史行（属 ③）
