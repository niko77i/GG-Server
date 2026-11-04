# 薪资计算（工具集）

> 状态：已实现（2026-11-04）
> 位置：工具集 → 薪资计算（`/toolkit/salary`）

## 1. 背景

投手薪资此前靠一个独立的 PowerShell 计算器（`carl knowledge/scripts/salary.ps1`）手填五项数字。
本功能把它搬进 GG-Server：**不再手抄合计**，直接从用户自己配置的「做表」Google 表格里
读 A–N 列，自动聚合出代投费 / 纯增值 / 消耗，再叠加页面可调的底薪、成本、汇率。

## 2. 口径（2026-11-04 用户逐条确认）

做表列结构（写入端见 `google_sheets_service.upsert_zuobiao`）：

| 列 | 含义 | 谁填 |
|---|---|---|
| A | 日期 | 做表写入 |
| E | 费用 | 做表写入 |
| F | 报给客户 | 人工 |
| K | 平台实际 | **人工，滞后填** |
| L | 代投比例 | 做表写入 |
| M | `=F*L` 代投费 | 公式 |
| N | `=F-K+M` 利润 | 公式 |

聚合规则：

```
代投费 = ΣM
纯增值 = Σ(F − K)
消耗   = ΣK
基数   = 代投费 + 纯增值（等价于 ΣN）
利润   = 基数 − 成本
总薪资 = 底薪 + (消耗提成 + 利润提成) × USDT 汇率
```

**只统计 K 列有值的行** —— K 没填时纯增值与消耗都不成立，整行跳过。
「最新日期」取**最后一条 K 有值的行**的 A 列，前端据此提示「当前薪资计算到 X 号」。

### 档位（一律左闭右开）

| 项 | 判定字段 | 档位 → 结果 |
|---|---|---|
| 底薪（元） | 基数 | <1万→4000；<3万→6000；<4万→8000；**≥4万→10000** |
| 消耗费率 | 消耗 | <20万→0.002；≥20万→0.003（**全额按档位**） |
| 利润提成费率 | 纯增值 | **<0→0.01**；<2万→0.10；<3万→0.12；<4万→0.15；≥4万→0.18 |

利润为负时提成按 0 计（不倒扣），明细里照实显示负利润。

**底薪判档用「基数」，不用「基数 − 成本」**：做表的 N 列（表头就叫「利润」）本来
就是 `F−K+M = 代投费+纯增值`，表里没有成本列；成本只在页面手填、只从利润提成里扣。
成本 > 0 时底薪不降 —— 与 2026-11-03 版「底薪永远看代投费+纯增值」一致。

### 与旧版（2026-11-03）的两处差异

1. 底薪 4 万以上由 8000 改为 **10000**（旧版 3–4万 与 4万以上同值，等于空档）。
2. 纯增值为负时费率取 **0.01**（旧版没有负档，会落到 0.10）。

## 3. 数据流

```
用户配置（config.google_sheets_user_<uid>，多张月度表 + active）
        │  前端下拉框按 spreadsheet_name 展示，可任选一张
        ▼
GET /api/salary/overview?spreadsheet_id=…
        │  salary_service.read_and_aggregate()
        │    → 取表格第一个 Sheet，读 A:N（UNFORMATTED_VALUE）
        │    → aggregate_rows()：跳过 K 空行、解析数字/日期、按日分组、口径告警
        ▼
aggregates + 默认 salary（成本 0 / 底薪自动判档 / 汇率 6.6）
        │  页面改底薪 / 成本 / 汇率
        ▼
POST /api/salary/compute  → salary_calc.compute_salary()（纯函数，不读表）
```

## 4. 后端

- `py/salary_calc.py`：纯计算（档位、边界、成本、汇率），无 IO，可直接单测。
- `py/salary_service.py`：读表 + 聚合。`parse_number` / `parse_date_cell` 处理
  千分位、百分号、`#VALUE!`、Google Sheets 日期序列号；`aggregate_rows` 产出四项输入、
  最新日期、按日明细与 `warnings`。
- `py/routes/salary_routes.py`：两个端点。`spreadsheet_id` **必须落在当前用户自己配置的
  表格列表**里（服务账号对这些表有读权限，不校验就能读别人的表），不在列表里统一 403。
- `py/google_sheets_service.read_sheet_values`：新增 `value_render_option` 参数（默认不变）。
  薪资必须传 `UNFORMATTED_VALUE`，否则拿到 `1,234.00`、`6%`、日期字符串。

### 口径告警（前端以 warning 展示，不阻断计算）

- K 列非数字 → 跳过并计数；
- **表头行**（K 列是 `平台实际` 这类短文本）单独计入 `rows_header_k`，**不告警** ——
  真机表的首行是表头，否则每次计算都会挂一条「1 行 K 列不是数字」的噪音；
- K 有值但 F 为空 → F 按 0 计（纯增值会偏负）；
- M 列无值（公式没铺到 / `#VALUE!`）→ 按 `F×L` 兜底；
- ΣN 与「代投费+纯增值」不一致 → 提示检查公式或手工改动。

> 真机核对（用户本人 2026.10 / 2026.11 两张表）：10 月计入 1096 行、最新日期 `2026-10-31`；
> 11 月计入 65 行、最新日期 `2026-11-02`。表尾有一行「无日期且全 0」的记录（不影响合计）。
> 07/08/09 三张旧表**没有共享给服务账号**（403），页面会给出「请确认已共享」的提示。

## 5. 前端

`frontend/src/views/toolkit/SalaryPanel.vue`，挂在工具集第 2 个 Tab（做表数据之后）。

- 表格下拉：来自 `/api/config/google-sheets`，**默认选「当月」那张**（名称含 `YYYY.MM`；
  找不到就取列表最后一张），并记住上次选择（localStorage）。⚠️ 不能直接沿用配置里的
  `active` —— 真机上 active 停在 `2026.07`，而那张表既不是当月、也不一定还共享着。
- 参数：底薪下拉（4000/6000/8000/10000 四项，**默认选中 6000**）、成本（默认 0）、汇率（默认 6.6）。
  旁注「按基数应落 X 元」只作提示，默认不自动跟随判档结果（用户 2026-11-04 指定默认 6000）。
- 结果：明细表 + 总薪资 + 按日期明细（可折叠）。
- 顶部固定提示「当前薪资计算到 X（K 列最后一条有值的行）」与统计行数。
- 进入页面才读表（`v-if`），避免每次开工具集都白跑一次 Sheets API。

## 6. 已知取舍

- **只读**：不写回表格，也不落库；每次进页面/切表重新读。
- 固定读**第一个工作表**，与写表端一致（`upsert_zuobiao`）。
- 成本是**页面手填的月合计**（表里没有成本列），默认 0。
- 不做「按人」拆分：工资归属当前登录用户，读的是他自己配置的表。

## 7. 文件清单

| 文件 | 变更 |
|---|---|
| `py/salary_calc.py` | 新增（纯计算） |
| `py/salary_service.py` | 新增（读表 + 聚合） |
| `py/routes/salary_routes.py` | 新增（2 路由） |
| `py/main.py` | 注册 `salary_bp` |
| `py/google_sheets_service.py` | `read_sheet_values` 增加 `value_render_option` |
| `frontend/src/views/toolkit/SalaryPanel.vue` | 新增 |
| `frontend/src/api/salary.js` | 新增 |
| `frontend/src/views/ToolkitView.vue` | 新增 Tab 与面板 |
| `frontend/src/router/index.js` | `/toolkit/salary` |
| `frontend/src/components/AppSidebar.vue` | 工具集菜单项（做表数据之后） |
| `py/tests/test_salary_calc.py` | 新增（档位边界） |
| `py/tests/test_salary_service.py` | 新增（读表聚合） |
| `py/tests/test_salary_routes.py` | 新增（归属/参数校验） |

## 8. 测试

```bash
cd py && python -m pytest tests/test_salary_calc.py tests/test_salary_service.py tests/test_salary_routes.py -q
```

覆盖：三组档位的左右边界、文档算例（27,120）、负利润不倒扣、负增值 0.01、
手选底薪（仍带出自动档）、K 空行跳过与最新日期、日期序列号（含文本形态、以及
「100 不是日期」）、`L=1` 按 1%、K=0 / 负 K 照实计入、M 兜底、N 不一致告警、
`read_and_aggregate` 必传 `UNFORMATTED_VALUE`、表格归属 403、非 dict 请求体 400、
错误文案用中文字段名。

## 9. 独立审查处置（2026-11-04）

一次只读代码审查提出 6 条中危 + 14 条低危，已全部处置：

| 问题 | 处置 |
|---|---|
| 非 dict 请求体 → 500 | 判 `isinstance(data, dict)`，否则 400 |
| 底薪按基数还是按利润判档 | 维持基数（见 §2 说明），页面可手动改选四档 |
| 空表仍显示「总薪资 4000」 | `rows_counted = 0` 时 `salary = null`，改为空态提示 |
| 切表/连点读表竞态 | `overviewSeq` 序号守卫，只认最后一次响应 |
| 刷新同表静默重置成本/汇率/底薪 | 仅**换表**时重置，同表刷新保留用户输入 |
| 重算失败后旧金额无标记 | 顶部红条明确「下方金额仍是上一次成功计算的结果」 |
| 表头识别过窄（`平台实际(USDT)`） | 放宽到 20 字符且含「平台/实际」 |
| 日期解析把 100 当序列号 / 文本序列号不转 | 序列号限定 20000–90000，文本形态同样转换 |
| `L=1` 被当成 100% | 改为 `>= 1` 即按百分数（1 → 1%） |
| 错误文案含英文字段名 | 改用「代投费 / 消耗 / 成本 / USDT 汇率」 |
| `/toolkit/salary` 缺 `meta.platform` | 补 `'gg'` |
| 读配置失败却同时显示「还没配置」空态 | 空态加 `&& !error` |
| `localStorage` 抛错会打断读表 | 读写都包 try/catch |
