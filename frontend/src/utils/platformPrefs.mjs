// 平台上下文（GG / TT / FB）的判据 —— 纯逻辑，供 node --test 覆盖，并供 **store 与 api 层共用**。
//
// 为什么单独成模块：store 依赖 pinia 与 localStorage、api/client.js 依赖 axios，在 node 里都跑不动；
// 而真正需要被钉住的判据（路径→平台、白名单回落、按角色归一）都是纯函数。
//
// 背景（2026-10-11 修的 bug）：`currentPlatform` 原先只活在内存里（初值硬编码 'gg'、setPlatform 不落盘、
// initFromStorage 不恢复）⇒ **整页刷新后，可切换平台的角色（户管/开发者）会静默掉回 GG**，
// 而页面还在刷新前那张表 ⇒ 侧边栏、导航、路由守卫、筛选器全按 GG 算：看着是 TT、实际是 GG。
// 另一条相关事实：**请求侧的平台**一直是从 URL 推的（见 api/client.js）——两处口径必须一致，
// 否则就会出现「数据是 TT、导航是 GG」这种割裂。
export const PLATFORMS = ['gg', 'tt', 'fb']

/** localStorage 的键名（与 store 共用一个常量，避免两边写错字符串）。 */
export const PLATFORM_KEY = 'currentPlatform'

/** 白名单回落：非法值 / 缺失 / 非字符串一律 'gg'（脏值绝不进 store）。 */
export function sanitizePlatform(value) {
  return PLATFORMS.includes(value) ? value : 'gg'
}

/**
 * 路径 → 平台；**路由没有"意见"时返回 null**，由调用方决定兜底（而不是硬按一个平台上去）。
 *
 * 这是**唯一一份**路径推导规则，`api/client.js`（请求参数）与 store（侧边栏/导航）共用。
 * ⚠️ `/admin/users` 必须返回 null：用户管理页有自己的平台 Tab 显式控制平台，按路径推断会把它
 * 误判成 gg，导致该页的「全部」看不到其它平台（该页的历史 bug，见 api/client.js 的注释）。
 * ⚠️ 空路径 / 根路径也返回 null：首帧路由尚未解析、根路径会重定向到平台首页，此时按 gg 会**凭空**
 * 把平台按到 GG 上。
 */
export function platformFromPath(path) {
  const p = String(path || '')
  if (!p || p === '/') return null
  if (p.startsWith('/admin/users')) return null
  if (p.startsWith('/tt')) return 'tt'
  if (p.startsWith('/fb')) return 'fb'
  return 'gg'
}

/**
 * 平台优先级的**唯一权威**：非切换角色取账号自带平台；可切换角色则 **路由 > 存储 > 'gg'**。
 *
 * - **非切换角色**（admin / viewer / user）：平台由账号决定（与 store 的 `effectivePlatform` 同一口径），
 *   **无视存储与路由**。理由是同一浏览器换号时存储里可能还留着上一个人的平台。
 * - **可切换角色**（户管 / 开发者）：路由说了算（切平台本来就是导航）；路由没意见时用存下来的值
 *   —— 这正是本 bug 要修的：刷新不该改变你正在看的平台。
 */
export function resolvePlatform({ stored, routePath, canSwitch, userPlatform }) {
  if (!canSwitch) return sanitizePlatform(userPlatform)
  return platformFromPath(routePath) || sanitizePlatform(stored)
}
