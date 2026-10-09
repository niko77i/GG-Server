# GG 看板同步认领 + 不再静默失败 实现计划

> **For agentic workers:** 按任务顺序执行，每任务走 TDD（先写失败测试 → 跑 → 实现 → 跑 → 提交）。

**Goal:** 同步不再把"系统里已存在的账户"误当新增（修根因），并提供认领通道；前端显示创建失败明细。

**Architecture:** 后端 `POST /api/accounts/sync-from-sheet` 的差异报告新增 `to_claim` 分类并把它从 `to_create` 里排除；认领执行复用 `accounts_reassign` 的核心（抽 `_reassign_owner` helper）。前端 `AccountSyncModal.vue` 渲染认领区块 + 错误明细。

**Tech Stack:** Python 3.11 / Flask / SQLite / Vue 3 + Element Plus / pytest

设计依据：`docs/superpowers/specs/2026-10-09-gg-sync-claim-design.md`（下称"设计 §X"）

## Global Constraints

- **只改 GG 的同步**。TT 的 `sync-from-sheet`、以及「批量导入」「新增账户」两个既有认领入口**一行不改**。
- **不动 `accounts.account_id` 的全局唯一约束**（产品口径）。
- **读侧 `existing_map` 的 owner 口径不变**（自己的账户仍走原 `to_update` / `unchanged` 逻辑）。
- **认领权限 = `CROSS_USER_ROLES`**（developer / admin / 户管），与另两个入口一致。
- **提交纪律**：只 `git add` 本任务列出的文件。**禁止 `git add -A` / `git add .`**（工作区有并行会话）。**禁止 `git push`**。
- 测试命令：`cd py && python -m pytest tests/<file> -q`（提交前跑相关文件全量）。

---

## Task 1: 后端 —— `to_claim` 分类 + `to_create` 排除已存在 + 认领执行

**Files:**
- Modify: `py/main.py`（`accounts_sync_from_sheet` `:5286-5470`；`accounts_reassign` `:4811-4921`；新增 `_reassign_owner` 与 `_execute_sync_claim`）
- Test: `py/tests/test_account_sync_claim.py`（新建）

**Interfaces:**
- Produces:
  - `_reassign_owner(db, aid: int, target_owner: int, actor_id: int) -> None` —— 改 `owner_id` + 两次回写（`hd.writeback_rows` / `hd.writeback_owner_channel`），与 `accounts_reassign` 同口径
  - diff 新增 `to_claim: [{account_id, existing_id, owner_id, owner_name, deleted}]`
  - `confirmed.claim: [account_id, ...]` 执行认领

- [ ] **Step 1: 写失败测试**

新建 `py/tests/test_account_sync_claim.py`。参照 `py/tests/test_gg_sheet_write.py` 或 `test_huguan_dashboard.py` 的既有点法（`client` 夹具 + `monkeypatch` 打桩 `google_sheets_service.read_sheet_values` / `build_service`）。

要点（每条一个用例）：
1. **他人账户不进 `to_create`、进 `to_claim`**：库里造一条 `owner_id != 当前用户` 的账户；看板里同一 ID；`dry_run=true` → 断言 `to_create` 不含它、`to_claim` 含它、`to_claim[0]["owner_name"]` 是归属人显示名。
2. **软删的他人账户**：`deleted_at` 非空的他人账户 → 同样进 `to_claim` 且 `deleted` 为真，**不进** `to_create`。（这条是防"第二个同样的坑"。）
3. **自己的账户不受影响**：`owner_id == 当前用户` 的账户仍走原逻辑（状态变更进 `to_update`，无变化进 `unchanged`），且**不在** `to_claim` 里。
4. **认领执行**：`dry_run=false` + `confirmed={"claim": [account_id]}` → 该账户 `owner_id` 变为调用者。
5. **认领权限**：非跨用户角色（`role='user'`）发认领 → `owner_id` **不变**，且响应里该条有错误（不静默丢弃）。

- [ ] **Step 2: 跑测试确认失败**

Run: `cd py && python -m pytest tests/test_account_sync_claim.py -q`
Expected: FAIL —— diff 里没有 `to_claim`；他人账户此刻还在 `to_create` 里

- [ ] **Step 3: 抽 `_reassign_owner`**

把 `accounts_reassign`（`py/main.py:4900-4903`）里这三段抽成模块级函数，**`accounts_reassign` 改为调用它**（行为逐字不变）：

```python
def _reassign_owner(db, aid: int, target_owner: int, actor_id: int) -> None:
    """改账户归属并触发两次看板回写。

    口径与 accounts_reassign 末尾逐字一致（规格 §6.2 / §7.2 规则 3①）：
    先 commit 再回写；回写走 actor 自己的户管看板，未配置则静默 no-op。
    ⚠️ 调用方负责提供已 commit 的 db（或自行 commit）—— 本函数不 commit。
    """
    db.execute("UPDATE accounts SET owner_id = ?, updated_at = datetime('now','localtime') "
               "WHERE id = ?", (target_owner, aid))
    acct = db.execute("SELECT account_id FROM accounts WHERE id=?", (aid,)).fetchone()
    db.commit()
    if not acct:
        return
    hd.writeback_rows(actor_id, "gg", [acct["account_id"]])
    hd.writeback_owner_channel(actor_id, "gg", acct["account_id"], target_owner)
```

`accounts_reassign` 里把原来的 `UPDATE ... owner_id` + `db.commit()` + 两行回写替换为「先做字段更新 / MCC 处理，最后调 `_reassign_owner(db, aid, target_owner, user_id)`」。**注意顺序**：原实现是先 UPDATE owner、再更新其他字段、再 commit、再回写；改后保证**字段更新仍然生效**（可在 `_reassign_owner` 之前做完字段更新，或在其中一并 commit）。

- [ ] **Step 4: `to_claim` 查询与 `to_create` 排除**

在 `accounts_sync_from_sheet` 的 `existing_map` 查询之后加：

```python
    # 这些 ID 里「不属于自己」的行（含软删）—— 它们是本次的认领候选。
    # ⚠️ 必须含软删：软删的他人账户既不在 existing_map（owner 不符）、
    #    若这里再排除掉，它就两边不沾、掉进 to_create 撞 account_id 全局唯一约束。
    other_map = {}
    for part in chunk(sheet_ids):
        marks = ",".join("?" for _ in part)
        for r in db.execute(
            f"""SELECT a.id, a.account_id, a.owner_id, a.deleted_at,
                       u.display_name AS owner_display, u.username AS owner_username
                FROM accounts a LEFT JOIN users u ON a.owner_id = u.id
                WHERE a.account_id IN ({marks}) AND a.owner_id != ?""",
            tuple(part) + (user_id,)
        ).fetchall():
            other_map[r["account_id"]] = dict(r)
```

在逐行比对循环里，`existing is None` 分支改为：

```python
        if existing is None:
            other = other_map.get(aid)
            if other is not None:
                # 系统里已有、但属于别人（或已被别人软删）。**绝不当新增** ——
                # 那必然撞 account_id 全局 UNIQUE（今天的 bug 根因）。
                to_claim.append({
                    "account_id": aid,
                    "existing_id": other["id"],
                    "owner_id": other["owner_id"],
                    "owner_name": (other["owner_display"] or other["owner_username"] or "").strip(),
                    "deleted": bool(other["deleted_at"]),
                })
                continue
            to_create.append({... original ...})
```

（`to_claim = []` 与 `to_create` 一起在循环前初始化。）

dry_run 响应里加 `"to_claim": to_claim`，`summary` 加 `"claimable": len(to_claim)`。

- [ ] **Step 5: 执行认领**

在执行段（`for item in confirmed.get("update", [])` 之前）插入：

```python
        # 10a-2. 认领他人账户（仅跨用户角色）
        for acct_id in confirmed.get("claim", []):
            try:
                target = other_map.get(acct_id) or {}
                aid = target.get("id")
                if aid is None:
                    errors.append({"account_id": acct_id, "error": "账户不存在，无法认领"})
                    continue
                if not _cross_user_actor(user_id):
                    errors.append({"account_id": acct_id, "error": "无权认领他人账户"})
                    continue
                _reassign_owner(db, aid, user_id, user_id)
                claimed_count += 1
            except Exception:
                log.exception("表格同步：认领账户失败")
                errors.append({"account_id": acct_id, "error": "认领失败，详情见服务端日志"})
```

`claimed_count` 与 `created_count` 一起初始化；响应 `result` 里加 `"claimed": claimed_count`。

- [ ] **Step 6: 跑测试确认通过**

Run: `cd py && python -m pytest tests/test_account_sync_claim.py -q`
Expected: PASS

- [ ] **Step 7: 跑同族回归**

Run: `cd py && python -m pytest tests/test_gg_sheet_write.py tests/test_huguan_dashboard.py tests/test_huguan_role.py tests/test_gg_recharge_sheet.py -q`
Expected: 全绿（`accounts_reassign` 重构后行为必须逐字不变）

- [ ] **Step 8: 提交**

```bash
git add py/main.py py/tests/test_account_sync_claim.py
git commit -m "fix(gg-sync): 已存在的账户不再误当新增 + 同步内认领他人账户"
```

---

## Task 2: 前端 —— 认领区块 + 显示失败明细

**Files:**
- Modify: `frontend/src/components/AccountSyncModal.vue`

**Interfaces:**
- Consumes: Task 1 的 `diff.to_claim` / `confirmed.claim` / `result.errors` / `result.claimed`

- [ ] **Step 1: 认领区块**

在「新增账户」区块之后加（照 `AccountBatchImportModal.vue` 的既有认领写法）：

```vue
      <!-- 他人账户（可认领） -->
      <div v-if="diff.to_claim?.length" style="margin-bottom:16px;">
        <h4>⚠ 他人账户（{{ diff.to_claim.length }} 条）{{ canClaim ? '— 可勾选认领' : '' }}</h4>
        <el-alert v-if="!canClaim" type="info" :closable="false" style="margin-bottom:8px;"
                  title="以下账户已属于他人，无法同步给你。" />
        <el-table ref="claimTableRef" :data="diff.to_claim" size="small" border stripe
                  @selection-change="val => selectedClaims = val">
          <el-table-column v-if="canClaim" type="selection" width="45" />
          <el-table-column prop="account_id" label="账户ID" min-width="130" />
          <el-table-column prop="owner_name" label="当前归属" width="110" />
          <el-table-column label="状态" width="120">
            <template #default="{ row }">
              <el-tag v-if="row.deleted" size="small" type="warning">已被他人删除</el-tag>
              <span v-else>—</span>
            </template>
          </el-table-column>
        </el-table>
      </div>
```

`canClaim` 从 store 取（与批量导入同一个判据）：`const canClaim = computed(() => store.canManageAccounts)`（按 `AccountBatchImportModal.vue` 里的实际取法照抄）。

「新增账户」区块加一行说明：`已存在的账户不会出现在这里`。

- [ ] **Step 2: 提交带 claim**

`doSync` 的请求体加 `confirmed.claim = selectedClaims.value.map(r => r.account_id)`。

- [ ] **Step 3: 显示失败明细（丙）**

`doSync` 成功分支：除 `ElMessage.success(...)` 外，若 `r.errors?.length`：

```js
      if (r.errors?.length) {
        errors.value = r.errors          // 新增 ref
        // **不关闭弹窗** —— 让用户看得见哪几条没落库
      } else {
        emit('update:visible', false)
      }
```

template 里加错误明细区块（弹窗内，`diff` 区块之后 / footer 之前）：

```vue
    <div v-if="errors.length" style="margin-top:16px;">
      <el-alert type="error" :closable="false" show-icon
                :title="`有 ${errors.length} 条没有同步成功`" />
      <el-table :data="errors" size="small" border stripe style="margin-top:8px;">
        <el-table-column prop="account_id" label="账户ID" min-width="130" />
        <el-table-column prop="error" label="原因" min-width="200" show-overflow-tooltip />
      </el-table>
    </div>
```

⚠️ 弹窗的 `v-else-if="diff"` 分支结构要调整，保证执行后仍能渲染这块（执行成功时 `diff` 仍在，通常够用；若不够，把错误块提到 `diff` 判断之外）。

- [ ] **Step 4: 静态检查**

无前端测试基线。跑 `@vue/compiler-sfc` 的 parse + compileTemplate + compileScript（本仓库前几个前端任务用过这个法子），贴结果。

- [ ] **Step 5: 提交**

```bash
git add frontend/src/components/AccountSyncModal.vue
git commit -m "feat(gg-ui): 同步弹窗支持认领他人账户 + 显示失败明细"
```

---

## 验收（人工，用户自测）

1. 卡尔同步 → `403-400-6011` 出现在「他人账户」并显示归属人「拉菲」，**不在**「新增账户」里。
2. 勾选认领 → 提交 → 该账户进入卡尔名下。
3. 故意不勾认领直接同步 → 弹窗**显示失败明细**，不再只报一个成功数字。
