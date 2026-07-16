# 音频替换 — 预览播放 & 历史记录

## 需求描述

当前音频替换已改为上传模式，但缺少两个体验功能：

1. **上传后预览**：用户上传视频/音频后，无法确认文件内容是否正确，需要在处理前能播放预览
2. **历史记录**：处理完没有记录，刷新页面就丢了。需要保留历史，支持回看和重新下载

## 技术方案

### 1. 上传预览（纯前端）

利用 `URL.createObjectURL()` 为已选择的 File 对象生成 blob URL，用 HTML5 `<video>` / `<audio>` 标签播放。

- 视频文件 → `<video>` 预览（静音、循环、小尺寸）
- 音频文件 → `<audio>` 预览（显示播放控件）
- 切换文件时用 `URL.revokeObjectURL()` 释放旧 URL，避免内存泄漏

涉及文件：
- [ToolkitView.vue](frontend/src/views/ToolkitView.vue) — 文件选择区域下方加预览播放器

### 2. 历史记录（前后端）

#### 2.1 数据库

在 SQLite 中新增 `audio_replace_history` 表（通过 `database.py` 的 `_ensure_schema` 自动创建）：

```sql
CREATE TABLE IF NOT EXISTS audio_replace_history (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    video_name  TEXT    NOT NULL,   -- 原视频文件名
    audio_name  TEXT    NOT NULL,   -- 音频源文件名
    output_name TEXT    NOT NULL,   -- 输出文件名
    output_path TEXT    NOT NULL,   -- 输出文件完整路径（用于下载）
    size_mb     REAL    NOT NULL,   -- 文件大小 (MB)
    created_at  TEXT    NOT NULL    -- 创建时间 ISO 格式
);
```

#### 2.2 API

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/audio-replace/history` | 返回历史列表（按时间倒序） |
| DELETE | `/api/audio-replace/history/<id>` | 删除单条历史（同时删除文件） |
| DELETE | `/api/audio-replace/history` | 清空全部历史（同时清理文件） |

现有 `/api/audio-replace` 在处理成功后自动写入历史。

#### 2.3 前端 UI

在音频替换 tab 下方增加历史记录区域：
- 表格列表：原视频名、音频源名、输出文件名、大小、时间、操作（下载、删除）
- 支持单条删除和全部清空
- 点击下载直接触发浏览器下载

涉及文件：
- [main.py](py/main.py) — 新增 2-3 个 API 端点，修改现有的 audio_replace 写入历史
- [database.py](py/database.py) — _ensure_schema 新增建表语句
- [ToolkitView.vue](frontend/src/views/ToolkitView.vue) — 预览播放器 + 历史列表 UI

## 数据流

```
用户选择文件 → blob URL 预览（本地）
     ↓
点击替换 → 上传到服务端 → FFmpeg 处理 → 写入 SQLite 历史 → 返回下载链接
     ↓
历史列表 ← API 查询 ← SQLite
```

## 文件清理策略

- `temp/audio_replace/` 加入每周清理（周日 24:00），文件最多保留一周
- 历史记录（SQLite）**永久保留**，知道处理过什么
- 文件已被清理的历史记录：前端显示"已过期"，不显示下载按钮
- 手动删除历史时同步删除对应文件

## 边界情况

- 历史记录中的文件可能已被清理或手动删除 → 历史 API 返回 `file_exists: false`，前端显示"已过期"
- 清空历史时同时删除临时目录中的对应文件
- 预览 blob URL 在组件卸载时释放
