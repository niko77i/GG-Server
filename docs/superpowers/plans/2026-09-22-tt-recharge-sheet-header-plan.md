# TT 充值表表头适配 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让 TT 充值写表改为 TT 专用 3 列（时间/账户ID/金额），不覆盖 D~I 列公式。

**Architecture:** 在 `google_sheets_service.py` 新增独立函数 `append_recharge_tt()`（纯增量，GG 的 `append_recharge` 不动），只写 A~C 三列；TT 路由 `_append_recharge_background` 改调该函数。

**Tech Stack:** Python 3 / Flask / Google Sheets API v4 / pytest

## Global Constraints

- 纯增量原则：不修改 GG 的 `append_recharge()`，只新增 TT 专用函数。
- 写表只覆盖 A~C 三列，D~I（代理/运营/是否充值/账户ID/金额锁定/是否处理）一律不写，保留公式。
- 时间格式「月/日」（如 `9/22`），系统自动写当前日期。
- 账户ID 用前导 `'` 标记为文本（防止 13 位纯数字变科学计数），对齐 FB 代码 `_upsert_rows` 写法。

---

### Task 1: 新增 `append_recharge_tt()` + 单测

**Files:**
- Modify: `py/google_sheets_service.py`（在 `append_recharge` 之后、`append_recycle` 之前插入新函数）
- Test: `py/tests/test_tt_accounts.py`（文件末尾追加两个测试）

**Interfaces:**
- Produces: `google_sheets_service.append_recharge_tt(service, spreadsheet_id, sheet_name, rows) -> dict`
  - `rows`: `[{"account_id": str, "amount": str}, ...]`（额外字段忽略）
  - 返回 `{"appended": int}`

- [ ] **Step 1: 写失败测试**

在 `py/tests/test_tt_accounts.py` 末尾追加：

```python
def test_append_recharge_tt_writes_only_three_columns():
    """TT 充值写表：只写 A:C 三列，时间月/日文本、账户ID文本、金额数字。"""
    import re
    from google_sheets_service import append_recharge_tt

    fake = mock.MagicMock()
    fake.spreadsheets.return_value.get.return_value.execute.return_value = {
        "sheets": [{
            "properties": {"title": "充值表", "sheetId": 123,
                           "gridProperties": {"rowCount": 1000}}
        }]
    }
    fake.spreadsheets.return_value.values.return_value.get.return_value.execute.return_value = {
        "values": [["时间", "账户ID", "金额"]]
    }

    result = append_recharge_tt(fake, "sheet-1", "充值表", [
        {"account_id": "1234567890123", "amount": "1000"},
    ])
    assert result == {"appended": 1}

    update = fake.spreadsheets.return_value.values.return_value.update
    args, kwargs = update.call_args
    assert kwargs["range"] == "'充值表'!A2:C2"
    written = kwargs["body"]["values"][0]
    assert len(written) == 3
    assert re.match(r"^'\d{1,2}/\d{1,2}$", written[0])  # 时间 月/日 文本
    assert written[1] == "'1234567890123"  # 账户ID 文本
    assert written[2] == 1000.0  # 金额数字


def test_append_recharge_tt_appends_after_last_row():
    """TT 充值写表：应在已有数据后追加，不覆盖已有行。"""
    from google_sheets_service import append_recharge_tt

    fake = mock.MagicMock()
    fake.spreadsheets.return_value.get.return_value.execute.return_value = {
        "sheets": [{
            "properties": {"title": "充值表", "sheetId": 123,
                           "gridProperties": {"rowCount": 1000}}
        }]
    }
    fake.spreadsheets.return_value.values.return_value.get.return_value.execute.return_value = {
        "values": [["时间", "账户ID", "金额"], ["9/21", "111", "500"]]
    }

    append_recharge_tt(fake, "sheet-1", "充值表", [
        {"account_id": "222", "amount": "300"},
    ])

    update = fake.spreadsheets.return_value.values.return_value.update
    assert update.call_args.kwargs["range"] == "'充值表'!A3:C3"
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd py && python -m pytest tests/test_tt_accounts.py::test_append_recharge_tt_writes_only_three_columns -v`
Expected: FAIL，报 `ImportError: cannot import name 'append_recharge_tt'`

- [ ] **Step 3: 实现 `append_recharge_tt()`**

在 `py/google_sheets_service.py` 中，`append_recharge` 函数结束（`return {"appended": len(new_rows)}` 之后、`def append_recycle` 之前）插入：

```python
def append_recharge_tt(service, spreadsheet_id: str, sheet_name: str, rows: list) -> dict:
    """TT 充值表专用：只写前三列（时间/账户ID/金额），不覆盖 D~I 列公式。

    sheet_name: 目标 sheet 名，为空时回退「充值表」
    rows: [{"account_id": "1234567890123", "amount": "1000"}, ...]

    A=时间(月/日,文本)  B=账户ID(文本)  C=金额(数字)；D~I 不动
    """
    import datetime

    effective_name = sheet_name.strip() if sheet_name else "充值表"
    ss = service.spreadsheets().get(spreadsheetId=spreadsheet_id).execute()
    target_sheet = None
    for s in ss.get("sheets", []):
        props = s.get("properties", {})
        if props.get("title", "") == effective_name:
            target_sheet = {
                "name": props["title"],
                "gid": props["sheetId"],
                "rowCount": props.get("gridProperties", {}).get("rowCount", 1000),
            }
            break
    if not target_sheet:
        raise GoogleSheetsServiceError(f"表格中未找到「{effective_name}」工作表")

    sheet_name = target_sheet["name"]
    sheet_id_int = target_sheet["gid"]
    sheet_rows = target_sheet["rowCount"]

    # 读现有 A:C 找最后一行
    range_read = f"'{sheet_name}'!A:C"
    result = service.spreadsheets().values().get(
        spreadsheetId=spreadsheet_id, range=range_read,
    ).execute()
    existing = result.get("values", [])
    last_row = 0
    for i in range(len(existing) - 1, -1, -1):
        row = existing[i]
        if any(row[j] for j in range(min(3, len(row))) if row[j]):
            last_row = i + 1
            break

    now = datetime.datetime.now()
    time_str = f"{now.month}/{now.day}"
    new_rows = []
    for r in rows:
        try:
            amount_val = float(str(r.get("amount", "")))
        except (TypeError, ValueError):
            amount_val = str(r.get("amount", ""))
        new_rows.append([
            "'" + time_str,                       # A 时间（文本）
            "'" + str(r.get("account_id", "")),   # B 账户ID（文本）
            amount_val,                           # C 金额（数字）
        ])

    start = last_row + 1
    end = last_row + len(new_rows)
    if end > sheet_rows:
        service.spreadsheets().batchUpdate(
            spreadsheetId=spreadsheet_id,
            body={"requests": [{
                "appendDimension": {
                    "sheetId": sheet_id_int,
                    "dimension": "ROWS",
                    "length": end - sheet_rows
                }
            }]}
        ).execute()

    service.spreadsheets().values().update(
        spreadsheetId=spreadsheet_id,
        range=f"'{sheet_name}'!A{start}:C{end}",
        valueInputOption="USER_ENTERED",
        body={"values": new_rows},
    ).execute()

    log.info("TT 充值记录已追加到 Google Sheets: %d 行", len(new_rows))
    return {"appended": len(new_rows)}
```

- [ ] **Step 4: 运行测试确认通过**

Run: `cd py && python -m pytest tests/test_tt_accounts.py -k append_recharge_tt -v`
Expected: 2 passed

- [ ] **Step 5: Commit**

```bash
git add py/google_sheets_service.py py/tests/test_tt_accounts.py
git commit -m "feat: TT 充值表新增 append_recharge_tt（只写时间/账户ID/金额三列）"
```

---

### Task 2: TT 路由切换到 `append_recharge_tt`

**Files:**
- Modify: `py/routes/tt_accounts_routes.py`（`_append_recharge_background` 内 `_do_sync`）

**Interfaces:**
- Consumes: `google_sheets_service.append_recharge_tt(service, sheet_id, sheet_name, rows)`
- Produces: 无（`submit`/`batch-submit`/`retry-sheets` 三处共用，行为一致）

- [ ] **Step 1: 修改 `_do_sync`**

将 [tt_accounts_routes.py](../../../py/routes/tt_accounts_routes.py) 中 `_do_sync` 内的一行：

```python
        gs.append_recharge(service, sheet_id, sheet_name, rows)
```

改为：

```python
        gs.append_recharge_tt(service, sheet_id, sheet_name, rows)
```

- [ ] **Step 2: 运行全量 TT 测试**

Run: `cd py && python -m pytest tests/test_tt_accounts.py -v`
Expected: 全部通过（含 `test_recharge_submit_and_list` 等既有用例）

- [ ] **Step 3: Commit**

```bash
git add py/routes/tt_accounts_routes.py
git commit -m "feat: TT 充值写表改走 append_recharge_tt（不覆盖代理/运营等公式列）"
```

---

## Self-Review 备注

- Spec 覆盖：3.1（新函数）→ Task 1；3.2（路由切换）→ Task 2；3.1 已知限制（时间取写入时）为设计决策，无额外任务。
- 无 placeholder；类型/函数名前后一致（`append_recharge_tt(service, spreadsheet_id, sheet_name, rows)`）。
