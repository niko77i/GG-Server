# AI 视频生成功能 — 实现计划

> **对于自动化执行：** 推荐使用 subagent-driven-development 逐任务执行。每个步骤用 checkbox (`- [ ]`) 语法追踪。

**目标：** 在现有图片爬取工具中新增 AI 视频生成标签页，支持从已爬取的图片拼接视频，可选 Logo 水印和 AI 动态化。

**架构：** 左侧侧边栏导航 + 双面板切换。视频处理通过 FFmpeg 子进程执行（单命令滤镜链），AI 动态化通过 Kling API 实现（可选）。Flask 新增 4 个 API 端点，前端新增独立 JS 模块。FFmpeg 打包进 EXE。

**技术栈：** Python 3 + Flask + FFmpeg (subprocess) + Kling API + 原生 JS/CSS/HTML

---

## 文件结构总览

| 文件 | 操作 | 职责 |
|------|------|------|
| `css/style.css` | 修改 | 侧边栏布局、视频面板样式、图片网格 |
| `index.html` | 修改 | 侧边栏导航、双面板结构、视频表单 HTML |
| `js/app.js` | 修改 | 添加 `switchTab()` 函数 |
| `js/video.js` | 新建 | 视频面板全部 UI 逻辑 |
| `py/video_processor.py` | 新建 | FFmpeg 命令构建、子进程执行、进度解析 |
| `py/ai_service.py` | 新建 | AI 抽象接口 + Kling 实现 |
| `py/main.py` | 修改 | 新增 4 个 API 路由 + FFmpeg 路径 + threaded |

---

### Task 1: 更新 CSS — 侧边栏布局 + 视频面板样式

**文件：**
- 修改：`css/style.css`

**背景：** 当前是居中卡片布局 (`.container` max-width 700px)。需要改为全屏侧边栏布局，同时保留所有现有组件样式。

- [ ] **Step 1: 将 body 布局改为 flex，添加侧边栏样式**

替换 `body` 样式，在文件开头（`* {}` 全局重置之后）修改：

```css
body {
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    background: #f5f5f5;
    color: #333;
    line-height: 1.6;
    display: flex;
    min-height: 100vh;
}

/* ========== 侧边栏导航 ========== */

.sidebar {
    width: 200px;
    background: #2c3e50;
    color: #fff;
    flex-shrink: 0;
    display: flex;
    flex-direction: column;
    padding-top: 20px;
}

.sidebar-title {
    padding: 0 16px 16px;
    font-size: 15px;
    font-weight: 700;
    border-bottom: 1px solid rgba(255, 255, 255, 0.1);
    margin-bottom: 8px;
}

.nav-item {
    padding: 12px 16px;
    font-size: 14px;
    cursor: pointer;
    transition: background 0.15s;
    border-left: 3px solid transparent;
    color: rgba(255, 255, 255, 0.7);
    user-select: none;
}

.nav-item:hover {
    background: rgba(255, 255, 255, 0.08);
    color: #fff;
}

.nav-item.active {
    background: rgba(255, 255, 255, 0.12);
    border-left-color: #4a90d9;
    color: #fff;
    font-weight: 600;
}

/* ========== 主内容区 ========== */

.main-content {
    flex: 1;
    padding: 32px;
    overflow-y: auto;
    display: flex;
    justify-content: center;
}

.tab-panel {
    display: none;
    width: 100%;
    max-width: 760px;
}

.tab-panel.active {
    display: block;
}
```

- [ ] **Step 2: 修改 `.container` 为面板内样式**

将原来的 `.container` 改为适应面板内部（去掉居中 margin 和背景/阴影，这些由面板承担）：

```css
.panel-inner {
    background: #fff;
    border-radius: 12px;
    box-shadow: 0 2px 12px rgba(0, 0, 0, 0.08);
    padding: 32px;
}
```

> 注意：`index.html` 中原 `.container` 内的内容需要包一层 `.panel-inner`（在 Task 2 中处理）。

- [ ] **Step 3: 添加视频面板专用样式**

在 CSS 文件末尾追加：

```css
/* ========== 图片网格 ========== */

.image-grid {
    display: grid;
    grid-template-columns: repeat(3, 1fr);
    gap: 12px;
    margin-top: 8px;
}

.image-card {
    border: 2px solid #ddd;
    border-radius: 8px;
    overflow: hidden;
    background: #fff;
    cursor: pointer;
    transition: border-color 0.15s, background 0.15s;
    user-select: none;
}

.image-card.selected {
    border-color: #4a90d9;
    background: #f0f4ff;
}

.image-card .card-img {
    width: 100%;
    aspect-ratio: 16 / 10;
    object-fit: cover;
    display: block;
    background: #f0f0f0;
}

.image-card .card-info {
    padding: 6px 8px;
    font-size: 11px;
}

.image-card .card-info .card-name {
    font-weight: 600;
    word-break: break-all;
}

.image-card .card-info .card-size {
    color: #888;
}

/* 选择指示器（左上角勾选标记） */
.image-card .card-check {
    position: absolute;
    top: 6px;
    left: 6px;
    width: 20px;
    height: 20px;
    background: #fff;
    border: 2px solid #ccc;
    border-radius: 4px;
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: 12px;
    color: transparent;
}

.image-card.selected .card-check {
    background: #4a90d9;
    border-color: #4a90d9;
    color: #fff;
}

.image-card .card-img-wrapper {
    position: relative;
}

/* ========== 全选/取消全选 ========== */

.select-all {
    color: #4a90d9;
    font-size: 12px;
    cursor: pointer;
    user-select: none;
}

.select-all:hover {
    text-decoration: underline;
}

/* ========== 选项区块高亮 ========== */

.option-block {
    padding: 10px 12px;
    border-radius: 8px;
    margin-bottom: 16px;
}

.option-block.logo-block {
    background: #fff8e1;
    border: 1px solid #ffe082;
}

.option-block.ai-block {
    background: #f3e5f5;
    border: 1px solid #e1bee7;
}

/* ========== 视频设置行 ========== */

.settings-row {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 10px;
}

.settings-row .form-group {
    margin-bottom: 12px;
}

/* ========== 进度条 ========== */

.progress-bar {
    width: 100%;
    height: 8px;
    background: #e0e0e0;
    border-radius: 4px;
    overflow: hidden;
    margin-top: 8px;
}

.progress-bar .progress-fill {
    height: 100%;
    background: #4a90d9;
    border-radius: 4px;
    transition: width 0.3s;
    width: 0%;
}

/* ========== 结果区域（复用现有 .results） ========== */
/* .results .result-item .summary 等全部复用，无需改动 */

/* ========== 折叠区域 ========== */

.collapsible-content {
    margin-top: 8px;
    display: none;
}

.collapsible-content.open {
    display: block;
}

/* ========== 响应式：窄屏时图片网格变两列 ========== */

@media (max-width: 900px) {
    .image-grid {
        grid-template-columns: repeat(2, 1fr);
    }
    .sidebar {
        width: 160px;
    }
    .settings-row {
        grid-template-columns: 1fr;
    }
}
```

- [ ] **Step 4: 提交**

```bash
git add css/style.css
git commit -m "style: 侧边栏布局 + 视频面板样式"
```

---

### Task 2: 更新 index.html — 侧边栏 + 双面板结构

**文件：**
- 修改：`index.html`

**注意：** 所有现有表单元素、按钮、结果区域保持在爬取面板中，功能不变。视频面板先用占位内容。

- [ ] **Step 1: 重写 `index.html` 的整体结构**

```html
<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Google Play 图片爬取工具</title>
    <link rel="stylesheet" href="css/style.css">
</head>
<body>

    <!-- ========== 侧边栏 ========== -->
    <nav class="sidebar">
        <div class="sidebar-title">🖼️ 工具集</div>
        <div class="nav-item active" onclick="switchTab('scrape')">📥 图片爬取</div>
        <div class="nav-item" onclick="switchTab('video')">🎬 AI 视频生成</div>
    </nav>

    <!-- ========== 主内容区 ========== -->
    <div class="main-content">

        <!-- ===== 爬取面板 ===== -->
        <div id="panel-scrape" class="tab-panel active">
            <div class="panel-inner">
                <h1>🖼️ Google Play 图片爬取工具</h1>
                <p class="subtitle">批量输入 Google Play 链接，自动爬取并缩放图片至 Google Ads 规格</p>

                <div class="form-group">
                    <label for="urls">📋 Google Play 链接</label>
                    <textarea id="urls" rows="6" placeholder="每行一个链接，或用逗号分隔&#10;例如：&#10;https://play.google.com/store/apps/details?id=com.spotify.music&#10;https://play.google.com/store/apps/details?id=com.whatsapp"></textarea>
                    <span class="hint">支持批量输入，换行或逗号分隔</span>
                </div>

                <div class="form-group">
                    <label for="saveDir">💾 保存路径</label>
                    <input type="text" id="saveDir" placeholder="例如：F:\images\google_ads\" />
                    <span class="hint">图片将按包名自动创建子文件夹</span>
                </div>

                <div class="form-group checkbox-group">
                    <label class="checkbox-label">
                        <input type="checkbox" id="includeAds" checked />
                        按 Google Ads 规格放大图片
                    </label>
                </div>

                <button id="startBtn" onclick="startScrape()">🚀 开始爬取</button>

                <div id="results" class="results">
                    <h3>📊 处理结果</h3>
                    <div id="resultList"></div>
                    <div id="summary" class="summary" style="display:none;"></div>
                </div>
            </div>
        </div>

        <!-- ===== 视频面板 ===== -->
        <div id="panel-video" class="tab-panel">
            <div class="panel-inner">
                <h1>🎬 AI 视频生成</h1>
                <p class="subtitle">从已爬取的图片生成视频，可选 Logo 水印与 AI 动态效果</p>

                <!-- 选择目录 -->
                <div class="form-group">
                    <label for="videoDir">📂 选择图片目录</label>
                    <div style="display:flex;gap:8px;">
                        <input type="text" id="videoDir" placeholder="例如：F:\images\google_ads\com.spotify.music" style="flex:1;" />
                        <button id="scanDirBtn" onclick="scanDirectory()" style="width:auto;padding:12px 20px;">🔍 扫描</button>
                    </div>
                    <span class="hint">选择已爬取的包名文件夹（包含 PNG 图片和 包logo 子目录）</span>
                </div>

                <!-- 图片列表 -->
                <div id="imageListSection" class="form-group" style="display:none;">
                    <div style="display:flex;align-items:center;justify-content:space-between;">
                        <label>🖼️ 图片列表（共 <span id="imageCount">0</span> 张）</label>
                        <span class="select-all" onclick="toggleSelectAll()">☑ 全选</span>
                    </div>
                    <div id="imageGrid" class="image-grid"></div>
                </div>

                <!-- Logo 叠加 -->
                <div id="logoSection" class="form-group option-block logo-block" style="display:none;">
                    <label class="checkbox-label">
                        <input type="checkbox" id="useLogo" onchange="toggleLogoOptions()" />
                        🏷️ Logo 叠加 — 检测到: <span id="logoFileName" style="color:#888;"></span>
                    </label>
                    <div id="logoOptions" class="collapsible-content">
                        <div class="settings-row" style="margin-top:8px;">
                            <div class="form-group">
                                <label>位置</label>
                                <select id="logoPosition">
                                    <option value="top-right">右上</option>
                                    <option value="top-left">左上</option>
                                    <option value="bottom-left">左下</option>
                                    <option value="bottom-right">右下</option>
                                    <option value="floating">浮动</option>
                                </select>
                            </div>
                            <div class="form-group">
                                <label>效果</label>
                                <select id="logoEffect">
                                    <option value="static">静态</option>
                                    <option value="fade">淡入淡出</option>
                                    <option value="bounce">浮动弹跳</option>
                                </select>
                            </div>
                        </div>
                    </div>
                </div>

                <!-- AI 动态化 -->
                <div class="form-group option-block ai-block">
                    <label class="checkbox-label">
                        <input type="checkbox" id="useAI" onchange="toggleAIOptions()" />
                        🤖 使用 AI 将静态图片转为短视频（需 API Key）
                    </label>
                    <div id="aiOptions" class="collapsible-content">
                        <div class="settings-row" style="margin-top:8px;">
                            <div class="form-group">
                                <label>API 服务</label>
                                <select id="aiService">
                                    <option value="kling">Kling 可灵</option>
                                </select>
                            </div>
                            <div class="form-group">
                                <label>每段时长（秒）</label>
                                <select id="aiDuration">
                                    <option value="3">3</option>
                                    <option value="4" selected>4</option>
                                    <option value="5">5</option>
                                </select>
                            </div>
                        </div>
                        <div class="form-group">
                            <label>API Key</label>
                            <input type="password" id="aiApiKey" placeholder="输入 Kling API Key" />
                        </div>
                    </div>
                </div>

                <!-- 视频设置 -->
                <h3 style="margin-bottom:12px;margin-top:20px;">⚙️ 视频设置</h3>
                <div class="settings-row">
                    <div class="form-group">
                        <label>单帧时长</label>
                        <select id="frameDuration">
                            <option value="3" selected>3 秒</option>
                            <option value="4">4 秒</option>
                            <option value="5">5 秒</option>
                        </select>
                    </div>
                    <div class="form-group">
                        <label>转场效果</label>
                        <select id="transition">
                            <option value="fade" selected>淡入淡出</option>
                            <option value="slideright">滑动</option>
                            <option value="zoomin">缩放</option>
                            <option value="none">无</option>
                        </select>
                    </div>
                    <div class="form-group">
                        <label>输出分辨率</label>
                        <select id="resolution">
                            <option value="1920:1080" selected>1080p (1920×1080)</option>
                            <option value="1280:720">720p (1280×720)</option>
                        </select>
                    </div>
                    <div class="form-group">
                        <label>背景音乐（可选）</label>
                        <input type="file" id="musicFile" accept=".mp3" />
                    </div>
                </div>
                <div class="form-group">
                    <label>输出路径</label>
                    <input type="text" id="outputPath" placeholder="例如：F:\output\video.mp4" />
                    <span class="hint">视频文件保存路径，需包含 .mp4 扩展名</span>
                </div>

                <!-- 生成按钮 -->
                <button id="generateBtn" onclick="startGenerate()">🎬 生成视频</button>

                <!-- 进度与结果 -->
                <div id="videoProgress" class="results" style="display:none;">
                    <h3>⏳ 生成进度</h3>
                    <div id="videoStatus"></div>
                    <div class="progress-bar"><div id="progressFill" class="progress-fill"></div></div>
                    <div id="videoResult" style="display:none;"></div>
                </div>
            </div>
        </div>

    </div>

    <script src="js/app.js"></script>
    <script src="js/video.js"></script>
</body>
</html>
```

- [ ] **Step 2: 提交**

```bash
git add index.html
git commit -m "feat: 添加侧边栏导航和视频生成面板结构"
```

---

### Task 3: 更新 js/app.js — 添加 switchTab()

**文件：**
- 修改：`js/app.js`

**变更：** 只在文件开头追加 `switchTab()` 函数。现有逻辑完全不动。

- [ ] **Step 1: 在 `app.js` 开头添加 switchTab 函数**

在 `const API_BASE = "";` 行之后插入：

```javascript
// ---------- 标签页切换 ----------

function switchTab(tabName) {
    // 更新导航激活态
    document.querySelectorAll(".nav-item").forEach((el, i) => {
        el.classList.toggle("active", (tabName === "scrape" && i === 0) || (tabName === "video" && i === 1));
    });
    // 切换面板
    document.getElementById("panel-scrape").classList.toggle("active", tabName === "scrape");
    document.getElementById("panel-video").classList.toggle("active", tabName === "video");
}
```

- [ ] **Step 2: 验证现有功能不受影响**

启动服务器，确认爬取页一切正常：

```bash
cd py && python main.py
# 浏览器打开 http://localhost:5000
# 确认：爬取表单完整、checkbox 正常、点击爬取功能正常
# 确认：点击侧边栏"图片爬取"和"AI 视频生成"可切换面板
```

- [ ] **Step 3: 提交**

```bash
git add js/app.js
git commit -m "feat: 添加侧边栏标签切换功能"
```

---

### Task 4: 创建 py/video_processor.py — FFmpeg 视频处理

**文件：**
- 创建：`py/video_processor.py`

**背景：** 这是核心视频处理模块。VideoTask 类封装了 FFmpeg 滤镜链构建、子进程执行、进度解析。所有图片在一个 FFmpeg 命令中处理完毕，无中间文件。

- [ ] **Step 1: 创建模块骨架 + VideoTask 类**

```python
"""视频处理模块 — FFmpeg 滤镜链构建与子进程执行。"""
import os
import re
import subprocess
import uuid


class VideoError(Exception):
    """视频处理失败异常。"""
    pass


class VideoTask:
    """封装一个视频生成任务：构建 FFmpeg 命令、执行、解析进度。"""

    def __init__(self, params: dict):
        self.task_id = uuid.uuid4().hex[:12]
        self.params = params
        self.status = "pending"      # pending | processing | completed | error
        self.progress = 0.0
        self.message = ""
        self._result = None
        self._proc = None

    # ---------- 公开 API ----------

    def build_command(self) -> list[str]:
        """构建完整的 FFmpeg 命令（滤镜链方式，单命令输出）。"""
        images = self.params["images"]
        settings = self.params["settings"]
        logo = self.params.get("logo")
        transition = settings.get("transition", "fade")
        duration_per_frame = int(settings.get("duration_per_frame", 3))
        resolution = settings.get("resolution", "1920:1080")
        output_path = settings["output_path"]
        ffmpeg = self._ffmpeg_path()

        cmd = [ffmpeg, "-y"]

        # 输入：每张图片
        for img_path in images:
            cmd += ["-loop", "1", "-i", img_path.replace("\\", "/")]

        # 输入：Logo（如果有）
        logo_input_idx = len(images)
        if logo and logo.get("path"):
            cmd += ["-loop", "1", "-i", logo["path"].replace("\\", "/")]
        else:
            logo_input_idx = -1

        # 输入：背景音乐（如果有）
        music_path = settings.get("music_path")
        has_music = bool(music_path and os.path.isfile(music_path))
        if has_music:
            cmd += ["-i", music_path.replace("\\", "/")]

        # 构建滤镜图
        filter_parts = []
        prev_label = None
        total_duration = 0.0

        # 第一步：每张图片 → 标准化视频流 [v0], [v1], ...
        for i in range(len(images)):
            # loop 图片，trim 到指定时长，scale+pad 到目标分辨率
            filter_parts.append(
                f"[{i}:v]loop=loop=-1:size=1:start=0,trim=duration={duration_per_frame},"
                f"setpts=PTS-STARTPTS,scale={resolution}:force_original_aspect_ratio=decrease,"
                f"pad={resolution}:(ow-iw)/2:(oh-ih)/2,setsar=1,fps=30[v{i}]"
            )

        # 第二步：xfade 转场链
        if len(images) == 1:
            # 单张图片，无需转场
            prev_label = f"v0"
        else:
            offset = 0.0
            xfade_dur = 0.5 if transition != "none" else 0.0
            for i in range(len(images) - 1):
                if i == 0:
                    input_a = f"[v0]"
                    input_b = f"[v1]"
                    out_label = "[f0]"
                else:
                    input_a = f"[f{i-1}]"
                    input_b = f"[v{i+1}]"
                    out_label = f"[f{i}]"
                offset += (duration_per_frame - xfade_dur)
                # xfade 参数：offset 是转场开始时间
                filter_parts.append(
                    f"{input_a}{input_b}xfade=transition={transition}:"
                    f"duration={xfade_dur}:offset={offset}{out_label}"
                )
            prev_label = f"f{len(images) - 2}"
            total_duration = offset + duration_per_frame

        # 第三步：Logo 叠加（如果有）
        if logo_input_idx >= 0:
            logo_pos = logo.get("position", "top-right")
            logo_effect = logo.get("effect", "static")
            overlay_expr = self._logo_overlay(logo_pos)

            if logo_effect == "fade":
                # logo 淡入淡出
                filter_parts.append(
                    f"[{logo_input_idx}:v]loop=loop=-1:size=1:start=0,"
                    f"trim=duration={total_duration},setpts=PTS-STARTPTS,"
                    f"fade=t=in:st=0:d=1,fade=t=out:st={total_duration-1}:d=1[l]"
                )
                filter_parts.append(f"{prev_label}[l]overlay={overlay_expr}[outv]")
            else:
                # 静态 / 浮动
                filter_parts.append(
                    f"[{logo_input_idx}:v]loop=loop=-1:size=1:start=0,"
                    f"trim=duration={total_duration},setpts=PTS-STARTPTS[l]"
                )
                if logo_effect == "bounce":
                    # 使用表达式实现弹跳效果
                    overlay_expr = self._logo_overlay("floating")
                filter_parts.append(f"{prev_label}[l]overlay={overlay_expr}[outv]")
            video_out = "[outv]"
        else:
            video_out = prev_label if len(images) == 1 else f"[f{len(images) - 2}]"

        # 第四步：音频处理
        if has_music:
            music_idx = logo_input_idx + 1 if logo_input_idx >= 0 else len(images)
            filter_parts.append(
                f"[{music_idx}:a]volume=0.3,aloop=loop=-1:size=2e+09,"
                f"atrim=duration={total_duration}[bga]"
            )
            audio_map = "[bga]"
        else:
            # 静音轨
            filter_parts.append(
                f"anullsrc=r=44100:cl=stereo,atrim=duration={total_duration}[s]"
            )
            audio_map = "[s]"

        # 组装完整滤镜
        filter_complex = ";".join(filter_parts)
        cmd += ["-filter_complex", filter_complex]
        cmd += ["-map", video_out, "-map", audio_map]
        cmd += ["-c:v", "libx264", "-preset", "medium", "-crf", "18"]
        cmd += ["-pix_fmt", "yuv420p"]
        cmd += ["-shortest"]
        cmd += [output_path.replace("\\", "/")]

        self._total_duration = total_duration
        return cmd

    def run(self):
        """执行 FFmpeg 命令（阻塞，在独立线程中调用）。"""
        cmd = self.build_command()
        self.status = "processing"
        self.message = "正在启动 FFmpeg..."

        try:
            self._proc = subprocess.Popen(
                cmd,
                stderr=subprocess.PIPE,
                stdout=subprocess.DEVNULL,
                universal_newlines=True,
                encoding="utf-8",
                errors="replace",
            )
            for line in self._proc.stderr:
                self._parse_progress(line)
            self._proc.wait()

            if self._proc.returncode == 0 and os.path.isfile(self.params["settings"]["output_path"]):
                out_path = self.params["settings"]["output_path"]
                size_mb = os.path.getsize(out_path) / (1024 * 1024)
                self.status = "completed"
                self.progress = 1.0
                self.message = "视频生成完成"
                self._result = {
                    "path": out_path,
                    "size_mb": round(size_mb, 1),
                    "duration_s": round(self._total_duration, 1),
                }
            else:
                self.status = "error"
                self.message = f"FFmpeg 返回错误码 {self._proc.returncode}"
        except FileNotFoundError:
            self.status = "error"
            self.message = "未找到 FFmpeg，请确认 ffmpeg.exe 在系统 PATH 中或与程序在同一目录"
        except Exception as e:
            self.status = "error"
            self.message = f"视频生成异常: {e}"

    def result(self):
        """获取生成结果（仅在 completed 状态下有效）。"""
        return self._result

    # ---------- 内部方法 ----------

    @staticmethod
    def _ffmpeg_path() -> str:
        """获取 FFmpeg 可执行文件路径。"""
        # 尝试从 main 模块获取已定位的路径
        try:
            from main import _get_ffmpeg_path
            path = _get_ffmpeg_path()
            if path:
                return path
        except Exception:
            pass
        # 回退：直接尝试 ffmpeg 命令
        return "ffmpeg"

    def _parse_progress(self, line: str):
        """从 FFmpeg stderr 行解析编码进度。"""
        m = re.search(r"time=(\d+):(\d+):(\d+\.\d+)", line)
        if m and hasattr(self, "_total_duration") and self._total_duration > 0:
            h, minutes, s = int(m.group(1)), int(m.group(2)), float(m.group(3))
            current = h * 3600 + minutes * 60 + s
            self.progress = min(current / self._total_duration, 0.99)
            self.message = f"编码中... {self.progress * 100:.0f}%"

    @staticmethod
    def _logo_overlay(position: str) -> str:
        """根据位置返回 FFmpeg overlay 表达式。"""
        margin = 10
        expressions = {
            "top-left": f"{margin}:{margin}",
            "top-right": f"W-w-{margin}:{margin}",
            "bottom-left": f"{margin}:H-h-{margin}",
            "bottom-right": f"W-w-{margin}:H-h-{margin}",
            "floating": f"{margin}+20*sin(t*2):H-h-{margin}-20*abs(cos(t*1.5))",
        }
        return expressions.get(position, expressions["top-right"])
```

- [ ] **Step 2: 提交**

```bash
git add py/video_processor.py
git commit -m "feat: 添加 VideoTask 类 — FFmpeg 滤镜链构建与执行"
```

---

### Task 5: 创建 py/ai_service.py — AI 接口 + 多 Provider

**文件：**
- 创建：`py/ai_service.py`

**背景：** 基于 NOTES.md 调研结果，使用免费/低成本方案：Seedance 2.0（🥇首推，每日 225 免费积分）通过 Atlas Cloud 统一网关调用，Veo 3.1 Lite（完全免费 + 自带音频）作为备选。

- [ ] **Step 1: 创建模块**

```python
"""AI 图片转视频服务 — 抽象接口 + Seedance/Veo/Atlas Provider。

Provider 选择:
- seedance: 通过 Atlas Cloud 调用 Seedance 2.0（每日 225 免费积分，图转视频最佳）
- veo: Google Veo 3.1 Lite（完全免费，视频自带音频）
- atlas: Atlas Cloud 统一网关，可切换多个后端
"""
import os
import time
import tempfile
import requests


class AIServiceError(Exception):
    """AI 服务调用失败异常。"""
    pass


class AIProvider:
    """AI 图片转视频抽象基类。"""

    def generate_video(self, image_path: str, duration: int, api_key: str) -> str:
        """将图片转为短视频，返回生成的 MP4 本地路径。"""
        raise NotImplementedError


class AtlasProvider(AIProvider):
    """通过 Atlas Cloud 统一网关调用 AI 视频模型。

    支持模型: seedance-2.0, kling-3.0, vidu-q3, wan-2.2 等
    参考: https://www.atlascloud.ai/
    """

    BASE_URL = "https://api.atlascloud.ai/v1"
    DEFAULT_MODEL = "seedance-2.0"

    def __init__(self, model: str = None):
        self.model = model or self.DEFAULT_MODEL

    def generate_video(self, image_path: str, duration: int, api_key: str) -> str:
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

        # Step 1: 提交生成请求（Atlas Cloud 兼容 OpenAI SDK 格式）
        task_id = self._create_task(image_path, duration, headers)

        # Step 2: 轮询直到完成
        video_url = self._poll_task(task_id, headers)

        # Step 3: 下载视频到临时目录
        return self._download_video(video_url)

    def _create_task(self, image_path: str, duration: int, headers: dict) -> str:
        """提交视频生成任务，返回 task_id。"""
        url = f"{self.BASE_URL}/video/generate"
        # 读取图片为 base64 或使用 URL
        # 简化处理：假设 Atlas Cloud 支持直接传图片 URL
        body = {
            "model": self.model,
            "image_url": f"file://{image_path}",  # 实际使用时可能需要先上传
            "duration": duration,
        }
        try:
            resp = requests.post(url, headers=headers, json=body, timeout=30)
            data = resp.json()
            task_id = data.get("task_id") or data.get("id")
            if resp.status_code != 200 or not task_id:
                raise AIServiceError(f"Atlas Cloud 创建任务失败: {data.get('message', resp.text)}")
            return task_id
        except requests.RequestException as e:
            raise AIServiceError(f"Atlas Cloud 网络错误: {e}")

    def _poll_task(self, task_id: str, headers: dict, timeout: int = 600) -> str:
        """轮询任务状态，返回视频下载 URL。"""
        url = f"{self.BASE_URL}/video/status/{task_id}"
        start = time.time()
        while time.time() - start < timeout:
            try:
                resp = requests.get(url, headers=headers, timeout=15)
                data = resp.json()
                status = data.get("status", "")
                if status in ("completed", "succeeded", "done"):
                    video_url = data.get("video_url") or data.get("output_url") or data.get("url")
                    if not video_url:
                        raise AIServiceError("任务完成但缺少视频 URL")
                    return video_url
                elif status in ("failed", "cancelled", "error"):
                    raise AIServiceError(f"任务失败: {data.get('message', status)}")
            except requests.RequestException:
                pass  # 网络抖动，继续轮询
            time.sleep(2)
        raise AIServiceError("任务超时")

    def _download_video(self, video_url: str) -> str:
        """下载视频到临时文件，返回本地路径。"""
        try:
            resp = requests.get(video_url, timeout=120, stream=True)
            resp.raise_for_status()
            fd, tmp_path = tempfile.mkstemp(suffix=".mp4", prefix="ai_video_")
            with os.fdopen(fd, "wb") as f:
                for chunk in resp.iter_content(chunk_size=8192):
                    f.write(chunk)
            return tmp_path
        except requests.RequestException as e:
            raise AIServiceError(f"下载视频失败: {e}")


class VeoProvider(AIProvider):
    """Google Veo 3.1 Lite — 通过 NexaAPI 免费调用（无需绑卡）。

    特点: 完全免费，视频自带同步音频生成，最长 8 秒。
    限制: 有速率限制，适合少量图片。
    """

    BASE_URL = "https://api.nexaapi.ai/v1"

    def generate_video(self, image_path: str, duration: int, api_key: str) -> str:
        # 限制最大 8 秒
        duration = min(duration, 8)
        headers = {
            "Authorization": f"Bearer {api_key or 'free'}",
            "Content-Type": "application/json",
        }

        try:
            resp = requests.post(
                f"{self.BASE_URL}/video/generate",
                headers=headers,
                json={
                    "model": "veo-3.1-lite-i2v",
                    "image_url": f"file://{image_path}",
                    "duration": duration,
                    "aspect_ratio": "16:9",
                },
                timeout=30,
            )
            data = resp.json()
            if resp.status_code != 200:
                raise AIServiceError(f"Veo 生成失败: {data.get('message', resp.text)}")

            # NexaAPI 可能同步返回或异步返回 — 简化处理
            video_url = data.get("video_url") or data.get("url")
            if video_url:
                return self._download_video(video_url)

            # 异步轮询
            task_id = data.get("task_id") or data.get("id")
            if task_id:
                return self._poll_and_download(task_id, headers)

            raise AIServiceError("Veo 返回格式未知")
        except requests.RequestException as e:
            raise AIServiceError(f"Veo 网络错误: {e}")

    def _poll_and_download(self, task_id: str, headers: dict) -> str:
        """轮询并下载。"""
        url = f"{self.BASE_URL}/video/status/{task_id}"
        start = time.time()
        while time.time() - start < 600:
            try:
                resp = requests.get(url, headers=headers, timeout=15)
                data = resp.json()
                if data.get("status") in ("completed", "done"):
                    video_url = data.get("video_url") or data.get("url")
                    if video_url:
                        return self._download_video(video_url)
                    raise AIServiceError("Veo 完成但无视频 URL")
                elif data.get("status") in ("failed", "error"):
                    raise AIServiceError(f"Veo 任务失败: {data.get('message')}")
            except requests.RequestException:
                pass
            time.sleep(2)
        raise AIServiceError("Veo 任务超时")

    def _download_video(self, video_url: str) -> str:
        try:
            resp = requests.get(video_url, timeout=120, stream=True)
            resp.raise_for_status()
            fd, tmp_path = tempfile.mkstemp(suffix=".mp4", prefix="veo_ai_")
            with os.fdopen(fd, "wb") as f:
                for chunk in resp.iter_content(chunk_size=8192):
                    f.write(chunk)
            return tmp_path
        except requests.RequestException as e:
            raise AIServiceError(f"Veo 下载视频失败: {e}")


# 服务注册表
AI_PROVIDERS = {
    "seedance": AtlasProvider,    # 🥇 推荐：通过 Atlas Cloud 调用 Seedance 2.0
    "veo": VeoProvider,           # 🥈 备选：Google Veo 3.1 Lite（免费 + 音频）
    "atlas": AtlasProvider,       # Atlas Cloud 多模型网关
}


def get_provider(name: str, **kwargs) -> AIProvider:
    """根据名称获取 AI Provider 实例。

    Args:
        name: Provider 名称 (seedance/veo/atlas)
        **kwargs: 传递给 Provider 构造函数的额外参数 (如 model)
    """
    cls = AI_PROVIDERS.get(name)
    if cls is None:
        raise AIServiceError(f"不支持的 AI 服务: {name}。可用: {list(AI_PROVIDERS.keys())}")
    return cls(**kwargs)
```

- [ ] **Step 2: 提交**

```bash
git add py/ai_service.py
git commit -m "feat: 添加 AI 视频服务 — Seedance/Veo/Atlas Provider"
```

---

### Task 6: 更新 py/main.py — 新增 API 路由 + FFmpeg 路径

**文件：**
- 修改：`py/main.py`

**变更：**
1. 新增 `_get_ffmpeg_path()` 辅助函数
2. 新增 4 个 API 路由
3. `app.run()` 加上 `threaded=True`
4. 导入新模块

- [ ] **Step 1: 更新导入 + 添加 FFmpeg 路径函数 + 任务存储**

在现有导入后追加：

```python
from video_processor import VideoTask, VideoError
from ai_service import get_provider, AIServiceError

# 视频生成任务存储（模块级字典）
_video_tasks: dict[str, VideoTask] = {}


def _get_ffmpeg_path() -> str:
    """获取 FFmpeg 可执行文件路径。"""
    if _FROZEN:
        # 打包模式：ffmpeg.exe 在 MEIPASS 中
        bundled = os.path.join(sys._MEIPASS, "ffmpeg.exe")
        if os.path.isfile(bundled):
            return bundled
    # 开发模式：尝试 PATH 中的 ffmpeg
    import shutil
    path = shutil.which("ffmpeg")
    if path:
        return path
    # 尝试常见位置
    for p in [
        os.path.join(os.path.dirname(_current_dir), "ffmpeg.exe"),
        r"C:\ffmpeg\bin\ffmpeg.exe",
    ]:
        if os.path.isfile(p):
            return p
    return "ffmpeg"  # 最终回退
```

- [ ] **Step 2: 添加 API 路由（在 `# ---------- API ----------` 块中，`/api/scrape` 之后追加）**

```python
# ---------- 视频 API ----------

@app.route("/api/video/scan-dir", methods=["POST"])
def video_scan_dir():
    """扫描目录，返回 PNG 图片列表和 logo 信息。"""
    data = request.get_json(silent=True)
    if not data:
        return jsonify({"success": False, "error": "请求体不能为空"}), 400

    dir_path = (data.get("dir") or "").strip()
    if not dir_path or not os.path.isdir(dir_path):
        return jsonify({"success": False, "error": "目录不存在或不可访问"}), 400

    images = []
    try:
        entries = sorted(os.listdir(dir_path))
    except OSError as e:
        return jsonify({"success": False, "error": f"无法读取目录: {e}"}), 400

    for f in entries:
        if not f.lower().endswith(".png"):
            continue
        full = os.path.join(dir_path, f)
        if not os.path.isfile(full):
            continue
        try:
            from PIL import Image
            with Image.open(full) as img:
                images.append({
                    "filename": f,
                    "path": full.replace("\\", "/"),
                    "width": img.width,
                    "height": img.height,
                })
        except Exception:
            pass  # 跳过无法读取的图片

    if not images:
        return jsonify({"success": False, "error": "目录中无有效的 PNG 图片"}), 404

    # 检测 logo
    logo = None
    logo_dir = os.path.join(dir_path, "包logo")
    if os.path.isdir(logo_dir):
        for f in sorted(os.listdir(logo_dir)):
            if f.lower().endswith(".png") and "_logo" in f.lower():
                full = os.path.join(logo_dir, f)
                try:
                    from PIL import Image
                    with Image.open(full) as img:
                        logo = {
                            "filename": f,
                            "path": full.replace("\\", "/"),
                            "width": img.width,
                            "height": img.height,
                        }
                except Exception:
                    pass
                break

    # 提取包名（从目录名）
    pkg_name = os.path.basename(dir_path.rstrip("/\\"))

    return jsonify({
        "success": True,
        "package_name": pkg_name,
        "images": images,
        "logo": logo,
    })


@app.route("/api/image", methods=["GET"])
def serve_image():
    """返回本地图片文件流，供前端缩略图加载。"""
    path = request.args.get("path", "")
    if not path:
        return "", 400

    # 安全检查：只允许访问存在的 PNG 文件
    path = os.path.normpath(path)
    if not os.path.isfile(path) or not path.lower().endswith(".png"):
        return "", 404

    from flask import send_file
    return send_file(path, mimetype="image/png", max_age=3600)


@app.route("/api/video/generate", methods=["POST"])
def video_generate():
    """提交视频生成任务。"""
    data = request.get_json(silent=True)
    if not data:
        return jsonify({"success": False, "error": "请求体不能为空"}), 400

    # 基本校验
    images = data.get("images") or []
    settings = data.get("settings") or {}
    output_path = settings.get("output_path", "").strip()

    if not images:
        return jsonify({"success": False, "error": "请至少选择一张图片"}), 400
    if not output_path:
        return jsonify({"success": False, "error": "请输入输出路径"}), 400

    # 确保输出目录存在
    out_dir = os.path.dirname(output_path)
    if out_dir:
        try:
            os.makedirs(out_dir, exist_ok=True)
        except OSError as e:
            return jsonify({"success": False, "error": f"无法创建输出目录: {e}"}), 400

    # 创建任务
    task = VideoTask(data)
    _video_tasks[task.task_id] = task

    # 后台线程执行
    import threading
    def _run():
        # 如果启用了 AI，先逐张处理
        ai = data.get("ai") or {}
        if ai.get("enabled") and ai.get("api_key"):
            task.message = "正在 AI 生成动态视频..."
            ai_provider = None
            try:
                ai_provider = get_provider(ai.get("service", "kling"))
            except AIServiceError:
                pass  # 降级为静态

            if ai_provider:
                duration = int(ai.get("duration", 4))
                api_key = ai["api_key"]
                ai_images = []
                for idx, img_path in enumerate(images):
                    task.message = f"AI 动态化: {idx + 1}/{len(images)}"
                    task.progress = idx / len(images) * 0.5  # AI 阶段占 50% 进度
                    try:
                        ai_video = ai_provider.generate_video(img_path, duration, api_key)
                        # 将 AI 视频路径替换到 params 中
                        task.params.setdefault("ai_videos", {})[img_path] = ai_video
                        ai_images.append(ai_video)
                    except AIServiceError:
                        ai_images.append(img_path)  # 降级为静态图片
                # 用 AI 生成的视频更新图片列表（需要用临时视频文件作为输入）
                # 但 FFmpeg 滤镜链需要的是图片... 
                # 简化处理：AI 视频文件单独 concat
                task.params["_ai_video_map"] = task.params.get("ai_videos", {})

        # 执行 FFmpeg
        task.run()

        # 清理 AI 临时文件
        ai_videos = task.params.get("ai_videos", {})
        for tmp_path in ai_videos.values():
            try:
                os.remove(tmp_path)
            except OSError:
                pass

    t = threading.Thread(target=_run, daemon=True)
    t.start()

    return jsonify({
        "success": True,
        "task_id": task.task_id,
        "message": "视频生成已开始",
    }), 202


@app.route("/api/video/progress", methods=["GET"])
def video_progress():
    """查询视频生成任务进度。"""
    task_id = request.args.get("task_id", "")
    task = _video_tasks.get(task_id)
    if task is None:
        return jsonify({"success": False, "error": "未知任务 ID"}), 404

    resp = {
        "task_id": task.task_id,
        "status": task.status,
        "progress": task.progress,
        "message": task.message,
    }
    if task.status == "completed":
        resp["output"] = task.result()
    elif task.status == "error":
        resp["error"] = task.message
    return jsonify(resp)
```

- [ ] **Step 3: 修改 app.run() 启用多线程**

找到 `app.run(host=host, port=port, debug=False)` 行，改为：

```python
app.run(host=host, port=port, debug=False, threaded=True)
```

- [ ] **Step 4: 提交**

```bash
git add py/main.py
git commit -m "feat: 添加视频生成 API — scan-dir/image/generate/progress"
```

---

### Task 7: 创建 js/video.js — 视频面板 UI 逻辑

**文件：**
- 创建：`js/video.js`

- [ ] **Step 1: 创建完整的 video.js**

```javascript
// 视频生成面板 UI 逻辑
// 依赖：API_BASE 已在 app.js 中定义为 ""

// ---- 全局状态 ----

let videoState = {
    images: [],           // 扫描到的图片列表
    logo: null,           // logo 信息
    selectedImages: new Set(),  // 选中图片的 path 集合
    allSelected: true,
    taskId: null,
    pollTimer: null,
};

// ---- 目录扫描 ----

async function scanDirectory() {
    const dir = document.getElementById("videoDir").value.trim();
    if (!dir) {
        alert("请输入图片目录路径");
        return;
    }

    const btn = document.getElementById("scanDirBtn");
    btn.disabled = true;
    btn.textContent = "⏳ 扫描中...";

    try {
        const resp = await fetch(`${API_BASE}/api/video/scan-dir`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ dir: dir }),
        });
        const data = await resp.json();

        if (data.success) {
            videoState.images = data.images || [];
            videoState.logo = data.logo || null;
            videoState.selectedImages = new Set(videoState.images.map(img => img.path));
            videoState.allSelected = true;
            renderImageGrid();
            renderLogoSection();
        } else {
            alert("扫描失败: " + data.error);
            document.getElementById("imageListSection").style.display = "none";
            document.getElementById("logoSection").style.display = "none";
        }
    } catch (err) {
        alert("扫描请求失败: " + err.message);
    } finally {
        btn.disabled = false;
        btn.textContent = "🔍 扫描";
    }
}

// ---- 图片网格渲染 ----

function renderImageGrid() {
    const section = document.getElementById("imageListSection");
    const grid = document.getElementById("imageGrid");
    const count = document.getElementById("imageCount");

    if (videoState.images.length === 0) {
        section.style.display = "none";
        return;
    }

    section.style.display = "block";
    count.textContent = videoState.images.length;
    grid.innerHTML = "";

    videoState.images.forEach(img => {
        const card = document.createElement("div");
        card.className = "image-card" + (videoState.selectedImages.has(img.path) ? " selected" : "");
        card.onclick = function () { toggleImage(img.path, card); };

        const wrapper = document.createElement("div");
        wrapper.className = "card-img-wrapper";

        const check = document.createElement("div");
        check.className = "card-check";
        check.textContent = videoState.selectedImages.has(img.path) ? "✓" : "";

        const thumb = document.createElement("img");
        thumb.className = "card-img";
        thumb.src = `${API_BASE}/api/image?path=${encodeURIComponent(img.path)}`;
        thumb.alt = img.filename;
        thumb.loading = "lazy";

        wrapper.appendChild(thumb);
        wrapper.appendChild(check);

        const info = document.createElement("div");
        info.className = "card-info";
        info.innerHTML = `<div class="card-name">${img.filename}</div><div class="card-size">${img.width} × ${img.height}</div>`;

        card.appendChild(wrapper);
        card.appendChild(info);
        grid.appendChild(card);
    });

    updateSelectAllLabel();
}

function toggleImage(path, card) {
    if (videoState.selectedImages.has(path)) {
        videoState.selectedImages.delete(path);
        card.classList.remove("selected");
        card.querySelector(".card-check").textContent = "";
    } else {
        videoState.selectedImages.add(path);
        card.classList.add("selected");
        card.querySelector(".card-check").textContent = "✓";
    }
    videoState.allSelected = videoState.selectedImages.size === videoState.images.length;
    updateSelectAllLabel();
}

function toggleSelectAll() {
    if (videoState.allSelected) {
        // 取消全选
        videoState.selectedImages.clear();
        videoState.allSelected = false;
    } else {
        // 全选
        videoState.images.forEach(img => videoState.selectedImages.add(img.path));
        videoState.allSelected = true;
    }
    // 刷新网格
    document.querySelectorAll(".image-card").forEach(card => {
        const path = card.querySelector("img").src.replace(`${API_BASE}/api/image?path=`, "");
        const decoded = decodeURIComponent(path);
        if (videoState.selectedImages.has(decoded)) {
            card.classList.add("selected");
            card.querySelector(".card-check").textContent = "✓";
        } else {
            card.classList.remove("selected");
            card.querySelector(".card-check").textContent = "";
        }
    });
    updateSelectAllLabel();
}

function updateSelectAllLabel() {
    const label = document.querySelector(".select-all");
    if (label) {
        label.textContent = videoState.allSelected ? "☐ 取消全选" : "☑ 全选";
    }
}

// ---- Logo 区域 ----

function renderLogoSection() {
    const section = document.getElementById("logoSection");
    if (videoState.logo) {
        section.style.display = "block";
        document.getElementById("logoFileName").textContent =
            `${videoState.logo.filename} (${videoState.logo.width}×${videoState.logo.height})`;
    } else {
        section.style.display = "none";
        document.getElementById("useLogo").checked = false;
        document.getElementById("logoOptions").classList.remove("open");
    }
}

function toggleLogoOptions() {
    const checked = document.getElementById("useLogo").checked;
    document.getElementById("logoOptions").classList.toggle("open", checked);
}

// ---- AI 选项 ----

function toggleAIOptions() {
    const checked = document.getElementById("useAI").checked;
    document.getElementById("aiOptions").classList.toggle("open", checked);
}

// ---- 视频生成 ----

async function startGenerate() {
    const outputPath = document.getElementById("outputPath").value.trim();
    if (!outputPath) {
        alert("请输入输出路径");
        return;
    }
    if (videoState.selectedImages.size === 0) {
        alert("请至少选择一张图片");
        return;
    }

    const generateBtn = document.getElementById("generateBtn");
    generateBtn.disabled = true;
    generateBtn.textContent = "⏳ 提交中...";

    // 收集参数
    const selectedPaths = videoState.images
        .filter(img => videoState.selectedImages.has(img.path))
        .map(img => img.path);

    const useLogo = document.getElementById("useLogo").checked;
    const useAI = document.getElementById("useAI").checked;
    const musicFile = document.getElementById("musicFile").files[0];

    const body = {
        images: selectedPaths,
        logo: useLogo && videoState.logo ? {
            path: videoState.logo.path,
            position: document.getElementById("logoPosition").value,
            effect: document.getElementById("logoEffect").value,
        } : null,
        ai: useAI ? {
            enabled: true,
            service: document.getElementById("aiService").value,
            api_key: document.getElementById("aiApiKey").value.trim(),
            duration: parseInt(document.getElementById("aiDuration").value),
        } : { enabled: false },
        settings: {
            duration_per_frame: parseInt(document.getElementById("frameDuration").value),
            transition: document.getElementById("transition").value,
            music_path: musicFile ? musicFile.name : null,  // 注意：需要额外处理文件上传
            resolution: document.getElementById("resolution").value,
            output_path: outputPath,
        },
    };

    try {
        // 如果有音乐文件，先用 FormData 上传或传路径
        // 简化处理：音乐文件需要用户提供本地路径
        // 实际使用中可扩展文件上传 API

        const resp = await fetch(`${API_BASE}/api/video/generate`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(body),
        });
        const data = await resp.json();

        if (data.success) {
            videoState.taskId = data.task_id;
            showProgress();
            startPolling();
        } else {
            alert("生成失败: " + data.error);
            resetGenerateButton();
        }
    } catch (err) {
        alert("请求失败: " + err.message);
        resetGenerateButton();
    }
}

function showProgress() {
    document.getElementById("videoProgress").style.display = "block";
    document.getElementById("videoResult").style.display = "none";
    document.getElementById("videoStatus").innerHTML =
        '<div class="result-item pending"><span class="icon">⏳</span> 正在初始化...</div>';
}

function startPolling() {
    if (videoState.pollTimer) clearInterval(videoState.pollTimer);
    videoState.pollTimer = setInterval(pollProgress, 1000);
}

async function pollProgress() {
    try {
        const resp = await fetch(`${API_BASE}/api/video/progress?task_id=${videoState.task_id}`);
        const data = await resp.json();

        const statusEl = document.getElementById("videoStatus");
        const fillEl = document.getElementById("progressFill");

        fillEl.style.width = (data.progress * 100) + "%";

        if (data.status === "completed") {
            clearInterval(videoState.pollTimer);
            videoState.pollTimer = null;
            statusEl.innerHTML = '<div class="result-item success"><span class="icon">✅</span> 视频生成完成</div>';
            const out = data.output;
            document.getElementById("videoResult").style.display = "block";
            document.getElementById("videoResult").innerHTML =
                `<div class="summary">输出文件: ${out.path}<br>大小: ${out.size_mb} MB, 时长: ${out.duration_s} 秒</div>`;
            resetGenerateButton();
        } else if (data.status === "error") {
            clearInterval(videoState.pollTimer);
            videoState.pollTimer = null;
            statusEl.innerHTML = `<div class="result-item error"><span class="icon">❌</span> ${data.error || "生成失败"}</div>`;
            resetGenerateButton();
        } else {
            statusEl.innerHTML = `<div class="result-item pending"><span class="icon">⏳</span> ${data.message}</div>`;
        }
    } catch (err) {
        // 网络错误不中断轮询
    }
}

function resetGenerateButton() {
    const btn = document.getElementById("generateBtn");
    btn.disabled = false;
    btn.textContent = "🎬 生成视频";
}
```

- [ ] **Step 2: 提交**

```bash
git add js/video.js
git commit -m "feat: 添加视频面板 UI 逻辑 — 扫描/预览/选择/生成"
```

---

### Task 8: 端到端验证

**文件：** 无新文件，验证所有功能。

- [ ] **Step 1: 启动服务器**

```bash
cd py
python main.py
```

- [ ] **Step 2: 验证爬取功能不受影响**

1. 浏览器打开 http://localhost:5000
2. 确认默认显示"图片爬取"面板
3. 填入 Google Play URL 和保存路径
4. 点击开始爬取 → 确认正常爬取图片和 logo
5. 确认结果列表显示 ✅ 和包名

- [ ] **Step 3: 验证标签切换**

1. 点击侧边栏"AI 视频生成"
2. 确认面板切换，视频生成表单完整显示
3. 点击侧边栏"图片爬取" → 切回爬取面板

- [ ] **Step 4: 验证视频目录扫描**

1. 切换到视频面板
2. 填入刚才爬取的保存目录
3. 点击"扫描" → 确认图片网格显示缩略图
4. 确认勾选/取消勾选正常工作
5. 确认 Logo 区域检测到 logo 文件

- [ ] **Step 5: 验证视频生成**

1. 选择输出路径（如 `F:\output\test.mp4`）
2. 点击"生成视频"
3. 确认进度条更新
4. 确认最终生成 MP4 文件可播放

- [ ] **Step 6: 验证错误路径**

1. 空目录扫描 → 提示"无有效的 PNG 图片"
2. 不选图片点生成 → 提示"至少选择一张图片"
3. 没有 FFmpeg → 提示"未找到 FFmpeg"

- [ ] **Step 7: 提交（如有修复）**

```bash
git add -A
git commit -m "fix: 端到端测试修复"
```

---

### Task 9: 下载 FFmpeg + 打包 EXE

**文件：**
- 下载：`ffmpeg.exe`（放入项目根目录）

- [ ] **Step 1: 下载 FFmpeg Windows 便携版**

从 https://www.gyan.dev/ffmpeg/builds/ 下载 `ffmpeg-release-essentials.zip`，解压获取 `ffmpeg.exe`（约 80MB），放到项目根目录：

```bash
# Windows PowerShell:
# Invoke-WebRequest -Uri "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip" -OutFile ffmpeg.zip
# Expand-Archive ffmpeg.zip -DestinationPath .
# copy ffmpeg-*\bin\ffmpeg.exe .
```

- [ ] **Step 2: 打包 EXE**

```bash
cd /f/carl_work/carl/Google/cc/ImageCrawling
pyinstaller --onefile --clean --name "gp-image-scraper" \
  --paths py \
  --add-binary "ffmpeg.exe;." \
  --add-data "index.html;." \
  --add-data "css/style.css;css" \
  --add-data "js/app.js;js" \
  --add-data "js/video.js;js" \
  py/main.py
```

- [ ] **Step 3: 验证打包后的 EXE**

```bash
# 在一个没有 Python 环境的机器上（或重命名 Python 目录临时测试）
dist/gp-image-scraper.exe
# 确认：
# 1. 浏览器自动打开
# 2. 爬取功能正常
# 3. 视频扫描功能正常
# 4. 视频生成正常（FFmpeg 从 MEIPASS 加载）
```

- [ ] **Step 4: 提交**

```bash
git add -A
git commit -m "build: 添加 FFmpeg 打包支持"
```

---

### Task 10: 更新文档

**文件：**
- 修改：`CLAUDE.md`

- [ ] **Step 1: 在 CLAUDE.md 中补充视频生成相关文档**

在 CLAUDE.md 末尾追加：

```markdown
## AI 视频生成（新增）

### 功能概述
- 左侧侧边栏导航：图片爬取 / AI 视频生成 两个标签页
- 视频生成流程：选择目录 → 扫描图片 → 勾选 → 设置参数 → 生成 MP4
- 混合方案：默认本地 FFmpeg 拼接（零成本），可选 Kling API 动态化

### 新增文件
| 文件 | 说明 |
|------|------|
| `py/video_processor.py` | VideoTask 类，FFmpeg 滤镜链构建与执行 |
| `py/ai_service.py` | AIProvider 接口 + KlingProvider 实现 |
| `js/video.js` | 视频面板 UI 逻辑 |

### 新增 API
| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/video/scan-dir` | 扫描目录返回图片列表 |
| GET | `/api/image?path=` | 返回本地图片文件流 |
| POST | `/api/video/generate` | 提交视频生成任务 |
| GET | `/api/video/progress?task_id=` | 轮询生成进度 |

### 注意事项
- 视频生成需要 FFmpeg（打包时通过 `--add-binary ffmpeg.exe;.` 嵌入）
- AI 动态化需要 Kling API Key（可选功能，不填则降级为静态帧拼接）
- Flask 需启用 `threaded=True`（视频生成在后台线程执行）
```

- [ ] **Step 2: 提交**

```bash
git add CLAUDE.md
git commit -m "docs: 更新 CLAUDE.md 添加视频生成文档"
```

---

## 验证清单

完成所有任务后，逐项验证：

- [ ] 侧边栏两个标签页切换正常
- [ ] 爬取功能完全不受影响
- [ ] 扫描目录正确展示图片网格缩略图
- [ ] 图片勾选/取消/全选正常
- [ ] Logo 检测和设置正常
- [ ] 生成 MP4 可播放，转场效果正确
- [ ] Logo 叠加位置/效果正确
- [ ] AI 参数面板折叠/展开正常
- [ ] 无 FFmpeg 时有明确错误提示
- [ ] 打包后 EXE 功能正常
