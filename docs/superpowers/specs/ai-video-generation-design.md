# AI 视频生成功能 — 设计规格

**日期**: 2026-06-05
**状态**: 设计完成，待审核

---

## 1. 概述

在现有 Google Play 图片爬取工具中新增"AI 视频生成"功能。用户爬取完图片后，可将图片拼接为视频，可选叠加 Logo 水印，可选通过免费云端 AI（Seedance 2.0 / Veo 3.1 Lite）将静态图片转为动态短视频片段。

### 核心场景

1. 爬取某个 App 的 Google Play 截图和 Logo
2. 切换到"AI 视频生成"标签页
3. 选择爬取目录，扫描展示所有图片（缩略图网格）
4. 勾选需要的图片，设置 Logo 叠加、AI 动态化、转场、音乐等
5. 点击生成，输出 MP4 视频

### 设计原则

- **混合方案**：默认本地 FFmpeg 拼接（零成本），可选 AI 动态化（需 API Key）
- **零新增 Python 依赖**：视频处理调 FFmpeg 子进程，AI 调 HTTP API
- **缩略图预览**：图片以网格卡片展示，勾选时蓝色高亮边框
- **Logo 水印**：自动检测包 logo，可选位置/效果
- **可分发**：FFmpeg 打包进 EXE，分发给他人无需安装任何环境

---

## 2. 导航结构

### 布局：左侧侧边栏 + 右侧内容区

```
┌──────────────┬────────────────────────────────────────┐
│  Sidebar     │  内容区（面板切换）                      │
│  200px 固定   │                                        │
│  #2c3e50 深色 │  panel-scrape: 图片爬取（现有功能）      │
│              │  panel-video: AI 视频生成（新增）        │
│  📥 图片爬取  │                                        │
│  🎬 AI 视频  │  同一时间只显示一个面板                  │
│              │  JS switchTab() 切换                     │
└──────────────┴────────────────────────────────────────┘
```

- 点击侧边栏导航项 → 切换 `.tab-panel` 显示/隐藏
- 两个面板共享同一 HTML 页面，无需页面刷新
- 现有爬取功能不受影响，CSS 组件样式完全复用

---

## 3. 视频生成面板 UI

### 3.1 表单结构（自上而下）

**① 选择图片目录**
- 文本输入框（路径）+ "扫描" 按钮
- 调用 `/api/video/scan-dir` 获取图片列表

**② 图片列表（网格缩略图）**
- 3 列 CSS Grid 布局
- 每张图片一个卡片：`<img>` 缩略图 + 文件名 + 尺寸
- 每张卡片左上角勾选框
- 已选中卡片：蓝色边框 (`border: 2px solid #4a90d9`) + 浅蓝背景
- 未选中卡片：灰色边框 (`#ddd`)
- 顶部提供"全选 / 取消全选"
- 图片通过 `GET /api/image?path=...` 加载

**③ Logo 叠加设置（可选）**
- 自动检测 `包logo/包名_logo.png`
- 复选框启用
- 位置选择：左上 / 右上 / 左下 / 右下 / 浮动
- 效果选择：静态 / 淡入淡出 / 浮动弹跳

**④ AI 动态化（可选）**
- 复选框："使用 AI 将静态图片转为短视频"
- 勾选后展开：API 服务下拉 (Seedance 2.0 / Veo 3.1 Lite / Atlas Cloud)、API Key 输入框、每段时长 (3-8s)
- **Seedance 2.0**（推荐）：每日 225 免费积分（约 10-15 个短视频），图片转视频效果最佳
- **Veo 3.1 Lite**：完全免费，视频自带音频生成（无需额外音乐文件）
- **Atlas Cloud**：统一接入网关，一个 Key 切换多个后端模型
- 未勾选或不填 Key → 降级为静态帧，不影响视频生成

**⑤ 视频设置**
- 单帧时长：3 / 4 / 5 秒（静态图片模式）
- 转场效果：淡入淡出 / 滑动 / 缩放 / 无
- 背景音乐：文件选择（.mp3，可选）
- 输出分辨率：1080p (1920×1080) / 720p (1280×720)
- 输出路径：文本输入

**⑥ 生成按钮 + 进度显示**
- 🎬 生成视频 按钮
- 进度条 + 状态文字（"正在生成第 3/10 帧..."）
- 完成时显示输出路径、文件大小、时长

---

## 4. 后端 API

### 现有 API（不变）

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/` | 返回前端页面 |
| GET | `/api/health` | 健康检查 |
| POST | `/api/scrape` | 爬取图片 |

### 新增 API（4 个端点）

#### 4.1 `POST /api/video/scan-dir`

扫描目录返回图片列表和 logo 信息。

请求：`{"dir": "F:/images/com.spotify.music"}`

成功响应 (200)：
```json
{
  "success": true,
  "images": [
    {"filename": "xxx_001.png", "path": "F:/.../001.png", "width": 1200, "height": 628},
    ...
  ],
  "logo": {"filename": "xxx_logo.png", "path": "F:/.../logo.png", "width": 512, "height": 512}
}
```

失败 (400/404)：`{"success": false, "error": "..."}`

#### 4.2 `GET /api/image?path=<绝对路径>`

返回图片文件流，供前端 `<img>` 加载缩略图。

- 路径白名单校验（防止目录遍历攻击）
- 返回 `image/png`，带缓存头

#### 4.3 `POST /api/video/generate`

提交视频生成任务（后台线程执行）。

请求：
```json
{
  "images": ["F:/.../001.png", "F:/.../002.png"],
  "logo": {"path": "F:/.../logo.png", "position": "top-right", "effect": "static"},
  "ai": {"enabled": true, "service": "seedance", "api_key": "sk-xxx", "duration": 4},
  "settings": {
    "duration_per_frame": 3,
    "transition": "fade",
    "music_path": null,
    "resolution": "1920:1080",
    "output_path": "F:/output/video.mp4"
  }
}
```

响应 (202)：`{"success": true, "task_id": "abc123", "message": "视频生成已开始"}`

#### 4.4 `GET /api/video/progress?task_id=xxx`

轮询进度。

进行中：`{"status": "processing", "progress": 0.45, "message": "编码中... 45%"}`
完成：`{"status": "completed", "progress": 1.0, "output": {"path": "...", "size_mb": 12.3, "duration_s": 30}}`
失败：`{"status": "error", "progress": 0.0, "error": "FFmpeg 执行失败: ..."}`

---

## 5. 视频处理流水线 (`py/video_processor.py`)

### 5.1 核心类：`VideoTask`

- 封装 FFmpeg 命令构建 + 子进程执行 + 进度解析
- 通过 `_video_tasks` 字典跟踪状态
- 在独立线程中运行，更新进度字段

### 5.2 FFmpeg 滤镜链（单命令，无临时文件）

所有图片在一个 FFmpeg 命令中完成，避免中间文件写入：

```
对每张图片:
  [i:v] loop=-1, trim=duration=N, setpts=PTS-STARTPTS,
        scale=W:H:force_original_aspect_ratio=decrease,
        pad=W:H:(ow-iw)/2:(oh-ih)/2, setsar=1 [vi]

Xfade 转场链:
  [v0][v1] xfade=transition=fade:duration=0.5:offset=2.5 [f0]
  [f0][v2] xfade=transition=fade:duration=0.5:offset=5.0 [f1]
  ...

Logo 叠加（可选）:
  [fN][logo] overlay=W-w-20:20 [outv]

音频（可选）:
  [bg_music] volume=0.3, aloop=... [bga]

输出:
  -map [outv] -map [bga] -c:v libx264 -preset medium -crf 18 final.mp4
```

### 5.3 转场映射

| UI 名称 | FFmpeg xfade 值 |
|---------|----------------|
| 淡入淡出 | fade |
| 滑动 | slideright |
| 缩放 | zoomin |
| 无 | fade (duration=0) |

### 5.4 Logo 位置映射

| UI | overlay 表达式 |
|----|---------------|
| 左上 | `10:10` |
| 右上 | `W-w-10:10` |
| 左下 | `10:H-h-10` |
| 右下 | `W-w-10:H-h-10` |
| 浮动 | `10+20*sin(t*2):H-h-10-20*abs(cos(t*1.5))` |

### 5.5 进度解析

解析 FFmpeg stderr 中的 `time=HH:MM:SS.ms`，计算 `progress = current_time / total_duration`。

### 5.6 降级处理

- AI 生成失败 → 降级为原始静态图片
- FFmpeg xfade 不可用 (版本 < 4.3) → 降级为无转场拼接

---

## 6. AI 集成 (`py/ai_service.py`)

### 6.1 抽象接口

```python
class AIProvider:
    def generate_video(self, image_path: str, duration: int, api_key: str) -> str:
        """返回生成的 MP4 本地路径，失败抛 AIServiceError"""
```

### 6.2 Atlas Cloud 统一网关（推荐）

Atlas Cloud 提供统一 REST API，一个 Key 接入 300+ 模型，兼容 OpenAI SDK 格式。

```python
class AtlasProvider(AIProvider):
    """通过 Atlas Cloud 调用 Seedance 2.0 / Kling / Vidu 等模型。"""
    BASE_URL = "https://api.atlascloud.ai/v1"
```

调用流程：
1. `POST /v1/video/generate` 提交生成请求（指定 `model` 参数）
2. 轮询任务状态直到完成
3. 下载视频到 `{output_dir}/.ai_temp/`

### 6.3 内置 Provider 注册表

| Provider 类 | 后端模型 | 免费额度 | 特点 |
|------------|---------|---------|------|
| `SeedanceProvider` (推荐) | Seedance 2.0（字节/即梦） | 每日 225 积分 ≈ 10-15 个视频 | 图转视频效果最好，ELO 全球第 2 |
| `VeoProvider` | Veo 3.1 Lite（Google） | 完全免费 + NexaAPI 100 次 | 视频自带音频生成 |
| `AtlasProvider` | 可切换多个模型 | $1 体验金 | 统一网关，灵活切换 |

```python
# 服务注册表
AI_PROVIDERS = {
    "seedance": AtlasProvider,       # 通过 Atlas Cloud 调用 Seedance 2.0
    "veo": VeoProvider,              # Google Veo 3.1 Lite
    "atlas": AtlasProvider,          # Atlas Cloud 多模型切换
}

def get_provider(name: str) -> AIProvider:
    cls = AI_PROVIDERS.get(name)
    if cls is None:
        raise AIServiceError(f"不支持的 AI 服务: {name}")
    return cls()
```

### 6.4 Veo 3.1 Lite (`VeoProvider`)

通过 NexaAPI（免费，无需绑卡）调用 Google Veo 3.1 Lite：
- 最长 8 秒，支持 720p-1080p
- **独有优势**：生成视频自带同步音效（唯一支持此功能的免费方案）
- 有速率限制，适合少量图片

### 6.5 AI 临时文件

- 存放位置：`{输出目录}/.ai_temp/`
- 视频生成完成后自动清理

---

## 7. FFmpeg 打包方案

### 7.1 获取 FFmpeg

从 [gyan.dev](https://www.gyan.dev/ffmpeg/builds/) 下载 Windows 便携版 `ffmpeg.exe`（约 80MB）。

### 7.2 PyInstaller 打包

```
pyinstaller --onefile \
  --add-binary "ffmpeg.exe;." \
  --add-data "index.html;." \
  --add-data "css/style.css;css" \
  --add-data "js/app.js;js" \
  --add-data "js/video.js;js" \
  py/main.py
```

### 7.3 运行时定位

`py/main.py` 中新增 `_get_ffmpeg_path()` 函数：

```python
def _get_ffmpeg_path():
    if _FROZEN:
        return os.path.join(sys._MEIPASS, "ffmpeg.exe")
    # 开发模式：先查 PATH，再查常见位置
    ...
```

---

## 8. Flask 线程配置

视频生成是长任务，Flask 开发服务器需启用多线程：

```python
app.run(host=host, port=port, debug=False, threaded=True)
```

任务状态存储在模块级字典 `_video_tasks = {}`，完成 30 分钟后自动清理。

---

## 9. 文件变更清单

### 新增文件

| 文件 | 说明 |
|------|------|
| `py/video_processor.py` | VideoTask 类，FFmpeg 命令构建与执行 (~250 行) |
| `py/ai_service.py` | AIProvider 接口 + KlingProvider 实现 (~150 行) |
| `js/video.js` | 视频面板 UI 逻辑 (~350 行) |

### 修改文件

| 文件 | 变更内容 |
|------|---------|
| `index.html` | 添加 `<nav class="sidebar">` 和 `<div id="panel-video">` |
| `css/style.css` | 添加侧边栏 + 视频面板 + 图片网格样式 |
| `js/app.js` | 添加 `switchTab()` 函数（约 10 行） |
| `py/main.py` | 添加 4 个新 API 路由 + `_get_ffmpeg_path()` + `threaded=True` |

### 不变更

| 文件 | 原因 |
|------|------|
| `py/scraper.py` | 爬取逻辑无变化 |
| `py/resizer.py` | 图片缩放逻辑无变化 |
| `py/utils.py` | 工具函数无变化 |
| `requirements.txt` | 无新增 Python 依赖 |

---

## 10. 实现顺序

### 阶段 1：布局重构（最安全，不改变现有行为）
1. 更新 `css/style.css`：添加侧边栏布局
2. 更新 `index.html`：添加侧边栏 + 两个面板
3. 更新 `js/app.js`：添加 `switchTab()` 函数
4. 验证：爬取功能完全不受影响

### 阶段 2：后端视频处理
5. 创建 `py/video_processor.py`
6. 添加到 `main.py` 的路由：`/api/video/scan-dir`、`/api/image`、`/api/video/generate`、`/api/video/progress`
7. 创建 `py/ai_service.py`

### 阶段 3：前端视频面板
8. 创建 `js/video.js`
9. 填充 `index.html` 中 `#panel-video` 的 HTML 结构

### 阶段 4：打包与测试
10. 更新打包命令（含 FFmpeg）
11. 端到端测试
12. 更新 CLAUDE.md 文档

---

## 11. 验证方案

### 开发模式测试

1. 启动 `python py/main.py`，浏览器打开 localhost:5000
2. 在爬取页爬一个 App 的图片
3. 切换到视频页，扫描爬取目录
4. 确认缩略图网格正确显示
5. 勾选部分图片，设置 Logo、转场，点击生成
6. 确认生成 MP4 可播放，转场/logos 正确

### AI 功能测试（需 API Key）

7. 启用 AI，填入 API Key（推荐 Seedance 2.0），用 1-2 张图片测试
8. 确认 AI 生成的动态片段正确拼接

### EXE 打包测试

9. 打包 EXE，在新环境（无 Python/FFmpeg）中运行
10. 确认视频生成功能正常

### 错误路径测试

- 空目录扫描 → 显示提示
- 无 FFmpeg → 显示错误
- AI API Key 错误 → 降级为静态帧
- 音乐文件不存在 → 跳过音乐


---

## 附录 A：代码审计补充（2026-07-23）

本章节对比设计文档（2026-06-05）与当前代码实现（`py/ai_service.py`、`py/video_processor.py`、`py/main.py` 视频路由、`frontend/src/views/MediaView.vue`），记录差异、补充遗漏、标注待修正项。

---

### A.1 前端架构：从原生 JS SPA 变为 Vue 3 + Element Plus

**设计文档描述**：单个 `index.html` + `js/video.js` + `css/style.css`，侧边栏切换面板。

**实际实现**：Vue 3 Composition API (`<script setup>`) + Element Plus 组件库，所有功能集中在 `MediaView.vue` 单文件组件中（约 1085 行）。使用 Pinia stores (`videoStore`、`taskStore`、`authStore`) 和独立 API 模块 (`videoApi`、`scrapeApi`、`browseApi`)。

**影响**：第 2 节的导航结构和第 9 节的文件变更清单已完全过时。不存在 `index.html` 侧边栏、`js/video.js`、`js/app.js` 这些文件。前端代码位于 `frontend/src/views/MediaView.vue`，样式为 scoped CSS。

---

### A.2 后端 API 端点完整清单（设计文档遗漏 14 个端点）

设计文档第 4 节只列出了 4 个新增 API。实际代码中，视频/媒体相关端点远多于此。以下是完整对照：

#### A.2.1 设计文档已列出（4 个，均有实现）

| 端点 | 实际实现与文档差异 |
|------|-------------------|
| `POST /api/video/scan-dir` | 响应额外返回 `package_name` 字段；图片列表中 `filename` 为相对路径（含子目录），而非仅文件名 |
| `GET /api/image` | 增加了白名单目录校验（`_ALLOWED_STATIC_DIRS`），包含 scrape 默认目录、音乐目录、temp 目录 |
| `POST /api/video/generate` | **增加了 `@jwt_required()` 认证装饰器**（文档未提及）；支持 `random_order` 参数；settings 中增加了大量新字段（见 A.3） |
| `GET /api/video/progress` | 增加了惰性清理逻辑（>1 小时的完成任务自动从内存和 DB 清除）；增加了 SQLite 兜底查询（服务器重启后可从 DB 恢复任务状态） |

#### A.2.2 设计文档未列出但代码中已实现（14 个端点）

| 端点 | 方法 | 说明 | 认证 |
|------|------|------|------|
| `/api/video/download` | GET | 下载已生成的视频文件（`send_file` as_attachment） | 无 |
| `/api/video/music-list` | GET | 列出服务器 `music/` 目录下可用背景音乐 | 无 |
| `/api/video/upload-music` | POST | 上传背景音乐，支持 MP4 自动提取音频为 MP3 | 无 |
| `/api/video/next-filename` | POST | 检查输出路径冲突，返回 `_1`、`_2` 递增后的可用路径 | 无 |
| `/api/video/history/save` | POST | 保存视频生成设置到 `temp/video_set/{username}/{pkg}.json` | 无 |
| `/api/video/history/list` | GET | 按用户名→包名两级分组返回所有历史设置 | 无 |
| `/api/video/history/delete` | POST | 删除指定包或包内指定索引的历史条目 | 无 |
| `/api/tasks` | GET | 返回活跃/最近任务列表（页面刷新恢复用） | JWT |
| `/api/scrape/packages` | GET | 列出用户已爬取的包（管理员可按 `user_dn` 查看他人） | JWT |
| `/api/scrape/users` | GET | 列出所有有爬取数据的用户（管理员用） | JWT |
| `/api/scrape/upload-images` | POST | 上传图片到用户专属目录，统一转 PNG | JWT |
| `/api/audio` | GET | 音频流服务，供前端 `<audio>` 预览播放 | 无 |
| `/api/audio-replace` | POST | 上传视频+音频，替换视频的音频轨道 | 无 |
| `/api/audio-replace/download` | GET | 下载音频替换后的视频 | 无 |
| `/api/audio-replace/history` | GET/DELETE | 音频替换历史记录管理 | 无 |
| `/api/fonts/list` | GET | 返回所有可用字体（系统 + 用户导入） | 无 |
| `/api/fonts/upload` | POST | 上传字体文件到 `fonts/` 目录 | 无 |
| `/api/fonts/import` | POST | 本机导入字体（支持多选和目录递归） | 本机 |
| `/api/fonts/preview` | GET | 生成字体标本卡预览图（PIL 渲染） | 无 |
| `/api/fonts/file/<font_id>` | GET | 提供字体原文件（供 CSS @font-face） | 无 |
| `/api/fonts/mark-used` | POST | 标记字体为最近使用 | 无 |
| `/api/font-file` | GET | 按绝对路径提供字体文件（前端预览加载） | 无 |

> **审计结论**：API 端点数量从设计的 4 个扩展到实际的 20+ 个，需补充完整 API 参考文档。

---

### A.3 `/api/video/generate` 请求体字段完整清单

设计文档中的请求体缺少以下实际支持的字段。以下为完整的 settings 对象字段（标注 **粗体** 为设计文档遗漏项）：

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `output_path` | string | - | 输出 MP4 路径 |
| `duration_per_frame` | int | 3 | 单帧时长（秒） |
| `transition` | string | `"fade"` | 转场效果（13 种可选，见 A.6） |
| `resolution` | string | `"1080:1920"` | 输出分辨率 `W:H` 格式 |
| **`use_logo`** | bool | false | 是否启用 Logo 叠加 |
| **`logo_path`** | string | auto | Logo 图片路径（不传则自动从 `包logo/` 子目录查找，最多向上查找 2 层父目录） |
| **`logo_position`** | string | `"top-right"` | Logo 位置（5 种） |
| **`logo_effect`** | string | `"static"` | Logo 效果（6 种：static/fade/bounce/zoom-in/slide-right/pulse） |
| **`logo_size`** | int | 16 | Logo 缩放比例（8-25%，相对于画面宽度） |
| **`background_path`** | string | - | 背景图片路径（可选，支持自定义背景图） |
| **`background_color`** | string | `"1a1a2e"` | 纯色背景的十六进制颜色值 |
| **`dynamic_bg`** | bool | false | 是否启用动态背景效果 |
| **`dynamic_bg_mode`** | string | `"breathe"` | 动态背景模式（breathe/wave/beat/flow），使用 FFmpeg geq 滤镜生成 |
| **`content_scale`** | float | 0.82 | 内容图片相对于画布的最大缩放比例 |
| **`text1`** | string | - | 文案浮层第 1 条 |
| **`text2`** | string | - | 文案浮层第 2 条 |
| **`text_font`** | string | `"simhei"` | 文案字体 ID |
| **`texts`** | array | - | 文案数组格式（兼容 `text1`+`text2`） |
| **`overwrite`** | bool | false | 是否覆盖已有输出文件（不勾选则自动追加 `_1`、`_2`） |
| `music_path` | string | - | 背景音乐路径 |
| **`random_order`** | bool | false | 是否随机打乱图片顺序 |

**Logo 自动检测逻辑**（文档描述不完整）：
1. 前端优先传 `logo_path`
2. 否则从第一张图片的目录向上查找 `包logo/` 子目录（最多 2 层父目录）
3. 匹配 `_logo.png` 结尾的文件

---

### A.4 AI Provider 架构实际实现

#### A.4.1 设计文档与代码差异

| 项目 | 设计文档 | 实际代码 |
|------|---------|---------|
| Provider 数量 | 3 个 (seedance, veo, atlas) | 5 个 (seedance, doubao, doubao-fast, veo, atlas) |
| SeedanceProvider | 独立类 | **继承 AtlasProvider**，固定 `model="seedance-2.0"` |
| DoubaoProvider | **不存在（文档未提及）** | 独立实现，使用火山方舟 Ark SDK（`volcenginesdkarkruntime`），模型 `doubao-seedance-1-5-pro-251215` |
| DoubaoFastProvider | **不存在** | 继承 DoubaoProvider，模型 `doubao-seedance-1-0-pro-fast-251015` |
| KlingProvider | 文档提及但**代码中不存在** | 如需 Kling 可用 AtlasProvider 指定 `model="kling-3.0"` |
| VeoProvider | 通过 NexaAPI（免费） | 实现一致，但增加了详细日志输出、支持同步和异步两种响应格式 |
| `get_provider()` | 不接受额外参数 | 支持 `**kwargs` 传递给构造函数（如 `model`） |

#### A.4.2 豆包 Seedance（文档完全遗漏）

```python
# DoubaoProvider 的核心特征（未在文档中记载）：
# - 使用 data URI (base64) 内嵌图片，无需公网 URL
# - 支持 custom_prompt 参数自定义视频效果描述
# - 豆包 i2v 只支持 5 秒和 10 秒两种时长
# - 调用方式：Ark SDK content_generation.tasks.create() + 轮询
# - 超时时间：900 秒（15 分钟），比其他 provider（600 秒）更长
# - 图片编码：PIL 缩放 + JPEG 压缩，确保 ≤ 2MB
# - 默认 prompt："镜头缓缓推进，画面中的人物和景物自然微动，光影流转，营造电影级氛围感"
```

#### A.4.3 前端默认值差异

前端 AI 服务下拉默认选 `doubao`（豆包 Seedance 1.5 Pro），标签为"效果最佳"。设计文档推荐 `seedance`（Seedance 2.0）。两者不一致。

---

### A.5 视频处理流水线（video_processor.py）实际实现

设计文档估计约 250 行，实际约 **693 行**，复杂度大幅超过预期。

#### A.5.1 滤镜链实际结构

设计文档描述的线性滤镜链与实际实现差异显著。实际滤镜链为：

```
① 背景层处理 [bg]
   ├── 静态背景图 → loop → trim → scale → crop → format=rgba
   ├── 动态纯色背景 → color → geq (4种模式) → format=rgba → trim
   └── 纯色静态背景 → color → format=rgba → trim

② 内容图片/AI视频 → [v0], [v1], ...
   ├── AI 视频（如有）: trim → scale → format=rgba → pad → fps=30
   └── 静态图片: loop → trim → scale → format=rgba → pad → fps=30

③ 转场链
   ├── 多图有转场: xfade 链式拼接
   ├── 多图无转场: concat 直接拼接
   └── 单图: 直接使用 [v0]

④ 背景+前景合成: [bg][fg] overlay → [comp]

⑤ Logo 叠加（可选）
   ├── [logo] loop → trim → scale → colorkey(去白底) → colorchannelmixer(85%透明) → split
   ├── 阴影分支: colorchannelmixer(25%透明) → boxblur(6px) → [l_shadow]
   ├── 效果分支: fade/bounce/zoom-in/slide-right/pulse/static → [l_effected]
   ├── [comp][l_shadow] overlay → [with_shadow]
   └── [with_shadow][l_effected] overlay → [post_logo]

⑥ 文案浮层（可选，最多2条）
   ├── PIL 精确文字宽度测量 + 智能换行
   ├── 随机种子（基于文案内容 hash，可复现）
   ├── 不重叠时间编排（每条占视频时长 30%~40%）
   ├── 淡入淡出 alpha 表达式
   └── drawtext 滤镜链：shadowcolor + borderw 描边效果

⑦ 编码准备: format=yuv420p → [outv]

⑧ 音频
   ├── 背景音乐: volume=0.3 → aloop → atrim → [aout]
   ├── AI 视频音频（无音乐时）: ffprobe 检测 → atrim 提取 → [aout]
   └── 静音（兜底）: anullsrc → atrim → [s]
```

#### A.5.2 设计文档遗漏的关键实现细节

| 遗漏项 | 实现细节 |
|--------|---------|
| 动态背景 | 4 种 FFmpeg geq 模式：breathe（呼吸脉动，0.55Hz）、wave（波浪流动）、beat（1.3Hz 节拍 + 色相偏移）、flow（对角流光） |
| Logo 去白底 | `colorkey=0xffffff:0.25:0.1` 滤镜自动移除白色/近白色背景 |
| Logo 半透明 | `colorchannelmixer=aa=0.85` 设置 85% 不透明度 |
| Logo 阴影 | 25% 不透明度 + boxblur(6px) + 偏移 2px |
| Logo 缩放 | 画面宽度的 8%~25%（前端滑块控制，默认 16%，最小值 48px） |
| AI 视频音频 | 使用 ffprobe 检测 AI 视频是否有音频轨道，有则自动提取作为背景音 |
| 内容缩放 | 内容图片缩放到 `画面宽度 × content_scale`（默认 82%）的内部区域 |
| 文件名冲突 | 不勾选覆盖时，自动追加 `_1`、`_2`…直到不冲突 |
| 字体定位 | 跨平台字体查找（Windows 系统字体、项目 fonts/ 用户字体、macOS/Linux 回退） |
| 中文换行 | PIL `ImageFont.getlength()` 精确测量 + `_wrap_text()` 智能分词换行 |
| Fontconfig | 设置 `FONTCONFIG_PATH` 环境变量防止 FFmpeg drawtext 崩溃 |

#### A.5.3 FFmpeg 路径解析（`_get_ffmpeg_path()`）

设计文档的 3 步查找已扩展为：

1. PyInstaller 打包路径：`sys._MEIPASS/ffmpeg.exe`
2. 项目根目录：`{project_root}/ffmpeg.exe`
3. 系统 PATH：`shutil.which("ffmpeg")`
4. 硬编码回退：`C:\ffmpeg\bin\ffmpeg.exe`
5. 最终兜底：返回字符串 `"ffmpeg"`（依赖系统 PATH）

---

### A.6 UI 控件选项完整清单

#### A.6.1 转场效果（设计文档 4 种 → 实际 13 种）

| UI 名称 | xfade 值 | 文档中 |
|---------|---------|--------|
| 淡入淡出 | fade | 是 |
| 黑场过渡 | fadeblack | **否** |
| 白场过渡 | fadewhite | **否** |
| 向右滑动 | slideright | 是 |
| 向左滑动 | slideleft | **否** |
| 向上滑动 | slideup | **否** |
| 向下滑动 | slidedown | **否** |
| 缩放 | zoomin | 是 |
| 溶解 | dissolve | **否** |
| 像素化 | pixelize | **否** |
| 圆形展开 | circleopen | **否** |
| 圆形收缩 | circleclose | **否** |
| 擦除 | wiperight | **否** |
| 无 | none | 是 |

#### A.6.2 Logo 效果（设计文档 3 种 → 实际 6 种）

设计文档：静态 / 淡入淡出 / 浮动弹跳
实际增加：放大进入 (zoom-in)、从右滑入 (slide-right)、脉冲缩放 (pulse)

#### A.6.3 输出分辨率

设计文档：1080p (1920×1080) / 720p (1280×720)
实际前端：**9:16 竖屏 (1080×1920)** / **1:1 方形 (1080×1080)**

> **注**：后端 `resolution` 参数是通用的 `W:H` 格式，前端限制了选项但后端支持任意分辨率。

#### A.6.4 新增 UI 功能（设计文档完全遗漏）

| 功能 | 说明 |
|------|------|
| 图片上传 | 拖拽/点击上传 PNG/JPG/WebP/BMP，统一转 PNG 存到用户专属目录 |
| 图片排序面板 | 拖拽排序（HTML5 Drag & Drop），可为视频指定图片出现顺序 |
| 随机排序 | 一键打乱排序面板中的图片顺序 |
| 背景图片 | 自定义背景图替代纯色背景 |
| 动态背景 | 4 种动态纯色背景模式（呼吸/波浪/律动/流光）+ 颜色选择器 |
| 内容缩放 | 70%/82%/92%/100% 四档控制内容在画面中的占比 |
| 文案浮层 | 最多 2 条文字，自定义字体，实时 CSS @font-face 预览 |
| 字体管理 | 上传/导入字体文件，存储到 `fonts/` 目录 |
| 任务队列 | 添加多个任务到队列，一键批量生成 |
| 音乐预览 | 远程服务器上可试听音乐 |
| 音乐上传 | 支持 MP4 自动提取音频（FFmpeg `-vn -acodec libmp3lame`） |
| 历史记录 | 按用户名+包名保存/恢复视频生成设置（JSON 文件存储） |
| 多用户管理 | 管理员可切换查看其他用户爬取的数据 |

---

### A.7 认证与安全

**设计文档未提及任何认证机制**。实际实现：

1. `POST /api/video/generate` — `@jwt_required()`，需要登录
2. `GET /api/tasks` — `@jwt_required()`
3. `GET /api/scrape/packages` — `@jwt_required()`，管理员可传 `user_dn` 查看他人数据
4. `GET /api/scrape/users` — `@jwt_required()`
5. `POST /api/scrape/upload-images` — `@jwt_required()`
6. `GET /api/image` — 白名单路径校验（`_is_safe_path`）防止目录遍历攻击
7. `GET /api/audio` — 同上白名单校验
8. `POST /api/fonts/import` — `_is_local_request()` 仅允许本机访问

---

### A.8 数据持久化

**设计文档**：仅模块级字典 `_video_tasks`，30 分钟后清理。

**实际实现**：双重持久化。

1. **内存**：`_video_tasks` 字典（快速访问）
2. **SQLite**：`video_tasks` 表，字段 `task_id, status, progress, message, output_path, created_at, finished_at`。用于：
   - 服务器重启后任务状态恢复
   - 前端页面刷新后通过 `/api/tasks` 恢复进度
3. **历史设置**：`temp/video_set/{username}/{pkg}.json`，每包最多 30 条
4. **清理策略**：每次查询进度时惰性清理 >1 小时的已完成任务（内存 + DB 同步删除）

---

### A.9 文件变更清单修正

实际文件清单与设计文档第 9 节有重大差异：

#### 新增文件（实际）

| 文件 | 实际行数 | 设计文档估计 |
|------|---------|------------|
| `py/video_processor.py` | ~693 行 | ~250 行 |
| `py/ai_service.py` | ~366 行 | ~150 行 |
| `frontend/src/views/MediaView.vue` | ~1085 行 | 无（设计文档假设原生 JS） |

#### 修改文件（实际）

| 设计文档假设 | 实际 |
|-------------|------|
| `index.html` 添加侧边栏 + 面板 | **不需要**：Vue SPA 路由，所有功能在 MediaView.vue 中 |
| `css/style.css` 添加视频面板样式 | **不需要**：scoped CSS 在 .vue 文件中 |
| `js/app.js` 添加 `switchTab()` | **不存在**：Vue Router + 组件切换 |
| `py/main.py` 添加 4 个路由 | **添加了 20+ 个路由**（视频、音频、字体、历史、包管理） |

#### 未在变更清单中的实际新增

| 文件/模块 | 说明 |
|----------|------|
| `frontend/src/stores/video.js` | Pinia store（视频状态管理） |
| `frontend/src/api/video.js` | API 请求封装 |
| `py/main.py` 字体相关路由（7 个端点） | 字体管理 CRUD |
| `py/main.py` 音频替换路由（3 个端点） | 视频音轨替换 |
| `py/main.py` 历史记录路由（3 个端点） | 设置保存/恢复 |
| `py/main.py` 包管理路由（3 个端点） | 多用户包列表 |
| `py/main.py` 任务列表路由 | `/api/tasks` |
| SQLite `video_tasks` 表 | 任务持久化 |

---

### A.10 关键需要修正的设计文档章节

| 章节 | 问题 | 严重程度 |
|------|------|---------|
| 第 2 节 — 导航结构 | Vue SPA 无侧边栏，MediaView.vue 自上而下布局 | 高 |
| 第 3 节 — UI | 大量新增功能未记载（背景、字体、文案、队列、历史） | 高 |
| 第 4 节 — 后端 API | 遗漏 14+ 个端点；`@jwt_required()` 认证未提及 | 高 |
| 第 5 节 — 视频处理 | 滤镜链复杂度远超描述；动态背景、文案浮层、logo 阴影/去白底均缺失 | 高 |
| 第 6 节 — AI 集成 | 缺少 DoubaoProvider 完整说明；KlingProvider 不存在；Provider 继承关系不准确 | 中 |
| 第 7 节 — FFmpeg 打包 | `_get_ffmpeg_path()` 逻辑已扩展 | 低 |
| 第 8 节 — Flask 线程 | 未提及 SQLite 持久化和 JWT 认证 | 中 |
| 第 9 节 — 文件清单 | 完全过时（原生 JS → Vue 3） | 高 |
| 第 10 节 — 实现顺序 | 阶段 1 布局重构不适用（无 index.html 侧边栏） | 低 |
| 第 11 节 — 验证方案 | 未覆盖新增功能（字体、历史、队列等）的测试路径 | 低 |

---

### A.11 建议后续行动

1. **更新设计文档**：按本审计附录修正第 2-11 节，使其与代码实现一致
2. **补充 API 参考文档**：为 20+ 个视频/媒体端点编写完整 API 文档（OpenAPI 格式）
3. **编写 AI Provider 集成指南**：重点说明豆包 Seedance（Ark SDK）和 Atlas Cloud 的接入步骤、免费额度、限制
4. **补充前端组件文档**：MediaView.vue 的组件树、stores、API 调用流程图
5. **决策记录**：确认 UI 默认值差异（seedance vs doubao 推荐）、分辨率选项差异（为何去掉了横向 1080p/720p）
