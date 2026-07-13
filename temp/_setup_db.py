import sqlite3

db = sqlite3.connect("d:/server/cc/GG-Server/temp/app.db")

# 创建缺失的表
db.executescript("""
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT NOT NULL UNIQUE,
        password TEXT NOT NULL,
        role TEXT NOT NULL DEFAULT 'user',
        display_name TEXT DEFAULT '',
        created_at TEXT NOT NULL DEFAULT (datetime('now')),
        last_login TEXT,
        created_by INTEGER REFERENCES users(id),
        config TEXT DEFAULT '{}'
    );

    CREATE TABLE IF NOT EXISTS scrape_cache (
        package_name TEXT PRIMARY KEY,
        image_count INTEGER DEFAULT 0,
        saved_path TEXT,
        logo_path TEXT,
        last_scraped TEXT DEFAULT (datetime('now')),
        scraped_by INTEGER REFERENCES users(id)
    );
""")
db.commit()

# 验证
for t in ["users", "accounts", "mcc", "products", "packages", "videos"]:
    cnt = db.execute(f"SELECT COUNT(*) FROM [{t}]").fetchone()[0]
    print(f"{t}: {cnt}")

db.close()
print("Done — startup will auto-create developer account")
