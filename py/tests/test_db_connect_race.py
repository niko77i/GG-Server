"""并发首次连库竞态回归测试。

缺陷：get_db() 里 _ensure_columns(conn) 曾在 _schema_lock **之外**执行。它是
一长串「PRAGMA 查列 → 条件 ALTER TABLE ADD COLUMN」两步操作，两条连接并发首次
连库时会双双看到列不存在、双双 ALTER，后到的撞
`sqlite3.OperationalError: duplicate column name: ...`。

放在独立文件而非 test_sheet_write.py：这是**数据库连接层**的并发缺陷，与写表业务
无关（只是写表功能恰好以「后台线程开连接 + 主线程也开连接」的形态撞上了它），
单列一个文件让缺陷的主语一目了然，也不给 sheet_write 的用例增负担。
"""
import os
import sys
import tempfile
import threading

_py_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _py_dir not in sys.path:
    sys.path.insert(0, _py_dir)

import database  # noqa: E402


def test_concurrent_get_db_on_fresh_db_raises_nothing():
    """全新库上 4 线程并发 get_db()，零异常。

    判据（会判错的那个）：_ensure_columns 若在锁外，本例必现
    OperationalError: duplicate column name。修复前实测 4 线程报 3 个错。
    """
    db_fd, db_path = tempfile.mkstemp(suffix=".db")
    original_path = database._db_path
    # 保存原标记，收尾时**还原**而非硬重置 —— 硬重置会逼下一个测试重走 ~105ms 冷路径。
    original_verified = database._schema_verified
    original_verified_path = database._schema_verified_path
    database._db_path = lambda: db_path
    # 重置 schema 缓存 —— 必须让每个线程都真正走到「补列」这一段
    database._schema_verified = False
    database._schema_verified_path = None

    errors = []
    ok = []
    barrier = threading.Barrier(4)

    def worker():
        try:
            barrier.wait(timeout=10)  # 尽量让 4 条连接同时起跑
            conn = database.get_db()
            conn.close()
            ok.append(1)
        except Exception as exc:  # noqa: BLE001 — 收全，交给断言判定
            errors.append(f"{type(exc).__name__}: {exc}")

    try:
        threads = [threading.Thread(target=worker) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30)

        assert errors == [], f"并发 get_db() 报错 {len(errors)} 个：{errors}"
        # 卡住的 worker 既不抛异常、也不写 errors —— 只断言 errors==[] 会空转过测试。
        assert len(ok) == 4, f"只有 {len(ok)}/4 个 worker 走完 get_db()（有线程卡住/未起跑）"
    finally:
        os.close(db_fd)
        try:
            os.unlink(db_path)
        except OSError:
            pass
        for suffix in ("-wal", "-shm"):
            try:
                os.unlink(db_path + suffix)
            except OSError:
                pass
        database._db_path = original_path
        database._schema_verified = original_verified
        database._schema_verified_path = original_verified_path
