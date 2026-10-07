# FB 账户面板批量能力对齐（设计）

> 2026-10-08。用户原话：「现在 fb 账户的前端界面功能按钮没几个，我功能按钮同步 gg 和 TT 那边的，
> 什么批量查户，批量新增等等」。

## 一、需求描述

FB 账户面板（`FbAccountPanel.vue`）的工具栏只有「新增账户 / 刷新 / 删除」三颗，
而 GG 的 `AdsAccountPanel.vue` 与 TT 的 `TtAccountPanel.vue` 各有七颗。
本次把 FB 缺的**批量能力**补齐，使 FB 用户在账户管理上的操作粒度与 GG/TT 一致。

### 现状对照（2026-10-08 实测代码）

| 按钮 | GG | TT | FB |
|---|---|---|---|
| ➕ 新增账户 | ✓ | ✓ | ✓ |
| 📥 批量导入 | ✓ | ✓ | **✗** |
| 🔍 批量查户 | ✓ | ✓ | **✗** |
| 💰 批量充值 | ✓ | ✓ | ✗（见 §8 范围外） |
| 🔄 同步 | ✓ | ✓ | ✗（见 §8 范围外） |
| 🗑 已删除 / 回收站 | ✓ | ✓ | **✗** |
| 🗑 批量删除 | ✓ | ✓ | **✗** |
| 表格多选列 | ✓ | ✓ | **✗** |

## 二、已确认的决策（用户 2026-10-08 逐条裁定）

| # | 决策 |
|---|---|
| 1 | **范围 = 四项**：批量查户 / 批量新增导入 / 批量删除 / 回收站 |
| 2 | **方案 A**：逐项照搬 GG 的实现（每平台一份），**不抽三平台公共抽象** |
| 3 | **不加角色守卫**：四颗按钮在 FB 面板一律可见；归属隔离仍由后端按 `owner_id` 承担（照 GG/TT 现状） |
| 4 | **不做「同步」按钮**：FB 无「从表格同步账户」通路，那是一个完整新需求，**押后** |
| 5 | **不做批量充值**：FB 无充值表与双写通路，**另立项** |
| 6 | **不动 FB 配置入口**：用户明确「FB 那边户管能看见，不用管」 |
| 7 | 走 **git worktree**（`fb-account-panel-parity`）隔离开发 |
| 8 | 走 **TDD**（AGENTS.md 要求） |

> ⚠️ 决策 3 与一条**押后**的规则要分清：用户另提出「三个平台的『🔄 同步』按钮都要**排除户管**」。
> 因决策 4 把同步整体押后，**该规则本次不落地**；它属于将来做同步那一轮。

## 三、技术方案

### 3.1 后端：`py/routes/fb_routes.py` 新增 3 个端点

**（1）`POST /api/fb/accounts/batch-lookup`** —— 与 GG `accounts_batch_lookup` 同形

- 入参：`{"account_ids": ["<资产UID>", ...]}`；空/非列表 ⇒ 400
- 返回：`{"success": true, "found": [...], "not_found": ["<未命中的ID>", ...]}`
- `found` 每项字段（GG → FB 映射）：`account_id` / `name` / `owner_id` / `owner_name`（`display_name` 回退 `username`）/ `status`（状态名）/ `timezone` / **`bm_name`**（FB 无 MCC，映射为**主 BM 名**）
- **归属隔离**：非 `CROSS_USER_ROLES` 只能查到 `owner_id = 自己` 的行；跨用户角色可查全部，并支持 `owner_id` 收窄

> ⚠️ **不照抄 GG 的既有缺陷。** GG 的 `accounts_lookup` / `accounts_batch_lookup` 目前**没有 owner 条件**
> （已登记在遗留清单 A8，属越权）。FB 版按本文件 `list_accounts` 的既有口径写 —— 见 §7.1。

**（2）`POST /api/fb/accounts/batch-create`** —— 与 GG `accounts_batch_create` 同形

- 入参：
  ```json
  {
    "account_ids": ["<资产UID>", "..."],
    "name_prefix": "", "timezone": "UTC+8", "status_id": null, "bm_id": null,
    "overrides": {"<资产UID>": {"name": "...", "timezone": "...", "status_id": ..., "bm_id": ...}}
  }
  ```
  顶部四项是**共用默认值**，`overrides` 按账户 ID 逐行覆盖（与 GG 同构；`name` 缺省时用 `name_prefix + 账户ID`）
- 返回：`{"success": true, "created": N, "skipped": [...], "errors": [{"account_id": …, "error": …}]}`
- 唯一键 `fb_accounts.account_id` 撞重 ⇒ 回 **「账户 ID 'X' 已存在」**（不是「操作失败」）——
  沿用 2026-10-07 建立的重复键口径 `_is_unique_conflict()`（先锁 `IntegrityError` 类型、再要求原文含 `"unique"`）
- `bm_id` 给了就挂主 BM（`fb_account_bm.is_primary`，**先清后设**的既有约束）

**（3）`POST /api/fb/accounts/batch-delete`** —— 与 GG `accounts_batch_delete` 同形（软删）

- 入参：`{"ids": [<fb_accounts.id>, ...]}`；空 ⇒ 400
- `ids` 元素做 **int64 上界 + 类型闸门**（超界/非 ASCII 数字串 ⇒ 400，不落到 sqlite 绑定）
- 单事务 `UPDATE fb_accounts SET deleted_at=... WHERE id IN (...)`；**归属校验**：非跨用户角色只能删自己的
- 找不到 / 无权删的 id 计入 `not_found`，不报错

### 3.2 回收站：**零后端改动**

`GET /api/fb/accounts/deleted`、`POST /api/fb/accounts/<aid>/restore`、`DELETE /api/fb/accounts/<aid>/permanent`
**均已存在且带归属隔离**。本次只补前端入口。

### 3.3 前端

| 文件 | 改动 |
|---|---|
| `frontend/src/views/fb/FbAccountPanel.vue` | 工具栏补四颗按钮；表格**新增多选列**（现无）；删除类按钮 `:disabled="!selected.length"` |
| `frontend/src/components/fb/FbAccountBatchLookupModal.vue` | **新建**（照 `AccountBatchLookupModal.vue`） |
| `frontend/src/components/fb/FbAccountBatchImportModal.vue` | **新建**（照 `AccountBatchImportModal.vue`） |
| `frontend/src/components/fb/FbAccountDeletedModal.vue` | **新建**（照 `AccountDeletedModal.vue`） |
| `frontend/src/api/fb.js` | 补 `batchLookup` / `batchCreate` / `batchDelete`；回收站三端点如已有则复用 |

## 四、数据结构

**无新表、无迁移。** 复用 `fb_accounts` / `fb_account_bm` / `fb_bms`。

## 五、UI 改动

- 工具栏按钮样式与文案照 GG/TT 既有语汇（emoji + 中文），**不自创视觉**
- 多选列与批量删除的交互照 `AdsAccountPanel.vue`（选中数、批量删除二次确认）
- 回收站弹窗照 `AccountDeletedModal.vue` 的三段式：列表 / 恢复 / 永久删除（永久删除需二次确认）

## 六、测试（TDD）

测试文件：`py/tests/test_fb_platform.py`（fb_routes 既有测试文件）。

**每个新端点三条腿，且必须驱动真实端点**：

1. **归属隔离**：用户 A 查不到 / 删不掉用户 B 的账户（越权 → 不可见 / 403 或计入 `not_found`）
2. **跨用户角色对照**：developer 能查到/操作全部（防「一律隔离」的过度收口变异体）
3. **边界**：空列表 ⇒ 400；`ids` 含超 int64 / 非 ASCII 数字串 ⇒ 400（不是 500）；`not_found` 断言**具体 ID**而非计数

**可证伪性**：每条都要能指出「去掉哪一行生产代码它会变红」。撞重那条要断言**具体文案**（「已存在」而非「操作失败」）。

## 七、风险与必须遵守的约束

### 7.1 不照抄 GG 的越权缺陷
GG 的 lookup 族**没有 owner 条件**（遗留清单 A8）。照搬实现时**只搬形状，不搬这个缺陷** ——
FB 版一律带 owner 过滤。

### 7.2 唯一键与重复键口径
`fb_accounts.account_id` 是 `UNIQUE`；撞重必须走 2026-10-07 建立的
「先锁 `IntegrityError` 类型、再要求 `str(e)` 含 `"unique"`」判据 ——
只判类型会把 FOREIGN KEY / NOT NULL 也误报成「已存在」。
`create_pixel_bm` 那类未收口的口径**不要**在这里复制。

### 7.3 状态解析必须带 `platform='fb'`
`account_statuses` 是 `UNIQUE(name, platform)` 的共享字典，「存活」在 gg/fb/tt 各有一行。
凡按名字取状态行**必须带 `platform='fb'`**，且**不要带 `owner_id`**
（`owner_id` 记的是创建者，与账户归属无关）。AGENTS.md 已记过这个陷阱的两次事故
（GG 侧 43 个账户被写成 fb 的状态 id；`data_service` 的选项导入被整次打崩）。

### 7.4 纯增量
**不改任何 GG / TT 的现有代码**（那正是选方案 A 而非 B 的原因）。

### 7.5 交付后必须提醒用户（AGENTS.md 第 1132-1133 行）
- 前端改动 ⇒ 必须 `cd frontend && npm run build`，否则别人看不到
- 后端改动 ⇒ 必须重启 Flask 服务才生效

## 八、范围外（本次明确不做）

1. **「🔄 同步」按钮**（含用户提的「三个平台都排除户管」规则）—— FB 无 sync-from-sheet 通路，属完整新需求
2. **批量充值** —— FB 无 `fb_recharge_records` 表与双写 Sheets 通路
3. **FB 配置入口 / 户管角色** —— 用户裁定「FB 那边户管能看见，不用管」
4. **三平台公共抽象（方案 B）** —— 会动 GG/TT 在生产运行的代码，收益与风险不匹配
5. GG 的 A8 越权缺口本身 —— 只登记，不在本需求修
