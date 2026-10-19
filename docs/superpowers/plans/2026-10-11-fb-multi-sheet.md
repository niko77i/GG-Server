# FB 户管看板：多表 + 户类型（子项目 B）实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 FB 户管看板从「一张表（靠空串约定撑着）」升级成「一组表」，并让 FB 账户有自己的分类 `account_type`（存每行「资产类型」单元格原串）与 `source_sheet`（存读自哪张工作表）。同步按表读、按 `source_sheet` 回写、撤回按表；账户页加户类型筛选。GG 逐字节不变，TT 只在既有「分组键」体系里加一层按平台取键的抽象（键仍 `account_type`）。

**Architecture:** `fb_accounts` 加两列 `account_type` / `source_sheet`（建表语句与迁移区两处）。抽出**分表键抽象** `_sheet_key_of(platform, row)` / `_table_key_of(platform, table)`（tt→`account_type`、fb→`source_sheet`、gg→空串），`group_rows_by_sheet` / `collect_rows_for_push` / `_resolve_account_table` / `dashboard_push` 全改用它。FB 配置从 `{spreadsheet_id, sheet_name, columns}` 升级成 `{spreadsheet_id, tables:[{name, sheet_name, columns}]}`，读路径对老配置做 legacy 兜底（扁平 `sheet_name` ⇒ 一条，`name` 取该表名）。两列经合成键 `_account_type` / `_source_sheet` 沿 `_collect_updates → build_diff → apply_diff` 传递，`apply_diff` 更新时**只在非空时写**，`_same_as_existing` 把「本次产出为空」视为无变化。

**Tech Stack:** Python 3.11 / Flask / SQLite（原生 sqlite3）/ Vue 3 + Element Plus / pytest / Google Sheets API（测试里一律打桩）/ 前端纯逻辑 `node --test`（`.mjs`）

**Spec:** `docs/superpowers/specs/2026-10-11-fb-multi-sheet-design.md`（下称「spec §X」）
**侦察:** `.superpowers/sdd/fb-multi-sheet-recon.md`（下称「recon §X」）

## Global Constraints

- **不启动任何进程**：前端 dev server 与后端 5001 都由用户控制。改完只跑测试，不起服务；**5001 绝不自己起**。
- **禁止 `git add -A` / `git pull` / `git push`**。提交一律显式 pathspec：`git add <file1> <file2>` 后 `git commit -m "..." -- <file1> <file2>`。
- **有并行会话共用工作区**：不要 `git checkout` / `git stash` / 切分支；拼审查包按文件过滤（`git diff -- <file>`），不带别人的 hunk。
- **GG 行为逐字节不变**：`COLUMN_SPEC["gg"]`、`READ_RANGE["gg"]`、gg 配置载荷形状（不含 `columns`、不含 `tables`、不含 `*_field_catalog`）、gg 的 `group_rows_by_sheet` / `collect_rows_for_push` / 撤回路径一个字不动。
- **TT 行为逐字节不变**：本次只在 TT 那套里加「按平台取分组键」的抽象，TT 的键仍是 `account_type`、匹配 `t["name"]`；改名级联、默认类型「加白户」、空类型跳过等语义全部照旧。每个任务结束时 TT 既有测试全绿。
- **`_ensure_region` / `_region_exists` 留在 `huguan_dashboard.py`**：本次不迁。
- **测试夹具涉及 `owner_id` / `user_id` 等 `REFERENCES users(id)` 时，必须先真造用户**：`get_db()` 开了 `PRAGMA foreign_keys=ON`，临时库空库时假 id（如 `owner_id=7`）会 FK 失败，且报错不点明原因。造用户用 `INSERT INTO users(username, password, role, platform) ...`。
- **测试命令**：后端 `cd py && python -m pytest tests/<file> -q`；前端 `cd frontend && npm test` + `npx vite build`。
- **提交信息格式**：`<type>(fb-multi-sheet): <中文说明>`。
- **行号会漂**：本计划所有 `文件:行号` 是 2026-10-19 侦察时点的位置，定位代码一律「按函数名 / 内容定位（当前约在 X，会漂）」，不要只信裸行号。

### 三个必须遵守的接口约定（后面每个任务都依赖）

1. **分表键**：`_sheet_key_of(platform, row) -> str`（行上的键）与 `_table_key_of(platform, table) -> str`（配置项上的键）。tt 两者分别是 `account_type` / `t["name"]`；fb 是 `source_sheet` / `t["sheet_name"]`；gg 恒空串。**匹配判据恒为 `_sheet_key_of(...) == _table_key_of(...)`**，别在调用点再手写一次 `or`。
2. **合成键 `_account_type` / `_source_sheet` 只在 fb 上无条件产出**（值缺失时为空串）；`apply_diff` 更新分支**只在非空时写**；`_same_as_existing` 对这两个键**「本次产出为空」一律视为无变化**（spec §4.9 的坑）。
3. **FB 的 `_account_type` 是「资产类型」单元格原串**（`parse_row` 产出的 `asset_type_name`），**不是**表名、**不是**配置里的 `name`、**不是** `asset_type_id`。

---

## 文件结构

| 文件 | 职责 | 本次改动 |
|---|---|---|
| `py/database.py` | 建表 + 列级迁移 | `fb_accounts` 建表语句**与**迁移区各加 `account_type` / `source_sheet` |
| `py/huguan_dashboard.py` | 户管看板纯逻辑层 | 分表键抽象；`_FB_ROW_SQL` 补两列；`group_rows_by_sheet` / `collect_rows_for_push` / `cross_sheet_notes` 按平台取键；`get_platform_tables("fb")` 多表化；`save_config` 放开 fb；`_collect_updates` / `_same_as_existing` / `apply_diff` 消费两键；`undo_push` 配置门放开 fb |
| `py/routes/huguan_dashboard_routes.py` | HTTP 入口 | `/sync` `/push` 按表门控放开 fb；配置 GET/POST 的 fb 形状改 `tables`；`_account_type`/`_source_sheet` 注入扩到 fb；`dashboard_push` 按表过滤改平台键 |
| `py/routes/huguan_sheet_targets.py` | 写表目标按账户重建 | `_resolve_account_table` 按平台取键（fb 用 `source_sheet`）；`huguan_dashboard_sync` 的 col_map 字典键按平台取 |
| `py/routes/fb_routes.py` | FB 账户列表 | `list_accounts` 加 `account_types` 筛选 + `type_counts` |
| `frontend/src/components/HuguanDashboardCard.vue` | 户管看板卡片 | 放开对 fb 隐藏的四样；平台级按钮文案；配置摊平/折回改 `tables` |
| `frontend/src/utils/columnMapping.mjs` | 列映射纯换算 | `seedTables` / `flattenColumns` 支持 fb 的 `tables` 形状 |
| `frontend/src/api/fb.js` | FB API | `listAccounts` 加 `paramsSerializer`（重复参数 `account_types`） |
| `frontend/src/constants/accountColumns.js` | 列注册表 | `FB_ADS_COLUMNS` 加「户类型」列 |
| `frontend/src/views/fb/FbAccountPanel.vue` | FB 账户面板 | 户类型筛选按钮 + 筛选/计数状态 |
| 测试 | — | 下面 §七 那一批（`test_fb_asset_model.py` / `test_huguan_dashboard.py` / `test_huguan_undo.py` / `test_huguan_sheet_write.py` / `test_fb_list_batch.py` / 前端 `.mjs`） |

---

## Task 1: 数据模型 —— `fb_accounts` 加 `account_type` / `source_sheet`

**Files:**
- Modify: `py/database.py`（`fb_accounts` 建表语句，按 `CREATE TABLE IF NOT EXISTS fb_accounts` 定位，当前约在 792-804；迁移区按 `acceptor` 那条 `_add_column_if_missing` 定位，当前约在 229）
- Test: `py/tests/test_fb_asset_model.py`（`TestFbAccountColumns` 类里追加）

**Interfaces:**
- Consumes: `_add_column_if_missing(conn, table, col_name, col_def) -> bool`
- Produces: `fb_accounts.account_type TEXT DEFAULT ''`、`fb_accounts.source_sheet TEXT DEFAULT ''`（建表语句 + 迁移区**两处**都有）

- [ ] **Step 1: 写失败测试**

追加到 `py/tests/test_fb_asset_model.py`（该文件已有 `_cols(conn, table)` helper 与 `TestFbAccountColumns` 类）。**在 `TestFbAccountColumns` 类里追加下面 3 个方法**（类里的既有用例一个字不动）：

```python
    def test_account_type_and_source_sheet_columns_exist(self, client):
        """B 的两列：account_type（资产类型原串）+ source_sheet（读自哪张表）。"""
        db = database.get_db()
        cols = _cols(db, "fb_accounts")
        db.close()
        assert cols.get("account_type") == "TEXT", "account_type 缺失或类型不对"
        assert cols.get("source_sheet") == "TEXT", "source_sheet 缺失或类型不对"

    def test_fresh_schema_has_both_columns(self):
        """建表语句那一处也要有：只加迁移不加建表，新建库会缺列（spec §4.1）。"""
        import os, tempfile, sqlite3
        fd, db_path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        try:
            database._ensure_schema(conn)      # 只跑建表，不跑 _ensure_columns
            cols = {r[1] for r in conn.execute("PRAGMA table_info(fb_accounts)").fetchall()}
            assert "account_type" in cols, "建表语句缺 account_type（迁移区加了也不够）"
            assert "source_sheet" in cols, "建表语句缺 source_sheet（迁移区加了也不够）"
        finally:
            conn.close()
            os.unlink(db_path)

    def test_migration_idempotent_includes_new_columns(self, client):
        """_ensure_columns 连跑两次不报错，且两列都存在。"""
        db1 = database.get_db()
        db1.close()
        db2 = database.get_db()
        cols = _cols(db2, "fb_accounts")
        db2.close()
        assert "account_type" in cols and "source_sheet" in cols
```

- [ ] **Step 2: 跑失败测试**

Run: `cd py && python -m pytest tests/test_fb_asset_model.py -q -k "account_type_and_source_sheet or fresh_schema_has_both or migration_idempotent_includes"`
Expected: FAIL —— `account_type` / `source_sheet` 不在列里。

- [ ] **Step 3: 建表语句加两列**

`py/database.py` 的 `CREATE TABLE IF NOT EXISTS fb_accounts`，在 `updated_at TEXT DEFAULT (datetime('now','localtime'))` 之前（`status_id` / `owner_id` 那组业务列之后）加两行。整体替换为：

```python
        CREATE TABLE IF NOT EXISTS fb_accounts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            account_id TEXT NOT NULL UNIQUE,
            timezone TEXT DEFAULT '',
            status_id INTEGER REFERENCES account_statuses(id),
            acquired_date TEXT DEFAULT (date('now','localtime')),
            status_changed_date TEXT DEFAULT '',
            owner_id INTEGER REFERENCES users(id),
            account_type TEXT DEFAULT '',
            source_sheet TEXT DEFAULT '',
            deleted_at TEXT DEFAULT NULL,
            created_at TEXT DEFAULT (datetime('now','localtime')),
            updated_at TEXT DEFAULT (datetime('now','localtime'))
        );
```

> `account_type` 存「资产类型」单元格**原串**（spec §二.4 接受与字典 id 漂移的代价）；`source_sheet` 存「读自哪张工作表」的原串。两列都可空 —— 存量 0 行（recon §三.8），**不回填**（写死一个默认类型反而是错的）。

- [ ] **Step 4: 迁移区加两列**

`py/database.py` 的 `_ensure_columns`，紧跟 FB 资产模型那批 `_add_column_if_missing`（`acceptor` 那条）之后插入：

```python
    # FB 多表 + 户类型（2026-10-11 子项目 B spec §4.1）：account_type 存「资产类型」单元格
    # 原串（不是 id、不回填 —— 存量 0 行且写死默认类型是错的）；source_sheet 存「读自哪张表」。
    # 与 tt_accounts.account_type 不同：fb 的 account_type 是数据驱动的（来自单元格），
    # **不做**一次性回填，也不在 save_config 里做改名级联（spec §五）。
    _add_column_if_missing(conn, "fb_accounts", "account_type",
                           "account_type TEXT DEFAULT ''")
    _add_column_if_missing(conn, "fb_accounts", "source_sheet",
                           "source_sheet TEXT DEFAULT ''")
```

- [ ] **Step 5: 跑测试确认通过**

Run: `cd py && python -m pytest tests/test_fb_asset_model.py -q`
Expected: PASS（含本次 3 个新用例）

- [ ] **Step 6: 跑同族回归**

Run: `cd py && python -m pytest tests/test_fb_asset_model.py tests/test_fb_huguan_dashboard.py tests/test_huguan_dashboard.py -q`
Expected: 全绿（加列不改任何既有读路径）

- [ ] **Step 7: 提交**

```bash
git add py/database.py py/tests/test_fb_asset_model.py
git commit -m "feat(fb-multi-sheet): fb_accounts 加 account_type / source_sheet（建表 + 迁移两处）" -- py/database.py py/tests/test_fb_asset_model.py
```

---

## Task 2: 分表键抽象 + SQL —— `_FB_ROW_SQL` 补两列，`group_rows_by_sheet` / `collect_rows_for_push` 改用它

> **依赖**：Task 1 的 `source_sheet` 列（`_FB_ROW_SQL` 要 SELECT 它）。

**Files:**
- Modify: `py/huguan_dashboard.py`（`save_config` 之后、`group_rows_by_sheet` 之前加抽象；`group_rows_by_sheet`；`_FB_ROW_SQL`；`collect_rows_for_push`）
- Test: `py/tests/test_huguan_dashboard.py`（`TestGroupRowsBySheet` 类里追加 fb 用例 + 新增 `TestSheetKeyAbstraction` 类）

**Interfaces:**
- Consumes: Task 1 的两列
- Produces:
  - `_SHEET_KEY_FIELD = {"tt": "account_type", "fb": "source_sheet", "gg": None}`
  - `_sheet_key_of(platform: str, row: dict) -> str`
  - `_table_key_of(platform: str, table: dict) -> str`
  - `_FB_ROW_SQL` 带 `a.account_type, a.source_sheet`
  - `collect_rows_for_push` 产出的 item 带 `account_type` 与 `source_sheet`

- [ ] **Step 1: 写失败测试**

在 `py/tests/test_huguan_dashboard.py` 的 `TestGroupRowsBySheet` 类里追加（该类已有 `client` 夹具，uid 用 7 与同文件一致；类里的既有用例一个字不动）；再新增一个类：

```python
    # 以下 3 个方法追加进 TestGroupRowsBySheet 类

    def test_fb_splits_by_source_sheet(self, client):
        """fb 按 source_sheet 分桶、匹配 t["sheet_name"]（不是 t["name"]）。"""
        db = database.get_db()
        db.execute("INSERT OR REPLACE INTO config(key,value) VALUES('huguan_dashboard_7', ?)",
                   (json.dumps({"fb": {"spreadsheet_id": "SS", "tables": [
                       {"name": "加白户", "sheet_name": "加白户表"},
                       {"name": "企业户", "sheet_name": "企业户表"}]}}),))
        db.commit()
        rows = [{"account_id": "1", "source_sheet": "加白户表", "cells": {"A": "x"}},
                {"account_id": "2", "source_sheet": "企业户表", "cells": {"A": "y"}}]
        groups, skipped = hd.group_rows_by_sheet(db, 7, "fb", rows)
        assert [(s, [r["account_id"] for r in rs]) for s, rs in groups] == [
            ("加白户表", ["1"]), ("企业户表", ["2"])]
        assert skipped == []
        db.close()

    def test_fb_unknown_source_sheet_is_skipped_not_first_table(self, client):
        """source_sheet 指向配置里没有的表 ⇒ 跳过，绝不写第一张表（spec §4.5）。"""
        db = database.get_db()
        db.execute("INSERT OR REPLACE INTO config(key,value) VALUES('huguan_dashboard_7', ?)",
                   (json.dumps({"fb": {"spreadsheet_id": "SS", "tables": [
                       {"name": "加白户", "sheet_name": "加白户表"}]}}),))
        db.commit()
        rows = [{"account_id": "1", "source_sheet": "已删除的表", "cells": {"A": "x"}}]
        groups, skipped = hd.group_rows_by_sheet(db, 7, "fb", rows)
        assert groups == []
        assert skipped == ["已删除的表"]
        db.close()

    def test_fb_empty_source_sheet_is_skipped(self, client):
        """空 source_sheet ⇒ 跳过（与 tt 空类型同口径），**不得**落进第一张表。"""
        db = database.get_db()
        db.execute("INSERT OR REPLACE INTO config(key,value) VALUES('huguan_dashboard_7', ?)",
                   (json.dumps({"fb": {"spreadsheet_id": "SS", "tables": [
                       {"name": "加白户", "sheet_name": "加白户表"}]}}),))
        db.commit()
        rows = [{"account_id": "1", "source_sheet": "", "cells": {"A": "x"}}]
        groups, skipped = hd.group_rows_by_sheet(db, 7, "fb", rows)
        assert groups == []
        assert skipped == ["（未设置来源表）"]
        db.close()


class TestSheetKeyAbstraction:
    """分表键抽象：tt/fb/gg 三个平台各取各的键（spec §4.2）。"""

    def test_sheet_key_of_per_platform(self):
        assert hd._sheet_key_of("tt", {"account_type": "加白户"}) == "加白户"
        assert hd._sheet_key_of("fb", {"source_sheet": "企业户表"}) == "企业户表"
        assert hd._sheet_key_of("gg", {"anything": "x"}) == ""

    def test_table_key_of_per_platform(self):
        assert hd._table_key_of("tt", {"name": "加白户", "sheet_name": "总户-加白"}) == "加白户"
        assert hd._table_key_of("fb", {"name": "企业户", "sheet_name": "企业户表"}) == "企业户表"
        assert hd._table_key_of("gg", {"name": "", "sheet_name": "看板G"}) == ""

    def test_fb_row_sql_selects_both_columns(self):
        """_FB_ROW_SQL 必须 SELECT account_type 与 source_sheet —— 这是整条链路的最小一刀。"""
        assert "a.account_type" in hd._FB_ROW_SQL
        assert "a.source_sheet" in hd._FB_ROW_SQL

    def test_fb_collect_rows_carries_both_keys(self):
        db = database.get_db()
        db.execute("INSERT OR REPLACE INTO users(id, username, password, role, platform) "
                   "VALUES(9901, 'fb_sk_u', 'x', 'user', 'fb')")
        db.execute("INSERT INTO fb_accounts(name, account_id, account_type, source_sheet, owner_id) "
                   "VALUES('户甲', 'SK-FB-1', '企业户', '企业户表', 9901)")
        db.commit()
        rows = hd.collect_rows_for_push(db, "fb", ["SK-FB-1"])
        db.close()
        assert rows[0]["account_type"] == "企业户"
        assert rows[0]["source_sheet"] == "企业户表"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd py && python -m pytest tests/test_huguan_dashboard.py -q -k "TestSheetKeyAbstraction or test_fb_splits_by_source_sheet or test_fb_unknown_source_sheet_is_skipped or test_fb_empty_source_sheet_is_skipped"`
Expected: FAIL —— `AttributeError: module 'huguan_dashboard' has no attribute '_sheet_key_of'` / `_FB_ROW_SQL` 不含 `source_sheet`。

- [ ] **Step 3: 加分表键抽象**

`py/huguan_dashboard.py`，在 `save_config` **之后**、`group_rows_by_sheet` **之前**插入（`_conf_text` 已在 638 定义，可直接用）：

```python
# 分表键（2026-10-11 设计 §4.2 方案 1 的核心）：一行账户「该写回哪张表」的判据字段。
#   tt → account_type（户类型名，与配置项 t["name"] 对）
#   fb → source_sheet（读自哪张工作表，与配置项 t["sheet_name"] 对）
#   gg → 无（恒单表，恒空串）
_SHEET_KEY_FIELD = {"tt": "account_type", "fb": "source_sheet", "gg": None}


def _sheet_key_of(platform: str, row: dict) -> str:
    """取某行账户的分表键值（空则返回空串）。gg 恒空串。"""
    field = _SHEET_KEY_FIELD.get(platform)
    return _conf_text((row or {}).get(field)) if field else ""


def _table_key_of(platform: str, table: dict) -> str:
    """取某配置表项上与之匹配的键：tt 是 t["name"]，fb 是 t["sheet_name"]，gg 恒空串。"""
    if platform == "fb":
        return _conf_text((table or {}).get("sheet_name"))
    return _conf_text((table or {}).get("name"))
```

- [ ] **Step 4: `group_rows_by_sheet` 改用它**

整体替换 `group_rows_by_sheet`（当前约 777-809，按函数名定位）：

```python
def group_rows_by_sheet(db, user_id: int, platform: str, rows: list):
    """把待写行按「分表键 → worksheet」分组（spec §4.2）。

    返回 `(groups, skipped)`：`groups` 是 `[(sheet_name, rows)]`（按配置顺序），
    `skipped` 是「在配置里查不到工作表的分表键」列表。

    分桶键与匹配键**按平台取**：tt 用 account_type（对 t["name"]）、fb 用 source_sheet
    （对 t["sheet_name"]）、gg 恒空串（配置里恰有一个空名条目 ⇒ 只有一组）。tt / fb 查不到
    对应工作表的分表键**跳过**，绝不退回写第一张表 —— 那正是多表之后要消除的「填错表」。
    只有 gg 保留「空键落进唯一一张表」的历史态兜底（它恒单表）。
    """
    tables = get_platform_tables(db, user_id, platform)
    buckets = {}
    for r in rows:
        buckets.setdefault(_sheet_key_of(platform, r) or "", []).append(r)
    groups, skipped = [], []
    for t in tables:
        key = _table_key_of(platform, t)
        if key in buckets:
            groups.append((t["sheet_name"], buckets.pop(key)))
    for leftover, leftover_rows in buckets.items():
        if leftover:
            skipped.append(leftover)
        elif platform == "gg" and tables:
            # gg 恒单表：空键配置里恰好一个空名条目 ⇒ 正常已被上面的循环取走。
            # 保留这一支只为兼容「配置条目缺失」的历史态，行为与改动前等价。
            groups.append((tables[0]["sheet_name"], leftover_rows))
        else:
            # tt / fb：空键（空类型 / 空 source_sheet）⇒ 查不到对应工作表。绝不退回写第一张表。
            label = "（未设置户类型）" if platform == "tt" else "（未设置来源表）"
            skipped.append(leftover or label)
    return groups, skipped
```

> ⚠️ `elif platform != "tt" and tables:` 改成 `elif platform == "gg" and tables:` —— fb 现在有「空 source_sheet」要跳过，**不能**再落进第一张表。tt 的空类型路径（`else` 分支）逐字不变。

- [ ] **Step 5: `_FB_ROW_SQL` 补两列**

`py/huguan_dashboard.py` 的 `_FB_ROW_SQL`（当前约 2213-2227），SELECT 列表加 `a.account_type, a.source_sheet`：

```python
_FB_ROW_SQL = """
SELECT a.account_id, a.account_type, a.source_sheet, a.acquired_date, a.name, a.timezone,
       a.operator, a.acceptor, a.unit_price, a.inbound_qty, a.outbound_date, a.outbound_qty,
       a.consumption, a.remark,
       ch.name AS channel_name, at.name AS asset_type_name,
       bm.name AS primary_bm_name,
       COALESCE(NULLIF(u.display_name, ''), u.username, '') AS owner_name,
       s.name AS status_name
FROM fb_accounts a
LEFT JOIN fb_channels ch ON a.channel_id = ch.id
LEFT JOIN fb_asset_types at ON a.asset_type_id = at.id
LEFT JOIN fb_account_bm ab ON ab.account_id = a.id AND ab.is_primary = 1
LEFT JOIN fb_bms bm ON ab.bm_id = bm.id
LEFT JOIN users u ON a.owner_id = u.id
LEFT JOIN account_statuses s ON a.status_id = s.id
"""
```

- [ ] **Step 6: `collect_rows_for_push` 按平台取键**

把 `collect_rows_for_push` 的产出循环（当前约 2271-2284）改为：

```python
    out = []
    for q_sql, q_params in queries:
        for r in db.execute(q_sql, q_params).fetchall():
            row = dict(r)
            key = _sheet_key_of(platform, row)
            cm = col_maps_by_type.get(key) if col_maps_by_type else None
            item = {"account_id": str(row.get("account_id") or "").strip(),
                    "cells": cells_for_row(row, platform, cm)}
            # 分表键：tt 是 account_type、fb 是 source_sheet。两者都从 SQL 带出（fb 的
            # _ROW_SQL 新增两列；gg/tt 的 _ROW_SQL 没有 source_sheet 列 ⇒ 空串）。
            # group_rows_by_sheet 按 _sheet_key_of 取用，这里原样带上，方便下游（按表过滤、
            # 日志）直接读，无需再回查库。
            item["account_type"] = row.get("account_type") or ""
            item["source_sheet"] = row.get("source_sheet") or ""
            out.append(item)
    return [o for o in out if o["account_id"]]
```

并把 `collect_rows_for_push` 的 docstring 里对 `col_maps_by_type` 的说明改成：

```python
    `col_maps_by_type`（可选）是 `{分表键: 该表的 col_map}`。**键按平台取**：tt 的键是
    `t["name"]`（户类型名）、fb 的键是 `t["sheet_name"]`（工作表名）—— 与 `_table_key_of`
    同口径。给了就逐行按该行的 `_sheet_key_of` 取到本表的 col_map 再产出 cells（tt / fb
    表头顺序不同 ⇒ 固定列字母会串列）；没给（None）⇒ 既有合成 map，只有 gg 与既有调用点
    零改动、逐字节不变。调用方负责把 col_map 解析好（读表头需要 service，本函数只有 db）。
```

- [ ] **Step 7: 跑测试确认通过**

Run: `cd py && python -m pytest tests/test_huguan_dashboard.py -q -k "TestSheetKeyAbstraction or TestGroupRowsBySheet"`
Expected: PASS（含 tt/gg 既有 `TestGroupRowsBySheet` 用例全绿 —— 这是「TT 逐字节不变」的第一道证据）

- [ ] **Step 8: 跑全量回归**

Run: `cd py && python -m pytest tests/test_huguan_dashboard.py tests/test_huguan_undo.py tests/test_fb_huguan_dashboard.py tests/test_chunk_callers.py -q`
Expected: 全绿（`collect_rows_for_push` 的 `chunk` 调用点、undo 侧既有用例均不动）

- [ ] **Step 9: 提交**

```bash
git add py/huguan_dashboard.py py/tests/test_huguan_dashboard.py
git commit -m "feat(fb-multi-sheet): 分表键抽象（tt=account_type/fb=source_sheet）+ _FB_ROW_SQL 补两列" -- py/huguan_dashboard.py py/tests/test_huguan_dashboard.py
```

---

## Task 3: 配置多表化 —— `get_platform_tables("fb")` 多表 + legacy 兜底，`save_config` 放开 fb

**Files:**
- Modify: `py/huguan_dashboard.py`（`get_platform_tables` 当前约 661-701、`save_config` 当前约 715-774）
- Test: `py/tests/test_huguan_dashboard.py`（更新 `TestPlatformTables` 里 4 个 fb 用例 + 追加多表用例）

**Interfaces:**
- Consumes: `TT_DEFAULT_ACCOUNT_TYPE`（tt 分支原样保留）
- Produces: `get_platform_tables(db, uid, "fb") -> [{"name", "sheet_name", "columns"}]`（legacy 扁平 `sheet_name` ⇒ 一条，`name` 取该表名）；`save_config(db, uid, platform, spreadsheet_id, sheet_name, *, tables=None, columns=None)` 放开 fb 的 `tables`

- [ ] **Step 1: 写失败测试 + 更新既有 fb 用例**

先更新 `TestPlatformTables` 里 4 个 fb 单表用例到新形状（它们在 `test_fb_carries_columns_and_gg_does_not` 等，按内容定位，当前约 4956-4990）：

```python
    def test_fb_carries_columns_and_gg_does_not(self, client):
        """fb 走 tables（多表，每项带 columns）；**gg 不带** —— 载荷形状逐字节不变。"""
        db = self._db()
        hd.save_config(db, 9, "fb", "SS1", "", tables=[
            {"name": "账户管理分配", "sheet_name": "账户管理分配", "columns": {"时区": "consumption"}}])
        hd.save_config(db, 9, "gg", "SS2", "看板G")
        assert hd.get_platform_tables(db, 9, "fb") == [
            {"name": "账户管理分配", "sheet_name": "账户管理分配",
             "columns": {"时区": "consumption"}}]
        assert hd.get_platform_tables(db, 9, "gg") == [
            {"name": "", "sheet_name": "看板G"}]
        db.close()

    def test_fb_columns_default_to_empty_dict(self, client):
        db = self._db()
        hd.save_config(db, 9, "fb", "SS1", "", tables=[
            {"name": "账户管理分配", "sheet_name": "账户管理分配"}])
        assert hd.get_platform_tables(db, 9, "fb")[0]["columns"] == {}
        db.close()

    def test_fb_columns_survive_a_round_trip(self, client):
        db = self._db()
        hd.save_config(db, 9, "fb", "SS1", "", tables=[
            {"name": "账户管理分配", "sheet_name": "账户管理分配", "columns": {"时区": "consumption"}}])
        got = hd.get_platform_tables(db, 9, "fb")[0]["columns"]
        hd.save_config(db, 9, "fb", "SS1", "", tables=[
            {"name": "账户管理分配", "sheet_name": "账户管理分配", "columns": got}])
        assert hd.get_platform_tables(db, 9, "fb")[0]["columns"] == {"时区": "consumption"}
        db.close()

    def test_fb_legacy_flat_config_reads_as_one_table(self, client):
        """存量扁平 {spreadsheet_id, sheet_name, columns} ⇒ 一条 tables，name 取该表名。"""
        db = self._db()
        db.execute("INSERT OR REPLACE INTO config(key,value) VALUES('huguan_dashboard_9', ?)",
                   (json.dumps({"fb": {"spreadsheet_id": "SS1",
                                       "sheet_name": "账户管理分配",
                                       "columns": {"时区": "consumption"}}}),))
        db.commit()
        assert hd.get_platform_tables(db, 9, "fb") == [
            {"name": "账户管理分配", "sheet_name": "账户管理分配",
             "columns": {"时区": "consumption"}}]
        raw = db.execute("SELECT value FROM config WHERE key='huguan_dashboard_9'").fetchone()[0]
        assert json.loads(raw)["fb"] == {"spreadsheet_id": "SS1",
                                          "sheet_name": "账户管理分配",
                                          "columns": {"时区": "consumption"}}, \
            "读路径兜底不许改写磁盘（spec §4.3）"
        db.close()

    def test_fb_multi_table_read(self, client):
        db = self._db()
        hd.save_config(db, 9, "fb", "SS1", "", tables=[
            {"name": "加白户", "sheet_name": "加白户表"},
            {"name": "企业户", "sheet_name": "企业户表"}])
        assert [t["name"] for t in hd.get_platform_tables(db, 9, "fb")] == ["加白户", "企业户"]
        db.close()
```

> 删除 `test_fb_empty_columns_do_not_touch_the_stored_text`（它断言顶层 `columns` 不落盘的旧契约，B 之后 fb 走 `tables`，此契约不再适用）。

- [ ] **Step 2: 跑测试确认失败**

Run: `cd py && python -m pytest tests/test_huguan_dashboard.py -q -k TestPlatformTables`
Expected: FAIL —— `save_config` 对 fb 传 `tables` 抛 `ValueError("多账户表只支持 tt")` / `get_platform_tables("fb")` 返回空串名单表。

- [ ] **Step 3: `get_platform_tables` 多表化 fb**

把 `get_platform_tables` 的 fb 分支（当前约 695-700）整体替换为（tt 分支原样不动）：

```python
    if platform == "fb":
        # fb 与 tt 同形多表：每项 {name, sheet_name, columns}。name 只是表的人名标签，
        # 不参与路由（路由按 source_sheet 走，spec §4.2）；columns 是手工覆盖（表头映射）。
        tables = entry.get("tables")
        if isinstance(tables, list):
            out = []
            for t in tables:
                if not isinstance(t, dict):
                    continue
                name = _conf_text(t.get("name"))
                sheet_name = _conf_text(t.get("sheet_name"))
                if name and sheet_name:
                    cols = t.get("columns")
                    out.append({"name": name, "sheet_name": sheet_name,
                                "columns": cols if isinstance(cols, dict) else {}})
            if out:
                return out
        # 存量扁平配置 {spreadsheet_id, sheet_name, columns} ⇒ 当成一条 tables，
        # name 取该工作表名（spec §4.3）。**只读不改写磁盘**：写回发生在用户下次保存时。
        legacy = _conf_text(entry.get("sheet_name"))
        if legacy:
            cols = entry.get("columns")
            return [{"name": legacy, "sheet_name": legacy,
                     "columns": cols if isinstance(cols, dict) else {}}]
        return []
    return [{"name": "", "sheet_name": _conf_text(entry.get("sheet_name"))}]
```

并把函数 docstring 里「gg → … fb → 单元素列表、带 columns」那句改成「gg → 单元素列表、不带 columns；fb → 与 tt 同形多表（legacy 扁平配置兜成一条，name 取该表名）」。

- [ ] **Step 4: `save_config` 放开 fb**

把 `save_config` 的门控与 else 分支改为：

```python
    if platform not in PLATFORMS:
        raise ValueError(f"不支持的平台: {platform}")
    if tables is not None and platform not in ("tt", "fb"):
        raise ValueError(f"多账户表只支持 tt / fb，收到: {platform}")
    conf = load_config(db, user_id)
    if tables is None:
        conf[platform] = {
            "spreadsheet_id": _conf_text(spreadsheet_id),
            "sheet_name": _conf_text(sheet_name),
        }
        # 列映射覆盖（仅 fb；`{表头名: 字段key}`）。空 dict / None 都**不落盘** ——
        # 保持「没配 columns」时的配置文本与改动前逐字节一致（gg 永远走这一支）。
        if platform == "fb" and isinstance(columns, dict) and columns:
            conf[platform]["columns"] = dict(columns)
    else:
        clean = []
        for t in tables:
            name = _conf_text((t or {}).get("name"))
            sheet = _conf_text((t or {}).get("sheet_name"))
            if not name or not sheet:
                raise ValueError("每个户类型都需要「类型名」和「工作表名」")
            item = {"name": name, "sheet_name": sheet}
            cols = (t or {}).get("columns")
            if isinstance(cols, dict) and cols:
                item["columns"] = cols
            clean.append(item)
        # 改名级联**只对 tt**（spec §五）：fb 的户类型是数据驱动的（来自单元格），
        # 改名应该改表、不是改配置，也不改账户的 account_type。
        if platform == "tt":
            old_by_sheet = {t["sheet_name"]: t["name"] for t in get_platform_tables(db, user_id, "tt")}
            for new_t in clean:
                old_name = old_by_sheet.get(new_t["sheet_name"])
                if old_name and old_name != new_t["name"]:
                    db.execute("UPDATE tt_accounts SET account_type=? WHERE account_type=?",
                               (new_t["name"], old_name))
        conf[platform] = {
            "spreadsheet_id": _conf_text(spreadsheet_id),
            "tables": clean,
        }
    db.execute("INSERT OR REPLACE INTO config(key,value) VALUES(?,?)",
               (CONFIG_KEY.format(uid=user_id), json.dumps(conf, ensure_ascii=False)))
    db.commit()
```

并把 docstring 里「`tables` 非 None → 只允许 tt」改成「只允许 tt / fb」，补一句「fb 的 `tables` 不级联改名」。

- [ ] **Step 5: 跑测试确认通过**

Run: `cd py && python -m pytest tests/test_huguan_dashboard.py -q -k TestPlatformTables`
Expected: PASS（tt/gg 既有用例 + fb 新用例全绿）

- [ ] **Step 6: 跑全量回归**

Run: `cd py && python -m pytest tests/test_huguan_dashboard.py tests/test_fb_huguan_dashboard.py -q`
Expected: 全绿。**注意**：`test_fb_huguan_dashboard.py` 里若有用例断言「fb 同步按单表空串名」，本轮会红 —— 那属于契约变更，按新契约更新（这是 B 唯一允许动的既有 fb 断言；gg/tt 一个不许动）。

- [ ] **Step 7: 提交**

```bash
git add py/huguan_dashboard.py py/tests/test_huguan_dashboard.py py/tests/test_fb_huguan_dashboard.py
git commit -m "feat(fb-multi-sheet): FB 配置多表化 + legacy 兜底，save_config 放开 fb" -- py/huguan_dashboard.py py/tests/test_huguan_dashboard.py py/tests/test_fb_huguan_dashboard.py
```

---

## Task 4: 读路径 —— 同步路由逐表注入 `_account_type` / `_source_sheet`，`_collect_updates` / `_same_as_existing` 消费

**Files:**
- Modify: `py/routes/huguan_dashboard_routes.py`（`dashboard_sync` 的逐行解析循环，当前约 285-297）
- Modify: `py/huguan_dashboard.py`（`_collect_updates` 当前约 1462-1463、`_same_as_existing` 当前约 1516-1520）
- Test: `py/tests/test_huguan_dashboard.py`（新增 `TestFbMultiSheetReadPath` 类）

**Interfaces:**
- Consumes: Task 1 的列、Task 2 的分表键、`parse_row` 产出的 `asset_type_name`
- Produces:
  - 同步路由对 fb 行注入 `parsed["_account_type"] = 该行「资产类型」单元格原串`、`parsed["_source_sheet"] = t["sheet_name"]`
  - `_collect_updates` 对 fb 产出 `out["_account_type"]` / `out["_source_sheet"]`
  - `_same_as_existing` 对 `_account_type` / `_source_sheet` 两个键「本次产出为空 ⇒ 无变化」

- [ ] **Step 1: 写失败测试**

在 `py/tests/test_huguan_dashboard.py` 追加：

```python
class TestFbMultiSheetReadPath:
    """fb 读路径：逐行注入两个合成键 + 空产出不算变（spec §4.4 / §4.9）。"""

    def _seed_user(self):
        db = database.get_db()
        db.execute("INSERT OR IGNORE INTO users(id, username, password, role, platform) "
                   "VALUES(1, 'fb_ms_u', 'x', 'user', 'fb')")
        db.commit()
        return db

    def test_collect_updates_produces_both_keys_for_fb(self):
        db = self._seed_user()
        # p 模拟 parse_row 产出：asset_type_name 是「资产类型」单元格原串
        p = {"account_id": "MS-1", "asset_type_name": "企业户",
             "_account_type": "企业户", "_source_sheet": "企业户表"}
        out = hd._collect_updates(db, "fb", p, None, 2, [])
        assert out["_account_type"] == "企业户"
        assert out["_source_sheet"] == "企业户表"
        db.close()

    def test_same_as_existing_empty_value_means_no_change(self):
        """§4.9 的坑：库里 account_type 非空 + 本次产出空串 ⇒ 视为无变化（不进 to_update）。"""
        db = self._seed_user()
        existing = {"account_type": "企业户", "source_sheet": "企业户表"}
        assert hd._same_as_existing(db, "fb", existing, "_account_type", "") is True
        assert hd._same_as_existing(db, "fb", existing, "_source_sheet", "") is True
        # 非空但不同 ⇒ 才是真的「变了」
        assert hd._same_as_existing(db, "fb", existing, "_account_type", "加白户") is False
        db.close()

    def test_build_diff_empty_account_type_does_not_report_update(self):
        """库里分类非空 + 表里那格空着 ⇒ 该行**不进 to_update**（整份报告不虚报）。"""
        db = self._seed_user()
        db.execute("INSERT INTO fb_accounts(name, account_id, account_type, source_sheet, owner_id) "
                   "VALUES('户甲', 'MS-9', '企业户', '企业户表', 1)")
        db.commit()
        # 表里那格空着：_account_type 无条件产出空串（_source_sheet 恒为表名，非空）
        rows = [{"row": 2, "account_id": "MS-9", "asset_type_name": "",
                 "_account_type": "", "_source_sheet": "企业户表",
                 "owner_name": "", "status_name": "存活"}]
        diff = hd.build_diff(db, rows, "fb")
        assert not any(u["account_id"] == "MS-9" for u in diff["to_update"]), \
            "空产出必须视为无变化，否则整份报告虚报「将更新」"
        db.close()
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd py && python -m pytest tests/test_huguan_dashboard.py -q -k TestFbMultiSheetReadPath`
Expected: FAIL —— `out["_source_sheet"]` 不存在 / `_same_as_existing` 对空值判成「变了」/ `build_diff` 产出 to_update。

- [ ] **Step 3: `_collect_updates` 对 fb 产出两键**

`py/huguan_dashboard.py` 的 `_collect_updates`，把 tt 分支那段（当前约 1462-1463）后面加 fb 分支：

```python
    if platform == "tt":
        out["_account_type"] = _conf_text(p.get("_account_type"))
        out["_sheet_name"] = _conf_text(p.get("name"))
    if platform == "fb":
        # 户类型 + 来源表（spec §4.4）：两个键都**无条件产出**（值缺失时空串），理由同 tt 的
        # _account_type —— 缺键会让已存账户被判成「变了」⇒ 整行虚报「将更新」。
        # account_type 是「资产类型」单元格原串（不是表名、不是配置里的 name）；
        # source_sheet 是「读自哪张工作表」。
        out["_account_type"] = _conf_text(p.get("_account_type"))
        out["_source_sheet"] = _conf_text(p.get("_source_sheet"))
```

并把 docstring 里「`_account_type`（TT 专有…）」「`_sheet_name`（TT 专有…）」那句更新为：`_account_type`（tt/fb，调用方注入的户类型，fb 是「资产类型」原串）、`_source_sheet`（fb 专有，读自哪张表）、`_sheet_name`（tt 专有）。

- [ ] **Step 4: `_same_as_existing` 空产出视为无变化**

把 `_same_as_existing` 里 `if key == "_account_type":` 那段（当前约 1516-1520）替换为：

```python
    if key in ("_account_type", "_source_sheet"):
        # 合成键：库里对应的是真实列 account_type / source_sheet。不加这一支会落到下面的
        # 通用比较，拿 existing["_account_type"]（不存在 → None）去比 → 恒判「变了」，
        # 于是每次同步都把每一行报成「将更新」。
        # **空值视为无变化**（spec §4.9）：fb 的 account_type 来自表里「资产类型」单元格、
        # source_sheet 来自「读自哪张表」，两者在 §4.4 都**无条件产出**（缺失时空串），
        # 而 apply_diff 的更新口径是「只在非空时写」。若拿空串去比库里非空值，库里是
        # 「企业户」+ 本次表里那格空着 ⇒ 恒判「变了」⇒ 整份报告虚报「将更新」。
        # tt 的 _account_type 恒非空（表名即类型名），加「空 ⇒ 无变化」不影响 tt（逐字节不变）。
        col = "account_type" if key == "_account_type" else "source_sheet"
        if _conf_text(value) == "":
            return True
        return _conf_text(existing.get(col)) == _conf_text(value)
```

- [ ] **Step 5: 同步路由注入两键**

`py/routes/huguan_dashboard_routes.py` 的 `dashboard_sync` 逐行解析循环（当前约 291-296），在 `if platform == "tt":` 之后加 fb 分支：

```python
                if platform == "tt":
                    # 户类型的来源：这一行是从哪张表读出来的。表名即类型名。
                    parsed["_account_type"] = t["name"]
                if platform == "fb":
                    # 户类型 = 该行「资产类型」单元格原串（不是表名、不是配置里的 name，spec §4.4）。
                    # 资产类型列在 COLUMN_SPEC 里的字段key 是 asset_type_name，parse_row 已产出原串。
                    parsed["_account_type"] = hd._conf_text(parsed.get("asset_type_name"))
                    # 回写路由 = 读自哪张工作表（source_sheet），与户类型解耦（spec §4.2）。
                    parsed["_source_sheet"] = t["sheet_name"]
```

- [ ] **Step 6: 跑测试确认通过**

Run: `cd py && python -m pytest tests/test_huguan_dashboard.py -q -k TestFbMultiSheetReadPath`
Expected: PASS

- [ ] **Step 7: 跑全量回归**

Run: `cd py && python -m pytest tests/test_huguan_dashboard.py tests/test_fb_huguan_dashboard.py tests/test_huguan_undo.py -q`
Expected: 全绿（tt 的 `_account_type` 判据加了「空 ⇒ 无变化」，但 tt 恒非空 ⇒ 逐字节不变）

- [ ] **Step 8: 提交**

```bash
git add py/huguan_dashboard.py py/routes/huguan_dashboard_routes.py py/tests/test_huguan_dashboard.py
git commit -m "feat(fb-multi-sheet): fb 读路径注入 _account_type/_source_sheet，空产出视为无变化" -- py/huguan_dashboard.py py/routes/huguan_dashboard_routes.py py/tests/test_huguan_dashboard.py
```

---

## Task 5: 落库 —— `apply_diff` 消费两个新键

**Files:**
- Modify: `py/huguan_dashboard.py`（`apply_diff` 的 create 分支当前约 1773-1800、update 分支当前约 1857-1862）
- Test: `py/tests/test_huguan_dashboard.py`（新增 `TestFbAccountTypeFlow` 类）

**Interfaces:**
- Consumes: Task 4 的 `_account_type` / `_source_sheet`
- Produces: `apply_diff` 对 fb 新建写 `account_type`（原串，可空）与 `source_sheet`；更新时两键**只在非空时写**

- [ ] **Step 1: 写失败测试**

在 `py/tests/test_huguan_dashboard.py` 追加：

```python
class TestFbAccountTypeFlow:
    """fb 的 account_type / source_sheet 落库（spec §4.5）。"""

    def _seed_user(self):
        db = database.get_db()
        db.execute("INSERT OR IGNORE INTO users(id, username, password, role, platform) "
                   "VALUES(1, 'fb_atf_u', 'x', 'user', 'fb')")
        db.commit()
        return db

    def test_create_writes_both_keys(self):
        db = self._seed_user()
        rows = [{"row": 2, "_account_type": "企业户", "_source_sheet": "企业户表",
                 "account_id": "ATF-1", "owner_name": "", "status_name": "存活"}]
        diff = hd.build_diff(db, rows, "fb")
        assert diff["to_create"][0]["db_values"]["_account_type"] == "企业户"
        assert diff["to_create"][0]["db_values"]["_source_sheet"] == "企业户表"
        result = hd.apply_diff(db, diff, "fb", {"create": ["ATF-1"]}, user_id=1)
        assert result["created"] == 1
        r = db.execute("SELECT account_type, source_sheet FROM fb_accounts WHERE account_id='ATF-1'").fetchone()
        assert (r["account_type"], r["source_sheet"]) == ("企业户", "企业户表")
        db.close()

    def test_create_allows_empty_account_type(self):
        """fb 的 account_type 可空（表里那格空着）—— 不能回落成任何默认类型。"""
        db = self._seed_user()
        rows = [{"row": 2, "_account_type": "", "_source_sheet": "加白户表",
                 "account_id": "ATF-2", "owner_name": "", "status_name": "存活"}]
        diff = hd.build_diff(db, rows, "fb")
        hd.apply_diff(db, diff, "fb", {"create": ["ATF-2"]}, user_id=1)
        r = db.execute("SELECT account_type FROM fb_accounts WHERE account_id='ATF-2'").fetchone()
        assert r["account_type"] == "", "fb 空资产类型不能回落成 TT 的默认「加白户」"
        db.close()

    def test_update_only_writes_non_empty_keys(self):
        """表里那格空着 ⇒ 不擦掉已有分类（spec §4.5 空值不覆盖）。"""
        db = self._seed_user()
        db.execute("INSERT INTO fb_accounts(name, account_id, account_type, source_sheet, owner_id) "
                   "VALUES('户甲', 'ATF-3', '企业户', '企业户表', 1)")
        db.commit()
        rows = [{"row": 2, "_account_type": "", "_source_sheet": "企业户表",
                 "account_id": "ATF-3", "owner_name": "", "status_name": "存活"}]
        diff = hd.build_diff(db, rows, "fb")
        # §4.9：空 account_type 视为无变化 ⇒ 这一行根本不该进 to_update
        assert not any(u["account_id"] == "ATF-3" for u in diff["to_update"])
        db.close()
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd py && python -m pytest tests/test_huguan_dashboard.py -q -k TestFbAccountTypeFlow`
Expected: FAIL —— `db_values` 里没有 `_account_type` / `_source_sheet`（`_collect_updates` 尚未被 Task 4 扩到 fb，若 Task 4 已提交则只剩 `apply_diff` 落库失败：`no column named _account_type`）。

- [ ] **Step 3: create 分支**

`apply_diff` 的 create 分支，把 `account_type = src.pop("_account_type", None) if platform == "tt" else None`（当前约 1776）替换为：

```python
            # 户类型（spec §4.3 第 ④ 环）：合成键必须在拼 SQL 之前摘掉，否则会拼出
            # `INSERT INTO tt_accounts(..., _account_type)` 直接报错。
            # tt：account_type 存户类型名，空值回落默认「加白户」；fb：存「资产类型」原串
            #     （可空 —— 空 = 该行没填资产类型），另加 source_sheet（读自哪张表）。
            account_type = src.pop("_account_type", None) if platform in ("tt", "fb") else None
            source_sheet = src.pop("_source_sheet", None) if platform == "fb" else None
```

并在 `src["owner_id"] = item.get("owner_id")` 之后、`if account_type is not None:` 那段替换为：

```python
            if account_type is not None:
                # tt：空类型回落默认「加白户」；fb：account_type 是资产类型原串，空就是空，
                #     绝不回落 TT 的默认类型。
                src["account_type"] = account_type if platform == "fb" \
                    else (account_type or TT_DEFAULT_ACCOUNT_TYPE)
            if source_sheet is not None:
                src["source_sheet"] = source_sheet
```

- [ ] **Step 4: update 分支**

`apply_diff` 的 update 分支，把 `account_type = fields.pop("_account_type", None) if platform == "tt" else None`（当前约 1860）及其后的 `if account_type:` 替换为：

```python
            # 同 create：`sets = [f"{k}=?" for k in fields]` 会无条件把每个键拼进 SET，
            # 漏 pop 就是 `UPDATE fb_accounts SET _account_type=?` 直接报错。
            account_type = fields.pop("_account_type", None) if platform in ("tt", "fb") else None
            source_sheet = fields.pop("_source_sheet", None) if platform == "fb" else None
            # 只在非空时写（照 TT 对 account_type 的既有口径）：空值不覆盖，避免「表里那格
            # 空着」把已有分类擦掉（spec §4.5）。
            if account_type:
                fields["account_type"] = account_type
            if source_sheet:
                fields["source_sheet"] = source_sheet
```

- [ ] **Step 5: 跑测试确认通过**

Run: `cd py && python -m pytest tests/test_huguan_dashboard.py -q -k "TestFbAccountTypeFlow or TestAccountTypeFlow"`
Expected: PASS（`TestAccountTypeFlow` 是 TT 既有类，须仍全绿 —— 逐字节不变的第二道证据）

- [ ] **Step 6: 跑全量回归**

Run: `cd py && python -m pytest tests/test_huguan_dashboard.py tests/test_fb_huguan_dashboard.py tests/test_huguan_undo.py -q`
Expected: 全绿

- [ ] **Step 7: 提交**

```bash
git add py/huguan_dashboard.py py/tests/test_huguan_dashboard.py
git commit -m "feat(fb-multi-sheet): apply_diff 消费 account_type/source_sheet（新建写、更新非空才写）" -- py/huguan_dashboard.py py/tests/test_huguan_dashboard.py
```

---

## Task 6: 写路径路由 —— `_resolve_account_table` 按平台取键 + `huguan_dashboard_sync` 的 col_map 键

**Files:**
- Modify: `py/routes/huguan_sheet_targets.py`（`_resolve_account_table` 当前约 21-44、`huguan_dashboard_sync` 当前约 84）
- Test: `py/tests/test_huguan_sheet_write.py`（追加）

**Interfaces:**
- Consumes: Task 2 的 `_table_key_of`、Task 1 的 `source_sheet` 列
- Produces: `_resolve_account_table(db, user_id, platform, account_id)` 对 fb 读 `fb_accounts.source_sheet` 并按 `t["sheet_name"]` 命中；`huguan_dashboard_sync` 的 `col_maps_by_type` 键按 `_table_key_of` 取

- [ ] **Step 1: 写失败测试**

追加到 `py/tests/test_huguan_sheet_write.py`（该文件已有 `_sync_env` / fb 夹具可参考，按既有风格写）：

```python
class TestFbResolveAccountTableBySourceSheet:
    def _seed(self):
        db = database.get_db()
        db.execute("INSERT OR IGNORE INTO users(id, username, password, role, platform) "
                   "VALUES(1, 'fb_rat_u', 'x', 'user', 'fb')")
        db.execute("INSERT INTO fb_accounts(name, account_id, account_type, source_sheet, owner_id) "
                   "VALUES('户甲', 'RAT-1', '企业户', '企业户表', 1)")
        db.execute("INSERT OR REPLACE INTO config(key,value) VALUES('huguan_dashboard_1', ?)",
                   (json.dumps({"fb": {"spreadsheet_id": "SS", "tables": [
                       {"name": "加白户", "sheet_name": "加白户表"},
                       {"name": "企业户", "sheet_name": "企业户表"}]}}),))
        db.commit()
        return db

    def test_resolve_account_table_uses_source_sheet_for_fb(self):
        import routes.huguan_sheet_targets as hst
        db = self._seed()
        t = hst._resolve_account_table(db, 1, "fb", "RAT-1")
        assert t["sheet_name"] == "企业户表", "fb 必须按 source_sheet 命中，不是按 t['name']"
        db.close()

    def test_resolve_account_table_returns_none_when_sheet_missing(self):
        """source_sheet 指向配置里没有的表 ⇒ None，调用方跳过 + warning，绝不写第一张表。"""
        import routes.huguan_sheet_targets as hst
        db = self._seed()
        db.execute("UPDATE fb_accounts SET source_sheet='已删除的表' WHERE account_id='RAT-1'")
        db.commit()
        assert hst._resolve_account_table(db, 1, "fb", "RAT-1") is None
        db.close()
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd py && python -m pytest tests/test_huguan_sheet_write.py -q -k TestFbResolveAccountTableBySourceSheet`
Expected: FAIL —— `_resolve_account_table` 对 fb 恒走空串命中（`name==""` 已不存在 ⇒ 返回 None 或命中错表）。

- [ ] **Step 3: `_resolve_account_table` 按平台取键**

整体替换 `_resolve_account_table`（`py/routes/huguan_sheet_targets.py`）：

```python
def _resolve_account_table(db, user_id, platform, account_id):
    """按账户的**分表键**解析它该写哪张 worksheet 的配置项（`{name, sheet_name, columns}`）。

    解析不到 → 返回 None，由调用方决定「跳过」还是「报失败」。
    分表键按平台取（spec §4.2）：tt 读 tt_accounts.account_type（对 t["name"]）；
    fb 读 fb_accounts.source_sheet（对 t["sheet_name"]）；gg 恒空串、命中唯一空名条目，
    行为与改动前（单表）等价。

    返回**整项**而不只是工作表名：写表前要按该表的 `columns`（手工覆盖）解析 col_map，
    读路径用的是同一份配置（`get_platform_tables` 的同一项），读写必须同源。
    """
    import huguan_dashboard as hd

    tables = hd.get_platform_tables(db, user_id, platform)
    if not tables:
        return None
    key = ""
    if platform == "tt":
        r = db.execute("SELECT account_type FROM tt_accounts WHERE advertiser_id=?",
                       (account_id,)).fetchone()
        key = (r["account_type"] if r else "") or ""
    elif platform == "fb":
        r = db.execute("SELECT source_sheet FROM fb_accounts WHERE account_id=?",
                       (account_id,)).fetchone()
        key = (r["source_sheet"] if r else "") or ""
    for t in tables:
        if hd._table_key_of(platform, t) == key:
            return t
    return None
```

- [ ] **Step 4: `huguan_dashboard_sync` 的 col_map 字典键按平台取**

`huguan_dashboard_sync` 里 `col_maps_by_type = {t["name"]: col_map_by_sheet[t["sheet_name"]] for t in tables}`（当前约 84）改为：

```python
        col_maps_by_type = {hd._table_key_of(platform, t): col_map_by_sheet[t["sheet_name"]]
                            for t in tables}
```

> 对 tt 这是 `t["name"]`（逐字节不变）；对 fb 是 `t["sheet_name"]`，与 `collect_rows_for_push` 里 `_sheet_key_of("fb", row)=source_sheet` 的查找键对齐。

- [ ] **Step 5: 跑测试确认通过**

Run: `cd py && python -m pytest tests/test_huguan_sheet_write.py -q -k TestFbResolveAccountTableBySourceSheet`
Expected: PASS

- [ ] **Step 6: 跑全量回归**

Run: `cd py && python -m pytest tests/test_huguan_sheet_write.py tests/test_huguan_dashboard.py tests/test_huguan_undo.py -q`
Expected: 全绿

- [ ] **Step 7: 提交**

```bash
git add py/routes/huguan_sheet_targets.py py/tests/test_huguan_sheet_write.py
git commit -m "feat(fb-multi-sheet): 写路径选表按 source_sheet（_resolve_account_table + col_map 键）" -- py/routes/huguan_sheet_targets.py py/tests/test_huguan_sheet_write.py
```

---

## Task 7: 撤回按表 —— `undo_push` 配置门放开 fb + `sheet_back_sheets` 已用 `_sheet`（即 source_sheet）

> **说明**：`dashboard_sync` 已把 `parsed["_sheet"] = t["sheet_name"]`，撤回快照的 `sheet_back_sheets` 走 `_conf_text(p.get("_sheet"))`（`huguan_dashboard_routes.py` 当前约 353-363），对 fb 而言 `_sheet` 就是 source_sheet —— 这一环**已经正确**。本任务只需补 `undo_push` 里「fb 也有多表 ⇒ conf["sheet_name"] 恒空」的配置门，以及按表快照只含那一张表的回归测试。

**Files:**
- Modify: `py/huguan_dashboard.py`（`undo_push` 的配置门，当前约 2585-2591）
- Test: `py/tests/test_huguan_undo.py`（追加）

**Interfaces:**
- Consumes: Task 3 的多表配置（fb 的 `conf["sheet_name"]` 恒空）
- Produces: `undo_push` 对 fb 多表不再因 `conf["sheet_name"]` 为空而静默返回全零

- [ ] **Step 1: 写失败测试**

追加到 `py/tests/test_huguan_undo.py`（该文件已有 fb undo 夹具，按既有风格写）：

```python
def test_undo_push_works_for_fb_multi_table(monkeypatch):
    """fb 多表配置下 conf['sheet_name'] 恒空 —— undo_push 不许因此静默返回全零。"""
    import huguan_dashboard as hd
    db = database.get_db()
    db.execute("INSERT OR IGNORE INTO users(id, username, password, role, platform) "
               "VALUES(1, 'fb_undo_u', 'x', 'user', 'fb')")
    db.execute("INSERT OR REPLACE INTO config(key,value) VALUES('huguan_dashboard_1', ?)",
               (json.dumps({"fb": {"spreadsheet_id": "SS", "tables": [
                   {"name": "加白户", "sheet_name": "加白户表"}]}}),))
    # 造一份 push 快照：覆盖一张表里的一个账户
    hd.save_undo(db, 1, "fb", "push",
                 {"spreadsheet_id": "SS",
                  "sheets": [{"sheet_name": "加白户表",
                              "cells": [{"account_id": "U-1", "cells": {"D": "旧值"}}]}]})
    db.commit()
    db.close()

    # 写回打桩：确认 undo_push 真的走了写表（而不是被配置门拦下返回全零）
    import google_sheets_service as gs
    calls = []
    monkeypatch.setattr(gs, "build_service", lambda p: object())
    monkeypatch.setattr(gs, "update_rows_by_account_id",
                        lambda svc, sid, name, rows, key_col: calls.append((name, rows)))
    out = hd.undo_push(1, "fb")
    assert calls, "fb 多表下 undo_push 必须真的写表，不能静默返回全零"
    assert calls[0][0] == "加白户表"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd py && python -m pytest tests/test_huguan_undo.py -q -k test_undo_push_works_for_fb_multi_table`
Expected: FAIL —— `conf["sheet_name"]` 为空 ⇒ 配置门 `(platform != "tt" and not conf["sheet_name"])` 触发，返回 `{"updated": 0, ...}`，`calls` 为空。

- [ ] **Step 3: 改 `undo_push` 配置门**

`undo_push` 里（当前约 2585-2591）：

```python
    db = _open_db()
    try:
        conf = get_platform_config(db, user_id, platform)
        tables = get_platform_tables(db, user_id, platform)
        # gg：只有一张表，工作表名仍在 conf 里 —— 判据与改动前逐字等价（表名为空时同样返回全零）。
        # tt / fb：工作表名在 tables 里，多表配置的 conf["sheet_name"] **恒为空串**，沿用旧判据
        # 会让撤回**静默变成空操作**。故只对 gg 保留 conf["sheet_name"] 判据。
        if not conf["spreadsheet_id"] or not tables or (platform == "gg" and not conf["sheet_name"]):
            return {"updated": 0, "not_found": []}
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd py && python -m pytest tests/test_huguan_undo.py -q -k test_undo_push_works_for_fb_multi_table`
Expected: PASS

- [ ] **Step 5: 跑全量回归**

Run: `cd py && python -m pytest tests/test_huguan_undo.py -q`
Expected: 全绿（tt 多表 undo 既有用例、gg/fb 单表 undo 用例均不动）

- [ ] **Step 6: 提交**

```bash
git add py/huguan_dashboard.py py/tests/test_huguan_undo.py
git commit -m "feat(fb-multi-sheet): fb 多表撤回 undo_push 不再被 conf[sheet_name] 空串拦死" -- py/huguan_dashboard.py py/tests/test_huguan_undo.py
```

---

## Task 8: 按表入口放开 —— `/sync` `/push` 门控 + `dashboard_push` 按表过滤 + `cross_sheet_notes` 平台键

> **依赖**：Task 1（`cross_sheet_notes` 的 SQL 要 SELECT `source_sheet`/`account_type` 列，必须先加列）。**顺序铁律：加列在前，放开在后。**

**Files:**
- Modify: `py/routes/huguan_dashboard_routes.py`（`dashboard_sync` 按表门 219、`dashboard_push` 配置门 499-501 + 按表门 506 + 目标过滤 508-538）
- Modify: `py/huguan_dashboard.py`（`cross_sheet_notes` 当前约 2287-2313）
- Test: `py/tests/test_huguan_dashboard.py`（追加）

**Interfaces:**
- Consumes: Task 2 的 `_sheet_key_of` / `_table_key_of` / `_SHEET_KEY_FIELD`
- Produces: `/sync` `/push` 的 `sheet_name` 对 fb 生效；`cross_sheet_notes` 按平台取分表键列（fb 用 `source_sheet`）

- [ ] **Step 1: 写失败测试**

追加到 `py/tests/test_huguan_dashboard.py`（参考既有 `TestMultiTableSync` / 按表用例的 `_create_user` / monkeypatch gs 风格）：

```python
class TestFbPerSheetEntry:
    """fb 按表导入/刷新入口放开 + cross_sheet_notes 不报错（spec §4.7 / §三.3 的哑弹）。"""

    def test_fb_sync_per_sheet_no_longer_400(self, client, monkeypatch):
        import google_sheets_service as gs
        hg, _ = _create_user(client, "_fps1", role="huguan")
        db = database.get_db()
        db.execute("INSERT OR REPLACE INTO config(key,value) VALUES(?,?)",
                   (f"huguan_dashboard_{_uid_of('_fps1')}", json.dumps({"fb": {
                       "spreadsheet_id": "SS", "tables": [
                           {"name": "加白户", "sheet_name": "加白户表"},
                           {"name": "企业户", "sheet_name": "企业户表"}]}})))
        db.commit(); db.close()
        monkeypatch.setattr(gs, "read_sheet_values",
                            lambda svc, sid, name, rng: [["资产UID", "资产类型"],
                                                          ["9001", "企业户"]])
        monkeypatch.setattr(gs, "build_service", lambda p: object())
        resp = client.post("/api/huguan/dashboard/sync", headers=hg,
                           json={"platform": "fb", "sheet_name": "企业户表", "dry_run": True})
        assert resp.status_code == 200, "fb 按表导入不再 400"
        # 且报告的 cross_sheet_notes 键存在（按表时追加）
        assert "cross_sheet_notes" in resp.get_json()["diff"]

    def test_cross_sheet_notes_uses_source_sheet_for_fb(self, client):
        """哑弹回归钉：放开按表后调 cross_sheet_notes 不报错，且按 source_sheet 比对。"""
        db = database.get_db()
        db.execute("INSERT OR IGNORE INTO users(id, username, password, role, platform) "
                   "VALUES(1, 'fb_csn_u', 'x', 'user', 'fb')")
        db.execute("INSERT INTO fb_accounts(name, account_id, account_type, source_sheet, owner_id) "
                   "VALUES('户甲', 'CSN-1', '企业户', '企业户表', 1)")
        db.commit()
        notes = hd.cross_sheet_notes(db, "fb", ["CSN-1"], "加白户表")
        db.close()
        assert notes["count"] == 1, "fb 应按 source_sheet 与本次表名比对（不是 account_type）"
        assert notes["notes"][0]["current_type"] == "企业户表"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd py && python -m pytest tests/test_huguan_dashboard.py -q -k "test_fb_sync_per_sheet_no_longer_400 or test_cross_sheet_notes_uses_source_sheet_for_fb"`
Expected: FAIL —— fb 按表返回 400「只有 TT 支持按表操作」/ `cross_sheet_notes` 拿 `account_type`（企业户）去比 `加白户表`。

- [ ] **Step 3: `/sync` 按表门放开 fb**

`dashboard_sync` 里 `if only_sheet and platform != "tt":`（当前约 219）改为：

```python
    if only_sheet and platform not in ("tt", "fb"):
        return err("只有 TT / FB 支持按表操作", 400)
```

并把上一行注释里「gg/fb 只有一张表」改成「gg 只有一张表，按表无意义；tt / fb 多表」。

- [ ] **Step 4: `/push` 配置门 + 按表门 + 按表过滤**

`dashboard_push` 里四处一起改：

配置门（当前约 499-501）：

```python
        if (not c["spreadsheet_id"] or not tables
                or (platform == "gg" and not c["sheet_name"])):
            return err("请先在设置页配置户管看板的表格 ID 与工作表名", 400)
```

> 注释里「gg/fb：判据里必须留着 c["sheet_name"]」改成「gg：判据里必须留着 c["sheet_name"]（tt / fb 的表名在 tables 里，conf["sheet_name"] 恒空串）」。

按表门 + 目标解析（当前约 505-515）：

```python
        only_sheet = str(data.get("sheet_name") or "").strip()
        if only_sheet and platform not in ("tt", "fb"):
            return err("只有 TT / FB 支持按表操作", 400)
        target = None
        if only_sheet:
            target = next((t for t in tables if t["sheet_name"] == only_sheet), None)
            if target is None:
                return err(f"工作表「{only_sheet}」不在你的看板配置里", 400)
```

目标表过滤 + col_map 键 + 行过滤（当前约 522-538）：

```python
        # 按表时只解析**目标表**的表头（省掉其它表的表头读 = 提速）；缺省＝全部表。
        target_tables = tables if target is None else [target]
        col_maps_by_sheet = {
            t["sheet_name"]: hd.resolve_table_col_map(
                service, c["spreadsheet_id"], t["sheet_name"], platform,
                t.get("columns") or {})
            for t in target_tables
        }
        col_maps_by_type = {hd._table_key_of(platform, t): col_maps_by_sheet[t["sheet_name"]]
                            for t in target_tables}
        rows = hd.collect_rows_for_push(db, platform, col_maps_by_type=col_maps_by_type)
        if target is not None:
            # 只留「分表键 == 目标表」的账户：写回的是**这张表**，别的表一个格都不碰。
            # tt：account_type == target["name"]；fb：source_sheet == target["sheet_name"]。
            rows = [r for r in rows
                    if hd._sheet_key_of(platform, r) == hd._table_key_of(platform, target)]
```

> 顺带删掉原 `target_type = target["name"]` 与 `col_maps_by_type` 里 `t["name"]` 那两处（已并入上面），以及后面「push 侧刻意不接 cross_sheet_notes」的注释里「account_type == 目标户类型」的说法更新为「按 `_sheet_key_of` 过滤」。

- [ ] **Step 5: `cross_sheet_notes` 按平台取键**

`py/huguan_dashboard.py` 的 `cross_sheet_notes`，把查询段改为按平台取分表键列，并把 docstring 更新：

```python
def cross_sheet_notes(db, platform: str, account_ids: list, sheet_name: str,
                      cap: int = 50) -> dict:
    """按表操作时的「跨表重复」提示（设计 §3.3）：这些账户**当前归属另一张表**。

    为什么只查库：读其它表会抵消按表操作带来的提速（与「只在该表内去重」的初衷冲突）。
    库里的**分表键**（tt 是 account_type、fb 是 source_sheet）就是「上一次同步时它来自
    哪张表」的记账，够用。

    判据：本次同步里出现的账户，其库里分表键非空且与本次表名不同。
    `count` 给总数（前端能说「共 N 个」），`notes` 最多 `cap` 条（防空表刷爆报告）。
    软删账户不计（`deleted_at IS NULL`，与 `collect_rows_for_push` 同口径）。
    """
    ids = [a for a in (account_ids or []) if a]
    if not ids:
        return {"count": 0, "notes": []}
    table = _TABLE_FOR_PLATFORM[platform]
    key_field = _SHEET_KEY_FIELD.get(platform) or "account_type"
    hits = []
    for part in chunk(ids):
        marks = ",".join("?" for _ in part)
        for r in db.execute(
                f"SELECT {ACCOUNT_KEY_FIELD[platform]} AS aid, {key_field} AS sheet_key "
                f"FROM {table} WHERE {ACCOUNT_KEY_FIELD[platform]} IN ({marks}) "
                "AND deleted_at IS NULL", tuple(part)).fetchall():
            cur = _conf_text(r["sheet_key"])
            if cur and cur != sheet_name:
                hits.append({"account_id": _conf_text(r["aid"]),
                             "current_type": cur, "this_sheet": sheet_name})
    return {"count": len(hits), "notes": hits[:cap]}
```

> 对 tt：`key_field = "account_type"`（与改动前逐字节相同）；对 fb：`key_field = "source_sheet"`（这才是正确的「跨表」判据）；对 gg：`_SHEET_KEY_FIELD.get("gg")` 为 None ⇒ `"account_type"`，但 gg 永不按表，不可达。

- [ ] **Step 6: 跑测试确认通过**

Run: `cd py && python -m pytest tests/test_huguan_dashboard.py -q -k "TestFbPerSheetEntry or test_fb_sync_per_sheet_no_longer_400 or test_cross_sheet_notes_uses_source_sheet_for_fb"`
Expected: PASS

- [ ] **Step 7: 跑全量回归**

Run: `cd py && python -m pytest tests/test_huguan_dashboard.py tests/test_huguan_undo.py tests/test_huguan_sheet_write.py tests/test_fb_huguan_dashboard.py -q`
Expected: 全绿（tt 按表用例、cross_sheet_notes 既有 tt 用例均不动）

- [ ] **Step 8: 提交**

```bash
git add py/huguan_dashboard.py py/routes/huguan_dashboard_routes.py py/tests/test_huguan_dashboard.py
git commit -m "feat(fb-multi-sheet): fb 按表入口放开 + cross_sheet_notes 按平台取键" -- py/huguan_dashboard.py py/routes/huguan_dashboard_routes.py py/tests/test_huguan_dashboard.py
```

---

## Task 9: 配置 GET/POST 形状 —— fb 从顶层 `columns` 改成 `tables[].columns`

**Files:**
- Modify: `py/routes/huguan_dashboard_routes.py`（`dashboard_config_get` 当前约 78-83、`dashboard_config_save` 当前约 111-179）
- Test: `py/tests/test_huguan_dashboard.py`（追加）

**Interfaces:**
- Consumes: Task 3 的 `get_platform_tables("fb")` / `save_config(tables=...)`
- Produces: `GET /api/huguan/dashboard` 的 `config.fb` 带 `tables`（保留 `fb_field_catalog`，**不再**带顶层 `columns`）；`POST /api/huguan/dashboard` 的 fb 载荷从顶层 `columns` 改成 `tables[]`（`tables[].columns` 白名单同 tt）；gg 载荷形状不变

- [ ] **Step 1: 写失败测试**

追加到 `py/tests/test_huguan_dashboard.py`（参考既有 `TestDashboardConfigMultiTable` / `TestFbColumnsPostValidation` 风格）：

```python
class TestFbConfigTablesShape:
    def _hg(self, client, username):
        hg, _ = _create_user(client, username, role="huguan")
        return hg

    def test_get_fb_returns_tables_and_catalog_not_top_level_columns(self, client):
        hg = self._hg(client, "_fbc1")
        client.post("/api/huguan/dashboard", headers=hg, json={
            "platform": "fb", "spreadsheet_id": "SS",
            "tables": [{"name": "加白户", "sheet_name": "加白户表", "columns": {"时区": "consumption"}},
                       {"name": "企业户", "sheet_name": "企业户表"}]})
        fb = client.get("/api/huguan/dashboard", headers=hg).get_json()["config"]["fb"]
        assert [t["name"] for t in fb["tables"]] == ["加白户", "企业户"]
        assert fb["tables"][0]["columns"] == {"时区": "consumption"}
        assert "columns" not in fb, "fb 不再有顶层 columns（迁移到 tables[].columns）"
        assert isinstance(fb["fb_field_catalog"], list), "fb_field_catalog 保留（列映射下拉还用它）"

    def test_post_fb_tables_columns_whitelist(self, client):
        """fb 的 tables[].columns 白名单按 fb 目录取，与 tt 同口径。"""
        hg = self._hg(client, "_fbc2")
        ok_resp = client.post("/api/huguan/dashboard", headers=hg, json={
            "platform": "fb", "spreadsheet_id": "SS",
            "tables": [{"name": "加白户", "sheet_name": "加白户表", "columns": {"时区": "consumption"}}]})
        assert ok_resp.status_code == 200
        bad_resp = client.post("/api/huguan/dashboard", headers=hg, json={
            "platform": "fb", "spreadsheet_id": "SS",
            "tables": [{"name": "加白户", "sheet_name": "加白户表",
                        "columns": {"某列": "不存在的字段"}}]})
        assert bad_resp.status_code == 400

    def test_gg_shape_unchanged(self, client):
        hg = self._hg(client, "_fbc3")
        client.post("/api/huguan/dashboard", headers=hg, json={
            "platform": "gg", "spreadsheet_id": "G1", "sheet_name": "看板"})
        gg = client.get("/api/huguan/dashboard", headers=hg).get_json()["config"]["gg"]
        assert gg == {"spreadsheet_id": "G1", "sheet_name": "看板"}
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd py && python -m pytest tests/test_huguan_dashboard.py -q -k TestFbConfigTablesShape`
Expected: FAIL —— fb 的 `tables` 键不存在 / 顶层 `columns` 仍在 / POST 带 `tables` 对 fb 返回 400「多账户表只支持 tt」。

- [ ] **Step 3: 改 GET**

`dashboard_config_get` 里 `elif p == "fb":` 那段（当前约 78-83）替换为：

```python
            elif p == "fb":
                # fb 与 tt 同形多表：回 `tables`（每项带 columns）。**不再回顶层 columns**
                # —— B 之后 fb 的列映射覆盖挂在 tables[].columns 上。`fb_field_catalog` 仍由
                # 下方 `if p in ("tt","fb")` 那段按平台回，列映射下拉的数据源不动。
                entry["tables"] = hd.get_platform_tables(db, uid, "fb")
                if entry["tables"] and entry["tables"][0]["sheet_name"]:
                    entry["sheet_name"] = entry["tables"][0]["sheet_name"]
```

> 保留 `sheet_name`（= `tables[0].sheet_name`）是为了兼容老前端只认顶层 `sheet_name` 的地方；gg 载荷形状不变。

- [ ] **Step 4: 改 POST**

`dashboard_config_save` 里：把「tables 只允许 tt」的门（当前约 115-116）放开到 fb，并把「fb 顶层 columns」那段（当前约 162-179）删掉。具体：

```python
    raw_tables = data.get("tables")
    tables = None
    if raw_tables is not None:
        if platform not in ("tt", "fb"):
            return err("多账户表只支持 tt / fb", 400)
        if not isinstance(raw_tables, list) or not raw_tables:
            return err("tables 必须是非空数组", 400)
        tables = []
        seen_names, seen_sheets = set(), set()
        for t in raw_tables:
            if not isinstance(t, dict):
                return err("tables 的每一项必须是对象", 400)
            name = str(t.get("name") or "").strip()
            sheet = str(t.get("sheet_name") or "").strip()
            if not name:
                return err("每个户类型都需要「类型名」", 400)
            if not sheet:
                return err(f"户类型「{name}」缺少工作表名", 400)
            if name in seen_names:
                return err(f"户类型「{name}」重复", 400)
            if sheet in seen_sheets:
                return err(f"工作表「{sheet}」被两个户类型共用", 400)
            seen_names.add(name)
            seen_sheets.add(sheet)
            cols = t.get("columns")
            if cols is not None:
                if not isinstance(cols, dict):
                    return err(f"户类型「{name}」的 columns 必须是对象", 400)
                seen_fields = set()
                for header, field in cols.items():
                    if isinstance(field, str) and field == "":
                        continue
                    if not isinstance(field, str) or field not in hd._catalog_fields(platform):
                        return err(f"列「{header}」指向了未知字段「{field}」", 400)
                    if field in seen_fields:
                        return err(f"字段「{field}」被两列同时指定", 400)
                    seen_fields.add(field)
            item = {"name": name, "sheet_name": sheet}
            if isinstance(cols, dict) and cols:
                item["columns"] = cols
            tables.append(item)
```

并删除 `fb_cols = data.get("columns")` 及其后的整段 fb 顶层 columns 校验；`hd.save_config(...)` 调用改成：

```python
        hd.save_config(db, get_uid(), platform, ss_id, sheet_name, tables=tables, columns=None)
```

> `columns=None` 保留参数位即可（fb 的 columns 现在只随 `tables` 走；gg 走 `tables=None` 单表路径）。

- [ ] **Step 5: 跑测试确认通过**

Run: `cd py && python -m pytest tests/test_huguan_dashboard.py -q -k "TestFbConfigTablesShape or TestDashboardConfigMultiTable or TestFbColumnsPostValidation"`
Expected: PASS（tt 的既有 POST 校验用例、gg 形状用例全绿）

- [ ] **Step 6: 跑全量回归**

Run: `cd py && python -m pytest tests/test_huguan_dashboard.py tests/test_fb_huguan_dashboard.py -q`
Expected: 全绿

- [ ] **Step 7: 提交**

```bash
git add py/routes/huguan_dashboard_routes.py py/tests/test_huguan_dashboard.py py/tests/test_fb_huguan_dashboard.py
git commit -m "feat(fb-multi-sheet): 配置 GET/POST 的 fb 形状改 tables[].columns（保留 fb_field_catalog）" -- py/routes/huguan_dashboard_routes.py py/tests/test_huguan_dashboard.py py/tests/test_fb_huguan_dashboard.py
```

---

## Task 10: 前端卡片 —— 放开对 fb 隐藏的四样 + 配置摊平/折回改 `tables`

**Files:**
- Modify: `frontend/src/utils/columnMapping.mjs`（`seedTables` / `flattenColumns`）
- Modify: `frontend/src/components/HuguanDashboardCard.vue`（四处隐藏 + 按钮文案 + tooltip）
- Test: `frontend/tests/fbMultiSheetSeed.test.mjs`（新建）

**Interfaces:**
- Consumes: Task 9 的后端 `config.fb.tables`
- Produces: `seedTables(conf, platform)` / `flattenColumns(platform, tables)` 对 fb 走 `tables`（多条）；卡片对 fb 显示户类型名输入、删除、按表两按钮、「＋ 新增户类型」

- [ ] **Step 1: 写失败测试（纯逻辑）**

新建 `frontend/tests/fbMultiSheetSeed.test.mjs`：

```js
// FB 多表配置 → 渲染用 tables 的摊平/折回（spec §4.3 / §4.7）。
// 运行：cd frontend && npm test
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { seedTables, flattenColumns } from '../src/utils/columnMapping.mjs'

test('fb：后端给 tables ⇒ 逐项复制（不再包成单条空名）', () => {
  const rows = seedTables(
    { spreadsheet_id: 'SS', tables: [
      { name: '加白户', sheet_name: '加白户表', columns: { 时区: 'consumption' } },
      { name: '企业户', sheet_name: '企业户表' }] }, 'fb')
  assert.deepEqual(rows, [
    { name: '加白户', sheet_name: '加白户表', columns: { 时区: 'consumption' } },
    { name: '企业户', sheet_name: '企业户表', columns: {} }])
})

test('fb：折回时产出 tables 数组（不再是扁平 sheet_name + columns）', () => {
  const tables = [
    { name: '加白户', sheet_name: '加白户表', columns: { 时区: 'consumption' } },
    { name: '企业户', sheet_name: '企业户表', columns: {} }]
  assert.deepEqual(flattenColumns('fb', tables),
    [{ name: '加白户', sheet_name: '加白户表', columns: { 时区: 'consumption' } },
     { name: '企业户', sheet_name: '企业户表' }])
})

test('fb：折回时过滤掉没填工作表名的空行', () => {
  const tables = [
    { name: '加白户', sheet_name: '加白户表', columns: {} },
    { name: '', sheet_name: '', columns: {} }]
  assert.deepEqual(flattenColumns('fb', tables),
    [{ name: '加白户', sheet_name: '加白户表' }])
})

test('tt：行为不变（逐项复制 + 折回仍是 tables）', () => {
  const src = [{ name: '加白户', sheet_name: 'S1', columns: { 日期: 'acquired_date' } }]
  assert.deepEqual(seedTables({ tables: src }, 'tt'),
    [{ name: '加白户', sheet_name: 'S1', columns: { 日期: 'acquired_date' } }])
})
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd frontend && npm test`
Expected: FAIL —— `seedTables` 对 fb 仍走「包成一条空名」分支（`flattenColumns('fb', ...)` 仍回扁平 `{sheet_name, columns}`）。

- [ ] **Step 3: 改 `columnMapping.mjs`**

`seedTables` 把 fb 分支改成走 `tables`；`flattenColumns` 把 fb 分支改成回 `tables` 数组：

```js
export function seedTables(conf, platform) {
  const c = conf || {}
  if (Array.isArray(c.tables)) {
    return c.tables.map(t => ({
      name: t.name || '',
      sheet_name: t.sheet_name || '',
      columns: (t.columns && typeof t.columns === 'object') ? { ...t.columns } : {},
    }))
  }
  if (platform === 'fb') {
    // legacy：后端仍未多表化的存量扁平配置（过渡态）⇒ 包成一条空名（向后兼容）
    return [{
      name: '',
      sheet_name: c.sheet_name || '',
      columns: (c.columns && typeof c.columns === 'object') ? { ...c.columns } : {},
    }]
  }
  return []
}

/** 渲染用的 tables → 后端的配置。fb 现在与 tt 一样回 tables 数组（spec §4.3）。
 *  空行（没填工作表名的）过滤掉；空 columns 不上送（保持配置文本与改动前一致）。 */
export function flattenColumns(platform, tables) {
  if (platform === 'fb') {
    return (tables || [])
      .map(t => {
        const item = { name: (t.name || '').trim(), sheet_name: (t.sheet_name || '').trim() }
        const cols = t.columns
        if (cols && typeof cols === 'object' && Object.keys(cols).length) item.columns = { ...cols }
        return item
      })
      .filter(t => t.name && t.sheet_name)
  }
  const t = (tables || [])[0] || {}
  const out = { sheet_name: (t.sheet_name || '').trim() }
  const cols = t.columns
  if (cols && typeof cols === 'object' && Object.keys(cols).length) out.columns = { ...cols }
  return out
}
```

- [ ] **Step 4: 改 `HuguanDashboardCard.vue`**

**四处放开**（把 `HD_PLATFORM === 'tt'` 改成 `HD_PLATFORM !== 'gg'`，即 tt/fb 都走）：
1. 户类型名输入（当前约 70）：`v-if="HD_PLATFORM === 'tt'"` → `v-if="HD_PLATFORM !== 'gg'"`
2. 删除按钮（当前约 76）：同上 `v-if="HD_PLATFORM === 'tt'"` → `v-if="HD_PLATFORM !== 'gg'"`
3. 按表两按钮（当前约 184）：`v-if="HD_PLATFORM === 'tt'"` → `v-if="HD_PLATFORM !== 'gg'"`
4. 「＋ 新增户类型」与空态提示（当前约 203-204）：`v-if="HD_PLATFORM === 'tt'"` → `v-if="HD_PLATFORM !== 'gg'"`
   并把空态文案里「至少要有『加白户』一条」改成分平台（fb 说「至少要有『账户管理分配』一条」）。

**平台级按钮文案 + tooltip**（当前约 986-995）把 fb 也纳入「全部导入 / 全部刷新」：

```js
const hdPushBtnLabel = (HD_PLATFORM === 'tt' || HD_PLATFORM === 'fb')
  ? '⬆️ 全部刷新' : '🔄 刷新到看板'
const hdSyncBtnLabel = (HD_PLATFORM === 'tt' || HD_PLATFORM === 'fb')
  ? '⬇️ 全部导入' : '⬇️ 从表同步到系统'
// tt / fb 的按表配置里所有填了工作表名的表名（按配置顺序）—— 给平台级按钮当 tooltip 用。
const hdPlatformTables = computed(() => (hdForm.value.tables || [])
  .map(t => ((t && t.sheet_name) || '').trim()).filter(Boolean))
// 空串 = 不挂 tooltip（gg、未配置、或一张表都没填）。挂上时两条 tooltip 不叠加。
const hdTablesTip = computed(() => ((HD_PLATFORM === 'tt' || HD_PLATFORM === 'fb')
  && hdConfigured.value && hdPlatformTables.value.length)
  ? `所有表：${hdPlatformTables.value.join('、')}` : '')
```

**`saveHdConfig` 的 fb 分支**（当前约 1683-1685）改成与 tt 同路：

```js
    if (HD_PLATFORM === 'tt' || HD_PLATFORM === 'fb') {
      const tables = hdForm.value.tables
        .map((t) => {
          const item = { name: (t.name || '').trim(), sheet_name: (t.sheet_name || '').trim() }
          const cols = t.columns
          if (cols && typeof cols === 'object' && Object.keys(cols).length) item.columns = { ...cols }
          return item
        })
        .filter(t => t.name && t.sheet_name)
      body.tables = tables
    } else {
      body.sheet_name = hdForm.value.sheet_name
    }
```

并把 `if (HD_PLATFORM === 'tt' && (!body.tables || !body.tables.length))` 的空表校验改成 `if ((HD_PLATFORM === 'tt' || HD_PLATFORM === 'fb') && ...)`。

> `hdConfigured`（当前约 972-982）的 fb 分支已经用 `hdForm.value.tables.some(t => (t.sheet_name || '').trim())`，fb 现在有了户类型名，改成与 tt 同款 `some(t => (t.name || '').trim() && (t.sheet_name || '').trim())`。

- [ ] **Step 5: 跑测试 + 构建**

Run: `cd frontend && npm test && npx vite build`
Expected: 全绿 + 构建成功（**不要**起 dev server）

- [ ] **Step 6: 提交**

```bash
git add frontend/src/utils/columnMapping.mjs frontend/src/components/HuguanDashboardCard.vue frontend/tests/fbMultiSheetSeed.test.mjs
git commit -m "feat(fb-multi-sheet): FB 卡片放开多表 UI（户类型名/删除/按表按钮/新增）+ 配置走 tables" -- frontend/src/utils/columnMapping.mjs frontend/src/components/HuguanDashboardCard.vue frontend/tests/fbMultiSheetSeed.test.mjs
```

---

## Task 11: 账户页 —— FB 列表 `account_type` 筛选 + 「户类型」列

**Files:**
- Modify: `py/routes/fb_routes.py`（`list_accounts` 当前约 461-532）
- Modify: `frontend/src/api/fb.js`（`listAccounts` 加 `paramsSerializer`）
- Modify: `frontend/src/constants/accountColumns.js`（`FB_ADS_COLUMNS` 加「户类型」列）
- Modify: `frontend/src/views/fb/FbAccountPanel.vue`（筛选按钮 + 状态）
- Test: `py/tests/test_fb_list_batch.py`（追加）

**Interfaces:**
- Consumes: Task 1 的 `account_type` 列
- Produces: `GET /api/fb/accounts/list` 接受 `account_types`（重复参数）+ 回 `type_counts`；前端「户类型」筛选按钮（选项 = 实际出现过的值去重）+ 「户类型」列

- [ ] **Step 1: 写失败测试**

追加到 `py/tests/test_fb_list_batch.py`：

```python
def test_list_filters_by_account_types(client, fb_headers):
    db = database.get_db()
    for name, atype in (('户甲', '企业户'), ('户乙', '企业户'), ('户丙', '加白户')):
        db.execute("INSERT INTO fb_accounts(name, account_id, account_type, owner_id) "
                   "SELECT ?, ?, ?, id FROM users WHERE username='fbuser'",
                   (name, f'{name}-ID', atype))
    db.commit(); db.close()

    data = client.get("/api/fb/accounts/list?account_types=企业户",
                      headers=fb_headers).get_json()
    assert data["total"] == 2
    assert data["type_counts"] == {"企业户": 2, "加白户": 1}

    data = client.get("/api/fb/accounts/list?account_types=加白户&account_types=企业户",
                      headers=fb_headers).get_json()
    assert data["total"] == 3
```

> `fb_headers` 按该文件既有的 fb 夹具名取（若名字不同，照抄文件里的建 header 方式）。

- [ ] **Step 2: 跑测试确认失败**

Run: `cd py && python -m pytest tests/test_fb_list_batch.py -q -k test_list_filters_by_account_types`
Expected: FAIL —— `KeyError: 'type_counts'`（响应没有该键，筛选参数被忽略）。

- [ ] **Step 3: 后端筛选 + `type_counts`**

`list_accounts` 在 `search = ...` 取参之后加：

```python
    account_types = [t.strip() for t in request.args.getlist("account_types") if t.strip()]
```

主查询 `if search:` 之后加（fb 的 account_type 是「资产类型」原串，空串就是没填，不折进任何默认桶）：

```python
    if account_types:
        marks = ",".join("?" for _ in account_types)
        where.append(f"a.account_type IN ({marks})")
        params += account_types
```

在 `status_filter` 那组 where 之后、`return` 之前，加 `type_counts`（口径与 `total` 同底，不含 `account_types` 自身，参照 TT 的 `status_counts` 做法）：

```python
    # 各户类型计数：基于主 where 去掉 account_types 自身（与 total/列表同底，含 search/bm/status/
    # owner）。fb 无「默认户类型」，空 account_type 的行不进任何桶（按钮上不显示「空」）。
    tc_where = list(where)
    tc_params = list(params)
    if account_types:
        # 从 tc_where 里摘掉 account_types 那条（IN ...）及其参数
        idx = tc_where.index(f"a.account_type IN ({','.join('?' for _ in account_types)})")
        tc_where.pop(idx)
        del tc_params[len(tc_params) - len(account_types):]
    type_counts = {}
    for r in db.execute(
        "SELECT a.account_type AS atype, COUNT(*) AS cnt FROM fb_accounts a "
        "WHERE " + (" AND ".join(tc_where) if tc_where else "1=1") + " GROUP BY a.account_type",
        tc_params
    ).fetchall():
        t = r["atype"] or ""
        if t:
            type_counts[t] = type_counts.get(t, 0) + r["cnt"]
```

并在 `return ok({...})` 里加 `'type_counts': type_counts`。

> ⚠️ 这段从 `where` 摘掉 `account_types` 的写法偏脆。更稳的写法是**显式再列一遍**计数用的 where（照 TT 的 `sc_where2` 风格），不共享主 `where` 列表。实现时优先用「显式重列」：

```python
    tc_where = ["a.deleted_at IS NULL"]
    tc_params = []
    if cross_user:
        if owner_filter:
            tc_where.append("a.owner_id = ?"); tc_params.append(owner_filter)
    else:
        tc_where.append("a.owner_id = ?"); tc_params.append(uid)
    if bm_filter:
        tc_where.append("a.id IN (SELECT account_id FROM fb_account_bm WHERE bm_id=?)")
        tc_params.append(bm_filter)
    if status_filter:
        tc_where.append("a.status_id = ?"); tc_params.append(status_filter)
    if search:
        tc_where.append("(a.name LIKE ? OR a.account_id LIKE ?)")
        tc_params.extend([f"%{search}%", f"%{search}%"])
    type_counts = {}
    for r in db.execute(
        "SELECT a.account_type AS atype, COUNT(*) AS cnt FROM fb_accounts a "
        "WHERE " + " AND ".join(tc_where) + " GROUP BY a.account_type", tc_params
    ).fetchall():
        t = r["atype"] or ""
        if t:
            type_counts[t] = type_counts.get(t, 0) + r["cnt"]
```

- [ ] **Step 4: 前端 API 加 `paramsSerializer`**

`frontend/src/api/fb.js` 的 `listAccounts` 改成（重复参数 `account_types` 需要 `indexes: null`，理由同 TT）：

```js
  listAccounts(params = {}) { return client.get('/fb/accounts/list', { params, paramsSerializer: { indexes: null } }) },
```

- [ ] **Step 5: 前端列 + 筛选按钮**

`frontend/src/constants/accountColumns.js` 的 `FB_ADS_COLUMNS` 在 `account_id` 之后加：

```js
  { key: 'account_type', prop: 'account_type', label: '户类型', width: 110 },
```

> 它是纯 prop 列，`FbAccountPanel.vue` 的 `v-else` 兜底会自动渲染，无需加显式分支。

`frontend/src/views/fb/FbAccountPanel.vue`：
- 状态（`search = ref('')` 附近）加：`const accountTypes = ref([])`、`const typeCounts = ref({})`。
- 筛选栏（当前约 40-46，在 `search` 与 `filterBm` 之间）加一排按钮：

```html
        <div style="display:flex;gap:8px;margin-bottom:8px;flex-wrap:wrap;align-items:center;">
          <el-button v-for="t in availableTypes" :key="t"
                     :type="accountTypes.includes(t) ? 'primary' : 'default'"
                     size="small" @click="toggleType(t)" style="font-weight:600;">
            {{ t }} {{ typeCounts[t] || 0 }}
          </el-button>
          <el-button v-if="accountTypes.length" size="small" type="info" plain
                     @click="clearTypes">展示全部</el-button>
        </div>
```

- `availableTypes`（放在 `optName` 附近）：

```js
// 户类型候选集 = 库里实际出现过的 account_type（计数 > 0），不是字典全量（spec §4.8）。
const availableTypes = computed(() => {
  const counted = Object.keys(typeCounts.value).filter(t => (typeCounts.value[t] || 0) > 0)
  return counted.sort((a, b) => (typeCounts.value[b] || 0) - (typeCounts.value[a] || 0))
})
function toggleType(name) {
  const i = accountTypes.value.indexOf(name)
  if (i >= 0) accountTypes.value.splice(i, 1)
  else accountTypes.value.push(name)
  page.value = 1
  loadData()
}
function clearTypes() { accountTypes.value = []; page.value = 1; loadData() }
```

- `loadData` 里加 `account_types` 参数与 `typeCounts` 回填：

```js
    if (accountTypes.value.length) p.account_types = accountTypes.value
    const res = await fbApi.listAccounts(p)
    items.value = res.items; total.value = res.total
    typeCounts.value = res.type_counts || {}
```

- [ ] **Step 6: 跑后端测试 + 前端构建**

Run: `cd py && python -m pytest tests/test_fb_list_batch.py -q && cd ../frontend && npm test && npx vite build`
Expected: 全绿 + 构建成功

- [ ] **Step 7: 提交**

```bash
git add py/routes/fb_routes.py py/tests/test_fb_list_batch.py frontend/src/api/fb.js frontend/src/constants/accountColumns.js frontend/src/views/fb/FbAccountPanel.vue
git commit -m "feat(fb-multi-sheet): FB 账户页加户类型筛选（实际出现过的值）+ 户类型列" -- py/routes/fb_routes.py py/tests/test_fb_list_batch.py frontend/src/api/fb.js frontend/src/constants/accountColumns.js frontend/src/views/fb/FbAccountPanel.vue
```

---

## Task 12: 收尾 —— 全量回归 + 端到端串表测试 + 验收清单

**Files:**
- Modify: `py/tests/test_huguan_dashboard.py`（端到端「两张表各一行、互不串」用例）
- Create: 无

- [ ] **Step 1: 端到端串表测试（spec §七 的核心锚）**

追加到 `py/tests/test_huguan_dashboard.py`：

```python
class TestFbTwoTableEndToEnd:
    """两张表各一行、刷新时互不串（spec §七 的核心锚）。"""

    def test_two_tables_write_back_to_own_sheet(self, monkeypatch):
        db = database.get_db()
        db.execute("INSERT OR IGNORE INTO users(id, username, password, role, platform) "
                   "VALUES(1, 'fb_e2e_u', 'x', 'user', 'fb')")
        db.execute("INSERT INTO fb_accounts(name, account_id, account_type, source_sheet, owner_id) "
                   "VALUES('户甲', 'E2E-1', '企业户', '企业户表', 1), "
                   "('户乙', 'E2E-2', '加白户', '加白户表', 1)")
        db.execute("INSERT OR REPLACE INTO config(key,value) VALUES('huguan_dashboard_1', ?)",
                   (json.dumps({"fb": {"spreadsheet_id": "SS", "tables": [
                       {"name": "加白户", "sheet_name": "加白户表"},
                       {"name": "企业户", "sheet_name": "企业户表"}]}}),))
        db.commit()

        # col_map 解析打桩：两张表都按「资产UID=D」的固定映射（简化，端到端只验证选表）
        monkeypatch.setattr(hd, "resolve_table_col_map",
                            lambda *a, **k: {"account_id": "D"})
        # 写表打桩：记录 (sheet_name, [account_id...])
        import google_sheets_service as gs
        writes = []
        monkeypatch.setattr(gs, "build_service", lambda p: object())
        monkeypatch.setattr(gs, "update_rows_by_account_id",
                            lambda svc, sid, name, rows, key_col: writes.append(
                                (name, [r["account_id"] for r in rows])))
        hd.push_rows(1, "fb")
        db.close()
        # push_rows 走 target 的整行重建（huguan_dashboard_sync），按 source_sheet 分表
        by_sheet = {}
        for name, rows in writes:
            by_sheet.setdefault(name, []).extend(rows)
        assert set(by_sheet.get("企业户表", [])) == {"E2E-1"}, "企业户表只能写 E2E-1"
        assert set(by_sheet.get("加白户表", [])) == {"E2E-2"}, "加白户表只能写 E2E-2"
```

> ⚠️ 该用例走 `push_rows` → `huguan_dashboard_sync`（整行重建），它内部会真读表头（`resolve_table_col_map`）与真调 `update_rows_by_account_id` —— 两处都已 monkeypatch。若发现 `push_rows` 走 `run_write_many` 后台线程导致打桩时序不稳，改测 `routes.huguan_sheet_targets.huguan_dashboard_sync(1, "fb", ["E2E-1","E2E-2"])` 直接调（同步、可断言）。

- [ ] **Step 2: 后端全量**

Run: `cd py && python -m pytest tests/ -q`
Expected: 全绿。把通过数与**改动前**的基线比较（基线：本次开工前跑一次记下来）。**任何一条从绿变红都必须先查清原因，不许改测试来让它变绿。**

- [ ] **Step 3: 前端全量 + 构建**

Run: `cd frontend && npm test && npx vite build`
Expected: 全绿 + 构建成功

- [ ] **Step 4: 三条锚的最终证据**

Run: `cd py && python -m pytest tests/test_huguan_dashboard.py tests/test_huguan_undo.py tests/test_huguan_sheet_write.py tests/test_fb_huguan_dashboard.py -q -k "TestSheetKeyAbstraction or TestGroupRowsBySheet or TestFbMultiSheetReadPath or TestFbAccountTypeFlow or TestFbTwoTableEndToEnd or TestFbPerSheetEntry or TestAccountTypeFlow"`
Expected: PASS。这就是「TT/GG 行为未变」+「fb 多表不串」的证据。

- [ ] **Step 5: 写验收清单（追加到本文件末尾，见下）**

- [ ] **Step 6: 提交（收尾改动）**

```bash
git add py/tests/test_huguan_dashboard.py docs/superpowers/plans/2026-10-11-fb-multi-sheet.md
git commit -m "docs(fb-multi-sheet): 收尾 —— 端到端串表测试 + 人工验收清单" -- py/tests/test_huguan_dashboard.py docs/superpowers/plans/2026-10-11-fb-multi-sheet.md
```

---

## 人工验收清单（全部由用户在浏览器里点，我不启动任何进程）

**前置**：`cd frontend && npm run build` → 重启 Flask。两步都由用户执行。**用测试表格**（要建第二张工作表、改表头）。

- [ ] **A. 存量配置兜底**：FB 卡片的「账户表」出现**一行**（老扁平配置兜成的那条，名字＝`账户管理分配`）
- [ ] **B. 新增第二张表**：点「＋ 新增户类型」加第二行（名字「企业户」→ 工作表选另一张）
- [ ] **C. 列映射互不影响**：两张表各自「读取表头」→ 各显示各自的列映射（**互不影响**）
- [ ] **D. 全部导入**：点平台级「⬇️ 全部导入」→ 报告里能看出两张表的行；「表」列出现且值正确
- [ ] **E. 按表导入**：点第二行的「⬇️ 导入这张表」→ 报告**只含那张表**、标题带表名、没有「表」列
- [ ] **F. 账户页户类型筛选**：账户页出现「户类型」筛选按钮，选项＝**实际出现过的资产类型值**；点一个 → 只剩那种账户
- [ ] **G. 户类型列**：账户表里新出现「户类型」列，值＝表里「资产类型」那一列的原文
- [ ] **H. 按表刷新**：点某一张表的「⬆️ 刷新回这张表」→ 只有那张表被写；另一张表的行**没被动过**
- [ ] **I. 跨表隔离**：在两张表里各放一个**同名资产UID**的账户 → 导入后按表刷新，**各自写回各自的表**（不许串）
- [ ] **J. 撤回**：撤回上一次按表操作 → 只影响那一张表
- [ ] **K. 单一真相的代价（显式验一次）**：在 Google 里把某行的「资产类型」改成新值 → 同步 → 账户页的分类跟着变
- [ ] **L. 空资产类型不擦分类**：把某行的「资产类型」清空 → 同步 → 账户页该账户的分类**不变**（不是被清掉）
- [ ] **M. GG / TT 回归**：GG 卡片完全没变；TT 的户类型筛选与按表按钮**行为不变**

---

## Self-Review 记录

**Spec 覆盖**：
- §4.1（数据模型）→ Task 1
- §4.2（分表键抽象，五处清点）→ Task 2（`_FB_ROW_SQL` / `group_rows_by_sheet` / `collect_rows_for_push` + `_sheet_key_of`/`_table_key_of`）、Task 6（`_resolve_account_table`）、Task 8（`dashboard_push` 过滤 + `cross_sheet_notes`）
- §4.3（配置形态与迁移）→ Task 3（读）、Task 9（GET/POST 形状）
- §4.4（读路径）→ Task 4
- §4.5（写路径）→ Task 5（落库）、Task 6（写路由选表）
- §4.6（撤回）→ Task 7
- §4.7（按表入口）→ Task 8、Task 10（前端放开）
- §4.8（账户页）→ Task 11
- §4.9（两份真相口径 / 空产出不算变）→ Task 4（`_same_as_existing`）+ Task 5（`apply_diff` 非空才写）
- §七（测试）→ Task 12 端到端 + 各任务内用例；「空串不算变」「source_sheet 指不到表 ⇒ 跳过」「配置兜底」各有专门用例
- §八（人工验收）→ 文末清单（A–M）

**占位符扫描**：无 `...` / `TBD` /「照 Task N」/「类似上面」。所有代码块为完整实现。

**类型一致性**：
- `_sheet_key_of(platform, row) -> str` / `_table_key_of(platform, table) -> str` 在 Task 2 定义，Task 6/8 消费，签名一致。
- `_SHEET_KEY_FIELD` 在 Task 2 定义，Task 8（`cross_sheet_notes`）消费，键名一致。
- 合成键 `_account_type` / `_source_sheet` 在 Task 4 路由注入 → `_collect_updates` 产出 → `_same_as_existing` 比对 → Task 5 `apply_diff` 消费，四处字段名一致。
- `collect_rows_for_push` 的 `col_maps_by_type` 参数**保留原名**（键的语义改为「分表键」，对 tt 仍是 `t["name"]`），避免破坏 `test_huguan_undo.py` 既有 `col_maps_by_type={"加白户": cm}` 关键字调用。

**顺序自检**：加列（Task 1）早于放开按表入口（Task 8）——`cross_sheet_notes` 的 SQL 要 SELECT `source_sheet`/`account_type`，Task 1 先补列，Task 8 再放开，哑弹不会炸。✓

**已知取舍**（供审查者核对）：
1. Task 8 把 `cross_sheet_notes` 从「恒查 account_type」改成「按 `_SHEET_KEY_FIELD` 取列」——spec §4.7 只要求「不报错」，但只加列不改列会让 fb 按表时把 `account_type`（资产类型）拿去和 `sheet_name` 比，产出**恒错**的跨表提示；改成按 `source_sheet` 比对才是正确口径（tt 逐字节不变）。
2. Task 3 删除了 `test_fb_empty_columns_do_not_touch_the_stored_text`——它断言「fb 顶层 columns 空 dict 不落盘」的旧契约，B 之后 fb 走 `tables[]`，此契约不存在。这是唯一删除的既有测试。
3. Task 10 的 `flattenColumns` 对 fb 返回 `tables` 数组（不再回扁平 `{sheet_name, columns}`），签名不变、tt/gg 行为不变。
