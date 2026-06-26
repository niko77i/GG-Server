"""GG-Server 数据管理 CLI 工具。

用法：
  python manage.py backup                          # 整库备份
  python manage.py list-backups                    # 列出备份
  python manage.py restore <备份路径>               # 整库恢复
  python manage.py import-db <db路径> --user <用户名>    # 从 db 导入
  python manage.py import-json <json路径> --user <用户名> # 从 JSON 导入
  python manage.py export-user <用户名> [-o output.json] # 导出用户
  python manage.py export-all [-o output_dir/]          # 导出所有用户
"""
import sys
import os
import json
import argparse

# 确保当前目录在 path 中
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import data_service
import auth
import database


def cmd_backup():
    path = data_service.backup_database()
    print(f"✅ 备份完成: {path}")


def cmd_list_backups():
    backups = data_service.list_backups()
    if not backups:
        print("(无备份文件)")
        return
    print(f"{'文件名':<40} {'大小':>8} {'时间':>20}")
    print("-" * 70)
    for b in backups:
        print(f"{b['name']:<40} {b['size_mb']:>6.1f}MB {b['mtime']:>20}")


def cmd_restore(args):
    backup_path = args.path
    if not os.path.isfile(backup_path):
        print(f"❌ 备份文件不存在: {backup_path}")
        sys.exit(1)
    current = data_service.restore_database(backup_path)
    print(f"✅ 已恢复。原库备份至: {current}")


def cmd_import(args):
    file_path = args.path
    username = args.user

    user = auth.get_user_by_username(username)
    if not user:
        print(f"❌ 用户不存在: {username}")
        sys.exit(1)

    file_type = "db" if file_path.endswith(".db") else "json"
    print(f"导入 {file_type} 文件: {file_path}")
    print(f"目标用户: {username} (id={user['id']})")

    report = data_service.execute_import(file_path, file_type, user["id"])

    r = report.get("report", {})
    print(f"✅ 导入完成:")
    print(f"  products: {r.get('products', 0)}")
    print(f"  packages: {r.get('packages', 0)}")
    print(f"  accounts: {r.get('accounts', 0)}")
    print(f"  mcc:      {r.get('mcc', 0)}")
    print(f"  videos:   {r.get('videos', 0)}")
    cw = r.get("copywritings", {})
    print(f"  copywritings: {cw.get('imported', 0)} 条导入, {cw.get('skipped', 0)} 条跳过")
    tg = r.get("tags", {})
    print(f"  tags:         {tg.get('imported', 0)} 条导入, {tg.get('skipped', 0)} 条跳过")


def cmd_export_user(args):
    username = args.user
    user = auth.get_user_by_username(username)
    if not user:
        print(f"❌ 用户不存在: {username}")
        sys.exit(1)

    data = data_service.export_user_data(user["id"])
    output = args.output or f"gg-server-export-{username}.json"

    with open(output, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    print(f"✅ 已导出到: {output}")


def cmd_export_all(args):
    output_dir = args.output or "exports"
    os.makedirs(output_dir, exist_ok=True)

    db = database.get_db()
    users = db.execute("SELECT id, username FROM users WHERE role != 'hidden'").fetchall()
    db.close()

    for u in users:
        data = data_service.export_user_data(u["id"])
        fname = f"gg-server-export-{u['username']}.json"
        fpath = os.path.join(output_dir, fname)
        with open(fpath, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        print(f"  ✅ {u['username']} → {fname}")

    print(f"\n共导出 {len(users)} 个用户到: {output_dir}")


def main():
    parser = argparse.ArgumentParser(description="GG-Server 数据管理工具")
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("backup", help="整库备份")
    sub.add_parser("list-backups", help="列出备份")

    p = sub.add_parser("restore", help="整库恢复")
    p.add_argument("path", help="备份文件路径")

    p = sub.add_parser("import-db", help="从 db 文件导入")
    p.add_argument("path", help="db 文件路径")
    p.add_argument("--user", required=True, help="目标用户名")

    p = sub.add_parser("import-json", help="从 JSON 文件导入")
    p.add_argument("path", help="JSON 文件路径")
    p.add_argument("--user", required=True, help="目标用户名")

    p = sub.add_parser("export-user", help="导出指定用户")
    p.add_argument("user", help="用户名")
    p.add_argument("-o", "--output", help="输出文件路径")

    p = sub.add_parser("export-all", help="导出所有用户")
    p.add_argument("-o", "--output", help="输出目录")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return

    commands = {
        "backup": cmd_backup,
        "list-backups": cmd_list_backups,
        "restore": lambda: cmd_restore(args),
        "import-db": lambda: cmd_import(args),
        "import-json": lambda: cmd_import(args),
        "export-user": lambda: cmd_export_user(args),
        "export-all": lambda: cmd_export_all(args),
    }

    try:
        commands[args.command]()
    except Exception as e:
        print(f"❌ 错误: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
