# 视频/文案编辑删除权限修复设计

## 需求

**方案 A**：公开视频/文案任何人可编辑删除，私有视频/文案只有 owner 和管理员可操作。

| | 公开 (is_public=1) | 私有 (is_public=0) |
|---|---|---|
| 管理员 (admin/developer) | ✅ 可编辑/删除 | ✅ 可编辑/删除 |
| owner 本人 | ✅ | ✅ |
| 其他普通用户 | ✅ | ❌ |

## 现状问题

### 后端

| 接口 | 当前行为 | 问题 |
|---|---|---|
| `/api/youtube/delete` | `WHERE id=? AND owner_id=?` | 只允许 owner 删，公开视频其他人删不了 |
| `/api/youtube/edit` | `WHERE id=?` | 无任何权限校验，任何人可改任何视频 |
| `/api/youtube/batch-edit` | `WHERE id=?` | 同上 |
| `/api/copywriting/delete` | `WHERE id=?` | 无任何权限校验 |
| `/api/copywriting/edit` | `WHERE id=?` | 无任何权限校验 |
| `/api/copywriting/batch-edit` | `WHERE id=?` | 无任何权限校验 |

### 前端

- 编辑/删除按钮对所有用户可见，不区分权限
- 非 owner 点删除按钮后端静默跳过，无提示

## 技术方案

### 1. 后端：添加权限校验辅助函数

在 `main.py` 中添加：

```python
def _check_edit_permission(user_id, table, item_id):
    """检查用户是否有权编辑/删除某项。
    admin/developer 始终有权限；
    普通用户只能操作自己的项或公开项。
    返回 (can_edit: bool, error_msg: str|None)
    """
    user = auth.get_user_by_id(user_id)
    if user and user["role"] in ("developer", "admin"):
        return True, None
    db = _yt_db()
    row = db.execute(
        f"SELECT owner_id, is_public FROM {table} WHERE id=?",
        (item_id,)
    ).fetchone()
    if not row:
        return False, "记录不存在"
    if row["owner_id"] == user_id:
        return True, None
    if row["is_public"] == 1:
        return True, None
    return False, "无权限：仅可编辑/删除自己的或公开的内容"
```

### 2. 各接口改动

#### `/api/youtube/delete`

```python
# 旧：for vid in ids: db.execute("DELETE FROM videos WHERE id=? AND owner_id=?", (vid, user_id))
# 新：
user = auth.get_user_by_id(user_id)
is_admin = user and user["role"] in ("developer", "admin")
deleted = 0
for vid in ids:
    if is_admin:
        db.execute("DELETE FROM videos WHERE id=?", (vid,))
        deleted += 1
    else:
        # 非管理员只能删自己的或公开的
        cur = db.execute("DELETE FROM videos WHERE id=? AND (owner_id=? OR is_public=1)", (vid, user_id))
        deleted += cur.rowcount
db.commit()
return jsonify({"success": True, "deleted": deleted})
```

#### `/api/youtube/edit`

```python
# 添加权限校验：先查出 owner_id 和 is_public，再判断
user = auth.get_user_by_id(user_id)
is_admin = user and user["role"] in ("developer", "admin")
if not is_admin:
    row = db.execute("SELECT owner_id, is_public FROM videos WHERE id=?", (vid,)).fetchone()
    if not row:
        return jsonify({"success": False, "error": "视频不存在"}), 404
    if row["owner_id"] != user_id and row["is_public"] != 1:
        return jsonify({"success": False, "error": "无权限：仅可编辑自己的或公开的视频"}), 403
# 现有 UPDATE 逻辑保持不变
```

#### `/api/youtube/batch-edit`

同上逻辑，对每个 id 做权限校验：
```python
user = auth.get_user_by_id(user_id)
is_admin = user and user["role"] in ("developer", "admin")
updated = 0
for vid in ids:
    if is_admin:
        db.execute(f"UPDATE videos SET {field}=? WHERE id=?", (value, vid))
        updated += 1
    else:
        cur = db.execute(
            f"UPDATE videos SET {field}=? WHERE id=? AND (owner_id=? OR is_public=1)",
            (value, vid, user_id)
        )
        updated += cur.rowcount
db.commit()
return jsonify({"success": True, "updated": updated})
```

#### `/api/copywriting/delete`

```python
# 旧：DELETE FROM copywritings WHERE id=?
# 新：
user = auth.get_user_by_id(user_id)
is_admin = user and user["role"] in ("developer", "admin")
deleted = 0
for cid in ids:
    if is_admin:
        db.execute("DELETE FROM copywritings WHERE id=?", (cid,))
        deleted += 1
    else:
        cur = db.execute("DELETE FROM copywritings WHERE id=? AND (owner_id=? OR is_public=1)", (cid, user_id))
        deleted += cur.rowcount
db.commit()
return jsonify({"success": True, "deleted": deleted})
```

#### `/api/copywriting/edit`

同 youtube edit，添加权限校验。

#### `/api/copywriting/batch-edit`

同 youtube batch-edit，对每个 id 校验。

### 3. 前端改动

在 [YoutubeView.vue](frontend/src/views/YoutubeView.vue) 中：

**视频列操作按钮**（第 106 行 popover）：
- 判断条件：`authStore.isAdmin || row.owner_id === authStore.user?.id || row.is_public`
- 不满足条件时，隐藏 "编辑" 按钮（或整个 popover）

**删除选中按钮**（第 52 行）：
- 保持可见，后端会处理权限（无权限的项静默跳过）

**批量编辑工具栏**（第 56-73 行）：
- 保持可见，后端会处理权限

**文案部分同理**：
- 单个删除按钮 `cwDeleteOne`：根据权限隐藏
- 批量操作保持可见

### 4. 涉及文件

- `py/main.py` — 6 个接口 + 1 个辅助函数
- `frontend/src/views/YoutubeView.vue` — 按钮条件渲染

### 5. 不涉及的部分

- 导入、列表查询、标签配置等接口不受影响
- 数据库 schema 不变

---

## 实际代码逻辑补充（2026-07-23 审计）

以下记录设计文档与实际代码的差异。

### 一、后端 `py/main.py`

#### 1. 权限校验辅助函数

设计文档命名为 `_check_edit_permission(user_id, table, item_id)`，实际实现命名为 `_can_modify(db, user_id, table, item_id)`（line 1768）。差异：

- 函数名不同。
- 实际签名多了一个 `db` 参数，由调用方传入数据库连接。
- 实际函数在校验完成后通过 `try/finally` 块调用 `db.close()`。

**潜在问题 — `_can_modify` 关闭了调用方仍在使用的 db 连接**：`_can_modify` 在 `finally` 块中无条件执行 `db.close()`（line 1788-1789）。调用方（`youtube_edit` line 1824-1833、`copywriting_edit` line 5579-5589）在 `_can_modify` 返回 `(True, None)` 后立即继续使用该 db 连接执行 UPDATE 和 SELECT。由于 `_yt_db()` 基于 `flask.g` 缓存连接（line 1518-1524），同一请求内始终返回同一个连接对象，关闭后将导致后续 SQL 操作抛出 `ProgrammingError: Cannot operate on a closed database`。

- 对**管理员**用户不触发：`_can_modify` 在进入 `try/finally` 前就 `return True, None`（line 1775-1776），不关闭连接。
- 对**普通用户**（owner 本人或编辑公开内容时）：`_can_modify` 返回 `True` 后 db 已被关闭，后续 UPDATE 理论上会失败。如果此场景在生产环境未报错，建议排查是否普通用户实际从未触发过编辑路径，或 `database.get_db()` 返回的连接对象对 `close()` 有特殊处理。

#### 2. 权限校验模式未统一

设计文档建议所有 6 个接口统一调用 `_check_edit_permission`。实际代码中：

| 接口 | 实际权限校验方式 |
|---|---|
| `/api/youtube/edit` | 调用 `_can_modify()` |
| `/api/copywriting/edit` | 调用 `_can_modify()` |
| `/api/youtube/delete` | 内联 `is_admin` 判断 + 条件 SQL（line 1800-1812） |
| `/api/copywriting/delete` | 内联 `is_admin` 判断 + 条件 SQL（line 5602-5611） |
| `/api/youtube/batch-edit` | 内联 `is_admin` 判断 + 条件 SQL（line 1850-1867） |
| `/api/copywriting/batch-edit` | 内联 `is_admin` 判断 + 条件 SQL（line 5628-5651） |

实际只有 2 个 edit 接口使用了 `_can_modify`，其余 4 个接口保留了各自的内联权限逻辑。

#### 3. `/api/youtube/delete` 额外清理关联数据

实际代码在删除视频前，先级联删除 `product_assets` 和 `video_consumption` 表中的关联记录（line 1803-1805）。设计文档未提及此清理逻辑。

#### 4. `/api/youtube/batch-edit` 的 `is_public` 特殊限制

实际代码中，当 `field == "is_public"` 时，**即使是管理员也只能修改自己上传的视频的可见性**（line 1854-1859）：

```python
if field == "is_public":
    cur = db.execute(
        "UPDATE videos SET is_public=? WHERE id=? AND owner_id=?",
        (value, vid, user_id)
    )
```

设计文档所有字段统一使用 `(owner_id=? OR is_public=1)` 条件，未提及此例外。

#### 5. `/api/copywriting/batch-edit` 支持双字段同时更新

设计文档描述的是单字段批量编辑模式（类似 youtube/batch-edit 的 `field` + `value`）。实际代码在一个请求中同时接受 `region` 和 `effectiveness` 两个可选字段（line 5621-5622），对每个字段分别执行独立的 UPDATE 语句。这也导致前端传参格式不同——不传 `field`/`value`，而是直接传 `region` 和/或 `effectiveness`。

#### 6. 可编辑字段白名单

实际后端代码对各接口的可编辑字段做了白名单限制：

| 接口 | 允许编辑的字段 |
|---|---|
| `/api/youtube/edit` | `region`, `frame_type`, `effectiveness`, `product_name`, `review_status`, `is_public`（6 个） |
| `/api/copywriting/edit` | `region`, `content`, `effectiveness`（3 个） |
| `/api/youtube/batch-edit` | `region`, `frame_type`, `effectiveness`, `product_name`, `review_status`, `is_public`（6 个，`is_public` 有额外限制） |
| `/api/copywriting/batch-edit` | `region`, `effectiveness`（2 个） |

注意 `owner_id` 不在任何可编辑字段中——即使用户通过编辑接口传入 `owner_id`，后端也会忽略。

#### 7. `/api/copywriting/list` 的 scope 过滤

设计文档未涉及列表查询。实际代码使用 `_scope_where(scope, user_id, alias)` 函数（line 162-170）实现三级过滤：

- `scope=public`：只查 `is_public=1`
- `scope=private`：只查 `owner_id=?`（自己的）
- `scope=all`（或其他）：查 `is_public=1 OR owner_id=?`

前端通过 `store.cwScope` 控制（仅管理员可见切换控件，普通用户强制 `public`）。

### 二、前端

#### 8. CopywritingTab.vue 独立组件

设计文档标注只修改 `frontend/src/views/YoutubeView.vue`。实际代码创建了独立组件 `frontend/src/components/youtube/CopywritingTab.vue`：

- YoutubeView.vue line 252：`import CopywritingTab from '@/components/youtube/CopywritingTab.vue'`
- YoutubeView.vue line 196：`<CopywritingTab ref="cwTabRef" v-show="activeTab === 'copywriting'" />`

CopywritingTab.vue 通过 `defineExpose({ loadCopywritings })`（line 259）暴露刷新方法，父组件在切换到文案 tab 时调用（YoutubeView.vue line 749-750）。

#### 9. YoutubeView.vue 遗留死代码

YoutubeView.vue 的 `<script>` 区域（lines 573-744，约 170 行）仍保留了大量 copywriting 相关函数和变量，包括：`cwTableRef`、`cwSelected`、`cwBatchRegion`、`cwBatchEff`、`cwTransMap`、`copywritingTree`、`cwSelectable`、`cwRowClass`、`cwToggleSelectAll`、`cwInvertSelection`、`copyCopywriting`、`cwTranslate`、`cwCopyTrans`、`cwOpenEdit`、`cwSaveEdit`、`cwDeleteOne`、`cwDeleteSelected`、`cwDoBatchEdit`、`cwDoBatchEffEdit`、`loadCopywritings`。

这些代码在模板中**没有任何引用**（模板中仅使用 `<CopywritingTab>` 组件），属于 CopywritingTab.vue 抽取后的遗留代码，建议清理。

#### 10. 非管理员强制公开视图

YoutubeView.vue `onMounted`（lines 472-476）中，普通用户被强制设置：

```javascript
if (!authStore.isAdmin) {
    store.filters.scope = 'public'
    store.cwScope = 'public'
}
```

这比设计文档的"仅靠按钮隐藏"更进一步——从数据源层面确保普通用户只能看到公开内容，无法通过修改请求参数绕过。

#### 11. 权限判断函数与设计一致

`canModifyVideo`（YoutubeView.vue line 491）和 `canModifyCopywriting`（CopywritingTab.vue line 119-121）的实现与设计文档完全一致：

```javascript
authStore.isAdmin || row.owner_id === authStore.user?.id || row.is_public
```

视频的编辑按钮通过 `v-if="canModifyVideo(row)"` 控制可见（YoutubeView.vue line 120），文案的编辑和删除按钮通过 `v-if="canModifyCopywriting(row)"` 控制（CopywritingTab.vue lines 38-39）。批量删除/批量编辑工具栏保持对所有用户可见（后端处理权限）。

#### 12. 前端 API 和 Store 层

设计文档未涉及 API 层和状态管理，实际代码中：

- **API 层**（`frontend/src/api/youtube.js`）：`copywritingApi` 对象包含 `list`、`import`、`edit`、`delete`、`batchEdit` 共 5 个接口，均通过 `api.post()` 或 `api.get()` 调用。
- **Store 层**（`frontend/src/stores/youtube.js`）：文案相关 state 为 `copywritings`、`copywritingCounts`、`cwScope`。文案 action 使用 `dedupLoader` 工具函数做请求去重，避免短时间内重复请求。

### 三、总结

| 类别 | 状态 | 说明 |
|---|---|---|
| 权限模型 | 已实现且一致 | 公开内容所有人可操作，私有内容仅 owner+admin 可操作 |
| `_can_modify` 辅助函数 | 存在潜在 bug | 对非管理员用户会关闭调用方仍在使用的 db 连接 |
| 权限校验模式 | 未完全统一 | 仅 2/6 接口使用辅助函数，其余 4 个保留内联逻辑 |
| 前端组件拆分 | 已完成但未清理 | CopywritingTab 已独立，YoutubeView 中遗留约 170 行死代码 |
| `is_public` 批量编辑 | 设计未覆盖 | 管理员也只能改自己视频的可见性，比设计更严格 |
| 关联数据清理 | 设计未覆盖 | 删除视频时级联清理 product_assets 和 video_consumption |
| scope 过滤 | 设计未覆盖 | 列表查询通过 `_scope_where` 实现三级权限过滤 |

### 四、2026-07-23 修复记录

**1. `_can_modify` bug 修复**

`py/main.py` 中 `_can_modify()` 函数（L1788-1789）原来用了 `finally: db.close()`，导致非管理员用户权限校验通过后，db 连接被意外关闭，调用方后续的 UPDATE/SELECT 操作崩溃。

修复方式：将 `finally: db.close()` 改为 `except Exception: return False, "查询出错"`，与 `routes/helpers.py` 中的 `can_modify()` 保持一致。

**2. CopywritingTab UI 改造：树形 → 地区标签页**

原设计使用 el-table 的树形展示（虚拟 `isRegion` 行作为父节点），交互不够直观。改造为：

- **顶部地区标签页**：圆角标签按钮，显示 `全部(15)` `巴西(5)` `东南亚(4)` ...，点击切换过滤
- **扁平表格**：移除 `tree-props`，每行前面用 `el-tag` 显示所属地区
- **排序保持不变**：先按地区名排序，同一地区内按内容排序
- 其他功能（全选/反选、批量改地区/成效、翻译、编辑、删除）全部保持不变
