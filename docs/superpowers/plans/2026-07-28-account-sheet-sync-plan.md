# 账户管理 — Sheet 同步功能实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在账户管理页面增加 Google Sheets「我的看板」双向同步功能 — Sheet→系统（两步确认）和系统→Sheet（状态变更时自动更新备注列）。

**Architecture:** 后端新增 `POST /api/accounts/sync-from-sheet` 接口（dry_run + execute 两阶段），Google Sheets 服务新增 `read_sheet_values()` 和 `update_cell_by_account_id()` 两个通用函数。前端新增 `AccountSyncModal.vue` 组件展示差异报告。系统→Sheet 方向复用现有 `_sync_sheets_background()` 后台线程模式。

**Tech Stack:** Python Flask + SQLite + Google Sheets API v4 + Vue 3 + Element Plus + Pinia

## Global Constraints

- 纯增量原则：不修改原有功能逻辑，只在现有代码基础上追加
- 状态同步不触发清账逻辑（同步触发的状态变更仅改 status_id，不插 recharge_records）
- 代理自动创建遵循现有 `agents(name, owner_id)` UNIQUE 约束
- 运营校验失败时返回 400，不阻塞其他逻辑

---

## 文件结构

| 文件 | 角色 | 职责 |
|------|------|------|
| `py/google_sheets_service.py` | 修改 | 新增 `read_sheet_values()` 通用读取 + `update_cell_by_account_id()` 按 ID 更新备注列 |
| `py/main.py` | 修改 | 新增 sync-from-sheet 端点 + 辅助函数 + 修改 accounts_update/batch-update |
| `frontend/src/api/accounts.js` | 修改 | 新增 `syncFromSheet()` |
| `frontend/src/stores/accounts.js` | 修改 | 新增 sync action |
| `frontend/src/components/AccountSyncModal.vue` | **新建** | 同步差异弹窗（三步流程） |
| `frontend/src/views/AdsAccountPanel.vue` | 修改 | 新增「🔄 同步」按钮 + 引入弹窗 |
| `frontend/src/components/AccountDetailModal.vue` | 修改 | 新增「状态变更时间」展示 |

---

### Task 1: Google Sheets — `read_sheet_values()` 通用读取函数

**Files:**
- Modify: `py/google_sheets_service.py`（文件末尾追加）

**Interfaces:**
- Produces: `read_sheet_values(service, spreadsheet_id: str, sheet_name: str, range_str: str) -> list[list]`

- [ ] **Step 1: 在 `py/google_sheets_service.py` 末尾追加函数**

```python
def read_sheet_values(service, spreadsheet_id: str, sheet_name: str, range_str: str) -> list:
    """通用读取 Google Sheet 指定范围的值。

    Args:
        service: Google Sheets API service 对象
        spreadsheet_id: 表格 ID
        sheet_name: sheet 名称
        range_str: 范围字符串，如 'A:G'

    Returns:
        二维列表，每行为一个 list[str]，不包含空行之后的数据
    """
    range_full = f"'{sheet_name}'!{range_str}"
    try:
        result = service.spreadsheets().values().get(
            spreadsheetId=spreadsheet_id,
            range=range_full,
        ).execute()
        return result.get("values", [])
    except Exception as e:
        raise GoogleSheetsServiceError(f"读取工作表失败: {e}") from e
```

- [ ] **Step 2: 验证语法正确**

```bash
python -c "import py.google_sheets_service as gs; print('read_sheet_values' in dir(gs))"
```

- [ ] **Step 3: Commit**

```bash
git add py/google_sheets_service.py
git commit -m "feat: google_sheets_service 新增 read_sheet_values 通用读取函数"
```

---

### Task 2: Google Sheets — `update_cell_by_account_id()` 按 ID 更新备注列

**Files:**
- Modify: `py/google_sheets_service.py`（紧接 Task 1 函数之后追加）

**Interfaces:**
- Consumes: `read_sheet_values` (Task 1)
- Produces: `update_cell_by_account_id(service, spreadsheet_id: str, sheet_name: str, account_id: str, new_status: str) -> dict`

- [ ] **Step 1: 在 `py/google_sheets_service.py` 中追加函数**

```python
def update_cell_by_account_id(service, spreadsheet_id: str, sheet_name: str,
                               account_id: str, new_status: str) -> dict:
    """在指定 sheet 中按 account_id（B 列）定位行，更新备注列（F 列）。

    我的看板列结构：
      A=运营, B=账户ID, C=所属渠道, D=国家, E=时区, F=备注, G=是否封户

    Args:
        service: Google Sheets API service 对象
        spreadsheet_id: 表格 ID
        sheet_name: sheet 名称（用户私有的「我的看板」）
        account_id: 要查找的账户 ID
        new_status: 新的状态文本，写入 F 列（备注）

    Returns:
        {"updated": 1} 或 {"not_found": True}
    """
    import logging
    log = logging.getLogger("gg-server")

    # 读取全表 A-G 列
    rows = read_sheet_values(service, spreadsheet_id, sheet_name, "A:G")

    # 查找匹配 account_id 的行（B 列 = 第 0 列是 A，第 1 列是 B）
    target_row = None
    for i, row in enumerate(rows):
        if len(row) > 1 and (row[1] or "").strip() == account_id.strip():
            target_row = i
            break

    if target_row is None:
        log.info("update_cell_by_account_id: account_id=%s 在 sheet 中未找到", account_id)
        return {"not_found": True}

    # 确保行足够长到 F 列（索引 5）
    while len(rows[target_row]) < 6:
        rows[target_row].append("")

    # 更新备注列（F 列 = 索引 5）
    rows[target_row][5] = new_status

    # 写回全表
    row_num = target_row + 1  # 1-indexed
    range_write = f"'{sheet_name}'!A{row_num}:G{row_num}"
    service.spreadsheets().values().update(
        spreadsheetId=spreadsheet_id,
        range=range_write,
        valueInputOption="USER_ENTERED",
        body={"values": [rows[target_row]]},
    ).execute()

    log.info("update_cell_by_account_id: account_id=%s 备注列已更新为 '%s'", account_id, new_status)
    return {"updated": 1}
```

- [ ] **Step 2: 验证语法**

```bash
python -c "import py.google_sheets_service as gs; print('update_cell_by_account_id' in dir(gs))"
```

- [ ] **Step 3: Commit**

```bash
git add py/google_sheets_service.py
git commit -m "feat: google_sheets_service 新增 update_cell_by_account_id 按账户ID更新备注列"
```

---

### Task 3: 后端辅助函数

**Files:**
- Modify: `py/main.py`（在 `_BUILTIN_SHEET_DEFAULTS` 定义之后，约 L5178 处追加）

**Interfaces:**
- Consumes: `_json` (已有), `database` (已有), `_parse_sheet_id` (已有)
- Produces: `_get_my_dashboard_name(db, user_id) -> str`, `_get_sync_spreadsheet_id(db) -> str`

- [ ] **Step 1: 在 `_BUILTIN_SHEET_DEFAULTS` 定义之后追加两个辅助函数**

在 `py/main.py` 中找到 `_BUILTIN_SHEET_DEFAULTS = {...}` 块（约 L5174-5178），紧接其后追加：

```python
def _get_my_dashboard_name(db, user_id: int) -> str:
    """三层叠加获取当前用户的「我的看板」sheet 名。

    优先级：用户私有 config > 全局 tags > 内置默认
    """
    name = _BUILTIN_SHEET_DEFAULTS.get("my_dashboard", "我的看板")

    # 全局 tags 覆盖
    row = db.execute("SELECT value FROM tags WHERE key='sheet_mappings'").fetchone()
    if row and row["value"]:
        try:
            mappings = _json.loads(row["value"])
            if isinstance(mappings, dict) and mappings.get("my_dashboard"):
                name = mappings["my_dashboard"]
        except Exception:
            pass

    # 用户私有 config 覆盖
    row = db.execute("SELECT value FROM config WHERE key=?",
                     (f"sheet_mappings_{user_id}",)).fetchone()
    if row and row["value"]:
        try:
            mappings = _json.loads(row["value"])
            if isinstance(mappings, dict) and mappings.get("my_dashboard"):
                name = mappings["my_dashboard"]
        except Exception:
            pass

    return name


def _get_sync_spreadsheet_id(db) -> str:
    """从 tags 表获取 spreadsheet ID（复用充值表同一个表格）。

    Returns:
        spreadsheet ID 字符串，未配置时返回空字符串
    """
    row = db.execute("SELECT value FROM tags WHERE key='recharge_sheet_id'").fetchone()
    if row and row["value"]:
        raw = _json.loads(row["value"]) if row["value"] else ""
        return _parse_sheet_id(raw)
    return ""
```

- [ ] **Step 2: 验证语法**

```bash
python -c "import py.main; print('OK')"
```

- [ ] **Step 3: Commit**

```bash
git add py/main.py
git commit -m "feat: 新增 _get_my_dashboard_name 和 _get_sync_spreadsheet_id 辅助函数"
```

---

### Task 4: `POST /api/accounts/sync-from-sheet` API 端点

**Files:**
- Modify: `py/main.py`（在 `accounts_batch_update` 之后、`recharge_submit` 之前插入，约 L4095 处）

**Interfaces:**
- Consumes: `_get_my_dashboard_name` (Task 3), `_get_sync_spreadsheet_id` (Task 3), `read_sheet_values` (Task 1), `_parse_sheet_id` (已有)
- Produces: `POST /api/accounts/sync-from-sheet` 端点

- [ ] **Step 1: 在 `accounts_batch_update` 函数结束后插入 sync-from-sheet 端点**

找到 `accounts_batch_update` 函数结束（约 L4095，`recharge_submit` 注释之前），插入以下代码：

```python
@app.route("/api/accounts/sync-from-sheet", methods=["POST"])
@jwt_required()
def accounts_sync_from_sheet():
    """从「我的看板」Sheet 同步账户数据到系统。

    dry_run=true: 仅比对，返回差异报告
    dry_run=false: 执行确认后的同步操作
    """
    user_id = int(get_jwt_identity())
    data = request.get_json(silent=True) or {}
    dry_run = data.get("dry_run", True)

    db = _yt_db()

    # 1. 获取 spreadsheet_id
    sheet_id = _get_sync_spreadsheet_id(db)
    if not sheet_id:
        db.close()
        return jsonify({"success": False, "error": "请先在设置中配置表格链接"}), 400

    # 2. 获取 my_dashboard sheet 名
    dashboard_name = _get_my_dashboard_name(db, user_id)

    # 3. 检查 Google Sheets 配置
    creds_path = _GOOGLE_SHEETS_CONFIG.get("credentials_path", "")
    if not creds_path or not os.path.isfile(creds_path):
        db.close()
        return jsonify({"success": False, "error": "Google Sheets 未配置"}), 400

    # 4. 读取 Sheet 数据
    try:
        import google_sheets_service as gs
        service = gs.build_service(creds_path)
        rows = gs.read_sheet_values(service, sheet_id, dashboard_name, "A:G")
    except gs.GoogleSheetsServiceError as e:
        db.close()
        return jsonify({"success": False, "error": str(e)}), 400
    except Exception as e:
        db.close()
        return jsonify({"success": False, "error": f"无法读取表格: {e}"}), 400

    if not rows or len(rows) < 2:
        db.close()
        return jsonify({"success": False, "error": f"「{dashboard_name}」工作表中没有数据"}), 400

    # 5. 门禁校验：运营列（A列）必须匹配当前用户 display_name
    user = db.execute("SELECT display_name FROM users WHERE id=?", (user_id,)).fetchone()
    current_display_name = (user["display_name"] or "").strip() if user else ""

    # 检查数据行中运营列的值（跳过表头第一行）
    sheet_operators = set()
    for row in rows[1:]:
        op = (row[0] or "").strip() if len(row) > 0 else ""
        if op:
            sheet_operators.add(op)

    if current_display_name not in sheet_operators:
        db.close()
        operators_str = "、".join(sheet_operators) if sheet_operators else "(空)"
        return jsonify({
            "success": False,
            "error": f"这不是你的私有看板表，请修改。Sheet 中运营为「{operators_str}」，当前登录用户为「{current_display_name}」"
        }), 400

    # 6. 解析 Sheet 数据（跳过表头第一行）
    sheet_accounts = []
    warnings = []
    for i, row in enumerate(rows[1:], start=2):
        account_id = (row[1] or "").strip() if len(row) > 1 else ""
        if not account_id:
            warnings.append({"row": i, "message": "账户ID为空，跳过"})
            continue
        sheet_accounts.append({
            "account_id": account_id,
            "operator": (row[0] or "").strip() if len(row) > 0 else "",
            "agent": (row[2] or "").strip() if len(row) > 2 else "",
            "timezone": (row[4] or "").strip() if len(row) > 4 else "",
            "remark": (row[5] or "").strip() if len(row) > 5 else "",
            "blocked": (row[6] or "").strip() if len(row) > 6 else "",
        })

    # 7. 批量查询系统现有账户
    sheet_ids = [a["account_id"] for a in sheet_accounts]
    placeholders = ",".join(["?" for _ in sheet_ids])
    existing_rows = db.execute(
        f"""SELECT a.id, a.account_id, a.timezone, a.agent_id, a.status_id,
                   ag.name AS agent_name, st.name AS status_name
            FROM accounts a
            LEFT JOIN agents ag ON a.agent_id = ag.id
            LEFT JOIN account_statuses st ON a.status_id = st.id
            WHERE a.account_id IN ({placeholders}) AND a.owner_id = ?""",
        sheet_ids + [user_id]
    ).fetchall()

    existing_map = {}
    for r in existing_rows:
        existing_map[r["account_id"]] = dict(r)

    # 8. 逐行比对
    to_create = []
    to_update = []
    unchanged = 0

    for sa in sheet_accounts:
        aid = sa["account_id"]
        existing = existing_map.get(aid)

        if existing is None:
            # 系统没有 → 新增
            to_create.append({
                "account_id": aid,
                "agent": sa["agent"],
                "timezone": sa["timezone"],
                "operator": sa["operator"],
            })
        else:
            # 系统有 → 根据"是否封户"判断是否需要状态变更
            blocked = sa["blocked"]
            current_status = existing["status_name"] or "存活"

            if blocked == "是":
                if current_status != "死亡":
                    to_update.append({
                        "account_id": aid,
                        "existing_id": existing["id"],
                        "current_status": current_status,
                        "suggested_status": "死亡",
                        "封户值": blocked,
                    })
                else:
                    unchanged += 1
            elif blocked in ("否", "可用"):
                if blocked == "否" and current_status != "存活":
                    to_update.append({
                        "account_id": aid,
                        "existing_id": existing["id"],
                        "current_status": current_status,
                        "suggested_status": "存活",
                        "封户值": blocked,
                    })
                elif blocked == "可用" and current_status == "死亡":
                    to_update.append({
                        "account_id": aid,
                        "existing_id": existing["id"],
                        "current_status": current_status,
                        "suggested_status": "存活",
                        "封户值": blocked,
                    })
                else:
                    unchanged += 1
            else:
                unchanged += 1

    # 9. dry_run → 返回差异报告
    if dry_run:
        db.close()
        return jsonify({
            "success": True,
            "diff": {
                "to_create": to_create,
                "to_update": to_update,
                "unchanged": unchanged,
                "warnings": warnings,
            },
            "summary": {
                "total_in_sheet": len(sheet_accounts),
                "new_accounts": len(to_create),
                "status_changes_pending": len(to_update),
                "unchanged": unchanged,
            }
        })

    # 10. execute → 执行同步
    confirmed = data.get("confirmed", {})
    created_count = 0
    updated_count = 0
    errors = []

    # 10a. 创建新账户
    for item in confirmed.get("create", []):
        try:
            _execute_sync_create(db, item, user_id)
            created_count += 1
        except Exception as e:
            errors.append({"account_id": item, "error": str(e)})

    # 10b. 执行状态更新
    for item in confirmed.get("update", []):
        try:
            account_id = item.get("account_id", "")
            new_status = item.get("new_status", "")
            if account_id and new_status:
                # 查找状态 ID
                st = db.execute(
                    "SELECT id FROM account_statuses WHERE name=? AND owner_id=?",
                    (new_status, user_id)
                ).fetchone()
                if not st:
                    db.execute(
                        "INSERT INTO account_statuses(name, owner_id) VALUES(?,?)",
                        (new_status, user_id)
                    )
                    st_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]
                else:
                    st_id = st["id"]

                # 更新账户状态（不触发清账逻辑）
                db.execute(
                    "UPDATE accounts SET status_id=?, status_changed_date=datetime('now','localtime'), "
                    "updated_at=datetime('now','localtime') WHERE account_id=? AND owner_id=?",
                    (st_id, account_id, user_id)
                )
                updated_count += 1
        except Exception as e:
            errors.append({"account_id": item.get("account_id", ""), "error": str(e)})

    db.commit()
    db.close()

    return jsonify({
        "success": True,
        "result": {
            "created": created_count,
            "updated": updated_count,
            "errors": errors,
        }
    })


def _execute_sync_create(db, item: dict, user_id: int):
    """执行同步创建账户（内部函数，不触发清账等副作用）。"""
    account_id = item.get("account_id", "").strip()
    agent_name = item.get("agent", "").strip()
    timezone = item.get("timezone", "").strip()

    if not account_id:
        raise ValueError("账户ID不能为空")

    # 检查是否已存在（并发安全）
    existing = db.execute(
        "SELECT id FROM accounts WHERE account_id=? AND owner_id=?",
        (account_id, user_id)
    ).fetchone()
    if existing:
        return  # 已存在，跳过

    # 自动创建代理
    agent_id = None
    if agent_name:
        ag = db.execute(
            "SELECT id FROM agents WHERE name=? AND owner_id=?",
            (agent_name, user_id)
        ).fetchone()
        if ag:
            agent_id = ag["id"]
        else:
            db.execute(
                "INSERT INTO agents(name, owner_id) VALUES(?,?)",
                (agent_name, user_id)
            )
            agent_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]

    # 默认状态为"存活"
    st = db.execute(
        "SELECT id FROM account_statuses WHERE name='存活' AND owner_id=?",
        (user_id,)
    ).fetchone()
    if st:
        status_id = st["id"]
    else:
        db.execute(
            "INSERT INTO account_statuses(name, owner_id) VALUES('存活',?)",
            (user_id,)
        )
        status_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]

    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    db.execute(
        "INSERT INTO accounts(name, account_id, timezone, agent_id, status_id, "
        "acquired_date, created_at, updated_at, owner_id) "
        "VALUES(?,?,?,?,?,?,?,?,?)",
        ("", account_id, timezone, agent_id, status_id,
         datetime.date.today().isoformat(), now, now, user_id)
    )
```

- [ ] **Step 2: 验证语法**

```bash
python -c "import py.main; print('accounts_sync_from_sheet' in dir(py.main))"
```

- [ ] **Step 3: Commit**

```bash
git add py/main.py
git commit -m "feat: 新增 POST /api/accounts/sync-from-sheet 端点（dry_run + execute）"
```

---

### Task 5: 修改 `accounts_update` 增加 my_dashboard 状态同步

**Files:**
- Modify: `py/main.py`（在 `accounts_update` 函数中，清账逻辑之后，约 L3837 处）

**Interfaces:**
- Consumes: `_get_my_dashboard_name` (Task 3), `_get_sync_spreadsheet_id` (Task 3), `update_cell_by_account_id` (Task 2), `_sync_sheets_background` (已有)

- [ ] **Step 1: 在 `accounts_update` 中状态变更处增加 my_dashboard 同步**

找到 `accounts_update` 函数中 `db.commit()` 之前、清账逻辑的 Sheets 同步之后（约 L3836 的 `_sync_sheets_background(_do_sync, _on_fail)` 之后），在 `db.commit()` 之前插入以下代码：

```python
                # 新增：状态变更时同步「我的看板」备注列
                dashboard_name = _get_my_dashboard_name(db, user_id)
                sync_sheet_id = _get_sync_spreadsheet_id(db)
                if new_status and old_status and new_status != old_status["status_name"] \
                        and sync_sheet_id and dashboard_name:
                    _sync_account_id = old_status["account_id"]
                    _sync_new_status = new_status
                    _dash_name = dashboard_name
                    _s_id = sync_sheet_id

                    def _sync_dashboard():
                        import google_sheets_service as gs
                        service = gs.build_service(_GOOGLE_SHEETS_CONFIG["credentials_path"])
                        gs.update_cell_by_account_id(service, _s_id, _dash_name,
                                                      _sync_account_id, _sync_new_status)

                    def _on_dash_fail(status, err_msg):
                        if err_msg:
                            log.warning("我的看板同步失败: %s", err_msg)

                    _sync_sheets_background(_sync_dashboard, _on_dash_fail)
```

- [ ] **Step 2: 验证语法**

```bash
python -c "import py.main; print('OK')"
```

- [ ] **Step 3: Commit**

```bash
git add py/main.py
git commit -m "feat: accounts_update 状态变更时自动同步我的看板备注列"
```

---

### Task 6: 修改 `accounts_batch_update` 增加 my_dashboard 状态同步

**Files:**
- Modify: `py/main.py`（在 `accounts_batch_update` 函数中，约 L4030 `db.commit()` 之后、Sheets 同步代码处）

**Interfaces:**
- Consumes: `_get_my_dashboard_name` (Task 3), `_get_sync_spreadsheet_id` (Task 3), `update_cell_by_account_id` (Task 2), `_sync_sheets_background` (已有)

- [ ] **Step 1: 在 `accounts_batch_update` 中增加 my_dashboard 同步**

找到 `accounts_batch_update` 函数中现有的 Sheets 同步代码块（约 L4032-4064，`if field in ("status", "status_id") and value and new_clear_rows:`），在该 `if` 块的 `_sync_sheets_background(_do_sync, _on_fail)` 调用之后，该 `if` 块结束之前，增加 my_dashboard 同步。

具体位置：在 `_sync_sheets_background(_do_sync, _on_fail)` 调用之后（约 L4053 行 `gs.append_recharge(service, sheet_id, _sname, _sheet_data)` 那一行的 `_sync_sheets_background` 调用），紧接追加：

```python
                        # 新增：批量状态变更时同步「我的看板」
                        dashboard_name = _get_my_dashboard_name(db, user_id)
                        if dashboard_name:
                            _dname = dashboard_name
                            _sid = sheet_id
                            # 收集所有发生状态变更的账户
                            _status_updates = []
                            for aid in ids:
                                old = db.execute(
                                    "SELECT a.account_id, COALESCE(st.name, '存活') AS status_name "
                                    "FROM accounts a "
                                    "LEFT JOIN account_statuses st ON a.status_id = st.id "
                                    "WHERE a.id=?", (aid,)
                                ).fetchone()
                                if old and old["status_name"] != status_value_effective:
                                    _status_updates.append({
                                        "account_id": old["account_id"],
                                        "new_status": status_value_effective,
                                    })

                            if _status_updates:
                                def _sync_batch_dashboard():
                                    import google_sheets_service as gs
                                    service = gs.build_service(_GOOGLE_SHEETS_CONFIG["credentials_path"])
                                    for u in _status_updates:
                                        try:
                                            gs.update_cell_by_account_id(
                                                service, _sid, _dname,
                                                u["account_id"], u["new_status"]
                                            )
                                        except Exception as e:
                                            log.warning("我的看板同步失败 account_id=%s: %s",
                                                        u["account_id"], e)

                                _sync_sheets_background(_sync_batch_dashboard,
                                                        lambda s, e: log.warning("我的看板同步失败: %s", e) if e else None)
```

- [ ] **Step 2: 验证语法**

```bash
python -c "import py.main; print('OK')"
```

- [ ] **Step 3: Commit**

```bash
git add py/main.py
git commit -m "feat: accounts_batch_update 状态变更时自动同步我的看板备注列"
```

---

### Task 7: 前端 API + Store

**Files:**
- Modify: `frontend/src/api/accounts.js`（末尾追加）
- Modify: `frontend/src/stores/accounts.js`（actions 中追加）

**Interfaces:**
- Produces: `accountsApi.syncFromSheet(body)` → `store.syncFromSheet(body)`

- [ ] **Step 1: 在 `frontend/src/api/accounts.js` 的 `accountsApi` 对象中追加**

在 `accountsApi` 对象内（`rechargeRecords` 之后，`}` 闭合之前）追加：

```js
  syncFromSheet: (body) => api.post('/accounts/sync-from-sheet', body),
```

完整位置：`frontend/src/api/accounts.js` 第 16 行 `rechargeRecords` 之后，第 17 行 `}` 之前。

- [ ] **Step 2: 在 `frontend/src/stores/accounts.js` 的 `actions` 中追加**

在 actions 对象内（`rechargeBatchSubmit` 之后）追加：

```js
    async syncFromSheet(body) {
      return accountsApi.syncFromSheet(body)
    },
```

- [ ] **Step 3: Commit**

```bash
git add frontend/src/api/accounts.js frontend/src/stores/accounts.js
git commit -m "feat: 前端新增 syncFromSheet API 和 store action"
```

---

### Task 8: AccountSyncModal.vue — 同步差异弹窗

**Files:**
- Create: `frontend/src/components/AccountSyncModal.vue`

**Interfaces:**
- Consumes: `useAccountStore` (已有), `ElMessage` (已有)
- Produces: `<AccountSyncModal v-model:visible="syncVisible" @synced="load" />`

- [ ] **Step 1: 创建组件文件**

```vue
<template>
  <el-dialog :model-value="visible" @update:model-value="$emit('update:visible', $event)"
    title="🔄 同步 — 我的看板" width="700px" @open="startSync">
    <div v-if="loading" style="text-align:center;padding:40px;">
      <el-icon class="is-loading" :size="32"><Loading /></el-icon>
      <p style="margin-top:12px;color:#888;">正在读取「我的看板」...</p>
    </div>

    <div v-else-if="error" style="text-align:center;padding:20px;">
      <el-result icon="error" :title="error" />
    </div>

    <div v-else-if="diff">
      <el-alert type="info" :closable="false" style="margin-bottom:16px;">
        Sheet 中共 <strong>{{ diff.summary?.total_in_sheet || 0 }}</strong> 条记录
      </el-alert>

      <!-- 新增 -->
      <div v-if="diff.to_create?.length" style="margin-bottom:16px;">
        <h4>🆕 新增账户（{{ diff.to_create.length }} 条）</h4>
        <el-table :data="diff.to_create" size="small" border stripe>
          <el-table-column prop="account_id" label="账户ID" min-width="130" />
          <el-table-column prop="agent" label="所属渠道" width="100" />
          <el-table-column prop="timezone" label="时区" width="80" />
          <el-table-column prop="operator" label="运营" width="80" />
        </el-table>
      </div>

      <!-- 状态变更 -->
      <div v-if="diff.to_update?.length" style="margin-bottom:16px;">
        <h4>⚠️ 状态变更确认（{{ diff.to_update.length }} 条）</h4>
        <el-table :data="diff.to_update" size="small" border stripe
          @selection-change="val => selectedUpdates = val">
          <el-table-column type="selection" width="45" />
          <el-table-column prop="account_id" label="账户ID" min-width="130" />
          <el-table-column prop="current_status" label="当前状态" width="90">
            <template #default="{ row }">
              <el-tag size="small" :type="statusTag(row.current_status)">{{ row.current_status }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column label="建议状态" width="90">
            <template #default="{ row }">
              <el-tag size="small" :type="statusTag(row.suggested_status)">{{ row.suggested_status }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="封户值" label="封户值" width="70" />
        </el-table>
      </div>

      <!-- 无变化 -->
      <div v-if="(diff.unchanged || 0) > 0" style="margin-bottom:16px;">
        <p style="color:#16a34a;">✅ 无变化（{{ diff.unchanged }} 条）</p>
      </div>
    </div>

    <template #footer>
      <el-button @click="$emit('update:visible', false)">取消</el-button>
      <el-button v-if="diff && !submitting" type="primary" @click="doSync" :disabled="!canSync">
        确认同步
      </el-button>
      <el-button v-if="submitting" type="primary" loading>同步中...</el-button>
    </template>
  </el-dialog>
</template>

<script setup>
import { ref, computed } from 'vue'
import { useAccountStore } from '@/stores/accounts'
import { ElMessage } from 'element-plus'
import { Loading } from '@element-plus/icons-vue'

const props = defineProps({ visible: Boolean })
const emit = defineEmits(['update:visible', 'synced'])

const store = useAccountStore()
const loading = ref(false)
const submitting = ref(false)
const error = ref('')
const diff = ref(null)
const selectedUpdates = ref([])

const canSync = computed(() => {
  if (!diff.value) return false
  const hasCreates = (diff.value.to_create?.length || 0) > 0
  const hasUpdates = (diff.value.to_update?.length || 0) > 0
  if (hasUpdates && selectedUpdates.value.length === 0) return false
  return hasCreates || hasUpdates
})

function statusTag(status) {
  const map = { '存活': 'success', '验证': 'warning', '死亡': 'danger' }
  return map[status] || 'info'
}

async function startSync() {
  loading.value = true
  error.value = ''
  diff.value = null
  selectedUpdates.value = []
  try {
    const res = await store.syncFromSheet({ dry_run: true })
    if (res.success) {
      diff.value = res.diff
      // 默认全选状态变更项
      selectedUpdates.value = [...(res.diff?.to_update || [])]
    } else {
      error.value = res.error || '读取失败'
    }
  } catch (e) {
    error.value = e.response?.data?.error || e.message || '同步失败'
  } finally {
    loading.value = false
  }
}

async function doSync() {
  submitting.value = true
  try {
    const confirmed = {
      create: (diff.value?.to_create || []).map(c => c.account_id),
      update: selectedUpdates.value.map(u => ({
        account_id: u.account_id,
        new_status: u.suggested_status,
      })),
    }
    const res = await store.syncFromSheet({ dry_run: false, confirmed })
    if (res.success) {
      const r = res.result
      ElMessage.success(`同步完成：新增 ${r.created} 个账户，更新 ${r.updated} 个状态`)
      emit('update:visible', false)
      emit('synced')
    } else {
      ElMessage.error(res.error || '同步失败')
    }
  } catch (e) {
    ElMessage.error(e.response?.data?.error || e.message || '同步失败')
  } finally {
    submitting.value = false
  }
}
</script>
```

- [ ] **Step 2: 验证组件语法**（Vue 编译检查由构建工具处理）

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/AccountSyncModal.vue
git commit -m "feat: 新增 AccountSyncModal 同步差异弹窗组件"
```

---

### Task 9: AdsAccountPanel.vue — 同步按钮

**Files:**
- Modify: `frontend/src/views/AdsAccountPanel.vue`

- [ ] **Step 1: 在工具栏按钮行增加同步按钮**

在 `AdsAccountPanel.vue` 模板中，找到工具栏按钮行（约 L6-10），在 `batchRechargeVisible` 按钮之后、`selected.length` 显示之前插入：

```html
        <el-button @click="syncVisible = true">🔄 同步</el-button>
```

即修改后的按钮行变为：

```html
        <el-button type="primary" @click="showModal()">➕ 新增账户</el-button>
        <el-button @click="batchVisible = true">📥 批量导入</el-button>
        <el-button @click="lookupVisible = true">🔍 批量查户</el-button>
        <el-button @click="batchRechargeVisible = true" :disabled="!selected.length">💰 批量充值</el-button>
        <el-button @click="syncVisible = true">🔄 同步</el-button>
```

- [ ] **Step 2: 在模板末尾引入 AccountSyncModal**

找到 `AdsAccountPanel.vue` 模板末尾的其他 Modal 组件（约 L93-98），在 `RechargeBatchModal` 之后、`</div>` 闭合之前添加：

```html
    <AccountSyncModal v-model:visible="syncVisible" @synced="load" />
```

- [ ] **Step 3: 在 script 中导入组件和添加状态变量**

在 `<script setup>` 的 import 区域（约 L109），添加：

```js
import AccountSyncModal from '@/components/AccountSyncModal.vue'
```

在 ref 变量声明区域（约 L124 附近），添加：

```js
const syncVisible = ref(false)
```

- [ ] **Step 4: 验证** — 前端构建

```bash
cd frontend && npm run build
```

- [ ] **Step 5: Commit**

```bash
git add frontend/src/views/AdsAccountPanel.vue
git commit -m "feat: AdsAccountPanel 新增同步按钮和弹窗集成"
```

---

### Task 10: AccountDetailModal.vue — 状态变更时间展示

**Files:**
- Modify: `frontend/src/components/AccountDetailModal.vue`

- [ ] **Step 1: 在 info-grid 中增加状态变更时间**

在 `AccountDetailModal.vue` 模板的 `info-grid` div 中，找到「到手时间」行（约 L23），在其后增加：

```html
        <div><strong>状态变更时间：</strong>{{ account.status_changed_date || '-' }}</div>
```

完整上下文（修改后的 info-grid）：
```html
      <div class="info-grid">
        <div><strong>账户名称：</strong>{{ account.name }}</div>
        <div><strong>账户 ID：</strong>{{ account.account_id }}</div>
        <div>
          <strong>当前 MCC：</strong>
          <template v-if="account.mcc_name">
            <span class="mcc-current">{{ account.mcc_name }}</span>
            <span class="mcc-code"> ({{ account.mcc_code }})</span>
          </template>
          <span v-else class="text-muted">未分配</span>
        </div>
        <div><strong>时区：</strong>{{ account.timezone || '-' }}</div>
        <div><strong>代理：</strong>{{ account.agent || '-' }}</div>
        <div>
          <strong>状态：</strong>
          <el-tag size="small" :type="statusTagType(account.status)">{{ account.status || '未知' }}</el-tag>
        </div>
        <div><strong>状态变更时间：</strong>{{ account.status_changed_date || '-' }}</div>
        <div><strong>到手时间：</strong>{{ account.acquired_date || '-' }}</div>
        <div v-if="account.death_date"><strong>死亡时间：</strong><span class="text-danger">{{ account.death_date }}</span></div>
      </div>
```

- [ ] **Step 2: 验证** — 确保 `accounts_list` API 返回的数据中包含 `status_changed_date` 字段

检查 `accounts_list` 查询（`py/main.py` L3351-3358）使用 `SELECT a.*`，已包含 `status_changed_date` 字段，无需额外修改。

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/AccountDetailModal.vue
git commit -m "feat: AccountDetailModal 新增状态变更时间展示"
```

---

## 自审记录

1. **Spec 覆盖检查**：
   - ✅ Sheet→系统 dry_run 比对 → Task 4
   - ✅ Sheet→系统 execute 执行 → Task 4
   - ✅ 运营门禁校验 → Task 4
   - ✅ 新增不弹窗、已有弹窗 → Task 4
   - ✅ 是否封户规则（是→死亡/否→存活/可用→非死亡即可）→ Task 4
   - ✅ 系统→Sheet 自动同步（accounts_update）→ Task 5
   - ✅ 系统→Sheet 批量同步（batch-update）→ Task 6
   - ✅ 状态变更时间展示 → Task 10
   - ✅ 代理自动创建 → Task 4 中 `_execute_sync_create`
   - ✅ 新增时账户名称/MCC 留空 → Task 4 中 `_execute_sync_create`

2. **占位符检查**：无 TBD/TODO/占位符

3. **类型一致性**：
   - `read_sheet_values` 返回 `list[list]` → Task 2 调用一致
   - `update_cell_by_account_id` 返回 `dict` → Task 5/6 的 on_fail 回调签名一致
   - 前端 `syncFromSheet` 接口签名 → Task 7/8 调用一致
