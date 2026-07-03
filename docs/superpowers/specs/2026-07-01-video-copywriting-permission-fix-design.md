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
