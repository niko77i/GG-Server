"""共享账号网关的持久化（站点 / 会话罐 / 访问日志）。

只做 SQL，不含业务判断。所有函数自己开连接、自己关，和仓内其它 routes 的
`db = database.get_db() ... finally db.close()` 保持一致（get_db 每次新建连接）。
"""
import database


def _rows(rows):
    return [dict(r) for r in rows]


def ensure_site(site: dict) -> None:
    """把配置里的站点写进库（名称/上游/端口以配置为准，enabled 只在首次生效）。"""
    db = database.get_db()
    try:
        db.execute(
            "INSERT INTO share_sites (id, name, upstream, port, enabled, created_at) "
            "VALUES (?, ?, ?, ?, 1, datetime('now','localtime')) "
            "ON CONFLICT(id) DO UPDATE SET name=excluded.name, "
            "upstream=excluded.upstream, port=excluded.port",
            (site["id"], site.get("name") or site["id"], site["upstream"], int(site["port"])),
        )
        db.commit()
    finally:
        db.close()


def list_sites() -> list[dict]:
    db = database.get_db()
    try:
        return _rows(db.execute(
            "SELECT id, name, upstream, port, enabled, created_at FROM share_sites ORDER BY created_at, id"
        ).fetchall())
    finally:
        db.close()


def get_site(site_id: str) -> dict | None:
    db = database.get_db()
    try:
        row = db.execute(
            "SELECT id, name, upstream, port, enabled, created_at FROM share_sites WHERE id=?",
            (site_id,),
        ).fetchone()
        return dict(row) if row else None
    finally:
        db.close()


def set_enabled(site_id: str, enabled: bool) -> bool:
    db = database.get_db()
    try:
        cur = db.execute("UPDATE share_sites SET enabled=? WHERE id=?", (1 if enabled else 0, site_id))
        db.commit()
        return cur.rowcount > 0
    finally:
        db.close()


def get_session(site_id: str) -> dict | None:
    db = database.get_db()
    try:
        row = db.execute(
            "SELECT site_id, cookies_enc, updated_at, status, last_ok_at, last_error, "
            "fail_streak, ver FROM share_sessions WHERE site_id=?",
            (site_id,),
        ).fetchone()
        return dict(row) if row else None
    finally:
        db.close()


def bump_ver(site_id: str) -> int:
    """会话代次 +1，返回新值。

    用途：停用站点 / 清空会话时让**已经发出去的** `__sgw_<site>` cookie 立即失效
    （cookie 是无状态签名，只能靠代次对不上来吊销）。
    """
    db = database.get_db()
    try:
        db.execute(
            "UPDATE share_sessions SET ver=COALESCE(ver,0)+1 WHERE site_id=?", (site_id,)
        )
        db.commit()
        row = db.execute("SELECT ver FROM share_sessions WHERE site_id=?", (site_id,)).fetchone()
        return int(row[0]) if row and row[0] is not None else 0
    finally:
        db.close()


def save_session(site_id: str, cookies_enc: str | None) -> None:
    """整体覆盖会话罐（加密串）。updated_at 一并刷新。"""
    db = database.get_db()
    try:
        db.execute(
            "INSERT INTO share_sessions (site_id, cookies_enc, updated_at, status, fail_streak) "
            "VALUES (?, ?, datetime('now','localtime'), 'unknown', 0) "
            "ON CONFLICT(site_id) DO UPDATE SET cookies_enc=excluded.cookies_enc, "
            "updated_at=excluded.updated_at",
            (site_id, cookies_enc),
        )
        db.commit()
    finally:
        db.close()


def update_status(site_id: str, status: str, error: str | None = None, ok: bool = False) -> None:
    """写探测结果。ok=True 时同时刷新 last_ok_at 并把失败计数清零。"""
    db = database.get_db()
    try:
        if ok:
            db.execute(
                "UPDATE share_sessions SET status=?, last_error=NULL, fail_streak=0, "
                "last_ok_at=datetime('now','localtime') WHERE site_id=?",
                (status, site_id),
            )
        else:
            db.execute(
                "UPDATE share_sessions SET status=?, last_error=?, "
                "fail_streak=COALESCE(fail_streak,0)+1 WHERE site_id=?",
                (status, error, site_id),
            )
        db.commit()
    finally:
        db.close()


def record_access(site_id: str, user_id, username: str, ip: str) -> None:
    db = database.get_db()
    try:
        db.execute(
            "INSERT INTO share_access_log (site_id, user_id, username, ip, created_at) "
            "VALUES (?, ?, ?, ?, datetime('now','localtime'))",
            (site_id, user_id, username, ip),
        )
        db.commit()
    finally:
        db.close()


def list_logs(site_id: str, limit: int = 200) -> list[dict]:
    limit = max(1, min(int(limit), 500))
    db = database.get_db()
    try:
        return _rows(db.execute(
            "SELECT id, site_id, user_id, username, ip, created_at FROM share_access_log "
            "WHERE site_id=? ORDER BY id DESC LIMIT ?",
            (site_id, limit),
        ).fetchall())
    finally:
        db.close()


def today_users(site_id: str) -> int:
    db = database.get_db()
    try:
        row = db.execute(
            "SELECT COUNT(DISTINCT user_id) FROM share_access_log "
            "WHERE site_id=? AND date(created_at)=date('now','localtime')",
            (site_id,),
        ).fetchone()
        return int(row[0]) if row and row[0] is not None else 0
    finally:
        db.close()


def last_access(site_id: str) -> dict | None:
    db = database.get_db()
    try:
        row = db.execute(
            "SELECT username, created_at FROM share_access_log "
            "WHERE site_id=? ORDER BY id DESC LIMIT 1",
            (site_id,),
        ).fetchone()
        return dict(row) if row else None
    finally:
        db.close()
