# 写表失败统一治理（三期：户管看板域接入）设计

> **日期**: 2026-10-08
> **状态**: 已确认（2026-10-08）
> **前置**: 一期（基建 + TT 回收清单，已在 master）/ 二期（GG 平台 9 点，已合入 master `027abfc`+`2a02e40`）
> **范围**: 收口全仓**仅剩的「只写日志」区** —— 户管看板域 5 个写表点

---

## 1. 需求与背景

用户最初的要求：「**所有**异步操作写表失败，都应提示加重试以及回滚」，且失败提示要给出原因、只在**最终结果**产生时发出。

一期交了基建（`py/sheet_write.py` 的 `run_write`/`run_write_many` + `sheet_write_log` + `/api/sheet-write/*`）与 TT 回收户清单；二期把 GG 的 9 个写表点接了进来。

**三期收口最后一块「静默」区**：户管看板域的 5 个写表点，全是 `lambda s, e: log.warning(...)` —— 写失败只落服务端日志，**用户完全看不见、也重试不了**。做完这块，全仓「异步写表失败静默」清零（只剩 FB 域与 TT 充值两个非静默项）。

---

## 2. 现状（运行时核实）

| # | 点位 | 写什么 | 表主人 |
|---|---|---|---|
| 1 | `huguan_dashboard.py:1526`（`push_rows` 内） | 户管看板整行回写（`update_rows_by_account_id`） | `get_platform_config(db, user_id)` ⇒ **操作者自己的** |
| 2 | `huguan_dashboard.py:1778`（`push_remark_to_operator_dashboard` 内） | **投手看板备注**（`key_col="D"`） | 入参 `owner_id` = **账户 owner（第三方）** |
| 3 | `huguan_dashboard.py:1835`（`writeback_owner_channel` 内） | 归属变更通道列 | 操作者自己的 config |
| 4 | `huguan_dashboard.py:1873`（`writeback_fb_acceptor` 内） | FB 接户运营列 | 操作者自己的 config |
| 5 | `huguan_dashboard_routes.py:452`（`_write_background` 内） | 户管看板回写（sync 端点收尾） | 户管的（端点户管专属） |

**准确表述**：5 处中**只有 #2 写的是第三方的表**；其余 4 处写的是「操作者自己的」看板配置（而这些操作只有户管会做，故操作者即表主人）。

> 这一点在设计评审时必须摆在台面上：用户对「失败提示给谁」的裁决是**给看板的主人**。
> 在 4/5 的点位上它与「给操作者」等价，只有 #2 真正区分二者。
> 该裁决仍然正确（口径统一，且 #2 那种情况不会被漏掉），但**不要把它说成「普遍地给第三方」**。

### 2.1 关键结论：本期同样 **零回滚**

5 个点全是 `update_rows_by_account_id` 一类的**镜像写**（表内容 = 系统状态的投影，源在 `accounts` / `fb_accounts` / 归属字段）。按一、二期的口径，**一律不注册 `rollback`**，最终失败落 `retry_failed`。

---

## 3. 目标行为

1. 5 个点的**最终失败**产生持久记录（含原因），**表主人**可查、可重试
2. 提示只在最终结果产生时发出（沿用既有状态机，无需改动）
3. 前端：表主人在某处能看到「你的看板有 N 处没同步上」并可重试
4. **不做业务回滚**
5. `sheet_write_log.user_id` = **表主人**（不是操作者）—— 这是本期与二期的一处**有意差异**

---

## 4. 架构

### 4.1 四个 target（**不是五个** —— 实施前勘察后合并）

勘察发现 **#1（`push_rows`）与 #5（`_write_background`）写的是同一张表的同一批列** ——
都是「把该账户的整行刷新到该户管的看板」。故合并为一个 target，全期 4 个：

| target token | business_key | 表主人如何取得 | 覆盖点位 |
|---|---|---|---|
| `huguan_dashboard` | `account_id` | 调用方传入的 `user_id`（= 表主人，因只有户管会触发） | **#1** + **#5 的 :159/:180** |
| `huguan_owner_channel` | `account_id` | 同上传入的 `user_id` | **#3** + **#5 的 :165**（写值或清空，同一列） |
| `operator_dashboard_remark` | `account_id` | **入参 `owner_id`**（账户 owner = 投手）—— 本期唯一真正的第三方 | **#2** |
| `huguan_fb_acceptor` | `account_id` | 调用方传入的 `user_id` | **#4** + **#5 的 :171** |

> **#1 与 #5 合并的代价（须知）**：#5 原本每个点位只写**一列**，而合并后重建走
> `collect_rows_for_push` ⇒ **重试会写该账户的全部可写列**（即整行刷新）。
> 这是**有意的**：重试的语义就是「把这行刷到与系统一致」，且 `cells_for_row` 只产出
> 系统拥有的可写列（**刻意不含**归属变更通道列，规格 §7.2 规则 2），故不会碰到
> 户管自己用公式维护的列。
>
> **勘误（2026-10-08，Task 3 实施发现）**：#5 的 `:171`（fb 换绑记录写 I 列）**不能**走
> `huguan_dashboard` 整行重建 —— 对 `fb` 而言 I 列在 `COLUMN_SPEC` 里 `writable=False`，
> 且 `OWNER_CHANNEL_COL['fb'] is None`，落进整行重建会被**静默丢弃**。本节初稿声称它被覆盖，
> **是错的**。故 `_write_background` 要**三分**：通道列 → `huguan_owner_channel`；
> fb 接户运营列 → `huguan_fb_acceptor`；其余 → `huguan_dashboard`。划分一律**按身份**，
> 不能用 `in`（dict 的 `in` 是按值比较）。
>
> ⚠️ **通道列被 `cells_for_row` 排除**，所以它必须单列一个 target（`huguan_owner_channel`），
> 否则 #5 的 :165（清空通道列）与 #3（写通道列）都无法重建。

### 4.2 rebuild 一律从 DB 重算

与二期同思路：`rebuild` 从 `accounts` / `fb_accounts` / 归属字段重算那几列，不重放快照。**实现时逐点核对「该表那一行的列内容能否从当前 DB 完全重算」** —— 若某列依赖已消失的上下文（如某次操作传入的文本），则该点需把该文本放进 `payload_json`（参考二期的 `dash_uid` 做法）。

> 已知需要 payload 的一处候选：#3 归属变更通道列写的是「旧转新月.日」这类**文本**，未必能从 DB 重算 —— 实现时先读现场。

### 4.3 `run_write_many` 的复用

`push_rows` / `_write_background` 是「一次写 N 户」，应走 `run_write_many`（一个后台线程、N 行日志）。**注意二期踩过的坑**：`sync_fn` 只执行**一次**，必须用覆盖 N 键的工厂（`build_many_sync` 形态），拿单键工厂会让只有第一户被写而 N 行全落 `synced`。

---

## 5. 前端

**这一节是本期的设计难点：表主人在哪里看到它？**

**已裁定的落点（用户 2026-10-08）**：

- 户管看板相关（#1/#3/#5）：户管已有「📊 户管看板配置」卡片（`HuguanDashboardCard.vue`）—— 在此卡片内显示失败汇总 + 重试。
- 投手看板备注（#2）：落在 **TT 账户表**的行上（投手在 TT 账户表看自己的户；TT 没有独立的「投手看板」页面）。
- FB 接户运营（#4）：落在 **FB 账户表**的行上。

两处行内标记均**复用二期已确认的视觉方案**（列位、`width="54"`、三态语汇、文案单源），不重新设计。

**复用而非新设计**：行内标记沿用二期已确认的视觉方案（位置、宽度、三态、文案单源 `frontend/src/utils/sheetWriteUi.js`）。

**⚠️ 二期的一条已知限制在这里会放大**：`/api/sheet-write/status?platform=`（位于 `py/routes/sheet_write_routes.py:26-60`，**不在** `huguan_dashboard_routes.py` —— 初稿写错了位置）**不带 `target`**，同一 `business_key` 跨 target 时只回最新一行。三期的 target 数是 4，而键都是 `account_id` —— **碰撞概率比二期高得多**（同一账户可能同时有 `huguan_dashboard` 与 `operator_dashboard_remark` 两条）。**本期必须给该端点加 `target` 参数**，否则会出现「一个 target 的行遮住另一个」的静默漏报。这是本期**必须做**的后端改动（二期记录为「今日不可达」，三期不再成立）。

---

## 6. 测试

| 用例 | 判据 |
|---|---|
| 5 个点各自登记正确的 target 与 business_key | 逐点 |
| `sheet_write_log.user_id` = **表主人** | 尤其 #2：故意让操作者 ≠ 表主人，断言落在表主人名下 |
| 零回滚 | 最终失败落 `retry_failed`，**不得**出现 `rolled_back` |
| 批量点走 `run_write_many` 且**写全 N 户** | 二期同类守卫（单键工厂会漏写） |
| `/status` 的 `target` 参数 | 同一 business_key 两个 target 各回各的，不互相遮蔽 |
| 前端 | build + 人工清单（无前端测试套件） |

---

## 7. 不做

1. **FB 域剩余写表点**（`fb_routes.py` 自建线程那处 + 2 个同步点）—— 四期
2. **TT 充值** —— 它有记录、非静默，但带着与 GG 侧同源的「首次失败就报警」两分支缺陷；**建议作为独立 bug 修复**，不混进本期
3. **业务回滚** —— 全镜像
4. **重设计视觉** —— 复用二期

---

## 8. 风险与已知代价

1. **/status 加 target 参数是破坏性接口变更**（现调用方不传 target）—— 需保持向后兼容（不传时行为不变），否则会打断一期 TT 与二期 GG 的前端。
2. **#2 是唯一真正「给别人写表」的点** —— 它的 `user_id` 从操作者改为表主人是**行为变更**，需确认表主人（投手）确实有权限重试（`/api/sheet-write/retry` 按 `user_id` 校验，表主人能改自己的行 ✓）。
3. **前端落点已裁定**（§5）：三处均用行内标记复用二期方案；户管看板侧另在配置卡片内做汇总。
4. 前端运行时行为仍无法自动验证（无测试套件）。
