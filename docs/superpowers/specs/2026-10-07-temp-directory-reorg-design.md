# temp/ 目录归类整理 — 设计文档

- 日期：2026-10-07
- 状态：**已确认**（2026-10-07 用户确认，决策见 §4.2）
- 类型：新需求（目标结构此前不存在，需先定）
- 实现计划：`docs/superpowers/plans/2026-10-07-temp-directory-reorg.md`

---

## 一、需求描述

temp/ 根下同时堆着一次性草稿、运行时活数据、历史备份三类东西，共 100+ 个条目，难以分辨哪些能动、哪些动了会出事。

目标：**测试/草稿归一个文件夹，数据归一个文件夹**，不再散落在 temp/ 根下。运行时目录一并迁移（用户已选定此范围）。

非目标：
- 不改动任何现有数据的内容，只搬位置。
- 不做与本次归类无关的清理（例如死配置 `scrape_cache_dir`，见 §6）。

---

## 二、现状盘点

### 2.1 三类内容

**A. 运行时活路径（代码硬编码）** — 迁移需同步改代码

| 路径 | 引用点 |
|---|---|
| `app.db` | `py/database.py:29` |
| `scraped_images/` | `py/auth.py:44`、`py/main.py:71` |
| `music/` | `py/main.py:72`（`/api/audio`、`/api/video/music-list` 在服务） |
| `audio_replace/` | `py/main.py:1364`、`py/main.py:8760` |
| `video_set/` | `py/main.py:1552`、`py/database.py:1846` |
| `video_set.bak/` | `py/database.py:1875` |
| `ai_videos/` | `py/main.py:1080`（按需创建） |
| `youtube.db` | `py/database.py:1882` |
| `youtube_videos.json.backup` | `py/database.py:1885` |
| `logs/` | `py/logging_setup.py:46` |
| `backups/` | `py/data_service.py:455`（**推导式**，见 2.2） |

**B. 一次性草稿（`_*` 前缀）** — 零代码依赖，可自由整理

- 82 个 `.py`（探针 / 变异 / 补丁施加脚本）
- 12 `.txt`、5 `.md`、4 `.patch`、4 `.mjs`、4 `.js`、4 `.diff`、1 `.json`
- 2 个探针用 `.db` 副本（`_fk_probe_copy.db`、`_probe_schema_copy.db`）
- `_travprobe/`（注意：**非**代码常量 —— 测试用的是 `mkdtemp(prefix="_travprobe_")`，见 `py/tests/test_upload_filename_traversal.py:136`；此目录只出现在注释与文档叙述里）
- `__pycache__/`

**C. 备份 / 导出产物** — 无代码依赖，仅约定位置

- `app.db.bak-before-*`（3 组，各含 `-shm`/`-wal`）
- `tt-accounts-clear-20261006-195957/`、`tt-statuses-trim-20261006-200410/`（CSV 导出）
- `deleted-69-accounts-20260924-152525.csv`
- `mut-backup/`（`tt_accounts_routes.py.orig`）
- `dist-backup-before-rebuild-20260924-162447/`（前端旧构建）

### 2.2 一条推导规则（重要）

`py/data_service.py:455`：

```python
backup_dir = os.path.join(os.path.dirname(db_path), "backups")
```

备份目录**由 DB 所在目录推导**，不是硬编码。因此 app.db 一迁移，新备份自动落到新位置——**备份天然跟着 DB 走**，无需单独改这行。现有 3 组 `.bak-before-*` 应随之迁入新 DB 目录下的 `backups/`，以保持"同一个地方放备份"的一致性。

### 2.3 完整改动面

**生产代码（15 处 / 6 文件）**

```
py/auth.py:44                      temp/scraped_images
py/database.py:29                  temp/app.db
py/database.py:1846                temp/video_set
py/database.py:1875                temp/video_set.bak
py/database.py:1882                temp/youtube.db
py/database.py:1885                temp/youtube_videos.json.backup
py/logging_setup.py:46             temp/logs
py/main.py:71                      temp/scraped_images
py/main.py:72                      temp/music
py/main.py:941                     temp            ← 静态白名单整棵树（安全相关）
py/main.py:1080                    temp/ai_videos
py/main.py:1364                    temp/audio_replace
py/main.py:1552                    temp/video_set
py/main.py:8760                    temp/audio_replace
py/migrate_from_production.py:25   temp/app.db
```

**测试（4 处 / 3 文件）**

```
py/tests/test_huguan_role.py:2439              temp/audio_replace
py/tests/test_security_hardening.py:163        temp/scraped_images
py/tests/test_security_hardening.py:211        temp/scraped_images_evil  ← 前缀绕过用例
py/tests/test_upload_filename_traversal.py:125 temp/audio_replace
```

**`.gitignore`（16 条规则）**

```
16-17  注释（说明刻意不整目录忽略 temp/，因 temp/music/ 是正式内容）→ 需改写
18  temp/scraped_images/      → temp/data/scraped_images/
19  temp/backups/             → temp/data/backups/
20  temp/video_set/           → temp/data/video_set/
22  temp/*.bak*               → temp/data/*.bak*
23  temp/server.*             → temp/data/server.*
24  temp/*.db-shm             → temp/data/*.db-shm
25  temp/*.db-wal             → temp/data/*.db-wal
26  temp/*.db                 → temp/data/*.db
27  temp/app.db               → temp/data/app.db
28  temp/audio_replace        → temp/data/audio_replace
29  temp/logs/                → temp/data/logs/
31  temp/_*                   → temp/scratch/          ← 规则本身简化为整目录
32  temp/mut-backup/          → temp/data/backups/mut-backup/
33  temp/dist-backup-*/       → temp/data/backups/dist-backup-*/
34  temp/deleted-*.csv        → temp/data/backups/deleted-*.csv
```

**草稿脚本（13 个文件，会随迁移"失效"）**

这些脚本内部硬编码了 `temp/app.db`、`temp/scraped_images` 等路径：

```
_dn_probe.py            _fix_m1_l7.py          _patch_auth.py
_patch_dne.py           _patch_r3_auth.py      _patch_r3_auth2.py
_patch_r3_warm.py       _patch_r9.py           _patch_wire.py
_probe_mcc_history_on_sync.py  _probe_migration_race.py
_probe_r5_verify.py     _probe_tt_reassign_owner.py
```

⚠️ 其中 `_probe_r5_verify.py` 是**被活代码点名引用的证据脚本**（`py/auth.py:447`、`py/tests/test_scrape_ownership.py:1291,1558`），已定**留在原路径不动**（§4.2 决策 C）。**文件不动，但它内部的路径字符串会失效**——须明确接受这一点。

---

## 三、目标结构

```
temp/
├── scratch/                      ← B 类：一次性草稿（原 temp/_*）
│   ├── _probe_r5_verify.py 等 82 个 .py
│   ├── _*.txt / _*.md / _*.diff / _*.patch / _*.js / _*.mjs
│   ├── _fk_probe_copy.db / _probe_schema_copy.db
│   ├── _travprobe/
│   └── __pycache__/
│
└── data/                         ← A 类 + C 类：运行时数据与备份
    ├── app.db
    ├── app.db-shm / app.db-wal
    ├── scraped_images/
    ├── music/
    ├── audio_replace/
    ├── video_set/
    ├── video_set.bak/
    ├── ai_videos/                （按需创建）
    ├── youtube.db
    ├── youtube_videos.json.backup
    ├── logs/
    └── backups/                  ← C 类全部收这里
        ├── app.db.bak-before-*
        ├── tt-accounts-clear-20261006-195957/
        ├── tt-statuses-trim-20261006-200410/
        ├── deleted-69-accounts-20260924-152525.csv
        ├── mut-backup/
        └── dist-backup-before-rebuild-20260924-162447/
```

整理后 temp/ 根下只剩 **2 个目录**。

### 命名说明

- `scratch/` 而非 `tests/`：这 82 个 `.py` 是探针 / 变异测试 / 补丁施加脚本，**不是测试套件**；真正的测试在 `py/tests/`。叫 `tests/` 会与既有惯例冲突并造成误导。仓库里已有大量文档用"探针""草稿"称呼它们。
- 文件名保留 `_` 前缀不变：只搬位置、不改名，把改动面压到最小。`.gitignore` 规则可由 `temp/_*` 简化为 `temp/scratch/`（整目录忽略）。

---

## 四、技术方案

### 4.1 代码改动

**方案 A（最小改动）**：逐处把字面量 `"temp", "X"` 改成 `"temp", "data", "X"`。

**方案 B（收敛常量）— ✅ 已选定**：定义一处 `DATA_DIR`，其余 15 处改为引用它，此后路径只在一处维护。

> ⚠️ 按仓库规则「纯增量原则 / 重构须先说明理由并确认」：方案 B 是重构，改动面比 A 大但根治了"15 处散落字面量"这个乱源。**用户已于 2026-10-07 确认采用方案 B。**

### 4.2 开放决策（已全部裁定）

| # | 决策 | 裁定 |
|---|---|---|
| A | 草稿目录命名 | **`scratch/`**（`tests/` 会与 `py/tests/` 冲突并误导） |
| B | `logs/` 位置 | 归 **`temp/data/logs/`**，保持"根下只有 2 个目录" |
| C | 13 个脚本内部路径失效 | **接受失效**。它们是历史证据，记录的是已发生的实测结果，无重跑计划；改脚本内容反而会篡改证据。 |
| D | `_ALLOWED_STATIC_DIRS`（`main.py:941`）取值 | **收紧为 `temp/data`**。原值放行整棵 temp 树（含草稿）；收紧是安全性改善，但会改变 `/api/` 静态服务行为，须实测确认无依赖。 |
| E | 迁移时机 | **等在途会话提交后再开工**（见 §5.3） |

### 4.3 安全面（须一并复核）

1. `_ALLOWED_STATIC_DIRS`（`main.py:941`）—— 整棵 temp 树在静态白名单内。迁移后取值见决策 D。
2. `_is_safe_music_path()`（`main.py:946`）—— 依赖 `_MUSIC_DIR`，其 docstring 明确说明**刻意不复用** `_is_safe_path`，因为后者白名单覆盖整个 temp 树、会放行 `audio_replace` 产物。**迁移后必须复核这两个函数的包含关系未被破坏**（music 仍应是白名单的子集关系可推导）。
3. `py/tests/test_security_hardening.py:211` —— 前缀绕过用例（`temp/scraped_images` 与 `temp/scraped_images_evil` 为兄弟目录）。迁到 `temp/data/` 下仍是兄弟，**语义不变，仅需改路径**；但必须重跑确认。
4. `py/main.py:1364` 用的是 `os.path.dirname(__file__), "..", "temp", ...` 相对写法，与其余 `_DATA_ROOT` 写法不一致，迁移时注意别漏。

### 4.4 数据迁移步骤

服务为 WAL 模式且**当前正在运行**（实测有 2 个 `python.exe`），直接拷文件会丢 `-wal` 未 checkpoint 的内容。

```
1. 停服务                                  ← 需你同意（既定规则：重启 5001 前先问）
2. 建 temp/scratch/ 与 temp/data/、temp/data/backups/
3. 搬 B 类：temp/_* → temp/scratch/（含 _travprobe/、__pycache__/）
   注意：9 个证据脚本留 temp/ 根原位（决策 C）—— 它们**与**其余 _* 同前缀，
   搬运时必须逐个排除，不能用通配符一把梭
4. 搬 A 类：app.db（含 -shm/-wal）、scraped_images/、music/、audio_replace/、
   video_set/、video_set.bak/、ai_videos/、youtube.db、youtube_videos.json.backup、logs/
   → temp/data/
5. 搬 C 类 → temp/data/backups/
6. 改代码（15 处，方案 A 或 B）+ 4 处测试 + .gitignore
7. 启动服务，跑全量 pytest，实测验收入口
```

> ⚠️ 步骤 3 是本次唯一容易出错的地方：`_*` 通配符会把必须留在原位的 9 个证据脚本一并卷走。必须显式排除，搬完逐个核对。

### 4.5 验收方式

- `python -m pytest -q` 全绿（重点是 `test_security_hardening`、`test_upload_filename_traversal`、`test_huguan_role`）。
- 走真实入口实测（依「未跑过的测试不算绿」）：
  - `/api/video/music-list` 能列出 music 库
  - `/api/audio` 取到 music 内文件、且**仍拒绝** `audio_replace` 产物
  - 爬取产物落到新 `scraped_images` 路径
  - 建库 / 备份：`backup_database()` 落到 `temp/data/backups/`
  - `temp/logs/gg-server.log`（新路径）有日志写入
- 对照迁移前后 `app.db` 的 `PRAGMA integrity_check` 与关键表行数。

---

## 五、风险

### 5.1 高风险点

| 风险 | 说明 |
|---|---|
| 活库迁移 | `app.db` 为 WAL 模式且服务在跑，必须停机迁移，否则丢 `-wal` 数据 |
| 安全白名单语义变化 | 决策 D 会改变 `/api/` 静态服务的放行范围，需实测确认无回归 |
| 证据脚本路径失效 | 13 个脚本内部路径失效（决策 C 建议接受） |
| 数据位置漂移 | 迁移后旧文档 / 报告里大量 `temp/xxx` 路径叙述全部过时，短时间内会误导排查 |

### 5.2 兼容性

无外部依赖指向这些路径（已核实 `frontend/`、`config/`、`etc/` 均无引用；`config/config.json` 的 `scrape_cache_dir` 是死配置，无消费方）。

### 5.3 在途会话冲突（建议先处理）

`git status` 显示以下文件**正被其他会话修改**（未提交）：

```
M py/main.py                        ← 本次要改
M py/google_sheets_service.py
M py/huguan_dashboard.py
M py/routes/huguan_dashboard_routes.py
M py/tests/conftest.py              ← 本次可能涉及
M py/tests/test_huguan_undo.py
?? py/logging_setup.py              ← 本次要改
?? py/tests/test_sheet_concurrent_probe.py
```

`py/main.py` 与 `py/logging_setup.py` 都在本次改动清单内。**建议等在途会话提交后再动手**，否则改同一文件的未提交改动易冲突（参见既定教训：并行会话共享工作区）。

---

## 六、本次不做（但记录在案）

- `config/config.json:14` 的 `"scrape_cache_dir": "temp/scrape_cache"` 是**死配置**：无任何代码读取（`scrape_cache` 的代码命中全是同名数据库表），且该目录不存在。可另行清理。
- `py/migrate_from_production.py:23` 的 `SRC_DB` 指向 `f:\carl_work\...`，与本机无关，不在范围内。

---

## 七、实施顺序（确认后）

1. 确认 §4.2 的决策 A–E、选定 §4.1 的方案 A 或 B
2. 等在途会话提交（§5.3）
3. 改代码 + 测试 + `.gitignore`
4. 停服务 → 迁移数据 → 启动服务（每步均先征得同意）
5. 全量测试 + 真实入口实测
6. `/code-review`（本次触及鉴权/静态白名单/数据归属，按规则必须过审）
