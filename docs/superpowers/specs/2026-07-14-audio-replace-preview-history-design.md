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

## 实际代码逻辑补充（2026-07-23 审计）

以下是对比 `py/main.py`、`py/database.py`、`frontend/src/views/ToolkitView.vue` 三份代码后，发现的与设计文档存在差异或文档未覆盖的实现细节。

### 1. 数据库 schema：`created_at` 由 DEFAULT 自动填充

**设计文档**的建表 SQL 中 `created_at TEXT NOT NULL` 没有默认值，暗示由应用层写入。

**实际代码** (`py/database.py` 第 421-429 行)：

```sql
CREATE TABLE IF NOT EXISTS audio_replace_history (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    video_name  TEXT    NOT NULL,
    audio_name  TEXT    NOT NULL,
    output_name TEXT    NOT NULL,
    output_path TEXT    NOT NULL,
    size_mb     REAL    NOT NULL,
    created_at  TEXT    NOT NULL DEFAULT (datetime('now','localtime'))
);
```

`created_at` 使用 `DEFAULT (datetime('now','localtime'))`，由 SQLite 在 INSERT 时自动生成。相应地，写入历史的 INSERT 语句 (`py/main.py` 第 1039 行) **只插入 5 列**（video_name, audio_name, output_name, output_path, size_mb），不包含 `created_at`。

### 2. 文件清理策略：全量清空而非按文件年龄清理（关键差异）

**设计文档**描述：

> temp/audio_replace/ 加入每周清理（周日 24:00），文件最多保留一周

暗示按文件年龄的渐进清理——超过 7 天的文件才删除。

**实际代码** (`py/main.py` 第 6098-6115 行) 的 `_run_weekly_cleanup_once()` 函数：

```python
audio_tmp = os.path.join(_DATA_ROOT, "temp", "audio_replace")
if os.path.isdir(audio_tmp):
    _shutil.rmtree(audio_tmp)       # 整个目录直接删除
    os.makedirs(audio_tmp, exist_ok=True)
```

实际行为是 **`shutil.rmtree` 全量删除整个目录并重建**，不分文件年龄。这意味着：

- 周日清理前一天（周六）生成的文件也会被立即删除，实际保留时间只有 1 天
- 历史记录（SQLite）永久保留，但所有文件路径全部失效 → 所有历史项 `file_exists` 变为 `false` → 前端全部显示"已过期"
- `file_exists` 判断逻辑 (`py/main.py` 第 1089 行 `os.path.isfile(r["output_path"])`) 正确覆盖了这一场景

### 3. 清理执行时间：周日 00:00 而非 24:00

**设计文档**写"周日 24:00"。

**实际代码** (`py/main.py` 第 6276-6296 行) 计算的下次执行时间为周日 `hour=0, minute=0, second=0`，即**周日凌晨 00:00**（周六跨周日的瞬间），而非周日结束时。这与"周日 24:00"有一天的偏差。

### 4. 音频源支持视频文件（设计文档未覆盖）

**设计文档**只提到：

> 音频文件 → `<audio>` 预览（显示播放控件）

**实际前端** (`ToolkitView.vue` 第 143-147 行)：

```html
<input type="file" accept="audio/*,video/*" @change="onAudioSourceFileChange" ... />
<video v-if="audioSourceBlobUrl && audioSourceFile?.type?.startsWith('video/')" ... />
<audio v-else-if="audioSourceBlobUrl" ... />
```

音频源输入接受 `audio/*,video/*`，允许用户直接上传视频文件作为音源——FFmpeg 会自动提取其音频轨道。前端根据文件 MIME 类型决定用 `<video>`（视频源）还是 `<audio>`（纯音频源）预览。这是比设计文档更灵活的实现。

### 5. POST 请求字段名与格式

设计文档以 JSON 思路描述 API。**实际是 FormData 上传**，字段名为：

- `video` — 原视频文件
- `audio` — 新音频源文件（可以是音频或视频）

前端调用 (`ToolkitView.vue` 第 691-692 行)：

```javascript
fd.append('video', audioVideoFile.value)
fd.append('audio', audioSourceFile.value)
```

### 6. 上传临时文件的即时清理（设计文档未提及）

处理成功后，`py/main.py` 第 1027-1031 行立即删除上传的 `_upload_video_xxx` 和 `_upload_audio_xxx` 临时文件，仅保留最终输出。这与 `temp/audio_replace/` 目录的全量周清是不同的清理粒度。

### 7. FFmpeg 处理超时限制

**设计文档未提及。** 实际 `subprocess.run(cmd, ..., timeout=600)` — 10 分钟超时，超时后返回 500 错误。这是一个重要的运维约束。

### 8. 管理员手动触发清理 API（设计文档未提及）

`POST /api/admin/trigger-weekly-cleanup` (`py/main.py` 第 6332-6344 行) 允许 developer 角色手动触发周清理，不必等到周日。权限：仅 `role == "developer"`。

### 9. 定时任务以 daemon 线程启动

`_start_weekly_cleanup()` (`py/main.py` 第 8149 行) 在应用启动时作为 daemon 线程启动，计算到下一个周日 00:00 的等待时间后执行。进程退出时该线程自动终止。

### 10. 下载接口的安全考量

`/api/audio-replace/download?path=...` 直接接受文件系统绝对路径作为 GET 参数（`py/main.py` 第 1062-1068 行），未做路径遍历校验。虽然 `send_file` 本身只发送存在的文件，但暴露了服务器目录结构。设计文档未提及此点。

### 11. 前端 API 封装

前端通过 `frontend/src/api/video.js` 第 11-14 行封装了四个与音频替换相关的 API 调用：

| 封装方法 | HTTP | 路径 |
|---|---|---|
| `videoApi.audioReplace(body)` | POST | `/audio-replace` |
| `videoApi.audioHistoryList()` | GET | `/audio-replace/history` |
| `videoApi.audioHistoryDelete(id)` | DELETE | `/audio-replace/history/{id}` |
| `videoApi.audioHistoryClear()` | DELETE | `/audio-replace/history` |

### 12. 已正确实现的点（设计文档与代码一致）

- 预览用 `URL.createObjectURL()` / `URL.revokeObjectURL()` — `ToolkitView.vue` 第 667-668 行正确释放
- `file_exists: false` 时前端显示"已过期"标签，不显示下载按钮 — `ToolkitView.vue` 第 173-176 行
- 历史 API 返回 100 条上限 (`LIMIT 100`)
- 删除/清空历史时同步删除对应文件
- 组件卸载时释放 blob URL (`onUnmounted`)
