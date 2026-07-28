# Sheet 映射动态配置 — 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 Google Sheets 充值表 sheet 名称从硬编码改为可动态配置的映射表，前端可读取 sheet 列表并下拉选择。

**Architecture:** 在 `tags` 表中新增 `sheet_mappings` JSON 配置（功能 key → sheet 名），后端 `append_recharge()` 接受 `sheet_name` 参数替代硬编码，前端 SettingsPanel 增加读取按钮 + 动态下拉框。

**Tech Stack:** Python/Flask + Vue 3 + Element Plus + Google Sheets API v4

## Global Constraints

- 向后兼容：`sheet_mappings` 不存在时默认 `{"recharge": "充值表"}`
- `append_recharge()` 传入空 `sheet_name` 时回退到 `"充值表"`
- 前端下拉框 `allow-create`，API 失败时仍可手动输入
- 仅 admin/developer 可见充值表配置区域（保持现有权限）

---

### Task 1: 后端 — `append_recharge()` 增加 `sheet_name` 参数

**Files:**
- Modify: `py/google_sheets_service.py:266-344`

**Interfaces:**
- Produces: `append_recharge(service, spreadsheet_id: str, sheet_name: str, rows: list) -> dict`

- [ ] **Step 1: 修改函数签名和 sheet 查找逻辑**

把 `py/google_sheets_service.py` 中 `append_recharge` 函数的签名从：

```python
def append_recharge(service, spreadsheet_id: str, rows: list) -> dict:
```

改为：

```python
def append_recharge(service, spreadsheet_id: str, sheet_name: str, rows: list) -> dict:
```

- [ ] **Step 2: 修改 sheet 名获取逻辑**

将第 274-288 行的硬编码逻辑：

```python
    # 1. 获取表格信息，找到名为「充值表」的 sheet
    ss = service.spreadsheets().get(spreadsheetId=spreadsheet_id).execute()
    target_sheet = None
    for s in ss.get("sheets", []):
        props = s.get("properties", {})
        if props.get("title", "") == "充值表":
            target_sheet = {
                "name": props["title"],
                "gid": props["sheetId"],
                "rowCount": props.get("gridProperties", {}).get("rowCount", 1000),
            }
            break

    if not target_sheet:
        raise GoogleSheetsServiceError("表格中未找到「充值表」工作表")
```

替换为：

```python
    # 1. 按传入的 sheet_name 查找目标 sheet（为空时回退到「充值表」）
    effective_name = sheet_name.strip() if sheet_name else "充值表"
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
```

- [ ] **Step 3: 提交**

```bash
git add py/google_sheets_service.py
git commit -m "refactor: append_recharge 增加 sheet_name 参数，去掉硬编码"
```

---

### Task 2: 后端 — 新增 `_get_recharge_sheet_name()` 辅助函数 + 新增 sheets 列表 API

**Files:**
- Modify: `py/main.py`

**Interfaces:**
- Produces: `_get_recharge_sheet_name(db) -> str`
- Produces: `GET /api/google-sheets/sheets?spreadsheet_id=xxx`

- [ ] **Step 1: 在 `_parse_sheet_id` 函数后面添加辅助函数**

在 `py/main.py` 第 4077 行（`_parse_sheet_id` 函数之后、`recharge_submit` 之前）插入：

```python
def _get_recharge_sheet_name(db) -> str:
    """从 tags 表读取 sheet_mappings，提取 recharge 对应的 sheet 名。
    不存在时默认返回 '充值表'（向后兼容）。"""
    row = db.execute("SELECT value FROM tags WHERE key='sheet_mappings'").fetchone()
    if row and row["value"]:
        try:
            mappings = _json.loads(row["value"])
            if isinstance(mappings, dict):
                return (mappings.get("recharge") or "").strip() or "充值表"
        except Exception:
            pass
    return "充值表"
```

- [ ] **Step 2: 新增 `GET /api/google-sheets/sheets` 端点**

在 `py/main.py` 中找一个合适位置（建议放在 `google-sheets/status` 端点附近或 `_get_recharge_sheet_name` 之后），新增：

```python
@app.route("/api/google-sheets/sheets", methods=["GET"])
@jwt_required()
def google_sheets_list_sheets():
    """读取指定 spreadsheet 中的所有 sheet 名称列表。"""
    spreadsheet_id = (request.args.get("spreadsheet_id") or "").strip()
    if not spreadsheet_id:
        return jsonify({"success": False, "error": "缺少 spreadsheet_id"}), 400

    # 提取纯 ID（兼容完整 URL）
    sid = _parse_sheet_id(spreadsheet_id)
    if not sid:
        return jsonify({"success": False, "error": "无效的 spreadsheet ID"}), 400

    # 检查 Google Sheets 是否已配置
    creds_path = _GOOGLE_SHEETS_CONFIG.get("credentials_path", "")
    if not creds_path or not os.path.isfile(creds_path):
        return jsonify({"success": False, "error": "Google Sheets 未配置"}), 400

    try:
        import google_sheets_service as gs
        service = gs.build_service(creds_path)
        info = gs.get_spreadsheet_info(service, sid)
        return jsonify({"success": True, "sheets": info.get("sheets", [])})
    except gs.GoogleSheetsServiceError as e:
        return jsonify({"success": False, "error": str(e)}), 400
    except Exception as e:
        return jsonify({"success": False, "error": f"无法访问表格: {e}"}), 400
```

- [ ] **Step 3: 确认 `os` 已在文件顶部导入**

检查 `py/main.py` 顶部是否有 `import os`，如果没有则添加。

- [ ] **Step 4: 提交**

```bash
git add py/main.py
git commit -m "feat: 新增 _get_recharge_sheet_name 辅助函数 + GET /api/google-sheets/sheets 端点"
```

---

### Task 3: 后端 — 修改 settings API 支持 `sheet_mappings`

**Files:**
- Modify: `py/main.py:5090-5127`

**Interfaces:**
- Modifies: `GET /api/settings/account` — 响应新增 `sheet_mappings`
- Modifies: `POST /api/settings/account` — 请求体新增可选 `sheet_mappings`

- [ ] **Step 1: 修改 `account_settings_get`**

将第 5093 行的 keys 列表从：

```python
    keys = ["account_statuses", "account_agents", "mcc_levels", "sales_persons", "recharge_sheet_id"]
```

改为：

```python
    keys = ["account_statuses", "account_agents", "mcc_levels", "sales_persons", "recharge_sheet_id"]
```

并在 `result` 构建完成后、`db.close()` 之前，追加 `sheet_mappings` 处理逻辑：

```python
    # sheet_mappings 特殊处理：不存在时返回默认值
    sm_row = db.execute("SELECT value FROM tags WHERE key='sheet_mappings'").fetchone()
    if sm_row and sm_row["value"]:
        try:
            result["sheet_mappings"] = _json.loads(sm_row["value"])
        except Exception:
            result["sheet_mappings"] = {"recharge": "充值表"}
    else:
        result["sheet_mappings"] = {"recharge": "充值表"}
    db.close()
```

注意：需要把原来的 `db.close()` 移到新代码之后，或者保留在最后。

- [ ] **Step 2: 修改 `account_settings_save`**

将第 5121 行 keys 列表从：

```python
    for key in ["account_statuses", "account_agents", "mcc_levels", "sales_persons", "recharge_sheet_id"]:
```

改为：

```python
    for key in ["account_statuses", "account_agents", "mcc_levels", "sales_persons", "recharge_sheet_id", "sheet_mappings"]:
```

`sheet_mappings` 是一个 JSON 对象，`_json.dumps` 序列化后存入 `tags` 表，与其他 key 处理方式完全一致。

- [ ] **Step 3: 提交**

```bash
git add py/main.py
git commit -m "feat: settings API 增加 sheet_mappings 读写支持"
```

---

### Task 4: 后端 — 更新 5 处 `append_recharge` 调用，传入 sheet_name

**Files:**
- Modify: `py/main.py`（5 处调用点）

**Interfaces:**
- Consumes: `_get_recharge_sheet_name(db)` from Task 2
- Consumes: `append_recharge(service, sid, sheet_name, rows)` from Task 1

**5 处调用点及行号：**

| # | 行号 | 函数 | 场景 |
|---|---|---|---|
| 1 | ~3822 | `accounts_update` | 单账户状态变更 → 清账 |
| 2 | ~4051 | `accounts_batch_update` | 批量状态变更 → 清账 |
| 3 | ~4126 | `recharge_submit` | 单次充值 |
| 4 | ~4211 | `recharge_batch_submit` | 批量充值 |
| 5 | ~4321 | `recharge_retry_sheets` | 手动重试同步 |

每处的改动模式相同，以**调用点 3（单次充值）**为例：

- [ ] **Step 1: 修改调用点 3 — `recharge_submit`（第 4115-4126 行）**

在读取 `sheet_id` 的代码块中，同时读取 `sheet_name`。将：

```python
        # 2. 读配置，启动后台同步
        sheet_id_row = db.execute(
            "SELECT value FROM tags WHERE key='recharge_sheet_id'"
        ).fetchone()
        sheet_id = _parse_sheet_id(_json.loads(sheet_id_row["value"]) if (sheet_id_row and sheet_id_row["value"]) else "")
        db.close()

        if sheet_id:
            def _do_sync():
                import google_sheets_service as gs
                service = gs.build_service(_GOOGLE_SHEETS_CONFIG["credentials_path"])
                gs.append_recharge(service, sheet_id, [{
                    "account_id": account_id, "amount": amount,
                    "agent": agent, "operator": operator,
                }])
```

改为：

```python
        # 2. 读配置，启动后台同步
        sheet_id_row = db.execute(
            "SELECT value FROM tags WHERE key='recharge_sheet_id'"
        ).fetchone()
        sheet_id = _parse_sheet_id(_json.loads(sheet_id_row["value"]) if (sheet_id_row and sheet_id_row["value"]) else "")
        recharge_sheet_name = _get_recharge_sheet_name(db)
        db.close()

        if sheet_id:
            _sheet_name = recharge_sheet_name
            def _do_sync():
                import google_sheets_service as gs
                service = gs.build_service(_GOOGLE_SHEETS_CONFIG["credentials_path"])
                gs.append_recharge(service, sheet_id, _sheet_name, [{
                    "account_id": account_id, "amount": amount,
                    "agent": agent, "operator": operator,
                }])
```

- [ ] **Step 2: 同样模式修改其余 4 处调用点**

**调用点 1**（第 3813-3822 行，`accounts_update` 中的清账逻辑）：

在 `sheet_id_row = db.execute(...)` 之后添加 `recharge_sheet_name = _get_recharge_sheet_name(db)`，将 `gs.append_recharge(service, sheet_id, [clear_row])` 改为 `gs.append_recharge(service, sheet_id, recharge_sheet_name, [clear_row])`。

**调用点 2**（第 4033-4051 行，`accounts_batch_update` 中的批量清账）：

同上，在读取 `sheet_id` 后添加 `recharge_sheet_name = _get_recharge_sheet_name(db)`，将 `gs.append_recharge(service, sheet_id, _sheet_data)` 改为 `gs.append_recharge(service, sheet_id, recharge_sheet_name, _sheet_data)`。

**调用点 4**（第 4200-4211 行，`recharge_batch_submit`）：

在 `sheet_id_row = db.execute(...)` 之后、`db.close()` 之前添加 `recharge_sheet_name = _get_recharge_sheet_name(db)`，将 `gs.append_recharge(service, sheet_id, valid_rows)` 改为 `gs.append_recharge(service, sheet_id, recharge_sheet_name, valid_rows)`。

**调用点 5**（第 4311-4321 行，`recharge_retry_sheets`）：

在 `sheet_id_row = db.execute(...)` 之后添加 `recharge_sheet_name = _get_recharge_sheet_name(db)`，将 `gs.append_recharge(service, sheet_id, [{...}])` 改为 `gs.append_recharge(service, sheet_id, recharge_sheet_name, [{...}])`。

- [ ] **Step 3: 提交**

```bash
git add py/main.py
git commit -m "feat: 5 处 append_recharge 调用均传入动态 sheet_name"
```

---

### Task 5: 前端 — API 层 + Store 层

**Files:**
- Modify: `frontend/src/api/google-sheets.js`
- Modify: `frontend/src/stores/accounts.js`

**Interfaces:**
- Produces: `googleSheetsApi.listSheets(spreadsheetId)` → Promise
- Produces: `store.settings.sheet_mappings` (reactive)

- [ ] **Step 1: `google-sheets.js` 新增 `listSheets` 方法**

在 `frontend/src/api/google-sheets.js` 的 `googleSheetsApi` 对象中新增：

```js
  /** 读取指定 spreadsheet 中的所有 sheet 列表 */
  listSheets(spreadsheetId) {
    return api.get('/google-sheets/sheets', { params: { spreadsheet_id: spreadsheetId } })
  },
```

插入位置：`retrySync` 方法之后、对象闭合 `}` 之前。

- [ ] **Step 2: `accounts.js` store 增加 `sheet_mappings` 初始值**

在 `frontend/src/stores/accounts.js` 第 17 行的 `settings` state 中，增加 `sheet_mappings` 字段：

```js
    settings: { account_statuses: ['存活','死亡','验证','限额'], account_agents: [], mcc_levels: [], sales_persons: [], sheet_mappings: { recharge: '充值表' } },
```

- [ ] **Step 3: 提交**

```bash
git add frontend/src/api/google-sheets.js frontend/src/stores/accounts.js
git commit -m "feat: 前端 API 新增 listSheets，store 增加 sheet_mappings"
```

---

### Task 6: 前端 — SettingsPanel.vue UI 改造

**Files:**
- Modify: `frontend/src/views/SettingsPanel.vue`

**Interfaces:**
- Consumes: `googleSheetsApi.listSheets()` from Task 5
- Consumes: `store.settings.sheet_mappings` from Task 5

- [ ] **Step 1: 在 `<script setup>` 顶部新增 import 和常量**

```js
import { googleSheetsApi } from '@/api/google-sheets'

// Sheet 映射功能注册表（新增功能只需在此加一行，UI 自动渲染）
const SHEET_MAPPING_META = {
  recharge: { label: '充值表', description: '充值记录写入目标 sheet' },
}
```

- [ ] **Step 2: 在 `form` reactive 中增加 `sheet_mappings`**

将第 147-153 行的 `form` 从：

```js
const form = reactive({
  account_statuses: '',
  account_agents: '',
  mcc_levels: '',
  sales_persons: '',
  recharge_sheet_id: '',
})
```

改为：

```js
const form = reactive({
  account_statuses: '',
  account_agents: '',
  mcc_levels: '',
  sales_persons: '',
  recharge_sheet_id: '',
  sheet_mappings: { recharge: '充值表' },
})
```

- [ ] **Step 3: 新增响应式变量**

在 `const msg = ref('')` 之后添加：

```js
const readingSheets = ref(false)       // 「读取工作表」按钮 loading
const sheetOptions = ref([])           // API 返回的 sheet 名列表，供下拉框使用
const sheetOptionsLoaded = ref(false)  // 是否已成功读取过
```

- [ ] **Step 4: 新增 `readSheets` 函数**

在 `save` 函数之前添加：

```js
async function readSheets() {
  const rawId = form.recharge_sheet_id.trim()
  if (!rawId) {
    ElMessage.warning('请先输入表格链接或 ID')
    return
  }
  // 提取 spreadsheet ID
  const m = rawId.match(/spreadsheets\/d\/([a-zA-Z0-9_-]+)/)
  const sid = m ? m[1] : rawId

  readingSheets.value = true
  sheetOptionsLoaded.value = false
  try {
    const res = await googleSheetsApi.listSheets(sid)
    sheetOptions.value = (res.sheets || []).map(s => s.name)
    sheetOptionsLoaded.value = true
    ElMessage.success(`已读取 ${sheetOptions.value.length} 个工作表`)
  } catch (e) {
    sheetOptions.value = []
    ElMessage.error('读取工作表失败: ' + (e.response?.data?.error || e.message))
  } finally {
    readingSheets.value = false
  }
}
```

- [ ] **Step 5: 修改 `onMounted` 中的回显逻辑**

在第 182 行之后新增回显 `sheet_mappings`：

```js
  form.sheet_mappings = store.settings.sheet_mappings || { recharge: '充值表' }
```

- [ ] **Step 6: 修改 `save` 函数**

在第 222-228 行的 `body` 对象中增加 `sheet_mappings`：

```js
  const body = {
    account_statuses: form.account_statuses.split('\n').map(s => s.trim()).filter(Boolean),
    account_agents: form.account_agents.split('\n').map(s => s.trim()).filter(Boolean),
    mcc_levels: form.mcc_levels.split('\n').map(s => s.trim()).filter(Boolean),
    sales_persons: form.sales_persons.split('\n').map(s => s.trim()).filter(Boolean),
    recharge_sheet_id: sheetId,
    sheet_mappings: form.sheet_mappings,
  }
```

- [ ] **Step 7: 改造模板 — 替换充值表配置区域**

将第 30-36 行的模板：

```html
        <template v-if="authStore.isAdmin || authStore.isDeveloper">
          <el-divider />
          <h4 style="margin-bottom:8px;">📊 充值表配置（仅管理员可见）</h4>
          <el-form-item label="Google Sheets（URL 或 ID）">
            <el-input v-model="form.recharge_sheet_id" placeholder="粘贴表格链接或直接输入 spreadsheet ID" />
          </el-form-item>
        </template>
```

替换为：

```html
        <template v-if="authStore.isAdmin || authStore.isDeveloper">
          <el-divider />
          <h4 style="margin-bottom:8px;">📊 充值表配置（仅管理员可见）</h4>
          <el-form-item label="Google Sheets（URL 或 ID）">
            <div style="display:flex;gap:8px;width:100%;">
              <el-input v-model="form.recharge_sheet_id" placeholder="粘贴表格链接或直接输入 spreadsheet ID" style="flex:1;" />
              <el-button @click="readSheets" :loading="readingSheets">📋 读取工作表</el-button>
            </div>
          </el-form-item>
          <el-form-item label="Sheet 映射">
            <div style="width:100%;">
              <div v-for="(meta, key) in SHEET_MAPPING_META" :key="key" style="display:flex;align-items:center;gap:8px;margin-bottom:4px;">
                <span style="white-space:nowrap;font-size:13px;min-width:60px;">{{ meta.label }}</span>
                <el-select
                  v-model="form.sheet_mappings[key]"
                  filterable
                  allow-create
                  default-first-option
                  placeholder="选择或输入 sheet 名"
                  style="flex:1;"
                >
                  <el-option
                    v-for="name in sheetOptions"
                    :key="name"
                    :label="name"
                    :value="name"
                  />
                </el-select>
              </div>
              <span v-if="!sheetOptionsLoaded" style="font-size:11px;color:#909399;">点击「📋 读取工作表」加载可选 sheet 列表，也可直接手动输入</span>
              <span v-else style="font-size:11px;color:#059669;">已加载 {{ sheetOptions.length }} 个工作表可供选择</span>
            </div>
          </el-form-item>
        </template>
```

- [ ] **Step 8: 提交**

```bash
git add frontend/src/views/SettingsPanel.vue
git commit -m "feat: SettingsPanel 充值配置区改造 — 读取工作表 + 动态映射下拉框"
```

---

### Task 7: 验证测试

- [ ] **Step 1: 启动后端确认无语法错误**

```bash
cd py && python -c "import main; print('OK')"
```

- [ ] **Step 2: 前端构建检查**

```bash
cd frontend && npx vite build --mode development 2>&1 | tail -20
```
预期：无报错，正常完成构建。

- [ ] **Step 3: 手动测试清单**

| 测试项 | 预期 |
|---|---|
| 打开设置页 → 账户设置 Tab | admin 可见充值表配置区，普通用户不可见 |
| 输入表格 URL → 点击「📋 读取工作表」 | 下拉框加载 sheet 名列表，提示已加载 N 个 |
| 从下拉框选择 sheet | 选中值回显在下拉框中 |
| 手动输入不存在的 sheet 名 | 可正常输入并保存 |
| 不点「读取」直接保存 | 手动输入的 sheet 名正常保存 |
| 提交充值 → 检查 Sheets | 数据写入到配置的 sheet（而非硬编码「充值表」）|
| 清空 sheet_mappings 后读配置 | API 返回默认 `{"recharge":"充值表"}` |

- [ ] **Step 4: 提交（如有修复）**

```bash
git add -A && git commit -m "chore: 验证测试通过后的修复"
```
