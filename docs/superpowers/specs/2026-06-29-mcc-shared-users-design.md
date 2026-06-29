# MCC 多人共享与去重整合 — 设计文档

**日期：** 2026-06-29
**状态：** 待实现

---

## 1. 问题描述

### 现状

`mcc` 表的 `mcc_id`（Google Ads 经理账户 ID 字符串）没有唯一约束。同一个 Google Ads MCC 被不同用户各自创建后，产生多条数据库记录（不同的自增 `id`）。产品（`products.mcc_id`）和账户（`accounts.mcc_id`）分别关联到不同用户的 MCC 记录，导致：

- 同一产品多人合跑时，各 runner 的产品→MCC→账户 链路断裂
- 用户看不到其他 runner 关联的 MCC 和账户
- 同一个 MCC 被重复创建，数据冗余

### 目标

- 同一 `mcc_id` 全局唯一，不再重复创建
- MCC 可共享给多个用户（类似产品的 runner 机制）
- 新增 runner 时自动分配产品关联的 MCC（含上级链）
- 历史重复数据以 developer 为主进行合并
- 共享用户只能查看和使用 MCC，不能编辑/删除

---

## 2. 数据库变更

### 2.1 `mcc` 表新增字段

```sql
ALTER TABLE mcc ADD COLUMN shared_user_ids TEXT DEFAULT '[]';
```

`shared_user_ids` 为 JSON 数组，存储可访问该 MCC 的用户 ID 列表，例如 `[2, 3, 5]`。

### 2.2 唯一索引

在 `mcc.mcc_id` 列上创建唯一索引，防止未来重复插入：

```sql
CREATE UNIQUE INDEX IF NOT EXISTS idx_mcc_mcc_id_unique ON mcc(mcc_id);
```

**注意：** 创建唯一索引前必须先执行数据迁移（第 3 节），否则会因现有重复数据而失败。

---

## 3. 数据迁移（一次性，启动时自动执行）

### 3.1 迁移标记

使用 `config` 表标记迁移状态：
```
key = 'migrated_mcc_dedup'
```

### 3.2 迁移步骤

1. 查找所有重复的 `mcc_id`（同一个 `mcc_id` 字符串出现多次）：

```sql
SELECT mcc_id, COUNT(*) as cnt FROM mcc GROUP BY mcc_id HAVING cnt > 1
```

2. 对每个重复组：
   - **确定主记录**：优先保留 `owner_id` 为 developer（role='developer'）的记录；若无 developer 记录，保留 `id` 最小的（最早创建的）
   - **收集所有 shared 用户**：将该组所有 MCC 的 `owner_id` 合并 → 去重 → 排除主记录的 owner → 得到 shared 用户列表
   - **更新关联数据**：将该组中非主记录的 `products.mcc_id` 和 `accounts.mcc_id` 全部改为指向主记录的 `id`
   - **写入 shared_user_ids**：将 shared 用户列表写入主记录的 `shared_user_ids`
   - **删除重复记录**：删除该组中除主记录外的所有 MCC 行

3. 对于非重复的 MCC（只有一个记录的），确保其 `shared_user_ids` 初始化为 `[]`

4. 写入迁移标记，防止重复执行

### 3.3 外键处理

迁移期间设置 `PRAGMA foreign_keys=OFF`，完成后再开启。

---

## 4. API 变更

### 4.1 MCC 列表 — `GET /api/mcc/list`

**当前过滤：**
```sql
WHERE m.owner_id = ?
```

**改为：**
```sql
WHERE (m.owner_id = ? OR m.shared_user_ids LIKE '%' || ? || '%')
```

**返回字段新增：** 每条记录增加 `is_owner` 布尔值，标记当前用户是否是 owner（前端根据此字段控制编辑/删除按钮显示）。

### 4.2 MCC 选项 — `GET /api/mcc/options`

同样改为按 `owner_id` 或 `shared_user_ids` 过滤。

### 4.3 MCC 创建 — `POST /api/mcc/create`

**新增逻辑（在 INSERT 之前）：**

1. 先按 `mcc_id` 字符串查询是否已存在：
```sql
SELECT m.*, u.display_name, u.username FROM mcc m
LEFT JOIN users u ON m.owner_id = u.id
WHERE m.mcc_id = ?
```

2. **不存在** → 正常创建，`shared_user_ids` 初始化为 `[当前用户ID]`

3. **存在且当前用户已在 `shared_user_ids` 或为 owner** → 返回 `409`：
```json
{"success": false, "error": "该 MCC 已关联到您的账户"}
```

4. **存在且当前用户不在 shared 中** → 返回 `200` + 标记：
```json
{
  "success": true,
  "exists": true,
  "existing_mcc": { "id": 1, "name": "xxx", "mcc_id": "123-456-7890" },
  "owner_name": "张三"
}
```

### 4.4 MCC 关联（新增）— `POST /api/mcc/<int:mid>/link`

将当前用户加入指定 MCC 的 `shared_user_ids`，同时递归将上级 MCC 也加入。

**逻辑：**
1. 查询目标 MCC 是否存在
2. 检查当前用户是否已在 `shared_user_ids` 或为 owner → 若已存在，返回 409
3. 将当前用户 ID 追加到 `shared_user_ids`
4. 递归处理上级：如果该 MCC 有 `parent_mcc_id`，对上级 MCC 重复步骤 2-3
5. 提交并返回成功

### 4.5 MCC 编辑 — `PUT /api/mcc/<int:mid>`

**新增检查：**
- 当前用户必须是 `owner_id`，否则返回 403：
```json
{"success": false, "error": "只有创建者才能编辑此 MCC"}
```

### 4.6 MCC 删除 — `DELETE /api/mcc/<int:mid>`

**新增检查：**
- 当前用户必须是 `owner_id`，否则返回 403
- 删除前检查是否有子 MCC 引用了当前 MCC（`parent_mcc_id`），若有则阻止删除
- 删除后自动清理 `shared_user_ids` 中相关用户的引用（可选，级联处理）

### 4.7 批量删除 — `POST /api/mcc/batch-delete`

**新增检查：**
- 每条被删 MCC 都检查 `owner_id`，跳过非 owner 的并返回 skipped 信息

### 4.8 更新产品 Runner — `PUT /api/products/<int:pid>/runners`

**新增逻辑（在更新 runner_ids 之后）：**

1. 计算新增的 runner（对比旧 runner_ids 和新 runner_ids 的差集）
2. 查询产品关联的 MCC（`products.mcc_id`）
3. 对每个新增的 runner：
   - 调用 MCC 链分配逻辑：将产品的 MCC 及其所有上级 MCC 加入该 runner 的 `shared_user_ids`

---

## 5. 前端变更

### 5.1 MCC 新增弹窗（`MccModal.vue`）

- 提交后检查返回结果
- 若 `exists: true`，弹出确认框：
  > "MCC 'xxx (123-456-7890)' 已存在（属于 张三），是否关联到您的列表？"
- 用户确认 → 调用 `POST /api/mcc/<id>/link`
- 用户取消 → 关闭确认框，不创建

### 5.2 MCC 列表面板（`MccPanel.vue`）

- 编辑按钮：仅当 `row.is_owner === true` 时显示
- 删除按钮：仅当 `row.is_owner === true` 时显示
- 批量删除：非 owner 的自动跳过，提示给用户

### 5.3 MCC 选项下拉

- 无需改动，后端已过滤

---

## 6. 权限矩阵

| 操作 | Owner | Shared 用户 | 其他人 |
|------|-------|------------|--------|
| 查看 MCC 列表 | ✅ | ✅ | ❌ |
| 查看 MCC 详情 | ✅ | ✅ | ❌ |
| 在账户/产品中选择 MCC | ✅ | ✅ | ❌ |
| 编辑 MCC | ✅ | ❌ | ❌ |
| 删除 MCC | ✅ | ❌ | ❌ |
| 自动分配（runner 触发） | — | ✅ | — |

---

## 7. 涉及文件

### 后端
| 文件 | 改动内容 |
|------|---------|
| `py/database.py` | `mcc` 表加 `shared_user_ids` 字段；加唯一索引；编写数据迁移逻辑 |
| `py/main.py` | 修改 `mcc_list`、`mcc_options`、`mcc_create`、`mcc_update`、`mcc_delete`、`mcc_batch_delete`；新增 `mcc_link` 端点；修改 `products_update_runners` |

### 前端
| 文件 | 改动内容 |
|------|---------|
| `frontend/src/components/MccModal.vue` | 处理 MCC 已存在的确认关联流程 |
| `frontend/src/views/MccPanel.vue` | 根据 `is_owner` 控制编辑/删除按钮显隐 |
| `frontend/src/api/accounts.js` | 新增 `linkMcc(mid)` 方法 |
| `frontend/src/stores/accounts.js` | 新增 `linkMcc` action |

---

## 8. 边界情况

1. **MCC 有子 MCC 时删除**：阻止删除，提示"请先删除子 MCC"
2. **上级 MCC 已被 shared 时再分配子 MCC**：link 接口需处理上级已存在的情况（幂等，静默跳过）
3. **产品没有 MCC**：添加 runner 时跳过 MCC 分配逻辑
4. **并发创建同名 MCC**：唯一索引兜底，后到的请求返回 IntegrityError
5. **删除 runner 时**：不移除 MCC 的 shared 权限（用户可能还在其他产品中使用该 MCC）
