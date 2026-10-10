# temp/ 目录归类整理 — 实现计划

- 日期：2026-10-07
- 设计文档：`docs/superpowers/specs/2026-10-07-temp-directory-reorg-design.md`（已确认）
- 目标结构：`temp/scratch/`（草稿）+ `temp/data/`（运行时数据与备份）

---

## 前置条件（不满足则不开工）

- [ ] **P1**：在途会话已提交 `py/main.py`、`py/logging_setup.py`、`py/tests/conftest.py` 等相关改动，`git status` 干净（用户已选"等会话提交后再动"）。
- [ ] **P2**：用户明确许可停服务与改 `.gitignore`。
- [ ] **P3**：确认当前无别的会话正在跑 `pytest`（迁移期间路径会短暂不一致）。

---

## 阶段 1：新增 `py/paths.py`（无依赖的布局常量）

**为什么只收敛布局、不收敛根解析**：`main.py` / `database.py` / `logging_setup.py` 各自按 frozen 模式解析根，`auth.py` 刻意独立推导（其注释 `auth.py:39-40` 说明为与 `database.py` 同惯例、由测试钉住，避免导入期循环依赖）。若一并统一根解析，会**顺手改变 `auth.py` 的 frozen 行为**——而 `auth.py` 目前**没有 frozen 分支**，属另一个既有隐患（见文末「本次不做」）。重构不得夹带行为变更。

新建 `py/paths.py`，只依赖 `os`：

```python
"""temp/ 下的目录布局 —— 只固定「在 data_root 之下怎么摆」。

刻意不解析根目录：main / database / logging_setup 各自按打包/开发模式
解析，auth.py 刻意独立推导（见 auth.py:39-40 的注释）。本模块被它们
共同 import，因此**不得**依赖 main、database、auth 中任何一个，
否则引入导入期循环。
"""
import os

TEMP_DIRNAME = "temp"
DATA_DIRNAME = "data"


def temp_dir(data_root: str) -> str:
    return os.path.join(data_root, TEMP_DIRNAME)


def data_dir(data_root: str) -> str:
    return os.path.join(temp_dir(data_root), DATA_DIRNAME)
```

**验收**：`python -c "from paths import data_dir; print(data_dir(r'X'))"` → `X\temp\data`；且 `python -c "import paths"` 不触发任何其他模块导入。

---

## 阶段 2：改造 15 处引用

统一改为 `paths.data_dir(<该站点自己的 root>)`，**各站点 root 推导原样保留**。

| # | 位置 | 改法 |
|---|---|---|
| 1 | `py/main.py:71` | `os.path.join(paths.data_dir(_DATA_ROOT), "scraped_images")` |
| 2 | `py/main.py:72` | `os.path.join(paths.data_dir(_DATA_ROOT), "music")` |
| 3 | `py/main.py:941` | `os.path.normpath(paths.data_dir(_DATA_ROOT))` ← **白名单收紧（决策 D）** |
| 4 | `py/main.py:1080` | `os.path.join(paths.data_dir(_DATA_ROOT), "ai_videos")` |
| 5 | `py/main.py:1364` | `os.path.join(paths.data_dir(_DATA_ROOT), "audio_replace")` ← 原为 `dirname(__file__),".."` 相对写法，顺带与其余写法对齐（行为等价，见风险 R4） |
| 6 | `py/main.py:1552` | `os.path.join(paths.data_dir(_DATA_ROOT), "video_set")` |
| 7 | `py/main.py:8760` | `os.path.join(paths.data_dir(_DATA_ROOT), "audio_replace")` |
| 8 | `py/database.py:29` | `os.path.join(paths.data_dir(root), "app.db")` |
| 9 | `py/database.py:1846` | `os.path.join(paths.data_dir(root), "video_set")` |
| 10 | `py/database.py:1875` | `os.path.join(paths.data_dir(root), "video_set.bak")` |
| 11 | `py/database.py:1882` | `os.path.join(paths.data_dir(root), "youtube.db")` |
| 12 | `py/database.py:1885` | `os.path.join(paths.data_dir(root), "youtube_videos.json.backup")` |
| 13 | `py/auth.py:44` | `os.path.join(paths.data_dir(os.path.dirname(current)), "scraped_images")` ← **只换布局层，根解析不动** |
| 14 | `py/logging_setup.py:46` | `os.path.join(paths.data_dir(_data_root()), "logs")` |
| 15 | `py/migrate_from_production.py:25` | 先确认 `DST_DIR` 语义，同法处理 |

**不动**：`py/data_service.py:455` —— 它用 `dirname(db_path) + "/backups"` 推导，自动跟随 DB 新位置（设计文档 §2.2）。

**验收**：`grep -rn '"temp"' --include=*.py py/ | grep -v tests` 只剩 `paths.py` 内的定义；四个站点各自 `print(<路径常量>)` 均指向 `<repo根>/temp/data/...`。

---

## 阶段 3：测试改动（4 处 / 3 文件）

| 位置 | 改法 |
|---|---|
| `py/tests/test_security_hardening.py:163` | `temp/data/scraped_images` |
| `py/tests/test_security_hardening.py:211` | `temp/data/scraped_images_evil`（**前缀绕过用例，语义不变**：两者迁后仍是兄弟目录） |
| `py/tests/test_upload_filename_traversal.py:125` | `temp/data/audio_replace` |
| `py/tests/test_huguan_role.py:2439` | `temp/data/audio_replace` |

测试里其余 `_SCRAPE_DEFAULT_DIR` 的引用是 import 常量（`conftest.py:25`），**自动跟随，不用改**。

**验收**：`python -m pytest py/tests/test_security_hardening.py py/tests/test_upload_filename_traversal.py py/tests/test_huguan_role.py -q` 全绿（**此时数据尚未搬迁，需先完成阶段 5 再跑** —— 顺序见下）。

---

## 阶段 4：`.gitignore`

按设计文档 §2.3 的 16 条规则改写为 `temp/data/...` 前缀。

⚠️ **必须同时保留 `temp/_*` 规则**：9 个证据脚本按决策留在 `temp/` 根（不搬进 `scratch/`），若把 `temp/_*` 换成 `temp/scratch/`，这 9 个会变成**未忽略**，重现 2026-09-25「`git add -A` 误扫 168 个文件」的事故条件。

```gitignore
temp/scratch/          # 新增：整目录忽略草稿
temp/_*                # 保留：兜住留在根上的 9 个证据脚本
temp/data/scraped_images/
temp/data/backups/
...（其余 12 条按 §2.3 改写）
```

**验收**：`git status --porcelain` 中 temp 下**零输出**；且对 9 个证据脚本逐个 `git check-ignore -v` 均命中。

---

## 阶段 5：数据迁移（需停机）

> ⚠️ `app.db` 为 WAL 模式且服务在跑，直接拷文件会丢 `-wal` 未 checkpoint 的内容。
> ⚠️ **每步先征得同意**（既定规则：启动/停止 5001 前先问）。

```
1. 停服务
2. 建 temp/scratch/、temp/data/、temp/data/backups/
3. 搬 B 类 → temp/scratch/
   ⚠️ 不能用 mv temp/_* —— 会把 9 个证据脚本一起卷走。
      用显式排除：
        cd temp && for f in _*; do case "$f" in
          _probe_r5_verify.py|_probe_username_namespace.py|_probe_migration_race.py|\
          _mut_r8.py|_probe_m31.py|_dn_probe.py|_task3b_probe.py|\
          _old_delist_checker.py|_probe_finalfix_rows.py) continue;; esac
          mv "$f" scratch/; done
      搬完逐个核对 9 个仍在 temp/ 根。
4. 搬 A 类 → temp/data/
   app.db（含 -shm/-wal 一起）、scraped_images/、music/、audio_replace/、
   video_set/、video_set.bak/、ai_videos/、youtube.db、
   youtube_videos.json.backup、logs/
   ⚠️ app.db 必须与 -shm/-wal 一起搬，不能只搬主库文件。
5. 搬 C 类 → temp/data/backups/
   app.db.bak-before-*（3 组含 -shm/-wal）、tt-accounts-clear-*/、
   tt-statuses-trim-*/、deleted-69-accounts-*.csv、mut-backup/、
   dist-backup-before-rebuild-*/
6. 校验：PRAGMA integrity_check；关键表行数（迁移前先记录）
7. 启动服务
```

**验收**：迁移前后 `app.db` 的 `PRAGMA integrity_check` 均为 `ok`，关键表行数一致；`temp/` 根下只剩 `scratch/`、`data/` 和 9 个证据脚本。

---

## 阶段 6：验收（真实入口实测，依「未跑过的测试不算绿」）

- [ ] `python -m pytest -q` 全量绿
- [ ] `/api/video/music-list` 能列出 music 库
- [ ] `/api/audio` 取到 music 内文件，且**仍拒绝** `audio_replace` 产物（决策 D 的核心）
- [ ] 爬取产物落到 `temp/data/scraped_images/`
- [ ] `backup_database()` 落到 `temp/data/backups/`
- [ ] `temp/data/logs/gg-server.log` 有日志写入
- [ ] 静态路由实测：`temp/data/` 内文件可服务，`temp/scratch/` 内文件**不可**（白名单收紧的预期效果）

---

## 阶段 7：`/code-review`

本次触及**鉴权 / 静态白名单 / 数据归属**，按仓库规则必须过审。重点复核：

1. `_ALLOWED_STATIC_DIRS` 收紧后与 `_is_safe_music_path` 的包含关系未被破坏（`main.py:941` vs `:946`）。
2. 前缀绕过用例（`test_security_hardening.py:211`）在新布局下语义仍成立。
3. `paths.py` 未引入导入期循环依赖。

---

## 风险

| # | 风险 | 应对 |
|---|---|---|
| R1 | 步骤 3 通配符卷走 9 个证据脚本 | 显式排除 + 搬完逐个核对（**本计划最易出错处**） |
| R2 | `.gitignore` 漏掉 `temp/_*` → 9 个脚本变未忽略 → 重现 9/25 误扫事故 | 阶段 4 验收含 `git check-ignore` 逐项检查 |
| R3 | app.db 只搬主库、漏搬 `-shm`/`-wal` → 丢数据 | 阶段 5 显式要求三者同搬 + integrity_check |
| R4 | `main.py:1364` 由相对写法改为 `_DATA_ROOT` 写法 | 两者在开发/打包模式下**均**应等价（`_DATA_ROOT` 即 `dirname(dirname(__file__))`）；仍须在阶段 6 实测上传/替换音频一次 |
| R5 | 旧文档/报告中大量 `temp/xxx` 路径叙述过时 | 已知代价，接受；在交接说明中标注 |
| R6 | 在途会话冲突 | 前置条件 P1 把关 |
| R7 | 13 个脚本内部路径失效（含留原位的 `_probe_r5_verify.py`） | 决策 C：接受，不改脚本内容（改了等于篡改证据） |

**回滚**：阶段 2/3/4 为纯代码改动，`git revert` 即可；阶段 5 的迁移是 `mv`，反向 `mv` 可复原（迁移前记录完整文件清单与各文件大小，作为回滚基准）。

---

## 本次不做（记录在案）

- **`auth.py` 缺 frozen 分支（既有隐患）**：`_scrape_root()`（`auth.py:41-44`）一律用 `dirname(dirname(abspath(__file__)))`，无 frozen 处理；而 `main.py:61`、`database.py:24-28`、`logging_setup.py:39-40` 均有。打包运行后 `__file__` 指向 PyInstaller 解压目录，`auth.py` 会推出**错误的爬取根**，与 `main._SCRAPE_DEFAULT_DIR` 不一致 —— 而 `auth.py:39-40` 的注释正是说"两边一致由 test_scrape_ownership.py 的一条断言钉住"，即该断言在打包模式下可能失效。**本次不动**（属独立 bug 修复，需单独裁定与验证）。建议另行立项。
- `config/config.json:14` 的 `scrape_cache_dir` 是死配置（无消费方，目录不存在）。
- `py/migrate_from_production.py:23` 的 `SRC_DB` 指向 `f:\carl_work\...`，与本机无关。

---

## 阶段 7 审查结果与修复（2026-10-11）

审查由专职代码审查代理执行（`/code-review` 技能被设为仅限用户手动调用，无法由工具触发）。

### 🔴 阻塞项（已修）：`_migrate_if_needed` 反推数据根少一层

`py/database.py` 的 `_migrate_if_needed` 原先用 `os.path.dirname(os.path.dirname(_db_path()))`
反推数据根。`app.db` 由 `temp/app.db` 归入 `temp/data/app.db` 后，该推导得到
`<ROOT>/temp` 而非 `<ROOT>`，于是三个旧格式迁移全部指向错误位置：

| 迁移 | 错误位置 |
|---|---|
| `_migrate_video_history` | `<ROOT>/temp/temp/data/video_set`（双重嵌套） |
| `_migrate_youtube_db` | `<ROOT>/temp/temp/data/youtube.db`（双重嵌套） |
| `_migrate_font_recent` | `<ROOT>/temp/fonts/.recent.json`（错一层） |

三者均以 `isdir`/`isfile` 为假而 `return`，**不抛异常** ⇒ 静默跳过。

**影响评估**：生产库三个标记（`migrated_video_history` / `migrated_youtube` /
`migrated_font_recent`）都已置位，**当前生产不受影响**；但全新部署或从旧备份恢复会丢数据。

**修法**：抽出 `database._data_root()`，供 `_db_path()` 与 `_migrate_if_needed()` 共用，
消除「反推目录层级」这个脆弱点本身。

### 🔴 连带发现（已修）：测试隔离被打破，且有破坏性

改用 `_data_root()` 后，测试夹具只 monkeypatch 了 `_db_path`，数据根仍指向**真实仓库** ⇒
测试会去读真实的 `fonts/.recent.json`，而 `_migrate_font_recent` 导入后会
`os.rename` 源文件成 `.bak` —— **跑一次测试就改坏一个真实文件**。

> 此前 root 由被 patch 的 `_db_path` 反推，恰好顺带隔离了迁移，属偶然而非设计。

**修法**：`conftest.py` 增加 autouse 夹具 `_isolate_data_root`，统一把 `database._data_root`
指向临时目录（一处覆盖所有测试，含 test_fb_platform / test_db_connect_race 自建的夹具）。
已实测：假根上的假文件被迁移改名，真实文件哈希不变。

### 🟡 其余修复

- `py/migrate_from_production.py`：结尾的「恢复命令」提示原写死 `temp\app.db`，改为由
  `DST_DB` 推导（`os.path.relpath`），避免以后再次与库的真实位置脱节。
- 注释/docstring 里的旧路径残留共 10 处（`py/auth.py` ×3、`py/main.py` ×3、
  `py/database.py` ×1、`py/tests/` ×3）改为 `temp/data/...`。

### 新增回归测试

`py/tests/test_migration_data_root.py`：

1. `test_migration_receives_data_root` —— 契约层，钉住「三个迁移收到的 root 必须等于
   `_data_root()`」。若将来又改成按目录层级反推，本例会红而不是再次静默跳过。
2. `test_font_recent_source_sits_in_data_root` —— 端到端定位，钉住
   「`fonts/.recent.json` 在**数据根**下，不在 `temp/data/` 下」这一布局假设。

### 审查判定「已核查，无问题」的四项

1. **导入期循环依赖**：`py/paths.py` 只依赖 `os`；`main.py` 在 `sys.path.insert` 之后才导入
   `logging_setup`，后者顶层 `import paths` 能解析；database/auth 命中同一缓存模块。无环。
2. **白名单收紧后的包含关系**：`_MUSIC_DIR`（`temp/data/music`）仍是第 2、3 项的子目录；
   `audio_replace` 产物在 `temp/data/audio_replace`，被 `_is_safe_path` 放行、但不被
   `_is_safe_music_path` 放行 —— 两个函数的既有分工未被破坏。
3. **前缀绕过用例**：`scraped_images` 与 `scraped_images_evil` 迁后仍是同一父目录下的兄弟，
   用例仍在测原本要测的 `startswith` 前缀绕过防护。语义未漂移。
4. **`main.py` 的 `tmp_dir` 由相对写法改为 `_DATA_ROOT`**：开发模式等价（基址相同，仅多
   刻意的 `data/` 段）；**frozen 模式下是修复而非回归** —— 旧写法落到 PyInstaller 解压目录，
   与 `_run_weekly_cleanup_once` 早已用 `_DATA_ROOT` 的清理目录是**两个不同目录**（写、清对不上）；
   新写法让写/清/读三处对齐。已实测通过。
5. **`auth._scrape_root()` 的 frozen 行为未被意外改变**：根解析
   `os.path.dirname(current)` 原样保留，只多了 `data/` 段；既有隐患既未修掉也未恶化。
