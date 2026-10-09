# TT 表头映射 · 第二批（前端列映射 UI）设计

> 2026-10-10。承接第一批（后端机制，8 任务已实现、逐任务审查 + 整批终审判 Ready）。
> 本设计是 `docs/superpowers/specs/2026-10-09-tt-header-mapping-design.md` **§4.8（配置）/ §4.9（前端列映射区）**
> 的落地细化，不推翻其任何已确认决策。

## 一、需求（要解决什么）

第一批让两件事成立：**认不出的列会被如实报出来**（差异报告 `unmatched_columns`），
**认识但认错的列可以手工覆盖**（`tables[i].columns`）。但覆盖**只能改配置/走 API**——户管在界面上**点不到**。

第二批把这件事搬进 TT 设置页的户管看板卡片，让户管能自己：
1. 看到某张表**当前每一列被认成了什么**；
2. 把认不出的列**指派**给系统字段（或显式选择「不采集」）；
3. 把**自动认错的列**改过来；
4. 从同步报告的「未采集」提示**直接跳到**指派处。

目标是把「未采集列」这条信号闭成环：**报告报出来 → 点进去 → 指派 → 下次同步采集到**。

## 二、第一批遗留、本批要补的三个后端缺口

| # | 缺口 | 证据 |
|---|---|---|
| 1 | **没有「读表头」端点** | 现有端点只有 `/huguan/dashboard`(GET/POST)、`/sync`、`/push`、`/undo`(GET/POST)、`/owner-options`（`py/routes/huguan_dashboard_routes.py:24/54/135/360/477/523/579`）。列映射 UI 必须能读到某张表第 1 行的原始表头。 |
| 2 | **字段目录没暴露给前端** | 下拉要列出全部合法字段（中文名 ↔ 字段key）。前端现有 `FIELD_LABELS`（`HuguanDashboardCard.vue:737` 附近）只是差异报告用的局部小表，**不能当权威来源**（会与后端目录漂）。 |
| 3 | **「刻意不采集」存不下** | 第一批 Task 8 的校验把空串排除在合法覆盖目标之外，而空串在字段目录里**正是** `ignore`（认识但刻意不采集）那一档的哨兵。→ 用户无法关掉一个「已自动识别但不想采集」的列。**（用户 2026-10-10 裁定：方案 A）** |

## 三、技术方案

### 3.1 后端：新增「读表头」端点

```
GET /api/huguan/dashboard/sheet-headers?platform=tt&sheet_name=<工作表名>
```

- **门禁沿用既有**：`@jwt_required()` + `@huguan_required`；**表格地址只从该户管自己的配置取**
  （既有 §8.2 归属门禁：请求体不接受表格地址）。
- **`sheet_name` 必须是该用户自己配置里的某张 tt 表**（配置校验保证工作表名互不重复 ⇒ 它能唯一确定一张表）。
  不在配置里 → `err(...)` 400（否则就等于「对着任意 sheet 读表头」）。
- 读 `A1:ZZ1`（与写侧同一个读法；gg/fb 不适用，传 non-tt → 400）。
- **响应**（逐列，按列序）：

```json
{
  "columns": [
    {"header": "日期",   "field": "acquired_date", "via": "alias"},
    {"header": "账户ID", "field": "advertiser_id", "via": "override"},
    {"header": "位置",   "field": "",              "via": "ignored"},
    {"header": "备注二", "field": null,            "via": "none"}
  ],
  "unmatched": ["备注二"]
}
```

- `via` 四档：`alias`（别名自动认出）/ `override`（该表 `columns` 手工指派）/
  `ignored`（认识但刻意不采集：目录哨兵「位置」，或用户指派了「不采集」）/ `none`（完全不认识）。
- `field=""` 仅与 `via="ignored"` 同时出现；`field=null` 仅与 `via="none"` 同时出现。
- **空表头列不列出**（`resolve_column_map` 本就跳过它们；列出来也无从指派）。
- `unmatched` 与同步报告里的口径**逐字一致**（同一个 `resolve_column_map` 产出）。
- `header` 是 **`strip()` 之后**的文本 —— 它同时就是 `columns` 的**键**（`resolve_column_map` 也是按
  strip 后的文本匹配与存键）。前端显示、回填、写覆盖三处必须用同一个值，别在某一处再 trim 出差异。

### 3.2 后端：把字段目录暴露给前端

在 `GET /api/huguan/dashboard` 的 **tt 分支**追加一个只读键 `tt_field_catalog`（gg/fb 载荷形状不变）：

```json
[{"key": "acquired_date", "label": "入库时间", "direction": "rw",
  "writable": true, "readable": true, "key_col": false}, ...]
```

- **只含真正的字段**（排除空串哨兵）；「不采集」由前端单独提供选项、存空串（见 3.3）。
- 来源必须是**与 POST 校验同一处**（`TT_FIELD_CATALOG` / `field_spec("tt")`），否则「前端能选但后端拒绝」会漂。
- `key_col: true` 只给定位键（`advertiser_id`）——UI 要把它标成「定位键（必选）」，用户取消它会直接导致同步被拒。
- `direction: "r"`（目前只有「换绑情况」）在 UI 上标「只读回」。

### 3.3 后端：覆盖值为空串 ＝ 刻意不采集（用户裁定 A）

- **POST 校验**：`columns` 的值允许 `""`（＝刻意不采集）；其余值仍必须在字段目录内。
  **同一个字段 key 不得被两列同时指定**——但**空串除外**（多列同时「不采集」是合法的）。
- **`resolve_column_map`**：覆盖命中且值为 `""` ⇒ 按「认识但刻意不采集」处理：**既不映射、也不进 `unmatched`**。
  （用户显式要求不采集的列再报「未采集」，就是把这条信号重新变成噪音——正是第一批 §4.1 要把
  「认识但刻意不采集」与「不认识」分开的同一个理由。）
- 语义上与目录里的 `ignore` 哨兵（「位置」）**同档**：等于「手工把任意列降级为 ignore」。
- 记录一条边界：`""` 是**唯一的**空语义魔法值；不再引入第二个。

### 3.4 前端：`HuguanDashboardCard.vue` 的列映射区（方案 1）

**位置**：tt 的多表配置里，每个表项（`hdForm.tables[i]`）下方一个**可折叠面板**「列映射」。

- **「读取表头」按钮**：调 3.1 的端点（带该行当前 `sheet_name`；为空则按钮禁用并提示先填工作表名）。
- 读回来**逐列一行**：`[表头原文] → [下拉]`。
  - 下拉选项 = `tt_field_catalog`（按中文名显示；定位键标「定位键」、只读回标「只读回」）+ **「（不采集）」**。
  - **默认虚显**：`via="alias"`/`via="ignored"` 的行，下拉显示自动识别的结果，但**不算覆盖**、不写进 `columns`。
  - `via="none"`（未识别）的行**醒目标出**，下拉默认停在「（不采集）」。
  - 用户**只要改动**该行下拉 ⇒ 这一行转成覆盖，写进 `hdForm.tables[i].columns`（键＝表头原文，值＝字段key 或 `""`）。
- **保存**：改动留在表单状态里，由卡片**现有的「保存」按钮**一起提交（同一条 POST，含 3.3 的校验）。
  - 面板标题上给「**有未保存的列映射**」提示（与卡片既有的未保存提示风格一致）——不引入第二条配置写路径。
- **未采集列的入口**：同步差异报告里那条「有 N 列未识别」的提示，逐条列出表名 + 表头，各带一个
  「去指派」按钮 → 打开该表的列映射面板（滚动到可见）并**自动点一次「读取表头」**。
- **GG / FB 不出现该区**：`HD_PLATFORM === 'tt'` 门控（与卡片既有写法一致）。

**纯逻辑抽出以便单测**：把「表头响应 → 下拉行状态」的换算（默认虚显值、哪几行算「改动过」、
`columns` 的组装/回读）抽进一个纯模块（`frontend/src/utils/columnMapping.js`），
按仓库既有做法用 `node --test tests/`（参照 `frontend/tests/columnPrefsLogic.test.mjs`）覆盖。
Vue 组件里只留渲染与事件绑定。

### 3.5 数据结构

```jsonc
// config.huguan_dashboard_<uid>.tt.tables[i]
{"name": "企业户", "sheet_name": "企业户",
 "columns": {
   "备注二": "remark",   // 把未识别的「备注二」指派给 产品信息
   "负责人": "",          // 刻意不采集（覆盖值为空串）
   "运营":   "owner_name" // 改掉自动识别结果
 }}
```

- 只存**手工覆盖**（表头原文 → 字段key），不存自动识别结果（沿用 §4.8）。
- 键允许是当前表里还不存在的表头名（表头以后再加），**但同步时会记 warning**（既有行为，不改）。

### 3.6 错误处理

- **读表头**：未配表格 / 表名不在自己的配置里 / 读表失败 → 400（沿用 `err(...)` 文案风格）；
  前端在**面板内**就地显示错误，不弹全局错误。
- **保存**：沿用 3.3 的校验错误（400 + 文案），前端展示在卡片内（既有做法）。
- 读表头失败**不影响**用户继续用已有的 `columns` 保存——两件事互不阻塞。

## 四、非目标（本批不做）

- 不做「按内容猜列」；不做「表头改名后自动跟随」（改名＝变成未识别 → 报告里报出来 → 户管重配）。
- 不做列映射的导入/导出、不做跨用户共享。
- **不改 gg/fb**：卡片不出现该区；`GET /api/huguan/dashboard` 的 gg/fb 载荷形状不变。
- **不引入第二条配置写路径**（方案 1 的实质约束：列映射也走卡片那一个保存按钮）。
- 不重做同步差异报告的既有版式，只在其「未识别」提示上加跳转入口。

## 五、测试

**后端**（`py/tests/test_huguan_dashboard.py` 为主）：

| 用例 | 断言 |
|---|---|
| 读表头端点 | 返回逐列 `header/field/via`；未识别的进 `unmatched`；`via` 四档齐备 |
| 读表头的归属门禁 | `sheet_name` 不属于该用户 → 400；`platform` 非 tt → 400；未配表格 → 400 |
| 字段目录暴露 | tt 的 GET 响应含目录、**不含空串哨兵**；gg/fb 响应形状与改动前一致 |
| 覆盖空串＝刻意不采集 | 该列**不映射**且**不进 `unmatched`**；两列同时 `""` 允许落盘 |
| 覆盖值非法仍被拒 | 第一批 Task 8 的既有用例保持绿（非目录内的值仍 400） |
| 别名仍优先于空串？ | 覆盖 `""` **必须压过**别名自动匹配（覆盖优先级最高，空串也是一种覆盖） |

**前端**（`frontend/tests/columnMappingLogic.test.mjs`，`node --test`）：
默认虚显不落盘、改动过的行才进 `columns`、回读已有 `columns` 能还原下拉状态、
`""` 与 `null` 两种「不采集」在 UI 上的区分。

**手工验收**（本人做）：见「整体验收」清单。

## 六、影响面

**后端**
- `py/routes/huguan_dashboard_routes.py` —— 新端点 `/sheet-headers`；GET 响应 tt 分支加 `tt_field_catalog`；
  POST 校验放行空串（3.3）。
- `py/huguan_dashboard.py` —— `resolve_column_map` 支持「覆盖＝空串」；把字段目录/`ignore` 档导出给路由复用
  （与 `field_spec`/`TT_FIELD_CATALOG` 同源，不新建第二份）。
- `py/tests/test_huguan_dashboard.py` —— 按 §五 扩充。

**前端**
- `frontend/src/api/huguan.js` —— 加 `getSheetHeaders(platform, sheetName)`。
- `frontend/src/components/HuguanDashboardCard.vue` —— 列映射折叠区 + 读表头 + 未采集列跳转。
- `frontend/src/utils/columnMapping.js`（新）—— 纯逻辑，供 `node --test` 覆盖。
- `frontend/tests/columnMappingLogic.test.mjs`（新）。

**不改**：写表/撤回/推送四条链路的既有实现、`COLUMN_SPEC` 与 gg/fb 全部路径。

## 七、未决项

无。三处待定已裁定：**「不采集」的表达**（用户 2026-10-10 选 A：覆盖值空串）、
**UI 形态与落盘时机**（选方案 1：内联折叠区 + 复用卡片保存按钮）、
**字段目录来源**（后端暴露，与 POST 校验同源）。
