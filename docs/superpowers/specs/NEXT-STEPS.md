# 继续执行：从上次会话中断处开始

> **给新会话的指令**：阅读本文件，然后按顺序执行每项 TODO。
> **前提**：项目已有 127 个测试全部通过，后端 + 前端均构建正常。
> **运行命令**：
> - 后端测试：`cd py && python -m pytest tests/ -v`
> - 前端构建：`cd frontend && npm run build`

---

## TODO 1：后端 — 创建剩余 16 个 Blueprint 模块

**模式**：参考已完成的 `py/routes/auth_routes.py`。每个 Blueprint 遵循：

```python
"""模块路由"""
from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity
from routes.helpers import get_uid, get_db, ok, err, parse_body, scope_where
from routes.decorators import reject_viewer as _reject_viewer
import auth, database

xxx_bp = Blueprint('xxx', __name__)
# ... routes ...
```

**需要创建的 Blueprint 按 main.py 路由数量**：

| 文件 | URL 前缀 | 路由数 | main.py 中对应位置（grep 找出精确行号） |
|------|----------|--------|------|
| `routes/products.py` | `/api/products` | 18 | `grep "@app.route.*products" py/main.py` |
| `routes/ad_reports.py` | `/api/ad-reports` | 17 | `grep "@app.route.*ad-reports" py/main.py` |
| `routes/youtube.py` | `/api/youtube` | 15 | `grep "@app.route.*youtube" py/main.py` |
| `routes/accounts.py` | `/api/accounts` | 12 | `grep "@app.route.*accounts" py/main.py` |
| `routes/admin.py` | `/api/admin` | 12 | `grep "@app.route.*admin" py/main.py` |
| `routes/mcc.py` | `/api/mcc` | 8 | `grep "@app.route.*mcc" py/main.py` |
| `routes/video.py` | `/api/video` + `/api/audio` | 10+5 | 含音频替换 |
| `routes/copywriting.py` | `/api/copywriting` | 5 | `grep "@app.route.*copywriting" py/main.py` |
| `routes/scrape.py` | `/api/scrape` | 5 | `grep "@app.route.*scrape" py/main.py` |
| `routes/fonts.py` | `/api/fonts` | 6 | `grep "@app.route.*font" py/main.py` |
| `routes/regions.py` | `/api/regions` | 4 | `grep "@app.route.*regions" py/main.py` |
| `routes/config_routes.py` | `/api/config` + `/api/settings` | 4+2 |  |
| `routes/data_routes.py` | `/api/data` | 3 |  |
| `routes/delist.py` | `/api/delist` + 部分 products | 2+4 | 含掉包检测 |
| `routes/google_sheets.py` | `/api/google-sheets` | 3 |  |
| `routes/google_ads.py` | `/api/google-ads` | 2 |  |
| `routes/browse.py` | `/api/browse-*` | 3 |  |

**每模块执行步骤**：
1. `grep -n "@app.route.*<模块前缀>" py/main.py` 找到路由行号
2. 读取对应的函数代码块
3. 复制到 Blueprint 文件（改 `@app` 为 `@xxx_bp`，改相对路径）
4. 在 `py/main.py` 中 `app.register_blueprint(xxx_bp, url_prefix="/api/xxx")`
5. 删除 main.py 中旧代码
6. `pytest tests/` 确认通过
7. `git commit`

---

## TODO 2：后端 — main.py 瘦身收尾

所有 Blueprint 注册完毕后：
1. 删除 main.py 中残留的辅助函数定义（已迁移到 helpers.py 的版本）
2. 删除 `_can_modify_user`（用 helpers.can_modify_user 替代）
3. main.py 最终保留：Flask app 创建、全局钩子（before/after_request）、静态文件路由、favicon、启动代码
4. 目标行数：~500 行

---

## TODO 3：前端 — 提取 YoutubeView VideoTable (~850行)

YoutubeView 目前 849 行，大部分是视频展示 Tab。

**步骤**：
1. 读取 `frontend/src/views/YoutubeView.vue` 的 view tab 部分（模板 ~14-194行，脚本 分散在各处）
2. 创建 `frontend/src/components/youtube/VideoTable.vue`
3. 提取：视频列表表格、筛选栏、批量编辑、消耗弹窗、视频编辑弹窗
4. 保持相同的 store 引用（`useYoutubeStore`、`useAuthStore`）
5. YoutubeView 中 `import VideoTable from ...` 并替换模板
6. `npm run build` 确认
7. 目标：YoutubeView ~200 行

---

## TODO 4：前端 — 拆分 MediaView (1084行)

**拆分为**：
- `frontend/src/components/media/ScrapePanel.vue` (~150行)
- `frontend/src/components/media/VideoGenerator.vue` (~350行)
- `frontend/src/components/media/VideoHistory.vue` (~120行)
- `frontend/src/components/media/ImageSorter.vue` (~100行)

**步骤**：同 YoutubeView 模式，逐个提取 → 替换 → 构建验证 → commit。

---

## TODO 5：前端 — 拆分 AnalysisView (1054行)

**拆分为**：
- `frontend/src/components/analysis/DashboardTab.vue` (~300行)
- `frontend/src/components/analysis/TrendsTab.vue` (~200行)
- `frontend/src/components/analysis/CompareTab.vue` (~150行)
- `frontend/src/components/analysis/MultiAnalysisTab.vue` (~250行)

---

## TODO 6：推广 composables

`frontend/src/composables/useDebounce.js` 和 `usePagination.js` 已存在但未广泛使用：
1. grep 查找所有 `setTimeout(fn, 300)` 搜索防抖 → 替换为 useDebounce
2. grep 查找所有手动分页逻辑 → 替换为 usePagination

---

## 验证清单（每步完成后执行）

```bash
# 后端语法
cd py && python -c "import py_compile; py_compile.compile('main.py', doraise=True)"

# 后端测试（目标：127+ passed, 0 failed）
cd py && python -m pytest tests/ -v

# 前端构建
cd frontend && npm run build
```

---

## 参考文件

- 设计文档：`docs/superpowers/specs/2026-07-22-large-scale-refactoring-design.md`
- 测试设计：`docs/superpowers/specs/2026-07-22-optimization-tests-design.md`
- 已完成的后端 Blueprint：`py/routes/auth_routes.py`
- 已完成的前端组件：`frontend/src/components/youtube/TagsConfig.vue`、`ImportTab.vue`、`CopywritingTab.vue`
- 公共工具：`py/routes/helpers.py`、`frontend/src/utils/dedupLoader.js`
