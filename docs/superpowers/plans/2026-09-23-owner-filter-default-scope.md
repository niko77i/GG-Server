# 「归属人」默认作用域 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让 developer / admin 进入账户类面板时，「归属人」下拉默认选中自己；户管保持「全部」，且「全部」始终可手动选回。

**Architecture:** 纯前端。把「默认作用域该取谁」抽成一个无副作用的纯函数放进 `src/utils/`（与既有的 `statusTag.js` 同一惯例，便于不引入测试框架也能跑验证），再由 8 个面板共用的 `OwnerFilterSelect.vue` 在身份就绪时调用一次。后端一行不改。

**Tech Stack:** Vue 3 `<script setup>` + Pinia + Element Plus；Vite 构建；Node 18 验证脚本。

## Global Constraints

- **纯增量**：不改 8 个面板组件、不改 `stores/accounts.js`、不改 `stores/auth.js`、不改任何后端文件（`py/` 零改动）。
- **户管口径不变**：`role === 'huguan'` 时默认值恒为 `''`（全部用户）。
- **「全部」必须仍可达**：默认值只在父组件尚无值时套用一次；用户手动清空或另选后不得被改回。
- **跨平台不默认自己**：`user.platform !== effectivePlatform` 时返回 `''`，否则会出现空表。
- **提交信息**按仓库既有约定使用中文 `feat:` / `fix:` 前缀。

---

### Task 1: 抽出纯函数 `defaultOwnerScope`

**Files:**
- Create: `frontend/src/utils/ownerScope.js`
- Verify（临时，仓库外）: `D:/server/cc/_gghist/verify_owner_scope.mjs`

**Interfaces:**
- Consumes: 无
- Produces: `defaultOwnerScope(user, effectivePlatform) => number | ''`
  - `user`: `{ id: number, role: string, platform: string } | null`
  - `effectivePlatform`: `'gg' | 'fb' | 'tt'`
  - 返回本人 `id` 表示「默认选自己」，返回 `''` 表示「默认全部用户」

- [ ] **Step 1: 写纯函数**

创建 `frontend/src/utils/ownerScope.js`：

```js
/**
 * 账户类面板「归属人」下拉的默认作用域。
 *
 * developer / admin 进本平台面板时默认选中自己；户管与跨平台场景保持「全部用户」。
 *
 * 为什么带平台条件：开发者可跨平台切面板，但本人在别的平台可能一个户都没有
 * （例如 GG 的开发者切到 TT 面板）。若无条件默认选自己，那边就是空表 —— 比默认「全部」更糟。
 *
 * @param {{id:number, role:string, platform:string}|null} user 当前登录用户
 * @param {string} effectivePlatform 当前所看面板的平台（'gg' | 'fb' | 'tt'）
 * @returns {number|string} 默认 owner_id；'' 表示「全部用户」
 */
export function defaultOwnerScope(user, effectivePlatform) {
  if (!user || !user.id) return ''
  // 户管保持「全部」（用户裁定）；其余非跨用户角色本就不显示该下拉
  if (user.role !== 'developer' && user.role !== 'admin') return ''
  // 跨平台面板不默认自己：本人可能在该平台一个户都没有，默认自己会得到空表
  if (user.platform !== effectivePlatform) return ''
  return user.id
}
```

- [ ] **Step 2: 写验证脚本（仓库外，避免污染项目）**

创建 `D:/server/cc/_gghist/verify_owner_scope.mjs`：

```js
// 通过读取源码 + 去 export 后 eval，绕开 package.json 无 "type":"module" 的限制
import fs from 'node:fs'

const SRC = 'D:/server/cc/GG-Server/frontend/src/utils/ownerScope.js'
const src = fs.readFileSync(SRC, 'utf8')
const defaultOwnerScope = new Function(src.replace(/^export /gm, '') + '\nreturn defaultOwnerScope')()

const cases = [
  // [说明, user, effectivePlatform, 期望]
  ['developer 本平台 → 自己', { id: 1, role: 'developer', platform: 'gg' }, 'gg', 1],
  ['developer 跨平台 → 全部', { id: 1, role: 'developer', platform: 'gg' }, 'tt', ''],
  ['admin 本平台 → 自己', { id: 4, role: 'admin', platform: 'gg' }, 'gg', 4],
  ['admin 跨平台 → 全部', { id: 4, role: 'admin', platform: 'gg' }, 'tt', ''],
  ['huguan 本平台 → 全部', { id: 26, role: 'huguan', platform: 'gg' }, 'gg', ''],
  ['huguan 跨平台 → 全部', { id: 26, role: 'huguan', platform: 'gg' }, 'tt', ''],
  ['普通用户 → 全部', { id: 5, role: 'user', platform: 'gg' }, 'gg', ''],
  ['未登录（null）→ 全部', null, 'gg', ''],
  ['用户对象无 id → 全部', { role: 'developer', platform: 'gg' }, 'gg', ''],
]

let fail = 0
for (const [name, user, plat, want] of cases) {
  const got = defaultOwnerScope(user, plat)
  const ok = got === want
  if (!ok) fail++
  console.log(`${ok ? 'PASS' : 'FAIL'}  ${name}  期望=${JSON.stringify(want)} 实得=${JSON.stringify(got)}`)
}
console.log(fail === 0 ? `\n全部 ${cases.length} 条通过` : `\n${fail} 条失败`)
process.exit(fail === 0 ? 0 : 1)
```

- [ ] **Step 3: 运行验证，确认全部通过**

Run: `node D:/server/cc/_gghist/verify_owner_scope.mjs`
Expected: 9 行 `PASS`，末行 `全部 9 条通过`，退出码 0。

- [ ] **Step 4: 提交**

```bash
cd /d/server/cc/GG-Server
git add frontend/src/utils/ownerScope.js
git commit -m "feat: 抽出「归属人」默认作用域判定（developer/admin 默认自己，户管保持全部）"
```

---

### Task 2: 组件接入默认值

**Files:**
- Modify: `frontend/src/components/OwnerFilterSelect.vue`

**Interfaces:**
- Consumes: `defaultOwnerScope(user, effectivePlatform)`（Task 1）
- Produces: 无对外接口变化；组件行为变为「首次挂载时，若父组件未设值则自动 emit 默认 owner_id」

- [ ] **Step 1: 改 import 与 props 接收**

把 `frontend/src/components/OwnerFilterSelect.vue` 的 `<script setup>` 开头改为：

```js
import { ref, computed, watch } from 'vue'
import { useAuthStore } from '@/stores/auth'
import api from '@/api/client'
import { defaultOwnerScope } from '@/utils/ownerScope'

const props = defineProps({ modelValue: { type: [String, Number], default: '' } })
const emit = defineEmits(['update:modelValue', 'change'])
```

（原为 `defineProps({...})` 未接收返回值，现改为 `const props =` 以便在函数内读取。）

- [ ] **Step 2: 在既有 watch 内套用默认作用域**

把既有的 watch 替换为：

```js
// ★ 关键：身份水合必须赶在面板首次 load() 之前。
// App.vue 把 initFromStorage 放在根组件 onMounted，而子组件 setup 恒早于父组件 onMounted；
// 面板的首次 load() 就在父组件 onMounted 里 —— 若等到 watch 触发才写默认值，
// GG/MCC 面板的 dedupLoader 会把那次 change 吞掉（首次请求仍在途 → 返回同一 Promise，不重发），
// 表现为「下拉显示自己、表格却是全部用户」的静默错数据。故先幂等补一次水合。
if (!auth.user) auth.initFromStorage()

// 身份就绪后：拉用户列表 + 首次套用默认作用域
watch(
  () => auth.user?.id,
  (uid) => {
    if (uid && visible.value) {
      fetchUsers()
      applyDefaultScope()
    }
  },
  { immediate: true }
)

// 首次进入面板时套用默认作用域（developer/admin → 自己；户管 → 全部）。
// 只在父组件尚无值时生效：用户手动清空或另选后不会被打回（watch 只认 user.id 变化）。
function applyDefaultScope() {
  const v = props.modelValue
  if (v !== '' && v !== null && v !== undefined) return
  const def = defaultOwnerScope(auth.user, auth.effectivePlatform)
  if (def !== '') onChange(def)
}
```

`fetchUsers()` / `onChange()` / `visible` 原样保留，不改动。

- [ ] **Step 3: 构建校验（SFC 编译 + 语法）**

Run: `cd /d/server/cc/GG-Server/frontend && npm run build`
Expected: 构建成功，无 `error`；产物输出到 `dist/`。

- [ ] **Step 4: 提交**

```bash
cd /d/server/cc/GG-Server
git add frontend/src/components/OwnerFilterSelect.vue
git commit -m "feat: 账户面板「归属人」默认作用域（developer/admin 默认自己，户管保持全部）"
```

---

### Task 3: 验收与回归

**Files:**
- Verify only（无代码改动，除非验收发现问题）

**Interfaces:**
- Consumes: Task 1 + Task 2 的成果
- Produces: 验收结论

- [ ] **Step 1: 后端回归（确认零影响）**

Run: `cd /d/server/cc/GG-Server/py && python -m pytest tests/ -q`
Expected: `420 passed`（本次未动后端，作为兜底）

- [ ] **Step 2: 手工验收矩阵**

启动前端（`cd frontend && npm run dev`），按下列矩阵逐一核对：

| # | 身份 | 面板 | 期望 |
|---|---|---|---|
| 1 | 卡尔 / developer / gg | GG 广告账户 | 下拉默认「卡尔」，状态统计变为其名下户数（不再是 99） |
| 2 | 卡尔 / developer / gg | 切到 TT 广告账户 | 下拉为「全部用户」，**不得**是空表 |
| 3 | 阿伟 / admin / gg | GG 广告账户 | 默认「阿伟」 |
| 4 | 阿伟 / admin / gg | 地址栏直敲 `/tt/accounts` | 被路由守卫弹回本平台 |
| 5 | 黎明 / admin / tt | TT 广告账户 | 默认「黎明」 |
| 6 | 户部尚书 / huguan / gg | GG / FB / TT 账户面板 | 一律「全部用户」**（关键回归，不得改变）** |
| 7 | 卡尔 / developer / gg | GG 广告账户 → 点下拉 × 清空 | 切回「全部用户」，且不被自动打回自己 |
| 8 | 卡尔 / developer / gg | GG 广告账户 → 手动选「阿伟」 | 按其筛选，不被覆盖 |
| 9 | 卡尔 / developer / gg | GG「MCC 管理」 | 同样默认「卡尔」（验证 8 处统一） |

- [ ] **Step 3: 若验收发现问题 → 修复后重跑 Step 1、Step 2**

- [ ] **Step 4: 代码审查**

按 CLAUDE.md 要求，调用 `/code-review` 对本次改动做审查，修复发现的问题。

- [ ] **Step 5: 收尾提交（仅当有修复或文档更新时）**

```bash
cd /d/server/cc/GG-Server
git add -A
git commit -m "docs: 补充「归属人」默认作用域设计与实现计划"
```

---

## 备注

- 临时验证脚本 `D:/server/cc/_gghist/verify_owner_scope.mjs` 留在仓库外，不进版本库。
- 已知边界（设计文档 §3.3）：同平台但名下 0 户的用户（如 GG 的 阿信/柠檬/蜻蜓）仍会看到空表。不为此加自动回退逻辑 —— 下拉点 × 即回「全部」，且自动回退会造成「有时默认我、有时默认全部」的不可预期行为。
- 本次**不含**：69 户 `status_id` 悬空的数据订正、`COALESCE(st.name,'存活')` 显示层掩盖问题。二者为独立议题，已有取证结论，另行裁定。
