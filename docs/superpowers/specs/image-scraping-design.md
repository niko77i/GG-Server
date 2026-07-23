# 图片爬取 — 设计规格

**最后更新**：2026-06-14（合并自 2026-06-04 两个文档）

## 1. 功能概述

从 Google Play 链接批量爬取广告图片 + 应用 Logo，按 Google Ads 规格自动缩放，按包名分类保存。

## 2. 数据流

```
URL 列表（前端）
  → POST /api/scrape（逐条）
    → extract_package_name(url) → 创建 保存路径/包名/ 文件夹
    → scrape_images(url) → 获取广告图片 URL 列表
    → scrape_logo(url) → 获取 Logo URL
    → 对每张广告图: detect_format() → resize() → save .png（≤5 MiB）
    → 对 Logo: 原图直接保存 .png
    → 返回结果 JSON
  → 前端实时更新状态
```

## 3. 模块设计

### scraper.py

| 函数 | 说明 |
|------|------|
| `scrape_images(url)` | 查找 `<c-wiz jsrenderer="UZStuc">` 内所有 `<img>` src，升级高清 URL，去重返回 |
| `scrape_logo(url)` | 查找 `<div class="Mqg6jb Mhrnjf">` 内第一张 `<img>` src，返回绝对 URL（无则 None） |

### resizer.py

| 函数 | 说明 |
|------|------|
| `process_image(url, dir, name, skip_scaling)` | 下载 → 检测宽高比 → 匹配规格 → Pillow 缩放 → 保存 .png |
| `save_logo(url, dir, name)` | 下载 Logo 原图直接保存 .png，不做缩放 |

### utils.py

| 函数 | 说明 |
|------|------|
| `extract_package_name(url)` | 正则匹配 `?id=` 提取包名 |
| `detect_format(w, h)` | 根据宽高比返回 "landscape"/"square"/"portrait" |
| `natural_sort_key(s)` | 自然排序（数字按数值大小） |

## 4. 图片规格

| 类型 | 目标尺寸 | min_short | 宽高比 |
|------|----------|-----------|--------|
| landscape | 1200×628 | 314 | > 1.3 |
| square | 1200×1200 | 200 | 0.8 ~ 1.3 |
| portrait | 1200×1500 | 320 | < 0.8 |

短边小于 min_short 则等比放大；文件 > 5 MiB 以 0.85 倍逐步缩小；PNG 格式 optimise=True。

## 5. API

### POST /api/scrape

请求：`{"url": "...", "save_dir": "F:/images/", "include_ads_images": true}`

成功响应：
```json
{
  "success": true,
  "package_name": "com.example.app",
  "saved_path": "F:/images/com.example.app",
  "image_count": 5,
  "images": [{"filename": "com.example.app_001.png", "width": 1200, "height": 628}],
  "logo": {"filename": "com.example.app_logo.png", "width": 512, "height": 512} | null,
  "from_cache": false
}
```

特殊行为：如果 `save_dir/包名/` 已有 PNG 文件 → 直接返回本地缓存（`from_cache: true`），跳过爬取。

## 6. 前端交互

- URL 输入框：多行/逗号分隔
- 保存路径：文本框 + 📂 文件夹选择
- 复选框：「按 Google Ads 规格放大图片」，默认勾选
- 逐条调用 API，实时显示 ⏳/✅/❌，完成后统计汇总

## 7. 保存目录结构

```
<保存路径>/
└── com.example.app/
    ├── 包logo/
    │   └── com.example.app_logo.png
    ├── com.example.app_001.png
    ├── com.example.app_002.png
    └── ...
```

## 8. 错误处理

| 异常 | 行为 |
|------|------|
| `ScrapeError` | 页面不可访问/未找到目标标签 → 500 |
| `ResizeError`（单张） | 跳过该图，继续处理其他 |
| `scrape_logo` 返回 None | 不报错，logo 字段为 null |
| 提取包名失败 | 400 |

## 9. 技术栈

| 层 | 技术 |
|---|---|
| 前端 | HTML + CSS + JS |
| 后端 | Python 3 + Flask |
| 爬虫 | requests + beautifulsoup4 |
| 图片 | Pillow |

---

## 10. 审计补充（2026-07-23）

以下内容基于 `py/scraper.py`、`py/main.py`（scrape 相关路由）、`frontend/src/views/ScrapeView.vue`、`py/resizer.py`、`py/utils.py` 实际代码与本文档对比得出。标记为 **【缺失】** 表示代码已有但文档未提；标记为 **【差异】** 表示文档描述与代码行为不一致。

### 10.1 API 层

#### 【缺失】JWT 认证

`POST /api/scrape` 实际带有 `@jwt_required()` 装饰器，所有请求需要携带有效的 JWT token。文档未提及任何认证要求。

#### 【缺失】请求体为空的校验

代码对 `request.get_json(silent=True)` 返回 `None` 做了显式处理，返回 400 `{"success": False, "error": "请求体不能为空"}`。文档未提及此错误响应。

#### 【缺失】save_dir 为空时的默认路径

代码中，若客户端未传 `save_dir` 或传空字符串，服务端会根据当前登录用户的 `display_name`（或 `username`）自动生成路径：`<DATA_ROOT>/temp/scraped_images/<display_name>/`。文档描述 `save_dir` 为必填字段，未提及此默认行为。

#### 【缺失】额外 API 端点

代码中存在以下文档未提及的端点：

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/scrape/download` | GET | 将爬取的图片目录打包为 zip 下载，参数 `?path=` |
| `/api/scrape/packages` | GET | 列出当前用户已爬取的包列表，管理员可传 `?user_dn=` 查看其他用户 |
| `/api/scrape/users` | GET | 列出所有有爬取数据的用户（管理员用） |
| `/api/scrape/upload-images` | POST | 上传图片到用户专属目录，用于视频生成 |

### 10.2 爬虫模块（scraper.py）

#### 【缺失】`_upgrade_image_url` 私有函数

代码中存在文档未提及的 `_upgrade_image_url(url)` 函数，将 Google 图片 URL 中的 `=w<数字>-h<数字>` 模式替换为 `=w1200-h1200`。文档只说"升级高清 URL"，未给出具体替换规则。

#### 【缺失】User-Agent 请求头

所有 HTTP 请求均携带固定的 Chrome 120 User-Agent。文档未提及反爬策略，但在 Google Play 爬取场景中这是一个关键实现细节。

#### 【差异】`scrape_logo` 的异常处理

文档描述为"无则 None"，仅提到未找到目标标签时返回 None。代码实际在 `requests.RequestException`（网络异常）时也返回 None，且此时不会抛出 `ScrapeError`。这与 `scrape_images` 在同样场景下抛 `ScrapeError` 的行为不一致——logo 爬取失败是静默的，广告图爬取失败是显式的。

### 10.3 图片处理模块（resizer.py）

#### 【差异 - 重要】图片规格缩放逻辑

文档第 4 节列出了三种目标尺寸（1200×628、1200×1200、1200×1500），暗示图片会被缩放到这些具体尺寸。**代码实际行为并非如此**：

`resizer.py` 中的 `FORMAT_CONFIG` 只定义了 `min_short`（短边最小像素值），处理逻辑为：
1. 若短边 < `min_short`，等比放大至短边满足 `min_short`
2. 若已满足，**不做任何缩放，保留原尺寸**

代码不会强制将图片缩放到 1200×628 / 1200×1200 / 1200×1500 这些具体目标尺寸。文档第 4 节的描述具有误导性——"目标尺寸"应改为"最小短边要求"。

#### 【缺失】`process_image` 返回结构中的 `format` 字段

文档 API 响应示例中 `images` 数组元素为 `{"filename": "...", "width": 1200, "height": 628}`，但代码实际返回还包含 `"format": "landscape"` 字段，指示检测到的图片规格类型。

#### 【缺失】RGBA/P 模式转 RGB

`process_image` 和 `save_logo` 在保存前都会将 RGBA 和 P 模式图片转换为 RGB 模式（去掉透明通道），以减小文件大小。文档未提及此处理。

#### 【差异】`save_logo` 的实际行为

文档第 3.2 节描述为"下载 Logo 原图直接保存 .png，不做缩放"。代码实际行为：
- 同样执行 RGBA→RGB 转换
- 同样有 5 MiB 文件大小限制，超出时以 0.85 倍逐步缩小
- 因此"不做缩放"这一描述不准确——Logo 在文件过大时仍会被缩小

### 10.4 前端（ScrapeView.vue）

#### 【差异 - 重要】技术栈

文档第 9 节写前端为"HTML + CSS + JS"，但实际代码为 **Vue 3（`<script setup>`） + Element Plus + Vue Router**，是一个 SPA 组件而非纯静态页面。

#### 【缺失】仅 localhost 显示文件夹选择按钮

文件夹选择按钮（📂）仅在 `isLocalhost()` 返回 true 时渲染。文档未提及此条件限制。非 localhost 部署时，用户只能手动输入路径。

#### 【缺失】单条成功时自动跳转视频页

代码逻辑：当 `successCount === 1` 时，自动调用 `bridgeToVideo()`，将 `saved_path` 存入 `sessionStorage` 并跳转到 `/video` 路由。文档仅描述"完成后统计汇总"，未提及此自动跳转行为。

#### 【缺失】结果列表中的下载和视频桥接按钮

每条成功结果旁有两个操作按钮：📥 下载图片（调用 `/api/scrape/download`）和 🎬 生成视频（跳转视频页面）。文档第 6 节未提及这些交互。

#### 【缺失】`parseUrls` 的双重解析策略

URL 解析先尝试正则匹配 `play.google.com` 的完整链接，匹配不到时才回退到换行/逗号分隔。文档只说"多行/逗号分隔"，未描述优先提取完整链接的逻辑。

### 10.5 保存目录结构

#### 【差异】Logo 保存了两份

代码行为：Logo 首先保存到 `包logo/` 子目录，随后通过 `shutil.copy2` 在包根目录也复制一份。注释说明根目录的副本"作为内容图片使用，不会被叠加优化影响"。文档第 7 节只展示了 `包logo/` 下的单一路径，未体现根目录存在第二份副本。

### 10.6 并行处理

#### 【缺失】ThreadPoolExecutor 并发下载

广告图片下载使用 `concurrent.futures.ThreadPoolExecutor`，最多 4 个并发 worker。文档第 2 节数据流未提及并行处理。

### 10.7 部分成功逻辑

#### 【缺失】广告图爬取失败但 Logo 已保存时的部分成功响应

代码中存在一条特殊路径：若 `scrape_images` 抛 `ScrapeError` 但 Logo 已成功保存，API 返回 `success: true`（而非 500），`image_count` 为 0。文档错误处理表中未列出此场景。

#### 【缺失】既无 Logo 也无广告图时返回 404

代码中，当 `scrape_images` 返回空列表且 `scrape_logo` 也返回 None 时，API 返回 404 `{"success": False, "error": "该页面未找到图片"}`。文档未描述此 HTTP 状态码。

### 10.8 工具函数（utils.py）

#### 【差异】`detect_format` 的 portrait 边界条件

文档第 4 节写 portrait 条件为 `ratio < 0.8`。代码中为 `ratio <= 0.8`（等号归属不同）。意味着宽高比恰好为 0.8 的图片在文档中归类为 square，在代码中归类为 portrait。

### 10.9 缓存逻辑

#### 【差异】缓存触发条件

文档描述为"如果 `save_dir/包名/` 已有 PNG 文件"，暗示有任意 PNG 即命中缓存。代码中还需验证 `os.path.isdir(pkg_dir)` 目录确实存在（而不仅仅是拼出路径）。此外，缓存响应中的 images 数组元素多了一个 `"local": True` 字段，文档未提及。

### 10.10 汇总

| 类别 | 数量 |
|------|------|
| 缺失项（代码有、文档无） | 13 |
| 差异项（文档与代码不一致） | 8 |
| 其中需重点关注 | 见下方 |

**需重点关注的问题**：

1. **图片缩放逻辑**（10.3）：文档声称缩放到 Google Ads 目标尺寸，代码只保证短边最小值——概念偏差最大的一项。
2. **前端技术栈**（10.4）：文档写 HTML+CSS+JS，实际是 Vue 3 SPA。
3. **JWT 认证**（10.1）：API 调用方如不携带 token 会收到 401，文档缺失此关键前置条件。
4. **Logo 双份保存**（10.5）：目录结构描述不完整。
5. **detect_format 边界**（10.8）：ratio=0.8 的归类文档与代码有分歧。
