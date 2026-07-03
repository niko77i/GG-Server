# 数据分析板块 — 设计文档

> 日期：2026-07-03
> 需求：基于做表数据（ad_reports）提供数据分析看板，包含仪表盘、趋势图、对比、跨用户分析、AI 分析五个模块。

## 需求描述

在做表数据保存功能的基础上，提供数据分析看板，帮助运营人员：
1. 快速查看关键指标（花费、展示、安装、CPI、CTR、CVR）
2. 通过趋势图观察数据变化
3. 对比不同产品/系列的投放效果
4. 跨用户对比同产品的投放表现
5. 接入 AI 进行智能分析

## 技术方案

### 1. 数据库

**`ad_reports` 表**（`py/database.py`）：

```sql
CREATE TABLE IF NOT EXISTS ad_reports (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id),
    product_name TEXT NOT NULL,
    region TEXT NOT NULL,
    report_date TEXT NOT NULL,
    account TEXT NOT NULL DEFAULT '',
    customer_id TEXT NOT NULL DEFAULT '',
    campaign TEXT NOT NULL DEFAULT '',
    cost REAL DEFAULT 0,
    impressions INTEGER DEFAULT 0,
    clicks INTEGER DEFAULT 0,
    installs INTEGER DEFAULT 0,
    in_app_actions REAL DEFAULT 0,
    cost_per_in_app REAL DEFAULT 0,
    saved_at TEXT DEFAULT (datetime('now','localtime'))
);
```

**索引**：
- `idx_ad_reports_user_product_date` ON (user_id, product_name, report_date)
- `idx_ad_reports_dedup` ON (user_id, product_name, customer_id, campaign, report_date) — 去重
- `idx_ad_reports_date` ON (report_date)

### 2. 后端 API

所有端点挂载在 `/api/ad-reports/`，需 JWT 认证。

| 端点 | 方法 | 功能 |
|------|------|------|
| `/api/ad-reports/products` | GET | 用户有权限的产品列表（含 owner + runner） |
| `/api/ad-reports/list` | GET | 分页列出报告数据 + 产品/地区下拉选项 |
| `/api/ad-reports/save` | POST | 保存做表数据，自动关联 MCC/账户/时区，去重 |
| `/api/ad-reports/check-duplicates` | POST | 检查待保存数据中的重复行 |
| `/api/ad-reports/<id>` | DELETE | 删除单条报告（仅 owner） |
| `/api/ad-reports/dashboard` | GET | **仪表盘**：聚合指标、环比、异常检测、KPI 对比 |
| `/api/ad-reports/trends` | GET | **趋势**：按日期+分组聚合指定指标（cost/installs/cpi/ctr/cvr） |
| `/api/ad-reports/compare` | GET | **对比**：按产品/系列聚合，支持排序 |
| `/api/ad-reports/cross-user` | GET | **跨用户**：同产品不同用户的聚合数据（JOIN users） |
| `/api/ad-reports/dates` | GET | 有数据的日期及条数（前端日期选择器高亮） |
| `/api/ad-reports/analyze` | POST | **AI 分析**：聊天式交互，从 config 表读取开关 |

#### 仪表盘逻辑（dashboard 端点）

**聚合指标**（`SUM` 跨所有行）：

| 指标 | SQL | 说明 |
|------|-----|------|
| 总花费 | `SUM(cost)` | ad_reports 原始字段 |
| 总展示 | `SUM(impressions)` | ad_reports 原始字段 |
| 总安装 | `SUM(installs)` | ad_reports 原始字段（REAL，支持小数） |
| 应用内操作 | `SUM(in_app_actions)` | ad_reports 原始字段 |
| **CPI** | `SUM(cost) / SUM(in_app_actions)` | 总花费 ÷ 总应用内操作数 |
| **CTR** | `SUM(clicks) / MAX(SUM(impressions), 1)` | 后端按聚合结果计算 |
| **CVR** | `SUM(installs) / MAX(SUM(clicks), 1)` | 后端按聚合结果计算 |

**注意**：CPI 的计算方式是 `总花费 ÷ 总应用内操作数`（`SUM(cost) / SUM(in_app_actions)`），而非各行 cost_per_in_app 的平均值。

**按 campaign 分组**（v2 新增）：
- 同一产品下按 `campaign` 分组聚合，返回 `campaigns` 数组
- 每组包含：`campaign`, `total_cost`, `total_installs`, `total_impressions`, `total_clicks`, `avg_cpi`, `total_in_app`
- 按 `total_cost DESC` 排序

- **环比计算**：对比上一周期（同长度时间段之前）的花费和安装变化百分比
- **异常检测**：单日花费暴涨 > 50% 或 CPI 飙升 > 30% 时标记为异常
- **KPI 对比**：从 `products` 表获取产品 KPI，按 CPI（cost_per_in_app）vs KPI 判断达标
- **成效素材关联**：统计 `product_assets` 表中关联的素材数量

### 3. 前端 — AnalysisView.vue

**路由**：`/analysis`（所有已登录用户可访问）  
**导航**：AppSidebar 一级菜单 📈 数据分析 → 数据看板

#### 页面结构

```
数据分析页面
├── 筛选栏（产品 / 地区 / 日期范围 / 刷新按钮）
│   └── 日期选择器带数据密度标记（蓝色圆点高亮有数据的日期）
├── el-tabs（border-card 类型，5 个 tab）
│   ├── 📊 仪表盘
│   │   ├── 6 个统计卡片（总花费/总展示/总安装/应用内操作/CPI/CTR+CVR）
│   │   ├── 指标说明面板（解释 CPI、CTR、CVR、KPI 定义）
│   │   ├── 环比变化（花费/安装的涨跌百分比）
│   │   ├── 异常提醒（异常日期 + 系列 + 详情）
│   │   ├── 📦 按包/系列分组表格（campaign 粒度聚合）
│   │   └── 成效素材关联数
│   ├── 📈 趋势
│   │   ├── 指标切换 radio（CPI / 花费 / 安装 / CTR）
│   │   ├── 分组切换 radio（按包 / 按产品）
│   │   └── ECharts 折线图（360px，X=日期，多条折线按分组类型拆分）
│   ├── 📋 对比
│   │   ├── 分组切换（按产品 / 按系列）
│   │   └── el-table 排序表格（名称/花费/安装/CPI/CTR/CVR/展示）
│   ├── 👥 跨用户
│   │   └── 同产品不同用户的聚合对比表（用户/花费/安装/CPI/上报天数）
│   └── 🤖 AI 分析
│       ├── 未启用时提示管理员在 config.json 设置 ai_analysis.enabled = true
│       ├── 聊天界面（400px 消息区 + 输入框 + 发送）
│       ├── 蓝色气泡（用户）/ 白色气泡（AI）布局
│       └── 加载动画 "分析中..."
```

#### 数据流

- **筛选条件**：`filterProduct`、`filterRegion`、`filterDateRange` 三参数控制所有 tab 的数据范围
- **懒加载**：切换 tab 时才请求对应数据（`watch(activeTab)`）
- **日期高亮**：`/ad-reports/dates` 返回有数据的日期，在日期选择器中渲染蓝色圆点

#### 关键依赖

- **ECharts**：趋势图渲染，按需懒加载 chart 实例
- **Element Plus**：`el-tabs`、`el-table`、`el-date-picker`、`el-card` 等
- **reportsApi**：`frontend/src/api/reports.js` 封装所有分析 API 调用

### 4. AI 分析功能

- 从 `config` 表读取 `ai_analysis.enabled` 控制开关
- 聊天式交互：用户在输入框输入问题，发送到 `/api/ad-reports/analyze`
- 请求包含：`question` + 筛选条件（product/region/dateRange）
- **当前状态**：后端为占位实现，返回"正在接入 AI 服务中..."

### 5. 涉及文件清单

| 文件 | 说明 |
|------|------|
| `py/database.py` | ad_reports 表结构 + 索引 |
| `py/main.py` | 12 个分析相关 API 端点 |
| `frontend/src/views/AnalysisView.vue` | 数据分析主页面 |
| `frontend/src/api/reports.js` | 前端 API 封装 |
| `frontend/src/router/index.js` | `/analysis` 路由配置 |
| `frontend/src/components/AppSidebar.vue` | 导航菜单 📈 数据分析 |

## 数据链路

```
[ToolkitView 做表数据录入]
       │
       ▼
POST /api/ad-reports/save ──► ad_reports 表
       │
       ▼
[AnalysisView 筛选] ──► /api/ad-reports/dashboard   ──► 仪表盘（聚合+环比+异常+KPI）
                   ──► /api/ad-reports/trends      ──► ECharts 折线图
                   ──► /api/ad-reports/compare     ──► 产品/系列对比表
                   ──► /api/ad-reports/cross-user  ──► 跨用户对比表
                   ──► /api/ad-reports/analyze     ──► AI 分析（聊天式）
                   ──► /api/ad-reports/dates       ──► 日期选择器高亮
```

## 与做表数据保存的关系

- 做表数据保存（ToolkitView）是数据来源，用户在工具集中录入 Google Ads 原始数据
- 数据分析（AnalysisView）是消费端，读取 ad_reports 表进行多维度分析
- 两者共享 `ad_reports` 表和 `/api/ad-reports/` API 路径
