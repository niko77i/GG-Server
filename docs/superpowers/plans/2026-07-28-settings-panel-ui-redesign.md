# SettingsPanel UI 美化实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 SettingsPanel.vue 设置页面从原始表格布局重构为卡片式 Tag 标签布局，提升视觉层次和交互体验

**Architecture:** 纯前端重构，单文件改动。Tab 1 用 `el-card` + `el-tag` 替代 `el-table`；Tab 2 用 `el-card` + 行列表替代 `el-table`；Tab 3 微调现有卡片。所有 CRUD 逻辑保持不变，仅适配新 UI 交互。

**Tech Stack:** Vue 3 + Element Plus 2.9 + Pinia（无新依赖）

## Global Constraints

- 不修改后端 API
- 不新增第三方依赖
- 不改变现有功能逻辑（CRUD 行为不变）
- 不重构 store 层
- 保持与项目现有设计风格一致（灰白配色 `#f5f7fa` 背景，`el-card` 卡片）

---

### Task 1: 选项管理改为 Tag 标签卡片模式

**Files:**
- Modify: `frontend/src/views/SettingsPanel.vue`（模板 + 脚本）

**Interfaces:**
- Consumes: `store.options.statuses/agents/mccLevels/salesPersons`（`{ id, name }[]`），`store[action](...)` CRUD 方法
- Produces: 新的 `editingTagId` reactive 对象替代旧的 `editing` 对象；新增 `addingOption` reactive 控制展开状态

- [ ] **Step 1: 重写 Tab 1 选项管理区域的模板**

将原有 4 个 `el-table` 区域替换为 4 张 `el-card`，每张卡片内用 `el-tag` 展示选项。每张卡片结构相同，以"账户状态选项"为例：

```html
<!-- Tab 1: 账户设置 -->
<el-tab-pane label="账户设置" name="account">
  <p style="color:#909399;font-size:13px;margin-bottom:20px;">自定义下拉框选项，双击标签编辑名称，点击 × 删除</p>

  <!-- 4 张选项卡片 2x2 网格 -->
  <el-row :gutter="16">
    <el-col :span="12" v-for="card in optionCards" :key="card.key">
      <el-card shadow="never" style="margin-bottom:16px;">
        <template #header>
          <div style="display:flex;align-items:center;justify-content:space-between;">
            <span style="font-weight:600;font-size:14px;">{{ card.icon }} {{ card.label }}</span>
            <el-tag size="small" type="info" round>{{ store.options[card.key].length }} 项</el-tag>
          </div>
        </template>

        <!-- Tag 标签区 -->
        <div style="display:flex;flex-wrap:wrap;gap:8px;min-height:32px;align-items:center;">
          <template v-if="store.options[card.key].length">
            <el-tag
              v-for="item in store.options[card.key]"
              :key="item.id"
              :type="card.tagType"
              closable
              size="default"
              @close="handleDelete(card.key, item)"
              @dblclick="startTagEdit(card.key, item)"
              style="cursor:pointer;user-select:none;"
            >
              <template v-if="editingTagId[card.key] === item.id">
                <el-input
                  v-model="item._editName"
                  size="small"
                  style="width:80px;"
                  @blur="finishTagEdit(card.key, item)"
                  @keyup.enter="finishTagEdit(card.key, item)"
                  @click.stop
                  ref="tagInputRef"
                />
              </template>
              <span v-else>{{ item.name }}</span>
            </el-tag>
          </template>
          <span v-else style="color:#c0c4cc;font-size:13px;">暂无选项</span>

          <!-- 新增：展开输入或 + 按钮 -->
          <template v-if="addingOption[card.key]">
            <el-input
              v-model="newOptionNames[card.key]"
              size="small"
              :placeholder="card.addPlaceholder"
              style="width:100px;"
              @keyup.enter="addOption(card.key)"
              @blur="cancelAddOption(card.key)"
              ref="addInputRef"
            />
            <el-button size="small" type="primary" @click="addOption(card.key)" :loading="addingLoading">确认</el-button>
          </template>
          <el-button v-else size="small" circle @click="showAddInput(card.key)" style="width:24px;height:24px;font-size:14px;">+</el-button>
        </div>
      </el-card>
    </el-col>
  </el-row>

  <!-- 充值表配置卡片（仅管理员） -->
  ...
</el-tab-pane>
```

- [ ] **Step 2: 新增 `optionCards` 配置和新的响应式变量**

在 `<script setup>` 中，替换旧的 `editing` 对象，新增卡片配置：

```js
// ---- 选项卡片配置 ----
const optionCards = [
  { key: 'statuses',     icon: '📊', label: '账户状态选项',  tagType: '',        addPlaceholder: '新状态名' },
  { key: 'agents',       icon: '🏷', label: '代理名选项',    tagType: 'success', addPlaceholder: '新代理名' },
  { key: 'mccLevels',    icon: '📈', label: 'MCC 等级选项',  tagType: 'warning', addPlaceholder: '新等级名' },
  { key: 'salesPersons', icon: '👤', label: '商务人员选项',  tagType: 'info',    addPlaceholder: '新商务人名' },
]

// Tag 编辑状态：{ statuses: null|itemId, agents: null|itemId, ... }
const editingTagId = reactive({ statuses: null, agents: null, mccLevels: null, salesPersons: null })
// 新增输入展开状态
const addingOption = reactive({ statuses: false, agents: false, mccLevels: false, salesPersons: false })
const addingLoading = ref(false)

const newOptionNames = reactive({ statuses: '', agents: '', mccLevels: '', salesPersons: '' })
```

- [ ] **Step 3: 重写选项 CRUD 交互函数**

替换旧的 `startEdit`/`finishEdit`/`addOption`/`deleteOption`，适配 Tag 交互：

```js
// ---- Tag 标签交互 ----
function startTagEdit(type, item) {
  item._editName = item.name
  editingTagId[type] = item.id
  // 下一帧自动聚焦 input（通过 ref 处理）
}

function cancelTagEdit(type, item) {
  editingTagId[type] = null
  delete item._editName
}

async function finishTagEdit(type, item) {
  const newName = (item._editName || '').trim()
  editingTagId[type] = null
  delete item._editName
  if (!newName || newName === item.name) return

  const actions = { statuses: 'renameStatus', agents: 'renameAgent', mccLevels: 'renameMccLevel', salesPersons: 'renameSalesPerson' }
  try {
    await store[actions[type]](item.id, newName)
    ElMessage.success('已更新')
  } catch (e) { ElMessage.error(e.response?.data?.error || '更新失败') }
}

function showAddInput(type) {
  addingOption[type] = true
  newOptionNames[type] = ''
}

function cancelAddOption(type) {
  if (newOptionNames[type].trim()) return // 有内容时不取消，等用户确认
  addingOption[type] = false
}

async function addOption(type) {
  const name = newOptionNames[type].trim()
  if (!name) { ElMessage.warning('请输入名称'); return }
  const actions = { statuses: 'createStatus', agents: 'createAgent', mccLevels: 'createMccLevel', salesPersons: 'createSalesPerson' }
  try {
    await store[actions[type]](name)
    newOptionNames[type] = ''
    addingOption[type] = false
    ElMessage.success('已添加')
  } catch (e) { ElMessage.error(e.response?.data?.error || '添加失败') }
}

async function handleDelete(type, item) {
  try {
    await ElMessageBox.confirm(`确定删除「${item.name}」吗？`, '确认删除', {
      confirmButtonText: '删除',
      cancelButtonText: '取消',
      type: 'warning',
    })
  } catch { return } // 用户取消

  const actions = { statuses: 'deleteStatus', agents: 'deleteAgent', mccLevels: 'deleteMccLevel', salesPersons: 'deleteSalesPerson' }
  try {
    await store[actions[type]](item.id)
    ElMessage.success('已删除')
  } catch (e) {
    if (e.response?.status === 409) {
      ElMessage.warning(e.response?.data?.error || '无法删除')
    } else {
      ElMessage.error(e.response?.data?.error || '删除失败')
    }
  }
}
```

- [ ] **Step 4: 添加 import ElMessageBox**

在现有 import 中添加：

```js
import { ElMessage, ElMessageBox } from 'element-plus'
```

- [ ] **Step 5: 删除旧代码**

移除以下不再使用的旧代码：
- `editing` reactive 对象
- 旧的 `startEdit`、`finishEdit`、`addOption`、`deleteOption` 函数（它们被 Task 3 中的新版本替代）

- [ ] **Step 6: 验证 Tab 1 交互**

启动 dev server 验证：
- Tag 标签正确展示所有选项
- 双击 Tag 进入编辑模式，失焦/回车保存
- 点击 Tag × 弹出确认框，确认后删除
- 点击 + 按钮展开新增输入，回车确认添加
- 管理员可见充值表配置区域

---

### Task 2: 充值表配置卡片美化

**Files:**
- Modify: `frontend/src/views/SettingsPanel.vue`（模板部分）

**Interfaces:**
- Consumes: `authStore.isAdmin`, `authStore.isDeveloper`, `form`, `SHEET_MAPPING_META`, `sheetOptions`, `sheetOptionsLoaded`
- Produces: 无新接口

- [ ] **Step 1: 用 el-card 包裹充值表配置区域**

将原有 `el-divider` + 裸表单 改为独立卡片：

```html
<template v-if="authStore.isAdmin || authStore.isDeveloper">
  <el-card shadow="never" style="margin-top:20px;border-left:3px solid #0891b2;">
    <template #header>
      <span style="font-weight:600;">📊 充值表配置</span>
      <el-tag size="small" type="warning" style="margin-left:8px;">仅管理员</el-tag>
    </template>

    <!-- Google Sheets URL -->
    <div style="margin-bottom:16px;">
      <div style="font-weight:500;font-size:13px;color:#374151;margin-bottom:6px;">Google Sheets（URL 或 ID）</div>
      <div style="display:flex;gap:8px;">
        <el-input v-model="form.recharge_sheet_id" placeholder="粘贴表格链接或直接输入 spreadsheet ID" style="flex:1;" />
        <el-button @click="readSheets" :loading="readingSheets">📋 读取工作表</el-button>
      </div>
    </div>

    <!-- Sheet 映射 -->
    <div style="margin-bottom:16px;">
      <div style="font-weight:500;font-size:13px;color:#374151;margin-bottom:6px;">Sheet 映射</div>
      <div style="background:#f9fafb;border-radius:8px;padding:12px;">
        <div v-for="(meta, key) in SHEET_MAPPING_META" :key="key" style="display:flex;align-items:center;gap:8px;margin-bottom:8px;">
          <span style="white-space:nowrap;font-size:13px;min-width:60px;color:#374151;">{{ meta.label }}</span>
          <el-select
            v-model="form.sheet_mappings[key]"
            filterable allow-create default-first-option
            placeholder="选择或输入 sheet 名"
            style="flex:1;"
          >
            <el-option v-for="name in sheetOptions" :key="name" :label="name" :value="name" />
          </el-select>
        </div>
        <span v-if="!sheetOptionsLoaded" style="font-size:11px;color:#909399;">点击「📋 读取工作表」加载可选 sheet 列表，也可直接手动输入</span>
        <span v-else style="font-size:11px;color:#059669;">✅ 已加载 {{ sheetOptions.length }} 个工作表可供选择</span>
      </div>
    </div>

    <el-button type="primary" @click="save" :loading="saving">💾 保存配置</el-button>
    <span v-if="msg" style="margin-left:8px;font-size:12px;color:#059669;">{{ msg }}</span>
  </el-card>
</template>
```

注意：保留完整的 `SHEET_MAPPING_META` 迭代及 `addMapping`/`removeMapping` 逻辑。

---

### Task 3: 地区时区改为卡片列表

**Files:**
- Modify: `frontend/src/views/SettingsPanel.vue`（模板部分）

**Interfaces:**
- Consumes: `regionList`, `timezoneOptions`, `newRegionName`, `newRegionTz`, `saveRegionTz`, `addRegion` 函数（保持不变）
- Produces: 新增 `deletingRegion` ref，复用现有 `saveRegionTz`/`addRegion`

- [ ] **Step 1: 重写 Tab 2 模板**

将 `el-table` 替换为卡片式行列表：

```html
<el-tab-pane label="地区时区" name="region">
  <p style="color:#909399;font-size:13px;margin-bottom:16px;">地区对应的时区，产品数据分析时使用</p>

  <el-card shadow="never" style="max-width:600px;">
    <template #header>
      <div style="display:flex;align-items:center;justify-content:space-between;">
        <span style="font-weight:600;font-size:14px;">🌍 地区时区配置</span>
        <el-tag size="small" type="info" round>{{ regionList.length }} 个地区</el-tag>
      </div>
    </template>

    <!-- 地区列表 -->
    <div v-if="regionList.length">
      <div
        v-for="row in regionList"
        :key="row.id"
        style="display:flex;align-items:center;gap:12px;padding:10px 12px;border-bottom:1px solid #f3f4f6;transition:background 0.15s;"
        class="region-row"
      >
        <span style="flex:0 0 100px;font-size:14px;font-weight:500;color:#374151;">{{ row.name }}</span>
        <el-select
          v-model="row._editTz"
          placeholder="选择时区"
          size="small"
          style="flex:1;"
          filterable
          @change="v => saveRegionTz(row, v)"
        >
          <el-option v-for="tz in timezoneOptions" :key="tz" :label="tz" :value="tz" />
        </el-select>
        <el-button
          size="small"
          type="danger"
          :icon="Delete"
          circle
          text
          @click="deleteRegion(row)"
          style="opacity:0;transition:opacity 0.15s;"
          class="region-delete-btn"
        />
      </div>
    </div>
    <div v-else style="text-align:center;padding:20px;color:#c0c4cc;">
      <span style="font-size:13px;">暂无地区配置</span>
    </div>

    <!-- 新增行 -->
    <div style="display:flex;align-items:center;gap:12px;padding:10px 12px;background:#f9fafb;border-radius:6px;margin-top:8px;">
      <el-input v-model="newRegionName" placeholder="新地区名" size="small" style="flex:0 0 100px;" @keyup.enter="addRegion" />
      <el-select v-model="newRegionTz" placeholder="时区" size="small" style="flex:1;" filterable>
        <el-option v-for="tz in timezoneOptions" :key="tz" :label="tz" :value="tz" />
      </el-select>
      <el-button size="small" type="primary" @click="addRegion">新增</el-button>
    </div>
  </el-card>
</el-tab-pane>
```

- [ ] **Step 2: 新增删除地区函数和样式**

```js
// 在 script setup 中添加
import { Delete } from '@element-plus/icons-vue'

async function deleteRegion(row) {
  try {
    await ElMessageBox.confirm(`确定删除地区「${row.name}」吗？`, '确认删除', {
      confirmButtonText: '删除',
      cancelButtonText: '取消',
      type: 'warning',
    })
  } catch { return }

  try {
    await api.delete(`/regions/${row.id}`)
    const idx = regionList.value.findIndex(r => r.id === row.id)
    if (idx >= 0) regionList.value.splice(idx, 1)
    ElMessage.success('已删除')
  } catch (e) { ElMessage.error('删除失败: ' + (e.response?.data?.error || e.message)) }
}
```

- [ ] **Step 3: 在末尾添加 scoped style**

```html
<style scoped>
.region-row:hover {
  background: #f9fafb;
}
.region-row:hover .region-delete-btn {
  opacity: 1 !important;
}
</style>
```

---

### Task 4: Tab 3 数据管理微调

**Files:**
- Modify: `frontend/src/views/SettingsPanel.vue`（模板部分）

- [ ] **Step 1: 美化导入/导出卡片**

将现有 `el-row` 卡片改为 `el-card shadow="never"`，统一风格：

```html
<el-tab-pane label="数据管理" name="data">
  <el-row :gutter="16">
    <!-- 导出 -->
    <el-col :span="12">
      <el-card shadow="never">
        <template #header>
          <span style="font-weight:600;">📤 导出数据</span>
        </template>
        <p style="color:#909399;font-size:13px;margin-bottom:12px;">导出你的所有数据为 JSON 文件，可用于备份或迁移。</p>
        <el-button type="primary" @click="exportData" :loading="exporting">📥 导出我的数据</el-button>
      </el-card>
    </el-col>

    <!-- 导入 -->
    <el-col :span="12">
      <el-card shadow="never">
        <template #header>
          <span style="font-weight:600;">📥 导入数据</span>
        </template>
        <p style="color:#909399;font-size:13px;margin-bottom:12px;">上传 ImageCrawling 的 app.db 或 JSON 导出文件。</p>
        <el-upload
          :auto-upload="false"
          :on-change="onFileChange"
          :limit="1"
          accept=".db,.json"
          drag
        >
          <el-icon style="font-size:24px;color:#0891b2;"><UploadFilled /></el-icon>
          <div style="margin-top:8px;font-size:13px;color:#606266;">拖拽或点击上传 <b>.db</b> / <b>.json</b> 文件</div>
        </el-upload>
        <el-button
          type="success"
          @click="confirmImport"
          :loading="importing"
          :disabled="!importFile"
          style="margin-top:12px;"
        >✅ 确认导入</el-button>
      </el-card>
    </el-col>
  </el-row>

  <!-- 导入历史 -->
  <el-card shadow="never" style="margin-top:16px;">
    <template #header>
      <span style="font-weight:600;">📋 导入历史</span>
    </template>
    <!-- 原有 el-table 和 el-empty 保持不变 -->
  </el-card>
</el-tab-pane>
```

---

### Task 5: 清理与最终验证

**Files:**
- Modify: `frontend/src/views/SettingsPanel.vue`

- [ ] **Step 1: 删除脚本中不再使用的旧变量和函数**

确认以下代码已移除：
- `editing` reactive 对象（已由 `editingTagId` 替代）
- 旧的 `startEdit` 函数
- 旧的不再引用的交互函数

- [ ] **Step 2: 启动 dev server 全面验证**

```bash
cd frontend && npm run dev
```

逐项检查：
1. Tab 1: 4 张卡片正常渲染，Tag 颜色区分，双击编辑，× 删除（含确认弹窗），+ 新增
2. Tab 1: 管理员可见充值表卡片，URL 输入、读取工作表、Sheet 映射下拉、保存
3. Tab 2: 地区列表卡片展示，时区下拉切换，hover 显示删除按钮，新增行
4. Tab 3: 导入/导出卡片风格统一，导入历史表格正常

- [ ] **Step 3: 检查控制台无报错**

确认无 Vue 警告、无未使用的 import、无 undefined 引用。

- [ ] **Step 4: 提交**

```bash
git add frontend/src/views/SettingsPanel.vue
git commit -m "style: 美化设置页面为卡片式 Tag 标签布局"
```
