# Google Sheets 做表数据自动写入 — 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 ToolkitView 中添加"更新你的表格"功能，将做表数据 upsert 到用户配置的 Google Sheet。

**Architecture:** 产品管理新增商务/代投比例字段 → `google_sheets_service.py` 新增写入方法 → `main.py` 新增 API 路由 → 前端 ToolkitView 新增产品下拉+日期+按钮，弹窗简化。数据流：解析做表数据 → 获取产品信息 + 表格标题 → 按 (日期, 客户ID, 广告系列) upsert 到表格 A-N 列。

**Tech Stack:** Python Flask + SQLite + Google Sheets API v4 + Vue 3 + Element Plus

## Global Constraints

- 纯增量原则：不修改原有功能的代码逻辑
- D列（广告账户ID）强制文本格式，E列（账号消耗）数字格式，L列（代投比例）百分比文本
- Upsert 唯一键：(日期, 客户ID, 渠道号)，不碰其他日期/产品数据
- agency_ratio 数据库存数字（如 `6`），写入表格格式化为 `"6%"`
- 表格标题格式 `运营名+年月`（如"卡尔202607"），解析失败 B 列留空

---

### Task 1: 数据库 — products 表新增字段

**Files:**
- Modify: `temp/app.db`（SQLite）

**Interfaces:**
- Produces: `products.sales_person TEXT DEFAULT ''`, `products.agency_ratio REAL DEFAULT NULL`

- [ ] **Step 1: 执行 ALTER TABLE**

```bash
cd d:/server/cc/GG-Server
sqlite3 temp/app.db "ALTER TABLE products ADD COLUMN sales_person TEXT DEFAULT '';"
sqlite3 temp/app.db "ALTER TABLE products ADD COLUMN agency_ratio REAL DEFAULT NULL;"
```

- [ ] **Step 2: 验证新列已添加**

```bash
sqlite3 temp/app.db "PRAGMA table_info(products);" | grep -E "sales_person|agency_ratio"
```

Expected: 显示两行，分别包含 `sales_person` 和 `agency_ratio`

- [ ] **Step 3: 提交**

```bash
git add temp/app.db
git commit -m "feat: products 表新增 sales_person、agency_ratio 列"
```

---

### Task 2: 后端 — products_create 适配新字段

**Files:**
- Modify: `py/main.py:2296-2350`

**Interfaces:**
- Consumes: `sales_person TEXT`, `agency_ratio REAL`（从请求 JSON）
- Produces: 新产品 INSERT 包含新字段，同名产品更新时同步更新新字段

- [ ] **Step 1: 提取新字段变量**

在 `products_create` 函数中（约第 2302 行，`customer` 变量之后），新增：

```python
    sales_person = (data.get("sales_person") or "").strip()
    agency_ratio = data.get("agency_ratio")
    if agency_ratio is not None:
        try:
            agency_ratio = float(agency_ratio)
        except (ValueError, TypeError):
            agency_ratio = None
```

- [ ] **Step 2: 修改同名产品存在时的 UPDATE 逻辑**

在 `existing` 分支中（约第 2324-2339 行），`if mcc_id is not None:` 块之后添加：

```python
        if sales_person:
            db.execute("UPDATE products SET sales_person=? WHERE id=?", (sales_person, pid))
        if agency_ratio is not None:
            db.execute("UPDATE products SET agency_ratio=? WHERE id=?", (agency_ratio, pid))
```

- [ ] **Step 3: 修改 INSERT 语句**

将第 2342 行的 INSERT：
```python
        db.execute("INSERT INTO products(product_name,kpi,region,mcc_id,customer,owner_id,runner_ids,created_at) VALUES(?,?,?,?,?,?,?,?)",
                   (product_name, kpi, region, mcc_id, customer, user_id, runner_ids, now))
```

改为：
```python
        db.execute("INSERT INTO products(product_name,kpi,region,mcc_id,customer,sales_person,agency_ratio,owner_id,runner_ids,created_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
                   (product_name, kpi, region, mcc_id, customer, sales_person, agency_ratio, user_id, runner_ids, now))
```

- [ ] **Step 4: 提交**

```bash
git add py/main.py
git commit -m "feat: products_create 支持 sales_person、agency_ratio 字段"
```

---

### Task 3: 后端 — products_update 白名单加入新字段

**Files:**
- Modify: `py/main.py:2361-2365`

**Interfaces:**
- Consumes: `sales_person`、`agency_ratio`（从 PUT 请求 body）
- Produces: 更新接口支持修改新字段

- [ ] **Step 1: 扩展 _product_fields 白名单**

将第 2362-2365 行：
```python
    _product_fields = {
        "product_name": "product_name", "kpi": "kpi", "region": "region",
        "status": "status", "mcc_id": "mcc_id", "customer": "customer",
    }
```

改为：
```python
    _product_fields = {
        "product_name": "product_name", "kpi": "kpi", "region": "region",
        "status": "status", "mcc_id": "mcc_id", "customer": "customer",
        "sales_person": "sales_person", "agency_ratio": "agency_ratio",
    }
```

- [ ] **Step 2: 提交**

```bash
git add py/main.py
git commit -m "feat: products_update 白名单加入 sales_person、agency_ratio"
```

---

### Task 4: 后端 — /ad-reports/products 返回新字段

**Files:**
- Modify: `py/main.py:5777-5794`

**Interfaces:**
- Produces: 返回的 products 数组中每个对象包含 `sales_person`、`agency_ratio`

- [ ] **Step 1: 修改 SELECT 查询**

将第 5783-5788 行的 SQL：
```python
    rows = db.execute("""
        SELECT DISTINCT p.id, p.product_name, p.region
        FROM products p
        ...
    """, ...)
```

改为：
```python
    rows = db.execute("""
        SELECT DISTINCT p.id, p.product_name, p.region, p.sales_person, p.agency_ratio
        FROM products p
        ...
    """, ...)
```

- [ ] **Step 2: 提交**

```bash
git add py/main.py
git commit -m "feat: /ad-reports/products 返回 sales_person、agency_ratio"
```

---

### Task 5: 前端 — ProductModal 新增商务/代投比例输入框

**Files:**
- Modify: `frontend/src/components/ProductModal.vue`

**Interfaces:**
- Produces: 编辑/新增产品时可输入 sales_person、agency_ratio

- [ ] **Step 1: 表单新增「商务」输入框**

在「客户」的 `el-form-item` 之后（约第 18 行后），添加：

```html
      <el-form-item label="商务">
        <el-input v-model="form.sales_person" placeholder="负责该产品的商务人员" />
      </el-form-item>
```

- [ ] **Step 2: 表单新增「代投比例」输入框**

在「商务」之后，添加：

```html
      <el-form-item label="代投比例">
        <el-input v-model.number="form.agency_ratio" placeholder="数字，如 6 表示 6%" />
      </el-form-item>
```

- [ ] **Step 3: form 对象加入新字段**

修改 `form` 的 `reactive` 初始化（约第 42 行）：
```javascript
const form = reactive({ product_name: '', kpi: '', region: '', customer: '', sales_person: '', agency_ratio: null, mcc_id: '' })
```

- [ ] **Step 4: init() 适配新字段**

修改 `init()` 中赋值逻辑（约第 55-57 行），在 `customer` 后添加：
```javascript
      sales_person: p.sales_person || '', agency_ratio: p.agency_ratio ?? null,
```

以及重置逻辑（约第 60 行）：
```javascript
    Object.assign(form, { product_name: '', kpi: '', region: '', customer: '', sales_person: '', agency_ratio: null, mcc_id: '' })
```

- [ ] **Step 5: 提交**

```bash
git add frontend/src/components/ProductModal.vue
git commit -m "feat: ProductModal 新增商务、代投比例输入框"
```

---

### Task 6: 后端 — google_sheets_service.py 新增 get_spreadsheet_title()

**Files:**
- Modify: `py/google_sheets_service.py`

**Interfaces:**
- Produces: `get_spreadsheet_title(service, spreadsheet_id) -> dict` 返回 `{"title": str, "sheets": [{"name": str, "gid": int}]}`

- [ ] **Step 1: 在文件末尾添加函数**

```python
def get_spreadsheet_info(service, spreadsheet_id: str) -> dict:
    """获取表格标题和所有 sheet（tab）信息。
    
    Args:
        service: Google Sheets API 服务对象
        spreadsheet_id: 表格 ID
    
    Returns:
        {
            "title": "卡尔202607",
            "operator": "卡尔",        # 从标题解析的运营名
            "year_month": "202607",    # 从标题解析的年月
            "sheets": [{"name": "Sheet1", "gid": 0}, ...]
        }
    """
    import re
    try:
        ss = service.spreadsheets().get(spreadsheetId=spreadsheet_id).execute()
    except Exception as e:
        raise GoogleSheetsServiceError(f"获取表格信息失败: {e}") from e
    
    title = ss.get("properties", {}).get("title", "")
    
    # 解析运营名和年月：格式为 <运营名><YYYYMM>
    operator = ""
    year_month = ""
    if title:
        m = re.match(r'^(\D+)(\d{6})$', title)
        if m:
            operator = m.group(1)
            year_month = m.group(2)
    
    sheets = []
    for s in ss.get("sheets", []):
        props = s.get("properties", {})
        sheets.append({
            "name": props.get("title", ""),
            "gid": props.get("sheetId", 0),
        })
    
    return {
        "title": title,
        "operator": operator,
        "year_month": year_month,
        "sheets": sheets,
    }
```

- [ ] **Step 2: 提交**

```bash
git add py/google_sheets_service.py
git commit -m "feat: 新增 get_spreadsheet_info() 获取表格标题和 sheet 列表"
```

---

### Task 7: 后端 — google_sheets_service.py 新增 upsert_zuobiao()

**Files:**
- Modify: `py/google_sheets_service.py`

**Interfaces:**
- Consumes: `service`, `spreadsheet_id`, `sheet_gid`, `rows`, `product_name`, `region`, `report_date`, `sales_person`, `agency_ratio`, `operator_name`
- Produces: `upsert_zuobiao(...) -> dict` 返回 `{"updated": int, "inserted": int}`

- [ ] **Step 1: 添加 upsert_zuobiao 函数**

在 `get_spreadsheet_info` 之后添加：

```python
def upsert_zuobiao(service, spreadsheet_id: str, sheet_gid: str, rows: list,
                   product_name: str, region: str, report_date: str,
                   sales_person: str, agency_ratio, operator_name: str) -> dict:
    """将做表数据 upsert 到 Google Sheets。
    
    以 (日期, 客户ID, 渠道号) 为唯一键，
    匹配到则覆盖该行，未匹配则在同日期行块下方插入新行。
    不触碰其他日期/产品的数据行。
    
    Args:
        service: Google Sheets API 服务对象
        spreadsheet_id: 表格 ID
        sheet_gid: sheet 的 gid（字符串数字）
        rows: 做表数据行列表 [{account, customerId, cost, campaign}, ...]
        product_name: 产品名 → G列
        region: 投放国家 → I列
        report_date: 日期 YYYY-MM-DD → A列
        sales_person: 商务 → H列
        agency_ratio: 代投比例（数字）→ L列，格式化为 "6%"
        operator_name: 运营名 → B列
    
    Returns:
        {"updated": int, "inserted": int}
    """
    # 将 gid 转为 sheet 名称，用于范围引用
    info = get_spreadsheet_info(service, spreadsheet_id)
    sheet_name = "Sheet1"
    for s in info.get("sheets", []):
        if str(s.get("gid", 0)) == str(sheet_gid):
            sheet_name = s["name"]
            break
    
    # 读取现有数据（A-N 列，跳过空行用原始索引）
    range_read = f"'{sheet_name}'!A:N"
    result = service.spreadsheets().values().get(
        spreadsheetId=spreadsheet_id,
        range=range_read,
    ).execute()
    existing = result.get("values", [])
    
    # 构建现有数据索引：(日期, 客户ID, 渠道号) -> 行号(0-based)
    existing_index = {}
    for i, row in enumerate(existing):
        if len(row) >= 10:
            key = (
                row[0].strip() if len(row) > 0 else "",        # A: 日期
                row[3].strip() if len(row) > 3 else "",        # D: 客户ID
                row[9].strip() if len(row) > 9 else "",        # J: 渠道号
            )
            if key[0] or key[1] or key[2]:
                existing_index[key] = i
    
    # 准备新数据行
    percent_str = f"{int(agency_ratio)}%" if agency_ratio is not None else ""
    
    new_rows = []
    for row in rows:
        new_rows.append([
            report_date,                    # A: 日期
            operator_name,                  # B: 运营
            row.get("account", ""),         # C: 账户名称
            row.get("customerId", ""),      # D: 广告账户ID
            str(row.get("cost", 0)),        # E: 账号消耗
            "",                             # F: 报给客户
            product_name,                   # G: 客户名称
            sales_person or "",             # H: 商务
            region,                         # I: 投放国家
            row.get("campaign", ""),        # J: 渠道号
            "",                             # K: 平台实际
            percent_str,                    # L: 代投比例
            "",                             # M: 代投费
            "",                             # N: 利润
        ])
    
    # 分拣：更新 vs 插入
    updates = []   # (row_idx_0based, new_row_data)
    inserts = []   # (target_date, new_row_data)  — 按日期分组插入
    for new_row in new_rows:
        key = (new_row[0], new_row[3], new_row[9])
        if key in existing_index:
            updates.append((existing_index[key], new_row))
        else:
            inserts.append((new_row[0], new_row))
    
    updated_count = 0
    inserted_count = 0
    
    # 批量更新（每行一个 range）
    if updates:
        for row_idx, row_data in updates:
            range_write = f"'{sheet_name}'!A{row_idx + 1}:N{row_idx + 1}"
            service.spreadsheets().values().update(
                spreadsheetId=spreadsheet_id,
                range=range_write,
                valueInputOption="USER_ENTERED",
                body={"values": [row_data]},
            ).execute()
            updated_count += 1
    
    # 批量插入：按日期分块，在同日期行下方插入
    if inserts:
        # 找到每个日期的最后一行
        date_last_row = {}
        for i, row in enumerate(existing):
            d = row[0].strip() if row else ""
            if d:
                date_last_row[d] = i  # 0-based, 最后出现的行号
        
        # 按日期分组待插入行
        from collections import defaultdict
        inserts_by_date = defaultdict(list)
        for target_date, row_data in inserts:
            inserts_by_date[target_date].append(row_data)
        
        # 按日期插入（从后往前插入，保持行号正确）
        total_existing = len(existing)
        rows_to_add = sum(len(v) for v in inserts_by_date.values())
        
        # 先扩充 sheet（如果需要）
        if total_existing < 1:
            total_existing = 1  # 至少有一行（可能是空行）
        
        # 用 batchUpdate 在需要的位置插入空行
        # 按日期排序，从后往前插入以避免行号偏移
        sorted_dates = sorted(inserts_by_date.keys())
        insert_requests = []
        cumulative_offset = 0
        insert_positions = {}  # date -> (start_row_1based, count)
        
        for target_date in sorted_dates:
            count = len(inserts_by_date[target_date])
            # 找到该日期的最后一行
            last_idx = date_last_row.get(target_date, total_existing - 1)
            # 插入位置 = 该日期最后一行之后（1-based）
            insert_after = last_idx + 1 + cumulative_offset
            insert_positions[target_date] = (insert_after + 1, count)  # start row (1-based), count
            cumulative_offset += count
        
        # 如果需要插入行，先扩充 sheet（在最末尾追加空行）
        needed = total_existing + cumulative_offset
        current_sheet_rows = 0
        ss_meta = service.spreadsheets().get(
            spreadsheetId=spreadsheet_id,
            ranges=[f"'{sheet_name}'"],
            fields="sheets/properties/gridProperties/rowCount"
        ).execute()
        for s in ss_meta.get("sheets", []):
            if str(s.get("properties", {}).get("sheetId", 0)) == str(sheet_gid):
                current_sheet_rows = s.get("properties", {}).get("gridProperties", {}).get("rowCount", 0)
                break
        
        if needed > current_sheet_rows:
            service.spreadsheets().batchUpdate(
                spreadsheetId=spreadsheet_id,
                body={
                    "requests": [{
                        "appendDimension": {
                            "sheetId": int(sheet_gid),
                            "dimension": "ROWS",
                            "length": needed - current_sheet_rows
                        }
                    }]
                }
            ).execute()
        
        # 从后往前写入插入数据（避免行号偏移影响）
        for target_date in reversed(sorted_dates):
            insert_rows = inserts_by_date[target_date]
            start_row, count = insert_positions[target_date]
            # 把 existing 中插入位置之后的数据下移
            if start_row <= total_existing + cumulative_offset:
                # 先写入新数据（如果位置在现有数据范围内，需要先搬移）
                pass
            
            # 直接写入到目标位置
            range_write = f"'{sheet_name}'!A{start_row}:N{start_row + count - 1}"
            service.spreadsheets().values().update(
                spreadsheetId=spreadsheet_id,
                range=range_write,
                valueInputOption="USER_ENTERED",
                body={"values": insert_rows},
            ).execute()
            inserted_count += count
    
    # 格式化 D列（文本）、E列（数字）、L列（百分比）
    # 这里使用 batchUpdate 设置列格式
    sheet_id_int = int(sheet_gid) if str(sheet_gid).isdigit() else 0
    # ... 格式设置（见后续步骤）
    
    return {"updated": updated_count, "inserted": inserted_count}
```

- [ ] **Step 2: 简化 — 直接用 values.append 追加 + values.update 覆盖**

由于复杂的插入逻辑容易出错，改用更稳健的方案：
  1. 读取现有数据
  2. 匹配到 → 覆盖原行
  3. 未匹配到 → 追加到表格末尾

```python
def upsert_zuobiao(service, spreadsheet_id: str, sheet_gid: str, rows: list,
                   product_name: str, region: str, report_date: str,
                   sales_person: str, agency_ratio, operator_name: str) -> dict:
    """将做表数据 upsert 到 Google Sheets。"""
    import re
    
    # 1. 解析 sheet 名称
    info = get_spreadsheet_info(service, spreadsheet_id)
    sheet_name = "Sheet1"
    for s in info.get("sheets", []):
        if str(s.get("gid", 0)) == str(sheet_gid):
            sheet_name = s["name"]
            break
    
    # 2. 读取现有数据
    range_read = f"'{sheet_name}'!A:N"
    result = service.spreadsheets().values().get(
        spreadsheetId=spreadsheet_id,
        range=range_read,
    ).execute()
    existing = result.get("values", [])
    
    # 3. 构建索引
    existing_index = {}
    for i, row in enumerate(existing):
        if len(row) >= 10:
            key = (
                (row[0] or "").strip() if len(row) > 0 else "",
                (row[3] or "").strip() if len(row) > 3 else "",
                (row[9] or "").strip() if len(row) > 9 else "",
            )
            if key[0] or key[1] or key[2]:
                existing_index[key] = i
    
    # 4. 构建新行
    percent_str = f"{int(agency_ratio)}%" if agency_ratio is not None else ""
    new_rows = []
    for row in rows:
        new_rows.append([
            report_date,
            operator_name,
            row.get("account", ""),
            str(row.get("customerId", "")),      # 强制字符串，防止数字化
            row.get("cost", 0),                   # 数字
            "",
            product_name,
            sales_person or "",
            region,
            row.get("campaign", ""),
            "",
            percent_str,
            "",
            "",
        ])
    
    # 5. 分拣：更新 vs 新增
    updates = []
    appends = []
    for new_row in new_rows:
        key = (new_row[0], new_row[3], new_row[9])
        if key in existing_index:
            updates.append((existing_index[key], new_row))
        else:
            appends.append(new_row)
    
    # 6. 批量更新已存在的行
    for row_idx, row_data in updates:
        range_write = f"'{sheet_name}'!A{row_idx + 1}:N{row_idx + 1}"
        service.spreadsheets().values().update(
            spreadsheetId=spreadsheet_id,
            range=range_write,
            valueInputOption="USER_ENTERED",
            body={"values": [row_data]},
        ).execute()
    
    # 7. 追加新行到末尾
    if appends:
        range_append = f"'{sheet_name}'!A:N"
        service.spreadsheets().values().append(
            spreadsheetId=spreadsheet_id,
            range=range_append,
            valueInputOption="USER_ENTERED",
            insertDataOption="INSERT_ROWS",
            body={"values": appends},
        ).execute()
    
    # 8. 格式化 D列（文本）、E列（数字）
    sheet_id_int = int(sheet_gid) if str(sheet_gid).isdigit() else 0
    requests = [
        {
            "repeatCell": {
                "range": {
                    "sheetId": sheet_id_int,
                    "startColumnIndex": 3,   # D列
                    "endColumnIndex": 4,
                },
                "cell": {
                    "userEnteredFormat": {
                        "numberFormat": {"type": "TEXT"}
                    }
                },
                "fields": "userEnteredFormat.numberFormat"
            }
        },
        {
            "repeatCell": {
                "range": {
                    "sheetId": sheet_id_int,
                    "startColumnIndex": 4,   # E列
                    "endColumnIndex": 5,
                },
                "cell": {
                    "userEnteredFormat": {
                        "numberFormat": {"type": "NUMBER", "pattern": "#,##0.00"}
                    }
                },
                "fields": "userEnteredFormat.numberFormat"
            }
        }
    ]
    service.spreadsheets().batchUpdate(
        spreadsheetId=spreadsheet_id,
        body={"requests": requests}
    ).execute()
    
    return {"updated": len(updates), "inserted": len(appends)}
```

- [ ] **Step 3: 提交**

```bash
git add py/google_sheets_service.py
git commit -m "feat: 新增 upsert_zuobiao() 做表数据写入 Google Sheets"
```

---

### Task 8: 后端 — 新增 POST /api/google-sheets/update-zuobiao 路由

**Files:**
- Modify: `py/main.py`（约第 4213 行之后，`/api/config/google-sheets` POST 之后）

**Interfaces:**
- Consumes: `POST {product_name, region, report_date, rows}` + JWT
- Produces: `{"success": bool, "updated": int, "inserted": int, "error": str}`

- [ ] **Step 1: 添加路由**

在 `/api/config/google-sheets` POST 路由之后（约第 4213 行），添加：

```python
@app.route("/api/google-sheets/update-zuobiao", methods=["POST"])
@jwt_required()
def google_sheets_update_zuobiao():
    """将做表数据写入用户激活的 Google Sheets 表格。"""
    user_id = int(get_jwt_identity())
    data = request.get_json(silent=True) or {}
    product_name = (data.get("product_name") or "").strip()
    region = (data.get("region") or "").strip()
    report_date = (data.get("report_date") or "").strip()
    rows = data.get("rows") or []

    if not product_name:
        return jsonify({"success": False, "error": "产品名不能为空"}), 400
    if not rows:
        return jsonify({"success": False, "error": "做表数据不能为空"}), 400

    # 读取用户激活的表格配置
    db = _yt_db()
    config_row = db.execute(
        "SELECT value FROM config WHERE key=?", (f"google_sheets_{user_id}",)
    ).fetchone()
    active_row = db.execute(
        "SELECT value FROM config WHERE key=?", (f"google_sheets_active_{user_id}",)
    ).fetchone()
    db.close()

    sheets = []
    if config_row:
        try:
            sheets = json.loads(config_row["value"])
        except Exception:
            sheets = []
    active_id = active_row["value"].strip() if active_row else ""

    if not sheets:
        return jsonify({"success": False, "error": "请先在个人中心配置 Google 表格"}), 400

    # 找到激活的表格配置
    active_config = None
    for s in sheets:
        if s.get("id") == active_id:
            active_config = s
            break
    if not active_config:
        active_config = sheets[0]

    spreadsheet_id = active_config.get("spreadsheet_id", "")
    sheet_gid = active_config.get("sheet_gid", "0")
    if not spreadsheet_id:
        return jsonify({"success": False, "error": "表格 ID 为空，请检查配置"}), 400

    # 获取产品的 sales_person 和 agency_ratio
    db2 = _yt_db()
    prod_row = db2.execute(
        "SELECT sales_person, agency_ratio FROM products WHERE product_name=?",
        (product_name,)
    ).fetchone()
    db2.close()
    sales_person = prod_row["sales_person"] if prod_row and prod_row["sales_person"] else ""
    agency_ratio = prod_row["agency_ratio"] if prod_row else None

    # 构建 Google Sheets 服务
    try:
        from google_sheets_service import build_service, get_spreadsheet_info, upsert_zuobiao, GoogleSheetsServiceError
    except ImportError:
        return jsonify({"success": False, "error": "Google Sheets 功能不可用"}), 500

    creds_path = _GOOGLE_SHEETS_CONFIG["credentials_path"]
    token_path = _GOOGLE_SHEETS_CONFIG["token_path"]

    try:
        service = build_service(creds_path, token_path)
        info = get_spreadsheet_info(service, spreadsheet_id)
        operator_name = info.get("operator", "")
    except GoogleSheetsServiceError as e:
        return jsonify({"success": False, "error": f"连接 Google Sheets 失败: {e}"}), 500

    try:
        result = upsert_zuobiao(
            service=service,
            spreadsheet_id=spreadsheet_id,
            sheet_gid=sheet_gid,
            rows=rows,
            product_name=product_name,
            region=region,
            report_date=report_date,
            sales_person=sales_person,
            agency_ratio=agency_ratio,
            operator_name=operator_name,
        )
        return jsonify({
            "success": True,
            "updated": result["updated"],
            "inserted": result["inserted"],
            "total": result["updated"] + result["inserted"],
        })
    except GoogleSheetsServiceError as e:
        return jsonify({"success": False, "error": f"写入表格失败: {e}"}), 500
```

- [ ] **Step 2: 提交**

```bash
git add py/main.py
git commit -m "feat: 新增 POST /api/google-sheets/update-zuobiao 路由"
```

---

### Task 9: 前端 API — google-sheets.js 新增 updateZuobiao()

**Files:**
- Modify: `frontend/src/api/google-sheets.js`

**Interfaces:**
- Produces: `googleSheetsApi.updateZuobiao(body) -> Promise`

- [ ] **Step 1: 添加方法**

在 `googleSheetsApi` 对象中，`saveConfig` 之后添加：

```javascript
  /** 将做表数据写入用户激活的 Google Sheets */
  updateZuobiao(body) {
    return api.post('/google-sheets/update-zuobiao', body)
  }
```

完整文件变为：

```javascript
import api from './client'

export const googleSheetsApi = {
  /** 检查 Google Sheets API 配置状态（OAuth 凭据等） */
  status() {
    return api.get('/google-sheets/status')
  },

  /** 获取当前用户的 Google Sheets 配置 */
  getConfig() {
    return api.get('/config/google-sheets')
  },

  /** 保存当前用户的 Google Sheets 配置 */
  saveConfig(body) {
    return api.post('/config/google-sheets', body)
  },

  /** 将做表数据写入用户激活的 Google Sheets */
  updateZuobiao(body) {
    return api.post('/google-sheets/update-zuobiao', body)
  }
}
```

- [ ] **Step 2: 提交**

```bash
git add frontend/src/api/google-sheets.js
git commit -m "feat: google-sheets API 新增 updateZuobiao()"
```

---

### Task 10: 前端 — ToolkitView.vue 改造

**Files:**
- Modify: `frontend/src/views/ToolkitView.vue`

**Interfaces:**
- Consumes: `googleSheetsApi.updateZuobiao()`, `/ad-reports/products`
- Produces: 产品下拉 + 日期选择 + 「更新你的表格」按钮 + 简化弹窗

**这是最大的改动，分步骤进行：**

- [ ] **Step 1: 模板 — 做表数据区域顶部新增产品/日期选择行**

在第 14 行（`<div style="flex-shrink:0;">` 之后）和 `<p style="color:#888...">` 之前，添加：

```html
        <div style="display:flex;gap:12px;align-items:center;margin-bottom:8px;">
          <el-select v-model="zbSelectedProduct" placeholder="搜索并选择产品..." filterable clearable style="width:220px;" :loading="zbProductsLoading" @change="onZbProductChange">
            <el-option v-for="p in zbProducts" :key="p.id" :label="p.product_name + (p.region ? ' (' + p.region + ')' : '')" :value="p.product_name" />
          </el-select>
          <el-date-picker v-model="zbSelectedDate" type="date" placeholder="选择日期" value-format="YYYY-MM-DD" style="width:150px;" />
        </div>
```

- [ ] **Step 2: 模板 — 按钮区域添加「更新你的表格」按钮**

在现有 `<el-button type="success" @click="zbSaveDialogVisible = true">` 之后添加：

```html
          <el-button v-if="zbShowSheetButtons" type="warning" @click="zbUpdateSheet" :loading="zbUpdatingSheet">📊 更新你的表格</el-button>
```

并将「保存到数据库」按钮的 `disabled` 条件改为使用统一的可见性：

```html
          <el-button v-if="zbShowSheetButtons" type="success" @click="zbSaveDialogVisible = true">💾 保存到数据库</el-button>
```

**注意**：原来的 `v-if="!zbYanghu"` 和 `:disabled="!zbRaw.length"` 改为统一的 `v-if="zbShowSheetButtons"`。

- [ ] **Step 3: 模板 — 简化保存弹窗**

将弹窗中的 `<el-form :inline="true" ...>` 产品/地区/日期选择块替换为只读展示：

```html
    <el-dialog v-model="zbSaveDialogVisible" title="💾 保存做表数据" width="95%" top="3vh" @open="onSaveDialogOpen">
      <div style="margin-bottom:12px;font-size:13px;color:#555;">
        <span>产品：<b>{{ zbSelectedProduct }}</b></span>
        <span style="margin-left:16px;">地区：<b>{{ zbSelectedRegion }}</b></span>
        <span style="margin-left:16px;">日期：<b>{{ zbSelectedDate }}</b></span>
      </div>
      <div style="margin-top:8px;">
        <!-- 表格部分不变 -->
      </div>
      <template #footer>
        <el-button @click="zbSaveDialogVisible = false">取消</el-button>
        <el-button type="primary" @click="zbDoSave" :loading="zbSaving">💾 保存</el-button>
      </template>
    </el-dialog>
```

移除 `<el-form>` 整块（原第 161-173 行），移除 `@@open="onSaveDialogOpen"` 中的产品加载逻辑（后续步骤处理）。

- [ ] **Step 4: 脚本 — 新增状态变量**

在 `<script setup>` 中（约第 297 行，`// ========== 保存到数据库相关状态 ==========` 附近），添加：

```javascript
// ========== 外层产品/日期选择（共享给保存弹窗和更新表格） ==========
const zbSelectedProduct = ref('')
const zbSelectedDate = ref(_yesterday())
const zbProducts = ref([])
const zbProductsLoading = ref(false)
const zbUpdatingSheet = ref(false)

// 从产品列表反查地区（选中产品名 → 产品信息）
const zbSelectedRegion = computed(() => {
  const p = zbProducts.value.find(x => x.product_name === zbSelectedProduct.value)
  return p ? p.region : ''
})

// 两个按钮的可见性条件一致
const zbShowSheetButtons = computed(() => {
  return zbSelectedProduct.value && zbRaw.value.length > 0 && !zbIncludeCampaignId.value && !zbYanghu.value
})
```

需要在文件顶部 import 中加上 `computed`（已存在，检查第 268 行）。

- [ ] **Step 5: 脚本 — 产品加载（在 onMounted 或 tab 切换时）**

添加产品加载函数，在组件挂载时调用：

```javascript
async function loadZbProducts() {
  zbProductsLoading.value = true
  try {
    const res = await api.get('/ad-reports/products')
    zbProducts.value = res.products || []
  } catch { zbProducts.value = [] }
  zbProductsLoading.value = false
}

function onZbProductChange(pname) {
  // 选择产品后，地区自动从产品信息获取（computed 已处理）
  // 无需额外操作，zbSelectedRegion 自动更新
}
```

在现有的 `onMounted` 调用后追加 `loadZbProducts()`（约第 531 行）。

- [ ] **Step 6: 脚本 — onSaveDialogOpen 简化**

修改 `onSaveDialogOpen` 函数：

```javascript
async function onSaveDialogOpen() {
  // 产品/日期/地区使用外层已选值，弹窗内不再重新选择
  saveRows.value = [...zbRaw.value]
}
```

移除了原来的 `zbSaveDate.value = _yesterday()` 和产品加载逻辑。

- [ ] **Step 7: 脚本 — zbDoSave 修改**

修改 `zbDoSave`，使用外层值替代弹窗的 `zbSaveProduct`/`zbSaveRegion`/`zbSaveDate`：

```javascript
async function zbDoSave() {
  if (!zbSelectedProduct.value) { ElMessage.warning('请选择产品'); return }
  if (!zbSelectedRegion.value) { ElMessage.warning('产品缺少地区信息'); return }
  if (!saveRows.value.length) { ElMessage.warning('没有可保存的数据'); return }
  zbSaving.value = true
  try {
    const checkRes = await api.post('/ad-reports/check-duplicates', {
      product_name: zbSelectedProduct.value,
      region: zbSelectedRegion.value,
      report_date: zbSelectedDate.value,
      rows: saveRows.value,
    })
    if (checkRes.duplicates && checkRes.duplicates.length) {
      duplicateItems.value = checkRes.duplicates.map(d => ({ ...d, resolved: false, decision: null }))
      zbSaveDialogVisible.value = false
      zbDupDialogVisible.value = true
    } else {
      const saveRes = await api.post('/ad-reports/save', {
        product_name: zbSelectedProduct.value,
        region: zbSelectedRegion.value,
        report_date: zbSelectedDate.value,
        rows: saveRows.value,
        override_ids: [],
      })
      ElMessage.success(`保存成功！已保存 ${saveRes.saved} 条`)
      zbSaveDialogVisible.value = false
    }
  } catch (e) { ElMessage.error('保存失败: ' + (e.message || '未知错误')) }
  zbSaving.value = false
}
```

- [ ] **Step 8: 脚本 — zbConfirmSave 修改**

同样替换为外层值：

```javascript
async function zbConfirmSave() {
  const unresolved = duplicateItems.value.filter(d => !d.resolved)
  if (unresolved.length) { ElMessage.warning('请处理所有重复数据'); return }
  zbSaving.value = true
  try {
    const overrideIds = duplicateItems.value
      .filter(d => d.decision === 'keep-new')
      .map(d => d.existing.id)
    const saveRes = await api.post('/ad-reports/save', {
      product_name: zbSelectedProduct.value,
      region: zbSelectedRegion.value,
      report_date: zbSelectedDate.value,
      rows: saveRows.value,
      override_ids: overrideIds,
    })
    ElMessage.success(`保存成功！已保存 ${saveRes.saved} 条，跳过 ${saveRes.skipped || 0} 条`)
    zbDupDialogVisible.value = false
  } catch (e) { ElMessage.error('保存失败: ' + (e.message || '未知错误')) }
  zbSaving.value = false
}
```

- [ ] **Step 9: 脚本 — 「更新你的表格」按钮处理函数**

```javascript
async function zbUpdateSheet() {
  if (!zbSelectedProduct.value) { ElMessage.warning('请选择产品'); return }
  if (!zbZuobiao.value.length) { ElMessage.warning('没有做表数据，请先解析'); return }
  zbUpdatingSheet.value = true
  try {
    const res = await googleSheetsApi.updateZuobiao({
      product_name: zbSelectedProduct.value,
      region: zbSelectedRegion.value,
      report_date: zbSelectedDate.value,
      rows: zbZuobiao.value,
    })
    ElMessage.success(`表格已更新！更新 ${res.updated} 条，新增 ${res.inserted} 条`)
  } catch (e) {
    ElMessage.error('更新表格失败: ' + (e.response?.data?.error || e.message))
  }
  zbUpdatingSheet.value = false
}
```

需要在 import 中加入 `googleSheetsApi`（约第 275 行）：
```javascript
import { googleSheetsApi } from '@/api/google-sheets'
```

- [ ] **Step 10: 弹窗表格 — 支持行数据 inline 编辑**

将弹窗中数据表格的每列改为可编辑的 `el-input`：

以「账号」列为例，将：
```html
<el-table-column prop="account" label="账号" min-width="100" />
```

改为：
```html
<el-table-column label="账号" min-width="100">
  <template #default="{ $index }">
    <el-input v-model="saveRows[$index].account" size="small" />
  </template>
</el-table-column>
```

同理修改「客户ID」「广告系列」「费用」「展示」「点击」「安装」「应用内操作」「每次操作费用」列。

- [ ] **Step 12: 清理不再需要的旧状态**

以下变量可以保留但不再直接使用（保留是怕其他地方引用）：
- `zbSaveProduct`、`zbSaveRegion`、`zbSaveDate` → 保留声明但不在弹窗中使用
- `zbSaveProducts`、`zbSaveProductsLoading` → 保留但外层已有 `zbProducts`/`zbProductsLoading`
- `onProductSelect` → 不需要了（外层 `onZbProductChange` 替代）

**保留旧变量声明不动**，仅不再在弹窗 UI 中使用，避免改出 bug。

- [ ] **Step 13: 提交**

```bash
git add frontend/src/views/ToolkitView.vue
git commit -m "feat: ToolkitView 新增产品/日期选择 + 更新表格按钮 + 弹窗简化"
```

---

### Task 11: 集成测试 & 验证

- [ ] **Step 1: 启动后端测试**

```bash
cd d:/server/cc/GG-Server
# 启动 Flask 服务
python py/main.py
```

验证路由可访问：
```bash
# 测试 products API 返回新字段
curl -H "Authorization: Bearer <token>" http://localhost:5001/api/ad-reports/products
# 预期返回包含 sales_person, agency_ratio
```

- [ ] **Step 2: 验证产品编辑功能**

前端操作：
1. 打开产品管理面板
2. 编辑一个产品，确认「商务」和「代投比例」字段显示正常
3. 填写并保存，刷新后确认数据保留

- [ ] **Step 3: 验证 ToolkitView 功能**

前端操作：
1. 打开工具集 → 做表数据
2. 确认产品下拉和日期选择器显示
3. 选择产品后，「保存到数据库」和「更新你的表格」按钮显示
4. 勾选「包含广告系列ID」或「养户」后按钮隐藏
5. 粘贴数据并解析
6. 点击「保存到数据库」，弹窗只显示数据表格（产品/地区/日期只读）
7. 点击「更新你的表格」，确认数据写入 Google Sheet

- [ ] **Step 4: 提交最终调整**

```bash
git add -A
git commit -m "chore: 集成验证通过，最终调整"
```
