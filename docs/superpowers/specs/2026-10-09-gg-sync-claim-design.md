# GG 看板同步：认领他人账户 + 不再静默失败（设计）

> 2026-10-09。触发：用户运营「卡尔」点同步，账户 `403-400-6011` 同步不进来。
> 用户裁定：**甲 + 丙**。

## 一、问题与根因

### 现象

账户 `403-400-6011` 在看板里、点同步后"系统里还是没有"。

### 根因（已用证据链确认）

**读侧按 owner 隔离，写侧靠全局唯一 —— 两边口径不一致。**

| 环节 | 位置 | 行为 |
|---|---|---|
| 建表 | `py/database.py`（`accounts`） | `account_id TEXT UNIQUE NOT NULL` —— **全局唯一，不分 owner** |
| 读（查"系统有没有"） | `py/main.py:5365` | `WHERE a.account_id IN (...) AND a.owner_id = ?` —— **只看自己的** |
| 写（新建） | `py/main.py:5585,5612` | 前置检查也是 owner 口径 → 放行 → `INSERT` → **撞全局 UNIQUE** → 抛异常 |

实测：`403-400-6011` 库里**存在**（`id=2133`，`owner_id=9`＝拉菲，未软删）。卡尔（`id=1`）查不到 → 归入 `to_create`；确认后 INSERT 撞唯一约束。

### 附带的第二个缺陷（丙）

异常被塞进 `result.errors`（后端**已经返回了**，带 account_id），但前端 `AccountSyncModal.vue:141-142` 只读 `created` / `updated`：

```js
ElMessage.success(`同步完成：新增 ${r.created} 个账户，更新 ${r.updated} 个状态`)
```

**从不读 `errors`** ⇒ 任何创建失败都**完全静默**（用户只看到绿色的成功提示，数字少一个）。

### 一个残留的次生风险

软删的他人账户：既不在 `existing_map`（owner 不符）、也不会进认领（若只列未删），**仍会掉进 `to_create`** 撞约束。必须一并处理。

## 二、方案

### 甲：同步里支持认领（复用现有的 reassign 通路）

系统里**已有两个认领入口**，行为应当一致：

- 「📥 批量导入」→ `AccountBatchImportModal.vue`：「⚠ 他人账户 — 可编辑后勾选认领」→ `accountsApi.reassign`
- 「➕ 新增账户」→ `AccountModal.vue`：认领模式「该账户已存在，当前归属「X」，可转移给我」

**同步这条是缺的**，且它把"他人的账户"误报成"新增"。本次补齐。

#### 后端 `POST /api/accounts/sync-from-sheet`（`py/main.py:5286`）

1. **新增一次查询**：这些 `account_id` 里 **`owner_id != 自己`** 的行（LEFT JOIN `users` 取归属人名），**含软删的**（带 `deleted` 标记，前端据此提示"该账户已被他人删除，认领会恢复它"）。
   → 差异报告新增 `to_claim: [{account_id, existing_id, owner_id, owner_name, deleted}]`。
2. **`to_create` 必须排除所有"系统里已存在该 account_id"的行**（无论属于谁、无论是否软删）。
   这是**修根因的关键一步**：已存在的账户绝不能再当"新增"，否则必然撞唯一约束。归属人不是自己且无权认领时，它只出现在 `to_claim` 里作为提示。
3. **执行阶段**：`confirmed.claim`（account_id 数组）→ 逐条认领：`UPDATE accounts SET owner_id=? WHERE id=?` + 两次回写（`hd.writeback_rows` / `hd.writeback_owner_channel`，与 `accounts_reassign` 同口径）。
4. **权限**：只有 `CROSS_USER_ROLES`（developer / admin / 户管）可认领 —— 与另两个入口一致。非跨用户角色的认领请求逐条返回错误，不静默丢弃。

**归位说明**：`accounts_reassign`（`py/main.py:4811`）现有逻辑里，认领所需的核心就是"改 owner_id + 两次回写"。抽一个小内部函数 `_reassign_owner(db, aid, target_owner, actor_id)` 供同步复用；`accounts_reassign` 的字段更新 / MCC 处理不动。

#### 前端 `AccountSyncModal.vue`

- 新增区块「⚠ 他人账户（N 个）— 可勾选认领」，照 `AccountBatchImportModal.vue` 的既有写法（勾选列表 + 归属人列）。
- **非跨用户角色**（`auth.canManageAccounts` 为假）不渲染勾选列，只显示一条提示：「以下账户已属于他人，无法同步给你」。
- `to_create` 区块加一行说明：已存在的账户不会出现在这里。
- 提交时把勾选项并入请求体 `confirmed.claim`。

### 丙：前端显示 `result.errors`

`doSync` 里除成功提示外，读 `res.result.errors`：非空则**不自动关闭弹窗**，在弹窗里列出失败明细（账户ID + 原因），用户能看清哪几条没落库。

> 这条是**独立的基础缺陷**，与多表/认领无关：现在**任何**创建失败都看不见。

## 三、非目标

- **不动 `accounts.account_id` 的全局唯一约束**：那是产品口径（一个账户只属于一个人），本次只修正"读侧误判成不存在"的错配。
- **不动 TT 的同步**：TT 的 `sync-from-sheet` 有自己的 conflicts/status_conflicts 机制，形态不同。
- **不动**「批量导入」「新增账户」两个既有的认领入口。
- 不做「同步时自动把他人账户转给自己」（无提示的静默转移）——必须由人勾选。

## 四、测试

| 用例 | 断言 |
|---|---|
| 他人账户不再进 `to_create` | `403-400-6011` 属于他人时，diff 里 `to_create` **不含**它、`to_claim` 含它 |
| 他人账户带归属人名 | `to_claim[0]["owner_name"]` 为归属人显示名 |
| 软删的他人账户 | 同样进 `to_claim` 且 `deleted` 为真，**不进** `to_create` |
| 自己的账户不受影响 | owner == 自己的账户仍走原 `to_update` / `unchanged` 逻辑 |
| 认领执行 | `confirmed.claim=[id]` → `owner_id` 变为调用者；两次回写被触发 |
| 非跨用户角色认领 | 逐条返回错误，`owner_id` 不变 |
| 前端 errors | （无前端测试基线）靠人工验证 |

## 五、验收（人工）

1. 卡尔同步 → 报告里 `403-400-6011` 出现在「他人账户」而不是「新增账户」，并显示归属人「拉菲」。
2. 勾选认领 → 提交 → 该账户出现在卡尔的列表里，归属为卡尔。
3. 造一条会失败的创建（如某账户已在他人名下但未勾选认领）→ 弹窗**显示失败明细**，不再只报一个成功数字。
