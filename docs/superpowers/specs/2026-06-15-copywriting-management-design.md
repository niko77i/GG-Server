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
