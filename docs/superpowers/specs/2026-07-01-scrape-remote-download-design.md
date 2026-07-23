# 图片爬取 & 视频生成 — 远程用户支持

## 问题

远程用户（Tailscale 访问）用不了爬取和视频生成功能：

1. **ScrapeView**：📂 按钮 `_is_local_request()` → 403；手填路径不知道填什么 → 500
2. **VideoView**：同样要填服务器路径；输出视频也在服务器上，远程拿不到
3. **完整链路断裂**：爬取 → 生成视频 → 获取结果 全流程远程用户都无法使用

## 方案：服务器默认目录 + 下载

不改变核心流程（图片和视频都存在服务器上），让远程用户不需要手动填路径。

### 1. 爬取：默认保存目录

**后端**：新增配置 `_SCRAPE_DEFAULT_DIR`，路径为 `{DATA_ROOT}/temp/scraped_images/`。

`/api/scrape` 当 `save_dir` 为空时，自动使用 `{_SCRAPE_DEFAULT_DIR}/{用户display_name}/` 作为保存目录。每个用户有独立的子目录，互不干扰。

**前端**：`saveDir` 留空即可，placeholder 提示"留空则使用服务器默认目录"。📂 按钮仅本机（localhost/127.0.0.1/::1）可用。

```
远程用户打开页面 → saveDir 留空 → 粘贴链接 → 爬取 → 图片存在服务器 {SCRAPE_DEFAULT_DIR}/{用户名}/{包名}/
```

### 2. 爬取完成后：下载图片

**后端**：新增 `/api/scrape/download?path=...` 接口，将指定路径下的图片文件夹打包为 zip 返回下载。使用 query 参数传递路径（非路径参数）。

**前端**：爬取成功后每条结果显示"📥 下载图片"按钮 → 点击触发 `window.open('/api/scrape/download?path=...')` 触发浏览器下载 zip。

### 3. 视频生成：沿用现有逻辑

视频生成接口 `/api/video/generate` 没有本地限制，只需要路径正确：

- 爬取后 `saved_path` 通过"🎬 生成视频"按钮存入 `sessionStorage('bridgeVideoDir', dirPath)` → 跳转 `/video` 页面 → `VideoView` 读取该值自动填入 `videoDir`
- 视频输出也保存到服务器，远程用户可下载

### 4. 视频生成完成后：下载视频

新增 `/api/video/download?path=...` 接口，根据路径返回视频文件下载（`send_file` + `as_attachment=True`）。

**前端**：视频生成完成后显示"📥 下载视频"按钮。

---

## 实现详情

### 架构概览

```
py/
├── main.py            # Flask 路由（scrape + video + 静态文件服务）
├── scraper.py         # Google Play 页面爬取（图片 URL 提取）
├── resizer.py         # 图片下载、缩放、格式转换
├── video_processor.py # FFmpeg 视频生成（VideoTask）
├── utils.py           # extract_package_name, detect_format, natural_sort_key
├── ai_service.py      # AI 视频动态化（豆包等）
└── database.py        # SQLite 持久化（视频任务历史）

frontend/src/
├── views/ScrapeView.vue  # 爬取页面
├── views/VideoView.vue   # 视频生成页面
├── api/scrape.js         # scrape API 客户端
├── api/browse.js         # browse API 客户端（文件/文件夹浏览）
└── utils/env.js          # isLocalhost() 判断
```

### 后端路由总览

#### Scrape 相关（`py/main.py`）

| 路由 | 方法 | JWT | 说明 |
|------|------|-----|------|
| `/api/scrape` | POST | 需要 | 爬取 Google Play 页面图片。`save_dir` 为空时自动使用 `{_SCRAPE_DEFAULT_DIR}/{display_name}/`。支持 `include_ads_images` 参数（默认 true）。返回 `package_name`、`saved_path`、`image_count`、`images`、`logo`、`from_cache` |
| `/api/scrape/download` | GET | 不需要 | 下载爬取的图片目录为 zip。参数：`path`（query string），必须是已存在的目录 |
| `/api/scrape/packages` | GET | 需要 | 列出当前用户已爬取的包。管理员可传 `user_dn` 参数查看其他用户的数据 |
| `/api/scrape/users` | GET | 需要 | 列出所有有爬取数据的用户及其包数量（管理员查看所有用户用） |
| `/api/scrape/upload-images` | POST | 需要 | 上传图片到用户专属目录（`{_SCRAPE_DEFAULT_DIR}/{display_name}/_upload_{timestamp}/`），用于视频生成。支持 PNG/JPG/JPEG/WEBP/BMP，统一转为 PNG |

#### Video 相关（`py/main.py`）

| 路由 | 方法 | JWT | 说明 |
|------|------|-----|------|
| `/api/video/scan-dir` | POST | 不需要 | 扫描目录返回 PNG 图片列表和 logo 信息。跳过 `包logo` 子目录（logo 只用于叠加） |
| `/api/video/generate` | POST | 需要 | 提交视频生成任务。后台线程执行（FFmpeg + 可选 AI 动态化）。返回 `task_id`，状态码 202 |
| `/api/video/progress` | GET | 不需要 | 查询任务进度。惰性清理 >1 小时的过期任务 |
| `/api/video/tasks` | GET | 不需要 | 查询视频任务历史（从 SQLite + 内存合并） |
| `/api/video/download` | GET | 不需要 | 下载生成的视频文件。参数：`path`（query string） |
| `/api/video/music-list` | GET | 不需要 | 列出服务器可用背景音乐 |
| `/api/video/upload-music` | POST | 不需要 | 上传背景音乐。支持 MP3/WAV/AAC/M4A/OGG/FLAC/MP4（MP4 自动提取音频） |

#### 安全机制

- **路径安全**：`_is_safe_path()` 函数检查路径是否在 `_ALLOWED_STATIC_DIRS` 白名单内，防止路径遍历攻击。白名单包括 `_SCRAPE_DEFAULT_DIR`、`_MUSIC_DIR`、`{DATA_ROOT}/temp`
- **JWT 认证**：所有写操作（scrape、video/generate、upload-*）需要 JWT。下载和查询类接口无需认证（方便远程用户下载结果）
- **用户隔离**：每个用户的爬取数据存储在 `{display_name}/` 子目录下，管理员可通过 API 查看所有用户数据

### scraper.py 模块

```python
# 核心函数
scrape_images(url: str) -> list[str]
# 从 Google Play 页面 <c-wiz jsrenderer='UZStuc'> 内提取所有 <img> 的 src
# 自动补全相对路径，去重，升级 Google 图片 URL 为高清版本（=w1200-h1200）
# 抛出 ScrapeError 当页面不可访问或未找到目标标签

scrape_logo(url: str) -> str | None
# 从 Google Play 页面 <div class="Mqg6jb Mhrnjf"> 中提取第一张 <img> 的 src
# 返回绝对 URL，未找到返回 None
```

### resizer.py 模块

```python
# Google Ads 图片规格
FORMAT_CONFIG = {
    "landscape": {"min_short": 314},   # 横向：高是短边
    "square":    {"min_short": 200},   # 方形：两边相等
    "portrait":  {"min_short": 320},   # 纵向：宽是短边
}
MAX_FILE_SIZE = 5 * 1024 * 1024  # 5 MiB

process_image(img_url, save_dir, filename, skip_scaling=False) -> dict
# 下载 → 检测格式 → 等比放大到 Google Ads 最小短边 → 保存 PNG
# 如果文件 >5MiB，逐步缩小到 85% 直到达标
# skip_scaling=True 时保留原图尺寸（用户取消"按 Google Ads 规格放大"时）

save_logo(img_url, save_dir, filename) -> dict
# 下载 logo 原图 → 不做缩放 → 保存 PNG（文件 >5MiB 时缩小）
```

### `/api/scrape` 详细流程

```
1. 解析请求参数（url, save_dir, include_ads_images）
2. save_dir 为空 → 查询用户信息 → 生成用户子目录
3. 提取包名（extract_package_name）
4. 检查缓存：pkg_dir 已存在且有 PNG → 直接返回本地图片列表（from_cache: true）
5. 创建目录
6. Logo 爬取：scrape_logo → save_logo → 保存到 包logo/ 子目录
   → 同时复制一份到包根目录作为内容图片
7. 广告图片爬取：scrape_images → 并行下载（ThreadPoolExecutor, max 4 workers）
   → process_image 逐个处理
8. 返回 JSON：package_name, saved_path, image_count, images[], logo, from_cache
```

### 前端 ScrapeView.vue 关键行为

| 行为 | 实现 |
|------|------|
| 路径输入 | saveDir 默认留空，placeholder 提示"留空则使用服务器默认目录" |
| 📂 按钮 | 仅 `isLocalhost()` 为 true 时显示（localhost/127.0.0.1/::1），调用 browseApi.folder |
| URL 解析 | `parseUrls()` 支持换行、逗号、分号分隔；优先匹配 `play.google.com` 的完整 URL |
| 爬取请求 | 逐个请求（非并发），每个返回后立即更新结果列表 |
| 缓存提示 | `from_cache: true` 时显示"📂本地"标签 |
| 下载图片 | `window.open('/api/scrape/download?path=...', '_blank')` 触发浏览器下载 |
| 桥接视频 | `sessionStorage.setItem('bridgeVideoDir', saved_path)` → `router.push('/video')` |
| 自动跳转 | 单个链接爬取成功后自动跳转到视频生成页面 |
| 进度展示 | 爬取过程中逐条显示结果（⏳/✅/❌），完成后显示汇总 |

### 数据流：爬取 → 视频 完整链路

```
1. ScrapeView: 用户输入 Google Play 链接 → 点击"开始爬取"
2. POST /api/scrape → 服务器爬取 + 下载图片 → 返回 saved_path
3. 前端显示结果 + "🎬 生成视频" 按钮
4. 点击 → sessionStorage.setItem('bridgeVideoDir', saved_path)
5. router.push('/video')
6. VideoView onMounted: 读取 sessionStorage('bridgeVideoDir')
7. 自动填入 videoDir → 自动调用 POST /api/video/scan-dir
8. 用户选择图片 → POST /api/video/generate
9. 后台线程执行 FFmpeg（+可选 AI 动态化）
10. 轮询 GET /api/video/progress?task_id=...
11. 完成后显示"📥 下载视频" → GET /api/video/download?path=...
```

### 配置与常量

| 常量 | 值 | 说明 |
|------|-----|------|
| `_SCRAPE_DEFAULT_DIR` | `{DATA_ROOT}/temp/scraped_images` | 爬取图片默认存储目录 |
| `_MUSIC_DIR` | `{DATA_ROOT}/temp/music` | 背景音乐存储目录 |
| `_DATA_ROOT` | 开发模式：项目根目录；打包模式：EXE 所在目录 | 数据根目录 |
| `_ALLOWED_STATIC_DIRS` | `[_SCRAPE_DEFAULT_DIR, _MUSIC_DIR, {DATA_ROOT}/temp]` | 静态文件服务白名单 |

### 视频生成增强功能（设计文档未覆盖，已实现）

1. **AI 动态化**：支持豆包等 AI 服务将静态图片转为动态视频片段，可通过 `ai.enabled` + `ai.api_key` 启用
2. **任务持久化**：视频任务写入 SQLite（`database.task_create` / `task_update`），服务器重启后历史可查
3. **音频替换**：`/api/audio/replace` 支持上传视频 + 音频文件，用 FFmpeg 替换音轨
4. **背景音乐**：上传/管理背景音乐文件，视频生成时可选用
5. **图片上传**：`/api/scrape/upload-images` 允许用户直接上传图片用于视频生成（不经过爬取流程）

---

## 设计文档 vs 实际实现的差异

以下是设计文档中与最终代码不一致的地方，已在上方正文中修正：

| 项目 | 设计文档（原） | 实际代码 |
|------|-------------|---------|
| 下载接口路径 | `/api/scrape/download/<pkg_name>` | `/api/scrape/download?path=...`（query 参数） |
| save_dir 默认行为 | 直接用 `SCRAPE_DEFAULT_DIR` | 用 `{_SCRAPE_DEFAULT_DIR}/{display_name}/`（用户子目录隔离） |
| 前端自动填入 | `onMounted` 自动填入 saveDir | saveDir 留空，由后端自动处理 |
| 常量命名 | `SCRAPE_DEFAULT_DIR`（公开） | `_SCRAPE_DEFAULT_DIR`（Python 私有约定） |
| 新增接口数量 | 2 个（scrape/download, video/download） | 5 个 scrape + 6 个 video + 1 个 audio |
| 模块拆分 | 未提及 | 新增 `scraper.py`、`resizer.py` |
| Logo 爬取 | 未提及 | `scrape_logo()` + `save_logo()` + `包logo/` 子目录 |
| 缓存机制 | 未提及 | 目录已存在直接返回本地文件（`from_cache: true`） |
| Google Ads 规格 | 未提及 | `include_ads_images` 参数控制（resizer.py） |
| 并行下载 | 未提及 | `ThreadPoolExecutor(max_workers=4)` |
| AI 视频动态化 | 未提及 | 豆包等 AI 服务集成 |
| 路径安全 | 未提及 | `_is_safe_path()` + `_ALLOWED_STATIC_DIRS` |
| JWT 认证 | 未提及 | 写操作需要 JWT，读操作可选 |
| 用户隔离 | 未提及 | 按 display_name 分目录 |

---

## 备注

- `_SCRAPE_DEFAULT_DIR` 路径在服务器上，基于 `_DATA_ROOT`（开发模式为项目根目录，打包模式为 EXE 所在目录）
- 默认目录与 `_DATA_ROOT`（在 main.py 中根据 `sys.frozen` 动态计算）保持一致性
- `📂` browse 系列接口仅限 localhost 访问（`isLocalhost()` 判断），不依赖 `_is_local_request()`
- 视频生成任务在后台线程执行，前端通过轮询 `/api/video/progress` 获取进度
- 视频下载接口无 JWT 限制，方便远程用户通过链接直接下载
