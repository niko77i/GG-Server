# 多维分析与 AI 智能解读 — 设计文档

> 日期：2026-07-03
> 需求：在现有数据分析看板中新增"多维分析"能力，支持自由维度组合、指标关系探索（散点图+相关性）、AI 智能解读和对话分析。

## 1. 需求描述

当前分析看板只能按 product_name 或 campaign 两个固定维度查看数据，无法分析：

1. **账户维度**：不同账户对同一产品/包的效果差异
2. **指标关系**：花费、CPI、CTR 等指标之间是否存在相关性
3. **智能解读**：看到数据后，需要人工判断好坏，缺乏自动结论

本次新增"多维分析"tab，实现自由维度组合、散点图关系探索、AI 智能解读与对话分析。

## 2. 核心原则

- **自由度优先**：所有维度/指标参数均可选可组合，不固化分析路径
- **AI 优先**：AI 启用时用 AI 生成结论，未启用时用规则引擎兜底
- **纯增量**：新增 tab 和 API，不修改现有仪表盘/趋势/对比的逻辑

## 3. 后端设计

### 3.1 新增端点：`GET /api/ad-reports/multi-analysis`

**参数**（全部可选，自由组合）：

| 参数 | 类型 | 说明 | 可选值 |
|------|------|------|--------|
| `x_axis` | string | X 轴指标，默认 `cost` | `cost` / `cpi` / `ctr` / `cvr` / `installs` / `impressions` / `clicks` |
| `y_axis` | string | Y 轴指标，默认 `cpi` | 同上 |
| `size_by` | string | 气泡大小指标，默认不传（统一大小） | 同上，传了则按值映射气泡半径 |
| `group_by` | string | 分组维度，默认 `account` | `product_name` / `campaign` / `account` / `customer_id` |
| `product_name` | string | 筛选产品 | 可选 |
| `campaign` | string | 筛选包/系列 | 可选 |
| `account` | string | 筛选账户名 | 可选 |
| `region` | string | 筛选地区 | 可选 |
| `from_date` | string | 开始日期 | YYYY-MM-DD |
| `to_date` | string | 结束日期 | YYYY-MM-DD |

**SQL 聚合逻辑**：

- `group_col` 根据 `group_by` 动态映射：`product_name` → `product_name`，`campaign` → `campaign`，`account` → `account`，`customer_id` → `customer_id`
- WHERE 子句复用现有模式（`user_id` + 动态条件拼接），新增 `campaign` / `account` 筛选支持
- SELECT：`SUM(cost)`, `SUM(impressions)`, `SUM(clicks)`, `SUM(installs)`, `SUM(in_app_actions)`，GROUP BY `group_col`
- Python 端计算派生指标：CPI、CTR、CVR

**统计计算**（Python 端）：

- X/Y 轴的均值、中位数
- Pearson 相关系数（X 和 Y 之间）
- 样本数量
- 各点的百分位排名

**规则引擎 insights 生成**（Python 端，无 AI 时使用）：

| 规则 | 触发条件 | 输出模板 |
|------|---------|---------|
| CPI 异常高 | 某点 CPI > 均值 × 1.5 | `"{name} 的 CPI(${cpi}) 高于均值(${avg}) {pct}%，位于异常区"` |
| 花费集中 | 某点花费 > 总花费 × 0.6 | `"{name} 消耗了 {pct}% 的预算，CTR 为 {ctr}%，需关注投入产出比"` |
| 高花费低 CTR | 花费 > 均值 × 1.5 且 CTR < 均值 | `"{name} 花费高但 CTR 低于均值，可能存在投放效率问题"` |
| 低 CPI 高效率 | CPI 在最低 20% 分位 | `"{name} CPI ${cpi}，处于最优区间"` |
| 相关性结论 | 相关系数 r | `"{x_label} 与 {y_label} 呈{r_desc}(r={r})，{implication}"` |

**返回结构**：

```json
{
  "success": true,
  "points": [
    {
      "name": "string",
      "group": "string (group_by的值)",
      "x": 5000,
      "y": 2.5,
      "size": 0.03,
      "x_label": "花费",
      "y_label": "CPI",
      "detail": {
        "total_cost": 5000,
        "total_installs": 2000,
        "total_in_app": 2000,
        "avg_cpi": 2.5,
        "ctr": 0.03,
        "cvr": 0.05,
        "total_impressions": 100000,
        "total_clicks": 3000
      }
    }
  ],
  "stats": {
    "x_avg": 3500,
    "x_median": 3200,
    "y_avg": 2.1,
    "y_median": 2.0,
    "correlation": 0.35,
    "sample_count": 15,
    "x_label": "花费",
    "y_label": "CPI"
  },
  "insights": [
    "账户A的 CPI($3.2) 高于均值($2.1) 52%，位于异常区",
    "花费与CPI呈弱正相关(r=0.35)，未观测到明显的规模效应"
  ]
}
```

### 3.2 增强：补全 AI 分析端点

**现有端点**：`POST /api/ad-reports/analyze`（当前为占位实现）

**改造内容**：

1. 从 `config` 表读取 `ai_analysis` 配置：
   ```json
   {
     "enabled": true,
     "provider": "volcano",
     "model": "deepseek-v4-flash",
     "api_key": "xxx",
     "endpoint": "https://ark.cn-beijing.volces.com/api/coding"
   }
   ```

2. 收到请求时：收集当前筛选条件下的聚合数据，拼接 prompt：
   ```
   你是一个广告投放数据分析师。以下是用户在 GG-Server 中的广告数据：

   筛选条件：产品={product_name}, 日期={from_date}~{to_date}
   聚合维度：{group_by}
   数据摘要：
   - 总花费: ${total_cost}
   - 总安装: {total_installs}
   - 平均 CPI: ${avg_cpi}
   - 平均 CTR: {avg_ctr}%
   - 各分组明细: (表格格式附上)

   用户问题：{question}

   请用中文回答，简洁明确，指出问题和可执行的建议。
   ```

3. 调用火山方舟 API：
   ```
   POST {endpoint}/chat/completions  (注意：用户提供的地址是 .../api/coding，需确认实际 chat completions 路径)
   Authorization: Bearer {api_key}
   Body: { "model": "deepseek-v4-flash", "messages": [...] }
   ```

4. 返回 `{ success: true, enabled: true, answer: "AI 回复内容" }`

5. **无 AI 时**：`enabled: false` 时返回空 answer + 规则引擎 insights（由 multi-analysis 端点的 insights 字段兜底）

### 3.3 新增端点：`GET /api/ad-reports/multi-ai-chat`

对话式分析端点，支持多轮对话上下文。

**参数**：

| 参数 | 说明 |
|------|------|
| `question` | 用户问题 |
| `context` | 当前多维分析的数据摘要 JSON（前端传入） |
| `history` | 对话历史（可选，前端维护） |

**返回**：`{ success: true, answer: "..." }`

> 注：如果后续需要流式输出，可改为 SSE。首版先做非流式。

### 3.4 新增端点：`POST /api/ad-reports/multi-analysis`

支持临时数据对比的 POST 版本。GET 只能查历史数据，POST 可以传入 `extra_rows` 做历史+新增对比。

**请求体**：
```json
{
  "params": { "x_axis": "cost", "y_axis": "cpi", "group_by": "account", ... },
  "extra_rows": [
    { "account": "xxx", "customerId": "xxx", "campaign": "xxx", "cost": 100, "impressions": 1000, ... }
  ]
}
```

**后端逻辑**：
1. 用 `params` 查询历史数据并聚合（同 GET 逻辑）
2. 用 `extra_rows` 在 Python 内存中按 `group_by` 维度聚合
3. 计算 combined stats（历史+新增合并）
4. 返回 `{ historical: [...points], new: [...points], points: [...all], stats, insights }`

**注意**：`extra_rows` 只用于临时分析，不写入数据库。

### 3.5 数据清洗工具函数

从 ToolkitView 的 `zbProcess` 提取纯函数到 `frontend/src/utils/adsParser.js`：

```js
export function parseAdsData(rawText, { isYanghu = false, includeCampaignId = false } = {}) {
  // 返回 { raw: [...], zuobiao: [...], kehu: [...] }
}
```

ToolkitView 和多维分析共用此函数。

## 4. 前端设计

### 4.1 新增 Tab

位置在"对比"和"跨用户"之间：

```
📊 仪表盘 | 📈 趋势 | 📋 对比 | 🔬 多维分析 | 👥 跨用户 | 🤖 AI分析
```

### 4.2 页面布局

```
┌─────────────────────────────────────────────────┐
│  维度配置栏                                       │
│  X轴: [花费 ▼]  Y轴: [CPI ▼]  气泡: [无 ▼]       │
│  分组: [账户 ▼]  产品: [全部 ▼]  包: [全部 ▼]      │
│  账户: [全部 ▼]  地区: [全部 ▼]                    │
│                              [🔄 刷新]            │
├─────────────────────────────────────────────────┤
│                                                   │
│          ECharts 散点图 / 气泡图 (400px)           │
│      • 每个点 = 一个分组单元（按 group_by）         │
│      • hover 显示 tooltip：名称 + 核心指标         │
│      • 坐标轴标签根据 x_axis/y_axis 动态变化        │
│                                                   │
├─────────────────────────────────────────────────┤
│  📊 分析结论                                      │
│  ┌─────────────────────────────────────────────┐ │
│  │ AI 已启用时：自动生成首轮 AI 分析结论          │ │
│  │ "根据当前数据，共有 {n} 个分组……"             │ │
│  │                                              │ │
│  │ AI 未启用时：显示规则引擎 insights             │ │
│  │ · 账户A CPI $3.2，高于均值 52%               │ │
│  └─────────────────────────────────────────────┘ │
├─────────────────────────────────────────────────┤
│  💬 对话分析                                      │
│  ┌─────────────────────────────────────────────┐ │
│  │ (消息列表，和现有 AI分析 tab 风格一致)         │ │
│  │ 用户: 哪些账户的投放效率最高？                 │ │
│  │ AI: 根据 CPI 和 CTR 综合评估……               │ │
│  └─────────────────────────────────────────────┘ │
│  [输入问题...]                          [发送]    │
├─────────────────────────────────────────────────┤
│  📋 数据明细表 (可折叠，默认展开)                  │
│  [名称] [花费] [安装] [CPI] [CTR] [CVR] [展示]    │
│  [点击] [应用内操作]                              │
│  (支持排序)                                      │
└─────────────────────────────────────────────────┘
```

### 4.3 组件复用

- **散点图**：复用现有趋势图的 ECharts 初始化模式（`echarts.init` + `_echart` 缓存），改用 `scatter` 类型
- **对话区域**：复用现有 AI 分析 tab 的消息渲染样式（蓝色用户气泡 / 白色 AI 气泡）
- **统计卡片**：复用 `.stat-card` CSS 类
- **表格**：复用 Element Plus `el-table`，和仪表盘表格风格一致
- **筛选参数**：复用现有 `filterParams()` 函数，新增账户维度参数

### 4.4 新增 ref 变量

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `multiXAxis` | `'cost'` | X 轴指标 |
| `multiYAxis` | `'cpi'` | Y 轴指标 |
| `multiSizeBy` | `''` | 气泡大小指标（空=统一大小） |
| `multiGroupBy` | `'account'` | 分组维度 |
| `multiFilterCampaign` | `''` | 包筛选 |
| `multiFilterAccount` | `''` | 账户筛选 |
| `multiPoints` | `[]` | 散点图数据 |
| `multiStats` | `null` | 统计数据 |
| `multiInsights` | `[]` | 分析结论 |
| `multiChatMessages` | `[]` | 对话消息 |
| `multiChatQuestion` | `''` | 输入框内容 |
| `multiChatLoading` | `false` | AI 对话加载状态 |
| `multiTableVisible` | `true` | 明细表折叠状态 |

### 4.5 交互逻辑

1. **加载流程**：切换到多维分析 tab 时 → `loadMultiAnalysis()` → 获取数据 + 渲染图表 + 显示结论
2. **AI 自动分析**：数据加载完成后，如果 AI 已启用，自动调 `multi-ai-chat` 生成首轮结论
3. **维度切换**：任何维度参数变化 → 自动重新加载（debounce 300ms 或手动刷新按钮）
4. **图表点击**：点击散点图中的点 → 表格滚动并高亮对应行
5. **AI 对话**：输入问题后发送 → 带上当前数据上下文 + 历史消息 → 非流式返回答案
6. **无 AI 时**：规则引擎 insights 替代 AI 结论，对话区域显示"AI 分析未启用"

## 5. AI 接入方案

### 5.1 模型配置

- **提供商**：火山方舟（Ark）
- **模型**：`deepseek-v4-flash`
- **Endpoint**：`https://ark.cn-beijing.volces.com/api/coding`

### 5.2 API 调用方式

需确认火山方舟的实际 chat completions 路径。标准火山方舟 API 路径通常是：
- `/api/v3/chat/completions`（如果 endpoint 是 `https://ark.cn-beijing.volces.com/api/coding`，完整 URL 可能是 `https://ark.cn-beijing.volces.com/api/coding/v3/chat/completions` 或类似格式）

实现时在 `py/ai_service.py` 中新增 `VolcanoChatProvider` 类，或在 `main.py` 中直接调用 requests。

### 5.3 配置存储

在 `config` 表中按用户隔离存储，key 格式为 `ai_analysis_{user_id}`，JSON 格式：
```json
{
  "enabled": true,
  "provider": "volcano",
  "model": "deepseek-v4-flash",
  "api_key": "<用户提供的key>",
  "endpoint": "https://ark.cn-beijing.volces.com/api/coding/v3/chat/completions"
}
```

提供 `GET/POST /api/config/ai` 端点供前端读写。AI 分析 tab 内可直接配置，无需手动操作数据库。

### 5.4 错误处理

- API Key 无效 → 返回友好提示"AI 服务配置有误，请检查 API Key"
- 网络超时（10s）→ 规则引擎结论兜底 + 提示"AI 服务响应超时，显示为规则分析结论"
- 模型不存在 → 提示"模型配置错误，请联系管理员"

## 6. 涉及文件清单

| 文件 | 变更类型 | 说明 |
|------|---------|------|
| `py/main.py` | 修改 | 新增 `GET/POST multi-analysis` + `multi-ai-chat` 端点；补全 `analyze` 端点 LLM 调用；新增 `config/ai` 端点 |
| `frontend/src/views/AnalysisView.vue` | 修改 | 新增多维分析 tab（散点图+粘贴对比+双色图表+AI结论+对话+明细表） |
| `frontend/src/views/ToolkitView.vue` | 修改 | 改用共享的数据解析函数 `parseAdsData` |
| `frontend/src/utils/adsParser.js` | **新建** | 从 ToolkitView 提取的共享数据清洗函数 |
| `frontend/src/api/reports.js` | 修改 | 新增 `multiAnalysis()`, `multiAnalysisPost()`, `multiAiChat()` |
| `py/tests/test_ad_reports.py` | 修改 | 新增 9 个多维分析测试 |

## 7. 验证方式

1. **后端 API 测试**：27 个 pytest 全部通过
2. **前端散点图**：切换不同 X/Y 轴/分组维度，图表正确渲染
3. **按天拆分**：勾选后每个点=一天数据，散点图正确显示
4. **粘贴对比**：粘贴原始数据 → 解析 → 加入对比 → 散点图显示蓝色(历史)+红色(新增)
5. **规则引擎**：无 AI 时自动显示异常值、相关性等结论
6. **AI 解读**：点击按钮后正确调用火山方舟 deepseek-v4-flash
7. **AI 配置**：按用户隔离，AI分析tab内直接配置

---

## 实际代码逻辑补充（2026-07-23 审计）

以下记录了设计文档与实际代码实现之间的差异，以及设计文档中未覆盖的实现细节。

### 一、GET `/api/ad-reports/multi-analysis` — 设计遗漏

#### 1.1 新增参数 `split_by_date`

设计文档未提及此参数。实际代码已完整实现：

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `split_by_date` | string/bool | `"0"` | 是否按天拆分分组。传 `"1"` 后每个数据点 = 一个分组单元在某一天的数据，点名称格式变为 `"{分组名} (YYYY-MM-DD)"` |

启用后 SQL 变为 `GROUP BY {group_col}, report_date ORDER BY report_date`，新增 `report_date` 字段。

#### 1.2 返回结构中多了 `campaign_options` 和 `account_options`

设计文档的返回结构仅包含 `points`、`stats`、`insights`。实际返回额外包含：

```json
{
  "campaign_options": ["campaign_a", "campaign_b"],
  "account_options": ["account_x", "account_y"]
}
```

这两个数组实现了**筛选器联动**：选定产品后，包名下拉和账户下拉自动限定为该产品下有数据的选项。联动链为：产品 → 包名 → 账户（单向，上层过滤下层）。

#### 1.3 `product_name` / `campaign` / `account` 参数支持逗号分隔多值

设计文档将这些参数描述为单个值。实际代码中，后端 `_append_multi` 函数支持逗号分隔多值（如 `product_name=A,B`），自动转换为 `IN (?,?)` 的 SQL 查询。前端 `multiFilterProduct` 也是多选数组，通过 `.join(',')` 传给后端。

#### 1.4 `group_col_map` 缺少 `customer_id` 的中文名映射

设计文档 group_by 可选值列表中未列出 `customer_id`，但实际代码中 `group_col_map` 已包含 `"customer_id": "customer_id"`。

#### 1.5 指标计算函数差异

设计文档中 CPI 用 `cost / installs`，实际代码用 `cost / max(in_app_actions, 1)`。CPI 的分母是 `in_app_actions`（应用内操作），而非 `installs`（安装数）。

#### 1.6 点数据的 `size` 字段

- 如果没传 `size_by`，后端返回 `size = 1.0`
- 如果传了 `size_by`，后端将对应指标的原始值存入 `size`（保留 6 位小数），前端用 `Math.max(8, Math.min(60, Math.sqrt(val[2]) * 30))` 将原始值映射为像素半径

### 二、POST `/api/ad-reports/multi-analysis` — 设计遗漏

#### 2.1 返回的点数据多了 `source` 字段

POST 版本返回的每个 point 多了 `"source": "历史"` 或 `"source": "新增"` 字段，用于前端区分数据来源并在图表中着色。

#### 2.2 `extra_rows` 聚合兼容驼峰字段名

`_agg_rows` 函数在读取 `extra_rows` 时做了特殊处理：

```python
groups[key]["total_in_app"] += float(r.get("inAppActions", 0)) if isinstance(r, dict) else (r["in_app_actions"] or 0)
```

这意味着 `extra_rows` 支持两种字段命名风格：后端习惯的蛇形（`in_app_actions`）和前端粘贴解析的驼峰（`inAppActions`）。

#### 2.3 POST 版 insights 文案比 GET 版更简略

GET 版 CPI 异常 insight 末尾带"建议排查投放策略"，POST 版没有。同样，"需关注投入产出比"和"可能存在投放效率问题"在 POST 版中也被省略。

### 三、`/api/ad-reports/multi-ai-chat` — 设计遗漏

#### 3.1 context 参数结构明确化

设计文档描述 `context` 为"数据摘要 JSON"。实际代码中，前端传入的具体结构是：

```json
{
  "points": [{ "name": "...", "detail": { "total_cost": ..., "avg_cpi": ..., "ctr": ..., "cvr": ..., "total_installs": ... } }],
  "stats": { "x_label": "...", "x_avg": ..., "y_label": "...", "y_avg": ..., "correlation": ... },
  "x_axis": "cost",
  "y_axis": "cpi",
  "group_by": "account"
}
```

后端从 `context.points`、`context.stats` 中提取具体字段拼接文本摘要，不依赖前端预处理。

#### 3.2 history 截断

`history` 参数在后端被截断为最近 10 轮（`history[-10:]`），前端也做了一次 `slice(-10)`。双重保护。

#### 3.3 超时时间

设计文档说"网络超时 10s"，实际代码中 `timeout=30`（30 秒）。

#### 3.4 AI 未启用时的返回

设计文档说 AI 未启用时"返回空 answer + 规则引擎 insights 兜底"。实际代码中，`enabled: false` 时直接返回：

```json
{ "success": true, "enabled": false, "answer": "AI 分析未启用，请联系管理员在系统配置中开启。" }
```

不会回退到规则引擎。

### 四、`/api/ad-reports/analyze` — 设计遗漏

#### 4.1 接收参数结构

设计文档说"收集当前筛选条件下的聚合数据"。实际代码中接收 `filters` 对象（含 `product_name`、`region`、`from_date`、`to_date`），从数据库查询聚合摘要（总花费/展示/点击/安装/应用内操作/平均 CPI/平均 CTR），拼入上下文。

#### 4.2 返回 `provider` 字段

实际返回中多了 `"provider": "atlas"` 或 `"volcano"` 字段。

### 五、前端 AnalysisView.vue — 设计遗漏

#### 5.1 多维分析 tab 首次进入自动继承全局产品筛选

`watch(activeTab)` 中，切换到 `multi` 时，如果 `multiFilterProduct` 为空且全局 `filterProduct` 有值，则自动赋值为 `filterProduct.value[0]`（取第一个产品）。

#### 5.2 全局产品/地区变化时联动重置多维筛选器

`watch(filterRegion)` 和 `watch(filterProduct)` 中会重置 `multiFilterCampaign` 和 `multiFilterAccount`，并触发 `loadMultiAnalysis()`。

#### 5.3 `multiProductOptions` computed 联动

多维 tab 的产品下拉选项 `multiProductOptions` 是 computed 属性：如果全局选了产品则只显示全局选中的产品，否则显示全部产品（`filterProducts.value`）。

#### 5.4 AI 解读是手动触发而非自动

设计文档说"数据加载完成后，如果 AI 已启用，自动调 multi-ai-chat 生成首轮结论"。实际实现中需要用户**手动点击"🤖 AI 解读"按钮**才会触发 `autoAiAnalysis()`。`loadMultiAnalysis()` 结尾不调用 `autoAiAnalysis()`。

#### 5.5 图表点击交互未实现

设计文档说"点击散点图中的点 → 表格滚动并高亮对应行"，实际代码中 ECharts 散点图未绑定任何 click 事件。

#### 5.6 维度切换无 debounce

设计文档说"维度参数变化 → 自动重新加载（debounce 300ms）"。实际代码中 `@change` 直接调用 `loadMultiAnalysis()`，无防抖。

#### 5.7 粘贴对比区的完整 UI

设计文档仅在高层次提到 POST 版本，实际前端有一整套粘贴对比工作流：

1. 点击"📋 粘贴实时数据"展开折叠区
2. 在 textarea 中粘贴 Google Ads 竖排原始数据
3. 可选勾选"含广告系列ID（11列）"
4. 点击"🔍 解析数据"调用 `parseAdsData`
5. 显示解析结果条数或错误信息
6. 解析成功后可打开 `el-switch` 开关"加入对比"
7. 对比模式下：蓝色圆形 = 历史数据，红色菱形 = 新增数据
8. 关闭开关 → 恢复纯历史数据视图

#### 5.8 新增 ref 变量（设计文档遗漏的）

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `multiFilterProduct` | `[]` | 多维 tab 的产品筛选（多选数组，非单值） |
| `multiSplitDate` | `false` | 按天拆分开关 |
| `multiCampaignOptions` | `[]` | 联动包名选项 |
| `multiAccountOptions` | `[]` | 联动账户选项 |
| `multiLoaded` | `false` | 加载完成标记 |
| `multiChart` | `null` | ECharts DOM ref |
| `multiTableData` | computed | 明细表数据（从 points 提取 detail + source） |
| `multiAiMessages` | `[]` | AI 自动解读结论（首次 AI 解读按钮触发） |
| `multiShowPaste` | `false` | 粘贴区展开/折叠 |
| `multiPasteRaw` | `''` | 粘贴的原始文本 |
| `multiPasteCampaignId` | `false` | 是否含广告系列ID |
| `multiParsedRows` | `[]` | 解析后的行数据 |
| `multiParseError` | `''` | 解析错误信息 |
| `multiParseLoading` | `false` | 解析加载状态 |
| `multiCompareOn` | `false` | 对比模式开关 |
| `multiHistPoints` | `[]` | 历史数据点 |
| `multiNewPoints` | `[]` | 新增数据点 |

#### 5.9 `multiChatMessages` vs `multiChatHistory`

设计文档列了 `multiChatMessages` 用于"对话消息"，但实际代码中分解为两个职责：
- `multiAiMessages`：AI 自动解读生成的首条结论（"🤖 AI 解读"按钮触发）
- `multiChatHistory`：对话分析区的多轮对话历史（"💬 对话分析"区域）

#### 5.10 无 AI 时行为

设计文档说"对话区域显示'AI 分析未启用'"。实际代码中对话区域整块被 `v-if="aiEnabled"` 控制，AI 未启用时直接不渲染对话区。只有规则引擎 insights（`multiInsights`）仍然显示。

### 六、规则引擎 — 设计遗漏

#### 6.1 未实现的规则

设计文档列了 5 条规则，实际代码只实现了 4 条。**第 4 条"低 CPI 高效率"规则未实现**：

| 规则 | 设计状态 | 实际状态 |
|------|---------|---------|
| CPI 异常高 | 有 | 已实现 |
| 花费集中 | 有 | 已实现 |
| 高花费低 CTR | 有 | 已实现 |
| 低 CPI 高效率 | 有 | **未实现** |
| 相关性结论 | 有 | 已实现 |

#### 6.2 规则触发条件与文案差异

- "CPI 异常高"规则增加了 `y_axis == "cpi"` 的前置条件检查
- "高花费低 CTR"规则增加了 `x_axis == "cost"` 的前置条件检查
- 实际文案与设计文档有措辞差异（见上文第二节 2.3）

### 七、AI 配置 — 设计遗漏

#### 7.1 `config/ai` 端点的实际实现

设计文档说提供 `GET/POST /api/config/ai` 端点。实际已完整实现：

- **GET** `/api/config/ai`：从 `config` 表读取 `key='ai_analysis_{user_id}'`，不存在时返回默认配置（`enabled: false`）
- **POST** `/api/config/ai`：用 `INSERT OR REPLACE INTO config` 存储，强制覆盖 `enabled`、`provider`、`model`、`api_key`、`endpoint` 五个字段

#### 7.2 AI 分析 tab 的双模式状态机

`aiEnabled` 是一个三态变量：`null`（加载中）、`false`（未启用）、`true`（已启用）。

- `null` → 显示"加载中..."
- `false` → 显示配置表单（API Key / 模型 / Endpoint + 保存按钮）
- `true` → 显示对话界面 + 可折叠配置面板

`checkAIEnabled()` 通过向 `/ad-reports/analyze` 发空问题来探测是否启用（因为 `/config/ai` GET 只返回配置，analyze 端点会实际校验 enabled 字段）。

### 八、`adsParser.js` 公用模块

设计文档指定新建 `frontend/src/utils/adsParser.js`。该文件已存在并被两处引用：
- `ToolkitView.vue` 的数据清洗流程
- `AnalysisView.vue` 多维分析 tab 的粘贴解析（`parsePastedData` 函数调用 `parseAdsData(multiPasteRaw.value, { includeCampaignId: multiPasteCampaignId.value })`）

### 九、tab 顺序

实际 tab 排列与设计文档一致：仪表盘 → 趋势 → 对比 → 多维分析 → 跨用户 → AI分析。

### 十、涉及文件清单修正

设计文档文件清单与实际变更的差异：

| 文件 | 设计文档状态 | 实际状态 |
|------|------------|---------|
| `py/main.py` | 修改 | 已实现 |
| `frontend/src/views/AnalysisView.vue` | 修改 | 已实现（实际比设计更复杂） |
| `frontend/src/views/ToolkitView.vue` | 修改 | 已改用 `parseAdsData` |
| `frontend/src/utils/adsParser.js` | 新建 | 已存在 |
| `frontend/src/api/reports.js` | 修改 | 已实现（多出 `analyze` 和 `crossUser`） |
| `py/tests/test_ad_reports.py` | 修改 | 待验证 |
