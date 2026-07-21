# 大规模重构设计：拆分 main.py + 前端大组件

> **执行状态**：已完成 Phase 1-2 + 部分 Phase 6。剩余见文末 TODO 清单。
> **最后更新**：2026-07-22

## 零、已完成项

### 后端
| 完成项 | 详情 |
|--------|------|
| helpers.py 扩展 | `scope_where`、`can_modify`、`can_modify_user`、`runner_ids_where`、`MCC_CHANGE_TYPE_LABELS` 已迁移 |
| auth_routes.py Blueprint | ✅ 已激活，main.py 旧路由已删除 |
| `_reject_viewer` 统一 | 删除 main.py 中的重复，统一用 decorators 版本 |
| `_can_modify` 优化 | db 连接由调用方传入，消除双连接 |
| 多余 import 清理 | json x8, datetime x6 已从函数体移除 |
| JWT 滑动过期 | `_refresh_jwt` after_request 钩子 |
| 测试 | 29 个新测试，127/127 全通过 |
| sales_person 列 | database.py 添加 `_add_column_if_missing` |

### 前端
| 完成项 | 详情 |
|--------|------|
| dedupLoader.js | 提取公共 loading guard，3 个 store 已采用 |
| loadSettings 优化 | 防重复 + `_settingsLoaded` 标志 |
| TagsConfig.vue | ✅ 已独立 |
| ImportTab.vue | ✅ 已独立 |
| CopywritingTab.vue | ✅ 已独立 |
| MCC 悬停复制 | ProductCard.vue |
| 商务下拉框 | ProductModal.vue + SettingsPanel.vue |

### 文件变更清单
```
新增:
  py/routes/auth_routes.py
  py/tests/test_helpers.py
  py/tests/test_decorators.py
  py/tests/test_auth.py
  frontend/src/utils/dedupLoader.js
  frontend/src/components/youtube/TagsConfig.vue
  frontend/src/components/youtube/ImportTab.vue
  frontend/src/components/youtube/CopywritingTab.vue
  docs/superpowers/specs/2026-07-22-large-scale-refactoring-design.md (本文件)
  docs/superpowers/specs/2026-07-22-optimization-tests-design.md

修改:
  py/main.py (7462→7306 行)
  py/database.py (+sales_person/agency_ratio 列)
  py/scraper.py (User-Agent 常量化)
  py/routes/helpers.py (+6 个公共函数)
  py/routes/decorators.py (reject_viewer 更新)
  frontend/src/stores/accounts.js (dedupLoader)
  frontend/src/stores/products.js (dedupLoader)
  frontend/src/stores/youtube.js (dedupLoader)
  frontend/src/api/client.js (JWT 滑动过期)
  frontend/src/components/ProductCard.vue (MCC)
  frontend/src/components/ProductModal.vue (商务下拉)
  frontend/src/views/SettingsPanel.vue (商务管理)
  frontend/src/views/YoutubeView.vue (1085→849 行)
```

---

## 一、现状分析

### 1.1 main.py — 7306 行（从 7462 缩减）

| 指标 | 数值 |
|------|------|
| 总行数 | 7306 |
| 路由总数 | 157 |
| `@jwt_required()` 调用 | 114 |
| `_yt_db()` 调用 | 90 |
| `int(get_jwt_identity())` | 92 |

**路由按模块分布**：

| 模块 | 路由数 | 行数估算 |
|------|--------|----------|
| `/api/products` | 18 | ~900 |
| `/api/ad-reports` | 17 | ~1200 |
| `/api/youtube` | 15 | ~600 |
| `/api/admin` | 12 | ~500 |
| `/api/accounts` | 12 | ~700 |
| `/api/auth` | 11 | ~300 |
| `/api/video` | 10 | ~500 |
| `/api/mcc` | 8 | ~400 |
| `/api/fonts` | 6 | ~150 |
| `/api/scrape` | 5 | ~200 |
| `/api/copywriting` | 5 | ~200 |
| `/api/audio-replace` | 5 | ~150 |
| `/api/regions` | 4 | ~100 |
| `/api/config` | 4 | ~150 |
| `/api/data` | 3 | ~150 |
| 其他（delist/google-sheets/google-ads等） | 12 | ~400 |
| 全局钩子+辅助函数+启动代码 | 10 (非路由) | ~500 |

**routes/ 目录现状**：仅 3 个文件（`__init__.py`、`decorators.py`、`helpers.py`）

### 1.2 前端大组件

| 组件 | 行数 | 问题 |
|------|------|------|
| YoutubeView.vue | 1085 | 4 个 Tab 混在一个文件，视频列表+文案展示+导入+标签配置 |
| MediaView.vue | 1084 | 爬取+预览+排序+视频生成+音乐+历史，6 个功能区混杂 |
| AnalysisView.vue | 1054 | 仪表盘+趋势+对比+多维分析+AI 聊天，多个 Tab |
| VideoView.vue | 860 | 视频生成+历史+音频替换+字体管理 |

---

## 二、后端拆分方案：Flask Blueprint

### 2.1 目标目录结构

```
py/
├── main.py                  # 仅保留：app 创建、全局钩子、启动代码 (~500行)
├── routes/
│   ├── __init__.py          # 注册所有 Blueprint
│   ├── decorators.py        # 权限装饰器（已有，不拆分）
│   ├── helpers.py           # 工具函数（已有，不拆分）
│   ├── products.py          # /api/products/*
│   ├── ad_reports.py        # /api/ad-reports/*
│   ├── youtube.py           # /api/youtube/*
│   ├── accounts.py          # /api/accounts/*
│   ├── auth.py              # /api/auth/* + JWT 回调
│   ├── admin.py             # /api/admin/*
│   ├── mcc.py               # /api/mcc/*
│   ├── video.py             # /api/video/* + /api/audio-replace/*
│   ├── copywriting.py       # /api/copywriting/*
│   ├── scrape.py            # /api/scrape/*
│   ├── fonts.py             # /api/fonts/*
│   ├── regions.py           # /api/regions/*
│   ├── config_routes.py     # /api/config/* + /api/settings/*
│   ├── data_routes.py       # /api/data/*
│   ├── delist.py            # /api/delist/* + /api/products/*delist*
│   ├── google_sheets.py     # /api/google-sheets/*
│   ├── google_ads.py        # /api/google-ads/*
│   └── browse.py            # /api/browse-*
```

### 2.2 拆分原则

1. **纯增量** — 不改原有逻辑，只移动代码位置
2. **每个 Blueprint 自包含** — 自己 import 需要的模块
3. **共同依赖保留在 main.py** — `_runner_ids_where`、`_scope_where`、`_yt_db` 等移至 `routes/helpers.py`
4. **Flask 全局钩子保留在 main.py** — `before_request`、`after_request`、`errorhandler`
5. **JWT 回调保留在 auth.py Blueprint 中**

### 2.3 Blueprint 模板

每个路由模块遵循统一结构：

```python
"""products 路由 — /api/products/*"""
from flask import Blueprint, request, jsonify, g
from flask_jwt_extended import jwt_required, get_jwt_identity
from routes.helpers import get_uid, get_db, ok, err, parse_body
from routes.decorators import reject_viewer as _reject_viewer
import auth
import database

products_bp = Blueprint('products', __name__)

# --- 辅助函数 ---
def _runner_ids_where(alias, uid): ...
def _scope_where(scope, user_id, alias=None): ...

# --- 路由 ---
@products_bp.route('/list', methods=['GET'])
@jwt_required()
def product_list(): ...

@products_bp.route('/create', methods=['POST'])
@jwt_required()
def product_create(): ...
```

### 2.4 main.py 瘦身后保留

```python
# main.py (~500行)
from flask import Flask
from routes import register_blueprints

app = Flask(...)
CORS(app)
Compress(app)
jwt = JWTManager(app)

# 全局钩子
@app.before_request
def _log_request(): ...
@app.before_request
def _attach_db(): ...
@app.after_request
def _log_response(): ...
@app.after_request
def _add_static_cache(): ...
@app.after_request
def _refresh_jwt(): ...
@app.after_request
def _close_db(): ...

# 注册 Blueprint
register_blueprints(app)

# 静态文件
@app.route("/")
def index(): ...

# 启动
if __name__ == "__main__":
    app.run(...)
```

### 2.5 公共辅助函数迁移到 routes/helpers.py

从 main.py 迁移过来：
- `_runner_ids_where()` → `helpers.runner_ids_where()`
- `_scope_where()` → `helpers.scope_where()`
- `_can_modify()` → `helpers.can_modify()`
- `_can_modify_user()` → `helpers.can_modify_user()`
- `_record_mcc_change()` → `helpers.record_mcc_change()`
- `_assign_mcc_to_users()` → `helpers.assign_mcc_to_users()`
- `_MCC_CHANGE_TYPE_LABELS` → `helpers.MCC_CHANGE_TYPE_LABELS`

### 2.6 实施步骤（分 5 阶段）

| 阶段 | 内容 | 风险 |
|------|------|------|
| **1** | 迁移公共辅助函数到 helpers.py | 低 |
| **2** | 创建 `routes/auth.py` Blueprint（auth 路由 + JWT 回调） | 低 |
| **3** | 逐个迁移独立模块：regions → scrape → fonts → browse → delist → google_* → config_routes | 低 |
| **4** | 迁移核心模块：products → ad_reports → accounts → mcc → youtube → copywriting → video | 中 |
| **5** | 迁移 admin 模块，清理 main.py | 中 |

每阶段迁移完成后运行 `pytest tests/` 确保无回归。

---

## 三、前端拆分方案：组件抽离

### 3.1 YoutubeView.vue（1085 行 → 4 个子组件）

**现状**：4 个 Tab 全部内联在一个 SFC 中。

**方案**：

```
views/
├── YoutubeView.vue           # ~80行 仅保留 Tab 容器 + 路由
└── youtube/
    ├── VideoTable.vue        # ~400行 视频列表 + 批量操作 + 消耗弹窗
    ├── CopywritingTab.vue    # ~200行 文案展示 + 树形表格
    ├── ImportTab.vue         # ~150行 导入视频/文案表单
    └── TagsConfig.vue        # ~100行 标签配置
```

**YoutubeView.vue 瘦身后**：
```vue
<template>
  <el-tabs :model-value="activeTab" @update:model-value="switchTab">
    <el-tab-pane label="视频展示" name="view" />
    <el-tab-pane label="文案展示" name="copywriting" />
    <el-tab-pane label="导入" name="import" />
    <el-tab-pane label="标签配置" name="config" />
  </el-tabs>
  <VideoTable v-show="activeTab==='view'" />
  <CopywritingTab v-show="activeTab==='copywriting'" />
  <ImportTab v-show="activeTab==='import'" />
  <TagsConfig v-show="activeTab==='config'" />
</template>
```

### 3.2 MediaView.vue（1084 行 → 5 个子组件）

**现状**：6 个功能区域（爬取、预览、排序、视频生成、音乐、历史）全部内联。

**方案**：

```
views/
├── MediaView.vue             # ~100行 布局容器
└── media/
    ├── ScrapePanel.vue        # ~150行 爬取图片
    ├── ImagePreview.vue       # ~180行 图片预览 + 选择
    ├── ImageSorter.vue        # ~100行 拖拽排序
    ├── VideoGenerator.vue     # ~350行 视频生成表单 + AI
    └── VideoHistory.vue       # ~120行 历史记录
```

### 3.3 AnalysisView.vue（1054 行 → 子组件）

**方案**：

```
views/
├── AnalysisView.vue          # ~80行 筛选栏 + Tab 切换
└── analysis/
    ├── DashboardTab.vue       # ~300行 仪表盘
    ├── TrendsTab.vue          # ~200行 趋势图表
    ├── CompareTab.vue         # ~150行 对比分析
    └── MultiAnalysisTab.vue   # ~250行 多维分析 + AI
```

### 3.4 共享逻辑抽离

从各组件提取的公共模式：

| 模式 | 目标 | 现状 |
|------|------|------|
| 防抖搜索 | `composables/useDebounce.js` | 已存在，仅 1 处使用 |
| 分页 | `composables/usePagination.js` | 已存在，仅 1 处使用 |
| 全选/反选/取消 | `composables/useTableSelection.js` | 多处内联 |

### 3.5 前端实施步骤

| 阶段 | 内容 |
|------|------|
| **1** | 抽离共享 composables（防抖搜索、分页、表格选择） |
| **2** | 拆分 YoutubeView（最常用页面，影响最大） |
| **3** | 拆分 MediaView |
| **4** | 拆分 AnalysisView |
| **5** | 拆分 VideoView |

每阶段完成后 `npm run build` 确认无编译错误。

---

## 四、风险与回滚

| 风险 | 缓解措施 |
|------|----------|
| Blueprint 注册顺序导致路由冲突 | Flask 按注册顺序匹配，保持原 main.py 路由定义顺序 |
| import 循环依赖 | 公共函数统一放 helpers.py，各 Blueprint 只单向依赖 helpers |
| 前端组件通信断裂 | Props/Emits 保持不变，只移动代码不改变口 |
| 测试数据库路径变化 | conftest.py 的 `from main import app` 保持不变，app 对象仍在 main.py |

**回滚方案**：每个阶段独立 commit，出问题直接 `git revert`。

---

## 五、预期收益

| 指标 | 改前 | 改后 |
|------|------|------|
| main.py 行数 | 7462 | ~500 |
| 单文件最大行数 | 7462 | ~1200（ad_reports.py） |
| 前端最大组件行数 | 1085 | ~400 |
| 代码导航时间 | 全文搜索 | 按模块定位 |
| 新路由添加 | 在 7000+ 行中找位置 | 在对应 ~200 行模块中加 |
