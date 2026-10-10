"""主数据「确保存在」规则 —— 从 tt_accounts_routes 提取的共享实现。

两条链路（表 → 系统同步、看板同步）共用一份，避免「一条规则两处实现」漂移。
函数体为逐字搬运，行为与提取前完全一致（仅去掉前导下划线）。
"""
from cache import cache as _app_cache


def ensure_bc(db, name, uid):
    if not name:
        return None
    row = db.execute("SELECT id, deleted_at FROM tt_bcs WHERE name=?", (name,)).fetchone()
    if row:
        if row["deleted_at"]:
            db.execute("UPDATE tt_bcs SET deleted_at=NULL WHERE id=?", (row["id"],))
        return row["id"]
    # bc_id 唯一冲突兜底：同名软删后 name 可能仍在，但 bc_id 一定还占用
    row = db.execute("SELECT id, deleted_at FROM tt_bcs WHERE bc_id=?", (name,)).fetchone()
    if row:
        if row["deleted_at"]:
            db.execute("UPDATE tt_bcs SET deleted_at=NULL WHERE id=?", (row["id"],))
        return row["id"]
    db.execute("INSERT INTO tt_bcs(name, bc_id, owner_id) VALUES(?,?,?)",
               (name, name, uid))
    return db.execute("SELECT last_insert_rowid()").fetchone()[0]


def ensure_agent(db, name, uid):
    if not name:
        return None
    row = db.execute("SELECT id FROM agents WHERE name=? AND platform='tt'", (name,)).fetchone()
    if row:
        return row["id"]
    db.execute("INSERT INTO agents(name, owner_id, platform) VALUES(?,?, 'tt')", (name, uid))
    # 清除缓存：任何写入 agents 表都须让代理名下拉立即刷新
    _app_cache.clear_prefix("accounts:agents:")
    return db.execute("SELECT last_insert_rowid()").fetchone()[0]


def strip_utc_prefix(value):
    """去掉 UTC 前缀（仅当以 UTC 开头），如 UTC+8 → +8；非 UTC 值原样返回。"""
    value = value or ""
    return value[3:] if value.startswith("UTC") else value
