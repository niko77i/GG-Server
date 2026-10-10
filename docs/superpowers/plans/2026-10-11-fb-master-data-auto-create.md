# FB 所属渠道 / 资产类型 自动补建 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** FB 同步时遇到系统里没有的「所属渠道」「资产类型」，从「记警告 + 整列跳过」改成「补建字典项并挂到账户上」，与 TT 的 BC/渠道 补建同形。

**Architecture:** 把写死的平台门控（`platform == "tt" and f in (...)`）换成一张 `_PENDING_MASTER_FIELDS` 映射表；kind→函数的**末位 `else` 兜底改成显式穷举 + `raise`**（那个兜底会把新类别静默写进 `regions` 表）；新增两个幂等的 `ensure_channel` / `ensure_asset_type`，与既有 `ensure_bc` / `ensure_agent` 同住一处（模块顺势从 `tt_master_data` 改名 `master_data`）。

**Tech Stack:** Python 3.11 / Flask / SQLite / pytest；前端 Vue 3 + Element Plus。

**Spec:** `docs/superpowers/specs/2026-10-11-fb-master-data-auto-create-design.md`

## Global Constraints

- **不启动任何进程**：前端 dev server 与后端 5001 都由用户控制。验证只跑测试 / 构建。
- **禁止 `git add -A` / `git pull` / `git push`**。提交一律显式 pathspec（`git add <具体文件>` 后 `git commit -- <具体文件>`）。
- **这个仓库有别的会话在共用工作区、且正在活跃提交**：不要 `git checkout` / `git stash` / 切分支；拼审查包一律**按文件过滤**，不要用相邻 commit 区间。
- **TT 与 GG 的行为逐字节不变**：门控换映射表后 TT 命中的两条完全一样；`_PENDING_MASTER_FIELDS` 里没有 `gg` 的键。
- **位置（主 BM 名）不补建**（`fb_bms.bm_id` 是 `NOT NULL UNIQUE`，凭空造不出）。
- **状态不动**（它已经会自动建）。
- **`_ensure_region` / `_region_exists` 留在 `huguan_dashboard.py` 不动** —— 若把它们挪进 `master_data.py` 会造成循环 import。
- 测试命令：`cd py && python -m pytest tests/<file> -q`；前端 `cd frontend && npm test` + `npx vite build`。
- 提交信息格式：`<type>(fb-master-data): <中文说明>`。

### 三个必须遵守的接口约定

1. **`_PENDING_MASTER_FIELDS = {("tt","bc_name"): "bc", ("tt","agent_name"): "agent", ("fb","channel_name"): "channel", ("fb","asset_type_name"): "asset_type"}`** —— 唯一的门控。
2. **`ensure_channel(db, name, uid)` / `ensure_asset_type(db, name, uid)`** —— 幂等，返回 id 或 `None`（名称为空时）；`platform` **写死 `'fb'`**；INSERT 形状 `(name, owner_id, platform)`。
3. **`ensure_pending_master(db, items, owner_id) -> dict`** —— 返回 `{列名: id}`；kind 显式穷举，**未知 kind 必须 `raise ValueError`**。

---

## 文件结构

| 文件 | 职责 | 本次改动 |
|---|---|---|
| `py/tt_master_data.py` → `py/master_data.py` | 各字典表的「确保存在」原语 | 改名 + 两个新函数 |
| `py/huguan_dashboard.py` | 户管看板纯逻辑（目录、diff、落库） | 门控表、`_named_hits`、`ensure_pending_master`、三处调用点 |
| `py/routes/tt_accounts_routes.py` | TT 账户路由 | import 改名 |
| `py/tests/test_tt_master_data.py` → `test_master_data.py` | 该模块的单测 | 改名 + FB 用例 |
| `py/tests/test_fb_huguan_dashboard.py` | FB 看板回归 | 新增补建用例 |
| `frontend/src/components/HuguanDashboardCard.vue` | 户管看板卡片 | kind 标签 + 文案按数据推导 |

---

## Task 1: 模块改名 `tt_master_data.py` → `master_data.py`

**Files:**
- Rename: `py/tt_master_data.py` → `py/master_data.py`
- Rename: `py/tests/test_tt_master_data.py` → `py/tests/test_master_data.py`
- Modify: `py/huguan_dashboard.py:13`、`py/routes/tt_accounts_routes.py:12`、`py/tests/test_tt_accounts.py`（2 处）

**Interfaces:**
- Consumes: 无
- Produces: `py/master_data.py` 导出 `ensure_bc` / `ensure_agent` / `strip_utc_prefix`（**名字都不变**，只有模块名变）

- [ ] **Step 1: 先确认全部引用点（全仓，别给文件白名单）**

Run: `grep -rn "tt_master_data" --include=*.py . | grep -v "\.venv" | grep -v worktrees`

Expected（2026-10-11 实测，共 7 处）：
```
./py/huguan_dashboard.py:13:from tt_master_data import ensure_agent, ensure_bc, strip_utc_prefix
./py/routes/tt_accounts_routes.py:12:from tt_master_data import ensure_bc, ensure_agent, strip_utc_prefix
./py/tests/test_tt_accounts.py:604:    from tt_master_data import ensure_bc
./py/tests/test_tt_accounts.py:883:    from tt_master_data import ensure_bc
./py/tests/test_tt_master_data.py:28:    from tt_master_data import strip_utc_prefix
./py/tests/test_tt_master_data.py:36:    from tt_master_data import ensure_bc
./py/tests/test_tt_master_data.py:61:    from tt_master_data import ensure_agent
```
若数量或位置与上面不同，**以实际 greps 为准**并逐条改。

- [ ] **Step 2: 改名并替换引用**

```bash
git mv py/tt_master_data.py py/master_data.py
git mv py/tests/test_tt_master_data.py py/tests/test_master_data.py
```
然后把上一步每一条命中里的 `tt_master_data` 逐字替换成 `master_data`
（`huguan_dashboard.py`、`tt_accounts_routes.py`、`test_tt_accounts.py`、`test_master_data.py`）。
同时把 `py/master_data.py` 模块 docstring 的第一句改成：
```
"""主数据「确保存在」规则 —— 各平台的字典表共用一份实现（原 tt_master_data，2026-10-11 改名）。
```
（保留原有那两行关于「从 tt_accounts_routes 提取、两条链路共用」的说明。）

- [ ] **Step 3: 跑全量回归**

Run: `cd py && python -m pytest tests/ -q`
Expected: PASS，通过数与改动前**相同**。这是「纯改名、行为不变」的证据。

- [ ] **Step 4: 确认没有漏网的旧名**

Run: `grep -rn "tt_master_data" --include=*.py . | grep -v "\.venv" | grep -v worktrees`
Expected: 无输出

- [ ] **Step 5: 提交**

```bash
git add py/master_data.py py/tt_master_data.py py/tests/test_master_data.py py/tests/test_tt_master_data.py py/huguan_dashboard.py py/routes/tt_accounts_routes.py py/tests/test_tt_accounts.py
git commit -m "refactor(fb-master-data): tt_master_data 改名 master_data（要加 FB 的字典项了）" -- py/master_data.py py/tt_master_data.py py/tests/test_master_data.py py/tests/test_tt_master_data.py py/huguan_dashboard.py py/routes/tt_accounts_routes.py py/tests/test_tt_accounts.py
```

---

## Task 2: 新增 `ensure_channel` / `ensure_asset_type`

**Files:**
- Modify: `py/master_data.py`（在 `ensure_agent` 之后追加）
- Test: `py/tests/test_master_data.py`

**Interfaces:**
- Consumes: 无
- Produces: `ensure_channel(db, name, uid) -> int | None`；`ensure_asset_type(db, name, uid) -> int | None`

- [ ] **Step 1: 写失败的测试**

追加到 `py/tests/test_master_data.py`：

```python
class TestEnsureFbDictionaries:
    """fb_channels / fb_asset_types 的幂等补建（设计 §4.4 / §4.4bis）。

    与 `ensure_agent` 的关键差别：这两张表**没有 deleted_at**（不像 tt_bcs），
    所以没有「软删复活」这一档；且 `platform` 必须**写死 'fb'` ——
    同步侧的 `_SQL_CHANNEL` / `_SQL_ASSET_TYPE` 写死了 `platform='fb'`，
    跟着请求侧的平台走会建出同步侧永远查不到的行。
    """

    def test_ensure_channel_creates_then_is_idempotent(self, client):
        from master_data import ensure_channel
        db = database.get_db()
        cid = ensure_channel(db, "渠道甲", 7)
        db.commit()
        assert cid is not None
        assert ensure_channel(db, "渠道甲", 7) == cid, "第二次必须复用，不再新建"
        assert db.execute("SELECT COUNT(*) FROM fb_channels WHERE name='渠道甲'"
                          ).fetchone()[0] == 1
        db.close()

    def test_ensure_channel_pins_platform_fb_and_owner(self, client):
        from master_data import ensure_channel
        db = database.get_db()
        ensure_channel(db, "渠道乙", 9)
        db.commit()
        row = db.execute("SELECT platform, owner_id FROM fb_channels WHERE name='渠道乙'"
                         ).fetchone()
        assert row["platform"] == "fb", "platform 必须写死 'fb'，不能跟请求侧走"
        assert row["owner_id"] == 9
        db.close()

    def test_ensure_channel_blank_name_is_noop(self, client):
        from master_data import ensure_channel
        db = database.get_db()
        assert ensure_channel(db, "", 7) is None
        assert ensure_channel(db, "   ", 7) is None
        assert ensure_channel(db, None, 7) is None
        db.commit()
        assert db.execute("SELECT COUNT(*) FROM fb_channels").fetchone()[0] == 0
        db.close()

    def test_ensure_asset_type_creates_then_is_idempotent(self, client):
        from master_data import ensure_asset_type
        db = database.get_db()
        tid = ensure_asset_type(db, "资产甲", 7)
        db.commit()
        assert tid is not None
        assert ensure_asset_type(db, "资产甲", 7) == tid
        assert db.execute("SELECT COUNT(*) FROM fb_asset_types WHERE name='资产甲'"
                          ).fetchone()[0] == 1
        assert db.execute("SELECT platform FROM fb_asset_types WHERE name='资产甲'"
                          ).fetchone()[0] == "fb"
        db.close()

    def test_ensure_channel_ignores_rows_of_other_platforms(self, client):
        """同名但 platform 不是 fb 的行不该被当成「已有」。"""
        from master_data import ensure_channel
        db = database.get_db()
        db.execute("INSERT INTO fb_channels(name, owner_id, platform) VALUES(?,?,?)",
                   ("同名", None, "gg"))
        db.commit()
        cid = ensure_channel(db, "同名", 7)
        db.commit()
        assert cid is not None
        assert db.execute("SELECT COUNT(*) FROM fb_channels WHERE name='同名'"
                          ).fetchone()[0] == 2, "fb 命名空间里没有 ⇒ 应当新建一行"
        db.close()
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd py && python -m pytest tests/test_master_data.py -q -k TestEnsureFbDictionaries`
Expected: FAIL —— `ImportError: cannot import name 'ensure_channel' from 'master_data'`

- [ ] **Step 3: 实现**

在 `py/master_data.py` 的 `ensure_agent` 之后追加：

```python
def ensure_channel(db, name, uid):
    """fb_channels 里没有就建，返回 id（名称为空返回 None）。

    与 `ensure_bc` 的关键差别：**这张表没有 `deleted_at`**（`database.py` 的建表里
    只有 name / owner_id / platform / created_at），所以没有「软删复活」这一档。

    `platform` **写死 'fb'**：同步侧的 `_SQL_CHANNEL` 就是
    `... WHERE name=? AND platform='fb'`；跟着请求侧的 effective platform 走，
    会建出**同步侧永远查不到**的行（看不见地重复建）。与 `ensure_agent` 写死 'tt' 同理。

    幂等：先查后插，不抛异常（既有 `/api/fb-channels/create` 对同名是 409 拒绝，
    我们这里是「确保存在」语义，不能抛）。
    """
    name = (name or "").strip()
    if not name:
        return None
    row = db.execute("SELECT id FROM fb_channels WHERE name=? AND platform='fb'",
                     (name,)).fetchone()
    if row:
        return row["id"]
    db.execute("INSERT INTO fb_channels(name, owner_id, platform) VALUES(?,?, 'fb')",
               (name, uid))
    return db.execute("SELECT last_insert_rowid()").fetchone()[0]


def ensure_asset_type(db, name, uid):
    """fb_asset_types 的 ensure。规则与 `ensure_channel` 逐条相同（表不同而已）。"""
    name = (name or "").strip()
    if not name:
        return None
    row = db.execute("SELECT id FROM fb_asset_types WHERE name=? AND platform='fb'",
                     (name,)).fetchone()
    if row:
        return row["id"]
    db.execute("INSERT INTO fb_asset_types(name, owner_id, platform) VALUES(?,?, 'fb')",
               (name, uid))
    return db.execute("SELECT last_insert_rowid()").fetchone()[0]
```

> **不要加缓存清理**：这两张表的列表端点（`py/main.py:6898` 注册的 `/api/fb-channels/list`）
> 是**直查**、没走 `_app_cache`。`ensure_agent` 要清缓存是因为 `agents` 的列表有缓存，
> 这两张表没有。实现后**再核一遍**（grep `_app_cache` 与这两张表），把结论写进报告。

- [ ] **Step 4: 跑测试确认通过**

Run: `cd py && python -m pytest tests/test_master_data.py -q`
Expected: PASS

- [ ] **Step 5: 全量回归 + 提交**

Run: `cd py && python -m pytest tests/ -q`
Expected: PASS

```bash
git add py/master_data.py py/tests/test_master_data.py
git commit -m "feat(fb-master-data): ensure_channel / ensure_asset_type（幂等、platform 写死 fb）" -- py/master_data.py py/tests/test_master_data.py
```

---

## Task 3: 门控改成映射表 + `_named_hits` 认下 FB 字段

**Files:**
- Modify: `py/huguan_dashboard.py`（`_PARSEABLE_FIELDS` 之后加表；`_named_hits:812-828`；`_collect_updates:1306-1322`）
- Test: `py/tests/test_fb_huguan_dashboard.py`

**Interfaces:**
- Consumes: `ensure_channel` / `ensure_asset_type`（Task 2，本任务还不调用）
- Produces: `_PENDING_MASTER_FIELDS`（模块级 dict）；FB 的 `build_diff` 现在会为 `channel_name` / `asset_type_name` 产出 `pending_master` 项 `{"kind","name","timezone","rows"}`

- [ ] **Step 1: 写失败的测试**

追加到 `py/tests/test_fb_huguan_dashboard.py`（该文件已有 `_fb_row` 等助手，见文件顶部）：

```python
def _fb_row_with_dicts(account_id, channel, asset_type):
    """一行 FB 表原始单元格：只填 D 资产UID / E 所属渠道 / F 资产类型。"""
    values = [""] * 17
    values[hd.col_index("D")] = account_id
    values[hd.col_index("E")] = channel
    values[hd.col_index("F")] = asset_type
    return values


class TestFbPendingMaster:
    """FB 的渠道 / 资产类型：系统里没有 ⇒ 产 pending，且**不再报「无法唯一匹配」**。

    这条「不再报警告」正是用户报的问题本身（现状是记一句
    「channel_name「X」无法唯一匹配，已跳过该列」并把整列丢掉）。
    """

    def test_missing_channel_produces_pending_and_no_warning(self, client):
        db = database.get_db()
        parsed = hd.parse_row(_fb_row_with_dicts("FB1", "新渠道", ""), "fb")
        parsed["row"] = 2
        diff = hd.build_diff(db, [parsed], "fb")
        assert diff["pending_master"] == [
            {"kind": "channel", "name": "新渠道", "timezone": None, "rows": 1}], \
            diff["pending_master"]
        assert not [w for w in diff["warnings"] if "channel_name" in w["message"]], \
            "不再报「channel_name 无法唯一匹配」"
        db.close()

    def test_missing_asset_type_produces_pending(self, client):
        db = database.get_db()
        parsed = hd.parse_row(_fb_row_with_dicts("FB2", "", "新资产类型"), "fb")
        parsed["row"] = 2
        diff = hd.build_diff(db, [parsed], "fb")
        assert [(m["kind"], m["name"]) for m in diff["pending_master"]] \
            == [("asset_type", "新资产类型")]
        assert not [w for w in diff["warnings"] if "asset_type_name" in w["message"]]
        db.close()

    def test_existing_channel_resolves_and_produces_no_pending(self, client):
        """系统里已有的渠道名 ⇒ 照常解析成 id，不产 pending（不能重复建）。"""
        db = database.get_db()
        db.execute("INSERT INTO fb_channels(name, owner_id, platform) VALUES('老渠道', 1, 'fb')")
        db.commit()
        parsed = hd.parse_row(_fb_row_with_dicts("FB3", "老渠道", ""), "fb")
        parsed["row"] = 2
        diff = hd.build_diff(db, [parsed], "fb")
        assert diff["pending_master"] == []
        assert not diff["warnings"]
        db.close()

    def test_dry_run_does_not_write_the_dictionaries(self, client):
        """干跑只产出报告，**不写库**。"""
        db = database.get_db()
        parsed = hd.parse_row(_fb_row_with_dicts("FB4", "干跑渠道", ""), "fb")
        parsed["row"] = 2
        hd.build_diff(db, [parsed], "fb")
        assert db.execute("SELECT COUNT(*) FROM fb_channels WHERE name='干跑渠道'"
                          ).fetchone()[0] == 0
        db.close()

    def test_tt_gate_unchanged(self, client):
        """TT 的 BC / 渠道 仍走原来的两条（门控换表不能改 TT）。"""
        from huguan_dashboard import _PENDING_MASTER_FIELDS
        assert _PENDING_MASTER_FIELDS[("tt", "bc_name")] == "bc"
        assert _PENDING_MASTER_FIELDS[("tt", "agent_name")] == "agent"
        assert ("gg", "agent_name") not in _PENDING_MASTER_FIELDS, "GG 一个都不命中"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd py && python -m pytest tests/test_fb_huguan_dashboard.py -q -k TestFbPendingMaster`
Expected: FAIL —— `AttributeError: module 'huguan_dashboard' has no attribute '_PENDING_MASTER_FIELDS'`，
且 `test_missing_channel_produces_pending_and_no_warning` 的 `pending_master` 为空。

- [ ] **Step 3a: 加门控表**

在 `py/huguan_dashboard.py` 的 `_parseable_fields` 函数之后插入：

```python
# 字段 → 待补建的字典项类别。**这是唯一的门控**：命中这个表才产 pending。
# 用数据表而不是 `platform == ".."` 分支 —— 将来加平台/加字段只是加一行，
# 不会再多一个「某平台走某分支」的地方（那种分支正是漏算新类别的温床：
# 2026-10-10 的教训就是加新类别时门控谓词没跟上）。
# GG 一个键都没有 ⇒ 行为逐字节不变。
_PENDING_MASTER_FIELDS = {
    ("tt", "bc_name"): "bc",
    ("tt", "agent_name"): "agent",
    ("fb", "channel_name"): "channel",
    ("fb", "asset_type_name"): "asset_type",
}
```

- [ ] **Step 3b: `_named_hits` 认下 FB 的两个字段**

把 `_named_hits`（`:812-828`）改成：

```python
def _named_hits(db, platform: str, field: str, value: str) -> int:
    """该名称命中了**几条**（0 / 1 / ≥2）。只为区分「没有」与「歧义」，不参与取值。

    `resolve_named_id` 对 0 条与 ≥2 条都返回 None，两者的处理却**相反**：
    0 条 = 系统里没有 ⇒ 产 pending、落库补建；≥2 条 = 歧义 ⇒ 仍警告跳过。
    本函数只数命中行数，**不改变 `resolve_named_id` 的取值口径**。

    FB 的两个字段也在这里认（2026-10-11）：它们走 fb_channels / fb_asset_types
    （不是 agents 表），而两张表都有 UNIQUE(name, platform) ⇒ 实际至多 1 条、
    没有歧义档，`hits == 0` 就等价于「系统里没有」。
    """
    if field == "bc_name":
        sql = _SQL_BC
    elif field == "agent_name":
        sql = _AGENT_SQL[platform]
        if sql is None:
            # 只有 fb 的 agent_name 是 None（它的「所属渠道」在 fb_channels 里，
            # 走下面 channel_name 那一支）⇒ 不进 pending 分支。
            return 0
    elif field == "channel_name":
        sql = _SQL_CHANNEL
    elif field == "asset_type_name":
        sql = _SQL_ASSET_TYPE
    else:
        return 0
    return len(db.execute(sql, (value,)).fetchall())
```

- [ ] **Step 3c: `_collect_updates` 的门控改查表**

把 `:1315-1322`（`hits = _named_hits(...)` 到 `continue`）整段换成：

```python
            hits = _named_hits(db, platform, f, value)
            kind = _PENDING_MASTER_FIELDS.get((platform, f))
            if kind and hits == 0:
                # 系统里没有这个名字 ⇒ 产 pending，落库阶段再补建（设计 §4.6）。
                # FB 的 channel_name / asset_type_name 从这里进来 ⇒ 不再落进下面那句
                # 警告、也不再「整列跳过」（那正是用户报的问题本身）。
                pending_master.append({"kind": kind, "name": value, "timezone": None})
                continue
            warnings.append({"row": row_no, "sheet": _conf_text(p.get("_sheet")),
                             "message": f"{f}「{value}」无法唯一匹配，已跳过该列"})
            continue
```

（把原来那句 `# **只 tt 产**（设计 §4.4）…` 的长注释一并删掉/替换 —— 它描述的是旧门控。）

- [ ] **Step 4: 跑测试确认通过**

Run: `cd py && python -m pytest tests/test_fb_huguan_dashboard.py -q -k TestFbPendingMaster`
Expected: PASS（5 passed）

- [ ] **Step 5: 全量回归**（TT/GG 不许变红）

Run: `cd py && python -m pytest tests/ -q`
Expected: PASS

- [ ] **Step 6: 提交**

```bash
git add py/huguan_dashboard.py py/tests/test_fb_huguan_dashboard.py
git commit -m "feat(fb-master-data): 门控改映射表，FB 渠道/资产类型产 pending（不再整列跳过）" -- py/huguan_dashboard.py py/tests/test_fb_huguan_dashboard.py
```

---

## Task 4: `ensure_pending_master` —— 拿掉 kind 的 `else` 兜底 + 三处调用点

**Files:**
- Modify: `py/huguan_dashboard.py`（新增 `ensure_pending_master`；三处调用点 `:1662` / `:1754` / `:1903`）
- Test: `py/tests/test_fb_huguan_dashboard.py`、`py/tests/test_huguan_dashboard.py`

**Interfaces:**
- Consumes: `ensure_bc` / `ensure_agent`（既有）、`ensure_channel` / `ensure_asset_type`（Task 2）、`_ensure_region`（既有，本文件内）
- Produces: `ensure_pending_master(db, items, owner_id) -> dict`

- [ ] **Step 1: 写失败的测试**

追加到 `py/tests/test_fb_huguan_dashboard.py`：

```python
class TestEnsurePendingMasterDispatch:
    """kind 分派必须**显式穷举**。曾经的 `else: _ensure_region(...)` 兜底会让
    新增的 kind 被静默写进 regions 表（把渠道名当国家），而且不报错。"""

    def test_unknown_kind_raises_instead_of_falling_into_region(self, client):
        import pytest
        db = database.get_db()
        with pytest.raises(ValueError):
            hd.ensure_pending_master(db, [{"kind": "不存在的类别", "name": "X"}], 1)
        assert db.execute("SELECT COUNT(*) FROM regions WHERE name='X'").fetchone()[0] == 0, \
            "绝不能落进 regions"
        db.close()

    def test_channel_kind_creates_and_maps_to_channel_id(self, client):
        db = database.get_db()
        out = hd.ensure_pending_master(db, [{"kind": "channel", "name": "派单渠道"}], 3)
        db.commit()
        assert set(out) == {"channel_id"}
        assert out["channel_id"] == db.execute(
            "SELECT id FROM fb_channels WHERE name='派单渠道'").fetchone()[0]
        db.close()

    def test_region_kind_creates_nothing_to_map(self, client):
        db = database.get_db()
        out = hd.ensure_pending_master(
            db, [{"kind": "region", "name": "美国", "timezone": "+8"}], 3)
        db.commit()
        assert out == {}, "region 没有可挂的 id"
        assert db.execute("SELECT COUNT(*) FROM regions WHERE name='美国'").fetchone()[0] == 1
        db.close()

    def test_empty_items_is_noop(self, client):
        db = database.get_db()
        assert hd.ensure_pending_master(db, None, 1) == {}
        assert hd.ensure_pending_master(db, [], 1) == {}
        db.close()


class TestFbMasterDataEndToEnd:
    """走真实路径：build_diff → apply_diff，确认字典项真被补建**且挂到账户上**。"""

    def test_confirm_creates_the_channel_and_links_it(self, client):
        db = database.get_db()
        parsed = hd.parse_row(_fb_row_with_dicts("FB9", "端到端渠道", "端到端资产"), "fb")
        parsed["row"] = 2
        diff = hd.build_diff(db, [parsed], "fb")
        res = hd.apply_diff(db, diff, "fb",
                            {"create": ["FB9"], "update": [], "owner": []}, user_id=1)
        db.commit()
        assert res.get("created", 1) == 1
        acc = db.execute("SELECT channel_id, asset_type_id FROM fb_accounts "
                         "WHERE account_id='FB9'").fetchone()
        ch = db.execute("SELECT id FROM fb_channels WHERE name='端到端渠道'").fetchone()
        at = db.execute("SELECT id FROM fb_asset_types WHERE name='端到端资产'").fetchone()
        assert acc["channel_id"] == ch["id"], "新账户必须挂上补建的渠道"
        assert acc["asset_type_id"] == at["id"], "新账户必须挂上补建的资产类型"
        db.close()

    def test_second_sync_creates_nothing_new(self, client):
        """再同步一次：字典项已存在 ⇒ pending 为空、表里行数不变（不会重复建）。"""
        db = database.get_db()
        parsed = hd.parse_row(_fb_row_with_dicts("FB10", "幂等渠道", ""), "fb")
        parsed["row"] = 2
        diff1 = hd.build_diff(db, [parsed], "fb")
        hd.apply_diff(db, diff1, "fb", {"create": ["FB10"], "update": [], "owner": []},
                      user_id=1)
        db.commit()
        n1 = db.execute("SELECT COUNT(*) FROM fb_channels WHERE name='幂等渠道'").fetchone()[0]
        diff2 = hd.build_diff(db, [parsed], "fb")
        assert diff2["pending_master"] == [], "第二次不该再有待补建项"
        assert db.execute("SELECT COUNT(*) FROM fb_channels WHERE name='幂等渠道'"
                          ).fetchone()[0] == n1
        db.close()
```

**TT 不新增用例**——`py/tests/test_huguan_dashboard.py` 里**已经有**一批「tt 字典项补建」的
既有用例，它们本身就是 TT 行为的回归锚。先确认那批用例存在：

Run: `grep -n "pending_master" py/tests/test_huguan_dashboard.py | head`

Expected: 有多条命中（若一条都没有，说明本计划的前提不成立，**停下来报告**，不要凭空补一条）。
本任务对 TT 的要求就是：**那批用例在 Step 5 的全量回归里全绿**，报告里写明这一点即可。

- [ ] **Step 2: 跑测试确认失败**

Run: `cd py && python -m pytest tests/test_fb_huguan_dashboard.py -q -k "Dispatch or EndToEnd"`
Expected: FAIL —— `AttributeError: ... no attribute 'ensure_pending_master'`

- [ ] **Step 3a: 新增 `ensure_pending_master`**

放在 `py/huguan_dashboard.py` 的 `_ensure_region` 之后（**不要放进 `master_data.py`** ——
它要调本文件的 `_ensure_region`，放过去会造成 `master_data → huguan_dashboard → master_data` 的循环 import）：

```python
def ensure_pending_master(db, items, owner_id) -> dict:
    """补建一行引用的全部字典项，返回要写进账户行的 `{列名: id}`。

    **kind 必须显式穷举，末位 `raise`**：这里曾经是 `else: _ensure_region(...)` 的兜底，
    新增 kind 若漏改就会被**静默写进 regions 表**（把渠道名当国家写进去），而且不报错。
    不知道的类别要当场炸，不要猜。

    `region` 没有可挂的 id ⇒ 只建、不进返回值。
    """
    out = {}
    for x in items or []:
        kind = x.get("kind")
        if kind == "bc":
            out["bc_id"] = ensure_bc(db, x["name"], owner_id)
        elif kind == "agent":
            out["agent_id"] = ensure_agent(db, x["name"], owner_id)
        elif kind == "channel":
            out["channel_id"] = ensure_channel(db, x["name"], owner_id)
        elif kind == "asset_type":
            out["asset_type_id"] = ensure_asset_type(db, x["name"], owner_id)
        elif kind == "region":
            _ensure_region(db, x["name"], x.get("timezone"))
        else:
            raise ValueError(f"未知的字典项类别: {kind!r}")
    return out
```

并把文件顶部的 import 改成：
```python
from master_data import (ensure_agent, ensure_asset_type, ensure_bc,
                         ensure_channel, strip_utc_prefix)
```

- [ ] **Step 3b: 三处调用点**

**新建分支（`:1662-1667`）** —— 整段
```python
            for x in item.get("pending_master") or []:
                if x["kind"] == "bc":
                    ...
                else:
                    _ensure_region(db, x["name"], x.get("timezone"))
```
换成
```python
            src.update(ensure_pending_master(db, item.get("pending_master"),
                                             item.get("owner_id")))
```

**更新分支（`:1754-1759`）** —— 同形换成
```python
            fields.update(ensure_pending_master(db, item.get("pending_master"),
                                                item.get("scope_owner_id")))
```

**孤儿行（`:1903-1912`）** —— 那次循环 + 下面那个 `if link:` 换成
```python
            # 原有的「None 不挂链」口径保留（ensure_bc / ensure_agent 只在名称为空时返 None）。
            link = {k: v for k, v in ensure_pending_master(
                db, item.get("pending_master"), item.get("scope_owner_id")).items()
                if v is not None}
            if link:
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd py && python -m pytest tests/test_fb_huguan_dashboard.py -q`
Expected: PASS

- [ ] **Step 5: 全量回归**

Run: `cd py && python -m pytest tests/ -q`
Expected: PASS（TT/GG 既有用例一条都不许变红 —— 这是抽函数没改行为的证据）

- [ ] **Step 6: 提交**

```bash
git add py/huguan_dashboard.py py/tests/test_fb_huguan_dashboard.py
git commit -m "feat(fb-master-data): kind 分派显式穷举（拿掉 else 兜底），三处调用点统一" -- py/huguan_dashboard.py py/tests/test_fb_huguan_dashboard.py
```

---

## Task 5: 前端 —— kind 标签 + 文案改按数据推导

**Files:**
- Modify: `frontend/src/components/HuguanDashboardCard.vue`

**Interfaces:**
- Consumes: 后端 `diff.pending_master[].kind` 现在会出现 `"channel"` / `"asset_type"`
- Produces: `HD_MASTER_KIND_LABEL` 含 5 个 kind；`hdMasterKindList` computed

- [ ] **Step 1: 加 kind 标签**

`frontend/src/components/HuguanDashboardCard.vue` 的 `HD_MASTER_KIND_LABEL`（约 `:1211`）改成：

```js
// kind → 中文名。`agent` 是 **TT** 的「所属渠道」（agents 表）；FB 的走 `channel`
// （fb_channels 表）—— 两者是不同字典，标签各自对齐自己表里的表头原文，不互相改。
const HD_MASTER_KIND_LABEL = {
  bc: 'BC', agent: '渠道', region: '国家时区',
  channel: '所属渠道', asset_type: '资产类型',
}
```

- [ ] **Step 2: 三处写死的文案改成按数据推导**

`HD_MASTER_KIND_LABEL` 之后加：

```js
// 「将新增的字典项」那一节说明文案里的类别清单，**从本次实际出现的 kind 推导**。
// 原先写死成「BC / 渠道 / 国家时区」——2026-10-11 加 FB 的两个新类别时它就没跟上，
// 正是「写死的清单必漂」。改成从数据推就不会有第二次。
const HD_MASTER_KIND_ORDER = ['bc', 'agent', 'channel', 'asset_type', 'region']
const hdMasterKindList = computed(() => {
  const present = new Set((hdPendingMaster.value || []).map(m => m && m.kind))
  return HD_MASTER_KIND_ORDER.filter(k => present.has(k)).map(hdMasterKindLabel).join(' / ')
})
```

把模板里那三处的字面量（约 `:728` / `:729` / `:731`）替换成插值，逐条是：

```html
<template v-if="hdMasterPartial">这些是本次同步计划写入系统字典的 {{ hdMasterKindList }}；其中未能落库的项，原因见上方错误 / 未落库说明（也可能是对应行未勾选）。</template>
<template v-else>这些是本次同步自动写入系统字典的 {{ hdMasterKindList }}。</template>
...
<template v-else>这些是系统里还没有的 {{ hdMasterKindList }}，确认同步后会自动创建。</template>
```

> `hdMasterKindList` 为空串的情况不会发生：那一节整个 `v-if="hdPendingMaster.length"`，
> 有空项时至少会有一个 kind。**但还是核一眼**：若某条 `pending_master` 缺 `kind`，
> `filter` 会把它滤掉 → 文案变成「系统里还没有的 ，确认…」。若你担心，把
> `hdMasterKindList` 的空值兜一个 `'字典项'` 是允许的（自行决定并在报告里说明）。

- [ ] **Step 3: 构建 + 纯逻辑测试**

Run: `cd frontend && npx vite build`
Expected: 构建成功

Run: `cd frontend && npm test`
Expected: 全绿（既有 63 条）

- [ ] **Step 4: 提交**

```bash
git add frontend/src/components/HuguanDashboardCard.vue
git commit -m "feat(fb-master-data): 字典项 kind 标签补两个，文案改按数据推导（不再写死类别清单）" -- frontend/src/components/HuguanDashboardCard.vue
```

---

## Task 6: 收尾 —— 全量回归 + 人工验收清单

**Files:**
- Modify: 无（只跑回归）

- [ ] **Step 1: 后端全量**

Run: `cd py && python -m pytest tests/ -q`
Expected: 全绿，且通过数 **≥ 改动前基线**。变红必须先查清原因，**不许改测试让它变绿**。

- [ ] **Step 2: 前端全量 + 构建**

Run: `cd frontend && npm test && npx vite build`
Expected: 全绿 + 构建成功

- [ ] **Step 3: 把下面这份清单贴进交付说明**

（清单内容见本节末尾「人工验收清单」，或直接引用 `docs/superpowers/specs/2026-10-11-fb-master-data-auto-create-design.md` 的 §六之二。）

---

## 人工验收清单（全部由用户在浏览器里点；我不启动任何进程）

**前置（都由用户执行）**：`cd frontend && npm run build`，然后重启 Flask。

- [ ] FB 同步一张含**系统里没有的渠道名**的表 → 预演弹窗出现「将新增的字典项」一节，列出「所属渠道 · XX · N 行」
- [ ] 同一张表**不再出现**「channel_name「XX」无法唯一匹配，已跳过该列」这条警告
- [ ] 该行**其他列**照常出现在「新增账户」里（渠道不再拖累整行）
- [ ] 点确认 → `fb_channels` 多了一行，且该账户的「所属渠道」**显示出名字**（不是空白）
- [ ] 资产类型同款
- [ ] **只干跑不确认** → `fb_channels` / `fb_asset_types` 行数**不变**
- [ ] 同一批表数据**再同步一次** → 「将新增的字典项」一节**为空**（不会重复建）
- [ ] 那一节的文案说对了词（FB 出现「所属渠道 / 资产类型」，不出现「BC / 国家时区」）
- [ ] **TT 回归**：TT 的「加白户」表仍照常补建 BC / 渠道（门控换表没改 TT）
- [ ] **GG 回归**：GG 的看板同步行为完全没变

---

## Self-Review 记录

**Spec 覆盖**：§4.1→Task 3a；§4.2→Task 3b；§4.3→Task 4；§4.4→Task 2；§4.4bis→Task 2 的 Step 3 注释与 Step 3 的「不要加缓存清理」；§4.5→Task 1；§4.6→Task 3+4 的用例；§4.7→Task 5；§五 非目标→Global Constraints；§六 测试→各任务 Step 1；§六之二 人工验收→文末清单。

**自审修正记录**（写完重读时抓到的）：
1. Task 4 初稿在 TT 锚那儿放了一段带 `...` 的测试骨架 —— **那是占位符，writing-plans 明令禁止**。
   已改为「先 grep 确认既有 `pending_master` 用例存在，靠它们做 TT 回归锚」。
2. Task 2 的一条测试初稿用了 `"...VALUES('同名','?','gg')".replace("'?'","NULL")` 这种别扭拼接
   —— 已直接改成参数化绑定 `db.execute(..., ("同名", None, "gg"))`。

**已知的取舍**（供审查者核对）：
- Task 5 的 `hdMasterKindList` 空值兜底留给实现者自行决定（计划里已写明允许范围与理由）。

**类型一致性核对**：`ensure_channel` / `ensure_asset_type` / `ensure_pending_master` 的签名在
Task 2/3/4 里逐处一致；`_PENDING_MASTER_FIELDS` 的键是 `(platform, field)` 二元组、
值是 kind 字符串，Task 3 与 Task 4 的 kind 取值（`bc` / `agent` / `channel` / `asset_type` / `region`）
与 Task 5 前端的 `HD_MASTER_KIND_ORDER` 逐个对齐。
