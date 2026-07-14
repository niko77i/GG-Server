# 视频批量可见性编辑 & 消耗追踪设计

## 需求概述

1. **批量编辑公用/私有**：admin/developer 可批量选择自己上传的视频，统一设置为公开或私有
2. **导入默认值调整**：admin/developer 导入视频默认私有，普通用户/viewer 默认公开
3. **视频消耗追踪**：手动录入广告消耗金额，按人展示消耗明细，统计总消耗

---

## 一、批量编辑公用/私有

### 1.1 权限规则

| 角色 | 批量改 is_public | 可操作范围 |
|------|-------------------|-----------|
| admin/developer | ✅ | 仅自己上传的视频（owner_id = 自己） |
| viewer / user | ❌ | 不可见此选项 |

### 1.2 前端改动

**文件**：[frontend/src/views/YoutubeView.vue](frontend/src/views/YoutubeView.vue)

在批量编辑工具栏（第 58-76 行）末尾增加可见性下拉框：

```html
<el-select v-if="authStore.isAdmin" v-model="batchPublic" 
  @change="val => doBatchEdit('is_public', val)" 
  placeholder="可见性..." size="small" style="width:110px;" clearable>
  <el-option label="🌐 公开" :value="1" />
  <el-option label="🔒 私有" :value="0" />
</el-select>
```

新增响应式变量 `batchPublic`，在 `doBatchEdit` 完成后重置。

### 1.3 后端

修改 `/api/youtube/batch-edit`，当 `field=is_public` 时，**即使是 admin 也只能更新自己的视频**（与编辑其他字段的 all-powerful 权限不同）：

```python
if field == "is_public":
    # 任何人（含 admin）只能改自己上传的视频
    cur = db.execute(
        "UPDATE videos SET is_public=? WHERE id=? AND owner_id=?",
        (value, vid, user_id)
    )
elif is_admin:
    cur = db.execute(f"UPDATE videos SET {field}=? WHERE id=?", (value, vid))
else:
    cur = db.execute(
        f"UPDATE videos SET {field}=? WHERE id=? AND (owner_id=? OR is_public=1)",
        (value, vid, user_id)
    )
```

---

## 二、导入视频默认可见性调整

### 2.1 规则

| 角色 | 默认可见性 |
|------|-----------|
| admin / developer | 🔒 私有（is_public=0） |
| viewer / user | 🌐 公开（is_public=1） |

### 2.2 前端改动

**文件**：[frontend/src/views/YoutubeView.vue:559](frontend/src/views/YoutubeView.vue#L559)

```javascript
// 旧：
const importIsPublic = ref(true)      // 默认公开

// 新：
const importIsPublic = ref(!authStore.isAdmin)  // admin默认私有，普通用户默认公开
```

文案导入同理，`cwImportPublic` 做相同修改。

---

## 三、视频消耗追踪

### 3.1 数据库

**文件**：[py/database.py](py/database.py)

新增 `video_consumption` 表：

```sql
CREATE TABLE IF NOT EXISTS video_consumption (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    video_id TEXT NOT NULL REFERENCES videos(id),
    user_id INTEGER NOT NULL REFERENCES users(id),
    product_id INTEGER REFERENCES products(id),
    amount REAL NOT NULL DEFAULT 0,
    consume_date TEXT NOT NULL DEFAULT (date('now','localtime')),
    created_at TEXT DEFAULT (datetime('now','localtime'))
);
CREATE INDEX IF NOT EXISTS idx_vc_video ON video_consumption(video_id);
CREATE INDEX IF NOT EXISTS idx_vc_user ON video_consumption(user_id);
CREATE INDEX IF NOT EXISTS idx_vc_date ON video_consumption(consume_date);
```

### 3.2 权限矩阵

| 角色 | 查看消耗 | 新增记录 | 编辑记录 | 删除记录 |
|------|---------|---------|---------|---------|
| admin / developer | ✅ | ✅（仅自己） | ✅（仅自己） | ✅（仅自己） |
| viewer / user | ✅ | ❌ | ❌ | ❌ |

### 3.3 后端 API

**文件**：[py/main.py](py/main.py)

#### 3.3.1 获取视频消耗明细

`GET /api/youtube/<vid>/consumption`

```python
# 返回：
{
  "success": true,
  "total": 15000.0,                    # 该视频总消耗
  "users": [                           # 按用户分组
    {
      "user_id": 1,
      "display_name": "张三",
      "username": "zhangsan",
      "total": 10000.0,
      "records": [
        {
          "id": 1,
          "amount": 5000.0,
          "product_id": 2,
          "product_name": "产品A",
          "consume_date": "2026-07-10",
          "created_at": "2026-07-10 14:30:00"
        },
        ...
      ]
    },
    ...
  ]
}
```

权限：所有登录用户可查看。

#### 3.3.2 新增消耗记录

`POST /api/youtube/<vid>/consumption`

```python
# Body: { amount: 5000, product_id: 2, consume_date: "2026-07-10" }
# 自动以当前用户作为 user_id
# 仅 admin/developer 可调用
```

#### 3.3.3 编辑消耗记录

`PUT /api/youtube/<vid>/consumption/<cid>`

```python
# Body: { amount: 6000, product_id: 3, consume_date: "2026-07-11" }
# 仅记录 owner 本人可编辑
```

#### 3.3.4 删除消耗记录

`DELETE /api/youtube/<vid>/consumption/<cid>`

```python
# 仅记录 owner 本人可删除
```

#### 3.3.5 消耗日期标注

`GET /api/youtube/consumption/dates`

```python
# 参数: scope, region, frame_type, ... (与 /api/youtube/dates 一致)
# 返回: { "success": true, "dates": { "2026-07-10": 3, "2026-07-11": 5 } }
# dates 中 key 为日期，value 为该日期有消耗记录的视频数
```

#### 3.3.6 视频列表增加总消耗

修改 `GET /api/youtube/list`，在查询中 LEFT JOIN 消耗汇总：

```sql
SELECT v.*, u.display_name AS owner_display_name, u.username AS owner_username,
       COALESCE(vc.total_consumption, 0) AS total_consumption
FROM videos v
LEFT JOIN users u ON v.owner_id = u.id
LEFT JOIN (
    SELECT video_id, SUM(amount) AS total_consumption 
    FROM video_consumption 
    GROUP BY video_id
) vc ON v.id = vc.video_id
WHERE ...
```

#### 3.3.7 获取当前用户跑的产品（下拉框用）

`GET /api/products/runner-products`

```python
# 返回当前用户作为 runner 的产品列表
# { "success": true, "products": [{ "id": 1, "product_name": "产品A" }, ...] }
```

### 3.4 前端改动

**文件**：[frontend/src/views/YoutubeView.vue](frontend/src/views/YoutubeView.vue)

#### 3.4.1 视频列表 — 总消耗展示

每行视频标题旁显示总消耗金额标签：

```html
<el-tag v-if="row.total_consumption > 0" size="small" type="danger" effect="dark">
  💰 {{ formatAmount(row.total_consumption) }}
</el-tag>
```

放在 `owner_display_name` 标签旁（第 94 行附近）。

#### 3.4.2 视频详情弹窗（新增）

点击视频标题或新增"详情"按钮，打开 `el-dialog`：

```
┌─────────────────────────────────────────────┐
│  视频消耗详情 — [视频标题]                     │
│                                              │
│  📊 总消耗：¥15,000                          │
│                                              │
│  ┌─ 张三 — ¥10,000 ───────────────── [展开] ┐│
│  │  2026-07-10  产品A  ¥5,000   ✏️ 🗑       ││
│  │  2026-07-11  产品B  ¥5,000   ✏️ 🗑       ││
│  └──────────────────────────────────────────┘│
│  ┌─ 李四 — ¥5,000 ────────────────── [展开] ┐│
│  │  2026-07-12  产品A  ¥5,000   ✏️ 🗑       ││
│  └──────────────────────────────────────────┘│
│                                              │
│  ── 录入消耗（仅 admin/developer 可见）──      │
│  金额: [    ]  日期: [📅    ]                │
│  产品: [搜索下拉▼    ]                       │
│  [保存]                                      │
└─────────────────────────────────────────────┘
```

- 明细列表按用户分组，每组可折叠展开
- 每条记录显示：日期、产品名、金额
- 编辑/删除按钮仅记录 owner 可见
- 录入表单仅 admin/developer 可见
- 产品下拉框调用 `/api/products/runner-products`，支持搜索过滤

#### 3.4.3 日期选择器 — 消耗日期标记

在现有日期选择器的 `dateCellClass` 中，同时查询 `/api/youtube/consumption/dates`，有消耗记录的日期也高亮标记（用不同颜色区分导入日期和消耗日期）。

#### 3.4.4 金额格式化

新增工具函数 `formatAmount(amount)`，大于等于 10000 显示为 "1.5万" 格式。

### 3.5 API 前端封装

**文件**：[frontend/src/api/youtube.js](frontend/src/api/youtube.js)

新增方法：

```javascript
// 获取消耗明细
getConsumption(videoId)
// 新增消耗
addConsumption(videoId, { amount, product_id, consume_date })
// 编辑消耗
updateConsumption(videoId, recordId, { amount, product_id, consume_date })
// 删除消耗
deleteConsumption(videoId, recordId)
// 消耗日期
getConsumptionDates(params)
```

---

## 四、涉及文件汇总

| 文件 | 改动内容 |
|------|---------|
| `py/database.py` | 新增 `video_consumption` 表 + 迁移 |
| `py/main.py` | 5 个新接口 + 修改 `/api/youtube/list` 查询 |
| `frontend/src/views/YoutubeView.vue` | 批量 is_public 下拉、导入默认值、消耗展示、详情弹窗、日期标记 |
| `frontend/src/api/youtube.js` | 5 个新 API 方法 |
| `frontend/src/stores/youtube.js` | 消耗相关状态和方法 |

---

## 五、不涉及的部分

- 文案模块（copywritings）不受影响
- 产品管理、账户管理不受影响
- 视频生成、素材管理不受影响
- 已有视频编辑/删除权限逻辑不变
