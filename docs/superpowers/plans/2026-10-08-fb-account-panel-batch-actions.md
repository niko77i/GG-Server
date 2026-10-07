# FB 账户面板批量能力对齐 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让 FB 账户面板具备与 GG/TT 同档的批量能力 —— 批量查户、批量新增导入、批量删除、回收站。

**Architecture:** 后端在 `py/routes/fb_routes.py` 新增 3 个端点（照 GG `main.py` 的同名端点移植形状，字段换成 FB 的）；回收站的后端**已存在**，只补前端入口。前端在 `FbAccountPanel.vue` 补工具栏按钮与多选列，新建 3 个 FB 弹窗组件。**不改任何 GG/TT 的现有代码。**

**Tech Stack:** Flask Blueprint + SQLite（`PRAGMA foreign_keys=ON`）/ Vue 3 + Element Plus + Pinia / pytest。

**设计依据：** `docs/superpowers/specs/2026-10-08-fb-account-panel-batch-actions-design.md`（与本文冲突时以该 spec 为准）。

## Global Constraints

- **计划里的示例代码与行号是编写时的快照。落笔前必须核对现行代码；不符时以现行代码为准，并在报告里记录偏差。**
- **纯增量**：不改任何 GG / TT 的现有代码。本计划只新增 FB 的端点、组件与测试。
- **归属隔离口径**：非 `CROSS_USER_ROLES` 角色只能操作 `owner_id = 自己` 的行；取 role 用 `fb_routes.py` 既有的 `_get_role(db, uid)`，判断用 `.helpers` 的 `CROSS_USER_ROLES`（文件头已 import）。
- **不照抄 GG lookup 族的越权缺陷**：GG 的 `accounts_batch_lookup`（`main.py` 约 4332 行）**没有 owner 条件**（遗留清单 A8）。FB 版**只搬形状，一律带 owner 过滤**。
- **重复键口径**：撞 `fb_accounts.account_id` 的 UNIQUE 约束 ⇒ 回 **「账户 ID「X」已存在」**，判据用 `fb_routes.py` 既有的 `_is_unique_conflict(e)`（先锁 `sqlite3.IntegrityError` 类型、再要求 `str(e)` 含 `"unique"`）。**不得只判类型** —— FK / NOT NULL 也是 `IntegrityError`，只判类型会把它们误报成「已存在」。
- **主键闸门**：任何随后绑进 sqlite 的 id 必须过 `_valid_pk_int64`（ASCII 十进制数字串且 ≤ `2**63-1`），否则 400。**别让超界值走到绑定处**（会抛 `OverflowError` → 500 + 英文原文）。
- **fb_routes.py 不 import main**（会循环）。需要 GG 的助手就**在本文件内自带一份**。
- 测试文件：`py/tests/test_fb_platform.py`。
- 门禁：`cd py && python -m pytest tests/ -q`（当前基线 **1495 passed / 0 failed**，以实跑为准）。
- **新增接口必须同步更新 `AGENTS.md` 的「API 路由一览 → FB 平台」表**。

---

## File Structure

| 文件 | 职责 | 动作 |
|---|---|---|
| `py/routes/fb_routes.py` | 新增 1 个模块级助手 + 3 个端点 | Modify |
| `py/tests/test_fb_platform.py` | 三个端点的测试（归属隔离 / 跨用户对照 / 边界） | Modify |
| `frontend/src/api/fb.js` | 三个新 API 方法 | Modify |
| `frontend/src/views/fb/FbAccountPanel.vue` | 工具栏按钮 + 多选列 + 弹窗挂载 | Modify |
| `frontend/src/components/fb/FbAccountBatchLookupModal.vue` | 批量查户弹窗 | Create |
| `frontend/src/components/fb/FbAccountBatchImportModal.vue` | 批量导入弹窗 | Create |
| `frontend/src/components/fb/FbAccountDeletedModal.vue` | 回收站弹窗 | Create |
| `AGENTS.md` | API 路由表 + 设计文档索引 | Modify |

---

### Task 1: 主键闸门助手 + `POST /api/fb/accounts/batch-lookup`

**Files:**
- Modify: `py/routes/fb_routes.py`（助手放模块级、紧跟 `_is_unique_conflict` 之后；端点放 `list_accounts` 附近）
- Test: `py/tests/test_fb_platform.py`

**Interfaces:**
- Consumes: `fb_routes.py` 既有的 `ok` / `err` / `get_db` / `get_uid` / `parse_body` / `CROSS_USER_ROLES` / `_get_role(db, uid)`
- Produces:
  - `_valid_pk_int64(raw) -> int | None`（模块级助手，Task 2 复用）
  - `POST /api/fb/accounts/batch-lookup` ⇒ `{"success": true, "found": [...], "not_found": [...]}`
    - `found` 每项：`{"account_id","name","owner_id","owner_name","status","timezone","bm_name"}`

- [ ] **Step 1: 核对现行代码**

Run: `grep -n "_is_unique_conflict\|def list_accounts\|_get_role" py/routes/fb_routes.py | head`
确认：助手位置、`_get_role` 的签名、`list_accounts` 里 owner 过滤的确切写法。**与本文不符时以现行代码为准。**

- [ ] **Step 2: 写失败测试**

```python
class TestFbBatchLookup:
    """POST /api/fb/accounts/batch-lookup —— 批量查户。"""

    def test_batch_lookup_finds_own_account_with_bm_name(self, client, fb_user_headers):
        """自己的账户查得到，且带主 BM 名。"""
        # 夹具：建一个 fb_bms + 一个 fb_accounts（owner=自己）+ 关联主 BM
        # 先读 test_fb_platform.py 里既有的建户夹具，照它的形状准备数据
        resp = client.post("/api/fb/accounts/batch-lookup",
                           json={"account_ids": ["LOOKUP-1"]}, headers=fb_user_headers)
        data = resp.get_json()
        assert data["success"] is True
        assert [f["account_id"] for f in data["found"]] == ["LOOKUP-1"]
        assert data["not_found"] == []
        assert data["found"][0]["bm_name"] == "测试BM"

    def test_batch_lookup_does_not_leak_other_users_account(self, client, fb_user_headers, other_fb_user_headers):
        """**归属隔离**：别人的账户查不到，且落在 not_found 里。"""
        resp = client.post("/api/fb/accounts/batch-lookup",
                           json={"account_ids": ["OTHERS-1"]}, headers=fb_user_headers)
        data = resp.get_json()
        assert data["found"] == []
        assert data["not_found"] == ["OTHERS-1"]

    def test_batch_lookup_cross_user_role_sees_all(self, client, developer_headers, other_fb_user_headers):
        """**对照腿**：跨用户角色能查到别人的（防「一律看不见」的过度收口）。"""
        resp = client.post("/api/fb/accounts/batch-lookup",
                           json={"account_ids": ["OTHERS-1"]}, headers=developer_headers)
        assert [f["account_id"] for f in resp.get_json()["found"]] == ["OTHERS-1"]

    def test_batch_lookup_rejects_empty_and_non_list(self, client, fb_user_headers):
        for body in ({"account_ids": []}, {"account_ids": "x"}, {}):
            resp = client.post("/api/fb/accounts/batch-lookup", json=body, headers=fb_user_headers)
            assert resp.status_code == 400
```

> ⚠️ 夹具名以 `test_fb_platform.py` 现行文件为准 —— 上面用的是**占位名**，落笔前先看既有夹具怎么造两个 FB 用户与 developer。

- [ ] **Step 3: 运行测试确认失败**

Run: `cd py && python -m pytest tests/test_fb_platform.py -q -k BatchLookup`
Expected: FAIL（404 或路由不存在）

- [ ] **Step 4: 实现**

模块级助手（紧跟 `_is_unique_conflict` 之后）：

```python
def _valid_pk_int64(raw):
    """主键/外键候选值的闸门 —— 口径与 GG 的 `main._valid_pk_int64` 完全一致。

    合法 = `str(raw).strip()` 后是纯 ASCII 十进制数字串（无正负号、无小数点 ⇒ 天然 ≥ 0），
    且数值 ≤ 2**63-1（SQLite INTEGER 是 64 位有符号）。非法（含 bool）返回 None。

    为什么必须有：这些值随后原样交给 sqlite3 参数绑定。超上界时 Python 的 int() 能解析，
    但绑定处会抛 OverflowError（内建，非 sqlite3.OverflowError）⇒ 500 + 英文异常原文。
    本文件不 import main（会循环），故自带一份。
    """
    s = str(raw).strip()
    if not (s.isascii() and s.isdigit()):
        return None
    try:
        v = int(s)
    except (ValueError, OverflowError):
        return None
    if v > 2**63 - 1:
        return None
    return v
```

端点（放在 `list_accounts` 之后）：

```python
@fb_bp.route('/api/fb/accounts/batch-lookup', methods=['POST'])
@jwt_required()
@fb_required
def batch_lookup_accounts():
    """批量查询多个资产UID是否已存在（单次 SQL IN 查询）。

    ⚠️ **归属隔离**：GG 的同名端点在 main.py 里没有 owner 条件（越权，见遗留清单 A8），
    本端点**不复制该缺陷** —— 非跨用户角色只查得到自己的行。
    """
    db = get_db()
    data = parse_body()
    account_ids = data.get('account_ids') or []
    if not account_ids or not isinstance(account_ids, list):
        return err('请提供 account_ids 列表', 400)

    clean_ids = [str(a).strip() for a in account_ids if str(a).strip()]
    if not clean_ids:
        return ok({'found': [], 'not_found': []})

    uid = get_uid()
    cross_user = _get_role(db, uid) in CROSS_USER_ROLES
    placeholders = ",".join(["?"] * len(clean_ids))
    where = [f"a.account_id IN ({placeholders})"]
    params = list(clean_ids)
    if not cross_user:
        where.append("a.owner_id = ?")
        params.append(uid)

    rows = db.execute(
        "SELECT a.account_id, a.name, a.owner_id, a.timezone, "
        "       u.display_name AS owner_display, u.username AS owner_username, "
        "       st.name AS status_name, b.name AS bm_name "
        "FROM fb_accounts a "
        "LEFT JOIN users u ON a.owner_id = u.id "
        "LEFT JOIN account_statuses st ON a.status_id = st.id "
        "LEFT JOIN fb_account_bm ab ON ab.account_id = a.id AND ab.is_primary = 1 "
        "LEFT JOIN fb_bms b ON b.id = ab.bm_id "
        "WHERE " + " AND ".join(where) + " AND a.deleted_at IS NULL",
        params
    ).fetchall()

    found = [{
        'account_id': r['account_id'],
        'name': r['name'],
        'owner_id': r['owner_id'],
        'owner_name': r['owner_display'] or r['owner_username'] or '',
        'status': r['status_name'] or '',
        'timezone': r['timezone'] or '',
        'bm_name': r['bm_name'] or '',
    } for r in rows]
    found_ids = {f['account_id'] for f in found}
    return ok({'found': found, 'not_found': [a for a in clean_ids if a not in found_ids]})
```

> ⚠️ **落笔前核对**：`fb_account_bm` 的主 BM 标记列名（是否 `is_primary`）、`fb_accounts.deleted_at` 是否存在。不符时以现行代码为准。

- [ ] **Step 5: 运行测试确认通过**

Run: `cd py && python -m pytest tests/test_fb_platform.py -q -k BatchLookup`
Expected: PASS

- [ ] **Step 6: 提交**

```bash
git add py/routes/fb_routes.py py/tests/test_fb_platform.py
git commit -m "feat(fb): 批量查户端点 + 主键 int64 闸门助手"
```

---

### Task 2: `POST /api/fb/accounts/batch-delete`（软删）

**Files:**
- Modify: `py/routes/fb_routes.py`
- Test: `py/tests/test_fb_platform.py`

**Interfaces:**
- Consumes: Task 1 的 `_valid_pk_int64`；`CROSS_USER_ROLES` / `_get_role`
- Produces: `POST /api/fb/accounts/batch-delete` ⇒ `{"success": true, "deleted": N, "not_found": [ids]}`

- [ ] **Step 1: 写失败测试**

```python
class TestFbBatchDelete:
    def test_deletes_only_own_and_reports_others_as_not_found(self, client, fb_user_headers, other_fb_user_headers):
        """自己的删掉；别人的计入 not_found 且**未被改动**。"""
        # 夹具：自己一个账户 pk_own、别人一个账户 pk_other
        resp = client.post("/api/fb/accounts/batch-delete",
                           json={"ids": [pk_own, pk_other]}, headers=fb_user_headers)
        data = resp.get_json()
        assert data["deleted"] == 1
        assert data["not_found"] == [pk_other]
        # 别人的账户 deleted_at 仍为 NULL（没被越权软删）

    def test_empty_ids_is_400(self, client, fb_user_headers):
        assert client.post("/api/fb/accounts/batch-delete", json={"ids": []},
                           headers=fb_user_headers).status_code == 400

    def test_oversized_or_non_ascii_id_is_400_not_500(self, client, fb_user_headers):
        for bad in (10 ** 30, "９", "abc", True):
            resp = client.post("/api/fb/accounts/batch-delete", json={"ids": [bad]},
                               headers=fb_user_headers)
            assert resp.status_code == 400, bad
```

- [ ] **Step 2: 运行确认失败** — `cd py && python -m pytest tests/test_fb_platform.py -q -k BatchDelete` ⇒ FAIL

- [ ] **Step 3: 实现**

```python
@fb_bp.route('/api/fb/accounts/batch-delete', methods=['POST'])
@jwt_required()
@fb_required
def batch_delete_accounts():
    """批量软删账户。非跨用户角色只能删自己的；删不到的 id 进 not_found。"""
    db = get_db()
    data = parse_body()
    ids = data.get('ids') or []
    if not ids or not isinstance(ids, list):
        return err('未选择账户', 400)
    # ids 元素闸门：元素随后原样绑进 sqlite（IN 与逐条 UPDATE），
    # 非 ASCII 数字串 / 超 int64 会抛 OverflowError ⇒ 提前 400 挡下。
    for _i in ids:
        if _valid_pk_int64(_i) is None:
            return err('ids 不合法', 400)

    uid = get_uid()
    cross_user = _get_role(db, uid) in CROSS_USER_ROLES
    owner_clause = "" if cross_user else " AND owner_id = ?"
    deleted, not_found = 0, []
    for aid in ids:
        params = (_valid_pk_int64(aid),) if cross_user else (_valid_pk_int64(aid), uid)
        cur = db.execute(
            "UPDATE fb_accounts SET deleted_at = datetime('now','localtime'), "
            "       updated_at = datetime('now','localtime') "
            f"WHERE id = ?{owner_clause} AND deleted_at IS NULL", params)
        if cur.rowcount:
            deleted += 1
        else:
            not_found.append(_valid_pk_int64(aid))
    db.commit()
    return ok({'deleted': deleted, 'not_found': not_found})
```

> 用**逐条 UPDATE + rowcount**（而不是一条 `IN`）—— `IN` 无法区分「不存在」与「无权」，而本端点要求把两者都归入 `not_found`。

- [ ] **Step 4: 运行确认通过** — 同 Step 2 命令 ⇒ PASS
- [ ] **Step 5: 提交**

```bash
git add py/routes/fb_routes.py py/tests/test_fb_platform.py
git commit -m "feat(fb): 批量软删端点（归属隔离 + int64 闸门）"
```

---

### Task 3: `POST /api/fb/accounts/batch-create`

**Files:**
- Modify: `py/routes/fb_routes.py`
- Test: `py/tests/test_fb_platform.py`

**Interfaces:**
- Consumes: `_valid_pk_int64`；`_is_unique_conflict`；`_set_primary_bm(db, acc_pk, bm_id)`（本文件既有）；`_display_name(db, uid)`（本文件既有）；`hd.writeback_rows(uid, "fb", [account_id])`
- Produces: `POST /api/fb/accounts/batch-create` ⇒ `{"success": true, "created": N, "created_ids": [...], "skipped": [...], "errors": [{"account_id":…, "error":…}]}`

- [ ] **Step 1: 写失败测试**

```python
class TestFbBatchCreate:
    def test_creates_rows_with_common_defaults(self, client, fb_user_headers):
        resp = client.post("/api/fb/accounts/batch-create", json={
            "account_ids": ["BC-1", "BC-2"], "name_prefix": "前缀", "timezone": "UTC+8",
        }, headers=fb_user_headers)
        data = resp.get_json()
        assert data["created"] == 2
        assert sorted(data["created_ids"]) == ["BC-1", "BC-2"]
        # 落库校验：name = "前缀 BC-1"，owner 是调用者，owner 不是提交人以外的人

    def test_overrides_win_over_common(self, client, fb_user_headers):
        """overrides 逐行覆盖共用默认值。"""
        # 传 timezone 共用 "UTC+8"、overrides 里 BC-3 给 "UTC+9"
        # 断言 BC-3 落库的 timezone 是 UTC+9、BC-4 是 UTC+8

    def test_duplicate_account_id_reports_exists_not_generic(self, client, fb_user_headers):
        """撞 UNIQUE ⇒ 「已存在」，不是「操作失败」。"""
        # 先建 BC-DUP，再批量建同 ID
        assert [e["account_id"] for e in data["errors"]] == ["BC-DUP"]
        assert "已存在" in data["errors"][0]["error"]

    def test_blank_and_non_list_are_400(self, client, fb_user_headers):
        for body in ({"account_ids": []}, {"account_ids": "x"}, {}):
            assert client.post("/api/fb/accounts/batch-create", json=body,
                               headers=fb_user_headers).status_code == 400

    def test_partial_failure_does_not_abort_batch(self, client, fb_user_headers):
        """一条失败不影响其余（逐行独立 try/except）。"""
        # ["BC-OK","BC-DUP","BC-OK2"] ⇒ created==2 且 errors 只有 BC-DUP
```

- [ ] **Step 2: 运行确认失败**
- [ ] **Step 3: 实现**

```python
@fb_bp.route('/api/fb/accounts/batch-create', methods=['POST'])
@jwt_required()
@fb_required
def batch_create_accounts():
    """批量创建 FB 账户：共用默认值 + 逐账户 overrides。

    字段形状照本文件的 `create_account`（FB 没有 MCC/代理，且 status_id 由前端直接给数值）。
    `operator` 是冻结字段（规格 6.1）—— 服务端填创建者名字快照，请求体同名键一律忽略。
    """
    db = get_db()
    data = parse_body()
    account_ids = data.get('account_ids') or []
    if not account_ids or not isinstance(account_ids, list):
        return err('请提供 account_ids 列表', 400)

    common = {
        'name_prefix': (data.get('name_prefix') or '').strip(),
        'timezone': (data.get('timezone') or ''),
        'status_id': _valid_pk_int64(data['status_id']) if data.get('status_id') is not None else None,
        'primary_bm_id': _valid_pk_int64(data['primary_bm_id']) if data.get('primary_bm_id') is not None else None,
        'acquired_date': data.get('acquired_date', ''),
    }
    overrides = data.get('overrides') or {}
    if not isinstance(overrides, dict):
        return err('overrides 必须是对象', 400)

    uid = get_uid()
    operator = _display_name(db, uid)
    created, skipped, errors = [], [], []
    written_ids = []          # 仅用于最后一次性回写看板

    for raw_aid in account_ids:
        aid = str(raw_aid).strip()
        if not aid:
            skipped.append(aid)
            continue
        ov = overrides.get(aid) or {}
        # 名称：overrides.name 直接用作完整名称；否则 name_prefix + ID
        name = (ov.get('name') or '').strip() or \
               ((common['name_prefix'] + ' ' + aid).strip() if common['name_prefix'] else aid)
        timezone = ov['timezone'] if 'timezone' in ov else common['timezone']
        status_id = (_valid_pk_int64(ov['status_id'])
                     if 'status_id' in ov and ov['status_id'] is not None else common['status_id'])
        primary_bm_id = (_valid_pk_int64(ov['primary_bm_id'])
                         if 'primary_bm_id' in ov and ov['primary_bm_id'] is not None
                         else common['primary_bm_id'])
        acquired_date = ov['acquired_date'] if 'acquired_date' in ov else common['acquired_date']

        if not aid.isdigit():
            errors.append({'account_id': aid, 'error': '账户ID必须是纯数字'})
            continue
        try:
            db.execute(
                "INSERT INTO fb_accounts (name, account_id, timezone, status_id, "
                "       acquired_date, owner_id, operator) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (name, aid, timezone, status_id, acquired_date, uid, operator))
            acc_pk = db.execute("SELECT last_insert_rowid()").fetchone()[0]
            if primary_bm_id:
                _set_primary_bm(db, acc_pk, primary_bm_id)
            db.commit()
            created.append(aid)
            written_ids.append(aid)
        except Exception as e:
            log.exception("FB 批量建户失败 account_id=%s", aid)
            if _is_unique_conflict(e):
                errors.append({'account_id': aid, 'error': f"账户 ID「{aid}」已存在"})
            else:
                errors.append({'account_id': aid, 'error': _FB_DB_FAILED_MSG})

    if written_ids:
        hd.writeback_rows(uid, "fb", written_ids)

    return ok({'created': len(created), 'created_ids': created,
               'skipped': skipped, 'errors': errors})
```

- [ ] **Step 4: 运行确认通过**
- [ ] **Step 5: 提交**

```bash
git add py/routes/fb_routes.py py/tests/test_fb_platform.py
git commit -m "feat(fb): 批量建户端点（共用默认值 + overrides）"
```

---

### Task 4: 前端 API + 工具栏按钮 + 多选列

**Files:**
- Modify: `frontend/src/api/fb.js`、`frontend/src/views/fb/FbAccountPanel.vue`

**Interfaces:**
- Consumes: Task 1–3 的三个端点；FB 回收站三个**已存在**的端点
- Produces: `fbApi.batchLookup(body)` / `fbApi.batchCreate(body)` / `fbApi.batchDelete(body)` / `fbApi.listDeleted(params)` / `fbApi.restoreAccount(id)` / `fbApi.permanentDeleteAccount(id)`

- [ ] **Step 1: 补 api**

先 `grep -n "listDeleted\|restoreAccount\|permanentDelete" frontend/src/api/fb.js` —— **已有的直接复用，只补缺的三个批量方法**（形状照同文件既有方法）：

```js
  batchLookup: (body) => client.post('/fb/accounts/batch-lookup', body),
  batchCreate: (body) => client.post('/fb/accounts/batch-create', body),
  batchDelete: (body) => client.post('/fb/accounts/batch-delete', body),
```

- [ ] **Step 2: 工具栏 + 多选列**

`FbAccountPanel.vue` 头部（现有 `<el-button type="primary" @click="openCreate">新增账户</el-button>` 之后）补：

```vue
      <el-button @click="batchImportVisible = true">📥 批量导入</el-button>
      <el-button @click="lookupVisible = true">🔍 批量查户</el-button>
      <el-button @click="deletedVisible = true">🗑 回收站</el-button>
      <el-button v-if="selected.length" @click="batchDelete" style="margin-left:auto;">🗑 批量删除</el-button>
```

表格加多选列（**照 `AdsAccountPanel.vue` 的既有写法**，先读它怎么绑 `selected`）：

```vue
      <el-table-column type="selection" width="46" />
```

并以**同一 `@selection-change` 处理器**维护 `const selected = ref([])`。

批量删除复用既有单删的二次确认口径（`ElMessageBox.confirm`），成功后 `load()` 刷新。

- [ ] **Step 3: 挂载三个弹窗**（下一个 Task 才写组件，本 Step 先建空壳占位会打红构建 —— **故本 Task 只做按钮与多选，弹窗挂载放到各弹窗 Task 里**）
- [ ] **Step 4: 构建验证** — `cd frontend && npm run build` ⇒ 通过
- [ ] **Step 5: 提交**

```bash
git add frontend/src/api/fb.js frontend/src/views/fb/FbAccountPanel.vue
git commit -m "feat(fb-ui): 账户面板补批量按钮与多选列"
```

---

### Task 5: 批量查户弹窗

**Files:**
- Create: `frontend/src/components/fb/FbAccountBatchLookupModal.vue`
- Modify: `frontend/src/views/fb/FbAccountPanel.vue`（挂载）

**Interfaces:**
- Consumes: `fbApi.batchLookup`
- Produces: `<FbAccountBatchLookupModal v-model:visible="lookupVisible" />`

- [ ] **Step 1: 读样板** — 通读 `frontend/src/components/AccountBatchLookupModal.vue`（GG 版），确认：粘贴框、`account_ids` 的切分规则、结果表格列、`found`/`not_found` 的呈现。**照它写，只改字段**：`mcc_name/mcc_code` 两列 → 换成 **`bm_name`「主 BM」一列**。
- [ ] **Step 2: 建组件**（同 Step 1 的结构，`fbApi.batchLookup`）
- [ ] **Step 3: 挂载到 `FbAccountPanel.vue`**（import + `v-model:visible`）
- [ ] **Step 4: 构建验证** — `cd frontend && npm run build` ⇒ 通过
- [ ] **Step 5: 提交** — `git add frontend/src/components/fb/ frontend/src/views/fb/FbAccountPanel.vue && git commit -m "feat(fb-ui): 批量查户弹窗"`

---

### Task 6: 批量导入弹窗

**Files:**
- Create: `frontend/src/components/fb/FbAccountBatchImportModal.vue`
- Modify: `frontend/src/views/fb/FbAccountPanel.vue`

**Interfaces:**
- Consumes: `fbApi.batchCreate`
- Produces: `<FbAccountBatchImportModal v-model:visible="batchImportVisible" @imported="load" />`

- [ ] **Step 1: 读样板** — 通读 `frontend/src/components/AccountBatchImportModal.vue`（GG 版）与 TT 的 `components/tt/TtAccountBatchImportModal.vue`，确认：共用默认值区 + **逐行可覆盖**的编辑表格、`overrides` 的构造、提交后 `errors` 的呈现。**照它写，字段换成 FB 的**：共用默认值 = 名称前缀 / 时区 / 状态 / 主 BM（**去掉 MCC、代理**）。
- [ ] **Step 2: 建组件**（`fbApi.batchCreate`）
- [ ] **Step 3: 挂载到 `FbAccountPanel.vue`**
- [ ] **Step 4: 构建验证**
- [ ] **Step 5: 提交** — `git commit -m "feat(fb-ui): 批量导入弹窗"`

---

### Task 7: 回收站弹窗

**Files:**
- Create: `frontend/src/components/fb/FbAccountDeletedModal.vue`
- Modify: `frontend/src/views/fb/FbAccountPanel.vue`

**Interfaces:**
- Consumes: `fbApi.listDeleted` / `restoreAccount` / `permanentDeleteAccount`（**已存在的端点**）
- Produces: `<FbAccountDeletedModal v-model:visible="deletedVisible" @changed="load" />`

- [ ] **Step 1: 读样板** — 通读 `frontend/src/components/AccountDeletedModal.vue`（GG 版）：列表、分页、恢复、永久删除（二次确认）、`@changed` 通知父组件刷新。
- [ ] **Step 2: 建组件**（三个 api 均为**已存在**端点，**不要新建后端**）
- [ ] **Step 3: 挂载到 `FbAccountPanel.vue`**
- [ ] **Step 4: 构建验证**
- [ ] **Step 5: 提交** — `git commit -m "feat(fb-ui): 回收站弹窗"`

---

### Task 8: 文档与交付门禁

**Files:**
- Modify: `AGENTS.md`

- [ ] **Step 1: 更新 AGENTS.md 的 FB 路由表**（`### FB 平台（fb_routes.py，49 路由）` 那节）

加上三行，并把标题里的「49 路由」改成实际数（跑 `grep -c "@fb_bp.route" py/routes/fb_routes.py` 取真值）：

```
| POST | /api/fb/accounts/batch-lookup | 批量查户（归属隔离，字段含主 BM 名） |
| POST | /api/fb/accounts/batch-create | 批量建户（共用默认值 + 逐行 overrides） |
| POST | /api/fb/accounts/batch-delete | 批量软删（归属隔离，删不到的进 not_found） |
```

- [ ] **Step 2: 全量测试** — `cd py && python -m pytest tests/ -q` ⇒ 全绿（基线 ± 本计划新增数）
- [ ] **Step 3: 前端构建** — `cd frontend && npm run build` ⇒ 成功
- [ ] **Step 4: 提交**

```bash
git add AGENTS.md
git commit -m "docs: AGENTS.md 补 FB 批量端点三行"
```

- [ ] **Step 5: 交付提醒（AGENTS.md 第 1132-1133 行硬性要求）**

向用户明确说清两步，**不要漏**：

1. **前端**：`cd frontend && npm run build` —— 否则 Tailscale 上的同事看不到新按钮
2. **后端**：**重启 Flask 服务** —— 否则三个新端点不生效

---

## Self-Review

**Spec 覆盖**：设计 §3.1（三个端点）→ Task 1/2/3；§3.2（回收站零后端）→ Task 7；§3.3（前端五处）→ Task 4/5/6/7；§6（测试三条腿）→ 各 Task 的测试；§7.1（不照抄 A8）→ Task 1 端点 docstring 与测试的隔离腿；§7.2（重复键口径）→ Task 3；§7.3 已勘误为「不涉及」；§7.4（纯增量）→ 无 GG/TT 文件出现在 Files 列表；§7.5（交付提醒）→ Task 8 Step 5。**无遗漏。**

**占位符**：Task 5/6/7 的「读样板」步骤是**有意的**——这三个弹窗属于「照 GG 既有组件改写」，
逐行重抄 GG 组件会把两份实现写歪；改为**先读样板再照写**，并把「去掉哪些列 / 换成什么」逐条写明。
Task 1–3 与 Task 4 给了完整代码。

**类型一致性**：`_valid_pk_int64` 在 Task 1 定义、Task 2/3 复用；`ok(...)` 的平铺语义
（`helpers.ok` 对 dict 是 `resp.update`）决定了响应形状就是 Task 1–3 写的那些顶层键；
`created_ids` / `not_found` / `errors` 三个键名在 Task 3 与 Task 6 之间一致。
