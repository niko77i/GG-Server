# FB 资产数据模型 设计（子项目 ①）

> 日期：2026-10-06
> 范围：FB 平台资产（`fb_accounts`）的字段扩充、两个公共选项表、以及为看板同步所需的归属端点。
> 本设计是三步拆分的**第一步**。② FB 户管看板（列映射 + 双向同步）、③ 双向撤回，另出文档。

---

## 一、需求描述

### 背景

FB 户管需要一张跨用户的资产看板（Google Sheet 双向同步），语义与 GG / TT 的户管看板一致
（见 `2026-09-23-huguan-sheet-design.md`），但 FB 的列完全不同。

用户 2026-10-06 给出的 FB 看板列（原文，17 列）：

> 日期 / 操作人 / 账户名称 / 资产UID / 所属渠道 / 资产类型 / 单价 / 入库 / 接户运营 /
> 在用运营 / 出库时间 / 出库 / 时区 / 消耗 / 状态 / 位置 / 产品信息（备注）

同一条消息里的三点补充（原文）：

> 「资产UID就是账号id，所属渠道，资产类型，状态，要提取为公用的，就像gg里面的代理一样，
> 接户运营和在用运营可以不同，系统分别展示。位置暂定为bm名称」

### 现状差距

`fb_accounts` 现在只有 7 个业务列：

```
name / account_id / timezone / status_id / acquired_date / status_changed_date / owner_id
```

17 列里能直接对上的只有 6 个（日期、账户名称、资产UID、时区、状态、**在用运营**）。
**缺 10 个字段 + 2 个公共选项表。**

### 一句话目标

把 17 列里系统需要承载的字段落进库，使子项目 ② 的看板列映射有字段可用。

---

## 二、已定决策汇总

| # | 决策点 | 结论 | 来源 |
|---|---|---|---|
| 1 | 「位置」列 | 映射为该账户的**主 BM 名称** | 2026-10-06 |
| 2 | 主 BM 是否可换 | **可换**。约束只是「同一账户至多一个主 BM」 | 2026-10-06（用户更正） |
| 3 | 所属渠道 / 资产类型 | **新建两张 platform 级公共选项表**，不复用 `agents` | 2026-10-06 |
| 4 | 单价 / 入库 / 出库 | `TEXT DEFAULT ''` | 2026-10-06 |
| 5 | 操作人 | **冻结字段**：INSERT 时定，此后无写入路径 | 2026-10-06 |
| 6 | 在用运营 / 接户运营 | **在用运营 = 现有 `owner_id`**（实际归属）；**接户运营 = 新字段** | 2026-10-06 |
| 7 | 归属变更权限 | 维持现状（`CROSS_USER_ROLES`），普通运营改不了 | 2026-10-06 |
| 8 | 10 个新字段的用途 | 全部**系统内可操作 + 双向同步**，无「户管自用、系统不碰」的列 | 2026-10-06 |
| 9 | UI 视觉 | **不走 `/frontend-design`**，沿用 GG / TT 既有样式 | 2026-10-06（用户指定） |

> 决策 9 的说明：用户原话「ui这次不走 /frontend-design。跟着 gg 和 tt 的审美就好，
> 不然需求量太大，后续不满意我会自己调整」。这是对 CLAUDE.md「新 UI 须先走
> `/frontend-design`」的一次**明确豁免**，仅适用于本子项目，不构成对后续需求的先例。

---

## 三、范围边界

### 做

- `fb_accounts` 新增 10 列
- 两张公共选项表（`fb_channels` / `fb_asset_types`）+ 各自 CRUD 接口
- `fb_account_bm.is_primary` + 部分唯一索引
- FB 账户创建 / 编辑接口承载新字段
- **FB 归属变更端点（`reassign`）** —— ② 的「户归属」列需要它，FB 目前没有
- FB 账户面板与设置页的 UI 扩充

### 不做（YAGNI）

- 看板列映射、表 ↔ 系统双向同步（子项目 ②）
- 撤回（子项目 ③）
- 存量 FB 账户的历史数据回填 —— 新列一律取默认值
- FB 的 BM / 像素 / 产品域改动

---

## 四、数据结构

### 4.1 `fb_accounts` 新增 10 列

| 看板表头 | 列名 | 列定义 | 说明 |
|---|---|---|---|
| 操作人 | `operator` | `TEXT DEFAULT ''` | **冻结**，见 6.1 |
| 所属渠道 | `channel_id` | `INTEGER REFERENCES fb_channels(id)` | 见 4.2 |
| 资产类型 | `asset_type_id` | `INTEGER REFERENCES fb_asset_types(id)` | 见 4.2 |
| 单价 | `unit_price` | `TEXT DEFAULT ''` | |
| 入库 | `inbound_qty` | `TEXT DEFAULT ''` | 数量 |
| 接户运营 | `acceptor_id` | `INTEGER REFERENCES users(id)` | 不参与归属判定 |
| 出库时间 | `outbound_date` | `TEXT DEFAULT ''` | |
| 出库 | `outbound_qty` | `TEXT DEFAULT ''` | 数量 |
| 消耗 | `consumption` | `TEXT DEFAULT ''` | |
| 产品信息 | `remark` | `TEXT DEFAULT ''` | |

**数值三项存 TEXT 而非 REAL**：与 `tt_accounts.consumption` 同口径（该列也是 `TEXT DEFAULT ''`），
「没填」与「填了 0」可以区分；写 Google Sheet 走 `valueInputOption="USER_ENTERED"`，
到表里仍是数字格式。代价是系统内按数值排序 / 筛选会按字符串比 —— 这三列当下只用于展示与
同步，够用；将来若要排序，另做迁移。

### 4.2 两张公共选项表

```sql
CREATE TABLE IF NOT EXISTS fb_channels (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    name       TEXT NOT NULL,
    owner_id   INTEGER REFERENCES users(id),   -- 只记「谁先建的」，不参与查重
    platform   TEXT DEFAULT 'fb',
    created_at TEXT DEFAULT (datetime('now','localtime')),
    UNIQUE(name, platform)
);

CREATE TABLE IF NOT EXISTS fb_asset_types (   -- 与 fb_channels 同构
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    name       TEXT NOT NULL,
    owner_id   INTEGER REFERENCES users(id),
    platform   TEXT DEFAULT 'fb',
    created_at TEXT DEFAULT (datetime('now','localtime')),
    UNIQUE(name, platform)
);
```

**为什么不复用 `agents`（用户的原始措辞是「就像 gg 里面的代理一样」）：**

`agents` 的唯一约束是 `UNIQUE(name, owner_id, platform)`（`py/database.py:1483-1494` 的迁移重建），
名字唯一性**按 owner 算**。甲、乙各建一个「渠道A」(fb) 会落成两行；而 `_resolve_field` 的口径是
「唯一命中才落库」（`py/huguan_dashboard.py:289-296`），表里写「渠道A」会命中 2 条 → 记警告、
**这一列永远同步不上**。TT 的代理已有此隐患（`_SQL_AGENT_TT` 按 platform 查、不按 owner 查）。

用户要的「公用」在仓库里有更贴的先例：`account_statuses` 的 `UNIQUE(name, platform)`、
`tt_recycle_reasons` 的「全平台公用词表，name 全局唯一」。所以新建两张表，形状照
`account_statuses`。

`owner_id` 只记「谁先建的」，不参与查重 —— 与 `resolve_status_id` 对
`account_statuses.owner_id` 的口径一致（`py/huguan_dashboard.py:229-264`）：
因为唯一约束是 `(name, platform)`，**至多命中 1 行**，不存在「命中 ≥2 条」的歧义档。

### 4.3 「位置」= 主 BM

```sql
ALTER TABLE fb_account_bm ADD COLUMN is_primary INTEGER NOT NULL DEFAULT 0;

CREATE UNIQUE INDEX IF NOT EXISTS idx_fb_account_bm_primary
    ON fb_account_bm(account_id) WHERE is_primary = 1;
```

这是一条**部分唯一索引**，只约束 `is_primary = 1` 的行，因此它保证的是
「**同一账户至多一个主 BM**」，**不阻止换 BM**。

换 BM 的写法（② 读回「位置」列时用）：

```sql
-- 必须在同一事务内，顺序不能反：
UPDATE fb_account_bm SET is_primary = 0 WHERE account_id = ?;              -- ① 先清
UPDATE fb_account_bm SET is_primary = 1 WHERE account_id = ? AND bm_id = ?; -- ② 再设
-- 若该 BM 尚未与该账户关联，② 改为：
-- INSERT INTO fb_account_bm(account_id, bm_id, is_primary) VALUES(?, ?, 1)
```

**顺序反了会撞 `idx_fb_account_bm_primary`**：先设新的（此刻旧的主 BM 还是 1）会立刻
`UNIQUE constraint failed`。SQLite 的唯一索引是**逐语句**检查的，不是事务提交时统一检查，
所以「先清后设」不是代码风格问题，是**正确性问题**。

本子项目只定义该列的存储与约束；「位置」列的读写口径（填了 BM 名 → 换主 BM；空着 → 只把
所有 `is_primary` 置 0、**不删**任何关联行）属于子项目 ②。

---

## 五、迁移

走既有幂等口子，不新造机制：

- **10 个新列** → `_add_column_if_missing(conn, "fb_accounts", ...)`，加进 `_ensure_columns`
  （`py/database.py:91`，每次连库都跑，`ALTER TABLE ADD COLUMN` 幂等）
- **两张新表** → `CREATE TABLE IF NOT EXISTS`
- **`is_primary` 列 + 部分唯一索引** → 只在 `fb_account_bm` 存在时执行
  （`_table_exists` 判断，照 `_ensure_columns` 里既有索引段的写法）

**不动 `fb_accounts` 建表语句的既有列**，纯增量。

存量 FB 账户的 10 个新列全部取默认值（空串 / NULL），列表、编辑、删除行为与改动前一致。

---

## 六、接口

| 端点 | 动作 | 门禁 |
|---|---|---|
| `GET /api/fb/accounts` | 返回 10 个新字段 + 主 BM 名 | 现状（`@fb_required`） |
| `POST /api/fb/accounts/create` | 接受 10 个新字段；**`operator` 由服务端填**，忽略请求体同名键 | 现状 |
| `PUT /api/fb/accounts/<int:aid>` | 接受新字段；**`operator` 拒绝修改**（收到也忽略） | 现状 |
| `PUT /api/fb/accounts/<int:aid>/reassign` | **新增**，见 6.2 | `@fb_required` |
| `GET/POST/PUT/DELETE /api/fb-channels/*` | **新增**，照 `/api/statuses/*` 的形状 | `GLOBAL_OPTION_ROLES` |
| `GET/POST/PUT/DELETE /api/fb-asset-types/*` | **新增**，与渠道同构 | `GLOBAL_OPTION_ROLES` |

### 6.1 `operator` 的冻结

`operator` 写成**创建者的名字快照**（`display_name or username`）：

- 系统内建户 → 当前登录用户的名字
- 从表同步新建（② 的 `apply_diff`）→ 发起该次同步的户管名字

冻结的实现口径是**让它没有写入路径**，而不是「在接口层过滤请求体」：
`INSERT` 语句里出现该列，**`UPDATE` 语句里根本不出现这一列**。
接口层同时忽略请求体里的 `operator`（纵深防御，且让行为对调用方显式）。

`operator` 存名字快照而非 `users.id` 外键，是「固定」这个词的直接要求：用户改名后，
表里的操作人仍是当时的名字。

### 6.2 FB `reassign`（新增端点）

FB 目前**没有任何归属变更端点**（`py/routes/fb_routes.py` 内 grep `reassign` 为空），
而在用运营 = `owner_id` 决定了户归谁。没有它，② 的「户归属」列在 FB 面板上改不动。

形状照 TT 的 `reassign_account`（`py/routes/tt_accounts_routes.py:466`，
其扩展口径见 `2026-09-23-huguan-sheet-design.md` §7.5）：

- **默认路径**（不带 `owner_id`，或调用者非 `CROSS_USER_ROLES`）→ 维持「转给调用者自己」，
  逐字节保持原行为与原返回文案
- **新增路径**：`CROSS_USER_ROLES` + 合法 `owner_id` → 转给该用户
- `owner_id` 必须是 ASCII 数字串且 ≤ `2**63-1`（照 TT 的校验，`or ""` 兜底不能省）
- 目标用户必须存在（`fb_accounts.owner_id REFERENCES users(id)` 且连接开着
  `PRAGMA foreign_keys=ON`，不校验会以 FK `IntegrityError` 收场变 500）

---

## 七、UI

**沿用 GG / TT 既有样式，不做独立视觉设计**（决策 9）。

- `frontend/src/views/fb/FbAccountPanel.vue`
  - 表格列扩充（现在只有 账户名 / 账户ID / 所属BM / 时区 / 到手时间，`:52-59`）
  - 编辑弹窗从 6 个字段扩到 16 个（`:120` 的 `form`），布局照 TT 账户弹窗
- `frontend/src/views/fb/FbSettingsPanel.vue`
  - 新增两张 `el-card`（所属渠道 / 资产类型），照现有「地区 / 商务人员 / 状态」三张卡的样式
    （`:13` / `:40` / `:66`），编辑入口用 `v-if="authStore.canManageAccounts"` 门控

---

## 八、测试要点

新增 `py/tests/test_fb_asset_model.py`（或并入既有 FB 测试文件）：

1. **迁移幂等**：连续两次取连接不报错；存量行的 10 个新列为默认值
2. **`operator` 冻结**：POST 带 `operator` → 被忽略，落库是调用者名字；
   PUT 带 `operator` → 该列不变
3. **主 BM**：设为 `is_primary=1` 成功；**换 BM 成功**（先清后设）；
   同一事务内**先设后清**会撞 `UNIQUE constraint failed`（把这条顺序约束钉住）
4. **两张选项表**：`UNIQUE(name, platform)` 生效；甲、乙建同名渠道仍只有一行
5. **`reassign`**：`CROSS_USER_ROLES` + `owner_id` → 转给目标；
   不带 `owner_id` → 原行为与原文案逐字节不变；目标不存在 → 400 而非 500
6. **回归**：存量 FB 账户的列表 / 编辑 / 删除行为与改动前一致

门禁：`cd py && python -m pytest tests/ -q`，只增不减。

---

## 九、风险与已知代价

1. **`operator` 是名字快照，不是外键。** 用户改名后表里的操作人仍是当时的名字 ——
   这是「冻结」的应有之义，但 UI 上要让户管看得懂，不能让人以为它跟着改名走。
2. **`fb_accounts` 一次加 10 列**，是本仓库单次改动里较大的一次表结构变更。
   全部是 `ADD COLUMN` + 默认值，**无数据迁移**，SQLite 支持 `DROP COLUMN` 回滚，风险可控。
3. **数值三项存 TEXT**：系统内按数值排序 / 筛选会按字符串比（见 4.1 的取舍说明）。
4. **「所属渠道」与 GG 的「代理」是两套词表。** 若将来发现两者语义重合，
   合并需要一次数据迁移；本次按用户「公用的」口径新建独立表，不做跨平台统一。

---

## 十、范围外

1. FB 看板的列映射与双向同步（子项目 ②）
2. 双向撤回（子项目 ③）
3. 存量 FB 账户的历史数据回填
4. FB 的 BM / 像素 / 产品域改动
5. 「所属渠道」与 GG「代理」的词表合并
