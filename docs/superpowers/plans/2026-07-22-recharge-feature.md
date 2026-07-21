# 账户充值功能 — 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 AdsAccountPanel 新增单次/批量充值功能，写入 SQLite + Google Sheets 双存储，账户死亡时自动追加清账记录。

**Architecture:** 后端新增 `recharge_records` 表 + 两个充值 API 端点，`google_sheets_service.py` 新增追加方法。前端新增两个充值弹窗组件，`AdsAccountPanel` 加按钮入口，`SettingsPanel` 加充值表配置。

**Tech Stack:** Python Flask + SQLite + Google Sheets API / Vue 3 + Pinia + Element Plus

## Global Constraints

- 充值表 Sheet 名为「充值表」，按名称定位
- 普通充值只追加不做去重；死亡清账按 account_id 去重
- Sheets E 列（时间）、F 列（是否充值）始终留空
- 充值表配置仅 admin/developer 可见
- 写入顺序：先 DB，后 Sheets（Sheets 失败不影响 DB）

---

## 文件结构

| 文件 | 操作 | 职责 |
|---|---|---|
| `py/database.py` | 修改 | 新增 `recharge_records` 表 |
| `py/google_sheets_service.py` | 修改 | 新增 `append_recharge()` |
| `py/main.py` | 修改 | 新增充值路由；扩展 settings；死亡清账挂钩 |
| `frontend/src/api/accounts.js` | 修改 | 新增充值 API 函数 |
| `frontend/src/stores/accounts.js` | 修改 | 新增充值 actions |
| `frontend/src/components/RechargeModal.vue` | **新建** | 单次充值弹窗 |
| `frontend/src/components/RechargeBatchModal.vue` | **新建** | 批量充值弹窗 |
| `frontend/src/views/AdsAccountPanel.vue` | 修改 | 操作列加「💰」、工具栏加批量充值 |
| `frontend/src/views/SettingsPanel.vue` | 修改 | 充值表配置（仅管理员可见） |
| `frontend/src/components/AccountModal.vue` | 修改 | 死亡清账响应提醒 |

---

### Task 1: 数据库 — 新增 recharge_records 表

**Files:**
- Modify: `py/database.py`

**Interfaces:**
- Produces: `recharge_records` 表（id, account_id, amount, agent, operator, created_by, created_at）

- [ ] **Step 1: 在 `_ensure_schema()` 中添加建表语句**

在 `py/database.py` 的 `_ensure_schema()` 函数中，找到 CREATE TABLE 区域（约第 170 行，`account_mcc_history` 表之后），添加：

```python
# 增量迁移：recharge_records 表
conn.execute("""
    CREATE TABLE IF NOT EXISTS recharge_records (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        account_id TEXT NOT NULL,
        amount TEXT NOT NULL,
        agent TEXT DEFAULT '',
        operator TEXT DEFAULT '',
        created_by INTEGER REFERENCES users(id),
        created_at TEXT DEFAULT (datetime('now','localtime'))
    )
""")
conn.execute("CREATE INDEX IF NOT EXISTS idx_recharge_account ON recharge_records(account_id)")
```

- [ ] **Step 2: 验证**

启动服务器，确认 `recharge_records` 表已创建：

```bash
sqlite3 instance/gg.db ".schema recharge_records"
```

预期输出：CREATE TABLE 语句

- [ ] **Step 3: Commit**

```bash
git add py/database.py
git commit -m "feat: 新增 recharge_records 表"
```

---

### Task 2: Google Sheets — 新增 append_recharge 方法

**Files:**
- Modify: `py/google_sheets_service.py`

**Interfaces:**
- Produces: `append_recharge(service, spreadsheet_id, rows) -> dict`
  - `rows`: `[{"account_id", "amount", "agent", "operator"}, ...]`
  - Returns: `{"appended": int}`

- [ ] **Step 1: 实现 `append_recharge()` 函数**

在 `py/google_sheets_service.py` 文件末尾（`upsert_zuobiao` 函数之后）添加：

```python
def append_recharge(service, spreadsheet_id: str, rows: list) -> dict:
    """将充值记录追加到 Google Sheets「充值表」sheet。

    rows: [{"account_id": "123-456-7890", "amount": "1000",
            "agent": "卡尔", "operator": "张三"}, ...]

    A=账户ID, B=金额, C=代理, D=运营, E=留空, F=留空
    """
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

    sheet_name = target_sheet["name"]
    sheet_id_int = target_sheet["gid"]
    sheet_rows = target_sheet["rowCount"]

    # 2. 读取现有数据，找最后一行
    range_read = f"'{sheet_name}'!A:F"
    result = service.spreadsheets().values().get(
        spreadsheetId=spreadsheet_id, range=range_read,
    ).execute()
    existing = result.get("values", [])
    last_row = 0
    for i in range(len(existing) - 1, -1, -1):
        row = existing[i]
        if any(row[j] for j in range(min(4, len(row))) if row[j]):
            last_row = i + 1
            break

    # 3. 构建待写入行（A-F，E和F留空）
    new_rows = []
    for r in rows:
        new_rows.append([
            r.get("account_id", ""),
            str(r.get("amount", "")),
            r.get("agent", ""),
            r.get("operator", ""),
            "",  # E列 时间 留空
            "",  # F列 是否充值 留空
        ])

    # 4. 检查是否需要扩充行数
    start = last_row + 1
    end = last_row + len(new_rows)
    if end > sheet_rows:
        service.spreadsheets().batchUpdate(
            spreadsheetId=spreadsheet_id,
            body={"requests": [{
                "appendDimension": {
                    "sheetId": sheet_id_int,
                    "dimension": "ROWS",
                    "length": end - sheet_rows
                }
            }]}
        ).execute()

    # 5. 追加写入
    service.spreadsheets().values().update(
        spreadsheetId=spreadsheet_id,
        range=f"'{sheet_name}'!A{start}:F{end}",
        valueInputOption="USER_ENTERED",
        body={"values": new_rows},
    ).execute()

    log.info("充值记录已追加到 Google Sheets: %d 行", len(new_rows))
    return {"appended": len(new_rows)}
```

- [ ] **Step 2: 验证**

在 Python REPL 中手动测试（需要有效的 spreadsheet_id）：

```python
from py.google_sheets_service import build_service, append_recharge
service = build_service("credentials.json")
result = append_recharge(service, "your_spreadsheet_id", [
    {"account_id": "123-456-7890", "amount": "100", "agent": "测试", "operator": "测试员"}
])
print(result)  # {"appended": 1}
```

- [ ] **Step 3: Commit**

```bash
git add py/google_sheets_service.py
git commit -m "feat: 新增 append_recharge — 追加充值记录到 Google Sheets"
```

---

### Task 3: 后端 — Settings 扩展 + 充值 API 路由

**Files:**
- Modify: `py/main.py`

**Interfaces:**
- Consumes: `recharge_records` 表（Task 1）, `append_recharge()`（Task 2）
- Produces: `POST /api/recharge/submit`, `POST /api/recharge/batch-submit`, settings 含 `recharge_sheet_id`

- [ ] **Step 1: Settings GET 扩展 `recharge_sheet_id`**

找到 `account_settings_get()` 函数（约 4052 行），在 `keys` 列表中加入 `"recharge_sheet_id"`，默认值为 `""`：

```python
@app.route("/api/settings/account", methods=["GET"])
def account_settings_get():
    db = _yt_db()
    keys = ["account_statuses", "account_agents", "mcc_levels", "sales_persons", "recharge_sheet_id"]
    result = {}
    for k in keys:
        row = db.execute("SELECT value FROM tags WHERE key=?", (k,)).fetchone()
        if row:
            try:
                result[k] = _json.loads(row["value"])
            except Exception:
                result[k] = [] if k != "recharge_sheet_id" else ""
        else:
            defaults = {
                "account_statuses": ["存活", "死亡", "验证", "限额"],
                "account_agents": [],
                "mcc_levels": [],
                "sales_persons": [],
                "recharge_sheet_id": "",
            }
            result[k] = defaults.get(k, [] if k != "recharge_sheet_id" else "")
    db.close()
    return jsonify({"success": True, "settings": result})
```

- [ ] **Step 2: Settings POST 扩展 `recharge_sheet_id`**

找到 `account_settings_save()` 函数（约 4078 行），在 `keys` 循环中加入 `"recharge_sheet_id"`：

```python
@app.route("/api/settings/account", methods=["POST"])
def account_settings_save():
    data = request.get_json(silent=True) or {}
    db = _yt_db()
    for key in ["account_statuses", "account_agents", "mcc_levels", "sales_persons", "recharge_sheet_id"]:
        if key in data:
            val = data[key]
            # recharge_sheet_id 是字符串，其他是列表
            db.execute("INSERT OR REPLACE INTO tags(key,value) VALUES(?,?)",
                       (key, _json.dumps(val, ensure_ascii=False)))
    db.commit()
    db.close()
    return jsonify({"success": True})
```

- [ ] **Step 3: 新增 `POST /api/recharge/submit` 路由**

在 main.py 中找个合适位置（建议在 accounts batch-update 路由之后，约 3644 行），添加：

```python
@app.route("/api/recharge/submit", methods=["POST"])
@jwt_required()
def recharge_submit():
    """单次充值 — 写入 DB + Google Sheets"""
    data = request.get_json(silent=True) or {}
    user_id = int(get_jwt_identity())
    db = _yt_db()

    # 获取当前用户 display_name
    user = db.execute("SELECT display_name FROM users WHERE id=?", (user_id,)).fetchone()
    operator = (user["display_name"] or "") if user else ""

    account_id = (data.get("account_id") or "").strip()
    amount = str(data.get("amount", "")).strip()
    agent = (data.get("agent") or "").strip()

    if not account_id or not amount:
        db.close()
        return jsonify({"success": False, "error": "账户ID和金额不能为空"}), 400

    try:
        # 1. 写入数据库
        db.execute(
            "INSERT INTO recharge_records (account_id, amount, agent, operator, created_by) "
            "VALUES (?, ?, ?, ?, ?)",
            (account_id, amount, agent, operator, user_id)
        )
        db.commit()
        record_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]

        # 2. 异步追加到 Google Sheets
        sheets_warning = None
        try:
            sheet_id_row = db.execute(
                "SELECT value FROM tags WHERE key='recharge_sheet_id'"
            ).fetchone()
            if sheet_id_row:
                sheet_id = _json.loads(sheet_id_row["value"]) if sheet_id_row["value"] else ""
                if sheet_id:
                    credentials_path = os.environ.get("GOOGLE_SHEETS_CREDENTIALS", "")
                    if credentials_path and os.path.isfile(credentials_path):
                        from py import google_sheets_service as gs
                        service = gs.build_service(credentials_path)
                        gs.append_recharge(service, sheet_id, [{
                            "account_id": account_id,
                            "amount": amount,
                            "agent": agent,
                            "operator": operator,
                        }])
        except Exception as e:
            log.warning("充值记录已写入数据库，但 Google Sheets 同步失败: %s", e)
            sheets_warning = "数据库已保存，但 Google Sheets 同步失败，请手动检查"

        db.close()
        resp = {"success": True, "id": record_id}
        if sheets_warning:
            resp["warning"] = sheets_warning
        return jsonify(resp)
    except Exception as e:
        db.close()
        return jsonify({"success": False, "error": str(e)}), 500
```

- [ ] **Step 4: 新增 `POST /api/recharge/batch-submit` 路由**

紧接着添加：

```python
@app.route("/api/recharge/batch-submit", methods=["POST"])
@jwt_required()
def recharge_batch_submit():
    """批量充值 — 写入 DB + Google Sheets"""
    data = request.get_json(silent=True) or {}
    records = data.get("records", [])
    user_id = int(get_jwt_identity())
    db = _yt_db()

    if not records or not isinstance(records, list):
        db.close()
        return jsonify({"success": False, "error": "充值记录不能为空"}), 400

    user = db.execute("SELECT display_name FROM users WHERE id=?", (user_id,)).fetchone()
    operator = (user["display_name"] or "") if user else ""

    try:
        # 1. 批量写入数据库
        sheet_rows = []
        for r in records:
            account_id = (r.get("account_id") or "").strip()
            amount = str(r.get("amount", "")).strip()
            agent = (r.get("agent") or "").strip()
            if not account_id or not amount:
                continue
            db.execute(
                "INSERT INTO recharge_records (account_id, amount, agent, operator, created_by) "
                "VALUES (?, ?, ?, ?, ?)",
                (account_id, amount, agent, operator, user_id)
            )
            sheet_rows.append({
                "account_id": account_id,
                "amount": amount,
                "agent": agent,
                "operator": operator,
            })
        db.commit()

        # 2. 异步追加到 Google Sheets
        sheets_warning = None
        if sheet_rows:
            try:
                sheet_id_row = db.execute(
                    "SELECT value FROM tags WHERE key='recharge_sheet_id'"
                ).fetchone()
                if sheet_id_row:
                    sheet_id = _json.loads(sheet_id_row["value"]) if sheet_id_row["value"] else ""
                    if sheet_id:
                        credentials_path = os.environ.get("GOOGLE_SHEETS_CREDENTIALS", "")
                        if credentials_path and os.path.isfile(credentials_path):
                            from py import google_sheets_service as gs
                            service = gs.build_service(credentials_path)
                            gs.append_recharge(service, sheet_id, sheet_rows)
            except Exception as e:
                log.warning("批量充值 Google Sheets 同步失败: %s", e)
                sheets_warning = "数据库已保存，但 Google Sheets 同步失败，请手动检查"

        db.close()
        resp = {"success": True, "count": len(sheet_rows)}
        if sheets_warning:
            resp["warning"] = sheets_warning
        return jsonify(resp)
    except Exception as e:
        db.close()
        return jsonify({"success": False, "error": str(e)}), 500
```

- [ ] **Step 5: 死亡清账 — 修改 `accounts_update` 路由**

找到 `accounts_update()` 函数（约 3508 行），在 `db.commit()` 之前（约 3525 行），添加死亡清账逻辑。将整个 try 块改为：

```python
@app.route("/api/accounts/<int:aid>", methods=["PUT"])
@jwt_required()
def accounts_update(aid):
    data = request.get_json(silent=True) or {}
    db = _yt_db()
    try:
        user_id = int(get_jwt_identity())
        old_status = db.execute("SELECT status, agent, account_id FROM accounts WHERE id=?", (aid,)).fetchone()

        for f in ["name", "mcc_id", "timezone", "agent", "status", "acquired_date", "death_date"]:
            if f in data:
                val = data[f]
                if f == "mcc_id":
                    if val is None or val == 0 or val == "0" or (isinstance(val, str) and not val.strip()):
                        val = None
                    _record_mcc_change(db, aid, val, user_id, "manual")
                db.execute(f"UPDATE accounts SET {f}=?, updated_at=datetime('now','localtime') WHERE id=?",
                           (val, aid))

        # 死亡清账：状态变为「死亡」时自动追加 amount='清'
        recharge_note = None
        new_status = data.get("status", "")
        if new_status == "死亡" and (not old_status or old_status["status"] != "死亡"):
            existing_clear = db.execute(
                "SELECT id FROM recharge_records WHERE account_id=? AND amount='清'",
                (old_status["account_id"],)
            ).fetchone()
            if not existing_clear:
                user = db.execute("SELECT display_name FROM users WHERE id=?", (user_id,)).fetchone()
                operator_name = (user["display_name"] or "") if user else ""
                db.execute(
                    "INSERT INTO recharge_records (account_id, amount, agent, operator, created_by) "
                    "VALUES (?, '清', ?, ?, ?)",
                    (old_status["account_id"], data.get("agent", old_status["agent"] or ""),
                     operator_name, user_id)
                )
                recharge_note = "已追加清账记录"

        db.commit()

        resp = {"success": True}
        if recharge_note:
            resp["recharge_note"] = recharge_note
        return jsonify(resp)
    except _sqlite3.IntegrityError as e:
        # ... 保持原有错误处理不变
```

- [ ] **Step 6: 验证**

启动服务器，用 curl 测试：

```bash
# 测试单次充值
curl -X POST http://localhost:5000/api/recharge/submit \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{"account_id":"123-456-7890","amount":"1000","agent":"卡尔"}'

# 测试批量充值
curl -X POST http://localhost:5000/api/recharge/batch-submit \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{"records":[{"account_id":"123-456-7890","amount":"500","agent":"卡尔"}]}'

# 测试 settings 返回 recharge_sheet_id
curl http://localhost:5000/api/settings/account
```

- [ ] **Step 7: Commit**

```bash
git add py/main.py
git commit -m "feat: 充值 API + Settings 扩展 + 死亡清账"
```

---

### Task 4: 前端 — API 函数 + Store Actions

**Files:**
- Modify: `frontend/src/api/accounts.js`
- Modify: `frontend/src/stores/accounts.js`

**Interfaces:**
- Consumes: `POST /api/recharge/submit`, `POST /api/recharge/batch-submit`（Task 3）
- Produces: `rechargeApi.submit()`, `rechargeApi.batchSubmit()`, `store.rechargeSubmit()`, `store.rechargeBatchSubmit()`

- [ ] **Step 1: 在 `accounts.js` API 文件中新增充值函数**

在 `frontend/src/api/accounts.js` 的 `settingsApi` 之后添加：

```javascript
export const rechargeApi = {
  submit: (body) => api.post('/recharge/submit', body),
  batchSubmit: (body) => api.post('/recharge/batch-submit', body),
}
```

- [ ] **Step 2: 在 store 中新增充值 actions**

在 `frontend/src/stores/accounts.js` 中：

1. 顶部 import 加入 `rechargeApi`：
```javascript
import { accountsApi, mccApi, settingsApi, rechargeApi } from '@/api/accounts'
```

2. 在 actions 中添加：
```javascript
async rechargeSubmit(body) { return rechargeApi.submit(body) },
async rechargeBatchSubmit(body) { return rechargeApi.batchSubmit(body) },
```

- [ ] **Step 3: Commit**

```bash
git add frontend/src/api/accounts.js frontend/src/stores/accounts.js
git commit -m "feat: 前端充值 API + Store actions"
```

---

### Task 5: 前端 — RechargeModal.vue（单次充值弹窗）

**Files:**
- Create: `frontend/src/components/RechargeModal.vue`

**Interfaces:**
- Consumes: `store.rechargeSubmit()`（Task 4）, `store.accounts` 列表, `authStore.user.display_name`
- Produces: `v-model:visible`, prop `defaultAccountId`, emit `saved`

- [ ] **Step 1: 创建组件**

```vue
<template>
  <el-dialog :model-value="visible" @update:model-value="$emit('update:visible', $event)"
    title="💰 充值" width="450px" @open="init">
    <el-form label-position="top">
      <el-form-item label="账户ID" required>
        <el-select v-model="form.account_id" filterable placeholder="搜索账户ID..."
          style="width:100%;" @change="onAccountChange">
          <el-option v-for="ac in accountOptions" :key="ac.account_id"
            :label="ac.account_id + ' (' + ac.name + ')'" :value="ac.account_id" />
        </el-select>
      </el-form-item>
      <el-form-item label="代理">
        <el-input :model-value="form.agent" disabled />
      </el-form-item>
      <el-form-item label="运营">
        <el-input :model-value="operator" disabled />
      </el-form-item>
      <el-form-item label="金额" required>
        <el-input v-model="form.amount" placeholder="输入充值金额" />
      </el-form-item>
    </el-form>
    <template #footer>
      <el-button @click="$emit('update:visible', false)">取消</el-button>
      <el-button type="primary" @click="submit" :loading="saving">💰 确认充值</el-button>
    </template>
  </el-dialog>
</template>

<script setup>
import { ref, reactive, computed, watch } from 'vue'
import { useAccountStore } from '@/stores/accounts'
import { useAuthStore } from '@/stores/auth'
import { ElMessage } from 'element-plus'

const props = defineProps({
  visible: Boolean,
  defaultAccountId: { type: String, default: '' },
})
const emit = defineEmits(['update:visible', 'saved'])

const store = useAccountStore()
const authStore = useAuthStore()
const saving = ref(false)

const accountOptions = computed(() => store.accounts || [])

const operator = computed(() => authStore.user?.display_name || '')

const form = reactive({
  account_id: '',
  agent: '',
  amount: '',
})

function init() {
  form.account_id = props.defaultAccountId || ''
  form.amount = ''
  onAccountChange(props.defaultAccountId || '')
}

function onAccountChange(accountId) {
  const ac = store.accounts.find(a => a.account_id === accountId)
  form.agent = ac ? (ac.agent || '') : ''
}

async function submit() {
  if (!form.account_id || !form.amount) {
    ElMessage.warning('账户ID和金额不能为空')
    return
  }
  saving.value = true
  try {
    const res = await store.rechargeSubmit({
      account_id: form.account_id,
      amount: form.amount,
      agent: form.agent,
    })
    if (res.warning) ElMessage.warning(res.warning)
    else ElMessage.success('充值记录已提交')
    emit('update:visible', false)
    emit('saved')
  } catch (e) {
    ElMessage.error(e.response?.data?.error || '充值失败')
  }
  saving.value = false
}
</script>
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/components/RechargeModal.vue
git commit -m "feat: 单次充值弹窗 RechargeModal"
```

---

### Task 6: 前端 — RechargeBatchModal.vue（批量充值弹窗）

**Files:**
- Create: `frontend/src/components/RechargeBatchModal.vue`

**Interfaces:**
- Consumes: `store.rechargeBatchSubmit()`（Task 4）, `selectedAccounts` prop, `authStore.user.display_name`
- Produces: `v-model:visible`, prop `accounts`, emit `saved`

- [ ] **Step 1: 创建组件**

```vue
<template>
  <el-dialog :model-value="visible" @update:model-value="$emit('update:visible', $event)"
    title="💰 批量充值" width="600px" @open="init">
    <div style="display:flex;gap:8px;margin-bottom:12px;align-items:center;">
      <span style="white-space:nowrap;">统一金额:</span>
      <el-input v-model="unifiedAmount" placeholder="输入金额" style="width:150px;" size="small" />
      <el-button size="small" @click="applyUnified" :disabled="!unifiedAmount">📝 应用</el-button>
    </div>
    <el-table :data="rows" size="small" border stripe max-height="400">
      <el-table-column prop="account_id" label="账户ID" width="160" />
      <el-table-column prop="agent" label="代理" width="100" />
      <el-table-column label="金额" min-width="150">
        <template #default="{ row, $index }">
          <el-input v-model="row.amount" placeholder="输入金额" size="small" />
        </template>
      </el-table-column>
    </el-table>
    <template #footer>
      <el-button @click="$emit('update:visible', false)">取消</el-button>
      <el-button type="primary" @click="submit" :loading="saving">
        💰 确认批量充值 ({{ rows.length }})
      </el-button>
    </template>
  </el-dialog>
</template>

<script setup>
import { ref, reactive, watch } from 'vue'
import { useAccountStore } from '@/stores/accounts'
import { useAuthStore } from '@/stores/auth'
import { ElMessage } from 'element-plus'

const props = defineProps({
  visible: Boolean,
  accounts: { type: Array, default: () => [] },
})
const emit = defineEmits(['update:visible', 'saved'])

const store = useAccountStore()
const authStore = useAuthStore()
const saving = ref(false)
const unifiedAmount = ref('')
const rows = ref([])

function init() {
  rows.value = props.accounts.map(a => ({
    account_id: a.account_id,
    agent: a.agent || '',
    amount: '',
  }))
  unifiedAmount.value = ''
}

function applyUnified() {
  if (!unifiedAmount.value) return
  rows.value.forEach(r => { r.amount = unifiedAmount.value })
}

async function submit() {
  const records = rows.value.filter(r => r.amount)
  if (!records.length) {
    ElMessage.warning('请至少填写一个金额')
    return
  }
  saving.value = true
  try {
    const res = await store.rechargeBatchSubmit({ records })
    if (res.warning) ElMessage.warning(res.warning)
    else ElMessage.success(`已提交 ${res.count} 条充值记录`)
    emit('update:visible', false)
    emit('saved')
  } catch (e) {
    ElMessage.error(e.response?.data?.error || '批量充值失败')
  }
  saving.value = false
}
</script>
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/components/RechargeBatchModal.vue
git commit -m "feat: 批量充值弹窗 RechargeBatchModal"
```

---

### Task 7: 前端 — AdsAccountPanel.vue 加充值入口

**Files:**
- Modify: `frontend/src/views/AdsAccountPanel.vue`

**Interfaces:**
- Consumes: `RechargeModal`（Task 5）, `RechargeBatchModal`（Task 6）
- Produces: 操作列「💰」按钮, 工具栏「💰 批量充值」按钮

- [ ] **Step 1: 操作列新增单次充值按钮**

在操作列的 `<el-table-column label="操作" width="160">` 中，删除按钮 `<el-button link type="danger">` 之前添加：

```html
<el-button link type="warning" size="small" @click="openRecharge(row)">💰</el-button>
```

操作列调整宽度为 `width="200"`（因为多了按钮）。

- [ ] **Step 2: 工具栏新增批量充值按钮**

在 `[🔍 批量查户]` 按钮之后、`已选 N 条` 之前添加：

```html
<el-button @click="batchRechargeVisible = true" :disabled="!selected.length">💰 批量充值</el-button>
```

- [ ] **Step 3: 在模板底部添加弹窗组件**

在 `AccountDetailModal` 之后添加：

```html
<RechargeModal v-model:visible="rechargeVisible" :default-account-id="rechargeAccountId" @saved="load" />
<RechargeBatchModal v-model:visible="batchRechargeVisible" :accounts="selected" @saved="onBatchRecharged" />
```

- [ ] **Step 4: 在 script 中导入组件和添加响应式变量**

```javascript
import RechargeModal from '@/components/RechargeModal.vue'
import RechargeBatchModal from '@/components/RechargeBatchModal.vue'

// 在现有 ref 声明附近添加：
const rechargeVisible = ref(false)
const rechargeAccountId = ref('')
const batchRechargeVisible = ref(false)
```

- [ ] **Step 5: 添加处理函数**

```javascript
function openRecharge(row) {
  rechargeAccountId.value = row.account_id
  rechargeVisible.value = true
}

function onBatchRecharged() {
  // 清空勾选
  selected.value = []
  load()
}
```

- [ ] **Step 6: Commit**

```bash
git add frontend/src/views/AdsAccountPanel.vue
git commit -m "feat: AdsAccountPanel 加充值按钮入口"
```

---

### Task 8: 前端 — SettingsPanel.vue 充值表配置

**Files:**
- Modify: `frontend/src/views/SettingsPanel.vue`

**Interfaces:**
- Consumes: `authStore.isAdmin` / `authStore.isDeveloper`, `store.settings.recharge_sheet_id`
- Produces: 充值表配置 UI（仅管理员可见）

- [ ] **Step 1: 在「账户设置」Tab 底部添加充值表配置**

在「账户设置」Tab 的保存按钮之前（`<el-button type="primary" @click="save">` 之前），添加：

```html
<template v-if="authStore.isAdmin || authStore.isDeveloper">
  <el-divider />
  <h4 style="margin-bottom:8px;">📊 充值表配置（仅管理员可见）</h4>
  <el-form-item label="Google Sheets ID">
    <el-input v-model="form.recharge_sheet_id" placeholder="输入充值表的 spreadsheet ID" />
  </el-form-item>
</template>
```

- [ ] **Step 2: script 中导入 authStore**

在 import 区域已有的基础上确保有：

```javascript
import { useAuthStore } from '@/stores/auth'
```

在 setup 中已有的 `const store = useAccountStore()` 之后添加：

```javascript
const authStore = useAuthStore()
```

- [ ] **Step 3: form reactive 中加入 `recharge_sheet_id`**

```javascript
const form = reactive({
  account_statuses: '',
  account_agents: '',
  mcc_levels: '',
  sales_persons: '',
  recharge_sheet_id: '',
})
```

- [ ] **Step 4: `onMounted` 中初始化 `recharge_sheet_id`**

```javascript
form.recharge_sheet_id = store.settings.recharge_sheet_id || ''
```

- [ ] **Step 5: `save` 函数中加入 `recharge_sheet_id`**

```javascript
async function save() {
  saving.value = true
  const body = {
    account_statuses: form.account_statuses.split('\n').map(s => s.trim()).filter(Boolean),
    account_agents: form.account_agents.split('\n').map(s => s.trim()).filter(Boolean),
    mcc_levels: form.mcc_levels.split('\n').map(s => s.trim()).filter(Boolean),
    sales_persons: form.sales_persons.split('\n').map(s => s.trim()).filter(Boolean),
    recharge_sheet_id: form.recharge_sheet_id.trim(),
  }
  await store.saveSettings(body)
  store.settings = body
  msg.value = '✅ 已保存'
  setTimeout(() => msg.value = '', 2000)
  saving.value = false
}
```

- [ ] **Step 6: Commit**

```bash
git add frontend/src/views/SettingsPanel.vue
git commit -m "feat: SettingsPanel 充值表配置（仅管理员可见）"
```

---

### Task 9: 前端 — AccountModal.vue 死亡清账提醒

**Files:**
- Modify: `frontend/src/components/AccountModal.vue`

**Interfaces:**
- Consumes: `PUT /api/accounts/<id>` 响应中的 `recharge_note` 字段（Task 3 Step 5）

- [ ] **Step 1: 在 submit 成功分支处理 recharge_note**

找到 `AccountModal.vue` 的 `submit()` 函数中 `else if (props.editId)` 分支（约 187 行），修改为：

```javascript
} else if (props.editId) {
  const res = await store.updateAccount(props.editId, form)
  if (res.recharge_note === '已追加清账记录') {
    ElMessage.success('该账户已自动追加清账记录')
  }
}
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/components/AccountModal.vue
git commit -m "feat: AccountModal 死亡清账提醒"
```

---

## 验证清单

全部实现完成后，端到端验证：

1. 【充值表配置】SettingsPanel → 管理员可见充值表 ID 输入框，保存后刷新仍保留
2. 【单次充值】AdsAccountPanel → 点击操作列 💰 → 弹窗默认填入账户ID/代理，填金额提交 → 数据库有记录
3. 【批量充值】勾选 3 个账户 → 批量充值 → 统一金额填充 → 提交 → 3 条记录写入
4. 【死亡清账】编辑账户状态为「死亡」→ 弹窗提示「已自动追加清账记录」→ `recharge_records` 有 amount='清' 记录
5. 【死亡去重】同一账户再次改为死亡 → 不会重复追加「清」记录
6. 【Sheets 同步】配置有效的 spreadsheet ID 后，充值记录自动追加到「充值表」sheet
