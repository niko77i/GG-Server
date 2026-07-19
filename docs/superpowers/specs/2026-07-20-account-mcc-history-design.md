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
