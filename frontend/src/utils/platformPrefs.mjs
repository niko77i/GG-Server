// 平台上下文（GG / TT / FB）的持久化口径 —— 纯逻辑，供 node --test 覆盖。
//
// 为什么单独成模块：store 依赖 pinia 与 localStorage，在 node 里跑不动；而真正需要被钉住的
// 判据（白名单回落、按角色归一）都是纯函数。
//
// 背景（2026-10-11 修的 bug）：`currentPlatform` 原先只活在内存里（初始值硬编码 'gg'、
// setPlatform 不落盘、initFromStorage 不恢复）⇒ **整页刷新后，可切换平台的角色（户管/开发者）
// 会静默掉回 GG**，而页面还在刷新前那张 TT 页 ⇒ 侧边栏、导航、路由守卫、筛选器全按 GG 算，
// 看着是 TT、实际是 GG。
export const PLATFORMS = ['gg', 'tt', 'fb']

/** localStorage 的键名（与 store 共用一个常量，避免两边写错字符串）。 */
export const PLATFORM_KEY = 'currentPlatform'

/** 白名单回落：非法值 / 缺失 / 非字符串一律 'gg'（脏值绝不进 store）。 */
export function sanitizePlatform(value) {
  return PLATFORMS.includes(value) ? value : 'gg'
}

/**
 * 水合（刷新后 / 换号后）时该用哪个平台。
 *
 * - **可切换平台的角色**（户管 / 开发者）：用存下来的值 —— 这正是本 bug 要修的：
 *   刷新不该改变你正在看的平台。
 * - **其余角色**：一律以 `user.platform` 为准，**无视存储**。理由是同一浏览器换号时，
 *   存储里可能还留着上一个人的平台；而这类角色的平台本来就由账号决定
 *   （与 store 的 `effectivePlatform` 同一口径）。
 */
export function platformOnHydrate({ stored, canSwitch, userPlatform }) {
  return canSwitch ? sanitizePlatform(stored) : sanitizePlatform(userPlatform)
}
