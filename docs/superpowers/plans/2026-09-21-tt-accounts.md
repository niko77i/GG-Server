# TT 广告账户管理页面 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为 TT 平台新增「广告账户」管理页面，完整对标 GG 广告账户（[AdsAccountPanel.vue](../../../frontend/src/views/AdsAccountPanel.vue)），叠加 TikTok 特有业务规则（消耗双向同步、回收户清单、回收原因、独立代理/状态）。

**Architecture:** 后端新建独立 blueprint 文件 `py/routes/tt_accounts_routes.py`（账户 CRUD / 查户 / 充值 / 同步 / 回收原因），在 `py/database.py` 新增 4 张 `tt_*` 表，复用 `agents`/`account_statuses` 的 `platform` 列隔离。前端新建 `TtAccountPanel.vue` + 9 个子组件（对标 GG 对应组件做语义替换），扩展 `api/tt.js` 与 `TtSettingsPanel.vue`。所有改动纯增量，不修改 GG/FB 现有逻辑。

**Tech Stack:** Flask + SQLite（`sqlite3.Row`，`['col']`/`[0]` 索引）、Google Sheets API（服务账号）、Vue 3 + Vite + Pinia + Element Plus、pytest（`py/tests/conftest.py` 提供 `client`/`auth_headers`/`tt_headers`）。

## Global Constraints

以下约束对**每个任务**生效（继承自设计文档 `docs/superpowers/specs/2026-09-21-tt-accounts-design.md` v1.1）：

1. **纯增量原则**：只新增 `tt_*` 文件/端点/表，不修改 GG/FB 现有功能的逻辑。禁止因新增功能导致 GG/FB 已有功能出错或失效。
2. **语言**：代码/表名/字段名用英文，注释与报错文案用中文。回复用户用中文。
3. **advertiser_id 校验**：TT 广告账户 ID 是**十多位纯数字、无 `-`**。创建/导入时去空格、拒绝非数字（校验失败返回 400）。
4. **owner 隔离**：普通用户所有查询 `WHERE owner_id = 当前用户 AND deleted_at IS NULL`；`admin`/`developer` 角色可传 `owner_id` 参数查看任意投手的户。
5. **agents 迁移只增不改**：`agents` 表加 `platform` 列（默认 `'gg'`），**不重建 UNIQUE 约束**（保持 `UNIQUE(name, owner_id)`），保证 GG/FB 行为不受影响。复制 GG 代理到 TT 用 `INSERT OR IGNORE`（冲突跳过，不报错）。
6. **时区格式**：`timezone` 存文本，格式为 `+8`/`-3` 这类**数字+符号**，**不用 `UTC+8` 前缀**。读看板时区直接存原始值；看板时区为空时用 TT 设置页「地区时区」(regions) 补。
7. **状态不靠看板自动改**：同步只读看板数据，不改系统状态；状态变更走系统手动（改状态为「封禁/死亡」时触发回收清单写入）。
8. **`name` 字段可空**：`tt_accounts.name` 保留但可为空，显示时回退 `advertiser_id`。

### 全局字段映射表（GG → TT）

| GG | TT | 说明 |
|----|----|------|
| 表 `accounts` | 表 `tt_accounts` | |
| `account_id`（`123-456-7890`） | `advertiser_id`（十多位纯数字） | 字段更名 + 数字校验 |
| `mcc_id` / 表 `mcc` | `bc_id` / 表 `tt_bcs` | BC 变更历史表 `tt_account_bc_history` |
| `agent_id` | `agent_id`（复用 `agents`） | 查询时 `platform='tt'` 隔离 |
| `status_id` | `status_id`（复用 `account_statuses`） | 查询时 `platform='tt'` 隔离 |
| 表 `recharge_records` | 表 `tt_recharge_records` | `account_id` 存 advertiser_id 文本 |
| 表 `account_mcc_history` | 表 `tt_account_bc_history` | `old/new_mcc_id` → `old/new_bc_id` |
| `mccRowClass`/`mccGroupIndex` | `bcRowClass`/`bcGroupIndex` | 前端分组着色 |
| 同步读「我的看板」列 A:H | 10 列 A:J（见 Task 4） | 列结构不同 |
| 充值写「充值表」 | `tt_sheet_mappings.recharge` | 复用 `append_recharge` |

### 共享常量 / 复用接口（本计划定义，后续任务引用）

后端新文件 `py/routes/tt_accounts_routes.py` 内定义以下 helper，供各端点使用：

- `tt_accounts_bp = Blueprint('tt_accounts', __name__)` —— 在 `main.py` 注册
- `_get_role(db, uid) -> str` —— 返回 `users.role`，无用户返回 `'user'`
- `_get_tt_sheet_id(db) -> str` —— 读 `tags['tt_sheet_id']`
- `_get_tt_sheet_mappings(db) -> dict` —— 读 `tags['tt_sheet_mappings']`，解析失败返回 `{}`
- `_resolve_agent_id(db, agent, agent_id, uid) -> int|None` —— 文本回退：`agent_id` 为 None 且有 `agent` 文本时，按 `platform='tt'` 查/插 `agents`
- `_resolve_status_id(db, status, status_id, uid) -> int|None` —— 同上，按 `platform='tt'` 查/插 `account_statuses`
- `_record_bc_change(db, account_row_id, new_bc_id, uid, change_type) -> None` —— 写 `tt_account_bc_history`

异步 Sheets 写：**在函数内延迟导入** `from main import _GOOGLE_SHEETS_CONFIG, _sync_sheets_background`（避免循环导入），复用 GG 的凭据路径与后台线程工具。

---

### Task 1: 数据库迁移 — 4 张 `tt_*` 表 + `agents` platform 列

**Files:**
- Modify: `py/database.py`（TT 平台表区域，`tt_bcs`/`tt_products` 附近）
- Test: `py/tests/test_tt_accounts.py`（新建）

**Interfaces:**
- Consumes: `_add_column_if_missing(conn, table, col_name, col_def)`（database.py:74）、`conn`（`_migrate_if_needed` 传入的 sqlite 连接）
- Produces: 表 `tt_accounts`、`tt_account_bc_history`、`tt_recharge_records`、`tt_recycle_reasons`；`agents.platform` 列；`tt` 平台代理初始数据。后续 Task 2-4 的端点直接读写这些表。

- [ ] **Step 1: 写失败的 schema 测试**

创建 `py/tests/test_tt_accounts.py`：

```python
"""TT 广告账户路由测试。"""
import os
import sys

_py_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _py_dir not in sys.path:
    sys.path.insert(0, _py_dir)

import database  # noqa: E402


def test_tt_accounts_tables_exist():
    db = database.get_db()
    for tbl in ("tt_accounts", "tt_account_bc_history",
                "tt_recharge_records", "tt_recycle_reasons"):
        row = db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (tbl,)
        ).fetchone()
        assert row is not None, f"表 {tbl} 不存在"
    db.close()


def test_agents_has_platform_column():
    db = database.get_db()
    cols = [r["name"] for r in db.execute("PRAGMA table_info(agents)").fetchall()]
    assert "platform" in cols
    db.close()


def test_agents_copied_to_tt():
    """GG 代理应复制到 platform='tt'（INSERT OR IGNORE，冲突跳过）。"""
    db = database.get_db()
    # 先确保 GG 有一条代理
    db.execute("INSERT OR IGNORE INTO agents(name, owner_id, platform) VALUES(?,?, 'gg')",
               ("卡尔", 1))
    db.commit()
    cnt = db.execute(
        "SELECT COUNT(*) FROM agents WHERE name='卡尔' AND platform='tt'"
    ).fetchone()[0]
    assert cnt == 1
    db.close()
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd py && python -m pytest tests/test_tt_accounts.py -v`
Expected: FAIL — `tt_accounts` 表不存在 / `platform` 列不存在。

- [ ] **Step 3: 新增 4 张表 + agents platform 列**

在 `py/database.py` 的 TT 平台表区域（`tt_bcs`/`tt_products` 的 `conn.executescript(...)` 附近，或紧随其后），追加：

```python
    # ==================== TT 广告账户表 ====================
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS tt_accounts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT DEFAULT '',
            advertiser_id TEXT NOT NULL UNIQUE,
            bc_id INTEGER REFERENCES tt_bcs(id),
            country TEXT DEFAULT '',
            agent_id INTEGER REFERENCES agents(id),
            timezone TEXT DEFAULT '',
            consumption TEXT DEFAULT '',
            status_id INTEGER REFERENCES account_statuses(id),
            acquired_date TEXT DEFAULT (date('now','localtime')),
            death_date TEXT DEFAULT '',
            status_changed_date TEXT DEFAULT '',
            remark TEXT DEFAULT '',
            owner_id INTEGER REFERENCES users(id),
            deleted_at TEXT DEFAULT NULL,
            created_at TEXT DEFAULT (datetime('now','localtime')),
            updated_at TEXT DEFAULT (datetime('now','localtime'))
        );
        CREATE INDEX IF NOT EXISTS idx_tt_accounts_owner ON tt_accounts(owner_id);
        CREATE INDEX IF NOT EXISTS idx_tt_accounts_bc ON tt_accounts(bc_id);
        CREATE INDEX IF NOT EXISTS idx_tt_accounts_list ON tt_accounts(owner_id, status_id, deleted_at);

        CREATE TABLE IF NOT EXISTS tt_account_bc_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            account_id INTEGER NOT NULL REFERENCES tt_accounts(id) ON DELETE CASCADE,
            old_bc_id INTEGER,
            new_bc_id INTEGER,
            changed_by INTEGER REFERENCES users(id),
            change_type TEXT NOT NULL DEFAULT 'manual',
            created_at TEXT DEFAULT (datetime('now','localtime'))
        );
        CREATE INDEX IF NOT EXISTS idx_tt_acbh_account ON tt_account_bc_history(account_id);

        CREATE TABLE IF NOT EXISTS tt_recharge_records (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            account_id TEXT NOT NULL,
            amount TEXT NOT NULL,
            agent_id INTEGER REFERENCES agents(id),
            operator TEXT DEFAULT '',
            status TEXT DEFAULT '',
            created_by INTEGER REFERENCES users(id),
            sheets_synced INTEGER DEFAULT 0,
            sheets_error TEXT DEFAULT '',
            created_at TEXT DEFAULT (datetime('now','localtime'))
        );
        CREATE INDEX IF NOT EXISTS idx_tt_recharge_account ON tt_recharge_records(account_id);

        CREATE TABLE IF NOT EXISTS tt_recycle_reasons (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            owner_id INTEGER REFERENCES users(id),
            created_at TEXT DEFAULT (datetime('now','localtime')),
            UNIQUE(name, owner_id)
        );
    """)
```

在 `_add_column_if_missing` 调用区（database.py 约 141-154 行，`account_statuses` platform 之后）追加一行：

```python
    _add_column_if_missing(conn, "agents", "platform", "platform TEXT DEFAULT 'gg'")
```

- [ ] **Step 4: 新增复制函数 + 挂载迁移**

在 `py/database.py` 的 `_copy_gg_options_to_tt` 函数（database.py:1200）**之后**，新增：

```python
def _copy_gg_agents_to_tt(conn: sqlite3.Connection):
    """一次性迁移：将 GG 代理复制一份到 TT 平台（owner_id 统一为 1，冲突跳过）。

    注意：agents 保持 UNIQUE(name, owner_id) 不变，只加 platform 列做隔离标记；
    INSERT OR IGNORE 在 (name, owner_id=1) 已存在时跳过，不报错。
    """
    migrated = conn.execute(
        "SELECT value FROM config WHERE key='migrated_copy_agents_to_tt'"
    ).fetchone()
    if migrated:
        return
    for s in conn.execute("SELECT DISTINCT name FROM agents WHERE platform='gg'").fetchall():
        conn.execute(
            "INSERT OR IGNORE INTO agents(name, owner_id, platform) VALUES(?,1,'tt')",
            (s["name"],))
    conn.execute("INSERT OR REPLACE INTO config(key,value) VALUES('migrated_copy_agents_to_tt','1')")
    conn.commit()
```

在 `_migrate_if_needed`（database.py:1234）中，`_copy_gg_options_to_tt(conn)` 之后追加调用：

```python
    # 复制 GG 代理到 TT
    _copy_gg_agents_to_tt(conn)
```

- [ ] **Step 5: 运行测试确认通过**

Run: `cd py && python -m pytest tests/test_tt_accounts.py -v`
Expected: PASS（4 个表存在、platform 列存在、代理已复制）。

- [ ] **Step 6: Commit**

```bash
git add py/database.py py/tests/test_tt_accounts.py
git commit -m "feat: 新增 TT 广告账户 4 张表 + agents platform 列迁移"
```

---

### Task 2: 账户 CRUD + 查户 + BC 历史端点

**Files:**
- Create: `py/routes/tt_accounts_routes.py`
- Modify: `py/main.py`（注册 blueprint）
- Test: `py/tests/test_tt_accounts.py`（追加）

**Interfaces:**
- Consumes: `helpers.ok/err/get_uid/get_db/parse_body`、`decorators.tt_required`、Task 1 的表
- Produces: blueprint `tt_accounts_bp`；端点列表见下。Task 3/4 复用本文件的 helper（`_get_role`、`_resolve_agent_id`、`_resolve_status_id`、`_record_bc_change`、`_get_tt_sheet_id`、`_get_tt_sheet_mappings`）。

本任务实现端点：
- `GET /api/tt/accounts/list` — 列表 + 筛选 + `status_counts`
- `GET /api/tt/accounts/lookup` — 按 advertiser_id 查本地库
- `POST /api/tt/accounts/batch-lookup` — 批量查本地库
- `POST /api/tt/accounts/create` — 新增
- `POST /api/tt/accounts/batch-create` — 批量导入
- `PUT /api/tt/accounts/<id>` — 更新（含 consumption）
- `PUT /api/tt/accounts/<id>/reassign` — 换绑 BC（记录历史）
- `DELETE /api/tt/accounts/<id>` — 软删除
- `POST /api/tt/accounts/batch-delete` — 批量软删除
- `POST /api/tt/accounts/<id>/restore` — 恢复
- `DELETE /api/tt/accounts/<id>/permanent` — 永久删除
- `GET /api/tt/accounts/deleted` — 已删除列表
- `POST /api/tt/accounts/batch-update` — 批量改状态/BC
- `GET /api/tt/accounts/<id>/bc-history` — BC 历史
- `DELETE /api/tt/accounts/<id>/bc-history/<hid>` — 删除历史

**参考 GG 端点**（`py/main.py`）：`accounts_list`(3621)、`accounts_batch_create`(3936)、`accounts_update`(4050)、`accounts_reassign`(4184)、`accounts_delete`(4240)、`accounts_batch_delete`(4277)、`accounts_restore`(4299)、`accounts_permanent_delete`(4336)、`accounts_deleted_list`(4358)、`accounts_batch_update`(4386)。实现时对照替换字段（`account_id`→`advertiser_id`、`mcc_id`→`bc_id`、`account_mcc_history`→`tt_account_bc_history`、`mcc`→`tt_bcs`），并应用「Global Constraints」的差异规则。**本任务不写回收清单**（留待 Task 4）。

- [ ] **Step 1: 写失败的 list 测试**

在 `py/tests/test_tt_accounts.py` 追加：

```python
import unittest.mock as mock  # noqa: E402


def _mk_account(client, headers, advertiser_id="1234567890123", **kw):
    body = {"advertiser_id": advertiser_id, **kw}
    return client.post("/api/tt/accounts/create", headers=headers, json=body)


def test_account_create_and_list(client, tt_headers):
    resp = _mk_account(client, tt_headers, name="测试户")
    assert resp.status_code == 200
    aid = resp.get_json()["id"]
    assert aid > 0

    resp = client.get("/api/tt/accounts/list", headers=tt_headers)
    data = resp.get_json()
    assert data["total"] == 1
    assert data["items"][0]["advertiser_id"] == "1234567890123"
    assert "status_counts" in data


def test_account_create_rejects_non_digit(client, tt_headers):
    resp = _mk_account(client, tt_headers, advertiser_id="123-456-789")
    assert resp.status_code == 400


def test_account_create_duplicate_conflict(client, tt_headers):
    _mk_account(client, tt_headers, advertiser_id="1234567890123")
    resp = _mk_account(client, tt_headers, advertiser_id="1234567890123")
    assert resp.status_code == 409
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd py && python -m pytest tests/test_tt_accounts.py::test_account_create_and_list -v`
Expected: FAIL — 404（端点不存在）。

- [ ] **Step 3: 新建 blueprint 文件骨架 + helper**

创建 `py/routes/tt_accounts_routes.py`：

```python
"""TikTok 广告账户 API 路由 — 账户管理 / 充值 / 同步 / 回收原因"""
import json

from flask import Blueprint, request
from flask_jwt_extended import jwt_required

from .helpers import ok, err, get_uid, get_db, parse_body
from .decorators import tt_required

tt_accounts_bp = Blueprint('tt_accounts', __name__)


def _get_role(db, uid):
    user = db.execute("SELECT role FROM users WHERE id=?", (uid,)).fetchone()
    return user['role'] if user else 'user'


def _get_tt_sheet_id(db):
    row = db.execute("SELECT value FROM tags WHERE key='tt_sheet_id'").fetchone()
    return (row["value"] if row and row["value"] else "")


def _get_tt_sheet_mappings(db):
    row = db.execute("SELECT value FROM tags WHERE key='tt_sheet_mappings'").fetchone()
    if row and row["value"]:
        try:
            loaded = json.loads(row["value"])
            if isinstance(loaded, dict):
                return loaded
        except Exception:
            pass
    return {"accounts": "账户明细", "recharge": "充值表",
            "my_dashboard": "我的看板", "recycle": "回收户清单"}


def _resolve_agent_id(db, agent, agent_id):
    """agent_id 为 None 且有 agent 文本时，按 platform='tt' 查/插 agents。"""
    if agent_id is not None:
        return agent_id
    if not agent:
        return None
    existing = db.execute(
        "SELECT id FROM agents WHERE name=? AND platform='tt'", (agent,)
    ).fetchone()
    if existing:
        return existing["id"]
    db.execute("INSERT INTO agents(name, owner_id, platform) VALUES(?,?, 'tt')", (agent, 1))
    return db.execute("SELECT last_insert_rowid()").fetchone()[0]


def _resolve_status_id(db, status, status_id):
    """status_id 为 None 且有 status 文本时，按 platform='tt' 查/插 account_statuses。"""
    if status_id is not None:
        return status_id
    if not status:
        return None
    existing = db.execute(
        "SELECT id FROM account_statuses WHERE name=? AND platform='tt'", (status,)
    ).fetchone()
    if existing:
        return existing["id"]
    db.execute("INSERT INTO account_statuses(name, owner_id, platform) VALUES(?,?, 'tt')", (status, 1))
    return db.execute("SELECT last_insert_rowid()").fetchone()[0]


def _record_bc_change(db, account_row_id, new_bc_id, uid, change_type):
    if new_bc_id == 0 or new_bc_id == "0" or (isinstance(new_bc_id, str) and not new_bc_id.strip()):
        new_bc_id = None
    if not new_bc_id:
        return
    db.execute(
        "INSERT INTO tt_account_bc_history(account_id, old_bc_id, new_bc_id, changed_by, change_type) "
        "VALUES(?, NULL, ?, ?, ?)",
        (account_row_id, new_bc_id, uid, change_type))
```

- [ ] **Step 4: 实现 create / lookup / list 端点**

在文件末尾追加：

```python
# ==================== 广告账户 CRUD ====================

@tt_accounts_bp.route('/api/tt/accounts/create', methods=['POST'])
@jwt_required()
@tt_required
def create_account():
    db = get_db()
    uid = get_uid()
    data = parse_body()
    advertiser_id = str(data.get("advertiser_id") or "").strip()
    if not advertiser_id:
        return err("请提供广告账户 ID")
    if not advertiser_id.isdigit():
        return err("广告账户 ID 必须是纯数字")
    # 唯一冲突检测
    ex = db.execute(
        "SELECT a.id, u.display_name, u.username FROM tt_accounts a "
        "LEFT JOIN users u ON a.owner_id = u.id WHERE a.advertiser_id = ?",
        (advertiser_id,)
    ).fetchone()
    if ex:
        owner = ex["display_name"] or ex["username"] or "未知"
        return err(f"该广告账户已存在，归属人：{owner}", 409)

    bc_id = data.get("bc_id") or None
    if bc_id == "" or bc_id == 0 or bc_id == "0":
        bc_id = None
    agent_id = _resolve_agent_id(db, (data.get("agent") or "").strip(), data.get("agent_id"))
    status = (data.get("status") or "").strip() or "存活"
    status_id = _resolve_status_id(db, status, data.get("status_id"))
    now = __import__("datetime").datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    db.execute(
        "INSERT INTO tt_accounts(name, advertiser_id, bc_id, country, agent_id, timezone, "
        "consumption, status_id, acquired_date, remark, owner_id, created_at, updated_at) "
        "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
        ((data.get("name") or "").strip(), advertiser_id, bc_id,
         (data.get("country") or "").strip(), agent_id, (data.get("timezone") or "").strip(),
         (data.get("consumption") or "").strip(), status_id,
         (data.get("acquired_date") or None), (data.get("remark") or "").strip(),
         uid, now, now))
    db.commit()
    new_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]
    _record_bc_change(db, new_id, bc_id, uid, "create")
    db.commit()
    return ok({"id": new_id})


@tt_accounts_bp.route('/api/tt/accounts/lookup', methods=['GET'])
@jwt_required()
@tt_required
def lookup_account():
    db = get_db()
    advertiser_id = (request.args.get("advertiser_id") or "").strip()
    if not advertiser_id:
        return err("缺少 advertiser_id")
    row = db.execute(
        "SELECT a.*, u.username, u.display_name, st.name AS status_name, ag.name AS agent_name "
        "FROM tt_accounts a "
        "LEFT JOIN users u ON a.owner_id = u.id "
        "LEFT JOIN account_statuses st ON a.status_id = st.id "
        "LEFT JOIN agents ag ON a.agent_id = ag.id "
        "WHERE a.advertiser_id = ?", (advertiser_id,)
    ).fetchone()
    if not row:
        return ok({"found": False})
    d = dict(row)
    d["found"] = True
    d["status"] = d.get("status_name") or ""
    d["agent"] = d.get("agent_name") or ""
    return ok(d)


@tt_accounts_bp.route('/api/tt/accounts/batch-lookup', methods=['POST'])
@jwt_required()
@tt_required
def batch_lookup_accounts():
    db = get_db()
    data = parse_body()
    ids = data.get("account_ids") or []
    if not ids or not isinstance(ids, list):
        return err("请提供 account_ids 列表")
    ids = [str(i).strip() for i in ids if str(i).strip()]
    found, not_found = [], []
    for aid in ids:
        row = db.execute(
            "SELECT a.id, a.advertiser_id, u.display_name, u.username "
            "FROM tt_accounts a LEFT JOIN users u ON a.owner_id = u.id "
            "WHERE a.advertiser_id = ?", (aid,)
        ).fetchone()
        if row:
            d = dict(row)
            d["owner"] = d.get("display_name") or d.get("username") or "未知"
            found.append(d)
        else:
            not_found.append(aid)
    return ok({"found": found, "not_found": not_found})


@tt_accounts_bp.route('/api/tt/accounts/list', methods=['GET'])
@jwt_required()
@tt_required
def list_accounts():
    db = get_db()
    uid = get_uid()
    role = _get_role(db, uid)

    page = request.args.get('page', 1, type=int)
    size = request.args.get('size', 50, type=int)
    search = (request.args.get('search') or '').strip()
    bc_id = (request.args.get('bc_id') or '').strip()
    agent_id = (request.args.get('agent_id') or '').strip()
    status_id = (request.args.get('status_id') or '').strip()
    timezone = (request.args.get('timezone') or '').strip()
    owner_id = (request.args.get('owner_id') or '').strip()

    where = ["a.deleted_at IS NULL"]
    params = []
    if role in ('developer', 'admin'):
        if owner_id:
            where.append("a.owner_id = ?")
            params.append(owner_id)
    else:
        where.append("a.owner_id = ?")
        params.append(uid)
    if search:
        where.append("(a.name LIKE ? OR a.advertiser_id LIKE ?)")
        params += [f"%{search}%", f"%{search}%"]
    if bc_id:
        where.append("a.bc_id = ?"); params.append(bc_id)
    if agent_id:
        where.append("a.agent_id = ?"); params.append(agent_id)
    if status_id:
        where.append("a.status_id = ?"); params.append(status_id)
    if timezone:
        where.append("a.timezone = ?"); params.append(timezone)

    where_clause = " AND ".join(where)
    offset = (page - 1) * size
    total = db.execute(
        f"SELECT COUNT(*) FROM tt_accounts a WHERE {where_clause}", params
    ).fetchone()[0]
    rows = db.execute(
        f"""SELECT a.*, b.name AS bc_name, ag.name AS agent_name, st.name AS status_name,
                   u.display_name AS owner_name
            FROM tt_accounts a
            LEFT JOIN tt_bcs b ON a.bc_id = b.id
            LEFT JOIN agents ag ON a.agent_id = ag.id
            LEFT JOIN account_statuses st ON a.status_id = st.id
            LEFT JOIN users u ON a.owner_id = u.id
            WHERE {where_clause}
            ORDER BY (a.bc_id IS NULL), a.bc_id, a.created_at DESC
            LIMIT ? OFFSET ?""",
        params + [size, offset]
    ).fetchall()
    items = [dict(r) for r in rows]
    for it in items:
        it['bc'] = it.get('bc_name') or ''
        it['agent'] = it.get('agent_name') or ''
        it['status'] = it.get('status_name') or '存活'
        it['owner'] = it.get('owner_name') or ''

    # 各状态计数（不含 status 筛选，展示所有状态数量）
    sc_where = [w for w in where if "status_id" not in w]
    sc_where[0] = "a.deleted_at IS NULL"
    sc_where.append("a.owner_id = ?" if owner_id else ("a.owner_id = ?" if role not in ('developer', 'admin') else "1=1"))
    sc_params = [p for p in params]
    # 简化：直接用与列表相同的 owner 过滤重算
    sc_where2 = ["a.deleted_at IS NULL"]
    sc_params2 = []
    if role in ('developer', 'admin'):
        if owner_id:
            sc_where2.append("a.owner_id = ?"); sc_params2.append(owner_id)
    else:
        sc_where2.append("a.owner_id = ?"); sc_params2.append(uid)
    if search:
        sc_where2.append("(a.name LIKE ? OR a.advertiser_id LIKE ?)")
        sc_params2 += [f"%{search}%", f"%{search}%"]
    if bc_id:
        sc_where2.append("a.bc_id = ?"); sc_params2.append(bc_id)
    if agent_id:
        sc_where2.append("a.agent_id = ?"); sc_params2.append(agent_id)
    if timezone:
        sc_where2.append("a.timezone = ?"); sc_params2.append(timezone)
    status_counts = {}
    for r in db.execute(
        "SELECT COALESCE(st.name, '存活') AS status, COUNT(*) AS cnt "
        "FROM tt_accounts a LEFT JOIN account_statuses st ON a.status_id = st.id "
        "WHERE " + " AND ".join(sc_where2) + " GROUP BY st.name",
        sc_params2
    ).fetchall():
        s = r["status"] or "存活"
        status_counts[s] = status_counts.get(s, 0) + r["cnt"]

    return ok({'items': items, 'total': total, 'page': page, 'size': size,
               'status_counts': status_counts})
```

- [ ] **Step 5: 运行测试确认通过**

Run: `cd py && python -m pytest tests/test_tt_accounts.py -v`
Expected: PASS（create/list/lookup 测试通过）。

- [ ] **Step 6: 实现 update / batch-create / batch-update / reassign**

在文件末尾追加（对照 GG `accounts_update`(4050)、`accounts_batch_create`(3936)、`accounts_batch_update`(4386)、`accounts_reassign`(4184)，字段替换后实现；关键差异：`mcc_id`→`bc_id`，`account_mcc_history`→`tt_account_bc_history`，`consumption` 字段可编辑）：

```python
@tt_accounts_bp.route('/api/tt/accounts/<int:aid>', methods=['PUT'])
@jwt_required()
@tt_required
def update_account(aid):
    db = get_db()
    uid = get_uid()
    role = _get_role(db, uid)
    data = parse_body()
    row = db.execute(
        "SELECT a.*, st.name AS status_name FROM tt_accounts a "
        "LEFT JOIN account_statuses st ON a.status_id = st.id WHERE a.id=?", (aid,)
    ).fetchone()
    if not row:
        return err("账户不存在", 404)
    if role not in ('developer', 'admin') and row["owner_id"] != uid:
        return err("无权限", 403)

    editable = ["name", "country", "timezone", "consumption", "agent_id", "status_id",
                "acquired_date", "death_date", "remark"]
    for f in editable:
        if f in data and data[f] is not None:
            db.execute(f"UPDATE tt_accounts SET {f}=? WHERE id=?",
                       (str(data[f]).strip() if isinstance(data[f], str) else data[f], aid))

    # agent/status 文本回退
    if "agent" in data or "agent_id" in data:
        agent_id = _resolve_agent_id(db, (data.get("agent") or "").strip(), data.get("agent_id"))
        if agent_id is not None:
            db.execute("UPDATE tt_accounts SET agent_id=? WHERE id=?", (agent_id, aid))
    if "status" in data or "status_id" in data:
        status_id = _resolve_status_id(db, (data.get("status") or "").strip(), data.get("status_id"))
        if status_id is not None:
            # 状态变更时间
            new_status_name = db.execute(
                "SELECT name FROM account_statuses WHERE id=?", (status_id,)
            ).fetchone()
            new_status_name = new_status_name["name"] if new_status_name else ""
            if new_status_name and new_status_name != (row["status_name"] or ""):
                db.execute("UPDATE tt_accounts SET status_changed_date=datetime('now','localtime') WHERE id=?", (aid,))
            if new_status_name == "死亡":
                db.execute("UPDATE tt_accounts SET death_date=date('now','localtime') WHERE id=?", (aid,))
            elif (row["status_name"] or "") == "死亡":
                db.execute("UPDATE tt_accounts SET death_date='' WHERE id=?", (aid,))
            db.execute("UPDATE tt_accounts SET status_id=? WHERE id=?", (status_id, aid))

    # BC 变更（记录历史）
    if "bc_id" in data:
        bc_id = data["bc_id"]
        if bc_id in (None, 0, "0", "") or (isinstance(bc_id, str) and not bc_id.strip()):
            bc_id = None
        old_bc = row["bc_id"]
        if (bc_id or None) != (old_bc or None):
            db.execute(
                "INSERT INTO tt_account_bc_history(account_id, old_bc_id, new_bc_id, changed_by, change_type) "
                "VALUES(?,?,?,?,?)", (aid, old_bc, bc_id, uid, "manual"))
        db.execute("UPDATE tt_accounts SET bc_id=? WHERE id=?", (bc_id, aid))

    db.execute("UPDATE tt_accounts SET updated_at=datetime('now','localtime') WHERE id=?", (aid,))
    db.commit()
    return ok()


@tt_accounts_bp.route('/api/tt/accounts/batch-create', methods=['POST'])
@jwt_required()
@tt_required
def batch_create_accounts():
    db = get_db()
    uid = get_uid()
    data = parse_body()
    account_ids = data.get("account_ids") or []
    if not account_ids or not isinstance(account_ids, list):
        return err("请提供 account_ids 列表")
    common = {
        "name_prefix": (data.get("name_prefix") or "").strip(),
        "bc_id": data.get("bc_id") or None,
        "timezone": (data.get("timezone") or "").strip(),
        "agent": (data.get("agent") or "").strip(),
        "agent_id": data.get("agent_id") or None,
        "status": (data.get("status") or "存活").strip(),
        "status_id": data.get("status_id") or None,
        "country": (data.get("country") or "").strip(),
        "acquired_date": (data.get("acquired_date") or None),
    }
    overrides = data.get("overrides") or {}
    now = __import__("datetime").datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    created, skipped = [], []
    for aid in account_ids:
        aid = str(aid).strip()
        if not aid:
            continue
        if not aid.isdigit():
            skipped.append({"advertiser_id": aid, "reason": "ID 必须是纯数字"})
            continue
        ov = overrides.get(aid, {})
        name = (ov.get("name") or "").strip() or (
            (common["name_prefix"] + " " + aid).strip() if common["name_prefix"] else aid)
        bc_id = ov.get("bc_id") if "bc_id" in ov else common["bc_id"]
        if bc_id in (0, "0", ""):
            bc_id = None
        timezone = ov.get("timezone") if "timezone" in ov else common["timezone"]
        country = ov.get("country") if "country" in ov else common["country"]
        agent_id = _resolve_agent_id(db, ov.get("agent", common["agent"]), ov.get("agent_id", common["agent_id"]))
        status_id = _resolve_status_id(db, ov.get("status", common["status"]), ov.get("status_id", common["status_id"]))
        acquired_date = ov.get("acquired_date") if "acquired_date" in ov else common["acquired_date"]
        try:
            db.execute(
                "INSERT INTO tt_accounts(name, advertiser_id, bc_id, country, agent_id, timezone, "
                "status_id, acquired_date, owner_id, created_at, updated_at) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                (name, aid, bc_id, country, agent_id, timezone, status_id,
                 acquired_date, uid, now, now))
            db.commit()
            created.append(aid)
            new_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]
            _record_bc_change(db, new_id, bc_id, uid, "import")
            db.commit()
        except Exception as e:
            err_msg = str(e).lower()
            if "advertiser_id" in err_msg or "unique" in err_msg:
                skipped.append({"advertiser_id": aid, "reason": "已存在"})
            else:
                skipped.append({"advertiser_id": aid, "reason": str(e)})
    return ok({"created": len(created), "created_ids": created, "skipped": skipped})


@tt_accounts_bp.route('/api/tt/accounts/batch-update', methods=['POST'])
@jwt_required()
@tt_required
def batch_update_accounts():
    db = get_db()
    uid = get_uid()
    data = parse_body()
    ids = data.get("ids") or []
    field = (data.get("field") or "").strip()
    value = data.get("value")
    if not ids or not field:
        return err("缺少参数")
    allowed = ["status_id", "agent_id", "bc_id", "timezone"]
    if field not in allowed:
        return err(f"不允许修改字段: {field}")
    if field == "bc_id" and value in (None, 0, "0", ""):
        value = None
    role = _get_role(db, uid)
    for aid in ids:
        # owner 权限校验
        if role not in ('developer', 'admin'):
            r = db.execute("SELECT owner_id, bc_id FROM tt_accounts WHERE id=?", (aid,)).fetchone()
            if not r or r["owner_id"] != uid:
                continue
        else:
            r = db.execute("SELECT owner_id, bc_id FROM tt_accounts WHERE id=?", (aid,)).fetchone()
            if not r:
                continue
        if field == "bc_id":
            if (value or None) != (r["bc_id"] or None):
                db.execute(
                    "INSERT INTO tt_account_bc_history(account_id, old_bc_id, new_bc_id, changed_by, change_type) "
                    "VALUES(?,?,?,?,?)", (aid, r["bc_id"], value, uid, "batch"))
        if field == "status_id" and value:
            st_name = db.execute("SELECT name FROM account_statuses WHERE id=?", (value,)).fetchone()
            if st_name and st_name["name"] == "死亡":
                db.execute("UPDATE tt_accounts SET death_date=date('now','localtime') WHERE id=?", (aid,))
            db.execute("UPDATE tt_accounts SET status_changed_date=datetime('now','localtime') WHERE id=?", (aid,))
        db.execute(f"UPDATE tt_accounts SET {field}=?, updated_at=datetime('now','localtime') WHERE id=?",
                   (value, aid))
    db.commit()
    return ok({"updated": len(ids)})


@tt_accounts_bp.route('/api/tt/accounts/<int:aid>/reassign', methods=['PUT'])
@jwt_required()
@tt_required
def reassign_account(aid):
    db = get_db()
    uid = get_uid()
    data = parse_body()
    existing = db.execute(
        "SELECT a.*, u.username, u.display_name FROM tt_accounts a "
        "LEFT JOIN users u ON a.owner_id = u.id WHERE a.id = ?", (aid,)
    ).fetchone()
    if not existing:
        return err("账户不存在", 404)
    if int(existing["owner_id"] or 0) == uid:
        return err("该账户已属于当前用户，无需转移", 409)
    db.execute("UPDATE tt_accounts SET owner_id=?, updated_at=datetime('now','localtime') WHERE id=?",
               (uid, aid))
    for f in ["name", "country", "timezone", "agent_id", "status_id", "acquired_date", "consumption"]:
        if f in data and data[f] is not None:
            db.execute(f"UPDATE tt_accounts SET {f}=? WHERE id=?",
                       (str(data[f]).strip() if isinstance(data[f], str) else data[f], aid))
    if "bc_id" in data:
        bc_id = data["bc_id"]
        if bc_id in (None, 0, "0", "") or (isinstance(bc_id, str) and not bc_id.strip()):
            bc_id = None
        db.execute(
            "INSERT INTO tt_account_bc_history(account_id, old_bc_id, new_bc_id, changed_by, change_type) "
            "VALUES(?,?,?,?,?)", (aid, existing["bc_id"], bc_id, uid, "reassign"))
        db.execute("UPDATE tt_accounts SET bc_id=? WHERE id=?", (bc_id, aid))
    db.commit()
    return ok({"message": f"账户「{existing['name'] or existing['advertiser_id']}」已转移至当前用户"})
```

- [ ] **Step 7: 实现软删除 / 恢复 / 永久删除 / 批量删除 / 已删除列表**

在文件末尾追加（对照 GG `accounts_delete`(4240)/`accounts_batch_delete`(4277)/`accounts_restore`(4299)/`accounts_permanent_delete`(4336)/`accounts_deleted_list`(4358)；**本任务不含解绑/回收清单 Sheet 写**，仅 DB 操作）：

```python
@tt_accounts_bp.route('/api/tt/accounts/<int:aid>', methods=['DELETE'])
@jwt_required()
@tt_required
def delete_account(aid):
    db = get_db()
    uid = get_uid()
    role = _get_role(db, uid)
    ac = db.execute("SELECT id, owner_id FROM tt_accounts WHERE id=? AND deleted_at IS NULL", (aid,)).fetchone()
    if not ac:
        return err("账户不存在或已删除", 404)
    if role not in ('developer', 'admin') and ac["owner_id"] != uid:
        return err("无权限", 403)
    db.execute("UPDATE tt_accounts SET deleted_at=datetime('now','localtime'), "
               "updated_at=datetime('now','localtime') WHERE id=?", (aid,))
    db.commit()
    return ok()


@tt_accounts_bp.route('/api/tt/accounts/batch-delete', methods=['POST'])
@jwt_required()
@tt_required
def batch_delete_accounts():
    db = get_db()
    uid = get_uid()
    role = _get_role(db, uid)
    ids = parse_body().get("ids") or []
    if not ids:
        return err("未选择账户")
    for aid in ids:
        if role in ('developer', 'admin'):
            db.execute("UPDATE tt_accounts SET deleted_at=datetime('now','localtime') WHERE id=? AND deleted_at IS NULL", (aid,))
        else:
            db.execute("UPDATE tt_accounts SET deleted_at=datetime('now','localtime') WHERE id=? AND owner_id=? AND deleted_at IS NULL", (aid, uid))
    db.commit()
    return ok({"deleted": len(ids)})


@tt_accounts_bp.route('/api/tt/accounts/<int:aid>/restore', methods=['POST'])
@jwt_required()
@tt_required
def restore_account(aid):
    db = get_db()
    uid = get_uid()
    role = _get_role(db, uid)
    ac = db.execute("SELECT owner_id FROM tt_accounts WHERE id=? AND deleted_at IS NOT NULL", (aid,)).fetchone()
    if not ac:
        return err("账户不存在或未被删除", 404)
    if role not in ('developer', 'admin') and ac["owner_id"] != uid:
        return err("无权限", 403)
    db.execute("UPDATE tt_accounts SET deleted_at=NULL, updated_at=datetime('now','localtime') WHERE id=?", (aid,))
    db.commit()
    return ok()


@tt_accounts_bp.route('/api/tt/accounts/<int:aid>/permanent', methods=['DELETE'])
@jwt_required()
@tt_required
def permanent_delete_account(aid):
    db = get_db()
    uid = get_uid()
    role = _get_role(db, uid)
    ac = db.execute("SELECT owner_id FROM tt_accounts WHERE id=? AND deleted_at IS NOT NULL", (aid,)).fetchone()
    if not ac:
        return err("账户不存在或未被删除", 404)
    if role not in ('developer', 'admin') and ac["owner_id"] != uid:
        return err("无权限", 403)
    db.execute("DELETE FROM tt_recharge_records WHERE account_id IN "
               "(SELECT advertiser_id FROM tt_accounts WHERE id=?)", (aid,))
    db.execute("DELETE FROM tt_account_bc_history WHERE account_id=?", (aid,))
    db.execute("DELETE FROM tt_accounts WHERE id=?", (aid,))
    db.commit()
    return ok()


@tt_accounts_bp.route('/api/tt/accounts/deleted', methods=['GET'])
@jwt_required()
@tt_required
def deleted_accounts_list():
    db = get_db()
    uid = get_uid()
    role = _get_role(db, uid)
    if role in ('developer', 'admin'):
        rows = db.execute(
            "SELECT a.id, a.name, a.advertiser_id, a.deleted_at, "
            "ag.name AS agent_name, st.name AS status_name "
            "FROM tt_accounts a LEFT JOIN agents ag ON a.agent_id = ag.id "
            "LEFT JOIN account_statuses st ON a.status_id = st.id "
            "WHERE a.deleted_at IS NOT NULL ORDER BY a.deleted_at DESC").fetchall()
    else:
        rows = db.execute(
            "SELECT a.id, a.name, a.advertiser_id, a.deleted_at, "
            "ag.name AS agent_name, st.name AS status_name "
            "FROM tt_accounts a LEFT JOIN agents ag ON a.agent_id = ag.id "
            "LEFT JOIN account_statuses st ON a.status_id = st.id "
            "WHERE a.owner_id=? AND a.deleted_at IS NOT NULL ORDER BY a.deleted_at DESC",
            (uid,)).fetchall()
    items = []
    for r in rows:
        d = dict(r)
        d["agent"] = d.get("agent_name") or ""
        d["status"] = d.get("status_name") or ""
        items.append(d)
    return ok({"items": items})
```

- [ ] **Step 8: 实现 BC 历史端点**

在文件末尾追加：

```python
@tt_accounts_bp.route('/api/tt/accounts/<int:aid>/bc-history', methods=['GET'])
@jwt_required()
@tt_required
def bc_history(aid):
    db = get_db()
    rows = db.execute(
        "SELECT h.id, h.old_bc_id, h.new_bc_id, h.change_type, h.created_at, "
        "u.display_name AS changed_by_name, "
        "b1.name AS old_bc_name, b2.name AS new_bc_name "
        "FROM tt_account_bc_history h "
        "LEFT JOIN users u ON h.changed_by = u.id "
        "LEFT JOIN tt_bcs b1 ON h.old_bc_id = b1.id "
        "LEFT JOIN tt_bcs b2 ON h.new_bc_id = b2.id "
        "WHERE h.account_id=? ORDER BY h.created_at DESC", (aid,)).fetchall()
    items = []
    for r in rows:
        d = dict(r)
        d["old_bc"] = d.get("old_bc_name") or ""
        d["new_bc"] = d.get("new_bc_name") or ""
        d["changed_by"] = d.get("changed_by_name") or ""
        items.append(d)
    return ok({"items": items})


@tt_accounts_bp.route('/api/tt/accounts/<int:aid>/bc-history/<int:hid>', methods=['DELETE'])
@jwt_required()
@tt_required
def delete_bc_history(aid, hid):
    db = get_db()
    db.execute("DELETE FROM tt_account_bc_history WHERE id=? AND account_id=?", (hid, aid))
    db.commit()
    return ok()
```

- [ ] **Step 9: 注册 blueprint**

在 `py/main.py` 的 `tt_bp` 注册处（约 357-358 行）之后追加：

```python
from routes.tt_accounts_routes import tt_accounts_bp
app.register_blueprint(tt_accounts_bp)
```

- [ ] **Step 10: 运行全量 TT 测试确认通过 + 回归**

Run: `cd py && python -m pytest tests/test_tt_accounts.py tests/test_tt_routes.py -v`
Expected: PASS（新测试 + 既有 TT 测试不回归）。

- [ ] **Step 11: Commit**

```bash
git add py/routes/tt_accounts_routes.py py/main.py py/tests/test_tt_accounts.py
git commit -m "feat: TT 广告账户 CRUD + 查户 + BC 历史端点"
```

---

### Task 3: 充值端点

**Files:**
- Modify: `py/routes/tt_accounts_routes.py`
- Test: `py/tests/test_tt_accounts.py`（追加）

**Interfaces:**
- Consumes: Task 2 的 `tt_accounts_bp`、helper；`google_sheets_service.append_recharge(service, spreadsheet_id, sheet_name, rows)`（rows 为 `[{"account_id","amount","agent","operator","status"}]`）；延迟导入 `from main import _GOOGLE_SHEETS_CONFIG, _sync_sheets_background`
- Produces: `tt_recharge_records` 数据；写 DB 后后台异步写「充值表」Sheet

端点：`GET /api/tt/accounts/<id>/recharge-records`、`POST /api/tt/recharge/submit`、`POST /api/tt/recharge/batch-submit`、`PUT /api/tt/recharge/<rid>`、`DELETE /api/tt/recharge/<rid>`、`POST /api/tt/recharge/<rid>/retry-sheets`。

**参考 GG**：`recharge_submit`(4903)、`recharge_batch_submit`、`recharge_update`、`recharge_delete`、`recharge_retry_sheets`（`py/main.py`）；`append_recharge`（`py/google_sheets_service.py:286`）。TT 版差异：表名 `tt_recharge_records`、读 `tt_sheet_mappings.recharge`、`agent_id` 解析按 `platform='tt'`、`account_id` 存 advertiser_id 文本。

- [ ] **Step 1: 写失败的充值测试**

```python
def test_recharge_submit_and_list(client, tt_headers):
    _mk_account(client, tt_headers, advertiser_id="1112223334445")
    resp = client.post("/api/tt/recharge/submit", headers=tt_headers, json={
        "account_id": "1112223334445", "amount": "1000",
    })
    assert resp.status_code == 200
    rid = resp.get_json()["id"]

    resp = client.get("/api/tt/accounts/1/recharge-records", headers=tt_headers)
    assert resp.get_json()["items"][0]["amount"] == "1000"
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd py && python -m pytest tests/test_tt_accounts.py::test_recharge_submit_and_list -v`
Expected: FAIL — 404。

- [ ] **Step 3: 实现充值端点**

在 `tt_accounts_routes.py` 末尾追加：

```python
# ==================== 充值 ====================

def _recharge_sheet_name(db):
    mappings = _get_tt_sheet_mappings(db)
    return (mappings.get("recharge") or "").strip() or "充值表"


def _append_recharge_background(db, uid, sheet_id, sheet_name, rows, rids):
    """后台异步写充值表；成功置 sheets_synced=1，失败写 sheets_error。"""
    from main import _GOOGLE_SHEETS_CONFIG, _sync_sheets_background

    def _do_sync():
        import google_sheets_service as gs
        service = gs.build_service(_GOOGLE_SHEETS_CONFIG["credentials_path"])
        gs.append_recharge(service, sheet_id, sheet_name, rows)

    def _on_fail(status, err_msg):
        _db = get_db()
        if status == "synced":
            for rid in rids:
                _db.execute("UPDATE tt_recharge_records SET sheets_synced=1, sheets_error='' WHERE id=?", (rid,))
        else:
            for rid in rids:
                _db.execute("UPDATE tt_recharge_records SET sheets_error=? WHERE id=?", (err_msg, rid))
        _db.commit()

    _sync_sheets_background(_do_sync, _on_fail)


@tt_accounts_bp.route('/api/tt/accounts/<int:aid>/recharge-records', methods=['GET'])
@jwt_required()
@tt_required
def recharge_records(aid):
    db = get_db()
    ac = db.execute("SELECT advertiser_id FROM tt_accounts WHERE id=?", (aid,)).fetchone()
    if not ac:
        return err("账户不存在", 404)
    rows = db.execute(
        "SELECT r.*, ag.name AS agent_name, u.display_name AS operator_name "
        "FROM tt_recharge_records r "
        "LEFT JOIN agents ag ON r.agent_id = ag.id "
        "LEFT JOIN users u ON r.created_by = u.id "
        "WHERE r.account_id=? ORDER BY r.created_at DESC", (ac["advertiser_id"],)).fetchall()
    items = []
    for r in rows:
        d = dict(r)
        d["agent"] = d.get("agent_name") or ""
        d["operator"] = d.get("operator_name") or d.get("operator") or ""
        items.append(d)
    return ok({"items": items})


@tt_accounts_bp.route('/api/tt/recharge/submit', methods=['POST'])
@jwt_required()
@tt_required
def recharge_submit():
    db = get_db()
    uid = get_uid()
    data = parse_body()
    account_id = (data.get("account_id") or "").strip()
    amount = str(data.get("amount") or "").strip()
    if not account_id or not amount:
        return err("缺少 account_id 或 amount")
    # 校验账户存在且属于当前用户（或 admin）
    role = _get_role(db, uid)
    ac = db.execute("SELECT advertiser_id, status_id, agent_id, owner_id FROM tt_accounts WHERE advertiser_id=? AND deleted_at IS NULL",
                    (account_id,)).fetchone()
    if not ac:
        return err("账户不存在", 404)
    if role not in ('developer', 'admin') and ac["owner_id"] != uid:
        return err("无权限", 403)
    # 仅「存活」状态可充值
    st = db.execute("SELECT name FROM account_statuses WHERE id=?", (ac["status_id"],)).fetchone()
    if st and st["name"] != "存活":
        return err(f"仅「存活」状态可充值，当前状态：{st['name']}")

    agent_id = _resolve_agent_id(db, (data.get("agent") or "").strip(), data.get("agent_id"))
    agent_name = db.execute("SELECT name FROM agents WHERE id=?", (agent_id,)).fetchone()
    agent_name = agent_name["name"] if agent_name else ""
    user = db.execute("SELECT display_name FROM users WHERE id=?", (uid,)).fetchone()
    operator = (user["display_name"] or "") if user else ""
    status = st["name"] if st else ""
    db.execute(
        "INSERT INTO tt_recharge_records(account_id, amount, agent_id, operator, status, created_by, sheets_synced) "
        "VALUES(?,?,?,?,?,?,0)",
        (account_id, amount, agent_id, operator, status, uid))
    db.commit()
    rid = db.execute("SELECT last_insert_rowid()").fetchone()[0]

    sheet_id = _get_tt_sheet_id(db)
    sheet_name = _recharge_sheet_name(db)
    if sheet_id:
        rows = [{"account_id": account_id, "amount": amount, "agent": agent_name,
                 "operator": operator, "status": status}]
        _append_recharge_background(db, uid, sheet_id, sheet_name, rows, [rid])
    return ok({"id": rid})


@tt_accounts_bp.route('/api/tt/recharge/batch-submit', methods=['POST'])
@jwt_required()
@tt_required
def recharge_batch_submit():
    db = get_db()
    uid = get_uid()
    data = parse_body()
    items = data.get("items") or []
    if not items:
        return err("缺少 items")
    user = db.execute("SELECT display_name FROM users WHERE id=?", (uid,)).fetchone()
    operator = (user["display_name"] or "") if user else ""
    rids, rows = [], []
    for it in items:
        account_id = (it.get("account_id") or "").strip()
        amount = str(it.get("amount") or "").strip()
        if not account_id or not amount:
            continue
        ac = db.execute("SELECT agent_id, status_id FROM tt_accounts WHERE advertiser_id=? AND deleted_at IS NULL",
                        (account_id,)).fetchone()
        if not ac:
            continue
        agent_id = _resolve_agent_id(db, (it.get("agent") or "").strip(), it.get("agent_id"))
        agent_name = db.execute("SELECT name FROM agents WHERE id=?", (agent_id,)).fetchone()
        agent_name = agent_name["name"] if agent_name else ""
        st = db.execute("SELECT name FROM account_statuses WHERE id=?", (ac["status_id"],)).fetchone()
        status = st["name"] if st else ""
        db.execute(
            "INSERT INTO tt_recharge_records(account_id, amount, agent_id, operator, status, created_by, sheets_synced) "
            "VALUES(?,?,?,?,?,?,0)",
            (account_id, amount, agent_id, operator, status, uid))
        db.commit()
        rid = db.execute("SELECT last_insert_rowid()").fetchone()[0]
        rids.append(rid)
        rows.append({"account_id": account_id, "amount": amount, "agent": agent_name,
                     "operator": operator, "status": status})
    sheet_id = _get_tt_sheet_id(db)
    if sheet_id and rows:
        _append_recharge_background(db, uid, sheet_id, _recharge_sheet_name(db), rows, rids)
    return ok({"created": len(rows)})


@tt_accounts_bp.route('/api/tt/recharge/<int:rid>', methods=['PUT'])
@jwt_required()
@tt_required
def recharge_update(rid):
    db = get_db()
    uid = get_uid()
    data = parse_body()
    row = db.execute("SELECT created_by FROM tt_recharge_records WHERE id=?", (rid,)).fetchone()
    if not row:
        return err("充值记录不存在", 404)
    role = _get_role(db, uid)
    if role not in ('developer', 'admin') and row["created_by"] != uid:
        return err("无权限", 403)
    for f in ["amount", "operator", "status"]:
        if f in data and data[f] is not None:
            db.execute(f"UPDATE tt_recharge_records SET {f}=? WHERE id=?",
                       (str(data[f]).strip() if isinstance(data[f], str) else data[f], rid))
    db.commit()
    return ok()


@tt_accounts_bp.route('/api/tt/recharge/<int:rid>', methods=['DELETE'])
@jwt_required()
@tt_required
def recharge_delete(rid):
    db = get_db()
    uid = get_uid()
    row = db.execute("SELECT created_by FROM tt_recharge_records WHERE id=?", (rid,)).fetchone()
    if not row:
        return err("充值记录不存在", 404)
    role = _get_role(db, uid)
    if role not in ('developer', 'admin') and row["created_by"] != uid:
        return err("无权限", 403)
    db.execute("DELETE FROM tt_recharge_records WHERE id=?", (rid,))
    db.commit()
    return ok()


@tt_accounts_bp.route('/api/tt/recharge/<int:rid>/retry-sheets', methods=['POST'])
@jwt_required()
@tt_required
def recharge_retry_sheets(rid):
    db = get_db()
    uid = get_uid()
    row = db.execute(
        "SELECT r.*, ag.name AS agent_name FROM tt_recharge_records r "
        "LEFT JOIN agents ag ON r.agent_id = ag.id WHERE r.id=?", (rid,)).fetchone()
    if not row:
        return err("充值记录不存在", 404)
    sheet_id = _get_tt_sheet_id(db)
    if not sheet_id:
        return err("未配置 Google 表格")
    rows = [{"account_id": row["account_id"], "amount": row["amount"],
             "agent": row["agent_name"] or "", "operator": row["operator"] or "",
             "status": row["status"] or ""}]
    _append_recharge_background(db, uid, sheet_id, _recharge_sheet_name(db), rows, [rid])
    return ok()
```

- [ ] **Step 4: 运行测试确认通过**

Run: `cd py && python -m pytest tests/test_tt_accounts.py::test_recharge_submit_and_list -v`
Expected: PASS。注意：`recharge_submit` 会调 `_sync_sheets_background`，但 `sheet_id` 为空时跳过（测试数据库无 `tt_sheet_id`），不会真的后台写。

- [ ] **Step 5: Commit**

```bash
git add py/routes/tt_accounts_routes.py py/tests/test_tt_accounts.py
git commit -m "feat: TT 充值端点（写 DB + 后台异步写充值表）"
```

---

### Task 4: 同步 + 回收原因 + 回收清单

**Files:**
- Modify: `py/routes/tt_accounts_routes.py`
- Modify: `py/google_sheets_service.py`（新增 `append_recycle`）
- Test: `py/tests/test_tt_accounts.py`（追加）

**Interfaces:**
- Consumes: Task 2 的 update/batch-update 端点（本任务在状态改「封禁/死亡」后追加回收清单写入）；`google_sheets_service.read_sheet_values(service, spreadsheet_id, sheet_name, range_str)`；延迟导入 `from main import _GOOGLE_SHEETS_CONFIG, _sync_sheets_background`
- Produces: `append_recycle(service, spreadsheet_id, sheet_name, rows)`；`tt_recycle_reasons` 数据；`/api/tt/recycle-reasons/*` 端点；`/api/tt/accounts/sync-from-sheet`

**参考 GG**：`accounts_sync_from_sheet`（`py/main.py:4534`，读 A:H 8 列）。TT 版读 **10 列 A:J**（见下），无「封户值/解绑」列，新增「国家/时区/消耗/备注/是否回收」。

「我的看板」10 列映射：

| 列 | 字段 | 处理 |
|----|------|------|
| A | 运营 | 门禁：匹配当前用户 `display_name`；存 owner |
| B | 入库时间 | `acquired_date` |
| C | 是否回收 | 仅读取，**不触发状态变更** |
| D | 账户ID | `advertiser_id` |
| E | BC | 不存在则自动新增到 `tt_bcs` |
| F | 国家 | `country` |
| G | 所属渠道 | 不存在则自动新增到 `agents`（platform='tt'） |
| H | 时区 | 直接存；空则用 regions 补 |
| I | 一周内消耗情况 | `consumption` 双向同步 |
| J | 备注 | `remark` |

「回收户清单」12 列：时间|账户ID|渠道|运营|国家|时区|有无消耗|回收原因|是否提交|清零金额|备注|是否二次提交。系统写入前 7 列（时间/账户ID/渠道/运营/国家/时区/回收原因），其余留空。

- [ ] **Step 1: 写失败的回收原因 + 同步 dry_run 测试**

```python
def test_recycle_reason_crud(client, tt_headers):
    resp = client.post("/api/tt/recycle-reasons/create", headers=tt_headers, json={"name": "跑量差"})
    assert resp.status_code == 200
    rid = resp.get_json()["id"]
    resp = client.get("/api/tt/recycle-reasons/list", headers=tt_headers)
    assert resp.get_json()["items"][0]["name"] == "跑量差"
    resp = client.put(f"/api/tt/recycle-reasons/{rid}", headers=tt_headers, json={"name": "跑量差改"})
    assert resp.status_code == 200
    resp = client.delete(f"/api/tt/recycle-reasons/{rid}", headers=tt_headers)
    assert resp.status_code == 200


@mock.patch("google_sheets_service.build_service")
@mock.patch("google_sheets_service.read_sheet_values")
def test_sync_from_sheet_dry_run(mock_read, mock_build, client, tt_headers):
    # 构造看板 10 列：A运营 B入库 C是否回收 D账户ID EBC F国家 G渠道 H时区 I消耗 J备注
    mock_build.return_value = object()
    mock_read.return_value = [
        ["ttuser", "2026-09-20", "否", "1234567890123", "BC-A", "US", "渠道X", "+8", "高", "备注1"],
    ]
    db = database.get_db()
    db.execute("INSERT OR REPLACE INTO tags(key,value) VALUES('tt_sheet_id','sheet-1')")
    db.execute("INSERT OR REPLACE INTO tags(key,value) VALUES('tt_sheet_mappings', ?)",
               ('{"my_dashboard": "我的看板", "recharge": "充值表", "recycle": "回收户清单", "accounts": "账户明细"}',))
    db.commit()
    db.close()

    resp = client.post("/api/tt/accounts/sync-from-sheet", headers=tt_headers,
                       json={"dry_run": True})
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["total"] == 1
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd py && python -m pytest tests/test_tt_accounts.py::test_recycle_reason_crud tests/test_tt_accounts.py::test_sync_from_sheet_dry_run -v`
Expected: FAIL — 404。

- [ ] **Step 3: 新增 `append_recycle`**

在 `py/google_sheets_service.py` 的 `append_recharge`（:286）之后追加：

```python
def append_recycle(service, spreadsheet_id: str, sheet_name: str, rows: list) -> dict:
    """将回收记录追加到「回收户清单」sheet。

    sheet_name: 目标 sheet 名
    rows: [{"time": "2026-09-21", "account_id": "...", "agent": "...",
            "operator": "...", "country": "...", "timezone": "+8",
            "reason": "跑量差"}, ...]

    12 列：A时间 B账户ID C渠道 D运营 E国家 F时区 G有无消耗 H回收原因
           I是否提交 J清零金额 K备注 L是否二次提交
    （系统写入前 7 列 A-G，H 起留空）
    """
    effective_name = sheet_name.strip() if sheet_name else "回收户清单"
    ss = service.spreadsheets().get(spreadsheetId=spreadsheet_id).execute()
    target_sheet = None
    for s in ss.get("sheets", []):
        props = s.get("properties", {})
        if props.get("title", "") == effective_name:
            target_sheet = {
                "name": props["title"],
                "gid": props["sheetId"],
                "rowCount": props.get("gridProperties", {}).get("rowCount", 1000),
            }
            break
    if not target_sheet:
        raise GoogleSheetsServiceError(f"表格中未找到「{effective_name}」工作表")

    sheet_name = target_sheet["name"]
    sheet_id_int = target_sheet["gid"]
    sheet_rows = target_sheet["rowCount"]

    range_read = f"'{sheet_name}'!A:L"
    result = service.spreadsheets().values().get(
        spreadsheetId=spreadsheet_id, range=range_read,
    ).execute()
    existing = result.get("values", [])
    last_row = 0
    for i in range(len(existing) - 1, -1, -1):
        row = existing[i]
        if any(row[j] for j in range(min(7, len(row))) if row[j]):
            last_row = i + 1
            break

    new_rows = []
    for r in rows:
        new_rows.append([
            r.get("time", ""),
            r.get("account_id", ""),
            r.get("agent", ""),
            r.get("operator", ""),
            r.get("country", ""),
            r.get("timezone", ""),
            "",  # G 有无消耗（留空）
            r.get("reason", ""),  # H 回收原因
            "",  # I 是否提交
            "",  # J 清零金额
            "",  # K 备注
            "",  # L 是否二次提交
        ])

    start = last_row + 1
    end = last_row + len(new_rows)
    if end > sheet_rows:
        service.spreadsheets().batchUpdate(
            spreadsheetId=spreadsheet_id,
            body={"requests": [{
                "appendDimension": {
                    "sheetId": sheet_id_int,
                    "dimension": "ROWS",
                    "length": end - sheet_rows
                }
            }]}
        ).execute()

    service.spreadsheets().values().update(
        spreadsheetId=spreadsheet_id,
        range=f"'{sheet_name}'!A{start}:L{end}",
        valueInputOption="USER_ENTERED",
        body={"values": new_rows},
    ).execute()

    log.info("回收记录已追加到 Google Sheets: %d 行", len(new_rows))
    return {"appended": len(new_rows)}
```

- [ ] **Step 4: 实现回收原因 CRUD**

在 `tt_accounts_routes.py` 末尾追加：

```python
# ==================== 回收原因 ====================

@tt_accounts_bp.route('/api/tt/recycle-reasons/list', methods=['GET'])
@jwt_required()
@tt_required
def recycle_reasons_list():
    db = get_db()
    uid = get_uid()
    role = _get_role(db, uid)
    if role in ('developer', 'admin'):
        rows = db.execute("SELECT id, name FROM tt_recycle_reasons ORDER BY id").fetchall()
    else:
        rows = db.execute("SELECT id, name FROM tt_recycle_reasons WHERE owner_id=? ORDER BY id",
                          (uid,)).fetchall()
    return ok({"items": [dict(r) for r in rows]})


@tt_accounts_bp.route('/api/tt/recycle-reasons/create', methods=['POST'])
@jwt_required()
@tt_required
def recycle_reason_create():
    db = get_db()
    uid = get_uid()
    name = (parse_body().get("name") or "").strip()
    if not name:
        return err("名称不能为空")
    existing = db.execute("SELECT id FROM tt_recycle_reasons WHERE name=? AND owner_id=?",
                          (name, uid)).fetchone()
    if existing:
        return err(f"回收原因「{name}」已存在", 409)
    db.execute("INSERT INTO tt_recycle_reasons(name, owner_id) VALUES(?,?)", (name, uid))
    db.commit()
    return ok({"id": db.execute("SELECT last_insert_rowid()").fetchone()[0]})


@tt_accounts_bp.route('/api/tt/recycle-reasons/<int:rid>', methods=['PUT'])
@jwt_required()
@tt_required
def recycle_reason_rename(rid):
    db = get_db()
    uid = get_uid()
    role = _get_role(db, uid)
    name = (parse_body().get("name") or "").strip()
    if not name:
        return err("名称不能为空")
    row = db.execute("SELECT owner_id FROM tt_recycle_reasons WHERE id=?", (rid,)).fetchone()
    if not row:
        return err("回收原因不存在", 404)
    if role not in ('developer', 'admin') and row["owner_id"] != uid:
        return err("无权限", 403)
    db.execute("UPDATE tt_recycle_reasons SET name=? WHERE id=?", (name, rid))
    db.commit()
    return ok()


@tt_accounts_bp.route('/api/tt/recycle-reasons/<int:rid>', methods=['DELETE'])
@jwt_required()
@tt_required
def recycle_reason_delete(rid):
    db = get_db()
    uid = get_uid()
    role = _get_role(db, uid)
    row = db.execute("SELECT owner_id FROM tt_recycle_reasons WHERE id=?", (rid,)).fetchone()
    if not row:
        return err("回收原因不存在", 404)
    if role not in ('developer', 'admin') and row["owner_id"] != uid:
        return err("无权限", 403)
    db.execute("DELETE FROM tt_recycle_reasons WHERE id=?", (rid,))
    db.commit()
    return ok()
```

- [ ] **Step 5: 实现同步端点（dry_run + 确认）**

在文件末尾追加（对齐 GG `accounts_sync_from_sheet`(4534) 的 dry_run → confirm 流程，但读 10 列、自动新增 BC/渠道、消耗双向、状态不自动改）：

```python
# ==================== 同步（我的看板） ====================

def _ensure_bc(db, name):
    if not name:
        return None
    row = db.execute("SELECT id FROM tt_bcs WHERE name=? AND deleted_at IS NULL", (name,)).fetchone()
    if row:
        return row["id"]
    db.execute("INSERT INTO tt_bcs(name, bc_id, owner_id) VALUES(?,?,?)",
               (name, name, 1))
    return db.execute("SELECT last_insert_rowid()").fetchone()[0]


def _ensure_agent(db, name):
    if not name:
        return None
    row = db.execute("SELECT id FROM agents WHERE name=? AND platform='tt'", (name,)).fetchone()
    if row:
        return row["id"]
    db.execute("INSERT INTO agents(name, owner_id, platform) VALUES(?,?, 'tt')", (name, 1))
    return db.execute("SELECT last_insert_rowid()").fetchone()[0]


def _region_timezone(db, country):
    """看板时区为空时，用 regions 的时区补。"""
    row = db.execute("SELECT timezone FROM regions WHERE name=? AND platform='tt'", (country,)).fetchone()
    if row:
        return row["timezone"]
    row = db.execute("SELECT timezone FROM regions WHERE platform='tt' ORDER BY id LIMIT 1").fetchone()
    return (row["timezone"] if row else "")


@tt_accounts_bp.route('/api/tt/accounts/sync-from-sheet', methods=['POST'])
@jwt_required()
@tt_required
def sync_from_sheet():
    from main import _GOOGLE_SHEETS_CONFIG
    import google_sheets_service as gs

    db = get_db()
    uid = get_uid()
    data = parse_body()
    dry_run = bool(data.get("dry_run"))
    user = db.execute("SELECT display_name FROM users WHERE id=?", (uid,)).fetchone()
    display_name = (user["display_name"] or "") if user else ""

    sheet_id = _get_tt_sheet_id(db)
    mappings = _get_tt_sheet_mappings(db)
    dashboard = (mappings.get("my_dashboard") or "").strip() or "我的看板"
    if not sheet_id:
        return err("未配置 Google 表格")

    service = gs.build_service(_GOOGLE_SHEETS_CONFIG["credentials_path"])
    rows = gs.read_sheet_values(service, sheet_id, dashboard, "A:J")
    rows = [r for r in rows if len(r) > 3 and (r[3] or "").strip()]  # D 列账户ID非空

    # 门禁：A 列运营匹配当前用户
    if rows and any((r[0] or "").strip() != display_name for r in rows):
        return err("看板「运营」列与当前账号不匹配，仅可同步自己的账户")

    created, updated, conflicts = [], [], []
    for r in rows:
        operator = (r[0] or "").strip()
        acquired_date = (r[1] or "").strip()
        # r[2] 是否回收 — 仅读取，不触发状态变更
        advertiser_id = (r[3] or "").strip()
        bc_name = (r[4] or "").strip()
        country = (r[5] or "").strip()
        agent_name = (r[6] or "").strip()
        timezone = (r[7] or "").strip() or _region_timezone(db, country)
        consumption = (r[8] or "").strip()
        remark = (r[9] or "").strip()

        if not advertiser_id.isdigit():
            continue
        bc_id = _ensure_bc(db, bc_name) if not dry_run else None
        agent_id = _ensure_agent(db, agent_name) if not dry_run else None

        existing = db.execute("SELECT * FROM tt_accounts WHERE advertiser_id=?", (advertiser_id,)).fetchone()
        if not existing:
            if dry_run:
                created.append({"advertiser_id": advertiser_id, "bc": bc_name,
                                "country": country, "agent": agent_name,
                                "timezone": timezone, "consumption": consumption})
            else:
                db.execute(
                    "INSERT INTO tt_accounts(name, advertiser_id, bc_id, country, agent_id, timezone, "
                    "consumption, acquired_date, remark, owner_id) VALUES(?,?,?,?,?,?,?,?,?,?)",
                    (advertiser_id, advertiser_id, bc_id, country, agent_id, timezone,
                     consumption, acquired_date or None, remark, uid))
                db.commit()
                new_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]
                _record_bc_change(db, new_id, bc_id, uid, "create")
                db.commit()
                created.append({"advertiser_id": advertiser_id})
            continue

        # 消耗情况双向同步：Sheet 与系统不一致 → 冲突列表
        if consumption and consumption != (existing["consumption"] or ""):
            conflicts.append({
                "advertiser_id": advertiser_id,
                "sheet_value": consumption,
                "system_value": existing["consumption"] or "",
            })
        else:
            updated.append({"advertiser_id": advertiser_id})

    if dry_run:
        db.commit()  # 确保 _ensure_* 的副作用？dry_run 下不新增，无需 commit
        return ok({"dry_run": True, "total": len(rows), "created": created,
                   "updated": updated, "conflicts": conflicts})

    # 确认模式：处理消耗冲突 — 客户端传入 resolutions: [{advertiser_id, value}]
    resolutions = data.get("resolutions") or {}
    for adv_id, value in resolutions.items():
        db.execute("UPDATE tt_accounts SET consumption=? WHERE advertiser_id=?",
                   (value, adv_id))
    db.commit()
    return ok({"created": len(created), "updated": len(updated), "conflicts": conflicts})
```

> 注意：`dry_run` 分支中 `_ensure_bc`/`_ensure_agent` 传入 `None`（`not dry_run` 为 False），不会新增。但函数内 `db.execute("INSERT ...")` 在 dry_run 下被跳过；实际 dry_run 下 `bc_id`/`agent_id` 恒为 None，仅用于返回 diff，不落库。

- [ ] **Step 6: 状态改「封禁/死亡」触发回收清单写入**

在 Task 2 的 `update_account`（PUT）与 `batch_update_accounts` 中，**在 `db.commit()` 之前**追加回收清单写入。抽取公共 helper：

```python
def _maybe_write_recycle(db, uid, advertiser_id, agent_name, country, timezone, reason, sheet_id, sheet_name):
    """状态改为封禁/死亡时，后台异步写回收户清单。失败不阻塞状态变更。"""
    from main import _GOOGLE_SHEETS_CONFIG, _sync_sheets_background

    user = db.execute("SELECT display_name FROM users WHERE id=?", (uid,)).fetchone()
    operator = (user["display_name"] or "") if user else ""
    rows = [{
        "time": __import__("datetime").datetime.now().strftime("%Y-%m-%d"),
        "account_id": advertiser_id,
        "agent": agent_name,
        "operator": operator,
        "country": country,
        "timezone": timezone,
        "reason": reason,
    }]

    def _do_sync():
        import google_sheets_service as gs
        service = gs.build_service(_GOOGLE_SHEETS_CONFIG["credentials_path"])
        gs.append_recycle(service, sheet_id, sheet_name, rows)

    _sync_sheets_background(_do_sync, lambda s, e: None)


def _trigger_recycle_if_dead(db, uid, advertiser_id, status_id, reason):
    """status 为「封禁」或「死亡」时，异步写回收户清单。"""
    st = db.execute("SELECT name FROM account_statuses WHERE id=?", (status_id,)).fetchone()
    if not st or st["name"] not in ("封禁", "死亡"):
        return
    sheet_id = _get_tt_sheet_id(db)
    mappings = _get_tt_sheet_mappings(db)
    sheet_name = (mappings.get("recycle") or "").strip() or "回收户清单"
    if not sheet_id:
        return
    # 自动新增回收原因
    if reason:
        existing = db.execute("SELECT id FROM tt_recycle_reasons WHERE name=?", (reason,)).fetchone()
        if not existing:
            db.execute("INSERT INTO tt_recycle_reasons(name, owner_id) VALUES(?,?)", (reason, uid))
    ac = db.execute("SELECT a.country, a.timezone, ag.name AS agent_name FROM tt_accounts a "
                    "LEFT JOIN agents ag ON a.agent_id = ag.id WHERE a.advertiser_id=?",
                    (advertiser_id,)).fetchone()
    agent_name = ac["agent_name"] if ac else ""
    country = ac["country"] if ac else ""
    timezone = ac["timezone"] if ac else ""
    _maybe_write_recycle(db, uid, advertiser_id, agent_name, country, timezone, reason, sheet_id, sheet_name)
```

然后在 `update_account` 的状态处理分支（`if "status" in data or "status_id" in data:` 内，设置 `status_id` 后）追加：

```python
            _trigger_recycle_if_dead(db, uid, row["advertiser_id"], status_id, (data.get("recycle_reason") or "").strip())
```

并在 `batch_update_accounts` 的 `field == "status_id"` 分支（设置 status 后）追加：

```python
            _trigger_recycle_if_dead(db, uid, r["advertiser_id"], value, (data.get("recycle_reason") or "").strip())
```

> 注意：`batch_update_accounts` 中 `r` 需要 `advertiser_id` 字段——把该函数里的 `SELECT owner_id, bc_id` 改为 `SELECT owner_id, bc_id, advertiser_id`。

- [ ] **Step 7: 运行测试确认通过 + 回归**

Run: `cd py && python -m pytest tests/test_tt_accounts.py tests/test_tt_routes.py -v`
Expected: PASS。

- [ ] **Step 8: Commit**

```bash
git add py/routes/tt_accounts_routes.py py/google_sheets_service.py py/tests/test_tt_accounts.py
git commit -m "feat: TT 同步 + 回收原因 + 状态改封禁/死亡写回收清单"
```

---

### Task 5: `agents` 端点 platform 隔离支持

**Files:**
- Modify: `py/main.py`（`agents_list`(5625)、`agents_create`(5639)、`agents_rename`(5662)、`agents_delete`(5698)）
- Test: `py/tests/test_tt_accounts.py`（追加）

**Interfaces:**
- Consumes: `_get_effective_platform()`（main.py:5731）、Task 1 的 `agents.platform` 列
- Produces: `/api/agents/*` 支持 `?platform=tt` 隔离，供 TT 设置页配置代理。GG 默认行为不变（`platform='gg'` 时仍按 owner 隔离）。

**改造方式（纯增量，不改 GG 默认逻辑）**：每个 agents 端点读取 `platform = request.args.get("platform")`。当 `platform == 'tt'` 时，查询/插入/删除按 `platform='tt'` 过滤（TT 代理平台级共享）；否则走原 owner 隔离逻辑。

- [ ] **Step 1: 写失败的平台隔离测试**

```python
def test_agents_platform_isolation(client, auth_headers, tt_headers):
    # TT 平台创建代理
    resp = client.post("/api/agents/create", headers=tt_headers,
                       json={"name": "TT代理A"}, query_string={"platform": "tt"})
    assert resp.status_code == 200
    # TT 列表（platform=tt）能看到
    resp = client.get("/api/agents/list?platform=tt", headers=tt_headers)
    names = [a["name"] for a in resp.get_json()["agents"]]
    assert "TT代理A" in names
    # GG 列表（默认）看不到 TT 代理
    resp = client.get("/api/agents/list", headers=auth_headers)
    names = [a["name"] for a in resp.get_json()["agents"]]
    assert "TT代理A" not in names
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd py && python -m pytest tests/test_tt_accounts.py::test_agents_platform_isolation -v`
Expected: FAIL — TT 代理出现在 GG 列表（或 platform 参数被忽略）。

- [ ] **Step 3: 改造 agents 端点**

`agents_list` 改造：

```python
@app.route("/api/agents/list", methods=["GET"])
@jwt_required()
def agents_list():
    """返回代理名选项列表。platform=tt 时按平台隔离，否则按 owner 隔离。"""
    user_id = int(get_jwt_identity())
    platform = request.args.get("platform", "")
    db = _yt_db()
    if platform == "tt":
        rows = db.execute(
            "SELECT id, name FROM agents WHERE platform='tt' ORDER BY id"
        ).fetchall()
    else:
        rows = db.execute(
            "SELECT id, name FROM agents WHERE owner_id=? AND platform='gg' ORDER BY id",
            (user_id,)
        ).fetchall()
    db.close()
    return jsonify({"success": True, "agents": [dict(r) for r in rows]})
```

`agents_create` 改造（在 `name` 校验后、`existing` 检查前插入 platform 分支）：

```python
    platform = request.args.get("platform", "")
    db = _yt_db()
    if platform == "tt":
        existing = db.execute(
            "SELECT id FROM agents WHERE name=? AND platform='tt'", (name,)
        ).fetchone()
        if existing:
            db.close()
            return jsonify({"success": False, "error": f"代理「{name}」已存在"}), 409
        db.execute("INSERT INTO agents(name, owner_id, platform) VALUES(?,?, 'tt')",
                   (name, user_id))
        db.commit()
        new_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]
        db.close()
        return jsonify({"success": True, "id": new_id})
    # ... 原 owner 隔离逻辑不变 ...
```

`agents_rename` / `agents_delete` 改造：在 `is_dev` 检查之后，插入 `platform == 'tt'` 分支（按 `platform='tt'` 查 row，无 owner 限制），否则走原逻辑。

- [ ] **Step 4: 运行测试确认通过 + 回归**

Run: `cd py && python -m pytest tests/test_tt_accounts.py tests/test_tt_routes.py -v`
Expected: PASS。

- [ ] **Step 5: Commit**

```bash
git add py/main.py py/tests/test_tt_accounts.py
git commit -m "feat: agents 端点补 platform=tt 隔离支持"
```

---

### Task 6: 前端 API 模块 + 路由 + 导航

**Files:**
- Modify: `frontend/src/api/tt.js`
- Modify: `frontend/src/router/index.js`
- Modify: `frontend/src/components/AppSidebar.vue`

**Interfaces:**
- Consumes: Task 2-5 的后端端点
- Produces: `ttAccountsApi`、`ttRechargeApi`、`ttRecycleReasonApi`（供 Task 7-9 组件调用）；路由 `/tt/accounts`；侧边栏「👤 广告账户」。

- [ ] **Step 1: 扩展 `api/tt.js`**

在文件末尾追加：

```js
/** TT 广告账户 */
export const ttAccountsApi = {
  list:   (params) => client.get('/tt/accounts/list', { params }),
  lookup: (advertiserId) => client.get('/tt/accounts/lookup', { params: { advertiser_id: advertiserId } }),
  batchLookup: (accountIds) => client.post('/tt/accounts/batch-lookup', { account_ids: accountIds }),
  create: (body) => client.post('/tt/accounts/create', body),
  batchCreate: (body) => client.post('/tt/accounts/batch-create', body),
  update: (id, body) => client.put(`/tt/accounts/${id}`, body),
  reassign: (id, body) => client.put(`/tt/accounts/${id}/reassign`, body || {}),
  delete: (id) => client.delete(`/tt/accounts/${id}`),
  batchDelete: (ids) => client.post('/tt/accounts/batch-delete', { ids }),
  batchUpdate: (body) => client.post('/tt/accounts/batch-update', body),
  restore: (id) => client.post(`/tt/accounts/${id}/restore`),
  permanentDelete: (id) => client.delete(`/tt/accounts/${id}/permanent`),
  listDeleted: () => client.get('/tt/accounts/deleted'),
  bcHistory: (id) => client.get(`/tt/accounts/${id}/bc-history`),
  deleteBcHistory: (id, hid) => client.delete(`/tt/accounts/${id}/bc-history/${hid}`),
  syncFromSheet: (body) => client.post('/tt/accounts/sync-from-sheet', body),
}

/** TT 充值 */
export const ttRechargeApi = {
  records: (aid) => client.get(`/tt/accounts/${aid}/recharge-records`),
  submit: (body) => client.post('/tt/recharge/submit', body),
  batchSubmit: (body) => client.post('/tt/recharge/batch-submit', body),
  update: (id, body) => client.put(`/tt/recharge/${id}`, body),
  delete: (id) => client.delete(`/tt/recharge/${id}`),
  retrySheets: (id) => client.post(`/tt/recharge/${id}/retry-sheets`),
}

/** TT 回收原因 */
export const ttRecycleReasonApi = {
  list: () => client.get('/tt/recycle-reasons/list'),
  create: (name) => client.post('/tt/recycle-reasons/create', { name }),
  rename: (id, name) => client.put(`/tt/recycle-reasons/${id}`, { name }),
  delete: (id) => client.delete(`/tt/recycle-reasons/${id}`),
}
```

- [ ] **Step 2: 注册路由**

在 `router/index.js` 的 TT 路由区（`/tt/bcs` 之后）追加：

```js
  {
    path: '/tt/accounts',
    component: () => import('../views/tt/TtAccountPanel.vue'),
    meta: { platform: 'tt', title: 'TT广告账户' }
  },
```

（**不加 `admin: true`**——所有 TT 用户可访问，管理员额外有「投手」下拉。）

- [ ] **Step 3: 侧边栏加导航**

在 `AppSidebar.vue` 的 `ttNavItems` 中「产品管理」区 items 追加：

```js
      { icon:'👤',label:'广告账户',path:'/tt/accounts'},
```

（放在 `{ icon:'🏢',label:'BC管理',path:'/tt/bcs'}` 之后。）

- [ ] **Step 4: 验证构建**

Run: `cd frontend && npm run build`
Expected: 构建通过（路由组件 `TtAccountPanel.vue` 此时尚未创建会导致构建失败——**本 Step 依赖 Task 7 创建组件**。故本任务 Step 4 延后到 Task 7 完成后执行。若需独立验证，可先创建空壳组件占位）。

- [ ] **Step 5: Commit**

```bash
git add frontend/src/api/tt.js frontend/src/router/index.js frontend/src/components/AppSidebar.vue
git commit -m "feat: TT 广告账户前端 API + 路由 + 导航"
```

---

### Task 7: 主页面 `TtAccountPanel.vue` + 新增/编辑/详情/已删除弹窗

**Files:**
- Create: `frontend/src/views/tt/TtAccountPanel.vue`
- Create: `frontend/src/components/tt/TtAccountModal.vue`
- Create: `frontend/src/components/tt/TtAccountDetailModal.vue`
- Create: `frontend/src/components/tt/TtAccountDeletedModal.vue`

**Interfaces:**
- Consumes: `ttAccountsApi`、`ttApi.bcOptions()`、`/api/agents/list?platform=tt`、`/api/statuses/list?platform=tt`、`/api/tt/users`（投手下拉）
- Produces: TT 广告账户主页面 + 基础弹窗，供 Task 8 其余弹窗挂载。

**参考 GG 组件**（`frontend/src/views/AdsAccountPanel.vue`、`frontend/src/components/AccountModal.vue`、`AccountDetailModal.vue`、`AccountDeletedModal.vue`）。**逐字段替换**：`account_id`→`advertiser_id`、`mcc`→`bc`（数据源 `ttApi.bcOptions()`）、`mccRowClass`/`mccGroupIndex`→`bcRowClass`/`bcGroupIndex`、`accountsApi`→`ttAccountsApi`。

**关键差异（TikTok 特有）**：
1. 表格新增「消耗情况」列（可内联编辑，调 `ttAccountsApi.update(id, { consumption })`）。
2. 表格新增「国家」列。
3. 状态列改「封禁/死亡」时弹 `TtRecycleReasonModal`（Task 8）收集回收原因，随 update 传 `recycle_reason`。
4. 管理员专属「投手」下拉：`v-if="authStore.isAdmin || authStore.isDeveloper"`，数据源 `/api/tt/users`（`ttApi.listTtUsers()`），切换时传 `owner_id` 到 list。
5. 分页 `pageSizes` 为 `[50, 100, 200]`，默认 50。
6. BC 分组着色：`bcRowClass` 返回 `row.bc_id` 分组后的 `bcGroupIndex % 2` 奇偶交替 class（复用 GG `mccRowClass` 逻辑，仅字段名换）。

- [ ] **Step 1: 写主页面骨架**

`TtAccountPanel.vue` 结构（对齐 GG，替换字段名）：
- 工具栏：搜索框（name/advertiser_id）、BC 下拉、代理下拉、时区下拉、状态筛选、[新增] [批量导入] [批量查户] [批量充值] [同步] [回收站] 按钮
- 状态按钮行：各状态按钮 + `status_counts` 计数（点击筛选）
- 表格：多选 + 内联编辑（名称/BC/时区/代理/状态/消耗/国家）+ BC 分组着色 + 详情/充值/删除按钮
- 分页：`[50, 100, 200]`

组件逻辑要点：
```js
const authStore = useAuthStore()
const isAdmin = computed(() => authStore.isAdmin || authStore.isDeveloper)
const ttUsers = ref([])  // 投手下拉
const ownerId = ref('')  // 管理员选中的投手 owner_id

async function load() {
  const params = { page: page.value, size: size.value, search, bc_id, agent_id, status_id, timezone }
  if (isAdmin.value && ownerId.value) params.owner_id = ownerId.value
  const res = await ttAccountsApi.list(params)
  items.value = res.items; total.value = res.total; statusCounts.value = res.status_counts
}
```

内联编辑、批量删除、批量改状态/BC、软删除/恢复/永久删除均对齐 GG 组件（`accountsApi`→`ttAccountsApi`，字段替换）。

- [ ] **Step 2: 写新增/编辑弹窗 `TtAccountModal.vue`**

对齐 `AccountModal.vue`，字段替换：`account_id`→`advertiser_id`（纯数字校验）、`mcc`→`bc`（`ttApi.bcOptions()`）、新增「国家」「消耗情况」输入；代理/状态下拉数据源 `/api/agents/list?platform=tt`、`/api/statuses/list?platform=tt`。

- [ ] **Step 3: 写详情弹窗 `TtAccountDetailModal.vue`**

对齐 `AccountDetailModal.vue`：充值记录（`ttRechargeApi.records(id)`）+ BC 历史（`ttAccountsApi.bcHistory(id)`，字段 `old_bc/new_bc/change_type/changed_by/created_at`）。

- [ ] **Step 4: 写已删除弹窗 `TtAccountDeletedModal.vue`**

对齐 `AccountDeletedModal.vue`：列表（`ttAccountsApi.listDeleted()`）、恢复（`restore`）、永久删除（`permanentDelete`）。

- [ ] **Step 5: 验证构建**

Run: `cd frontend && npm run build`
Expected: 构建通过（此时 Task 6 的路由引用已满足）。

- [ ] **Step 6: Commit**

```bash
git add frontend/src/views/tt/TtAccountPanel.vue frontend/src/components/tt/TtAccountModal.vue frontend/src/components/tt/TtAccountDetailModal.vue frontend/src/components/tt/TtAccountDeletedModal.vue
git commit -m "feat: TT 广告账户主页面 + 新增/编辑/详情/回收站弹窗"
```

---

### Task 8: 批量导入 / 查户 / 充值 / 同步 / 回收原因弹窗

**Files:**
- Create: `frontend/src/components/tt/TtAccountBatchImportModal.vue`
- Create: `frontend/src/components/tt/TtAccountBatchLookupModal.vue`
- Create: `frontend/src/components/tt/TtRechargeModal.vue`
- Create: `frontend/src/components/tt/TtRechargeBatchModal.vue`
- Create: `frontend/src/components/tt/TtAccountSyncModal.vue`
- Create: `frontend/src/components/tt/TtRecycleReasonModal.vue`

**Interfaces:**
- Consumes: `ttAccountsApi`、`ttRechargeApi`、`ttRecycleReasonApi`
- Produces: 主页面工具栏挂载的剩余弹窗。

**参考 GG 组件**：`AccountBatchImportModal.vue`、`AccountBatchLookupModal.vue`、`RechargeModal.vue`、`RechargeBatchModal.vue`、`AccountSyncModal.vue`。字段替换同 Task 7。

**关键差异**：
1. `TtAccountBatchLookupModal.vue`：ID 解析改为**十多位纯数字**（去空格、按换行/逗号拆分），结果分 `found`/`not_found`。
2. `TtAccountSyncModal.vue`：**新增「消耗情况冲突」弹窗**——当 `syncFromSheet({dry_run:true})` 返回 `conflicts` 非空时，逐条展示 Sheet 值 vs 系统值，用户选「以 Sheet 为准」或「以系统为准」，收集后 `syncFromSheet({dry_run:false, resolutions})` 确认。
3. `TtRecycleReasonModal.vue`（**GG 无对应**）：状态改「封禁/死亡」时弹出，下拉可选（`ttRecycleReasonApi.list()`）+ 手动输入 + 自动新增（`ttRecycleReasonApi.create()`），确定后随 `ttAccountsApi.update(id, { status_id, recycle_reason })` 提交。

- [ ] **Step 1: 实现 6 个弹窗**（对齐 GG 对应组件 + 上述差异）

- [ ] **Step 2: 验证构建**

Run: `cd frontend && npm run build`
Expected: 构建通过。

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/tt/
git commit -m "feat: TT 广告账户批量/查户/充值/同步/回收原因弹窗"
```

---

### Task 9: 设置页扩展 — 代理 / 状态 / 回收原因配置

**Files:**
- Modify: `frontend/src/views/tt/TtSettingsPanel.vue`

**Interfaces:**
- Consumes: `/api/agents/list?platform=tt`、`/api/statuses/list?platform=tt`、`ttRecycleReasonApi`、`ttSettingsApi`
- Produces: 设置页「账户设置」tab 新增代理/状态/回收原因配置卡片（仅管理员可见）+ `sheet_mappings` 扩展为 4 个 key。

- [ ] **Step 1: 扩展 `SHEET_MAPPING_META` 与默认 `sheet_mappings`**

```js
const SHEET_MAPPING_META = {
  accounts: { label: '账户明细' },
  recharge: { label: '充值表' },
  my_dashboard: { label: '我的看板' },
  recycle: { label: '回收户清单' },
}
// form 默认值
const form = reactive({
  sheet_id: '',
  sheet_mappings: { accounts: '账户明细', recharge: '充值表', my_dashboard: '我的看板', recycle: '回收户清单' },
})
```

`loadSettings()` 中 `form.sheet_mappings = res.settings?.sheet_mappings || form.sheet_mappings`。

- [ ] **Step 2: 新增代理/状态/回收原因配置卡片**

复用现有「商务人员选项」卡片的 Tag 增删改模式（`salesPersons` 那套 `startTagEdit`/`finishTagEdit`/`addOption`/`handleDelete`），复制为三份：`agents`（`/api/agents/list?platform=tt`）、`statuses`（`/api/statuses/list?platform=tt`）、`recycleReasons`（`ttRecycleReasonApi`）。三者放在「仅管理员」区块内（`v-if="authStore.isAdmin || authStore.isDeveloper"`）。

- [ ] **Step 3: 验证构建**

Run: `cd frontend && npm run build`
Expected: 构建通过。

- [ ] **Step 4: Commit**

```bash
git add frontend/src/views/tt/TtSettingsPanel.vue
git commit -m "feat: TT 设置页新增代理/状态/回收原因配置"
```

---

## Self-Review（计划自检）

**1. Spec 覆盖**：
- ✅ 列表+分页+投手筛选+BC分组 → Task 2（list）+ Task 7（页面）
- ✅ 搜索/筛选/状态按钮计数 → Task 2（list `status_counts`）+ Task 7
- ✅ 新增/编辑/删除/批量删除/批量导入/批量查户 → Task 2 + Task 7/8
- ✅ 批量充值/单充值 → Task 3 + Task 8
- ✅ 同步（看板 10 列 + 消耗双向 + 冲突弹窗）→ Task 4 + Task 8
- ✅ 回收户清单（状态改封禁/死亡写 sheet）→ Task 4（`append_recycle` + `_trigger_recycle_if_dead`）
- ✅ 回收原因 CRUD → Task 4 + Task 9
- ✅ 内联编辑/批量修改/详情 → Task 2 + Task 7
- ✅ 独立代理/状态 platform 隔离 → Task 1 + Task 5
- ✅ 设置页扩展 + sheet_mappings 4 key → Task 9
- ✅ 导航/路由 → Task 6

**2. Placeholder 扫描**：无 TBD/TODO；「参考 GG 端点/组件 + 字段替换」是明确的对齐指令（已给出文件+行号+映射表），非占位。

**3. 类型一致性**：
- 后端 `_resolve_agent_id/_resolve_status_id/_record_bc_change/_get_tt_sheet_id/_get_tt_sheet_mappings` 在 Task 2 定义，Task 3/4 复用，签名一致。
- `_maybe_write_recycle/_trigger_recycle_if_dead/_ensure_bc/_ensure_agent/_region_timezone` 在 Task 4 定义并自洽。
- 前端 `ttAccountsApi`/`ttRechargeApi`/`ttRecycleReasonApi` 在 Task 6 定义，Task 7/8/9 使用，方法名一致。
- 表名 `tt_accounts`/`tt_account_bc_history`/`tt_recharge_records`/`tt_recycle_reasons` 全计划一致。
- `advertiser_id`/`bc_id`/`consumption`/`recycle_reason` 字段名全计划一致。
