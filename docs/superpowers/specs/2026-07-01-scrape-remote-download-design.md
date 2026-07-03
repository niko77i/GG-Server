# 图片爬取 & 视频生成 — 远程用户支持

## 问题

远程用户（Tailscale 访问）用不了爬取和视频生成功能：

1. **ScrapeView**：📂 按钮 `_is_local_request()` → 403；手填路径不知道填什么 → 500
2. **VideoView**：同样要填服务器路径；输出视频也在服务器上，远程拿不到
3. **完整链路断裂**：爬取 → 生成视频 → 获取结果 全流程远程用户都无法使用

## 方案：服务器默认目录 + 下载

不改变核心流程（图片和视频都存在服务器上），让远程用户不需要手动填路径。

### 1. 爬取：默认保存目录

**后端**：新增配置 `SCRAPE_DEFAULT_DIR`，默认为 `temp/scraped_images/`（项目相对路径）。
→ `/api/scrape` 当 `save_dir` 为空时自动使用默认目录。

**前端**：页面加载时 `saveDir` 自动填入默认目录；📂 按钮保留（仅本机/管理员可用）。

```
远程用户打开页面 → saveDir 已填好 → 粘贴链接 → 爬取 → 图片存在服务器默认目录
```

### 2. 爬取完成后：下载图片

**后端**：新增 `/api/scrape/download/<pkg_name>` 接口，将对应包名文件夹下的图片打包成 zip 返回下载。

**前端**：爬取成功后显示"📥 下载图片"按钮 → 点击触发浏览器下载 zip。

### 3. 视频生成：沿用现有逻辑

视频生成接口 `/api/video/generate` 没有本地限制，只需要路径正确：

- 爬取后 `saved_path` 存入 `sessionStorage` → 点"🎬 生成视频" → `videoDir` 自动填好 → 扫描 → 生成
- 视频输出也保存到服务器，远程用户可下载

**后端**：视频生成成功后，输出路径在响应中返回。前端可提供下载。

### 4. 视频生成完成后：下载视频

新增 `/api/video/download` 接口，根据输出路径返回视频文件下载。

**前端**：视频生成完成后显示"📥 下载视频"按钮。

## 改动清单

### 后端 (`py/main.py`)

| 改动 | 说明 |
|---|---|
| 全局常量 `SCRAPE_DEFAULT_DIR` | 默认 `temp/scraped_images` |
| `/api/scrape`：`save_dir` 为空时用默认目录 | save_dir 改为可选 |
| `/api/scrape/download/<pkg_name>`（新） | 打包文件夹为 zip 下载 |
| `/api/video/download`（新） | 根据路径返回视频文件下载 |

### 前端

| 文件 | 改动 |
|---|---|
| `ScrapeView.vue` | onMounted 自动填入默认 saveDir；爬取成功后显示下载按钮 |
| `VideoView.vue` | 视频生成完成后显示下载按钮 |

## 不需要改的

- 📂 browse 系列接口（之前已放开给管理员）
- 视频生成流程（逻辑不变，路径从 scrape 自动传递）

## 备注

- `SCRAPE_DEFAULT_DIR` 路径在服务器上，应是 `DATA_ROOT`（即 `DATA_DIR`）下的子目录
- 默认目录和 `_DATA_ROOT`（在 config.py 中配置的 DATA_DIR）保持一致性
