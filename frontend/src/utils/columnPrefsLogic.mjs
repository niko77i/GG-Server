/**
 * 账户看板自定义列 —— 纯逻辑层。
 *
 * **扩展名是 .mjs 而非 .js，是刻意的**：package.json 没有 "type": "module"，
 * Node 会把 .js 当 CommonJS 解析，node --test 跑这个文件时会直接
 * SyntaxError（Vite 不在乎，但测试在乎）。改扩展名比给整个 frontend/
 * 加 "type": "module" 的波及面小得多。
 *
 * 设计见 docs/superpowers/specs/2026-10-08-account-column-prefs-design.md。
 * 这里刻意不 import Vue / Pinia / axios：顺序解析与显隐计算是本功能最容易出错
 * 的部分（新列策略、陈旧 key、角色闸门三方交织），抽成纯函数才能用 Node 内置的
 * 测试运行器覆盖。Pinia store 只是这些函数的一层薄封装。
 *
 * 术语
 *   registry  列注册表（数组），每项 { key, label, ...可 v-bind 的列属性, available? }
 *             available 是 (auth) => boolean，缺省视为恒真
 *   panelPref 服务端存的单面板配置 { order: string[], hidden: string[] }，可缺省
 *   order     该面板「全部列」的有序表，可见的与隐藏的都在里面
 *   hidden    order 中被用户隐藏的 key 子集
 */

/** 注册表数组 → key 数组。数组声明顺序即默认显示顺序。 */
export function registryKeys(registry) {
  return registry.map((col) => col.key)
}

/** key → 列属性。剔除 key 与 available，产物可直接 v-bind 到 el-table-column。 */
export function indexByKey(registry) {
  const out = {}
  for (const col of registry) {
    const { key, available, ...attrs } = col
    out[key] = attrs
  }
  return out
}

/**
 * isAvailable 是**权威判据**：它接收注册表里的一项，直接给出「该列对当前角色是否
 * 可见」的结论。列自身的 available 闸门（`(auth) => boolean`，缺省恒真）由调用方
 * （Pinia store）在构造 isAvailable 时折算进去 —— 例如 store 端是
 * `(col) => col.available ? col.available(auth) : true`。
 *
 * 之所以不在这里写 `!col.available || isAvailable(col)`：那是把 isAvailable 降级成
 * 「仅对带闸门的列生效的额外开关」，会让非闸门列永远无法被角色谓词挡掉，与
 * 「isAvailable 判断该列对当前角色是否可见」的约定冲突（测试里 gateOnly 谓词应能
 * 只放行带闸门的列）。
 */
function available(col, isAvailable) {
  return isAvailable(col)
}

/**
 * 解析出该面板的完整顺序表（含隐藏列）。顺序：
 *   1. 用户存过的 order；没有则用注册表默认顺序
 *   2. 剔除陈旧 key（代码里已不存在的列）与角色不可见的列
 *   3. 注册表里存在、但用户 order 里没有的**新列追加到末尾**
 *
 * 第 3 步就是「新列默认显示、追加到末尾」策略的落点。
 */
export function resolveOrder(panelPref, registry, isAvailable) {
  const cols = registry.filter((col) => available(col, isAvailable))
  const known = new Set(cols.map((col) => col.key))
  const base = Array.isArray(panelPref?.order) && panelPref.order.length
    ? panelPref.order
    : registryKeys(registry)

  const kept = base.filter((key) => known.has(key))
  const seen = new Set(kept)
  const appended = cols.map((col) => col.key).filter((key) => !seen.has(key))
  return [...kept, ...appended]
}

/** 实际渲染顺序 = 完整顺序减去 hidden。 */
export function resolveVisible(panelPref, registry, isAvailable) {
  const hidden = new Set(panelPref?.hidden ?? [])
  return resolveOrder(panelPref, registry, isAvailable).filter((key) => !hidden.has(key))
}

/** 净化为 { order, hidden }，hidden 按 order 排序并裁剪到 order 之内。 */
function normalize(panelPref, registry, isAvailable) {
  const order = resolveOrder(panelPref, registry, isAvailable)
  const hiddenSet = new Set(panelPref?.hidden ?? [])
  return { order, hidden: order.filter((key) => hiddenSet.has(key)) }
}

/** 勾选/取消勾选：只改 hidden，**不动 order**，所以再勾回来会回到原位而非末尾。 */
export function applyToggle(panelPref, registry, isAvailable, key, checked) {
  const { order, hidden } = normalize(panelPref, registry, isAvailable)
  const set = new Set(hidden)
  if (checked) set.delete(key)
  else set.add(key)
  return { order, hidden: order.filter((k) => set.has(k)) }
}

/** 拖拽调序：fromIndex / toIndex 是完整顺序表里的下标。越界则原样返回。 */
export function applyMove(panelPref, registry, isAvailable, fromIndex, toIndex) {
  const { order, hidden } = normalize(panelPref, registry, isAvailable)
  if (fromIndex === toIndex || fromIndex < 0 || toIndex < 0 ||
      fromIndex >= order.length || toIndex >= order.length) {
    return { order, hidden }
  }
  const next = [...order]
  const [moved] = next.splice(fromIndex, 1)
  next.splice(toIndex, 0, moved)
  return { order: next, hidden }
}

/**
 * 取消勾选 key 是否会导致一个可见列都不剩。
 * 会的话 UI 应该拦下 —— 只剩选择框和「操作」列的表格看着像坏了。
 */
export function isOnlyVisible(panelPref, registry, isAvailable, key) {
  const visible = resolveVisible(panelPref, registry, isAvailable)
  return visible.length === 1 && visible[0] === key
}
