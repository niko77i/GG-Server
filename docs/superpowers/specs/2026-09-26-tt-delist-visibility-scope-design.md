# TT 掉包可见性收窄（去掉 developer/admin 特权）设计文档

> 日期：2026-09-26
> 触发：用户报告「我不是在跑人员，为什么掉包弹窗会通知我」
> 关联文档：[TT 掉包通知（独立机器人）](2026-09-24-tt-delist-notification-design.md)
> 状态：**已实现（2026-09-26，提交 `e4d6fa2` + `38c8e80`）**

---

## 1. 需求描述

### 1.1 现象（用户原话）

> 这个TT系统的 我也不是在跑人员，为什么掉包弹窗会通知我 老虎99RS-GGB-G01-GG-TT，我登陆的carl账号

### 1.2 根因（已查证，非推断）

`py/routes/tt_routes.py` 的 TT 掉包两个查询接口各有一条**角色特权分支**：

```python
if role in ('developer', 'admin'):
    params = [...]          # 不加任何可见性过滤 → 看全部
else:
    ... owner_id 或在跑人员过滤 ...
```

已用接口原样的 SQL 独立复现两个分支：

| 分支 | 结果 |
|------|------|
| developer/admin 分支（carl567 id=1, role=developer） | `老虎99RS-GGB-G01-GG-TT / 99RS-GGB-G01-99rsFalse-TT` ← **恰是用户看到的弹窗** |
| 非特权分支（同一 uid 走 else 路径） | **空** |

生产库事实：
- `carl567`（id=1）role = **developer**
- carl 在 TT 全部产品的在跑名单里 **0 条**
- 该产品 owner 是 id=23（`LM123`，且是该产品唯一的在跑人员）

⇒ 弹窗**只**因角色特权分支而出现，与在跑身份无关。用户的判断正确。

### 1.3 目标行为（用户裁定，含一次复查改回）

**裁定 1**（2026-09-26）：两处都收窄 —— 去掉 TT 掉包可见性中的 developer/admin 特权分支。

**裁定 2 的来龙去脉**（记录来路，避免后人误改）：
- 初答「owner 轴也去掉」→ 我随后查到**新证据**：`test_owner_sees_own_delisted_notification`
  是具名的既有行为断言，且 TT 设计文档 `2026-09-24-tt-delist-notification-design.md:159`
  明文写「其余按 `owner_id` 或在跑人员」—— **owner 轴是设计过的需求**，不是顺手写的过滤条件。
  另说明：GG 无 owner 轴是因为 GG 的 `products` 表**压根没有 owner 列**（产品共享，
  只能用 `runner_ids` 划范围），那是「只有这一条轴可用」，不等于「刻意排斥 owner 看自己的产品」。
- **改回：保留 owner 轴。**

最终口径：

> **TT 掉包可见性 = 产品归属人（`owner_id`）∪ 在跑人员（`tt_product_runners`）。**
> **无 developer/admin 特权。**

即：**只删特权分支，`else` 路径原样升格为唯一路径。**

---

## 2. 为什么这是「对齐 GG」的正确做法

设计文档 `2026-09-24-tt-delist-notification-design.md` 自称「对齐 GG」，但把 TT 可见性定义成
**沿用 TT 自己的 `delist_status` 传统**（该文 `:93`「developer/admin 全部」、`:159`「developer/admin 看全部」）。
这两句与实际要达成的目标**自相矛盾** —— 因为 GG 侧根本没有角色分支。

已核实（`grep -n "role in ('developer', 'admin')" py/main.py` → **无任何命中**）：

| 接口 | GG 侧（`py/main.py`） | TT 侧（`py/routes/tt_routes.py`） |
|------|----------------------|-----------------------------------|
| `delist-status` | `:3678`，**无角色分支** | `:729`，**有** developer/admin 全看分支 |
| `delist/pending` | `:3757`，**无角色分支** | `:762`，**有** developer/admin 全看分支 |

GG 侧的可见性条件（`main.py:3694-3696`）逐字为：

```sql
AND (EXISTS (SELECT 1 FROM product_runners pr WHERE pr.product_id = prod.id AND pr.user_id = ?)
     OR prod.runner_ids = ? OR prod.runner_ids LIKE ? OR prod.runner_ids LIKE ? OR prod.runner_ids LIKE ?)
```

GG 只有 runner 一条轴，且 **GG 没有 owner 概念可对齐**（`products` 表无 owner 列）。
故本次的对齐目标是**语义对齐**：可见性只由「与该产品有实际关系的人」决定，
**不因角色而放大**；而不是逐列照抄 GG 的 SQL。TT 的「实际关系」= 归属 ∪ 在跑。
本次改动就是**删掉 TT 独有的那条角色特权分支**，使两侧在这一点上同构。

---

## 3. 技术方案

### 3.1 改动点 1：`delist_status`（`py/routes/tt_routes.py:729`）

删掉 `if role in ('developer', 'admin')` 分支，`else` 路径的 where/params 原样提升为唯一路径：

```python
def delist_status():
    """获取当前用户可见的掉包检测状态（按归属/在跑人员，无角色特权）。"""
    db = get_db()
    uid = get_uid()

    base_sql = (...)   # 不变
    where = (
        "WHERE dc.is_delisted = 1 AND prod.is_archived = 0 AND "
        "(prod.owner_id = ? OR pkg.product_id IN "
        "(SELECT product_id FROM tt_product_runners WHERE user_id=?)) "
    )
    rows = db.execute(base_sql + where + "ORDER BY dc.checked_at DESC", [uid, uid]).fetchall()
    ...
```

同时删除因此变为**未使用**的局部变量 `role = _get_role(db, uid)`（`:736`）。

### 3.2 改动点 2：`delist_pending`（`py/routes/tt_routes.py:762`）

删掉 `:803-804` 的特权分支，`else` 的追加段原样无条件执行：

```python
    base_sql += (
        "AND (prod.owner_id = ? OR pkg.product_id IN "
        "(SELECT product_id FROM tt_product_runners WHERE user_id=?)) "
    )
    params = [uid, uid, uid]
```

> **参数顺序**：`params` 第一个 `uid` 属于 `base_sql` 里的
> `LEFT JOIN tt_delist_notifications ... AND dn.user_id = ?`，
> 后两个属于追加的过滤。追加段在 SQL 文本中位于 `LEFT JOIN` 之后 ⇒ 顺序为 `[uid, uid, uid]`，不可颠倒。

同时：
- 删除未使用的 `role = _get_role(db, uid)`（`:785`）—— 已核实该变量在函数内**仅** `:803` 一处使用。
- 更新 docstring（`:769`）：「可见性与 delist_status 一致：跨用户角色看全部，其余按 owner_id 或在跑人员」
  → 改为「可见性按 owner_id 或在跑人员，**无 developer/admin 特权**」。
- 更新 `:779-783` 平台闸门注释：该注释后半句「developer / 户管 属 PLATFORM_SWITCH_ROLES 直接放行，
  户管不命中任何 TT 产品 → 天然返回空」在改动后对 developer 同样成立（除非其确为 owner/在跑人员），
  措辞需相应修正，但**平台闸门本身保留不动**。

### 3.3 明确不动的部分

| 项 | 决定 | 理由 |
|----|------|------|
| `@tt_required`（`delist_status`） | **保留** | 平台闸门，与角色可见性是两条正交的轴 |
| `require_platform('tt')`（`delist_pending`） | **保留** | 同上；且静默返空是为避免 30s 轮询的 403 噪声 |
| `prod.owner_id` 过滤轴 | **保留** | 设计文档 `:159` 明文需求，有具名测试钉住（见 §1.3 裁定 2） |
| Telegram 通知受众 | **不动** | `send_tt_delist_notifications`（`:613`）本就只从 `tt_product_runners` JOIN `users` 取人，**口径已正确**，无特权问题 |
| 前端 | **一行不改** | `frontend/src/App.vue:95-180` 的 `checkDelistNotifications` 无任何角色过滤，完全按后端返回渲染；后端收窄后前端自然跟随 |

---

## 4. 影响面实测（改前已量化，只读查询生产库）

TT 生产数据共 **12 个产品**（1 个已归档）：

| 检查项 | 结果 | 含义 |
|--------|------|------|
| 真正有掉包记录的产品 | **3 个**（#2 / #3 / #5） | 其 owner **全部同时是在跑人员** → 改后照样可见 |
| 因本次改动而失去可见性的人 | **carl（developer，非 owner 非在跑）** | 正是用户要消除的那个误报 |

本案验证：产品#2「老虎99RS-GGB-G01-GG-TT」owner `LM123` 本身即在跑名单 → 改后**照常收到**弹窗；
只有 carl（developer、非 owner、非在跑）不再收到。**正是用户要的结果。**

⇒ 改动**不影响任何真实业务可见性**，只消除 developer 的越权可见。

---

## 5. 涉及的文件 / API

| 文件 | 改动 |
|------|------|
| `py/routes/tt_routes.py` | `delist_status`（:729）、`delist_pending`（:762）删角色分支；删 2 处未用 `role` 变量；改 2 处注释/docstring |
| `py/tests/test_tt_delist_notification.py` | 改写 `test_developer_sees_all`（见 §7） |
| `docs/.../2026-09-24-tt-delist-notification-design.md` | 修正 `:93` / `:159` 两处相反表述 |
| `AGENTS.md` | TT 掉包通知段补「可见性无角色特权」口径 |
| `frontend/` | **不改** —— 无需 `npm run build` |

**API 契约不变**：路由、方法、响应结构（含 `platform: "tt"` 标记）全部不动，仅**返回集合收窄**。

---

## 6. 数据结构

无数据库结构变更。无迁移。三张相关表（`tt_delist_checks` / `tt_delist_notifications` / `tt_product_runners`）schema 与数据均不动。

---

## 7. 既有测试影响（已逐条查证）

**只有 1 条会红**（保留 owner 轴的直接收益）：

| 用例 | 位置 | 影响 | 处置 |
|------|------|------|------|
| `test_developer_sees_all` | `test_tt_delist_notification.py:116` | **必红** —— 产品 owner 是 `ttuser_dev`，developer 既非 owner 也非在跑人员，收窄后返回 0 条 | **改写**为 `test_developer_no_longer_sees_all`，断言 developer 对**他人**产品返回 0 条 |
| （新增）developer 作为在跑人员 → 可见 | 同上 | — | **正向对照**：防「整个接口对 developer 返空」的假绿 |
| （新增）非在跑人员看不到他人掉包 | 同上，`delist-status` | — | 补 `test_tt_routes.py` 注释段留下的**越权回归缺口** |
| `test_owner_sees_own_delisted_notification` | 同上 `:62` | **仍绿**（owner 轴保留） | 不动 |
| `test_multi_package_grouped_into_one_notification` | 同上 `:188` | **仍绿** | 不动 |
| `test_first_takes_priority_over_reminder_in_group` | 同上 `:193` | **仍绿** | 不动 |
| `test_dismiss_then_reminder_after_3min` | 同上 `:229` | **仍绿** | 不动 |
| `test_non_tt_platform_admin_sees_nothing` | 同上 `:173` | **仍绿**（平台闸门保留） | docstring 理由过时，措辞微调 |
| `TestHuguanTtDelist...`（户管） | `test_huguan_role.py:1199` | **仍绿** —— 户管 role 是 `'huguan'`，本就走 else 分支 | 不动 |
| `test_delist_status_scope` 等 | `test_tt_routes.py:395/429/434` | **整段已注释**（2026-09-24 因真实外发 Telegram 停用） | 不动 |

> ⚠️ `test_tt_routes.py` 注释段自带警示 —— 横向越权防护因此**失去回归测试**。本次顺带把
> 「非 owner/runner 看不到他人掉包」这条腿补回来（既有 `test_user_does_not_see_others_notification`
> 覆盖 pending，但 **`delist-status` 侧无对应用例**）。

---

## 8. 验证方式（TDD）

1. **先写失败测试**（改代码之前）：
   - `test_developer_no_longer_sees_all` —— 端到端 `client.get("/api/tt/delist/pending", headers=dev_headers)`，
     断言 0 条。**当前必红**（现为 1 条），红即证根因。
   - 同型覆盖 `delist-status`。
2. **正向对照腿**（防假绿）：把 developer 加入 `tt_product_runners`，断言**能**看到
   → 证接口对 developer 本身有效，只是不再有特权。
3. **owner 轴保留腿**：owner 无在跑人员时**仍可见**（钉住裁定 2 的复查结论）。
4. **非 owner/runner 的普通用户**看不到他人掉包（`delist-status` 侧补缺）。
5. **回归**：`pytest py/tests/test_tt_delist_notification.py py/tests/test_huguan_role.py py/tests/test_tt_appstore_package.py`
6. 两条腿**必须有一条走真实 HTTP 入口**（`client.get(...)`），不得只调内部函数。

---

## 9. 边界与风险

- **不产生新泄露**：改动方向是「收窄」，最坏结果是该看到的人看不到（可见性不足），不是多看到。
- **两条轴兜底**：owner 与在跑人员任一命中即可见，覆盖产品归属人与实际执行人。
- **`role` 变量删除**已核实无其他引用，不会引入 NameError。
- **与 GG 的差异点（有意保留）**：TT 多一条 owner 轴。这是 TT 产品有归属人而 GG 产品共享
  所致，属**结构性差异**，不是特权，故不在本次收窄范围。
