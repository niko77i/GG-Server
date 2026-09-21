# TT 同步「是否回收」驱动状态变更 实现计划

> 依据设计文档：`docs/superpowers/specs/2026-09-22-tt-sync-recycle-status-design.md`

## 任务拆解

### Task 1: 后端 dry_run 阶段状态比对（tt_accounts_routes.py）

在 `sync_from_sheet` 遍历循环里：
- 读 C 列推导 `sheet_status`（"是"→死亡，否则→存活）
- 新户 `created` 条目加 `status` 字段
- 已存在且状态不一致 → 追加 `status_conflicts`
- dry_run 返回加 `status_conflicts`

### Task 2: 后端 confirm 阶段执行（tt_accounts_routes.py）

- 创建新户 INSERT 加 `status_id`
- 处理 `status_resolutions`（更新 status_id + status_changed_date，不触发回收清单）

### Task 3: 前端同步弹窗（TtAccountSyncModal.vue）

- 新增账户表加「状态」列
- 新增「状态冲突」区块 + radio 选择
- doSync 组装 `status_resolutions`
- `canSync` 纳入状态冲突

### Task 4: 测试（test_tt_accounts.py）

- 补状态冲突 dry_run / confirm 测试
- 回归：新增带状态的测试

### Task 5: 验证

- 后端 `pytest tests/test_tt_accounts.py tests/test_tt_routes.py`
- 前端 `npm run build`

## 关键代码

### 状态映射

```python
recycle = (r[2] or "").strip() if len(r) > 2 else ""
sheet_status = "死亡" if recycle == "是" else "存活"
```

### confirm 状态更新（不写回收清单）

```python
status_resolutions = data.get("status_resolutions") or {}
for adv_id, new_status in status_resolutions.items():
    if adv_id not in valid_ids or new_status not in ("存活", "死亡"):
        continue
    status_id = _resolve_status_id(db, new_status, None)
    if role in ('developer', 'admin'):
        db.execute("UPDATE tt_accounts SET status_id=?, status_changed_date=datetime('now','localtime') WHERE advertiser_id=?", (status_id, adv_id))
    else:
        db.execute("UPDATE tt_accounts SET status_id=?, status_changed_date=datetime('now','localtime') WHERE advertiser_id=? AND owner_id=?", (status_id, adv_id, uid))
```
