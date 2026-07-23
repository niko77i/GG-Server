# 文案管理 + 翻译工具 — 设计规格

**日期**：2026-06-15  
**状态**：待确认

---

## 1. 需求描述

### 1.1 文案管理
在 YouTube 视频管理页面增加**文案管理**功能。文案是独立存在的推广/广告文本（多种语言），与视频无直接关联，只按地区分类。

### 1.2 文案翻译
每条文案可点击「翻译」按钮，实时翻译为目标语言（默认中文），翻译结果展示在原文下方，**不存储**。使用 Google 翻译。

### 1.3 翻译工具（工具集新标签页）
在工具集面板新增独立的翻译工具标签页，支持输入文本 → 选择语言 → 翻译。

---

## 2. 数据结构

### 2.1 数据库新表 `copywritings`

```sql
CREATE TABLE IF NOT EXISTS copywritings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    region TEXT NOT NULL DEFAULT '通用',
    content TEXT NOT NULL,
    created_at TEXT DEFAULT (datetime('now','localtime'))
);
CREATE INDEX IF NOT EXISTS idx_copywritings_region ON copywritings(region);
```

| 字段 | 类型 | 说明 |
|------|------|------|
| id | INTEGER | 自增主键 |
| region | TEXT | 地区，复用标签配置中的地区选项 |
| content | TEXT | 文案文本内容（单条，不分行） |
| created_at | TEXT | 创建时间 |

### 2.2 存储位置
- 存入 `temp/app.db`，由 `database.py` 统一管理建表
- 翻译结果**不存储**，每次实时调用

---

## 3. API 设计

所有路由加在 `py/main.py` 中。

### 3.1 文案 CRUD API

#### 导入文案
```
POST /api/copywriting/import
```
请求：`{"text": "文案第一行\n文案第二行", "region": "巴西"}`
- 按 `\n` 分割，过滤空行，每条一行写入
- 响应：`{"success": true, "imported": 3}`

#### 获取文案列表
```
GET /api/copywriting/list?region=巴西
```
- region 可选，不传返回全部，按 created_at 降序
- 响应：`{"success": true, "items": [...], "counts": {"巴西": 15, "菲律宾": 8}}`

#### 编辑单条
```
POST /api/copywriting/edit
```
`{"id": 1, "region": "巴西", "content": "修改后的文案"}`

#### 批量删除
```
POST /api/copywriting/delete
```
`{"ids": [1, 2, 3]}`

#### 批量修改地区
```
POST /api/copywriting/batch-edit
```
`{"ids": [1, 2, 3], "region": "印尼"}`

### 3.2 翻译 API（新增）

```
POST /api/translate
```
请求：
```json
{
  "text": "Texto em português",
  "target": "zh-CN"
}
```
- 使用 Google 翻译（`deep-translator` 库，免费无需 API Key）
- 响应：`{"success": true, "translated": "葡萄牙语文本", "source": "pt"}`

---

## 4. 前端设计

### 4.1 YouTube 标签页结构调整

现有：`视频展示` | `导入视频` | `标签配置`

调整为：`视频展示` | **`文案展示`** | `导入视频或文案` | `标签配置`

路由新增：
```js
{ path: 'copywriting', component: () => import('../views/YoutubeView.vue'), meta: { title: '文案展示' } }
```

### 4.2 文案展示标签页

- 树形结构（`el-tree`），地区=父节点，文案=子节点
- 父节点显示 `地区名 (N条)`
- 子节点显示：`文案内容截断... [翻译] [✏️] [🗑]`
  - **点击文案文本 → 直接复制到剪贴板**（Toast "已复制 ✓"）
  - 点击 **[翻译]** → 调用翻译 API，在文案下方展开显示翻译结果
  - 翻译结果旁有目标语言选择器（默认中文）
  - 点击 ✏️ → 编辑弹窗
  - 点击 🗑 → 确认删除
- 顶部工具栏：全选、反选、批量删除、批量改地区
- 编辑弹窗：可修改文案内容和所属地区

### 4.3 导入视频或文案标签页

在"导入视频或文案"标签页内，增加子标签切换：

```
┌─ 导入视频或文案 ──────────────────────────┐
│  [导入视频]  [导入文案]                     │  ← 子标签
│                                            │
│  （根据子标签显示对应表单）                   │
└────────────────────────────────────────────┘
```

- **导入视频子标签**：保持现有内容不变
- **导入文案子标签**：
  - 地区选择下拉框（复用 `store.tags.regions`）
  - 文本输入框（textarea，6 行）
  - "导入文案"按钮
  - 提示：每行一条文案，空行自动跳过

### 4.4 工具集 — 翻译工具（新增）

工具集现有：`做表数据` | `音频替换`

调整为：`做表数据` | `音频替换` | **`翻译工具`**

```
┌─ 翻译工具 ───────────────────────────────┐
│  源文本：                                  │
│  [textarea 多行输入]                       │
│                                           │
│  目标语言：[下拉搜索框，filterable]   [翻译] 按钮          │
│                                           │
│  翻译结果：                                │
│  [textarea 只读展示]    [📋 复制] 按钮      │
└───────────────────────────────────────────┘
```

- 目标语言选项：中文(zh-CN)、英语(en)、葡萄牙语(pt)、印尼语(id)、菲律宾语(tl)、西班牙语(es)、日语(ja)、韩语(ko)、泰语(th)、越南语(vi) 等
- 翻译结果支持一键复制
- 复用 `/api/translate` 接口

### 4.5 Store 扩展

在 `stores/youtube.js` 中新增：

```js
// state
copywritings: [],
copywritingCounts: {},

// actions
loadCopywritings(region = ''),
importCopywritings({ text, region }),
editCopywriting({ id, region, content }),
deleteCopywritings(ids),
batchEditCopywritings({ ids, region }),
```

### 4.6 API 模块扩展

在 `api/youtube.js` 中新增：

```js
copywritingApi: {
  list:      (params) => api.get('/list/api/copywriting', { params }),
  import:    (body)   => api.post('/api/copywriting/import', body),
  edit:      (body)   => api.post('/api/copywriting/edit', body),
  delete:    (body)   => api.post('/api/copywriting/delete', body),
  batchEdit: (body)   => api.post('/api/copywriting/batch-edit', body),
},
translateApi: {
  translate: (body) => api.post('/api/translate', body),
}
```

---

## 5. UI 交互细节

### 5.1 文案树形展示
```
📁 巴西 (15条)
  ├── 📄 文案内容预览...              [翻译] [✏️] [🗑]
  │     └─ 🌐 中文翻译结果...          [语言▼] [📋复制]
  ├── 📄 Outra frase em português... [翻译] [✏️] [🗑]
  └── 📄 ...
📁 菲律宾 (8条)
  ├── 📄 ...
  └── 📄 ...
```

- 点击父节点 → 展开/折叠
- 点击文案文本 → 复制原文到剪贴板
- 点击 [翻译] → 调用 API，在下方展开翻译结果
- 翻译结果下方的语言选择器可切换目标语言，切换后自动重新翻译
- 翻译结果旁有复制按钮

### 5.2 批量操作栏
- 全选 / 反选
- 批量删除
- 批量改地区（下拉选择）

### 5.3 导入文案子标签
- 地区下拉框（默认"通用"）
- textarea，placeholder: "每行一条文案，空行自动跳过"
- 导入按钮 + 结果显示

---

## 6. 涉及文件

| 文件 | 改动类型 | 说明 |
|------|---------|------|
| `py/database.py` | 修改 | `_ensure_schema()` 中新增 `copywritings` 表 |
| `py/main.py` | 修改 | 新增 5 个文案 API + 1 个翻译 API |
| `frontend/src/router/index.js` | 修改 | 新增 `/youtube/copywriting` + `/toolkit/translate` 路由 |
| `frontend/src/views/YoutubeView.vue` | 修改 | 新增文案展示标签页 + 导入子标签 + 翻译交互 |
| `frontend/src/views/ToolkitView.vue` | 修改 | 新增翻译工具标签页 |
| `frontend/src/stores/youtube.js` | 修改 | 新增文案相关 state/actions |
| `frontend/src/api/youtube.js` | 修改 | 新增文案 API + 翻译 API |
| `requirements.txt` | 可能修改 | 如需安装 `deep-translator` |

---

## 7. 不变更项

- 现有的视频展示、导入视频、标签配置功能**完全不动**
- 现有的 YouTube API 路由**完全不动**
- 现有的做表数据、音频替换功能**完全不动**
- 数据库已有表结构**完全不动**

---

## 实际代码逻辑补充（2026-07-23 审计）

以下记录实际实现与设计文档之间的差异，按模块逐一对比。

### 8. 数据库表结构差异

设计文档中 `copywritings` 表仅含 4 列（id, region, content, created_at），实际建表语句（`py/database.py:248-256`）多了 3 列：

```sql
CREATE TABLE IF NOT EXISTS copywritings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    region TEXT NOT NULL DEFAULT '通用',
    content TEXT NOT NULL,
    owner_id INTEGER REFERENCES users(id),        -- 新增：归属用户
    effectiveness TEXT DEFAULT '',                  -- 新增：成效标签（"成效"/""）
    is_public INTEGER DEFAULT 0,                    -- 新增：是否公开（0=私有, 1=公开）
    created_at TEXT DEFAULT (datetime('now','localtime'))
);
```

其中 `owner_id`、`effectiveness`、`is_public` 三列是通过 `_add_column_if_missing()` 在旧表上增量补加的（`py/database.py:114-116`），而非一次建表完成。

### 9. API 实际逻辑差异

所有文案 CRUD API 均加了 `@jwt_required()` 认证装饰器，设计文档未提及。翻译 API（`/api/translate`）未加认证，与设计一致。

#### 9.1 POST /api/copywriting/import — 参数扩展

设计只接收 `text` + `region`。实际额外接收：

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `effectiveness` | string | `""` | 成效标签，写入每条文案 |
| `is_public` | int | `0` | 公开标记，写入每条文案 |

每条文案 INSERT 时同时写入 `owner_id`（当前登录用户）。

#### 9.2 GET /api/copywriting/list — scope 过滤 + 排序变更

设计只支持 `?region=` 参数。实际额外支持：

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `scope` | string | `"private"` | 可见范围：`public` / `private` / `all` |

scope 逻辑由 `_scope_where()` 函数（`py/main.py:162-170`）实现：
- `public`: `is_public = 1`
- `private`: `owner_id = ?`（只看自己的）
- `all`: `is_public = 1 OR owner_id = ?`（自己的 + 公开的）

排序逻辑与设计不同。设计是 `ORDER BY created_at DESC`；实际是：
```sql
ORDER BY CASE cw.effectiveness WHEN '成效' THEN 0 ELSE 1 END, cw.created_at DESC
```
即标记为"成效"的文案优先排在前面，同组内再按创建时间降序。

#### 9.3 POST /api/copywriting/edit — 增加成效字段 + 权限校验

设计允许编辑 `region` 和 `content`。实际额外允许编辑 `effectiveness`。

增加了 `_can_modify()` 权限检查（`py/main.py:1768-1789`）：
- admin/developer：始终有权限
- 普通用户：仅可编辑 `owner_id == 自己` 或 `is_public == 1` 的文案

#### 9.4 POST /api/copywriting/delete — 权限分级

设计无权限逻辑。实际实现了分级删除：
- admin/developer：`DELETE FROM copywritings WHERE id=?`（无限制）
- 普通用户：`DELETE FROM copywritings WHERE id=? AND (owner_id=? OR is_public=1)`（只能删自己的或公开的）

#### 9.5 POST /api/copywriting/batch-edit — 增加成效批量修改

设计只支持批量改 `region`。实际额外支持批量改 `effectiveness`。

请求体扩展：
```json
{
  "ids": [1, 2, 3],
  "region": "印尼",          // 可选
  "effectiveness": "成效"     // 可选（新增）
}
```
至少需要提供 `region` 或 `effectiveness` 之一，否则返回 400。

权限逻辑同 delete API 的分级策略。

#### 9.6 POST /api/translate — 响应缺少 source 字段

设计文档中翻译 API 的响应示例包含 `"source": "pt"`（自动检测到的源语言）。实际响应为：
```json
{"success": true, "translated": "葡萄牙语文本"}
```
**不包含 `source` 字段**。`deep-translator` 的 `GoogleTranslator(source='auto', target=target)` 调用后未提取并返回源语言检测结果。

### 10. 前端实际逻辑差异

#### 10.1 文案展示方式：从树形改为扁平表格 + 地区标签页

设计文档要求使用 `el-tree` 树形结构展示（地区=父节点，文案=子节点）。实际实现（`CopywritingTab.vue`）使用 `el-table` 扁平表格 + 顶部地区标签页按钮（`regionTabs`）进行过滤。

- 每个表格行展示完整信息：成效标签 + 地区标签 + 文案内容 + 操作按钮
- 点击地区标签页按钮过滤显示，而非展开/折叠树节点

注意：`YoutubeView.vue` 中保留了旧的 `copywritingTree` computed 属性和相关函数（`cwSelectable`、`cwRowClass` 等），但 `CopywritingTab.vue` 组件内部并不使用它们——这些是重构抽取组件过程中遗留的未清理代码。

#### 10.2 CopywritingTab 为独立组件

设计文档将文案展示逻辑写在 `YoutubeView.vue` 内部。实际拆分为独立组件 `frontend/src/components/youtube/CopywritingTab.vue`，通过 `ref` 引用并暴露 `loadCopywritings()` 方法供父组件在 tab 切换时调用刷新。

#### 10.3 可见范围切换

工具栏顶部增加了"公用/私有" scope 切换（仅 admin 可见），对应 `store.cwScope` 状态。切换后自动重新加载文案列表。

非 admin 用户在 `onMounted` 时强制设为 `cwScope = 'public'`。

#### 10.4 成效标签贯穿全流程

设计文档未提及"成效"概念，实际中它贯穿了：
- **表格展示**：每行以 `el-tag` 显示成效，成效=success 色，其他=warning 色
- **编辑弹窗**：增加成效下拉选择框（`store.tags.effectiveness`）
- **批量操作**：增加"批量改成效"下拉框
- **导入文案**：增加成效下拉选择框（可选）
- **排序**：成效文案优先显示

#### 10.5 权限控制

操作按钮（✏️编辑、🗑删除）通过 `canModifyCopywriting(row)` 控制显示：
```js
return authStore.isAdmin || row.owner_id === authStore.user?.id || row.is_public
```
即仅 admin 或文案归属人可操作，普通用户不可编辑/删除他人的私有文案。

#### 10.6 语言列表差异

设计文档列出的翻译目标语言：`zh-CN, en, pt, id, tl, es, ja, ko, th, vi`（10 种）

`CopywritingTab.vue` 中的 `CW_LANGS`（13 种）：
`zh-CN, en, ja, ko, pt, es, fr, de, ru, ar, hi, th, vi`

差异：实际增加了 `fr, de, ru, ar, hi`，去掉了 `id, tl`。

`ToolkitView.vue` 翻译工具中的 `TL_LANGS`（10 种）则与设计文档一致：
`zh-CN, en, pt, id, tl, es, ja, ko, th, vi`

**两处语言列表不一致**，需关注。

#### 10.7 导入文案表单扩展

`ImportTab.vue` 中导入文案子标签比设计多了两项：
- **成效下拉框**（可选，复用 `store.tags.effectiveness`）
- **可见范围切换**：私有 / 公开（仅 admin 可切换，普通用户默认公开）

#### 10.8 页面标题变更

`YoutubeView.vue` 页面标题从"Youtube视频管理"改为"**视频 文案管理**"，反映了文案管理功能的加入。

#### 10.9 API 调用路径

设计文档中 list 接口路径写为 `/list/api/copywriting`（疑似笔误），实际 `api/youtube.js` 中为：
```js
list: (params) => api.get('/copywriting/list', { params }),
```

其他接口路径设计文档与代码一致（均以 `/api/copywriting/` 为前缀，`/api/translate` 为翻译端点）。

### 11. 总结：设计 vs 实现差异清单

| 维度 | 设计文档 | 实际代码 | 影响 |
|------|---------|---------|------|
| 数据库列数 | 4 列 | 7 列（+owner_id, effectiveness, is_public） | 核心差异，引入了多用户与权限体系 |
| 认证 | 未提及 | 所有 CRUD API 需要 JWT | 安全增强 |
| 权限模型 | 无 | 三级：admin / 本人 / 公开 | 多用户协作的基础 |
| scope 过滤 | 无 | public/private/all | 配合权限的可见范围控制 |
| 成效标签 | 无 | 全流程支持 | 业务需求扩展 |
| 展示组件 | el-tree | el-table + region tabs | UI 实现方案变更 |
| 翻译响应 | 含 source 字段 | 不含 source 字段 | 缺失源语言检测 |
| 语言列表 | 两处统一 | CopywritingTab 与 ToolkitView 不一致 | 需统一 |
| 排序逻辑 | created_at DESC | 成效优先 + created_at DESC | 业务优先级调整 |
