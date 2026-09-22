# TT 数据提取（解析预览）— 设计文档

> **日期**：2026-09-22
> **状态**：待确认

## 1. 需求描述

TT 平台新增「数据提取」功能，第一期只做**解析预览**（不写表）：

1. 粘贴 TikTok Ads 报表数据 → 解析 → 预览三类结果（原始清洗数据 / 做表数据 / 客户表数据）。
2. 每个结果表格支持「📋 一键复制」；全部结果支持「📥 导出全部为 Excel」。
3. 解析逻辑**先完全复用 GG 的 `parseAdsData`**（Google Ads 竖排格式，含「添加过滤条件」「Total」标记），**数据格式后续再针对 TikTok Ads 实际格式调整**。
4. 本期**不做写表**。写表目标 sheet 后续在「个人信息」里配置（与 GG 一致），本期不涉及。

> 核心目标：把 GG 的「做表数据」UI 与解析链路搬到 TT，先跑通「粘贴 → 解析 → 预览 → 复制/导出」，写表留到下一期。

## 2. 现状

- GG 的「做表数据」在 [ToolkitView.vue](../../../frontend/src/views/ToolkitView.vue) 的 `zuobiao` Tab：粘贴 Google Ads 竖排数据 → 前端 [adsParser.js](../../../frontend/src/utils/adsParser.js) 的 `parseAdsData` 解析 → 预览 + 「更新你的表格」写库写 Sheets。
- FB 的「数据提取」在 [FbDataExtract.vue](../../../frontend/src/views/fb/FbDataExtract.vue)（独立页 + 侧边栏入口，后端解析）。
- TT 目前**没有**数据提取 / 做表功能。

## 3. 技术方案

### 3.1 新增页面 `frontend/src/views/tt/TtDataExtract.vue`

**复刻** GG `ToolkitView`「做表数据」Tab 的 UI，但**去掉写表相关部分**：

保留：
- 产品下拉（数据源 `/api/tt/products/list`，label = `product_name + (region) + (sales_person_name)`，value = `product_name`）
- 日期选择（默认「昨天」，跨天自动刷新）
- 养户关键词（多选可创建，localStorage 持久化，默认 `['养户', 'Website traffic-Search', 'Campaign #1']`）
- 勾选项：「包含广告系列ID」「7列数据（无安装/应用指标）」
- 粘贴框 + 「🚀 一键解析并生成所有报表」按钮
- 三个结果表格：原始清洗数据 / 做表数据 / 客户表数据
- 每表「📋 一键复制」、整体「📥 导出全部为 Excel」

去掉：
- 「📊 更新你的表格」按钮
- 表格同步状态提示条 + 轮询逻辑
- 「保存做表数据」弹窗 + 重复数据对比弹窗

> 产品/日期/养户关键词在本期仅作 **UI 占位**（解析预览不依赖它们），为下一期写表预留；解析只依赖粘贴文本 + 两个勾选项。

### 3.2 解析逻辑复用 `parseAdsData`（不改动）

直接 `import { parseAdsData } from '@/utils/adsParser'`，调用：

```js
const { raw, zuobiao, kehu } = parseAdsData(input, {
  isSevenCols: sevenCols,        // 7列模式
  includeCampaignId: includeCampaignId, // 含广告系列ID
})
```

`parseAdsData` 是纯函数，后续针对 TikTok Ads 格式调整时，只需替换/扩展该函数或新增 `parseTtAdsData`，页面结构不变。

### 3.3 路由：`/tt/extract`

参照 FB 的 `/fb/extract`（独立路由，`meta.platform='tt'`），**不进** `TtView` 的顶部 tab children，页面自带 header。

### 3.4 侧边栏入口

[AppSidebar.vue](../../../frontend/src/components/AppSidebar.vue) 的 `ttNavItems` 新增「数据提取」入口（参照 `fb-extract`）：

```js
{ key: 'tt-extract', icon: '📋', label: '数据提取', sections: [{ title: '提取', items: [{ icon:'📥', label:'TT数据提取', path:'/tt/extract' }] }] },
```

### 3.5 无后端改动

本期纯前端，不新增/修改任何后端接口、表、Google Sheets 逻辑。

## 4. 涉及文件

| 文件 | 操作 | 说明 |
|---|---|---|
| `frontend/src/views/tt/TtDataExtract.vue` | 新增 | 数据提取页面（复刻 GG 做表数据 Tab，去写表） |
| `frontend/src/router/index.js` | 修改 | 新增 `/tt/extract` 路由 |
| `frontend/src/components/AppSidebar.vue` | 修改 | `ttNavItems` 新增「数据提取」入口 |
| `frontend/src/utils/adsParser.js` | 复用 | 不改动 |

## 5. 数据结构（parseAdsData 返回值）

```js
{
  raw: [   // 原始清洗数据（每条 = 一个广告系列一行）
    { account, customerId, campaign, campaignStatus, cost,
      impressions, clicks, installs?, inAppActions?, costPerInApp? }
  ],
  zuobiao: [ // 做表数据（按 customerId + campaign 聚合，cost 累加）
    { account, customerId, cost, campaign }
  ],
  kehu: [   // 客户表数据（按 campaign 聚合）
    { campaign, cost, impressions, clicks }
  ]
}
```

## 6. UI 改动

复刻 GG「做表数据」Tab 布局：顶部产品/日期/关键词/勾选 + 粘贴框 + 操作按钮，下方三张结果表格（各带一键复制），无写表按钮与同步状态条。整体视觉与 GG 做表数据 Tab 一致。

## 7. 测试计划

本期纯前端，无自动化单测。验证方式：

1. 粘贴一段含「添加过滤条件」「Total」的 Google Ads 竖排样本 → 解析出三张表、条数正确。
2. 切换「7列 / 含广告系列ID」勾选 → 解析结果随之变化。
3. 「一键复制」「导出 Excel」可用。
4. 侧边栏「数据提取」入口可点击进入，路由 `/tt/extract` 正常渲染。

## 8. 后续（不在本期）

- 针对 TikTok Ads 实际数据格式调整解析（新增/替换解析函数）。
- 「更新你的表格」写表 + 写库（`ad_reports` 等价表）+ 写表目标 sheet 在「个人信息」配置。
- TT 数据管理页（列表/导出/分析）。
