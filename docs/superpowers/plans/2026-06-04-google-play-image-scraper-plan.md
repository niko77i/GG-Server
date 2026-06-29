# Google Play 图片爬取与处理工具 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 构建一个工具，从 Google Play 链接批量爬取 `<c-wiz jsrenderer="UZStuc">` 内的图片，按 Google Ads 规格缩放，按包名分类保存。

**Architecture:** HTML+CSS+JS 前端 → Flask HTTP API → requests+BeautifulSoup 爬取 → Pillow 缩放处理。单一数据流，前端逐条 POST URL，后端同步处理并返回结果。

**Tech Stack:** Python 3 + Flask + flask-cors + requests + beautifulsoup4 + Pillow, HTML + CSS + vanilla JS

**项目不涉及 git，跳过 commit 步骤。**

---

## File Structure

```
tt/
├── index.html              # 前端页面（新建）
├── css/
│   └── style.css           # 样式（新建）
├── js/
│   └── app.js              # 前端逻辑（新建）
├── py/
│   ├── main.py             # Flask API 入口（新建）
│   ├── scraper.py          # 爬取 c-wiz 内图片 URL（新建）
│   ├── resizer.py          # 下载+缩放+保存 .png（新建）
│   └── utils.py            # 包名提取 + 宽高比判断（新建）
└── requirements.txt        # Python 依赖（新建）
```

---

### Task 1: 项目脚手架 & 依赖

**Files:**
- Create: `requirements.txt`

- [ ] **Step 1: 创建 requirements.txt**

```txt
flask>=3.0
flask-cors>=4.0
requests>=2.31
beautifulsoup4>=4.12
Pillow>=10.0
```

- [ ] **Step 2: 安装依赖**

```bash
pip install -r requirements.txt
```

- [ ] **Step 3: 创建目录结构**

```bash
mkdir -p css js py
```

---

### Task 2: utils.py — 工具函数

**Files:**
- Create: `py/utils.py`

- [ ] **Step 1: 实现 extract_package_name(url)**

```python
import re


def extract_package_name(url: str) -> str:
    """从 Google Play URL 提取包名。

    支持格式:
    - https://play.google.com/store/apps/details?id=com.abc.def
    - https://play.google.com/store/apps/details?id=com.abc.def&hl=zh
    - https://play.google.com/store/apps/details/com.abc.def

    返回包名字符串，无法提取时抛出 ValueError。
    """
    # 匹配 ?id=xxx 或 &id=xxx 格式
    m = re.search(r"[?&]id=([^&]+)", url)
    if m:
        return m.group(1)

    # 匹配 /details/xxx 路径格式
    m = re.search(r"/details/([^/?]+)", url)
    if m:
        return m.group(1)

    raise ValueError(f"无法从 URL 提取包名: {url}")
```

- [ ] **Step 2: 实现 detect_format(w, h)**

```python
def detect_format(width: int, height: int) -> str:
    """根据图片宽高比判断 Google Ads 规格。

    返回: "landscape" | "square" | "portrait"
    """
    ratio = width / height
    if ratio > 1.3:
        return "landscape"
    elif ratio < 0.8:
        return "portrait"
    else:
        return "square"
```

- [ ] **Step 3: 验证 utils.py 可独立运行**

```bash
python -c "from py.utils import extract_package_name, detect_format; \
  print(extract_package_name('https://play.google.com/store/apps/details?id=com.spotify.music')); \
  print(detect_format(1200, 628)); \
  print(detect_format(1200, 1200)); \
  print(detect_format(1200, 1500))"
```

预期输出:
```
com.spotify.music
landscape
square
portrait
```

---

### Task 3: scraper.py — 爬取模块

**Files:**
- Create: `py/scraper.py`

- [ ] **Step 1: 实现 ScrapeError 异常和 scrape_images(url)**

```python
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin


class ScrapeError(Exception):
    """爬取失败异常。"""
    pass


def scrape_images(url: str) -> list[str]:
    """从 Google Play 页面爬取 <c-wiz jsrenderer='UZStuc'> 内所有图片 URL。

    参数:
        url: Google Play 应用页面链接

    返回:
        去重后的图片 URL 列表（已补全为绝对路径）

    异常:
        ScrapeError: 页面不可访问、未找到目标标签
    """
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        )
    }

    try:
        resp = requests.get(url, headers=headers, timeout=30)
        resp.raise_for_status()
    except requests.RequestException as e:
        raise ScrapeError(f"无法访问页面: {e}")

    soup = BeautifulSoup(resp.text, "html.parser")
    c_wiz = soup.find("c-wiz", {"jsrenderer": "UZStuc"})

    if c_wiz is None:
        raise ScrapeError("未找到目标标签 <c-wiz jsrenderer='UZStuc'>")

    img_urls = []
    for img in c_wiz.find_all("img"):
        src = img.get("src")
        if src:
            # 补全相对路径
            full_url = urljoin(url, src)
            img_urls.append(full_url)

    # 去重，保持顺序
    seen = set()
    unique = []
    for u in img_urls:
        if u not in seen:
            seen.add(u)
            unique.append(u)

    return unique
```

- [ ] **Step 2: 验证 scrape_images 可导入**

```bash
python -c "from py.scraper import scrape_images, ScrapeError; print('OK')"
```

预期: `OK`

---

### Task 4: resizer.py — 图片处理模块

**Files:**
- Create: `py/resizer.py`

- [ ] **Step 1: 实现图片规格配置和 process_image()**

```python
import os
import requests
from PIL import Image
from io import BytesIO
from .utils import detect_format


# Google Ads 图片规格配置
FORMAT_CONFIG = {
    "landscape": {"target": (1200, 628), "min": (600, 314)},
    "square":    {"target": (1200, 1200), "min": (200, 200)},
    "portrait":  {"target": (1200, 1500), "min": (320, 400)},
}

MAX_FILE_SIZE = 5 * 1024 * 1024  # 5 MiB


class ResizeError(Exception):
    """图片处理失败异常。"""
    pass


def process_image(img_url: str, save_dir: str, filename: str) -> dict:
    """下载、缩放并保存单张图片为 .png。

    参数:
        img_url: 图片远程 URL
        save_dir: 保存目录的绝对路径
        filename: 不含扩展名的文件名

    返回:
        {"filename": "img_001.png", "width": 1200, "height": 628, "format": "landscape"}

    异常:
        ResizeError: 下载失败或处理失败
    """
    # 1. 下载图片
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        )
    }
    try:
        resp = requests.get(img_url, headers=headers, timeout=30, stream=True)
        resp.raise_for_status()
        img_data = BytesIO(resp.content)
    except requests.RequestException as e:
        raise ResizeError(f"下载图片失败: {e}")

    # 2. 打开图片
    try:
        img = Image.open(img_data)
    except Exception as e:
        raise ResizeError(f"无法识别图片格式: {e}")

    # 3. 判断规格
    fmt = detect_format(img.width, img.height)
    cfg = FORMAT_CONFIG[fmt]
    target_w, target_h = cfg["target"]

    # 4. 如果原图小于目标尺寸，放大
    if img.width < target_w or img.height < target_h:
        img = img.resize((target_w, target_h), Image.LANCZOS)

    # 5. 保存为 .png，确保 ≤ 5 MiB
    output_path = os.path.join(save_dir, f"{filename}.png")
    quality = 95
    while True:
        img.save(output_path, "PNG", optimize=True)
        size = os.path.getsize(output_path)
        if size <= MAX_FILE_SIZE or quality <= 30:
            break
        quality -= 15
        # 降 quality 对 PNG 效果有限，如果仍超标则缩小尺寸
        if quality <= 60:
            new_w = int(img.width * 0.9)
            new_h = int(img.height * 0.9)
            img = img.resize((new_w, new_h), Image.LANCZOS)

    return {
        "filename": f"{filename}.png",
        "width": img.width,
        "height": img.height,
        "format": fmt,
    }
```

- [ ] **Step 2: 验证 resizer 可导入**

```bash
python -c "from py.resizer import process_image, ResizeError, FORMAT_CONFIG; print('OK')"
```

预期: `OK`

---

### Task 5: main.py — Flask API 入口

**Files:**
- Create: `py/main.py`
- Create: `py/__init__.py` (空文件，支持包导入)

- [ ] **Step 1: 创建 py/__init__.py**

```bash
echo "" > py/__init__.py
```

- [ ] **Step 2: 实现 Flask API**

```python
import os
from flask import Flask, request, jsonify
from flask_cors import CORS

from .scraper import scrape_images, ScrapeError
from .resizer import process_image, ResizeError
from .utils import extract_package_name

app = Flask(__name__)
CORS(app)


@app.route("/api/health", methods=["GET"])
def health():
    return jsonify({"status": "ok"})


@app.route("/api/scrape", methods=["POST"])
def scrape():
    data = request.get_json(silent=True)
    if not data:
        return jsonify({"success": False, "error": "请求体不能为空"}), 400

    url = data.get("url", "").strip()
    save_dir = data.get("save_dir", "").strip()

    if not url:
        return jsonify({"success": False, "error": "URL 不能为空"}), 400
    if not save_dir:
        return jsonify({"success": False, "error": "保存路径不能为空"}), 400

    # 1. 提取包名
    try:
        pkg_name = extract_package_name(url)
    except ValueError as e:
        return jsonify({"success": False, "error": str(e)}), 400

    # 2. 创建保存目录
    pkg_dir = os.path.join(save_dir, pkg_name)
    try:
        os.makedirs(pkg_dir, exist_ok=True)
    except OSError as e:
        return jsonify({"success": False, "error": f"无法创建目录: {e}"}), 500

    # 3. 爬取图片 URL
    try:
        img_urls = scrape_images(url)
    except ScrapeError as e:
        return jsonify({"success": False, "error": str(e)}), 500

    if not img_urls:
        return jsonify({"success": False, "error": "该页面未找到图片"}), 404

    # 4. 逐张处理
    results = []
    for i, img_url in enumerate(img_urls):
        try:
            result = process_image(img_url, pkg_dir, f"img_{i+1:03d}")
            results.append(result)
        except ResizeError:
            # 单张失败不影响其他图片
            continue

    return jsonify({
        "success": True,
        "package_name": pkg_name,
        "image_count": len(results),
        "saved_path": pkg_dir,
        "images": results,
    })


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=True)
```

- [ ] **Step 3: 启动 Flask 服务验证**

```bash
cd py && python main.py
```

预期: `* Running on http://127.0.0.1:5000`

- [ ] **Step 4: 测试 health 端点**

```bash
curl http://localhost:5000/api/health
```

预期: `{"status":"ok"}`

---

### Task 6: index.html — 前端页面

**Files:**
- Create: `index.html`
- Create: `css/style.css`
- Create: `js/app.js`

- [ ] **Step 1: 创建 index.html**

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
    <div class="container">
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

        <button id="startBtn" onclick="startScrape()">🚀 开始爬取</button>

        <div id="results" class="results">
            <h3>📊 处理结果</h3>
            <div id="resultList"></div>
            <div id="summary" class="summary" style="display:none;"></div>
        </div>
    </div>

    <script src="js/app.js"></script>
</body>
</html>
```

- [ ] **Step 2: 创建 css/style.css**

```css
* {
    margin: 0;
    padding: 0;
    box-sizing: border-box;
}

body {
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    background: #f5f5f5;
    color: #333;
    line-height: 1.6;
}

.container {
    max-width: 700px;
    margin: 40px auto;
    padding: 32px;
    background: #fff;
    border-radius: 12px;
    box-shadow: 0 2px 12px rgba(0,0,0,0.08);
}

h1 {
    font-size: 24px;
    margin-bottom: 4px;
}

.subtitle {
    color: #888;
    font-size: 14px;
    margin-bottom: 28px;
}

.form-group {
    margin-bottom: 20px;
}

.form-group label {
    display: block;
    font-weight: 600;
    margin-bottom: 6px;
    font-size: 14px;
}

.form-group textarea,
.form-group input {
    width: 100%;
    padding: 12px;
    border: 1px solid #ddd;
    border-radius: 8px;
    font-size: 14px;
    font-family: inherit;
    transition: border-color 0.2s;
}

.form-group textarea:focus,
.form-group input:focus {
    outline: none;
    border-color: #4a90d9;
}

.hint {
    display: block;
    margin-top: 4px;
    font-size: 12px;
    color: #aaa;
}

button {
    width: 100%;
    padding: 14px;
    background: #4a90d9;
    color: #fff;
    border: none;
    border-radius: 8px;
    font-size: 16px;
    font-weight: 600;
    cursor: pointer;
    transition: background 0.2s;
}

button:hover {
    background: #3a7bc8;
}

button:disabled {
    background: #b0c4de;
    cursor: not-allowed;
}

.results {
    margin-top: 28px;
}

.results h3 {
    font-size: 16px;
    margin-bottom: 12px;
}

.result-item {
    padding: 10px 12px;
    border-radius: 6px;
    margin-bottom: 8px;
    font-size: 13px;
    display: flex;
    align-items: center;
    gap: 8px;
}

.result-item.pending {
    background: #fff8e1;
    border: 1px solid #ffe082;
}

.result-item.success {
    background: #e8f5e9;
    border: 1px solid #a5d6a7;
}

.result-item.error {
    background: #ffebee;
    border: 1px solid #ef9a9a;
}

.result-item .icon {
    font-size: 16px;
    min-width: 20px;
}

.result-item .detail {
    color: #666;
    font-size: 12px;
}

.summary {
    margin-top: 16px;
    padding: 12px;
    background: #e3f2fd;
    border-radius: 8px;
    font-size: 14px;
    font-weight: 600;
}
```

- [ ] **Step 3: 创建 js/app.js**

```javascript
const API_BASE = "http://localhost:5000";

function parseUrls(input) {
    // 先按换行分割，再按逗号分割，过滤空字符串
    return input
        .split(/[\n,]+/)
        .map(s => s.trim())
        .filter(s => s.length > 0);
}

async function startScrape() {
    const urlsText = document.getElementById("urls").value.trim();
    const saveDir = document.getElementById("saveDir").value.trim();
    const startBtn = document.getElementById("startBtn");
    const resultList = document.getElementById("resultList");
    const summary = document.getElementById("summary");

    if (!urlsText) {
        alert("请输入至少一个 Google Play 链接");
        return;
    }
    if (!saveDir) {
        alert("请输入保存路径");
        return;
    }

    const urls = parseUrls(urlsText);

    // 重置状态
    resultList.innerHTML = "";
    summary.style.display = "none";
    startBtn.disabled = true;
    startBtn.textContent = "⏳ 处理中...";

    let successCount = 0;
    let failCount = 0;
    let totalImages = 0;

    for (const url of urls) {
        // 创建结果行
        const item = document.createElement("div");
        item.className = "result-item pending";
        item.innerHTML = `<span class="icon">⏳</span> <span class="text">${url}</span>`;
        resultList.appendChild(item);

        try {
            const resp = await fetch(`${API_BASE}/api/scrape`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ url: url, save_dir: saveDir }),
            });
            const data = await resp.json();

            if (data.success) {
                item.className = "result-item success";
                item.innerHTML = `<span class="icon">✅</span> <span class="text">${data.package_name}</span> <span class="detail">— ${data.image_count} 张图片 → ${data.saved_path}</span>`;
                successCount++;
                totalImages += data.image_count;
            } else {
                item.className = "result-item error";
                item.innerHTML = `<span class="icon">❌</span> <span class="text">${url}</span> <span class="detail">— ${data.error}</span>`;
                failCount++;
            }
        } catch (err) {
            item.className = "result-item error";
            item.innerHTML = `<span class="icon">❌</span> <span class="text">${url}</span> <span class="detail">— 网络错误: ${err.message}</span>`;
            failCount++;
        }
    }

    // 显示汇总
    startBtn.disabled = false;
    startBtn.textContent = "🚀 开始爬取";
    summary.style.display = "block";
    summary.textContent = `完成！成功 ${successCount} 个，失败 ${failCount} 个，共保存 ${totalImages} 张图片`;
}
```

- [ ] **Step 4: 在浏览器中打开 index.html 验证页面渲染**

用浏览器打开 `index.html`，确认页面正常显示：标题、两个输入框、按钮。

---

### Task 7: 集成测试

**Files:**
- 无新建文件

- [ ] **Step 1: 确认 Flask 服务运行中**

```bash
curl http://localhost:5000/api/health
```

预期: `{"status":"ok"}`

- [ ] **Step 2: 端到端测试 scrape 端点（使用真实 URL）**

```bash
curl -X POST http://localhost:5000/api/scrape \
  -H "Content-Type: application/json" \
  -d "{\"url\": \"https://play.google.com/store/apps/details?id=com.spotify.music\", \"save_dir\": \"./test_output\"}"
```

检查:
- 返回 `"success": true`
- `saved_path` 目录下存在 .png 文件
- 图片尺寸符合三种规格之一

- [ ] **Step 3: 前端手动测试**

1. 打开 `index.html`
2. 输入一个 Google Play 链接
3. 输入保存路径
4. 点击"开始爬取"
5. 确认结果区显示 ✅ 状态和图片数量

---

### Task 8: 完善 CLAUDE.md

**Files:**
- Modify: `CLAUDE.md`

- [ ] **Step 1: 更新 CLAUDE.md 状态**

将原有 "项目目前处于规划阶段，尚未开始编码" 替换为实际的项目启动说明和架构信息（当前 CLAUDE.md 已包含大部分内容，只需移除规划阶段提示并添加启动命令）。
