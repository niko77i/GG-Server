"""
生产数据迁移脚本：ImageCrawling → GG-Server

用法：
  cd GG-Server/py
  python migrate_from_production.py          # 预览模式（不写入，--dry-run）
  python migrate_from_production.py --run    # 执行迁移

安全设计：
  - 默认 dry-run，只打印将迁移的数据量，不写入
  - 执行前自动备份 GG-Server 的 app.db
  - 保留 GG-Server 的 users 表不动
  - 保留 GG-Server 的 config 迁移标记不动
  - 业务表先清空再插入，保持原始 ID（维护外键关系）
"""

import sqlite3
import os
import sys
import shutil
from datetime import datetime

SRC_DB = r"f:\carl_work\carl\Google\cc\ImageCrawling\temp\app.db"
DST_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DST_DB = os.path.join(DST_DIR, "temp", "app.db")

# 需要迁移的表及其主键类型
TABLES = {
    "products":      {"pk": "auto"},
    "packages":      {"pk": "auto"},
    "mcc":           {"pk": "auto"},
    "accounts":      {"pk": "auto"},
    "videos":        {"pk": "text", "pk_col": "id"},
    "video_history": {"pk": "auto"},
    "video_tasks":   {"pk": "auto"},
    "copywritings":  {"pk": "auto"},
    "tags":          {"pk": "text", "pk_col": "key"},
    "config":        {"pk": "text", "pk_col": "key"},  # 特殊：合并而非覆盖
}

# GG-Server 专属的 config key，不能被覆盖
GG_CONFIG_KEYS = {
    "migrated_video_history",
    "migrated_youtube",
    "migrated_font_recent",
    "gg_server_initialized",
}


def get_columns(conn, table):
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return [r[1] for r in rows]


def count_table(conn, table):
    return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]


def migrate(dry_run=True):
    if not os.path.isfile(SRC_DB):
        print(f"[错误] 源数据库不存在: {SRC_DB}")
        sys.exit(1)
    if not os.path.isfile(DST_DB):
        print(f"[错误] 目标数据库不存在: {DST_DB}")
        sys.exit(1)

    print(f"源库: {SRC_DB}")
    print(f"目标库: {DST_DB}")
    print(f"模式: {'预览 (--dry-run)' if dry_run else '执行 (--run)'}\n")

    src = sqlite3.connect(SRC_DB)
    src.row_factory = sqlite3.Row

    print("=" * 60)
    print("源库 (ImageCrawling) 数据量:")
    print("=" * 60)
    for table in TABLES:
        count = count_table(src, table)
        print(f"  {table:20s} {count:>6} 条")
    print()

    if dry_run:
        dst = sqlite3.connect(DST_DB)
        dst.row_factory = sqlite3.Row
        print("目标库 (GG-Server) 当前数据量:")
        print("-" * 60)
        for table in TABLES:
            count = count_table(dst, table)
            print(f"  {table:20s} {count:>6} 条")
        user_count = count_table(dst, "users")
        print(f"  {'users':20s} {user_count:>6} 条 (保留不动)")
        sc_count = count_table(dst, "scrape_cache")
        print(f"  {'scrape_cache':20s} {sc_count:>6} 条 (保留不动)")
        dst.close()
        print("\n[预览完成] 使用 --run 参数执行实际迁移")
        src.close()
        return

    # ==================== 执行模式 ====================

    # 1. 备份
    backup_path = DST_DB + f".bak.{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    print(f"[1/4] 备份目标库 → {backup_path}")
    shutil.copy2(DST_DB, backup_path)
    print("      备份完成")

    # 2. 连接目标库
    dst = sqlite3.connect(DST_DB)
    dst.row_factory = sqlite3.Row
    dst.execute("PRAGMA foreign_keys=OFF")
    dst.execute("PRAGMA journal_mode=WAL")

    # 3. 逐表迁移
    print("\n[2/4] 开始迁移数据...")
    stats = {}

    for table, info in TABLES.items():
        src_cols = get_columns(src, table)
        dst_cols = get_columns(dst, table)
        common_cols = [c for c in src_cols if c in dst_cols]
        if not common_cols:
            print(f"  {table}: 无共同列，跳过")
            continue

        col_list = ", ".join(common_cols)
        placeholders = ", ".join(["?"] * len(common_cols))

        if table == "config":
            # config: 只复制非 GG-Server 专属 key
            rows = src.execute(f"SELECT {col_list} FROM {table}").fetchall()
            imported, skipped = 0, 0
            for r in rows:
                d = dict(r)
                if d["key"] in GG_CONFIG_KEYS:
                    skipped += 1
                    continue
                vals = [d.get(c) for c in common_cols]
                dst.execute(
                    f"INSERT OR REPLACE INTO {table}({col_list}) VALUES({placeholders})",
                    vals,
                )
                imported += 1
            print(f"  {table:20s} 导入 {imported} 条, 跳过 {skipped} 条 (GG-Server 专属)")
            stats[table] = imported
        else:
            dst.execute(f"DELETE FROM {table}")
            rows = src.execute(f"SELECT {col_list} FROM {table}").fetchall()
            count = 0
            for r in rows:
                d = dict(r)
                vals = [d.get(c) for c in common_cols]
                try:
                    dst.execute(
                        f"INSERT INTO {table}({col_list}) VALUES({placeholders})", vals
                    )
                    count += 1
                except sqlite3.IntegrityError as e:
                    print(f"    跳过重复: {e}")
            print(f"  {table:20s} {count:>6} 条")
            stats[table] = count

    # 4. 更新自增序列
    print("\n[3/4] 更新自增序列...")
    for table, info in TABLES.items():
        if info["pk"] != "auto":
            continue
        max_id = dst.execute(f"SELECT MAX(id) FROM {table}").fetchone()[0]
        if max_id:
            dst.execute(
                "INSERT OR REPLACE INTO sqlite_sequence(name, seq) VALUES(?,?)",
                (table, max_id),
            )
            print(f"  {table}: seq = {max_id}")

    dst.execute("PRAGMA foreign_keys=ON")
    dst.commit()

    # 5. 验证
    print("\n[4/4] 验证迁移结果:")
    print("-" * 60)
    for table in TABLES:
        sc = count_table(src, table)
        dc = count_table(dst, table)
        status = "✅" if dc >= sc else "❌"
        print(f"  {table:20s} 源: {sc:>6} → 目标: {dc:>6}  {status}")

    user_count = count_table(dst, "users")
    print(f"  {'users':20s} {'':>8} 目标: {user_count:>6}  ✅ (未变更)")

    dst.close()
    src.close()

    print(f"\n迁移完成！备份文件: {backup_path}")
    print("恢复命令: copy /Y <备份文件> temp\\app.db")


if __name__ == "__main__":
    dry_run = "--run" not in sys.argv
    if "--help" in sys.argv or "-h" in sys.argv:
        print(__doc__)
        sys.exit(0)
    migrate(dry_run=dry_run)
