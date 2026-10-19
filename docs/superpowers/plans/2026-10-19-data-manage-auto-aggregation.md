# 数据管理页：按可见列自动聚合 + 联动 —— 实现计划

日期：2026-10-19
设计：`docs/superpowers/specs/2026-10-19-data-manage-auto-aggregation-design.md`（已确认）

---

## Task 1: 视觉决策

- [ ] 调 `/frontend-design`，产出记入设计文档末尾 `## 附录：视觉决策`（新增「放弃聚合」按钮与子列禁用态）。

## Task 2: 前端纯逻辑模块（可测）

- [ ] 新建 `frontend/src/utils/reportAggregation.mjs`：
  - `isAggregating(visibleProps, cfg, aggregationOff)` — 可见维度数 < 维度总数 且未放弃
  - `visibleDimensions(visibleProps, cfg)` — 按 cfg 声明顺序返回可见维度 prop
  - `applyLinkage(visibleProps, prop, checked, cfg)` — 父子联动（勾父带子、取消父取消子、子不能独立存在）
  - `normalizePrefs(savedProps, cfg)` — 过滤未知列；含子缺父时补父
- [ ] 新建 `frontend/tests/reportAggregation.test.mjs`（node --test），覆盖上述四条规则。

## Task 3: 服务端聚合

- [ ] `py/routes/fb_routes.py` `list_reports`：接受 `group_by`，白名单映射、GROUP BY + SUM、
  `total` 用分组子查询计数；非法列名 → 400。缺省行为逐字不变。
- [ ] `py/main.py` `ad_reports_list`：同上（`display_product → product_name`）。
- [ ] 测试：聚合值正确、跨页 total 为组数、非法列名 400、普通 user 仍只看自己。

## Task 4: 两页接入

- [ ] 维度/数值分类配置；`aggregating` / `aggregationOff` / 列变化时复位。
- [ ] 聚合态：请求带 `group_by`；隐藏 勾选列/操作列/消耗 ✏️；显示「放弃聚合」按钮
      （放弃后变「恢复聚合」）。
- [ ] 列选择器使用 `applyLinkage` / `normalizePrefs`（FB 产品名→线名；GG 产品→广告系列）。
- [ ] 切聚合/切列 ⇒ 页码归 1。

## Task 5: 验证与提交

- [ ] `npm run build` / `npm test` / 相关 pytest（含全量）。
- [ ] 提交（仅本任务文件），不推 origin。
