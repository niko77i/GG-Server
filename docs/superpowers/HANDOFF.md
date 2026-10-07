# 交接说明：户管看板三步拆分（① / ② / ③）+ 后续安全工作

> 初版写于 2026-10-07（③ 执行到 Task 2 时交接）。
> **2026-10-07 更新为终态**：③ 已由接手会话完成 Task 3–6，并通过全分支终审。
> **同日再次更新**：③ 之后同一会话续做了三块安全工作（越权收口 / 500 脱敏族 / 全仓遗留清点），
> 见**第八节**。前面的七节仍是 ③ 的记录，未改动。

---

## 一、整体位置：三步全部完成

| 子项目 | 状态 | 关键提交 |
|---|---|---|
| ① FB 资产数据模型 | ✅ 完成并验证 | `bdef5e0` 收尾 |
| ② FB 户管看板 | ✅ 完成并验证 | `8eefcc5` 收尾 |
| ③ 双向撤回 | ✅ **完成并验证** | ③ 区间 `6f0ac9e..ec9d533`，收尾 `ec9d533` |

### ③ 的交付指标（均为**实测**，非转述）

| 项 | 值 |
|---|---|
| 全量测试 | **1250 passed / 0 failed**（接手基线 1154，净增 96 条） |
| 前端构建 | `npm run build` ✓ |
| 全分支终审 | opus 档，**Ready to merge: Yes**，无 Critical、无阻断性 Important |
| 必修项 | 1 条（撤回失败回传原始异常文本），已修并独立核对 |
| 推送状态 | **提交在本地 `master`，未推送**（用户 2026-10-07 裁定保持本地） |

③ 新增的两个接口（spec §7）：

- `GET /api/huguan/dashboard/undo?platform=X` → **平铺**
  `{"success":true, "push": {count, created_at}|null, "sync": …|null}`
- `POST /api/huguan/dashboard/undo` body `{"platform","direction"}`
  → `push` 返回 `{updated, not_found}`；`sync` 返回 `{reverted, conflicts, kept, not_found}`

---

## 二、③ 期间计划外清掉的事（接手会话额外做的）

1. **补做了 Task 2 修复轮 3 的独立回审**（初版交接留的欠账）：结论 Spec ✅ / Approved。
2. **找到并修掉 FB 定位键缺陷族的第 4 处漏网** —— `huguan_dashboard.py` 的 `push_rows`（提交 `fa82338`）。
   详见 §三。
3. **按用户裁定补齐计划漏掉的 3 项 spec 要求**（Task 4/5）：`owner_changes` 的库侧回退
   （含 FB 的 `acceptor`）、`created_statuses` 的无引用清理。
   > 不补的后果很隐蔽：**撤回一次同步，表回退了，但库里的归属改动纹丝不动。**
4. **终审后收尾修复**：`ec9d533`。

**总计：计划与规格/现行代码的实质冲突 6 处**，全部按「spec 与现行代码优先」裁定，
逐处记录在 `.superpowers/sdd/fb-undo/task-{3,4,5,6}-addendum.md`。

---

## 三、跨子项目缺陷族：FB 定位键（**已修全**）

FB 看板的定位键是 **D 列（资产UID）**，而写表函数 `gs.update_rows_by_account_id(...)`
默认 `key_col="C"`（账户名称）。GG / TT 的 `KEY_COL` 都是 `"C"`，所以只有 FB 中招。
**症状是静默的**：找不到行、一个字都不写、**且不抛异常**，后台线程连日志都没有。

**已修 6 处**（覆盖生产侧 `update_rows_by_account_id` 的全部调用点）：

| 站点 | 提交 |
|---|---|
| `dashboard_push`（手动刷新） | `7fc1167` |
| `_write_background`（`/sync` 的 FB 回写） | `71d0bfe` |
| `writeback_fb_acceptor`（`fb_routes` 三端点） | `71d0bfe` |
| **`push_rows`（② 的 FB 自动回写）** | **`fa82338`** |
| `undo_push`（Task 3 新增） | `565bca7` |
| `undo_sync`（Task 5 新增） | `9b31c86` |

已核实**不受影响** 1 处：`writeback_owner_channel`（`OWNER_CHANNEL_COL` 无 fb 键 ⇒
fb 输入会在写表之前先 `KeyError`；且其调用方只传 gg/tt）。

> ⚠️ **`push_rows` 那处意味着 ② 的 FB 自动回写（建号/改态/改归属触发）一直是错的** ——
> 手动刷新是对的，症状因此被局部掩盖。识别它用了**三路独立排查**
> （控制端读码 / Task 2 审查者未经提示自己挖到 / 全仓调用链扫描），三条路汇聚到同一个点。

---

## 四、仍然有效、必须带进后续工作的约束

### 平台与列

- **GG/TT/FB 三平台，任何按平台分流的代码都不能用二元 `else` 兜底** —— 一律字典查表，缺键 `KeyError`。
- **FB 的 `OWNER_CHANNEL_COL` 刻意不含 fb 键**（写的内容语义不同）。
- **`COLUMN_SPEC` 的 `writable` 管「系统→表」，`_PLAIN_TEXT_FIELDS` 管「表→系统」**，两个旋钮正交。
- 表侧写点按平台分流：**GG** 运营列 + 清通道列；**TT** 只撤运营列（无通道列）；
  **FB** 在用运营列 + 接户运营列。

### 数据完整性

- **`fb_account_bm_history` 没有 `ON DELETE CASCADE`**（另两个历史表都有）——
  删新建 FB 账户时**必须先显式删该表历史行**。
- **`fb_accounts.acceptor` 是 TEXT**（复合串 `"{旧}转{新}"`），按普通文本列处理，不做名称解析。
- **`fb_account_bm.is_primary` 是部分唯一索引**，换主 BM 必须**先清后设**。
- **`huguan_sync_undo.user_id` 无 `ON DELETE`** —— 已加入 `admin_delete_user` 的清理清单
  （`py/main.py`，提交 `e4ccbe3`）。**将来再加带 `user_id` 外键的表，必须同步加进那个清单。**
- **表→系统撤回顺序铁律：先表后库**（spec §6.2 有「反了会怎样」的推演）。

### ⚠️ 「静默失效」是本子项目反复出现的失败模式

**出现了三次，全部不报错**：

1. FB 路径不传 `key_col` ⇒ 写表全落 `not_found`、一字未写；
2. `apply_diff(collect_undo=True)` 忘传 `sheet_from` ⇒ `sheet_back` 全空、**表侧撤回静默失效**；
3. `GET /undo` 的 sync `count` 只数了两类 payload（共五类）⇒ **按钮亮着却显示「影响 0 项」**。

**凡新增「按平台/按方向取数据」的路径，都要问一句：漏了参数会怎样？会不会安静地什么都不做？**

---

## 五、遗留项（都已记账，尚未处理）

### 需要用户决策的

- **`py/main.py` 的两会话撞车只被绕开、没有解决。** 并行会话给 `py/main.py` 加了
  `from logging_setup import setup_logging`，而 `py/logging_setup.py` 是**未跟踪的新文件**。
  ③ 的 Task 6 恰好也要改 `py/main.py` 的 `admin_delete_user`；控制端用「只动索引」的分步法
  （`git apply --cached -R` 摘掉别人的 hunk）完成了干净提交，**工作区一字节未碰**。
  但隔壁的改动仍悬着 —— 谁若 `git add -A` 就会产生**坏提交**（import 不存在的模块）。
  > **2026-10-07 更新：已消解。** 隔壁会话随后自行把日志基建（含 `py/logging_setup.py`）
  > 一并提交，`py/main.py` 已回到干净状态，上述风险不复存在。

### 建议尽快处理的（与 ③ 无关，终审已登记）

- ⚠️ **`_migrate_account_status_platform` 每次 `get_db()` 都跑**，会**静默改写**
  GG `accounts.status_id` 的引用 ⇒ 删状态行在那个腿上**并不可靠地受外键保护**。
  ③ 的 Task 5 实现者指出这与 **2026-09-24 的「69 户 status_id 悬空」事故同源**。
  它与「Task 5 的三表引用检查里 GG 那条腿恰好缺独立测试」叠加，是当前残余风险最高处。
- 两套「我的看板」布局并存是潜在陷阱：`update_cell_by_account_id` **硬编码按 B 列定位**并假设
  GG 布局，而 TT 的「我的看板」是 D=广告账户ID。当前 6 个调用点**全在 GG 路径**（受
  `require_platform('gg')` 守卫）⇒ 现状无实害；但将来任何 TT/FB 路径复用它，会立刻变成同族命中。

### 已登记待分诊的 Minor

**20 余条**，全部汇总在 `.superpowers/sdd/fb-undo/final-minors-rollup.md`，
终审已逐条判过「必修 / 可留待」（**仅 A7 判为必修，已修**）。
其中一条已被用户裁定接受：前端**既有两个按钮的间距 8px→24px**（为给每个按钮配一行小字）。

另有一条已被裁定接受、值得写明的**已知代价**（已补进 spec §十一）：
**`sync` 撤回的字段类回退不跨下一次同步持久** —— `sheet_back` 只覆盖归属/运营相关的表侧列，
字段类更新（如 `unit_price`）只在库里回退、表里不回退，下一次同步会重新把表里的新值 diff 出来落库。

---

## 六、过程教训（写给接手者，也写给未来的我）

1. **计划里的示例代码必须落笔前核对现行代码。** ② 的计划被实现者抓出 **17 处**「照抄就会失败」；
   ③ 把这条写进了 Global Constraints，效果立竿见影 —— 但它**仍不够**：
   ③ 期间另有 **6 处**计划与规格/现行代码冲突，其中 Task 4 那处最典型（见下条）。
   **新计划请沿用这条约束。**

2. **「计划的 `git add` 名单」是计划作者知识边界的映射。**
   Task 4 的冲突线索是：计划要改 `build_diff` 的 `owner_changes` 项，而它的 `git add` 名单里
   **没有**那个测试文件 ⇒ 计划**不知道**那条哨兵存在（那条哨兵用等号钉住该项的键集，
   docstring 明写「也钉住没有夹带别的键」）。**照抄就会红，而且会以为是自己的错。**
   **以后拿到计划先看它的 `git add` 名单，与「必须改的文件」对照，差额就是计划看不见的守卫。**

3. **计划里写死的「口径公式」会随 spec 补齐而失效。** 见 §四 的静默失效第 3 条。
   **补 payload 字段时，要顺手把所有消费该 payload 的计数/展示口径一起过一遍。**

4. **不要让生产迁就测试。** ③ Task 2 首轮为了迁就一个 stub 不全的测试，去放宽了生产错误处理；
   控制端裁决改为修 stub。实现者自己如实标了「动机部分是测试形状造成的」——**这种诚实值得鼓励，
   它让纠错能当场发生。**

5. **审查规则要把「自证式空转的测试」当 Important。** 判据是「去掉对应的生产行，这条测试会不会变红」。

6. **跨子项目的缺陷会躲在两轮审查之间。** FB 定位键那个 bug 在 ② 的三轮审查里都没出来，
   因为每一轮都只看自己那部分；它的第 4 处（`push_rows`）又躲过了 ③ 的前五轮审查。
   **终审用最强档模型是值得的** —— ③ 的终审（opus）挖出了任务级审查一致漏掉的 count 口径不一致。

7. **并行会话共用工作区是真实风险，不只是「不干净」。** 带上别人的 hunk 可能造成**坏提交**
   （import 一个未提交的新文件）。可用的安全做法：把别人的 hunk 备份成 patch，
   `git add` 后 `git apply --cached -R` 只从**索引**里摘掉 —— 工作区不动。
   **绝不要**用 `git stash` / `git checkout` / `git restore` 去动别人的改动。

---

## 七、去哪里找详细记录

| 内容 | 位置 |
|---|---|
| ③ 的完整进度账本（含每条裁定、每条 Minor、每次独立实测） | `.superpowers/sdd/progress.md` **最后一节** |
| 计划偏差裁定（4 份，权威性高于计划原文） | `.superpowers/sdd/fb-undo/task-{3,4,5,6}-addendum.md` |
| 遗留 Minor 汇总（终审已分诊） | `.superpowers/sdd/fb-undo/final-minors-rollup.md` |
| 各任务 brief / report / 审查包 | `.superpowers/sdd/fb-undo/` |
| ③ 的接口与三平台表侧写点 | `docs/superpowers/specs/2026-10-06-huguan-sync-undo-design.md` |

---

## 八、③ 之后同一会话续做的安全工作（2026-10-07）

> **不在 ③ 的计划里。** 起因是「这个仓库还有什么没完成」的盘点：先发现 **② 的计划第 1109 行
> 点名要顺带修的 3 条 ② 遗留一处未做**，再做了一轮**全仓遗留清点**（`leftover-audit.md`，
> 仍成立约 140 条），并据其修掉两组**从未有人承接的活跃缺陷**。
> **全部提交在本地 `master`，未推送。**

### 8.1 ③ 自身的补完

| 提交 | 内容 |
|---|---|
| `ffdfb3d` | 补 **spec §十 第 1/2 条**漏掉的 3 条回归测试（push 写表失败→不留快照 / 空写→作废 / `not_found` 透传）。**落笔即绿** —— 生产本来就对，缺的只是测试 |
| `87b624d` | **计划第 1109 行点名的 3 条 ② 遗留**（建号位置名解析失败静默 / `updated` 计数偏高 / 主 BM 查软删未带 `deleted_at IS NULL`）—— Task 4/5 都重写了 `apply_diff` 却没修 |

### 8.2 越权收口

- **`0390cd4`** —— `pixels` / `pixel-bms` 两族（`fb_routes.py`）。`fb_required` 只卡「是不是 FB 用户」
  **不卡归属** ⇒ **任何 FB 用户可改/删他人像素、软删他人 BM、往他人 BM 塞像素**。
  收口 7 个端点（另 3 个本已正确）。**TDD 证据特别可信**：还原改动前跑新测试类得到 7 failed / 5 passed，
  失败的恰是 7 条越权用例、通过的恰是「本人成功 + 跨用户角色成功 + 契约对照」。

### 8.3 500 脱敏族（CWE-209）—— **六个提交、五轮才收干净**

| 提交 | 内容 |
|---|---|
| `66b4b0c` | 全局 500 兜底改固定文案（**并从 `__main__` 块移到模块级** —— 原先以导入方式拉起时根本不生效）；GG 三字段 + TT `<int:aid>` 闸门 |
| `047370f` | `reassign` 自吞异常 + GG `<int:aid>` 9 条 + batch `ids` + 全仓 `str(e)` 20 处 |
| `e9f5ce9` | `f"...{e}"` 直接内插形态 + 单引号变体 |
| `f4776a9` | **按数据流**收口：`fb_routes` 12 处、三个「异常落库列 → 读取端点回出」、Google typed 源头、FFmpeg stderr 等 13 文件 |
| `c679ad1` | `apply_diff` 逐行 `errors[].error` |
| `c096856` | 上游 AI 响应体 + FB 重复键回「已存在」+ 裸 `KeyError` |

**⚠️ 这一段的核心教训不是「修了什么」，而是「为什么修了五轮」：**

1. **前三轮每轮只 grep 一个字符串字面量**（先 `str(e)`、再 `{e}`、再单引号变体）——
   **换汤不换药**，所以每轮只能修到「上一轮那个串能命中」的站点。
   第四轮换成**按数据流扫**（异常文本落到哪里 → 哪些落点被读取端点回出去），一下多收 4 处。
   封版审查再换成**从响应体出口反查值的来源**，才找到 `main.py:11243/11366`
   （**上游 AI 服务商的原始 HTTP 响应体**直通客户端）—— 它不是本地异常变量，**任何 grep 都命中不了**。
   ⇒ **同一判据的两种实现不是独立验证。**
2. **因为并行会话而临时排除的文件，对方落地后必须主动回来收。**
   `fb_routes.py` 的 12 处就是这么漏掉的：派单时写了「不要碰它，另一条线在改」，
   而那条线落地后没人回填，后来还被解释成「有意保留」。**别把「暂时排除」说成「有意保留」。**
   （控制端自身也犯过一次，见 §8.3 的 `c679ad1`。）
3. **脱敏不能牺牲可用性。** FB 侧一度把「重复键」信号也一并砍成「操作失败」，
   而 **GG / TT 两侧都保留了「已存在」** ⇒ 用户再也分不清撞重与真故障。封版审查用**跨平台口径对照**抓到的。

### 8.4 顺带修掉的既有功能性 bug：`/api/ad-reports/analyze` 必 500

`ad_reports_analyze` 读完配置就 `db.close()`，而 `_yt_db()` 返回的是 `flask.g` 里的**请求级共享连接**；
函数下面又调 `_yt_db()` 取回**同一个已关闭的连接** ⇒
**只要 AI 分析被启用、用户提问就必 500**（`Cannot operate on a closed database`）。
**只有「已启用」的请求会走到第二段**，所以既有测试一直没暴露它。
引入者是更早的 `36ca5d1`（非本轮）。修法：去掉那句 `close()`（仓库口径见
`google_sheets_update_zuobiao` 里那条明文注释：`_yt_db()` 的共享连接不在函数中途关）。

### 8.5 ★ 仍然挂着、需要裁决的（**未修**）

| # | 项 | 说明 |
|---|---|---|
| 1 | **`products` / `lines` 族的间接绕过** | 用自己的产品可经 `fb_lines.pixel_id` JOIN 读回**他人像素名/外部号** ⇒ 8.2 的收口**端到端没闭合** |
| 2 | **`bms` 族同类越权** | `update_bm` / `delete_bm` / `bm_options` / `ban_and_migrate` —— 与 8.2 同一种越权，作用在 `fb_bms` 上 |
| 3 | **A7 `regions` 旁路写** | 登录用户可经 `/api/ad-reports/save` 等触发 `INSERT OR IGNORE INTO regions`。**属产品语义决策**（普通用户录数据时能否自动建地区），不是纯安全修复 |
| 4 | **A8 四处越权** | `accounts/lookup`、`accounts/batch-lookup`、`mcc/<mid>/detail`、`mcc/<mid>/link`（后者牵扯「链接 MCC 要不要所有者同意」的产品语义） |
| 5 | **存量数据** | 四个错误列（`recharge_records.sheets_error`、`tt_recharge_records.sheets_error`、`sheets_sync_log.error_msg`、`sheet_write_log.error_msg`）里**历史写入的异常原文仍在库里**，读取端点仍会原样回出。本族只保证「不再写入」；清洗属数据变更 |
| 6 | **`_migrate_account_status_platform` 每次 `get_db()` 都跑** | 会静默改写 GG `accounts.status_id` 的引用 ⇒ 删状态行在那个腿上并不可靠地受外键保护。**与 2026-09-24「69 户 status_id 悬空」事故同源** |
| 7 | `/api/audio-replace/history` | 回服务端绝对路径给**任意登录用户，且无归属过滤**（IDOR，另账） |
| 8 | **~140 条 Minor** | 逐条判据见 `.superpowers/sdd/fb-undo/leftover-audit.md` |

### 8.6 账本可信度的提醒

本轮清点时发现**至少三处「账本说已修、实际没修」**：
`accounts_create` 的 Unicode 数字路径、`_migrate_account_status_platform`、
以及 int64 那一族「标了已了结但三处都没修全」。⇒ **这份账本的可信度没有它看起来那么高；
接手时对关键结论要落到现行代码上复核。**
