# 数据管理 & 做表数据聚合 — 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 改造 ad_reports 保存逻辑为聚合 upsert，新增独立数据管理页面支持查看/编辑/删除/搜索/导出

**Architecture:** 后端改造 save/list 端点 + 新增 PUT/batch-delete/export 端点；前端新建 DataManageView.vue 独立页面，挂载到左侧导航；去重索引从 UNIQUE 降级为普通 INDEX

**Tech Stack:** Flask + SQLite + Vue 3 + Element Plus + ECharts

## Global Constraints

- 纯增量：不修改现有仪表盘/趋势/对比/多维分析的分析逻辑
- 保存逻辑按 `(report_date, product_name, account, customer_id, campaign)` 聚合后 upsert
- 所有端点校验 `user_id`，用户只能操作自己的数据
- 前端复用 Element Plus 组件和现有 CSS 模式
- 向后兼容：现有 ToolkitView 保存流程不受影响

---

## File Structure

| 文件 | 变更 | 职责 |
|------|------|------|
| `py/database.py` | 修改 | 去重索引迁移 v3：UNIQUE → 普通 INDEX |
| `py/main.py` | 修改 | 改造 save、list；新增 PUT/batch-delete/export 端点 |
| `py/tests/test_ad_reports.py` | 修改 | 新增聚合保存、编辑、批量删除、导出测试 |
| `frontend/src/views/DataManageView.vue` | **新建** | 数据管理页面：表格+筛选+编辑弹窗+删除+导出+新增 |
| `frontend/src/api/reports.js` | 修改 | 新增 updateReport、batchDeleteReports、exportReports 方法 |
| `frontend/src/router/index.js` | 修改 | 新增 /data-manage 路由 |
| `frontend/src/components/AppSidebar.vue` | 修改 | 新增"数据管理"导航项 |

---

### Task 1: 数据库迁移 — 去重索引降级

**Files:**
- Modify: `py/database.py:326-336`

**Interfaces:**
- Produces: 普通索引 `idx_ad_reports_dedup`（不再是 UNIQUE），迁移标记 `migrated_ad_reports_dedup_v3`

- [ ] **Step 1: 在 database.py 的 `_init_db` 中添加 v3 迁移**

在现有 `migrated_ad_reports_dedup_v2` 迁移块（约第 326-336 行）之后添加：

```python
    # 迁移：ad_reports 去重索引 v3 — 从 UNIQUE 降级为普通 INDEX（支持聚合 upsert）
    ar_migrated_v3 = conn.execute(
        "SELECT value FROM config WHERE key='migrated_ad_reports_dedup_v3'"
    ).fetchone()
    if not ar_migrated_v3:
        # 检查当前索引是否 UNIQUE
        idx_info = conn.execute(
            "SELECT sql FROM sqlite_master WHERE type='index' AND name='idx_ad_reports_dedup'"
        ).fetchone()
        if idx_info and 'UNIQUE' in (idx_info[0] or '').upper():
            conn.execute("DROP INDEX IF EXISTS idx_ad_reports_dedup")
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_ad_reports_dedup "
                "ON ad_reports(user_id, product_name, customer_id, campaign, report_date)"
            )
        conn.execute(
            "INSERT OR REPLACE INTO config(key,value) VALUES('migrated_ad_reports_dedup_v3','1')"
        )
```

- [ ] **Step 2: 验证迁移**

```bash
cd py && python -c "import database; db = database._get_db(); print('migration ok'); db.close()"
```

Expected: 输出 `migration ok`，无报错

- [ ] **Step 3: 确认索引不再是 UNIQUE**

```bash
cd py && python -c "
import database
db = database._get_db()
info = db.execute(\"SELECT sql FROM sqlite_master WHERE type='index' AND name='idx_ad_reports_dedup'\").fetchone()
print(info[0])
db.close()
"
```

Expected: 输出不含 `UNIQUE` 关键字

- [ ] **Step 4: Commit**

```bash
git add py/database.py
git commit -m "feat: ad_reports 去重索引 v3 — UNIQUE 降级为普通 INDEX 以支持聚合 upsert"
```

---

### Task 2: 改造 save 端点 — 聚合 + upsert

**Files:**
- Modify: `py/main.py:3936-4012`

**Interfaces:**
- Consumes: 普通索引 `idx_ad_reports_dedup`（来自 Task 1）
- Produces: 聚合后的 `ad_reports_save()` 端点，返回 `{success, saved, skipped, aggregated_from}`

- [ ] **Step 1: 重写 `ad_reports_save()` 函数**

替换 `py/main.py` 第 3963-4012 行（从 `# 处理覆盖` 到 `return` 之间的代码）：

```python
    # 处理覆盖：删除被选定覆盖的旧行
    override_set = set(override_ids)
    if override_set:
        placeholders = ",".join(["?"] * len(override_set))
        db.execute(
            f"DELETE FROM ad_reports WHERE id IN ({placeholders}) AND user_id=?",
            list(override_set) + [user_id]
        )

    # === 聚合步骤（新增）：按 (report_date, product_name, account, customer_id, campaign) SUM ===
    raw_count = len(rows)
    aggregated = {}
    for row in rows:
        account = str(row.get("account", "")).strip()
        customer_id = str(row.get("customerId", "")).strip()
        campaign = str(row.get("campaign", "")).strip()
        if not customer_id or not campaign:
            continue

        key = (report_date, product_name, account, customer_id, campaign)
        if key not in aggregated:
            aggregated[key] = {
                "account": account,
                "customer_id": customer_id,
                "campaign": campaign,
                "cost": float(row.get("cost", 0) or 0),
                "impressions": int(row.get("impressions", 0) or 0),
                "clicks": int(row.get("clicks", 0) or 0),
                "installs": float(row.get("installs", 0) or 0),
                "in_app_actions": float(row.get("inAppActions", 0) or 0),
                "cost_per_in_app": float(row.get("costPerInApp", 0) or 0),
            }
        else:
            existing = aggregated[key]
            existing["cost"] += float(row.get("cost", 0) or 0)
            existing["impressions"] += int(row.get("impressions", 0) or 0)
            existing["clicks"] += int(row.get("clicks", 0) or 0)
            existing["installs"] += float(row.get("installs", 0) or 0)
            existing["in_app_actions"] += float(row.get("inAppActions", 0) or 0)
            existing["cost_per_in_app"] += float(row.get("costPerInApp", 0) or 0)

    # === upsert 逻辑（替换原有 skip 逻辑）===
    saved = 0
    skipped = 0
    for key, agg_row in aggregated.items():
        _rdate, _pname, account, customer_id, campaign = key

        # 查询是否已有同维度记录
        existing = db.execute(
            "SELECT id, cost, impressions, clicks, installs, in_app_actions, cost_per_in_app "
            "FROM ad_reports WHERE user_id=? AND product_name=? "
            "AND account=? AND customer_id=? AND campaign=? AND report_date=?",
            (user_id, product_name, account, customer_id, campaign, report_date)
        ).fetchone()

        if existing and existing["id"] not in override_set:
            # 已存在 → UPDATE 累加
            db.execute(
                "UPDATE ad_reports SET "
                "cost = cost + ?, impressions = impressions + ?, clicks = clicks + ?, "
                "installs = installs + ?, in_app_actions = in_app_actions + ?, "
                "cost_per_in_app = cost_per_in_app + ?, saved_at = datetime('now','localtime') "
                "WHERE id=?",
                (agg_row["cost"], agg_row["impressions"], agg_row["clicks"],
                 agg_row["installs"], agg_row["in_app_actions"], agg_row["cost_per_in_app"],
                 existing["id"])
            )
            saved += 1
        elif existing and existing["id"] in override_set:
            # 旧记录已被 override 删除 → INSERT 新记录
            db.execute(
                "INSERT INTO ad_reports(user_id, product_name, region, report_date, "
                "account, customer_id, campaign, cost, impressions, clicks, installs, "
                "in_app_actions, cost_per_in_app) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (user_id, product_name, region, report_date,
                 account, customer_id, campaign,
                 agg_row["cost"], agg_row["impressions"], agg_row["clicks"],
                 agg_row["installs"], agg_row["in_app_actions"], agg_row["cost_per_in_app"])
            )
            saved += 1
        else:
            # 不存在 → INSERT
            db.execute(
                "INSERT INTO ad_reports(user_id, product_name, region, report_date, "
                "account, customer_id, campaign, cost, impressions, clicks, installs, "
                "in_app_actions, cost_per_in_app) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (user_id, product_name, region, report_date,
                 account, customer_id, campaign,
                 agg_row["cost"], agg_row["impressions"], agg_row["clicks"],
                 agg_row["installs"], agg_row["in_app_actions"], agg_row["cost_per_in_app"])
            )
            saved += 1

    db.commit()
    db.close()
    return jsonify({
        "success": True,
        "saved": saved,
        "skipped": skipped,
        "aggregated_from": raw_count
    })
```

- [ ] **Step 2: 运行现有测试确认不破坏原有逻辑**

```bash
cd py && python -m pytest tests/test_ad_reports.py -v -k "TestAdReportsSave or TestAdReportsCheckDuplicates" 2>&1 | tail -20
```

Expected: 大部分测试通过（部分测试因行为变化可能需调整）

- [ ] **Step 3: 查看失败的测试并评估**

```bash
cd py && python -m pytest tests/test_ad_reports.py::TestAdReportsSave -v 2>&1
```

关注 `test_save_duplicate_skipped_in_same_request` — 这个测试预期"重复跳过"，但新行为是"重复累加"，需要在 Task 8 中更新测试。

- [ ] **Step 4: Commit**

```bash
git add py/main.py
git commit -m "feat: ad_reports save 改为聚合累加 + upsert"
```

---

### Task 3: 新增 PUT 编辑端点

**Files:**
- Modify: `py/main.py`（在 delete 端点之前插入）

**Interfaces:**
- Produces: `PUT /api/ad-reports/<id>` — 编辑单条报告所有字段

- [ ] **Step 1: 在 main.py 中添加 PUT 端点**

在 delete 端点（`@app.route("/api/ad-reports/<int:report_id>", methods=["DELETE"])`，约第 4069 行）**之前**插入：

```python
@app.route("/api/ad-reports/<int:report_id>", methods=["PUT"])
@jwt_required()
def ad_reports_update(report_id):
    """编辑单条报告（仅 owner）。"""
    user_id = int(get_jwt_identity())
    data = request.get_json(silent=True) or {}

    db = _yt_db()

    # 确认记录存在且属于当前用户
    existing = db.execute(
        "SELECT id FROM ad_reports WHERE id=? AND user_id=?",
        (report_id, user_id)
    ).fetchone()
    if not existing:
        db.close()
        return jsonify({"success": False, "error": "记录不存在或无权操作"}), 404

    # 允许更新的字段
    updatable = [
        "product_name", "region", "report_date", "account",
        "customer_id", "campaign", "cost", "impressions",
        "clicks", "installs", "in_app_actions"
    ]
    sets = []
    params = []
    for field in updatable:
        if field in data:
            val = data[field]
            if field in ("cost", "installs", "in_app_actions"):
                val = float(val) if val != "" else 0.0
            elif field in ("impressions", "clicks"):
                val = int(val) if val != "" else 0
            else:
                val = str(val).strip() if val else ""
            sets.append(f"{field}=?")
            params.append(val)

    if not sets:
        db.close()
        return jsonify({"success": False, "error": "没有可更新的字段"}), 400

    params.append(report_id)
    db.execute(
        f"UPDATE ad_reports SET {', '.join(sets)}, saved_at=datetime('now','localtime') WHERE id=?",
        params
    )
    db.commit()
    db.close()
    return jsonify({"success": True})
```

- [ ] **Step 2: 快速手动测试**

```bash
cd py && python -m pytest tests/ -v -k "test_list" --no-header 2>&1 | tail -5
```

确认 list 端点仍正常工作

- [ ] **Step 3: Commit**

```bash
git add py/main.py
git commit -m "feat: 新增 PUT /api/ad-reports/<id> 编辑端点"
```

---

### Task 4: 新增批量删除端点

**Files:**
- Modify: `py/main.py`（在 PUT 端点之后、delete 端点之前插入）

**Interfaces:**
- Produces: `POST /api/ad-reports/batch-delete` — `{ids: [1,2,3]}` → `{success, deleted}`

- [ ] **Step 1: 在 main.py 中添加批量删除端点**

在 PUT 端点之后、单条 DELETE 端点之前插入：

```python
@app.route("/api/ad-reports/batch-delete", methods=["POST"])
@jwt_required()
def ad_reports_batch_delete():
    """批量删除报告（仅 owner）。"""
    user_id = int(get_jwt_identity())
    data = request.get_json(silent=True) or {}
    ids = data.get("ids") or []

    if not ids or not isinstance(ids, list):
        return jsonify({"success": False, "error": "请提供要删除的 ID 列表"}), 400

    db = _yt_db()
    placeholders = ",".join(["?"] * len(ids))
    db.execute(
        f"DELETE FROM ad_reports WHERE id IN ({placeholders}) AND user_id=?",
        list(ids) + [user_id]
    )
    deleted = db.changes()
    db.commit()
    db.close()
    return jsonify({"success": True, "deleted": deleted})
```

- [ ] **Step 2: Commit**

```bash
git add py/main.py
git commit -m "feat: 新增 POST /api/ad-reports/batch-delete 批量删除端点"
```

---

### Task 5: 新增导出 CSV 端点 + 增强 list 搜索

**Files:**
- Modify: `py/main.py`（list 端点 + 新增 export 端点）

**Interfaces:**
- Produces: `GET /api/ad-reports/export` — 按条件导出 CSV；`GET /api/ad-reports/list` 增加 `search` 参数

- [ ] **Step 1: 修改 list 端点增加搜索参数**

在 `ad_reports_list()` 函数（约第 4015 行）中，`to_date` 参数解析之后、`db = _yt_db()` 之前，添加：

```python
    search = request.args.get("search", "").strip()
```

然后在 WHERE 子句构建部分（约第 4028-4036 行），在日期条件之后添加搜索条件：

```python
    if search:
        where.append(
            "(account LIKE ? OR campaign LIKE ? OR customer_id LIKE ?)"
        )
        like_val = f"%{search}%"
        params.extend([like_val, like_val, like_val])
```

- [ ] **Step 2: 在 main.py 中添加导出端点**

在 list 端点之后、delete 端点之前插入：

```python
@app.route("/api/ad-reports/export", methods=["GET"])
@jwt_required()
def ad_reports_export():
    """导出做表数据为 CSV。"""
    import csv
    import io

    user_id = int(get_jwt_identity())
    product_name = request.args.get("product_name", "").strip()
    from_date = request.args.get("from_date", "").strip()
    to_date = request.args.get("to_date", "").strip()
    search = request.args.get("search", "").strip()

    db = _yt_db()
    where = ["user_id=?"]; params = [user_id]
    if product_name:
        where.append("product_name=?"); params.append(product_name)
    if from_date:
        where.append("report_date >= ?"); params.append(from_date)
    if to_date:
        where.append("report_date <= ?"); params.append(to_date)
    if search:
        like_val = f"%{search}%"
        where.append(
            "(account LIKE ? OR campaign LIKE ? OR customer_id LIKE ?)"
        )
        params.extend([like_val, like_val, like_val])

    rows = db.execute(
        f"SELECT product_name, report_date, region, account, customer_id, "
        f"campaign, cost, impressions, clicks, installs, in_app_actions "
        f"FROM ad_reports WHERE {' AND '.join(where)} ORDER BY saved_at DESC",
        params
    ).fetchall()
    db.close()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "产品名", "日期", "地区", "账户名", "客户ID", "广告系列",
        "花费", "展示", "点击", "安装", "应用内操作"
    ])
    for r in rows:
        writer.writerow(list(r))

    csv_content = output.getvalue()
    output.close()

    from flask import Response
    return Response(
        csv_content,
        mimetype="text/csv",
        headers={
            "Content-Disposition": "attachment; filename=ad_reports_export.csv",
            "Content-Type": "text/csv; charset=utf-8-sig",
        }
    )
```

- [ ] **Step 3: Commit**

```bash
git add py/main.py
git commit -m "feat: list 增加 search 参数 + 新增 CSV 导出端点"
```

---

### Task 6: 前端 API 层 — 新增接口方法

**Files:**
- Modify: `frontend/src/api/reports.js`

**Interfaces:**
- Produces: `updateReport(id, body)`, `batchDeleteReports(body)`, `exportReports(params)` 三个新方法

- [ ] **Step 1: 在 reports.js 中添加新方法**

```js
import api from './client'

export const reportsApi = {
  checkDuplicates: (body) => api.post('/ad-reports/check-duplicates', body),
  save:          (body) => api.post('/ad-reports/save', body),
  list:          (params) => api.get('/ad-reports/list', { params }),
  products:      () => api.get('/ad-reports/products'),
  delete:        (id) => api.delete(`/ad-reports/${id}`),
  update:        (id, body) => api.put(`/ad-reports/${id}`, body),
  batchDelete:   (body) => api.post('/ad-reports/batch-delete', body),
  export:        (params) => api.get('/ad-reports/export', { params, responseType: 'blob' }),
  dashboard:     (params) => api.get('/ad-reports/dashboard', { params }),
  trends:        (params) => api.get('/ad-reports/trends', { params }),
  compare:       (params) => api.get('/ad-reports/compare', { params }),
  crossUser:     (params) => api.get('/ad-reports/cross-user', { params }),
  multiAnalysis: (params) => api.get('/ad-reports/multi-analysis', { params }),
  multiAnalysisPost: (body) => api.post('/ad-reports/multi-analysis', body),
  multiAiChat:   (body) => api.post('/ad-reports/multi-ai-chat', body),
  analyze:       (body) => api.post('/ad-reports/analyze', body),
}
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/api/reports.js
git commit -m "feat: 前端 API 层新增 update/batchDelete/export 方法"
```

---

### Task 7: 路由 + 导航 — DataManageView 挂载

**Files:**
- Modify: `frontend/src/router/index.js`
- Modify: `frontend/src/components/AppSidebar.vue`

**Interfaces:**
- Produces: `/data-manage` 路由 + 左侧导航"数据管理"入口

- [ ] **Step 1: 添加路由**

在 `router/index.js` 的 routes 数组中，`/analysis` 路由之后添加：

```js
  {
    path: '/data-manage',
    component: () => import('../views/DataManageView.vue'),
    meta: { title: '数据管理' }
  },
```

- [ ] **Step 2: 添加导航项**

在 `AppSidebar.vue` 的 `navItems` 数组中，`analysis` 项之后添加：

```js
  { key: 'data-manage', icon: '📋', label: '数据管理', sections: [{ title: '数据', items: [{ icon:'📋',label:'数据管理',path:'/data-manage'}]}]},
```

同时更新 `watch` 中 `route.path` 的逻辑，在 for 循环之前或之内添加对 `data-manage` 的匹配。现有 watch 逻辑通过 `p.startsWith('/' + item.key)` 匹配，`data-manage` 会自动被匹配到。

- [ ] **Step 3: 验证前端构建**

```bash
cd frontend && npm run build 2>&1 | tail -5
```

可能因 DataManageView.vue 尚未创建而报错 — 这是预期的，Task 8 会创建。

- [ ] **Step 4: Commit**

```bash
git add frontend/src/router/index.js frontend/src/components/AppSidebar.vue
git commit -m "feat: 添加 /data-manage 路由和导航入口"
```

---

### Task 8: 创建 DataManageView.vue — 数据管理页面

**Files:**
- Create: `frontend/src/views/DataManageView.vue`

**Interfaces:**
- Consumes: `reportsApi.list()`, `reportsApi.update()`, `reportsApi.delete()`, `reportsApi.batchDelete()`, `reportsApi.export()`, `reportsApi.products()`
- Produces: 完整的数据管理页面组件

- [ ] **Step 1: 创建 DataManageView.vue**

```vue
<template>
  <div class="data-manage-page">
    <div class="page-header">
      <h2>📋 数据管理</h2>
      <p class="page-desc">查看、编辑、删除已保存的做表数据</p>
    </div>

    <!-- 筛选栏 -->
    <div class="filter-bar">
      <div class="filter-left">
        <el-select v-model="filterProduct" placeholder="全部产品" clearable style="width:160px" @change="loadData">
          <el-option v-for="p in products" :key="p" :label="p" :value="p" />
        </el-select>
        <el-date-picker
          v-model="dateRange" type="daterange" range-separator="~"
          start-placeholder="开始日期" end-placeholder="结束日期"
          value-format="YYYY-MM-DD" style="width:260px"
          @change="loadData"
        />
        <el-input
          v-model="searchKeyword" placeholder="搜索账户/系列/客户ID..."
          style="width:240px" clearable @input="onSearchDebounced"
        >
          <template #prefix><span>🔍</span></template>
        </el-input>
      </div>
      <div class="filter-right">
        <el-button @click="loadData">🔄 刷新</el-button>
        <el-button type="primary" @click="handleExport" :loading="exporting">📥 导出CSV</el-button>
        <el-button type="success" @click="openAddDialog">➕ 新增数据</el-button>
        <el-button type="danger" :disabled="selectedIds.length === 0" @click="handleBatchDelete">
          🗑 批量删除 ({{ selectedIds.length }})
        </el-button>
      </div>
    </div>

    <!-- 数据表格 -->
    <el-table
      :data="reports" stripe border style="width:100%" v-loading="loading"
      @selection-change="onSelectionChange" @sort-change="onSortChange"
    >
      <el-table-column type="selection" width="45" />
      <el-table-column prop="product_name" label="产品" width="110" sortable="custom" />
      <el-table-column prop="report_date" label="日期" width="110" sortable="custom" />
      <el-table-column prop="region" label="地区" width="70" sortable="custom" />
      <el-table-column prop="account" label="账户" width="120" sortable="custom" />
      <el-table-column prop="customer_id" label="客户ID" width="130" sortable="custom" />
      <el-table-column prop="campaign" label="广告系列" width="140" sortable="custom" />
      <el-table-column prop="cost" label="花费" width="100" sortable="custom" align="right">
        <template #default="{ row }">${{ formatNum(row.cost) }}</template>
      </el-table-column>
      <el-table-column prop="impressions" label="展示" width="90" sortable="custom" align="right">
        <template #default="{ row }">{{ formatNum(row.impressions) }}</template>
      </el-table-column>
      <el-table-column prop="clicks" label="点击" width="80" sortable="custom" align="right">
        <template #default="{ row }">{{ formatNum(row.clicks) }}</template>
      </el-table-column>
      <el-table-column prop="installs" label="安装" width="80" sortable="custom" align="right">
        <template #default="{ row }">{{ formatNum(row.installs) }}</template>
      </el-table-column>
      <el-table-column prop="in_app_actions" label="应用内操作" width="105" sortable="custom" align="right">
        <template #default="{ row }">{{ formatNum(row.in_app_actions) }}</template>
      </el-table-column>
      <el-table-column label="操作" width="140" fixed="right">
        <template #default="{ row }">
          <el-button size="small" type="primary" link @click="openEditDialog(row)">编辑</el-button>
          <el-popconfirm title="确定删除这条数据？" @confirm="handleDelete(row.id)">
            <template #reference>
              <el-button size="small" type="danger" link>删除</el-button>
            </template>
          </el-popconfirm>
        </template>
      </el-table-column>
    </el-table>

    <!-- 分页 -->
    <div class="pagination-wrap">
      <el-pagination
        v-model:current-page="page" v-model:page-size="pageSize"
        :page-sizes="[20, 50, 100, 200]" :total="total"
        layout="total, sizes, prev, pager, next"
        @current-change="loadData" @size-change="loadData"
      />
    </div>

    <!-- 编辑/新增弹窗 -->
    <el-dialog
      v-model="dialogVisible" :title="dialogTitle" width="480px"
      :close-on-click-modal="false"
    >
      <el-form :model="form" label-width="90px" label-position="left">
        <el-form-item label="产品名" required>
          <el-input v-model="form.product_name" placeholder="请输入产品名" />
        </el-form-item>
        <el-form-item label="日期" required>
          <el-date-picker v-model="form.report_date" type="date" value-format="YYYY-MM-DD" style="width:100%" />
        </el-form-item>
        <el-form-item label="地区">
          <el-input v-model="form.region" placeholder="如：巴西" />
        </el-form-item>
        <el-form-item label="账户名">
          <el-input v-model="form.account" placeholder="账户名" />
        </el-form-item>
        <el-form-item label="客户ID">
          <el-input v-model="form.customer_id" placeholder="xxx-xxx-xxxx" />
        </el-form-item>
        <el-form-item label="广告系列">
          <el-input v-model="form.campaign" placeholder="广告系列名" />
        </el-form-item>
        <el-form-item label="花费">
          <el-input-number v-model="form.cost" :min="0" :precision="2" style="width:100%" controls-position="right" />
        </el-form-item>
        <el-form-item label="展示">
          <el-input-number v-model="form.impressions" :min="0" :step="100" style="width:100%" controls-position="right" />
        </el-form-item>
        <el-form-item label="点击">
          <el-input-number v-model="form.clicks" :min="0" style="width:100%" controls-position="right" />
        </el-form-item>
        <el-form-item label="安装">
          <el-input-number v-model="form.installs" :min="0" :precision="1" style="width:100%" controls-position="right" />
        </el-form-item>
        <el-form-item label="应用内操作">
          <el-input-number v-model="form.in_app_actions" :min="0" :precision="1" style="width:100%" controls-position="right" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="handleSave">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, reactive, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { reportsApi } from '../api/reports'

// 筛选状态
const filterProduct = ref('')
const dateRange = ref(null)
const searchKeyword = ref('')
const products = ref([])

// 表格状态
const reports = ref([])
const loading = ref(false)
const total = ref(0)
const page = ref(1)
const pageSize = ref(50)
const selectedIds = ref([])
const sortProp = ref('')
const sortOrder = ref('')

// 弹窗状态
const dialogVisible = ref(false)
const dialogTitle = ref('')
const editingId = ref(null)
const saving = ref(false)
const exporting = ref(false)

const form = reactive({
  product_name: '', report_date: '', region: '',
  account: '', customer_id: '', campaign: '',
  cost: 0, impressions: 0, clicks: 0,
  installs: 0, in_app_actions: 0,
})

// 加载数据
async function loadData() {
  loading.value = true
  try {
    const params = { page: page.value, size: pageSize.value }
    if (filterProduct.value) params.product_name = filterProduct.value
    if (dateRange.value && dateRange.value.length === 2) {
      params.from_date = dateRange.value[0]
      params.to_date = dateRange.value[1]
    }
    if (searchKeyword.value) params.search = searchKeyword.value

    const { data } = await reportsApi.list(params)
    reports.value = data.reports || []
    total.value = data.total || 0
    products.value = data.products || []

    // 客户端排序
    if (sortProp.value) applyClientSort()
  } catch (e) {
    ElMessage.error('加载数据失败：' + (e.response?.data?.error || e.message))
  } finally {
    loading.value = false
  }
}

// 搜索 debounce
let searchTimer = null
function onSearchDebounced() {
  clearTimeout(searchTimer)
  searchTimer = setTimeout(() => { page.value = 1; loadData() }, 300)
}

// 客户端排序
function onSortChange({ prop, order }) {
  sortProp.value = prop
  sortOrder.value = order
  applyClientSort()
}

function applyClientSort() {
  if (!sortProp.value) return
  const key = sortProp.value
  const dir = sortOrder.value === 'ascending' ? 1 : -1
  reports.value.sort((a, b) => {
    const va = a[key] ?? '', vb = b[key] ?? ''
    if (typeof va === 'number') return (va - vb) * dir
    return String(va).localeCompare(String(vb)) * dir
  })
}

// 编辑弹窗
function openEditDialog(row) {
  dialogTitle.value = '编辑数据'
  editingId.value = row.id
  Object.assign(form, {
    product_name: row.product_name,
    report_date: row.report_date,
    region: row.region || '',
    account: row.account || '',
    customer_id: row.customer_id || '',
    campaign: row.campaign || '',
    cost: row.cost || 0,
    impressions: row.impressions || 0,
    clicks: row.clicks || 0,
    installs: row.installs || 0,
    in_app_actions: row.in_app_actions || 0,
  })
  dialogVisible.value = true
}

// 新增弹窗
function openAddDialog() {
  dialogTitle.value = '新增数据'
  editingId.value = null
  Object.assign(form, {
    product_name: '', report_date: '', region: '',
    account: '', customer_id: '', campaign: '',
    cost: 0, impressions: 0, clicks: 0,
    installs: 0, in_app_actions: 0,
  })
  dialogVisible.value = true
}

// 保存（编辑或新增）
async function handleSave() {
  if (!form.product_name.trim()) { ElMessage.warning('请输入产品名'); return }
  if (!form.report_date) { ElMessage.warning('请选择日期'); return }

  saving.value = true
  try {
    if (editingId.value) {
      // 编辑 → PUT
      await reportsApi.update(editingId.value, {
        product_name: form.product_name.trim(),
        report_date: form.report_date,
        region: form.region.trim(),
        account: form.account.trim(),
        customer_id: form.customer_id.trim(),
        campaign: form.campaign.trim(),
        cost: form.cost,
        impressions: form.impressions,
        clicks: form.clicks,
        installs: form.installs,
        in_app_actions: form.in_app_actions,
      })
      ElMessage.success('保存成功')
    } else {
      // 新增 → POST save
      await reportsApi.save({
        product_name: form.product_name.trim(),
        region: form.region.trim() || '未指定',
        report_date: form.report_date,
        rows: [{
          account: form.account,
          customerId: form.customer_id,
          campaign: form.campaign,
          cost: form.cost,
          impressions: form.impressions,
          clicks: form.clicks,
          installs: form.installs,
          inAppActions: form.in_app_actions,
        }],
      })
      ElMessage.success('新增成功')
    }
    dialogVisible.value = false
    loadData()
  } catch (e) {
    ElMessage.error('保存失败：' + (e.response?.data?.error || e.message))
  } finally {
    saving.value = false
  }
}

// 单条删除
async function handleDelete(id) {
  try {
    await reportsApi.delete(id)
    ElMessage.success('删除成功')
    loadData()
  } catch (e) {
    ElMessage.error('删除失败：' + (e.response?.data?.error || e.message))
  }
}

// 批量删除
async function handleBatchDelete() {
  try {
    await ElMessageBox.confirm(
      `确定删除选中的 ${selectedIds.value.length} 条数据？此操作不可撤销。`,
      '批量删除', { confirmButtonText: '确定', cancelButtonText: '取消', type: 'warning' }
    )
    await reportsApi.batchDelete({ ids: selectedIds.value })
    ElMessage.success(`成功删除 ${selectedIds.value.length} 条`)
    selectedIds.value = []
    loadData()
  } catch (e) {
    if (e !== 'cancel' && e !== 'close') {
      ElMessage.error('批量删除失败：' + (e.response?.data?.error || e.message))
    }
  }
}

// 导出 CSV
async function handleExport() {
  exporting.value = true
  try {
    const params = {}
    if (filterProduct.value) params.product_name = filterProduct.value
    if (dateRange.value && dateRange.value.length === 2) {
      params.from_date = dateRange.value[0]
      params.to_date = dateRange.value[1]
    }
    if (searchKeyword.value) params.search = searchKeyword.value

    const response = await reportsApi.export(params)
    const url = window.URL.createObjectURL(new Blob([response.data], { type: 'text/csv;charset=utf-8-sig' }))
    const link = document.createElement('a')
    link.href = url
    link.download = 'ad_reports_export.csv'
    link.click()
    window.URL.revokeObjectURL(url)
    ElMessage.success('导出成功')
  } catch (e) {
    ElMessage.error('导出失败：' + (e.response?.data?.error || e.message))
  } finally {
    exporting.value = false
  }
}

function onSelectionChange(selection) {
  selectedIds.value = selection.map(r => r.id)
}

function formatNum(v) {
  if (v == null) return '0'
  return Number(v).toLocaleString('en-US', { maximumFractionDigits: 2 })
}

onMounted(() => {
  loadData()
})
</script>

<style scoped>
.data-manage-page { padding: 20px 24px; }
.page-header { margin-bottom: 16px; }
.page-header h2 { margin: 0 0 4px; font-size: 20px; color: #111827; }
.page-desc { margin: 0; font-size: 13px; color: #6b7280; }

.filter-bar { display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 10px; margin-bottom: 16px; }
.filter-left { display: flex; gap: 10px; align-items: center; flex-wrap: wrap; }
.filter-right { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }

.pagination-wrap { display: flex; justify-content: flex-end; margin-top: 16px; }
</style>
```

- [ ] **Step 2: 构建前端验证**

```bash
cd frontend && npm run build 2>&1 | tail -10
```

Expected: 构建成功，无报错

- [ ] **Step 3: Commit**

```bash
git add frontend/src/views/DataManageView.vue
git commit -m "feat: 新建 DataManageView — 数据管理页面（查看/编辑/删除/搜索/导出/新增）"
```

---

### Task 9: 后端测试 — 聚合保存 + 编辑 + 批量删除 + 导出

**Files:**
- Modify: `py/tests/test_ad_reports.py`

**Interfaces:**
- Consumes: Task 2-5 的所有新端点

- [ ] **Step 1: 添加聚合保存测试**

在 `TestAdReportsSave` 类末尾添加：

```python
    def test_save_aggregates_same_dimension_rows(self, client, auth_headers):
        """同维度多条数据应聚合 SUM 后保存为一条。"""
        rows = [
            {"account": "Agg", "customerId": "agg-111", "campaign": "AggCamp",
             "cost": 100, "impressions": 1000, "clicks": 50,
             "installs": 10, "inAppActions": 5, "costPerInApp": 10},
            {"account": "Agg", "customerId": "agg-111", "campaign": "AggCamp",
             "cost": 50, "impressions": 500, "clicks": 25,
             "installs": 5, "inAppActions": 2, "costPerInApp": 25},
        ]
        resp = client.post("/api/ad-reports/save", json={
            "product_name": "test_agg_prod",
            "region": "巴西", "report_date": "2026-07-01",
            "rows": rows, "override_ids": [],
        }, headers=auth_headers)
        data = resp.get_json()
        assert data["success"] is True
        # 两行同维度 → 聚合成 1 条
        assert data["saved"] == 1
        assert data["aggregated_from"] == 2

        # 验证聚合值
        list_resp = client.get(
            "/api/ad-reports/list?product_name=test_agg_prod", headers=auth_headers
        )
        reports = list_resp.get_json()["reports"]
        assert len(reports) == 1
        r = reports[0]
        assert r["cost"] == 150  # 100 + 50
        assert r["impressions"] == 1500  # 1000 + 500
        assert r["clicks"] == 75  # 50 + 25
        assert r["installs"] == 15  # 10 + 5
        assert r["in_app_actions"] == 7  # 5 + 2

    def test_save_upsert_accumulates_on_existing(self, client, auth_headers):
        """同维度再次保存应累加到已有记录。"""
        rows = [{"account": "Up", "customerId": "up-111", "campaign": "UpCamp",
                 "cost": 100, "impressions": 1000, "clicks": 50,
                 "installs": 10, "inAppActions": 5, "costPerInApp": 20}]
        # 第一次
        client.post("/api/ad-reports/save", json={
            "product_name": "test_up_prod",
            "region": "巴西", "report_date": "2026-07-01",
            "rows": rows, "override_ids": [],
        }, headers=auth_headers)
        # 第二次 — 同样的维度
        resp = client.post("/api/ad-reports/save", json={
            "product_name": "test_up_prod",
            "region": "巴西", "report_date": "2026-07-01",
            "rows": rows, "override_ids": [],
        }, headers=auth_headers)
        data = resp.get_json()
        assert data["success"] is True
        assert data["saved"] == 1  # UPDATE 了已有记录

        # 验证数值累加
        list_resp = client.get(
            "/api/ad-reports/list?product_name=test_up_prod", headers=auth_headers
        )
        reports = list_resp.get_json()["reports"]
        assert len(reports) == 1
        r = reports[0]
        assert r["cost"] == 200  # 100 + 100
```

- [ ] **Step 2: 添加编辑测试**

在文件末尾添加新测试类：

```python
class TestAdReportsUpdate:
    """PUT /api/ad-reports/<id> — 编辑单条报告。"""

    def test_update_report_fields(self, client, auth_headers):
        """编辑报告字段成功。"""
        # 准备数据
        rows = [{"account": "Ed", "customerId": "ed-111", "campaign": "EdCamp",
                 "cost": 100, "impressions": 1000, "clicks": 50,
                 "installs": 10, "inAppActions": 5, "costPerInApp": 20}]
        client.post("/api/ad-reports/save", json={
            "product_name": "test_edit_prod",
            "region": "巴西", "report_date": "2026-07-01",
            "rows": rows, "override_ids": [],
        }, headers=auth_headers)

        list_resp = client.get(
            "/api/ad-reports/list?product_name=test_edit_prod", headers=auth_headers
        )
        rid = list_resp.get_json()["reports"][0]["id"]

        # 编辑
        resp = client.put(f"/api/ad-reports/{rid}", json={
            "cost": 999, "impressions": 888, "campaign": "UpdatedCamp",
        }, headers=auth_headers)
        assert resp.get_json()["success"] is True

        # 验证
        list_resp2 = client.get(
            "/api/ad-reports/list?product_name=test_edit_prod", headers=auth_headers
        )
        r = list_resp2.get_json()["reports"][0]
        assert r["cost"] == 999
        assert r["impressions"] == 888
        assert r["campaign"] == "UpdatedCamp"

    def test_update_nonexistent_returns_404(self, client, auth_headers):
        """编辑不存在的记录返回 404。"""
        resp = client.put("/api/ad-reports/99999", json={
            "cost": 100
        }, headers=auth_headers)
        assert resp.status_code == 404

    def test_update_cannot_modify_others_data(self, client, auth_headers):
        """不能编辑其他用户的数据。"""
        # 用另一个用户创建的记录 ID
        resp = client.put("/api/ad-reports/99999", json={
            "cost": 100
        }, headers=auth_headers)
        assert resp.status_code == 404
```

- [ ] **Step 3: 添加批量删除测试**

```python
class TestAdReportsBatchDelete:
    """POST /api/ad-reports/batch-delete — 批量删除。"""

    def test_batch_delete(self, client, auth_headers):
        """批量删除多条记录。"""
        rows = [
            {"account": "BD1", "customerId": "bd-111", "campaign": "BDCamp1",
             "cost": 10, "impressions": 100, "clicks": 10,
             "installs": 1, "inAppActions": 0, "costPerInApp": 10},
            {"account": "BD2", "customerId": "bd-222", "campaign": "BDCamp2",
             "cost": 20, "impressions": 200, "clicks": 20,
             "installs": 2, "inAppActions": 0, "costPerInApp": 10},
        ]
        client.post("/api/ad-reports/save", json={
            "product_name": "test_bd_prod",
            "region": "巴西", "report_date": "2026-07-01",
            "rows": rows, "override_ids": [],
        }, headers=auth_headers)

        list_resp = client.get(
            "/api/ad-reports/list?product_name=test_bd_prod", headers=auth_headers
        )
        ids = [r["id"] for r in list_resp.get_json()["reports"]]

        resp = client.post("/api/ad-reports/batch-delete", json={
            "ids": ids
        }, headers=auth_headers)
        data = resp.get_json()
        assert data["success"] is True
        assert data["deleted"] == len(ids)

    def test_batch_delete_requires_ids(self, client, auth_headers):
        """空 ids 返回 400。"""
        resp = client.post("/api/ad-reports/batch-delete", json={"ids": []}, headers=auth_headers)
        assert resp.status_code == 400
```

- [ ] **Step 4: 添加导出和搜索测试**

```python
class TestAdReportsExport:
    """GET /api/ad-reports/export — CSV 导出。"""

    def test_export_returns_csv(self, client, auth_headers):
        """导出返回 CSV 格式。"""
        rows = [{"account": "Exp", "customerId": "exp-111", "campaign": "ExpCamp",
                 "cost": 50, "impressions": 500, "clicks": 25,
                 "installs": 5, "inAppActions": 2, "costPerInApp": 25}]
        client.post("/api/ad-reports/save", json={
            "product_name": "test_exp_prod",
            "region": "巴西", "report_date": "2026-07-01",
            "rows": rows, "override_ids": [],
        }, headers=auth_headers)

        resp = client.get("/api/ad-reports/export?product_name=test_exp_prod", headers=auth_headers)
        assert resp.status_code == 200
        assert "text/csv" in resp.content_type
        content = resp.data.decode("utf-8-sig")
        assert "产品名" in content
        assert "test_exp_prod" in content


class TestAdReportsListSearch:
    """GET /api/ad-reports/list — 搜索参数。"""

    def test_list_search_by_account(self, client, auth_headers):
        """搜索账户名匹配。"""
        rows = [
            {"account": "SearchMe", "customerId": "sr-111", "campaign": "SrcCamp",
             "cost": 50, "impressions": 500, "clicks": 25,
             "installs": 5, "inAppActions": 2, "costPerInApp": 25},
            {"account": "OtherAcc", "customerId": "sr-222", "campaign": "OthCamp",
             "cost": 30, "impressions": 300, "clicks": 15,
             "installs": 3, "inAppActions": 1, "costPerInApp": 30},
        ]
        client.post("/api/ad-reports/save", json={
            "product_name": "test_srch_prod",
            "region": "巴西", "report_date": "2026-07-01",
            "rows": rows, "override_ids": [],
        }, headers=auth_headers)

        resp = client.get("/api/ad-reports/list?search=SearchMe", headers=auth_headers)
        data = resp.get_json()
        assert data["success"] is True
        # 只匹配到 SearchMe
        assert data["total"] == 1
        assert data["reports"][0]["account"] == "SearchMe"

    def test_list_search_by_campaign(self, client, auth_headers):
        """搜索系列名匹配。"""
        resp = client.get("/api/ad-reports/list?search=SrcCamp", headers=auth_headers)
        data = resp.get_json()
        assert data["total"] >= 1
```

- [ ] **Step 5: 运行全部新测试**

```bash
cd py && python -m pytest tests/test_ad_reports.py -v -k "test_save_aggregates or test_save_upsert or TestAdReportsUpdate or TestAdReportsBatchDelete or TestAdReportsExport or TestAdReportsListSearch" 2>&1
```

Expected: 全部 PASS

- [ ] **Step 6: 运行完整测试套件确认无回归**

```bash
cd py && python -m pytest tests/test_ad_reports.py -v 2>&1
```

如果有失败（特别是 `test_save_duplicate_skipped_in_same_request`），更新它以匹配新行为：

```python
    def test_save_duplicate_skipped_in_same_request(self, client, auth_headers):
        """同请求中同维度多条数据应聚合成一条（不再跳过）。"""
        rows = [{"account": "Dup", "customerId": "dup-111", "campaign": "DupCamp",
                 "cost": 100, "impressions": 100, "clicks": 10,
                 "installs": 1, "inAppActions": 0, "costPerInApp": 100}]
        resp = client.post("/api/ad-reports/save", json={
            "product_name": "test_dup_prod2",
            "region": "巴西", "report_date": "2026-07-01",
            "rows": rows, "override_ids": [],
        }, headers=auth_headers)
        data = resp.get_json()
        assert data["success"] is True
        assert data["saved"] == 1  # 聚合成 1 条
```

- [ ] **Step 7: Commit**

```bash
git add py/tests/test_ad_reports.py
git commit -m "test: 新增聚合保存/编辑/批量删除/导出/搜索测试"
```

---

### Task 10: 端到端验证 + 最终提交

- [ ] **Step 1: 运行全部后端测试**

```bash
cd py && python -m pytest tests/ -v 2>&1 | tail -20
```

Expected: 全部通过

- [ ] **Step 2: 构建前端**

```bash
cd frontend && npm run build 2>&1 | tail -10
```

Expected: 构建成功

- [ ] **Step 3: 最终 commit（如有未提交的变更）**

```bash
git status
git add -A
git commit -m "chore: 数据管理 & 聚合保存 — 最终整理"
```
