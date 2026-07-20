# 广告账户 MCC 变更历史 — 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为广告账户新增 MCC 变更历史功能，自动记录每次 MCC 归属变更并在详情弹窗中以时间线展示。

**Architecture:** 后端新增 `account_mcc_history` 表 + 辅助函数 + 2 个 API；5 处账户操作埋点自动写入历史。前端新建 `AccountDetailModal.vue` 详情弹窗，在 `AdsAccountPanel.vue` 增加入口按钮。

**Tech Stack:** Python Flask + SQLite (后端), Vue 3 + Element Plus + Pinia (前端)

## Global Constraints

- 纯增量原则：不修改已有业务逻辑代码，只在函数末尾追加历史记录调用
- `AccountModal.vue`、`AccountBatchImportModal.vue` 等已有组件不做任何修改
- `AdsAccountPanel.vue` 只在操作列增加一个按钮
- 单账户历史记录量小（几十条以内），无需分页
- 历史记录硬删除，删除账户时级联删除关联历史

---

## File Structure

| 文件 | 操作 | 职责 |
|------|------|------|
| `py/database.py` | 修改 | 新增 `account_mcc_history` 表定义 + 增量迁移 |
| `py/main.py` | 修改 | 新增辅助函数、2 个 API、5 处埋点调用 |
| `frontend/src/api/accounts.js` | 修改 | 新增 `history()` / `deleteHistory()` API 方法 |
| `frontend/src/components/AccountDetailModal.vue` | **新建** | 账户详情只读展示 + MCC 历史时间线 |
| `frontend/src/views/AdsAccountPanel.vue` | 修改 | 操作列增加"详情"按钮 |

---

### Task 1: 数据库 — 新增 account_mcc_history 表

**Files:**
- Modify: `py/database.py`

**Interfaces:**
- Produces: `account_mcc_history` 表 (id, account_id, old_mcc_id, new_mcc_id, changed_by, change_type, created_at) + 两个索引

- [ ] **Step 1: 在 `_ensure_schema()` 中添加建表 SQL**

找到 `py/database.py` 中 `accounts` 表的 `CREATE TABLE IF NOT EXISTS accounts` 定义（约第 141-153 行），在其后面新增 account_mcc_history 建表语句。

定位方式：搜索 `CREATE TABLE IF NOT EXISTS accounts`，在 `);` 闭合后、下一个注释块之前插入。

```sql
        -- 账户 MCC 变更历史
        CREATE TABLE IF NOT EXISTS account_mcc_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            account_id INTEGER NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
            old_mcc_id INTEGER,
            new_mcc_id INTEGER,
            changed_by INTEGER REFERENCES users(id),
            change_type TEXT NOT NULL DEFAULT 'manual',
            created_at TEXT DEFAULT (datetime('now','localtime'))
        );
        CREATE INDEX IF NOT EXISTS idx_acmh_account ON account_mcc_history(account_id);
        CREATE INDEX IF NOT EXISTS idx_acmh_changed_by ON account_mcc_history(changed_by);
```

**插入位置说明：** 在 `accounts` 表的 `CREATE TABLE` 语句结束后（约第 153 行之后），与下面 `copywritings` 表定义之间。具体位置在 `accounts` 表的 `);` 闭合行和 `-- 文案管理` 注释之间。

- [ ] **Step 2: 验证数据库迁移**

启动后端服务，确认表自动创建：

```bash
cd d:/server/cc/GG-Server
python -c "import sys; sys.path.insert(0,'py'); import database; db=database.get_db(); print([r[1] for r in db.execute(\"SELECT name FROM sqlite_master WHERE type='table' AND name='account_mcc_history'\").fetchall()])"
```

预期输出：`['account_mcc_history']`

- [ ] **Step 3: 提交**

```bash
git add py/database.py
git commit -m "feat: 新增 account_mcc_history 表用于记录账户 MCC 变更历史"
```

---

### Task 2: 后端 — 辅助函数 + API 路由 + 埋点

**Files:**
- Modify: `py/main.py`

**Interfaces:**
- Consumes: `account_mcc_history` 表 (Task 1)
- Produces:
  - `_record_mcc_change(db, account_id, new_mcc_id, changed_by, change_type)` — 辅助函数
  - `GET /api/accounts/<aid>/mcc-history` — 查询历史
  - `DELETE /api/accounts/<aid>/mcc-history/<hid>` — 删除单条历史

- [ ] **Step 1: 添加辅助函数 `_record_mcc_change`**

在 `_yt_db()` 函数附近（约第 1295 行之后）添加辅助函数：

```python
def _record_mcc_change(db, account_id, new_mcc_id, changed_by, change_type):
    """检测 mcc_id 变更并写入历史记录。值未变化则不写入。"""
    old = db.execute("SELECT mcc_id FROM accounts WHERE id=?", (account_id,)).fetchone()
    if not old:
        return
    old_mcc_id = old["mcc_id"]
    # 标准化空值
    if old_mcc_id == 0 or old_mcc_id == "0" or (isinstance(old_mcc_id, str) and not old_mcc_id.strip()):
        old_mcc_id = None
    if new_mcc_id == 0 or new_mcc_id == "0" or (isinstance(new_mcc_id, str) and not new_mcc_id.strip()):
        new_mcc_id = None
    if new_mcc_id is None and old_mcc_id is None:
        return
    if old_mcc_id == new_mcc_id:
        return
    db.execute(
        "INSERT INTO account_mcc_history(account_id, old_mcc_id, new_mcc_id, changed_by, change_type) "
        "VALUES(?,?,?,?,?)",
        (account_id, old_mcc_id, new_mcc_id, changed_by, change_type)
    )
```

- [ ] **Step 2: 添加 GET 查询接口**

在 batch-update 函数之后、MCC API 注释之前（约第 3409 行）插入：

```python
@app.route("/api/accounts/<int:aid>/mcc-history", methods=["GET"])
@jwt_required()
def accounts_mcc_history(aid):
    """获取账户的 MCC 变更历史"""
    db = _yt_db()
    try:
        rows = db.execute(
            "SELECT h.*, "
            "  om.name AS old_mcc_name, om.mcc_id AS old_mcc_code, "
            "  nm.name AS new_mcc_name, nm.mcc_id AS new_mcc_code, "
            "  u.username, u.display_name "
            "FROM account_mcc_history h "
            "LEFT JOIN mcc om ON h.old_mcc_id = om.id "
            "LEFT JOIN mcc nm ON h.new_mcc_id = nm.id "
            "LEFT JOIN users u ON h.changed_by = u.id "
            "WHERE h.account_id = ? "
            "ORDER BY h.created_at DESC",
            (aid,)
        ).fetchall()
        history = []
        type_labels = {
            "manual": "手动编辑", "batch": "批量修改", "reassign": "认领转移",
            "import": "批量导入", "create": "新建账户",
        }
        for r in rows:
            r = dict(r)
            r["changed_by_name"] = r.get("display_name") or r.get("username") or f"User#{r.get('changed_by','')}"
            r["change_type_label"] = type_labels.get(r.get("change_type", ""), r.get("change_type", ""))
            history.append(r)
        db.close()
        return jsonify({"success": True, "history": history})
    except Exception as e:
        db.close()
        return jsonify({"success": False, "error": str(e)}), 500
```

- [ ] **Step 3: 添加 DELETE 删除接口**

在 GET 接口后继续插入：

```python
@app.route("/api/accounts/<int:aid>/mcc-history/<int:hid>", methods=["DELETE"])
@jwt_required()
def accounts_mcc_history_delete(aid, hid):
    """删除单条 MCC 历史记录（admin/developer）"""
    user_id = int(get_jwt_identity())
    user = auth.get_user_by_id(user_id)
    if not user or user["role"] not in ("developer", "admin"):
        return jsonify({"success": False, "error": "权限不足"}), 403
    db = _yt_db()
    try:
        db.execute(
            "DELETE FROM account_mcc_history WHERE id=? AND account_id=?",
            (hid, aid)
        )
        db.commit()
        db.close()
        return jsonify({"success": True})
    except Exception as e:
        db.close()
        return jsonify({"success": False, "error": str(e)}), 500
```

- [ ] **Step 4: 埋点 1 — `accounts_create()`**

在 `accounts_create()` 函数中，`db.commit()` 之后、`new_id = ...` 之后，`db.close()` 之前（约第 3152-3153 行之间），插入：

```python
        # 记录 MCC 变更历史（首次分配）
        mcc_val = data.get("mcc_id") or None
        if mcc_val:
            _record_mcc_change(db, new_id, mcc_val, user_id, "create")
```

**插入位置：** 在 `new_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]` 之后、`db.close()` 之前。

- [ ] **Step 5: 埋点 2 — `accounts_update()`**

在 `accounts_update()` 函数中，循环更新字段的代码中，`mcc_id` 处理分支内。在当前代码更新完 `mcc_id` 后立即记录历史。

现有代码（约第 3277-3286 行）：
```python
        for f in ["name", "mcc_id", "timezone", "agent", "status", "acquired_date", "death_date"]:
            if f in data:
                val = data[f]
                if f == "mcc_id":
                    if val is None or val == 0 or val == "0" or (isinstance(val, str) and not val.strip()):
                        val = None
                db.execute(f"UPDATE accounts SET {f}=?, updated_at=datetime('now','localtime') WHERE id=?",
                           (val, aid))
        db.commit()
```

修改为：
```python
        user_id = int(get_jwt_identity())
        for f in ["name", "mcc_id", "timezone", "agent", "status", "acquired_date", "death_date"]:
            if f in data:
                val = data[f]
                if f == "mcc_id":
                    if val is None or val == 0 or val == "0" or (isinstance(val, str) and not val.strip()):
                        val = None
                    # 记录 MCC 变更历史
                    _record_mcc_change(db, aid, val, user_id, "manual")
                db.execute(f"UPDATE accounts SET {f}=?, updated_at=datetime('now','localtime') WHERE id=?",
                           (val, aid))
        db.commit()
```

**改动说明：** 在原有 for 循环开头新增 `user_id = int(get_jwt_identity())`；在 `if f == "mcc_id"` 分支的值标准化之后、`db.execute` 之前增加一行 `_record_mcc_change(...)` 调用。原有业务逻辑不变。

- [ ] **Step 6: 埋点 3 — `accounts_reassign()`**

在 `accounts_reassign()` 函数中，MCC 更新代码块之后（约第 3341-3342 行），`db.commit()` 之前，插入：

```python
        # 记录 MCC 变更历史
        if "mcc_id" in data:
            mcc_val = data["mcc_id"]
            if mcc_val is None or mcc_val == 0 or mcc_val == "0" or (isinstance(mcc_val, str) and not mcc_val.strip()):
                mcc_val = None
            _record_mcc_change(db, aid, mcc_val, user_id, "reassign")
```

- [ ] **Step 7: 埋点 4 — `accounts_batch_update()`**

在 `accounts_batch_update()` 函数中，循环内 `db.execute(...)` 之前（约第 3402-3403 行），当 `field == "mcc_id"` 时为每条记录写入历史：

现有代码：
```python
        for aid in ids:
            db.execute(f"UPDATE accounts SET {field}=?, updated_at=datetime('now','localtime') WHERE id=?",
                       (value, aid))
        db.commit()
```

修改为：
```python
        user_id = int(get_jwt_identity())
        for aid in ids:
            if field == "mcc_id":
                _record_mcc_change(db, aid, value, user_id, "batch")
            db.execute(f"UPDATE accounts SET {field}=?, updated_at=datetime('now','localtime') WHERE id=?",
                       (value, aid))
        db.commit()
```

- [ ] **Step 8: 埋点 5 — `accounts_batch_create()`**

在 `accounts_batch_create()` 函数中，`db.execute(...)` INSERT 成功之后、`db.commit()` 和 `created.append(aid)` 之后（约第 3243-3245 行），插入：

```python
            # 记录 MCC 变更历史
            if mcc_id:
                new_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]
                _record_mcc_change(db, new_id, mcc_id, user_id, "import")
```

**插入位置：** 在 `created.append(aid)` 之后（仍在 try 块内）。

- [ ] **Step 9: 验证后端 API**

启动后端服务，用 curl 测试：

```bash
# 测试 GET（替换 <aid> 为真实账户 ID）
curl -H "Authorization: Bearer <token>" http://localhost:5000/api/accounts/<aid>/mcc-history

# 测试 DELETE
curl -X DELETE -H "Authorization: Bearer <token>" http://localhost:5000/api/accounts/<aid>/mcc-history/1
```

预期：GET 返回 `{"success": true, "history": [...]}`；DELETE 返回 `{"success": true}`。

- [ ] **Step 10: 提交**

```bash
git add py/main.py
git commit -m "feat: 后端 MCC 变更历史 API + 5 处自动埋点"
```

---

### Task 3: 前端 API 层 — 新增历史查询/删除方法

**Files:**
- Modify: `frontend/src/api/accounts.js`

**Interfaces:**
- Produces: `accountsApi.history(aid)` → `Promise`, `accountsApi.deleteHistory(aid, hid)` → `Promise`

- [ ] **Step 1: 在 accountsApi 对象中添加两个方法**

在 `frontend/src/api/accounts.js` 的 `accountsApi` 对象中，`reassign` 行之后添加：

```js
  history: (aid) => api.get(`/accounts/${aid}/mcc-history`),
  deleteHistory: (aid, hid) => api.delete(`/accounts/${aid}/mcc-history/${hid}`),
```

插入位置：`reassign` 行（第 13 行）之后，`};` 闭合之前。

- [ ] **Step 2: 构建前端确保无误**

```bash
cd d:/server/cc/GG-Server/frontend && npx vite build --mode development 2>&1 | tail -5
```

预期：构建成功无报错。

- [ ] **Step 3: 提交**

```bash
git add frontend/src/api/accounts.js
git commit -m "feat: 前端 accountsApi 新增 history / deleteHistory 方法"
```

---

### Task 4: 前端 — 新建 AccountDetailModal 组件

**Files:**
- Create: `frontend/src/components/AccountDetailModal.vue`

**Interfaces:**
- Consumes: `accountsApi.history(aid)` / `accountsApi.deleteHistory(aid, hid)` (Task 3)
- Produces: `<AccountDetailModal>` 组件，props: `visible: Boolean`, `accountId: [Number, null]`，emits: `update:visible`

- [ ] **Step 1: 创建组件文件**

新建 `frontend/src/components/AccountDetailModal.vue`，完整内容如下：

```vue
<template>
  <el-dialog :model-value="visible" @update:model-value="$emit('update:visible', $event)"
    title="📋 账户详情" width="650px" @open="load">
    <div v-if="account" style="font-size:13px;">
      <!-- 基本信息 -->
      <div style="display:grid;grid-template-columns:1fr 1fr;gap:8px 16px;margin-bottom:16px;">
        <div><strong>账户名称：</strong>{{ account.name }}</div>
        <div><strong>账户 ID：</strong>{{ account.account_id }}</div>
        <div>
          <strong>当前 MCC：</strong>
          <template v-if="account.mcc_name">
            <span style="color:#0891b2;">{{ account.mcc_name }}</span>
            <span style="font-size:10px;color:#0891b2;"> ({{ account.mcc_code }})</span>
          </template>
          <span v-else style="color:#888;">未分配</span>
        </div>
        <div><strong>时区：</strong>{{ account.timezone || '-' }}</div>
        <div><strong>代理：</strong>{{ account.agent || '-' }}</div>
        <div>
          <strong>状态：</strong>
          <el-tag size="small" :type="statusTagType(account.status)">{{ account.status || '未知' }}</el-tag>
        </div>
        <div><strong>到手时间：</strong>{{ account.acquired_date || '-' }}</div>
        <div v-if="account.death_date"><strong>死亡时间：</strong><span style="color:#dc2626;">{{ account.death_date }}</span></div>
      </div>

      <el-divider />

      <!-- MCC 变更历史 -->
      <h4>🕓 MCC 变更历史（{{ history.length }} 条）</h4>
      <el-timeline v-if="history.length" style="margin-top:12px;">
        <el-timeline-item
          v-for="h in history"
          :key="h.id"
          :timestamp="h.created_at"
          placement="top"
        >
          <div style="display:flex;align-items:flex-start;justify-content:space-between;">
            <div>
              <span style="color:#666;">{{ h.changed_by_name }}</span>
              <el-tag size="small" type="info" style="margin-left:6px;">{{ h.change_type_label }}</el-tag>
              <div style="margin-top:2px;">
                <template v-if="h.old_mcc_name">
                  <span style="color:#dc2626;">{{ h.old_mcc_name }} ({{ h.old_mcc_code }})</span>
                </template>
                <template v-else>
                  <span style="color:#999;">(未分配)</span>
                </template>
                <span style="margin:0 4px;color:#666;">→</span>
                <template v-if="h.new_mcc_name">
                  <span style="color:#16a34a;">{{ h.new_mcc_name }} ({{ h.new_mcc_code }})</span>
                </template>
                <template v-else>
                  <span style="color:#999;">(未分配)</span>
                </template>
              </div>
            </div>
            <el-button
              link
              type="danger"
              size="small"
              @click="deleteHistory(h.id)"
              :loading="deleting === h.id"
              style="flex-shrink:0;opacity:0.5;"
              @mouseenter="$event.target.style.opacity=1"
              @mouseleave="$event.target.style.opacity=0.5"
            >✕</el-button>
          </div>
        </el-timeline-item>
      </el-timeline>
      <el-empty v-else description="暂无 MCC 变更记录" :image-size="50" />
    </div>
    <el-empty v-else description="加载中..." :image-size="50" />

    <template #footer>
      <el-button @click="$emit('update:visible', false)">关闭</el-button>
    </template>
  </el-dialog>
</template>

<script setup>
import { ref } from 'vue'
import { accountsApi } from '@/api/accounts'
import { ElMessage, ElMessageBox } from 'element-plus'

const props = defineProps({ visible: Boolean, accountId: [Number, null] })
const emit = defineEmits(['update:visible'])

const account = ref(null)
const history = ref([])
const deleting = ref(null)

function statusTagType(status) {
  const map = { '存活': 'success', '验证': 'warning', '死亡': 'danger' }
  return map[status] || 'info'
}

async function load() {
  account.value = null
  history.value = []
  if (!props.accountId) return
  try {
    // 从 accounts store 中查找账户基本信息
    const { useAccountStore } = await import('@/stores/accounts')
    const store = useAccountStore()
    const found = store.accounts.find(a => a.id === props.accountId)
    if (found) {
      account.value = { ...found }
    }
    // 加载历史
    const res = await accountsApi.history(props.accountId)
    history.value = res.history || []
  } catch (e) {
    ElMessage.error('加载失败: ' + (e.response?.data?.error || e.message))
  }
}

async function deleteHistory(hid) {
  try {
    await ElMessageBox.confirm('确定删除这条 MCC 变更记录？', '确认删除', {
      type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消',
    })
  } catch { return }

  deleting.value = hid
  try {
    await accountsApi.deleteHistory(props.accountId, hid)
    history.value = history.value.filter(h => h.id !== hid)
    ElMessage.success('已删除')
  } catch (e) {
    ElMessage.error('删除失败: ' + (e.response?.data?.error || e.message))
  } finally {
    deleting.value = null
  }
}
</script>
```

- [ ] **Step 2: 构建前端确保无误**

```bash
cd d:/server/cc/GG-Server/frontend && npx vite build --mode development 2>&1 | tail -5
```

预期：构建成功。

- [ ] **Step 3: 提交**

```bash
git add frontend/src/components/AccountDetailModal.vue
git commit -m "feat: 新建 AccountDetailModal — 账户详情 + MCC 历史时间线"
```

---

### Task 5: 前端 — AdsAccountPanel 入口按钮

**Files:**
- Modify: `frontend/src/views/AdsAccountPanel.vue`

**Interfaces:**
- Consumes: `AccountDetailModal` 组件 (Task 4)
- Produces: 操作列新增"详情"按钮，点击打开详情弹窗

- [ ] **Step 1: 在操作列增加"详情"按钮 + 引入组件**

**a) 模板中操作列（约第 70-75 行），在编辑按钮之前增加"详情"按钮：**

现有代码：
```html
        <el-table-column label="操作" width="120">
          <template #default="{ row }">
            <el-button link type="primary" size="small" @click="showModal(row.id)">✏️</el-button>
            <el-button link type="danger" size="small" @click="del(row.id)"><el-icon :size="14"><Delete /></el-icon></el-button>
          </template>
        </el-table-column>
```

修改为：
```html
        <el-table-column label="操作" width="160">
          <template #default="{ row }">
            <el-button link type="primary" size="small" @click="showModal(row.id)">✏️</el-button>
            <el-button link type="success" size="small" @click="showDetail(row.id)">📋</el-button>
            <el-button link type="danger" size="small" @click="del(row.id)"><el-icon :size="14"><Delete /></el-icon></el-button>
          </template>
        </el-table-column>
```

**b) 模板底部（`</template>` 之前，约第 91 行 `</div>` 之后），增加详情弹窗组件：**

```html
    <AccountDetailModal v-model:visible="detailVisible" :account-id="detailAccountId" />
```

**c) script 中（约第 96-100 行），新增 import：**

```js
import AccountDetailModal from '@/components/AccountDetailModal.vue'
```

**d) script 中（约第 105-108 行），新增响应式变量和方法：**

在 `const lookupVisible = ref(false)` 之后添加：
```js
const detailVisible = ref(false)
const detailAccountId = ref(null)
```

添加方法 `showDetail`（放在 `showModal` 函数附近）：
```js
function showDetail(id) { detailAccountId.value = id; detailVisible.value = true }
```

- [ ] **Step 2: 构建前端验证**

```bash
cd d:/server/cc/GG-Server/frontend && npx vite build --mode development 2>&1 | tail -5
```

预期：构建成功无报错。

- [ ] **Step 3: 端到端验证**

启动服务后，在浏览器中：
1. 进入广告账户页面
2. 点击某个账户的"📋"详情按钮 → 弹出详情弹窗，显示账户信息和 MCC 历史
3. 编辑该账户，修改 MCC → 再次查看详情，新记录出现
4. 点击历史记录的 ✕ 按钮 → 确认删除 → 记录消失

- [ ] **Step 4: 提交**

```bash
git add frontend/src/views/AdsAccountPanel.vue
git commit -m "feat: AdsAccountPanel 操作列新增账户详情入口按钮"
```

---

## 验证清单（全部 Task 完成后）

- [ ] 新建账户（带 MCC）→ 详情弹窗显示一条 `create` 类型历史
- [ ] 编辑账户改 MCC → 新增 `manual` 类型历史，旧→新对比正确
- [ ] 批量修改 MCC → 每条变更各生成 `batch` 类型历史
- [ ] 认领转移（含 MCC 变更）→ 生成 `reassign` 类型历史
- [ ] 批量导入 → 导入的账户生成 `import` 类型历史
- [ ] MCC 未变化（编辑其他字段）→ 不产生新历史记录
- [ ] 删除历史记录 → 确认弹窗后记录消失
- [ ] 删除账户 → 关联历史记录级联删除
- [ ] 已有的编辑/批量更新/认领/导入功能不受影响
