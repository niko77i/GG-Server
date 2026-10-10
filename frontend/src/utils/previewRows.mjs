// 大批量结果的「预览」纯逻辑（无 Vue 依赖，供 node --test 覆盖）。
//
// 扩展名必须是 .mjs —— package.json 没有 "type": "module"，.js 会被当 CJS 解析，
// node --test 会直接 SyntaxError（理由同 columnMapping.mjs / columnPrefsLogic.mjs）。
//
// 动机：Element Plus 的 el-table **不做虚拟滚动**，上万行直通会建几十万 DOM 节点、
// 把标签页搞崩（2026-10-11 实测 FB 户管看板一次同步产出 15035 行直接崩）。
// 三个函数各管一件事：
//   slicePreview   只渲染前 N 行（其余折叠，DOM 节点数封顶）
//   groupWarnings  把上千条重复警告按「原因 + 值」压成可读的几条
//   selectedIds    选中态用「全量 - 排除集」表示，这样「只渲染前 100 行」不会把
//                  另外几千行的勾选悄悄丢掉（默认全选 ⇒ 黑名单）

// 默认预览行数。够看清样本、又不会把 DOM 撑爆。
export const DEFAULT_PREVIEW_LIMIT = 100

// 只取前 limit 项用于渲染。返回 { shown, hiddenCount, total }：
//   shown       = 前 limit 项（新数组，绝不改入参）
//   hiddenCount = 被折叠的行数（永远 >= 0）
//   total       = 总数
// items 不是数组（含 undefined / null）⇒ 全空。limit <= 0 ⇒ 一行都不出、全部算隐藏
// （故 limit 先夹到 >= 0，负数不能再加回一个比 total 还大的 hiddenCount）。
export function slicePreview(items, limit = DEFAULT_PREVIEW_LIMIT) {
  const list = Array.isArray(items) ? items : []
  const total = list.length
  const raw = Number(limit)
  const eff = Number.isFinite(raw) ? Math.max(0, Math.floor(raw)) : 0
  const shown = list.slice(0, eff)
  return { shown, hiddenCount: Math.max(0, total - eff), total }
}

// 把警告按「原因 + 值」聚合：模板相同**且**捕获到的变量值序列相同才算一组。
//   · 每个「…」（左引号到右引号之间的任意字符）整体抽出来当变量，替换成「」得模板。
//     ⇒ 运营「张三」… 与 运营「李四」… 是**两条**（值不同，是不同的问题）
//     ⇒ 两条一模一样的 运营「张三」… 合成**一条，count=2**
//     ⇒ 无变量的文案（账户ID为空，跳过）模板即原文，相同原文归一组
// 返回数组，每项 { label, count, sampleRow, rows }：
//   label     该组第一条的 message 原文（保留真实值，供人读）
//   count     该组条数
//   sampleRow 该组第一条的 row
//   rows      该组的原始条目（供「展开看全部」）
// 排序：count 降序；count 相同则按该组首次出现的顺序（稳定）。
// warnings 不是数组 / 空 ⇒ []。不得修改入参。
export function groupWarnings(warnings) {
  if (!Array.isArray(warnings)) return []
  const groups = new Map()
  let seq = 0
  for (const w of warnings) {
    const message = String(w && w.message != null ? w.message : '')
    const values = []
    const template = message.replace(/「([^」]*)」/g, (_, v) => {
      values.push(v)
      return '「」'
    })
    // 分组键 = 模板 + 变量值序列。用 JSON 拼避免模板与值的边界歧义（值里可能带任何字符）。
    const key = JSON.stringify([template, values])
    let g = groups.get(key)
    if (!g) {
      g = { label: message, count: 0, sampleRow: w ? w.row : undefined, rows: [], _seq: seq++ }
      groups.set(key, g)
    }
    g.count += 1
    g.rows.push(w)
  }
  const out = [...groups.values()]
  out.sort((a, b) => (b.count - a.count) || (a._seq - b._seq))
  return out.map(({ label, count, sampleRow, rows }) => ({ label, count, sampleRow, rows }))
}

// 选中的权威表示 = 全量 id 数组 − 排除集（默认全选 ⇒ 黑名单）。
// 这样「只渲染前 100 行」只是少画了 DOM，另外几千行的选中态仍由 allIds − excludedIds 推出。
//   allIds 为空 / 非数组 ⇒ []
//   excludedIds 可为 Set / 数组 / null / undefined ⇒ 统一按集合处理
//   返回**新数组**，元素顺序与 allIds 一致；排除集里的陌生 id 静默忽略。
// 不得修改入参。
export function selectedIds(allIds, excludedIds) {
  if (!Array.isArray(allIds)) return []
  let excluded
  if (excludedIds instanceof Set) excluded = excludedIds
  else if (Array.isArray(excludedIds)) excluded = new Set(excludedIds)
  else excluded = new Set()
  return allIds.filter((id) => !excluded.has(id))
}
