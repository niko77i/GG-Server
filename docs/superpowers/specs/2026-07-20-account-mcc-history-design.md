# 广告账户 MCC 变更历史 — 设计文档

**日期:** 2026-07-20
**状态:** 待实现
**分支:** 待定

---

## 1. 需求描述

在广告账户详情中展示该账户的历史 MCC 归属变更记录，类似 git 提交记录。用户可以查看账户曾被分配到哪些 MCC、何时变更、由谁操作、变更前后的对比。同时支持删除错误的历史记录（如放错 MCC 的情况）。

## 2. 技术方案

### 2.1 数据模型

新建 `account_mcc_history` 表：

```sql
CREATE TABLE IF NOT EXISTS account_mcc_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id INTEGER NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
    old_mcc_id INTEGER,        -- NULL 表示首次分配或从"未分配"变更
    new_mcc_id INTEGER,        -- NULL 表示取消分配
    changed_by INTEGER REFERENCES users(id),
    change_type TEXT NOT NULL DEFAULT 'manual',
    -- change_type 取值:
    --   'manual'   — 手动编辑（AccountModal）
    --   'batch'    — 批量修改（batch-update）
    --   'reassign' — 认领转移（reassign）
    --   'import'   — 批量导入（batch-create）
    --   'create'   — 新建账户时初始分配
    created_at TEXT DEFAULT (datetime('now','localtime'))
);

CREATE INDEX IF NOT EXISTS idx_acmh_account ON account_mcc_history(account_id);
CREATE INDEX IF NOT EXISTS idx_acmh_changed_by ON account_mcc_history(changed_by);
```

**设计要点：**
- 只在 `mcc_id` 实际变更时才写入记录，相同值覆盖不产生记录
- `old_mcc_id` 为 NULL 表示这是该账户第一次被分配 MCC
- `new_mcc_id` 为 NULL 表示 MCC 被取消（清空）
- 账户删除时级联删除其历史记录
- 历史记录本身可单独删除（容错：放错 MCC 的情况）

### 2.2 后端 API

#### 新增接口

**`GET /api/accounts/<aid>/mcc-history`** — 获取 MCC 变更历史（需登录）

返回示例：
```json
{
  "success": true,
  "history": [
    {
      "id": 3,
      "account_id": 10,
      "old_mcc_id": 3,
      "old_mcc_name": "MCC-北美",
      "old_mcc_code": "123-456-7890",
      "new_mcc_id": 5,
      "new_mcc_name": "MCC-东南亚",
      "new_mcc_code": "098-765-4321",
      "changed_by": 2,
      "changed_by_name": "张三",
      "change_type": "manual",
      "change_type_label": "手动编辑",
      "created_at": "2026-07-20 14:30:00"
    }
  ]
}
```

**`DELETE /api/accounts/<aid>/mcc-history/<hid>`** — 删除单条历史记录（admin/developer）

返回：
```json
{ "success": true }
```

#### 埋点（写入历史记录）

在以下 5 个位置自动检测 `mcc_id` 变化并写入历史：

| 函数 | API 路由 | change_type |
|------|---------|-------------|
| `accounts_create()` | POST /api/accounts/create | `create` |
| `accounts_update()` | PUT /api/accounts/\<aid\> | `manual` |
| `accounts_batch_update()` | POST /api/accounts/batch-update | `batch` |
| `accounts_reassign()` | PUT /api/accounts/\<aid\>/reassign | `reassign` |
| `accounts_batch_create()` | POST /api/accounts/batch-create | `import` |

**核心逻辑(python 伪代码):**
```python
def _record_mcc_change(db, account_id, new_mcc_id, changed_by, change_type):
    old = db.execute("SELECT mcc_id FROM accounts WHERE id=?", (account_id,)).fetchone()
    if not old:
        return
    old_mcc_id = old["mcc_id"]
    # 值未变化不记录
    if old_mcc_id == new_mcc_id:
        return
    if old_mcc_id == 0 or old_mcc_id == "0" or old_mcc_id == "":
        old_mcc_id = None
    if not new_mcc_id or new_mcc_id == 0 or new_mcc_id == "0":
        new_mcc_id = None
    db.execute(
        "INSERT INTO account_mcc_history(account_id, old_mcc_id, new_mcc_id, changed_by, change_type) "
        "VALUES(?,?,?,?,?)",
        (account_id, old_mcc_id, new_mcc_id, changed_by, change_type)
    )
```

### 2.3 前端

#### 组件：`AccountDetailModal.vue`（新建）

- 参考 `ProductDetailModal.vue` 的实现模式，使用 `el-dialog`
- 打开时通过 API 加载账户信息和 MCC 历史

**内容布局：**

**上部 — 账户基本信息（只读）**
- 名称、账户 ID、当前 MCC、时区、代理、状态、到手时间

**下部 — MCC 变更历史时间线**
- 使用 `el-timeline` 组件渲染，时间倒序
- 每条记录展示：
  - 时间戳（`created_at`）
  - 操作人（`changed_by_name`）
  - 旧 MCC → 新 MCC，带颜色语义：
    - 🟢 绿色 = 新 MCC
    - 🔴 红色 = 旧 MCC
    - ⚪ 灰色 = 未分配
  - 变更类型标签（手动编辑 / 批量修改 / 认领转移 / 批量导入 / 新建）
  - 删除按钮（hover 出现，仅 admin/developer 可见）
- 无历史记录时显示空状态提示

#### 入口改动：`AdsAccountPanel.vue`

在操作列增加"详情"按钮：
```
[✏️ 编辑] [📋 详情] [🗑 删除]
```

#### 路由 / Store / API

- `frontend/src/api/accounts.js` — 新增 `accountsApi.history(aid)` 和 `accountsApi.deleteHistory(aid, hid)`
- `frontend/src/stores/accounts.js` — 无需大改，AccountDetailModal 内自行管理状态

## 3. 涉及的文件

### 后端
| 文件 | 改动 |
|------|------|
| `py/database.py` | 新增 `account_mcc_history` 表定义 + 迁移逻辑 |
| `py/main.py` | 新增 2 个 API 路由 + 5 处埋点 + 辅助函数 `_record_mcc_change()` |

### 前端
| 文件 | 改动 |
|------|------|
| `frontend/src/components/AccountDetailModal.vue` | **新建** — 账户详情 + MCC 历史时间线 |
| `frontend/src/views/AdsAccountPanel.vue` | 操作列增加"详情"按钮 |
| `frontend/src/api/accounts.js` | 新增 `history()` / `deleteHistory()` API 调用 |
| `frontend/src/stores/accounts.js` | 按需增加辅助方法 |

## 4. 纯增量原则约束

- 不在已有的业务函数中修改核心逻辑，只在调用前/后追加 4-5 行历史记录代码
- `AccountModal.vue`、`AccountBatchImportModal.vue` 等已有组件不做任何修改
- `AdsAccountPanel.vue` 只在操作列增加一个按钮，其余不动

## 5. 性能考量

- 历史表按 `account_id` 建索引，查询高效
- 单账户的历史记录量通常很小（几十条以内），无需分页
- `GET /api/accounts/list` 不需要 JOIN 历史表，仅在打开详情弹窗时才查询

## 6. 验证要点

1. 新建账户（带 MCC）→ 历史记录生成一条，change_type = `create`
2. 编辑账户改 MCC → 历史记录生成，change_type = `manual`
3. 批量修改 MCC → 每条变更分别生成，change_type = `batch`
4. 认领转移 → 历史记录生成，change_type = `reassign`
5. 批量导入 → change_type = `import`
6. MCC 未变化 → 不产生记录
7. 删除历史记录 → 软删除或硬删除，不影响账户本身
8. 删除账户 → 级联删除关联历史
9. 已有账户的编辑/批量更新功能不受影响

---

## 实际代码逻辑补充（2026-07-23 审计）

以下内容基于对 `py/database.py`、`py/main.py`、`frontend/src/components/AccountDetailModal.vue`、`frontend/src/views/AdsAccountPanel.vue`、`frontend/src/api/accounts.js`、`frontend/src/stores/accounts.js`、`frontend/src/stores/auth.js` 的实际代码审计记录。标记了所有与设计文档有差异或文档中未提及的实现细节。

### 2.2 补充：`_record_mcc_change` 实际空值标准化逻辑

设计文档中的伪代码与最终实现有两处差异：

**差异 1 — 空字符串判断更健壮：**

```python
# 设计文档伪代码
if old_mcc_id == 0 or old_mcc_id == "0" or old_mcc_id == "":
    old_mcc_id = None

# 实际代码 (main.py:1541-1544)
if old_mcc_id == 0 or old_mcc_id == "0" or (isinstance(old_mcc_id, str) and not old_mcc_id.strip()):
    old_mcc_id = None
if new_mcc_id == 0 or new_mcc_id == "0" or (isinstance(new_mcc_id, str) and not new_mcc_id.strip()):
    new_mcc_id = None
```

实际代码使用 `isinstance(x, str) and not x.strip()` 代替 `== ""`，能正确覆盖 `"  "`（纯空格字符串）的情况。

**差异 2 — 新增「双方都为空则不记录」的提前返回：**

```python
# 实际代码 (main.py:1545-1546)，设计文档伪代码中没有此逻辑
if new_mcc_id is None and old_mcc_id is None:
    return
```

此检查处理了"新值和旧值标准化后都是 NULL"的边界情况（如从 0 改成空字符串），避免写入无意义的空记录。

### 2.2 补充：create 和 import 场景不使用 `_record_mcc_change`

设计文档暗示 5 个埋点都调用 `_record_mcc_change`。实际代码中 `accounts_create` 和 `accounts_batch_create` 是**直接 INSERT**，不经过 `_record_mcc_change`：

- `accounts_create`（main.py:3477-3483）：INSERT 完成后用 `SELECT last_insert_rowid()` 获取新 ID，直接写入 history，`old_mcc_id` 硬编码为 NULL。
- `accounts_batch_create`（main.py:3580-3587）：同上模式。

原因：新账户不存在"旧值"，`_record_mcc_change` 内部靠 `SELECT mcc_id FROM accounts` 查旧值，对新账户查不到行。代码注释写明"直接写入，因为 _record_mcc_change 检测的是变更"。

### 2.2 补充：create/import 的两次 commit 非原子

**这是与 update/reassign 路径的关键不一致。** `accounts_update`、`accounts_batch_update`、`accounts_reassign` 中，历史记录 INSERT 和账户 UPDATE 在同一个事务中，最后一次性 `db.commit()`。但 `accounts_create` 和 `accounts_batch_create` 的流程是：

```
1. INSERT INTO accounts  →  db.commit()   ← 账户已持久化
2. INSERT INTO account_mcc_history  →  db.commit()   ← 历史记录单独提交
```

如果第 2 步（历史记录写入）失败，账户已经创建成功但缺少历史记录。虽然 `account_mcc_history` 表结构简单、失败概率极低，但这种不一致的事务边界仍然是一个潜在风险点。

### 2.2 补充：`accounts_update` 中埋点在 UPDATE 之前执行

设计文档未明确 `_record_mcc_change` 与 UPDATE 的执行顺序。实际代码（main.py:3628-3629）：

```python
_record_mcc_change(db, aid, val, user_id, "manual")  # 先读旧值、写入历史
db.execute("UPDATE accounts SET mcc_id=?...")          # 再更新
```

这个顺序是**正确且必要的**：`_record_mcc_change` 内部通过 `SELECT mcc_id FROM accounts` 读取当前 DB 值作为 `old_mcc_id`，必须在 UPDATE 覆盖之前读取。如果顺序反过来，将永远检测不到变化。

### 2.2 补充：`accounts_reassign` 中 mcc_id 为可选字段

设计文档未提及这一条件。实际代码中，`accounts_reassign`（main.py:3748-3753）仅在请求数据包含 `mcc_id` 字段时才记录 MCC 变更：

```python
if "mcc_id" in data:
    mcc_val = data["mcc_id"]
    ...
    _record_mcc_change(db, aid, mcc_val, user_id, "reassign")
    db.execute("UPDATE accounts SET mcc_id = ? WHERE id = ?", (mcc_val, aid))
```

如果前端认领转移时不传 `mcc_id`（只转移 owner），则不会产生 MCC 历史记录。设计文档的验证要点第 4 条"认领转移 → 历史记录生成，change_type = reassign"需要补充这一前置条件。

### 2.2 补充：DELETE API 返回 `deleted` 计数

设计文档声明的 DELETE 返回：

```json
{ "success": true }
```

实际返回（main.py:4227-4229）：

```json
{ "success": true, "deleted": 0 }
```

`deleted` 来自 `cur.rowcount`，值为 0 时表示未找到匹配记录（hid 不存在或不属于该 aid）。前端目前未使用此字段，但可用于更精确的错误提示。

### 2.2 补充：DELETE 使用双重 WHERE 条件

设计文档中 DELETE 路由为 `/api/accounts/<aid>/mcc-history/<hid>`，但未说明 SQL 层面的约束。实际 SQL（main.py:4223）：

```sql
DELETE FROM account_mcc_history WHERE id=? AND account_id=?
```

同时校验 `id` 和 `account_id`，防止通过修改 URL 中的 `hid` 来删除其他账户的历史记录。

### 2.2 补充：DELETE 权限检查逻辑

**后端**（main.py:4218）：

```python
if not user or user["role"] not in ("developer", "admin"):
    return jsonify({"success": False, "error": "权限不足"}), 403
```

**前端**（AccountDetailModal.vue:111）：

```html
<el-button v-if="authStore.isAdmin" ... >✕</el-button>
```

前端 `authStore.isAdmin`（auth.js:11）定义为 `['developer', 'admin'].includes(state.user?.role)`，与后端权限对齐。设计文档仅模糊描述为"admin/developer"，未给出具体判断逻辑。

### 2.2 补充：`_MCC_CHANGE_TYPE_LABELS` 模块级常量

设计文档未提及类型标签的实现方式。实际代码定义了模块级常量（main.py:1528-1531）：

```python
_MCC_CHANGE_TYPE_LABELS = {
    "manual": "手动编辑", "batch": "批量修改", "reassign": "认领转移",
    "import": "批量导入", "create": "新建账户",
}
```

在 GET API 中通过 `_MCC_CHANGE_TYPE_LABELS.get(change_type, change_type)` 转换为中文标签，避免了每次请求重新创建字典。

### 2.3 补充：AccountDetailModal 额外展示充值记录

设计文档描述的弹窗内容仅包含"账户基本信息"和"MCC 变更历史时间线"。实际组件（AccountDetailModal.vue）还额外包含：

- **充值记录表格**（第 30-76 行）：展示金额、状态、代理、运营、表格同步状态、时间
- **充值记录编辑**：支持内联编辑金额和代理（`startEdit`/`saveEdit`/`cancelEdit`）
- **充值记录删除**：admin 可删除充值记录（`deleteRecharge`）
- **充值表格重试**：对于 `sheets_synced === 0` 的记录，提供重试按钮（`retryRechargeSheets`）

API 调用中新增了 `accountsApi.rechargeRecords(aid)`、`rechargeApi.update()`、`rechargeApi.delete()`、`rechargeApi.retrySheets()`。这些在设计文档中完全未提及。

### 2.3 补充：账户信息从 store 获取而非 API

设计文档描述为"打开时通过 API 加载账户信息"。实际代码（AccountDetailModal.vue:162-167）：

```javascript
const store = useAccountStore()
const found = store.accounts.find(a => a.id === props.accountId)
if (found) {
  account.value = { ...found }
}
```

账户基本信息直接从 Pinia store 中已加载的 `accounts` 列表查找。如果 store 中未加载该账户（如通过直接 URL 访问），`account.value` 将为 null，此时弹窗只显示"加载中..."的空状态。这是一个隐含的前置条件：必须先加载账户列表。

### 2.3 补充：删除按钮的 hover 显隐设计

设计文档描述为"删除按钮（hover 出现，仅 admin/developer 可见）"。实际实现（AccountDetailModal.vue:110-118 及 CSS:317-323）：

```css
.delete-btn {
  flex-shrink: 0;
  opacity: 0.5;      /* 始终可见，半透明 */
}
.delete-btn:hover {
  opacity: 1;         /* hover 时完全不透明 */
}
```

删除按钮**始终渲染**（但有 `v-if="authStore.isAdmin"` 权限控制），并非 hover 时从无到有出现，而是 hover 时从不透明变完全透明的视觉效果。与设计文档描述的"hover 出现"行为不同。

### 2.4 补充：空值标准化逻辑存在代码重复

以下三处各自实现了相同的空值标准化逻辑（`0`/`"0"`/空字符串 → `None`），但代码是复制粘贴而非复用：

| 位置 | 函数 | 行号 |
|------|------|------|
| `_record_mcc_change` | 通用辅助函数 | 1541-1544 |
| `accounts_create` | 新建账户 | 3475-3476 |
| `accounts_batch_create` | 批量导入 | 3578-3579 |

### 2.4 补充：账户删除采用「手动删除 + FK CASCADE」双重保障

设计文档描述"账户删除时级联删除其历史记录"，指 FK `ON DELETE CASCADE`。实际代码在 `accounts_delete`（main.py:3775）和 `accounts_batch_delete`（main.py:3797）中额外手动执行了：

```python
db.execute("DELETE FROM account_mcc_history WHERE account_id=?", (aid,))
```

这是防御性做法，确保即使 FK 约束未生效（如 SQLite 中 `PRAGMA foreign_keys` 未开启），历史记录也会被清理。

### 2.4 补充：用户删除时的 `changed_by` 软置空

设计文档未提及此场景。实际代码在用户删除时（main.py:5824）：

```python
conn.execute("UPDATE account_mcc_history SET changed_by = NULL WHERE changed_by = ?", (uid,))
```

历史记录本身被保留，仅将操作人字段置 NULL（硬删除用户，但保留操作痕迹）。前端 GET API 已对此做了兼容处理（fallback 为 `f"User#{changed_by}"`）。

### 2.4 补充：删除方式为硬删除

设计文档写"软删除或硬删除"。实际代码使用 SQL `DELETE FROM`，是硬删除，无 `deleted_at` 或 `is_deleted` 字段。

### 3 补充：涉及文件清单更新

实际涉及文件比设计文档多：

| 文件 | 改动 | 文档是否提及 |
|------|------|------------|
| `frontend/src/api/client.js` | API 基础配置（间接依赖） | 否（隐式） |
| `frontend/src/stores/auth.js` | `isAdmin` getter 用于删除权限 | 否 |

### 4 补充：事务一致性总结

| 函数 | change_type | 使用 `_record_mcc_change` | 事务提交方式 |
|------|-----------|--------------------------|-------------|
| `accounts_create` | `create` | 否（直接 INSERT） | 两次独立 commit（**非原子**） |
| `accounts_update` | `manual` | 是（在 UPDATE 之前） | 单次 commit（原子） |
| `accounts_batch_update` | `batch` | 是（在 UPDATE 之前） | 单次 commit（原子） |
| `accounts_reassign` | `reassign` | 是（在 UPDATE 之前，仅当 mcc_id 在请求中） | 单次 commit（原子） |
| `accounts_batch_create` | `import` | 否（直接 INSERT） | 每条记录两次独立 commit（**非原子**） |
