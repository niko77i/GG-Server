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

在 `config` 表中存储 `ai_analysis` key，JSON 格式：
```json
{
  "enabled": true,
  "provider": "volcano",
  "model": "deepseek-v4-flash",
  "api_key": "<用户提供的key>",
  "endpoint": "https://ark.cn-beijing.volces.com/api/coding"
}
```

### 5.4 错误处理

- API Key 无效 → 返回友好提示"AI 服务配置有误，请检查 API Key"
- 网络超时（10s）→ 规则引擎结论兜底 + 提示"AI 服务响应超时，显示为规则分析结论"
- 模型不存在 → 提示"模型配置错误，请联系管理员"

## 6. 涉及文件清单

| 文件 | 变更类型 | 说明 |
|------|---------|------|
| `py/main.py` | 修改 | 新增 `multi-analysis` 端点 + `multi-ai-chat` 端点；补全 `analyze` 端点 LLM 调用 |
| `py/ai_service.py` | 修改（可选） | 新增 `VolcanoChatProvider` 类，或直接在 main.py 用 requests 调用 |
| `frontend/src/views/AnalysisView.vue` | 修改 | 新增多维分析 tab + 散点图 + 对话区域 + 明细表 |
| `frontend/src/api/reports.js` | 修改 | 新增 `multiAnalysis()` 和 `multiAiChat()` 两个 API 方法 |
| `docs/superpowers/specs/2026-07-03-data-analysis-design.md` | 参考 | 更新设计文档，记录新增 tab |

## 7. 验证方式

1. **后端 API 测试**：用 curl/pytest 调用 `GET /api/ad-reports/multi-analysis`，验证不同参数组合返回正确的聚合数据和统计值
2. **前端散点图**：切换不同 X/Y 轴/分组维度，确认图表正确渲染
3. **规则引擎兜底**：AI 未启用时，确认 insights 正确生成
4. **AI 对话**：启用 AI 后，发送问题确认能正常返回分析结论
5. **维度切换**：修改任何维度参数，确认图表和结论同步更新
6. **与现有功能隔离**：确认仪表盘/趋势/对比 tab 功能不受影响
