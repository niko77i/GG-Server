# TT 表头映射 · 第二批（前端列映射 UI）实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让户管在 TT 设置页的户管看板卡片里**看到每张表当前每一列被认成了什么**，把认不出的列指派给系统字段（或显式选择「不采集」），并能从同步报告的未采集提示直接跳到指派处。

**Architecture:** 后端补三个只读/校验能力（读表头端点、字段目录暴露、覆盖值空串＝刻意不采集），前端把那套「表头 → 下拉行状态」的换算抽成纯 JS 模块（`node --test` 覆盖），Vue 组件只做渲染与事件绑定；列映射的改动**复用卡片现有的保存按钮**走同一条 POST，不新增第二条配置写路径。

**Tech Stack:** Python 3.11 / Flask / SQLite / pytest（后端）；Vue 3 + Element Plus + Vite / `node --test`（前端）。

设计依据：`docs/superpowers/specs/2026-10-10-tt-header-mapping-frontend-design.md`（下称"设计 §X"）。
第一批（后端机制）已实现并终审判 Ready，本计划**不改**其四条写链路。

## Global Constraints

- **GG / FB 逐字节不变**：`COLUMN_SPEC` / `KEY_COL` / `OWNER_COL` / `OWNER_CHANNEL_COL` 全部保留；
  `GET /api/huguan/dashboard` 的 gg/fb 载荷形状不变（`tt_field_catalog` 只加在 tt 分支）。
- **只存手工覆盖**（表头原文 → 字段key），不存自动识别结果；键允许是当前表里不存在的表头名（同步时记 warning）。
- **`""` 是唯一的空语义魔法值**：覆盖值为空串 ⇔ 刻意不采集（既不映射、也不进 `unmatched`）。不引入第二个。
- **不引入第二条配置写路径**：列映射也走卡片那一个保存按钮 → 既有 POST。
- `columns` 的键与 `unmatched` 里报的表头名，**一律是 `strip()` 后的表头原文**（后端匹配与存键的口径）。
- **提交纪律**：只 `git add` 本任务列出的文件。**禁止 `git add -A` / `git add .` / `git checkout` / `git restore` / `git stash` / `git pull` / `git push`**（本工作区有并行会话，checkout/restore 会静默销毁别人未提交的编辑）。提交一律用显式 pathspec：
  `git commit -m "<msg>" -- <文件...>`
- 测试命令：后端 `cd py && python -m pytest tests/<file> -q`（用 `client`/`app` 夹具，**不得**裸用真实 `temp/app.db`；Google Sheets 一律 monkeypatch，sync 路由的桩缝是 `gs.read_sheet_values`）；前端 `cd frontend && npm test`。
- **不启动任何进程/服务**（5001 与前端 dev server 由用户控制）。

---

## 文件结构

| 文件 | 职责 | 本次改动 |
|---|---|---|
| `py/huguan_dashboard.py` | 户管看板双向同步的纯逻辑层 | `resolve_column_map` 支持「覆盖＝空串」；新增 `describe_header_columns`（逐列来源）、`tt_field_catalog`（前端下拉数据源） |
| `py/routes/huguan_dashboard_routes.py` | 户管看板 HTTP 入口 | 新端点 `GET /sheet-headers`；GET 配置的 tt 分支加 `tt_field_catalog`；POST 校验放行空串 |
| `py/tests/test_huguan_dashboard.py` | 后端测试 | 按各任务扩充 |
| `frontend/src/api/huguan.js` | 前端 API 封装 | 加 `getSheetHeaders` |
| `frontend/src/utils/columnMapping.mjs` | **新**：表头响应 ↔ 下拉行状态的纯换算 | 新建（**必须 `.mjs`**：`package.json` 无 `"type": "module"`，`.js` 会被 Node 当 CJS 解析 ⇒ `node --test` 报 ESM 语法错；既有 `columnPrefsLogic.mjs` 同理） |
| `frontend/tests/columnMappingLogic.test.mjs` | **新**：上面那块的单测 | 新建 |
| `frontend/src/components/HuguanDashboardCard.vue` | TT 看板卡片（1237 行） | 每表加「列映射」折叠区；差异弹窗加「未采集列」提示与「去指派」跳转 |

---

## Task 1: 覆盖值空串 ＝ 刻意不采集（后端语义 + 校验）

**Files:**
- Modify: `py/huguan_dashboard.py`（`resolve_column_map` 的**第一轮：手工覆盖**）
- Modify: `py/routes/huguan_dashboard_routes.py`（POST 的 `columns` 校验块）
- Test: `py/tests/test_huguan_dashboard.py`

**Interfaces:**
- Consumes: 第一批的 `resolve_column_map(headers, overrides) -> (col_map, unmatched)`、路由里的 `hd._TT_CATALOG_FIELDS`
- Produces: 覆盖值 `""` 的既定语义（供 Task 2 的 `describe_header_columns` 与 Task 4 的端点依赖）

- [ ] **Step 1: 写失败测试**

追加到 `py/tests/test_huguan_dashboard.py` 的 `TestResolveColumnMap` 类里：

```python
    def test_override_empty_string_means_deliberately_ignored(self):
        """覆盖值空串 = 刻意不采集：既不映射，也不进未采集（用户显式关掉的列不该再报噪音）。"""
        m, unmatched = hd.resolve_column_map(["账户ID", "备注二"], {"备注二": ""})
        assert unmatched == [], f"刻意不采集不该再报未采集，实际={unmatched}"
        assert "B" not in m.values()
        assert m.get("advertiser_id") == "A"

    def test_override_empty_string_beats_alias(self):
        """空串也是一种覆盖 ⇒ 优先级最高，压过别名自动匹配。"""
        m, unmatched = hd.resolve_column_map(["账户ID", "日期"], {"日期": ""})
        assert unmatched == []
        assert "acquired_date" not in m, "覆盖空串应压过别名"
        assert "B" not in m.values()
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd py && python -m pytest tests/test_huguan_dashboard.py -q -k override_empty_string`
Expected: FAIL —— 两条都会红（当前空串会落进 `catalog_fields` 判定失败分支 ⇒ 进 `unmatched`；第二条断言 `"acquired_date" not in m` 也会红）

- [ ] **Step 3: 实现（`resolve_column_map` 第一轮）**

把第一轮改成（新增的只有 `field == ""` 那三行，位置在取到 `field` 之后、目录判定之前）：

```python
    # 第一轮：手工覆盖
    for i, raw in enumerate(headers):
        name = ("" if raw is None else str(raw)).strip()
        if not name or name not in (overrides or {}):
            continue
        field = (overrides or {})[name]
        # 覆盖值空串 = 用户显式「刻意不采集」（设计 §3.3）：占用该列，既不映射也不上报。
        # 与目录里空串哨兵（「位置」）同档 —— 等于「手工把任意列降级为 ignore」。
        # 必须在目录判定**之前**，因为空串本就不是目录里的字段。
        if field == "":
            taken.add(_col_letter(i))
            continue
        if field not in catalog_fields or not _claim(field, _col_letter(i)):
            unmatched.append(name)
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd py && python -m pytest tests/test_huguan_dashboard.py -q -k TestResolveColumnMap`
Expected: PASS（既有用例 + 2 条新用例全绿）

- [ ] **Step 5: 写 POST 校验的失败测试**

追加到 `py/tests/test_huguan_dashboard.py` 的 `TestColumnsConfig` 类里：

```python
    def test_post_accepts_empty_string_as_deliberately_ignored(self, client):
        """覆盖值空串合法（刻意不采集），且允许多列同时指定空串（不去重）。"""
        hg, _ = _create_user(client, "_cc6", role="huguan")
        resp = client.post("/api/huguan/dashboard", headers=hg, json={
            "platform": "tt", "spreadsheet_id": "T1",
            "tables": [{"name": "企业户", "sheet_name": "企业户",
                        "columns": {"位置2": "", "备注二": "", "负责人": "owner_name"}}]})
        assert resp.status_code == 200, resp.get_json()
        tt = client.get("/api/huguan/dashboard", headers=hg).get_json()["config"]["tt"]
        assert tt["tables"][0]["columns"] == {"位置2": "", "备注二": "", "负责人": "owner_name"}
```

- [ ] **Step 6: 跑测试确认失败**

Run: `cd py && python -m pytest tests/test_huguan_dashboard.py -q -k empty_string_as_deliberately`
Expected: FAIL —— 400（`列「位置2」指向了未知字段「」`）

- [ ] **Step 7: 实现（POST 校验放行空串）**

把校验循环改成（新增的是最前面那条 `continue`）：

```python
                seen_fields = set()
                for header, field in cols.items():
                    # 空串 = 用户显式「刻意不采集」（设计 §3.3）：合法，且**允许多列同时指定** ——
                    # 所以它既不查目录，也不进 seen_fields 去重。
                    if isinstance(field, str) and field == "":
                        continue
                    # 非字符串字段key 一律按未知处理（否则下面 `not in set` 对 list/dict
                    # 等不可哈希值会抛 TypeError → 500；本层契约是畸形输入 400 而非 500）。
                    if not isinstance(field, str) or field not in hd._TT_CATALOG_FIELDS:
                        return err(f"列「{header}」指向了未知字段「{field}」", 400)
                    if field in seen_fields:
                        return err(f"字段「{field}」被两列同时指定", 400)
                    seen_fields.add(field)
```

- [ ] **Step 8: 跑测试 + 既有校验回归**

Run: `cd py && python -m pytest tests/test_huguan_dashboard.py -q -k "TestColumnsConfig or TestResolveColumnMap"`
Expected: PASS（含第一批 Task 8 的 5 条既有校验用例）

- [ ] **Step 9: 提交**

```bash
git commit -m "feat(tt): 覆盖值空串=刻意不采集（解析不映射不上报 + POST 放行）" -- py/huguan_dashboard.py py/routes/huguan_dashboard_routes.py py/tests/test_huguan_dashboard.py
```

---

## Task 2: `describe_header_columns`（逐列摊开来源）

**Files:**
- Modify: `py/huguan_dashboard.py`（紧接 `resolve_column_map` / `_col_letter` 之后新增）
- Test: `py/tests/test_huguan_dashboard.py`

**Interfaces:**
- Consumes: `resolve_column_map` 的产出（`col_map`、`unmatched`）、`_col_letter`、`TT_FIELD_CATALOG`
- Produces: `describe_header_columns(headers: list, overrides: dict, col_map: dict, unmatched: list) -> list[dict]`
  —— 每项 `{"header": str, "field": str | None, "via": "override"|"alias"|"ignored"|"none"}`；
  `field == ""` 只与 `"ignored"` 同现，`field is None` 只与 `"none"` 同现；空表头列不列出。

- [ ] **Step 1: 写失败测试**

追加到 `py/tests/test_huguan_dashboard.py`（新类，放在 `TestResolveColumnMap` 之后）：

```python
class TestDescribeHeaderColumns:
    """列映射 UI 的数据源：逐列摊开「认成了什么 + 怎么认的」。"""

    ENTERPRISE = ["日期", "是否回收", "账户ID", "主体名称", "账户名称", "BC",
                  "国家", "所属渠道", "接户运营", "时区", "下户链接"]

    def _describe(self, headers, overrides):
        m, unmatched = hd.resolve_column_map(headers, overrides)
        return hd.describe_header_columns(headers, overrides, m, unmatched), unmatched

    def test_alias_and_ignored_and_none_are_distinguished(self):
        rows, _u = self._describe(["账户ID", "位置", "备注二"], {})
        assert rows == [
            {"header": "账户ID", "field": "advertiser_id", "via": "alias"},
            {"header": "位置", "field": "", "via": "ignored"},
            {"header": "备注二", "field": None, "via": "none"},
        ]

    def test_override_and_empty_override_are_reported_as_override(self):
        rows, _u = self._describe(["账户ID", "负责人", "备注二"],
                                  {"负责人": "owner_name", "备注二": ""})
        assert rows[1] == {"header": "负责人", "field": "owner_name", "via": "override"}
        assert rows[2] == {"header": "备注二", "field": "", "via": "ignored"}

    def test_blank_headers_are_skipped(self):
        rows, _u = self._describe(["账户ID", "", "  "], {})
        assert [r["header"] for r in rows] == ["账户ID"]

    def test_enterprise_table_is_fully_describable(self):
        rows, unmatched = self._describe(self.ENTERPRISE, {})
        assert unmatched == []
        assert [r["via"] for r in rows] == ["alias"] * len(self.ENTERPRISE)
        assert [r["field"] for r in rows][:3] == ["acquired_date", "_dead_flag", "advertiser_id"]
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd py && python -m pytest tests/test_huguan_dashboard.py -q -k TestDescribeHeaderColumns`
Expected: FAIL —— `AttributeError: module 'huguan_dashboard' has no attribute 'describe_header_columns'`

- [ ] **Step 3: 实现**

在 `py/huguan_dashboard.py` 的 `_col_letter` 之后追加：

```python
def describe_header_columns(headers: list, overrides: dict,
                            col_map: dict, unmatched: list) -> list:
    """把一次表头解析的结果摊成「逐列一行」，供前端列映射 UI 显示（设计 §3.1）。

    每项：{"header": strip 后的表头原文, "field": 字段key | "" | None, "via": 四档}

      via = "override" 该表手工指派 / "alias" 别名自动认出 /
            "ignored" 认识但刻意不采集（目录哨兵「位置」，或覆盖值为空串）/ "none" 完全不认识
      field = "" 只与 "ignored" 同现；field = None 只与 "none" 同现。

    **不重新解析**：全部从 resolve_column_map 的三个产出（col_map / unmatched / overrides）
    反推，避免第二套「认列」逻辑（那是本批最容易漂的地方）。空表头列不列出
    —— 与 resolve_column_map 的跳过口径一致。
    """
    field_by_letter = {col: field for field, col in col_map.items()}
    ov = overrides or {}
    unknown = set(unmatched)
    rows = []
    for i, raw in enumerate(headers):
        name = ("" if raw is None else str(raw)).strip()
        if not name:
            continue
        if name in ov and ov[name] == "":
            # 覆盖空串：认识但刻意不采集（占用该列，不在 col_map 里）
            rows.append({"header": name, "field": "", "via": "ignored"})
            continue
        field = field_by_letter.get(_col_letter(i))
        if field is None:
            # 该列没进 col_map：要么根本不认识（在 unmatched 里），要么是目录哨兵那一档
            if name in unknown:
                rows.append({"header": name, "field": None, "via": "none"})
            else:
                rows.append({"header": name, "field": "", "via": "ignored"})
            continue
        via = "override" if ov.get(name) == field else "alias"
        rows.append({"header": name, "field": field, "via": via})
    return rows
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd py && python -m pytest tests/test_huguan_dashboard.py -q -k TestDescribeHeaderColumns`
Expected: PASS（4 条）

- [ ] **Step 5: 提交**

```bash
git commit -m "feat(huguan): describe_header_columns——逐列摊开认列结果与来源" -- py/huguan_dashboard.py py/tests/test_huguan_dashboard.py
```

---

## Task 3: 字段目录暴露给前端

**Files:**
- Modify: `py/huguan_dashboard.py`（新增 `tt_field_catalog`）
- Modify: `py/routes/huguan_dashboard_routes.py`（`dashboard_config_get` 的 tt 分支）
- Test: `py/tests/test_huguan_dashboard.py`

**Interfaces:**
- Consumes: `TT_FIELD_CATALOG`、`field_spec("tt")`（**与 POST 校验同源**，防「前端能选、后端拒绝」）
- Produces: `tt_field_catalog() -> list[dict]`，每项
  `{"key", "label", "direction", "writable", "readable", "key_col"}`；GET 响应的 `config.tt.tt_field_catalog`

- [ ] **Step 1: 写失败测试**

```python
class TestFieldCatalogExposure:
    def test_catalog_excludes_the_ignore_sentinel(self):
        """目录是前端下拉的数据源：只含真字段，绝不含空串哨兵（否则前端能选、后端必拒）。"""
        cat = hd.tt_field_catalog()
        keys = [c["key"] for c in cat]
        assert "" not in keys, "空串哨兵不该出现在目录里"
        assert "advertiser_id" in keys and "subject_name" in keys and "landing_url" in keys
        assert set(keys) == set(hd.field_spec("tt")), "必须与 POST 校验同源"

    def test_catalog_marks_the_key_column_and_directions(self):
        by_key = {c["key"]: c for c in hd.tt_field_catalog()}
        assert by_key["advertiser_id"]["key_col"] is True
        assert by_key["owner_change_note"]["direction"] == "r"      # 只读回
        assert by_key["landing_url"]["writable"] is True
        assert by_key["owner_change_note"]["writable"] is False

    def test_get_config_exposes_catalog_for_tt_only(self, client):
        hg, _ = _create_user(client, "_fc1", role="huguan")
        conf = client.get("/api/huguan/dashboard", headers=hg).get_json()["config"]
        assert isinstance(conf["tt"]["tt_field_catalog"], list)
        assert conf["tt"]["tt_field_catalog"], "tt 目录不该为空"
        for p in ("gg", "fb"):
            assert "tt_field_catalog" not in conf[p], f"{p} 的载荷形状不该变"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd py && python -m pytest tests/test_huguan_dashboard.py -q -k TestFieldCatalogExposure`
Expected: FAIL —— `AttributeError: ... 'tt_field_catalog'`

- [ ] **Step 3: 实现**

`py/huguan_dashboard.py`（紧跟 `spec_column_map` 之后）：

```python
def tt_field_catalog() -> list:
    """TT 字段目录（供前端「列映射」下拉）：只含**真正的字段**，排除空串哨兵。

    与 POST 校验**同源**（都出自 TT_FIELD_CATALOG / field_spec("tt")）—— 否则会出现
    「下拉里能选、保存时被 400 拒」这种漂移。`key_col` 给前端把定位键标成必选；
    `direction == "r"` 的标「只读回」。
    """
    spec = field_spec("tt")
    return [{"key": f, "label": label, "direction": d,
             "writable": spec[f]["writable"], "readable": spec[f]["readable"],
             "key_col": spec[f]["key"]}
            for f, label, _aliases, d, _key, _skip in TT_FIELD_CATALOG if f]
```

`py/routes/huguan_dashboard_routes.py` 的 `dashboard_config_get`，在 tt 分支里 `entry["tables"] = tables` 之后加一行：

```python
                # 列映射 UI 的下拉数据源（设计 §3.2）。只加在 tt 分支：gg/fb 载荷形状不变。
                entry["tt_field_catalog"] = hd.tt_field_catalog()
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd py && python -m pytest tests/test_huguan_dashboard.py -q -k TestFieldCatalogExposure`
Expected: PASS（3 条）

- [ ] **Step 5: 提交**

```bash
git commit -m "feat(tt): GET 配置暴露字段目录（与 POST 校验同源）" -- py/huguan_dashboard.py py/routes/huguan_dashboard_routes.py py/tests/test_huguan_dashboard.py
```

---

## Task 4: 「读表头」端点

**Files:**
- Modify: `py/routes/huguan_dashboard_routes.py`（在 `owner-options` 端点之后新增）
- Test: `py/tests/test_huguan_dashboard.py`

**Interfaces:**
- Consumes: Task 2 的 `describe_header_columns`、`resolve_column_map`、`get_platform_tables`（带 `columns`）
- Produces: `GET /api/huguan/dashboard/sheet-headers?platform=tt&sheet_name=<名>` →
  `{"columns": [{"header","field","via"}...], "unmatched": [表头...]}`

- [ ] **Step 1: 写失败测试**

```python
class TestSheetHeadersEndpoint:
    """列映射 UI 的「读取表头」：把某张表第 1 行摊成逐列来源。"""

    def _conf(self, client, username, tables):
        hg, _ = _create_user(client, username, role="huguan")
        db = database.get_db()
        db.execute("INSERT OR REPLACE INTO config(key,value) VALUES(?,?)",
                   (f"huguan_dashboard_{_uid_of(username)}", json.dumps(
                       {"tt": {"spreadsheet_id": "SS", "tables": tables}})))
        db.commit(); db.close()
        return hg

    def test_returns_per_column_provenance(self, client, monkeypatch):
        import google_sheets_service as gs
        hg = self._conf(client, "_sh1", [{"name": "企业户", "sheet_name": "企业户",
                                          "columns": {"备注二": "remark"}}])
        monkeypatch.setattr(gs, "read_sheet_values",
                            lambda *a, **k: [["账户ID", "备注二", "位置", "陌生列"]])
        monkeypatch.setattr(gs, "build_service", lambda p: object())
        res = client.get("/api/huguan/dashboard/sheet-headers", headers=hg,
                         query_string={"platform": "tt", "sheet_name": "企业户"}).get_json()
        assert res["columns"] == [
            {"header": "账户ID", "field": "advertiser_id", "via": "alias"},
            {"header": "备注二", "field": "remark", "via": "override"},
            {"header": "位置", "field": "", "via": "ignored"},
            {"header": "陌生列", "field": None, "via": "none"},
        ]
        assert res["unmatched"] == ["陌生列"]

    def test_rejects_a_sheet_outside_the_users_own_config(self, client, monkeypatch):
        """归属门禁：只能读自己配置里的表，否则等于对着任意 sheet 读表头。"""
        import google_sheets_service as gs
        hg = self._conf(client, "_sh2", [{"name": "企业户", "sheet_name": "企业户"}])
        reads = []
        monkeypatch.setattr(gs, "read_sheet_values", lambda *a, **k: reads.append(a) or [[]])
        monkeypatch.setattr(gs, "build_service", lambda p: object())
        resp = client.get("/api/huguan/dashboard/sheet-headers", headers=hg,
                          query_string={"platform": "tt", "sheet_name": "别人的表"})
        assert resp.status_code == 400
        assert "别人的表" in resp.get_json()["error"]
        assert reads == [], "不该真的去读那张表"

    def test_rejects_non_tt_and_missing_sheet_name(self, client):
        hg, _ = _create_user(client, "_sh3", role="huguan")
        r1 = client.get("/api/huguan/dashboard/sheet-headers", headers=hg,
                        query_string={"platform": "gg", "sheet_name": "企业户"})
        assert r1.status_code == 400
        r2 = client.get("/api/huguan/dashboard/sheet-headers", headers=hg,
                        query_string={"platform": "tt"})
        assert r2.status_code == 400
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd py && python -m pytest tests/test_huguan_dashboard.py -q -k TestSheetHeadersEndpoint`
Expected: FAIL —— 404（端点不存在）

- [ ] **Step 3: 实现**

在 `py/routes/huguan_dashboard_routes.py` 的 `owner-options` 端点之后追加：

```python
@huguan_dashboard_bp.route("/api/huguan/dashboard/sheet-headers", methods=["GET"])
@jwt_required()
@huguan_required
def dashboard_sheet_headers():
    """读某张 tt 表的第 1 行，摊成「逐列：表头 → 字段 + 来源」（设计 §3.1）。

    只服务列映射 UI 的显示。**归属门禁与 sync 同款**：表地址一律取自该户管自己的配置，
    请求体不接受表地址；`sheet_name` 必须是**他自己配置里的某张表**（配置保证工作表名互不重复）
    —— 否则就等于「对着任意 sheet 读表头」。
    """
    platform = str(request.args.get("platform") or "").strip()
    if platform != "tt":
        return err("只有 TT 支持表头映射", 400)
    sheet_name = str(request.args.get("sheet_name") or "").strip()
    if not sheet_name:
        return err("缺少 sheet_name", 400)

    uid = get_uid()
    db = database.get_db()
    try:
        spreadsheet_id = _spreadsheet_id(db, uid, platform)
        if not spreadsheet_id:
            return err("请先在设置页配置户管看板的表格 ID 与工作表名", 400)
        table = next((t for t in hd.get_platform_tables(db, uid, platform)
                      if t["sheet_name"] == sheet_name), None)
        if table is None:
            return err(f"工作表「{sheet_name}」不在你的看板配置里", 400)

        import google_sheets_service as gs
        from main import _GOOGLE_SHEETS_CONFIG
        service = gs.build_service(_GOOGLE_SHEETS_CONFIG["credentials_path"])
        # 与写侧同一个读法：只读第 1 行，够用且省流量。
        grid = gs.read_sheet_values(service, spreadsheet_id, sheet_name, "A1:ZZ1")
        headers = grid[0] if grid else []
        overrides = table.get("columns") or {}
        col_map, unmatched = hd.resolve_column_map(headers, overrides)
        return ok({"columns": hd.describe_header_columns(headers, overrides, col_map, unmatched),
                   "unmatched": unmatched})
    finally:
        db.close()
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd py && python -m pytest tests/test_huguan_dashboard.py -q -k TestSheetHeadersEndpoint`
Expected: PASS（3 条）

- [ ] **Step 5: 全量后端回归 + 提交**

Run: `cd py && python -m pytest tests/ -q`
Expected: 全绿（第一批的 1853 条一条不能少）

```bash
git commit -m "feat(tt): 新增读表头端点（逐列返回认列结果与来源，含归属门禁）" -- py/routes/huguan_dashboard_routes.py py/tests/test_huguan_dashboard.py
```

---

## Task 5: 前端 API + 纯逻辑模块 + `node --test`

**Files:**
- Modify: `frontend/src/api/huguan.js`
- Create: `frontend/src/utils/columnMapping.mjs`
- Create: `frontend/tests/columnMappingLogic.test.mjs`

**Interfaces:**
- Consumes: Task 4 的响应 `{columns: [{header, field, via}], unmatched: [...]}`、Task 3 的目录项
  `{key, label, key_col, direction, writable, readable}`
- Produces:
  - `getSheetHeaders(platform, sheetName)`（api）
  - `rowsFromColumns(columns) -> [{header, via, auto, selected, touched}]`（`selected`/`auto` ∈ 字段key / `""` / `null`）
  - `columnsFromRows(rows, existing) -> {表头: 字段key|""}`

- [ ] **Step 1: 写失败测试**

新建 `frontend/tests/columnMappingLogic.test.mjs`（照 `frontend/tests/columnPrefsLogic.test.mjs` 的 `node:test` 写法）：

```js
import test from 'node:test'
import assert from 'node:assert/strict'
import { rowsFromColumns, columnsFromRows } from '../src/utils/columnMapping.mjs'

// 三值约定：字段key = 采集 / "" = 刻意不采集 / null = 不写覆盖（未识别列的默认态）
test('rowsFromColumns: 四档 via 各自映射到正确的显示值与自动值', () => {
  const rows = rowsFromColumns([
    { header: '账户ID', field: 'advertiser_id', via: 'alias' },
    { header: '备注二', field: 'remark', via: 'override' },
    { header: '位置', field: '', via: 'ignored' },
    { header: '陌生列', field: null, via: 'none' },
  ])
  assert.deepEqual(rows, [
    { header: '账户ID', via: 'alias', auto: 'advertiser_id', selected: 'advertiser_id', touched: false },
    { header: '备注二', via: 'override', auto: 'remark', selected: 'remark', touched: false },
    { header: '位置', via: 'ignored', auto: '', selected: '', touched: false },
    { header: '陌生列', via: 'none', auto: null, selected: null, touched: false },
  ])
})

test('columnsFromRows: 没碰过的行一个键都不写', () => {
  const rows = rowsFromColumns([{ header: '陌生列', field: null, via: 'none' }])
  assert.deepEqual(columnsFromRows(rows, {}), {})
  // 关键回归：未识别列的默认态**不能**写成空串 —— 那等于声明「刻意不采集」，
  // 同步报告的「未采集」提示会因此消失。
})

test('columnsFromRows: 没碰过的既有覆盖原样保留（打开面板不该悄悄撤掉它）', () => {
  const rows = rowsFromColumns([{ header: '备注二', field: 'remark', via: 'override' }])
  assert.deepEqual(columnsFromRows(rows, { 备注二: 'remark' }), { 备注二: 'remark' })
})

test('columnsFromRows: 碰过并改了 ⇒ 写入', () => {
  const rows = rowsFromColumns([{ header: '陌生列', field: null, via: 'none' }])
  rows[0].touched = true
  rows[0].selected = 'remark'
  assert.deepEqual(columnsFromRows(rows, {}), { 陌生列: 'remark' })
})

test('columnsFromRows: 显式选「（不采集）」⇒ 写空串；改回自动值 ⇒ 撤掉覆盖', () => {
  const rows = rowsFromColumns([{ header: '陌生列', field: null, via: 'none' },
                                { header: '日期', field: 'acquired_date', via: 'alias' }])
  rows[0].touched = true
  rows[0].selected = ''
  rows[1].touched = true
  rows[1].selected = 'acquired_date'   // 与 auto 相同 = 改回自动
  assert.deepEqual(columnsFromRows(rows, { 日期: 'remark' }), { 陌生列: '' })
})

test('columnsFromRows: 已有但已不在表头里的键必须保留（表头以后再加）', () => {
  const rows = rowsFromColumns([{ header: '账户ID', field: 'advertiser_id', via: 'alias' }])
  assert.deepEqual(columnsFromRows(rows, { 未来列: 'remark' }), { 未来列: 'remark' })
})
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd frontend && npm test`
Expected: FAIL —— `Cannot find module '../src/utils/columnMapping.mjs'`

- [ ] **Step 3: 实现**

新建 `frontend/src/utils/columnMapping.mjs`（**扩展名必须 `.mjs`** —— 见文件结构表里的理由，既有 `columnPrefsLogic.mjs` 同理）：

```js
// 「读表头」响应 ↔ 列映射下拉行状态 的纯换算（无 Vue 依赖，供 node --test 覆盖）。
//
// 三值约定（与后端设计 §3.3 一一对应）：
//   字段key → 采集到该字段（写进 columns）
//   ""      → 刻意不采集（写进 columns，值空串；解析时既不映射也不上报）
//   null    → **不写覆盖**：未识别列的默认态。必须与 "" 分开 —— 若把未识别列的默认态
//             写成空串，等于替用户声明了「刻意不采集」，同步报告的「未采集」提示会消失。
export function rowsFromColumns(columns) {
  return (columns || []).map((c) => {
    const auto = c.via === 'none' ? null : (c.field ?? '')
    return { header: c.header, via: c.via, auto, selected: auto, touched: false }
  })
}

// 组装要保存的 columns：只认「用户碰过」的行（touched），没碰过的一个键都不动 ——
// 包括既有覆盖（打开面板看一眼不该把它撤掉），以及表头里还没有的键。
export function columnsFromRows(rows, existing) {
  const out = { ...(existing || {}) }
  for (const r of rows || []) {
    if (!r.touched) continue
    if (r.selected === r.auto) delete out[r.header]   // 改回自动 ⇒ 撤掉覆盖
    else if (r.selected !== null) out[r.header] = r.selected
  }
  return out
}
```

`frontend/src/api/huguan.js` 里加（放在 `saveConfig` 之后）：

```js
  /** 读某张 tt 表的第 1 行，摊成逐列「表头 → 字段 + 来源」，供列映射区显示。
   * 只有 TT 支持（gg/fb 调会 400）；sheet_name 必须是该户管自己配置里的某张表。 */
  getSheetHeaders: (platform, sheetName) =>
    api.get('/huguan/dashboard/sheet-headers', { params: { platform, sheet_name: sheetName } }),
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd frontend && npm test`
Expected: PASS（新 6 条 + 既有 `columnPrefsLogic` 全绿）

- [ ] **Step 5: 提交**

```bash
git commit -m "feat(tt-ui): 列映射纯逻辑（三值约定 + 只认碰过的行）+ 读表头 API" -- frontend/src/utils/columnMapping.mjs frontend/tests/columnMappingLogic.test.mjs frontend/src/api/huguan.js
```

---

## Task 6: 视觉设计（`/frontend-design`）

**Files:**
- 产出：本任务末尾追加到本计划文件的「视觉规格」小节（颜色/间距/状态/文案）

**Interfaces:**
- Produces: Task 7 实现 UI 时要照做的视觉规格（本任务必须先于 Task 7 完成）

- [ ] **Step 1: 调技能**

对「户管看板卡片里每张 TT 表的『列映射』折叠区 + 差异弹窗的『未采集列』提示区」调用
`/frontend-design`。它要覆盖的状态：未读表头（空态）、读取中、读失败（错误态）、
一列已识别（普通）、一列未识别（要醒目）、一列刻意不采集（灰）、一列被手工覆盖（要能看出「改过」）、
有未保存改动（提示）。

- [ ] **Step 2: 把结论记进本计划**

在本文件末尾追加「## 视觉规格（Task 6 产出）」小节，逐条写下最终的颜色/间距/组件选择/文案，
使 Task 7 的实现者不必再问。**不要**只写「按设计稿」——那会让 Task 7 无法独立执行。

- [ ] **Step 3: 提交**

```bash
git commit -m "docs(tt-ui): 列映射区与未采集提示的视觉规格" -- docs/superpowers/plans/2026-10-10-tt-header-mapping-frontend.md
```

---

## Task 7: `HuguanDashboardCard.vue` 接线（列映射区 + 未采集提示与跳转）

**Files:**
- Modify: `frontend/src/components/HuguanDashboardCard.vue`（1237 行；tt 多表配置区 ~`:56-70`，差异弹窗 ~`:200+`）

**Interfaces:**
- Consumes: Task 5 的 `getSheetHeaders` / `rowsFromColumns` / `columnsFromRows`；Task 3 的 `tt_field_catalog`
  （`getConfig` 的 `config.tt.tt_field_catalog`）；Task 6 的视觉规格
- Produces: 卡片内的列映射交互；差异弹窗的「未采集列」区

- [ ] **Step 1: 接目录与状态（script 部分）**

在 `getConfig` 的回填逻辑里，把 `conf.tt_field_catalog` 存进一个 ref（例如 `hdFieldCatalog`）。
新增状态（按 `sheet_name` 作键，因为配置保证工作表名互不重复）：

```js
// 每张表的「读表头」结果：{ [sheet_name]: [{header, via, auto, selected, touched}] }
const hdHeaderRows = ref({})
const hdHeaderLoading = ref({})   // { [sheet_name]: true }
const hdHeaderError = ref({})     // { [sheet_name]: '文案' }
const hdHeaderOpen = ref({})      // 折叠区展开态
```

- [ ] **Step 2: 读取表头**

```js
async function hdReadHeaders(i) {
  const t = hdForm.value.tables[i]
  const name = (t.sheet_name || '').trim()
  if (!name) return                      // 按钮已禁用，这里是兜底
  hdHeaderLoading.value = { ...hdHeaderLoading.value, [name]: true }
  hdHeaderError.value = { ...hdHeaderError.value, [name]: '' }
  try {
    const res = await huguanApi.getSheetHeaders('tt', name)
    hdHeaderRows.value = { ...hdHeaderRows.value, [name]: rowsFromColumns(res.columns || []) }
    hdHeaderOpen.value = { ...hdHeaderOpen.value, [name]: true }
  } catch (e) {
    // 就地显示，不弹全局错误：读表头失败不该打断用户已有的列映射保存
    hdHeaderError.value = { ...hdHeaderError.value,
      [name]: (e && e.response && e.response.data && e.response.data.error) || '读取表头失败' }
  } finally {
    hdHeaderLoading.value = { ...hdHeaderLoading.value, [name]: false }
  }
}
```

- [ ] **Step 3: 下拉改动 → 写回该表的 `columns`**

```js
function hdOnColumnPick(i, row, value) {
  row.selected = value
  row.touched = true
  const t = hdForm.value.tables[i]
  t.columns = columnsFromRows(hdHeaderRows.value[t.sheet_name] || [], t.columns)
}
```

- [ ] **Step 4: 渲染折叠区（照 Task 6 的视觉规格）**

在 tt 的多表 `el-form-item` 里、每个表项（`v-for="(t, i) in hdForm.tables"`）之下加一个
`el-collapse`/`el-collapse-item`（具体按视觉规格），标题为「列映射」+ 一个「有未保存的列映射」标记
（判据：`t.columns` 与打开面板时快照的差异；标记只在有差异时显示）。
区内：
- 未读表头 ⇒ 空态 + 「读取表头」按钮（`sheet_name` 为空时禁用并提示先填工作表名）
- 读取中 ⇒ loading；失败 ⇒ 就地 `el-alert` 显示 `hdHeaderError[sheet_name]`
- 逐列一行：`[表头原文]` + `el-select`（选项 = `hdFieldCatalog` 按 `label` 显示，定位键标「定位键」、
  `direction === 'r'` 标「只读回」；外加一个「（不采集）」= `""`）；未识别行（`via === 'none'`）加醒目标记
  且默认停在占位（`null`）
- 每行 `@change` 调 `hdOnColumnPick`
- 未采集列入口：差异弹窗里新增「未采集列」区，逐条 `表名 + 表头 + 「去指派」`；
  点击 ⇒ 关弹窗、展开该表的列映射区、自动 `hdReadHeaders(i)`、`scrollIntoView`

- [ ] **Step 5: 自查 + 构建**

Run: `cd frontend && npm test && npx vite build`
Expected: 测试绿；构建通过（无语法/导入错误）

- [ ] **Step 6: 提交**

```bash
git commit -m "feat(tt-ui): 卡片内列映射区（读表头/逐列指派/不采集）+ 未采集列提示与跳转" -- frontend/src/components/HuguanDashboardCard.vue
```

---

## Task 8: 收尾（全量回归 + 验收清单）

**Files:**
- Modify: `docs/superpowers/plans/2026-10-10-tt-header-mapping-frontend.md`（追加验收清单）

- [ ] **Step 1: 两套测试全量**

Run: `cd py && python -m pytest tests/ -q` → 全绿
Run: `cd frontend && npm test` → 全绿

- [ ] **Step 2: 写验收清单进本计划**

逐条写清「怎么点、看什么」，交给用户在自己的服务上执行（本计划**不启动任何进程**）：

1. **列映射区可见**：TT 设置 → 户管看板卡片 → 某张表下出现「列映射」；GG/FB 卡片**没有**这个区。
2. **读表头**：点「读取表头」⇒ 逐列列出表头，已识别的显示对应字段中文名（虚显），未识别的标出来。
3. **指派未识别列**：把某个未识别列指到某字段 → 保存 → 再点「读取表头」⇒ 该列显示为已指派（来源＝手工）。
4. **不采集**：把某列选成「（不采集）」→ 保存 → 同步一次 ⇒ 该列**不再**出现在报告的「未采集」里。
5. **未采集提示与跳转**：表里加一列没见过的表头 → 同步（dry_run）⇒ 报告里出现「未采集列」并带表名/表头；
   点「去指派」⇒ 关弹窗、打开该表列映射区并自动读出表头。
6. **归属门禁**：列映射区只能读自己配置里的表（换一张不在配置里的表名不会有入口——由第 4 步的 400 保证）。
7. **第一批回归**：企业户表零配置同步结果正确；加白户表与改动前一致；GG/FB 行为不变。

- [ ] **Step 3: 提交**

```bash
git commit -m "docs(tt-ui): 第二批验收清单" -- docs/superpowers/plans/2026-10-10-tt-header-mapping-frontend.md
```

---

## 视觉规格（Task 6 产出）

### 定位（决定了后面所有取舍）

这**不是新页面**，是既有户管看板卡片（`HuguanDashboardCard.vue`）里的一个区块 ⇒ 视觉方向由既有设计系统
（Element Plus + 卡片既有的 `#e6a23c` 警告橙 / `#6b7280` 次要灰 / `#7c3aed` 归属紫 / `el-tag` 灰底标签）
决定。在这里另起一套视觉语言是错的。**可支配的「大胆」只有一处：让「未采集」的行无法被忽略** ——
这个面板存在的全部意义，就是把原先**静默**的信号（串列、未采集）变成看得见的东西。

### 色（复用既有语义色，不新增色板）

| 用途 | 值 |
|---|---|
| 未保存提示（圆点/文字） | `#e6a23c` |
| 未采集行：左竖条 | `#f56c6c`（3px） |
| 未采集标签 | 字 `#f56c6c` / 底 `#fef0f0` |
| 已识别（别名）标签 | 字 `#909399` / 底 `#f4f4f5` |
| 手工覆盖标签 | 字 `#409eff` / 底 `#ecf5ff`；行尾「已改」用 `#409eff` 12px |
| 刻意不采集 | 整行文字降饱和到 `#c0c4cc` |
| 表头原文 | `#303133`，字重 500 |
| 面板内说明文字 | `#6b7280`，12px |

### 字

沿用卡片既有字族与字号：表头原文 13px/500；下拉与标签 12–13px；折叠区标题 14px/600。
**不引入新字族** —— 管理后台里一致性优先于个性，这是刻意的选择。

### 版式

- **折叠区标题行**：左「列映射」；右侧统计 `N 列已识别 · N 列未采集 · N 列不采集`；
  有未保存改动时加一个 `#e6a23c` 圆点 + 「未保存」；最右「读取表头」按钮（`size="small"`）。
- **列行**：两列 grid —— 表头原文（固定 `12em`，超出省略号 + `title` tooltip）+ 指派下拉（`14em`）。
  行高 32px、行间 4px、**无边框**（用留白分组）；未采集行额外 `border-left:3px solid #f56c6c; padding-left:8px`。
- **面板底部**一行 ⓘ 说明（12px `#6b7280`）。左对齐；不给这些行加编号（它们不是序列）。

### 状态与文案

| 状态 | 表现 | 文案 |
|---|---|---|
| 未读表头（空态） | **只留一行说明**（按钮只有一个，固定在标题行右侧——见版式；空态不再放第二个按钮） | 点「读取表头」看看这张表每一列会被认成什么。 |
| 读取中 | 按钮 loading + 两行骨架 | — |
| 读失败 | 就地 `el-alert type="error"`（**不弹全局错误**） | 用后端 `error` 文案；无则「读取表头失败，稍后重试。」 |
| 已识别（别名） | 灰标签「别名」；下拉显示字段中文名 | — |
| 手工覆盖 | 蓝标签「手工」+ 行尾「已改」 | — |
| 刻意不采集 | 下拉选中「（不采集）」，整行降饱和 | 选项文案：（不采集） |
| 未采集 | 红左条 + 红标签「未采集」；下拉未选 | 下拉空值占位：选择字段… |
| 定位键那一行 | 下拉里「账户ID」标「定位键」 | tooltip：这张表必须有「账户ID」列，否则整次同步会被拒绝 |
| **同表头重复** | 该行**只读**（下拉 `disabled`），红标签「未采集」 | 就地提示：表头重复，先在表里改名 |
| 有未保存改动 | 标题行橙点 + 「未保存」 | — |

### 未采集列提示（同步差异弹窗内）

照既有 ①~④ 分区的款式新增一区：标题「未采集列」；每条 `表名 + 表头`（`el-tag`）+ 右侧「去指派」按钮
（`size="small"`）。区顶一行说明：**这些列不会被同步。点「去指派」告诉系统它是什么字段。**
点击 ⇒ 关弹窗、展开该表列映射区、自动点一次「读取表头」、`scrollIntoView`。

### 两条决定（用户 2026-10-10 未逐条回答，编排者按推荐采纳，可推翻）

1. **`via="none"` 统一显示「未采集」** —— 对「真不认识」与「识别到了但落选」都准确，且与同步报告口径一致；
   **不新增第五档**（前端也不假装能区分）。
2. **同表头重复的行只读 + 提示改名** —— 因为 `columns` 按**表头名**存键，指派第二个同名表头会**静默作用于最左列**。

### 两个不做

- **不做动效**（展开/收起用 Element 默认即可）。
- **不加编号 01/02**（这些行不是序列；编号留给弹窗里真有顺序的分区）。
