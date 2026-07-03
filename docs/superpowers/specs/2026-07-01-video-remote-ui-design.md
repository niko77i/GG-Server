# 视频生成页 — 远程用户 UI 改造

## 需求

远程用户（通过 Tailscale 访问）生成视频时，所有路径操作改为服务端托管，不需要填任何文件路径。爬取图片和生成视频均按用户区分目录。

### 目录结构（按用户区分）

```
temp/
  scraped_images/
    <用户display_name>/           ← 每个用户独立目录
      com.spotify.music/          ← 爬取的图片
        包logo/
      com.example.app/
    ai/
      <用户display_name>/         ← 生成的视频按用户分
        com.spotify.music.mp4
  music/                          ← 共用音乐库（不清理）
    bg1.mp3
    bg2.wav
```

### 远程用户 vs 本机用户对比

| 功能 | 本机用户 | 远程用户 |
|---|---|---|
| 图片目录 | 输入框 + 📂 + 🔍 | 下拉框选择已爬取包 → 自动扫描 |
| 输出路径 | 输入框 + 📂 | 隐藏，自动生成 |
| 背景音乐 | 输入框 + 📂 | 下拉框选 + 上传 + 选中自动播放 + ⏹停止 |
| 下载视频 | 无 | 📥 下载按钮 |

### 权限

- `/api/scrape` 和 `/api/video/generate` 加 `@jwt_required()`（所有登录用户可用，不限制角色）
- 目的是获取用户身份来区分目录

## 后端改动

### 接口改动

**1. `/api/scrape` — save_dir 改为用户专属目录**

加 `@jwt_required()`，取用户 `display_name`，默认保存到：
```
temp/scraped_images/<display_name>/<包名>/
```

**2. `GET /api/scrape/packages`（新）— 列出当前用户已爬取包**

加 `@jwt_required()`，遍历当前用户的 `temp/scraped_images/<display_name>/` 子目录。
```
返回: { packages: [{ name, path, image_count }] }
```

**3. `GET /api/video/music-list`（新）— 列出背景音乐**
```
返回: { files: [{ name, path }] }
```
遍历 `temp/music/`。

**4. `POST /api/video/upload-music`（新）— 上传背景音乐**

multipart 上传，保存到 `temp/music/`。返回 `{ name, path }`。

**5. `GET /api/audio`（新）— 音频流服务**

`send_file(path)`，供前端 `<audio>` 元素预览播放。

**6. `/api/video/generate` — 加 @jwt_required()**

输出路径由前端传（已自动填好），后端不变。

### 定时清理

每周日 24:00 清理 `temp/scraped_images/` 下所有用户目录及 `ai/` 子目录。`temp/music/` 保留不清理。

## 前端改动

### ScrapeView.vue（补充）

- `saveDir` 远程用户默认留空（后端自动用用户专属目录）
- 之前已加 📥 下载按钮 ✅

### VideoView.vue

**图片目录（远程）**

```
┌─ 选择已爬取包 ──────────────────────────┐
│ [下拉框: com.spotify.music (5张)]  ▼   │
└─────────────────────────────────────────┘
```
选择后自动调用 `scanDir()`。

**输出路径（远程）**
- 隐藏
- 自动计算：由 `scanDir` 的逻辑生成

**背景音乐（远程）**

```
┌─ 背景音乐 ──────────────────────────────────┐
│ [下拉框: 选音乐或留空]  ▼  [⏹ 停止]        │
│ [选择文件] [上传到服务器]                     │
└──────────────────────────────────────────────┘
```

交互：
- 选中 → 自动播放，⏹ 按钮出现
- 点 ⏹ → 停止
- 切换/清空 → 停止上一个
- 上传 → 刷新下拉框列表
- 隐藏 `<audio>` 元素实现播放

**关键逻辑**
- `isRemote = computed(() => !isLocalhost())`
- `v-if="isRemote"` / `v-else` 切换 UI
- `onMounted` 远程时加载 packages、music 列表
- bridge 桥接有值时优先选中对应包
