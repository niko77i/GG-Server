# FB 数据管理页：自选展示列 —— 实现计划

日期：2026-10-19
设计：`docs/superpowers/specs/2026-10-19-fb-data-manage-column-selector-design.md`（已确认）
涉及文件：仅 `frontend/src/views/fb/FbDataManage.vue`（后端零改动）

---

## Task 1: 视觉决策（项目规范要求）

- [ ] 调用 `/frontend-design` 技能，产出要点记入设计文档末尾的 `## 附录：视觉决策`
      （**新增 UI，动组件前必须先调**）。

## Task 2: 列定义与持久化逻辑

- [ ] 在 `<script setup>` 里新增 `allColumns`（11 列，见设计 §3.1）。
- [ ] `COL_STORAGE_KEY = 'fb_data_manage_columns'`；`loadColumnPrefs()` / `saveColumnPrefs()`。
      **默认可见列 = 前 6 列**（产品名、线名、日期、账户名称、账户ID、消耗）。
- [ ] `visibleColumns`（ref）+ `visibleColumnDefs`（computed，保持 `allColumns` 顺序）。
- [ ] `toggleColumn(prop, checked)`：按 GG 的同款逻辑（勾选时按原顺序插回）。
      最后可见列不应为空 —— 至少保留 1 列（与 GG 行为一致；若 GG 未做此保护则抄齐，不额外加规则）。

## Task 3: 模板改造

- [ ] 表格数据列改为 `v-for="col in visibleColumnDefs"`，一个 `el-table-column` 承载。
- [ ] `cost` 列保留现有两个分支（`auth.canEditReportCost` 内联编辑 / 只读），
      宽度继续用「户管 150 / 其余 100」（`336b5bc` 的规则）。
- [ ] 其余列按 `col.width` / `col.minWidth` 输出；`cost_per_purchase` 保留 `$` 格式化。
- [ ] 筛选栏加入 `📊 列显示` popover + `el-checkbox` 列表（照 GG `DataManageView.vue:41-54`）。
- [ ] **移除** `showDetailCols` 复选框（`:26`）、5 个详情列的 `v-if`（`:85-91`）、
      `const showDetailCols`（`:173`）。
- [ ] 勾选框列 / 操作列保持在 `v-for` 之外，角色谓词不变。

## Task 4: 验证

- [ ] `cd frontend && npm run build` ✅
- [ ] `npm test` 全绿
- [ ] 手工核对清单（设计 §5）：普通 user 默认列与改动前一致；勾选/取消即时生效；
      刷新后保持；清除 localStorage 回到默认；户管消耗列可编辑且不截断；
      导出 CSV 不受影响。

## Task 5: 提交

- [ ] 只提交 `FbDataManage.vue` 与本文档/设计文档；提交前 `git diff --stat` 核对归属。
- [ ] 不推 origin。
