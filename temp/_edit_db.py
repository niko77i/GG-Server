import os
path = r'F:\carl_work\carl\Google\cc\GG-Server\py\database.py'
content = open(path, 'r', encoding='utf-8').read()

find_text = '        FOREIGN KEY(product_id) REFERENCES products(id)\n        );\n    \")'

new_tables = '''
        -- 用户表
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

        -- 爬取缓存表
        CREATE TABLE IF NOT EXISTS scrape_cache (
            package_name TEXT PRIMARY KEY,
            image_count INTEGER DEFAULT 0,
            saved_path TEXT,
            logo_path TEXT,
            last_scraped TEXT DEFAULT (datetime('now')),
            scraped_by INTEGER REFERENCES users(id)
        );

'''

idx = content.find(find_text)
if idx < 0:
    print('ERROR: Could not find insertion point')
else:
    end_pos = idx + len(find_text)
    content = content[:end_pos] + new_tables + content[end_pos:]
    open(path, 'w', encoding='utf-8').write(content)
    print('Done! File updated:', len(content), 'bytes')
