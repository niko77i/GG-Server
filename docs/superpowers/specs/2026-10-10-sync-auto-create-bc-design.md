# 同步自动补建 BC / 渠道（户管看板）设计

> 2026-10-10。触发：用户验收时看到警告「BC「7677926795186094081」无法唯一匹配，已跳过该列」，
> 确认系统里没有这个 BC 后提出：**「这个批量导户我希望有自动新增 bc 的功能，就和运营同步看板一样，
> 系统没得 bc 就自动新增」**。

## 一、现状（已核代码）

**户管看板同步**（表 → 系统，`/api/huguan/dashboard/sync`）对名称类字段的解析是
`_resolve_field` → `resolve_named_id`（`py/huguan_dashboard.py:802-808`）：

- 规则是**唯一命中才落库**；**命中 0 条或 ≥2 条都返回 None** ⇒ `_collect_updates` 记一条
  「`{字段}「{值}」无法唯一匹配，已跳过该列」的警告（`:1215`），**该列不写库，其余列照常**。
- BC 的查名 SQL 是 `SELECT id FROM tt_bcs WHERE name=? AND deleted_at IS NULL`（`:876`）—— **只按名称**。

**同仓库已有「自动补建」的先例**（用户说的「和…一样」就是它）：

- `py/routes/tt_accounts_routes.py` 的 `POST /api/tt/accounts/sync-from-sheet`（`:1311`，函数 `sync_from_sheet`）
  在同一文件里有一对 helper：
  - `_ensure_bc(db, name, uid)`（`:1265`）：按 `name` 查（**软删则复活**）→ 再按 `bc_id` 兜底查
    （**软删则复活**）→ 都没有则 `INSERT INTO tt_bcs(name, bc_id, owner_id) VALUES(名字, 名字, uid)`。
  - `_ensure_agent(db, name, uid)`（`:1284`）：同形，落到 `agents(name, owner_id, platform='tt')`。
  - 调用处 `:1376-1377`：`bc_id = _ensure_bc(...) if not dry_run else None`（**dry_run 不建**）。

**注意两个容易记错的点**（我核过）：① **运营（接户运营）不会自动建用户** —— 全仓没有 `INSERT INTO users`，
`resolve_owner_id` 也只有「唯一命中才落库」；② `tt_bcs.bc_id` 是 **NOT NULL UNIQUE**（`database.py:942`），
所以自动建必须给 `bc_id` 一个值——先例的做法是 **`bc_id = name`**（同一个值，天然不冲突）。

## 二、需求

让**户管看板同步**在遇到「表里有、系统里没有」的 **BC**（本次诉求）时**自动补建**，
而不是跳过该列并报警告。用户期望它与 `sync-from-sheet` 那条链路的行为一致。

## 三、方案

### 3.1 复用同一份实现（不写第二份）

把 `_ensure_bc` / `_ensure_agent` 从 `tt_accounts_routes.py` **提取到一个共享的非路由模块**
（拟 `py/tt_master_data.py`），两条链路都 import 它。理由：这两段是「确保主数据存在」的业务规则
（软删复活 + bc_id 兜底 + owner 记账），**复制一份必然漂**。

- 代价：要动 `tt_accounts_routes.py`（把两个 helper 换成 import）。该文件不属于本功能既往改动面，
  但改动是纯搬运（函数体逐字不变）。
- 备选（更小但会留重复）：直接在 `py/huguan_dashboard.py` 里照抄一份并注释指向先例。
  **不推荐** —— 本仓库对「同一规则两份实现」已经吃过亏（写表治理五期反复收口）。

### 3.2 户管看板同步的语义（与先例对齐，但 dry_run 要给可见性）

- **只在落库阶段（`dry_run: false`）真正 INSERT**；dry_run **绝不写库**（与既有 `_pending_status` 同一纪律）。
- **dry_run 必须在差异报告里看见**：新增一个合成键（照 `_pending_status` 的成熟做法），
  例如 `_pending_master`，在 `diff` 里呈现为
  `pending_master: [{"kind": "bc"|"agent", "name": str, "rows": N}]`
  ⇒ 前端报告里加一节「**将新增的 BC / 渠道**」，把行数列出来。
  **理由**：表里打错一个字就会建出一条垃圾主数据；不列出来用户就没有拦截机会，
  这正是差异报告这道「唯一人工护栏」存在的意义。
- **`≥2 条同名` 仍然跳过 + 警告**（不猜、不建第三条）：歧义不是「没有」，多建一条只会更乱。
- **软删复活**沿用先例：同名（或同 `bc_id`）的软删记录直接复活，不新建。
- **owner 记账**沿用先例：`owner_id = 该户管（发起同步的 uid）`。

### 3.3 `bc_id` 填什么（**需要你决定，见 §五**）

先例是 `bc_id = name`。这对「表里填的是 BC **名称**」是对的；但**你这次的值是一串 19 位数字**
（像是平台侧 BC ID），照先例会建出一个**名字是这串数字**的 BC。

### 3.4 范围

- **方向**：只做**同步（表 → 系统）**；「刷新回表」不动（它读库，无从补建）。
- **字段**：**BC**（本次诉求）+ **所属渠道**（与先例成对，`_ensure_agent` 现成）。
  - **不做 MCC**（gg 的 MCC 是另一套词表，且本次问题不在它）；**不做 FB** 的渠道/资产类型。
- **平台**：本设计只覆盖 tt（户管看板的多表就是 tt）。

## 四、影响面

| 文件 | 改动 |
|---|---|
| `py/tt_master_data.py`（新） | `ensure_bc(db, name, uid)` / `ensure_agent(db, name, uid)`（从 `tt_accounts_routes` 搬运，逐字） |
| `py/routes/tt_accounts_routes.py` | 两个 helper 改为 import（行为不变） |
| `py/huguan_dashboard.py` | `_collect_updates` 里：BC/渠道在「0 命中」时产 `_pending_master`（≥2 仍警告跳过）；`apply_diff` 落库时据它调用 `ensure_bc/ensure_agent` |
| `py/routes/huguan_dashboard_routes.py` | 把 `_pending_master` 摊到 `diff` 的新键（照 `_pending_status` 的既有路径） |
| `frontend/src/components/HuguanDashboardCard.vue` | 差异弹窗加一节「将新增的 BC / 渠道」（照既有分区款式） |
| `py/tests/test_huguan_dashboard.py` 等 | 用例：0 命中 ⇒ 落库建出 BC 且账户挂上；dry_run ⇒ **不建**但在报告里列出；≥2 命中 ⇒ 仍警告跳过；软删同名 ⇒ 复活不新建；渠道同款 |

**数据结构**：`diff.pending_master: [{"kind": "bc"|"agent", "name": str, "rows": int}]`（新键；缺省路径不带）。

## 五、待你决定

1. **`bc_id` 填什么（关键）**：
   - **甲（推荐，与先例一致）**：`bc_id = name = 表里那一格的内容`。若你表里填的是**名称**，完美；
     若填的是**ID 数字**（你这次的 `7677926795186094081`），会建出一条**名字就是这串数字**的 BC。
   - **乙**：表里那格是 ID ⇒ 你们其实需要**另有一列 BC 名称**（或以后统一改填名称），
     自动建时 `name` 取名称列、`bc_id` 取 ID 列。**这需要先确认你的表打算怎么填。**
   - **丙**：先只做「甲」，把「按 ID 认/建」留待你确认表结构后再说。
2. **渠道要不要一起自动建？**（先例是一起；推荐**一起**，否则渠道列还会出同样的警告）
3. **报告里列出来**（推荐，见 §3.2）——如果你希望**静默建**、不打扰，请明说（我不推荐：打错字会积垃圾主数据）。

## 六、非目标

- 不改「刷新回表」；不改 gg/fb；不改 MCC/资产类型；不做主数据的批量清理/合并。
- 不改变「≥2 条同名 ⇒ 跳过并警告」这条既有安全规则。
