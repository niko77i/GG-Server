# YouTube 视频管理功能 — 设计规格

**日期**: 2026-06-09
**状态**: 设计完成，待审核

---

## 1. 概述

在左侧侧边栏新增「📺 视频管理」标签页，用于管理 YouTube 视频链接。支持导入、分类、播放。

## 2. 面板结构

```
┌──────────────┬──────────────────────────────────────────┐
│  Sidebar     │  视频管理面板                              │
│              │  ┌─ 标签页 ──────────────────────────┐    │
│  📥 图片爬取  │  │ [ 📺 视频展示 ] [ ➕ 导入视频 ] │    │
│  🎬 AI 视频  │  └──────────────────────────────────┘    │
│  🎵 音频替换  │                                          │
│  📺 视频管理  │  (根据选中的子标签页显示不同内容)           │
│              │                                          │
└──────────────┴──────────────────────────────────────────┘
```

## 3. 子标签页 1：视频展示

- 从 `temp/youtube_videos.json` 加载已保存的视频列表
- 左侧显示视频列表（可滚动），每个条目显示：**名称、链接（截断）、地区标签、帧类型标签**
- 点击列表中的视频 → 右侧嵌入 YouTube iframe 播放器
- 播放器下方显示：完整链接、名称、地区、帧类型
- 视频列表支持按地区/帧类型筛选

## 4. 子标签页 2：导入视频

- 多行文本输入框，用于粘贴 YouTube 链接（每行一个）
- 地区下拉框：巴西 / 菲律宾 / 孟加拉 / 印尼 / 东南亚通用 / 通用
- 帧类型下拉框：融帧 / 非融帧
- 保存按钮 → 存储到本地 `temp/youtube_videos.json`
- 保存成功自动刷新视频展示列表

## 5. 数据存储

**位置**: `temp/youtube_videos.json`

```json
[
  {
    "id": "mpfKMV9PCKs",
    "url": "https://www.youtube.com/watch?v=mpfKMV9PCKs",
    "title": "视频标题",
    "region": "巴西",
    "frame_type": "融帧",
    "imported_at": "2026-06-09 12:00"
  }
]
```

- YouTube 视频 ID 从 URL 中提取
- 视频标题通过 YouTube oEmbed API 获取（`https://www.youtube.com/oembed?url=...`）
- 持久化：开发模式存在 `temp/`，EXE 模式存在 EXE 同目录

## 6. 后端 API

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/youtube/import` | 批量导入视频链接，提取 ID + 标题 |
| GET | `/api/youtube/list` | 返回所有已保存的视频 |
| POST | `/api/youtube/delete` | 删除指定视频 |
| GET | `/api/youtube/title?url=` | 获取视频标题 |

## 7. 文件变更

| 文件 | 变更 |
|------|------|
| `index.html` | 新增侧边栏项 + 视频管理面板 + 子标签页 |
| `css/style.css` | 新增视频面板样式（列表、播放器、筛选栏） |
| `js/youtube.js` | 新建，视频管理前端逻辑 |
| `py/main.py` | 新增 4 个 API 端点 |
| `js/app.js` | switchTab 增加 youtube 支持 |

## 8. 子标签页切换

视频管理面板内部有自己的子标签页（视频展示 / 导入视频），与外层侧边栏标签页独立。使用类似 `switchTab` 的模式，新增 `switchYoutubeTab(subtab)` 函数。

## 9. YouTube URL 提取

支持以下格式：
- `https://www.youtube.com/watch?v=VIDEO_ID`
- `https://youtu.be/VIDEO_ID`
- `https://www.youtube.com/embed/VIDEO_ID`
- `https://m.youtube.com/watch?v=VIDEO_ID`
- 带参数的 `?v=ID&t=123&list=...`

## 10. 验证

1. 切换到 📺 视频管理标签页
2. 点击「➕ 导入视频」，粘贴 YouTube 链接，选地区+帧类型，保存
3. 切换到「📺 视频展示」，确认视频出现在列表中
4. 点击视频 → 右侧嵌入播放器可播放
5. 切换地区/帧类型筛选，确认列表过滤正确
