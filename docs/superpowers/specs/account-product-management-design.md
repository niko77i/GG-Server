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
