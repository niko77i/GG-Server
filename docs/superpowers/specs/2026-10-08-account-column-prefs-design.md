# 账户看板自定义列（按用户保存）设计

日期：2026-10-08
状态：待实现
前置确认：本设计已经过 5 轮澄清问答，决策记录见文末「附：决策过程」。

---

## 1. 需求

三张主账户表的列越来越多，横向滚动严重；且不同角色关心的列不同。用户希望：

> 按用户自己的想法自定义需要的列，可以保存，各个用户都有自己的配置。

澄清后确认的边界：

- **纯个人自定义**。不做「按角色预设默认列」这个能力。「对不同的角色而言有些列不需要展示」只是在解释动机，不是需求。现有的角色闸门（如 TT 的「户归属」仅户管可见）保持不变，与个人自定义是两层正交的过滤。
- **配置存服务端，绑定账号**。换电脑、换浏览器配置跟着走，清缓存不丢。
- **交互 = 勾选显隐 + 拖拽调序**。
- **覆盖范围**：GG 广告账户、TT 广告账户、FB 账户三张表。MCC（`MccPanel.vue`）、BC（`TtBcPanel.vue`）本次不动。
- **锁定列**：`selection` 勾选框与「操作」列不可隐藏、不可拖动。其余数据列一律可隐可拖。
- **新列策略**：以后代码里新增的列，对存量用户**默认显示、追加到末尾**。

### 非目标

- 不改 `DataManageView.vue` 现有的 localStorage 版列显隐（那是「数据管理」页，不是账户看板）。是否迁移另议。
- 不做列宽持久化、不做列排序（点表头排序）持久化。
- 不做「按角色/全局预设默认列」的管理员配置界面。
- 不引入任何新的前端依赖。

---

## 2. 关键技术前提（已核实，非推测）

`el-table-column` **不依赖模板里手写的顺序**注册，而是每个列组件在 `onMounted` 时算出自己的 DOM 序号再插入 store：

```js
// frontend/node_modules/element-plus/es/components/table/src/table-column/index.vue_vue_type_script_setup_true_lang.mjs:84-97
onMounted(() => {
  const parent = columnOrTableParent.value
  const children = isSubColumn.value
    ? parent.vnode.el?.children
    : parent.refs.hiddenColumns?.children
  const getColumnIndex = () => getColumnElIndex(children || [], instance.vnode.el)
  columnConfig.value.getColumnIndex = getColumnIndex
  const columnIndex = getColumnIndex()
  columnIndex > -1 && owner.value.store.commit('insertColumn', columnConfig.value, …, updateColumnOrder)
})
```

```js
// 同目录 render-helper.mjs:121
const getColumnElIndex = (children, child) => Array.prototype.indexOf.call(children, child)
```

- `parent.refs.hiddenColumns` 存在（`table.vue_…mjs:25` 的 `ref: "hiddenColumns"`）。
- 列的渲染器会把默认插槽里 **Fragment 的 children 拍平一层**（同文件 `TableColumnRenderer`，对 `childNode.type === Fragment && isArray(childNode.children)` 逐个 push）。
- `.children` 是 DOM 的 HTMLCollection，**只含元素节点**，`v-if` 为假产生的注释节点不会占位。

**结论**：把 `<el-table-column>` 包进 `<template v-for>`（编译为 Fragment）后，列序 = 渲染出的 DOM 顺序 = 我们数组的顺序。方案 A 成立。

---

## 3. 方案选型

| 方案 | 做法 | 结论 |
|---|---|---|
| **A** | 列模板逐字保留，外面套 `<template v-for>` + `v-if` 分派 | **选定为打底** |
| B | 每列抽成独立单元格组件，列元数据纯 JS 驱动 | 否决：收益（面板文件变小）与代价（拔掉 `editingNameId`/`editNameValue`/`nameInputRef` 等内联编辑状态）不成比例，且跨面板复用收益接近零——三张表的单元格本来就不同 |
| C | 模板不动，CSS `order` 视觉重排 | 否决：element-plus 内部按 DOM 顺序算列序与列宽，CSS 只改视觉不改 DOM，两者会打架；`fixed` 列会错位 |

**定稿：A+** —— 方案 A 打底，并顺手把两块**已经被逐字复制**的单元格抽成共享组件：

1. **「写表」列**：`AdsAccountPanel.vue:63-78` 与 `TtAccountPanel.vue:59-71` 模板逐字复制（注释自述「语汇 / 位置 / 宽度**逐字沿用**一期 TT 账户表」）。
2. **「户归属」列**：逻辑早已抽到 `useOwnerPicker`（注释「GG 与 TT **逐字同构**，只差 reassign 实现」），但**标记**仍是两份复制——`AdsAccountPanel.vue:156-213` 与 `TtAccountPanel.vue:191-248`，各约 57 行。

抽这两个是**真复用**（改一处三平台生效），且它俩是纯展示 + emit、不碰内联编辑状态，风险可控。抽完后方案 A 的富列分支从 57 行缩成一行组件引用。

---

## 4. 数据模型与后端

### 4.1 存储

沿用 `config` 表（`py/database.py:372`，key-value），key = `dashboard_columns_{uid}`，value 为一个 JSON：

```json
{
  "gg_ads": {
    "order":  ["name", "account_id", "sheet_write", "mcc", "…"],
    "hidden": ["mcc", "status_changed"]
  },
  "tt_ads": { "order": ["advertiser_id", "sheet_write", "…"], "hidden": [] },
  "fb_ads": { "order": ["name", "account_id", "bms", "…"], "hidden": [] }
}
```

**每个面板必须存两个字段，只存一个是不行的：**

- `order` —— 该面板**全部**数据列的有序表（可见的与隐藏的都在里面）。渲染顺序由它决定。
- `hidden` —— `order` 中被用户隐藏的 key 子集。

为什么非要 `hidden` 不可：如果只存「可见列的有序数组」，那么**「用户主动隐藏了 A 列」与「A 列是代码里新加的」在数据上完全同形**（都是"不在数组里"）。而新列策略要求「不在配置里 → 追加到末尾并可见」，于是用户每隐藏一列，下次刷新就会被自动弹回来。存 `hidden` 才能把两者区分开。

- **只有「数据列」进 `order` / `hidden`**。`selection` 与「操作」是锁定列，不入库——以后调整锁定策略不会让存量配置失效。
- 某面板没有键 = 该面板全部数据列可见、按注册表默认顺序（等价于 `order` = registry 顺序、`hidden` = `[]`）。

**不建新表**的理由：`huguan_dashboard_{uid}`（`py/huguan_dashboard.py:180`）已经是「一个 key 存一个 JSON dict、按平台分子键」的现成先例，形状完全一致。新建表还要动 `_ensure_schema`（`py/database.py:320` 起）与 `data_service.py:10-43` 的导入导出表清单，收益为零。

### 4.2 接口

新增 `py/routes/column_prefs_routes.py`，蓝图 `column_prefs_bp`，在 `py/main.py:377` 附近注册（与 `sheet_write_bp` 相邻）：

| 方法 | 路径 | 请求 | 响应 |
|---|---|---|---|
| `GET` | `/api/user/column-prefs` | — | `{success, prefs: {…}}`，无配置时 `prefs: {}` |
| `PUT` | `/api/user/column-prefs` | `{panel, order: [...], hidden: [...]}` | `{success, prefs: {…}}`（保存后的完整 prefs） |

`PUT` 的请求体是**整个面板配置的替换**（`order` 与 `hidden` 一起提交），不是增量 patch。理由：两者有耦合不变式（`hidden ⊆ order`），分开提交会让服务端需要维护「先改哪个」的顺序，得不偿失。

- 装饰器：仅 `@jwt_required()`。**不加角色装饰器**——viewer 也该能配置自己的界面。`hidden` **角色**（已禁用）的用户本来就登录不了。（注意别和本设计的 `hidden` **字段**搞混，两者同名但无关。）
- 复用 `routes/helpers.py` 的 `ok()` / `err()` / `parse_body()` / `get_uid()`。
- **uid 一律从 `get_uid()`（JWT identity）取，绝不从请求体读 uid。** 这是本功能的权限边界：key 内含 uid，用户不可越权读写他人配置。
- `PUT` 只改一个面板，未涉及的其它面板配置保持不变（沿用 `huguan_dashboard.save_config` 的读-改-写模式）。

### 4.3 校验策略（刻意不做语义白名单）

只校验**形状**：

- `panel` 必须属于 `{"gg_ads", "tt_ads", "fb_ads"}`，否则 400。
- `order` 必须是 list，元素必须是 str；去重后长度 ≤ 64，每项长度 ≤ 64 字符；否则 400。
- `hidden` 必须是 list，元素必须是 str；长度 ≤ 64，每项 ≤ 64 字符；否则 400。
- `hidden` 里出现 `order` 里没有的 key → **不报错，直接丢弃该 key**。这是冗余信息，剔除即可，没必要把保存打回。

**不做**「key 必须是注册表里的合法列名」这种语义白名单。理由：白名单意味着「列清单」在 Python 与 Vue 各存一份，将来加列时忘改一边就是**线上静默失效**。而形状校验 + 渲染端与注册表求交集同样安全——损坏或恶意的值最多让该用户少看到几列，渲染不出坏 HTML，且永不漂移。

### 4.4 实现落点

`py/column_prefs.py`（约 60 行）：

- `PANELS = ("gg_ads", "tt_ads", "fb_ads")`
- `CONFIG_KEY = "dashboard_columns_{uid}"`
- `load_prefs(db, user_id) -> dict`
- `save_panel_prefs(db, user_id, panel, order, hidden) -> dict`
- `validate_order(raw) -> list | None` / `validate_hidden(raw, order) -> list | None`（形状校验 + 剔除 `hidden` 中不在 `order` 里的 key）

**必须带上的防御**：`config` 表全仓共用，读出来的值可能是数字、字符串或嵌套 list。`load_prefs` 要**逐层判类型**（顶层不是 dict → 返回 `{}`；面板值不是 dict → 跳过该面板；`order`/`hidden` 不是 list → 该字段降级；元素不是 str → 用 `str()` 兜底而非 `AttributeError`），否则一个畸形值就是 500。教训出处：`py/huguan_dashboard.py:188-200` 的 `_conf_text` 与 `get_platform_config` 注释。

---

## 5. 前端设计

### 5.1 新增单元

**① `frontend/src/stores/columnPrefs.js`（Pinia store）**

选 Pinia 而非裸 composable 的理由：三张表要共享同一份数据，且**每个登录会话只拉一次**。`App.vue` 里 `watch(() => auth.user?.id, ...)` —— uid 出现就拉、变空就清空，写法和 `composables/useOwnerPicker.js:35-38` 同源。

**不能写成「`onMounted` 里裸调一次 `ensureLoaded()`」**，有两处会出错：

- `onMounted` 那一刻用户可能还没登录（先落在 `/login`），裸调会 401 且永不重试
- `stores/auth.js:77-84` 的 `logout()` **不刷新页面**（`fetchMe()` 失败时也走它，见 `stores/auth.js:68`）。同浏览器换号时 store 里还留着上一个人的 prefs，而 `ensureLoaded()` 有 `if (ready.value) return` 守卫不会重拉 —— **B 会看到 A 的列**。所以换号时必须 `clear()`，且 `clear()` 还要清掉未落地的防抖定时器，否则 A 的定时器会带着 B 的新 token 把 A 的配置写进 B 的 key。

`stores/` 下已有 `auth.js`、`taskRunner.js` 先例。

状态与方法：

- `prefs`（服务端原始 JSON）、`loaded`（是否已完成首次拉取）
- `orderFor(panelKey, registry)` → 该面板的完整顺序数组（含隐藏列）：

  1. 取该面板已保存的 `order`；无配置则用 registry 默认顺序
  2. 剔除**陈旧 key**（不在 registry 里的，即列已删除）——渲染时忽略，但**不主动从存储里清理**（万一只是临时下线）
  3. 把 registry 里存在、但 `order` 里没有的**新列追加到末尾**（新列策略）
  4. 剔除 `available(auth)` 为假的列（角色闸门，与个人配置正交）

- `visibleOrder(panelKey, registry)` = `orderFor(...)` 再减去 `hidden`。这就是传给 `<template v-for>` 的数组。
- `settingsList(panelKey, registry)` = `orderFor(...)`（含隐藏列）——设置面板的列表用这个，**列表顺序 = 显示顺序**，所以取消勾选后该项留在原位，再勾回来就回原位。
- `toggle(panelKey, key, checked)` / `move(panelKey, fromIndex, toIndex)` / `reset(panelKey)`
  - `toggle` 只改 `hidden`，不动 `order`——这正是「隐藏保留原位置」得以成立的原因
  - `reset` = `order` 重置为 registry 默认顺序、`hidden` = `[]`
- 保存：变更后 **debounce 400ms** 发 `PUT`，整体提交该面板的 `order` + `hidden`。拖一次会连发十几个变更，不 debounce 就是一串请求。
  - 失败：`ElMessage.error` 提示，并把本地状态**回滚到上次服务端确认的状态**。不留「界面显示已保存、其实没存上」的假象。

**② `frontend/src/components/ColumnSettings.vue`** —— 设置面板 UI

- `el-popover` 形态沿用 `DataManageView.vue:30-43`。触发按钮放各面板现有的筛选栏里。
- 面板内是**单个列表**，每项：拖拽手柄 + 列名 + 勾选框。**列表顺序 = 显示顺序**。
- 拖拽用 **HTML5 原生**（`draggable="true"` + `dragstart` / `dragover` / `drop` / `dragend`）。`package.json` 无 sortablejs，不为一个 20 项以内的列表引入新依赖。
- 取消勾选 = 只往 `hidden` 里加 key，**不动 `order`**；所以该项在列表里保留原位置，再勾回来就回原位，不会跑到末尾。
- 底部「恢复默认」按钮：`order` 重置为 registry 默认顺序、`hidden` 置空。
- 守卫：**不允许取消勾选最后一列可见数据列**（否则表格只剩选择框与「操作」列，用户会以为界面坏了）。拦下时给 inline 提示。
- 锁定列（`selection`、「操作」）不进列表。

**③ `frontend/src/components/cells/SheetWriteCell.vue`**

写表单元格。markup 从 `AdsAccountPanel.vue:63-78` 与 `TtAccountPanel.vue:59-71` 逐字搬入（两者本就同构）。props：`row`、`failure`；emit：`retry`。语汇保持「⚠️ 点它即重试 / ✅ 已同步」不变。

**④ `frontend/src/components/cells/OwnerCell.vue`**

户归属单元格。markup 从 `AdsAccountPanel.vue:156-213` 与 `TtAccountPanel.vue:191-248` 逐字搬入。props：`row`；emit：`change`。

**`useOwnerPicker` 的调用点保留在各自面板内**，`OwnerCell` 只做展示 + emit。这样 GG/TT 的 `reassign` 实现差异仍在面板里注入，「只差 reassign 实现」这个现状不被打破。

**⑤ `frontend/src/constants/accountColumns.js`** —— 列元数据（单一真相源）

三个面板的 `COL_ATTRS` 集中放这一个文件，每项形如：

```js
{ key: 'acquired_date', label: '到手时间', prop: 'acquired_date', minWidth: 100, showOverflowTooltip: true }
{ key: 'owner', label: '户归属', width: 160, align: 'center', available: (auth) => auth.isHuguan }
```

- `available` 承接现有的角色闸门：TT 的「户归属」（`TtAccountPanel.vue:191`）与「换绑情况」（`:249`）现在是 `v-if="authStore.isHuguan"`，搬进注册表。GG 的「户归属」（`AdsAccountPanel.vue:156`）同理。
- 宽度一律沿用现有模板写死的 `min-width` / `width`，保证**零配置时视觉与现在逐像素一致**。
- 集中一处的价值：列清单只有一份真相源，且与 `py/column_prefs.py` 的 `PANELS` 常量能对照着看。

### 5.2 列清单

**GG `gg_ads`**（`AdsAccountPanel.vue:48-221`，10 列）

| key | 列名 | 单元格 |
|---|---|---|
| `name` | 账号名称 | 富（内联编辑） |
| `account_id` | 账号 ID | 纯 prop |
| `sheet_write` | 写表 | 富 → `SheetWriteCell` |
| `mcc` | 所属 MCC | 富 |
| `timezone` | 时区 | 富 |
| `agent` | 代理 | 富 |
| `status` | 状态 | 富 |
| `acquired_date` | 到手时间 | 纯 prop |
| `status_changed` | 状态变更时间 | 富 |
| `owner` | 户归属 | 富 → `OwnerCell`，`available: isHuguan` |

**TT `tt_ads`**（`TtAccountPanel.vue:52-258`，13 列）

| key | 列名 | 单元格 |
|---|---|---|
| `advertiser_id` | 广告账户 ID | 纯 prop |
| `sheet_write` | 写表 | 富 → `SheetWriteCell` |
| `bc` | 所属 BC | 富 |
| `timezone` | 时区 | 富 |
| `agent` | 代理 | 富 |
| `status` | 状态 | 富 |
| `country` | 国家 | 富 |
| `consumption` | 消耗情况 | 富 |
| `remark` | 备注 | 富 |
| `acquired_date` | 到手时间 | 纯 prop |
| `status_changed` | 状态变更时间 | 富 |
| `owner` | 户归属 | 富 → `OwnerCell`，`available: isHuguan` |
| `owner_change_note` | 换绑情况 | 富，`available: isHuguan` |

**FB `fb_ads`**（`FbAccountPanel.vue:52-83`，10 列）

| key | 列名 | 单元格 |
|---|---|---|
| `name` | 账户名 | 纯 prop |
| `account_id` | 账户ID | 纯 prop |
| `bms` | 所属BM | 富 |
| `location` | 位置 | 富 |
| `channel` | 所属渠道 | 富 |
| `asset_type` | 资产类型 | 富 |
| `status` | 状态 | 富 |
| `operator` | 操作人 | 纯 prop |
| `timezone` | 时区 | 纯 prop |
| `acquired_date` | 到手时间 | 纯 prop |

**锁定列（三面板一致）**：`selection`（勾选框）、`op`（「操作」列；FB 现有 `fixed="right"`，保持）。

### 5.3 各面板模板改法（三个同构）

```html
<el-table :data="store.accounts" @selection-change="…">
  <el-table-column type="selection" width="45" />            <!-- 锁定，位置固定 -->
  <template v-for="key in visibleOrder" :key="key">
    <!-- 富列：逐字搬入的单元格 markup 或抽出的组件 -->
    <el-table-column v-if="key === 'sheet_write'" v-bind="COL_ATTRS.sheet_write">
      <template #default="{ row }">
        <SheetWriteCell :row="row" :failure="sheetWriteFailures[row.account_id]"
                        @retry="retrySheetWrite(row)" />
      </template>
    </el-table-column>
    <el-table-column v-else-if="key === 'owner'" v-bind="COL_ATTRS.owner">
      <template #default="{ row }"><OwnerCell :row="row" @change="…" /></template>
    </el-table-column>
    <el-table-column v-else-if="key === 'mcc'" v-bind="COL_ATTRS.mcc">
      <template #default="{ row }"> …现有 markup 逐字不动… </template>
    </el-table-column>
    <!-- …其余富列同形… -->
    <!-- 纯 prop 列兜底 -->
    <el-table-column v-else v-bind="COL_ATTRS[key]" />
  </template>
  <el-table-column label="操作" width="200">…</el-table-column>  <!-- 锁定，位置固定 -->
</el-table>
```

**改动性质**：单元格业务逻辑一行不改，改的是「包一层 `<template v-for>` + 加一条 `v-if`」。diff 可以逐块核对。符合 CLAUDE.md 的纯增量原则。

---

## 6. 边界策略

| 场景 | 行为 |
|---|---|
| 用户没有任何配置 | 按注册表默认顺序，全部数据列可见（= 现在的样子） |
| 服务端读到的值类型不对 / JSON 坏 | `load_prefs` 返回 `{}`，前端走默认。**不抛 500** |
| 保存过的 key 代码里已不存在 | `visibleOrder` 与注册表求交集，自动忽略。**不主动清理**存量配置（万一只是临时下线） |
| 代码里新增了列，用户配置里没有 | 追加到末尾并可见（新列策略） |
| 用户角色变化（户管 → 普通用户） | `available` 过滤掉不该看的列。配置原样保留，角色变回来即恢复 |
| 用户想藏掉最后一列可见数据列 | 前端拦下并提示 |
| 未登录 / 令牌过期 | 走既有 `client.js` 拦截器，与其它接口一致 |
| 多标签页并发修改 | 后写覆盖先写，不做冲突检测（个人 UI 偏好，可接受） |

---

## 7. 测试与验证

### 7.1 后端（新增 `py/tests/test_column_prefs.py`）

- 读写往返：`PUT` 后 `GET` 拿到同样的 `order` 与 `hidden`
- `GET` 无配置 → `prefs: {}`
- **uid 隔离**：用户 A 保存后，用 B 的令牌读，拿不到 A 的配置
- `PUT` 只改一个面板时，其它面板配置不被清掉
- `hidden` 里含不在 `order` 中的 key → 该 key 被静默剔除，不是 400
- 参数非法 → 400：`panel` 不在白名单、`order`/`hidden` 不是 list、元素非 str、项数超 64、单项超 64 字符
- **畸形存量值不 500**：手工往 `config` 表塞字符串 / 数字 / 嵌套 list / 坏 JSON / 面板值是 list 而非 dict，`GET` 均降级为默认

### 7.2 前端（无测试基建）

`frontend/package.json` 里没有 test script，也没有前端测试框架。列显隐与拖序**只能走真实运行验证**，验收项：

1. 三个面板各做一次「藏列 → 拖序 → 刷新页面」，确认配置回读正确
2. **隐藏一列后刷新页面，该列必须仍是隐藏** —— 这是 `hidden` 字段与新列策略的回归用例，也是本设计自审时抓出来的那个缺陷（只存可见数组会把用户藏掉的列自动弹回来），必须实测
3. **换一个浏览器 profile 重新登录同一账号**，确认配置跟着账号走（证明是服务端而非 localStorage 假象）
4. 手工把浏览器 localStorage 清空后刷新，配置仍在
5. 用普通用户登录，确认 TT 的「户归属」「换绑情况」不在候选列表里
6. 藏到只剩一列可见数据列时，再取消勾选被拦下并提示
7. 取消勾选某一列再勾回来，该项回到列表原位置（而非末尾）

按既有要求：**未实际跑过的守卫不算绿**，上述每一项都要有实际执行的记录，不接受「代码看起来对」。

---

## 8. 风险

### 8.1 拖拽后列序是否即时生效（必须在实现第一步验证）

`getColumnIndex` 在 `onMounted` 时计算并作为闭包存进 `columnConfig`。对于**已经挂载的列**，element-plus 未必能察觉纯 DOM 重排（`:key="key"` 让 Vue 搬动 DOM 节点，但 store 里的列序可能不跟着更新）。

**不靠猜**——实现第一步就是写一个最小 spike 实测。若确实不生效，兜底方案：给 `<el-table>` 绑 `:key="orderKey"`，顺序变更时 bump `orderKey` 强制重挂载（列会在新 DOM 顺序下重新注册）。代价是丢选中态与滚动位置，但调序是用户的主动低频动作，可接受。

### 8.2 模板包裹的回归面

三个面板的表格结构都会被改动（包一层 + 加 `v-if` 链）。缓解：

- 单元格 markup **逐字不动**，diff 可逐块核对
- 零配置时列序与宽度与现状完全一致，视觉可对照
- 每个面板改完后立刻手测该面板的全部既有功能（内联改名、写表重试、MCC 切换、户归属改派、批量选择、操作列编辑/删除）

### 8.3 共享组件抽取引入的回归

`SheetWriteCell` / `OwnerCell` 抽出来后，GG/TT 的行为必须与抽取前逐字一致。缓解：markup 逐字搬移 + props/emit 映射表在实现计划里逐项列出，抽完对两个平台各测一遍。

---

## 附：决策过程

| # | 问题 | 用户决定 |
|---|---|---|
| 1 | 「角色」是动机还是需求 | 仅解释动机，只做个人自定义 |
| 2 | 配置存哪 | 服务端，绑定账号 |
| 3 | 覆盖哪些看板 | GG 广告账户 / TT 广告账户 / FB 账户 |
| 4 | 交互形态 | 勾选显隐 + 拖拽调序 |
| 5 | 锁定列 | 选择列 + 操作列锁死，其余全可配 |
| 6 | 实现方案 | A+（方案 A 打底，顺手抽两个已重复的单元格） |
| 7 | 新列上线策略 | 默认显示，追加到末尾 |
