// 「读表头」响应 ↔ 列映射下拉行状态 的纯换算（无 Vue 依赖，供 node --test 覆盖）。
//
// 扩展名必须是 .mjs —— package.json 没有 "type": "module"，.js 会被当 CJS 解析，
// node --test 会直接 SyntaxError（理由同 columnPrefsLogic.mjs）。
//
// 三值约定（与后端设计 §3.3 一一对应）：
//   字段key → 采集到该字段（写进 columns）
//   ""      → 刻意不采集（写进 columns，值空串；解析时既不映射也不上报）
//   null    → **不写覆盖**：未识别列的默认态。必须与 "" 分开 —— 若把未识别列的默认态
//             写成空串，等于替用户声明了「刻意不采集」，同步报告的「未采集」提示会消失。
export function rowsFromColumns(columns) {
  return (columns || []).map((c) => {
    const auto = c.via === 'none' ? null : (c.field ?? '')
    return { header: c.header, via: c.via, auto, selected: auto, touched: false }
  })
}

// 组装要保存的 columns：只认「用户碰过」的行（touched），没碰过的一个键都不动 ——
// 包括既有覆盖（打开面板看一眼不该把它撤掉），以及表头里还没有的键。
export function columnsFromRows(rows, existing) {
  const out = { ...(existing || {}) }
  for (const r of rows || []) {
    if (!r.touched) continue
    if (r.selected === r.auto) delete out[r.header]   // 改回自动 ⇒ 撤掉覆盖
    else if (r.selected !== null) out[r.header] = r.selected
  }
  return out
}
