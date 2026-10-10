# 数据分析按平台隔离（FB 接自有数据 / TT 明确无数据）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让「数据分析」页显示**当前平台自己的**数据 —— FB 接上 `fb_ad_reports` 的花费看板；TT 明确显示「暂无分析数据」且**不发起任何请求**；GG 原样不动。

**Architecture:** 根因是 `/analysis` 是**中性路由**（`meta` 里没有 `platform`），而请求层 `platformFromPath` 对中性页一律回落 `'gg'`，页面读的又是 GG 专用的 `/api/ad-reports/*`。修法是**让分析页成为各平台自己的页面**：路由按平台前缀拆开（`/analysis` 归档 GG、新增 `/tt/analysis`、`/fb/analysis`），请求层无需改动即自动带对平台；后端为 FB 补两个聚合端点。

**Tech Stack:** Flask + SQLite（后端）、Vue 3 `<script setup>` + Element Plus + ECharts（前端）、pytest。

**设计文档:** `docs/superpowers/specs/2026-10-11-analysis-platform-isolation-design.md`（已定案）

## Global Constraints

- **GG 的分析功能一行都不能改**：`/analysis` 路由、`AnalysisView.vue` 现有的 6 个 tab、`/api/ad-reports/*` 全部保持现状。改动一律是**按平台分支**，GG 分支走原路径。
- **不改 `platformFromPath`**（`frontend/src/utils/platformPrefs.mjs`）：它「其余一律 gg」的默认对**请求层**是对的，不能动。
- **不改 store 侧的平台逻辑**（`platformFamily` 等，2026-10-11 刚修过）。
- **TT 的空状态必须是「不发请求」**，不是「请求后为空」—— 判定标准是 DevTools Network 里**不出现任何 `/api/ad-reports/*`**。
- **FB 端点只读 `fb_ad_reports`**，绝不碰 `ad_reports`（GG 的表，无 `platform` 列）。
- **FB 看板的展示/点击照实返回**（当前几乎全 0），界面上标注「数据不全」，**不要隐藏真实状态**。
- **新 UI 必须先调 `/frontend-design`**（项目规范：新增 UI 前置）。
- **提交规范**：多会话共享工作区，**禁用 `git add -A`**；新文件用 `git add <文件>` + `git commit -- <同一文件>`（pathspec 提交对**未跟踪**的新文件会报 `did not match`，必须先 add）。**不推 origin。**

---

## 文件结构

| 文件 | 职责 | 本计划改动 |
|---|---|---|
| `py/routes/fb_routes.py` | FB 全部 HTTP 端点 | 新增 2 个分析端点 |
| `py/tests/test_fb_analysis.py` | 上述端点的测试 | **新建** |
| `frontend/src/router/index.js` | 路由表 | 新增 `/tt/analysis`、`/fb/analysis` |
| `frontend/src/components/AppSidebar.vue` | 三套平台导航 | FB/TT 的 analysis 项改指向各自路径 |
| `frontend/src/api/fb.js` | FB API 模块 | 加 2 个方法 |
| `frontend/src/views/AnalysisView.vue` | 分析页（1054 行） | 按 `route.meta.platform` 分支渲染 |

**任务依赖**：Task 1（后端）与 Task 2（路由/侧边栏）互不依赖，可并行；Task 3 依赖 1 与 2；Task 4 最后。

---

## Task 1: 后端 FB 分析端点（dashboard + trends）

**Files:**
- Modify: `py/routes/fb_routes.py`（新增两个端点，追加在 `reports_stats` 之后约 :2349）
- Test: `py/tests/test_fb_analysis.py`（新建）

**Interfaces:**
- Consumes: `fb_bp`、既有的 `get_db()` / `get_uid()` / `ok()` / `err()`（`routes/helpers.py`）、`@fb_required`（`routes/decorators.py`）
- Produces:
  - `GET /api/fb/analysis/dashboard` → `ok({summary, by_line, by_product})`
  - `GET /api/fb/analysis/trends` → `ok({points})`

**参数口径**（**逐字照 `ad_reports_dashboard`（`py/main.py:10276-10299`）**，这样前端 `filterParams()` 一份就够喂两个平台）：

- `product_name`：**逗号分隔多值**。单个 → `product_name=?`；多个 → `product_name IN (?,?,…)`（占位符逐个加，**不要**字符串拼接）
- `line_name`：单个精确匹配（可选）
- `from_date` / `to_date`：`report_date >= / <=`（可选）
- **不设 `region`**（FB 无该字段）

- [ ] **Step 1: 写失败测试**

创建 `py/tests/test_fb_analysis.py`：

```python
"""FB 分析端点 —— 聚合口径与平台数据隔离。

设计见 docs/superpowers/specs/2026-10-11-analysis-platform-isolation-design.md。
运行：cd py && python -m pytest tests/test_fb_analysis.py -v
"""
import pytest

import database

DASH = "/api/fb/analysis/dashboard"
TREND = "/api/fb/analysis/trends"


def _login(client, username):
    client.post("/api/auth/register", json={"username": username, "password": "test123"})
    db = database.get_db()
    db.execute("UPDATE users SET platform='fb', role='user' WHERE username=?", (username,))
    db.commit()
    db.close()
    resp = client.post("/api/auth/login", json={"username": username, "password": "test123"})
    assert resp.status_code == 200, resp.get_json()
    tok = resp.get_json().get("access_token", "")
    assert tok, "登录未返回 token"
    return {"Authorization": f"Bearer {tok}"}, resp.get_json()["user"]["id"]


@pytest.fixture
def fb_user(client):
    return _login(client, "fbanalysis")


def _seed(uid, rows):
    """rows: (product, line, date, account_id, cost, impressions, clicks)"""
    db = database.get_db()
    for p, l, d, aid, cost, imp, clk in rows:
        db.execute(
            "INSERT INTO fb_ad_reports (user_id, product_name, line_name, report_date, "
            "account_name, account_id, cost, impressions, clicks) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            (uid, p, l, d, f"acc-{aid}", aid, cost, imp, clk))
    db.commit()
    db.close()


def test_dashboard_aggregates_by_line(client, fb_user):
    headers, uid = fb_user
    _seed(uid, [
        ("P1", "L1", "2026-10-01", "a1", 10.0, 100, 5),
        ("P1", "L1", "2026-10-02", "a2", 20.0, 200, 6),
        ("P1", "L2", "2026-10-01", "a3", 5.0, 50, 1),
    ])
    body = client.get(DASH, headers=headers).get_json()
    assert body["summary"]["total_cost"] == 35.0
    assert body["summary"]["total_impressions"] == 350
    assert body["summary"]["total_clicks"] == 12
    assert body["summary"]["record_count"] == 3
    assert body["summary"]["account_count"] == 3
    lines = {r["line_name"]: r for r in body["by_line"]}
    assert lines["L1"]["total_cost"] == 30.0
    assert lines["L2"]["total_cost"] == 5.0


def test_dashboard_filters_by_multi_product(client, fb_user):
    """product_name 逗号分隔多值 → IN 查询（照 ad_reports_dashboard 的口径）。"""
    headers, uid = fb_user
    _seed(uid, [
        ("P1", "L1", "2026-10-01", "a1", 10.0, 0, 0),
        ("P2", "L1", "2026-10-01", "a2", 20.0, 0, 0),
        ("P3", "L1", "2026-10-01", "a3", 40.0, 0, 0),
    ])
    body = client.get(DASH, headers=headers, query_string={"product_name": "P1,P2"}).get_json()
    assert body["summary"]["total_cost"] == 30.0
    assert body["summary"]["record_count"] == 2


def test_dashboard_filters_by_date_range(client, fb_user):
    headers, uid = fb_user
    _seed(uid, [
        ("P1", "L1", "2026-10-01", "a1", 10.0, 0, 0),
        ("P1", "L1", "2026-10-10", "a2", 20.0, 0, 0),
        ("P1", "L1", "2026-10-20", "a3", 40.0, 0, 0),
    ])
    body = client.get(DASH, headers=headers,
                      query_string={"from_date": "2026-10-05", "to_date": "2026-10-15"}).get_json()
    assert body["summary"]["total_cost"] == 20.0


def test_dashboard_empty_is_zero_not_error(client, fb_user):
    headers, _ = fb_user
    body = client.get(DASH, headers=headers).get_json()
    assert body["success"] is True
    assert body["summary"]["total_cost"] == 0
    assert body["summary"]["record_count"] == 0
    assert body["by_line"] == []


def test_trends_groups_by_date_ascending(client, fb_user):
    headers, uid = fb_user
    _seed(uid, [
        ("P1", "L1", "2026-10-02", "a1", 20.0, 200, 2),
        ("P1", "L1", "2026-10-01", "a2", 10.0, 100, 1),
        ("P1", "L1", "2026-10-01", "a3", 5.0, 50, 1),
    ])
    body = client.get(TREND, headers=headers).get_json()
    pts = body["points"]
    assert [p["report_date"] for p in pts] == ["2026-10-01", "2026-10-02"], "必须按日期升序"
    assert pts[0]["total_cost"] == 15.0
    assert pts[1]["total_cost"] == 20.0


def test_endpoints_require_auth(client):
    assert client.get(DASH).status_code == 401
    assert client.get(TREND).status_code == 401


def test_only_reads_fb_table_not_gg(client, fb_user):
    """**数据隔离的核心判据**：往 GG 的 ad_reports 塞同名产品/线，
    FB 分析端点绝不能把它们算进来。"""
    headers, uid = fb_user
    _seed(uid, [("P1", "L1", "2026-10-01", "a1", 10.0, 0, 0)])   # fb_ad_reports
    db = database.get_db()
    db.execute(
        "INSERT INTO ad_reports (user_id, product_name, region, report_date, customer_id, "
        "campaign, cost) VALUES (?,?,?,?,?,?,?)",
        (uid, "P1", "R", "2026-10-01", "c1", "L1", 9999.0))      # ad_reports（GG）
    db.commit()
    db.close()
    body = client.get(DASH, headers=headers).get_json()
    assert body["summary"]["total_cost"] == 10.0, "不能把 GG 的 9999 算进来"
```

- [ ] **Step 2: 跑测试确认失败**

```bash
cd py && python -m pytest tests/test_fb_analysis.py -q
```

预期：全部 FAIL（404 —— 端点还不存在）

- [ ] **Step 3: 实现两个端点**

在 `py/routes/fb_routes.py` 的 `reports_stats` 之后追加。**聚合口径与筛选完全照 `py/main.py:10276-10299` 的 `ad_reports_dashboard`**（那是 GG 的，本任务是把同一套口径落到 `fb_ad_reports` 上）：

```python
# ---------- 分析端点（按平台隔离：只读 fb_ad_reports） ----------
# 参数口径逐字照 GG 的 ad_reports_dashboard（py/main.py:10276），
# 这样前端 AnalysisView 的 filterParams() 一份就够喂两个平台。
# 与 /api/fb/reports/stats 的区别：那个是「数据管理」的原始分组列表，
# 这两个是给分析页的汇总/趋势，字段名按分析页的语义取。

def _fb_analysis_where(args, uid):
    """构造 WHERE 与参数。product_name 支持逗号分隔多值（照 GG 口径）。"""
    where = ["user_id = ?"]
    params = [uid]

    product_name = (args.get("product_name") or "").strip()
    if product_name:
        names = [n.strip() for n in product_name.split(",") if n.strip()]
        if len(names) == 1:
            where.append("product_name = ?")
            params.append(names[0])
        else:
            where.append(f"product_name IN ({','.join(['?'] * len(names))})")
            params.extend(names)

    line_name = (args.get("line_name") or "").strip()
    if line_name:
        where.append("line_name = ?")
        params.append(line_name)

    from_date = (args.get("from_date") or "").strip()
    if from_date:
        where.append("report_date >= ?")
        params.append(from_date)

    to_date = (args.get("to_date") or "").strip()
    if to_date:
        where.append("report_date <= ?")
        params.append(to_date)

    return " AND ".join(where), params


@fb_bp.route('/api/fb/analysis/dashboard', methods=['GET'])
@jwt_required()
@fb_required
def fb_analysis_dashboard():
    """FB 分析页的仪表盘：总览 + 按线/按产品分组。

    **只读 fb_ad_reports**（GG 的 ad_reports 无 platform 列，绝不能混进来）。
    """
    db = get_db()
    uid = get_uid()
    where_clause, params = _fb_analysis_where(request.args, uid)

    summary = db.execute(
        f"SELECT COALESCE(SUM(cost),0) AS total_cost, "
        f"COALESCE(SUM(impressions),0) AS total_impressions, "
        f"COALESCE(SUM(clicks),0) AS total_clicks, "
        f"COALESCE(SUM(registrations),0) AS total_registrations, "
        f"COALESCE(SUM(purchases),0) AS total_purchases, "
        f"COUNT(*) AS record_count, "
        f"COUNT(DISTINCT account_id) AS account_count "
        f"FROM fb_ad_reports WHERE {where_clause}", params
    ).fetchone()

    def _group(col):
        rows = db.execute(
            f"SELECT {col} AS name, COALESCE(SUM(cost),0) AS total_cost, "
            f"COALESCE(SUM(impressions),0) AS total_impressions, "
            f"COALESCE(SUM(clicks),0) AS total_clicks, COUNT(*) AS record_count "
            f"FROM fb_ad_reports WHERE {where_clause} "
            f"GROUP BY {col} ORDER BY total_cost DESC", params
        ).fetchall()
        return [dict(r) for r in rows]

    return ok({
        "summary": dict(summary),
        "by_line": _group("line_name"),
        "by_product": _group("product_name"),
    })


@fb_bp.route('/api/fb/analysis/trends', methods=['GET'])
@jwt_required()
@fb_required
def fb_analysis_trends():
    """FB 分析页的趋势：按日期升序的每日汇总。"""
    db = get_db()
    uid = get_uid()
    where_clause, params = _fb_analysis_where(request.args, uid)

    rows = db.execute(
        f"SELECT report_date, COALESCE(SUM(cost),0) AS total_cost, "
        f"COALESCE(SUM(impressions),0) AS total_impressions, "
        f"COALESCE(SUM(clicks),0) AS total_clicks, COUNT(*) AS record_count "
        f"FROM fb_ad_reports WHERE {where_clause} "
        f"GROUP BY report_date ORDER BY report_date ASC", params
    ).fetchall()
    return ok({"points": [dict(r) for r in rows]})
```

> `request` 已在该文件顶部导入；`get_db` / `get_uid` / `ok` 若未导入，按该文件现有的导入行补齐（照 `reports_stats` 的写法）。

- [ ] **Step 4: 跑测试确认通过**

```bash
cd py && python -m pytest tests/test_fb_analysis.py -v
```

预期：全部 PASS

- [ ] **Step 5: 跑全量确认没碰坏别的**

```bash
cd py && python -m pytest tests/ -q
```

预期：无新增失败（全量约 1900+ 用例、约 10 分钟，耐心等）

- [ ] **Step 6: 提交**

```bash
cd "D:/server/cc/GG-Server" && git add py/routes/fb_routes.py py/tests/test_fb_analysis.py && git commit -m "feat(fb-analysis): 新增 FB 分析端点（仪表盘 + 趋势）

只读 fb_ad_reports；参数口径逐字照 GG 的 ad_reports_dashboard
（product_name 逗号分隔多值 → IN，from_date/to_date），
让前端一份 filterParams 同时喂两个平台。

含数据隔离判据：往 GG 的 ad_reports 塞同名产品/线，FB 端点不得算进来。" -- py/routes/fb_routes.py py/tests/test_fb_analysis.py
```

---

## Task 2: 路由与侧边栏按平台拆分

**Files:**
- Modify: `frontend/src/router/index.js:70-73`（`/analysis` 那条之后新增两条）
- Modify: `frontend/src/components/AppSidebar.vue:95`（fbNavItems）、`:111`（ttNavItems）

**Interfaces:**
- Consumes: 无
- Produces: 路由 `/tt/analysis`（`meta.platform='tt'`）、`/fb/analysis`（`meta.platform='fb'`）

**为什么这样改**：请求层 `platformFromPath` 按**路径前缀**推平台（`/tt…`→tt、`/fb…`→fb、其余→gg）。把分析页做成平台前缀路由后，**请求层一个字都不用改**，FB/TT 的请求就自动带对平台。

- [ ] **Step 1: 加两条路由**

`frontend/src/router/index.js` 里 `/analysis` 那条**保持不动**，紧跟其后插入：

```js
  {
    path: '/tt/analysis',
    component: () => import('../views/AnalysisView.vue'),
    meta: { title: '数据分析', platform: 'tt' }
  },
  {
    path: '/fb/analysis',
    component: () => import('../views/AnalysisView.vue'),
    meta: { title: '数据分析', platform: 'fb' }
  },
```

- [ ] **Step 2: 侧边栏各自指向自己的路径**

`frontend/src/components/AppSidebar.vue`：**只改 `path`，其余一字不动**。

- `:95`（`fbNavItems` 里的 analysis 行）→ `path:'/fb/analysis'`
- `:111`（`ttNavItems` 里的 analysis 行）→ `path:'/tt/analysis'`
- `:76`（`ggNavItems`）→ **保持 `/analysis` 不动**

> 三行的其余部分逐字相同（`{ key: 'analysis', icon: '📈', label: '数据分析', sections: [{ title: '分析', items: [{ icon:'📊',label:'数据看板',path:'…'}]}]},`），所以改的时候用「整行替换」而不是全局替换，避免误改 GG 那行。

- [ ] **Step 3: 核对路由守卫对四种角色放行**

`frontend/src/router/index.js:166-246` 的守卫按 `meta.admin` / viewer / huguan 逐路径拦截。**新增的两条路由必须逐一核对**这四种角色（admin / viewer / huguan / 普通 user）访问 `/tt/analysis`、`/fb/analysis` 时的行为，与它们访问旧的 `/analysis` **一致**（不该因为换了个路径就被拦或放行）。

```bash
cd frontend && npm run build
```

若守卫里有按路径前缀硬编码的规则，需按既有写法把新路径补进去。**把核对结论写进报告。**

- [ ] **Step 4: 起前端确认路由可达**

```bash
cd frontend && npm run build && npm run dev
```

手动访问 `/#/fb/analysis` 与 `/#/tt/analysis`，确认页面能渲染（此时还是 GG 的界面，Task 3 才分支）且**不报 404 / 不被守卫弹走**。

> **本任务不需要后端。** 若要连真实后端验证，先问协调者（用户自己的 5001 在跑真实库，不得擅自重启）。

- [ ] **Step 5: 提交**

```bash
cd "D:/server/cc/GG-Server" && git add frontend/src/router/index.js frontend/src/components/AppSidebar.vue && git commit -m "feat(analysis): 分析页按平台拆路由

/analysis 归档 GG（与 GG 其它页面无前缀一致），新增 /tt/analysis 与
/fb/analysis（meta.platform 分别为 tt/fb），侧边栏 FB/TT 各自指向自己的路径。
请求层 platformFromPath 按路径前缀推平台，故这样一改，FB/TT 的请求
自动带对平台，platformFromPath 一个字都不用动。" -- frontend/src/router/index.js frontend/src/components/AppSidebar.vue
```

---

## Task 3: AnalysisView 按平台分支（TT 空状态 + FB 花费看板）

**Files:**
- Modify: `frontend/src/api/fb.js`（加 2 个方法）
- Modify: `frontend/src/views/AnalysisView.vue`（1054 行）
- 设计文档附录：`docs/superpowers/specs/2026-10-11-analysis-platform-isolation-design.md`（记 `/frontend-design` 的产出）

**Interfaces:**
- Consumes: Task 1 的两个端点、Task 2 的 `route.meta.platform`
- Produces: 无（终端 UI）

- [ ] **Step 1: 先调 `/frontend-design`（项目规范硬性要求）**

本任务**含新增 UI**（TT 的空状态、FB 的花费看板）。按项目规范，**动 UI 之前必须先调 `frontend-design` 技能**。

给设计的输入：
1. 复用分析页**现有的视觉语法**（`.stat-card` / `.stat-val` / `.stat-label`，见 `AnalysisView.vue:27-45`），不另起一套
2. TT 空状态：整页居中的空状态，文案「TT 暂无分析数据」+ 一行原因说明（TT 数据提取目前不落库，故无数据可分析）
3. FB 看板：一行指标卡（总花费 / 记录数 / 账户数 / 展示 / 点击），其中**展示与点击要标注「数据不全」**（当前几乎全 0）—— 设计上要让「这个数可能是缺的」一眼可见，而不是让人误以为真的是 0
4. 一张按线的花费表 + 一条花费趋势折线
5. 沿用 ECharts（项目已装 `echarts` + `vue-echarts`）

把产出记进设计文档的附录节（新增 `## 附录：分析页视觉决策`），再动手。

- [ ] **Step 2: 加 API 方法**

`frontend/src/api/fb.js` 的 `fbApi` 对象里，紧挨现有的 reports 方法追加：

```js
  // 分析（按平台隔离：只读 fb_ad_reports，见 2026-10-11 设计）
  analysisDashboard(params = {}) { return client.get('/fb/analysis/dashboard', { params }) },
  analysisTrends(params = {}) { return client.get('/fb/analysis/trends', { params }) },
```

- [ ] **Step 3: AnalysisView 按平台分支**

在 `<script setup>` 里取平台（`useRoute` 已在该文件导入）：

```js
// 分析页按平台隔离（2026-10-11）：路由前缀即平台。
// /analysis 缺省 gg（与 GG 其它页面无前缀的现状一致）。
const analysisPlatform = computed(() => route.meta?.platform || 'gg')
```

模板（`AnalysisView.vue:22` 那组 `<el-tabs>` 的外层）包一层分支，**GG 分支原样保留**：

```vue
<!-- TT：无数据源，整页空状态。**刻意不发任何请求** —— 判定标准是
     DevTools Network 里不出现 /api/ad-reports/*。 -->
<div v-if="analysisPlatform === 'tt'" style="padding:64px 0;text-align:center;">
  <p style="font-size:16px;color:#303133;margin:0 0 8px;">TT 暂无分析数据</p>
  <p style="font-size:13px;color:#909399;margin:0;">
    TT 的数据提取目前不会把结果保存到系统（只支持复制 / 导出），因此没有可供分析的数据。
  </p>
</div>

<!-- FB：自有数据（fb_ad_reports）的花费看板 -->
<template v-else-if="analysisPlatform === 'fb'">
  <!-- 指标卡：容器与卡片类名逐字沿用仪表盘 tab（AnalysisView.vue:26-27） -->
  <div style="display:flex;gap:12px;flex-wrap:wrap;margin-bottom:16px;">
    <div class="stat-card"><div class="stat-val">${{ fbSummary.total_cost.toLocaleString() }}</div><div class="stat-label">总花费</div></div>
    <div class="stat-card"><div class="stat-val">{{ fbSummary.record_count.toLocaleString() }}</div><div class="stat-label">记录数</div></div>
    <div class="stat-card"><div class="stat-val">{{ fbSummary.account_count.toLocaleString() }}</div><div class="stat-label">账户数</div></div>
    <!-- 展示/点击：FB 侧目前几乎全为 0（见设计 §2.4），**照实显示但明确标注**，
         不隐藏真实状态、也不让人误以为真的是 0 -->
    <div class="stat-card"><div class="stat-val">{{ fbSummary.total_impressions.toLocaleString() }}</div><div class="stat-label">总展示 <span style="color:#E6A23C;font-size:11px;">数据不全</span></div></div>
    <div class="stat-card"><div class="stat-val">{{ fbSummary.total_clicks.toLocaleString() }}</div><div class="stat-label">总点击 <span style="color:#E6A23C;font-size:11px;">数据不全</span></div></div>
  </div>

  <!-- 按线花费表 -->
  <el-table :data="fbByLine" stripe border size="small">
    <el-table-column prop="name" label="线名" min-width="180" show-overflow-tooltip />
    <el-table-column prop="total_cost" label="花费" min-width="110" sortable>
      <template #default="{ row }">${{ row.total_cost.toLocaleString() }}</template>
    </el-table-column>
    <el-table-column prop="total_impressions" label="展示" min-width="100" sortable />
    <el-table-column prop="total_clicks" label="点击" min-width="90" sortable />
    <el-table-column prop="record_count" label="记录数" min-width="90" sortable />
  </el-table>

  <!-- 花费趋势（命令式 echarts，写法照趋势 tab：init + setOption） -->
  <div v-if="fbTrendPoints.length" ref="fbTrendChart" style="width:100%;height:340px;margin-top:16px;"></div>
  <el-empty v-else description="暂无趋势数据" />
</template>

<!-- GG：原样不动 -->
<template v-else>
  <!-- 现有 6 个 tab，一字不改 -->
</template>
```

`<script setup>` 里追加（`fbApi` **当前未导入**，需一并加）：

```js
import { fbApi } from '@/api/fb'          // 新增（放在 :456 的 reportsApi 之后）

// 分析页按平台隔离（2026-10-11）：路由前缀即平台；/analysis 缺省 gg。
const analysisPlatform = computed(() => route.meta?.platform || 'gg')

// ---- FB 分支状态（只读 fb_ad_reports）----
const fbSummary = ref({ total_cost: 0, total_impressions: 0, total_clicks: 0,
                        record_count: 0, account_count: 0 })
const fbByLine = ref([])
const fbTrendPoints = ref([])
const fbTrendChart = ref(null)
let fbChart = null

async function loadFbDashboard() {
  // filterParams()（本文件 :581）的参数名与 Task 1 的端点口径是同一套，
  // 故直接复用，不另写一套筛选。
  const res = await fbApi.analysisDashboard(filterParams())
  fbSummary.value = res.summary || fbSummary.value
  fbByLine.value = res.by_line || []
}

async function loadFbTrends() {
  const res = await fbApi.analysisTrends(filterParams())
  fbTrendPoints.value = res.points || []
  await nextTick()
  if (!fbTrendChart.value || !fbTrendPoints.value.length) return
  if (fbChart) fbChart.dispose()
  fbChart = echarts.init(fbTrendChart.value)
  fbChart.setOption({
    tooltip: { trigger: 'axis' },
    grid: { left: 60, right: 20, top: 30, bottom: 40 },
    xAxis: { type: 'category', data: fbTrendPoints.value.map(p => p.report_date) },
    yAxis: { type: 'value', name: '花费' },
    series: [{
      name: '花费', type: 'line', smooth: true,
      data: fbTrendPoints.value.map(p => p.total_cost),
    }],
  })
}
```

**在既有 `onMounted` 的开头加平台短路**（这是 TT「不发请求」的落点，**最关键的一处**）：

```js
onMounted(() => {
  // 按平台分流：TT 无数据源 ⇒ **直接 return**，不发起任何取数
  // （含 /ad-reports/* 与 config/ai）。这是本 bug 的直接判据。
  if (analysisPlatform.value === 'tt') return
  if (analysisPlatform.value === 'fb') { loadFbDashboard(); loadFbTrends(); return }
  // ↓↓↓ 以下 GG 分支的原有逻辑一字不改 ↓↓↓
  /* 现有 onMounted 内容 */
})
```

**同样要按平台短路的地方**（逐一检查，凡会发 `/ad-reports/*` 或 `/config/ai` 的都要）：现有的 `watch`（若有）、各 tab 的懒加载取数、以及 AI 分析 tab 的初始化。**TT 下这些一律不得执行。**

**关键实现要求**：

1. **TT 分支绝不能触发请求** —— 判定标准是 DevTools Network 里**不出现任何 `/api/ad-reports/*`**。
2. **FB 分支**：复用 `filterParams()`（`:581-591`），它的参数名（`product_name` 逗号分隔、`from_date`、`to_date`）与 Task 1 的端点口径**是同一套**。FB 分支**不渲染 `region` 筛选**（FB 无该字段）。
3. **GG 分支**：一行不改。

- [ ] **Step 4: 起前端验证（需后端）**

```bash
cd frontend && npm run build && npm run dev
```

**验证第 1 条（最重要）**：用开发者账号从 **TT** 进「数据分析」→ 打开 DevTools Network → **过滤 `/api/` → 不应出现任何 `ad-reports` 请求**；页面显示「TT 暂无分析数据」。

> 后端要不要起、起哪个，**事前问协调者**（用户自己的 5001 连着真实库；协调者另有一套隔离栈的起法）。

**验证第 2 条**：从 FB 进 → 看到的是 FB 的花费数据（不是 GG 的）；Network 里是 `/api/fb/analysis/*`。

**验证第 3 条**：从 GG 进 → 6 个 tab 与改造前**完全一致**（回归）。

- [ ] **Step 5: 提交**

```bash
cd "D:/server/cc/GG-Server" && git add frontend/src/api/fb.js frontend/src/views/AnalysisView.vue docs/superpowers/specs/2026-10-11-analysis-platform-isolation-design.md && git commit -m "feat(analysis): 分析页按平台渲染（TT 空状态 / FB 花费看板）

TT 分支整页空状态且**不发起任何请求**（含 /ad-reports/* 与 config/ai）；
FB 分支复用同一份 filterParams 喂 /api/fb/analysis/*；
GG 分支一字不改。

视觉按 /frontend-design 产出，复用分析页既有 .stat-card 语法。" -- frontend/src/api/fb.js frontend/src/views/AnalysisView.vue docs/superpowers/specs/2026-10-11-analysis-platform-isolation-design.md
```

---

## Task 4: 端到端验收 + 代码审查

**Files:** 无新增；可能按审查意见回头改

- [ ] **Step 1: 逐条跑验收清单**

| # | 操作 | 期望 |
|---|---|---|
| 1 | 开发者从 **TT** 进「数据分析」 | 页面显示「TT 暂无分析数据」；**Network 里无任何 `/api/ad-reports/*`** |
| 2 | 开发者从 **FB** 进 | 看到 FB 自己的花费数据（金额与 `fb_ad_reports` 对得上，**不是** GG 的） |
| 3 | 开发者从 **GG** 进 | 6 个 tab 与改造前**完全一致**（含图表、筛选、AI 分析） |
| 4 | 直接手输 `/#/analysis` | 显示 GG 数据（该 URL 即 GG 页，**刻意如此**，不是串） |
| 5 | 四种角色（admin/viewer/huguan/普通）各访问两条新路由 | 行为与旧的 `/analysis` 一致，无越权、无被弹走 |
| 6 | FB 看板里展示/点击全 0 的行 | 有「数据不全」标注，不是让人误以为真的是 0 |
| 7 | 旧书签 `/analysis` | 不失效 |

- [ ] **Step 2: 跑全量**

```bash
cd py && python -m pytest tests/ -q
cd ../frontend && npm run build && npm test
```

预期：全绿。

- [ ] **Step 3: 调 `/code-review`**

本次改动触及**跨平台数据隔离**（本 bug 的核心），必须走代码审查。重点请审查者关注：
- FB 的两个端点里，`_fb_analysis_where` 的 SQL 是否**全部走参数绑定**（`product_name` 多值那段最容易写错成拼接）
- TT 分支是否**真的**没有任何请求路径（含 `onMounted`、`watch`、以及 AI 分析那个 tab 的懒加载）
- GG 分支是否**真的一字未改**（逐块 diff）

- [ ] **Step 4: 修完重跑 Step 1-2**

- [ ] **Step 5: 更新设计文档状态**为「已实现」，并把 §4 里那条「新路由的守卫核对」的实际结论补进去。

---

## 附：验收判据汇总

交付前逐条打勾：

- [ ] **从 TT 进分析页时，Network 里不出现任何 `/api/ad-reports/*`**（本 bug 的直接判据）
- [ ] 从 FB 进看到的是 FB 自己的数据
- [ ] 从 GG 进与改造前完全一致
- [ ] `py/tests/test_fb_analysis.py` 全绿，**含「往 ad_reports 塞同名数据也不串」那条**
- [ ] 全量 pytest 无新增失败
- [ ] 四条角色 × 两条新路由的守卫行为已核对并记录
- [ ] `/frontend-design` 已调用，产出已记入设计文档附录
- [ ] `/code-review` 已执行，问题已修复并重跑验收
