# 媒体页 — 上传图片 + 视频生成始终可见

## 需求

1. **视频生成区域始终展示**：不依赖是否已扫描图片，打开页面就能看到完整的视频生成设置
2. **上传图片**：用户可以从自己电脑上传图片到服务器，用于制作视频

## 方案

### 上传图片

用户点击上传 → 选择本地图片文件 → 上传到服务器用户专属目录 → 自动加载到预览区 → 可用于生成视频。

存储路径：
```
temp/scraped_images/<display_name>/_uploads/<时间戳>/
```

### 视频生成始终可见

去掉 `v-if="images.length"` 条件，改为始终渲染。包下拉框中增加上传的文件夹。

### 整体布局调整

② 图片预览区域增加上传按钮和拖拽区：

```
┌─ ② 图片预览 ────────────────────────────────────┐
│ [选择包下拉框] [🔍扫描]                         │
│ 或                                               │
│ ┌─────────────────────────────────────┐          │
│ │    拖拽图片到此处 或 点击上传         │          │
│ └─────────────────────────────────────┘          │
│ 图片网格预览                                      │
└──────────────────────────────────────────────────┘
```

## 后台改动

**新增 `POST /api/scrape/upload-images`**

- `@jwt_required()`
- multipart/form-data，多文件上传
- 保存到 `temp/scraped_images/<display_name>/_uploads/<timestamp>/`
- 返回上传的文件列表（含路径、宽高）
- 返回目录路径 `saved_path`，前端可直接 scanDir

## 前端改动 `MediaView.vue`

### 模板
- ② 增加上传区域（拖拽/点击）
- ③ 去掉 `v-if="images.length"`，始终展示
- 无图片时显示"请先爬取或上传图片"

### 脚本
- `uploadImages()` — FormData 多文件上传
- 上传成功后自动 scanDir

## 涉及文件

| 文件 | 改动 |
|---|---|
| `py/main.py` | 新增 `/api/scrape/upload-images` |
| `MediaView.vue` | 上传区域 + ③ 始终可见 |

---

## 实际代码逻辑补充（2026-07-23 审计）

### 1. 图片自动转格式

设计文档未提及图片格式转换。代码实际使用 PIL 将上传图片统一转为 **RGBA PNG**：

```python
img = PILImage.open(f.stream)
img = img.convert("RGBA")
img.save(fp, "PNG")
```

支持的上传格式：`.png`, `.jpg`, `.jpeg`, `.webp`, `.bmp`。

### 2. 存储路径格式

文档写的路径格式为 `_uploads/<timestamp>/`，实际代码使用 `_upload_{timestamp}`（单数 `upload`，非 `uploads`）：

```
temp/scraped_images/<display_name>/_upload_20260723_143000/
```

### 3. 返回数据结构

实际 API 返回比设计文档更丰富：

```json
{
  "success": true,
  "saved_path": "temp/scraped_images/...",
  "image_count": 3,
  "images": [
    {"filename": "photo.png", "path": "...", "width": 1920, "height": 1080}
  ]
}
```

每个图片返回文件名、路径、宽高，前端可直接用于预览。

### 4. 文件名安全处理

空格替换为 `_`，反斜杠替换为 `_`，文件名截取扩展名之前的部分（`rsplit('.', 1)[0]`）。
