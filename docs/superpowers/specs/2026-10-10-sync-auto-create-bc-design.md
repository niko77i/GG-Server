# 同步自动补建字典项（BC / 渠道 / 国家时区）设计

> 2026-10-10。触发：用户验收时看到警告「BC「7677926795186094081」无法唯一匹配，已跳过该列」，
> 确认系统里没有这个 BC 后提出：**「这个批量导户我希望有自动新增 bc 的功能，就和运营同步看板一样，
> 系统没得 bc 就自动新增」**；随后补充**「一起，国家、时区都是一样的，这就是相当于系统默认的字典表，
> 只是没有系统运营去维护这一块，只能在导入的时候自动补充到系统中」**。

## 一、调研结论（**实证**，2026-10-10 对 `temp/app.db` 只读查过一条）

1. **该 BC 确实不存在**：按 `bc_id = '7677926795186094081'` 精确查 → 空；按名字模糊查 → 空。
2. **该系统的 BC「名字」本来就是那串数字**：前 8 条未删记录 **`name == bc_id`，全是 19 位纯数字**。
   ⇒ 表里 BC 列填数字**是惯例、不是错**；自动补建直接用表里那格的值即可（**无需另加一列 BC 名称**）。
3. **没有脏数据**：`name`/`bc_id` 带首尾空格的 **0 条**；同名 ≥2 条的 **0 组**（共 49 条 BC）。
   ⇒ 之前怀疑的「首尾空格导致匹配不上」**不成立**；「≥2 条同名」这个歧义档在这套库里也不会碰到。
4. 代码侧另有两条硬事实：`tt_bcs.bc_id` 是 **NOT NULL UNIQUE**、且 BC 管理**强制 BCID 为纯数字**
   （`py/routes/tt_routes.py:98`）；`regions` 是 `(name, timezone, platform)` + **UNIQUE(name, platform)**。

## 二、现状

**户管看板同步**（表 → 系统，`/api/huguan/dashboard/sync`）对名称类字段走
`_resolve_field` → `resolve_named_id`（`py/huguan_dashboard.py:802-808`）：**唯一命中才落库**，
**0 条或 ≥2 条都返回 None** ⇒ 记「…无法唯一匹配，已跳过该列」（`:1215`），该列不写、其余照常。

- **BC**：`_SQL_BC = SELECT id FROM tt_bcs WHERE name=? AND deleted_at IS NULL`（`:876`）—— 只按名称。
- **渠道**：`_AGENT_SQL["tt"]` → `agents`，同规则。
- **国家 / 时区**：**不是名称类字段** —— 它们在 `_PLAIN_TEXT_FIELDS["tt"]` 里（`:919`），
  **直接写进账户行的文本列**（`tt_accounts.country` / `.timezone`），**不查字典、不会"匹配不上"**。
- **`regions`（国家 → 时区字典）**：本链路**完全不碰**。只有另一条链路
  （`POST /api/tt/accounts/sync-from-sheet`）用它把「国家」换算成「时区」：`_region_timezone(db, country)`
  （`py/routes/tt_accounts_routes.py:1296`）—— 查不到就**退化成第一条 region 的时区**，**不补建**。

**同仓库已有「自动补建」先例**（用户说的「和它一样」）：

- `_ensure_bc(db, name, uid)`（`:1265`）：按 `name` 查（软删复活）→ 按 `bc_id` 兜底查（软删复活）
  → `INSERT INTO tt_bcs(name, bc_id, owner_id) VALUES(?,?,?)`，**`bc_id = name`**。
- `_ensure_agent(db, name, uid)`（`:1284`）：同形，落到 `agents(name, owner_id, platform='tt')`，
  并 **`_app_cache.clear_prefix("accounts:agents:")`**（**新建后必须清缓存，否则下拉看不到新项**）。
- 调用处 `:1376-1377`：`... if not dry_run else None`（**dry_run 不建**）。
- 运营（接户运营）**不会**自动建用户（全仓无 `INSERT INTO users`）——本设计也不做。

## 三、需求（用户已确认）

导入时，**系统字典里缺的项自动补建**，涵盖三类：**BC**、**所属渠道**、**国家→时区（`regions`）**。

## 四、方案

### 4.1 复用同一份实现（不写第二份）

把 `_ensure_bc` / `_ensure_agent` / `_strip_utc_prefix` 从 `tt_accounts_routes.py` **提取到共享非路由模块**
（拟 `py/tt_master_data.py`），两条链路都 import。理由：这是「确保主数据存在」的业务规则
（软删复活 + `bc_id` 兜底 + owner 记账 + 清缓存），**复制一份必然漂**。

### 4.2 三类字典项的补建规则

| 项 | 何时补建 | 建成什么 | 不做什么 |
|---|---|---|---|
| **BC** | 表里 BC 有值、`tt_bcs` 按名称查 **0 命中** | `name = bc_id = 表里那格`（与先例、与实测数据一致）；`owner_id = 发起同步的户管` | 同名 **≥2 条**时**仍警告跳过**（歧义不等于没有）；不覆盖已存在的 |
| **渠道** | 表里「所属渠道」有值、`agents`(platform='tt') 查 0 命中 | `name = 表里那格`、`platform='tt'`、`owner_id=该户管` | 同上（≥2 条跳过） |
| **国家→时区**（`regions`） | 表里**同时**有「国家」与「时区」且都非空、`regions` 里该 `(name, platform='tt')` **不存在** | `name = 表里的国家`、`timezone = _strip_utc_prefix(表里的时区)`（如 `UTC+8`→`+8`，与既有归一化一致） | **绝不覆盖**已存在的国家（字典是别的功能在用的权威值）；国家或时区**缺一不建**（建出「有国家没时区」的残项会被当成已有、再也补不上） |

- **软删复活**：BC / 渠道沿用先例（同名或同 `bc_id` 的软删记录直接复活，不新建）。
- **建后清缓存**：渠道照先例清 `accounts:agents:`；**BC 需确认有无对应缓存前缀要清**
  （先例 `_ensure_bc` 没清，实现时要 grep `_app_cache` 确认）。

### 4.3 dry_run：绝不写库，但**必须在差异报告里看得见**

照既有 `_pending_status` 的成熟做法：新增合成键（拟 `_pending_master`），dry_run 时产出、
**落库时**才真正 INSERT，并在 `diff` 里摊成新键：

```json
"pending_master": [
  {"kind": "bc",    "name": "7677926795186094081", "rows": 3},
  {"kind": "agent", "name": "渠道X",                "rows": 3},
  {"kind": "region","name": "美国",   "timezone": "+8", "rows": 2}
]
```

前端差异弹窗加一节「**将新增的字典项**」（照既有分区款式）。

**理由**：表里打错一个字就会建出一条垃圾字典项，而且**字典项一旦建成就"存在"了**、不会自愈；
差异报告是唯一的人工拦截点（本功能既有纪律：`dry_run` 只读、落库前必须让用户看到将发生什么）。

### 4.4 范围

- **方向**：只做**同步（表 → 系统）**；「刷新回表」不动（读库，无从补建）。
- **平台**：只做 **tt**（户管看板的多表就是 tt）；gg/fb 与 MCC/资产类型不动。

## 五、影响面

| 文件 | 改动 |
|---|---|
| `py/tt_master_data.py`（新） | `ensure_bc` / `ensure_agent` / `strip_utc_prefix`（前两个从 `tt_accounts_routes` 逐字搬运，含清缓存） |
| `py/routes/tt_accounts_routes.py` | 三个 helper 改为 import（行为不变，纯搬运） |
| `py/huguan_dashboard.py` | `_collect_updates`：BC/渠道 0 命中 ⇒ 产 `_pending_master`（≥2 仍警告跳过）；国家+时区都有而 `regions` 缺 ⇒ 产 `_pending_master` 的 region 项；`apply_diff` 落库时据它调用三个 ensure/insert |
| `py/routes/huguan_dashboard_routes.py` | 把 `_pending_master` 摊到 `diff.pending_master`（照 `_pending_status` 既有路径） |
| `frontend/src/components/HuguanDashboardCard.vue` | 差异弹窗加一节「将新增的字典项」 |
| `py/tests/` | 用例：0 命中 ⇒ 落库建出且账户挂上；**dry_run ⇒ 不建但在报告里列出**；≥2 命中 ⇒ 仍警告跳过；软删同名 ⇒ 复活不新建；**regions 已存在 ⇒ 不覆盖**；国家或时区缺一 ⇒ 不建；渠道同款；缓存清理被调用 |

## 六、非目标

- 不改「刷新回表」；不改 gg/fb；不自动建**用户（运营）**；不做 MCC / FB 资产类型；
- 不做字典项的批量清理/合并；不改变「≥2 条同名 ⇒ 跳过并警告」这条既有安全规则。
