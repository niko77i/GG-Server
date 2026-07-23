# 爬取 + 视频生成合并为统一页面

## 需求

将图片爬取和视频生成合并到一个页面，去掉页面跳转桥接，直接在一个页面完成完整流程。

## 方案

单一的 `MediaView.vue` 页面，从上到下三段布局：

```
┌─ ① 爬取图片 ──────────────────────────────┐
│ 输入链接 | saveDir | 爬取按钮               │
│ 结果列表（含 📥下载 🎬生成视频按钮）         │
└────────────────────────────────────────────┘
┌─ ② 图片预览 ──────────────────────────────┐
│ 选择包下拉框 / 扫描结果                     │
│ 图片网格预览                                │
└────────────────────────────────────────────┘
┌─ ③ 视频生成 ──────────────────────────────┐
│ Logo / AI / 设置 / 音乐 / 文案 / 生成按钮   │
└────────────────────────────────────────────┘
```

### 交互流程

1. 用户粘贴链接 → 爬取 → 结果出现在 ①
2. 点击 🎬 或手动选包 → 自动扫描 → 图片预览在 ②
3. 设置参数 → 生成视频 → 进度+下载在 ③

**不再需要 sessionStorage 桥接和路由跳转。**

### 远程用户：按用户隔离

- ② 的下拉框调用 `/api/scrape/packages`，后端按 `display_name` 返回当前用户自己的包
- 图片预览展示的是该用户目录下的图片
- 视频输出自动存到用户专属目录

### 代码组织

新建 `MediaView.vue`，复用现有逻辑：
- 爬取逻辑：从 `ScrapeView.vue` 搬过来
- 视频生成逻辑：从 `VideoView.vue` 搬过来
- 共享状态：选中的包路径（`videoDir`）在组件内直接传递

### 旧文件处理

- `ScrapeView.vue` → 删除
- `VideoView.vue` → 删除
- 路由 `/scrape` 和 `/video` → 合并为 `/media`

### 本机/远程用户适配

保持现有逻辑：远程用户隐藏 📂 按钮，使用下拉框选包和服务器目录。

## 改动清单

| 文件 | 操作 |
|---|---|
| `frontend/src/views/MediaView.vue` | **新建**，合并页面 |
| `frontend/src/router/index.js` | 加 `/media` 路由，删旧路由 |
| `frontend/src/views/ScrapeView.vue` | 删除 |
| `frontend/src/views/VideoView.vue` | 删除 |

后端无需改动。

---

## 实际代码逻辑补充（2026-07-23 审计）

以下基于 `frontend/src/views/MediaView.vue`（1085 行）和 `py/main.py` 中 media 相关路由的实际代码，对照设计文档逐项核对。

### 一、布局：设计为三段纵向，实际为「一段 + 双栏 + 侧边栏」

设计文档规划了 ①②③ 三段纵向堆叠布局。实际实现为：

```
┌─ ① 爬取图片 ─────────────────────────────────────┐
├───────────────────────────────────────────────────┤
│ ┌─ ② 图片预览 ───────┐ ┌─ ③ 视频生成 ───────┐ ┌─ 右侧历史栏 ─┐ │
│ │                     │ │                     │ │ 220px sticky │ │
│ │                     │ │                     │ │              │ │
│ └─────────────────────┘ └─────────────────────┘ └──────────────┘ │
└───────────────────────────────────────────────────┘
```

- ① 仍独占整行（`scrapeResults` 列表在下方展开后仍为全宽）。
- ② 和 ③ 为 `flex` 双栏并排，`flex:1` 各占一半宽度。
- 右侧额外增加了一个 220px、`position:sticky` 的历史设置侧边栏。**设计文档未提及此侧边栏。**

### 二、图片上传功能：设计文档未涉及，实际已完整实现

设计文档只提到"爬取图片"和"选择已爬取包"，完全没有提到用户手动上传图片。实际代码中 ② 区域包含完整的图片上传功能：

- **拖拽上传**：`dragover` / `drop` 事件，支持拖拽 PNG/JPG/WebP/BMP 到指定区域。
- **点击上传**：隐式 `<input type="file" accept="image/*" multiple>`。
- **后端 API**：`POST /api/scrape/upload-images`（JWT 认证），按用户 `display_name` 存储到 `_SCRAPE_DEFAULT_DIR/<dn>/_upload_<timestamp>/`，将上传文件统一转换为 PNG 格式。
- 上传成功后自动调用 `loadPackage()` 加载并扫描该目录。

### 三、图片排序面板（拖拽）：设计文档未提及，实际已完整实现

② 区域在图片网格上方有一个**排序面板**（`orderedImages`），用于确定视频中图片的出现顺序：

- 每张选中的图片以缩略卡片形式出现在排序面板中，可**拖拽重排**（HTML5 Drag & Drop API）。
- 支持「随机排序」按钮（Fisher-Yates shuffle）和「清空」按钮。
- 排序面板与 `selectedImgs` 双向同步：点击网格图片选中/取消选中时，排序面板同步增删；全选时排序面板同步全部图片。
- 生成视频时**优先使用排序面板的顺序**（`orderedImages`），仅在排序面板为空时才回退到勾选图片的网格顺序。
- 勾选"随机排序"复选框时自动调用 `shuffleOrdered()` 填充排序面板。

### 四、视频生成历史设置：设计文档未提及，实际已完整实现

右侧 220px sticky 侧边栏提供完整的历史设置功能：

**后端 API（5 个端点）**：
| 端点 | 方法 | 功能 |
|---|---|---|
| `/api/video/history/save` | POST | 保存当前设置（按 `username/pkg` 分组存为 JSON 文件） |
| `/api/video/history/list` | GET | 按用户名→包名两级分组返回所有历史 |
| `/api/video/history/delete` | POST | 删除指定包的全部历史或单条条目 |
| `/api/video/next-filename` | POST | 检查输出路径是否存在，返回 `_1`, `_2` 等不冲突文件名 |

**存储逻辑**：
- 历史文件目录：`<DATA_ROOT>/temp/video_set/`
- 文件结构：`{username}/{pkg}.json`（有用户名时）或 `{pkg}.json`（旧数据兼容，分组到 `_shared` 下）。
- 每个包最多保留 30 条历史。
- 每条记录包含：`saved_at` 时间戳、完整的 `settings` 对象、`ai` 配置、`videoDir`、`username`。

**前端交互**：
- 按用户名折叠/展开，点击历史条目调用 `applyHistory()` 恢复全部设置。
- 支持单条删除和整包删除。
- 视频生成完成后自动调用 `autoSaveHistory()` 保存当前设置。
- 页面挂载时 `loadHistory()` 加载，默认全部折叠。

### 五、任务队列：设计文档未提及，实际已实现

③ 区域底部有任务队列系统：

- 「添加到队列」按钮：将当前设置（`getSettings()`）快照后推入 `taskQueue` 数组。
- 「一键生成全部」按钮：快照当前队列并逐条执行 `doGenerate()`，每条之间间隔 1 秒。
- 队列项可单独移除（`el-tag` 的 `closable`）。
- 批量生成期间 `generatingBatch` 锁防止重复点击。
- 新加入队列的项留给下一次批量操作，不影响正在执行的批次。

### 六、输出路径自动填充：设计文档未提及

每次 `scanDir()` 扫描目录后，自动推断输出路径：

```javascript
// 从 videoDir 中提取包名，在父目录的 ai/ 子目录下生成同名 .mp4
const pkg = parts[parts.length - 1]
let outPath = parent + '/ai/' + pkg + '.mp4'
// 如果已存在则调用 nextFilename 自动加 _1, _2...
```

生成前还会再次调用 `nextFilename` 检查（除非勾选了"覆盖已有"）。

### 七、AI 动态化：设计文档仅提"AI"，实际有多服务商并行

设计文档只用「AI」一个词概括，实际实现包含：

- **5 个服务商**：豆包 Seedance 1.5 Pro（`doubao`）、豆包 Seedance 1.0 Pro Fast（`doubao-fast`）、Seedance 2.0（`seedance`）、Veo 3.1 Lite（`veo`）、Atlas Cloud（`atlas`），通过 `get_provider()` 工厂函数创建。
- **并行生成**：`ThreadPoolExecutor(max_workers=3)` 并行对所有图片调用 AI 生成视频。
- **两阶段进度**：AI 阶段占 50% 进度（`task.progress = completed / len(images) * 0.5`），FFmpeg 合成阶段占剩余 50%。
- AI 生成的临时视频存在 `temp/ai_videos/`，生成完成后清理。

### 八、后端新增 API（设计文档说"后端无需改动"——实际新增 9 个端点）

设计文档明确写「后端无需改动」，但实际代码中新增了以下端点：

| 端点 | 用途 |
|---|---|
| `POST /api/scrape/upload-images` | 图片上传 |
| `POST /api/video/next-filename` | 输出文件名冲突检测 |
| `POST /api/video/history/save` | 保存历史设置 |
| `GET /api/video/history/list` | 列出历史设置 |
| `POST /api/video/history/delete` | 删除历史设置 |
| `GET /api/video/music-list` | 列出服务器音乐 |
| `POST /api/video/upload-music` | 上传音乐（含 MP4→MP3 提取） |
| `GET /api/tasks` | 列出活跃/最近完成的任务（SQLite 兜底恢复） |
| `GET /api/fonts/list` + `POST /api/fonts/upload` + `GET /api/fonts/file/<id>` + `GET /api/fonts/preview` | 字体管理全套 |

### 九、音乐功能增强：设计文档仅提"音乐"，实际支持远程上传与预览

- **本机用户**：手动输入音乐路径 + 📂 浏览按钮。
- **远程用户**：
  - 下拉框选择服务器上已有的音乐文件（`GET /api/video/music-list`）。
  - 支持多文件上传（`POST /api/video/upload-music`），**MP4 文件自动用 FFmpeg 提取音频为 MP3** 后删除原始 MP4。
  - 选中音乐后可**即时预览播放**（`<audio>` 元素 → `/api/audio?path=`），支持停止按钮。
- 音频文件路径安全检查：`_is_safe_path()` 白名单校验，防止路径遍历。

### 十、字体系统：设计文档未提及，实际完整实现

③ 区域支持文案浮层的字体选择、上传和实时预览：

- **字体下拉框**：从 `videoStore.fonts` 加载，支持搜索。
- **字体上传**（`POST /api/fonts/upload`）：支持 `.ttf/.otf/.ttc/.woff/.woff2`，不限制本机访问。
- **实时预览**：选中字体后，通过 `@font-face` + `document.fonts.load()` 加载 Web 字体，在页面上实时渲染文案预览效果。
- **后端字体 API**：
  - `GET /api/fonts/list` — 列出所有可用字体（系统 + 用户导入）
  - `GET /api/fonts/file/<font_id>` — 提供字体文件（`font/ttf` 等 MIME）
  - `GET /api/fonts/preview` — 生成 560x210 字体标本卡图片（PIL 绘制）
  - `POST /api/fonts/upload` — 上传字体
  - `POST /api/fonts/import` — 本机用户从本地路径导入字体（限本机访问）
  - `POST /api/fonts/mark-used` — 标记最近使用

### 十一、管理员用户切换：设计文档未提及

设计文档仅提到"远程用户按 display_name 隔离"。实际代码中，当 `authStore.isAdmin === true` 时：

- ② 区域顶部出现「选择用户」下拉框，调用 `GET /api/scrape/users` 列出所有有爬取数据的用户。
- 切换用户后重新调用 `loadRemotePackages(userDn)` 加载该用户的包列表。
- 非管理员用户看不到此下拉框。

### 十二、本机用户手动路径输入：设计文档未提及

② 区域对于 `isLocalhost() === true` 的用户额外提供：

- 手动输入图片目录路径的文本框 + 📂 浏览按钮 + 🔍 扫描按钮。
- 这与下拉框选包是**并行的两种方式**，手动输入后调用 `doManualScan()` 等同于 `scanDir()`。

### 十三、爬取缓存机制：设计文档未提及

`POST /api/scrape` 在爬取前先检查目标目录是否已存在本地 PNG 文件。如果存在则直接返回已缓存结果（`from_cache: true`），跳过网络爬取。这避免了重复爬取同一 Google Play 页面。

### 十四、Logo 处理细节

- **爬取阶段**：Logo 保存在 `包logo/` 子目录（`{pkg_name}_logo.png`），**同时复制一份到包根目录**，作为内容图片使用且不会被叠加优化影响。
- **扫描阶段**：`video_scan_dir` 扫描时**显式跳过 `包logo/` 子目录**（`dirs[:] = [d for d in dirs if d != "包logo"]`），Logo 仅通过单独的 `logo` 字段返回，不混入 `images` 数组。
- ③ 区域 Logo 叠加支持 **6 种效果**：静态、淡入淡出、浮动弹跳、放大进入、从右滑入、脉冲缩放。

### 十五、转场效果扩展

设计文档仅示意性列出转场，实际代码支持 **14 种转场**：`fade`, `fadeblack`, `fadewhite`, `slideright`, `slideleft`, `slideup`, `slidedown`, `zoomin`, `dissolve`, `pixelize`, `circleopen`, `circleclose`, `wiperight`, `none`。

### 十六、动态背景模式

纯色背景支持 4 种动态模式：`breathe`（呼吸）、`wave`（波浪）、`beat`（律动）、`flow`（流光）。同时支持**背景图片**替代纯色背景（本机用户可浏览选择）。

### 十七、任务持久化与页面恢复

- **后端**：`POST /api/video/generate` 创建任务后立即写入 SQLite（`database.task_create`），完成后更新状态。内存中的 `_video_tasks` dict 在服务器重启后丢失，但 SQLite 提供兜底。
- **惰性清理**：每次查询进度时清理超过 1 小时的已完成/错误任务（内存 + DB 双清）。
- **前端恢复**：`onMounted` 时从 `taskStore.visibleTasks` 中查找 type 为 `video` 的最新任务，如果是 `running` 状态则恢复轮询（`pollLocalTask`），如果是 `completed` 则显示已完成信息。
- `GET /api/tasks` 返回最近 1 小时内活跃或完成的任务，供页面刷新后恢复用。

### 十八、路径安全

`/api/image` 和 `/api/audio` 两个静态文件服务端点均有 `_is_safe_path()` 白名单校验：

- 允许访问的目录：`_SCRAPE_DEFAULT_DIR`、`_MUSIC_DIR`、`<DATA_ROOT>/temp`。
- 使用 `os.path.realpath()` 解析后检查是否在白名单目录子树内，防止 `../` 路径遍历攻击。

### 十九、未按设计删除的内容

设计文档计划删除 `ScrapeView.vue` 和 `VideoView.vue`，路由 `/scrape` 和 `/video` 合并为 `/media`。**本次审计未验证旧文件是否已实际删除**（仅读取了 `MediaView.vue`），但代码层面确认 `MediaView.vue` 已自包含所有爬取和视频生成逻辑，不依赖旧组件。

### 二十、设计文档遗漏汇总

| 遗漏项 | 影响等级 |
|---|---|
| 图片上传（拖拽+点击） | 高 — 完整功能未在设计文档中体现 |
| 排序面板（拖拽排序图片顺序） | 高 — 影响视频输出结果的核心交互 |
| 历史设置侧边栏 | 高 — 完整功能模块 |
| 任务队列（批量生成） | 中 — 新增操作模式 |
| 输出路径自动填充 | 中 — 影响用户体验 |
| 字体系统（上传+预览） | 中 — 完整功能模块 |
| 音乐上传（远程用户） | 中 — 远程用户体验关键功能 |
| 管理员用户切换 | 中 — 管理员专属功能 |
| 本机手动路径输入 | 低 — 本机用户辅助功能 |
| 爬取缓存机制 | 低 — 性能优化 |
| 动态背景模式（4 种） | 低 — 参数扩展 |
| 任务持久化与页面恢复 | 低 — 可靠性增强 |
