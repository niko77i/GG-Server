# TT 回收户清单写入 — 只写 3 列、保护公式、非存活即触发 实现计划

> 依据设计文档：`docs/superpowers/specs/2026-09-22-tt-recycle-sheet-columns-design.md`

## 任务拆解

### Task 1: `append_recycle` 只写 3 列（py/google_sheets_service.py）

- 读 `A:B` 找最后一行（不再读 A:L，C-L 公式不作为判定依据）
- `values().batchUpdate` 一次写 `A/B/H` 三个 range
- 账户ID 前置 `'` 强制文本

### Task 2: 后端触发与传参（py/routes/tt_accounts_routes.py）

- `_trigger_recycle_if_dead`：触发条件 `in ("封禁","死亡")` → `!= "存活"`；移除查 agent/country/timezone 的 SQL
- `_maybe_write_recycle`：rows 只留 `time/account_id/reason`

### Task 3: 前端触发范围（frontend/src/views/tt/TtAccountPanel.vue）

- `saveStatus`：`stName === '封禁' || stName === '死亡'` → `stName !== '存活'`
- `doBatchStatus`：同上

### Task 4: 测试（py/tests/test_tt_accounts.py）

- 补「非存活（如 验证）触发回收」断言
- 补 `append_recycle` 只写 A/B/H 三列（mock 校验 batchUpdate 的 range）
- 回归现有回收相关测试

### Task 5: 验证

- 后端 `pytest tests/test_tt_accounts.py`
- 前端 `npm run build`

## 关键代码

### append_recycle 只写 3 列

```python
# 读 A:B 找最后一行
existing = service.spreadsheets().values().get(
    spreadsheetId=spreadsheet_id, range=f"'{sheet_name}'!A:B").execute().get("values", [])
last_row = 0
for i in range(len(existing) - 1, -1, -1):
    row = existing[i]
    if (len(row) > 0 and (row[0] or "").strip()) or (len(row) > 1 and (row[1] or "").strip()):
        last_row = i + 1
        break

# 只写 A/B/H
service.spreadsheets().values().batchUpdate(
    spreadsheetId=spreadsheet_id,
    body={"valueInputOption": "USER_ENTERED", "data": [
        {"range": f"'{sheet_name}'!A{start}:A{end}",
         "values": [[r.get("time", "")] for r in rows]},
        {"range": f"'{sheet_name}'!B{start}:B{end}",
         "values": [["'" + str(r.get("account_id", ""))] for r in rows]},
        {"range": f"'{sheet_name}'!H{start}:H{end}",
         "values": [[r.get("reason", "")] for r in rows]},
    ]}).execute()
```

### 触发条件放宽

```python
# _trigger_recycle_if_dead 内
if not st or st["name"] == "存活":
    return
```
