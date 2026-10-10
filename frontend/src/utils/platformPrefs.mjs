// 平台上下文（GG / TT / FB）的判据 —— 纯逻辑，供 node --test 覆盖。
//
// 为什么单独成模块：store 依赖 pinia 与 localStorage、api/client.js 依赖 axios，在 node 里都跑不动；
// 而真正需要被钉住的判据都是纯函数。
//
// **两个信号别混用**（2026-10-11 修 bug 时踩过）：
//   - `platformFromPath`  —— **请求层**的规则：请求总得带一个平台，所以"其余一律 gg"是对的默认。
//   - `platformFamily`    —— **store（侧边栏/导航）**的规则：只认路由**自己声明**的平台族。
//     路由没声明（`/profile`、`/analysis`、`/toolkit/*`、`/admin/*`）就必须返回 null，
//     否则 TT/FB 的用户点「个人信息」「数据分析」会被**连平台一起按回 GG**（刷新还会丢平台）。
//
// 背景：`currentPlatform` 原先只活在内存里（初值硬编码 'gg'、setPlatform 不落盘、initFromStorage
// 不恢复）⇒ 整页刷新后，可切换平台的角色（户管/开发者）会静默掉回 GG，而页面还在刷新前那张表
// ⇒ 侧边栏、导航、路由守卫、筛选器全按 GG 算：看着是 TT、实际是 GG。
export const PLATFORMS = ['gg', 'tt', 'fb']

/** localStorage 的键名（与 store 共用一个常量，避免两边写错字符串）。 */
export const PLATFORM_KEY = 'currentPlatform'

/** 白名单回落：非法值 / 缺失 / 非字符串一律 'gg'（脏值绝不进 store）。 */
export function sanitizePlatform(value) {
  return PLATFORMS.includes(value) ? value : 'gg'
}

/**
 * **请求层**用：路径 → 该请求该带的 platform 参数；`/admin/users`（有独立平台 Tab）返回 null
 * 表示"不带该参数"。其余路径一律落到 'gg' —— 请求侧必须有个默认值，这是刻意的。
 * 与 `api/client.js` 改动前的内联写法**逐字等价**。
 *
 * ⚠️ **不要**拿它当 store 的平台权威（见文件头）：`/profile`、`/analysis` 这类中性页会被它判成 gg。
 */
export function platformFromPath(path) {
  const p = String(path || '')
  if (p.startsWith('/admin/users')) return null
  if (p.startsWith('/tt')) return 'tt'
  if (p.startsWith('/fb')) return 'fb'
  return 'gg'
}

/**
 * **store 用**：路由的**平台族**信号，来自 `to.meta.platform`（路由自己的声明）。
 * 路由没声明平台 ⇒ **返回 null = "路由没有意见"**，此时平台保持不变（不动、更不落盘）。
 *
 * 这正是中性路由（`/profile`、`/analysis`、`/toolkit/*`、`/admin/*`）必须走的那条：
 * 它们可能从任意平台的导航里点进来，把平台按成某个固定值就是回归（2026-10-11 代码审查抓到）。
 */
export function platformFamily(metaPlatform) {
  return PLATFORMS.includes(metaPlatform) ? metaPlatform : null
}

/**
 * 水合（刷新后 / 换号后）时的平台，**唯一权威**：
 * 可切换角色用存下来的值（刷新不该改变你正在看的平台）；其余角色一律取 `user.platform`，
 * **无视存储**（同一浏览器换号时存储里可能还留着上一个人的平台）。
 *
 * 路由不在这个函数里：它经 `router.afterEach` → `syncPlatformFromRoute` 单独校正，
 * 因为首帧导航是异步的（守卫经微任务），水合这一刻路由还没解析。
 */
export function resolvePlatform({ stored, canSwitch, userPlatform }) {
  return canSwitch ? sanitizePlatform(stored) : sanitizePlatform(userPlatform)
}
