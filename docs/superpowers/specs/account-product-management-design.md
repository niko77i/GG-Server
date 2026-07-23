# 账户与产品管理 — 设计规格

**最后更新**：2026-06-14（合并自 2026-06-10 产品管理 + 2026-06-14 账户MCC管理）

## 1. 功能概述

统一面板管理三层关系：

```
产品 ──→ MCC ──→ 账户
```

- 产品下有多个包（Google Play 链接），产品关联到 MCC
- 账户挂在 MCC 下，树形层级（父 MCC → 子 MCC）
- 产品详情中通过 MCC 递归展示所有关联账户及状态
- 设置页可配置账户状态、代理名、MCC 等级等下拉选项

## 2. 数据模型

### products 表

| 字段 | 类型 | 说明 |
|------|------|------|
| id | INTEGER PK | 自增 |
| product_name | TEXT | 产品/群名 |
| kpi | TEXT | KPI |
| region | TEXT | 地区 |
| status | TEXT | 空=正常，paused=暂停 |
| mcc_id | INTEGER FK→mcc | 所属 MCC |
| created_at | TEXT | |

### packages 表

| 字段 | 类型 | 说明 |
|------|------|------|
| id | INTEGER PK | 自增 |
| product_id | INTEGER FK | 关联产品 |
| series_name | TEXT | 系列名 |
| package_name | TEXT | 包名（com.xxx.xxx） |
| url | TEXT | Google Play 链接 |
| status | TEXT | 空=正常，paused=暂停，dropped=掉包，rejected=拒登 |
| created_at | TEXT | |

### accounts 表

| 字段 | 类型 | 说明 |
|------|------|------|
| id | INTEGER PK | 自增 |
| name | TEXT | 账号名称 |
| account_id | TEXT UNIQUE | Google Ads ID，新增后不可改 |
| mcc_id | INTEGER FK→mcc | 所属 MCC |
| timezone | TEXT | 时区（如"巴西 -3"） |
| agent | TEXT | 代理 |
| status | TEXT | 存活/死亡/验证/限额（可在设置页自定义） |
| acquired_date | TEXT | 到手时间 |
| created_at / updated_at | TEXT | |

### mcc 表

| 字段 | 类型 | 说明 |
|------|------|------|
| id | INTEGER PK | 自增 |
| name | TEXT | MCC 名称 |
| mcc_id | TEXT UNIQUE | Google Ads manager ID，新增后不可改 |
| level | TEXT | 等级（可在设置页自定义） |
| parent_mcc_id | INTEGER FK→mcc | 上级 MCC，空=顶级（树形结构） |
| created_at / updated_at | TEXT | |

### 关系规则

- 账户 ∈ 唯一 MCC（一对多，`accounts.mcc_id`）
- 产品 → MCC（多对一，`products.mcc_id`）
- MCC ⇄ MCC（一对多树形，`parent_mcc_id` 自引用）
- 包 → 产品（多对一）
- 产品可见账户 = 关联 MCC 及其所有子孙 MCC 下的账户**合集**

## 3. API 路由

### 产品

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/products/list` | 列表（搜索/地区/MCC/暂停筛选+分页） |
| POST | `/api/products/create` | 创建（含 mcc_id + 批量包） |
| PUT | `/api/products/<pid>` | 更新（含 mcc_id） |
| DELETE | `/api/products/<pid>` | 删除产品及包 |
| GET | `/api/products/<pid>/detail` | 详情（包列表 + 关联账户+状态统计） |
| POST | `/api/products/<pid>/packages` | 添加包 |
| PUT | `/api/products/packages/<pkg_id>` | 更新包 |
| DELETE | `/api/products/packages/<pkg_id>` | 删除包 |
| POST | `/api/products/import-text` | 脏数据解析（6 种格式） |

### 账户

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/accounts/list` | 列表（搜索/状态/MCC/代理+分页） |
| POST | `/api/accounts/create` | 新增 |
| PUT | `/api/accounts/<id>` | 更新 |
| DELETE | `/api/accounts/<id>` | 删除 |
| POST | `/api/accounts/batch-delete` | 批量删除 |
| POST | `/api/accounts/batch-update` | 批量修改 |

### MCC

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/mcc/list` | 列表（搜索/等级/上级+分页） |
| GET | `/api/mcc/options` | 下拉选项 |
| POST | `/api/mcc/create` | 新增 |
| PUT | `/api/mcc/<id>` | 更新 |
| DELETE | `/api/mcc/<id>` | 删除（检查子节点） |
| POST | `/api/mcc/batch-delete` | 批量删除 |
| GET | `/api/mcc/<id>/detail` | 详情（直属账户+子MCC贡献+关联产品） |

### 设置

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/settings/account` | 获取可配置项 |
| POST | `/api/settings/account` | 保存可配置项 |

可配置项（存于 `tags` 表，JSON 数组）：`account_statuses`、`account_agents`、`mcc_levels`

## 4. 前端面板结构

侧边栏 **🏢 账户管理**，内含 4 个子标签：

| 子标签 | 内容 |
|--------|------|
| 📦 产品管理 | 产品卡片列表（可展开包列表）+ 新增/编辑/复制导入弹窗 + 产品详情弹窗（包列表+关联账户状态统计） |
| 👤 广告账户 | 表格（账号名称/ID/MCC/时区/代理/状态/到手时间）+ 新增/编辑弹窗 + 批量操作 |
| 🏢 MCC 管理 | 表格（MCC名称/ID/等级/上级/账户数）+ 新增/编辑弹窗 + 详情弹窗（直属账户+子MCC贡献+关联产品） |
| ⚙ 设置 | 账户状态/代理名/MCC 等级配置（textarea，每行一个值） |

## 5. 脏数据解析

支持 6 种格式，按优先级匹配：

| 类型 | 特征 | 系列名来源 |
|------|------|-----------|
| 1（APK行） | `📱FF345-APK-24` 含 "APK" 的行 | 整行去掉 emoji |
| 2（神包上线）| `🔥神包上线：7274-apk-包37` | `神包上线：` 后的内容 |
| 3（应用名在链接后）| 链接下方 `应用名：Edge dod-27包` | `应用名：` 后的内容 |
| 4（名称行）| `谷歌11 名称：NexaPulse` | `名称：` 后的内容 |
| 5（兜底）| 纯链接，无其他信息 | 从链接 `id=` 提取包名 |
| 6（首列含-）| 第一列含 `-` 即系列名 | 取第一个 token |

包名始终从链接 `?id=` 参数提取，不依赖文本中的包名。

## 6. UI 交互要点

- 产品卡片可折叠，badge 统计（正常/暂停/拒登/掉包），点击 badge 筛选
- 包排序：正常→拒登→暂停→掉包，同状态按系列名自然排序
- 复制导入：粘贴脏数据文本 → 预览解析 → 可编辑每行 → 导入
- 账户状态颜色动态生成，支持设置页自定义
- MCC 详情弹窗：总计/直属/子MCC来源 三栏汇总

---

## 7. 审计补充章节（代码对比，2026-07-23）

本节基于 `py/main.py`、`py/database.py`、`frontend/src/views/ProductPanel.vue`、`frontend/src/views/AdsAccountPanel.vue` 的实际代码，与上文设计文档逐项对比，记录差异和遗漏。

### 7.1 数据模型遗漏字段

以下字段已在代码中实现但设计文档未记录。

**products 表遗漏字段：**

| 字段 | 类型 | 说明 | 代码位置 |
|------|------|------|----------|
| `owner_id` | INTEGER FK→users | 产品归属用户（数据隔离） | `database.py:101` |
| `runner_ids` | TEXT | JSON 数组，在跑人员 ID 列表（冗余列，与 product_runners 表双写） | `database.py:102` |
| `is_archived` | INTEGER DEFAULT 0 | 软删除标记，1=已归档/已删除 | `database.py:103` |
| `deleted_at` | TEXT | 删除时间戳，空字符串表示未删除 | `database.py:111` |
| `customer` | TEXT DEFAULT '' | 客户名 | `database.py:110` |
| `sales_person` | TEXT DEFAULT '' | 销售人员 | `database.py:112` |
| `agency_ratio` | REAL DEFAULT NULL | 代理分成比例 | `database.py:113` |

**accounts 表遗漏字段：**

| 字段 | 类型 | 说明 | 代码位置 |
|------|------|------|----------|
| `owner_id` | INTEGER FK→users | 账户归属用户（数据隔离） | `database.py:96` |
| `death_date` | TEXT DEFAULT '' | 死亡日期，状态切为"死亡"时自动写入 | `database.py:92` |
| `status_changed_date` | TEXT DEFAULT '' | 状态最后变更时间 | `database.py:93` |
| `status` 默认值 | — | 默认 `'存活'`，非文档所暗示的空字符串 | `database.py:196` |
| `acquired_date` 默认值 | — | 默认 `date('now','localtime')` | `database.py:197` |

**mcc 表遗漏字段：**

| 字段 | 类型 | 说明 | 代码位置 |
|------|------|------|----------|
| `owner_id` | INTEGER FK→users | MCC 归属用户（数据隔离） | `database.py:97` |
| `shared_user_ids` | TEXT DEFAULT '[]' | JSON 数组，共享可见的用户 ID 列表 | `database.py:98` |

### 7.2 设计文档未记录的数据库表

以下表已在 `database.py:206-443` 建表但设计文档完全未提及：

| 表名 | 用途 | 关键字段 |
|------|------|----------|
| `product_runners` | 产品-在跑人员关联表（替代 runner_ids JSON 查询，支持索引） | `product_id`, `user_id`, 联合主键 |
| `account_mcc_history` | 账户 MCC 变更历史追踪 | `account_id`, `old_mcc_id`, `new_mcc_id`, `changed_by`, `change_type` |
| `recharge_records` | 充值记录（含 Sheets 同步状态） | `account_id`, `amount`, `agent`, `operator`, `status`, `sheets_synced` |
| `product_assets` | 产品成效素材关联（YouTube 视频→产品） | `product_id`, `video_id`, `added_by`, UNIQUE(product_id, video_id) |
| `delist_checks` | 掉包检测结果缓存 | `package_id`(UNIQUE), `product_id`, `is_delisted`, `checked_at` |
| `delist_notifications` | 掉包通知状态（按用户跟踪） | `package_id`, `user_id`, `first_notified`, `dismissed_at`, `reminder_count` |
| `audit_log` | 产品删除审计日志（支持恢复） | `user_id`, `action`, `target_type`, `target_id`, `target_name`, `detail`(JSON快照) |
| `regions` | 地区与时区管理 | `name`(UNIQUE), `timezone` |

### 7.3 API 路由遗漏

以下路由已在 `main.py` 中实现但设计文档第 3 节未列出。

**产品相关遗漏路由：**

| 方法 | 路径 | 说明 | 代码行 |
|------|------|------|--------|
| GET | `/api/products/runner-products` | 获取当前用户作为 runner 的产品列表（下拉框用） | 2190 |
| POST | `/api/products/merge` | 合并多个产品到主产品（含 runner/包合并） | 2526 |
| PUT | `/api/products/<pid>/runners` | 更新产品 runner 列表，新增 runner 自动分配 MCC | 2658 |
| POST | `/api/products/packages/batch-delete` | 批量删除包 | 2802 |
| POST | `/api/products/<pid>/check-delist` | 手动触发掉包检测 | 2935 |
| GET | `/api/products/delist-status` | 获取当前用户关联产品的掉包状态 | 3002 |
| GET | `/api/products/<pid>/assets` | 获取产品成效素材列表 | 6366 |
| POST | `/api/products/<pid>/assets` | 向产品添加成效素材（批量导入 YouTube 视频） | 6383 |
| DELETE | `/api/products/<pid>/assets/<video_id>` | 移除产品的成效素材关联 | 6442 |
| GET | `/api/audit-log/list` | 获取产品删除审计日志列表 | 2823 |
| POST | `/api/audit-log/restore/<log_id>` | 从审计日志恢复已删除的产品及包（仅 developer） | 2861 |

**账户相关遗漏路由：**

| 方法 | 路径 | 说明 | 代码行 |
|------|------|------|--------|
| GET | `/api/accounts/lookup` | 按 account_id 查询已有账户详情 | 3365 |
| POST | `/api/accounts/batch-lookup` | 批量查询多个 account_id 是否已存在 | 3416 |
| POST | `/api/accounts/batch-create` | 批量创建账户（共用配置+逐账户 overrides） | 3526 |
| PUT | `/api/accounts/<aid>/reassign` | 将已有账户归属权转移给当前用户 | 3710 |
| GET | `/api/accounts/<aid>/recharge-records` | 获取某账户的充值记录 | 4071 |
| GET | `/api/accounts/<aid>/mcc-history` | 获取某账户的 MCC 变更历史 | 4180 |
| DELETE | `/api/accounts/<aid>/mcc-history/<hid>` | 删除单条 MCC 变更历史 | 4212 |

**MCC 相关遗漏路由：**

| 方法 | 路径 | 说明 | 代码行 |
|------|------|------|--------|
| POST | `/api/mcc/<mid>/link` | 将当前用户关联到已有 MCC（含上级链） | 4512 |

**充值相关路由（完全未在设计文档中提及）：**

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/recharge/submit` | 单次充值（写 DB + Google Sheets 后台同步） |
| POST | `/api/recharge/batch-submit` | 批量充值 |
| PUT | `/api/recharge/<rid>` | 修改充值记录 |
| DELETE | `/api/recharge/<rid>` | 删除充值记录 |
| POST | `/api/recharge/<rid>/retry-sheets` | 重试 Sheets 同步 |

### 7.4 设置 API 差异

设计文档描述可配置项为 3 个：`account_statuses`、`account_agents`、`mcc_levels`。

代码实际实现 5 个可配置项（`main.py:4584`）：

| 配置项 | 设计文档 | 代码 | 说明 |
|--------|:---:|:---:|------|
| `account_statuses` | 有 | 有 | 默认值 `["存活","死亡","验证","限额"]` |
| `account_agents` | 有 | 有 | 默认空数组 |
| `mcc_levels` | 有 | 有 | 默认空数组 |
| `sales_persons` | **无** | 有 | 销售人员列表，默认空数组 |
| `recharge_sheet_id` | **无** | 有 | Google Sheets ID，用于充值记录同步 |

### 7.5 前端面板差异

#### ProductPanel.vue（vs 设计文档第 4/6 节）

设计文档未记载的功能：

| 功能 | 说明 | 代码位置 |
|------|------|----------|
| **Runner 筛选** | "我在跑的" / "全部产品" 切换 + 按指定 runner 筛选下拉框 | 8-13行 |
| **产品合并** | 选中 2+ 个产品后可合并（含包名重叠检测警告） | 26-32行, 217-254行 |
| **删除日志弹窗** | 查看产品删除审计日志，展示快照详情，developer 可恢复已删产品 | 72-100行, 277-314行 |
| **产品选择** | 卡片左侧 checkbox 多选，支持合并操作 | 43行 |
| **区域时区显示** | 加载 regions 表并在卡片上展示各地区的时区信息 | 137行, 154-161行 |
| **通知联动** | 从掉包通知点击跳转到产品页时自动高亮滚动到对应包 | 174-193行 |
| **自定义名称** | 加载当前用户的 custom_name 并在卡片上显示 | 139行, 147-152行 |
| **KPI 搜索** | 搜索同时匹配 product_name 和 kpi | 代码中搜索 SQL 包含 kpi |

#### AdsAccountPanel.vue（vs 设计文档第 4 节）

设计文档未记载的功能：

| 功能 | 说明 | 代码位置 |
|------|------|----------|
| **批量导入弹窗** | `AccountBatchImportModal` 组件 | 7行 |
| **批量查户弹窗** | `AccountBatchLookupModal` 组件（批量查询 account_id 是否存在） | 8行 |
| **批量充值弹窗** | `RechargeBatchModal` 组件 | 9行 |
| **单账户充值** | 每行操作列有充值按钮 → `RechargeModal` | 77行, 185-188行 |
| **账户详情弹窗** | `AccountDetailModal` 组件 | 76行, 183行 |
| **批量修改 MCC** | 下拉框选择目标 MCC 批量修改 | 15-17行, 218-222行 |
| **时区筛选** | 独立时区下拉框筛选（非仅表格列） | 36-38行, 147行 |
| **状态统计按钮** | 各状态按钮上显示该状态的账户数量 | 24行, 130-156行 |
| **MCC 分组着色** | 相邻相同 MCC 归组，奇偶行交替背景色 | 162-175行, 230-239行 |
| **状态变更时间列** | 表格中展示 `status_changed_date` | 68-72行 |
| **自动加载"存活"筛选** | `onMounted` 时默认筛选 `status='存活'` | 135行 |

### 7.6 核心行为差异

以下行为在代码中实际存在，但设计文档描述不准确或遗漏：

**产品删除 — 软删除而非硬删除：**

设计文档写"删除产品及包"，实际代码（`main.py:2479-2523`）做的是软删除：
- 设置 `is_archived=1` + `deleted_at` 时间戳
- 删除前生成完整快照（产品字段 + 包列表 + 素材数量）写入 `audit_log` 表
- 清理 `delist_checks`、`product_assets` 关联
- 删除 `packages`（硬删除，但审计快照中保留了完整数据）
- developer 角色可通过 `/api/audit-log/restore` 恢复

**产品创建 — 同名追加逻辑：**

设计文档未提及：创建产品时如果 `product_name` 已存在，不会报错而是**追加包到已有产品**（`main.py:2414-2436`）。同时：
- 自动将创建者加入 `runner_ids` 和 `product_runners` 表
- 自动将产品 MCC 分配给创建者（`_assign_mcc_to_users`）

**账户创建 — 重复检测带归属信息：**

设计文档未提及：当 `account_id` 已存在时，接口返回 409 + 已有账户的详细信息（名称、MCC、归属人），前端可提示用户该账户属于谁。

**账户删除 — 级联清理：**

设计文档未提及：删除账户时同时删除其关联的 `recharge_records` 和 `account_mcc_history`（`main.py:3772-3775`）。

**账户状态变更 — 自动清账逻辑：**

设计文档完全未提及：当账户状态从"存活"切到非存活时，系统会自动检查上次变存活后是否有充值记录，如有则自动追加一条"清"账记录并同步 Google Sheets（`main.py:3640-3691`，批量操作中同逻辑见 3829-3863 行）。同时自动记录 `status_changed_date`，切为"死亡"时自动记录 `death_date`。

**MCC 删除 — 四重检查：**

设计文档写"检查子节点"，实际代码（`main.py:4441-4471`）检查四项：
1. 是否有子 MCC
2. 是否有直接关联账户
3. 是否有直接关联产品
4. 仅 owner 可删除（权限检查）

**MCC 创建 — 重复检测带确认：**

设计文档未提及：当 `mcc_id` 字符串已存在时：
- 如果当前用户已是 owner 或在 shared 中 → 返回 409
- 如果当前用户不在 shared 中 → 返回 `exists: true` + 已有 MCC 信息 + 归属人名称，供前端确认是否关联

**数据隔离（owner_id 体系）：**

设计文档完全未提及多用户数据隔离体系：
- products、accounts、mcc 均有 `owner_id` 字段
- 查询时按 `owner_id`（或 runner_ids / shared_user_ids）过滤
- MCC 有 `shared_user_ids` 机制让多个用户可见同一 MCC
- 产品有 `runner_ids` 机制让多用户作为 runner
- 2026-06-26 执行了存量数据归属迁移（`database.py:529-539`）

### 7.7 脏数据解析实现细节补充

设计文档第 5 节描述了 6 种格式，代码实现（`main.py:3147-3183`）有额外细节：

- 支持 `prefix` 和 `suffix` 参数：在解析出的系列名前/后自动添加前缀后缀，且有智能去重（已包含则不再重复添加）
- 正则匹配 Google Play URL 更精确：`https?://play\.google\.com/store/apps/details\?id=[\w.&=/\-?%]+`
- 包名始终从 URL 的 `?id=` 参数提取（`_extract_pkg_from_url`），与文档描述一致

### 7.8 汇总：文档覆盖率

| 类别 | 设计文档记录 | 代码实际 | 覆盖率 |
|------|:---:|:---:|:---:|
| products 表字段 | 6 | 13 | 46% |
| accounts 表字段 | 8 | 11 | 73% |
| mcc 表字段 | 6 | 8 | 75% |
| 数据库表总数 | 4 | 12 | 33% |
| 产品 API 路由 | 9 | 17 | 53% |
| 账户 API 路由 | 6 | 13 | 46% |
| MCC API 路由 | 7 | 8 | 88% |
| 充值 API 路由 | 0 | 5 | 0% |
| 设置可配置项 | 3 | 5 | 60% |
| ProductPanel 功能点 | 5 | 13 | 38% |
| AdsAccountPanel 功能点 | 4 | 14 | 29% |
