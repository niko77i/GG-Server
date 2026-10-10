"""`_migrate_if_needed` 必须按**数据根**定位三类旧格式源文件。

回归背景（2026-10-11，temp/ 目录归类）
--------------------------------------
`app.db` 由 `temp/app.db` 归入 `temp/data/app.db` 后，`_migrate_if_needed` 原先用
`os.path.dirname(os.path.dirname(_db_path()))` 反推数据根，于是少了一层：

    _db_path() = <ROOT>/temp/data/app.db
    dirname×2  = <ROOT>/temp        ← 错，应为 <ROOT>

它把这个 root 传给三个迁移函数，导致：

    _migrate_video_history → <ROOT>/temp/temp/data/video_set   （双重嵌套）
    _migrate_youtube_db    → <ROOT>/temp/temp/data/youtube.db  （双重嵌套）
    _migrate_font_recent   → <ROOT>/temp/fonts/.recent.json    （错一层）

三者都以 `os.path.isdir` / `os.path.isfile` 为假而 `return`，**不抛任何异常**——
静默跳过迁移。生产库因三个标记早已置位而侥幸不受影响，但全新部署或从旧备份
恢复时会丢历史数据。修法：抽出 `database._data_root()` 供两处共用。

这两个用例钉住的正是「root 必须是数据根」这个契约 —— 值错了不会红，只会静默
少迁数据，所以必须显式断言。
"""
import json
import sqlite3

import database


def test_migration_receives_data_root(client, monkeypatch):
    """契约层：三个迁移函数收到的 root 必须等于 `_data_root()`。

    若将来有人改回由 `_db_path()` 反推目录层级，本例会红 —— 而不是再次静默跳过。
    """
    captured = []
    monkeypatch.setattr(database, "_migrate_video_history",
                        lambda conn, root: captured.append(("video_history", root)))
    monkeypatch.setattr(database, "_migrate_youtube_db",
                        lambda conn, root: captured.append(("youtube", root)))
    monkeypatch.setattr(database, "_migrate_font_recent",
                        lambda conn, root: captured.append(("font_recent", root)))

    db = database.get_db()
    # 清掉标记，逼三条迁移分支真的走到
    for key in ("migrated_video_history", "migrated_youtube", "migrated_font_recent"):
        db.execute("DELETE FROM config WHERE key=?", (key,))
    db.commit()

    database._migrate_if_needed(db)
    db.close()

    assert captured, "三条迁移一条都没被调用 —— 标记没清干净？"
    expected = database._data_root()
    for name, root in captured:
        assert root == expected, (
            f"{name} 收到的 root={root!r}，应为数据根 {expected!r}；"
            f"形如 <root>/temp 说明又在由 _db_path() 反推目录层级"
        )


def test_font_recent_source_sits_in_data_root(tmp_path):
    """端到端定位：`fonts/.recent.json` 在**数据根**下（不在 temp/data/ 下）。

    这条钉住布局假设本身。它同时说明：不隔离数据根的测试会去读**真实仓库**的
    `fonts/.recent.json`，而本函数导入后会 `os.rename` 源文件成 `.bak`
    —— 即跑测试改坏真实文件（故 conftest 有 autouse 夹具隔离 `_data_root`）。
    """
    (tmp_path / "fonts").mkdir()
    src = tmp_path / "fonts" / ".recent.json"
    src.write_text(json.dumps(["simhei"]), encoding="utf-8")

    con = sqlite3.connect(":memory:")
    con.execute("CREATE TABLE config(key TEXT PRIMARY KEY, value TEXT)")
    database._migrate_font_recent(con, str(tmp_path))

    row = con.execute("SELECT value FROM config WHERE key='font_recent'").fetchone()
    assert row is not None and json.loads(row[0]) == ["simhei"]
    assert not src.is_file(), "导入后源文件应被改名"
    assert (tmp_path / "fonts" / ".recent.json.bak").is_file()
    con.close()
