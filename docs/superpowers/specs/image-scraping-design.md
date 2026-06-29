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
