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
