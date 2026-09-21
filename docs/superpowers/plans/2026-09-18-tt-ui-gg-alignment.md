# TT 模块 UI 对齐 GG 实现计划

> 规格：docs/superpowers/specs/2026-09-18-tt-ui-gg-alignment-design.md
> 执行：inline（用户已批准「直接抄 GG」）

**Goal:** 将 TT 产品管理页 + BC 管理页 UI 视觉/布局对齐 GG，纯前端，后端零改动。

**全局约束：**
- 纯增量：只改 `frontend/src/views/tt/` 下文件 + 新增 `frontend/src/components/TtProductCard.vue`，GG/FB 文件一律不碰
- 后端 API 契约不变（`ttApi` 方法、字段名原样）

**字段映射（GG 组件 → TT 数据）：**
| GG 字段 | TT 字段 |
|---------|---------|
| `product.mcc_name`/`mcc_code` | `product.bc.name` / `product.bc.bc_id`（`bc` 可能 null/undefined） |
| `product.sales_person` | `product.sales_person_name`（可能 undefined） |
| `product.runner_ids` | `product.runners`（数组，元素 `{id,username,display_name}`） |
| `product.asset_count`/`related_account_count` | 无，去掉 |
| 包 `status` 五态 + 状态下拉 | TT 包 `type` 二值（package/pwa）+ `status`（自由字符串，右侧小字展示） |
| 产品 `status`（truthy 判暂停） | `status === 'paused'` |

---

### Task 1: 新建 TtProductCard.vue

- Create: `frontend/src/components/TtProductCard.vue`
- 照 GG `ProductCard.vue` 复刻视觉：`el-card` + `#header`（吸顶 sticky）+ body `pkg-row` 包列表行
- 头部左侧：8px 状态点（内联 style，active `#059669` / paused `#dc2626`）→ 产品名 `<strong>` → `🔍 是否掉包` 按钮（`type=warning plain`，组件内调 `ttApi.checkDelist` 后 `emit('refresh')`）→ 商务 tag（`type=success` `💼`）→ kpi tag（`type=warning`）→ region tag（`type=primary`）→ customer tag（`type=success` `👤`）→ BC tag（`type=info` `🏢`）→ 在跑 tag（`type=info` `🏃 N人`，tooltip 列 runner 名）
- 头部右侧：`⏸/▶` 暂停 toggle（`!auth.isViewer`）→ `✏️` 编辑 → `🗑` 删除 → 展开箭头 `▼/▲`
- body：`pkg-row` 单行 flex，每行 = 跑包/PWA tag（`type` 二值）→ 系列名（monospace 点击复制）→ `│` → 包名（monospace 点击复制）→ `│` → 链接（点击复制 + 🔗）→ 右侧 `pkg.status` 小字
- 无 GG 的 checkbox 批量选择 / 素材复制 / 批量改状态（TT 无此功能）
- Props: `product`；Emits: `edit` / `del` / `toggle-pause` / `refresh`

### Task 2: 改 TtProductPanel.vue

- Modify: `frontend/src/views/tt/TtProductPanel.vue`
- 顶层容器 → `display:flex;flex-direction:column;height:100%`，删除 `page-wrapper`/`page-header`/`page-title`/`filter-card`
- 工具栏 → 一行 flex（`gap:10px;margin-bottom:12px`）：`➕ 新增产品` → 搜索（`flex:1`）→ 地区 select → 在跑人 select → 状态 radio（正常/已暂停）→ 归档 radio（在用/已归档）
- 卡片列表改用 `<TtProductCard>`，`v-for` + emit 绑定（edit/del/toggle-pause/refresh）
- 弹窗改 `label-position="top"` + emoji 标题 + 垂直单列 480px
- 粘贴解析弹窗改为预览式：系列名前缀（无后缀）+ 粘贴 textarea + `🔍 预览解析结果` + 可编辑预览表格 + `💾 加入`（push 进 formPackages）

### Task 3: 改 TtBcPanel.vue

- Modify: `frontend/src/views/tt/TtBcPanel.vue`
- 顶层容器 → flex column，删除灰底容器
- 工具栏 → 一行 flex：`➕ 新增 BC` → 搜索（`flex:1`）→ 状态 select
- 表格：`stripe` + `size="small"`，操作列改 `el-button link`，分页 + 每页条数 select
- 弹窗改 `label-position="top"` + emoji 标题 + 垂直单列 480px

### 验证

- `cd frontend && npm run build` 通过
- 后端测试无改动
- 手动浏览器比对
