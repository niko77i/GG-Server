# GG-Server Facebook 平台支持设计文档

> 日期：2026-07-30
> 状态：设计完成，待确认

## 一、需求概述

GG-Server 当前仅支持 Google Ads (GG)，现需新增 Facebook (FB) 广告管理功能。核心改动：

1. **用户平台划分**：用户分为 GG 和 FB 两类，仅 developer 可访问双平台
2. **FB 独立页面**：产品管理、账户管理、账户BM管理、像素BM管理、数据提取、数据管理（不复用 GG 页面）
3. **数据提取**：从 FB 广告后台复制的数据透视表粘贴解析
4. **结构差异**：
   - FB 有 BM（Business Manager）而非 MCC，分为**账户BM**和**像素BM**两种
   - 账户BM 下有多个账户，像素BM 下有多个像素
   - 产品可有多条"线"，一个产品可多个在跑 BM（账户BM）
   - 一条线对应一个**像素**（非像素BM）

---

## 二、技术方案

采用**混合模式**：FB 新建独立表/路由/页面，GG 代码只做必要的权限扩展。

```
共享层（最小改动）：
├── users 表 + platform 字段
├── auth store + platform getter
├── 侧边栏：根据 platform 切换菜单
├── 路由守卫：根据 platform 限制访问
├── 数据分析：直接复用（数据按用户隔离）
├── 用户管理：创建用户时选 GG/FB
└── 选项表（地区/商务/状态等）：GG/FB 共用

FB 独立层（全新文件）：
├── 后端：routes/fb_routes.py + database.py 新增建表
└── 前端：新 views / api / stores / 路由
```

---

## 三、数据库设计

### 3.1 现有表改动

```sql
-- users 表新增平台字段
ALTER TABLE users ADD COLUMN platform TEXT DEFAULT 'gg';
-- 值: 'gg' | 'fb'，developer 为 NULL 或特殊值表示双平台
```

### 3.2 FB 新表

```sql
-- ===================== BM 管理 =====================
CREATE TABLE fb_bms (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    bm_id TEXT NOT NULL UNIQUE,          -- BM ID（纯数字校验）
    note TEXT DEFAULT '',                -- 备注（区分账户BM/像素BM）
    status TEXT DEFAULT 'normal',        -- normal / banned
    owner_id INTEGER REFERENCES users(id),
    deleted_at TEXT DEFAULT NULL,        -- 软删除
    created_at TEXT DEFAULT (datetime('now','localtime')),
    updated_at TEXT DEFAULT (datetime('now','localtime'))
);
CREATE INDEX IF NOT EXISTS idx_fb_bms_owner ON fb_bms(owner_id);
CREATE INDEX IF NOT EXISTS idx_fb_bms_status ON fb_bms(status);

-- ===================== FB 账户 =====================
CREATE TABLE fb_accounts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    account_id TEXT NOT NULL UNIQUE,     -- 账户ID（纯数字校验）
    timezone TEXT DEFAULT '',
    status_id INTEGER REFERENCES account_statuses(id),  -- 复用 GG 状态选项表
    acquired_date TEXT DEFAULT (date('now','localtime')),
    status_changed_date TEXT DEFAULT '',
    owner_id INTEGER REFERENCES users(id),
    deleted_at TEXT DEFAULT NULL,
    created_at TEXT DEFAULT (datetime('now','localtime')),
    updated_at TEXT DEFAULT (datetime('now','localtime'))
);
CREATE INDEX IF NOT EXISTS idx_fb_accounts_owner ON fb_accounts(owner_id);

-- ===================== 账户-BM 多对多关系 =====================
CREATE TABLE fb_account_bm (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id INTEGER NOT NULL REFERENCES fb_accounts(id) ON DELETE CASCADE,
    bm_id INTEGER NOT NULL REFERENCES fb_bms(id) ON DELETE CASCADE,
    created_at TEXT DEFAULT (datetime('now','localtime')),
    UNIQUE(account_id, bm_id)
);
CREATE INDEX IF NOT EXISTS idx_fb_account_bm_bm ON fb_account_bm(bm_id);

-- ===================== BM 封禁后账户迁移历史 =====================
CREATE TABLE fb_account_bm_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id INTEGER NOT NULL REFERENCES fb_accounts(id),
    old_bm_id INTEGER REFERENCES fb_bms(id),
    new_bm_id INTEGER REFERENCES fb_bms(id),
    changed_by INTEGER REFERENCES users(id),
    change_type TEXT NOT NULL DEFAULT 'manual',  -- manual / banned_migration
    created_at TEXT DEFAULT (datetime('now','localtime'))
);

-- ===================== FB 产品 =====================
CREATE TABLE fb_products (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    product_name TEXT NOT NULL,
    kpi TEXT DEFAULT '',
    region TEXT DEFAULT '',
    status TEXT DEFAULT 'active',        -- active / paused
    sales_person_id INTEGER REFERENCES sales_persons(id),
    agency_ratio REAL DEFAULT 0,
    owner_id INTEGER REFERENCES users(id),
    is_archived INTEGER DEFAULT 0,
    created_at TEXT DEFAULT (datetime('now','localtime')),
    updated_at TEXT DEFAULT (datetime('now','localtime'))
);
CREATE INDEX IF NOT EXISTS idx_fb_products_owner ON fb_products(owner_id);

-- ===================== 产品在跑人员关联表 =====================
CREATE TABLE fb_product_runners (
    product_id INTEGER NOT NULL REFERENCES fb_products(id) ON DELETE CASCADE,
    user_id INTEGER NOT NULL REFERENCES users(id),
    PRIMARY KEY (product_id, user_id)
);
CREATE INDEX IF NOT EXISTS idx_fb_product_runners_user ON fb_product_runners(user_id);

-- ===================== 产品-在跑BM 多对多关系 =====================
CREATE TABLE fb_product_bms (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    product_id INTEGER NOT NULL REFERENCES fb_products(id) ON DELETE CASCADE,
    bm_id INTEGER NOT NULL REFERENCES fb_bms(id) ON DELETE CASCADE,
    UNIQUE(product_id, bm_id)
);
CREATE INDEX IF NOT EXISTS idx_fb_product_bms_bm ON fb_product_bms(bm_id);

-- ===================== 像素BM（管理像素的BM） =====================
CREATE TABLE fb_pixel_bms (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    bm_id TEXT NOT NULL UNIQUE,          -- 像素BM ID（纯数字校验）
    note TEXT DEFAULT '',
    status TEXT DEFAULT 'normal',        -- normal / banned
    owner_id INTEGER REFERENCES users(id),
    deleted_at TEXT DEFAULT NULL,
    created_at TEXT DEFAULT (datetime('now','localtime')),
    updated_at TEXT DEFAULT (datetime('now','localtime'))
);
CREATE INDEX IF NOT EXISTS idx_fb_pixel_bms_owner ON fb_pixel_bms(owner_id);

-- ===================== 像素（属于像素BM） =====================
CREATE TABLE fb_pixels (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    pixel_bm_id INTEGER NOT NULL REFERENCES fb_pixel_bms(id) ON DELETE CASCADE,
    pixel_name TEXT NOT NULL,
    pixel_id TEXT NOT NULL UNIQUE,       -- 像素ID（纯数字校验）
    created_at TEXT DEFAULT (datetime('now','localtime'))
);
CREATE INDEX IF NOT EXISTS idx_fb_pixels_bm ON fb_pixels(pixel_bm_id);

-- ===================== 线名（产品子级） =====================
CREATE TABLE fb_lines (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    product_id INTEGER NOT NULL REFERENCES fb_products(id) ON DELETE CASCADE,
    line_name TEXT NOT NULL,
    link TEXT DEFAULT '',
    pixel_id INTEGER REFERENCES fb_pixels(id) ON DELETE SET NULL,  -- 一对一像素
    created_at TEXT DEFAULT (datetime('now','localtime')),
    UNIQUE(product_id, line_name)         -- 同一产品下不能重名
);
CREATE INDEX IF NOT EXISTS idx_fb_lines_product ON fb_lines(product_id);
CREATE INDEX IF NOT EXISTS idx_fb_lines_pixel ON fb_lines(pixel_id);

-- ===================== FB 数据管理（做表数据） =====================
CREATE TABLE fb_ad_reports (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id),
    product_name TEXT NOT NULL,          -- 产品名（标识归属）
    line_name TEXT DEFAULT '',           -- 线名（标识归属 + 累加维度）
    report_date TEXT NOT NULL,           -- 日期（累加维度）
    account_name TEXT DEFAULT '',        -- 账户名称（提取，展示用）
    account_id TEXT DEFAULT '',          -- 账户ID（提取，去重用）
    cost REAL DEFAULT 0,                 -- 账号消耗（最大$金额）
    impressions INTEGER DEFAULT 0,       -- 展示次数（仅排序模式有）
    clicks INTEGER DEFAULT 0,            -- 点击
    registrations INTEGER DEFAULT 0,     -- 完成注册次数
    purchases INTEGER DEFAULT 0,         -- 购物次数
    cost_per_purchase REAL DEFAULT 0,    -- 单词购物费用
    saved_at TEXT DEFAULT (datetime('now','localtime'))
);

-- 去重索引：同用户+产品+线名+账户+日期唯一
CREATE UNIQUE INDEX IF NOT EXISTS idx_fb_ad_reports_upsert
    ON fb_ad_reports(user_id, product_name, line_name, account_id, report_date);

-- 查询索引
CREATE INDEX IF NOT EXISTS idx_fb_ad_reports_user_date
    ON fb_ad_reports(user_id, report_date);
CREATE INDEX IF NOT EXISTS idx_fb_ad_reports_product_date
    ON fb_ad_reports(product_name, report_date);
```

### 3.3 表关系图

```
fb_products ──1对多── fb_lines ──1对1── fb_pixels ──多对1── fb_pixel_bms
     │
     │ 多对多
     │
fb_product_bms ──── fb_bms(账户BM) ──── 多对多 ──── fb_account_bm ──── fb_accounts

fb_pixel_bms(像素BM) ──1对多── fb_pixels
```

### 3.4 选项表复用

以下 GG 选项表被 FB 共用，不新建：

| 选项表 | 用途 | API |
|---------|------|-----|
| `regions` | 地区 | `/api/regions/list` |
| `account_statuses` | 账户状态 | `/api/statuses/list` |
| `sales_persons` | 商务 | `/api/sales-persons/list` |

---

## 四、API 路由设计

### 4.1 FB 专用路由（新建 `py/routes/fb_routes.py`）

所有路由挂载在 `/api/fb/*` 下，均需 `@jwt_required()`。

#### 产品管理

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | /api/fb/products/list | 产品列表（分页/搜索/status筛选） |
| GET | /api/fb/products/runner-products | 当前用户的在跑产品（下拉框用） |
| POST | /api/fb/products/create | 创建产品（含线名、在跑BM、在跑人员） |
| PUT | /api/fb/products/:pid | 更新产品 |
| DELETE | /api/fb/products/:pid | 软删除（is_archived=1） |
| GET | /api/fb/products/:pid/detail | 产品详情（含线名列表 + 在跑BM列表 + runner列表） |

#### 线名管理

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | /api/fb/products/:pid/lines | 添加线名（含像素BM） |
| PUT | /api/fb/lines/:lid | 更新线名 |
| DELETE | /api/fb/lines/:lid | 删除线名 |

#### BM 管理

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | /api/fb/bms/list | BM 列表（分页/status筛选） |
| POST | /api/fb/bms/create | 创建 BM |
| PUT | /api/fb/bms/:bid | 更新 BM（含状态变更） |
| DELETE | /api/fb/bms/:bid | 软删除 |
| POST | /api/fb/bms/:bid/ban-and-migrate | 封禁BM并迁移账户到目标BM |
| GET | /api/fb/bms/options | BM 下拉选项（id+name） |

#### 像素BM管理

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | /api/fb/pixel-bms/list | 像素BM列表（分页） |
| POST | /api/fb/pixel-bms/create | 创建像素BM |
| PUT | /api/fb/pixel-bms/:bid | 更新像素BM |
| DELETE | /api/fb/pixel-bms/:bid | 软删除 |
| GET | /api/fb/pixel-bms/options | 像素BM 下拉选项 |

#### 像素管理（像素BM子级）

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | /api/fb/pixel-bms/:bid/pixels | 像素BM下的像素列表 |
| POST | /api/fb/pixel-bms/:bid/pixels | 添加像素 |
| PUT | /api/fb/pixels/:pxid | 更新像素 |
| DELETE | /api/fb/pixels/:pxid | 删除像素 |

#### 账户管理

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | /api/fb/accounts/list | 账户列表（分页/BM筛选/status筛选/搜索） |
| POST | /api/fb/accounts/create | 创建账户（含关联BM） |
| PUT | /api/fb/accounts/:aid | 更新账户 |
| DELETE | /api/fb/accounts/:aid | 软删除 |
| GET | /api/fb/accounts/deleted | 已删除账户列表 |
| POST | /api/fb/accounts/:aid/restore | 恢复 |
| DELETE | /api/fb/accounts/:aid/permanent | 物理删除 |
| GET | /api/fb/accounts/:aid/bm-history | 账户 BM 变更历史 |

#### 数据提取

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | /api/fb/extract/parse | 粘贴数据解析（返回结构化 JSON 预览） |
| POST | /api/fb/extract/save | 保存解析后的数据 |

#### 数据管理

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | /api/fb/reports/list | 数据列表（筛选/分页/排序） |
| PUT | /api/fb/reports/:id | 编辑单条 |
| DELETE | /api/fb/reports/:id | 删除单条 |
| POST | /api/fb/reports/batch-delete | 批量删除 |
| GET | /api/fb/reports/stats | 同产品+线名+日期累加统计 |
| GET | /api/fb/reports/export | 导出 CSV |

### 4.2 现有路由改动

| 改动 | 说明 |
|------|------|
| `POST /api/admin/users/create` | 请求体新增 `platform` 参数（'gg' | 'fb'） |
| `PUT /api/admin/users/:uid` | 新增可修改 platform，仅 developer 可操作 |
| `GET /api/auth/me` | 返回 `platform` 字段 |
| `GET /api/regions/list` | 不修改，FB 前端直接调用 |

### 4.3 数据解析端点逻辑 (`POST /api/fb/extract/parse`)

**输入**：粘贴文本

**解析步骤**：

```
Step 1: 识别范围 — 截取 "数据透视表" 到 "总成效" 之间的内容

Step 2: 动态分组 — 逐行扫描：
  如果当前行是非纯数字（文本/含特殊字符如 "$""-"）
  AND 下一行是纯数字且长度 ≥ 10 位
  → 标记为新组起点
  两个起点之间 = 一组完整数据

Step 3: 每组提取：
  [0] = 账户名称
  [1] = 账户ID（纯数字长串）
  剩余行：
    - 过滤 [数字] 格式的脏数据（含中括号的）
    - 收集所有 $ 开头 → 数值最大的 = 消耗金额
    - 如果 $ 数量 > 2 → warning 标记

Step 4: 排序模式分支：
  未勾选（只能提取3项）：
    → 账户名称 | 账户ID | 消耗金额
    
  勾选（可提取完整8项）：
    过滤脏数据后，剩余非$数字行按顺序映射：
    → 账户名称 | 账户ID | 消耗 | 展示次数 | 点击 | 完成注册 | 购物 | 单词购物费用
```

**输出**：
```json
{
  "success": true,
  "data": [
    {
      "account_name": "100M$-308",
      "account_id": "1520401159586810",
      "cost": 3066.48,
      "impressions": 250090,
      "clicks": 228,
      "registrations": 2404,
      "purchases": 265,
      "cost_per_purchase": 13.45
    }
  ],
  "warnings": [],  // "$超过2个"的账户名列表
  "group_size": 11 // 当前每组行数（动态检测结果）
}
```

### 4.4 BM 封禁迁移逻辑 (`POST /api/fb/bms/:bid/ban-and-migrate`)

```
输入：{ target_bm_id: "123456", target_bm_name: "新BM名" }  // 可选已有BM或新BM

逻辑：
1. 如果 target_bm_id 在系统中不存在 → 自动创建新 BM（name=target_bm_name, bm_id=target_bm_id）
2. 查询该 BM 下所有关联账户 (fb_account_bm)
3. 在 fb_account_bm 中删除旧 BM 关联
4. 在 fb_account_bm 中插入新 BM 关联
5. 在 fb_account_bm_history 中记录迁移（change_type='banned_migration'）
6. 更新 fb_bms.status = 'banned'
```

---

## 五、前端设计

### 5.1 路由设计

新增 FB 路由，所有 `meta: { platform: 'fb' }`：

```js
// router/index.js 新增
{
  path: '/fb',
  redirect: '/fb/products',
  meta: { platform: 'fb' }
},
{
  path: '/fb/products',
  component: () => import('../views/fb/FbProductPanel.vue'),
  meta: { platform: 'fb', title: 'FB产品管理' }
},
{
  path: '/fb/accounts',
  component: () => import('../views/fb/FbAccountPanel.vue'),
  meta: { platform: 'fb', admin: true, title: 'FB账户管理' }
},
{
  path: '/fb/bms',
  component: () => import('../views/fb/FbBmPanel.vue'),
  meta: { platform: 'fb', admin: true, title: '账户BM管理' }
},
{
  path: '/fb/pixel-bms',
  component: () => import('../views/fb/FbPixelBmPanel.vue'),
  meta: { platform: 'fb', admin: true, title: '像素BM管理' }
},
{
  path: '/fb/extract',
  component: () => import('../views/fb/FbDataExtract.vue'),
  meta: { platform: 'fb', title: 'FB数据提取' }
},
{
  path: '/fb/data-manage',
  component: () => import('../views/fb/FbDataManage.vue'),
  meta: { platform: 'fb', title: 'FB数据管理' }
},
```

### 5.2 路由守卫改动

```js
// router.beforeEach 新增 platform 检查
if (to.meta.platform && to.meta.platform !== auth.currentPlatform) {
  next('/') // 非本平台路由重定向
}
```

### 5.3 侧边栏改动

- `AppSidebar.vue`：根据 `auth.currentPlatform` 渲染不同的 `navItems`
- Developer：侧边栏顶部显示平台切换开关 `[GG] [FB]`
- 普通用户：隐藏开关，固定菜单

### 5.4 FB 菜单结构

```
🏢 账户管理
  ├── 📦 产品管理         → /fb/products
  ├── 👤 广告账户         → /fb/accounts
  ├── 🏢 账户BM管理       → /fb/bms
  └── 🔷 像素BM管理       → /fb/pixel-bms
📋 数据提取              → /fb/extract
📊 数据管理              → /fb/data-manage
📈 数据分析              → /analysis （复用GG）
```

### 5.5 页面文件清单

| 文件 | 功能 |
|------|------|
| `views/fb/FbProductPanel.vue` | 产品列表 + 线名管理（线对应像素） |
| `views/fb/FbAccountPanel.vue` | 账户 CRUD + 账户BM 关联 |
| `views/fb/FbBmPanel.vue` | 账户BM CRUD + 封禁迁移 |
| `views/fb/FbPixelBmPanel.vue` | 像素BM CRUD + 像素管理 |
| `views/fb/FbDataExtract.vue` | 粘贴数据解析预览保存 |
| `views/fb/FbDataManage.vue` | 数据管理（筛选/统计/导出） |
| `api/fb.js` | FB API 调用模块 |
| `stores/fb.js` | FB 状态管理 |

### 5.6 各页面详细设计

#### FbProductPanel.vue

- **列表列**：产品名、KPI、地区、在跑BM（el-tag 列表）、商务、代投比例、状态
- **产品弹窗**：
  - 产品名、KPI、地区（复用 GG 选项下拉）、商务、代投比例、状态
  - 在跑BM：el-select multiple
  - 在跑人员：el-select multiple（选择 FB 用户）
  - 线名列表（子表）：线名、链接、像素（el-select 单选，从像素池选择），可增删
- **展开/复制**：点击线名复制名称到剪贴板，点击链接复制链接到剪贴板
- **操作**：编辑 / 暂停 / 删除（软删除）

#### FbAccountPanel.vue

- **列表列**：账户名、账户ID、所属BM（逗号拼接）、时区、状态、到手时间
- **筛选**：BM 下拉、状态下拉、搜索（ID/名称）
- **账户弹窗**：
  - 账户名、账户ID（纯数字校验）、时区、状态、到手时间
  - 关联BM：el-select multiple
- **操作**：编辑 / 删除（软删除）/ 恢复
- **批量导入**：类似 GG 批量导入
- **已删除弹窗**：类似 GG，展示已删除账户，支持恢复和物理删除

#### FbBmPanel.vue

- **列表列**：BM名、BMID、备注、状态标签、关联账户数
- **BM弹窗**：BM名、BMID（纯数字校验）、备注、状态
- **封禁操作**：
  1. 点击"封禁"按钮
  2. 弹窗 1：确认封禁 + 显示关联账户数
  3. 弹窗 2：选择目标 BM（下拉搜索，支持输入新 BM ID）
     - 下拉选项排除自身和已封禁 BM
     - 输入不存在的 BM ID → 弹出确认框"将新建 BM [xxx]"
  4. 确认 → 调用 ban-and-migrate API
- **操作**：编辑 / 封禁 / 删除（软删除）

#### FbPixelBmPanel.vue

- **列表列**：BM名、BMID、备注、状态标签、像素数
- **展开/弹窗**：像素BM详情 + 像素列表
  - 像素列表列：像素名、像素ID（纯数字）
  - 可增删像素
- **像素BM弹窗**：BM名、BMID（纯数字校验）、备注、状态
- **操作**：编辑 / 删除（软删除）
- 像素BM 不涉及账户迁移，结构比账户BM简单

#### FbDataExtract.vue

- **产品下拉** → **线名下拉**（条件显示：产品有多条线时才出现）
- **是否排序** checkbox
- **粘贴区**：el-input type="textarea"，粘贴 FB 数据透视表内容
- **解析按钮**：调用 `/api/fb/extract/parse`
- **预览表格**：
  - 未排序：账户名称 | 账户ID | 消耗金额（3列）
  - 排序：账户名称 | 账户ID | 消耗 | 展示 | 点击 | 注册 | 购物 | 单词购物费用（8列）
- **$ 超 2 个警告**：弹窗列出异常账户名，提示用户减少含$符号的数据
- **保存按钮**：选择产品+线名 → 调用 `/api/fb/extract/save`

#### FbDataManage.vue

- **筛选**：产品下拉、线名下拉、日期范围
- **表格**：动态列（根据数据是否含排序字段），列显示/隐藏切换
- **统计行**：表格底部汇总行（按产品+线名+日期维度累加 cost/impressions/clicks 等数值列）
- **操作**：编辑单条 / 删除 / 批量删除
- **导出**：CSV

---

## 六、权限与鉴权改动

### 6.1 后端权限

| 路由前缀 | 权限 |
|----------|------|
| `/api/fb/*` | `@jwt_required()` + platform 检查（非 FB 用户拒绝，developer 放行） |
| `/api/admin/users/*` | platform 字段仅 developer 可修改 |
| `/api/regions/*` 等选项表 | 不变，FB 前端直接调用 |
| `/api/ad-reports/*` (GG) | 不变，仅 GG 用户访问 |
| `/api/auth/me` | 返回 `platform` 字段 |

### 6.2 前端权限

| Store getter | 逻辑 |
|--------------|------|
| `auth.isFbUser` | `user.platform === 'fb'` |
| `auth.isGgUser` | `user.platform === 'gg'` |
| `auth.isDeveloper` | `user.role === 'developer'` |
| `auth.currentPlatform` | 普通用户取 `user.platform`，developer 取 `currentPlatform` 状态（可切换） |

---

## 七、涉及文件清单

### 新建文件

| 文件 | 说明 |
|------|------|
| `docs/superpowers/specs/2026-07-30-fb-platform-design.md` | 本文档 |
| `py/routes/fb_routes.py` | FB 所有 API 路由 |
| `frontend/src/views/fb/FbProductPanel.vue` | FB 产品管理 |
| `frontend/src/views/fb/FbAccountPanel.vue` | FB 账户管理 |
| `frontend/src/views/fb/FbBmPanel.vue` | 账户BM管理 |
| `frontend/src/views/fb/FbPixelBmPanel.vue` | 像素BM管理 + 像素管理 |
| `frontend/src/views/fb/FbDataExtract.vue` | FB 数据提取 |
| `frontend/src/views/fb/FbDataManage.vue` | FB 数据管理 |
| `frontend/src/api/fb.js` | FB API 模块 |
| `frontend/src/stores/fb.js` | FB 状态管理 |

### 修改文件

| 文件 | 改动 |
|------|------|
| `py/database.py` | 新增 FB 建表语句 |
| `py/main.py` | 注册 fb_routes Blueprint |
| `py/auth.py` | `/api/auth/me` 返回 platform 字段 |
| `py/routes/helpers.py` | 新增 `require_platform()` 权限检查 |
| `frontend/src/router/index.js` | 新增 FB 路由 + platform 守卫 |
| `frontend/src/components/AppSidebar.vue` | platform 菜单切换 |
| `frontend/src/stores/auth.js` | 新增 platform getter + currentPlatform 状态 |
| `frontend/src/views/LoginView.vue` | 开发者登录后进入平台（无需改，后端返 platform） |
| `frontend/src/views/UserManageView.vue` | 创建用户时选 GG/FB 平台 |

### 不变文件

GG 的所有页面（ProductPanel、AdsAccountPanel、MccPanel、ToolkitView、DataManageView 等）完全不动。

---

## 八、数据累加统计说明

在数据管理页面，选择产品+线名后：

```
统计维度：(product_name, line_name, report_date)
累加字段：cost, impressions, clicks, registrations, purchases
不累加：account_name, account_id（每条记录独立展示）

统计查询示例：
SELECT 
  product_name, line_name, report_date,
  SUM(cost) as total_cost,
  SUM(impressions) as total_impressions,
  COUNT(DISTINCT account_id) as account_count
FROM fb_ad_reports
WHERE user_id = ? AND product_name = ? AND line_name = ?
GROUP BY product_name, line_name, report_date
```

统计结果作为表格底部汇总行展示，不合并原数据行。

---

## 九、设计审查补充（来自全栈分析）

### 9.1 auth.py 改动明细

| 函数 | 改动 |
|------|------|
| `get_user_by_id()` | SELECT 加 `platform` 列 |
| `create_user()` | 签名加 `platform` 参数（默认 `'gg'`），INSERT 包含 platform |
| `list_users()` | SELECT 加 `platform`，支持 `?platform=fb` 筛选参数 |
| `update_user()` | 支持更新 `platform`，仅 developer 可操作 |
| 登录响应 | 返回 `platform` 字段 |
| `/api/auth/me` | 返回 `platform` 字段 |

### 9.2 GG 路由平台守卫

GG 所有写操作路由需加平台检查，FB 用户不可访问：
- `/api/ad-reports/*` → `require_platform('gg')`
- `/api/accounts/*`、`/api/mcc/*`、`/api/products/*` → `require_platform('gg')`
- `/api/scrape/*`、`/api/video/*`、`/api/youtube/*` → `require_platform('gg')`
- developer 直接放行

### 9.3 FB 用户列表端点

`GET /api/admin/users?platform=fb` — 产品管理选择在跑人员时需要 FB 用户列表。
或者复用 `/api/auth/names` 加 `platform` 过滤。

### 9.4 数据提取保存事务

```
POST /api/fb/extract/save 必须使用数据库事务：
1. BEGIN TRANSACTION
2. 遍历每条数据，INSERT OR REPLACE（依赖去重索引）
3. 如果全部成功 → COMMIT
4. 如果任一条失败 → ROLLBACK，返回错误
```

### 9.5 ban-and-migrate 补充

- 前置检查：`status != 'banned'`（防止重复封禁）
- 产品-BM 关联警告：返回产品列表，提示用户手动处理产品的在跑BM关联
- target_bm_name：仅当 target_bm_id 不存在（需新建）时使用，已存在的 BM 不覆盖名称

### 9.6 复合索引补充

```sql
-- 列表查询优化
CREATE INDEX IF NOT EXISTS idx_fb_bms_list ON fb_bms(owner_id, status, deleted_at);
CREATE INDEX IF NOT EXISTS idx_fb_accounts_list ON fb_accounts(owner_id, status_id, deleted_at);
CREATE INDEX IF NOT EXISTS idx_fb_pixel_bms_list ON fb_pixel_bms(owner_id, status, deleted_at);
```

### 9.7 N+1 查询防范

- 产品列表：一次 JOIN 查询获取产品 + 在跑BM + 线名
- BM 列表：一次 `LEFT JOIN + GROUP BY` 获取关联账户数/像素数
- 账户列表：一次 JOIN 获取关联 BM 名称列表

### 9.8 审计日志

关键 FB 操作写入 `audit_log` 表（复用 GG 现有表）：
- 产品软删除
- BM 封禁 + 迁移
- 账户永久删除

### 9.9 像素选择器分组

线名选择像素时，下拉框按像素BM分组展示：
```
像素BM: "主像素BM" (645797)
  ├── 像素A (123456)
  └── 像素B (789012)
像素BM: "备用像素BM" (371783)
  └── 像素C (345678)
```

### 9.10 其他注意事项

| 项目 | 说明 |
|------|------|
| 并发封禁 | `ban-and-migrate` 入口检查 `status != 'banned'` |
| 解析器错误处理 | 缺少"数据透视表"标记 → 返回错误；空文本 → 返回空数组 |
| 像素删除 | `ON DELETE SET NULL`，前端展示"像素已删除"占位符 |
| fb_ad_reports 编辑 | 加 `updated_at` 字段 |
| 预览大数据量 | 解析返回结果限制 500 条，超出提示分批粘贴 |
| 开发者默认平台 | 登录后默认进入 GG，切换平台状态记录在 Pinia（不持久化） |
| 开发者平台切换 | 切换时取消进行中的 API 请求（AbortController） |
| fb_lines/fb_pixels | 无软删除（子级数据，硬删除即可） |
