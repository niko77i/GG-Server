# TT 户类型与多账户表 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让 TT 户管看板的一个平台能配置多张账户表（加白户 / 企业户 / 以后更多），每张表对应一个「户类型」；账户带类型落库，读表按表打标、回写按标路由，前端加多选类型按钮。

**Architecture:** 配置存在既有的 `config.huguan_dashboard_<uid>` 里，TT 条目从「单表」扩成 `tables` 列表（GG/FB 旧格式一字节不改）。`tt_accounts` 加一列 `account_type`（存类型名）。类型经**合成键 `_account_type`** 沿 `_collect_updates → build_diff → apply_diff` 传递（照抄 `_is_dead` / `_primary_bm_name` 的既有惯例）。回写侧把待写行按 `account_type` 分组，分别写进各自的 worksheet。

**Tech Stack:** Python 3.11 / Flask / SQLite（原生 sqlite3）/ Vue 3 + Element Plus / pytest / Google Sheets API（测试里一律打桩）

设计依据：`docs/superpowers/specs/2026-10-08-tt-account-types-design.md`（下称"设计 §X"）

## Global Constraints

- **只做 TT**。GG / FB 的配置格式、DOM、后端路径必须**逐字节不变**；`get_platform_config()` 的签名与返回值也不许改。
- **纯增量原则**：不得因本次改动破坏任何既有功能。既有的 `recharge` / `recycle` / `accounts` 三个 sheet 映射 key 的**读取与消费路径一行不改**。
- **提交纪律**：只 `git add` 本任务明确列出的文件。**禁止 `git add -A` / `git add .`** —— 本工作区有并行会话，暂存别人的未跟踪文件可能造成坏提交。**禁止 `git push`**（用户按"一批改完才推"的节拍）。
- **测试命令**：本仓库无 pytest 配置文件。先在 Task 1 Step 2 里确认一条能跑通的调用口径（预期 `cd py && python -m pytest tests/<file> -q`；若报 `AttributeError: module 'py' has no attribute 'path'`，说明 cwd 的 `py/` 目录遮蔽了 pytest 依赖的同名包，改用仓库根目录 `python -m pytest py/tests/<file> -q`），确认后**全程固定使用同一口径**。
- **类型名文案**：默认类型名恒为 `加白户`；配置里另一个例子是 `企业户`。按钮顺序与默认勾选都按配置里的顺序。
- **类型名字即标识**：`tt_accounts.account_type` 存的是**类型名字符串**，不是 id。改类型名必须级联 `UPDATE`。
- **合成键一律以下划线开头**，且**必须在拼 SQL 之前 pop 掉**（`apply_diff` 的 update 分支会无条件把 `fields` 的每个键拼进 `SET`）。
- **后台写表失败只能记日志**：`push_rows` / `writeback_owner_channel` 跑在后台线程，没有回头路。类型查不到工作表时**跳过该组**，绝不退回写第一张表。

---

## 文件结构

| 文件 | 职责 | 本次改动 |
|---|---|---|
| `py/database.py` | 建表 + 列级迁移 | `_add_column_if_missing` 返回 bool；`tt_accounts.account_type` 列 + 一次性回填 |
| `py/huguan_dashboard.py` | 户管看板双向同步的**纯逻辑层**（不 import flask） | 配置读写、类型解析、`_account_type` 传递链、`sheet` 字段、回写分组、多表快照 |
| `py/routes/huguan_dashboard_routes.py` | 户管看板的 HTTP 入口 | 配置 GET/POST 多表、sync 逐表读 |
| `py/routes/tt_accounts_routes.py` | TT 账户 / 充值 / 回收 / 同步 | list 筛选与 `type_counts`、create/update/batch-create 的类型字段、sync-from-sheet 类型参数 |
| `py/routes/tt_routes.py` | TT 设置 | `tt_settings_save` 分档授权（户管可写 recharge/recycle） |
| `frontend/src/components/HuguanDashboardCard.vue` | 户管看板卡片（GG/TT/FB 共用） | **只加 tt 分支**：多表列表 |
| `frontend/src/views/tt/TtSettingsPanel.vue` | TT 设置页 | 通用 sheet 卡片对户管放开 + 按角色渲染 |
| `frontend/src/views/tt/TtAccountPanel.vue` | TT 账户面板 | 户类型多选按钮组 |
| `frontend/src/components/tt/TtAccountModal.vue` | 建户/编辑弹窗 | 户类型下拉 |
| `frontend/src/components/tt/TtAccountBatchImportModal.vue` | 批量导入弹窗 | 批次公共表单加户类型下拉 |
| `frontend/src/components/tt/TtAccountSyncModal.vue` | 投手看板同步弹窗 | 户类型下拉 + 报告带表名 |
| `frontend/src/constants/accountColumns.js` | 列注册表 | 新增「户类型」列 |

---

## Task 1: 数据库列 + 一次性回填

**Files:**
- Modify: `py/database.py:109-115`（`_add_column_if_missing`）、`py/database.py:210-213`（`tt_accounts` 迁移区）
- Test: `py/tests/test_tt_platform.py`（追加）

**Interfaces:**
- Consumes: 无
- Produces: `_add_column_if_missing(conn, table, col_name, col_def) -> bool`（`True` = 本次真的加了列）；`tt_accounts.account_type TEXT DEFAULT ''`

- [ ] **Step 1: 写失败测试**

追加到 `py/tests/test_tt_platform.py` 末尾（该文件已有 `_fresh_schema_conn()` 与 `_pre_migration` 风格的 helper；若 helper 名字不同，照抄文件里既有的建连方式）：

```python
def test_tt_accounts_has_account_type_column():
    conn = _fresh_schema_conn()
    cols = {r[1] for r in conn.execute("PRAGMA table_info(tt_accounts)").fetchall()}
    assert "account_type" in cols
    conn.close()


def test_add_column_if_missing_returns_whether_added():
    """返回值必须区分「加了」与「本来就有」——回填只在前者执行。"""
    conn = _fresh_schema_conn()
    assert database._add_column_if_missing(
        conn, "tt_accounts", "account_type", "account_type TEXT DEFAULT ''") is False
    assert database._add_column_if_missing(
        conn, "tt_accounts", "_tmp_probe", "_tmp_probe TEXT DEFAULT ''") is True
    conn.close()


def test_account_type_backfill_happens_once():
    """存量行回填成加白户；**列已存在时不再覆盖**（否则户管改名会被打回）。"""
    conn = _fresh_schema_conn()
    conn.execute("INSERT INTO tt_accounts(name, advertiser_id) VALUES('a','111')")
    conn.execute("UPDATE tt_accounts SET account_type='' WHERE advertiser_id='111'")
    conn.commit()
    # 再跑一次列迁移：列已存在 ⇒ 不得回填
    database._ensure_columns(conn)
    got = conn.execute(
        "SELECT account_type FROM tt_accounts WHERE advertiser_id='111'").fetchone()[0]
    assert got == "", f"列已存在时不该覆盖，实际={got!r}"
    conn.close()
```

- [ ] **Step 2: 确认测试命令口径并跑失败测试**

Run（先用这个；报 `module 'py' has no attribute 'path'` 就换仓库根目录口径）：
```bash
cd py && python -m pytest tests/test_tt_platform.py -q -k "account_type or add_column_if_missing"
```
Expected: FAIL —— `account_type` 不在列里、`_add_column_if_missing` 返回 `None`。
**把跑通的命令记下来，后面所有任务都用它。**

- [ ] **Step 3: 改 `_add_column_if_missing` 返回 bool**

`py/database.py:109-115`，整体替换：

```python
def _add_column_if_missing(conn: sqlite3.Connection, table: str, col_name: str, col_def: str) -> bool:
    """仅在列不存在时添加。如果表不存在则跳过。

    返回「本次是否真的新增了该列」。既有调用方全部忽略返回值，故是纯增量改动；
    需要「只在首次建列时做一次性数据迁移」的调用方（见 tt_accounts.account_type）
    靠这个布尔值区分「刚建出来」与「本来就有」——后者绝不能重复执行迁移。
    """
    if not _table_exists(conn, table):
        return False
    cols = [r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()]
    if col_name not in cols:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {col_def}")
        return True
    return False
```

- [ ] **Step 4: 加列 + 一次性回填**

`py/database.py:210-213`，紧跟 `owner_change_note` 那条之后插入：

```python
    # TT 户类型（2026-10-08 规格 §4.1）：存**类型名字符串**（不是 id），查库直接可读。
    # 名字与配置里的 custom 表名一一对应，改名的级联 UPDATE 在
    # huguan_dashboard.save_config 里做。
    # ⚠️ 回填**只在列刚建出来的这一次**执行：_ensure_columns 每次连库都跑，
    #    无条件 UPDATE 会在户管改名 / 手工清值之后把它打回「加白户」。
    # ⚠️ 字面量「加白户」与 huguan_dashboard.TT_DEFAULT_ACCOUNT_TYPE 必须一致。
    if _add_column_if_missing(conn, "tt_accounts", "account_type",
                              "account_type TEXT DEFAULT ''"):
        conn.execute("UPDATE tt_accounts SET account_type='加白户' "
                     "WHERE account_type IS NULL OR account_type=''")
```

- [ ] **Step 5: 跑测试确认通过**

Run: `cd py && python -m pytest tests/test_tt_platform.py -q`
Expected: PASS（含本次 3 个新用例）

- [ ] **Step 6: 跑同族回归**

Run: `cd py && python -m pytest tests/test_tt_accounts.py tests/test_huguan_dashboard.py -q`
Expected: 全绿（`_add_column_if_missing` 改了签名，但既有调用方都忽略返回值）

- [ ] **Step 7: 提交**

```bash
git add py/database.py py/tests/test_tt_platform.py
git commit -m "feat(tt): tt_accounts 加 account_type 列 + 存量一次性回填加白户"
```

---

## Task 2: 配置层 —— 多表读写与类型解析

**Files:**
- Modify: `py/huguan_dashboard.py:180-236`（`load_config` / `_conf_text` / `get_platform_config` / `save_config`）
- Test: `py/tests/test_huguan_dashboard.py`（追加）

**Interfaces:**
- Consumes: Task 1 的 `account_type` 列
- Produces:
  - `TT_DEFAULT_ACCOUNT_TYPE = "加白户"`（模块常量）
  - `get_platform_tables(db, user_id, platform) -> list[dict]`，每项 `{"name": str, "sheet_name": str}`
  - `save_config(db, user_id, platform, spreadsheet_id, sheet_name, *, tables=None) -> None`
  - `_default_account_type(db, user_id) -> str`
  - `group_rows_by_sheet(db, user_id, platform, rows) -> (list[tuple[str, list]], list[str])`
  - `get_platform_config(...)` 签名与返回值**不变**

- [ ] **Step 1: 写失败测试**

追加到 `py/tests/test_huguan_dashboard.py`（该文件顶部已 `import database` / `import json`。新增需要 `huguan_dashboard` 模块本身，按文件既有 import 风格补 `import huguan_dashboard as hd`，若已有就直接用）：

```python
class TestPlatformTables:
    def _db(self):
        return database.get_db()

    def test_legacy_single_sheet_reads_as_one_table_named_白户(self):
        """存量 tt:{spreadsheet_id, sheet_name} → 单条「加白户」，且**不写盘**。"""
        db = self._db()
        db.execute("INSERT OR REPLACE INTO config(key,value) VALUES('huguan_dashboard_9', ?)",
                   (json.dumps({"tt": {"spreadsheet_id": "SS", "sheet_name": "总户"}}),))
        db.commit()
        tables = hd.get_platform_tables(db, 9, "tt")
        assert tables == [{"name": "加白户", "sheet_name": "总户"}]
        raw = db.execute("SELECT value FROM config WHERE key='huguan_dashboard_9'").fetchone()[0]
        assert json.loads(raw)["tt"] == {"spreadsheet_id": "SS", "sheet_name": "总户"}, \
            "读路径不许改写磁盘"
        db.close()

    def test_multi_table_read(self):
        db = self._db()
        db.execute("INSERT OR REPLACE INTO config(key,value) VALUES('huguan_dashboard_9', ?)",
                   (json.dumps({"tt": {"spreadsheet_id": "SS", "tables": [
                       {"name": "加白户", "sheet_name": "总户-加白"},
                       {"name": "企业户", "sheet_name": "总户-企业"}]}}),))
        db.commit()
        assert [t["name"] for t in hd.get_platform_tables(db, 9, "tt")] == ["加白户", "企业户"]
        db.close()

    def test_gg_and_fb_stay_single_element(self):
        db = self._db()
        db.execute("INSERT OR REPLACE INTO config(key,value) VALUES('huguan_dashboard_9', ?)",
                   (json.dumps({"gg": {"spreadsheet_id": "G", "sheet_name": "看板G"}}),))
        db.commit()
        assert hd.get_platform_tables(db, 9, "gg") == [{"name": "", "sheet_name": "看板G"}]
        assert hd.get_platform_config(db, 9, "gg") == {
            "spreadsheet_id": "G", "sheet_name": "看板G"}
        db.close()

    def test_save_legacy_signature_unchanged(self):
        """tables=None 时必须逐字节保持旧行为（gg/fb 走这条路）。"""
        db = self._db()
        hd.save_config(db, 9, "gg", "G1", "看板1")
        db.commit()
        assert hd.get_platform_config(db, 9, "gg") == {
            "spreadsheet_id": "G1", "sheet_name": "看板1"}
        db.close()

    def test_save_tables_writes_new_shape(self):
        db = self._db()
        hd.save_config(db, 9, "tt", "T1", "", tables=[
            {"name": "加白户", "sheet_name": "总户-加白"},
            {"name": "企业户", "sheet_name": "总户-企业"}])
        db.commit()
        assert [t["name"] for t in hd.get_platform_tables(db, 9, "tt")] == ["加白户", "企业户"]
        db.close()

    def test_save_tables_renames_and_cascades_to_accounts(self):
        """改名必须级联回填 tt_accounts.account_type，否则存量账户从按钮里消失。"""
        db = self._db()
        db.execute("INSERT INTO tt_accounts(name, advertiser_id, account_type) "
                   "VALUES('a','111','加白户')")
        db.execute("INSERT OR REPLACE INTO config(key,value) VALUES('huguan_dashboard_9', ?)",
                   (json.dumps({"tt": {"spreadsheet_id": "SS", "tables": [
                       {"name": "加白户", "sheet_name": "总户-加白"}]}}),))
        db.commit()
        hd.save_config(db, 9, "tt", "SS", "", tables=[
            {"name": "白户", "sheet_name": "总户-加白"}])
        db.commit()
        got = db.execute("SELECT account_type FROM tt_accounts WHERE advertiser_id='111'").fetchone()[0]
        assert got == "白户"
        db.close()

    def test_default_account_type_prefers_first_configured(self):
        db = self._db()
        assert hd._default_account_type(db, 9) == hd.TT_DEFAULT_ACCOUNT_TYPE
        db.execute("INSERT OR REPLACE INTO config(key,value) VALUES('huguan_dashboard_9', ?)",
                   (json.dumps({"tt": {"spreadsheet_id": "SS", "tables": [
                       {"name": "企业户", "sheet_name": "X"}]}}),))
        db.commit()
        assert hd._default_account_type(db, 9) == "企业户"
        db.close()


class TestGroupRowsBySheet:
    def test_tt_splits_by_type_and_skips_unknown(self):
        db = database.get_db()
        db.execute("INSERT OR REPLACE INTO config(key,value) VALUES('huguan_dashboard_7', ?)",
                   (json.dumps({"tt": {"spreadsheet_id": "SS", "tables": [
                       {"name": "加白户", "sheet_name": "总户-加白"}]}}),))
        db.commit()
        rows = [{"account_id": "1", "account_type": "加白户", "cells": {"A": "x"}},
                {"account_id": "2", "account_type": "企业户", "cells": {"A": "y"}}]
        groups, skipped = hd.group_rows_by_sheet(db, 7, "tt", rows)
        assert [(s, [r["account_id"] for r in rs]) for s, rs in groups] == [("总户-加白", ["1"])]
        assert skipped == ["企业户"], "查不到工作表的类型要报出来，绝不能落到第一张表"
        db.close()

    def test_gg_single_group(self):
        db = database.get_db()
        db.execute("INSERT OR REPLACE INTO config(key,value) VALUES('huguan_dashboard_7', ?)",
                   (json.dumps({"gg": {"spreadsheet_id": "S", "sheet_name": "看板"}}),))
        db.commit()
        rows = [{"account_id": "1", "cells": {"A": "x"}}]
        groups, skipped = hd.group_rows_by_sheet(db, 7, "gg", rows)
        assert groups == [("看板", rows)] and skipped == []
        db.close()
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd py && python -m pytest tests/test_huguan_dashboard.py -q -k TestPlatformTables`
Expected: FAIL —— `AttributeError: module 'huguan_dashboard' has no attribute 'get_platform_tables'`

- [ ] **Step 3: 实现**

在 `py/huguan_dashboard.py` 的 `CONFIG_KEY = "huguan_dashboard_{uid}"` 之后加常量：

```python
# 默认户类型名（2026-10-08 规格 §5）。只在「新建账户却没指定类型」时兜底，
# 与 database.py 里 account_type 回填用的字面量必须一致。
TT_DEFAULT_ACCOUNT_TYPE = "加白户"
```

在 `save_config` **之后**追加三个函数（`get_platform_config` 一字不改）：

```python
def get_platform_tables(db, user_id: int, platform: str) -> list:
    """取某平台的全部账户表：[{"name": 户类型名, "sheet_name": worksheet 名}]。

    - tt 配了 `tables` → 原样返回（保持配置顺序，顺序即按钮顺序与跨表去重的优先级）；
    - tt 只有旧的 `sheet_name`（2026-10-08 之前的存量配置）→ 当成单条「加白户」。
      **只读不改写磁盘**：写回发生在用户下次点保存时，这样出问题能一眼看出是读的还是写的。
    - gg / fb → 单元素列表，`name` 为空串。下游按 name 分组时只有一组，行为与改动前等价。
    """
    entry = load_config(db, user_id).get(platform)
    if not isinstance(entry, dict):
        entry = {}
    if platform == "tt":
        tables = entry.get("tables")
        if isinstance(tables, list):
            out = []
            for t in tables:
                if not isinstance(t, dict):
                    continue
                name = _conf_text(t.get("name"))
                sheet_name = _conf_text(t.get("sheet_name"))
                if name and sheet_name:
                    out.append({"name": name, "sheet_name": sheet_name})
            if out:
                return out
        legacy = _conf_text(entry.get("sheet_name"))
        return [{"name": TT_DEFAULT_ACCOUNT_TYPE, "sheet_name": legacy}] if legacy else []
    return [{"name": "", "sheet_name": _conf_text(entry.get("sheet_name"))}]


def _default_account_type(db, user_id: int) -> str:
    """新建账户未指定类型时的兜底：该用户自己配置里的第一条类型名，否则常量。

    取用户**自己的**配置而不是全局：类型清单本来就随户管看板配置私有存放（规格决策 2）。
    """
    tables = get_platform_tables(db, user_id, "tt")
    if tables and tables[0]["name"]:
        return tables[0]["name"]
    return TT_DEFAULT_ACCOUNT_TYPE
```

把 `save_config` 整体替换为（新增 `tables` 关键字参数 + 改名级联）：

```python
def save_config(db, user_id: int, platform: str, spreadsheet_id: str, sheet_name: str,
                *, tables=None) -> None:
    """写入某平台的看板配置，另一个平台的配置保持不变。

    `tables=None`（默认）→ 写旧格式 `{spreadsheet_id, sheet_name}`，行为与改动前**逐字节一致**
    （gg / fb 走这条路）。`tables` 非 None → 只允许 tt，写新格式
    `{spreadsheet_id, tables:[{name, sheet_name}]}`，并按类型名改名**级联**回填账户表。
    """
    if platform not in PLATFORMS:
        raise ValueError(f"不支持的平台: {platform}")
    if tables is not None and platform != "tt":
        raise ValueError(f"多账户表只支持 tt，收到: {platform}")
    conf = load_config(db, user_id)
    if tables is None:
        conf[platform] = {
            "spreadsheet_id": _conf_text(spreadsheet_id),
            "sheet_name": _conf_text(sheet_name),
        }
    else:
        clean = []
        for t in tables:
            name = _conf_text((t or {}).get("name"))
            sheet = _conf_text((t or {}).get("sheet_name"))
            if not name or not sheet:
                raise ValueError("每个户类型都需要「类型名」和「工作表名」")
            clean.append({"name": name, "sheet_name": sheet})
        # 旧类型名 → 新类型名：按**位置**比对（清单是同一个列表，位置即身份）。
        old_tables = get_platform_tables(db, user_id, "tt")
        for i, new_t in enumerate(clean):
            if i >= len(old_tables):
                break
            old_name = old_tables[i]["name"]
            if old_name and old_name != new_t["name"]:
                # 类型名字符串即标识（规格 §5）：不级联的话，存量账户会从按钮里凭空消失。
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

再追加 `group_rows_by_sheet`（回写分组是纯函数，放在配置层最合适 —— 同步路由、回写、撤回三处都要用它）：

```python
def group_rows_by_sheet(db, user_id: int, platform: str, rows: list):
    """把待写行按「户类型 → worksheet」分组。

    返回 `(groups, skipped)`：`groups` 是 `[(sheet_name, rows)]`（按配置顺序），
    `skipped` 是「在配置里查不到工作表的类型名」列表。

    查不到就**跳过**，绝不退回写第一张表 —— 那正是多表之后要消除的「填错表」。
    gg/fb 的类型恒为空串且配置里恰好有一个空名条目 ⇒ 只有一组，与改动前等价。
    """
    tables = get_platform_tables(db, user_id, platform)
    buckets = {}
    for r in rows:
        buckets.setdefault(r.get("account_type") or "", []).append(r)
    groups, skipped = [], []
    for t in tables:
        name = t["name"]
        if name in buckets:
            groups.append((t["sheet_name"], buckets.pop(name)))
    for leftover, leftover_rows in buckets.items():
        if leftover:
            skipped.append(leftover)
        elif tables:
            groups.append((tables[0]["sheet_name"], leftover_rows))
    return groups, skipped
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd py && python -m pytest tests/test_huguan_dashboard.py -q -k TestPlatformTables`
Expected: PASS

- [ ] **Step 5: 跑同族回归**

Run: `cd py && python -m pytest tests/test_huguan_dashboard.py -q`
Expected: 全绿（尤其 `TestDashboardConfig` 的 `test_save_then_get_roundtrip`）

- [ ] **Step 6: 提交**

```bash
git add py/huguan_dashboard.py py/tests/test_huguan_dashboard.py
git commit -m "feat(huguan): 户管看板配置支持 tt 多账户表 + 类型改名级联"
```

---

## Task 3: 配置 HTTP —— GET 合并 tables、POST 校验

**Files:**
- Modify: `py/routes/huguan_dashboard_routes.py:24-65`
- Test: `py/tests/test_huguan_dashboard.py`（追加）

**Interfaces:**
- Consumes: Task 2 的 `get_platform_tables` / `save_config(tables=...)`
- Produces:
  - `GET /api/huguan/dashboard` 的 `config.tt` 额外带 `tables`，同时**保留** `sheet_name`（= `tables[0].sheet_name`）
  - `POST /api/huguan/dashboard` 接受可选 `tables` 数组

- [ ] **Step 1: 写失败测试**

```python
class TestDashboardConfigMultiTable:
    def test_get_tt_carries_tables_and_legacy_sheet_name(self, client):
        hg, _ = _create_user(client, "_mt_cfg1", role="huguan")
        resp = client.post("/api/huguan/dashboard", headers=hg, json={
            "platform": "tt", "spreadsheet_id": "T1",
            "tables": [{"name": "加白户", "sheet_name": "总户-加白"},
                       {"name": "企业户", "sheet_name": "总户-企业"}]})
        assert resp.status_code == 200
        tt = client.get("/api/huguan/dashboard", headers=hg).get_json()["config"]["tt"]
        assert [t["name"] for t in tt["tables"]] == ["加白户", "企业户"]
        assert tt["sheet_name"] == "总户-加白", "老前端读 sheet_name 必须仍拿到值"

    def test_gg_get_shape_unchanged(self, client):
        hg, _ = _create_user(client, "_mt_cfg2", role="huguan")
        client.post("/api/huguan/dashboard", headers=hg, json={
            "platform": "gg", "spreadsheet_id": "G1", "sheet_name": "看板"})
        gg = client.get("/api/huguan/dashboard", headers=hg).get_json()["config"]["gg"]
        assert gg == {"spreadsheet_id": "G1", "sheet_name": "看板"}

    @pytest.mark.parametrize("tables", [
        [{"name": "", "sheet_name": "X"}],                       # 空类型名
        [{"name": "加白户", "sheet_name": ""}],                   # 空工作表名
        [{"name": "加白户", "sheet_name": "X"},
         {"name": "加白户", "sheet_name": "Y"}],                  # 类型名重复
        [{"name": "加白户", "sheet_name": "X"},
         {"name": "企业户", "sheet_name": "X"}],                  # 工作表重复
        [],                                                       # 空清单
    ])
    def test_post_rejects_bad_tables(self, client, tables):
        hg, _ = _create_user(client, "_mt_cfg3", role="huguan")
        resp = client.post("/api/huguan/dashboard", headers=hg, json={
            "platform": "tt", "spreadsheet_id": "T1", "tables": tables})
        assert resp.status_code == 400
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd py && python -m pytest tests/test_huguan_dashboard.py -q -k TestDashboardConfigMultiTable`
Expected: FAIL —— `tt["tables"]` 缺失 / 坏输入返回 200

- [ ] **Step 3: 改 GET**

`dashboard_config_get` 里那一行 `conf = {p: hd.get_platform_config(db, uid, p) for p in hd.PLATFORMS}`
替换为：

```python
        conf = {}
        for p in hd.PLATFORMS:
            entry = hd.get_platform_config(db, uid, p)
            if p == "tt":
                # tt 额外带 tables，但**保留 sheet_name**（= tables[0].sheet_name）——
                # 老前端只认 sheet_name，去掉它等于把它们打成空配置。
                # get_platform_config 自身的签名/返回值不动（gg/fb 与既有测试依赖它）。
                tables = hd.get_platform_tables(db, uid, "tt")
                entry["tables"] = tables
                if tables and tables[0]["sheet_name"]:
                    entry["sheet_name"] = tables[0]["sheet_name"]
            conf[p] = entry
```

- [ ] **Step 4: 改 POST**

`dashboard_config_save` 中 `sheet_name = str(data.get("sheet_name") or "").strip()`
之后、`db = database.get_db()` 之前插入解析与校验：

```python
    # tables 可选：给了就走多表（仅 tt），没给走旧单表路径（gg/fb 与老前端）。
    raw_tables = data.get("tables")
    tables = None
    if raw_tables is not None:
        if platform != "tt":
            return err("多账户表只支持 tt", 400)
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
            # 重名会让按钮和回写路由产生歧义；同一 worksheet 挂两个类型则回写会打两次架。
            if name in seen_names:
                return err(f"户类型「{name}」重复", 400)
            if sheet in seen_sheets:
                return err(f"工作表「{sheet}」被两个户类型共用", 400)
            seen_names.add(name)
            seen_sheets.add(sheet)
            tables.append({"name": name, "sheet_name": sheet})
```

请求体 `platform` 的校验（`if platform not in hd.PLATFORMS`）**保持在最前面不动** —— `tables` 那段必须排在它后面才安全。

`hd.save_config(...)` 那一行替换为：

```python
        hd.save_config(db, get_uid(), platform, ss_id, sheet_name, tables=tables)
```

- [ ] **Step 5: 跑测试确认通过**

Run: `cd py && python -m pytest tests/test_huguan_dashboard.py -q -k "TestDashboardConfig"`
Expected: PASS（新用例 + 既有 `TestDashboardConfig` 全绿）

- [ ] **Step 6: 提交**

```bash
git add py/routes/huguan_dashboard_routes.py py/tests/test_huguan_dashboard.py
git commit -m "feat(huguan): 看板配置 HTTP 支持 tt 多账户表（GET 兼容 sheet_name）"
```

---

## Task 4: `_account_type` 合成键传递链 + `sheet` 字段

**Files:**
- Modify: `py/huguan_dashboard.py:467-615`（`build_diff`）、`:617-673`（`_collect_updates`）、`:702-722`（`_same_as_existing`）、`:842-1175`（`apply_diff`）
- Test: `py/tests/test_huguan_dashboard.py`（追加）

**Interfaces:**
- Consumes: Task 2 的 `TT_DEFAULT_ACCOUNT_TYPE`
- Produces:
  - `parsed` 行上的合成键 `_account_type`（由**调用方/路由**注入）与 `_sheet`（表名，路由注入）
  - diff 的每一项（`to_create` / `to_update` / `owner_changes` / `to_skip` / `warnings`）新增 `sheet` 字段
  - `apply_diff` 的 `errors` 项新增 `sheet` 字段
  - `apply_diff` 在 tt 上写 `tt_accounts.account_type`

- [ ] **Step 1: 写失败测试**

```python
class TestAccountTypeFlow:
    def _seed_user(self):
        db = database.get_db()
        db.execute("INSERT OR IGNORE INTO users(id, username, password, role) "
                   "VALUES(1,'dev','x','developer')")
        db.commit()
        return db

    def test_create_row_carries_account_type_and_sheet(self):
        db = self._seed_user()
        rows = [{"row": 2, "_sheet": "总户-企业", "_account_type": "企业户",
                 "account_id": "9001", "owner_name": "", "status_name": "存活"}]
        diff = hd.build_diff(db, rows, "tt")
        assert diff["to_create"][0]["sheet"] == "总户-企业"
        assert diff["to_create"][0]["db_values"]["_account_type"] == "企业户"

        result = hd.apply_diff(db, diff, "tt", {"create": ["9001"]}, user_id=1)
        assert result["created"] == 1
        got = db.execute("SELECT account_type FROM tt_accounts WHERE advertiser_id='9001'").fetchone()[0]
        assert got == "企业户"
        db.close()

    def test_update_rewrites_type_and_does_not_error_on_synthetic_key(self):
        """回归：UPDATE 分支会把 fields 的每个键拼进 SET，漏 pop `_account_type` 直接报错。"""
        db = self._seed_user()
        db.execute("INSERT INTO tt_accounts(name, advertiser_id, account_type) "
                   "VALUES('a','9002','加白户')")
        db.commit()
        rows = [{"row": 2, "_sheet": "总户-企业", "_account_type": "企业户",
                 "account_id": "9002", "owner_name": "", "status_name": "存活"}]
        diff = hd.build_diff(db, rows, "tt")
        assert diff["to_update"][0]["fields"]["_account_type"] == "企业户"
        hd.apply_diff(db, diff, "tt", {"update": ["9002"]}, user_id=1)
        got = db.execute("SELECT account_type FROM tt_accounts WHERE advertiser_id='9002'").fetchone()[0]
        assert got == "企业户"
        db.close()

    def test_same_type_produces_no_update(self):
        db = self._seed_user()
        db.execute("INSERT INTO tt_accounts(name, advertiser_id, account_type) "
                   "VALUES('a','9003','加白户')")
        db.commit()
        rows = [{"row": 2, "_sheet": "总户-加白", "_account_type": "加白户",
                 "account_id": "9003", "owner_name": "", "status_name": "存活"}]
        diff = hd.build_diff(db, rows, "tt")
        assert not any(u["account_id"] == "9003" for u in diff["to_update"]), \
            "类型没变不该产出更新项（否则每次同步都报「将更新」）"
        db.close()

    def test_warnings_carry_sheet(self):
        db = self._seed_user()
        rows = [{"row": 5, "_sheet": "总户-企业", "_account_type": "企业户",
                 "account_id": "", "owner_name": "", "status_name": "存活"}]
        diff = hd.build_diff(db, rows, "tt")
        warn = [w for w in diff["warnings"] if w["row"] == 5][0]
        assert warn["sheet"] == "总户-企业"
        db.close()

    def test_gg_unaffected(self):
        """gg 的行没有 _account_type，创建路径一个字都不该多写。"""
        db = self._seed_user()
        rows = [{"row": 2, "_sheet": "", "account_id": "GG-1",
                 "owner_name": "", "status_name": "存活"}]
        diff = hd.build_diff(db, rows, "gg")
        assert "_account_type" not in diff["to_create"][0]["db_values"]
        hd.apply_diff(db, diff, "gg", {"create": ["GG-1"]}, user_id=1)
        cols = {r[1] for r in db.execute("PRAGMA table_info(accounts)").fetchall()}
        assert "account_type" not in cols, "gg 的账户表不该被加上这一列"
        db.close()
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd py && python -m pytest tests/test_huguan_dashboard.py -q -k TestAccountTypeFlow`
Expected: FAIL —— `KeyError: '_account_type'` 或 `sqlite3.OperationalError: no column named _account_type`

- [ ] **Step 3: `_collect_updates` 产出 `_account_type` + warning 带 sheet**

`_collect_updates` 末尾，把 `out["_is_dead"] = is_dead(p)` 改为：

```python
    out["_is_dead"] = is_dead(p)
    # 户类型的传递链第 ② 环（规格 §4.3）：`account_type` 不是表里的列，
    # 所以走合成键，与 `_primary_bm_name` 同形 —— 由调用方（同步路由）按
    # 「这一行是从哪张表读出来的」注入，这里原样搬运。
    # **不放进 _PLAIN_TEXT_FIELDS**：那个集合参与「文本列空着＝清空系统该列」的口径。
    if platform == "tt":
        out["_account_type"] = _conf_text(p.get("_account_type"))
    return out
```

同函数内**所有** `warnings.append({"row": row_no, "message": ...})` 改为：

```python
        warnings.append({"row": row_no, "sheet": _conf_text(p.get("_sheet")),
                         "message": f"{f}「{value}」无法唯一匹配，已跳过该列"})
```

（本函数只有这一处 warning。）

- [ ] **Step 4: `_same_as_existing` 加 `_account_type` 分支**

在 `_same_as_existing` 的 `if key == "_primary_bm_name":` 分支**之前**插入：

```python
    if key == "_account_type":
        # 合成键：库里对应的是真实列 account_type。不加这一支会落到下面的通用比较，
        # 拿 existing["_account_type"]（不存在 → None）去比 → 恒判「变了」，
        # 于是每次同步都把每一行报成「将更新」。
        return _conf_text(existing.get("account_type")) == _conf_text(value)
```

- [ ] **Step 5: `build_diff` 给产出项与 warning 加 `sheet`**

在 `build_diff` 开头的去重循环之前加一行局部 helper：

```python
    # 多表同步后「第 N 行」在两张表里会撞（规格 §4.3 的坑）：每个产出项都带表名，
    # 前端按表分组展示，否则户管会去改错表。
    def _sheet_of(p):
        return _conf_text(p.get("_sheet"))
```

然后把下面 6 处 append 各加一个 `"sheet"` 键（只加键，其余不动）：

1. 去重 warning：`warnings.append({"row": p.get("row"), "sheet": _sheet_of(p), "message": f"账户ID「{aid}」已在第 {seen_rows[aid]} 行出现，本行跳过"})`
2. 空 ID warning：`warnings.append({"row": row_no, "sheet": _sheet_of(p), "message": "账户ID为空，跳过"})`
3. 归属解析不到 warning：`warnings.append({"row": row_no, "sheet": _sheet_of(p), "message": f"运营「{want_owner_name}」无法识别，已跳过归属变更"})`
4. `to_create.append({...})`：在 `"row": row_no,` 后面加 `"sheet": _sheet_of(p),`
5. `to_update.append({...})`：在 `"row": row_no,` 后面加 `"sheet": _sheet_of(p),`
6. `owner_changes` / `to_skip` 的 append 同样在 `"row"` 后加 `"sheet": _sheet_of(p),`（在 `build_diff` 里搜 `"row": row_no`，每一处都加）

- [ ] **Step 6: `apply_diff` 消费 `_account_type`、errors 带 sheet**

**create 分支**，在 `fb_bm_name = src.pop(...)` 那一行**之后**插入：

```python
            # 户类型（规格 §4.3 第 ④ 环）：合成键必须在拼 SQL 之前摘掉，
            # 否则会拼出 `INSERT INTO tt_accounts(..., _account_type)` 直接报错。
            account_type = src.pop("_account_type", None) if platform == "tt" else None
```

并在 `src["owner_id"] = item.get("owner_id")` 之后插入：

```python
            if account_type is not None:
                src["account_type"] = account_type or TT_DEFAULT_ACCOUNT_TYPE
```

**update 分支**，在 `new_bm_name = fields.pop(...)` 那一行**之后**插入：

```python
            # 同 create：`sets = [f"{k}=?" for k in fields]` 会无条件把每个键拼进 SET，
            # 漏 pop 就是 `UPDATE tt_accounts SET _account_type=?` 直接报错。
            account_type = fields.pop("_account_type", None) if platform == "tt" else None
            if account_type:
                fields["account_type"] = account_type
```

**两处 `errors.append`**（create/update 各一处）改为带表名：

```python
            errors.append({"row": item["row"], "sheet": item.get("sheet", ""),
                           "error": "创建失败，详情见服务端日志"})
```
```python
            errors.append({"row": item["row"], "sheet": item.get("sheet", ""),
                           "error": "更新失败，详情见服务端日志"})
```

`owner_changes` 分支的 `errors.append` 同样加 `"sheet": item.get("sheet", "")`。

- [ ] **Step 7: 跑测试确认通过**

Run: `cd py && python -m pytest tests/test_huguan_dashboard.py -q -k TestAccountTypeFlow`
Expected: PASS

- [ ] **Step 8: 跑全量失败面回归**

Run: `cd py && python -m pytest tests/test_huguan_dashboard.py tests/test_huguan_undo.py tests/test_fb_huguan_dashboard.py tests/test_gg_sheet_write.py -q`
Expected: 全绿。**若既有用例断言 `warnings` / `diff` 项「恰好等于某个 dict」，加 `sheet` 键会让它红** —— 那是契约变更，按新契约更新那些断言（这是本次唯一允许动的既有断言）。

- [ ] **Step 9: 提交**

```bash
git add py/huguan_dashboard.py py/tests/test_huguan_dashboard.py
git commit -m "feat(huguan): _account_type 合成键传递链 + diff 产出带 sheet 表名"
```

---

## Task 5: 同步路由逐表读

**Files:**
- Modify: `py/routes/huguan_dashboard_routes.py:68-95`（`dashboard_sync` 的读表段）
- Test: `py/tests/test_huguan_dashboard.py`（追加）

**Interfaces:**
- Consumes: Task 2 `get_platform_tables`；Task 4 `_account_type` / `_sheet`
- Produces: 同步路由把「多张表各读一次」合并成一个 `parsed_rows` 列表

- [ ] **Step 1: 写失败测试**

```python
class TestMultiTableSync:
    def test_tt_reads_every_table_and_tags_rows(self, client, monkeypatch):
        hg, _ = _create_user(client, "_mts1", role="huguan")
        db = database.get_db()
        db.execute("INSERT OR REPLACE INTO config(key,value) VALUES(?,?)",
                   (f"huguan_dashboard_{_uid_of('_mts1')}", json.dumps({"tt": {
                       "spreadsheet_id": "SS", "tables": [
                           {"name": "加白户", "sheet_name": "总户-加白"},
                           {"name": "企业户", "sheet_name": "总户-企业"}]}})))
        db.commit()
        db.close()

        import google_sheets_service as gs
        reads = []
        tabs = {
            "总户-加白": [["入库时间", "是否回收", "账户ID"],
                          ["2026-10-01", "否", "8001"]],
            "总户-企业": [["入库时间", "是否回收", "账户ID"],
                          ["2026-10-02", "否", "8002"]],
        }

        def _read(svc, sheet_id, sheet_name, rng):
            reads.append(sheet_name)
            return tabs[sheet_name]

        monkeypatch.setattr(gs, "read_sheet_values", _read)
        monkeypatch.setattr(gs, "build_service", lambda path: object())

        resp = client.post("/api/huguan/dashboard/sync", headers=hg,
                           json={"platform": "tt", "dry_run": True})
        assert resp.status_code == 200
        assert reads == ["总户-加白", "总户-企业"], "必须按配置顺序逐张表读一次"
        created = {c["account_id"]: c for c in resp.get_json()["diff"]["to_create"]}
        assert created["8001"]["sheet"] == "总户-加白"
        assert created["8002"]["sheet"] == "总户-企业"

    def test_route_writeback_enriches_type_before_grouping(self, client, monkeypatch):
        """回归：归属变更的定向回写行**不带** account_type，路由必须现查补上，
        否则整批会落进「无类型」桶、被当成「查不到工作表」静默跳过。"""
        hg, _ = _create_user(client, "_mts4", role="huguan")
        db = database.get_db()
        db.execute("INSERT INTO tt_accounts(name, advertiser_id, account_type) "
                   "VALUES('a','8010','企业户')")
        db.execute("INSERT OR REPLACE INTO config(key,value) VALUES(?,?)",
                   (f"huguan_dashboard_{_uid_of('_mts4')}", json.dumps({"tt": {
                       "spreadsheet_id": "SS", "tables": [
                           {"name": "加白户", "sheet_name": "总户-加白"},
                           {"name": "企业户", "sheet_name": "总户-企业"}]}})))
        db.commit()

        import routes.huguan_dashboard_routes as hdr
        calls = []
        monkeypatch.setattr(hdr, "_write_background",
                            lambda conf, rows, platform: calls.append(
                                (conf["sheet_name"], [r["account_id"] for r in rows])))
        hdr._write_background_tables(db, _uid_of('_mts4'), "tt",
                                     [{"account_id": "8010", "cells": {"G": "张三"}}])
        db.close()
        assert calls == [("总户-企业", ["8010"])]

    def test_cross_table_duplicate_first_table_wins_with_warning(self, client, monkeypatch):
        hg, _ = _create_user(client, "_mts2", role="huguan")
        db = database.get_db()
        db.execute("INSERT OR REPLACE INTO config(key,value) VALUES(?,?)",
                   (f"huguan_dashboard_{_uid_of('_mts2')}", json.dumps({"tt": {
                       "spreadsheet_id": "SS", "tables": [
                           {"name": "加白户", "sheet_name": "A"},
                           {"name": "企业户", "sheet_name": "B"}]}})))
        db.commit()
        db.close()

        import google_sheets_service as gs
        hdr = ["入库时间", "是否回收", "账户ID"]
        tabs = {"A": [hdr, ["2026-10-01", "否", "8003"]],
                "B": [hdr, ["2026-10-02", "否", "8003"]]}
        monkeypatch.setattr(gs, "read_sheet_values",
                            lambda svc, sid, name, rng: tabs[name])
        monkeypatch.setattr(gs, "build_service", lambda path: object())

        diff = client.post("/api/huguan/dashboard/sync", headers=hg,
                           json={"platform": "tt", "dry_run": True}).get_json()["diff"]
        assert [c["account_id"] for c in diff["to_create"]] == ["8003"]
        assert diff["to_create"][0]["sheet"] == "A", "配置里靠前的那张表生效"
        assert any(w["sheet"] == "B" for w in diff["warnings"]), "warning 要指出被跳过的那张表"

    def test_gg_still_reads_once(self, client, monkeypatch):
        hg, _ = _create_user(client, "_mts3", role="huguan")
        db = database.get_db()
        db.execute("INSERT OR REPLACE INTO config(key,value) VALUES(?,?)",
                   (f"huguan_dashboard_{_uid_of('_mts3')}",
                    json.dumps({"gg": {"spreadsheet_id": "SS", "sheet_name": "看板G"}})))
        db.commit()
        db.close()
        import google_sheets_service as gs
        reads = []
        monkeypatch.setattr(gs, "read_sheet_values",
                            lambda svc, sid, name, rng: reads.append(name) or [])
        monkeypatch.setattr(gs, "build_service", lambda path: object())
        client.post("/api/huguan/dashboard/sync", headers=hg,
                    json={"platform": "gg", "dry_run": True})
        assert reads == ["看板G"]
```

在文件里补一个取 uid 的小 helper（若已有同名就复用）：

```python
def _uid_of(username):
    db = database.get_db()
    row = db.execute("SELECT id FROM users WHERE username=?", (username,)).fetchone()
    db.close()
    return row["id"]
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd py && python -m pytest tests/test_huguan_dashboard.py -q -k TestMultiTableSync`
Expected: FAIL —— 只读了第一张表 / `sheet` 键不存在

- [ ] **Step 3: 实现**

`dashboard_sync` 里从 `conf = hd.get_platform_config(...)` 到 `diff = hd.build_diff(...)` 这一整段替换为：

```python
        tables = hd.get_platform_tables(db, uid, platform)
        tables = [t for t in tables if t["sheet_name"]]
        if not tables:
            return err("请先在设置页配置户管看板的表格 ID 与工作表名", 400)

        import google_sheets_service as gs
        from main import _GOOGLE_SHEETS_CONFIG
        service = gs.build_service(_GOOGLE_SHEETS_CONFIG["credentials_path"])

        # 逐张表各读一次，再**合并成一个列表**进 build_diff —— 跨表去重、冲突检测、
        # 归属变更全部沿用既有逻辑，不另写一套。
        # 顺序即优先级：同一账户出现在两张表时，靠前的那张表先出现 ⇒ 现有
        # 「首次出现生效 + warning」规则自然让靠前的表胜出（规格 §4.3 跨表重复）。
        parsed_rows = []
        spreadsheet_id = _spreadsheet_id(db, uid, platform)
        for t in tables:
            grid = gs.read_sheet_values(service, spreadsheet_id,
                                        t["sheet_name"], hd.READ_RANGE[platform])
            # 第 1 行是表头；不跳任何数据行（户管看板没有「是否解绑」列可用作跳过标记）
            for i, values in enumerate(grid[1:], start=2):
                parsed = hd.parse_row(values, platform)
                parsed["row"] = i
                # 多表后「第 N 行」会撞：带上表名，前端按表分组展示（规格 §4.3 的坑）
                parsed["_sheet"] = t["sheet_name"]
                if platform == "tt":
                    # 户类型的来源：这一行是从哪张表读出来的。表名即类型名。
                    parsed["_account_type"] = t["name"]
                parsed_rows.append(parsed)

        diff = hd.build_diff(db, parsed_rows, platform)
```

在 `dashboard_sync` 之前补一个小 helper（避免在循环里重复取配置）：

```python
def _spreadsheet_id(db, uid: int, platform: str) -> str:
    return hd.get_platform_config(db, uid, platform)["spreadsheet_id"]
```

**同时**：删掉下方 `if not conf["spreadsheet_id"] or not conf["sheet_name"]:` 那条旧校验（已被 `if not tables` 取代），并在替换后的代码**之前**补一条表格 ID 校验：

```python
        if not _spreadsheet_id(db, uid, platform):
            return err("请先在设置页配置户管看板的表格 ID 与工作表名", 400)
```

**还要**：原代码里 `conf` 在后面还被 `_write_background(conf, rows, platform)` 用了三次（归属变更回写）。把这三处的 `conf` 换成一个小字典即可（`_write_background` 只读 `conf["spreadsheet_id"]` / `conf["sheet_name"]`，而 TT 现在多表、`_write_background` 必须按类型路由）：

```python
            _write_background_tables(db, uid, platform, rows)
```

并在本文件加：

```python
def _write_background_tables(db, uid: int, platform: str, rows) -> None:
    """定向写回（归属变更 / 备注等）也要按户类型落到各自的 worksheet。

    与 push_rows 的分组口径完全一致：查不到对应工作表的类型**跳过**，
    绝不退回写第一张表 —— 那正是本次要消除的「填错表」。

    ⚠️ 本函数的入参 rows 是 `[{"account_id", "cells"}]` 形状，**不带 `account_type`**
      —— 它不经过 `collect_rows_for_push`（那条路才带类型）。必须在这里按账户 ID
      现查一次类型补上，否则每一行都会落进「无类型」桶、被 `group_rows_by_sheet`
      当成「查不到工作表」整批跳过：表现是**归属变更静默不回写**，不报错、不抛异常。
    """
    rows = [dict(r) for r in rows]
    if platform == "tt" and rows:
        ids = [r["account_id"] for r in rows if r.get("account_id")]
        type_by_id = {}
        for part in hd.chunk(ids):
            marks = ",".join("?" for _ in part)
            for r in db.execute(
                    f"SELECT advertiser_id, account_type FROM tt_accounts "
                    f"WHERE advertiser_id IN ({marks})", tuple(part)).fetchall():
                type_by_id[r["advertiser_id"]] = r["account_type"] or ""
        for r in rows:
            r["account_type"] = type_by_id.get(r.get("account_id"), "")

    groups, skipped = hd.group_rows_by_sheet(db, uid, platform, rows)
    for t in skipped:
        log.warning("回写跳过：户类型「%s」查不到工作表 platform=%s", t, platform)
    spreadsheet_id = hd.get_platform_config(db, uid, platform)["spreadsheet_id"]
    for sheet_name, sheet_rows in groups:
        _write_background({"spreadsheet_id": spreadsheet_id, "sheet_name": sheet_name},
                          sheet_rows, platform)
```

（`hd.group_rows_by_sheet` 是 Task 2 的产物，本任务直接可用。）

- [ ] **Step 4: 跑测试确认通过**

Run: `cd py && python -m pytest tests/test_huguan_dashboard.py -q -k "TestMultiTableSync"`
Expected: PASS

- [ ] **Step 5: 跑同步全量回归**

Run: `cd py && python -m pytest tests/test_huguan_dashboard.py tests/test_fb_huguan_dashboard.py -q`
Expected: 全绿

- [ ] **Step 6: 提交**

```bash
git add py/routes/huguan_dashboard_routes.py py/tests/test_huguan_dashboard.py
git commit -m "feat(huguan): TT 同步逐张账户表读取并按表打户类型标记"
```

---

## Task 6: 回写按户类型分组

**Files:**
- Modify: `py/huguan_dashboard.py:1272-1327`（`_TT_ROW_SQL`）、`:1330-1362`（`collect_rows_for_push`）、`:1492-1526`（`push_rows`）、`:1801-1838`（`writeback_owner_channel`）
- Test: `py/tests/test_huguan_dashboard.py`（追加）

**Interfaces:**
- Consumes: Task 2 `get_platform_tables` / `group_rows_by_sheet`（**已在 Task 2 实现并测过，本任务不要重复实现**）
- Produces: `collect_rows_for_push` 产出的 row 带 `account_type`（仅 tt）；`push_rows` / `writeback_owner_channel` 按类型分表写

- [ ] **Step 1: 写失败测试**

```python
class TestPushRouting:
    def test_tt_rows_carry_account_type(self):
        db = database.get_db()
        db.execute("INSERT INTO tt_accounts(name, advertiser_id, account_type) "
                   "VALUES('a','7001','加白户'), ('b','7002','企业户')")
        db.commit()
        rows = hd.collect_rows_for_push(db, "tt")
        got = {r["account_id"]: r["account_type"] for r in rows}
        assert got == {"7001": "加白户", "7002": "企业户"}
        db.close()

    def test_push_rows_writes_each_sheet_separately(self, monkeypatch):
        """端到端：两条不同类型账户 → 两次写表调用，各写各的 worksheet。"""
        db = database.get_db()
        db.execute("INSERT INTO tt_accounts(name, advertiser_id, account_type) "
                   "VALUES('a','7001','加白户'), ('b','7002','企业户')")
        db.execute("INSERT OR REPLACE INTO config(key,value) VALUES('huguan_dashboard_7', ?)",
                   (json.dumps({"tt": {"spreadsheet_id": "SS", "tables": [
                       {"name": "加白户", "sheet_name": "总户-加白"},
                       {"name": "企业户", "sheet_name": "总户-企业"}]}}),))
        db.commit()
        db.close()

        captured = _stub_sheets(monkeypatch, [])
        hd.push_rows(7, "tt")
        assert {c["sheet_name"] for c in captured} == {"总户-加白", "总户-企业"}
        by_sheet = {c["sheet_name"]: [r["account_id"] for r in c["rows"]] for c in captured}
        assert by_sheet == {"总户-加白": ["7001"], "总户-企业": ["7002"]}
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd py && python -m pytest tests/test_huguan_dashboard.py -q -k TestPushRouting`
Expected: FAIL —— `KeyError: 'account_type'`（`collect_rows_for_push` 还没带出这一列）

- [ ] **Step 3: `_TT_ROW_SQL` 带出类型**

`_TT_ROW_SQL` 的 `SELECT` 列表里 `a.advertiser_id AS account_id,` 之后加 `a.account_type,`（注意：`account_type` 与 `account_id` 同名冲突不存在，直接用列名）：

```sql
_TT_ROW_SQL = """
SELECT a.advertiser_id AS account_id, a.account_type, a.acquired_date, a.death_date, a.country,
```

- [ ] **Step 4: `collect_rows_for_push` 带上类型**

把产出循环改为：

```python
    out = []
    for q_sql, q_params in queries:
        for r in db.execute(q_sql, q_params).fetchall():
            row = dict(r)
            item = {"account_id": str(row.get("account_id") or "").strip(),
                    "cells": cells_for_row(row, platform)}
            # 户类型只用于**路由**（决定写哪张 worksheet），不进 cells ——
            # cells 是「表列字母 → 单元格值」，没有类型这一列。
            # gg/fb 的 _ROW_SQL 没有这一列 ⇒ 取到空串，分组时只有一组，行为不变。
            item["account_type"] = row.get("account_type") or ""
            out.append(item)
    return [o for o in out if o["account_id"]]
```

- [ ] **Step 5: `push_rows` 用分组**

把 `push_rows` 的 `_do` 闭包替换为「按组分次写」：

```python
    db = _open_db()
    try:
        tables = get_platform_tables(db, user_id, platform)
        if not tables:
            return
        rows = collect_rows_for_push(db, platform, account_ids)
        groups, skipped = group_rows_by_sheet(db, user_id, platform, rows)
        spreadsheet_id = get_platform_config(db, user_id, platform)["spreadsheet_id"]
    finally:
        db.close()

    for name in skipped:
        log.warning("户管看板回写跳过：户类型「%s」在配置里查不到工作表 user=%s platform=%s",
                    name, user_id, platform)

    if not groups or not spreadsheet_id:
        return

    from main import _sync_sheets_background

    for sheet_name, sheet_rows in groups:
        if not sheet_rows:
            continue

        def _do(_sheet=sheet_name, _rows=sheet_rows):
            import google_sheets_service as gs
            from main import _GOOGLE_SHEETS_CONFIG
            service = gs.build_service(_GOOGLE_SHEETS_CONFIG["credentials_path"])
            # 定位列必须按平台取：写入器默认 "C"（GG/TT 的账户ID列），而 FB 的
            # 账户ID在 **D** 列（C 是「账户名称」）—— 不传就按错误的列定位、写空。
            gs.update_rows_by_account_id(service, spreadsheet_id, _sheet, _rows,
                                         key_col=KEY_COL[platform])

        _sync_sheets_background(
            _do, lambda s, e: log.warning("户管看板回写失败: %s", e) if e else None)
```

> ⚠️ 闭包必须用**默认参数**绑住 `sheet_name` / `sheet_rows`（写成 `def _do(_sheet=sheet_name, ...)`）—— 否则后台线程跑起来时循环早已结束，捕获的是最后一组，前面的组全写错表。这是本任务最容易犯的错。

- [ ] **Step 6: `writeback_owner_channel` 同样按类型路由**

把 `conf = get_platform_config(...)` 那段改为按账户类型取工作表：

```python
        db = _open_db()
        try:
            tables = get_platform_tables(db, user_id, platform)
            if not tables:
                return
            spreadsheet_id = get_platform_config(db, user_id, platform)["spreadsheet_id"]
            if not spreadsheet_id:
                return
            row = db.execute("SELECT COALESCE(NULLIF(display_name, ''), username, '') AS n, "
                             "a.account_type FROM users u WHERE 0")  # 占位，见下
            ...
```

**具体做法**（替换整段 `conf = ...` 与其后的取值）：查一次该账户的类型名，再在 `tables` 里找对应 worksheet：

```python
        db = _open_db()
        try:
            tables = get_platform_tables(db, user_id, platform)
            if not tables:
                return
            spreadsheet_id = get_platform_config(db, user_id, platform)["spreadsheet_id"]
            if not spreadsheet_id:
                return
            atype = ""
            if platform == "tt":
                r0 = db.execute("SELECT account_type FROM tt_accounts WHERE advertiser_id=?",
                                (account_id,)).fetchone()
                atype = (r0["account_type"] if r0 else "") or ""
            sheet_name = None
            for t in tables:
                if t["name"] == atype:
                    sheet_name = t["sheet_name"]
                    break
            if sheet_name is None:
                log.warning("归属变更通道列回写跳过：户类型「%s」查不到工作表 account=%s",
                            atype, account_id)
                return
            r = db.execute("SELECT COALESCE(NULLIF(display_name, ''), username, '') AS n "
                           "FROM users WHERE id=?", (new_owner_id,)).fetchone()
            name = (r["n"] if r else "").strip()
        finally:
            db.close()
```

并把后面 `conf["spreadsheet_id"]` / `conf["sheet_name"]` 两处换成 `spreadsheet_id` / `sheet_name`。

- [ ] **Step 7: 跑测试确认通过**

Run: `cd py && python -m pytest tests/test_huguan_dashboard.py -q -k "TestPushRouting"`
Expected: PASS

- [ ] **Step 8: 跑全量回归**

Run: `cd py && python -m pytest tests/test_huguan_dashboard.py tests/test_huguan_undo.py tests/test_fb_huguan_dashboard.py -q`
Expected: 全绿

- [ ] **Step 9: 提交**

```bash
git add py/huguan_dashboard.py py/tests/test_huguan_dashboard.py
git commit -m "feat(huguan): 回写按户类型分组，各写各的 worksheet"
```

---

## Task 7: 撤回快照支持多表

> ⚠️ **本任务必须在 Task 6 之前做**（Task 6 Step 8 已经按多表快照的签名调用）。

**Files:**
- Modify: `py/huguan_dashboard.py:1446-1490`（`snapshot_push_targets` / `push_undo_cells`）、`:1529-1579`（`undo_push`）
- Test: `py/tests/test_huguan_undo.py`

**Interfaces:**
- Consumes: Task 2 `group_rows_by_sheet`；Task 6 的分组口径
- Produces:
  - `snapshot_push_targets(service, conf, platform, groups) -> {"spreadsheet_id": str, "sheets": [{"sheet_name": str, "cells": list}]}`
  - `push_undo_cells(payload) -> list[{"sheet_name": str, "rows": list}]`
  - `undo_push` 逐表还原

- [ ] **Step 1: 写失败测试**

追加到 `py/tests/test_huguan_undo.py`（该文件已有打桩工具，按它的风格写）：

```python
def test_snapshot_and_undo_across_two_sheets(monkeypatch):
    import huguan_dashboard as hd
    import google_sheets_service as gs

    grids = {
        "总户-加白": [["", "", "8001"], ["", "", ""]],
        "总户-企业": [["", "", "8002"], ["", "", ""]],
    }

    def _read(svc, sid, name, rng):
        return grids[name]

    monkeypatch.setattr(hd, "read_sheet_values", _read)

    groups = [("总户-加白", [{"account_id": "8001", "cells": {"A": "x"}}]),
              ("总户-企业", [{"account_id": "8002", "cells": {"A": "y"}}])]
    snap = hd.snapshot_push_targets(object(), {"spreadsheet_id": "SS"}, "tt", groups)
    assert [s["sheet_name"] for s in snap["sheets"]] == ["总户-加白", "总户-企业"]
    assert push_undo_calls := hd.push_undo_cells(snap)
    assert [(c["sheet_name"], [r["account_id"] for r in c["rows"]]) for c in push_undo_calls] == \
        [("总户-加白", ["8001"]), ("总户-企业", ["8002"])]
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd py && python -m pytest tests/test_huguan_undo.py -q -k two_sheets`
Expected: FAIL —— `snapshot_push_targets` 拿到的是 list-of-tuple 而不是 rows

- [ ] **Step 3: 改 `snapshot_push_targets`**

把函数签名改为接收 `groups`，返回逐表快照：

```python
def snapshot_push_targets(service, conf: dict, platform: str, groups: list) -> dict:
    """读每张表，记下「本次刷新将会写到的每个格子」的当前值。

    `groups` 是 `group_rows_by_sheet` 的产出：`[(sheet_name, rows)]`。

    只覆盖**真正会被写**的行与列：
      - 行：`rows` 里在表中命中定位键的那些（表里没有的账户 update_rows_by_account_id
        会进 not_found、一个字都不写）
      - 列：该行 `cells_for_row` 会产出的列（即 COLUMN_SPEC 里 writable=True 的）

    ⚠️ 必须在**写表之前**调用 —— 写完之后原值就没了。
    ⚠️ 返回值从「单表快照」改成**每张表一份**（2026-10-08 多表规格 §4.4）：
       TT 现在一个平台有多张 worksheet，撤回必须逐表还原。
       兼容性：旧快照 payload 是 `{spreadsheet_id, sheet_name, cells}`，
       `push_undo_cells` 两种形状都认（见下），所以历史快照仍能撤回一次。
    """
    spreadsheets = conf.get("spreadsheet_id") or ""
    out_sheets = []
    for sheet_name, rows in groups:
        if not rows:
            continue
        grid = read_sheet_values(service, spreadsheets, sheet_name, READ_RANGE[platform])
        key_i = col_index(KEY_COL[platform])

        where = {}
        for i, values in enumerate(grid[1:], start=2):
            if len(values) <= key_i:
                continue
            raw = ("" if values[key_i] is None else str(values[key_i])).strip().lstrip("'").strip()
            if raw and raw not in where:
                where[raw] = values

        cells = []
        for r in rows:
            aid = r["account_id"]
            values = where.get(aid)
            if values is None:
                continue
            row_cells = {}
            for col in r["cells"]:
                i = col_index(col)
                row_cells[col] = ("" if len(values) <= i or values[i] is None
                                  else str(values[i])).strip()
            if row_cells:
                cells.append({"account_id": aid, "cells": row_cells})
        out_sheets.append({"sheet_name": sheet_name, "cells": cells})
    return {"spreadsheet_id": spreadsheets, "sheets": out_sheets}
```

- [ ] **Step 4: 改 `push_undo_cells`**

```python
def push_undo_cells(payload: dict) -> list:
    """把 push 快照转成「按表分组」的写表入参：`[(sheet_name, rows)]`。

    兼容两种快照形状：
      - 新（2026-10-08 起）：`{spreadsheet_id, sheets: [{sheet_name, cells}]}`
      - 旧（多表之前）：`{spreadsheet_id, sheet_name, cells}`
    旧快照必须继续认，否则升级那一刻「撤回上次」会静默变成空操作。
    """
    payload = payload or {}
    sheets = payload.get("sheets")
    if isinstance(sheets, list):
        return [(s.get("sheet_name") or "",
                 [{"account_id": c["account_id"], "cells": dict(c["cells"])}
                  for c in (s.get("cells") or [])])
                for s in sheets if s.get("sheet_name")]
    legacy_name = payload.get("sheet_name") or ""
    if not legacy_name:
        return []
    return [(legacy_name,
             [{"account_id": c["account_id"], "cells": dict(c["cells"])}
              for c in (payload.get("cells") or [])])]
```

- [ ] **Step 5: 改 `undo_push`**

把 `rows = push_undo_cells(payload)` 之后的写表段改成逐表写：

```python
    groups = push_undo_cells(payload)
    if not any(rs for _sn, rs in groups):
        # 快照存在但覆盖 0 行 ⇒ 没东西可退；作废它，否则撤回按钮永久亮着。
        db = _open_db()
        try:
            delete_undo(db, user_id, platform, "push")
            db.commit()
        finally:
            db.close()
        return {"updated": 0, "not_found": []}

    import google_sheets_service as gs
    from main import _GOOGLE_SHEETS_CONFIG
    service = gs.build_service(_GOOGLE_SHEETS_CONFIG["credentials_path"])
    spreadsheet_id = payload.get("spreadsheet_id") or ""
    total_updated, total_not_found = 0, []
    for sheet_name, rows in groups:
        if not rows:
            continue
        res = gs.update_rows_by_account_id(service, spreadsheet_id, sheet_name, rows,
                                           key_col=KEY_COL[platform])
        total_updated += res["updated"]
        total_not_found.extend(res["not_found"])
    db = _open_db()
    try:
        delete_undo(db, user_id, platform, "push")
        db.commit()
    finally:
        db.close()
    return {"updated": total_updated, "not_found": total_not_found}
```

- [ ] **Step 6: `dashboard_push` 全量刷新按类型分组**

`py/routes/huguan_dashboard_routes.py` 的 `dashboard_push`：把 `conf` 校验、`collect_rows_for_push`、`snapshot_push_targets`、`update_rows_by_account_id` 四处改成多表版本。

- 校验段改为：

```python
    db = database.get_db()
    try:
        conf = {p: hd.get_platform_config(db, uid, p) for p in (platform,)}
        c = conf[platform]
        tables = hd.get_platform_tables(db, uid, platform)
        if not c["spreadsheet_id"] or not tables:
            return err("请先在设置页配置户管看板的表格 ID 与工作表名", 400)
        rows = hd.collect_rows_for_push(db, platform)
        groups, skipped = hd.group_rows_by_sheet(db, uid, platform, rows)
    finally:
        db.close()
    for name in skipped:
        log.warning("全量刷新跳过：户类型「%s」查不到工作表", name)

    import google_sheets_service as gs
    from main import _GOOGLE_SHEETS_CONFIG
    service = gs.build_service(_GOOGLE_SHEETS_CONFIG["credentials_path"])

    # 快照：每张表一份（Task 7 实现 snapshot_push_targets 的多表版本）
    undo_db = database.get_db()
    try:
        hd.save_undo(undo_db, uid, platform, "push",
                     hd.snapshot_push_targets(service, c, platform, groups))
        undo_db.commit()
    finally:
        undo_db.close()

    total_updated, total_not_found = 0, []
    try:
        for sheet_name, sheet_rows in groups:
            res = gs.update_rows_by_account_id(service, c["spreadsheet_id"],
                                               sheet_name, sheet_rows,
                                               key_col=hd.KEY_COL[platform])
            total_updated += res["updated"]
            total_not_found.extend(res["not_found"])
    except Exception:
        _discard_push_undo(uid, platform)
        raise

    if not total_updated and not total_not_found:
        _discard_push_undo(uid, platform)

    return ok({"result": {"rows": len(rows), "updated": total_updated,
                          "not_found": total_not_found}})
```

- [ ] **Step 7: 跑测试确认通过**

Run: `cd py && python -m pytest tests/test_huguan_undo.py -q`
Expected: 全绿（含新用例；旧的单表快照用例也应通过 —— `push_undo_cells` 兼容旧形状）

- [ ] **Step 8: 提交**

```bash
git add py/huguan_dashboard.py py/routes/huguan_dashboard_routes.py py/tests/test_huguan_undo.py
git commit -m "feat(huguan): 撤回快照改为按表分份，兼容旧单表快照"
```

---

## Task 8: 账户列表按户类型筛选与计数

**Files:**
- Modify: `py/routes/tt_accounts_routes.py:202-320`（`list_accounts`）
- Test: `py/tests/test_tt_accounts.py`

**Interfaces:**
- Consumes: Task 1 的 `account_type` 列；Task 2 的 `_default_account_type`
- Produces: `GET /api/tt/accounts/list` 新增查询参数 `account_types`（**重复参数**）与响应字段 `type_counts`

- [ ] **Step 1: 写失败测试**

```python
def test_list_filters_by_account_types(client, tt_headers):
    db = database.get_db()
    db.execute("INSERT INTO tt_accounts(name, advertiser_id, account_type, owner_id) "
               "SELECT 'a','6101','加白户', id FROM users WHERE username='ttuser'")
    db.execute("INSERT INTO tt_accounts(name, advertiser_id, account_type, owner_id) "
               "SELECT 'b','6102','企业户', id FROM users WHERE username='ttuser'")
    db.execute("INSERT INTO tt_accounts(name, advertiser_id, account_type, owner_id) "
               "SELECT 'c','6103','企业户', id FROM users WHERE username='ttuser'")
    db.commit()
    db.close()

    data = client.get("/api/tt/accounts/list?account_types=企业户",
                      headers=tt_headers).get_json()
    assert data["total"] == 2
    assert {i["advertiser_id"] for i in data["items"]} == {"6102", "6103"}
    assert data["type_counts"] == {"加白户": 1, "企业户": 2}

    data = client.get("/api/tt/accounts/list?account_types=加白户&account_types=企业户",
                      headers=tt_headers).get_json()
    assert data["total"] == 3


def test_type_counts_ignores_type_filter_but_respects_search(client, tt_headers):
    """type_counts 与 status_counts 同底：含 search，不含 account_types 自身。"""
    db = database.get_db()
    db.execute("INSERT INTO tt_accounts(name, advertiser_id, account_type, owner_id) "
               "SELECT 'a','6201','加白户', id FROM users WHERE username='ttuser'")
    db.execute("INSERT INTO tt_accounts(name, advertiser_id, account_type, owner_id) "
               "SELECT 'b','6202','企业户', id FROM users WHERE username='ttuser'")
    db.commit()
    db.close()
    data = client.get("/api/tt/accounts/list?account_types=加白户&search=6202",
                      headers=tt_headers).get_json()
    assert data["total"] == 0
    assert data["type_counts"] == {"企业户": 1}, "计数要跟着 search 走"


def test_list_extra_blank_account_types_ignored(client, tt_headers):
    data = client.get("/api/tt/accounts/list?account_types=&account_types=",
                      headers=tt_headers).get_json()
    assert data["success"] is True
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd py && python -m pytest tests/test_tt_accounts.py -q -k "account_types or type_counts"`
Expected: FAIL —— `KeyError: 'type_counts'`

- [ ] **Step 3: 实现筛选**

在 `owner_id = ...` 那一组取参之后加：

```python
    # 户类型可多选：**用重复查询参数**（?account_types=A&account_types=B），
    # 不用逗号分隔 —— 类型名是用户自己起的，完全可能含逗号，切开会静默筛不到任何行。
    account_types = [t.strip() for t in request.args.getlist("account_types") if t.strip()]
```

主查询 `if timezone:` 之前插入：

```python
    if account_types:
        marks = ",".join("?" for _ in account_types)
        where.append(f"a.account_type IN ({marks})")
        params += account_types
```

- [ ] **Step 4: 实现 `type_counts`**

在 `status_counts` 计算之后、`return` 之前插入：

```python
    # 各户类型计数。口径与 status_counts **完全同底**：都基于 sc_where2
    # （含 search/bc/agent/timezone/owner，不含 status 与 account_types 自身）——
    # 两排按钮的数字必须能对上同一批账户，否则户管看到「两排加起来不等于总数」会怀疑数据。
    default_type = _default_account_type_tt(db, uid)
    type_counts = {}
    for r in db.execute(
        "SELECT COALESCE(NULLIF(a.account_type, ''), ?) AS atype, COUNT(*) AS cnt "
        "FROM tt_accounts a WHERE " + " AND ".join(sc_where2) + " GROUP BY atype",
        [default_type] + sc_params2
    ).fetchall():
        t = r["atype"] or default_type
        type_counts[t] = type_counts.get(t, 0) + r["cnt"]
```

并在 `return ok({...})` 里加 `'type_counts': type_counts`。

在文件里加一个薄封装（避免 `list_accounts` 直接依赖 huguan_dashboard 的私有函数）：

```python
def _default_account_type_tt(db, uid):
    """新建账户未指定类型时的兜底类型名（取该用户自己看板配置的第一条）。"""
    return hd._default_account_type(db, uid)
```

- [ ] **Step 5: 跑测试确认通过**

Run: `cd py && python -m pytest tests/test_tt_accounts.py -q -k "account_types or type_counts"`
Expected: PASS

- [ ] **Step 6: 跑列表族回归**

Run: `cd py && python -m pytest tests/test_tt_accounts.py tests/test_deleted_pagination.py -q`
Expected: 全绿

- [ ] **Step 7: 提交**

```bash
git add py/routes/tt_accounts_routes.py py/tests/test_tt_accounts.py
git commit -m "feat(tt): 账户列表支持户类型多选筛选与 type_counts 计数"
```

---

## Task 9: 建户 / 编辑 / 批量导入 / 投手同步 接受户类型

**Files:**
- Modify: `py/routes/tt_accounts_routes.py`（`create_account` `:93-142`、`update_account` `:324-424`、`batch_create_accounts` `:427-492`、`sync_from_sheet` `:1216-1379`）
- Test: `py/tests/test_tt_accounts.py`

**Interfaces:**
- Consumes: Task 2 `_default_account_type`
- Produces: 四个端点接受 `account_type`；`create`/`batch-create`/`sync-from-sheet` 缺失时落默认类型；`update` 可改

- [ ] **Step 1: 写失败测试**

```python
def test_create_defaults_account_type(client, tt_headers):
    _mk_account(client, tt_headers, advertiser_id="6301")
    data = client.get("/api/tt/accounts/list", headers=tt_headers).get_json()
    assert data["items"][0]["account_type"] == "加白户"


def test_create_with_explicit_account_type(client, tt_headers):
    _mk_account(client, tt_headers, advertiser_id="6302", account_type="企业户")
    data = client.get("/api/tt/accounts/list", headers=tt_headers).get_json()
    assert data["items"][0]["account_type"] == "企业户"


def test_update_can_change_account_type(client, tt_headers):
    resp = _mk_account(client, tt_headers, advertiser_id="6303")
    aid = resp.get_json()["id"]
    client.put(f"/api/tt/accounts/{aid}", headers=tt_headers, json={"account_type": "企业户"})
    data = client.get("/api/tt/accounts/list", headers=tt_headers).get_json()
    assert data["items"][0]["account_type"] == "企业户"


def test_batch_create_applies_type_to_whole_batch(client, tt_headers):
    client.post("/api/tt/accounts/batch-create", headers=tt_headers,
                json={"account_ids": ["6304", "6305"], "agent": "", "agent_id": None,
                      "account_type": "企业户"})
    data = client.get("/api/tt/accounts/list", headers=tt_headers).get_json()
    assert {i["account_type"] for i in data["items"]} == {"企业户"}


@mock.patch("google_sheets_service.build_service")
@mock.patch("google_sheets_service.read_sheet_values")
def test_sync_from_sheet_applies_type_to_new_accounts_only(mock_read, mock_build,
                                                           client, tt_headers):
    mock_build.return_value = object()
    mock_read.return_value = [
        ["运营", "入库时间", "是否回收", "账户ID"],
        ["ttuser", "2026-09-20", "否", "6401"],
    ]
    db = database.get_db()
    db.execute("UPDATE users SET display_name='ttuser' WHERE username='ttuser'")
    db.execute("INSERT OR REPLACE INTO tags(key,value) VALUES('tt_sheet_id','sheet-1')")
    db.execute("INSERT OR REPLACE INTO tags(key,value) VALUES('tt_sheet_mappings', ?)",
               ('{"my_dashboard": "我的看板"}',))
    # 已存在的一条：它必须**不被**改写
    db.execute("INSERT INTO tt_accounts(name, advertiser_id, account_type, owner_id) "
               "SELECT 'old','6402','加白户', id FROM users WHERE username='ttuser'")
    db.commit()
    db.close()

    mock_read.return_value = [
        ["运营", "入库时间", "是否回收", "账户ID"],
        ["ttuser", "2026-09-20", "否", "6401"],
        ["ttuser", "2026-09-20", "否", "6402"],
    ]
    resp = client.post("/api/tt/accounts/sync-from-sheet", headers=tt_headers,
                       json={"dry_run": False, "account_type": "企业户"})
    assert resp.status_code == 200
    data = client.get("/api/tt/accounts/list", headers=tt_headers).get_json()
    got = {i["advertiser_id"]: i["account_type"] for i in data["items"]}
    assert got["6401"] == "企业户", "新建的落选定类型"
    assert got["6402"] == "加白户", "已存在的账户类型不动"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd py && python -m pytest tests/test_tt_accounts.py -q -k "account_type"`
Expected: FAIL —— `KeyError: 'account_type'`（响应里没有）或类型恒为空

- [ ] **Step 3: `create_account`**

在 `status_id = _resolve_status_id(...)` 之后加：

```python
    # 户类型：未指定/空白时落默认类型（看板配置第一条，否则常量）。
    # 服务端不做白名单校验 —— 清单是用户自定义的，硬校验会在「户管刚改名、前端
    # 还拿着旧清单」的瞬间把建户打断；非法值只会变成待总表同步纠正的孤儿类型。
    account_type = (data.get("account_type") or "").strip() or hd._default_account_type(db, uid)
```

INSERT 的列与占位符各加一项（`owner_id` 之后、`created_at` 之前）：

```python
        db.execute(
            "INSERT INTO tt_accounts(name, advertiser_id, bc_id, country, agent_id, timezone, "
            "consumption, status_id, acquired_date, remark, owner_id, account_type, "
            "created_at, updated_at) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (name, advertiser_id, bc_id,
             (data.get("country") or "").strip(), agent_id, (data.get("timezone") or "").strip(),
             (data.get("consumption") or "").strip(), status_id,
             (data.get("acquired_date") or None), (data.get("remark") or "").strip(),
             uid, account_type, now, now))
```

- [ ] **Step 4: `update_account`**

`editable` 列表里加 `"account_type"`：

```python
    editable = ["name", "country", "timezone", "consumption",
                "acquired_date", "death_date", "remark", "account_type"]
```

> 该循环对**值非 None** 的字段执行 `UPDATE ... SET f=?`，所以 `account_type` 传空串会被原样写空。前端下拉不会传空；为稳妥，在循环之前把空串规范成默认类型：

```python
    if "account_type" in data and data.get("account_type") is not None:
        _at = str(data["account_type"]).strip()
        data["account_type"] = _at or hd._default_account_type(db, uid)
```

- [ ] **Step 5: `batch_create_accounts`**

`common` 字典里加一项：

```python
        "account_type": (data.get("account_type") or "").strip(),
```

循环内解析（放在 `acquired_date = ...` 之后）：

```python
        account_type = (ov.get("account_type") or common["account_type"]).strip() \
            or hd._default_account_type(db, uid)
```

INSERT 列与值各加 `account_type`（位置与 create 一致）：

```python
            db.execute(
                "INSERT INTO tt_accounts(name, advertiser_id, bc_id, country, agent_id, timezone, "
                "status_id, acquired_date, owner_id, account_type, created_at, updated_at) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                (name, aid, bc_id, country, agent_id, timezone, status_id,
                 acquired_date, uid, account_type, now, now))
```

- [ ] **Step 6: `sync_from_sheet`**

`dry_run = bool(data.get("dry_run"))` 之后加：

```python
    # 投手自选的户类型（2026-10-08 规格 §4.8）：只作用于**本次新建**的账户，
    # 已存在的账户类型不动（那条通路不做「以表为准」改写，类型最终由户管从总表纠正）。
    new_account_type = (data.get("account_type") or "").strip() \
        or hd._default_account_type(db, uid)
```

新建分支的 INSERT 加 `account_type`：

```python
                db.execute(
                    "INSERT INTO tt_accounts(name, advertiser_id, bc_id, country, agent_id, timezone, "
                    "consumption, status_id, acquired_date, death_date, remark, owner_id, account_type) "
                    "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (advertiser_id, advertiser_id, bc_id, country, agent_id, timezone,
                     consumption, status_id, acquired_date or None, death_date, remark, uid,
                     new_account_type))
```

- [ ] **Step 7: 跑测试确认通过**

Run: `cd py && python -m pytest tests/test_tt_accounts.py -q -k "account_type"`
Expected: PASS

- [ ] **Step 8: 跑 TT 账户全量回归**

Run: `cd py && python -m pytest tests/test_tt_accounts.py -q`
Expected: 全绿

- [ ] **Step 9: 提交**

```bash
git add py/routes/tt_accounts_routes.py py/tests/test_tt_accounts.py
git commit -m "feat(tt): 建户/编辑/批量导入/投手同步支持户类型"
```

---

## Task 10: 户管的充值表 / 回收户清单配置权限

**Files:**
- Modify: `py/routes/tt_routes.py:1264-1296`（`tt_settings_save`）
- Test: `py/tests/test_tt_routes.py`

**Interfaces:**
- Consumes: 无
- Produces: 户管（role 恰为 `huguan`）写 `recharge` / `recycle` 时落全局 `tags.tt_sheet_mappings`；`accounts` 与 `sheet_id` 仍仅 admin

- [ ] **Step 1: 写失败测试**

```python
def test_settings_save_huguan_writes_recharge_and_recycle(client):
    hg = _make_huguan_headers(client, "huguants1")
    resp = client.post("/api/tt/settings", headers=hg, json={
        "sheet_id": "MUST_NOT_WRITE",
        "sheet_mappings": {"accounts": "不该写", "recharge": "户管充值表",
                           "recycle": "户管回收表", "my_dashboard": "也不该写"},
    })
    assert resp.status_code == 200

    db = database.get_db()
    assert db.execute("SELECT value FROM tags WHERE key='tt_sheet_id'").fetchone() is None, \
        "户管不许改全局表格 ID"
    row = db.execute("SELECT value FROM tags WHERE key='tt_sheet_mappings'").fetchone()
    got = json.loads(row["value"])
    assert got == {"recharge": "户管充值表", "recycle": "户管回收表"}, \
        "户管只能写 recharge / recycle，accounts 不许进全局"
    db.close()


def test_settings_save_plain_user_still_only_private(client, tt_headers):
    """既有行为不许被改坏：普通投手仍然只写自己的 my_dashboard。"""
    client.post("/api/tt/settings", headers=tt_headers, json={
        "sheet_mappings": {"recharge": "投手不该写", "my_dashboard": "我的"},
    })
    db = database.get_db()
    assert db.execute("SELECT value FROM tags WHERE key='tt_sheet_mappings'").fetchone() is None
    db.close()
```

在该文件顶部 helper 区加（照 `_make_tt_headers` 的形状）：

```python
def _make_huguan_headers(client, username):
    """户管（跨平台角色）。"""
    client.post("/api/auth/register", json={"username": username, "password": "test123"})
    db = database.get_db()
    db.execute("UPDATE users SET role='huguan', platform='gg' WHERE username=?", (username,))
    db.commit()
    db.close()
    resp = client.post("/api/auth/login", json={"username": username, "password": "test123"})
    return {"Authorization": f"Bearer {resp.get_json()['access_token']}"}
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd py && python -m pytest tests/test_tt_routes.py -q -k "huguan_writes"`
Expected: FAIL —— 全局 tags 里没有 `tt_sheet_mappings`

- [ ] **Step 3: 实现分档授权**

`tt_settings_save` 的 docstring 与函数体替换为：

```python
@tt_bp.route('/api/tt/settings', methods=['POST'])
@jwt_required()
@tt_required
def tt_settings_save():
    """保存 TT 平台的 Google 表格配置。

    写权限按角色分档（2026-10-08 规格 §4.9 决策 9）：

    - `sheet_id`：仅 admin/developer（全局 tag）
    - `accounts`：仅 admin/developer（它是无人读的历史 key）
    - `recharge` / `recycle`：admin/developer + **户管**（全局 tag）——
      充值表与回收户清单与投手是同一张，用户 2026-10-08 裁定给户管全局写权限
    - `my_dashboard`：所有用户写各自的私有 config（投手各自配看板）

    ⚠️ 前端 `TtSettingsPanel.vue` 的行渲染范围必须与这里逐字对齐。
       两边不一致就会造出「界面上能改、点保存提示成功、实际什么都没存」的静默丢弃
       （本次修掉的正是这个 bug）。
    """
    db = get_db()
    uid = get_uid()
    role = _get_role(db, uid)
    is_admin = role in ('admin', 'developer')
    is_huguan = role == 'huguan'
    data = parse_body()
    if 'sheet_id' in data and is_admin:
        db.execute("INSERT OR REPLACE INTO tags(key,value) VALUES(?,?)",
                   ("tt_sheet_id", str(data['sheet_id'] or '')))
    if 'sheet_mappings' in data:
        mappings = data['sheet_mappings']
        if not isinstance(mappings, dict):
            mappings = {}
        if is_admin:
            allowed = _TT_SHEET_MAPPING_KEYS
        elif is_huguan:
            allowed = {"recharge", "recycle"}
        else:
            allowed = set()
        global_mappings = {k: mappings[k] for k in allowed if k in mappings}
        if global_mappings:
            # 合并而非覆盖：户管只改 recharge/recycle 时，不要把 admin 配的其他 key 抹掉。
            merged = {}
            existing = db.execute(
                "SELECT value FROM tags WHERE key='tt_sheet_mappings'").fetchone()
            if existing and existing["value"]:
                try:
                    loaded = json.loads(existing["value"])
                    if isinstance(loaded, dict):
                        merged.update(loaded)
                except Exception:
                    pass
            merged.update(global_mappings)
            db.execute("INSERT OR REPLACE INTO tags(key,value) VALUES(?,?)",
                       ("tt_sheet_mappings", json.dumps(merged, ensure_ascii=False)))
        if is_huguan:
            # 户管不拥有投手看板，不写私有 my_dashboard（保持既有语义：投手专属）
            pass
        elif is_admin:
            _save_tt_user_sheet_mappings(db, uid, mappings)
        else:
            # 投手只保存自己的「我的看板」sheet 名
            _save_tt_user_sheet_mappings(db, uid, {"my_dashboard": mappings.get("my_dashboard", "")})
    db.commit()
    return ok()
```

> ⚠️ **admin 分支的合并语义变了**（原来是无条件覆盖全局 tags）。这是**必要**的修复：不合并的话，户管单独保存 recharge 会把 admin 配的 `accounts` 抹掉。既有测试 `test_settings_save_and_readback` 仍应通过（它只断言自己写的 key）。

- [ ] **Step 4: 跑测试确认通过**

Run: `cd py && python -m pytest tests/test_tt_routes.py -q -k "settings"`
Expected: 全绿（新用例 + 既有 3 个 settings 用例）

- [ ] **Step 5: 提交**

```bash
git add py/routes/tt_routes.py py/tests/test_tt_routes.py
git commit -m "feat(tt): 户管获得充值表/回收户清单的全局配置写权限（合并而非覆盖）"
```

---

## Task 11: 前端 —— 户管看板卡片的 TT 多表 UI

**Files:**
- Modify: `frontend/src/components/HuguanDashboardCard.vue`（template `:34-42` 的"工作表名"块、script `:510` 的 `hdForm`、`:786-802` `loadHdConfig`、`:872-890` `saveHdConfig`）
- Modify: `frontend/src/api/huguan.js`（注释更新）

**Interfaces:**
- Consumes: Task 3 的 `GET/POST /huguan/dashboard` 的 `tables` 字段
- Produces: `hdForm` 形如 `{ spreadsheet_id, sheet_name, tables: [{name, sheet_name}] }`

- [ ] **Step 1: 改 `hdForm` 与配置读写**

`const hdForm = ref({ spreadsheet_id: '', sheet_name: '' })` 改为：

```js
// tt 用 tables（多张账户表，每条 = 户类型名 + worksheet）；gg/fb 仍用 sheet_name 单表。
// 两个字段同时保留：切平台时不会因为残留值串味，保存时按平台只发对应的那个。
const hdForm = ref({ spreadsheet_id: '', sheet_name: '', tables: [] })
```

`loadHdConfig` 里赋值那段改为：

```js
    const conf = (res.config && res.config[HD_PLATFORM]) || {}
    hdForm.value = {
      spreadsheet_id: conf.spreadsheet_id || '',
      sheet_name: conf.sheet_name || '',
      // tt 的多表：后端对没有 tables 的存量配置会返回单条「加白户」兜底，
      // 但 gg/fb 完全不返回 tables ⇒ 这里必须兜成 []
      tables: Array.isArray(conf.tables)
        ? conf.tables.map(t => ({ name: t.name || '', sheet_name: t.sheet_name || '' }))
        : [],
    }
```

`saveHdConfig` 的请求体改为：

```js
    const body = {
      platform: HD_PLATFORM,
      spreadsheet_id: hdForm.value.spreadsheet_id,
    }
    if (HD_PLATFORM === 'tt') {
      // tt 走多表。空行（用户点了「+ 新增」还没填完）在这里被过滤掉 ——
      // 后端会 400，但用户在填的过程中不该被拦，所以只要有一条完整就发。
      const tables = hdForm.value.tables
        .map(t => ({ name: (t.name || '').trim(), sheet_name: (t.sheet_name || '').trim() }))
        .filter(t => t.name && t.sheet_name)
      body.tables = tables
    } else {
      body.sheet_name = hdForm.value.sheet_name
    }
    if (HD_PLATFORM === 'tt' && (!body.tables || !body.tables.length)) {
      ElMessage.warning('至少要配一张账户表（类型名 + 工作表名）')
      return
    }
    await huguanApi.saveConfig(body)
```

再在 `readHdSheets` 之外加两个小函数：

```js
function addHdTable() {
  hdForm.value.tables.push({ name: '', sheet_name: '' })
}
function removeHdTable(i) {
  hdForm.value.tables.splice(i, 1)
}
```

- [ ] **Step 2: 改 template**

`<div style="margin-bottom:16px;">` 里那段"工作表名"（`<el-select v-model="hdForm.sheet_name" ...>` 整块）替换为两个互斥分支：

```vue
      <!-- gg / fb：单表（原样保留） -->
      <div v-if="HD_PLATFORM !== 'tt'" style="margin-bottom:16px;">
        <div style="font-weight:500;font-size:13px;color:#374151;margin-bottom:6px;">工作表名</div>
        <el-select v-model="hdForm.sheet_name" filterable allow-create default-first-option
                   placeholder="选择或输入工作表名" style="width:100%;" :disabled="hdBusy">
          <el-option v-for="name in hdSheets" :key="name" :label="name" :value="name" />
          <template #empty>
            <div style="padding:8px 12px;font-size:12px;color:#6b7280;line-height:1.6;">
              这个表格里没有可读的工作表
            </div>
          </template>
        </el-select>
      </div>

      <!-- tt：多张账户表，每条 = 户类型名（自定义，也是账户页按钮的名字）+ 工作表 -->
      <div v-else style="margin-bottom:16px;">
        <div style="font-weight:500;font-size:13px;color:#374151;margin-bottom:6px;">
          账户表（户类型 → 工作表）
        </div>
        <div style="font-size:12px;color:#6b7280;margin-bottom:8px;line-height:1.6;">
          每一行是一张账户表。左边的名字就是「户类型」，会出现在账户页的筛选按钮上，
          也是系统里区分账户的依据；右边选这张表在 Google 表格里对应的工作表。
        </div>
        <div v-for="(t, i) in hdForm.tables" :key="i"
             style="display:flex;gap:8px;align-items:center;margin-bottom:8px;">
          <el-input v-model="t.name" placeholder="户类型名，如 加白户" style="width:180px;"
                    :disabled="hdBusy" />
          <el-select v-model="t.sheet_name" filterable allow-create default-first-option
                     placeholder="选择或输入工作表名" style="flex:1;" :disabled="hdBusy">
            <el-option v-for="name in hdSheets" :key="name" :label="name" :value="name" />
          </el-select>
          <el-button :disabled="hdBusy" @click="removeHdTable(i)">删除</el-button>
        </div>
        <el-button size="small" :disabled="hdBusy" @click="addHdTable">＋ 新增户类型</el-button>
        <div v-if="!hdForm.tables.length" style="font-size:12px;color:#e6a23c;margin-top:6px;">
          还没配任何账户表。至少要有「加白户」一条，否则同步会读不到数据。
        </div>
      </div>
```

`hdConfigured` 计算属性改为：

```js
const hdConfigured = computed(() => {
  if (!hdForm.value.spreadsheet_id) return false
  if (HD_PLATFORM === 'tt') {
    return hdForm.value.tables.some(t => (t.name || '').trim() && (t.sheet_name || '').trim())
  }
  return !!hdForm.value.sheet_name
})
```

- [ ] **Step 3: 手动验证**

启动前端 dev server（`cd frontend && npm run dev`），用户管账号进 TT 设置页：

1. 卡片显示「账户表（户类型 → 工作表）」+ 一行；点「＋ 新增户类型」出现第二行。
2. 填「加白户 / <工作表>」，保存 → 提示"配置已保存"；刷新页面后两行仍在。
3. 切到 GG 设置页，同一张卡片仍是**单个**「工作表名」下拉（回归）。
4. 「刷新到看板 / 从表同步到系统」按钮在 tt 未配工作表时是禁用的。

> ⚠️ 启动 dev server 前先征得用户同意（本仓库约定：不得自动启动新进程）。

- [ ] **Step 4: 提交**

```bash
git add frontend/src/components/HuguanDashboardCard.vue frontend/src/api/huguan.js
git commit -m "feat(tt-ui): 户管看板卡片支持 tt 多账户表（GG/FB 单表不变）"
```

---

## Task 12: 前端 —— TT 设置页放开 + 按角色渲染

**Files:**
- Modify: `frontend/src/views/tt/TtSettingsPanel.vue:121`（卡片 `v-if`）、`:155`（行的渲染条件）、`:294-307`（`SHEET_MAPPING_META` / `visibleSheetKeys`）

**Interfaces:**
- Consumes: Task 10 的后端白名单
- Produces: 户管能看到并保存「充值表 / 回收户清单」两行；看不到 `accounts` / `my_dashboard`；`sheet_id` 只读

- [ ] **Step 1: 改 `SHEET_MAPPING_META` 与 `visibleSheetKeys`**

```js
// Sheet 映射功能注册表 — 已知 key 的显示名（未知 key 直接显示 key 名）。
// writableBy 必须与后端 tt_settings_save 的白名单**逐字对齐**：
// 「界面上能改」与「存得下去」必须同一个集合，否则就是静默丢弃。
const SHEET_MAPPING_META = {
  accounts: { label: '账户明细', adminOnly: true, writableBy: ['admin', 'developer'] },
  recharge: { label: '充值表', adminOnly: true, writableBy: ['admin', 'developer', 'huguan'] },
  my_dashboard: { label: '我的看板', adminOnly: false, writableBy: ['admin', 'developer', 'user', 'viewer', 'hidden'] },
  recycle: { label: '回收户清单', adminOnly: true, writableBy: ['admin', 'developer', 'huguan'] },
}
```

`visibleSheetKeys` 替换为：

```js
// 当前用户可见的 sheet 映射 key。
// ⚠️ 这里**不再**用 `!adminOnly || isHuguan` 那种「给户管开后门放行全部 adminOnly 行」
// 的写法 —— 那正是「户管看得见 recharge/recycle/accounts、但后端只存 my_dashboard」
// 静默丢弃的由来。改成按角色的显式白名单，两边一起改才不会漂。
const visibleSheetKeys = computed(() => {
  const role = authStore.user?.role || 'user'
  return Object.keys(SHEET_MAPPING_META)
    .filter(k => (SHEET_MAPPING_META[k].writableBy || []).includes(role))
})
```

- [ ] **Step 2: 改卡片可见性 + header 提示**

`:121` 的 `<el-card v-if="!authStore.isHuguan" ...>` 改为：

```vue
          <el-card shadow="never" style="margin-top:20px;border-left:3px solid #0891b2;">
```

**表格 ID 输入框那一行不动** —— 它已经是 `:disabled="!isAdmin"`，而户管不是 admin ⇒ 天然只读，无需改。
（「📋 读取工作表」按钮不 disabled，户管仍能加载下拉候选，这是要的。）

把 header 里的「仅管理员」tag 改为按权限显示：

```vue
              <el-tag v-if="isAdmin" size="small" type="warning" style="margin-left:8px;">仅管理员</el-tag>
              <el-tag v-else-if="authStore.isHuguan" size="small" type="info" style="margin-left:8px;">充值表 / 回收户清单可改</el-tag>
```

- [ ] **Step 3: 修 `form.sheet_mappings` 的初始值与回读**

户管的 `form.sheet_mappings` 现在**只应含它有权写的 key**，否则 `save()` 会把无权 key 一起发出去（后端会过滤，但请求体里带着误导性的数据）。`loadSettings` 之后加一句收敛：

```js
    // 只保留当前用户有权写的 key：把无权 key 留在 form 里，保存时它们会被后端静默
    // 丢弃，而用户以为自己改了 —— 与造成静默丢弃的那个 bug 同源。
    const allowed = new Set(visibleSheetKeys.value)
    form.sheet_mappings = Object.fromEntries(
      Object.entries(form.sheet_mappings).filter(([k]) => allowed.has(k)))
    for (const k of allowed) {
      if (!(k in form.sheet_mappings)) form.sheet_mappings[k] = ''
    }
```

- [ ] **Step 4: 手动验证**

户管账号进 TT 设置页：

1. 「📊 Google 表格配置」卡片**可见**；表格 ID 输入框**灰的**（只读）；「📋 读取工作表」可点。
2. Sheet 映射里只有「充值表」「回收户清单」两行；**没有**「账户明细」「我的看板」。
3. 改这两行 → 保存 → 提示已保存；刷新 → 值还在（证明真的写进了全局 tags）。
4. 用 admin 账号看：四行都在，行为与改动前一致。
5. 用投手账号看：只有「我的看板」一行，保存后自己专属看板名生效、全局 tags 不变。

> ⚠️ 启动服务前先征得用户同意。

- [ ] **Step 5: 提交**

```bash
git add frontend/src/views/tt/TtSettingsPanel.vue
git commit -m "fix(tt-ui): 修户管配置静默丢弃——卡片放开 + 按角色渲染 + 白名单与后端对齐"
```

---

## Task 13: 前端 —— 账户页户类型多选按钮组 / 列 / 三个弹窗

**Files:**
- Modify: `frontend/src/views/tt/TtAccountPanel.vue`（template `:28-33`、script `:277-279`、`:375-415`）
- Modify: `frontend/src/constants/accountColumns.js:32-46`
- Modify: `frontend/src/components/tt/TtAccountModal.vue`（表单 + `form` + `submit`）
- Modify: `frontend/src/components/tt/TtAccountBatchImportModal.vue`（公共表单 + `form` + `submit`）
- Modify: `frontend/src/components/tt/TtAccountSyncModal.vue`（下拉 + 报告表名）

**Interfaces:**
- Consumes: Task 8 的 `type_counts` / `account_types`；Task 9 的四个端点
- Produces: 无（终端 UI）

- [ ] **Step 1: 列表筛选状态与请求参数**

`TtAccountPanel.vue` 的 `const statusCounts = ref({})` 之后加：

```js
const accountTypes = ref([])        // 多选：空数组 = 不加类型条件
const typeCounts = ref({})          // 后端给的「户类型 → 数量」，口径同 statusCounts
```

`load()` 里 `statusCounts.value = res.status_counts || {}` 之后加：

```js
    typeCounts.value = res.type_counts || {}
```

请求参数（`if (ownerId.value) params.owner_id = ownerId.value` 之后）加：

```js
  // 直接传数组：axios 会把数组展开成重复查询参数（?account_types=A&account_types=B）。
  // **不要**自己 join 成逗号分隔的串 —— 类型名是用户起的，完全可能含逗号。
  if (accountTypes.value.length) params.account_types = accountTypes.value
```

- [ ] **Step 2: 按钮组 template**

状态按钮组那个 `<div>` **之前**插入：

```vue
      <!-- 户类型按钮（多选）：候选集来自实际数据（type_counts），顺序按户管配置 -->
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

- [ ] **Step 3: 按钮逻辑**

`clearStatus` 之后加：

```js
// 户类型候选集 = 库里实际出现过的类型（计数 > 0），**不是**配置清单 ——
// 配置被清空时按钮也不该凭空消失。
// 顺序：按计数从多到少。为什么不用「配置清单顺序」：类型清单只存在于户管自己的
// `huguan_dashboard_<uid>` 配置里，`GET /api/tt/settings` 拿不到它，而按钮要对
// 投手 / admin 也一致可见 —— 用一个所有人都能算出来的稳定顺序，比给不同角色不同
// 顺序更不容易出错。真正需要确定的只有**默认勾选哪一项**，见 Step 4。
const availableTypes = computed(() => {
  const counted = Object.keys(typeCounts.value).filter(t => (typeCounts.value[t] || 0) > 0)
  return counted.sort((a, b) => (typeCounts.value[b] || 0) - (typeCounts.value[a] || 0))
})

function toggleType(name) {
  const i = accountTypes.value.indexOf(name)
  if (i >= 0) accountTypes.value.splice(i, 1)
  else accountTypes.value.push(name)
  page.value = 1
  load()
}
```

- [ ] **Step 4: 默认勾选**

首次加载完成后自动勾选默认类型（`加白户`；若库里没有该类型则勾第一个）：

```js
const defaultTypeApplied = ref(false)
function applyDefaultType() {
  if (defaultTypeApplied.value) return
  const counted = Object.keys(typeCounts.value).filter(t => (typeCounts.value[t] || 0) > 0)
  if (!counted.length) return                      // 一个新账户都没有 → 不加类型条件
  const preferred = counted.includes('加白户') ? '加白户' : counted[0]
  accountTypes.value = [preferred]
  defaultTypeApplied.value = true
}
```

在 `load()` 的 `typeCounts.value = res.type_counts || {}` 之后调用一次：

```js
    if (!defaultTypeApplied.value) { applyDefaultType(); if (accountTypes.value.length) return load() }
```

> ⚠️ 这里会二次请求一次列表（首次拿到计数才发现要勾默认类型）。可以接受：只在打开面板时发生一次，避免在不知道有哪些类型的情况下瞎猜默认值。

`clearTypes()` 要同时把 `defaultTypeApplied` 置 `true`，否则用户清空后又被自动勾回来：

```js
function clearTypes() {
  accountTypes.value = []
  defaultTypeApplied.value = true   // 用户显式清了，别再自动勾回去
  page.value = 1
  load()
}
```

- [ ] **Step 5: 新增「户类型」列**

`frontend/src/constants/accountColumns.js` 的 `TT_ADS_COLUMNS` 里，`advertiser_id` 之后插入：

```js
  { key: 'account_type', prop: 'account_type', label: '户类型', minWidth: 110, showOverflowTooltip: true },
```

在 `TtAccountPanel.vue` 的列渲染 `v-if/v-else-if` 链里加一支（找到 `key === 'advertiser_id'` 那一支，照它的形状写）：

```vue
        <el-table-column v-else-if="key === 'account_type'" prop="account_type" label="户类型"
                         min-width="110" show-overflow-tooltip>
          <template #default="{ row }">{{ row.account_type || '加白户' }}</template>
        </el-table-column>
```

- [ ] **Step 6: 建户 / 编辑弹窗加下拉**

`TtAccountModal.vue` 的 `form` 加 `account_type: '加白户'`：

```js
const form = reactive({
  name: '', advertiser_id: '', bc_id: '', timezone: '',
  agent: null, status: null, acquired_date: '', country: '', consumption: '',
  account_type: '加白户',
})
```

template 里「状态」那个 `el-form-item` 之后插入：

```vue
      <el-form-item label="户类型">
        <el-select v-model="form.account_type" style="width:100%;" filterable allow-create
                   placeholder="选择或输入户类型">
          <el-option v-for="t in typeOptions" :key="t" :label="t" :value="t" />
        </el-select>
      </el-form-item>
```

`submit` 的 `body` 加一项：

```js
      account_type: form.account_type,
```

打开弹窗时的回填：找到 `watch(() => props.visible, ...)` 或 `open()` 里回填 `form` 的地方，加一句 `form.account_type = props.editAccount?.account_type || '加白户'`。

`typeOptions` 的来源：与 Task 13 Step 3 同样的问题（投手读不到户管配置）。**用「当前列表里已出现过的类型 + 加白户 + 企业户」做候选**：

```js
const typeOptions = computed(() => {
  const s = new Set(['加白户', '企业户'])
  for (const k of Object.keys(typeCounts.value)) s.add(k)
  return [...s]
})
```

> 该弹窗的 `props` 里需要拿到 `typeCounts`。最省事的做法：给 `TtAccountModal` 增加一个 prop `typeOptions: { type: Array, default: () => [] }`，由 `TtAccountPanel` 传 `:type-options="typeOptions"` 进去，弹窗内直接用 `props.typeOptions`。**按这个做法写**，不要在弹窗里自己发请求。

- [ ] **Step 7: 批量导入弹窗加下拉**

`TtAccountBatchImportModal.vue` 的 `form` 加 `account_type: '加白户'`；在「状态」那个 `el-col` 之后加：

```vue
              <el-col :span="8">
                <el-form-item label="户类型" style="margin-bottom:8px;">
                  <el-select v-model="form.account_type" size="small" style="width:100%;"
                             filterable allow-create placeholder="选择户类型">
                    <el-option v-for="t in typeOptions" :key="t" :label="t" :value="t" />
                  </el-select>
                </el-form-item>
              </el-col>
```

（把上面那个 `el-row` 的三列改成 `:span="6"` 四列，或另起一个 `el-row` —— 二选一，保持栅格总和为 24。）

`submit` 的 `batchCreate` 请求体加：

```js
        account_type: form.account_type,
```

`typeOptions` 同样走 prop 传入（`TtAccountPanel` 传 `:type-options="typeOptions"`）。

- [ ] **Step 8: 投手同步弹窗加下拉**

`TtAccountSyncModal.vue`：

```js
const props = defineProps({
  visible: Boolean,
  typeOptions: { type: Array, default: () => ['加白户', '企业户'] },
})
const accountType = ref('加白户')
```

template 顶部（`el-alert` 之前）插入：

```vue
    <div style="display:flex;align-items:center;gap:8px;margin-bottom:12px;">
      <span style="font-size:13px;color:#374151;white-space:nowrap;">本次新建账户的户类型</span>
      <el-select v-model="accountType" size="small" style="width:200px;" filterable allow-create>
        <el-option v-for="t in props.typeOptions" :key="t" :label="t" :value="t" />
      </el-select>
      <span style="font-size:12px;color:#909399;">只作用于新建的账户；已存在的账户类型不变</span>
    </div>
```

两趟请求都带上它：

```js
    const res = await ttAccountsApi.syncFromSheet({ dry_run: true })
```
→
```js
    const res = await ttAccountsApi.syncFromSheet({ dry_run: true, account_type: accountType.value })
```
```js
    const res = await ttAccountsApi.syncFromSheet({ dry_run: false, resolutions, status_resolutions: statusResolutions })
```
→
```js
    const res = await ttAccountsApi.syncFromSheet({ dry_run: false, resolutions,
      status_resolutions: statusResolutions, account_type: accountType.value })
```

新增「新增」表格里加一列显示类型：

```vue
          <el-table-column label="户类型" width="100"><template #default>{{ accountType }}</template></el-table-column>
```

- [ ] **Step 9: 报告按表分组（总表同步）**

`HuguanDashboardCard.vue` 的差异报告里，「表行」那一列（出现 4 处：归属变更 / 清空 / 新增 / 更新 / 跳过 / 警告）改为带表名：

```vue
            <el-table-column label="表" min-width="120" show-overflow-tooltip>
              <template #default="{ row }">
                <el-tag v-if="row.sheet" size="small" type="info" effect="plain">{{ row.sheet }}</el-tag>
                <span v-else>—</span>
              </template>
            </el-table-column>
            <el-table-column label="表行" width="86">
              <template #default="{ row }">
                <el-tag size="small" type="info" effect="plain">第 {{ row.row }} 行</el-tag>
              </template>
            </el-table-column>
```

> **只在 `platform === 'tt'` 时渲染「表」这一列**（用 `v-if="HD_PLATFORM === 'tt'"` 包住）—— gg/fb 的 `sheet` 恒为空串，多一列全是「—」纯属噪音。

- [ ] **Step 10: 手动验证**

1. TT 账户页：户类型按钮组出现，默认只勾「加白户」；点「企业户」两个同时高亮，列表条数 = 两类型之和；点「展示全部」清空。
2. 新增账户弹窗有「户类型」下拉，默认加白户；建完在列表「户类型」列能看到。
3. 批量导入弹窗有「户类型」下拉；导入后整批都是该类型。
4. 投手账号点「🔄 同步」：弹窗顶部有下拉；同步后新建账户落该类型。
5. 户管账号点「⬇️ 从表同步到系统」：报告里多出「表」列，两张表的同名行号可区分。

> ⚠️ 启动服务前先征得用户同意。

- [ ] **Step 11: 提交**

```bash
git add frontend/src/views/tt/TtAccountPanel.vue frontend/src/constants/accountColumns.js \
        frontend/src/components/tt/TtAccountModal.vue \
        frontend/src/components/tt/TtAccountBatchImportModal.vue \
        frontend/src/components/tt/TtAccountSyncModal.vue \
        frontend/src/components/HuguanDashboardCard.vue
git commit -m "feat(tt-ui): 户类型多选按钮组、列、三个弹窗下拉与报告表名"
```

---

## Task 14: 端到端验证与文档

**Files:**
- Modify: `AGENTS.md`（表清单里 `tt_accounts` 的列说明 + 设计文档索引）

- [ ] **Step 1: 起服务实测（先征得用户同意）**

用户管账号走一遍真实流程：

1. TT 设置 → 户管看板卡片 → 配「加白户 / 企业户」两张工作表 → 保存。
2. 「⬇️ 从表同步到系统」→ 预演 → 确认 → 报告里「表」列正确、两表账户分别落对类型。
3. TT 账户页 → 用「企业户」按钮筛 → 只看到企业户。
4. 改一个账户的类型 → 保存 → 列表里归到新类型。
5. 「🔄 刷新到看板」→ 检查两张 worksheet **各自只被写了自己类型的账户**（这是本次的核心验收点）。
6. 「↩️ 撤回上次」→ 两张表都还原。
7. 户管在 TT 设置页改「回收户清单」→ 保存 → 刷新仍在（证明全局写入生效）。

- [ ] **Step 2: 确认户管能操作充值记录与回收清单（设计 §4.9 的实测项）**

用户管账号在 TT 账户页试：`💰 充值` / `💰 批量充值` 能开弹窗并提交；把账户状态改成「死亡」能触发回收清单写入。
若有按钮因角色被隐藏 → **按 bug 单独修，不扩大本计划范围**，并在 `AGENTS.md` 记录。

- [ ] **Step 3: 跑全量测试**

Run: `cd py && python -m pytest tests/ -q`
Expected: 全绿（与改动前的基线对比；新增用例数 = 本计划各 Task 之和）

- [ ] **Step 4: 更新 AGENTS.md**

在表清单（约 `:1018` 附近的 `tt_accounts` 条目）补一句：

```
`tt_accounts` 用 `owner_id` 隔离；`account_type` 存**户类型名字符串**（加白户 / 企业户…），
取值来自户管看板配置 `config.huguan_dashboard_<uid>.tt.tables[].name`，
改了配置里的类型名必须级联 `UPDATE tt_accounts.account_type`（`huguan_dashboard.save_config` 里做）。
```

在设计文档索引（约 `:937` 附近）加：

```
- [TT 户类型与多账户表](docs/superpowers/specs/2026-10-08-tt-account-types-design.md)
```

- [ ] **Step 5: 提交**

```bash
git add AGENTS.md
git commit -m "docs(agents): 记录 tt_accounts.account_type 的取值来源与改名级联"
```

---

## 自查清单（实现者收尾时逐条核对）

- [ ] `get_platform_config` 的签名与返回值**没变**（gg/fb 与既有测试依赖它）
- [ ] GG / FB 的配置存储、DOM、请求体**没变**
- [ ] `_account_type` 在 create 与 update 两条分支上**都**在拼 SQL 前 pop 了
- [ ] `group_rows_by_sheet` 对查不到工作表的类型是**跳过**，没有退回写第一张表
- [ ] 同步路由的定向回写（`_write_background_tables`）**先补了 `account_type` 再分组**（不补会导致归属变更静默不回写）
- [ ] `push_rows` 的闭包用默认参数绑住了 `sheet_name` / `sheet_rows`（不是闭包捕获）
- [ ] 类型改名级联写在同一事务里，且 `save_config` 里 `tables=None` 的老路径没被碰
- [ ] `_ensure_columns` 的回填只在 `_add_column_if_missing` 返回 `True` 时执行
- [ ] `tt_settings_save` 的全局写入是**合并**而不是覆盖
- [ ] 前端 `visibleSheetKeys` 的白名单与后端 `allowed` 集合逐字一致
- [ ] 没有 `git add -A`，没有 `git push`
