# TT 充值表表头适配 — 设计文档

> **日期**：2026-09-22
> **状态**：待确认

## 1. 需求描述

TT 的充值表（Google Sheets）表头与 GG 不同，需要把 TT 充值写入改成 TT 专用列映射。

- TT 充值表表头（9 列）：

  ```
  时间 | 账户ID | 金额 | 代理 | 运营 | 是否充值 | 账户ID | 金额锁定 | 是否处理
  ```

- **系统只写前 3 列**：时间、账户ID、金额。
- 第 4~9 列（代理 / 运营 / 是否充值 / 账户ID / 金额锁定 / 是否处理）在表格里**已有公式**，系统写入时**不得覆盖这些公式**。
- 时间列由**系统自动写入当前日期**，格式「月/日」（如 `9/22`）。

## 2. 现状

当前 TT 充值复用 GG 的 [append_recharge](../../../py/google_sheets_service.py)（写 7 列）：

```
A账户ID  B金额  C代理  D运营  E时间(留空)  F是否充值(留空)  G状态
```

这与 TT 新表头不匹配，且会覆盖 D~I 列的公式。GG 保持不动。

## 3. 技术方案

### 3.1 新增 `append_recharge_tt()`（纯增量，不影响 GG）

在 [google_sheets_service.py](../../../py/google_sheets_service.py) 新增函数 `append_recharge_tt()`，**只写 A~C 三列**：

| 列 | 表头 | 写入值 | 类型 |
|---|---|---|---|
| A | 时间 | 当前日期，`月/日`（如 `9/22`） | 文本（前导 `'`，防止被解析为日期） |
| B | 账户ID | `account_id` | 文本（前导 `'`，防止 13 位纯数字变科学计数） |
| C | 金额 | `float(amount)` | 数字（供 D~I 列公式计算） |
| D~I | 代理/运营/是否充值/账户ID/金额锁定/是否处理 | **不写入**（保留公式） | — |

实现要点：

- 写入范围 `A{start}:C{end}`，`valueInputOption="USER_ENTERED"`（与现有代码一致）。
- 账户ID、时间用前导 `'` 标记为文本，对齐 FB 代码 `_upsert_rows` 的既有写法（`f"'{account_id}"`）。
- 「找最后一行」改为读 `A:C`、**只看「账户ID」列（B 列）有无数据判断换行**（而非 GG 的 `A:G` / `A:D`，也非 A~C 任意列——时间/金额列有残留但账户ID为空的行会被忽略）。

### 3.2 路由调用切换

[tt_accounts_routes.py](../../../py/routes/tt_accounts_routes.py) 的 `_append_recharge_background._do_sync` 中，把

```python
gs.append_recharge(service, sheet_id, sheet_name, rows)
```

改为

```python
gs.append_recharge_tt(service, sheet_id, sheet_name, rows)
```

`submit` / `batch-submit` / `retry-sheets` 三处共用 `_append_recharge_background`，改这一处即可。`rows` 里的 `agent/operator/status` 字段保留不动，`append_recharge_tt` 只取 `account_id` 和 `amount`。

### 3.3 已知小限制

- 时间在后台线程写入时取「当时」日期；`retry-sheets` 场景下时间可能晚于首次提交日（差异可忽略，不影响对账）。

## 4. 涉及文件

| 文件 | 操作 | 说明 |
|---|---|---|
| `py/google_sheets_service.py` | 修改 | 新增 `append_recharge_tt()` |
| `py/routes/tt_accounts_routes.py` | 修改 | `_do_sync` 改调 `append_recharge_tt` |
| `py/tests/test_tt_accounts.py` | 修改 | 新增 `append_recharge_tt` 单测 |

## 5. UI 改动

无。纯后端写入逻辑变更，前端充值弹窗（TtRechargeModal / TtRechargeBatchModal）与充值记录展示（TtAccountDetailModal）均不涉及。

## 6. 测试计划

单测：mock Google Sheets service，断言：

1. 只写 `A:C` 三列（range 不含 D~I）；
2. 时间为 `月/日` 格式（如 `9/22`），账户ID 带文本标记、金额为数字；
3. 连续多次写入时，追加行号正确（从表头下一行开始）；
4. 判断最后一行只看「账户ID」列：时间/金额列有残留但账户ID为空的行被忽略。
