# Logo 爬取 + 广告图片可选 + 命名优化 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 新增应用 Logo 爬取、广告图片变为可选、图片命名改为包名前缀

**Architecture:** 在现有 scraper/resizer 中各加一个函数（scrape_logo/save_logo），main.py 增加 logo 流程和新参数，前端加一个复选框控制广告图片开关

**Tech Stack:** Python 3 + Flask + requests + BeautifulSoup4 + Pillow，前端 HTML/CSS/JS 无框架

---

### 文件结构

| 文件 | 操作 | 职责 |
|------|------|------|
| `py/scraper.py` | 修改 | 新增 `scrape_logo()` — 提取 `<div class="Mqg6jb Mhrnjf">` 内第一张图片 URL |
| `py/resizer.py` | 修改 | 新增 `save_logo()` — 下载原图直接存 PNG，不缩放 |
| `py/main.py` | 修改 | 接收 `include_ads_images`，调用 logo 流程，命名改为 `包名_NNN` |
| `index.html` | 修改 | 新增复选框控件 |
| `js/app.js` | 修改 | 读取复选框，传递参数，更新结果展示 |

---

### Task 1: scraper.py — 新增 scrape_logo()

**文件:**
- 修改: `py/scraper.py`

- [ ] **Step 1: 在 scrape_images 函数之后添加 scrape_logo 函数**

在 `scrape_images` 函数定义结束后（`return unique` 之后，文件末尾之前）插入：

```python
def scrape_logo(url: str) -> str | None:
    """从 Google Play 页面 <div class="Mqg6jb Mhrnjf"> 中提取第一张图片 URL。

    参数:
        url: Google Play 应用页面链接

    返回:
        第一张图片的绝对 URL，未找到返回 None
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
    except requests.RequestException:
        return None

    soup = BeautifulSoup(resp.text, "html.parser")
    logo_div = soup.find("div", class_="Mqg6jb Mhrnjf")

    if logo_div is None:
        return None

    img = logo_div.find("img")
    if img is None:
        return None

    src = img.get("src")
    if not src:
        return None

    return urljoin(url, src)
```

- [ ] **Step 2: 验证导入完整**

确保文件头部的 import 已经包含 `urljoin`（现有代码已有），无需额外导入。检查现有 import：
```python
import re
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin
```
以上已覆盖新函数所需全部依赖。

- [ ] **Step 3: 提交**

```bash
git add py/scraper.py
git commit -m "feat: 添加 scrape_logo() 爬取 Google Play 应用图标"
```

---

### Task 2: resizer.py — 新增 save_logo()

**文件:**
- 修改: `py/resizer.py`

- [ ] **Step 1: 在 process_image 函数之后添加 save_logo 函数**

在 `process_image` 函数定义结束后插入：

```python
def save_logo(img_url: str, save_dir: str, filename: str) -> dict:
    """下载 logo 原图并保存为 PNG，不做缩放处理。

    参数:
        img_url: 图片远程 URL
        save_dir: 保存目录的绝对路径
        filename: 不含扩展名的文件名

    返回:
        {"filename": "xxx.png", "width": 120, "height": 120, "format": "logo"}

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
        raise ResizeError(f"下载 logo 失败: {e}")

    # 2. 打开图片
    try:
        img = Image.open(img_data)
    except Exception as e:
        raise ResizeError(f"无法识别 logo 格式: {e}")

    # 3. 不做缩放，直接保存为 PNG
    output_path = os.path.join(save_dir, f"{filename}.png")

    # RGBA → RGB
    if img.mode in ("RGBA", "P"):
        img = img.convert("RGB")

    img.save(output_path, "PNG", optimize=True)

    # 如果文件超过 5 MiB，逐步缩小
    while os.path.getsize(output_path) > MAX_FILE_SIZE:
        new_w = int(img.width * 0.85)
        new_h = int(img.height * 0.85)
        if new_w < 1 or new_h < 1:
            break
        img = img.resize((new_w, new_h), Image.LANCZOS)
        img.save(output_path, "PNG", optimize=True)

    return {
        "filename": f"{filename}.png",
        "width": img.width,
        "height": img.height,
        "format": "logo",
    }
```

- [ ] **Step 2: 提交**

```bash
git add py/resizer.py
git commit -m "feat: 添加 save_logo() 保存应用图标原图"
```

---

### Task 3: main.py — 命名 + logo 流程 + include_ads_images

**文件:**
- 修改: `py/main.py`

- [ ] **Step 1: 修改 scrape() 函数 — 增加 logo 导入和参数解析**

在文件头部导入区添加 `scrape_logo` 和 `save_logo`：

```python
from scraper import scrape_images, scrape_logo, ScrapeError
from resizer import process_image, save_logo, ResizeError
```

- [ ] **Step 2: 修改 scrape() 函数体**

将原有的 `scrape()` 函数整体替换为以下内容（保持路由装饰器不变）：

```python
@app.route("/api/scrape", methods=["POST"])
def scrape():
    data = request.get_json(silent=True)
    if not data:
        return jsonify({"success": False, "error": "请求体不能为空"}), 400

    url = data.get("url", "").strip()
    save_dir = data.get("save_dir", "").strip()
    # 新增参数：是否下载广告图片（默认 true，向后兼容）
    include_ads_images = data.get("include_ads_images", True)

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

    response = {
        "success": True,
        "package_name": pkg_name,
        "saved_path": pkg_dir,
    }

    # ---- 3a. Logo 爬取（始终执行） ----
    logo_url = scrape_logo(url)
    if logo_url:
        logo_dir = os.path.join(pkg_dir, "包logo")
        try:
            os.makedirs(logo_dir, exist_ok=True)
            logo_result = save_logo(logo_url, logo_dir, f"{pkg_name}_logo")
            response["logo"] = logo_result
        except (ResizeError, OSError):
            response["logo"] = None
    else:
        response["logo"] = None

    # ---- 3b. 广告图片爬取（可选） ----
    if include_ads_images:
        try:
            img_urls = scrape_images(url)
        except ScrapeError as e:
            response["image_count"] = 0
            response["images"] = []
            if response["logo"] is None:
                return jsonify({"success": False, "error": str(e)}), 500
            # 有 logo 但广告图爬取失败 — 部分成功
            response["success"] = True
            return jsonify(response)

        if not img_urls:
            response["image_count"] = 0
            response["images"] = []
        else:
            results = []
            for i, img_url in enumerate(img_urls):
                try:
                    # 命名改为 包名_序号
                    result = process_image(img_url, pkg_dir, f"{pkg_name}_{i+1:03d}")
                    results.append(result)
                except ResizeError:
                    continue
            response["image_count"] = len(results)
            response["images"] = results
    else:
        response["image_count"] = 0
        response["images"] = []

    return jsonify(response)
```

- [ ] **Step 3: 提交**

```bash
git add py/main.py
git commit -m "feat: 命名改为包名前缀 + logo 流程 + include_ads_images 参数"
```

---

### Task 4: index.html — 新增复选框

**文件:**
- 修改: `index.html`

- [ ] **Step 1: 在保存路径输入框和开始按钮之间插入复选框**

找到：
```html
        <button id="startBtn" onclick="startScrape()">🚀 开始爬取</button>
```

在其上方插入：
```html
        <div class="form-group checkbox-group">
            <label class="checkbox-label">
                <input type="checkbox" id="includeAds" checked />
                下载 Google Ads 规格图片（缩放处理）
            </label>
        </div>
```

- [ ] **Step 2: 提交**

```bash
git add index.html
git commit -m "feat: 添加广告图片下载开关复选框"
```

---

### Task 5: js/app.js — 传递复选框状态

**文件:**
- 修改: `js/app.js`

- [ ] **Step 1: 修改 startScrape() — 读取复选框并传递参数**

找到 `startScrape` 函数，在接口调用处修改。当前代码：
```javascript
            const resp = await fetch(`${API_BASE}/api/scrape`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ url: url, save_dir: saveDir }),
            });
```

修改为：
```javascript
            const includeAds = document.getElementById("includeAds").checked;
            const resp = await fetch(`${API_BASE}/api/scrape`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ url: url, save_dir: saveDir, include_ads_images: includeAds }),
            });
```

- [ ] **Step 2: 修改 startScrape() — 更新结果展示以显示 logo 状态**

找到成功分支的结果展示：
```javascript
            if (data.success) {
                item.className = "result-item success";
                item.innerHTML = `<span class="icon">✅</span> <span class="text">${data.package_name}</span> <span class="detail">— ${data.image_count} 张图片 → ${data.saved_path}</span>`;
                successCount++;
                totalImages += data.image_count;
            }
```

修改为（增加 logo 信息展示）：
```javascript
            if (data.success) {
                item.className = "result-item success";
                const logoInfo = data.logo ? " + logo" : "";
                const imgInfo = includeAds ? ` — ${data.image_count} 张广告图` : "";
                item.innerHTML = `<span class="icon">✅</span> <span class="text">${data.package_name}</span> <span class="detail">${imgInfo}${logoInfo} → ${data.saved_path}</span>`;
                successCount++;
                totalImages += (data.image_count || 0) + (data.logo ? 1 : 0);
            }
```

- [ ] **Step 3: 提交**

```bash
git add js/app.js
git commit -m "feat: 前端传递 include_ads_images + 显示 logo 状态"
```

---

### Task 6: css/style.css — 复选框样式

**文件:**
- 修改: `css/style.css`

- [ ] **Step 1: 在 style.css 末尾追加复选框样式**

```css
.checkbox-group {
    margin-bottom: 20px;
}

.checkbox-label {
    display: flex;
    align-items: center;
    gap: 8px;
    font-weight: 400;
    font-size: 14px;
    cursor: pointer;
}

.checkbox-label input[type="checkbox"] {
    width: auto;
    cursor: pointer;
}
```

- [ ] **Step 2: 提交**

```bash
git add css/style.css
git commit -m "style: 复选框样式"
```

---

### Task 7: 验证

- [ ] **Step 1: 启动服务验证**

```bash
cd py
python main.py
```

- [ ] **Step 2: curl 测试（仅 Logo）**

```bash
curl -X POST http://localhost:5000/api/scrape \
  -H "Content-Type: application/json" \
  -d '{"url": "https://play.google.com/store/apps/details?id=com.spotify.music", "save_dir": "./test_output", "include_ads_images": false}'
```

预期响应包含 `"logo": {...}` 且 `"image_count": 0`。

- [ ] **Step 3: curl 测试（Logo + 广告图片）**

```bash
curl -X POST http://localhost:5000/api/scrape \
  -H "Content-Type: application/json" \
  -d '{"url": "https://play.google.com/store/apps/details?id=com.spotify.music", "save_dir": "./test_output"}'
```

预期：图片文件名格式为 `com.spotify.music_001.png`，logo 保存在 `包logo/` 子目录。

- [ ] **Step 4: 打开前端验证**

浏览器打开 http://localhost:5000，测试复选框开关。

- [ ] **Step 5: 提交（如有修正）**

```bash
git add -A && git commit -m "fix: 验证后的修正"
```
