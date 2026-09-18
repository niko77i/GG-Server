# GG-Server TikTok（TT）产品管理模块设计文档

> 日期：2026-09-18
> 状态：设计确认中（待实现）
> 范围：第一阶段 —— 仅 TT 产品管理（不含数据提取、做表）

---

## 一、需求概述

GG-Server 当前支持 Google Ads (GG) 与 Facebook (FB) 两个平台。现需新增 TikTok (TT) 平台，第一阶段只做「产品管理」大模块，功能对标 GG 产品管理的完整度（FB 目前只有基础展示，不作为对标基准）。

核心要点：

1. **组织结构**：TT 与 FB 类似，`BC`（Business Center 商务中心）即 FB 的 `BM`，账户侧结构后续（第二阶段）实现。
2. **产品管理功能对标 GG**：产品 CRUD、投放对象管理、在跑人员、BC 关联、合并、批量导入、掉包检测、素材关联。
3. **投放对象有两种**：
   - **跑包（package）**：安卓包（Google Play），字段对标 GG 包，功能**完全对标 GG**（含掉包检测、粘贴解析）。
   - **PWA 链接（pwa）**：网页应用链接，**先实现基础版**（增删改查），后续继续完善。
4. **投放对象建模**：单表 + `type` 字段区分，前端一个表格混排，用 type 标签区分。
5. **用户管理**：本轮同步支持 TT 平台用户（创建用户可选 GG/FB/TT，供「在跑人员」选择）。

---

## 二、技术方案

**采用方案 A：独立复制（FB 模式）**，即新建 `tt_*` 独立表 + 独立路由 + 独立页面，对 GG 代码零侵入（符合纯增量原则）。

```
共享层（最小改动，仅平台三值化）：
├── users 表 platform 字段：'gg' | 'fb' → 扩为 'gg' | 'fb' | 'tt'
├── auth 层：create_user / list_users / update_user / auth.me 支持 'tt'
├── 前端 auth store：isTtUser / effectivePlatform 三值
├── 侧边栏：平台切换 [GG][FB][TT]
└── 选项表（regions / sales_persons / account_statuses）：加 'tt' 数据（复用 platform 列）

TT 独立层（全新文件）：
├── 后端：routes/tt_routes.py + database.py 新增建表
├── 掉包检测：复用 delist_checker.py 核心逻辑（参数化平台）
└── 前端：views/tt/ + api/tt.js + stores/tt.js + 路由
```

---

## 三、数据库设计

### 3.1 平台三值化（现有表改动）

```sql
-- users.platform 已存在（DEFAULT 'gg'），值域从 ('gg','fb') 扩展为 ('gg','fb','tt')
-- 无需改表结构，仅代码层校验放宽
```

选项表（`regions` / `sales_persons` / `account_statuses`）已带 `platform` 列，直接插入 `platform='tt'` 数据即可，无需建表。参考现有 `_copy_gg_options_to_fb` 迁移，新增 `_copy_gg_options_to_tt`。

### 3.2 TT 新表

```sql
-- ===================== BC 管理（对标 FB 的 BM / GG 的 MCC） =====================
CREATE TABLE tt_bcs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    bc_id TEXT NOT NULL UNIQUE,          -- BC ID（纯数字校验）
    note TEXT DEFAULT '',
    status TEXT DEFAULT 'normal',        -- normal / banned
    owner_id INTEGER REFERENCES users(id),
    deleted_at TEXT DEFAULT NULL,        -- 软删除
    created_at TEXT DEFAULT (datetime('now','localtime')),
    updated_at TEXT DEFAULT (datetime('now','localtime'))
);
CREATE INDEX IF NOT EXISTS idx_tt_bcs_owner ON tt_bcs(owner_id);
CREATE INDEX IF NOT EXISTS idx_tt_bcs_status ON tt_bcs(status);

-- ===================== TT 产品（对标 GG 的 products，bc_id 替代 mcc_id） =====================
CREATE TABLE tt_products (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    product_name TEXT NOT NULL,
    kpi TEXT DEFAULT '',
    region TEXT DEFAULT '',
    status TEXT DEFAULT 'active',        -- active / paused
    bc_id INTEGER REFERENCES tt_bcs(id),
    sales_person_id INTEGER REFERENCES sales_persons(id),
    agency_ratio REAL DEFAULT 0,
    customer TEXT DEFAULT '',
    owner_id INTEGER REFERENCES users(id),
    is_archived INTEGER DEFAULT 0,
    created_at TEXT DEFAULT (datetime('now','localtime')),
    updated_at TEXT DEFAULT (datetime('now','localtime'))
);
CREATE INDEX IF NOT EXISTS idx_tt_products_owner ON tt_products(owner_id);
CREATE INDEX IF NOT EXISTS idx_tt_products_region ON tt_products(region);
CREATE INDEX IF NOT EXISTS idx_tt_products_bc ON tt_products(bc_id);

-- ===================== 在跑人员 =====================
CREATE TABLE tt_product_runners (
    product_id INTEGER NOT NULL REFERENCES tt_products(id) ON DELETE CASCADE,
    user_id INTEGER NOT NULL REFERENCES users(id),
    PRIMARY KEY (product_id, user_id)
);
CREATE INDEX IF NOT EXISTS idx_tt_product_runners_user ON tt_product_runners(user_id);

-- ===================== 投放对象（单表 + type 区分 package / pwa） =====================
CREATE TABLE tt_packages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    product_id INTEGER NOT NULL REFERENCES tt_products(id) ON DELETE CASCADE,
    type TEXT DEFAULT 'package',         -- 'package'（跑包）| 'pwa'（PWA 链接）
    series_name TEXT DEFAULT '',         -- 系列名（package 拼接自定义；pwa 直接填不拼接）
    package_name TEXT DEFAULT '',        -- 包名（仅 package 填，pwa 为空字符串）
    url TEXT DEFAULT '',
    status TEXT DEFAULT '',
    created_at TEXT DEFAULT (datetime('now','localtime')),
    updated_at TEXT DEFAULT (datetime('now','localtime'))
);
CREATE INDEX IF NOT EXISTS idx_tt_packages_product ON tt_packages(product_id);
CREATE INDEX IF NOT EXISTS idx_tt_packages_type ON tt_packages(type);

-- ===================== 掉包检测（仅跑包 type='package'） =====================
CREATE TABLE tt_delist_checks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    package_id INTEGER NOT NULL REFERENCES tt_packages(id) ON DELETE CASCADE,
    is_delisted INTEGER DEFAULT 0,
    checked_at TEXT DEFAULT (datetime('now','localtime')),
    UNIQUE(package_id)
);
CREATE INDEX IF NOT EXISTS idx_tt_delist_checks_package ON tt_delist_checks(package_id);

-- ===================== 素材关联（对标 GG 的 product_assets，关联共享视频库 videos） =====================
CREATE TABLE tt_product_assets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    product_id INTEGER NOT NULL REFERENCES tt_products(id),
    video_id TEXT NOT NULL,
    video_owner_id INTEGER NOT NULL DEFAULT 1,
    added_by INTEGER REFERENCES users(id),
    added_at TEXT DEFAULT (datetime('now','localtime')),
    UNIQUE(product_id, video_id)
);
CREATE INDEX IF NOT EXISTS idx_tt_product_assets_product ON tt_product_assets(product_id);
CREATE INDEX IF NOT EXISTS idx_tt_product_assets_video ON tt_product_assets(video_id);
```

### 3.3 表关系图

```
tt_bcs (BC 商务中心)
   │ 1对多
tt_products ──1对多── tt_packages (type: package | pwa)
   │                      │ 1对1（仅 package）
   │ 多对多                tt_delist_checks
tt_product_runners (在跑人员)

tt_products ──1对多── tt_product_assets ── 关联 videos
```

### 3.4 投放对象字段对照

| 字段 | 跑包（package） | PWA 链接（pwa） |
|------|----------------|-----------------|
| type | `package` | `pwa` |
| series_name | ✅（前缀+粘贴拼接） | ✅（直接填，不拼接） |
| package_name | ✅ 必填 | ❌（空字符串） |
| url | ✅ | ✅ |
| status | ✅ | ✅ |
| 掉包检测 | ✅ 有 | ❌ 无 |

---

## 四、API 路由设计（新建 `py/routes/tt_routes.py`）

所有路由挂载 `/api/tt/*`，均需 `@jwt_required()` + `@tt_required`。

### 4.1 产品管理

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | /api/tt/products/list | 产品列表（分页/搜索/region/status/runner 筛选） |
| GET | /api/tt/products/runner-products | 当前用户在跑产品（下拉用） |
| POST | /api/tt/products/create | 创建产品（含投放对象、在跑人员、BC） |
| PUT | /api/tt/products/:pid | 更新产品 |
| DELETE | /api/tt/products/:pid | 软删除（is_archived=1） |
| POST | /api/tt/products/:pid/restore | 恢复 |
| GET | /api/tt/products/:pid/detail | 详情（含投放对象+在跑人员+BC） |
| POST | /api/tt/products/merge | 合并产品 |
| PUT | /api/tt/products/:pid/runners | 更新在跑人员 |

### 4.2 投放对象（跑包 + PWA，单表）

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | /api/tt/products/:pid/packages | 添加投放对象（type 区分） |
| PUT | /api/tt/packages/:pkg_id | 更新投放对象 |
| DELETE | /api/tt/packages/:pkg_id | 删除投放对象 |
| POST | /api/tt/packages/batch-delete | 批量删除 |

### 4.3 BC 管理（简单 CRUD）

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | /api/tt/bcs/list | BC 列表（分页/status 筛选） |
| POST | /api/tt/bcs/create | 创建 BC |
| PUT | /api/tt/bcs/:bid | 更新 BC |
| DELETE | /api/tt/bcs/:bid | 软删除 |
| GET | /api/tt/bcs/options | BC 下拉选项（status='normal'） |

### 4.4 高级功能

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | /api/tt/products/:pid/check-delist | 手动掉包检测（仅跑包） |
| GET | /api/tt/products/delist-status | 掉包状态查询 |
| POST | /api/tt/products/import-text | 粘贴文本解析成投放对象列表（第一阶段仅跑包 Google Play 链接） |
| GET | /api/tt/products/:pid/assets | 素材列表 |
| POST | /api/tt/products/:pid/assets | 添加素材 |
| DELETE | /api/tt/products/:pid/assets/:video_id | 删除素材 |

### 4.5 用户查询

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | /api/tt/users | 返回 TT 平台用户（developer 也含），供「在跑人员」选择器 |

---

## 五、前端设计

### 5.1 路由（router/index.js 新增）

```js
{
  path: '/tt',
  redirect: '/tt/products',
  meta: { platform: 'tt' }
},
{
  path: '/tt/products',
  component: () => import('../views/tt/TtProductPanel.vue'),
  meta: { platform: 'tt', title: 'TT产品管理' }
},
{
  path: '/tt/bcs',
  component: () => import('../views/tt/TtBcPanel.vue'),
  meta: { platform: 'tt', title: 'BC管理' }
},
```

### 5.2 页面文件清单

| 文件 | 功能 |
|------|------|
| `views/tt/TtProductPanel.vue` | 产品列表 + 产品弹窗（投放对象子表、在跑人员、BC）+ 合并/批量导入/掉包检测 |
| `views/tt/TtBcPanel.vue` | BC 列表 + 弹窗（简单 CRUD） |
| `api/tt.js` | TT API 模块 |
| `stores/tt.js` | TT 状态管理 |

### 5.3 产品弹窗（对标 GG 交互）

- **产品字段**：产品名、KPI、地区（复用选项表）、商务、代投比例、客户、BC（下拉）、状态
- **在跑人员**：el-select multiple，从 `/api/tt/users` 加载
- **投放对象子表**：单表混排，列 = 类型标签（跑包/PWA）+ 系列名 + 包名（PWA 空）+ 链接 + 状态 + 操作
  - 跑包行：显示「跑包」标签，有「掉包检测」操作
  - PWA 行：显示「PWA」标签，无掉包检测
  - 添加投放对象时，先选 type，再填对应字段

### 5.4 投放对象粘贴解析（import-text）

对标 GG 的 `AddPackageModal`（粘贴文本 → 解析出投放对象列表）：
- **跑包（第一阶段）**：粘贴 Google Play 链接文本，解析出 series_name + package_name + url
- **PWA（后续）**：粘贴 PWA 链接文本解析，第一阶段 PWA 仅手工增删改查

### 5.5 侧边栏

- `AppSidebar.vue`：developer 平台切换从 `[GG][FB]` 扩为 `[GG][FB][TT]`
- TT 菜单：产品管理 + BC 管理

---

## 六、用户管理 TT 支持（平台三值化）

### 6.1 后端改动

| 位置 | 改动 |
|------|------|
| `py/auth.py` `create_user()` | platform 参数值域放宽为 `('gg','fb','tt')` |
| `py/auth.py` `list_users()` | 支持 `?platform=tt` 筛选 |
| `py/auth.py` `update_user()` | 支持更新 platform='tt'，仅 developer |
| `py/main.py` 用户创建校验 | `platform not in ("gg","fb")` → 加 `'tt'` |
| `py/main.py` 用户更新校验 | 同上 |
| `py/routes/auth_routes.py` `/api/auth/names` | 返回 platform 字段（已有），无需改 |

### 6.2 前端改动

| 位置 | 改动 |
|------|------|
| `stores/auth.js` | 加 `isTtUser` getter；`effectivePlatform` 三值；登录后 platform 判断 |
| `router/index.js` | 首页跳转加 `platform === 'tt'` 分支；平台守卫三值 |
| `views/UserManageView.vue` | 创建用户平台下拉加 `TT` 选项 |
| `components/AppSidebar.vue` | 平台切换三值 |

### 6.3 装饰器

`py/routes/decorators.py` 新增 `tt_required`（复用 `require_platform('tt')`）。

---

## 七、掉包检测说明

- **跑包（type='package'）**：复用 `py/delist_checker.py` 核心逻辑（代理 IP 访问 Google Play 检测包是否下架），结果写入 `tt_delist_checks`。GG 的 `delist_checks` 表不动。
- **PWA（type='pwa'）**：不做掉包检测。
- 检测调度：第一阶段仅支持手动触发（`check-delist`），定时自动检测后续阶段接入。

---

## 八、涉及文件清单

### 新建文件

| 文件 | 说明 |
|------|------|
| `docs/superpowers/specs/2026-09-18-tt-product-management-design.md` | 本文档 |
| `py/routes/tt_routes.py` | TT 产品管理所有 API 路由 |
| `frontend/src/views/tt/TtProductPanel.vue` | TT 产品管理 |
| `frontend/src/views/tt/TtBcPanel.vue` | BC 管理 |
| `frontend/src/api/tt.js` | TT API 模块 |
| `frontend/src/stores/tt.js` | TT 状态管理 |

### 修改文件

| 文件 | 改动 |
|------|------|
| `py/database.py` | 新增 TT 建表 + `_copy_gg_options_to_tt` 迁移 |
| `py/main.py` | 注册 tt_bp；用户创建/更新 platform 校验加 'tt'；GG 平台守卫跳过 `/api/tt/*` |
| `py/auth.py` | create_user/list_users/update_user 支持 'tt' |
| `py/routes/decorators.py` | 新增 `tt_required` |
| `frontend/src/router/index.js` | TT 路由 + 三值平台守卫 + 首页跳转 |
| `frontend/src/components/AppSidebar.vue` | 平台切换三值 + TT 菜单 |
| `frontend/src/stores/auth.js` | isTtUser / effectivePlatform 三值 |
| `frontend/src/views/UserManageView.vue` | 创建用户平台加 TT 选项 |

### 复用（不修改）

- `py/delist_checker.py`（抽取核心逻辑供 TT 调用，不改 GG 行为）
- `py/proxy_pool.py`（代理池）
- 选项表 `regions` / `sales_persons` / `account_statuses`（加 tt 数据，不改表结构）

---

## 九、风险与后续阶段

### 9.1 风险点

1. **平台二值硬编码**：代码中存在 `isFbUser`/`isGgUser` 二值 getter、`platform === 'fb'` 判断、`platform not in ("gg","fb")` 校验等，需系统性排查，遗漏会导致权限混乱。
2. **掉包检测复用**：`delist_checker.py` 现有逻辑针对 GG 的 `packages` 表，需确认可参数化（传入包 URL + 目标表）而不改动 GG 行为。

### 9.2 后续阶段（不在本轮）

- 第二阶段：TT 账户管理（BC 完整管理 + 广告账户，对标 GG）
- 第三阶段：TT 数据提取（TikTok 报表粘贴解析，格式 ≠ FB）
- 第四阶段：TT 做表写表（Google Sheets，列布局待定）
- PWA 链接高级功能完善（掉包检测、更多字段等）

---

## 十、已确定的设计决策

1. **素材关联复用共享视频库**：`tt_product_assets` 复用 `videos` 表（与 GG 的 `product_assets` 一致），TT 无独立视频库。
2. **PWA 第一阶段仅基础**：PWA 链接第一阶段只做手工增删改查（series_name + url + status），粘贴解析 PWA、掉包检测等「完善」功能留到后续阶段。
