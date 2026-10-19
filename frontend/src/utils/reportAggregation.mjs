/**
 * 数据管理页（GG / FB）的「按可见维度列自动聚合」与「父子列联动」纯逻辑。
 *
 * 两个页面共用本模块，差异全部由 cfg 描述：
 *
 *   cfg = {
 *     columns: [{ prop, role: 'dimension' | 'metric' }, ...],  // 声明顺序 = 展示顺序
 *     defaultVisible: [prop, ...],
 *     links: [{ parent, child }, ...],                         // 勾父必带子
 *   }
 *
 * 规则（设计文档 §3 / §5.1）：
 * - 可见维度数 < 维度总数 ⇒ 自动聚合（除非用户点了「放弃聚合」）；
 * - 勾父列 ⇒ 自动勾子列；取消父列 ⇒ 同时取消子列；
 * - 子列不能脱离父列单独存在（UI 层另有 disabled，本模块兜底）。
 *
 * 运行测试：cd frontend && npm test
 */

function dimensionProps(cfg) {
  return cfg.columns.filter(c => c.role === 'dimension').map(c => c.prop)
}

/** 当前可见的维度列，按 cfg 声明顺序返回。 */
export function visibleDimensions(visibleProps, cfg) {
  const visible = new Set(visibleProps || [])
  return dimensionProps(cfg).filter(p => visible.has(p))
}

/** 是否应进入聚合视图（用户点了「放弃聚合」时为 false）。 */
export function isAggregating(visibleProps, cfg, aggregationOff = false) {
  if (aggregationOff) return false
  return visibleDimensions(visibleProps, cfg).length < dimensionProps(cfg).length
}

/** 某列是否为「子列且父列未勾选」—— UI 用它决定 checkbox 的 disabled。 */
export function childDisabled(prop, visibleProps, cfg) {
  const link = (cfg.links || []).find(l => l.child === prop)
  if (!link) return false
  return !(visibleProps || []).includes(link.parent)
}

/**
 * 勾选/取消一列后的可见列集合（含父子联动），按 cfg 声明顺序返回。
 * 返回空数组是合法的（与 GG 页现有行为一致：允许全部取消）。
 */
export function applyLinkage(visibleProps, prop, checked, cfg) {
  const known = new Set(cfg.columns.map(c => c.prop))
  const next = new Set((visibleProps || []).filter(p => known.has(p)))
  const asParent = (cfg.links || []).find(l => l.parent === prop)
  const asChild = (cfg.links || []).find(l => l.child === prop)

  if (checked) {
    next.add(prop)
    if (asParent) next.add(asParent.child)   // 勾父 ⇒ 子跟随
    if (asChild) next.add(asChild.parent)     // 勾子 ⇒ 父必须在（兜底）
  } else {
    next.delete(prop)
    if (asParent) next.delete(asParent.child) // 取消父 ⇒ 子一起取消
  }
  return cfg.columns.map(c => c.prop).filter(p => next.has(p))
}

/**
 * 读取 localStorage 偏好后的归一化：
 * - 过滤掉已不存在的列；
 * - 含子列但缺父列 ⇒ 自动补上父列（保留用户想看子列的意图）；
 * - 结果为空 ⇒ 回落默认可见列。
 */
export function normalizePrefs(savedProps, cfg) {
  const known = new Set(cfg.columns.map(c => c.prop))
  const set = new Set(Array.isArray(savedProps) ? savedProps.filter(p => known.has(p)) : [])
  for (const { parent, child } of (cfg.links || [])) {
    if (set.has(child)) set.add(parent)
  }
  const ordered = cfg.columns.map(c => c.prop).filter(p => set.has(p))
  return ordered.length ? ordered : [...cfg.defaultVisible]
}
